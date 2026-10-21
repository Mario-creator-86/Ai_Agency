"""The showrunner's answer read as the model meant it (review of 2026-10-16): the narrator
under a screenplay's label is the voice in off, a beat of the story's own may cite nothing in
any way a model writes it, and a title's full stop ends no sentence of the narration."""

from __future__ import annotations

import pytest
from app.story.review import _narration, failed_rules
from app.story.services import is_narrator
from test_serial_pipeline import (  # noqa: F401 - staffed is a fixture
    KAEL,
    SARAH,
    beats_for,
    checks_of,
    letters_day,
    staffed,
    written,
)

OPENING = (
    "The Content floor, a little after nine. Sarah wants the number before lunch, and Kael "
    "has not slept. Today the studio finds out whether a late cut can still go out."
)
CLOSING = "The cut went back to the bay, and the number stayed on her desk."


@pytest.mark.parametrize(
    "label",
    [
        "Narrator",
        "narrator",
        "Narrator (V.O.)",
        "NARRATOR (O.S.)",
        "The Narrator",
        "Narrator:",
        "Voice-over",
        "Voiceover",
        "V.O.",
    ],
)
def test_the_narrator_under_any_screenplay_label_is_the_voice_in_off(label):
    assert is_narrator(label)


@pytest.mark.parametrize("name", ["Kael", "Sarah (Director)", "The", "", None, "Narrative"])
def test_a_name_is_not_the_narrator(name):
    assert not is_narrator(name)


def test_an_episode_narrated_under_a_screenplay_label_is_stored_with_its_voice_in_off(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["lines"] = [{"speaker": "Narrator (V.O.)", "text": OPENING}, *beats[0]["lines"]]
    beats[-1]["lines"] = [*beats[-1]["lines"], {"speaker": "The Narrator", "text": CLOSING}]

    episode = written(engine, monkeypatch, beats)

    first, last = episode["beats"][0], episode["beats"][-1]
    assert first["lines"][0] == {"speaker": None, "text": OPENING}
    assert last["lines"][-1] == {"speaker": None, "text": CLOSING}
    assert set(first["speakers"]) == {SARAH, KAEL}
    checks = checks_of(engine, episode["id"])
    assert checks["narration"]["opening_sentences"] == 3
    assert checks["narration"]["closing_sentences"] == 1


def test_a_beat_of_the_storys_own_may_cite_nothing_in_any_way_a_model_writes_it(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL])
    beats[0]["event_ids"] = None
    beats[1]["event_ids"] = ["none"]
    beats[2]["event_ids"] = ["<an id from EVENTS, or none>", "null", ""]
    beats[3]["event_ids"] = "n/a"
    cited = [eid for beat in beats[4:] for eid in beat["event_ids"]]
    seen: list[str] = []

    episode = written(engine, monkeypatch, beats, seen)

    assert [beat.get("event_ids") for beat in episode["beats"][:4]] == [[], [], [], []]
    assert sorted(episode["grounded_event_ids"]) == sorted(set(cited))
    assert failed_rules(checks_of(engine, episode["id"])) == []
    # The brief's format shows an empty list, not a placeholder a model copies.
    (brief,) = seen
    assert '"event_ids": []' in brief and "or none>" not in brief


def test_a_title_in_the_narration_ends_no_sentence():
    opening = (
        "This is the research floor of AMN-AI. Dr. Aris guards his numbers. Today Kael wants them."
    )
    closing = "Dr. Aris, for once, has nothing left to count."
    beats = [
        [{"speaker": None, "text": opening}, {"speaker": KAEL, "text": "May I see them?"}],
        [{"speaker": SARAH, "text": "Show him."}, {"speaker": None, "text": closing}],
    ]

    measured = _narration(beats, True)

    assert measured["opening_sentences"] == 3 and measured["closing_sentences"] == 1
    assert measured["passed"] is True and measured["reason"] == ""
