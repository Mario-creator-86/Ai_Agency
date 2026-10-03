"""The Owner's decisions window: his cards and his answers, behind his key."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from app.decisions.services import (
    OWNER,
    DecideCommand,
    DecisionApplyFailed,
    DecisionConflict,
    DecisionInvalid,
    DecisionMissing,
    DecisionRefused,
    decide_owner_decision,
    owner_decision_cards,
)
from app.security import require_owner


def create_decisions_router() -> APIRouter:
    router = APIRouter(prefix="/owner", dependencies=[Depends(require_owner)])

    @router.get("/decision-cards")
    def get_decision_cards(request: Request, history: bool = True) -> dict[str, Any]:
        """Everything that waits for the Owner, as one kind of card, newest first: the paid
        steps (answered through POST /owner/approvals/decision), the decision cards (answered
        here) and the letters that ask him something (answered through the letters' routes);
        ``count`` is what the «Decizii (N)» button shows, ``history`` what he answered."""
        return owner_decision_cards(
            request.app.state.engine, request.app.state.settings, include_history=history
        )

    @router.post("/decisions/{decision_id}/decide")
    def post_decide(
        request: Request,
        decision_id: Annotated[str, Path(min_length=1, max_length=36)],
        command: DecideCommand,
    ) -> Any:
        """The Owner answers one card. Issued as "owner" because this route is behind his key;
        no body field can name the issuer (the command forbids extra fields). A stale version or
        a card already answered is 409; a card that does not exist 404; an accept whose apply
        failed 422 with his reason (the card stays PENDING)."""
        try:
            return decide_owner_decision(
                request.app.state.engine,
                decision_id,
                command,
                issued_by=OWNER,
                settings=request.app.state.settings,
            )
        except DecisionMissing as exc:
            return JSONResponse({"detail": str(exc)}, status_code=404)
        except DecisionConflict as exc:
            return JSONResponse({"detail": str(exc)}, status_code=409)
        except DecisionRefused as exc:
            return JSONResponse({"detail": str(exc)}, status_code=403)
        except (DecisionApplyFailed, DecisionInvalid) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)

    return router
