"""The Owner's one click, attacked: every way the serial's day can go wrong ends named.

His done-condition (2026-09-24): one click films today's episode and writes the script of
the next one. The steps S0-S6 each hold their own piece; this file drives the two serial
stages the way a click does (`run_serial_stage`, then `run_serial_next_stage` on today's
closed log) with the inputs a real day and a real model produce when they go wrong: an idle
day, a day of routine, a model that answers the old schema, a label inside a line, a
stranger in the cast, a Romanian answer, one event stretched over every beat, a same-day
re-run, the Owner's own hand, and no leave for the Director. Each must end in a state the
run card can name - a COMPLETED or SKIPPED stage with the reason that says why - and never
in a film or a script nobody can account for.
"""

from __future__ import annotations

import json

import pytest
from app.agents.services import seed_initial_workforce
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.publishing.services import seed_default_channels
from app.story.models import DailyStudioLog
from app.story.serial_stage import run_serial_next_stage, run_serial_stage
from app.story.services import (
    DraftRefused,
    business_date,
    close_daily_log,
    decide_episode,
    write_episode,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    KAEL,
    NEXT,
    SARAH,
    SPOKEN,
    TZ,
    YESTERDAY_NOON,
    a_day,
    add_event,
    allow_director_approval,
    answers_in_turn,
    beats_for,
    counting_director,
    episode_answer,
    episode_rows,
    fake_showrunner,
    letters_day,
    registry,
    roster_names,
    storyboard_count,
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


def a_click(engine, settings) -> tuple[dict, dict]:
    """The serial's half of one run: yesterday's episode, then tomorrow's script from today.

    Today's log is closed first, as the runbook's daily_log stage closes it before
    serial_next runs; a test that wants events today adds them before the click.
    """
    queue = run_serial_stage(engine, registry(), settings)
    with Session(engine) as session:
        closed = session.scalar(
            select(DailyStudioLog).where(DailyStudioLog.business_date == business_date(TZ))
        )
    if closed is None:
        close_daily_log(engine, TZ)
    return queue, run_serial_next_stage(engine, registry(), settings)


def named(outcome: dict, *words: str) -> None:
    """A stage that ended in a state the Owner can read: its status, and a reason with these
    words in it. A COMPLETED stage with no reason is the silent success this file refuses."""
    assert outcome["status"] in ("COMPLETED", "SKIPPED"), outcome
    assert outcome["reason"].strip(), outcome
    for word in words:
        assert word in outcome["reason"], (word, outcome["reason"])


# -------------------------------------------------------------------------- the day --


def test_an_idle_studio_writes_nothing_and_says_so(engine, staffed, settings, monkeypatch):
    close_daily_log(engine, TZ, business_date(TZ, YESTERDAY_NOON()))
    seen: list[str] = []
    fake_showrunner(monkeypatch, "", seen)

    queue, _next = a_click(engine, settings)

    named(queue, "liniștită")
    assert queue["artefacts"]["written"] == 0
    # Today holds only the seeding's own events (the workforce and the channels are created
    # today), so tomorrow's script is the only thing the click may write; nothing is filmed
    # and yesterday stays untold.
    named(_next)
    assert storyboard_count(engine) == 0
    yesterday = _log_id(engine, business_date(TZ, YESTERDAY_NOON()))
    assert all(row.log_id != yesterday for row in episode_rows(engine))


def _log_id(engine, date_iso: str) -> str | None:
    with Session(engine) as session:
        return session.scalar(
            select(DailyStudioLog.id).where(DailyStudioLog.business_date == date_iso)
        )


def test_a_day_of_routine_alone_is_a_quiet_day_to_the_stage(engine, staffed, settings, monkeypatch):
    for event_type in ("runbook.stage_finished", "agent.message_answered"):
        for _ in range(3):
            add_event(engine, event_type, YESTERDAY_NOON(), {"stage": "media"})
    close_daily_log(engine, TZ, business_date(TZ, YESTERDAY_NOON()))
    seen: list[str] = []
    fake_showrunner(monkeypatch, "", seen)

    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "liniștită")
    assert outcome["artefacts"]["written"] == 0 and seen == []


# ---------------------------------------------------------------------- the model --


def test_the_old_schema_without_labels_is_refused_twice_and_the_day_named(
    engine, staffed, settings, monkeypatch
):
    _, ids = letters_day(engine, YESTERDAY_NOON())
    v2 = json.dumps(
        {
            "title": "The Cut Runs Long",
            "beats": [
                {
                    "scene": "The edit suite at night.",
                    "dialogue": "The cut runs long.",
                    "event_ids": [i],
                }
                for i in ids
            ],
            "summary": "The cut runs long.",
        }
    )
    seen: list[str] = []
    fake_showrunner(monkeypatch, v2, seen)

    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "Episod respins", "formatul")
    assert outcome["artefacts"]["refused"] == 2 and len(seen) == 2
    # The retry was told why and shown what it wrote.
    assert "YOUR PREVIOUS ANSWER WAS REFUSED" in seen[1]
    assert episode_rows(engine) == []


def test_a_label_for_the_speaker_inside_the_text_is_taken_out(engine, staffed, monkeypatch):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["lines"][0]["text"] = f"Sarah: {SPOKEN[0]}"

    fake_showrunner(monkeypatch, episode_answer(beats, title="The Cut Runs Long"))
    log_id = _log_id(engine, business_date(TZ))
    episode = write_episode(engine, registry(), log_id)["episode"]

    first = episode["beats"][0]["lines"][0]
    assert first == {"speaker": SARAH, "text": SPOKEN[0]}


def test_a_label_naming_someone_else_inside_a_line_is_refused_not_reassigned(
    engine, staffed, monkeypatch
):
    """Sarah's line that starts "Kael:" is either Kael's line under the wrong speaker or
    Sarah saying his name with a colon; taking the label off and giving the words to Sarah,
    as it did, filmed one person's line in another's voice and told nobody."""
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[1]["lines"][0]["text"] = f"Kael: {SPOKEN[0]}"
    fake_showrunner(monkeypatch, episode_answer(beats, title="The Cut Runs Long"))

    with pytest.raises(DraftRefused) as refused:
        write_episode(engine, registry(), _log_id(engine, business_date(TZ)))

    assert "Kael" in str(refused.value) and "2" in str(refused.value)
    assert episode_rows(engine) == []


def test_a_stranger_in_the_cast_twice_ends_the_day_with_the_allowed_names(
    engine, staffed, settings, monkeypatch
):
    _, ids = letters_day(engine, YESTERDAY_NOON())
    beats = beats_for(ids, ["Mara (Intern)", KAEL])
    seen: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats, title="The Cut Runs Long"), seen)

    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "Episod respins", "Mara (Intern)", "Numele permise")
    assert outcome["artefacts"]["refused"] == 2
    assert episode_rows(engine) == []


def test_a_romanian_episode_is_rejected_by_the_computed_check_and_named(
    engine, staffed, settings, monkeypatch
):
    _, ids = letters_day(engine, YESTERDAY_NOON())
    beats = beats_for(ids, [SARAH, KAEL])
    for beat in beats:
        beat["lines"] = [
            {"speaker": SARAH, "text": "Bună dimineața, unde suntem cu numărul de azi, echipă?"},
            {"speaker": KAEL, "text": "Mai întâi dovezile, apoi părerea, și niciodată invers."},
        ]
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats, title="Tăietura e prea lungă"))
    counting_director(monkeypatch, "PASS", reviewed)
    allow_director_approval(engine)

    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "respins de Director", "engleză")
    # The computed check refused it before any model was asked to read it.
    assert reviewed == []
    assert {row.status for row in episode_rows(engine)} == {"REJECTED"}
    assert storyboard_count(engine) == 0


def test_one_event_stretched_over_every_beat_is_rejected_and_named(
    engine, staffed, settings, monkeypatch
):
    _, ids = letters_day(engine, YESTERDAY_NOON())
    beats = beats_for([ids[0]], [SARAH, KAEL])
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats, title="The Cut Runs Long"))
    counting_director(monkeypatch, "PASS", reviewed)
    allow_director_approval(engine)

    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "respins de Director", "un singur eveniment")
    assert reviewed == [] and storyboard_count(engine) == 0


# ------------------------------------------------------------------- the calendar --


def test_a_same_day_rerun_films_and_writes_nothing_new(engine, staffed, settings, monkeypatch):
    allow_director_approval(engine)
    yesterday, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, yesterday["id"])
    _, today_ids = letters_day(engine)
    written: list[str] = []
    reviewed: list[str] = []
    answers_in_turn(
        monkeypatch,
        [
            episode_answer(beats_for(ids, names), title="The Number Before Morning"),
            episode_answer(beats_for(today_ids, [SARAH, KAEL]), title="The Cut Runs Long"),
        ],
        written,
    )
    counting_director(monkeypatch, "PASS", reviewed)
    first_queue, first_next = a_click(engine, settings)
    assert first_queue["artefacts"]["storyboard_id"], first_queue
    assert first_next["artefacts"]["approved"] == 1, first_next

    queue, again = a_click(engine, settings)

    named(queue)
    named(again, "deja scris", "The Cut Runs Long")
    assert queue["artefacts"]["written"] == again["artefacts"]["written"] == 0
    assert queue["artefacts"]["storyboard_id"] is None
    assert len(written) == 2 and len(reviewed) == 2
    # Yesterday's storyboard from the first click's serial stage, today's from its serial_next
    # (readied the same evening since 2026-10-11); the second click built neither again.
    assert storyboard_count(engine) == 2


def test_without_the_directors_leave_a_click_names_what_waits_for_the_owner(
    engine, staffed, settings, monkeypatch
):
    """His data today: director_may_approve_episodes is off. The click writes and reads
    yesterday's episode and leaves it for him; tomorrow's script is not written beside it,
    and both stages say so - the done-condition needs his approval, or her leave."""
    yesterday, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, yesterday["id"])
    letters_day(engine)
    written: list[str] = []
    reviewed: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)), written)
    counting_director(monkeypatch, "PASS", reviewed)

    queue, tomorrow = a_click(engine, settings)

    named(queue, "așteaptă aprobarea ta")
    named(tomorrow, "Scenariul de mâine nu se scrie", "așteaptă aprobarea ta")
    assert tomorrow["artefacts"]["written"] == 0
    assert len(written) == 1 and storyboard_count(engine) == 0


def test_the_owners_hand_on_a_draft_nobody_read_readies_it_and_the_record_says_so(
    engine, staffed, settings, monkeypatch
):
    """He may approve a draft the Director never read (her answer could not be parsed).
    His approval is the authority; the next click readies it and names him."""
    yesterday, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, yesterday["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    log_id = _log_id(engine, business_date(TZ, YESTERDAY_NOON()))
    episode = write_episode(engine, registry(), log_id)["episode"]

    decide_episode(engine, episode["id"], True, "Merge.")
    outcome = run_serial_stage(engine, registry(), settings)

    named(outcome, "aprobat de tine", "pregătit de filmare")
    assert outcome["artefacts"]["resumed"] == "storyboard"
    assert storyboard_count(engine) == 1


# -------------------------------------------------------------------------- the brief --


def test_the_brief_asks_for_enough_beats_to_reach_its_own_length(engine, staffed, monkeypatch):
    """Five beats of at most 22 words are 110 words, 44 seconds: under the 45 the review
    holds the episode to. A brief that allowed five beats asked for an episode it would fail."""
    from app.story.review import MIN_SECONDS, WORDS_PER_SECOND
    from app.story.services import WORDS_PER_BEAT

    _, ids = letters_day(engine)
    seen: list[str] = []
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, [SARAH, KAEL])), seen)
    write_episode(engine, registry(), _log_id(engine, business_date(TZ)))

    (prompt,) = seen
    floor = -(-MIN_SECONDS * WORDS_PER_SECOND // WORDS_PER_BEAT[1])
    assert f"{int(floor)} to 8 beats" in prompt, prompt[:900]
    assert NEXT["premise"] not in prompt  # no plan was handed: this is the first episode


def test_a_click_after_the_owner_approved_names_the_day_already_told(
    engine, staffed, settings, monkeypatch
):
    """His policy's day: the click leaves yesterday's episode for him, he approves it (his
    button readies it), and he clicks again. The second serial stage has no new day to tell,
    and said "no day has public events" while the media stage filmed his episode in the same
    run. It names the day already told instead."""
    yesterday, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, yesterday["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names)))
    counting_director(monkeypatch, "PASS", [])
    first = run_serial_stage(engine, registry(), settings)
    decide_episode(engine, first["artefacts"]["episode_id"], True, "Merge.")
    from app.media.serial_storyboard import storyboard_from_episode

    storyboard_from_episode(engine, first["artefacts"]["episode_id"], "owner")

    again = run_serial_stage(engine, registry(), settings)

    named(again, business_date(TZ, YESTERDAY_NOON()), "O zi la studio")
    assert "nu are evenimente publice" not in again["reason"], again["reason"]
    assert again["artefacts"]["written"] == 0
