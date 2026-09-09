"""Foundation schema. Immutable event and command history; no autonomous execution."""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.create_table(
        "owner_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("autonomy_stopped", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("id = 1"),
        sa.CheckConstraint("version >= 1"),
    )
    op.create_table(
        "domain_event",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("causation_id", sa.String(36), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "command_record",
        sa.Column("idempotency_key", sa.String(36), primary_key=True),
        sa.Column("command_type", sa.String(100), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "room",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("studio_id", sa.Integer(), sa.ForeignKey("studio.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=False
        ),
        sa.CheckConstraint("width > 0 AND height > 0"),
    )
    for table in ("domain_event", "command_record"):
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Immutable history'); END"
            )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
