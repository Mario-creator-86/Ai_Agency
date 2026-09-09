"""Phase 1: agent/role/capability/provider/run/tool_receipt tables."""

import sqlalchemy as sa
from alembic import op

revision = "0002_phase1_agents"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("allowed_task_types", sa.Text(), nullable=False),
        sa.Column("prohibited_actions", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=False,
        ),
    )
    op.create_table(
        "role_capability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("role.id"), nullable=False),
        sa.Column("capability_id", sa.String(36), sa.ForeignKey("capability.id"), nullable=False),
        sa.Column("requirement_level", sa.String(20), nullable=False),
        sa.UniqueConstraint("role_id", "capability_id"),
    )
    op.create_table(
        "provider_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("last_health_check", sa.String(40), nullable=True),
        sa.Column("adapter_version", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=False,
        ),
    )
    op.create_table(
        "model_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id", sa.String(36), sa.ForeignKey("provider_record.id"), nullable=False
        ),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("discovery_method", sa.String(30), nullable=False),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("last_verified", sa.String(40), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.UniqueConstraint("provider_id", "model_name"),
    )
    op.create_table(
        "model_capability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("model_record.id"), nullable=False),
        sa.Column("capability_id", sa.String(36), sa.ForeignKey("capability.id"), nullable=False),
        sa.Column("confidence", sa.String(30), nullable=False),
        sa.UniqueConstraint("model_id", "capability_id"),
    )
    op.create_table(
        "agent",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("role.id"), nullable=False),
        sa.Column(
            "provider_id", sa.String(36), sa.ForeignKey("provider_record.id"), nullable=False
        ),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("model_record.id"), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False),
        sa.Column("runtime_state", sa.String(25), nullable=False),
        sa.Column("cost_limit_per_task", sa.String(20), nullable=True),
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("hired_at", sa.String(40), nullable=False),
        sa.Column("terminated_at", sa.String(40), nullable=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1"),
    )
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("prompt_template_version", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("cost_vr", sa.String(20), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("domain_event.event_id"),
            nullable=True,
        ),
    )
    op.create_table(
        "tool_receipt",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("receipt_id", sa.String(36), nullable=False, unique=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_summary", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("remote_id", sa.String(200), nullable=True),
        sa.Column("cost_vr", sa.String(20), nullable=True),
        sa.Column("called_at", sa.String(40), nullable=False),
        sa.Column("returned_at", sa.String(40), nullable=True),
        sqlite_autoincrement=True,
    )
    # Immutable history trigger for tool_receipt (like domain_event)
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER tool_receipt_no_{action.lower()} BEFORE {action} ON tool_receipt "
            "BEGIN SELECT RAISE(ABORT, 'Immutable history'); END"
        )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
