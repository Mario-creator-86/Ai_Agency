"""Phase 9 — the daily log, and dramatising a day without inventing it.

`../architecture/07_STORY_ENGINE.md` separates Operational Truth from the Narrative Layer and
lists what the serial may never fabricate: a hire that did not happen, a success or failure that
did not happen, an outage, a decision attributed to the wrong person, staff who were not there.

Underneath, those are one failure: a beat about something the event stream never recorded. So
these tests are mostly about grounding — every beat cites events from that day's log, every
character was in that day's roster, and a citation that is not in the log fails the whole
episode rather than being quietly dropped.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.models import DomainEvent
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.services import (
    EpisodeNotGrounded,
    NothingHappened,
    StoryError,
    business_date,
    close_daily_log,
    decide_episode,
    grounding_report,
    write_episode,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

TZ = "Europe/Bucharest"


def add_event(engine, event_type: str, when: datetime | None = None, payload=None) -> str:
    """Write one domain event directly, so a day has something in it to count."""
    event_id = str(uuid4())
    moment = (when or datetime.now(UTC)).astimezone(UTC).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            DomainEvent(
                event_id=event_id,
                event_type=event_type,
                timestamp=moment,
                aggregate_type="agent",
                aggregate_id=str(uuid4()),
                aggregate_version=1,
                correlation_id=str(uuid4()),
                causation_id=None,
                schema_version=1,
                visibility="OWNER",
                payload=payload or {},
            )
        )
    return event_id


#: A beat the schema accepts, so tests exercise grounding rather than field lengths.
SCENE = "The newsroom, morning"
LINE = "Sarah asks for a new topic."
SARAH = "Sarah (Director)"


def beat(event_id: str, text: str = LINE, speaker: str = SARAH, scene: str = SCENE) -> dict:
    """A beat of the showrunner's v3 schema: one spoken line, one citation."""
    return {"scene": scene, "lines": [{"speaker": speaker, "text": text}], "event_ids": [event_id]}


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    return engine


#: The plan for the next episode, which every stored answer carries (schema v3, S6).
NEXT = {
    "premise": "Sarah finally gets a topic before she asks for one.",
    "cold_open_line": "I have a topic, and you did not even have to ask.",
    "open_question": "Will Sarah accept a topic she did not ask for?",
    "threads_to_pay_off": [],
}


def episode_answer(beats: list[dict], title: str = "O zi la studio") -> str:
    return json.dumps({"title": title, "beats": beats, "next_episode": NEXT})


def run(engine, log_id, answer, monkeypatch, roster_name="Sarah (Director)"):
    from app.story import services

    def fake_run(_engine, _registry, agent_id, *args, **kwargs):
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answer,
            "error_detail": None,
        }

    monkeypatch.setattr(services, "run_agent_task", fake_run)
    return write_episode(engine, object(), log_id, str(uuid4()))


# ---------------------------------------------------------------------------
# The log is counted, not narrated
# ---------------------------------------------------------------------------


def test_the_log_counts_what_the_stream_contains(engine, staffed):
    add_event(engine, "agent.message_sent")
    add_event(engine, "agent.message_sent")
    add_event(engine, "media.video_rendered")

    log = close_daily_log(engine, TZ)

    assert log["event_counts"]["agent.message_sent"] == 2
    assert log["event_counts"]["media.video_rendered"] == 1
    assert log["total_events"] >= 3
    assert log["business_date"] == business_date(TZ)


def test_yesterdays_events_are_not_in_todays_log(engine, staffed):
    add_event(engine, "agent.message_sent", when=datetime.now(UTC) - timedelta(days=2))

    log = close_daily_log(engine, TZ)

    assert "agent.message_sent" not in log["event_counts"]


def test_a_closed_log_does_not_change(engine, staffed):
    """The log is what an episode is checked against; letting it drift would let an episode
    become grounded after the fact."""
    add_event(engine, "agent.message_sent")
    first = close_daily_log(engine, TZ)

    add_event(engine, "media.video_rendered")
    second = close_daily_log(engine, TZ)

    assert second["id"] == first["id"]
    assert second["event_counts"] == first["event_counts"]
    with Session(engine) as session:
        assert len(session.scalars(select(DailyStudioLog)).all()) == 1


def test_the_roster_records_who_was_there(engine, staffed):
    log = close_daily_log(engine, TZ)

    names = {member["display_name"] for member in log["roster"]}
    assert "Sarah (Director)" in names
    assert all("lifecycle" in member for member in log["roster"])


def test_only_narratable_events_are_offered_as_material(engine, staffed):
    add_event(engine, "agent.message_sent")
    add_event(engine, "settings.integration_saved")  # real, but not story material

    log = close_daily_log(engine, TZ)

    offered = {item["event_type"] for item in log["notable_events"]}
    assert "agent.message_sent" in offered
    assert "settings.integration_saved" not in offered
    # It still counts towards the day's totals; it is simply not handed to the showrunner.
    assert log["event_counts"]["settings.integration_saved"] == 1


# ---------------------------------------------------------------------------
# A quiet day
# ---------------------------------------------------------------------------


def test_a_day_with_nothing_narratable_produces_no_episode(engine, staffed, monkeypatch):
    """Manufacturing a story from an empty log is the fabrication the spec forbids, dressed as
    productivity."""
    quiet = business_date(TZ, datetime.now(UTC) - timedelta(days=3))
    log = close_daily_log(engine, TZ, quiet)
    assert log["notable_events"] == []

    with pytest.raises(NothingHappened):
        run(engine, log["id"], episode_answer([]), monkeypatch)

    with Session(engine) as session:
        assert session.scalars(select(StoryEpisode)).all() == []


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_a_grounded_episode_is_stored_with_its_citations(engine, staffed, monkeypatch):
    first = add_event(engine, "agent.message_sent")
    second = add_event(engine, "media.video_rendered")
    log = close_daily_log(engine, TZ)

    answer = episode_answer(
        [
            beat(first, scene="The newsroom in the morning"),
            beat(second, "The render is finished.", "Kael (Video Editor)", "The edit suite"),
        ]
    )

    result = run(engine, log["id"], answer, monkeypatch)
    episode = result["episode"]

    assert episode["status"] == "DRAFT"
    assert sorted(episode["grounded_event_ids"]) == sorted([first, second])
    assert [beat["beat_number"] for beat in episode["beats"]] == [1, 2]
    assert episode["continuity"]["business_date"] == log["business_date"]


def test_a_beat_citing_an_event_that_did_not_happen_fails_the_whole_episode(
    engine, staffed, monkeypatch
):
    """The failure this mechanism exists for. The prose around an invented citation was written
    under the same misapprehension, so the episode goes, not just the beat."""
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)

    answer = episode_answer(
        [
            beat(real),
            beat(str(uuid4()), "The vendor was down all morning.", scene="The server room"),
        ]
    )

    with pytest.raises(EpisodeNotGrounded) as excinfo:
        run(engine, log["id"], answer, monkeypatch)

    assert "beat-ul 2" in str(excinfo.value)
    with Session(engine) as session:
        assert session.scalars(select(StoryEpisode)).all() == []


def test_an_event_from_another_day_cannot_be_cited(engine, staffed, monkeypatch):
    yesterday = add_event(engine, "agent.message_sent", when=datetime.now(UTC) - timedelta(days=2))
    add_event(engine, "media.video_rendered")
    log = close_daily_log(engine, TZ)

    answer = episode_answer(
        [
            beat(yesterday, "That was yesterday."),
        ]
    )

    with pytest.raises(EpisodeNotGrounded):
        run(engine, log["id"], answer, monkeypatch)


def test_the_serial_cannot_cast_someone_who_was_not_there(engine, staffed, monkeypatch):
    """Putting a person in a room the record says they were not in is the same failure as
    citing an event that did not happen."""
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)

    answer = episode_answer(
        [
            beat(real, "Someone new walks in.", "Un stagiar inventat", "A meeting"),
        ]
    )

    with pytest.raises(EpisodeNotGrounded) as excinfo:
        run(engine, log["id"], answer, monkeypatch)

    assert "nu era" in str(excinfo.value)


def test_a_beat_with_no_citation_is_refused(engine, staffed, monkeypatch):
    add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)

    answer = episode_answer(
        [{"scene": SCENE, "lines": [{"speaker": SARAH, "text": "A scene with no source."}]}]
    )

    with pytest.raises(StoryError):
        run(engine, log["id"], answer, monkeypatch)


@pytest.mark.parametrize(
    "answer",
    [
        "Iată episodul!",
        '{"title": "T", "beats": []}',
        '{"beats": [{"scene": "A"}]}',
        "",
        # The v2 shape, dialogue with no speaker on it: one voice would read it all, so the
        # v3 schema refuses it rather than guess who says what.
        '{"title": "Old shape", "beats": [{"scene": "The newsroom", "dialogue": "No names.",'
        ' "event_ids": ["x"]}]}',
    ],
)
def test_an_answer_that_is_not_an_episode_stores_nothing(engine, staffed, monkeypatch, answer):
    add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)

    with pytest.raises(StoryError):
        run(engine, log["id"], answer, monkeypatch)

    with Session(engine) as session:
        assert session.scalars(select(StoryEpisode)).all() == []


# ---------------------------------------------------------------------------
# The claim can be re-checked afterwards
# ---------------------------------------------------------------------------


def test_grounding_can_be_audited_after_the_fact(engine, staffed, monkeypatch):
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)
    answer = episode_answer([beat(real)])
    episode = run(engine, log["id"], answer, monkeypatch)["episode"]

    report = grounding_report(engine, episode["id"])

    assert report["grounded"] is True
    assert report["citations_not_in_the_log"] == []
    assert report["cited_events"] == 1


def test_the_audit_names_a_citation_that_is_not_in_the_log(engine, staffed, monkeypatch):
    """Defence in depth: if a row were ever written past the check, the report still catches it."""
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)
    answer = episode_answer([beat(real)])
    episode = run(engine, log["id"], answer, monkeypatch)["episode"]

    invented = str(uuid4())
    with Session(engine) as session, session.begin():
        session.get(StoryEpisode, episode["id"]).grounded_event_ids_json = [real, invented]

    report = grounding_report(engine, episode["id"])

    assert report["grounded"] is False
    assert report["citations_not_in_the_log"] == [invented]


# ---------------------------------------------------------------------------
# The Owner decides
# ---------------------------------------------------------------------------


def test_an_episode_can_be_rejected_with_a_reason(engine, staffed, monkeypatch):
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)
    episode = run(
        engine,
        log["id"],
        episode_answer([beat(real)]),
        monkeypatch,
    )["episode"]

    decided = decide_episode(engine, episode["id"], False, "Tonul nu se potrivește.")

    assert decided["status"] == "REJECTED"
    assert "Tonul" in decided["notes"]


def test_an_episode_cannot_be_decided_twice(engine, staffed, monkeypatch):
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)
    episode = run(
        engine,
        log["id"],
        episode_answer([beat(real)]),
        monkeypatch,
    )["episode"]
    decide_episode(engine, episode["id"], True, "")

    with pytest.raises(StoryError):
        decide_episode(engine, episode["id"], False, "M-am răzgândit")


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_a_quiet_day_is_reported_as_a_fact_not_an_error(client, headers, engine, staffed):
    quiet = business_date(TZ, datetime.now(UTC) - timedelta(days=3))
    closed = client.post(
        "/api/v1/story/logs/close",
        json={"command_id": str(uuid4()), "business_date": quiet},
        headers=headers,
    ).json()

    response = client.post(
        "/api/v1/story/episodes/write",
        json={"command_id": str(uuid4()), "log_id": closed["id"]},
        headers=headers,
    )

    assert response.status_code == 409
    assert "zi liniștită" in response.json()["detail"]


def test_the_operational_record_is_untouched_by_the_narrative(engine, staffed, monkeypatch):
    """The narrative layer may never overwrite operational truth."""
    real = add_event(engine, "agent.message_sent")
    log = close_daily_log(engine, TZ)
    with Session(engine) as session:
        before = session.scalars(select(DomainEvent.event_id)).all()

    run(
        engine,
        log["id"],
        episode_answer([beat(real)]),
        monkeypatch,
    )

    with Session(engine) as session:
        after = session.scalars(select(DomainEvent.event_id)).all()
    # Writing an episode only appends its own event; nothing that already existed changed.
    assert set(before).issubset(set(after))
    assert len(after) > len(before)
