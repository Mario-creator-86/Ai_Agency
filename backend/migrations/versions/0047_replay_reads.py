"""The replay reads the studio's own record by time: two indexes.

The headquarters' «Reluarea zilei» plays the newest finished run back from its events. The log
is paged by sequence, so finding the run's first event took about twelve one-event probes on the
Owner's data; `/events?since=` now finds it in one query over an index on the event's stamp
(`ix_domain_event_timestamp`). The Treasury and the tokens plate said «—» during a replay, since
the live books are not those of that night; `/economy/as-of` reads the day's spend and tokens up
to a moment, and the agent runs are read by when they started (`ix_agent_run_started`), which
also serves the live budget's own `started_at >= since` reads.

Additive: no row changes.
"""

from alembic import op

revision = "0047_replay_reads"
down_revision = "0046_agent_run_last_task"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_domain_event_timestamp", "domain_event", ["timestamp"])
    op.create_index("ix_agent_run_started", "agent_run", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_started", table_name="agent_run")
    op.drop_index("ix_domain_event_timestamp", table_name="domain_event")
