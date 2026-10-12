"""Approved stays approved: a scene that passed is not judged again while its picture is the same.

2026-10-12, film aa170155 («Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk»): scene 1
was cut from the same still (7a0be480) and the same clip (843617b8) in four films. The one-frame
look passed it at 14:45 and 15:03 (10-11) and at 08:15 UTC, and failed it at 10:35 UTC, unchanged;
the Director's REPAIR then bought a new still and clip for it. Scene 3 the same at 08:15 UTC (18
credits for a new still). That day 19.50 USD of RunPod went out, 11.05 on redos, and the Owner
stopped the studio: «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost aprobată».

What is asserted: the film's one-frame look (`picture_qc.evaluate_pictures`) and its span look
(`qc.span_picture_qc`) do not show the model a scene whose picture is exactly that of an earlier
film of the storyboard whose same check passed it: its entry passes with the report it came from
and «trecută la controlul din …, aceleași preluări»; a scene with a new clip, or one the earlier
check refused, is judged as before.

The review of that change (the same evening) is asserted too: the carry key is the takes AND the
check's version, the bible and look, and the scene's span and speed (`picture_qc.carry_keys`), so
a verdict of another version or another cut is not carried; only the model's look is carried,
while YuNet and the flat band still read a carried scene's frames; what the Director judged FALSE
or accepted as minor on the same takes is not looked at again (`earlier_acceptances`); and a look
that numbered its frames by position is read back to the scenes it was shown, or fails. Every
model is faked.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.media.director_qc import DECISION_EVENT
from app.media.models import MediaAsset, QualityControlReport, VideoRenderJob
from app.media.picture_qc import (
    CARRIED_STATUS,
    earlier_acceptances,
    earlier_passes,
    evaluate_pictures,
    storyboard_carry_keys,
)
from app.services import append_event
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


def _keys(engine, board_id: str, production: dict, check: str) -> dict[int, dict]:
    with Session(engine) as session:
        return storyboard_carry_keys(session, board_id, production, check)


def _picture_checks(
    keys: dict[str, dict[int, dict]], passed: set[int], failed: set[int] = frozenset()
) -> dict[str, Any]:
    """What an earlier film's report said, scene by scene, in both picture checks, with the
    carry key each entry was recorded with (``keys`` per check)."""
    scenes = sorted(set(passed) | set(failed))
    return {
        "picture_qc": {
            "status": "MEASURED",
            "passed": not failed,
            "scenes": [
                scene_answer(index, "as asked", shows_the_scene=index in passed)
                | {"status": "MEASURED", "carry_key": keys["picture_qc"].get(index)}
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
                    "carry_key": keys["picture_spans_qc"].get(index),
                }
                for index in scenes
            ],
        },
    }


def _earlier_film(
    engine,
    ids: dict[str, str],
    takes: dict[int, tuple[str, str | None]],
    passed: set[int],
    failed: set[int] = frozenset(),
    *,
    tamper=None,
) -> dict[str, str]:
    """A film of the same storyboard cut as ``ids``'s film is now, from ``takes``, with one QC
    report whose picture checks passed ``passed`` and refused ``failed``, each entry with the
    carry key it was measured with. ``tamper`` changes those keys (another version, span…)."""
    earlier = {k: str(uuid4()) for k in ("asset", "job", "report")}
    with Session(engine) as session:
        base = session.get(VideoRenderJob, ids["job"]).production_json
    production = _production(takes, base if isinstance(base, dict) else None)
    keys = {
        check: _keys(engine, ids["board"], production, check)
        for check in ("picture_qc", "picture_spans_qc")
    }
    if tamper is not None:
        for check_keys in keys.values():
            for key in check_keys.values():
                tamper(key)
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=earlier["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{earlier['asset']}.mp4",
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
                id=earlier["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=earlier["asset"],
                started_at=EARLIER,
                production_json=production,
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=earlier["report"],
                media_asset_id=earlier["asset"],
                status="FAILED",
                score=0.75,
                checks_json=_picture_checks(keys, passed, failed),
                failure_reasons_json=[],
                verified_at=EARLIER,
            )
        )
    return earlier


SAME = {1: ("still-1", "clip-1"), 2: ("still-2", "clip-2"), 3: ("still-3", "clip-3")}


# ------------------------------------------------------------------ the one-frame look


def test_an_unchanged_scene_that_passed_before_is_not_looked_at_again(engine, frames):
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids, SAME, {1, 2, 3})
    # Scenes 1 and 2 as they were; scene 3 has a new clip.
    _cut_from(engine, ids["job"], {1: SAME[1], 2: SAME[2], 3: ("still-3", "clip-3-new")})
    answer = json.dumps({"scenes": [scene_answer(3, "the planet against its star")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    # One look, at scene 3 alone: its frame is the only one sent, its words the only ones asked,
    # and the look is told which scene the frame is.
    assert len(model.calls) == 1
    assert model.calls[0]["extra"]["images"] == [FRAMES[2]]
    prompt = model.calls[0]["prompt"]
    assert "The planet turning against its star" in prompt
    assert "golden mirror" not in prompt and "water line" not in prompt
    assert "scenes 3, in that order" in prompt
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
    # Every entry keeps the key a later film must match to carry it.
    assert scenes[3]["carry_key"]["clip"] == "clip-3-new"
    assert scenes[3]["carry_key"]["version"] == picture["template_version"]


def test_a_film_whose_every_scene_passed_before_is_not_looked_at_at_all(engine, frames):
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids, SAME, {1, 2, 3})
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
    _earlier_film(engine, ids, SAME, {1, 2}, failed={3})
    # Scene 2: a new still (its clip id kept); scene 3: refused before, unchanged.
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("still-2-new", "clip-2"), 3: SAME[3]})
    answer = json.dumps({"scenes": [scene_answer(2, "ok"), scene_answer(3, "ok")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert model.calls[0]["extra"]["images"] == FRAMES[1:]
    statuses = {entry["scene"]: entry["status"] for entry in result["picture_qc"]["scenes"]}
    assert statuses == {1: CARRIED_STATUS, 2: "MEASURED", 3: "MEASURED"}


@pytest.mark.parametrize(
    "tamper",
    [
        # The look's version changed since: its questions are not the ones answered then.
        lambda key: key.update(version="picture-qc-v1"),
        # The scene sat elsewhere in the film, or was slowed: another picture on screen.
        lambda key: key.update(start=(key["start"] or 0.0) + 0.5),
        lambda key: key.update(speed=1.2),
        # The bible or the scene's look changed: the picture is judged against other rules.
        lambda key: key.update(look="0" * 16),
        # Recorded before the key existed (until 2026-10-12): it carries nothing.
        lambda key: key.clear(),
    ],
    ids=["version", "span", "speed", "bible", "no-key"],
)
def test_a_verdict_of_another_version_or_cut_is_not_carried(engine, frames, tamper):
    """The review of 2026-10-12: the carry was keyed by the takes alone."""
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids, SAME, {1, 2, 3}, tamper=tamper)
    _cut_from(engine, ids["job"], SAME)
    answer = json.dumps({"scenes": [scene_answer(n, "ok") for n in (1, 2, 3)]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert model.calls[0]["extra"]["images"] == FRAMES
    assert result["picture_qc"]["scenes_carried"] == 0


def test_only_a_measured_or_carried_pass_carries_and_never_the_report_being_read(engine):
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids, SAME, {1, 2}, failed={3})
    _cut_from(engine, ids["job"], SAME)
    with Session(engine) as session:
        production = session.get(VideoRenderJob, ids["job"]).production_json
        keys = storyboard_carry_keys(session, ids["board"], production, "picture_spans_qc")
        spans = earlier_passes(session, ids["board"], keys, "picture_spans_qc")
        looks = earlier_passes(
            session,
            ids["board"],
            storyboard_carry_keys(session, ids["board"], production, "picture_qc"),
            "picture_qc",
        )
        none_before = earlier_passes(
            session, ids["board"], keys, "picture_spans_qc", before="2026-10-11T00:00:00+00:00"
        )
        excluded = earlier_passes(
            session, ids["board"], keys, "picture_spans_qc", exclude_report_ids=[earlier["report"]]
        )
    assert sorted(spans) == [1, 2] and sorted(looks) == [1, 2]
    assert spans[1].report_id == earlier["report"] and spans[1].clip_take == "clip-1"
    assert none_before == {} and excluded == {}


# ------------------------------------------------------ what the Director settled stays settled


def _her_verdicts(
    engine,
    ids: dict[str, str],
    report_id: str,
    verdicts: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    **done: Any,
) -> None:
    """Her decision on an earlier report: ``verdicts`` as recorded, ``done`` (her second looks'
    ``overturned``) beside them; a decision of its own unless ``run_id`` names one already
    recorded (a REPAIR carried on writes its decision again)."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            report_id,
            1,
            {
                "report_id": report_id,
                "storyboard_id": ids["board"],
                "decided_by": "Director",
                "decision": "ACCEPT",
                "run_id": run_id or str(uuid4()),
                "verdicts": verdicts,
                **({"done": done} if done else {}),
            },
            str(uuid4()),
        )


def _now_keys(engine, ids: dict[str, str], check: str) -> dict[int, dict]:
    """Each scene's carry key in ``ids``'s film as it is cut now, for ``check``."""
    with Session(engine) as session:
        production = session.get(VideoRenderJob, ids["job"]).production_json
    return _keys(engine, ids["board"], production, check)


def test_a_scene_she_settled_on_the_same_takes_is_not_looked_at_again(engine, frames):
    """The review of 2026-10-12: a scene she ACCEPTED was judged again and could turn REAL,
    and a REPAIR followed. FALSE, or ACCEPTED as minor, on exactly these takes stays so."""
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids, SAME, {1}, failed={2, 3})
    _cut_from(engine, ids["job"], SAME)
    # Round 3 of the review: her verdict carries the picture's carry key, and settles only it.
    keys = _now_keys(engine, ids, "picture_qc")
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        [
            # Scene 2: a small light drift she accepted.
            {
                "finding": 1,
                "verdict": "ACCEPTED",
                "severity": "minor",
                "check": "picture_qc",
                "scene_index": 2,
                "reason": "a little lighter than asked",
                "carry_key": keys[2],
            },
            # Scene 3: accepted with a serious defect, from before the severities: settles
            # nothing, it is judged again.
            {
                "finding": 2,
                "verdict": "ACCEPTED",
                "check": "picture_qc",
                "scene_index": 3,
                "reason": "the wrong object",
                "carry_key": keys[3],
            },
        ],
    )
    answer = json.dumps({"scenes": [scene_answer(3, "ok")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert model.calls[0]["extra"]["images"] == [FRAMES[2]]
    scenes = {entry["scene"]: entry for entry in result["picture_qc"]["scenes"]}
    assert scenes[1]["carried_from"]["kind"] == "passed"
    assert scenes[2]["carried_from"]["kind"] == "accepted"
    assert scenes[2]["reason"].startswith("acceptată de Directoare la")
    assert scenes[3]["status"] == "MEASURED"

    # Her newer word on the same takes decides: REAL on scene 2 unsettles it.
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        [{"finding": 1, "verdict": "REAL", "severity": "serious", "check": "picture_qc",
          "scene_index": 2, "reason": "seen again: wrong", "carry_key": keys[2]}],
    )  # fmt: skip
    with Session(engine) as session:
        production = session.get(VideoRenderJob, ids["job"]).production_json
        assert earlier_acceptances(session, ids["board"], production, "picture_qc") == {}
    # Her second look that overturned a refusal settles the checks it named, on the picture
    # whose carry key it recorded; one recorded without a key settles nothing.
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        [],
        overturned=[{"scene_index": 2, "checks": ["picture_qc"], "reason": "no key"}],
    )
    with Session(engine) as session:
        assert earlier_acceptances(session, ids["board"], production, "picture_qc") == {}
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        [],
        overturned=[
            {
                "scene_index": 2,
                "checks": ["picture_qc"],
                "reason": "the refusal is wrong",
                "carry_keys": {"picture_qc": keys[2]},
            }
        ],
    )
    with Session(engine) as session:
        settled = earlier_acceptances(session, ids["board"], production, "picture_qc")
        spans = earlier_acceptances(session, ids["board"], production, "picture_spans_qc")
    assert settled[2].verdicts == ("OVERTURNED",) and spans == {}


def test_her_overturn_survives_her_repair_written_again_and_settles_any_check(engine):
    """Round 3 of the 2026-10-12 review: a REPAIR carried on writes its decision again, with its
    REAL verdicts and without the earlier overturn, and the overturn was lost; an overturned
    Motion QC or unattributed finding was settled by nothing, and the film looped every hour.
    The events of one decision (one report, one run) are read together, an overturn wins over
    its REAL verdicts, and it settles every check it names on exactly its picture."""
    ids = a_film(engine)
    earlier = _earlier_film(engine, ids, SAME, {1}, failed={2, 3})
    _cut_from(engine, ids["job"], SAME)
    pictures = _now_keys(engine, ids, "picture_qc")
    motion = _now_keys(engine, ids, "motion_qc")
    real = [
        {"finding": 1, "verdict": "REAL", "severity": "serious", "check": "picture_qc",
         "scene_index": 2, "reason": "a lamp", "carry_key": pictures[2]},
        {"finding": 2, "verdict": "REAL", "severity": "serious", "check": "motion_qc",
         "scene_index": 3, "reason": "frozen", "carry_key": motion[3]},
    ]  # fmt: skip
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        real,
        run_id="her-run",
        overturned=[
            {"scene_index": 2, "checks": ["picture_qc"], "reason": "a lamp is asked",
             "carry_keys": {"picture_qc": pictures[2]}},
            {"scene_index": 3, "checks": ["motion_qc"], "reason": "it moves",
             "carry_keys": {"motion_qc": motion[3]}},
        ],
    )  # fmt: skip
    # Carried on: the same decision written again, its REAL verdicts and nothing overturned.
    _her_verdicts(engine, ids, earlier["report"], real, run_id="her-run")
    with Session(engine) as session:
        production = session.get(VideoRenderJob, ids["job"]).production_json
        looks = earlier_acceptances(session, ids["board"], production, "picture_qc")
        moves = earlier_acceptances(session, ids["board"], production, "motion_qc")
    assert looks[2].verdicts == ("OVERTURNED",) and sorted(looks) == [2]
    assert moves[3].verdicts == ("OVERTURNED",) and sorted(moves) == [3]
    # Her FALSE on a Motion QC finding is not a look: only her second look settles it.
    _her_verdicts(
        engine,
        ids,
        earlier["report"],
        [{"finding": 1, "verdict": "FALSE", "check": "motion_qc", "scene_index": 1,
          "reason": "x", "carry_key": motion[1]}],
    )  # fmt: skip
    with Session(engine) as session:
        moves = earlier_acceptances(session, ids["board"], production, "motion_qc")
    assert sorted(moves) == [3]


# --------------------------------------------- the look told which scenes its frames are


def test_a_look_that_numbers_its_frames_by_position_is_read_back_to_the_scenes(engine, frames):
    """Scene 1 carried, scenes 2 and 3 shown: the look answered «1» and «2» for its two frames
    (2026-10-12 review: until then the shown scenes were left unjudged and the check certified
    nothing, silently)."""
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids, SAME, {1})
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("s2", "c2"), 3: ("s3", "c3")})
    answer = json.dumps(
        {"scenes": [scene_answer(1, "ok"), scene_answer(2, "a lamp", shows_the_scene=False)]}
    )
    registry, _model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    picture = result["picture_qc"]
    assert picture["renumbered"] == {"1": 2, "2": 3}
    scenes = {entry["scene"]: entry for entry in picture["scenes"]}
    assert scenes[2]["status"] == "MEASURED" and scenes[3]["shows_the_scene"] is False
    assert picture["passed"] is False
    assert result["failures"] == ["Scene 3: the picture is not what the scene asked for — a lamp"]


def test_a_look_that_answers_about_scenes_it_was_not_shown_is_asked_again(engine, frames):
    """Round 3 of the 2026-10-12 review: such a look failed the film with a «picture finding»,
    which buys a redo. It is asked once more, free, with the scene numbers stated; still about
    scenes it was not shown, the scenes are NOT_RUN: no finding, nothing to buy, no pass."""
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _earlier_film(engine, ids, SAME, {1})
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("s2", "c2"), 3: ("s3", "c3")})
    # Two frames shown, one answer, about a scene it was not shown: nothing can be read back.
    answer = json.dumps({"scenes": [scene_answer(1, "ok")]})
    registry, model = registry_with(staffed, lambda prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert len(model.calls) == 2
    assert "gave no verdict for scenes 2, 3" in model.calls[1]["prompt"]
    assert "It answered about scenes 1, which were not shown" in model.calls[1]["prompt"]
    picture = result["picture_qc"]
    assert result["failures"] == [] and picture["passed"] is None
    scenes = {entry["scene"]: entry for entry in picture["scenes"]}
    assert scenes[2]["status"] == scenes[3]["status"] == "NOT_RUN"
    assert "even when asked again" in scenes[2]["reason"]
    assert picture["asked_again"]["scenes"] == [2, 3]


def test_a_shown_scene_the_look_left_out_is_asked_again_and_judged(engine, frames):
    """Round 3 of the review: a scene the look's answer left out passed the check unseen."""
    staffed = staff(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    ids = a_film(engine)
    _cut_from(engine, ids["job"], {1: ("s1", "c1"), 2: ("s2", "c2"), 3: ("s3", "c3")})
    answers = iter(
        [
            json.dumps({"scenes": [scene_answer(1, "ok"), scene_answer(2, "ok")]}),
            json.dumps({"scenes": [scene_answer(3, "a lamp", shows_the_scene=False)]}),
        ]
    )
    registry, model = registry_with(staffed, lambda prompt: next(answers))

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert len(model.calls) == 2 and "gave no verdict for scenes 3" in model.calls[1]["prompt"]
    picture = result["picture_qc"]
    scenes = {entry["scene"]: entry for entry in picture["scenes"]}
    assert scenes[3]["status"] == "MEASURED" and scenes[3]["shows_the_scene"] is False
    assert picture["passed"] is False
    assert result["failures"] == ["Scene 3: the picture is not what the scene asked for — a lamp"]


# --------------------------------------------------------------------------- the span look


@requires_ffmpeg
def test_the_span_look_keeps_its_verdict_and_still_reads_faces_and_the_band(engine, tmp_path):
    """No judge is asked for a scene whose picture passed before; its three frames are still
    cut, YuNet still counts their faces and the band still reads them (the review of 2026-10-12:
    both free detectors were skipped on a carried scene)."""
    from app.media.qc import span_picture_qc

    staff(engine)
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE, film=_span_film(tmp_path))
    takes = {1: SAME[1], 2: SAME[2]}
    _cut_from(engine, ids["job"], takes)
    earlier = _earlier_film(engine, ids, takes, {1, 2})
    judge, faces = _Judge(), _Faces()

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert judge.calls == [], "the look is carried"
    assert len(faces.seen) == 6, "YuNet counted the three frames of both carried scenes"
    assert record["passed"] is True and record["failures"] == []
    assert record["status"] == "MEASURED" and record["carried_scenes"] == [1, 2]
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    for index in (1, 2):
        assert scenes[index]["status"] == "PASSED" and scenes[index]["passed"] is True
        assert scenes[index]["carried_from"]["report_id"] == earlier["report"]
        assert scenes[index]["picture"]["status"] == CARRIED_STATUS
        assert scenes[index]["panels"]["status"] == "PASSED"
        assert scenes[index]["faces"]["status"] == "PASSED"
        assert scenes[index]["carry_key"]["clip"] == f"clip-{index}"
    assert scenes[3]["status"] == "NOT_APPLICABLE"
    assert "aceleași preluări" in record["detail"]


@requires_ffmpeg
def test_a_face_yunet_counts_fails_a_carried_scene(engine, tmp_path):
    from app.media.qc import span_picture_qc

    staff(engine)
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE, film=_span_film(tmp_path))
    takes = {1: SAME[1], 2: SAME[2]}
    _cut_from(engine, ids["job"], takes)
    _earlier_film(engine, ids, takes, {1, 2})
    judge, faces = _Judge(), _Faces(faces={"scene_01_middle": 1})

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert judge.calls == []
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["passed"] is False and "YuNet a găsit fețe" in scenes[1]["reason"]
    assert record["passed"] is False


@requires_ffmpeg
def test_the_span_look_judges_a_scene_with_a_new_clip(engine, tmp_path):
    from app.media.qc import span_picture_qc

    staff(engine)
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE, film=_span_film(tmp_path))
    _earlier_film(engine, ids, {1: SAME[1], 2: SAME[2]}, {1, 2})
    _cut_from(engine, ids["job"], {1: SAME[1], 2: ("still-2", "clip-2-new")})
    judge, faces = _Judge(), _Faces()

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert [scene for scene, _widths in judge.calls] == [2]
    assert len(faces.seen) == 6, "every filmed scene's three frames are counted"
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["carried_from"] is not None and scenes[1]["passed"] is True
    assert "carried_from" not in scenes[2] and scenes[2]["status"] == "PASSED"
    assert record["status"] == "MEASURED" and record["passed"] is True
    assert record["carried_scenes"] == [1]
