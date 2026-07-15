from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SkippedRowOut(BaseModel):
    row: int
    movement_type: str
    reason: str


class ImportWarningOut(BaseModel):
    row: int
    ticker: str
    date: date
    quantity: Decimal
    message: str


class ImportResultOut(BaseModel):
    imported: int
    duplicates: int
    skipped: list[SkippedRowOut]
    warnings: list[ImportWarningOut] = []
    # Lending-events import only: reference rows added to lending_events vs
    # already known (timeline-extension idempotency). None for other sources.
    events_added: int | None = None
    events_known: int | None = None
