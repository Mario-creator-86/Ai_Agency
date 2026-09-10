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
    FAILED,
    SKIPPED,
    STAGES,
    RunbookError,
    SafeModeActive,
    clear_safe_mode,
    execute_daily_run,
    safe_mode_state,
)
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
