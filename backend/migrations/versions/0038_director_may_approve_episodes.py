"""The Director's leave to approve an episode becomes a column of the publish policy.

Measured before this revision: ``app.story.review.director_may_approve_episodes`` read a
boolean ``director_may_approve_episodes`` from the OFFICE_SERIAL channel's
``series_rules_json``, and nothing wrote it there — the production-policy command keeps that
JSON to ``{series_key: {purpose: selection}}`` and would have refused or overwritten the
key, and the publish-policy command did not know it. So an episode the Director passed
stayed DRAFT for the Owner's hand, and the serial never became a storyboard on its own.

Additive, every existing row keeping the safe reading:

- ``channel_record.director_may_approve_episodes`` (default false): whether the Director's
  PASS approves an episode by itself. Part of the versioned publish policy, set only by the
  Owner's publish-policy command (``change_publish_policy``), which bumps ``policy_version``
  and records the old and the new value in ``publishing.channel_policy_changed``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_director_may_approve_episodes"
down_revision = "0037_publish_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A NOT NULL column with a server default needs no rebuild on SQLite: plain ADD COLUMN.
    op.add_column(
        "channel_record",
        sa.Column(
            "director_may_approve_episodes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
