from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.enums import AssetClass, Market, Operation
from app.models.transaction import Transaction
from app.schemas.portfolio import (
    CapmOut,
    CapmSegmentOut,
    ContributionMonthOut,
    ContributionsOut,
    CorrelationOut,
    HistoryPointOut,
    PerformanceOut,
    PerformancePointOut,
    PortfolioHistoryOut,
    PortfolioOut,
    PositionOut,
    ReturnPointOut,
    ReturnSeriesOut,
    ReturnsOut,
    SegmentOut,
    SegmentSummaryOut,
    UsdBrlMarketOut,
)
from app.services.assets import get_asset_meta
from app.services.benchmarks import build_performance
from app.services.capm import build_capm
from app.services.correlation import build_correlation
from app.services.fx import FxResult, get_usd_brl
from app.services.history import Granularity, build_patrimony_history
from app.services.portfolio import Position, compute_positions
from app.services.quotes import (
    get_crypto_usd_quote,
    get_previous_close,
    get_quote,
    get_usdbrl_market_rate,
)
from app.services.usd import FxUnavailable, to_usd_transactions
from app.services.indexer import resolve_indexer
from app.services.returns import build_returns
from app.services.segments import SegmentRow, aggregate_segments, segment_of
from app.services.tesouro import parse_bond_ticker

router = APIRouter(prefix="/portfolio")

ZERO = Decimal("0")
CENTS = Decimal("0.01")


@router.get("/history", response_model=PortfolioHistoryOut)
def get_portfolio_history(
    granularity: Granularity = "daily", db: Session = Depends(get_db)
) -> PortfolioHistoryOut:
    result = build_patrimony_history(db, granularity)
    return PortfolioHistoryOut(
        points=[
            HistoryPointOut(
                date=p.date,
                total_brl=_cents(p.total_brl),
                twr_index=p.twr_index.quantize(Decimal("0.0001")),
            )
            for p in result.points
        ],
        warnings=result.warnings,
    )


@router.get("/contributions", response_model=ContributionsOut)
def get_portfolio_contributions(
    months: int = 24, db: Session = Depends(get_db)
) -> ContributionsOut:
    """Monthly contributions (buys), sales and income, in BRL.

    USD rows (Avenue) are converted by the PTAX of each transaction's own
    date — same get_usd_brl source the USD cost basis uses — never today's
    rate. A date with no FX available excludes that row from the sum (the
    same silent fallback _income_ytd applies) instead of failing the call.
    """
    months = max(1, min(months, 120))
    today = datetime.now(timezone.utc).date()
    start_year = today.year - (months - 1 + today.month - 1) // 12
    start_month = (today.month - 1 - (months - 1)) % 12 + 1
    start = date(start_year, start_month, 1)

    buckets: dict[str, dict[str, Decimal]] = {}
    cursor_year, cursor_month = start.year, start.month
    for _ in range(months):
        buckets[f"{cursor_year:04d}-{cursor_month:02d}"] = {
            "aportes": ZERO,
            "vendas": ZERO,
            "rendimentos": ZERO,
        }
        cursor_month += 1
        if cursor_month > 12:
            cursor_month = 1
            cursor_year += 1

    # One PTAX lookup per distinct date (the exchange_rates table is the
    # backing cache); None is memoized too so a missing date is not retried
    # per row.
    rates: dict[date, Decimal | None] = {}

    def to_brl(amount: Decimal, tx: Transaction) -> Decimal | None:
        if tx.currency == "BRL":
            return amount
        if tx.currency != "USD":
            return None  # no FX source for other currencies (matches _to_brl)
        if tx.date not in rates:
            fx = get_usd_brl(db, tx.date)
            rates[tx.date] = fx.rate if fx is not None else None
        rate = rates[tx.date]
        return amount * rate if rate is not None else None

    transactions = db.execute(
        select(Transaction).where(Transaction.date >= start)
    ).scalars().all()
    for tx in transactions:
        bucket = buckets.get(f"{tx.date.year:04d}-{tx.date.month:02d}")
        if bucket is None:
            continue
        fees = tx.fees or ZERO
        if tx.operation is Operation.buy:
            value = to_brl((tx.total_value or ZERO) + fees, tx)
        elif tx.operation is Operation.sell:
            value = to_brl((tx.total_value or ZERO) - fees, tx)
        elif tx.operation in INCOME_OPS:
            value = to_brl(tx.total_value or ZERO, tx)
        else:
            continue
        if value is None:
            continue
        if tx.operation is Operation.buy:
            bucket["aportes"] += value
        elif tx.operation is Operation.sell:
            bucket["vendas"] += value
        else:
            bucket["rendimentos"] += value

    return ContributionsOut(
        months=[
            ContributionMonthOut(
                month=month,
                aportes=_cents(values["aportes"]),
                vendas=_cents(values["vendas"]),
                rendimentos=_cents(values["rendimentos"]),
            )
            for month, values in buckets.items()
        ]
    )


@router.get("/performance", response_model=PerformanceOut)
def get_portfolio_performance(
    granularity: Granularity = "daily", db: Session = Depends(get_db)
) -> PerformanceOut:
    result = build_performance(db, granularity)
    index = Decimal("0.0001")

    def fmt(value: Decimal | None) -> Decimal | None:
        return value.quantize(index) if value is not None else None

    return PerformanceOut(
        points=[
            PerformancePointOut(
                date=p.date,
                carteira=p.portfolio.quantize(index),
                cdi=fmt(p.benchmarks.get("cdi")),
                ibov=fmt(p.benchmarks.get("ibov")),
                sp500=fmt(p.benchmarks.get("sp500")),
                btc=fmt(p.benchmarks.get("btc")),
            )
            for p in result.points
        ],
        warnings=result.warnings,
    )


@router.get("/returns", response_model=ReturnsOut)
def get_portfolio_returns(
    segments: str = "total",
    benchmarks: str = "",
    period: str = "MAX",
    currency: str = "BRL",
    db: Session = Depends(get_db),
) -> ReturnsOut:
    """Cumulative return (TWR) per segment and optional benchmarks, each
    rebased to 0% at the start of the requested period. `segments` and
    `benchmarks` are comma-separated keys (total,br,us,crypto,rf and
    cdi,ibov,sp500,btc). `currency=USD` values the EUA/Cripto segments in
    dollars (return in the asset's native currency)."""
    seg_keys = [s for s in segments.split(",") if s.strip()]
    bm_keys = [b for b in benchmarks.split(",") if b.strip()]
    result = build_returns(db, seg_keys, bm_keys, period, currency)
    pct = Decimal("0.0001")

    return ReturnsOut(
        period=result.period,
        start=result.start,
        series=[
            ReturnSeriesOut(
                key=s.key,
                label=s.label,
                kind=s.kind,
                points=[
                    ReturnPointOut(
                        date=p.date,
                        return_pct=(
                            p.return_pct.quantize(pct)
                            if p.return_pct is not None
                            else None
                        ),
                    )
                    for p in s.points
                ],
            )
            for s in result.series
        ],
        warnings=result.warnings,
    )


@router.get("/correlation", response_model=CorrelationOut)
def get_portfolio_correlation(
    period: str = "1A",
    segment: str | None = None,
    db: Session = Depends(get_db),
) -> CorrelationOut:
    """Correlation matrix of daily returns between the portfolio's priced
    assets, from cached closes. `segment` optionally narrows to br/us/
    crypto."""
    result = build_correlation(db, period, segment)
    return CorrelationOut(
        period=result.period,
        segment=result.segment,
        tickers=result.tickers,
        matrix=result.matrix,
        warnings=result.warnings,
    )


@router.get("/capm", response_model=CapmOut)
def get_portfolio_capm(
    period: str = "1A",
    db: Session = Depends(get_db),
) -> CapmOut:
    """CAPM metrics (beta, annualised Jensen alpha, Pearson correlation) per
    segment, against each segment's benchmark and risk-free, over a window
    (6M/1A/2A/MAX). Every coefficient carries its benchmark/risk-free/period/
    frequency labels so no figure is shown without its assumptions."""
    result = build_capm(db, period)
    return CapmOut(
        period=result.period,
        period_label=result.period_label,
        frequency=result.frequency,
        segments=[
            CapmSegmentOut(
                key=m.key,
                label=m.label,
                benchmark_label=m.benchmark_label,
                risk_free_label=m.risk_free_label,
                period=m.period,
                period_label=m.period_label,
                frequency=m.frequency,
                beta=m.beta,
                alpha_annual_pct=m.alpha_annual_pct,
                correlation=m.correlation,
                observations=m.observations,
                note=m.note,
                warnings=m.warnings,
            )
            for m in result.segments
        ],
        warnings=result.warnings,
    )


@router.get("", response_model=PortfolioOut)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioOut:
    transactions = db.execute(select(Transaction)).scalars().all()
    computed = compute_positions(transactions)
    warnings = list(computed.warnings)
    open_positions = sorted(
        (p for p in computed.positions.values() if p.is_open),
        key=lambda p: (p.ticker, p.custody.value if p.custody else ""),
    )

    # FX is fetched lazily, at most once per request, only if some value
    # needs conversion to BRL.
    fx: FxResult | None = None
    fx_attempted = False

    def usd_rate() -> FxResult | None:
        nonlocal fx, fx_attempted
        if not fx_attempted:
            fx_attempted = True
            fx = get_usd_brl(db, datetime.now(timezone.utc).date())
        return fx

    positions_out: list[PositionOut] = []
    total = ZERO
    total_day_change = ZERO
    any_day_change = False
    segment_totals: dict[Market, Decimal] = {}
    segment_counts: dict[Market, int] = {}
    segment_rows: list[SegmentRow] = []
    for position in open_positions:
        out = _build_position(db, position, usd_rate, warnings)
        positions_out.append(out)
        segment_counts[out.market] = segment_counts.get(out.market, 0) + 1
        if out.market_value_brl is not None:
            total += out.market_value_brl
            segment_totals[out.market] = (
                segment_totals.get(out.market, ZERO) + out.market_value_brl
            )
        if out.day_change_brl is not None:
            total_day_change += out.day_change_brl
            any_day_change = True
        key = segment_of(out.market, out.asset_class)
        if key is not None:
            # FX already attempted for the market value above; convert cost
            # without re-warning (a throwaway sink).
            cost_brl = _to_brl(out.total_cost, out.currency, usd_rate, [], out.ticker)
            segment_rows.append(SegmentRow(key, out.market_value_brl, cost_brl))

    previous_total = total - total_day_change
    day_change_pct = (
        total_day_change / previous_total
        if any_day_change and previous_total > 0
        else None
    )

    usd_segment_totals = _apply_usd_view(db, transactions, positions_out, warnings)

    return PortfolioOut(
        total_market_value_brl=_cents(total),
        day_change_brl=_cents(total_day_change) if any_day_change else None,
        day_change_pct=(
            day_change_pct.quantize(Decimal("0.000001"))
            if day_change_pct is not None
            else None
        ),
        income_ytd_brl=_cents(_income_ytd(db, transactions)),
        segments=[
            SegmentOut(
                market=market,
                total_brl=_cents(segment_totals.get(market, ZERO)),
                position_count=count,
            )
            for market, count in sorted(
                segment_counts.items(), key=lambda kv: kv[0].value
            )
        ],
        segment_summaries=[
            _segment_summary_out(summary, usd_segment_totals)
            for summary in aggregate_segments(segment_rows)
        ],
        usd_brl_rate=fx.rate if fx else None,
        usd_brl_date=fx.rate_date if fx else None,
        fx_stale=fx.stale if fx else False,
        positions=positions_out,
        warnings=warnings,
    )


@router.get("/usdbrl-market", response_model=UsdBrlMarketOut)
def get_usdbrl_market(db: Session = Depends(get_db)) -> UsdBrlMarketOut:
    """Commercial (delayed) USD/BRL market quote for the EUA page header.

    This is the market dollar, not the PTAX used in the portfolio cost basis.
    On a fetch failure the last cached value is returned with stale=True, or an
    empty payload if nothing was ever cached."""
    result = get_usdbrl_market_rate(db)
    if result is None:
        return UsdBrlMarketOut(stale=True)
    return UsdBrlMarketOut(
        rate=result.price,
        quote_date=result.quote_date,
        fetched_at=result.fetched_at,
        source=result.source,
        stale=result.stale,
    )


def _apply_usd_view(
    db: Session,
    transactions: list[Transaction],
    positions_out: list[PositionOut],
    warnings: list[str],
) -> dict[str, dict[str, Decimal]]:
    """Fill the USD fields of the EUA/Cripto positions and return per-segment
    USD totals (market value + cost) for the section summaries.

    EUA is USD-native (the existing fields are already USD). Cripto cost is
    recomputed in USD via each transaction's PTAX; its market value uses the
    Binance USDT quote.
    """
    totals: dict[str, dict[str, Decimal]] = {}

    def acc(seg: str, mv: Decimal | None, cost: Decimal) -> None:
        bucket = totals.setdefault(seg, {"mv": ZERO, "cost": ZERO, "priced": ZERO})
        bucket["cost"] += cost
        if mv is not None:
            bucket["mv"] += mv
            bucket["priced"] += 1

    # Crypto USD cost basis: reprice every crypto buy/sell by its date's PTAX.
    usd_positions: dict[tuple, Position] = {}
    try:
        usd_positions = compute_positions(
            to_usd_transactions(db, transactions)
        ).positions
    except FxUnavailable as exc:
        warnings.append(f"Seção em USD indisponível: {exc}")
        return totals

    for out in positions_out:
        if out.market is Market.us:
            out.usd_average_price = out.average_price
            out.usd_total_cost = out.total_cost
            out.usd_market_value = out.market_value
            out.usd_unrealized_pnl = out.unrealized_pnl
            acc("us", out.market_value, out.total_cost)
        elif out.market is Market.crypto:
            upos = usd_positions.get((out.ticker, out.custody))
            quote = get_crypto_usd_quote(db, out.ticker, live=False)
            if upos is not None:
                out.usd_average_price = upos.average_price
                out.usd_total_cost = upos.total_cost
                if quote is not None:
                    out.usd_market_value = (out.quantity * quote.price).quantize(CENTS)
                    out.usd_unrealized_pnl = (
                        out.usd_market_value - upos.total_cost
                    ).quantize(CENTS)
                acc("crypto", out.usd_market_value, upos.total_cost)
    return totals


def _segment_summary_out(summary, usd_totals: dict[str, dict[str, Decimal]]):
    base = vars(summary)
    bucket = usd_totals.get(summary.key)
    if bucket is None:
        return SegmentSummaryOut(**base)
    mv, cost = bucket["mv"], bucket["cost"]
    pnl = mv - cost
    pct = (pnl / cost) if cost > 0 else None
    return SegmentSummaryOut(
        **base,
        display_currency="USD",
        usd_total=mv.quantize(CENTS),
        usd_cost=cost.quantize(CENTS),
        usd_unrealized_pnl=pnl.quantize(CENTS),
        usd_pnl_pct=pct.quantize(Decimal("0.000001")) if pct is not None else None,
    )


def _build_position(
    db: Session,
    position: Position,
    usd_rate: Callable[[], FxResult | None],
    warnings: list[str],
) -> PositionOut:
    meta = get_asset_meta(db, position.ticker, position.market, position.asset_class)
    indexer = (
        resolve_indexer(position.ticker, position.asset_name, position.indexer)
        if position.asset_class is AssetClass.fixed_income
        else None
    )
    base = dict(
        ticker=position.ticker,
        asset_name=position.asset_name,
        asset_class=position.asset_class,
        market=position.market,
        institution=position.institution,
        custody=position.custody,
        indexer=indexer,
        sector=meta.sector,
        country=meta.country,
        currency=position.currency,
        quantity=position.quantity,
        average_price=position.average_price,
        total_cost=position.total_cost,
        realized_pnl=position.realized_pnl,
        income=position.income,
    )

    quote = get_quote(
        db, position.ticker, position.market, position.asset_class, live=False
    )
    if quote is None:
        if position.asset_class is not AssetClass.fixed_income:
            warnings.append(
                f"{position.ticker}: no quote available; position valued at cost"
            )
        elif parse_bond_ticker(position.ticker) is not None:
            # A Tesouro Direto bond we could not price (source down or no
            # match); private fixed income is expected to stay at cost.
            warnings.append(
                f"{position.ticker}: título do Tesouro sem preço na fonte; "
                "valorado a custo"
            )
        market_value_brl = _to_brl(
            position.total_cost, position.currency, usd_rate, warnings, position.ticker
        )
        return PositionOut(
            **base,
            priced=False,
            market_value_brl=_cents(market_value_brl),
        )

    market_value = position.quantity * quote.price
    market_value_brl = _to_brl(
        market_value, quote.currency, usd_rate, warnings, position.ticker
    )
    # Unrealized P&L only makes sense when quote and cost share a currency
    # (e.g. crypto bought with USDT is quoted in BRL by Binance).
    unrealized = (
        market_value - position.total_cost
        if quote.currency == position.currency
        else None
    )

    day_change_brl: Decimal | None = None
    day_change_pct: Decimal | None = None
    previous_close = get_previous_close(db, position.ticker, quote.quote_date)
    if previous_close is not None and previous_close > 0:
        change = position.quantity * (quote.price - previous_close)
        day_change_brl = _to_brl(
            change, quote.currency, usd_rate, warnings, position.ticker
        )
        day_change_pct = (quote.price - previous_close) / previous_close

    return PositionOut(
        **base,
        priced=True,
        quote_price=quote.price,
        quote_currency=quote.currency,
        quote_date=quote.quote_date,
        quote_fetched_at=quote.fetched_at,
        quote_stale=quote.stale,
        market_value=_cents(market_value),
        market_value_brl=_cents(market_value_brl),
        unrealized_pnl=_cents(unrealized),
        day_change_brl=_cents(day_change_brl),
        day_change_pct=(
            day_change_pct.quantize(Decimal("0.000001"))
            if day_change_pct is not None
            else None
        ),
    )


INCOME_OPS = (Operation.dividend, Operation.jcp, Operation.yield_)


def _income_ytd(db: Session, transactions: list[Transaction]) -> Decimal:
    """Income received since January 1st of the current year, in BRL.

    USD income (Avenue) converts at the PTAX of each payment's own date —
    the same get_usd_brl source and per-date convention the contributions
    endpoint uses — never today's rate. One lookup per distinct date
    (memoized, None included); a date with no FX available silently
    excludes that payment from the sum, matching contributions.
    """
    year_start = date(datetime.now(timezone.utc).year, 1, 1)
    rates: dict[date, Decimal | None] = {}
    total = ZERO
    for tx in transactions:
        if tx.operation not in INCOME_OPS or tx.date < year_start:
            continue
        amount = tx.total_value or ZERO
        if tx.currency == "BRL":
            total += amount
        elif tx.currency == "USD":
            if tx.date not in rates:
                fx = get_usd_brl(db, tx.date)
                rates[tx.date] = fx.rate if fx is not None else None
            rate = rates[tx.date]
            if rate is not None:
                total += amount * rate
    return total


def _to_brl(
    amount: Decimal,
    currency: str,
    usd_rate: Callable[[], FxResult | None],
    warnings: list[str],
    ticker: str,
) -> Decimal | None:
    if currency == "BRL":
        return amount
    if currency == "USD":
        fx = usd_rate()
        if fx is not None:
            return amount * fx.rate
        warnings.append(
            f"{ticker}: USD/BRL rate unavailable; excluded from BRL total"
        )
        return None
    warnings.append(f"{ticker}: no FX source for {currency}; excluded from BRL total")
    return None


def _cents(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)
