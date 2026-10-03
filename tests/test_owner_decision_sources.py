"""The studio's own places that meet a decision only the Owner can take PROPOSE a card for it
(2026-10-03, DECISION_SOURCES), and keep their letters.

His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
card.» Before this suite each of these places wrote him a letter or a log line and nothing in
his window of decisions:

- the daily run waiting OVER_DAILY_BUDGET at a film's paid step (a budget card with the amount
  the film needs, applied through his own budget command on his accept);
- a model connection refused by its provider with HTTP 401, 402 or 403 (a reconnect card naming
  the connection and its Settings place, withdrawn after the next run that succeeds on it);
- a YouTube connection whose grant Google refused (invalid_grant): a reconnect card;
- a film whose licence ledger is NEEDS_REVIEW because a connection does not state commercial use
  (one card per vendor connection);
- a film assembled while the music library has no music (the music card);
- the automatic sheet repair paused (language model down, or the day's ceiling): a card that says
  why and offers what unblocks it, his own Owner commands among them.

Every producer only proposes: idempotent per condition (one open card per dedupe key), withdrawn
when the condition clears, and a card he refused is not asked again for a week. Every provider is
faked; no socket is opened, nothing is bought.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage
from app.agents.services import run_agent_task
from app.decisions import sources
from app.decisions.models import OwnerDecision
from app.decisions.services import (
    DecideCommand,
    decide_owner_decision,
    refresh_owner_decisions,
)
from app.economy.budget import BudgetCommand, set_budget
from app.economy.models import SpendingBudget
from app.integrations.models import Integration
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_agent_budget import a_running_studio
from test_agent_error_detail import Refusing
from test_sheet_blocker_repair import film, sheet  # noqa: F401 - the fixture is used by name
from test_sheet_repair_guard import model_runs, paused_letters, unresolved


def cards(engine, kind: str | None = None, *, open_only: bool = False) -> list[OwnerDecision]:
    with Session(engine) as session:
        rows = [
            row
            for row in session.scalars(select(OwnerDecision).order_by(OwnerDecision.created_at))
            if (kind is None or row.kind == kind)
            and (not open_only or row.status in ("PENDING", "WAITING_FOR_OWNER_ACTION"))
        ]
        session.expunge_all()
        return rows


def accept(engine, card: OwnerDecision, option_key: str | None = None) -> dict:
    return decide_owner_decision(
        engine,
        card.id,
        DecideCommand(
            command_id=uuid4(),
            expected_version=card.version,
            decision="ACCEPT",
            option_key=option_key,
        ),
        issued_by="owner",
    )


def refuse(engine, card: OwnerDecision) -> dict:
    return decide_owner_decision(
        engine,
        card.id,
        DecideCommand(command_id=uuid4(), expected_version=card.version, decision="REFUSE"),
        issued_by="owner",
    )


def connection(engine, kind: str, name: str, *, identifier: str | None = None, **config) -> str:
    with Session(engine) as session, session.begin():
        event = append_event(session, "settings.test", "integration", "x", 1, {}, str(uuid4()))
        row = Integration(
            id=identifier or str(uuid4()),
            kind=kind,
            name=name,
            config=dict(config),
            encrypted_secrets="",
            secret_fields=[],
            version=1,
            status="VERIFIED",
            checked_at=utc_now(),
            event_id=event.event_id,
        )
        session.add(row)
        return row.id


def daily_limit(engine) -> int | None:
    with Session(engine) as session:
        return session.scalar(
            select(SpendingBudget.limit_usd_micros).where(
                SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True)
            )
        )


# ------------------------------------------------------------- the generic rule of a producer


def test_a_card_he_refused_is_not_asked_again_for_a_week(engine):
    def ask() -> str | None:
        with Session(engine) as session, session.begin():
            card = sources.ask(
                session,
                kind="music_library",
                dedupe_key="test:quiet",
                title_ro="Biblioteca de muzică este goală",
                why_ro="De ce.",
                effect_ro="Ce schimbă.",
                options=[{"key": "ok", "label_ro": "Da", "recommended": True}],
                source="test",
            )
            return card.id if card is not None else None

    first = ask()
    assert first is not None
    assert ask() == first, "one open card per key"
    (card,) = cards(engine)
    refuse(engine, card)

    assert ask() is None, "his no stands: the same question does not come back the next day"
    with Session(engine) as session, session.begin():
        row = session.get(OwnerDecision, card.id)
        long_ago = datetime.now(UTC) - timedelta(days=sources.REFUSAL_QUIET_DAYS + 1)
        row.decided_at = long_ago.isoformat()
    again = ask()
    assert again is not None and again != card.id, "after a week it may be asked again"


# ---------------------------------------------- (a) a film waiting OVER_DAILY_BUDGET: a budget


def _film_waiting_on_budget(engine, tmp_path, refusal: str = "OVER_DAILY_BUDGET"):
    from test_daily_run_stages import _bottom_of_the_staircase, _production

    _production(engine)
    board = _bottom_of_the_staircase(engine, tmp_path)
    waiting = {
        "status": "WAITING",
        "step": "test_shot",
        "refusal": refusal,
        "reason": "Plafonul pasului depășește bugetul zilei.",
        "sheet": {
            "title": "Un film",
            "sheet_hash": "a" * 64,
            "steps": {
                "test_shot": {
                    "to_buy": [1],
                    "cost_credits": 600,
                    "cost_usd": 6.0,
                    "cap_credits": 740,
                    "cap_usd": 7.4,
                }
            },
        },
        "approval_id": None,
    }
    plan_cost = {"usd_micros": 23_000_000, "expected_usd_micros": 18_000_000}
    return board, waiting, plan_cost


def test_a_film_over_the_daily_budget_puts_a_budget_card_with_what_the_film_needs(engine, tmp_path):
    from app.runbook import stages

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="5"))
    board, waiting, plan_cost = _film_waiting_on_budget(engine, tmp_path)

    stages._sheet_letter(engine, board, waiting, plan_cost, str(uuid4()))
    stages._sheet_letter(engine, board, waiting, plan_cost, str(uuid4()))

    (card,) = cards(engine, "daily_budget")
    assert card.status == "PENDING" and card.subject_id == board
    assert card.dedupe_key == sources.film_budget_key(board)
    raise_option = card.options[0]
    assert raise_option["recommended"] is True and raise_option["apply"]["type"] == "budget"
    assert raise_option["apply"]["limit_usd"] == str(math.ceil(23 / 5) * 5)
    assert "7,4" in card.why_ro and "23" in card.why_ro and "5 USD" in card.why_ro
    assert card.clears_when == {"type": "daily_budget_at_least", "usd_micros": 7_400_000}
    # The letter stays, and says where the decision waits.
    with Session(engine) as session:
        letters = [
            m
            for m in session.scalars(select(AgentMessage))
            if (m.body_json or {}).get("kind") == "owner_shooting_sheet"
        ]
    assert len(letters) == 1 and "«Decizii»" in letters[0].body_text

    accept(engine, card)

    assert daily_limit(engine) == 25_000_000


def test_a_budget_that_holds_the_step_gets_no_card_the_film_waits_for_tomorrow(engine, tmp_path):
    from app.runbook import stages

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    board, waiting, plan_cost = _film_waiting_on_budget(engine, tmp_path)

    stages._sheet_letter(engine, board, waiting, plan_cost, str(uuid4()))

    assert cards(engine, "daily_budget") == []


def test_the_films_budget_card_is_withdrawn_when_the_film_moves_on(engine, tmp_path):
    from app.runbook import stages

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="5"))
    board, waiting, plan_cost = _film_waiting_on_budget(engine, tmp_path)
    stages._sheet_letter(engine, board, waiting, plan_cost, str(uuid4()))

    moved = {**waiting, "refusal": "HERO_NOT_APPROVED", "reason": "Privește cadrul de probă."}
    stages._sheet_letter(engine, board, moved, plan_cost, str(uuid4()))

    (card,) = cards(engine, "daily_budget")
    assert card.status == "WITHDRAWN"


# ------------------------------------------ (b) a model connection refused: a reconnect card


@pytest.mark.parametrize("status", [401, 402, 403])
def test_a_refused_model_connection_puts_a_reconnect_card_naming_its_settings_place(
    engine, monkeypatch, status
):
    agent_id, registry, _ = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    connection(engine, "ollama", "Ollama Cloud", identifier=provider_id)
    registry.register(provider_id, Refusing(status))

    for _ in range(2):
        run = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))
        assert run["status"] == "FAILED"

    (card,) = cards(engine, "reconnect_connection")
    assert card.status == "PENDING" and card.subject_id == provider_id
    assert card.dedupe_key == sources.reconnect_key(provider_id)
    assert "«Ollama Cloud»" in card.title_ro
    assert f"HTTP {status}" in card.why_ro
    option = card.options[0]
    assert option["recommended"] and option["apply"]["type"] == "guided"
    assert option["apply"]["place"] == "llm"
    assert option["apply"]["place_ro"] == "Setări → Furnizori AI"
    assert card.clears_when == {"type": "integration_verified", "integration_id": provider_id}


def test_the_reconnect_card_is_withdrawn_after_the_next_run_that_succeeds(engine, monkeypatch):
    agent_id, registry, model = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    connection(engine, "ollama", "Ollama Cloud", identifier=provider_id)
    registry.register(provider_id, Refusing(401))
    run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    registry.register(provider_id, model)
    run = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert run["status"] == "SUCCEEDED"
    (card,) = cards(engine, "reconnect_connection")
    assert card.status == "WITHDRAWN"


@pytest.mark.parametrize("status", [404, 429, 503])
def test_a_status_the_owner_does_not_fix_by_reconnecting_puts_no_card(engine, monkeypatch, status):
    agent_id, registry, _ = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    connection(engine, "ollama", "Ollama Cloud", identifier=provider_id)
    registry.register(provider_id, Refusing(status))

    run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert cards(engine) == []


def test_a_provider_without_a_settings_connection_puts_no_card(engine, monkeypatch):
    agent_id, registry, _ = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    registry.register(provider_id, Refusing(401))

    run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert cards(engine) == []


def test_the_audit_seed_and_the_producer_share_one_card_per_connection(
    engine, settings, monkeypatch
):
    from app.decisions import seed

    agent_id, registry, _ = a_running_studio(engine, monkeypatch)
    with Session(engine) as session:
        provider_id = session.get(Agent, agent_id).provider_id
    connection(engine, "ollama", "Ollama Cloud", identifier=provider_id)
    with Session(engine) as session, session.begin():
        session.get(Integration, provider_id).status = "FAILED"
    registry.register(provider_id, Refusing(401))
    run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    seed.seed_owner_decisions(engine, settings)

    assert len(cards(engine, "reconnect_connection")) == 1


# --------------------------------------------------- (c) a YouTube grant refused: a reconnect


INVALID_GRANT = "Google a refuzat accesul la contul YouTube (HTTP 400, invalid_grant)."


def test_an_invalid_grant_puts_a_reconnect_card_for_that_channel(engine, connect_youtube):
    from app.youtube import services as youtube

    connection_id, vault = connect_youtube(name="Canal", channel_id="UC123", title="Știință")

    youtube.mark_reconnect_needed(engine, connection_id, INVALID_GRANT, correlation_id="c")
    youtube.mark_reconnect_needed(engine, connection_id, INVALID_GRANT, correlation_id="c")

    (card,) = cards(engine, "reconnect_youtube")
    assert card.status == "PENDING" and card.subject_id == connection_id
    assert card.dedupe_key == sources.youtube_key(connection_id)
    assert "«Știință»" in card.title_ro
    assert "invalid_grant" in card.why_ro
    option = card.options[0]
    assert option["recommended"] and option["apply"]["place"] == "social"
    # Still refused: the condition does not clear it.
    refresh_owner_decisions(engine)
    assert cards(engine, "reconnect_youtube")[0].status == "PENDING"

    youtube.verify_connection(engine, vault, connection_id, correlation_id="c")

    assert cards(engine, "reconnect_youtube")[0].status == "WITHDRAWN"


def test_a_failed_check_that_is_not_a_refused_grant_puts_no_card(engine, connect_youtube):
    from app.youtube import services as youtube

    connection_id, _ = connect_youtube(name="Canal", channel_id="UC123", title="Știință")

    youtube._record_failure(
        engine, connection_id, "Google nu a putut fi contactat: timeout", "x", 7, "c"
    )

    assert cards(engine) == []
    youtube._record_failure(engine, connection_id, INVALID_GRANT, "x", 7, "c")
    assert len(cards(engine, "reconnect_youtube")) == 1


def test_the_statistics_refused_by_google_put_the_same_reconnect_card(engine, connect_youtube):
    from types import SimpleNamespace

    from app.analytics import services as analytics
    from app.providers.youtube_analytics import MetricsUnavailable

    connection_id, _ = connect_youtube(name="Canal", channel_id="UC123", title="Știință")
    refused = MetricsUnavailable(
        "refused",
        during="token_refresh",
        http_status=400,
        oauth_error="invalid_grant",
        auth_refused=True,
    )

    analytics._record_account_refusal(
        engine, "channel-x", SimpleNamespace(connection_id=connection_id), refused
    )

    (card,) = cards(engine, "reconnect_youtube")
    assert card.subject_id == connection_id and "invalid_grant" in card.why_ro


# ---------------------------------------- (d) a film NEEDS_REVIEW: commercial use, per vendor


def _production_on(runway: str, elevenlabs: str) -> dict:
    return {
        "scenes": [
            {
                "scene_index": 1,
                "scene_kind": "LIVE",
                "still_take": {},
                "image": {"integration_id": runway},
                "voice_integration_ids": [elevenlabs],
            }
        ],
        "image": {"provider": "runway", "integration_id": runway},
        "voice": {"provider": "elevenlabs", "integration_id": elevenlabs},
    }


def test_a_film_that_needs_review_for_commercial_use_puts_one_card_per_vendor(engine):
    from app.media.assembler import film_licence_ledger

    runway = connection(engine, "runway", "Runway")
    eleven = connection(engine, "elevenlabs", "ElevenLabs")

    ledger = film_licence_ledger(engine, _production_on(runway, eleven))
    film_licence_ledger(engine, _production_on(runway, eleven))

    assert ledger["status"] == "NEEDS_REVIEW"
    found = {card.subject_id: card for card in cards(engine, "commercial_use")}
    assert set(found) == {runway, eleven}
    assert "Runway" in found[runway].title_ro and "ElevenLabs" in found[eleven].title_ro
    assert found[runway].dedupe_key == sources.commercial_use_key(runway)
    assert found[runway].options[0]["apply"]["place"] == "media"
    assert "NEEDS_REVIEW" in found[runway].why_ro


def test_a_connection_that_states_commercial_use_gets_no_card(engine):
    from app.media.assembler import film_licence_ledger

    runway = connection(engine, "runway", "Runway", commercial_use="da")
    eleven = connection(engine, "elevenlabs", "ElevenLabs", commercial_use="da")

    film_licence_ledger(engine, _production_on(runway, eleven))

    assert cards(engine, "commercial_use") == []


# --------------------------------------------- (e) a film assembled with no music: the music


def test_a_film_assembled_while_the_library_has_no_music_puts_the_music_card(
    engine, tmp_path, monkeypatch
):
    from app.media import assembler, music_library

    monkeypatch.setattr(
        music_library, "load_library", lambda *a: music_library.Library(path=tmp_path / "m.json")
    )
    monkeypatch.setattr(
        assembler,
        "mix_bed",
        lambda ffmpeg, voice, out, **kw: {"path": voice, "bed": None, "ambience": []},
    )
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"")

    for _ in range(2):
        mixed = assembler.film_mix(
            engine,
            str(uuid4()),
            "ffmpeg",
            voice,
            [],
            tmp_path,
            duration=1.0,
            title="Un film",
        )
        assert mixed["advisory"] == assembler.NO_BED_ADVISORY, "the film still says it"

    (card,) = cards(engine, "music_library")
    assert card.dedupe_key == sources.MUSIC_KEY
    assert "«Un film»" in card.why_ro
    assert card.clears_when == {"type": "music_library_has_music"}


# ------------------------------------------- (f) the sheet repair paused: what unblocks it


def _paused_by_the_language_model(engine, film_id):  # noqa: F811 - not the fixture
    from app.media import blocker_repair as repair

    reading = sheet(engine, film_id)
    first = repair.submit_sheet_issues(engine, reading)
    unresolved(engine, first)
    model_runs(engine, "FAILED", "FAILED", "FAILED")
    paused = repair.submit_sheet_issues(engine, reading)
    assert paused["status"] == "PAUSED" and paused["cause"] == "LANGUAGE_MODEL_DOWN"
    return reading


def test_a_repair_paused_by_the_language_model_puts_a_card_and_keeps_its_letter(
    engine,
    film,  # noqa: F811
):
    from app.media import blocker_repair as repair

    reading = _paused_by_the_language_model(engine, film)
    repair.submit_sheet_issues(engine, reading)

    (letter,) = paused_letters(engine)
    (card,) = cards(engine, "sheet_repair_paused")
    assert card.status == "PENDING" and card.subject_id == film
    assert card.dedupe_key == sources.sheet_repair_key(film, "LANGUAGE_MODEL_DOWN")
    assert "modelul de limbaj nu răspunde" in card.why_ro
    keys = [option["key"] for option in card.options]
    assert keys[0] == "reconnect" and card.options[0]["recommended"]
    assert card.options[0]["apply"]["place"] == "llm"
    assert "wait" in keys
    assert card.clears_when == {"type": "sheet_repair_resumed", "storyboard_id": film}
    assert letter.body_json["cause"] == "LANGUAGE_MODEL_DOWN"


def test_the_repair_card_is_withdrawn_when_the_repair_resumes(engine, film):  # noqa: F811
    from app.media import blocker_repair as repair

    reading = _paused_by_the_language_model(engine, film)
    model_runs(engine, "SUCCEEDED", "SUCCEEDED", "SUCCEEDED")

    resumed = repair.submit_sheet_issues(engine, reading)

    assert resumed.get("task_id"), resumed
    assert paused_letters(engine) == []
    assert cards(engine, "sheet_repair_paused")[0].status == "WITHDRAWN"


def _paused_for_the_day(engine, film_id):
    from app.media import blocker_repair as repair

    reading = sheet(engine, film_id)
    for n in range(repair.MAX_SAME_ISSUES_PER_DAY):
        dispatched = repair.submit_sheet_issues(engine, reading)
        unresolved(engine, dispatched, minutes_ago=600 - n)
    paused = repair.submit_sheet_issues(engine, reading)
    assert paused["status"] == "PAUSED" and paused["cause"] == "DAILY_LIMIT"
    return reading


def test_his_accept_lets_the_paused_repair_try_again_now(engine, film):  # noqa: F811
    from app.media import blocker_repair as repair

    reading = _paused_for_the_day(engine, film)
    (card,) = cards(engine, "sheet_repair_paused")
    assert card.dedupe_key == sources.sheet_repair_key(film, "DAILY_LIMIT")
    assert card.options[0]["key"] == "retry" and card.options[0]["recommended"]
    assert card.options[0]["apply"]["type"] == "sheet_repair_retry"

    answer = accept(engine, card)

    assert answer["decision"]["status"] == "ACCEPTED"
    again = repair.submit_sheet_issues(engine, reading)
    assert again.get("task_id"), again
    assert paused_letters(engine) == [], "the pause letter closes when the repair resumes"
    # Accepted twice (a retried click) the retry is recorded once.
    with Session(engine) as session:
        from app.models import DomainEvent

        retries = list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == repair.RETRY_EVENT))
        )
    assert len(retries) == 1 and retries[0].payload["decided_by"] == "owner"


def test_only_the_owner_lets_the_repair_try_again(engine, film):  # noqa: F811
    from app.media import blocker_repair as repair

    with pytest.raises(PermissionError):
        repair.allow_repair_retry(engine, film, issued_by="Director", correlation_id=str(uuid4()))


def test_his_accept_turns_the_blocked_scenes_into_a_local_move(engine, film):  # noqa: F811
    from app.media.models import StoryboardScene
    from app.media.production_policy import LOCAL_MOVE
    from app.media.shooting_sheet import sheet_overrides

    with Session(engine) as session, session.begin():
        scene = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == film))
        scene.prompt_json = {**scene.prompt_json, "source": "template"}
    _paused_for_the_day(engine, film)
    (card,) = cards(engine, "sheet_repair_paused")
    local = next(option for option in card.options if option["key"] == "local_move")
    scenes = local["apply"]["scenes"]
    assert scenes and local["apply"]["type"] == "sheet_local_move"

    accept(engine, card, "local_move")

    chosen = sheet_overrides(engine, film)
    assert all(chosen.get(index) == LOCAL_MOVE for index in scenes), chosen


def test_producers_never_decide_and_write_no_ledger_event_when_they_propose(engine):
    from app.models import DomainEvent

    with Session(engine) as session:
        before = len(list(session.scalars(select(DomainEvent.event_id))))
    with Session(engine) as session, session.begin():
        sources.music_library_empty(session, title="Un film")
    with Session(engine) as session:
        after = len(list(session.scalars(select(DomainEvent.event_id))))
    (card,) = cards(engine)
    assert card.status == "PENDING" and card.decided_by is None
    assert after == before


# ------------------------------------------- verification (2026-10-03): his answers stand


def test_his_keep_it_as_it_is_answer_stands_like_a_refusal(engine):
    """Accepting «Filmele merg fără muzică» (an option that applies nothing) is his no to the
    change: the next film must not put the same question back in front of him that day."""
    with Session(engine) as session, session.begin():
        sources.music_library_empty(session, title="Un film")
    (card,) = cards(engine, "music_library")
    accept(engine, card, "without")

    with Session(engine) as session, session.begin():
        again = sources.music_library_empty(session, title="Alt film")
    assert again is None, "his «as it is» answer is not asked again for a week"
    assert len(cards(engine, "music_library")) == 1


def test_a_guided_accept_does_not_silence_the_question(engine, tmp_path, monkeypatch):
    """A guided accept that he later marks done while the library is still empty is not a no:
    the next film may ask again."""
    from app.media import music_library

    monkeypatch.setattr(
        music_library, "load_library", lambda *a: music_library.Library(path=tmp_path / "m.json")
    )
    with Session(engine) as session, session.begin():
        sources.music_library_empty(session, title="Un film")
    (card,) = cards(engine, "music_library")
    accept(engine, card, "add")
    (waiting,) = cards(engine, "music_library")
    assert waiting.status == "WAITING_FOR_OWNER_ACTION"
    decide_owner_decision(
        engine,
        waiting.id,
        DecideCommand(command_id=uuid4(), expected_version=waiting.version, decision="DONE"),
        issued_by="owner",
    )
    with Session(engine) as session, session.begin():
        again = sources.music_library_empty(session, title="Alt film")
    assert again is not None


def test_the_paused_repair_shows_once_in_his_window_not_as_a_letter_and_a_card(
    engine,
    film,  # noqa: F811
):
    from app.decisions.services import owner_decision_cards

    _paused_by_the_language_model(engine, film)
    assert len(paused_letters(engine)) == 1

    feed = owner_decision_cards(engine)
    about_the_pause = [
        card
        for card in feed["cards"]
        if card["kind"] == "sheet_repair_paused"
        or (card["source_type"] == "letter" and card["kind"] == "sheet_repair_paused")
    ]
    assert [card["source_type"] for card in about_the_pause] == ["decision"], about_the_pause
    assert feed["counts"]["letters"] == 0
