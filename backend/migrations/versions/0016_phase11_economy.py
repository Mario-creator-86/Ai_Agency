"""Phase 11 tables: financial evidence, FX snapshots, Owner funding and the VR$ ledger.

Additive. Creating these tables gives the studio no money and no ability to spend: the ledger
starts empty, the chart of accounts is seeded by bootstrap, and every posting still requires an
Owner action carrying real evidence.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_phase11_economy"
down_revision = "0015_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ledger_account",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("account_type", sa.String(12), nullable=False),
        sa.Column("normal_balance", sa.String(6), nullable=False),
        # VR_CASH | VR_RESTRICTED | VR_RECEIVABLE | VR_DEBT | NULL for non-treasury accounts.
        sa.Column("money_class", sa.String(16)),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.CheckConstraint(
            "account_type IN ('ASSET','LIABILITY','EQUITY','REVENUE','EXPENSE')",
            name="ck_account_type",
        ),
        sa.CheckConstraint(
            "normal_balance IN ('DEBIT','CREDIT')", name="ck_account_normal_balance"
        ),
    )

    op.create_table(
        "fx_snapshot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate_micros", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.CheckConstraint("rate_micros > 0", name="ck_fx_rate_positive"),
    )
    op.create_index(
        "ix_fx_pair_observed", "fx_snapshot", ["base_currency", "quote_currency", "observed_at"]
    )

    op.create_table(
        "ledger_transaction",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.String(40), nullable=False),
        sa.Column("reverses_transaction_id", sa.String(36), sa.ForeignKey("ledger_transaction.id")),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        # A transaction can be reversed at most once, so a retried correction cannot double-post.
        sa.UniqueConstraint("reverses_transaction_id", name="uq_reversal_once"),
    )
    op.create_index("ix_ledger_transaction_posted", "ledger_transaction", ["posted_at"])

    op.create_table(
        "ledger_entry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "transaction_id", sa.String(36), sa.ForeignKey("ledger_transaction.id"), nullable=False
        ),
        sa.Column(
            "account_code", sa.String(8), sa.ForeignKey("ledger_account.code"), nullable=False
        ),
        sa.Column("debit_micros", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("credit_micros", sa.BigInteger(), nullable=False, server_default="0"),
        # Exactly one side carries the amount; a two-sided or empty line is malformed.
        sa.CheckConstraint("(debit_micros = 0) <> (credit_micros = 0)", name="ck_entry_one_sided"),
        sa.CheckConstraint(
            "debit_micros >= 0 AND credit_micros >= 0", name="ck_entry_non_negative"
        ),
    )
    op.create_index("ix_ledger_entry_account", "ledger_entry", ["account_code"])
    op.create_index("ix_ledger_entry_transaction", "ledger_entry", ["transaction_id"])

    op.create_table(
        "revenue_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("original_amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("original_currency", sa.String(3), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("fx_snapshot_id", sa.String(36), sa.ForeignKey("fx_snapshot.id")),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("minted_transaction_id", sa.String(36), sa.ForeignKey("ledger_transaction.id")),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column("settled_at", sa.String(40)),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        # One payout is recorded once. This is what makes "exactly one VR$ per dollar" hold.
        sa.UniqueConstraint("source", "external_reference", name="uq_evidence_reference"),
        sa.CheckConstraint(
            "status IN ('ESTIMATED','PENDING_PAYOUT','SETTLED','REVERSED')",
            name="ck_evidence_status",
        ),
        sa.CheckConstraint("original_amount_micros >= 0", name="ck_evidence_amount_positive"),
    )
    op.create_index("ix_evidence_status", "revenue_evidence", ["status", "recorded_at"])

    op.create_table(
        "provider_cost_record",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("fx_snapshot_id", sa.String(36), sa.ForeignKey("fx_snapshot.id")),
        sa.Column("attribution_json", sa.JSON(), nullable=False),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("ledger_transaction.id")),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column("billed_at", sa.String(40)),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        # Re-importing an invoice must not charge the studio twice.
        sa.UniqueConstraint("provider", "external_reference", name="uq_provider_cost_reference"),
        sa.CheckConstraint("status IN ('ESTIMATED','BILLED')", name="ck_provider_cost_status"),
        sa.CheckConstraint("amount_micros > 0", name="ck_provider_cost_positive"),
    )
    op.create_index("ix_provider_cost_status", "provider_cost_record", ["status", "recorded_at"])

    op.create_table(
        "owner_funding_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("funding_type", sa.String(24), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("fx_snapshot_id", sa.String(36), sa.ForeignKey("fx_snapshot.id")),
        sa.Column("annual_rate_bps", sa.Integer()),
        sa.Column("maturity_date", sa.String(40)),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("ledger_transaction.id")),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id")),
        sa.CheckConstraint(
            "funding_type IN ('CAPITAL_CONTRIBUTION','OWNER_LOAN')", name="ck_funding_type"
        ),
        sa.CheckConstraint("amount_micros > 0", name="ck_funding_amount_positive"),
        # A loan without terms is not a loan.
        sa.CheckConstraint(
            "funding_type <> 'OWNER_LOAN' OR "
            "(annual_rate_bps IS NOT NULL AND maturity_date IS NOT NULL)",
            name="ck_loan_has_terms",
        ),
    )


def downgrade() -> None:
    op.drop_table("owner_funding_event")
    op.drop_index("ix_provider_cost_status", table_name="provider_cost_record")
    op.drop_table("provider_cost_record")
    op.drop_index("ix_evidence_status", table_name="revenue_evidence")
    op.drop_table("revenue_evidence")
    op.drop_index("ix_ledger_entry_transaction", table_name="ledger_entry")
    op.drop_index("ix_ledger_entry_account", table_name="ledger_entry")
    op.drop_table("ledger_entry")
    op.drop_index("ix_ledger_transaction_posted", table_name="ledger_transaction")
    op.drop_table("ledger_transaction")
    op.drop_index("ix_fx_pair_observed", table_name="fx_snapshot")
    op.drop_table("fx_snapshot")
    op.drop_table("ledger_account")
