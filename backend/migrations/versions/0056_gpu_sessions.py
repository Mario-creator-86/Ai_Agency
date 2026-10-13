"""RunPod Serverless GPU sessions, batch columns of the journal, and no pictures in it.

- ``gpu_session``: one row per paid step that switched the GPU on (workers.max=1) and how it was
  switched off (purge, cancel, workers.max=0, verified OFF), so the guard can find a GPU left on
  by a crashed process (2026-10-08, the Owner: «trebuie oprit imediat dupa generare»).
- ``cloud_generation_job`` gains the batch a request travelled in (``batch_remote_id``,
  ``batch_index``), the request's digest, its GPU session and the billed seconds.
- Data: every ``data:<mime>;base64,...`` picture inside a journal row's ``request``
  (``reference_images[]`` and ``source_image``) is replaced by {"sha256", "bytes", "mime"}.
  ``payload_hash`` is left as it was. Batched and idempotent. The downgrade drops the table and
  the columns and cannot restore the pictures (they were never the journal's to keep).
"""

import base64
import binascii
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0056_gpu_sessions"
down_revision = "0055_cloud_generation_jobs"
branch_labels = None
depends_on = None

BATCH = 50


def _fingerprint(value: Any) -> Any:
    if not isinstance(value, str) or not value.startswith("data:") or ";base64," not in value:
        return value
    head, _, encoded = value.partition(";base64,")
    try:
        content = base64.b64decode(encoded, validate=False)
    except (binascii.Error, ValueError):
        return value
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "mime": head[len("data:") :] or "application/octet-stream",
    }


def _slim(request: dict[str, Any]) -> dict[str, Any] | None:
    changed = False
    out = dict(request)
    references = request.get("reference_images")
    if isinstance(references, list):
        slim = [_fingerprint(item) for item in references]
        if slim != references:
            out["reference_images"], changed = slim, True
    source = request.get("source_image")
    slim_source = _fingerprint(source)
    if slim_source != source:
        out["source_image"], changed = slim_source, True
    return out if changed else None


def upgrade() -> None:
    op.create_table(
        "gpu_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("integration_id", sa.String(36), nullable=False),
        sa.Column("endpoint_id", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("step", sa.String(30), nullable=False),
        sa.Column("storyboard_id", sa.String(100), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("process_token", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("workers_max", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.String(40), nullable=False),
        sa.Column("renewed_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("closed_at", sa.String(40), nullable=True),
        sa.Column("close_reason", sa.String(40), nullable=True),
        sa.Column("verified_off", sa.Boolean(), nullable=True),
        sa.Column("off_reading", sa.JSON(), nullable=True),
        sa.Column("remote_job_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPENING','OPEN','CLOSING','CLOSED','FAILED_OPEN','FORCED_OFF')",
            name="ck_gpu_session_status",
        ),
        sa.CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('STEP_DONE','STEP_FAILED','OWNER_OFF',"
            "'GUARD_ORPHAN','GUARD_STALE','GUARD_TTL','BOOT','SHUTDOWN','LAUNCHER_STOP',"
            "'OPEN_FAILED')",
            name="ck_gpu_session_close_reason",
        ),
        sa.CheckConstraint("purpose IN ('image','video')", name="ck_gpu_session_purpose"),
    )
    op.create_index("ix_gpu_session_endpoint_status", "gpu_session", ["endpoint_id", "status"])
    with op.batch_alter_table("cloud_generation_job") as batch:
        batch.add_column(sa.Column("batch_remote_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("batch_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("request_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("gpu_session_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("billed_seconds_value", sa.String(40), nullable=True))
        batch.create_index("ix_cloud_generation_job_batch_remote_id", ["batch_remote_id"])

    connection = op.get_bind()
    last = ""
    while True:
        rows = connection.execute(
            sa.text(
                "SELECT id, request FROM cloud_generation_job WHERE id > :last "
                "AND request LIKE '%data:%;base64,%' ORDER BY id LIMIT :limit"
            ),
            {"last": last, "limit": BATCH},
        ).fetchall()
        if not rows:
            break
        for identifier, raw in rows:
            last = identifier
            try:
                request = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if not isinstance(request, dict):
                continue
            slim = _slim(request)
            if slim is not None:
                connection.execute(
                    sa.text("UPDATE cloud_generation_job SET request = :request WHERE id = :id"),
                    {"request": json.dumps(slim), "id": identifier},
                )


def downgrade() -> None:
    with op.batch_alter_table("cloud_generation_job") as batch:
        batch.drop_index("ix_cloud_generation_job_batch_remote_id")
        batch.drop_column("billed_seconds_value")
        batch.drop_column("gpu_session_id")
        batch.drop_column("request_digest")
        batch.drop_column("batch_index")
        batch.drop_column("batch_remote_id")
    op.drop_index("ix_gpu_session_endpoint_status", table_name="gpu_session")
    op.drop_table("gpu_session")
