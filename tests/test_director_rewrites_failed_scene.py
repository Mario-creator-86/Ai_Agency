"""The Director reads a refused scene's prompt and has it rewritten (the Owner, 2026-10-11).

The cyclotron film (aa170155) stopped with «scenele 4, 5 așteaptă decizia Proprietarului»: clip
QC refused scene 4 twice (faces the bible forbids) and scene 5 once (the wrong object). The
Owner: a film is redone until QC passes, only money stops it, and not blindly — «directoarea
citește promptul și după îl cere la rescriere cu informații clare, ce să evite ca să treacă la
QC!». What is held here, every provider faked, 0 credits:

- a scene clip QC refused is read by the Director (its prompts, the refusals' reasons) and her
  brief is a letter to the Video Editor; his rewrite changes that scene's motion only, the
  picture's words stay, his answer is a letter back, both settled;
- her rewrite lifts the hold the refusal left: the shot is bought again, on the new words, and
  passes; no other scene is touched;
- after a motion rewrite that failed again on the same picture, only the picture may be
  rewritten (a still the gate approved, never one the Owner approved); a still rewrite gives a
  new still prompt and the scene needs a new still;
- an answer that names a layer not open, or no Director at all, rewrites nothing: the scene
  waits as before;
- the day's staircase does it by itself: a walk stopped on a refused scene gets her rewrite and
  walks the film again;
- before anything is stored she reviews his words against the findings (2026-10-12, the Owner on
  film 1c038a99's scene 5 redone five times: «tratează problema? Promptul trebuie revizuit»): a
  rewrite that misses a finding is not stored, the hold stays, the record and his letter say why;
  a rewrite nobody could review is not stored either.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, motion_plan
from app.media.models import SceneTake, StoryboardScene
from app.media.prompt_agent import motion_prompt_for
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    MOTION,
    STILL,
    earlier_briefs,
    open_layers,
    rewrite_failed_scene,
    rewrite_for_redo,
)
from app.media.toolchain import find_ffmpeg
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from final_rewrite_actor import final_answer, final_review
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import ScriptedCheck, events, shots
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film, approved

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

#: Scene 1's plan, as the Video Editor wrote it (the fixture film carries only its prompts).
PLAN = {
    "subject": "a far village of stone houses on a terraced slope",
    "action": "the village rests below steep ridges",
    "environment": "steep Himalayan ridges under low cloud",
    "camera": "wide establishing shot, 24mm lens, seen from high above",
    "lighting": "soft overcast daylight",
    "motion": "low grey cloud drifts slowly over the ridges",
}
BRIEF = {
    "diagnosis": "The motion asked only for a slow drift, so the clip barely moved.",
    "layer": "motion",
    "avoid": ["a frozen, almost still frame"],
    "keep": ["the village on its terraced slope"],
    "change": ["the cloud rolls clearly across the ridges from left to right"],
    "summary_ro": "Clipul aproape nu se mișca; cer o mișcare clară a norilor.",
}
SHOT = {
    "scene_index": 1,
    "motion": "thick grey cloud rolls steadily across the ridges from left to right",
    "camera_move": "slow pan right",
    "ending_frame": "the ridges half hidden by the passing cloud",
}
STILL_SHOT = {
    "scene_index": 1,
    "subject": "terraced rice fields on a mountain slope under rolling cloud",
    "action": "wind bends the young rice in long waves",
    "environment": "steep Himalayan ridges under low cloud",
    "camera": "wide establishing shot, 24mm lens",
    "lighting": "soft overcast daylight",
    "motion": "wind sweeps waves through the rice while cloud rolls over the ridges",
    "camera_move": "slow push-in",
}
#: Her review of his rewrite: the finding is treated by the new sentence it quotes. Every one
#: of quality control's findings is answered by its id (2026-10-12): the scripted answer is
#: given for each id the review's data names (`answer_each`).
REVIEW = {
    "findings": [
        {
            "finding": "the clip barely moved",
            "treated": True,
            "severity": "serious",
            "by": "Thick grey cloud rolls steadily across the ridges from left to right.",
        }
    ],
    "reason_ro": "Rescrierea tratează constatarea: norii se mișcă clar de la stânga la dreapta.",
    "cause": "The motion asked only for a slow drift, so the model barely moved the frame.",
    "lesson": (
        "Give every shot one clear movement with a direction and a pace across the whole clip."
    ),
}
#: Her review when the rewrite changed words the finding never named; each untreated finding
#: says why and the field he must change (2026-10-12).
MISSED = {
    "findings": [
        {
            "finding": "a face seen in profile",
            "treated": False,
            "severity": "serious",
            "by": "",
            "why_not": "the figure on the ridge is still described, and it can turn its head",
            "field": "motion",
        }
    ],
    "reason_ro": "Rescrierea schimbă doar norii; fața din profil rămâne posibilă în cadru.",
    "cause": "The plan places a figure on the ridge, whose head can turn to the camera.",
    "lesson": "Show people only as small distant figures seen from behind for the whole shot.",
}


def answer_each(prompt: str, review: dict[str, Any]) -> dict[str, Any]:
    """Her scripted review given for every finding id quality control's findings carry in the
    review's data, each answered as the script's first finding."""
    found = re.search(
        r'<untrusted_source_evidence hash="rewrite-review">\n(.*?)\n</untrusted_source_evidence>',
        prompt,
        re.DOTALL,
    )
    ids = [item["id"] for item in json.loads(found.group(1))["quality_control_findings"]]
    template = review["findings"][0]
    return {**review, "findings": [{**template, "id": number} for number in ids]}


class Agents:
    """Every agent's model, scripted: the Director's brief, the Video Editor's shot, her
    review of his rewrite (a string is answered as it is, for a review nobody can read)."""

    def __init__(self, brief: Any = None, shot: Any = None, review: Any = None):
        self.brief = dict(BRIEF) if brief is None else brief
        self.shot = dict(SHOT) if shot is None else shot
        self.review = dict(REVIEW) if review is None else review
        self.briefs: list[str] = []
        self.rewrites: list[str] = []
        self.reviews: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        if '"scene-brief"' in prompt:
            self.briefs.append(prompt)
            return GenerateResult(json.dumps(self.brief), 10, 40, None)
        if '"scene-rewrite"' in prompt:
            self.rewrites.append(prompt)
            return GenerateResult(json.dumps(final_answer(prompt, self.shot)), 10, 40, None)
        if '"prompt-audit"' in prompt:
            # The staircase has an independent pre-purchase Director audit after
            # the rewrite review. The deterministic test actor must handle it
            # instead of returning "{}" (which is correctly held as unreviewed).
            scene_ids = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)})
            return GenerateResult(
                json.dumps(
                    {
                        "scenes": [
                            {
                                "scene_index": index,
                                "approved": True,
                                "reason": "The corrected prompt describes the intended movement.",
                            }
                            for index in scene_ids
                        ]
                    }
                ),
                10,
                40,
                None,
            )
        if '"rewrite-review"' in prompt:
            self.reviews.append(prompt)
            said = (
                json.dumps(final_review(answer_each(prompt, self.review)))
                if isinstance(self.review, dict)
                else str(self.review)
            )
            return GenerateResult(said, 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent.id
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = session.scalars(select(Agent.provider_id)).first()
    return {"agents": agents, "provider_id": provider_id}


def agents_say(studio, agents: Agents) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], agents)
    return registry


def a_planned_film(engine, tmp_path, *, still_by: str = "owner") -> str:
    """One filmed scene with its plan, its still approved (by him, or by the stills gate)."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        row.prompt_json = {**dict(row.prompt_json or {}), **PLAN}
        for take in session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        ):
            take.approved_by = still_by
    return storyboard_id


def refused_twice(engine, storyboard_id, tmp_path) -> tuple[Models, Account, SpyVideo]:
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED"),
    )
    assert {t.status for t in shots(engine, storyboard_id)} == {"REJECTED"}
    return models, account, spy


def scene(engine, storyboard_id) -> StoryboardScene:
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        session.expunge(row)
        return row


def test_her_brief_rewrites_the_motion_and_the_shot_is_bought_again_and_passes(
    engine, tmp_path, studio
):
    storyboard_id = a_planned_film(engine, tmp_path)
    models, account, spy = refused_twice(engine, storyboard_id, tmp_path)
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert held["held"] == [1] and held["to_buy"] == []
    before = scene(engine, storyboard_id)
    agents = Agents()

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome
    # She read the prompt the vendor was sent and why quality control refused it.
    (asked,) = agents.briefs
    assert "nu se mișcă" in asked and "low grey cloud drifts slowly" in asked
    # He was given her brief.
    (rewrite,) = agents.rewrites
    assert "a frozen, almost still frame" in rewrite and "from left to right" in rewrite
    after = scene(engine, storyboard_id)
    # The picture's words stay: the still he approved is still the scene's still.
    assert after.visual_prompt == before.visual_prompt
    assert after.prompt_json["still_prompt"] == before.prompt_json["still_prompt"]
    assert after.prompt_json["subject"] == PLAN["subject"]
    # The movement is new.
    assert after.prompt_json["camera_move"] == "slow pan right"
    assert after.prompt_json["motion_intent"] is None
    assert after.prompt_json["prompt_format"] == "editor_final_v1"
    # She reviewed his words against the finding before anything was stored: the refusal's
    # words, his new sentence and the difference were put before her.
    (review,) = agents.reviews
    assert "nu se mișcă" in review, review
    assert "grey cloud rolls steadily across the ridges from left to right" in review
    assert '"added"' in review and '"removed"' in review and "director_brief" in review
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["rewritten"] is True and brief.payload["layer"] == MOTION
    assert brief.payload["failures"][0]["code"] == "QC.CLIP"
    assert brief.payload["review_verdict"] == "TREATS" and brief.payload["review_run_id"]
    (rewritten,) = [
        e
        for e in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if e.payload.get("decided_by") == "director"
    ]
    assert rewritten.payload["layer"] == MOTION and rewritten.payload["scene_index"] == 1
    assert rewritten.payload["review"]["verdict"] == "TREATS"
    # Her brief and his answer are letters between them, settled.
    with Session(engine) as session:
        letters = session.scalars(select(AgentMessage).order_by(AgentMessage.created_at)).all()
        mine = [m for m in letters if "Rescrie scena 1" in m.subject]
    assert len(mine) == 2
    assert mine[0].from_agent_id == studio["agents"]["Director"]
    assert mine[0].to_agent_id == studio["agents"]["VideoEditor"]
    assert mine[1].in_reply_to == mine[0].id
    assert {m.status for m in mine} == {"RESOLVED"}
    assert "Evită: a frozen, almost still frame" in (mine[0].body_text or "")

    # Her rewrite lifts the hold: the shot is bought again, on the new words, and passes.
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert plan["held"] == [] and plan["to_buy"] == [1]
    posted = models.posts()
    summary = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("PASSED"),
    )
    assert models.posts() == posted + 1
    # The words sent are the rewritten package as rendered, not merely other words
    # (2026-10-13): a retry's firmer prompt or a stale intent would also differ.
    expected, _negative = motion_prompt_for(after.prompt_json, "seedance2_5", None)
    assert spy.asked[-1]["prompt"] == expected
    assert "from left to right" in expected and "from left to right" not in spy.asked[0]["prompt"]
    (entry,) = summary["scenes"]
    assert entry["status"] == "PAID"


def test_after_a_motion_rewrite_failed_again_only_the_picture_is_rewritten(
    engine, tmp_path, studio
):
    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")
    models, account, _spy = refused_twice(engine, storyboard_id, tmp_path)
    assert rewrite_failed_scene(
        engine, agents_say(studio, Agents()), storyboard_id, 1, str(uuid4())
    )["rewritten"]
    # The new movement fails too.
    approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        clip_check=ScriptedCheck("FAILED"),
    )
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (STILL,)
    before = scene(engine, storyboard_id)

    # A brief that asks for the movement again is not one this scene can take.
    stubborn = Agents()
    refused = rewrite_failed_scene(
        engine, agents_say(studio, stubborn), storyboard_id, 1, str(uuid4())
    )
    assert refused["rewritten"] is False and len(stubborn.briefs) == 2
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json

    agents = Agents(brief={**BRIEF, "layer": "still"}, shot=STILL_SHOT)
    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    (asked,) = agents.briefs
    assert "Only still is open" in asked
    after = scene(engine, storyboard_id)
    assert after.visual_prompt != before.visual_prompt
    assert "terraced rice fields" in after.visual_prompt.lower()
    assert after.prompt_json["still_prompt"] == after.visual_prompt
    # The scene needs its new still before any motion.
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    (row,) = plan["scenes"]
    assert row["status"] == "NEEDS_STILL"


def test_a_still_he_approved_is_never_rewritten_and_no_director_rewrites_nothing(
    engine, tmp_path, studio
):
    storyboard_id = a_planned_film(engine, tmp_path, still_by="owner")
    refused_twice(engine, storyboard_id, tmp_path)
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION,)
    before = scene(engine, storyboard_id)

    picture = Agents(brief={**BRIEF, "layer": "still"}, shot=STILL_SHOT)
    outcome = rewrite_failed_scene(
        engine, agents_say(studio, picture), storyboard_id, 1, str(uuid4())
    )
    assert outcome["rewritten"] is False
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json

    nobody = rewrite_failed_scene(engine, None, storyboard_id, 1, str(uuid4()))
    assert nobody["rewritten"] is False and "Director" in nobody["reason"]
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert held["held"] == [1]


def test_the_days_staircase_has_her_rewrite_the_refused_scene_and_walks_on(
    engine, tmp_path, studio, settings
):
    from app.runbook import stages

    storyboard_id = a_planned_film(engine, tmp_path)
    models, account, _spy = refused_twice(engine, storyboard_id, tmp_path)
    agents = Agents()
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": None,
        "account": account,
        "adapter_for_model": models,
        "resolution": "1080p",
        "storage_root": tmp_path / "media",
    }

    film = stages._film_staircase(
        engine,
        settings,
        agents_say(studio, agents),
        storyboard_id,
        wiring,
        "TEST",
        str(uuid4()),
    )

    (rung,) = film["director_ladder"]
    assert rung["scenes"] == [1]
    assert [item["scene_index"] for item in rung["rewritten"]] == [1]
    # Walked again on the new words: in TEST the Owner is asked for the shot, nothing waits
    # for his decision on the scene any more.
    assert film["status"] == "ASKED", film
    assert len(agents.briefs) == 1


def test_a_paid_redo_after_the_film_failed_is_bought_only_on_a_corrected_prompt(
    engine, tmp_path, studio
):
    """«Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!»: the redo
    she decided after the finished film failed QC is preceded by her brief and his rewrite;
    when the prompt could not be corrected nothing is bought on the same words."""
    from types import SimpleNamespace

    from app.runbook import stages

    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")
    before = scene(engine, storyboard_id)
    proposals = [
        SimpleNamespace(scene_index=1, redo="still", reason="the still shows a face", free=False)
    ]
    reading = {"findings": [{"scene_index": 1, "text": "Scena 1: o față se vede din profil"}]}

    refused = stages._correct_before_redo(
        engine, None, storyboard_id, 1, ["still", "motion"], proposals, reading, "c"
    )
    assert refused is not None
    assert refused["status"] == stages.PROMPT_NOT_CORRECTED and refused["redo"] == "still"
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json

    agents = Agents(brief={**BRIEF, "layer": "still"}, shot=STILL_SHOT)
    corrected = stages._correct_before_redo(
        engine,
        agents_say(studio, agents),
        storyboard_id,
        1,
        ["still", "motion"],
        proposals,
        reading,
        "c",
    )

    assert corrected is None
    (asked,) = agents.briefs
    assert "the still shows a face" in asked and "o față se vede din profil" in asked
    assert "you decided to redo this scene's still" in asked
    after = scene(engine, storyboard_id)
    assert "terraced rice fields" in after.visual_prompt.lower()
    assert after.prompt_json["still_prompt"] == after.visual_prompt

    # A scene with no plan to rewrite goes on as it would have.
    other = a_film(engine, tmp_path, scenes=1)
    assert stages._correct_before_redo(engine, None, other, 1, ["motion"], [], {}, "c") is None


def test_a_walk_whose_rewrite_did_not_land_says_the_studio_retries_not_the_owner(
    engine, tmp_path, studio, settings
):
    """Review of 2026-10-11: with no Director (or a brief refused twice) the walk still read
    «așteaptă decizia Proprietarului», the words of a film waiting for him, while the ladder
    retry pass was going to walk it again by itself."""
    from app.runbook import stages

    storyboard_id = a_planned_film(engine, tmp_path)
    models, account, _spy = refused_twice(engine, storyboard_id, tmp_path)
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": None,
        "account": account,
        "adapter_for_model": models,
        "resolution": "1080p",
        "storage_root": tmp_path / "media",
    }

    film = stages._film_staircase(
        engine, settings, None, storyboard_id, wiring, "TEST", str(uuid4())
    )

    assert film["status"] == "WAITING" and film["refusal"] == "NEEDS_OWNER"
    (rung,) = film["director_ladder"]
    assert rung["rewritten"] == [] and rung["not_rewritten"][0]["scene_index"] == 1
    assert film["reason"].startswith("Directoarea nu a putut încă rescrie scena 1")
    assert "Director" in film["reason"] and "reia singur" in film["reason"]
    assert "decizia Proprietarului" not in film["reason"]


def test_a_motion_rewrite_that_came_back_the_same_is_the_movements_turn_taken(
    engine, tmp_path, studio
):
    """2026-10-12, the cyclotron's scene 5: the Director's brief rewrote the movement every hour
    and the words came back the same, so nothing was recorded as rewritten and the ladder kept
    the movement open. A motion attempt that changed nothing on a picture that stays counts
    like one that landed: the picture's turn (the words on the attempts recorded before the
    flag, the flag since)."""
    from app.services import append_event

    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION, STILL)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            BRIEF_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "scene_index": 1,
                "layer": "motion",
                "asked_layer": "motion",
                "rewritten": False,
                "reason": "Rescrierea a dat același prompt; nimic nou de cumpărat.",
            },
            str(uuid4()),
        )
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (STILL,)
        # A brief refused for another reason (his rewrite blocked by the lint) is no attempt.
    with Session(engine) as session, session.begin():
        append_event(
            session,
            BRIEF_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "scene_index": 1,
                "layer": "still",
                "asked_layer": "still",
                "rewritten": True,
                "same_prompt": False,
                "reason": "",
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
                "scene_index": 1,
                "layer": "motion",
                "asked_layer": "motion",
                "rewritten": False,
                "same_prompt": False,
                "reason": "Verificarea promptului a blocat rescrierea: STILL_LENGTH",
            },
            str(uuid4()),
        )
    with Session(engine) as session:
        # The still rewrite started the count again; the blocked attempt did not count.
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION, STILL)


def test_a_rewrite_that_does_not_treat_the_finding_is_not_stored_and_nothing_is_bought(
    engine, tmp_path, studio
):
    """Owner, 2026-10-12, on film 1c038a99's scene 5 redone five times: «Dacă se reface ceva,
    trebuie să ne asigurăm că promptul de regenerare este impecabil. Adică, tratează problema?»
    Her review of his rewrite says MISSES: he is asked once more with her why_not (since
    2026-10-12, f06808c9 scenes 3, 4, 7), and when he sends the refused words again nothing is
    stored, the hold stays, the record carries the verdict for the next brief, his letter says
    the review refused it, and the paid redo's correction is refused the same way (the brake
    `_correct_before_redo` reads)."""
    storyboard_id = a_planned_film(engine, tmp_path)
    refused_twice(engine, storyboard_id, tmp_path)
    before = scene(engine, storyboard_id)
    agents = Agents(review=MISSED)

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is False and outcome["not_treating"] is True, outcome
    assert outcome["reason"].startswith("Rescrierea nu tratează constatarea")
    assert outcome["review_verdict"] == "MISSES" and outcome["same_prompt"] is False
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json
    # He rewrote twice, the second time with her why_not; his second answer was the refused
    # words again, so she was not asked to read them twice — and the motion layer, with
    # nothing else to say, is exhausted: the picture's turn, but the Owner approved it.
    assert len(agents.rewrites) == 2 and len(agents.reviews) == 1
    assert "it can turn its head" in agents.rewrites[1]
    assert "aceleași cuvinte pe care Directoarea le-a refuzat" in outcome["reason"]
    assert outcome["layer_exhausted"] is True and "escalated_from" not in outcome
    assert "nu se mișcă" in agents.reviews[0] and "grey cloud rolls steadily" in agents.reviews[0]
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["rewritten"] is False and brief.payload["not_treating"] is True
    assert brief.payload["review_verdict"] == "MISSES" and brief.payload["review_run_id"]
    assert "fața din profil" in brief.payload["review_reason_ro"]
    assert brief.payload["same_prompt"] is False
    assert [
        e
        for e in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if e.payload.get("decided_by") == "director"
    ] == []
    # The next brief is shown why the last rewrite was refused.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["review_verdict"] == "MISSES" and "nu tratează constatarea" in shown["reason"]
    # ...and why: the words that caused the defect, why the finding stayed, the rule drawn.
    assert shown["cause"] == MISSED["cause"] and shown["lesson"] == MISSED["lesson"]
    assert shown["why_not"] == [
        {"finding": "a face seen in profile", "why_not": MISSED["findings"][0]["why_not"]}
    ]
    # A refused rewrite is no motion attempt: both layers stay open for her next brief.
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION,)
    # The hold stays: nothing is bought on words that do not treat the finding.
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert held["held"] == [1] and held["to_buy"] == []
    # His letter back says the review refused it, and why.
    with Session(engine) as session:
        letters = session.scalars(select(AgentMessage).order_by(AgentMessage.created_at)).all()
        reply = next(m for m in letters if m.in_reply_to and "Rescrie scena 1" in m.subject)
        assert "a refuzat rescrierea" in (reply.body_text or "")
        assert "fața din profil" in (reply.body_text or "")

    # The redo she decided after the finished film failed: refused the same way, nothing bought.
    again = rewrite_for_redo(
        engine,
        agents_say(studio, Agents(review=MISSED)),
        storyboard_id,
        1,
        "motion",
        ["the clip barely moved"],
        str(uuid4()),
    )
    assert again["rewritten"] is False and again["rewritable"] is True, again
    assert again["not_treating"] is True and again["same_prompt"] is False
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json


def test_a_rewrite_nobody_could_review_is_not_stored(engine, tmp_path, studio):
    """Nothing is bought on words nobody verified: a review that cannot be read twice fails
    closed, like one that says MISSES, and the record says the review could not be made."""
    storyboard_id = a_planned_film(engine, tmp_path)
    refused_twice(engine, storyboard_id, tmp_path)
    before = scene(engine, storyboard_id)
    agents = Agents(review="I would rather not say.")

    outcome = rewrite_failed_scene(
        engine, agents_say(studio, agents), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is False and outcome["review_unavailable"] is True, outcome
    assert "nu a putut fi verificată" in outcome["reason"]
    assert outcome["review_verdict"] is None and "not_treating" in outcome
    assert scene(engine, storyboard_id).prompt_json == before.prompt_json
    # Asked twice (no object at all: the thinking retry), then nothing more today.
    assert len(agents.reviews) == 2
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["rewritten"] is False and brief.payload["review_verdict"] is None
    assert "nu a putut fi verificată" in brief.payload["reason"]
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"]
    assert held["held"] == [1]


def test_a_rewrite_that_comes_back_with_the_same_words_tells_the_redo_so(engine, tmp_path, studio):
    """2026-10-12, the cyclotron's scenes 4 and 5: the redo's rewrite of the movement came back
    with the same words every hour, the paid redo was refused PROMPT_NOT_CORRECTED and the
    Director wrote to the Owner about a «tooling defect». The outcome of `rewrite_for_redo`
    now says `same_prompt`, so the repair turns to the picture (`_correct_before_redo`)."""
    from app.media.scene_rewrite import rewrite_for_redo

    storyboard_id = a_planned_film(engine, tmp_path, still_by="still_gate")
    reasons = ["the glow replaced the pencil drawing"]
    # The first rewrite lands: the stored movement is now the Video Editor's own words.
    first = rewrite_for_redo(
        engine, agents_say(studio, Agents()), storyboard_id, 1, "motion", reasons, str(uuid4())
    )
    assert first["rewritten"] is True and first["same_prompt"] is False, first
    stored = dict(scene(engine, storyboard_id).prompt_json)

    # Asked again, he answers the same words.
    again = rewrite_for_redo(
        engine, agents_say(studio, Agents()), storyboard_id, 1, "motion", reasons, str(uuid4())
    )

    assert again["rewritten"] is False and again["same_prompt"] is True, again
    assert "același prompt" in again["reason"]
    assert scene(engine, storyboard_id).prompt_json == stored
    briefs = [e for e in events(engine, BRIEF_EVENT) if e.payload.get("scene_index") == 1]
    assert [b.payload["same_prompt"] for b in briefs] == [False, True]
    assert [b.payload["rewritten"] for b in briefs] == [True, False]
