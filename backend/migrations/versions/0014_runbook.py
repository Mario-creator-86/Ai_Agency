"""Phase 10 tables: daily runs and safe-mode periods.

Additive. A run row is a record of what happened, so nothing here changes how the studio behaves
until a run is actually executed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_runbook"
down_revision = "0013_story"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("business_date", sa.String(10), nullable=False),
        # Stored with the run: "the studio ran today" means something different on a day when
        # half the capabilities were missing, and that difference has to survive in the record.
        sa.Column("preflight_status", sa.String(20), nullable=False),
        sa.Column("preflight_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("stages_json", sa.JSON(), nullable=False),
        sa.Column("stages_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stages_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stopped_at_stage", sa.String(60)),
        sa.Column("stop_reason", sa.Text()),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40)),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint("stages_total >= 0", name="ck_daily_run_stage_count"),
    )
    op.create_index("ix_daily_run_started", "daily_run", ["started_at"])

    op.create_table(
        "safe_mode_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("daily_run.id")),
        sa.Column("entered_at", sa.String(40), nullable=False),
        sa.Column("cleared_at", sa.String(40)),
        sa.Column("cleared_notes", sa.Text()),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
    )
    op.create_index("ix_safe_mode_open", "safe_mode_record", ["cleared_at"])


def downgrade() -> None:
    op.drop_table("safe_mode_record")
    op.drop_table("daily_run")
