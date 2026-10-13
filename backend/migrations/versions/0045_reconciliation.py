"""An estimate is replaced by what the vendor actually billed, and stops counting.

Measured before this revision, on the shape of the code rather than on a live row: every
`provider_cost_record` the studio writes for itself is ESTIMATED — `record_render_costs` and
`record_failed_render_cost` price a render at the Owner's price or the public catalogue's —
and `spend_since` (backend/app/economy/budget.py) sums every row in the period whatever its
status. So a render estimated at 4.20 and later billed at 4.55 charged the period 8.75, and
`bill_provider_cost` made that worse rather than better: it posts the money and leaves the
estimate standing beside it. The vocabulary for the truth existed (ESTIMATED | DOCUMENTED |
QUOTED | BILLED on a price, ESTIMATED | BILLED on a cost) and nothing ever reconciled them.

Only the Owner sees the vendor's invoice, so reconciliation is his act and nothing else's.

- ``provider_reconciliation``: one invoice as he types it — the vendor, his invoice number
  (unique per vendor), what it covers (a half-open period, or one named thing such as a render
  job), what it billed, the BILLED cost row it wrote, how many estimates it replaced and for
  how much, and, as data, every row it touched and could not replace with the reason. One
  active row per (provider, scope, period or correlation), versioned exactly like
  `provider_price`: a correction carries `expected_version`, reverses the previous invoice's
  posting in the ledger and re-adopts its estimates. Nothing is edited and nothing is deleted.
- ``provider_cost_record.reconciled_at`` / ``reconciled_by_id`` (both NULL): when an invoice
  replaced this row and which one. A reconciled row is kept whole — it is the record of what
  the studio believed a film would cost — and is skipped by `spend_since`, so a budget counts
  the estimate until the invoice arrives and the invoice afterwards, never both.

Additive, and every existing row keeps the reading it had: NULL `reconciled_at` means "no
invoice has covered this yet", which is true of every row written before today.
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_reconciliation"
down_revision = "0044_approval_answered"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_reconciliation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("period_start", sa.String(40), nullable=True),
        sa.Column("period_end", sa.String(40), nullable=True),
        sa.Column("correlation", sa.String(200), nullable=True),
        sa.Column("correlation_key", sa.String(60), nullable=True),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("fx_snapshot_id", sa.String(36), sa.ForeignKey("fx_snapshot.id"), nullable=True),
        sa.Column(
            "cost_id", sa.String(36), sa.ForeignKey("provider_cost_record.id"), nullable=True
        ),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("matched_usd_micros", sa.BigInteger(), nullable=False),
        sa.Column("unmatched_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("set_by", sa.String(100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.String(40), nullable=False),
        sa.Column("replaced_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.UniqueConstraint("provider", "external_reference", name="uq_reconciliation_reference"),
        sa.CheckConstraint("scope IN ('PERIOD','CORRELATION')", name="ck_reconciliation_scope"),
        sa.CheckConstraint("usd_micros > 0", name="ck_reconciliation_positive"),
    )
    op.create_index(
        "ix_reconciliation_active", "provider_reconciliation", ["provider", "scope", "active"]
    )
    with op.batch_alter_table("provider_cost_record") as batch:
        batch.add_column(sa.Column("reconciled_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("reconciled_by_id", sa.String(36), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
