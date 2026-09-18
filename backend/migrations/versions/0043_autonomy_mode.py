"""The autonomy mode becomes a fact the studio stores, and an approval a row it can show.

Measured before this revision: `PolicyView.autonomy_mode` was `Literal["MANUAL"] = "MANUAL"`
— a constant no command could move — while the daily run walked twelve stages with no Owner
approval between them, the Director approved her own scripts, the media stage paid a vendor
for shots and the publish stage wrote to YouTube within the channel policy the Owner had set.
`51_AUTONOMY_MODE_SEMANTICS` describes three modes and the code had none of them, so the
specification said "the Owner approves every stage transition" about a studio that has been
running its whole day unattended.

Two additive columns' worth of honesty:

- ``owner_policy.autonomy_mode`` — MANUAL | SUPERVISED | AUTONOMOUS_CEO. Existing rows and
  new ones take AUTONOMOUS_CEO, because that is the reading of the code that is true: the
  Director executes T0-T3 within policy, T4 is nowhere executed autonomously, and the hard
  gates (the stop, the five-point publishing gate, the factual gate, the budget) are
  unchanged and still non-bypassable. This is a record of what already happens, not a
  promotion: `change_autonomy_mode` is the only thing that promotes, and it refuses while
  the studio is stopped or in safe mode.
- ``owner_approval_request`` — the Approval object of `31_GOVERNANCE_APPROVAL_POLICY`
  (action, requester, risk tier, evidence, proposed diff, cost, reversibility, expiry,
  approver, result), which a SUPERVISED studio writes instead of performing a T3 external
  write. The cost is nullable: a cost the studio cannot compute is None, never zero.

Numbering: this implementer was given 0043. The 0041 and 0042 revisions were reserved by the
other Phase D/G implementers and neither was needed — the picture and character verdicts live
in ``quality_control_report.checks_json`` and the reference set in columns that already
existed — so ``down_revision`` chains onto 0040 and this revision is the head ``app.main``
pins. The two numbers are free for whoever needs them next.
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_autonomy_mode"
#: See the note above: 0041 and 0042 were reserved and not used, so the chain is 0040 -> 0043.
down_revision = "0040_research_sources"
branch_labels = None
depends_on = None

#: The honest reading of what the studio does today (see the module docstring).
DEFAULT_AUTONOMY_MODE = "AUTONOMOUS_CEO"


def upgrade() -> None:
    with op.batch_alter_table("owner_policy") as batch:
        batch.add_column(
            sa.Column(
                "autonomy_mode",
                sa.String(20),
                nullable=False,
                server_default=DEFAULT_AUTONOMY_MODE,
            )
        )

    op.create_table(
        "owner_approval_request",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("risk_tier", sa.String(4), nullable=False),
        sa.Column("requester", sa.String(100), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("proposed_diff", sa.JSON(), nullable=True),
        #: USD, or NULL when nothing in the studio can price this action yet.
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("approver", sa.String(100), nullable=True),
        sa.Column("result", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint("risk_tier IN ('T0','T1','T2','T3','T4')", name="ck_approval_tier"),
        sa.CheckConstraint(
            "result IN ('PENDING','APPROVED','REFUSED','EXPIRED')", name="ck_approval_result"
        ),
    )
    # The question asked most often is "what is still waiting for the Owner, for this action".
    op.create_index("ix_approval_open", "owner_approval_request", ["result", "action"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
