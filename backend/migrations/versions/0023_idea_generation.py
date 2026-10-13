"""What the studio decided to look into, who proposed it and who chose it.

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` §3 asks for a candidate pool that is
deduplicated and scored (interest, credibility, source availability, visual potential,
novelty, cost), and §5 for the Director to choose the day's production candidate under
policy. Topics carried only a single `novelty_score` and no author, so neither the score set
nor the decision could be recorded, and the runbook's idea stage had nothing to write to.

- `topic_idea.scores_json`: the six criteria as the proposer scored them, plus the composite.
- `topic_idea.proposed_by_agent_id`: the employee who proposed it (NULL for the Owner's own).
- `topic_idea.decided_by` / `decision_notes`: who selected it and why.
- `topic_idea.source_plan_json`: the hosts the proposer expects to find evidence on, all of
  them already on the Owner's allowlist; the retrieval still fetches and may find nothing.

Every column is nullable or defaulted, so existing topics keep their meaning.
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_idea_generation"
down_revision = "0022_agent_identity_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("topic_idea") as batch:
        batch.add_column(
            sa.Column("scores_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch.add_column(
            sa.Column("source_plan_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch.add_column(
            sa.Column(
                "proposed_by_agent_id",
                sa.String(36),
                sa.ForeignKey("agent.id", name="fk_topic_idea_proposed_by"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("decided_by", sa.String(100), nullable=True))
        batch.add_column(sa.Column("decision_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
