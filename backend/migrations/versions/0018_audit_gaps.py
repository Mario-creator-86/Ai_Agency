"""Link two audited facts to the event that created them.

Additive, and nullable: rows written before this revision keep a NULL event_id, which is the
truth about them — no event was appended at the time.

Why these two tables. An exchange rate decides how a foreign payout converts to USD, and that
USD figure is what mints VR$; a rate that appeared with no event behind it leaves the ledger
unable to say who introduced it or when. A scheduled job decides that the studio will run a
workflow again and again without being asked; that is an autonomy decision, and the Owner's
history should be able to explain when it started.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_audit_gaps"
down_revision = "0017_youtube_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fx_snapshot") as batch:
        batch.add_column(sa.Column("event_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_fx_snapshot_event", "domain_event", ["event_id"], ["event_id"])
    with op.batch_alter_table("scheduled_job") as batch:
        batch.add_column(sa.Column("event_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_scheduled_job_event", "domain_event", ["event_id"], ["event_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_job") as batch:
        batch.drop_constraint("fk_scheduled_job_event", type_="foreignkey")
        batch.drop_column("event_id")
    with op.batch_alter_table("fx_snapshot") as batch:
        batch.drop_constraint("fk_fx_snapshot_event", type_="foreignkey")
        batch.drop_column("event_id")
