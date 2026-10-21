"""A line the showrunner's model wrote with no speaker (the audit of 2026-10-16, SAFE-005).

Since the narrator came in (2026-10-16), a line with no name on it was read as the narrator's
anywhere in the episode, where it used to refuse the answer. A character's line that lost its
name mid-episode was then read by the voice in off, and the review's narration check, which
counts only the opening and the closing, passed it. Now a nameless line is the narrator's only
where the narrator speaks — the start of the first beat and the end of the last — and is
refused anywhere else, with the beat named, as before.

No model is called: the showrunner is scripted.
"""

from __future__ import annotations

import pytest
from app.story.services import DraftRefused
from test_serial_pipeline import (  # noqa: F401 - staffed is a fixture
    KAEL,
    SARAH,
    SPOKEN,
    beats_for,
    episode_rows,
    letters_day,
    staffed,
    written,
)

OPENING = (
    "The Content floor, a little after nine. Sarah wants the number before lunch, and Kael "
    "has not slept. Today the studio finds out whether a late cut can still go out."
)
CLOSING = "The cut went back to the bay, and the number stayed on her desk."


def test_a_nameless_opening_and_closing_are_the_narrators(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["lines"] = [{"text": OPENING}, *beats[0]["lines"]]
    beats[-1]["lines"] = [*beats[-1]["lines"], CLOSING]

    episode = written(engine, monkeypatch, beats)

    first, last = episode["beats"][0], episode["beats"][-1]
    assert first["lines"][0] == {"speaker": None, "text": OPENING}
    assert last["lines"][-1] == {"speaker": None, "text": CLOSING}
    assert set(first["speakers"]) == {SARAH, KAEL}


def test_a_nameless_line_in_the_middle_of_the_episode_is_refused_with_its_beat(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[2]["lines"] = [beats[2]["lines"][0], {"text": SPOKEN[1], "direction": "quietly"}]

    with pytest.raises(DraftRefused) as refused:
        written(engine, monkeypatch, beats)

    reason = str(refused.value)
    assert "Beat-ul 3" in reason and "nu are vorbitor" in reason
    assert "Narrator" in reason
    assert episode_rows(engine) == []


def test_a_nameless_line_after_a_characters_line_in_the_first_beat_is_refused(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    # The opening is the narrator's only before anyone in the room speaks.
    beats[0]["lines"] = [beats[0]["lines"][0], SPOKEN[1]]

    with pytest.raises(DraftRefused) as refused:
        written(engine, monkeypatch, beats)

    assert "Beat-ul 1" in str(refused.value)
    assert episode_rows(engine) == []
