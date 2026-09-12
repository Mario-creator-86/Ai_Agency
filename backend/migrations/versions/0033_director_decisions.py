"""The Director decides, and the decision is a row with a review date.

The studio had a Director who read her inbox, chose the day's topic and watched the finished
film. What it did not have was a record of a *strategic* decision: why the studio was doing
more of one thing and less of another, on what evidence, how sure she was, who was asked to
act, and when the decision would be looked at again. So nothing could be learned from
strategy itself — only from individual films.

- ``director_decision`` is that record, in the shape the Owner asked for: observation,
  evidence, interpretation, confidence, decision, action, owner, review condition. It stays
  OPEN until its review condition is met, then it is REVIEWED with what actually happened, or
  SUPERSEDED when a later decision replaces it. A decision with no review condition cannot be
  written, because a decision nobody checks is an opinion.
- ``topic_idea.priority`` and ``priority_reason`` make the backlog an ordered queue with a
  stated reason per place, instead of whatever the database returned first. The Director
  reorders it; the reason is what the Owner reads.

Nothing here duplicates `director_recommendation`, which stays what it is: a bounded change to
one channel's topic or hook weights, backed by at least three measured videos. That is one
kind of decision. This table holds the rest of them.
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_director_decisions"
down_revision = "0032_editorial_intelligence"
branch_labels = None
depends_on = None

#: What a decision can be. The Owner's list, unchanged.
DECISIONS = (
    "SCALE",
    "CONTINUE",
    "ITERATE",
    "EXPERIMENT",
    "HOLD",
    "COOLDOWN",
    "REDUCE",
    "STOP",
    "NEEDS_MORE_DATA",
)


def upgrade() -> None:
    with op.batch_alter_table("topic_idea") as batch:
        #: Where this candidate stands in the queue, and why it stands there. Higher first.
        batch.add_column(sa.Column("priority", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("priority_reason", sa.Text(), nullable=True))

    op.create_table(
        "director_decision",
        sa.Column("id", sa.String(36), primary_key=True),
        #: COMPANY | CHANNEL | CONTENT | AGENT | PRODUCTION — what the decision is about.
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channel_record.id"), nullable=True),
        #: The eight fields that make a decision reviewable rather than a sentiment.
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        #: The role asked to act. NULL only for a decision the Owner must take.
        sa.Column("owner_role", sa.String(50), nullable=True),
        #: When this is looked at again: after N published videos, or after a date, or both.
        sa.Column("review_after_videos", sa.Integer(), nullable=True),
        sa.Column("review_after_at", sa.String(40), nullable=True),
        #: OPEN | REVIEWED | SUPERSEDED
        sa.Column("state", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.String(40), nullable=True),
        #: What was already published when the decision was made, so "after ten videos" can
        #: be measured without guessing which ten.
        sa.Column("published_at_decision", sa.Integer(), nullable=False, server_default="0"),
        #: A key for the matter decided, so the same matter is not decided twice a day.
        sa.Column("matter_key", sa.String(120), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("agent_message.id"), nullable=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "decision IN ('" + "','".join(DECISIONS) + "')", name="ck_decision_kind"
        ),
        sa.CheckConstraint("confidence IN ('LOW','MEDIUM','HIGH')", name="ck_decision_confidence"),
        sa.CheckConstraint("state IN ('OPEN','REVIEWED','SUPERSEDED')", name="ck_decision_state"),
        #: A decision nobody will check is an opinion: one of the two review conditions must
        #: be set, unless the decision is explicitly that more data is needed.
        sa.CheckConstraint(
            "review_after_videos IS NOT NULL OR review_after_at IS NOT NULL "
            "OR decision = 'NEEDS_MORE_DATA'",
            name="ck_decision_is_reviewable",
        ),
    )
    op.create_index("ix_director_decision_state", "director_decision", ["state", "created_at"])
    op.create_index("ix_director_decision_matter", "director_decision", ["matter_key", "state"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
