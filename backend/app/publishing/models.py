"""Phase 6 SQLAlchemy ORM models for Autonomous Publishing & Distribution."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class ChannelRecord(Base):
    """A configured distribution channel (e.g. Channel A Main, Channel B Office Serial)."""

    __tablename__ = "channel_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_name: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MAIN_FACTUAL")
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="YOUTUBE")
    remote_channel_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credentials_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    upload_privacy_default: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    # UNCONFIGURED | CONFIGURED | AUTHENTICATED | ERROR | ACTIVE
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNCONFIGURED")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    last_sync_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    publications: Mapped[list[PublicationRecord]] = relationship(
        "PublicationRecord", back_populates="channel", cascade="all, delete-orphan"
    )
    brand_assets: Mapped[list[ChannelBrandAsset]] = relationship(
        "ChannelBrandAsset", back_populates="channel", cascade="all, delete-orphan"
    )


class ChannelBrandAsset(Base):
    """Brand assets (avatar, banner, watermark, tagline) associated with a channel."""

    __tablename__ = "channel_brand_asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content_or_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    channel: Mapped[ChannelRecord] = relationship("ChannelRecord", back_populates="brand_assets")


class PublicationRecord(Base):
    """Lifecycle record of an individual video upload/publishing attempt."""

    __tablename__ = "publication_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=False
    )
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_asset.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    privacy_status: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    # DRAFT_INTENT | VALIDATED | STARTED | REMOTE_CONFIRMED | REMOTE_UNKNOWN | SCHEDULED | PUBLISHED | FAILED_RETRYABLE | FAILED_FINAL | NEEDS_RECONCILIATION | BLOCKED_GATE
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT_INTENT")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remote_video_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scheduled_publish_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "idempotency_key", name="uq_channel_idempotency"),
    )

    channel: Mapped[ChannelRecord] = relationship("ChannelRecord", back_populates="publications")
