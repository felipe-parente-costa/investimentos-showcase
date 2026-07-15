from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MonthlySnapshot(Base):
    """Frozen end-of-month portfolio snapshot.

    Values are computed once (by the scheduled job or a manual trigger)
    and stored; viewing a report reads these frozen numbers instead of
    recomputing from history. The detailed positions and allocations live
    in `payload` (money as strings); the scalar columns index the summary.
    """

    __tablename__ = "monthly_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    year_month: Mapped[str] = mapped_column(String(7), unique=True, index=True)  # YYYY-MM
    as_of_date: Mapped[date_type] = mapped_column(Date)
    total_brl: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    month_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    cumulative_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    income_month_brl: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Recompute trail: set whenever an EXISTING row is regenerated (manual
    # button or the snapshot reconciler). The snapshot is a best-current-
    # estimate of the month end with an audit trail, not an immutable photo
    # (definition change sanctioned 2026-07-14). NULL = never regenerated.
    last_recomputed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recompute_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
