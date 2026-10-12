"""The GPU session of one paid step: the RunPod Serverless GPU on for the step, off right after.

The Owner, 2026-10-08: «trebuie sa se opreasca imediat dupa, nu la 30 sec. Sunt taxat la
secunda, deci trebuie oprit imediat dupa generare». A paid step (stills, the hero test shot, the
motion, a one-scene redo) that runs on RunPod Serverless:

1. opens a session: the Policy Kernel's ``infra.gpu_on`` (only inside an already approved paid
   step, under its cap, never asking him and never spending a yes), the one-GPU rule (a session
   on another endpoint waits, then GPU_BUSY), then ``PATCH workers {min 0, max 1, idleTimeout
   1}`` whose answer is checked. A failure before anything was sent refuses the step with
   COMPUTE_NOT_READY: nothing sent, nothing spent, the journal keys stay reusable. While a
   session on the endpoint whose /run was booked as never queued closed less than the longest
   job ttl ago (`booked_unsent_sessions`), the queue is purged before that PATCH: a job RunPod
   queued late never runs on the new GPU;
2. sends its rounds (the step's own code, `app.media.gpu_batch`), renewing the session;
3. closes it in ``finally``: purge the queue, cancel what is left, ``PATCH workers {0, 0, 1}``,
   verify OFF (max 0, running 0, inProgress 0, inQueue 0; ``idle`` only logged). A close that
   cannot verify never breaks the step: it is recorded, told to the Owner once, and the guard
   (`gpu_guard`) tries again every minute. When a /run of the session failed with no job id
   (2026-10-09), the close first reads the queue (GET /health, one short try that never holds
   back the off) and keeps RunPod's own purge count: the evidence, with the off reading, on
   the session row (``off_reading.evidence``) and on the session (``off_evidence``), for
   `batch.BatchRun.prove_unsent`.

Switching OFF is always allowed (``infra.gpu_off``, T0), under STOP AUTONOMIE too: `force_off`
never consults the kernel. «Oprirea GPU-ului nu este o acțiune autonomă: nu cheltuie, doar
oprește cheltuiala» (ADR, amendment of 51). RunPod's facts are cited in `endpoint`.

Sync API: the stages run in worker threads, so each network sequence runs in ``asyncio.run``.
One `threading.Lock` per endpoint is held across each open/close sequence, so an open never
races a close's purge and max=0.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Engine,
    Index,
    Integer,
    String,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import lock_for_write
from app.models import Base
from app.providers.media_http import MediaProviderError
from app.providers.runpod import weights
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.endpoint import (
    EndpointControl,
    EndpointHealth,
    EndpointSettings,
    OffReading,
    is_off,
    still_on_words,
    utc_now,
)

if TYPE_CHECKING:
    from app.integrations.vault import CredentialVault
    from app.media.mode_guard import PurchaseGuard
    from app.providers.runpod.client import Transport

logger = logging.getLogger("studio.runpod")

#: This process: a session opened by another process (one that crashed) is an orphan.
PROCESS_TOKEN = str(uuid4())

OPENING, OPEN, CLOSING, CLOSED = "OPENING", "OPEN", "CLOSING", "CLOSED"
FAILED_OPEN, FORCED_OFF = "FAILED_OPEN", "FORCED_OFF"
LIVE = (OPENING, OPEN)
SESSION_STATUSES = (OPENING, OPEN, CLOSING, CLOSED, FAILED_OPEN, FORCED_OFF)
CLOSE_REASONS = (
    "STEP_DONE",
    "STEP_FAILED",
    "OWNER_OFF",
    "GUARD_ORPHAN",
    "GUARD_STALE",
    "GUARD_TTL",
    "BOOT",
    "SHUTDOWN",
    "LAUNCHER_STOP",
    "OPEN_FAILED",
)
#: The journal's statuses after which a RunPod job needs no cancel.
TERMINAL_JOB_STATUSES = ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT")
#: How often a step waiting for the one GPU looks again.
BUSY_POLL_SECONDS = 5.0
#: One live read per endpoint per this many seconds for the page.
FRESH_READ_SECONDS = 10.0
#: The window-close path: each request at most this long, no retry.
FAST_REQUEST_SECONDS = 2.0
#: The queue read a close makes BEFORE its purge when a /run had no job id (2026-10-09): one
#: try, this long at most, no retry. It sits ahead of the purge and the max=0, which must not
#: wait on it (the Owner: the GPU off right after); a read that fails or is slow is recorded
#: unread, which only makes the proof fail (the safe side), never the off.
EVIDENCE_READ_SECONDS = 5.0

OFF_UNVERIFIED_LETTER = (
    "Am trimis oprirea GPU-ului RunPod, dar nu a confirmat că s-a oprit; verific din nou la "
    "fiecare minut."
)
FORCED_OFF_WORDS = (
    "GPU-ul a fost oprit în timpul pasului: ce s-a cumpărat rămâne; restul nu s-a cumpărat."
)
NOT_IN_STEP_WORDS = "GPU-ul se pornește doar în interiorul unui pas plătit aprobat."


class GpuSessionRow(Base):
    __tablename__ = "gpu_session"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPENING','OPEN','CLOSING','CLOSED','FAILED_OPEN','FORCED_OFF')",
            name="ck_gpu_session_status",
        ),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('STEP_DONE','STEP_FAILED','OWNER_OFF',"
            "'GUARD_ORPHAN','GUARD_STALE','GUARD_TTL','BOOT','SHUTDOWN','LAUNCHER_STOP',"
            "'OPEN_FAILED')",
            name="ck_gpu_session_close_reason",
        ),
        CheckConstraint("purpose IN ('image','video')", name="ck_gpu_session_purpose"),
        Index("ix_gpu_session_endpoint_status", "endpoint_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    integration_id: Mapped[str] = mapped_column(String(36), nullable=False)
    endpoint_id: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(10), nullable=False)
    step: Mapped[str] = mapped_column(String(30), nullable=False)
    storyboard_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    process_token: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    workers_max: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[str] = mapped_column(String(40), nullable=False)
    renewed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False)
    closed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verified_off: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    off_reading: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    remote_job_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class GpuSessionRefused(MediaProviderError):
    """The GPU was not switched on; nothing was sent and nothing spent."""

    def __init__(self, code: str, reason_ro: str) -> None:
        super().__init__(reason_ro, code=code, unsent=True)
        self.reason_ro = reason_ro


class GpuForcedOff(MediaProviderError):
    """The session was switched off from outside (the Owner's button, the guard, a shutdown)."""

    def __init__(self, reason_ro: str = FORCED_OFF_WORDS) -> None:
        super().__init__(reason_ro, code="GPU_FORCED_OFF")
        self.reason_ro = reason_ro


@dataclass(frozen=True)
class StepPermit:
    """What the paid step is: the kernel's ``infra.gpu_on`` reads it, never more.
    ``cost_usd`` (an addition to the shared interface, default None) is the step's cap, the
    cost the step itself was allowed with, so the kernel's inner question is the same one."""

    action: str
    step: str
    storyboard_id: str
    plan_hash: str
    requester: str
    approval_id: str | None
    owner_press: bool
    correlation_id: str
    integration_id: str | None
    cost_usd: float | None = None

    def context(self) -> dict[str, Any]:
        return {
            "step_action": self.action,
            "plan_hash": self.plan_hash,
            "approval_id": self.approval_id,
            "owner_press": self.owner_press,
            "integration_id": self.integration_id,
        }

    @classmethod
    def from_guard(
        cls,
        guard: PurchaseGuard | None,
        verdict: Mapping[str, Any],
        *,
        action: str,
        step: str,
        storyboard_id: str,
        plan_hash: str,
        requester: str,
        correlation_id: str,
        integration_id: str | None,
        unasked: bool,
    ) -> StepPermit:
        owner_press = (not guard.unasked) if guard is not None else not unasked
        return cls(
            action=action,
            step=step,
            storyboard_id=storyboard_id,
            plan_hash=plan_hash,
            requester=requester,
            approval_id=verdict.get("approval_id"),
            owner_press=owner_press,
            correlation_id=correlation_id,
            integration_id=integration_id,
            cost_usd=guard.cost_usd if guard is not None else None,
        )


@dataclass
class GpuSession:
    engine: Engine
    id: str
    endpoint_id: str
    purpose: str
    workers_max: int
    mock: bool
    config: RunPodConfig
    integration_id: str | None
    correlation_id: str
    transport: Any = None
    closed: bool = field(default=False)
    #: The idempotency keys of items whose /run failed without a job id and was not proven
    #: unsent (`batch`, 2026-10-09): the close then reads the queue BEFORE its purge and keeps
    #: RunPod's own purge count, the evidence `batch.BatchRun.prove_unsent` reads.
    uncertain_keys: list[str] = field(default_factory=list)
    #: What the close read for those items (None when there were none, or the close failed).
    off_evidence: dict[str, Any] | None = None

    def note_uncertain(self, keys: Sequence[str]) -> None:
        """A /run of this session got no job id and no proof that nothing left: its close
        collects the queue evidence (`close_session`)."""
        for key in keys:
            if key not in self.uncertain_keys:
                self.uncertain_keys.append(str(key))

    def _status(self) -> str | None:
        with Session(self.engine) as session:
            row = session.get(GpuSessionRow, self.id)
            return row.status if row is not None else None

    def check(self) -> None:
        """Raise `GpuForcedOff` when the session was switched off from outside."""
        if self._status() != OPEN:
            raise GpuForcedOff()

    def renew(self) -> None:
        """The step is alive: renewed_at = now. Raises `GpuForcedOff` like `check`."""
        with Session(self.engine) as session, session.begin():
            lock_for_write(session)
            row = session.get(GpuSessionRow, self.id)
            if row is None or row.status != OPEN:
                raise GpuForcedOff()
            row.renewed_at = utc_now()

    def note_job(self, remote_job_id: str, *, session: Session | None = None) -> None:
        """Remember a RunPod job this session sent, so its close can cancel it. Pass the
        caller's ``session`` to write it in the same transaction that saves the batch id."""

        def write(s: Session) -> None:
            row = s.get(GpuSessionRow, self.id)
            if row is None:
                return
            known = list(row.remote_job_ids or [])
            if remote_job_id not in known:
                row.remote_job_ids = [*known, remote_job_id]

        if session is not None:
            write(session)
            return
        with Session(self.engine) as own, own.begin():
            lock_for_write(own)
            write(own)


# ------------------------------------------------------------------------------- the locks

_LOCKS_GUARD = threading.Lock()
_ENDPOINT_LOCKS: dict[str, threading.Lock] = {}
#: Held while the one-GPU rule is checked and a session row inserted.
_GPU_RULE_LOCK = threading.Lock()


def endpoint_lock(endpoint_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _ENDPOINT_LOCKS.get(endpoint_id)
        if lock is None:
            lock = _ENDPOINT_LOCKS[endpoint_id] = threading.Lock()
        return lock


# ------------------------------------------------------------------------- readings cache

_READINGS_GUARD = threading.Lock()
#: endpoint_id -> {"settings", "health", "problem", "read_at", "monotonic"}
_READINGS: dict[str, dict[str, Any]] = {}


def remember_reading(
    endpoint_id: str,
    settings: EndpointSettings | None,
    health: EndpointHealth | None,
    problem: str | None = None,
) -> None:
    with _READINGS_GUARD:
        _READINGS[endpoint_id] = {
            "settings": settings,
            "health": health,
            "problem": problem,
            "read_at": utc_now(),
            "monotonic": time.monotonic(),
        }


def last_reading(endpoint_id: str) -> dict[str, Any] | None:
    with _READINGS_GUARD:
        reading = _READINGS.get(endpoint_id)
        return dict(reading) if reading is not None else None


def forget_readings() -> None:
    with _READINGS_GUARD:
        _READINGS.clear()


# ------------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _event(
    session: Session, kind: str, aggregate_id: str, payload: dict[str, Any], correlation: str
) -> None:
    from app.services import append_event  # noqa: PLC0415 - services imports providers

    append_event(session, kind, "gpu_session", aggregate_id[:36], 1, payload, correlation[:100])


def _write_event(
    engine: Engine, kind: str, aggregate_id: str, payload: dict[str, Any], correlation: str
) -> None:
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            _event(session, kind, aggregate_id, payload, correlation)
    except Exception as exc:  # noqa: BLE001 - an event never breaks the off
        logger.warning(
            "runpod_event_not_written", extra={"kind": kind, "error": type(exc).__name__}
        )


def owner_letter(engine: Engine, subject: str, text_ro: str, kind: str, correlation: str) -> None:
    """One letter to the Owner (an open letter with the same subject is that letter)."""
    from app.agents.messages import post_message  # noqa: PLC0415

    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            post_message(
                session,
                intent="ESCALATE",
                subject=subject,
                body={"kind": kind},
                body_text=text_ro,
                to_owner=True,
                correlation_id=correlation,
            )
    except Exception as exc:  # noqa: BLE001 - a letter never breaks the off
        logger.warning(
            "runpod_letter_not_written", extra={"kind": kind, "error": type(exc).__name__}
        )


def _moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def overlapping_sessions(
    session: Session,
    endpoint_id: str,
    own: str,
    opened_at: str | None,
    closed_at: str | None = None,
) -> list[str]:
    """The other sessions that had this endpoint switched on (or could have sent to it) while
    ``own`` was open: their jobs would be in the same queue counts and the same purge. A
    session refused at its open (FAILED_OPEN) sent nothing and is not one of them."""
    start = _moment(opened_at)
    end = _moment(closed_at) or _now()
    found: list[str] = []
    for row in session.scalars(
        select(GpuSessionRow).where(
            GpuSessionRow.endpoint_id == endpoint_id, GpuSessionRow.id != own
        )
    ):
        if row.status == FAILED_OPEN:
            continue
        other_start = _moment(row.opened_at)
        other_end = _moment(row.closed_at) if row.closed_at else None
        if other_start is None or start is None:
            found.append(row.id)  # unreadable times: counted, never assumed apart
            continue
        if other_start <= end and (other_end is None or other_end >= start):
            found.append(row.id)
    return found


def longest_job_ttl_seconds(config: RunPodConfig) -> int:
    """How long a job RunPod queued may still wait to run: the longest round's ttl (its
    execution cap, the queue wait and, under the cached-model source, the unbilled cache wait;
    `batch.chunk_policy`)."""
    cache = (
        int(config.model_cache_wait_seconds)
        if config.model_source == "cache" and not config.mock
        else 0
    )
    return int(config.execution_timeout_cap_seconds) + int(config.queue_wait_seconds) + cache


def booked_unsent_sessions(
    session: Session, endpoint_id: str, own: str | None, config: RunPodConfig
) -> list[str]:
    """The sessions on this endpoint, closed within the longest job ttl, whose /run with no job
    id was then booked as never queued (rows FAILED/UNSENT with ``not_queued``: the GPU-off's
    proof, `batch.BatchRun.mark_unsent`, or the Owner's release, `media.runpod_unsent`).

    The proof is one reading at the close. A /run that RunPod answered late (a 502/504, the
    client's deadline) could still be queued AFTER that reading, wait at max=0, and run at the
    next switch-on, billed and booked nowhere (2026-10-09 review). The next switch-on purges
    the queue first while such a session is that recent (`open_session`)."""
    from app.providers.runpod.jobs import GenerationJob  # noqa: PLC0415 - jobs is a leaf

    cutoff = _now() - timedelta(seconds=longest_job_ttl_seconds(config))
    named: set[str] = set()
    for row in session.scalars(
        select(GenerationJob).where(
            GenerationJob.status == "FAILED",
            GenerationJob.error_code == "UNSENT",
            GenerationJob.finished_at >= cutoff.isoformat(),
        )
    ):
        mark = (row.output or {}).get("not_queued")
        if not isinstance(mark, dict):
            continue
        for identifier in (mark.get("gpu_session_id"), row.gpu_session_id):
            if identifier:
                named.add(str(identifier))
    found: list[str] = []
    if not named:
        return found
    for gpu in session.scalars(
        select(GpuSessionRow).where(
            GpuSessionRow.id.in_(sorted(named)), GpuSessionRow.endpoint_id == endpoint_id
        )
    ):
        if gpu.id == own:
            continue
        closed = _moment(gpu.closed_at)
        if closed is None or closed >= cutoff:
            found.append(gpu.id)
    return found


async def _switch_on(control: EndpointControl, maximum: int, *, purge: bool) -> int | None:
    """PATCH workers.max to the one GPU; with ``purge`` the queue is purged first (a late job
    of a /run booked as never queued must not run on this GPU). RunPod's purge count is
    returned (None when not purged, or the answer had none)."""
    removed: int | None = None
    if purge:
        await control.purge_queue()
        removed = control.last_purge_removed
    await control.set_workers(maximum)
    return removed


def _other_live(session: Session, endpoint_id: str, own: str | None) -> list[GpuSessionRow]:
    query = select(GpuSessionRow).where(
        GpuSessionRow.endpoint_id == endpoint_id, GpuSessionRow.status.in_(LIVE)
    )
    return [row for row in session.scalars(query) if row.id != own]


def _unfinished(session: Session, job: str) -> bool:
    """A RunPod job whose journal rows are not all terminal (or that the journal does not know)."""
    statuses = [
        str(value)
        for value in session.execute(
            text("SELECT status FROM cloud_generation_job WHERE batch_remote_id = :job"),
            {"job": job},
        ).scalars()
    ]
    return not statuses or any(s not in TERMINAL_JOB_STATUSES for s in statuses)


def _open_jobs(session: Session, endpoint_id: str, own_jobs: Sequence[str]) -> list[str]:
    """The RunPod jobs to cancel at an off: this session's jobs whose journal rows are not all
    terminal (or that the journal does not know), and every non-terminal journal batch of this
    endpoint whose session is no longer live."""
    wanted: list[str] = []
    terminal = ",".join(f"'{s}'" for s in TERMINAL_JOB_STATUSES)
    for job in own_jobs:
        if _unfinished(session, job):
            wanted.append(job)
    orphaned = session.execute(
        text(
            "SELECT DISTINCT j.batch_remote_id FROM cloud_generation_job j "
            "JOIN gpu_session g ON j.gpu_session_id = g.id "
            "WHERE g.endpoint_id = :endpoint AND g.status NOT IN ('OPENING','OPEN') "
            f"AND j.status NOT IN ({terminal}) AND j.batch_remote_id IS NOT NULL"
        ),
        {"endpoint": endpoint_id},
    ).scalars()
    for job in orphaned:
        if job and str(job) not in wanted:
            wanted.append(str(job))
    return wanted


async def _cancel_jobs(control: EndpointControl, jobs: Sequence[str]) -> list[str]:
    """POST /cancel for each job; every one is tried, the errors are returned."""
    errors: list[str] = []
    for job in jobs:
        try:
            await control.cancel(job)
        except MediaProviderError as exc:
            errors.append("CANCEL:" + str(exc.code or exc.http_status or type(exc).__name__))
    return errors


def _health_record(health: EndpointHealth) -> dict[str, Any]:
    return {
        "in_queue": health.in_queue,
        "in_progress": health.in_progress,
        "running": health.running,
        "idle": health.idle,
        "completed": health.completed,
        "failed": health.failed,
        "read_at": utc_now(),
    }


async def _switch_off(
    control: EndpointControl,
    jobs: Sequence[str],
    *,
    verify: bool,
    cancel: bool = True,
    fast: bool = False,
    evidence: dict[str, Any] | None = None,
) -> tuple[OffReading, list[str]]:
    """Purge, cancel, max=0, verify. Every part is tried; the errors are returned. ``fast``
    (the window closing, ~4 s in all): purge and max=0 are sent together, so a slow purge
    never holds back the max=0.

    ``evidence`` (a dict, filled in place) is asked for when a /run of the session failed with
    no job id (2026-10-09): the queue is read once BEFORE anything is taken out of it (GET
    /health: inQueue, inProgress, workers.running), and RunPod's own purge count is kept. A
    read that fails is recorded as unread, never as zero; the off itself goes on regardless.
    That read is ONE try of at most `EVIDENCE_READ_SECONDS`, never the control's retries (up to
    4 x 60 s with backoff): it comes exactly when RunPod's API is failing, and the purge and the
    max=0 behind it must not wait (2026-10-09 review)."""
    errors: list[str] = []
    if evidence is not None and not fast:
        reader = EndpointControl(
            control.config,
            control.endpoint_id,
            control.transport,
            request_timeout=EVIDENCE_READ_SECONDS,
            retries=0,
        )
        try:
            health = await asyncio.wait_for(reader.health(), EVIDENCE_READ_SECONDS + 1.0)
            evidence["before_purge"] = _health_record(health)
        except Exception as exc:  # noqa: BLE001 - unread, never zero, and never the off's problem
            evidence["before_purge"] = None
            evidence["before_purge_problem"] = str(
                getattr(exc, "code", None)
                or getattr(exc, "http_status", None)
                or type(exc).__name__
            )
    if fast:
        answers = await asyncio.gather(
            control.purge_queue(), control.set_workers(0), return_exceptions=True
        )
        for label, answer in zip(("PURGE:", "MAX0:"), answers, strict=True):
            if isinstance(answer, BaseException):
                code = getattr(answer, "code", None) or getattr(answer, "http_status", None)
                errors.append(label + str(code or type(answer).__name__))
    else:
        try:
            await control.purge_queue()
        except MediaProviderError as exc:
            errors.append("PURGE:" + str(exc.code or exc.http_status or type(exc).__name__))
        if evidence is not None:
            evidence["purge_removed"] = control.last_purge_removed
            evidence["purged_at"] = utc_now()
            evidence["cancelled"] = list(jobs) if cancel else []
        if cancel:
            errors += await _cancel_jobs(control, jobs)
        try:
            await control.set_workers(0)
        except MediaProviderError as exc:
            errors.append("MAX0:" + str(exc.code or exc.http_status or type(exc).__name__))
    if verify:
        reading = await control.verify_off()
        if reading.off and errors:
            # RunPod reads OFF: what failed on the way does not matter any more.
            logger.info("runpod_off_after_errors", extra={"errors": errors})
    else:
        reading = OffReading(
            endpoint_id=control.endpoint_id,
            off=False,
            workers_max=None,
            running=None,
            in_progress=None,
            in_queue=None,
            idle=None,
            reason_ro="Oprirea a fost trimisă, dar nu a fost verificată.",
            read_at=utc_now(),
        )
    if verify and control.last_settings is not None and control.last_health is not None:
        remember_reading(control.endpoint_id, control.last_settings, control.last_health)
    return reading, errors


def _unreadable(endpoint_id: str, reason_ro: str) -> OffReading:
    return OffReading(
        endpoint_id=endpoint_id,
        off=False,
        workers_max=None,
        running=None,
        in_progress=None,
        in_queue=None,
        idle=None,
        reason_ro=reason_ro,
        read_at=utc_now(),
    )


def _tell_off(
    engine: Engine,
    aggregate_id: str,
    reading: OffReading,
    correlation: str,
    *,
    letter: bool = True,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {**reading.as_dict(), **(extra or {})}
    if reading.off:
        _write_event(engine, "runpod.gpu_off_verified", aggregate_id, payload, correlation)
        return
    _write_event(engine, "runpod.gpu_off_unverified", aggregate_id, payload, correlation)
    if letter:
        owner_letter(
            engine,
            "GPU-ul RunPod nu a confirmat oprirea",
            OFF_UNVERIFIED_LETTER + (f"\n{reading.reason_ro}" if reading.reason_ro else ""),
            "runpod_gpu_off_unverified",
            correlation,
        )


# --------------------------------------------------------------------------- open and close


def precheck(
    engine: Engine,
    adapter: Any,
    *,
    purpose: Literal["image", "video"],
    integration_id: str | None = None,
) -> None:
    """What `open_session` would refuse whatever the step's own verdict, read BEFORE the step
    asks for or spends the Owner's yes (completeness check, 2026-10-08): RunPod Serverless not
    configured for this purpose, the bucket missing, or his card «Agenții pot porni singuri
    GPU-ul RunPod …» not accepted. A yes spent on a step whose GPU cannot be switched on would
    be a yes lost with nothing bought. A simulation passes (it switches nothing on)."""
    from app.services import (  # noqa: PLC0415 - services imports providers
        BLOCKED_INFRA_DISABLED,
        GPU_INFRA_DISABLED_WORDS,
        _runpod_infra_allowed,
    )

    config: RunPodConfig = adapter.config
    if config.mock:
        return
    # His stop holds before anything else is read: no yes is asked or spent while it stands.
    _refuse_owner_hold(engine)
    if not config.configured or config.endpoint_for(purpose) is None or config.mode != "serverless":
        raise GpuSessionRefused(
            "NOT_CONFIGURED", "RunPod Serverless nu este configurat pentru acest pas."
        )
    if config.bucket() is None:
        raise GpuSessionRefused(
            "NOT_CONFIGURED",
            "Bucketul pentru rezultatele RunPod nu este configurat: GPU-ul nu se pornește.",
        )
    identifier = getattr(adapter, "integration_id", None) or integration_id
    with Session(engine) as session:
        if not _runpod_infra_allowed(session, identifier):
            raise GpuSessionRefused(BLOCKED_INFRA_DISABLED, GPU_INFRA_DISABLED_WORDS)
    # Where the weights live (2026-10-09): the cached model reads his mirror, which must exist;
    # an endpoint whose results proved other weights waits for his console step.
    not_ready = weights.readiness_problem(config, purpose)
    if not_ready:
        raise GpuSessionRefused("WEIGHTS_NOT_READY", not_ready)
    _refuse_held(engine, identifier, purpose, config)


def _refuse_held(
    engine: Engine,
    integration_id: str | None,
    purpose: Literal["image", "video"],
    config: RunPodConfig,
) -> None:
    held = weights.weights_hold(engine, integration_id, purpose, config)
    if held:
        raise GpuSessionRefused("WEIGHTS_MISMATCH", held)


RUNPOD_OFF_WORDS = (
    "RunPod este oprit din comutatorul «RunPod pornit»: GPU-ul nu se pornește; nu s-a trimis "
    "și nu s-a cheltuit nimic."
)

#: The Owner's «Oprește GPU acum» HOLDS (2026-10-12): his press is recorded as a hold, on the
#: record as {on: true, by, command_id}; lifted only by his answer «Permite din nou» on the card
#: `decisions.producers.gpu_hold` writes ({on: false}). 16:52:08 that day he pressed it while the
#: Director's repair of Higgs-2's scene 5 was buying a clip; the clip was cancelled, and 25 s
#: later the same walk opened a new GPU session and bought the same clip again — his stop held
#: for nothing but the job it caught.
OWNER_HOLD_EVENT = "runpod.owner_hold"
OWNER_HOLD = "OWNER_HOLD"
OWNER_HOLD_WORDS = (
    "Ai oprit GPU-ul: niciun pas plătit nu-l mai pornește până nu permiți din nou («Permite GPU "
    "din nou», lângă «Oprește GPU acum»); nu s-a trimis și nu s-a cheltuit nimic."
)


def owner_hold_active(engine: Engine) -> bool:
    """Whether his stop holds now: the newest `OWNER_HOLD_EVENT` says on. Unreadable → held
    (a GPU is never switched on past a stop nobody could read)."""
    from app.models import DomainEvent  # noqa: PLC0415 - the core's model

    try:
        with Session(engine) as session:
            newest = session.scalar(
                select(DomainEvent)
                .where(DomainEvent.event_type == OWNER_HOLD_EVENT)
                .order_by(DomainEvent.sequence.desc())
                .limit(1)
            )
    except Exception:  # noqa: BLE001 - fail closed on money
        logger.warning("owner_hold_unreadable")
        return True
    payload = newest.payload if newest is not None and isinstance(newest.payload, dict) else {}
    return bool(payload.get("on"))


def set_owner_hold(engine: Engine, on: bool, *, by: str, command_id: str | None = None) -> None:
    """Record his hold (``on``) or its lift; idempotent in effect (the newest one counts)."""
    _write_event(
        engine,
        OWNER_HOLD_EVENT,
        "owner_hold",
        {"on": bool(on), "by": by, "command_id": command_id},
        command_id or str(uuid4()),
    )


def _refuse_owner_hold(engine: Engine) -> None:
    if owner_hold_active(engine):
        raise GpuSessionRefused(OWNER_HOLD, OWNER_HOLD_WORDS)


def _switched_off_now(engine: Engine, integration_id: str | None) -> bool:
    """His switch (or RUNPOD_ENABLED) as the integration row says it NOW, not as the step's
    adapter read it. No row (a test adapter, a removed connection): nothing to read."""
    if not integration_id:
        return False
    from app.integrations.models import Integration  # noqa: PLC0415

    with Session(engine) as session:
        row = session.get(Integration, integration_id)
        stored = dict(row.config or {}) if row is not None and row.kind == "runpod" else None
    if stored is None:
        return False
    try:
        return not RunPodConfig.from_integration(stored, {}).enabled
    except ValueError:
        return True  # a config that no longer reads never switches a GPU on


def _kernel(engine: Engine, permit: StepPermit) -> dict[str, Any]:
    from app.services import may_act  # noqa: PLC0415 - services imports providers

    with Session(engine) as session:
        verdict: dict[str, Any] = may_act(
            session,
            "infra.gpu_on",
            requester=permit.requester,
            subject=permit.storyboard_id,
            cost_usd=permit.cost_usd,
            context=permit.context(),
            ask_owner=False,
        )
        session.rollback()
    return verdict


def _insert(
    engine: Engine,
    *,
    endpoint_id: str,
    purpose: str,
    permit: StepPermit,
    status: str,
    workers_max: int,
    config: RunPodConfig,
) -> str:
    moment = _now()
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        session.add(
            GpuSessionRow(
                id=identifier,
                integration_id=permit.integration_id or "",
                endpoint_id=endpoint_id,
                purpose=purpose,
                step=permit.step[:30],
                storyboard_id=permit.storyboard_id[:100] if permit.storyboard_id else None,
                correlation_id=permit.correlation_id[:100],
                process_token=PROCESS_TOKEN,
                status=status,
                workers_max=workers_max,
                opened_at=moment.isoformat(),
                renewed_at=moment.isoformat(),
                expires_at=(moment + timedelta(seconds=config.session_max_seconds)).isoformat(),
                remote_job_ids=[],
            )
        )
    return identifier


def _update(engine: Engine, identifier: str, **values: Any) -> None:
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = session.get(GpuSessionRow, identifier)
        if row is not None:
            for key, value in values.items():
                setattr(row, key, value)


def open_session(
    engine: Engine,
    adapter: Any,
    *,
    purpose: Literal["image", "video"],
    permit: StepPermit,
    transport: Transport | None = None,
) -> GpuSession:
    """Switch the one GPU on for this paid step (see the module's text for the order)."""
    config: RunPodConfig = adapter.config
    integration_id = getattr(adapter, "integration_id", None) or permit.integration_id
    if config.mock:
        identifier = _insert(
            engine,
            endpoint_id="mock",
            purpose=purpose,
            permit=permit,
            status=OPEN,
            workers_max=0,
            config=config,
        )
        return GpuSession(
            engine=engine,
            id=identifier,
            endpoint_id="mock",
            purpose=purpose,
            workers_max=0,
            mock=True,
            config=config,
            integration_id=integration_id,
            correlation_id=permit.correlation_id,
            transport=transport,
        )
    endpoint_id = config.endpoint_for(purpose)
    # His stop holds (`OWNER_HOLD_EVENT`): read again here, at the switch, whatever the step's
    # precheck read before (a press between the two is his press).
    _refuse_owner_hold(engine)
    if not config.configured or endpoint_id is None or config.mode != "serverless":
        raise GpuSessionRefused(
            "NOT_CONFIGURED", "RunPod Serverless nu este configurat pentru acest pas."
        )
    if config.bucket() is None:
        raise GpuSessionRefused(
            "NOT_CONFIGURED",
            "Bucketul pentru rezultatele RunPod nu este configurat: GPU-ul nu se pornește.",
        )
    _refuse_held(engine, integration_id, purpose, config)
    verdict = _kernel(engine, permit)
    if not verdict.get("allowed"):
        raise GpuSessionRefused(
            str(verdict.get("status") or "BLOCKED_NOT_IN_STEP"),
            str(verdict.get("reason") or NOT_IN_STEP_WORDS),
        )
    # The one-GPU rule: a live session on another endpoint makes this step wait, then refuse.
    deadline = time.monotonic() + config.gpu_busy_wait_seconds
    while True:
        with _GPU_RULE_LOCK:
            with Session(engine) as session:
                busy = [
                    row
                    for row in session.scalars(
                        select(GpuSessionRow).where(GpuSessionRow.status.in_(LIVE))
                    )
                    if row.endpoint_id not in (endpoint_id, "mock")
                ]
            if not busy:
                identifier = _insert(
                    engine,
                    endpoint_id=endpoint_id,
                    purpose=purpose,
                    permit=permit,
                    status=OPENING,
                    workers_max=config.max_workers,
                    config=config,
                )
                break
        if time.monotonic() >= deadline:
            raise GpuSessionRefused(
                "GPU_BUSY",
                "GPU-ul RunPod este deja folosit de alt pas; nu pornesc un al doilea.",
            )
        time.sleep(BUSY_POLL_SECONDS)
    control = EndpointControl(config, endpoint_id, transport)
    with endpoint_lock(endpoint_id):
        if _switched_off_now(engine, integration_id):
            # His «RunPod pornit» went OFF after this step built its adapter (adversary
            # 2026-10-09). Read under the endpoint lock his OFF's GPU off also takes: a step
            # that gets here after his OFF never switches the GPU on.
            _update(
                engine,
                identifier,
                status=FAILED_OPEN,
                close_reason="OPEN_FAILED",
                closed_at=utc_now(),
                error_code="RUNPOD_OFF",
            )
            raise GpuSessionRefused("RUNPOD_OFF", RUNPOD_OFF_WORDS)
        with Session(engine) as session:
            shared = bool(
                [r for r in _other_live(session, endpoint_id, identifier) if r.status == OPEN]
            )
            # A recent /run booked as never queued: its job, queued late, must not run on this
            # GPU (`booked_unsent_sessions`). While the endpoint is off nothing of ours waits in
            # its queue, so the purge removes only such a job. A shared endpoint is already on.
            recent = (
                [] if shared else booked_unsent_sessions(session, endpoint_id, identifier, config)
            )
        removed: int | None = None
        try:
            if not shared:
                removed = asyncio.run(_switch_on(control, config.max_workers, purge=bool(recent)))
        except Exception as exc:  # noqa: BLE001 - every failure here refuses the step unsent
            code = str(
                getattr(exc, "code", None)
                or getattr(exc, "http_status", None)
                or type(exc).__name__
            )
            logger.warning(
                "runpod_gpu_on_failed", extra={"endpoint_id": endpoint_id, "error": code}
            )
            _update(
                engine,
                identifier,
                status=FAILED_OPEN,
                close_reason="OPEN_FAILED",
                closed_at=utc_now(),
                error_code=code[:100],
            )
            with Session(engine) as session:
                still_shared = bool(_other_live(session, endpoint_id, identifier))
            if not still_shared:
                try:
                    asyncio.run(control.set_workers(0))
                except Exception as off_exc:  # noqa: BLE001 - the guard retries
                    logger.warning(
                        "runpod_gpu_on_compensation_failed",
                        extra={"endpoint_id": endpoint_id, "error": type(off_exc).__name__},
                    )
            raise GpuSessionRefused(
                "COMPUTE_NOT_READY",
                "GPU-ul RunPod nu a putut fi pornit; nu s-a trimis și nu s-a cheltuit nimic.",
            ) from None
        if recent:
            # A job removed here was a late one of a /run booked as never queued: it never ran.
            logger.log(
                logging.WARNING if removed else logging.INFO,
                "runpod_queue_purged_before_on",
                extra={"endpoint_id": endpoint_id, "removed": removed, "after_sessions": recent},
            )
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            row = session.get(GpuSessionRow, identifier)
            if row is not None:
                row.status = OPEN
                row.renewed_at = utc_now()
            _event(
                session,
                "runpod.gpu_session_opened",
                identifier,
                {
                    "endpoint_id": endpoint_id,
                    "purpose": purpose,
                    "step": permit.step,
                    "storyboard_id": permit.storyboard_id,
                    "workers_max": config.max_workers,
                    "shared": shared,
                    **(
                        {"purged_first": {"after_sessions": recent, "removed": removed}}
                        if recent
                        else {}
                    ),
                },
                permit.correlation_id,
            )
    return GpuSession(
        engine=engine,
        id=identifier,
        endpoint_id=endpoint_id,
        purpose=purpose,
        workers_max=config.max_workers,
        mock=False,
        config=config,
        integration_id=integration_id,
        correlation_id=permit.correlation_id,
        transport=transport,
    )


def close_session(
    engine: Engine,
    session: GpuSession,
    *,
    reason: str,
    transport: Transport | None = None,
) -> OffReading | None:
    """End the step's session. The last live session on the endpoint switches the GPU off and
    verifies it. Never raises: a failure is recorded, told, and retried by the guard."""
    if session.closed:
        return None
    session.closed = True
    if session.mock:
        _update(engine, session.id, status=CLOSED, close_reason=reason, closed_at=utc_now())
        return None
    transport = transport or session.transport
    # A /run of this session failed with no job id (2026-10-09): the off below also keeps what
    # proves whether RunPod queued anything (`_switch_off`'s evidence, `batch.prove_unsent`).
    evidence: dict[str, Any] | None = (
        {"uncertain_items": len(session.uncertain_keys)} if session.uncertain_keys else None
    )
    try:
        with endpoint_lock(session.endpoint_id):
            with Session(engine) as db, db.begin():
                lock_for_write(db)
                row = db.get(GpuSessionRow, session.id)
                if row is None or row.status not in LIVE:
                    # Forced off already (the Owner, the guard, a shutdown): that off is done.
                    return None
                row.status = CLOSING
                jobs = list(row.remote_job_ids or [])
                opened_at = row.opened_at
                others = [r for r in _other_live(db, session.endpoint_id, session.id)]
            if evidence is not None:
                evidence["remote_job_ids"] = list(jobs)
            if others:
                if evidence is not None:
                    # No purge while another step uses the GPU: nothing here can be proven.
                    session.off_evidence = {**evidence, "shared": True}
                # The GPU stays on for the other step (refcount): no purge, no max=0. But this
                # step's own jobs that are not finished (it failed or stopped mid-batch) would
                # keep the one worker busy and billed for nobody: they are cancelled.
                with Session(engine) as db:
                    own = [job for job in jobs if _unfinished(db, job)]
                errors: list[str] = []
                if own:
                    control = EndpointControl(session.config, session.endpoint_id, transport)
                    errors = asyncio.run(_cancel_jobs(control, own))
                _update(
                    engine,
                    session.id,
                    status=CLOSED,
                    close_reason=reason,
                    closed_at=utc_now(),
                    error_code=(";".join(errors)[:100] or None),
                )
                return None
            with Session(engine) as db:
                to_cancel = _open_jobs(db, session.endpoint_id, jobs)
            control = EndpointControl(session.config, session.endpoint_id, transport)
            reading, errors = asyncio.run(
                _switch_off(control, to_cancel, verify=True, evidence=evidence)
            )
            stored: dict[str, Any] = reading.as_dict()
            if evidence is not None:
                with Session(engine) as db:
                    evidence["other_sessions"] = overlapping_sessions(
                        db, session.endpoint_id, session.id, opened_at
                    )
                evidence["errors"] = list(errors)
                stored = {**stored, "evidence": evidence}
                session.off_evidence = {**evidence, "off": reading.as_dict()}
            _update(
                engine,
                session.id,
                status=CLOSED,
                close_reason=reason,
                closed_at=utc_now(),
                verified_off=reading.off,
                off_reading=stored,
                error_code=(";".join(errors)[:100] or None),
            )
    except Exception as exc:  # noqa: BLE001 - the close never breaks the step; the guard retries
        logger.warning(
            "runpod_gpu_close_failed",
            extra={"endpoint_id": session.endpoint_id, "error": type(exc).__name__},
        )
        session.off_evidence = None  # a close that failed proves nothing
        reading = _unreadable(
            session.endpoint_id, "Oprirea GPU-ului RunPod nu a putut fi trimisă sau verificată."
        )
        _update(
            engine,
            session.id,
            status=CLOSED,
            close_reason=reason,
            closed_at=utc_now(),
            verified_off=False,
            off_reading=reading.as_dict(),
            error_code=type(exc).__name__[:100],
        )
    extra: dict[str, Any] = {"reason": reason}
    if session.off_evidence is not None:
        extra["evidence"] = {k: v for k, v in session.off_evidence.items() if k != "off"}
    _tell_off(engine, session.id, reading, session.correlation_id, extra=extra)
    return reading


@contextmanager
def gpu_session(
    engine: Engine,
    adapter: Any,
    *,
    purpose: Literal["image", "video"],
    permit: StepPermit,
    transport: Transport | None = None,
) -> Iterator[GpuSession]:
    """The paid step's GPU: on at entry, off in ``finally`` (STEP_DONE or STEP_FAILED)."""
    opened = open_session(engine, adapter, purpose=purpose, permit=permit, transport=transport)
    reason = "STEP_DONE"
    try:
        yield opened
    except BaseException:
        reason = "STEP_FAILED"
        raise
    finally:
        close_session(engine, opened, reason=reason, transport=transport)


# ------------------------------------------------------------------- the integrations' GPUs


@dataclass(frozen=True)
class RunPodTarget:
    integration_id: str
    config: RunPodConfig | None
    problem_ro: str | None


def runpod_targets(
    engine: Engine, vault: CredentialVault, integration_ids: Sequence[str] | None = None
) -> list[RunPodTarget]:
    """Every RunPod integration with its config, or why it could not be read."""
    from app.integrations.models import Integration  # noqa: PLC0415

    targets: list[RunPodTarget] = []
    with Session(engine) as session:
        found = list(session.scalars(select(Integration).where(Integration.kind == "runpod")))
        for row in found:
            session.expunge(row)
    for row in found:
        if integration_ids is not None and row.id not in integration_ids:
            continue
        try:
            secrets = vault.decrypt(row.encrypted_secrets)
        except Exception:  # noqa: BLE001 - an unreadable vault is said, not raised
            secrets = {}
            problem: str | None = "Cheile conexiunii RunPod nu pot fi citite din seif."
        else:
            problem = None
        try:
            config = RunPodConfig.from_integration(dict(row.config or {}), secrets)
        except Exception:  # noqa: BLE001
            targets.append(
                RunPodTarget(row.id, None, "Configurația conexiunii RunPod nu este validă.")
            )
            continue
        targets.append(RunPodTarget(row.id, config, problem))
    return targets


def controllable(config: RunPodConfig | None) -> bool:
    """A real Serverless integration the studio can switch: a key and an endpoint. Switching
    OFF does not wait for RUNPOD_ENABLED: a disabled flag never leaves a GPU on."""
    return bool(
        config is not None
        and not config.mock
        and config.mode == "serverless"
        and config.api_key.get_secret_value()
        and config.endpoints()
    )


def listed(target: RunPodTarget) -> bool:
    """A real Serverless integration to show and to switch: controllable, or one whose keys
    cannot be read (said as UNKNOWN / unverified rather than hidden)."""
    config = target.config
    return controllable(config) or bool(
        target.problem_ro
        and config is not None
        and not config.mock
        and config.mode == "serverless"
        and config.endpoints()
    )


def force_off(
    engine: Engine,
    vault: CredentialVault,
    *,
    reason: str,
    fast: bool = False,
    integration_ids: Sequence[str] | None = None,
    transport: Transport | None = None,
) -> list[OffReading]:
    """Switch every RunPod GPU of the studio off now: the Owner's button, a shutdown, the
    launcher, the guard. Never consults the kernel (off is always allowed). Idempotent.
    ``fast`` (the window closing): purge + PATCH only, 2 s per request, no verification."""
    readings: list[OffReading] = []
    correlation = str(uuid4())
    # Every endpoint gets its off at once (concurrently), and only then is any verified: an
    # endpoint that is slow to verify (up to idleTimeout + grace) or slow to answer never holds
    # back another endpoint's max=0 past the launcher's or the shutdown's time bound.
    plans: list[tuple[RunPodConfig, str, list[str]]] = []
    held: list[threading.Lock] = []
    results: list[tuple[OffReading, list[str]]] = []
    try:
        for target in runpod_targets(engine, vault, integration_ids):
            config = target.config
            if config is not None and config.mock:
                _mark_forced(engine, target.integration_id, None, reason)
                continue
            if not listed(target):
                continue
            assert config is not None
            for _purpose, endpoint_id in config.endpoints():
                if target.problem_ro:
                    readings.append(_unreadable(endpoint_id, target.problem_ro))
                    continue
                if any(planned == endpoint_id for _, planned, _ in plans):
                    continue
                lock = endpoint_lock(endpoint_id)
                if lock.acquire(timeout=1.0 if fast else 120.0):
                    held.append(lock)
                jobs = _mark_forced(engine, target.integration_id, endpoint_id, reason)
                to_cancel: list[str] = list(jobs)
                if not fast:
                    try:
                        with Session(engine) as db:
                            to_cancel = _open_jobs(db, endpoint_id, jobs)
                    except Exception:  # noqa: BLE001 - the off goes on without the journal
                        to_cancel = list(jobs)
                plans.append((config, endpoint_id, to_cancel))
        if plans:
            try:
                results = asyncio.run(_off_everywhere(plans, fast=fast, transport=transport))
            except Exception as exc:  # noqa: BLE001 - said, never raised
                results = [
                    (
                        _unreadable(endpoint, "Oprirea GPU-ului RunPod nu a putut fi trimisă."),
                        [type(exc).__name__],
                    )
                    for _, endpoint, _ in plans
                ]
    finally:
        for lock in held:
            lock.release()
    for (_config, endpoint_id, _jobs), (reading, errors) in zip(plans, results, strict=True):
        readings.append(reading)
        _write_event(
            engine,
            "runpod.gpu_forced_off",
            endpoint_id,
            {**reading.as_dict(), "reason": reason, "fast": fast, "errors": errors},
            correlation,
        )
        if not fast:
            _tell_off(engine, endpoint_id, reading, correlation, letter=reason != "OWNER_OFF")
    if reason in ("SHUTDOWN", "LAUNCHER_STOP") and not fast:
        # The studio stopping also terminates a running copy pod (2026-10-09): nothing of the
        # studio's keeps billing while it is down. A closing window (fast) leaves it to BOOT.
        _stop_copies(engine, vault, transport)
    return readings


def _stop_copies(engine: Engine, vault: CredentialVault, transport: Transport | None) -> None:
    from app.providers.runpod import pods  # noqa: PLC0415 - pods is the guard's neighbour

    try:
        pods.watch_copies(engine, vault, reason="SHUTDOWN", transport=transport)
    except Exception as exc:  # noqa: BLE001 - the GPU's own off is never held back by it
        logger.warning("runpod_mirror_stop_failed", extra={"error": type(exc).__name__})


async def _off_everywhere(
    plans: Sequence[tuple[RunPodConfig, str, list[str]]],
    *,
    fast: bool,
    transport: Transport | None,
) -> list[tuple[OffReading, list[str]]]:
    """Purge, cancel (not when fast) and max=0 on every endpoint concurrently; then, unless
    fast, verify every endpoint concurrently."""
    controls = [
        EndpointControl(
            config,
            endpoint_id,
            transport,
            request_timeout=FAST_REQUEST_SECONDS if fast else None,
            retries=0 if fast else None,
        )
        for config, endpoint_id, _ in plans
    ]
    sent = await asyncio.gather(
        *(
            _switch_off(control, jobs, verify=False, cancel=not fast, fast=fast)
            for control, (_, _, jobs) in zip(controls, plans, strict=True)
        ),
        return_exceptions=True,
    )
    verified: list[OffReading | BaseException | None] = [None] * len(controls)
    if not fast:
        verified = list(
            await asyncio.gather(*(c.verify_off() for c in controls), return_exceptions=True)
        )
    results: list[tuple[OffReading, list[str]]] = []
    for control, outcome, check in zip(controls, sent, verified, strict=True):
        endpoint_id = control.endpoint_id
        if isinstance(outcome, BaseException):
            reading = _unreadable(endpoint_id, "Oprirea GPU-ului RunPod nu a putut fi trimisă.")
            errors = [type(outcome).__name__]
        else:
            reading, errors = outcome
        if fast:
            if errors:
                reading = _unreadable(endpoint_id, "Oprirea GPU-ului RunPod nu a putut fi trimisă.")
        elif isinstance(check, OffReading):
            reading = check
            if control.last_settings is not None and control.last_health is not None:
                remember_reading(endpoint_id, control.last_settings, control.last_health)
            if reading.off and errors:
                logger.info("runpod_off_after_errors", extra={"errors": errors})
        else:
            reading = _unreadable(
                endpoint_id, "Oprirea GPU-ului RunPod a fost trimisă, dar nu a putut fi verificată."
            )
            errors = [*errors, "VERIFY:" + type(check).__name__]
        results.append((reading, errors))
    return results


def _mark_forced(
    engine: Engine, integration_id: str, endpoint_id: str | None, reason: str
) -> list[str]:
    """The live sessions of this endpoint (or of this simulated integration) become FORCED_OFF;
    returns the RunPod jobs they sent."""
    jobs: list[str] = []
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            query = select(GpuSessionRow).where(GpuSessionRow.status.in_((*LIVE, CLOSING)))
            if endpoint_id is None:
                query = query.where(
                    GpuSessionRow.endpoint_id == "mock",
                    GpuSessionRow.integration_id == integration_id,
                )
            else:
                query = query.where(GpuSessionRow.endpoint_id == endpoint_id)
            for row in session.scalars(query):
                jobs += [j for j in (row.remote_job_ids or []) if j not in jobs]
                row.status, row.close_reason, row.closed_at = FORCED_OFF, reason, utc_now()
    except Exception as exc:  # noqa: BLE001 - the off goes on without the rows
        logger.warning("runpod_force_off_rows_failed", extra={"error": type(exc).__name__})
    return jobs


# --------------------------------------------------------------------------- for the page


def _state(reading: Mapping[str, Any] | None) -> dict[str, Any]:
    if not reading or reading.get("settings") is None or reading.get("health") is None:
        return {
            "state": "UNKNOWN",
            "workers_max": None,
            "running": None,
            "idle": None,
            "in_queue": None,
            "in_progress": None,
            "idle_timeout": None,
            "read_at": reading.get("read_at") if reading else None,
            "problem_ro": (reading or {}).get("problem")
            or "Starea GPU-ului nu a fost citită încă.",
        }
    settings: EndpointSettings = reading["settings"]
    health: EndpointHealth = reading["health"]
    off = is_off(settings, health)
    return {
        "state": "OFF" if off else "ON",
        "workers_max": settings.workers_max,
        "running": health.running,
        "idle": health.idle,
        "in_queue": health.in_queue,
        "in_progress": health.in_progress,
        "idle_timeout": settings.idle_timeout,
        "read_at": reading.get("read_at"),
        "problem_ro": None,
    }


def read_endpoint(
    config: RunPodConfig, endpoint_id: str, transport: Transport | None = None
) -> tuple[EndpointSettings | None, EndpointHealth | None, str | None]:
    """One live read (settings + health), remembered for the page and the guard."""
    control = EndpointControl(config, endpoint_id, transport)
    try:
        settings, health = asyncio.run(control.read())
    except MediaProviderError as exc:
        problem = (
            "Cheia RunPod nu are acces la acest endpoint."
            if exc.http_status in (401, 403)
            else "Nu am putut citi starea GPU-ului RunPod."
        )
        remember_reading(endpoint_id, None, None, problem)
        return None, None, problem
    remember_reading(endpoint_id, settings, health)
    return settings, health, None


def gpu_status(
    engine: Engine,
    vault: CredentialVault,
    *,
    fresh: bool = False,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """What the page's GPU switch shows. Not fresh: the guard's last reading. Fresh: one live
    read per endpoint, at most one per `FRESH_READ_SECONDS`."""
    targets = [t for t in runpod_targets(engine, vault) if t.config is not None]
    real = [t for t in targets if listed(t)]
    simulated = [t for t in targets if t.config is not None and t.config.mock]
    rate = real[0].config if real else targets[0].config if targets else None
    default_rate = RunPodConfig.model_fields["serverless_cost_per_hour"].default
    rate_value = rate.hourly_rate if rate is not None else default_rate
    endpoints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in real:
        assert target.config is not None
        for purpose, endpoint_id in target.config.endpoints():
            if endpoint_id in seen:
                continue
            seen.add(endpoint_id)
            reading = last_reading(endpoint_id)
            if target.problem_ro:
                reading = {"problem": target.problem_ro, "read_at": None}
            elif fresh and (
                reading is None
                or time.monotonic() - float(reading.get("monotonic", 0)) >= FRESH_READ_SECONDS
            ):
                read_endpoint(target.config, endpoint_id, transport)
                reading = last_reading(endpoint_id)
            endpoints.append(
                {
                    "purpose": purpose,
                    "endpoint_id": endpoint_id,
                    **_state(reading),
                    # A job RunPod has not started a worker for yet: unbilled (2026-10-09).
                    "model_wait_ro": weights.model_wait(endpoint_id),
                }
            )
    with Session(engine) as session:
        live = list(
            session.scalars(
                select(GpuSessionRow)
                .where(GpuSessionRow.status.in_(LIVE))
                .order_by(GpuSessionRow.opened_at)
            )
        )
        last = session.scalars(
            select(GpuSessionRow)
            .where(GpuSessionRow.closed_at.is_not(None), GpuSessionRow.status != FAILED_OPEN)
            .order_by(GpuSessionRow.closed_at.desc())
            .limit(1)
        ).first()
        sessions = [
            {
                "id": row.id,
                "purpose": row.purpose,
                "step": row.step,
                "storyboard_id": row.storyboard_id,
                "opened_at": row.opened_at,
                "renewed_at": row.renewed_at,
                "words_ro": _session_words(session, row),
            }
            for row in live
        ]
        held = owner_hold_active(engine)
        last_off = (
            {"at": last.closed_at, "reason": last.close_reason, "verified": last.verified_off}
            if last is not None
            else None
        )
    configured = bool(real or simulated)
    mock = bool(simulated) and not real
    waiting = next((e["model_wait_ro"] for e in endpoints if e.get("model_wait_ro")), None)
    if not configured:
        words = "RunPod nu este configurat."
    elif mock:
        words = "Simulare RunPod: niciun GPU real."
    # What is being made, in the Owner's words: the film, the scene and the take, never a step's
    # code name (2026-10-12: «GPU pornit, worker activ · pas: scene_redo» — «Ce lucrează? Pentru
    # ce film, ce cadru?»).
    doing = "; ".join(str(s["words_ro"]) for s in sessions if s.get("words_ro"))
    if not configured:
        words = "RunPod nu este configurat."
    elif mock:
        words = "Simulare RunPod: niciun GPU real."
    elif waiting:
        steps = doing or ", ".join(sorted({str(s["step"]) for s in sessions}))
        words = f"GPU: {weights.WAIT_WORDS_RO}" + (f" — {steps}." if steps else ".")
    elif sessions:
        words = "GPU pornit — " + (
            doing or "pas: " + ", ".join(sorted({str(s["step"]) for s in sessions}))
        )
        words = words.rstrip(".") + "."
    elif any(e["state"] == "ON" for e in endpoints):
        words = "GPU pornit fără niciun pas plătit deschis; paznicul îl oprește."
    elif endpoints and all(e["state"] == "OFF" for e in endpoints):
        words = "GPU oprit."
    else:
        words = "GPU: stare necunoscută."
    if held and configured and not mock:
        words = f"{words} Oprit de tine: nu pornește până permiți din nou (cardul din «Decizii»)."
    return {
        "configured": configured,
        "mock": mock,
        "rate_usd_per_hour": f"{rate_value:.2f}",
        "endpoints": endpoints,
        "sessions": sessions,
        "last_off": last_off,
        "words_ro": words,
        "model_wait_ro": waiting,
        "owner_hold": bool(held),
    }


#: A paid step's name in the Owner's words (`StepPermit.step`).
_STEP_WORDS_RO = {
    "stills": "imaginile",
    "test_shot": "cadrul de probă",
    "motion": "mișcarea",
    "scene_redo": "refacerea",
}
#: A take's kind in the Owner's words.
_TAKE_WORDS_RO = {"still": "imaginea", "motion": "clipul", "test_shot": "cadrul de probă"}


def _session_words(session: Session, row: GpuSessionRow) -> str:
    """One live GPU session in the Owner's words: ««The Particle That Shouldn't Exist»: refacerea
    — clipul scenei 5». The scenes are the takes of the session's film still at the vendor
    (SUBMITTED); a session whose takes are not sent yet says its step alone. Never raises."""
    from app.media.models import SceneTake, Storyboard  # noqa: PLC0415 - media imports providers

    try:
        step = _STEP_WORDS_RO.get(str(row.step or ""), str(row.step or "un pas plătit"))
        if not row.storyboard_id:
            return step
        board = session.get(Storyboard, row.storyboard_id)
        title = str(getattr(board, "title", "") or "").strip()
        if title.lower().startswith("storyboard:"):
            title = title.split(":", 1)[1].strip()
        takes = list(
            session.scalars(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == row.storyboard_id,
                    SceneTake.status == "SUBMITTED",
                )
                .order_by(SceneTake.scene_number)
            )
        )
        what = sorted(
            {
                (int(take.scene_number), _TAKE_WORDS_RO.get(str(take.kind), str(take.kind)))
                for take in takes
            }
        )
        made = ", ".join(f"{kind} scenei {scene}" for scene, kind in what)
        film = f"«{title[:80]}»: " if title else ""
        return f"{film}{step}" + (f" — {made}" if made else "")
    except Exception:  # noqa: BLE001 - words never break the GPU switch
        logger.warning("gpu_session_words_unreadable")
        return str(row.step or "")


__all__ = [
    "PROCESS_TOKEN",
    "GpuForcedOff",
    "GpuSession",
    "GpuSessionRefused",
    "GpuSessionRow",
    "OffReading",
    "StepPermit",
    "close_session",
    "force_off",
    "gpu_session",
    "gpu_status",
    "open_session",
    "still_on_words",
]
