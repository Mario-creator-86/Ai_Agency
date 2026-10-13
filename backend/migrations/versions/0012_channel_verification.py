"""Do not equate credential presence with successful remote authentication."""

import sqlalchemy as sa
from alembic import op

revision = "0012_channel_verification"
down_revision = "0011_claim_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep only identities actually checked and bound via the Settings workflow.
    op.get_bind().execute(
        sa.text("""
        UPDATE channel_record SET status = 'CONFIGURED'
        WHERE status = 'AUTHENTICATED' AND NOT EXISTS (
            SELECT 1 FROM integration i
            WHERE channel_record.credentials_ref = 'integration:' || i.id
              AND i.kind = 'youtube' AND i.status = 'VERIFIED'
              AND json_extract(i.config, '$.channel_id') = channel_record.remote_channel_id
        )
    """)
    )


def downgrade() -> None:
    raise RuntimeError("Unverified channel authentication must not be restored")
