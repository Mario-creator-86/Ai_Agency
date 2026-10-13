"""Every current employee has a stable personal seat and their actual backend state."""

from datetime import datetime, timedelta
from uuid import uuid4

from app.agents.models import Agent, Role
from app.agents.services import (
    mark_idle,
    mark_working,
    pause_agent,
    resume_agent,
    seed_initial_workforce,
)
from app.db import create_db_engine
from app.office.services import PIXEL_OFFICE, get_office_layout_with_assignments
from sqlalchemy import select
from sqlalchemy.orm import Session


def assignments(engine):
    return {a["agent_id"]: a for a in get_office_layout_with_assignments(engine)["assignments"]}


def ownership(rows):
    return {aid: (a["pixel_desk_id"], a["pixel_slot"]) for aid, a in rows.items()}


def later_hires(engine, count):
    ids = []
    with Session(engine) as session, session.begin():
        template = session.scalars(select(Agent).order_by(Agent.hired_at)).first()
        last = max(a.hired_at for a in session.scalars(select(Agent)))
        moment = datetime.fromisoformat(last)
        for i in range(count):
            aid = str(uuid4())
            ids.append(aid)
            session.add(
                Agent(
                    id=aid,
                    display_name=f"Extra employee {i}",
                    role_id=template.role_id,
                    provider_id=template.provider_id,
                    model_id=template.model_id,
                    lifecycle="ACTIVE",
                    runtime_state="IDLE",
                    max_concurrent_tasks=1,
                    version=1,
                    hired_at=(moment + timedelta(seconds=i + 1)).isoformat(),
                    event_id=template.event_id,
                )
            )
    return ids


def test_known_roles_have_their_own_illustrated_station(engine):
    seed_initial_workforce(engine)
    layout = get_office_layout_with_assignments(engine)
    assert layout["pixel_office"] == PIXEL_OFFICE
    expected = {station["role"]: i for i, station in enumerate(PIXEL_OFFICE["stations"])}
    assert len(layout["assignments"]) == 8
    for agent in layout["assignments"]:
        assert agent["pixel_slot"] == expected[agent["role_name"]]
        assert agent["pixel_desk_id"] == f"pixel_desk_{agent['agent_id']}"
        assert agent["version"] >= 1


def test_real_work_pause_and_resume_keep_personal_ownership(engine):
    seed_initial_workforce(engine)
    before = assignments(engine)
    director = next(a for a in before.values() if a["role_name"] == "Director")
    aid = mark_working(engine, "Director", "personal-desk-test", "Preparing the real plan")
    assert aid == director["agent_id"]
    working = assignments(engine)
    assert working[aid]["runtime_state"] == "WORKING"
    assert working[aid]["version"] > director["version"]
    pause_agent(engine, aid)
    assert assignments(engine)[aid]["lifecycle"] == "PAUSED"
    resume_agent(engine, aid)
    mark_idle(engine, aid, "personal-desk-test")
    after = assignments(engine)
    assert after[aid]["runtime_state"] == "IDLE"
    assert ownership(before) == ownership(working) == ownership(after)


def test_later_hires_and_departures_do_not_move_any_other_employee(engine):
    seed_initial_workforce(engine)
    before = assignments(engine)
    new_ids = later_hires(engine, 2)
    after_hire = assignments(engine)
    assert all(ownership(after_hire)[aid] == place for aid, place in ownership(before).items())
    assert [after_hire[aid]["pixel_slot"] for aid in new_ids] == [8, 9]
    with Session(engine) as session, session.begin():
        session.get(Agent, next(iter(before))).lifecycle = "TERMINATED"
        session.get(Agent, new_ids[0]).lifecycle = "TERMINATED"
    newest = later_hires(engine, 1)[0]
    after_departure = assignments(engine)
    assert after_departure[newest]["pixel_slot"] == 10
    assert new_ids[0] not in after_departure
    assert all(
        ownership(after_departure)[aid] == ownership(after_hire)[aid]
        for aid in after_departure
        if aid != newest
    )


def test_large_workforce_has_no_omitted_or_shared_desks(engine, settings):
    seed_initial_workforce(engine)
    later_hires(engine, 25)
    layout = get_office_layout_with_assignments(engine)
    rows = layout["assignments"]
    assert len(rows) == 33
    assert layout["unassigned_count"] == 0
    assert len({a["pixel_slot"] for a in rows}) == 33
    assert len({a["pixel_desk_id"] for a in rows}) == 33
    with Session(engine) as session:
        expected = {a.id for a in session.scalars(select(Agent))}
    assert {a["agent_id"] for a in rows} == expected
    reopened = create_db_engine(settings.database_url)
    try:
        assert ownership(assignments(reopened)) == ownership({a["agent_id"]: a for a in rows})
    finally:
        reopened.dispose()


def test_office_api_is_authenticated_and_returns_actual_thinking_state(client, engine, headers):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        agent = session.scalars(select(Agent)).first()
        agent.runtime_state = "THINKING"
        agent.version += 1
        aid, version = agent.id, agent.version
        role_name = session.get(Role, agent.role_id).name
    assert client.get("/api/v1/office/layout").status_code == 401
    response = client.get("/api/v1/office/layout", headers=headers)
    assert response.status_code == 200
    row = next(a for a in response.json()["assignments"] if a["agent_id"] == aid)
    assert row["runtime_state"] == "THINKING"
    assert row["version"] == version
    assert row["role_name"] == role_name
