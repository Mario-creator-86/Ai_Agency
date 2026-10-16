"""The channels' longest film is YouTube's Shorts limit (the Owner, 2026-10-16).

The Owner read the serial's episode «Zero Scripts, Blocked Log» (131 words, 45-70 s) and the
30-second shorts and decided: a short carries a small story a stranger can follow, 60 to
180 s (160 aimed at); an episode 90 to 180 s with 250-450 spoken words. The channel rows
still at the seed's old ceilings (60 s factual, 70 s serial) go to 180; a ceiling the Owner
set by hand to another value is not touched.

The downgrade puts the old ceilings back on rows at 180.
"""

import sqlalchemy as sa
from alembic import op

revision = "0058_shorts_max_180"
down_revision = "0057_runpod_copy_pod"
branch_labels = None
depends_on = None

_OLD = {"MAIN_FACTUAL": 60, "OFFICE_SERIAL": 70}


def upgrade() -> None:
    for channel_type, old in _OLD.items():
        op.execute(
            sa.text(
                "UPDATE channel_record SET shorts_max_seconds = 180 "
                "WHERE channel_type = :kind AND shorts_max_seconds = :old"
            ).bindparams(kind=channel_type, old=old)
        )


def downgrade() -> None:
    for channel_type, old in _OLD.items():
        op.execute(
            sa.text(
                "UPDATE channel_record SET shorts_max_seconds = :old "
                "WHERE channel_type = :kind AND shorts_max_seconds = 180"
            ).bindparams(kind=channel_type, old=old)
        )
