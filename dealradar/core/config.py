"""Configuration from environment variables (prefix ``DEALRADAR_``) and an optional ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEALRADAR_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Field(default=Path("data"), description="Database, logs and backups.")
    log_level: LogLevel = "INFO"
    lock_timeout_s: float = Field(default=10.0, gt=0, le=600)
    # Optional Telegram notifications (free Bot API). Both must be set to enable sending.
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = Field(default=None, max_length=64)

    @property
    def telegram_enabled(self) -> bool:
        return bool(
            self.telegram_bot_token
            and self.telegram_bot_token.get_secret_value()
            and self.telegram_chat_id
        )

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.resolved_data_dir / "dealradar.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def log_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.resolved_data_dir / "backups"

    @property
    def lock_path(self) -> Path:
        return self.resolved_data_dir / "dealradar.lock"

    def ensure_dirs(self) -> None:
        for directory in (self.resolved_data_dir, self.log_dir, self.backup_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Forget cached settings so changed environment variables apply (used by tests)."""
    get_settings.cache_clear()
