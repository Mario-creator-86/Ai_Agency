"""Montage: a scene cut into shots (the Owner, 2026-10-16).

The Owner watched a Seedance-made fan film (150 shots in 14 minutes) and asked for the same
complexity of montage in the shorts and the serial: «o mică poveste, mișcare, efecte
cinematice». He decided: the shots are made with the studio's own RunPod models; dialogue is
heard in off with reaction shots instead of lip-synced speech; the serial keeps its 2D look.

A filmed scene (a narration line of a factual short, a beat of the serial) is cut here into
shots of about `Settings.montage_shot_seconds` each, at most `montage_max_shots_per_scene`:
each shot becomes an ordinary storyboard scene with its own still, its own clip and its own
camera move, so the sheet, the stills stage, the assembler, quality control and the renders
cap read nothing new (a shot is a row; the renders cap, `renders_cap`, counts per row). The
shots of one scene are tied by a tag kept on the scene's ``prompt_json["beat"]``:
``{"scene_number": k, "shot": i, "of": n, "size": ...}`` — ``scene_number`` is the writer's
scene the shot belongs to (the fact-checked script is never rewritten), so the prompt agent
and the second look read the writer's own words through it.

Nothing here is bought: cutting the words is free, and the builders call it once.
"""

from __future__ import annotations

import re
from typing import Any

from app.media.pauses import DASH, SENTENCE, punctuation_class
from app.story.lines import ends_sentence, stops_inside

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
#: A speaker's run shorter than this joins the shot beside it, as a two-shot or, beside only
#: the narrator, his shot held on the speaker: a cut for four words is a flicker, and a still
#: and a clip bought for under a second of screen. Only a beat whose one line is this short
#: is a shot this short.
MIN_TAKE_SECONDS = 1.6
#: The longest a serial shot may be (the motion model's clip, before the local slow-down).
MAX_SHOT_SECONDS = 9.0

_CLAUSE_MARK = re.compile(r"[;:,—–][\"'”’»)\]]*$")


def _ends_clause(word: str) -> bool:
    """A sentence end (`lines.ends_sentence`: never the stop of "Dr." or "U.S.") or a comma,
    a semicolon, a colon, a dash."""
    return ends_sentence(word) or bool(_CLAUSE_MARK.search(word))


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


#: What the pause plan freezes on a row's beat tag (`pause_plan.freeze_rows`, the Owner's
#: «pauza vocii», 2026-10-16): the voice take the row's words are said in, the silence after
#: them, the silences between its own takes (a serial row of two speakers), and, on the film's
#: first row, every number they were made from. None of it is the montage's cut.
PAUSE_KEYS = ("voice_group", "pause_after", "inner_pauses", "pause_profile")


def shot_tag(prompt_json: Any) -> dict[str, Any]:
    """The montage's own tag of a row (its writer's scene or beat, which shot, its size, whose
    face): the beat tag without the frozen pauses, or an empty dict for a row the montage
    never cut. What a model is shown of the cut: the pauses are numbers for the render, never
    words for a prompt, and a scene of one shot reads as it always did."""
    return {key: value for key, value in beat_of(prompt_json).items() if key not in PAUSE_KEYS}


def keep_frozen(new: Any, old: Any) -> Any:
    """``new`` (a scene's package about to replace ``old``) with ``old``'s frozen pauses kept
    on its beat tag: a shot plan, a rewrite or a restored package changes the words of a
    picture, never the film's timing. ``new`` as it is when ``old`` froze none."""
    frozen = {key: value for key, value in beat_of(old).items() if key in PAUSE_KEYS}
    if not frozen or not isinstance(new, dict):
        return new
    tag = beat_of(new)
    return {**new, "beat": {**tag, **frozen}}


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


def _ends_sentence(word: str) -> bool:
    """A sentence end (`lines.ends_sentence`) or the writer's ellipsis: the voice's full stop,
    where a cut lands first (`pauses.punctuation_class`)."""
    return punctuation_class(word) == SENTENCE


def split_words(text: str, count: int) -> list[str]:
    """``text`` cut into ``count`` fragments of about equal length, each cut on a clause end
    (a comma, a full stop, a dash) when one lies near the ideal point, else between words.
    Fewer fragments when the words cannot give each its MIN_SHOT_WORDS.

    A title's or an abbreviation's stop is no clause end, and no cut falls right after one
    (2026-10-16: "signed by Dr." / "Ellen Harper" were two shots and two voice takes, the
    voice pausing between the title and the name)."""
    return [fragment for fragment, _cut in split_words_classed(text, count)]


def split_words_classed(text: str, count: int) -> list[tuple[str, str | None]]:
    """`split_words`, each fragment with the class of the cut after it
    (`pauses.punctuation_class` of its last word: SENTENCE at a full stop or the writer's
    ellipsis, DASH, CLAUSE, else WORD; None after the last fragment). The cut is a picture cut
    inside one voice take: the class says which of the voice's own pauses the viewer hears
    there, and which join it would be if the fragments were ever voiced apart (2026-10-16,
    the Owner's «pauza vocii»). An ellipsis is a cut of sentence priority."""
    tokens = str(text or "").split()
    fragments = _split_tokens(tokens, count)
    return [
        (
            fragment,
            None if position == len(fragments) - 1 else punctuation_class(fragment.split()[-1]),
        )
        for position, fragment in enumerate(fragments)
    ]


def _split_tokens(tokens: list[str], count: int) -> list[str]:
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
            # A sentence end nearest the ideal, else a clause end, else the word nearest
            # the ideal that does not follow a title ("Dr." | "Ellen").
            best = None
            for ends in (_ends_sentence, _ends_clause):
                near = [i for i in range(low, high + 1) if ends(tokens[i - 1])]
                if near:
                    best = min(near, key=lambda i: abs(i - ideal))
                    break
            if best is None:
                free = [i for i in range(low, high + 1) if not stops_inside(tokens[i - 1])]
                best = min(free, key=lambda i: abs(i - ideal)) if free else None
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
    """A factual scene's shots: ``[{"narration", "size", "shot", "of", "cut_after"}]``. A
    composed scene (a card, black) or a montage switched off is one shot with no size of its
    own. ``cut_after`` is the class of the picture cut after the shot inside the writer's
    scene (`split_words_classed`), None after its last shot."""
    options = montage_settings(settings)
    words = len(str(narration or "").split())
    count = (
        shot_count(words, shot_seconds=options["shot_seconds"], max_shots=options["max_shots"])
        if live and options["enabled"]
        else 1
    )
    cut = (
        split_words_classed(narration, count)
        if count > 1
        else [(str(narration or "").strip(), None)]
    )
    if len(cut) <= 1:
        return [
            {
                "narration": cut[0][0] if cut else "",
                "size": None,
                "shot": 1,
                "of": 1,
                "cut_after": None,
            }
        ]
    sizes = factual_sizes(len(cut), scene_number)
    return [
        {"narration": fragment, "size": size, "shot": i, "of": len(cut), "cut_after": after}
        for i, ((fragment, after), size) in enumerate(zip(cut, sizes, strict=True), start=1)
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


def _words(text: Any) -> int:
    return len(str(text or "").split())


def _clips(seconds: float) -> int:
    """How many clips ``seconds`` of speech need, each at most MAX_SHOT_SECONDS."""
    return max(1, int(-(-seconds // MAX_SHOT_SECONDS)))


def _line_parts(line: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """One line cut on its clauses into ``count`` parts (`split_words`), each part still
    that line's: its speaker, its acting note, every other key it carries."""
    if count <= 1:
        return [line]
    parts = split_words(str(line.get("text") or ""), count)
    if len(parts) <= 1:
        return [line]
    # A writer's mark stays where it stood (`pause_plan.serial_lines`): one before the line
    # on its first part, one after it on its last; the punchline starts with the first.
    cut = []
    for position, part in enumerate(parts):
        piece = {**line, "text": part}
        if position:
            piece.pop("mark_before", None)
            piece.pop("punchline", None)
        if position < len(parts) - 1:
            piece.pop("mark_after", None)
        cut.append(piece)
    return cut


def _partition(
    sizes: list[int], joints: list[bool], count: int
) -> tuple[tuple[int, int, int, float], list[int]]:
    """``sizes`` (words, in order) cut into ``count`` consecutive groups: first as few
    groups over MAX_SHOT_SECONDS as the cut allows, then as few under MIN_TAKE_SECONDS,
    then as few cuts inside a line (``joints[i]``: size i continues the line of size i-1),
    then as even as can be. Returns (that cost, the index where each group starts)."""
    mean = sum(sizes) / count
    prefix = [0]
    for size in sizes:
        prefix.append(prefix[-1] + size)

    def cost(start: int, end: int) -> tuple[int, int, int, float]:
        words = prefix[end] - prefix[start]
        seconds = words * SECONDS_PER_SPOKEN_WORD
        return (
            int(seconds > MAX_SHOT_SECONDS),
            int(seconds < MIN_TAKE_SECONDS),
            int(start > 0 and joints[start]),
            (words - mean) ** 2,
        )

    # best[j][i]: the cheapest cut of the first i sizes into j groups, and where its last
    # group starts. The costs add up and compare in their order (a lexicographic sum), so
    # the cheapest cut of the whole holds the cheapest cut of every prefix.
    infinite = (len(sizes) + 1, len(sizes) + 1, len(sizes) + 1, float("inf"))
    best = [[(infinite, 0)] * (len(sizes) + 1) for _ in range(count + 1)]
    best[0][0] = ((0, 0, 0, 0.0), 0)
    for j in range(1, count + 1):
        for i in range(j, len(sizes) + 1):
            for start in range(j - 1, i):
                before = best[j - 1][start][0]
                if before == infinite:
                    continue
                here = cost(start, i)
                total = (
                    before[0] + here[0],
                    before[1] + here[1],
                    before[2] + here[2],
                    before[3] + here[3],
                )
                if total < best[j][i][0]:
                    best[j][i] = (total, start)
    starts: list[int] = []
    end = len(sizes)
    for j in range(count, 0, -1):
        end = best[j][end][1]
        starts.append(end)
    return best[count][len(sizes)][0], starts[::-1]


def _split_run(run: dict[str, Any], pieces: int) -> list[list[dict[str, Any]]]:
    """A run's lines cut into about ``pieces`` shots of about equal words, never one over
    MAX_SHOT_SECONDS (the clip) and, where the cut allows, none under MIN_TAKE_SECONDS.

    Every line keeps its speaker and its acting note. A run of several voices (a two-shot)
    is cut between its lines; a line itself is cut on its clauses (`split_words`) when it is
    one voice's run that needs the pieces, or when whole lines cannot make shots within the
    clip. A run the clip cannot hold in ``pieces`` is first cut finer, then given one piece
    more (the beat's budget of shots is the Owner's, a piece more is one more still and
    clip bought); a piece that would be a flicker goes back into its neighbour.

    2026-10-16 review: a two-shot cut into more pieces than it had lines was joined into one
    text and given to the first speaker (Kael said Sarah's «Fine, go.» in his voice), and
    whole lines were never cut below the clip (a narrator opening of three lines gave a 14 s
    shot, which the episode's «filmable» rule refused).
    """
    lines = [line for line in run["lines"] if _words(line.get("text"))]
    if not lines:
        return [list(run["lines"])]
    one_voice = len({line.get("speaker") or None for line in lines}) == 1
    # Each line in as many parts as the clip forces on it alone.
    counts = [_clips(_words(line.get("text")) * SECONDS_PER_SPOKEN_WORD) for line in lines]
    # The fewest pieces the clip allows the whole run.
    fewest = _clips(sum(_words(line.get("text")) for line in lines) * SECONDS_PER_SPOKEN_WORD)

    def units_of(counts: list[int]) -> list[tuple[int, dict[str, Any]]]:
        return [
            (index, part)
            for index, (line, count) in enumerate(zip(lines, counts, strict=True))
            for part in _line_parts(line, count)
        ]

    def cut_further(units: list[tuple[int, dict[str, Any]]]) -> bool:
        # The line whose parts are longest takes one part more, when its words allow it.
        have = [sum(1 for j, _part in units if j == i) for i in range(len(lines))]
        order = sorted(range(len(lines)), key=lambda i: -_words(lines[i].get("text")) / have[i])
        for i in order:
            for more in range(counts[i] + 1, _words(lines[i].get("text")) // MIN_SHOT_WORDS + 1):
                if len(_line_parts(lines[i], more)) > have[i]:
                    counts[i] = more
                    return True
        return False

    units = units_of(counts)
    # One voice: as many parts as the shots asked for, its lines cut on their clauses.
    while one_voice and len(units) < pieces and cut_further(units):
        units = units_of(counts)
    added = 0
    while True:
        sizes = [_words(part["text"]) for _index, part in units]
        joints = [i > 0 and units[i - 1][0] == units[i][0] for i in range(len(units))]
        count = max(1, min(max(pieces, fewest) + added, len(units)))
        (over, short, _inside, _even), starts = _partition(sizes, joints, count)
        if over:
            # A piece over the clip: the lines cut finer, then one piece more.
            if cut_further(units):
                units = units_of(counts)
            elif count < len(units):
                added += 1
            else:
                break
            continue
        # A flicker: one piece fewer when the clip allows it...
        clip_bound = False
        while short and count > 1:
            fewer, fewer_starts = _partition(sizes, joints, count - 1)
            clip_bound = fewer[0] > 0
            if clip_bound or fewer[1] >= short:
                break
            count -= 1
            short, starts = fewer[1], fewer_starts
        # ...else a line cut finer, so the few words join a piece of their neighbour's: for
        # several voices only when whole lines cannot make shots within the clip.
        if short and count > 1 and (one_voice or clip_bound) and cut_further(units):
            units = units_of(counts)
            continue
        break

    shots: list[list[dict[str, Any]]] = []
    for start, end in zip(starts, [*starts[1:], len(units)], strict=True):
        piece: list[dict[str, Any]] = []
        previous = None
        for index, part in units[start:end]:
            if index == previous:
                # Two parts of one line in one piece are that line again, whole (with the
                # mark after its last part, `_line_parts`).
                piece[-1] = {
                    **piece[-1],
                    "text": f"{piece[-1]['text']} {part['text']}",
                    **({"mark_after": True} if part.get("mark_after") else {}),
                }
            else:
                piece.append(part)
            previous = index
        shots.append(piece)
    return shots


def _held(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Two neighbouring groups of a beat as one shot, their lines in the order said, on the
    later group's speaker, or the earlier one's when the later is the narrator: a short line
    that shares the narrator's run keeps the camera on its speaker while his words go on."""
    speaker = second["speaker"] if second["speaker"] is not None else first["speaker"]
    return {"speaker": speaker, "lines": [*first["lines"], *second["lines"]]}


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
    MIN_TAKE_SECONDS joins the shot before it as a two-shot, or the speaking shot after it
    when nothing speaks before it (the beat's first words, the first after the narrator),
    or else the narrator's shot beside it, held on its speaker (the button's «Told you.»
    before the closing sentence) — a beat's only line stays its own shot; a run longer than
    REACTION_SPLIT_SECONDS is cut in two, the second half a reaction shot on the listener
    (``on``), the words heard from beside the frame; a run longer than MAX_SHOT_SECONDS is
    cut into as many pieces as it needs. The first shot of the first beat establishes the
    room; the button's last shot is a close-up. ``on`` names whose face the shot is on.
    """
    options = montage_settings(settings)
    runs = _runs(lines)
    if not runs:
        return [
            {
                "lines": list(lines),
                "size": None,
                "on": None,
                "shot": 1,
                "of": 1,
                "cut_after": BEAT_END,
            }
        ]
    if not options["enabled"] or options["max_shots"] <= 1:
        return [
            {
                "lines": list(lines),
                "size": None,
                "on": None,
                "shot": 1,
                "of": 1,
                "cut_after": BEAT_END,
            }
        ]
    distinct = list(dict.fromkeys(run["speaker"] for run in runs if run["speaker"]))

    # 1. The runs as shots: a few words answer inside the shot before (a two-shot on both).
    groups: list[dict[str, Any]] = []
    for run in runs:
        seconds = _take_seconds(" ".join(str(line.get("text") or "") for line in run["lines"]))
        # The narrator's run (speaker None) is a shot of its own, whole: the voice in off over
        # the room, never a reaction, and shared only with a line in the room too short for a
        # shot of its own that has no speaking shot to join (below).
        if (
            groups
            and seconds < MIN_TAKE_SECONDS
            and run["speaker"] is not None
            and groups[-1]["speaker"] is not None
        ):
            groups[-1]["lines"] = [*groups[-1]["lines"], *run["lines"]]
            continue
        groups.append({"speaker": run["speaker"], "lines": list(run["lines"])})
    # A short run with no speaking shot before it (the beat opens on «Wait.», or it answers
    # the narrator) joins the speaking shot after it. With only the narrator after it (the
    # v8 button: one line that lands the laugh, then the narrator's closing sentence), or
    # nothing after it at all, it shares the narrator's shot beside it, the camera held on
    # its speaker while the narrator's words go on (`_held`). On its own it was a shot of
    # under a second, a still and a clip bought for a flicker, in every episode whose button
    # is a few words (2026-10-16 review). A beat whose only line is short stays one shot.
    # Step 1 already joined every short run that had a speaking shot before it, so a short
    # speaking group here has none.
    joined: list[dict[str, Any]] = []
    waiting: dict[str, Any] | None = None
    for group in groups:
        if waiting is not None:
            group = _held(waiting, group)
            waiting = None
        seconds = _take_seconds(" ".join(str(line.get("text") or "") for line in group["lines"]))
        if group["speaker"] is not None and seconds < MIN_TAKE_SECONDS:
            waiting = group
            continue
        joined.append(group)
    while waiting is not None and joined:
        # Nothing after it: the shot before it takes it (the narrator's, or a speaking shot
        # that took the narrator's words), and again while the two are still a flicker.
        waiting = _held(joined.pop(), waiting)
        seconds = _take_seconds(" ".join(str(line.get("text") or "") for line in waiting["lines"]))
        if seconds >= MIN_TAKE_SECONDS:
            break
    groups = [*joined, waiting] if waiting is not None else joined

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
    # heard from beside the frame). A piece is on whoever speaks in it, a two-shot when two
    # do; a reaction is only ever on a listener who says nothing in it. A piece of the
    # narrator's words alone is his wide shot, also inside a run a short line shares with
    # him (`_held`), and the alternation counts only the pieces with a voice in the room.
    shots: list[dict[str, Any]] = []
    for group, pieces in zip(groups, wanted, strict=True):
        others = [name for name in distinct if name != group["speaker"]]
        run = {"speaker": group["speaker"], "lines": group["lines"]}
        in_room = 0
        for piece in _split_run(run, pieces):
            voices = list(dict.fromkeys(str(line.get("speaker") or "") or None for line in piece))
            room = [name for name in voices if name is not None]
            if not room:
                # The voice in off over the room and its people.
                shots.append(
                    {"lines": piece, "size": "establishing", "on": None, "shot": 0, "of": 0}
                )
                continue
            silent = [name for name in others if name not in room]
            listener = silent[0] if silent else None
            reaction = in_room % 2 == 1 and listener is not None
            in_room += 1
            if reaction:
                size, on = "reaction", listener
            elif len(room) > 1:
                size, on = "two_shot", group["speaker"] if group["speaker"] in room else room[0]
            else:
                size, on = "single", room[0]
            shots.append({"lines": piece, "size": size, "on": on, "shot": 0, "of": 0})
    if first_beat and shots:
        shots[0]["size"] = "establishing"
    kind = str(part or "").strip().lower()
    if kind == "button":
        # The last shot in the room is the close-up; a narrator's closing shot stays wide —
        # save when the button's few words share it (`_held`): it is then that close-up,
        # held on the speaker under the closing line.
        spoken = [shot for shot in shots if shot["on"] is not None]
        if spoken and spoken[-1]["size"] in ("single", "two_shot"):
            spoken[-1]["size"] = "close"
    for i, shot in enumerate(shots, start=1):
        shot["shot"], shot["of"] = i, len(shots)
        shot["cut_after"] = serial_cut(shot, shots[i] if i < len(shots) else None)
    return shots


#: How a serial shot hands over to the next one (`serial_cut`): the pause plan reads it with
#: the lines themselves (`pauses.boundary_class`).
SPEAKER_CHANGE = "speaker_change"
INTERRUPT_CUT = "interrupt"
REACTION_SPLIT = "reaction_split"
SAME_SPEAKER = "same_speaker"
NARRATOR_IN = "narrator_in"
NARRATOR_OUT = "narrator_out"
BEAT_END = "beat_end"


def serial_cut(shot: dict[str, Any], following: dict[str, Any] | None) -> str:
    """What happens at the cut after ``shot`` (``following`` the beat's next shot, None after
    its last): BEAT_END; NARRATOR_IN (the room hands to the narrator) or NARRATOR_OUT (he hands
    to the room); INTERRUPT (the line ends on a dash and another speaker cuts in) or
    SPEAKER_CHANGE; REACTION_SPLIT (the same speaker's words go on over the listener's face)
    or SAME_SPEAKER."""
    if following is None:
        return BEAT_END
    said = [line for line in shot.get("lines") or [] if str(line.get("text") or "").strip()]
    next_said = [
        line for line in following.get("lines") or [] if str(line.get("text") or "").strip()
    ]
    if not said or not next_said:
        return SAME_SPEAKER
    out = str(said[-1].get("speaker") or "") or None
    inn = str(next_said[0].get("speaker") or "") or None
    if out is None and inn is not None:
        return NARRATOR_OUT
    if out is not None and inn is None:
        return NARRATOR_IN
    if out != inn:
        words = str(said[-1].get("text") or "").split()
        return INTERRUPT_CUT if words and punctuation_class(words[-1]) == DASH else SPEAKER_CHANGE
    return REACTION_SPLIT if following.get("size") == "reaction" else SAME_SPEAKER
