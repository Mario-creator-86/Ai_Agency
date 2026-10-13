from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Integration(Base):
    __tablename__ = "integration"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict] = mapped_column(JSON)
    encrypted_secrets: Mapped[str] = mapped_column(Text)
    secret_fields: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    checked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class ServiceSelection(Base):
    __tablename__ = "service_selection"
    purpose: Mapped[str] = mapped_column(String(40), primary_key=True)
    integration_id: Mapped[str | None] = mapped_column(ForeignKey("integration.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(ForeignKey("domain_event.event_id"))


class ProviderResource(Base):
    """Account-scoped API inventory; research annotations survive discovery refreshes."""

    __tablename__ = "provider_resource"
    __table_args__ = (UniqueConstraint("integration_id", "resource_type", "remote_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    integration_id: Mapped[str] = mapped_column(ForeignKey("integration.id", ondelete="CASCADE"))
    resource_type: Mapped[str] = mapped_column(String(10))
    remote_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(300))
    api_metadata: Mapped[dict] = mapped_column(JSON)
    api_available: Mapped[bool] = mapped_column(Boolean)
    last_seen_at: Mapped[str] = mapped_column(String(40))
    pricing: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    availability_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    metadata_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_updated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_version: Mapped[int] = mapped_column(Integer, default=0)
    #: Where this model stands with the studio (migration 0031). A model the vendor
    #: exposed today is DISCOVERED, then QUARANTINE until something is known about it;
    #: only CANDIDATE, PRODUCTION and PREFERRED may film a scene that will be published.
    production_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PRODUCTION")
    #: The price's provenance: which version, when and how it was verified, and what it
    #: was before. A price that changed is a fact with a date, not a silent overwrite.
    pricing_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_verified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: DOCUMENTED (a vendor page) | ESTIMATED (a dry run) | BILLED (a render's charge).
    price_verification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    previous_pricing_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lifecycle_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderDiscovery(Base):
    __tablename__ = "provider_discovery"
    integration_id: Mapped[str] = mapped_column(
        ForeignKey("integration.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20))
    last_attempt_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_success_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_refresh_at: Mapped[str] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)


class MediaProductionConfig(Base):
    __tablename__ = "media_production_config"
    integration_id: Mapped[str] = mapped_column(
        ForeignKey("integration.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    voice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: A connection that also makes stills (Runway) keeps its image default apart from its
    #: video default: one model cannot serve both purposes.
    image_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: These two are the Organization default for this connection. When False, channel, series,
    #: episode and scene levels may not replace them; character identity locks still apply.
    allow_production_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(40))


class ModelOutcome(Base):
    """What one generation actually produced, so the studio learns from its own results.

    A model's worth is not a number on a vendor page: it is what it delivered, for what it
    cost, in the kind of scene the studio asked for. Every generation is recorded with its
    environment and kind, because a cheap functional test must never teach the studio that a
    model's picture is poor — only a benchmark or a real production scene may (migration 0031).
    """

    __tablename__ = "model_outcome"
    __table_args__ = (
        Index(
            "ix_model_outcome_model",
            "integration_id",
            "remote_id",
            "purpose",
            "scene_category",
        ),
        Index("ix_model_outcome_kind", "run_kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    integration_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("integration.id"), nullable=False
    )
    remote_id: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    #: TEST_FUNCTIONAL | TEST_BENCHMARK | PRODUCTION.
    run_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    scene_category: Mapped[str] = mapped_column(String(40), nullable=False, default="GENERAL")
    quality_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seconds_requested: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    seconds_accepted: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: TECHNICAL | QUALITY | NONE — why a shot was not accepted, so a retry is reasoned.
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("video_render_job.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
