"""Observed token exhaustion changes the next request, without model-name assumptions."""

from uuid import uuid4

from app.agents.memory import agent_for_role
from app.agents.models import AgentRun, ModelRecord, ProviderRecord
from app.agents.services import seed_initial_workforce
from app.media.prompt_agent import PROMPT_ROLE, shot_generation_profile, shot_payload_batches
from app.services import utc_now
from sqlalchemy.orm import Session


def test_exhaustion_selects_native_single_scene_work_and_a_configurable_allowance(
    engine, monkeypatch
):
    seed_initial_workforce(engine)
    monkeypatch.setenv("STUDIO_SHOT_PLAN_OUTPUT_TOKENS", "6000")
    monkeypatch.setenv("STUDIO_SHOT_PLAN_RECOVERY_OUTPUT_TOKENS", "18000")
    with Session(engine) as session, session.begin():
        editor = agent_for_role(session, PROMPT_ROLE)
        model = session.get(ModelRecord, editor.model_id)
        provider = session.get(ProviderRecord, model.provider_id)
        editor_id = editor.id
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=editor_id,
                task_type="shot_prompts",
                objective="test",
                prompt_template_version="shot-prompts-v3+think",
                model_name=model.model_name,
                provider_name=provider.name,
                status="EMPTY_OUTPUT",
                completion_tokens=6000,
                started_at=utc_now(),
                correlation_id=str(uuid4()),
                context_json={"generation_limits": {"effective_max_tokens": 6000}},
            )
        )
    profile = shot_generation_profile(engine, editor_id)
    assert profile.native_thinking and profile.max_tokens == 18000 and profile.max_scenes == 1
    scenes = [
        {"scene_index": i, "claims": ["whole claim"], "narration": "whole line"}
        for i in range(1, 4)
    ]
    data = {
        "film": {"scenes": scenes, "story": "whole story"},
        "repair_context": {"issues": ["all findings"]},
    }
    batches = shot_payload_batches(data, ["full QC rule"], max_scenes=profile.max_scenes)
    assert [batch["film"]["scenes"][0] for batch in batches] == scenes
    assert all(batch["repair_context"] == data["repair_context"] for batch in batches)
    assert all(batch["film"]["story"] == "whole story" for batch in batches)
    assert all(batch["lessons"] == ["full QC rule"] for batch in batches)


def test_an_unobserved_model_keeps_the_initial_allowance(engine, monkeypatch):
    seed_initial_workforce(engine)
    monkeypatch.setenv("STUDIO_SHOT_PLAN_OUTPUT_TOKENS", "5000")
    with Session(engine) as session:
        editor = agent_for_role(session, PROMPT_ROLE)
    profile = shot_generation_profile(engine, editor.id)
    assert profile.max_tokens == 5000 and not profile.native_thinking
    assert profile.max_scenes is None
