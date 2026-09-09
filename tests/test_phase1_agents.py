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
    assert "autonomy stop" in result["error_detail"].lower()


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
