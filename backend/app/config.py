from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def validate_public_host(host: str, where: str = "the allowlist") -> str:
    """A bare lowercase public DNS hostname, or a ValueError saying what is wrong with it."""
    if (
        not host
        or host != host.lower()
        or len(host) > 253
        or any(c in host for c in "/:*@ \\?#")
        or host.startswith(".")
        or host.endswith(".")
    ):
        raise ValueError(
            f"Use bare lowercase hostnames in {where}, for example www.iana.org — no scheme, "
            "port, path or wildcard"
        )
    # Naming this machine or a private range here would turn a research allowlist into a
    # way to read internal services, so the studio refuses such an entry outright.
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        raise ValueError(f"{where} names public sources, not this machine")
    try:
        address = ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise ValueError(f"{where} names public sources, not internal addresses")
    return host


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
    # Empty by default. This list is one half of the studio's SSRF boundary; the other half
    # is the table of hosts the Owner adds and tests from the interface
    # (`research_allowed_host`, Owner-authenticated endpoints only). No agent has a tool that
    # reaches either: an allowlist an agent could add to would not be an allowlist.
    research_allowed_hosts: list[str] = []

    # Absolute path to an ffmpeg executable. When unset, PATH is searched.
    ffmpeg_path: str | None = None

    # Google's public "trending now" feed for this country code, read once a day and kept as
    # a signal for the Researcher's proposals and the Director's weekly review. A trend is a
    # hook, never a source. STUDIO_TRENDS_GEO=RO; STUDIO_TRENDS_ENABLED=false turns it off.
    trends_enabled: bool = True
    trends_geo: str = Field(default="RO", min_length=2, max_length=8, pattern="^[A-Za-z-]+$")

    # The language the audience reads and hears: narration, titles, descriptions, tags. The
    # Owner's rule is English regardless of the language the office works in; a publication
    # whose metadata is not in this language holds. STUDIO_CONTENT_LANGUAGE=en.
    content_language: str = Field(default="en", min_length=2, max_length=5, pattern="^[a-z-]+$")

    # The background worker is what makes the studio run without the browser: it fires due
    # scheduled jobs and executes the tasks they enqueue. Off in tests, where a loop that starts
    # the day on its own would make every other test's timing a coincidence.
    worker_enabled: bool = True
    worker_interval_seconds: int = Field(default=30, ge=5, le=3600)
    provider_catalog_refresh_enabled: bool = True
    provider_catalog_refresh_seconds: int = Field(default=21600, ge=60, le=604800)
    provider_catalog_retry_seconds: int = Field(default=900, ge=30, le=86400)
    provider_catalog_poll_seconds: int = Field(default=60, ge=5, le=3600)

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
        """Reject anything that is not a bare lowercase public DNS hostname.

        A scheme, a port, a path or a wildcard here would silently widen the boundary; the
        retriever compares the parsed hostname against these entries exactly. The same rule
        guards the hosts the Owner adds from the interface (`validate_public_host`).
        """
        for host in value:
            validate_public_host(host, "STUDIO_RESEARCH_ALLOWED_HOSTS")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value
