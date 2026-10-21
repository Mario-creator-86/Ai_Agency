"""How long the assembled film will be, and how long each of its clips must be, before anything
is bought: the studio's ONE estimate.

2026-10-16 (the adversarial review of the montage day): the factual review measured a script
at 2.6 words a second plus 0.35 s per writer's scene, and the serial review at 2.5 words a
second with 5 s left for every breath. The montage cuts a writer's scene or a beat into shots
(`montage.factual_shots`, `montage.serial_shots`), and the assembler then gave every shot with
words a breath of its own (LEGACY_SPOKEN_TAIL_SECONDS). A 442-word script the review passed
became a 194 s film, which quality control refused at YouTube's 180 s wall after the stills,
clips and voice of its 56 shots were bought, and no repair can make words shorter.

The same day the Owner approved «pauza vocii» (`app.media.pauses`): one voice take per
writer's scene and per speaker's run, the montage cutting the picture on the take's own words
(nothing added), and between two takes the pause this voice makes at this kind of boundary,
frozen on the storyboard when it is built (`pause_plan.freeze_rows`). This module is the one
estimate every reader of a film's length uses, built on those rules:

- a SCRIPT (the factual brief and review, the serial review): its words cut as the storyboard
  builders will cut them, its joins classed and timed exactly as the freeze will time them
  (`pauses.freeze` over the same sides), each voice at its own measured rate (`speech_seconds`):
  `factual_film_length`, `serial_film_length`, and each row's clip (`factual_clips`,
  `serial_clips`: the words at the voice's high rate plus the estimate's margin, the share of
  the pauses the row's shot holds, the voice's own pause at a cut inside its take
  (`in_take_holds`), the dissolve, on whole frames up, `pauses.row_estimate`);
- a STORYBOARD already built (the motion plan, the sheet, the render's pre-check): its own
  frozen pauses and the voices they were frozen from (`frozen_rows`: each speaker's part at
  its own voice's rate), never a constant, whatever the rules say now (`is_frozen`); a film
  frozen over its wall buys nothing (`wall_refusal`);
- the WALL: min(the channel's Shorts maximum, 180 s) (`pauses.wall_seconds`). The script is
  held under it with the speech's margin (``FilmLength.wall_seconds``: the words at the median
  rate plus NARRATION_ESTIMATE_MARGIN, the pauses unfitted, the cards); the render keeps the
  pauses' compression toward their floors as its reserve (`pauses.fit_to_wall`).

With the pause rules switched off (or unreadable) every estimate is the legacy one, exactly as
the film is then timed: each row with words its takes at SECONDS_PER_SPOKEN_WORD plus the
edges, SPEAKER_GAP_SECONDS between two speakers, LEGACY_SPOKEN_TAIL_SECONDS after it, rounded up
to a frame, and the reviews hold the estimate WALL_MARGIN_SECONDS under the wall.

What stays an estimate, and which way it errs: a take's pace spreads around its voice's rate
(the high rate a clip is bought for is the voice's own first quartile, so most takes come in
under it, and a clip may still be slowed 25% at 0 USD); a number and its unit said aloud
("299,792,458 m/s") are longer than `spoken_words` foresees; a scene's kind is read from the
script, and the storyboard's content gate may still turn a LIVE scene into a card, which only
shortens the film. Quality control's own measurement of the delivered file stays the last word
(`qc.evaluate_media_qc`).

Nothing here is bought, sent anywhere or written; the measured voices are read from their
derived cache (`pauses.load_profiles`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from app.media import pauses as pause_rules
from app.media.montage import factual_shots, montage_settings, serial_shots

logger = logging.getLogger(__name__)

#: YouTube's Shorts limit: the longest a vertical film may be and still be a Short. The same
#: number as `qc.SHORTS_MAX_LIMIT_SECONDS` and `editorial.MAX_SHORT_SECONDS` (a test holds the
#: three equal; this module cannot import quality control, which imports the editorial rules).
#: The wall with the pause rules off; under them the wall is the channel's maximum, never past
#: the rules' own cap (config/pause_rules.json studio.wall_cap_seconds, `pauses.wall_seconds`),
#: the one the storyboard is frozen and the render fitted under (`review_ceiling_seconds`).
SHORTS_WALL_SECONDS = 180.0
#: With the pause rules off, how far under the wall the reviews hold the legacy estimate: about
#: one standard deviation of the takes' pace over a film at the ceiling. Under the rules the
#: margin is the speech's own (NARRATION_ESTIMATE_MARGIN, ``FilmLength.wall_seconds``).
WALL_MARGIN_SECONDS = 3.0
#: The kinds the assembler times as cards when they are silent; anything else is LIVE.
CARD_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
#: How the factual storyboard plans a row whose writer stated no length: its words at this
#: rate, within MIN/MAX (`media.services.generate_storyboard_from_script`). Only a row with no
#: words is timed by its plan.
PLANNED_WORDS_PER_SECOND = 2.5
PLANNED_MIN_SECONDS = 3.0
PLANNED_MAX_SECONDS = 9.0
#: The most words a scene's cut point is looked for in: a narration is at most 800
#: characters (`agent_pipeline._Scene`), well under this many words.
CUT_SEARCH_WORDS = 200

FACTUAL = "factual"
SERIAL = "serial"


@dataclass(frozen=True)
class FilmLength:
    """A film as it will be cut and timed: its length, its rows, and how much of it is words.

    ``seconds`` is the film expected (the words at each voice's median rate, the planned
    pauses, the cards): what a target length is aimed at. ``wall_seconds`` is what the wall is
    held against: the words with the estimate's margin, the same pauses and cards (the legacy
    estimate's own length when the pause rules are off)."""

    seconds: float
    rows: int
    speaking_rows: int
    #: The takes' estimated words alone, without their edges, gaps or pauses.
    spoken_seconds: float
    wall_seconds: float | None = None
    #: The planned pauses (the joins between takes) and the silent rows (cards, plans).
    pause_seconds: float = 0.0
    silent_seconds: float = 0.0

    @property
    def against_wall(self) -> float:
        """The number the wall is checked against."""
        return self.wall_seconds if self.wall_seconds is not None else self.seconds


# ---------------------------------------------------------------------------------- the timing


@dataclass(frozen=True)
class Timing:
    """What one estimate is made by, read once: the pause rules in use (None: the legacy
    timing), the channel's knobs, the measured voices, the narrator's voice and each speaker's
    (profile keys, `pauses.profile_key`; None where not known: the voice's pool)."""

    rules: Any = None
    knobs: Any = None
    profiles: Mapping[str, Any] | None = None
    narrator: str | None = None
    speakers: Mapping[str, str | None] = field(default_factory=dict)
    channel: str = FACTUAL

    @property
    def paused(self) -> bool:
        """Whether the film is timed by the pause rules."""
        return self.rules is not None


def timing(
    channel: str = FACTUAL,
    *,
    narrator: str | None = None,
    speakers: Mapping[str, str | None] | None = None,
    rules: Any = None,
    profiles: Mapping[str, Any] | None = None,
) -> Timing:
    """The timing of a ``"factual"`` or ``"serial"`` estimate: the pause rules when they are in
    use, the channel's knobs, the measured voices (`pauses.load_profiles`)."""
    rules = rules or pause_rules.active_rules()
    if rules is None:
        return Timing(channel=channel)
    knobs = pause_rules.channel_pauses(channel, rules)
    if profiles is None:
        try:
            profiles = pause_rules.load_profiles(rules=rules)
        except OSError as exc:
            logger.warning("voice_profiles_unread", extra={"error": type(exc).__name__})
            profiles = None
    return Timing(
        rules=rules,
        knobs=knobs,
        profiles=profiles,
        narrator=narrator,
        speakers=dict(speakers or {}),
        channel=channel,
    )


@lru_cache(maxsize=1)
def _legacy() -> SimpleNamespace:
    """The assembler's own timing numbers, read once (the assembler is heavy and imports
    quality control, which imports the editorial rules that import this module)."""
    from app.media.assembler import (  # noqa: PLC0415
        LEGACY_SPOKEN_TAIL_SECONDS,
        NARRATION_ESTIMATE_MARGIN,
        SECONDS_PER_SPOKEN_WORD,
        TIMELINE_FPS,
        spoken_words,
        whole_frames,
    )
    from app.media.qc import MAX_SILENT_CARD_SECONDS  # noqa: PLC0415
    from app.media.speaker_voices import SPEAKER_GAP_SECONDS, speaker_segments  # noqa: PLC0415
    from app.media.toolchain import EDGE_KEEP_SECONDS  # noqa: PLC0415

    return SimpleNamespace(
        per_word=SECONDS_PER_SPOKEN_WORD,
        tail=LEGACY_SPOKEN_TAIL_SECONDS,
        margin=NARRATION_ESTIMATE_MARGIN,
        fps=TIMELINE_FPS,
        edge=EDGE_KEEP_SECONDS,
        gap=SPEAKER_GAP_SECONDS,
        card_max=dict(MAX_SILENT_CARD_SECONDS),
        spoken_words=spoken_words,
        whole_frames=whole_frames,
        speaker_segments=speaker_segments,
    )


def voice_of(side: Mapping[str, Any], when: Timing) -> pause_rules.VoiceProfile:
    """The voice a side is said in, as `pauses.freeze` resolves it: the side's own voice, else
    the narrator's; a character whose voice is not known speaks in the cast's pool."""
    key = side.get("voice") or when.narrator
    pool = side.get("pool")
    if not pool and side.get("speaker") and key != when.narrator:
        pool = pause_rules.CHARACTER_POOL
    return pause_rules.voice_profile(
        str(key) if key else None,
        rules=when.rules,
        profiles=when.profiles,
        pool=str(pool) if pool else None,
    )


def narrator_profile(when: Timing | None = None) -> pause_rules.VoiceProfile | None:
    """The narrator's voice as the estimate times it; None with the pause rules off."""
    when = when or timing(FACTUAL)
    if not when.paused:
        return None
    return voice_of({"voice": when.narrator, "pool": pause_rules.NARRATOR_POOL}, when)


def film_timing(when: Timing | None = None) -> dict[str, Any]:
    """The numbers a brief states, from the estimate itself: the narrator's seconds a word
    (``seconds_per_word``), the pause between two of his writer's scenes (``breath_seconds``:
    his full-stop pause, or the legacy breath after every shot), the pause at a change of part
    (``section_seconds``), what a cut inside his take adds (``in_take_seconds``: nothing under
    the rules), and the marked silence's band (``beat_seconds``: (floor, ceiling), None when
    the writer's marks are off)."""
    when = when or timing(FACTUAL)
    if not when.paused:
        legacy = _legacy()
        return {
            "seconds_per_word": float(legacy.per_word),
            "breath_seconds": float(legacy.tail),
            "section_seconds": float(legacy.tail),
            "in_take_seconds": float(legacy.tail),
            "beat_seconds": None,
            "paused": False,
        }
    rules, knobs = when.rules, when.knobs
    narrator = narrator_profile(when)
    assert narrator is not None
    common = {
        "out": narrator,
        "inn": narrator,
        "narrator": narrator,
        "knobs": knobs,
        "rules": rules,
    }
    return {
        "seconds_per_word": narrator.seconds_per_word,
        "breath_seconds": pause_rules.target(pause_rules.SENTENCE, **common),
        "section_seconds": pause_rules.target(pause_rules.PARAGRAPH, **common),
        "in_take_seconds": 0.0,
        "beat_seconds": (
            (rules.beat_floor_seconds, rules.beat_ceiling_seconds)
            if rules.switch("marked_beats")
            else None
        ),
        "paused": True,
    }


def review_ceiling_seconds(wall: float = SHORTS_WALL_SECONDS, when: Timing | None = None) -> float:
    """The longest estimate a review accepts against ``wall`` (the channel's, as the reviews
    read it, `pause_plan.channel_wall`): under the pause rules the wall itself, never past the
    rules' cap (`pauses.wall_seconds`, what the storyboard is frozen and the render fitted
    under), the estimate carrying its own margin (``wall_seconds``); with them off, the wall
    less WALL_MARGIN_SECONDS, never past YouTube's limit."""
    rules = when.rules if when is not None else pause_rules.active_rules()
    if rules is not None:
        return round(pause_rules.wall_seconds(float(wall), rules), 1)
    bounded = min(float(wall), SHORTS_WALL_SECONDS)
    return round(bounded - WALL_MARGIN_SECONDS, 1)


def montage_options(settings: Any = None) -> SimpleNamespace:
    """The montage's settings, read once, in the shape `montage.montage_settings` reads: an
    estimate cuts dozens of scenes, and the studio's settings are not read again for each."""
    if isinstance(settings, SimpleNamespace) and hasattr(settings, "montage_enabled"):
        return settings
    options = montage_settings(settings)
    return SimpleNamespace(
        montage_enabled=options["enabled"],
        montage_shot_seconds=options["shot_seconds"],
        montage_max_shots_per_scene=options["max_shots"],
    )


# ------------------------------------------------------------------------------- the factual


def scene_kind(scene: Mapping[str, Any]) -> str:
    """A factual scene's kind as the script stores it (``scene_kind``; the writer's ``kind``);
    an unknown or missing kind is LIVE, as the assembler reads it."""
    kind = str(scene.get("scene_kind") or scene.get("kind") or "LIVE").strip().upper()
    return kind if kind in CARD_KINDS else "LIVE"


def _narration(scene: Mapping[str, Any]) -> str:
    return str(
        scene.get("voiceover_segment") or scene.get("voiceover") or scene.get("narration") or ""
    ).strip()


def _purpose(scene: Mapping[str, Any]) -> str | None:
    value = str(scene.get("purpose") or scene.get("story_purpose") or "").strip().upper()
    return value or None


def factual_rows(
    scenes: Sequence[Mapping[str, Any]], *, settings: Any = None
) -> list[dict[str, Any]]:
    """A factual script's storyboard rows, as `media.services` cuts and plans them: a LIVE
    scene in the montage's shots (`montage.factual_shots`), a card one row. Each row:
    ``{scene_number, shot, of, narration, scene_kind, story_purpose, transition_in,
    duration_seconds}`` — the writer's transition on a scene's first shot only, and
    ``duration_seconds`` only where the writer stated one for an uncut scene (a stated plan is
    a floor of the clip; the storyboard's own default plan is `planned_seconds`)."""
    options = montage_options(settings)
    rows: list[dict[str, Any]] = []
    for number, scene in enumerate(scenes, start=1):
        kind = scene_kind(scene)
        for shot in factual_shots(_narration(scene), number, live=kind == "LIVE", settings=options):
            row: dict[str, Any] = {
                "scene_number": number,
                "shot": int(shot["shot"]),
                "of": int(shot["of"]),
                "narration": str(shot["narration"] or "").strip(),
                "scene_kind": kind,
                "story_purpose": _purpose(scene),
                "transition_in": (
                    str(scene.get("transition_in") or "CUT") if int(shot["shot"]) <= 1 else "CUT"
                ),
            }
            stated = scene.get("duration_seconds")
            if int(shot["of"]) <= 1 and isinstance(stated, int | float) and stated > 0:
                row["duration_seconds"] = float(stated)
            rows.append(row)
    return rows


def planned_seconds(row: Mapping[str, Any]) -> float:
    """A factual row's plan as the storyboard writes it: the writer's stated length for an
    uncut scene, else its words at PLANNED_WORDS_PER_SECOND within 3-9 s."""
    stated = row.get("duration_seconds")
    if isinstance(stated, int | float) and stated > 0:
        return float(stated)
    words = len(str(row.get("narration") or "").split())
    return min(
        PLANNED_MAX_SECONDS,
        max(PLANNED_MIN_SECONDS, round(words / PLANNED_WORDS_PER_SECOND, 1)),
    )


def factual_sides(rows: Sequence[Mapping[str, Any]], when: Timing) -> list[dict[str, Any]]:
    """The rows as the freeze reads them (`pause_plan.factual_side`, as the storyboard builds
    them): one side a row, its writer's scene its voice take, said by the narrator."""
    from app.media.pause_plan import factual_side  # noqa: PLC0415 - pause_plan reads qc

    sides: list[dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
        side = factual_side(
            str(row.get("narration") or row.get("voiceover_segment") or ""),
            scene=int(row.get("scene_number") or position),
            purpose=row.get("story_purpose") or row.get("purpose"),
            kind=scene_kind(row),
            planned_seconds=planned_seconds(row),
            rules=when.rules,
        )
        sides.append({**side, "voice": when.narrator})
    return sides


def _frozen(
    sides: Sequence[Mapping[str, Any]], when: Timing, *, serial: bool, fallbacks: bool = True
) -> Any:
    """The joins of ``sides`` classed and timed exactly as the storyboard will freeze them,
    before the wall's compression (the estimate is held against the wall with its margin; the
    compression is the render's reserve); with ``fallbacks``, a cut inside a take carries the
    voice's own pause there (`pauses.freeze`), what a clip is sized for."""
    return pause_rules.freeze(
        sides,
        serial=serial,
        rules=when.rules,
        knobs=when.knobs,
        profiles=when.profiles,
        narrator_voice=when.narrator,
        fallbacks=fallbacks,
    )


def _silent_row_seconds(plan: float, kind: str | None) -> float:
    """A row with no words that is no card: its plan, on whole frames."""
    legacy = _legacy()
    if kind in legacy.card_max:
        return float(legacy.whole_frames(min(float(plan), legacy.card_max[kind]), legacy.fps))
    return float(legacy.whole_frames(float(plan), legacy.fps))


def _paused_length(
    sides: Sequence[Mapping[str, Any]],
    plans: Sequence[float],
    when: Timing,
    *,
    serial: bool,
    speaking_rows: int,
    rows: int,
) -> FilmLength:
    frozen = _frozen(sides, when, serial=serial, fallbacks=False)
    estimate = frozen.estimate
    # A row with no words that is no card (a silent LIVE shot) keeps its plan on the timeline.
    silent = sum(
        _silent_row_seconds(plan, None)
        for side, plan in zip(sides, plans, strict=True)
        if not pause_rules.is_card(side) and not str(side.get("text") or "").strip()
    )
    margin = float(_legacy().margin)
    expected = estimate.seconds + silent
    walled = estimate.speech_seconds * (1.0 + margin) + estimate.pause_seconds
    walled += estimate.card_seconds + silent
    return FilmLength(
        seconds=round(expected, 3),
        rows=rows,
        speaking_rows=speaking_rows,
        spoken_seconds=round(estimate.speech_seconds, 3),
        wall_seconds=round(walled, 3),
        pause_seconds=round(estimate.pause_seconds, 3),
        silent_seconds=round(estimate.card_seconds + silent, 3),
    )


def factual_film_length(
    scenes: Sequence[Mapping[str, Any]], *, settings: Any = None, when: Timing | None = None
) -> FilmLength:
    """How long a factual script's film will be, cut and timed as the studio will."""
    rows = factual_rows(scenes, settings=settings)
    when = when or timing(FACTUAL)
    if not when.paused:
        return _legacy_factual(rows)
    sides = factual_sides(rows, when)
    speaking = sum(1 for side in sides if str(side.get("text") or "").strip())
    return _paused_length(
        sides,
        [planned_seconds(row) for row in rows],
        when,
        serial=False,
        speaking_rows=speaking,
        rows=len(rows),
    )


def _dissolves(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """The dissolve into each row from the one before (`assembler.scene_joins`)."""
    from app.media.assembler import scene_joins  # noqa: PLC0415 - the assembler is heavy

    return scene_joins([dict(row) for row in rows])


def _clip(
    speech: float,
    inner: float,
    out: float,
    into: float,
    beta: float,
    dissolve: float,
    held: float = 0.0,
) -> float:
    legacy = _legacy()
    seconds = speech + inner + beta * out + (1.0 - beta) * into + dissolve + held
    return round(float(legacy.whole_frames(seconds, legacy.fps, up=True)), 3)


def in_take_holds(records: Sequence[Any], beta: float, slide: int) -> list[float]:
    """Per side (each record is the join after one), the voice's own pause its shot holds at
    a picture cut inside its take: a cut inside a take adds no silence, but the voice pauses
    there as it always does (at a full stop, its own sentence pause: the record's
    ``fallback``, the join it would be were the sides voiced apart), and the cut falls
    ``cut_in_pause`` into that pause (1.0: the outgoing shot holds it all, the incoming none);
    an L-cut (``picture_slide_words``) cuts after it, so the outgoing shot holds it all. What
    a clip is sized for before the voice exists, which measures the words alone; a voiced
    take measures the pause with its words. 0.0 where the join is no cut inside a take."""
    holds = [0.0] * len(records)
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or record.get("class") != pause_rules.IN_TAKE:
            continue
        fallback = record.get("fallback")
        seconds = fallback.get("seconds") if isinstance(fallback, Mapping) else None
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
            continue
        outgoing = 1.0 if slide > 0 else max(0.0, min(1.0, float(beta)))
        holds[index] += outgoing * float(seconds)
        if index + 1 < len(records):
            holds[index + 1] += (1.0 - outgoing) * float(seconds)
    return [round(value, 4) for value in holds]


def _joined(records: Sequence[Any]) -> list[bool]:
    """Per side, whether it goes on in the take the side before it is said in (the join
    before it is a cut inside a take)."""
    return [False] + [
        isinstance(record, Mapping) and record.get("class") == pause_rules.IN_TAKE
        for record in records[:-1]
    ]


def factual_clips(
    rows: Sequence[Mapping[str, Any]], *, when: Timing | None = None
) -> dict[int, float]:
    """Per filmed row (by position, from 1, as its storyboard numbers it), the clip the
    motion plan will buy for it before a word is voiced: its words at the narrator's high
    rate plus the estimate's margin, the share of the pauses its shot holds (``cut_in_pause``
    of the pause after it on a take's last row, the rest of the pause before it on a take's
    first), the voice's own pause at a cut inside its take (`in_take_holds`), the dissolve
    into the next row, on whole frames up; never shorter than a plan the row states. A cut
    inside one take adds no silence, and an L-cut's words are the outgoing row's
    (`pause_plan.slid_units`). ``rows`` are storyboard rows (`factual_rows`) or, with the
    montage off, the script's scenes themselves."""
    from app.media.pause_plan import slid_units  # noqa: PLC0415 - pause_plan reads qc

    when = when or timing(FACTUAL)
    if not when.paused:
        return _legacy_clips(rows)
    legacy = _legacy()
    sides = factual_sides(rows, when)
    frozen = _frozen(sides, when, serial=False)
    beta = float(when.knobs.cut_in_pause)
    slide = int(when.knobs.picture_slide_words)
    holds = in_take_holds(frozen.pauses, beta, slide)
    texts = slid_units(
        [str(side.get("text") or "") for side in sides], _joined(frozen.pauses), slide
    )
    joins = _dissolves(rows)
    sizes: dict[int, float] = {}
    for position, (row, side) in enumerate(zip(rows, sides, strict=True)):
        if scene_kind(row) in CARD_KINDS:
            continue
        said = texts[position]
        out = float(frozen.pauses[position]["seconds"])
        into = float(frozen.pauses[position - 1]["seconds"]) if position else 0.0
        dissolve = joins[position + 1] if position + 1 < len(joins) else 0.0
        voiced = 0.0
        if legacy.spoken_words(said) > 0:
            speech = pause_rules.speech_seconds(
                said, voice_of(side, when), high=True, margin=float(legacy.margin)
            )
            voiced = _clip(speech, 0.0, out, into, beta, dissolve, holds[position])
        stated = row.get("duration_seconds")
        planned = (
            _motion_seconds(float(stated)) if isinstance(stated, int | float) and stated else 0.0
        )
        sizes[position + 1] = max(voiced, planned)
    return sizes


def _motion_seconds(plan: float) -> float:
    from app.media.assembler import motion_seconds  # noqa: PLC0415 - the assembler is heavy

    return float(motion_seconds({"duration_seconds": plan}))


# -------------------------------------------------------------------------------- the serial


def serial_rows(
    lines_by_beat: Sequence[Sequence[Mapping[str, Any]]],
    parts: Sequence[str | None],
    *,
    settings: Any = None,
    rules: Any = None,
) -> list[tuple[int, dict[str, Any]]]:
    """An episode's storyboard rows, as `storyboard_from_episode` cuts them: the writer's
    marks and voice takes named (`pause_plan.serial_lines`, under the rules), then each beat in
    the montage's shots (`montage.serial_shots`). (beat number, shot) pairs."""
    from app.media.pause_plan import serial_lines  # noqa: PLC0415

    options = montage_options(settings)
    lines = serial_lines(lines_by_beat, list(parts), rules) if rules is not None else lines_by_beat
    rows: list[tuple[int, dict[str, Any]]] = []
    for number, (said, part) in enumerate(zip(lines, parts, strict=True), start=1):
        for shot in serial_shots(
            [dict(line) for line in said],
            number,
            part=part,
            first_beat=number == 1,
            settings=options,
        ):
            rows.append((number, shot))
    return rows


def _serial_sides(
    rows: Sequence[tuple[int, Mapping[str, Any]]], when: Timing
) -> tuple[list[dict[str, Any]], list[int]]:
    """Every row's sides (`pause_plan.serial_row_sides`: one per speaker's run inside one
    take), each in its speaker's voice where it is known, and which row each side is of."""
    from app.media.pause_plan import serial_row_sides  # noqa: PLC0415

    sides: list[dict[str, Any]] = []
    owners: list[int] = []
    for position, (beat, shot) in enumerate(rows):
        row_sides, _runs = serial_row_sides(list(shot.get("lines") or []), beat=beat)
        if not row_sides:
            row_sides = [{"text": "", "scene": beat, "speaker": None, "kind": None}]
        for side in row_sides:
            speaker = side.get("speaker")
            voice = when.speakers.get(str(speaker)) if speaker else when.narrator
            sides.append({**side, "voice": voice})
            owners.append(position)
    return sides, owners


def serial_film_length(
    lines_by_beat: Sequence[Sequence[Mapping[str, Any]]],
    parts: Sequence[str | None],
    *,
    settings: Any = None,
    when: Timing | None = None,
) -> FilmLength:
    """How long an episode's film will be: each beat cut into the montage's shots, each shot
    its speakers' runs in their own voices at their own rates, the joins classed and timed as
    the storyboard freezes them (a speaker change, a beat's end, the narrator handing over, a
    writer's marked beat). A shot with no words keeps the storyboard's 3 s plan."""
    when = when or timing(SERIAL)
    if not when.paused:
        return _legacy_serial(lines_by_beat, parts, settings=settings)
    rows = serial_rows(lines_by_beat, parts, settings=settings, rules=when.rules)
    sides, owners = _serial_sides(rows, when)
    plans = [PLANNED_MIN_SECONDS for _ in sides]
    speaking = len({owner for side, owner in zip(sides, owners, strict=True) if side.get("text")})
    return _paused_length(sides, plans, when, serial=True, speaking_rows=speaking, rows=len(rows))


def serial_clips(
    lines_by_beat: Sequence[Sequence[Mapping[str, Any]]],
    parts: Sequence[str | None],
    *,
    settings: Any = None,
    when: Timing | None = None,
) -> list[list[float]]:
    """Per beat, the clip each of its shots needs before a word is voiced: each run's words at
    its voice's high rate plus the estimate's margin, the joins between the shot's own runs,
    the share of the pauses before and after it the shot holds, the voice's own pause at a
    cut inside a speaker's take (`in_take_holds`; an L-cut's words are the outgoing shot's);
    on whole frames up. A serial shot cuts to the next one, so no dissolve is added."""
    from app.media.pause_plan import slid_units  # noqa: PLC0415 - pause_plan reads qc

    when = when or timing(SERIAL)
    beats = len(lines_by_beat)
    if not when.paused:
        options = montage_options(settings)
        out: list[list[float]] = [[] for _ in range(beats)]
        for number, (said, part) in enumerate(zip(lines_by_beat, parts, strict=True), start=1):
            for shot in serial_shots(
                [dict(line) for line in said],
                number,
                part=part,
                first_beat=number == 1,
                settings=options,
            ):
                out[number - 1].append(legacy_shot_clip(shot["lines"]))
        return out
    legacy = _legacy()
    rows = serial_rows(lines_by_beat, parts, settings=settings, rules=when.rules)
    sides, owners = _serial_sides(rows, when)
    frozen = _frozen(sides, when, serial=True)
    beta = float(when.knobs.cut_in_pause)
    slide = int(when.knobs.picture_slide_words)
    holds = in_take_holds(frozen.pauses, beta, slide)
    texts = slid_units(
        [str(side.get("text") or "") for side in sides], _joined(frozen.pauses), slide
    )
    clips: list[list[float]] = [[] for _ in range(beats)]
    for position, (beat, _shot) in enumerate(rows):
        mine = [i for i, owner in enumerate(owners) if owner == position]
        first, last = mine[0], mine[-1]
        speech = sum(
            pause_rules.speech_seconds(
                texts[i],
                voice_of(sides[i], when),
                high=True,
                margin=float(legacy.margin),
            )
            for i in mine
            if texts[i].strip()
        )
        inner = sum(float(frozen.pauses[i]["seconds"]) for i in mine[:-1])
        out_pause = float(frozen.pauses[last]["seconds"])
        into = float(frozen.pauses[first - 1]["seconds"]) if first else 0.0
        held = sum(holds[i] for i in mine)
        clips[beat - 1].append(_clip(speech, inner, out_pause, into, beta, 0.0, held))
    return clips


def shot_clip_seconds(
    lines: Sequence[Mapping[str, Any]], *, beat: int = 1, when: Timing | None = None
) -> float:
    """The clip one serial shot's lines need on their own, before a word is voiced: each
    speaker's run at their voice's high rate with the estimate's margin, the joins between the
    runs as the freeze classes them (a speaker change, an interruption), and after the last
    one the longest pause a shot can be followed by (the film's end, the narrator's paragraph
    pause), on whole frames up. Inside its episode a shot is sized by `serial_clips`."""
    when = when or timing(SERIAL)
    if not when.paused:
        return legacy_shot_clip(lines)
    from app.media.pause_plan import serial_row_sides  # noqa: PLC0415

    legacy = _legacy()
    found, _runs = serial_row_sides([dict(line) for line in lines], beat=beat)
    sides = [
        {
            **side,
            "voice": when.speakers.get(str(side.get("speaker")))
            if side.get("speaker")
            else when.narrator,
        }
        for side in found
    ]
    if not sides:
        return 0.0
    frozen = _frozen(sides, when, serial=True)
    speech = sum(
        pause_rules.speech_seconds(
            str(side.get("text") or ""),
            voice_of(side, when),
            high=True,
            margin=float(legacy.margin),
        )
        for side in sides
        if str(side.get("text") or "").strip()
    )
    inner = sum(float(record["seconds"]) for record in frozen.pauses[:-1])
    out = float(frozen.pauses[-1]["seconds"])
    return _clip(speech, inner, out, 0.0, float(when.knobs.cut_in_pause), 0.0)


# ---------------------------------------------------------------------- a storyboard's own rows


@dataclass(frozen=True)
class RowPause:
    """What a storyboard row's frozen pauses ask of its shot: the voice its words are said in
    (the slowest of its takes'), the planned silence after its words when its take ends there
    (``out``; 0 inside a take), the one before them when its take starts there (``into``), the
    joins between its own takes (``inner``, of ``joins`` frozen records) and where the picture
    cut falls inside a pause (``beta``, the channel's ``cut_in_pause`` frozen with the film).
    ``after`` is the planned seconds of its pause after as a join between two of its own takes
    (the render's join where the row holds more takes than inner records,
    `assembler._unit_join`). ``room`` is what that pause may give up, in whole frames, toward
    its floor before the row's clip is called too short (`assembler._clip_slowdowns`): none
    for a marked beat, a card or a join with no planned silence.

    Before its words are voiced the row is read as `factual_clips` and `serial_clips` read it
    (the one estimate, the Owner's decision 10): ``speech`` is its words at each speaker's own
    high rate (each part of a row said by two voices at its own voice's, from the words the
    freeze counted on each; the slowest voice for the whole row when the words changed since),
    an L-cut's words counted on the shot they are said under (``slide``); ``held`` is the
    voice's own pause its shot holds at a cut inside its take (`in_take_holds`), which a
    voiced take measures with its words."""

    voice: pause_rules.VoiceProfile | None
    out: float
    into: float
    inner: float
    beta: float
    joins: int = 0
    after: float = 0.0
    room: float = 0.0
    speech: float | None = None
    held: float = 0.0
    slide: int = 0

    @property
    def share(self) -> float:
        """The seconds of silence this row's shot holds: the share of the pause after it, the
        rest of the pause before it, and its own inner joins."""
        return round(self.beta * self.out + (1.0 - self.beta) * self.into + self.inner, 4)


def _row_join(record: Any) -> float:
    """A frozen join's planned seconds as the render lays it: a cut inside one take adds
    nothing (the film's voice groups, frozen with it, are what the render follows)."""
    if not isinstance(record, Mapping) or record.get("class") == pause_rules.IN_TAKE:
        return 0.0
    seconds = record.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return 0.0
    return float(seconds)


def _room(record: Mapping[str, Any], out: float, beta: float) -> float:
    """What a row's pause after may give up for a short clip, in whole frames of the timeline:
    its planned seconds down to its frozen floor (a class never compressed was frozen with its
    floor at its seconds), at most the share the row's shot holds; none for a marked beat, a
    card or a join with no planned silence (as the render's room, `assembler._lay_out_voice`)."""
    cls = str(record.get("class") or "")
    if out <= 0 or cls in pause_rules.EDGES_ONLY or cls in (pause_rules.BEAT, pause_rules.CARD):
        return 0.0
    floor = record.get("floor")
    lowest = float(floor) if isinstance(floor, int | float) and not isinstance(floor, bool) else out
    fps = int(_legacy().fps)
    seconds = max(0.0, min(beta * out, out - lowest))
    return float(int(seconds * fps + 1e-6)) / fps


def _profile_of(views: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    from app.media.pause_plan import frozen_beat  # noqa: PLC0415

    first = views[0] if views else {}
    profile = first.get("pause_profile")
    if isinstance(profile, Mapping):
        return profile
    beat = frozen_beat(first.get("prompt_json")) or {}
    found = beat.get("pause_profile")
    return found if isinstance(found, Mapping) else {}


def is_frozen(views: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a storyboard is timed by its frozen pauses: every row carries the pause frozen
    when it was built (``pause_after``, as `assembler.scene_view` reads it). Whatever the pause
    rules say now: a film is timed by the numbers it was built with, and switching the rules
    off (or a rules file that no longer reads) never re-times it, nor re-buys its takes (the
    Owner's decision 8, 2026-10-16). A film built before them keeps the legacy timing."""
    return bool(views) and all(isinstance(view.get("pause_after"), Mapping) for view in views)


def film_knobs(views: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The channel's knobs a frozen film is laid out by: the ones it froze (``pause_profile``
    on its first row), else its channel's as the rules state them (in use or not); None when
    neither can be read."""
    profile = _profile_of(views)
    knobs = profile.get("knobs")
    beta = knobs.get("cut_in_pause") if isinstance(knobs, Mapping) else None
    if isinstance(beta, int | float) and not isinstance(beta, bool):
        slide = knobs.get("picture_slide_words") if isinstance(knobs, Mapping) else 0
        return {
            "cut_in_pause": max(0.0, min(1.0, float(beta))),
            "picture_slide_words": int(slide) if isinstance(slide, int) and slide > 0 else 0,
        }
    rules = pause_rules.readable_rules()
    if rules is None:
        return None
    serial = str(profile.get("channel") or "") == SERIAL
    channel = pause_rules.channel_pauses(SERIAL if serial else FACTUAL, rules)
    return {
        "cut_in_pause": channel.cut_in_pause,
        "picture_slide_words": channel.picture_slide_words,
    }


def _side_words(
    records: Sequence[Mapping[str, Any]], said: str, moved_out: int, moved_in: int
) -> list[int] | None:
    """Each part of a row's words as the freeze counted them (``words`` on each join record),
    an L-cut's words moved; None when they no longer add up to the row's words."""
    words = [
        int(record["words"])
        for record in records
        if isinstance(record.get("words"), int) and not isinstance(record.get("words"), bool)
    ]
    if not words or len(words) != len(records):
        return None
    if sum(words) != int(_legacy().spoken_words(said)):
        return None
    words[0] = max(0, words[0] - moved_out)
    words[-1] += moved_in
    return words


def frozen_rows(views: Sequence[Mapping[str, Any]]) -> list[RowPause] | None:
    """Each row's `RowPause` of a storyboard timed by its frozen pauses (`is_frozen`); None for
    a film built before them, which keeps the legacy timing. The voices and the knobs are the
    ones the film froze (``pause_profile`` on its first row), never measured again."""
    if not is_frozen(views):
        return None
    knobs = film_knobs(views)
    if knobs is None:
        return None
    beta = float(knobs["cut_in_pause"])
    slide = int(knobs["picture_slide_words"])
    profile = _profile_of(views)
    rules = pause_rules.active_rules() or pause_rules.readable_rules()
    frozen_voices: dict[str, pause_rules.VoiceProfile] = {}
    raw_voices = profile.get("voices")
    for name, entry in raw_voices.items() if isinstance(raw_voices, Mapping) else []:
        try:
            kept = pause_rules.VoiceProfile.from_dict(entry)
        except (KeyError, TypeError, ValueError):
            continue
        frozen_voices.setdefault(str(name), kept)
        frozen_voices.setdefault(kept.key, kept)
    narrator_key = profile.get("narrator")
    measured: Mapping[str, Any] | None = None

    def voice(key: Any) -> pause_rules.VoiceProfile | None:
        nonlocal measured
        if key is not None and str(key) in frozen_voices:
            return frozen_voices[str(key)]
        if narrator_key is not None and str(narrator_key) in frozen_voices:
            return frozen_voices[str(narrator_key)]
        if rules is None:
            return None
        if measured is None:
            try:
                measured = pause_rules.load_profiles(rules=rules)
            except OSError:
                measured = {}
        return pause_rules.voice_profile(str(key) if key else None, rules=rules, profiles=measured)

    from app.media.pause_plan import slid_to  # noqa: PLC0415 - pause_plan reads qc

    afters = [dict(view.get("pause_after") or {}) for view in views]
    texts = [" ".join(str(view.get("voiceover_segment") or "").split()) for view in views]
    holds = in_take_holds(afters, beta, slide)
    # The words an L-cut moves from the start of each row to the row before it (the two said
    # in one take): how many, counted as the voice says them.
    moved = [0] * len(views)
    if slide > 0:
        for index in range(1, len(views)):
            words = texts[index].split()
            if afters[index - 1].get("class") == pause_rules.IN_TAKE and words and texts[index - 1]:
                taken = words[: slid_to(0, len(words), slide)]
                moved[index] = int(_legacy().spoken_words(" ".join(taken)))
    plans: list[RowPause] = []
    previous_out = 0.0
    for index, view in enumerate(views):
        after = afters[index]
        inner_records = [r for r in view.get("inner_pauses") or [] if isinstance(r, Mapping)]
        said = texts[index]
        out = _row_join(after)
        records = [*inner_records, after]
        voices = [voice(r.get("voice_key")) for r in records] if said else []
        known = [v for v in voices if v is not None]
        slowest = max(known, key=lambda v: v.seconds_per_word_high) if known else None
        moved_in = moved[index + 1] if index + 1 < len(views) else 0
        speech: float | None = None
        if said and slowest is not None:
            parts = _side_words(records, said, moved[index], moved_in)
            if parts is not None and all(v is not None for v in voices):
                speech = round(
                    sum(
                        pause_rules.speech_seconds(count, part_voice, high=True)
                        for count, part_voice in zip(parts, voices, strict=True)
                        if part_voice is not None
                    ),
                    3,
                )
            else:
                said_words = max(0, int(_legacy().spoken_words(said)) - moved[index] + moved_in)
                speech = pause_rules.speech_seconds(said_words, slowest, high=True)
        plans.append(
            RowPause(
                voice=slowest,
                out=out,
                into=previous_out,
                inner=round(sum(_row_join(r) for r in inner_records), 4),
                beta=beta,
                joins=len(inner_records),
                after=_row_join(
                    after.get("fallback")
                    if after.get("class") == pause_rules.IN_TAKE
                    and isinstance(after.get("fallback"), Mapping)
                    else after
                ),
                room=_room(after, out, beta),
                speech=speech,
                held=holds[index] if said else 0.0,
                slide=slide,
            )
        )
        previous_out = out
    return plans


def wall_refusal(views: Sequence[Mapping[str, Any]]) -> str | None:
    """Why nothing may be bought for a film frozen over its wall, in the Owner's words: its
    storyboard was frozen (`pause_plan.freeze_rows`) with even every pause at its floor longer
    than its channel's wall (``pause_profile.wall.fits`` false), so quality control would
    refuse the film at the wall after every still, voice and clip were paid for. None for a
    film that fits, or one built before the pause rules (the review held it then)."""
    profile = _profile_of(views) if is_frozen(views) else {}
    wall = profile.get("wall") if isinstance(profile, Mapping) else None
    if not isinstance(wall, Mapping) or wall.get("fits") is not False:
        return None
    return over_the_wall_words(
        float(wall.get("estimate") or 0.0),
        float(wall.get("wall") or 0.0),
        float(wall.get("over_seconds") or 0.0),
        measured=False,
    )


def over_the_wall_words(seconds: float, wall: float, over: float, *, measured: bool) -> str:
    """A film longer than its wall even with every pause at its floor, in the Owner's words."""
    what = "măsurat cu vocea înregistrată" if measured else "estimat la construirea scenariului"
    return (
        f"Filmul, {what}, ar dura {seconds:.1f} s chiar cu fiecare pauză scurtată până la "
        f"podeaua ei: cu {over:.1f} s peste zidul de {wall:.0f} s al canalului. Nu se cumpără "
        "nimic pentru el (controlul de calitate l-ar refuza la zid): textul trebuie scurtat."
    )


# --------------------------------------------------------------------------- the legacy timing


def spoken_row_seconds(takes: Sequence[str]) -> float:
    """LEGACY (the pause rules off): a row with words as the legacy `assembler.scene_spans`
    times it: its takes (each its words plus EDGE_KEEP_SECONDS either side),
    SPEAKER_GAP_SECONDS between two of them, then LEGACY_SPOKEN_TAIL_SECONDS, rounded up to a
    whole frame. 0.0 for a row with no words."""
    legacy = _legacy()
    said = [legacy.spoken_words(text) for text in takes]
    said = [words for words in said if words > 0]
    if not said:
        return 0.0
    spoken = sum(words * legacy.per_word + 2 * legacy.edge for words in said)
    spoken += legacy.gap * (len(said) - 1)
    return float(legacy.whole_frames(spoken + legacy.tail, legacy.fps, up=True))


def silent_row_seconds(plan: float, kind: str | None) -> float:
    """A row with no words: a silent card its plan up to its kind's maximum, anything else its
    plan, on whole frames (`assembler.scene_spans`)."""
    return _silent_row_seconds(plan, kind)


def _legacy_factual(rows: Sequence[Mapping[str, Any]]) -> FilmLength:
    legacy = _legacy()
    seconds = 0.0
    speaking = 0
    spoken = 0.0
    for row in rows:
        words = legacy.spoken_words(row["narration"])
        if words > 0:
            seconds += spoken_row_seconds([row["narration"]])
            speaking += 1
            spoken += words * legacy.per_word
        else:
            seconds += silent_row_seconds(planned_seconds(row), row["scene_kind"])
    return FilmLength(round(seconds, 3), len(rows), speaking, round(spoken, 3))


def _legacy_clips(rows: Sequence[Mapping[str, Any]]) -> dict[int, float]:
    """LEGACY: the clip `assembler.clip_plan` bought before the pause rules: the words at
    SECONDS_PER_SPOKEN_WORD with the margin, LEGACY_SPOKEN_TAIL_SECONDS, the dissolve."""
    legacy = _legacy()
    joins = _dissolves(rows)
    sizes: dict[int, float] = {}
    for position, row in enumerate(rows):
        if scene_kind(row) in CARD_KINDS:
            continue
        said = round(
            legacy.spoken_words(str(row.get("narration") or row.get("voiceover_segment") or ""))
            * legacy.per_word,
            3,
        )
        dissolve = joins[position + 1] if position + 1 < len(joins) else 0.0
        voiced = (
            round(
                float(
                    legacy.whole_frames(
                        said * (1 + legacy.margin) + legacy.tail + dissolve, legacy.fps, up=True
                    )
                ),
                3,
            )
            if said > 0
            else 0.0
        )
        stated = row.get("duration_seconds")
        planned = (
            _motion_seconds(float(stated)) if isinstance(stated, int | float) and stated else 0.0
        )
        sizes[position + 1] = max(voiced, planned)
    return sizes


def legacy_shot_clip(lines: Sequence[Mapping[str, Any]]) -> float:
    """LEGACY: the clip one serial shot's lines needed before the pause rules: the words at
    SECONDS_PER_SPOKEN_WORD, SPEAKER_GAP_SECONDS between two speakers' takes, the margin and
    LEGACY_SPOKEN_TAIL_SECONDS."""
    legacy = _legacy()
    takes = legacy.speaker_segments([dict(line) for line in lines])
    said = sum(legacy.spoken_words(take["text"]) for take in takes) * legacy.per_word
    said += legacy.gap * max(0, len(takes) - 1)
    return round(said * (1 + legacy.margin) + legacy.tail, 2)


def _legacy_serial(
    lines_by_beat: Sequence[Sequence[Mapping[str, Any]]],
    parts: Sequence[str | None],
    *,
    settings: Any = None,
) -> FilmLength:
    legacy = _legacy()
    options = montage_options(settings)
    seconds = 0.0
    rows = speaking = 0
    spoken = 0.0
    for number, (lines, part) in enumerate(zip(lines_by_beat, parts, strict=True), start=1):
        for shot in serial_shots(
            [dict(line) for line in lines],
            number,
            part=part,
            first_beat=number == 1,
            settings=options,
        ):
            rows += 1
            takes = [str(take["text"]) for take in legacy.speaker_segments(shot["lines"])]
            row = spoken_row_seconds(takes)
            if row > 0:
                seconds += row
                speaking += 1
                spoken += sum(legacy.spoken_words(text) for text in takes) * legacy.per_word
            else:
                seconds += silent_row_seconds(PLANNED_MIN_SECONDS, None)
    return FilmLength(round(seconds, 3), rows, speaking, round(spoken, 3))


# ------------------------------------------------------------------------- the factual brief


def factual_cut_words(settings: Any = None) -> int | None:
    """The fewest words the montage cuts a LIVE scene into two shots or more
    (`montage.factual_shots`), under these settings; None when it never cuts (the montage off,
    or one shot a scene). The cut only grows with the words (`montage.shot_count`)."""
    options = montage_options(settings)
    if not options.montage_enabled or int(options.montage_max_shots_per_scene) <= 1:
        return None
    for words in range(1, CUT_SEARCH_WORDS + 1):
        if len(factual_shots(" ".join(["word"] * words), 1, live=True, settings=options)) > 1:
            return words
    return None


def longest_factual_films(scenes: int, low: int, high: int, *, settings: Any = None) -> list[float]:
    """LEGACY (the pause rules off): the longest film each total of words makes, over every
    draft a writer's band allows: at most ``scenes`` LIVE scenes of ``low`` to ``high`` words
    each. Item ``t`` is the longest film of any such draft with at most ``t`` words, for ``t``
    up to ``scenes * high``.

    The even shape was not the longest (the adversarial review of 2026-10-16): a scene of
    fifteen words was two shots and two breaths where fourteen was one, and every row was
    rounded up to its own frame, so the same words spread unevenly made a longer film. 399
    words in 28 scenes were 176.5 s spread evenly and 184.1 s as 23 scenes of fifteen. This
    is the worst shape exactly, in whole frames: a knapsack over the scenes. Under the pause
    rules a cut inside a writer's scene adds nothing and no row is rounded on its own, and the
    worst shape is a change of part at every join (`words_within` with ``worst``)."""
    scenes, low, high = int(scenes), max(1, int(low)), int(high)
    if scenes <= 0 or low > high:
        return [0.0]
    legacy = _legacy()
    options = montage_options(settings)
    plain = Timing(channel=FACTUAL)
    # One scene's film in whole frames: its rows are whole frames (`spoken_row_seconds`).
    frames = {
        words: round(
            factual_film_length(
                [{"narration": " ".join(["word"] * words)}], settings=options, when=plain
            ).seconds
            * legacy.fps
        )
        for words in range(low, high + 1)
    }
    top = scenes * high
    # best[t]: the longest film, in frames, of a draft of exactly t words; -1 when no draft
    # inside the band has t words.
    best = [0] + [-1] * top
    for _ in range(scenes):
        step = list(best)  # this scene left out: a draft may have fewer scenes than asked
        for total, film in enumerate(best):
            if film < 0:
                continue
            for words, more in frames.items():
                if total + words > top:
                    break
                step[total + words] = max(step[total + words], film + more)
        best = step
    longest: list[float] = []
    worst = 0
    for film in best:
        worst = max(worst, film)
        longest.append(worst / legacy.fps)
    return longest


#: Two purposes no body pair joins: a draft alternating them changes its part at every join.
_WORST_PURPOSES = ("HOOK", "PAYOFF")


def _worst_draft(words: int, scenes: int) -> list[dict[str, Any]]:
    """``scenes`` LIVE scenes carrying ``words`` evenly, a change of part at every join, each
    one long sentence (no short-sentence guard)."""
    base, extra = divmod(max(0, int(words)), max(1, int(scenes)))
    return [
        {
            "narration": " ".join(["word"] * (base + (1 if index < extra else 0))) + ".",
            "kind": "LIVE",
            "purpose": _WORST_PURPOSES[index % 2],
        }
        for index in range(int(scenes))
    ]


def even_draft(
    words: int, scenes: int, purposes: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """The brief's own shape: ``scenes`` filmed scenes carrying ``words`` evenly spread, each
    one sentence, with ``purposes`` (one a scene) where given."""
    base, extra = divmod(max(0, int(words)), max(1, int(scenes)))
    draft: list[dict[str, Any]] = []
    for index in range(int(scenes)):
        scene: dict[str, Any] = {
            "narration": " ".join(["word"] * (base + (1 if index < extra else 0))) + ".",
            "kind": "LIVE",
        }
        if purposes is not None and index < len(purposes):
            scene["purpose"] = purposes[index]
        draft.append(scene)
    return draft


def words_within(
    fits: Callable[[FilmLength], bool],
    scenes: int,
    *,
    settings: Any = None,
    when: Timing | None = None,
    purposes: Sequence[str] | None = None,
    worst: bool = False,
) -> int:
    """The most words ``scenes`` evenly written scenes may carry while the film the montage
    cuts from them still ``fits``; 0 when even one word a scene does not. ``worst``: a change
    of part at every join (`longest_factual_films`). The film only grows with its words (a
    scene's shots only multiply, its joins stay), so this is a bisection over the words."""
    if scenes <= 0:
        return 0
    when = when or timing(FACTUAL)
    options = montage_options(settings)

    def film(words: int) -> FilmLength:
        draft = _worst_draft(words, scenes) if worst else even_draft(words, scenes, purposes)
        return factual_film_length(draft, settings=options, when=when)

    low = scenes  # one word a scene: below this a scene would be silent, timed by its plan
    if not fits(film(low)):
        return 0
    rate = film_timing(when)["seconds_per_word"]
    high = low + int(SHORTS_WALL_SECONDS * 2 / max(rate, 1e-3)) + 1  # words alone run over
    while high - low > 1:
        middle = (low + high) // 2
        if fits(film(middle)):
            low = middle
        else:
            high = middle
    return low
