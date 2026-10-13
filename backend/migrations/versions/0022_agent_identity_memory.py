"""Agent identity, work contracts, memory records and typed messages.

Until now an agent run sent the model only the task text: no name, no mission, no
prohibitions, no persona, nothing remembered from earlier work. The Character Bible existed
but pointed at no employee. This migration adds the places where an employee's identity and
memory live, following ../architecture/04_AGENT_SYSTEM.md §9 (memory classes), §16 (context
manifest and memory records used per run) and ../architecture/20_EMPLOYEE_AGENT_SPEC.md
(work contract, memory scope, typed message intents, structured blockers).

- `role`: `work_contract_json` (what the role watches, investigates, corrects, lets pass,
  never lets pass, escalates), `memory_scope_json` (memory classes it may read/write) and a
  `contract_version`. Seeded from data; an Owner's edit is never overwritten.
- `agent_run`: `context_json` — the context manifest of the run (identity version, contract
  and bible versions, memory record ids used).
- `memory_record`: one remembered fact per row, typed by class, with provenance, expiry and
  invalidation. Written by backend services on real outcomes, never by model free text.
- `agent_message`: typed messages between employees (STATUS, ESCALATE, REQUEST_INFO, ...),
  with an OPEN → ANSWERED / RESOLVED lifecycle.

Nothing existing is rewritten; every new column has a neutral default.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_agent_identity_memory"
down_revision = "0021_production_policy"
branch_labels = None
depends_on = None

MEMORY_CLASSES = (
    "VERIFIED_FACT",
    "STRATEGY",
    "OWNER_POLICY",
    "HISTORICAL_EVENT",
    "AGENT_OPINION",
    "TEMP_CONTEXT",
)
INTENTS = ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "HANDOFF", "STATUS", "ESCALATE")


def upgrade() -> None:
    with op.batch_alter_table("role") as batch:
        batch.add_column(
            sa.Column(
                "work_contract_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )
        batch.add_column(
            sa.Column(
                "memory_scope_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )
        batch.add_column(
            sa.Column("contract_version", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(
            sa.Column("context_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    # A connection that serves two purposes (Runway: video and images) needs a default per
    # purpose; `model_id` stays the primary purpose's default (video), this one is the image's.
    with op.batch_alter_table("media_production_config") as batch:
        batch.add_column(sa.Column("image_model_id", sa.String(200), nullable=True))

    # Hosts the Owner authorised for source retrieval from the interface, next to the ones in
    # .env. Each carries the result of its last connectivity test, because a site the studio
    # cannot actually read is not a source.
    op.create_table(
        "research_allowed_host",
        sa.Column("host", sa.String(253), primary_key=True),
        sa.Column("added_by", sa.String(50), nullable=False, server_default="owner"),
        sa.Column("added_at", sa.String(40), nullable=False),
        sa.Column("last_test_at", sa.String(40), nullable=True),
        sa.Column("last_test_status", sa.String(20), nullable=True),
        sa.Column("last_test_detail", sa.Text(), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    )

    op.create_table(
        "memory_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("memory_class", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=True),
        sa.Column("invalidated_at", sa.String(40), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "memory_class IN (" + ",".join(f"'{c}'" for c in MEMORY_CLASSES) + ")",
            name="ck_memory_record_class",
        ),
        sa.CheckConstraint(
            "source_type IN ('event','run','owner','system')",
            name="ck_memory_record_source",
        ),
    )
    op.create_index(
        "ix_memory_record_agent_class",
        "memory_record",
        ["agent_id", "memory_class", "created_at"],
    )

    op.create_table(
        "agent_message",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("intent", sa.String(20), nullable=False),
        sa.Column("from_agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("to_agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("resolved_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "intent IN (" + ",".join(f"'{i}'" for i in INTENTS) + ")",
            name="ck_agent_message_intent",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','ANSWERED','RESOLVED')", name="ck_agent_message_status"
        ),
    )
    op.create_index("ix_agent_message_status", "agent_message", ["status", "to_agent_id"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
