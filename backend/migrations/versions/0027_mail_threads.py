"""Messages become correspondence: a thread, a reply, and the letter itself.

`agent_message` recorded typed messages with a subject and a JSON body, each one alone. The
Owner asked for what an office has: a mail that says who wrote to whom, when, about what, why,
and how it ends — and that carries its history when it is forwarded, so everyone on the thread
reads the same exchange. Three columns do that:

- `thread_id`: the first message's id, inherited by every reply and forward. Existing rows
  each start their own thread (backfilled to their own id).
- `in_reply_to`: the message this one answers or forwards.
- `body_text`: the letter as written — the problem, why it is sent, the closing — beside the
  structured body the pipeline reads.

Nothing existing is rewritten; every new column is nullable.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_mail_threads"
down_revision = "0026_director_mandate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_message") as batch:
        batch.add_column(sa.Column("thread_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "in_reply_to",
                sa.String(36),
                sa.ForeignKey("agent_message.id", name="fk_agent_message_in_reply_to"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("body_text", sa.Text(), nullable=True))
    op.execute("UPDATE agent_message SET thread_id = id WHERE thread_id IS NULL")
    op.create_index("ix_agent_message_thread", "agent_message", ["thread_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
