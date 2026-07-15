"""Manual transactions: create, edit, delete.

Only `manual` transactions can be edited or deleted. Imported rows are
owned by their source file: deleting one would silently come back on the
next reimport, and editing one would desynchronize it from the file.
Corrections to imported data are expressed as additional manual
transactions (e.g. a cross-ticker conversion carrying cost).
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.enums import AssetClass, Market, Operation, Source
from app.models.transaction import Transaction
from app.schemas.transactions import TransactionIn, TransactionListOut, TransactionOut
from app.services.importer import compute_import_hash
from app.services.portfolio import compute_positions

router = APIRouter(prefix="/transactions")

SORT_COLUMNS = {
    "date": Transaction.date,
    "ticker": Transaction.ticker,
    "operation": Transaction.operation,
    "total_value": Transaction.total_value,
    "source": Transaction.source,
}


@router.get("", response_model=TransactionListOut)
def list_transactions(
    ticker: str | None = None,
    source: Source | None = None,
    operation: Operation | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "date",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> TransactionListOut:
    limit = max(1, min(limit, 200))
    query = select(Transaction)
    if ticker:
        query = query.where(Transaction.ticker.ilike(f"%{ticker.strip()}%"))
    if source is not None:
        query = query.where(Transaction.source == source)
    if operation is not None:
        query = query.where(Transaction.operation == operation)
    if date_from is not None:
        query = query.where(Transaction.date >= date_from)
    if date_to is not None:
        query = query.where(Transaction.date <= date_to)

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    column = SORT_COLUMNS.get(sort, Transaction.date)
    primary = column.asc() if order == "asc" else column.desc()
    items = (
        db.execute(
            # created_at breaks ties deterministically across pages.
            query.order_by(primary, Transaction.created_at.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
        .scalars()
        .all()
    )
    return TransactionListOut(items=items, total=total)


def _unique_manual_hash(
    db: Session, payload: TransactionIn, exclude_id: str | None = None
) -> str:
    # Same formula as file imports; seq is bumped until the hash is free so
    # intentionally identical manual entries can coexist.
    seq = 0
    while True:
        import_hash = compute_import_hash(
            Source.manual,
            payload.date,
            payload.ticker,
            payload.operation,
            payload.quantity,
            payload.unit_price,
            seq,
        )
        query = select(Transaction.id).where(Transaction.import_hash == import_hash)
        if exclude_id is not None:
            query = query.where(Transaction.id != exclude_id)
        if db.execute(query).first() is None:
            return import_hash
        seq += 1


def _normalize_custody_transfer(
    db: Session, payload: TransactionIn, exclude_id: str | None = None
) -> TransactionIn:
    """Validate a custody transfer and force its derived/irrelevant fields.

    A custody move has no price, no realized P&L and no asset metadata to
    type: it is always crypto, quantity-only, with distinct origin/destination
    custodies. The quantity must fit the origin's balance on that date.
    """
    if payload.operation is not Operation.custody_transfer:
        return payload

    src, dst = payload.custody_from, payload.custody_to
    if src is None or dst is None:
        raise HTTPException(
            status_code=422,
            detail="Transferência de custódia exige custódia de origem e destino.",
        )
    if src == dst:
        raise HTTPException(
            status_code=422,
            detail="Custódia de origem e destino devem ser diferentes.",
        )
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=422, detail="Quantidade transferida deve ser positiva."
        )

    available = _custody_balance(db, payload.ticker, src, payload.date, exclude_id)
    if payload.quantity > available:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Saldo insuficiente: {payload.ticker} tem {available:f} em "
                f"{src.value}, menor que {payload.quantity:f}."
            ),
        )

    # Custody moves carry no price/cost; metadata is fixed to crypto.
    return payload.model_copy(
        update={
            "asset_class": AssetClass.crypto,
            "market": Market.crypto,
            "custody": None,
            "unit_price": Decimal("0"),
            "fees": Decimal("0"),
            "total_value": Decimal("0"),
            "indexer": None,
        }
    )


def _custody_balance(
    db: Session,
    ticker: str,
    custody,
    on: date,
    exclude_id: str | None,
) -> Decimal:
    rows = (
        db.execute(
            select(Transaction).where(
                Transaction.ticker == ticker, Transaction.date <= on
            )
        )
        .scalars()
        .all()
    )
    if exclude_id is not None:
        rows = [r for r in rows if r.id != exclude_id]
    computed = compute_positions(rows)
    position = computed.positions.get((ticker, custody))
    return position.quantity if position is not None else Decimal("0")


def _apply_payload(transaction: Transaction, payload: TransactionIn) -> None:
    transaction.date = payload.date
    transaction.ticker = payload.ticker
    transaction.asset_name = payload.asset_name
    transaction.asset_class = payload.asset_class
    transaction.market = payload.market
    transaction.institution = payload.institution
    transaction.custody = payload.custody
    transaction.custody_from = payload.custody_from
    transaction.custody_to = payload.custody_to
    transaction.indexer = payload.indexer
    transaction.currency = payload.currency
    transaction.operation = payload.operation
    transaction.quantity = payload.quantity
    transaction.unit_price = payload.unit_price
    transaction.fees = payload.fees
    if payload.total_value is not None:
        total_value = payload.total_value
    else:
        # `or` normalizes Decimal("-0") (negative quantity at price 0).
        total_value = payload.quantity * payload.unit_price or Decimal("0")
    transaction.total_value = total_value
    transaction.notes = payload.notes


def _get_manual(db: Session, transaction_id: str) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transação não encontrada.")
    if transaction.source is not Source.manual:
        raise HTTPException(
            status_code=409,
            detail=(
                "Apenas transações manuais podem ser editadas ou excluídas; "
                "linhas importadas voltariam no próximo reimport do arquivo."
            ),
        )
    return transaction


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(
    payload: TransactionIn, db: Session = Depends(get_db)
) -> Transaction:
    payload = _normalize_custody_transfer(db, payload)
    transaction = Transaction(
        source=Source.manual,
        import_hash=_unique_manual_hash(db, payload),
    )
    _apply_payload(transaction, payload)
    db.add(transaction)
    db.commit()
    return transaction


@router.put("/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: str, payload: TransactionIn, db: Session = Depends(get_db)
) -> Transaction:
    transaction = _get_manual(db, transaction_id)
    payload = _normalize_custody_transfer(db, payload, exclude_id=transaction_id)
    transaction.import_hash = _unique_manual_hash(db, payload, exclude_id=transaction_id)
    _apply_payload(transaction, payload)
    db.commit()
    return transaction


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: str, db: Session = Depends(get_db)) -> None:
    transaction = _get_manual(db, transaction_id)
    db.delete(transaction)
    db.commit()
