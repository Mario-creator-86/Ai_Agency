"""Phase 5 Pydantic schemas for media production, storyboarding, assets, and QC."""

from __future__ import annotations

from typing import Any

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


class StoryboardView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    script_draft_id: str
    title: str
    visual_style: str
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
