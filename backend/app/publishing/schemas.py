"""Phase 6 Pydantic schemas for Autonomous Publishing & Distribution."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChannelView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_name: str
    channel_type: str
    platform: str
    remote_channel_id: str | None
    credentials_ref: str | None
    upload_privacy_default: str
    status: str
    # Production policy: FLEXIBLE (technology may change per video) or CONSISTENCY_LOCKED
    # (locked character identities are never replaced by production). NULL until seeded.
    production_policy: str | None = None
    production_defaults_json: dict = {}
    series_rules_json: dict = {}
    allow_production_override: bool = True
    created_at: str
    last_sync_at: str | None
    # The binding endpoint refuses a stale write, so the screen that offers the
    # binding has to know which version of the row it is looking at.
    event_id: str | None = None
    # Which OAuth connection this slot publishes through. Filled by `list_channels` from the
    # connection rows, never stored twice: `credentials_ref` remains the single source.
    youtube_connection_id: str | None = None
    youtube_connection_name: str | None = None
    youtube_channel_title: str | None = None
    youtube_connection_status: str | None = None
    publisher_ready: bool = False


class ConfigureChannelCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    channel_name: str | None = Field(default=None, max_length=100)
    remote_channel_id: str | None = Field(default=None, max_length=100)
    credentials_ref: str | None = Field(default=None, max_length=200)
    upload_privacy_default: Literal["private", "unlisted", "public"] = "private"


class CreatePublicationIntentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    channel_id: str
    media_asset_id: str
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    privacy_status: Literal["private", "unlisted", "public"] = "private"
    idempotency_key: str | None = Field(default=None, max_length=100)
    scheduled_publish_time: str | None = None


class PublicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    media_asset_id: str
    title: str
    description: str
    tags_json: list[str]
    privacy_status: str
    status: str
    idempotency_key: str
    remote_video_id: str | None
    remote_url: str | None
    scheduled_publish_time: str | None
    published_at: str | None
    error_detail: str | None
    created_at: str


class GateCheckItem(BaseModel):
    check_name: str
    passed: bool
    detail: str


class PublishingGateEvaluationView(BaseModel):
    media_asset_id: str
    channel_id: str
    eligible: bool
    checks: list[GateCheckItem]
    reasons: list[str]
