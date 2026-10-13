"""The production sheet's rows: scene kinds, paid takes, and the Owner's rule for paid media.

Measured on the Nepal film (storyboard 1d530880, 2026-09-26): a bar chart of 100 against 83
billion and a black screen were sent to a photographic image model, because the only kind the
studio knew was the storyboard-wide ``visual_style``; a second full render bought every still
and every clip again with the same prompts, because nothing recorded that a take had already
been paid for; and it ran without a question, because no rule of the Owner's covered paid media.
Over 1000 credits went on two films of which neither could be published.

Three additions, all additive for existing rows:

- ``storyboard_scene.scene_kind`` — LIVE | DATA_CARD | TITLE_CARD | BLACK, and
  ``storyboard_scene.card_json`` for a composed card's spec. Existing scenes are LIVE, which is
  what every one of them was treated as.
- ``scene_take`` — one row per paid (or quoted, or refused) asset: a still, a motion clip or the
  hero test shot, with the prompt hash, model, resolution, seconds, seed, credits quoted and
  measured, and a status the database restricts to QUOTED | PAID | APPROVED | REJECTED |
  REFUSED. One file of one prompt for one scene is one row, so an approved take is found again
  instead of bought again.
- ``owner_policy.paid_media_approval`` — EVERY_PAID_STEP | OVER_USD | MODE, with
  ``paid_media_approval_over_usd`` holding the threshold that OVER_USD, and only OVER_USD,
  carries. It starts at EVERY_PAID_STEP, the strictest reading.

Why plain ``ALTER TABLE ... ADD COLUMN`` with an inline CHECK and not a batch rebuild:
``owner_policy`` and ``storyboard_scene`` carry unnamed CHECK constraints (``id = 1``,
``version >= 1``) that Alembic's batch mode does not reflect, so a rebuild would drop them
silently. SQLite accepts a CHECK on an added column and tests it against existing rows; a
column's own CHECK leaves with the column on the way down (SQLite 3.35+ ``DROP COLUMN``).
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_production_sheet"
down_revision = "0047_replay_reads"
branch_labels = None
depends_on = None

SCENE_KINDS = ("LIVE", "DATA_CARD", "TITLE_CARD", "BLACK")
TAKE_KINDS = ("still", "motion", "test_shot")
TAKE_STATUSES = ("QUOTED", "PAID", "APPROVED", "REJECTED", "REFUSED")
PAID_MEDIA_APPROVALS = ("EVERY_PAID_STEP", "OVER_USD", "MODE")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ",".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE storyboard_scene ADD COLUMN scene_kind VARCHAR(20) DEFAULT 'LIVE' NOT NULL"
        f" CONSTRAINT ck_scene_kind CHECK ({_in('scene_kind', SCENE_KINDS)})"
    )
    op.add_column("storyboard_scene", sa.Column("card_json", sa.JSON(), nullable=True))

    op.execute(
        "ALTER TABLE owner_policy ADD COLUMN paid_media_approval VARCHAR(20)"
        " DEFAULT 'EVERY_PAID_STEP' NOT NULL CONSTRAINT ck_paid_media_approval"
        f" CHECK ({_in('paid_media_approval', PAID_MEDIA_APPROVALS)})"
    )
    # The threshold's CHECK names both columns: it lives on the threshold, which is added (and
    # dropped) after the rule, so each column can leave with its own constraint.
    op.execute(
        "ALTER TABLE owner_policy ADD COLUMN paid_media_approval_over_usd FLOAT"
        " CONSTRAINT ck_paid_media_over_usd CHECK ("
        "(paid_media_approval = 'OVER_USD') = (paid_media_approval_over_usd IS NOT NULL)"
        " AND (paid_media_approval_over_usd IS NULL OR paid_media_approval_over_usd >= 0))"
    )

    op.create_table(
        "scene_take",
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
        sa.CheckConstraint(_in("kind", TAKE_KINDS), name="ck_scene_take_kind"),
        sa.CheckConstraint(_in("status", TAKE_STATUSES), name="ck_scene_take_status"),
        sa.CheckConstraint("scene_number >= 1", name="ck_scene_take_scene_number"),
        sa.UniqueConstraint(
            "storyboard_id",
            "scene_number",
            "kind",
            "prompt_hash",
            "sha256",
            name="uq_scene_take_identity",
        ),
    )
    # The question the sheet and the purchase loop ask: what does this scene already have.
    op.create_index(
        "ix_scene_take_scene", "scene_take", ["storyboard_id", "scene_number", "kind", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_scene_take_scene", table_name="scene_take")
    op.drop_table("scene_take")
    op.execute("ALTER TABLE owner_policy DROP COLUMN paid_media_approval_over_usd")
    op.execute("ALTER TABLE owner_policy DROP COLUMN paid_media_approval")
    op.execute("ALTER TABLE storyboard_scene DROP COLUMN card_json")
    op.execute("ALTER TABLE storyboard_scene DROP COLUMN scene_kind")
