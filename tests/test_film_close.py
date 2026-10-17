"""«Închide filmul»: the Owner closes one film, and it no longer holds the studio.

2026-10-09: the daily run chose no new topic because three old factual films (Nepal's climate
bill, the LHC upgrade, the Moon's one face) each waited for the Owner's look at one scene of
its shooting sheet, after the stills. `_selection` refuses while any selected topic is live,
and the Director never retires a film with a question of his PENDING. Nothing let him close
a film. POST /api/v1/media/storyboards/{id}/close does:

- the film becomes REJECTED, the terminal state of the Director's retirement, so its topic
  counts as stalled and the next run chooses another; one `runbook.film_retired` event with
  ``retired_by: "Owner"``, what was bought for it and what the books hold;
- every question still asking him about THIS film is withdrawn through its own service
  (the Policy Kernel's approval rows, the decision cards, the letters that ask);
- refused (409, in Romanian) while a purchase of the film is in flight: its purchase lease,
  an open RunPod GPU session, a FILM_CONTINUE at work, a render still writing; and for a film
  with a finished render or an episode of the serial. A continuation only queued (the studio
  stopped) does not refuse it;
- the same close twice is one close: one event, the same answer.

A closed film buys nothing more: the sheet's steps, the paid redo, the day's staircase and
FILM_CONTINUE refuse or skip it. Every vendor here is a fake that counts its calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.messages import post_message
from app.agents.models import AgentMessage
from app.decisions.models import OwnerDecision
from app.decisions.services import owner_decision_cards, propose_owner_decision
from app.media.models import Storyboard, VideoRenderJob
from app.models import ApprovalRequest, DomainEvent
from app.services import pending_approvals, request_approval, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import (
    _a_bought_still,
    _approved_board,
    _busy_elsewhere,
    _claim,
    _owner_letters,
    _production,
    _staircase_world,
    _topic,
    _topic_of,
)

RETIRED = "runbook.film_retired"


def close_url(storyboard_id: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/close"


def command(command_id: str | None = None) -> dict:
    return {"schema_version": 1, "command_id": command_id or str(uuid4())}


def status_of(engine, storyboard_id: str) -> str:
    with Session(engine) as session:
        return str(session.get(Storyboard, storyboard_id).status)


def retired_events(engine, storyboard_id: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == RETIRED, DomainEvent.aggregate_id == storyboard_id
                )
            )
        )
        session.expunge_all()
        return rows


def ask_about(engine, storyboard_id: str, action: str = "media.stills_purchase") -> str:
    """A paid question about the film, asked through the Policy Kernel."""
    with Session(engine) as session, session.begin():
        return str(
            request_approval(
                session,
                action,
                "T2",
                "Director",
                subject=storyboard_id,
                evidence="Imaginile scenelor.",
                proposed_diff={"plan_hash": "a" * 64, "step": "stills", "cap_credits": 216},
                cost_usd=0.72,
            ).id
        )


def card_about(engine, storyboard_id: str) -> str:
    with Session(engine) as session, session.begin():
        return str(
            propose_owner_decision(
                session,
                kind="daily_budget",
                dedupe_key=f"film-budget:{storyboard_id}",
                title_ro="Bugetul zilnic nu ajunge pentru film",
                why_ro="Pasul nu încape în bugetul zilei.",
                effect_ro="Bugetul crește.",
                options=[{"key": "keep", "label_ro": "Las bugetul", "apply": {"type": "none"}}],
                source="daily_run",
                subject_type="storyboard",
                subject_id=storyboard_id,
            ).id
        )


def letter_about(engine, storyboard_id: str, intent: str, subject: str) -> str:
    with Session(engine) as session, session.begin():
        return str(
            post_message(
                session,
                intent=intent,
                subject=subject,
                body={"kind": "owner_shooting_sheet", "storyboard_id": storyboard_id},
                body_text="Filmul așteaptă privirea ta pe foaia de filmare.",
                to_owner=True,
            ).id
        )


def film_cards(engine, storyboard_id: str) -> list[dict]:
    """Every card of the Decisions window that names the film."""
    cards = owner_decision_cards(engine, include_history=False)["cards"]
    with Session(engine) as session:
        letters = {
            message.id
            for message in session.scalars(select(AgentMessage))
            if isinstance(message.body_json, dict)
            and message.body_json.get("storyboard_id") == storyboard_id
        }
    return [
        card
        for card in cards
        if (card.get("subject") or {}).get("id") == storyboard_id
        or (card["source_type"] == "letter" and card["id"] in letters)
    ]


# ----------------------------------------------------------------- 1. the Owner's alone


def test_closing_a_film_needs_the_owners_key(client, engine):
    film = _approved_board(engine, "A film nobody else may close")

    response = client.post(close_url(film), json=command())

    assert response.status_code == 401
    assert status_of(engine, film) == "APPROVED"


# --------------------------------- 2. closed: nothing asks about it, the studio moves on


def test_closing_withdraws_every_question_and_the_day_chooses_another_topic(
    client, engine, headers
):
    from app.media.shooting_sheet import film_spend_micros
    from app.runbook import stages

    film = _approved_board(engine, "Storyboard: The Moon Turns. Why Do We See One Face?")
    other = _approved_board(engine, "Another film, still waiting")
    _a_bought_still(engine, film)
    asked = ask_about(engine, film)
    narration = ask_about(engine, film, "media.paid_generation")
    kept = ask_about(engine, other)
    card = card_about(engine, film)
    escalated = letter_about(engine, film, "ESCALATE", "Filmul așteaptă privirea ta")
    status_letter = letter_about(engine, film, "STATUS", "Ce s-a cumpărat azi")
    candidate = _topic(engine)
    _claim(engine, candidate, status="SUPPORTED")
    assert len(film_cards(engine, film)) == 4  # two questions, a card and a letter that asks
    with Session(engine) as session:
        live, _stalled = stages.topics_in_production(session)
    assert _topic_of(engine, film) in live
    spent = film_spend_micros(engine, film)

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "CLOSED" and body["already_closed"] is False
    assert body["closed_by"] == "Owner"
    assert body["bought_takes"] == {"still": 1}
    assert body["spent_usd_micros"] == spent
    assert sorted(body["withdrawn"]["approvals"]) == sorted([asked, narration])
    assert body["withdrawn"]["decisions"] == [card]
    assert body["withdrawn"]["letters"] == [escalated]
    words = body["words_ro"]
    assert "nimic nu se mai cumpără pentru el" in words and "1 imagine" in words, words
    assert "rămâne în registre" in words and "nu mai ține studioul pe loc" in words, words
    assert status_of(engine, film) == "REJECTED"

    (event,) = retired_events(engine, film)
    assert event.payload["retired_by"] == "Owner"
    assert event.payload["bought_takes"] == {"still": 1}
    assert event.payload["spent_usd_micros"] == spent
    assert event.payload["previous_status"] == "APPROVED"

    with Session(engine) as session:
        for approval_id in (asked, narration):
            row = session.get(ApprovalRequest, approval_id)
            assert row.result == "EXPIRED" and row.decided_at is None
            assert "închis" in row.note
        assert session.get(ApprovalRequest, kept).result == "PENDING"
        assert session.get(OwnerDecision, card).status == "WITHDRAWN"
        assert session.get(AgentMessage, escalated).status == "RESOLVED"
        # A letter that only informs is not a question: it stays in his inbox.
        assert session.get(AgentMessage, status_letter).status == "OPEN"
    assert film_cards(engine, film) == []
    assert [view.subject for view in pending_approvals(engine)] == [other]

    with Session(engine) as session:
        live, stalled = stages.topics_in_production(session)
    assert _topic_of(engine, film) in stalled and _topic_of(engine, film) not in live
    # The other film still holds the studio; once it is closed too, a new topic is chosen.
    assert client.post(close_url(other), headers=headers, json=command()).status_code == 200
    chosen = stages._selection(engine)
    assert chosen["artefacts"]["topic_id"] == candidate, chosen


def test_the_days_list_of_his_questions_goes_only_when_it_asks_about_this_film_alone(
    client, engine, headers
):
    """The day's «N întrebări așteaptă» letter (`waiting_approvals_letter`) lists his standing
    questions by subject: one that lists only this film's is withdrawn with them; one that also
    asks about another film stays, since that question still stands."""
    film = _approved_board(engine, "A film on the day's list")
    other = _approved_board(engine, "Another film on the list")
    mine, theirs = ask_about(engine, film), ask_about(engine, other)

    def digest(subject: str, questions: list[tuple[str, str]]) -> str:
        with Session(engine) as session, session.begin():
            return str(
                post_message(
                    session,
                    intent="ESCALATE",
                    subject=subject,
                    body={
                        "kind": "owner_waiting",
                        "questions": [{"id": q, "subject": s} for q, s in questions],
                        "count": len(questions),
                    },
                    body_text="Întrebări așteaptă răspunsul tău.",
                    to_owner=True,
                ).id
            )

    alone = digest("O întrebare așteaptă răspunsul tău", [(mine, film)])
    mixed = digest("2 întrebări așteaptă răspunsul tău", [(mine, film), (theirs, other)])

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    assert response.json()["withdrawn"]["letters"] == [alone]
    with Session(engine) as session:
        assert session.get(AgentMessage, alone).status == "RESOLVED"
        assert session.get(AgentMessage, mixed).status == "OPEN"


def test_closing_twice_is_one_close(client, engine, headers):
    film = _approved_board(engine, "A film closed twice")
    same = str(uuid4())

    first = client.post(close_url(film), headers=headers, json=command(same))
    again = client.post(close_url(film), headers=headers, json=command(same))
    later = client.post(close_url(film), headers=headers, json=command())

    assert first.status_code == again.status_code == later.status_code == 200, later.text
    assert again.json() == first.json()
    assert later.json()["status"] == "CLOSED" and later.json()["already_closed"] is True
    assert later.json()["closed_at"] == first.json()["closed_at"]
    assert later.json()["closed_by"] == "Owner"
    assert len(retired_events(engine, film)) == 1
    # The same command id with another film is a different command.
    other = _approved_board(engine, "Another film")
    reused = client.post(close_url(other), headers=headers, json=command(same))
    assert reused.status_code == 409
    assert status_of(engine, other) == "APPROVED"


def test_an_unknown_film_is_404(client, headers):
    response = client.post(close_url(str(uuid4())), headers=headers, json=command())
    assert response.status_code == 404


# ---------------------------------------------- 3. never while its money is in flight


def _gpu_open(engine, film: str) -> None:
    from app.providers.runpod.gpu_session import GpuSessionRow

    with Session(engine) as session, session.begin():
        session.add(
            GpuSessionRow(
                id=str(uuid4()),
                integration_id="i-1",
                endpoint_id="ep-stills",
                purpose="image",
                step="stills",
                storyboard_id=film,
                correlation_id="c",
                process_token="p",
                status="OPEN",
                workers_max=1,
                opened_at=utc_now(),
                renewed_at=utc_now(),
                expires_at="2099-01-01T00:00:00+00:00",
                remote_job_ids=[],
            )
        )


def _continuation(engine, film: str, status: str = "QUEUED") -> str:
    """A FILM_CONTINUE of the film: QUEUED (nobody holds it), or CLAIMED by a worker whose
    task lease is still live."""
    from app.services import FILM_CONTINUE_TASK
    from app.workflows.models import TaskQueueItem

    now = utc_now()
    leased = status in ("CLAIMED", "RUNNING")
    task_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TaskQueueItem(
                id=task_id,
                workflow_id=None,
                step_id=None,
                task_type=FILM_CONTINUE_TASK,
                payload={"storyboard_id": film, "cause": "approval:x"},
                priority=4,
                status=status,
                attempts=1 if leased else 0,
                max_attempts=1,
                backoff_seconds=60,
                next_attempt_at=now,
                lease_token="worker_main:x" if leased else None,
                lease_expires_at="2099-01-01T00:00:00+00:00" if leased else None,
                idempotency_key=f"film-continue-{film}-{task_id}",
                error_detail=None,
                created_at=now,
                updated_at=now,
            )
        )
    return task_id


def _continuation_at_work(engine, film: str) -> None:
    _continuation(engine, film, "CLAIMED")


def _render_writing(engine, film: str) -> None:
    """The day's assembly of the film, still writing (its narration is being bought)."""
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=film,
                status="RENDERING",
                started_at=utc_now(),
                finished_at=None,
            )
        )


@pytest.mark.parametrize("busy", ["lease", "gpu", "continuation", "render"])
def test_closing_is_refused_while_a_purchase_of_the_film_is_in_flight(
    client, engine, headers, busy
):
    film = _approved_board(engine, "A film being bought")
    asked = ask_about(engine, film)
    {
        "lease": _busy_elsewhere,
        "gpu": _gpu_open,
        "continuation": _continuation_at_work,
        "render": _render_writing,
    }[busy](engine, film)

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "FILM_BUSY"
    assert "Filmul" in detail["message"] and "nu se închide" in detail["message"]
    assert status_of(engine, film) == "APPROVED"
    assert retired_events(engine, film) == []
    assert [view.id for view in pending_approvals(engine)] == [asked]


def test_a_rendered_film_and_a_serial_episode_are_not_closed_here(client, engine, headers):
    rendered = _approved_board(engine, "A film already rendered")
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=rendered,
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
            )
        )
    serial = _approved_board(engine, "Episodul de azi", serial=True)

    for film, code in ((rendered, "FILM_RENDERED"), (serial, "SERIAL_EPISODE")):
        response = client.post(close_url(film), headers=headers, json=command())
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["status"] == code
        if code == "FILM_RENDERED":
            assert "Directoarei" in response.json()["detail"]["message"]
        assert status_of(engine, film) == "APPROVED"
        assert retired_events(engine, film) == []


# ------------------------------------------------------- 4. a closed film buys nothing more


def test_a_closed_film_is_refused_by_the_sheet_steps_and_the_sheet_says_it_is_closed(
    client, engine, headers, tmp_path
):
    from test_shooting_sheet import approvals, sheet_url, step_url, wire
    from test_stills_stage import SpyStills
    from test_stills_stage import a_film as film_without_stills

    film = film_without_stills(engine, tmp_path)
    images = SpyStills(balance=10_000)
    wire(client, tmp_path, image_adapter=images)
    sheet = client.get(sheet_url(film), headers=headers).json()
    assert sheet["closure"]["closed"] is False and sheet["closure"]["closable"] is True
    asked = client.post(
        step_url(film, "stills"), headers=headers, json={"plan_hash": sheet["sheet_hash"]}
    )
    assert asked.status_code == 202, asked.text

    closed = client.post(close_url(film), headers=headers, json=command())
    assert closed.status_code == 200, closed.text
    assert closed.json()["withdrawn"]["approvals"] == [asked.json()["approval_id"]]

    again = client.get(sheet_url(film), headers=headers).json()
    assert again["closure"]["closed"] is True and again["closure"]["closable"] is False
    assert again["closure"]["closed_by"] == "Owner"
    refused = client.post(
        step_url(film, "stills"), headers=headers, json={"plan_hash": again["sheet_hash"]}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["status"] == "FILM_CLOSED"
    assert "închis" in refused.json()["detail"]["message"]
    assert images.asked == []
    (question,) = approvals(engine)
    assert question.result == "EXPIRED", "a closed film asked the Owner again"


def test_a_closed_films_paid_redo_buys_nothing_and_asks_nothing(client, engine, headers, tmp_path):
    from app.media.assembler import SceneRedoRefused, redo_plan
    from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film
    from test_scene_redo import approvals, coloured_clip, filmed, redo_motion

    film = a_film(engine, tmp_path, scenes=4)
    filmed(engine, film, tmp_path, coloured_clip(tmp_path, "navy"))
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=coloured_clip(tmp_path, "olive")))
    plan = redo_plan(engine, film, "motion", 3, capabilities=[SEEDANCE])
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    with pytest.raises(SceneRedoRefused) as refused:
        redo_motion(engine, film, tmp_path, models, account, 3, plan["plan_hash"])

    assert refused.value.status == "FILM_CLOSED" and refused.value.http_status == 409
    assert models.posts() == 0 and approvals(engine) == []


def test_the_days_staircase_and_the_continuation_leave_a_closed_film_alone(
    client, engine, headers, settings, tmp_path, monkeypatch
):
    from app.media.shooting_sheet import FilmClosed, film_purchase_lease
    from app.runbook import stages
    from test_daily_run_stages import _bottom_of_the_staircase

    _production(engine)
    film = _bottom_of_the_staircase(engine, tmp_path)
    world = _staircase_world(engine, tmp_path, monkeypatch)
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    # The continuation his yes would have queued: the film is no longer to be filmed.
    continued = stages.continue_film(engine, settings, None, None, film)
    assert continued["status"] == "SKIPPED", continued
    # A walk that read the film before it was closed meets the closed film at its lease:
    # nothing bought, nothing asked, and no letter written about it.
    wiring = stages.sheet_wiring(engine, None, settings)
    walked = stages._film_staircase(engine, settings, None, film, wiring, "PRODUCTION", "c")
    assert walked["refusal"] == "FILM_CLOSED" and walked["bought"] == []
    day = stages._media_staircase(engine, settings, None, None, [film], [], set(), "PRODUCTION")
    assert [f["status"] for f in day["artefacts"]["films"]] == ["CLOSED"]
    assert _owner_letters(engine, "owner_shooting_sheet") == []
    # The whole media stage does not pick it up either.
    stages._media(engine, settings, None, None)
    assert world["images"].asked == [] and world["models"].posts() == 0
    assert [r for r in pending_approvals(engine) if r.subject == film] == []
    # Every holder of its lease meets the closed film: the buying steps, and the sheet's
    # repairs, which would write a replacement storyboard or reopen it as NEEDS_SHOT_PLAN.
    # Only the close itself still takes it (an already closed film's close takes none).
    for step in (
        "stills",
        "test_shot",
        "motion",
        "assemble",
        "scene_redo",
        "staircase",
        "story_repair",
        "prompt_repair",
    ):
        with pytest.raises(FilmClosed):
            with film_purchase_lease(engine, film, holder=f"h-{step}", step=step):
                pass
    with film_purchase_lease(engine, film, holder="close", step="close"):
        pass


def test_the_old_render_button_makes_nothing_for_a_closed_film(client, engine, headers):
    film = _approved_board(engine, "A closed film nobody renders")
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    response = client.post(f"/api/v1/media/render/{film}", headers=headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["status"] == "FILM_CLOSED"
    with Session(engine) as session:
        assert list(session.scalars(select(VideoRenderJob.id))) == []


def test_a_sheet_repair_queued_before_the_close_ends_without_a_model_run(
    client, engine, headers, monkeypatch
):
    """A story repair writes a replacement storyboard of the film's topic, which would make
    the topic hold the studio again: a closed film's repair ends before any of it runs."""
    from app.media import blocker_repair
    from test_daily_run_stages import _autonomy_on

    _autonomy_on(engine)
    film = _approved_board(engine, "A film with a repair in the queue")
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    def never(*_args, **_kwargs):
        raise AssertionError("a closed film's sheet was read or repaired")

    monkeypatch.setattr(blocker_repair, "build_sheet", never)
    monkeypatch.setattr(blocker_repair, "repair_story", never)

    result = blocker_repair.process_sheet_repair(
        engine,
        None,
        {"storyboard_id": film, "message_id": str(uuid4()), "sheet_hash": "0" * 64},
    )

    assert result["status"] == "STALE" and "închis" in result["reason"], result
    with Session(engine) as session:
        boards = list(session.scalars(select(Storyboard.id)))
    assert boards == [film]


# ----------------------------------------- 5. the Director's retirement shares the close


def test_the_directors_retirement_still_closes_a_film_with_his_letter(engine):
    from app.runbook import stages

    film = _approved_board(engine, "A film that stood still")
    _a_bought_still(engine, film)
    since = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()

    made = stages._retire_film(
        engine, film, "A film that stood still", since, 5, 3, {"reason": "Filmul așteaptă."}
    )

    assert made is not None and made["storyboard_id"] == film
    assert status_of(engine, film) == "REJECTED"
    (event,) = retired_events(engine, film)
    assert event.payload["retired_by"] == "Director"
    assert event.payload["bought_takes"] == {"still": 1}
    assert event.payload["days"] == 5
    (letter,) = _owner_letters(engine, "owner_film_retired")
    assert "1 imagine" in letter.body_text
    # Retired once: a second retirement writes nothing.
    assert stages._retire_film(engine, film, "x", since, 5, 3, {}) is None
    assert len(retired_events(engine, film)) == 1


def test_a_retired_film_closed_by_the_owner_answers_closed_without_a_second_event(
    client, engine, headers
):
    from app.runbook import stages

    film = _approved_board(engine, "A retired film")
    card = card_about(engine, film)
    stages._retire_film(engine, film, "A retired film", "2026-10-01", 5, 3, {})

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already_closed"] is True and body["closed_by"] == "Director"
    assert len(retired_events(engine, film)) == 1
    # What still asked him about it is withdrawn all the same, the Director's letter with it.
    assert body["withdrawn"]["decisions"] == [card]
    (retired_letter,) = _owner_letters(engine, "owner_film_retired")
    assert body["withdrawn"]["letters"] == [retired_letter.id]
    with Session(engine) as session:
        assert session.get(OwnerDecision, card).status == "WITHDRAWN"
    assert film_cards(engine, film) == []


# ------------------------------------------- 6. what a close withdraws, and what it says


def test_letters_about_money_stay_and_only_the_asking_letters_go(client, engine, headers):
    """A paid step that stopped after it paid, a purchase abandoned under it: those letters
    report money and the books, and closing the film answers neither. The sheet repair's
    letter asking him to move the sheet on is a question about the film, and goes."""
    from app.economy.accountant import paid_step_interrupted_letter, purchase_abandoned_letter
    from app.media.shooting_sheet import ABANDONED_LETTER_KIND

    film = _approved_board(engine, "A film whose step stopped after paying")
    unbooked = paid_step_interrupted_letter(
        engine,
        storyboard_id=film,
        step_words="imaginile",
        credits_ro="18 credite",
        amount_ro="0,18 USD",
        booked=False,
        reason="furnizorul a căzut",
        correlation_id="c",
    )
    abandoned = purchase_abandoned_letter(
        engine,
        kind=ABANDONED_LETTER_KIND,
        storyboard_id=film,
        subject="Pasul «imaginile» s-a oprit înainte să se termine",
        body={"held_usd_micros": 180000},
        body_text="Suma ținută pentru pas rămâne în registru.",
        correlation_id="c",
    )
    repair = letter_about(engine, film, "ESCALATE", "Foaia necesită intervenție")
    with Session(engine) as session, session.begin():
        message = session.get(AgentMessage, repair)
        message.body_json = {**message.body_json, "kind": "sheet_repair_owner"}

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    assert response.json()["withdrawn"]["letters"] == [repair]
    with Session(engine) as session:
        assert session.get(AgentMessage, repair).status == "RESOLVED"
        assert session.get(AgentMessage, unbooked).status == "OPEN"
        assert session.get(AgentMessage, abandoned).status == "OPEN"


def _newer_film_of_the_same_topic(engine, film: str, title: str) -> str:
    """What a sheet's story repair leaves: a newer script of the film's topic, with its own
    storyboard, and the old film APPROVED as it was."""
    from app.factual.models import ScriptDraft
    from test_daily_run_stages import _script_of

    old = _script_of(engine, film)
    script_id, board_id = str(uuid4()), str(uuid4())
    later = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    with Session(engine) as session, session.begin():
        topic = session.get(ScriptDraft, old).topic_id
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic,
                version=2,
                title=title,
                target_duration_seconds=12,
                voiceover_full_text="One line. Another line.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=later,
            )
        )
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title=f"Storyboard: {title}",
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=12,
                status="APPROVED",
                total_scenes=2,
                created_at=later,
            )
        )
    return board_id


def test_a_topic_a_newer_film_still_holds_is_named_and_not_said_to_be_freed(
    client, engine, headers
):
    from app.media.film_close import closure_view
    from app.runbook import stages

    film = _approved_board(engine, "The old cut of the story")
    newer = _newer_film_of_the_same_topic(engine, film, "The repaired story")
    # The confirmation already says what the close will not do.
    before = closure_view(engine, film)
    assert before["closable"] is True
    assert "«The repaired story»" in before["topic_ro"], before

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["topic"]["freed"] is False
    assert body["topic"]["held_by"]["storyboard_id"] == newer
    assert "nu mai ține studioul pe loc" not in body["words_ro"], body["words_ro"]
    assert "rămâne în lucru prin filmul mai nou «The repaired story»" in body["words_ro"]
    (event,) = retired_events(engine, film)
    assert event.payload["topic"]["freed"] is False
    with Session(engine) as session:
        live, _stalled = stages.topics_in_production(session)
    assert _topic_of(engine, film) in live  # what the words say is what the day reads


def test_a_film_its_script_replaced_is_not_said_to_have_bought_nothing(client, engine, headers):
    """REJECTED by a rebuild of its script, with a still bought for it and no closing event:
    the sheet and a press of «Închide filmul» read its takes and its books, and the newer
    storyboard that holds the topic."""
    from app.media.film_close import closure_view
    from app.media.shooting_sheet import film_spend_micros

    film = _approved_board(engine, "A storyboard a rebuild replaced")
    _a_bought_still(engine, film)
    newer = _newer_film_of_the_same_topic(engine, film, "The rebuilt storyboard")
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film).status = "REJECTED"
    spent = film_spend_micros(engine, film)

    closure = closure_view(engine, film)
    assert closure["closed"] is True and closure["closed_by"] is None
    assert closure["bought_takes"] == {"still": 1}
    assert closure["spent_usd_micros"] == spent
    assert "nu s-a cumpărat nimic" not in closure["words_ro"]
    assert "1 imagine" in closure["words_ro"]
    assert "«The rebuilt storyboard»" in closure["words_ro"], closure["words_ro"]
    assert closure["topic"]["held_by"]["storyboard_id"] == newer

    again = client.post(close_url(film), headers=headers, json=command())
    assert again.status_code == 200, again.text
    assert again.json()["already_closed"] is True
    assert again.json()["bought_takes"] == {"still": 1}
    assert "nu mai ține studioul pe loc" not in again.json()["words_ro"]
    assert retired_events(engine, film) == []


def test_the_spend_is_read_while_the_close_holds_the_film(client, engine, headers, monkeypatch):
    """The figure the event carries and the takes it counts describe one moment: the spend is
    read under the film's lease, after any purchase that held it has finished."""
    from app.media.shooting_sheet import current_lease
    from app.runbook import stages

    film = _approved_board(engine, "A film whose books are read under its lease")
    seen: list[str | None] = []

    def books(engine_, storyboard_id):
        lease = current_lease(engine_, storyboard_id)
        seen.append(lease["step"] if lease else None)
        return 2_100_000

    monkeypatch.setattr(stages, "film_spent_micros", books)

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    assert seen == ["close"]
    assert response.json()["spent_usd_micros"] == 2_100_000
    (event,) = retired_events(engine, film)
    assert event.payload["spent_usd_micros"] == 2_100_000


# --------------------------------------- 7. a continuation only queued does not hold it


def test_a_queued_continuation_under_his_stop_does_not_refuse_the_close(
    client, engine, headers, settings
):
    """STOP AUTONOMIE: the worker claims nothing, so a continuation his look queued stays
    QUEUED. It holds nothing and buys nothing for a closed film, so the close goes ahead; once
    the stop is lifted and it runs, it skips the film."""
    from app.models import OwnerPolicy
    from app.runbook import stages

    _production(engine)
    film = _approved_board(engine, "A film with a queued continuation")
    _continuation(engine, film, "QUEUED")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True

    response = client.post(close_url(film), headers=headers, json=command())

    assert response.status_code == 200, response.text
    assert status_of(engine, film) == "REJECTED"
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    continued = stages.continue_film(engine, settings, None, None, film)
    assert continued["status"] == "SKIPPED", continued


# ------------------------------- 8. the day's assembly holds the film; a close waits for it


def _ready_day(engine, tmp_path, monkeypatch, on_ready=None):
    """The day's walk of one film, faked up to READY (the staircase gives the lease back),
    and its plan costed; ``on_ready`` runs between the two, as a press of his would."""
    from app.runbook import stages

    _production(engine)
    _staircase_world(engine, tmp_path, monkeypatch)

    def ready(engine_, settings_, registry, storyboard_id, wiring, environment, correlation):
        if on_ready is not None:
            on_ready(storyboard_id)
        return {
            "status": "READY",
            "step": None,
            "reason": "",
            "sheet": {"sheet_hash": "a" * 64, "title": "A ready film", "footer": {}},
            "bought": [],
            "refusal": None,
        }

    monkeypatch.setattr(stages, "_film_staircase", ready)
    monkeypatch.setattr(
        stages,
        "estimate_film_cost_micros",
        lambda *a, **k: {
            "narration_usd_micros": 10_000,
            "expected_usd_micros": 10_000,
            "usd_micros": 20_000,
        },
    )


def test_a_film_closed_between_its_staircase_and_its_assembly_is_not_assembled(
    client, engine, headers, settings, tmp_path, monkeypatch
):
    from app.runbook import stages

    film = _approved_board(engine, "A film closed before its assembly")

    def press(storyboard_id):
        closed = client.post(close_url(storyboard_id), headers=headers, json=command())
        assert closed.status_code == 200, closed.text

    _ready_day(engine, tmp_path, monkeypatch, on_ready=press)

    def never(*_args, **_kwargs):
        raise AssertionError("a closed film was assembled (its narration bought)")

    monkeypatch.setattr(stages, "_assemble_from_takes", never)

    day = stages._media_staircase(engine, settings, None, None, [film], [], set(), "PRODUCTION")

    assert [f["status"] for f in day["artefacts"]["films"]] == ["CLOSED"], day
    assert status_of(engine, film) == "REJECTED"
    assert [r for r in pending_approvals(engine) if r.subject == film] == []
    assert _owner_letters(engine, "owner_shooting_sheet") == []


def test_a_close_pressed_during_the_days_assembly_waits_for_it(
    client, engine, headers, settings, tmp_path, monkeypatch
):
    from app.runbook import stages

    film = _approved_board(engine, "A film being assembled")
    _ready_day(engine, tmp_path, monkeypatch)
    pressed: list[dict] = []

    def assembling(engine_, settings_, vault, storyboard_id, *args, **kwargs):
        response = client.post(close_url(storyboard_id), headers=headers, json=command())
        pressed.append({"code": response.status_code, **response.json()})
        return {"status": "HELD", "reason": "Asamblarea s-a oprit."}

    monkeypatch.setattr(stages, "_assemble_from_takes", assembling)

    stages._media_staircase(engine, settings, None, None, [film], [], set(), "PRODUCTION")

    (answer,) = pressed
    assert answer["code"] == 409 and answer["detail"]["status"] == "FILM_BUSY", answer
    assert "asamblarea" in answer["detail"]["message"]
    assert status_of(engine, film) == "APPROVED"
    assert retired_events(engine, film) == []


def test_the_days_letter_about_a_film_closed_meanwhile_is_not_written(client, engine, headers):
    from app.runbook import stages

    film = _approved_board(engine, "A film closed before its letter")
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    written = stages._sheet_letter(
        engine,
        film,
        {
            "status": "ASKED",
            "step": "stills",
            "sheet": {"sheet_hash": "a" * 64, "title": "A film closed before its letter"},
            "reason": "Imaginile așteaptă răspunsul tău.",
            "approval_id": None,
            "bought": [],
        },
        None,
        "c",
    )

    assert written is None
    assert _owner_letters(engine, "owner_shooting_sheet") == []
    assert film_cards(engine, film) == []


# ------------------------------------- 9. the shot-plan writers never reopen a closed film


def test_holding_a_closed_film_for_its_shot_plan_leaves_it_closed(client, engine, headers):
    from app.media.prompt_agent import hold_for_shot_plan, shot_plan_gaps

    film = _approved_board(engine, "A closed film without a model plan")
    with Session(engine) as session:
        assert shot_plan_gaps(session, film) == [1, 2]
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    assert hold_for_shot_plan(engine, film, "c") == []
    assert status_of(engine, film) == "REJECTED"


def test_a_film_closed_while_its_shot_plan_is_written_stays_closed(
    client, engine, headers, monkeypatch
):
    """The day's re-ask (or a repair) runs the model with no lease held; the Owner closes the
    film meanwhile, and the model's plan comes back incomplete again. The film stays closed:
    not NEEDS_SHOT_PLAN, which would make its topic hold the studio once more."""
    from app.media import prompt_agent
    from app.media.prompt_agent import PromptError, write_shot_prompts
    from app.runbook import stages

    film = _approved_board(engine, "A film closed during its shot plan")
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, film)
        board.status = "NEEDS_SHOT_PLAN"
        board.visual_bible_json = {"source": "model", "look": "documentary"}
    monkeypatch.setattr(
        "app.factual.story_review.story_gate", lambda session, script_id: (True, "")
    )
    monkeypatch.setattr(
        prompt_agent, "agent_for_role", lambda session, role: type("A", (), {"id": "editor"})()
    )
    calls: list[str] = []

    def model(
        engine_,
        registry,
        agent_id,
        task,
        prompt,
        template,
        correlation,
        summary,
        tokens,
        *,
        native_thinking=None,
        subject=None,
    ):
        if not calls:
            closed = client.post(close_url(film), headers=headers, json=command())
            assert closed.status_code == 200, closed.text
        calls.append(task)
        return {"id": f"run-{len(calls)}", "output_text": "not a plan"}

    monkeypatch.setattr(prompt_agent, "_run", model)

    with pytest.raises(PromptError) as refused:
        write_shot_prompts(engine, object(), film, "c")

    assert "închis" in str(refused.value)
    assert calls == ["shot_prompts", "shot_prompts"]
    assert status_of(engine, film) == "REJECTED"
    with Session(engine) as session:
        live, stalled = stages.topics_in_production(session)
    assert _topic_of(engine, film) in stalled and _topic_of(engine, film) not in live
    # Asked again later, it runs no model at all.
    with pytest.raises(PromptError):
        write_shot_prompts(engine, object(), film, "c")
    assert len(calls) == 2


def test_a_sheet_repair_whose_film_closes_during_it_ends_at_its_lease(
    client, engine, headers, monkeypatch
):
    """The repair read the film open; the Owner closed it before the repair took its lease.
    The repair's lease meets the closed film: nothing is repaired or rewritten, and no letter
    asks him about it."""
    from app.media import blocker_repair
    from test_daily_run_stages import _autonomy_on

    _autonomy_on(engine)
    film = _approved_board(engine, "A film closed under its repair")
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200
    # As if the repair had read the film before the close.
    monkeypatch.setattr(blocker_repair, "film_is_closed", lambda session, storyboard_id: False)
    monkeypatch.setattr(
        blocker_repair, "build_sheet", lambda *a, **k: {"sheet_hash": "0" * 64, "scenes": []}
    )

    def never(*_args, **_kwargs):
        raise AssertionError("a closed film's story was repaired")

    monkeypatch.setattr(blocker_repair, "repair_story", never)
    monkeypatch.setattr(blocker_repair, "write_shot_prompts", never)

    result = blocker_repair.process_sheet_repair(
        engine,
        None,
        {"storyboard_id": film, "message_id": str(uuid4()), "sheet_hash": "0" * 64},
    )

    assert result["status"] == "STALE" and "închis" in result["reason"], result
    assert _owner_letters(engine, "sheet_repair_owner") == []
    assert status_of(engine, film) == "REJECTED"


# ------------------------------------------------ 10. a closed film's takes are not chosen


def test_a_closed_films_take_is_not_chosen_and_nothing_continues(client, engine, headers, tmp_path):
    from app.media.models import SceneTake
    from app.services import FILM_CONTINUE_TASK
    from app.workflows.models import TaskQueueItem

    _production(engine)
    film = _approved_board(engine, "A closed film with a picture to choose")
    picture = tmp_path / "still.jpg"
    picture.write_bytes(b"\xff\xd8\xff\xd9")
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=film,
                scene_number=1,
                kind="still",
                prompt_hash="c" * 64,
                model_id="seedream5_pro",
                resolution="1530:2720",
                credits_quoted=18,
                status="PAID",
                path=str(picture),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    response = client.post(
        f"/api/v1/media/takes/{take_id}/decision",
        headers=headers,
        json={"decision": "APPROVED"},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "FILM_CLOSED" and "închis" in detail["message"]
    with Session(engine) as session:
        assert session.get(SceneTake, take_id).status == "PAID"
        continued = [
            task
            for task in session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            )
            if (task.payload or {}).get("storyboard_id") == film
        ]
    assert continued == []


def test_a_repair_that_ends_waiting_for_him_on_a_closed_film_writes_him_nothing(
    client, engine, headers
):
    """A repair with no prompt to rewrite takes no lease: the Owner may close the film while
    the Director's assignment runs. Its end would have asked him «Foaia necesită intervenție»;
    on a closed film it ends STALE and writes him nothing."""
    from app.media import blocker_repair

    film = _approved_board(engine, "A film closed while its sheet was checked")
    with Session(engine) as session, session.begin():
        report = post_message(
            session,
            intent="ESCALATE",
            subject="Blocaje pe foaia de filmare",
            body={"kind": blocker_repair.REPORT_KIND, "storyboard_id": film, "issues": []},
            body_text="Foaia are blocaje.",
        ).id
    assert client.post(close_url(film), headers=headers, json=command()).status_code == 200

    result = blocker_repair._finish(
        engine,
        {"storyboard_id": film, "message_id": report, "sheet_hash": "0" * 64},
        "WAITING_OWNER",
        [{"kind": "OWNER", "detail": "Soldul nu ajunge."}],
        "Foaia a fost reverificată: blocajele de mai jos rămân deschise.",
        "c",
    )

    assert result["status"] == "STALE" and "închis" in result["reason"], result
    assert _owner_letters(engine, "sheet_repair_owner") == []
    assert film_cards(engine, film) == []
