"""The paid-redo cap reached is the Owner's card, not a loop of the Director's (2026-10-12).

«The Particle That Shouldn't Exist (And Briefly Didn't)», 11:51: the Director decided REPAIR
three times in eleven seconds and each time the repair was stopped by his cap («Scena 5: nu se
mai cumpără automat, s-a atins limita de 5 refaceri plătite pe scenă»); the film waited in her
inbox, where the review pass would have put it before her again every hour. Now the repair
proposes his card once per film, with his four answers — more paid redos, publish as it is,
close, wait — and the review pass does not ask her again while the card waits. Every provider
faked; nothing here buys.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.decisions.models import OwnerDecision
from app.decisions.producers.redo_cap import (
    ALLOWANCE_EVENT,
    EXTRA_REDOS,
    KIND,
    dedupe_key,
    propose_redo_cap_card,
    redo_allowance,
)
from app.decisions.services import (
    DecideCommand,
    condition_reading,
    decide_owner_decision,
)
from app.media.director_qc import DECISION_EVENT, decision_state
from app.media.models import QualityControlReport, Storyboard
from app.models import DomainEvent, OwnerPolicy
from app.services import FILM_CONTINUE_TASK, append_event, utc_now
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import failed_film

LIMITED = [{"scene_index": 5, "per_scene": 5, "per_film": 20}]


def _card(engine, ids: dict[str, Any]) -> OwnerDecision:
    card_id = propose_redo_cap_card(
        engine,
        storyboard_id=ids["board"],
        report_id=ids["report"],
        media_asset_id=ids["asset"],
        limited=LIMITED,
        rounds={5: 5},
    )
    assert card_id
    with Session(engine) as session:
        row = session.get(OwnerDecision, card_id)
        assert row is not None
        session.expunge(row)
        return row


def _answer(engine, card: OwnerDecision, option_key: str) -> dict[str, Any]:
    command = DecideCommand(
        command_id=uuid4(),
        expected_version=card.version,
        decision="ACCEPT",
        option_key=option_key,
    )
    return decide_owner_decision(engine, card.id, command, issued_by="owner")


def _continuations(engine, storyboard_id: str) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = [
            task
            for task in session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            )
            if (task.payload or {}).get("storyboard_id") == storyboard_id
        ]
        session.expunge_all()
        return rows


def _production(engine) -> None:
    """A continuation is queued only in PRODUCTION (`queue_film_continue` refuses TEST)."""
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"


def _her_decision(engine, ids: dict[str, Any]) -> None:
    """Her REPAIR of scene 5, on the report's record (what the card quotes)."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            ids["report"],
            1,
            {
                "report_id": ids["report"],
                "storyboard_id": ids["board"],
                "media_asset_id": ids["asset"],
                "decision": "REPAIR",
                "outcome": "NOTHING_DONE",
                "summary": "Scena 5 arată un turn cu schele, nu caverna detectorului.",
            },
            str(uuid4()),
        )


def test_the_cap_reached_is_one_card_with_his_four_answers(engine):
    ids = failed_film(engine, local_move=False)
    _her_decision(engine, ids)

    card = _card(engine, ids)

    assert card.kind == KIND and card.status == "PENDING"
    assert card.dedupe_key == dedupe_key(ids["board"])
    assert "limita de refaceri plătite" in card.title_ro and "scena 5" in card.title_ro
    assert "5 din 5" in card.why_ro and "turn cu schele" in card.why_ro
    assert [option["key"] for option in card.options] == ["allow", "publish", "close", "wait"]
    assert card.options[0]["recommended"] is True
    assert card.options[0]["apply"]["extra"] == EXTRA_REDOS
    # Asked once: the same card stands while it waits.
    assert _card(engine, ids).id == card.id
    with Session(engine) as session:
        assert condition_reading(session, card, None) != "MET"


def test_his_allow_moves_the_cap_and_queues_her_repair_again(engine):
    ids = failed_film(engine, local_move=False)
    _production(engine)
    card = _card(engine, ids)

    done = _answer(engine, card, "allow")

    assert done["decision"]["status"] == "ACCEPTED", done
    with Session(engine) as session:
        assert redo_allowance(session, ids["board"]) == EXTRA_REDOS
        (granted,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == ALLOWANCE_EVENT)
        ).all()
        assert granted.payload["granted_by"] == "owner" and granted.aggregate_id == ids["board"]
        # Answered: the question is gone (an allowance since the card).
        row = session.get(OwnerDecision, card.id)
        assert condition_reading(session, row, None) == "MET"
    (task,) = _continuations(engine, ids["board"])
    assert task.payload["cause"] == f"director_qc:{ids['report']}" and task.status == "QUEUED"


def test_his_publish_as_is_passes_the_film_by_his_decision_and_queues_its_publication(engine):
    ids = failed_film(engine, local_move=False)
    _production(engine)
    card = _card(engine, ids)

    done = _answer(engine, card, "publish")

    assert done["decision"]["status"] == "ACCEPTED", done
    with Session(engine) as session:
        passed = session.scalar(
            select(QualityControlReport).where(
                QualityControlReport.media_asset_id == ids["asset"],
                QualityControlReport.status == "PASSED",
            )
        )
        assert passed is not None
        assert passed.checks_json["director_qc"]["decided_by"] == "owner"
        assert passed.checks_json["director_qc"]["decision"] == "ACCEPT"
        assert passed.checks_json["director_qc"]["original_status"] == "FAILED"
    state = decision_state(engine, ids["report"])
    assert state["final"] is True and state["outcome"] == "ACCEPTED"
    assert state["decision"]["decided_by"] == "owner"
    (task,) = _continuations(engine, ids["board"])
    assert task.payload["cause"] == f"director_qc:{ids['report']}"


def test_his_close_retires_the_film_with_its_books(engine):
    ids = failed_film(engine, local_move=False)
    card = _card(engine, ids)

    done = _answer(engine, card, "close")

    assert done["decision"]["status"] == "ACCEPTED", done
    with Session(engine) as session:
        assert session.get(Storyboard, ids["board"]).status == "REJECTED"
        row = session.get(OwnerDecision, card.id)
        assert condition_reading(session, row, None) == "MET"
    state = decision_state(engine, ids["report"])
    assert state["outcome"] == "CLOSED"


def test_the_review_pass_does_not_ask_her_again_while_his_card_waits(engine, settings):
    from app.workflows.passes import WatchdogContext
    from app.workflows.passes.director_qc_review import queue_director_reviews

    ids = failed_film(engine, local_move=False)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"

    def run_pass() -> list[str]:
        return list(queue_director_reviews(WatchdogContext(engine, settings, "watchdog"))["queued"])

    card = _card(engine, ids)
    assert run_pass() == [], "she was asked again while his card waited"

    # His answer closes the card; the film is hers again (the review pass may queue it).
    _answer(engine, card, "wait")
    assert run_pass() == [ids["board"]]
    assert utc_now() > card.created_at


def _delivered_round(engine, ids: dict[str, Any], scene: int) -> None:
    """One paid round of the scene that made a still (approved, with its file)."""
    import time

    from app.runbook import stages
    from test_director_decides_qc import _take

    time.sleep(0.01)
    began = utc_now()
    with Session(engine) as session, session.begin():
        append_event(
            session,
            stages.QC_PAID_REDO_EVENT,
            "storyboard",
            ids["board"],
            1,
            {"scene_index": scene, "of_asset": ids["asset"], "started_at": began},
            str(uuid4()),
        )
        _take(session, ids["board"], scene, "still", None)


def test_the_card_is_moot_once_the_rounds_counted_again_fall_below_his_cap(engine, settings):
    """1c038a99 (2026-10-12): the card said «scena 5: 5 din 5», but two of the five rounds
    had been stopped by a restart and one cancelled after a second. Counted by what they made,
    the scene stood at two: the question is not his to answer, and the film goes on under his
    original limits. A card whose rounds really reached the cap stays."""
    settings.film_max_paid_redos_per_scene = 2
    settings.film_max_paid_redos = 20
    ids = failed_film(engine, local_move=False)
    _her_decision(engine, ids)
    card = _card(engine, ids)
    assert card.clears_when["scenes"] == [5]

    with Session(engine) as session:
        # No round of scene 5 delivered anything: the cap was never reached.
        assert condition_reading(session, card, settings) == "MET"
        # Without the limits to read, the card is kept (fail closed).
        assert condition_reading(session, card, None) != "MET"

    _delivered_round(engine, ids, 5)
    with Session(engine) as session:
        assert condition_reading(session, card, settings) == "MET"  # one of two

    _delivered_round(engine, ids, 5)
    with Session(engine) as session:
        assert condition_reading(session, card, settings) != "MET"  # two of two: reached

    # His allowance moves the cap: the recount reads below it again (and the allowance
    # itself clears the card, as before).
    with Session(engine) as session, session.begin():
        append_event(
            session,
            ALLOWANCE_EVENT,
            "storyboard",
            ids["board"],
            1,
            {"storyboard_id": ids["board"], "extra": EXTRA_REDOS, "granted_by": "owner"},
            str(uuid4()),
        )
    with Session(engine) as session:
        assert condition_reading(session, card, settings) == "MET"
