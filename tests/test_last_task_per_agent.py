"""Each employee's last real task, from the studio's own records (W12).

The headquarters' name tags said «ultima sarcină: —» for six of eight employees, because the
page could only read a task from the events it had replayed. The runs themselves are recorded
(`agent_run`, one row per model call, written the moment the call starts). The snapshot the page
already polls now carries, per employee, the newest of them — started or finished — read with
one grouped query over an index, so the five-second poll stays cheap.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, ModelRecord, ProviderRecord, Role
from app.db import create_db_engine, migrate
from app.models import DomainEvent
from app.services import bootstrap_studio, last_task_per_agent, snapshot, utc_now
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session


@pytest.fixture
def studio(settings):
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    ids: dict = {}
    with Session(engine) as session, session.begin():
        eid = session.scalars(select(DomainEvent).limit(1)).one().event_id
        role = Role(
            id=str(uuid4()),
            name="Researcher",
            mission="Find sources",
            allowed_task_types="gather_sources",
            prohibited_actions="",
            created_at=utc_now(),
            event_id=eid,
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
        session.add_all([role, provider])
        session.flush()
        model = ModelRecord(
            id=str(uuid4()),
            provider_id=provider.id,
            model_name="m:latest",
            discovery_method="MANUALLY_CONFIGURED",
            context_length=None,
            last_verified=None,
            is_available=True,
            notes="",
        )
        session.add(model)
        session.flush()
        for key, name in (
            ("aris", "Dr. Aris (Researcher)"),
            ("elena", "Elena (Fact Checker)"),
            ("vera", "Vera (Publisher)"),
        ):
            agent = Agent(
                id=str(uuid4()),
                display_name=name,
                role_id=role.id,
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
            session.add(agent)
            ids[key] = agent.id
    ids["engine"] = engine
    yield ids
    engine.dispose()


def add_run(engine, agent_id, task_type, status, started_at, finished_at=None):
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=agent_id,
                task_type=task_type,
                objective="x",
                prompt_template_version="v1",
                model_name="m",
                provider_name="p",
                status=status,
                correlation_id=str(uuid4()),
                started_at=started_at,
                finished_at=finished_at,
                context_json={},
            )
        )


def test_the_newest_run_of_each_employee_is_their_last_task(studio):
    engine = studio["engine"]
    add_run(
        engine,
        studio["aris"],
        "gather_sources",
        "SUCCEEDED",
        "2026-09-12T20:40:00+00:00",
        "2026-09-12T20:41:00+00:00",
    )
    add_run(
        engine,
        studio["aris"],
        "answer_mail",
        "SUCCEEDED",
        "2026-09-18T21:03:39+00:00",
        "2026-09-18T21:03:50+00:00",
    )
    add_run(
        engine,
        studio["elena"],
        "verify_claim",
        "FAILED",
        "2026-09-12T20:48:30+00:00",
        "2026-09-12T20:49:00+00:00",
    )
    with Session(engine) as session:
        tasks = last_task_per_agent(session)
    assert set(tasks) == {studio["aris"], studio["elena"]}, (
        "an employee with no run has no last task"
    )
    assert tasks[studio["aris"]] == {
        "task_type": "answer_mail",
        "status": "SUCCEEDED",
        "started_at": "2026-09-18T21:03:39+00:00",
        "finished_at": "2026-09-18T21:03:50+00:00",
    }
    assert tasks[studio["elena"]]["task_type"] == "verify_claim"
    assert tasks[studio["elena"]]["status"] == "FAILED"


def test_a_task_started_and_not_finished_is_the_last_one(studio):
    engine = studio["engine"]
    add_run(
        engine,
        studio["vera"],
        "prepare_publication",
        "SUCCEEDED",
        "2026-09-12T20:58:29+00:00",
        "2026-09-12T20:59:00+00:00",
    )
    add_run(engine, studio["vera"], "publish", "RUNNING", "2026-09-24T09:00:00+00:00")
    with Session(engine) as session:
        last = last_task_per_agent(session)[studio["vera"]]
    assert last["task_type"] == "publish"
    assert last["status"] == "RUNNING"
    assert last["finished_at"] is None


def test_the_snapshot_carries_the_last_tasks(studio):
    engine = studio["engine"]
    add_run(
        engine,
        studio["aris"],
        "answer_mail",
        "SUCCEEDED",
        "2026-09-18T21:03:39+00:00",
        "2026-09-18T21:03:50+00:00",
    )
    data = snapshot(engine)
    assert data["last_tasks"] == {
        studio["aris"]: {
            "task_type": "answer_mail",
            "status": "SUCCEEDED",
            "started_at": "2026-09-18T21:03:39+00:00",
            "finished_at": "2026-09-18T21:03:50+00:00",
        }
    }


def test_the_snapshot_route_carries_an_empty_record_as_empty(client, headers):
    data = client.get("/api/v1/snapshot", headers=headers).json()
    assert data["last_tasks"] == {}


def test_it_is_one_indexed_query(studio):
    engine = studio["engine"]
    for day in range(1, 9):
        add_run(
            engine,
            studio["aris"],
            "gather_sources",
            "SUCCEEDED",
            f"2026-09-0{day}T10:00:00+00:00",
            f"2026-09-0{day}T10:01:00+00:00",
        )
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        with Session(engine) as session:
            tasks = last_task_per_agent(session)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert tasks[studio["aris"]]["started_at"] == "2026-09-08T10:00:00+00:00"
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, selects
    with engine.connect() as connection:
        plan = " ".join(
            str(row[-1])
            for row in connection.execute(text("EXPLAIN QUERY PLAN " + selects[0]), {}).fetchall()
        )
    assert "ix_agent_run_agent_started" in plan, plan
