"""A spending budget the studio can be held to.

The books already record what a provider charged (`provider_cost_record`) and the treasury
shows what is spendable. Nothing said how much the studio was allowed to spend, so no stage
could refuse to spend it and nobody could report against a limit. `spending_budget` is that
limit: one active row per period (DAILY, MONTHLY), set by the Owner, in USD micros like every
other amount in the books. Costs are never written here; the budget is compared with them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_spending_budget"
down_revision = "0023_idea_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spending_budget",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("limit_usd_micros", sa.BigInteger(), nullable=False),
        #: Above this share of the limit the Accountant escalates before the limit is hit.
        sa.Column("warn_ratio", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("set_by", sa.String(100), nullable=False, server_default="owner"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("replaced_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint("period IN ('DAILY','MONTHLY')", name="ck_spending_budget_period"),
        sa.CheckConstraint("limit_usd_micros > 0", name="ck_spending_budget_positive"),
    )
    op.create_index("ix_spending_budget_active", "spending_budget", ["period", "active"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
