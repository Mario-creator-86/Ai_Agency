"""A refusal cannot buy a generic reroll before Sarah reviews the replacement words.

Kelvin's real 2026-10-13 defect: the tracking camera reveals a distorted face.
Her second look diagnosed it; the automatic calmer suffix did not address it.
All providers here are fakes; tests spend no credits and read no live database.
"""

from pathlib import Path

import pytest
from app.media import fix_check, qc
from app.media.scene_rewrite import quality_refused
from test_clip_qc_wiring import approved, shots
from test_director_rewrites_failed_scene import studio  # noqa: F401 - shared fixture
from test_film_costing import Account, Models, SpyVideo, a_film
from test_fix_is_verified import HER, Looks, OffPlanFirst, new_pictures_for
from test_stills_stage import SUBJECTS, SpyStills, approved_run
from test_stills_stage import a_film as still_film


def kelvin_report(path: Path) -> qc.ClipReport:
    reason = "The camera reveals a distorted close-up face instead of staying behind."
    return qc.ClipReport(
        scene=1,
        path=str(path),
        checks=(qc.ClipCheck("picture", "FAILED", True, None, reason),),
        passed=False,
        blocks_ro=(reason,),
        warnings_ro=(),
        unmeasured=(),
        measured={"picture": {"verdict": {"matches_plan": False, "technical_ok": False}}},
    )


@pytest.mark.parametrize("answer", ["CONFIRMED", "UNAVAILABLE"])
def test_a_clip_refusal_enters_the_review_ladder_without_buying_a_generic_retry(
    engine, tmp_path, monkeypatch, answer
):
    asked = []

    def look(*args, **kwargs):
        asked.append(kwargs)
        return {
            **HER[answer],
            "cause": "The tracking camera turns around the researcher.",
            "lesson": "Keep the researcher seen from behind throughout.",
            "layer": "motion",
        }

    monkeypatch.setattr(fix_check, "shot_second_look", look)
    board = a_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    result = approved(
        engine,
        board,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=lambda path, **kwargs: kelvin_report(path),
    )
    (entry,) = result["scenes"]
    assert asked and models.posts() == 1
    assert entry["status"] == "NEEDS_OWNER"  # Internal hold consumed by the Director ladder.
    assert entry["clip_qc"]["status"] == "ESCALATED"
    assert entry["clip_qc"]["retry_prompt"] is None
    assert entry["clip_qc"]["retry_credits"] == 0
    assert quality_refused(engine, board, [1]) == [1]
    (take,) = shots(engine, board)
    assert take.status == "REJECTED" and take.failure_code == "QC.CLIP"


def test_a_hard_clip_limit_cannot_bypass_the_review_when_second_look_is_ineligible(tmp_path):
    report = qc.ClipReport(
        scene=1,
        path="clip.mp4",
        checks=(qc.ClipCheck("faces", "FAILED", True, 1, "forbidden face"),),
        passed=False,
        blocks_ro=("forbidden face",),
        warnings_ro=(),
        unmeasured=(),
        measured={},
    )
    bought, looked = [], []
    outcome = qc.qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: report,
        buy=lambda seed, prompt: bought.append(prompt),
        seed=7,
        motion_prompt="Tracking left. Dust drifts.",
        camera_move="tracking left",
        model_id="LTX-2.5",
        price_credits=1,
        committed_credits=1,
        cap_credits=100,
        look=lambda result: looked.append(result),
    )
    assert bought == [] and looked == []
    assert outcome.status == "ESCALATED" and outcome.attempts == 1


@pytest.mark.parametrize("problem", ["confirmed", "unavailable", "technical", "hard_limit"])
def test_every_refused_still_round_waits_for_review_instead_of_a_generic_reroll(
    engine, tmp_path, monkeypatch, problem
):
    looks = Looks(HER["UNAVAILABLE" if problem == "unavailable" else "CONFIRMED"])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    board = still_film(engine, tmp_path)
    adapter = SpyStills(pictures=new_pictures_for(2))
    judge = OffPlanFirst(lettering=problem == "hard_limit", technical=problem == "technical")
    result = approved_run(engine, board, tmp_path, adapter, judge)
    calls = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    entry = next(row for row in result["scenes"] if row["scene_index"] == 2)
    assert len(calls) == 1  # One original request delivering two candidates.
    assert entry["rewrite"] is True and entry["status"] == "NEEDS_OWNER"
    assert quality_refused(engine, board, [2]) == [2]


def test_an_approved_still_round_keeps_its_take_without_any_rewrite(engine, tmp_path):
    from test_stills_stage import SpyJudge

    board = still_film(engine, tmp_path)
    adapter = SpyStills()
    result = approved_run(engine, board, tmp_path, adapter, SpyJudge())
    assert all(
        row["status"] == "APPROVED" for row in result["scenes"] if row["scene_kind"] == "LIVE"
    )
    assert quality_refused(engine, board, [1, 2, 3, 4, 5, 6]) == []


def test_the_gpu_request_uses_the_exact_words_sarah_reviewed_for_the_kelvin_defect(
    engine,
    tmp_path,
    studio,  # noqa: F811 - shared fixture
    monkeypatch,
):
    from uuid import uuid4

    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, motion_plan
    from app.media.prompt_agent import motion_prompt_for
    from app.media.scene_rewrite import rewrite_failed_scene
    from test_clip_qc_wiring import ScriptedCheck, events
    from test_director_rewrites_failed_scene import Agents, a_planned_film, agents_say, scene
    from test_film_costing import SEEDANCE

    monkeypatch.setattr(fix_check, "shot_second_look", lambda *args, **kwargs: HER["CONFIRMED"])
    board = a_planned_film(engine, tmp_path)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    approved(
        engine,
        board,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=lambda path, **kwargs: kelvin_report(path),
    )
    assert models.posts() == 1
    old_prompt = spy.asked[0]["prompt"]
    words = "The researcher remains seen from behind throughout, with his back to the camera."
    agents = Agents(
        brief={
            "diagnosis": "The camera revealed a distorted face instead of the back.",
            "layer": "motion",
            "avoid": ["revealing the researcher's face"],
            "keep": ["the approved first frame"],
            "change": [words],
            "summary_ro": "Cercetătorul rămâne văzut din spate pe tot clipul.",
        },
        shot={
            "scene_index": 1,
            "motion": words,
            "camera_move": "slow push-in",
            "ending_frame": "the same back and shoulder beside the brass apparatus",
        },
        review={
            "findings": [
                {
                    "finding": "The camera revealed a distorted face.",
                    "treated": True,
                    "severity": "serious",
                    "by": words,
                }
            ],
            "reason_ro": "Promptul păstrează cercetătorul din spate pe tot clipul.",
            "cause": "The camera path allowed the face to enter the shot.",
            "lesson": "Keep the character seen from behind throughout the camera move.",
        },
    )
    outcome = rewrite_failed_scene(engine, agents_say(studio, agents), board, 1, str(uuid4()))
    assert outcome["rewritten"] is True and outcome["review_verdict"] == "TREATS", outcome
    assert models.posts() == 1  # The free review itself makes no GPU purchase.
    (review,) = agents.reviews
    assert "distorted" in review and words in review
    (event,) = events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, board)
    assert event.payload["review"]["verdict"] == "TREATS"
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert plan["held"] == [] and plan["to_buy"] == [1]
    approved(
        engine, board, tmp_path, "test_shot", models, account, clip_check=ScriptedCheck("PASSED")
    )
    expected, _negative = motion_prompt_for(scene(engine, board).prompt_json, "seedance2_5", None)
    import json
    import re

    evidence = re.search(
        r'<untrusted_source_evidence hash="rewrite-review">\n(.*?)\n</untrusted_source_evidence>',
        review,
        re.DOTALL,
    )
    assert evidence is not None
    reviewed_prompt = json.loads(evidence.group(1))["prompts_after"]["motion"]
    assert models.posts() == 2
    assert spy.asked[-1]["prompt"] == expected != old_prompt
    assert expected == reviewed_prompt
    assert words in expected  # The complete orientation, including "back to the camera".
