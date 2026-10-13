"""Phase 8 tables: workforce proposals and employment periods.

Additive. Creating these tables changes nothing about who works at the studio: a proposal is a
recommendation with its evidence attached, and applying one is an Owner decision.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_workforce"
down_revision = "0011_claim_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workforce_proposal",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("proposal_type", sa.String(30), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id")),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("role.id")),
        sa.Column("summary", sa.Text(), nullable=False),
        # The measurements the proposal was built from, kept so the reasoning can be checked
        # long after the numbers that produced it have changed.
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("need_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROPOSED"),
        sa.Column("decision_notes", sa.Text()),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("decided_at", sa.String(40)),
        sa.Column("applied_at", sa.String(40)),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        # A proposal about someone's work that rests on fewer runs than this is an anecdote.
        sa.CheckConstraint("sample_size >= 5", name="ck_proposal_has_evidence"),
        sa.CheckConstraint(
            "need_score >= 0 AND need_score <= 1", name="ck_proposal_need_is_a_fraction"
        ),
    )
    op.create_index("ix_workforce_proposal_status", "workforce_proposal", ["status", "created_at"])

    op.create_table(
        "employment_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("role.id"), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("ended_at", sa.String(40)),
        sa.Column("end_reason", sa.Text()),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("workforce_proposal.id")),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
    )
    op.create_index("ix_employment_agent", "employment_record", ["agent_id", "ended_at"])


def downgrade() -> None:
    op.drop_table("employment_record")
    op.drop_table("workforce_proposal")
