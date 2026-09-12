"""Phase 10 routes — preflight, the daily run, the weekly review, and safe mode."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.command import (
    CommandError,
    company_state,
    direct_company,
    due_reviews,
    review_decision,
)
from app.analytics.models import DirectorDecision
from app.runbook.preflight import run_preflight
from app.runbook.services import (
    PENDING_STATES,
    RunbookError,
    SafeModeActive,
    clear_safe_mode,
    list_runs,
    pending_daily_run,
    safe_mode_state,
    start_daily_run,
)
from app.runbook.weekly import WEEKLY_REVIEW_TASK
from app.security import require_owner
from app.workflows.models import TaskQueueItem
from app.workflows.services import enqueue_task


class RunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID


class ReviewDecisionCommand(BaseModel):
    """What actually happened, in the Owner's or the studio's own words."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    outcome: str = Field(min_length=3, max_length=4000)


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
        """The days that have closed, and the one on its way if there is one."""
        return {
            "runs": list_runs(request.app.state.engine),
            "pending": pending_daily_run(request.app.state.engine),
        }

    @router.post("/runs")
    def post_run(request: Request, cmd: RunCommand) -> dict:
        """Start today's run. Returns as soon as it is queued; the worker does the day."""
        try:
            return start_daily_run(
                request.app.state.engine,
                request.app.state.settings,
                str(cmd.command_id),
                worker_enabled=request.app.state.settings.worker_enabled,
            )
        except SafeModeActive as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RunbookError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/weekly-review")
    def post_weekly_review(request: Request, cmd: RunCommand) -> dict:
        """Queue the Director's weekly performance review now. The worker does the work."""
        from app.models import OwnerPolicy
        from app.services import utc_now

        engine = request.app.state.engine
        if not request.app.state.settings.worker_enabled:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Lucrătorul de fundal este oprit în configurație; nimeni nu ar prelua revizia."
                ),
            )
        with Session(engine) as session:
            policy = session.get(OwnerPolicy, 1)
            if policy is not None and policy.autonomy_stopped:
                raise HTTPException(
                    status_code=409,
                    detail="Autonomia este oprită: nimic nu pornește până nu o repornești.",
                )
            pending = session.scalar(
                select(TaskQueueItem)
                .where(
                    TaskQueueItem.task_type == WEEKLY_REVIEW_TASK,
                    TaskQueueItem.status.in_(PENDING_STATES),
                )
                .limit(1)
            )
        if pending is not None:
            raise HTTPException(
                status_code=409,
                detail=f"O revizie săptămânală este deja la coadă (pusă la {pending.created_at}).",
            )
        task = enqueue_task(
            engine,
            WEEKLY_REVIEW_TASK,
            {"manual": True, "requested_at": utc_now()},
            priority=8,
            max_attempts=1,
            idempotency_key=f"weekly-review-{cmd.command_id}",
        )
        return {
            "status": "QUEUED",
            "task_id": task["id"],
            "message": (
                "Revizia săptămânală a fost pusă la coadă. Directorul citește performanța "
                "măsurată și trimite indicațiile spre departamentele de sunet și video; "
                "urmărește registrul."
            ),
        }

    @router.get("/company-state")
    def get_company_state(request: Request) -> dict:
        """Where the company stands: channels, pipeline, agents, backlog, decisions.

        Reads only, and nothing is invented: a channel with nothing measured says so instead
        of showing zeros that would read as a measurement.
        """
        return company_state(request.app.state.engine, request.app.state.settings)

    @router.post("/direct")
    def post_direct(request: Request) -> dict:
        """Run one pass of the Director's management of the company, now.

        The same pass the scheduler makes four times a day. Its output is assignments, not a
        report: what it decided, who was asked, and what goes to the Owner instead.
        """
        result = direct_company(
            request.app.state.engine,
            getattr(request.app.state, "registry", None),
            request.app.state.settings,
        )
        return {
            "status": result["status"],
            "reason": result["reason"],
            "assignments": result.get("assignments", []),
            "escalated": result.get("escalated", []),
            "note": result.get("note", ""),
            "maturity": result.get("maturity"),
        }

    @router.get("/decisions")
    def get_decisions(request: Request) -> dict:
        """The Director's strategic decisions, newest first, with what became of them."""
        with Session(request.app.state.engine) as session:
            rows = session.scalars(
                select(DirectorDecision).order_by(DirectorDecision.created_at.desc()).limit(40)
            ).all()
            return {
                "decisions": [
                    {
                        "id": row.id,
                        "scope": row.scope,
                        "matter_key": row.matter_key,
                        "observation": row.observation,
                        "interpretation": row.interpretation,
                        "confidence": row.confidence,
                        "decision": row.decision,
                        "action": row.action,
                        "owner_role": row.owner_role,
                        "review_after_videos": row.review_after_videos,
                        "state": row.state,
                        "outcome": row.outcome,
                        "created_at": row.created_at,
                        "reviewed_at": row.reviewed_at,
                    }
                    for row in rows
                ],
                "due_for_review": due_reviews(request.app.state.engine),
            }

    @router.post("/decisions/{decision_id}/review")
    def post_review_decision(
        request: Request,
        decision_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: ReviewDecisionCommand,
    ) -> dict:
        """Close a decision with what actually happened. The Owner's word is final here."""
        try:
            return review_decision(request.app.state.engine, decision_id, command.outcome)
        except CommandError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
