"""Quality control refuses a film the old way made (2026-10-02, DAY_FLOW_NO_STALL / A12).

The second Nepal render (3ec1740c, 2026-09-26) was bought whole by the legacy path, from
template prompts, after its shot plan was lost. It never reached quality control, so it sat in
the queue as a video with no verdict: the next day's QC would have measured it as a file and
could have handed it to publishing. A film is now judged on how it was made as well as on
what the file measures: in PRODUCTION, scenes filmed from prompts no model wrote, or a film
whose stills and shots the whole-film path bought from a paid vendor after the staircase
cut-over, fail with a Romanian reason. Nothing here opens a socket or the Owner's database.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.media.models import MediaAsset, Storyboard, StoryboardScene, VideoRenderJob
from app.media.qc import evaluate_media_qc
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def _render(
    engine,
    tmp_path: Path,
    storyboard_id: str,
    production: dict[str, Any],
    *,
    started_at: str | None = None,
) -> str:
    """A finished render of the film, recorded as the renderer records one."""
    path = tmp_path / f"film_{uuid4().hex[:8]}.mp4"
    path.write_bytes(b"\x00" * 4096)
    asset_id, job_id = str(uuid4()), str(uuid4())
    now = started_at or utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name=str((production.get("image") or {}).get("provider") or "test"),
                license_status="ORIGINAL_AI_GENERATED",
                provenance_hash=sha256(path.read_bytes()).hexdigest(),
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json=production,
                started_at=now,
                finished_at=now,
            )
        )
    return asset_id


def _legacy_paid(environment: str = "PRODUCTION") -> dict[str, Any]:
    """The manifest the whole-film path wrote for the Nepal render: stills and a shot bought
    inside the render from Runway (the shape read from that render's own record)."""
    bought = {
        "provider": "RUNWAY_IMAGES",
        "model": "seedream5_pro",
        "images": 1,
        "succeeded": True,
        "estimated_usd": 0.03,
    }
    return {
        "plan": {},
        "image": {"provider": "RUNWAY_IMAGES", "model": "seedream5_pro"},
        "voice": {"provider": "ELEVENLABS"},
        "scenes": [
            {
                "scene_index": 1,
                "image": dict(bought),
                "motion": {"provider": "RUNWAY", "model": "seedance2_5", "asked_seconds": 4.4},
            },
            {"scene_index": 2, "image": dict(bought), "motion": None},
        ],
        "motion": {
            "clips": 1,
            "scenes": 2,
            "environment": environment,
            "run_kind": environment,
            "from_prompt": False,
        },
    }


def _from_takes(environment: str = "PRODUCTION") -> dict[str, Any]:
    """The manifest of a film assembled from its takes on the shooting sheet."""
    return {
        "plan": {},
        "image": {"provider": "SCENE_TAKES", "model": None},
        "voice": {"provider": "ELEVENLABS"},
        "scenes": [
            {"scene_index": 1, "motion": {"reused_take": True}},
            {"scene_index": 2, "motion": {"reused_take": True}},
        ],
        "motion": {"clips": 2, "scenes": 2, "environment": environment, "run_kind": environment},
    }


def _templates(engine, storyboard_id: str) -> None:
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            row.prompt_json = {**dict(row.prompt_json or {}), "source": "template"}


def _check(report: dict[str, Any]) -> dict[str, Any]:
    check: dict[str, Any] = report["checks_json"]["production_path_qc"]
    return check


def test_a_production_film_shot_from_template_prompts_fails_quality_control(engine, tmp_path):
    film = a_film(engine, tmp_path, scenes=2)
    _templates(engine, film)
    asset = _render(engine, tmp_path, film, _from_takes())

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert report["status"] == "FAILED"
    check = _check(report)
    assert check["passed"] is False
    assert check["template_scenes"] == [1, 2]
    reasons = " ".join(report["failure_reasons_json"])
    assert "prompturi-șablon" in reasons and "Scenele 1, 2" in reasons


def test_a_film_the_whole_film_path_bought_from_a_paid_vendor_fails_quality_control(
    engine, tmp_path
):
    film = a_film(engine, tmp_path, scenes=2)
    asset = _render(engine, tmp_path, film, _legacy_paid())

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert report["status"] == "FAILED"
    check = _check(report)
    assert check["passed"] is False and check["legacy_paid"] is True
    assert check["paid_vendors"] == ["RUNWAY", "RUNWAY_IMAGES"]
    reasons = " ".join(report["failure_reasons_json"])
    assert "calea veche" in reasons and "foaia de filmare" in reasons


def test_the_nepal_render_fails_on_both_counts(engine, tmp_path):
    """Template prompts and the whole-film path together, as 3ec1740c was made."""
    film = a_film(engine, tmp_path, scenes=2)
    _templates(engine, film)
    asset = _render(
        engine, tmp_path, film, _legacy_paid(), started_at="2026-09-26T15:16:50.313273+00:00"
    )

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    check = _check(report)
    assert report["status"] == "FAILED"
    assert check["legacy_paid"] is True and check["template_scenes"] == [1, 2]


def test_a_film_assembled_from_its_takes_with_the_models_plan_passes_this_check(engine, tmp_path):
    film = a_film(engine, tmp_path, scenes=2)
    asset = _render(engine, tmp_path, film, _from_takes())

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    check = _check(report)
    assert check["passed"] is True
    assert check["template_scenes"] == [] and check["legacy_paid"] is False
    assert not any("șablon" in reason for reason in report["failure_reasons_json"])
    assert not any("calea veche" in reason for reason in report["failure_reasons_json"])


def test_a_test_film_from_templates_is_not_refused_for_it(engine, tmp_path):
    """Template prompts are a TEST convenience; a TEST film is never refused for them."""
    film = a_film(engine, tmp_path, scenes=2)
    _templates(engine, film)
    asset = _render(engine, tmp_path, film, _from_takes("TEST"))

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert _check(report)["passed"] is True


def test_an_old_render_from_before_the_cut_over_is_not_refused_for_its_path(engine, tmp_path):
    """The films the studio made and published before the staircase are not refused again
    for the path they were made on, should their verdict ever be measured again."""
    film = a_film(engine, tmp_path, scenes=2)
    asset = _render(
        engine, tmp_path, film, _legacy_paid(), started_at="2026-09-12T11:47:24.654661+00:00"
    )

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert _check(report)["legacy_paid"] is False


def test_a_serial_film_composed_from_the_series_look_is_not_refused(engine, tmp_path):
    film = a_film(engine, tmp_path, scenes=2)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film).series_key = "office_serial"
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == film)
        ):
            row.prompt_json = {**dict(row.prompt_json or {}), "source": "series_look"}
    asset = _render(engine, tmp_path, film, _from_takes())

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert _check(report)["template_scenes"] == []
