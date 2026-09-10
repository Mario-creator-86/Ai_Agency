"""Phase 9 routes — the daily log, and the serial drawn from it."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.security import require_owner
from app.story.services import (
    EpisodeNotGrounded,
    NothingHappened,
    StoryError,
    close_daily_log,
    decide_episode,
    get_daily_log,
    grounding_report,
    list_daily_logs,
    list_episodes,
    write_episode,
)


class CloseDayCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    #: Defaults to today in the studio's timezone.
    business_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class WriteEpisodeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    log_id: str = Field(min_length=36, max_length=36)
    agent_id: UUID | None = None


class EpisodeDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    approve: bool
    notes: str = Field(default="", max_length=2000)


def create_story_router() -> APIRouter:
    router = APIRouter(prefix="/story", dependencies=[Depends(require_owner)])

    @router.get("/logs")
    def get_logs(request: Request) -> dict:
        return {"logs": list_daily_logs(request.app.state.engine)}

    @router.post("/logs/close")
    def post_close(request: Request, cmd: CloseDayCommand) -> dict:
        """Count a business date from the event stream and freeze it.

        Closing a date that is already closed returns the stored log unchanged: the log is what
        every episode is checked against, so letting it drift would let an episode become
        grounded after the fact.
        """
        return close_daily_log(
            request.app.state.engine,
            request.app.state.settings.timezone,
            cmd.business_date,
            str(cmd.command_id),
        )

    @router.get("/logs/{log_id}")
    def get_log(
        request: Request,
        log_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        log = get_daily_log(request.app.state.engine, log_id)
        if log is None:
            raise HTTPException(status_code=404, detail="Jurnalul nu există")
        return log

    @router.get("/episodes")
    def get_episodes(
        request: Request,
        log_id: Annotated[str | None, Query(max_length=36)] = None,
    ) -> dict:
        return {"episodes": list_episodes(request.app.state.engine, log_id=log_id)}

    @router.post("/episodes/write")
    def post_write(request: Request, cmd: WriteEpisodeCommand) -> dict:
        """Draft the episode for one closed day, checked against that day's events."""
        try:
            return write_episode(
                request.app.state.engine,
                request.app.state.registry,
                cmd.log_id,
                str(cmd.command_id),
                agent_id=str(cmd.agent_id) if cmd.agent_id else None,
            )
        except NothingHappened as exc:
            # A quiet day is a fact, not an error to work around.
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except EpisodeNotGrounded as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except StoryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @router.get("/episodes/{episode_id}/grounding")
    def get_grounding(
        request: Request,
        episode_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        """Re-check a stored episode against its day, so the claim can be audited."""
        try:
            return grounding_report(request.app.state.engine, episode_id)
        except StoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/episodes/{episode_id}/decide")
    def post_decide(
        request: Request,
        episode_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: EpisodeDecisionCommand,
    ) -> dict:
        if not cmd.approve and not cmd.notes.strip():
            raise HTTPException(
                status_code=422, detail="Scrie de ce respingi episodul; motivul rămâne în istoric."
            )
        try:
            return decide_episode(
                request.app.state.engine,
                episode_id,
                cmd.approve,
                cmd.notes,
                str(cmd.command_id),
            )
        except StoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    return router
