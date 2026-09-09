"""Phase 5 ORM models: character bible, storyboards, scenes, media assets,
render jobs, QC reports."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
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
