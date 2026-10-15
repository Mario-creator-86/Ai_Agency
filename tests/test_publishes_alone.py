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

    # A sibling candidate of the same round, refused by the gate with the same timestamp,
    # is not «a newer still»: the scene is still offered (07:59Z, scenes 2 and 5 were skipped).
    with Session(engine) as session, session.begin():
        twin = session.get(SceneTake, still_id)
        session.add(
            SceneTake(
                id="still-twin",
                storyboard_id=board,
                scene_number=1,
                kind="still",
                prompt_hash=twin.prompt_hash,
                model_id=twin.model_id,
                resolution=twin.resolution,
                seconds=twin.seconds,
                seed=twin.seed,
                credits_quoted=twin.credits_quoted,
                status="REJECTED",
                failure_code="LOCAL.STILL_GATE",
                failure_detail="Nu arată ce cere scena.",
                path=twin.path,
                sha256="t" * 64,
                approved_by="still_gate",
                created_at=twin.created_at,
                updated_at=twin.updated_at,
            )
        )

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


# ------------------------------------------------------ 14. the budget counts media, not tokens


def test_the_daily_budget_counts_media_and_reports_the_subscriptions_tokens_apart(engine):
    """2026-10-15: 14,22 USD of priced tokens (the Director's 580k-token calls) were counted
    as the day's spend against the 20 USD budget, and a 3,90 USD stills step was refused
    OVER_DAILY_BUDGET with a letter to the Owner. His rule: the subscription costs nothing;
    images and motion do. The period's spent is the vendors' costs; the tokens are reported
    beside it."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.agents.models import Agent, AgentRun
    from app.agents.services import seed_initial_workforce
    from app.economy.budget import spend_since
    from app.economy.models import ProviderCostRecord

    seed_initial_workforce(engine)
    now = datetime.now(UTC).isoformat()
    with Session(engine) as session, session.begin():
        sarah = session.scalar(select(Agent).where(Agent.display_name.like("Sarah%")))
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=sarah.id,
                task_type="director_review",
                objective="o",
                prompt_template_version="v",
                model_name="deepseek-v4.1-flash",
                provider_name="settings:cloud",
                correlation_id="c",
                status="SUCCEEDED",
                cost_vr=0.49,
                prompt_tokens=583898,
                completion_tokens=2000,
                started_at=now,
                finished_at=now,
            )
        )
        session.add(
            ProviderCostRecord(
                id=str(uuid4()),
                provider="runpod",
                external_reference="foaie:x:stills",
                status="ESTIMATED",
                amount_micros=1_470_000,
                currency="USD",
                usd_micros=1_470_000,
                recorded_at=now,
            )
        )
    with Session(engine) as session:
        spend = spend_since(session, "2026-10-14T21:00:00+00:00")
    assert spend["spent_usd_micros"] == 1_470_000
    assert spend["agent_usd_micros"] > 0 and spend["agent_runs"] == 1


# ------------------------------------------------------ 15. a structured first attempt


def test_a_structured_first_attempt_bounds_the_thinking_except_for_a_narrating_model(
    engine, monkeypatch
):
    """deepseek-v4.1-flash, asked nothing about thinking, reasoned to its 393k-token limit on
    the Director's rewrite review twice (05:45Z, 08:04Z) and answered nothing — twelve minutes
    each. The first attempt asks for JSON with thinking off; glm-5.3-flash, which narrates when
    told not to think, is asked nothing; the second attempt thinks natively for everyone."""
    from app.agents import structured
    from app.agents.models import Agent
    from app.agents.services import seed_initial_workforce
    from pydantic import BaseModel

    assert structured.first_attempt_extra("deepseek-v4.1-flash") == {
        "format": "json",
        "think": False,
    }
    assert structured.first_attempt_extra("glm-5.3-flash") == {"format": "json"}
    assert structured.first_attempt_extra(None) == {"format": "json", "think": False}

    class Answer(BaseModel):
        ok: bool

    seed_initial_workforce(engine)
    with Session(engine) as session:
        sarah = session.scalar(select(Agent).where(Agent.display_name.like("Sarah%")))
        sarah_id = sarah.id
    monkeypatch.setattr(structured, "_model_name", lambda engine_, aid, mid: "deepseek-v4.1-flash")
    calls: list[dict] = []

    def fake_run(engine_, registry, agent_id, task_type, prompt, version, correlation, **kw):
        calls.append(dict(kw.get("extra") or {}))
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": "not an object" if len(calls) == 1 else '{"ok": true}',
            "model_name": "deepseek-v4.1-flash",
        }

    monkeypatch.setattr(structured, "run_agent_task", fake_run)
    parsed, first, second = structured.structured_run(
        engine,
        None,
        sarah_id,
        "director_rewrite_review",
        "P",
        "v1",
        "c",
        Answer,
        "",
        max_tokens=100,
    )
    assert parsed is not None and parsed.ok is True
    assert calls == [{"format": "json", "think": False}, {"think": True}]


# ------------------------------------------------------ 16. her audit before the first purchase


def test_the_director_audits_a_scenes_words_before_the_first_purchase(
    engine, tmp_path, monkeypatch
):
    """The Owner, 2026-10-15: «Mereu verificăm prompturile, fără excepție!» Before the stills
    step buys scene 1 and scene 2, she audits their words: scene 1 approved (kept on those
    exact words, not asked again); scene 2 not — her brief goes to the Editor's rewrite, and
    the scene is reported rewritten, so the sheet is rebuilt and audited again; after
    AUDIT_ROUNDS briefs without approval the scene waits for her and is never bought."""
    from app.media import prompt_audit
    from app.media.models import StoryboardScene
    from test_film_costing import a_film

    board = a_film(engine, tmp_path, scenes=2)
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ):
            row.prompt_json = {
                **dict(row.prompt_json or {}),
                "subject": f"the desk of scene {row.scene_index}",
                "action": "a hand rests on the desk",
            }
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)  # her audit needs a Director; without one nothing is bought
    asked: list[dict] = []
    rewrites: list[dict] = []

    def fake_structured_run(engine_, registry, agent_id, task_type, prompt, *a, **kw):
        asked.append({"task": task_type, "prompt": prompt})
        answer = prompt_audit.PromptAudit(
            scenes=[
                prompt_audit.AuditedScene(scene_index=1, approved=True, reason="says everything"),
                prompt_audit.AuditedScene(
                    scene_index=2,
                    approved=False,
                    reason="the papers are not said blank",
                    brief=prompt_audit.AuditBrief(
                        diagnosis="the words leave the papers to the model",
                        layer="still",
                        avoid=["ruled paper"],
                        keep=["the desk"],
                        change=["say the papers are blank and unmarked"],
                        summary_ro="Hârtiile trebuie spuse goale.",
                    ),
                ),
            ]
        )
        return answer, {"id": "run-1", "status": "SUCCEEDED"}, None

    monkeypatch.setattr("app.agents.structured.structured_run", fake_structured_run)

    def fake_rewrite(engine_, registry, context, brief, correlation_id):
        rewrites.append({"scene": context["scene_index"], "brief": brief})
        return {"rewritten": True, "layer": brief["layer"]}

    monkeypatch.setattr("app.media.scene_rewrite.rewrite_scene", fake_rewrite)

    first = prompt_audit.audit_before_purchase(
        engine, object(), storyboard_id=board, step="stills", scenes=[1, 2], correlation_id="c"
    )
    assert first["approved"] == [1] and first["rewritten"] == [2] and first["held"] == [], first
    # Her refusal teaches: the brief's diagnosis and change are a provisional lesson the
    # Editor reads on his next prompts (the Owner, 19:05Z: «Kael trebuie să învețe»).
    from app.media.prompt_agent import prompt_lessons

    with Session(engine) as session:
        taught = " ".join(prompt_lessons(session, scope="factual"))
    assert "say the papers are blank and unmarked" in taught, taught
    assert asked[0]["task"] == prompt_audit.AUDIT_TASK and "PAY" in asked[0]["prompt"]
    assert rewrites[0]["scene"] == 2 and rewrites[0]["brief"]["avoid"] == ["ruled paper"]

    # The same words of scene 1 are not asked about again; scene 2's unchanged words (the
    # fake rewrite stored nothing) get her second brief, then she holds the scene.
    second = prompt_audit.audit_before_purchase(
        engine, object(), storyboard_id=board, step="stills", scenes=[1, 2], correlation_id="c"
    )
    assert second["approved"] == [1] and second["rewritten"] == [2], second
    assert (
        "the desk of scene 1" in asked[0]["prompt"] and "the desk of scene 2" in asked[0]["prompt"]
    )
    assert (
        "the desk of scene 1" not in asked[1]["prompt"]
        and "the desk of scene 2" in asked[1]["prompt"]
    )
    third = prompt_audit.audit_before_purchase(
        engine, object(), storyboard_id=board, step="stills", scenes=[1, 2], correlation_id="c"
    )
    # No cap on her rounds (the Owner, 18:15Z) — and the same finding a third time running,
    # while his rewrites land, is a tool defect for the developer (20:14Z): scene 2 is held,
    # nothing is bought on words she refused, and she is not asked a fourth time.
    assert third["approved"] == [1] and third["rewritten"] == [], third
    (held_two,) = third["held"]
    assert held_two["scene_index"] == 2 and held_two.get("developer_defect") is True
    assert "under_cap" not in third and third["asked"] is True
    assert "Judge ONLY words_to_send" in prompt_audit._INSTRUCTIONS
    assert prompt_audit._plan_without_props(
        {
            "characters": [{"name": "Sarah", "props": "gold nameplate"}],
            "in_frame": [{"name": "Nadia", "props": "a cork wall of index cards"}],
            "part": "hook",
        }
    ) == {"characters": [{"name": "Sarah"}], "in_frame": [{"name": "Nadia"}], "part": "hook"}
    # The motion audit is told the picture is settled (15:41Z: she refused the clip's words
    # for the still's own objects, which no motion rewrite could touch).
    assert "already bought and approved" in prompt_audit._MOTION_NOTE

    # A brief whose rewrite could not land (findings locked on the other layer) does not
    # hold the scene for the Owner: the words are bought under the cap. Scene 1's words
    # change, so she is asked again and this time refuses them.
    def refusing_run(engine_, registry, agent_id, task_type, prompt, *a, **kw):
        asked.append({"task": task_type, "prompt": prompt})
        answer = prompt_audit.PromptAudit(
            scenes=[
                prompt_audit.AuditedScene(
                    scene_index=1,
                    approved=False,
                    reason="the cork wall carries index cards",
                    brief=prompt_audit.AuditBrief(
                        diagnosis="the still's objects",
                        layer="still",
                        avoid=["index cards"],
                        keep=["the desk"],
                        change=["say the wall is bare"],
                        summary_ro="Peretele trebuie spus gol.",
                    ),
                ),
            ]
        )
        return answer, {"id": "run-4", "status": "SUCCEEDED"}, None

    monkeypatch.setattr("app.agents.structured.structured_run", refusing_run)
    monkeypatch.setattr(
        "app.media.scene_rewrite.rewrite_scene",
        lambda *a, **k: {"rewritten": False, "reason": "constatările sunt pe stratul still"},
    )
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ):
            row.prompt_json = {
                **dict(row.prompt_json or {}),
                "still_prompt": "A fresh desk by a cork wall; a hand lifts a cup.",
            }
    before = len(asked)
    fourth = prompt_audit.audit_before_purchase(
        engine, object(), storyboard_id=board, step="stills", scenes=[1], correlation_id="c"
    )
    # Her rounds in the same walk, each with her earlier brief and why the rewrite could not
    # answer it (16:10Z: clips bought on refused words after one miss), up to the walk's
    # bound; then the scene waits for her next walk — approved by nobody, bought by nobody.
    assert fourth["approved"] == [] and "under_cap" not in fourth and fourth["asked"] is True
    # The same finding three rounds running while no rewrite can answer it: a tool defect
    # for the developer (the Owner, 20:14Z), not a seventh round and not a purchase.
    assert len(asked) - before == prompt_audit.SAME_FINDING_ROUNDS
    assert "previous_round" in asked[-1]["prompt"] and "stratul still" in asked[-1]["prompt"]
    assert "say the wall is bare" in asked[-1]["prompt"]
    (held,) = fourth["held"]
    assert held["scene_index"] == 1 and held.get("developer_defect") is True, held
    assert "defect de unealtă" in held["reason"]
    with Session(engine) as session:
        assert (
            prompt_audit.briefs_given(session, board, 1, "still")
            == prompt_audit.SAME_FINDING_ROUNDS - 1
        )
    with Session(engine) as session:
        scene_rows = session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ).all()
        assert len(scene_rows) == 2
        assert prompt_audit.briefs_given(session, board, 2, "still") == 2  # then the defect


def test_the_same_refusal_three_rounds_running_is_a_tool_defect_for_the_developer(
    engine, tmp_path, monkeypatch
):
    """The Owner, 2026-10-15 20:14Z: «trebuie să avem un proces automat care intervine în
    astfel de situații». Scene 2 of 7c26a7ce was refused eight rounds for a sentence the
    composer kept putting back: after three refusals with the same finding while the Editor's
    rewrites kept landing, the scene is a TOOL_DEFECT — a developer note, no more rounds,
    nothing bought, and not asked about again while the words stand."""
    from app.agents.director import DEVELOPER_DEFECT_KIND
    from app.agents.models import AgentMessage
    from app.agents.services import seed_initial_workforce
    from app.media import prompt_audit
    from app.media.models import StoryboardScene
    from test_film_costing import a_film

    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ):
            row.prompt_json = {
                **dict(row.prompt_json or {}),
                "subject": "the scientist's hands on the bar",
                "action": "her hands lift the bar",
                "still_prompt": "Hands on the bar, take 0. Any people appear only as small "
                "distant figures seen from behind.",
            }
    seed_initial_workforce(engine)
    asked: list[str] = []
    finding = (
        "The words carry the wide-frame people clause 'small distant figures seen from behind' "
        "inside a detail shot of hands; take it out and state the face rule at the shot's scale"
    )

    def refusing(engine_, registry, agent_id, task_type, prompt, *a, **kw):
        asked.append(prompt)
        answer = prompt_audit.PromptAudit(
            scenes=[
                prompt_audit.AuditedScene(
                    scene_index=1,
                    approved=False,
                    reason=finding,
                    brief=prompt_audit.AuditBrief(
                        diagnosis=finding,
                        layer="still",
                        avoid=["small distant figures"],
                        keep=["the hands"],
                        change=["state the face rule at the shot's scale"],
                        summary_ro="Scoate clauza de cadru larg.",
                    ),
                )
            ]
        )
        return answer, {"id": "run-x", "status": "SUCCEEDED"}, None

    rewrites: list[int] = []

    def landing_rewrite(engine_, registry, context, brief, correlation_id):
        # His rewrite lands and changes the words — the composer puts the clause back.
        rewrites.append(1)
        with Session(engine) as session, session.begin():
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
            ):
                row.prompt_json = {
                    **dict(row.prompt_json or {}),
                    "still_prompt": f"Hands on the bar, take {len(rewrites)}. Any people appear "
                    "only as small distant figures seen from behind.",
                }
        return {"rewritten": True, "layer": "still"}

    monkeypatch.setattr("app.agents.structured.structured_run", refusing)
    monkeypatch.setattr("app.media.scene_rewrite.rewrite_scene", landing_rewrite)
    outcomes = []
    for _ in range(4):
        outcomes.append(
            prompt_audit.audit_before_purchase(
                engine, object(), storyboard_id=board, step="stills", scenes=[1], correlation_id="c"
            )
        )
    # Round 1 and 2: rewritten; round 3: the same finding a third time — a tool defect.
    assert outcomes[0]["rewritten"] == [1] and outcomes[1]["rewritten"] == [1], outcomes
    (held,) = outcomes[2]["held"]
    assert held["scene_index"] == 1 and held.get("developer_defect") is True
    assert "defect de unealtă" in held["reason"] and outcomes[2]["approved"] == []
    # Round 4: the words stand, nobody is asked, the scene still waits for the developer.
    assert outcomes[3]["asked"] is False and outcomes[3]["held"][0].get("developer_defect")
    assert len(asked) == 3 and len(rewrites) == 2
    with Session(engine) as session:
        notes = [
            m
            for m in session.scalars(select(AgentMessage))
            if isinstance(m.body_json, dict) and m.body_json.get("kind") == DEVELOPER_DEFECT_KIND
        ]
        assert len(notes) == 1 and notes[0].status == "RESOLVED"
        assert "small distant figures" in str(notes[0].body_text)


def test_a_new_finding_after_two_of_the_same_is_not_a_tool_defect(engine, tmp_path, monkeypatch):
    """20:35Z, 7c26a7ce scene 2: the first guard read «the action is written twice» as the
    same finding as «the action stops at raise it a little» — the long reasons share action,
    pointing, laser, bar — and held a scene whose rounds were converging. The guard compares
    her briefs' own words; a new finding starts the count again."""
    from app.agents.services import seed_initial_workforce
    from app.media import prompt_audit
    from app.media.models import StoryboardScene
    from test_film_costing import a_film

    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ):
            row.prompt_json = {
                **dict(row.prompt_json or {}),
                "subject": "the scientist's hands on the bar",
                "action": "her hands lift the bar",
                "still_prompt": "Hands lift the bar, take 0, along the laser line on the floor.",
            }
    seed_initial_workforce(engine)
    briefs = [
        (
            "the action stops at 'raise it a little' and drops the pointing along the laser line",
            ["write the pointing as the first clause of the action"],
        ),
        (
            "the action stops at 'raise it a little' and drops the pointing along the laser line",
            ["write the pointing as the first clause of the action"],
        ),
        (
            "the bar-lifting clause is written twice, in the subject and in the action; two "
            "movements invite the model to render both",
            ["say each movement once"],
        ),
    ]
    calls = {"n": 0}

    def refusing(engine_, registry, agent_id, task_type, prompt, *a, **kw):
        diagnosis, change = briefs[min(calls["n"], len(briefs) - 1)]
        calls["n"] += 1
        answer = prompt_audit.PromptAudit(
            scenes=[
                prompt_audit.AuditedScene(
                    scene_index=1,
                    approved=False,
                    reason=f"The words_to_send: {diagnosis}; the laser line, the bar and the "
                    "pointing along the floor are the beat the narration rides on.",
                    brief=prompt_audit.AuditBrief(
                        diagnosis=diagnosis,
                        layer="still",
                        avoid=[],
                        keep=["the hands"],
                        change=change,
                        summary_ro="Rescrie.",
                    ),
                )
            ]
        )
        return answer, {"id": "run-y", "status": "SUCCEEDED"}, None

    def landing_rewrite(engine_, registry, context, brief, correlation_id):
        with Session(engine) as session, session.begin():
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
            ):
                row.prompt_json = {
                    **dict(row.prompt_json or {}),
                    "still_prompt": f"Hands on the bar, take {calls['n']}, the laser line.",
                }
        return {"rewritten": True, "layer": "still"}

    monkeypatch.setattr("app.agents.structured.structured_run", refusing)
    monkeypatch.setattr("app.media.scene_rewrite.rewrite_scene", landing_rewrite)
    outcomes = [
        prompt_audit.audit_before_purchase(
            engine, object(), storyboard_id=board, step="stills", scenes=[1], correlation_id="c"
        )
        for _ in range(3)
    ]
    # Two of the same, then a new finding: three rewrites, no defect, the rounds go on.
    assert [o["rewritten"] for o in outcomes] == [[1], [1], [1]], outcomes
    assert all(o["held"] == [] for o in outcomes)


def test_the_walk_audits_before_it_pays_and_her_hold_is_not_the_owners():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "backend" / "app" / "runbook" / "stages.py"
    text = root.read_text(encoding="utf-8")
    audit_at = text.index("audit_before_purchase(\n")
    buy_at = text.index("result = run_sheet_step(\n")
    assert audit_at < buy_at, "her audit comes before the money"
    assert 'if status == "NEEDS_PROMPT_APPROVAL":\n        # Her audit' in text


# ------------------------------------------------------ 17. the first prompt right from the start


def test_the_serial_still_always_says_its_surfaces_are_blank_and_the_editor_is_told_why():
    """The Owner, 2026-10-15: «Cine face prompturile trebuie să le facă corect de la început!»
    Episode 2's scenes 2, 5 and 6 paid for monitors with content, ruled paper and a nameplate
    inviting a name: the first prompt named none of it blank. The serial composer now says the
    surfaces are blank in every still, not only when a page is named, and the Video Editor's
    instructions name the objects that carry writing in real life and ask him to leave them out."""
    from app.media import prompt_agent
    from app.media.prompt_agent import SERIAL_BLANK_SENTENCE, compose_serial_prompt

    look = {"block": "Hand-drawn studio house.", "shot_sizes": {}, "max_prompt_chars": 20000}
    package = {
        "location": "the penthouse office",
        "shot_size": "single",
        "in_frame": [{"name": "Sarah", "face_hair": "dark bob", "outfit": "navy blazer"}],
        "action": "Sarah leans back, arms crossed, facing the viewer.",
    }
    still = compose_serial_prompt(package, look)
    assert SERIAL_BLANK_SENTENCE in still, still
    # 11:22Z the same day: «every screen is dark or a plain soft glow» was the sentence the
    # Director locked scenes 5 and 7 on — a screen named is a screen drawn. No screen is named;
    # the room's own sentence says where a monitor exists and that it is dark.
    assert "screen" not in SERIAL_BLANK_SENTENCE and "blank" in SERIAL_BLANK_SENTENCE
    told = prompt_agent._SERIAL_SHOTS_INSTRUCTIONS
    assert "nameplate" in told and "leave such objects out" in told
    # The Owner, 2026-10-15 14:15Z: the first prompt complete the first time — the room by
    # its own objects, the pose first, a chain of moments for the clip, the feeling in the
    # body, the camera as a storytelling choice, never a timid zoom on a face.
    for phrase in (
        "ONLY by its own objects",
        "ONE short clause",
        "chain of two or three moments",
        "comedy, suspense, fear",
        "never the same move twice in a row",
        "never a timid zoom on a face",
        "the still is drawn from the first moment, the clip plays the chain",
    ):
        assert phrase in told, phrase


# ------------------------------------------------------ 18. the room is the beat's, not the block's


def test_a_serial_shot_is_drawn_in_the_room_the_beat_names_and_the_block_puts_no_screen_in_it():
    """Episode 2 (2d276038, 2026-10-15): the look's block said «wooden desks with glowing
    monitors … Screens show abstract glow» at the head of every shot, Sarah's penthouse was
    drawn as the render bay with lit monitors, and the Director refused every rewrite on the
    block's own words — six scenes held, nothing bought, no film. The block is the rendering,
    the camera and the frame; the room's furniture comes from the look's rooms table, matched
    on the beat's location, the house's own sentence for a room the table does not name."""
    from app.media.prompt_agent import compose_serial_prompt
    from app.media.series_look import load_series_look, room_sentence

    look = load_series_look()
    assert look["in_use"] and look["version"] == 3
    block = look["block"].lower()
    assert "monitor" not in block and "screen" not in block and "glow" not in block
    assert room_sentence(look, "Executive Penthouse (Director / CEO), floor 4").startswith(
        "The Executive Penthouse"
    )
    # Named by its own objects only: a negation («no screen») is read as a screen by an image
    # model (the Director's brief on scene 6, 2026-10-15).
    penthouse = room_sentence(look, "Executive Penthouse, floor 4").lower()
    assert "mahogany desk" in penthouse and "monitor" not in penthouse and "screen" not in penthouse
    assert room_sentence(look, "Content, floor 2") == look["rooms"]["house"]
    assert room_sentence(look, "") == look["rooms"]["house"]
    assert room_sentence({"rooms": {}}, "Research, floor 3") == ""

    sarah = {
        "id": "s",
        "name": "Sarah Executive",
        "face_hair": "brunette professional bob with warm highlights",
        "outfit": "navy two-piece executive blazer, white collared shirt and sky-blue tie",
    }
    package = {
        "location": "Executive Penthouse (Director / CEO), floor 4",
        "shot_size": "single",
        "in_frame": [sarah],
        "characters": [sarah],
        "action": "Sarah sits very upright, shoulders square, facing the viewer.",
        "background": "the mahogany desk edge low behind her and the big window onto the city",
    }
    prompt = compose_serial_prompt(package, look)
    assert prompt.startswith(look["block"])
    assert "Location: Executive Penthouse (Director / CEO), floor 4." in prompt
    at_room = prompt.index("The Executive Penthouse at the top of the studio house")
    assert prompt.index("Location:") < at_room < prompt.index("Medium close-up single")
    assert "glowing monitors" not in prompt and "abstract glow" not in prompt
    # Kael's beat in the render bay is drawn in the render bay, its monitors dark.
    kael = {"id": "k", "name": "Kael Video Editor", "face_hair": "sandy hair", "outfit": "shirt"}
    bay = compose_serial_prompt(
        {
            **package,
            "location": "Video & Render Bay, floor 1",
            "in_frame": [kael],
            "characters": [kael],
            "background": "",
        },
        look,
    )
    assert "The render bay of the studio house" in bay and "switched off and dark" in bay
    assert "Executive Penthouse" not in bay


def test_the_rooms_sentence_is_the_composers_own_so_a_lock_on_it_is_the_developers():
    """The Director's review quotes words a rewrite cannot change (`lock_texts` constants):
    the room's sentence is the composer's, like the block and the frame, so a finding it
    invites is a tool's defect for the developer, never a brief the Editor fails twice."""
    from app.media.scene_rewrite import _still_sentences
    from app.media.series_look import load_series_look, room_sentence

    look = load_series_look()
    location = "Executive Penthouse (Director / CEO), floor 4"
    room = room_sentence(look, location)
    still = f"{look['block']} Location: {location}. {room} Medium close-up single at eye level."
    package = {"location": location, "shot_size": "single", "in_frame": []}
    context = {"serial": True, "look": look, "package": package}
    fixed, _chosen = _still_sentences(context, package, still)
    assert room in fixed and look["block"] in fixed


# ------------------------------------------------------ 19. the writers punctuate, as speech


def test_a_line_or_a_narration_without_its_full_stop_gets_one_and_the_writers_are_told():
    """The Owner, 2026-10-15 14:03Z: «Marcus, scenaristul trebuie să folosească semne de
    punctuație.» Both briefs say it; and what he writes is punctuated as speech when it is
    read: a line or a narration that ends on a letter or a digit gets its full stop, one that
    ends on a question mark, an ellipsis or a closing quote is left as it is, a trailing comma
    or dash is replaced by the full stop."""
    from app.factual import agent_pipeline
    from app.story import services as story
    from app.wording import punctuated

    assert punctuated("The editor rewrites scene two") == "The editor rewrites scene two."
    assert punctuated("Thirteen rewrite demands") == "Thirteen rewrite demands."
    assert punctuated("Zero rejected. The close is within limit") == (
        "Zero rejected. The close is within limit."
    )
    assert punctuated("Is it within limit?") == "Is it within limit?"
    assert punctuated("Then nothing…") == "Then nothing…"
    assert punctuated("She said «no»") == "She said «no»"
    assert punctuated("Four pages, four sources,") == "Four pages, four sources."
    assert punctuated("the number is 24") == "the number is 24."
    assert punctuated("  ") == ""

    line = story._Line.model_validate({"speaker": "Marcus", "text": "Thirteen rewrite demands"})
    assert line.text == "Thirteen rewrite demands."
    scene = agent_pipeline._Scene.model_validate(
        {"narration": "Four pages, four sources, twenty-four claims verified", "claim_ids": ["c1"]}
    )
    assert scene.narration.endswith("verified.")
    assert "Punctuate every line as speech" in story._INSTRUCTIONS
    assert "on EVERY line, because the voice plays it" in story._INSTRUCTIONS
    assert "not a report read aloud" in story._INSTRUCTIONS
    assert "scris pentru o voce vie" in agent_pipeline._WRITE_INSTRUCTIONS
    assert "semne de punctuație" in agent_pipeline._WRITE_INSTRUCTIONS


# ------------------------------------------------------ 20. research reads the topic itself


def test_a_found_page_with_no_word_of_the_topic_is_not_read_and_a_title_asks_its_last_words():
    """2026-10-15, d7d80450: the suggestion search for «Type Ia» found Type Ia supernova — and
    Type Iax supernova, Type Ia sensory fiber and Type O Negative, read and verified into
    claims about a metal band; the day before, «Discovery» found the channel and the album.
    A page whose title shares no word of substance with the topic is left aside; a
    title-case title asks its last two words too («Dark Energy»)."""
    from app.research.agent import relevant_pages, search_queries

    title = "The Supernova Surprise: How Distant Explosions Revealed Dark Energy"
    topic = "Discovery that the universe's expansion is accelerating thanks to Type Ia supernovae"
    thesis = "In 1998 two teams found distant Type Ia supernovae dimmer than expected."
    found = [
        {"url": "https://en.wikipedia.org/wiki/Type_Ia_supernova", "title": "Type Ia supernova"},
        {"url": "https://en.wikipedia.org/wiki/Type_Iax_supernova", "title": "Type Iax supernova"},
        {
            "url": "https://en.wikipedia.org/wiki/Type_Ia_sensory_fiber",
            "title": "Type Ia sensory fiber",
        },
        {"url": "https://ro.wikipedia.org/wiki/Type_O_Negative", "title": "Type O Negative"},
        {"url": "https://science.nasa.gov/dark-energy", "title": "Dark energy - NASA Science"},
    ]
    kept = [page["title"] for page in relevant_pages(found, title, topic, thesis)]
    assert kept == ["Type Ia supernova", "Type Iax supernova", "Dark energy - NASA Science"]
    assert relevant_pages(found, "", "", "") == found  # nothing to compare: every page stays
    queries = search_queries(title, topic)
    assert "Dark Energy" in queries and "Type Ia" in queries and "Discovery" not in queries


def test_a_fetched_page_that_is_not_about_the_subject_is_not_stored():
    """2026-10-15 18:11Z, 89101f50 «Glass Rain on a Distant Hot Jupiter»: the searches for
    «Glass Rain» and «Distant Hot» found Glass Animals (a band) and Distant Origin (a Star
    Trek episode); both were stored and «verified» into 24 claims the writer refused, and
    the day's run was spent. A page's own text decides: the subject's designation (HD
    189733b) when it has one, else several of the subject's words; the designation is also
    the first search query."""
    from app.research.agent import designations, page_is_about, search_queries

    title = "Glass Rain on a Distant Hot Jupiter"
    topic = "HD 189733b experiences glass rain caused by silicate-laden winds on its day side."
    fact = "HD\u202f189733b, a hot-Jupiter exoplanet, has winds that loft silicate particles."
    assert designations(title, topic, fact) == ["HD 189733b"]
    assert search_queries(title, topic)[0] == "HD 189733b"
    band = "Glass Animals are an English indie rock band formed in Oxford in 2010. Heat Waves…"
    planet = (
        "HD 189733 b is an exoplanet approximately 64 light-years away. Observations suggest "
        "winds of 8,700 km/h and silicate particles that may fall as rain of molten glass."
    )
    assert "HD 189733b" in str(page_is_about(band, title, topic, fact))
    assert page_is_about(planet, title, topic, fact) is None
    # Without a designation, the subject's own words decide, several of them.
    sn_topic = (
        "Discovery that the universe's expansion is accelerating thanks to Type Ia supernovae"
    )
    sn_fact = "In 1998 two teams found distant Type Ia supernovae dimmer than expected."
    channel = "Discovery Channel is an American cable television channel owned by Warner."
    paper = (
        "In 1998 two independent teams observed distant Type Ia supernovae and found them "
        "dimmer than expected, indicating that the expansion of the universe is accelerating."
    )
    assert page_is_about(channel, "The Supernova Surprise", sn_topic, sn_fact) is not None
    assert page_is_about(paper, "The Supernova Surprise", sn_topic, sn_fact) is None
    assert page_is_about("", title, topic, fact) == "pagina nu are text"


def test_the_reader_of_a_source_is_told_the_films_thesis_first():
    """Ten claims on white dwarfs and none on the 1998 discovery the film rests on
    (2026-10-15): the reader is told the title and the thesis, as data, and asked for the
    claims that support or refute the core fact first."""
    from types import SimpleNamespace

    from app.factual.agent_pipeline import _EXTRACT_INSTRUCTIONS, extraction_thesis_brief

    topic = SimpleNamespace(
        title="The Supernova Surprise",
        topic="the accelerating universe",
        thesis_json={"core_fact": "In 1998 distant supernovae were dimmer.", "hook": "What if"},
    )
    brief = extraction_thesis_brief(topic)
    assert "SUBIECTUL FILMULUI" in brief and "In 1998 distant supernovae were dimmer." in brief
    assert extraction_thesis_brief(None) == ""
    assert extraction_thesis_brief(SimpleNamespace(title="", topic="", thesis_json={})) == ""
    assert "MAI ÎNTÂI" in _EXTRACT_INSTRUCTIONS and "până la 14" in _EXTRACT_INSTRUCTIONS
