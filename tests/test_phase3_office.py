"""Phase 3 tests: 2D office layout, desk assignments, and agent pause/resume controls."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.models import Agent, Capability, ModelRecord, ProviderRecord, Role
from app.agents.services import pause_agent, resume_agent
from app.db import create_db_engine, migrate
from app.models import DomainEvent
from app.office.services import get_office_layout_with_assignments
from app.services import bootstrap_studio, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def phase3_engine(settings):
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded_studio(phase3_engine):
    engine = phase3_engine
    ids = {}
    with Session(engine) as session, session.begin():
        root_event = session.scalars(select(DomainEvent).limit(1)).first()
        eid = root_event.event_id

        cap = Capability(id=str(uuid4()), name="text_generation", description="text gen")
        session.add(cap)

        role_dir = Role(
            id=str(uuid4()),
            name="Director",
            mission="Direct studio",
            allowed_task_types="plan,direct",
            prohibited_actions="none",
            created_at=utc_now(),
            event_id=eid,
        )
        role_script = Role(
            id=str(uuid4()),
            name="ScriptWriter",
            mission="Write scripts",
            allowed_task_types="write",
            prohibited_actions="none",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add_all([role_dir, role_script])
        session.flush()

        provider = ProviderRecord(
            id=str(uuid4()),
            name="local-ollama",
            provider_type="OLLAMA",
            base_url="http://127.0.0.1:11434",
            status="HEALTHY",
            last_health_check=None,
            adapter_version="1.0.0",
            notes="",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add(provider)
        session.flush()

        model = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name="glm-5.2:cloud",
            discovery_method="DECLARED_BY_PROVIDER",
            context_length=None,
            last_verified=None,
            is_available=True,
            notes="cloud_model=true",
        )
        session.add(model)
        session.flush()

        agent_dir = Agent(
            id=str(uuid4()),
            display_name="Sarah (Director)",
            role_id=role_dir.id,
            provider_id=provider.id,
            model_id=model.id,
            lifecycle="ACTIVE",
            runtime_state="IDLE",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=None,
            event_id=eid,
        )
        agent_script = Agent(
            id=str(uuid4()),
            display_name="Leo (Writer)",
            role_id=role_script.id,
            provider_id=provider.id,
            model_id=model.id,
            lifecycle="ACTIVE",
            runtime_state="WORKING",
            cost_limit_per_task=None,
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=None,
            event_id=eid,
        )
        session.add_all([agent_dir, agent_script])
        session.flush()

        ids["director_id"] = agent_dir.id
        ids["writer_id"] = agent_script.id

    ids["engine"] = engine
    return ids


def test_office_layout_returns_zones_and_assignments(seeded_studio):
    engine = seeded_studio["engine"]
    layout = get_office_layout_with_assignments(engine)

    assert layout["width"] == 1200
    assert layout["height"] == 1000
    assert len(layout["zones"]) >= 8

    zone_types = {z["zone_type"] for z in layout["zones"]}
    assert "DIRECTOR" in zone_types
    assert "RESEARCH" in zone_types
    assert "SCRIPT" in zone_types
    assert "AUDIO" in zone_types
    assert "VIDEO" in zone_types
    assert "PUBLISH" in zone_types
    assert "SERVER" in zone_types
    assert "SHOP" in zone_types

    # The ground floor is a tall, street-facing level; the shop unit has no desks, so the
    # renderer must not place a character in it.
    ground = [z for z in layout["zones"] if z["floor"] == 0]
    assert all(z["height"] == 200 for z in ground)
    shop = next(z for z in ground if z["zone_type"] == "SHOP")
    assert shop["desks"] == []

    # Zones on the same floor must not overlap.
    for floor in {z["floor"] for z in layout["zones"]}:
        spans = sorted(
            (z["x"], z["x"] + z["width"]) for z in layout["zones"] if z["floor"] == floor
        )
        for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
            assert end <= start, f"zones overlap on floor {floor}"

    # Every desk stands on its zone's floor slab.
    for z in layout["zones"]:
        for desk in z["desks"]:
            assert z["y"] < desk["y"] <= z["y"] + z["height"]
            assert z["x"] <= desk["x"] <= z["x"] + z["width"]

    assignments = layout["assignments"]
    assert len(assignments) >= 2
    agent_ids = {a["agent_id"] for a in assignments}
    assert seeded_studio["director_id"] in agent_ids
    assert seeded_studio["writer_id"] in agent_ids


def test_agent_pause_and_resume(seeded_studio):
    engine = seeded_studio["engine"]
    agent_id = seeded_studio["director_id"]

    paused = pause_agent(engine, agent_id)
    assert paused["lifecycle"] == "PAUSED"
    assert paused["version"] == 2

    with Session(engine) as session:
        event = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "agent.paused")
        ).first()
        assert event is not None
        assert event.aggregate_id == agent_id

    resumed = resume_agent(engine, agent_id)
    assert resumed["lifecycle"] == "ACTIVE"
    assert resumed["version"] == 3

    with Session(engine) as session:
        event = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "agent.resumed")
        ).first()
        assert event is not None
        assert event.aggregate_id == agent_id


def test_cannot_pause_terminated_agent(phase3_engine):
    engine = phase3_engine
    agent_id = str(uuid4())

    with Session(engine) as session, session.begin():
        root_event = session.scalars(select(DomainEvent).limit(1)).first()
        eid = root_event.event_id
        cap = Capability(id=str(uuid4()), name="t_gen", description="t")
        role = Role(
            id=str(uuid4()),
            name="R",
            mission="m",
            allowed_task_types="t",
            prohibited_actions="p",
            created_at=utc_now(),
            event_id=eid,
        )
        prov = ProviderRecord(
            id=str(uuid4()),
            name="P",
            provider_type="OLLAMA",
            base_url="http://x",
            status="HEALTHY",
            adapter_version="1",
            notes="",
            created_at=utc_now(),
            event_id=eid,
        )
        session.add_all([cap, role, prov])
        session.flush()

        mod = ModelRecord(
            id=str(uuid4()),
            provider_id=prov.id,
            model_name="m",
            discovery_method="M",
            is_available=True,
            notes="",
        )
        session.add(mod)
        session.flush()

        agent = Agent(
            id=agent_id,
            display_name="Term",
            role_id=role.id,
            provider_id=prov.id,
            model_id=mod.id,
            lifecycle="TERMINATED",
            runtime_state="IDLE",
            max_concurrent_tasks=1,
            version=1,
            hired_at=utc_now(),
            terminated_at=utc_now(),
            event_id=eid,
        )
        session.add(agent)
        session.flush()

    with pytest.raises(ValueError, match="Cannot pause a TERMINATED agent"):
        pause_agent(engine, agent_id)

    with pytest.raises(ValueError, match="Cannot resume a TERMINATED agent"):
        resume_agent(engine, agent_id)
