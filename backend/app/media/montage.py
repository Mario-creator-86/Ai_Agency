"""Montage: a scene cut into shots (the Owner, 2026-10-16).

The Owner watched a Seedance-made fan film (150 shots in 14 minutes) and asked for the same
complexity of montage in the shorts and the serial: «o mică poveste, mișcare, efecte
cinematice». He decided: the shots are made with the studio's own RunPod models; dialogue is
heard in off with reaction shots instead of lip-synced speech; the serial keeps its 2D look.

A filmed scene (a narration line of a factual short, a beat of the serial) is cut here into
shots of about `Settings.montage_shot_seconds` each, at most `montage_max_shots_per_scene`:
each shot becomes an ordinary storyboard scene with its own still, its own clip and its own
camera move, so the sheet, the stills stage, the assembler, quality control and the renders
cap read nothing new (a shot is a row; the cap of three renders a layer counts per row). The
shots of one scene are tied by a tag kept on the scene's ``prompt_json["beat"]``:
``{"scene_number": k, "shot": i, "of": n, "size": ...}`` — ``scene_number`` is the writer's
scene the shot belongs to (the fact-checked script is never rewritten), so the prompt agent
and the second look read the writer's own words through it.

Nothing here is bought: cutting the words is free, and the builders call it once.
"""

from __future__ import annotations

import re
from typing import Any

#: Words a second, as the storyboard builders size a scene from its words.
WORDS_PER_SECOND = 2.5
#: A shot with fewer words than this is not a shot of its own: the cut is heard before it is
#: seen. Six words are about 2.4 s.
MIN_SHOT_WORDS = 6
#: The factual sizes, in the order a beat's shots take them: the place, the subject, the
#: detail that matters. A beat starts where the beat before stopped, so the film does not
#: open every moment wide.
FACTUAL_SIZES: tuple[str, ...] = ("wide", "medium", "detail")
#: The storyboard's `shot_type` for each factual size (`prompt_agent.shot_frame` reads it
#: as the fallback size when the plan's camera text names none).
FACTUAL_SHOT_TYPES = {"wide": "WIDE", "medium": "MEDIUM", "detail": "DETAIL"}

#: Serial: a speaker's run longer than this is cut in two, the second half on the listener
#: (a reaction shot, the voice heard from beside the frame — the Owner's «narat + cadre de
#: reacție», 2026-10-16). 0.40 s a spoken word is `assembler.SECONDS_PER_SPOKEN_WORD`.
SECONDS_PER_SPOKEN_WORD = 0.40
REACTION_SPLIT_SECONDS = 5.5
#: A speaker's run shorter than this joins the shot beside it as a two-shot: a cut for four
#: words is a flicker.
MIN_TAKE_SECONDS = 1.6
#: The longest a serial shot may be (the motion model's clip, before the local slow-down).
MAX_SHOT_SECONDS = 9.0

_CLAUSE_END = re.compile(r"[.!?;:,—–]$")
_SENTENCE_END = re.compile(r"[.!?]$")


def montage_settings(settings: Any = None) -> dict[str, Any]:
    """The montage's three settings, from ``settings`` or the studio's own; the defaults when
    neither can be read."""
    if settings is None:
        try:
            from app.config import Settings  # noqa: PLC0415

            settings = Settings()  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001 - a studio without usable settings keeps the defaults
            settings = None
    return {
        "enabled": bool(getattr(settings, "montage_enabled", True)),
        "shot_seconds": float(getattr(settings, "montage_shot_seconds", 4.0) or 4.0),
        "max_shots": int(getattr(settings, "montage_max_shots_per_scene", 3) or 3),
    }


def beat_tag(
    scene_number: int, shot: int, of: int, size: str | None, **extra: Any
) -> dict[str, Any]:
    """The tag a shot's storyboard scene carries on ``prompt_json["beat"]``."""
    tag: dict[str, Any] = {"scene_number": int(scene_number), "shot": int(shot), "of": int(of)}
    if size:
        tag["size"] = str(size)
    tag.update({key: value for key, value in extra.items() if value is not None})
    return tag


def beat_of(prompt_json: Any) -> dict[str, Any]:
    """The beat tag of a scene's ``prompt_json``, or an empty dict."""
    tag = prompt_json.get("beat") if isinstance(prompt_json, dict) else None
    return dict(tag) if isinstance(tag, dict) else {}


def shot_count(words: int, *, shot_seconds: float, max_shots: int) -> int:
    """How many shots ``words`` are cut into: about ``shot_seconds`` each, at most
    ``max_shots``, never a shot under MIN_SHOT_WORDS."""
    if words <= 0 or max_shots <= 1:
        return 1
    per_shot = max(1.0, shot_seconds * WORDS_PER_SECOND)
    count = max(1, min(int(max_shots), round(words / per_shot)))
    while count > 1 and words / count < MIN_SHOT_WORDS:
        count -= 1
    return count


def split_words(text: str, count: int) -> list[str]:
    """``text`` cut into ``count`` fragments of about equal length, each cut on a clause end
    (a comma, a full stop, a dash) when one lies near the ideal point, else between words.
    Fewer fragments when the words cannot give each its MIN_SHOT_WORDS."""
    tokens = str(text or "").split()
    if count <= 1 or len(tokens) < 2 * MIN_SHOT_WORDS:
        return [" ".join(tokens)] if tokens else []
    count = min(count, len(tokens) // MIN_SHOT_WORDS)
    cuts: list[int] = []
    start = 0
    for piece in range(1, count):
        ideal = round(len(tokens) * piece / count)
        low = max(start + MIN_SHOT_WORDS, ideal - max(2, (ideal - start) // 3))
        high = min(
            len(tokens) - MIN_SHOT_WORDS * (count - piece), ideal + max(2, (ideal - start) // 3)
        )
        if low > high:
            cut = min(max(ideal, start + MIN_SHOT_WORDS), len(tokens) - MIN_SHOT_WORDS)
        else:
            # A sentence end nearest the ideal, else a clause end, else the ideal word.
            best = None
            for pattern in (_SENTENCE_END, _CLAUSE_END):
                near = [i for i in range(low, high + 1) if pattern.search(tokens[i - 1])]
                if near:
                    best = min(near, key=lambda i: abs(i - ideal))
                    break
            cut = best if best is not None else ideal
        cut = max(start + 1, min(cut, len(tokens) - 1))
        if cut <= start:
            break
        cuts.append(cut)
        start = cut
    bounds = [0, *cuts, len(tokens)]
    fragments = [" ".join(tokens[a:b]) for a, b in zip(bounds[:-1], bounds[1:], strict=True)]
    return [fragment for fragment in fragments if fragment]


def factual_sizes(count: int, scene_number: int) -> list[str]:
    """The sizes of a factual beat's shots: FACTUAL_SIZES in turn, the first beat opening
    wide, each next beat starting where the beat before stopped."""
    offset = 0 if scene_number <= 1 else (scene_number - 1) % len(FACTUAL_SIZES)
    return [FACTUAL_SIZES[(offset + i) % len(FACTUAL_SIZES)] for i in range(count)]


def factual_shots(
    narration: str, scene_number: int, *, live: bool, settings: Any = None
) -> list[dict[str, Any]]:
    """A factual scene's shots: ``[{"narration", "size", "shot", "of"}]``. A composed scene
    (a card, black) or a montage switched off is one shot with no size of its own."""
    options = montage_settings(settings)
    words = len(str(narration or "").split())
    count = (
        shot_count(words, shot_seconds=options["shot_seconds"], max_shots=options["max_shots"])
        if live and options["enabled"]
        else 1
    )
    fragments = split_words(narration, count) if count > 1 else [str(narration or "").strip()]
    if len(fragments) <= 1:
        return [{"narration": fragments[0] if fragments else "", "size": None, "shot": 1, "of": 1}]
    sizes = factual_sizes(len(fragments), scene_number)
    return [
        {"narration": fragment, "size": size, "shot": i, "of": len(fragments)}
        for i, (fragment, size) in enumerate(zip(fragments, sizes, strict=True), start=1)
    ]


# ------------------------------------------------------------------------------ the serial


def _take_seconds(text: str) -> float:
    return len(str(text or "").split()) * SECONDS_PER_SPOKEN_WORD


def _runs(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A beat's lines as one run per consecutive speaker: ``{"speaker", "lines"}``."""
    runs: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict) or not str(line.get("text") or "").strip():
            continue
        speaker = str(line.get("speaker") or "") or None
        if runs and runs[-1]["speaker"] == speaker:
            runs[-1]["lines"].append(dict(line))
        else:
            runs.append({"speaker": speaker, "lines": [dict(line)]})
    return runs


def _run_words(run: dict[str, Any]) -> int:
    return sum(len(str(line.get("text") or "").split()) for line in run["lines"])


def _split_run(run: dict[str, Any], pieces: int) -> list[list[dict[str, Any]]]:
    """A speaker's run cut into ``pieces`` groups of lines of about equal words: whole lines
    first; one long line is cut on its clauses (`split_words`), its acting note kept on each
    part."""
    lines = run["lines"]
    if pieces <= 1:
        return [lines]
    if len(lines) >= pieces:
        groups: list[list[dict[str, Any]]] = [[] for _ in range(pieces)]
        total = _run_words(run)
        target = total / pieces
        position, counted = 0, 0
        for line in lines:
            if position < pieces - 1 and counted >= target * (position + 1) and groups[position]:
                position += 1
            groups[position].append(line)
            counted += len(str(line.get("text") or "").split())
        return [group for group in groups if group]
    text = " ".join(str(line.get("text") or "").strip() for line in lines)
    direction = "; ".join(
        dict.fromkeys(
            str(line.get("direction") or "").strip() for line in lines if line.get("direction")
        )
    )
    parts = split_words(text, pieces)
    return [[{"speaker": run["speaker"], "text": part, "direction": direction}] for part in parts]


def serial_shots(
    lines: list[dict[str, Any]],
    scene_number: int,
    *,
    part: str | None,
    first_beat: bool,
    settings: Any = None,
) -> list[dict[str, Any]]:
    """A serial beat's shots: ``[{"lines", "size", "on", "shot", "of"}]``.

    One shot per speaker's run (the camera cuts with the dialogue); a run shorter than
    MIN_TAKE_SECONDS joins its neighbour as a two-shot; a run longer than
    REACTION_SPLIT_SECONDS is cut in two, the second half a reaction shot on the listener
    (``on``), the words heard from beside the frame; a run longer than MAX_SHOT_SECONDS is
    cut into as many pieces as it needs. The first shot of the first beat establishes the
    room; the button's last shot is a close-up. ``on`` names whose face the shot is on.
    """
    options = montage_settings(settings)
    runs = _runs(lines)
    if not runs:
        return [{"lines": list(lines), "size": None, "on": None, "shot": 1, "of": 1}]
    if not options["enabled"] or options["max_shots"] <= 1:
        return [{"lines": list(lines), "size": None, "on": None, "shot": 1, "of": 1}]
    distinct = list(dict.fromkeys(run["speaker"] for run in runs if run["speaker"]))

    # 1. The runs as shots: a few words answer inside the shot before (a two-shot on both).
    groups: list[dict[str, Any]] = []
    for run in runs:
        seconds = _take_seconds(" ".join(str(line.get("text") or "") for line in run["lines"]))
        # The narrator's run (speaker None) is a shot of its own, whole: the voice in off over
        # the room, never a reaction and never shared with a line in the room.
        if (
            groups
            and seconds < MIN_TAKE_SECONDS
            and run["speaker"] is not None
            and groups[-1]["speaker"] is not None
        ):
            groups[-1]["lines"] = [*groups[-1]["lines"], *run["lines"]]
            if run["speaker"] != groups[-1]["speaker"]:
                groups[-1]["shared"] = True
            continue
        groups.append({"speaker": run["speaker"], "lines": list(run["lines"]), "shared": False})

    # 2. How many pieces each shot is cut into: what its words ask (about shot_seconds each
    # past REACTION_SPLIT_SECONDS), within the beat's budget of max_shots — a run longer than
    # the clip keeps the pieces the clip's length forces, whatever the budget.
    limit = max(1, int(options["max_shots"]))
    wanted: list[int] = []
    forced: list[int] = []
    for group in groups:
        seconds = _take_seconds(" ".join(str(line.get("text") or "") for line in group["lines"]))
        words = sum(len(str(line.get("text") or "").split()) for line in group["lines"])
        need = int(-(-seconds // MAX_SHOT_SECONDS)) if seconds > MAX_SHOT_SECONDS else 1
        want = (
            int(-(-seconds // options["shot_seconds"])) if seconds > REACTION_SPLIT_SECONDS else 1
        )
        most = max(1, words // MIN_SHOT_WORDS)
        forced.append(max(1, min(need, most)))
        wanted.append(max(forced[-1], min(want, most)))
    while sum(wanted) > limit:
        loose = [
            i for i, (want, need) in enumerate(zip(wanted, forced, strict=True)) if want > need
        ]
        if not loose:
            break
        wanted[max(loose, key=lambda i: wanted[i])] -= 1

    # 3. The shots: a cut run alternates the speaker and the listener (the words go on,
    # heard from beside the frame); a shared shot is a two-shot.
    shots: list[dict[str, Any]] = []
    for group, pieces in zip(groups, wanted, strict=True):
        others = [name for name in distinct if name != group["speaker"]]
        listener = others[0] if others and group["speaker"] is not None else None
        run = {"speaker": group["speaker"], "lines": group["lines"]}
        for piece_index, piece in enumerate(
            _split_run(run, pieces) if pieces > 1 else [group["lines"]]
        ):
            reaction = piece_index % 2 == 1 and listener is not None
            if group["speaker"] is None:
                size = "establishing"  # the voice in off over the room and its people
            else:
                size = "reaction" if reaction else ("two_shot" if group["shared"] else "single")
            shots.append(
                {
                    "lines": piece,
                    "size": size,
                    "on": listener if reaction else group["speaker"],
                    "shot": 0,
                    "of": 0,
                }
            )
    if first_beat and shots:
        shots[0]["size"] = "establishing"
    kind = str(part or "").strip().lower()
    if kind == "button":
        # The last shot in the room is the close-up; a narrator's closing shot stays wide.
        spoken = [shot for shot in shots if shot["on"] is not None]
        if spoken and spoken[-1]["size"] in ("single", "two_shot"):
            spoken[-1]["size"] = "close"
    for i, shot in enumerate(shots, start=1):
        shot["shot"], shot["of"] = i, len(shots)
    return shots
