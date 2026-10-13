"""The Director's verdict on a finished video, before it is published.

Until now nothing between the render and the upload judged the film: quality control measured
the file, the Publisher wrote metadata that described it honestly, and the Director read her
inbox after the fact. A finished video with no story, in the wrong language, resting on one
sourceless claim, went out. `editorial_review` is the record of the Director watching it —
what it is about, whether it may go, why not, and what each department is told — and the
publish stage requires an APPROVE here before anything reaches a channel.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_editorial_review"
down_revision = "0028_trend_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_review",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_asset_id", sa.String(36), sa.ForeignKey("media_asset.id"), nullable=False),
        sa.Column("storyboard_id", sa.String(36), sa.ForeignKey("storyboard.id"), nullable=True),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("story", sa.String(400), nullable=False, server_default=""),
        sa.Column("reasons_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notes_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reviewer_agent_id", sa.String(36), sa.ForeignKey("agent.id"), nullable=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("frames_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_used", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("domain_event.event_id"), nullable=True),
        sa.CheckConstraint("verdict IN ('APPROVE','REJECT')", name="ck_editorial_verdict"),
    )
    op.create_index(
        "ix_editorial_review_asset", "editorial_review", ["media_asset_id", "created_at"]
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrades are not supported")
