"""What stopped the studio from publishing on 2026-10-13/15, each pinned (Owner: «ce o oprește
din a face publicările; să publice singură»).

1. `think: false` on Ollama Cloud made glm-5.3-flash narrate its reasoning into the visible
   answer — no JSON, scripts and episodes refused for two days. Cloud is asked nothing about
   thinking now; the local endpoint still is.
2. A writer whose answer carries no object is asked once more in JSON mode with his own
   thinking on, before the studio refuses him.
3. The motion redo of a scene whose new still was already approved was refused LINT_BLOCKED on
   the still prompt's words (thirteen walks on «The Zero Script Club»): an approved picture's
   words are not re-judged when motion is bought.
4. Every probe failing at the provider at once is an outage, not a card for the Owner.
5. A film that passed quality control and waits unpublished for days no longer holds the
   next topic.

Every provider is stubbed; nothing is bought, nothing is sent anywhere.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.repairs import DECLINED, RepairContext, agent_health
from app.factual import agent_pipeline
from app.factual.agent_pipeline import JSON_AGAIN, answered_with_object
from app.integrations.llm import ConfiguredLLM
from app.story.services import episode_object
from sqlalchemy import select
from sqlalchemy.orm import Session

NARRATION = "Let me work through this carefully. The user wants a JSON object with scenes..."
OBJECT = '{"title": "T", "voiceover_full_text": "v", "scenes": [], "referenced_claim_ids": []}'


# ------------------------------------------------------------------ 1. the thinking flag


def _bodies(monkeypatch, adapter: ConfiguredLLM) -> list[dict]:
    sent: list[dict] = []

    def fake_request(method, path, body=None):
        sent.append(dict(body or {}))
        return {"response": OBJECT, "done_reason": "stop", "eval_count": 5}

    monkeypatch.setattr(adapter, "request", fake_request)
    return sent


def test_cloud_is_asked_nothing_about_thinking_and_the_local_endpoint_still_is(monkeypatch):
    cloud = ConfiguredLLM("ollama", {"base_url": "https://ollama.com"}, {"api_key": "k"})
    sent = _bodies(monkeypatch, cloud)
    # As `run_agent_task` calls it on Cloud: no output cap of the studio's (provider-native).
    asyncio.run(cloud.generate("glm-5.3-flash", "Answer with JSON."))
    assert "think" not in sent[-1]
    assert "num_predict" not in sent[-1].get("options", {})
    # A caller that must say so (a second attempt with native thinking) still can.
    asyncio.run(cloud.generate("glm-5.3-flash", "Again.", extra={"think": True, "format": "json"}))
    assert sent[-1]["think"] is True and sent[-1]["format"] == "json"

    local = ConfiguredLLM("ollama", {"base_url": "http://127.0.0.1:11434"}, {"api_key": ""})
    sent = _bodies(monkeypatch, local)
    asyncio.run(local.generate("qwen3.5", "Answer with JSON.", max_tokens=700))
    assert sent[-1]["think"] is False
    assert sent[-1]["options"]["num_predict"] == 700


# ------------------------------------------------------------------ 2. the second attempt


def _writer(monkeypatch, answers: list[str]):
    calls: list[dict] = []

    def fake_run(engine, registry, agent_id, task_type, prompt, version, correlation, **kw):
        calls.append({"version": version, "extra": kw.get("extra"), "prompt": prompt})
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answers[len(calls) - 1],
            "model_name": "glm-5.3-flash",
        }

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    return calls


def test_a_writer_who_narrated_is_asked_once_more_in_json_mode(monkeypatch):
    # The first answer (narration) is already in hand; the stub answers the second attempt.
    calls = _writer(monkeypatch, ["```json\n" + OBJECT + "\n```"])
    first = {"status": "SUCCEEDED", "output_text": NARRATION, "model_name": "glm-5.3-flash"}
    result = answered_with_object(
        None,
        None,
        "writer",
        "write_script",
        "PROMPT",
        "v1",
        "c",
        first,
        summary="Scriu",
        max_tokens=7200,
        temperature=0.4,
    )
    assert OBJECT in result["output_text"]
    assert calls[-1]["version"] == "v1+json" and calls[-1]["extra"] == JSON_AGAIN
    assert calls[-1]["prompt"] == "PROMPT"  # the same words, not a scolding


def test_a_writer_who_answered_with_an_object_is_not_asked_again(monkeypatch):
    calls = _writer(monkeypatch, [])
    first = {"status": "SUCCEEDED", "output_text": OBJECT, "model_name": "kimi-k3"}
    assert (
        answered_with_object(
            None,
            None,
            "writer",
            "write_script",
            "PROMPT",
            "v1",
            "c",
            first,
            summary="Scriu",
            max_tokens=7200,
            temperature=0.4,
        )
        is first
    )
    assert calls == []


def test_a_writer_who_narrates_twice_keeps_the_first_answer_for_the_refusal(monkeypatch):
    _writer(monkeypatch, [NARRATION + " still narrating"])
    first = {"status": "SUCCEEDED", "output_text": NARRATION, "model_name": "glm-5.3-flash"}
    assert (
        answered_with_object(
            None,
            None,
            "writer",
            "write_script",
            "PROMPT",
            "v1",
            "c",
            first,
            summary="Scriu",
            max_tokens=7200,
            temperature=0.4,
        )
        is first
    )


def test_episode_object_reads_fenced_and_embedded_json_or_none():
    assert episode_object('```json\n{"title": "E"}\n```') == {"title": "E"}
    assert episode_object('Here you go: {"title": "E"} end') == {"title": "E"}
    assert episode_object(NARRATION) is None
    assert episode_object("") is None


# ------------------------------------------------------------------ 3. the approved still's words


def test_an_approved_stills_words_are_not_rejudged_when_motion_is_bought(
    engine, tmp_path, monkeypatch
):
    from app.media import prompt_agent
    from app.media.assembler import _motion_state
    from app.media.models import SceneTake
    from app.media.shooting_sheet import connection_capabilities
    from test_film_costing import a_film
    from test_motion_redo_prices_runpod import profile_delivers_the_frame
    from test_runpod_pipeline import connect

    _vault, identity = connect(engine, tmp_path, monkeypatch)
    profile_delivers_the_frame(engine, identity)
    board = a_film(engine, tmp_path, scenes=1)
    wardrobe = "still_prompt: ținuta vizibilă a lui Sarah lipsește; descrieți «Crisp navy blazer»"
    asked: list[tuple] = []

    def rejudge(package, *, layers=("still", "motion")):
        asked.append(layers)
        return [wardrobe] if "still" in layers else []

    monkeypatch.setattr(prompt_agent, "incomplete_plan_fields", rejudge)

    state = _motion_state(engine, board, capabilities=connection_capabilities(engine, identity))
    assert not any(wardrobe in f.message_ro for f in state["findings"]), state["findings"]
    assert not state["plan"]["lint_blocked"]

    # Without an approved still the scene's words are what a still would be bought on: judged.
    with Session(engine) as session, session.begin():
        for take in session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == board, SceneTake.kind == "still")
        ):
            take.status = "REJECTED"
    state = _motion_state(engine, board, capabilities=connection_capabilities(engine, identity))
    assert any(wardrobe in f.message_ro for f in state["findings"])


# ------------------------------------------------------------------ 4. an outage is not his card


def test_every_probe_failing_at_the_provider_is_an_outage_not_the_owners_card(
    engine, settings, monkeypatch
):
    from app.agents.models import Agent
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session:
        marcus = session.scalar(select(Agent).where(Agent.display_name.like("Marcus%")))
        agent_id = marcus.id

    monkeypatch.setattr(
        agent_health,
        "diagnosis",
        lambda session, agent, now=None: {
            "current": {"model": "glm-5.3-flash"},
            "cause": "PROVIDER_ERROR",
            "failing_now": True,
        },
    )
    monkeypatch.setattr(
        agent_health,
        "candidates",
        lambda session, agent, settings, registry: [
            SimpleNamespace(id="m-kimi", model_name="kimi-k3"),
            SimpleNamespace(id="m-mistral", model_name="mistral-large-4"),
        ],
    )
    probed: list[str] = []

    def down(context, agent_id, model_id, model_name, name):
        probed.append(model_name)
        return {
            "model": model_name,
            "status": "FAILED",
            "answered": False,
            "reason": "ProviderHTTPError: HTTP 400",
        }

    monkeypatch.setattr(agent_health, "_probe", down)
    cards: list[str] = []
    monkeypatch.setattr(
        agent_health, "_ask_owner", lambda context, agent_id, why: cards.append(why) or "card"
    )
    context = RepairContext(engine, settings, SimpleNamespace(), "corr")

    result = agent_health.switch_model(context, {"agent_id": agent_id})

    assert result["status"] == DECLINED
    assert result["changed"]["provider_down"] is True
    assert probed == ["glm-5.3-flash", "kimi-k3", "mistral-large-4"]
    assert cards == [], "an outage of the provider is not a question for the Owner"
    assert "reîncerc la trecerea următoare" in result["outcome_ro"]
    assert "Decizii" not in result["outcome_ro"]


# ------------------------------------------------------------------ 5. a passed film that waits


def test_a_passed_film_waiting_past_the_publish_wait_no_longer_holds_the_next_topic(engine):
    from app.media.models import VideoRenderJob
    from app.runbook.stages import PUBLISH_WAIT_DAYS, topics_in_production
    from test_cycle_fixes import _selected_topic_with_render

    fresh, _asset = _selected_topic_with_render(engine, verdict="PASSED")
    waited, waited_asset = _selected_topic_with_render(engine, verdict="PASSED")
    long_ago = (datetime.now(UTC) - timedelta(days=PUBLISH_WAIT_DAYS, hours=1)).isoformat()
    with Session(engine) as session, session.begin():
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == waited_asset)
        )
        job.started_at = long_ago
        job.finished_at = long_ago
    with Session(engine) as session:
        live, stalled = topics_in_production(session)
    assert fresh in live and waited not in live
    assert waited in stalled


# ------------------------------------------------------------------ 6. the route's allowance


def test_a_still_is_linted_against_the_allowance_of_the_route_it_is_bought_on(
    engine, tmp_path, monkeypatch
):
    """Production stills are bought on the GPU worker (Qwen, MAX_PROMPT characters) and a
    serial's complete prompt is never cut to fit (2026-10-14): the worker's models carry its
    allowance, another vendor can declare its own, and a model nobody declared keeps Runway's
    legacy thousand, under which a complete serial prompt is refused OVER_CAP."""
    from app.media import prompt_lint
    from app.media.models import StoryboardScene
    from app.media.shooting_sheet import build_sheet
    from runpod_worker.contract import MAX_PROMPT, WORKFLOWS
    from test_film_costing import SEEDANCE, a_film, still_prompt

    assert all(prompt_lint.ALLOWANCES[model] == MAX_PROMPT for model in WORKFLOWS)
    board = a_film(engine, tmp_path, scenes=1)
    room = "The room is lit by warm lamps and the plants on the sill stir softly."
    complete = still_prompt(1) + " " + " ".join([room] * 25)
    assert len(complete) > 1000
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        )
        scene.prompt_json = {**dict(scene.prompt_json or {}), "still_prompt": complete}

    def codes() -> set[str]:
        sheet = build_sheet(engine, board, capabilities=[SEEDANCE], stills_model="seedream5_pro")
        return {finding["code"] for finding in sheet["lint"]}

    assert "OVER_CAP" in codes()
    monkeypatch.setitem(prompt_lint.ALLOWANCES, "seedream5_pro", MAX_PROMPT)
    assert "OVER_CAP" not in codes()


# ------------------------------------------------------------------ 7. the writer's honest stop

BLOCKED = (
    '{"blocker": {"reason": "The verified claim set contains zero claims about the subject. '
    'All 35 claims concern the word Discovery.", "needs": "Verified claims for this exact '
    "topic: the 1998 observation by two teams that distant Type Ia supernovae were dimmer "
    'than expected."}}'
)


def test_a_sentences_first_capital_is_not_searched_as_a_name():
    """2026-10-14, d7d80450: «Discovery that the universe's expansion is accelerating…» made
    the studio search Wikipedia for «Discovery» and read the album, the channel and the
    shuttle. The first word of a sentence is a name only when it is also capitalised inside
    a sentence, is an acronym, or starts a run of names."""
    from app.research.agent import search_queries

    queries = search_queries(
        "The Supernova Surprise: How Distant Explosions Revealed Dark Energy",
        "Discovery that the universe’s expansion is accelerating thanks to observations of "
        "Type Ia supernovae",
    )
    assert "Discovery" not in queries and "Type Ia" in queries
    # Still names: inside a sentence, an acronym, a run of two at the start.
    assert "Nepal" in search_queries("Why Nepal Is Being Handed a Climate Bill", "Nepal owes.")
    assert "CERN" in search_queries("A tale of nothing", "CERN measures the lifetime.")
    assert "James Webb" in search_queries("A tale of nothing", "James Webb sees far.")


def test_a_writer_who_stops_honestly_is_not_a_format_fault():
    from app.factual.agent_pipeline import ScriptBlocked, _parse_script

    with pytest.raises(ScriptBlocked) as refused:
        _parse_script(BLOCKED)
    assert "Scenaristul s-a oprit" in str(refused.value)
    assert "zero claims about the subject" in str(refused.value)
    assert "Type Ia" in refused.value.blocker.needs


def test_a_blocked_topic_goes_back_to_research_and_is_read_for_again(engine, settings, monkeypatch):
    """The topic is PROPOSED again with the writer's reason noted to the Director, and the
    pages read before the note no longer count as its sources: `_gather_for_candidates`
    reads for it again; a topic with sources and no such note is left alone, as before."""
    from app.agents.identity import Blocker
    from app.agents.models import AgentMessage
    from app.factual.models import SourceSnapshot, TopicIdea
    from app.providers.registry import ProviderRegistry
    from app.runbook import stages
    from app.services import utc_now

    def topic_with_a_source(title: str, status: str) -> str:
        topic_id, source_id = str(uuid4()), str(uuid4())
        with Session(engine) as session, session.begin():
            session.add(
                TopicIdea(
                    id=topic_id,
                    title=title,
                    topic="t",
                    angle="a",
                    target_audience="g",
                    novelty_score=0.7,
                    status=status,
                    created_at=utc_now(),
                )
            )
            session.flush()
            session.add(
                SourceSnapshot(
                    id=source_id,
                    topic_id=topic_id,
                    url=f"https://en.wikipedia.org/wiki/{source_id[:8]}",
                    title="Discovery",
                    publisher="en.wikipedia.org",
                    content_hash="0" * 64,
                    raw_content="Discovery is the name of a space shuttle.",
                    sanitized_content="Discovery is the name of a space shuttle.",
                    fetched_at="2026-10-14T02:03:12+00:00",
                )
            )
        return topic_id

    blocked = topic_with_a_source("The Supernova Surprise", "SELECTED")
    settled = topic_with_a_source("A topic whose writer wrote", "PROPOSED")

    stages._topic_back_to_research(
        engine, blocked, Blocker(reason="claims about the word Discovery", needs="Type Ia")
    )
    with Session(engine) as session:
        assert session.get(TopicIdea, blocked).status == "PROPOSED"
        notes = [
            m
            for m in session.scalars(select(AgentMessage))
            if isinstance(m.body_json, dict) and m.body_json.get(stages.SCRIPT_BLOCKED_KEY)
        ]
        assert [n.body_json["topic_id"] for n in notes] == [blocked]
        assert notes[0].intent == "STATUS"

    asked: list[str] = []
    monkeypatch.setattr(
        stages,
        "gather_sources",
        lambda engine_, registry, settings_, topic_id, correlation, limit=4: (
            asked.append(topic_id) or {"fetched": [], "failed": []}
        ),
    )
    stages._gather_for_candidates(engine, ProviderRegistry(), settings)
    assert blocked in asked and settled not in asked


# ------------------------------------------------------------------ 8. the Owner's model stays


def _marcus_whose_model_fails(engine, monkeypatch, candidate_answers: bool):
    from app.agents.models import Agent
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session:
        marcus = session.scalar(select(Agent).where(Agent.display_name.like("Marcus%")))
        agent_id = marcus.id
    monkeypatch.setattr(agent_health, "_chosen_by_owner", lambda session, aid, mid: True)
    monkeypatch.setattr(
        agent_health,
        "diagnosis",
        lambda session, agent, now=None: {
            "current": {"model": "gpt-oss:120b"},
            "cause": "PROVIDER_ERROR",
            "failing_now": True,
        },
    )
    monkeypatch.setattr(
        agent_health,
        "candidates",
        lambda session, agent, settings, registry: [
            SimpleNamespace(id="m-mistral", model_name="mistral-large-4")
        ],
    )

    def probe(context, aid, mid, model_name, name):
        answered = candidate_answers and model_name != "gpt-oss:120b"
        return {
            "model": model_name,
            "status": "SUCCEEDED" if answered else "FAILED",
            "answered": answered,
            "reason": None if answered else "ProviderHTTPError: HTTP 400",
        }

    monkeypatch.setattr(agent_health, "_probe", probe)
    cards: list[str] = []
    monkeypatch.setattr(
        agent_health, "_ask_owner", lambda context, aid, why: cards.append(why) or "card"
    )
    assigned: list[tuple] = []
    monkeypatch.setattr(
        "app.integrations.services.assign_agent", lambda *a, **k: assigned.append((a, k))
    )
    return agent_id, cards, assigned


def test_a_model_the_owner_chose_is_never_switched_by_the_repair(engine, settings, monkeypatch):
    """2026-10-15, the Owner: «modelele de LLM, dacă au fost alese de mine, rămân; nu se
    schimbă singur». His model fails and another answers: she tells him on a card and
    changes nothing. Everything fails: an outage, no card, nothing changed."""
    agent_id, cards, assigned = _marcus_whose_model_fails(engine, monkeypatch, True)
    context = RepairContext(engine, settings, SimpleNamespace(), "corr")

    result = agent_health.switch_model(context, {"agent_id": agent_id})

    assert result["status"] == DECLINED and result["changed"]["owner_chosen"] is True
    assert assigned == [] and len(cards) == 1 and "nu se schimbă singur" in cards[0]
    assert "ales de Owner" in result["outcome_ro"]

    agent_id, cards, assigned = _marcus_whose_model_fails(engine, monkeypatch, False)
    result = agent_health.switch_model(context, {"agent_id": agent_id})
    assert result["status"] == DECLINED and result["changed"]["provider_down"] is True
    assert assigned == [] and cards == []


# ------------------------------------------------------------------ 9. the inbox in a work task


def test_a_work_task_carries_the_asks_of_the_inbox_bounded_and_the_inbox_tasks_carry_all(
    engine,
):
    """2026-10-15: the Director's every call carried her 152 open messages (105 status reports
    since 2026-10-03), 1.6 million characters, and her rewrite reviews came back empty. A work
    task carries the newest asks (handoff, request, challenge), at most OPEN_MESSAGES_IN_WORK,
    each whole with its thread; the inbox tasks and an unnamed task carry everything."""
    from app.agents.identity import INBOX_TASKS, OPEN_MESSAGES_IN_WORK, compose_identity
    from app.agents.messages import post_message
    from app.agents.models import Agent
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        sarah = session.scalar(select(Agent).where(Agent.display_name.like("Sarah%")))
        nadia = session.scalar(select(Agent).where(Agent.display_name.like("Nadia%")))
        for i in range(30):
            post_message(
                session,
                intent="STATUS",
                subject=f"Remediere foaie: RESOLVED {i}",
                body={"i": i},
                from_agent_id=nadia.id,
                to_agent_id=sarah.id,
                body_text=f"Report {i}.",
            )
        for i in range(25):
            post_message(
                session,
                intent="REQUEST_REVIEW" if i % 2 else "HANDOFF",
                subject=f"Ask {i}",
                body={},
                from_agent_id=nadia.id,
                to_agent_id=sarah.id,
                body_text=f"ASK TEXT {i} whole.",
            )
        sarah_id = sarah.id

    with Session(engine) as session:
        agent = session.get(Agent, sarah_id)
        work = compose_identity(session, agent, task_type="director_rewrite_review")
        assert len(work.context["open_message_ids"]) == OPEN_MESSAGES_IN_WORK
        assert "Remediere foaie" not in work.system
        assert "ASK TEXT 24 whole." in work.system and "ASK TEXT 4 whole." not in work.system
        for task in sorted(INBOX_TASKS):
            full = compose_identity(session, agent, task_type=task)
            assert len(full.context["open_message_ids"]) == 55, task
            assert "Remediere foaie: RESOLVED 0" in full.system
