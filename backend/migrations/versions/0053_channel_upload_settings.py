"""Each channel carries its own upload settings (audit PUB-09, PUB-15; 2026-10-02).

Until 0053 every upload was sent with ``categoryId`` 28 (Science & Technology) on both
channels, ``selfDeclaredMadeForKids`` False and no language at all, all hard-coded in the
YouTube adapter; and quality control refused any Short over 70 seconds on every channel,
although YouTube has taken vertical Shorts up to 3 minutes since 2024-10-15. Four columns on
``channel_record``, part of the channel's versioned publish policy (``change_publish_policy``):

- ``youtube_category_id``: YouTube's ``snippet.categoryId``; ``'28'`` for every existing row,
  which is what was sent until now: the Owner chooses another;
- ``made_for_kids``: ``status.selfDeclaredMadeForKids``; False, as before;
- ``default_language``: ``snippet.defaultLanguage`` and ``defaultAudioLanguage``; NULL means
  the studio's content language (``STUDIO_CONTENT_LANGUAGE``);
- ``shorts_max_seconds``: the longest film quality control accepts for the channel; 60 for
  every row, 70 for the office serial (its episodes are written for 45-70 s).

Added in place (SQLite ADD COLUMN with server defaults); nothing is rebuilt. The way down
drops them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_channel_upload_settings"
down_revision = "0052_publication_remote_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel_record", recreate="never") as batch:
        batch.add_column(
            sa.Column("youtube_category_id", sa.String(4), nullable=False, server_default="28")
        )
        batch.add_column(
            sa.Column("made_for_kids", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("default_language", sa.String(20), nullable=True))
        batch.add_column(
            sa.Column("shorts_max_seconds", sa.Integer(), nullable=False, server_default="60")
        )
    op.execute(
        "UPDATE channel_record SET shorts_max_seconds = 70 WHERE channel_type = 'OFFICE_SERIAL'"
    )


def downgrade() -> None:
    with op.batch_alter_table("channel_record", recreate="never") as batch:
        batch.drop_column("shorts_max_seconds")
        batch.drop_column("default_language")
        batch.drop_column("made_for_kids")
        batch.drop_column("youtube_category_id")
