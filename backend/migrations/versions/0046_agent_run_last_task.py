"""Each employee's last task is read from an index, not the whole run table.

The headquarters' name tags show an employee's last real task. The page could only read it
from the events it had replayed, so six of the Owner's eight employees said «—» although every
one of them has runs recorded. The snapshot the page polls every five seconds now carries the
newest run of each employee (app.services.last_task_per_agent): one grouped MAX(started_at) per
agent. This index makes that a walk of the index instead of a scan of every run ever made.

Additive: no row changes.
"""

from alembic import op

revision = "0046_agent_run_last_task"
down_revision = "0045_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_agent_run_agent_started", "agent_run", ["agent_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_agent_started", table_name="agent_run")
