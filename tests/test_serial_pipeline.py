"""The Office Serial as a Channel B video, from a sanitised full-day log.

What was measured before this work: every `domain_event` carried visibility OWNER and the
day's notable events were described as raw `key=value` payload pairs — model ids, message
text, prices — handed as they were to the showrunner; continuity between episodes was one
title and a roster size; an episode stopped at a text DRAFT for the Owner's hand, and nothing
consumed an APPROVED one.

These tests hold the six pieces that change that, in the order the day runs them:

- the projection: only PUBLIC_SAFE event types reach the showrunner, unknown types are
  private by default, and a key, a model id, a price, a URL or an Owner's words never do;
- continuity: the next episode's prompt carries the last summaries and the open threads,
  and the canon number moves only when an episode is approved;
- the Director's review: computed checks first, then her verdict; PASS approves only under
  the channel's policy; FAIL is one rewrite, then REJECTED;
- the storyboard: the same shape the factual path produces, so render, QC and publish need
  no change, and nothing private in its prompts;
- the stage: a quiet day is COMPLETED with the reason, a refusal never raises;
- closing yesterday in full.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.factual.story_review import story_gate
from app.media.models import Storyboard, StoryboardScene
from app.media.serial_storyboard import SerialStoryboardError, storyboard_from_episode
from app.media.services import (
    generate_storyboard_from_script,
    get_storyboard,
    seed_default_character_bibles,
)
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.services import utc_now
from app.story.models import ContinuityState, DailyStudioLog, StoryEpisode
from app.story.projection import (
    OWNER_PRIVATE,
    PUBLIC_SAFE,
    classify_event_type,
    project_log_for_story,
    redact,
)
from app.story.review import episode_checks, review_episode
from app.story.serial_stage import run_serial_stage
from app.story.services import (
    EpisodeNotGrounded,
    business_date,
    close_daily_log,
    close_previous_day,
    decide_episode,
    get_continuity,
    write_episode,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

TZ = "Europe/Bucharest"

#: A fake key, a model id, a price, a URL and an address: none may reach a prompt.
FAKE_KEY = "sk-TESTKEYabcdefghijklmnop1234"
MODEL_ID = "glm-5.3"
PRICE = "$2.60"
URL = "https://vendor.example/invoice/77"
EMAIL = "owner@example.com"


def add_event(
    engine,
    event_type: str,
    when: datetime | None = None,
    payload=None,
    aggregate_type: str = "agent",
    aggregate_id: str | None = None,
) -> str:
    event_id = str(uuid4())
    moment = (when or datetime.now(UTC)).astimezone(UTC).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            DomainEvent(
                event_id=event_id,
                event_type=event_type,
                timestamp=moment,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id or str(uuid4()),
                aggregate_version=1,
                correlation_id=str(uuid4()),
                causation_id=None,
                schema_version=1,
                visibility="OWNER",
                payload=payload or {},
            )
        )
    return event_id


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def projected(log: dict, event_id: str) -> dict:
    """The projection item for one event. The seeded workforce and channels emit public
    events of their own on the same day, so a test picks its event by id."""
    (item,) = [i for i in log["narrative_projection"] if i["event_id"] == event_id]
    return item


def roster_names(engine, log_id: str) -> list[str]:
    with Session(engine) as session:
        return [m["display_name"] for m in session.get(DailyStudioLog, log_id).roster_json]


#: Enough words for a beat that, over three beats, lands in the 45-70 second window.
LINE = (
    "Sarah opens the board and asks for the number before anyone says good morning. "
    "Aris answers with the evidence first and the opinion never, which is his whole style. "
    "The room laughs, the espresso cup goes down, and the day has officially started here."
)


def beats_for(event_ids: list[str], names: list[str], count: int = 3) -> list[dict]:
    beats = []
    for index in range(count):
        beats.append(
            {
                "scene": f"Redacția, scena {index + 1}: {names[0]} la birou.",
                "dialogue": LINE,
                "event_ids": [event_ids[index % len(event_ids)]],
                "characters": names if index == 0 else names[:1],
            }
        )
    return beats


def episode_answer(beats, title="O zi la studio", **extra) -> str:
    body = {"title": title, "beats": beats, "summary": "Sarah a cerut numărul; Aris l-a adus."}
    body.update(extra)
    return json.dumps(body)


def fake_showrunner(monkeypatch, answer: str, seen: list[str] | None = None):
    from app.story import services

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        if seen is not None:
            seen.append(prompt)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    monkeypatch.setattr(services, "run_agent_task", fake_run)


def fake_director(monkeypatch, verdict: str, notes: str = "", calls: list | None = None):
    from app.story import review

    answer = json.dumps(
        {"verdict": verdict, "reasons": ["motiv de test"], "notes": notes, "story": "o zi"}
    )

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        if calls is not None:
            calls.append(prompt)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    monkeypatch.setattr(review, "run_agent_task", fake_run)


def registry():
    return SimpleNamespace(registered_ids=lambda: ["fake-provider"])


def allow_director_approval(engine, allowed: bool = True) -> None:
    with Session(engine) as session, session.begin():
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        rules = dict(channel.series_rules_json or {})
        rules["director_may_approve_episodes"] = allowed
        channel.series_rules_json = rules


def a_day(engine, when: datetime | None = None) -> tuple[dict, list[str]]:
    """A closed day with three PUBLIC_SAFE events; returns the log and their ids."""
    ids = [
        add_event(engine, "factual.topic_selected", when, {"title": "Apa de pe GJ 486 b"}),
        add_event(engine, "factual.script_approved", when, {"claims_count": 3}),
        add_event(engine, "media.video_rendered", when, {"file_size_bytes": 1}),
    ]
    log = close_daily_log(engine, TZ, business_date(TZ, when) if when else None)
    return log, ids


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


def test_unknown_event_types_are_private_by_default():
    assert classify_event_type("factual.script_approved") == PUBLIC_SAFE
    assert classify_event_type("agent.model_assigned") == OWNER_PRIVATE
    assert classify_event_type("something.nobody_classified") == OWNER_PRIVATE


@pytest.mark.parametrize("secret", [FAKE_KEY, MODEL_ID, PRICE, URL, EMAIL, "12.50 USD"])
def test_redaction_removes_what_may_not_be_public(secret):
    text = f"Directorul a spus: {secret} și a plecat."
    cleaned = redact(text)
    assert secret not in cleaned
    assert "Directorul a spus" in cleaned


def test_the_projection_keeps_only_public_safe_events(engine, staffed):
    safe = add_event(engine, "factual.script_approved", payload={"claims_count": 2})
    private = add_event(engine, "agent.model_assigned", payload={"model": MODEL_ID})
    log = close_daily_log(engine, TZ)

    projected = {item["event_id"] for item in log["narrative_projection"]}
    assert safe in projected
    assert private not in projected
    # The private one still counts, and is still in the operational record of the day.
    assert private in {item["event_id"] for item in log["notable_events"]}


def test_a_private_payload_value_is_redacted_from_a_public_event(engine, staffed):
    event_id = add_event(
        engine,
        "media.editorial_reviewed",
        payload={"verdict": "APPROVE", "title": f"Film cu {MODEL_ID} la {PRICE}", "story": "x"},
    )
    log = close_daily_log(engine, TZ)

    item = projected(log, event_id)
    assert MODEL_ID not in item["description"]
    assert PRICE not in item["description"]
    assert "APPROVE" in item["description"]


def test_the_owners_words_are_a_fact_not_content(engine, staffed):
    event_id = add_event(
        engine,
        "agent.message_posted",
        aggregate_type="agent_message",
        payload={
            "from_name": "Sarah (Director)",
            "to_name": "Owner",
            "for_owner": True,
            "subject": "Parola contului este hunter2",
            "excerpt": "Parola contului este hunter2 și cardul se termină în 4242",
        },
    )
    log = close_daily_log(engine, TZ)

    item = projected(log, event_id)
    assert "Owner" in item["description"]
    assert "hunter2" not in item["description"]
    assert "4242" not in item["description"]


def test_project_log_for_story_reads_only_from_the_events(engine, staffed):
    event_id = add_event(engine, "agent.message_sent", payload={"text": f"cheia este {FAKE_KEY}"})
    log = close_daily_log(engine, TZ)
    with Session(engine) as session:
        row = session.get(DailyStudioLog, log["id"])
        projection = project_log_for_story(session, row)
    assert event_id in {item["event_id"] for item in projection}
    assert FAKE_KEY not in json.dumps(projection)


def test_the_showrunner_prompt_contains_nothing_private(engine, staffed, monkeypatch):
    """The test the projection exists for: a key, a model id and a price in the day's raw
    payloads, none in the prompt."""
    safe = add_event(
        engine,
        "publishing.video_published",
        payload={"title": "Apa de pe GJ 486 b", "remote_url": URL, "privacy_status": "private"},
    )
    add_event(engine, "agent.model_assigned", payload={"model_id": MODEL_ID, "price": PRICE})
    add_event(engine, "agent.message_sent", payload={"text": f"key {FAKE_KEY}"})
    log = close_daily_log(engine, TZ)
    raw = json.dumps(log["notable_events"])
    assert MODEL_ID in raw and FAKE_KEY in raw  # the operational record keeps the truth

    seen: list[str] = []
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for([safe], names)), seen)
    write_episode(engine, registry(), log["id"], str(uuid4()))

    (prompt,) = seen
    for forbidden in (FAKE_KEY, MODEL_ID, PRICE, URL):
        assert forbidden not in prompt
    assert safe in prompt


def test_a_beat_citing_a_private_event_is_not_grounded(engine, staffed, monkeypatch):
    private = add_event(engine, "agent.model_assigned", payload={"model_id": MODEL_ID})
    safe = add_event(engine, "factual.script_approved")
    log = close_daily_log(engine, TZ)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for([safe, private], names)))

    with pytest.raises(EpisodeNotGrounded):
        write_episode(engine, registry(), log["id"], str(uuid4()))


def test_an_older_log_without_a_projection_is_projected_once(engine, staffed, monkeypatch):
    safe = add_event(engine, "factual.script_approved")
    log = close_daily_log(engine, TZ)
    with Session(engine) as session, session.begin():
        session.get(DailyStudioLog, log["id"]).narrative_projection_json = None

    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for([safe], names)))
    write_episode(engine, registry(), log["id"], str(uuid4()))

    with Session(engine) as session:
        assert session.get(DailyStudioLog, log["id"]).narrative_projection_json


# ---------------------------------------------------------------------------
# Continuity
# ---------------------------------------------------------------------------


def test_the_second_episode_carries_the_first_summary_and_threads(engine, staffed, monkeypatch):
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    first_log, first_ids = a_day(engine, two_days_ago)
    names = roster_names(engine, first_log["id"])
    fake_showrunner(
        monkeypatch,
        episode_answer(
            beats_for(first_ids, names),
            summary="Sarah a cerut numărul și nimeni nu l-a avut.",
            threads_opened=["Cine aduce numărul mâine?"],
        ),
    )
    first = write_episode(engine, registry(), first_log["id"], str(uuid4()))["episode"]
    assert first["continuity"]["episode_number"] == 1
    decide_episode(engine, first["id"], True, "")

    state = get_continuity(engine)
    assert state["canon_episode_number"] == 1
    assert [t["text"] for t in state["threads"]] == ["Cine aduce numărul mâine?"]
    assert state["summaries"][-1]["summary"] == "Sarah a cerut numărul și nimeni nu l-a avut."

    second_log, second_ids = a_day(engine)
    seen: list[str] = []
    fake_showrunner(
        monkeypatch,
        episode_answer(beats_for(second_ids, names), threads_closed=["T1"]),
        seen,
    )
    second = write_episode(engine, registry(), second_log["id"], str(uuid4()))["episode"]

    (prompt,) = seen
    assert "Sarah a cerut numărul și nimeni nu l-a avut." in prompt
    assert "Cine aduce numărul mâine?" in prompt
    assert "T1" in prompt
    # Who they are, from the bible, verbatim.
    assert "Brunette professional bob" in prompt
    assert second["continuity"]["episode_number"] == 2
    assert second["continuity"]["threads_closed"] == ["T1"]


def test_the_canon_number_moves_only_on_approval(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    assert get_continuity(engine)["canon_episode_number"] == 0

    fake_director(monkeypatch, "FAIL", notes="Prea lung.")
    review_episode(engine, registry(), episode["id"])
    assert get_continuity(engine)["canon_episode_number"] == 0

    again = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    decide_episode(engine, again["id"], True, "")
    assert get_continuity(engine)["canon_episode_number"] == 1
    # A second approval of the same episode cannot happen, and the state is versioned.
    assert get_continuity(engine)["version"] == 2


# ---------------------------------------------------------------------------
# The Director's review
# ---------------------------------------------------------------------------


def test_the_checks_are_computed_before_any_model(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    with Session(engine) as session:
        checks = episode_checks(session, session.get(StoryEpisode, episode["id"]))

    assert set(checks) == {"grounding", "privacy", "length", "cast", "accessibility"}
    assert all(check["passed"] for check in checks.values()), checks
    assert 45 <= checks["length"]["seconds"] <= 70


def test_a_leaked_pattern_in_the_dialogue_fails_without_asking_the_model(
    engine, staffed, monkeypatch
):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    beats = beats_for(ids, names)
    beats[1]["dialogue"] = LINE + f" Cheia este {FAKE_KEY}."
    fake_showrunner(monkeypatch, episode_answer(beats))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL"
    assert calls == []  # the Director was not asked about an episode the checks refused
    assert review["checks"]["privacy"]["passed"] is False
    with Session(engine) as session:
        assert session.get(StoryEpisode, episode["id"]).status == "REJECTED"


def test_a_missing_cast_member_and_a_short_episode_are_named(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    beats = beats_for(ids, names[:1], count=1)  # one beat, one character
    fake_showrunner(monkeypatch, episode_answer(beats))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "PASS")
    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL"
    assert review["checks"]["cast"]["passed"] is False
    assert review["checks"]["length"]["passed"] is False


def test_a_pass_without_the_policy_leaves_the_episode_for_the_owner(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "PASS")
    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "PASS"
    assert review["status"] == "DRAFT"
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "DRAFT"
        assert row.review_json["verdict"] == "PASS"
        assert row.reviewed_by is None
    assert get_continuity(engine)["canon_episode_number"] == 0


def test_a_pass_under_the_policy_approves_as_the_director(engine, staffed, monkeypatch):
    allow_director_approval(engine)
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "PASS")
    review = review_episode(engine, registry(), episode["id"])

    assert review["status"] == "APPROVED"
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "APPROVED"
        assert row.reviewed_by == "director"
        approved = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "story.episode_approved",
                DomainEvent.aggregate_id == episode["id"],
            )
        ).all()
        assert len(approved) == 1
        assert approved[0].payload["reviewed_by"] == "director"
    assert get_continuity(engine)["canon_episode_number"] == 1


def test_a_reviewed_episode_is_not_reviewed_twice(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    fake_director(monkeypatch, "FAIL", notes="Nu.")
    review_episode(engine, registry(), episode["id"])

    from app.story.review import ReviewError

    with pytest.raises(ReviewError):
        review_episode(engine, registry(), episode["id"])


# ---------------------------------------------------------------------------
# The storyboard
# ---------------------------------------------------------------------------


def approved_episode(engine, monkeypatch, extra_private: bool = False) -> tuple[dict, dict]:
    log, ids = a_day(engine)
    if extra_private:
        add_event(engine, "agent.model_assigned", payload={"model_id": MODEL_ID})
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]
    decide_episode(engine, episode["id"], True, "")
    return log, episode


def a_factual_storyboard(engine) -> dict:
    ids = {k: str(uuid4()) for k in ("topic", "script")}
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title="Apa de pe GJ 486 b",
                topic="space",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title="Apa de pe GJ 486 b",
                voiceover_full_text=LINE,
                scenes_json=[{"narration": LINE, "visual_description": "A planet."}],
                claim_ids_json=[],
                status="APPROVED",
                created_at=utc_now(),
            )
        )
    return generate_storyboard_from_script(engine, ids["script"], "MOTION_GRAPHIC", "9:16", "c")


def test_the_storyboard_has_the_shape_of_the_factual_one(engine, staffed, monkeypatch):
    _, episode = approved_episode(engine, monkeypatch)
    factual = a_factual_storyboard(engine)

    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    serial = get_storyboard(engine, board_id)

    assert set(serial) == set(factual)
    assert set(serial["scenes"][0]) == set(factual["scenes"][0])
    assert serial["status"] == factual["status"] == "APPROVED"
    assert serial["aspect_ratio"] == "9:16"
    assert serial["total_scenes"] == len(episode["beats"])
    for scene, beat in zip(serial["scenes"], episode["beats"], strict=True):
        assert scene["voiceover_segment"] == beat["dialogue"]
        assert beat["scene"] in scene["visual_prompt"]
        assert scene["claim_ids_json"] == []
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        assert board.channel_id == channel.id
        assert board.series_key == "office_serial"
        # The gate the media stage asks before it spends anything is satisfied by the review.
        assert story_gate(session, board.script_draft_id) == (True, "")
        script = session.get(ScriptDraft, board.script_draft_id)
        assert script.status == "APPROVED" and script.claim_ids_json == []
        assert session.get(StoryEpisode, episode["id"]).storyboard_id == board_id


def test_the_scenes_bind_the_characters_from_the_bibles(engine, staffed, monkeypatch):
    _, episode = approved_episode(engine, monkeypatch)
    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    with Session(engine) as session:
        first = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board_id)
            .order_by(StoryboardScene.scene_index)
        ).first()
        assert first.character_ids_json  # bible ids for the roster members in the beat
        assert "Brunette professional bob" in first.visual_prompt


def test_nothing_private_reaches_the_storyboard_prompts(engine, staffed, monkeypatch):
    _, episode = approved_episode(engine, monkeypatch, extra_private=True)
    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    with Session(engine) as session:
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        ):
            assert MODEL_ID not in scene.visual_prompt
            assert MODEL_ID not in scene.voiceover_segment


def test_only_an_approved_episode_becomes_a_storyboard(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    with pytest.raises(SerialStoryboardError):
        storyboard_from_episode(engine, episode["id"], str(uuid4()))


def test_the_storyboard_is_built_once_per_episode(engine, staffed, monkeypatch):
    _, episode = approved_episode(engine, monkeypatch)
    first = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    second = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    assert first == second


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def test_the_stage_is_skipped_without_a_language_model(engine, staffed, settings):
    outcome = run_serial_stage(engine, SimpleNamespace(registered_ids=list), settings)
    assert outcome["status"] == "SKIPPED"
    assert "model de limbaj" in outcome["reason"]


def test_a_quiet_day_completes_with_the_reason(engine, staffed, settings, monkeypatch):
    close_daily_log(engine, TZ, business_date(TZ, datetime.now(UTC) - timedelta(days=3)))
    fake_showrunner(monkeypatch, "")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["episodes"] == 0
    assert "liniștită" in outcome["reason"]
    with Session(engine) as session:
        assert session.scalars(select(StoryEpisode)).all() == []


def test_the_stage_runs_the_day_through_to_a_storyboard(engine, staffed, settings, monkeypatch):
    allow_director_approval(engine)
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["projected"] >= 3
    assert artefacts["written"] == 1
    assert artefacts["reviewed"] == 1
    assert artefacts["approved"] == 1
    assert artefacts["storyboard_id"]
    assert get_storyboard(engine, artefacts["storyboard_id"])["status"] == "APPROVED"


def test_a_fail_is_rewritten_once_with_the_notes_then_rejected(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    prompts: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), prompts)
    fake_director(monkeypatch, "FAIL", notes="Primul beat nu se ține singur.")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["rewritten"] == 1
    assert outcome["artefacts"]["approved"] == 0
    assert outcome["artefacts"]["storyboard_id"] is None
    assert len(prompts) == 2
    assert "Primul beat nu se ține singur." in prompts[1]
    with Session(engine) as session:
        rows = session.scalars(select(StoryEpisode)).all()
        assert sorted(row.status for row in rows) == ["REJECTED", "REJECTED"]
        assert any(row.rewrite_of_id for row in rows)


def test_a_pass_without_the_policy_leaves_the_day_waiting_for_the_owner(
    engine, staffed, settings, monkeypatch
):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["approved"] == 0
    assert outcome["artefacts"]["storyboard_id"] is None
    assert "aprobarea" in outcome["reason"]


def test_a_refusal_never_raises_and_a_provider_fault_is_transient(
    engine, staffed, settings, monkeypatch
):
    from app.runbook.services import TransientStageError
    from app.story import services

    a_day(engine)
    fake_showrunner(monkeypatch, "nu e JSON")
    outcome = run_serial_stage(engine, registry(), settings)
    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["written"] == 0
    assert outcome["artefacts"]["refusal"]

    def unreachable(*args, **kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(services, "run_agent_task", unreachable)
    with pytest.raises(TransientStageError):
        run_serial_stage(engine, registry(), settings)


# ---------------------------------------------------------------------------
# Closing yesterday, in full
# ---------------------------------------------------------------------------


def test_yesterday_is_closed_with_all_its_events(engine, staffed, settings):
    from zoneinfo import ZoneInfo

    yesterday = datetime.now(ZoneInfo(TZ)) - timedelta(days=1)
    morning = yesterday.replace(hour=2, minute=0, second=0, microsecond=0)
    evening = yesterday.replace(hour=22, minute=0, second=0, microsecond=0)
    add_event(engine, "factual.script_approved", when=morning)
    add_event(engine, "media.video_rendered", when=evening)

    log = close_previous_day(engine, settings)

    assert log["business_date"] == yesterday.date().isoformat()
    assert log["status"] == "CLOSED"
    counted = {t for t in log["event_counts"] if t.startswith(("factual.", "media."))}
    # Both halves of the day are in it: it was closed after the day was over.
    assert counted >= {"factual.script_approved", "media.video_rendered"}
    again = close_previous_day(engine, settings)
    assert again["id"] == log["id"]
    with Session(engine) as session:
        assert session.scalars(select(ContinuityState)).all() == []  # nothing narrative here
