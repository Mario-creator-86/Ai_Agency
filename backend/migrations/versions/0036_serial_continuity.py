"""The serial gets a memory, and the day's log gets a public face.

Measured on the live database before this work: every `domain_event` carried visibility
OWNER and the day's notable events were described as raw `key=value` payload pairs — model
ids, message text, prices — handed as they were to the showrunner; continuity between
episodes was one title and a roster size; an episode stopped at DRAFT for the Owner's hand,
and nothing consumed an APPROVED one.

Additive, nullable where a row already exists:

- ``daily_studio_log.narrative_projection_json``: the PUBLIC_SAFE projection of the day's
  events, written at close. The showrunner reads this and nothing else. NULL on logs closed
  before this revision; the service fills it once, from the same committed events, the first
  time such a log is asked for an episode.
- ``continuity_state``: one row (id 1), versioned, holding the canon episode number, the
  open threads the serial carries, its recurring elements and the last three episode
  summaries. It advances only when an episode is APPROVED.
- ``story_episode.reviewed_by``, ``review_json``, ``storyboard_id``, ``rewrite_of_id``: who
  passed the episode (director | owner), the review that did, the storyboard it became, and
  the draft it rewrote.
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_serial_continuity"
down_revision = "0035_clock_and_fault_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_studio_log", sa.Column("narrative_projection_json", sa.JSON(), nullable=True)
    )

    op.create_table(
        "continuity_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("canon_episode_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("threads_json", sa.JSON(), nullable=False),
        sa.Column("recurring_json", sa.JSON(), nullable=False),
        sa.Column("summaries_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint("canon_episode_number >= 0", name="ck_continuity_episode_positive"),
    )

    # Foreign keys on a new column need the batch rebuild on SQLite, and the rebuild needs
    # the constraints named.
    with op.batch_alter_table("story_episode") as batch:
        batch.add_column(sa.Column("reviewed_by", sa.String(40), nullable=True))
        batch.add_column(sa.Column("review_json", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "storyboard_id",
                sa.String(36),
                sa.ForeignKey("storyboard.id", name="fk_story_episode_storyboard"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "rewrite_of_id",
                sa.String(36),
                sa.ForeignKey("story_episode.id", name="fk_story_episode_rewrite_of"),
                nullable=True,
            )
        )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
