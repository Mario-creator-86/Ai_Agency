"""The office serial's one look, as every shot prompt of every episode opens with it.

Measured before this module (2026-09-24): the serial's visual style was the storyboard label
"CHARACTER_ANIMATION". No prompt carried it, so each still was drawn in whatever style the
image model defaults to, a different film in every shot. The Owner's headquarters picture
(`art-source/reference/headquarters_dusk_primary.png`) already says what the studio looks
like: a stylised, warm-lit, cinematic 3D office at human scale, with the eight employees as
their bibles describe them.

The look is a proposal in `config/serial_series_look.json`, next to the voice cast, and not a
row in the Owner's database: writing a style block is free configuration, and he changes it
by editing the file. It is versioned: a shot described under an older version is described
again (`app.media.serial_storyboard.describe_serial_shots`). The block is read, never written
by a model: an episode may not re-decide the series' look.

Nothing here asks a vendor for anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import ROOT

#: The Owner's proposal file for the serial's look.
SERIES_LOOK_FILE = ROOT / "config" / "serial_series_look.json"

#: What a serial prompt may be at most, when the file does not say: the style block first,
#: then the room, the people, the action and the camera. A longer prompt buries the shot.
DEFAULT_MAX_PROMPT_CHARS = 900

#: The shot sizes the serial varies between, when the file does not name them. ``{name}`` is
#: the character the shot is on.
DEFAULT_SHOT_SIZES = {
    "establishing": "Establishing wide shot at eye level, the whole room in view",
    "two_shot": "Medium two-shot at eye level, both speakers facing the viewer",
    "single": "Medium close-up single at eye level on {name}, facing the viewer",
    "close": "Close-up at eye level on {name}'s reaction, facing the viewer",
}


#: The storyboard's shot type for each size, so the plan and the page say what the shot is.
SHOT_TYPES = {
    "establishing": "WIDE_ESTABLISHING",
    "two_shot": "MEDIUM_TWO_SHOT",
    "single": "MEDIUM_CLOSEUP",
    "close": "CLOSEUP",
}

#: The part a beat plays (the showrunner's structure, S4) as the scene purpose a shot records.
PART_PURPOSES = {
    "hook": "HOOK",
    "situation": "SETUP",
    "turn": "REVEAL",
    "payoff": "PAYOFF",
    "button": "ENDING",
}


def serial_shot_size(part: Any, index: int, speakers: int) -> str:
    """The shot size of one beat: the camera varies across an episode, by the beat's part.

    The first beat establishes the room; people talking are a two-shot; a turn is a single
    on the one who turns it; the button is a close-up on the last reaction. With one speaker
    there is nobody to share a two-shot with, and it is a single.
    """
    if index <= 1:
        return "establishing"
    kind = str(part or "").strip().lower()
    if kind == "turn":
        return "single"
    if kind == "button":
        return "close"
    return "two_shot" if speakers >= 2 else "single"


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _strings(raw: Any) -> list[str]:
    return [_clean(item) for item in raw if _clean(item)] if isinstance(raw, list) else []


def load_series_look(path: Path | None = None) -> dict[str, Any]:
    """The look as the prompts read it.

    ``block`` is the style block every serial shot prompt opens with, and is empty while the
    file says the look is not in use (``proposed_block`` keeps it either way, for the page).
    Any clause of the block that asks for writing in the picture is taken out, because the
    retry of a degenerate still strips such clauses and the look must survive it whole. A
    missing or unreadable file is no look: the shots are still composed, without a style.
    """
    from app.media.prompt_agent import strip_on_screen_text  # noqa: PLC0415 - it imports this

    source = path or SERIES_LOOK_FILE
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {
            "status": "MISSING",
            "version": None,
            "series_key": None,
            "series": None,
            "in_use": False,
            "block": "",
            "proposed_block": "",
            "rendering": "",
            "palette": "",
            "continuity_rules": [],
            "avoid": [],
            "shot_sizes": dict(DEFAULT_SHOT_SIZES),
            "max_prompt_chars": DEFAULT_MAX_PROMPT_CHARS,
            "file": str(source),
        }
    written = _clean(data.get("style_block"))
    proposed = strip_on_screen_text(written)
    if len(proposed.split()) == len(written.split()):
        # Nothing asked for writing: the block is kept word for word, punctuation included.
        proposed = written
    in_use = bool(data.get("use_until_the_owner_changes_it", False)) and bool(proposed)
    sizes = dict(DEFAULT_SHOT_SIZES)
    given = data.get("shot_sizes")
    if isinstance(given, dict):
        sizes.update({key: _clean(value) for key, value in given.items() if _clean(value)})
    try:
        cap = int(data.get("max_prompt_chars") or DEFAULT_MAX_PROMPT_CHARS)
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_PROMPT_CHARS
    rendering = strip_on_screen_text(_clean(data.get("rendering")))
    if not rendering and proposed:
        rendering = proposed.split(". ")[0].rstrip(".") + "."
    return {
        "status": _clean(data.get("status")) or "PROPOSED",
        "version": data.get("version"),
        "series_key": data.get("series_key"),
        "series": data.get("series"),
        "in_use": in_use,
        "block": proposed if in_use else "",
        "proposed_block": proposed,
        "rendering": rendering if in_use else "",
        "palette": _clean(data.get("palette")) if in_use else "",
        "continuity_rules": _strings(data.get("continuity_rules")) if in_use else [],
        "avoid": _strings(data.get("avoid")) if in_use else [],
        "shot_sizes": sizes,
        "max_prompt_chars": max(300, min(2000, cap)),
        "file": str(source),
    }


def series_bible(look: dict[str, Any], aspect_ratio: str = "9:16") -> dict[str, Any]:
    """The storyboard's visual bible for a serial episode: the series' look, read-only.

    Stored on `Storyboard.visual_bible_json` in the shape the factual bible has, so the
    production package and the Director's viewing read it unchanged. ``source`` says where it
    came from; a model never writes it.
    """
    return {
        "style": look.get("block") or "",
        "realism": "",
        "period": "",
        "world": "the AMN-AI headquarters, the studio's own building",
        "palette": look.get("palette") or "",
        "lighting": "",
        "camera_language": "",
        "weather": "",
        "continuity_rules": list(look.get("continuity_rules") or []),
        "avoid": list(look.get("avoid") or []),
        "aspect_ratio": aspect_ratio,
        "quality_target": "premium cinematic, readable on a phone in vertical framing",
        "source": "series look" if look.get("in_use") else "no series look",
        "version": look.get("version") if look.get("in_use") else None,
        "status": look.get("status"),
    }
