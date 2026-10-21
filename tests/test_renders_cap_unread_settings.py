"""An unreadable setting never loosens the Owner's renders cap (the dishonest-code audit of
2026-10-16, SAFE-010).

When the studio's settings could not be built (a locked or invalid .env, no Owner token), the
cap fell back to the environment alone, then to the default: a cap of 1 written only in .env
read as 2 or 3, one paid render more than the Owner set. Now the reader fails safe — never more
than any source sets, the lowest the setting allows when a source cannot be read — and logs it.
Nothing is bought here; the main .env is never read (the settings class is pointed elsewhere).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.media import renders_cap


def _broken_settings(monkeypatch, env_file: Path | None) -> None:
    class Broken(Settings):
        model_config = {**Settings.model_config, "env_file": env_file}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ValueError("the .env could not be read")

    monkeypatch.setattr("app.config.Settings", Broken)
    monkeypatch.setattr(renders_cap, "_LOGGED", set(), raising=False)


def test_an_unreadable_settings_file_never_allows_more_renders_than_set(
    monkeypatch, tmp_path, caplog
):
    env = tmp_path / ".env"
    env.write_text("STUDIO_RENDERS_PER_LAYER=1\n", encoding="utf-8")
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "3")
    _broken_settings(monkeypatch, env)
    with caplog.at_level(logging.WARNING, logger="studio.renders_cap"):
        assert renders_cap.renders_per_layer() == 1
    assert any(r.getMessage() == "renders_cap_settings_unreadable" for r in caplog.records)
    # A value it cannot hold, or a file it cannot read: the lowest the setting allows.
    env.write_text("STUDIO_RENDERS_PER_LAYER=nine\n", encoding="utf-8")
    assert renders_cap.renders_per_layer() == 1

    def unreadable(path: Any) -> dict[str, str]:
        raise OSError("locked")

    env.write_text("STUDIO_RENDERS_PER_LAYER=3\n", encoding="utf-8")
    monkeypatch.setattr("dotenv.dotenv_values", unreadable)
    assert renders_cap.renders_per_layer() == 1


def test_with_no_file_the_environment_holds_and_nothing_set_is_the_default(monkeypatch, tmp_path):
    _broken_settings(monkeypatch, tmp_path / "missing.env")
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "3")
    assert renders_cap.renders_per_layer() == 3
    monkeypatch.delenv("STUDIO_RENDERS_PER_LAYER")
    assert renders_cap.renders_per_layer() == Settings.model_fields["renders_per_layer"].default
