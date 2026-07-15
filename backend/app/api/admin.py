"""Admin operations: trigger a database backup on demand."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.backup import BackupError, create_backup

router = APIRouter(prefix="/admin")


class BackupOut(BaseModel):
    filename: str
    size_bytes: int
    total_backups: int
    deleted: list[str]


@router.post("/backup", response_model=BackupOut)
def trigger_backup() -> BackupOut:
    try:
        result = create_backup()
    except BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BackupOut(
        filename=result.path.name,
        size_bytes=result.size_bytes,
        total_backups=result.total_backups,
        deleted=result.deleted,
    )
