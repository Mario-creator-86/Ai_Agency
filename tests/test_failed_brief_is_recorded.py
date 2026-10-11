"""A brief of hers that failed is recorded like one that rewrote the scene (2026-10-11).

14:20:57 UTC, the cyclotron film: the Director's brief for a refused scene was refused twice by
its schema, `rewrite_failed_scene` returned the reason and wrote nothing, so the walk stopped
WAITING NEEDS_OWNER with nothing to show that she had tried; `earlier_briefs` could not see the
attempt and the watchdog had nothing to read, and the film waited until an unrelated take
approval walked it again at 14:31. Now a brief that failed — refused twice, no Director, a fault
while asking — is a BRIEF_EVENT with rewritten False and the reason: the attempt she is shown
next time and the watchdog's ladder retry reads. Every provider faked, 0 credits.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import AgentMessage, ModelRecord
from app.agents.services import seed_initial_workforce
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.scene_rewrite import BRIEF_EVENT, earlier_briefs, rewrite_failed_scene
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import events
from test_film_costing import a_film

#: Scene 1's plan, as the Video Editor wrote it (the fixture film carries only its prompts).
PLAN = {
    "subject": "a far village of stone houses on a terraced slope",
    "action": "the village rests below steep ridges",
    "environment": "steep Himalayan ridges under low cloud",
    "camera": "wide establishing shot, 24mm lens, seen from high above",
    "lighting": "soft overcast daylight",
    "motion": "low grey cloud drifts slowly over the ridges",
}
#: A brief for the picture of a scene whose picture the Owner approved: not a layer it can take.
STILL_BRIEF = {
    "diagnosis": "The picture itself invites the face: a figure that can turn its head.",
    "layer": "still",
    "avoid": ["a figure whose face can turn to the camera"],
    "keep": ["the village on its terraced slope"],
    "change": ["hands and tools in close-up, no figure"],
    "summary_ro": "Refac imaginea fără chip.",
}


class Director:
    """Her model, scripted: the same brief every time she is asked."""

    def __init__(self, brief: dict[str, Any]):
        self.brief = brief
        self.briefs: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        if '"scene-brief"' in prompt:
            self.briefs.append(prompt)
            return GenerateResult(json.dumps(self.brief), 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        return {"provider_id": session.scalars(select(ModelRecord.provider_id)).first()}


def she_says(studio, director: Director) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], director)
    return registry


def a_refused_scene(engine, tmp_path) -> str:
    """One planned scene, its still approved by the Owner, its clip refused by quality control
    (the take written as the clip QC leaves it: no vendor, no credits)."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    now = utc_now()
    with Session(engine) as session, session.begin():
        assert session.get(Storyboard, storyboard_id).status == "APPROVED"
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        row.prompt_json = {**dict(row.prompt_json or {}), **PLAN}
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="test_shot",
                prompt_hash=uuid4().hex,
                model_id="seedance2_5",
                resolution="1080:1920",
                status="REJECTED",
                failure_code="QC.CLIP",
                failure_detail="o față se vede din profil",
                path=None,
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )
    return storyboard_id


def test_a_brief_refused_twice_is_recorded_with_its_reason(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)
    director = Director(STILL_BRIEF)

    outcome = rewrite_failed_scene(
        engine, she_says(studio, director), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is False
    assert "layer still is not open" in outcome["reason"]
    # Asked twice: the second time with the refusal quoted, not with her thinking on.
    assert len(director.briefs) == 2
    assert "Your previous answer was refused" in director.briefs[1]
    (attempt,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert attempt.payload["scene_index"] == 1 and attempt.payload["rewritten"] is False
    assert "layer still is not open" in attempt.payload["reason"]
    assert attempt.payload["failures"][0]["code"] == "QC.CLIP"
    assert attempt.payload["brief_run_id"] and attempt.payload["rewrite_run_id"] is None
    assert attempt.payload["diagnosis"] is None and attempt.payload["message_id"] is None
    # She is shown the attempt next time, with why it failed.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["rewritten"] is False and "layer still is not open" in shown["reason"]
    # No letter to the Video Editor: there was no brief to hand him.
    with Session(engine) as session:
        assert session.scalars(select(AgentMessage)).all() == []


def test_with_no_director_the_attempt_is_recorded_too(engine, tmp_path):
    storyboard_id = a_refused_scene(engine, tmp_path)

    outcome = rewrite_failed_scene(engine, None, storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and "Director" in outcome["reason"]
    (attempt,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert attempt.payload["rewritten"] is False
    assert attempt.payload["reason"] == outcome["reason"]
    assert attempt.payload["brief_run_id"] is None


def test_a_fault_while_asking_her_is_recorded_too(engine, tmp_path, studio, monkeypatch):
    from app.media import scene_rewrite

    storyboard_id = a_refused_scene(engine, tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("the provider hung up")

    monkeypatch.setattr(scene_rewrite, "director_brief", broken)

    outcome = rewrite_failed_scene(
        engine, she_says(studio, Director(STILL_BRIEF)), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is False and "RuntimeError" in outcome["reason"]
    (attempt,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert attempt.payload["rewritten"] is False and "RuntimeError" in attempt.payload["reason"]
