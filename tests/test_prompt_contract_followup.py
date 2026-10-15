"""Recorded prompt defects and full repair evidence, without any provider calls."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.media import prompt_agent as words
from app.media import scene_rewrite as repair
from app.media.series_look import load_series_look


def recorded(kind: str, scene: int) -> dict:
    rows = json.loads(
        (Path(__file__).parent / "fixtures/prompt_contract_followup.json").read_text(
            encoding="utf-8"
        )
    )
    return next(
        row for row in rows if row["source"]["kind"] == kind and row["source"]["scene"] == scene
    )


@pytest.mark.parametrize(
    ("ending", "visible"),
    [
        (
            "The bright-rayed crater near centre frame, its shadow stretched leftward, "
            "terminator advanced slightly past where scene 1 ended",
            "bright-rayed crater near centre frame",
        ),
        (
            "The far end of the sunshield with its thin bright edge line, the small trim "
            "flap just visible at the end of the stack, setting up scene 4",
            "small trim flap just visible at the end of the stack",
        ),
    ],
)
def test_a_continuity_pointer_does_not_delete_the_visible_final_frame(ending, visible):
    compiled = words.compile_prompts(
        {
            "subject": "A physical object",
            "motion": "The object moves.",
            "camera_move": "static",
            "ending_frame": ending,
        },
        {},
        {"model_id": "LTX-2.5"},
    )
    actual, _negative = words.motion_prompt_for(compiled, "LTX-2.5")
    assert visible in actual
    assert "scene 1" not in actual and "scene 4" not in actual
    assert not compiled["composition_issues"]


def test_a_spatial_intro_cannot_reduce_marcus_to_the_word_behind():
    first = words._still_moment(
        "Sarah holds the doorframe; behind her, Marcus lets his head drop in a deadpan tilt"
    )
    assert "behind her, Marcus" in first
    assert "deadpan tilt" in first


def test_a_characters_identity_intro_is_not_mistaken_for_the_first_action():
    first = words._still_moment(
        "Marcus, tousled dark hair, wearing a purple hoodie, counts on his fingers, "
        "then lowers his hand; Sarah, brunette bob, wearing a navy blazer, sets down her cup"
    )
    assert "counts on his fingers" in first and "sets down her cup" in first
    assert "lowers his hand" not in first


def test_an_object_pronoun_in_a_complete_spatial_pose_is_not_a_dangling_tail():
    assert words._still_moment("Marcus stands behind her") == "Marcus stands behind her"


@pytest.mark.parametrize("seconds", [3, 9])
def test_a_declared_motionless_world_does_not_get_invented_moving_shadows(seconds):
    compiled = words.compile_prompts(
        {
            "subject": "The sunshield in black vacuum",
            "motion": "Nothing in the world moves",
            "camera_move": "slow pan right",
            "seconds": seconds,
        },
        {},
        {"model_id": "LTX-2.5"},
    )
    actual, _negative = words.motion_prompt_for(compiled, "LTX-2.5")
    assert words.DEFAULT_WORLD_MOTION not in actual
    assert "Nothing in the world moves" in actual
    assert words.MOTION_PAD not in actual
    assert "everything in the frame keeps moving" not in actual.lower()


def test_the_serial_motion_keeps_all_first_moments_when_the_native_cap_allows_them():
    package = recorded("serial", 1)["package"]
    prompt = words.compose_serial_motion(package, load_series_look())
    assert "mostly out of frame" in prompt
    assert not [
        issue
        for issue in words.composition_issues(package, "", prompt, layers=("motion",))
        if "inițială" in issue
    ]
    assert words.lint.utf16_units(prompt) <= words.lint.DEFAULT_PROMPT_MAX_UTF16


def test_an_impossible_motion_still_reports_loss_and_respects_the_native_cap():
    package = {
        "action": "Nadia holds " + "large brass apparatus " * 80,
        "ending_frame": "Nadia beside " + "large intact apparatus " * 80,
        "camera_move": "static",
    }
    prompt, dropped = words.serial_motion(package, load_series_look())
    assert dropped
    assert words.lint.utf16_units(prompt) <= words.lint.DEFAULT_PROMPT_MAX_UTF16
    assert words.composition_issues(package, "", prompt)


def test_all_nine_offline_proposals_fit_without_pretending_sarah_approved_them():
    import importlib.util

    tool = Path(__file__).parents[1] / "tools/prepare_prompt_repairs.py"
    spec = importlib.util.spec_from_file_location("offline_prompt_repairs", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = json.loads(
        (Path(__file__).parent / "fixtures/prompt_contract_followup.json").read_text(
            encoding="utf-8"
        )
    )
    result = module.prepare(rows)
    assert len(result["examples"]) == 9 and result["examples_blocked"] == 0
    report = module.markdown(result)
    assert report.count("— propunere compusă") == 18
    assert "Nu redeschideți filme respinse/închise" in report
    for example in result["examples"]:
        assert not example["auto_apply"]
        assert example["status"] == "OFFLINE_DRAFT_NOT_DIRECTOR_APPROVED"
        contract = {"model_id": example["model"]}
        assert example["prompt_units"]["still"] <= words.lint.prompt_cap(contract, "still")
        assert example["prompt_units"]["motion"] <= words.lint.prompt_cap(contract, "motion")


def test_a_motion_correction_is_not_refused_for_an_unchanged_accepted_still_prompt():
    package = {
        "in_frame": [{"name": "Nadia", "outfit": "plum blouse"}],
        "action": "Nadia taps the pen",
        "camera_move": "static",
        "ending_frame": "Nadia's hand beside the intact pen",
    }
    still = "Nadia at her desk."  # Historical words; the real image is judged separately.
    motion = words.compose_serial_motion(package, load_series_look())
    context = {
        "scene_index": 1,
        "package": {
            **package,
            "still_prompt": still,
            "motion_prompt": "Static camera. Nadia taps the pen.",
        },
        "visual_prompt": still,
        "bible": {},
    }
    assert words.composition_issues(package, still, motion)
    assert not repair._lint_blocks(
        context, {**package, "motion_prompt": motion}, still, layer=repair.MOTION
    )
    assert repair._lint_blocks(
        context, {**package, "motion_prompt": motion}, still, layer=repair.STILL
    )


def test_the_sheet_requires_a_complete_still_only_when_a_new_still_is_needed(engine, tmp_path):
    from app.media.models import SceneTake, StoryboardScene
    from app.media.shooting_sheet import build_sheet
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_film_costing import SEEDANCE, a_film

    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == board))
        package = dict(row.prompt_json)
        package.update(
            {
                "in_frame": [{"name": "Nadia", "outfit": "plum blouse"}],
                "action": "Nadia taps the pen",
                "camera_move": "static",
                "ending_frame": "Nadia's hand beside the intact pen",
            }
        )
        package.pop("motion_intent", None)
        package["motion_prompt"] = words.compose_serial_motion(package, load_series_look())
        row.prompt_json = package
    accepted = build_sheet(engine, board, capabilities=[SEEDANCE], read_live=False)
    assert not [f for f in accepted["lint"] if f["code"] == "REQUIRED_CONTENT_LOST"]
    with Session(engine) as session, session.begin():
        take = session.scalar(select(SceneTake).where(SceneTake.storyboard_id == board))
        take.status = "REJECTED"
    rejected = build_sheet(engine, board, capabilities=[SEEDANCE], read_live=False)
    assert [f for f in rejected["lint"] if f["code"] == "REQUIRED_CONTENT_LOST"]


def test_all_take_refusal_findings_and_their_final_evidence_reach_the_director():
    findings = [
        f"Defect {i}: " + "complete evidence " * 35 + f"LAST CONDITION {i}" for i in range(12)
    ]
    assert repair.refusal_findings(findings) == findings


def test_all_film_findings_retain_their_complete_paired_causes():
    reasons = [
        {
            "text": f"The valve {i} is visibly broken. " + "Evidence detail. " * 30,
            "cause": f"Cause {i}: " + "complete source detail " * 25 + "FINAL CAUSE",
        }
        for i in range(12)
    ]
    failure = repair.film_failure(reasons)
    assert failure["reasons"] == [r["text"].strip() for r in reasons]
    assert failure["causes"] == [r["cause"] for r in reasons]


def test_the_result_check_keeps_the_complete_correction_not_a_300_character_summary():
    from app.media import fix_check

    actual = fix_check._item(
        "Observed defect. " * 35 + "FINAL DEFECT",
        "Expected pose. " * 35 + "FINAL POSE",
        "motion",
        "director",
        cause="Cause. " * 50,
    )
    assert actual["finding"].endswith("FINAL DEFECT")
    assert actual["expected"].endswith("FINAL POSE")
    assert len(actual["cause"]) > 300


def test_the_complete_film_dossier_reaches_the_vision_agent(engine, monkeypatch):
    from uuid import uuid4

    from app.media.picture_qc import evaluate_pictures
    from test_picture_qc import a_film, all_good, give_vision, registry_with, staff

    people = staff(engine)
    give_vision(engine, people["agents"]["VideoEditor"].id)
    ids = a_film(
        engine,
        scenes=[
            {
                "picture": "A telescope. " * 1100,
                "narration": "FINAL NARRATION: preserve the silver membranes.",
            }
        ],
    )
    monkeypatch.setattr("app.media.picture_qc.frames_for", lambda *_a, **_k: ["ZnJhbWUx"])
    registry, model = registry_with(people, lambda _p: all_good(scenes=1))
    evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))
    assert "FINAL NARRATION" in model.calls[0]["prompt"]


def test_the_repair_letter_back_to_sarah_contains_complete_before_after_and_review(engine):
    from app.agents.memory import agent_for_role
    from app.agents.models import AgentMessage
    from app.agents.services import seed_initial_workforce
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    seed_initial_workforce(engine)
    old = "Old first-frame condition. " * 40
    new = "Revised movement condition. " * 40 + "FINAL CORRECTION"
    context = {
        "storyboard_id": "offline",
        "scene_index": 1,
        "title": "Laboratory",
        "visual_prompt": old,
        "package": {"still_prompt": old, "motion_prompt": old},
    }
    with Session(engine) as session:
        director_id = agent_for_role(session, "Director").id
    asked = {
        "brief": {"layer": "motion", "diagnosis": "Valve remains open."},
        "agent_id": director_id,
    }
    done = {
        "layer": "motion",
        "rewritten": True,
        "still_prompt": old,
        "motion_prompt": new,
        "review_attempts": [{"verdict": "TREATS", "reason_ro": "All findings covered."}],
    }
    letter_id = repair._letters(engine, context, asked, done, "offline")
    assert letter_id
    with Session(engine) as session:
        letter = session.scalar(select(AgentMessage).where(AgentMessage.in_reply_to == letter_id))
        assert letter.to_agent_id == director_id
        assert "FINAL CORRECTION" in letter.body_text
        assert letter.body_json["prompts_before"]["motion"] == old
        assert letter.body_json["prompts_after"]["motion"] == new
        assert letter.body_json["review_attempts"][0]["verdict"] == "TREATS"


def test_the_shot_schema_and_rewrite_keep_every_specific_exclusion(monkeypatch):
    # The rewrite merges the Director's, editor's and stored constraints before validation.
    from app.media.series_look import load_factual_look

    constraints = [f"wrong laboratory apparatus {i}" for i in range(14)]
    shot = words.ShotPrompt(
        scene_index=1, subject="A brass valve", motion="The valve turns.", avoid=constraints
    )
    context = {
        "package": {"subject": "A brass valve", "avoid": constraints},
        "scene_index": 1,
        "scene": {"scene_index": 1},
        "bible": {},
        "allowed": {},
        "previous_ending": "",
        "previous_moves": [],
        "shot_type": "MEDIUM",
    }
    # This checks only preservation of editorial constraints, with the real compiler.
    monkeypatch.setattr(words, "_validated_package", lambda s, *_a: (s.model_dump(), []))
    compiled = repair.rewritten_package(context, shot, repair.STILL, {"avoid": constraints})
    assert set(constraints) <= set(compiled["avoid"])
    assert load_factual_look()  # Existing look is retained.


def test_the_editors_reask_and_failure_report_keep_the_last_lint_condition(monkeypatch, engine):
    from app.agents import structured

    constraints = [f"Scene constraint {i}: " + "full requirement " * 12 for i in range(12)]
    constraints[-1] += "UNIQUE LAST CORRECTION"
    asked = []

    def run(*args, **_kwargs):
        asked.append(args[4])
        return SimpleNamespace(), {"id": "offline", "status": "SUCCEEDED"}, None

    monkeypatch.setattr(structured, "structured_run", run)
    monkeypatch.setattr(repair, "shot_schema", lambda *_a, **_k: object())
    monkeypatch.setattr(repair, "rewritten_package", lambda *_a: {"still_prompt": "A valve"})
    monkeypatch.setattr(repair, "_lint_blocks", lambda *_a, **_k: constraints)
    outcome = repair._editor_rewrite(
        engine,
        object(),
        "editor",
        {"scene_index": 1, "title": "Laboratory", "visual_prompt": "A valve"},
        {"layer": "still"},
        "Rewrite the valve scene.",
        "offline",
    )
    assert "UNIQUE LAST CORRECTION" in asked[1]
    assert "UNIQUE LAST CORRECTION" in outcome["reason"]
