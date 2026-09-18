"""A failed stage costs that stage, not the day's films.

Measured on a copy of the Owner's studio on 2026-09-18: performance intake — which only reads
YouTube's numbers for films already published — failed on a refused token refresh, and the
runbook then BLOCKED every stage after it with "Rularea s-a oprit la etapa
«performance_intake»". Nothing was researched, written or filmed, and the same-day re-attempt
would have failed the same way. The audit found it worse: an HTTP 4xx from Google is HARD, and
a HARD failure opened safe mode and set the autonomy stop, so one expired statistics token
would have halted the studio until the Owner cleared it.

These tests hold the runbook to its dependency table instead: a failed stage blocks only the
stages that take their input from it, a HARD fault opens safe mode only where
`21_FAILURE_RECOVERY_PLAYBOOK` puts a P0, the Owner's stop still outranks everything, a
same-day re-attempt follows only a failure that cost the day's films, and the run's summary
says how many stages produced something rather than how many returned.

Every stage here is a stub runner, the way `test_phase10_runbook` drives the day: nothing is
generated, bought or uploaded, and no provider is called.
"""

from __future__ import annotations

import io
import shutil
from urllib.error import HTTPError, URLError

import pytest
from app.agents.services import seed_initial_workforce
from app.integrations.vault import CredentialVault
from app.models import DomainEvent, OwnerPolicy
from app.runbook.services import (
    BLOCKED,
    COMPLETED,
    FAILED,
    OWNER_STOP_REASON,
    PRODUCTION_STAGES,
    STAGE_PREREQUISITES,
    STAGES,
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
    """A studio the Owner has started, with a model the preflight can see (not BLOCKED)."""
    from app.agents.models import ModelRecord

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.scalars(select(ModelRecord)).first().is_available = True
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    settings.stage_retry_attempts = 2
    return engine


@pytest.fixture
def letters(monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.agents.director.letter_to_owner",
        lambda engine, subject, body, *a, **k: sent.append((subject, body)) or "id",
    )
    return sent


def _ok(name: str, ran: list[str], **artefacts) -> dict:
    ran.append(name)
    return {"status": COMPLETED, "reason": "ok", "artefacts": artefacts}


def _day(ran: list[str]) -> dict:
    """Every stage completes and produces what a real day's artefacts carry."""
    produced = {
        "performance_intake": {"measured": 2},
        "idea_generation": {"proposed": ["a", "b"]},
        "research_and_verification": {"pages_fetched": 3, "claims_verified": 5},
        "selection": {"topic_id": "t-1"},
        "script_and_storyboard": {"scripts": 1, "storyboards": 1},
        "serial_queue": {"written": 1, "storyboard_id": "s-1"},
        "media": {"assets": ["factual", "serial"]},
        "edit_and_qc": {"passed": 2, "failed": 0},
        "publish": {"published": [{"publication_id": "p-1"}, {"publication_id": "p-2"}]},
        "post_run": {"applied": ["d-1"]},
    }
    # The day's log has no runner of its own: the runbook closes it (`_close_the_day`).
    return {name: (lambda n=name: _ok(n, ran, **produced.get(n, {}))) for name in STAGES[1:-1]}


def _raise(exc: BaseException):
    def runner() -> dict:
        raise exc

    return runner


def _invalid_grant() -> HTTPError:
    return HTTPError(
        "https://oauth2.googleapis.com/token",
        400,
        "Bad Request",
        {},  # type: ignore[arg-type]
        io.BytesIO(b'{"error": "invalid_grant"}'),
    )


def _by_name(result: dict) -> dict[str, dict]:
    return {stage["stage"]: stage for stage in result["stages"]}


# ------------------------------------------------------------------- the table itself --


def test_the_dependency_table_names_every_stage_after_the_preflight_and_only_earlier_ones():
    assert set(STAGE_PREREQUISITES) == set(STAGES[1:])
    for name, needs in STAGE_PREREQUISITES.items():
        for need in needs:
            assert STAGES.index(need) < STAGES.index(name), (name, need)
    # The two the day reports on and records never wait for anything.
    assert STAGE_PREREQUISITES["post_run"] == () and STAGE_PREREQUISITES["daily_log"] == ()
    # Selection needs what verification writes, not today's statistics.
    assert "performance_intake" not in STAGE_PREREQUISITES["selection"]
    assert set(STAGE_PREREQUISITES["media"]) == {"script_and_storyboard", "serial_queue"}
    assert {"media", "edit_and_qc", "publish"} <= set(PRODUCTION_STAGES)
    assert "performance_intake" not in PRODUCTION_STAGES


# ------------------------------------------- the rehearsal's day, and what it should do --


@pytest.mark.parametrize(
    "fault",
    [
        URLError("[Errno 11001] rehearsal guard: DNS for 'oauth2.googleapis.com' refused"),
        _invalid_grant(),
    ],
    ids=["google-unreachable", "invalid-grant"],
)
def test_a_day_whose_performance_intake_fails_still_researches_writes_films_and_publishes(
    engine, settings, vault, studio, letters, fault
):
    ran: list[str] = []
    runners = _day(ran)
    runners["performance_intake"] = _raise(fault)

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stages = _by_name(result)
    assert stages["performance_intake"]["status"] == FAILED
    for name in STAGES[2:]:
        assert stages[name]["status"] == COMPLETED, (name, stages[name]["reason"])
    for name in ("research_and_verification", "selection", "script_and_storyboard", "media"):
        assert name in ran
    assert ran[-2:] == ["publish", "post_run"]
    # The films went out: the day is PARTIAL, not FAILED, and it is not done again today —
    # a re-attempt would choose a new subject and buy a second film.
    assert result["status"] == "PARTIAL"
    assert result["retryable"] is False
    assert result["fault_class"] in ("TRANSIENT", "HARD")
    # A 400 from Google is HARD, and it still costs one stage: no safe mode, no stop.
    assert safe_mode_state(engine)["active"] is False
    with Session(engine) as session:
        assert session.get(OwnerPolicy, 1).autonomy_stopped is False
    # The Owner is told, once, in words that do not say the day stopped.
    (subject, body) = letters[0]
    assert len(letters) == 1
    assert "performance_intake" in subject and "s-a oprit" not in subject
    assert "filmele" in body.lower()


def test_a_failed_media_blocks_quality_control_and_publishing_but_not_the_report_or_the_log(
    engine, settings, vault, studio, letters
):
    ran: list[str] = []
    runners = _day(ran)
    runners["media"] = _raise(RuntimeError("the render crashed"))

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stages = _by_name(result)
    assert stages["media"]["status"] == FAILED
    for name in ("edit_and_qc", "publish"):
        assert stages[name]["status"] == BLOCKED, name
        assert name not in ran
    assert "«media»" in stages["edit_and_qc"]["reason"]
    # Publish is blocked by quality control, which was blocked by media: the reason names the
    # stage it waited for and the fault behind it.
    assert "«edit_and_qc»" in stages["publish"]["reason"]
    assert "«media»" in stages["publish"]["reason"]
    assert stages["post_run"]["status"] == COMPLETED and "post_run" in ran
    assert stages["daily_log"]["status"] == COMPLETED
    assert result["status"] == "FAILED"
    assert result["stopped_at_stage"] == "media"
    # A HARD fault where the money is spent is the P0 safe mode exists for.
    assert safe_mode_state(engine)["active"] is True
    assert letters and letters[0][0] == "Ziua s-a oprit la etapa «media»"
    assert "edit_and_qc" in letters[0][1] and "publish" in letters[0][1]


def test_a_failed_selection_blocks_the_factual_script_but_the_serial_is_still_filmed(
    engine, settings, vault, studio, letters
):
    ran: list[str] = []
    runners = _day(ran)
    runners["selection"] = _raise(ValueError("a topic with no title"))

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stages = _by_name(result)
    assert stages["selection"]["status"] == FAILED
    assert stages["script_and_storyboard"]["status"] == BLOCKED
    assert "«selection»" in stages["script_and_storyboard"]["reason"]
    assert "script_and_storyboard" not in ran
    for name in ("serial_queue", "media", "edit_and_qc", "publish", "post_run"):
        assert stages[name]["status"] == COMPLETED, (name, stages[name]["reason"])
        assert name in ran
    # The factual film was lost to a HARD fault in a stage that spends nothing and writes
    # nothing outside: a P1 — the Owner is told, the studio is not put out of action, and a
    # re-attempt would meet the same bug.
    assert result["status"] == "FAILED" and result["fault_class"] == "HARD"
    assert result["retryable"] is False
    assert safe_mode_state(engine)["active"] is False
    assert letters and "selection" in letters[0][0]


def test_media_is_blocked_only_when_neither_the_factual_nor_the_serial_storyboard_came(
    engine, settings, vault, studio, letters
):
    ran: list[str] = []
    runners = _day(ran)
    runners["script_and_storyboard"] = _raise(ValueError("the writer's answer"))
    runners["serial_queue"] = _raise(ValueError("the showrunner's answer"))

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stages = _by_name(result)
    assert stages["media"]["status"] == BLOCKED
    assert "«script_and_storyboard»" in stages["media"]["reason"]
    assert "«serial_queue»" in stages["media"]["reason"]
    assert "media" not in ran and "publish" not in ran
    assert stages["post_run"]["status"] == COMPLETED


def test_a_skipped_prerequisite_is_not_a_failed_one(engine, settings, vault, studio, letters):
    """SKIPPED is a stage that could not run (no model, the Owner's mode): the stages after it
    still do what they can, as they always have."""
    ran: list[str] = []
    runners = _day(ran)
    runners["selection"] = lambda: {"status": "SKIPPED", "reason": "modul MANUAL"}

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert _by_name(result)["script_and_storyboard"]["status"] == COMPLETED
    assert result["status"] == "PARTIAL"
    assert letters == []


def test_the_owner_stop_still_blocks_everything_after_it(engine, settings, vault, studio, letters):
    ran: list[str] = []
    runners = _day(ran)

    def stop_while_selecting() -> dict:
        ran.append("selection")
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).autonomy_stopped = True
        return {"status": COMPLETED, "reason": "ok", "artefacts": {"topic_id": "t"}}

    runners["performance_intake"] = _raise(URLError("down"))
    runners["selection"] = stop_while_selecting

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stages = _by_name(result)
    after = STAGES[STAGES.index("selection") + 1 :]
    for name in after:
        if name == "daily_log":
            assert stages[name]["status"] == COMPLETED  # the studio worked; the day is closed
            continue
        assert stages[name]["status"] == BLOCKED, name
        assert OWNER_STOP_REASON in stages[name]["reason"], name
        assert name not in ran
    assert result["status"] == "PARTIAL"
    assert result["retryable"] is False
    assert safe_mode_state(engine)["active"] is False


# --------------------------------------------------------------- the same-day re-attempt --


def test_a_transient_failure_that_cost_the_films_is_re_attemptable(
    engine, settings, vault, studio, letters
):
    ran: list[str] = []
    runners = _day(ran)
    runners["media"] = _raise(TimeoutError("the vendor did not answer"))

    result = execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners=runners,
        sleep=lambda _s: None,
        attempt=1,
        attempts_allowed=3,
    )

    assert result["status"] == "FAILED" and result["fault_class"] == "TRANSIENT"
    assert result["retryable"] is True
    assert safe_mode_state(engine)["active"] is False
    assert letters == [], "the letter waits for the day's last attempt"


def test_a_transient_failure_that_cost_no_film_is_not_re_attempted(
    engine, settings, vault, studio, letters
):
    ran: list[str] = []
    runners = _day(ran)
    runners["idea_generation"] = _raise(TimeoutError("the model did not answer"))

    result = execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners=runners,
        sleep=lambda _s: None,
        attempt=1,
        attempts_allowed=3,
    )

    assert _by_name(result)["publish"]["status"] == COMPLETED
    assert result["status"] == "PARTIAL"
    assert result["fault_class"] == "TRANSIENT"
    assert result["retryable"] is False
    # Nothing follows today, so the Owner hears about it now, not after a third attempt.
    assert len(letters) == 1 and "idea_generation" in letters[0][0]


def test_a_transient_failure_upstream_of_the_films_is_re_attemptable(
    engine, settings, vault, studio, letters
):
    """Research broke on a lock: selection could not choose, so the factual film was lost to
    a fault that a re-attempt can change."""
    from sqlalchemy.exc import OperationalError

    ran: list[str] = []
    runners = _day(ran)
    runners["research_and_verification"] = _raise(
        OperationalError("UPDATE claim", {}, Exception("database is locked"))
    )

    result = execute_daily_run(
        engine,
        settings,
        vault,
        stage_runners=runners,
        sleep=lambda _s: None,
        attempt=1,
        attempts_allowed=3,
    )

    stages = _by_name(result)
    assert stages["selection"]["status"] == BLOCKED
    assert stages["script_and_storyboard"]["status"] == BLOCKED
    assert "«research_and_verification»" in stages["script_and_storyboard"]["reason"]
    assert stages["serial_queue"]["status"] == COMPLETED
    assert result["stopped_at_stage"] == "research_and_verification"
    assert result["retryable"] is True


# ------------------------------------------------------------------------ safe mode, P0 --


def test_a_database_integrity_fault_opens_safe_mode_wherever_it_happens(
    engine, settings, vault, studio, letters
):
    """`21`: "if audit/event/DB consistency is doubtful … require repair before autonomy
    resumes". An integrity error is that doubt, in any stage."""
    from sqlalchemy.exc import IntegrityError

    ran: list[str] = []
    runners = _day(ran)
    runners["post_run"] = _raise(
        IntegrityError("INSERT agent_message", {}, Exception("UNIQUE constraint failed"))
    )

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    assert _by_name(result)["publish"]["status"] == COMPLETED
    assert safe_mode_state(engine)["active"] is True


# ------------------------------------------------------------------ the day's headline --


def test_the_summary_counts_the_stages_that_produced_something_not_the_ones_that_returned(
    engine, settings, vault, studio
):
    """Measured in the rehearsal: "COMPLETED 12/12" for a day whose ideas were refused, whose
    research verified nothing and whose Director decided nothing."""
    ran: list[str] = []
    runners = _day(ran)
    runners["idea_generation"] = lambda: {
        "status": COMPLETED,
        "reason": "Propunerile au fost respinse",
        "artefacts": {"proposed": 0},
    }
    runners["research_and_verification"] = lambda: {
        "status": COMPLETED,
        "reason": "0 pagini",
        "artefacts": {"pages_fetched": 0, "sources_read": 0, "claims_verified": 0},
    }
    runners["post_run"] = lambda: {
        "status": COMPLETED,
        "reason": "revizuirea Directorului a fost respinsă",
        "artefacts": {"reports": 10, "review_rejected": "no decisions"},
    }

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "COMPLETED"
    stages = _by_name(result)
    assert stages["idea_generation"]["produced"] == 0
    assert stages["research_and_verification"]["produced"] == 0
    assert stages["post_run"]["produced"] == 0
    assert stages["media"]["produced"] == 2
    assert stages["publish"]["produced"] == 2
    assert stages["selection"]["produced"] == 1
    # The preflight checks and the day's log records; the ten between them are the work.
    worked = len(STAGES) - 2
    assert result["stages_productive"] == worked - 3
    summary = result["summary"]
    assert f"{worked} din {worked} etape au rulat" in summary
    assert f"{worked - 3} au produs ceva" in summary
    for name in ("idea_generation", "research_and_verification", "post_run"):
        assert name in summary
    with Session(engine) as session:
        finished = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "runbook.daily_run_finished")
        ).one()
    assert finished.payload["summary"] == summary
    # The runs list reads the same headline back from the stored stages.
    from app.runbook.services import list_runs

    (listed,) = list_runs(engine)
    assert listed["summary"] == summary and listed["stages_productive"] == worked - 3


def test_a_day_that_made_nothing_says_so(engine, settings, vault, studio):
    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}

    result = execute_daily_run(engine, settings, vault, stage_runners=runners)

    assert result["status"] == "COMPLETED"
    # The day's own log is a record of the day, not something the day made.
    assert result["stages_productive"] == 0
    assert _by_name(result)["daily_log"]["produced"] is None
    assert "nu a produs nimic" in result["summary"]
    assert "Niciun film publicat" in result["summary"]
