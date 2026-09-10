"""Record which agent extracted a claim and which agent verified it.

`../architecture/02_SRS.md` FR-038 requires the fact-check path to be independent of the
research path. Until now nothing recorded who did either, so independence could be claimed in a
docstring but never demonstrated, and never enforced. With both attributions stored, the
verification service can refuse to let the agent that read a source also be the one that
confirms it, and an auditor can check afterwards that it did.

Both columns are nullable: claims created before this migration, and claims the Owner verifies
themselves, have no agent attached, and a placeholder agent id would be a fabricated record.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_claim_attribution"
down_revision = "0010_phase7_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("factual_claim") as batch:
        batch.add_column(sa.Column("extracted_by_agent_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("verified_by_agent_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_claim_extracted_by", "agent", ["extracted_by_agent_id"], ["id"]
        )
        batch.create_foreign_key("fk_claim_verified_by", "agent", ["verified_by_agent_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("factual_claim") as batch:
        batch.drop_constraint("fk_claim_verified_by", type_="foreignkey")
        batch.drop_constraint("fk_claim_extracted_by", type_="foreignkey")
        batch.drop_column("verified_by_agent_id")
        batch.drop_column("extracted_by_agent_id")
