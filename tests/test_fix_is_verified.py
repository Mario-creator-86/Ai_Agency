"""After a rewrite, the new still is checked for exactly what the rewrite was meant to fix.

The Owner, 2026-10-12, 16:50, after stopping the studio: «Sistemul trebuie să refacă promptul!
... DAR SĂ REFACĂ CE A FOST GREȘIT. Și să se asigure că ce a fost greșit este acum corectat. Nu
să facă aceeași greșeală la nesfârșit!» On f06808c9 scene 4 the finding was «two women face to
face instead of a single on Nadia»; the rewrite answered it in words, the Director's review said
so, and nothing looked for the two women again until the film's QC, after the clip and the money.

What is asserted:

- `fix_check.open_findings` names what the scene's current words were rewritten to fix: her
  review's findings with the sentence that treats each, and the film QC's own words on her brief,
  without the studio's process notes, at most four, at most 300 characters each; nothing when
  no rewrite of the picture is open, and nothing once a still made after it was approved;
- the vision look is shown those items and must answer each (an answer that leaves one out is
  asked again, and is NOT_RUN if it leaves it out twice); without them nothing of the check is
  in the look's prompt, nor in the report it is read into;
- the gate refuses a still that repeats the mistake («Imaginea repetă greșeala ...»,
  ``finding_persists``, read by the Director's ladder as a content refusal) and passes one that
  fixed it; the best candidate that fixes everything is chosen;
- the stills step and the paid still redo give every still they buy its open findings, so the
  refusal happens before any clip is bought;
- the gate's «scene» is the scriptwriter's line (``writer_visual``), not the compiled prompt,
  judged at its first moment like the plan.

Every model and vendor is faked, as the stills-step and picture-QC tests fake them.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import AgentRun
from app.media import fix_check, stills_stage
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.models import SceneTake, StoryboardScene
from app.media.picture_qc import (
    STILL_FIX_TEMPLATE_VERSION,
    STILL_TASK,
    STILL_TEMPLATE_VERSION,
    StillFix,
    StillJudgement,
    StillVerdict,
    still_report_schema,
)
from app.media.scene_rewrite import BRIEF_EVENT, CONTENT_REFUSAL, REWRITE_REASON, refusal_kind
from app.media.still_gate import (
    POSITIVE_WORDS,
    StillPlan,
    choose_best,
    decide,
    next_step,
)
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
FFMPEG = __import__("shutil").which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def rewritten(
    engine,
    storyboard_id: str,
    scene: int,
    *,
    findings: list[tuple[str, str]],
    film: list[str] = (),
    layer: str = "still",
    reason: str = REWRITE_REASON,
    run_id: str | None = None,
) -> None:
    """The Director's rung on one scene, as `scene_rewrite.rewrite_scene` and `_record_brief`
    record it: the rewrite (with her review's findings), then her brief (with the film's words)."""
    run_id = run_id or str(uuid4())
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
                "still_prompt": "the new words" if layer == "still" else "the old words",
                "run_id": run_id,
                "review": {
                    "verdict": "TREATS",
                    "reason_ro": "Rescrierea tratează constatarea.",
                    "findings": [
                        {"finding": finding, "treated": True, "by": by} for finding, by in findings
                    ],
                    "run_id": str(uuid4()),
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


def approved_still(engine, storyboard_id: str, scene: int, created_at: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                scene_number=scene,
                kind="still",
                prompt_hash=uuid4().hex + uuid4().hex,
                model_id="seedream5_pro",
                resolution="1530:2720",
                status="APPROVED",
                approved_by="still_gate",
                created_at=created_at,
                updated_at=created_at,
            )
        )


def open_for(engine, storyboard_id: str, scene: int) -> list[dict[str, str]]:
    with Session(engine) as session:
        return fix_check.open_findings(session, storyboard_id, scene)


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


def fix(item: int, fixed: bool, seen: str = "Nadia alone at her desk") -> StillFix:
    return StillFix(item=item, finding="", fixed=fixed, seen=seen)


# ------------------------------------------------------- 1. what the rewrite was meant to fix


def test_open_findings_are_the_reviews_findings_and_the_films_own_words(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    long_word = "x" * 400
    rewritten(
        engine,
        storyboard_id,
        2,
        findings=[(NADIA, NADIA_FIX), ("ruled lines and garbled text on the ledger", "")],
        film=[
            "Scena 2: mișcarea filmată din imaginea nouă.",  # the studio's note, not a finding
            NADIA,  # the same finding again, in the film's words: asked once
            "The movement of this scene was rewritten before and came back with the same "
            "words; the picture itself must change now.",
            "the lamp is missing from the desk",
            long_word,
            "a fifth thing that does not fit",
        ],
    )

    found = open_for(engine, storyboard_id, 2)

    assert [item["finding"] for item in found][:3] == [
        NADIA,
        "ruled lines and garbled text on the ledger",
        "the lamp is missing from the desk",
    ]
    assert found[0]["expected"] == NADIA_FIX
    assert found[2]["expected"] == ""  # the film's words carry no rewrite sentence
    assert len(found) == fix_check.MAX_ITEMS == 4
    assert all(len(item["finding"]) <= fix_check.MAX_CHARS for item in found)
    assert not any("mișcarea filmată" in item["finding"] for item in found)
    # Only the rewritten scene has anything open.
    assert open_for(engine, storyboard_id, 1) == []


def test_nothing_is_open_without_a_rewrite_of_the_picture_by_her_brief(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    assert open_for(engine, storyboard_id, 3) == []
    # The compiler's own rewrite for a redo, and the serial composer's, answer no finding.
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], reason="redo")
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], reason="serial_recompose")
    assert open_for(engine, storyboard_id, 3) == []
    # A motion rewrite keeps the still's words: nothing for a still to show.
    rewritten(
        engine, storyboard_id, 3, findings=[("the camera drifts", "a slow push-in")], layer="motion"
    )
    assert open_for(engine, storyboard_id, 3) == []


def test_a_motion_rewrite_after_the_pictures_leaves_the_pictures_findings(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    rewritten(
        engine, storyboard_id, 2, findings=[("the camera drifts", "a slow push-in")], layer="motion"
    )
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2)] == [NADIA]


def test_a_still_approved_after_the_rewrite_leaves_nothing_open(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    # The still the film was made from, approved long before the rewrite: never checked for it.
    approved_still(engine, storyboard_id, 2, "2026-10-01T10:00:00+00:00")
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    assert [item["finding"] for item in open_for(engine, storyboard_id, 2)] == [NADIA]
    # A still made after the rewrite and approved was checked for it: nothing is open.
    approved_still(engine, storyboard_id, 2, "2999-01-01T00:00:00+00:00")
    assert open_for(engine, storyboard_id, 2) == []


# ------------------------------------------------------------------ 2. the gate's decision


def test_a_still_that_repeats_the_mistake_is_refused_and_one_that_fixed_it_passes():
    plan = plan_for(must_fix=[{"finding": NADIA, "expected": NADIA_FIX}])
    seen = "two women facing each other across the ledger"

    persists = decide(
        NO_FACE[0], plan, [], verdict(fixes=[fix(1, False, seen)]), environment="TEST"
    )
    fixed = decide(NO_FACE[1], plan, [], verdict(fixes=[fix(1, True)]), environment="TEST")

    assert persists.decision == "BLOCKED"
    assert persists.reasons_ro[0].startswith(
        f"Imaginea repetă greșeala pe care rescrierea trebuia să o corecteze: «{NADIA}»"
    )
    assert seen in persists.reasons_ro[0]
    assert persists.violations == ("finding_persists",)
    assert persists.fixes == ({"finding": NADIA, "fixed": False, "seen": seen},)
    # The Director's ladder reads the take's words as a content refusal: her brief, not a reroll
    # of the same words with another seed (scene_rewrite.refusal_kind).
    assert refusal_kind("LOCAL.STILL_GATE", "; ".join(persists.reasons_ro)[:500]) == CONTENT_REFUSAL
    step = next_step(persists, rerolls_done=0)
    assert step.action == "reroll" and POSITIVE_WORDS["finding_persists"] in step.instruction

    assert fixed.decision == "PASSED" and fixed.violations == ()
    assert fixed.fixes == ({"finding": NADIA, "fixed": True, "seen": "Nadia alone at her desk"},)
    # Of two candidates, the one that fixed everything is chosen.
    assert choose_best([persists, fixed]) is fixed


def test_every_answer_for_an_item_must_say_fixed_and_silence_is_not_a_pass():
    plan = plan_for(
        must_fix=[{"finding": NADIA, "expected": NADIA_FIX}, {"finding": "a lamp", "expected": ""}]
    )
    both = decide(
        NO_FACE[0],
        plan,
        [],
        verdict(fixes=[fix(1, True), fix(1, False, "Sarah in full view"), fix(2, True)]),
        environment="TEST",
    )
    assert both.decision == "BLOCKED" and "finding_persists" in both.violations
    # A verdict built in code that leaves an item out is a still nobody checked for it.
    silent = decide(NO_FACE[0], plan, [], verdict(fixes=[fix(1, True)]), environment="TEST")
    assert silent.decision == "BLOCKED" and "vision" in silent.unmeasured
    assert any("nu a spus dacă imaginea corectează" in r for r in silent.reasons_ro)


def test_without_must_fix_the_decision_is_unchanged():
    report = decide(NO_FACE[0], plan_for(), [], verdict(), environment="TEST")
    assert report.decision == "PASSED" and report.fixes == ()


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
        asked.model_validate(
            {"stills": [{**entry, "fixes": [{"item": 1, "fixed": True, "seen": "ok"}]}]}
        )
    with pytest.raises(ValidationError):  # a word is not an answer
        asked.model_validate(
            {
                "stills": [
                    {
                        **entry,
                        "fixes": [
                            {"item": 1, "fixed": "yes", "seen": "ok"},
                            {"item": 2, "fixed": True, "seen": "ok"},
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
                        {"item": 1, "fixed": False, "seen": "two women"},
                        {"item": 2, "fixed": True, "seen": "a lamp"},
                    ],
                }
            ]
        }
    )
    assert [f.fixed for f in read.stills[0].fixes] == [False, True]


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


def _template_versions(engine) -> list[str]:
    with Session(engine) as session:
        return [
            run.prompt_template_version
            for run in session.scalars(
                select(AgentRun)
                .where(AgentRun.task_type == STILL_TASK)
                .order_by(AgentRun.started_at)
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
            fixes=[{"item": 1, "finding": "the two women", "fixed": False, "seen": seen}]
        ),
    )
    plan = plan_for(must_fix=[{"finding": NADIA, "expected": NADIA_FIX}])

    judged = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))

    assert judged.status == "MEASURED" and len(model.calls) == 1
    (answered,) = judged.verdict.fixes
    assert (answered.item, answered.finding, answered.fixed, answered.seen) == (
        1,
        NADIA,
        False,
        seen,
    )
    prompt = model.calls[0]["prompt"]
    assert "must_fix" in prompt and NADIA in prompt and NADIA_FIX in prompt
    assert "fixed false when the still shows the mistake again" in prompt
    assert _template_versions(engine) == [STILL_FIX_TEMPLATE_VERSION]
    report = decide(NEPAL_STILL, plan, [], judged, environment="TEST")
    assert report.decision == "BLOCKED" and "finding_persists" in report.violations


@needs_ffmpeg
def test_a_look_that_leaves_a_finding_unanswered_is_asked_again_then_not_run(engine, staffed):
    from app.media.picture_qc import judge_still
    from test_picture_qc import NEPAL_STILL, give_vision, registry_with

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    plan = plan_for(must_fix=[{"finding": NADIA, "expected": NADIA_FIX}])

    registry, model = registry_with(staffed, lambda prompt: _answer())
    mute = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))
    assert len(model.calls) == 2, "the answer without `fixes` is refused and asked again"
    assert mute.status == "NOT_RUN" and "nu a fost privită" in mute.detail_ro

    answers = iter([_answer(), _answer(fixes=[{"item": 1, "fixed": True, "seen": "Nadia alone"}])])
    registry, model = registry_with(staffed, lambda prompt: next(answers))
    second = judge_still(engine, registry, NEPAL_STILL, plan, str(uuid4()))
    assert len(model.calls) == 2 and second.status == "MEASURED"
    assert [(f.finding, f.fixed) for f in second.verdict.fixes] == [(NADIA, True)]


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
    """The vision model, faked: answers every item it is asked about as ``fixed(look, plan)``
    says, and remembers each plan it was shown."""

    def __init__(self, fixed=lambda look, plan: True):
        self.plans: list[StillPlan] = []
        self.fixed = fixed

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        self.plans.append(plan)
        answer = self.fixed(len(self.plans), plan)
        return verdict(
            plan.scene,
            fixes=[
                fix(number, answer, "Nadia alone" if answer else "two women face to face")
                for number in range(1, len(plan.must_fix) + 1)
            ],
            reason="the scene as planned",
        )


def test_the_stills_step_refuses_a_still_that_repeats_the_mistake_before_any_clip(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    rewritten(engine, storyboard_id, 2, findings=[(NADIA, NADIA_FIX)])
    # Scene 2's first pair repeats the two women; its re-roll fixed them.
    judge = FixJudge(fixed=lambda look, plan: plan.scene != 2 or look > 4)
    asked_two: list[int] = []

    def pictures(prompt, call):
        # Scene 2's pictures are new files each time (one file of one prompt is one row).
        if SUBJECTS[2] not in prompt:
            return list(NO_FACE)
        asked_two.append(call)
        names = ("scene_03", "scene_04") if len(asked_two) == 1 else ("scene_05", "scene_02")
        return [FIXTURES / f"{name}.jpg" for name in names]

    adapter = SpyStills(pictures=pictures)

    result = approved_run(engine, storyboard_id, tmp_path, adapter, judge)

    must = [plan for plan in judge.plans if plan.must_fix]
    assert must and all(plan.scene == 2 for plan in must)
    assert all(plan.must_fix == ({"finding": NADIA, "expected": NADIA_FIX},) for plan in must)
    assert all(plan.must_fix == () for plan in judge.plans if plan.scene != 2)
    scene_2 = [call for call in adapter.asked if SUBJECTS[2] in call["prompt"]]
    assert len(scene_2) == 2, "one pair refused, one re-roll"
    assert POSITIVE_WORDS["finding_persists"] in scene_2[1]["prompt"]
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    refused = [t for t in rows if t.status == "REJECTED"]
    assert len(refused) == 2
    assert all("Imaginea repetă greșeala" in t.failure_detail for t in refused)
    assert all(NADIA in t.failure_detail for t in refused)
    assert sorted(t.status for t in rows if t.status != "REJECTED") == ["APPROVED", "PAID"]
    entry = next(e for e in result["scenes"] if e["scene_index"] == 2)
    assert entry["status"] == "APPROVED" and entry["must_fix"] == [NADIA]
    # Nothing here ever buys motion (SpyStills fails the test on any video call); and the
    # still approved after the rewrite was checked for it: nothing is open any more.
    assert open_for(engine, storyboard_id, 2) == []


def test_the_runpod_rounds_check_the_rewritten_scene_on_every_round(
    engine,
    tmp_path,
    fake_session,  # noqa: F811
):
    """RunPod Serverless buys in rounds (`stills_stage._StillRounds`): the rewritten scene's
    plan carries its findings on the first round and on each re-roll; a scene whose every
    picture repeats the mistake is never approved, and the others go on."""
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
    judge = FixJudge(fixed=lambda look, plan: False)

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
    assert by_scene[2]["status"] == "NEEDS_OWNER" and by_scene[2]["rerolls"] == 2
    assert by_scene[2]["must_fix"] == [NADIA]
    assert all(by_scene[n]["status"] == "APPROVED" for n in (1, 3, 4))
    looked_at_two = [plan for plan in judge.plans if plan.scene == 2]
    assert len(looked_at_two) == 6, "three rounds of two"
    assert all(
        plan.must_fix == ({"finding": NADIA, "expected": NADIA_FIX},) for plan in looked_at_two
    )
    assert all(plan.must_fix == () for plan in judge.plans if plan.scene != 2)
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert rows and all(t.status == "REJECTED" for t in rows)
    assert all("Imaginea repetă greșeala" in (t.failure_detail or "") for t in rows)


@pytest.mark.parametrize("fixed", [False, True], ids=["repeats-the-mistake", "fixed-it"])
def test_a_still_redo_is_checked_for_what_its_rewrite_answered(engine, tmp_path, fixed):
    """The paid still redo the Director decided after the film failed QC (the per-request
    buyer, `assembler._redo_still`): every candidate is checked for her rewrite's findings. A
    picture that repeats the two women is refused before any clip; one that fixed them is
    approved, and nothing is open on the scene any more."""
    from app.media.assembler import SceneRedoRefused, redo_plan, redo_scene
    from test_approvals import answer
    from test_film_costing import a_film as costed_film
    from test_stills_stage import faces_in

    storyboard_id = costed_film(engine, tmp_path, scenes=4)
    before = {t.id for t in takes(engine, storyboard_id)}
    rewritten(engine, storyboard_id, 3, findings=[(NADIA, NADIA_FIX)], film=[NADIA])
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)
    judge = FixJudge(fixed=lambda look, plan: fixed)

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

    assert judge.plans and all(
        p.must_fix == ({"finding": NADIA, "expected": NADIA_FIX},) for p in judge.plans
    )
    new = [t for t in takes(engine, storyboard_id) if t.id not in before]
    assert new and all(t.scene_number == 3 and t.kind == "still" for t in new)
    if fixed:
        assert result["still"]["status"] == "APPROVED"
        assert sorted(t.status for t in new) == ["APPROVED", "PAID"]
        assert open_for(engine, storyboard_id, 3) == []
        return
    assert result["still"]["status"] != "APPROVED"
    assert all(t.status == "REJECTED" for t in new)
    # Each picture the gate looked at is refused for the mistake (a re-roll that handed back
    # a file the scene already had is refused as that duplicate, `assembler.record_take`).
    gate = [t for t in new if t.failure_code == "LOCAL.STILL_GATE"]
    assert len(gate) >= 2
    assert all("Imaginea repetă greșeala" in (t.failure_detail or "") for t in gate)
    assert all(NADIA in (t.failure_detail or "") for t in gate)
    # No clip was bought on a still that repeats the mistake.
    assert not [t for t in takes(engine, storyboard_id) if t.kind in ("motion", "test_shot")]


# ------------------------------------------------------- 5. the scene the gate is shown


@pytest.mark.parametrize("serial", [False, True], ids=["factual", "serial"])
def test_the_scene_shown_is_the_writers_line_not_the_compiled_prompt(engine, tmp_path, serial):
    """2026-10-12, read on the database copy: visual_prompt equals the compiled still prompt
    (1c038a99 scene 5, aa170155 scene 1, f06808c9 scene 4), so shows_scene could only repeat
    matches_plan. The writer's line is kept on the package as ``writer_visual``."""
    storyboard_id = a_film(engine, tmp_path)
    line = "Return to the dark detector cavern from the opening shot, points of light on the rings."
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        )
        package = dict(row.prompt_json or {})
        package["writer_visual"] = line
        if serial:
            package.update(in_frame=[{"name": "Nadia"}], shot_size="MCU", action="Nadia writes")
        row.prompt_json = package

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
