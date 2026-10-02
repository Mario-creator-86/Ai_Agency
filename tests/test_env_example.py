"""Every setting a buyer can change is written down where he looks for it (SELL-09).

59 of the studio's settings were read only from the Python source, among them the disclosure
URL and the creator title every published description uses. `.env.example` is the buyer's list:
this test fails when a field of `Settings` is missing from it, when it names a setting that no
longer exists, or when its uncommented values would not start a studio.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import ROOT, Settings

EXAMPLE = ROOT / ".env.example"
#: Variables read outside `Settings` (by a module or the test suite) that the file documents too.
EXTRA = {
    "STUDIO_MUSIC_LIBRARY",
    "STUDIO_REQUIRE_FFMPEG",
    "STUDIO_REAL_ENCODE",
    "STUDIO_REHEARSAL_DB",
}
ASSIGNMENT = re.compile(r"^#?\s?(STUDIO_[A-Z0-9_]+)=", re.MULTILINE)


def _env_name(name: str) -> str:
    """The variable a field is read from: its alias when it has one, else STUDIO_<NAME>."""
    alias = Settings.model_fields[name].validation_alias
    choices = getattr(alias, "choices", None) or ([alias] if isinstance(alias, str) else [])
    for choice in choices:
        if isinstance(choice, str) and choice.isupper():
            return choice
    return f"STUDIO_{name.upper()}"


FIELDS = {_env_name(name) for name in Settings.model_fields}


def _named() -> list[str]:
    return ASSIGNMENT.findall(EXAMPLE.read_text(encoding="utf-8"))


def test_every_setting_is_in_the_example():
    missing = sorted(FIELDS - set(_named()))
    assert not missing, f".env.example does not document: {missing}"


def test_the_example_names_no_setting_that_does_not_exist():
    stale = sorted(set(_named()) - FIELDS - EXTRA)
    assert not stale, f".env.example names settings the studio does not read: {stale}"


def test_each_setting_is_written_once():
    named = _named()
    twice = sorted({name for name in named if named.count(name) > 1})
    assert not twice, twice


def test_the_uncommented_values_start_a_studio(tmp_path: Path):
    # The example as a buyer copies it, with only the key the bootstrap writes filled in.
    text = EXAMPLE.read_text(encoding="utf-8").replace(
        "STUDIO_OWNER_TOKEN=\n",
        "STUDIO_OWNER_TOKEN=" + "e" * 48 + "\n",  # pragma: allowlist secret
    )
    copy = tmp_path / ".env"
    copy.write_text(text, encoding="utf-8")
    settings = Settings(_env_file=copy)  # type: ignore[call-arg]
    assert settings.demo_mode is False
    assert settings.port == 8000 and settings.host == "127.0.0.1"


def test_the_disclosure_and_the_place_are_documented_with_their_meaning():
    text = EXAMPLE.read_text(encoding="utf-8")
    for name in (
        "STUDIO_AI_DISCLOSURE_URL",
        "STUDIO_CREATOR_CHANNEL_TITLE",
        "STUDIO_TIMEZONE",
        "STUDIO_OFFICE_CITY",
        "STUDIO_HOLIDAY_COUNTRY",
        "STUDIO_DAILY_RUN_HOUR_LOCAL",
        "STUDIO_MOTION_BUDGET_USD",
        "STUDIO_FILM_BUDGET_USD",
    ):
        line = text.index(f"{name}=")
        before = text[max(0, line - 400) : line]
        assert "#" in before.splitlines()[-1] or "# " in before, name


def test_the_display_name_is_read_from_the_name_the_example_gives(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STUDIO_DISPLAY_NAME", "Studioul Meu")
    settings = Settings(_env_file=None, owner_token="e" * 48)  # pragma: allowlist secret
    assert settings.studio_display_name == "Studioul Meu"
    assert (
        Settings(
            _env_file=None, owner_token="e" * 48, studio_display_name="Prin argument"
        ).studio_display_name
        == "Prin argument"
    )
