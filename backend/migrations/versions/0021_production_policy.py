"""Production policy per channel, the configuration hierarchy, and character identity locks.

Technology (providers, models, voices) is replaceable; a recurring character is not. Until now
one global voice/model on a connection was the only production choice, so a video for the
factual channel and an episode of the office serial were forced onto the same voice, and a
better model arriving in discovery could only be adopted by changing that one choice for
everyone. This migration adds the places where the difference lives:

- `channel_record`: production policy (FLEXIBLE | CONSISTENCY_LOCKED), channel defaults, series
  rules and an override switch. The policy column is NULL here; the channel seed fills it from
  the stored channel type, and the Owner can change it afterwards.
- `media_production_config`: the existing model/voice becomes the Organization default with an
  `allow_production_override` switch (True: it is a fallback, not a rule).
- `character_bible`: voice binding, identity locks, approved technology fallbacks and a
  consistency status.
- `storyboard` / `storyboard_scene`: channel, series key and per-level overrides.
- `video_render_job`: the production record of what was actually used.
- `character_identity_change`: the PROPOSED -> TESTING -> APPROVED | REJECTED workflow.

Nothing existing is rewritten: connections, discovered resources, defaults and channel rows
keep their values.
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_production_policy"
down_revision = "0020_character_persona"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel_record") as batch:
        batch.add_column(sa.Column("production_policy", sa.String(30), nullable=True))
        batch.add_column(
            sa.Column(
                "production_defaults_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "series_rules_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            )
        )
        batch.add_column(
            sa.Column(
                "allow_production_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("media_production_config") as batch:
        batch.add_column(
            sa.Column(
                "allow_production_override",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("character_bible") as batch:
        for column in ("voice_binding_json", "identity_locks_json"):
            batch.add_column(
                sa.Column(column, sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
            )
        batch.add_column(
            sa.Column(
                "approved_fallbacks_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "consistency_status",
                sa.String(20),
                nullable=False,
                server_default="UNVERIFIED",
            )
        )
    with op.batch_alter_table("storyboard") as batch:
        batch.add_column(
            sa.Column(
                "channel_id",
                sa.String(36),
                sa.ForeignKey("channel_record.id", name="fk_storyboard_channel"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("series_key", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column(
                "production_overrides_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
    with op.batch_alter_table("storyboard_scene") as batch:
        batch.add_column(
            sa.Column(
                "production_overrides_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
    with op.batch_alter_table("video_render_job") as batch:
        batch.add_column(
            sa.Column("production_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    op.create_table(
        "character_identity_change",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "character_id",
            sa.String(36),
            sa.ForeignKey("character_bible.id"),
            nullable=False,
        ),
        sa.Column("field", sa.String(20), nullable=False),
        sa.Column("proposed_json", sa.JSON(), nullable=False),
        sa.Column("previous_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROPOSED"),
        sa.Column("proposed_by_agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("test_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("decided_by", sa.String(100), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("decided_at", sa.String(40), nullable=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "status IN ('PROPOSED','TESTING','APPROVED','REJECTED')",
            name="ck_identity_change_status",
        ),
        sa.CheckConstraint(
            "field IN ('voice','visual','personality','speech_style')",
            name="ck_identity_change_field",
        ),
    )
    op.create_index(
        "ix_identity_change_character",
        "character_identity_change",
        ["character_id", "status"],
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
