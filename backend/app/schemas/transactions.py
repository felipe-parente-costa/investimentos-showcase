from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import AssetClass, Custody, Indexer, Market, Operation, Source


class TransactionIn(BaseModel):
    date: date_type
    ticker: str = Field(min_length=1, max_length=40)
    asset_name: str | None = None
    asset_class: AssetClass
    market: Market
    institution: str | None = None
    # Crypto custody (hot exchange vs cold wallet); leave null for non-crypto.
    custody: Custody | None = None
    # Origin/destination custody for an operation=custody_transfer.
    custody_from: Custody | None = None
    custody_to: Custody | None = None
    # Fixed-income indexer override; leave null to derive from the name.
    indexer: Indexer | None = None
    currency: str = "BRL"
    operation: Operation
    quantity: Decimal
    unit_price: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    # Defaults to quantity * unit_price when omitted.
    total_value: Decimal | None = None
    notes: str | None = None


class TransactionOut(BaseModel):
    id: str
    source: Source
    date: date_type
    ticker: str
    asset_name: str | None
    asset_class: AssetClass
    market: Market
    institution: str | None
    custody: Custody | None = None
    custody_from: Custody | None = None
    custody_to: Custody | None = None
    indexer: Indexer | None = None
    currency: str
    operation: Operation
    quantity: Decimal
    unit_price: Decimal
    fees: Decimal
    total_value: Decimal
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
