"""An approved episode of the serial is filmed by itself, the same day (2026-10-11).

Measured on a copy of the Owner's database on 2026-10-11: the first episode the Director ever
approved under his policy (043317d3, «The Zero Script Club», canon episode 1, 12:46 UTC) had
no storyboard. The stage that approved it (`serial_next`, the run's last) built none by
design, so the next morning's run was the first thing that would film it, and the serial had
never made one public episode. The Owner: «Agenția trebuie să fie autonomă».

What is held here, with every provider faked and no network:

- the evening's stage readies the episode it approves (storyboard, shots) and, in PRODUCTION,
  queues the one FILM_CONTINUE that walks it tonight under his money rules; in TEST nothing
  continues and the next run films it; a same-day re-run queues nothing twice and finishes an
  approved episode an older run left with no storyboard;
- the watchdog pass `serial_unfilmed` builds the storyboard of an episode approved longer than
  its grace with none, queues the same continuation once, and walks a standing serial
  storyboard once after each start, unless the day's own run or a walk already took it, or its
  last walk stopped on the Owner's money.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import app.workflows.passes.serial_unfilmed as unfilmed
import pytest
from app.agents.services import seed_initial_workforce
from app.media.models import Storyboard
from app.media.serial_storyboard import storyboard_from_episode
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.publishing.services import seed_default_channels
from app.runbook.models import DailyRun
from app.runbook.stages import serial_films_due
from app.services import FILM_CONTINUE_TASK, append_event, utc_now
from app.story.serial_stage import (
    SERIAL_APPROVED_CAUSE,
    run_serial_stage,
    serial_continuation_key,
)
from app.story.services import business_date, decide_episode
from app.workflows.models import TaskQueueItem
from app.workflows.passes import WatchdogContext, registered_passes
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    TZ,
    allow_director_approval,
    episode_rows,
    registry,
    run_serial_next,
    storyboard_count,
    todays_episode,
    tomorrow_is,
    waiting_for_the_owner,
)


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def production(engine) -> None:
    """His studio's environment: only there does a continuation have anything to buy."""
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"


def continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = session.scalars(
            select(TaskQueueItem)
            .where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            .order_by(TaskQueueItem.created_at)
        ).all()
        session.expunge_all()
        return list(rows)


def boards(engine) -> list[Storyboard]:
    with Session(engine) as session:
        rows = session.scalars(select(Storyboard)).all()
        session.expunge_all()
        return list(rows)


def films_due(engine, date_iso: str) -> list[str]:
    with Session(engine) as session:
        return serial_films_due(session, list(session.scalars(select(Storyboard))), date_iso)


def the_grace_has_passed(monkeypatch) -> None:
    """The pass's clock, moved past the grace: the ledger is immutable (an approval's event
    cannot be dated back), so the grace is shortened to nothing instead."""
    monkeypatch.setattr(unfilmed, "GRACE_MINUTES", 0)


def approved_moments_ago(engine, episode_id: str) -> str:
    """The approval's own event, as the pass reads it: when the episode was approved."""
    with Session(engine) as session:
        moment = session.scalar(
            select(DomainEvent.timestamp).where(
                DomainEvent.event_type == unfilmed.APPROVED_EVENT,
                DomainEvent.aggregate_id == episode_id,
            )
        )
    assert moment, "the approval left no event"
    return str(moment)


def a_walk(engine, storyboard_id: str, *, refusal: str | None, status: str = "SKIPPED") -> None:
    """What `runbook.stages.continue_film` leaves of one walk of the film."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            unfilmed.WALKED_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {"status": status, "reason": "test", "cause": "test", "refusal": refusal},
            str(uuid4()),
        )


def a_days_run(engine, date_iso: str) -> None:
    """A daily run of this studio process, as the runbook records one."""
    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date=date_iso,
                preflight_status="OK",
                preflight_json={},
                status="COMPLETED",
                stages_json=[],
                stages_total=0,
                stages_completed=0,
                started_at=utc_now(),
                finished_at=utc_now(),
            )
        )


def the_pass(engine, settings) -> dict:
    return unfilmed.finish_approved_episodes(WatchdogContext(engine, settings, str(uuid4())))


def an_approved_episode_with_no_storyboard(engine, monkeypatch, settings) -> str:
    """Yesterday's episode, passed by the Director and approved by the Owner's hand, as the
    story page approved one before it built the storyboard too."""
    first, _, _ = waiting_for_the_owner(engine, monkeypatch, settings)
    episode_id = first["artefacts"]["episode_id"]
    decide_episode(engine, episode_id, True, "")
    return episode_id


# ------------------------------------------------------------------ the evening's stage --


def test_the_evening_stage_readies_the_episode_it_approved_and_queues_its_filming(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    production(engine)

    log, outcome, written_, reviewed = todays_episode(engine, monkeypatch, settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["approved"] == 1 and artefacts["storyboard_id"], artefacts
    (row,) = episode_rows(engine)
    assert row.status == "APPROVED" and row.storyboard_id == artefacts["storyboard_id"]
    assert storyboard_count(engine) == 1
    (task,) = continuations(engine)
    assert task.id == artefacts["film_continue_task_id"]
    assert task.status == "QUEUED" and task.max_attempts == 1
    assert task.idempotency_key == serial_continuation_key(row.storyboard_id)
    assert task.payload == {
        "storyboard_id": row.storyboard_id,
        "cause": SERIAL_APPROVED_CAUSE,
        "episode_id": row.id,
    }
    assert "pregătit de filmare" in outcome["reason"] and "coadă" in outcome["reason"]
    # The day's own media stage still films a serial episode only once its day is over: the
    # continuation is what films it tonight, and a same-day re-run buys nothing twice.
    assert films_due(engine, log["business_date"]) == []
    assert films_due(engine, tomorrow_is(monkeypatch)) == [row.storyboard_id]
    assert len(written_) == 1 and len(reviewed) == 1


def test_in_test_the_storyboard_is_built_and_the_filming_waits_for_the_next_run(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)

    _, outcome, _, _ = todays_episode(engine, monkeypatch, settings)

    artefacts = outcome["artefacts"]
    assert artefacts["storyboard_id"] and artefacts["film_continue_task_id"] is None
    assert storyboard_count(engine) == 1 and continuations(engine) == []
    assert "pregătit de filmare" in outcome["reason"] and "mâine" in outcome["reason"]


def test_a_same_day_rerun_queues_the_continuation_once(engine, staffed, settings, monkeypatch):
    allow_director_approval(engine)
    production(engine)
    _, first, written_, _ = todays_episode(engine, monkeypatch, settings)

    again = run_serial_next(engine, registry(), settings)

    assert again["artefacts"]["written"] == 0 and "deja scris" in again["reason"], again
    assert again["artefacts"]["storyboard_id"] is None
    assert storyboard_count(engine) == 1 and len(written_) == 1
    (task,) = continuations(engine)
    assert task.id == first["artefacts"]["film_continue_task_id"]


def test_an_episode_an_older_run_approved_with_no_storyboard_is_readied_by_the_rerun(
    engine, staffed, settings, monkeypatch
):
    """His data on 2026-10-11: today's episode APPROVED by a stage that built no storyboard.
    His «Pornește rularea de azi» finishes it instead of saying «deja scris» until tomorrow."""
    production(engine)
    _, outcome, _, _ = todays_episode(engine, monkeypatch, settings)  # no leave: DRAFT, PASS
    episode_id = outcome["artefacts"]["episode_id"]
    decide_episode(engine, episode_id, True, "")
    assert storyboard_count(engine) == 0

    again = run_serial_next(engine, registry(), settings)

    assert again["status"] == "COMPLETED", again
    artefacts = again["artefacts"]
    assert artefacts["resumed"] == "storyboard" and artefacts["episode_id"] == episode_id
    assert artefacts["written"] == 0 and artefacts["storyboard_id"]
    (row,) = episode_rows(engine)
    assert row.storyboard_id == artefacts["storyboard_id"]
    (task,) = continuations(engine)
    assert task.idempotency_key == serial_continuation_key(row.storyboard_id)
    assert "pregătit de filmare acum" in again["reason"] and "coadă" in again["reason"]


def test_the_morning_after_writes_nothing_and_the_film_is_that_days(
    engine, staffed, settings, monkeypatch
):
    """Readied the evening before, the episode leaves the morning's serial stage nothing to
    take up; its film is the media stage's that morning (`serial_films_due`)."""
    allow_director_approval(engine)
    _, first, written_, reviewed = todays_episode(engine, monkeypatch, settings)
    tomorrow = tomorrow_is(monkeypatch)

    morning = run_serial_stage(engine, registry(), settings)

    assert morning["status"] == "COMPLETED", morning
    assert morning["artefacts"]["resumed"] is None and morning["artefacts"]["written"] == 0
    assert "Ultima zi povestită" in morning["reason"]
    assert storyboard_count(engine) == 1 and len(written_) == 1 and len(reviewed) == 1
    assert films_due(engine, tomorrow) == [first["artefacts"]["storyboard_id"]]


# ------------------------------------------------------------------- the watchdog pass --


def test_the_pass_runs_after_the_owner_choice_continuation():
    names = [entry.name for entry in registered_passes()]
    assert names.index("serial_unfilmed") > names.index("owner_choice_continuation")
    (entry,) = [entry for entry in registered_passes() if entry.name == "serial_unfilmed"]
    assert entry.order == 160 and entry.on_error == {"readied": [], "queued": []}


def test_the_pass_finishes_an_episode_approved_longer_than_the_grace(
    engine, staffed, settings, monkeypatch
):
    production(engine)
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    assert approved_moments_ago(engine, episode_id) <= datetime.now(UTC).isoformat()
    the_grace_has_passed(monkeypatch)

    outcome = the_pass(engine, settings)

    assert outcome["readied"] == [episode_id], outcome
    (row,) = episode_rows(engine)
    assert row.storyboard_id and outcome["queued"] == [row.storyboard_id]
    (board,) = boards(engine)
    assert board.id == row.storyboard_id and board.series_key == "office_serial"
    (task,) = continuations(engine)
    assert task.idempotency_key == serial_continuation_key(row.storyboard_id)
    assert task.payload == {"storyboard_id": row.storyboard_id, "cause": SERIAL_APPROVED_CAUSE}

    # Minutes later: the same rows, nothing a second time.
    again = the_pass(engine, settings)
    assert again == {"readied": [], "queued": [], "not_readied": []}
    assert storyboard_count(engine) == 1 and len(continuations(engine)) == 1


def test_a_fresh_approval_is_left_to_the_stage_that_made_it(engine, staffed, settings, monkeypatch):
    production(engine)
    an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)

    outcome = the_pass(engine, settings)

    assert outcome == {"readied": [], "queued": [], "not_readied": []}
    assert storyboard_count(engine) == 0 and continuations(engine) == []


def test_in_test_the_pass_readies_and_queues_nothing(engine, staffed, settings, monkeypatch):
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    the_grace_has_passed(monkeypatch)

    outcome = the_pass(engine, settings)

    assert outcome["readied"] == [episode_id] and outcome["queued"] == []
    assert storyboard_count(engine) == 1 and continuations(engine) == []


def test_the_stage_and_the_pass_queue_one_continuation_between_them(
    engine, staffed, settings, monkeypatch
):
    """The key is the storyboard's: whichever of the two reaches the queue first, the other
    finds the standing task and queues nothing beside it."""
    allow_director_approval(engine)
    production(engine)
    _, first, _, _ = todays_episode(engine, monkeypatch, settings)

    outcome = the_pass(engine, settings)

    assert outcome["queued"] == [] and outcome["readied"] == []
    (task,) = continuations(engine)
    assert task.id == first["artefacts"]["film_continue_task_id"]


def test_a_standing_serial_storyboard_is_walked_once_after_a_start(
    engine, staffed, settings, monkeypatch
):
    production(engine)
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))

    outcome = the_pass(engine, settings)

    assert outcome["queued"] == [board_id] and outcome["readied"] == []
    (task,) = continuations(engine)
    assert task.idempotency_key == unfilmed.after_start_key(
        board_id, unfilmed.STARTED_AT.isoformat()
    )
    assert task.payload == {"storyboard_id": board_id, "cause": "serial_unfilmed_after_start"}
    assert the_pass(engine, settings)["queued"] == [] and len(continuations(engine)) == 1

    # The studio restarted: the worker's walk of the film (its continuation's event) is what
    # tells this start the film was taken; without one it is walked once more.
    monkeypatch.setattr(unfilmed, "STARTED_AT", datetime.now(UTC))
    a_walk(engine, board_id, refusal=None, status="COMPLETED")
    assert the_pass(engine, settings)["queued"] == []
    monkeypatch.setattr(unfilmed, "STARTED_AT", datetime.now(UTC) + timedelta(seconds=1))
    assert the_pass(engine, settings)["queued"] == [board_id]
    assert len(continuations(engine)) == 2


def test_a_film_whose_walk_stopped_on_the_owners_money_is_not_walked_again(
    engine, staffed, settings, monkeypatch
):
    production(engine)
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))
    a_walk(engine, board_id, refusal="OVER_BUDGET")
    monkeypatch.setattr(unfilmed, "STARTED_AT", datetime.now(UTC) + timedelta(seconds=1))

    assert the_pass(engine, settings)["queued"] == []

    # Stopped on something of the studio's own: walked again, once.
    a_walk(engine, board_id, refusal="TAKES_NOT_ACCEPTED")
    assert the_pass(engine, settings)["queued"] == [board_id]
    assert the_pass(engine, settings)["queued"] == []


def test_the_days_own_run_since_the_start_counts_as_the_walk(
    engine, staffed, settings, monkeypatch
):
    """The day's media stage walks every serial film told before its date and leaves no film
    state for it: a run of this process since the start is that walk."""
    production(engine)
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))
    a_days_run(engine, business_date(TZ))

    assert the_pass(engine, settings)["queued"] == []
    assert continuations(engine) == []

    # A run of an earlier process is not: the film is walked once after this start.
    monkeypatch.setattr(unfilmed, "STARTED_AT", datetime.now(UTC) + timedelta(seconds=1))
    assert the_pass(engine, settings)["queued"] == [board_id]


def test_an_episode_approved_by_hand_after_the_days_run_is_walked_the_same_day(
    engine, staffed, settings, monkeypatch
):
    """The common hour of his hand (2026-10-11 review of the pass): the 05:00 run of this
    process is long over when he approves yesterday's episode in the afternoon, and the story
    page builds its storyboard at once (`story.router.post_decide`). That run never saw the
    board, so it is not the board's walk: the pass walks it at its next tick, not tomorrow."""
    production(engine)
    a_days_run(engine, business_date(TZ))
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))

    assert the_pass(engine, settings)["queued"] == [board_id]

    (task,) = continuations(engine)
    assert task.payload == {"storyboard_id": board_id, "cause": "serial_unfilmed_after_start"}
    assert the_pass(engine, settings)["queued"] == [] and len(continuations(engine)) == 1


def test_a_rendered_storyboard_is_left_alone(engine, staffed, settings, monkeypatch):
    from app.media.models import VideoRenderJob

    production(engine)
    episode_id = an_approved_episode_with_no_storyboard(engine, monkeypatch, settings)
    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board_id,
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={},
            )
        )

    assert the_pass(engine, settings)["queued"] == []
