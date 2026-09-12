"""Phase 10 — the daily runbook: preflight, staged execution, abort behaviour, safe mode.

Nothing in a daily run invents a fact about the world. The risk here is different and quieter: a
run that *reports* more than it did. A stage skipped because a provider is missing is not a stage
that quietly succeeded, and a run that stopped at step four is not a completed day.

So these tests are about the honesty of the record — a preflight that never rounds up, a status
derived from stages rather than asserted, and a skipped stage that appears in the run with its
reason instead of being left out of the list.
"""

from __future__ import annotations

import shutil
from uuid import uuid4

import pytest
from app.agents.models import ModelRecord
from app.agents.services import seed_initial_workforce
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.runbook.models import DailyRun, SafeModeRecord
from app.runbook.preflight import run_preflight
from app.runbook.services import (
    BLOCKED,
    COMPLETED,
    DAILY_RUN_TASK,
    FAILED,
    SKIPPED,
    STAGES,
    RunbookError,
    SafeModeActive,
    clear_safe_mode,
    execute_daily_run,
    pending_daily_run,
    safe_mode_state,
    start_daily_run,
)
from app.services import read_events
from app.workflows.services import claim_task, complete_task
from app.workflows.worker import build_task_handlers
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "run.credentials.key")


@pytest.fixture
def studio(engine, settings):
    """A studio the Owner has already started.

    A freshly bootstrapped studio ships with the STOP gate closed — nothing runs until a person
    opens it — and the preflight is right to call that BLOCKED. Every test below is about what
    happens *after* that decision, so the fixture makes it, and the tests that care about the
    gate itself close it again explicitly.
    """
    seed_initial_workforce(engine)
    stop_autonomy(engine, False)
    # The stage state machine is what these tests exercise; the real encoder's presence is
    # environment luck (CI images ship without it). Preflight only asks whether a path is
    # configured, so name one and keep the run observable on machines without FFmpeg.
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    return engine


def make_a_model_available(engine) -> None:
    with Session(engine) as session, session.begin():
        session.scalars(select(ModelRecord)).first().is_available = True


def stop_autonomy(engine, stopped: bool = True) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = stopped


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_preflight_reports_missing_capabilities_rather_than_rounding_up(
    engine, settings, vault, studio
):
    """A fresh studio has no verified model and no media providers. That is not READY."""
    result = run_preflight(engine, settings, vault)

    assert result["status"] == "BLOCKED"
    assert "llm_provider" in result["blocking_failures"]
    assert result["summary"].startswith("Studioul nu poate rula")


def test_a_stopped_studio_is_blocked_whatever_else_is_configured(engine, settings, vault, studio):
    make_a_model_available(engine)
    stop_autonomy(engine)

    result = run_preflight(engine, settings, vault)

    assert result["status"] == "BLOCKED"
    assert "stop_autonomy" in result["blocking_failures"]


def test_missing_media_providers_degrade_rather_than_block(engine, settings, vault, studio):
    make_a_model_available(engine)

    result = run_preflight(engine, settings, vault)

    assert result["status"] == "DEGRADED"
    assert "image_provider" in result["degrading_failures"]
    assert result["blocking_failures"] == []
    # The wording matters: "DEGRADED" alone invites being read as "fine for now".
    assert "nepublicabile" in result["summary"]


def test_every_check_says_what_it_found(engine, settings, vault, studio):
    result = run_preflight(engine, settings, vault)

    for check in result["checks"]:
        assert check["message"], f"{check['name']} reported nothing"
        assert check["severity"] in ("BLOCKING", "DEGRADING")


def test_preflight_changes_nothing(engine, settings, vault, studio):
    """It is read before deciding whether to act; a check with a side effect would be a trap."""
    with Session(engine) as session:
        before = session.get(OwnerPolicy, 1).version

    run_preflight(engine, settings, vault)
    run_preflight(engine, settings, vault)

    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).version == before
        assert session.scalars(select(DailyRun)).all() == []


# ---------------------------------------------------------------------------
# The run records what it did
# ---------------------------------------------------------------------------


def test_a_blocked_preflight_stops_the_run_and_says_where(engine, settings, vault, studio):
    result = execute_daily_run(engine, settings, vault)

    assert result["preflight"]["status"] == "BLOCKED"
    assert result["status"] == "BLOCKED"
    assert result["stopped_at_stage"] == "preflight"
    # Every stage still appears, marked as never attempted. A run listing three stages when the
    # runbook has twelve would mislead by the shape of the page.
    assert len(result["stages"]) == len(STAGES)
    assert all(s["status"] == BLOCKED for s in result["stages"][1:])


def test_a_stage_with_no_implementation_is_skipped_with_a_reason(engine, settings, vault, studio):
    make_a_model_available(engine)

    result = execute_daily_run(engine, settings, vault)

    skipped = [s for s in result["stages"] if s["status"] == SKIPPED]
    assert skipped, "unimplemented stages must be visible, not omitted"
    assert all(s["reason"] for s in skipped)
    assert result["status"] == "PARTIAL", "a day with skipped stages is not a completed day"


def test_a_run_is_completed_only_when_every_stage_ran(engine, settings, vault, studio):
    make_a_model_available(engine)
    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "COMPLETED"
    assert result["stages_completed"] == len(STAGES)


def test_a_failing_stage_stops_the_run_and_the_rest_is_marked_blocked(
    engine, settings, vault, studio
):
    make_a_model_available(engine)

    def explode():
        raise RuntimeError("provider timeout")

    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}
    runners["media"] = explode

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "FAILED"
    assert result["stopped_at_stage"] == "media"
    stages = {s["stage"]: s for s in result["stages"]}
    assert stages["media"]["status"] == FAILED
    assert "provider timeout" in stages["media"]["reason"]
    assert stages["publish"]["status"] == BLOCKED, "later stages did not run and must not claim to"


def test_a_stage_that_blocks_itself_stops_the_run(engine, settings, vault, studio):
    """A hard gate refusing is not a crash; it is the gate doing its job."""
    make_a_model_available(engine)
    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}
    runners["publish"] = lambda: {"status": BLOCKED, "reason": "Poarta de publicare a refuzat."}

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "BLOCKED"
    assert result["stopped_at_stage"] == "publish"
    assert "Poarta de publicare" in result["stop_reason"]


def test_the_status_cannot_be_asserted_by_a_stage(engine, settings, vault, studio):
    """A stage reporting COMPLETED does not make the run completed if another was skipped."""
    make_a_model_available(engine)
    runners = {"idea_generation": lambda: {"status": COMPLETED, "reason": "ok"}}

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "PARTIAL"


def test_the_day_is_closed_even_when_the_run_did_not_finish(engine, settings, vault, studio):
    """A partial day is still a day, and the log is what tomorrow's episode is checked against."""
    make_a_model_available(engine)

    result = execute_daily_run(engine, settings, vault)

    daily_log_stage = next(s for s in result["stages"] if s["stage"] == "daily_log")
    assert daily_log_stage["status"] == COMPLETED
    assert daily_log_stage["artefacts"]["log_id"]


def test_the_run_is_stored_with_the_preflight_it_ran_under(engine, settings, vault, studio):
    make_a_model_available(engine)

    result = execute_daily_run(engine, settings, vault)

    with Session(engine) as session:
        stored = session.get(DailyRun, result["id"])
    assert stored.preflight_status == "DEGRADED"
    assert stored.preflight_json["degrading_failures"]
    assert stored.status == stored.status.upper()


# ---------------------------------------------------------------------------
# Safe mode
# ---------------------------------------------------------------------------


def test_a_failed_stage_puts_the_studio_into_safe_mode(engine, settings, vault, studio):
    """An unattended studio must not carry on to tomorrow with an unexamined fault behind it."""
    make_a_model_available(engine)

    def explode():
        raise RuntimeError("disk full")

    result = execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners={
            "media": explode,
            **{name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:6]},
        },
    )

    assert result["status"] == "FAILED"
    state = safe_mode_state(engine)
    assert state["active"] is True
    assert state["trigger"] == "STAGE_FAILURE"
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).autonomy_stopped is True


def test_no_run_starts_while_safe_mode_is_active(engine, settings, vault, studio):
    make_a_model_available(engine)

    def explode():
        raise RuntimeError("disk full")

    execute_daily_run(engine, settings, vault, stage_runners={"performance_intake": explode})

    with pytest.raises(SafeModeActive):
        execute_daily_run(engine, settings, vault)


def test_leaving_safe_mode_requires_saying_what_was_checked(engine, settings, vault, studio):
    make_a_model_available(engine)
    execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners={"performance_intake": lambda: (_ for _ in ()).throw(RuntimeError("x"))},
    )

    with pytest.raises(RunbookError):
        clear_safe_mode(engine, "   ")

    assert safe_mode_state(engine)["active"] is True


def test_leaving_safe_mode_does_not_restart_autonomy(engine, settings, vault, studio):
    """Examining an incident and deciding the studio should act again are separate choices."""
    make_a_model_available(engine)
    execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners={"performance_intake": lambda: (_ for _ in ()).throw(RuntimeError("x"))},
    )

    result = clear_safe_mode(engine, "Am verificat discul; era plin, l-am eliberat.")

    assert result["cleared"] is True
    assert safe_mode_state(engine)["active"] is False
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).autonomy_stopped is True, (
            "one click must not both close the incident and restart the studio"
        )


def test_a_second_failure_does_not_obscure_when_safe_mode_began(engine, settings, vault, studio):
    make_a_model_available(engine)
    boom = {"performance_intake": lambda: (_ for _ in ()).throw(RuntimeError("x"))}
    execute_daily_run(engine, settings, vault, stage_runners=boom)
    first = safe_mode_state(engine)["entered_at"]

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    with pytest.raises(SafeModeActive):
        execute_daily_run(engine, settings, vault, stage_runners=boom)

    with Session(engine) as session:
        records = session.scalars(select(SafeModeRecord)).all()
    assert len(records) == 1
    assert safe_mode_state(engine)["entered_at"] == first


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_starting_the_day_returns_at_once_and_says_it_started(
    client, headers, engine, settings, studio
):
    """The run takes minutes; the browser gave up after ten seconds and said the connection
    was unavailable while the studio kept working. The button queues the day instead."""
    settings.worker_enabled = True
    make_a_model_available(engine)

    response = client.post(
        "/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "QUEUED" and body["task_id"]
    assert "pornit" in body["message"]
    # Queued, not run: nothing is recorded as a day until the worker has done one.
    with Session(engine) as session:
        assert session.scalars(select(DailyRun)).all() == []
    assert pending_daily_run(engine)["task_type"] == DAILY_RUN_TASK

    listed = client.get("/api/v1/runbook/runs", headers=headers).json()
    assert listed["pending"]["id"] == body["task_id"]


def test_a_second_start_while_one_is_on_its_way_is_refused_with_the_reason(
    client, headers, engine, settings, studio
):
    settings.worker_enabled = True
    make_a_model_available(engine)
    client.post("/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers)

    again = client.post("/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers)

    assert again.status_code == 409
    assert "deja în lucru" in again.json()["detail"]


def test_the_day_does_not_start_while_autonomy_is_stopped_and_says_so(
    client, headers, engine, settings, studio
):
    settings.worker_enabled = True
    stop_autonomy(engine, True)

    response = client.post(
        "/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers
    )

    assert response.status_code == 409
    assert "AUTONOMIE" in response.json()["detail"]
    assert pending_daily_run(engine) is None


def test_safe_mode_refuses_to_queue_a_day_just_as_it_refuses_to_run_one(
    engine, settings, vault, studio
):
    settings.worker_enabled = True
    make_a_model_available(engine)
    execute_daily_run(engine, settings, vault, stage_runners={"media": lambda: 1 / 0})

    with pytest.raises(SafeModeActive):
        start_daily_run(engine, settings, str(uuid4()))
    assert pending_daily_run(engine) is None


def test_the_day_is_not_queued_when_nobody_would_pick_it_up(client, headers, engine, studio):
    """The worker is what runs a queued day; with it off, the button would queue silence."""
    response = client.post(
        "/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers
    )

    assert response.status_code == 409
    assert "worker_enabled" in response.json()["detail"]
    assert pending_daily_run(engine) is None


def test_a_run_the_owner_asked_for_repeats_a_day_the_clock_would_not(
    engine, settings, vault, studio
):
    """One run per day is the schedule's rule. The Owner's button is a decision, not a tick."""
    make_a_model_available(engine)
    execute_daily_run(engine, settings, vault)
    handlers = build_task_handlers(engine, settings, vault, None)

    scheduled = handlers[DAILY_RUN_TASK]({"id": str(uuid4()), "payload": {}})
    manual = handlers[DAILY_RUN_TASK]({"id": str(uuid4()), "payload": {"manual": True}})

    assert scheduled["status"] == "SKIPPED" and "rulat deja" in scheduled["reason"]
    assert manual["status"] in ("PARTIAL", "COMPLETED", "BLOCKED", "FAILED")
    assert manual["run_id"] != scheduled["run_id"]


def test_the_worker_runs_the_day_the_owner_queued(client, headers, engine, settings, vault, studio):
    settings.worker_enabled = True
    make_a_model_available(engine)
    client.post("/api/v1/runbook/runs", json={"command_id": str(uuid4())}, headers=headers)
    handlers = build_task_handlers(engine, settings, vault, None)

    task = claim_task(engine, "worker_test", lease_duration_seconds=600)
    assert task is not None and task["task_type"] == DAILY_RUN_TASK
    result = handlers[DAILY_RUN_TASK](task)
    complete_task(engine, task["id"], task["lease_token"])

    assert result["run_id"]

    with Session(engine) as session:
        assert len(session.scalars(select(DailyRun)).all()) == 1
    assert pending_daily_run(engine) is None


def test_every_stage_says_when_it_starts_and_how_it_ended(engine, settings, vault, studio):
    """Where production is, while it is there: the ledger reads these as they happen."""
    make_a_model_available(engine)

    execute_daily_run(engine, settings, vault)

    types = [e["event_type"] for e in read_events(engine, after=0, limit=300)["events"]]
    assert "runbook.daily_run_started" in types
    assert types.count("runbook.stage_started") == len(STAGES) - 1
    assert types.count("runbook.stage_finished") == len(STAGES) - 1
    assert types.index("runbook.daily_run_started") < types.index("runbook.stage_started")
    assert types.index("runbook.stage_finished") < types.index("runbook.daily_run_finished")


def test_the_api_reports_preflight_without_running_anything(client, headers, engine, studio):
    response = client.get("/api/v1/runbook/preflight", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] in ("READY", "DEGRADED", "BLOCKED")
    with Session(engine) as session:
        assert session.scalars(select(DailyRun)).all() == []


def test_clearing_safe_mode_when_none_is_active_is_refused(client, headers, studio):
    response = client.post(
        "/api/v1/runbook/safe-mode/clear",
        json={"command_id": str(uuid4()), "notes": "nimic de verificat"},
        headers=headers,
    )

    assert response.status_code == 409


def test_a_write_that_takes_the_lock_first_survives_a_commit_beside_it(tmp_path):
    """The failure that killed two watched runs, and the line that prevents it.

    SQLite's deferred BEGIN takes a read snapshot at the first SELECT. A transaction that reads
    and then writes asks to upgrade it, and if anything committed in between SQLite refuses at
    once — with the lock already free, so `busy_timeout` has nothing to wait for. `lock_for_write`
    makes the transaction a writer before it reads, and then it cannot be refused.
    """
    import sqlite3

    from app.db import create_db_engine, lock_for_write
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'lock.db'}")
    with engine.begin() as setup:
        setup.execute(text("CREATE TABLE owner_policy (id INTEGER PRIMARY KEY, version INT)"))
        setup.execute(text("INSERT INTO owner_policy (id, version) VALUES (1, 1)"))
        setup.execute(text("CREATE TABLE note (id INTEGER PRIMARY KEY, n INT)"))
        setup.execute(text("INSERT INTO note (id, n) VALUES (1, 0)"))

    def commit_beside(table: str) -> None:
        other = sqlite3.connect(str(tmp_path / "lock.db"), isolation_level=None, timeout=30)
        other.execute("PRAGMA busy_timeout=30000")
        other.execute(f"UPDATE {table} SET n = n + 1 WHERE id = 1")
        other.close()

    # Without it: read, someone else commits, write — refused, and no waiting can help.
    with pytest.raises(Exception) as refused:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT n FROM note WHERE id = 1")).all()
            commit_beside("note")
            session.execute(text("UPDATE note SET n = 99 WHERE id = 1"))
    assert "database is locked" in str(refused.value).lower()

    # With it: the transaction is a writer from the start, so the other connection waits its
    # turn and this one commits.
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        session.execute(text("SELECT n FROM note WHERE id = 1")).all()
        session.execute(text("UPDATE note SET n = 42 WHERE id = 1"))
    with engine.connect() as check:
        assert check.execute(text("SELECT n FROM note WHERE id = 1")).scalar() == 42


def test_production_work_shows_on_the_employee_doing_it(engine):
    """Found live on 2026-09-12: Lyra's voice was recorded for five minutes while the office
    showed her IDLE and the ledger was silent. WORKING for as long as the work runs, IDLE after
    — also when the vendor fails — and nothing at all for a role nobody holds."""
    from app.agents.memory import agent_for_role
    from app.agents.services import at_work, seed_initial_workforce
    from app.models import DomainEvent
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    seed_initial_workforce(engine)

    def state() -> str:
        with Session(engine) as session:
            return agent_for_role(session, "VoiceArtist").runtime_state

    during: list[str] = []
    with at_work(engine, "VoiceArtist", "synthesize_voice", "vocea scenei 3"):
        during.append(state())
    assert during == ["WORKING"]
    assert state() == "IDLE"

    with Session(engine) as session:
        changes = [
            event.payload
            for event in session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == "agent.state_changed")
                .order_by(DomainEvent.sequence)
            )
        ]
    assert [c["runtime_state"] for c in changes[-2:]] == ["WORKING", "IDLE"]
    assert changes[-2]["detail"] == "vocea scenei 3"

    with pytest.raises(RuntimeError):
        with at_work(engine, "VoiceArtist", "synthesize_voice", "vocea scenei 4"):
            raise RuntimeError("the vendor refused")
    assert state() == "IDLE"

    with at_work(engine, "NoSuchRole", "anything", "nobody"):
        pass


def test_a_render_cost_is_read_from_the_credits(engine):
    """The Owner's instruction: verify the cost from the credits, before and after."""
    from app.economy.credits import credit_balances, credit_spend

    before = {
        "rw": {"kind": "runway", "unit": "credits", "balance": 1700.0},
        "el": {"kind": "elevenlabs", "unit": "characters", "used": 1411.0, "limit": 10000},
    }
    after = {
        "rw": {"kind": "runway", "unit": "credits", "balance": 1662.0},
        "el": {"kind": "elevenlabs", "unit": "characters", "used": 1608.0, "limit": 10000},
    }
    spent = credit_spend(before, after)
    assert spent["rw"]["spent"] == 38.0 and spent["rw"]["before"] == 1700.0
    assert spent["el"]["spent"] == 197.0 and spent["el"]["after"] == 1608.0
    assert credit_spend(before, {}) == {}  # a vendor that did not answer the second time

    class NoVault:
        def decrypt(self, value):
            raise AssertionError("nothing to decrypt in a studio with no connections")

    assert credit_balances(engine, NoVault()) == {}
