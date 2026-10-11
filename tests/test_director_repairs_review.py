"""The adversarial review of the Director's repair desk, 2026-10-11: one test per finding.

Each rebuilds, on fakes, the case the review reproduced on the code as it was, and asserts
what the desk does now: no model switched on stale history or over a model that answers, no
department's owed work closed by a loop rule or a cost report, a declined repair offered again
once its refusal is lifted, one card for what only the Owner can do (never a letter at every
loop), a card he answered not asked again, a review not cut short, a thread's history not read
as a new loop, one decision per case, measured costs not «compared» with themselves, an
invoice's cover said, her choice to wait kept, the day's replay as the books knew it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.command import direct_company
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, AgentRun
from app.agents.repairs import registered_repairs
from app.agents.repairs.desk import execute_repair, repair_matters, submit_repair
from app.analytics.models import DirectorDecision
from app.analytics.performance import film_cost
from app.decisions.models import OwnerDecision
from app.decisions.services import DecideCommand, decide_owner_decision
from app.economy.as_of import economy_as_of
from app.economy.models import ProviderCostRecord
from app.integrations.services import assign_agent
from app.models import OwnerPolicy
from app.providers.base import GenerateResult
from app.providers.registry import ProviderRegistry
from app.services import utc_now
from app.workflows.models import TaskQueueItem
from app.workflows.worker import build_task_handlers, work_once
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_director_repairs import (
    Models,
    a_connection,
    a_handoff,
    a_published_film,
    agent_of,
    an_open_decision,
    cards,
    matter_of,
    owner_letters,
    owner_price,
    run_repair,
    runs,
    staffed_studio,
    this_month,
)

NOW = datetime.now(UTC)


@pytest.fixture(name="studio")
def _studio(engine):
    return staffed_studio(engine)


def _drain(engine, settings, registry=None) -> list[dict]:
    handlers = build_task_handlers(engine, settings, None, None, registry or ProviderRegistry())
    done = []
    while (result := work_once(engine, handlers)) is not None:
        done.append(result)
    return done


def _switch_matters(engine, settings, registry=None) -> list[dict]:
    return [
        m
        for m in repair_matters(engine, settings, registry)
        if m["matter_key"].startswith("agent_failing_")
        and m["repair"]["name"] == "switch_agent_model"
    ]


# ----------------------------------------------------- 1. a switch on stale history (blocker)


def test_failures_before_the_owner_chose_her_model_again_are_no_case_against_it(
    engine, studio, settings
):
    cloud = a_connection(engine, models=("owner-model", "other-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    runs(
        engine,
        lyra.id,
        model="owner-model",
        provider=cloud["provider"],
        at=NOW - timedelta(days=6),
        n=3,
        status="FAILED",
        error="ProviderHTTPError: HTTP 503 — furnizorul are o problemă",
    )
    # The Owner (re)chooses owner-model after the blip.
    with Session(engine) as session:
        version = session.get(Agent, lyra.id).version
    assign_agent(engine, lyra.id, cloud["models"]["owner-model"], version)
    registry = ProviderRegistry()
    registry.register(cloud["id"], Models(refusing=set()))
    assert not _switch_matters(engine, settings, registry)


def test_her_model_answering_the_probe_is_not_switched(engine, studio, settings):
    cloud = a_connection(engine, models=("owner-model", "other-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["owner-model"], lyra.version)
    # Three provider errors of an outage that has since passed.
    runs(
        engine,
        lyra.id,
        model="owner-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),
        n=3,
        status="FAILED",
        error="ProviderHTTPError: HTTP 503 — furnizorul are o problemă",
    )
    fake = Models(refusing=set())
    registry = ProviderRegistry()
    registry.register(cloud["id"], fake)
    (matter,) = _switch_matters(engine, settings, registry)
    done = run_repair(engine, settings, matter, registry)
    assert done["result"]["status"] == "NOTHING_TO_DO", done["result"]
    assert fake.asked == ["owner-model"], "her own model is asked first, and only it"
    with Session(engine) as session:
        assert session.get(Agent, lyra.id).model_id == cloud["models"]["owner-model"]


def test_a_providers_cached_refusal_is_not_a_failure_of_her_model(engine, studio, settings):
    cloud = a_connection(engine, models=("owner-model", "other-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["owner-model"], lyra.version)
    runs(
        engine,
        lyra.id,
        model="owner-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),
        n=3,
        status="BLOCKED_PROVIDER",
        error="Provider status is 'UNHEALTHY'; cannot run.",
    )
    assert not _switch_matters(engine, settings)


def test_probes_are_not_her_work_and_without_settings_no_model_is_a_candidate(
    engine, studio, settings
):
    from app.agents.repairs.agent_health import candidates, diagnosis

    cloud = a_connection(engine, models=("broken-model", "other-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["broken-model"], lyra.version)
    runs(
        engine,
        lyra.id,
        model="broken-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),
        n=3,
        status="FAILED",
        error="ProviderHTTPError: HTTP 401 — cheia conexiunii este respinsă",
    )
    registry = ProviderRegistry()
    registry.register(cloud["id"], Models(refusing={"broken-model", "other-model"}))
    with Session(engine) as session:
        agent = session.get(Agent, lyra.id)
        before = diagnosis(session, agent)
        # The deny list lives in the settings: without them, no candidate, not every one.
        assert candidates(session, agent, None, registry) == []
    (matter,) = _switch_matters(engine, settings, registry)
    done = run_repair(engine, settings, matter, registry)
    assert done["result"]["status"] == "DECLINED"
    with Session(engine) as session:
        probes = session.scalars(
            select(AgentRun).where(AgentRun.task_type == "TEST_CONNECTIVITY")
        ).all()
        assert len(probes) == 2 and all(p.status == "FAILED" for p in probes)
        after = diagnosis(session, session.get(Agent, lyra.id))
    # Two failed probes later her record, and so the case, is the same.
    assert (after["runs"], after["failed"], after["last_failure"]) == (
        before["runs"],
        before["failed"],
        before["last_failure"],
    )


# ------------------------------------------- 2. owed work and standing guidance stay open


def test_a_looping_thread_keeps_standing_guidance_and_a_budget_request_open(
    engine, studio, settings
):
    kael, sarah, nadia = (agent_of(engine, r) for r in ("VideoEditor", "Director", "Accountant"))
    with Session(engine) as session, session.begin():
        weekly = post_message(
            session,
            intent="HANDOFF",
            subject="Indicațiile Directorului pentru departamentul de video — 2026-W41",
            body={"instructions": "Mișcare din prima secundă.", "week": "2026-W41"},
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        ).id
        reply = None
        for index in range(3):  # a burst: three replies in a minute
            reply = post_message(
                session,
                intent="STATUS",
                subject="Re: Indicațiile Directorului",
                body={"done": False, "about_message_id": weekly},
                body_text=f"Notat {index}: aplic {index * 11} reguli diferite azi {index}.",
                from_agent_id=kael.id,
                in_reply_to=weekly,
            )
        budget = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Cerere de buget: +5 USD — 2026-W41",
            body={"budget_request": True, "amount_usd": 5, "week": "2026-W41"},
            body_text="Cerere de buget.",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=reply.id,
        ).id
        question = post_message(
            session,
            intent="REQUEST_INFO",
            subject="De lămurit",
            body={},
            body_text="Ce lipsește?",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
            in_reply_to=reply.id,
        ).id
    matter = matter_of(engine, settings, "thread_loops")
    assert run_repair(engine, settings, matter)["result"]["status"] == "APPLIED"
    with Session(engine) as session:
        assert session.get(AgentMessage, weekly).status == "OPEN", "the week's guidance stays"
        assert session.get(AgentMessage, budget).status == "OPEN", "the Owner's request stays"
        assert session.get(AgentMessage, question).status == "RESOLVED"


# ------------------------------------------------- 3. a review closes the decision, not work


def test_a_review_closes_the_decision_but_not_the_departments_owed_work(engine, studio, settings):
    a_published_film(engine, studio["channel_id"])
    kael, sarah = agent_of(engine, "VideoEditor"), agent_of(engine, "Director")
    with Session(engine) as session, session.begin():
        handoff = post_message(
            session,
            intent="HANDOFF",
            subject="ITERATE: refă primul cadru și miniatura",
            body={"kind": "direction"},
            body_text="DE FĂCUT: improve the first frame and the thumbnail moment",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        ).id
    reviewed = an_open_decision(
        engine,
        matter_key="growth_reach_12345678",
        action="improve the first frame and the thumbnail moment",
        role="VideoEditor",
        message_id=handoff,
    )
    registry = ProviderRegistry()
    registry.register(studio["local_provider"], Models(refusing=set()))
    direct_company(engine, registry, settings)
    _drain(engine, settings, registry)
    with Session(engine) as session:
        assert session.get(DirectorDecision, reviewed).state == "REVIEWED"
        letter = session.get(AgentMessage, handoff)
        assert letter.status == "OPEN", "Kael never said it was done: the work is still owed"


# ------------------------------------------- 4. her model's own words for the film cost


def test_a_film_cost_decision_in_her_models_own_words_is_closed_with_the_report(
    engine, studio, settings
):
    a_published_film(engine, studio["channel_id"])
    nadia = agent_of(engine, "Accountant")
    handoff = a_handoff(engine, "Accountant")
    decision = an_open_decision(
        engine,
        matter_key="review_bottleneck_research",
        action=(
            "Report what a film cost against what it returned for the 3 measured films to "
            "the Owner, with the stage-level breakdown"
        ),
        role="Accountant",
        message_id=handoff,
        review_after_videos=50,
    )
    with Session(engine) as session, session.begin():
        for index in range(3):
            post_message(
                session,
                intent="STATUS",
                subject="Re: costul filmelor",
                body={"done": False, "about_message_id": handoff},
                body_text=f"Nu pot atribui costul ({index}) fără lista {index * 3} de prețuri.",
                from_agent_id=nadia.id,
                in_reply_to=handoff,
            )
    done = run_repair(engine, settings, matter_of(engine, settings, "thread_loops"))
    assert done["result"]["status"] == "APPLIED"
    with Session(engine) as session:
        closed = session.get(DirectorDecision, decision)
        assert closed.state == "REVIEWED" and "The Higgs Boson" in closed.outcome


def test_the_cost_report_is_computed_whatever_words_her_model_uses():
    from app.agents.command import Choice, _repair_spec

    def matter(key: str, action: str) -> dict:
        return {"matter_key": key, "action": action, "owner_role": "Accountant"}

    def choice(key: str, action: str) -> Choice:
        return Choice(matter_key=key, decision="ITERATE", confidence="MEDIUM", action=action)

    # The idle Accountant's matter is the report, whatever words carry it.
    idle = _repair_spec(
        matter("idle_costs_unread", "report what a film cost against what it returned"),
        choice("idle_costs_unread", "Have Nadia tally each film's spend for the Owner"),
    )
    assert idle is not None and idle["name"] == "film_cost_report"
    # Any matter whose action her model wrote in its own case and words.
    worded = _repair_spec(
        matter("growth_reach_1", "improve the first frame and the thumbnail moment"),
        choice("growth_reach_1", "Report what a film cost against what it returned, film by film"),
    )
    assert worded is not None and worded["name"] == "film_cost_report"
    # And a department's own work stays a department's.
    assert (
        _repair_spec(
            matter("growth_reach_1", "improve the first frame and the thumbnail moment"),
            choice("growth_reach_1", "improve the first frame and the thumbnail moment"),
        )
        is None
    )


# ------------------------------------------- 5. a declined repair comes back, once lifted


def test_a_repair_declined_under_the_stop_is_offered_again_a_day_after(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)
    matter = matter_of(engine, settings, "unpriced_usage")
    queued = submit_repair(
        engine,
        matter=matter,
        spec=matter["repair"],
        decision="ITERATE",
        interpretation="",
        confidence="HIGH",
        correlation_id=str(uuid4()),
        run_id=None,
        published=0,
    )
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    with Session(engine) as session:
        payload = dict(session.get(TaskQueueItem, queued["task_id"]).payload)
    declined = execute_repair(engine, None, settings, payload, correlation_id=queued["task_id"])
    assert declined["status"] == "DECLINED"
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    def offered() -> bool:
        return any(m["matter_key"] == "unpriced_usage" for m in repair_matters(engine, settings))

    assert not offered(), "not at every loop: a day after the refusal"
    with Session(engine) as session, session.begin():
        row = session.get(DirectorDecision, queued["decision_id"])
        row.reviewed_at = (NOW - timedelta(hours=25)).isoformat()
    assert offered(), "the stop was lifted and the runs are still unpriced"


def test_pricing_that_would_exceed_a_budget_is_one_card_for_the_owner(engine, studio, settings):
    from app.economy.budget import BudgetCommand, set_budget

    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(seconds=5)),
        n=3,
        spacing_seconds=0.1,
        prompt=1_000_000,
        completion=1_000_000,
    )
    owner_price(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="2"))
    for _ in range(2):
        result = execute_repair(
            engine, None, settings, {"repair": "reprice_unpriced_runs"}, correlation_id=str(uuid4())
        )
        assert result["status"] == "DECLINED"
    (card,) = cards(engine, "director_reprice_budget:")
    assert card.status == "PENDING" and "bugetul" in card.why_ro
    assert {o["apply"]["type"] for o in card.options} == {"guided", "none"}


# ------------------------------------- 6. what her mode forbids: one card, not a letter a loop


def test_a_repair_her_mode_forbids_is_one_card_not_a_letter_at_every_loop(engine, studio, settings):
    cloud = a_connection(engine, models=("broken-model", "working-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["broken-model"], lyra.version)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "MANUAL"

    def fail() -> None:
        runs(
            engine,
            lyra.id,
            model="broken-model",
            provider=cloud["provider"],
            at=datetime.now(UTC),
            n=3,
            status="FAILED",
            error="HTTPError",
        )

    fail()
    direct_company(engine, None, settings)
    fail()  # new failures: a new count in the observation
    direct_company(engine, None, settings)
    escalations = [
        m
        for m in owner_letters(engine)
        if m.intent == "ESCALATE"
        and str((m.body_json or {}).get("matter_key", "")).startswith("agent_failing_")
    ]
    assert escalations == [], [m.subject for m in escalations]
    (card,) = cards(engine, "director_repair:agent_failing_")
    assert card.status == "PENDING" and "MANUAL" in card.dedupe_key
    assert card.options[0]["apply"]["place_ro"] == "Setări → Angajați"


# ------------------------------------------- 7. an invoice card he answered is not re-asked


def _estimate(session, provider, when, micros) -> None:
    session.add(
        ProviderCostRecord(
            id=str(uuid4()),
            provider=provider,
            external_reference=str(uuid4()),
            status="ESTIMATED",
            amount_micros=micros,
            currency="USD",
            usd_micros=micros,
            attribution_json={"storyboard_id": str(uuid4())},
            recorded_at=when.isoformat(),
        )
    )


def _decide(engine, card_id, decision, option=None) -> None:
    with Session(engine) as session:
        version = session.get(OwnerDecision, card_id).version
    decide_owner_decision(
        engine,
        card_id,
        DecideCommand(
            command_id=uuid4(),
            expected_version=version,
            decision=decision,
            **({"option_key": option} if option else {}),
        ),
        issued_by="owner",
    )


def test_an_invoice_card_he_answered_is_not_asked_again_for_the_same_estimates(
    engine, studio, settings
):
    old = NOW - timedelta(days=20)
    with Session(engine) as session, session.begin():
        _estimate(session, "runway", old, 500_000)
        _estimate(session, "runpod", old, 900_000)
    run_repair(engine, settings, matter_of(engine, settings, "unbilled_estimates"))
    (runway,) = cards(engine, "unbilled:runway:")
    assert "prepaid" in {o["key"] for o in runway.options}
    _decide(engine, runway.id, "ACCEPT")
    _decide(engine, runway.id, "DONE")
    assert "unbilled_estimates" not in {m["matter_key"] for m in repair_matters(engine, settings)}
    execute_repair(engine, None, settings, {"repair": "unbilled_estimates"}, correlation_id="x")
    assert len(cards(engine, "unbilled:runway:")) == 1, "the same estimates, the same answer"
    # A new estimate of that month is a new question.
    with Session(engine) as session, session.begin():
        _estimate(session, "runway", old + timedelta(hours=1), 200_000)
    run_repair(engine, settings, matter_of(engine, settings, "unbilled_estimates"))
    found = cards(engine, "unbilled:runway:")
    assert len(found) == 2 and sorted(c.status for c in found)[-1] == "PENDING"


# ------------------------------------------- 8. a decision's review is not cut short


def test_a_decision_whose_review_is_not_due_stays_open_after_its_letter_closes(
    engine, studio, settings
):
    from app.agents.messages import resolve_message

    dr_aris = agent_of(engine, "LeadResearcher")
    handoff = a_handoff(engine, "LeadResearcher", subject="Ține subiectul LHC")
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject="Re: Ține subiectul LHC",
            body={"done": True, "about_message_id": handoff},
            body_text="Am confirmat; subiectul rămâne.",
            from_agent_id=dr_aris.id,
            in_reply_to=handoff,
        )
        resolve_message(
            session, handoff, resolution="Am confirmat.", resolved_by="Dr. Aris", status="ANSWERED"
        )
    measured_later = an_open_decision(
        engine,
        matter_key="cold_start_23d3ba8b",
        action="Hold the topic pipeline as is",
        role="LeadResearcher",
        message_id=handoff,
        decision="HOLD",
        review_after_videos=3,
    )
    # A HANDOFF closed as ANSWERED without her done=true (as before the mail's rule) is not
    # work done either.
    legacy = a_handoff(engine, "LeadResearcher", subject="Verifică sursele")
    with Session(engine) as session, session.begin():
        resolve_message(
            session, legacy, resolution="Am citit.", resolved_by="Dr. Aris", status="ANSWERED"
        )
    acknowledged = an_open_decision(
        engine,
        matter_key="sources_unchecked",
        action="check the authorised sources",
        role="LeadResearcher",
        message_id=legacy,
        decision="NEEDS_MORE_DATA",
        review_after_videos=None,
    )
    stale = [m for m in repair_matters(engine, settings) if m["matter_key"] == "stale_decisions"]
    ids = set(stale[0]["repair"]["params"]["decision_ids"]) if stale else set()
    assert measured_later not in ids and acknowledged not in ids


def test_a_loop_after_the_work_was_done_leaves_the_decision_to_its_review(engine, studio, settings):
    """The studio's copy of 2026-10-11: Vera answered the dead-letter HANDOFF done=true in a
    burst of replies; its decision is reviewed after three films, two of which were out."""
    vera, sarah = agent_of(engine, "Publisher"), agent_of(engine, "Director")
    handoff = a_handoff(engine, "Publisher", subject="De ce a murit publicarea")
    with Session(engine) as session, session.begin():
        reply = None
        for index in range(3):
            reply = post_message(
                session,
                intent="STATUS",
                subject="Re: De ce a murit publicarea",
                body={"done": index == 2, "about_message_id": handoff},
                body_text=f"Caut {index}: jurnalul {index * 5} al cozii, pasul {index}.",
                from_agent_id=vera.id,
                in_reply_to=handoff,
            )
        from app.agents.messages import resolve_message

        resolve_message(
            session, handoff, resolution="Am găsit cauza.", resolved_by="Vera", status="ANSWERED"
        )
        follow_up = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Raportează de ce a eșuat publicarea",
            body={},
            body_text="Care film?",
            from_agent_id=sarah.id,
            to_agent_id=vera.id,
            in_reply_to=reply.id,
        ).id
    decision = an_open_decision(
        engine,
        matter_key="dead_letters",
        action="Report why the dead-lettered publication failed",
        role="Publisher",
        message_id=handoff,
        review_after_videos=3,
    )
    done = run_repair(engine, settings, matter_of(engine, settings, "thread_loops"))
    assert done["result"]["status"] == "APPLIED"
    with Session(engine) as session:
        assert session.get(AgentMessage, follow_up).status == "RESOLVED", "the loop is closed"
        assert session.get(DirectorDecision, decision).state == "OPEN", "its review is to come"


# ------------------------------------------- 9. a thread's history is not a new loop


def test_a_thread_that_looped_once_is_not_closed_again_for_its_history(engine, studio, settings):
    nadia, sarah = agent_of(engine, "Accountant"), agent_of(engine, "Director")
    handoff = a_handoff(engine, "Accountant")
    with Session(engine) as session, session.begin():
        reply = None
        for index in range(3):
            reply = post_message(
                session,
                intent="STATUS",
                subject="Re: x",
                body={"done": True, "about_message_id": handoff},
                body_text=f"answer {index} distinct words {index * 7} alpha{index}",
                from_agent_id=nadia.id,
                in_reply_to=handoff,
            )
        reply_id = reply.id
    assert (
        run_repair(engine, settings, matter_of(engine, settings, "thread_loops"))["result"][
            "status"
        ]
        == "APPLIED"
    )
    # The same day, a new and legitimate question in that thread.
    with Session(engine) as session, session.begin():
        fresh = post_message(
            session,
            intent="REQUEST_INFO",
            subject="De investigat: luna nouă",
            body={},
            body_text="Ce s-a schimbat luna aceasta?",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=reply_id,
        ).id
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "thread_loops"]
    # And two weeks on, the old burst is history as well.
    with Session(engine) as session, session.begin():
        for letter in session.scalars(select(AgentMessage)):
            letter.created_at = (NOW - timedelta(days=14)).isoformat()
            if letter.resolved_at:
                letter.resolved_at = (NOW - timedelta(days=14)).isoformat()
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "thread_loops"]
    with Session(engine) as session:
        assert session.get(AgentMessage, fresh).status == "OPEN"


# ------------------------------------------- 10. one case, one decision, one task


def test_a_case_submitted_twice_is_one_decision_and_one_task(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)
    matter = matter_of(engine, settings, "unpriced_usage")
    for _ in range(2):
        submit_repair(
            engine,
            matter=matter,
            spec=matter["repair"],
            decision="ITERATE",
            interpretation="",
            confidence="HIGH",
            correlation_id="c",
            run_id=None,
            published=0,
        )
    _drain(engine, settings)
    with Session(engine) as session:
        rows = session.scalars(
            select(DirectorDecision).where(DirectorDecision.matter_key == "unpriced_usage")
        ).all()
        assert [r.state for r in rows] == ["REVIEWED"]


def test_a_matter_her_model_names_twice_is_one_choice(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)

    class Twice(Models):
        async def generate(self, model, prompt, **kwargs):
            choice = {
                "matter_key": "unpriced_usage",
                "decision": "ITERATE",
                "interpretation": "price them",
                "confidence": "HIGH",
                "action": "reprice",
                "owner_role": "Director",
                "repair_action": "reprice_unpriced_runs",
            }
            return GenerateResult(json.dumps({"choices": [choice, choice]}), 50, 20, None)

    registry = ProviderRegistry()
    registry.register(studio["local_provider"], Twice(refusing=set()))
    result = direct_company(engine, registry, settings)
    assert [r["matter_key"] for r in result["repairs"]] == ["unpriced_usage"]
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count()).where(DirectorDecision.matter_key == "unpriced_usage")
            )
            == 1
        )


# ------------------------------------------- 12. a film's estimate an invoice has covered


def test_a_films_estimate_covered_by_an_invoice_is_said_so(engine, studio, settings):
    from app.agents.repairs.film_cost import film_report, report_words

    film = a_published_film(engine, studio["channel_id"])
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(ProviderCostRecord).where(ProviderCostRecord.provider == "runpod")
        ):
            row.reconciled_at = utc_now()
    cost = film_cost_of(engine, film["storyboard_id"])
    assert cost["reconciled_usd_micros"] == 9 * 509_383
    assert cost["estimated_usd_micros"] == 56_760
    assert cost["total_usd_micros"] == 9 * 509_383 + 56_760, "no double count"
    assert "acoperit de factură" in report_words(film_report(engine))


def film_cost_of(engine, storyboard_id: str) -> dict:
    with Session(engine) as session:
        return film_cost(session, storyboard_id)


# ------------------------------------------- 13. her choice to wait is kept


def test_her_choice_to_wait_holds_the_repair_until_the_next_day(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)

    class Holds(Models):
        async def generate(self, model, prompt, **kwargs):
            choice = {
                "matter_key": "unpriced_usage",
                "decision": "HOLD",
                "interpretation": "wait for the month's close",
                "confidence": "MEDIUM",
                "action": "wait",
                "owner_role": "Director",
            }
            return GenerateResult(json.dumps({"choices": [choice]}), 50, 20, None)

    registry = ProviderRegistry()
    registry.register(studio["local_provider"], Holds(refusing=set()))
    assert direct_company(engine, registry, settings)["repairs"] == []
    # The next loop without a model: the measurements' own order does not make it either.
    assert direct_company(engine, None, settings)["repairs"] == []
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TaskQueueItem)) == 0
        assert session.scalar(select(AgentRun.cost_vr).where(AgentRun.agent_id == sarah.id)) is None


# ------------------------------------------- 14. the day's replay, and the price card's grace


def test_the_days_replay_keeps_a_run_priced_later_unpriced_until_then(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    ran = this_month(engine, timedelta(minutes=30))
    runs(engine, sarah.id, model="kimi-k3", provider=cloud["provider"], at=ran)
    owner_price(engine)
    then = (ran + timedelta(seconds=5)).isoformat()
    before = economy_as_of(engine, [then])["readings"][0]["budget"]["today"]
    run_repair(engine, settings, matter_of(engine, settings, "unpriced_usage"))
    replay = economy_as_of(engine, [then, datetime.now(UTC).isoformat()])["readings"]
    assert replay[0]["budget"]["today"]["unpriced_agent_runs"] == before["unpriced_agent_runs"] == 1
    assert replay[0]["budget"]["today"]["agent_usd_micros"] == 0
    assert replay[1]["budget"]["today"]["unpriced_agent_runs"] == 0
    assert replay[1]["budget"]["today"]["agent_usd_micros"] > 0


def test_a_price_card_waits_the_detectors_grace_when_the_repair_runs(engine, studio, settings):
    cloud = a_connection(engine, models=("kimi-k3",))
    other = a_connection(engine, kind="openai", name="OpenAI", models=("gpt-x",))
    sarah = agent_of(engine, "Director")
    at = this_month(engine, timedelta(hours=1))
    runs(engine, sarah.id, model="kimi-k3", provider=cloud["provider"], at=at)
    runs(engine, sarah.id, model="gpt-x", provider=other["provider"], at=at, n=2)
    owner_price(engine)  # ollama only; the OpenAI runs are an hour old
    done = run_repair(engine, settings, matter_of(engine, settings, "unpriced_usage"))
    assert done["result"]["status"] == "APPLIED"
    assert not cards(engine, "director_price:"), "an hour on, he may be typing that price"


# ------------------------------------------- 16. the report is a write, at a write's tier


def test_the_film_cost_report_asks_the_kernel_for_a_write():
    report = registered_repairs()["film_cost_report"]
    assert report.tier == "T1" and report.action != "analytics.read"
