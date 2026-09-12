"""An employee may think with more than one model, and the choice stays configuration.

Every agent ran on exactly one model, named in `agent.model_id` and changed by the Owner from
Settings. That is the right shape and it stays. What it could not express is the thing the
Owner asked for: a Director who proposes a strategic decision on her own model and then has it
challenged by a second one before she commits, a researcher who falls back to another model
when the first is unavailable, a hard question answered independently by two models and
reconciled.

So three slots instead of one, and a strategy that says what to do with them:

- ``agent.secondary_model_id`` and ``tertiary_model_id`` — optional, from the same model
  registry the primary comes from. No second registry, no model named in code.
- ``agent.multi_llm_strategy`` — SINGLE, FALLBACK, REVIEW, DEBATE or PARALLEL. SINGLE is the
  default and stays the normal way work is done.
- ``agent.additional_llm_policy`` with ``min_importance`` and ``min_confidence`` — when the
  extra models are worth their tokens: important tasks only, low-confidence tasks, always, or
  only when a caller explicitly asks. Routine work never spends three calls.
- ``llm_collaboration`` — one row per multi-model execution, linking the runs that took part
  with the role each model played, why the extra model was called, whether they disagreed and
  which model's answer was final. Each participating call stays an ordinary `agent_run`, so
  the model actually used is recorded there as it always was: changing a model today cannot
  rewrite what yesterday's run was answered by.

Nothing here decides anything by model name. A model in a slot is a configuration value the
Owner can replace from the interface tomorrow without a line of code changing.
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_agent_multi_llm"
down_revision = "0033_director_decisions"
branch_labels = None
depends_on = None

STRATEGIES = ("SINGLE", "FALLBACK", "REVIEW", "DEBATE", "PARALLEL")
POLICIES = ("IMPORTANT_ONLY", "LOW_CONFIDENCE", "ALWAYS", "MANUAL")
IMPORTANCE = ("ROUTINE", "NOTABLE", "STRATEGIC")


def upgrade() -> None:
    # Plain ADD COLUMN, not a batch rebuild: the `agent` table carries an unnamed CHECK from
    # an early migration, and SQLite's batch mode cannot copy a constraint it cannot name.
    # The vocabularies below are therefore enforced where they are set — the Owner's command
    # validates them — rather than by a CHECK this table cannot be given without a rebuild.
    # The slots hold a `model_record.id`. No declared foreign key: SQLite cannot add a
    # constraint to an existing table with ALTER, and a rebuild would drop this table's own
    # unnamed CHECK. The reference is enforced where a slot is set — the command refuses a
    # model that does not exist, is unavailable, or lacks what the role requires.
    op.add_column("agent", sa.Column("secondary_model_id", sa.String(36), nullable=True))
    op.add_column("agent", sa.Column("tertiary_model_id", sa.String(36), nullable=True))
    op.add_column(
        "agent",
        sa.Column("multi_llm_strategy", sa.String(20), nullable=False, server_default="SINGLE"),
    )
    op.add_column(
        "agent",
        sa.Column(
            "additional_llm_policy",
            sa.String(20),
            nullable=False,
            server_default="IMPORTANT_ONLY",
        ),
    )
    op.add_column(
        "agent",
        sa.Column("min_importance", sa.String(20), nullable=False, server_default="STRATEGIC"),
    )
    op.add_column("agent", sa.Column("min_confidence", sa.Float(), nullable=True))

    op.create_table(
        "llm_collaboration",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(20), nullable=False),
        #: ROUTINE | NOTABLE | STRATEGIC, as the caller stated it.
        sa.Column("importance", sa.String(20), nullable=False, server_default="ROUTINE"),
        #: Why a second model was called at all, in words: the policy that allowed it.
        sa.Column("reason", sa.Text(), nullable=False),
        #: The runs that took part, each an ordinary agent_run with its own model recorded.
        sa.Column("primary_run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("secondary_run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("tertiary_run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("final_run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        #: What each model was asked to be: PRIMARY, CRITIC, JUDGE, PEER, FALLBACK.
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("disagreed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("disagreement_note", sa.Text(), nullable=True),
        #: COMPLETE | PARTIAL | REVIEW_INCOMPLETE — a review that could not be done is said
        #: so, never filled with an invented critique.
        sa.Column("outcome", sa.String(20), nullable=False, server_default="COMPLETE"),
        sa.Column("final_model", sa.String(200), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "strategy IN ('" + "','".join(STRATEGIES) + "')", name="ck_collaboration_strategy"
        ),
        sa.CheckConstraint(
            "outcome IN ('COMPLETE','PARTIAL','REVIEW_INCOMPLETE')",
            name="ck_collaboration_outcome",
        ),
    )
    op.create_index("ix_llm_collaboration_agent", "llm_collaboration", ["agent_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
