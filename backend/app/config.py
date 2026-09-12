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

    #: Every published description ends with the studio's AI disclosure and a pointer to the
    #: channel that made the film. Both halves are configuration, never code: the site the
    #: disclosure links to (STUDIO_AI_DISCLOSURE_URL, empty until the Owner publishes it) and
    #: the title of the connected YouTube channel credited as the creator
    #: (STUDIO_CREATOR_CHANNEL_TITLE). The link to that channel is read from its stored
    #: connection.
    ai_disclosure_url: str | None = None
    creator_channel_title: str | None = None

    #: The office scene draws the live weather where the studio is. The service that reports
    #: it is configuration (STUDIO_OFFICE_WEATHER_HOST, an Open-Meteo compatible forecast host);
    #: unset, the scene says the weather is unavailable and draws none. The coordinates are
    #: the office's own (Bucharest by default), also used for sunrise and sunset.
    office_weather_host: str | None = None
    office_latitude: float = Field(default=44.4268, ge=-90, le=90)
    office_longitude: float = Field(default=26.1025, ge=-180, le=180)

    #: What the studio optimises for when it picks a model itself. The Owner's standing
    #: instruction is premium: the best picture the account can make, cost secondary — "no
    #: sense having a film company that cannot deliver good films". `balanced` weighs the
    #: four criteria evenly, `thrifty` puts cost first. The weights below are what each
    #: means; every channel may still override them per purpose.
    production_priority: Literal["premium", "balanced", "thrifty"] = "premium"

    #: The most one film may spend on generated motion, in dollars. Measured on the Owner's
    #: account: a six-second shot on `seedance2_5` costs about 2.60 USD, so eight shots are
    #: twenty. A film is worth that; a day of experiments is not, and nothing priced a shot
    #: until the Owner recorded what a credit costs — so the daily budget saw a day that had
    #: spent nothing while twenty-one dollars went out.
    motion_budget_usd: float = 12.0

    #: How long a short should be. The Owner's answer: about thirty seconds, and the story
    #: decides — twenty-four when that is the film, thirty-four when a premium story needs it.
    #: The writer is briefed with it, and the story review measures the narration against it.
    target_video_seconds: int = 30

    #: How many scenes of a render may be generated as motion. None means every scene; a
    #: small number is what a test render uses, so seeing how a film reads costs one shot
    #: instead of eight. The Owner's instruction: "la teste redam doar minimul".
    motion_scenes_max: int | None = None

    #: How many scenes a TEST render may generate. A test answers "does this work", and two
    #: shots answer it; the Owner's instruction after an afternoon cost twenty-one dollars
    #: was that a test renders the minimum.
    test_motion_scenes: int = 2

    #: What a single TEST generation may cost, and what a TEST second may cost. A request
    #: above either is refused rather than quietly bought: in TEST the studio is checking
    #: that the pipeline works, not what a shot looks like.
    test_max_cost_per_generation_usd: float = 0.60
    test_max_cost_per_second_usd: float = 0.12

    # ---------------------------------------------------------------- models come and go
    #: Whether a model the vendor has newly exposed is taken into the studio's catalogue at
    #: all. On, because a catalogue the studio refuses to read is a catalogue frozen in the
    #: month someone wrote it down; a new model still starts outside production.
    auto_discover_models: bool = True

    #: Whether the studio may spend money of its own accord to learn what a new model's
    #: picture is like. Off by default: benchmarking is generation, and generation is money.
    auto_benchmark_new_models: bool = False

    #: What the studio may spend on benchmarking in one review, in dollars.
    max_benchmark_budget_usd: float = 1.50

    #: Whether the periodic review may move a model up when its own results justify it, and
    #: down when it keeps failing or costs a multiple of an admitted model for the same job.
    auto_promote_cheaper_better_models: bool = True
    auto_demote_expensive_models: bool = True

    #: How many judged generations a model needs before its results may move it. Below this
    #: a good run is luck, not evidence.
    min_test_samples_for_promotion: int = Field(default=3, ge=1, le=100)

    #: A price that moves by at least this much is a letter to the Owner, and a vendor quote
    #: that disagrees with the stored price by more than the tolerance makes it stale.
    price_change_alert_percent: float = Field(default=10.0, ge=0.1, le=1000.0)
    price_stale_tolerance_percent: float = Field(default=5.0, ge=0.1, le=1000.0)

    #: Model names the Owner refuses, as comma-separated shell patterns (`*` matches). The
    #: one thing about models that belongs in configuration: a judgement, not a fact.
    model_deny_list: str = ""

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
