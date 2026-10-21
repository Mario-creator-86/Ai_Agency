"""The day's goal keeps the day going (2026-10-15, 15:20Z): a short and a serial episode out
on a channel, or a problem only the Owner can solve."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.models import OwnerPolicy
from app.publishing.models import ChannelRecord, PublicationRecord
from app.runbook.models import DailyRun
from app.services import utc_now
from app.story.services import business_date
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext
from app.workflows.passes.day_goal import (
    DAY_GOAL_GAP_MINUTES,
    DAY_GOAL_RUNS_PER_DAY,
    LETTER_SUBJECT,
    day_goal,
    keep_the_day_going,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

TZ = "Europe/Bucharest"


def _production(engine) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.autonomy_stopped = False


def _pass(engine, settings) -> dict[str, Any]:
    return dict(keep_the_day_going(WatchdogContext(engine, settings, "watchdog")))


def _finished_run(engine, date_iso: str, minutes_ago: float = 60) -> None:
    ended = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date=date_iso,
                preflight_status="OK",
                preflight_json={},
                status="COMPLETED",
                stages_json=[],
                stages_total=13,
                stages_completed=13,
                started_at=ended,
                finished_at=ended,
            )
        )


def _published(engine, *, serial: bool) -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        asset_id, board_id = str(uuid4()), str(uuid4())
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                provider_name="SCENE_TAKES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        from app.factual.models import ScriptDraft, TopicIdea

        topic_id, script_id = str(uuid4()), str(uuid4())
        session.add(
            TopicIdea(
                id=topic_id,
                title="a topic",
                topic="a topic",
                angle="an angle",
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                title="a film",
                voiceover_full_text="text",
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title="a film",
                status="RENDERED",
                total_scenes=1,
                visual_bible_json={},
                series_key="office_serial" if serial else None,
                created_at=now,
            )
        )
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board_id,
                status="COMPLETED",
                output_asset_id=asset_id,
                started_at=now,
                finished_at=now,
            )
        )
        channel = session.scalar(select(ChannelRecord))
        if channel is None:
            channel = ChannelRecord(id=str(uuid4()), channel_name="Nexus", created_at=now)
            session.add(channel)
            session.flush()
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                media_asset_id=asset_id,
                channel_id=channel.id,
                title="a film",
                description="",
                status="PUBLISHED",
                privacy_status="public",
                idempotency_key=f"pub-{asset_id}",
                created_at=now,
            )
        )


def _queued_runs(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = session.scalars(
            select(TaskQueueItem).where(TaskQueueItem.task_type == "DAILY_RUN")
        ).all()
        session.expunge_all()
        return list(rows)


def test_the_day_is_run_again_until_a_short_and_an_episode_are_out(engine, settings):
    today = business_date(TZ)
    _production(engine)
    _finished_run(engine, today)

    first = _pass(engine, settings)

    assert first["queued"] and first["run"] == 1 and first["goal"]["met"] is False
    (task,) = _queued_runs(engine)
    assert task.payload["manual"] is True and task.payload["cause"] == "day_goal"
    assert task.idempotency_key == f"day-goal-{today}-1"
    # Queued: not again while it waits.
    assert _pass(engine, settings)["why"] == "a run is queued"


def test_nothing_is_queued_once_both_are_out_or_while_the_day_works(engine, settings):
    today = business_date(TZ)
    _production(engine)
    _published(engine, serial=False)
    _finished_run(engine, today)
    assert _pass(engine, settings)["queued"]  # the episode is still owed
    with Session(engine) as session, session.begin():
        for row in session.scalars(select(TaskQueueItem)):
            row.status = "COMPLETED"
    _published(engine, serial=True)

    outcome = _pass(engine, settings)

    assert outcome["why"] == "met" and outcome["goal"] == {"short": 1, "serial": 1, "met": True}
    with Session(engine) as session:
        assert day_goal(session, today)["met"] is True


def test_the_gap_a_running_day_and_a_film_at_work_hold_the_next_run(engine, settings):
    today = business_date(TZ)
    _production(engine)
    _finished_run(engine, today, minutes_ago=DAY_GOAL_GAP_MINUTES - 1)
    assert _pass(engine, settings)["why"] == "the last run just ended"
    with Session(engine) as session, session.begin():
        session.add(
            TaskQueueItem(
                id=str(uuid4()),
                task_type="FILM_CONTINUE",
                payload={"storyboard_id": "x"},
                priority=5,
                status="CLAIMED",
                attempts=1,
                max_attempts=1,
                backoff_seconds=5,
                next_attempt_at=utc_now(),
                idempotency_key="film-x",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    _finished_run(engine, today, minutes_ago=60)
    assert _pass(engine, settings)["why"] == "a film is at work"


def test_after_the_days_runs_the_owner_gets_one_letter(engine, settings):
    from app.agents.models import AgentMessage

    today = business_date(TZ)
    _production(engine)
    _finished_run(engine, today)
    for n in range(DAY_GOAL_RUNS_PER_DAY):
        outcome = _pass(engine, settings)
        assert outcome["run"] == n + 1, outcome
        with Session(engine) as session, session.begin():
            for row in session.scalars(select(TaskQueueItem)):
                row.status = "COMPLETED"

    stopped = _pass(engine, settings)

    assert stopped["queued"] is None and stopped["letter"] is True
    assert "rulări pornite de studio azi" in stopped["why"]
    assert _pass(engine, settings)["letter"] is False  # said once
    with Session(engine) as session:
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.subject == LETTER_SUBJECT)
        ).all()
        assert len(letters) == 1 and letters[0].to_agent_id is None
