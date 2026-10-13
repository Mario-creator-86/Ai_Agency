"""Each bought component carries its licence: vendor, terms, commercial use (AR-15).

Until 0051 every rendered film was stamped PROPRIETARY_STUDIO and quality control passed the
stamp: nothing recorded whether the plan a still, a shot or a narration was bought under
allowed commercial use. A film is now LICENSED only when every component carries that
evidence, and a take keeps what was read for it:

- ``scene_take.licence_vendor``: the vendor (the connection's kind) it was bought from;
- ``scene_take.licence_terms``: the plan or terms the Owner recorded on that connection;
- ``scene_take.commercial_use``: True only on his explicit yes, NULL when nothing says so.

Narration is a kind of take since 0049, so it is covered here; a music track's licence lives
in the Owner's library (config/music_library.json) and on the film's own record.

Three nullable columns added in place (SQLite ADD COLUMN); nothing is rebuilt. The way down
drops them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_component_licences"
down_revision = "0050_film_purchase_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scene_take", recreate="never") as batch:
        batch.add_column(sa.Column("licence_vendor", sa.String(60), nullable=True))
        batch.add_column(sa.Column("licence_terms", sa.String(200), nullable=True))
        batch.add_column(sa.Column("commercial_use", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # SQLite drops a column in place since 3.35; the table keeps its constraints and rows.
    with op.batch_alter_table("scene_take", recreate="never") as batch:
        batch.drop_column("commercial_use")
        batch.drop_column("licence_terms")
        batch.drop_column("licence_vendor")
