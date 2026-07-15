"""SQLite database backup with daily rotation.

Uses SQLite's online backup API (not a raw file copy) so the snapshot is
consistent even if the app is mid-write. Backups are named
`portfolio-YYYY-MM-DD.db`; the ISO date makes lexicographic order match
chronological order, so rotation just keeps the newest N filenames.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from app.core.config import settings

BACKUP_PREFIX = "portfolio-"


class BackupError(Exception):
    pass


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    total_backups: int
    deleted: list[str]


def sqlite_path() -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise BackupError("Backup automático só é suportado para SQLite.")
    return Path(url.split("sqlite:///", 1)[1])


def create_backup(
    db_path: Path | None = None,
    backup_dir: Path | None = None,
    keep: int | None = None,
    on: date | None = None,
) -> BackupResult:
    db_path = db_path or sqlite_path()
    backup_dir = backup_dir or settings.backup_dir
    keep = settings.backup_keep if keep is None else keep
    if not db_path.exists():
        raise BackupError(f"Banco de dados não encontrado: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    day = on or datetime.now(timezone.utc).date()
    dest = backup_dir / f"{BACKUP_PREFIX}{day.isoformat()}.db"

    _sqlite_snapshot(db_path, dest)
    deleted = _rotate(backup_dir, keep)
    return BackupResult(
        path=dest,
        size_bytes=dest.stat().st_size,
        total_backups=len(_list_backups(backup_dir)),
        deleted=deleted,
    )


def _sqlite_snapshot(src: Path, dest: Path) -> None:
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _list_backups(backup_dir: Path) -> list[Path]:
    return sorted(backup_dir.glob(f"{BACKUP_PREFIX}*.db"))


def _rotate(backup_dir: Path, keep: int) -> list[str]:
    if keep <= 0:
        return []
    backups = _list_backups(backup_dir)
    stale = backups[:-keep] if len(backups) > keep else []
    deleted: list[str] = []
    for old in stale:
        old.unlink()
        deleted.append(old.name)
    return deleted
