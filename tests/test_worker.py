"""The worker's FILM_CONTINUE task: the Owner's yes moves his film on the same day.

2026-10-02 (CONTINUE_REDOS_E2E; A6, AR-05). The daily run does one successful day per date,
and nothing reacted to his answer on a paid step of a film, so under EVERY_PAID_STEP a film
climbed one stair a day. His APPROVED answer (and his look at the hero take) now queues
FILM_CONTINUE for that film, which the worker runs behind his stop, his mode and the film's
purchase lease. The scheduled day stays one per date. Every vendor is faked or absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.models import OwnerPolicy
from app.runbook.models import DailyRun
from app.services import FILM_CONTINUE_TASK
from app.workflows.models import TaskQueueItem
from app.workflows.services import enqueue_task
from app.workflows.worker import FILM_CONTINUE, build_task_handlers, work_once
from sqlalchemy import select
from sqlalchemy.orm import Session


def _vault(engine):
    from app.integrations.vault import CredentialVault

    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def _studio(engine, *, environment: str = "PRODUCTION", stopped: bool = False) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = environment
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.autonomy_stopped = stopped


def _tasks(engine, task_type: str = FILM_CONTINUE_TASK) -> list[TaskQueueItem]:
    with Session(engine) as session:
        found = list(
            session.scalars(
                select(TaskQueueItem)
                .where(TaskQueueItem.task_type == task_type)
                .order_by(TaskQueueItem.created_at)
            )
        )
        session.expunge_all()
        return found


def _handlers(engine, settings):
    return build_task_handlers(engine, settings, _vault(engine), stage_runners={}, registry=None)


def _queue(engine, storyboard_id: str = "board-1", **payload: Any) -> dict:
    return enqueue_task(
        engine,
        FILM_CONTINUE,
        {"storyboard_id": storyboard_id, "cause": "approval:a-1", **payload},
        idempotency_key=f"film-continue-{storyboard_id}-a-1",
        max_attempts=1,
    )


def test_the_task_type_is_the_kernels_and_has_a_handler(engine, settings):
    assert FILM_CONTINUE == FILM_CONTINUE_TASK == "FILM_CONTINUE"
    assert FILM_CONTINUE in _handlers(engine, settings)


def test_a_continuation_walks_its_film_and_writes_no_daily_run(engine, settings, monkeypatch):
    from app.runbook import stages

    _studio(engine)
    walked: list[dict[str, Any]] = []

    def continue_film(engine_, settings_, vault, registry, storyboard_id, **kwargs):
        walked.append({"storyboard_id": storyboard_id, **kwargs})
        return {"status": "COMPLETED", "reason": "Filmul a mers mai departe.", "refusal": None}

    monkeypatch.setattr(stages, "continue_film", continue_film)
    task = _queue(engine)

    ran = work_once(engine, _handlers(engine, settings))

    assert ran["status"] == "COMPLETED", ran
    assert ran["outcome"]["status"] == "COMPLETED"
    (call,) = walked
    assert call["storyboard_id"] == "board-1"
    assert call["cause"] == "approval:a-1"
    assert call["correlation_id"] == task["id"]
    # The scheduled day stays one per date: a continuation is not a day.
    with Session(engine) as session:
        assert session.scalars(select(DailyRun)).all() == []


def test_a_continuation_without_a_film_is_dead_lettered_with_the_reason(engine, settings):
    _studio(engine)
    enqueue_task(engine, FILM_CONTINUE, {"cause": "approval:a-1"}, max_attempts=1)

    ran = work_once(engine, _handlers(engine, settings))

    assert ran["status"] == "DEAD_LETTER"
    assert "film" in ran["reason"]


def test_a_film_busy_elsewhere_is_continued_later_and_not_for_ever(engine, settings, monkeypatch):
    """Another buyer holds the film's purchase lease (the daily run, his own press): nothing
    is bought twice; the continuation is queued again ten minutes on, at most three times."""
    from datetime import UTC, datetime

    from app.runbook import stages

    _studio(engine)
    monkeypatch.setattr(
        stages,
        "continue_film",
        lambda *a, **k: {
            "status": "SKIPPED",
            "reason": "Filmul este deja în lucru.",
            "refusal": "FILM_BUSY",
        },
    )
    _queue(engine)
    handlers = _handlers(engine, settings)

    first = work_once(engine, handlers)

    later = [t for t in _tasks(engine) if t.status == "QUEUED"]
    assert len(later) == 1, [(t.status, t.idempotency_key) for t in _tasks(engine)]
    assert later[0].payload["deferred"] == 1
    wait = datetime.fromisoformat(later[0].next_attempt_at) - datetime.now(UTC)
    assert 8 * 60 < wait.total_seconds() <= 10 * 60
    assert first["outcome"]["deferred_task_id"] == later[0].id

    # The third deferral is the last one.
    with Session(engine) as session, session.begin():
        for task in session.scalars(select(TaskQueueItem)):
            task.next_attempt_at = "2000-01-01T00:00:00+00:00"
            if task.status == "QUEUED":
                task.payload = {**task.payload, "deferred": 3}
    last = work_once(engine, handlers)
    assert "deferred_task_id" not in last["outcome"]
    assert [t for t in _tasks(engine) if t.status == "QUEUED"] == []


def test_under_his_stop_a_continuation_is_not_even_claimed(engine, settings, monkeypatch):
    from app.runbook import stages

    _studio(engine, stopped=True)
    monkeypatch.setattr(stages, "continue_film", lambda *a, **k: pytest.fail("ran under STOP"))
    _queue(engine)

    assert work_once(engine, _handlers(engine, settings)) is None


def test_in_test_the_continuation_buys_nothing_and_says_why(engine, settings, monkeypatch):
    from app.runbook import stages

    _studio(engine, environment="TEST")
    monkeypatch.setattr(
        stages, "_media_staircase", lambda *a, **k: pytest.fail("climbed a sheet in TEST")
    )

    outcome = stages.continue_film(
        engine, settings, _vault(engine), None, "board-1", cause="approval:a", correlation_id="c"
    )

    assert outcome["status"] == "SKIPPED"
    assert "TEST" in outcome["reason"]


def test_the_stop_set_after_the_task_was_claimed_still_stops_it(engine, settings, monkeypatch):
    from app.runbook import stages

    _studio(engine, stopped=True)
    monkeypatch.setattr(
        stages, "_media_staircase", lambda *a, **k: pytest.fail("climbed a sheet under STOP")
    )

    outcome = stages.continue_film(
        engine, settings, _vault(engine), None, "board-1", cause="approval:a", correlation_id="c"
    )

    assert outcome["status"] == "BLOCKED"


def test_a_film_that_is_gone_or_retired_is_not_continued(engine, settings, monkeypatch):
    from app.runbook import stages

    _studio(engine)
    monkeypatch.setattr(
        stages, "_media_staircase", lambda *a, **k: pytest.fail("climbed a missing film")
    )

    outcome = stages.continue_film(
        engine, settings, _vault(engine), None, str(uuid4()), cause="x", correlation_id="c"
    )

    assert outcome["status"] == "SKIPPED"
    assert "nu" in outcome["reason"]


# ------------------------------------------------ his look at a take continues the film too


def _a_paid_shot(engine, tmp_path) -> tuple[str, str]:
    from hashlib import sha256

    from app.media.assembler import motion_fields, scene_clip_context, take_hash
    from app.media.models import SceneTake
    from test_film_costing import a_film

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    clip = tmp_path / "hero.mp4"
    clip.write_bytes(b"a clip")
    scene, still_sha, _ = scene_clip_context(engine, storyboard_id, 1)
    identity = take_hash(motion_fields(scene, still_sha, from_prompt=False), "seedance2_5")
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="test_shot",
                prompt_hash=identity,
                model_id="seedance2_5",
                resolution="1080:1920",
                status="PAID",
                path=str(clip),
                sha256=sha256(clip.read_bytes()).hexdigest(),
                created_at="2026-10-02T10:00:00+00:00",
                updated_at="2026-10-02T10:00:00+00:00",
            )
        )
    return storyboard_id, take_id


def test_his_look_approving_a_shot_queues_the_film_to_continue(engine, tmp_path):
    from app.media.assembler import decide_take

    _studio(engine)
    storyboard_id, take_id = _a_paid_shot(engine, tmp_path)

    decide_take(engine, take_id, "APPROVED", decided_by="owner")

    (task,) = _tasks(engine)
    assert task.payload["storyboard_id"] == storyboard_id
    assert task.payload["take_id"] == take_id
    assert task.idempotency_key == f"film-continue-{storyboard_id}-take-{take_id}"


def test_his_rejection_of_a_shot_queues_nothing(engine, tmp_path):
    from app.media.assembler import decide_take

    _studio(engine)
    _storyboard_id, take_id = _a_paid_shot(engine, tmp_path)

    decide_take(engine, take_id, "REJECTED", decided_by="owner", note="Nu.")

    assert _tasks(engine) == []


# ------------------------------------------------- leases (QUEUE_LEASE_SHUTDOWN, A16/AR-17) --
#
# 2026-10-02. The lease token was the worker's id, the constant 'worker_main' in every process,
# so a second process (the scheduled task plus a manual start.cmd) could complete or fail the
# first one's claim; `heartbeat_task` had no caller, so a day longer than the hour's lease was
# handed out again while it ran. Each claim now carries its own token, a background heartbeat
# keeps a running handler's lease, a lost lease is refused loudly, and one worker per database
# runs at a time (an OS file lock beside it).


def _stop_off(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False


def test_every_claim_has_its_own_lease_token(engine):
    from app.workflows.services import claim_task

    _stop_off(engine)
    enqueue_task(engine, "ANY", {})
    enqueue_task(engine, "ANY", {})

    first = claim_task(engine, "worker_main", lease_duration_seconds=60)
    second = claim_task(engine, "worker_main", lease_duration_seconds=60)

    assert first is not None and second is not None
    assert first["lease_token"] != second["lease_token"]
    assert first["lease_token"].startswith("worker_main:")
    assert second["lease_token"].startswith("worker_main:")


def test_a_worker_whose_lease_was_taken_over_cannot_complete_or_fail_the_task(engine):
    from datetime import UTC, datetime, timedelta

    from app.workflows.services import LeaseLost, claim_task, complete_task, fail_task

    _stop_off(engine)
    queued = enqueue_task(engine, "ANY", {}, max_attempts=3)
    dead = claim_task(engine, "worker_main", lease_duration_seconds=60)
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, queued["id"]).lease_expires_at = (
            datetime.now(UTC) - timedelta(minutes=1)
        ).isoformat()
    # The same worker id in another process: before, its token equalled the dead one's.
    alive = claim_task(engine, "worker_main", lease_duration_seconds=60)
    assert alive is not None and alive["id"] == queued["id"]

    with pytest.raises(LeaseLost):
        complete_task(engine, queued["id"], dead["lease_token"])
    with pytest.raises(LeaseLost):
        fail_task(engine, queued["id"], dead["lease_token"], "late", retryable=True)
    assert issubclass(LeaseLost, ValueError)

    assert complete_task(engine, queued["id"], alive["lease_token"])["status"] == "COMPLETED"


def test_a_background_heartbeat_keeps_a_long_handlers_lease(engine):
    import time

    from app.workflows.services import claim_task

    _stop_off(engine)
    queued = enqueue_task(engine, "LONG", {}, max_attempts=3)
    seen: dict[str, Any] = {}

    def long_handler(task: dict[str, Any]) -> dict[str, Any]:
        seen["claimed_until"] = task["lease_expires_at"]
        time.sleep(1.5)  # past the one-second lease it was claimed with
        with Session(engine) as session:
            seen["expires"] = session.get(TaskQueueItem, task["id"]).lease_expires_at
        # Another worker asks for work after the original lease would have lapsed.
        seen["stolen"] = claim_task(engine, "other_worker", lease_duration_seconds=60)
        return {"status": "COMPLETED"}

    result = work_once(engine, {"LONG": long_handler}, lease_seconds=1, heartbeat_seconds=0.2)

    assert result is not None and result["status"] == "COMPLETED"
    assert seen["stolen"] is None, "the running handler's task was not handed out again"
    assert seen["expires"] > seen["claimed_until"], "the heartbeat moved the lease on"
    with Session(engine) as session:
        assert session.get(TaskQueueItem, queued["id"]).status == "COMPLETED"


def test_a_lost_lease_at_completion_is_refused_loudly_and_recorded(engine, monkeypatch):
    from app.models import DomainEvent
    from app.workflows import worker

    logged: list[str] = []
    # A spy, not caplog: the studio's loggers stop propagating once an app configured them.
    monkeypatch.setattr(worker.logger, "error", lambda message, *a, **k: logged.append(message))
    _stop_off(engine)
    queued = enqueue_task(engine, "TAKEN", {}, max_attempts=3)

    def taken_over(task: dict[str, Any]) -> dict[str, Any]:
        with Session(engine) as session, session.begin():
            session.get(TaskQueueItem, task["id"]).lease_token = "other:" + uuid4().hex
        return {"status": "COMPLETED"}

    result = work_once(engine, {"TAKEN": taken_over})

    assert result is not None and result["status"] == "LEASE_LOST"
    assert "task_lease_lost" in logged
    with Session(engine) as session:
        row = session.get(TaskQueueItem, queued["id"])
        assert row.status != "COMPLETED", "the other holder's claim is left to it"
        events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "workflow.task_lease_lost")
            )
        )
    assert len(events) == 1 and events[0].aggregate_id == queued["id"]


def test_one_worker_per_database_the_second_is_refused(tmp_path):
    from app.workflows.worker import acquire_worker_lock

    path = tmp_path / "studio.lock"
    first = acquire_worker_lock(path)
    assert first is not None
    try:
        assert acquire_worker_lock(path) is None, "a second holder in this process"
    finally:
        first.release()
    again = acquire_worker_lock(path)
    assert again is not None
    again.release()


_LOCK_PROBE = """
import sys
from pathlib import Path
from app.workflows.worker import acquire_worker_lock
lock = acquire_worker_lock(Path(sys.argv[1]))
print("LOCKED" if lock else "REFUSED")
"""


def _probe_lock(path: Path) -> str:
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, "-c", _LOCK_PROBE, str(path)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root / "backend")},
        cwd=str(path.parent),
        timeout=180,
        check=False,
    )
    lines = done.stdout.strip().splitlines()
    assert lines, done.stderr[-2000:]
    return lines[-1]


def test_a_second_worker_process_is_refused_by_the_lock(tmp_path):
    from app.workflows.worker import acquire_worker_lock

    path = tmp_path / "studio.lock"
    held = acquire_worker_lock(path)
    assert held is not None
    try:
        assert _probe_lock(path) == "REFUSED"
    finally:
        held.release()
    assert _probe_lock(path) == "LOCKED"


def test_a_studio_started_beside_a_running_worker_runs_no_worker_of_its_own(
    settings, engine, monkeypatch
):
    from app import main
    from app.workflows.worker import acquire_worker_lock, worker_lock_path
    from fastapi.testclient import TestClient

    warned: list[str] = []
    real_warning = main.logger.warning

    def spy(message: str, *args: Any, **kwargs: Any) -> None:
        warned.append(message)
        real_warning(message, *args, **kwargs)

    # The studio's own loggers do not propagate to pytest's capture once configured.
    monkeypatch.setattr(main.logger, "warning", spy)
    path = worker_lock_path(engine)
    assert path is not None and path.parent == Path(str(engine.url.database)).parent
    held = acquire_worker_lock(path)
    assert held is not None
    try:
        app = main.create_app(settings.model_copy(update={"worker_enabled": True}))
        with TestClient(app):
            assert app.app.state.worker_running is False
        assert "worker_refused_second_instance" in warned
    finally:
        held.release()

    app = main.create_app(settings.model_copy(update={"worker_enabled": True}))
    with TestClient(app):
        assert app.app.state.worker_running is True
    # The lock is given back at shutdown: the next start takes it.
    again = acquire_worker_lock(path)
    assert again is not None
    again.release()


def test_a_task_a_dead_worker_left_claimed_is_queued_again_at_the_next_start(engine):
    """2026-10-15 20:08Z: two FILM_CONTINUE tasks of one film, claimed by processes the Owner
    had stopped by hand, stood CLAIMED for an hour; the day-goal pass read «a film at work»
    and queued nothing. One worker per database: at its start every claimed task is an
    orphan and goes back to the queue, attempts untouched."""
    from app.workflows.services import new_lease_token, release_orphaned_claims
    from sqlalchemy.orm import Session

    task_id = enqueue_task(
        engine, FILM_CONTINUE_TASK, {"storyboard_id": "x"}, priority=5, max_attempts=1
    )["id"]
    with Session(engine) as session, session.begin():
        task = session.get(TaskQueueItem, task_id)
        task.status = "CLAIMED"
        task.attempts = 1
        task.lease_token = new_lease_token("worker_main")
        task.lease_expires_at = "2099-01-01T00:00:00+00:00"
    assert release_orphaned_claims(engine) == 1
    with Session(engine) as session:
        task = session.get(TaskQueueItem, task_id)
        assert task.status == "QUEUED" and task.lease_token is None and task.attempts == 1
    assert release_orphaned_claims(engine) == 0  # nothing claimed: nothing to release


def test_a_day_a_dead_worker_left_claimed_is_closed_at_the_next_start_not_queued(settings, engine):
    """Review 2026-10-16: the start gave every claimed task back to the queue, a day too, so
    the Owner's GO left by a killed process ran again from its start — a second subject, a
    second film. The start now closes it INTERRUPTED, even one written after this module was
    imported (only the start's own release counts every leased task an orphan), for the
    watchdog to resume its run from the stage it stopped in. Under his stop nothing is
    claimed, so what is seen is what the start did."""
    from app import main
    from app.workflows.services import new_lease_token
    from app.workflows.worker import DAILY_RUN
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    task_id = enqueue_task(engine, DAILY_RUN, {"manual": True}, priority=10, max_attempts=1)["id"]
    with Session(engine) as session, session.begin():
        task = session.get(TaskQueueItem, task_id)
        task.status = "CLAIMED"
        task.attempts = 1
        task.lease_token = new_lease_token("worker_main")
        task.lease_expires_at = "2099-01-01T00:00:00+00:00"

    app = main.create_app(settings.model_copy(update={"worker_enabled": True}))
    with TestClient(app):
        assert app.app.state.worker_running is True
    with Session(engine) as session:
        task = session.get(TaskQueueItem, task_id)
        assert task.status == "DEAD_LETTER", task.status
        assert str(task.error_detail).startswith("INTERRUPTED") and task.attempts == 1
