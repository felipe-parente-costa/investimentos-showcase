"""Monthly report endpoints: list snapshots, fetch one, generate on demand."""

import re
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.monthly_snapshot import MonthlySnapshot
from app.schemas.reports import (
    SnapshotDetailOut,
    SnapshotListOut,
    SnapshotSummaryOut,
)
from app.services.reports import generate_monthly_snapshot

router = APIRouter(prefix="/reports")

YEAR_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
CENTS = Decimal("0.01")
PCT = Decimal("0.0001")


def _money(value: Decimal) -> Decimal:
    # The NUMERIC(24,10) column pads to 10 places on read; trim to cents.
    return value.quantize(CENTS)


def _pct(value: Decimal | None) -> Decimal | None:
    return value.quantize(PCT) if value is not None else None


def _summary(snapshot: MonthlySnapshot) -> SnapshotSummaryOut:
    return SnapshotSummaryOut(
        year_month=snapshot.year_month,
        as_of_date=snapshot.as_of_date,
        total_brl=_money(snapshot.total_brl),
        month_return_pct=_pct(snapshot.month_return_pct),
        cumulative_return_pct=_pct(snapshot.cumulative_return_pct),
        income_month_brl=_money(snapshot.income_month_brl),
    )


def _detail(snapshot: MonthlySnapshot) -> SnapshotDetailOut:
    return SnapshotDetailOut(
        **_summary(snapshot).model_dump(),
        created_at=snapshot.created_at,
        last_recomputed_at=snapshot.last_recomputed_at,
        recompute_reason=snapshot.recompute_reason,
        positions=snapshot.payload.get("positions", []),
        allocation_class=snapshot.payload.get("allocation_class", {}),
        allocation_currency=snapshot.payload.get("allocation_currency", {}),
        allocation_broker=snapshot.payload.get("allocation_broker", {}),
        usd_brl_rate=snapshot.payload.get("usd_brl_rate"),
    )


@router.get("/monthly", response_model=SnapshotListOut)
def list_monthly(db: Session = Depends(get_db)) -> SnapshotListOut:
    snapshots = (
        db.execute(select(MonthlySnapshot).order_by(MonthlySnapshot.year_month))
        .scalars()
        .all()
    )
    return SnapshotListOut(items=[_summary(s) for s in snapshots])


@router.post("/monthly/generate", response_model=SnapshotDetailOut, status_code=201)
def generate_current_month(db: Session = Depends(get_db)) -> SnapshotDetailOut:
    """Generate (or refresh) the snapshot for the current month, as of today."""
    today = datetime.now(timezone.utc).date()
    snapshot = generate_monthly_snapshot(db, today)
    if snapshot is None:
        raise HTTPException(
            status_code=400, detail="Sem transações para gerar o relatório."
        )
    return _detail(snapshot)


@router.get("/monthly/{year_month}", response_model=SnapshotDetailOut)
def get_monthly(year_month: str, db: Session = Depends(get_db)) -> SnapshotDetailOut:
    if not YEAR_MONTH_RE.match(year_month):
        raise HTTPException(status_code=422, detail="Use o formato AAAA-MM.")
    snapshot = db.execute(
        select(MonthlySnapshot).where(MonthlySnapshot.year_month == year_month)
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return _detail(snapshot)
