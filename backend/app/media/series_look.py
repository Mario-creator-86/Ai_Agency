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
import re
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
    # Nothing asked for writing: the block is kept word for word, punctuation included
    # (strip_on_screen_text returns its input unchanged when it removes nothing).
    proposed = strip_on_screen_text(_clean(data.get("style_block")))
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


# ------------------------------------------------------------------ the factual look
#
# The Nepal film (2026-09-26) had no look: its bible was enum codes and hex colours, pasted
# into the prompt as "Environment: NEPAL_CLIMATE_CRISIS. Palette: #2E4A66 ...". An image
# model reads words, not codes, so each still came out in whatever style it defaults to.
# A factual short now opens every still prompt with one look block, the same words for
# every scene of the film: the studio's documentary rendering from config/factual_look.json,
# with the place, season, weather, light and palette the film's bible names in plain words.

#: The Owner's proposal file for the factual shorts' look.
FACTUAL_LOOK_FILE = ROOT / "config" / "factual_look.json"

#: What the look is when the file is missing or unreadable: the studio still films one look.
DEFAULT_FACTUAL_RENDERING = "Documentary photograph, natural and unposed, true-to-life colour"
DEFAULT_FACTUAL_SLOTS = {
    "place": "a real location as it is today",
    "season": "",
    "weather": "overcast sky",
    "light": "soft diffuse daylight from high to one side",
    "palette": "slate blue, muted moss green, wet earth brown and stone grey",
    "lens": "natural 35mm lens perspective with gentle depth of field",
    "grain": "fine film grain and crisp detail",
}
DEFAULT_SLOT_WORDS = {"place": 8, "season": 4, "weather": 6, "light": 8, "palette": 8}
DEFAULT_FILL = (
    "Honest textures of stone, soil, water and weathered cloth.",
    "Clear separation between foreground and background.",
)
LOOK_MIN_WORDS = 40
LOOK_MAX_WORDS = 60

#: A bible rule that asks for overcast or shadowless light, said as the light it wants.
_OVERCAST_RULE = re.compile(r"\bovercast\b|\bharsh\s+shadows?\b|\bdiffused?\b", re.IGNORECASE)
OVERCAST_LIGHT = "soft diffuse overcast light with gentle shadows"

_HEX = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")
_LABEL = re.compile(r"^[A-Za-z][\w /-]{0,24}:\s*")
_QUOTE_MARKS = re.compile('["“”„]')


def load_factual_look(path: Path | None = None) -> dict[str, Any]:
    """The factual look as the compiler reads it; built-in defaults when the file is absent.

    ``in_use`` false (the Owner switched the look off) gives an empty look block.
    """
    source = path or FACTUAL_LOOK_FILE
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
        status = "MISSING"
    else:
        status = _clean(data.get("status")) or "PROPOSED"
    slots = dict(DEFAULT_FACTUAL_SLOTS)
    given = data.get("slots")
    if isinstance(given, dict):
        slots.update({str(key): _clean(value) for key, value in given.items()})
    caps = dict(DEFAULT_SLOT_WORDS)
    given_caps = data.get("slot_words")
    if isinstance(given_caps, dict):
        for key, value in given_caps.items():
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                caps[str(key)] = value
    fill = _strings(data.get("fill")) or list(DEFAULT_FILL)

    def bound(key: str, default: int) -> int:
        value = data.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    return {
        "status": status,
        "version": data.get("version"),
        "in_use": bool(data.get("use_until_the_owner_changes_it", True)),
        "rendering": _clean(data.get("rendering")) or DEFAULT_FACTUAL_RENDERING,
        "slots": slots,
        "slot_words": caps,
        "fill": fill,
        "min_words": bound("min_words", LOOK_MIN_WORDS),
        "max_words": bound("max_words", LOOK_MAX_WORDS),
        "file": str(source),
    }


def _said(value: Any) -> str:
    """A bible value as one line of text, whatever shape the model gave it."""
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_said(item)}" for key, item in value.items() if _said(item))
    if isinstance(value, list | tuple):
        return ", ".join(_said(item) for item in value if _said(item))
    return _clean(value)


def look_phrase(value: Any, max_words: int | None, *, own: bool = False) -> str:
    """Plain words of a bible value that may enter a look block, whole clauses first.

    A clause is dropped when an image model would read it wrongly: a code or a hex colour, a
    negation ("no harsh shadows" invites them), a person (the look is about the world, and
    faces are the scene's business), writing, another medium, a shot size (it would decide
    every scene's framing at once), a chart or a black screen, a quotation or a "then".
    ``own`` marks the look file's own words: its "film grain" is the look, not a restyle.
    """
    from app.media import prompt_lint as lint  # noqa: PLC0415
    from app.media.prompt_agent import _STYLE_OVERRIDE, _TEXT_REQUEST  # noqa: PLC0415

    text = _said(value).replace("’", "'").replace("‘", "'")
    kept: list[str] = []
    for clause in re.split(r"[;,.]\s*|\s*\(|\)\s*", text):
        said = _LABEL.sub("", " ".join(clause.split()).strip(" -:"))
        if not re.search(r"[A-Za-z]", said):
            continue
        if (
            _HEX.search(said)
            or lint.ENUM_CODE.search(said)
            or lint.NEGATION.search(said)
            or lint.INLINE_EXCLUSION.search(said)
            or lint.PERSON.search(said)
            or lint.classify_kind_phrase(said)
            or _TEXT_REQUEST.search(said)
            or (not own and _STYLE_OVERRIDE.search(said))
            or lint.SHOT_SIZE.search(said)
            or lint.THEN_CHAIN.search(said)
            or _QUOTE_MARKS.search(said)
        ):
            continue
        kept.append(said)
    if max_words is None:
        return ", ".join(kept)
    fitted: list[str] = []
    count = 0
    for said in kept:
        words = len(said.split())
        if count + words > max_words:
            if not fitted:
                fitted.append(" ".join(said.split()[:max_words]))
            break
        fitted.append(said)
        count += words
    return ", ".join(fitted)


def _bible_rules(bible: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    for key in ("continuity_rules", "avoid", "lighting"):
        value = bible.get(key)
        if isinstance(value, list | tuple):
            rules.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value:
            rules.append(value)
    return rules


def _sentence(text: str) -> str:
    said = " ".join(text.split()).strip(" ,;")
    if not said:
        return ""
    said = said[:1].upper() + said[1:]
    return said if said.endswith((".", "!", "?")) else f"{said}."


def look_block(bible: dict[str, Any] | None, look: dict[str, Any] | None = None) -> str:
    """The words every still prompt of a factual film opens with, 40-60 of them.

    The rendering is the studio's and is never taken from the bible: a bible that asks for
    another medium contradicts the look and is not read. The place, season, weather, light
    and palette are the bible's when it names them in plain words, the file's otherwise. A
    bible rule that asks for overcast light is said as the light it wants. The same bible
    always gives the same block, so every scene of a film opens identically.
    """
    look = look or load_factual_look()
    if not look.get("in_use"):
        return ""
    source = bible if isinstance(bible, dict) else {}
    slots: dict[str, str] = look.get("slots") or DEFAULT_FACTUAL_SLOTS
    caps: dict[str, int] = look.get("slot_words") or DEFAULT_SLOT_WORDS

    def pick(slot: str, *keys: str, fallback: str | None = None) -> str:
        for key in keys:
            said = look_phrase(source.get(key), caps.get(slot, 8))
            if said:
                return said
        if fallback is not None:
            return fallback
        return look_phrase(slots.get(slot), None, own=True)

    overcast = any(_OVERCAST_RULE.search(rule) for rule in _bible_rules(source))
    light_default = OVERCAST_LIGHT if overcast else look_phrase(slots.get("light"), None, own=True)
    place = pick("place", "world", "place")
    season = pick("season", "season")
    weather = pick("weather", "weather")
    light = pick("light", "lighting", fallback=light_default)
    palette = pick("palette", "palette")
    lens = look_phrase(slots.get("lens"), None, own=True)
    grain = look_phrase(slots.get("grain"), None, own=True)
    fills: list[str] = list(look.get("fill") or [])

    def compose(with_season: bool, with_weather: bool, extra: int) -> str:
        where = ", ".join(
            part
            for part in (place, season if with_season else "", weather if with_weather else "")
            if part
        )
        parts = [
            _sentence(str(look.get("rendering") or DEFAULT_FACTUAL_RENDERING)),
            _sentence(where),
            _sentence(light),
            _sentence(f"Muted natural palette of {palette}") if palette else "",
            *[_sentence(item) for item in fills[:extra]],
            _sentence(", ".join(part for part in (lens, grain) if part)),
        ]
        return " ".join(part for part in parts if part)

    low = int(look.get("min_words") or LOOK_MIN_WORDS)
    high = int(look.get("max_words") or LOOK_MAX_WORDS)
    block = compose(True, True, 0)
    extra = 0
    while len(block.split()) < low and extra < len(fills):
        extra += 1
        block = compose(True, True, extra)
    if len(block.split()) > high:
        block = compose(False, True, 0)
    if len(block.split()) > high:
        block = compose(False, False, 0)
    if len(block.split()) > high:
        # A file edited past its own bounds: whole sentences from the end go first.
        sentences = re.split(r"(?<=[.!?])\s+", block)
        while len(sentences) > 1 and len(" ".join(sentences).split()) > high:
            sentences.pop()
        block = " ".join(sentences)
    return block
