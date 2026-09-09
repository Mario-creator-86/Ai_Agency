"""Phase 2: workflow, step, task queue, scheduled job, and outbox tables."""

import sqlalchemy as sa
from alembic import op

revision = "0003_phase2_automation"
down_revision = "0002_phase1_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_stage", sa.String(50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=False,
        ),
    )
    op.create_table(
        "workflow_step",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(36),
            sa.ForeignKey("workflow.id"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "assigned_agent_id",
            sa.String(36),
            sa.ForeignKey("agent.id"),
            nullable=True,
        ),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.String(40), nullable=True),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=True,
        ),
    )
    op.create_table(
        "task_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(36),
            sa.ForeignKey("workflow.id"),
            nullable=True,
        ),
        sa.Column(
            "step_id",
            sa.String(36),
            sa.ForeignKey("workflow_step.id"),
            nullable=True,
        ),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("backoff_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.String(40), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.String(40), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True, unique=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "scheduled_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("workflow_type", sa.String(50), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.String(40), nullable=True),
        sa.Column("next_run_at", sa.String(40), nullable=False),
        sa.Column("missed_policy", sa.String(20), nullable=False, server_default="SKIP"),
        sa.Column("leader_token", sa.String(64), nullable=True),
        sa.Column("leader_expires_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "outbox_record",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(36), nullable=False, unique=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=False,
        ),
        sa.Column("destination", sa.String(50), nullable=False, server_default="WEBSOCKET"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("published_at", sa.String(40), nullable=True),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
