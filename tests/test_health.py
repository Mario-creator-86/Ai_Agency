"""/health/ready tells the truth about the parts that keep the studio running (REL-07, AR-18).

Until 2026-10-02 the probe ran ``SELECT version FROM owner_policy`` and nothing else: a worker
whose passes had stopped, a media disk with nothing left, an FFmpeg that was uninstalled and a
backup that had not run for a week all answered 200 HEALTHY. Document 25 asks for alerts on a
worker down, a scheduler down, a disk low and a backup failed.

Every test runs on the suite's tmp database and its private media folder. No provider is asked
anything; the disk and the toolchain are read through seams the tests replace.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app import backup, operations
from app.agents.models import AgentMessage
from app.main import create_app
from app.media import disk
from app.models import DomainEvent, Studio
from app.workflows.models import TaskQueueItem
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

GB = 1024**3


def state_of(client):
    return client.app.app.state


def a_running_worker(client, *, idle_minutes: float, in_pass: bool = False) -> None:
    """The background worker as the lifespan keeps it, its last pass ``idle_minutes`` ago."""
    state = state_of(client)
    state.worker_running = True
    moment = datetime.now(UTC) - timedelta(minutes=idle_minutes)
    state.operations = operations.new_operations()
    state.operations["last_pass_at"] = moment.isoformat()
    state.operations["pass_started_at"] = moment.isoformat()
    state.operations["in_pass"] = in_pass


def test_a_fresh_studio_is_healthy_and_says_what_it_checked(client):
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.json()
    body = ready.json()
    assert body["status"] == "HEALTHY"
    assert body["worker"] == "OFF"  # the suite's settings run no worker
    assert body["disk"] == "OK" and body["toolchain"] == "OK"
    assert body["backup"] == "NONE_YET"
    assert body["problems"] == []
    # Public, unauthenticated: codes only, never a path or a sentence about his studio.
    assert "path" not in str(body).lower() and "\\" not in str(body)


def test_a_worker_whose_passes_stopped_is_503_degraded(client, settings):
    a_running_worker(client, idle_minutes=10)  # interval 30 s: three intervals are 1.5 min
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["status"] == "DEGRADED"
    assert ready.json()["worker"] == "STALE"
    assert "WORKER_STALE" in ready.json()["problems"]


def test_a_long_task_with_a_live_lease_is_not_a_dead_worker(client, engine):
    a_running_worker(client, idle_minutes=45, in_pass=True)
    assert client.get("/health/ready").status_code == 503  # no task holds a lease: dead
    stamp = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            TaskQueueItem(
                id="the-day",
                task_type="DAILY_RUN",
                payload={},
                priority=0,
                status="RUNNING",
                attempts=1,
                max_attempts=1,
                backoff_seconds=5,
                next_attempt_at=stamp.isoformat(),
                lease_token="worker_main:abc",
                lease_expires_at=(stamp + timedelta(minutes=50)).isoformat(),
                created_at=stamp.isoformat(),
                updated_at=stamp.isoformat(),
            )
        )
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.json()
    assert ready.json()["worker"] == "BUSY"


def test_free_disk_under_the_minimum_is_503(client, monkeypatch):
    monkeypatch.setattr(disk, "free_bytes", lambda _path: 0)  # under any minimum
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["disk"] == "LOW" and "DISK_LOW" in ready.json()["problems"]


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_a_missing_encoder_or_inspector_is_503(client, monkeypatch, missing):
    monkeypatch.setattr(
        operations,
        f"find_{missing}",
        lambda *_args, **_kwargs: None,
    )
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["toolchain"] == "MISSING"
    assert f"{missing.upper()}_MISSING" in ready.json()["problems"]


def test_a_backup_older_than_36_hours_is_503_and_a_fresh_one_is_healthy(client, engine, tmp_path):
    database = Path(str(engine.url.database))
    folder = database.parent / "backups"
    backup.make_backup(database, folder, now=datetime.now(UTC) - timedelta(hours=40))
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["backup"] == "STALE" and "BACKUP_STALE" in ready.json()["problems"]

    backup.make_backup(database, folder, now=datetime.now(UTC) - timedelta(hours=1))
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.json()
    assert ready.json()["backup"] == "OK"


def test_a_studio_older_than_36_hours_with_no_backup_at_all_is_503(client, engine):
    with Session(engine) as session, session.begin():
        session.get(Studio, 1).created_at = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["backup"] == "MISSING"


def test_the_snapshot_carries_the_same_reading_in_the_owners_words(client, headers, settings):
    a_running_worker(client, idle_minutes=14)
    block = client.get("/api/v1/snapshot", headers=headers).json()["operations"]
    assert block["status"] == "DEGRADED"
    assert block["worker"]["status"] == "STALE"
    assert block["banner_ro"].startswith("Lucrătorul nu a mai lucrat de 14 minute")
    codes = [problem["code"] for problem in block["problems"]]
    assert codes == ["WORKER_STALE"]
    assert all(problem["reason_ro"] for problem in block["problems"])
    assert block["disk"]["free_gb"] > 0
    assert block["disk"]["min_free_gb"] == settings.min_free_gb
    assert block["backup"]["status"] == "NONE_YET"


def test_three_failed_passes_in_a_row_are_one_event_and_one_letter(engine):
    ops = operations.new_operations()
    for _ in range(4):
        operations.record_pass_failure(engine, ops, RuntimeError("database is locked"))
    assert ops["consecutive_failures"] == 4
    assert ops["last_error_class"] == "RuntimeError"
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == operations.WORKER_FAILING_EVENT)
        ).all()
        letters = [
            row
            for row in session.scalars(select(AgentMessage))
            if (row.body_json or {}).get("kind") == operations.WORKER_FAILING_LETTER
        ]
    assert len(events) == 1 and events[0].payload["consecutive_failures"] == 3
    assert len(letters) == 1
    assert "3 treceri" in letters[0].subject or "3 treceri" in (letters[0].body_text or "")
    # A good pass ends the streak.
    operations.record_pass_end(ops)
    assert ops["consecutive_failures"] == 0 and ops["last_error_class"] is None


def test_the_running_worker_keeps_its_operations_reading(settings, engine, monkeypatch):
    """The lifespan's worker loop writes app.state.operations on every pass."""
    import app.main as main

    live = settings.model_copy(
        update={"worker_enabled": True, "worker_interval_seconds": 5, "trends_enabled": False}
    )

    def failing_pass(*_args, **_kwargs):
        raise RuntimeError("a pass that fails")

    with TestClient(create_app(live)) as client:
        state = state_of(client)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not state.operations.get("last_pass_at"):
            time.sleep(0.1)
        assert state.operations["last_pass_at"], "the worker's first pass was not recorded"
        assert state.operations["consecutive_failures"] == 0
        assert state.operations["in_pass"] is False

    monkeypatch.setattr(main, "worker_pass", failing_pass)
    with TestClient(create_app(live)) as client:
        state = state_of(client)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not state.operations.get("consecutive_failures"):
            time.sleep(0.1)
        assert state.operations["consecutive_failures"] >= 1
        assert state.operations["last_error_class"] == "RuntimeError"
