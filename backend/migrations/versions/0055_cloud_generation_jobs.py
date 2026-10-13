"""RunPod submission identity, restart recovery and generation telemetry."""

import sqlalchemy as sa
from alembic import op

revision = "0055_cloud_generation_jobs"
down_revision = "0054_owner_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_generation_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("integration_id", sa.String(36)),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("scene_id", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("gpu", sa.String(100), nullable=False),
        sa.Column("hourly_rate", sa.String(40), nullable=False),
        sa.Column("remote_job_id", sa.String(200)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("started_at", sa.String(40)),
        sa.Column("finished_at", sa.String(40)),
        sa.Column("gpu_seconds_value", sa.String(40)),
        sa.Column("cost_value", sa.String(40)),
        sa.Column("accepted", sa.Boolean()),
        sa.Column("quality_result", sa.Text()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("asset_path", sa.String(500)),
        sa.Column("asset_sha256", sa.String(64)),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("idempotency_key", name="uq_cloud_generation_key"),
        sa.CheckConstraint("attempt >= 1", name="ck_cloud_generation_attempt"),
        sa.CheckConstraint(
            "status IN ('QUEUED','STARTING','RUNNING','UPLOADING',"
            "'COMPLETED','FAILED','CANCELLED','TIMEOUT')",
            name="ck_cloud_generation_status",
        ),
    )
    op.create_index("ix_cloud_generation_job_project_id", "cloud_generation_job", ["project_id"])
    op.create_index(
        "ix_cloud_generation_job_remote_job_id", "cloud_generation_job", ["remote_job_id"]
    )


def downgrade() -> None:
    op.drop_table("cloud_generation_job")
