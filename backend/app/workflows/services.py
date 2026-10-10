"""Phase 2 workflow, task queue, scheduler, and transactional outbox services."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.models import DomainEvent, OwnerPolicy
from app.services import append_event, utc_now
from app.workflows.models import (
    OutboxRecord,
    ScheduledJob,
    TaskQueueItem,
    Workflow,
    WorkflowStep,
)
from app.workflows.schemas import (
    CreateScheduledJobCommand,
    CreateWorkflowCommand,
    ScheduledJobView,
    TaskQueueItemView,
    WorkflowDetailView,
    WorkflowStepView,
    WorkflowView,
)

logger = logging.getLogger("studio.workflows")

PIPELINE_STAGES = [
    "DISCOVERY",
    "IDEA_SELECTION",
    "RESEARCH",
    "FACT_CHECK",
    "SCRIPTING",
    "HOOK_OPTIMIZATION",
    "STORYBOARD",
    "ASSET_GENERATION",
    "VIDEO_GENERATION",
    "VOICE_GENERATION",
    "EDITING",
    "QUALITY_CONTROL",
    "READY_TO_PUBLISH",
    "PUBLISHING",
    "PUBLISHED",
    "ANALYTICS",
    "LEARNING",
]

VALID_WORKFLOW_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"PREFLIGHT", "CANCELLED"},
    "PREFLIGHT": {"ADMITTED", "BLOCKED", "FAILED", "CANCELLED"},
    "ADMITTED": {"RUNNING", "PAUSED", "CANCELLED"},
    "RUNNING": {"PAUSED", "COMPLETED", "FAILED", "BLOCKED", "CANCEL_REQUESTED"},
    "PAUSED": {"RUNNING", "CANCELLED"},
    "BLOCKED": {"RUNNING", "FAILED", "CANCELLED"},
    "CANCEL_REQUESTED": {"CANCELLED", "FAILED"},
    "CANCELLED": set(),
    "COMPLETED": set(),
    "FAILED": set(),
    "NEEDS_REPAIR": {"RUNNING", "FAILED"},
}


class InvalidStateTransitionError(ValueError):
    """Raised when attempting an illegal workflow or task status change."""


class LeaseLost(ValueError):
    """The task is no longer held under this lease token: it lapsed and was taken over, or
    the row was finished elsewhere. The caller's outcome is not written over the new holder's.
    A ValueError, as the old refusal was, so callers that caught that still catch this."""


#: What a task whose lease lapsed with no attempts left becomes: DEAD_LETTER, with this word
#: opening its ``error_detail`` and an event of `TASK_INTERRUPTED_EVENT`. The process that held
#: it died (a crash, a kill, a reboot); running it again would repeat whatever it had done —
#: for a day, its purchases — so nothing re-runs it on its own (REL-03, 2026-10-02).
INTERRUPTED = "INTERRUPTED"
TASK_INTERRUPTED_EVENT = "workflow.task_interrupted"
#: A worker found at completion that its lease was no longer its own.
TASK_LEASE_LOST_EVENT = "workflow.task_lease_lost"
#: A scheduled job fired: the job and the task it queued. Scheduled fires used to create a
#: `Workflow` row each (status CREATED, stage DISCOVERY) that nothing ever moved — 665 such
#: rows in the live copy — so its pause and cancel controlled nothing (AR-14, 2026-10-02).
JOB_FIRED_EVENT = "workflow.job_fired"

#: Queue states in which a task is held under a lease.
LEASED_STATES = ("CLAIMED", "RUNNING")


# ---------------------------------------------------------------------------
# Transactional Outbox Helper
# ---------------------------------------------------------------------------


def append_event_with_outbox(
    session: Session,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    schema_version: int,
    payload: dict,
    correlation_id: str,
    destination: str = "WEBSOCKET",
) -> tuple[DomainEvent, OutboxRecord]:
    """Atomically append a DomainEvent and an OutboxRecord in the same session."""
    event = append_event(
        session,
        event_type,
        aggregate_type,
        aggregate_id,
        schema_version,
        payload,
        correlation_id,
    )
    outbox = OutboxRecord(
        id=str(uuid4()),
        event_id=event.event_id,
        destination=destination,
        status="PENDING",
        payload={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "correlation_id": event.correlation_id,
            "schema_version": event.schema_version,
            "payload": event.payload,
        },
        created_at=utc_now(),
        published_at=None,
    )
    session.add(outbox)
    session.flush()
    return event, outbox


# ---------------------------------------------------------------------------
# Workflows & Steps
# ---------------------------------------------------------------------------


def create_workflow(
    engine: Engine,
    command: CreateWorkflowCommand,
) -> dict:
    workflow_id = str(uuid4())
    now = utc_now()
    correlation_id = str(command.command_id)

    with Session(engine) as session, session.begin():
        event, _ = append_event_with_outbox(
            session,
            "workflow.created",
            "workflow",
            workflow_id,
            1,
            {
                "workflow_type": command.workflow_type,
                "title": command.title,
                "initial_stage": PIPELINE_STAGES[0],
            },
            correlation_id,
        )

        wf = Workflow(
            id=workflow_id,
            workflow_type=command.workflow_type,
            title=command.title,
            status="CREATED",
            current_stage=PIPELINE_STAGES[0],
            config=command.config,
            created_at=now,
            updated_at=now,
            event_id=event.event_id,
        )
        session.add(wf)

        # Initialize the first step
        step_id = str(uuid4())
        step = WorkflowStep(
            id=step_id,
            workflow_id=workflow_id,
            stage=PIPELINE_STAGES[0],
            status="PENDING",
            assigned_agent_id=None,
            inputs=command.config,
            outputs=None,
            error_detail=None,
            attempt=1,
            started_at=None,
            completed_at=None,
            event_id=event.event_id,
        )
        session.add(step)
        session.flush()

        view = WorkflowDetailView.model_validate(wf)
        view.steps = [WorkflowStepView.model_validate(step)]
        return view.model_dump()


def transition_workflow(
    engine: Engine,
    workflow_id: str,
    target_status: str,
    correlation_id: str | None = None,
) -> dict:
    """Transition workflow status enforcing legal state machine invariants."""
    cid = correlation_id or str(uuid4())
    now = utc_now()

    with Session(engine) as session, session.begin():
        wf = session.get(Workflow, workflow_id)
        if wf is None:
            raise ValueError(f"Workflow {workflow_id} not found")

        valid_targets = VALID_WORKFLOW_TRANSITIONS.get(wf.status, set())
        if target_status not in valid_targets:
            raise InvalidStateTransitionError(
                f"Cannot transition workflow from {wf.status} to {target_status}. "
                f"Allowed: {sorted(valid_targets)}"
            )

        wf.status = target_status
        wf.updated_at = now

        event, _ = append_event_with_outbox(
            session,
            f"workflow.{target_status.lower()}",
            "workflow",
            workflow_id,
            1,
            {"target_status": target_status, "current_stage": wf.current_stage},
            cid,
        )
        wf.event_id = event.event_id
        session.flush()
        return WorkflowView.model_validate(wf).model_dump()


def list_workflows(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        wfs = session.scalars(select(Workflow).order_by(Workflow.created_at.desc())).all()
        return [WorkflowView.model_validate(w).model_dump() for w in wfs]


def get_workflow_detail(engine: Engine, workflow_id: str) -> dict | None:
    with Session(engine) as session:
        wf = session.get(Workflow, workflow_id)
        if wf is None:
            return None
        steps = session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.started_at)
        ).all()
        view = WorkflowDetailView.model_validate(wf)
        view.steps = [WorkflowStepView.model_validate(s) for s in steps]
        return view.model_dump()


# ---------------------------------------------------------------------------
# Task Queue & Leases
# ---------------------------------------------------------------------------


def enqueue_task(
    engine: Engine,
    task_type: str,
    payload: dict,
    workflow_id: str | None = None,
    step_id: str | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    backoff_seconds: int = 5,
    idempotency_key: str | None = None,
    not_before: str | None = None,
) -> dict:
    """Put a task in the queue. ``not_before`` (ISO, UTC) holds it until then.

    The queue already orders and gates claims on ``next_attempt_at``; a task that should
    wait — the day's second attempt half an hour after a blocked first — is simply queued
    with that time, and no claim hands it out early.
    """
    now = utc_now()
    with Session(engine) as session, session.begin():
        if idempotency_key:
        # The lock first: the key is looked up and then the task inserted. 2026-10-09 16:47:25
        # UTC a FILM_CONTINUE deferral (the continuation of a paid yes) died here on «database
        # is locked» when a commit landed between the two (`app.db.lock_for_write`), and the
        # film was left to a dead letter. Writer from the first statement, it waits its turn.
        lock_for_write(session)
            existing = session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.idempotency_key == idempotency_key)
            ).first()
            if existing:
                return TaskQueueItemView.model_validate(existing).model_dump()

        task = TaskQueueItem(
            id=str(uuid4()),
            workflow_id=workflow_id,
            step_id=step_id,
            task_type=task_type,
            payload=payload,
            priority=priority,
            status="QUEUED",
            attempts=0,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
            next_attempt_at=not_before or now,
            lease_token=None,
            lease_expires_at=None,
            idempotency_key=idempotency_key,
            error_detail=None,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        session.flush()
        return TaskQueueItemView.model_validate(task).model_dump()


def claim_task(
    engine: Engine,
    worker_id: str,
    lease_duration_seconds: int = 30,
) -> dict | None:
    """Atomically claim the next eligible task in queue with a lease.

    Refuses to claim tasks if Owner autonomy stop is enabled. A task whose lease lapsed is
    claimed again only while it has attempts left: one that had its last attempt was being run
    by a process that died, and is `sweep_interrupted_tasks`'s (REL-03). Measured before
    2026-10-02: a day queued with max_attempts=1, claimed, its lease lapsed, was claimed a
    second time — the whole day, purchases included, ran again an hour after a crash.

    Every claim carries its own lease token, ``<worker_id>:<uuid>`` (AR-17): every process
    used to call itself 'worker_main', so a second process could complete or fail the first
    one's claim. The worker id stays readable at the front for the logs.
    """
    now_dt = datetime.now(UTC)
    now_str = now_dt.isoformat()
    lease_expiry = (now_dt + timedelta(seconds=lease_duration_seconds)).isoformat()
    eligible_when = or_(
        (TaskQueueItem.status.in_(["QUEUED", "RETRYING"]))
        & (TaskQueueItem.next_attempt_at <= now_str),
        (TaskQueueItem.status.in_(LEASED_STATES))
        & (TaskQueueItem.lease_expires_at < now_str)
        & (TaskQueueItem.attempts < TaskQueueItem.max_attempts),
    )
    order = (TaskQueueItem.priority.desc(), TaskQueueItem.next_attempt_at.asc())

    # A plain read first: the worker asks every few seconds, and an empty queue must not take
    # the studio's write lock each time.
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            return None
        if session.scalars(select(TaskQueueItem.id).where(eligible_when).limit(1)).first() is None:
            return None

    with Session(engine) as session, session.begin():
        # Read-then-write under the write lock, so two claimers (two processes on one
        # database) are served one after the other and cannot both take the same row.
        lock_for_write(session)
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            return None
        eligible = session.scalars(
            select(TaskQueueItem).where(eligible_when).order_by(*order).limit(1)
        ).first()

        if eligible is None:
            return None

        eligible.status = "CLAIMED"
        eligible.lease_token = new_lease_token(worker_id)
        eligible.lease_expires_at = lease_expiry
        eligible.attempts += 1
        eligible.updated_at = now_str
        session.flush()
        return TaskQueueItemView.model_validate(eligible).model_dump()


def new_lease_token(worker_id: str) -> str:
    """A token no other claim has: the worker's id (cut to fit the column) and a uuid."""
    return f"{worker_id[:27]}:{uuid4().hex}"


def sweep_interrupted_tasks(engine: Engine) -> list[dict]:
    """Dead-letter every leased task whose lease lapsed with no attempts left; the tasks.

    Its holder is gone — the process was killed, crashed or the machine restarted — and the
    task had its last attempt, so nothing runs it again on its own. Each becomes DEAD_LETTER
    with ``error_detail`` opening with INTERRUPTED and one `TASK_INTERRUPTED_EVENT`; the caller
    (the worker) tells the Owner about the kinds of work he cares for. A lapsed task with
    attempts left is not touched: the queue re-claims it, as before.

    Not behind the autonomy stop: it starts nothing and spends nothing, it only records that
    a dead task is dead — and a day left CLAIMED would make the Owner's own start refuse,
    saying a run is already under way.
    """
    now_str = utc_now()
    lapsed = (
        (TaskQueueItem.status.in_(LEASED_STATES))
        & (TaskQueueItem.lease_expires_at < now_str)
        & (TaskQueueItem.attempts >= TaskQueueItem.max_attempts)
    )
    with Session(engine) as session:
        if session.scalars(select(TaskQueueItem.id).where(lapsed).limit(1)).first() is None:
            return []

    swept: list[dict] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for task in session.scalars(select(TaskQueueItem).where(lapsed)):
            previous_token = task.lease_token
            lapsed_at = task.lease_expires_at
            task.status = "DEAD_LETTER"
            task.error_detail = (
                f"{INTERRUPTED}: procesul care rula sarcina s-a oprit înainte să o încheie "
                f"(contractul expirat la {str(lapsed_at)[:19]}); sarcina și-a folosit "
                "încercările și nu este pornită din nou automat."
            )
            task.lease_token = None
            task.lease_expires_at = None
            task.updated_at = now_str
            append_event_with_outbox(
                session,
                TASK_INTERRUPTED_EVENT,
                "task_queue",
                task.id,
                1,
                {
                    "task_type": task.task_type,
                    "attempts": task.attempts,
                    "max_attempts": task.max_attempts,
                    "lease_token": previous_token,
                    "lease_expired_at": lapsed_at,
                },
                task.id,
            )
            swept.append(TaskQueueItemView.model_validate(task).model_dump())
    for item in swept:
        logger.error(
            "task_interrupted", extra={"task_id": item["id"], "task_type": item["task_type"]}
        )
    return swept


def _held(task: TaskQueueItem | None, lease_token: str) -> bool:
    return task is not None and task.status in LEASED_STATES and task.lease_token == lease_token


def heartbeat_task(
    engine: Engine,
    task_id: str,
    lease_token: str,
    extension_seconds: int = 30,
) -> bool:
    """Push the lease on while the holder still has it; False once it is no longer its own."""
    now_dt = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        task = session.get(TaskQueueItem, task_id)
        if not _held(task, lease_token):
            return False
        assert task is not None  # _held says so
        task.lease_expires_at = (now_dt + timedelta(seconds=extension_seconds)).isoformat()
        task.updated_at = now_dt.isoformat()
        return True


def complete_task(
    engine: Engine,
    task_id: str,
    lease_token: str,
) -> dict:
    now_str = utc_now()
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        task = session.get(TaskQueueItem, task_id)
        if task is None or task.lease_token != lease_token:
            raise LeaseLost(f"Task {task_id} is no longer held under lease {lease_token}")
        task.status = "COMPLETED"
        task.lease_token = None
        task.lease_expires_at = None
        task.updated_at = now_str
        session.flush()
        return TaskQueueItemView.model_validate(task).model_dump()


def fail_task(
    engine: Engine,
    task_id: str,
    lease_token: str,
    error_detail: str,
    retryable: bool = True,
) -> dict:
    now_dt = datetime.now(UTC)
    now_str = now_dt.isoformat()

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        task = session.get(TaskQueueItem, task_id)
        if task is None or task.lease_token != lease_token:
            raise LeaseLost(f"Task {task_id} is no longer held under lease {lease_token}")

        task.lease_token = None
        task.lease_expires_at = None
        task.error_detail = error_detail
        task.updated_at = now_str

        if retryable and task.attempts < task.max_attempts:
            task.status = "RETRYING"
            backoff = task.backoff_seconds * (2 ** (task.attempts - 1))
            task.next_attempt_at = (now_dt + timedelta(seconds=backoff)).isoformat()
        else:
            task.status = "DEAD_LETTER"

        session.flush()
        return TaskQueueItemView.model_validate(task).model_dump()


def retry_dead_letter_task(engine: Engine, task_id: str) -> dict:
    """Operator intervention: restore dead-letter task to queue."""
    now_str = utc_now()
    with Session(engine) as session, session.begin():
        task = session.get(TaskQueueItem, task_id)
        lock_for_write(session)  # reads the dead task, then re-queues it (see enqueue_task)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status != "DEAD_LETTER":
            raise ValueError(f"Task {task_id} status is {task.status}, not DEAD_LETTER")

        task.status = "QUEUED"
        task.attempts = 0
        task.next_attempt_at = now_str
        task.lease_token = None
        task.lease_expires_at = None
        task.error_detail = None
        task.updated_at = now_str
        session.flush()
        return TaskQueueItemView.model_validate(task).model_dump()


def list_queue_tasks(
    engine: Engine,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[dict]:
    with Session(engine) as session:
        query = select(TaskQueueItem).order_by(TaskQueueItem.created_at.desc())
        if status_filter:
            query = query.where(TaskQueueItem.status == status_filter)
        items = session.scalars(query.limit(limit)).all()
        return [TaskQueueItemView.model_validate(t).model_dump() for t in items]


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def create_scheduled_job(
    engine: Engine,
    command: CreateScheduledJobCommand,
    correlation_id: str | None = None,
) -> dict:
    """Register a recurring trigger, and record that it was registered.

    A scheduled job runs a workflow without anyone asking again, so its creation belongs in the
    history beside the Owner's other autonomy decisions.
    """
    correlation = correlation_id or str(uuid4())
    now_dt = datetime.now(UTC)
    now_str = now_dt.isoformat()
    next_run = (now_dt + timedelta(seconds=command.interval_seconds)).isoformat()

    with Session(engine) as session, session.begin():
        job = ScheduledJob(
            id=str(uuid4()),
            name=command.name,
            workflow_type=command.workflow_type,
            interval_seconds=command.interval_seconds,
            is_active=True,
            last_run_at=None,
            next_run_at=next_run,
            missed_policy=command.missed_policy,
            leader_token=None,
            leader_expires_at=None,
            created_at=now_str,
        )
        session.add(job)
        session.flush()
        event = append_event(
            session,
            "workflow.job_scheduled",
            "scheduled_job",
            job.id,
            1,
            {
                "name": job.name,
                "workflow_type": job.workflow_type,
                "interval_seconds": job.interval_seconds,
                "missed_policy": job.missed_policy,
            },
            correlation,
        )
        job.event_id = event.event_id
        return ScheduledJobView.model_validate(job).model_dump()


def list_scheduled_jobs(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        jobs = session.scalars(select(ScheduledJob).order_by(ScheduledJob.created_at)).all()
        return [ScheduledJobView.model_validate(j).model_dump() for j in jobs]


def next_run_after(
    due_at: datetime, now: datetime, interval_seconds: int, missed_policy: str
) -> datetime:
    """When a job that was due at ``due_at`` should run next.

    Both policies fire the missed slot exactly once — this tick — because a studio coming back
    from three days offline must not run three days' worth of production in a row
    (`09_CHANNELS_AND_AUTOMATION.md`: "never create a backlog explosion"). They differ in what
    happens after:

    * SKIP re-anchors the cadence to now, so a daily job that was late by six hours is late by
      six hours from then on;
    * CATCH_UP keeps the original anchor: the next run is the first slot after now on the
      schedule the job had before it was missed.
    """
    interval = timedelta(seconds=interval_seconds)
    if missed_policy != "CATCH_UP":
        return now + interval
    candidate = due_at + interval
    while candidate <= now:
        candidate += interval
    return candidate


def next_local_occurrence(run_at_local: str, timezone: str, now: datetime) -> datetime:
    """The next moment the wall clock in ``timezone`` reads ``run_at_local`` ("HH:MM").

    Computed on the local calendar and converted afterwards, so the hour survives the
    clocks changing: the day the studio leaves summer time is twenty-five hours long and
    05:00 is still 05:00 (`18_AUTOMATION_ORCHESTRATION.md`: "avoid DST creating duplicate
    or missing close jobs"). A slot exactly on the minute counts as passed — the slot the
    caller asks for is the *next* one. The answer is a UTC instant, comparable with the
    ISO strings the scheduler stores.
    """
    zone = ZoneInfo(timezone)
    hour, minute = (int(part) for part in run_at_local.split(":"))
    local_now = now.astimezone(zone)
    candidate = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
    # "Is the slot past?" is asked of the instants, not the wall clock. Two aware datetimes
    # that share one tzinfo compare as naive wall-clock time, and on the day the clocks go
    # back the wall clock reads 03:00–03:59 twice: at the second 03:30 a slot of 03:45 (its
    # first reading, forty-five minutes ago) compared as still ahead, and the job fired on
    # every tick until the wall clock passed the hour again. An hour inside the repeated
    # hour fires once, at its first reading; one inside the spring gap fires once, on the
    # first instant after it.
    if candidate.astimezone(UTC) <= now.astimezone(UTC):
        candidate = datetime.combine(
            local_now.date() + timedelta(days=1), time(hour, minute), tzinfo=zone
        )
    return candidate.astimezone(UTC)


def ensure_scheduled_job(
    engine: Engine,
    *,
    name: str,
    workflow_type: str,
    interval_seconds: int,
    missed_policy: str = "CATCH_UP",
    first_run_at: str | None = None,
    active: bool = True,
    run_at_local: str | None = None,
    timezone: str | None = None,
) -> dict:
    """The named job, created if it does not exist and left alone if it does.

    Idempotent on the unique name, so calling it at every start-up neither duplicates the job
    nor appends a second "scheduled" event for a decision already recorded. ``active=False``
    creates the schedule dormant: the studio knows when its day would start, and starting the
    clock is left to the Owner.

    ``run_at_local`` ("HH:MM") with ``timezone`` puts the job on the wall clock instead of an
    interval anchored to now. The hour is configuration, so it is the one thing an existing
    job does follow: a changed setting reaches the row and moves its next slot, without
    touching whether the job is active — following the hour is not starting the clock.
    """
    with Session(engine) as session, session.begin():
        existing = session.scalars(select(ScheduledJob).where(ScheduledJob.name == name)).first()
        # Read, then the hour rewritten: the lock first. At start-up the outbox dispatcher, the
        # lease reclaim and the GPU guard already commit beside it, and a refusal here is raised
        # out of the start-up itself (review 2026-10-09; `app.db.lock_for_write`).
        lock_for_write(session)
        if existing is not None:
            if run_at_local is not None and timezone is not None:
                if (existing.run_at_local, existing.timezone) != (run_at_local, timezone):
                    existing.run_at_local = run_at_local
                    existing.timezone = timezone
                    existing.next_run_at = next_local_occurrence(
                        run_at_local, timezone, datetime.now(UTC)
                    ).isoformat()
            return ScheduledJobView.model_validate(existing).model_dump()
    created = create_scheduled_job(
        engine,
        CreateScheduledJobCommand(
            command_id=uuid4(),
            name=name,
            workflow_type=workflow_type,
            interval_seconds=interval_seconds,
            missed_policy=missed_policy,  # type: ignore[arg-type]
        ),
    )
    if first_run_at is not None or not active or run_at_local is not None:
        with Session(engine) as session, session.begin():
            job = session.get(ScheduledJob, created["id"])
            lock_for_write(session)  # reads the new job, then sets its hour (see above)
            if job is not None:
                if run_at_local is not None and timezone is not None:
                    job.run_at_local = run_at_local
                    job.timezone = timezone
                    job.next_run_at = next_local_occurrence(
                        run_at_local, timezone, datetime.now(UTC)
                    ).isoformat()
                elif first_run_at is not None:
                    job.next_run_at = first_run_at
                job.is_active = active
                created = ScheduledJobView.model_validate(job).model_dump()
    return created


def set_job_active(engine: Engine, job_id: str, active: bool, correlation_id: str) -> dict:
    """Start or stop a schedule's clock, and record who decided.

    Activating a daily job means the studio will begin a day on its own from now on. That is an
    autonomy decision of the same weight as clearing the stop, so it is an event, not a flag
    flipped in silence. A job already in the requested state is returned unchanged.
    """
    now_dt = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        job = session.get(ScheduledJob, job_id)
        # The lock first: the job is read, then switched. Review 2026-10-09: a commit between
        # the two refused his «stop» with a 500 and left the daily job active, so the day
        # still started at its hour and bought under his paid-step rule.
        lock_for_write(session)
        if job is None:
            raise ValueError(f"Scheduled job {job_id} not found")
        if job.is_active == active:
            return ScheduledJobView.model_validate(job).model_dump()
        job.is_active = active
        if active and job.run_at_local and job.timezone:
            # On the wall clock, waking always means "the next time it is that hour": never
            # a fire on the spot, and never a slot computed from an hour since changed.
            job.next_run_at = next_local_occurrence(
                job.run_at_local, job.timezone, now_dt
            ).isoformat()
        elif active and job.next_run_at <= now_dt.isoformat():
            # A job that lay dormant with a past slot would otherwise fire the moment it wakes,
            # before the Owner has closed the panel. Waking sets the clock from now.
            job.next_run_at = (now_dt + timedelta(seconds=job.interval_seconds)).isoformat()
        event = append_event(
            session,
            "workflow.job_activated" if active else "workflow.job_deactivated",
            "scheduled_job",
            job.id,
            2,
            {"name": job.name, "workflow_type": job.workflow_type, "next_run_at": job.next_run_at},
            correlation_id,
        )
        job.event_id = event.event_id
        session.flush()
        return ScheduledJobView.model_validate(job).model_dump()


def scheduler_tick(
    engine: Engine,
    leader_id: str = "scheduler_main",
    lease_seconds: int = 15,
) -> list[dict]:
    """Fire the jobs that are due: a queued task and a `JOB_FIRED_EVENT` for each.

    Leader leasing keeps two schedulers from firing the same job; the task's idempotency key —
    the job and the slot it was due for — keeps a restart from queueing the same run twice even
    when the lease has lapsed. Nothing fires while the Owner's autonomy stop is set.
    """
    now_dt = datetime.now(UTC)
    now_str = now_dt.isoformat()
    lease_expiry = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
    triggered: list[dict] = []

    with Session(engine) as session, session.begin():
        # The tick reads the policy and the jobs, then claims their leases. Without the write
        # lock first, a write committed in between (the outbox, a start-up pass) left its read
        # snapshot stale and SQLite refused the claim at once: «database is locked» at every
        # start-up of 10-02 and 10-03 (`worker_pass_failed`), whatever `busy_timeout` says.
        lock_for_write(session)
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            return []

        jobs = session.scalars(select(ScheduledJob).where(ScheduledJob.is_active.is_(True))).all()

        for job in jobs:
            # Check leader lease
            if (
                job.leader_token
                and job.leader_expires_at
                and job.leader_expires_at > now_str
                and job.leader_token != leader_id
            ):
                continue  # Held by another scheduler leader

            # Claim lease
            job.leader_token = leader_id
            job.leader_expires_at = lease_expiry

            if job.next_run_at <= now_str:
                due_at = job.next_run_at
                key = f"scheduled:{job.id}:{due_at}"
                # A job on the wall clock moves to the next occurrence of its hour; a missed
                # slot still fires exactly once, like the interval policies below.
                if job.run_at_local and job.timezone:
                    following = next_local_occurrence(job.run_at_local, job.timezone, now_dt)
                else:
                    following = next_run_after(
                        datetime.fromisoformat(due_at),
                        now_dt,
                        job.interval_seconds,
                        job.missed_policy,
                    )
                already_queued = session.scalars(
                    select(TaskQueueItem).where(TaskQueueItem.idempotency_key == key)
                ).first()
                if already_queued is not None:
                    # A restart put the slot back, but the slot already fired. Move on; the
                    # queued task is the record and nothing new happened here.
                    job.last_run_at = now_str
                    job.next_run_at = following.isoformat()
                    job.leader_token = None
                    job.leader_expires_at = None
                    continue
                # The slot this run was due for names the task, so a second tick — or a second
                # scheduler after a restart — finds the queued work rather than adding to it.
                # No `Workflow` row: scheduled work keeps its real state where it runs (a day
                # in `DailyRun`, stage by stage), and a row nothing ever moved made its pause
                # and cancel controls that controlled nothing (AR-14). The fire itself is an
                # event, so the ledger still shows the job starting.
                task = TaskQueueItem(
                    id=str(uuid4()),
                    workflow_id=None,
                    step_id=None,
                    task_type=job.workflow_type,
                    payload={
                        "scheduled_job_id": job.id,
                        "job_name": job.name,
                        "due_at": due_at,
                    },
                    priority=0,
                    status="QUEUED",
                    attempts=0,
                    max_attempts=1,
                    backoff_seconds=5,
                    next_attempt_at=now_str,
                    lease_token=None,
                    lease_expires_at=None,
                    idempotency_key=key,
                    error_detail=None,
                    created_at=now_str,
                    updated_at=now_str,
                )
                session.add(task)
                session.flush()
                append_event_with_outbox(
                    session,
                    JOB_FIRED_EVENT,
                    "scheduled_job",
                    job.id,
                    1,
                    {
                        "job_name": job.name,
                        "workflow_type": job.workflow_type,
                        "task_id": task.id,
                        "due_at": due_at,
                    },
                    task.id,
                )

                job.last_run_at = now_str
                job.next_run_at = following.isoformat()
                triggered.append(
                    {
                        "job_id": job.id,
                        "task_id": task.id,
                        "name": job.name,
                        "due_at": due_at,
                    }
                )

            # Release leader
            job.leader_token = None
            job.leader_expires_at = None

        session.flush()
    return triggered
