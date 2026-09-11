"""Separate provider authentication, discovered resources, and production selections."""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0019_provider_resources"
down_revision = "0018_audit_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_resource",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "integration_id",
            sa.String(36),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(10), nullable=False),
        sa.Column("remote_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("api_metadata", sa.JSON(), nullable=False),
        sa.Column("api_available", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.String(40), nullable=False),
        sa.Column("pricing", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("availability_override", sa.Boolean(), nullable=True),
        sa.Column("metadata_source", sa.Text(), nullable=True),
        sa.Column("metadata_updated_at", sa.String(40), nullable=True),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("integration_id", "resource_type", "remote_id"),
    )
    op.create_table(
        "provider_discovery",
        sa.Column(
            "integration_id",
            sa.String(36),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_attempt_at", sa.String(40), nullable=True),
        sa.Column("last_success_at", sa.String(40), nullable=True),
        sa.Column("next_refresh_at", sa.String(40), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.String(40), nullable=True),
    )
    production = op.create_table(
        "media_production_config",
        sa.Column(
            "integration_id",
            sa.String(36),
            sa.ForeignKey("integration.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_id", sa.String(200), nullable=True),
        sa.Column("voice_id", sa.String(200), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    # Preserve existing choices without claiming that any typed ID has been discovered.
    connection = op.get_bind()
    now = datetime.now(UTC).isoformat()
    rows = connection.execute(sa.text("SELECT id, config FROM integration WHERE kind='elevenlabs'"))
    for identifier, raw in rows.fetchall():
        config = json.loads(raw) if isinstance(raw, str) else raw
        connection.execute(
            production.insert().values(
                integration_id=identifier,
                model_id=config.get("model"),
                voice_id=config.get("voice_id"),
                version=1,
                updated_at=now,
            )
        )
        connection.execute(
            sa.text("UPDATE integration SET config='{}' WHERE id=:id"), {"id": identifier}
        )
        connection.execute(
            sa.text(
                "INSERT INTO provider_discovery (integration_id,status,next_refresh_at) "
                "VALUES (:id,'EMPTY',:now)"
            ),
            {"id": identifier, "now": now},
        )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
