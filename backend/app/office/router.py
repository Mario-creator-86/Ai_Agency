"""Office layout FastAPI routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.office.services import get_office_layout_with_assignments
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

    return router
