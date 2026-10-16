"""«Pauza vocii» on a film: its pauses frozen on its rows when its storyboard is built, and
its voice laid out on the timeline when it is rendered (the Owner, 2026-10-16).

`app.media.pauses` holds the rules as formulas; this module applies them to one film.

At the build (`freeze_rows`): every row's words become the sides `pauses.freeze` reads —
a factual row one side (the writer's scene it was cut from is its voice take), a serial row
one side per run of one speaker (`speaker_voices.line_runs`), the run going on into the
next shot when the speaker does. Each voice is the one the production policy will speak it
in (`production_policy.resolve_storyboard_plan`, `speaker_voices.plan_speakers`: database
reads only). The joins are classed, timed from each voice's measured pauses and fitted under
the channel's wall, then frozen on the row's beat tag (``prompt_json["beat"]``,
`montage.PAUSE_KEYS`): ``voice_group`` (the take its first words are said in),
``pause_after`` (the join after its words: class, seconds, floor, whether the writer marked
it, whose pause it is, the rules' version, and for a cut inside a take the join it would be
if the row were voiced on its own, ``fallback``), ``inner_pauses`` (the joins between its
own takes) and, on the film's first row, ``pause_profile`` (every number they came from).
A later profile or rule never changes a film already built.

At the render (`voice_layout`): one take per group, the montage's picture cuts placed on the
take's own word timing (`take_cuts`, ``alignment``, never ``normalized_alignment``), the
silence between two takes the frozen pause less the silence the trim kept
(`pauses.render_pad`), every cut on a frame of the cumulative timeline, never drifting.

Nothing here calls a model, a vendor or the network; nothing is bought.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.media import pauses
from app.media.montage import PAUSE_KEYS, beat_of

logger = logging.getLogger(__name__)

FACTUAL = "factual"
SERIAL = "serial"


# ------------------------------------------------------------------------------- the frozen row


def frozen_beat(prompt_json: Any) -> dict[str, Any] | None:
    """The pauses frozen on a row (`montage.PAUSE_KEYS` of its beat tag) when its join after
    is a valid frozen record (`pauses.frozen_pause`); None for a legacy row."""
    tag = beat_of(prompt_json)
    after = pauses.frozen_pause(tag)
    if after is None:
        return None
    inner = [
        dict(entry)
        for entry in tag.get("inner_pauses") or []
        if pauses.frozen_pause({"pause_after": entry}) is not None
    ]
    return {
        "voice_group": tag.get("voice_group"),
        "pause_after": after,
        "inner_pauses": inner,
        "pause_profile": tag.get("pause_profile")
        if isinstance(tag.get("pause_profile"), Mapping)
        else None,
    }


def film_is_frozen(prompt_jsons: Sequence[Any]) -> bool:
    """Whether every row of a film carries its frozen pause: only then is it timed by the
    rules; a film built before them (or with them off) keeps the legacy timing whole."""
    return bool(prompt_jsons) and all(frozen_beat(p) is not None for p in prompt_jsons)


# ------------------------------------------------------------------------------- the voices


def resolved_voice_key(session: Any, resolved: Any) -> str | None:
    """The profile key (`pauses.profile_key`) of a voice the production policy resolved:
    its connection's kind as the vendor, its model and its voice."""
    if not isinstance(resolved, Mapping) or not resolved.get("voice_id"):
        return None
    provider = None
    integration_id = resolved.get("integration_id")
    if integration_id:
        from app.integrations.models import Integration  # noqa: PLC0415

        row = session.get(Integration, integration_id)
        provider = row.kind if row is not None else None
    return pauses.profile_key(provider, resolved.get("model_id"), resolved.get("voice_id"))


def _board_plan(session: Any, board: Any, *, serial: bool) -> dict[str, Any] | None:
    """The voices the render will resolve for this board (database reads only), or None when
    they cannot be resolved here: the pauses then come from the voices' pools."""
    try:
        from app.media.production_policy import resolve_storyboard_plan  # noqa: PLC0415
        from app.media.speaker_voices import plan_speakers  # noqa: PLC0415

        plan = resolve_storyboard_plan(session, board)
        if serial:
            plan_speakers(session, board, plan)
        return plan
    except Exception as exc:  # noqa: BLE001 - a film is planned on its pools rather than refused
        logger.warning("pause_plan_voices_unresolved", extra={"error": type(exc).__name__})
        return None


def serial_voice_keys(
    session: Any, bibles: Mapping[str, Any]
) -> tuple[str | None, dict[str, str | None]]:
    """The voices an episode's render would speak in, before it has a storyboard (the serial
    review's estimate, «pauza vocii»): the narrator's (the serial channel's voice purpose) and
    each speaker's, by the name the lines use (``bibles``: name -> the character's bible), as
    `speaker_voices.speaker_voice` resolves it (a voice of their own, the cast's proposal, else
    the narrator's). Database reads only; (None, {}) when they cannot be resolved here, and the
    estimate times the voices by their pools."""
    try:
        from sqlalchemy import select  # noqa: PLC0415

        from app.media.production_policy import resolve_purpose  # noqa: PLC0415
        from app.media.speaker_voices import load_voice_cast, speaker_voice  # noqa: PLC0415
        from app.publishing.models import ChannelRecord  # noqa: PLC0415
        from app.story.services import SERIES_KEY  # noqa: PLC0415

        channel = session.scalars(
            select(ChannelRecord)
            .where(ChannelRecord.channel_type == "OFFICE_SERIAL")
            .order_by(ChannelRecord.created_at)
        ).first()
        narrator = resolve_purpose(session, "voice", channel=channel, series_key=SERIES_KEY)
        cast = load_voice_cast()
        keys = {
            str(name): resolved_voice_key(
                session,
                speaker_voice(
                    session, narrator, bible, cast, channel=channel, series_key=SERIES_KEY
                ),
            )
            for name, bible in bibles.items()
            if name
        }
        return resolved_voice_key(session, narrator), keys
    except Exception as exc:  # noqa: BLE001 - an estimate on the pools rather than none
        logger.warning("serial_voices_unresolved", extra={"error": type(exc).__name__})
        return None, {}


def board_wall(session: Any, board: Any, rules: pauses.PauseRules) -> float:
    """The board's wall: its channel's Shorts maximum (the type's default when the channel
    states none), never past the rules' cap (`pauses.wall_seconds`)."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.media.qc import SHORTS_MAX_BY_CHANNEL_TYPE  # noqa: PLC0415
    from app.publishing.models import ChannelRecord  # noqa: PLC0415
    from app.publishing.services import channel_type_for_storyboard  # noqa: PLC0415

    kind = channel_type_for_storyboard(board)
    channel = session.get(ChannelRecord, board.channel_id) if board.channel_id else None
    if channel is None:
        channel = session.scalars(
            select(ChannelRecord)
            .where(ChannelRecord.channel_type == kind)
            .order_by(ChannelRecord.created_at)
        ).first()
    if channel is not None:
        kind = channel.channel_type
    stated = getattr(channel, "shorts_max_seconds", None)
    return pauses.wall_seconds(
        float(stated) if stated else SHORTS_MAX_BY_CHANNEL_TYPE.get(kind), rules
    )


# --------------------------------------------------------------------------- the serial lines


def serial_lines(
    beats_lines: Sequence[Sequence[Mapping[str, Any]]],
    parts: Sequence[Any],
    rules: pauses.PauseRules | None,
) -> list[list[dict[str, Any]]]:
    """Each beat's lines as the pause plan reads them, in order:

    - a writer's «(beat)» (`lines.split_direction_places`, ``pause_at``) becomes a mark on its
      line: before it, after it, or, in the middle, the line cut in two lines of the same
      speaker with the mark between them; a line whose direction asks for a silence but says
      not where (an episode written before the place was kept) is marked after it;
    - at most the rules' marks a beat, the first ones, and never one before the punchline (the
      last line said in the room in the button);
    - each line named for the voice take it is said in (``voice_group``): a speaker's run is one
      take until another voice or a mark; it goes on into the next shot when its words do.

    With the rules not in use the lines are as stored (no mark, no group)."""
    out: list[list[dict[str, Any]]] = []
    marking = rules is not None and rules.switch("marked_beats")
    grouping = rules is not None and rules.switch("voice_groups")
    for number, lines in enumerate(beats_lines, start=1):
        split: list[dict[str, Any]] = []
        for raw in lines:
            line = {k: v for k, v in dict(raw).items() if k != "pause_at"}
            at = raw.get("pause_at") if marking else None
            words = str(line.get("text") or "").split()
            if isinstance(at, int) and not isinstance(at, bool) and 0 < at < len(words):
                split.append({**line, "text": " ".join(words[:at]), "mark_after": True})
                split.append({**line, "text": " ".join(words[at:])})
                continue
            if at == "start":
                line["mark_before"] = True
            elif at == "end" or (
                marking
                and at is None
                and "pause_at" not in raw
                and rules is not None
                and pauses.direction_marked(line.get("direction"), rules)
            ):
                line["mark_after"] = True
            split.append(line)
        part = str((parts[number - 1] if number - 1 < len(parts) else None) or "").strip().lower()
        if part == "button":
            room = [i for i, line in enumerate(split) if line.get("speaker")]
            if room:
                split[room[-1]]["punchline"] = True
        if marking and rules is not None:
            _keep_first_marks(split, rules)
        else:
            for line in split:
                line.pop("mark_before", None)
                line.pop("mark_after", None)
        if grouping:
            group = 1
            for index, line in enumerate(split):
                if index and (
                    (line.get("speaker") or None) != (split[index - 1].get("speaker") or None)
                    or split[index - 1].get("mark_after")
                    or line.get("mark_before")
                ):
                    group += 1
                line["voice_group"] = f"b{number}.{group}"
        out.append(split)
    return out


def _keep_first_marks(lines: list[dict[str, Any]], rules: pauses.PauseRules) -> None:
    """The beat's marks the rules keep: never one before the punchline, at most
    ``marks_per_section``, the first ones; the others are taken off their lines."""
    kept = 0
    for index, line in enumerate(lines):
        for key in ("mark_before", "mark_after"):
            if not line.get(key):
                continue
            following = (
                line
                if key == "mark_before"
                else (lines[index + 1] if index + 1 < len(lines) else None)
            )
            before_punchline = bool(
                following is not None
                and following.get("punchline")
                and rules.no_pause_before_punchline
            )
            if before_punchline or kept >= rules.marks_per_section:
                line.pop(key, None)
                continue
            kept += 1


# ------------------------------------------------------------------------------ the freeze


@dataclass
class RowSpec:
    """One storyboard row as the freeze reads it: the row (its ``prompt_json`` is written),
    its sides in the order said (a silent card is one side with no words) and, for the
    serial, the lines each side is said from."""

    row: Any
    sides: list[dict[str, Any]]
    lines: list[list[dict[str, Any]]] = field(default_factory=list)


def factual_side(
    text: str,
    *,
    scene: int,
    purpose: Any,
    kind: Any,
    planned_seconds: float,
    rules: pauses.PauseRules,
) -> dict[str, Any]:
    """A factual row's one side: its words, its writer's scene (whose one take it is said in,
    with the voice groups on), the scene's story purpose and kind; a silent card's length is
    its pause (at most what quality control allows its kind)."""
    from app.media.qc import MAX_SILENT_CARD_SECONDS  # noqa: PLC0415 - qc reads the models

    said = " ".join(str(text or "").split())
    card = str(kind or "").strip().upper()
    side: dict[str, Any] = {
        "text": said,
        "scene": int(scene),
        "purpose": str(purpose or "").strip().upper() or None,
        "kind": card or None,
        "pool": pauses.NARRATOR_POOL,
        "speaker": None,
        "take": f"s{int(scene)}" if said and rules.switch("voice_groups") else None,
    }
    if not said and card in MAX_SILENT_CARD_SECONDS:
        side["card_seconds"] = min(float(planned_seconds or 0.0), MAX_SILENT_CARD_SECONDS[card])
    return side


def serial_sides(lines: Sequence[Mapping[str, Any]], *, beat: int) -> list[list[dict[str, Any]]]:
    """A serial row's sides: one per run of one speaker inside one voice take
    (`speaker_voices.line_runs`), each with the lines it is said from."""
    from app.media.speaker_voices import line_runs  # noqa: PLC0415

    runs = line_runs([dict(line) for line in lines])
    return [list(run) for run in runs]


def _serial_side(run: Sequence[Mapping[str, Any]], *, beat: int) -> dict[str, Any]:
    first, last = run[0], run[-1]
    speaker = str(first.get("speaker") or "") or None
    directions: list[str] = []
    for line in run:
        note = " ".join(str(line.get("direction") or "").split())
        if note and note not in directions:
            directions.append(note)
    return {
        "text": " ".join(" ".join(str(line.get("text") or "").split()) for line in run),
        "scene": int(beat),
        "speaker": speaker,
        "pool": pauses.CHARACTER_POOL if speaker else pauses.NARRATOR_POOL,
        "take": first.get("voice_group"),
        "direction": "; ".join(directions),
        "mark_before": bool(first.get("mark_before")),
        "mark_after": bool(last.get("mark_after")),
        "punchline": bool(first.get("punchline")),
        "kind": None,
    }


def serial_row_sides(
    lines: Sequence[Mapping[str, Any]], *, beat: int
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """(the sides, the lines of each) of a serial row."""
    runs = serial_sides(lines, beat=beat)
    return [_serial_side(run, beat=beat) for run in runs], runs


def freeze_rows(
    session: Any,
    board: Any,
    specs: Sequence[RowSpec],
    *,
    serial: bool,
    rules: pauses.PauseRules | None = None,
    profiles: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Every row's pauses planned, fitted under the board's wall and frozen on its beat tag
    (see the module). Writes ``prompt_json`` of every row in ``specs``; the caller's
    transaction commits it. Returns what was frozen (the snapshot and the wall), or None when
    the rules are not in use (the film keeps the legacy timing)."""
    rules = rules or pauses.active_rules()
    if rules is None or not specs:
        return None
    knobs = pauses.channel_pauses(SERIAL if serial else FACTUAL, rules)
    session.flush()
    plan = _board_plan(session, board, serial=serial)
    by_index = {
        int(entry.get("scene_index") or 0): entry for entry in (plan or {}).get("scenes") or []
    }
    narrator = resolved_voice_key(session, ((plan or {}).get("purposes") or {}).get("voice"))
    sides: list[dict[str, Any]] = []
    owners: list[int] = []
    for position, spec in enumerate(specs):
        entry = by_index.get(int(spec.row.scene_index), {})
        scene_voice = resolved_voice_key(session, entry.get("voice"))
        speakers = entry.get("speakers") or []
        for part, side in enumerate(spec.sides):
            voice = scene_voice
            if serial and part < len(speakers) and isinstance(speakers[part], Mapping):
                voice = resolved_voice_key(session, speakers[part].get("voice")) or scene_voice
            sides.append({**side, "voice": voice or (None if side.get("speaker") else narrator)})
            owners.append(position)
    narrator = narrator or next((s["voice"] for s in sides if s.get("voice")), None)
    if profiles is None:
        try:
            profiles = pauses.load_profiles(rules=rules)
        except OSError as exc:
            logger.warning("voice_profiles_unread", extra={"error": type(exc).__name__})
            profiles = None
    wall = board_wall(session, board, rules)
    frozen = pauses.freeze(
        sides,
        serial=serial,
        rules=rules,
        knobs=knobs,
        profiles=profiles,
        narrator_voice=narrator,
        wall=wall,
    )
    alone = pauses.freeze(
        [{**side, "take": None} for side in sides],
        serial=serial,
        rules=rules,
        knobs=knobs,
        profiles=profiles,
        narrator_voice=narrator,
        wall=wall,
    )
    for record, single in zip(frozen.pauses, alone.pauses, strict=True):
        if record["class"] == pauses.IN_TAKE:
            # The join this cut would be were the row voiced on its own (a take with no word
            # timing, or the voice groups switched off at the render).
            record["fallback"] = {
                key: single[key] for key in ("class", "seconds", "floor") if key in single
            }
    profile = {
        **frozen.snapshot,
        "channel": SERIAL if serial else FACTUAL,
        "wall": frozen.wall,
        "estimate": {
            "seconds": frozen.estimate.seconds,
            "speech_seconds": frozen.estimate.speech_seconds,
            "pause_seconds": frozen.estimate.pause_seconds,
            "card_seconds": frozen.estimate.card_seconds,
        },
    }
    for position, spec in enumerate(specs):
        records = [r for r, owner in zip(frozen.pauses, owners, strict=True) if owner == position]
        own_sides = [s for s, owner in zip(sides, owners, strict=True) if owner == position]
        tag = beat_of(spec.row.prompt_json)
        for key in PAUSE_KEYS:
            tag.pop(key, None)
        tag["voice_group"] = own_sides[0].get("take") if own_sides else None
        tag["pause_after"] = records[-1]
        tag["inner_pauses"] = records[:-1]
        if position == 0:
            tag["pause_profile"] = profile
        spec.row.prompt_json = {**dict(spec.row.prompt_json or {}), "beat": tag}
    return profile


# ------------------------------------------------------------------------- cuts inside a take


@dataclass(frozen=True)
class Word:
    """One word of a take as timed: its whole span and, where the vendor timed letters, the
    span from its first letter or digit to its last (else the same span)."""

    text: str
    start: float
    end: float
    first: float
    last: float


def take_words(raw_response: Any, word_timings: Any) -> list[Word] | None:
    """A take's words with their times: the vendor's character ``alignment`` first (never the
    ``normalized_alignment``, which times the words as the vendor spelt them out), else the
    adapter's word timing; None when the take carries neither."""
    alignment = pauses.alignment_of(raw_response)
    if alignment is not None:
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]
        words: list[Word] = []
        group: list[int] = []
        for index, char in enumerate([*chars, " "]):
            if not str(char).strip():
                if group:
                    letters = [i for i in group if str(chars[i]).isalnum()] or group
                    words.append(
                        Word(
                            "".join(str(chars[i]) for i in group),
                            float(starts[group[0]]),
                            float(ends[group[-1]]),
                            float(starts[letters[0]]),
                            float(ends[letters[-1]]),
                        )
                    )
                    group = []
                continue
            group.append(index)
        return words or None
    if isinstance(word_timings, list) and word_timings:
        timed: list[Word] = []
        for item in word_timings:
            if not isinstance(item, Mapping):
                return None
            start, end = item.get("start"), item.get("end")
            if isinstance(start, bool) or not isinstance(start, int | float):
                return None
            if isinstance(end, bool) or not isinstance(end, int | float):
                return None
            timed.append(
                Word(
                    str(item.get("word") or ""), float(start), float(end), float(start), float(end)
                )
            )
        return timed
    return None


def _key(word: str) -> str:
    return "".join(char for char in str(word).casefold() if char.isalnum())


@dataclass(frozen=True)
class TakeCuts:
    """Where each unit (a row's words, or a speaker's part of them) of one take begins inside
    it, and the words each one is said in, timed from its own beginning. ``timed`` is False
    when the take's timing could not be matched to its words and the cuts were placed by the
    units' share of its characters instead (nothing is bought again for it)."""

    offsets: tuple[float, ...]
    words: tuple[tuple[dict[str, Any], ...] | None, ...]
    gaps: tuple[float | None, ...]
    timed: bool


def take_cuts(
    units: Sequence[str],
    duration: float,
    words: Sequence[Word] | None,
    *,
    cut_in_pause: float,
    picture_slide_words: int = 0,
) -> TakeCuts:
    """The picture cuts inside one take said from ``units`` (each unit's text, in order),
    placed on the take's own word timing: between the last word of a unit and the first of the
    next, at ``cut_in_pause`` of the voice's own pause there (1.0: on the next unit's first
    letter, the outgoing shot holding the whole pause), moved ``picture_slide_words`` words
    into the next unit for an L-cut. A vendor tag before the words (a model that reads an
    acting note as «[surprised] ») is skipped. Without a timing that matches the words the
    cuts fall at each unit's share of the take's characters."""
    texts = [" ".join(str(unit or "").split()) for unit in units]
    counts = [len(text.split()) for text in texts]
    timed = list(words or [])
    expected = sum(counts)
    if timed and len(timed) > expected:
        extra = len(timed) - expected
        flat = [word for text in texts for word in text.split()]
        if [_key(w.text) for w in timed[extra:]] == [_key(w) for w in flat]:
            timed = timed[extra:]
    if timed and len(timed) == expected and all(counts):
        offsets = [0.0]
        gaps: list[float | None] = []
        position = counts[0]
        for count in counts[1:]:
            before, after = timed[position - 1], timed[position]
            gap = max(0.0, after.first - before.last)
            cut = before.last + max(0.0, min(1.0, cut_in_pause)) * gap
            if picture_slide_words > 0:
                slid = min(position + picture_slide_words, position + count - 1)
                cut = max(cut, timed[slid].first)
            offsets.append(round(min(max(cut, offsets[-1]), duration), 4))
            gaps.append(round(gap, 4))
            position += count
        gaps.append(None)
        sliced: list[tuple[dict[str, Any], ...] | None] = []
        position = 0
        for index, count in enumerate(counts):
            begin = offsets[index]
            sliced.append(
                tuple(
                    {
                        "word": word.text,
                        "start": round(max(0.0, word.start - begin), 4),
                        "end": round(max(0.0, word.end - begin), 4),
                    }
                    for word in timed[position : position + count]
                )
            )
            position += count
        return TakeCuts(tuple(offsets), tuple(sliced), tuple(gaps), True)
    characters = [len(text) for text in texts]
    total = sum(characters) or 1
    offsets = []
    running = 0
    for count in characters:
        offsets.append(round(duration * running / total, 4))
        running += count
    return TakeCuts(
        tuple(offsets),
        tuple(None for _ in texts),
        tuple(None for _ in texts),
        False,
    )


# ---------------------------------------------------------------------------- the voice layout


@dataclass(frozen=True)
class Unit:
    """One unit of a row's words in the voice track: the take it is said in (its index in
    the track), where it begins inside the take and how long it lasts there."""

    take: int
    offset: float
    seconds: float


@dataclass(frozen=True)
class TakeJoin:
    """One take of the voice track: how long it lasts once trimmed, and the silence planned
    after it (`pauses.render_pad`: the frozen pause less the silence the trim kept)."""

    seconds: float
    pad: float


@dataclass
class Layout:
    """The film's voice laid out under its pictures: each row's span on whole frames of the
    cumulative timeline (``spans``) and its start (``starts``), the silence written before
    the voice's first take (``lead``) and after each take (``pads``), and where each take
    begins on the track (``take_starts``)."""

    spans: list[float]
    starts: list[float]
    lead: float
    pads: list[float]
    take_starts: list[float]
    cut_at: list[float]


def voice_layout(
    rows: Sequence[Sequence[Unit] | float],
    takes: Sequence[TakeJoin],
    *,
    fps: int,
    cut_in_pause: float,
) -> Layout:
    """The rows (each its units in order, or a silent card's length in seconds) laid on the
    timeline with the voice track under them.

    The voice: each take where the one before it ended plus its planned pad, a silent card's
    length added to the silence it stands in. The picture: a row begins at its first unit's
    beginning, or, where that unit opens a take after a pause, ``cut_in_pause`` of that pause
    after the previous take ended (1.0: with the take); a silent card where the voice before
    it ended. Every row's boundary is rounded to the nearest frame of the timeline, so the cuts
    never drift; a take that opens a row is placed on its row's rounded boundary, any other
    where the one before it ended plus its pad, and the pads are what lies between, never
    negative (a take is late by less than a frame where its pad was shorter than the
    rounding)."""
    beta = max(0.0, min(1.0, float(cut_in_pause)))
    starts_exact: list[float] = []
    take_exact: dict[int, float] = {}
    opener: dict[int, int] = {}
    clock = 0.0  # where the voice stands: the end of the last take and its pad
    pause_from: float | None = None  # where the silence before ``clock`` began (a take's end)
    for index, row in enumerate(rows):
        if not isinstance(row, Sequence):
            starts_exact.append(clock)
            clock += float(row)
            pause_from = None  # the card is the pause: the next row starts after it
            continue
        if not row:
            starts_exact.append(clock)
            continue
        for position, unit in enumerate(row):
            if unit.take not in take_exact:
                take_exact[unit.take] = clock
                if position == 0:
                    opener[unit.take] = index
                    starts_exact.append(
                        clock if pause_from is None else pause_from + beta * (clock - pause_from)
                    )
            elif position == 0:
                starts_exact.append(take_exact[unit.take] + unit.offset)
            take = takes[unit.take]
            if abs(unit.offset + unit.seconds - take.seconds) <= 1e-6:
                pause_from = take_exact[unit.take] + take.seconds
                clock = pause_from + take.pad
            else:
                clock = take_exact[unit.take] + unit.offset + unit.seconds
                pause_from = None
    snapped = [round(start * fps) / fps for start in starts_exact]
    end_snapped = round(clock * fps) / fps
    bounds = [*snapped, end_snapped]
    spans = [max(0.0, round(b - a, 6)) for a, b in zip(bounds, bounds[1:], strict=False)]
    placed: list[float] = []
    pads: list[float] = []
    for k in range(len(takes)):
        if k in opener:
            row = opener[k]
            target = snapped[row] + (take_exact.get(k, 0.0) - starts_exact[row])
        elif k:
            target = placed[-1] + takes[k - 1].seconds + takes[k - 1].pad
        else:
            target = take_exact.get(k, 0.0)
        start = max(target, placed[-1] + takes[k - 1].seconds) if k else max(0.0, target)
        if k:
            pads.append(round(max(0.0, start - placed[-1] - takes[k - 1].seconds), 4))
        placed.append(start)
    if takes:
        pads.append(round(max(0.0, end_snapped - placed[-1] - takes[-1].seconds), 4))
    return Layout(
        spans=spans,
        starts=snapped,
        lead=round(placed[0], 4) if placed else 0.0,
        pads=pads,
        take_starts=[round(p, 4) for p in placed],
        cut_at=[round(s, 4) for s in snapped],
    )


def shrink_frames(have: float, need: float, room: float, fps: int, fits: Any) -> int:
    """How many whole frames a span of ``need`` seconds must give up, at most ``room``
    seconds of pause, for a clip of ``have`` seconds to fill it (``fits(have, span)``); 0
    when it fits already, -1 when even the whole room is not enough."""
    if fits(have, need):
        return 0
    most = int(math.floor(max(0.0, room) * fps + 1e-6))
    for frames in range(1, most + 1):
        if fits(have, need - frames / fps):
            return frames
    return -1
