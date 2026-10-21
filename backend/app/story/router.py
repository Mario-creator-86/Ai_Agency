"""Phase 9 routes — the daily log, and the serial drawn from it."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.media.serial_storyboard import SerialStoryboardError, storyboard_from_episode
from app.security import require_owner
from app.services import CommandConflict
from app.story.review import ReviewError, review_episode
from app.story.serial_stage import DayNotTold, tell_day_now
from app.story.services import (
    EpisodeNotGrounded,
    NothingHappened,
    StoryError,
    close_daily_log,
    close_previous_day,
    decide_episode,
    get_continuity,
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


class CommandOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID


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

    @router.post("/logs/close-previous")
    def post_close_previous(request: Request, cmd: CommandOnly) -> dict:
        """Close yesterday's log with every event of that day; a closed one is returned as is."""
        return close_previous_day(
            request.app.state.engine, request.app.state.settings, str(cmd.command_id)
        )

    @router.get("/continuity")
    def get_continuity_state(request: Request) -> dict:
        """The serial's memory: canon episode number, open threads, recent summaries."""
        return get_continuity(request.app.state.engine)

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

    @router.post("/logs/{log_id}/tell")
    def post_tell(
        request: Request,
        log_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: CommandOnly,
    ) -> dict:
        """The Owner's «Scrie episodul», to the end: written, read by the Director, approved
        under the channel's policy, storyboarded, its filming queued (`tell_day_now`).

        Until 2026-10-13 the button was `/episodes/write` alone, and the draft it made waited
        for the next run's stage to be read. That route still drafts alone. Idempotent by the
        command id. A state that refuses the press — a quiet day, the Owner's stop, a day
        that has its episode or used its drafts, an episode waiting for him, no model, the
        same id reused with another day — is 409 with the studio's sentence; an answer
        refused before it was stored is 422, as the write route says it.
        """
        state = request.app.state
        try:
            return tell_day_now(
                state.engine, state.registry, state.settings, log_id, str(cmd.command_id)
            )
        except (DayNotTold, NothingHappened, CommandConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
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

    @router.post("/episodes/{episode_id}/review")
    def post_review(
        request: Request,
        episode_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: CommandOnly,
    ) -> dict:
        """The Director reads a drafted episode; approval follows only under channel policy."""
        try:
            return review_episode(
                request.app.state.engine,
                request.app.state.registry,
                episode_id,
                str(cmd.command_id),
                language=request.app.state.settings.content_language,
            )
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @router.post("/episodes/{episode_id}/storyboard")
    def post_storyboard(
        request: Request,
        episode_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: CommandOnly,
    ) -> dict:
        """Turn an APPROVED episode into the storyboard the film path shoots."""
        try:
            board_id = storyboard_from_episode(
                request.app.state.engine, episode_id, str(cmd.command_id)
            )
        except SerialStoryboardError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return {"episode_id": episode_id, "storyboard_id": board_id}

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
        engine = request.app.state.engine
        try:
            decided = decide_episode(
                engine, episode_id, cmd.approve, cmd.notes, str(cmd.command_id)
            )
        except StoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        if not cmd.approve:
            return decided
        # His approval used to flip the status and stop there: nothing built the storyboard,
        # and the serial stage never went back to a day that had an episode, so an episode he
        # approved was never filmed (measured 2026-09-24). The storyboard is rows, no vendor
        # is called; the next run's media stage films it. Should it fail, the approval
        # stands, the reason is returned, and the next run's serial stage tries again.
        try:
            decided["storyboard_id"] = storyboard_from_episode(
                engine, episode_id, str(cmd.command_id)
            )
        except SerialStoryboardError as exc:
            decided["storyboard_error"] = str(exc)
        return decided

    return router
