from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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
    #: These two are the Organization default for this connection. When False, channel, series,
    #: episode and scene levels may not replace them; character identity locks still apply.
    allow_production_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(String(40))
