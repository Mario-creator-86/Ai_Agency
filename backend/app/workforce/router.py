"""Phase 8 routes: what the studio proposes about its own staff, and the Owner's decision."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.security import require_owner
from app.workforce.services import (
    AutonomousChangeBlocked,
    WorkforceError,
    decide_proposal,
    employment_history,
    list_proposals,
    measure_workforce,
    open_employment,
    propose_workforce_changes,
)


class DecisionCommand(BaseModel):
    """The Owner's decision on one proposal.

    ``notes`` is required for a rejection and optional for an approval: a change that is carried
    out leaves its own trail in the event log, while a refusal leaves none unless a reason is
    written down, and a future reader deserves to know why the studio was told no.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    approve: bool
    notes: str = Field(default="", max_length=2000)


class EmploymentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    agent_id: UUID
    role_id: UUID


def create_workforce_router() -> APIRouter:
    router = APIRouter(prefix="/workforce", dependencies=[Depends(require_owner)])

    @router.get("/measurements")
    def get_measurements(request: Request) -> dict:
        """The studio's own operating record. Counts rows; judges nothing."""
        return measure_workforce(request.app.state.engine)

    @router.get("/proposals")
    def get_proposals(
        request: Request,
        status: Annotated[str | None, Query(max_length=20)] = None,
    ) -> dict:
        return {"proposals": list_proposals(request.app.state.engine, status=status)}

    @router.post("/proposals/generate")
    def post_generate(request: Request) -> dict:
        """Re-read the measurements and propose what they support.

        An empty list is the ordinary answer for a studio that is running normally, and is not
        an error: there is no threshold at which thin evidence becomes a recommendation.
        """
        created = propose_workforce_changes(request.app.state.engine, str(uuid4()))
        return {
            "proposals": created,
            "message": (
                f"{len(created)} propuneri noi."
                if created
                else "Măsurătorile nu susțin nicio schimbare de personal acum."
            ),
        }

    @router.post("/proposals/{proposal_id}/decide")
    def post_decide(
        request: Request,
        proposal_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: DecisionCommand,
    ) -> dict:
        if not cmd.approve and not cmd.notes.strip():
            raise HTTPException(
                status_code=422,
                detail="Scrie de ce respingi propunerea; motivul rămâne în istoric.",
            )
        try:
            return decide_proposal(
                request.app.state.engine,
                proposal_id,
                cmd.approve,
                cmd.notes,
                str(cmd.command_id),
                owner_decision=True,
            )
        except AutonomousChangeBlocked as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except WorkforceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/employment")
    def post_employment(request: Request, cmd: EmploymentCommand) -> dict:
        """Start a period of employment — a first hire, or a rehire after termination."""
        try:
            return open_employment(
                request.app.state.engine,
                str(cmd.agent_id),
                str(cmd.role_id),
                str(cmd.command_id),
            )
        except WorkforceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.get("/employment/{agent_id}")
    def get_employment(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return {"history": employment_history(request.app.state.engine, agent_id)}

    return router
