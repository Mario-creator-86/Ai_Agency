"""Series look: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from app.config import ROOT

#: The Owner's proposal file for the serial's look.
SERIES_LOOK_FILE = ROOT / "config" / "serial_series_look.json"

#: What a serial prompt may be at most, when the file does not say: the style block first,
#: then the room, the people, the action and the camera. A longer prompt buries the shot.
DEFAULT_MAX_PROMPT_CHARS = 980

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
#: A bible sentence with its own verb ("The environment is a controlled space"). A comma
#: after its verb does not split it when what follows goes on the same phrase (look_phrase),
#: and capitalised, it is not joined to the place with a comma ("today, The environment is
#: ..."): place, season and weather are then said as sentences.
_HAS_VERB = re.compile(
    r"\b(?:is|are|was|were|exists?|has|have|sits?|lies?|remains?|stays?|appears?|seems?"
    r"|feels?)\b",
    re.IGNORECASE,
)
#: The first word of a new phrase after a comma: an article, a pronoun, a preposition, a
#: conjunction, a negation. Any other first word goes on the phrase before the comma ("is a
#: controlled, climate-stable space"; "is soft, warm and low").
_NEW_PHRASE = re.compile(
    r"^(?:the|a|an|this|that|these|those|its|it|their|they|his|he|her|she|our|we|my|your"
    r"|every|each|all|some|no|not|never|without|with|in|on|at|under|over|outside|inside"
    r"|beside|behind|near|where|which|who|whose|while|when|as|and|but|or|yet|so|from|to|by"
    r"|for|through|across|along|against|above|below|beneath|between|among|around|there|here"
    r"|then|than)\b",
    re.IGNORECASE,
)
#: A bible piece said for one of the film's places: "In the tunnel, lighting is practical
#: and industrial", "in the void a glow". Film babcf272 (2026-10-09): the block said for
#: every scene kept that tunnel light, and the void scenes came back as tunnels over flat
#: black bands. Not a time, a light or the film itself: "In the soft light of dawn, ...",
#: "At the end of the day, ...", "In this film, ..." are said for every scene.
_PLACE_SCOPE = re.compile(
    r"^(?:in|inside|within|at|on|outside|under|beneath|below|across|near)\s+"
    r"(?:the|a|an|this|that|its|their|our)\s+((?:[\w'-]+\s+){0,3}?[\w'-]+)"
    r"(?:\s*,|\s+(?=(?:a|an|the|it|everything|there)\b))",
    re.IGNORECASE,
)
_NOT_A_PLACE = re.compile(
    r"\b(?:films?|series|story|documentary|video|episode|whole|entire|lights?|lighting|glow"
    r"|sun|sunlight|daylight|moonlight|starlight|shade|shadows?|dark|darkness|haze|mist|fog"
    r"|rain|snow|morning|evening|afternoon|night|day|dawn|dusk|twilight|hour|season|winter"
    r"|summer|autumn|spring|monsoon|end|beginning|distance|background|foreground)\b",
    re.IGNORECASE,
)
#: A world that is several places ("two interconnected spaces: the tunnel and the void").
_SEVERAL_PLACES = re.compile(
    r"\b(?:two|three|four|five|several|multiple|many|different|distinct|separate|parallel)\s+"
    r"(?:[\w-]+\s+){0,2}?(?:spaces|places|locations|settings|worlds|realms|environments|sites"
    r"|landscapes)\b",
    re.IGNORECASE,
)
#: Keys of a structured world that describe one place rather than name another one.
_ONE_PLACE_KEYS = frozenset(
    "name description details detail summary notes note type era period time mood look feel"
    " style texture textures".split()
)


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


def _scoped_to_a_place(piece: str) -> bool:
    """Whether a bible piece is said for one of the film's places, not for all of it."""
    scope = _PLACE_SCOPE.match(piece.strip())
    return scope is not None and not _NOT_A_PLACE.search(scope.group(1))


def _place_by_place(value: Any) -> bool:
    """Whether a bible value says its words place by place ("In the tunnel, ...")."""
    from app.media import prompt_lint as lint  # noqa: PLC0415

    text = lint.without_asides(_said(value))
    return any(_scoped_to_a_place(piece) for piece in re.split(r"[;.]\s*", text))


def _names_several_places(world: Any) -> bool:
    """Whether the bible's world is more than one place: a block said for every scene then
    names none of them, or every scene would show all of them (babcf272: tunnel and void)."""
    if isinstance(world, dict):
        named = [
            key
            for key, item in world.items()
            if _said(item) and str(key).strip().lower() not in _ONE_PLACE_KEYS
        ]
        return len(named) > 1
    text = _said(world)
    labels = {
        label.group(1).strip().lower()
        for label in re.finditer(r"(?:^|;)\s*([A-Za-z][\w /-]{0,24}):", text)
    }
    return len(labels - _ONE_PLACE_KEYS) > 1 or bool(_SEVERAL_PLACES.search(text))


def look_phrase(
    value: Any, max_words: int | None, *, own: bool = False, whole_film: bool = False
) -> str:
    """Plain words of a bible value that may enter a look block, whole clauses only.

    A clause is dropped when an image model would read it wrongly: a code or a hex colour, a
    negation ("no harsh shadows" invites them), a person (the look is about the world, and
    faces are the scene's business), writing, another medium, a shot size (it would decide
    every scene's framing at once), a chart or a black screen, a quotation, a "then" or a
    later moment, a pointer at another scene. A clause that says nothing ("None", "n/a")
    or is the head of a broken sentence (it ends in "the", "of", "is"...) is dropped too.
    ``own`` marks the look file's own words: its "film grain" is the look, not a restyle.

    With ``max_words``, whole clauses are taken from the start while they fit, and a clause
    is never cut: babcf272's look said "The setting is entirely" and "The environment is a
    controlled", each the first words of a sentence too long for its slot. A first clause
    that does not fit gives "", and the slot falls back to the next key or the look file.
    A comma splits clauses, except after a verb when the next words go on the same phrase
    ("The environment is a controlled, climate-stable space" is one clause); a name before
    the comma stays whole on its own ("Kathmandu, a valley city where temples sit ...").

    ``whole_film`` marks a value said for every scene (light, palette, season, weather): a
    piece the bible says for one of its places ("In the tunnel, lighting is ...") is not.
    """
    from app.media import prompt_lint as lint  # noqa: PLC0415
    from app.media.prompt_agent import (  # noqa: PLC0415
        _STYLE_OVERRIDE,
        _TEXT_REQUEST,
        without_scene_reference,
    )

    def readable(clause: str) -> str:
        said = without_scene_reference(_LABEL.sub("", " ".join(clause.split()).strip(" -:")))
        if not re.search(r"[A-Za-z]", said) or (
            lint.NONE_WORD.match(said)
            or lint.dangling(said)
            or _HEX.search(said)
            or lint.ENUM_CODE.search(said)
            or lint.NEGATION.search(said)
            or lint.INLINE_EXCLUSION.search(said)
            or lint.PERSON.search(said)
            or lint.classify_kind_phrase(said)
            or _TEXT_REQUEST.search(said)
            or (not own and _STYLE_OVERRIDE.search(said))
            or lint.SHOT_SIZE.search(said)
            or lint.THEN_CHAIN.search(said)
            or lint.SEQUENCE_OPENER.match(said)
            or lint.LATER_MOMENT.search(said)
            or lint.PANEL_LAYOUT.search(said)
            or _QUOTE_MARKS.search(said)
        ):
            return ""
        return said

    text = lint.without_asides(_said(value).replace("’", "'").replace("‘", "'"))
    kept: list[str] = []
    for piece in re.split(r"[;.]\s*|\s*\(|\)\s*", text):
        if whole_film and _scoped_to_a_place(piece):
            continue
        clauses: list[str] = []
        for clause in re.split(r",\s*", piece):
            clause = " ".join(clause.split())
            if not clause:
                continue
            if clauses and _HAS_VERB.search(clauses[-1]) and not _NEW_PHRASE.match(clause):
                # The comma sits inside the phrase its verb began: between two adjectives
                # ("is a controlled, climate-stable space"), and "The environment is a
                # controlled" on its own is a broken sentence. The phrase is one clause.
                clauses[-1] = f"{clauses[-1]}, {clause}"
            else:
                clauses.append(clause)
        kept.extend(said for said in map(readable, clauses) if said)
    if max_words is None:
        return ", ".join(kept)
    fitted: list[str] = []
    count = 0
    for said in kept:
        words = len(said.split())
        if count + words > max_words:
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


#: The look slots a scene's own words replace (`look_block(omit=...)`): a scene that names
#: its place leaves the look's place, season and weather unsaid; one that names its light
#: leaves the look's daylight unsaid. 2026-10-11, cyclotron aa170155: every still opened with
#: "A real location as it is today, Early autumn, None indoors. Soft diffuse daylight from
#: high to one side" over a 1930s lamp-lit desk at night, and the model drew the daylight and
#: a beige lamp; the Director's brief named those words.
PLACE_SLOTS: frozenset[str] = frozenset({"place", "season", "weather"})
LIGHT_SLOTS: frozenset[str] = frozenset({"light"})
#: A bible value that says there is none ("None indoors; the only exterior is ...").
_NONE_FIRST = re.compile(r"^\s*(?:none|no\s+weather|n/?a)\b", re.IGNORECASE)


def look_block(
    bible: dict[str, Any] | None,
    look: dict[str, Any] | None = None,
    *,
    omit: Collection[str] = (),
) -> str:
    """The words every still prompt of a factual film opens with, 40-60 of them.

    The rendering is the studio's and is never taken from the bible: a bible that asks for
    another medium contradicts the look and is not read. The place, season, weather, light
    and palette are the bible's when it names them in whole clauses that fit their slot, the
    file's otherwise; a bible whose season or weather is "None" has none. A bible rule that
    asks for overcast light is said as the light it wants. The same bible always gives the
    same block, so every scene of a film opens identically — unless the scene names its own
    place or light (``omit``: `PLACE_SLOTS`, `LIGHT_SLOTS`), when those slots are left to the
    scene's words and the fills keep the block at its length.
    """
    from app.media import prompt_lint as lint  # noqa: PLC0415

    look = look or load_factual_look()
    if not look.get("in_use"):
        return ""
    source = bible if isinstance(bible, dict) else {}
    slots: dict[str, str] = look.get("slots") or DEFAULT_FACTUAL_SLOTS
    caps: dict[str, int] = look.get("slot_words") or DEFAULT_SLOT_WORDS
    left_out = {str(slot) for slot in omit}

    def pick(
        slot: str,
        *keys: str,
        fallback: str | None = None,
        none: bool = False,
        whole_film: bool = True,
        by_place_is_none: bool = False,
    ) -> str:
        if slot in left_out:
            return ""
        for key in keys:
            value = source.get(key)
            text = lint.without_asides(_said(value)).strip()
            # A bible that says its film has no weather ("None. The environment is a
            # controlled ...", babcf272: a particle accelerator tunnel; "None indoors; the
            # only exterior is the final dusk aerial", aa170155) is not given the look file's
            # "overcast sky", nor its own "None indoors" said as weather.
            if none and (
                _NONE_FIRST.match(text)
                or lint.NONE_WORD.match(re.split(r"[;,.:]\s*", text, maxsplit=1)[0])
            ):
                return ""
            said = look_phrase(value, caps.get(slot, 8), whole_film=whole_film)
            if said:
                return said
            # A bible that gives its light place by place (babcf272: "In the tunnel, ...")
            # leaves the light to each scene: the look file's daylight in a void scene would
            # be as wrong as the tunnel's light.
            if by_place_is_none and _place_by_place(value):
                return ""
        if fallback is not None:
            return fallback
        return look_phrase(slots.get(slot), None, own=True)

    overcast = any(_OVERCAST_RULE.search(rule) for rule in _bible_rules(source))
    light_default = OVERCAST_LIGHT if overcast else look_phrase(slots.get("light"), None, own=True)
    if "place" in left_out:
        place = ""
    elif _names_several_places(source.get("world")):
        place = look_phrase(slots.get("place"), None, own=True)
    else:
        place = pick("place", "world", "place", whole_film=False)
    season = pick("season", "season", none=True)
    weather = pick("weather", "weather", none=True)
    light = pick("light", "lighting", fallback=light_default, by_place_is_none=True)
    palette = pick("palette", "palette")
    lens = look_phrase(slots.get("lens"), None, own=True)
    grain = look_phrase(slots.get("grain"), None, own=True)
    fills: list[str] = list(look.get("fill") or [])

    # A palette that names itself ("A core palette of deep charcoal and slate") is said as it
    # is: babcf272's block read "Muted natural palette of A core palette of ...".
    if re.search(r"\bpalettes?\b", palette, re.IGNORECASE):
        palette_sentence = _sentence(palette)
    else:
        palette_sentence = _sentence(f"Muted natural palette of {palette}") if palette else ""

    def compose(with_season: bool, with_weather: bool, extra: int) -> str:
        wheres = [
            part
            for part in (place, season if with_season else "", weather if with_weather else "")
            if part
        ]
        if any(part[:1].isupper() and _HAS_VERB.search(part) for part in wheres):
            where = " ".join(_sentence(part) for part in wheres)
        else:
            where = _sentence(", ".join(wheres))
        parts = [
            _sentence(str(look.get("rendering") or DEFAULT_FACTUAL_RENDERING)),
            where,
            _sentence(light),
            palette_sentence,
            *[_sentence(item) for item in fills[:extra]],
            _sentence(", ".join(part for part in (lens, grain) if part)),
        ]
        return " ".join(part for part in parts if part)

    low = int(look.get("min_words") or LOOK_MIN_WORDS)
    high = int(look.get("max_words") or LOOK_MAX_WORDS)
    block = compose(True, True, 0)
    extra = 0
    # A block whose place or light the scene says itself is not padded with the fills: the
    # scene's own words take that room in the prompt (a desk at night gains nothing from
    # "honest textures of stone, soil, water and weathered cloth").
    while not left_out and len(block.split()) < low and extra < len(fills):
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
