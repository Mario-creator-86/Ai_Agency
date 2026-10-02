"""A paid task is on the books before the studio waits for it: the take's intent.

Until this revision the id of a task Runway had accepted, and would bill, lived only in the
memory of the process that asked for it. A poll that ran out of time was recorded REFUSED with
the id thrown away; a download that failed lost it the same way; a process killed between the
purchase and its row left nothing at all. The next run saw a scene with no take and bought it
again. (Measured on fakes, 2026-10-01: failed stills and clips were bought again on every run.)

Three changes to ``scene_take``:

- ``remote_task_id``: the vendor's task id, written in its own short transaction the moment the
  vendor accepts the request, before the studio polls. Indexed: the watchdog and the steps look
  takes up by it to collect them.
- the statuses SUBMITTED (accepted by the vendor, its output not collected yet: never bought
  again, collected with a free GET) and LOST (accepted and never collected before the vendor's
  output expired: the Owner gets a letter, and the scene may be planned again);
- the kind ``narration``, so a narration purchase can be booked as a take like a still or a shot.

Why a batch rebuild here, when 0048 avoided one: the change is to ``scene_take``'s own named
CHECK constraints, which SQLite cannot alter in place. The rebuild copies from an explicit
description of the table (``copy_from``), never from reflection, so every column, the identity
UNIQUE, the scene_number CHECK, both foreign keys and the scene index come back exactly.

The way down: a SUBMITTED or LOST take becomes REFUSED with ``DOWNGRADE.<status>`` as its failure
code (what 0048 can say about a task it cannot collect); a narration take stops the downgrade,
because 0048 has no word for it and deleting a paid row is not a migration's decision.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0049_take_intent"
down_revision = "0048_production_sheet"
branch_labels = None
depends_on = None

OLD_TAKE_KINDS = ("still", "motion", "test_shot")
OLD_TAKE_STATUSES = ("QUOTED", "PAID", "APPROVED", "REJECTED", "REFUSED")
TAKE_KINDS = ("still", "motion", "test_shot", "narration")
TAKE_STATUSES = ("QUOTED", "SUBMITTED", "PAID", "APPROVED", "REJECTED", "REFUSED", "LOST")
#: The statuses 0048 cannot hold; on the way down each becomes REFUSED.
NEW_STATUSES = ("SUBMITTED", "LOST")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ",".join(f"'{value}'" for value in values) + ")"


def _scene_take(kinds: tuple[str, ...], statuses: tuple[str, ...], *, task_id: bool) -> sa.Table:
    """``scene_take`` as it stands before the rebuild, written out (0048's shape, plus the
    task id when ``task_id``). Its two parents are named so the foreign keys compile."""
    metadata = sa.MetaData()
    sa.Table("storyboard", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("domain_event", metadata, sa.Column("event_id", sa.String(36), primary_key=True))
    columns: list[sa.Column[Any]] = [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storyboard_id", sa.String(36), sa.ForeignKey("storyboard.id"), nullable=False),
        sa.Column("scene_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("resolution", sa.String(20), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("credits_quoted", sa.Float(), nullable=True),
        sa.Column("credits_measured", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUOTED"),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_detail", sa.String(500), nullable=True),
        sa.Column("path", sa.String(500), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
    ]
    if task_id:
        columns.append(sa.Column("remote_task_id", sa.String(100), nullable=True))
    return sa.Table(
        "scene_take",
        metadata,
        *columns,
        sa.CheckConstraint(_in("kind", kinds), name="ck_scene_take_kind"),
        sa.CheckConstraint(_in("status", statuses), name="ck_scene_take_status"),
        sa.CheckConstraint("scene_number >= 1", name="ck_scene_take_scene_number"),
        sa.UniqueConstraint(
            "storyboard_id",
            "scene_number",
            "kind",
            "prompt_hash",
            "sha256",
            name="uq_scene_take_identity",
        ),
        sa.Index("ix_scene_take_scene", "storyboard_id", "scene_number", "kind", "status"),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        "scene_take",
        recreate="always",
        copy_from=_scene_take(OLD_TAKE_KINDS, OLD_TAKE_STATUSES, task_id=False),
    ) as batch:
        batch.add_column(sa.Column("remote_task_id", sa.String(100), nullable=True))
        batch.drop_constraint("ck_scene_take_kind", type_="check")
        batch.drop_constraint("ck_scene_take_status", type_="check")
        batch.create_check_constraint("ck_scene_take_kind", _in("kind", TAKE_KINDS))
        batch.create_check_constraint("ck_scene_take_status", _in("status", TAKE_STATUSES))
    op.create_index("ix_scene_take_remote_task", "scene_take", ["remote_task_id"])


def downgrade() -> None:
    bind = op.get_bind()
    narrations = bind.execute(
        sa.text("SELECT COUNT(*) FROM scene_take WHERE kind = 'narration'")
    ).scalar()
    if narrations:
        raise RuntimeError(
            f"{narrations} narration take(s) exist; 0048 has no kind for them and a paid row "
            "is not deleted by a migration. Remove them deliberately before downgrading."
        )
    op.execute(
        "UPDATE scene_take SET failure_code = 'DOWNGRADE.' || status, status = 'REFUSED'"
        f" WHERE {_in('status', NEW_STATUSES)}"
    )
    op.drop_index("ix_scene_take_remote_task", table_name="scene_take")
    with op.batch_alter_table(
        "scene_take",
        recreate="always",
        copy_from=_scene_take(TAKE_KINDS, TAKE_STATUSES, task_id=True),
    ) as batch:
        batch.drop_column("remote_task_id")
        batch.drop_constraint("ck_scene_take_kind", type_="check")
        batch.drop_constraint("ck_scene_take_status", type_="check")
        batch.create_check_constraint("ck_scene_take_kind", _in("kind", OLD_TAKE_KINDS))
        batch.create_check_constraint("ck_scene_take_status", _in("status", OLD_TAKE_STATUSES))
