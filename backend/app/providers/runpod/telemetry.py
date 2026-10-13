from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.providers.runpod.jobs import GenerationJob


def generation_metrics(
    engine: Engine, project_id: str, *, finished: bool = False
) -> dict[str, Any]:
    with Session(engine) as s:
        rows = s.scalars(select(GenerationJob).where(GenerationJob.project_id == project_id)).all()
        cost = sum((Decimal(r.cost_value or "0") for r in rows), Decimal(0))
        unknown = sum(r.cost_value is None for r in rows)
        seconds = sum((Decimal(r.gpu_seconds_value or "0") for r in rows), Decimal(0))
        accepted_operation = "video" if any(r.operation == "video" for r in rows) else "image"
        scenes = {
            r.scene_id for r in rows if r.accepted is True and r.operation == accepted_operation
        }
        models: dict[str, dict[str, Any]] = {}
        for row in rows:
            reading = models.setdefault(row.model, {"accepted": 0, "reviewed": 0})
            if row.accepted is not None:
                reading["reviewed"] += 1
                reading["accepted"] += int(row.accepted)
        for reading in models.values():
            reading["acceptance_rate"] = (
                reading["accepted"] / reading["reviewed"] if reading["reviewed"] else None
            )
        attempts: dict[tuple[str, str], set[int]] = {}
        for row in rows:
            attempts.setdefault((row.scene_id, row.operation), set()).add(row.attempt)
        return {
            "provider": "RUNPOD_MOCK"
            if rows and all(r.provider == "RUNPOD_MOCK" for r in rows)
            else "RUNPOD",
            "project_id": project_id,
            "jobs": len(rows),
            "estimated_gpu_cost_usd": str(cost),
            "jobs_with_unknown_cost": unknown,
            "cost_per_accepted_scene_usd": str(cost / len(scenes))
            if scenes and not unknown
            else None,
            "cost_per_finished_short_usd": str(cost) if finished and not unknown else None,
            "gpu_minutes_per_short": str(seconds / 60) if finished and not unknown else None,
            "regenerations": sum(max(0, len(values) - 1) for values in attempts.values()),
            "accepted_scenes": len(scenes),
            "acceptance_by_model": models,
            "estimate_only": True,
        }
