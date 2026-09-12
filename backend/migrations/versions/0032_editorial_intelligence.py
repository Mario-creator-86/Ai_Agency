"""A video has to be worth making, and the prompt has to carry the story.

The studio could produce a film and never answer why anyone should watch it. A topic was six
numbers and an angle; a script was narration that cited claims; a "video prompt" was the one
line the writer wrote under `visual` — "a spinning galaxy" — sent to a model that costs
dollars a shot. The Owner's answer to the first film was exact: the pictures were glued
together and the story did not hold. No video model can fix that.

So four things the studio could not state before, in the tables it already has:

- ``topic_idea.thesis_json`` — why this video should exist: the core fact, why now, why the
  audience should care, the payoff, a possible hook and ending, a call to action that belongs
  to the story, the risk, the expected length. Plus ``rejection_reasons_json``: an idea the
  editorial rules refuse is kept with the reasons, so the studio learns what it turned down
  and why.
- ``script_draft.story_json`` — the one message, what the viewer takes away, the hook, the
  ending, the call to action and its kind, and the structure the writer used. Scenes keep
  their own purpose, so a shot that exists only because it looks good can be found.
- ``story_review`` — the review that happens **before** anything is generated: does the
  opening earn the next three seconds, does every sentence advance the story, is there a real
  payoff that answers the hook, is the narration sayable in the target length, where would
  interest collapse. It is cheaper to rewrite text than to buy a shot twice.
- ``storyboard.visual_bible_json`` and ``storyboard_scene.prompt_json`` — the master visual
  bible the whole film inherits (style, world, palette, lighting, camera language, continuity
  rules, what to avoid) and the full prompt package per shot (subject, action, environment,
  camera, lighting, composition, motion, emotion, background, continuity, audio intent,
  transition, negatives, story purpose). The prompt package is the same quality in both
  environments: TEST saves money by choosing a cheaper model, never by thinking less.
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_editorial_intelligence"
down_revision = "0031_environment_and_model_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("topic_idea") as batch:
        #: Why this video should exist, as the proposer argued it. A score is an opinion about
        #: a candidate; this is the argument the opinion rests on.
        batch.add_column(sa.Column("thesis_json", sa.JSON(), nullable=True))
        #: The editorial rules an idea failed, if any. Kept rather than discarded: what the
        #: studio refused, and why, is how it learns which ideas are worth proposing.
        batch.add_column(sa.Column("rejection_reasons_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("script_draft") as batch:
        #: The story the script tells: one message, the takeaway, hook, ending, CTA and kind,
        #: and the estimated narration length at the studio's measured speaking rate.
        batch.add_column(sa.Column("story_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("storyboard") as batch:
        #: The master visual bible every shot of this film inherits.
        batch.add_column(sa.Column("visual_bible_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("storyboard_scene") as batch:
        #: The full prompt package for this shot, as the prompt agent wrote it.
        batch.add_column(sa.Column("prompt_json", sa.JSON(), nullable=True))
        #: Why this shot is in the film: HOOK, SETUP, DEVELOPMENT, EVIDENCE, REVEAL, PAYOFF,
        #: ENDING, CTA. A shot with no purpose is cut or redesigned.
        batch.add_column(sa.Column("story_purpose", sa.String(20), nullable=True))

    op.create_table(
        "story_review",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("script_id", sa.String(36), sa.ForeignKey("script_draft.id"), nullable=False),
        #: PASS | REVISE | REJECT — REVISE means the writer is asked once more with the notes.
        sa.Column("verdict", sa.String(10), nullable=False),
        #: The deterministic checks, each with its own pass and reason.
        sa.Column("checks_json", sa.JSON(), nullable=False),
        #: Expected interest at 0, 3, 5, 10, 15, 20, 25 seconds and at the ending, and where
        #: it is expected to collapse.
        sa.Column("retention_json", sa.JSON(), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("notes_json", sa.JSON(), nullable=False),
        sa.Column("estimated_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reviewer_agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint("verdict IN ('PASS','REVISE','REJECT')", name="ck_story_review_verdict"),
    )
    op.create_index("ix_story_review_script", "story_review", ["script_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
