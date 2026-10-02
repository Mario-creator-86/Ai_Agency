"""Stopping the studio during a day: the current scene ends, nothing new is bought.

2026-10-02 (QUEUE_LEASE_SHUTDOWN, REL-10). The lifespan's shutdown set the dispatcher's event
and awaited the worker, while the worker thread sat inside `execute_daily_run`, which only
read the Owner's stop in the database. A Ctrl+C, a stopped scheduled task or a reboot either
waited for the whole day or killed it in the middle of a film. Now a process-level shutdown
request (`request_shutdown`) is honoured by `stop_requested` — the paid loops already read it
between scenes — and the day records itself INTERRUPTED (INTERRUPTED_BY_SHUTDOWN), is never
re-run by the clock, and tells the Owner once. Every provider is faked; nothing is bought.
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any

import pytest
from app.agents.models import AgentMessage, ModelRecord
from app.agents.services import seed_initial_workforce
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.runbook.models import DailyRun
from app.runbook.services import (
    BLOCKED,
    COMPLETED,
    INTERRUPTED,
    INTERRUPTED_BY_SHUTDOWN,
    STAGES,
    clear_shutdown,
    execute_daily_run,
    request_shutdown,
    safe_mode_state,
    shutdown_requested,
    stop_requested,
)
from app.workflows.services import enqueue_task
from app.workflows.worker import DAILY_RUN, build_task_handlers, work_once
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_shutdown_left_behind():
    """A shutdown request is process state: whatever a test does, the next one starts clean."""
    clear_shutdown()
    yield
    clear_shutdown()


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "run.credentials.key")


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.scalars(select(ModelRecord)).first().is_available = True
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    return engine


def _letters(engine, kind: str) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = [
            row
            for row in session.scalars(select(AgentMessage))
            if isinstance(row.body_json, dict) and row.body_json.get("kind") == kind
        ]
        session.expunge_all()
        return rows


def test_a_shutdown_request_is_a_stop_for_the_loops_of_that_studio_only(engine, tmp_path):
    from app.db import create_db_engine

    other = create_db_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    try:
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = False
        assert stop_requested(engine) is False

        request_shutdown(engine)
        assert shutdown_requested(engine) and stop_requested(engine)
        # Another studio in the same process (a test, a rehearsal on a copy) is not stopped.
        assert not shutdown_requested(other)

        clear_shutdown(engine)
        assert stop_requested(engine) is False

        # Without an engine, the whole process is shutting down.
        request_shutdown()
        assert shutdown_requested(engine) and shutdown_requested(other)
    finally:
        other.dispose()


def test_a_shutdown_during_a_staircase_ends_after_the_current_scene_and_buys_nothing_new(
    engine, settings, vault, studio
):
    bought: list[int] = []
    later: list[str] = []

    def staircase() -> dict[str, Any]:
        for scene in (1, 2, 3, 4):
            # The paid loops read the stop before each purchase (stills_stage, assembler).
            if stop_requested(engine):
                return {
                    "status": BLOCKED,
                    "reason": f"Oprit înainte de scena {scene}.",
                    "artefacts": {"bought": list(bought)},
                }
            bought.append(scene)
            if scene == 1:
                # The studio is told to stop while scene 1's purchase is in flight.
                request_shutdown(engine)
        return {"status": COMPLETED, "reason": "toate", "artefacts": {"bought": list(bought)}}

    def after(name: str):
        def runner() -> dict[str, Any]:
            later.append(name)
            return {"status": COMPLETED, "reason": "ok"}

        return runner

    runners = {name: after(name) for name in STAGES[1:]}
    before_media = STAGES[1 : STAGES.index("media")]
    runners["media"] = staircase

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert bought == [1], "the scene in flight ends; no new purchase is started"
    assert result["status"] == INTERRUPTED
    assert result["interruption"] == INTERRUPTED_BY_SHUTDOWN
    assert result["stopped_at_stage"] == "media"
    assert result["retryable"] is False
    assert later == list(before_media), "no stage starts after the shutdown"
    by_name = {stage["stage"]: stage for stage in result["stages"]}
    assert by_name["media"]["status"] == INTERRUPTED
    assert by_name["media"]["artefacts"] == {"bought": [1]}
    for name in STAGES[STAGES.index("media") + 1 :]:
        assert by_name[name]["status"] == BLOCKED
    assert safe_mode_state(engine)["active"] is False, "a shutdown is not a P0"

    with Session(engine) as session:
        runs = list(session.scalars(select(DailyRun)))
    assert len(runs) == 1
    assert runs[0].status == INTERRUPTED and runs[0].stopped_at_stage == "media"
    assert runs[0].finished_at

    told = _letters(engine, "day_interrupted")
    assert len(told) == 1
    letter = f"{told[0].subject} {told[0].body_text}"
    assert "întreruptă" in letter and "nu o repornesc singur" in letter


def test_the_worker_claims_nothing_while_the_studio_shuts_down(engine, settings, vault):
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    enqueue_task(engine, DAILY_RUN, {"manual": True}, max_attempts=1)
    request_shutdown(engine)

    assert work_once(engine, build_task_handlers(engine, settings, vault, None)) is None


def test_the_lifespan_asks_the_day_to_stop_before_it_waits_and_leaves_no_stop_behind(
    settings, engine, monkeypatch
):
    from app import main
    from fastapi.testclient import TestClient

    asked: list[object] = []
    real = main.request_shutdown

    def spy(target=None) -> None:
        asked.append(target)
        real(target)

    monkeypatch.setattr(main, "request_shutdown", spy)
    with TestClient(main.create_app(settings)):
        assert not shutdown_requested(engine)

    assert len(asked) == 1, "the shutdown is announced to the day's loops"
    # Once the worker has been awaited the request is done: a studio started again in this
    # process (the next test, a restart in place) is not born stopped.
    assert not shutdown_requested(engine)


def test_uvicorn_is_given_a_graceful_shutdown_timeout():
    tree = ast.parse((ROOT / "scripts" / "run.py").read_text(encoding="utf-8"))
    keywords = {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "run"
        for keyword in node.keywords
    }
    assert "timeout_graceful_shutdown" in keywords
