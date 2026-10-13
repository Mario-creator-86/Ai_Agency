"""Phase 7 analytics tables: audience snapshots, experiments, strategy, recommendations.

Additive schema only. Creating these tables does not create any measurement — a snapshot row
exists only after a configured analytics provider reported real figures for a video the
platform is actually serving.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_phase7_analytics"
down_revision = "0009_unverified_seeded_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_strategy",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("topic_weights_json", sa.JSON(), nullable=False),
        sa.Column("hook_weights_json", sa.JSON(), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("cooldown_until", sa.String(40)),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
    )
    op.create_index("ix_content_strategy_channel", "content_strategy", ["channel_id", "is_active"])

    op.create_table(
        "analytics_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "publication_id",
            sa.String(36),
            sa.ForeignKey("publication_record.id"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("window", sa.String(20), nullable=False, server_default="LIFETIME"),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watch_time_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_view_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subscribers_gained", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subscribers_lost", sa.Integer(), nullable=False, server_default="0"),
        # The provider's own response, kept verbatim so a stored figure can always be traced
        # back to what the platform actually said.
        sa.Column("raw_metrics_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint("views >= 0 AND impressions >= 0", name="ck_snapshot_counts_positive"),
        sa.CheckConstraint(
            "average_view_percentage >= 0 AND average_view_percentage <= 100",
            name="ck_snapshot_retention_is_a_percentage",
        ),
    )
    op.create_index(
        "ix_analytics_snapshot_publication",
        "analytics_snapshot",
        ["publication_id", "window", "snapshot_at"],
    )

    op.create_table(
        "content_experiment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("target_metric", sa.String(50), nullable=False, server_default="RETENTION_RATE"),
        sa.Column("guardrail_metrics_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("control_variant", sa.String(100), nullable=False),
        sa.Column("treatment_variant", sa.String(100), nullable=False),
        sa.Column("sample_size_target", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("control_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("treatment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("outcome_decision", sa.Text()),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("concluded_at", sa.String(40)),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
    )
    op.create_index("ix_content_experiment_channel", "content_experiment", ["channel_id", "status"])

    op.create_table(
        "director_recommendation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("strategy_id", sa.String(36), sa.ForeignKey("content_strategy.id")),
        sa.Column("recommendation_type", sa.String(50), nullable=False),
        sa.Column("target_entity", sa.String(100), nullable=False),
        sa.Column("suggested_weight_change", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("mean_retention", sa.Float(), nullable=False),
        sa.Column("mean_ctr", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
        sa.Column("created_at", sa.String(40), nullable=False),
        # A recommendation that changes the editorial strategy must rest on more than one
        # observation; the service enforces N >= 3 and the schema refuses anything smaller.
        sa.CheckConstraint("sample_size >= 3", name="ck_recommendation_has_evidence"),
        sa.CheckConstraint(
            "suggested_weight_change >= -0.20 AND suggested_weight_change <= 0.20",
            name="ck_recommendation_change_is_bounded",
        ),
    )
    op.create_index(
        "ix_director_recommendation_channel", "director_recommendation", ["channel_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("director_recommendation")
    op.drop_table("content_experiment")
    op.drop_table("analytics_snapshot")
    op.drop_table("content_strategy")
