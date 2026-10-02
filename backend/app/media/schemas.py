"""Phase 5 Pydantic schemas for media production, storyboarding, assets, and QC."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CharacterBibleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employee_id: str | None
    canonical_name: str
    palette_json: dict[str, Any]
    face_hair_desc: str
    outfit_desc: str
    props_desc: str
    role_symbols: str
    voice_profile_json: dict[str, Any]
    personality_json: dict[str, Any]
    speech_style_json: dict[str, Any]
    expressions_json: dict[str, Any]
    behavior_json: dict[str, Any]
    reference_assets_json: dict[str, Any]
    voice_binding_json: dict[str, Any]
    identity_locks_json: dict[str, Any]
    approved_fallbacks_json: list[dict[str, Any]]
    consistency_status: str
    forbidden_deviations: str
    version: int
    created_at: str


class CreateCharacterBibleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(min_length=1, max_length=100)
    employee_id: str | None = None
    palette_json: dict[str, Any] = Field(default_factory=dict)
    face_hair_desc: str = Field(min_length=1)
    outfit_desc: str = Field(min_length=1)
    props_desc: str = Field(default="")
    role_symbols: str = Field(default="")
    voice_profile_json: dict[str, Any] = Field(default_factory=dict)
    personality_json: dict[str, Any] = Field(default_factory=dict)
    speech_style_json: dict[str, Any] = Field(default_factory=dict)
    expressions_json: dict[str, Any] = Field(default_factory=dict)
    behavior_json: dict[str, Any] = Field(default_factory=dict)
    reference_assets_json: dict[str, Any] = Field(default_factory=dict)
    forbidden_deviations: str = Field(default="")


class StoryboardSceneView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    storyboard_id: str
    scene_index: int
    visual_prompt: str
    visual_type: str
    duration_seconds: float
    voiceover_segment: str
    shot_type: str
    transition_in: str
    character_ids_json: list[str]
    claim_ids_json: list[str]
    created_at: str
    #: LIVE (filmed), DATA_CARD, TITLE_CARD or BLACK (composed locally, 0 credits). Declared
    #: so the API stops stripping what `get_storyboard` returns (migration 0048).
    scene_kind: str = "LIVE"
    #: The card's verified numbers ({title, bars[...], highlight}, or {cta}); None for LIVE.
    card_json: dict[str, Any] | None = None


class StoryboardView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    script_draft_id: str
    title: str
    #: The caller's named style, or "PER_SCENE" since each scene carries its own kind.
    visual_style: str | None
    aspect_ratio: str
    target_duration_seconds: int
    status: str
    total_scenes: int
    created_at: str
    scenes: list[StoryboardSceneView] = Field(default_factory=list)


class GenerateStoryboardCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_style: str = Field(default="MOTION_GRAPHIC", max_length=50)
    aspect_ratio: str = Field(default="9:16", max_length=20)


class MediaAssetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_type: str
    uri_or_path: str
    file_size_bytes: int
    mime_type: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    provider_name: str
    license_status: str
    provenance_hash: str
    created_at: str


class RenderJobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    storyboard_id: str
    output_asset_id: str | None
    status: str
    render_engine: str
    command_args_json: list[str]
    production_json: dict[str, Any] = {}
    execution_log: str | None
    started_at: str
    finished_at: str | None
    duration_ms: float | None


class QCReportView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    media_asset_id: str
    status: str
    score: float
    checks_json: dict[str, Any]
    failure_reasons_json: list[str]
    verified_at: str


class SheetStepCommand(BaseModel):
    """The Owner's press of a step on the shooting sheet: the sheet he was shown, by hash.

    ``allow_over_budget`` is his explicit consent to go over the daily budget (and, in
    PRODUCTION, the film's own ceiling) for this step; without it a step that would exceed
    them is refused (409). Neither field buys anything on its own: the step still needs his
    yes for this very sheet.

    ``command_id`` makes a press safe to repeat (MONEY-04): a step that bought under an id
    answers the same id again with what it bought, ``replayed: true``, and buys nothing; the
    same id with another body is refused (409).
    """

    model_config = ConfigDict(extra="forbid")

    plan_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    allow_over_budget: bool = False
    command_id: UUID | None = None


class SceneModelCommand(BaseModel):
    """The Owner's choice of a filmed scene's motion model on the sheet: a model id,
    LOCAL_MOVE (the approved still moved locally, 0 credits), or null for the policy's."""

    model_config = ConfigDict(extra="forbid")

    model_id: str | None = Field(default=None, min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class TakeDecisionCommand(BaseModel):
    """The Owner's look at a paid take on the contact sheet."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    note: str | None = Field(default=None, max_length=500)
