"""Phase 10 — running the day, and recording what actually happened at each stage.

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` lays out the stages and the abort behaviour: a
hard gate failure blocks, a retryable failure retries within bounds, a P0 goes to safe mode.

The design pressure here is different from earlier phases. Nothing in a daily run invents a fact
about the world; the risk is a run that *reports* more than it did. A stage that could not run
because a provider is missing is not a stage that succeeded quietly, and a run that stopped at
step four is not a completed day. So:

- a stage is recorded with its real outcome and the reason for it, including SKIPPED;
- the run's status is derived from its stages, never written by a caller;
- the preflight verdict is stored with the run, because "the studio ran today" means something
  different on a day when half the capabilities were missing.
"""

from __future__ import annotations

import http.client
import logging
import re
import socket
import sqlite3
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OwnerPolicy
from app.runbook.models import DailyRun, SafeModeRecord
from app.runbook.preflight import run_preflight
from app.services import append_event, utc_now
from app.story.services import (
    business_date,
    close_daily_log,
    close_missing_days,
    close_previous_day,
)
from app.wording import (
    clause,
    count,
    error_fields,
    error_words,
    sentence,
    stage_list,
    stage_name,
)
from app.workflows.services import append_event_with_outbox, enqueue_task, list_queue_tasks

logger = logging.getLogger("studio.runbook")

#: The queue task type the daily run is executed under, by the schedule and by the Owner.
DAILY_RUN_TASK = "DAILY_RUN"

#: Queue states that mean a run is already on its way: starting a second one would have two
#: days running over each other on the same books.
PENDING_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")

#: The stages of the daily runbook, in order. The serial queue (runbook §12) runs before
#: the media stage rather than after the day's log: it writes the episode of the *previous*
#: day, whose log is closed at the start of the run, and leaves a storyboard that the same
#: run's media stage films, quality control measures and the publish stage routes to
#: Channel B. Last in the list it was a stage the day never rendered — the serial existed
#: as text only. The day's own log is closed after every stage of work; only tomorrow's
#: script (``serial_next``, since 2026-09-24) comes after it, because it is written from that
#: log: the Owner's one click films one episode and writes the next.
STAGES = (
    "preflight",
    "performance_intake",
    "idea_generation",
    "research_and_verification",
    "selection",
    "script_and_storyboard",
    "serial_queue",
    "media",
    "edit_and_qc",
    "publish",
    "post_run",
    "daily_log",
    "serial_next",
)

#: The stages that read today's closed log, and so run after the close (`_close_the_day`),
#: not merely after the ``daily_log`` entry in the order.
AFTER_THE_CLOSE = STAGES[STAGES.index("daily_log") + 1 :]

#: What each stage needs from the stages before it — the only edges along which a failure
#: travels. A stage whose every listed prerequisite FAILED or was BLOCKED is BLOCKED itself,
#: with the prerequisite named; a stage with an empty entry needs nothing but the preflight
#: and runs whatever happened before it. Until 2026-09-18 any failure blocked every later
#: stage: on a copy of the Owner's studio a refused statistics token at performance intake
#: left the day with nothing researched, written or filmed. Each edge is read from what the
#: runner in `app.runbook.stages.build_stage_runners` actually reads, not from STAGES' order:
#:
#: performance_intake — the channel slots and their PUBLISHED rows; nothing of today.
#: idea_generation — the topic pool, plus the cohorts of every snapshot ever stored
#:   (`research.agent._signals`, "empty when unknown"): today's numbers are not required.
#: research_and_verification — the whole pool, every unextracted source and every UNVERIFIED
#:   claim, whichever day wrote them; a failed idea stage leaves that backlog where it was.
#: selection — only topics with SUPPORTED claims, which verification writes. The day does not
#:   choose a subject on the far side of an unexamined fault in the step that turns a page
#:   into a claim a film may cite.
#: script_and_storyboard — writes for the SELECTED topic (`script_work`), storyboards what is
#:   approved.
#: serial_queue — the previous day's closed log, closed on the preflight line, not a stage.
#: media — APPROVED storyboards: the factual one from script_and_storyboard, the serial's from
#:   serial_queue. Either one is a film to make, so media is blocked only when both are lost.
#: edit_and_qc — the files media rendered. publish — what quality control passed.
#: post_run, daily_log — the report and the record of whatever happened: nothing.
#: serial_next — today's log, closed by daily_log: with no closed log there is no day to
#:   write tomorrow's episode from, and "blocked by daily_log" says so where a quiet day
#:   would not.
STAGE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "performance_intake": (),
    "idea_generation": (),
    "research_and_verification": (),
    "selection": ("research_and_verification",),
    "script_and_storyboard": ("selection",),
    "serial_queue": (),
    "media": ("script_and_storyboard", "serial_queue"),
    "edit_and_qc": ("media",),
    "publish": ("edit_and_qc",),
    "post_run": (),
    "daily_log": (),
    "serial_next": ("daily_log",),
}

#: The stages the day's films pass through. A failure that loses one of them loses a film,
#: and that is what the same-day re-attempt exists for; a failure anywhere else costs its own
#: stage, and a re-attempt of the whole day would choose a new subject and buy a second film
#: to recover a report.
PRODUCTION_STAGES = (
    "selection",
    "script_and_storyboard",
    "serial_queue",
    "media",
    "edit_and_qc",
    "publish",
)

#: Where a HARD fault is a P0. `21_FAILURE_RECOVERY_PLAYBOOK` names four — duplicate publish,
#: uncontrolled spend, secret leak, corrupted audit state — and `36_RELIABILITY_SLO_RUNBOOK`
#: gives safe mode to P0 alone; "production blocked, provider unavailable" is P1 (pause what
#: is affected, notify). So safe mode opens for an unexplained fault in the stage that buys
#: generation (media: the studio no longer knows what it spent), in the one that writes to a
#: platform (publish: it no longer knows what it uploaded), in the day's own record
#: (daily_log), and for a database integrity error in any stage (`_doubts_the_record`). A
#: HARD fault anywhere else — a refused statistics token at performance intake, a bug in
#: selection — costs that stage and a letter to the Owner. It used to open safe mode and set
#: the autonomy stop from any stage: one expired read-only token would have halted the studio.
SAFE_MODE_STAGES = ("media", "publish", "daily_log")

#: How many things each stage made, read from the artefacts its runner already returns
#: (`app.runbook.stages`). A key holding a list counts its items, a number counts itself,
#: anything else present counts one. The preflight checks and the day's log records, so
#: neither is counted: "produced something" is about the ten stages of work between them.
PRODUCED_FROM: dict[str, tuple[str, ...]] = {
    "performance_intake": ("measured",),
    "idea_generation": ("proposed",),
    "research_and_verification": ("pages_fetched", "sources_read", "claims_verified"),
    "selection": ("topic_id",),
    "script_and_storyboard": ("scripts", "storyboards"),
    "serial_queue": ("written", "storyboard_id"),
    "media": ("assets",),
    "edit_and_qc": ("passed", "failed"),
    "publish": ("published",),
    "post_run": ("applied",),
    "serial_next": ("written",),
}

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

#: The two kinds of fault a stage can fail on. TRANSIENT is the world being slow — a
#: timeout, a provider's 429 or 5xx, SQLite's "database is locked" — and is retried in
#: place; a run that still fails is FAILED without safe mode, because nothing about the
#: studio is wrong. HARD is everything else — a wrong value, a policy refusal, a bug —
#: and keeps the old behaviour: FAILED, safe mode, a person looks.
TRANSIENT = "TRANSIENT"
HARD = "HARD"

#: What a stage is told when the Owner's switch ends the day under it.
OWNER_STOP_REASON = "Oprit de AUTONOMIE OPRITĂ."

#: HTTP statuses that say "not now" rather than "not like that".
_TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
_HTTP_IN_MESSAGE = re.compile(r"\bHTTP (\d{3})\b")


class RunbookError(RuntimeError):
    """The run could not start."""


class SafeModeActive(RunbookError):
    """The studio is in safe mode and will not act autonomously until a person clears it."""


class TransientStageError(RuntimeError):
    """A stage runner saying its failure is the world's, not the studio's: retry me.

    For the cases the classifier cannot see from the exception's shape — a provider job that
    reported "queued" for longer than the stage would wait, a vendor answering 200 with an
    error body. Raising this instead of a bare RuntimeError is what makes the difference
    between a retry twenty seconds later and safe mode until a person clears it.
    """


def _http_status(exc: BaseException) -> int | None:
    """The HTTP status an exception carries, wherever the raising code put it."""
    for attribute in ("http_status", "status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    found = _HTTP_IN_MESSAGE.search(str(exc))
    return int(found.group(1)) if found else None


def _is_transient(exc: BaseException) -> bool:
    from app.providers.media_http import MediaProviderNotConfigured  # noqa: PLC0415
    from app.providers.publishing_base import RemoteStateUnavailable  # noqa: PLC0415

    if isinstance(exc, TransientStageError):
        return True
    if isinstance(exc, MediaProviderNotConfigured):
        return False  # no key is a configuration fact, and waiting will not produce one
    if isinstance(exc, OperationalError | sqlite3.OperationalError):
        return True  # "database is locked", "unable to open database file": try again
    if isinstance(exc, RemoteStateUnavailable):
        return True  # the platform could not be asked; asking again is safe, it is a read
    status = _http_status(exc)
    if status is not None:
        # A status is the provider's own word: 4xx other than the rate limit is our
        # request being wrong, and repeating it repeats the answer.
        return status in _TRANSIENT_HTTP
    if isinstance(exc, HTTPError):
        return False
    # Network shapes. Not OSError wholesale: a missing file or a full disk is an OSError too,
    # and no retry fills a disk.
    return isinstance(
        exc,
        TimeoutError
        | ConnectionError
        | socket.gaierror
        | socket.herror
        | URLError
        | http.client.HTTPException,
    )


def classify_fault(exc: BaseException) -> str:
    """TRANSIENT or HARD, from the exception and the chain it was raised from.

    The chain matters because the studio wraps: `media_http.request` raises
    `MediaProviderError("… could not be reached") from OSError`, and a stage may wrap that
    again. The walk follows what a traceback would print — the explicit cause, else the
    implicit context unless suppressed — and stops at the first transient link. Anything
    the walk cannot name is HARD, because retrying an unknown fault is how a studio spends
    a night repeating a bug.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_transient(current):
            return TRANSIENT
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return HARD


def stop_requested(engine: Engine) -> bool:
    """Has the Owner set AUTONOMIE OPRITĂ since the work started?

    For anything that runs long inside a stage and can stop cleanly between steps — the
    media loop between scenes, a render between shots, a publish loop between videos.
    Poll it between units of work, never mid-write, and on True stop where you are and
    return what was done so far (or raise; the run records the stage BLOCKED with
    `OWNER_STOP_REASON` either way). One short read of the policy row; cheap enough to
    call before every scene. The runbook itself calls it between stages, so a stage that
    does not poll still ends the day at its own boundary.
    """
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        return bool(policy is not None and policy.autonomy_stopped)


def retryable_outcome(
    status: str,
    preflight_status: str,
    fault_class: str | None,
    *,
    production_lost: bool = True,
) -> bool:
    """Whether a day that ended like this may be attempted again by the clock today.

    Yes for a BLOCKED preflight (a provider that was down at five may be up at six) and
    for a FAILED run whose fault was transient and cost the day's films. No for a day that
    did work — COMPLETED or PARTIAL is one day's production, and a second is the Owner's
    decision — no for a hard failure, which a re-attempt would meet again, and no for a
    transient fault in a stage no film depends on: the re-attempt runs the whole day, and
    selection would choose a new subject and the media stage buy a second film to recover a
    report. ``production_lost`` defaults to True, the old reading, for a caller that cannot
    tell.
    """
    if status == "BLOCKED" and preflight_status == "BLOCKED":
        return True
    return status == "FAILED" and fault_class == TRANSIENT and production_lost


def _doubts_the_record(exc: BaseException | None) -> bool:
    """A database integrity error anywhere in the chain: `21`'s data integrity incident.

    Not `OperationalError`, which is a lock or a busy file and is TRANSIENT; an
    `IntegrityError` or any other `DatabaseError` says the record may not be what the studio
    thinks it is, and no stage's name makes that smaller.
    """
    from sqlalchemy.exc import DatabaseError  # noqa: PLC0415

    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, DatabaseError | sqlite3.DatabaseError) and not isinstance(
            current, OperationalError | sqlite3.OperationalError
        ):
            return True
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return False


def _count(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return int(bool(value))
    if isinstance(value, int | float):
        return max(0, int(value))
    if isinstance(value, list | tuple | set | dict):
        return len(value)
    return 1 if value else 0


#: A publication a legacy publish artefact names is a film on the channel only in these states:
#: out (PUBLISHED, REMOTE_CONFIRMED) or given a release time on the channel (SCHEDULED). A
#: simulated upload, a failure or a validation that went no further is not a film published.
LEGACY_PUBLISHED_STATES = ("PUBLISHED", "REMOTE_CONFIRMED", "SCHEDULED")


def _legacy_publications(artefacts: dict[str, Any]) -> int:
    """The film a publish stage recorded before its films were listed under ``published``.

    Such a run carries its one publication flat, as ``publication_id`` and
    ``publication_status`` (the 12.09 run of the Owner's studio: publication 86fe911d,
    PUBLISHED). It is read by the keys it has; nothing is inferred from the stage's status.
    """
    publication = artefacts.get("publication_id")
    status = artefacts.get("publication_status")
    if isinstance(publication, str) and publication and status in LEGACY_PUBLISHED_STATES:
        return 1
    return 0


def produced_by(stage: dict[str, Any]) -> int | None:
    """How many things a stage outcome made, from its own artefacts; None when not counted.

    The keys of `PRODUCED_FROM` are read from what the runner returned. Nothing is inferred
    from the status: a stage COMPLETED on a refusal made nothing, and says 0.
    """
    keys = PRODUCED_FROM.get(stage["stage"])
    if keys is None:
        return None
    artefacts = stage.get("artefacts") or {}
    if stage["stage"] == "publish" and "published" not in artefacts:
        return _legacy_publications(artefacts)
    return sum(_count(artefacts.get(key)) for key in keys)


def run_summary(stages: list[dict[str, Any]]) -> tuple[str, int]:
    """The day's headline in Romanian, and how many stages produced something.

    "COMPLETED 12/12" was the headline of a rehearsal day whose ideas were refused, whose
    research verified nothing and whose Director decided nothing. This counts the ten stages
    of work: how many ran to their end, how many made something, and names the rest.
    """
    work = [s for s in stages if s["stage"] in PRODUCED_FROM]
    ran = [s for s in work if s["status"] == COMPLETED]
    productive = [s for s in work if (s.get("produced") or 0) > 0]
    idle = [s["stage"] for s in ran if not (s.get("produced") or 0)]
    failed = [s["stage"] for s in work if s["status"] == FAILED]
    blocked = [s["stage"] for s in work if s["status"] == BLOCKED]
    made = (
        "niciuna nu a produs ceva"
        if not productive
        else f"{len(productive)} {'a' if len(productive) == 1 else 'au'} produs ceva"
    )
    parts = [
        # «etape de lucru»: the stages that make something; the page counts every stage beside
        # this sentence («12/12 etape încheiate», the preflight and the day's log included).
        f"{len(ran)} din {len(work)} etape de lucru {'a' if len(ran) == 1 else 'au'} rulat până "
        f"la capăt; {made}."
    ]
    if not productive:
        parts.append("Ziua nu a produs nimic.")
    elif idle:
        parts.append("Fără rezultat: " + stage_list(idle) + ".")
    if failed:
        parts.append(("Eșuată: " if len(failed) == 1 else "Eșuate: ") + stage_list(failed) + ".")
    if blocked:
        parts.append(
            ("Blocată: " if len(blocked) == 1 else "Blocate: ") + stage_list(blocked) + "."
        )
    published = next((s.get("produced") or 0 for s in work if s["stage"] == "publish"), 0)
    parts.append(f"Filme publicate: {published}." if published else "Niciun film publicat azi.")
    return " ".join(parts), len(productive)


def _blocked_by(name: str, lost: dict[str, dict[str, Any]]) -> str | None:
    """Why ``name`` cannot run today, or None when one of its inputs was delivered."""
    needs = STAGE_PREREQUISITES.get(name, ())
    if not needs or any(need not in lost for need in needs):
        return None
    causes: list[str] = []
    for need in needs:
        for root in lost[need]["roots"]:
            if root not in causes:
                causes.append(root)
    if len(needs) == 1:
        how = "a eșuat" if lost[needs[0]]["status"] == FAILED else "a fost blocată"
        reason = f"Nu a fost încercată: etapa de care depinde, «{stage_name(needs[0])}», {how}."
    else:
        reason = (
            "Nu a fost încercată: niciuna dintre etapele de care depinde "
            f"({stage_list(needs)}) nu a livrat."
        )
    if causes != list(needs):
        reason += " Cauza: " + stage_list(causes) + "."
    return reason


def _run_with_retries(
    engine: Engine,
    settings: Settings,
    run_id: str,
    name: str,
    runner: Callable[[], dict[str, Any]],
    wait: Callable[[float], None],
    correlation: str,
) -> tuple[dict[str, Any] | None, BaseException | None, int]:
    """Run a stage; on a transient fault, again after a wait, up to the configured tries.

    Returns (outcome, error, attempts): exactly one of outcome and error is set. The
    backoff doubles from `stage_retry_backoff_seconds` (20, 40, 80 by default), and each
    retry is announced so the ledger shows a stage waiting rather than a stage hanging.
    The Owner's stop is read before each retry: a stop during the wait ends the retries,
    and the runbook then records the stage as it would any failed one.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return runner(), None, attempts
        except Exception as exc:  # noqa: BLE001 - the stage's failure is the record
            retries_left = settings.stage_retry_attempts - (attempts - 1)
            if classify_fault(exc) != TRANSIENT or retries_left <= 0 or stop_requested(engine):
                return None, exc, attempts
            backoff = settings.stage_retry_backoff_seconds * (2 ** (attempts - 1))
            reason = (
                f"Etapa «{stage_name(name)}» a întâlnit o eroare trecătoare "
                f"({error_words(exc)}); reîncerc în {backoff} s (încercarea {attempts + 1} "
                f"din {settings.stage_retry_attempts + 1})."
            )
            logger.warning(
                "stage_retrying",
                extra={"run_id": run_id, "stage": name, "attempt": attempts, "wait": backoff},
            )
            _announce(
                engine,
                "runbook.stage_retrying",
                run_id,
                {
                    "stage": name,
                    "attempt": attempts,
                    "wait_seconds": backoff,
                    "reason": reason,
                    "error_class": type(exc).__name__,
                },
                correlation,
            )
            wait(backoff)


def _announce(
    engine: Engine,
    event_type: str,
    run_id: str,
    payload: dict[str, Any],
    correlation_id: str,
) -> None:
    """Say what the day is doing, as it does it.

    A run used to be silent until it was over: one `runbook.daily_run_finished` event after
    ten minutes of work. The Owner watching the ledger saw employees talking with no idea
    which stage they were in. These go through the outbox, so they reach the open page live.
    """
    with Session(engine) as session, session.begin():
        append_event_with_outbox(
            session, event_type, "daily_run", run_id, 1, payload, correlation_id
        )


def _open_safe_mode(session: Session, reason: str, trigger: str, run_id: str | None) -> None:
    existing = session.scalars(
        select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None))
    ).first()
    if existing is not None:
        return  # Already in safe mode; a second record would obscure when it began.
    identifier = str(uuid4())
    event = append_event(
        session,
        "runbook.safe_mode_entered",
        "safe_mode_record",
        identifier,
        1,
        {"trigger": trigger, "run_id": run_id},
        str(uuid4()),
    )
    session.add(
        SafeModeRecord(
            id=identifier,
            reason=reason[:2000],
            trigger=trigger,
            run_id=run_id,
            entered_at=utc_now(),
            cleared_at=None,
            cleared_notes=None,
            event_id=event.event_id,
        )
    )
    policy = session.get(OwnerPolicy, 1)
    if policy is not None:
        policy.autonomy_stopped = True
        policy.version += 1
        policy.updated_at = utc_now()


def safe_mode_state(engine: Engine) -> dict[str, Any]:
    with Session(engine) as session:
        current = session.scalars(
            select(SafeModeRecord)
            .where(SafeModeRecord.cleared_at.is_(None))
            .order_by(SafeModeRecord.entered_at.desc())
        ).first()
        return {
            "active": current is not None,
            "reason": current.reason if current else None,
            "trigger": current.trigger if current else None,
            "entered_at": current.entered_at if current else None,
            "record_id": current.id if current else None,
        }


def clear_safe_mode(engine: Engine, notes: str, correlation_id: str = "") -> dict[str, Any]:
    """Leave safe mode. Requires a note: a P0 is cleared by a person who looked at it.

    Autonomy is deliberately *not* restarted here. Leaving safe mode says the incident was
    examined; deciding the studio should act again is a separate choice, and folding the two
    together would let one click undo both.
    """
    if not notes.strip():
        raise RunbookError(
            "Scrie ce ai verificat înainte de a ieși din modul sigur; nota rămâne în istoric."
        )
    with Session(engine) as session, session.begin():
        current = session.scalars(
            select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None))
        ).first()
        if current is None:
            raise RunbookError("Studioul nu este în mod sigur.")
        current.cleared_at = utc_now()
        current.cleared_notes = notes.strip()[:2000]
        current.event_id = append_event(
            session,
            "runbook.safe_mode_cleared",
            "safe_mode_record",
            current.id,
            2,
            {},
            correlation_id or str(uuid4()),
        ).event_id
        return {
            "cleared": True,
            "note": (
                "Modul sigur a fost închis. Autonomia rămâne oprită — pornește-o separat, "
                "când ești sigur că studioul poate lucra din nou."
            ),
        }


def _stage(
    name: str,
    status: str,
    reason: str,
    artefacts: dict | None = None,
    *,
    fault_class: str | None = None,
    attempts: int | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """One stage's record. A stage that raised keeps the exception's class and its own text
    in ``error_class`` and ``error_detail``; its ``reason`` is the Romanian sentence the Owner
    reads (`app.wording.error_words`), never the library's text."""
    record: dict[str, Any] = {
        "stage": name,
        "status": status,
        "reason": reason,
        "artefacts": artefacts or {},
        "fault_class": fault_class,
        "at": utc_now(),
    }
    if attempts is not None:
        record["attempts"] = attempts
    if error is not None:
        record.update(error_fields(error))
    return record


def _derive_status(stages: list[dict[str, Any]]) -> str:
    """A run's status is what its stages add up to, not what the caller hoped for."""
    if any(stage["status"] == FAILED for stage in stages):
        return "FAILED"
    if any(stage["status"] == BLOCKED for stage in stages):
        return "BLOCKED"
    if any(stage["status"] == SKIPPED for stage in stages):
        return "PARTIAL"
    return "COMPLETED"


def _close_the_day(
    stages: list[dict[str, Any]],
    engine: Engine,
    settings: Settings,
    date_iso: str,
    run_id: str,
    wait: Callable[[float], None],
    correlation: str,
) -> list[dict[str, Any]]:
    """Replace the ``daily_log`` stage with the real outcome of closing the day's log.

    The close is a stage like the others: a lock on the log table is retried in place, and
    what still fails carries its class, so a hard fault here opens safe mode as a hard fault
    anywhere does. It used to be FAILED with no class at all, which neither safe mode nor
    the clock's re-attempt could see — a run that failed at its last step slipped past both.
    """
    outcome, error, attempts = _run_with_retries(
        engine,
        settings,
        run_id,
        "daily_log",
        lambda: close_daily_log(engine, settings.timezone, date_iso, correlation),
        wait,
        correlation,
    )
    if error is not None:
        closed = _stage(
            "daily_log",
            FAILED,
            sentence(error_words(error)),
            fault_class=classify_fault(error),
            attempts=attempts,
            error=error,
        )
    else:
        assert outcome is not None  # one of the two is always set
        closed = _stage(
            "daily_log",
            COMPLETED,
            f"Jurnalul zilei {outcome['business_date']} a fost închis.",
            {"log_id": outcome["id"], "total_events": outcome["total_events"]},
            attempts=attempts,
        )
    return [stage if stage["stage"] != "daily_log" else closed for stage in stages]


def _close_previous_day(
    engine: Engine,
    settings: Settings,
    run_id: str,
    wait: Callable[[float], None],
    correlation: str,
) -> dict[str, Any]:
    """Close the past days no run closed, then yesterday in full, retried like a stage; the
    log of yesterday (with the dates this call closed) or the fault.

    The missing days first (`close_missing_days`, a week back): measured on the readers' copy
    of his database on 2026-09-24, 2026-09-13..22 were never closed because only yesterday
    was, and the serial could tell nothing but a quiet yesterday.
    """

    def close_past_days() -> dict[str, Any]:
        closed = [log["business_date"] for log in close_missing_days(engine, settings, correlation)]
        return {**close_previous_day(engine, settings, correlation), "days_closed": closed}

    outcome, error, attempts = _run_with_retries(
        engine,
        settings,
        run_id,
        "previous_day_log",
        close_past_days,
        wait,
        correlation,
    )
    if error is not None:
        logger.warning(
            "previous_day_not_closed",
            extra={"run_id": run_id, "attempts": attempts, "fault_class": classify_fault(error)},
        )
        return {
            "error": f"Jurnalul zilei de ieri nu s-a închis: {error_words(error)}.",
            "fault_class": classify_fault(error),
            "attempts": attempts,
            **error_fields(error),
        }
    assert outcome is not None  # one of the two is always set
    return {
        "id": outcome["id"],
        "business_date": outcome["business_date"],
        "status": outcome["status"],
        "total_events": outcome["total_events"],
        "event_counts": outcome["event_counts"],
        "closed_at": outcome["closed_at"],
        "days_closed": outcome["days_closed"],
        "attempts": attempts,
    }


def _finished(
    engine: Engine, run_id: str, stage: str, status: str, reason: str, correlation_id: str
) -> None:
    _announce(
        engine,
        "runbook.stage_finished",
        run_id,
        {"stage": stage, "status": status, "reason": reason[:300]},
        correlation_id,
    )


def pending_daily_run(engine: Engine) -> dict[str, Any] | None:
    """The queued or running daily run, if the studio has one on its way."""
    for task in list_queue_tasks(engine, limit=50):
        if task["task_type"] == DAILY_RUN_TASK and task["status"] in PENDING_STATES:
            return task
    return None


def _is_waiting_retry(task: dict[str, Any]) -> bool:
    """A same-day re-attempt that has not started yet.

    It is not "a run in progress" to the Owner: refusing his button for the half hour a
    retry waits would hold the studio to the clock's patience instead of his. The manual
    run goes ahead; when the retry's time comes it finds the day done and skips itself.
    """
    return task["status"] == "QUEUED" and bool((task.get("payload") or {}).get("retry_of"))


def start_daily_run(
    engine: Engine, settings: Settings, command_id: str, worker_enabled: bool = True
) -> dict[str, Any]:
    """Put today's run in the queue and return — the worker does the day.

    The run itself takes minutes: agents think, a render is waited on, quality control reads
    the file. Executing it inside the Owner's request meant the browser gave up long before
    the studio did and said the connection was unavailable, while the studio went on working.
    So the button queues the work and says so; what happens next is in the ledger, stage by
    stage, and in the runs list when the day is closed.
    """
    safe = safe_mode_state(engine)
    if safe["active"]:
        raise SafeModeActive(
            f"Studioul este în mod sigur din {safe['entered_at']}: {safe['reason']} "
            "Nu pornește nicio rulare până nu închizi modul sigur."
        )
    if not worker_enabled:
        raise RunbookError(
            "Lucrătorul de fundal este oprit în configurație, deci nimeni nu ar prelua "
            "rularea. Pornește-l (worker_enabled) și încearcă din nou."
        )
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy is not None and policy.autonomy_stopped:
            raise RunbookError(
                "Autonomia este oprită: nimic nu pornește până nu o repornești de la "
                "comutatorul AUTONOMIE."
            )
    existing = pending_daily_run(engine)
    if existing is not None and not _is_waiting_retry(existing):
        raise RunbookError(
            f"O rulare zilnică este deja în lucru (pusă la coadă la {existing['created_at']}). "
            "Așteapt-o pe aceasta."
        )
    task = enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {"manual": True, "requested_at": utc_now(), "date": business_date(settings.timezone)},
        priority=10,
        max_attempts=1,
        idempotency_key=f"manual-run-{command_id}",
    )
    return {
        "status": "QUEUED",
        "task_id": task["id"],
        "queued_at": task["created_at"],
        "message": (
            "Rularea de azi a fost pornită. Prima etapă începe în câteva secunde; "
            "urmărește-o în registrul din stânga."
        ),
    }


def finish_media_setup(engine: Engine, vault: Any) -> dict[str, Any] | None:
    """Fill the empty media defaults from the account's own catalogue, if any are empty."""
    from app.integrations.autoconfig import auto_configure  # noqa: PLC0415
    from app.media.factory import media_readiness  # noqa: PLC0415

    if all(item["status"] == "READY" for item in media_readiness(engine, vault).values()):
        return None
    try:
        return auto_configure(engine, vault)
    except Exception as exc:  # noqa: BLE001 - setup that cannot finish must not stop the day
        logger.info("media_setup_not_finished", extra={"error": type(exc).__name__})
        return None


def execute_daily_run(
    engine: Engine,
    settings: Settings,
    vault: Any,
    correlation_id: str = "",
    stage_runners: dict[str, Callable[[], dict[str, Any]]] | None = None,
    attempt: int = 1,
    attempts_allowed: int = 1,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Run the day, stage by stage, and record the truth about each.

    ``stage_runners`` lets a caller supply real work for a stage. A stage with no runner is
    recorded SKIPPED with the reason — it is not silently omitted, because a run that lists ten
    stages and performed three has told the Owner something false by arrangement of the page.

    A stage that raises is classified (`classify_fault`). A transient fault is retried in
    place, ``settings.stage_retry_attempts`` times with exponential backoff, and only then
    fails the stage. A failed stage BLOCKS the stages that take their input from it
    (`STAGE_PREREQUISITES`) and no others: the rest of the day still runs. Safe mode opens
    only for a P0 (`SAFE_MODE_STAGES`); the day is re-attempted only when a transient fault
    cost its films (`PRODUCTION_STAGES`). Between stages the Owner's stop is read again: a
    day already running stops where it is, the rest BLOCKED whatever the table says, with no
    safe mode and no letter — the Owner did it.

    ``attempt`` of ``attempts_allowed`` is where this run stands in the day's re-attempts.
    The Director's letter about a stopped day goes to the Owner only when no further attempt
    will follow: after the last one, or after a fault a re-attempt could not change.
    ``sleep`` is the backoff clock, injectable so a test does not wait a minute.
    """
    correlation = correlation_id or str(uuid4())
    runners = stage_runners or {}
    wait = sleep or time.sleep

    safe = safe_mode_state(engine)
    if safe["active"]:
        raise SafeModeActive(
            f"Studioul este în mod sigur din {safe['entered_at']}: {safe['reason']} "
            "Nu pornește nicio rulare până nu închizi modul sigur."
        )

    # A verified connection with no default model or voice is the studio's own unfinished
    # setup, not a fact about the world: the catalogue already says what the account can
    # do. The day fills what is empty before it judges itself, so an Owner who connected a
    # voice and an image service gets narration and stills, not a DEGRADED preflight about
    # a form in Settings.
    finish_media_setup(engine, vault)
    preflight = run_preflight(engine, settings, vault)
    date_iso = business_date(settings.timezone)
    run_id = str(uuid4())
    started_at = utc_now()
    stages: list[dict[str, Any]] = [
        _stage(
            "preflight",
            COMPLETED if preflight["status"] != "BLOCKED" else BLOCKED,
            preflight["summary"],
            {
                "status": preflight["status"],
                "failures": preflight["blocking_failures"],
                # Which stages this day was even allowed to attempt. Read back a week later,
                # a day of skipped stages says whether the studio lacked something or the
                # Owner had it on a shorter leash.
                "autonomy_mode": preflight["autonomy_mode"],
            },
        )
    ]

    stopped_at: str | None = None
    stop_reason: str | None = None
    fault_class: str | None = None
    owner_stopped = False
    # What the day lost, stage by stage: a stage that FAILED or BLOCKED itself is its own
    # root; a stage blocked by `STAGE_PREREQUISITES` carries the roots it inherited. The
    # Owner's stop is not in here — it is not a loss, it is his decision.
    lost: dict[str, dict[str, Any]] = {}
    # The stages that broke by themselves, in order, with what the run needs to say of them.
    broken: list[str] = []
    faults: dict[str, str | None] = {}
    reasons: dict[str, str] = {}
    errors: dict[str, BaseException] = {}

    def breaks(name: str, status: str, reason: str, fault: str | None) -> None:
        broken.append(name)
        faults[name] = fault
        reasons[name] = reason
        lost[name] = {"status": status, "roots": [name]}

    _announce(
        engine,
        "runbook.daily_run_started",
        run_id,
        {
            "date": date_iso,
            "preflight": preflight["status"],
            "autonomy_mode": preflight["autonomy_mode"],
            "stages": len(STAGES),
            "attempt": attempt,
            "attempts_allowed": attempts_allowed,
        },
        correlation,
    )

    def run_stage(name: str) -> None:
        """Run one stage, or record why it did not run: the Owner's stop first, then the
        dependency table, then the runner with its retries. Called for the stages before
        the day's log is closed and, after the close, for those that read it."""
        nonlocal owner_stopped, stopped_at, stop_reason
        if owner_stopped:
            stages.append(_stage(name, BLOCKED, OWNER_STOP_REASON))
            return
        # The switch is read again before every stage. It used to be read once, at the
        # gate: an Owner who pressed STOP at stage three watched the studio spend the
        # remaining nine anyway. It outranks the dependency table: a stage after his
        # stop is his, whatever else happened before it.
        if stop_requested(engine):
            owner_stopped = True
            stopped_at = name
            stop_reason = OWNER_STOP_REASON
            stages.append(_stage(name, BLOCKED, OWNER_STOP_REASON))
            _finished(engine, run_id, name, BLOCKED, OWNER_STOP_REASON, correlation)
            return
        # A failure costs the stages that take their input from it, and no others. This
        # used to be "any failure blocks everything after it": a refused statistics token
        # at performance intake left the day with nothing filmed (rehearsal, 2026-09-18).
        waiting = _blocked_by(name, lost)
        if waiting is not None:
            needs = STAGE_PREREQUISITES[name]
            roots: list[str] = []
            for need in needs:
                roots.extend(r for r in lost[need]["roots"] if r not in roots)
            lost[name] = {"status": BLOCKED, "roots": roots}
            stages.append(_stage(name, BLOCKED, waiting))
            _finished(engine, run_id, name, BLOCKED, waiting, correlation)
            return
        runner = runners.get(name)
        _announce(
            engine,
            "runbook.stage_started",
            run_id,
            {"stage": name, "index": STAGES.index(name) + 1, "total": len(STAGES)},
            correlation,
        )
        if runner is None:
            reason = "Nicio implementare conectată pentru această etapă în această rulare."
            stages.append(_stage(name, SKIPPED, reason))
            _finished(engine, run_id, name, SKIPPED, reason, correlation)
            return
        outcome, error, attempts = _run_with_retries(
            engine, settings, run_id, name, runner, wait, correlation
        )
        if error is not None:
            reason = sentence(error_words(error))
            if stop_requested(engine):
                # A runner that polls `stop_requested` may raise to get out; a runner
                # that does not may have been failed by the stop itself (a connection
                # closed under it). Either way the Owner ended the day: BLOCKED, with
                # what the stage said kept in the record, and no fault.
                owner_stopped = True
                stopped_at = name
                stop_reason = OWNER_STOP_REASON
                stages.append(
                    _stage(
                        name,
                        BLOCKED,
                        f"{OWNER_STOP_REASON} ({error_words(error)})",
                        attempts=attempts,
                        error=error,
                    )
                )
                _finished(engine, run_id, name, BLOCKED, OWNER_STOP_REASON, correlation)
                return
            stage_fault: str | None = classify_fault(error)
            stages.append(
                _stage(
                    name, FAILED, reason, fault_class=stage_fault, attempts=attempts, error=error
                )
            )
            _finished(engine, run_id, name, FAILED, reason, correlation)
            errors[name] = error
            breaks(
                name,
                FAILED,
                (
                    f"Etapa «{stage_name(name)}» a eșuat după "
                    f"{count(attempts, 'încercare', 'încercări')}, pe o eroare trecătoare: "
                    f"{error_words(error)}"
                    if stage_fault == TRANSIENT
                    else f"Etapa «{stage_name(name)}» a eșuat: {error_words(error)}"
                ),
                stage_fault,
            )
            return
        assert outcome is not None  # one of the two is always set
        status = str(outcome.get("status", COMPLETED))
        stage_fault = None
        if status == FAILED:
            # A runner that reports its own failure says which kind, or it is hard: a
            # stage that knows the fault is passing has to say so to be retried.
            stage_fault = str(outcome.get("fault_class") or HARD)
        stages.append(
            _stage(
                name,
                status,
                str(outcome.get("reason", "")),
                outcome.get("artefacts"),
                fault_class=stage_fault,
                attempts=attempts,
            )
        )
        _finished(engine, run_id, name, status, str(outcome.get("reason", "")), correlation)
        if status == BLOCKED and stop_requested(engine):
            # The stage stopped itself because the Owner asked (the media loop between
            # scenes): his decision, not a gate refusing.
            owner_stopped = True
            stopped_at = name
            stop_reason = str(outcome.get("reason", "")) or OWNER_STOP_REASON
        elif status in (BLOCKED, FAILED):
            breaks(
                name,
                status,
                str(outcome.get("reason", "")) or f"Etapa «{stage_name(name)}» s-a oprit.",
                stage_fault,
            )

    if preflight["status"] == "BLOCKED":
        stopped_at = "preflight"
        stop_reason = preflight["summary"]
        for name in STAGES[1:]:
            stages.append(
                _stage(
                    name,
                    BLOCKED,
                    "Verificarea preliminară a oprit ziua; etapa nu a fost încercată.",
                )
            )
    else:
        # Yesterday is closed first, with every event of its date. Measured live: the day's
        # log was frozen at the run's own hour (the morning of its date, 92 events, one of
        # them narratable), because the only close was the one at the end of this run. The
        # previous business date is over now, which is the one moment a full day can be
        # counted, and the serial stage below reads that log. A date already closed is
        # returned as it is — a closed log never changes. Today's close at the end of the
        # run is kept, so the day the run completes is still frozen at the run's hour; a
        # full-day log for every date needs that close moved, which is recorded as open.
        # A fault here is retried like a stage's and then recorded on the preflight line
        # rather than ending the day: yesterday's record is not today's work, and the
        # serial stage simply finds no closed day to tell.
        stages[0]["artefacts"]["previous_day_log"] = _close_previous_day(
            engine, settings, run_id, wait, correlation
        )
        for name in STAGES[1 : STAGES.index("daily_log") + 1]:
            run_stage(name)

    # The day is closed from the event stream whenever the studio actually worked: a partial day
    # is still a day, and the log is what tomorrow's episode is checked against. A blocked
    # preflight is not a partial day — the studio did nothing, so there is nothing to close, and
    # writing a log for it would put an entry in the record for work that never happened. The
    # stage keeps the BLOCKED it was given. A day the Owner stopped before any stage ran is the
    # same: nothing happened, nothing to close.
    worked = any(s["status"] == COMPLETED for s in stages[1:])
    if preflight["status"] != "BLOCKED" and (worked or not owner_stopped):
        stages = _close_the_day(stages, engine, settings, date_iso, run_id, wait, correlation)
        closing = next(s for s in stages if s["stage"] == "daily_log")
        if closing["status"] == FAILED:
            # The day's own record: a fault here is the run's, whatever else went well.
            breaks(
                "daily_log",
                FAILED,
                f"Etapa «{stage_name('daily_log')}» a eșuat: {clause(closing['reason'])}",
                closing["fault_class"],
            )
    if preflight["status"] != "BLOCKED":
        # Tomorrow's script is written from the log just closed, under the same rules as
        # every other stage: the Owner's stop, the dependency table (a failed close blocks
        # it) and the retries. A blocked preflight has already recorded it BLOCKED.
        for name in AFTER_THE_CLOSE:
            run_stage(name)
        worked = any(s["status"] == COMPLETED for s in stages[1:])

    for stage in stages:
        stage["produced"] = produced_by(stage)
    summary, productive = run_summary(stages)

    # Which of the day's losses cost a film. A stage the films pass through that failed or
    # was blocked by what it waited for; its roots are the faults the Owner has to hear about
    # first, and the ones a re-attempt would have to change.
    lost_production = [name for name in PRODUCTION_STAGES if name in lost]
    production_roots: list[str] = []
    for name in lost_production:
        production_roots.extend(r for r in lost[name]["roots"] if r not in production_roots)
    production_lost = preflight["status"] == "BLOCKED" or bool(lost_production)
    # The record keeps the first fault that cost a film, else the first fault of the day.
    # The fault class is the worst of those it names: HARD if any of them is, because a
    # re-attempt would meet a hard fault again.
    named = [r for r in STAGES if r in production_roots] or broken
    if named and not owner_stopped and preflight["status"] != "BLOCKED":
        stopped_at = named[0]
        stop_reason = reasons[named[0]]
    classes = {faults[name] for name in named if faults.get(name)}
    fault_class = HARD if HARD in classes else TRANSIENT if classes else None

    if owner_stopped:
        # Not FAILED, whatever the stages say: the Owner ended the day, nothing broke. PARTIAL
        # if the studio did some of it, BLOCKED if it did none.
        status = "PARTIAL" if worked else "BLOCKED"
    else:
        status = _derive_status(stages)
        if status in ("FAILED", "BLOCKED") and not production_lost and "daily_log" not in broken:
            # A stage the films do not need broke, and the films went through: the studio did
            # part of its day, which is PARTIAL — the state the clock reads as "this day ran".
            status = "PARTIAL"
    if not broken:
        fault_class = None
    finished_at = utc_now()
    retryable = retryable_outcome(
        status, preflight["status"], fault_class, production_lost=production_lost
    )
    another_attempt = retryable and attempt < attempts_allowed
    # A HARD fault where `SAFE_MODE_STAGES` puts a P0, or an integrity error anywhere.
    p0 = next(
        (
            name
            for name in broken
            if faults.get(name) == HARD
            and (name in SAFE_MODE_STAGES or _doubts_the_record(errors.get(name)))
        ),
        None,
    )
    if stopped_at is not None and not owner_stopped and not another_attempt:
        # A day that stopped is the Owner's to unblock: the Director says where and why —
        # once, after the day's last attempt, not after each of them.
        from app.agents.director import letter_to_owner  # noqa: PLC0415

        tried = f" Am încercat de {attempt} ori azi." if attempts_allowed > 1 and retryable else ""
        caused = [
            s["stage"]
            for s in stages
            if s["stage"] in lost and s["stage"] not in broken and s["stage"] != "preflight"
        ]
        if stopped_at == "preflight":
            consequence = " Etapele de după ea nu au rulat."
        elif caused:
            consequence = " Din cauza ei nu au rulat: " + stage_list(caused) + "."
        else:
            consequence = ""
        others = [name for name in broken if name != stopped_at]
        if others:
            consequence += (
                (" A mai eșuat: " if len(others) == 1 else " Au mai eșuat: ")
                + stage_list(others)
                + "."
            )
        if p0 is not None:
            consequence += " Studioul a intrat în modul sigur până verifici."
        if production_lost:
            subject = f"Ziua s-a oprit la etapa «{stage_name(stopped_at)}»"
            body = (
                f"Rularea din {date_iso} s-a oprit la etapa «{stage_name(stopped_at)}»: "
                f"{clause(stop_reason or '')}."
                f"{consequence}{tried} Spune-mi ce ai reparat și pornesc din nou. — Sarah"
            )
        else:
            # Not "the day stopped": it did not, and a letter that says so is the rehearsal's
            # headline over again. Nor is the day tried again — that would buy a second film.
            subject = f"Etapa «{stage_name(stopped_at)}» a eșuat; filmele zilei nu depind de ea"
            body = (
                f"Rularea din {date_iso}: {clause(stop_reason or '')}.{consequence} Filmele zilei "
                "nu depind "
                "de ea, așa că restul zilei a rulat și nu o reiau azi. Spune-mi ce ai reparat. "
                "— Sarah"
            )
        letter_to_owner(engine, subject, body, correlation)

    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "runbook.daily_run_finished",
            "daily_run",
            run_id,
            1,
            {
                "status": status,
                "preflight": preflight["status"],
                "fault_class": fault_class,
                "attempt": attempt,
                "owner_stopped": owner_stopped,
                "summary": summary,
                "stages_productive": productive,
                "production_lost": production_lost,
                "retryable": retryable,
            },
            correlation,
        )
        session.add(
            DailyRun(
                id=run_id,
                business_date=date_iso,
                preflight_status=preflight["status"],
                preflight_json=preflight,
                status=status,
                stages_json=stages,
                stages_total=len(stages),
                stages_completed=sum(1 for s in stages if s["status"] == COMPLETED),
                stopped_at_stage=stopped_at,
                stop_reason=stop_reason,
                fault_class=fault_class,
                started_at=started_at,
                finished_at=finished_at,
                event_id=event.event_id,
            )
        )
        # A P0 for an unattended studio stops rather than carrying on to the next day's run
        # with an unexamined fault behind it (`SAFE_MODE_STAGES` says which, and why). A
        # transient fault never is: measured on the live copy, one "database is locked"
        # opened safe mode and set the autonomy stop, and the studio stood still for days
        # over a lock that was free a second later. Nor is a hard fault in a stage that
        # neither spends, nor publishes, nor keeps the record — it costs that stage, and the
        # letter above is how the Owner hears of it.
        if p0 is not None and not owner_stopped:
            _open_safe_mode(
                session,
                reasons.get(p0) or "O etapă a rulării zilnice a eșuat.",
                "STAGE_FAILURE",
                run_id,
            )

    return {
        "id": run_id,
        "business_date": date_iso,
        "preflight": preflight,
        "status": status,
        "stages": stages,
        "stages_total": len(stages),
        "stages_completed": sum(1 for s in stages if s["status"] == COMPLETED),
        "stages_productive": productive,
        "summary": summary,
        "summary_code": SUMMARY_COUNTED,
        "stopped_at_stage": stopped_at,
        "stop_reason": stop_reason,
        "fault_class": fault_class,
        "owner_stopped": owner_stopped,
        "production_lost": production_lost,
        "attempt": attempt,
        "retryable": retryable,
        "started_at": started_at,
        "finished_at": finished_at,
        "safe_mode": safe_mode_state(engine),
    }


#: How a stored run's headline was read: from the counts it was run with, or — a run stored
#: before the counts existed — from what its record holds, and said so.
SUMMARY_COUNTED = "counted"
SUMMARY_BEFORE_COUNTS = "before_counts"


def _before_counts_summary(stages: list[dict[str, Any]]) -> str:
    """The headline of a run stored before counts existed, from what its record does hold.

    Measured on a copy of the Owner's studio (2026-09-25): all 18 stored runs are of 12.09 and
    none carries ``produced``. They were recounted from today's artefact keys, which they never
    wrote — their media stage returned ``rendered``, not ``assets`` — so the headline called
    idle a stage that rendered, and empty a day the page's own rows called «nenumărat». What an
    old record holds truthfully is each stage's status and the film its publish artefact names
    by id (`_legacy_publications`); nothing else is said, and «azi» is not: it is not the day
    it is read on.
    """
    work = [s for s in stages if s["stage"] in PRODUCED_FROM]
    ran = [s for s in work if s["status"] == COMPLETED]
    failed = [s["stage"] for s in work if s["status"] == FAILED]
    blocked = [s["stage"] for s in work if s["status"] == BLOCKED]
    parts = [
        f"Rulare dinainte de numărătoare: {len(ran)} din {len(work)} etape de lucru "
        f"{'a' if len(ran) == 1 else 'au'} rulat până la capăt; ce a produs fiecare etapă nu "
        "s-a numărat atunci."
    ]
    if failed:
        parts.append(("Eșuată: " if len(failed) == 1 else "Eșuate: ") + stage_list(failed) + ".")
    if blocked:
        parts.append(
            ("Blocată: " if len(blocked) == 1 else "Blocate: ") + stage_list(blocked) + "."
        )
    published = sum(produced_by(s) or 0 for s in work if s["stage"] == "publish")
    if published:
        parts.append(f"Filme publicate: {published}.")
    return " ".join(parts)


def stored_summary(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline of a stored run, and how it was read.

    ``counted`` when every stage carries the count it was run with (`execute_daily_run`
    writes ``produced`` on each, None for the two it does not count): the headline is the one
    the run wrote, read back. ``before_counts`` otherwise: the headline opens with «Rulare
    dinainte de numărătoare» and ``stages_productive`` is None — never 0, which would call a
    day empty that nobody counted. Half a count is no count: one stage without it and the rest
    would be called idle beside it.
    """
    if all("produced" in stage for stage in stages):
        summary, productive = run_summary(stages)
        return {
            "summary": summary,
            "stages_productive": productive,
            "summary_code": SUMMARY_COUNTED,
        }
    return {
        "summary": _before_counts_summary(stages),
        "stages_productive": None,
        "summary_code": SUMMARY_BEFORE_COUNTS,
    }


def list_runs(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    with Session(engine) as session:
        runs = []
        for run in session.scalars(
            select(DailyRun).order_by(DailyRun.started_at.desc()).limit(limit)
        ):
            stages = list(run.stages_json or [])
            told = stored_summary(stages)
            runs.append(
                {
                    "id": run.id,
                    "business_date": run.business_date,
                    "preflight_status": run.preflight_status,
                    "status": run.status,
                    "stages_total": run.stages_total,
                    "stages_completed": run.stages_completed,
                    "stages_productive": told["stages_productive"],
                    "summary": told["summary"],
                    "summary_code": told["summary_code"],
                    "stopped_at_stage": run.stopped_at_stage,
                    "stop_reason": run.stop_reason,
                    "fault_class": run.fault_class,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "stages": stages,
                }
            )
        return runs
