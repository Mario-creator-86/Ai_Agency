"""Phase 6 SQLAlchemy ORM models for Autonomous Publishing & Distribution."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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
    upload_privacy_default: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private"
    )
    #: The publish policy the Owner sets for autonomous uploads (migration 0037). Measured
    #: before it existed: the daily run hardcoded "private" and `upload_privacy_default`
    #: above was read by nobody on a publish path. `autonomous_privacy` is what the run asks
    #: for; "public" is honoured only while `public_publish_enabled` is True and the studio
    #: is in PRODUCTION (`resolve_publish_visibility`). A delay turns a public release into a
    #: private upload with a publishAt, which is how YouTube schedules one. The version and
    #: the event name the Owner command that put this policy in force, so a publication can
    #: say which policy authorised its visibility. Changed only by `change_publish_policy`.
    autonomous_privacy: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    public_publish_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publish_delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_changed_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
    # UNCONFIGURED | CONFIGURED | AUTHENTICATED | ERROR | ACTIVE
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNCONFIGURED")
    #: How production may choose technology for this channel. FLEXIBLE: every level of the
    #: configuration hierarchy may override the level above it, per video. CONSISTENCY_LOCKED:
    #: overrides never touch a locked character identity. NULL until the seed fills it from the
    #: stored channel type; editable through the API afterwards, never decided in code.
    production_policy: Mapped[str | None] = mapped_column(String(30), nullable=True)
    #: Channel-level defaults per purpose ({"voice": {...}, "image": {...}, "video": {...}}).
    production_defaults_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Rules per series/format key, each shaped like production_defaults_json.
    series_rules_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: False freezes production at the channel defaults (episode/scene overrides are ignored).
    allow_production_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    # DRAFT_INTENT | VALIDATED | STARTED | REMOTE_CONFIRMED | REMOTE_UNKNOWN | SCHEDULED
    # | PUBLISHED | FAILED_RETRYABLE | FAILED_FINAL | NEEDS_RECONCILIATION | BLOCKED_GATE
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT_INTENT")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remote_video_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scheduled_publish_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: The channel policy version that authorised this publication's visibility (migration
    #: 0036). NULL for a private upload, which needs no authorisation, and for every row
    #: written before the policy existed. The sixth gate check refuses an unlisted or public
    #: publication without it, so an audit can say which policy published what.
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
