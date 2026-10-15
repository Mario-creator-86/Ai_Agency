"""Complete messages and answers survive every internal LLM boundary."""

import json
from uuid import uuid4

import pytest
from app.agents.identity import clipped, compose_identity, fit_to_schema, joined, parse_structured
from app.agents.memory import remember
from app.agents.messages import post_message, resolve_message
from app.agents.models import Agent
from app.agents.services import run_agent_task
from app.economy import repurchase_gate
from app.providers.base import GenerateResult
from app.providers.registry import ProviderRegistry
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from test_agent_identity import staffed  # noqa: F401


def test_schema_normalization_keeps_every_character_and_every_list_item():
    class Item(BaseModel):
        reason: str = Field(max_length=20)

    class Decision(BaseModel):
        items: list[Item] = Field(max_length=1)

    data = {"items": [{"reason": "Required ending condition " * 3}] * 8}
    assert fit_to_schema(data, Decision) == data
    parsed = parse_structured(json.dumps(data), Decision)
    assert isinstance(parsed, Decision) and parsed.model_dump() == data


def test_compatibility_validators_join_but_never_clip_text():
    text = "All conditions " * 1000 + "THE REQUIRED END"
    assert clipped(10)(text) == text
    assert joined(10)([text, "Last line"]) == text + "\nLast line"


def test_memory_and_message_resolution_store_the_complete_text(engine, staffed):  # noqa: F811
    agent = staffed["agents"]["VideoEditor"]
    text = "Every QC finding and its proposed correction. " * 300 + "THE REQUIRED END"
    with Session(engine) as session, session.begin():
        record = remember(
            session,
            memory_class="TEMP_CONTEXT",
            content=text,
            source_type="system",
            agent_id=agent.id,
        )
        assert record.content == text
        message = post_message(
            session,
            intent="HANDOFF",
            subject="Complete assignment",
            body={},
            to_agent_id=agent.id,
            body_text=text,
        )
        resolve_message(session, message.id, resolution=text, resolved_by="Director")
        assert message.body_text == text and message.resolution == text


def test_every_open_message_and_the_whole_thread_reach_the_identity(engine, staffed):  # noqa: F811
    agent = staffed["agents"]["VideoEditor"]
    sender = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        first = post_message(
            session,
            intent="HANDOFF",
            subject="Thread",
            body={},
            from_agent_id=sender.id,
            to_agent_id=agent.id,
            body_text="FIRST REQUIRED INSTRUCTION " + "Evidence " * 300,
        )
        first.status = "RESOLVED"
        for i in range(15):
            post_message(
                session,
                intent="HANDOFF",
                subject=f"Scene correction {i}",
                body={},
                from_agent_id=sender.id,
                to_agent_id=agent.id,
                in_reply_to=first.id,
                body_text="Evidence " * 300 + f"REQUIRED END {i}",
            )
        identity = compose_identity(session, session.get(Agent, agent.id))
        assert len(identity.context["open_message_ids"]) == 15
        assert "FIRST REQUIRED INSTRUCTION" in identity.system
        for i in range(15):
            assert f"REQUIRED END {i}" in identity.system


@pytest.mark.parametrize("role_name,director_factor", [("VideoEditor", 1), ("Director", 2)])
def test_all_employee_output_allowances_are_multiplied_once_and_input_is_complete(
    engine,
    settings,
    staffed,  # noqa: F811
    monkeypatch,
    role_name,
    director_factor,  # noqa: F811
):
    import app.agents.services as services

    monkeypatch.setattr(services, "_studio_settings", lambda: settings)
    calls = []

    class Model:
        async def generate(self, model, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            return GenerateResult("Complete answer", 10, 20, None)

    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Model())
    prompt = "The complete current dossier. " * 1500 + "FINAL BUDGET 20 USD"
    result = run_agent_task(
        engine,
        registry,
        staffed["agents"][role_name].id,
        "test_complete_context",
        prompt,
        "complete-context-v1",
        str(uuid4()),
        max_tokens=3600,
    )
    assert result["status"] == "SUCCEEDED"
    assert calls[0]["prompt"] == prompt
    assert calls[0]["max_tokens"] == 3600 * director_factor * 10
    limits = result["context_json"]["generation_limits"]
    assert limits["context_multiplier"] == 10


def test_nadias_refusal_preserves_all_findings_and_the_full_reason():
    reason = ("The corrected ending must remain visible. " * 200).strip()
    reasons = [f"QC finding {i}: " + reason for i in range(30)]
    reading = {"findings": [{"scene_index": 1, "text": text} for text in reasons]}
    assert repurchase_gate._reasons(reading, [], 1) == reasons
    assert repurchase_gate._held(reason)["reason"] == reason


def test_semantic_errors_are_refused_without_shortening_the_answer():
    class Limited(BaseModel):
        reason: str = Field(max_length=10)
        decision: str = Field(pattern="^(APPROVE|REFUSE)$")

    answer = {"reason": "z" * 101, "decision": "INVALID"}
    assert fit_to_schema(answer, Limited) == answer
    assert parse_structured(json.dumps(answer), Limited) is None


def test_prompt_payload_keeps_claims_lessons_and_scenes_even_over_the_old_budget():
    from app.media.prompt_agent import trim_payload

    payload = {
        "film": {"scenes": [{"scene_index": 1, "claims": ["Whole evidence " * 3000]}]},
        "lessons": ["Preserve the final required condition"],
    }
    result, dropped = trim_payload(payload, 12000)
    assert result == payload and not any(dropped.values())


def test_director_editorial_judgement_reads_the_complete_story():
    from app.agents.editorial_judgement import judgement_prompt

    story = "The complete story and its dialogue. " * 1000 + "FINAL REQUIRED TWIST"
    prompt = judgement_prompt(story, "serial_episode", {"title": "Current serial"})
    assert story in prompt and "text_cut_at" not in prompt


def test_rewrite_review_keeps_every_observation_and_its_ending():
    from app.media.scene_rewrite import RewriteReview

    observations = ["QC observation " * 100 + f"REQUIRED END {i}" for i in range(12)]
    review = {
        "verdict": "TREATS",
        "findings": [{"id": 1, "treated": True, "severity": "serious", "by": "Corrected words"}],
        "observations": observations,
        "reason_ro": "Treats the current defects",
        "cause": "Current prompt",
    }
    parsed = parse_structured(json.dumps(review), RewriteReview)
    assert parsed is not None and parsed.observations == observations


def test_the_editors_shot_plan_keeps_the_complete_action_and_ending():
    from app.media.prompt_agent import parse_shot_plan

    action = "Sarah and Nadia remain in frame with their correct clothes. " * 40
    action += "FINAL REQUIRED CONDITION: Sarah is visible on the right edge."
    parsed = parse_shot_plan(json.dumps({"shots": [{"scene_index": 1, "action": action}]}))
    assert parsed.shots[1].action == action


def test_the_models_full_answers_reach_the_peer_review():
    from app.agents.ensemble import _critique_prompt, _judge_prompt

    text = "All required evidence and conditions. " * 400 + "FINAL CONDITION"
    assert (
        _critique_prompt(
            objective=text, evidence=text, answer=text, review_objective="Check all conditions"
        ).count("FINAL CONDITION")
        == 3
    )
    assert (
        _judge_prompt(text, text, {"output_text": text}, {"output_text": text}, text).count(
            "FINAL CONDITION"
        )
        == 5
    )


def test_a_provider_length_stop_is_reported_and_the_visible_text_is_preserved(
    engine,
    settings,
    staffed,  # noqa: F811
    monkeypatch,  # noqa: F811
):
    import app.agents.services as services

    monkeypatch.setattr(services, "_studio_settings", lambda: settings)

    class Model:
        async def generate(self, model, prompt, **kwargs):
            return GenerateResult(
                "The preserved partial visible reply",
                10,
                20,
                None,
                raw_response={"done_reason": "length"},
            )

    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], Model())
    result = run_agent_task(
        engine,
        registry,
        staffed["agents"]["VideoEditor"].id,
        "test_complete_context",
        "Complete prompt",
        "complete-context-v1",
        str(uuid4()),
        max_tokens=3600,
    )
    assert result["status"] == "INCOMPLETE_OUTPUT"
    assert result["output_text"] == "The preserved partial visible reply"
