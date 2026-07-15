from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.enums import Market, Source
from app.parsers.avenue import parse_avenue_csv
from app.parsers.base import ParseError, ParseResult
from app.parsers.binance import convert_usdt_to_brl, parse_binance_xlsx
from app.parsers.cei import parse_cei_xlsx
from app.schemas.imports import ImportResultOut, ImportWarningOut, SkippedRowOut
from app.services.fx import get_usd_brl
from app.services.importer import import_transactions
from app.services.lending import (
    CONFIRMED_TRADES,
    load_contracts,
    parse_lending_export_xlsx,
    reconcile,
    store_reference_events,
)

router = APIRouter(prefix="/imports")


def _run_import(
    content: bytes, parser, db: Session, source: Source, market: Market, currency: str
) -> ImportResultOut:
    try:
        result: ParseResult = parser(content)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    summary = import_transactions(
        db, result.transactions, source=source, market=market, currency=currency
    )
    return ImportResultOut(
        imported=summary.imported,
        duplicates=summary.duplicates,
        skipped=[
            SkippedRowOut(row=s.row, movement_type=s.movement_type, reason=s.reason)
            for s in result.skipped
        ],
        warnings=_warnings_out(result),
    )


def _warnings_out(result: ParseResult) -> list[ImportWarningOut]:
    return [
        ImportWarningOut(
            row=w.row,
            ticker=w.ticker,
            date=w.date,
            quantity=w.quantity,
            message=w.message,
        )
        for w in result.warnings
    ]


def _require_extension(file: UploadFile, extension: str, expected: str) -> None:
    if file.filename and not file.filename.lower().endswith(extension):
        raise HTTPException(
            status_code=422, detail=f"Envie o arquivo {extension} de {expected}."
        )


@router.post("/cei", response_model=ImportResultOut, response_model_exclude_none=True)
async def import_cei(file: UploadFile, db: Session = Depends(get_db)) -> ImportResultOut:
    _require_extension(file, ".xlsx", "Movimentação da B3")
    content = await file.read()
    try:
        result = parse_cei_xlsx(content)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Lending reconciliation (design doc §3.2/§3.8): with reference events
    # loaded via the "B3 — Empréstimos" import, custody legs are classified
    # and dropped BEFORE import, so lending churn never enters as trades and
    # the blanket warnings collapse to the genuinely undecidable cases. With
    # an empty lending_events table this is a no-op and the parser's
    # fail-loud warnings pass through unchanged.
    contracts = load_contracts(db)
    if contracts:
        result, _stats = reconcile(result, contracts, CONFIRMED_TRADES)

    summary = import_transactions(
        db, result.transactions, source=Source.cei, market=Market.br, currency="BRL"
    )
    return ImportResultOut(
        imported=summary.imported,
        duplicates=summary.duplicates,
        skipped=[
            SkippedRowOut(row=s.row, movement_type=s.movement_type, reason=s.reason)
            for s in result.skipped
        ],
        warnings=_warnings_out(result),
    )


@router.post("/binance", response_model=ImportResultOut, response_model_exclude_none=True)
async def import_binance(file: UploadFile, db: Session = Depends(get_db)) -> ImportResultOut:
    _require_extension(file, ".xlsx", "Spot Trade/Order History da Binance")
    content = await file.read()
    try:
        result = parse_binance_xlsx(content)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Order History rows priced in USDT need the day's USD/BRL (PTAX) to land
    # a BRL cost basis; raise rather than silently mispricing if FX is missing.
    if any(tx.currency == "USDT" for tx in result.transactions):
        convert_usdt_to_brl(result.transactions, _usd_brl_fetcher(db))

    summary = import_transactions(
        db, result.transactions, source=Source.binance, market=Market.crypto, currency="BRL"
    )
    return ImportResultOut(
        imported=summary.imported,
        duplicates=summary.duplicates,
        skipped=[
            SkippedRowOut(row=s.row, movement_type=s.movement_type, reason=s.reason)
            for s in result.skipped
        ],
        warnings=_warnings_out(result),
    )


def _usd_brl_fetcher(db: Session):
    def fetch(on):
        fx = get_usd_brl(db, on)
        if fx is None:
            raise HTTPException(
                status_code=502,
                detail=f"USD/BRL (PTAX) indisponível para {on}; não é possível "
                "converter ordens em USDT para BRL.",
            )
        return fx.rate

    return fetch


@router.post("/avenue", response_model=ImportResultOut, response_model_exclude_none=True)
async def import_avenue(file: UploadFile, db: Session = Depends(get_db)) -> ImportResultOut:
    _require_extension(file, ".csv", "extrato da Avenue")
    content = await file.read()
    return _run_import(content, parse_avenue_csv, db, Source.avenue, Market.us, "USD")


@router.post("/lending-events", response_model=ImportResultOut, response_model_exclude_none=True)
async def import_lending_events(
    file: UploadFile, db: Session = Depends(get_db)
) -> ImportResultOut:
    """Filtered B3 Movimentação exports for the lending reconciler.

    `Empréstimo`/`Atualização` rows become reference data in the
    lending_events table (no import_hash — they are classification context,
    not portfolio facts); `Reembolso` rows are real income and import as
    normal `yield_` transactions. Idempotency: reimporting adds nothing; a
    newer export only extends the timeline (design doc §3.8).
    """
    _require_extension(file, ".xlsx", 'Movimentação filtrada da B3 (filtro "Outros")')
    content = await file.read()
    try:
        parse = parse_lending_export_xlsx(content)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    added = store_reference_events(db, parse.events)
    summary = import_transactions(
        db, parse.reembolsos, source=Source.cei, market=Market.br, currency="BRL"
    )
    return ImportResultOut(
        imported=summary.imported,
        duplicates=summary.duplicates,
        skipped=[
            SkippedRowOut(row=s.row, movement_type=s.movement_type, reason=s.reason)
            for s in parse.skipped
        ],
        warnings=[],
        events_added=added,
        events_known=len(parse.events) - added,
    )
