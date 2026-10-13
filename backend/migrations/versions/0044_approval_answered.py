"""An approval request is about a thing, and the Owner's answer is on the row.

Measured before this revision: `app.services.request_approval` deduped a standing request by
its `action` alone. Under SUPERVISED the second, dearer film of the day reused the first
film's row for `media.paid_generation_over_threshold`, and two films sent to two channels in
one day shared one row for `publishing.public_publish`. Nothing consumed an APPROVED row yet,
so nothing was wrong yet — but the answering route that lands with this revision would have
let the Owner's "yes" to a four-dollar film silently authorise a forty-dollar one.

Four additive columns:

- ``subject`` — the specific thing the request is about: the media asset for an upload, the
  storyboard for a paid render. The key is now (action, subject), so one answer covers one
  thing. Existing rows take "" and dedupe as they did, which is the right reading for an
  action about the studio itself rather than about a film.
- ``note`` — the Owner's own words when he answers, carried into the Romanian reason the
  publish stage reports back to him.
- ``decided_at`` — when he answered.
- ``consumed_at`` — when the studio spent the answer. An approval authorises one act, once:
  this column is what the gate reads before it lets a film past, so a yes cannot serve two
  films or two days. The ledger carries the same fact as `governance.approval_consumed`;
  the column is the lock, the event is the record.

No data is rewritten and nothing is dropped: a request written before this revision keeps its
action, its evidence and its result, and reads as a request about nothing in particular.
"""

import sqlalchemy as sa
from alembic import op

revision = "0044_approval_answered"
down_revision = "0043_autonomy_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("owner_approval_request") as batch:
        batch.add_column(sa.Column("subject", sa.String(100), nullable=False, server_default=""))
        batch.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("consumed_at", sa.String(40), nullable=True))
    # The question every gated act asks before it acts: what did the Owner answer about
    # *this* film. `ix_approval_open` answers the Owner's own question (what is waiting).
    op.create_index(
        "ix_approval_subject", "owner_approval_request", ["action", "subject", "result"]
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
