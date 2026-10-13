"""One buyer per film at a time: the film's purchase lease.

Measured on fakes (2026-10-01): two presses of one shooting-sheet step under the Owner's MODE
rule bought an extra shot, and the second thread's paid shot was lost before its take was
written ("database is locked"). Under MODE no yes is spent, so nothing serialised the two
buyers, and the motion step fixes its list of scenes to buy when it starts.

``film_purchase_lease`` holds at most one row per film: who is buying for it (the run's
correlation id), what step, since when, and until when the hold stands. A film's paid steps
take it before anything is priced and delete it when they end; a second buyer finds it and buys
nothing. A row past ``expires_at`` was left by a process that died under it and is taken over.

A new table, so nothing is rebuilt; the way down drops it (a lease is never history: it only
says who is buying now).
"""

import sqlalchemy as sa
from alembic import op

revision = "0050_film_purchase_lease"
down_revision = "0049_take_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "film_purchase_lease",
        sa.Column(
            "storyboard_id",
            sa.String(36),
            sa.ForeignKey("storyboard.id"),
            primary_key=True,
        ),
        sa.Column("holder", sa.String(100), nullable=False),
        sa.Column("step", sa.String(20), nullable=False),
        sa.Column("acquired_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("film_purchase_lease")
