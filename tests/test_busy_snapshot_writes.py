"""«Baza de date era ocupată»: a long read that then writes is refused when another write lands.

2026-10-02 and 10-03: `edit_and_qc` failed in four runs (stage_finished seq 5473, 5700, 5927,
6194; publish BLOCKED after each) with «database is locked». The stage was retried three times
each run (20, 40, 80 s) and failed every time, because the fault was not contention a wait
cures: `qc.evaluate_media_qc` opened its transaction, read the asset, then measured the file
(ffprobe, loudness, duplicate frames) for seconds, then wrote its event. Anything that committed
in between (the agents' run events, the outbox) left its read snapshot stale, and SQLite refuses
to upgrade a stale snapshot at once: no `busy_timeout` helps (`app.db.lock_for_write`). The same
error hit the Owner's own «evaluează QC» press at 05:39 on 10-03 with no start-up storm around.
The start-up storm's own failure (`worker_pass_failed` in `scheduler_tick`, 13:48:32 and
04:53:49) is the same shape: it reads the policy and the jobs, then claims their leases.

Each test commits another write between the read and the write, as the outbox does.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.media import qc
from app.media.qc import evaluate_media_qc
from app.models import DomainEvent, OwnerPolicy
from app.services import append_event
from app.workflows import services as workflow_services
from app.workflows.models import ScheduledJob
from app.workflows.services import ensure_scheduled_job, scheduler_tick
from app.workflows.worker import DAILY_RUN
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film
from test_media_qc_legacy import _from_takes, _render

#: The writers started by the tests, joined at the end of each test.
WRITERS: list[threading.Thread] = []


def _someone_else_writes(engine) -> None:
    """Another thread commits, as the outbox dispatcher does once a second. It is given two
    seconds: a reader that holds no lock lets it commit at once (and its own write is then
    refused); a writer that took the lock first makes it wait its turn, as it should."""

    def write() -> None:
        with Session(engine) as session, session.begin():
            append_event(
                session, "test.concurrent_write", "test", str(uuid4()), 1, {}, str(uuid4())
            )

    writer = threading.Thread(target=write)
    writer.start()
    writer.join(2)
    WRITERS.append(writer)


@pytest.fixture(autouse=True)
def _writers_finish():
    yield
    while WRITERS:
        WRITERS.pop().join(60)


def test_quality_control_survives_a_write_that_lands_while_it_measures(
    engine, tmp_path, monkeypatch
):
    film = a_film(engine, tmp_path, scenes=2)
    asset = _render(engine, tmp_path, film, _from_takes())
    original = qc.production_path_verdict

    def meanwhile(*args, **kwargs):
        _someone_else_writes(engine)
        return original(*args, **kwargs)

    monkeypatch.setattr(qc, "production_path_verdict", meanwhile)

    report = evaluate_media_qc(engine, asset, str(uuid4()))

    assert report["status"] in ("PASSED", "FAILED")
    with Session(engine) as session:
        assert session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.qc_evaluated")
        ).all()


def test_the_scheduler_tick_survives_a_write_that_lands_while_it_reads(engine, monkeypatch):
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    job = ensure_scheduled_job(
        engine,
        name="busy_test",
        workflow_type=DAILY_RUN,
        interval_seconds=86400,
        missed_policy="CATCH_UP",
    )
    with Session(engine) as session, session.begin():
        session.get(ScheduledJob, job["id"]).next_run_at = (
            datetime.now(UTC) - timedelta(minutes=5)
        ).isoformat()
    original = workflow_services.next_run_after

    def meanwhile(*args, **kwargs):
        _someone_else_writes(engine)
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow_services, "next_run_after", meanwhile)

    fired = scheduler_tick(engine)

    assert [item["job_id"] for item in fired] == [job["id"]]
