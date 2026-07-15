"""Portfolio engine: derives positions from transactions.

Positions are computed on the fly, never persisted. Brazilian average-price
rules:
- Buys update the weighted average price (fees enter the cost basis).
- Sells reduce quantity at the current average price without changing it;
  realized P&L = quantity * (sale price - average price) - fees.
- A total sale zeroes the position; a later repurchase restarts the average
  from scratch.
- split: signed quantity adjustment with unchanged total cost, so the
  average price rescales (negative quantity models a reverse split).
- bonus: adds quantity at the attributed unit price (often 0), diluting the
  average.
- transfer: signed quantity adjustment that preserves the average price
  (cost moves proportionally), so custody/lending in-out pairs are neutral.
  A transfer-in may declare a unit_price: the shares then arrive carrying
  that average (cross-ticker conversions, custody moved from another
  broker with known cost). Without a price, the receiving position's
  average (or dormant average) is used, as before.
- dividend/jcp/yield: accumulate as income, no position effect.

Sells and transfers out beyond the held quantity are clamped to zero and
reported as warnings instead of failing the whole computation — real
exports contain history older than the export window.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Protocol

from app.models.enums import AssetClass, Custody, Indexer, Market, Operation

ZERO = Decimal("0")

# Read-time asset-class overrides, keyed by ticker. Some sources store an
# instrument with the wrong class (e.g. Avenue marks every US holding as a
# stock, including ETFs). Applied at the single point where a position's class
# is resolved (compute_positions), so every downstream consumer — positions,
# allocation-by-class, reports, grouping — sees the corrected class. Imported
# transactions stay literally untouched. Explicit allowlist, never a name
# heuristic; extend deliberately.
ASSET_CLASS_OVERRIDES: dict[str, AssetClass] = {
    "QQQ": AssetClass.etf,
    "VTI": AssetClass.etf,
}


def resolve_asset_class(ticker: str, default: AssetClass) -> AssetClass:
    return ASSET_CLASS_OVERRIDES.get(ticker, default)


class TransactionLike(Protocol):
    date: object
    ticker: str
    asset_name: str | None
    asset_class: AssetClass
    market: Market
    currency: str
    operation: Operation
    quantity: Decimal
    unit_price: Decimal
    fees: Decimal | None
    total_value: Decimal | None
    custody: Custody | None
    custody_from: Custody | None
    custody_to: Custody | None
    indexer: Indexer | None


@dataclass
class Position:
    ticker: str
    asset_name: str | None
    asset_class: AssetClass
    market: Market
    currency: str
    # Crypto custody (hot/cold); None for non-crypto. Part of the position
    # identity, so the same ticker in two custodies stays separate.
    custody: Custody | None = None
    quantity: Decimal = ZERO
    total_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    income: Decimal = ZERO
    # Institution of the most recent transaction that declared one — an
    # approximation when the same ticker passed through multiple brokers.
    institution: str | None = None
    # Manual fixed-income indexer override from the most recent transaction
    # that declared one; None means "derive from the name" at read time.
    indexer: Indexer | None = None
    # Average price held while a transfer keeps the position at zero (e.g.
    # all shares lent out), so the cost basis survives the round trip. A
    # total *sale* must not preserve it — repurchase restarts the average.
    dormant_average: Decimal = ZERO

    @property
    def average_price(self) -> Decimal:
        if self.quantity == 0:
            return ZERO
        return self.total_cost / self.quantity

    @property
    def is_open(self) -> bool:
        return self.quantity != 0

    def unrealized_pnl(self, market_price: Decimal) -> Decimal:
        return self.quantity * market_price - self.total_cost


PositionKey = tuple[str, Custody | None]


@dataclass
class PortfolioResult:
    # Keyed by (ticker, custody): the same ticker in hot and cold custody is
    # two distinct positions with their own average price and quantity.
    positions: dict[PositionKey, Position] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _intraday_rank(tx: TransactionLike) -> int:
    """Within a day, inflows are processed before outflows.

    B3 exports have no intra-day timestamps, and selling shares that are
    lent out produces a same-day triplet (loan returns +N, custody transfer
    -N, sale N) whose file order starts with the outflows. Processing an
    outflow first hits the clamp and corrupts the day's net quantity;
    inflow-first ordering is always clamp-free for these settlements. The
    known trade-off: a same-day total-sale-then-repurchase would blend the
    average instead of restarting it — accepted, since that ambiguity is
    inherent to date-only data.
    """
    if tx.operation is Operation.sell:
        return 1
    if tx.operation in (Operation.transfer, Operation.split) and tx.quantity < 0:
        return 1
    # A custody move reads the origin's current average, so it must run after
    # same-day buys/sells that shape that average.
    if tx.operation is Operation.custody_transfer:
        return 2
    return 0


def _engine_order(tx: TransactionLike) -> tuple:
    """Deterministic engine ordering: (date, intraday rank, created_at, id).

    Python's sort is stable, but relying on input order for same-day,
    same-rank legs means relying on SELECT arrival order — which SQL does
    not guarantee without an ORDER BY. Reconciled data carries many legs on
    one day, and sells/transfers clamp (they do not commute), so the
    tiebreak must be explicit: creation time, then id. Objects without
    those fields (parser output, repriced USD copies) sort before persisted
    rows of the same day+rank and keep their relative input order via sort
    stability.
    """
    created = getattr(tx, "created_at", None)
    if created is not None and created.tzinfo is not None:
        # Stored values are always UTC; SQLite reads them back naive. Strip
        # the tz so freshly-created (aware) and re-read (naive) rows compare.
        created = created.replace(tzinfo=None)
    return (
        tx.date,
        _intraday_rank(tx),
        created or datetime.min,
        str(getattr(tx, "id", "") or ""),
    )


def compute_positions(transactions: Iterable[TransactionLike]) -> PortfolioResult:
    result = PortfolioResult()
    ordered = sorted(transactions, key=_engine_order)
    for tx in ordered:
        if tx.operation is Operation.custody_transfer:
            _apply_custody_transfer(result, tx)
            continue
        custody = getattr(tx, "custody", None)
        key: PositionKey = (tx.ticker, custody)
        position = result.positions.get(key)
        if position is None:
            position = Position(
                ticker=tx.ticker,
                asset_name=tx.asset_name,
                asset_class=resolve_asset_class(tx.ticker, tx.asset_class),
                market=tx.market,
                currency=tx.currency,
                custody=custody,
            )
            result.positions[key] = position
        if tx.asset_name:
            position.asset_name = tx.asset_name
        institution = getattr(tx, "institution", None)
        if institution:
            position.institution = institution
        indexer = getattr(tx, "indexer", None)
        if indexer:
            position.indexer = indexer
        _apply(position, tx, result.warnings)
    return result


def _apply_custody_transfer(result: PortfolioResult, tx: TransactionLike) -> None:
    """Move quantity between two custodies of the same ticker at the origin's
    *current derived* average price.

    The origin position has already absorbed every earlier transaction (the
    loop runs in date order, custody moves last within a day), so its
    `average_price` is the live, derived PM — nothing is read from the
    transaction. Debiting the origin and crediting the destination at the
    same average keeps Σcost and total quantity invariant, so the
    consolidated PM is unchanged and no realized P&L is produced.
    """
    origin = result.positions.get((tx.ticker, tx.custody_from))
    available = origin.quantity if origin is not None else ZERO
    qty = tx.quantity
    if qty > available:
        result.warnings.append(
            f"{tx.date} {tx.ticker}: custody transfer of {qty} exceeds "
            f"{available} held in {tx.custody_from}; clamped"
        )
        qty = available
    if qty <= 0 or origin is None:
        return

    average = origin.average_price if origin.quantity > 0 else origin.dormant_average
    origin.quantity -= qty
    if origin.quantity == 0:
        origin.dormant_average = average
        origin.total_cost = ZERO
    else:
        origin.total_cost -= qty * average

    dest_key: PositionKey = (tx.ticker, tx.custody_to)
    dest = result.positions.get(dest_key)
    if dest is None:
        dest = Position(
            ticker=tx.ticker,
            asset_name=origin.asset_name or tx.asset_name,
            asset_class=origin.asset_class,
            market=origin.market,
            currency=origin.currency,
            custody=tx.custody_to,
        )
        result.positions[dest_key] = dest
    dest.quantity += qty
    dest.total_cost += qty * average


def _apply(position: Position, tx: TransactionLike, warnings: list[str]) -> Decimal:
    """Applies the transaction and returns the quantity delta actually
    applied (post-clamp), so callers like the TWR flow accounting can
    mirror exactly what happened — a clamped sell moved no shares and
    must not be treated as a cash flow either."""
    fees = tx.fees or ZERO
    op = tx.operation

    if op is Operation.buy:
        position.quantity += tx.quantity
        position.total_cost += tx.quantity * tx.unit_price + fees
        return tx.quantity

    if op is Operation.sell:
        sellable = min(tx.quantity, position.quantity)
        if sellable < tx.quantity:
            warnings.append(
                f"{tx.date} {tx.ticker}: sell of {tx.quantity} exceeds held "
                f"quantity {position.quantity}; clamped (history before the "
                "export window?)"
            )
        average = position.average_price
        position.realized_pnl += sellable * (tx.unit_price - average) - fees
        position.quantity -= sellable
        if position.quantity == 0:
            position.total_cost = ZERO
            position.dormant_average = ZERO
        else:
            position.total_cost = position.quantity * average
        return -sellable

    if op is Operation.bonus:
        position.quantity += tx.quantity
        position.total_cost += tx.quantity * tx.unit_price
        return tx.quantity

    if op is Operation.split:
        position.quantity += tx.quantity
        return tx.quantity

    if op is Operation.transfer:
        if tx.quantity < 0 and -tx.quantity > position.quantity:
            warnings.append(
                f"{tx.date} {tx.ticker}: transfer out of {-tx.quantity} exceeds "
                f"held quantity {position.quantity}; clamped"
            )
            delta = -position.quantity
        else:
            delta = tx.quantity
        if delta > 0 and tx.unit_price:
            average = tx.unit_price
        else:
            average = (
                position.average_price
                if position.quantity > 0
                else position.dormant_average
            )
        position.quantity += delta
        position.total_cost += delta * average
        if position.quantity == 0:
            position.dormant_average = average
        return delta

    if op in (Operation.dividend, Operation.jcp, Operation.yield_):
        position.income += tx.total_value or ZERO
        return ZERO

    if op is Operation.custody_transfer:
        # Internal to a ticker; handled two-sided by _apply_custody_transfer
        # in the (ticker, custody)-keyed engine. In any ticker-keyed caller
        # (the TWR engine) it is a pure no-op: no quantity change, no flow.
        return ZERO

    # pragma: no cover - enum is closed, guard against new members
    warnings.append(f"{tx.date} {tx.ticker}: operation {op} not handled")
    return ZERO
