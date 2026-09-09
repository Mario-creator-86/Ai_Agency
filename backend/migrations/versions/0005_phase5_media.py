"""Phase 5: media production, character bible, storyboards, scenes, assets, render jobs, and QC reports."""

import sqlalchemy as sa
from alembic import op

revision = "0005_phase5_media"
down_revision = "0004_phase4_factual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_bible",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("canonical_name", sa.String(100), nullable=False, unique=True),
        sa.Column("palette_json", sa.JSON(), nullable=False),
        sa.Column("face_hair_desc", sa.Text(), nullable=False),
        sa.Column("outfit_desc", sa.Text(), nullable=False),
        sa.Column("props_desc", sa.Text(), nullable=False),
        sa.Column("role_symbols", sa.String(200), nullable=False),
        sa.Column("voice_profile_json", sa.JSON(), nullable=False),
        sa.Column("forbidden_deviations", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, default=1),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "storyboard",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("script_draft_id", sa.String(36), sa.ForeignKey("script_draft.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("visual_style", sa.String(50), nullable=False),
        sa.Column("aspect_ratio", sa.String(20), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("total_scenes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "storyboard_scene",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storyboard_id", sa.String(36), sa.ForeignKey("storyboard.id"), nullable=False),
        sa.Column("scene_index", sa.Integer(), nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("visual_type", sa.String(50), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("voiceover_segment", sa.Text(), nullable=False),
        sa.Column("shot_type", sa.String(50), nullable=False),
        sa.Column("transition_in", sa.String(50), nullable=False),
        sa.Column("character_ids_json", sa.JSON(), nullable=False),
        sa.Column("claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "media_asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("uri_or_path", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("remote_job_id", sa.String(200), nullable=True),
        sa.Column("license_status", sa.String(50), nullable=False),
        sa.Column("provenance_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "video_render_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storyboard_id", sa.String(36), sa.ForeignKey("storyboard.id"), nullable=False),
        sa.Column("output_asset_id", sa.String(36), sa.ForeignKey("media_asset.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("render_engine", sa.String(50), nullable=False),
        sa.Column("command_args_json", sa.JSON(), nullable=False),
        sa.Column("execution_log", sa.Text(), nullable=True),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "quality_control_report",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_asset_id", sa.String(36), sa.ForeignKey("media_asset.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("failure_reasons_json", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
