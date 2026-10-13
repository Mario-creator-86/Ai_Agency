"""Phase 4: factual intelligence, topics, sources, claims, scripts, hooks."""

import sqlalchemy as sa
from alembic import op

revision = "0004_phase4_factual"
down_revision = "0003_phase2_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_idea",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("target_audience", sa.String(100), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("selected_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )
    op.create_table(
        "source_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic_id", sa.String(36), sa.ForeignKey("topic_idea.id"), nullable=True),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("sanitized_content", sa.Text(), nullable=False),
        sa.Column("credibility_score", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )
    op.create_table(
        "factual_claim",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("source_snapshot.id"), nullable=True),
        sa.Column("topic_id", sa.String(36), sa.ForeignKey("topic_idea.id"), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(50), nullable=False),
        sa.Column("importance", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("verifier_notes", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )
    op.create_table(
        "script_draft",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("topic_id", sa.String(36), sa.ForeignKey("topic_idea.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("voiceover_full_text", sa.Text(), nullable=False),
        sa.Column("scenes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("unverified_claim_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )
    op.create_table(
        "hook_option",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("script_id", sa.String(36), sa.ForeignKey("script_draft.id"), nullable=False),
        sa.Column("hook_text", sa.Text(), nullable=False),
        sa.Column("hook_technique", sa.String(50), nullable=False),
        sa.Column("retention_score_estimate", sa.Float(), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
