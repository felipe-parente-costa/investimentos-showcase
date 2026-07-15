import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AssetClass, Custody, Indexer, Market, Operation, Source


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source: Mapped[Source] = mapped_column(Enum(Source, native_enum=False, length=20))
    date: Mapped[date_type] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String(40), index=True)
    asset_name: Mapped[str | None] = mapped_column(String(200))
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, native_enum=False, length=20)
    )
    market: Mapped[Market] = mapped_column(Enum(Market, native_enum=False, length=10))
    institution: Mapped[str | None] = mapped_column(String(100))
    # Crypto custody (hot exchange vs cold wallet); null for non-crypto.
    custody: Mapped[Custody | None] = mapped_column(
        Enum(Custody, native_enum=False, length=20)
    )
    # Origin/destination custody for a custody_transfer (crypto hot<->cold);
    # null for every other operation.
    custody_from: Mapped[Custody | None] = mapped_column(
        Enum(Custody, native_enum=False, length=20)
    )
    custody_to: Mapped[Custody | None] = mapped_column(
        Enum(Custody, native_enum=False, length=20)
    )
    # Manual fixed-income indexer override; null means "derive from the name".
    indexer: Mapped[Indexer | None] = mapped_column(
        Enum(Indexer, native_enum=False, length=20)
    )
    currency: Mapped[str] = mapped_column(String(10))
    operation: Mapped[Operation] = mapped_column(
        Enum(Operation, native_enum=False, length=20)
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    fees: Mapped[Decimal] = mapped_column(Numeric(24, 10), default=Decimal("0"))
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    import_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    notes: Mapped[str | None] = mapped_column(Text)
