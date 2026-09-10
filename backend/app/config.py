from ipaddress import ip_address
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
    name: str = Field(default="AMN-AI", min_length=1, max_length=100)
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

    # Hosts the research retriever may fetch from, e.g.
    # STUDIO_RESEARCH_ALLOWED_HOSTS=["www.iana.org","www.nasa.gov"]
    #
    # Empty by default, which disables retrieval entirely. This list is the studio's SSRF
    # boundary, so it lives in the Owner's configuration file and nothing inside the
    # application — no endpoint, no form, no agent — can extend it. An allowlist an agent
    # could add to would not be an allowlist.
    research_allowed_hosts: list[str] = []

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

    @field_validator("research_allowed_hosts")
    @classmethod
    def plain_hostnames(cls, value: list[str]) -> list[str]:
        """Reject anything that is not a bare lowercase DNS hostname.

        A scheme, a port, a path or a wildcard here would silently widen the boundary; the
        retriever compares the parsed hostname against these entries exactly.
        """
        for host in value:
            if not host or host != host.lower() or any(c in host for c in "/:*@ "):
                raise ValueError(
                    "Use bare lowercase hostnames in STUDIO_RESEARCH_ALLOWED_HOSTS, "
                    "for example www.iana.org — no scheme, port, path or wildcard"
                )
            # Naming this machine or a private range here would turn a research allowlist
            # into a way to read internal services, so the studio refuses to start on one.
            if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
                raise ValueError(
                    "STUDIO_RESEARCH_ALLOWED_HOSTS names public sources, not this machine"
                )
            try:
                address = ip_address(host)
            except ValueError:
                continue
            if not address.is_global:
                raise ValueError(
                    "STUDIO_RESEARCH_ALLOWED_HOSTS names public sources, not internal addresses"
                )
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value
