"""Durable provider submission journal in the Agency DB, never a second queue."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Engine, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import lock_for_write
from app.models import Base
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import IdempotencyConflict, RunPodProtocolError
from app.providers.runpod.models import STATUSES, TERMINAL


def now() -> str:
    return datetime.now(UTC).isoformat()


class GenerationJob(Base):
    __tablename__ = "cloud_generation_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_cloud_generation_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    integration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    scene_id: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    gpu: Mapped[str] = mapped_column(String(100), nullable=False)
    hourly_rate: Mapped[str] = mapped_column(String(40), nullable=False)
    remote_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gpu_seconds_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cost_value: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    asset_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    asset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Migration 0056: one RunPod /run job carries a whole round (``amn.batch.v1``); each item
    # keeps its own row, key and SceneTake. ``remote_job_id`` is then "<job>:<index>".
    batch_remote_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    batch_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # sha256 of the request as journalled (pictures as {sha256, bytes, mime}, never base64).
    # NULL on rows written before 0056: those compare by key only once terminal.
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gpu_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The batch's billed estimate apportioned to this item (seconds, Decimal as text).
    billed_seconds_value: Mapped[str | None] = mapped_column(String(40), nullable=True)

    @property
    def gpu_seconds(self) -> float | None:
        return float(self.gpu_seconds_value) if self.gpu_seconds_value is not None else None

    @property
    def estimated_cost_usd(self) -> Decimal | None:
        return Decimal(self.cost_value) if self.cost_value is not None else None


def _picture_digest(value: Any) -> Any:
    """A ``data:<mime>;base64,...`` picture as the journal keeps it: {sha256, bytes, mime}."""
    if not isinstance(value, str) or not value.startswith("data:") or ";base64," not in value:
        return value
    head, _, encoded = value.partition(";base64,")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return {
            "sha256": hashlib.sha256(value.encode()).hexdigest(),
            "bytes": len(value),
            "mime": head.removeprefix("data:")[:100],
        }
    return {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "mime": head.removeprefix("data:")[:100],
    }


def journal_request(payload: dict[str, Any]) -> dict[str, Any]:
    """The request as the journal keeps it: every inline picture replaced by its digest.

    2026-10-08: rows of 6.7 MB held base64 pictures; the digest identifies the picture just as
    well for idempotency, and the picture itself is the studio's file, not the journal's."""
    kept = dict(payload)
    if isinstance(kept.get("reference_images"), list):
        kept["reference_images"] = [_picture_digest(v) for v in kept["reference_images"]]
    if "source_image" in kept:
        kept["source_image"] = _picture_digest(kept["source_image"])
    return kept


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def target_identity(config: RunPodConfig, integration_id: str | None) -> str:
    return digest(
        [config.mode, config.endpoint_id, config.generation_base_url, config.mock, integration_id]
    )


class JobStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def reserve(
        self,
        operation: str,
        payload: dict[str, Any],
        config: RunPodConfig,
        integration_id: str | None,
    ) -> tuple[GenerationJob, bool]:
        target = target_identity(config, integration_id)
        key = digest(
            [
                target,
                payload["project_id"],
                payload["scene_id"],
                payload["attempt_number"],
                operation,
                payload.get("candidate_index", 0),
            ]
        )
        journal = journal_request(payload)
        hashed = digest(journal)
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            lock_for_write(s)
            job = s.scalar(select(GenerationJob).where(GenerationJob.idempotency_key == key))
            if job is not None:
                if job.request_digest is not None:
                    same = job.request_digest == hashed
                else:
                    # A row from before 0056 (its hash covered the base64 pictures): compared
                    # by key alone once it is finished; an open one that differs stays a
                    # conflict, never a second purchase.
                    same = job.payload_hash == digest(payload) or job.status in TERMINAL
                if not same:
                    raise IdempotencyConflict("Generation key was already used for another payload")
                if (
                    job.status == "FAILED"
                    and job.remote_job_id is None
                    and (job.error_code == "UNSENT" or str(job.error_code).startswith("HTTP_"))
                ):
                    # A proven refusal/unsent request can reuse its creative attempt/key.
                    job.status, job.error_code, job.finished_at = "STARTING", None, None
                    job.cost_value = job.gpu_seconds_value = None
                    return job, True
                return job, False
            job = GenerationJob(
                id=str(uuid4()),
                idempotency_key=key,
                payload_hash=hashed,
                request_digest=hashed,
                integration_id=integration_id,
                provider="RUNPOD_MOCK" if config.mock else "RUNPOD",
                target=target,
                project_id=payload["project_id"],
                scene_id=payload["scene_id"],
                attempt=payload["attempt_number"],
                operation=operation,
                model=payload["model"],
                gpu="MOCK_CPU" if config.mock else config.gpu_name,
                hourly_rate=str(config.hourly_rate),
                status="STARTING",
                request=journal,
                output={},
                created_at=now(),
                poll_count=0,
            )
            s.add(job)
            return job, True

    def read(self, identifier: str, *, target: str | None = None) -> GenerationJob:
        with Session(self.engine) as s:
            query = select(GenerationJob).where(
                (GenerationJob.id == identifier) | (GenerationJob.remote_job_id == identifier)
            )
            if target is not None:
                query = query.where(GenerationJob.target == target)
            row = s.execute(query).scalar_one_or_none()
            if row is None:
                raise RunPodProtocolError("RunPod job is not in this Agency's journal")
            s.expunge(row)
            return row

    def update(self, identifier: str, **values: Any) -> GenerationJob:
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            lock_for_write(s)
            row = s.get(GenerationJob, identifier)
            if row is None:
                raise RunPodProtocolError("RunPod job is not in this Agency's journal")
            if "status" in values and values["status"] not in STATUSES:
                raise RunPodProtocolError("Unknown RunPod job status")
            for key, value in values.items():
                setattr(row, key, value)
            return row
