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

The review of 68fa0b4, later that evening: a negated correction passed for the rule it
corrects; a short lesson shrank to one word and swallowed others; a correction sharing few
words with its rule did not displace it; a refresh moved a lesson to its newest source; a
refuted lesson was learned again at once; unverified lessons were crowded out; one phrase of
any film's title refused a general rule. The Director now reads each new lesson beside the
live ones (free) and decides what it repeats or corrects; the words decide only without her.
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
    LESSON_READ_EVENT,
    LESSONS_GIVEN,
    LESSONS_RULE,
    REFUTED_PREFIX,
    REFUTED_RULE,
    SCOPE_FACTUAL,
    SCOPE_SERIAL,
    SUPERSEDED_RO,
    UNVERIFIED_SUFFIX,
    confirm_prompt_lessons,
    fit_with_lessons,
    lesson_is_general,
    lesson_overlap,
    lesson_words,
    lessons_rule,
    prompt_lessons,
    reconcile_prompt_lessons,
    record_prompt_lesson,
    withdraw_prompt_lessons,
    write_shot_prompts,
)
from app.models import DomainEvent
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
    # Without a Director to read them the words decide (`_read_by_words`).
    assert reconcile_prompt_lessons(engine, None) == 2
    with Session(engine) as session:
        assert prompt_lessons(session) == [STACKED_AGAIN, LEDGER]
        retired = session.scalars(
            select(MemoryRecord).where(MemoryRecord.invalidated_at.is_not(None))
        ).all()
        assert {row.invalidation_reason for row in retired if row.content.endswith(STACKED)} == {
            SUPERSEDED_RO
        }
    why: list[str] = []
    with Session(engine) as session, session.begin():
        # Learned again word for word: ABSORBED, the older row comes back with this source.
        assert record_prompt_lesson(session, f"  {LEDGER}  ", reasons=why) is False
    assert "deja știută" in why[0]
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER, STACKED_AGAIN], "back at the top"
    assert len(live_rows(engine)) == 2


def test_a_proven_lesson_learned_again_stays_proven(engine):
    """Learned again by a review whose picture is not made yet, a confirmed lesson comes back
    to the top still confirmed: the newest evidence adds to it, it does not unprove it."""
    later = str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, CAMERA, source_id=str(uuid4()))
        assert record_prompt_lesson(session, LEDGER)
        assert not record_prompt_lesson(session, CAMERA, source_id=later, provisional=True)
    with Session(engine) as session:
        assert prompt_lessons(session) == [CAMERA, LEDGER]
    # The later source's failure never withdraws a proven lesson (review of 68fa0b4).
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [later], "defectul a rămas") == 0
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
    first, second = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER, source_id=first, provisional=True)
        assert record_prompt_lesson(session, CAMERA)
        assert record_prompt_lesson(
            session, "Pages and screens are blank.", source_id=second, provisional=True
        )
    assert reconcile_prompt_lessons(engine, None) == 2
    with Session(engine) as session:
        assert prompt_lessons(session) == [CAMERA, f"{LEDGER}{UNVERIFIED_SUFFIX}"]
    (row,) = [row for row in live_rows(engine) if row.content.endswith(LEDGER)]
    # The older text is never stored under the new source alone (review of 68fa0b4): its own
    # source stays the row's, and the new one joins its sources.
    assert row.source_id == first
    assert f"[from:{first[:8]},{second[:8]}]" in row.content
    with Session(engine) as session, session.begin():
        assert confirm_prompt_lessons(session, [second]) == 1, "any source that passes proves it"
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER, CAMERA]


def test_a_lesson_that_is_empty_a_report_or_about_one_film_is_refused(engine):
    ids = studio(engine)
    long = "word " * 799 + "wordy"  # 4000 characters
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, "") is False
        assert record_prompt_lesson(session, "   \n ") is False
        assert record_prompt_lesson(session, long + "!") is False, "4001 characters: a report"
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
    # Before anyone read the new lessons both rules are given: an unverified lesson never hides
    # a confirmed one (review of 68fa0b4), and the writers are told the newer wins.
    assert given == [
        open_ledger,
        CAMERA,
        f"{LEDGER}{UNVERIFIED_SUFFIX}",
        f"{closed_ledger}{UNVERIFIED_SUFFIX}",
    ], "the confirmed first, the unverified after, each newest first"
    reconcile_prompt_lessons(engine, None)
    with Session(engine) as session:
        given = prompt_lessons(session, scope=SCOPE_SERIAL)
        # The studio-wide lesson the serial's corrected stays the factual films' rule.
        assert prompt_lessons(session, scope=SCOPE_FACTUAL)[:2] == [open_ledger, CAMERA]
    assert given == [
        CAMERA,
        f"{LEDGER}{UNVERIFIED_SUFFIX}",
        f"{closed_ledger}{UNVERIFIED_SUFFIX}",
    ]

    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [review], "defectul a rămas") == 2
        assert withdraw_prompt_lessons(session, [other], "defectul a rămas") == 0, (
            "a confirmed lesson is not withdrawn"
        )
    with Session(engine) as session:
        # The lessons a picture refuted are said apart, as refuted diagnoses.
        assert prompt_lessons(session, scope=SCOPE_SERIAL) == [
            open_ledger,
            CAMERA,
            f"{REFUTED_PREFIX}{LEDGER}",
            f"{REFUTED_PREFIX}{closed_ledger}",
        ]
        reasons = {
            row.invalidation_reason
            for row in session.scalars(select(MemoryRecord).where(MemoryRecord.source_id == review))
            if str(row.invalidation_reason or "").startswith("retrasă")
        }
    assert reasons == {"retrasă: defectul a rămas"}
    assert sum(1 for row in live_rows(engine) if row.content.endswith(open_ledger)) == 1

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
    reconcile_prompt_lessons(engine, None)
    with Session(engine) as session:
        assert prompt_lessons(session) == [f"{closed_ledger}{UNVERIFIED_SUFFIX}"]
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [review], "") == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [open_ledger, f"{REFUTED_PREFIX}{closed_ledger}"]
    assert [row.content for row in live_rows(engine)] == [f"{LESSON_MARKER} [all] {open_ledger}"]


def test_the_writers_are_told_a_lesson_never_overrides_their_fixed_rules():
    rule = lessons_rule(["anything"])
    assert "(unverified)" in rule
    assert "the brief wins and that lesson does not apply here" in rule
    assert lessons_rule([]) == ""
    # Review of 68fa0b4: «unless a confirmed lesson says otherwise» let the old rule win.
    assert "a newer lesson that contradicts an older one wins" in rule
    assert "unless a confirmed lesson says otherwise" not in rule
    assert REFUTED_RULE not in rule
    assert lessons_rule([f"{REFUTED_PREFIX}x"]) == REFUTED_RULE
    assert lessons_rule(["a", f"{REFUTED_PREFIX}x"]) == LESSONS_RULE + REFUTED_RULE


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


# ------------------------------------------------------------------ the review of 68fa0b4

STATIC = "Keep the camera static."
NOT_STATIC = "Do not keep the camera static."
FROZEN = (
    "The clip model reads a locked camera as a frozen picture: ask for a slow drift while the "
    "subject moves."
)


def her_prompt(prompt: str) -> tuple[str, dict[str, int]]:
    """The new lesson her reading is about, and the live lessons by the ids her prompt gives."""
    data = json.loads(
        prompt.split('<untrusted_source_evidence hash="prompt-lessons">\n', 1)[1].rsplit(
            "\n</untrusted_source_evidence>", 1
        )[0]
    )
    return data["new_lesson"]["lesson"], {
        item["lesson"]: item["id"] for item in data["live_lessons"]
    }


def directors_reading(monkeypatch, answer) -> list[dict]:
    """Her reading, faked (`agents.structured.structured_run`): ``answer(new, ids)`` gives the
    relations, None for an answer that did not validate twice. Records what she was asked."""
    from app.agents import structured

    asked: list[dict] = []

    def fake(
        engine, registry, agent_id, task_type, prompt, template, correlation, schema, hint, **_
    ):
        asked.append({"task": task_type, "prompt": prompt, "agent_id": agent_id})
        relations = answer(*her_prompt(prompt))
        run = {"id": str(uuid4()), "status": "SUCCEEDED"}
        if relations is None:
            return None, {**run, "error_detail": "răspuns refuzat de forma cerută"}, None
        return schema.model_validate({"relations": relations}), run, None

    monkeypatch.setattr(structured, "structured_run", fake)
    return asked


def read_events(engine) -> list[dict]:
    with Session(engine) as session:
        return [
            dict(event.payload)
            for event in session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == LESSON_READ_EVENT)
                .order_by(DomainEvent.timestamp)
            )
        ]


def test_a_negated_correction_is_never_the_rule_it_corrects_said_again(engine):
    """Review of 68fa0b4: «not» and «never» were filler and «no»/«do» too short to count, so
    «Do not keep the camera static.» passed for «Keep the camera static.» said again — the
    wrong rule was refreshed under the correction's run and confirmed by its success."""
    for said in (
        NOT_STATIC,
        "Don't keep the camera static.",
        "It doesn’t keep the camera static.",
        "Never keep the camera static.",
        "No static camera.",
    ):
        assert "not" in lesson_words(said), said
    assert "not" not in lesson_words(STATIC)
    old, new = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STATIC, source_id=old)
        assert record_prompt_lesson(session, NOT_STATIC, source_id=new, provisional=True)
    reconcile_prompt_lessons(engine, None)
    with Session(engine) as session:
        assert prompt_lessons(session) == [f"{NOT_STATIC}{UNVERIFIED_SUFFIX}"]
    with Session(engine) as session, session.begin():
        assert confirm_prompt_lessons(session, [old]) == 0, "the corrected rule is gone"
        assert confirm_prompt_lessons(session, [new]) == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [NOT_STATIC]
    (read,) = read_events(engine)
    assert read["read_by"] == "words" and read["corrects"] == [STATIC]


def test_a_short_lesson_neither_swallows_nor_retires_unrelated_ones(engine):
    """Review of 68fa0b4: «Keep the camera still.» is {keep} once the scaffold is filler, and
    one word swallowed or retired unrelated lessons. A lesson of fewer than three content words
    is compared word for word only."""
    still = "Keep the camera still."
    longer = "Keep the subject still while the camera moves along the desk."
    faces = "Keep faces turned away from the lens in wide office shots."
    assert lesson_words(still) == {"keep"}
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, longer)
        assert record_prompt_lesson(session, still, source_id=str(uuid4()))
        assert record_prompt_lesson(session, faces)
    reconcile_prompt_lessons(engine, None)
    with Session(engine) as session:
        assert sorted(prompt_lessons(session)) == sorted([longer, still, faces])
    why: list[str] = []
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, "keep the camera STILL", reasons=why) is False
    assert why and len(live_rows(engine)) == 3


@pytest.mark.usefixtures("staffed")
def test_the_director_reads_a_new_lesson_and_retires_the_rule_it_corrects(engine, monkeypatch):
    """Review of 68fa0b4: a correction that shares few words with the rule it corrects did not
    displace it, both were given, and the rule said the old confirmed one won. She reads each
    new lesson beside the live ones (free) and decides; what she corrects is retired, and given
    back when a picture refutes her correction."""
    from app.agents.memory import agent_for_role

    old, new = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STATIC, source_id=old)
        assert record_prompt_lesson(session, LEDGER, source_id=str(uuid4()))
        assert record_prompt_lesson(session, FROZEN, source_id=new, provisional=True)
    assert lesson_overlap(FROZEN, STATIC) < LESSON_OVERLAP, "the words alone keep both"
    with Session(engine) as session:
        before = prompt_lessons(session)
        director = agent_for_role(session, "Director").id
    assert STATIC in before and f"{FROZEN}{UNVERIFIED_SUFFIX}" in before

    def answer(lesson: str, ids: dict[str, int]) -> list[dict]:
        if lesson != FROZEN:
            return [{"id": number, "relation": "UNRELATED"} for number in ids.values()]
        return [
            {"id": ids[STATIC], "relation": "corrects", "why": "regula veche îngheța cadrul"},
            {"id": ids[LEDGER], "relation": "UNRELATED"},
        ]

    asked = directors_reading(monkeypatch, answer)
    assert reconcile_prompt_lessons(engine, models(), str(uuid4())) == 2
    assert [item["task"] for item in asked] == ["prompt_lesson_reading"] * 2
    assert {item["agent_id"] for item in asked} == {director}
    assert inside_a_boundary(asked[-1]["prompt"], STATIC)
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER, f"{FROZEN}{UNVERIFIED_SUFFIX}"]
    read = next(item for item in read_events(engine) if item["lesson"] == FROZEN)
    assert read["read_by"] == "director" and read["agent_id"] == director
    assert read["corrects"] == [STATIC] and read["repeats"] == []
    # Nothing new to read: she is not asked again.
    assert reconcile_prompt_lessons(engine, models()) == 0 and len(asked) == 2
    # A picture refutes the correction: the rule it corrected is given back.
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [new], "defectul a rămas") == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [STATIC, LEDGER, f"{REFUTED_PREFIX}{FROZEN}"]


@pytest.mark.usefixtures("staffed")
def test_a_lesson_she_reads_as_said_again_is_kept_once_with_every_source(engine, monkeypatch):
    first, second = str(uuid4()), str(uuid4())
    again = "Monitors and sheets of paper come back lettered unless they are asked for empty."
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER, source_id=first, provisional=True)
        assert record_prompt_lesson(session, again, source_id=second, provisional=True)
    directors_reading(
        monkeypatch,
        lambda lesson, ids: [{"id": ids[LEDGER], "relation": "REPEATS"}] if lesson == again else [],
    )
    assert reconcile_prompt_lessons(engine, models()) == 1
    (row,) = live_rows(engine)
    assert row.content.endswith(LEDGER), "the longer words are kept"
    assert first[:8] in row.content and second[:8] in row.content
    with Session(engine) as session, session.begin():
        assert confirm_prompt_lessons(session, [first]) == 1
        assert withdraw_prompt_lessons(session, [second], "defectul a rămas") == 0
    with Session(engine) as session:
        assert prompt_lessons(session) == [LEDGER]
    (read,) = read_events(engine)
    assert read["repeats"] == [LEDGER] and read["corrects"] == []


@pytest.mark.usefixtures("staffed")
def test_when_her_answer_does_not_come_the_words_decide_and_it_is_said(engine, monkeypatch):
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STACKED)
        assert record_prompt_lesson(session, STACKED_AGAIN)
    asked = directors_reading(monkeypatch, lambda lesson, ids: None)
    assert reconcile_prompt_lessons(engine, models()) == 1 and len(asked) == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [STACKED_AGAIN]
    (read,) = read_events(engine)
    assert read["read_by"] == "words" and read["corrects"] == [STACKED]
    assert "forma cerută" in read["unavailable"]


@pytest.mark.usefixtures("staffed")
def test_the_shot_writer_has_her_read_the_new_lessons_first(engine, monkeypatch):
    """Every writer of words a picture is made from has the new lessons read before it reads
    them: the rule her reading retired never reaches the shot plan."""
    board_id = serial_board(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STATIC)
        assert record_prompt_lesson(session, FROZEN, provisional=True)
    asked = directors_reading(
        monkeypatch,
        lambda lesson, ids: (
            [{"id": ids[STATIC], "relation": "CORRECTS"}] if lesson == FROZEN else []
        ),
    )
    calls: list = []
    fake_editor(monkeypatch, shot_pack(len(scenes_of(engine, board_id))), calls)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    assert asked, "she read the new lesson before the shots were written"
    prompt = next(c["prompt"] for c in calls if c["task"] == "shot_prompts")
    assert f"{FROZEN}{UNVERIFIED_SUFFIX}" in prompt and STATIC not in prompt


def test_a_lesson_learned_twice_keeps_both_sources_until_both_failed(engine):
    """Review of 68fa0b4: a refresh moved the lesson to its newest source, so the first review's
    passing picture could no longer confirm it and another's failure deleted it. Every source
    is kept: one that passes proves it, and it is withdrawn only once all of them failed."""
    first, second = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER, source_id=first, provisional=True)
        assert not record_prompt_lesson(session, LEDGER, source_id=second, provisional=True)
    (row,) = live_rows(engine)
    assert row.source_id == first and f"[from:{first[:8]},{second[:8]}]" in row.content
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [second], "defectul a rămas") == 0
    (row,) = live_rows(engine)
    assert f"!{second[:8]}" in row.content, "the failure is written on it"
    with Session(engine) as session:
        assert prompt_lessons(session) == [f"{LEDGER}{UNVERIFIED_SUFFIX}"]
    with Session(engine) as session, session.begin():
        assert withdraw_prompt_lessons(session, [first], "defectul a rămas") == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [f"{REFUTED_PREFIX}{LEDGER}"]

    proven, failing = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, CAMERA, source_id=proven, provisional=True)
        assert not record_prompt_lesson(session, CAMERA, source_id=failing, provisional=True)
        assert confirm_prompt_lessons(session, [proven]) == 1
        assert withdraw_prompt_lessons(session, [failing], "defectul a rămas") == 0
    with Session(engine) as session:
        assert prompt_lessons(session)[0] == CAMERA


def test_a_refuted_lesson_is_not_learned_again_and_is_told_as_a_refuted_diagnosis(engine):
    """Review of 68fa0b4: a lesson a picture had refuted was learned again at once, and the
    same wrong fix was paid for again. It is refused, in Romanian, and the writers are told it
    as a refuted diagnosis — set apart from the rules they follow."""
    taught = str(uuid4())
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER, source_id=taught, provisional=True)
        assert withdraw_prompt_lessons(session, [taught], "defectul a rămas") == 1
    why: list[str] = []
    again = LEDGER.replace("blank:", "blank;").replace("writing.", "writing!")
    opposite = (
        "Do not ask for blank pages: a ledger drawn for a number comes back with lettering the "
        "vision gate reads as writing."
    )
    with Session(engine) as session, session.begin():
        assert not record_prompt_lesson(session, LEDGER, source_id=str(uuid4()), reasons=why)
        assert not record_prompt_lesson(session, again, provisional=True, reasons=why)
        # The opposite direction is a lesson of its own.
        assert record_prompt_lesson(session, opposite, provisional=True)
    assert len(why) == 2 and all("a mai fost învățată" in item for item in why)
    with Session(engine) as session:
        given = prompt_lessons(session)
    assert given == [f"{opposite}{UNVERIFIED_SUFFIX}", f"{REFUTED_PREFIX}{LEDGER}"]
    data = fit_with_lessons({"film": {"title": "x"}}, given, 10000)
    assert list(data)[:2] == ["lessons", "refuted_diagnoses"]
    assert data["refuted_diagnoses"] == [LEDGER] and data["lessons"] == [given[0]]
    assert lessons_rule(given) == LESSONS_RULE + REFUTED_RULE


def test_the_newest_unverified_lessons_keep_a_third_of_the_places(engine):
    """Review of 68fa0b4: twelve confirmed lessons filled every place, and what the Director's
    QC and the editorial review had just learned never reached a writer."""
    for number in range(1, 15):
        kept(engine, distinct(number), number)
    with Session(engine) as session, session.begin():
        for number in range(20, 26):
            assert record_prompt_lesson(session, distinct(number), provisional=True)
    with Session(engine) as session:
        given = prompt_lessons(session)
    assert len(given) == LESSONS_GIVEN
    assert given[:8] == [distinct(number) for number in range(14, 6, -1)]
    assert given[8:] == [f"{distinct(number)}{UNVERIFIED_SUFFIX}" for number in range(25, 21, -1)]
    # With fewer unverified, the confirmed fill the rest.
    with Session(engine) as session:
        assert len([g for g in prompt_lessons(session, 20) if g.endswith(UNVERIFIED_SUFFIX)]) == 6


def test_an_unverified_lesson_never_hides_a_confirmed_one(engine):
    kept(engine, STACKED, 10)
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, STACKED_AGAIN, provisional=True)
    with Session(engine) as session:
        assert prompt_lessons(session) == [STACKED, f"{STACKED_AGAIN}{UNVERIFIED_SUFFIX}"]


@pytest.mark.parametrize(
    ("lesson", "general"),
    [
        ("Scene three repeats the lab bench.", False),
        ("The third shot drifts to profile.", False),
        ("The 3rd beat holds too long.", False),
        ("The second scene repeats the desk.", False),
        ("Scena a 4-a are o literă pe registru.", False),
        ("Cadrul al 3-lea se mișcă prea încet.", False),
        ("A doua scenă repetă biroul.", False),
        ("Give every shot one clear action.", True),
        ("The first shot hooks the viewer; the last one lands the point.", True),
        ("A shot two seconds long reads as a still.", True),
        ("Ask for a second shot of the same room only when the light changes.", True),
    ],
)
def test_a_scene_named_in_words_or_as_an_ordinal_is_one_film(lesson, general):
    assert (lesson_is_general(lesson) is None) is general, lesson_is_general(lesson)


def test_a_lesson_names_only_the_film_it_was_learned_on(engine):
    """Review of 68fa0b4: three words in a row of any title in the studio refused general rules
    that shared a phrase with one («… in real time …», «space telescope»). Another film is
    named only by its whole title; the film the lesson was learned on by most of its words."""
    from app.media.models import Storyboard

    ids = studio(engine)
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, ids["board"])
        board.title = "Storyboard: How the Space Telescope Sees in Real Time"
    why: list[str] = []
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(
            session,
            "A screen that updates in real time is drawn as a frozen frame; ask for one light.",
        )
        assert record_prompt_lesson(
            session, "A space telescope drawn small reads as a toy; give it a person for scale."
        )
        assert not record_prompt_lesson(
            session, "How the space telescope sees in real time: stars come back as stickers."
        )
        assert not record_prompt_lesson(
            session,
            "The telescope sees stars in real time as stickers; ask for points of light.",
            storyboard_id=ids["board"],
            reasons=why,
        )
    assert "numește filmul" in why[0]


@pytest.mark.usefixtures("staffed")
def test_the_shot_writer_keeps_an_ending_that_fits_the_native_cap(engine, monkeypatch):
    """The 95-word target must not remove a visible endpoint that fits the provider cap."""
    board_id = serial_board(engine, monkeypatch)
    count = len(scenes_of(engine, board_id))
    action = (
        "Kael slowly swivels his heavy office chair toward Sarah while holding a paper cup of "
        "cold coffee in his left hand and pointing with his right hand at the long column of "
        "render times scrolling down the middle monitor of the three curved screens on the "
        "cluttered render desk under the lamp"
    )
    ending = " ".join(["Kael and Sarah facing the viewer across the cluttered render desk"] * 4)
    pack = shot_pack(count)
    pack["shots"][0] = {**pack["shots"][0], "action": action, "ending_frame": ending[:300]}
    fake_editor(monkeypatch, pack)

    result = write_shot_prompts(engine, models(), board_id, str(uuid4()))

    # The editorial word target no longer removes an endpoint that fits the native cap.
    assert result["ending_dropped"] == []
    with Session(engine) as session:
        written = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.shot_prompts_written")
        ).all()
    assert written[-1].payload["ending_dropped"] == []
    first = scenes_of(engine, board_id)[0].prompt_json
    from app.media.prompt_agent import _ending_sentence
    from app.media.prompt_lint import DEFAULT_PROMPT_MAX_UTF16, utf16_units

    assert _ending_sentence(first["ending_frame"]) in first["motion_prompt"]
    assert utf16_units(first["motion_prompt"]) <= DEFAULT_PROMPT_MAX_UTF16
