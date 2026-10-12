"""The studio's lessons reach every writer of words a picture is made from (2026-10-12).

The Owner, 16:50, after 11.05 USD of the day's 19.50 went on redos and all three films still
failed quality control: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE
APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!» A lesson is how the
studio remembers why a defect happened. It is refused when it is no rule (empty, a report over
400 characters, about one film by its id, its title or a scene's number), given to the writers
each said once, and named in their instructions as rules — the serial's beat writer and its
showrunner included, whose payload sat at its cap and would have dropped them first.

The review of that work (a9f84ea), the same evening: a newer lesson that says an older one
again, or corrects it, replaces it (the older one used to win); a lesson is for its kind of
film (serial, factual or both); it is unverified until a picture made after it passes, and
withdrawn — giving back what it replaced — when the picture still shows the defect.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import MemoryRecord
from app.media import prompt_agent
from app.media.prompt_agent import (
    LESSON_MARKER,
    LESSON_OVERLAP,
    LESSONS_GIVEN,
    SCOPE_FACTUAL,
    SCOPE_SERIAL,
    SUPERSEDED_RO,
    UNVERIFIED_SUFFIX,
    confirm_prompt_lessons,
    lesson_is_general,
    lesson_overlap,
    lesson_words,
    lessons_rule,
    prompt_lessons,
    record_prompt_lesson,
    withdraw_prompt_lessons,
    write_shot_prompts,
)
from sqlalchemy import select
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
from test_serial_pipeline import (
    KAEL,
    SARAH,
    a_factual_storyboard,
    beats_for,
    inside_a_boundary,
    letters_day,
    written,
)

#: A factual film's lesson that is no rule for the serial, whose people face the viewer.
FROM_BEHIND = "Show people only from behind, small and distant, so no face is drawn."
#: A serial lesson that is no rule for a factual film.
FACING = "Both speakers face the viewer from the first moment to the last."

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


def live_rows(engine) -> list[MemoryRecord]:
    """The studio's live lesson rows, newest first."""
    with Session(engine) as session:
        return list(
            session.scalars(
                select(MemoryRecord)
                .where(
                    MemoryRecord.content.like(f"{LESSON_MARKER}%"),
                    MemoryRecord.invalidated_at.is_(None),
                )
                .order_by(MemoryRecord.created_at.desc())
            )
        )


def test_a_lesson_said_again_replaces_the_older_and_comes_back_to_the_top(engine):
    """Review of a9f84ea, 2026-10-12: the older lesson used to win, so a lesson learned again
    never came back into the twelve given. Said again (in other words or the same), the newer
    replaces the older — retired with its reason, never deleted — and stands first."""
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STACKED, source_id=str(uuid4())) is True
        assert record_prompt_lesson(session, LEDGER) is True
        assert record_prompt_lesson(session, STACKED_AGAIN) is True
    with Session(engine) as session:
        assert prompt_lessons(session) == [STACKED_AGAIN, LEDGER]
        retired = session.scalars(
            select(MemoryRecord).where(MemoryRecord.invalidated_at.is_not(None))
        ).all()
        assert [row.invalidation_reason for row in retired] == [SUPERSEDED_RO]
        assert retired[0].content.endswith(STACKED)
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, f"  {LEDGER}  ") is True, "learned again"
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER, STACKED_AGAIN], "back at the top"
    assert len(live_rows(engine)) == 2


def test_a_proven_lesson_learned_again_stays_proven(engine):
    """Learned again by a review whose picture is not made yet, a confirmed lesson comes back
    to the top still confirmed: the newest evidence adds to it, it does not unprove it."""
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, CAMERA, source_id=str(uuid4()))
        assert record_prompt_lesson(session, LEDGER)
        assert record_prompt_lesson(session, CAMERA, source_id=str(uuid4()), provisional=True)
    with Session(engine) as session:
        assert prompt_lessons(session) == [CAMERA, LEDGER]


def test_a_correction_is_kept_and_wins_over_the_rule_it_corrects(engine):
    """Review of a9f84ea, 2026-10-12: «Keep the camera static.» shared «camera» and «static»
    with the lesson that corrected it and, measured on the shorter one, kept it out. Measured
    from the new lesson's words, with the scaffold of every picture lesson as filler, the
    correction is a lesson of its own and the newest; one that changes a rule's words replaces
    it."""
    static = "Keep the camera static."
    frozen = (
        "The clip model reads 'static camera' as a frozen picture: ask for a locked-off camera "
        "while the subject moves."
    )
    assert lesson_words(static) == {"keep", "static"}
    assert lesson_overlap(frozen, static) < LESSON_OVERLAP
    assert lesson_words("Describe the camera movement of the shot in the clip prompt.") == set()
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, static)
        assert record_prompt_lesson(session, frozen)
    with Session(engine) as session:
        assert prompt_lessons(session) == [frozen, static]

    open_ledger = "Ask for the ledger open on the desk."
    closed_ledger = "Ask for the ledger closed on the desk."
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, open_ledger)
        assert record_prompt_lesson(session, closed_ledger)
    with Session(engine) as session:
        given = prompt_lessons(session)
    assert given[0] == closed_ledger and open_ledger not in given


def test_a_lesson_inside_a_longer_one_brings_the_longer_back(engine):
    """A new lesson the older one already says, and more, is not stored as less: the older
    text is stored again as the newest (refreshed), proven if either was."""
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER)
        assert record_prompt_lesson(session, CAMERA)
        assert record_prompt_lesson(session, "Pages and screens are blank.", provisional=True)
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER, CAMERA]
    assert sum(1 for row in live_rows(engine) if row.content.endswith(LEDGER)) == 1


def test_a_lesson_that_is_empty_a_report_or_about_one_film_is_refused(engine):
    ids = studio(engine)
    long = "word " * 79 + "wordy"  # 400 characters
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, "") is False
        assert record_prompt_lesson(session, "   \n ") is False
        assert record_prompt_lesson(session, long + "!") is False, "401 characters: a report"
        assert record_prompt_lesson(session, f"Storyboard {ids['board']}: {LEDGER}") is False
        head = ids["board"][:8]
        assert record_prompt_lesson(session, f"In {head} the ledger had words.") is False
        # Review of a9f84ea: a scene by its number, or the film by its title, is one film.
        assert record_prompt_lesson(session, "Scene 5 repeats the lab bench of scene 2.") is False
        assert (
            record_prompt_lesson(session, "In the zero script club the ledger had words.") is False
        )
        assert record_prompt_lesson(session, long) is True, "400 characters is a rule"
    with Session(engine) as session:
        assert prompt_lessons(session) == [long]


@pytest.mark.parametrize(
    ("lesson", "general"),
    [
        ("Scene 5 repeats the lab bench; ask for another room.", False),
        ("scena 4 are o literă pe registru", False),
        ("Pe registrul scenei 4 apar litere.", False),
        ("Shot 3 drifts to profile.", False),
        ("Scenes 1, 4 show the same desk.", False),
        ("Scene #2 is too dark.", False),
        ("The Zero Script Club ledger came back with lettering.", False),
        ("A shot 5 seconds long reads as a still; ask for one movement through it.", True),
        ("Every shot of 2-3 seconds needs one clear action.", True),
        ("A scene with a ledger needs the pages blank.", True),
        ("Pages and screens are blank.", True),
        ("Higgs fields are not drawn as glowing balls.", True),
    ],
)
def test_a_lesson_is_general_or_names_a_scene_or_a_film(lesson, general):
    titles = ["Storyboard: The Zero Script Club", "Higgs"]
    assert (lesson_is_general(lesson, titles) is None) is general, lesson_is_general(lesson, titles)


def test_a_lesson_is_kept_for_its_kind_of_film(engine):
    """Review of a9f84ea, 2026-10-12: a factual film's «show people only from behind» would
    have reached the serial's beat writer, whose fixed rule is «in frame, facing the viewer».
    A lesson is the serial's, the factual films' or both ("all", as every older row reads)."""
    from_behind, facing = FROM_BEHIND, FACING
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, from_behind, scope=SCOPE_FACTUAL)
        assert record_prompt_lesson(session, facing, scope=SCOPE_SERIAL)
        assert record_prompt_lesson(session, LEDGER)
        with pytest.raises(ValueError):
            record_prompt_lesson(session, CAMERA, scope="serial_episode")
    with Session(engine) as session:
        assert prompt_lessons(session, scope=SCOPE_SERIAL) == [LEDGER, facing]
        assert prompt_lessons(session, scope=SCOPE_FACTUAL) == [LEDGER, from_behind]
        assert prompt_lessons(session) == [LEDGER, facing, from_behind]
    stored = {row.content for row in live_rows(engine)}
    assert f"{LESSON_MARKER} [factual] {from_behind}" in stored
    assert f"{LESSON_MARKER} [all] {LEDGER}" in stored


def test_a_narrower_correction_of_a_studio_wide_lesson_leaves_it_to_the_other_kind(engine):
    """A serial lesson that corrects a studio-wide one is given in its place to the serial,
    and the factual films, which taught nothing against it, keep the older rule."""
    open_ledger = "Ask for the ledger open on the desk."
    closed_ledger = "Ask for the ledger closed on the desk."
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, open_ledger)
        assert record_prompt_lesson(session, closed_ledger, scope=SCOPE_SERIAL)
    with Session(engine) as session:
        assert prompt_lessons(session, scope=SCOPE_SERIAL) == [closed_ledger]
        assert prompt_lessons(session, scope=SCOPE_FACTUAL) == [open_ledger]


def test_an_unverified_lesson_is_said_so_confirmed_by_a_passed_picture_or_withdrawn(engine):
    """Review of a9f84ea, 2026-10-12: a lesson was never verified and never retired. The
    rewrite review's lesson is stored unverified (by her review's run id); a still made from
    that rewrite that passes with every finding gone confirms it, one that still shows the
    finding withdraws it — and the lesson it had replaced comes back."""
    review, other = str(uuid4()), str(uuid4())
    open_ledger = "Ask for the ledger open on the desk."
    closed_ledger = "Ask for the ledger closed on the desk."
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, CAMERA, source_id=other)
        assert record_prompt_lesson(session, open_ledger, source_id=other)
        assert record_prompt_lesson(
            session, closed_ledger, source_id=review, scope=SCOPE_SERIAL, provisional=True
        )
        assert record_prompt_lesson(session, LEDGER, source_id=review, provisional=True)
    with Session(engine) as session:
        given = prompt_lessons(session, scope=SCOPE_SERIAL)
    assert given == [
        CAMERA,
        f"{LEDGER}{UNVERIFIED_SUFFIX}",
        f"{closed_ledger}{UNVERIFIED_SUFFIX}",
    ], "the confirmed first, the unverified after, each newest first"

    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [review], "defectul a rămas") == 2
        assert withdraw_prompt_lessons(session, [other], "defectul a rămas") == 0, (
            "a confirmed lesson is not withdrawn"
        )
    with Session(engine) as session:
        assert prompt_lessons(session, scope=SCOPE_SERIAL) == [open_ledger, CAMERA]
        reasons = {
            row.invalidation_reason
            for row in session.scalars(select(MemoryRecord).where(MemoryRecord.source_id == review))
        }
    assert reasons == {"defectul a rămas"}

    learned = str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STACKED, source_id=learned, provisional=True)
    with Session(engine) as session, session.begin():
        assert confirm_prompt_lessons(session, [learned]) == 1
        assert confirm_prompt_lessons(session, [learned]) == 0, "already confirmed"
    with Session(engine) as session:
        given = prompt_lessons(session, scope=SCOPE_FACTUAL)
    assert given[0] == STACKED and all(not item.endswith(UNVERIFIED_SUFFIX) for item in given)


def test_a_withdrawn_correction_gives_back_the_lesson_it_replaced(engine):
    """A correction of the same scope retires the lesson it corrects; when the picture made
    after the correction still shows the defect, the correction is withdrawn and the older
    lesson stands again, as it was (proven, its own source)."""
    review = str(uuid4())
    open_ledger = "Ask for the ledger open on the desk."
    closed_ledger = "Ask for the ledger closed on the desk."
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, open_ledger, source_id=str(uuid4()))
        assert record_prompt_lesson(session, closed_ledger, source_id=review, provisional=True)
    with Session(engine) as session:
        assert prompt_lessons(session) == [f"{closed_ledger}{UNVERIFIED_SUFFIX}"]
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [review], "") == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [open_ledger]
    assert [row.content for row in live_rows(engine)] == [f"{LESSON_MARKER} [all] {open_ledger}"]


def test_the_writers_are_told_a_lesson_never_overrides_their_fixed_rules():
    rule = lessons_rule(["anything"])
    assert "(unverified)" in rule
    assert "the brief wins and that lesson does not apply here" in rule
    assert lessons_rule([]) == ""


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
        # A factual film's lesson is no rule for the serial's beats (review of a9f84ea).
        assert record_prompt_lesson(session, FROM_BEHIND, scope=SCOPE_FACTUAL)
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
    assert FROM_BEHIND not in prompt
    # The episode was cut to fit the cap; the lessons were not.
    assert len(data["episode"]["scenes"]) < count


@pytest.mark.usefixtures("staffed")
def test_the_factual_shot_plan_and_its_bible_are_given_the_lessons_as_rules(engine, monkeypatch):
    from app.factual import story_review

    board = a_factual_storyboard(engine)
    monkeypatch.setattr(story_review, "story_gate", lambda _session, _script_id: (True, ""))
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER)
        assert record_prompt_lesson(session, FROM_BEHIND, scope=SCOPE_FACTUAL, provisional=True)
        # The serial's lesson is no rule for a factual film (review of a9f84ea).
        assert record_prompt_lesson(session, FACING, scope=SCOPE_SERIAL)
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
        assert f"{FROM_BEHIND}{UNVERIFIED_SUFFIX}" in call["prompt"]
        assert FACING not in call["prompt"]


@pytest.mark.usefixtures("staffed")
def test_the_showrunner_writes_the_scene_lines_with_the_serials_lessons(engine, monkeypatch):
    """Review of a9f84ea, 2026-10-12: the showrunner's «scene», the first words a serial
    picture is made from (``writer_visual``), was written without the lessons the shot writer
    and every rewrite were given. The serial's lessons and the studio-wide ones reach it as
    rules, inside their own boundary; a factual film's do not."""
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER)
        assert record_prompt_lesson(session, FACING, scope=SCOPE_SERIAL, provisional=True)
        assert record_prompt_lesson(session, FROM_BEHIND, scope=SCOPE_FACTUAL)
    _, ids = letters_day(engine)
    seen: list[str] = []

    written(engine, monkeypatch, beats_for(ids, [KAEL, SARAH]), seen)

    prompt = seen[0]
    assert "PICTURE LESSONS" in prompt
    assert "The studio's lessons from earlier defects are rules: follow every one." in prompt
    assert inside_a_boundary(prompt, LEDGER)
    assert inside_a_boundary(prompt, f"{FACING}{UNVERIFIED_SUFFIX}")
    assert FROM_BEHIND not in prompt


@pytest.mark.usefixtures("staffed")
def test_without_lessons_the_showrunner_is_not_told_of_any(engine, monkeypatch):
    _, ids = letters_day(engine)
    seen: list[str] = []
    written(engine, monkeypatch, beats_for(ids, [KAEL, SARAH]), seen)
    assert "PICTURE LESSONS" not in seen[0] and "lessons from earlier defects" not in seen[0]


@pytest.mark.usefixtures("staffed")
def test_without_lessons_the_writers_are_not_told_of_any(engine, monkeypatch):
    board_id = serial_board(engine, monkeypatch)
    calls: list = []
    fake_editor(monkeypatch, shot_pack(len(scenes_of(engine, board_id))), calls)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    prompt = calls[0]["prompt"]
    assert "lessons from earlier defects" not in prompt and '"lessons"' not in prompt
