"""A film the Director's ladder left waiting is walked again by itself (2026-10-11).

The cyclotron film, 14:20:57 UTC: her brief for a refused scene failed, the walk stopped
WAITING NEEDS_OWNER, and nothing retried the ladder until an unrelated take approval at 14:31
ran another continuation (which then succeeded). The Owner: a film is never left waiting for
quality, only money stops it. So the watchdog pass `ladder_retry` finds a film in production
whose newest walk stopped WAITING on a ladder refusal, whose refused scenes are quality control's,
whose newest brief attempt is older than twenty minutes and did not rewrite, with no continuation
queued or at work, and queues one FILM_CONTINUE (cause director_ladder_retry), at most six a day
per film. PRODUCTION only; nothing here buys: the walk asks for anything paid under his rule.
Every provider faked, 0 credits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.agents.memory import agent_for_role
from app.agents.models import AgentRun
from app.agents.services import seed_initial_workforce
from app.media.models import SceneTake, Storyboard
from app.media.scene_rewrite import BRIEF_EVENT, BRIEF_TASK
from app.models import OwnerPolicy
from app.services import FILM_CONTINUE_TASK, append_event, utc_now
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film

FILM_STATE_EVENT = "runbook.film_state"


def production(engine) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"


def moment(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


def written_at(
    engine, minutes_ago: int, event_type: str, storyboard_id: str, payload: dict
) -> None:
    """An event written ``minutes_ago`` (the history is immutable: written then, not moved)."""
    with (
        pytest.MonkeyPatch.context() as patch,
        Session(engine) as session,
        session.begin(),
    ):
        patch.setattr("app.services.utc_now", lambda: moment(minutes_ago))
        append_event(session, event_type, "storyboard", storyboard_id, 1, payload, str(uuid4()))


def stopped(engine, storyboard_id: str, *, minutes_ago: int, refusal: str = "NEEDS_OWNER") -> None:
    """The walk's stop, as `runbook.stages._note_film_state` records it."""
    written_at(
        engine,
        minutes_ago,
        FILM_STATE_EVENT,
        storyboard_id,
        {
            "business_date": "2026-10-11",
            "status": "WAITING",
            "refusal": refusal,
            "step": "test_shot",
            "reason": "după pasul «cadrul de probă», scena 1 așteaptă decizia Proprietarului",
            "moved": False,
        },
    )


def briefed(
    engine, storyboard_id: str, *, minutes_ago: int, rewritten: bool, scene: int = 1
) -> None:
    """Her brief attempt for the scene, as `scene_rewrite._record_brief` records it."""
    written_at(
        engine,
        minutes_ago,
        BRIEF_EVENT,
        storyboard_id,
        {
            "scene_index": scene,
            "layer": "motion" if rewritten else None,
            "rewritten": rewritten,
            "reason": "" if rewritten else "Brief-ul Directoarei nu a respectat forma cerută",
            "failures": [{"code": "QC.CLIP"}],
        },
    )


def refused_by_quality_control(
    engine, storyboard_id: str, scene: int = 1, code: str = "QC.CLIP"
) -> None:
    """The scene's newest take REJECTED by quality control (no vendor, no credits)."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                scene_number=scene,
                kind="test_shot",
                prompt_hash=uuid4().hex,
                model_id="seedance2_5",
                resolution="1080:1920",
                status="REJECTED",
                failure_code=code,
                failure_detail="o față se vede din profil",
                path=None,
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )


def a_waiting_film(engine, tmp_path, *, minutes_ago: int = 30) -> str:
    """A film in production whose walk stopped on a refused scene and whose brief failed."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session:
        assert session.get(Storyboard, storyboard_id).status == "APPROVED"
    production(engine)
    refused_by_quality_control(engine, storyboard_id)
    briefed(engine, storyboard_id, minutes_ago=minutes_ago, rewritten=False)
    stopped(engine, storyboard_id, minutes_ago=minutes_ago)
    return storyboard_id


def run_pass(engine, settings) -> dict[str, Any]:
    from app.workflows.passes.ladder_retry import queue_ladder_retries

    return dict(queue_ladder_retries(WatchdogContext(engine, settings, "watchdog")))


def continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(TaskQueueItem)
                .where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
                .order_by(TaskQueueItem.created_at)
            )
        )
        session.expunge_all()
        return rows


def finish(engine) -> None:
    with Session(engine) as session, session.begin():
        for task in session.scalars(select(TaskQueueItem)):
            task.status = "COMPLETED"


def test_a_film_left_waiting_after_a_failed_brief_is_walked_again_once(engine, settings, tmp_path):
    storyboard_id = a_waiting_film(engine, tmp_path)

    assert run_pass(engine, settings) == {"queued": [storyboard_id]}

    (task,) = continuations(engine)
    assert task.payload["storyboard_id"] == storyboard_id
    assert task.payload["cause"] == "director_ladder_retry"
    assert task.status == "QUEUED"
    # Queued, then at work: nothing more while the walk is owed or running.
    assert run_pass(engine, settings) == {"queued": []}
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task.id).status = "RUNNING"
    assert run_pass(engine, settings) == {"queued": []}
    assert len(continuations(engine)) == 1


def test_the_pass_is_registered_in_its_place_and_queues_nothing_in_test(engine, settings, tmp_path):
    from app.workflows.passes import registered_passes

    (entry,) = [p for p in registered_passes() if p.name == "ladder_retry"]
    assert entry.order == 155 and entry.on_error == {"queued": []}

    storyboard_id = a_waiting_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "TEST"
    assert run_pass(engine, settings) == {"queued": []}
    assert continuations(engine) == []
    production(engine)
    assert run_pass(engine, settings) == {"queued": [storyboard_id]}


def test_a_fresh_attempt_a_rewrite_or_a_brief_being_written_waits(engine, settings, tmp_path):
    # Her attempt five minutes ago: the walk may still be going; twenty minutes first.
    fresh = a_waiting_film(engine, tmp_path, minutes_ago=5)
    assert run_pass(engine, settings) == {"queued": []}

    # Her brief rewrote the scene: the walk itself buys on the new words.
    rewrote = a_film(engine, tmp_path, scenes=1)
    refused_by_quality_control(engine, rewrote)
    briefed(engine, rewrote, minutes_ago=40, rewritten=True)
    stopped(engine, rewrote, minutes_ago=40)
    assert run_pass(engine, settings) == {"queued": []}

    # A brief being written right now, for whichever film: its record comes when it ends.
    old = a_waiting_film(engine, tmp_path, minutes_ago=45)
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        director = agent_for_role(session, "Director")
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=director.id,
                task_type=BRIEF_TASK,
                objective="brief",
                prompt_template_version="director-scene-brief-v1",
                model_name="m",
                provider_name="p",
                status="RUNNING",
                correlation_id=str(uuid4()),
                started_at=utc_now(),
                finished_at=None,
                context_json={},
            )
        )
    assert run_pass(engine, settings) == {"queued": []}
    with Session(engine) as session, session.begin():
        for run in session.scalars(select(AgentRun)):
            run.status = "EMPTY_OUTPUT"
    assert run_pass(engine, settings) == {"queued": [old]}
    assert fresh not in [t.payload["storyboard_id"] for t in continuations(engine)]


def test_a_walk_just_run_waits_and_six_retries_a_day_are_the_limit(
    engine, settings, tmp_path, monkeypatch
):
    from app.workflows.passes import ladder_retry

    storyboard_id = a_waiting_film(engine, tmp_path, minutes_ago=90)
    # The retry walked the film a minute ago and stopped it again without reaching her brief
    # (his stop, safe mode, his mode): not again before the wait.
    written_at(
        engine,
        1,
        "runbook.film_continued",
        storyboard_id,
        {"status": "BLOCKED", "cause": "director_ladder_retry"},
    )
    assert run_pass(engine, settings) == {"queued": []}

    monkeypatch.setattr(ladder_retry, "RETRY_MINUTES", 0)
    for n in range(1, 7):
        assert run_pass(engine, settings) == {"queued": [storyboard_id]}, n
        finish(engine)
    assert run_pass(engine, settings) == {"queued": []}  # the sixth was the last today
    assert len(continuations(engine)) == 6
    assert len({t.idempotency_key for t in continuations(engine)}) == 6


def test_a_film_that_is_not_the_ladders_is_left_alone(engine, settings, tmp_path):
    # Waiting on his money, not on quality control.
    money = a_film(engine, tmp_path, scenes=1)
    production(engine)
    refused_by_quality_control(engine, money)
    briefed(engine, money, minutes_ago=40, rewritten=False)
    stopped(engine, money, minutes_ago=40, refusal="LOW_BALANCE")
    # Its scene refused by the vendor, not by quality control.
    vendor = a_film(engine, tmp_path, scenes=1)
    refused_by_quality_control(engine, vendor, code="SAFETY.SENT_BACK")
    briefed(engine, vendor, minutes_ago=40, rewritten=False)
    stopped(engine, vendor, minutes_ago=40)
    # No brief attempt of hers at all: the walk never reached her, nothing of hers to retry.
    silent = a_film(engine, tmp_path, scenes=1)
    refused_by_quality_control(engine, silent)
    stopped(engine, silent, minutes_ago=40)
    # Closed by the Owner since.
    closed = a_waiting_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, closed).status = "REJECTED"

    assert run_pass(engine, settings) == {"queued": []}
    assert continuations(engine) == []


def test_a_brief_run_of_the_films_continuation_counts_as_the_attempt_when_no_record_exists(
    engine, settings, tmp_path
):
    """Before 2026-10-11 a brief that failed left no BRIEF_EVENT; her run of it, under the
    film's continuation, is the attempt the pass reads."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    production(engine)
    refused_by_quality_control(engine, storyboard_id)
    stopped(engine, storyboard_id, minutes_ago=40)
    seed_initial_workforce(engine)
    walk_id = str(uuid4())
    with Session(engine) as session, session.begin():
        director = agent_for_role(session, "Director")
        session.add(
            TaskQueueItem(
                id=walk_id,
                task_type=FILM_CONTINUE_TASK,
                payload={"storyboard_id": storyboard_id, "cause": "take_approved"},
                priority=4,
                status="COMPLETED",
                attempts=1,
                max_attempts=1,
                backoff_seconds=60,
                next_attempt_at=moment(45),
                idempotency_key=f"film-continue-{storyboard_id}-take",
                created_at=moment(45),
                updated_at=moment(40),
            )
        )
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=director.id,
                task_type=BRIEF_TASK,
                objective="brief",
                prompt_template_version="director-scene-brief-v1+think",
                model_name="m",
                provider_name="p",
                status="EMPTY_OUTPUT",
                correlation_id=walk_id,
                started_at=moment(41),
                finished_at=moment(40),
                context_json={},
            )
        )

    assert run_pass(engine, settings) == {"queued": [storyboard_id]}
