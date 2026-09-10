"""Phase 10 routes — preflight, the daily run, and safe mode."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.runbook.preflight import run_preflight
from app.runbook.services import (
    RunbookError,
    SafeModeActive,
    clear_safe_mode,
    execute_daily_run,
    list_runs,
    safe_mode_state,
)
from app.security import require_owner


class RunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID


class ClearSafeModeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    notes: str = Field(min_length=3, max_length=2000)


def create_runbook_router() -> APIRouter:
    router = APIRouter(prefix="/runbook", dependencies=[Depends(require_owner)])

    @router.get("/preflight")
    def get_preflight(request: Request) -> dict:
        """What the studio can actually do right now. Changes nothing, calls nothing."""
        return run_preflight(
            request.app.state.engine,
            request.app.state.settings,
            request.app.state.credential_vault,
        )

    @router.get("/runs")
    def get_runs(request: Request) -> dict:
        return {"runs": list_runs(request.app.state.engine)}

    @router.post("/runs")
    def post_run(request: Request, cmd: RunCommand) -> dict:
        """Execute the daily runbook and record what each stage actually did."""
        try:
            return execute_daily_run(
                request.app.state.engine,
                request.app.state.settings,
                request.app.state.credential_vault,
                str(cmd.command_id),
                stage_runners=getattr(request.app.state, "stage_runners", None),
            )
        except SafeModeActive as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RunbookError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/safe-mode")
    def get_safe_mode(request: Request) -> dict:
        return safe_mode_state(request.app.state.engine)

    @router.post("/safe-mode/clear")
    def post_clear_safe_mode(request: Request, cmd: ClearSafeModeCommand) -> dict:
        """Leave safe mode. Autonomy stays off; restarting it is a separate decision."""
        try:
            return clear_safe_mode(request.app.state.engine, cmd.notes, str(cmd.command_id))
        except RunbookError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    return router
