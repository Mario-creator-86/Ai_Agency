"""The film's length against YouTube's 180 s wall, measured before anything is bought
(the adversarial review of 2026-10-16, findings 2, 9, 14-16, 18-20 and 28).

The montage cuts a writer's scene or a beat into shots, and every shot with words kept a
0.4 s breath rounded up to a frame. The reviews priced 0.35 s a writer's scene (factual) or
5 s in all (serial), so scripts they passed came out at 185-195 s and quality control
refused them after every still, clip and voice was bought.

Since «pauza vocii» (the Owner, 2026-10-16) a film is said one take per writer's scene and per
speaker's run, the montage cutting the picture inside a take for nothing, and between two
takes the voice's own pause at that boundary, frozen when the storyboard is built. Each test
here lays the film out the way the render does (`pause_plan.voice_layout`, over takes said at
the pinned voices' median rates and the pauses `pauses.freeze` plans), never through the
estimate it checks (`film_length`), and the reviews hold the estimate against the wall with the
margin on its words (``FilmLength.against_wall``).
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from app.factual.editorial import MAX_SHORT_SECONDS, narration_budget, story_checks
from app.media import qc
from app.media.assembler import SECONDS_PER_SPOKEN_WORD, scene_spans, spoken_words, whole_frames
from app.media.montage import factual_shots, serial_shots
from app.media.toolchain import EDGE_KEEP_SECONDS
from app.story.review import failed_rules
from pause_timing import MEDIAN, PINNED_VOICE_PROFILES
from test_serial_pipeline import (  # noqa: F401 - staffed is a fixture
    KAEL,
    SARAH,
    beats_for,
    checks_of,
    letters_day,
    staffed,
    written,
)

WALL = 180.0
VOCABULARY = (
    "the registry kept one address back for itself and nobody may buy it today "
    "because a rule older than the web still holds every registrar to that promise"
).split()


def _text(words: int, offset: int = 0) -> str:
    """``words`` plain words of prose, ending on a full stop."""
    picked = [VOCABULARY[(offset + i) % len(VOCABULARY)] for i in range(words)]
    return " ".join(picked) + "."


def _factual(counts: list[int]) -> list[dict]:
    return [
        {"narration": _text(n, offset=i), "purpose": "HOOK" if i == 0 else "DEVELOPMENT"}
        for i, n in enumerate(counts)
    ]


def _factual_worst(counts: list[int]) -> list[dict]:
    """The same words with a change of part at every join: the longest film they make."""
    return [
        {"narration": _text(n, offset=i), "purpose": ("HOOK", "PAYOFF")[i % 2]}
        for i, n in enumerate(counts)
    ]


#: The pinned cast's median rate (`pause_timing.PINNED_VOICE_PROFILES`).
CHARACTER_MEDIAN = 0.34


def _laid_out(sides: list[dict], owners: list[int], rows: int, *, serial: bool) -> float:
    """The film the render lays out (`pause_plan.voice_layout`) from these sides: the joins
    planned as the storyboard freezes them (`pauses.freeze`), one take per voice take (a cut
    inside it adds nothing), each side said at its pinned voice's median rate, each take
    followed by its planned pause, every cut on a frame of the timeline."""
    from app.media import pause_plan, pauses

    rules = pauses.load_rules()
    frozen = pauses.freeze(
        sides,
        serial=serial,
        rules=rules,
        knobs=pauses.channel_pauses("serial" if serial else "factual", rules),
        profiles=PINNED_VOICE_PROFILES,
        narrator_voice=None,
    )
    takes: list[dict] = []
    units: list[list] = [[] for _ in range(rows)]
    for index, side in enumerate(sides):
        said = spoken_words(side["text"]) * (CHARACTER_MEDIAN if side.get("speaker") else MEDIAN)
        if not said:
            continue
        joined = index > 0 and frozen.pauses[index - 1]["class"] == "IN_TAKE" and takes
        if not joined:
            takes.append({"seconds": 0.0, "pad": 0.0})
        unit = pause_plan.Unit(len(takes) - 1, takes[-1]["seconds"], said)
        units[owners[index]].append(unit)
        takes[-1]["seconds"] += said
        takes[-1]["pad"] = float(frozen.pauses[index]["seconds"])
    layout = pause_plan.voice_layout(
        [row or 3.0 for row in units],
        [pause_plan.TakeJoin(take["seconds"], take["pad"]) for take in takes],
        fps=24,
        cut_in_pause=1.0,
    )
    return sum(layout.spans)


def _even(words: int, scenes: int) -> list[int]:
    base, extra = divmod(words, scenes)
    return [base + (1 if i < extra else 0) for i in range(scenes)]


def _take(text: str) -> float:
    """A take as the render keeps it: its words at the studio's rate and the edges the trim
    keeps either side."""
    return spoken_words(text) * SECONDS_PER_SPOKEN_WORD + 2 * EDGE_KEEP_SECONDS


def _legacy_assembled_factual(scenes: list[dict]) -> float:
    """The film the assembler timed before the pause rules: each LIVE scene cut by the
    montage, each shot its take plus the legacy breath on whole frames (`scene_spans`)."""
    planned: list[float] = []
    spoken: list[float | None] = []
    for number, scene in enumerate(scenes, start=1):
        for shot in factual_shots(scene["narration"], number, live=True):
            planned.append(3.0)
            spoken.append(_take(shot["narration"]) if spoken_words(shot["narration"]) else None)
    return sum(scene_spans(planned, spoken))


def _assembled_factual(scenes: list[dict]) -> float:
    """The film the render would lay out: each LIVE scene cut by the montage into shots of one
    take (`pause_plan.factual_side`, its writer's scene its take), the pauses between the
    writer's scenes as the storyboard freezes them (`_laid_out`)."""
    from app.media import pauses
    from app.media.pause_plan import factual_side

    rules = pauses.load_rules()
    sides: list[dict] = []
    for number, scene in enumerate(scenes, start=1):
        for shot in factual_shots(scene["narration"], number, live=True):
            sides.append(
                factual_side(
                    shot["narration"],
                    scene=number,
                    purpose=scene.get("purpose"),
                    kind="LIVE",
                    planned_seconds=3.0,
                    rules=rules,
                )
            )
    return _laid_out(sides, list(range(len(sides))), len(sides), serial=False)


def _assembled_serial(beats: list[tuple[list[dict], str]]) -> tuple[float, int]:
    """An episode as the render would lay it out: each beat's lines marked and named for their
    voice takes (`pause_plan.serial_lines`), cut by the montage, each shot its speakers' runs
    (`pause_plan.serial_row_sides`), the joins as the storyboard freezes them (`_laid_out`)."""
    from app.media import pauses
    from app.media.pause_plan import serial_lines, serial_row_sides

    rules = pauses.load_rules()
    named = serial_lines([said for said, _ in beats], [part for _, part in beats], rules)
    sides: list[dict] = []
    owners: list[int] = []
    rows = 0
    for number, (lines, (_, part)) in enumerate(zip(named, beats, strict=True), start=1):
        for shot in serial_shots(lines, number, part=part, first_beat=number == 1):
            found, _runs = serial_row_sides(shot["lines"], beat=number)
            sides += found
            owners += [rows] * len(found)
            rows += 1
    return _laid_out(sides, owners, rows, serial=True), rows


def test_the_wall_is_one_number_and_the_estimate_carries_its_margin():
    from app.media.film_length import (
        SHORTS_WALL_SECONDS,
        Timing,
        factual_film_length,
        review_ceiling_seconds,
    )

    assert SHORTS_WALL_SECONDS == qc.SHORTS_MAX_LIMIT_SECONDS == MAX_SHORT_SECONDS == WALL
    # Under the pause rules the reviews hold the film against the wall itself...
    assert review_ceiling_seconds() == 180.0
    # ...a channel the Owner sets lower under its own number, never above the wall...
    assert review_ceiling_seconds(150) == 150.0
    assert review_ceiling_seconds(240) == 180.0
    # ...the margin being the estimate's own: its words with NARRATION_ESTIMATE_MARGIN.
    film = factual_film_length(_factual([20, 20, 20]))
    assert film.against_wall == pytest.approx(
        film.spoken_seconds * 1.1 + film.pause_seconds, abs=1e-3
    )
    assert film.seconds == pytest.approx(film.spoken_seconds + film.pause_seconds, abs=1e-3)
    # With the rules off, the legacy estimate is held 3 s under the wall, as before.
    assert review_ceiling_seconds(when=Timing()) == 177.0
    assert review_ceiling_seconds(150, Timing()) == 147.0


# ------------------------------------------------------------------------- factual (14, 2, 28)


@pytest.mark.montage
def test_a_factual_draft_at_the_briefs_maximum_is_a_film_under_the_wall():
    budget = narration_budget(160)
    assert budget["target_seconds"] == 160.0 and 26 <= budget["scenes"] <= 30
    assert budget["max_seconds"] <= WALL

    at_target = _factual(_even(budget["total_words"], budget["scenes"]))
    # The most words on the longest shape a draft can take: a change of part at every join.
    at_most = _factual_worst(_even(budget["max_words"], budget["scenes"]))
    # Written to the brief's own numbers, the film the render would lay out stays under the
    # wall, and the review accepts both.
    assert _assembled_factual(at_target) <= 160.0 + 1 / 24
    assert _assembled_factual(at_most) <= WALL
    for draft in (at_target, at_most):
        assert story_checks(title="t", scenes=draft, story={}, target_seconds=160)[
            "duration_is_realistic"
        ]["passed"]

    # Ten words over the brief's ceiling, in the same shape: with the estimate's margin on its
    # words the film passes the wall and the review refuses it, before a still is bought.
    longer = _factual_worst(_even(budget["max_words"] + 10, budget["scenes"]))
    check = story_checks(title="t", scenes=longer, story={}, target_seconds=160)[
        "duration_is_realistic"
    ]
    assert not check["passed"] and check["wall_seconds"] > WALL
    assert "ținta de 160s" in check["reason"] and "80-180s" in check["reason"]
    assert "zidul de 180 s" in check["reason"]


def _keeping_the_brief(budget: dict, seed: int) -> list[list[int]]:
    """Drafts that keep every number the brief gives: its scene count, each scene inside its
    band of words, at most its maximum in all. The worst shapes first (for each width of the
    band, as many scenes at it as the maximum allows, the rest at the band's floor taking what
    is left), every scene at the band's top, then random ones."""
    scenes = budget["scenes"]
    low, high = budget["words_per_scene_low"], budget["words_per_scene_high"]
    most = budget["max_words"]
    shapes: list[list[int]] = []
    for width in range(low, high + 1):
        many = max(k for k in range(scenes + 1) if k * width + (scenes - k) * low <= most)
        counts = [width] * many + [low] * (scenes - many)
        spare = most - sum(counts)
        for index in range(many, scenes):
            more = min(spare, high - counts[index])
            counts[index] += more
            spare -= more
        shapes.append(counts)
    shapes.append([high] * scenes)
    rng = random.Random(seed)
    for _ in range(12):
        shapes.append([rng.randint(low, high) for _ in range(scenes)])
    for counts in shapes:
        while sum(counts) > most:
            index = rng.choice([i for i, words in enumerate(counts) if words > low])
            counts[index] -= 1
    return shapes


@pytest.mark.montage
@pytest.mark.parametrize("montage", ["1", "0"])
@pytest.mark.parametrize("target", [90, 160, 180])
def test_every_draft_that_keeps_the_brief_is_a_film_the_review_accepts(
    montage, target, monkeypatch
):
    """The adversarial review's R1: the brief's band (10-16 words a scene at 160 s) reached
    past the montage's cut at fifteen, and 23 scenes of fifteen, one of fourteen and four of
    ten — 399 words, every scene inside the band, at the brief's maximum — were 51 shots and
    184.1 s, refused for following the brief. Whatever shape a writer gives the words, if
    every number of the brief is kept, the film is under the ceiling and the review takes it."""
    monkeypatch.setenv("STUDIO_MONTAGE_ENABLED", montage)
    budget = narration_budget(target)
    for counts in _keeping_the_brief(budget, seed=target):
        assert len(counts) == budget["scenes"] and sum(counts) <= budget["max_words"]
        assert all(
            budget["words_per_scene_low"] <= words <= budget["words_per_scene_high"]
            for words in counts
        )
        draft = _factual(counts)
        assert _assembled_factual(draft) <= budget["max_seconds"] + 1e-6, counts
        check = story_checks(title="t", scenes=draft, story={}, target_seconds=target)[
            "duration_is_realistic"
        ]
        assert check["passed"], (counts, check["reason"])


@pytest.mark.montage
def test_the_band_stops_under_the_montages_cut_and_the_brief_names_it():
    from app.factual.agent_pipeline import _write_instructions
    from app.media.film_length import factual_cut_words

    budget = narration_budget(160)
    cut = factual_cut_words()
    # Fifteen words are two shots and two breaths, fourteen one (`montage.shot_count`).
    assert cut == 15 == budget["cut_words"]
    assert len(factual_shots(_text(cut - 1), 2, live=True)) == 1
    assert len(factual_shots(_text(cut), 2, live=True)) == 2
    # A scene the brief describes is one shot, and the band still holds the target's words.
    # (Under the pause rules the most words may sit inside the band: a draft keeps both, and
    # the most words are priced on the longest shape a draft can take.)
    assert budget["words_per_scene_high"] == cut - 1
    assert (
        budget["scenes"] * budget["words_per_scene_low"]
        <= budget["total_words"]
        <= min(budget["max_words"], budget["scenes"] * budget["words_per_scene_high"])
    )
    # The reviewer's drafts are no longer inside the band: each has a scene at the cut.
    for counts in ([15] * 23 + [14] + [10] * 4, [16] * 19 + [15] + [10] * 8, [15] * 26):
        assert max(counts) > budget["words_per_scene_high"]
    # The writer is told where the cut lies, in the brief's own numbers.
    brief = _write_instructions(160)
    assert f"{budget['scenes']} scene, cam {budget['words_per_scene_low']}-{cut - 1} cuvinte" in (
        " ".join(brief.split())
    )
    assert f"o scenă de {cut} cuvinte sau mai multe se taie în două-trei cadre" in (
        " ".join(brief.split())
    )


def test_with_the_montage_off_the_brief_cuts_no_scene():
    from app.factual.agent_pipeline import _write_instructions
    from app.media.film_length import factual_cut_words

    assert factual_cut_words() is None
    assert narration_budget(160)["cut_words"] is None
    brief = " ".join(_write_instructions(160).split())
    assert "iar fiecare scenă rămâne un singur cadru" in brief
    assert "se taie în două-trei cadre" not in brief


@pytest.mark.montage
def test_the_review_measures_the_film_as_the_montage_cuts_it():
    """The finding's case: 25 scenes of 17 words were read at 171.9 s and passed; the montage
    cut each into two shots, each with its breath, and the film was about 190 s. Under the
    pause rules a cut inside a writer's scene adds nothing: the film is its words and the
    narrator's pauses between the scenes (about 169 s), and held against the wall with the
    estimate's margin on its words it passes it, so the review refuses it before a still is
    bought."""
    draft = _factual([17] * 25)
    film = _assembled_factual(draft)
    assert _legacy_assembled_factual(draft) > WALL > film

    check = story_checks(title="t", scenes=draft, story={}, target_seconds=160)[
        "duration_is_realistic"
    ]
    assert check["shots"] == 50
    assert check["estimated_seconds"] == pytest.approx(film, abs=1 / 24)
    assert check["wall_seconds"] > WALL
    assert not check["passed"]
    assert "50 de cadre" in check["reason"]


@pytest.mark.montage
def test_the_estimate_reads_the_storyboards_own_rows(engine):
    """The estimate cuts the script as the storyboard does, row for row."""
    from app.media.film_length import factual_rows
    from app.media.models import StoryboardScene
    from app.media.services import generate_storyboard_from_script
    from app.models import OwnerPolicy
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_editorial_quality import GOOD_STORY, a_passed_review, a_script, a_topic

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
    scenes = [
        {
            "scene_number": index,
            "purpose": purpose,
            "narration": _text(words, offset=index),
            "visual_description": "A notebook page of figures under a desk lamp.",
            "claim_ids": [("c1", "c2")[index % 2]],
        }
        for index, (purpose, words) in enumerate(
            (("HOOK", 31), ("SETUP", 12), ("DEVELOPMENT", 16), ("PAYOFF", 24)), start=1
        )
    ]
    script_id = a_script(engine, a_topic(engine), scenes=scenes, story=GOOD_STORY)
    a_passed_review(engine, script_id)

    board = generate_storyboard_from_script(engine, script_id, None, "9:16", "c")
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        )
    estimated = factual_rows(scenes)
    assert [row.voiceover_segment for row in rows] == [row["narration"] for row in estimated]
    assert len(rows) == 3 + 1 + 2 + 2


# ----------------------------------------------------------------------------- serial (9, 15)


def _episode(total_words: int, beats: int = 12, lines_per_beat: int = 3) -> list[tuple]:
    """A v8 episode of ``total_words``: a narrator opens with three sentences and closes with
    one, two people alternate in between."""
    opening = [
        {"speaker": None, "text": _text(11, 1)},
        {"speaker": None, "text": _text(11, 5)},
        {"speaker": None, "text": _text(12, 9)},
    ]
    closing = [{"speaker": None, "text": _text(12, 3)}]
    middle = total_words - 34 - 12
    lines = _even(middle, beats * lines_per_beat)
    parts = ["hook"] + ["situation"] * (beats - 4) + ["turn", "payoff", "button"]
    episode = []
    for beat in range(beats):
        said = [
            {"speaker": (SARAH, KAEL)[(beat + i) % 2], "text": _text(n, beat + i)}
            for i, n in enumerate(lines[beat * lines_per_beat : (beat + 1) * lines_per_beat])
        ]
        if beat == 0:
            said = opening + said
        if beat == beats - 1:
            said = said + closing
        episode.append((said, parts[beat]))
    assert sum(len(line["text"].split()) for said, _ in episode for line in said) == total_words
    return episode


@pytest.mark.montage
def test_a_twelve_beat_episode_at_the_briefs_maximum_is_a_film_under_the_wall():
    from app.story.services import EPISODE_WORDS

    episode = _episode(EPISODE_WORDS[1])
    film, shots = _assembled_serial(episode)
    assert 30 <= shots <= 45
    assert film <= WALL - 2

    from app.media.film_length import serial_film_length
    from app.story.review import MAX_SECONDS, MIN_SECONDS
    from app.story.services import EPISODE_SECONDS

    estimate = serial_film_length([said for said, _ in episode], [part for _, part in episode])
    assert estimate.rows == shots and estimate.seconds == pytest.approx(film, abs=1 / 24)
    assert estimate.against_wall <= WALL
    # The brief and the review read the same numbers.
    assert (MIN_SECONDS, MAX_SECONDS) == EPISODE_SECONDS == (90.0, EPISODE_WORDS[1] / 2.5)


@pytest.mark.montage
def test_an_episode_of_slow_voices_is_refused_under_the_word_ceiling(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    """Under the brief's words, but said by two voices that measured slow (0.46 s a word,
    as Kael and Dr. Aris measure 0.43-0.44): the episode is a film past the wall. The review
    measures the film in its speakers' own voices («pauza vocii»), not the words; it used to
    be the 86 breaths of seven four-word lines a beat, which a cut no longer adds."""
    import copy

    from app.media import pause_plan, pauses
    from app.story.services import EPISODE_WORDS

    slow = {
        "pool": "character",
        "takes": 9,
        "classes": {
            "SENTENCE": {"median": 0.3, "p25": 0.24, "n": 9},
            "CLAUSE": {"median": 0.24, "p25": 0.19, "n": 9},
            "DASH": {"median": 0.35, "p25": 0.18, "n": 9},
        },
        "rate": {
            "seconds_per_word": 0.46,
            "take_median_seconds_per_word": 0.46,
            "take_median_words_per_second": 2.17,
            "take_p25_words_per_second": 2.0,
        },
    }
    measured = copy.deepcopy(PINNED_VOICE_PROFILES)
    measured["voices"] = {"TEST:v1:sarah": dict(slow), "TEST:v1:kael": dict(slow)}
    monkeypatch.setattr(pauses, "load_profiles", lambda *a, **k: copy.deepcopy(measured))
    monkeypatch.setattr(
        pause_plan,
        "serial_voice_keys",
        lambda _session, _bibles: (None, {SARAH: "TEST:v1:sarah", KAEL: "TEST:v1:kael"}),
    )

    _, ids = letters_day(engine)
    beats = beats_for(ids, [SARAH, KAEL], count=12)
    said = (
        "We cut the whole second act again today.",
        "Then the number moves and the client sees it.",
        "Not before lunch, Kael, the board reads it.",
        "Give me ten minutes and the cut runs clean.",
    )
    for index, beat in enumerate(beats):
        beat["lines"] = [
            {"speaker": (SARAH, KAEL)[(index + i) % 2], "text": said[(index + i) % 4]}
            for i in range(3)
        ]
    beats[0]["lines"] = [
        {
            "speaker": "Narrator",
            "text": "The Content floor, a little after nine. Sarah wants the number before "
            "lunch, and Kael has not slept. Today the studio finds out whether a late cut can "
            "still go out.",
        },
        *beats[0]["lines"],
    ]
    beats[-1]["lines"] = [
        *beats[-1]["lines"],
        {"speaker": "Narrator", "text": "The cut went back to the bay, and that was the day."},
    ]

    checks = checks_of(engine, written(engine, monkeypatch, beats)["id"])

    length = checks["length"]
    assert length["words"] <= EPISODE_WORDS[1]
    assert length["wall_seconds"] > length["ceiling_seconds"] == 180.0
    assert "length" in failed_rules(checks)
    assert "zidul de 180 s al Short-ului" in length["reason"] and "cadre" in length["reason"]


# ------------------------------------------------------------------------- quality control (19)


def test_the_wall_is_exactly_the_channels_maximum_never_past_youtubes():
    # «Pauza vocii» (2026-10-16): the film's last word is held for its planned END and the
    # render fits every pause under min(the channel's maximum, 180 s); no slack past it.
    assert qc.shorts_length_ceiling(180) == 180.0
    assert qc.shorts_length_ceiling(150) == 150.0
    assert qc.shorts_length_ceiling(179.5) == 179.5
    assert qc.shorts_length_ceiling(240) == 180.0


# ------------------------------------------------------------- the length budget's rounding (16)


def test_fifty_speaking_shots_rounded_up_to_a_frame_are_not_film_over_the_narration():
    """Each shot lasts its words plus the breath, rounded UP to a frame: fifty shots round
    by about 2 s, which the 1.0 s used to refuse in PRODUCTION."""
    fps = 24
    # Words just past a frame boundary, so each span rounds up by almost a whole frame.
    spoken = [round(2.6 + (i % 5) / fps + 0.001, 4) for i in range(50)]
    spans = scene_spans([3.0] * 50, spoken, fps=fps)
    clock, recorded = 0.0, []
    for index, (said, span) in enumerate(zip(spoken, spans, strict=True), start=1):
        recorded.append(
            {
                "scene_index": index,
                "start": round(clock, 6),
                "end": round(clock + span, 6),
                "kind": "LIVE",
                "spoken_seconds": said,
            }
        )
        clock += span
    production = {
        "scenes": [
            {"scene_index": i, "scene_kind": "LIVE", "audio_seconds": s}
            for i, s in enumerate(spoken, start=1)
        ],
        "timeline": {"fps": fps, "spoken_tail_seconds": 0.4, "spans": recorded},
    }
    narration = sum(spoken)
    rounding = clock - narration - 0.4 * 50
    assert rounding > 1.5  # what the 1.0 s could not hold

    budget = qc.film_length_budget(production)
    probe = {
        "width": 1080,
        "height": 1920,
        "video_codec": "h264",
        "video_profile": "High",
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
        "video_fps": 24.0,
        "video_bit_rate": 10_000_000,
        "duration_seconds": round(clock, 3),
    }
    failures, warnings = qc.technical_problems(
        probe, environment="PRODUCTION", timeline_fps=24, narration_seconds=narration, budget=budget
    )
    assert failures == [] and warnings == []
    assert budget["frame_rounding_seconds"] == pytest.approx(rounding, abs=0.01)
    assert budget["frame_rounding_seconds"] <= 50 / fps

    # A shot that kept a plan longer than its words, its breath and a frame is still film over
    # the narration: the rounding is read per span, at most one frame each.
    recorded[0]["end"] += 2.0
    for span in recorded[1:]:
        span["start"] += 2.0
        span["end"] += 2.0
    longer = qc.film_length_budget(production)
    assert longer["frame_rounding_seconds"] <= budget["frame_rounding_seconds"] + 1 / fps
    failures, _ = qc.technical_problems(
        {**probe, "duration_seconds": round(clock + 2.0, 3)},
        environment="PRODUCTION",
        timeline_fps=24,
        narration_seconds=narration,
        budget=longer,
    )
    assert any("rotunjirea la cadre întregi" in failure for failure in failures), failures


# --------------------------------------------------------------- the factual clip check (18)


@pytest.mark.montage
def test_a_long_live_scene_is_measured_by_its_longest_shot(engine, monkeypatch):
    from app.factual.story_review import scene_clip_check

    monkeypatch.setattr("app.media.shooting_sheet.motion_clip_limit", lambda _e: ("ltx2_5", 10))
    scene = {"narration": _text(28), "scene_kind": "LIVE"}
    # Twelve and three quarter seconds as one clip; three shots of nine or ten words cut.
    assert len(factual_shots(scene["narration"], 1, live=True)) == 3
    fits = scene_clip_check(engine, [scene])
    assert fits is not None and fits["passed"] is True, fits

    # A scene whose longest shot still runs past the clip is refused, naming the shot.
    flood = {"narration": _text(90), "scene_kind": "LIVE"}
    refused = scene_clip_check(engine, [scene, flood])
    assert refused is not None and refused["passed"] is False
    assert "Scena 2" in refused["reason"] and "cele 3 cadre" in refused["reason"]
    assert "Scena 1 " not in refused["reason"]

    # With the montage off a scene is one clip, measured whole: 28 words at the narrator's
    # high rate with the 10% margin and the film's END held after them, 13.125 s.
    monkeypatch.setenv("STUDIO_MONTAGE_ENABLED", "0")
    whole = scene_clip_check(engine, [scene])
    assert whole is not None and whole["passed"] is False
    assert "Scena 1 cere un cadru de 13,12 s" in whole["reason"]


# ----------------------------------------------------------------------- editorial QC (20)


@pytest.mark.montage
def test_the_average_shot_follows_the_montage():
    on = qc.average_shot_limit({"timeline": {"spoken_tail_seconds": 0.4}})
    assert on == pytest.approx(4.0 * 1.5 + 0.4)
    # The Owner's 160 s short at the brief's own target: 28 shots of about 5.8 s.
    assert 160.0 / 28 < on
    off = SimpleNamespace(
        montage_enabled=False, montage_shot_seconds=4.0, montage_max_shots_per_scene=3
    )
    assert qc.average_shot_limit({}, off) == qc.MAX_AVERAGE_SHOT_SECONDS


def test_the_breath_at_a_cut_is_planned_and_dead_air_past_it_is_not(tmp_path):
    from test_editorial_qc import BED, FFMPEG, _film

    if FFMPEG is None:
        pytest.skip("no FFmpeg on this machine")

    def spans(first_words: float, first_span: float, second: float) -> dict:
        return {
            **BED,
            "timeline": {
                "spoken_tail_seconds": 0.4,
                "spans": [
                    {
                        "scene_index": 1,
                        "start": 0.0,
                        "end": first_span,
                        "kind": "LIVE",
                        "spoken_seconds": first_words,
                    },
                    {
                        "scene_index": 2,
                        "start": first_span,
                        "end": first_span + second,
                        "kind": "LIVE",
                        "spoken_seconds": second - 0.4,
                    },
                ],
            },
        }

    first_span = whole_frames(2.0 + 0.4, 24, up=True)
    breath = first_span - 2.0 + EDGE_KEEP_SECONDS  # the pad and the next take's kept edge
    film = _film(
        tmp_path / "breath.mp4",
        [("testsrc2", first_span), ("testsrc2,negate", 2.4)],
        [("tone", 2.0), ("silence", breath), ("tone", 2.0), ("silence", 2.4 - 2.0 - 0.03)],
    )
    report = qc.editorial_problems(film, spans(2.0, first_span, 2.4), ffmpeg=FFMPEG, cues=[])
    assert "dead_air" not in {problem["code"] for problem in report["problems"]}, report

    # A take that kept 0.6 s of the vendor's silence after its words (an untrimmed take): the
    # timeline planned only the breath after it, and the 0.6 s is dead air, named.
    kept = whole_frames(2.6 + 0.4, 24, up=True)
    gap = _film(
        tmp_path / "gap.mp4",
        [("testsrc2", kept), ("testsrc2,negate", 2.4)],
        [("tone", 2.0), ("silence", kept - 2.0 + 0.03), ("tone", 2.0), ("silence", 0.37)],
    )
    report = qc.editorial_problems(gap, spans(2.6, kept, 2.4), ffmpeg=FFMPEG, cues=[])
    assert "dead_air" in {problem["code"] for problem in report["problems"]}, report
