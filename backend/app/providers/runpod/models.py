from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import ROOT

STATUSES = (
    "QUEUED",
    "STARTING",
    "RUNNING",
    "UPLOADING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
)
TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"})


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    project_id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20000)
    negative_prompt: str | None = Field(default=None, max_length=20000)
    aspect_ratio: str = Field(default="9:16", pattern=r"^[1-9][0-9]{0,3}:[1-9][0-9]{0,3}$")
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    quality: Literal["QUALITY", "HERO", "AUTO"] = "QUALITY"
    model: str | None = Field(default=None, max_length=100)
    reference_images: list[str] = Field(default_factory=list, max_length=8)
    attempt_number: int = Field(default=1, ge=1, le=1000)
    candidate_index: int = Field(default=0, ge=0, le=7)
    original_prompt: str | None = Field(default=None, max_length=20000)
    previous_seed: int | None = None
    previous_model: str | None = None
    qa_reason: str | None = Field(default=None, max_length=4000)
    qa_feedback: list[str] = Field(default_factory=list, max_length=20)
    generation_history: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    mock_failure: bool = False


class ImageRequest(GenerationRequest):
    quality: Literal["QUALITY", "HERO"] = "QUALITY"
    width: int = Field(default=1080, ge=64, le=8192)
    height: int = Field(default=1920, ge=64, le=8192)
    style: str | None = Field(default=None, max_length=1000)


class VideoRequest(GenerationRequest):
    source_image: str | None = None
    duration: float = Field(default=5, gt=0, le=120)
    fps: int = Field(default=24, ge=1, le=120)
    resolution: str = Field(default="1080x1920", max_length=30)
    motion_strength: float | None = Field(default=None, ge=0, le=1)
    camera_motion: str | None = Field(default=None, max_length=1000)


class FinalizeRequest(GenerationRequest):
    source_video: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


#: The pinned RunPod Serverless catalogue (Owner decisions 2026-10-08): models, licences and
#: the GPU-second ESTIMATES until the paid bake-off measures them.
MODELS_FILE = ROOT / "config" / "runpod_models.json"


@lru_cache(maxsize=4)
def _catalogue(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("config/runpod_models.json: unknown schema")
    return data


def serverless_catalogue(path: Path | None = None) -> dict[str, Any]:
    """The whole pinned catalogue (models, worker images, budget rate)."""
    return _catalogue(str(path or MODELS_FILE))


def serverless_models(endpoints: dict[str, bool] | None = None) -> list[dict[str, Any]]:
    """The models of the catalogue whose endpoint (stills / motion) is configured.

    ``endpoints`` maps "stills"/"motion" to whether that endpoint exists; None keeps all."""
    rows = [dict(row) for row in serverless_catalogue()["models"]]
    if endpoints is None:
        return rows
    return [row for row in rows if endpoints.get(str(row.get("endpoint")))]
