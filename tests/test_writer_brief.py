"""The Scriptwriter's brief says where the film plays, for whom, how it is judged and what it
costs; the Director's letters reach him (2026-10-13).

The Owner: «Marcus care scrie scriptul știe că trebuie să fie pentru un short pe YouTube? Știe
că trebuie să atragă vizualizări? Știe că trebuie să aibă un conținut mesajul lui?» and
«Directorul comunică cu fiecare și poate întoarce către el indicații noi? Agenția trebuie să
fie autonomă; toți agenții trebuie să fie conștienți că trebuie să economisim bani și să avem
calitate.»

What was measured before this work: the brief named the length and the claims; the platform,
the audience, the five criteria the Director scores, the thesis she chose, the cover and the
title rules and the price of a filmed scene lived in other modules and never in his prompt; her
REVISE letter was posted to her own inbox; the weekly «topics» direction was written on her own
id and recalled by nobody else; nothing he wrote was ever measured back to him.

Offline only: scripted models and the studio's own rows; no vendor, no model, no network (the
network is refused by conftest). Nothing here proves a live model answered.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.agents.editorial_judgement import CRITERION_FLOOR, PASS_TOTAL, criteria_lines
from app.agents.identity import compose_identity
from app.agents.memory import recall
from app.agents.models import Agent, AgentMessage, MemoryRecord, Role
from app.analytics.models import AnalyticsSnapshot
from app.analytics.services import MIN_SAMPLE_THRESHOLD
from app.factual import agent_pipeline
from app.factual.agent_pipeline import (
    HOOK_WORDS,
    MAX_SCENES,
    TITLE_CHARS,
    _cost_paragraph,
    _measured_paragraph,
    _write_instructions,
    agent_write_script,
)
from app.factual.editorial import MAX_SHORT_SECONDS, narration_budget
from app.factual.models import ScriptDraft, TopicIdea
from app.factual.story_review import judged_story, review_story
from app.media.cost_plan import plan_film
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.media.shooting_sheet import film_ceiling_micros
from app.publishing.models import ChannelRecord, PublicationRecord
from app.runbook.weekly import execute_weekly_review
from app.services import append_event, utc_now
from app.wording import review_verdict, usd
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_editorial_judgement import GOOD, StandIn, her_answer
from test_editorial_judgement import registry_with as judgement_registry
from test_editorial_quality import (  # noqa: F401 - `studio` is a fixture
    GOOD_SCENES,
    GOOD_SCORES,
    GOOD_THESIS,
    a_script,
    a_topic,
    registry_with,
    studio,
)
from test_serial_pipeline import inside_a_boundary
from test_weekly_review import (  # noqa: F401 - `staffed` and `channel` are fixtures
    REVIEW_JSON,
    channel,
    make_published,
    staffed,
)
from test_weekly_review import registry_with as weekly_registry


def _agent(session: Session, role_name: str) -> Agent:
    agent = session.scalar(
        select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == role_name)
    )
    assert agent is not None, role_name
    return agent


# ---------------------------------------------------------------------------
# The brief itself (no database)
# ---------------------------------------------------------------------------


def test_the_brief_names_the_platform_and_the_audience_and_says_the_hook_window_once():
    brief = _write_instructions(30)
    assert "YouTube Short" in brief and "vertical 9:16" in brief and "pe telefon" in brief
    assert "fără sunet la început" in brief and "redat în buclă" in brief
    assert "primul cadru și prima replică decid" in brief
    # No publishing record: the studio's own channel, unnamed; named when one exists.
    assert "pe canalul studioului" in brief
    assert "pe canalul «Main Channel A - Factual Shorts»" in _write_instructions(
        30, channel_name="Main Channel A - Factual Shorts"
    )
    assert f"niciodată peste {MAX_SHORT_SECONDS:.0f} de secunde" in brief
    assert "un străin de oriunde din lume" in brief and "fără nicio cunoștință" in brief
    # The hook window is the judge's — two seconds, said once; the brief's three are gone.
    assert "trei secunde" not in brief
    assert brief.count("două secunde") == 1
    assert "first two seconds" in criteria_lines()


def test_the_brief_carries_the_judges_own_criteria_and_her_bar():
    brief = _write_instructions(30)
    # The judge's lines, verbatim: the brief and the judgement cannot drift apart.
    assert criteria_lines() in brief
    assert "CUM JUDECĂ DIRECTORUL" in brief
    assert f"Pragul: {PASS_TOTAL}/50" in brief
    assert f"niciun criteriu sub {CRITERION_FLOOR}" in brief
    assert "KEEP / CHANGE / AVOID" in brief


def test_the_chosen_idea_is_inert_data_and_its_weaknesses_come_first():
    brief = _write_instructions(30, thesis=GOOD_THESIS, idea_scores=GOOD_SCORES)
    assert "IDEEA ALEASĂ DE DIRECTOR" in brief
    assert inside_a_boundary(brief, GOOD_THESIS["hook"])
    assert inside_a_boundary(brief, GOOD_THESIS["payoff"])
    assert "Păstrează promisiunea ei" in brief and "Directorul judecă" not in brief
    assert "ea judecă scenariul față de ele" in brief
    assert "Faptele rămân numai cele verificate de mai jos" in " ".join(brief.split())
    # The research scores under 0,70, lowest first, at most three — as a note, not as data.
    assert (
        "- Slăbiciunile ideii, după notele cercetării: visual_potential 0,50; "
        "cta_opportunity 0,60; shareability 0,60 — scrie ca să le acoperi." in brief
    )
    assert "composite" not in brief
    # An idea scored well everywhere has no weaknesses to name; a topic without a thesis has
    # no idea block at all.
    strong = _write_instructions(
        30, thesis=GOOD_THESIS, idea_scores=dict.fromkeys(GOOD_SCORES, 0.8)
    )
    assert "IDEEA ALEASĂ DE DIRECTOR" in strong and "Slăbiciunile ideii" not in strong
    assert "IDEEA ALEASĂ" not in _write_instructions(30)


def test_the_brief_says_what_the_cover_and_the_published_title_are_made_from():
    brief = _write_instructions(30)
    assert "Se desenează pe coperta filmului, peste primul cadru" in brief
    assert f"cel mult vreo {HOOK_WORDS} cuvinte" in brief
    assert "nicio cifră pe care afirmațiile de mai jos" in brief
    assert "sămânța titlului" in brief and "subiectul întâi" in brief
    assert f"cel mult {TITLE_CHARS} de caractere" in brief and "fără clickbait" in brief


# ---------------------------------------------------------------------------
# The cost line: the price table or nothing
# ---------------------------------------------------------------------------


def test_the_cost_line_is_priced_from_the_table_or_left_out(engine, monkeypatch):
    budget = narration_budget(30)
    ceiling, source = film_ceiling_micros(None)
    assert source == "implicit"  # no Owner setting in a test studio

    # No motion model selected: the ceiling and the free cards are said, no price is guessed.
    without = _cost_paragraph(engine, 30)
    assert "COSTUL, din tabelul de prețuri" in without
    assert "o scenă LIVE de" not in without and "costă circa" not in without
    assert f"plafonul acestui film este {usd(ceiling)} (implicit, nesetat de Proprietar)" in without
    assert "DATA_CARD, TITLE_CARD și BLACK costă 0" in without
    assert f"preferă {budget['scenes']} scene LIVE puternice față de {MAX_SCENES} slabe" in without

    # The model the studio films with, at the sheet's resolution: the published price of one
    # scene of the brief's own average length, stills and clip together.
    monkeypatch.setattr(
        "app.media.shooting_sheet.motion_clip_limit", lambda _engine: ("seedance2_5", 30)
    )
    priced = _cost_paragraph(engine, 30)
    seconds = budget["target_seconds"] / budget["scenes"]
    per_scene = plan_film([seconds], model_id="seedance2_5", resolution="1080p")["total_usd_micros"]
    assert (
        f"o scenă LIVE de circa 6,0 s costă circa {usd(per_scene)} "
        "(imagine + mișcare, seedance2_5 la 1080p);" in priced
    )
    affordable = ceiling // per_scene
    assert affordable < budget["scenes"]  # the implicit ceiling does not pay five such scenes
    assert f"plafonul plătește cel mult {affordable} scene LIVE" in priced
    assert f"preferă {affordable} scene LIVE puternice față de {MAX_SCENES} slabe" in priced


# ---------------------------------------------------------------------------
# The whole prompt, through the writer's own path
# ---------------------------------------------------------------------------


def _writer_answer() -> str:
    return json.dumps(
        {
            "title": "The address nobody may buy",
            "core_message": "One web address is reserved so nobody can ever own it.",
            "takeaway": "Some addresses are reserved by the registry, on purpose.",
            "hook": "There is one web address nobody on earth is allowed to buy.",
            "ending": "Reserved on purpose, by the registry itself.",
            "cta": "Which reserved address surprised you most?",
            "cta_kind": "COMMENT",
            "scenes": [
                {
                    "narration": scene["narration"],
                    "visual": scene["visual_description"],
                    "purpose": scene["purpose"],
                    "claim_ids": scene["claim_ids"],
                }
                for scene in GOOD_SCENES
            ],
        }
    )


def test_the_writers_prompt_carries_the_platform_the_idea_and_the_money(
    engine,
    studio,  # noqa: F811 - the fixture
    monkeypatch,
):
    topic_id = a_topic(engine)
    seen: list[str] = []

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        seen.append(prompt)
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": _writer_answer(),
            "error_detail": None,
        }

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    monkeypatch.setattr(agent_pipeline, "_announce", lambda *a, **k: None)
    written = agent_write_script(
        engine, object(), topic_id, str(uuid4()), target_duration_seconds=20
    )
    assert written["script"]["id"]
    (prompt,) = seen
    # The channel by its publishing record, the idea she chose as data, the money, the rules.
    assert "pe canalul «Main Channel A - Factual Shorts»" in prompt
    assert inside_a_boundary(prompt, GOOD_THESIS["hook"])
    assert inside_a_boundary(prompt, '"target_audience": "general"')
    assert "Slăbiciunile ideii, după notele cercetării: visual_potential 0,50" in prompt
    assert "plafonul acestui film este" in prompt
    assert criteria_lines() in prompt
    assert "coperta filmului" in prompt
    # Nothing published and measured yet: no measured block, nothing invented.
    assert "MĂSURAT PE ACEST CANAL" not in prompt
    # The brief ends where it always did: the claims, then the subject.
    assert prompt.index("AFIRMAȚII VERIFICATE") < prompt.index("SUBIECT:")


# ---------------------------------------------------------------------------
# Her letter reaches the writer, and is settled when a later draft passes
# ---------------------------------------------------------------------------


def _she_says(verdict: str, *notes: str):
    def answer(prompt: str) -> str:
        return json.dumps(
            {
                "verdict": verdict,
                "hook_strength": 7,
                "clarity": 7,
                "payoff": 7,
                "cta_fit": 6,
                "retention": {
                    "at_0": 100,
                    "at_3": 70,
                    "at_10": 55,
                    "at_end": 45,
                    "collapse_at": "3-9",
                    "why": "the setup repeats the hook",
                },
                "notes": list(notes) or ["Strânge scena 3."],
            }
        )

    return answer


def test_her_letter_reaches_the_writers_next_prompt_and_is_settled_when_a_later_draft_passes(
    engine,
    studio,  # noqa: F811 - the fixture
):
    topic_id = a_topic(engine)
    first = a_script(engine, topic_id, status="VERIFIED_PASS")
    registry, _ = registry_with(studio, _she_says("REVISE", "Strânge scena 3."))
    verdict = review_story(engine, registry, first, str(uuid4()), target_seconds=20)
    assert verdict["verdict"] == "REVISE"

    with Session(engine) as session:
        writer, director = _agent(session, "ScriptWriter"), _agent(session, "Director")
        (letter,) = session.scalars(
            select(AgentMessage).where(AgentMessage.intent == "REQUEST_REVIEW")
        ).all()
        letter_id = letter.id
        # Addressed to him, from her, open; not in her own inbox any more.
        assert letter.to_agent_id == writer.id and letter.from_agent_id == director.id
        assert letter.status == "OPEN"
        assert (
            letter.subject == f"Povestea «The address nobody may buy»: {review_verdict('REVISE')}"
        )
        assert letter.body_json["kind"] == "story_review"
        assert letter.body_json["topic_id"] == topic_id
        assert letter.body_json["script_id"] == first
        assert letter.body_json["retention"]["collapse_at"] == "3-9"
        # Her notes, her retention row and the span where she loses the viewer, in words.
        assert "Strânge scena 3." in letter.body_text
        assert (
            "Reținerea la care se așteaptă Directorul: 100% la 0 s, 70% la 3 s, 55% la 10 s, "
            "45% la final; pierde publicul la 3-9: the setup repeats the hook." in letter.body_text
        )
        assert "0% la 5 s" not in letter.body_text  # a mark she did not give is not said
        # It enters his next run's prompt, through his identity.
        identity = compose_identity(session, writer)
        assert "WHAT IS ASKED OF YOU RIGHT NOW" in identity.system
        assert letter.subject in identity.system and "70% la 3 s" in identity.system
        assert letter_id in identity.context["open_message_ids"]
        director_name = director.display_name

    # A later draft of the same story passes: the letter is resolved and leaves his prompt.
    second = a_script(engine, topic_id, status="VERIFIED_PASS")
    passing, _ = registry_with(studio, _she_says("PASS"))
    assert (
        review_story(engine, passing, second, str(uuid4()), target_seconds=20)["verdict"] == "PASS"
    )
    with Session(engine) as session:
        letter = session.get(AgentMessage, letter_id)
        assert letter.status == "RESOLVED"
        assert letter.resolved_by == director_name
        assert letter.resolution == f"Versiunea {second[:8]} a trecut recenzia de poveste."
        writer = _agent(session, "ScriptWriter")
        identity = compose_identity(session, writer)
        assert letter.subject not in identity.system
        assert identity.context["open_message_ids"] == []


# ---------------------------------------------------------------------------
# The weekly direction is studio-wide; the writer gets his own letter
# ---------------------------------------------------------------------------


def test_the_weekly_direction_is_studio_wide_and_the_writer_gets_his_own_letter(
    engine,
    staffed,  # noqa: F811 - the fixture
    channel,  # noqa: F811 - the fixture
):
    make_published(engine, channel)
    answer = {
        **REVIEW_JSON,
        "writing": (
            "Cârligul „Test publication” a ținut 62%: deschide cu o miză, nu cu o definiție; "
            "îndemnul de tip COMMENT a adus comentarii, păstrează-l."
        ),
    }
    registry, _ = weekly_registry(staffed, json.dumps(answer, ensure_ascii=False))
    result = execute_weekly_review(engine, registry)
    assert result["status"] == "COMPLETED", result
    assert result["instructions_filed"] == 5

    with Session(engine) as session:
        strategy = session.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_class == "STRATEGY")
        )
        assert strategy is not None and REVIEW_JSON["topics"][:40] in strategy.content
        # Studio-wide: on nobody's id, so every role whose scope reads STRATEGY recalls it.
        assert strategy.agent_id is None
        for role_name in ("ScriptWriter", "LeadResearcher", "Director"):
            employee = staffed["agents"][role_name]
            role = session.get(Role, employee.role_id)
            assert strategy.id in [m.id for m in recall(session, employee, role)], role_name
        # His own letter about how to write, apart from the topics letter he already got.
        writer = staffed["agents"]["ScriptWriter"]
        letters = session.scalars(
            select(AgentMessage).where(
                AgentMessage.intent == "HANDOFF", AgentMessage.to_agent_id == writer.id
            )
        ).all()
        by_department = {m.body_json["department"]: m for m in letters}
        assert set(by_department) == {"scenarii", "scris"}
        assert by_department["scris"].body_json["instructions"] == answer["writing"]
        assert by_department["scenarii"].body_json["instructions"] == REVIEW_JSON["topics"]
        assert "departamentul de scris" in by_department["scris"].subject


# ---------------------------------------------------------------------------
# The measured block: this channel's best and worst, only with enough samples
# ---------------------------------------------------------------------------


def a_measured_short(
    engine,
    channel_id: str,
    *,
    title: str,
    hook: str,
    cta_kind: str,
    average_view_percentage: float,
    total: int | None,
    seconds: float = 45.0,
) -> str:
    """One published short with the rows `story_performance` walks: its topic, its script
    (the hook, the call to action, the editorial record of what shipped), its storyboard,
    the rendered asset, the render job, the publication and one measured snapshot."""
    now = utc_now()
    topic_id, script_id, board_id, asset_id, job_id, publication_id = (
        str(uuid4()) for _ in range(6)
    )
    story: dict[str, Any] = {"hook": hook, "cta_kind": cta_kind, "estimated_seconds": seconds}
    if total is not None:
        story["editorial"] = {"shipped": {"total": total, "scores": {"hook": 8}, "passed": True}}
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="t",
                angle="a",
                target_audience="general",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=45,
                voiceover_full_text=hook,
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                story_json=story,
                created_at=now,
            )
        )
        session.flush()
        session.add(Storyboard(id=board_id, script_draft_id=script_id, title=title, created_at=now))
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}/final_short_9_16.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=seconds,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
                event_id=None,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=board_id,
                status="COMPLETED",
                output_asset_id=asset_id,
                started_at=now,
            )
        )
        event = append_event(
            session, "publishing.intent_created", "publication_record", publication_id, 1, {}, "c"
        )
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title=title,
                description="",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=f"yt_{publication_id[:8]}",
                remote_url=None,
                scheduled_publish_time=None,
                published_at=now,
                created_at=now,
                event_id=event.event_id,
            )
        )
        session.add(
            AnalyticsSnapshot(
                id=str(uuid4()),
                publication_id=publication_id,
                channel_id=channel_id,
                window="LIFETIME",
                views=1000,
                watch_time_seconds=28000.0,
                average_view_percentage=average_view_percentage,
                impressions=12000,
                ctr_percentage=8.0,
                likes=120,
                comments=9,
                shares=4,
                subscribers_gained=15,
                subscribers_lost=2,
                raw_metrics_json={"provider": "TEST"},
                snapshot_at=now,
                event_id=None,
            )
        )
    return publication_id


FILMS = (
    (
        "The light your eyes were not built for",
        "Most of the sky hides in light you cannot see.",
        "CURIOSITY",
        71.0,
        42,
    ),
    (
        "The address nobody may buy",
        "There is one web address nobody is allowed to buy.",
        "COMMENT",
        55.0,
        38,
    ),
    (
        "Napoleon was not short",
        "Everyone pictures Napoleon as tiny; he was not.",
        "DEBATE",
        23.0,
        31,
    ),
    ("A fourth short", "What if the fourth one is the plain one.", "KNOWLEDGE", 40.0, None),
)


def test_the_measured_block_appears_only_with_enough_samples(engine, studio):  # noqa: F811
    with Session(engine) as session:
        channel_id = session.scalar(
            select(ChannelRecord.id).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        )
    assert MIN_SAMPLE_THRESHOLD == 3
    for title, hook, cta, average, total in FILMS[: MIN_SAMPLE_THRESHOLD - 1]:
        a_measured_short(
            engine,
            channel_id,
            title=title,
            hook=hook,
            cta_kind=cta,
            average_view_percentage=average,
            total=total,
        )
    # Two measured films: the analytics' own rule says nothing, so the brief says nothing.
    assert _measured_paragraph(engine, channel_id) == ""
    assert _measured_paragraph(engine, None) == ""

    napoleon = ""
    for title, hook, cta, average, total in FILMS[MIN_SAMPLE_THRESHOLD - 1 :]:
        publication_id = a_measured_short(
            engine,
            channel_id,
            title=title,
            hook=hook,
            cta_kind=cta,
            average_view_percentage=average,
            total=total,
        )
        if title.startswith("Napoleon"):
            napoleon = publication_id
    # A newer snapshot of one film outranks its older one: 30% is what Napoleon measured now.
    with Session(engine) as session, session.begin():
        session.add(
            AnalyticsSnapshot(
                id=str(uuid4()),
                publication_id=napoleon,
                channel_id=channel_id,
                window="LIFETIME",
                views=1500,
                watch_time_seconds=30000.0,
                average_view_percentage=30.0,
                impressions=14000,
                ctr_percentage=7.0,
                likes=130,
                comments=10,
                shares=4,
                subscribers_gained=16,
                subscribers_lost=2,
                raw_metrics_json={"provider": "TEST"},
                snapshot_at=utc_now(),
                event_id=None,
            )
        )

    block = _measured_paragraph(engine, channel_id)
    assert block.startswith(
        "MĂSURAT PE ACEST CANAL (4 short-uri publicate și măsurate; cifre, nu păreri):"
    )
    best, worst = block.split("Cele mai puțin urmărite:")
    assert "Cele mai urmărite până la capăt:" in best
    lines = [line for line in best.splitlines() if line.startswith("- «")]
    assert [line.split("»")[0] for line in lines] == [
        "- «The light your eyes were not built for",
        "- «The address nobody may buy",
        "- «A fourth short",
    ]
    assert (
        "- «The light your eyes were not built for»: reținere medie 71%, cârlig «Most of the sky "
        "hides in light you cannot see.», CTA CURIOSITY, 45 s, notă editorială 42/50" in best
    )
    # The one never judged carries no editorial total; nothing is invented for it.
    (fourth,) = [line for line in lines if "A fourth short" in line]
    assert "notă editorială" not in fourth and "CTA KNOWLEDGE" in fourth
    assert "- «Napoleon was not short»: reținere medie 30%" in worst
    assert "23%" not in block
    assert block.rstrip().endswith(
        "Scrie pentru ce a ținut publicul, nu pentru ce a plăcut studioului."
    )


# ---------------------------------------------------------------------------
# What shipped stays with the writer
# ---------------------------------------------------------------------------


def test_the_writer_remembers_what_shipped_and_her_last_note(engine, studio):  # noqa: F811
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, status="VERIFIED_PASS")
    model = StandIn(lambda _prompt: her_answer(GOOD))
    judged = judged_story(
        engine,
        judgement_registry(studio, model),
        script_id,
        target_seconds=20,
        rounds=1,
        review={"verdict": "PASS", "failed": [], "notes": []},
    )
    assert judged["script_id"] == script_id and judged["editorial"]["passed"] is True

    with Session(engine) as session:
        writer = _agent(session, "ScriptWriter")
        (record,) = session.scalars(
            select(MemoryRecord).where(
                MemoryRecord.memory_class == "AGENT_OPINION", MemoryRecord.agent_id == writer.id
            )
        ).all()
        assert record.content == (
            "Povestea «The address nobody may buy»: 1 versiune citită de Director; a plecat "
            "versiunea 1 cu 40/50 (hook 8, clarity 8, moment 8, punchline 8, follow 8). "
            "Ultima ei notă: hook (8/10): the hook as written; clarity (8/10): the clarity as "
            "written"
        )
        assert record.source_type == "run" and record.source_id
        # His next run recalls it: AGENT_OPINION is in his scope, and the record is his.
        role = session.get(Role, writer.role_id)
        assert record.id in [m.id for m in recall(session, writer, role)]


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_contract_tells_the_writer_a_live_scene_is_paid(engine, studio):  # noqa: F811
    with Session(engine) as session:
        system = compose_identity(session, _agent(session, "ScriptWriter")).system
    assert "every LIVE scene is a paid shot" in system
    assert "merge two scenes that show the same thing into one" in system
    assert "a vertical YouTube Short watched on a phone" in system
