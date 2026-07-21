"""Monthly portfolio snapshots.

A snapshot freezes the portfolio state as of a given date: total in BRL,
each open position (quantity / average price / market value / P&L),
allocation by class, currency and broker, the month and cumulative TWR,
and the month's income. Values are computed once and stored; reports read
the frozen rows rather than recomputing from history.

Valuation is "as of" the snapshot date using cached daily closes (the
last close on/before that date) and the PTAX of that date, so a month-end
snapshot reflects month-end prices regardless of when it is generated.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Operation
from app.models.monthly_snapshot import MonthlySnapshot
from app.models.quote import Quote
from app.models.transaction import Transaction
from app.services.fx import FxResult, get_usd_brl
from app.services.history import build_patrimony_history
from app.services.indexer import resolve_indexer
from app.services.portfolio import compute_positions

ZERO = Decimal("0")
CENTS = Decimal("0.01")
PCT = Decimal("0.0001")
INCOME_OPERATIONS = (Operation.dividend, Operation.jcp, Operation.yield_)


@dataclass
class SnapshotData:
    year_month: str
    as_of_date: date
    total_brl: Decimal
    month_return_pct: Decimal | None
    cumulative_return_pct: Decimal | None
    income_month_brl: Decimal
    payload: dict


def month_bounds(as_of: date) -> tuple[date, date]:
    """First and last day of `as_of`'s month."""
    first = as_of.replace(day=1)
    last = as_of.replace(day=monthrange(as_of.year, as_of.month)[1])
    return first, last


def previous_month(reference: date) -> tuple[str, date]:
    """(year_month, last_day) of the month before `reference`'s month."""
    last_prev = reference.replace(day=1) - timedelta(days=1)
    return f"{last_prev.year:04d}-{last_prev.month:02d}", last_prev


def _as_of_close(db: Session, ticker: str, as_of: date) -> Decimal | None:
    # Official closes only: intraday snapshot rows must not value a frozen
    # month-end snapshot.
    return db.execute(
        select(Quote.close_price)
        .where(
            Quote.ticker == ticker,
            Quote.date <= as_of,
            Quote.kind == "close",
        )
        .order_by(Quote.date.desc(), Quote.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _to_brl(amount: Decimal, currency: str, fx: FxResult | None) -> Decimal | None:
    if currency == "BRL":
        return amount
    if currency == "USD" and fx is not None:
        return amount * fx.rate
    return None


def _cents(value: Decimal | None) -> Decimal | None:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP) if value is not None else None


def build_snapshot_data(db: Session, as_of: date) -> SnapshotData | None:
    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return None

    # Building history backfills daily closes and gives the TWR index per
    # day for the month/cumulative returns.
    history = build_patrimony_history(db, granularity="daily")
    twr_by_date = {p.date: p.twr_index for p in history.points}

    in_scope = [tx for tx in transactions if tx.date <= as_of]
    positions = compute_positions(in_scope).positions
    fx = get_usd_brl(db, as_of)

    total = ZERO
    positions_out: list[dict] = []
    alloc_class: dict[str, Decimal] = {}
    alloc_currency: dict[str, Decimal] = {}
    alloc_broker: dict[str, Decimal] = {}

    for position in sorted(
        positions.values(),
        key=lambda p: (p.ticker, p.custody.value if p.custody else ""),
    ):
        ticker = position.ticker
        if not position.is_open:
            continue
        close = _as_of_close(db, ticker, as_of)
        priced = close is not None and position.asset_class is not AssetClass.fixed_income
        if priced:
            market_value_native = position.quantity * close
        else:
            market_value_native = position.total_cost
        market_value_brl = _to_brl(market_value_native, position.currency, fx)
        if market_value_brl is None:
            continue  # no FX: cannot value in BRL, exclude from the frozen total

        unrealized_brl: Decimal | None = None
        if priced:
            unrealized_brl = _to_brl(
                market_value_native - position.total_cost, position.currency, fx
            )

        total += market_value_brl
        _add(alloc_class, position.asset_class.value, market_value_brl)
        _add(alloc_currency, position.currency, market_value_brl)
        _add(alloc_broker, position.institution or "Sem corretora", market_value_brl)

        positions_out.append(
            {
                "ticker": ticker,
                "asset_name": position.asset_name,
                "asset_class": position.asset_class.value,
                "market": position.market.value,
                "institution": position.institution,
                "custody": position.custody.value if position.custody else None,
                "indexer": (
                    resolve_indexer(
                        position.ticker, position.asset_name, position.indexer
                    ).value
                    if position.asset_class is AssetClass.fixed_income
                    else None
                ),
                "currency": position.currency,
                "quantity": _num(position.quantity),
                "average_price": _num(position.average_price),
                "market_value_brl": str(_cents(market_value_brl)),
                "unrealized_pnl_brl": (
                    str(_cents(unrealized_brl)) if unrealized_brl is not None else None
                ),
                "priced": priced,
            }
        )

    cumulative, month = _returns(twr_by_date, as_of)
    income_month = _income_month(in_scope, as_of, fx)

    payload = {
        "positions": positions_out,
        "allocation_class": _alloc_payload(alloc_class),
        "allocation_currency": _alloc_payload(alloc_currency),
        "allocation_broker": _alloc_payload(alloc_broker),
        "usd_brl_rate": str(fx.rate) if fx else None,
    }
    return SnapshotData(
        year_month=f"{as_of.year:04d}-{as_of.month:02d}",
        as_of_date=as_of,
        total_brl=_cents(total),
        month_return_pct=month,
        cumulative_return_pct=cumulative,
        income_month_brl=_cents(income_month),
        payload=payload,
    )


def generate_monthly_snapshot(
    db: Session, as_of: date, *, recompute_reason: str | None = None
) -> MonthlySnapshot | None:
    """Compute and upsert the snapshot for `as_of`'s month.

    Regenerating an existing row records last_recomputed_at and a reason —
    the snapshot is a best-current-estimate of the month end with an audit
    trail, not an immutable photo (definition sanctioned 2026-07-14). The
    manual button passes no reason and is recorded as "manual"."""
    data = build_snapshot_data(db, as_of)
    if data is None:
        return None
    snapshot = db.execute(
        select(MonthlySnapshot).where(MonthlySnapshot.year_month == data.year_month)
    ).scalar_one_or_none()
    regenerating = snapshot is not None
    if snapshot is None:
        snapshot = MonthlySnapshot(year_month=data.year_month)
        db.add(snapshot)
    if regenerating:
        snapshot.last_recomputed_at = datetime.now(timezone.utc)
        snapshot.recompute_reason = recompute_reason or "manual (geração sob demanda)"
    snapshot.as_of_date = data.as_of_date
    snapshot.total_brl = data.total_brl
    snapshot.month_return_pct = data.month_return_pct
    snapshot.cumulative_return_pct = data.cumulative_return_pct
    snapshot.income_month_brl = data.income_month_brl
    snapshot.payload = data.payload
    snapshot.created_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _returns(
    twr_by_date: dict[date, Decimal], as_of: date
) -> tuple[Decimal | None, Decimal | None]:
    end_index = _index_on_or_before(twr_by_date, as_of)
    if end_index is None:
        return None, None
    cumulative = (end_index - 100).quantize(PCT)
    _, prev_month_end = previous_month(as_of)
    base_index = _index_on_or_before(twr_by_date, prev_month_end) or Decimal("100")
    month = (
        ((end_index / base_index - 1) * 100).quantize(PCT) if base_index > 0 else None
    )
    return cumulative, month


def _index_on_or_before(twr_by_date: dict[date, Decimal], target: date) -> Decimal | None:
    candidates = [d for d in twr_by_date if d <= target]
    return twr_by_date[max(candidates)] if candidates else None


def _income_month(
    transactions: list[Transaction], as_of: date, fx: FxResult | None
) -> Decimal:
    first, _ = month_bounds(as_of)
    total = ZERO
    for tx in transactions:
        if tx.operation not in INCOME_OPERATIONS:
            continue
        if tx.date < first or tx.date > as_of:
            continue
        amount = tx.total_value or ZERO
        converted = _to_brl(amount, tx.currency, fx)
        if converted is not None:
            total += converted
    return total


def _add(bucket: dict[str, Decimal], key: str, value: Decimal) -> None:
    bucket[key] = bucket.get(key, ZERO) + value


def _alloc_payload(bucket: dict[str, Decimal]) -> dict[str, str]:
    return {key: str(_cents(value)) for key, value in bucket.items()}


def _num(value: Decimal) -> str:
    # Trim trailing zeros while staying a plain decimal string.
    normalized = value.normalize()
    return f"{normalized:f}"
