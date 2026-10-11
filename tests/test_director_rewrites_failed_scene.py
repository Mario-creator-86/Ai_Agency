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
  walks the film again.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, motion_plan
from app.media.models import SceneTake, StoryboardScene
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    MOTION,
    STILL,
    open_layers,
    rewrite_failed_scene,
)
from app.media.toolchain import find_ffmpeg
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
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


class Agents:
    """Every agent's model, scripted: the Director's brief, the Video Editor's shot."""

    def __init__(self, brief: Any = None, shot: Any = None):
        self.brief = dict(BRIEF) if brief is None else brief
        self.shot = dict(SHOT) if shot is None else shot
        self.briefs: list[str] = []
        self.rewrites: list[str] = []

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
            return GenerateResult(json.dumps(self.shot), 10, 40, None)
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
    assert after.prompt_json["motion_intent"] != before.prompt_json["motion_intent"]
    assert "a frozen, almost still frame" in after.prompt_json["avoid"]
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["rewritten"] is True and brief.payload["layer"] == MOTION
    assert brief.payload["failures"][0]["code"] == "QC.CLIP"
    (rewritten,) = [
        e
        for e in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if e.payload.get("decided_by") == "director"
    ]
    assert rewritten.payload["layer"] == MOTION and rewritten.payload["scene_index"] == 1
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
    assert spy.asked[-1]["prompt"] != spy.asked[0]["prompt"]
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
