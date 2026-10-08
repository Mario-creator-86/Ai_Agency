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
from zoneinfo import ZoneInfo

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


#: Two lines of ten spoken words each: a beat of twenty, inside the brief's 8-22, and six
#: beats of them are 120 words, 48 seconds at the studio's 2.5 words a second.
SPOKEN = (
    "Right, where are we with the number this morning, everyone?",
    "The evidence first, then the opinion, and never the reverse.",
)


def parts_for(count: int) -> list[str]:
    """The brief's structure over ``count`` beats: hook first, button last, in order."""
    if count < 5:
        return ["hook", "situation", "turn", "payoff", "button"][:count]
    return ["hook"] + ["situation"] * (count - 4) + ["turn", "payoff", "button"]


def beats_for(
    event_ids: list[str], names: list[str], count: int = 6, location: str = "script_room"
) -> list[dict]:
    """A v3 episode's beats: the first two names speak, the rest stand in the first beat."""
    speakers = names[:2]
    beats = []
    for index, part in enumerate(parts_for(count)):
        beats.append(
            {
                "part": part,
                "location": location,
                "scene": f"The Content floor, scene {index + 1}: {names[0]} at the desk.",
                "lines": [
                    {"speaker": speakers[0], "text": SPOKEN[0]},
                    {"speaker": speakers[-1], "text": SPOKEN[1]},
                ],
                "background": names[2:] if index == 0 else [],
                "event_ids": [event_ids[index % len(event_ids)]],
            }
        )
    return beats


#: The plan for the next episode every answer carries (schema v3, since S6): required, so an
#: answer without it is refused before anything is stored.
NEXT = {
    "premise": "Kael finally brings the number before anyone asks for it.",
    "cold_open_line": "Before you say anything, I already have the number.",
    "open_question": "Will Sarah believe a number she did not ask for?",
    "threads_to_pay_off": [],
}


def episode_answer(beats, title="O zi la studio", **extra) -> str:
    body = {
        "title": title,
        "beats": beats,
        "summary": "Sarah a cerut numărul; Aris l-a adus.",
        "next_episode": NEXT,
    }
    body.update(extra)
    return json.dumps(body)


def fake_showrunner(monkeypatch, answer: str, seen: list[str] | None = None):
    from app.story import services

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        if seen is not None:
            seen.append(prompt)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    monkeypatch.setattr(services, "run_agent_task", fake_run)


#: The Director's rubric (review v2) with every part working: what a PASS carries.
RUBRIC = {"hook": 4, "situation": 4, "turn": 4, "payoff": 4, "voices": 4, "button": 4}


def fake_director(
    monkeypatch,
    verdict: str,
    notes: str = "",
    calls: list | None = None,
    scores: dict | None = RUBRIC,
):
    from app.story import review

    body = {"verdict": verdict, "reasons": ["motiv de test"], "notes": notes, "story": "o zi"}
    if scores is not None:
        body["scores"] = scores
    answer = json.dumps(body)

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        if calls is not None:
            calls.append(prompt)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    monkeypatch.setattr(review, "run_agent_task", fake_run)


def registry():
    return SimpleNamespace(
        registered_ids=lambda: ["fake-provider"],
        cached_status=lambda provider_id: "UNKNOWN",
        get=lambda provider_id: None,
    )


def allow_director_approval(engine, allowed: bool = True) -> None:
    """The state the Owner's publish-policy command leaves on Channel B, written directly:
    these are tests of the stage, not of the command (tests/test_publish_policy.py is)."""
    with Session(engine) as session, session.begin():
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        channel.director_may_approve_episodes = allowed


def YESTERDAY_NOON() -> datetime:  # noqa: N802 - read as a moment, like TZ
    """Noon of the studio's yesterday: the day the serial stage tells, which is over.

    The stage takes only a day before today (2026-09-19): today's log is closed at the end
    of every attempt, and a re-attempt used to film it before the day was over.
    """
    local = datetime.now(UTC).astimezone(ZoneInfo(TZ)) - timedelta(days=1)
    return local.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)


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

    assert set(checks) == {
        "grounding",
        "privacy",
        "length",
        "words_per_beat",
        "concentration",
        "language",
        "cast",
        "structure",
        "accessibility",
    }
    assert all(check["passed"] for check in checks.values()), checks
    assert 45 <= checks["length"]["seconds"] <= 70


def test_a_leaked_pattern_in_the_dialogue_fails_without_asking_the_model(
    engine, staffed, monkeypatch
):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    beats = beats_for(ids, names)
    beats[1]["lines"][0]["text"] = SPOKEN[0] + f" The key is {FAKE_KEY}."
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
    log, ids = a_day(engine, YESTERDAY_NOON())
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
    log, ids = a_day(engine, YESTERDAY_NOON())
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
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["approved"] == 0
    assert outcome["artefacts"]["storyboard_id"] is None
    assert "aprobarea" in outcome["reason"]


def test_today_closed_by_an_earlier_attempt_is_not_told_before_it_is_over(
    engine, staffed, settings, monkeypatch
):
    """Measured on 2026-09-19 by the verifier: the day's first attempt closed today's log at
    its end (daily_log), the clock re-attempted the day after a transient fault, and the
    serial stage of the second attempt took today's log as the newest closed day and filmed
    an episode of a day not yet over — a film the first attempt never decided on, bought on a
    re-attempt. The serial tells the day that is over, never today's."""
    allow_director_approval(engine)
    log, ids = a_day(engine)  # today, closed as a finished attempt closes it
    assert log["business_date"] == business_date(settings.timezone)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["episodes"] == 0, outcome
    with Session(engine) as session:
        assert session.scalars(select(StoryEpisode)).all() == []


def test_a_refusal_never_raises_and_a_provider_fault_is_transient(
    engine, staffed, settings, monkeypatch
):
    from app.runbook.services import TransientStageError
    from app.story import services

    a_day(engine, YESTERDAY_NOON())
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


# ---------------------------------------------------------------------------
# The stage resumes what an earlier run left, before it writes anything new
# ---------------------------------------------------------------------------
#
# Measured before this (2026-09-24): `pending_log` took only a closed day with no episode at
# all, so every episode already written was finished with as far as the stage knew. An
# episode the Owner approved by hand was never storyboarded, and never filmed; a Director's
# answer that could not be read lost the day for good; a draft waiting for the Owner was not
# named. The stage now asks, in order: an approved episode with no storyboard, a draft with
# no review, a draft passed and waiting for the Owner, and only then a new day.


def counting_director(monkeypatch, verdict: str, calls: list) -> None:
    fake_director(monkeypatch, verdict, notes="Primul beat nu se ține singur.", calls=calls)


def unreadable_director(monkeypatch, calls: list) -> None:
    """A Director whose answer is not a verdict: `review_episode` raises ReviewError."""
    from app.story import review

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        calls.append(prompt)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": "nu e un verdict"}

    monkeypatch.setattr(review, "run_agent_task", fake_run)


def episode_rows(engine) -> list[StoryEpisode]:
    with Session(engine) as session:
        rows = session.scalars(select(StoryEpisode).order_by(StoryEpisode.created_at)).all()
        session.expunge_all()
        return list(rows)


def storyboard_count(engine) -> int:
    with Session(engine) as session:
        return len(session.scalars(select(Storyboard)).all())


def waiting_for_the_owner(engine, monkeypatch, settings, when=None) -> tuple[dict, list, list]:
    """Yesterday written and passed, left for the Owner: the channel's default policy."""
    log, ids = a_day(engine, when or YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    written: list[str] = []
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), written)
    counting_director(monkeypatch, "PASS", reviewed)
    first = run_serial_stage(engine, registry(), settings)
    assert first["artefacts"]["approved"] == 0 and first["artefacts"]["written"] == 1, first
    return first, written, reviewed


def test_an_episode_the_owner_approved_is_storyboarded_by_the_next_run(
    engine, staffed, settings, monkeypatch
):
    first, written, reviewed = waiting_for_the_owner(engine, monkeypatch, settings)
    episode_id = first["artefacts"]["episode_id"]
    decide_episode(engine, episode_id, True, "")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["episode_id"] == episode_id
    assert artefacts["storyboard_id"]
    assert artefacts["written"] == artefacts["reviewed"] == 0
    assert len(written) == 1 and len(reviewed) == 1  # no model was asked again
    (row,) = episode_rows(engine)
    assert row.storyboard_id == artefacts["storyboard_id"]
    # What the media stage takes: an APPROVED serial storyboard whose story gate is open.
    with Session(engine) as session:
        board = session.get(Storyboard, row.storyboard_id)
        assert board.status == "APPROVED" and board.series_key == "office_serial"
        assert story_gate(session, board.script_draft_id) == (True, "")

    # And a third run writes nothing twice: the day has its episode, and its storyboard.
    again = run_serial_stage(engine, registry(), settings)
    assert again["artefacts"]["storyboard_id"] is None, again
    assert len(episode_rows(engine)) == 1 and storyboard_count(engine) == 1
    assert len(written) == 1 and len(reviewed) == 1


def test_an_approved_episode_is_storyboarded_even_without_a_language_model(
    engine, staffed, settings, monkeypatch
):
    """A storyboard is built from rows, not asked of a model: a studio whose models are down
    still readies the episode the Owner approved."""
    first, _, _ = waiting_for_the_owner(engine, monkeypatch, settings)
    decide_episode(engine, first["artefacts"]["episode_id"], True, "")

    outcome = run_serial_stage(engine, SimpleNamespace(registered_ids=list), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["storyboard_id"]


def test_a_review_that_could_not_be_read_is_asked_again_next_run(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    written: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), written)
    unreadable: list[str] = []
    unreadable_director(monkeypatch, unreadable)

    lost = run_serial_stage(engine, registry(), settings)

    assert lost["status"] == "COMPLETED" and "nu a putut fi citit" in lost["reason"], lost
    (draft,) = episode_rows(engine)
    assert draft.status == "DRAFT" and draft.review_json is None

    reviewed: list[str] = []
    counting_director(monkeypatch, "PASS", reviewed)
    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["episode_id"] == draft.id
    assert artefacts["written"] == 0 and artefacts["reviewed"] == 1
    assert artefacts["approved"] == 1 and artefacts["storyboard_id"]
    assert len(written) == 1 and len(reviewed) == 1
    (row,) = episode_rows(engine)
    assert row.status == "APPROVED" and row.storyboard_id == artefacts["storyboard_id"]


def test_a_resumed_draft_that_fails_gets_the_rewrite_the_day_had_left(
    engine, staffed, settings, monkeypatch
):
    """The day's budget is two drafts, counted over every run: a first draft read on the
    second run and failed is rewritten once, and a failed rewrite is the end of the day."""
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    written: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), written)
    unreadable_director(monkeypatch, [])
    run_serial_stage(engine, registry(), settings)

    reviewed: list[str] = []
    counting_director(monkeypatch, "FAIL", reviewed)
    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["artefacts"]["written"] == 1 and outcome["artefacts"]["rewritten"] == 1
    assert len(written) == 2 and len(reviewed) == 2
    assert "Primul beat nu se ține singur." in written[1]
    rows = episode_rows(engine)
    assert sorted(row.status for row in rows) == ["REJECTED", "REJECTED"]
    assert rows[1].rewrite_of_id == rows[0].id

    # The day is finished with: a third run writes and reads nothing more.
    run_serial_stage(engine, registry(), settings)
    assert len(written) == 2 and len(reviewed) == 2 and len(episode_rows(engine)) == 2


def test_a_draft_waiting_for_the_owner_is_named_and_no_new_episode_is_written(
    engine, staffed, settings, monkeypatch
):
    """The canon number moves only on his approval, so a second draft written beside the
    first would claim the same number. The stage names the one waiting and writes nothing."""
    first, written, reviewed = waiting_for_the_owner(
        engine, monkeypatch, settings, YESTERDAY_NOON() - timedelta(days=1)
    )
    a_day(engine, YESTERDAY_NOON())  # a newer day, closed, with no episode yet
    (draft,) = episode_rows(engine)

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert draft.title in outcome["reason"] and "aprobarea ta" in outcome["reason"]
    assert outcome["artefacts"]["episode_id"] == draft.id
    assert outcome["artefacts"]["written"] == outcome["artefacts"]["reviewed"] == 0
    assert len(written) == 1 and len(reviewed) == 1
    assert len(episode_rows(engine)) == 1


def test_a_draft_older_than_the_window_is_left_and_the_newest_day_is_told(
    engine, staffed, settings, monkeypatch
):
    """The shape of the Owner's own data on 2026-09-24: one DRAFT of 2026-09-12, written
    before the review existed and never read. A draft that old tells a day long gone; the
    stage does not spend a model on it, and does not wait on it."""
    old_log, old_ids = a_day(engine, YESTERDAY_NOON() - timedelta(days=12))
    names = roster_names(engine, old_log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(old_ids, names)))
    old = write_episode(engine, registry(), old_log["id"], str(uuid4()))["episode"]
    log, ids = a_day(engine, YESTERDAY_NOON())
    written: list[str] = []
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), written)
    counting_director(monkeypatch, "PASS", reviewed)

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["artefacts"]["written"] == 1, outcome
    assert outcome["artefacts"]["episode_id"] != old["id"]
    assert len(written) == 1 and len(reviewed) == 1  # the new day's draft, read once
    with Session(engine) as session:
        stale = session.get(StoryEpisode, old["id"])
        assert stale.status == "DRAFT" and stale.review_json is None
        newest = session.get(StoryEpisode, outcome["artefacts"]["episode_id"])
        assert newest.log_id == log["id"]


def test_the_owners_approval_readies_the_episode_for_filming(
    client, headers, engine, staffed, settings, monkeypatch
):
    """His approve button used to flip the status and stop: nothing ever filmed what he
    approved. The route now builds the storyboard the next run's media stage takes."""
    first, _, _ = waiting_for_the_owner(engine, monkeypatch, settings)
    episode_id = first["artefacts"]["episode_id"]

    response = client.post(
        f"/api/v1/story/episodes/{episode_id}/decide",
        json={"command_id": str(uuid4()), "approve": True},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED" and body["storyboard_id"]
    (row,) = episode_rows(engine)
    assert row.storyboard_id == body["storyboard_id"]
    # The next run finds nothing left to ready, and writes no second storyboard.
    outcome = run_serial_stage(engine, registry(), settings)
    assert outcome["artefacts"]["storyboard_id"] is None
    assert storyboard_count(engine) == 1


def test_the_owners_rejection_readies_nothing(
    client, headers, engine, staffed, settings, monkeypatch
):
    first, _, _ = waiting_for_the_owner(engine, monkeypatch, settings)

    response = client.post(
        f"/api/v1/story/episodes/{first['artefacts']['episode_id']}/decide",
        json={"command_id": str(uuid4()), "approve": False, "notes": "Tonul nu se potrivește."},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["storyboard_id"] is None
    assert storyboard_count(engine) == 0


# ---------------------------------------------------------------------------
# The missing days are closed, and the serial tells the newest real day
# ---------------------------------------------------------------------------
#
# Measured on the readers' copy of his database (2026-09-24): one closed log (2026-09-12),
# events up to 2026-09-19 13:43, and none since. Only yesterday was ever closed at a run's
# start, so a run today closed 2026-09-23 with nothing in it, the serial said "a quiet day"
# and the click made no episode; 2026-09-13..22 were never closed at all.


def NOON_DAYS_AGO(days: int) -> datetime:  # noqa: N802 - read as a moment, like TZ
    local = datetime.now(UTC).astimezone(ZoneInfo(TZ)) - timedelta(days=days)
    return local.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)


def date_days_ago(days: int) -> str:
    return business_date(TZ, NOON_DAYS_AGO(days))


def events_on(engine, when: datetime) -> list[str]:
    """Three public events on one day, not closed: the run closes it."""
    return [
        add_event(engine, "factual.topic_selected", when, {"title": "The Water of GJ 486 b"}),
        add_event(engine, "factual.script_approved", when, {"claims_count": 3}),
        add_event(engine, "media.video_rendered", when, {"file_size_bytes": 1}),
    ]


def cast_names(engine) -> list[str]:
    from app.agents.models import Agent

    with Session(engine) as session:
        return list(
            session.scalars(select(Agent.display_name).where(Agent.lifecycle != "TERMINATED"))
        )


def logged_dates(engine) -> list[str]:
    with Session(engine) as session:
        return sorted(session.scalars(select(DailyStudioLog.business_date)))


def test_one_run_closes_the_missing_days_and_tells_the_newest_real_one(
    engine, staffed, settings, monkeypatch, tmp_path
):
    """The plan's proof for S2: events on D-5 and none on D-1. One run closes D-5..D-1 and
    the episode is grounded in D-5, and the stage says which day it told."""
    import shutil

    from app.agents.models import ModelRecord
    from app.integrations.vault import CredentialVault
    from app.runbook.services import COMPLETED, STAGES, execute_daily_run

    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    with Session(engine) as session, session.begin():
        session.scalars(select(ModelRecord)).first().is_available = True
    allow_director_approval(engine)
    ids = events_on(engine, NOON_DAYS_AGO(5))
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, cast_names(engine))))
    fake_director(monkeypatch, "PASS")

    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}
    runners["serial_queue"] = lambda: run_serial_stage(engine, registry(), settings)
    result = execute_daily_run(
        engine, settings, CredentialVault(tmp_path / "k.key"), stage_runners=runners
    )

    told = date_days_ago(5)
    closed = logged_dates(engine)
    assert [date_days_ago(d) for d in (5, 4, 3, 2, 1)] == closed[:5], closed
    previous = result["stages"][0]["artefacts"]["previous_day_log"]
    assert previous["business_date"] == date_days_ago(1)
    assert told in previous["days_closed"]
    serial = next(s for s in result["stages"] if s["stage"] == "serial_queue")
    assert serial["status"] == COMPLETED, serial
    assert told in serial["reason"], serial["reason"]
    assert serial["artefacts"]["told_date"] == told
    (episode,) = episode_rows(engine)
    with Session(engine) as session:
        assert session.get(DailyStudioLog, episode.log_id).business_date == told
    assert set(episode.grounded_event_ids_json) <= set(ids)
    assert episode.storyboard_id


def test_the_missing_days_are_closed_a_week_back_and_no_further(engine, staffed, settings):
    from app.story.services import CLOSE_WINDOW_DAYS, close_missing_days

    add_event(engine, "factual.script_approved", NOON_DAYS_AGO(10))
    add_event(engine, "factual.script_approved", NOON_DAYS_AGO(3))

    closed = close_missing_days(engine, settings)

    window = [date_days_ago(d) for d in range(CLOSE_WINDOW_DAYS, 0, -1)]
    assert CLOSE_WINDOW_DAYS == 7
    assert [log["business_date"] for log in closed] == window
    assert logged_dates(engine) == window
    # Closing again closes nothing new: a closed log never changes, and is not made twice.
    assert close_missing_days(engine, settings) == []
    assert logged_dates(engine) == window


def test_no_log_is_made_for_a_day_before_the_studio_had_any_event(engine, staffed, settings):
    """A studio started today has no past to close: an empty log for a day before its first
    event would be a record of nothing, and a date the serial would call quiet."""
    from app.story.services import close_missing_days

    add_event(engine, "factual.script_approved", NOON_DAYS_AGO(2))

    closed = close_missing_days(engine, settings)

    assert [log["business_date"] for log in closed] == [date_days_ago(2), date_days_ago(1)]


def test_a_quiet_yesterday_hands_the_serial_the_newest_day_that_happened(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    ids = events_on(engine, NOON_DAYS_AGO(3))
    for days in (3, 2, 1):
        close_daily_log(engine, TZ, date_days_ago(days))
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, cast_names(engine))))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["told_date"] == date_days_ago(3)
    assert outcome["artefacts"]["written"] == 1
    # The reason names the day told and the quiet days it passed over.
    for days in (3, 2, 1):
        assert date_days_ago(days) in outcome["reason"], outcome["reason"]


def test_an_older_day_is_never_told_after_a_newer_one(engine, staffed, settings, monkeypatch):
    """Canon runs forward: once D-2 has had its episode, an untold D-3 is not told after it,
    even when D-1 is quiet. The serial would otherwise show Tuesday after Wednesday."""
    older = events_on(engine, NOON_DAYS_AGO(3))
    newer = events_on(engine, NOON_DAYS_AGO(2))
    for days in (3, 2, 1):
        close_daily_log(engine, TZ, date_days_ago(days))
    with Session(engine) as session:
        told_log = session.scalars(
            select(DailyStudioLog).where(DailyStudioLog.business_date == date_days_ago(2))
        ).one()
        told_id = told_log.id
    fake_showrunner(monkeypatch, episode_answer(beats_for(newer, cast_names(engine))))
    written = write_episode(engine, registry(), told_id, str(uuid4()))
    decide_episode(engine, written["episode"]["id"], False, "Not this one.")
    seen: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(older, cast_names(engine))), seen)

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["written"] == 0 and seen == []
    assert "liniștită" in outcome["reason"]


# ---------------------------------------------------------------------------
# The writer gets the day's story, not its tail
# ---------------------------------------------------------------------------
#
# Measured before this (2026-09-24): the projection kept the chronologically last 40 public
# events, so a day of 993 events handed the showrunner the evening's "a stage of the day
# ended" lines and none of the morning's choices; each line was a Romanian template with no
# title, no reason and no claim; and a model name with no known shape ("seedream5_pro",
# "kimi-k3") passed the redaction whole.


@pytest.mark.parametrize(
    "name",
    [
        "seedream5_pro",
        "seedance2_5",
        "seedance2_mini",
        "kimi-k3",
        "kimi-k2.6:cloud",
        "minimax-m3",
        "gemma4:31b",
        "nemotron-3-super",
        "deepseek-v4-pro:0813",
    ],
)
def test_the_models_the_studio_uses_are_redacted(name):
    cleaned = redact(f"Kael tested {name} this morning")
    assert name not in cleaned
    family = name.replace(":", "-").replace("_", "-").split("-")[0].rstrip("0123456789")
    assert family not in cleaned.lower(), cleaned
    assert cleaned.startswith("Kael tested")
    assert cleaned.endswith("this morning")


def test_a_model_in_the_studios_own_records_is_redacted_whatever_its_shape(engine, staffed):
    from app.agents.models import ModelRecord

    with Session(engine) as session, session.begin():
        provider_id = session.scalars(select(ModelRecord)).first().provider_id
        session.add(
            ModelRecord(
                id=str(uuid4()),
                provider_id=provider_id,
                model_name="novamind",
                discovery_method="MANUAL",
                context_length=None,
                last_verified=None,
                is_available=False,
                notes="",
            )
        )
    event_id = add_event(
        engine,
        "agent.message_posted",
        aggregate_type="agent_message",
        payload={
            "from_name": "Kael (Video Editor)",
            "to_name": "Director",
            "for_owner": False,
            "subject": "Model research (image): novamind",
        },
    )
    log = close_daily_log(engine, TZ)

    assert "novamind" not in projected(log, event_id)["description"].lower()


def _bulk(engine, rows: list[tuple[str, datetime, dict, str, str]]) -> list[str]:
    ids = []
    with Session(engine) as session, session.begin():
        for event_type, when, payload, aggregate_type, aggregate_id in rows:
            event_id = str(uuid4())
            ids.append(event_id)
            session.add(
                DomainEvent(
                    event_id=event_id,
                    event_type=event_type,
                    timestamp=when.astimezone(UTC).isoformat(),
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    aggregate_version=1,
                    correlation_id=str(uuid4()),
                    causation_id=None,
                    schema_version=1,
                    visibility="OWNER",
                    payload=payload,
                )
            )
    return ids


def a_long_day(engine) -> dict:
    """993 events on one closed day: the morning's story, then the day's routine."""
    from app.factual.models import FactualClaim

    morning = NOON_DAYS_AGO(1) - timedelta(hours=6)
    claim_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            FactualClaim(
                id=claim_id,
                claim_text="The planet has an ocean of liquid water.",
                created_at=utc_now(),
            )
        )
    story = _bulk(
        engine,
        [
            (
                "factual.topic_selected",
                morning,
                {"title": "The Water of GJ 486 b", "supported_claims": 4},
                "topic_idea",
                str(uuid4()),
            ),
            (
                "factual.topic_refused",
                morning + timedelta(minutes=1),
                {"title": "Moon Dust Myths", "reasons": ["no payoff", "no hook"]},
                "topic_idea",
                str(uuid4()),
            ),
            (
                "factual.claim_verified",
                morning + timedelta(minutes=2),
                {"status": "REFUTED", "confidence": 0.9},
                "factual_claim",
                claim_id,
            ),
            (
                "factual.story_reviewed",
                morning + timedelta(minutes=3),
                {"verdict": "REVISE", "failed": ["the first beat does not stand alone"]},
                "script_draft",
                str(uuid4()),
            ),
        ],
    )
    routine: list[tuple[str, datetime, dict, str, str]] = []
    later = morning + timedelta(hours=1)
    for index in range(900):
        routine.append(
            (
                "runbook.stage_finished",
                later + timedelta(seconds=index),
                {"stage": "research", "status": "COMPLETED"},
                "daily_run",
                str(uuid4()),
            )
        )
    for index in range(60):
        routine.append(
            (
                "factual.claim_verified",
                later + timedelta(seconds=1000 + index),
                {"status": "SUPPORTED"},
                "factual_claim",
                str(uuid4()),
            )
        )
    for index in range(29):
        routine.append(
            (
                "agent.message_answered",
                later + timedelta(seconds=2000 + index),
                {"subject": f"Re: note {index}"},
                "agent_message",
                str(uuid4()),
            )
        )
    _bulk(engine, routine)
    log = close_daily_log(engine, TZ, date_days_ago(1))
    assert log["total_events"] == 993
    return {"log": log, "story": story}


def test_a_long_day_keeps_its_story_not_its_tail(engine, staffed):
    day = a_long_day(engine)
    projection = day["log"]["narrative_projection"]
    kept = {item["event_id"] for item in projection}

    assert 5 <= len(projection) <= 15
    assert set(day["story"]) <= kept, [i["event_type"] for i in projection]
    # Sixty identical checks are one line that says how many there were.
    supported = [
        i
        for i in projection
        if i["event_type"] == "factual.claim_verified" and i["event_id"] not in day["story"]
    ]
    assert len(supported) == 1 and supported[0]["repeats"] == 60
    assert "60" in supported[0]["description"]
    # Five story lines, and the routine collapsed into the two lines that say how many
    # stages ended and letters were answered: fewer than eight, because that is all there is.
    assert len(projection) == 7
    assert sum(item.get("repeats", 1) for item in projection) == 993
    # In the order the day happened, so the writer reads a day and not a ranking.
    moments = [item["at"] for item in projection]
    assert moments == sorted(moments)


def test_the_story_keys_carry_the_substance_in_english(engine, staffed):
    day = a_long_day(engine)
    by_id = {item["event_id"]: item for item in day["log"]["narrative_projection"]}
    chosen, refused, refuted, reviewed = (by_id[i] for i in day["story"])

    assert chosen["title"] == "The Water of GJ 486 b"
    assert "The Water of GJ 486 b" in chosen["description"]
    assert refused["title"] == "Moon Dust Myths" and refused["reason"] == "no payoff"
    assert "no payoff" in refused["description"]
    assert refuted["claim"] == "The planet has an ocean of liquid water."
    assert "ocean of liquid water" in refuted["description"]
    assert reviewed["reason"] == "the first beat does not stand alone"
    assert reviewed["verdict"] == "REVISE"
    romanian = ("a fost", "un angajat", "o temă", "Directorul", "scenariul", "etapă")
    for item in by_id.values():
        assert not any(word in item["description"] for word in romanian), item["description"]


def test_a_letter_between_employees_names_both_and_its_subject(engine, staffed):
    event_id = add_event(
        engine,
        "agent.message_posted",
        aggregate_type="agent_message",
        payload={
            "from_agent_id": None,
            "from_name": "Sarah (Director)",
            "to_name": "Kael (Video Editor)",
            "for_owner": False,
            "subject": "ITERATE: two renders failed",
        },
    )
    log = close_daily_log(engine, TZ)

    item = projected(log, event_id)
    assert item["description"] == (
        'Sarah (Director) wrote to Kael (Video Editor): "ITERATE: two renders failed"'
    )
    assert item["actor"] == "Sarah (Director)"


def _stage_report(engine, when: datetime, stage: str, reporter: str, reason: str) -> str:
    """A letter as `file_stage_reports` posts it at the end of every run: one per stage,
    from the stage's owner to the Director's desk, its subject the stage's own outcome."""
    return add_event(
        engine,
        "agent.message_posted",
        when,
        {
            "intent": "STATUS",
            "subject": f"{stage}: COMPLETED — {reason}",
            "from_name": reporter,
            "to_agent_id": None,
            "to_name": "Director",
            "for_owner": False,
        },
        "agent_message",
    )


def test_the_runs_own_stage_reports_are_routine_and_its_film_is_the_story(engine, staffed):
    """Rehearsal on a copy of his data (2026-09-24): on the second day the fifteen lines the
    writer was handed were the run's fifteen end-of-run reports, one per stage, and the
    episode that was filmed and published that morning was not among them."""
    when = NOON_DAYS_AGO(2)
    story = [
        add_event(engine, "media.storyboard_created", when, {"title": "The record, read twice"}),
        add_event(engine, "media.video_rendered", when + timedelta(minutes=1), {}),
        add_event(
            engine,
            "publishing.video_published_simulated",
            when + timedelta(minutes=2),
            {"title": "The record, read twice | Inside The Nexus Ep. 2"},
        ),
    ]
    for index, stage in enumerate(
        ("performance_intake", "idea_generation", "research_and_verification", "selection")
        + ("script_and_storyboard", "serial_queue", "media", "edit_and_qc", "publish")
        + ("post_run", "serial_next", "books", "daily_log", "preflight", "analytics")
    ):
        _stage_report(
            engine, when + timedelta(minutes=10 + index), stage, "Lyra (Voice Artist)", "gata."
        )

    log = close_daily_log(engine, TZ, date_days_ago(2))

    projection = log["narrative_projection"]
    kept = {item["event_id"] for item in projection}
    assert set(story) <= kept, [item["description"] for item in projection]
    # The reports only fill a short day up to its eight lines, as the stages ending do.
    assert len(projection) == 8, [item["description"] for item in projection]


def test_a_note_to_the_directors_own_desk_is_not_a_letter_to_a_stranger(engine, staffed):
    """A letter to the Director's desk was projected as '... wrote to Director', and hers
    as 'Sarah (Director) wrote to Director': a writer reads two people where there is one."""
    own = add_event(
        engine,
        "agent.message_posted",
        payload={
            "intent": "STATUS",
            "subject": "Vizionare: APPROVE — The record, read twice",
            "from_name": "Sarah (Director)",
            "to_agent_id": None,
            "to_name": "Director",
        },
        aggregate_type="agent_message",
    )
    other = add_event(
        engine,
        "agent.message_posted",
        payload={
            "intent": "STATUS",
            "subject": "Publication READY: The record, read twice",
            "from_name": "Vera (Publisher)",
            "to_agent_id": None,
            "to_name": "Director",
        },
        aggregate_type="agent_message",
    )
    log = close_daily_log(engine, TZ)

    assert projected(log, own)["description"] == (
        'Sarah (Director) noted: "Vizionare: APPROVE — The record, read twice"'
    )
    assert projected(log, other)["description"] == (
        'Vera (Publisher) wrote to Sarah (Director): "Publication READY: The record, read twice"'
    )


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Ziua povestită: 2026-09-19.", True),
        ("The 1969 landing, told again.", True),
        ("The card ends in 4242.", False),
        ("Account 4111111111111111 was charged.", False),
        ("Order 12345 shipped.", False),
    ],
)
def test_a_year_is_not_an_account_number(text, kept):
    """'[redacted]-09-25' reached the writer (rehearsal, 2026-09-24): every four-digit run
    was read as an account number, a date's year included, and a line naming a year failed
    the review's privacy check."""
    assert (redact(text) == text) is kept, redact(text)


def test_a_day_of_routine_alone_has_nothing_to_tell(engine, staffed):
    """A day where only stages ended and letters were answered is a quiet day: the serial
    goes back to the newest day that happened rather than dramatise the machinery."""
    when = NOON_DAYS_AGO(2)
    add_event(engine, "runbook.stage_finished", when, {"stage": "research", "status": "COMPLETED"})
    add_event(engine, "agent.message_answered", when, {"subject": "Re: the brief"})

    log = close_daily_log(engine, TZ, date_days_ago(2))

    assert log["narrative_projection"] == []


def test_a_stage_that_failed_is_story_not_routine(engine, staffed):
    when = NOON_DAYS_AGO(2)
    failed = add_event(
        engine, "runbook.stage_finished", when, {"stage": "media", "status": "FAILED"}
    )

    log = close_daily_log(engine, TZ, date_days_ago(2))

    assert [item["event_id"] for item in log["narrative_projection"]] == [failed]


def test_a_short_day_is_filled_to_eight_with_its_routine(engine, staffed):
    when = NOON_DAYS_AGO(2)
    story = add_event(engine, "factual.topic_selected", when, {"title": "The Water of GJ 486 b"})
    for index in range(12):
        add_event(
            engine,
            "runbook.stage_finished",
            when + timedelta(minutes=index + 1),
            {"stage": f"stage{chr(97 + index)}", "status": "COMPLETED"},
        )

    log = close_daily_log(engine, TZ, date_days_ago(2))

    projection = log["narrative_projection"]
    assert len(projection) == 8
    assert story in {item["event_id"] for item in projection}


def a_crowded_day(engine) -> tuple[dict, list[str]]:
    """Three hires and twenty proposed topics: more story than fifteen lines hold."""
    when = NOON_DAYS_AGO(2)
    hires = [
        add_event(
            engine,
            "agent.hired",
            when + timedelta(minutes=index),
            {"display_name": f"Hire {chr(65 + index)}", "role": "Editor"},
        )
        for index in range(3)
    ]
    for index in range(20):
        add_event(
            engine,
            "factual.topic_proposed",
            when + timedelta(minutes=10 + index),
            {"title": f"Idea number {chr(65 + index)}"},
        )
    return close_daily_log(engine, TZ, date_days_ago(2)), hires


def test_a_crowded_day_keeps_fifteen_by_weight(engine, staffed):
    log, hires = a_crowded_day(engine)

    projection = log["narrative_projection"]
    assert len(projection) == 15
    assert set(hires) <= {item["event_id"] for item in projection}


def test_the_writer_is_told_how_much_of_the_day_was_left_out(engine, staffed, monkeypatch):
    from app.story.projection import classify_event_type

    log, hires = a_crowded_day(engine)
    projection = log["narrative_projection"]
    public = sum(n for t, n in log["event_counts"].items() if classify_event_type(t) == PUBLIC_SAFE)
    shown = sum(item.get("repeats", 1) for item in projection)
    seen: list[str] = []
    fake_showrunner(
        monkeypatch, episode_answer(beats_for(hires, roster_names(engine, log["id"]))), seen
    )

    write_episode(engine, registry(), log["id"], str(uuid4()))

    (prompt,) = seen
    assert public - shown == 8
    assert "8 more public events" in prompt
    for item in projection:
        assert item["event_id"] in prompt


# ---------------------------------------------------------------------------
# The showrunner's brief, v3: lines people say, not a script one voice reads
# ---------------------------------------------------------------------------
#
# Measured before this (2026-09-24): the dialogue was free text with the speakers' names in
# it, and the storyboard handed it whole to one voice, so "Sarah: (sighs)" was read aloud;
# the brief was Romanian, called the day "azi", forced all eight employees into every
# episode, asked for no hook, turn or payoff, and one wrong spelling of a name refused the
# day with no second try.

#: The two people who act in `letters_day`'s events.
SARAH, KAEL = "Sarah (Director)", "Kael (Video Editor)"


def letters_day(engine, when: datetime | None = None) -> tuple[dict, list[str]]:
    """A closed day with people in its events: two letters between Sarah and Kael, and the
    topic chosen. Returns the log and the three event ids."""
    ids = [
        add_event(
            engine,
            "agent.message_posted",
            when,
            {"from_name": SARAH, "to_name": KAEL, "subject": "The cut runs long"},
            aggregate_type="agent_message",
        ),
        add_event(
            engine,
            "agent.message_posted",
            when,
            {"from_name": KAEL, "to_name": SARAH, "subject": "Re: The cut runs long"},
            aggregate_type="agent_message",
        ),
        add_event(engine, "factual.topic_selected", when, {"title": "The Water of GJ 486 b"}),
    ]
    log = close_daily_log(engine, TZ, business_date(TZ, when) if when else None)
    return log, ids


def answers_in_turn(monkeypatch, answers: list[str], seen: list[str]) -> None:
    """A showrunner who gives these answers in order, the last one from then on."""
    from app.story import services

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        seen.append(prompt)
        answer = answers[min(len(seen), len(answers)) - 1]
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    monkeypatch.setattr(services, "run_agent_task", fake_run)


def inside_a_boundary(prompt: str, text: str) -> bool:
    """Whether ``text`` stands inside one of the prompt's inert data blocks."""
    blocks = prompt.split("<untrusted_source_evidence")[1:]
    return any(text in block.split("</untrusted_source_evidence>")[0] for block in blocks)


def written(engine, monkeypatch, beats, seen: list[str] | None = None, **extra) -> dict:
    """The newest closed day's episode, written from these beats."""
    fake_showrunner(monkeypatch, episode_answer(beats, title="The Cut Runs Long", **extra), seen)
    with Session(engine) as session:
        log_id = session.scalars(
            select(DailyStudioLog.id).order_by(DailyStudioLog.business_date.desc())
        ).first()
    return write_episode(engine, registry(), log_id, str(uuid4()))["episode"]


def checks_of(engine, episode_id: str) -> dict:
    with Session(engine) as session:
        return episode_checks(session, session.get(StoryEpisode, episode_id))


def test_a_v3_answer_is_stored_as_lines_with_nothing_but_speech(engine, staffed, monkeypatch):
    from app.story.services import EPISODE_TEMPLATE_VERSION

    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["lines"][0]["text"] = f"Sarah: (sighs) {SPOKEN[0]}"
    beats[0]["lines"][1]["direction"] = "without looking up"

    episode = written(engine, monkeypatch, beats)

    first = episode["beats"][0]
    assert first["part"] == "hook" and first["location"] == "script_room"
    assert first["lines"][0] == {"speaker": SARAH, "text": SPOKEN[0], "direction": "sighs"}
    assert first["lines"][1] == {
        "speaker": KAEL,
        "text": SPOKEN[1],
        "direction": "without looking up",
    }
    # What a voice reads is the words alone: no name, no colon, no stage direction.
    assert first["dialogue"] == f"{SPOKEN[0]}\n{SPOKEN[1]}"
    assert first["speakers"] == [SARAH, KAEL]
    assert episode["continuity"]["template_version"] == EPISODE_TEMPLATE_VERSION
    checks = checks_of(engine, episode["id"])
    assert all(check["passed"] for check in checks.values()), checks


def test_a_short_name_is_normalised_to_the_roster_name(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    beats = beats_for(ids, ["Sarah", "kael"])
    beats[0]["background"] = ["Aris", "Sarah Executive"]

    episode = written(engine, monkeypatch, beats)

    assert episode["beats"][0]["speakers"] == [SARAH, KAEL]
    # Sarah speaks in the beat, so she is not also counted as standing in its background.
    assert episode["beats"][0]["background"] == ["Dr. Aris (Researcher)"]
    assert episode["beats"][0]["characters"] == [SARAH, KAEL, "Dr. Aris (Researcher)"]


def test_a_name_outside_the_roster_is_rewritten_within_the_days_budget(
    engine, staffed, settings, monkeypatch
):
    """One wrong name used to lose the day. The refusal is now a draft spent: the writer is
    told why and shown what was refused, and the day's second draft is written."""
    _, ids = letters_day(engine, YESTERDAY_NOON())
    prompts: list[str] = []
    answers_in_turn(
        monkeypatch,
        [
            episode_answer(beats_for(ids, [SARAH, "Bob the Intern"]), title="Who Is Bob"),
            episode_answer(beats_for(ids, [SARAH, KAEL]), title="The Cut Runs Long"),
        ],
        prompts,
    )
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["refused"] == 1 and outcome["artefacts"]["written"] == 1
    assert len(prompts) == 2
    assert "nu era" in prompts[1]  # why the first answer was refused
    assert inside_a_boundary(prompts[1], "Bob the Intern")  # and what it was, as data
    (row,) = episode_rows(engine)
    assert row.title == "The Cut Runs Long"


def test_two_refused_answers_end_the_day_with_nothing_stored(
    engine, staffed, settings, monkeypatch
):
    _, ids = letters_day(engine, YESTERDAY_NOON())
    prompts: list[str] = []
    answers_in_turn(
        monkeypatch, [episode_answer(beats_for(ids, [SARAH, "Bob the Intern"]))], prompts
    )

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert len(prompts) == 2  # the budget is MAX_DRAFTS, and a refusal spends one
    assert outcome["artefacts"]["refused"] == 2 and outcome["artefacts"]["written"] == 0
    assert "nu era" in outcome["artefacts"]["refusal"]
    assert episode_rows(engine) == []


@pytest.mark.parametrize(
    "threads",
    [
        {"threads_opened": ["<one question this episode leaves open, or nothing>"]},
        {"threads_opened": ["o întrebare nouă"]},
        {"threads_opened": ["..."]},
        {"recurring": ["o glumă sau un obiect care revine"]},
        {"threads_continued": ["T1"]},  # the format's example, with no thread open
    ],
)
def test_a_placeholder_thread_is_refused(engine, staffed, monkeypatch, threads):
    from app.story.services import DraftRefused

    _, ids = letters_day(engine)

    with pytest.raises(DraftRefused):
        written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), **threads)

    assert episode_rows(engine) == []


def test_thread_ids_are_checked_against_the_open_threads(engine, staffed, monkeypatch):
    from app.story.services import DraftRefused

    _, ids = letters_day(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ContinuityState(
                id=1,
                version=2,
                canon_episode_number=1,
                threads_json=[{"id": "T1", "text": "Who brings the number?", "opened_in": 1}],
                recurring_json=[],
                summaries_json=[],
                updated_at=utc_now(),
            )
        )

    with pytest.raises(DraftRefused) as refused:
        written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), threads_closed=["T9"])
    assert "T9" in str(refused.value)

    episode = written(
        engine,
        monkeypatch,
        beats_for(ids, [SARAH, KAEL]),
        threads_closed=["T1: who brings the number"],
    )
    assert episode["continuity"]["threads_closed"] == ["T1"]


def test_the_rewrite_is_shown_the_draft_the_director_refused(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    _, ids = letters_day(engine, YESTERDAY_NOON())
    prompts: list[str] = []
    answers_in_turn(
        monkeypatch,
        [
            episode_answer(beats_for(ids, [SARAH, KAEL]), title="The First Cut"),
            episode_answer(beats_for(ids, [SARAH, KAEL]), title="The Second Cut"),
        ],
        prompts,
    )
    fake_director(monkeypatch, "FAIL", notes="The turn comes too late.")

    run_serial_stage(engine, registry(), settings)

    assert len(prompts) == 2
    assert "The turn comes too late." in prompts[1]
    assert inside_a_boundary(prompts[1], "The First Cut")
    assert inside_a_boundary(prompts[1], SPOKEN[0])  # its lines, not only its title
    assert "The First Cut" not in prompts[0]


def test_the_brief_names_the_day_the_names_the_rooms_and_the_voices(engine, staffed, monkeypatch):
    log, ids = letters_day(engine)
    seen: list[str] = []

    written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), seen)

    (prompt,) = seen
    assert log["business_date"] in prompt
    names = roster_names(engine, log["id"])
    assert "ALLOWED_NAMES: " + json.dumps(names, ensure_ascii=False) in prompt
    for location in ("director_suite", "script_room", "video_studio", "lobby"):
        assert location in prompt
    assert "no written text" in prompt.lower()
    for part in ("hook", "situation", "turn", "payoff", "button"):
        assert f'"{part}"' in prompt
    assert "8 to 22 spoken words" in prompt
    # Her voice, from her bible: the register and a phrase of hers.
    assert "executive briefing" in prompt and "Right. Where are we?" in prompt
    # The day's events and the serial's memory are data, inside the boundary.
    assert inside_a_boundary(prompt, ids[0])
    assert inside_a_boundary(prompt, "This is the first episode")
    # Who acts in an event is told with it, so the writer can cast from the record.
    assert inside_a_boundary(prompt, f'"who": ["{SARAH}", "{KAEL}"]')
    # The brief is English, and names the day instead of calling it "azi".
    for romanian in ("DISTRIBUȚIA", "EVENIMENTELE", " azi", "Răspunde"):
        assert romanian not in prompt


def test_the_writer_counts_spoken_words_after_reading_a_short_refused_draft(
    engine, staffed, monkeypatch
):
    from app.story.services import EPISODE_WORDS, WORDS_PER_BEAT

    _, ids = letters_day(engine)
    first = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]))
    prompts: list[str] = []
    answers_in_turn(monkeypatch, [episode_answer(beats_for(ids, [SARAH, KAEL]))], prompts)
    write_episode(
        engine,
        registry(),
        first["log_id"],
        str(uuid4()),
        notes="The previous draft had only 46 spoken words; expand the dialogue.",
        rewrite_of=first["id"],
    )
    (prompt,) = prompts
    # The measurement excludes scene directions and must still be obeyed on a rewrite.
    tail = prompt[prompt.rfind("</untrusted_source_evidence>") :]
    assert f"{EPISODE_WORDS[0]} to {EPISODE_WORDS[1]}" in tail
    assert f"{WORDS_PER_BEAT[0]} to {WORDS_PER_BEAT[1]}" in tail
    assert "Only words inside lines[].text count" in tail
    assert "first line" in tail and "whole hook beat" in tail


def test_the_speaking_cast_is_two_to_four_who_act_in_the_cited_events(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    nadia = "Nadia (Accountant)"

    stranger = written(engine, monkeypatch, beats_for(ids, [SARAH, nadia]))
    checks = checks_of(engine, stranger["id"])
    assert checks["cast"]["passed"] is False
    assert nadia in checks["cast"]["reason"]

    alone = written(engine, monkeypatch, beats_for(ids, [SARAH]))
    assert checks_of(engine, alone["id"])["cast"]["passed"] is False

    crowd = beats_for(ids, [SARAH, KAEL])
    everyone = [SARAH, KAEL, "Dr. Aris (Researcher)", nadia, "Vera (Publisher)"]
    crowd[1]["lines"] = [{"speaker": name, "text": "Four words each here."} for name in everyone]
    assert checks_of(engine, written(engine, monkeypatch, crowd)["id"])["cast"]["passed"] is False

    # Only the two who acted speak, the rest of the studio in the background: that passes.
    both = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL, nadia]))
    assert checks_of(engine, both["id"])["cast"]["passed"] is True


def test_the_structure_runs_from_hook_to_button_in_the_studios_rooms(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)

    no_turn = beats_for(ids, [SARAH, KAEL])
    no_turn[3]["part"] = "situation"
    checks = checks_of(engine, written(engine, monkeypatch, no_turn)["id"])
    assert checks["structure"]["passed"] is False
    assert "turn" in checks["structure"]["reason"]

    elsewhere = beats_for(ids, [SARAH, KAEL], location="the moon base")
    checks = checks_of(engine, written(engine, monkeypatch, elsewhere)["id"])
    assert checks["structure"]["passed"] is False
    assert "the moon base" in checks["structure"]["reason"]


def test_the_storyboard_reads_the_lines_and_speaks_no_label(engine, staffed, monkeypatch):
    from app.media.models import CharacterBible

    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH])
    beats[0]["lines"][0]["text"] = f"Kael: [quietly] {SPOKEN[0]}"
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")

    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))

    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        first = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board_id)
            .order_by(StoryboardScene.scene_index)
        ).first()
        kael = session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name.like("Kael%"))
        )
        assert first.voiceover_segment == f"{SPOKEN[0]}\n{SPOKEN[1]}"
        assert "Kael:" not in script.voiceover_full_text
        assert "[" not in script.voiceover_full_text
        # The first speaker's bible comes first, so the voice bound is the one who speaks.
        assert first.character_ids_json[0] == kael.id
        assert script.scenes_json[0]["lines"][0] == {
            "speaker": KAEL,
            "text": SPOKEN[0],
            "direction": "quietly",
        }
        assert "Content" in first.visual_prompt  # the room, from the headquarters


def test_an_old_v2_episode_is_still_filmed_without_its_labels(engine, staffed, monkeypatch):
    """Episodes written before the lines existed keep their free dialogue. They are read
    with the names the day's roster knows taken off the front and the stage directions
    out, so a v2 episode never makes a voice say "Sarah:" either."""
    log, ids = a_day(engine)
    episode_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = session.scalars(select(DomainEvent)).first()
        session.add(
            StoryEpisode(
                id=episode_id,
                log_id=log["id"],
                title="An Old Episode",
                beats_json=[
                    {
                        "beat_number": 1,
                        "scene": "The Content floor, morning light.",
                        "dialogue": "Sarah (Director): Right. Where are we?\n"
                        "Kael: (sighs) The render is running, do not touch it.",
                        "event_ids": [ids[0]],
                        "characters": [SARAH, KAEL],
                    },
                    {
                        "beat_number": 2,
                        "scene": "The lobby at noon.",
                        "dialogue": "The day went on without anyone noticing the cup.",
                        "event_ids": [ids[1]],
                        "characters": [],
                    },
                ],
                grounded_event_ids_json=ids[:2],
                continuity_json={"episode_number": 1},
                status="APPROVED",
                created_at=utc_now(),
                event_id=event.event_id,
                reviewed_by="owner",
            )
        )

    board_id = storyboard_from_episode(engine, episode_id, str(uuid4()))

    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        first, second = script.scenes_json
        assert [line["speaker"] for line in first["lines"]] == [SARAH, KAEL]
        assert first["lines"][1]["direction"] == "sighs"
        assert first["narration"] == "Right. Where are we?\nThe render is running, do not touch it."
        # A line with no name on it is the narrator's.
        assert second["lines"] == [
            {"speaker": None, "text": "The day went on without anyone noticing the cup."}
        ]


def test_the_script_writers_contract_carries_the_serial_brief():
    from app.agents.identity import load_role_contracts

    contract = load_role_contracts().roles["ScriptWriter"]
    lines = " ".join(contract.watch_for + contract.never_let_pass)
    assert "write_episode" in lines
    assert "2-4 speaking characters" in lines


def test_a_thread_list_that_says_nothing_is_empty_not_refused(engine, staffed, monkeypatch):
    """The brief says "or nothing"; a model that writes the word is not copying the format."""
    _, ids = letters_day(engine)

    episode = written(
        engine,
        monkeypatch,
        beats_for(ids, [SARAH, KAEL]),
        threads_opened=["none"],
        recurring=["Nothing."],
        threads_continued=["n/a"],
    )

    continuity = episode["continuity"]
    assert continuity["threads_opened"] == continuity["recurring"] == []
    assert continuity["threads_continued"] == []


def test_a_name_a_line_addresses_is_said_not_taken_for_a_label(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["lines"][0]["text"] = "Kael - the render is late, and so is the coffee."

    episode = written(engine, monkeypatch, beats)

    assert episode["beats"][0]["lines"][0]["text"] == (
        "Kael - the render is late, and so is the coffee."
    )


# ---------------------------------------------------------------------------
# The Director reads what each beat cites (episode review v2)
# ---------------------------------------------------------------------------
#
# Measured before this (2026-09-24): the Director judged an episode without seeing the
# events it dramatises, so an outcome no event holds could pass; her facts were cut at
# 14,000 characters in the middle of the JSON; the one episode on his data cites the same
# event in all eight beats, and nothing computed counted it; nothing checked that the lines
# are English before a paid render; and a PASS carried no scores, so "good" meant nothing
# anyone could compare.


def stored_episode(engine, log_id: str, beats: list[dict], title: str, cited: list[str]) -> str:
    """An episode row written straight to the table, as the old code wrote the one on his
    data: the review reads what is stored, whatever wrote it."""
    episode_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = session.scalars(select(DomainEvent)).first()
        session.add(
            StoryEpisode(
                id=episode_id,
                log_id=log_id,
                title=title,
                beats_json=beats,
                grounded_event_ids_json=cited,
                continuity_json={"episode_number": 1},
                status="DRAFT",
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return episode_id


def the_stored_v1_episode(event_id: str) -> list[dict]:
    """The shape of 'Day One' on his data (2026-09-12): eight beats of labelled dialogue,
    stage directions in the text, every beat citing the same event."""
    dialogue = (
        "Sarah (Director): (sighs) Right. The board says the script lands by noon.\n"
        "Kael (Video Editor): (without looking up) Then the render waits, and so do I."
    )
    return [
        {
            "beat_number": number,
            "scene": "The Content floor, morning light, the team at the board.",
            "dialogue": dialogue,
            "event_ids": [event_id],
            "characters": [SARAH, KAEL],
        }
        for number in range(1, 9)
    ]


def facts_in(prompt: str) -> dict:
    """The episode the Director was given, parsed from its boundary: it must be whole JSON."""
    block = prompt.split('<untrusted_source_evidence hash="the-episode">', 1)[1]
    return json.loads(block.split("</untrusted_source_evidence>", 1)[0])


def test_the_stored_v1_episode_fails_the_concentration_check(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    episode_id = stored_episode(
        engine, log["id"], the_stored_v1_episode(ids[0]), "Day One", [ids[0]]
    )

    checks = checks_of(engine, episode_id)
    assert checks["concentration"]["passed"] is False
    assert checks["concentration"]["most_cited"] == 8
    assert checks["concentration"]["beats"] == 8
    assert "8" in checks["concentration"]["reason"]

    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    review = review_episode(engine, registry(), episode_id)
    assert review["verdict"] == "FAIL" and calls == []


def test_no_event_may_carry_more_than_half_the_beats(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    crowded = beats_for([ids[0]] * 4 + [ids[1], ids[2]], [SARAH, KAEL])
    checks = checks_of(engine, written(engine, monkeypatch, crowded)["id"])
    assert checks["concentration"]["passed"] is False
    assert checks["concentration"]["most_cited"] == 4

    # Half is allowed: three of six beats on the letter, three on the answer.
    half = beats_for([ids[0]] * 3 + [ids[1]] * 3, [SARAH, KAEL])
    checks = checks_of(engine, written(engine, monkeypatch, half)["id"])
    assert checks["concentration"]["passed"] is True, checks["concentration"]


def test_the_days_only_event_may_carry_the_whole_episode(engine, staffed, monkeypatch):
    when = datetime.now(UTC) - timedelta(days=3)
    only = add_event(engine, "factual.topic_selected", when, {"title": "The Water of GJ 486 b"})
    log = close_daily_log(engine, TZ, business_date(TZ, when))
    assert [item["event_id"] for item in log["narrative_projection"]] == [only]

    episode = written(engine, monkeypatch, beats_for([only], [SARAH, KAEL]))
    checks = checks_of(engine, episode["id"])
    assert checks["concentration"]["passed"] is True, checks["concentration"]
    assert checks["concentration"]["only_event"] is True


def test_a_romanian_episode_fails_the_language_check(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    for beat in beats:
        beat["lines"][0]["text"] = "Bună dimineața, unde este numărul pentru această zi, colegi?"
    episode = written(engine, monkeypatch, beats)
    checks = checks_of(engine, episode["id"])
    assert checks["language"]["passed"] is False
    assert checks["language"]["lines_not_english"] == 6
    assert checks["language"]["title_english"] is True

    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    review = review_episode(engine, registry(), episode["id"])
    assert review["verdict"] == "FAIL" and calls == []
    assert "englez" in " ".join(review["reasons"])

    fake_showrunner(
        monkeypatch, episode_answer(beats_for(ids, [SARAH, KAEL]), title="Numărul de dimineață")
    )
    with Session(engine) as session:
        log_id = session.scalars(select(DailyStudioLog.id)).first()
    titled = write_episode(engine, registry(), log_id, str(uuid4()))["episode"]
    checks = checks_of(engine, titled["id"])
    assert checks["language"]["passed"] is False
    assert checks["language"]["title_english"] is False


def test_words_per_beat_are_the_spoken_words_only(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[1]["lines"] = [{"speaker": SARAH, "text": "Fine."}, {"speaker": KAEL, "text": "Sure."}]
    beats[2]["lines"][0]["text"] = " ".join((SPOKEN[0], SPOKEN[1], SPOKEN[0]))
    # A long acting note is not speech: the beat stays at its twenty spoken words.
    beats[3]["lines"][0]["direction"] = " ".join(["slowly"] * 40)
    checks = checks_of(engine, written(engine, monkeypatch, beats)["id"])

    measured = checks["words_per_beat"]
    assert measured["passed"] is False
    assert measured["per_beat"] == [20, 2, 40, 20, 20, 20]
    assert measured["outside"] == [2, 3]
    assert "2" in measured["reason"] and "3" in measured["reason"]
    assert checks["length"]["words"] == sum(measured["per_beat"])


def test_a_check_with_nothing_to_measure_does_not_pass(engine, staffed):
    log, _ = a_day(engine)
    empty = [
        {
            "beat_number": 1,
            "part": "hook",
            "location": "script_room",
            "scene": "An empty room with the lights off.",
            "lines": [],
            "event_ids": [],
            "characters": [],
        }
    ]
    checks = checks_of(engine, stored_episode(engine, log["id"], empty, "", []))
    for name in ("grounding", "concentration", "words_per_beat", "language"):
        assert checks[name]["passed"] is False, (name, checks[name])
        assert checks[name]["reason"], name


def with_memory(engine) -> None:
    """The serial's memory after three episodes: three long summaries and one open thread."""
    with Session(engine) as session, session.begin():
        session.add(
            ContinuityState(
                id=1,
                version=4,
                canon_episode_number=3,
                threads_json=[{"id": "T1", "text": "Who brings the number first?", "opened_in": 1}],
                recurring_json=["the espresso cup"],
                summaries_json=[
                    {
                        "episode_number": number,
                        "episode_id": str(uuid4()),
                        "title": f"Episode {number}",
                        "summary": f"Summary of episode {number}: " + "the board, " * 45,
                        "business_date": "2026-09-1" + str(number),
                    }
                    for number in (1, 2, 3)
                ],
                updated_at=utc_now(),
            )
        )


def test_the_director_reads_the_cited_events_the_voices_and_the_threads(
    engine, staffed, monkeypatch
):
    with_memory(engine)
    log, ids = letters_day(engine)
    episode = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), threads_continued=["T1"])

    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    review = review_episode(engine, registry(), episode["id"])

    (prompt,) = calls
    facts = facts_in(prompt)  # whole JSON: no blunt cut through the middle of it
    (cited,) = facts["beats"][0]["cites"]
    assert cited["id"] == ids[0]
    assert cited["what"] == projected(log, ids[0])["description"]
    assert "The cut runs long" in cited["what"]
    assert facts["voices"][SARAH]["register"] == "executive briefing"
    assert facts["voices"][SARAH]["expressions"]["greeting"] == "Right. Where are we?"
    assert facts["previously"]["open_threads"] == [
        {"id": "T1", "text": "Who brings the number first?"}
    ]
    assert "Summary of episode 3" in json.dumps(facts["previously"]["summaries"])
    # The brief: an outcome the cited event does not hold fails the episode, and the rubric.
    assert "an outcome that is not in the event it cites" in prompt
    for part in ("hook", "situation", "turn", "payoff", "voices", "button"):
        assert f'"{part}": 1-5' in prompt

    assert review["verdict"] == "PASS"
    assert review["scores"] == RUBRIC
    with Session(engine) as session:
        assert session.get(StoryEpisode, episode["id"]).review_json["scores"] == RUBRIC


def test_the_facts_are_fitted_to_a_budget_not_cut(engine, staffed, monkeypatch):
    from app.story.review import fit_to_budget, review_facts

    with_memory(engine)
    _, ids = letters_day(engine)
    episode = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]))
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        facts = review_facts(session, row, episode_checks(session, row))

    whole = json.dumps(facts, ensure_ascii=False)
    budget = len(whole) - 1500
    fitted = fit_to_budget(facts, budget)
    assert len(fitted) <= budget
    kept = json.loads(fitted)
    assert kept["trimmed"]
    # What was trimmed is the background; the episode itself is whole, every line of it.
    assert [beat["lines"] for beat in kept["beats"]] == [beat["lines"] for beat in facts["beats"]]
    assert [c["id"] for b in kept["beats"] for c in b["cites"]] == [
        c["id"] for b in facts["beats"] for c in b["cites"]
    ]
    assert fit_to_budget(facts, len(whole) + 10) == whole


@pytest.mark.parametrize(
    "scores",
    [None, {"hook": 4, "situation": 4, "turn": 4, "payoff": 4, "voices": 4}, {**RUBRIC, "turn": 9}],
)
def test_a_pass_without_its_rubric_is_not_a_verdict(engine, staffed, monkeypatch, scores):
    from app.story.review import ReviewError

    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "PASS", scores=scores)
    with pytest.raises(ReviewError):
        review_episode(engine, registry(), episode["id"])
    with Session(engine) as session:
        row = session.get(StoryEpisode, episode["id"])
        assert row.status == "DRAFT" and row.review_json is None  # read again next run


def test_a_pass_her_own_scores_contradict_is_a_fail(engine, staffed, monkeypatch):
    allow_director_approval(engine)
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "PASS", scores={**RUBRIC, "payoff": 2})
    review = review_episode(engine, registry(), episode["id"])

    assert review["verdict"] == "FAIL" and review["status"] == "REJECTED"
    assert "payoff" in " ".join(review["reasons"])
    assert review["scores"]["payoff"] == 2
    assert get_continuity(engine)["canon_episode_number"] == 0


def test_a_fail_needs_no_rubric(engine, staffed, monkeypatch):
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    fake_director(monkeypatch, "FAIL", notes="Beat 4 shows a verdict nobody gave.", scores=None)
    review = review_episode(engine, registry(), episode["id"])
    assert review["verdict"] == "FAIL" and review["scores"] == {}


def test_the_directors_contract_carries_the_episode_review():
    from app.agents.identity import load_role_contracts

    contract = load_role_contracts().roles["Director"]
    lines = " ".join(contract.watch_for + contract.never_let_pass)
    assert "episode_review" in lines
    assert "not in the event it cites" in lines


# ---------------------------------------------------------------------------
# Tomorrow's script in the same click (serial_next)
# ---------------------------------------------------------------------------

# Measured before this (2026-09-24): nothing wrote tomorrow's episode. The run's last act was
# closing today's log, and the serial stage tells only a day that is over, so the Owner's one
# click filmed an episode and left the next one unwritten. The new stage runs after today's
# log is closed: it writes, reviews and (under his policy) approves the episode of today,
# and builds no storyboard, so nothing is filmed or bought before the day is over. The next
# morning's serial stage readies it (S1's "storyboard" case) and the media stage films it.
# The schema carries a plan for the next episode, which the next writer keeps only if the
# events support it (07_STORY_ENGINE, marketing teaser linkage), and says whether it did.


def run_serial_next(engine, registry_, settings):
    from app.story.serial_stage import run_serial_next_stage

    return run_serial_next_stage(engine, registry_, settings)


def tomorrow_is(monkeypatch, days: int = 1) -> str:
    """The studio's clock moved on by ``days``, as both serial stages read it."""
    from app.story import serial_stage

    moved = business_date(TZ, datetime.now(UTC) + timedelta(days=days))
    monkeypatch.setattr(serial_stage, "business_date", lambda *_a, **_k: moved)
    return moved


def todays_episode(engine, monkeypatch, settings, **extra) -> tuple[dict, dict, list, list]:
    """Today, closed as the daily_log stage closes it, and the serial_next stage run on it."""
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    written_: list[str] = []
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names), **extra), written_)
    counting_director(monkeypatch, "PASS", reviewed)
    outcome = run_serial_next(engine, registry(), settings)
    return log, outcome, written_, reviewed


def test_tomorrows_script_is_written_reviewed_and_approved_but_never_storyboarded(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)

    log, outcome, written_, reviewed = todays_episode(engine, monkeypatch, settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["written"] == artefacts["reviewed"] == artefacts["approved"] == 1
    assert artefacts["storyboard_id"] is None
    assert artefacts["told_date"] == log["business_date"] == business_date(TZ)
    assert "mâine" in outcome["reason"]
    (row,) = episode_rows(engine)
    assert row.log_id == log["id"]
    assert row.status == "APPROVED" and row.storyboard_id is None
    # Nothing a media stage could film: no storyboard at all.
    assert storyboard_count(engine) == 0
    assert get_continuity(engine)["canon_episode_number"] == 1
    assert len(written_) == 1 and len(reviewed) == 1


def test_the_next_morning_readies_it_for_filming_without_writing_it_again(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    _, first, written_, reviewed = todays_episode(engine, monkeypatch, settings)
    tomorrow_is(monkeypatch)

    outcome = run_serial_stage(engine, registry(), settings)

    artefacts = outcome["artefacts"]
    assert outcome["status"] == "COMPLETED", outcome
    assert artefacts["resumed"] == "storyboard"
    assert artefacts["episode_id"] == first["artefacts"]["episode_id"]
    # The day it films is named on the run card, as on the day it was written (rehearsal on
    # a copy of his data, 2026-09-24: the resumed stage said told_date None every morning).
    assert artefacts["told_date"] == first["artefacts"]["told_date"]
    assert artefacts["storyboard_id"]
    assert artefacts["written"] == artefacts["reviewed"] == 0
    assert len(written_) == 1 and len(reviewed) == 1
    assert len(episode_rows(engine)) == 1 and storyboard_count(engine) == 1


def test_a_same_day_rerun_writes_nothing_twice_and_readies_nothing(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    _, first, written_, reviewed = todays_episode(engine, monkeypatch, settings)

    queue = run_serial_stage(engine, registry(), settings)
    again = run_serial_next(engine, registry(), settings)

    assert queue["artefacts"]["storyboard_id"] is None, queue
    assert again["status"] == "COMPLETED", again
    assert again["artefacts"]["written"] == 0
    assert again["artefacts"]["episode_id"] == first["artefacts"]["episode_id"]
    assert "O zi la studio" in again["reason"]
    assert len(written_) == 1 and len(reviewed) == 1
    assert len(episode_rows(engine)) == 1 and storyboard_count(engine) == 0


def test_without_the_directors_leave_tomorrows_script_waits_for_the_owner(
    engine, staffed, settings, monkeypatch
):
    _, outcome, _, _ = todays_episode(engine, monkeypatch, settings)

    assert outcome["artefacts"]["approved"] == 0
    assert "aprobarea" in outcome["reason"]
    (row,) = episode_rows(engine)
    assert row.status == "DRAFT" and (row.review_json or {}).get("verdict") == "PASS"
    assert storyboard_count(engine) == 0


def test_no_script_is_written_beside_an_episode_waiting_for_the_owner(
    engine, staffed, settings, monkeypatch
):
    """The canon number is fixed on his approval: a script written beside a waiting episode
    would claim the same number and continue a story it never read."""
    _, written_, reviewed = waiting_for_the_owner(engine, monkeypatch, settings)
    a_day(engine)

    outcome = run_serial_next(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["written"] == 0
    assert "O zi la studio" in outcome["reason"] and "aprobarea" in outcome["reason"]
    assert len(written_) == 1 and len(reviewed) == 1
    assert len(episode_rows(engine)) == 1


def test_a_quiet_today_writes_no_script(engine, staffed, settings, monkeypatch):
    moved = tomorrow_is(monkeypatch)
    close_daily_log(engine, TZ, moved)  # a day with no event at all
    written_: list[str] = []
    fake_showrunner(monkeypatch, "", written_)

    outcome = run_serial_next(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["written"] == 0
    assert "liniștită" in outcome["reason"]
    assert written_ == [] and episode_rows(engine) == []


def test_no_script_is_written_before_today_is_closed(engine, staffed, settings, monkeypatch):
    a_day(engine, YESTERDAY_NOON())
    written_: list[str] = []
    fake_showrunner(monkeypatch, "", written_)

    outcome = run_serial_next(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert outcome["artefacts"]["written"] == 0
    assert "nu este închis" in outcome["reason"]
    assert written_ == []


def test_tomorrows_script_is_skipped_without_a_language_model(engine, staffed, settings):
    a_day(engine)

    outcome = run_serial_next(engine, SimpleNamespace(registered_ids=list), settings)

    assert outcome["status"] == "SKIPPED"
    assert "model de limbaj" in outcome["reason"]


def test_an_answer_without_the_plan_for_the_next_episode_is_refused(engine, staffed, monkeypatch):
    from app.story.services import DraftRefused

    _, ids = letters_day(engine)

    with pytest.raises(DraftRefused) as refused:
        written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), next_episode=None)

    assert "next_episode" in str(refused.value)
    assert episode_rows(engine) == []


@pytest.mark.parametrize(
    "plan",
    [
        {**NEXT, "premise": "<one sentence: what the next episode is about>"},
        {**NEXT, "cold_open_line": ""},
        {**NEXT, "open_question": "..."},
        {**NEXT, "threads_to_pay_off": ["T4"]},
    ],
    ids=["format-copied", "no-cold-open", "filler-question", "thread-not-open"],
)
def test_a_plan_left_as_the_format_or_empty_is_refused(engine, staffed, monkeypatch, plan):
    from app.story.services import DraftRefused

    _, ids = letters_day(engine)

    with pytest.raises(DraftRefused):
        written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), next_episode=plan)
    assert episode_rows(engine) == []


def test_the_plan_is_stored_as_planned_and_names_only_open_threads(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ContinuityState(
                id=1,
                version=2,
                canon_episode_number=1,
                threads_json=[{"id": "T1", "text": "Who brings the number?", "opened_in": 1}],
                recurring_json=[],
                summaries_json=[],
                updated_at=utc_now(),
            )
        )
    plan = {**NEXT, "threads_to_pay_off": ["T1: who brings the number", "none"]}

    episode = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), next_episode=plan)

    stored = episode["continuity"]["next_episode"]
    assert stored["status"] == "PLANNED"
    assert stored["premise"] == NEXT["premise"]
    assert stored["cold_open_line"] == NEXT["cold_open_line"]
    assert stored["open_question"] == NEXT["open_question"]
    assert stored["threads_to_pay_off"] == ["T1"]
    assert stored["planned_on"] == business_date(TZ)
    # There was no plan before this one, so there was none to keep.
    assert episode["continuity"]["plan"] is None


@pytest.mark.parametrize(("kept", "status"), [(True, "KEPT"), (False, "DROPPED"), (None, "UNSAID")])
def test_the_next_writer_is_given_the_plan_and_says_whether_it_kept_it(
    engine, staffed, settings, monkeypatch, kept, status
):
    allow_director_approval(engine)
    yesterday, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, yesterday["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    fake_director(monkeypatch, "PASS")
    first = run_serial_stage(engine, registry(), settings)
    assert first["artefacts"]["approved"] == 1, first
    _, today_ids = a_day(engine)
    seen: list[str] = []
    note = "The day brought the number, so the plan holds." if kept else ""
    fake_showrunner(
        monkeypatch,
        episode_answer(beats_for(today_ids, names), plan_kept=kept, plan_note=note),
        seen,
    )

    outcome = run_serial_next(engine, registry(), settings)

    assert outcome["artefacts"]["approved"] == 1, outcome
    (prompt,) = seen
    assert "keep it only if" in prompt
    assert inside_a_boundary(prompt, NEXT["premise"])
    assert inside_a_boundary(prompt, NEXT["cold_open_line"])
    rows = {row.id: row for row in episode_rows(engine)}
    earlier = rows[first["artefacts"]["episode_id"]]
    later = rows[outcome["artefacts"]["episode_id"]]
    assert later.continuity_json["plan"] == {
        "from_episode_id": earlier.id,
        "from_episode_number": 1,
        "premise": NEXT["premise"],
        "kept": kept,
        "note": note,
    }
    # The plan's own record says what became of it, and which episode judged it.
    judged = earlier.continuity_json["next_episode"]
    assert judged["status"] == status
    assert judged["judged_in"] == later.id
    # And the new episode leaves a plan of its own for the day after.
    assert later.continuity_json["next_episode"]["status"] == "PLANNED"


def test_a_private_word_in_the_plan_fails_the_privacy_check(engine, staffed, monkeypatch):
    """The plan reaches the next writer's brief like canon does, so it is read like canon."""
    _, ids = letters_day(engine)
    plan = {**NEXT, "premise": f"Kael pastes {FAKE_KEY} into the brief."}

    episode = written(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]), next_episode=plan)

    privacy = checks_of(engine, episode["id"])["privacy"]
    assert privacy["passed"] is False
    assert privacy["leaking_canon"]


def test_todays_episode_approved_by_the_owner_is_not_filmed_before_the_day_is_over(
    engine, staffed, settings, monkeypatch
):
    """His approve button builds the storyboard at once (S1). The media stage still films a
    serial episode only once its day is over: a same-day re-run must not film today."""
    from app.runbook.stages import _media

    _, outcome, _, _ = todays_episode(engine, monkeypatch, settings)
    decide_episode(engine, outcome["artefacts"]["episode_id"], True, "")
    storyboard_from_episode(engine, outcome["artefacts"]["episode_id"], str(uuid4()))
    assert storyboard_count(engine) == 1

    today = _media(engine, settings, None)

    assert today["artefacts"].get("rendered") == 0, today
    assert "Niciun storyboard" in today["reason"]

    # The next day it is the serial's film like any other.
    from app.runbook import stages

    tomorrow = business_date(TZ, datetime.now(UTC) + timedelta(days=1))
    with Session(engine) as session:
        boards = session.scalars(select(Storyboard)).all()
        assert stages.serial_films_due(session, list(boards), tomorrow) == [boards[0].id]
