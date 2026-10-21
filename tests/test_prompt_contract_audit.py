"""Prompt losses reproduced without network, models or paid generation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.agents.mail import _thread_text
from app.agents.messages import post_message
from app.media import prompt_agent as words
from app.media.prompt_lint import utf16_units
from app.media.scene_rewrite import review_findings
from app.media.series_look import load_series_look
from sqlalchemy.orm import Session

FACE_BIBLE = {"continuity_rules": ["No human faces appear"]}


@pytest.mark.parametrize("model", ["LTX-2.5", "wan2.2", "veo3.1", "gen4_turbo"])
def test_factual_final_frame_is_in_the_actual_model_dialect(model):
    package = {
        "subject": "A brass valve on a laboratory bench",
        "action": "The valve rests beside a glass tube",
        "motion": "The valve wheel turns a quarter turn.",
        "camera_move": "static",
        "ending_frame": "the closed brass valve beside the intact glass tube",
    }
    compiled = words.compile_prompts(package, FACE_BIBLE, {"model_id": model})
    actual, _negative = words.motion_prompt_for(compiled, model)
    assert "closed brass valve beside the intact glass tube" in actual.lower()
    assert utf16_units(actual) <= 1000


def test_a_measurement_does_not_ask_the_image_model_to_add_people():
    compiled = words.compile_prompts(
        {
            "subject": "Two metal discs with a finger's-width gap between them",
            "camera": "Detail shot, 85mm lens",
            "motion": "The discs rotate slowly.",
        },
        FACE_BIBLE,
    )
    assert "figures" not in compiled["still_prompt"]
    assert "Faces stay" not in compiled["motion_prompt"]


def test_explicit_static_camera_is_not_changed_to_obtain_variety():
    assert (
        words._serial_camera_move({"camera_move": "static", "shot_size": "single"}, ["static"])
        == "static"
    )


def test_static_camera_written_in_the_plan_is_respected_too():
    assert (
        words._serial_camera_move(
            {"camera": "Medium close-up, static camera on a tripod", "shot_size": "single"},
            ["static"],
        )
        == "static"
    )


def test_face_ban_blocks_an_orbit_that_would_turn_into_the_face():
    package = {
        "subject": "A researcher at the bench seen from behind",
        "camera_move": "slow orbit",
        "motion": "The researcher turns the valve slowly.",
    }
    compiled = words.compile_prompts(package, FACE_BIBLE)
    assert any("orbit" in issue for issue in compiled["composition_issues"])


def test_a_camera_clause_in_the_ending_is_reported_as_lost():
    package = {
        "action": "Nadia taps the pen.",
        "camera_move": "static",
        "ending_frame": "Nadia and Sarah facing the viewer, static camera, no zoom",
    }
    _prompt, dropped = words.serial_motion(package, load_series_look())
    assert dropped, "An unusable final-frame instruction must not disappear silently."


def test_serial_wardrobe_survives_a_long_action():
    nadia = {
        "name": "Nadia",
        "face_hair": "Chestnut hair in a neat low bun; round tortoiseshell glasses; hazel eyes",
        "outfit": "Plum blouse under a dark violet cardigan, small brass pen on a chain",
    }
    package = {
        "in_frame": [nadia],
        "shot_size": "single",
        "location": "Treasury office",
        "action": "Nadia taps the pen against the green ledger resting beside "
        + "polished walnut objects " * 13,
    }
    prompt = words.compose_serial_prompt(package, load_series_look())
    assert "plum blouse under a dark violet cardigan" in prompt.lower()
    assert len(prompt) <= load_series_look()["max_prompt_chars"]


def test_ninth_qc_finding_is_not_silently_removed():
    context = {
        "last_code": "QC.CLIP",
        "failures": [
            {
                "kind": "motion",
                "code": "QC.CLIP",
                "reasons": [
                    f"Visible defect {number}: the requested object is missing"
                    for number in range(12)
                ],
            }
        ],
    }
    findings = review_findings(context)
    assert len(findings) == 12
    assert findings[-1]["id"] == 12


def test_all_corrections_reach_the_new_picture_and_clip_checklists():
    from app.media.picture_qc import fix_items

    required = tuple(
        {"finding": f"Defect {i}", "expected": f"Corrected condition {i}"} for i in range(12)
    )
    items = fix_items(SimpleNamespace(must_fix=required))
    assert len(items) == 12
    assert items[-1]["expected"] == "Corrected condition 11"


def test_specific_negative_conditions_are_not_lost_after_generic_terms():
    from app.media.stills_stage import still_negative

    condition = "duplicated valves and extra glass tubes appearing behind the apparatus"
    actual = still_negative(
        {"avoid": ["miscellaneous artefact " * 12, condition]},
        {"avoid": ["anachronistic electric switches"]},
    )
    assert condition in actual
    assert "anachronistic electric switches" in actual


def test_factual_bible_specific_exclusions_reach_a_supported_negative_channel():
    compiled = words.compile_prompts(
        {"subject": "A brass valve", "motion": "The valve turns slowly.", "camera_move": "static"},
        {"avoid": ["anachronistic electric switches"]},
        {"model_id": "veo3.1"},
    )
    assert "anachronistic electric switches" in compiled["negative_prompt"]


def test_a_composed_prompt_with_lost_required_meaning_blocks_before_purchase():
    from app.media.prompt_lint import BLOCK, LintScene, lint_scene

    package = {
        "action": "Nadia taps the pen.",
        "ending_frame": "Nadia facing the viewer, static camera",
    }
    issues = words.composition_issues(
        package, "Nadia with a pen.", "Static camera. Nadia taps the pen."
    )
    assert issues
    findings = lint_scene(
        LintScene(
            scene=1,
            still_prompt="Nadia with a pen.",
            motion_prompt="Static camera. Nadia taps the pen.",
            composition_issues=tuple(issues),
        )
    )
    assert any(f.code == "REQUIRED_CONTENT_LOST" and f.severity == BLOCK for f in findings)


def test_long_letter_is_stored_whole_and_structured_evidence_reaches_the_addressee(engine):
    letter = "Diagnosis with evidence. " * 500 + "FINAL REQUIRED CORRECTION: keep the valve closed."
    with Session(engine) as session, session.begin():
        row = post_message(
            session,
            intent="STATUS",
            subject="Scene repair",
            body_text=letter,
            body={"qc_findings": [{"id": 9, "expected": "keep the valve closed"}]},
        )
        assert row.body_text == letter
        transcript = _thread_text([row], {})
        assert "FINAL REQUIRED CORRECTION" in transcript
        assert '"id": 9' in transcript


def test_initial_plan_batches_keep_every_scene_claim_and_character():
    scenes = [
        {
            "scene_index": n,
            "narration": "Evidence-backed explanation. " * 80,
            "claims": [{"claim_text": "Complete verified claim. " * 60}],
            "characters": [{"name": "Nadia", "outfit": "plum blouse"}],
        }
        for n in range(1, 9)
    ]
    data = {"visual_bible": FACE_BIBLE, "film": {"title": "Kelvin", "scenes": scenes}}
    batches = words.shot_payload_batches(data, ["Keep the researcher seen from behind."], 7000)
    supplied = [scene for batch in batches for scene in batch["film"]["scenes"]]
    assert supplied == scenes
    assert len(batches) > 1
    assert all(batch["lessons"] == ["Keep the researcher seen from behind."] for batch in batches)
    assert all(batch["visual_bible"] == FACE_BIBLE for batch in batches)


def test_qc_payload_never_cuts_json_or_the_last_required_rule(monkeypatch, engine):
    from app.agents import structured
    from app.agents.memory import agent_for_role
    from app.agents.services import seed_initial_workforce
    from app.media import picture_qc
    from app.media.still_gate import StillPlan

    seed_initial_workforce(engine)
    with Session(engine) as session:
        editor = agent_for_role(session, "VideoEditor")
        looker = (editor.id, editor.display_name)
    captured = []
    monkeypatch.setattr(picture_qc, "still_image", lambda *_a, **_k: "fake-image")
    monkeypatch.setattr(picture_qc, "vision_agent", lambda *_a, **_k: looker)
    monkeypatch.setattr(picture_qc, "find_ffmpeg", lambda *_a: "fake-ffmpeg")

    def run(*args, **kwargs):
        captured.append(args[4])
        return None, {"id": "offline", "status": "FAILED"}, None

    monkeypatch.setattr(structured, "structured_run", run)
    plan = StillPlan(
        scene=1,
        still_prompt="The valve rests on the bench. " * 330,
        camera_move="static",
        faces_forbidden=True,
        bible_rules=("REQUIRED LAST RULE: intact glass tube",),
    )
    picture_qc.judge_still(
        engine, SimpleNamespace(registered_ids=lambda: ["fake"]), "unused.png", plan, "offline"
    )
    assert captured and "REQUIRED LAST RULE" in captured[0]


def test_director_inbox_includes_the_actual_letter_not_only_metadata(monkeypatch, engine):
    from app.agents import structured
    from app.agents.director import DirectorError, director_review
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject="QC failed",
            body_text="UNIQUE DEFECT: the valve is open; it must be closed.",
            body={"scene": 2},
        )
    captured = []

    def run(*args, **kwargs):
        captured.append(args[4])
        return None, {"id": "offline", "status": "FAILED"}, None

    monkeypatch.setattr(structured, "structured_run", run)
    with pytest.raises(DirectorError):
        director_review(engine, SimpleNamespace())
    assert "UNIQUE DEFECT" in captured[0]


def test_same_rejected_input_cannot_be_reserved_on_a_new_seed(engine, tmp_path):
    from app.providers.runpod.batch import BatchRefused, reserve_item
    from app.providers.runpod.jobs import JobStore
    from test_input_guard import at, bought, clip
    from test_phase5_media import _seeded_storyboard
    from test_runpod_batch import serverless

    film, _claim = _seeded_storyboard(engine, tmp_path, scenes=1)
    asked = clip(film)
    bought(
        engine,
        asked,
        status="REJECTED",
        when=at(18),
        code="QC.CLIP",
        detail="The valve remains open instead of closed.",
    )
    with pytest.raises(BatchRefused) as error:
        reserve_item(JobStore(engine), serverless(), None, clip(film, seed=999, attempt=2))
    assert error.value.code == "SAME_INPUT_FAILED"
