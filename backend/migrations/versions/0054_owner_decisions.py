"""The Owner's decisions: one card per question he alone answers (2026-10-03).

His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
card.» Until 0054 the audit's questions to him (the daily budget, reconnecting Ollama Cloud and
YouTube, commercial use, the music library, narration as a paid step, when to leave
EVERY_PAID_STEP, editorial QC, old test films, sale terms) lived only in CURRENT_STATUS and in
letters. ``owner_decision`` holds each as a card: what, why, the effect, the options with the
recommended one first and how each applies, the source that proposed it, his answer and what
applying it did.

- ``dedupe_key``: one OPEN card (PENDING or WAITING_FOR_OWNER_ACTION) per key, enforced by a
  partial unique index, so a stage that proposes the same question every day adds nothing;
- ``status``: PENDING, ACCEPTED, REFUSED, WAITING_FOR_OWNER_ACTION, WITHDRAWN, EXPIRED;
- ``version``: bumped on every transition, so an answer given from a stale page is refused.

A new table only; nothing existing is touched. The way down drops it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_owner_decisions"
down_revision = "0053_channel_upload_settings"
branch_labels = None
depends_on = None

STATUSES = "'PENDING','ACCEPTED','REFUSED','WAITING_FOR_OWNER_ACTION','WITHDRAWN','EXPIRED'"


def upgrade() -> None:
    op.create_table(
        "owner_decision",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=True),
        sa.Column("subject_id", sa.String(100), nullable=True),
        sa.Column("title_ro", sa.String(300), nullable=False),
        sa.Column("why_ro", sa.Text(), nullable=False),
        sa.Column("effect_ro", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("clears_when", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("chosen_option", sa.String(60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decided_at", sa.String(40), nullable=True),
        sa.Column("applied", sa.JSON(), nullable=True),
        sa.Column("apply_error_ro", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.String(40), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_owner_decision_status"),
        sa.CheckConstraint("version >= 1", name="ck_owner_decision_version"),
    )
    op.create_index("ix_owner_decision_status", "owner_decision", ["status", "created_at"])
    op.create_index(
        "uq_owner_decision_open_key",
        "owner_decision",
        ["dedupe_key"],
        unique=True,
        sqlite_where=sa.text("status IN ('PENDING','WAITING_FOR_OWNER_ACTION')"),
    )


def downgrade() -> None:
    op.drop_index("uq_owner_decision_open_key", table_name="owner_decision")
    op.drop_index("ix_owner_decision_status", table_name="owner_decision")
    op.drop_table("owner_decision")
