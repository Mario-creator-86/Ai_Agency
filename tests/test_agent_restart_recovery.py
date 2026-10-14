"""A dead worker's text call must not occupy an editor for another 45 minutes."""

# ruff: noqa: F811 -- pytest injects the imported film fixture by name
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.memory import agent_for_role
from app.agents.models import Agent, AgentRun
from app.agents.recovery import recover_interrupted_sheet_runs
from app.media import blocker_repair as repair
from app.media.prompt_agent import PROMPT_ROLE
from app.workflows.models import TaskQueueItem
from sqlalchemy.orm import Session
from test_sheet_blocker_repair import film, sheet, task  # noqa: F401


def interrupted(engine, film, *, task_type=repair.REPAIR_TASK, new=False):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    cutoff = datetime.now(UTC)
    stamp = (cutoff + timedelta(seconds=1) if new else cutoff - timedelta(seconds=30)).isoformat()
    with Session(engine) as session, session.begin():
        editor = agent_for_role(session, PROMPT_ROLE)
        editor.runtime_state = "THINKING"
        row = session.get(TaskQueueItem, queued.id)
        row.task_type = task_type
        row.status, row.attempts = "CLAIMED", 1
        row.max_attempts = 3
        row.lease_token = "dead-worker"
        row.lease_expires_at = (cutoff + timedelta(hours=1)).isoformat()
        row.updated_at = stamp
        run_id = str(uuid4())
        session.add(
            AgentRun(
                id=run_id,
                agent_id=editor.id,
                task_type="shot_prompts",
                objective="offline",
                prompt_template_version="shot-prompts-v3",
                model_name="test",
                provider_name="test",
                status="RUNNING",
                correlation_id=queued.id,
                started_at=stamp,
                context_json={},
            )
        )
        return cutoff, run_id, queued.id, editor.id


def test_previous_worker_call_releases_the_editor_and_retries_the_durable_work(engine, film):
    cutoff, run_id, task_id, editor_id = interrupted(engine, film)
    result = recover_interrupted_sheet_runs(engine, started_at=cutoff)
    assert result["abandoned_run_ids"] == [run_id]
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        assert run.status == "ABANDONED" and run.finished_at and run.event_id
        assert run.output_text is None and run.cost_vr is None
        assert session.get(Agent, editor_id).runtime_state == "IDLE"
        row = session.get(TaskQueueItem, task_id)
        assert row.status == "RETRYING" and row.attempts == 1
        assert row.lease_token is None and row.lease_expires_at is None
    assert recover_interrupted_sheet_runs(engine, started_at=cutoff)["abandoned_run_ids"] == []


@pytest.mark.parametrize("task_type,new", [("FILM_CONTINUE", False), (repair.REPAIR_TASK, True)])
def test_current_calls_and_tasks_that_can_purchase_are_never_reclaimed(
    engine, film, task_type, new
):
    cutoff, run_id, task_id, editor_id = interrupted(engine, film, task_type=task_type, new=new)
    assert recover_interrupted_sheet_runs(engine, started_at=cutoff)["abandoned_run_ids"] == []
    with Session(engine) as session:
        assert session.get(AgentRun, run_id).status == "RUNNING"
        assert session.get(TaskQueueItem, task_id).status == "CLAIMED"
        assert session.get(Agent, editor_id).runtime_state == "THINKING"


def test_another_current_call_keeps_the_agent_busy(engine, film):
    cutoff, _, _, editor_id = interrupted(engine, film)
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=editor_id,
                task_type="mail",
                objective="current",
                prompt_template_version="v1",
                model_name="test",
                provider_name="test",
                status="RUNNING",
                correlation_id=str(uuid4()),
                started_at=(cutoff + timedelta(seconds=1)).isoformat(),
                context_json={},
            )
        )
    recover_interrupted_sheet_runs(engine, started_at=cutoff)
    with Session(engine) as session:
        assert session.get(Agent, editor_id).runtime_state == "THINKING"


def test_interrupted_retry_does_not_reset_exhausted_attempts(engine, film):
    cutoff, _, task_id, _ = interrupted(engine, film)
    with Session(engine) as session, session.begin():
        row = session.get(TaskQueueItem, task_id)
        row.attempts = row.max_attempts
    recover_interrupted_sheet_runs(engine, started_at=cutoff)
    with Session(engine) as session:
        row = session.get(TaskQueueItem, task_id)
        assert row.status == "DEAD_LETTER" and row.attempts == row.max_attempts


def test_a_naive_process_boundary_is_refused(engine, film):
    with pytest.raises(ValueError):
        recover_interrupted_sheet_runs(engine, started_at=datetime.now())
