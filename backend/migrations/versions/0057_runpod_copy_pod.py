"""The one-time RunPod copy pod that fills the Owner's private Hugging Face mirrors.

- ``runpod_copy_pod``: one row per copy his card «Copiez modelele în contul tău Hugging Face cu
  un server RunPod temporar?» started (2026-10-09): the pod, the cap he read (minutes, USD),
  what RunPod charged per hour, whether its termination was verified, what it cost and what it
  copied. The guard reads it to terminate the pod on success, failure, a cap or a restart.

The downgrade drops the table.
"""

import sqlalchemy as sa
from alembic import op

revision = "0057_runpod_copy_pod"
down_revision = "0056_gpu_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runpod_copy_pod",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("decision_inner", sa.String(36), nullable=True),
        sa.Column("pod_name", sa.String(100), nullable=False),
        sa.Column("pod_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("repos", sa.JSON(), nullable=False),
        sa.Column("max_minutes", sa.Integer(), nullable=False),
        sa.Column("max_usd", sa.String(20), nullable=False),
        sa.Column("rate_usd_per_hour", sa.String(20), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=True),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column("terminated_at", sa.String(40), nullable=True),
        sa.Column("terminate_verified", sa.Boolean(), nullable=True),
        sa.Column("cost_usd", sa.String(20), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.CheckConstraint(
            "status IN ('CREATING','RUNNING','SUCCEEDED','FAILED','TIMED_OUT','OVER_COST',"
            "'STOPPED')",
            name="ck_runpod_copy_pod_status",
        ),
    )
    op.create_index("ix_runpod_copy_pod_status", "runpod_copy_pod", ["status"])


def downgrade() -> None:
    op.drop_index("ix_runpod_copy_pod_status", table_name="runpod_copy_pod")
    op.drop_table("runpod_copy_pod")
