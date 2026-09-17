"""The publish policy the Owner sets per channel, and the stamp on what it published.

Measured before this revision: the daily run hardcoded ``privacy_status="private"`` and took
the first bound channel slot whatever film it held; ``channel_record.upload_privacy_default``
was read by nobody on a publish path; ``publication_record.scheduled_publish_time`` was stored
and never sent; and the policy view reported ``public_publish_enabled`` as a constant False
that no command could change. Nothing could ever leave a channel private on purpose, and
nothing could say who had decided otherwise.

Additive columns, every existing row keeping the safe reading:

- ``channel_record.autonomous_privacy`` ("private" | "unlisted" | "public", default private),
  ``public_publish_enabled`` (default false), ``publish_delay_minutes`` (default 0),
  ``policy_version`` (default 1) and ``policy_changed_event_id`` (the ledger event of the
  Owner command that set the policy in force; NULL until one has). A channel written before
  this revision is therefore a channel whose policy is "private", version 1, set by nobody.
- ``publication_record.policy_version``: which channel policy authorised the publication's
  visibility. NULL for a private upload and for every row written before this revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_publish_policy"
down_revision = "0036_serial_continuity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode for channel_record: the event reference is a foreign key, and SQLite adds
    # one only by rebuilding the table (as 0021 did for storyboard.channel_id).
    with op.batch_alter_table("channel_record") as batch:
        batch.add_column(
            sa.Column("autonomous_privacy", sa.String(20), nullable=False, server_default="private")
        )
        batch.add_column(
            sa.Column(
                "public_publish_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("publish_delay_minutes", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column(
                "policy_changed_event_id",
                sa.String(36),
                sa.ForeignKey("domain_event.event_id", name="fk_channel_record_policy_event"),
                nullable=True,
            )
        )
    # Plain ADD COLUMN: nullable, no default, no constraint, so no rebuild is needed.
    op.add_column("publication_record", sa.Column("policy_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
