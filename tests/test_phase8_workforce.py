"""Phase 8 — the studio proposing changes to its own staff.

This is the most consequential thing the studio can recommend, so the bar is different from a
content decision. A recommendation to stop someone's work has to be reconstructible: which runs
were counted, over what window, what the failure rate was. And it has to stay a recommendation —
hiring and firing are the Owner's, and no code path here changes employment without a decision.

The tests are mostly about what is *not* proposed, and what a proposal cannot do on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun
from app.agents.services import seed_initial_workforce
from app.services import utc_now
from app.workflows.models import TaskQueueItem
from app.workforce.models import EmploymentRecord, WorkforceProposal
from app.workforce.services import (
    MIN_RUNS_FOR_JUDGEMENT,
    OBSERVATION_DAYS,
    AutonomousChangeBlocked,
    WorkforceError,
    decide_proposal,
    employment_history,
    list_proposals,
    measure_workforce,
    open_employment,
    propose_workforce_changes,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session:
        return [
            {"id": a.id, "name": a.display_name, "role_id": a.role_id}
            for a in session.scalars(select(Agent))
        ]


def add_runs(engine, agent_id: str, *, succeeded: int, failed: int, days_ago: int = 1) -> None:
    when = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    with Session(engine) as session, session.begin():
        for index in range(succeeded + failed):
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=agent_id,
                    task_type="test",
                    objective="fixture run",
                    prompt_template_version="v1",
                    model_name="m",
                    provider_name="p",
                    status="SUCCEEDED" if index < succeeded else "FAILED",
                    correlation_id=str(uuid4()),
                    started_at=when,
                    finished_at=when,
                )
            )


def queue_tasks(engine, count: int, status: str = "QUEUED") -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        for _ in range(count):
            session.add(
                TaskQueueItem(
                    id=str(uuid4()),
                    task_type="test",
                    payload={},
                    priority=0,
                    status=status,
                    attempts=0,
                    max_attempts=3,
                    backoff_seconds=5,
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def test_measurement_counts_rows_and_judges_nothing(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=7, failed=3)

    measured = measure_workforce(engine)

    subject = next(a for a in measured["agents"] if a["agent_id"] == staffed[0]["id"])
    assert subject["runs"] == 10
    assert subject["failed"] == 3
    assert subject["failure_rate"] == 0.3
    assert measured["window_days"] == OBSERVATION_DAYS


def test_an_agent_that_never_ran_has_an_unknown_rate_not_a_perfect_one(engine, staffed):
    """Zero would read as a flawless record. Nothing ran, so nothing is known."""
    measured = measure_workforce(engine)

    subject = next(a for a in measured["agents"] if a["agent_id"] == staffed[0]["id"])
    assert subject["runs"] == 0
    assert subject["failure_rate"] is None


def test_work_older_than_the_window_is_not_counted(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=0, failed=20, days_ago=OBSERVATION_DAYS + 5)

    measured = measure_workforce(engine)

    subject = next(a for a in measured["agents"] if a["agent_id"] == staffed[0]["id"])
    assert subject["runs"] == 0, "old failures say little about how an agent is doing now"


# ---------------------------------------------------------------------------
# What is not proposed
# ---------------------------------------------------------------------------


def test_a_healthy_studio_gets_no_proposals(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=20, failed=1)

    assert propose_workforce_changes(engine) == []


def test_a_small_sample_never_becomes_a_recommendation(engine, staffed):
    """Four total failures out of four runs is a bad day, not a performance record."""
    add_runs(engine, staffed[0]["id"], succeeded=0, failed=MIN_RUNS_FOR_JUDGEMENT - 1)

    assert propose_workforce_changes(engine) == []
    with Session(engine) as session:
        assert session.scalars(select(WorkforceProposal)).all() == []


def test_an_idle_agent_is_recorded_but_not_accused(engine, staffed):
    """An agent nobody asked for anything is a fact about the studio, not about the agent."""
    measured = measure_workforce(engine)

    assert staffed[0]["id"] in measured["idle_agents"]
    assert propose_workforce_changes(engine) == []


def test_the_same_concern_is_not_proposed_twice_while_undecided(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)

    first = propose_workforce_changes(engine)
    second = propose_workforce_changes(engine)

    assert len(first) == 1
    assert second == [], "an undecided proposal about the same agent already stands"


# ---------------------------------------------------------------------------
# What is proposed, and what it carries
# ---------------------------------------------------------------------------


def test_a_failing_agent_is_proposed_for_suspension_with_its_numbers(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=2, failed=8)

    proposals = propose_workforce_changes(engine)

    assert len(proposals) == 1
    proposal = proposals[0]
    # Suspension, not termination: the cause is often the model or provider, and suspension
    # is reversible.
    assert proposal["proposal_type"] == "SUSPEND_AGENT"
    assert proposal["agent_id"] == staffed[0]["id"]
    assert proposal["sample_size"] == 10
    assert proposal["evidence"]["failed"] == 8
    assert proposal["evidence"]["failure_rate"] == 0.8
    assert proposal["evidence"]["window_days"] == OBSERVATION_DAYS
    assert "8 din 10" in proposal["summary"]


def test_a_backlog_the_staff_cannot_clear_proposes_a_hire(engine, staffed):
    queue_tasks(engine, 80)

    proposals = propose_workforce_changes(engine)

    hire = next(p for p in proposals if p["proposal_type"] == "HIRE_ROLE")
    assert hire["evidence"]["queue_backlog"] == 80
    assert hire["evidence"]["active_agents"] == len(staffed)
    assert hire["agent_id"] is None, "a hire is about a role, not about an existing agent"


# ---------------------------------------------------------------------------
# Only the Owner decides
# ---------------------------------------------------------------------------


def test_an_autonomous_approval_is_refused(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]

    with pytest.raises(AutonomousChangeBlocked):
        decide_proposal(engine, proposal["id"], True, "", owner_decision=False)

    with Session(engine) as session:
        assert session.get(WorkforceProposal, proposal["id"]).status == "PROPOSED"
        assert session.get(Agent, staffed[0]["id"]).lifecycle == "ACTIVE"


def test_an_owner_approval_suspends_the_agent(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]

    decided = decide_proposal(engine, proposal["id"], True, "Verific modelul.")

    assert decided["status"] == "APPLIED"
    assert decided["applied_at"] is not None
    with Session(engine) as session:
        assert session.get(Agent, staffed[0]["id"]).lifecycle == "SUSPENDED"


def test_a_rejection_records_why_and_changes_nothing(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]

    decided = decide_proposal(engine, proposal["id"], False, "Furnizorul era căzut în acea zi.")

    assert decided["status"] == "REJECTED"
    assert "Furnizorul era căzut" in decided["decision_notes"]
    with Session(engine) as session:
        assert session.get(Agent, staffed[0]["id"]).lifecycle == "ACTIVE"


def test_a_decided_proposal_cannot_be_decided_again(engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]
    decide_proposal(engine, proposal["id"], True, "")

    with pytest.raises(WorkforceError):
        decide_proposal(engine, proposal["id"], False, "M-am răzgândit")


def test_a_hire_proposal_is_approved_but_left_for_the_owner_to_carry_out(engine, staffed):
    """Which role, on which model, is a decision the studio cannot make for the Owner."""
    queue_tasks(engine, 80)
    hire = next(p for p in propose_workforce_changes(engine) if p["proposal_type"] == "HIRE_ROLE")

    with pytest.raises(WorkforceError) as excinfo:
        decide_proposal(engine, hire["id"], True, "De acord.")

    assert "Settings" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Employment is a record, not a column
# ---------------------------------------------------------------------------


def test_termination_closes_the_employment_period(engine, staffed):
    agent_id, role_id = staffed[0]["id"], staffed[0]["role_id"]
    open_employment(engine, agent_id, role_id)
    add_runs(engine, agent_id, succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]

    # Turn the suspension into a termination to exercise the harder path.
    with Session(engine) as session, session.begin():
        session.get(WorkforceProposal, proposal["id"]).proposal_type = "TERMINATE_AGENT"

    decide_proposal(engine, proposal["id"], True, "Rol desființat.")

    history = employment_history(engine, agent_id)
    assert len(history) == 1
    assert history[0]["ended_at"] is not None
    assert history[0]["proposal_id"] == proposal["id"]
    with Session(engine) as session:
        assert session.get(Agent, agent_id).lifecycle == "TERMINATED"


def test_a_rehire_opens_a_new_period_rather_than_reviving_the_closed_one(engine, staffed):
    """The spec forbids TERMINATED becoming ACTIVE by editing state; employment history is what
    makes a return an event instead of an edit."""
    agent_id, role_id = staffed[0]["id"], staffed[0]["role_id"]
    open_employment(engine, agent_id, role_id)
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        agent.lifecycle = "TERMINATED"
        period = session.scalars(
            select(EmploymentRecord).where(EmploymentRecord.agent_id == agent_id)
        ).one()
        period.ended_at = utc_now()

    open_employment(engine, agent_id, role_id)

    history = employment_history(engine, agent_id)
    assert len(history) == 2, "the closed period stays closed; the return is a new one"
    assert history[0]["ended_at"] is None
    assert history[1]["ended_at"] is not None


def test_an_agent_cannot_hold_two_open_employment_periods(engine, staffed):
    agent_id, role_id = staffed[0]["id"], staffed[0]["role_id"]
    open_employment(engine, agent_id, role_id)

    with pytest.raises(WorkforceError):
        open_employment(engine, agent_id, role_id)


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_the_api_says_plainly_when_nothing_is_warranted(client, headers, staffed):
    response = client.post("/api/v1/workforce/proposals/generate", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["proposals"] == []
    assert "nicio schimbare" in body["message"]


def test_a_rejection_without_a_reason_is_refused(client, headers, engine, staffed):
    add_runs(engine, staffed[0]["id"], succeeded=1, failed=9)
    proposal = propose_workforce_changes(engine)[0]

    response = client.post(
        f"/api/v1/workforce/proposals/{proposal['id']}/decide",
        json={"command_id": str(uuid4()), "approve": False, "notes": "   "},
        headers=headers,
    )

    assert response.status_code == 422
    assert list_proposals(engine, status="PROPOSED")
