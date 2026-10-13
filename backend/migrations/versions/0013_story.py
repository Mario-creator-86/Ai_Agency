"""Phase 9 tables: the daily studio log and the Office Serial episodes drawn from it.

Additive. The two tables are separate on purpose — `../architecture/07_STORY_ENGINE.md` keeps
Operational Truth and the Narrative Layer apart, and an episode references events rather than
touching them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_story"
down_revision = "0012_workforce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_studio_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("business_date", sa.String(10), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("event_counts_json", sa.JSON(), nullable=False),
        sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("roster_json", sa.JSON(), nullable=False),
        sa.Column("notable_events_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="CLOSED"),
        sa.Column("closed_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint("total_events >= 0", name="ck_daily_log_counts_positive"),
    )
    # One log per business date: a second one would give an episode a choice of records to be
    # grounded against, which is no grounding at all.
    op.create_index("ix_daily_log_date", "daily_studio_log", ["business_date"], unique=True)

    op.create_table(
        "story_episode",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("log_id", sa.String(36), sa.ForeignKey("daily_studio_log.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("beats_json", sa.JSON(), nullable=False),
        sa.Column("grounded_event_ids_json", sa.JSON(), nullable=False),
        sa.Column("continuity_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("written_by_agent_id", sa.String(36), sa.ForeignKey("agent.id")),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_story_episode_log", "story_episode", ["log_id", "created_at"])


def downgrade() -> None:
    op.drop_table("story_episode")
    op.drop_table("daily_studio_log")
