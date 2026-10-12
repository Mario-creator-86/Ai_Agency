"""Phase 1 tests: agents, roles, capabilities, providers, policy kernel."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.models import (
    Agent,
    AgentRun,
    Capability,
    ModelCapability,
    ModelRecord,
    ProviderRecord,
    Role,
    RoleCapability,
    ToolReceipt,
)
from app.agents.services import (
    list_agents,
    list_providers,
    list_roles,
    run_agent_task,
)
from app.db import create_db_engine, migrate
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import HealthResult
from app.providers.registry import ProviderRegistry
from app.services import bootstrap_studio, utc_now
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def phase1_engine(settings):
    """Engine with Phase 0 + Phase 1 migrations applied."""
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(phase1_engine):
    """Seed capabilities, role, provider, models, and agents. Returns plain IDs."""
    engine = phase1_engine
    # Capture all IDs *inside* the session scope before it closes
    ids: dict = {}

    with Session(engine) as session, session.begin():
        root_event = session.scalars(select(DomainEvent).limit(1)).first()
        eid = root_event.event_id

        cap_text = Capability(
            id=str(uuid4()), name="text_generation", description="Basic text generation"
        )
        cap_tool = Capability(
            id=str(uuid4()), name="tool_calling", description="Structured tool calling"
        )
        session.add_all([cap_text, cap_tool])
        session.flush()

        role = Role(
            id=str(uuid4()),
            name="Director",
            mission="Oversee studio production",
            allowed_task_types="plan,review,decide",
            prohibited_actions="self_escalate,fabricate_capability",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add(role)
        session.flush()

        session.add(
            RoleCapability(
                role_id=role.id,
                capability_id=cap_text.id,
                requirement_level="REQUIRED",
            )
        )

        provider = ProviderRecord(
            id=str(uuid4()),
            name="local-ollama",
            provider_type="OLLAMA",
            base_url="http://127.0.0.1:11434",
            status="NOT_CONFIGURED",
            last_health_check=None,
            adapter_version="1.0.0",
            notes="",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add(provider)
        session.flush()

        model_capable = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name="llama3.2:latest",
            discovery_method="MANUALLY_CONFIGURED",
            context_length=None,
            last_verified=None,
            is_available=True,
            notes="",
        )
        model_incapable = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name="embedding-only:v1",
            discovery_method="MANUALLY_CONFIGURED",
            context_length=None,
            last_verified=None,
            is_available=True,
            notes="embeddings only",
        )
        session.add_all([model_capable, model_incapable])
        session.flush()

        session.add(
            ModelCapability(
                model_id=model_capable.id,
                capability_id=cap_text.id,
                confidence="MANUALLY_CONFIGURED",
            )
        )

        agent_active = Agent(
            id=str(uuid4()),
            display_name="Alice (Director)",
            role_id=role.id,
            provider_id=provider.id,
            model_id=model_capable.id,
            lifecycle="ACTIVE",
            runtime_state="IDLE",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=None,
            event_id=eid,
        )
        agent_terminated = Agent(
            id=str(uuid4()),
            display_name="Bob (Former)",
            role_id=role.id,
            provider_id=provider.id,
            model_id=model_capable.id,
            lifecycle="TERMINATED",
            runtime_state="IDLE",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=utc_now(),
            event_id=eid,
        )
        agent_no_cap = Agent(
            id=str(uuid4()),
            display_name="Charlie (embed)",
            role_id=role.id,
            provider_id=provider.id,
            model_id=model_incapable.id,
            lifecycle="ACTIVE",
            runtime_state="IDLE",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=None,
            event_id=eid,
        )
        session.add_all([agent_active, agent_terminated, agent_no_cap])
        session.flush()

        # Capture all IDs before session closes
        ids["role_id"] = role.id
        ids["provider_id"] = provider.id
        ids["model_capable_id"] = model_capable.id
        ids["model_incapable_id"] = model_incapable.id
        ids["agent_active_id"] = agent_active.id
        ids["agent_terminated_id"] = agent_terminated.id
        ids["agent_no_cap_id"] = agent_no_cap.id
        ids["cap_text_id"] = cap_text.id

    ids["engine"] = engine
    return ids


def empty_registry() -> ProviderRegistry:
    return ProviderRegistry()


def clear_stop(engine) -> None:
    """Disable autonomy stop so policy gate passes."""
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.version += 1


# ---------------------------------------------------------------------------
# Migration / schema
# ---------------------------------------------------------------------------


def test_phase1_migration_creates_all_tables(phase1_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.agents.models import Agent  # noqa: F401
    from app.models import Base

    with phase1_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"Schema drift: {diff}"


# ---------------------------------------------------------------------------
# Role and agent listing
# ---------------------------------------------------------------------------


def test_list_roles_empty_initially(phase1_engine):
    assert list_roles(phase1_engine) == []


def test_list_roles_returns_seeded_role_with_capabilities(seeded):
    roles = list_roles(seeded["engine"])
    assert len(roles) == 1
    assert roles[0]["name"] == "Director"
    assert "text_generation" in roles[0]["required_capabilities"]


def test_list_agents_returns_all_three(seeded):
    agents = list_agents(seeded["engine"])
    assert len(agents) == 3
    names = {a["display_name"] for a in agents}
    assert "Alice (Director)" in names


def test_list_providers_returns_not_configured(seeded):
    providers = list_providers(seeded["engine"])
    assert len(providers) == 1
    assert providers[0]["status"] == "NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Policy kernel: autonomy stop
# ---------------------------------------------------------------------------


def test_autonomy_stop_blocks_run(seeded):
    """Bootstrap sets autonomy_stopped=True -> every run is blocked."""
    result = run_agent_task(
        seeded["engine"],
        empty_registry(),
        seeded["agent_active_id"],
        "plan",
        "Draft the day plan.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_POLICY"
    assert "Autonomia studioului este oprită" in result["error_detail"]


# ---------------------------------------------------------------------------
# Policy kernel: lifecycle gate
# ---------------------------------------------------------------------------


def test_terminated_agent_blocked(seeded):
    clear_stop(seeded["engine"])
    result = run_agent_task(
        seeded["engine"],
        empty_registry(),
        seeded["agent_terminated_id"],
        "plan",
        "Some task.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_POLICY"
    assert "TERMINATED" in result["error_detail"]


# ---------------------------------------------------------------------------
# Policy kernel: capability gate
# ---------------------------------------------------------------------------


def test_missing_capability_blocks_run(seeded):
    clear_stop(seeded["engine"])
    result = run_agent_task(
        seeded["engine"],
        empty_registry(),
        seeded["agent_no_cap_id"],
        "plan",
        "This model cannot do text generation.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_CAPABILITY"
    assert "text_generation" in result["error_detail"]


# ---------------------------------------------------------------------------
# Policy kernel: provider offline gate
# ---------------------------------------------------------------------------


def test_offline_provider_blocks_run(seeded):
    clear_stop(seeded["engine"])
    registry = ProviderRegistry()
    registry._health_cache[seeded["provider_id"]] = HealthResult(
        status="OFFLINE", detail="Connection refused"
    )
    result = run_agent_task(
        seeded["engine"],
        registry,
        seeded["agent_active_id"],
        "plan",
        "Objective.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_PROVIDER"


# ---------------------------------------------------------------------------
# No adapter -> BLOCKED_PROVIDER from service layer
# ---------------------------------------------------------------------------


def test_no_adapter_blocks_after_gate_passes(seeded):
    """UNKNOWN status lets gate pass; empty registry has no adapter -> BLOCKED_PROVIDER."""
    clear_stop(seeded["engine"])
    result = run_agent_task(
        seeded["engine"],
        empty_registry(),
        seeded["agent_active_id"],
        "plan",
        "Objective.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_PROVIDER"
    assert result["error_detail"] == "No adapter registered for provider"


# ---------------------------------------------------------------------------
# Tool receipt immutability
# ---------------------------------------------------------------------------


def test_tool_receipt_is_immutable(seeded):
    engine = seeded["engine"]
    run_id = str(uuid4())
    receipt_id = str(uuid4())

    with Session(engine) as session, session.begin():
        root_event = session.scalars(select(DomainEvent).limit(1)).first()
        run = AgentRun(
            id=run_id,
            agent_id=seeded["agent_active_id"],
            task_type="test",
            objective="test objective",
            prompt_template_version="v1",
            model_name="llama3.2:latest",
            provider_name="local-ollama",
            status="SUCCEEDED",
            output=None,
            output_text="result",
            error_detail=None,
            cost_vr=None,
            prompt_tokens=None,
            completion_tokens=None,
            correlation_id=str(uuid4()),
            started_at=utc_now(),
            finished_at=utc_now(),
            event_id=root_event.event_id,
        )
        session.add(run)
        session.flush()
        receipt = ToolReceipt(
            receipt_id=receipt_id,
            run_id=run_id,
            tool_name="health_check",
            status="SUCCEEDED",
            request_summary={"path": "/api/tags"},
            result_summary={"status": "HEALTHY"},
            remote_id=None,
            cost_vr=None,
            called_at=utc_now(),
            returned_at=utc_now(),
        )
        session.add(receipt)

    for query in (
        f"UPDATE tool_receipt SET status='FAILED' WHERE receipt_id='{receipt_id}'",
        f"DELETE FROM tool_receipt WHERE receipt_id='{receipt_id}'",
    ):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(query))


# ---------------------------------------------------------------------------
# Blocked run persisted
# ---------------------------------------------------------------------------


def test_blocked_run_is_persisted(seeded):
    """A policy-blocked run must still be recorded in agent_run."""
    result = run_agent_task(
        seeded["engine"],
        empty_registry(),
        seeded["agent_active_id"],
        "plan",
        "Test.",
        "v1",
        str(uuid4()),
    )
    assert result["status"] == "BLOCKED_POLICY"
    with Session(seeded["engine"]) as session:
        run = session.get(AgentRun, result["id"])
    assert run is not None
    assert run.status == "BLOCKED_POLICY"


# ---------------------------------------------------------------------------
# Successful runs emit the real model output as agent.message_sent
# ---------------------------------------------------------------------------


class _StubAdapter:
    """Minimal provider adapter returning a fixed real-looking answer."""

    def __init__(self, text: str | None = None, fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    async def health_check(self):  # pragma: no cover - gate only reads cached status
        return HealthResult("HEALTHY")

    async def list_models(self):  # pragma: no cover - not used by run_agent_task
        return []

    async def generate(self, model, prompt, **kwargs):
        if self.fail:
            raise RuntimeError("provider exploded")
        from app.providers.base import GenerateResult

        return GenerateResult(self.text, 3, 5, None)


def session_events(engine, event_type):
    with Session(engine) as session:
        return session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == event_type)
            .order_by(DomainEvent.sequence)
        ).all()


def _message_events(engine):
    with Session(engine) as session:
        return session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == "agent.message_sent")
            .order_by(DomainEvent.sequence)
        ).all()


def test_successful_run_emits_real_agent_message(seeded):
    from app.workflows.models import OutboxRecord

    clear_stop(seeded["engine"])
    engine = seeded["engine"]
    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], _StubAdapter("Da, sunt funcțional."))

    result = run_agent_task(
        engine, registry, seeded["agent_active_id"], "plan", "Say you work", "v1", str(uuid4())
    )

    assert result["status"] == "SUCCEEDED"
    events = _message_events(engine)
    assert len(events) == 1
    assert events[0].aggregate_type == "agent"
    assert events[0].aggregate_id == seeded["agent_active_id"]
    assert events[0].payload["text"] == "Da, sunt funcțional."
    assert events[0].payload["run_id"] == result["id"]
    with Session(engine) as session:
        outbox = session.scalars(
            select(OutboxRecord).where(OutboxRecord.event_id == events[0].event_id)
        ).all()
    assert len(outbox) == 1 and outbox[0].status == "PENDING"

    # The office learns the run's phases live: THINKING at start, IDLE at completion.
    state_events = session_events(engine, "agent.state_changed")
    assert [e.payload["runtime_state"] for e in state_events] == ["THINKING", "IDLE"]
    assert all(e.aggregate_id == seeded["agent_active_id"] for e in state_events)


def test_failed_run_emits_no_agent_message(seeded):
    clear_stop(seeded["engine"])
    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], _StubAdapter(fail=True))

    result = run_agent_task(
        seeded["engine"],
        registry,
        seeded["agent_active_id"],
        "plan",
        "Say you work",
        "v1",
        str(uuid4()),
    )

    assert result["status"] == "FAILED"
    assert _message_events(seeded["engine"]) == []


def test_a_run_that_produced_no_text_is_not_recorded_as_a_success(seeded):
    """An answer nobody can read is not an answer: the run says so, and bubbles nothing.

    Thinking models spend the token budget on private reasoning and can return an empty
    visible answer. Recorded as SUCCEEDED, that put a green line in the employee's history
    with nothing under it while every caller failed on "no usable answer".
    """
    clear_stop(seeded["engine"])
    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], _StubAdapter("   "))

    result = run_agent_task(
        seeded["engine"],
        registry,
        seeded["agent_active_id"],
        "plan",
        "Say you work",
        "v1",
        str(uuid4()),
    )

    assert result["status"] == "EMPTY_OUTPUT"
    assert "niciun text" in (result["error_detail"] or "").lower()
    assert _message_events(seeded["engine"]) == []


@pytest.mark.parametrize(
    ("role_name", "requested", "expected"),
    [
        ("Director", 6000, 12000),
        ("Director", 24000, 48000),
        ("Director", None, None),
        ("Research", 6000, 6000),
    ],
)
def test_director_token_budget_is_doubled_by_role_and_recorded(
    seeded, monkeypatch, role_name, requested, expected
):
    from app.agents import services
    from app.config import Settings

    config = Settings(_env_file=None, owner_token="test-owner-token-for-budget-check")
    monkeypatch.setattr(services, "_studio_settings", lambda: config)
    clear_stop(seeded["engine"])
    with Session(seeded["engine"]) as session, session.begin():
        session.get(Role, seeded["role_id"]).name = role_name
    seen = []

    class BudgetAdapter(_StubAdapter):
        async def generate(self, model, prompt, **kwargs):
            seen.append(kwargs["max_tokens"])
            return await super().generate(model, prompt, **kwargs)

    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], BudgetAdapter("A concise decision."))
    result = run_agent_task(
        seeded["engine"],
        registry,
        seeded["agent_active_id"],
        "plan",
        "Plan",
        "v1",
        str(uuid4()),
        max_tokens=requested,
    )
    assert result["status"] == "SUCCEEDED"
    assert seen == [expected]
    limits = result["context_json"]["generation_limits"]
    assert limits["requested_max_tokens"] == requested
    assert limits["effective_max_tokens"] == expected
    assert limits["token_multiplier"] == (2 if role_name == "Director" else 1)


@pytest.mark.parametrize("multiplier", [1, 3])
def test_director_token_multiplier_uses_configuration(seeded, monkeypatch, multiplier):
    from app.agents import services
    from app.config import Settings

    config = Settings(
        _env_file=None,
        owner_token="test-owner-token-for-budget-check",
        director_token_multiplier=multiplier,
    )
    monkeypatch.setattr(services, "_studio_settings", lambda: config)
    clear_stop(seeded["engine"])
    seen = []

    class BudgetAdapter(_StubAdapter):
        async def generate(self, model, prompt, **kwargs):
            seen.append(kwargs["max_tokens"])
            return await super().generate(model, prompt, **kwargs)

    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], BudgetAdapter("A concise decision."))
    result = run_agent_task(
        seeded["engine"],
        registry,
        seeded["agent_active_id"],
        "plan",
        "Plan",
        "v1",
        str(uuid4()),
        max_tokens=6000,
    )
    assert result["status"] == "SUCCEEDED"
    assert seen == [6000 * multiplier]


@pytest.mark.parametrize("invalid", [0, 5])
def test_director_token_multiplier_rejects_out_of_range_configuration(invalid):
    from app.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            owner_token="test-owner-token-for-budget-check",
            director_token_multiplier=invalid,
        )


def test_director_qc_both_attempts_send_doubled_limit_to_ollama(seeded, monkeypatch):
    import json

    from app.agents import services
    from app.agents.reviews import DIRECTOR_QC_TASK, review_film_qc
    from app.config import Settings
    from app.providers.ollama import OllamaProvider

    config = Settings(
        _env_file=None,
        owner_token="test-owner-token-for-budget-check",
        director_token_multiplier=2,
    )
    monkeypatch.setattr(services, "_studio_settings", lambda: config)
    clear_stop(seeded["engine"])
    with Session(seeded["engine"]) as session, session.begin():
        session.get(Role, seeded["role_id"]).allowed_task_types += "," + DIRECTOR_QC_TASK
    # Narration with no object: the one failure that still earns the thinking retry (since
    # 2026-10-11 a reason too long is fitted and validates the first time, and an object refused
    # for its content is asked again with thinking off; see tests/test_structured_answers_fitted).
    first = "Let me read the report first. {not the object} Scene 1 shows the wrong image."
    second = {
        "verdicts": [
            {
                "finding": 1,
                "verdict": "REAL",
                "reason": "The image is wrong.",
                "severity": "serious",
                "cause": "The still prompt named no subject.",
                "lesson": "Name the visible subject first in every still prompt.",
            }
        ],
        "decision": "REPAIR",
        "repairs": [{"scene_index": 1, "redo": "still", "reason": "Remove panels."}],
        "summary": "Refacem scena.",
    }
    answers = iter([first, json.dumps(second)])
    bodies = []

    def reply(_path, body, **_kwargs):
        bodies.append(body)
        return {"response": next(answers), "prompt_eval_count": 10, "eval_count": 100}

    adapter = OllamaProvider("http://127.0.0.1:11434")
    monkeypatch.setattr(adapter, "_post", reply)
    registry = ProviderRegistry()
    registry.register(seeded["provider_id"], adapter)
    result = review_film_qc(
        seeded["engine"],
        registry,
        {
            "film": {"title": "A film", "report_id": "test-report"},
            # A still is redone only for a scene a REAL serious finding names (2026-10-12).
            "findings": [{"id": 1, "text": "Scena 1: wrong image", "scene_index": 1}],
            "scenes": [{"scene_index": 1, "kind": "LIVE", "paid_redos_left": 1}],
        },
    )
    assert result["decision"] == "REPAIR"
    assert len(bodies) == 2
    assert [body["options"]["num_predict"] for body in bodies] == [12000, 12000]
    assert [body["think"] for body in bodies] == [False, True]
    assert "400 characters" in bodies[0]["prompt"]
    assert "800 characters" in bodies[0]["prompt"]


# ---------------------------------------------------------------------------
# What a role prefers of a model: the studio can see, or says it cannot
# ---------------------------------------------------------------------------


def _admit_seeing_model(engine, model_name: str) -> str:
    """A model the provider says can see and can write, admitted into the registry.

    Exactly what `sync_provider_models` records when a vendor declares it: the model is
    available, and the capability rows are the vendor's own declaration. No provider is
    contacted — the Owner's rule: nothing in a test costs money.
    """
    with Session(engine) as session, session.begin():
        provider = session.scalars(select(ProviderRecord)).first()
        model = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name=model_name,
            discovery_method="DECLARED_BY_PROVIDER",
            context_length=None,
            last_verified=utc_now(),
            is_available=True,
            notes="",
        )
        session.add(model)
        session.flush()
        for cap_name in ("text_generation", "vision"):
            capability = session.scalar(select(Capability).where(Capability.name == cap_name))
            session.add(
                ModelCapability(
                    model_id=model.id,
                    capability_id=capability.id,
                    confidence="DECLARED_BY_PROVIDER",
                )
            )
        return model.id


def _agent_on_role(session, role_name: str):
    return session.scalar(
        select(Agent)
        .join(Role, Agent.role_id == Role.id)
        .where(Role.name == role_name, Agent.lifecycle == "ACTIVE")
    )


def test_a_studio_that_has_admitted_a_seeing_model_ends_up_with_a_seeing_employee(engine):
    """The picture gate can actually run in a seeded studio, once a seeing model exists.

    Measured before this: `seed_initial_workforce` hired every employee on a text model, so
    `vision_agent` returned None on every film and the picture and character checks reported
    NOT_APPLICABLE for ever — a film of blank fields passed every automatic check. The
    preference is recorded on the role, not on a model name, and acted on at the next start.
    """
    from app.agents.services import seed_initial_workforce
    from app.agents.vision import vision_agent

    seed_initial_workforce(engine)
    with Session(engine) as session:
        assert vision_agent(session, "VideoEditor", "Director") is None, (
            "the seeded models declare no vision; nobody could have looked"
        )

    model_id = _admit_seeing_model(engine, "qwen3-vl:cloud")
    seed_initial_workforce(engine)  # the studio's next start

    with Session(engine) as session:
        found = vision_agent(session, "VideoEditor", "Director")
        assert found is not None
        agent = session.get(Agent, found[0])
        assert session.get(Role, agent.role_id).name == "VideoEditor"
        assert agent.model_id == model_id
        # And the move did not cost her the job: what the role requires is still satisfied.
        from app.agents.services import _check_required_capabilities

        _check_required_capabilities(session, agent)


def test_the_preference_never_overrules_the_owners_own_assignment(engine):
    """A model the Owner chose himself stays chosen, even when a seeing one is admitted.

    `agent.model_assigned` is the record of his choice — the same guard the starting
    allocation reads. Without it, every start would quietly undo what he saved from Settings.
    """
    from app.agents.services import prefer_capable_models, seed_initial_workforce
    from app.services import append_event

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        editor = _agent_on_role(session, "VideoEditor")
        chosen = editor.model_id
        append_event(
            session,
            "agent.model_assigned",
            "agent",
            editor.id,
            editor.version,
            {"model_id": chosen},
            str(uuid4()),
        )
    _admit_seeing_model(engine, "qwen3-vl:cloud")

    result = prefer_capable_models(engine)

    assert result["moved"] == []
    assert any("Owner" in entry["why"] for entry in result["skipped"])
    with Session(engine) as session:
        assert _agent_on_role(session, "VideoEditor").model_id == chosen


def test_a_studio_with_no_seeing_model_still_hires_and_still_runs(engine):
    """Preferred is not required: nothing here blocks a studio whose Owner admitted no eyes.

    The whole workforce is hired, the Video Editor works on the model the seed gave her, and
    `vision_agent` says plainly that nobody can look — which is what the picture check turns
    into NOT_APPLICABLE with a reason, never into a pass.
    """
    from app.agents.services import run_agent_task, seed_initial_workforce
    from app.agents.vision import vision_agent

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True

    with Session(engine) as session:
        editor = _agent_on_role(session, "VideoEditor")
        assert editor is not None and editor.lifecycle == "ACTIVE"
        assert vision_agent(session) is None
        editor_id, provider_id = editor.id, editor.provider_id

    registry = ProviderRegistry()
    registry.register(provider_id, _StubAdapter("Taie scena a treia."))
    result = run_agent_task(
        engine, registry, editor_id, "edit_scenes", "Cut scene three", "v1", str(uuid4())
    )

    assert result["status"] == "SUCCEEDED", result.get("error_detail")
    roles = {row["name"]: row for row in list_roles(engine)}
    assert "vision" not in roles["VideoEditor"]["required_capabilities"]
