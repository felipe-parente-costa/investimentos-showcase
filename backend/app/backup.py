"""CLI entrypoint: `python -m app.backup` creates a database backup now."""

from app.services.backup import BackupError, create_backup


def main() -> None:
    try:
        result = create_backup()
    except BackupError as exc:
        print(f"Backup falhou: {exc}")
        raise SystemExit(1)
    print(f"Backup criado: {result.path} ({result.size_bytes} bytes)")
    print(f"Total de backups: {result.total_backups}")
    if result.deleted:
        print(f"Removidos na rotação: {', '.join(result.deleted)}")


if __name__ == "__main__":
    main()
