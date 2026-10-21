"""The serial's v8 form (the Owner, 2026-10-16: «Eu nu înțeleg nimic… ar trebui să existe o
narațiune pe poveste, o introducere în scenă»): a narrator opens with where we are, who is
in the room and what is at stake, and closes with one sentence; whole sentences over 90 to
175 seconds; the story is the showrunner's, the day its backdrop."""

from __future__ import annotations

import pytest
from app.media import montage
from app.story.review import failed_rules
from test_serial_pipeline import (  # noqa: F401 - staffed is a fixture
    KAEL,
    SARAH,
    SPOKEN,
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


def _story(ids: list[str]) -> list[dict]:
    beats = beats_for(ids, [SARAH, KAEL])
    for beat in beats:
        beat["lines"] = beat["lines"] * 2  # forty spoken words a beat, whole sentences
    beats[0]["lines"] = [{"speaker": "Narrator", "text": OPENING}, *beats[0]["lines"]]
    beats[-1]["lines"] = [*beats[-1]["lines"], {"speaker": "Narrator", "text": CLOSING}]
    return beats


def test_the_narrator_opens_and_closes_and_the_episode_is_long_enough(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    _, ids = letters_day(engine)

    episode = written(engine, monkeypatch, _story(ids))

    first, last = episode["beats"][0], episode["beats"][-1]
    # The narrator's lines are stored with no speaker: the narrator voice reads them, and
    # they never count in the speaking cast.
    assert first["lines"][0]["speaker"] is None and first["lines"][0]["text"] == OPENING
    assert last["lines"][-1]["speaker"] is None and last["lines"][-1]["text"] == CLOSING
    assert set(first["speakers"]) == {SARAH, KAEL}
    checks = checks_of(engine, episode["id"])
    assert failed_rules(checks) == [], checks
    assert checks["narration"]["passed"] is True
    assert checks["narration"]["opening_sentences"] == 3
    assert checks["narration"]["closing_sentences"] == 1
    assert checks["length"]["passed"] is True and 90 <= checks["length"]["seconds"] <= 175
    assert checks["cast"]["passed"] is True and checks["cast"]["speakers"] == [SARAH, KAEL]


def test_an_episode_without_its_narrator_is_shown_to_the_director_not_refused(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    _, ids = letters_day(engine)
    beats = _story(ids)
    beats[0]["lines"] = beats[0]["lines"][1:]  # no opening

    checks = checks_of(engine, written(engine, monkeypatch, beats)["id"])

    assert checks["narration"]["passed"] is False and checks["narration"]["advisory"] is True
    assert "naratorul deschide cu 0" in checks["narration"]["reason"]
    assert failed_rules(checks) == []


def test_past_the_shorts_wall_the_episode_is_refused(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """Past the brief's words the episode is refused: the shots' breaths take the rest of
    YouTube's 180 s (`film_length.serial_film_length` measures them)."""
    _, ids = letters_day(engine)
    beats = _story(ids)
    for beat in beats[1:-1]:
        beat["lines"] = beat["lines"] * 3  # 120 words a beat: far past 390 in all

    checks = checks_of(engine, written(engine, monkeypatch, beats)["id"])

    assert "length" in failed_rules(checks)
    assert "zidul Short-ului" in checks["length"]["reason"]


@pytest.mark.montage
def test_the_narrators_lines_are_a_wide_shot_of_their_own():
    lines = [
        {"speaker": None, "text": OPENING},
        {"speaker": SARAH, "text": SPOKEN[0]},
        {"speaker": KAEL, "text": SPOKEN[1]},
    ]
    shots = montage.serial_shots(lines, 2, part="situation", first_beat=False)
    # Twelve seconds of narration are cut as one clip must be, each piece a wide shot of the
    # room with nobody's face, never shared with a line spoken in the room that can be a shot
    # of its own (a few words with no speaking shot to join share his, held on their speaker).
    narrated = [shot for shot in shots if shot["on"] is None]
    assert narrated == shots[: len(narrated)] and len(narrated) >= 1
    assert all(shot["size"] == "establishing" for shot in narrated)
    said = " ".join(line["text"] for shot in narrated for line in shot["lines"])
    assert said == OPENING
    assert all(line["speaker"] is None for shot in narrated for line in shot["lines"])

    closing = [
        {"speaker": SARAH, "text": SPOKEN[0]},
        {"speaker": KAEL, "text": SPOKEN[1]},
        {"speaker": None, "text": CLOSING},
    ]
    shots = montage.serial_shots(closing, 6, part="button", first_beat=False)
    assert shots[-1]["on"] is None and shots[-1]["size"] == "establishing"
    # The close-up lands on the last shot in the room, not on the narrator's.
    assert shots[-2]["size"] == "close"


def test_production_aims_shorts_at_160_seconds_under_the_180_wall():
    """The Owner, 2026-10-16: «mai bine 60-300 cu ținta de 150-200», then «mergem atunci ca
    maxim 180». The suite runs its 30-second fixtures (conftest); production is this."""
    from app.config import Settings
    from app.factual.editorial import MAX_SHORT_SECONDS
    from app.story.review import MAX_SECONDS

    assert Settings.model_fields["target_video_seconds"].default == 160
    # 156 s of speech (390 words): the montage's breaths after 30-43 shots fill the rest.
    assert MAX_SHORT_SECONDS == 180.0 and MAX_SECONDS == 156.0
