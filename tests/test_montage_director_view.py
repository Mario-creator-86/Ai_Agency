"""The Director's view of a montage film (the review of 2026-10-16's commits).

The montage cuts a writer's scene into 2-3 storyboard rows, so a 160 s film has 40-90 rows
where it had a dozen scenes. Three readings were still sized for the old films:

- her QC decision held at most 80 verdicts and 24 repairs, and she was told «judge at most 80
  findings», while the report's own schema wants every finding judged: a report past 80
  waited for an answer that could not exist (`reviews.qc_answer_caps`);
- her viewing and the film's picture look took the first eight rows, the film's first
  half-minute, and never saw its ending (`editorial.frame_picks`);
- the guesses about who a writer's scene shows were keyed by the writer's scene and read by
  the storyboard's row, so the record named another shot (`services.GUESSED_CAST_BY_ROW`).

No provider is called: every model is scripted, every encoder faked.
"""

from __future__ import annotations

import base64
import json
import subprocess
from uuid import uuid4

import pytest
from app.agents.editorial import MAX_FRAMES, editorial_review, frame_picks, frames_for
from app.agents.identity import read_structured
from app.agents.models import AgentRun
from app.agents.reviews import (
    QC_MIN_REPAIRS,
    QC_MIN_VERDICTS,
    decision_schema,
    director_qc_tokens,
    qc_answer_caps,
    review_film_qc,
)
from app.media.models import CharacterBible, StoryboardScene
from app.media.montage import beat_tag
from app.media.picture_qc import evaluate_pictures
from app.media.services import (
    GUESSED_CAST_BY_ROW,
    generate_storyboard_from_script,
    seed_default_character_bibles,
    storyboard_cast_record,
)
from app.models import OwnerPolicy
from app.services import append_event, utc_now
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_director_decides_qc import (  # noqa: F401 - studio is a fixture
    _context_of,
    answer,
    director_says,
    studio,
)
from test_editorial import (
    ENGLISH,
    staffed,  # noqa: F401 - the fixture
)
from test_editorial import a_film as an_editorial_film
from test_editorial import registry_with as editorial_registry
from test_editorial_quality import GOOD_STORY, a_passed_review, a_script, a_topic
from test_picture_qc import a_film as a_picture_film
from test_picture_qc import give_vision, registry_with, scene_answer, staff

#: A film of ten writer's scenes, each cut into three shots: thirty rows.
BEATS_10x3 = [beat for beat in range(1, 11) for _shot in range(3)]


def _tag_rows(engine, board_id: str, beats: list[int], seconds: float | None = None) -> None:
    """Tag the board's rows with the writer's scene each was cut from, as the montage does."""
    with Session(engine) as session, session.begin():
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        assert len(rows) == len(beats)
        for row, beat in zip(rows, beats, strict=True):
            shot = sum(1 for earlier in beats[: row.scene_index] if earlier == beat)
            row.prompt_json = {"beat": beat_tag(beat, shot, beats.count(beat), None)}
            if seconds is not None:
                row.duration_seconds = seconds


def _picked_frames(asked: dict):
    """The encoder, faked: one frame per row it is asked for. Asked for no rows in particular,
    it does what the encoder did before the montage review: the first MAX_FRAMES rows."""

    def frames(path, ffmpeg_path, duration, scene_seconds=None, picks=None):
        asked["picks"] = None if picks is None else list(picks)
        rows = list(range(len(scene_seconds or [])))[:MAX_FRAMES] if picks is None else picks
        return [base64.b64encode(f"frame {row}".encode()).decode() for row in rows]

    return frames


# ------------------------------------------------------------------ the frames, spread (#5)


def test_one_frame_per_writers_scene_spread_over_the_film_with_its_payoff():
    rows = [beat for beat in range(1, 31) for _shot in range(3)]  # 90 rows, 30 scenes
    picks = frame_picks(rows)

    assert len(picks) == MAX_FRAMES
    assert picks == sorted(set(picks))
    # The last row is the payoff, always shown; the first writer's scene opens the look.
    assert picks[-1] == len(rows) - 1
    assert rows[picks[0]] == 1
    # One row per writer's scene, evenly over the film: never two of one scene, no long gap.
    seen = [rows[position] for position in picks]
    assert len(set(seen)) == MAX_FRAMES
    assert max(b - a for a, b in zip(seen, seen[1:], strict=False)) <= 5


def test_fewer_writers_scenes_than_frames_show_each_and_spread_the_rest():
    rows = [beat for beat in range(1, 5) for _shot in range(3)]  # 12 rows, 4 scenes
    picks = frame_picks(rows)

    assert len(picks) == MAX_FRAMES and picks[-1] == 11
    assert {rows[position] for position in picks} == {1, 2, 3, 4}
    # A film that fits is shown whole; rows the montage did not cut are scenes of their own.
    assert frame_picks([None] * 5) == [0, 1, 2, 3, 4]
    uncut = frame_picks([None] * 12)
    assert len(uncut) == MAX_FRAMES and uncut[0] == 0 and uncut[-1] == 11


def test_the_encoder_cuts_each_picked_row_where_it_plays(tmp_path, monkeypatch):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not decoded: the encoder is faked")
    moments: list[float] = []

    def encoder(args, **_kwargs):
        moments.append(float(args[args.index("-ss") + 1]))
        return subprocess.CompletedProcess(args, 0, stdout=b"jpeg", stderr=b"")

    monkeypatch.setattr("app.agents.editorial.find_ffmpeg", lambda _path: "ffmpeg")
    monkeypatch.setattr("app.agents.editorial.subprocess.run", encoder)
    rows = [beat for beat in range(1, 13) for _shot in range(3)]  # 36 rows of 4 s: 144 s

    frames = frames_for(str(film), None, 144.0, [4.0] * 36, picks=frame_picks(rows))

    assert len(frames) == MAX_FRAMES
    assert moments[0] == pytest.approx(6.0)  # the middle of the first scene's middle shot
    assert moments[-1] == pytest.approx(142.0)  # the middle of the last row: the payoff
    moments.clear()
    # Asked for no rows in particular, the frames still reach the end of the film.
    frames_for(str(film), None, 144.0, [4.0] * 36)
    assert len(moments) == MAX_FRAMES and moments[-1] == pytest.approx(142.0)


def test_the_film_look_judges_rows_from_the_whole_film(engine, monkeypatch):
    staffed_ = staff(engine)
    ids = a_picture_film(
        engine,
        scenes=[
            {"picture": f"Shot {index} of the story", "narration": f"Line {index}."}
            for index in range(1, 31)
        ],
        title="Thirty shots",
    )
    _tag_rows(engine, ids["board"], BEATS_10x3)
    give_vision(engine, staffed_["agents"]["VideoEditor"].id)
    asked: dict = {}
    monkeypatch.setattr("app.media.picture_qc.frames_for", _picked_frames(asked))
    everything = json.dumps({"scenes": [scene_answer(i) for i in range(1, 31)], "characters": []})
    registry, _model = registry_with(staffed_, lambda _prompt: everything)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    measured = [
        entry["scene"] for entry in result["picture_qc"]["scenes"] if entry["status"] == "MEASURED"
    ]
    assert len(measured) == MAX_FRAMES
    assert measured[-1] == 30, "the payoff was not looked at"
    assert len({BEATS_10x3[scene - 1] for scene in measured}) == MAX_FRAMES
    assert asked["picks"] == frame_picks(BEATS_10x3)


def test_the_directors_viewing_sees_the_payoff_and_is_told_which_scenes(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    monkeypatch,
):
    ids = an_editorial_film(engine, voiceover=ENGLISH, with_source=True)
    with Session(engine) as session, session.begin():
        session.execute(
            delete(StoryboardScene).where(StoryboardScene.storyboard_id == ids["board"])
        )
        for index in range(1, 31):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=f"Shot {index} of the telescope's story",
                    visual_type="GENERATED_IMAGE",
                    duration_seconds=4.0,
                    voiceover_segment=ENGLISH[:60],
                    created_at=utc_now(),
                )
            )
    _tag_rows(engine, ids["board"], BEATS_10x3)
    monkeypatch.setattr("app.agents.editorial.model_can_see", lambda _session, _agent: True)
    asked: dict = {}
    monkeypatch.setattr("app.agents.editorial.frames_for", _picked_frames(asked))
    approve = json.dumps(
        {"verdict": "APPROVE", "story": "A telescope finds water.", "reasons": [], "notes_for": {}}
    )
    registry, model = editorial_registry(staffed, lambda _prompt: approve)

    result = editorial_review(engine, registry, ids["asset"], language="en")

    picks = frame_picks(BEATS_10x3)
    assert result["frames_seen"] == MAX_FRAMES
    assert asked["picks"] == picks and picks[-1] == 29
    prompt = model.calls[0]["prompt"]
    named = ", ".join(str(position + 1) for position in picks)
    assert f"(the middle of scenes {named}, in that order)" in prompt
    assert '"writer_scene": 10' in prompt


# ------------------------------------------------------ her QC decision, sized (#4)


def _long_report(findings: int, scenes: int) -> dict:
    """A failed report on a montage film: one picture finding per row, as a systemic problem
    writes it."""
    return {
        "film": {"title": "Ninety shots", "report_id": "test-report"},
        "findings": [
            {
                "id": number,
                "text": f"Scena {(number - 1) % scenes + 1}: the picture is not what it asked for",
                "check": "picture_qc",
                "scene_index": (number - 1) % scenes + 1,
            }
            for number in range(1, findings + 1)
        ],
        "scenes": [
            {"scene_index": index, "kind": "LIVE", "paid_redos_left": 1}
            for index in range(1, scenes + 1)
        ],
    }


def test_her_answer_holds_every_finding_and_every_redo_of_a_long_report():
    findings, scenes = 120, 45
    schema = decision_schema(set(range(1, findings + 1)), set(range(1, scenes + 1)))
    verdicts = [
        {
            "finding": number,
            "verdict": "REAL",
            "reason": "the shot shows another room",
            "severity": "serious",
            "cause": "the still prompt named no room",
            "lesson": "Name the room before the subject in every still prompt.",
        }
        for number in range(1, 41)
    ] + [
        {"finding": number, "verdict": "FALSE", "reason": "the studio's own captions"}
        for number in range(41, findings + 1)
    ]
    repairs = [
        {"scene_index": scene, "redo": "still", "reason": "a new still of the room"}
        for scene in range(1, 41)
    ]
    data = {"verdicts": verdicts, "decision": "REPAIR", "repairs": repairs, "summary": "Refac."}

    decided = schema.model_validate(data)
    parsed, why = read_structured(json.dumps(data), schema)

    assert len(decided.verdicts) == findings and len(decided.repairs) == 40
    assert parsed is not None, why
    assert qc_answer_caps(findings, scenes) == (findings, 3 * scenes + 2)
    # A short report keeps the caps it always had.
    assert qc_answer_caps(3, 2) == (QC_MIN_VERDICTS, QC_MIN_REPAIRS)


def test_she_is_asked_to_judge_every_finding_of_a_report_past_eighty(
    engine,
    studio,  # noqa: F811 - the fixture, imported
):
    findings, scenes = 100, 40
    context = _long_report(findings, scenes)

    def every_finding_false(prompt: str) -> str:
        judged = _context_of(prompt)["findings"]
        return answer(
            [{"finding": item["id"], "verdict": "FALSE", "reason": "misread"} for item in judged],
            "ACCEPT",
            summary="Filmul este bun.",
        )

    registry, model = director_says(studio, every_finding_false)

    result = review_film_qc(engine, registry, context)

    assert result["decision"] == "ACCEPT" and len(result["verdicts"]) == findings
    prompt = model.asked[0]
    assert "at most 80 findings" not in prompt
    assert f"Judge all {findings} findings, one verdict each" in prompt
    assert f"list at most {3 * scenes + 2} repairs" in prompt
    with Session(engine) as session:
        run = session.get(AgentRun, result["run_id"])
        limits = run.context_json["generation_limits"]
    assert limits["requested_max_tokens"] == director_qc_tokens(findings) == 7500


# ------------------------------------------------ the guesses, by the row they are on (#7)


@pytest.mark.montage
def test_a_guessed_name_is_recorded_on_every_shot_of_its_writers_scene(engine):
    long = (
        "There is one web address on earth that nobody is allowed to buy, and every registrar "
        "refuses it the moment you type it in. The address was reserved long before the web "
        "grew up, set aside by the registry itself, and that old reservation still holds: the "
        "address cannot be registered by anyone, however much they offer."
    )
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    topic_id = a_topic(engine)
    script_id = a_script(
        engine,
        topic_id,
        scenes=[
            {
                "scene_number": 1,
                "purpose": "HOOK",
                "narration": long,
                "visual_description": "A brass cyclotron the size of a hand on a wooden bench.",
                "claim_ids": ["c1"],
            },
            {
                "scene_number": 2,
                "purpose": "SETUP",
                "narration": long,
                "visual_description": "Lyra, the constellation, rises over the ridge",
                "claim_ids": ["c2"],
            },
        ],
        story=GOOD_STORY,
    )
    a_passed_review(engine, script_id)

    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        )
        lyra = session.scalar(
            select(CharacterBible.id).where(CharacterBible.canonical_name == "Lyra Voice Artist")
        )
        record = storyboard_cast_record(session, board["id"])
    assert len(rows) == 6
    second = [
        str(row.scene_index) for row in rows if (row.prompt_json or {})["beat"]["scene_number"] == 2
    ]
    assert second == ["4", "5", "6"]
    assert record["guessed"] == {index: [lyra] for index in second}


def test_a_montage_board_keyed_by_the_writers_scenes_names_no_shot(engine):
    board_id = str(uuid4())
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.storyboard_created",
            "storyboard",
            board_id,
            1,
            {"scene_count": 2, "shot_count": 6, "guessed_cast": {"2": ["someone"]}},
            str(uuid4()),
        )
    with Session(engine) as session:
        legacy = storyboard_cast_record(session, board_id)

    # Its «2» is the writer's second scene, rows 4-6, not row 2: no record, never a wrong one.
    assert legacy["guessed"] == {}

    keyed = str(uuid4())
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.storyboard_created",
            "storyboard",
            keyed,
            1,
            {
                "scene_count": 2,
                "shot_count": 6,
                "guessed_cast": {"4": ["someone"]},
                "guessed_cast_keys": GUESSED_CAST_BY_ROW,
            },
            str(uuid4()),
        )
    with Session(engine) as session:
        assert storyboard_cast_record(session, keyed)["guessed"] == {"4": ["someone"]}
