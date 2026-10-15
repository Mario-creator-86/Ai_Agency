import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agents.models import ProviderRecord
from app.agents.router import create_agents_router, create_providers_router
from app.analytics.router import create_analytics_router
from app.config import ROOT, Settings
from app.db import create_db_engine
from app.decisions.router import create_decisions_router
from app.decisions.seed import seed_owner_decisions
from app.decisions.services import refresh_owner_decisions
from app.economy.prices import price_lookup
from app.economy.router import create_economy_router
from app.factual.router import create_factual_router
from app.integrations.discovery import refresh_due_catalogs
from app.integrations.router import create_settings_router
from app.integrations.services import check_vault_at_startup, load_registry, vault_health
from app.integrations.vault import CredentialVault
from app.local_session import create_local_session_router
from app.logging import configure_logging, log_directory
from app.media.router import create_media_router
from app.office.kept_frame import create_kept_frame_router
from app.office.router import create_office_router
from app.office.stream import register_stream_gateway
from app.office.unreal import remote_control_target, run_unreal_bridge
from app.operations import (
    new_operations,
    operations_reading,
    public_health,
    record_pass_end,
    record_pass_failure,
    record_pass_start,
)
from app.page_build import page_build
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
from app.providers.runpod.gpu_guard import guard_intervals, next_interval, run_gpu_guard
from app.providers.runpod.gpu_session import force_off
from app.providers.runpod.router import create_runpod_router
from app.publishing.router import create_publishing_router
from app.runbook.router import create_runbook_router
from app.runbook.services import clear_shutdown, request_shutdown
from app.runbook.stages import build_stage_runners
from app.runbook.weekly import WEEKLY_JOB_NAME
from app.schemas import (
    ApprovalDecisionCommand,
    ApprovalDecisionResult,
    ApprovalView,
    AutonomyModeCommand,
    EnvironmentCommand,
    PolicyCommand,
    PolicyResult,
)
from app.security import owner_key_matches, require_owner
from app.services import (
    ApprovalClosed,
    ApprovalMissing,
    AutonomyRefused,
    CommandConflict,
    PaidMediaApprovalCommand,
    PaidMediaApprovalRefused,
    PaidMediaApprovalResult,
    change_autonomy_mode,
    change_environment,
    change_paid_media_approval,
    change_stop,
    decide_approval,
    pending_approvals,
    read_events,
    read_instant,
    snapshot,
    studio_location,
)
from app.story.router import create_story_router
from app.workflows.publisher import ConnectionManager, dispatch_pending_outbox
from app.workflows.router import (
    create_scheduler_router,
    create_tasks_router,
    create_workflows_router,
    register_websocket_gateway,
)
from app.workflows.services import ensure_scheduled_job
from app.workflows.worker import (
    BACKUP,
    BACKUP_JOB_NAME,
    DAILY_JOB_NAME,
    DAILY_RUN,
    DIRECTOR_LOOP,
    DIRECTOR_LOOP_JOB_NAME,
    MODEL_RESEARCH,
    MODEL_RESEARCH_JOB_NAME,
    MODEL_REVIEW,
    MODEL_REVIEW_JOB_NAME,
    TRENDS_JOB_NAME,
    TRENDS_REFRESH,
    WATCHDOG,
    WATCHDOG_JOB_NAME,
    WorkerLock,
    acquire_worker_lock,
    build_task_handlers,
    worker_lock_path,
    worker_pass,
)
from app.workforce.router import create_workforce_router
from app.youtube.router import create_youtube_callback_router, create_youtube_router

logger = logging.getLogger("studio.api")
#: How long /health/ready trusts its last reading of the stored keys (it unwraps the key).
VAULT_HEALTH_TTL_S = 30.0

#: A file Vite built and named by its content: ``/assets/index-D49zCqy2.js``. Its bytes can never
#: change under that name (a change is a new name, and index.html points at the new one), so a
#: browser may keep it for a year without asking again. The art under ``/assets/hq/`` is copied
#: from ``frontend/public`` with its own, unhashed names and is NOT matched: the depth of the path
#: keeps it out.
HASHED_ASSET = re.compile(r"^assets/[^/]+-[A-Za-z0-9_-]{8}\.(?:js|css|woff2?|png|webp|jpe?g|svg)$")
#: The year a hashed file is kept, and the one header that says so.
IMMUTABLE = "public, max-age=31536000, immutable"
#: Everything else the page is made of (index.html, the icons, the HQ art and scene.json): kept,
#: but asked about on every use. StaticFiles answers the question with a 304 and no body when the
#: file is unchanged, so a return visit re-downloads nothing and a rebuilt file is seen at once.
REVALIDATE = "no-cache"


def static_cache_control(path: str) -> str:
    """The Cache-Control for one file of the built page, by its path inside frontend/dist."""
    return IMMUTABLE if HASHED_ASSET.match(path) else REVALIDATE


class PageFiles(StaticFiles):
    """The built page, served with the cache policy its files can bear.

    Until 2026-09-24 every response of this process said ``no-store``, the page's 8.7 MB of art
    included, so every visit downloaded all of it again before the first picture. The API keeps
    ``no-store`` (the request middleware forces it on ``/api/*``); only a file this class served
    with a 200 or a 304 carries a policy of its own.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # A socket on a path no route serves falls through to the page's files, which only
        # speak HTTP: Starlette asserted, printed a traceback and answered 500 on every retry
        # (the Owner's console, 2026-10-02). Refused with a policy close instead; its path is
        # logged at DEBUG only, without the query: a stranger's knock is not the studio's error.
        if scope["type"] == "websocket":
            logger.debug("websocket_unknown_path", extra={"path": str(scope.get("path", ""))[:200]})
            await send({"type": "websocket.close", "code": 1008})
            return
        await super().__call__(scope, receive, send)

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = static_cache_control(path.replace("\\", "/"))
        return response


@lru_cache(maxsize=1)
def expected_revision() -> str:
    """The head of the migration chain this code was written for, read from the migrations.

    It was a literal ('0048_production_sheet') that every new revision had to remember to
    change, and a test copied it. The chain itself is the truth: read once per process.
    """
    from alembic.config import Config  # noqa: PLC0415 - only the start needs it
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("The migration chain has no single head")
    return str(head)


#: What the Owner reads when the database is not the one this version needs. Romanian: it is
#: the first thing a buyer sees on a fresh install that skipped the bootstrap.
_BOOTSTRAP_HINT = "Rulează scripts/bootstrap.py cu această versiune a aplicației."


def database_revision(connection: Connection) -> str | None:
    """The revision the database is at; RuntimeError in the Owner's words when it has none.

    A file with no `alembic_version` table is a studio nobody bootstrapped. The raw error was
    an OperationalError naming a missing table, which says nothing about what to do.
    """
    try:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))
    except OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        raise RuntimeError(
            "Baza de date nu este inițializată (lipsește tabelul alembic_version). "
            + _BOOTSTRAP_HINT
        ) from None


def _utc_now_plus(seconds: int) -> str:
    """An ISO timestamp `seconds` from now; the scheduler stores strings."""
    from datetime import datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def register_seeded_ollama(engine: Engine, registry: ProviderRegistry) -> None:
    """Give the seeded Ollama endpoint a live adapter so the owner can actually check it.

    Without this the seeded provider has no adapter, so the health check and model sync both
    fail with "no adapter registered" and the owner has no way to replace the seeded record's
    unverified state with a measured one. Registering an adapter asserts nothing about whether
    Ollama is running; only a check does that.
    """
    with Session(engine) as session:
        for provider in session.scalars(
            select(ProviderRecord).where(ProviderRecord.provider_type == "OLLAMA")
        ):
            if registry.get(provider.id) is None:
                # With the Owner's price table in hand the adapter costs every generation
                # from the tokens it counted. Without it 391 runs on the live copy carried
                # `cost_vr` NULL and the day's budget saw none of them. A local model has no
                # price and still costs None — never zero.
                registry.register(
                    provider.id,
                    OllamaProvider(
                        base_url=provider.base_url, price_lookup=price_lookup(engine, "ollama")
                    ),
                )


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings()  # type: ignore[call-arg]
    if settings.demo_mode:
        # SELL-03: the demo runs on its own database (refused on the studio's) with every
        # switch that would reach the network off; its vendors are replaced in the lifespan.
        from app.demo import demo_settings  # noqa: PLC0415

        settings = demo_settings(settings)
    configure_logging(
        settings.log_level,
        log_dir=log_directory(settings),
        max_bytes=settings.log_file_max_bytes,
        backups=settings.log_file_backups,
        console_level=settings.log_console_level,
    )
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The moment this process started: a film lease taken before it, and never renewed,
        # was left by an earlier process (`reclaim_abandoned_leases`, below).
        process_started = datetime.now(UTC)
        # Migrations/bootstrap are explicit startup commands, never hidden destructive schema edits.
        with engine.connect() as connection:
            revision = database_revision(connection)
            # The head of the chain, read from the migrations (`expected_revision`).
            # Phase D/G reserved 0041 (the picture check) and 0042
            # (the reference set and the second vendor) and neither needed a schema change —
            # the verdicts live in `quality_control_report.checks_json`, the references in
            # columns that already existed — so 0043 chains onto 0040, and 0044 (the subject
            # an approval is about, and the Owner's answer on the row) onto 0043. 0045 adds
            # the vendor invoice that replaces the studio's estimates, so a budget stops
            # counting an estimate and its bill together. 0046 indexes each employee's runs
            # by start, for the snapshot's last task per employee. 0047 indexes the events by
            # stamp and the runs by start, for the replay's reads by time. 0048 adds the
            # production sheet's rows: each scene's kind, the paid takes, and the Owner's rule
            # for paid media. 0049 records a paid task's id before the studio waits for it.
            head = expected_revision()
            if revision != head:
                raise RuntimeError(
                    f"Baza de date este la revizia {revision or 'necunoscută'}, iar această "
                    f"versiune cere {head}. " + _BOOTSTRAP_HINT
                )
            if connection.scalar(text("SELECT COUNT(*) FROM owner_policy")) != 1:
                raise RuntimeError(
                    "Studioul nu este inițializat (lipsește politica Proprietarului). "
                    + _BOOTSTRAP_HINT
                )
        # The stored keys are read once here, and a key that cannot be read is said instead
        # of crashing the start (REL-06): the page must be up for the Owner to reconnect.
        app.state.vault_health = check_vault_at_startup(engine, app.state.credential_vault)
        app.state.vault_health_cache = None
        load_registry(engine, app.state.credential_vault, app.state.registry)
        register_seeded_ollama(engine, app.state.registry)
        # The audit's open questions to the Owner, as cards in his window, each once; and
        # the cards whose condition cleared while the studio was down, closed. A failure
        # here is logged and never stops the start: the page must come up.
        try:
            seed_owner_decisions(engine, settings)
            refresh_owner_decisions(engine, settings)
        except Exception as exc:  # noqa: BLE001 - logged; the studio still starts
            logger.warning("owner_decisions_seed_failed", exc_info=exc)
        demo_exit = None
        if settings.demo_mode:
            # Every vendor seam replaced for the life of this process, and every provider's
            # adapter the demo's stand-in model (app.demo). Undone at shutdown.
            from contextlib import ExitStack  # noqa: PLC0415

            from app.demo import (  # noqa: PLC0415
                demo_vendors,
                no_outbound_network,
                register_demo_models,
            )

            register_demo_models(engine, app.state.registry)
            demo_exit = ExitStack()
            demo_exit.enter_context(no_outbound_network())
            demo_exit.enter_context(demo_vendors())
        # A studio started again in this process (a restart in place, the next test) is not
        # born stopped by the last one's shutdown.
        clear_shutdown(engine)

        # Outbox dispatcher: broadcast committed events to WebSocket clients every second.
        # The broadcasts run on the server's own event loop, because the sockets belong to
        # it; the database part (claim, mark PUBLISHED, commit) runs in a thread, so a write
        # lock held elsewhere makes this pass wait rather than the requests.
        stop_dispatcher = asyncio.Event()

        async def dispatch_outbox() -> None:
            while not stop_dispatcher.is_set():
                try:
                    # The rows are claimed and committed in a thread, then broadcast here:
                    # nobody hears of an event whose row did not commit (REL-12).
                    await dispatch_pending_outbox(engine, app.state.connection_manager)
                except Exception as exc:
                    logger.error(
                        "outbox_dispatch_failed",
                        extra={"error": type(exc).__name__},
                        exc_info=exc,
                    )
                try:
                    await asyncio.wait_for(stop_dispatcher.wait(), timeout=1.0)
                except TimeoutError:
                    pass

        dispatcher = asyncio.create_task(dispatch_outbox())
        catalog_refresher: asyncio.Task[None] | None = None
        if settings.provider_catalog_refresh_enabled:

            async def refresh_provider_catalogs() -> None:
                while not stop_dispatcher.is_set():
                    try:
                        await asyncio.to_thread(
                            refresh_due_catalogs,
                            engine,
                            app.state.credential_vault,
                            interval_seconds=settings.provider_catalog_refresh_seconds,
                            retry_seconds=settings.provider_catalog_retry_seconds,
                            settings=settings,
                        )
                    except Exception as exc:
                        logger.warning(
                            "catalog_refresh_failed", extra={"error_class": type(exc).__name__}
                        )
                    try:
                        await asyncio.wait_for(
                            stop_dispatcher.wait(), timeout=settings.provider_catalog_poll_seconds
                        )
                    except TimeoutError:
                        pass

            catalog_refresher = asyncio.create_task(refresh_provider_catalogs())

        # The live Unreal headquarters shows the employees the backend has, doing what it says.
        unreal_bridge: asyncio.Task[None] | None = None
        if remote_control_target(settings) is not None:
            unreal_bridge = asyncio.create_task(
                run_unreal_bridge(engine, settings, stop_dispatcher)
            )

        # The worker is what runs the studio without the browser: it fires due scheduled jobs
        # and executes the tasks they enqueue. Each pass is synchronous database and agent
        # work, so it runs in a thread and the request loop stays responsive. Nothing fires
        # while the Owner's autonomy stop is set — the scheduler and the queue both refuse.
        worker: asyncio.Task[None] | None = None
        gpu_guard_task: asyncio.Task[None] | None = None
        gpu_guard_started = False
        worker_lock: WorkerLock | None = None
        lock_path = worker_lock_path(engine) if settings.worker_enabled else None
        if lock_path is not None:
            # One worker per database (AR-17): a second studio started on the same database
            # (the scheduled task beside a manual start) serves the page and runs no worker.
            worker_lock = acquire_worker_lock(lock_path)
            if worker_lock is None:
                logger.warning(
                    "worker_refused_second_instance",
                    extra={
                        "lock": str(lock_path),
                        "reason": (
                            "Un alt proces al studioului rulează deja lucrătorul pe această bază "
                            "de date; acesta servește pagina și nu pornește un al doilea."
                        ),
                    },
                )
        if settings.worker_enabled and (lock_path is None or worker_lock is not None):
            # Only the exclusive queue owner may clear its predecessor's interrupted calls.
            # A previous editor call otherwise blocks fresh work for the 45-minute fallback.
            from app.agents.recovery import recover_interrupted_sheet_runs  # noqa: PLC0415
            from app.workflows.services import release_orphaned_claims  # noqa: PLC0415

            await asyncio.to_thread(
                recover_interrupted_sheet_runs, engine, started_at=process_started
            )
            # The tasks a dead worker left CLAIMED go back to the queue now, not when their
            # hour-long lease lapses (2026-10-15 20:08Z, two walks of 7c26a7ce).
            try:
                released = await asyncio.to_thread(release_orphaned_claims, engine)
                if released:
                    logger.info("orphaned_claims_released", extra={"count": released})
            except Exception as exc:  # noqa: BLE001 - logged; the studio still starts
                logger.warning(
                    "orphaned_claims_release_failed", extra={"error": type(exc).__name__}
                )
            # The one process that runs the worker takes back the film purchase leases that
            # earlier processes left (2026-10-03: a redo whose process had been stopped held
            # the Owner's film «în lucru» for hours). A lease another live process renews is
            # never touched; each one taken back is a letter to the Owner.
            try:
                from app.media.shooting_sheet import reclaim_abandoned_leases  # noqa: PLC0415

                await asyncio.to_thread(
                    reclaim_abandoned_leases,
                    engine,
                    correlation_id=str(uuid4()),
                    started_at=process_started,
                    timezone=settings.timezone,
                )
            except Exception as exc:  # noqa: BLE001 - logged; the studio still starts
                logger.warning("film_lease_reclaim_failed", extra={"error": type(exc).__name__})
            # The RunPod GPU guard (2026-10-08): the sessions an earlier process left open are
            # forced off and a GPU found on with no paid step open is switched off. Not the
            # watchdog and not a scheduled job: it runs under STOP AUTONOMIE, because it only
            # ever stops spending (ADR-GPU-OFF-ALWAYS).
            if settings.runpod_guard_enabled:
                gpu_guard_started = True
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            run_gpu_guard, engine, app.state.credential_vault, reason="BOOT"
                        ),
                        timeout=60,
                    )
                except Exception as exc:  # noqa: BLE001 - logged; the studio still starts
                    logger.warning(
                        "runpod_gpu_guard_boot_failed", extra={"error": type(exc).__name__}
                    )

                async def guard_gpu() -> None:
                    while not stop_dispatcher.is_set():
                        try:
                            intervals = await asyncio.to_thread(
                                guard_intervals, engine, app.state.credential_vault
                            )
                            wait = await asyncio.to_thread(next_interval, engine, intervals)
                        except Exception:  # noqa: BLE001
                            wait = 60
                        try:
                            await asyncio.wait_for(stop_dispatcher.wait(), timeout=wait)
                            break
                        except TimeoutError:
                            pass
                        try:
                            await asyncio.to_thread(
                                run_gpu_guard, engine, app.state.credential_vault, reason="TICK"
                            )
                        except Exception as exc:  # noqa: BLE001 - the loop goes on
                            logger.warning(
                                "runpod_gpu_guard_failed", extra={"error": type(exc).__name__}
                            )

                gpu_guard_task = asyncio.create_task(guard_gpu())
            # The day is on the studio's wall clock — STUDIO_DAILY_RUN_HOUR_LOCAL in
            # STUDIO_TIMEZONE — not on the moment the process started; the hour follows the
            # setting on every start-up.
            ensure_scheduled_job(
                engine,
                name=DAILY_JOB_NAME,
                workflow_type=DAILY_RUN,
                interval_seconds=86400,
                missed_policy="CATCH_UP",
                run_at_local=settings.daily_run_hour_local,
                timezone=settings.timezone,
                # Dormant until the Owner starts it from the panel: a job that fired within
                # thirty seconds of the first start-up would begin a real day — agents, tokens,
                # renders — on a decision nobody took.
                active=False,
            )
            # The watchdog: stuck work found and named every ten minutes. Active from birth
            # and behind the autonomy stop like every other scheduled thing; it starts nothing
            # and spends nothing, it only says what is stuck.
            ensure_scheduled_job(
                engine,
                name=WATCHDOG_JOB_NAME,
                workflow_type=WATCHDOG,
                interval_seconds=settings.watchdog_interval_seconds,
                missed_policy="SKIP",
                first_run_at=_utc_now_plus(settings.watchdog_interval_seconds),
                active=True,
            )
            # The Director's weekly performance review: standing policy ordered by the Owner,
            # so the job is active from birth. The first pass waits an hour — a studio that
            # has published nothing yet reports exactly that instead of spending tokens —
            # and the autonomy stop gates every fire like any other scheduled work.
            ensure_scheduled_job(
                engine,
                name=WEEKLY_JOB_NAME,
                workflow_type="WEEKLY_REVIEW",
                interval_seconds=7 * 86400,
                missed_policy="CATCH_UP",
                first_run_at=_utc_now_plus(3600),
                active=True,
            )
            # What people search for, once a day, so proposals and reviews can read it; the
            # stewards' reading of their vendors' pages, once a week, so the model choice
            # rests on prices and capabilities they recorded, not on catalogue order.
            if settings.trends_enabled:
                ensure_scheduled_job(
                    engine,
                    name=TRENDS_JOB_NAME,
                    workflow_type=TRENDS_REFRESH,
                    interval_seconds=86400,
                    missed_policy="CATCH_UP",
                    first_run_at=_utc_now_plus(120),
                    active=True,
                )
            # The stewards read their vendors' pages on the network: not in the demo.
            if not settings.demo_mode:
                ensure_scheduled_job(
                    engine,
                    name=MODEL_RESEARCH_JOB_NAME,
                    workflow_type=MODEL_RESEARCH,
                    interval_seconds=7 * 86400,
                    missed_policy="CATCH_UP",
                    first_run_at=_utc_now_plus(7200),
                    active=True,
                )
            # And every day, the standing of every model, re-judged on what it delivered.
            # The light review reads the studio's own results and generates nothing, so a
            # model that has started failing stops being chosen within a day instead of a
            # week — and a model that has proved itself stops waiting outside production.
            ensure_scheduled_job(
                engine,
                name=MODEL_REVIEW_JOB_NAME,
                workflow_type=MODEL_REVIEW,
                interval_seconds=86400,
                missed_policy="SKIP",
                first_run_at=_utc_now_plus(900),
                active=True,
            )
            # And the Director's regular pass over the company: blockers found
            # in the morning are not work for tomorrow. It assigns at most three things and
            # skips a matter already under an open decision, so it cannot become noise.
            ensure_scheduled_job(
                engine,
                name=DIRECTOR_LOOP_JOB_NAME,
                workflow_type=DIRECTOR_LOOP,
                interval_seconds=settings.director_check_interval_seconds,
                missed_policy="SKIP",
                first_run_at=_utc_now_plus(settings.director_check_interval_seconds),
                active=True,
                follow_interval=True,
            )
            # The database's backup, once a day on the studio's clock (REL-04): SQLite's online
            # copy, its check, the wrapped key beside it, then the pruning of old housekeeping
            # rows (REL-15). No network and no cost, so it is active from birth; behind the
            # autonomy stop like every other scheduled thing.
            ensure_scheduled_job(
                engine,
                name=BACKUP_JOB_NAME,
                workflow_type=BACKUP,
                interval_seconds=86400,
                missed_policy="CATCH_UP",
                run_at_local=settings.backup_hour_local,
                timezone=settings.timezone,
                active=True,
            )
            handlers = build_task_handlers(
                engine, settings, app.state.credential_vault, app.state.stage_runners, registry
            )
            ops = app.state.operations

            async def run_worker() -> None:
                while not stop_dispatcher.is_set():
                    try:
                        record_pass_start(ops)
                        summary = await asyncio.to_thread(
                            worker_pass, engine, handlers, "worker_main", registry, ops
                        )
                        record_pass_end(ops)
                        if summary["triggered"] or summary["ran"]:
                            logger.info(
                                "worker_pass",
                                extra={
                                    "triggered": len(summary["triggered"]),
                                    "ran": [item["status"] for item in summary["ran"]],
                                },
                            )
                    except Exception as exc:  # noqa: BLE001 - a pass failing must not end the loop
                        logger.error(
                            "worker_pass_failed",
                            extra={"error": type(exc).__name__},
                            exc_info=exc,
                        )
                        # Counted for /health/ready; the third in a row is one event and one
                        # letter to the Owner (REL-07). Written off the loop: it is database work.
                        await asyncio.to_thread(record_pass_failure, engine, ops, exc)
                    try:
                        await asyncio.wait_for(
                            stop_dispatcher.wait(), timeout=settings.worker_interval_seconds
                        )
                    except TimeoutError:
                        pass

            worker = asyncio.create_task(run_worker())
            app.state.worker_running = True

        try:
            yield
        finally:
            # The day running in the worker's thread hears this at its next boundary — the
            # paid loops read it before every scene — and ends INTERRUPTED instead of being
            # waited out for hours or killed mid-purchase (REL-10). Asked before the wait.
            request_shutdown(engine)
            try:
                stop_dispatcher.set()
                with suppress(asyncio.CancelledError):
                    await dispatcher
                if worker is not None:
                    if not worker.done():
                        logger.info("shutdown_waiting_for_worker")
                    with suppress(asyncio.CancelledError):
                        await worker
                if catalog_refresher is not None:
                    with suppress(asyncio.CancelledError):
                        await catalog_refresher
                if unreal_bridge is not None:
                    with suppress(asyncio.CancelledError):
                        await unreal_bridge
                if gpu_guard_task is not None:
                    with suppress(asyncio.CancelledError):
                        await gpu_guard_task
                if gpu_guard_started:
                    # The worker's steps have closed their GPU sessions; whatever is still on
                    # (a close that could not verify) is switched off before the studio goes.
                    try:
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                force_off,
                                engine,
                                app.state.credential_vault,
                                reason="SHUTDOWN",
                            ),
                            timeout=20,
                        )
                    except Exception as exc:  # noqa: BLE001 - the launcher's off follows
                        logger.warning(
                            "runpod_gpu_shutdown_off_failed", extra={"error": type(exc).__name__}
                        )
            finally:
                # The worker has been awaited: the shutdown it was told of is over, and the
                # worker's lock is the next start's.
                app.state.worker_running = False
                if worker_lock is not None:
                    worker_lock.release()
                if demo_exit is not None:
                    demo_exit.close()
                clear_shutdown(engine)
                engine.dispose()

    app = FastAPI(
        title="AMN-AI",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    #: The worker's own record of its passes (REL-07): read by /health/ready and the snapshot.
    app.state.operations = new_operations()
    #: The page's own folder (PAGE-01): the snapshot says whether the bundle it serves was built
    #: from the sources there (`app.page_build`). A test points it at a page of its own.
    app.state.page_root = ROOT / "frontend"
    # The Owner's STUDIO_MEDIA_ROOT (REL-08): the media routes, the sheet's steps and the file
    # routes' allowed folders read it here. Unset, they use the studio's own folder.
    if settings.media_root is not None:
        app.state.media_storage_root = settings.media_root
    #: True while this process runs the background worker (False when it is off in the
    #: settings, or another process on the same database holds the worker's lock).
    app.state.worker_running = False
    app.state.credential_vault = CredentialVault(
        Path(str(engine.url.database)).with_suffix(".credentials.key")
    )
    registry = ProviderRegistry()
    app.state.registry = registry
    connection_manager = ConnectionManager()
    app.state.connection_manager = connection_manager
    # The work behind the runbook's stages. Without this a daily run walks twelve stages and
    # records eleven of them SKIPPED for want of an implementation — truthful, and idle.
    app.state.stage_runners = build_stage_runners(
        engine, settings, app.state.credential_vault, registry
    )

    owner_key = settings.owner_token.get_secret_value()

    def demo_refused(request: Request) -> str | None:
        """The demo's refusal of a write it never runs (SELL-03), told only to the Owner: a
        request without his key goes on to the route, which answers 401 as everywhere."""
        if not settings.demo_mode:
            return None
        from app.demo import demo_refusal  # noqa: PLC0415

        reason = demo_refusal(request.method, request.url.path)
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else None
        return reason if reason and owner_key_matches(presented, owner_key) else None

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = str(uuid4())
        started = time.perf_counter()
        try:
            refusal = demo_refused(request)
            if refusal is not None:
                response = JSONResponse({"detail": refusal}, status_code=403)
            else:
                response = await call_next(request)
        except Exception as exc:
            # Never log arbitrary request bodies, authorization headers, URLs or DB error strings.
            logger.error(
                "request_failed",
                extra={"correlation_id": correlation_id, "error_class": type(exc).__name__},
                # Its frames, never its text (app.logging): the cause is findable, the
                # request's data and the database's strings stay out of the file.
                exc_info=exc,
            )
            response = JSONResponse(
                {"detail": "Internal error", "correlation_id": correlation_id}, status_code=500
            )
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Nothing the API answers may be kept: it carries the Owner's studio, and every answer is
        # the state of one moment. Only a file of the built page (PageFiles) says otherwise, and
        # only outside /api/.
        if request.url.path.startswith("/api/") or "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: https://yt3.ggpht.com https://yt3.googleusercontent.com; "
            # The Media dialog plays a film from the bytes it fetched with the Owner's key, as a
            # blob: URL; without media-src the default 'self' refused it on the real server.
            "media-src 'self' blob:; "
            "frame-src https://www.youtube-nocookie.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        logger.info(
            "request_complete",
            extra={
                "correlation_id": correlation_id,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
                    for item in exc.errors()
                ]
            },
        )

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "HEALTHY", "service": "api", "version": "0.1.0"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT version FROM owner_policy WHERE id=1")).one()
        except SQLAlchemyError:
            return JSONResponse({"status": "DEGRADED", "database": "UNAVAILABLE"}, status_code=503)
        # Whether the stored keys can be read (REL-06). A studio that cannot read them still
        # answers 200: it serves the page, where the Owner reconnects. Public, so it names no
        # connection; the preflight says which. Read again at most every VAULT_HEALTH_TTL_S,
        # because the probe is unauthenticated and each read unwraps the key.
        credentials = "HEALTHY"
        try:
            cached = getattr(app.state, "vault_health_cache", None)
            if cached is None or time.monotonic() - cached[0] > VAULT_HEALTH_TTL_S:
                cached = (
                    time.monotonic(),
                    vault_health(engine, app.state.credential_vault)["status"],
                )
                app.state.vault_health_cache = cached
            credentials = "HEALTHY" if cached[1] == "HEALTHY" else "UNREADABLE"
        except Exception as exc:  # noqa: BLE001 - the probe answers; the error is logged
            logger.warning("vault_health_failed", exc_info=exc)
            credentials = "UNKNOWN"
        # What keeps the studio running (REL-07, AR-18): the worker's passes, the media disk,
        # FFmpeg and FFprobe, the newest backup. Any of them wrong is 503 DEGRADED, so a
        # supervisor watching this probe sees it; the page reads the same in the snapshot,
        # in words. The probe is public: statuses and codes only.
        try:
            reading = public_health(operations_now())
        except Exception as exc:  # noqa: BLE001 - the probe answers; the error is logged
            logger.warning("operations_reading_failed", exc_info=exc)
            reading = {"worker": "UNKNOWN", "problems": ["OPERATIONS_UNREADABLE"]}
        degraded = credentials != "HEALTHY" or bool(reading["problems"])
        return JSONResponse(
            {
                "status": "DEGRADED" if degraded else "HEALTHY",
                "database": "HEALTHY",
                "credentials": credentials,
                **reading,
                "scope": "FOUNDATION_API_AND_DATABASE",
            },
            status_code=503 if reading["problems"] else 200,
        )

    def operations_now() -> dict:
        return operations_reading(
            engine,
            settings,
            getattr(app.state, "operations", None),
            worker_running=bool(getattr(app.state, "worker_running", False)),
        )

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_owner)])

    @router.get("/snapshot")
    def get_snapshot() -> dict:
        try:
            operations = operations_now()
        except Exception as exc:  # noqa: BLE001 - the snapshot is the page; it still answers
            logger.warning("operations_reading_failed", exc_info=exc)
            operations = None
        reading = snapshot(
            engine,
            operations,
            location=studio_location(settings),
            demo=settings.demo_mode,
        )
        # Whether the page is older than the studio's sources (PAGE-01); None when it cannot be
        # read, which the page shows as no banner rather than a guess.
        try:
            reading["page_build"] = page_build(Path(app.state.page_root))
        except OSError as exc:
            logger.warning("page_build_unreadable", exc_info=exc)
            reading["page_build"] = None
        return reading

    @router.get("/events")
    def get_events(
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=300)] = 50,
        since: Annotated[str | None, Query(max_length=40)] = None,
    ) -> dict:
        """The record, paged by sequence; with `since`, from the first event stamped at or
        after that instant (the replay of a day finds its run's start in one read)."""
        instant = None
        if since is not None:
            try:
                instant = read_instant(since)
            except ValueError:
                raise HTTPException(422, "since: an ISO 8601 instant is expected") from None
        return read_events(engine, after, limit, instant)

    @router.post("/owner/environment", response_model=PolicyResult)
    def set_environment(command: EnvironmentCommand) -> PolicyResult | JSONResponse:
        """Move the studio between TEST and PRODUCTION.

        The environment decides what a generation may cost, so it lives in the studio's own
        policy and changes only here — never from a query parameter a page could set.
        """
        try:
            return change_environment(engine, command)
        except CommandConflict as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})

    @router.post("/owner/autonomy-mode", response_model=PolicyResult)
    def set_autonomy_mode(command: AutonomyModeCommand) -> PolicyResult | JSONResponse:
        """Move the studio between MANUAL, SUPERVISED and AUTONOMOUS_CEO.

        The mode decides which risk tiers an agent may act in at all, so it lives in the
        studio's own policy and changes only here. A promotion the studio's state forbids
        (the stop is on, an incident is open) answers 409 with the Owner's reason.
        """
        try:
            return change_autonomy_mode(engine, command)
        except CommandConflict as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})
        except AutonomyRefused as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})

    @router.post("/owner/paid-media-approval", response_model=PaidMediaApprovalResult)
    def set_paid_media_approval(
        command: PaidMediaApprovalCommand,
    ) -> PaidMediaApprovalResult | JSONResponse:
        """When a paid step of a film (stills, hero test, motion, one-scene redo) asks him.

        The Owner's command and only his: this route is behind his key, so it is issued as
        "owner", and no body field can name another issuer (the command forbids extra
        fields). A stale version answers 409, a malformed rule 422 (the command's own
        validation), and an issuer the service refuses 403.
        """
        try:
            return change_paid_media_approval(engine, command, issued_by="owner")
        except PaidMediaApprovalRefused as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc)})
        except CommandConflict as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})

    @router.get("/owner/approvals", response_model=list[ApprovalView])
    def list_owner_approvals() -> list[ApprovalView]:
        """What a SUPERVISED studio is waiting to be told, newest first.

        Everything the Owner needs to decide is on the row: what the action is in his own
        language, the risk tier, who asked, the evidence, and the cost — the word
        "necunoscut" when nothing in the studio could compute one, never a zero. Only
        PENDING and only unexpired: a request the studio has stopped waiting on is not a
        decision he still has to make.
        """
        return pending_approvals(engine)

    @router.post("/owner/approvals/decision", response_model=ApprovalDecisionResult)
    def decide_owner_approval(
        command: ApprovalDecisionCommand,
    ) -> ApprovalDecisionResult | JSONResponse:
        """The Owner answers one request: APPROVED or REFUSED, with a word of his own.

        Versioned and idempotent by command id like the rest of his commands. A request
        that was already answered or has expired answers 409 with his reason — 31 says an
        expired approval cannot be reused, and a request answered twice would be two
        authorities for one act. A request the studio never made is 404, because that is
        what it is: a stale page, not a governance conflict.
        """
        try:
            return decide_approval(engine, command)
        except ApprovalMissing as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc)})
        except (ApprovalClosed, CommandConflict) as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc)})

    @router.post("/owner/autonomy-stop", response_model=PolicyResult)
    def set_autonomy_stop(command: PolicyCommand) -> PolicyResult | JSONResponse:
        try:
            return change_stop(engine, command)
        except CommandConflict as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)

    app.include_router(router)
    app.include_router(create_settings_router(), prefix="/api/v1", tags=["settings"])
    # Phase 1: agent and provider routes
    app.include_router(create_agents_router(registry), prefix="/api/v1", tags=["agents"])
    app.include_router(create_providers_router(registry), prefix="/api/v1", tags=["providers"])
    # Phase 2: workflow, task, scheduler routes + websocket gateway
    app.include_router(create_workflows_router(), prefix="/api/v1", tags=["workflows"])
    app.include_router(create_tasks_router(), prefix="/api/v1", tags=["tasks"])
    app.include_router(create_scheduler_router(), prefix="/api/v1", tags=["scheduler"])
    register_websocket_gateway(app, connection_manager)
    register_stream_gateway(app)
    # Phase 3: 2D office layout router
    app.include_router(create_office_router(), prefix="/api/v1", tags=["office"])
    # W24: the newest real frame of the live headquarters; read publicly by the title, written
    # only with the Owner's key
    app.include_router(create_kept_frame_router(), prefix="/api/v1", tags=["office"])
    # Phase 4: Factual Intelligence & Verification Engine router
    app.include_router(create_factual_router(), prefix="/api/v1", tags=["factual"])
    # Phase 5: Media Production & Assembly router
    app.include_router(create_media_router(), prefix="/api/v1", tags=["media"])
    # Phase 6: Autonomous Publishing & Distribution router
    app.include_router(create_publishing_router(), prefix="/api/v1", tags=["publishing"])
    app.include_router(create_analytics_router(), prefix="/api/v1", tags=["analytics"])
    app.include_router(create_economy_router(), prefix="/api/v1", tags=["economy"])
    app.include_router(create_youtube_router(), prefix="/api/v1", tags=["youtube"])
    # Public on purpose: Google redirects a browser here, and a redirect cannot carry the
    # Owner credential. The single-use OAuth state is what protects it.
    app.include_router(create_youtube_callback_router(), tags=["youtube"])
    app.include_router(create_workforce_router(), prefix="/api/v1", tags=["workforce"])
    app.include_router(create_story_router(), prefix="/api/v1", tags=["story"])
    app.include_router(create_runbook_router(), prefix="/api/v1", tags=["runbook"])
    # The Owner's decisions window (2026-10-03): his cards, and his answers to them.
    app.include_router(create_decisions_router(), prefix="/api/v1", tags=["owner"])
    # The RunPod GPU switch (2026-10-08): its state, and the Owner's «Oprește GPU acum».
    app.include_router(create_runpod_router(), prefix="/api/v1", tags=["runpod"])
    # LOCAL_AUTO_LOGIN (2026-10-08): the Owner's key for his own page on this machine, without
    # the sign-in form; everyone else gets the 404 of an unknown path (app/local_session.py).
    app.include_router(create_local_session_router(), prefix="/api/v1")

    if (ROOT / "frontend/dist").is_dir():
        app.mount("/", PageFiles(directory=ROOT / "frontend/dist", html=True), name="frontend")
    return TrustedHostMiddleware(app, allowed_hosts=settings.allowed_hosts, www_redirect=False)
