"""The watchdog: the part of the studio that notices a day was interrupted.

A render is a row marked RENDERING, a process running FFmpeg, and a row marked COMPLETED or
FAILED when the process comes back. Kill the process — a reboot, a closed terminal, a crash —
and the row stays RENDERING forever, with nothing left to change it. Measured on a copy of the
live database: two `video_render_job` rows had been RENDERING since 2026-09-12 with `finished_at`
NULL. In the same way, an upload whose answer was lost leaves a publication in REMOTE_UNKNOWN,
and `reconcile_publication` — written for exactly that — had no caller outside the tests.

One pass of the watchdog does these things and records each. It fails renders that have made
no progress past a threshold, with the reason on the row and an event, the way the assembler
itself records a failure. It sends every uncertain publication through the reconciliation that
already exists, a bounded number of times, and then hands the row to the Owner rather than
asking a platform that does not answer forever. And it reports task leases that have lapsed
without touching them: the queue re-claims an expired lease that has attempts left on its own
(`claim_task`), the worker dead-letters one that has none (`sweep_interrupted_tasks`), and a
third mechanism doing either would be two owners of one row. And it releases the money a
film held and never spent: the media stage reserves what a render is estimated to cost and
settles the hold when the cost rows are in the books, so a process killed in between leaves
the day's budget pledged to a film nobody is making. And it collects the paid tasks a vendor
accepted and nobody collected (2026-10-01): a still or a shot is written SUBMITTED, with the
vendor's task id, the moment the vendor accepts it; a poll that ran out of time, a failed
download or a dead process leaves it so. Each is asked about by its id (a GET, which buys
nothing): finished, it is downloaded into its take, PAID; failed, REFUSED; still unknown a day
after it was bought, LOST, with one letter to the Owner per pass. Never a POST. And it closes a
day nobody is running any more (2026-10-02, REL-03): a day writes its row RUNNING when it
begins, so a process that died under it leaves that row behind; when the day's queue task no
longer holds a live lease (or, for a day started without the queue, nothing moved for longer
than a lease) the row becomes INTERRUPTED at the stage it was in, with one letter to the Owner.
The day is not run again: what it bought stays bought. And it takes back a film's purchase
lease whose holder is gone (2026-10-03): a holder renews its lease while it buys, so a lease
that lapsed was left by a process that stopped under it; the film is freed, the budget hold
it took is released, and the Owner gets one letter saying what his spent yes bought according
to the balance readings and that nothing is bought again unless he presses again (a live
purchase, which renews, is never touched). And it keeps publishing honest
(2026-10-02, PUB-01/PUB-08): a publication left STARTED past `publish_stuck_after_seconds`
(a process that died mid-upload) becomes REMOTE_UNKNOWN and is reconciled like any other; an
uncertain publication YouTube never named is asked of the channel's own uploads by its exact
title; and a published video is looked at for six hours, until YouTube says its processing
ended, so a rejected or failed one is FAILED_FINAL with a letter instead of PUBLISHED.

What it will not do. It changes nothing while the Owner's autonomy stop is set — safe mode sets
that stop too — because a stopped studio is a studio in which nothing moves, including repair.
And it never uploads on a guess: the retry path it reuses asks the platform first.

The repairs added since 2026-10-09 register from their own files (`app.workflows.passes`) and
run after the parts above, in their declared order, each in its own try; also when one of the
first parts raised, whose exception still ends the pass.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.economy.budget import DEFAULT_RESERVATION_TTL_SECONDS, release_stale_reservations
from app.media.models import SceneTake, VideoRenderJob
from app.models import DomainEvent, OwnerPolicy
from app.providers.publishing_base import PublishingProvider
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    REMOTE_SETTLED_STATES,
    channel_bindings,
    check_processing,
    execute_publication,
    hand_to_owner,
    mark_stale_started,
    reconcile_by_title,
    reconcile_publication,
    upload_started_at,
)
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem
from app.workflows.passes import PASSES, WatchdogContext, WatchdogPass, registered_passes

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
#: The Owner's own answer about a row the studio could not settle; attempts restart after it.
OWNER_RESOLVED_EVENT = "publishing.resolved_by_owner"

#: The states `reconcile_publication` and `execute_publication` were written for.
UNCERTAIN_STATES = ("REMOTE_UNKNOWN", "FAILED_RETRYABLE")

#: An upload of a short takes minutes; one STARTED for an hour is a process that is no longer
#: there. Read through `settings.publish_stuck_after_seconds`.
DEFAULT_PUBLISH_STUCK_AFTER_SECONDS = 3600

#: A cut upload whose video YouTube never named is asked of the channel by title only once its
#: upload began this long ago: a finished upload is listed in the channel's uploads within
#: moments, and asking too early could read "not there" for a video still being written.
RECONCILE_BY_TITLE_AFTER_SECONDS = 15 * 60

#: How long after the upload YouTube's processing is followed (PUB-08), and how many published
#: videos are looked at per pass.
PROCESSING_WINDOW_SECONDS = 6 * 3600
PROCESSING_PER_PASS = 20

PublisherResolver = Callable[[str], PublishingProvider | None]
#: The adapter that may be asked about a SUBMITTED take's task (None: nobody, for now).
CollectorResolver = Callable[[SceneTake], Any]


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
    """The attempts since the Owner last settled the row by hand (`resolve_publication`).

    Counted from his answer on: the attempts before it were the studio failing to ask, and
    his «Nu există» is what makes the row retryable again. Counted from the start, a row he
    answered went straight back to him on the next pass, with a second letter."""
    since = (
        session.scalar(
            select(func.max(DomainEvent.sequence)).where(
                DomainEvent.aggregate_id == publication_id,
                DomainEvent.event_type == OWNER_RESOLVED_EVENT,
            )
        )
        or 0
    )
    return int(
        session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(
                DomainEvent.aggregate_id == publication_id,
                DomainEvent.event_type == RECONCILE_ATTEMPT_EVENT,
                DomainEvent.sequence > since,
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
    """The manual repair queue: a row a person must look at, named as such and not asked
    again, with one letter to the Owner (`hand_to_owner`)."""
    hand_to_owner(engine, publication_id, detail, correlation_id)


def _reconcile_publications(
    engine: Engine,
    publisher_for: PublisherResolver,
    max_attempts: int,
    correlation_id: str,
    stuck_after: int = DEFAULT_PUBLISH_STUCK_AFTER_SECONDS,
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
        "stale_started": 0,
        "waiting": 0,
    }
    reasons: list[dict[str, str]] = []

    # A STARTED row past its time is an upload whose process is gone (PUB-01): it is made
    # REMOTE_UNKNOWN here and reconciled below, in this same pass.
    counts["stale_started"] = len(mark_stale_started(engine, stuck_after, correlation_id))

    now = datetime.now(UTC)
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
                "upload_age": (now - upload_started_at(session, row)).total_seconds(),
            }
            for row in rows
        ]

    for item in pending:
        publication_id = str(item["id"])
        attempts = int(item["attempts"])
        by_title = item["status"] == "REMOTE_UNKNOWN" and not item["remote_video_id"]

        if by_title and float(item["upload_age"]) < RECONCILE_BY_TITLE_AFTER_SECONDS:
            # YouTube's UNKNOWN carries no id: the stream was cut before the platform named
            # the video. The channel's uploads are asked by title once a finished upload would
            # be listed there; until then the row waits, asked nothing.
            counts["waiting"] += 1
            continue
        counts["checked"] += 1

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
            if by_title:
                result = reconcile_by_title(engine, publication_id, provider, correlation_id)
            elif item["status"] == "REMOTE_UNKNOWN":
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


def _follow_processing(
    engine: Engine, publisher_for: PublisherResolver, correlation_id: str
) -> dict[str, Any]:
    """Each video published in the last six hours whose processing YouTube has not finished,
    asked once (videos.list, 1 quota unit): rejected, failed or deleted becomes FAILED_FINAL
    with a letter; processed ends the following (PUB-08)."""
    since = (datetime.now(UTC).timestamp()) - PROCESSING_WINDOW_SECONDS
    counts: dict[str, int] = {"checked": 0, "processed": 0, "rejected": 0, "unreadable": 0}
    with Session(engine) as session:
        rows = [
            (row.id, row.channel_id, row.published_at)
            for row in session.scalars(
                select(PublicationRecord)
                .where(
                    PublicationRecord.status == "PUBLISHED",
                    PublicationRecord.remote_video_id.is_not(None),
                    PublicationRecord.published_at.is_not(None),
                )
                .order_by(PublicationRecord.published_at.desc())
            )
            if (row.remote_upload_status or "").lower() not in REMOTE_SETTLED_STATES
        ]
    for publication_id, channel_id, published_at in rows:
        if counts["checked"] >= PROCESSING_PER_PASS:
            break
        if _parse(str(published_at)).timestamp() < since:
            continue
        try:
            provider = publisher_for(str(channel_id))
        except NoPublisher:
            counts["unreadable"] += 1
            continue
        if provider is None:
            counts["unreadable"] += 1
            continue
        counts["checked"] += 1
        try:
            said = check_processing(engine, publication_id, provider, correlation_id)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the pass
            logger.error(
                "watchdog_processing_failed",
                extra={"publication_id": publication_id, "error": type(exc).__name__},
            )
            counts["unreadable"] += 1
            continue
        if said == "processed":
            counts["processed"] += 1
        elif said in ("rejected", "failed", "deleted"):
            counts["rejected"] += 1
        elif said == "UNREADABLE":
            counts["unreadable"] += 1
    return counts


# -------------------------------------------------------------------------------- leases --


def _lapsed_leases(engine: Engine) -> dict[str, Any]:
    """Report leases that expired without a completion. The queue reclaims those with
    attempts left; the worker's sweep dead-letters the rest (INTERRUPTED)."""
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


# --------------------------------------------------------------------- paid tasks --


def _default_collector_for(engine: Engine) -> CollectorResolver:
    """The Runway connection the studio buys from, read from the vault on first use.

    Asking about a task needs the account's key and nothing else (GET /v1/tasks/{id}); the
    adapter is built once per pass, and only when a SUBMITTED take exists.
    """
    from pathlib import Path  # noqa: PLC0415

    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.media.shooting_sheet import (  # noqa: PLC0415 - media imports workflows
        connection_account,
        runway_connection_id,
    )

    built: dict[str, Any] = {}

    def resolve(_take: SceneTake) -> Any:
        from app.integrations.models import Integration  # noqa: PLC0415
        from app.providers.runpod.jobs import GenerationJob  # noqa: PLC0415
        from app.providers.runpod.wiring import connection  # noqa: PLC0415

        with Session(engine) as session:
            job = session.scalar(
                select(GenerationJob).where(
                    GenerationJob.remote_job_id == _take.remote_task_id,
                    GenerationJob.project_id == _take.storyboard_id,
                    GenerationJob.scene_id == str(_take.scene_number),
                )
            )
            if job is not None:
                identity = str(job.integration_id)
                if identity not in built:
                    integration = (
                        session.get(Integration, job.integration_id) if job.integration_id else None
                    )
                    if integration is None or integration.status not in (
                        "VERIFIED",
                        "ACCESS_VERIFIED",
                    ):
                        return None
                    vault = CredentialVault(
                        Path(str(engine.url.database)).with_suffix(".credentials.key")
                    )
                    built[identity] = connection(engine, vault, integration)
                return built[identity]
        if "adapter" not in built:
            vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
            built["adapter"] = connection_account(engine, vault, runway_connection_id(engine))
        return built["adapter"]

    return resolve


def _collect_paid_tasks(
    engine: Engine,
    collector_for: CollectorResolver,
    correlation_id: str,
    storage_root: Any = None,
) -> dict[str, Any]:
    """Every SUBMITTED take asked about by its task id; a summary of what became of each.
    A collected output is written under the Owner's media root (STUDIO_MEDIA_ROOT)."""
    from app.media import assembler  # noqa: PLC0415
    from app.media.shooting_sheet import held_films  # noqa: PLC0415

    # A film whose buyer is at work (its purchase lease held, renewed by a live holder) polls
    # its own tasks: collected here beside it, a task's candidates would land twice. Its
    # tasks wait for the lease to be given back, or reclaimed above from a buyer that is gone.
    outcomes = assembler.collect_submitted_takes(
        engine,
        collector_for=collector_for,
        correlation_id=correlation_id,
        storage_root=storage_root,
        exclude_storyboards=held_films(engine),
    )
    return {
        "checked": len(outcomes),
        "paid": sum(1 for item in outcomes if item["status"] == "PAID"),
        "refused": sum(1 for item in outcomes if item["status"] == "REFUSED"),
        "lost": sum(1 for item in outcomes if item["status"] == "LOST"),
        "waiting": sum(1 for item in outcomes if item["status"] == "SUBMITTED"),
        "take_ids": [item["take_id"] for item in outcomes],
    }


# ------------------------------------------------------------------ intermediates --


def _sweep_failed_intermediates(engine: Engine, settings: Any, correlation_id: str) -> dict:
    """The shot and card clips of renders that FAILED before quality control, deleted once
    they are older than the Owner's setting: only when he turned the sweep on (REL-08)."""
    if not getattr(settings, "sweep_failed_intermediates", False):
        return {"status": "OFF", "files": [], "bytes": 0}
    from app.media import assembler  # noqa: PLC0415 - media imports workflows

    swept = assembler.sweep_failed_intermediates(
        engine,
        storage_root=assembler.media_root(settings),
        older_than_days=float(getattr(settings, "failed_intermediates_days", 7)),
        correlation_id=correlation_id,
    )
    return {"status": "SWEPT", "files": swept["files"], "bytes": swept["bytes"]}


# --------------------------------------------------------------------------- days --


def _interrupted_days(engine: Engine, correlation_id: str) -> dict[str, Any]:
    """Close every RUNNING day whose process is gone; the days closed, with their letters."""
    from app.runbook.services import interrupt_stale_runs  # noqa: PLC0415 - runbook imports
    from app.workflows.worker import TASK_LEASE_SECONDS  # noqa: PLC0415 - worker imports runbook

    closed = interrupt_stale_runs(
        engine, lease_seconds=TASK_LEASE_SECONDS, correlation_id=correlation_id
    )
    return {"interrupted": [record["run_id"] for record in closed]}


# --------------------------------------------------------------- registered passes --


#: The registry modules (and their errors) one event already named in this process: a module
#: that did not import is said once per boot, not every few minutes (2026-10-09).
_REPORTED_LOAD_ERRORS: set[tuple[str, str]] = set()

#: The package of the card producers (`app.decisions.producers`), named in the events.
_PRODUCERS_PACKAGE = "app.decisions.producers"


def _stop_pressed(engine: Engine) -> bool:
    """The Owner's stop, read again before each registered pass; unreadable reads as pressed."""
    try:
        return _autonomy_stopped(engine)
    except Exception as exc:  # noqa: BLE001 - a stop nobody can read is not a go
        logger.error("watchdog_stop_unreadable", extra={"error": type(exc).__name__})
        return True


def _report_load_errors(engine: Engine, load_errors: Mapping[str, str], correlation: str) -> None:
    """One `studio.registry_module_failed` event per module that did not import, once per boot.

    Review of 2026-10-09: the worker keeps nothing of the watchdog's answer, so `load_errors`
    in the result alone reached nobody. A producer that did not import leaves its cards unable
    to close (UNREADABLE) and his accept refused (UNKNOWN_APPLY_RO); a pass module that did
    not, a repair that never runs. The studio says so where it is read: here, and on the
    `watchdog_pass` log line of every pass."""
    fresh = sorted(
        (module, error)
        for module, error in load_errors.items()
        if (module, error) not in _REPORTED_LOAD_ERRORS
    )
    if not fresh:
        return
    if _stop_pressed(engine):
        # The watchdog writes nothing while he has the studio stopped; the first pass after
        # he lets it go writes the event (the log line names the module meanwhile).
        return
    try:
        with Session(engine) as session, session.begin():
            for module, error in fresh:
                append_event(
                    session,
                    "studio.registry_module_failed",
                    "studio_registry",
                    # A module name can be longer than the 36 characters the column keeps.
                    str(uuid5(NAMESPACE_URL, f"amn-registry:{module}")),
                    1,
                    {
                        "module": module,
                        "error": error,
                        "registry": (
                            "decision_producers"
                            if module.startswith(_PRODUCERS_PACKAGE)
                            else "watchdog_passes"
                        ),
                    },
                    correlation,
                )
    except Exception as exc:  # noqa: BLE001 - a report, never a reason to lose the pass
        logger.error("watchdog_registry_report_failed", extra={"error": type(exc).__name__})
        return
    _REPORTED_LOAD_ERRORS.update(fresh)


def _run_registered_passes(
    context: WatchdogContext,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Every pass registered in `app.workflows.passes`, in its declared order, each in its own
    try: (each pass's result by its name, what ran). A pass that raises, or answers with
    something that is not a dict, reports its ``on_error`` shape with ``"error": True``, and
    the next pass still runs, as the built-in parts above do for each other.

    The Owner's stop is read again before each pass (review of 2026-10-09): the built-in parts
    above can take minutes (the paid collection asks the vendors), and a stop he pressed
    meanwhile, or that a pass before set, skips every pass still to run (``skipped``)."""
    results: dict[str, dict[str, Any]] = {}
    ran: list[dict[str, Any]] = []
    failed: list[str] = []
    skipped: list[str] = []
    passes: list[WatchdogPass] = []
    try:
        passes = registered_passes()
        pass_errors = dict(PASSES.errors)
    except Exception as exc:  # noqa: BLE001 - the built-in parts' results must not be lost
        logger.error("watchdog_passes_unavailable", extra={"error": type(exc).__name__})
        pass_errors = {PASSES.package: f"{type(exc).__name__}: {exc}"[:500]}
    for entry in passes:
        if skipped or _stop_pressed(context.engine):
            skipped.append(entry.name)
            continue
        started = time.monotonic()
        status = "OK"
        try:
            answer = entry.function(context)
            if not isinstance(answer, Mapping):
                raise TypeError(f"the pass answered {type(answer).__name__}, not a dict")
            outcome = dict(answer)
        except Exception as exc:  # noqa: BLE001 - one pass's failure must not lose the others'
            logger.error(
                "watchdog_registered_pass_failed",
                extra={"pass": entry.name, "error": type(exc).__name__},
                exc_info=exc,
            )
            outcome = {**dict(entry.on_error), "error": True, "error_type": type(exc).__name__}
            status = "FAILED"
            failed.append(entry.name)
        results[entry.name] = outcome
        ran.append(
            {
                "name": entry.name,
                "order": entry.order,
                "status": status,
                "ms": int((time.monotonic() - started) * 1000),
            }
        )
    if skipped:
        logger.info("watchdog_registered_passes_stopped", extra={"skipped": list(skipped)})
    # A card producer that did not import leaves its cards unable to apply or close (they
    # fail closed); the watchdog names it each pass, beside a pass module that did not.
    try:
        from app.decisions.producers import PRODUCERS  # noqa: PLC0415

        PRODUCERS.load()
        producer_errors = dict(PRODUCERS.errors)
    except Exception as exc:  # noqa: BLE001 - a report, never a reason to lose the pass
        producer_errors = {_PRODUCERS_PACKAGE: f"{type(exc).__name__}: {exc}"[:500]}
    load_errors = {**pass_errors, **producer_errors}
    _report_load_errors(context.engine, load_errors, context.correlation_id)
    return results, {
        "ran": ran,
        "failed": failed,
        "skipped": skipped,
        "load_errors": load_errors,
    }


def _passes_after_a_failed_part(context: WatchdogContext, failure: Exception) -> None:
    """The registered passes, when one of the first built-in parts raised (they have no try
    of their own, and their exception stays the watchdog's answer).

    Review of 2026-10-09: the registered passes carry the money repairs of the self-repair
    plan (unbooked spend, GPU receipts, held RunPod scenes). A part that raised before them (a
    locked database in `release_stale_reservations`, an unreadable publisher binding) skipped
    every one, every cycle while the cause lasted, and the result that would have said so was
    never built. Each still runs in its own try with the stop read again (a stop nobody can
    read skips them all); what ran is on this log line, and nothing here may hide the part's
    own exception."""
    try:
        _results, passes = _run_registered_passes(context)
        logger.error(
            "watchdog_built_in_part_failed",
            extra={
                "error": type(failure).__name__,
                "registered_passes_ran": [entry["name"] for entry in passes["ran"]],
                "registered_passes_failed": list(passes["failed"]),
                "registered_passes_skipped": list(passes["skipped"]),
                "registered_load_errors": sorted(passes["load_errors"]),
            },
        )
    except Exception as exc:  # noqa: BLE001 - the part's exception is the one that goes on
        logger.error(
            "watchdog_built_in_part_failed",
            extra={"error": type(failure).__name__, "passes_error": type(exc).__name__},
        )


# ------------------------------------------------------------------------------ the pass --


def run_watchdog(
    engine: Engine,
    settings: Any,
    correlation_id: str = "",
    *,
    publisher_for: PublisherResolver | None = None,
    collector_for: CollectorResolver | None = None,
) -> dict[str, Any]:
    """One pass: fail stuck renders, reconcile publications, report leases, free stale holds,
    collect the paid tasks nobody collected, close the days nobody is running, and (when the
    Owner turned it on) delete the intermediates of renders that failed long ago.

    Thresholds are read through `getattr` so the pass works before the settings carry them.
    `publisher_for` maps a channel id to the account that can be asked about it; the default
    reads the channel's binding and the vault, as the publish stage does. `collector_for`
    gives the adapter a SUBMITTED take's task may be asked about; the default is the studio's
    Runway connection, from the vault.
    """
    correlation = correlation_id or str(uuid4())
    if _autonomy_stopped(engine):
        result = {
            "status": "SKIPPED",
            "reason": "Studioul este oprit (STOP AUTONOMIE); paznicul nu schimbă nimic.",
            "renders": {"failed": 0, "failed_ids": [], "rendering": 0},
            "publications": {"checked": 0, "reasons": []},
            "processing": {"checked": 0, "processed": 0, "rejected": 0, "unreadable": 0},
            "leases": {"expired": 0, "task_ids": []},
            "reservations": {"released": [], "ttl_seconds": 0, "cutoff": None},
            "takes": {"checked": 0, "paid": 0, "refused": 0, "lost": 0, "waiting": 0},
            "film_leases": {"reclaimed": [], "letters": []},
            "days": {"interrupted": []},
            "intermediates": {"status": "OFF", "files": [], "bytes": 0},
            "correlation_id": correlation,
        }
        logger.info("watchdog_skipped", extra={"reason": "autonomy_stopped"})
        return result

    threshold = int(
        getattr(settings, "render_stuck_after_seconds", DEFAULT_RENDER_STUCK_AFTER_SECONDS)
    )
    max_attempts = int(getattr(settings, "reconcile_max_attempts", DEFAULT_RECONCILE_MAX_ATTEMPTS))

    stuck_after = int(
        getattr(settings, "publish_stuck_after_seconds", DEFAULT_PUBLISH_STUCK_AFTER_SECONDS)
    )

    # These first parts have no try of their own: one that raises ends the watchdog with its
    # exception, as it always did (the worker records the task FAILED). The registered passes
    # still run first (`_passes_after_a_failed_part`, review of 2026-10-09).
    try:
        renders = _fail_stuck_renders(engine, threshold, correlation)
        resolver = publisher_for or _default_publisher_for(engine, settings)
        publications = _reconcile_publications(
            engine, resolver, max_attempts, correlation, stuck_after
        )
        try:
            processing = _follow_processing(engine, resolver, correlation)
        except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
            logger.error("watchdog_processing_pass_failed", extra={"error": type(exc).__name__})
            processing = {"checked": 0, "processed": 0, "rejected": 0, "unreadable": 0, "error": 1}
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
    except Exception as exc:
        _passes_after_a_failed_part(WatchdogContext(engine, settings, correlation), exc)
        raise

    # A film's purchase lease whose holder is gone: freed, its hold released, the Owner told.
    # Before the collection below, so his letter says what was still at the vendor.
    try:
        from app.media.shooting_sheet import reclaim_abandoned_leases  # noqa: PLC0415

        film_leases = reclaim_abandoned_leases(
            engine, correlation_id=correlation, timezone=getattr(settings, "timezone", None)
        )
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_film_leases_failed", extra={"error": type(exc).__name__})
        film_leases = {"reclaimed": [], "letters": [], "error": True}

    # The fifth: a task the vendor accepted, and may have billed, that nobody collected.
    try:
        takes = _collect_paid_tasks(
            engine,
            collector_for or _default_collector_for(engine),
            correlation,
            getattr(settings, "media_root", None),
        )
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_takes_failed", extra={"error": type(exc).__name__})
        takes = {"checked": 0, "paid": 0, "refused": 0, "lost": 0, "waiting": 0, "error": True}

    # The sixth: a day left RUNNING by a process that died.
    try:
        days = _interrupted_days(engine, correlation)
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_days_failed", extra={"error": type(exc).__name__})
        days = {"interrupted": [], "error": True}

    # A scene held for the Owner only because the vendor refused a request the studio itself
    # sent wrong (2026-10-04: the Nepal test shot's keyframe ratio): released once, on the
    # books, so the scene is planned again on its model. Reads and one event; 0 credits.
    defect_holds: dict[str, Any]
    try:
        from app.media.assembler import release_studio_defect_holds  # noqa: PLC0415

        defect_holds = {"released": release_studio_defect_holds(engine, correlation_id=correlation)}
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_defect_holds_failed", extra={"error": type(exc).__name__})
        defect_holds = {"released": [], "error": True}

    # A scene held by a RunPod /run that got no job id (2026-10-09): released when a later
    # round with the same keys proved nothing was queued or made; otherwise, when its GPU
    # session recorded a clean off but not that proof, the Owner's card, once per hold (his
    # yes releases it). Local reads and writes; nothing sent, nothing bought.
    unsent_holds: dict[str, Any]
    try:
        from app.media.runpod_unsent import propose_release_cards  # noqa: PLC0415

        unsent_holds = propose_release_cards(engine, correlation_id=correlation)
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_runpod_unsent_failed", extra={"error": type(exc).__name__})
        unsent_holds = {"cards": [], "released": [], "error": True}

    # A letter to the Owner asking about a question that no longer waits (answered, withdrawn,
    # expired) or about a film a newer letter has moved past: closed (2026-10-09, he closed six
    # by hand in one afternoon). Local writes; nothing sent, nothing bought.
    answered_letters: dict[str, Any]
    try:
        from app.media.answered_letters import retire_answered_letters  # noqa: PLC0415

        answered_letters = retire_answered_letters(engine, correlation)
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_answered_letters_failed", extra={"error": type(exc).__name__})
        answered_letters = {
            "answered": [],
            "superseded": [],
            "moved_on": [],
            "lists": [],
            "error": True,
        }

    # The seventh, only when the Owner turned it on: a failed render's shots, deleted.
    try:
        intermediates = _sweep_failed_intermediates(engine, settings, correlation)
    except Exception as exc:  # noqa: BLE001 - one part's failure must not lose the others'
        logger.error("watchdog_sweep_failed", extra={"error": type(exc).__name__})
        intermediates = {"status": "FAILED", "files": [], "bytes": 0, "error": True}

    # The repairs registered from their own files (2026-10-09), after every part above.
    registered, passes = _run_registered_passes(WatchdogContext(engine, settings, correlation))

    result = {
        "status": "COMPLETED",
        "reason": "",
        "renders": renders,
        "publications": publications,
        "processing": processing,
        "leases": leases,
        "reservations": reservations,
        "takes": takes,
        "film_leases": film_leases,
        "days": days,
        "intermediates": intermediates,
        "defect_holds": defect_holds,
        "runpod_unsent_holds": unsent_holds,
        "answered_letters": answered_letters,
        "correlation_id": correlation,
        # A registered pass's name is never a key above (`BUILT_IN_RESULT_KEYS`).
        **registered,
        "passes": passes,
    }
    logger.info(
        "watchdog_pass",
        extra={
            "renders_failed": renders["failed"],
            "publications_checked": publications["checked"],
            "publications_handed_to_owner": publications["handed_to_owner"],
            "leases_expired": leases["expired"],
            "reservations_released": len(reservations["released"]),
            "takes_checked": takes["checked"],
            "takes_lost": takes["lost"],
            "film_leases_reclaimed": len(film_leases["reclaimed"]),
            "days_interrupted": len(days["interrupted"]),
            "intermediates_swept": len(intermediates["files"]),
            "defect_holds_released": len(defect_holds["released"]),
            "runpod_unsent_cards": len(unsent_holds["cards"]),
            "runpod_unsent_released": len(unsent_holds.get("released") or []),
            "registered_passes_ran": len(passes["ran"]),
            "registered_passes_failed": len(passes["failed"]),
            "registered_passes_skipped": len(passes["skipped"]),
            # Every pass, while a registry module does not import (the result reaches no one).
            "registered_load_errors": sorted(passes["load_errors"]),
        },
    )
    return result
