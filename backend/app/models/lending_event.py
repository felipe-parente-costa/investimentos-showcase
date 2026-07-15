from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LendingEventRecord(Base):
    """Reference data for the B3 stock-lending reconciler — NOT transactions.

    Rows come from the filtered Movimentação export (B3 filter "Outros"):
    `Empréstimo` contract events (qty > 0) and `Atualização` credits. They
    carry no import_hash on purpose: they are classification context, not
    portfolio facts. Idempotency is timeline extension via the natural key —
    reimporting the same export adds nothing; a newer export inserts only
    the events not yet known.
    """

    __tablename__ = "lending_events"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "date", "quantity", "direction", "kind",
            name="uq_lending_event",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(40), index=True)
    date: Mapped[date_type] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    direction: Mapped[str] = mapped_column(String(10))  # credito | debito
    kind: Mapped[str] = mapped_column(String(15))  # emprestimo | atualizacao
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
