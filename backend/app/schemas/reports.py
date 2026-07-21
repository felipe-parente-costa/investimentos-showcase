from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SnapshotSummaryOut(BaseModel):
    year_month: str
    as_of_date: date
    total_brl: Decimal
    month_return_pct: Decimal | None
    cumulative_return_pct: Decimal | None
    income_month_brl: Decimal


class SnapshotPositionOut(BaseModel):
    ticker: str
    asset_name: str | None
    asset_class: str
    market: str
    institution: str | None
    custody: str | None
    indexer: str | None = None
    currency: str
    quantity: Decimal
    average_price: Decimal
    market_value_brl: Decimal
    unrealized_pnl_brl: Decimal | None
    priced: bool


class SnapshotDetailOut(SnapshotSummaryOut):
    created_at: datetime
    # Recompute trail (None = never regenerated since creation).
    last_recomputed_at: datetime | None = None
    recompute_reason: str | None = None
    positions: list[SnapshotPositionOut]
    allocation_class: dict[str, Decimal]
    allocation_currency: dict[str, Decimal]
    allocation_broker: dict[str, Decimal]
    usd_brl_rate: Decimal | None = None


class SnapshotListOut(BaseModel):
    items: list[SnapshotSummaryOut]
