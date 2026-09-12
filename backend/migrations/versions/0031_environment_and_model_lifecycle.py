"""The studio has two environments, and a model has a life.

Three things the studio could not say, and paid for not saying. It could not say whether it
was testing or publishing, so an experiment bought the same shots a film does — twenty-one
dollars in an afternoon. It could not say where a price came from, so a steward's reading of
one page ("0.025 USD a second") outlived four renders that measured 0.43. And it could not
say that a model was new, so a model the vendor had just exposed was as usable as one the
studio had filmed with for weeks.

- ``owner_policy.environment`` — TEST or PRODUCTION, the studio's own state, changed by the
  Owner through the same versioned command that stops autonomy. Never a request parameter:
  a page cannot ask for production routing.
- ``provider_resource`` keeps a model's standing (DISCOVERED → QUARANTINE → BENCHMARKING →
  CANDIDATE → PRODUCTION → PREFERRED → DEPRECATED) and its price's provenance: which
  version, when it was verified, how, from where, and what it was before, so a change of
  price is a fact with a date rather than a silent overwrite.
- ``model_outcome`` records what a generation actually produced — its environment and kind,
  its scene category, what it cost, whether it was accepted first time — so the studio can
  learn cost per accepted second per category instead of trusting a single global score.
  Ordinary functional tests are recorded too, and marked, so they never distort what the
  studio believes about a model's picture.
"""

import sqlalchemy as sa
from alembic import op

revision = "0031_environment_and_model_lifecycle"
down_revision = "0030_search_template"
branch_labels = None
depends_on = None

#: A studio that does not know which environment it is in must not spend like a film studio.
DEFAULT_ENVIRONMENT = "TEST"

LIFECYCLE = (
    "DISCOVERED",
    "QUARANTINE",
    "BENCHMARKING",
    "CANDIDATE",
    "PRODUCTION",
    "PREFERRED",
    "DEPRECATED",
)


def upgrade() -> None:
    with op.batch_alter_table("owner_policy") as batch:
        batch.add_column(
            sa.Column(
                "environment",
                sa.String(20),
                nullable=False,
                server_default=DEFAULT_ENVIRONMENT,
            )
        )

    with op.batch_alter_table("provider_resource") as batch:
        # A model the vendor exposed today is not a model the studio has filmed with. Rows
        # that exist already are in production by the fact of having been used.
        batch.add_column(
            sa.Column(
                "production_status", sa.String(20), nullable=False, server_default="PRODUCTION"
            )
        )
        batch.add_column(
            sa.Column("pricing_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("price_verified_at", sa.String(40), nullable=True))
        #: DOCUMENTED (a vendor page), ESTIMATED (a dry run), BILLED (what a render was charged).
        batch.add_column(sa.Column("price_verification", sa.String(20), nullable=True))
        batch.add_column(sa.Column("previous_pricing_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("lifecycle_note", sa.Text(), nullable=True))

    op.create_table(
        "model_outcome",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_id", sa.String(36), sa.ForeignKey("integration.id"), nullable=False),
        sa.Column("remote_id", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        #: TEST_FUNCTIONAL | TEST_BENCHMARK | PRODUCTION — only the last two may teach quality.
        sa.Column("run_kind", sa.String(20), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False),
        #: What the shot was of, so a model can be good at humans and poor at vehicles.
        sa.Column("scene_category", sa.String(40), nullable=False, server_default="GENERAL"),
        sa.Column("quality_tier", sa.String(20), nullable=True),
        sa.Column("seconds_requested", sa.Float(), nullable=False, server_default="0"),
        sa.Column("seconds_accepted", sa.Float(), nullable=False, server_default="0"),
        sa.Column("credits", sa.Float(), nullable=True),
        sa.Column("usd", sa.Float(), nullable=True),
        sa.Column("first_pass", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        #: TECHNICAL | QUALITY | NONE — why a shot was not accepted, so escalation is reasoned.
        sa.Column("failure_kind", sa.String(20), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "render_job_id", sa.String(36), sa.ForeignKey("video_render_job.id"), nullable=True
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint(
            "run_kind IN ('TEST_FUNCTIONAL','TEST_BENCHMARK','PRODUCTION')",
            name="ck_model_outcome_kind",
        ),
        sa.CheckConstraint(
            "environment IN ('TEST','PRODUCTION')", name="ck_model_outcome_environment"
        ),
    )
    op.create_index(
        "ix_model_outcome_model",
        "model_outcome",
        ["integration_id", "remote_id", "purpose", "scene_category"],
    )
    op.create_index("ix_model_outcome_kind", "model_outcome", ["run_kind", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
