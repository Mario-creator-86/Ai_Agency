"""The serial's approved episode is filmed by itself, whatever the day left of it (2026-10-11).

Measured on a copy of his database on 2026-10-11: episode 043317d3 «The Zero Script Club» was
APPROVED at 12:46 UTC by the Director under his policy, canon episode 1, and had no storyboard.
The stage that approved it (`serial_next`, the run's last) built none by design, and the next
morning's run was the first thing that would; the serial had never made one public episode. The
Owner: «Agenția trebuie să fie autonomă». Since that day the stage readies the episode it
approves and queues its continuation (`app.story.serial_stage._queue_filming`). This pass is
what finishes the work when that did not happen, or did not survive:

- An APPROVED episode with no storyboard for longer than `GRACE_MINUTES`: approved by an older
  studio, by the Owner's hand where no storyboard build followed, or whose build died. Its
  storyboard is built here from its rows (no model: the shots keep the series' look they are
  composed with, and the video editor's model describes them when the media stage asks), and
  the one continuation of that storyboard is queued under the key the stage uses
  (`serial_continuation_key`), so stage and pass never queue twice. The grace is for the stage
  itself, which builds the storyboard right after the approval: a pass arriving in between
  would race it and build a second one.
- A serial storyboard APPROVED, with no finished render, that nothing walked since this studio
  process started: walked once after each start, as the sibling pass walks the factual films
  (`owner_choice_continuation`), so a restart during its walk never strands it until the next
  morning. A walk of one film leaves `runbook.film_continued`; the day's media stage leaves no
  film state for a serial film, so the day's own run since the start counts as the walk of
  every episode told before that day (`serial_films_due` takes them) whose storyboard stood
  when the run started: one built after it, by the Owner's hand on the story page in the
  afternoon, was never seen by that run and is walked here. Not a film whose last walk
  stopped on something only the Owner lifts (`runbook.stages.OWNER_DECIDES`): his answer
  queues its own continuation. A walk stopped by the sheet's own work (NEEDS_SHOT_PLAN,
  LINT_BLOCKED) is walked again after a start, as the factual films are
  (`owner_choice_continuation`): a restart usually brings the code that fixes what stopped
  it, and the walk buys nothing on a refused sheet.

Nothing here buys: the walk asks for anything paid under his rule, behind his stop, safe mode
and his mode; PRODUCTION only (`app.services.queue_film_continue`). Finishing an episode his
run approved is unfinished work, not new work: nothing new is started here (his rule: new work
starts at the 05:00 run or on his «Pornește rularea de azi»).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How long an APPROVED episode may stand with no storyboard before this pass builds it: the
#: stage that approved it builds one within seconds; longer than this, nothing will.
GRACE_MINUTES = 15
#: How far back an episode or a storyboard is looked for.
LOOKBACK_DAYS = 7
#: What a walk of one film leaves (`runbook.stages.continue_film`).
WALKED_EVENT = "runbook.film_continued"
#: The event an approval leaves, whoever approved (the Director under policy, or the Owner).
APPROVED_EVENT = "story.episode_approved"
#: When this studio process loaded the pass (the first watchdog after the start).
STARTED_AT = datetime.now(UTC)


def after_start_key(storyboard_id: str, started: str) -> str:
    """The key of the one walk a standing serial storyboard gets after a start."""
    return f"film-continue-{storyboard_id}-serial-after-start-{started}"


@watchdog_pass("serial_unfilmed", order=160, on_error={"readied": [], "queued": []})
def finish_approved_episodes(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.models import Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.runbook.models import DailyRun  # noqa: PLC0415
    from app.runbook.stages import OWNER_DECIDES  # noqa: PLC0415 - runbook imports workflows
    from app.services import FILM_CONTINUE_TASK, queue_film_continue  # noqa: PLC0415
    from app.story.models import DailyStudioLog, StoryEpisode  # noqa: PLC0415
    from app.story.serial_stage import (  # noqa: PLC0415 - story imports media
        SERIAL_APPROVED_CAUSE,
        ready_for_filming,
        serial_continuation_key,
    )
    from app.story.services import SERIES_KEY  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    now = datetime.now(UTC)
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    grace = (now - timedelta(minutes=GRACE_MINUTES)).isoformat()
    started = STARTED_AT.isoformat()
    readied: list[str] = []
    not_readied: list[dict[str, str]] = []
    owed: list[tuple[str, str, str]] = []

    with Session(context.engine) as session:

        def queued(key: str) -> bool:
            return (
                session.scalar(select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key))
                is not None
            )

        def approved_at(episode: StoryEpisode) -> str:
            moment = session.scalar(
                select(DomainEvent.timestamp)
                .where(
                    DomainEvent.event_type == APPROVED_EVENT,
                    DomainEvent.aggregate_id == episode.id,
                )
                .order_by(DomainEvent.sequence.desc())
                .limit(1)
            )
            return str(moment or episode.created_at)

        # Episodes approved and left with no storyboard longer than the stage needs.
        standing = [
            (episode.id, approved_at(episode))
            for episode in session.scalars(
                select(StoryEpisode)
                .where(
                    StoryEpisode.status == "APPROVED",
                    StoryEpisode.storyboard_id.is_(None),
                    StoryEpisode.created_at >= since,
                )
                .order_by(StoryEpisode.created_at)
            )
        ]
    to_ready = [episode_id for episode_id, moment in standing if moment <= grace]
    for episode_id in to_ready:
        storyboard_id, refusal = ready_for_filming(
            context.engine, episode_id, context.correlation_id
        )
        if storyboard_id is None:
            not_readied.append({"episode_id": episode_id, "reason": str(refusal or "")[:200]})
            continue
        readied.append(episode_id)
        owed.append((storyboard_id, serial_continuation_key(storyboard_id), SERIAL_APPROVED_CAUSE))
    just_built = {storyboard_id for storyboard_id, _key, _cause in owed}

    with Session(context.engine) as session:
        # The day's own run since the start walks the serial films due before its date, among
        # the films standing when it started. A storyboard built after that run started was
        # never seen by it: the common hour of the Owner's hand, approving yesterday's episode
        # in the afternoon on the story page, which builds the storyboard at once, long after
        # the 05:00 run (review of 2026-10-11: the pass took that run for the walk and left
        # the episode to the next morning).
        day = session.execute(
            select(DailyRun.business_date, DailyRun.started_at)
            .where(DailyRun.started_at >= started)
            .order_by(DailyRun.started_at.desc())
            .limit(1)
        ).first()
        run_date = str(day[0]) if day is not None else None
        run_started = str(day[1]) if day is not None else None
        continued_since_start = {
            str((task.payload or {}).get("storyboard_id") or "")
            for task in session.scalars(
                select(TaskQueueItem).where(
                    TaskQueueItem.task_type == FILM_CONTINUE_TASK,
                    TaskQueueItem.created_at >= started,
                )
            )
        }
        boards = session.scalars(
            select(Storyboard)
            .where(
                Storyboard.status == "APPROVED",
                Storyboard.series_key == SERIES_KEY,
                Storyboard.created_at >= since,
            )
            .order_by(Storyboard.created_at)
        ).all()
        told_on = {
            storyboard_id: date
            for storyboard_id, date in session.execute(
                select(StoryEpisode.storyboard_id, DailyStudioLog.business_date)
                .join(DailyStudioLog, DailyStudioLog.id == StoryEpisode.log_id)
                .where(StoryEpisode.storyboard_id.in_([board.id for board in boards]))
            )
        }
        for board in boards:
            if board.id in just_built or board.id in continued_since_start:
                continue
            if (
                run_date is not None
                and run_started is not None
                and str(board.created_at) < run_started
                and str(told_on.get(board.id) or "") < run_date
            ):
                continue  # the day's run of this process took it (`serial_films_due`)
            rendered = session.scalar(
                select(VideoRenderJob.id)
                .where(
                    VideoRenderJob.storyboard_id == board.id,
                    VideoRenderJob.status == "COMPLETED",
                )
                .limit(1)
            )
            if rendered is not None:
                continue
            walks = session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == WALKED_EVENT, DomainEvent.aggregate_id == board.id)
                .order_by(DomainEvent.sequence.desc())
                .limit(1)
            ).first()
            if walks is not None:
                if str(walks.timestamp) >= started:
                    continue
                if str((walks.payload or {}).get("refusal") or "") in OWNER_DECIDES:
                    continue
            key = after_start_key(board.id, started)
            if queued(key):
                continue
            owed.append((board.id, key, "serial_unfilmed_after_start"))

    if not owed:
        return {"readied": readied, "queued": [], "not_readied": not_readied}
    done: list[str] = []
    with Session(context.engine) as session, session.begin():
        # Written only when something is owed, so a quiet pass takes no write lock.
        lock_for_write(session)
        for storyboard_id, key, cause in owed:
            standing_task = session.scalar(
                select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key)
            )
            if standing_task is not None:
                continue  # the stage queued it between the read above and this write
            if queue_film_continue(session, storyboard_id, key=key, payload={"cause": cause}):
                done.append(storyboard_id)
    return {"readied": readied, "queued": done, "not_readied": not_readied}
