"""Live scene-4 defects must be repaired before a purchase can reuse an approval."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from app.media import director_qc, prompt_agent, prompt_lint
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, still_fields, take_hash
from app.media.models import SceneTake, StoryboardScene
from app.media.scene_rewrite import DECIDED_BY, REWRITE_REASON
from app.media.series_look import load_series_look
from app.runbook import stages
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import (
    DECISION_EVENT,
    REPAIR_5,
    FakeRedoPath,
    _gpu_forced_off,
    _panels_on_disk,
    answer,
    director_says,
    events,
    failed_film,
    studio,  # noqa: F401 - pytest fixture
    verdicts_for,
)


def recorded_package():
    return json.loads(
        (Path(__file__).parent / "fixtures/live_serial_scene4_2026-10-14.json").read_text(
            encoding="utf-8"
        )
    )["package"]


def whole_package():
    package = deepcopy(recorded_package())
    package["background"] = "The ledger, calculator and pencils remain behind Nadia."
    package["continuity"] = (
        "Sarah's shoulder at the right frame edge wears a crisp navy two-piece executive "
        "blazer, white collared shirt, and sky-blue tie."
    )
    package["still_prompt"] = prompt_agent.compose_serial_prompt(package, load_series_look())
    return package


def test_live_legacy_fields_cannot_pass_before_the_gpu_purchase():
    package = recorded_package()
    prompt = prompt_agent.compose_serial_prompt(package, load_series_look())
    issues = prompt_agent.composition_issues(package, prompt, "", layers=("still",))
    assert any("background" in issue and "incomplet" in issue for issue in issues)
    assert any("continuity" in issue and "sky-blue tie" in issue for issue in issues)
    findings = prompt_lint.lint_scene(
        prompt_lint.LintScene(
            4,
            still_prompt=prompt,
            composition_issues=tuple(issues),
            contract={"still_model_id": "Qwen-Image-2512"},
        )
    )
    with pytest.raises(prompt_lint.PromptLintBlocked):
        prompt_lint.require_no_block(findings)
    assert prompt.endswith("sky-blue.")  # No guessed repair or silent text deletion.


def test_complete_repair_keeps_the_wardrobe_and_partial_person():
    package = whole_package()
    assert not prompt_agent.composition_issues(
        package, package["still_prompt"], "", layers=("still",)
    )
    assert "plum blouse under a dark violet cardigan" in package["still_prompt"]
    assert "Sarah's right shoulder and upper arm" in package["still_prompt"]
    assert "sky-blue tie" in package["still_prompt"]


def test_valid_adverb_particle_is_not_an_incomplete_sentence():
    package = whole_package()
    package["background"] = "Clouds drift by. The desk lamp stays switched on."
    prompt = prompt_agent.compose_serial_prompt(package, load_series_look())
    assert not prompt_agent.composition_issues(package, prompt, "", layers=("still",))


def test_motion_only_review_does_not_rewrite_an_existing_accepted_picture():
    package = recorded_package()
    issues = prompt_agent.composition_issues(
        package, package["still_prompt"], package["motion_prompt"], layers=("motion",)
    )
    assert not any("background" in issue or "continuity" in issue for issue in issues)


def correction_event(engine, film, package, *, reviewed_prompt=None):
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"],
                StoryboardScene.scene_index == 5,
            )
        )
        row.prompt_json = package
        row.visual_prompt = package["still_prompt"]
        return append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            film["board"],
            1,
            {
                "scene_index": 5,
                "decided_by": DECIDED_BY,
                "reason": REWRITE_REASON,
                "layer": "still",
                "still_prompt": reviewed_prompt or package["still_prompt"],
                "motion_prompt": package.get("motion_prompt", ""),
                "review": {"verdict": "TREATS"},
            },
            str(uuid4()),
        ).event_id


def test_old_treats_approval_cannot_authorize_incomplete_stored_fields(engine):
    film = failed_film(engine)
    package = recorded_package()
    correction_event(engine, film, package)
    with Session(engine) as session:
        assert stages._corrected_for_film(session, film["board"], 5, film["asset"]) is None


def test_approval_must_match_the_words_that_will_be_sent(engine):
    film = failed_film(engine)
    correction_event(engine, film, whole_package(), reviewed_prompt="A different room.")
    with Session(engine) as session:
        assert stages._corrected_for_film(session, film["board"], 5, film["asset"]) is None


def test_complete_current_words_retain_the_existing_approval(engine):
    film = failed_film(engine)
    event_id = correction_event(engine, film, whole_package())
    with Session(engine) as session:
        assert stages._corrected_for_film(session, film["board"], 5, film["asset"]) == {
            "layer": "still",
            "event_id": str(event_id),
        }


@pytest.mark.parametrize("matches", [False, True])
def test_replacement_offer_requires_current_prompt_and_verified_picture(engine, tmp_path, matches):
    film = failed_film(engine)
    data = b"already delivered approved picture"
    path = tmp_path / "picture.png"
    path.write_bytes(data)
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"],
                StoryboardScene.scene_index == 5,
            )
        )
        scene.visual_prompt = "A revised picture with the required wardrobe."
        scene.character_ids_json = []
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=film["board"],
                scene_number=5,
                kind="still",
                model_id="Qwen-Image-2512",
                resolution="2K",
                prompt_hash=take_hash(
                    still_fields(scene.visual_prompt if matches else "An old picture.", None),
                    "Qwen-Image-2512",
                ),
                status="APPROVED",
                path=str(path),
                sha256=hashlib.sha256(data).hexdigest(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        append_event(
            session,
            DECISION_EVENT,
            "qc_report",
            film["report"],
            1,
            {
                "storyboard_id": film["board"],
                "started_at": "2020-01-01T00:00:00+00:00",
                "bought_so_far": [["still", 5]],
            },
            str(uuid4()),
        )
    with Session(engine) as session:
        offers = director_qc.bought_not_in_film(session, film["board"])
        assert [item["take_id"] for item in offers] == ([take_id] if matches else [])
        assert stages._still_newer_than_film(session, film["board"], 5, film["asset"]) is matches


def test_terminal_no_picture_redo_is_not_a_purchase_or_a_wait(
    engine,
    settings,
    studio,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
):
    film = failed_film(engine)
    panels = _panels_on_disk(engine, film, tmp_path)
    registry, _ = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch, verdict="FAILED")
    monkeypatch.setattr(
        "app.media.assembler.redo_scene", _gpu_forced_off(redo, panels, raise_after=False)
    )
    result = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert result["outcome"] == "NOTHING_DONE"
    decided = events(engine, DECISION_EVENT)[-1].payload
    assert decided["bought_so_far"] == []
    assert decided["done"]["bought"] == []
    assert decided["done"]["waiting"] == []
    assert decided["done"]["refused"]
    assert events(engine, "runbook.qc_paid_redo") == []


def test_purchase_plan_blocks_the_recorded_broken_fields(engine):
    from app.media.assembler import SceneRedoRefused, redo_plan
    from app.media.models import Storyboard

    film = failed_film(engine)
    correction_event(engine, film, recorded_package())
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film["board"]).series_key = "office_serial"
    with pytest.raises(SceneRedoRefused, match="background") as refused:
        redo_plan(engine, film["board"], "still", 5, stills_model="seedream5_pro")
    assert refused.value.status == "LINT_BLOCKED"


def test_initial_still_loader_exposes_the_same_integrity_blocks(engine):
    from app.media.stills_stage import _read_scenes

    film = failed_film(engine)
    correction_event(engine, film, recorded_package())
    _bible, scenes = _read_scenes(engine, film["board"])
    target = next(item for item in scenes if item.index == 5)
    assert any("background" in issue for issue in target.prompt_issues)
    assert any("sky-blue tie" in issue for issue in target.prompt_issues)


def test_the_rewrite_receives_every_broken_saved_field(engine, monkeypatch):
    from app.media import scene_rewrite

    film = failed_film(engine)
    correction_event(engine, film, recorded_package())
    captured = []

    def rewrite(*args):
        captured.extend(args[-2])
        return {"rewritten": False, "rewritable": True, "reason": "model unavailable"}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", rewrite)
    stages._correct_before_redo(
        engine, None, film["board"], 5, ["still"], [], {"findings": []}, str(uuid4())
    )
    assert any("background" in reason for reason in captured)
    assert any("continuity" in reason and "sky-blue tie" in reason for reason in captured)


def test_factual_rewrite_does_not_reintroduce_the_old_field_size_limit(monkeypatch):
    from app.agents.identity import complete_schema
    from app.media import scene_rewrite

    action = ("The scientist holds the sealed vessel at the desk. " * 25).strip()
    shot = complete_schema(prompt_agent.ShotPrompt).model_validate(
        {"scene_index": 1, "action": action}
    )
    captured = []

    def validate(shot, *args):
        captured.append(shot.action)
        return shot.model_dump(), []

    monkeypatch.setattr(prompt_agent, "_validated_package", validate)
    monkeypatch.setattr(prompt_agent, "compile_prompts", lambda *a, **k: {})
    context = {
        "package": {},
        "scene_index": 1,
        "scene": {},
        "bible": {},
        "allowed": [],
        "previous_ending": "",
        "shot_type": "medium",
        "previous_moves": [],
    }
    scene_rewrite.rewritten_package(context, shot, "still", {})
    assert captured == [action]


def test_subject_orientation_to_camera_is_kept_as_one_complete_motion_condition():
    condition = "The researcher remains seen from behind throughout, with his back to the camera"
    assert prompt_agent._clauses_of(condition, motion=True) == [condition]
    assert prompt_agent._clauses_of("The camera zooms toward the desk", motion=True) == []


@pytest.mark.parametrize("kind,delivered", [("still", False), ("motion", False), ("still", True)])
def test_returned_old_takes_distinguish_no_delivery_from_rejected_picture(
    engine,
    settings,
    studio,  # noqa: F811 - imported pytest fixture
    monkeypatch,
    tmp_path,
    kind,
    delivered,  # noqa: F811
):
    film = failed_film(engine, local_move=False)
    repair = [{"scene_index": 5, "redo": kind, "reason": "The scene failed quality control."}]
    registry, _ = director_says(studio, answer(verdicts_for(film), "REPAIR", repair))
    FakeRedoPath(engine, monkeypatch, verdict="FAILED")

    def attempted(*args, **kwargs):
        if delivered:
            data = b"delivered picture refused by visual QC"
            path = tmp_path / "rejected.png"
            path.write_bytes(data)
            with Session(engine) as session, session.begin():
                session.add(
                    SceneTake(
                        id=str(uuid4()),
                        storyboard_id=film["board"],
                        scene_number=5,
                        kind=kind,
                        model_id="Qwen-Image-2512",
                        resolution="2K",
                        prompt_hash=uuid4().hex,
                        status="REJECTED",
                        path=str(path),
                        sha256=hashlib.sha256(data).hexdigest(),
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                )
        return {
            "still": {"status": "NEEDS_OWNER" if delivered else "NOT_BOUGHT"},
            "motion": {"bought_shots": 1},
            "credits": 28,
            "given_back": {"restored": [film["takes"][5]["still"]]},
        }

    monkeypatch.setattr("app.media.assembler.redo_scene", attempted)
    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    decision = events(engine, DECISION_EVENT)[-1].payload
    assert bool(decision["done"]["bought"]) is delivered
    assert bool(decision["done"]["waiting"]) is delivered
    assert outcome["outcome"] == ("BOUGHT_WAITING" if delivered else "NOTHING_DONE")
