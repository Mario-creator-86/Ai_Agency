"""The books see the real cost of a film, and can hold money before it is spent.

Measured on a copy of the live database before this revision: the pre-render budget check
was ``may_spend(engine, 0)``, so a day at 14.99 of 15 USD started a full film; every LLM
adapter returned ``cost_vr=None`` although the models were Ollama Cloud (391 ``agent_run``
rows with no cost); all nine ElevenLabs models carried ``pricing {}`` so narration was never
costed; a render that failed midway recorded no cost although the vendor may have charged;
and nothing could hold a sum against the day's budget while a film was being made.

Additive, every existing row keeping the safe reading:

- ``provider_price``: what a unit of a provider's resource costs, as the Owner typed it (or
  as a public price list documents it, marked so). One active row per
  ``(provider_kind, resource, unit)``; a new price deactivates the previous one and keeps it,
  with its provenance — OWNER, DOCUMENTED, QUOTED or BILLED — and the event that set it. Read
  by the LLM and voice adapters to cost a run the moment it happens, and by the Accountant to
  cost a render's narration when the model's own catalogue row has no price.
- ``spend_reservation``: a sum held against the period's budget while a film is made, until
  the real cost replaces it (SETTLED) or it is let go (RELEASED). Counted by every budget
  check while RESERVED, so two films cannot both be started on the last ten dollars.
- ``provider_cost_record.failed`` (default false): the cost of a render the vendor may have
  charged for and the studio never brought home. Counted by budgets like any estimate.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_pricing_truth_and_reservations"
down_revision = "0038_director_may_approve_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_price",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("resource", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("provenance", sa.String(12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("set_by", sa.String(100), nullable=False, server_default="owner"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("set_at", sa.String(40), nullable=False),
        sa.Column("replaced_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint(
            "unit IN ('per_1k_characters','per_1m_input_tokens','per_1m_output_tokens',"
            "'per_second','per_generation')",
            name="ck_provider_price_unit",
        ),
        sa.CheckConstraint(
            "provenance IN ('OWNER','DOCUMENTED','QUOTED','BILLED')",
            name="ck_provider_price_provenance",
        ),
        sa.CheckConstraint("usd_micros >= 0", name="ck_provider_price_non_negative"),
        sa.UniqueConstraint(
            "provider_kind", "resource", "unit", "version", name="uq_provider_price_version"
        ),
    )
    op.create_index(
        "ix_provider_price_lookup",
        "provider_price",
        ["provider_kind", "resource", "unit", "active"],
    )

    op.create_table(
        "spend_reservation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purpose", sa.String(200), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reserved_at", sa.String(40), nullable=False),
        sa.Column("released_at", sa.String(40), nullable=True),
        sa.Column("settled_reference", sa.String(120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint(
            "status IN ('RESERVED','RELEASED','SETTLED')", name="ck_spend_reservation_status"
        ),
        sa.CheckConstraint("usd_micros > 0", name="ck_spend_reservation_positive"),
    )
    op.create_index("ix_spend_reservation_status", "spend_reservation", ["status", "reserved_at"])

    # A NOT NULL column with a server default needs no rebuild on SQLite: plain ADD COLUMN.
    op.add_column(
        "provider_cost_record",
        sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
