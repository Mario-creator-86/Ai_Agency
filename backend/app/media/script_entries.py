"""Which entry of a script's ``scenes_json`` a storyboard row reads (2026-10-16).

The two storyboards keep their script at two different grains:

* the factual board's script is the writer's own, one entry a writer's scene, fact-checked
  and never rewritten. The montage cuts a scene into several rows, each tagged with the
  writer's scene it came from (`montage.beat_tag`: the scene's place in ``scenes_json``,
  as `services._montage_rows` counts it); a scene of one shot carries no tag at all;
* the serial's script is written by `serial_storyboard.storyboard_from_episode` with one
  entry a shot, because the speakers, the voices and the lines are the shot's own. Its tag
  names the beat the shot was cut from, which is not a place in that list.

Reading a serial shot's entry at its beat's number gave every shot of beat 2 onwards the
scene line, the lines and the part of a shot of an earlier beat: the shot prompts were
composed from another beat's action, and the Director's second look judged the still against
another shot's words (review of 2026-10-16). Reading an untagged factual row at its own row
number gave it a later writer's scene once a scene before it had been cut. Every reader maps
a row to its entry here, once.

Imports nothing of the studio's but the montage's tag reader, so the prompt agent and the
second look both read it without an import cycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from app.media.montage import beat_of


def _positive(value: Any) -> int | None:
    """``value`` as a positive whole number, else None (a bool is not a number here)."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def writer_scene_numbers(rows: Iterable[tuple[int, Any]]) -> dict[int, int]:
    """The writer's scene each row of a factual board shows, by row number.

    ``rows`` are ``(scene_index, prompt_json)``. A tagged row names its writer's scene; an
    untagged row is a writer's scene of one shot, the next after the row before it (a board
    the montage never cut is read row for row, exactly as before).
    """
    numbers: dict[int, int] = {}
    previous_row, previous_writer = 0, 0
    for index, prompt_json in sorted(rows, key=lambda row: int(row[0])):
        row = int(index)
        tagged = _positive(beat_of(prompt_json).get("scene_number"))
        writer = tagged if tagged is not None else previous_writer + (row - previous_row)
        numbers[row] = writer
        previous_row, previous_writer = row, writer
    return numbers


def serial_entry(scenes_json: Sequence[Any], scene_index: int) -> dict[str, Any]:
    """A serial shot's own entry: the one at its row number, when that entry says it is
    this shot's (its own ``scene_index``, or none stored); else the entry that says so;
    else nothing — never another shot's words."""
    entries = list(scenes_json or [])
    at = entries[scene_index - 1] if 1 <= scene_index <= len(entries) else None
    if isinstance(at, dict) and _positive(at.get("scene_index")) in (None, scene_index):
        return dict(at)
    for entry in entries:
        if isinstance(entry, dict) and _positive(entry.get("scene_index")) == scene_index:
            return dict(entry)
    return {}


def row_entries(
    scenes_json: Sequence[Any], rows: Iterable[tuple[int, Any]], *, serial: bool
) -> dict[int, dict[str, Any]]:
    """Each storyboard row's own script entry, by row number (``{}`` for a row with none).

    ``rows`` are every row of the board as ``(scene_index, prompt_json)``: a factual row's
    writer's scene is read from the rows before it when it carries no tag. ``serial`` is the
    board's kind (`editorial.is_serial_film`): only the kind says which grain the script
    keeps, a factual script may carry ``scene_index`` keys of its own (the demo fixture).
    """
    entries = list(scenes_json or [])
    listed = [(int(index), prompt_json) for index, prompt_json in rows]
    if serial:
        return {index: serial_entry(entries, index) for index, _ in listed}
    return {
        index: dict(entries[number - 1])
        if 1 <= number <= len(entries) and isinstance(entries[number - 1], dict)
        else {}
        for index, number in writer_scene_numbers(listed).items()
    }
