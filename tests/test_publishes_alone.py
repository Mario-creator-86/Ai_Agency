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


# ------------------------------------------------------------------ 10. a motion fault by meaning


def test_a_clip_refused_for_a_move_other_than_the_plans_is_hers_and_her_yes_buys_nothing(
    tmp_path,
):
    """2026-10-15, the Owner: «mișcarea influențează cu ceva povestea ca să fie respinsă? nu-i de
    ajuns să zică quality control că e de la mișcare, că nu e același cadru; ea poate să
    hotărască că imaginea este ok». Clip QC refuses a clip for a zoom where the plan said static
    and for papers with writing in the background; her look says OVERTURNED, minor, the story
    intact: the clip is kept as hers (ACCEPTED_BY_LOOK) and no retry, no new still is bought."""
    from app.media import qc

    clip = tmp_path / "scene_01.mp4"
    clip.write_bytes(b"\x00" * 64)
    refusal = (
        "Scena 1: privit la 1080 px: apare text sau un logo; nu arată ce cere planul: camera "
        "zooms when the plan requires a static shot; papers show ruled lines in the background"
    )
    report = qc.ClipReport(
        scene=1,
        path=str(clip),
        checks=(
            qc.ClipCheck("motion", "PASSED", True, 0.4, "mișcare măsurată"),
            qc.ClipCheck("cuts", "PASSED", True, 0.0, "fără tăieturi"),
            qc.ClipCheck("picture", "FAILED", True, None, refusal),
        ),
        passed=False,
        blocks_ro=(refusal,),
        warnings_ro=(),
        unmeasured=(),
        measured={"picture": {"verdict": {"readable_text": True, "matches_plan": False}}},
        back_to_still=True,
    )
    bought: list[tuple] = []
    looked: list[qc.ClipReport] = []

    def look(seen):
        looked.append(seen)
        return {
            "verdict": "OVERTURNED",
            "severity": "minor",
            "redo": False,
            "reason_ro": "Zoom-ul ușor și liniile de pe hârtii nu schimbă ce spune scena.",
            "cause": "the prompt said static and blank papers; the model drifted",
            "layer": "motion",
        }

    outcome = qc.qc_clip_with_retry(
        clip,
        check=lambda path: report,
        buy=lambda seed, prompt: bought.append((seed, prompt)) or None,
        seed=7,
        motion_prompt="Static camera. Marcus writes.",
        camera_move="static",
        model_id="LTX-2.5",
        price_credits=24.0,
        committed_credits=0.0,
        cap_credits=100.0,
        look=look,
    )

    assert len(looked) == 1, "she is asked before anything is bought or sent back"
    assert outcome.status == qc.ACCEPTED_BY_LOOK and outcome.clip == clip
    assert bought == [] and outcome.retry_credits == 0.0
    assert "Directoarea a privit clipul refuzat" in outcome.reason_ro


# ------------------------------------------------------- 11. a scene sent back for its clip


def test_a_scene_sent_back_for_its_clip_is_restored_by_her_look_and_buys_nothing(
    engine, tmp_path, monkeypatch
):
    """Episode 2, scene 1 (2026-10-15): clip QC blamed the still, the still she had approved
    went back to the gate REJECTED, the clip REJECTED, and the next walk would buy a new still
    and a new clip. Before that, she looks at the clip: her yes restores both, hers, with the
    clip's note; her no leaves the scene as it was."""
    from app.media import fix_check
    from app.media.models import SceneTake
    from app.services import utc_now
    from test_film_costing import a_film

    board = a_film(engine, tmp_path, scenes=2)
    clip_file = tmp_path / "test_shot_01.mp4"
    clip_file.write_bytes(b"\x00" * 64)
    with Session(engine) as session, session.begin():
        still = session.scalar(
            select(SceneTake).where(
                SceneTake.storyboard_id == board,
                SceneTake.scene_number == 1,
                SceneTake.kind == "still",
            )
        )
        still.status = "REJECTED"
        still.failure_detail = (
            fix_check.SENT_BACK_FOR_CLIP_MARK + "; imaginea se întoarce la poartă."
        )
        session.add(
            SceneTake(
                id="clip-1",
                storyboard_id=board,
                scene_number=1,
                kind="test_shot",
                prompt_hash="h" * 64,
                model_id="LTX-2.5",
                resolution="1080p",
                seconds=5.0,
                seed=1,
                credits_quoted=24.0,
                status="REJECTED",
                failure_code="QC.CLIP",
                failure_detail=(
                    "Controlul clipului: Scena 1: apare text sau un logo; zoom în loc de static"
                ),
                path=str(clip_file),
                sha256="s" * 64,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        still_id = still.id

    asked: list[dict] = []
    answer = {"verdict": "CONFIRMED", "severity": "serious", "redo": True, "reason_ro": "nu"}

    def look(engine_, registry, **kwargs):
        asked.append(kwargs)
        return dict(answer)

    monkeypatch.setattr(fix_check, "shot_second_look", look)

    assert (
        fix_check.restore_sent_back_scenes(
            engine, object(), storyboard_id=board, correlation_id="c"
        )
        == []
    )
    assert [a["scene_index"] for a in asked] == [1] and asked[0]["take_ids"] == ["clip-1"]
    with Session(engine) as session:
        assert session.get(SceneTake, still_id).status == "REJECTED"
        assert session.get(SceneTake, "clip-1").status == "REJECTED"

    answer.update(verdict="OVERTURNED", severity="minor", redo=False, reason_ro="e bine așa")
    assert fix_check.restore_sent_back_scenes(
        engine, object(), storyboard_id=board, correlation_id="c"
    ) == [1]
    with Session(engine) as session:
        restored_still = session.get(SceneTake, still_id)
        restored_clip = session.get(SceneTake, "clip-1")
        assert (restored_still.status, restored_still.approved_by) == (
            "APPROVED",
            fix_check.DIRECTOR_LOOK_APPROVER,
        )
        assert (restored_clip.status, restored_clip.approved_by) == (
            "PAID",
            fix_check.DIRECTOR_LOOK_APPROVER,
        )
        assert restored_clip.failure_code is None
        note = fix_check.take_note(session, "clip-1")
        assert note and note["approved_by"] == fix_check.DIRECTOR_LOOK_APPROVER
        # What the hero gate reads: the clip's latest record, PASSED as hers.
        from app.media.assembler import clip_qc_of

        record = clip_qc_of(session, "clip-1")
        assert record and record["verdict"] == "PASSED" and record["passed"] is True
        assert record["accepted_by"] == fix_check.DIRECTOR_LOOK_APPROVER
        assert record["director_look"]["reason_ro"] == "e bine așa"
    # A clip she kept whose record was never rewritten (the first restore of 07:12Z) is
    # settled on the next walk: the record says PASSED, as her note says.
    with Session(engine) as session, session.begin():
        from app.media.assembler import CLIP_QC_EVENT
        from app.services import append_event

        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            "clip-1",
            1,
            {
                "storyboard_id": board,
                "scene_number": 1,
                "take_id": "clip-1",
                "attempt": 3,
                "verdict": "FAILED",
                "passed": False,
                "blocks_ro": ["x"],
            },
            "c",
        )
    assert fix_check.settle_clips_she_kept(engine, storyboard_id=board, correlation_id="c") == [
        "clip-1"
    ]
    with Session(engine) as session:
        settled = clip_qc_of(session, "clip-1")
        assert settled["verdict"] == "PASSED" and settled["attempt"] == 4
        assert settled["director_look"]["reason_ro"] == "e bine așa"
    assert fix_check.settle_clips_she_kept(engine, storyboard_id=board, correlation_id="c") == []
    # Nothing left to offer: the scene is restored, the next walk prices nothing for it.
    assert (
        fix_check.restore_sent_back_scenes(
            engine, object(), storyboard_id=board, correlation_id="c"
        )
        == []
    )
    assert len(asked) == 2


# ------------------------------------------------------ 12. no regeneration without her review


def test_every_production_purchase_of_a_refused_clip_passes_through_her_look():
    """2026-10-15, the Owner: «întotdeauna, înainte de a se regenera orice, promptul trebuie
    verificat, revizuit și aprobat» — any scene, any attempt. The clip helper keeps a
    mechanical retry only for the standalone case (no look callback); every production caller
    hands it her look, so a refusal goes to her brief, the Editor's rewrite and her review
    before a replacement is bought (test_fix_is_verified: the director looks before a still,
    a RunPod round and a clip retry are bought; test_stills_stage: no paid re-rolls)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    callers: list[tuple[str, bool]] = []
    helper_users: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        at = 0
        while True:
            at = text.find("qc_clip_with_retry(", at)
            if at < 0:
                break
            if text[max(0, at - 4) : at] != "def ":
                depth, close = 0, at + len("qc_clip_with_retry(") - 1
                for here in range(close, len(text)):
                    depth += {"(": 1, ")": -1}.get(text[here], 0)
                    if depth == 0:
                        close = here
                        break
                callers.append((path.name, "look=" in text[at : close + 1]))
            at += 1
        if "retry_motion_prompt(" in text and "def retry_motion_prompt" not in text:
            helper_users.append(path.name)
    assert callers, "the motion step calls the clip helper"
    assert all(has_look for _name, has_look in callers), callers
    # The mechanical retry's words are composed in one place only, inside the helper.
    assert helper_users == [], helper_users


# ------------------------------------------------------ 13. a run orphaned by a restart


def test_a_run_that_started_before_this_process_does_not_block_its_agent(engine, monkeypatch):
    """2026-10-15 07:16Z: the Director's run outlived a hard stop; for 45 minutes every call
    of hers was refused «already has an active task». A RUNNING row older than this process
    is closed as ABANDONED with the reason, and she is free at once; a run of this process is
    still hers while it is young."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from app.agents import services as agent_services
    from app.agents.models import Agent, AgentRun
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        sarah = session.scalar(select(Agent).where(Agent.display_name.like("Sarah%")))
        sarah_id = sarah.id
        before = (datetime.now(UTC) - timedelta(minutes=12)).isoformat()
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=sarah_id,
                task_type="prompt_lesson_reading",
                objective="o",
                prompt_template_version="v",
                model_name="m",
                provider_name="p",
                correlation_id="c",
                status="RUNNING",
                started_at=before,
            )
        )
    monkeypatch.setattr(agent_services, "PROCESS_STARTED_AT", datetime.now(UTC).isoformat())
    with Session(engine) as session, session.begin():
        assert agent_services._has_live_run(session, sarah_id) is False
        (run,) = session.scalars(select(AgentRun).where(AgentRun.agent_id == sarah_id)).all()
        assert run.status == "ABANDONED" and "procesul s-a oprit" in run.error_detail

    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=sarah_id,
                task_type="director_second_look",
                objective="o",
                prompt_template_version="v",
                model_name="m",
                provider_name="p",
                correlation_id="c",
                status="RUNNING",
                started_at=datetime.now(UTC).isoformat(),
            )
        )
    with Session(engine) as session:
        assert agent_services._has_live_run(session, sarah_id) is True
