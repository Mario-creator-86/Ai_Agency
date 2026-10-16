"""«Pauza vocii», stage 3: one estimate of the film, read everywhere, and quality control
against the plan (the Owner, 2026-10-16).

`media.film_length` is the one estimate: the script's reviews and the brief, the motion plan
and the sheet, the rehearsal, all read the voice's own pauses as the storyboard freezes them
and each voice's own rate, never a breath after every shot. Quality control reads the same
plan back from the render's record: the wall is the channel's maximum, never past 180 s; the
pauses the film may hold are the ones it planned; a join is dead air only past its own plan,
and a silence inside a take only past the join ceiling. Every voice here is a local fake;
nothing is bought from anyone, and no model is asked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.media import film_length, pauses, qc
from app.media.assembler import (
    NARRATION_ESTIMATED,
    NARRATION_MEASURED,
    clip_plan,
    narration_readings,
    scene_view,
    whole_frames,
)
from app.media.models import StoryboardScene, VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.services import utc_now
from pause_timing import HIGH, MARGIN, MEDIAN, pause
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_pause_freeze import LONG, _factual_board, _scene
from test_pause_render import SpacedVoice, _render

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="FFmpeg is not installed")
FRAME = 1.0 / 24


def _views(engine, board: str) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            scene_view(row)
            for row in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board)
                .order_by(StoryboardScene.scene_index)
            )
        ]


# ------------------------------------------------------------------- a storyboard's own rows


@pytest.mark.montage
def test_a_takes_last_row_holds_its_pause_and_a_cut_inside_it_none(engine):
    board = _factual_board(
        engine, [_scene(1, "HOOK", LONG), _scene(2, "ENDING", "Reserved on purpose, by it.")]
    )
    views = _views(engine, board)
    plans = film_length.frozen_rows(views)
    assert plans is not None
    hook = [i for i, view in enumerate(views) if view["voice_group"] == "s1"]
    assert len(hook) >= 2
    # Inside the take the cut adds nothing; the take's last row holds the change of part, the
    # film's last row its END: the narrator's own pauses, by the rules' formulas.
    assert all(plans[i].out == 0.0 for i in hook[:-1])
    assert plans[hook[-1]].out == pytest.approx(pause("PARAGRAPH"))
    assert plans[-1].out == pytest.approx(pause("END"))
    assert plans[hook[-1] + 1].into == pytest.approx(pause("PARAGRAPH"))
    # The shot holds the whole pause after it (cut_in_pause 1.0, the Owner's default).
    assert all(plan.beta == 1.0 for plan in plans)
    assert [plan.share for plan in plans] == [plan.out for plan in plans]

    # The motion plan buys each clip for its words at the narrator's high rate with the
    # margin, and for the pause its shot holds: nothing inside the take, the pause at its end.
    with Session(engine) as session:
        sizes = clip_plan(session, board, views)
        readings = narration_readings(session, board, views)
    for i in hook:
        index = views[i]["scene_index"]
        reading = readings[index]
        assert reading.source == NARRATION_ESTIMATED
        words = len(str(views[i]["voiceover_segment"]).split())
        assert reading.seconds == pytest.approx(round(words * HIGH, 3), abs=0.005)
        voiced = round(whole_frames(reading.seconds * (1 + MARGIN) + plans[i].out, up=True), 3)
        assert sizes[index]["seconds"] == max(voiced, sizes[index]["planned_seconds"])


def test_a_film_built_before_the_rules_is_no_frozen_film(engine, tmp_path):
    from pause_timing import freeze_film
    from test_clip_fits_narration import a_board

    board = a_board(engine, tmp_path, ["One scene said once.", "Then another one."])
    assert film_length.frozen_rows(_views(engine, board)) is not None
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        ):
            row.prompt_json = {k: v for k, v in dict(row.prompt_json or {}).items() if k != "beat"}
    assert film_length.frozen_rows(_views(engine, board)) is None
    # A plain view with no frozen pause is read by the legacy timing too.
    assert film_length.frozen_rows([{"scene_index": 1, "voiceover_segment": "x"}]) is None
    assert freeze_film(engine, board) is not None
    assert film_length.frozen_rows(_views(engine, board)) is not None


@requires_ffmpeg
@pytest.mark.montage
def test_a_take_said_over_rows_is_read_per_row_by_its_own_word_timing(engine, tmp_path):
    """Before a render measured them, the rows of a kept take said over several shots are
    read on the take's own alignment, as the render cuts it: each row to the next picture cut,
    the take's last row to its last letter at least and to the vendor's end at most."""
    board = _factual_board(
        engine, [_scene(1, "HOOK", LONG), _scene(2, "ENDING", "Reserved on purpose, by it.")]
    )
    render = _render(engine, board, SpacedVoice(), tmp_path)
    rendered = {
        entry["scene_index"]: float(entry["audio_seconds"])
        for entry in render["production"]["scenes"]
    }
    with Session(engine) as session, session.begin():
        session.execute(delete(VideoRenderJob).where(VideoRenderJob.storyboard_id == board))
    views = _views(engine, board)
    hook = [view["scene_index"] for view in views if view["voice_group"] == "s1"]
    with Session(engine) as session:
        readings = narration_readings(session, board, views)
    for index in hook[:-1]:
        reading = readings[index]
        assert reading.source == NARRATION_MEASURED
        assert reading.seconds == reading.least
        # The render lays each row on the frame nearest its cut: within a frame.
        assert reading.seconds == pytest.approx(rendered[index], abs=FRAME)
    last = readings[hook[-1]]
    assert last.source == NARRATION_MEASURED and last.least < last.seconds
    assert last.least - FRAME <= rendered[hook[-1]] <= last.seconds + FRAME


# -------------------------------------------------------------------------- the one estimate


def test_the_review_and_the_storyboard_read_the_same_film(engine):
    scenes = [
        _scene(1, "HOOK", "There is one web address on earth nobody is allowed to buy."),
        _scene(2, "DEVELOPMENT", "The registry keeps a short list of names it never sells."),
        _scene(3, "EVIDENCE", "The list has been public for decades, and it still holds."),
        _scene(4, "ENDING", "Reserved on purpose, by the registry itself."),
    ]
    board = _factual_board(engine, scenes)
    with Session(engine) as session:
        first = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board)
            .order_by(StoryboardScene.scene_index)
        ).first()
        frozen = first.prompt_json["beat"]["pause_profile"]
    estimate = film_length.factual_film_length(scenes)
    # The storyboard froze its pauses and its estimate from the same rules and voices.
    assert frozen["estimate"]["seconds"] == pytest.approx(estimate.seconds, abs=1e-3)
    assert estimate.pause_seconds == pytest.approx(
        2 * pause("PARAGRAPH") + pause("SENTENCE") + pause("END"), abs=1e-3
    )
    words = sum(len(scene["narration"].split()) for scene in scenes)
    assert estimate.spoken_seconds == pytest.approx(words * MEDIAN, abs=0.01)
    assert estimate.against_wall == pytest.approx(
        estimate.spoken_seconds * (1 + MARGIN) + estimate.pause_seconds, abs=1e-3
    )


def test_the_legacy_estimate_stands_while_the_rules_are_off(tmp_path, monkeypatch):
    data = json.loads(pauses.RULES_FILE.read_text(encoding="utf-8"))
    data["use_until_the_owner_changes_it"] = False
    off = tmp_path / "pause_rules.json"
    off.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pauses, "RULES_FILE", off)
    scenes = [{"narration": " ".join(["word"] * 10) + "."} for _ in range(3)]
    film = film_length.factual_film_length(scenes)
    # Each row its words at 0.40 s, the trim's two edges and the 0.4 s breath, on whole frames.
    row = whole_frames(10 * 0.40 + 2 * 0.03 + 0.4, up=True)
    assert film.seconds == pytest.approx(3 * row) and film.against_wall == film.seconds
    assert film_length.review_ceiling_seconds() == 177.0
    assert film_length.film_timing()["breath_seconds"] == 0.4
    assert film_length.factual_clips(scenes)[1] == round(whole_frames(4.0 * 1.1 + 0.4, up=True), 3)


def test_a_brief_states_the_voices_own_pauses_and_the_writers_marked_silence():
    from app.factual.agent_pipeline import _write_instructions
    from app.story import services

    brief = " ".join(_write_instructions(160).split())
    assert "plus pauza vocii între două scene (0,49 s, 0,77 s când se schimbă partea" in brief
    assert "respirație de 0,4 s după fiecare cadru" not in brief
    # The one sentence on the writer's marked silence, in the rules' own band.
    assert "devine o tăcere adevărată de 0,7-1,2 s înainte de scena următoare" in brief
    note = services._beat_note()
    assert "becomes a real silence of 0.7 to 1.2 seconds where it stands" in note
    assert "{beat_note}" in services._INSTRUCTIONS
    assert "Every shot keeps a breath" not in services._pause_note()


def test_a_script_past_its_channels_wall_is_refused_before_a_still_is_bought(engine):
    from app.factual.story_review import film_wall_check
    from app.publishing.models import ChannelRecord

    short = [{"narration": " ".join(["word"] * 12) + ".", "purpose": "HOOK"}]
    long = [{"narration": " ".join(["word"] * 14) + ".", "purpose": "HOOK"} for _ in range(30)]
    with Session(engine) as session:
        fits = film_wall_check(session, short)
        over = film_wall_check(session, long)
    assert fits is not None and fits["passed"] is True and fits["wall_seconds"] <= 180.0
    assert over is not None and over["passed"] is False
    assert over["with_margin_seconds"] > over["wall_seconds"]
    # A channel the Owner sets lower is held to its own maximum.
    with Session(engine) as session, session.begin():
        channel = session.scalars(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        ).first()
        if channel is None:
            channel = ChannelRecord(
                id=str(uuid4()),
                channel_name="Nexus Curiosity",
                channel_type="MAIN_FACTUAL",
                created_at=utc_now(),
            )
            session.add(channel)
        channel.shorts_max_seconds = 30
    with Session(engine) as session:
        lower = film_wall_check(session, [short[0]] * 4)
    assert lower is not None and lower["wall_seconds"] == 30.0


# ------------------------------------------------------------------- quality control's plan


def _frozen_production(spans: list[dict[str, Any]]) -> dict[str, Any]:
    clock, recorded = 0.0, []
    for index, span in enumerate(spans, start=1):
        end = clock + span["seconds"]
        recorded.append(
            {
                "scene_index": index,
                "start": round(clock, 6),
                "end": round(end, 6),
                "kind": span.get("kind", "LIVE"),
                "spoken_seconds": span.get("spoken"),
                "pause": {**span["pause"], "cut_at": round(end, 4)},
            }
        )
        clock = end
    return {
        "scenes": [
            {"scene_index": i, "scene_kind": "LIVE", "audio_seconds": span.get("spoken")}
            for i, span in enumerate(spans, start=1)
        ],
        "timeline": {"fps": 24, "spans": recorded, "pause_profile": {"rule_version": 1}},
    }


def test_the_length_budget_counts_the_pauses_the_film_planned():
    production = _frozen_production(
        [
            {"seconds": 3.0, "spoken": 3.0, "pause": {"class": "IN_TAKE", "planned": 0.0}},
            {"seconds": 3.5, "spoken": 3.0, "pause": {"class": "SENTENCE", "planned": 0.49}},
            {
                "seconds": 4.0,
                "spoken": 3.0,
                "pause": {
                    "class": "END",
                    "planned": 0.767,
                    "pad": 0.70,
                    "inner": [{"class": "TURN", "planned": 0.236, "pad": 0.2, "cut_at": 9.0}],
                },
            },
        ]
    )
    budget = qc.film_length_budget(production)
    assert budget["breath_seconds"] == pytest.approx(0.49 + 0.767 + 0.236)
    assert budget["allowed_seconds"] == pytest.approx(
        9.0 + 0.49 + 0.767 + 0.236 + budget["frame_rounding_seconds"] + 1.0
    )
    # A frozen film's average shot holds the mean pause it planned, not the legacy breath.
    montage = SimpleNamespace(
        montage_enabled=True, montage_shot_seconds=4.0, montage_max_shots_per_scene=3
    )
    assert qc.average_shot_limit(production, montage) == pytest.approx(
        round(4.0 * 1.5 + (0.0 + 0.49 + 1.003) / 3, 2)
    )


@requires_ffmpeg
def test_a_join_is_dead_air_only_past_its_own_plan_and_a_take_past_the_ceiling(tmp_path):
    from test_editorial_qc import BED, _film

    def checked(silence: float, inside: float) -> dict[str, Any]:
        # Scene 1: words, then the planned 0.49 s full stop heard as ``silence``; scene 2: words,
        # a pause of ``inside`` seconds inside its own take, words.
        first = 2.0 + silence
        second = 1.0 + inside + 1.0 + 0.5
        film = _film(
            tmp_path / f"film_{silence}_{inside}.mp4",
            [("testsrc2", first), ("testsrc2,negate", second)],
            [
                ("tone", 2.0),
                ("silence", silence),
                ("tone", 1.0),
                ("silence", inside),
                ("tone", 1.0),
                ("silence", 0.5),
            ],
        )
        production = {
            **BED,
            **_frozen_production(
                [
                    {
                        "seconds": first,
                        "spoken": 2.0,
                        "pause": {"class": "SENTENCE", "planned": 0.49},
                    },
                    {
                        "seconds": second,
                        "spoken": second - 0.5,
                        "pause": {"class": "END", "planned": 0.5},
                    },
                ]
            ),
        }
        return qc.editorial_problems(film, production, ffmpeg=find_ffmpeg(), cues=[])

    def dead(report: dict[str, Any]) -> list[dict[str, Any]]:
        return [problem for problem in report["problems"] if problem["code"] == "dead_air"]

    # Heard within the plan's tolerance (0.49 x 1.2 + a frame = 0.63 s), and a 1.0 s pause the
    # voice made inside its take: no dead air.
    assert dead(checked(0.55, 1.0)) == []
    # Past the join's own plan: dead air, said against the pause planned there.
    (late,) = dead(checked(0.85, 0.3))
    assert late["planned"] == pytest.approx(0.49)
    assert "pauza plănuită e de 0,49 s" in late["reason_ro"]
    # Past the join ceiling inside a take (1.2 s): dead air in the middle of the words.
    (long,) = dead(checked(0.5, 1.5))
    assert long["planned"] is None and "în mijlocul unei replici" in long["reason_ro"]
    assert long["limit"] == pytest.approx(pauses.load_rules().join_ceiling_seconds)


def test_the_wall_is_the_rules_wall():
    rules = pauses.load_rules()
    assert qc.shorts_length_ceiling(240) == pauses.wall_seconds(240, rules) == 180.0
    assert qc.shorts_length_ceiling(120) == pauses.wall_seconds(120, rules) == 120.0
