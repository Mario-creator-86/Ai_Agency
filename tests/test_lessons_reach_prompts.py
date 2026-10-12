"""The studio's lessons reach every writer of words a picture is made from (2026-10-12).

The Owner, 16:50, after 11.05 USD of the day's 19.50 went on redos and all three films still
failed quality control: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE
APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!» A lesson is how the
studio remembers why a defect happened. It is kept once (a near-duplicate is skipped), refused
when it is no rule (empty, a report over 400 characters, or about one film by its id), given to
the writers newest first and each said once, and named in their instructions as rules — the
serial's beat writer included, whose payload sat at its cap and would have dropped them first.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import MemoryRecord
from app.media import prompt_agent
from app.media.prompt_agent import (
    LESSON_MARKER,
    LESSONS_GIVEN,
    lesson_overlap,
    prompt_lessons,
    record_prompt_lesson,
    write_shot_prompts,
)
from sqlalchemy.orm import Session
from test_events_feed import studio
from test_serial_look import (  # noqa: F401 - `staffed` is a fixture
    fake_editor,
    models,
    scenes_of,
    serial_board,
    shot_pack,
    staffed,
)
from test_serial_pipeline import a_factual_storyboard

#: The first episode's defect, as the Director would learn it (f06808c9, scenes 3, 4 and 7).
STACKED = (
    "A chain of moments in one still prompt is drawn as the same picture stacked three times; "
    "describe one moment."
)
#: The same lesson, said again in other words a day later.
STACKED_AGAIN = (
    "Describe one moment per still: a chain of moments is drawn as stacked panels of the same "
    "picture."
)
LEDGER = (
    "Pages and screens are blank: a ledger drawn for a number comes back with lettering the "
    "vision gate reads as writing."
)
CAMERA = "Asking for a slow push in produced a static shot; say 'dolly in' instead."


def kept(engine, text: str, minute: int) -> None:
    """One lesson as the studio's memory holds it, written at 10:<minute>."""
    with Session(engine) as session, session.begin():
        session.add(
            MemoryRecord(
                id=str(uuid4()),
                agent_id=None,
                memory_class="STRATEGY",
                content=f"{LESSON_MARKER} {text}",
                source_type="system",
                created_at=f"2026-10-12T10:{minute:02d}:00+00:00",
            )
        )


def distinct(number: int) -> str:
    """A lesson that shares no meaning with any other this file writes."""
    words = ("amber", "basalt", "cobalt", "dune", "ember", "fjord", "glacier", "harbor")
    return f"Lesson {number}: {words[number % 8]}{number} gravel{number} quartz{number}."


def test_two_lessons_said_in_other_words_overlap_and_two_different_ones_do_not():
    assert lesson_overlap(STACKED, STACKED_AGAIN) >= 0.6
    assert lesson_overlap(STACKED, LEDGER) < 0.6
    assert lesson_overlap(CAMERA, LEDGER) < 0.6
    # Case, accents and punctuation are not what a lesson says.
    assert lesson_overlap("Fără literă pe registru!", "fara litera pe REGISTRU") == 1.0


def test_the_writers_are_given_the_newest_twelve_lessons_each_said_once(engine):
    for number in range(1, 14):
        kept(engine, distinct(number), 20 - number)  # 1 is the newest of these
    kept(engine, STACKED, 30)
    kept(engine, STACKED_AGAIN, 31)  # the newest of all, and the same lesson as STACKED

    with Session(engine) as session:
        given = prompt_lessons(session)

    assert LESSONS_GIVEN == 12 and len(given) == 12
    assert given[0] == STACKED_AGAIN, "newest first"
    assert STACKED not in given, "the same lesson is not given twice"
    assert given[1:] == [distinct(number) for number in range(1, 12)]


def test_a_lesson_said_again_is_skipped_and_a_new_one_is_kept(engine):
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STACKED, source_id=str(uuid4())) is True
        assert record_prompt_lesson(session, STACKED_AGAIN) is False
        assert record_prompt_lesson(session, f"  {STACKED}  ") is False
        assert record_prompt_lesson(session, LEDGER) is True
    with Session(engine) as session:
        assert sorted(prompt_lessons(session)) == sorted([LEDGER, STACKED])


def test_a_lesson_that_is_empty_a_report_or_about_one_film_is_refused(engine):
    ids = studio(engine)
    long = "word " * 79 + "wordy"  # 400 characters
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, "") is False
        assert record_prompt_lesson(session, "   \n ") is False
        assert record_prompt_lesson(session, long + "!") is False, "401 characters: a report"
        assert record_prompt_lesson(session, f"Storyboard {ids['board']}: {LEDGER}") is False
        head = ids["board"][:8]
        assert record_prompt_lesson(session, f"In {head} scene 4 the ledger had words.") is False
        assert record_prompt_lesson(session, long) is True, "400 characters is a rule"
    with Session(engine) as session:
        assert prompt_lessons(session) == [long]


@pytest.mark.usefixtures("staffed")
def test_the_serial_beat_writer_is_given_every_lesson_as_rules_even_at_its_cap(engine, monkeypatch):
    """The serial's shot plan (the beats' action, in_frame, ending_frame) is written from its
    lessons, named in the instructions, kept whole at the head of the data even when the
    episode has to be cut to fit (its payload stood at 14-15 of its 16 thousand characters)."""
    board_id = serial_board(engine, monkeypatch)
    count = len(scenes_of(engine, board_id))
    with Session(engine) as session, session.begin():
        for lesson in (STACKED, LEDGER, CAMERA):
            assert record_prompt_lesson(session, lesson)
    calls: list = []
    fake_editor(monkeypatch, shot_pack(count), calls)
    monkeypatch.setattr(prompt_agent, "MAX_SHOTS_PAYLOAD_CHARS", 3000)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    prompt = next(c["prompt"] for c in calls if c["task"] == "shot_prompts")
    rules, boundary = prompt.split('<untrusted_source_evidence hash="approved-film">\n', 1)
    assert "The studio's lessons from earlier defects are rules: follow every one." in rules
    data = json.loads(boundary.rsplit("\n</untrusted_source_evidence>", 1)[0])
    assert sorted(data["lessons"]) == sorted([CAMERA, LEDGER, STACKED]), "every one, whole"
    assert list(data)[0] == "lessons", "the rules come before the episode"
    # The episode was cut to fit the cap; the lessons were not.
    assert len(data["episode"]["scenes"]) < count


@pytest.mark.usefixtures("staffed")
def test_the_factual_shot_plan_and_its_bible_are_given_the_lessons_as_rules(engine, monkeypatch):
    from app.factual import story_review

    board = a_factual_storyboard(engine)
    monkeypatch.setattr(story_review, "story_gate", lambda _session, _script_id: (True, ""))
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER)
    count = len(scenes_of(engine, board["id"]))
    answer = {"style": "documentary realism", "palette": "slate blue", **shot_pack(count)}
    calls: list = []
    fake_editor(monkeypatch, answer, calls)

    write_shot_prompts(engine, models(), board["id"], str(uuid4()))

    assert [c["task"] for c in calls] == ["visual_bible", "shot_prompts"]
    for call in calls:
        assert (
            "The studio's lessons from earlier defects are rules: follow every one."
            in (call["prompt"])
        )
        assert LEDGER in call["prompt"]


@pytest.mark.usefixtures("staffed")
def test_without_lessons_the_writers_are_not_told_of_any(engine, monkeypatch):
    board_id = serial_board(engine, monkeypatch)
    calls: list = []
    fake_editor(monkeypatch, shot_pack(len(scenes_of(engine, board_id))), calls)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    prompt = calls[0]["prompt"]
    assert "lessons from earlier defects" not in prompt and '"lessons"' not in prompt
