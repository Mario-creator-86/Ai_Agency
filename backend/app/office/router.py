"""Office layout FastAPI routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.media.storage import media_roots
from app.office.presentation import presentation_snapshot
from app.office.services import get_office_layout_with_assignments
from app.office.stream import stream_status
from app.office.weather import current_weather
from app.security import require_owner


def create_office_router() -> APIRouter:
    router = APIRouter(prefix="/office", dependencies=[Depends(require_owner)])

    @router.get("/layout")
    def get_layout(request: Request) -> dict:
        return get_office_layout_with_assignments(request.app.state.engine)

    @router.get("/weather")
    def get_weather(request: Request) -> dict:
        """The live weather over the office, or why it is unavailable. Never invented."""
        return current_weather(request.app.state.settings)

    @router.get("/presentation")
    def get_presentation(request: Request) -> dict:
        return presentation_snapshot(request.app.state.engine, roots=media_roots(request.app.state))

    @router.get("/stream")
    def get_stream(request: Request) -> dict:
        """Whether the live Unreal headquarters is configured, and where the page's relay is."""
        return stream_status(request.app.state.settings)

    return router
