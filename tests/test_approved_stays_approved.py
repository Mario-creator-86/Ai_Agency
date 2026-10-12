"""Approved stays approved: a scene that passed is not judged again while its takes are the same.

2026-10-12, film aa170155 («Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk»): scene 1
was cut from the same still (7a0be480) and the same clip (843617b8) in four films. The one-frame
look passed it at 14:45 and 15:03 (10-11) and at 08:15 UTC, and failed it at 10:35 UTC, unchanged;
the Director's REPAIR then bought a new still and clip for it. Scene 3 the same at 08:15 UTC (18
credits for a new still). That day 19.50 USD of RunPod went out, 11.05 on redos, and the Owner
stopped the studio: «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost aprobată».

What is asserted: the film's one-frame look (`picture_qc.evaluate_pictures`) and its span look
(`qc.span_picture_qc`) do not judge a scene whose still take and clip take are those of an earlier
film of the storyboard whose same check passed it: the judge is not called for it, its entry
passes with the report it came from and «trecută la controlul din …, aceleași preluări»; a scene
with a new clip, or one the earlier check refused, is judged as before. Every model is faked.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.media.models import MediaAsset, QualityControlReport, VideoRenderJob
from app.media.picture_qc import CARRIED_STATUS, earlier_passes, evaluate_pictures
from sqlalchemy.orm import Session
from test_picture_qc import (
    FRAMES,
    NO_FACES_BIBLE,
    _Faces,
    _Judge,
    _span_film,
    _spanned_film,
    a_film,
    give_vision,
    registry_with,
    requires_ffmpeg,
    scene_answer,
    staff,
)

EARLIER = "2026-10-11T14:45:40.130140+00:00"


@pytest.fixture
def frames(monkeypatch):
    """The encoder, faked: one frame per scene of the film, counted."""
    asked: list[list[float]] = []

    def frames_for(path, ffmpeg_path, duration, scene_seconds=None):
        asked.append(list(scene_seconds or []))
        return list(FRAMES)

    monkeypatch.setattr("app.media.picture_qc.frames_for", frames_for)
    return asked


def _production(takes: dict[int, tuple[str, str | None]], base: dict | None = None) -> dict:
    """The render's record of which still and clip each scene was cut from."""
    production = dict(base or {})
    recorded = {
        int(entry["scene_index"]): dict(entry)
        for entry in production.get("scenes") or []
        if isinstance(entry, dict)
    }
    for index, (still, clip) in takes.items():
        entry = recorded.setdefault(index, {"scene_index": index, "scene_kind": "LIVE"})
        entry["still_take"] = {"take_id": still, "status": "APPROVED"}
        entry["motion"] = {"take_id": clip, "take_status": "PAID"} if clip else None
    production["scenes"] = [recorded[index] for index in sorted(recorded)]
    return production


def _cut_from(engine, job_id: str, takes: dict[int, tuple[str, str | None]]) -> None:
    with Session(engine) as session, session.begin():
        job = session.get(VideoRenderJob, job_id)
        job.production_json = _production(takes, job.production_json)


def _picture_checks(passed: set[int], failed: set[int] = frozenset()) -> dict[str, Any]:
    """What an earlier film's report said, scene by scene, in both picture checks."""
    scenes = sorted(set(passed) | set(failed))
    return {
        "picture_qc": {
            "status": "MEASURED",
            "passed": not failed,
            "scenes": [
                scene_answer(index, "as asked", shows_the_scene=index in passed)
                | {"status": "MEASURED"}
                for index in scenes
            ],
        },
        "character_drift_qc": {"status": "NOT_IMPLEMENTED", "passed": None, "characters": []},
        "picture_spans_qc": {
            "status": "MEASURED",
            "passed": not failed,
            "scenes": [
                {
                    "scene_index": index,
                    "kind": "LIVE",
                    "status": "PASSED" if index in passed else "FAILED",
                    "passed": index in passed,
                }
                for index in scenes
            ],
        },
    }


def _earlier_film(
    engine,
    board_id: str,
    takes: dict[int, tuple[str, str | None]],
    checks: dict[str, Any],
) -> dict[str, str]:
    """A film of the same storyboard, cut from ``takes``, with one QC report of ``checks``."""
    ids = {k: str(uuid4()) for k in ("asset", "job", "report")}
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=18.0,
                provider_name="SCENE_TAKES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="1" * 64,
                created_at=EARLIER,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=board_id,
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=EARLIER,
                production_json=_production(takes),
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=ids["report"],
                media_asset_id=ids["asset"],
                status="FAILED",
                score=0.75,
                checks_json=checks,
                failure_reasons_json=[],
                verified_at=EARLIER,
            )
        )
    return ids


SAME = {1: ("still-1", "clip-1"), 2: ("still-2", "clip-2"), 3: ("still-3", "clip-3")}


# ------------------------------------------------------------------ the one-frame look


def test_an_unchanged_scene_that_passed_before_is_not_looked_at_again(engine, frames):
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids["board"], SAME, _picture_checks({1, 2, 3}))
    # Scenes 1 and 2 as they were; scene 3 has a new clip.
    _cut_from(engine, ids["job"], {1: SAME[1], 2: SAME[2], 3: ("still-3", "clip-3-new")})
    answer = json.dumps({"scenes": [scene_answer(3, "the planet against its star")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    # One look, at scene 3 alone: its frame is the only one sent, its words the only ones asked.
    assert len(model.calls) == 1
    assert model.calls[0]["extra"]["images"] == [FRAMES[2]]
    prompt = model.calls[0]["prompt"]
    assert "The planet turning against its star" in prompt
    assert "golden mirror" not in prompt and "water line" not in prompt
    picture = result["picture_qc"]
    assert picture["passed"] is True and result["failures"] == []
    assert picture["frames"] == 1 and picture["scenes_carried"] == 2
    scenes = {entry["scene"]: entry for entry in picture["scenes"]}
    assert [entry["scene"] for entry in picture["scenes"]] == [1, 2, 3]
    for index in (1, 2):
        assert scenes[index]["status"] == CARRIED_STATUS
        assert scenes[index]["shows_the_scene"] is True
        assert scenes[index]["carried_from"]["report_id"] == earlier["report"]
        assert scenes[index]["carried_from"]["still_take"] == f"still-{index}"
        assert scenes[index]["reason"] == (
            "trecută la controlul din 2026-10-11 14:45 UTC, aceleași preluări"
        )
    assert scenes[3]["status"] == "MEASURED"


def test_a_film_whose_every_scene_passed_before_is_not_looked_at_at_all(engine, frames):
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids["board"], SAME, _picture_checks({1, 2, 3}))
    _cut_from(engine, ids["job"], SAME)

    def looked_again(prompt):
        pytest.fail("a scene that passed with the same takes was looked at again")

    registry, model = registry_with(staffed, looked_again)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert model.calls == [] and frames == [], "nothing was cut, nobody was asked"
    picture = result["picture_qc"]
    assert picture["status"] == CARRIED_STATUS and picture["passed"] is True
    assert picture["model_used"] is False and picture["scenes_carried"] == 3
    assert result["failures"] == []


def test_a_scene_the_earlier_look_refused_or_a_new_still_is_judged_again(engine, frames):
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids["board"], SAME, _picture_checks({1, 2}, failed={3}))
    # Scene 2: a new still (its clip id kept); scene 3: refused before, unchanged.
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("still-2-new", "clip-2"), 3: SAME[3]})
    answer = json.dumps({"scenes": [scene_answer(2, "ok"), scene_answer(3, "ok")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert model.calls[0]["extra"]["images"] == FRAMES[1:]
    statuses = {entry["scene"]: entry["status"] for entry in result["picture_qc"]["scenes"]}
    assert statuses == {1: CARRIED_STATUS, 2: "MEASURED", 3: "MEASURED"}


def test_only_a_measured_or_carried_pass_carries_and_never_the_report_being_read(engine):
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids["board"], SAME, _picture_checks({1, 2}, failed={3}))
    production = _production(SAME)
    with Session(engine) as session:
        spans = earlier_passes(session, ids["board"], production, "picture_spans_qc")
        both = earlier_passes(session, ids["board"], production, None)
        none_before = earlier_passes(
            session, ids["board"], production, None, before="2026-10-11T00:00:00+00:00"
        )
        excluded = earlier_passes(
            session, ids["board"], production, None, exclude_report_ids=[earlier["report"]]
        )
    assert sorted(spans) == [1, 2] and sorted(both) == [1, 2]
    assert spans[1].report_id == earlier["report"] and spans[1].clip_take == "clip-1"
    assert none_before == {} and excluded == {}


# --------------------------------------------------------------------------- the span look


def test_the_span_look_keeps_every_scene_that_passed_with_the_same_takes(engine, tmp_path):
    """No frame is cut and no judge is asked when every filmed scene passed before: the file
    on disk is not even a film."""
    from app.media.qc import span_picture_qc

    staff(engine)
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not a film: nothing is cut from it")
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE, film=film)
    takes = {1: SAME[1], 2: SAME[2]}
    _cut_from(engine, ids["job"], takes)
    earlier = _earlier_film(engine, ids["board"], takes, _picture_checks({1, 2}))
    judge, faces = _Judge(), _Faces()

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert judge.calls == [] and faces.seen == []
    assert record["passed"] is True and record["failures"] == []
    assert record["status"] == CARRIED_STATUS and record["carried_scenes"] == [1, 2]
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    for index in (1, 2):
        assert scenes[index]["status"] == "PASSED" and scenes[index]["passed"] is True
        assert scenes[index]["carried_from"]["report_id"] == earlier["report"]
        assert "aceleași preluări" in scenes[index]["reason"]
        assert scenes[index]["picture"]["status"] == CARRIED_STATUS
    assert scenes[3]["status"] == "NOT_APPLICABLE"
    assert "aceleași preluări" in record["detail"]


@requires_ffmpeg
def test_the_span_look_judges_a_scene_with_a_new_clip(engine, tmp_path):
    from app.media.qc import span_picture_qc

    staff(engine)
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE, film=_span_film(tmp_path))
    _earlier_film(engine, ids["board"], {1: SAME[1], 2: SAME[2]}, _picture_checks({1, 2}))
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("still-2", "clip-2-new")})
    judge, faces = _Judge(), _Faces()

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert [scene for scene, _widths in judge.calls] == [2]
    assert len(faces.seen) == 3, "only the new clip's three frames are counted"
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["carried_from"] is not None and scenes[1]["passed"] is True
    assert "carried_from" not in scenes[2] and scenes[2]["status"] == "PASSED"
    assert record["status"] == "MEASURED" and record["passed"] is True
    assert record["carried_scenes"] == [1]
