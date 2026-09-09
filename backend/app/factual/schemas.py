"""Phase 4 Pydantic schemas for Factual Intelligence."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposeTopicCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    title: str = Field(min_length=3, max_length=200)
    topic: str = Field(min_length=2, max_length=200)
    angle: str = Field(min_length=5, max_length=1000)
    target_audience: str = Field(default="general", max_length=100)


class TopicIdeaView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    topic: str
    angle: str
    target_audience: str
    novelty_score: float
    status: str
    created_at: str
    selected_at: str | None = None
    event_id: str | None = None


class IngestSourceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    topic_id: str | None = None
    url: str = Field(min_length=5, max_length=1000)
    title: str = Field(min_length=2, max_length=300)
    publisher: str = Field(min_length=2, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    raw_content: str = Field(min_length=10, max_length=100000)
    credibility_score: float = Field(default=0.8, ge=0.0, le=1.0)


class SourceSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    topic_id: str | None
    url: str
    title: str
    publisher: str
    author: str | None
    content_hash: str
    sanitized_content: str
    credibility_score: float
    fetched_at: str
    event_id: str | None = None


class ExtractClaimItem(BaseModel):
    claim_text: str = Field(min_length=5, max_length=2000)
    claim_type: Literal["STATISTIC", "HISTORICAL_EVENT", "SCIENTIFIC_FACT", "QUOTE", "GENERAL"] = (
        "GENERAL"
    )
    importance: Literal["CRITICAL", "SUPPORTING", "FLAVOR"] = "SUPPORTING"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ExtractClaimsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    source_id: str
    topic_id: str | None = None
    claims: list[ExtractClaimItem] = Field(min_length=1, max_length=50)


class VerifyClaimCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    status: Literal["SUPPORTED", "REFUTED", "UNVERIFIED"]
    confidence: float = Field(ge=0.0, le=1.0)
    verifier_notes: str = Field(min_length=3, max_length=2000)
    evidence_text: str | None = Field(default=None, max_length=4000)


class ApproveScriptCommand(BaseModel):
    """Owner approval of a script draft; the factual gate is re-run at approval time."""

    model_config = ConfigDict(extra="forbid")
    command_id: UUID


class FactualClaimView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str | None
    topic_id: str | None
    claim_text: str
    claim_type: str
    importance: str
    status: str
    confidence: float
    evidence_text: str | None
    verifier_notes: str | None
    verified_at: str | None
    created_at: str
    event_id: str | None = None


class GenerateScriptCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    topic_id: str
    title: str = Field(min_length=3, max_length=200)
    target_duration_seconds: int = Field(default=50, ge=15, le=180)
    voiceover_full_text: str = Field(min_length=20, max_length=10000)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    referenced_claim_ids: list[str] = Field(min_length=1, max_length=50)


class ScriptDraftView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    topic_id: str
    version: int
    title: str
    target_duration_seconds: int
    voiceover_full_text: str
    scenes_json: list
    status: str
    claim_ids_json: list
    unverified_claim_ids_json: list
    created_at: str
    event_id: str | None = None


class CreateHookOptionItem(BaseModel):
    hook_text: str = Field(min_length=5, max_length=500)
    hook_technique: Literal[
        "CURIOSITY_GAP", "CONTRARIAN", "STATISTIC_SHOCK", "QUESTION", "STORY_IN_MEDIA_RES"
    ] = "CURIOSITY_GAP"
    retention_score_estimate: float = Field(default=7.0, ge=0.0, le=10.0)


class GenerateHooksCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    script_id: str
    hooks: list[CreateHookOptionItem] = Field(min_length=1, max_length=10)


class HookOptionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    script_id: str
    hook_text: str
    hook_technique: str
    retention_score_estimate: float
    is_selected: bool
    created_at: str
