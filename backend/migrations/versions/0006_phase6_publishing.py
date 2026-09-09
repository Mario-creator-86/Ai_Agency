"""Phase 6: autonomous publishing, distribution channels, and publication tracking."""

import sqlalchemy as sa
from alembic import op

revision = "0006_phase6_publishing"
down_revision = "0005_phase5_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_name", sa.String(100), nullable=False),
        sa.Column("channel_type", sa.String(50), nullable=False, default="MAIN_FACTUAL"),
        sa.Column("platform", sa.String(50), nullable=False, default="YOUTUBE"),
        sa.Column("remote_channel_id", sa.String(100), nullable=True),
        sa.Column("credentials_ref", sa.String(200), nullable=True),
        sa.Column("upload_privacy_default", sa.String(20), nullable=False, default="private"),
        sa.Column("status", sa.String(30), nullable=False, default="UNCONFIGURED"),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("last_sync_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "channel_brand_asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("content_or_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "publication_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=False),
        sa.Column("media_asset_id", sa.String(36), sa.ForeignKey("media_asset.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("privacy_status", sa.String(20), nullable=False, default="private"),
        sa.Column("status", sa.String(30), nullable=False, default="DRAFT_INTENT"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("remote_video_id", sa.String(100), nullable=True),
        sa.Column("remote_url", sa.String(500), nullable=True),
        sa.Column("scheduled_publish_time", sa.String(40), nullable=True),
        sa.Column("published_at", sa.String(40), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.UniqueConstraint("channel_id", "idempotency_key", name="uq_channel_idempotency"),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup instead")
