import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp

from app.agents.models import ProviderRecord
from app.agents.router import create_agents_router, create_providers_router
from app.analytics.router import create_analytics_router
from app.config import ROOT, Settings
from app.db import create_db_engine
from app.economy.router import create_economy_router
from app.factual.router import create_factual_router
from app.integrations.router import create_settings_router
from app.integrations.services import load_registry
from app.integrations.vault import CredentialVault
from app.logging import configure_logging
from app.media.router import create_media_router
from app.office.router import create_office_router
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
from app.publishing.router import create_publishing_router
from app.runbook.router import create_runbook_router
from app.runbook.stages import build_stage_runners
from app.schemas import PolicyCommand, PolicyResult
from app.security import require_owner
from app.services import CommandConflict, change_stop, read_events, snapshot
from app.story.router import create_story_router
from app.workflows.publisher import ConnectionManager, publish_pending_outbox
from app.workflows.router import (
    create_scheduler_router,
    create_tasks_router,
    create_workflows_router,
    register_websocket_gateway,
)
from app.workforce.router import create_workforce_router
from app.youtube.router import create_youtube_callback_router, create_youtube_router

logger = logging.getLogger("studio.api")


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
                registry.register(provider.id, OllamaProvider(base_url=provider.base_url))


def create_app(settings: Settings | None = None) -> ASGIApp:
    settings = settings or Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Migrations/bootstrap are explicit startup commands, never hidden destructive schema edits.
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "0018_audit_gaps":
                raise RuntimeError("Run scripts/bootstrap.py with this application version")
            if connection.scalar(text("SELECT COUNT(*) FROM owner_policy")) != 1:
                raise RuntimeError("Run scripts/bootstrap.py to initialize the studio")
        load_registry(engine, app.state.credential_vault, app.state.registry)
        register_seeded_ollama(engine, app.state.registry)

        # Outbox dispatcher: broadcast committed events to WebSocket clients every second.
        # Runs on the server's own event loop on purpose — publish_pending_outbox schedules
        # the broadcasts with the running loop, and the sockets belong to this loop. The
        # SQLite read is a short local transaction, acceptable between request cycles.
        stop_dispatcher = asyncio.Event()

        async def dispatch_outbox() -> None:
            while not stop_dispatcher.is_set():
                try:
                    publish_pending_outbox(engine, app.state.connection_manager)
                except Exception as exc:
                    logger.error("outbox_dispatch_failed", extra={"error": type(exc).__name__})
                try:
                    await asyncio.wait_for(stop_dispatcher.wait(), timeout=1.0)
                except TimeoutError:
                    pass

        dispatcher = asyncio.create_task(dispatch_outbox())
        try:
            yield
        finally:
            stop_dispatcher.set()
            with suppress(asyncio.CancelledError):
                await dispatcher
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

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = str(uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Never log arbitrary request bodies, authorization headers, URLs or DB error strings.
            logger.error(
                "request_failed",
                extra={"correlation_id": correlation_id, "error_class": type(exc).__name__},
            )
            response = JSONResponse(
                {"detail": "Internal error", "correlation_id": correlation_id}, status_code=500
            )
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
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
        return JSONResponse(
            {"status": "HEALTHY", "database": "HEALTHY", "scope": "FOUNDATION_API_AND_DATABASE"}
        )

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_owner)])

    @router.get("/snapshot")
    def get_snapshot() -> dict:
        return snapshot(engine)

    @router.get("/events")
    def get_events(
        after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> dict:
        return read_events(engine, after, limit)

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
    # Phase 3: 2D office layout router
    app.include_router(create_office_router(), prefix="/api/v1", tags=["office"])
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

    if (ROOT / "frontend/dist").is_dir():
        app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="frontend")
    return TrustedHostMiddleware(app, allowed_hosts=settings.allowed_hosts, www_redirect=False)
