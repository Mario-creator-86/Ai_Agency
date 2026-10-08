"""RunPod settings: one integration's form + vault secrets, or RUNPOD_* in the environment.

Phase 1 (2026-10-08, the Owner's cards): all stills and video on RunPod **Serverless**, an RTX PRO
6000 96 GB, at most ONE GPU at once, budgeted at 4.00 USD/h (RunPod's own pages disagree, 3.49 on
the pricing page, 0.00111 USD/s = 4.00 USD/h on the Serverless settings page). His words on the
idle tail: «trebuie sa se opreasca imediat dupa, nu la 30 sec. Sunt taxat la secunda, deci
trebuie oprit imediat dupa generare» - so ``idle_timeout_seconds`` is 1, the documented minimum
of ``EndpointWorkers.idleTimeout`` (1..3600, https://docs.runpod.io/api-reference-v2/serverless/
update-a-serverless-endpoint.md). Outputs go to an S3-compatible bucket he creates (RunPod keeps a
/run result only 30 minutes), read through presigned URLs (SigV4: 7 days at most).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config import ROOT

logger = logging.getLogger("studio.runpod")

#: The secrets a RunPod integration keeps in the vault, never in its public config.
SECRET_FIELDS = ("api_key", "s3_access_key_id", "s3_secret_access_key")

#: Set while a config is built from the integration alone (the environment ignored).
_WITHOUT_ENVIRONMENT: ContextVar[bool] = ContextVar("runpod_without_environment", default=False)

_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PREFIX = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,100}/$")


@contextmanager
def _without_environment() -> Iterator[None]:
    token = _WITHOUT_ENVIRONMENT.set(True)
    try:
        yield
    finally:
        _WITHOUT_ENVIRONMENT.reset(token)


@dataclass(frozen=True)
class BucketConfig:
    """Where the worker writes its outputs and the studio reads them (any S3-compatible API)."""

    endpoint_url: str
    bucket: str
    region: str
    prefix: str
    access_key_id: str
    secret_access_key: SecretStr
    url_ttl_seconds: int

    def __repr__(self) -> str:
        return (
            f"BucketConfig(endpoint_url={self.endpoint_url!r}, bucket={self.bucket!r}, "
            f"region={self.region!r}, prefix={self.prefix!r})"
        )


def _https_without_secrets(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.port not in (None, 443)
    ):
        raise ValueError("Use an HTTPS address without credentials, query or fragment")
    return value.rstrip("/")


class RunPodConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RUNPOD_",
        env_file=ROOT / ".env",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )

    enabled: bool = False
    mock: bool = False
    mode: Literal["pod", "serverless"] = "serverless"
    api_key: SecretStr = SecretStr("")
    #: Legacy single endpoint: used for both purposes when the two below are not set.
    endpoint_id: str | None = None
    stills_endpoint_id: str | None = None
    motion_endpoint_id: str | None = None
    generation_base_url: str | None = None
    gpu_name: str = "RTX_PRO_6000"
    gpu_vram_gb: int = Field(default=96, ge=1)
    #: The Pod rate (frozen Pod mode).
    gpu_cost_per_hour: Decimal = Field(default=Decimal("2.09"), ge=0)
    #: The Serverless rate the Owner budgets with (4.00 USD/h until a real bill settles 3.49).
    serverless_cost_per_hour: Decimal = Field(default=Decimal("4.00"), ge=0)
    request_timeout: float = Field(default=60, gt=0, le=300)
    poll_interval: float = Field(default=2, gt=0, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    job_timeout: float = Field(default=1800, gt=0, le=604800)
    #: The Owner's card «Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?».
    allow_infra_actions: bool = False
    auto_start: bool = False
    auto_stop: bool = False
    idle_shutdown_minutes: int = Field(default=15, ge=1)
    pod_id: str | None = None
    pod_cancel_path: str | None = None
    # --- Serverless GPU control (phase 1) ---
    #: EndpointWorkers.idleTimeout; 1 s is the documented minimum (his «oprit imediat»).
    idle_timeout_seconds: int = Field(default=1, ge=1, le=3600)
    #: workers.max while a paid step runs. One GPU at once: raising it is a code + ADR change.
    max_workers: int = Field(default=1, ge=1, le=1)
    #: Model load priced once per round (replaced by the bake-off's measurement).
    cold_start_seconds: int = Field(default=120, ge=0, le=900)
    #: The endpoint's per-request execution timeout (ms), sent explicitly, never a default.
    endpoint_timeout_ms: int = Field(default=2_400_000, ge=5_000, le=86_400_000)
    flashboot: Literal["OFF", "FLASHBOOT", "PRIORITY_FLASHBOOT"] = "FLASHBOOT"
    execution_timeout_cap_seconds: int = Field(default=2400, ge=5, le=86_400)
    still_item_budget_seconds: int = Field(default=180, ge=1, le=3600)
    clip_item_budget_seconds: int = Field(default=900, ge=1, le=7200)
    queue_wait_seconds: int = Field(default=900, ge=0, le=86_400)
    #: How long after the off request the studio waits for RunPod to show 0 running.
    off_grace_seconds: int = Field(default=60, ge=0, le=3600)
    off_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    #: A session not renewed for this long is forced off by the guard.
    session_stale_seconds: int = Field(default=300, ge=10, le=86_400)
    session_max_seconds: int = Field(default=14_400, ge=60, le=604_800)
    gpu_busy_wait_seconds: int = Field(default=600, ge=0, le=86_400)
    guard_interval_seconds: int = Field(default=60, ge=5, le=3600)
    guard_idle_interval_seconds: int = Field(default=600, ge=5, le=86_400)
    # --- Output bucket (S3-compatible; the keys live in the vault) ---
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = Field(default="auto", min_length=1, max_length=64)
    s3_prefix: str = "amn/"
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    url_ttl_seconds: int = Field(default=604_800, ge=60, le=604_800)
    model_routes: dict[str, str] = Field(
        default_factory=lambda: {
            "IMAGE_QUALITY": "Qwen-Image-2512",
            "IMAGE_HERO": "Qwen-Image-2512",
            "VIDEO_QUALITY": "LTX-2.5",
            "VIDEO_HERO": "LTX-2.5",
            "VIDEO_AUTO": "AUTO",
        }
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        if _WITHOUT_ENVIRONMENT.get():
            return (init_settings,)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    @field_validator("generation_base_url")
    @classmethod
    def secure_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.port not in (None, 443)
        ):
            raise ValueError("Use an HTTPS generation base URL without credentials or query")
        return value.rstrip("/")

    @field_validator("s3_endpoint_url")
    @classmethod
    def secure_bucket_url(cls, value: str | None) -> str | None:
        return _https_without_secrets(value) if value else None

    @field_validator("s3_bucket")
    @classmethod
    def bucket_name(cls, value: str | None) -> str | None:
        if value and not _BUCKET_NAME.fullmatch(value):
            raise ValueError("Bucket names are 3-63 characters of a-z, 0-9, dot and dash")
        return value or None

    @field_validator("s3_prefix")
    @classmethod
    def bucket_prefix(cls, value: str) -> str:
        if not _PREFIX.fullmatch(value):
            raise ValueError("The bucket prefix is lowercase, relative and ends with /")
        return value

    @field_validator("endpoint_id", "stills_endpoint_id", "motion_endpoint_id", "pod_id")
    @classmethod
    def safe_identifier(cls, value: str | None) -> str | None:
        if value and (len(value) > 100 or not all(c.isalnum() or c in "-_" for c in value)):
            raise ValueError("Invalid RunPod resource identifier")
        return value or None

    @field_validator("pod_cancel_path")
    @classmethod
    def cancellation_route(cls, value: str | None) -> str | None:
        if value and (
            not value.startswith("/")
            or value.count("{job_id}") != 1
            or "?" in value
            or "#" in value
            or ".." in value
        ):
            raise ValueError("Cancellation needs an explicit relative path with {job_id}")
        return value or None

    @model_validator(mode="after")
    def infra_policy(self) -> RunPodConfig:
        # auto_start/auto_stop drive a Pod; Serverless has no Pod to start, so a .env that
        # still says RUNPOD_AUTO_START never breaks a serverless studio (pricing, the page).
        if (
            self.mode == "pod"
            and (self.auto_start or self.auto_stop)
            and not self.allow_infra_actions
        ):
            raise ValueError("Automatic compute requires explicit infrastructure permission")
        return self

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and (
                self.mock
                or (
                    self.api_key.get_secret_value()
                    and (
                        (self.endpoint_id or self.stills_endpoint_id or self.motion_endpoint_id)
                        if self.mode == "serverless"
                        else self.generation_base_url
                    )
                )
            )
        )

    @property
    def hourly_rate(self) -> Decimal:
        """What one GPU hour is priced at: the Serverless budget rate, or the Pod rate."""
        return (
            self.serverless_cost_per_hour if self.mode == "serverless" else self.gpu_cost_per_hour
        )

    def endpoint_for(self, operation: Literal["image", "video"]) -> str | None:
        """The Serverless endpoint that serves stills (image) or motion (video)."""
        own = self.stills_endpoint_id if operation == "image" else self.motion_endpoint_id
        return own or self.endpoint_id

    def endpoints(self) -> list[tuple[str, str]]:
        """Every configured endpoint once, as (purpose, endpoint_id), image first."""
        seen: list[tuple[str, str]] = []
        for purpose in ("image", "video"):
            identifier = self.endpoint_for(purpose)  # type: ignore[arg-type]
            if identifier and identifier not in [e for _, e in seen]:
                seen.append((purpose, identifier))
        if self.endpoint_id and self.endpoint_id not in [e for _, e in seen]:
            seen.append(("image", self.endpoint_id))
        return seen

    def bucket(self) -> BucketConfig | None:
        """The output bucket, or None until every part of it is configured."""
        if not (
            self.s3_endpoint_url
            and self.s3_bucket
            and self.s3_access_key_id.get_secret_value()
            and self.s3_secret_access_key.get_secret_value()
        ):
            return None
        return BucketConfig(
            endpoint_url=self.s3_endpoint_url,
            bucket=self.s3_bucket,
            region=self.s3_region,
            prefix=self.s3_prefix,
            access_key_id=self.s3_access_key_id.get_secret_value(),
            secret_access_key=self.s3_secret_access_key,
            url_ttl_seconds=self.url_ttl_seconds,
        )

    @property
    def ready_for_generation(self) -> bool:
        """Configured, and (unless simulated) with a bucket to receive the outputs."""
        return self.configured and (self.mock or self.bucket() is not None)

    def route(self, operation: str, quality: str, model: str | None) -> str:
        if model and model.upper() != "AUTO":
            return self.model_routes.get(model, model)
        logical = f"{operation.upper()}_{quality.upper()}"
        if logical not in self.model_routes:
            raise ValueError("No configured route for this generation quality")
        return self.model_routes[logical]

    @classmethod
    def from_integration(
        cls, config: Mapping[str, Any], secrets: Mapping[str, str]
    ) -> RunPodConfig:
        """One integration's config (strings from its form) and its vault secrets.

        A value the environment adds (RUNPOD_* in .env) never makes this raise: the callers
        are pricing, the page and the GPU off, which must work whatever an old .env says.
        When the environment is what breaks it, the integration alone is used (logged). The
        integration's own invalid values still raise: they are what its form typed.
        """
        public = {
            k: v
            for k, v in config.items()
            if k in cls.model_fields and k not in SECRET_FIELDS and v != ""
        }
        for name in SECRET_FIELDS:
            value = secrets.get(name, "")
            if value:
                public[name] = value
        try:
            return cls(**public)
        except ValidationError:
            with _without_environment():
                built = cls(**public)
            logger.warning("runpod_environment_ignored")
            return built

    @classmethod
    def connection(cls, values: dict[str, Any], key: str = "") -> RunPodConfig:
        """Legacy wrapper: the public config and the API key only."""
        return cls.from_integration(values, {"api_key": key} if key else {})
