"""The serial makes its episode by itself: a writer held to the review before its draft is
kept, and a refused day told again.

Measured on a copy of the Owner's database (2026-10-10): 17 episodes and none approved. The
16 drafts since 2026-09-19 were all REJECTED by the Director's computed checks, her model
never asked: the cast check in 14 of them (five to seven speakers against the Owner's two to
four, because the writer gave a line to everyone who acts in an event it cites), the length
in 12, privacy in 4. And once a day's two drafts were refused nothing wrote it again: the
script for tomorrow said the day "is already written (rejected)", the morning's stage told
only a day after the last one told, and the serial made nothing at all.

These tests hold the three changes, in the order a day meets them:

- the brief names two to four SPEAKERS, and an answer is measured by the review's own checks
  before it is stored: a refusal is asked again once, with the reasons, and the better of
  the two answers is kept; a beat the camera cannot film in one clip is one of the refusals;
- a day whose every draft was refused is told again by a later run, with the reasons, up to
  three drafts a day; then the oldest day the serial passed over;
- end to end on fakes: a writer that first casts six people and then obeys makes episode 1,
  approved by the Director, storyboarded the next morning and due for filming then.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.media.models import Storyboard
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.publishing.services import seed_default_channels
from app.runbook.stages import serial_films_due
from app.services import append_event, utc_now
from app.story.lines import NameBook
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.review import beat_clip_seconds, episode_checks, review_episode
from app.story.serial_stage import (
    MAX_DRAFTS_PER_DAY,
    run_serial_next_stage,
    run_serial_stage,
)
from app.story.services import (
    OFFERED_SPEAKERS,
    business_date,
    close_daily_log,
    get_continuity,
    speakers_to_offer,
    write_episode,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    NEXT,
    NOON_DAYS_AGO,
    SPOKEN,
    TZ,
    YESTERDAY_NOON,
    add_event,
    allow_director_approval,
    cast_names,
    date_days_ago,
    episode_rows,
    events_on,
    fake_director,
    parts_for,
    registry,
    storyboard_count,
    tomorrow_is,
)


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def a_crowded_day(engine, when: datetime | None = None) -> tuple[dict, list[str]]:
    """A closed day where six people act: three pairs of colleagues write to each other.
    Returns the log and the six letters' event ids."""
    names = cast_names(engine)[:6]
    ids = []
    for first, second in zip(names[::2], names[1::2], strict=True):
        for sender, receiver, subject in (
            (first, second, "The cut runs long"),
            (second, first, "Re: The cut runs long"),
        ):
            ids.append(
                add_event(
                    engine,
                    "agent.message_posted",
                    when,
                    {"from_name": sender, "to_name": receiver, "subject": subject},
                    aggregate_type="agent_message",
                )
            )
    log = close_daily_log(engine, TZ, business_date(TZ, when) if when else None)
    return log, ids


def _listed(prompt: str, label: str) -> list[str]:
    found = re.search(rf"^{label}: (\[.*\])$", prompt, re.MULTILINE)
    return json.loads(found.group(1)) if found else []


def _events(prompt: str) -> list[dict]:
    block = prompt.split("EVENTS OF", 1)[-1].split("PREVIOUSLY:", 1)[0]
    return [json.loads(row) for row in block.splitlines() if row.startswith('{"id"')]


def _rooms(prompt: str) -> list[str]:
    block = prompt.split("LOCATIONS (", 1)[-1].split("EVENTS OF", 1)[0]
    return re.findall(r"^- ([a-z0-9_-]+): ", block, re.MULTILINE)


def answer_to(prompt: str, obedient: bool, title: str = "The Cut Runs Long") -> str:
    """An episode written from the brief's own data. Unruly, it gives a line to everyone who
    acts in the day's events, as his writer did in 14 of 16 drafts; obedient, only the first
    two SPEAKERS speak, in the events they act in."""
    events = _events(prompt)
    if obedient:
        speakers = _listed(prompt, "SPEAKERS")[:2]
        cited = [event for event in events if set(event["who"]) & set(speakers)]
        cited += [event for event in events if not event["who"]][: max(0, 2 - len(cited))]
    else:
        speakers = list(dict.fromkeys(name for event in events for name in event["who"]))
        cited = [event for event in events if event["who"]]
    room = _rooms(prompt)[0]
    beats = []
    for index, part in enumerate(parts_for(6)):
        beats.append(
            {
                "part": part,
                "location": room,
                "scene": f"The studio floor, scene {index + 1}: {speakers[0]} at the desk.",
                "lines": [
                    {"speaker": speakers[index % len(speakers)], "text": SPOKEN[0]},
                    {"speaker": speakers[(index + 1) % len(speakers)], "text": SPOKEN[1]},
                ],
                "event_ids": [cited[index % len(cited)]["id"]],
            }
        )
    return json.dumps(
        {
            "title": title,
            "beats": beats,
            "summary": "The cut ran long, and the letters said so.",
            "next_episode": NEXT,
        }
    )


class Writer:
    """The showrunner's model, faked: its first ``unruly`` answers cast everyone, the rest
    obey the brief. Every brief it was given is kept."""

    def __init__(self, unruly: int) -> None:
        self.unruly = unruly
        self.prompts: list[str] = []

    def __call__(self, _engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        self.prompts.append(prompt)
        obedient = len(self.prompts) > self.unruly
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answer_to(prompt, obedient),
        }


def hire(monkeypatch, writer: Writer) -> Writer:
    from app.story import services

    monkeypatch.setattr(services, "run_agent_task", writer)
    return writer


def a_motion_model(engine, longest: int = 10, model_id: str = "LTX-2.5") -> None:
    """The serial's camera as his studio has it: the Organization's video connection, whose
    selected model films at most ``longest`` seconds in one clip (its contract)."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="runpod",
                name="runpod",
                config={},
                encrypted_secrets="",
                secret_fields=[],
                version=1,
                status="VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.flush()
        session.add(
            MediaProductionConfig(
                integration_id=identifier, model_id=model_id, version=1, updated_at=utc_now()
            )
        )
        session.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=identifier,
                resource_type="MODEL",
                remote_id=model_id,
                name=model_id,
                api_available=True,
                last_seen_at=utc_now(),
                api_metadata={
                    "purpose": "video",
                    "durations": {"image_to_video": {"min": 1, "max": longest}},
                    "max_seconds": longest,
                },
            )
        )
        session.merge(
            ServiceSelection(
                purpose="video", integration_id=identifier, version=1, event_id=event.event_id
            )
        )


def checks_of(engine, episode_id: str) -> dict:
    with Session(engine) as session:
        return episode_checks(session, session.get(StoryEpisode, episode_id))


# ------------------------------------------------------------------ the writer's brief --


def test_the_brief_names_the_speakers_who_act_most_in_the_day(engine, staffed, monkeypatch):
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    writer = hire(monkeypatch, Writer(unruly=0))

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    (prompt,) = writer.prompts
    offered = _listed(prompt, "SPEAKERS")
    acting = list(dict.fromkeys(n for event in _events(prompt) for n in event["who"]))
    assert len(acting) == 6
    # Three of the six, each with two letters: the first to act first on a tie.
    assert offered == acting[:OFFERED_SPEAKERS]
    assert "Only the people in SPEAKERS speak" in prompt
    assert episode["continuity"]["speakers_offered"] == offered
    assert episode["continuity"]["write_checks"] == {
        "attempts": 1,
        "first_refusal": None,
        "failed": [],
    }


def test_a_day_where_one_person_acts_offers_the_roster_beside_them(engine, staffed):
    roster = [
        {"display_name": name, "role_name": "Agent", "lifecycle": "ACTIVE"}
        for name in cast_names(engine)
    ]
    names = NameBook(roster)
    projection = [
        {
            "event_id": "e1",
            "event_type": "agent.message_posted",
            "description": f"{roster[3]['display_name']} wrote a note to the Director's desk",
        },
        {"event_id": "e2", "event_type": "media.video_rendered", "description": "A film"},
    ]

    offered = speakers_to_offer(projection, names, roster)

    assert offered[0] == roster[3]["display_name"]
    assert offered[1:] == [roster[0]["display_name"], roster[1]["display_name"]]


# ---------------------------------------------------- measured before the draft is kept --


def test_six_speakers_are_asked_again_with_the_reasons_and_the_obedient_draft_kept(
    engine, staffed, monkeypatch
):
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    writer = hire(monkeypatch, Writer(unruly=1))

    written = write_episode(engine, registry(), log["id"], str(uuid4()))

    assert written["attempts"] == 2 and len(writer.prompts) == 2
    retry = writer.prompts[1]
    # Asked again the way a refused answer is: the reasons, the answer as data.
    assert "YOUR PREVIOUS ANSWER WAS REFUSED" in retry
    assert "vorbesc 6 personaje; episodul cere între 2 și 4" in retry
    # Only the review's own checks ask again; the offered speakers only steer (2026-10-11).
    assert "vorbesc fără să fie printre vorbitorii aleși" not in retry
    episode = written["episode"]
    speakers = {name for beat in episode["beats"] for name in beat["speakers"]}
    assert speakers == set(_listed(retry, "SPEAKERS")[:2])
    assert episode["continuity"]["write_checks"]["failed"] == []
    assert "vorbesc 6 personaje" in episode["continuity"]["write_checks"]["first_refusal"]
    assert all(check["passed"] for check in checks_of(engine, episode["id"]).values())


def test_a_draft_that_still_fails_is_kept_and_the_review_names_the_same_reasons(
    engine, staffed, monkeypatch
):
    """The writer's measure is the review's: what the second ask could not fix, the review
    refuses for, with the same words, and her model is never asked."""
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    writer = hire(monkeypatch, Writer(unruly=2))
    written = write_episode(engine, registry(), log["id"], str(uuid4()))
    measured = written["episode"]["continuity"]["write_checks"]
    assert measured["attempts"] == 2 and measured["failed"] == ["cast"]
    with Session(engine) as session:
        assert session.get(StoryEpisode, written["episode"]["id"]).status == "DRAFT"

    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    review = review_episode(engine, registry(), written["episode"]["id"])

    assert review["verdict"] == "FAIL" and review["status"] == "REJECTED"
    assert calls == [] and review["model_used"] is False
    failed = [name for name, check in review["checks"].items() if not check["passed"]]
    assert failed == ["cast"]  # the offered speakers steer the writer; the cast rule decides
    assert review["reasons"] == [review["checks"]["cast"]["reason"]]
    assert review["checks"]["cast"]["reason"] in measured["first_refusal"]
    assert len(writer.prompts) == 2


def test_the_better_of_the_two_answers_is_kept(engine, staffed, monkeypatch):
    from app.story import services

    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    seen: list[str] = []

    def two_answers(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        seen.append(prompt)
        if len(seen) == 1:
            text = answer_to(prompt, obedient=False, title="The First Answer")
        else:
            worse = json.loads(answer_to(prompt, obedient=False, title="The Second Answer"))
            worse["beats"] = worse["beats"][:2]  # short, and no structure: more refusals
            text = json.dumps(worse)
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": text}

    monkeypatch.setattr(services, "run_agent_task", two_answers)

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    assert len(seen) == 2
    assert episode["title"] == "The First Answer"
    assert episode["continuity"]["write_checks"]["failed"] == ["cast"]


def test_an_answer_that_is_not_an_episode_on_the_second_ask_keeps_the_first(
    engine, staffed, monkeypatch
):
    from app.story import services

    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    seen: list[str] = []

    def then_nonsense(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        seen.append(prompt)
        text = answer_to(prompt, obedient=False) if len(seen) == 1 else "nu e JSON"
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": text}

    monkeypatch.setattr(services, "run_agent_task", then_nonsense)

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    assert len(seen) == 2 and episode["title"] == "The Cut Runs Long"
    assert episode["continuity"]["write_checks"]["failed"] == ["cast"]


# ------------------------------------------------------------ a beat the camera can film --


def test_numbers_said_in_words_and_the_breath_between_speakers_count():
    lines = [
        {"speaker": "Sarah (Director)", "text": "In 1964 we shipped it."},
        {"speaker": "Kael (Video Editor)", "text": "Twice."},
    ]
    # "1964" is said as three words: 8 words x 0.40 s, one 0.3 s breath between the two
    # takes, the estimate's 10 % and the scene's 0.12 s closing breath.
    assert beat_clip_seconds(lines) == round((8 * 0.40 + 0.3) * 1.10 + 0.12, 2)
    # One speaker's two lines are one take: no breath between them.
    alone = [{**line, "speaker": "Sarah (Director)"} for line in lines]
    assert beat_clip_seconds(alone) == round(8 * 0.40 * 1.10 + 0.12, 2)


def test_a_beat_longer_than_one_clip_is_refused_and_the_writer_told(engine, staffed, monkeypatch):
    """22 written words pass the words-per-beat rule; four years said in words (30 spoken)
    and the breaths between three takes make the beat 14 s, longer than a 10 s clip slowed
    by a quarter (12.5 s)."""
    from app.story import services

    a_motion_model(engine, longest=10)
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    seen: list[str] = []
    long_lines = [
        {"text": "In 1961, 1962, 1963 and 1964 the old cut ran"},
        {"text": "long, and nobody"},
        {"text": "said a word about it, ever, to anyone here."},
    ]

    def numbers(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        seen.append(prompt)
        body = json.loads(answer_to(prompt, obedient=True))
        speakers = _listed(prompt, "SPEAKERS")[:2]
        body["beats"][2]["lines"] = [
            {"speaker": speakers[index % len(speakers)], **line}
            for index, line in enumerate(long_lines)
        ]
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": json.dumps(body)}

    monkeypatch.setattr(services, "run_agent_task", numbers)

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    assert len(seen) == 2
    assert "nu încap într-un singur cadru" in seen[1] and "LTX-2.5" in seen[1]
    checks = checks_of(engine, episode["id"])
    assert checks["words_per_beat"]["passed"] is True
    assert checks["filmable"]["passed"] is False and checks["filmable"]["outside"] == [3]
    assert checks["filmable"]["limit_seconds"] == 12.5
    assert checks["filmable"]["needed_seconds"][2] > 12.5
    assert episode["continuity"]["write_checks"]["failed"] == ["filmable"]
    assert "14,0 s" in episode["continuity"]["write_checks"]["first_refusal"]


def test_every_beat_inside_one_clip_passes_the_filming_check(engine, staffed, monkeypatch):
    a_motion_model(engine, longest=10)
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    hire(monkeypatch, Writer(unruly=0))

    episode = write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]

    filmable = checks_of(engine, episode["id"])["filmable"]
    assert filmable["passed"] is True and filmable["model_id"] == "LTX-2.5"
    assert max(filmable["needed_seconds"]) < 12.5


# ------------------------------------------------------------- a refused day told again --


def refused_twice(engine, monkeypatch, settings, when: datetime) -> tuple[dict, Writer]:
    """A day told the way every day of his serial was: an unruly writer, two drafts, both
    REJECTED by the computed checks."""
    log, _ids = a_crowded_day(engine, when)
    writer = hire(monkeypatch, Writer(unruly=99))
    calls: list[str] = []
    fake_director(monkeypatch, "PASS", calls=calls)
    first = run_serial_stage(engine, registry(), settings)
    assert first["artefacts"]["written"] == 2, first
    assert [row.status for row in episode_rows(engine)] == ["REJECTED", "REJECTED"]
    # Bounded: two drafts a run, each asked at most twice; the Director's model is never
    # asked about a draft the computed checks refused.
    assert len(writer.prompts) == 4 and calls == []
    return log, writer


def test_a_refused_day_is_told_again_by_the_next_run_and_filmed(
    engine, staffed, settings, monkeypatch
):
    allow_director_approval(engine)
    log, _ = refused_twice(engine, monkeypatch, settings, YESTERDAY_NOON())
    last = episode_rows(engine)[-1]
    writer = hire(monkeypatch, Writer(unruly=0))
    fake_director(monkeypatch, "PASS")

    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["resumed"] == "retell" and artefacts["told_date"] == log["business_date"]
    assert artefacts["written"] == 1 and artefacts["approved"] == 1
    assert "se scrie din nou" in outcome["reason"]
    # Written with the reasons the last draft was refused for, as its rewrite.
    (prompt,) = writer.prompts
    assert "THIS IS A REWRITE" in prompt and last.notes and last.notes in prompt
    newest = episode_rows(engine)[-1]
    assert newest.rewrite_of_id == last.id and newest.status == "APPROVED"
    assert newest.reviewed_by == "director"
    assert get_continuity(engine)["canon_episode_number"] == 1
    assert artefacts["storyboard_id"] == newest.storyboard_id
    with Session(engine) as session:
        boards = list(session.scalars(select(Storyboard)))
        assert serial_films_due(session, boards, business_date(TZ)) == [newest.storyboard_id]


def test_a_day_out_of_drafts_gives_way_to_the_oldest_day_passed_over(
    engine, staffed, settings, monkeypatch
):
    older = events_on(engine, NOON_DAYS_AGO(3))
    for days in (3, 1):
        close_daily_log(engine, TZ, date_days_ago(days))
    refused_twice(engine, monkeypatch, settings, NOON_DAYS_AGO(2))
    hire(monkeypatch, Writer(unruly=99))
    third = run_serial_stage(engine, registry(), settings)
    assert third["artefacts"]["resumed"] == "retell" and third["artefacts"]["written"] == 1
    assert "serialul trece la altă zi" in third["reason"]
    assert len(episode_rows(engine)) == MAX_DRAFTS_PER_DAY

    writer = hire(monkeypatch, Writer(unruly=0))
    allow_director_approval(engine)
    fake_director(monkeypatch, "PASS")
    outcome = run_serial_stage(engine, registry(), settings)

    assert outcome["artefacts"]["told_date"] == date_days_ago(3), outcome
    assert "sărită până acum" in outcome["reason"]
    assert outcome["artefacts"]["approved"] == 1
    assert "THIS IS A REWRITE" not in writer.prompts[0]
    assert all(event_id in writer.prompts[0] for event_id in older)


def test_nothing_is_told_again_before_an_approved_day(engine, staffed, settings, monkeypatch):
    """Canon runs forward: a refused day older than an approved one stays as it is."""
    refused_twice(engine, monkeypatch, settings, NOON_DAYS_AGO(2))
    allow_director_approval(engine)
    hire(monkeypatch, Writer(unruly=0))
    fake_director(monkeypatch, "PASS")
    log, _ids = a_crowded_day(engine, YESTERDAY_NOON())
    approved = run_serial_stage(engine, registry(), settings)
    assert approved["artefacts"]["told_date"] == log["business_date"]
    assert approved["artefacts"]["approved"] == 1

    writer = hire(monkeypatch, Writer(unruly=0))
    again = run_serial_stage(engine, registry(), settings)

    assert again["artefacts"]["written"] == 0 and writer.prompts == [], again


def test_tomorrows_script_refused_is_written_again_until_the_days_budget(
    engine, staffed, settings, monkeypatch
):
    a_crowded_day(engine)  # today, closed as daily_log closes it
    writer = hire(monkeypatch, Writer(unruly=99))
    fake_director(monkeypatch, "PASS")

    first = run_serial_next_stage(engine, registry(), settings)
    assert first["artefacts"]["written"] == 2
    second = run_serial_next_stage(engine, registry(), settings)
    assert second["artefacts"]["resumed"] == "retell" and second["artefacts"]["written"] == 1
    third = run_serial_next_stage(engine, registry(), settings)

    assert third["artefacts"]["written"] == 0
    assert f"ziua și-a folosit cele {MAX_DRAFTS_PER_DAY} ciorne" in third["reason"]
    assert len(episode_rows(engine)) == MAX_DRAFTS_PER_DAY
    assert len(writer.prompts) == 2 * MAX_DRAFTS_PER_DAY


# ------------------------------------------------------------------ end to end, on fakes --


def test_the_serial_makes_its_first_episode_alone(engine, staffed, settings, monkeypatch):
    """The Owner's «Toate trebuie să le facă studioul singur», on fakes: today's script is
    written by a writer that first casts six people, measured, asked again with the reasons,
    kept, passed and approved by the Director as episode 1 and readied the same evening
    (2026-10-11; until then the next morning readied it); it is the serial's film of the day
    after, not of today, and the morning writes nothing again."""
    allow_director_approval(engine)
    log, _ids = a_crowded_day(engine)  # today, closed as daily_log closes it
    writer = hire(monkeypatch, Writer(unruly=1))
    asked: list[str] = []
    fake_director(monkeypatch, "PASS", calls=asked)

    tonight = run_serial_next_stage(engine, registry(), settings)

    assert tonight["status"] == "COMPLETED", tonight
    assert tonight["artefacts"]["written"] == 1 and tonight["artefacts"]["approved"] == 1
    assert len(writer.prompts) == 2 and len(asked) == 1
    (episode,) = episode_rows(engine)
    assert episode.status == "APPROVED" and episode.reviewed_by == "director"
    assert episode.review_json["verdict"] == "PASS" and episode.review_json["model_used"]
    assert episode.continuity_json["write_checks"]["attempts"] == 2
    assert episode.storyboard_id == tonight["artefacts"]["storyboard_id"]
    assert storyboard_count(engine) == 1
    assert get_continuity(engine)["canon_episode_number"] == 1
    today = business_date(TZ)
    assert tonight["artefacts"]["told_date"] == log["business_date"] == today
    with Session(engine) as session:
        boards = list(session.scalars(select(Storyboard)))
        assert [board.series_key for board in boards] == ["office_serial"]
        assert serial_films_due(session, boards, today) == []
        assert session.get(DailyStudioLog, episode.log_id).business_date == today

    tomorrow = tomorrow_is(monkeypatch)
    morning = run_serial_stage(engine, registry(), settings)

    assert morning["artefacts"]["resumed"] is None, morning
    assert morning["artefacts"]["written"] == 0 and storyboard_count(engine) == 1
    with Session(engine) as session:
        boards = list(session.scalars(select(Storyboard)))
        assert serial_films_due(session, boards, tomorrow) == [episode.storyboard_id]
    assert len(writer.prompts) == 2  # the morning wrote nothing


def test_a_retold_day_is_readied_but_its_days_media_stage_waits_for_it_to_be_over(
    engine, staffed, settings, monkeypatch
):
    """Today's script, refused and written again by a same-day re-run, is approved and
    readied (2026-10-11); the day's own media stage still films nothing of a day not yet over,
    and in TEST nothing continues tonight."""
    allow_director_approval(engine)
    a_crowded_day(engine)
    hire(monkeypatch, Writer(unruly=99))
    fake_director(monkeypatch, "PASS")
    run_serial_next_stage(engine, registry(), settings)
    hire(monkeypatch, Writer(unruly=0))

    again = run_serial_next_stage(engine, registry(), settings)

    assert again["artefacts"]["approved"] == 1 and again["artefacts"]["storyboard_id"]
    assert again["artefacts"]["film_continue_task_id"] is None
    assert storyboard_count(engine) == 1
    with Session(engine) as session:
        boards = list(session.scalars(select(Storyboard)))
        assert serial_films_due(session, boards, business_date(TZ)) == []


def test_a_day_already_at_the_cap_ships_its_newest_draft_once_she_may_approve(
    engine, staffed, settings, monkeypatch
):
    """15.10, 14:19Z: episode 3 had used the day's three drafts on the Director's reading and
    «serialul trece la altă zi». The evening script of a later run finds the day at its cap,
    every draft refused by her reading, and ships the newest draft under the cap (the Owner,
    2026-10-15: «publicăm ce avem»): approved, readied, its filming queued. A writer whose
    drafts the computed checks refused (``unruly``) never ships — the test above keeps that."""
    a_crowded_day(engine)
    writer = hire(monkeypatch, Writer(unruly=0))
    fake_director(monkeypatch, "FAIL", notes="Rebuild around one situation that changes.")
    for _ in range(3):
        run_serial_next_stage(engine, registry(), settings)
    rows = episode_rows(engine)
    assert len(rows) == MAX_DRAFTS_PER_DAY
    assert all(row.status == "REJECTED" and row.reviewed_by == "director" for row in rows)
    # Her approval alone is not in the channel's policy yet: nothing ships.
    spent = run_serial_next_stage(engine, registry(), settings)
    assert spent["artefacts"]["approved"] == 0
    assert f"ziua și-a folosit cele {MAX_DRAFTS_PER_DAY} ciorne" in spent["reason"]

    allow_director_approval(engine)
    prompts_before = len(writer.prompts)
    shipped = run_serial_next_stage(engine, registry(), settings)

    artefacts = shipped["artefacts"]
    assert artefacts["approved"] == 1 and artefacts.get("cap_shipped") is True, shipped
    assert artefacts["resumed"] == "cap" and artefacts["storyboard_id"], shipped
    assert "se expediază sub plafonul ciornelor" in shipped["reason"]
    assert len(writer.prompts) == prompts_before  # nothing written again
    rows = episode_rows(engine)
    assert [row.status for row in rows] == ["REJECTED", "REJECTED", "APPROVED"]
