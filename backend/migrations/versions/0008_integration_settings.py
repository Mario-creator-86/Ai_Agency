"""Owner integration settings; additive schema, no default accounts or credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0008_integration_settings"
down_revision = "0007_correct_fabricated_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=False),
        sa.Column("secret_fields", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("checked_at", sa.String(40)),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=False
        ),
    )
    op.create_table(
        "service_selection",
        sa.Column("purpose", sa.String(40), primary_key=True),
        sa.Column("integration_id", sa.String(36), sa.ForeignKey("integration.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=False
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a reviewed backup instead of deleting credentials and routing")
