"""What an adversary found after the three first-day fixes reported green.

The three were: a cast the studio guessed no longer steers a paid render, a seeing model
admitted after the workforce exists reaches an employee, and the day tells the Owner in the
minute it stops with a figure that admits what it left out. Each was measured against this
tree and each is covered by its own part's tests. What follows is the other side of those
claims — the sentences nobody wrote a test for, the check nobody labelled, and the second
film of a SUPERVISED day.

Nothing here reaches a vendor, renders a frame, queues a day or opens `data/studio.db`: the
suite's `no_network` fixture refuses a socket to anything but loopback, every engine comes
from the `engine` fixture's temporary file, and the render is faked at `assemble_video_job`.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.media.services import _character_keys, _scene_cast
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# A cast is what the film states — and everything it states
# ---------------------------------------------------------------------------


def _keys() -> dict[str, tuple[str, tuple[str, ...]]]:
    """The seeded bible as the matcher sees it, without a database."""
    return {
        "sarah": _character_keys("Sarah Executive"),
        "elena": _character_keys("Elena Fact-Checker"),
        "kael": _character_keys("Kael Video Editor"),
        "lyra": _character_keys("Lyra Voice Artist"),
        "aris": _character_keys("Dr. Aris Researcher"),
    }


def test_a_scene_that_states_two_characters_records_both_of_them():
    """The writer's cast list is a record, and a record of two people names two people.

    Measured on this tree before the fix: `_scene_cast` joined the whole list into one line
    with spaces and read it as prose, so the given-name rule that protects "the Vera Rubin
    Observatory" saw `["Elena", "Kael"]` as «Elena Kael» — a first name followed by another
    capitalised word — and dropped Elena. A two-hander therefore recorded one person, and
    the one it dropped was neither stated nor guessed: her stored portrait was not attached
    to the paid render, the character gate never compared her, and had her look been locked
    the film would have been drawn with her face invented. Each entry is now read on its
    own, which is what a list is.
    """
    keys = _keys()

    assert _scene_cast({"characters": ["Elena", "Kael"]}, "A control room at night", keys) == (
        ["elena", "kael"],
        [],
    )
    assert _scene_cast({"characters": ["Kael", "Elena"]}, "A control room at night", keys) == (
        ["kael", "elena"],
        [],
    )
    # Three of them, and a whole name beside two given ones, read the same way.
    stated, guessed = _scene_cast(
        {"characters": ["Sarah", "Dr. Aris Researcher", "Lyra"]}, "The long table", keys
    )
    assert (sorted(stated), guessed) == (["aris", "lyra", "sarah"], [])


def test_a_listed_name_the_bible_does_not_hold_still_puts_nobody_on_screen():
    """Reading each entry on its own must not turn a stranger into an employee.

    The rule that a given name followed by another capitalised word is somebody else's
    surname is what keeps "Elena Rodriguez" out of the cast, and it still holds inside one
    entry — it was only ever wrong across two of them.
    """
    keys = _keys()

    assert _scene_cast({"characters": ["Elena Rodriguez"]}, "A press room", keys) == ([], [])
    assert _scene_cast({"characters": ["Vera Rubin"]}, "The observatory", keys) == ([], [])
    assert _scene_cast({"characters": ["Elena Rodriguez", "Kael"]}, "A press room", keys) == (
        ["kael"],
        [],
    )


def test_five_more_sentences_of_prose_cast_nobody_and_are_kept_as_guesses():
    """Five sentences of the adversary's own, beyond the three the last one measured.

    Each spells a studio character's given name in prose that is plainly about something
    else — one of them in the middle of the sentence, one of them naming two. None may reach
    the scene's cast, because the cast buys a portrait and can refuse a locked film; all of
    them are kept as guesses, because a studio that throws away what it read cannot show the
    Owner why it cast nobody.
    """
    keys = _keys()
    sentences = {
        # The name in the middle of the sentence, not at its head.
        "A slow pan across the Kael river delta at first light": ["kael"],
        "Astronomers watching Lyra through a winter night": ["lyra"],
        # Two of them in one line, and neither is a person on screen.
        "The Elena fault line runs under the Kael basin": ["elena", "kael"],
        "Sarah's Law was written the year the bridge fell": ["sarah"],
        # Lower case is nobody at all, whatever it spells.
        "The rover crosses the aris plain": [],
    }
    for sentence, expected in sentences.items():
        stated, guessed = _scene_cast({}, sentence, keys)
        assert stated == [], f"{sentence!r} put somebody on screen"
        assert sorted(guessed) == sorted(expected), sentence


def test_a_whole_canonical_name_in_the_middle_of_a_sentence_is_the_films_own_word():
    """The strict reading is not anchored to the start of the picture the scene asks for."""
    keys = _keys()

    stated, guessed = _scene_cast(
        {}, "A wide shot of the newsroom where Elena Fact-Checker reads a source", keys
    )
    assert (stated, guessed) == (["elena"], [])
    stated, guessed = _scene_cast(
        {}, "Sarah Executive and Kael Video Editor over the same monitor", keys
    )
    assert (stated, guessed) == (["sarah", "kael"], [])


# ---------------------------------------------------------------------------
# Every check the preflight can emit is a check the Owner can read
# ---------------------------------------------------------------------------


def _preflight_check_names() -> set[str]:
    """Every name `run_preflight` can put on a card, read out of the source.

    Read rather than run, because `run_preflight` reports only the checks a given studio
    reaches, and the panel has to have a word for all of them. `_check`'s first argument is
    the name, and it is always a literal.
    """
    source = (REPO_ROOT / "backend" / "app" / "runbook" / "preflight.py").read_text(
        encoding="utf-8"
    )
    names = re.findall(r"_check\(\s*\n?\s*\"([a-z_]+)\"", source)
    assert len(names) > 10, "the check names could not be read out of preflight.py"
    return set(names)


def _panel_check_labels() -> dict[str, str]:
    """The map the Owner's panel reads, out of `frontend/src/readiness.js`."""
    source = (REPO_ROOT / "frontend" / "src" / "readiness.js").read_text(encoding="utf-8")
    block = re.search(r"RUNBOOK_CHECK_LABELS\s*=\s*\{(.*?)\n\};", source, re.S)
    assert block is not None, "RUNBOOK_CHECK_LABELS is not where the panel keeps it"
    return dict(re.findall(r"([a-z_]+):\s*'([^']*)'", block.group(1)))


def test_every_check_the_preflight_can_emit_has_a_name_the_owner_would_use():
    """Walked, not listed: the panel's own test named the six checks it knew about.

    Measured when this was written: `youtube_channel_binding` is emitted on every run
    (`backend/app/runbook/preflight.py`) and had no line in the map, so the Owner read
    «youtube_channel_binding» on a DEGRADING card — a code name reads as a fault in the
    program rather than as a question about his studio. A test that lists the names it
    checks cannot find the name nobody thought of, so this one reads both files.
    """
    labels = _panel_check_labels()
    emitted = _preflight_check_names()
    missing = sorted(name for name in emitted if name not in labels)
    assert missing == [], f"the panel has no words for {missing}"
    # And nothing in the map is a name the preflight cannot emit: a label for a check that
    # does not exist is a promise about a card the Owner will never see.
    stale = sorted(name for name in labels if name not in emitted)
    assert stale == [], f"the panel labels checks the preflight never emits: {stale}"


def test_the_panel_looks_for_the_caveat_in_the_words_the_studio_writes_it_in():
    """Three readers find that sentence by its first words, and two of them are in two files.

    `backend/app/economy/budget.py` writes it, `backend/app/economy/accountant.py` reads it
    back into the letter, and `frontend/src/readiness.js` reads it back onto the approvals
    card — the last of them holding its own copy of the prefix, because a browser cannot
    import a Python constant. A prefix changed on one side and not the other does not fail
    anything: the card simply stops saying that the figure is incomplete, which is the exact
    silence this phase was closing. So the two copies are compared here.
    """
    from app.economy.budget import UNPRICED_CAVEAT_PREFIX

    source = (REPO_ROOT / "frontend" / "src" / "readiness.js").read_text(encoding="utf-8")
    panel = re.search(r"UNPRICED_CAVEAT_PREFIX\s*=\s*'([^']*)'", source)
    assert panel is not None, "the panel no longer keeps a prefix to look for"
    assert panel.group(1) == UNPRICED_CAVEAT_PREFIX


def test_no_check_label_is_left_in_the_language_the_code_is_written_in():
    """His panel is Romanian; a label still in English is a check he has to translate."""
    english = {"Available agents", "Authorised source sites", "Image provider", "Publishing"}
    assert not (english & set(_panel_check_labels().values()))


# ---------------------------------------------------------------------------
# The letter about what waits names everything that waits
# ---------------------------------------------------------------------------


def _letters(engine, kind: str) -> list:
    from app.agents.models import AgentMessage
    from sqlalchemy import select

    with Session(engine) as session:
        return [
            message
            for message in session.scalars(select(AgentMessage))
            if isinstance(message.body_json, dict) and message.body_json.get("kind") == kind
        ]


def test_the_letter_names_every_question_the_media_stage_raised_not_only_the_first(
    engine, settings, monkeypatch
):
    """A SUPERVISED day makes two films, so it raises two questions.

    The letter is written once a business date — that is what keeps the day's close from
    writing a second one — so whichever call writes it is the only one the Owner gets. When
    it was written from inside the loop, on the first refusal, `pending_approvals` held one
    question and the second film's question was raised a moment later into a letter that had
    already gone: he was told one film was waiting when two were, and the one he was not
    told about expired after `approval_expires_after_hours` with the film never made.
    Written once the stage has finished asking, the letter names both — and still leaves
    hours before the day's close.
    """
    from app.agents.services import seed_initial_workforce
    from app.runbook import stages
    from test_daily_run_stages import (
        _approvals,
        _approved_board,
        _autonomy_on,
        _media_stage_with_a_fake_camera,
        _mode,
    )

    _autonomy_on(engine)
    _mode(engine, "SUPERVISED")
    # The letter has an author or it is not written at all: the Accountant, or the Director
    # where the studio has no Accountant.
    seed_initial_workforce(engine)
    settings.paid_generation_approval_threshold_usd = 0.0
    _approved_board(engine, "A factual short")
    _approved_board(engine, "Office serial", serial=True)
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "SKIPPED" and rendered == []
    asked = {request.id for request in _approvals(engine)}
    assert len(asked) == 2, "a SUPERVISED day with two films raises two questions"
    (letter,) = _letters(engine, "owner_waiting")
    named = {question["id"] for question in letter.body_json["questions"]}
    assert named == asked, "the Owner was told about only part of what waits for him"


def test_a_media_stage_that_asks_him_nothing_writes_him_no_letter(engine, settings, monkeypatch):
    """A silent inbox must keep meaning «nothing to decide».

    The stage now calls the Accountant itself, so the rule that nothing is written when
    nothing waits has a second way of being broken.
    """
    from app.runbook import stages
    from test_daily_run_stages import (
        _approvals,
        _approved_board,
        _autonomy_on,
        _media_stage_with_a_fake_camera,
    )

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert _approvals(engine) == []
    assert _letters(engine, "owner_waiting") == []


# ---------------------------------------------------------------------------
# Nothing in the suite opens the Owner's own database
# ---------------------------------------------------------------------------


def test_no_test_in_this_suite_opens_the_owners_own_database(engine, settings):
    """Two of his server processes hold `data/studio.db` open; a test that opened it would
    corrupt the studio the test is meant to be proving. Every engine is a temporary file.

    What is looked for is a line that would *open* it — an engine, a path, a handle — and not
    a line that merely names it, because every adversary file in this suite says in its own
    first paragraph that it does not. A test that puts the live file's own URL into a settings
    object, or opens its path, is the failure this is about.
    """
    assert "/data/studio.db" not in settings.database_url.replace("\\", "/")
    opens = ("sqlite:", "open(", "connect(", "Path(", "create_db_engine", "database_url")
    # An assertion that the name is *absent* is the rule working, and `database_path` is a
    # pure reader of a URL string that opens nothing.
    allowed = ("not in", "tmp_path", "database_path(")
    offenders = []
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "studio.db" not in line or any(word in line for word in allowed):
                continue
            if any(word in line for word in opens):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == [], offenders
