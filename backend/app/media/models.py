"""Phase 5 ORM models: character bible, storyboards, scenes, media assets,
render jobs, QC reports."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class CharacterBible(Base):
    """Canonical character bible entry for recurring agents/employees."""

    __tablename__ = "character_bible"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    palette_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    face_hair_desc: Mapped[str] = mapped_column(Text, nullable=False)
    outfit_desc: Mapped[str] = mapped_column(Text, nullable=False)
    props_desc: Mapped[str] = mapped_column(Text, nullable=False)
    role_symbols: Mapped[str] = mapped_column(String(200), nullable=False)
    voice_profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Who the character is, beyond how they look and sound. Narrative only: none of this may
    # change what an agent is allowed to do, which model it runs on, or whether a gate passes.
    personality_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    speech_style_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expressions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    behavior_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Declared reference-image slots. A slot holds a stored asset id or null; it never holds a
    # description standing in for an image that was never produced.
    reference_assets_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The voice this character is produced with: {"integration_id", "voice_id", "model_id",
    #: "voice_settings", "language", "pronunciation_rules"}. Points at discovered resources;
    #: no id in it exists anywhere in source.
    voice_binding_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: {"voice": bool, "visual": bool, "personality": bool, "speech_style": bool}. A locked
    #: field is replaced only by an APPROVED CharacterIdentityChange, never by production.
    identity_locks_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Technology the character may be produced with while keeping its identity:
    #: [{"integration_id", "model_id", "approved_at", "change_id"}].
    approved_fallbacks_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: UNVERIFIED | CONSISTENT | CHANGE_PENDING | DRIFT_SUSPECTED
    consistency_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNVERIFIED"
    )
    forbidden_deviations: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class Storyboard(Base):
    """Storyboard linking an approved ScriptDraft to a sequence of visual/audio scenes."""

    __tablename__ = "storyboard"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("script_draft.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    visual_style: Mapped[str] = mapped_column(String(50), nullable=False, default="MOTION_GRAPHIC")
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="9:16")
    target_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    # DRAFT | APPROVED | IN_PRODUCTION | COMPLETED | REJECTED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    total_scenes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: The channel this video is produced for, and the series/format inside it. Both optional:
    #: a storyboard without them resolves at the Organization level only.
    channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel_record.id"), nullable=True
    )
    series_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: Episode/video-level production choices per purpose.
    production_overrides_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The master visual bible this film's every shot inherits (migration 0032): style,
    #: period, world, palette, lighting philosophy, camera language, continuity rules and
    #: what to avoid. One film, one look — not several AI clips that happen to be adjacent.
    visual_bible_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )

    scenes: Mapped[list[StoryboardScene]] = relationship(
        "StoryboardScene",
        back_populates="storyboard",
        cascade="all, delete-orphan",
        order_by="StoryboardScene.scene_index",
    )


class StoryboardScene(Base):
    """An individual scene in a storyboard with visual framing and voiceover cue."""

    __tablename__ = "storyboard_scene"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    storyboard_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("storyboard.id"), nullable=False
    )
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    visual_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MOTION_GRAPHIC")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    voiceover_segment: Mapped[str] = mapped_column(Text, nullable=False)
    shot_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MEDIUM")
    transition_in: Mapped[str] = mapped_column(String(50), nullable=False, default="CUT")
    character_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    claim_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: Scene-level production choices per purpose.
    production_overrides_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The full prompt package for this shot (migration 0032): subject, action, environment,
    #: camera, lighting, composition, motion, emotion, background, continuity, audio intent,
    #: transition, negatives and story purpose. `visual_prompt` holds what is actually sent
    #: to the model, composed from this, so the whole render path is unchanged by it.
    prompt_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Why this shot is in the film: HOOK, SETUP, DEVELOPMENT, EVIDENCE, REVEAL, PAYOFF,
    #: ENDING or CTA. A shot that serves nothing is cut or redesigned, not filmed.
    story_purpose: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    storyboard: Mapped[Storyboard] = relationship("Storyboard", back_populates="scenes")


class MediaAsset(Base):
    """An immutable media file or artifact with SHA-256 provenance tracking."""

    __tablename__ = "media_asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # IMAGE | VIDEO | VOICEOVER | MUSIC | SUBTITLE | RENDERED_VIDEO
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uri_or_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="STUDIO_INTERNAL"
    )
    remote_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ORIGINAL_AI_GENERATED | PROPRIETARY_STUDIO | PUBLIC_DOMAIN | LICENSED
    license_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="PROPRIETARY_STUDIO"
    )
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class VideoRenderJob(Base):
    """A rendering job tracking video assembly execution."""

    __tablename__ = "video_render_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    storyboard_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("storyboard.id"), nullable=False
    )
    output_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("media_asset.id"), nullable=True
    )
    # PENDING | RENDERING | COMPLETED | FAILED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    render_engine: Mapped[str] = mapped_column(
        String(50), nullable=False, default="DETERMINISTIC_ASSEMBLER"
    )
    command_args_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: What this render actually used, per purpose and per scene: integration, model, voice,
    #: which hierarchy level decided it, whether a character lock applied, retries, timings and
    #: a cost estimate when pricing is known. Analytics joins here through the output asset.
    production_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class QualityControlReport(Base):
    """Immutable QC report evaluating technical, factual, and visual conformance."""

    __tablename__ = "quality_control_report"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_asset.id"), nullable=False
    )
    # PASSED | FAILED | FLAGGED_FOR_REVIEW
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    checks_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verified_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class CharacterIdentityChange(Base):
    """A proposed change to a locked part of a character's identity.

    PROPOSED -> TESTING -> APPROVED | REJECTED. Only APPROVED rewrites the bible, in one
    transaction with the event that records who approved it. A newer or cheaper model is never
    a reason for the system to take this path on its own: proposals are made by people or by
    agents in their roles, and decided by the Director or the Owner.
    """

    __tablename__ = "character_identity_change"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PROPOSED','TESTING','APPROVED','REJECTED')",
            name="ck_identity_change_status",
        ),
        CheckConstraint(
            "field IN ('voice','visual','personality','speech_style')",
            name="ck_identity_change_field",
        ),
        Index("ix_identity_change_character", "character_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("character_bible.id"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(20), nullable=False)
    #: The full replacement for the field (a voice binding, a visual profile, ...).
    proposed_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    #: What the field held when the change was proposed, so the decision is reviewable.
    previous_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROPOSED")
    proposed_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    #: Test evidence attached while TESTING (renders compared, QA notes).
    test_evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )


class EditorialReview(Base):
    """The Director's verdict on a finished film before publication (migration 0029)."""

    __tablename__ = "editorial_review"
    __table_args__ = (Index("ix_editorial_review_asset", "media_asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_asset.id"), nullable=False
    )
    storyboard_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("storyboard.id"), nullable=True
    )
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    story: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reviewer_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent.id"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_run.id"), nullable=True
    )
    frames_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_event.event_id"), nullable=True
    )
