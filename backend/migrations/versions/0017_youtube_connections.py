"""YouTube OAuth connections: one row per channel the Owner authorises.

Additive. Creating these tables authorises nothing and stores no credential: a connection starts
at AUTH_REQUIRED with only the client details the Owner typed, and the refresh token appears only
after Google returns one through the callback.
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_youtube_connections"
down_revision = "0016_phase11_economy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_connection",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        # The client id travels in the authorisation URL, so it is not a secret and stays a
        # plain column. The client secret and refresh token live in encrypted_secrets only.
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=False),
        sa.Column("secret_fields", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="AUTH_REQUIRED"),
        # Everything below is read from Google, never typed.
        sa.Column("remote_channel_id", sa.String(100)),
        sa.Column("remote_channel_title", sa.String(200)),
        sa.Column("channel_snapshot", sa.JSON(), nullable=False),
        sa.Column("granted_scopes", sa.String(600)),
        sa.Column("connected_at", sa.String(40)),
        sa.Column("last_checked_at", sa.String(40)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.UniqueConstraint("name", name="uq_youtube_connection_name"),
        sa.CheckConstraint(
            "status IN ('AUTH_REQUIRED','CONNECTED','ERROR')", name="ck_youtube_connection_status"
        ),
    )
    op.create_index("ix_youtube_connection_status", "youtube_connection", ["status", "created_at"])

    op.create_table(
        "youtube_oauth_state",
        # Random, single-use and short-lived: the only thing tying a browser redirect back to the
        # request that started it, since a redirect cannot carry the Owner credential.
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column(
            "connection_id", sa.String(36), sa.ForeignKey("youtube_connection.id"), nullable=False
        ),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("used_at", sa.String(40)),
    )
    op.create_index("ix_youtube_oauth_state_connection", "youtube_oauth_state", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_youtube_oauth_state_connection", table_name="youtube_oauth_state")
    op.drop_table("youtube_oauth_state")
    op.drop_index("ix_youtube_connection_status", table_name="youtube_connection")
    op.drop_table("youtube_connection")
