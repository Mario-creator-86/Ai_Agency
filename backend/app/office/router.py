"""Office layout FastAPI routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.office.services import get_office_layout_with_assignments
from app.security import require_owner


def create_office_router() -> APIRouter:
    router = APIRouter(prefix="/office", dependencies=[Depends(require_owner)])

    @router.get("/layout")
    def get_layout(request: Request) -> dict:
        return get_office_layout_with_assignments(request.app.state.engine)

    return router
