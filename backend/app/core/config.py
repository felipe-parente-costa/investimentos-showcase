from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), env_prefix="APP_")

    database_url: str = f"sqlite:///{BASE_DIR / 'investimentos.db'}"
    brapi_token: str = ""
    scheduler_enabled: bool = True
    backup_dir: Path = BASE_DIR / "backups"
    backup_keep: int = 30


settings = Settings()
