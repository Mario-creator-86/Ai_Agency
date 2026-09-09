from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STUDIO_", env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

    owner_token: SecretStr
    name: str = Field(default="Autonomous AI Studio", min_length=1, max_length=100)
    timezone: str = "Europe/Bucharest"
    database_url: str = "sqlite:///data/studio.db"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Official YouTube Data API v3 credentials. Absent by default: the application must
    # never simulate a publishing integration when these are missing (AGENTS.md).
    youtube_client_id: str | None = None
    youtube_client_secret: SecretStr | None = None
    youtube_refresh_token: SecretStr | None = None
    youtube_channel_id: str | None = None

    # Absolute path to an ffmpeg executable. When unset, PATH is searched.
    ffmpeg_path: str | None = None

    @property
    def youtube_credentials_present(self) -> bool:
        """True only when a real OAuth credential triple is configured."""
        return bool(
            self.youtube_client_id and self.youtube_client_secret and self.youtube_refresh_token
        )

    @field_validator("owner_token")
    @classmethod
    def strong_token(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("Run scripts/bootstrap.py to configure a unique Owner token")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value
