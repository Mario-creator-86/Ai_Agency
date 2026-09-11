"""The studio publishes in English, whatever language the office speaks.

What is asserted: the setting exists and defaults to English; the guard knows Romanian
when it sees it and passes English; a publication whose metadata is Romanian holds with the
reason; the prompts the script writer, the showrunner and the Publisher receive name the
audience language.
"""

from __future__ import annotations

from app.agents.language import (
    audience_language_line,
    language_name,
    looks_like_english,
    publication_language_hold,
)
from app.config import Settings


def test_the_setting_defaults_to_english(settings):
    assert settings.content_language == "en"
    assert (
        Settings(_env_file=None, owner_token="x" * 40, content_language="ro").content_language
        == "ro"
    )


def test_the_guard_knows_romanian_and_passes_english():
    assert looks_like_english("How the James Webb telescope found water vapour on a rocky world")
    assert looks_like_english("Autonomous robots: what NASA's refueling mission proved")
    assert not looks_like_english("Studioul AI produce conținut cu integritate garantată.")
    assert not looks_like_english("Fiecare afirmatie este validata factual inainte de productie")
    assert not looks_like_english("Descoperire Robotică Autonomă")


def test_a_romanian_title_holds_the_publication_with_the_reason():
    reason = publication_language_hold(
        "Storyboard: Descoperire Robotică Autonomă - Shorts #1",
        "Studioul AI produce conținut cu integritate garantată.",
        "en",
    )
    assert reason and "nu sunt în English" in reason
    assert publication_language_hold("What the Webb telescope saw", "A rocky world.", "en") is None
    # Publishing in Romanian is a choice the setting can make; then nothing holds.
    assert publication_language_hold("Descoperire Robotică", "Fiecare afirmație", "ro") is None


def test_the_prompt_line_names_the_audience_language():
    line = audience_language_line("en")
    assert line.startswith("AUDIENCE LANGUAGE: English.")
    assert "narration, the title, the description, the tags" in line
    assert language_name("ro") == "Romanian" and language_name("xx") == "xx"
