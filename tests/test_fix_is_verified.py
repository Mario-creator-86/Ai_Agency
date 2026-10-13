"""After a rewrite, the new still and clip are checked for exactly what it was meant to fix.

The Owner, 2026-10-12, 16:50, after stopping the studio: «Sistemul trebuie să refacă promptul!
... DAR SĂ REFACĂ CE A FOST GREȘIT. Și să se asigure că ce a fost greșit este acum corectat. Nu
să facă aceeași greșeală la nesfârșit!» On f06808c9 scene 4 the finding was «two women face to
face instead of a single on Nadia»; the rewrite answered it in words, the Director's review said
so, and nothing looked for the two women again until the film's QC, after the clip and the money.
Later that evening: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!», «Nu putem permite loopuri pe bani»,
and the rule «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI
ȘI MIȘCĂRI COSTĂ!» — the Director looks at a refusal before any re-roll or retry is bought.

What is asserted (the adversarial review of 9ac0195, findings 1-10):

- `fix_check.open_findings` names, per layer, what is open: her review's findings in quality
  control's OWN words (``qc_text``) with her correction as guidance (``expected``); the brief's
  film words only for a rewrite whose review kept no findings, and then only what was SEEN — her
  repair proposals never; her REAL QC verdicts on a scene no still was made for since; a finding
  treated in the motion's words on the clip, never on the still; picture findings ranked first
  under the cap, paraphrases said once;
- the look answers each item gone, minor or persists: only persists refuses, a minor trace is a
  warning on the take; a still that shows its corrected words and the mistake again is never
  re-rolled on them (the scene goes back to her ladder with the sentence that failed); one that
  also missed its plan gets one re-roll at most; a look nobody could make is a content refusal;
- the serial's «scene» is the composed beat, never the writer's line;
- clip QC asks the motion items, refuses a persisting one back to the motion, never the still;
- the rewrite's lessons are confirmed by a still approved with every item gone and withdrawn by
  one that showed the mistake again;
- before a re-roll or a clip retry is bought, the Director looks (faked): OVERTURNED keeps the
  picture and buys nothing, CONFIRMED lets the purchase go with her reason, UNAVAILABLE changes
  nothing — counted in purchases.

Every model and vendor is faked, as the stills-step and picture-QC tests fake them.
"""

from __future__ import annotations

import json
import sys
import types
from uuid import uuid4

import pytest
from app.agents.models import AgentRun
from app.media import fix_check, prompt_agent, stills_stage
from app.media.assembler import CLIP_QC_EVENT, SCENE_PROMPTS_REWRITTEN_EVENT, _clip_plan
from app.media.models import SceneTake, StoryboardScene
from app.media.picture_qc import (
    CLIP_FIX_TEMPLATE_VERSION,
    CLIP_TASK,
    STILL_FIX_TEMPLATE_VERSION,
    STILL_TASK,
    STILL_TEMPLATE_VERSION,
    ClipJudgement,
    ClipVerdict,
    FixAnswer,
    StillFix,
    StillJudgement,
    StillJudgeReport,
    StillVerdict,
    fix_items,
    still_report_schema,
)
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    CONTENT_REFUSAL,
    REWRITE_REASON,
    TECHNICAL_REFUSAL,
    refusal_kind,
)
from app.media.still_gate import (
    POSITIVE_WORDS,
    REWRITE_PHRASE,
    StillPlan,
    choose_best,
    decide,
    fix_answers,
    may_be_overturned,
    next_step,
    round_step,
)
from app.models import DomainEvent
from app.services import append_event
from sqlalchemy import select
from sqlalchemy.orm import Session

# The GPU session switched on and off around the rounds, faked as the RunPod tests fake it.
from test_runpod_batch import fake_session  # noqa: F401
from test_stills_stage import (
    FIXTURES,
    NO_FACE,
    SUBJECTS,
    SpyStills,
    a_film,
    approved_run,
    takes,
)

NADIA = "two women face to face instead of a single on Nadia"
NADIA_FIX = (
    "Medium close-up single at eye level on Nadia at her ledger desk, Sarah only a blurred "
    "shoulder at the frame's left edge."
)
#: Quality control's own words for the same finding (the film's picture QC, f06808c9 scene 4).
QC_NADIA = (
    "Scene 4: the picture is not what the scene asked for — Frame shows two women facing each "
    "other across the ledger instead of the requested medium close-up single on Nadia."
)
ENDING = "the ending frame lands on a profile two-shot instead of both facing the viewer"
ENDING_FIX = "The shot ends on Marcus and Sarah side by side, both facing the viewer."
FFMPEG = __import__("shutil").which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def rewritten(
    engine,
    storyboard_id: str,
    scene: int,
    *,
    findings: list,
    film: list[str] = (),
    layer: str = "still",
    reason: str = REWRITE_REASON,
    run_id: str | None = None,
    review_run_id: str | None = None,
    still_prompt: str | None = None,
    motion_prompt: str | None = None,
) -> str:
    """The Director's rung on one scene, as `scene_rewrite.rewrite_scene` and `_record_brief`
    record it: the rewrite (with her review's findings: a (finding, by) pair as the first
    version kept them, or a whole entry as the contract of 2026-10-12 evening keeps it), then
    her brief (with the film's words). Returns her review's run id."""
    run_id = run_id or str(uuid4())
    review_run_id = review_run_id or str(uuid4())
    entries = [
        item
        if isinstance(item, dict)
        else {"finding": item[0], "treated": True, "by": item[1], "why_not": ""}
        for item in findings
    ]
    with Session(engine) as session, session.begin():
        append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "scene_index": scene,
                "reason": reason,
                "decided_by": "director",
                "layer": layer,
                "old_still_prompt": "the old words",
                "still_prompt": still_prompt
                or ("the new words" if layer == "still" else "the old words"),
                "old_motion_prompt": "the old motion",
                "motion_prompt": motion_prompt or "the new motion",
                "run_id": run_id,
                "review": {
                    "verdict": "TREATS",
                    "reason_ro": "Rescrierea tratează constatarea.",
                    "findings": entries,
                    "run_id": review_run_id,
                },
            },
            str(uuid4()),
        )
        append_event(
            session,
            BRIEF_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "scene_index": scene,
                "layer": layer,
                "rewritten": True,
                "rewrite_run_id": run_id,
                "failures": [{"kind": "film", "code": "QC.FILM", "reasons": list(film)}]
                if film
                else [],
            },
            str(uuid4()),
        )
    return review_run_id


def decided(engine, storyboard_id: str, verdicts: list[dict], repairs: list[dict] = ()) -> None:
    """Her QC decision (`director_qc.record_decision`), on the report's aggregate."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            fix_check.DIRECTOR_QC_EVENT,
            "qc_report",
            str(uuid4()),
            1,
            {
                "storyboard_id": storyboard_id,
                "decision": "REPAIR",
                "run_id": str(uuid4()),
                "verdicts": verdicts,
                "repairs": list(repairs),
            },
            str(uuid4()),
        )


def _take(engine, storyboard_id, scene, kind, status, created_at, **more) -> str:
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=scene,
                kind=kind,
                prompt_hash=uuid4().hex + uuid4().hex,
                model_id="seedream5_pro" if kind == "still" else "seedance2_5",
                resolution="1530:2720" if kind == "still" else "1080:1920",
                status=status,
                created_at=created_at,
                updated_at=created_at,
                **more,
            )
        )
    return take_id


def approved_still(engine, storyboard_id: str, scene: int, created_at: str) -> None:
    _take(engine, storyboard_id, scene, "still", "APPROVED", created_at, approved_by="still_gate")


def passed_clip(engine, storyboard_id: str, scene: int, created_at: str) -> None:
    take_id = _take(engine, storyboard_id, scene, "motion", "PAID", created_at)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            take_id,
            1,
            {"storyboard_id": storyboard_id, "scene_number": scene, "verdict": "PASSED"},
            str(uuid4()),
        )


def open_for(engine, storyboard_id: str, scene: int, layer: str = "still") -> list[dict]:
    with Session(engine) as session:
        return fix_check.open_findings(session, storyboard_id, scene, layer=layer)


def said(items) -> list[tuple[str, str]]:
    return [(item["finding"], item["expected"]) for item in items]


def item(finding: str = NADIA, expected: str = NADIA_FIX, **more) -> dict:
    return {
        "finding": finding,
        "expected": expected,
        "layer": "still",
        "source": "review",
        "source_id": "review-run",
        "cause": "",
        **more,
    }


def plan_for(scene: int = 4, must_fix=()) -> StillPlan:
    return StillPlan(
        scene=scene,
        still_prompt="Warm hand-drawn 2D animation. Medium close-up single at eye level on Nadia.",
        camera_move="slow push-in",
        faces_forbidden=False,
        bible_rules=(),
        scene_picture="Ground floor, quiet office, Nadia at her ledger desk.",
        narration="My close went out twice today.",
        purpose="REVEAL",
        must_fix=tuple(must_fix),
    )


def verdict(scene: int = 4, fixes=(), **changes) -> StillJudgement:
    fields = {
        "scene": scene,
        "faces_visible": False,
        "readable_text": False,
        "one_picture": True,
        "matches_plan": True,
        "shows_scene": True,
        "look_ok": True,
        "technical_ok": True,
        "bible_violations": "none",
        "verdict": "buy_motion",
        "reason": "Nadia at her desk",
        "fixes": list(fixes),
    }
    fields.update(changes)
    return StillJudgement(
        status="MEASURED",
        verdict=StillVerdict(**fields),
        detail_ro="",
        run_id="run-1",
        looked_by="Video Editor",
        image_width=1080,
    )


def fix(number: int, status: str, seen: str = "Nadia alone at her desk") -> FixAnswer:
    return FixAnswer(item=number, finding="", status=status, seen=seen)


# ------------------------------------------------------- 1. what the rewrite was meant to fix


def test_the_items_are_quality_controls_own_words_with_her_correction_as_guidance(engine, tmp_path):
    """Finding 1: her review keeps, per finding, quality control's words (``qc_text``); the
    item is those words, the sentence that treats it is guidance. Her brief's film reasons
    (her REPAIR proposals among them) are never read while the review kept findings."""
    storyboard_id = a_film(engine, tmp_path)
    review_run = rewritten(
        engine,
        storyboard_id,
        2,
        findings=[
            {
                "id": 1,
                "qc_text": QC_NADIA,
                "finding": "two women in frame",
                "treated": True,
                "by": NADIA_FIX,
                "why_not": "",
                "severity": "serious",
                "layer": "still",
            }
        ],
        film=[
            "After the new still is bought and approved, the motion must be redone on the new "
            "still with a prompt that specifies the medium close-up single on Nadia.",
            "Paid redo within the cap: 7 credits for the still of scene 2.",
        ],
    )

    (found,) = open_for(engine, storyboard_id, 2)

    assert (found["finding"], found["expected"]) == (QC_NADIA, NADIA_FIX)
    assert found["layer"] == "still" and found["source"] == "review"
    assert found["source_id"] == review_run
    # Only the rewritten scene has anything open; the clip has nothing of a still finding.
    assert open_for(engine, storyboard_id, 1) == []
    assert open_for(engine, storyboard_id, 2, layer="motion") == []


def test_a_record_without_review_findings_gives_only_what_the_film_saw(engine, tmp_path):
    """A rewrite recorded before her review kept its findings: the brief's film reasons, the
    sentences that say what was seen. Her proposals, the studio's notes, English or Romanian,
    never become an item (read on the 2026-10-12 database copy, f06808c9)."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(
        engine,
        storyboard_id,
        2,
        findings=[],
        film=[
            "Scena 2: mișcarea filmată din imaginea nouă.",
            "The motion take was made from the rejected still and carries the same faults: two "
            "women facing each other, garbled text and ruled lines. After the new still is "
            "bought and approved, the motion must be redone on the new still with a prompt "
            "that specifies the medium close-up single on Nadia.",
            "Paid redo within the cap: the still of scene 2 must be redone after the new still.",
            "The movement of this scene was rewritten before and came back with the same "
            "words; the picture itself must change now.",
            "the lamp is missing from the desk",
            "x" * 400,
            "the cup on the desk is blue",
        ],
    )

    found = open_for(engine, storyboard_id, 2)

    assert [item["finding"] for item in found][:2] == [
        "The motion take was made from the rejected still and carries the same faults: two "
        "women facing each other, garbled text and ruled lines.",
        "the lamp is missing from the desk",
    ]
    assert all(item["expected"] == "" and item["source"] == "film" for item in found)
    assert len(found) == fix_check.MAX_ITEMS == 4
    assert all(len(item["finding"]) <= fix_check.MAX_CHARS for item in found)
    words = " ".join(item["finding"] for item in found)
    for proposal in ("mișcarea filmată", "must be redone", "Paid redo", "rewritten before"):
        assert proposal not in words
    # The film's words name no layer: the clip after the still is checked for them too.
    assert said(open_for(engine, storyboard_id, 2, layer="motion")) == said(found)


def test_what_a_film_reason_saw_is_kept_and_its_prescription_left_out():
    assert fix_check.observed("Scena 5: mișcarea filmată din imaginea nouă.") == ""
    assert fix_check.observed("Paid redo within the cap.") == ""
    assert fix_check.observed("Rewrite the motion prompt to state the final framing.") == ""
    assert fix_check.observed("Refacerea imaginii costă 7 credite; cumpărăm din nou.") == ""
    assert fix_check.observed("Buying a new still is needed.") == ""
    assert (
        fix_check.observed(
            "The push-in is steady but the ending frame lands on a profile two-shot. Rewrite "
            "the motion prompt to state the final framing explicitly."
        )
        == "The push-in is steady but the ending frame lands on a profile two-shot."
    )


def test_nothing_is_open_without_a_rewrite_by_her_brief(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    assert open_for(engine, storyboard_id, 3) == []
    # The compiler's own rewrite for a redo, and the serial composer's, answer no finding.
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], reason="redo")
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], reason="serial_recompose")
    assert open_for(engine, storyboard_id, 3) == []
    assert open_for(engine, storyboard_id, 3, layer="motion") == []
    # A motion rewrite keeps the still's words: nothing for a still, its findings for the clip.
    rewritten(
        engine, storyboard_id, 3, findings=[("the camera drifts", "a slow push-in")], layer="motion"
    )
    assert open_for(engine, storyboard_id, 3) == []
    assert said(open_for(engine, storyboard_id, 3, layer="motion")) == [
        ("the camera drifts", "a slow push-in")
    ]


def test_a_motion_rewrite_after_the_pictures_leaves_the_pictures_findings(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)], still_prompt=NADIA_FIX)
    rewritten(
        engine, storyboard_id, 2, findings=[("the camera drifts", "a slow push-in")], layer="motion"
    )
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2)] == [NADIA]
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2, layer="motion")] == [
        "the camera drifts"
    ]


def test_each_finding_is_checked_on_its_layer(engine, tmp_path):
    """Finding 5: an item stays on the still only when its layer is the still's (the contract)
    or, on an older record, when the sentence that treats it is in the still prompt; one
    treated in the motion's words goes to the clip; one whose layer is not known, to both."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(
        engine,
        storyboard_id,
        2,
        findings=[
            {"qc_text": QC_NADIA, "by": NADIA_FIX, "treated": True, "layer": "still"},
            {"qc_text": ENDING, "by": ENDING_FIX, "treated": True, "layer": "motion"},
            ("a lamp is missing from the desk", "A brass lamp stands lit on the desk."),
            ("the cup on the desk is red", "A plain white cup sits beside the ledger now."),
            ("the window shows night", "Morning light through the tall window."),
        ],
        still_prompt="Warm office. A brass lamp stands lit on the desk.",
        motion_prompt="Slow push-in. A plain white cup sits beside the ledger now.",
    )

    still = open_for(engine, storyboard_id, 2)
    motion = open_for(engine, storyboard_id, 2, layer="motion")

    assert [i["finding"] for i in still] == [
        QC_NADIA,
        "a lamp is missing from the desk",
        "the window shows night",
    ]
    assert [i["layer"] for i in still] == ["still", "still", "both"]
    assert [i["finding"] for i in motion] == [
        ENDING,
        "the cup on the desk is red",
        "the window shows night",
    ]
    assert motion[0]["expected"] == ENDING_FIX


def test_a_still_approved_after_the_rewrite_closes_the_picture_and_a_passed_clip_the_motion(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path)
    # The still the film was made from, approved long before the rewrite: never checked for it.
    approved_still(engine, storyboard_id, 2, "2026-10-01T10:00:00+00:00")
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2)] == [NADIA]
    # A still made after the rewrite and approved was checked for it: the still is closed...
    approved_still(engine, storyboard_id, 2, "2999-01-01T00:00:00+00:00")
    assert open_for(engine, storyboard_id, 2) == []
    # ... and an item whose layer is not known still waits for the clip (finding 5: the still's
    # look answering «gone» for a movement never closed what only the clip can show).
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2, layer="motion")] == [
        NADIA
    ]
    passed_clip(engine, storyboard_id, 2, "2999-01-01T00:00:01+00:00")
    assert open_for(engine, storyboard_id, 2, layer="motion") == []


def test_the_cap_keeps_the_picture_findings_and_says_a_paraphrase_once(engine, tmp_path):
    """Finding 6: four items at most, the picture's first on the still layer, the movement's
    first on the clip's; a paraphrase of a finding already kept is not asked twice."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(
        engine,
        storyboard_id,
        2,
        findings=[],
        film=[
            "The camera drifts left and the ending frame lands on a profile two-shot.",
            "Two women facing each other instead of a single on Nadia.",
            NADIA,
            "ruled lines and garbled text on the ledger",
            "the lamp is missing from the desk",
            "the cup on the desk is blue",
        ],
    )

    still = [item["finding"] for item in open_for(engine, storyboard_id, 2)]
    motion = [item["finding"] for item in open_for(engine, storyboard_id, 2, layer="motion")]

    assert still == [
        "Two women facing each other instead of a single on Nadia.",
        "ruled lines and garbled text on the ledger",
        "the lamp is missing from the desk",
        "the cup on the desk is blue",
    ]
    assert motion[0] == "The camera drifts left and the ending frame lands on a profile two-shot."
    assert NADIA not in still + motion


def test_her_real_qc_verdicts_are_checked_when_the_redo_was_not_rewritten(engine, tmp_path):
    """Finding 7: a paid still redo with no rewrite (a still he approved without «final») is
    checked for her REAL verdicts on the scene, with her cause, until a still newer than her
    decision is approved; the motion copy until a clip passes. ACCEPTED and FALSE ask nothing,
    and her review's ``qc_text`` of the same finding is not asked twice."""
    storyboard_id = a_film(engine, tmp_path)
    decided(
        engine,
        storyboard_id,
        [
            {
                "finding": 1,
                "text": QC_NADIA,
                "scene_index": 3,
                "verdict": "REAL",
                "severity": "serious",
                "cause": "the still prompt named both women in one sentence",
            },
            {"finding": 2, "text": "a faint mark", "scene_index": 2, "verdict": "ACCEPTED"},
            {"finding": 3, "text": "nothing wrong", "scene_index": 4, "verdict": "FALSE"},
        ],
        repairs=[{"scene_index": 3, "redo": "still", "reason": "Paid redo of the still."}],
    )

    (found,) = open_for(engine, storyboard_id, 3)
    assert (found["finding"], found["expected"]) == (QC_NADIA, "")
    assert found["cause"] == "the still prompt named both women in one sentence"
    assert found["source"] == "director_qc"
    assert open_for(engine, storyboard_id, 2) == [] and open_for(engine, storyboard_id, 4) == []
    # The look is shown her cause beside quality control's words.
    shown = fix_items(plan_for(3, must_fix=[found]))
    assert shown == [{"finding": QC_NADIA, "expected": "", "cause": found["cause"]}]

    # Her review of a rewrite of the same scene, with the same words: said once, with her fix.
    rewritten(
        engine,
        storyboard_id,
        3,
        findings=[{"qc_text": QC_NADIA, "by": NADIA_FIX, "treated": True, "layer": "still"}],
    )
    assert said(open_for(engine, storyboard_id, 3)) == [(QC_NADIA, NADIA_FIX)]

    approved_still(engine, storyboard_id, 3, "2999-01-01T00:00:00+00:00")
    assert open_for(engine, storyboard_id, 3) == []
    assert [i["finding"] for i in open_for(engine, storyboard_id, 3, layer="motion")] == [QC_NADIA]


# ------------------------------------------------------------------ 2. the gate's decision


def test_a_still_that_repeats_the_mistake_on_its_plan_goes_back_to_her_words():
    """Findings 2 and 3: persists refuses with the sentence that failed; a still that shows its
    plan and the mistake again is not re-rolled — the scene goes to her ladder."""
    plan = plan_for(must_fix=[item()])
    seen = "two women facing each other across the ledger"

    persists = decide(
        NO_FACE[0], plan, [], verdict(fixes=[fix(1, "persists", seen)]), environment="TEST"
    )
    gone = decide(NO_FACE[1], plan, [], verdict(fixes=[fix(1, "gone")]), environment="TEST")

    assert persists.decision == "BLOCKED"
    first = persists.reasons_ro[0]
    # The content phrase FIRST (round 3, finding 2): it must survive the take's 500 characters.
    assert first.startswith(
        "Nu arată ce cere scena după rescriere: imaginea repetă greșeala pe care rescrierea "
        f"trebuia să o corecteze «{NADIA}»"
    )
    assert "cuvintele «Medium close-up single at eye level on Nadia" in first
    assert "nu au corectat-o" in first and seen in first
    assert persists.violations == ("finding_persists",)
    assert persists.fixes[0]["status"] == "persists" and persists.fixes[0]["fixed"] is False
    # The Director's ladder reads the take's words as a content refusal: her brief, not a reroll
    # of the same words with another seed (scene_rewrite.refusal_kind).
    assert refusal_kind("LOCAL.STILL_GATE", "; ".join(persists.reasons_ro)[:500]) == CONTENT_REFUSAL
    step = next_step(persists, rerolls_done=0)
    assert step.action == "rewrite" and step.instruction == ""
    assert "nu au corectat-o" in step.reason_ro and "Directoarea le rescrie" in step.reason_ro

    assert gone.decision == "PASSED" and gone.violations == () and gone.minor == ()
    assert choose_best([persists, gone]) is gone


def test_a_still_that_also_missed_its_plan_gets_one_reroll_at_most():
    plan = plan_for(must_fix=[item()])
    missed = decide(
        NO_FACE[0],
        plan,
        [],
        verdict(fixes=[fix(1, "persists", "two women")], matches_plan=False),
        environment="TEST",
    )
    assert set(missed.violations) == {"finding_persists", "plan"}
    first = next_step(missed, rerolls_done=0)
    assert first.action == "reroll" and POSITIVE_WORDS["finding_persists"] in first.instruction
    assert next_step(missed, rerolls_done=1).action == "rewrite"
    # In a round, the candidate that showed its plan and the mistake decides it.
    on_plan = decide(
        NO_FACE[1], plan, [], verdict(fixes=[fix(1, "persists", "two women")]), environment="TEST"
    )
    assert round_step([missed, on_plan], rerolls_done=0).action == "rewrite"


def test_a_minor_trace_is_accepted_as_a_warning():
    """Finding 2: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» — a minor trace passes the still, says so
    on it, and a candidate with nothing left is preferred to one with a trace."""
    plan = plan_for(must_fix=[item()])
    shoulder = "Sarah's shoulder at the left edge, blurred"
    minor = decide(
        NO_FACE[0], plan, [], verdict(fixes=[fix(1, "minor", shoulder)]), environment="TEST"
    )
    gone = decide(NO_FACE[1], plan, [], verdict(fixes=[fix(1, "gone")]), environment="TEST")

    assert minor.decision == "PASSED" and minor.violations == ()
    assert minor.minor == ({"finding": NADIA, "seen": shoulder},)
    assert any("Urmă mică" in w and shoulder in w for w in minor.warnings_ro)
    assert choose_best([minor, gone]) is gone
    assert choose_best([minor]) is minor


def test_the_worst_answer_for_an_item_wins_and_silence_is_not_a_pass():
    plan = plan_for(must_fix=[item(), item("a lamp", "")])
    both = decide(
        NO_FACE[0],
        plan,
        [],
        verdict(fixes=[fix(1, "gone"), fix(1, "persists", "Sarah in full view"), fix(2, "gone")]),
        environment="TEST",
    )
    assert both.decision == "BLOCKED" and "finding_persists" in both.violations
    # A verdict built in code that leaves an item out is a still nobody checked for it.
    silent = decide(NO_FACE[0], plan, [], verdict(fixes=[fix(1, "gone")]), environment="TEST")
    assert silent.decision == "BLOCKED" and "vision" in silent.unmeasured
    assert any("nu a spus dacă imaginea corectează" in r for r in silent.reasons_ro)


def test_without_must_fix_the_decision_is_unchanged():
    report = decide(NO_FACE[0], plan_for(), [], verdict(), environment="TEST")
    assert report.decision == "PASSED" and report.fixes == () and report.minor == ()


def test_a_still_nobody_could_check_for_the_mistake_is_a_content_refusal():
    """Finding 8: a NOT_RUN on a still with open items read TECHNICAL, and the serial bought
    the same words again; with items it carries the content phrase, without them it does not."""
    nobody = StillJudgement(
        status="NOT_RUN",
        verdict=None,
        detail_ro="nu a fost privită: modelul nu a dat un verdict utilizabil",
        run_id=None,
        looked_by=None,
        image_width=None,
    )
    checked = decide(NO_FACE[0], plan_for(must_fix=[item()]), [], nobody, environment="TEST")
    plain = decide(NO_FACE[0], plan_for(), [], nobody, environment="TEST")
    assert checked.unmeasured == ("vision",) and plain.unmeasured == ("vision",)
    assert refusal_kind("LOCAL.STILL_GATE", "; ".join(checked.reasons_ro)) == CONTENT_REFUSAL
    assert refusal_kind("LOCAL.STILL_GATE", "; ".join(plain.reasons_ro)) == TECHNICAL_REFUSAL
    assert NADIA[:40] in "; ".join(checked.reasons_ro)


# -------------------------------------------------------------------- 3. the vision look


def test_the_report_must_answer_every_item_and_ignores_fixes_nobody_asked_for():
    from pydantic import ValidationError

    entry = json.loads(_answer())["stills"][0]
    # Nothing asked: a volunteered `fixes`, even a malformed one, is not read.
    plain = still_report_schema(0)
    assert (
        plain.model_validate({"stills": [{**entry, "fixes": [{"note": "?"}]}]}).stills[0].fixes
        == []
    )
    asked = still_report_schema(2)
    with pytest.raises(ValidationError):
        asked.model_validate({"stills": [entry]})
    # The still's own entry, read alone (the parser tries every «{»), is not an empty answer.
    with pytest.raises(ValidationError):
        asked.model_validate(entry)
    with pytest.raises(ValidationError):
        asked.model_validate({"stills": [{**entry, "fixes": [{"item": 1, "status": "gone"}]}]})
    with pytest.raises(ValidationError):  # a word that is not a status is not an answer
        asked.model_validate(
            {
                "stills": [
                    {
                        **entry,
                        "fixes": [
                            {"item": 1, "status": "fixed", "seen": "ok"},
                            {"item": 2, "status": "gone"},
                        ],
                    }
                ]
            }
        )
    read = asked.model_validate(
        {
            "stills": [
                {
                    **entry,
                    "fixes": [
                        {"item": 1, "status": "Persists", "seen": "two women"},
                        # «seen» may be left out when the mistake is gone (finding 8).
                        {"item": 2, "status": "gone"},
                    ],
                }
            ]
        }
    )
    assert [f.status for f in read.stills[0].fixes] == ["persists", "gone"]


def test_an_answer_says_what_it_sees_unless_the_mistake_is_gone():
    from pydantic import ValidationError

    assert FixAnswer(item=1, status="gone").seen == ""
    for status in ("minor", "persists"):
        with pytest.raises(ValidationError):
            FixAnswer(item=1, status=status)
    # The first version's answer reads as before; StillFix is the same answer.
    assert FixAnswer.model_validate({"item": 1, "fixed": False, "seen": "x"}).status == "persists"
    assert FixAnswer.model_validate({"item": 1, "fixed": True}).fixed is True
    assert StillFix is FixAnswer


def test_a_plain_report_whose_entry_leaves_a_question_out_is_not_an_empty_answer():
    """Finding 8, the older defect: `read_structured` tried the entry alone as a report, found
    no `stills` and read an empty report — «no answer for this scene» — so the model was never
    asked again. A report must name its stills; a complete answer reads as before."""
    from app.agents.identity import read_structured

    entry = json.loads(_answer())["stills"][0]
    mute = {key: value for key, value in entry.items() if key != "one_picture"}
    parsed, why = read_structured(json.dumps({"stills": [mute]}), StillJudgeReport)
    assert parsed is None and why
    complete, _ = read_structured(_answer(), StillJudgeReport)
    assert complete is not None and complete.stills[0].scene == 4
    # The clip's report reads the same way.
    from app.media.picture_qc import ClipJudgeReport

    clip = {
        "scene": 1,
        "faces_visible": False,
        "readable_text": False,
        "matches_plan": True,
        "look_ok": True,
        "technical_ok": True,
        "same_shot": True,
        "bible_violations": "none",
        "verdict": "keep",
        "reason": "x",
    }
    parsed, why = read_structured(json.dumps({"clips": [clip]}), ClipJudgeReport)
    assert parsed is None and why
    parsed, _ = read_structured(
        json.dumps({"clips": [{**clip, "one_picture": True}]}), ClipJudgeReport
    )
    assert parsed is not None and parsed.clips[0].one_picture is True


def _answer(scene: int = 4, fixes=None) -> str:
    entry = {
        "scene": scene,
        "faces_visible": False,
        "readable_text": False,
        "one_picture": True,
        "matches_plan": True,
        "shows_scene": True,
        "look_ok": True,
        "technical_ok": True,
        "bible_violations": "none",
        "verdict": "buy_motion",
        "reason": "Nadia at her ledger desk",
    }
    if fixes is not None:
        entry["fixes"] = fixes
    return json.dumps({"stills": [entry]})


def _template_versions(engine, task: str = STILL_TASK) -> list[str]:
    with Session(engine) as session:
        return [
            run.prompt_template_version
            for run in session.scalars(
                select(AgentRun).where(AgentRun.task_type == task).order_by(AgentRun.started_at)
            )
        ]


@needs_ffmpeg
def test_the_look_is_shown_each_finding_and_its_answer_quotes_the_studios_words(engine, staffed):
    from app.media.picture_qc import judge_still
    from test_picture_qc import NEPAL_STILL, give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    seen = "two women facing each other across the ledger"
    registry, model = registry_with(
        staffed,
        lambda prompt: _answer(
            fixes=[{"item": 1, "finding": "the two women", "status": "persists", "seen": seen}]
        ),
    )
    plan = plan_for(must_fix=[item()])

    judged = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))

    assert judged.status == "MEASURED" and len(model.calls) == 1
    (answered,) = judged.verdict.fixes
    assert (answered.item, answered.finding, answered.status, answered.seen) == (
        1,
        NADIA,
        "persists",
        seen,
    )
    prompt = model.calls[0]["prompt"]
    assert "must_fix" in prompt and NADIA in prompt and NADIA_FIX in prompt
    # Gone, minor or persists; the correction is guidance; never «even in part».
    assert '"gone" | "minor" | "persists"' in prompt and "`expected` is guidance" in prompt
    assert "even in part" not in prompt
    assert _template_versions(engine) == [STILL_FIX_TEMPLATE_VERSION]
    report = decide(NEPAL_STILL, plan, [], judged, environment="TEST")
    assert report.decision == "BLOCKED" and "finding_persists" in report.violations


@needs_ffmpeg
def test_a_look_that_leaves_a_finding_unanswered_is_asked_again_then_not_run(engine, staffed):
    from app.media.picture_qc import judge_still
    from test_picture_qc import NEPAL_STILL, give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    plan = plan_for(must_fix=[item()])

    registry, model = registry_with(staffed, lambda prompt: _answer())
    mute = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))
    assert len(model.calls) == 2, "the answer without `fixes` is refused and asked again"
    assert mute.status == "NOT_RUN" and "nu a fost privită" in mute.detail_ro

    answers = iter([_answer(), _answer(fixes=[{"item": 1, "status": "gone"}])])
    registry, model = registry_with(staffed, lambda prompt: next(answers))
    second = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))
    assert len(model.calls) == 2 and second.status == "MEASURED"
    assert [(f.finding, f.status) for f in second.verdict.fixes] == [(NADIA, "gone")]


@needs_ffmpeg
def test_a_plain_look_whose_entry_leaves_a_question_out_is_asked_again(engine, staffed):
    from app.media.picture_qc import judge_still
    from test_picture_qc import NEPAL_STILL, give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    entry = json.loads(_answer())["stills"][0]
    mute = json.dumps({"stills": [{k: v for k, v in entry.items() if k != "shows_scene"}]})
    answers = iter([mute, _answer()])
    registry, model = registry_with(staffed, lambda prompt: next(answers))

    judged = judge_still(engine, registry, NEPAL_STILL, plan_for(), str(uuid4()))

    assert len(model.calls) == 2 and judged.status == "MEASURED"


@needs_ffmpeg
def test_without_a_rewrite_the_look_carries_nothing_of_the_fix_check(engine, staffed):
    from app.factual.sanitizer import wrap_in_inert_boundary
    from app.media.picture_qc import _STILL_INSTRUCTIONS, judge_still
    from test_picture_qc import NEPAL_STILL, give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    # A model that volunteers `fixes` nobody asked for is read as before.
    registry, model = registry_with(staffed, lambda p: _answer(fixes=[{"item": "x"}]))
    plan = plan_for()

    judged = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))

    assert judged.status == "MEASURED" and judged.verdict.fixes == []
    v2_shown = {
        "scene": plan.scene,
        "plan": plan.still_prompt,
        "scene_picture": plan.scene_picture,
        "narration": plan.narration,
        "purpose": plan.purpose,
        "look": plan.look_block,
        "camera_move": plan.camera_move,
        "faces_forbidden": plan.faces_forbidden,
        "bible_rules": list(plan.bible_rules),
    }
    assert model.calls[0]["prompt"] == _STILL_INSTRUCTIONS.format(
        scene=plan.scene
    ) + wrap_in_inert_boundary(json.dumps(v2_shown, ensure_ascii=False)[:8000], "the-still")
    assert _template_versions(engine) == [STILL_TEMPLATE_VERSION]
    prompt = model.calls[0]["prompt"]
    assert "must_fix" not in prompt and "fixes" not in prompt
    # The script's line is a movement or several moments; the still is its first moment.
    assert "the still is its first moment" in prompt


# ------------------------------------------------- 4. every still bought after the rewrite


class FixJudge:
    """The vision model, faked: answers every item it is asked about as ``status(look, plan)``
    says (gone, minor, persists), the plan as ``on_plan(look, plan)``, and remembers each plan
    it was shown. ``look`` counts the looks at the plan's scene."""

    def __init__(self, status=lambda look, plan: "gone", on_plan=lambda look, plan: True):
        self.plans: list[StillPlan] = []
        self.status = status
        self.on_plan = on_plan
        self.per_scene: dict[int, int] = {}

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        self.plans.append(plan)
        look = self.per_scene[plan.scene] = self.per_scene.get(plan.scene, 0) + 1
        status = self.status(look, plan)
        return verdict(
            plan.scene,
            fixes=[
                fix(number, status, "Nadia alone" if status == "gone" else "two women face to face")
                for number in range(1, len(plan.must_fix) + 1)
            ],
            matches_plan=self.on_plan(look, plan),
            reason="the scene as planned",
        )


def new_pictures_for(scene: int):
    """The vendor's pictures: a new pair of files each time the scene is asked (one file of one
    prompt is one row, `assembler.record_take`), the two nobody-pictures for the others."""
    asked: list[int] = []
    pairs = [("scene_03", "scene_04"), ("scene_05", "scene_02"), ("scene_06", "scene_01")]

    def pictures(prompt, call):
        if SUBJECTS[scene] not in prompt:
            return list(NO_FACE)
        asked.append(call)
        first, second = pairs[(len(asked) - 1) % len(pairs)]
        return [FIXTURES / f"{first}.jpg", FIXTURES / f"{second}.jpg"]

    return pictures


@pytest.fixture
def lessons(monkeypatch):
    """The prompt writer's lesson book (group FA's `confirm_prompt_lessons`,
    `withdraw_prompt_lessons`), faked: what was confirmed and withdrawn, by source."""
    seen: dict[str, list] = {"confirmed": [], "withdrawn": []}

    def confirm(session, source_ids):
        seen["confirmed"].append(list(source_ids))
        return len(source_ids)

    def withdraw(session, source_ids, reason):
        seen["withdrawn"].append((list(source_ids), reason))
        return len(source_ids)

    monkeypatch.setattr(prompt_agent, "confirm_prompt_lessons", confirm, raising=False)
    monkeypatch.setattr(prompt_agent, "withdraw_prompt_lessons", withdraw, raising=False)
    return seen


def test_a_still_that_repeats_the_mistake_on_its_plan_is_not_bought_again(
    engine, tmp_path, lessons
):
    """Finding 3: the first pair of the rewritten scene shows its plan and the two women again:
    nothing more is bought on those words (until 2026-10-12 two re-rolls followed, four paid
    stills of the same mistake); the scene goes back to her ladder; the review's lessons are
    withdrawn (finding 9). No clip is ever bought here."""
    storyboard_id = a_film(engine, tmp_path)
    review_run = rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    judge = FixJudge(status=lambda look, plan: "persists")
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, judge)

    must = [plan for plan in judge.plans if plan.must_fix]
    assert must and all(plan.scene == 2 for plan in must)
    assert all(said(plan.must_fix) == [(NADIA, NADIA_FIX)] for plan in must)
    scene_2 = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    assert len(scene_2) == 1, "one pair, no re-roll on the words that did not correct it"
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert entry["status"] == "NEEDS_OWNER" and entry["rewrite"] is True
    assert entry["rerolls"] == 0 and entry["must_fix"] == [NADIA]
    assert "nu au corectat-o" in entry["reason"] and "Directoarea le rescrie" in entry["reason"]
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert len(rows) == 2 and all(t.status == "REJECTED" for t in rows)
    assert all(t.failure_detail.startswith(REWRITE_PHRASE) for t in rows)
    assert all("imaginea repetă greșeala" in t.failure_detail for t in rows)
    assert all(refusal_kind(t.failure_code, t.failure_detail) == CONTENT_REFUSAL for t in rows)
    assert lessons["withdrawn"] and lessons["withdrawn"][0][0] == [review_run]
    assert lessons["confirmed"] == []
    assert all(
        e["status"] == "APPROVED"
        for e in result["scenes"]
        if e["scene_index"] != 2 and e["scene_kind"] == "LIVE"
    )


def test_a_still_that_also_missed_its_plan_is_bought_once_more_and_then_fixed(
    engine, tmp_path, lessons
):
    """Finding 3, the other side, and finding 9: a pair that missed its plan as well gets the
    one re-roll; the re-roll that shows every item gone is approved, and the review's lessons
    are confirmed — the finding lives on the still's layer, so the still closes it on both
    (round 3, finding 7: a finding the clip must also show is confirmed only by the clip)."""
    storyboard_id = a_film(engine, tmp_path)
    review_run = rewritten(
        engine,
        storyboard_id,
        2,
        findings=[
            {"finding": NADIA, "treated": True, "by": NADIA_FIX, "why_not": "", "layer": "still"}
        ],
    )
    judge = FixJudge(
        status=lambda look, plan: "persists" if look <= 2 else "gone",
        on_plan=lambda look, plan: look > 2,
    )
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, judge)

    scene_2 = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    assert len(scene_2) == 2, "one pair refused, one re-roll"
    assert POSITIVE_WORDS["finding_persists"] in scene_2[1]["prompt"]
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert entry["status"] == "APPROVED" and entry["rerolls"] == 1
    # Not withdrawn before the re-roll that fixed it; confirmed by it.
    assert lessons["withdrawn"] == [] and lessons["confirmed"] == [[review_run]]
    # The still approved after the rewrite was checked for it: nothing is open on the still.
    assert open_for(engine, storyboard_id, 2) == []


def test_a_minor_trace_approves_the_still_and_is_written_on_it(engine, tmp_path, lessons):
    """Finding 2: Sarah's shoulder at the frame's edge, as the correction asked, is a minor
    trace of «two women»: the still is approved, the trace is said on the take (for the film's
    QC) and on the step's entry; the lessons are not confirmed by a trace."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    judge = FixJudge(status=lambda look, plan: "minor")

    result = approved_run(
        engine, storyboard_id, tmp_path, SpyStills(pictures=new_pictures_for(2)), judge
    )

    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert entry["status"] == "APPROVED" and entry["rerolls"] == 0
    assert entry["minor_defects"] == [{"finding": NADIA, "seen": "two women face to face"}]
    with Session(engine) as session:
        note = fix_check.take_note(session, entry["take_id"])
    assert note["minor"] == entry["minor_defects"] and note["approved_by"] == "still_gate"
    assert lessons["confirmed"] == [] and lessons["withdrawn"] == []


def test_the_runpod_rounds_check_the_rewritten_scene_and_stop_on_words_that_failed(
    engine,
    tmp_path,
    fake_session,  # noqa: F811
):
    """RunPod Serverless buys in rounds (`stills_stage._StillRounds`): the rewritten scene's
    plan carries its findings; a round whose every picture shows its plan and the mistake
    again ends the scene for her ladder — no second round on the same words — and the others
    go on."""
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_runpod_batch import PictureCloud, adapter, stills_table
    from test_stills_stage import faces_in

    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    drawn: list[int] = []

    def picture(prompt):
        # Every picture its own bytes (a byte after the JPEG's end), nobody in it.
        drawn.append(len(drawn))
        return NO_FACE[len(drawn) % 2].read_bytes() + bytes([len(drawn)])

    made = adapter(engine, tmp_path, PictureCloud(picture))
    table = stills_table()
    judge = FixJudge(status=lambda look, plan: "persists")

    def go():
        return run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=stills_plan(engine, storyboard_id, model_id=made.model, table=table)[
                "plan_hash"
            ],
            image_adapter=made,
            registry=None,
            judge=judge,
            storage_root=tmp_path / "media",
            table=table,
            face_counter=faces_in(),
            measure=("faces",),
        )

    with pytest.raises(StillsStageRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[2]["status"] == "NEEDS_OWNER" and by_scene[2]["rerolls"] == 0
    assert by_scene[2]["rewrite"] is True and by_scene[2]["must_fix"] == [NADIA]
    assert all(by_scene[n]["status"] == "APPROVED" for n in (1, 3, 4))
    looked_at_two = [plan for plan in judge.plans if plan.scene == 2]
    assert len(looked_at_two) == 2, "one round of two"
    assert all(said(plan.must_fix) == [(NADIA, NADIA_FIX)] for plan in looked_at_two)
    assert all(plan.must_fix == () for plan in judge.plans if plan.scene != 2)
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert rows and all(t.status == "REJECTED" for t in rows)
    assert all((t.failure_detail or "").startswith(REWRITE_PHRASE) for t in rows)
    assert all("imaginea repetă greșeala" in (t.failure_detail or "") for t in rows)
    # The scene's hold says her ladder rewrites the words (round 3, finding 3).
    with Session(engine) as session:
        holds = [
            event.payload
            for event in session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == "media.still_needs_owner",
                    DomainEvent.aggregate_id == storyboard_id,
                )
            )
            if event.payload.get("scene_number") == 2
        ]
    assert holds and holds[-1]["rewrite"] is True


@pytest.mark.parametrize("status", ["persists", "gone"], ids=["repeats-the-mistake", "fixed-it"])
def test_a_still_redo_is_checked_for_what_its_rewrite_answered(engine, tmp_path, status):
    """The paid still redo the Director decided after the film failed QC (the per-request
    buyer, `assembler._redo_still`): every candidate is checked for her rewrite's findings. A
    pair that shows its plan and the two women again is refused and nothing more is bought on
    those words; one that fixed them is approved, and nothing is open on the still any more."""
    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from test_approvals import answer
    from test_film_costing import a_film as costed_film
    from test_stills_stage import faces_in

    storyboard_id = costed_film(engine, tmp_path, scenes=4)
    before = {t.id for t in takes(engine, storyboard_id)}
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], film=[NADIA])
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)
    judge = FixJudge(status=lambda look, plan: status)

    def run():
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=3,
            plan_hash=plan["plan_hash"],
            image_adapter=images,
            judge=judge,
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    with pytest.raises(SceneRedoRefused) as asked:
        run()
    answer(engine, asked.value.approval_id, "APPROVED")
    result = run()

    assert judge.plans and all(said(p.must_fix) == [(NADIA, NADIA_FIX)] for p in judge.plans)
    new = [t for t in takes(engine, storyboard_id) if t.id not in before]
    assert new and all(t.scene_number == 3 and t.kind == "still" for t in new)
    if status == "gone":
        assert result["still"]["status"] == "APPROVED"
        assert sorted(t.status for t in new) == ["APPROVED", "PAID"]
        assert open_for(engine, storyboard_id, 3) == []
        return
    assert result["still"]["status"] == "NEEDS_OWNER" and result["still"]["rewrite"] is True
    assert len(images.asked) == 1, "one pair, no re-roll on the words that did not correct it"
    assert len(new) == 2 and all(t.status == "REJECTED" for t in new)
    assert all((t.failure_detail or "").startswith(REWRITE_PHRASE) for t in new)
    assert all("imaginea repetă greșeala" in (t.failure_detail or "") for t in new)
    # No clip was bought on a still that repeats the mistake.
    assert not [t for t in takes(engine, storyboard_id) if t.kind in ("motion", "test_shot")]


# ------------------------------------------------------- 5. the scene the gate is shown


def test_a_factual_scene_shown_is_the_writers_line_not_the_compiled_prompt(engine, tmp_path):
    """2026-10-12, read on the database copy: visual_prompt equals the compiled still prompt
    (1c038a99 scene 5, 00000160 scene 1, f06808c9 scene 4), so shows_scene could only repeat
    matches_plan. The writer's line is kept on the package as ``writer_visual``."""
    storyboard_id = a_film(engine, tmp_path)
    line = "Return to the dark detector cavern from the opening shot, points of light on the rings."
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        )
        row.prompt_json = {**dict(row.prompt_json or {}), "writer_visual": line}

    _bible, scenes = stills_stage._read_scenes(engine, storyboard_id)
    by_index = {scene.index: scene for scene in scenes}

    assert by_index[1].picture == line
    assert by_index[1].words != line  # the plan is still the compiled prompt
    # No writer's line, and visual_prompt is the still prompt itself: no second copy of the
    # plan is shown as «the scene» (the gate then judges by the plan, as it says).
    assert by_index[2].picture == ""
    plan = stills_stage._still_plan(by_index[1], faces_forbidden=True, rules=())
    assert plan.scene_picture == line and plan.purpose == by_index[1].purpose
    assert plan.narration == by_index[1].narration


def test_a_serial_scene_shown_is_the_composed_beat_not_the_writers_line(engine, monkeypatch):
    """Finding 4, on a real serial storyboard (built as tests/test_serial_ladder.py builds it):
    f06808c9 scene 1's writer's line said «Marcus alone at his desk» while the composed beat put
    Marcus and Sarah in frame. The gate (and clip QC) are shown the beat: the room, who is in
    frame, the first moment of the action — never the writer's line."""
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels
    from test_serial_ladder import described_board

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    board_id = described_board(engine, monkeypatch)
    alone = "Kael alone at his desk, nobody else in the room, staring at a blank wall."
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board_id, StoryboardScene.scene_index == 2
            )
        )
        package = dict(row.prompt_json or {})
        assert package.get("in_frame"), "the composer put the beat's people in frame"
        package["writer_visual"] = alone
        row.prompt_json = package
        scene_row = {
            "scene_index": 2,
            "prompt_json": package,
            "visual_prompt": row.visual_prompt,
            "voiceover_segment": row.voiceover_segment,
        }
        names = [
            prompt_agent._short_name(person["name"])
            for person in package["in_frame"]
            if isinstance(person, dict) and person.get("name")
        ]
        location = str(package.get("location") or "")

    _bible, scenes = stills_stage._read_scenes(engine, board_id)
    picture = next(scene for scene in scenes if scene.index == 2).picture

    assert alone not in picture and "alone" not in picture
    assert location and location.rstrip(". ") in picture
    assert all(name in picture for name in names)
    assert "In frame:" in picture
    # The first moment of the action, not its chain («then lays the pen flat» is the clip's).
    assert "then" not in picture.lower().split("in frame:")[1]
    # The clip's plan shows the same beat.
    assert _clip_plan(scene_row, {}).scene_picture == picture


def test_the_fixture_answers_without_fixes_are_unchanged_for_a_scene_never_rewritten(
    engine, tmp_path
):
    """The stills step's other fakes (verdicts built in code, no `fixes`) still pass a scene
    with nothing open: the fix check costs nothing where nothing was rewritten."""
    from test_stills_stage import SpyJudge

    storyboard_id = a_film(engine, tmp_path)
    result = approved_run(engine, storyboard_id, tmp_path, SpyStills(), SpyJudge())
    assert all(
        entry["status"] == "APPROVED" and "must_fix" not in entry
        for entry in result["scenes"]
        if entry["scene_kind"] == "LIVE"
    )


@pytest.fixture
def staffed(engine):
    from test_picture_qc import staff

    return staff(engine)


def test_no_open_finding_is_read_for_a_film_without_events(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    _bible, scenes = stills_stage._read_scenes(engine, storyboard_id)
    assert all(scene.must_fix == () for scene in scenes)


# --------------------------------------------- 6. the movement's findings, on the clip


def _clip_judgement(
    scene: int, fixes=(), *, matches_plan: bool = True, said: str | None = None
) -> ClipJudgement:
    return ClipJudgement(
        status="MEASURED",
        verdict=ClipVerdict(
            scene=scene,
            faces_visible=False,
            readable_text=False,
            matches_plan=matches_plan,
            look_ok=True,
            technical_ok=True,
            same_shot=True,
            one_picture=True,
            bible_violations="none",
            verdict=said or ("keep" if matches_plan else "regenerate_motion"),
            reason="Marcus and Sarah at the desk",
            fixes=list(fixes),
        ),
        detail_ro="",
        run_id="run",
        looked_by="VideoEditor",
        image_width=1080,
        frames=3,
    )


@pytest.fixture(scope="module")
def static_clip(tmp_path_factory):
    """A 2-second 1080x1920 clip of one still (the shape the vendor delivers)."""
    import subprocess

    if FFMPEG is None:
        pytest.skip("ffmpeg is not installed")
    work = tmp_path_factory.mktemp("fix_clip")
    out = work / "static.mp4"
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-loop",
            "1",
            "-i",
            str(NO_FACE[0]),
            "-vf",
            "scale=1080:1920,fps=24",
            "-frames:v",
            "48",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],  # fmt: skip
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return out


@needs_ffmpeg
@pytest.mark.parametrize("status", ["persists", "minor", "gone"])
def test_clip_qc_refuses_a_persisting_motion_finding_back_to_the_motion(
    static_clip, tmp_path, status
):
    """Finding 5: the clip is asked the movement's items; one that persists fails it — back to
    the motion's words, never the still — and a clip that showed its plan is not retried on
    the same words; a minor trace is a warning; gone passes."""
    from app.media import qc

    must_fix = [item(ENDING, ENDING_FIX, layer="motion")]
    seen = "Marcus and Sarah in profile, facing each other"

    def judge(frames):
        return _clip_judgement(1, [FixAnswer(item=1, finding=ENDING, status=status, seen=seen)])

    report = qc.check_clip(
        static_clip,
        scene=1,
        camera_move="static",
        faces_forbidden=False,
        environment="TEST",
        judge=judge,
        work_dir=tmp_path / "frames",
        must_fix=must_fix,
    )

    assert report.fixes[0]["status"] == status and report.back_to_still is False
    assert report.measured["picture"]["fixes"][0]["status"] == status
    if status == "gone":
        assert report.check("picture").status == "PASSED"
        return
    if status == "minor":
        assert report.check("picture").status == "PASSED"
        assert any("urmă mică" in w and seen in w for w in report.warnings_ro)
        return
    picture = report.check("picture")
    assert picture.status == "FAILED" and "repetă greșeala" in picture.detail_ro
    assert "cuvintele «The shot ends on Marcus and Sarah" in picture.detail_ro
    decision = qc.clip_retry_decision(
        report, seed=7, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert decision.action == "ESCALATE" and decision.seed is None
    assert "nu au corectat-o" in decision.reason_ro
    # Its words are rewritten by her ladder: a clip QC refusal is a content refusal.
    assert refusal_kind("QC.CLIP", picture.detail_ro) == CONTENT_REFUSAL


@needs_ffmpeg
def test_a_clip_that_also_missed_its_plan_gets_the_one_retry(static_clip, tmp_path):
    from app.media import qc

    report = qc.check_clip(
        static_clip,
        scene=1,
        camera_move="static",
        faces_forbidden=False,
        environment="TEST",
        judge=lambda frames: _clip_judgement(
            1,
            [FixAnswer(item=1, finding=ENDING, status="persists", seen="profile")],
            matches_plan=False,
        ),
        work_dir=tmp_path / "frames",
        must_fix=[item(ENDING, ENDING_FIX, layer="motion")],
    )
    decision = qc.clip_retry_decision(
        report, seed=7, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert decision.action == "RETRY" and decision.seed == 8


@needs_ffmpeg
def test_judge_clip_asks_the_movements_items_and_quotes_the_studios_words(engine, staffed):
    from app.media.picture_qc import judge_clip
    from test_picture_qc import give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    clip_entry = {
        "scene": 3,
        "faces_visible": False,
        "readable_text": False,
        "matches_plan": True,
        "look_ok": True,
        "technical_ok": True,
        "same_shot": True,
        "one_picture": True,
        "bible_violations": "none",
        "verdict": "regenerate_motion",
        "reason": "the clip ends in profile",
    }
    asked = {**clip_entry}
    answered = {
        **clip_entry,
        "fixes": [{"item": 1, "finding": "profile", "status": "persists", "seen": "in profile"}],
    }
    answers = iter([json.dumps({"clips": [asked]}), json.dumps({"clips": [answered]})])
    registry, model = registry_with(staffed, lambda prompt: next(answers))
    plan = StillPlan(
        scene=3,
        still_prompt="Marcus and Sarah at the desk, both facing the viewer.",
        camera_move="slow push-in",
        faces_forbidden=False,
        scene_picture="Ground floor office. In frame: Marcus, Sarah. Marcus opens both hands.",
        narration="We start again.",
        must_fix=(item(ENDING, ENDING_FIX, layer="motion"),),
    )
    frames = [NO_FACE[0], NO_FACE[1], NO_FACE[0]]

    judged = judge_clip(engine, registry, frames, plan, str(uuid4()), motion_prompt="Push in.")

    assert len(model.calls) == 2, "the answer without `fixes` is refused and asked again"
    assert judged.status == "MEASURED"
    (fixed,) = judged.verdict.fixes
    assert (fixed.finding, fixed.status, fixed.seen) == (ENDING, "persists", "in profile")
    prompt = model.calls[0]["prompt"]
    assert "must_fix" in prompt and ENDING in prompt and ENDING_FIX in prompt
    assert "In frame: Marcus, Sarah" in prompt
    assert _template_versions(engine, CLIP_TASK)[0] == CLIP_FIX_TEMPLATE_VERSION


def test_the_clip_plan_carries_the_movements_items_and_the_writers_line():
    package = {
        "still_prompt": "Compiled still prompt.",
        "writer_visual": "Return to the dark detector cavern.",
        "camera_move": "slow push-in",
    }
    scene = {"scene_index": 5, "prompt_json": package, "visual_prompt": "Compiled still prompt."}
    items = [item(ENDING, ENDING_FIX, layer="motion")]

    plan = _clip_plan(scene, {}, must_fix=items)

    assert plan.scene_picture == "Return to the dark detector cavern."
    assert plan.must_fix == tuple(items)
    assert _clip_plan(scene, {}).must_fix == ()


# ------------------------------------- 7. the Director looks before anything is bought again


class Looks:
    """Her second look, faked (`fix_check.director_second_look`): answers ``answer`` and keeps
    every question."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.asked: list[dict] = []

    def __call__(self, engine, registry, **kwargs):
        self.asked.append(kwargs)
        return dict(self.answer)


HER = {
    "OVERTURNED": {
        "verdict": "OVERTURNED",
        "severity": "minor",
        "redo": False,
        "reason_ro": "Imaginea arată valea cerută; refuzul e prea strict.",
        "run_id": "look-1",
    },
    "CONFIRMED": {
        "verdict": "CONFIRMED",
        "severity": "serious",
        "redo": True,
        "reason_ro": "Imaginea arată alt loc decât cere scena.",
        "run_id": "look-2",
    },
    "UNAVAILABLE": {
        "verdict": "UNAVAILABLE",
        "severity": "none",
        "redo": True,
        "reason_ro": "",
        "run_id": None,
    },
}


class OffPlanFirst:
    """The vision model, faked: the first pair of scene 2 does not match its plan (a reading her
    look may overturn), or shows lettering (a hard limit), or has warped artefacts (a technical
    fault, ``technical``); everything else is right."""

    def __init__(self, *, lettering: bool = False, technical: bool = False):
        self.lettering = lettering
        self.technical = technical
        self.looked: dict[int, int] = {}

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        look = self.looked[plan.scene] = self.looked.get(plan.scene, 0) + 1
        wrong = plan.scene == 2 and look <= 2
        return verdict(
            plan.scene,
            matches_plan=not wrong or self.lettering or self.technical,
            readable_text=wrong and self.lettering,
            technical_ok=not (wrong and self.technical),
            verdict="regenerate_still" if wrong else "buy_motion",
            reason="another valley" if wrong else "the scene as planned",
        )


@pytest.mark.parametrize("her", ["OVERTURNED", "CONFIRMED", "UNAVAILABLE"])
def test_the_director_looks_before_a_still_is_bought_again(engine, tmp_path, monkeypatch, her):
    """Finding 10, the Owner's rule: before the re-roll is bought, she looks at the refused
    pair (free). OVERTURNED (minor): her look approves a candidate and nothing more is bought;
    CONFIRMED: the re-roll is bought, her reason kept with it; UNAVAILABLE: as before."""
    looks = Looks(HER[her])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, OffPlanFirst())

    scene_2 = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert looks.asked and all(ask["kind"] == "still" for ask in looks.asked)
    assert all(
        ask["scene_index"] == 2 and ask["storyboard_id"] == storyboard_id for ask in looks.asked
    )
    assert all(len(ask["images"]) == 1 and ask["take_ids"] for ask in looks.asked)
    assert all(any("nu arată ce cere planul" in r for r in ask["refusal"]) for ask in looks.asked)
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    if her == "OVERTURNED":
        assert len(scene_2) == 1, "her look kept a picture: no re-roll was bought"
        assert len(looks.asked) == 1
        assert entry["status"] == "APPROVED" and entry["approved_by"] == "director_look"
        assert entry["director_look"]["reason_ro"] == HER[her]["reason_ro"]
        (kept,) = [t for t in rows if t.status == "APPROVED"]
        assert kept.approved_by == "director_look" and kept.failure_detail is None
        assert kept.id == entry["take_id"] == looks.asked[0]["take_ids"][0]
        with Session(engine) as session:
            note = fix_check.take_note(session, kept.id)
        assert note["approved_by"] == "director_look"
        assert note["director_look"]["verdict"] == "OVERTURNED"
        return
    assert len(looks.asked) == 2, "she looked at both refused candidates"
    if her == "CONFIRMED":
        # Round 3, finding 4: she confirmed that the picture is not what the words should give
        # (its plan): no seed is bought blind on them, the words go back to her ladder.
        assert len(scene_2) == 1, "no re-roll on words she confirmed give the wrong picture"
        assert entry["status"] == "NEEDS_OWNER" and entry["rewrite"] is True
        assert entry["director_confirmed"] == [HER[her]["reason_ro"]] * 2
        assert REWRITE_PHRASE.lower() in entry["reason"].lower()
        assert all(t.status == "REJECTED" for t in rows)
        assert all(t.failure_detail.startswith(REWRITE_PHRASE) for t in rows)
        assert all(refusal_kind(t.failure_code, t.failure_detail) == CONTENT_REFUSAL for t in rows)
        return
    assert len(scene_2) == 2, "the re-roll was bought"
    assert entry["status"] == "APPROVED" and entry.get("approved_by") is None
    assert "director_confirmed" not in entry


def test_a_confirmed_technical_refusal_is_rerolled_with_her_reason(engine, tmp_path, monkeypatch):
    """Round 3, finding 4, the other side: a refusal of one picture's technique (warped hands,
    artefacts) that she confirms is another seed's to answer — the re-roll is bought, her reason
    kept with it; the words are not sent back."""
    looks = Looks(HER["CONFIRMED"])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, OffPlanFirst(technical=True))

    scene_2 = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert len(looks.asked) == 2 and len(scene_2) == 2, "the re-roll was bought"
    assert entry["status"] == "APPROVED" and entry["rerolls"] == 1
    assert entry["director_confirmed"] == [HER["CONFIRMED"]["reason_ro"]] * 2
    assert "rewrite" not in entry


@pytest.mark.parametrize(
    ("her", "technical"),
    [("OVERTURNED", False), ("CONFIRMED", False), ("CONFIRMED", True)],
    ids=["overturned", "confirmed-content", "confirmed-technical"],
)
def test_the_director_looks_before_a_runpod_round_is_bought_again(
    engine,
    tmp_path,
    monkeypatch,
    fake_session,  # noqa: F811
    her,
    technical,
):
    """The same look in the RunPod rounds (`_StillRounds`): OVERTURNED, scene 2's second
    round is never sent; CONFIRMED on its plan (content), neither — the words go back to her
    ladder (round 3, finding 4); CONFIRMED on a technical fault, it is, with her reason kept on
    the scene."""
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_runpod_batch import PictureCloud, adapter, stills_table
    from test_stills_stage import faces_in

    looks = Looks(HER[her])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    drawn: list[str] = []

    def picture(prompt):
        drawn.append(prompt)
        return NO_FACE[len(drawn) % 2].read_bytes() + bytes([len(drawn)])

    made = adapter(engine, tmp_path, PictureCloud(picture))
    table = stills_table()
    judge = OffPlanFirst(technical=technical)

    def go():
        return run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=stills_plan(engine, storyboard_id, model_id=made.model, table=table)[
                "plan_hash"
            ],
            image_adapter=made,
            registry=None,
            judge=judge,
            storage_root=tmp_path / "media",
            table=table,
            face_counter=faces_in(),
            measure=("faces",),
        )

    with pytest.raises(StillsStageRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    scene_2_pictures = len([p for p in drawn if SUBJECTS[2] in p])
    if her == "OVERTURNED":
        assert scene_2_pictures == 2, "one round of two: her look kept a picture"
        assert by_scene[2]["status"] == "APPROVED"
        assert by_scene[2]["approved_by"] == "director_look" and by_scene[2]["rerolls"] == 0
        return
    if not technical:
        assert scene_2_pictures == 2, "no round bought on words she confirmed are wrong"
        assert by_scene[2]["status"] == "NEEDS_OWNER" and by_scene[2]["rewrite"] is True
        assert by_scene[2]["director_confirmed"] == [HER[her]["reason_ro"]] * 2
        return
    assert scene_2_pictures == 4, "the re-roll round was bought"
    assert by_scene[2]["status"] == "APPROVED" and by_scene[2]["rerolls"] == 1
    assert by_scene[2]["director_confirmed"] == [HER[her]["reason_ro"]] * 2


def test_her_look_never_overturns_the_bibles_hard_limits(engine, tmp_path, monkeypatch):
    looks = Looks(HER["OVERTURNED"])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills(pictures=new_pictures_for(2))

    approved_run(engine, storyboard_id, tmp_path, adapter, OffPlanFirst(lettering=True))

    assert looks.asked == [], "writing in the picture stays the code's refusal"
    assert len([c for c in adapter.asked if SUBJECTS[2] in c["prompt"]]) == 2


def test_who_may_be_overturned():
    plan = plan_for()
    off_plan = decide(NO_FACE[0], plan, [], verdict(matches_plan=False), environment="TEST")
    lettering = decide(NO_FACE[0], plan, [], verdict(readable_text=True), environment="TEST")
    panels = decide(NO_FACE[0], plan, [], verdict(one_picture=False), environment="TEST")
    unseen = decide(
        NO_FACE[0],
        plan,
        [],
        StillJudgement("NOT_RUN", None, "nu a fost privită: x", None, None, None),
        environment="TEST",
    )
    assert may_be_overturned(off_plan)
    assert not may_be_overturned(lettering) and not may_be_overturned(panels)
    assert not may_be_overturned(unseen)


@pytest.mark.parametrize("her", ["NOT_THERE", "OVERTURNED", "CONFIRMED", "UNAVAILABLE"])
def test_the_director_looks_before_a_clip_retry_is_bought(engine, tmp_path, monkeypatch, her):
    """Finding 10, for the clip: before seed + 1 is bought, she looks at the refused clip, which
    clip QC measured as barely moving. OVERTURNED with the defect not in the clip (severity
    none): the clip is kept as hers and nothing more is bought; OVERTURNED as «minor» does not
    keep a measured refusal (round 3 contract) — the retry is bought; CONFIRMED: the retry is
    bought, her reason in its words; UNAVAILABLE: as before."""
    from app.media import fix_check as checks
    from test_clip_qc_wiring import ScriptedCheck, approved, events, shots
    from test_film_costing import Account, Models, SpyVideo
    from test_film_costing import a_film as costed_film

    asked: list[dict] = []

    def look(engine_, registry, **kwargs):
        asked.append(kwargs)
        if her == "NOT_THERE":
            return {**HER["OVERTURNED"], "severity": "none"}
        return dict(HER[her])

    monkeypatch.setattr(checks, "shot_second_look", look)
    storyboard_id = costed_film(engine, tmp_path, scenes=1)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED", "PASSED"),
    )

    (entry,) = summary["scenes"]
    (first_ask,) = asked
    assert first_ask["scene_index"] == 1 and first_ask["storyboard_id"] == storyboard_id
    assert any("nu se mișcă" in text for text in first_ask["refusal"])
    if her == "NOT_THERE":
        assert models.posts() == 1, "her look kept the clip: no retry was bought"
        assert entry["status"] == "PAID" and entry["clip_qc"]["status"] == "ACCEPTED_BY_LOOK"
        (take,) = shots(engine, storyboard_id)
        assert take.status == "PAID" and entry["take_id"] == take.id
        (kept,) = events(engine, CLIP_QC_EVENT, take.id)
        assert kept.payload["verdict"] == "PASSED"
        # Round 3, finding 10: kept by her look, the record says passed too.
        assert kept.payload["passed"] is True
        assert kept.payload["accepted_by"] == "director_look"
        assert kept.payload["director_look"]["reason_ro"] == HER["OVERTURNED"]["reason_ro"]
        with Session(engine) as session:
            note = fix_check.take_note(session, take.id)
        assert note["approved_by"] == "director_look" and note["kind"] == "motion"
        return
    assert models.posts() == 2, "the retry was bought"
    assert entry["clip_qc"]["status"] == "PASSED_ON_RETRY"
    if her == "CONFIRMED":
        assert HER[her]["reason_ro"] in entry["clip_qc"]["reason_ro"]


# ----------------------------------------------------------- 8. her look's own contract


def test_the_second_look_never_raises_and_says_her_verdict_in_the_contracts_words(monkeypatch):
    asks: list[dict] = []
    common = {
        "storyboard_id": "sb",
        "scene_index": 2,
        "kind": "still",
        "images": ["a.png"],
        "refusal": ["nu arată ce cere planul"],
        "correlation_id": "c",
        "take_ids": ["t1"],
    }
    assert fix_check.director_second_look(None, None, **common)["verdict"] == "UNAVAILABLE"
    assert (
        fix_check.director_second_look(None, object(), **{**common, "images": []})["verdict"]
        == "UNAVAILABLE"
    )
    # Not installed yet: the refusal stands, as before her look existed.
    monkeypatch.setitem(sys.modules, "app.media.second_look", None)
    assert fix_check.director_second_look(None, object(), **common)["verdict"] == "UNAVAILABLE"

    def answering(engine, registry, **kwargs):
        asks.append(kwargs)
        return {"verdict": "overturned", "severity": "Minor", "redo": False, "reason_ro": "bun"}

    module = types.ModuleType("app.media.second_look")
    module.second_look = answering
    monkeypatch.setitem(sys.modules, "app.media.second_look", module)
    look = fix_check.director_second_look("engine", object(), **common)
    assert look == {
        "verdict": "OVERTURNED",
        "severity": "minor",
        "redo": False,
        "reason_ro": "bun",
        "run_id": None,
    }
    assert asks == [{**common, "images": ["a.png"], "take_ids": ["t1"]}]
    assert fix_check.look_accepts(look)

    def failing(engine, registry, **kwargs):
        raise RuntimeError("the model is down")

    module.second_look = failing
    assert fix_check.director_second_look("engine", object(), **common)["verdict"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    ("look", "accepts"),
    [
        ({"verdict": "OVERTURNED", "severity": "none", "redo": False}, True),
        ({"verdict": "OVERTURNED", "severity": "minor", "redo": False}, True),
        ({"verdict": "OVERTURNED", "severity": "serious", "redo": True}, False),
        # The shared contract of round 3: a minor defect is never CONFIRMED, and a CONFIRMED
        # look never keeps the picture, whatever severity it carries (defence in depth).
        ({"verdict": "CONFIRMED", "severity": "minor", "redo": False}, False),
        ({"verdict": "CONFIRMED", "severity": "minor", "redo": True}, False),
        ({"verdict": "CONFIRMED", "severity": "serious", "redo": True}, False),
        ({"verdict": "OVERTURNED", "severity": "minor", "redo": True}, False),
        ({"verdict": "UNAVAILABLE", "severity": "none", "redo": True}, False),
        (None, False),
    ],
)
def test_which_of_her_looks_lets_the_picture_stand(look, accepts):
    assert fix_check.look_accepts(look) is accepts


def test_a_measured_refusal_is_kept_only_as_not_in_the_picture():
    """Round 3 contract: what quality control measured (a floor) is dropped only on OVERTURNED
    with severity none — she may say the measure was wrong, never that the defect is small."""
    none = {"verdict": "OVERTURNED", "severity": "none", "redo": False}
    minor = {"verdict": "OVERTURNED", "severity": "minor", "redo": False}
    assert fix_check.look_accepts(none, measured=True)
    assert not fix_check.look_accepts(minor, measured=True)
    assert fix_check.look_accepts(minor, measured=False)


def test_a_rewrite_recorded_now_reads_as_one_event_per_brief(engine, tmp_path):
    """The helper above writes what `scene_rewrite` writes: one rewrite and one brief."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    with Session(engine) as session:
        kinds = [
            event.event_type
            for event in session.scalars(
                select(DomainEvent).where(DomainEvent.aggregate_id == storyboard_id)
            )
            if event.event_type in (SCENE_PROMPTS_REWRITTEN_EVENT, BRIEF_EVENT)
        ]
    assert kinds == [SCENE_PROMPTS_REWRITTEN_EVENT, BRIEF_EVENT]


# ------------------------------------------------- 9. round 3: the review of 5fc7468
#
# 2026-10-12, night: 19.50 USD of RunPod that day, 11.05 on redos; the Owner: «DIRECTOAREA
# ACCEPTĂ DEFECTELE MICI!», «Nu putem permite loopuri pe bani», «Nu să facă aceeași greșeală
# la nesfârșit!». The thirteen confirmed findings of the review of 5fc7468.


def review_entry(qc_text: str, *, treated: bool, severity: str, **more) -> dict:
    """One of her review's findings as the contract keeps it (`scene_rewrite._kept_findings`)."""
    return {
        "qc_text": qc_text,
        "finding": qc_text,
        "treated": treated,
        "by": NADIA_FIX if treated else "",
        "why_not": "" if treated else "a small thing, left as it is",
        "severity": severity,
        "layer": "still",
        **more,
    }


LEDGER = "the ledger on the desk reads as a laptop"


def test_a_minor_finding_she_left_untreated_is_never_checked_and_a_treated_minor_one_only_warns(
    engine, tmp_path
):
    """Finding 1 [high]: an untreated MINOR finding is one she accepted — no item, nothing
    refused or bought for it; an untreated SERIOUS one is checked; a treated minor one seen
    again is a minor trace (a warning), never ``finding_persists``, and withdraws no lesson."""
    storyboard_id = a_film(engine, tmp_path)
    rewritten(
        engine,
        storyboard_id,
        2,
        findings=[
            review_entry(
                "a small sketched mark on the whiteboard", treated=False, severity="minor"
            ),
            review_entry("a stray cup on the desk", treated=False, severity="minor", accepted=True),
            review_entry(NADIA, treated=True, severity="minor"),
            review_entry(LEDGER, treated=False, severity="serious"),
        ],
    )

    items = open_for(engine, storyboard_id, 2)

    assert [i["finding"] for i in items] == [NADIA, LEDGER]
    assert [i["severity"] for i in items] == ["minor", "serious"]
    seen_again = decide(
        NO_FACE[0],
        plan_for(2, must_fix=items),
        [],
        verdict(2, fixes=[fix(1, "persists", "two women"), fix(2, "gone")]),
        environment="TEST",
    )
    assert seen_again.decision == "PASSED" and "finding_persists" not in seen_again.violations
    assert seen_again.fixes[0]["status"] == "minor"
    assert seen_again.minor == ({"finding": NADIA, "seen": "two women"},)
    with Session(engine) as session:
        assert fix_check.withdraw_lessons(session, [list(seen_again.fixes)]) == []
    # The serious one seen again still refuses.
    ledger = decide(
        NO_FACE[0],
        plan_for(2, must_fix=items),
        [],
        verdict(2, fixes=[fix(1, "gone"), fix(2, "persists", "a laptop")]),
        environment="TEST",
    )
    assert ledger.decision == "BLOCKED" and "finding_persists" in ledger.violations


def test_the_content_phrase_comes_first_whatever_else_refused_the_still():
    """Finding 2: the fix check's refusal, then the look's readings, then the local checks: the
    content phrase survives the take's 500 characters, so the ladder rewrites the words."""
    from app.media.still_gate import CheckResult

    long_finding = "two women face to face across the ledger, " * 6
    blur = CheckResult(
        "sharpness", "FAILED", True, 12.0, "Imaginea e neclară: 12 sub pragul de 30 " + "x" * 300
    )
    report = decide(
        NO_FACE[0],
        plan_for(must_fix=[item(long_finding, NADIA_FIX * 2)]),
        [blur],
        verdict(
            fixes=[fix(1, "persists", "two women " * 20)],
            matches_plan=False,
            look_ok=False,
            technical_ok=False,
            reason="r" * 200,
        ),
        environment="TEST",
    )

    assert report.reasons_ro[0].startswith(REWRITE_PHRASE)
    plan_at = next(n for n, r in enumerate(report.reasons_ro) if "ce cere planul" in r)
    assert report.reasons_ro.index(blur.detail_ro) > plan_at
    detail = "; ".join(report.reasons_ro)[:500]
    assert refusal_kind("LOCAL.STILL_GATE", detail) == CONTENT_REFUSAL


class MixedFirst:
    """The vision model, faked: scene 2's first candidate misses its plan (content), the second
    has warped artefacts (technical); everything after is right."""

    def __init__(self):
        self.looked: dict[int, int] = {}

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        look = self.looked[plan.scene] = self.looked.get(plan.scene, 0) + 1
        first, second = plan.scene == 2 and look == 1, plan.scene == 2 and look == 2
        return verdict(
            plan.scene,
            matches_plan=not first,
            technical_ok=not second,
            verdict="regenerate_still" if first or second else "buy_motion",
            reason="another valley" if first else "warped" if second else "as planned",
        )


def test_every_refused_take_of_a_round_sent_back_reads_as_content(engine, tmp_path, monkeypatch):
    """Findings 3 and 4: she confirms the round's refusal; one candidate missed its plan (the
    words), its sibling was warped (one picture). Nothing more is bought on those words, and
    EVERY refused take of the round begins with the content phrase: whichever the ladder reads
    as the scene's newest, it reads CONTENT — never the serial's re-roll of the same words."""
    from app.media.scene_rewrite import serial_refusal

    looks = Looks(HER["CONFIRMED"])
    monkeypatch.setattr(fix_check, "director_second_look", looks)
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills(pictures=new_pictures_for(2))

    result = approved_run(engine, storyboard_id, tmp_path, adapter, MixedFirst())

    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert len([c for c in adapter.asked if SUBJECTS[2] in c["prompt"]]) == 1
    assert entry["status"] == "NEEDS_OWNER" and entry["rewrite"] is True
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert len(rows) == 2 and all(t.failure_detail.startswith(REWRITE_PHRASE) for t in rows)
    assert all(refusal_kind(t.failure_code, t.failure_detail) == CONTENT_REFUSAL for t in rows)
    with Session(engine) as session:
        assert serial_refusal(session, storyboard_id, 2)[1] == CONTENT_REFUSAL


@needs_ffmpeg
@pytest.mark.parametrize(
    ("layer", "said", "back"),
    [
        ("motion", "back_to_still", True),
        ("both", "regenerate_motion", True),
        ("still", "regenerate_motion", True),
        ("motion", "regenerate_motion", False),
    ],
    ids=["look-says-still", "both-layers", "still-layer", "motion-layer"],
)
def test_a_persisting_picture_item_or_the_looks_own_word_sends_the_clip_to_its_still(
    static_clip, tmp_path, layer, said, back
):
    """Finding 5: a persisting item no longer silences the look's own «back_to_still», and an
    item that lives in the picture (still, or both: no still was approved since it was found)
    goes back to the still — seed + 1 on a still that must change buys the same mistake. Only a
    movement's item goes back to the motion."""
    from app.media import qc

    report = qc.check_clip(
        static_clip,
        scene=1,
        camera_move="static",
        faces_forbidden=False,
        environment="TEST",
        judge=lambda frames: _clip_judgement(
            1, [FixAnswer(item=1, finding=ENDING, status="persists", seen="x")], said=said
        ),
        work_dir=tmp_path / "frames",
        must_fix=[item(ENDING, ENDING_FIX, layer=layer)],
    )

    assert report.back_to_still is back
    decision = qc.clip_retry_decision(
        report, seed=7, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert decision.action == ("BACK_TO_STILL" if back else "ESCALATE")
    picture = report.check("picture").detail_ro
    assert ("rescrierea imaginii" in picture) is (layer != "motion")


class FixClipCheck:
    """qc.check_clip, faked: answers each clip's motion items with the next status; one that
    persists fails the picture (the plan not matched, so the one retry is bought)."""

    def __init__(self, *statuses: str):
        self.statuses = list(statuses)
        self.asked: list[tuple] = []

    def __call__(self, clip, **kwargs):
        from app.media.qc import ClipCheck, ClipReport

        status = self.statuses.pop(0)
        asked = tuple(kwargs.get("must_fix") or ())
        self.asked.append(asked)
        fixes = tuple(
            {**dict(it), "status": status, "fixed": status == "gone", "seen": "profile"}
            for it in asked
        )
        failed = status == "persists"
        checks = (
            ClipCheck("motion", "PASSED", False, 1.4, "YDIF mediu 1,40 peste prag"),
            ClipCheck(
                "picture",
                "FAILED" if failed else "PASSED",
                failed,
                None,
                "privit la 1080 px: repetă greșeala" if failed else "privit la 1080 px",
            ),
        )
        scene = int(kwargs["scene"])
        return ClipReport(
            scene=scene,
            path=str(clip),
            checks=checks,
            passed=not failed,
            blocks_ro=tuple(f"Scena {scene}: {c.detail_ro}" for c in checks if c.blocking),
            warnings_ro=(),
            unmeasured=(),
            measured={"motion": {"mean_ydif": 1.4}},
            fixes=fixes,
        )


def test_a_runpod_clip_retry_deferred_to_the_next_round_settles_nothing_before_it_is_checked(
    engine,
    tmp_path,
    fake_session,  # noqa: F811
    lessons,
):
    """Finding 6: on RunPod the first clip's retry is bought in the NEXT round; the review's
    lessons were withdrawn when the first clip showed the mistake, before the retry that
    corrected it was even bought. Now nothing is settled until clip QC's last word: the retry
    shows the movement's item gone, and the lessons are confirmed — never withdrawn."""
    from app.media.assembler import MotionStepRefused, motion_plan, run_motion_step
    from test_approvals import answer
    from test_film_costing import a_film as costed_film
    from test_runpod_batch import (
        Cloud,
        RunPodVideoAdapter,
        finishing_video,
        motion_table,
        runpod_capability,
        serverless,
    )

    storyboard_id = costed_film(engine, tmp_path, scenes=1)
    review_run = rewritten(
        engine, storyboard_id, 1, findings=[(ENDING, ENDING_FIX)], layer="motion"
    )
    cloud = finishing_video(Cloud())
    made = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    capability = runpod_capability()
    table = motion_table()
    check = FixClipCheck("persists", "gone")

    def go():
        plan = motion_plan(engine, storyboard_id, capabilities=[capability], table=table)
        return run_motion_step(
            engine,
            storyboard_id,
            str(uuid4()),
            step="test_shot",
            plan_hash=plan["plan_hash"],
            adapter_for_model=lambda model: made if model == "LTX-2.5" else None,
            capabilities=[capability],
            table=table,
            storage_root=tmp_path / "media",
            clip_check=check,
        )

    with pytest.raises(MotionStepRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    result = go()

    (entry,) = result["scenes"]
    assert entry["status"] == "PAID" and entry["clip_qc"]["attempts"] == 2
    assert [said(asked_items) for asked_items in check.asked] == [[(ENDING, ENDING_FIX)]] * 2
    assert lessons["withdrawn"] == []
    assert lessons["confirmed"] == [[review_run]]


def test_lessons_are_settled_review_run_by_review_run(engine, tmp_path, lessons):
    """Finding 7: a run whose item lives on the motion layer is not confirmed by a still that
    cannot show it; a run is withdrawn only for ITS own item, never a neighbour's."""
    storyboard_id = a_film(engine, tmp_path)
    picture_run = rewritten(
        engine,
        storyboard_id,
        2,
        findings=[
            {"qc_text": NADIA, "by": NADIA_FIX, "treated": True, "layer": "still"},
            {"qc_text": ENDING, "by": ENDING_FIX, "treated": True, "layer": "motion"},
        ],
    )
    approved_still(engine, storyboard_id, 2, "2999-01-01T00:00:00+00:00")
    still_answers = [
        {"finding": NADIA, "status": "gone", "source": "review", "source_id": picture_run}
    ]
    with Session(engine) as session, session.begin():
        confirmed = fix_check.confirm_lessons(
            session, still_answers, storyboard_id=storyboard_id, scene_index=2
        )
    assert confirmed == [] and lessons["confirmed"] == [], "the ending is the clip's to show"
    passed_clip(engine, storyboard_id, 2, "2999-01-01T00:00:01+00:00")
    clip_answers = [
        {"finding": ENDING, "status": "gone", "source": "review", "source_id": picture_run}
    ]
    with Session(engine) as session, session.begin():
        confirmed = fix_check.confirm_lessons(
            session, clip_answers, storyboard_id=storyboard_id, scene_index=2
        )
    assert confirmed == [picture_run] and lessons["confirmed"] == [[picture_run]]

    # Two runs on one candidate: only the run whose item persists is withdrawn.
    looks = [
        [
            {"status": "persists", "source": "review", "source_id": "run-a"},
            {"status": "gone", "source": "review", "source_id": "run-b"},
        ]
    ]
    with Session(engine) as session, session.begin():
        assert fix_check.withdraw_lessons(session, looks) == ["run-a"]
    assert lessons["withdrawn"][-1][0] == ["run-a"]


def _reading_report(scene: int, clip, *, band: bool = False):
    """A clip the look sent back to its still (``back_to_still``): by its own reading, or by a
    flat band measured on its first frame (``band``)."""
    from app.media.qc import ClipCheck, ClipReport

    checks = (
        ClipCheck("motion", "PASSED", False, 1.4, "YDIF mediu 1,40 peste prag"),
        ClipCheck(
            "picture",
            "FAILED",
            True,
            None,
            "privit la 1080 px: nu arată ce cere planul («the desk holds a laptop»)",
        ),
    )
    measured: dict = {
        "motion": {"mean_ydif": 1.4},
        "picture": {"verdict": {"one_picture": True, "matches_plan": False}},
    }
    if band:
        measured["panels"] = {"frames": [{"at": "first", "splits_the_picture": True}]}
    return ClipReport(
        scene=scene,
        path=str(clip),
        checks=checks,
        passed=False,
        blocks_ro=tuple(f"Scena {scene}: {c.detail_ro}" for c in checks if c.blocking),
        warnings_ro=(),
        unmeasured=(),
        measured=measured,
        back_to_still=True,
    )


@pytest.mark.parametrize("her", ["OVERTURNED", "CONFIRMED", "BAND"])
def test_a_clip_sent_back_to_its_still_by_a_reading_is_shown_to_her_first(tmp_path, her):
    """Finding 8: a clip the look's reading sent back to its still bought a new still and new
    motion with nobody looking. Now she looks first (free): OVERTURNED keeps the clip, nothing
    is bought; CONFIRMED sends it back with her reason; a band measured on the first frame
    (panels, a hard limit) is never offered to her."""
    from app.media import qc

    asked: list = []
    bought: list = []

    def look(report):
        asked.append(report)
        return dict(HER["CONFIRMED" if her == "BAND" else her])

    outcome = qc.qc_clip_with_retry(
        tmp_path / "clip.mp4",
        check=lambda path: _reading_report(1, path, band=her == "BAND"),
        buy=lambda seed, prompt: bought.append(seed),
        seed=7,
        motion_prompt="Slow push-in.",
        camera_move="slow push-in",
        model_id="seedance2_5",
        price_credits=10,
        committed_credits=0,
        cap_credits=100,
        look=look,
    )

    assert bought == [], "nothing is animated again from a still sent back"
    if her == "BAND":
        assert asked == [] and outcome.status == "BACK_TO_STILL"
        return
    assert len(asked) == 1
    if her == "OVERTURNED":
        assert outcome.status == qc.ACCEPTED_BY_LOOK and outcome.clip is not None
        return
    assert outcome.status == "BACK_TO_STILL" and HER[her]["reason_ro"] in outcome.reason_ro


def test_what_was_accepted_on_a_take_is_read_back_for_the_films_qc(engine, tmp_path, lessons):
    """Finding 9: the note of an accepted minor trace has a reader (`accepted_on_takes`), for
    the film's QC context, so the trace is not refused again after the money."""
    storyboard_id = a_film(engine, tmp_path)
    review_run = rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    judge = FixJudge(status=lambda look, plan: "minor")

    result = approved_run(
        engine, storyboard_id, tmp_path, SpyStills(pictures=new_pictures_for(2)), judge
    )

    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    with Session(engine) as session:
        accepted = fix_check.accepted_on_takes(session, [entry["take_id"], None, "nothing"])
        note = fix_check.take_note(session, entry["take_id"])
    assert list(accepted) == [entry["take_id"]]
    assert accepted[entry["take_id"]]["minor"] == entry["minor_defects"]
    assert accepted[entry["take_id"]]["approved_by"] == "still_gate"
    # The trace names its review run: it never confirms that run's lessons.
    assert note["minor_sources"] == [review_run]
    assert lessons["confirmed"] == [] and lessons["withdrawn"] == []


def test_her_reading_of_an_older_briefs_words_replaces_the_patterns(engine, tmp_path, staffed):
    """Finding 11: a brief recorded before her review kept findings carries the film's words
    mixed with the studio's process notes and her own prescriptions. The patterns keep only
    the sight (and now leave out «test_shot, not approved», «drop '…'», «no negations»); when
    she has read the brief (free), her reading is what the still is checked for."""
    from test_picture_qc import registry_with

    storyboard_id = a_film(engine, tmp_path)
    words = [
        "The motion take is a test_shot, not approved; two women face to face across the ledger.",
        "drop 'sensors and electronics' which invited instrument markings; no negations, no "
        "'text'.",
    ]
    rewritten(engine, storyboard_id, 2, findings=[], film=words)
    assert [i["finding"] for i in open_for(engine, storyboard_id, 2)] == [
        "two women face to face across the ledger."
    ]
    sight = "Two women stand face to face across the ledger instead of Nadia alone."
    registry, model = registry_with(staffed, lambda prompt: json.dumps({"seen": [sight]}))

    read = fix_check.read_film_reasons(
        engine, registry, storyboard_id=storyboard_id, correlation_id=str(uuid4())
    )

    assert read == 1 and len(model.calls) == 1
    assert "test_shot" in model.calls[0]["prompt"]
    assert [i["finding"] for i in open_for(engine, storyboard_id, 2)] == [sight]
    assert [i["finding"] for i in open_for(engine, storyboard_id, 2, layer="motion")] == [sight]
    # Read once: nothing is asked again.
    again = fix_check.read_film_reasons(
        engine, registry, storyboard_id=storyboard_id, correlation_id=str(uuid4())
    )
    assert again == 0 and len(model.calls) == 1
    # No registry: nothing is asked, nothing changes.
    unasked = fix_check.read_film_reasons(
        engine, None, storyboard_id=storyboard_id, correlation_id="c"
    )
    assert unasked == 0


def test_collected_candidates_that_repeat_the_mistake_go_back_to_her_words(
    engine, tmp_path, lessons
):
    """Finding 12: candidates collected after their step, judged by the day, that show their
    plan and the corrected mistake again were left NOT_BOUGHT — planned and bought again on the
    same words. Now the round goes to her ladder, as a bought round does."""
    import hashlib

    from app.media.assembler import UNJUDGED_FAILURE_CODE, record_take, still_fields, take_hash
    from app.media.stills_stage import STILL_RATIO, settle_stills
    from test_stills_stage import SpyJudge, faces_in

    storyboard_id = a_film(engine, tmp_path)
    approved_run(engine, storyboard_id, tmp_path, SpyStills(), SpyJudge())
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.scene_number == 2
            )
        ):
            row.status = "REJECTED"
            row.failure_code = "REDO.OWNER"
        visual = (
            session.scalars(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == storyboard_id,
                    StoryboardScene.scene_index == 2,
                )
            )
            .one()
            .visual_prompt
        )
    review_run = rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    folder = tmp_path / "collected"
    folder.mkdir()
    for n, source in enumerate(NO_FACE, start=1):
        path = folder / f"scene_02_collected_c{n}.jpg"
        path.write_bytes(source.read_bytes() + b"collected")
        record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=2,
            kind="still",
            prompt_hash=take_hash(still_fields(visual, None), "seedream5_pro"),
            model_id="seedream5_pro",
            resolution=STILL_RATIO,
            status="PAID",
            correlation_id="watchdog",
            credits_quoted=9.0,
            path=path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            failure_code=UNJUDGED_FAILURE_CODE,
            remote_task_id="img-task-late",
        )
    adapter = SpyStills()

    settled = settle_stills(
        engine,
        storyboard_id,
        str(uuid4()),
        image_adapter=adapter,
        registry=None,
        judge=FixJudge(status=lambda look, plan: "persists"),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
    )

    assert adapter.asked == []
    (entry,) = [e for e in settled["scenes"] if e["scene_index"] == 2]
    assert entry["status"] == "NEEDS_OWNER" and entry["rewrite"] is True
    rows = [
        t
        for t in takes(engine, storyboard_id)
        if t.scene_number == 2 and t.remote_task_id == "img-task-late"
    ]
    assert len(rows) == 2 and all(t.failure_detail.startswith(REWRITE_PHRASE) for t in rows)
    assert lessons["withdrawn"] and lessons["withdrawn"][0][0] == [review_run]


def test_a_sibling_that_shows_the_mistake_gone_keeps_the_words(engine):
    """Finding 13: one candidate shows its plan and the mistake again, its sibling (refused for
    its technique) shows the mistake gone: the words CAN correct it, so the round is re-rolled
    on them — not sent back — and no lesson is withdrawn."""
    plan = plan_for(must_fix=[item()])
    repeats = decide(
        NO_FACE[0], plan, [], verdict(fixes=[fix(1, "persists", "two women")]), environment="TEST"
    )
    corrected = decide(
        NO_FACE[1],
        plan,
        [],
        verdict(fixes=[fix(1, "gone")], technical_ok=False),
        environment="TEST",
    )

    assert round_step([repeats], rerolls_done=0).action == "rewrite"
    step = round_step([repeats, corrected], rerolls_done=0)
    assert step.action == "reroll" and POSITIVE_WORDS["finding_persists"] in step.instruction
    with Session(engine) as session:
        looks = [list(repeats.fixes), list(corrected.fixes)]
        assert fix_check.withdraw_lessons(session, looks) == []
    # The answers carry their item's review run (`fix_answers`), so runs are settled one by one.
    assert repeats.fixes[0]["source_id"] == "review-run" and repeats.fixes[0]["layer"] == "still"
    assert fix_answers([item(severity="minor")], verdict().verdict) == [
        {
            "finding": NADIA,
            "expected": NADIA_FIX,
            "status": None,
            "fixed": None,
            "seen": "",
            "layer": "still",
            "source": "review",
            "source_id": "review-run",
            "severity": "minor",
        }
    ]
