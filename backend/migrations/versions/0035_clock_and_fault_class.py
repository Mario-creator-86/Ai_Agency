"""The day gets a fixed local hour, and a failed run says what kind of fault stopped it.

Measured on a copy of the live database: the daily job had never fired by itself, and the
one thing that had stopped the studio for days was a single transient error — SQLite's
"database is locked" at the wrong second — recorded as a failure of the same weight as a
bug, which opened safe mode and set the autonomy stop.

Two additive, nullable changes:

- ``scheduled_job.run_at_local`` ("HH:MM") and ``scheduled_job.timezone`` (IANA). When set,
  the scheduler fires the job at the next occurrence of that wall-clock time instead of
  anchoring it to the moment it was activated. The decision log of 2026-09-11 said a fixed
  hour "is the right shape and needs a column"; this is the column. The timezone is stored
  with the row because the activation route and the tick both need it and neither carries
  the application settings — and the orchestration architecture says a stored schedule
  stores its timezone. Jobs written before this revision keep NULL and stay interval-anchored.
- ``daily_run.fault_class`` (TRANSIENT | HARD) on a FAILED run. Runs written before this
  revision keep NULL, which is the truth about them: nobody classified their fault.
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_clock_and_fault_class"
down_revision = "0034_agent_multi_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN: both tables keep their constraints, and a nullable column with no
    # default needs no rebuild.
    op.add_column("scheduled_job", sa.Column("run_at_local", sa.String(5), nullable=True))
    op.add_column("scheduled_job", sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column("daily_run", sa.Column("fault_class", sa.String(12), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
