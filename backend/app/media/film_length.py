"""How long the assembled film will be, from its words, before anything is bought.

2026-10-16 (the adversarial review of the montage day): the factual review measured a script
at 2.6 words a second plus 0.35 s per writer's scene, and the serial review at 2.5 words a
second with 5 s left for every breath. The montage cuts a writer's scene or a beat into shots
(`montage.factual_shots`, `montage.serial_shots`), and the assembler gives every shot with
words a breath of its own (`assembler.scene_spans`: SPOKEN_TAIL_SECONDS, rounded up to a
frame). A 442-word script the review passed became a 194 s film, which quality control refused
at YouTube's 180 s wall after the stills, clips and voice of its 56 shots were bought, and no
repair can make words shorter.

This is the one estimate the factual brief and review and the serial review read. It cuts the
words as the storyboard builders will, under the same montage settings, and times every row
as the assembler does:

- a row with words lasts its takes, each its words at SECONDS_PER_SPOKEN_WORD (`spoken_words`:
  a number is said in words) plus the EDGE_KEEP_SECONDS `_trimmed_take` keeps either side;
  SPEAKER_GAP_SECONDS between two speakers' takes in one row; then SPOKEN_TAIL_SECONDS, the
  whole rounded up to a frame of the 24 fps timeline (`scene_spans`);
- a silent card (BLACK, TITLE_CARD, DATA_CARD) lasts its plan, at most what quality control
  allows its kind (`qc.MAX_SILENT_CARD_SECONDS`); any other silent row its plan; on whole
  frames;
- the film is its rows end to end: a dissolve overlaps two pictures, never the sound.

The factual brief's numbers must hold for every draft that keeps them, not only for its words
spread evenly: its band of words a scene stops under the montage's cut (`factual_cut_words`),
and its ceiling holds for the longest film the band allows (`longest_factual_films`).

What stays an estimate, and which way it errs:

- a take's length. SECONDS_PER_SPOKEN_WORD is the mean of the vendor's own takes (babcf272),
  measured before their silent edges were trimmed, while the assembler times the trimmed
  takes: the estimate errs long by what the vendor leaves around each take's words (up to
  0.09 s before and 0.96 s after them on babcf272). Scene by scene the takes ran 0.80-1.26
  times the rate; over a film's 30-60 takes those spreads largely cancel;
- a factual row's plan (the writer's stated length for an uncut scene, else its words at 2.5 a
  second within 3-9 s, as `media.services` writes it), which only a silent row is timed by;
- a factual scene's kind, read from the script. The storyboard's content gate may still turn a
  LIVE scene into a card, which is one row where the montage would have cut up to three: the
  film only gets shorter.

The reviews hold the estimate WALL_MARGIN_SECONDS under the wall (`review_ceiling_seconds`):
the pace of single takes spreads about 0.13 around the rate (0.80-1.26), which over the 35-45
takes of a film at the ceiling is about 3 s either way (one standard deviation), while the
untrimmed edges the rate still counts make the estimate long by more than that. Quality
control's own measurement of the delivered file stays the last word (`qc.evaluate_media_qc`).

Nothing here is bought, read from the database or sent anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from app.media.montage import factual_shots, montage_settings, serial_shots

#: YouTube's Shorts wall: the longest a vertical film may be and still be a Short. The same
#: number as `qc.SHORTS_MAX_LIMIT_SECONDS` and `editorial.MAX_SHORT_SECONDS` (a test holds the
#: three equal; this module cannot import quality control, which imports the editorial rules).
SHORTS_WALL_SECONDS = 180.0
#: How far under the wall the reviews hold their estimate (see the module's note): about one
#: standard deviation of the takes' pace over a film at the ceiling, on an estimate that
#: already errs long.
WALL_MARGIN_SECONDS = 3.0
#: The kinds the assembler times as cards when they are silent; anything else is LIVE.
CARD_KINDS = ("DATA_CARD", "TITLE_CARD", "BLACK")
#: How the factual storyboard plans a row whose writer stated no length: its words at this
#: rate, within MIN/MAX (`media.services.generate_storyboard_from_script`).
PLANNED_WORDS_PER_SECOND = 2.5
PLANNED_MIN_SECONDS = 3.0
PLANNED_MAX_SECONDS = 9.0
#: The most words a scene's cut point is looked for in: a narration is at most 800
#: characters (`agent_pipeline._Scene`), well under this many words.
CUT_SEARCH_WORDS = 200


@dataclass(frozen=True)
class FilmLength:
    """A film as it will be cut and timed: its length, its rows, and how much of it is words."""

    seconds: float
    rows: int
    speaking_rows: int
    #: The takes' estimated words alone, without their edges, gaps or breaths.
    spoken_seconds: float


@lru_cache(maxsize=1)
def _timing() -> SimpleNamespace:
    """The assembler's own timing numbers, read once (the assembler is heavy and imports
    quality control, which imports the editorial rules that import this module)."""
    from app.media.assembler import (  # noqa: PLC0415
        SECONDS_PER_SPOKEN_WORD,
        SPOKEN_TAIL_SECONDS,
        TIMELINE_FPS,
        spoken_words,
        whole_frames,
    )
    from app.media.qc import MAX_SILENT_CARD_SECONDS  # noqa: PLC0415
    from app.media.speaker_voices import SPEAKER_GAP_SECONDS, speaker_segments  # noqa: PLC0415
    from app.media.toolchain import EDGE_KEEP_SECONDS  # noqa: PLC0415

    return SimpleNamespace(
        per_word=SECONDS_PER_SPOKEN_WORD,
        tail=SPOKEN_TAIL_SECONDS,
        fps=TIMELINE_FPS,
        edge=EDGE_KEEP_SECONDS,
        gap=SPEAKER_GAP_SECONDS,
        card_max=dict(MAX_SILENT_CARD_SECONDS),
        spoken_words=spoken_words,
        whole_frames=whole_frames,
        speaker_segments=speaker_segments,
    )


def film_timing() -> dict[str, float]:
    """The rate a word is said at and the breath after each shot, as the estimate times them,
    for a brief to state the numbers it is measured by."""
    timing = _timing()
    return {"seconds_per_word": float(timing.per_word), "breath_seconds": float(timing.tail)}


def review_ceiling_seconds(wall: float = SHORTS_WALL_SECONDS) -> float:
    """The longest estimate a review accepts: the wall (never past YouTube's) less the margin."""
    return round(min(float(wall), SHORTS_WALL_SECONDS) - WALL_MARGIN_SECONDS, 1)


def montage_options(settings: Any = None) -> SimpleNamespace:
    """The montage's settings, read once, in the shape `montage.montage_settings` reads: an
    estimate cuts dozens of scenes, and the studio's settings are not read again for each."""
    options = montage_settings(settings)
    return SimpleNamespace(
        montage_enabled=options["enabled"],
        montage_shot_seconds=options["shot_seconds"],
        montage_max_shots_per_scene=options["max_shots"],
    )


def scene_kind(scene: dict[str, Any]) -> str:
    """A factual scene's kind as the script stores it (``scene_kind``; the writer's ``kind``);
    an unknown or missing kind is LIVE, as the assembler reads it."""
    kind = str(scene.get("scene_kind") or scene.get("kind") or "LIVE").strip().upper()
    return kind if kind in CARD_KINDS else "LIVE"


def _narration(scene: dict[str, Any]) -> str:
    return str(
        scene.get("voiceover_segment") or scene.get("voiceover") or scene.get("narration") or ""
    ).strip()


def factual_rows(scenes: Sequence[dict[str, Any]], *, settings: Any = None) -> list[dict[str, Any]]:
    """A factual script's storyboard rows, as `media.services` cuts and plans them: a LIVE
    scene in the montage's shots (`montage.factual_shots`), a card one row. Each row:
    ``{scene_number, shot, of, narration, scene_kind, transition_in, duration_seconds}`` —
    the writer's transition on a scene's first shot only, and ``duration_seconds`` only where
    the writer stated one for an uncut scene (`assembler.script_clip_seconds` reads a stated
    plan as a floor; the storyboard's own default plan is `planned_seconds`)."""
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
                "transition_in": (
                    str(scene.get("transition_in") or "CUT") if int(shot["shot"]) <= 1 else "CUT"
                ),
            }
            stated = scene.get("duration_seconds")
            if int(shot["of"]) <= 1 and isinstance(stated, int | float) and stated > 0:
                row["duration_seconds"] = float(stated)
            rows.append(row)
    return rows


def planned_seconds(row: dict[str, Any]) -> float:
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


def spoken_row_seconds(takes: Sequence[str]) -> float:
    """A row with words, as `assembler.scene_spans` times it: its takes (each trimmed to its
    words plus EDGE_KEEP_SECONDS either side), SPEAKER_GAP_SECONDS between two of them, then
    SPOKEN_TAIL_SECONDS, rounded up to a whole frame. 0.0 for a row with no words."""
    timing = _timing()
    said = [timing.spoken_words(text) for text in takes]
    said = [words for words in said if words > 0]
    if not said:
        return 0.0
    spoken = sum(words * timing.per_word + 2 * timing.edge for words in said)
    spoken += timing.gap * (len(said) - 1)
    return float(timing.whole_frames(spoken + timing.tail, timing.fps, up=True))


def silent_row_seconds(plan: float, kind: str | None) -> float:
    """A row with no words: a silent card its plan up to its kind's maximum, anything else its
    plan, on whole frames (`assembler.scene_spans`)."""
    timing = _timing()
    if kind in timing.card_max:
        return float(timing.whole_frames(min(float(plan), timing.card_max[kind]), timing.fps))
    return float(timing.whole_frames(float(plan), timing.fps))


def factual_cut_words(settings: Any = None) -> int | None:
    """The fewest words the montage cuts a LIVE scene into two shots or more
    (`montage.factual_shots`), under these settings; None when it never cuts (the montage off,
    or one shot a scene). Under it a writer's scene is one shot and one breath, from it on two
    or three, each with its breath. The cut only grows with the words (`montage.shot_count`),
    so a brief whose band of words a scene stops under this number keeps every scene one
    shot."""
    options = montage_options(settings)
    if not options.montage_enabled or int(options.montage_max_shots_per_scene) <= 1:
        return None
    for words in range(1, CUT_SEARCH_WORDS + 1):
        if len(factual_shots(" ".join(["word"] * words), 1, live=True, settings=options)) > 1:
            return words
    return None


def longest_factual_films(scenes: int, low: int, high: int, *, settings: Any = None) -> list[float]:
    """The longest film each total of words makes, over every draft a writer's band allows:
    at most ``scenes`` LIVE scenes of ``low`` to ``high`` words each. Item ``t`` is the
    longest film of any such draft with at most ``t`` words, for ``t`` up to
    ``scenes * high``.

    The even shape is not the longest (the adversarial review of 2026-10-16): a scene of
    fifteen words is two shots and two breaths where fourteen is one, and every row is
    rounded up to its own frame, so the same words spread unevenly make a longer film. 399
    words in 28 scenes were 176.5 s spread evenly and 184.1 s as 23 scenes of fifteen. This
    is the worst shape exactly, in whole frames: a knapsack over the scenes (a few dozen
    scenes, a band of a few words, a few hundred totals)."""
    scenes, low, high = int(scenes), max(1, int(low)), int(high)
    if scenes <= 0 or low > high:
        return [0.0]
    timing = _timing()
    options = montage_options(settings)
    # One scene's film in whole frames: its rows are whole frames (`spoken_row_seconds`).
    frames = {
        words: round(
            factual_film_length(
                [{"narration": " ".join(["word"] * words)}], settings=options
            ).seconds
            * timing.fps
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
        longest.append(worst / timing.fps)
    return longest


def factual_film_length(scenes: Sequence[dict[str, Any]], *, settings: Any = None) -> FilmLength:
    """How long a factual script's film will be, cut and timed as the studio will."""
    timing = _timing()
    seconds = 0.0
    speaking = 0
    spoken = 0.0
    rows = factual_rows(scenes, settings=settings)
    for row in rows:
        words = timing.spoken_words(row["narration"])
        if words > 0:
            seconds += spoken_row_seconds([row["narration"]])
            speaking += 1
            spoken += words * timing.per_word
        else:
            seconds += silent_row_seconds(planned_seconds(row), row["scene_kind"])
    return FilmLength(round(seconds, 3), len(rows), speaking, round(spoken, 3))


def serial_film_length(
    lines_by_beat: Sequence[list[dict[str, Any]]],
    parts: Sequence[str | None],
    *,
    settings: Any = None,
) -> FilmLength:
    """How long an episode's film will be: each beat cut into the montage's shots
    (`montage.serial_shots`, as `storyboard_from_episode` cuts it), each shot its speakers'
    takes (`speaker_segments`, as the render voices them) timed as `spoken_row_seconds`. A shot
    with no words keeps the storyboard's 3 s plan."""
    timing = _timing()
    options = montage_options(settings)
    seconds = 0.0
    rows = speaking = 0
    spoken = 0.0
    for number, (lines, part) in enumerate(zip(lines_by_beat, parts, strict=True), start=1):
        for shot in serial_shots(
            list(lines), number, part=part, first_beat=number == 1, settings=options
        ):
            rows += 1
            takes = [str(take["text"]) for take in timing.speaker_segments(shot["lines"])]
            row = spoken_row_seconds(takes)
            if row > 0:
                seconds += row
                speaking += 1
                spoken += sum(timing.spoken_words(text) for text in takes) * timing.per_word
            else:
                seconds += silent_row_seconds(PLANNED_MIN_SECONDS, None)
    return FilmLength(round(seconds, 3), rows, speaking, round(spoken, 3))
