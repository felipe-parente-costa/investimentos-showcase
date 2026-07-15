from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (Index("ix_quotes_ticker_fetched_at", "ticker", "fetched_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(40), index=True)
    date: Mapped[date_type] = mapped_column(Date)
    close_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    currency: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))
    # Role of the row: 'close' = official daily close written by the history
    # backfill; 'intraday' = live spot snapshot written by the quote service.
    # Only 'close' rows feed the historical series (patrimony/TWR/correlation);
    # intraday rows exist so get_quote can serve/cache the live price without
    # polluting the closes. Pre-migration rows default to 'close' on purpose:
    # they must keep valuing history exactly as before until the contaminated
    # past is re-backfilled (a separate, follow-up task).
    kind: Mapped[str] = mapped_column(
        String(10), default="close", server_default="close"
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
