"""Phase 6 Pydantic schemas for Autonomous Publishing & Distribution."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PrivacyStatus = Literal["private", "unlisted", "public"]


class ChannelView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_name: str
    channel_type: str
    platform: str
    remote_channel_id: str | None
    credentials_ref: str | None
    upload_privacy_default: str
    # The publish policy for autonomous uploads, set only by the publish-policy command. The
    # defaults are the safe reading of a row written before the policy existed.
    autonomous_privacy: str = "private"
    public_publish_enabled: bool = False
    publish_delay_minutes: int = 0
    policy_version: int = 1
    policy_changed_event_id: str | None = None
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


class PublishPolicyCommand(BaseModel):
    """The Owner sets how a channel's autonomous uploads are released.

    The same shape as the autonomy stop and the environment command, for the same reason:
    whether a film the studio made on its own can be seen by anyone is the Owner's decision,
    so it is a versioned command recorded in the ledger, never a setting a page can flip or
    an agent can assume. `expected_version` is the channel's `policy_version`. A field left
    out keeps its value; a field the command does not know is refused, not ignored.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    autonomous_privacy: PrivacyStatus | None = None
    public_publish_enabled: bool | None = None
    # A delay before a scheduled public release. Thirty days is YouTube's own horizon for a
    # publishAt; a longer one is a wrong number, not a plan.
    publish_delay_minutes: int | None = Field(default=None, ge=0, le=43200)


class PublishPolicyResult(BaseModel):
    command_id: str
    status: Literal["COMMITTED", "NO_CHANGE"]
    channel: ChannelView
    event_id: str | None


class CreatePublicationIntentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    channel_id: str
    media_asset_id: str
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    privacy_status: PrivacyStatus = "private"
    idempotency_key: str | None = Field(default=None, max_length=100)
    scheduled_publish_time: str | None = None

    @model_validator(mode="after")
    def _a_scheduled_release_is_a_private_upload(self) -> CreatePublicationIntentCommand:
        # YouTube schedules a release as a private upload with a publishAt; a publishAt on an
        # unlisted or public upload is refused by the platform, so it is refused here first.
        if self.scheduled_publish_time and self.privacy_status != "private":
            raise ValueError(
                "O lansare programată se încarcă privat: privacy_status trebuie să fie "
                "„private” când scheduled_publish_time este setat."
            )
        return self


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
    # Which channel policy authorised the visibility; None for a private upload.
    policy_version: int | None = None
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
