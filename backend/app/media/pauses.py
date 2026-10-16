"""«Pauza vocii»: the silence at every cut is the pause this voice makes at this kind of boundary.

Measured before this module (2026-10-16, the 55 kept ElevenLabs takes of 8 films): one value,
`assembler.LEGACY_SPOKEN_TAIL_SECONDS` (0.4 s), was added after every storyboard row, on top of the
vendor's own trailing silence, which `assembler._trimmed_take` never cut (the vendor stretches a
take's final "." to the end of its file, and the trim let the vendor's clock veto the meter). A
cut carried 0.92 [0.82-1.05] s whatever the boundary, up to 1.56 s, even between two words; a
speaker change in the serial carried 0.70 s. The narrator's own pauses inside his takes are about
0 between words, 0.30 s at a dash and 0.49 s at a full stop.

The Owner listened to a before/after preview built from the takes already paid for and decided
(2026-10-16): «Sună foarte bine și este o îmbunătățire. Deci da.» His decisions, which this module
holds as formulas only:

1. One voice take per writer scene (factual) and per speaker run inside a beat (serial); the
   montage cuts the picture on the vendor's word timestamps inside the take (``alignment``,
   never ``normalized_alignment``) and adds 0 s (IN_TAKE).
2. Where two takes meet, the class of the boundary and each voice's own measured pauses give the
   silence T, from the last letter of one take to the first sound of the next:
   SENTENCE = the voice's full-stop pause; PARAGRAPH = ratio x the larger of the two voices'
   pauses; TURN = the conversational gap, clamped to [its floor, the speaker's sentence pause];
   INTERRUPT = the kept edges only; CARD = the card is the pause; a ceiling on every planned
   join; never a pause before a punchline.
3. A writer-marked beat («…» at a factual scene's end, «(beat)» in a serial line's direction)
   is a real silence inside the beat band, at most one per section or beat.
4. END = the narrator's PARAGRAPH pause, for every film.
5. Tempo per channel (a knob in the channel's look file, ``"pauses"``).
6. ``cut_in_pause`` 1.0 (the outgoing shot holds the pause) and ``picture_slide_words`` 0 (no
   L-cut) are knobs, not code.
7. The trim keeps the take to its last LETTER, guarded so that no sound is split
   (`trim_cut`, used by `assembler._trimmed_take` behind the ``trim_to_last_letter`` switch).
8. Nothing is hard-coded here: the research constants and the studio's choices, each with its
   source or reason, are in ``config/pause_rules.json`` (PROPOSED, used until the Owner changes
   it); the per-channel knobs in ``config/factual_look.json`` and
   ``config/serial_series_look.json``; each voice's own numbers are measured from its kept PAID
   narration sidecars (`load_profiles`, cached in the git-ignored
   ``<media_root>/voice_pause_profiles.json``); each film's pauses are frozen on its storyboard
   rows when it is built (`freeze`), so a later profile never changes an open film.
9. The wall: min(the channel's Shorts maximum, the rules' cap). A film is fitted by compressing
   pauses toward their floors, the ladder keeping its order (`fit_to_wall`); a BEAT and a card
   are never compressed.

What is here: the classifier (`boundary_class`), the profile (`voice_profile`), the targets and
floors (`target`, `floor`, `short_guard`), the estimates (`speech_seconds`, `row_estimate`,
`film_estimate`), the wall (`fit_to_wall`), the render's pad (`render_pad`), the freeze
(`freeze`, `snapshot`) and the trim's cut points (`trim_cut`). `media.film_length` stays the one
estimate of an assembled film the reviews read; it composes these. Nothing here calls a model, a
vendor or the network, and nothing is bought.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import statistics
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import ROOT

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as np

logger = logging.getLogger(__name__)

#: The rules: research constants with their sources, the studio's choices with their reasons,
#: the switches, the channel defaults and the fallback pools (the Owner's proposal file).
RULES_FILE = ROOT / "config" / "pause_rules.json"
#: The derived, git-ignored cache of the measured voices, beside the films it is measured from.
PROFILE_CACHE_NAME = "voice_pause_profiles.json"
#: The layout of that cache; a cache of another layout is measured again.
PROFILE_CACHE_FORMAT = 1

# The boundary classes. Joins between two takes:
SENTENCE = "SENTENCE"
PARAGRAPH = "PARAGRAPH"
TURN = "TURN"
INTERRUPT = "INTERRUPT"
CARD = "CARD"
BEAT = "BEAT"
END = "END"
# Only between takes voiced row by row (no word timestamps came back), by the punctuation:
CLAUSE = "CLAUSE"
DASH = "DASH"
WORD = "WORD"
# A montage cut inside one take: the picture changes, the voice goes on, nothing is added.
IN_TAKE = "IN_TAKE"

JOIN_CLASSES = (END, CARD, BEAT, PARAGRAPH, INTERRUPT, TURN, SENTENCE, DASH, CLAUSE, WORD, IN_TAKE)
#: Classes that add no planned silence: the kept edges (or the voice's own pause) are heard.
EDGES_ONLY = frozenset({INTERRUPT, CARD, WORD, IN_TAKE})
#: Classes a writer's mark can lengthen into a BEAT. The end keeps the Owner's END, a card is
#: already a pause, an interruption has no gap and a cut inside a take is no join.
MARKABLE = frozenset({SENTENCE, PARAGRAPH, TURN, CLAUSE, DASH, WORD})
#: The END class says the film's last hold is one of these, as the channel's knob names it.
END_CLASSES = (PARAGRAPH, SENTENCE)

#: The two pools a voice falls back to while it has too few takes of its own.
NARRATOR_POOL = "narrator"
CHARACTER_POOL = "character"
POOLS = (NARRATOR_POOL, CHARACTER_POOL)

#: The storyboard kinds the assembler times as silent cards (`qc.MAX_SILENT_CARD_SECONDS`).
CARD_KINDS = frozenset({"BLACK", "TITLE_CARD", "DATA_CARD"})

#: The per-channel knobs, as the look files name them under "pauses".
KNOB_NAMES = ("tempo", "cut_in_pause", "picture_slide_words", "end_class")

_DASHES = ("—", "–", "--")
_ELLIPSES = ("…", "...")
_CLAUSE_MARKS = ",;:"
_CLOSERS = "\"'”’»)]}"
_VOWEL_GROUP = re.compile(r"[aeiouy]+")


class PauseRulesError(ValueError):
    """The rules file is missing, unreadable or not the shape the formulas need."""


# --------------------------------------------------------------------------------- the rules


def _value(entry: Any) -> Any:
    """A rule's value: the rules file writes each as {"value": ..., "source"/"why": ...}."""
    return entry.get("value") if isinstance(entry, dict) and "value" in entry else entry


def _number(section: Mapping[str, Any], name: str, *, positive: bool = True) -> float:
    raw = _value(section.get(name))
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise PauseRulesError(f"pause rule {name!r} is not a number")
    if positive and raw <= 0:
        raise PauseRulesError(f"pause rule {name!r} must be above 0")
    return float(raw)


@dataclass(frozen=True)
class Stat:
    """One measured pause: its median, its first quartile and how many it was read from, and
    where the number came from ("own" voice, "pool" of voices, or "config")."""

    median: float
    p25: float
    n: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"median": self.median, "p25": self.p25, "n": self.n, "source": self.source}


@dataclass(frozen=True)
class PauseRules:
    """config/pause_rules.json as the formulas read it."""

    version: int
    status: str
    in_use: bool
    switches: Mapping[str, bool]
    paragraph_ratio: float
    turn_seconds: float
    turn_floor_seconds: float
    beat_floor_seconds: float
    beat_ceiling_seconds: float
    beat_factor: float
    join_ceiling_seconds: float
    short_guard_syllables: int
    dead_air_tolerance: float
    no_pause_before_punchline: bool
    min_samples: int
    realised_pause_seconds: float
    body_pair: frozenset[str]
    factual_marks: tuple[str, ...]
    serial_mark_words: tuple[str, ...]
    marks_per_section: int
    wall_cap_seconds: float
    wall_stages: tuple[tuple[str, ...], ...]
    never_compressed: frozenset[str]
    rate_spread: float
    channel_defaults: Mapping[str, Any]
    fallback: Mapping[str, Mapping[str, Stat]]
    fallback_rates: Mapping[str, Mapping[str, float]]

    def switch(self, name: str) -> bool:
        """Whether a switch is on: never, while the Owner's proposal is not in use."""
        return bool(self.in_use and self.switches.get(name, False))


def parse_rules(data: Any) -> PauseRules:
    """The rules from the file's JSON; PauseRulesError naming the first thing missing."""
    if not isinstance(data, dict):
        raise PauseRulesError("the pause rules are not a JSON object")
    research = data.get("research")
    studio = data.get("studio")
    fallback = data.get("fallback")
    if not isinstance(research, dict) or not isinstance(studio, dict):
        raise PauseRulesError("the pause rules have no research or studio section")
    if not isinstance(fallback, dict):
        raise PauseRulesError("the pause rules have no fallback pools")
    switches_raw = data.get("switches")
    switches = {
        str(name): bool(_value(flag))
        for name, flag in (switches_raw.items() if isinstance(switches_raw, dict) else [])
    }
    pools: dict[str, dict[str, Stat]] = {}
    rates: dict[str, dict[str, float]] = {}
    for pool in POOLS:
        entry = fallback.get(pool)
        if not isinstance(entry, dict):
            raise PauseRulesError(f"the pause rules have no fallback pool {pool!r}")
        classes: dict[str, Stat] = {}
        for cls in (SENTENCE, CLAUSE, DASH):
            stat = entry.get(cls)
            if not isinstance(stat, dict):
                raise PauseRulesError(f"fallback pool {pool!r} has no {cls}")
            classes[cls] = Stat(
                median=_number(stat, "median"),
                p25=_number(stat, "p25"),
                n=int(_value(stat.get("n")) or 0),
                source="config",
            )
        rate = entry.get("rate")
        if not isinstance(rate, dict):
            raise PauseRulesError(f"fallback pool {pool!r} has no speech rate")
        pools[pool] = classes
        rates[pool] = {
            "seconds_per_word": _number(rate, "seconds_per_word"),
            "seconds_per_word_high": _number(rate, "seconds_per_word_high"),
        }
    marks = studio.get("beat_marks")
    marks = marks if isinstance(marks, dict) else {}
    stages = _value(studio.get("wall_stages"))
    if not isinstance(stages, list) or not all(isinstance(stage, list) for stage in stages):
        raise PauseRulesError("pause rule 'wall_stages' is not a list of class lists")
    defaults = data.get("channel_defaults")
    if not isinstance(defaults, dict):
        raise PauseRulesError("the pause rules have no channel_defaults")
    rules = PauseRules(
        version=int(data.get("version") or 0),
        status=str(data.get("status") or "PROPOSED"),
        in_use=bool(data.get("use_until_the_owner_changes_it", False)),
        switches=switches,
        paragraph_ratio=_number(research, "paragraph_ratio"),
        turn_seconds=_number(research, "turn_seconds"),
        turn_floor_seconds=_number(research, "turn_floor_seconds"),
        beat_floor_seconds=_number(research, "beat_floor_seconds"),
        beat_ceiling_seconds=_number(research, "beat_ceiling_seconds"),
        beat_factor=_number(research, "beat_factor"),
        join_ceiling_seconds=_number(research, "join_ceiling_seconds"),
        short_guard_syllables=int(_number(research, "short_guard_syllables")),
        dead_air_tolerance=_number(research, "dead_air_tolerance"),
        no_pause_before_punchline=bool(_value(research.get("no_pause_before_a_punchline"))),
        min_samples=int(_number(studio, "min_samples")),
        realised_pause_seconds=_number(studio, "realised_pause_seconds"),
        body_pair=frozenset(str(p).upper() for p in (_value(studio.get("body_pair")) or [])),
        factual_marks=tuple(str(m) for m in (_value(marks.get("factual")) or []) if str(m)),
        serial_mark_words=tuple(
            str(m).casefold() for m in (_value(marks.get("serial_words")) or []) if str(m)
        ),
        marks_per_section=int(_number(studio, "marks_per_section")),
        wall_cap_seconds=_number(studio, "wall_cap_seconds"),
        wall_stages=tuple(tuple(str(cls) for cls in stage) for stage in stages),
        never_compressed=frozenset(str(c) for c in (_value(studio.get("never_compressed")) or [])),
        rate_spread=_number(studio, "rate_spread"),
        channel_defaults={name: _value(defaults.get(name)) for name in KNOB_NAMES},
        fallback=pools,
        fallback_rates=rates,
    )
    if rules.beat_floor_seconds > rules.beat_ceiling_seconds:
        raise PauseRulesError("the beat's floor is above its ceiling")
    if rules.rate_spread > 1:
        raise PauseRulesError("pause rule 'rate_spread' is a share of the median (at most 1)")
    return rules


_RULES_CACHE: dict[tuple[str, int, int], PauseRules] = {}


def load_rules(path: Path | None = None) -> PauseRules:
    """The rules file read (once per version of the file); PauseRulesError when it is missing
    or broken. The formulas never make up a number the file does not hold."""
    source = Path(path or RULES_FILE)
    try:
        stat = source.stat()
    except OSError as exc:
        raise PauseRulesError(f"no pause rules at {source}") from exc
    key = (str(source), stat.st_mtime_ns, stat.st_size)
    cached = _RULES_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PauseRulesError(f"the pause rules at {source} cannot be read") from exc
    rules = parse_rules(data)
    _RULES_CACHE.clear()
    _RULES_CACHE[key] = rules
    return rules


def active_rules(path: Path | None = None) -> PauseRules | None:
    """The rules when the file is there, readable and in use; None otherwise, and the caller
    keeps the legacy timing (`assembler.LEGACY_SPOKEN_TAIL_SECONDS` and the old trim)."""
    try:
        rules = load_rules(path)
    except PauseRulesError as exc:
        logger.warning("pause_rules_unavailable", extra={"error": str(exc)})
        return None
    return rules if rules.in_use else None


def readable_rules(path: Path | None = None) -> PauseRules | None:
    """The rules when the file is there and readable, in use or not; None otherwise. What a
    film already frozen reads its formulas from (the wall's compression stages, a voice it did
    not freeze): its own numbers were frozen with it, and a later change of the rules, even
    switching them off, never re-times it (the Owner's decision 8, 2026-10-16)."""
    try:
        return load_rules(path)
    except PauseRulesError as exc:
        logger.warning("pause_rules_unreadable", extra={"error": str(exc)})
        return None


def switch(name: str, path: Path | None = None) -> bool:
    """Whether one of the rules' switches is on (off when the rules are not in use)."""
    rules = active_rules(path)
    return bool(rules and rules.switch(name))


# ------------------------------------------------------------------------- the channel's knobs


@dataclass(frozen=True)
class ChannelPauses:
    """The Owner's knobs for one channel (the look file's "pauses", else the rules' defaults):
    the tempo every pause is scaled by, where the picture cut falls inside a pause (1.0: the
    outgoing shot holds it all), how many words the picture may slide over the next phrase (0:
    no L-cut), and which pause the film's last word is held for."""

    tempo: float
    cut_in_pause: float
    picture_slide_words: int
    end_class: str
    source: str = "rules"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tempo": self.tempo,
            "cut_in_pause": self.cut_in_pause,
            "picture_slide_words": self.picture_slide_words,
            "end_class": self.end_class,
            "source": self.source,
        }


def _knobs(raw: Mapping[str, Any], source: str) -> ChannelPauses:
    tempo = raw.get("tempo")
    beta = raw.get("cut_in_pause")
    slide = raw.get("picture_slide_words")
    end = str(raw.get("end_class") or "").strip().upper()
    if isinstance(tempo, bool) or not isinstance(tempo, int | float) or not tempo > 0:
        raise PauseRulesError("pauses.tempo must be a number above 0")
    if isinstance(beta, bool) or not isinstance(beta, int | float) or not 0 <= beta <= 1:
        raise PauseRulesError("pauses.cut_in_pause must be between 0 and 1")
    if isinstance(slide, bool) or not isinstance(slide, int) or slide < 0:
        raise PauseRulesError("pauses.picture_slide_words must be a whole number, 0 or more")
    if end not in END_CLASSES:
        raise PauseRulesError(f"pauses.end_class must be one of {', '.join(END_CLASSES)}")
    return ChannelPauses(float(tempo), float(beta), int(slide), end, source)


def channel_pauses(
    channel: str, rules: PauseRules, *, look: Mapping[str, Any] | None = None
) -> ChannelPauses:
    """The knobs of the ``"factual"`` or ``"serial"`` channel: its look file's "pauses" over
    the rules' channel defaults. A knob the look file gets wrong is reported and the default
    is used: the film is never timed by a guess."""
    defaults = _knobs(dict(rules.channel_defaults), "rules")
    if look is None:
        from app.media.series_look import FACTUAL_LOOK_FILE, SERIES_LOOK_FILE  # noqa: PLC0415

        path = FACTUAL_LOOK_FILE if channel == "factual" else SERIES_LOOK_FILE
        try:
            look = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            look = None
    own = look.get("pauses") if isinstance(look, Mapping) else None
    if not isinstance(own, Mapping):
        return defaults
    merged = {**defaults.as_dict(), **{k: own[k] for k in KNOB_NAMES if k in own}}
    try:
        return _knobs(merged, f"{channel} look")
    except PauseRulesError as exc:
        logger.warning("pause_knobs_refused", extra={"channel": channel, "error": str(exc)})
        return defaults


# ------------------------------------------------------------------------- the voice's profile


def profile_key(provider: Any, model: Any, voice_id: Any) -> str | None:
    """Which recordings make one voice's profile: the vendor, its model and the voice. A new
    model or a new voice starts on its pool and earns its own numbers from its own takes."""
    if not voice_id:
        return None
    return f"{str(provider or '').strip().upper()}:{str(model or '').strip()}:{str(voice_id)}"


def voice_key_of(voice: Any) -> str | None:
    """The profile key of a voice adapter (``PROVIDER_NAME``, ``model``, ``voice_id``)."""
    return profile_key(
        getattr(voice, "PROVIDER_NAME", None),
        getattr(voice, "model", None),
        getattr(voice, "voice_id", None),
    )


@dataclass(frozen=True)
class Token:
    """One word of a take as the vendor timed it: from its first LETTER or DIGIT to its last,
    and the punctuation after its last letter (a spaced dash or ellipsis joins the word
    before it)."""

    text: str
    start: float
    end: float
    trail: str


def alignment_of(raw_response: Any) -> dict[str, Any] | None:
    """The vendor's character alignment of a take: ``alignment`` only. The
    ``normalized_alignment`` times the text as the vendor normalised it ("1964" spelt out),
    which is not the text the captions and the cuts are placed on."""
    if not isinstance(raw_response, Mapping):
        return None
    alignment = raw_response.get("alignment")
    if not isinstance(alignment, Mapping):
        return None
    characters = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not (
        isinstance(characters, list)
        and isinstance(starts, list)
        and isinstance(ends, list)
        and characters
        and len(characters) == len(starts) == len(ends)
    ):
        return None
    for char, start, end in zip(characters, starts, ends, strict=True):
        if not isinstance(char, str):
            return None
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
    return {
        "characters": list(characters),
        "character_start_times_seconds": [float(v) for v in starts],
        "character_end_times_seconds": [float(v) for v in ends],
    }


def alignment_tokens(alignment: Mapping[str, Any]) -> list[Token]:
    """The take's words from its character alignment (`alignment_of`), each timed from its
    first letter or digit to its last; punctuation is the word's trail, never its time."""
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    groups: list[list[int]] = []
    current: list[int] = []
    for index, char in enumerate(chars):
        if char.isspace():
            if current:
                groups.append(current)
                current = []
        else:
            current.append(index)
    if current:
        groups.append(current)
    tokens: list[Token] = []
    for group in groups:
        text = "".join(chars[i] for i in group)
        letters = [i for i in group if chars[i].isalnum()]
        if not letters:
            if tokens:  # a spaced dash or ellipsis: the trail of the word before it
                last = tokens[-1]
                tokens[-1] = Token(last.text + text, last.start, last.end, last.trail + text)
            continue
        trail = "".join(chars[i] for i in group if i > letters[-1])
        tokens.append(Token(text, float(starts[letters[0]]), float(ends[letters[-1]]), trail))
    return tokens


def last_letter_times(alignment: Mapping[str, Any]) -> tuple[float, float] | None:
    """(start, end) of the take's last letter or digit, as the vendor timed it; None when the
    take has none. The final "." the vendor stretches to the end of its file is not a letter."""
    chars = alignment["characters"]
    for index in range(len(chars) - 1, -1, -1):
        if chars[index].isalnum():
            return (
                float(alignment["character_start_times_seconds"][index]),
                float(alignment["character_end_times_seconds"][index]),
            )
    return None


def _strip_closers(text: str) -> str:
    return str(text or "").strip().rstrip(_CLOSERS)


def punctuation_class(word: str) -> str:
    """The class of the boundary after ``word`` (with its trailing punctuation): an ellipsis or
    a sentence end (`lines.ends_sentence`: never the stop of "Dr.") is SENTENCE, a dash DASH, a
    comma, semicolon or colon CLAUSE, anything else WORD."""
    from app.story.lines import ends_sentence  # noqa: PLC0415

    bare = _strip_closers(word)
    if not bare:
        return WORD
    if bare.endswith(_ELLIPSES):
        return SENTENCE
    if ends_sentence(word):
        return SENTENCE
    if bare.endswith(_DASHES):
        return DASH
    if bare[-1] in _CLAUSE_MARKS:
        return CLAUSE
    return WORD


def spoken_word_count(text: str) -> int:
    """How many words a voice says for ``text`` (`assembler.spoken_words`: a number is said in
    words), the one count every estimate reads."""
    from app.media.assembler import spoken_words  # noqa: PLC0415 - the assembler is heavy

    return int(spoken_words(text))


@dataclass(frozen=True)
class TakeTiming:
    """What one kept take says about its voice: its words, the time from its first letter to
    its last, and the pause (vendor's clock) at each boundary between two of its words."""

    voice: str
    voice_id: str
    words: int
    speech_seconds: float
    gaps: tuple[tuple[str, float], ...]


def take_timing(sidecar: Mapping[str, Any]) -> TakeTiming | None:
    """A kept narration take's timing from its sidecar (`assembler.keep_narration`); None when
    the sidecar has no character alignment or no word in it."""
    raw = sidecar.get("raw_response")
    alignment = alignment_of(raw)
    if alignment is None or not isinstance(raw, Mapping):
        return None
    key = profile_key(raw.get("provider"), raw.get("model"), raw.get("voice_id"))
    if key is None:
        return None
    tokens = alignment_tokens(alignment)
    if not tokens:
        return None
    text = "".join(alignment["characters"])
    words = spoken_word_count(text)
    speech = tokens[-1].end - tokens[0].start
    if words <= 0 or speech <= 0:
        return None
    gaps = tuple(
        (punctuation_class(a.text), max(0.0, b.start - a.end))
        for a, b in zip(tokens, tokens[1:], strict=False)
    )
    return TakeTiming(key, str(raw.get("voice_id")), words, round(speech, 4), gaps)


def _quartiles(values: Sequence[float]) -> tuple[float, float, int]:
    """(median, first quartile, n) of ``values``, inclusive quartiles as the measurement used."""
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0, 0.0, 0
    if len(ordered) == 1:
        return ordered[0], ordered[0], 1
    quarter = statistics.quantiles(ordered, n=4, method="inclusive")
    return float(statistics.median(ordered)), float(quarter[0]), len(ordered)


def _summary(timings: Sequence[TakeTiming], rules: PauseRules) -> dict[str, Any]:
    """The measured numbers of a set of takes (one voice's, or a pool's)."""
    by_class: dict[str, list[float]] = {SENTENCE: [], CLAUSE: [], DASH: []}
    for timing in timings:
        for cls, gap in timing.gaps:
            if cls == CLAUSE:
                # A comma is paused at only about half the time: the clause pause is the one
                # the voice makes when it pauses there.
                if gap >= rules.realised_pause_seconds:
                    by_class[CLAUSE].append(gap)
            elif cls in by_class:
                by_class[cls].append(gap)
    classes = {}
    for cls, values in by_class.items():
        median, p25, n = _quartiles(values)
        classes[cls] = {"median": round(median, 4), "p25": round(p25, 4), "n": n}
    words = sum(t.words for t in timings)
    speech = sum(t.speech_seconds for t in timings)
    per_take = [t.words / t.speech_seconds for t in timings]
    seconds_per_take_word = [t.speech_seconds / t.words for t in timings]
    wps_median, wps_p25, takes = _quartiles(per_take)
    spw_median, _, _ = _quartiles(seconds_per_take_word)
    return {
        "takes": takes,
        "words": words,
        "speech_seconds": round(speech, 3),
        "classes": classes,
        "rate": {
            "seconds_per_word": round(speech / words, 4) if words else None,
            "take_median_seconds_per_word": round(spw_median, 4) if takes else None,
            "take_median_words_per_second": round(wps_median, 4) if takes else None,
            "take_p25_words_per_second": round(wps_p25, 4) if takes else None,
        },
    }


def character_voice_ids() -> frozenset[str]:
    """The voices the serial's cast proposes (config/serial_voice_cast.json): their takes
    measure the character pool, every other voice's the narrator pool."""
    from app.media.speaker_voices import load_voice_cast  # noqa: PLC0415

    return frozenset(load_voice_cast()["proposed"].values())


def measure_profiles(
    sidecars: Iterable[Mapping[str, Any]],
    *,
    rules: PauseRules,
    characters: Iterable[str] = (),
) -> dict[str, Any]:
    """Every voice's measured numbers and the two pools', from kept takes' sidecars. A voice
    whose id is in ``characters`` is measured into the character pool, any other into the
    narrator pool."""
    character_ids = frozenset(characters)
    by_voice: dict[str, list[TakeTiming]] = {}
    for sidecar in sidecars:
        timing = take_timing(sidecar)
        if timing is not None:
            by_voice.setdefault(timing.voice, []).append(timing)
    voices: dict[str, Any] = {}
    pools: dict[str, list[TakeTiming]] = {pool: [] for pool in POOLS}
    for key, timings in sorted(by_voice.items()):
        pool = CHARACTER_POOL if timings[0].voice_id in character_ids else NARRATOR_POOL
        pools[pool].extend(timings)
        voices[key] = {"pool": pool, **_summary(timings, rules)}
    return {
        "format": PROFILE_CACHE_FORMAT,
        "takes": sum(len(t) for t in by_voice.values()),
        "voices": voices,
        "pools": {pool: _summary(timings, rules) for pool, timings in pools.items()},
    }


def narration_sidecars(media_root: Path) -> list[Path]:
    """Every kept narration take's sidecar under ``media_root`` (<film>/narration/*.json):
    only a PAID take is kept there (`assembler.keep_narration`)."""
    from app.media.assembler import NARRATION_FOLDER, NARRATION_SIDECAR  # noqa: PLC0415

    root = Path(media_root)
    if not root.is_dir():
        return []
    return sorted(root.glob(f"*/{NARRATION_FOLDER}/*{NARRATION_SIDECAR}"))


def take_set_key(paths: Sequence[Path], root: Path, rules: PauseRules) -> str:
    """The cache's identity: which takes it was measured from (each sidecar's place, size and
    time) and under which rules."""
    digest = hashlib.sha256(f"rules:{rules.version}:{PROFILE_CACHE_FORMAT}".encode())
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        digest.update(f"\n{relative}|{stat.st_size}|{stat.st_mtime_ns}".encode())
    return digest.hexdigest()


def load_profiles(
    media_root: Path | None = None, *, rules: PauseRules, write: bool = True
) -> dict[str, Any]:
    """The measured voices of the kept takes under ``media_root`` (the studio's media root by
    default), from the derived cache while no take has been added since it was written,
    measured again otherwise (and the cache rewritten when ``write``). A sidecar that cannot be
    read is skipped: the profile measures, it never invents."""
    if media_root is None:
        from app.media.disk import media_root as configured_root  # noqa: PLC0415

        media_root = configured_root()
    root = Path(media_root)
    paths = narration_sidecars(root)
    key = take_set_key(paths, root, rules)
    cache = root / PROFILE_CACHE_NAME
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict) and cached.get("key") == key:
        return cached
    sidecars: list[Mapping[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            sidecars.append(data)
    profiles = measure_profiles(sidecars, rules=rules, characters=character_voice_ids())
    profiles["key"] = key
    if write and root.is_dir():
        _write_atomic(cache, profiles)
    return profiles


def _write_atomic(path: Path, data: Mapping[str, Any]) -> None:
    """``data`` written to ``path`` whole or not at all (a temporary file, then replaced)."""
    try:
        handle, temporary = tempfile.mkstemp(prefix=".pauses_", dir=str(path.parent))
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(temporary, path)
    except OSError as exc:
        logger.warning("voice_profiles_not_cached", extra={"error": type(exc).__name__})


@dataclass(frozen=True)
class VoiceProfile:
    """One voice's numbers as a film is timed by them: its sentence, clause and dash pauses
    and its speech rate (the median seconds a word, and the high one a clip is bought for),
    each with where it came from."""

    key: str
    pool: str
    sentence: Stat
    clause: Stat
    dash: Stat
    seconds_per_word: float
    seconds_per_word_high: float
    rate_source: str
    takes: int = 0

    def stat(self, cls: str) -> Stat:
        return {SENTENCE: self.sentence, CLAUSE: self.clause, DASH: self.dash}[cls]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "pool": self.pool,
            "sentence": self.sentence.as_dict(),
            "clause": self.clause.as_dict(),
            "dash": self.dash.as_dict(),
            "seconds_per_word": self.seconds_per_word,
            "seconds_per_word_high": self.seconds_per_word_high,
            "rate_source": self.rate_source,
            "takes": self.takes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VoiceProfile:
        """A profile as a film froze it (`snapshot`)."""

        def stat(entry: Mapping[str, Any]) -> Stat:
            return Stat(
                float(entry["median"]),
                float(entry["p25"]),
                int(entry.get("n") or 0),
                str(entry.get("source") or "frozen"),
            )

        return cls(
            key=str(data["key"]),
            pool=str(data.get("pool") or NARRATOR_POOL),
            sentence=stat(data["sentence"]),
            clause=stat(data["clause"]),
            dash=stat(data["dash"]),
            seconds_per_word=float(data["seconds_per_word"]),
            seconds_per_word_high=float(data["seconds_per_word_high"]),
            rate_source=str(data.get("rate_source") or "frozen"),
            takes=int(data.get("takes") or 0),
        )


def _measured_stat(entry: Any, minimum: int, source: str) -> Stat | None:
    if not isinstance(entry, Mapping):
        return None
    n = int(entry.get("n") or 0)
    if n < minimum:
        return None
    return Stat(float(entry["median"]), float(entry["p25"]), n, source)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rate(summary: Any) -> Mapping[str, Any]:
    rate = summary.get("rate") if isinstance(summary, Mapping) else None
    return rate if isinstance(rate, Mapping) else {}


def voice_profile(
    voice_key: str | None,
    *,
    rules: PauseRules,
    profiles: Mapping[str, Any] | None = None,
    pool: str | None = None,
) -> VoiceProfile:
    """A voice's numbers, each from the first of: the voice's own kept takes (at least the
    rules' min_samples of that pause), its pool's takes, the rules' fallback pool. The speech
    rate is the voice's own from its first kept take, its high end from its own takes' first
    quartile once it has min_samples of them, else from its median and the pool's spread.
    ``pool`` is the pool the caller speaks the voice in (a narrator or a character); by
    default the one the voice was measured in, else the narrator's."""
    measured: Mapping[str, Any] = profiles if isinstance(profiles, Mapping) else {}
    voices = _mapping(measured.get("voices"))
    own = _mapping(voices.get(voice_key)) if voice_key else {}
    chosen = pool or str(own.get("pool") or NARRATOR_POOL)
    if chosen not in POOLS:
        chosen = NARRATOR_POOL
    measured_pool = _mapping(_mapping(measured.get("pools")).get(chosen))
    minimum = rules.min_samples

    def stat(cls: str) -> Stat:
        return (
            _measured_stat(_mapping(own.get("classes")).get(cls), minimum, "own")
            or _measured_stat(_mapping(measured_pool.get("classes")).get(cls), minimum, "pool")
            or rules.fallback[chosen][cls]
        )

    own_rate, pool_rate = _rate(own), _rate(measured_pool)
    own_takes = int(own.get("takes") or 0)
    pool_takes = int(measured_pool.get("takes") or 0)
    if pool_takes >= minimum and pool_rate.get("take_p25_words_per_second"):
        spread = float(pool_rate["take_p25_words_per_second"]) / float(
            pool_rate["take_median_words_per_second"]
        )
    else:
        spread = rules.rate_spread
    if own_takes >= minimum and own_rate.get("take_p25_words_per_second"):
        median = float(own_rate["seconds_per_word"])
        high = 1.0 / float(own_rate["take_p25_words_per_second"])
        source = "own"
    elif own_takes >= 1 and own_rate.get("seconds_per_word"):
        median = float(own_rate["seconds_per_word"])
        high = float(own_rate["take_median_seconds_per_word"]) / spread
        source = f"own ({own_takes} takes, high end by the pool's spread)"
    elif pool_takes >= minimum and pool_rate.get("take_p25_words_per_second"):
        median = float(pool_rate["seconds_per_word"])
        high = 1.0 / float(pool_rate["take_p25_words_per_second"])
        source = "pool"
    else:
        median = rules.fallback_rates[chosen]["seconds_per_word"]
        high = rules.fallback_rates[chosen]["seconds_per_word_high"]
        source = "config"
    return VoiceProfile(
        key=str(voice_key or f"{chosen}-pool"),
        pool=chosen,
        sentence=stat(SENTENCE),
        clause=stat(CLAUSE),
        dash=stat(DASH),
        seconds_per_word=round(median, 4),
        seconds_per_word_high=round(max(high, median), 4),
        rate_source=source,
        takes=own_takes,
    )


# ---------------------------------------------------------------------------- the boundaries


@dataclass(frozen=True)
class Boundary:
    """A join's class, the class it would have had without the writer's mark, and the mark."""

    cls: str
    base: str
    marked: bool = False
    mark_dropped: str | None = None


def _text(side: Mapping[str, Any] | None) -> str:
    return " ".join(str((side or {}).get("text") or "").split())


def _last_word(text: str) -> str:
    words = text.split()
    return words[-1] if words else ""


def is_card(side: Mapping[str, Any] | None) -> bool:
    """A silent card row: a BLACK, TITLE_CARD or DATA_CARD with nothing said."""
    if side is None:
        return False
    kind = str(side.get("kind") or "").strip().upper()
    return kind in CARD_KINDS and not _text(side)


def ends_in_dash(text: str) -> bool:
    return _strip_closers(text).endswith(_DASHES)


def factual_marked(text: str, rules: PauseRules) -> bool:
    """A factual writer scene that ends in the writer's mark («…»): a real silence after it."""
    bare = _strip_closers(text)
    return any(bare.endswith(mark) for mark in rules.factual_marks)


def direction_marked(direction: Any, rules: PauseRules) -> bool:
    """A serial direction that asks for a silence («(beat)», "pause")."""
    words = re.findall(r"[^\W\d_]+", str(direction or "").casefold())
    phrase = " ".join(words)
    return any(
        re.search(rf"(?<![\w]){re.escape(mark)}(?![\w])", phrase)
        for mark in rules.serial_mark_words
    )


def boundary_class(
    out: Mapping[str, Any],
    inn: Mapping[str, Any] | None,
    *,
    serial: bool,
    rules: PauseRules,
) -> Boundary:
    """The class of the join after ``out`` (a take, or a row voiced on its own) before ``inn``
    (None after the film's last word). Each side is a mapping: ``text`` (the words said),
    ``voice`` (profile key), ``speaker`` (None for the narrator), ``scene`` (the writer's scene
    or the beat), ``purpose`` (factual story_purpose), ``kind`` (a card kind), ``take`` (the
    voice take it is said in), ``direction``, ``mark_before``/``mark_after`` (where a serial
    mark stood) and ``punchline``. Checked from the top, the first match wins: END, CARD,
    IN_TAKE, then PARAGRAPH, INTERRUPT, TURN, and the punctuation (SENTENCE, DASH, CLAUSE,
    WORD); a writer's mark then lengthens the join into a BEAT, never before a punchline."""
    base = _base_class(out, inn, serial=serial, rules=rules)
    if inn is None or base not in MARKABLE or not rules.switch("marked_beats"):
        return Boundary(base, base)
    if serial:
        if any(key in side for side in (out, inn) for key in ("mark_after", "mark_before")):
            marked = bool(out.get("mark_after")) or bool(inn.get("mark_before"))
        else:
            marked = direction_marked(out.get("direction"), rules)
    else:
        marked = out.get("scene") != inn.get("scene") and factual_marked(_text(out), rules)
    if not marked:
        return Boundary(base, base)
    if inn.get("punchline") and rules.no_pause_before_punchline:
        # Measured jokes carry no pause before the punchline (Attardo & Pickering 2011).
        return Boundary(base, base, marked=True, mark_dropped="punchline")
    return Boundary(BEAT, base, marked=True)


def _base_class(
    out: Mapping[str, Any], inn: Mapping[str, Any] | None, *, serial: bool, rules: PauseRules
) -> str:
    if inn is None:
        return END
    if is_card(out) or is_card(inn):
        return CARD
    take = out.get("take")
    if take is not None and take == inn.get("take"):
        return IN_TAKE
    text = _text(out)
    if serial:
        if out.get("scene") != inn.get("scene"):
            return PARAGRAPH  # a beat ends
        if (out.get("speaker") is None) != (inn.get("speaker") is None):
            return PARAGRAPH  # the narrator and the room hand over
        if out.get("speaker") != inn.get("speaker"):
            return INTERRUPT if ends_in_dash(text) else TURN
        return punctuation_class(_last_word(text))
    if out.get("scene") != inn.get("scene"):
        before = str(out.get("purpose") or "").strip().upper()
        after = str(inn.get("purpose") or "").strip().upper()
        if before and after and before != after and {before, after} != rules.body_pair:
            return PARAGRAPH
    return punctuation_class(_last_word(text))


# ------------------------------------------------------------------------ targets and floors


def syllables(text: str) -> int:
    """A rough syllable count, as the short-sentence guard needs it: vowel groups a word, a
    silent final e dropped, at least one a word; a number two syllables a word it is said in."""
    count = 0
    for token in re.findall(r"[^\W_]+(?:['’][^\W_]+)*", str(text or "")):
        if token[0].isdigit():
            count += 2 * spoken_word_count(token)
            continue
        word = token.casefold()
        groups = len(_VOWEL_GROUP.findall(word))
        if word.endswith("e") and not word.endswith(("le", "ee")) and groups > 1:
            groups -= 1
        count += max(1, groups)
    return count


def _sentences(text: str) -> list[str]:
    from app.story.lines import ends_sentence  # noqa: PLC0415

    sentences: list[str] = []
    current: list[str] = []
    for word in str(text or "").split():
        current.append(word)
        if ends_sentence(word) or _strip_closers(word).endswith(_ELLIPSES):
            sentences.append(" ".join(current))
            current = []
    if current:
        sentences.append(" ".join(current))
    return sentences


def short_guard(out_text: str, in_text: str, rules: PauseRules) -> bool:
    """Whether both sentences beside a SENTENCE join are short (at most the rules' syllables):
    a short pause occurs only next to a short phrase (Zvonik 2003), so the join takes the
    voice's first-quartile pause instead of its median."""
    before = _sentences(out_text)
    after = _sentences(in_text)
    if not before or not after:
        return False
    limit = rules.short_guard_syllables
    return syllables(before[-1]) <= limit and syllables(after[0]) <= limit


def target(
    cls: str,
    *,
    out: VoiceProfile | None,
    inn: VoiceProfile | None,
    narrator: VoiceProfile,
    knobs: ChannelPauses,
    rules: PauseRules,
    short: bool = False,
    base: str | None = None,
) -> float:
    """The planned silence T of a join of class ``cls``, in seconds (0.0 where only the kept
    edges, the card or the voice's own pause are heard). ``base`` is the class a BEAT would
    otherwise have had; ``short`` the short-sentence guard."""
    tempo = knobs.tempo
    if cls in EDGES_ONLY:
        return 0.0
    if cls == BEAT:
        underlying = 0.0
        if base and base != BEAT:
            underlying = target(
                base, out=out, inn=inn, narrator=narrator, knobs=knobs, rules=rules, short=short
            )
        seconds = min(
            max(rules.beat_factor * underlying, rules.beat_floor_seconds),
            rules.beat_ceiling_seconds,
        )
        return round(min(seconds, rules.join_ceiling_seconds), 3)
    speaker = out or narrator
    if cls == SENTENCE:
        seconds = tempo * (speaker.sentence.p25 if short else speaker.sentence.median)
    elif cls == PARAGRAPH:
        listener = inn or speaker
        seconds = (
            tempo * rules.paragraph_ratio * max(speaker.sentence.median, listener.sentence.median)
        )
    elif cls == END:
        if knobs.end_class == SENTENCE:
            seconds = tempo * narrator.sentence.median
        else:
            seconds = tempo * rules.paragraph_ratio * narrator.sentence.median
    elif cls == TURN:
        seconds = min(
            max(tempo * rules.turn_seconds, rules.turn_floor_seconds),
            tempo * speaker.sentence.median,
        )
    elif cls in (CLAUSE, DASH):
        seconds = tempo * speaker.stat(cls).median
    else:
        raise ValueError(f"unknown pause class {cls!r}")
    return round(min(seconds, rules.join_ceiling_seconds), 3)


def floor(
    cls: str,
    seconds: float,
    *,
    out: VoiceProfile | None,
    inn: VoiceProfile | None,
    narrator: VoiceProfile,
    rules: PauseRules,
) -> float:
    """The shortest a join of class ``cls`` may be compressed to for the wall (never above its
    planned ``seconds``): a voice's first-quartile pause, the turn's floor. A BEAT, a card and
    the joins with no planned silence are never compressed."""
    if cls in rules.never_compressed or cls in EDGES_ONLY or cls == BEAT:
        return round(seconds, 3)
    speaker = out or narrator
    if cls == SENTENCE:
        value = speaker.sentence.p25
    elif cls == PARAGRAPH:
        listener = inn or speaker
        value = rules.paragraph_ratio * max(speaker.sentence.p25, listener.sentence.p25)
    elif cls == END:
        value = narrator.sentence.p25
    elif cls == TURN:
        value = rules.turn_floor_seconds
    elif cls in (CLAUSE, DASH):
        value = speaker.stat(cls).p25
    else:
        raise ValueError(f"unknown pause class {cls!r}")
    return round(min(value, seconds), 3)


# ---------------------------------------------------------------------------- the estimates


def _words(text_or_words: str | int) -> int:
    if isinstance(text_or_words, int) and not isinstance(text_or_words, bool):
        return max(0, text_or_words)
    return spoken_word_count(str(text_or_words or ""))


def speech_seconds(
    text_or_words: str | int, voice: VoiceProfile, *, high: bool = False, margin: float = 0.0
) -> float:
    """How long ``voice`` takes to say these words, first letter to last: its median seconds a
    word, or the high one (``high``: what a clip is bought for), plus ``margin`` as a share."""
    rate = voice.seconds_per_word_high if high else voice.seconds_per_word
    return round(_words(text_or_words) * rate * (1.0 + margin), 3)


def _whole_frames(seconds: float, fps: int | None, *, up: bool) -> float:
    from app.media.assembler import TIMELINE_FPS, whole_frames  # noqa: PLC0415

    return float(whole_frames(seconds, fps or TIMELINE_FPS, up=up))


def row_estimate(
    text_or_words: str | int,
    voice: VoiceProfile,
    *,
    cut_in_pause: float,
    pause_out: float = 0.0,
    pause_in: float = 0.0,
    dissolve: float = 0.0,
    margin: float = 0.0,
    fps: int | None = None,
) -> float:
    """A row's clip before the voice exists, on whole frames up: its words at the voice's high
    rate plus ``margin``, the share ``cut_in_pause`` of the pause after it (on a take's last
    row) and the rest of the pause before it (on a take's first row), and any dissolve."""
    seconds = speech_seconds(text_or_words, voice, high=True, margin=margin)
    seconds += cut_in_pause * max(0.0, pause_out) + (1.0 - cut_in_pause) * max(0.0, pause_in)
    seconds += max(0.0, dissolve)
    return round(_whole_frames(seconds, fps, up=True), 3)


@dataclass(frozen=True)
class FilmEstimate:
    """A film's length before anything is bought: speech + planned pauses + silent cards."""

    seconds: float
    speech_seconds: float
    pause_seconds: float
    card_seconds: float
    rows: int


def film_estimate(
    sides: Sequence[Mapping[str, Any]],
    pauses: Sequence[Mapping[str, Any] | None],
    voices: Callable[[Mapping[str, Any]], VoiceProfile],
    *,
    margin: float = 0.0,
) -> FilmEstimate:
    """The film: every side's words at its voice's median rate (plus ``margin``), every
    planned pause after it (``pauses[i]["seconds"]``, frozen on the row), every silent card's
    own length (``card_seconds``). A cut inside one take adds nothing: its pause is the voice's
    own, already inside the rate."""
    speech = pause = cards = 0.0
    for side, after in zip(sides, pauses, strict=True):
        if is_card(side):
            cards += float(side.get("card_seconds") or 0.0)
        elif _text(side):
            speech += speech_seconds(_text(side), voices(side), margin=margin)
        if isinstance(after, Mapping):
            pause += float(after.get("seconds") or 0.0)
    return FilmEstimate(
        round(speech + pause + cards, 3),
        round(speech, 3),
        round(pause, 3),
        round(cards, 3),
        len(sides),
    )


# ------------------------------------------------------------------------------------ the wall


@dataclass(frozen=True)
class WallFit:
    """How a film's pauses were fitted under its wall: the seconds of each join, the factor of
    each compression stage, and what is still over when even the floors do not fit."""

    seconds: tuple[float, ...]
    factors: tuple[float, ...]
    budget: float
    total: float
    over_seconds: float

    @property
    def fits(self) -> bool:
        return self.over_seconds <= 0.0


def wall_seconds(channel_max: float | None, rules: PauseRules) -> float:
    """The wall: the channel's Shorts maximum, never past the rules' cap."""
    if (
        isinstance(channel_max, int | float)
        and not isinstance(channel_max, bool)
        and channel_max > 0
    ):
        return min(float(channel_max), rules.wall_cap_seconds)
    return rules.wall_cap_seconds


def _floor_ms(value: float) -> float:
    return math.floor(value * 1000 + 1e-9) / 1000


def fit_to_wall(
    joins: Sequence[Mapping[str, Any]],
    *,
    fixed_seconds: float,
    wall: float,
    rules: PauseRules,
) -> WallFit:
    """``joins`` (each ``{class, seconds, floor}``) compressed toward their floors until the
    film (``fixed_seconds`` of speech and cards plus the joins) fits ``wall``. The rules' stages
    go in order (the row-voiced CLAUSE and DASH first, then SENTENCE, PARAGRAPH, END and TURN);
    inside a stage one common factor k shrinks every join's distance to its floor, so the ladder
    keeps its order. A BEAT and a card are never compressed."""
    seconds = [round(float(j.get("seconds") or 0.0), 3) for j in joins]
    floors = [min(float(j.get("floor") or 0.0), s) for j, s in zip(joins, seconds, strict=True)]
    classes = [str(j.get("class") or "") for j in joins]
    factors: list[float] = []
    for stage in rules.wall_stages:
        over = fixed_seconds + sum(seconds) - wall
        members = [
            i
            for i, cls in enumerate(classes)
            if cls in stage and cls not in rules.never_compressed and seconds[i] > floors[i]
        ]
        room = sum(seconds[i] - floors[i] for i in members)
        if over <= 1e-9 or room <= 0:
            factors.append(1.0)
            continue
        k = max(0.0, 1.0 - over / room)
        for i in members:
            seconds[i] = max(floors[i], _floor_ms(floors[i] + k * (seconds[i] - floors[i])))
        factors.append(round(k, 4))
    total = round(fixed_seconds + sum(seconds), 3)
    return WallFit(tuple(seconds), tuple(factors), wall, total, round(max(0.0, total - wall), 3))


# ---------------------------------------------------------------------------------- the render


def render_pad(target_seconds: float, kept_tail: float, next_head: float) -> float:
    """The silence the render adds after a take: the planned T less the silence the trim kept
    after the take's last sound and before the next take's first, never negative (the vendor's
    own tail noise stays, so a join is never digital zero where it had any)."""
    return round(max(0.0, float(target_seconds) - max(0.0, kept_tail) - max(0.0, next_head)), 4)


def snap_cumulative(spans: Sequence[float], fps: int) -> list[float]:
    """``spans`` laid end to end with every cut on a frame of the timeline: each cut lands on the
    frame nearest its exact time, so a film of many rows never drifts from its voice."""
    out: list[float] = []
    exact = 0.0
    placed = 0
    for span in spans:
        exact += float(span)
        frame = round(exact * fps)
        out.append((frame - placed) / fps)
        placed = frame
    return out


# ----------------------------------------------------------------------------------- the freeze


@dataclass
class Frozen:
    """A film's pauses as frozen on its storyboard: one record a side (the join after it),
    the snapshot of every number they were made from, and the wall fit."""

    pauses: list[dict[str, Any]]
    snapshot: dict[str, Any]
    estimate: FilmEstimate
    wall: dict[str, Any] | None = field(default=None)


def snapshot(
    voices: Mapping[str, VoiceProfile],
    *,
    narrator: VoiceProfile,
    knobs: ChannelPauses,
    rules: PauseRules,
    profile_cache_key: str | None = None,
) -> dict[str, Any]:
    """Every number a film's pauses were frozen from: the rules' version, the channel's knobs,
    each voice's profile, the switches as they stood (the trim the film is cut by) and the
    limits quality control reads its silences against (production.timeline.pause_profile): a
    film is timed and judged by these, whatever the rules say later."""
    return {
        "rule_version": rules.version,
        "rules_status": rules.status,
        "knobs": knobs.as_dict(),
        "narrator": narrator.key,
        "profile_key": profile_cache_key,
        "voices": {key: voice.as_dict() for key, voice in sorted(voices.items())},
        "switches": {name: rules.switch(name) for name in sorted(rules.switches)},
        "limits": {
            "dead_air_tolerance": rules.dead_air_tolerance,
            "join_ceiling_seconds": rules.join_ceiling_seconds,
        },
    }


def freeze(
    sides: Sequence[Mapping[str, Any]],
    *,
    serial: bool,
    rules: PauseRules,
    knobs: ChannelPauses,
    profiles: Mapping[str, Any] | None,
    narrator_voice: str | None,
    wall: float | None = None,
    margin: float = 0.0,
    fallbacks: bool = True,
) -> Frozen:
    """Each side's join planned and frozen: its class (`boundary_class`), its seconds
    (`target`, with the short-sentence guard), its floor, whether a writer marked it, the voice
    whose pause it is, how many words the side says (``words``: each speaker's part of a row
    is sized at its own voice's rate, `film_length.frozen_rows`) and the rules' version. At
    most the rules' marks a section (a factual section, a serial beat) become a BEAT, the
    first ones; a serial mark is counted in the beat it was written in (a «(beat)» before a
    beat's first line is that beat's, not the one before). With ``wall``, the joins are fitted
    under it (`fit_to_wall`) against the film's speech (the voices' median rates plus
    ``margin``) and cards.

    With ``fallbacks``, a cut inside a take (IN_TAKE) carries the join it would be were its
    sides voiced apart (``fallback``: class, seconds, floor): the render's join when the take
    is voiced row by row after all, and the voice's own pause there, which the outgoing shot
    holds (`film_length`)."""
    resolved: dict[str, VoiceProfile] = {}

    def voice(key: str | None, pool: str | None) -> VoiceProfile:
        name = f"{key}|{pool}"
        if name not in resolved:
            resolved[name] = voice_profile(key, rules=rules, profiles=profiles, pool=pool)
        return resolved[name]

    narrator = voice(narrator_voice, None)

    def side_voice(side: Mapping[str, Any]) -> VoiceProfile:
        key = side.get("voice") or narrator_voice
        pool = side.get("pool")
        if not pool and side.get("speaker") and key != narrator_voice:
            pool = CHARACTER_POOL  # a character's voice not measured yet: the cast's pool
        return voice(str(key) if key else None, str(pool) if pool else None)

    records: list[dict[str, Any]] = []
    marks: dict[Any, int] = {}
    section = 0
    for index, out in enumerate(sides):
        inn = sides[index + 1] if index + 1 < len(sides) else None
        boundary = boundary_class(out, inn, serial=serial, rules=rules)
        cls, dropped = boundary.cls, boundary.mark_dropped
        where: Any = section
        if serial:
            # The beat the writer's mark was written in: a mark before the next side's line
            # is the next beat's (`pause_plan.serial_lines` keeps one a beat on that count).
            marked_in = (
                inn is not None and bool(inn.get("mark_before")) and not out.get("mark_after")
            )
            where = (inn or {}).get("scene") if marked_in else out.get("scene")
        if cls == BEAT:
            used = marks.get(where, 0)
            if used >= rules.marks_per_section:
                cls, dropped = boundary.base, "one_per_section"
            else:
                marks[where] = used + 1
        if not serial and boundary.base == PARAGRAPH:
            section += 1
        speaker = None if is_card(out) else side_voice(out)
        listener = None if inn is None or is_card(inn) else side_voice(inn)
        short = cls == SENTENCE and inn is not None and short_guard(_text(out), _text(inn), rules)
        seconds = target(
            cls,
            out=speaker,
            inn=listener,
            narrator=narrator,
            knobs=knobs,
            rules=rules,
            short=short,
            base=boundary.base,
        )
        record: dict[str, Any] = {
            "class": cls,
            "seconds": seconds,
            "floor": floor(cls, seconds, out=speaker, inn=listener, narrator=narrator, rules=rules),
            "marked": boundary.marked,
            "voice_key": speaker.key if speaker else None,
            "words": _words(_text(out)) if speaker else 0,
            "rule_version": rules.version,
        }
        if cls == BEAT:
            record["unmarked_class"] = boundary.base
        if dropped:
            record["mark_dropped"] = dropped
        if short:
            record["short_guard"] = True
        records.append(record)
    estimate = film_estimate(sides, records, side_voice, margin=margin)
    fitted: dict[str, Any] | None = None
    if wall is not None:
        fixed = estimate.speech_seconds + estimate.card_seconds
        fit = fit_to_wall(records, fixed_seconds=fixed, wall=wall, rules=rules)
        for record, seconds in zip(records, fit.seconds, strict=True):
            if seconds != record["seconds"]:
                record["target"] = record["seconds"]
                record["seconds"] = seconds
                record["wall_k"] = list(fit.factors)
        estimate = film_estimate(sides, records, side_voice, margin=margin)
        fitted = {
            "wall": fit.budget,
            "factors": list(fit.factors),
            "estimate": estimate.seconds,
            "over_seconds": fit.over_seconds,
            "fits": fit.fits,
        }
    if fallbacks and any(record["class"] == IN_TAKE for record in records):
        alone = freeze(
            [{**side, "take": None} for side in sides],
            serial=serial,
            rules=rules,
            knobs=knobs,
            profiles=profiles,
            narrator_voice=narrator_voice,
            wall=wall,
            margin=margin,
            fallbacks=False,
        )
        for record, single in zip(records, alone.pauses, strict=True):
            if record["class"] == IN_TAKE:
                record["fallback"] = {
                    key: single[key] for key in ("class", "seconds", "floor") if key in single
                }
    voices: dict[str, VoiceProfile] = {}
    for profile in resolved.values():
        name = profile.key if profile.key not in voices else f"{profile.key}|{profile.pool}"
        voices[name] = profile
    return Frozen(
        pauses=records,
        snapshot=snapshot(
            voices,
            narrator=narrator,
            knobs=knobs,
            rules=rules,
            profile_cache_key=(profiles or {}).get("key"),
        ),
        estimate=estimate,
        wall=fitted,
    )


def frozen_pause(beat: Any) -> dict[str, Any] | None:
    """The pause frozen on a storyboard row's beat tag (``prompt_json["beat"]["pause_after"]``),
    when it is one; None for a legacy row, which keeps the legacy timing."""
    after = beat.get("pause_after") if isinstance(beat, Mapping) else None
    if not isinstance(after, Mapping):
        return None
    seconds = after.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds < 0:
        return None
    if str(after.get("class") or "") not in JOIN_CLASSES:
        return None
    return dict(after)


# -------------------------------------------------------------------------------- the trim cut


@dataclass(frozen=True)
class TrimCut:
    """Where a take is cut, in samples: ``head`` (the first sample kept) and ``tail`` (the
    first sample cut away), and the silence the meter hears inside what is kept, before its
    first sound and after its last (``kept_head``, ``kept_tail``, seconds)."""

    head: int
    tail: int
    letter_cut: int
    guard_point: int
    guard_moved: bool
    kept_head: float
    kept_tail: float


def loud_samples(
    frames: bytes, sample_width: int, channels: int, threshold_db: float
) -> np.ndarray:
    """Per sample frame, whether any channel is at or above ``threshold_db`` dBFS."""
    import numpy as np  # noqa: PLC0415

    if sample_width == 1:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.int32) - 128
        scale = 128.0
    elif sample_width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.int32)
        scale = 32768.0
    elif sample_width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        data = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        data = np.where(data >= 1 << 23, data - (1 << 24), data)
        scale = float(1 << 23)
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.int64)
        scale = float(1 << 31)
    else:
        raise ValueError(f"unsupported sample width {sample_width}")
    level = np.abs(data.astype(np.float64)) / scale
    if channels > 1:
        level = level[: len(level) - len(level) % channels].reshape(-1, channels).max(axis=1)
    threshold = 10 ** (threshold_db / 20)
    return np.asarray(level >= threshold)


def _quiet_runs(loud: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(starts, ends) of every run of samples under the threshold."""
    import numpy as np  # noqa: PLC0415

    quiet = ~loud
    edges = np.diff(np.concatenate(([0], quiet.astype(np.int8), [0])))
    return np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)


def trim_cut(
    loud: np.ndarray,
    rate: int,
    *,
    last_letter: tuple[float, float],
    lead_seconds: float,
    edge_keep: float,
    settle_seconds: float,
) -> TrimCut | None:
    """Where to cut a take so its tail ends with its last letter and no sound is split (the
    Owner's decision 7, 2026-10-16):

    - the tail at the later of (the last letter's end + ``edge_keep``) and the first point after
      the last letter starts where the signal falls under the threshold and stays there for
      ``settle_seconds`` (or stays quiet to the end of the file); if that point would split a
      sound, the next such point; speech is never cut;
    - the head by the meter (``lead_seconds`` - ``edge_keep``), never past the first sample at
      or above the threshold.

    None when the take has no sound at all."""
    import numpy as np  # noqa: PLC0415

    n = int(len(loud))
    if n == 0 or not bool(loud.any()):
        return None
    starts, ends = _quiet_runs(loud)
    settle = int(round(settle_seconds * rate))
    settled = ((ends - starts) >= settle) | (ends == n)
    letter_start = int(round(max(0.0, last_letter[0]) * rate))
    letter_cut = min(n, int(round((max(0.0, last_letter[1]) + edge_keep) * rate)))
    after_letter = np.flatnonzero(settled & (ends > letter_start))
    guard = int(starts[after_letter[0]]) if len(after_letter) else n
    tail = max(letter_cut, guard)
    moved = False
    if tail < n:
        inside = settled & (starts <= tail) & (tail < ends)
        if not bool(inside.any()):
            later = np.flatnonzero(settled & (starts >= tail))
            tail = int(starts[later[0]]) if len(later) else n
            moved = True
    first_loud = int(np.argmax(loud))
    head = min(int(round(max(0.0, lead_seconds - edge_keep) * rate)), first_loud)
    kept = loud[head:tail]
    if not bool(kept.any()):
        return None
    kept_first = int(np.argmax(kept))
    kept_last = len(kept) - 1 - int(np.argmax(kept[::-1]))
    return TrimCut(
        head=head,
        tail=tail,
        letter_cut=letter_cut,
        guard_point=guard,
        guard_moved=moved,
        kept_head=round(kept_first / rate, 4),
        kept_tail=round((len(kept) - 1 - kept_last) / rate, 4),
    )


def kept_edges(loud: np.ndarray, rate: int, head: int, tail: int) -> tuple[float, float] | None:
    """(silence before the first sound, after the last) inside samples [head, tail)."""
    import numpy as np  # noqa: PLC0415

    kept = loud[head:tail]
    if len(kept) == 0 or not bool(kept.any()):
        return None
    first = int(np.argmax(kept))
    last = len(kept) - 1 - int(np.argmax(kept[::-1]))
    return round(first / rate, 4), round((len(kept) - 1 - last) / rate, 4)
