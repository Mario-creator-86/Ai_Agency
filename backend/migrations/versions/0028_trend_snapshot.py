"""What people are searching for, kept as a signal the studio can read back.

`trend_snapshot` holds Google's public "trending now" feed for the studio's country, one row
per trend per fetch: the query, its approximate search volume, the news items the feed
attached, when it was published and when the studio read it. The Researcher's proposals and
the Director's weekly review read it beside the studio's own measured numbers. A trend is a
hook, never a source: nothing here is evidence for a claim.
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_trend_snapshot"
down_revision = "0027_mail_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trend_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("geo", sa.String(8), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("approx_traffic", sa.Integer(), nullable=True),
        sa.Column("news_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("published_at", sa.String(60), nullable=True),
        sa.Column("fetched_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )
    op.create_index("ix_trend_snapshot_geo_time", "trend_snapshot", ["geo", "fetched_at"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
