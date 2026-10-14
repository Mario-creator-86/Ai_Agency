"""Recover text-only sheet work interrupted by a previous queue worker process."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agents.models import Agent, AgentRun
from app.db import lock_for_write
from app.workflows.models import TaskQueueItem
from app.workflows.services import append_event_with_outbox

RESTART_REASON = "Rularea a fost întreruptă de repornirea studioului; lucrarea nu este finalizată."


def _before(stamp: str, boundary: datetime) -> bool:
    try:
        value = datetime.fromisoformat(stamp)
        return value.tzinfo is not None and value < boundary
    except ValueError:
        return False


def recover_interrupted_sheet_runs(engine: Engine, *, started_at: datetime) -> dict[str, Any]:
    """Called by the exclusive worker at startup, or after verifying its predecessor died.

    A pre-start call correlated with a pre-start CLAIMED sheet task belongs to the dead
    worker. No uncorrelated calls, purchasing tasks, or calls from this process qualify.
    This is interruption recovery, never a successful repair or a reset of attempt caps.
    """
    if started_at.tzinfo is None:
        raise ValueError("The process start boundary must include a timezone")
    now = datetime.now(UTC)
    abandoned: list[str] = []
    recovered_tasks: list[str] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        affected_agents: set[str] = set()
        rows = list(
            session.execute(
                select(AgentRun, TaskQueueItem)
                .join(TaskQueueItem, TaskQueueItem.id == AgentRun.correlation_id)
                .where(
                    AgentRun.status == "RUNNING",
                    TaskQueueItem.task_type == "FILM_SHEET_REPAIR",
                    TaskQueueItem.status == "CLAIMED",
                    TaskQueueItem.lease_token.is_not(None),
                )
            )
        )
        for run, task in rows:
            if not _before(run.started_at, started_at) or not _before(task.updated_at, started_at):
                continue
            run.status = "ABANDONED"
            run.finished_at = now.isoformat()
            run.error_detail = RESTART_REASON
            event, _ = append_event_with_outbox(
                session,
                "agent.run_completed",
                "agent_run",
                run.id,
                1,
                {
                    "agent_id": run.agent_id,
                    "status": "ABANDONED",
                    "task_type": run.task_type,
                    "reason": "previous_worker_interrupted",
                    "error_detail": RESTART_REASON,
                },
                run.correlation_id,
            )
            run.event_id = event.event_id
            abandoned.append(run.id)
            affected_agents.add(run.agent_id)
            if task.id in recovered_tasks:
                continue
            # Same retry accounting as fail_task, atomically with the interrupted run.
            task.lease_token = None
            task.lease_expires_at = None
            task.error_detail = RESTART_REASON
            task.updated_at = now.isoformat()
            if task.attempts < task.max_attempts:
                task.status = "RETRYING"
                delay = task.backoff_seconds * 2 ** max(0, task.attempts - 1)
                task.next_attempt_at = (now + timedelta(seconds=delay)).isoformat()
            else:
                task.status = "DEAD_LETTER"
            recovered_tasks.append(task.id)
            append_event_with_outbox(
                session,
                "workflow.task_interrupted",
                "task_queue_item",
                task.id,
                1,
                {
                    "task_id": task.id,
                    "status": task.status,
                    "attempts": task.attempts,
                    "reason": "previous_worker_interrupted",
                },
                task.id,
            )
        session.flush()
        for agent_id in affected_agents:
            agent = session.get(Agent, agent_id)
            has_live_run = session.scalar(
                select(AgentRun.id)
                .where(
                    AgentRun.agent_id == agent_id,
                    AgentRun.status == "RUNNING",
                )
                .limit(1)
            )
            if agent and agent.runtime_state == "THINKING" and not has_live_run:
                agent.runtime_state = "IDLE"
                agent.version += 1
                append_event_with_outbox(
                    session,
                    "agent.state_changed",
                    "agent",
                    agent.id,
                    agent.version,
                    {"runtime_state": "IDLE", "reason": "previous_worker_interrupted"},
                    abandoned[0],
                )
    return {"abandoned_run_ids": abandoned, "recovered_task_ids": recovered_tasks}
