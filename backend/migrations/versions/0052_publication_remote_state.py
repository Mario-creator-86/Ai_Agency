"""A publication keeps what YouTube says the video is, not only what was asked (PUB-05, PUB-08).

Until 0052 the record held the visibility the studio requested. Google keeps every upload of an
unaudited API project (created after 28 July 2020) private until the project passes the
YouTube API Services audit, and the insert answer says so in ``status.privacyStatus``; the
adapter read only the video id, so a film nobody could see was recorded «public, PUBLISHED».
A video YouTube rejected or failed to process was recorded PUBLISHED as well. Three columns:

- ``publication_record.remote_privacy_status``: YouTube's ``status.privacyStatus``;
- ``publication_record.remote_upload_status``: YouTube's ``status.uploadStatus``
  (uploaded, processed, rejected, failed, deleted);
- ``publication_record.remote_checked_at``: when YouTube last said so.

Nullable, added in place (SQLite ADD COLUMN); nothing is rebuilt. The way down drops them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_publication_remote_state"
down_revision = "0051_component_licences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publication_record", recreate="never") as batch:
        batch.add_column(sa.Column("remote_privacy_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("remote_upload_status", sa.String(30), nullable=True))
        batch.add_column(sa.Column("remote_checked_at", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("publication_record", recreate="never") as batch:
        batch.drop_column("remote_checked_at")
        batch.drop_column("remote_upload_status")
        batch.drop_column("remote_privacy_status")
