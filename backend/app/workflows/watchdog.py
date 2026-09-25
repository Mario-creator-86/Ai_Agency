"""The watchdog: the part of the studio that notices a day was interrupted.

A render is a row marked RENDERING, a process running FFmpeg, and a row marked COMPLETED or
FAILED when the process comes back. Kill the process — a reboot, a closed terminal, a crash —
and the row stays RENDERING forever, with nothing left to change it. Measured on a copy of the
live database: two `video_render_job` rows had been RENDERING since 2026-09-12 with `finished_at`
NULL. In the same way, an upload whose answer was lost leaves a publication in REMOTE_UNKNOWN,
and `reconcile_publication` — written for exactly that — had no caller outside the tests.

One pass of the watchdog does four things and records each. It fails renders that have made
no progress past a threshold, with the reason on the row and an event, the way the assembler
itself records a failure. It sends every uncertain publication through the reconciliation that
already exists, a bounded number of times, and then hands the row to the Owner rather than
asking a platform that does not answer forever. And it reports task leases that have lapsed
without touching them: the queue re-claims an expired lease on its own (`claim_task`), and a
second mechanism doing the same would be two owners of one row. And it releases the money a
film held and never spent: the media stage reserves what a render is estimated to cost and
settles the hold when the cost rows are in the books, so a process killed in between leaves
the day's budget pledged to a film nobody is making.

What it will not do. It changes nothing while the Owner's autonomy stop is set — safe mode sets
that stop too — because a stopped studio is a studio in which nothing moves, including repair.
And it never uploads on a guess: the retry path it reuses asks the platform first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.economy.budget import DEFAULT_RESERVATION_TTL_SECONDS, release_stale_reservations
from app.media.models import VideoRenderJob
from app.models import DomainEvent, OwnerPolicy
from app.providers.publishing_base import PublishingProvider
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    channel_bindings,
    execute_publication,
    reconcile_publication,
)
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem

logger = logging.getLogger("studio.watchdog")

#: The workflow type and the job name the worker registers this under. The job is light —
#: it reads three tables and asks a platform a question — so it can run often.
WATCHDOG = "WATCHDOG"
WATCHDOG_JOB_NAME = "watchdog"

#: A render is a few minutes of FFmpeg after a few minutes of generation. Three hours without
#: an end is not a slow render; it is a process that is no longer there. Read through
#: `settings.render_stuck_after_seconds` when the settings have it.
DEFAULT_RENDER_STUCK_AFTER_SECONDS = 3 * 3600

#: How many times the watchdog asks a platform that cannot be reached about one publication
#: before the row is handed to the Owner. Read through `settings.reconcile_max_attempts`.
DEFAULT_RECONCILE_MAX_ATTEMPTS = 3

#: Uncertain publications considered per pass. A backlog larger than this is a broken studio,
#: not a queue, and the next pass takes the rest.
PUBLICATIONS_PER_PASS = 20

#: The event the watchdog writes for each attempt on a publication. Counting these per row is
#: what bounds the attempts without a column for it: the record is the counter.
RECONCILE_ATTEMPT_EVENT = "publishing.watchdog_reconcile"

#: The states `reconcile_publication` and `execute_publication` were written for.
UNCERTAIN_STATES = ("REMOTE_UNKNOWN", "FAILED_RETRYABLE")

PublisherResolver = Callable[[str], PublishingProvider | None]


class NoPublisher(RuntimeError):
    """The channel a publication belongs to has no account to ask. Reported, never guessed."""


def _autonomy_stopped(engine: Engine) -> bool:
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        # A missing policy row is a studio that was never bootstrapped: treat it as stopped.
        return bool(policy.autonomy_stopped) if policy else True


def _elapsed_text(seconds: float) -> str:
    """How long the row has been waiting, for a person: "4 ore", "1 oră", "20 de minute"."""
    hours = int(seconds // 3600)
    if hours >= 1:
        return "1 oră" if hours == 1 else f"{hours} ore"
    minutes = max(1, int(seconds // 60))
    if minutes == 1:
        return "1 minut"
    return f"{minutes} minute" if minutes < 20 else f"{minutes} de minute"


def _parse(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------- renders --


def _fail_stuck_renders(
    engine: Engine, threshold_seconds: int, correlation_id: str
) -> dict[str, Any]:
    """Fail every RENDERING row older than the threshold, the way `_fail_job` would have."""
    now = datetime.now(UTC)
    failed_ids: list[str] = []
    rendering = 0
    editor_to_idle: str | None = None
    with Session(engine) as session, session.begin():
        jobs = session.scalars(
            select(VideoRenderJob).where(
                VideoRenderJob.status == "RENDERING", VideoRenderJob.finished_at.is_(None)
            )
        ).all()
        for job in jobs:
            elapsed = (now - _parse(job.started_at)).total_seconds()
            if elapsed < threshold_seconds:
                rendering += 1
                continue
            reason = f"Blocat: fără progres de {_elapsed_text(elapsed)}"
            job.status = "FAILED"
            job.finished_at = utc_now()
            job.duration_ms = elapsed * 1000
            # The log is the assembler's own last words plus the watchdog's verdict, kept to the
            # same length the assembler keeps.
            job.execution_log = f"{job.execution_log or ''}\n{reason}".strip()[-8000:]
            append_event(
                session,
                "media.render_failed",
                "video_render_job",
                job.id,
                1,
                {
                    "storyboard_id": job.storyboard_id,
                    "reason": reason,
                    "stuck_seconds": int(elapsed),
                    "watchdog": True,
                },
                correlation_id,
            )
            failed_ids.append(job.id)
            logger.error("render_stuck", extra={"reason": reason, "job_id": job.id})
        if failed_ids:
            # The assembler marks the editor WORKING for the render and IDLE when it ends. A
            # process that died left her typing in the office; the render it was for is now
            # closed, so her state is closed with it.
            from app.agents.memory import agent_for_role  # noqa: PLC0415

            editor = agent_for_role(session, "VideoEditor")
            if editor is not None and editor.runtime_state == "WORKING":
                editor_to_idle = editor.id
    if editor_to_idle is not None:
        from app.agents.services import mark_idle  # noqa: PLC0415

        mark_idle(engine, editor_to_idle, "assemble_video")
    return {"failed": len(failed_ids), "failed_ids": failed_ids, "rendering": rendering}


# ----------------------------------------------------------------------- publications --


def _default_publisher_for(engine: Engine, settings: Any) -> PublisherResolver:
    """The account bound to a channel slot, from the vault, as the runbook's publish stage."""
    from pathlib import Path  # noqa: PLC0415

    from app.integrations.services import selected_youtube  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415

    # The same file `create_app` opens: next to the database, never a second key.
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    bindings = channel_bindings(engine)

    def resolve(channel_id: str) -> PublishingProvider | None:
        binding = bindings.get(channel_id) or {}
        if not binding.get("publisher_ready"):
            raise NoPublisher(
                "Canalul nu este legat de un cont YouTube conectat; publicarea nu poate fi "
                "verificată până nu îl legi în Distribuție → Sloturi de canal."
            )
        try:
            provider = selected_youtube(engine, vault, binding["youtube_connection_id"])
        except ValueError as exc:
            raise NoPublisher(str(exc)) from None
        if provider is None:
            raise NoPublisher("Contul YouTube legat de acest canal nu mai este conectat.")
        return provider

    return resolve


def _attempts_so_far(session: Session, publication_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(
                DomainEvent.aggregate_id == publication_id,
                DomainEvent.event_type == RECONCILE_ATTEMPT_EVENT,
            )
        )
        or 0
    )


def _record_attempt(
    engine: Engine, publication_id: str, attempt: int, outcome: str, correlation_id: str
) -> None:
    with Session(engine) as session, session.begin():
        append_event(
            session,
            RECONCILE_ATTEMPT_EVENT,
            "publication_record",
            publication_id,
            1,
            {"attempt": attempt, "outcome": outcome},
            correlation_id,
        )


def _hand_to_owner(engine: Engine, publication_id: str, detail: str, correlation_id: str) -> None:
    """The manual repair queue: a row a person must look at, named as such and not asked again."""
    with Session(engine) as session, session.begin():
        record = session.get(PublicationRecord, publication_id)
        if record is None:
            return
        previous = record.status
        record.status = "NEEDS_RECONCILIATION"
        record.error_detail = detail
        event = append_event(
            session,
            "publishing.reconcile_exhausted",
            "publication_record",
            publication_id,
            1,
            {"previous_status": previous, "detail": detail},
            correlation_id,
        )
        record.event_id = event.event_id


def _reconcile_publications(
    engine: Engine,
    publisher_for: PublisherResolver,
    max_attempts: int,
    correlation_id: str,
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "checked": 0,
        "reconciled_published": 0,
        "reconciled_not_found": 0,
        "retry_reconciled": 0,
        "retry_uploaded": 0,
        "retry_failed": 0,
        "still_unknown": 0,
        "handed_to_owner": 0,
        "no_publisher": 0,
        "errored": 0,
    }
    reasons: list[dict[str, str]] = []

    with Session(engine) as session:
        rows = session.scalars(
            select(PublicationRecord)
            .where(PublicationRecord.status.in_(UNCERTAIN_STATES))
            .order_by(PublicationRecord.created_at)
            .limit(PUBLICATIONS_PER_PASS)
        ).all()
        pending: list[dict[str, Any]] = [
            {
                "id": row.id,
                "channel_id": row.channel_id,
                "status": row.status,
                "remote_video_id": row.remote_video_id,
                "attempts": _attempts_so_far(session, row.id),
            }
            for row in rows
        ]

    for item in pending:
        counts["checked"] += 1
        publication_id = str(item["id"])
        attempts = int(item["attempts"])

        if item["status"] == "REMOTE_UNKNOWN" and not item["remote_video_id"]:
            # YouTube's UNKNOWN carries no id — the stream was interrupted before the platform
            # named the video — and the existing reconciliation can only ask about an id. The
            # row would stay REMOTE_UNKNOWN for as long as the studio ran; it is the Owner's.
            _hand_to_owner(
                engine,
                publication_id,
                "Încărcarea s-a întrerupt înainte ca platforma să numească videoclipul; "
                "studioul nu poate verifica singur dacă există. Verifică pe canal și "
                "reia sau închide publicarea.",
                correlation_id,
            )
            counts["handed_to_owner"] += 1
            continue

        if attempts >= max_attempts:
            _hand_to_owner(
                engine,
                publication_id,
                f"Platforma nu a răspuns la {attempts} încercări de verificare; studioul nu "
                "mai încearcă singur. Verifică pe canal dacă videoclipul există.",
                correlation_id,
            )
            counts["handed_to_owner"] += 1
            continue

        try:
            provider = publisher_for(str(item["channel_id"]))
        except NoPublisher as exc:
            counts["no_publisher"] += 1
            reasons.append({"publication_id": publication_id, "reason": str(exc)})
            continue
        if provider is None:
            counts["no_publisher"] += 1
            reasons.append(
                {"publication_id": publication_id, "reason": "Niciun cont de publicare."}
            )
            continue

        attempt = attempts + 1
        try:
            if item["status"] == "REMOTE_UNKNOWN":
                result = reconcile_publication(engine, publication_id, provider, correlation_id)
            else:
                # FAILED_RETRYABLE: the retry path asks the platform by idempotency key before
                # it uploads, and stops if the platform cannot say. Never a blind re-upload.
                result = execute_publication(engine, provider, publication_id, correlation_id)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the pass
            detail = f"{type(exc).__name__}: {exc}"[:500]
            counts["errored"] += 1
            reasons.append({"publication_id": publication_id, "reason": detail})
            _record_attempt(engine, publication_id, attempt, f"ERROR {detail}", correlation_id)
            logger.error("watchdog_reconcile_failed", extra={"publication_id": publication_id})
            continue

        status = str(result["status"])
        if status in ("PUBLISHED", "PUBLISHED_SIMULATED"):
            if item["status"] == "REMOTE_UNKNOWN":
                counts["reconciled_published"] += 1
            else:
                # `execute_publication` writes one event when the platform already held the
                # video and another when it uploaded; the same error_detail for both. The
                # event under this pass's correlation is the honest source of which road ran.
                with Session(engine) as session:
                    suppressed = session.scalar(
                        select(func.count())
                        .select_from(DomainEvent)
                        .where(
                            DomainEvent.aggregate_id == publication_id,
                            DomainEvent.event_type == "publishing.retry_reconciled",
                            DomainEvent.correlation_id == correlation_id,
                        )
                    )
                counts["retry_reconciled" if suppressed else "retry_uploaded"] += 1
        elif status == "REMOTE_UNKNOWN":
            counts["still_unknown"] += 1
        elif status == "FAILED_RETRYABLE":
            if item["status"] == "REMOTE_UNKNOWN":
                counts["reconciled_not_found"] += 1
            else:
                counts["still_unknown"] += 1
        else:
            counts["retry_failed"] += 1
            reasons.append(
                {"publication_id": publication_id, "reason": str(result.get("error_detail"))}
            )
        _record_attempt(engine, publication_id, attempt, status, correlation_id)

    return {**counts, "reasons": reasons}


# -------------------------------------------------------------------------------- leases --


def _lapsed_leases(engine: Engine) -> dict[str, Any]:
    """Report leases that expired without a completion. The queue reclaims them itself."""
    now = utc_now()
    with Session(engine) as session:
        task_ids = list(
            session.scalars(
                select(TaskQueueItem.id).where(
                    TaskQueueItem.status.in_(["CLAIMED", "RUNNING"]),
                    TaskQueueItem.lease_expires_at < now,
                )
            )
        )
    return {"expired": len(task_ids), "task_ids": task_ids}


# ------------------------------------------------------------------------------ the pass --


def run_watchdog(
    engine: Engine,
    settings: Any,
    correlation_id: str = "",
    *,
    publisher_for: PublisherResolver | None = None,
) -> dict[str, Any]:
    """One pass: fail stuck renders, reconcile publications, report leases, free stale holds.

    Thresholds are read through `getattr` so the pass works before the settings carry them.
    `publisher_for` maps a channel id to the account that can be asked about it; the default
    reads the channel's binding and the vault, as the publish stage does.
    """
    correlation = correlation_id or str(uuid4())
    if _autonomy_stopped(engine):
        result = {
            "status": "SKIPPED",
            "reason": "Studioul este oprit (STOP AUTONOMIE); paznicul nu schimbă nimic.",
            "renders": {"failed": 0, "failed_ids": [], "rendering": 0},
            "publications": {"checked": 0, "reasons": []},
            "leases": {"expired": 0, "task_ids": []},
            "reservations": {"released": [], "ttl_seconds": 0, "cutoff": None},
            "correlation_id": correlation,
        }
        logger.info("watchdog_skipped", extra={"reason": "autonomy_stopped"})
        return result

    threshold = int(
        getattr(settings, "render_stuck_after_seconds", DEFAULT_RENDER_STUCK_AFTER_SECONDS)
    )
    max_attempts = int(getattr(settings, "reconcile_max_attempts", DEFAULT_RECONCILE_MAX_ATTEMPTS))

    renders = _fail_stuck_renders(engine, threshold, correlation)
    publications = _reconcile_publications(
        engine,
        publisher_for or _default_publisher_for(engine, settings),
        max_attempts,
        correlation,
    )
    leases = _lapsed_leases(engine)
    # The fourth thing a dead process leaves behind. A film holds the money it is about to
    # spend (`reserve_spend`) and releases or settles it when the render ends; a process
    # killed under a hold leaves the day's budget pledged to a film nobody is making, and
    # every later film is refused for money that was never spent. Same threshold logic as
    # the renders above: read through the settings when they carry it.
    reservations = release_stale_reservations(
        engine,
        ttl_seconds=int(
            getattr(settings, "reservation_ttl_seconds", DEFAULT_RESERVATION_TTL_SECONDS)
        ),
        correlation_id=correlation,
    )

    result = {
        "status": "COMPLETED",
        "reason": "",
        "renders": renders,
        "publications": publications,
        "leases": leases,
        "reservations": reservations,
        "correlation_id": correlation,
    }
    logger.info(
        "watchdog_pass",
        extra={
            "renders_failed": renders["failed"],
            "publications_checked": publications["checked"],
            "publications_handed_to_owner": publications["handed_to_owner"],
            "leases_expired": leases["expired"],
            "reservations_released": len(reservations["released"]),
        },
    )
    return result
