"""A clip as long as the words it carries (WP10, the Owner's «Încetinește local», 2026-10-09).

Film babcf272 «The Particle That Shouldn't Exist (But Does)»: the sheet bought every clip at its
PLANNED seconds before a word was voiced. FILM_CONTINUE then bought the narration (18:22 UTC) and
scene 3's words measured 6.06 s (the vendor's length; 5.991 s once its silence was trimmed)
against its 5.0 s clip: its 6.0 s shot span was longer than the clip,
`_usable_motion_take(min_seconds=span)` found nothing, and the assembly was refused four times
while the sheet said «Pregătit». babcf272's joins are all hard cuts, so with this package its
scene 3 is slowed 20% at 0 USD (`test_babcf272_as_it_is_assembles_with_scene_3_slowed_20_percent`).
The other tests use its numbers with a dissolve into scene 4 (the spec's "6.46 s, 29% short"),
which puts scene 3 past the 25% a clip may be slowed. The Owner's answer:

- (1) prevention: a clip is bought as long as the narration it will carry (measured when its take
  exists, else estimated from its words at the studio's measured speaking rate), plus the breath,
  the dissolve and a margin, rounded up to a length its model accepts; a scene planned longer
  keeps its plan, and a bought take is never orphaned by a new length;
- (2) self-repair at 0 USD: a clip short of its span by at most 25% is slowed down locally
  (interpolated frames, never a frozen frame) and the film records it;
- (3) beyond 25% the assembly is refused, recorded (media.assembly_refused) and the studio raises
  the paid motion redo at the right length through `redo_scene`, unasked, so his paid-media rule
  asks him; nothing is bought without his yes;
- (4) the sheet, the pre-check and the render read one readiness, so the sheet never says
  «Pregătit» when the render refuses.

Every provider is faked; no socket is opened and no credit is spent.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import subprocess
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media.assembler import (
    ASSEMBLY_REFUSED_EVENT,
    CLIP_REDO_PROPOSED_EVENT,
    CLIP_SHORT,
    NARRATION_ESTIMATED,
    NARRATION_KIND,
    NARRATION_MEASURED,
    NARRATION_PLANNED,
    NARRATION_RENDERED,
    SECONDS_PER_SPOKEN_WORD,
    SLOWDOWN_ALLOWANCE,
    ClipsNotAccepted,
    _shot_command,
    _sidecar,
    _text_sha,
    assemble_from_takes,
    assembly_readiness,
    clip_fits,
    clip_plan,
    clip_short_words,
    clip_stretch,
    estimated_narration_seconds,
    expected_shot_spans,
    min_clip_seconds,
    motion_fields,
    motion_plan,
    propose_clip_redos,
    scene_narration_lengths,
    scene_view,
    spoken_words,
    take_hash,
)
from app.media.cost_plan import price_shot
from app.media.models import SceneTake, StoryboardScene, VideoRenderJob
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_assemble_step
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.providers.media_base import TTSResult
from app.services import utc_now
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, Account, Models, SpyVideo
from test_film_costing import a_film as film_with_stills

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

#: babcf272's five narration takes, as ElevenLabs measured them (2026-10-09, 18:22 UTC).
BABCF272_NARRATION = {1: 4.885, 2: 6.06, 3: 6.06, 4: 6.008, 5: 7.732}
#: Where each take's last timed word ends (ElevenLabs' alignment, its first word at 0.0): the
#: length the render measured once each take's silence was trimmed (its audio_seconds).
BABCF272_WORDS_END = {1: 4.83, 2: 5.991, 3: 5.991, 4: 5.944, 5: 7.662}
#: Its scenes' plan (the clip bought at plan + 0.4 s = 5.0 s).
PLANNED = 4.6

# --------------------------------------------------------------------------------- helpers


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def in_environment(engine: Engine, environment: str) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        assert policy is not None
        policy.environment = environment


def a_board(
    engine: Engine, tmp_path: Path, words: list[str], *, dissolve_into: tuple[int, ...] = ()
) -> str:
    """A film of len(words) filmed scenes, each with its approved still and its words; the
    scenes in ``dissolve_into`` are joined from the scene before by a dissolve."""
    storyboard_id = film_with_stills(engine, tmp_path, scenes=len(words))
    with Session(engine) as session, session.begin():
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        for row, text in zip(rows, words, strict=True):
            row.voiceover_segment = text
            row.duration_seconds = PLANNED
            row.transition_in = "DISSOLVE" if row.scene_index in dissolve_into else "CUT"
    return storyboard_id


def scenes_of(engine: Engine, storyboard_id: str) -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        return [scene_view(row) for row in rows]


def still_sha(engine: Engine, storyboard_id: str, index: int) -> str:
    with Session(engine) as session:
        return str(
            session.scalars(
                select(SceneTake.sha256).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == index,
                    SceneTake.kind == "still",
                    SceneTake.status == "APPROVED",
                )
            ).one()
        )


def a_clip(path: Path, seconds: float) -> Path:
    """``seconds`` of real moving h264 at the vendor's 24 fps."""
    subprocess.run(
        [
            str(find_ffmpeg()),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s=270x480:r=24:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def a_shot_take(
    engine: Engine,
    storyboard_id: str,
    index: int,
    seconds: float,
    path: Path,
    *,
    kind: str = "motion",
    status: str = "APPROVED",
) -> str:
    """A bought shot of the scene for its current shot identity (its still, its package),
    billed ``seconds`` long, with its file."""
    scene = next(s for s in scenes_of(engine, storyboard_id) if s["scene_index"] == index)
    fields = motion_fields(scene, still_sha(engine, storyboard_id, index), from_prompt=False)
    if not path.is_file():
        path.write_bytes(f"clip of scene {index}, {path.name}".encode())
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=index,
                kind=kind,
                prompt_hash=take_hash(fields, "seedance2_5"),
                model_id="seedance2_5",
                resolution="1080p",
                status=status,
                approved_by="owner" if status == "APPROVED" else None,
                path=str(path),
                sha256=sha(path),
                seconds=seconds,
                created_at="2026-10-09T17:00:00+00:00",
                updated_at="2026-10-09T17:00:00+00:00",
            )
        )
    return take_id


def a_narration_take(
    engine: Engine,
    storyboard_id: str,
    tmp_path: Path,
    index: int,
    seconds: float,
    *,
    voice_key: str = "voice-1",
    part: int = 0,
    parts: int = 1,
    words_end: float | None = None,
) -> str:
    """The scene's words as they are now, voiced and kept (PAID), ``seconds`` long as the
    vendor measured them; ``words_end``: the vendor's word timing ends there (its first word
    starts at 0.0), as ElevenLabs' alignment does. Part ``part`` of ``parts``, said by
    ``voice_key``. Returns the take's id."""
    scene = next(s for s in scenes_of(engine, storyboard_id) if s["scene_index"] == index)
    folder = tmp_path / "narration"
    folder.mkdir(exist_ok=True)
    path = folder / f"scene_{index:02d}_{part}_{voice_key}.mp3"
    path.write_bytes(b"ID3" + bytes([index, part]) * 64 + voice_key.encode())
    timings = (
        [
            {"word": "First", "start": 0.0, "end": 0.4},
            {"word": "last.", "start": round(words_end - 0.5, 3), "end": words_end},
        ]
        if words_end is not None
        else []
    )
    _sidecar(path).write_text(
        json.dumps(
            {
                "format": "mp3",
                "duration_seconds": seconds,
                "word_timings": timings,
                "scene_text_sha256": _text_sha(str(scene["voiceover_segment"])),
                "voice_key": voice_key,
                "part": part,
                "parts": parts,
            }
        ),
        encoding="utf-8",
    )
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=index,
                kind=NARRATION_KIND,
                prompt_hash=f"narration-{index}-{part}-{voice_key}",
                model_id="eleven_multilingual_v2",
                resolution="mp3",
                status="PAID",
                path=str(path),
                sha256=sha(path),
                seconds=seconds,
                created_at=f"2026-10-09T18:22:{part:02d}+00:00",
                updated_at=f"2026-10-09T18:22:{part:02d}+00:00",
            )
        )
    return take_id


def a_render_record(
    engine: Engine, storyboard_id: str, said: dict[int, tuple[float, list[str]]]
) -> str:
    """A refused render that measured each scene's words (trimmed ``audio_seconds``) from its
    narration takes, as `_fail_job` keeps what was built."""
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="FAILED",
                production_json={
                    "scenes": [
                        {"scene_index": index, "audio_seconds": seconds, "narration_takes": takes}
                        for index, (seconds, takes) in said.items()
                    ]
                },
                started_at="2026-10-09T18:43:58+00:00",
            )
        )
    return job_id


class ToneVoice:
    """The narrator, faked: a steady tone exactly as long as the scene's words were measured
    (by the words it is asked to say). Defined outside the studio's code, so it counts as a
    bought voice and its takes are kept, as ElevenLabs' are."""

    PROVIDER_NAME = "TEST_TONE_VOICE"
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"

    def __init__(self, seconds_by_words: dict[str, float]):
        self.seconds = {" ".join(words.split()): value for words, value in seconds_by_words.items()}
        self.said: list[str] = []

    async def synthesize(self, text: str, **_kwargs: Any) -> TTSResult:
        words = " ".join(text.split())
        self.said.append(words)
        seconds = self.seconds[words]
        rate = 16000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(
                b"".join(
                    int(9000 * math.sin(2 * math.pi * 220 * n / rate)).to_bytes(
                        2, "little", signed=True
                    )
                    for n in range(int(round(seconds * rate)))
                )
            )
        return TTSResult(
            audio_bytes=buffer.getvalue(), format="wav", duration_seconds=seconds, sample_rate=rate
        )


def events(engine: Engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == event_type)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


def approvals(engine: Engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest)))
        session.expunge_all()
        return rows


# ------------------------------------------------------------ the numbers and their words

#: babcf272's words as the five scenes say them; scene 3 ends on «simultaneously.»
WORDS = [
    "In 1964 Peter Higgs wrote two pages nobody wanted.",
    "Physicists needed a field that gives every particle its mass.",
    "Without it, matter would fly apart, everywhere, simultaneously.",
    "For decades the particle hid below every detector's noise.",
    "Then in 2013 it showed itself, and it should not exist.",
]


def test_the_speaking_rate_is_the_one_measured_on_the_studios_own_narration() -> None:
    # 30.745 s for 77 words as `spoken_words` counts them: 0.399 s a word, kept as 0.40.
    assert math.isclose(sum(BABCF272_NARRATION.values()) / 77, 0.399, abs_tol=0.001)
    assert SECONDS_PER_SPOKEN_WORD == 0.40
    # A year is said in three words, a number of one or two digits in one.
    assert spoken_words("In 1964 Peter Higgs") == 6
    assert spoken_words("Two pages, 12 lines.") == 4
    assert spoken_words("") == 0
    assert estimated_narration_seconds("In 1964 Peter Higgs") == 2.4


def test_with_a_dissolve_into_scene_4_scene_3_is_29_percent_short_and_a_59_s_span_is_slowed() -> (
    None
):
    planned: list[dict[str, Any]] = [
        {"scene_index": n, "duration_seconds": PLANNED} for n in range(1, 6)
    ]
    planned[3]["transition_in"] = "DISSOLVE"  # scene 4 dissolves in: scene 3's shot covers it
    lengths = {n: (said, NARRATION_RENDERED) for n, said in BABCF272_NARRATION.items()}
    spans = expected_shot_spans(planned, lengths)
    # 6.06 s of words, no breath past the plan, on whole frames, plus the 8-frame dissolve.
    assert math.isclose(spans[3], 146 / 24 + 8 / 24)
    assert not clip_fits(5.0, spans[3])
    assert math.isclose(min_clip_seconds(spans[3]), spans[3] / (1 + SLOWDOWN_ALLOWANCE))
    words = clip_short_words(3, 5.0, spans[3])
    assert "ar trebui încetinit cu 29%, peste cele 25%" in words
    assert "Mișcarea scenei se reface la cel puțin 6,42 s." in words
    # A 5.0 s clip under a 5.9 s span is slowed 18%; one that covers its span is cut.
    assert clip_fits(5.0, 5.9) and math.isclose(clip_stretch(5.0, 5.9), 1.18)
    assert clip_stretch(7.0, 6.04) == 1.0 and clip_stretch(None, 6.0) == 1.0


def test_a_slowed_shot_is_interpolated_never_held_on_a_frozen_frame() -> None:
    args = _shot_command(
        "ffmpeg",
        Path("still.png"),
        Path("motion_03.mp4"),
        5.9,
        Path("shot.mp4"),
        slow=144 / 120,
        interpolate="minterpolate",
    )
    chain = args[args.index("-vf") + 1]
    assert "setpts=PTS*1.200000,minterpolate=fps=24:mi_mode=mci" in chain
    assert "tpad" not in chain and chain.index("minterpolate") < chain.index("trim=end_frame=142")
    blended = _shot_command(
        "ffmpeg", Path("s.png"), Path("m.mp4"), 5.9, Path("o.mp4"), slow=1.2, interpolate="x"
    )
    assert "framerate=fps=24" in blended[blended.index("-vf") + 1]
    cut = _shot_command("ffmpeg", Path("s.png"), Path("m.mp4"), 5.9, Path("o.mp4"))
    assert "setpts=PTS*" not in cut[cut.index("-vf") + 1]


# ------------------------------------------------------------- (1) prevention: the plan


def test_before_a_word_is_voiced_each_clip_is_bought_as_long_as_its_estimated_words(
    engine: Engine, tmp_path: Path
) -> None:
    long_words = " ".join(["word"] * 20)  # 20 words: 8.0 s estimated
    storyboard_id = a_board(engine, tmp_path, [long_words, "Scene two.", "Scene three."])
    with Session(engine) as session, session.begin():
        # Scene 3 is planned longer than its words: it keeps its plan.
        session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        ).one().duration_seconds = 9.0
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        sizes = clip_plan(session, storyboard_id, scenes)
    # 8.0 s of words + 0.12 s breath + 10% margin, on whole frames.
    assert sizes[1]["source"] == NARRATION_ESTIMATED and sizes[1]["spoken_seconds"] == 8.0
    assert sizes[1]["seconds"] == round(math.ceil((8.0 + 0.12 + 0.8) * 24) / 24, 3)
    assert sizes[2] == {
        "seconds": 5.0,
        "planned_seconds": 5.0,
        "spoken_seconds": 0.8,
        "source": NARRATION_PLANNED,
    }
    assert sizes[3]["seconds"] == 9.4 and sizes[3]["source"] == NARRATION_PLANNED

    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    by_scene = {item["scene_index"]: item for item in plan["scenes"]}
    # Rounded up to a length the model's contract accepts (seedance2_5: whole seconds 4-30),
    # and priced at that length: the cost the Owner reads is the clip that will be bought.
    assert [by_scene[n]["billed_seconds"] for n in (1, 2, 3)] == [9, 5, 10]
    assert by_scene[1]["credits"] == price_shot("seedance2_5", "1080p", 9)
    assert by_scene[1]["seconds_source"] == NARRATION_ESTIMATED

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    first = sheet["scenes"][0]
    assert first["shot_seconds"] == sizes[1]["seconds"]
    assert first["shot_seconds_source"] == NARRATION_ESTIMATED
    assert first["motion"]["billed_seconds"] == 9


def test_measured_words_size_the_clip_and_never_orphan_a_take_already_bought(
    engine: Engine, tmp_path: Path
) -> None:
    storyboard_id = a_board(engine, tmp_path, WORDS[:2], dissolve_into=(2,))
    a_narration_take(engine, storyboard_id, tmp_path, 1, 6.06)
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        assert scene_narration_lengths(session, storyboard_id, scenes)[1] == (
            6.06,
            NARRATION_MEASURED,
        )
        sizes = clip_plan(session, storyboard_id, scenes)
    # 6.06 s + breath + the dissolve into scene 2 + two frames: 6.597 s on whole frames.
    assert sizes[1]["source"] == NARRATION_MEASURED
    assert sizes[1]["seconds"] == round(math.ceil((6.06 + 0.12 + 8 / 24 + 2 / 24) * 24) / 24, 3)
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert next(i for i in plan["scenes"] if i["scene_index"] == 1)["billed_seconds"] == 7

    # The 5.0 s shot bought on the old plan stays the scene's shot: a length is no part of a
    # shot's identity, so a new size (or new words) never orphans what was paid for.
    take_id = a_shot_take(engine, storyboard_id, 1, 5.0, tmp_path / "s1.mp4")
    before = take_hash(
        motion_fields(scenes[0], still_sha(engine, storyboard_id, 1), from_prompt=False), "m"
    )
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        ).one()
        row.voiceover_segment = "New words, said again, longer than before, by the narrator."
        # A recompiled still prompt (the panels rule) keeps the shot's motion package.
        package = dict(row.prompt_json or {})
        package["still_prompt"] = str(package["still_prompt"]) + " One moment."
        row.prompt_json = package
    moved = scenes_of(engine, storyboard_id)[0]
    after = take_hash(
        motion_fields(moved, still_sha(engine, storyboard_id, 1), from_prompt=False), "m"
    )
    assert before == after
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    first = next(i for i in plan["scenes"] if i["scene_index"] == 1)
    assert first["status"] == "BOUGHT" and first["take_id"] == take_id
    assert 1 not in plan["steps"]["motion"]["to_buy"] + plan["steps"]["test_shot"]["to_buy"]


# --------------------------------------- (3)(4) one readiness; a refusal raises the redo


def babcf272_like(engine: Engine, tmp_path: Path) -> str:
    """Scenes 1-4 with babcf272's narration takes (the vendor's lengths, and its word timing:
    scene 3's words end at 5.991 s) and its bought clips: scene 3's 5.0 s clip under 6.06 s of
    words, and (unlike babcf272, whose joins are hard cuts) scene 4 dissolving in, which puts
    scene 3 29% short, and 27% even at its trimmed length: certain before any render."""
    storyboard_id = a_board(engine, tmp_path, WORDS[:4], dissolve_into=(4,))
    for index, seconds in ((1, 5.0), (2, 6.0), (3, 5.0), (4, 7.0)):
        a_shot_take(engine, storyboard_id, index, seconds, tmp_path / f"shot_{index}.mp4")
        a_narration_take(
            engine,
            storyboard_id,
            tmp_path,
            index,
            BABCF272_NARRATION[index],
            words_end=BABCF272_WORDS_END[index],
        )
    return storyboard_id


def test_the_sheet_is_not_ready_while_scene_3_is_too_short_for_its_measured_words(
    engine: Engine, tmp_path: Path
) -> None:
    storyboard_id = babcf272_like(engine, tmp_path)
    in_environment(engine, "PRODUCTION")
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        readings = {
            item["scene_index"]: item
            for item in assembly_readiness(
                session,
                storyboard_id,
                scenes,
                {n: still_sha(engine, storyboard_id, n) for n in (1, 2, 3, 4)},
                environment="PRODUCTION",
                local_moves=set(),
            )
        }
    assert readings[3]["ok"] is False and readings[3]["code"] == CLIP_SHORT
    assert readings[3]["clip_seconds"] == 5.0 and readings[3]["span_source"] == NARRATION_MEASURED
    assert math.isclose(readings[3]["span"], round(146 / 24 + 8 / 24, 3))
    assert readings[1]["how"] == "shot" and readings[4]["how"] == "shot"
    # Scene 2's 6.0 s clip under 6.06 s of words is slowed 1.4%, at 0 USD.
    assert readings[2]["how"] == "slowed" and "0 USD" in readings[2]["reason_ro"]

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    step = sheet["steps"]["assemble"]
    assert step["ready"] is False
    (blocked,) = step["blocked"]
    assert blocked["scene_index"] == 3 and blocked["code"] == CLIP_SHORT
    assert "29%" in step["blocked_ro"] and step["blocked_ro"].count("Scena 3: clipul are") == 1
    assert any("se încetinește local" in note for note in step["notes_ro"])

    # His press refuses before a word is bought again, and the refusal is recorded.
    with pytest.raises(SheetStepRefused) as refused:
        run_assemble_step(
            engine,
            storyboard_id,
            sheet["sheet_hash"],
            correlation_id="press-1",
            capabilities=[SEEDANCE],
            environment="PRODUCTION",
            storage_root=tmp_path / "media",
        )
    assert refused.value.status == "TAKES_NOT_ACCEPTED"
    (event,) = events(engine, ASSEMBLY_REFUSED_EVENT)
    assert event.payload["stage"] == "sheet"
    (scene,) = event.payload["scenes"]
    assert scene["scene_index"] == 3 and scene["code"] == CLIP_SHORT
    assert scene["clip_seconds"] == 5.0 and scene["span"] == readings[3]["span"]
    with Session(engine) as session:
        assert session.scalars(select(VideoRenderJob)).all() == []


def wiring(tmp_path: Path, models: Models, account: Account) -> dict[str, Any]:
    return {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "adapter_for_model": models,
        "account": account,
        "image_adapter": None,
        "resolution": None,
        "storage_root": tmp_path / "media",
    }


def test_a_refused_scene_gets_its_paid_redo_at_the_right_length_asked_never_bought(
    engine: Engine, settings: Any, tmp_path: Path
) -> None:
    storyboard_id = babcf272_like(engine, tmp_path)
    in_environment(engine, "PRODUCTION")
    account = Account(5000)
    models = Models(SpyVideo("seedance2_5", account))
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    with pytest.raises(SheetStepRefused) as refused:
        run_assemble_step(
            engine,
            storyboard_id,
            sheet["sheet_hash"],
            correlation_id="press-1",
            capabilities=[SEEDANCE],
            settings=settings,
            environment="PRODUCTION",
            storage_root=tmp_path / "media",
            redo_wiring=wiring(tmp_path, models, account),
        )
    (scene,) = refused.value.scenes
    redo = scene["redo"]
    # The studio raised the redo itself, under his paid-media rule: his question waits.
    assert redo["status"] == "NEEDS_APPROVAL", redo
    # Sized to the words it will carry: 6.06 s + breath + dissolve + two frames -> 7 s.
    assert redo["billed_seconds"] == 7
    assert models.posts() == 0 and account.shots == 0, "a proposal bought a clip"
    (question,) = [row for row in approvals(engine) if row.action == "media.scene_redo"]
    assert question.id == redo["approval_id"]
    # His question says why, with the seconds, and the length the redo buys.
    assert "ar trebui încetinit cu 29%" in str(question.evidence)
    assert "Studioul propune refacerea mișcării la 7 s." in str(question.evidence)
    (proposed,) = events(engine, CLIP_REDO_PROPOSED_EVENT)
    assert proposed.payload["scene_index"] == 3 and proposed.payload["billed_seconds"] == 7

    # Raised again (the next FILM_CONTINUE, his next press): the same question, not a second.
    again = propose_clip_redos(
        engine,
        storyboard_id,
        "continue-2",
        wiring=wiring(tmp_path, models, account),
        settings=settings,
        environment="PRODUCTION",
    )
    assert [outcome["status"] for outcome in again] == ["NEEDS_APPROVAL"]
    assert again[0]["approval_id"] == question.id
    assert len([row for row in approvals(engine) if row.action == "media.scene_redo"]) == 1
    assert models.posts() == 0

    # Once a clip long enough was bought after the refusal, nothing is raised again: the next
    # assembly reads that clip.
    longer = a_shot_take(engine, storyboard_id, 3, 7.0, tmp_path / "redo_3.mp4", status="PAID")
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, longer)
        assert row is not None
        row.created_at = row.updated_at = utc_now()
    assert (
        propose_clip_redos(
            engine,
            storyboard_id,
            "continue-3",
            wiring=wiring(tmp_path, models, account),
            settings=settings,
            environment="PRODUCTION",
        )
        == []
    )


# --------------------------------------------------- the render, with real ffmpeg and voice


@requires_ffmpeg
def test_a_5_s_clip_under_a_59_s_span_is_slowed_locally_and_the_film_is_assembled(
    engine: Engine, settings: Any, tmp_path: Path
) -> None:
    words = "A field that gives every particle its mass."
    storyboard_id = a_board(engine, tmp_path, [words])
    in_environment(engine, "PRODUCTION")
    take_id = a_shot_take(engine, storyboard_id, 1, 5.0, a_clip(tmp_path / "motion.mp4", 5.0))

    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        tts_adapter=ToneVoice({words: 5.9}),
        environment="PRODUCTION",
        settings=settings,
    )

    production = film["production"]
    (entry,) = [e for e in production["scenes"] if e["scene_index"] == 1]
    motion = entry["motion"]
    span = 142 / 24  # 5.9 s of words on whole frames
    assert motion["take_id"] == take_id and motion["reused_take"] is True
    assert motion["from_seconds"] == 5.0 and motion["to_seconds"] == round(span, 3)
    assert math.isclose(motion["slowed_by"], round(span / 5.0, 4))
    (slowed,) = production["slowed_scenes"]
    assert slowed["scene_index"] == 1 and "0 USD" in slowed["words_ro"]
    assert slowed["words_ro"] in production["owner_warnings"]
    (shot,) = production["shots"]
    assert shot["source"]["slow"] > 1.0 and shot["source"]["hold"] == 0.0
    assert shot["source"]["interpolate"] in ("minterpolate", "framerate")
    assert production["fallback_gate"]["owner_chosen"] == []
    with Session(engine) as session:
        job = session.get(VideoRenderJob, film["job_id"])
        assert job is not None and job.status == "COMPLETED"
        assert "tpad" not in json.dumps(job.command_args_json)

    # The sheet reads the same: ready, and it says the clip is slowed at 0 USD.
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert sheet["steps"]["assemble"]["ready"] is True
    assert any("se încetinește local" in note for note in sheet["steps"]["assemble"]["notes_ro"])


@requires_ffmpeg
def test_a_slowed_shot_whose_interpolation_crashes_is_blended_and_the_film_still_made(
    engine: Engine, settings: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    """2026-10-10, babcf272 scene 3 live: minterpolate died in this encoder build after 1.5 s
    (exit 3221225477, an access violation, nothing on stderr) and the whole film was refused
    for a filter the shot did not need. The shot is built again blended (framerate)."""
    import subprocess

    from app.media import assembler

    real = assembler.run_encoder
    crashed: list[str] = []

    def encoder(command, folder, **kwargs):
        if any("minterpolate" in str(part) for part in command):
            crashed.append(str(command[-1]))
            return subprocess.CompletedProcess(list(command), 3221225477, "", "Stream mapping:")
        return real(command, folder, **kwargs)

    monkeypatch.setattr(assembler, "run_encoder", encoder)
    monkeypatch.setattr(assembler, "slowdown_filter", lambda _ffmpeg: "minterpolate")
    words = "A field that gives every particle its mass."
    storyboard_id = a_board(engine, tmp_path, [words])
    in_environment(engine, "PRODUCTION")
    a_shot_take(engine, storyboard_id, 1, 5.0, a_clip(tmp_path / "motion.mp4", 5.0))

    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        tts_adapter=ToneVoice({words: 5.9}),
        environment="PRODUCTION",
        settings=settings,
    )

    assert crashed, "the best interpolation was tried first"
    (shot,) = film["production"]["shots"]
    assert shot["source"]["slow"] > 1.0
    assert shot["source"]["interpolate"] == "framerate", "a redo rebuilds it the way it was made"
    with Session(engine) as session:
        assert session.get(VideoRenderJob, film["job_id"]).status == "COMPLETED"


@requires_ffmpeg
def test_measured_at_the_render_scene_3_is_refused_recorded_and_the_sheet_agrees(
    engine: Engine, settings: Any, tmp_path: Path
) -> None:
    """FILM_CONTINUE's path: nothing voiced yet, so the pre-check reads estimates (scene 3's
    eight words fit its clip) and lets the narration be bought; the render measures 6.06 s,
    with the dissolve into scene 4 refuses scene 3 and records why. From then on the sheet,
    which reads the same measured words, is not ready either."""
    storyboard_id = a_board(engine, tmp_path, WORDS[:4], dissolve_into=(4,))
    in_environment(engine, "PRODUCTION")
    for index, seconds in ((1, 5.0), (2, 6.0), (3, 5.0), (4, 7.0)):
        a_shot_take(
            engine, storyboard_id, index, seconds, a_clip(tmp_path / f"m{index}.mp4", seconds)
        )
    voice = ToneVoice({WORDS[n - 1]: BABCF272_NARRATION[n] for n in (1, 2, 3, 4)})
    before = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert before["steps"]["assemble"]["ready"] is True  # nothing voiced: words estimated

    with pytest.raises(ClipsNotAccepted) as refused:
        assemble_from_takes(
            engine,
            storyboard_id,
            "continue-1",
            storage_root=tmp_path / "media",
            tts_adapter=voice,
            environment="PRODUCTION",
            settings=settings,
        )

    assert refused.value.scenes == [3]
    assert "29%" in refused.value.message_ro
    (event,) = events(engine, ASSEMBLY_REFUSED_EVENT)
    assert event.payload["stage"] == "render" and event.payload["job_id"]
    (scene,) = event.payload["scenes"]
    assert scene["code"] == CLIP_SHORT and scene["clip_seconds"] == 5.0
    assert scene["span"] > 6.3 and scene["needed_seconds"] > 5.0
    assert len(voice.said) == 4

    after = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    step = after["steps"]["assemble"]
    assert step["ready"] is False and [b["scene_index"] for b in step["blocked"]] == [3]
    assert step["last_refusal"]["stage"] == "render"
    reading = next(item for item in step["scenes"] if item["scene_index"] == 3)
    assert reading["span_source"] == NARRATION_RENDERED
    # The redo the sheet's «Refă mișcarea» offers (`redo_plan`) is the right length: 7 s
    # (6.06 s of words, the breath, the dissolve, two frames), not the plan's 5.
    from app.media.assembler import redo_plan

    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert plan["billed_seconds"] == 7 and plan["buyable"] is True


# ---------------------------------------- the review of 2026-10-10: one reading, every case

#: babcf272 as the database holds it (a read-only copy, 2026-10-10 09:40): its words, its plans,
#: every join a hard cut; each narration take's vendor length (BABCF272_NARRATION) and where
#: its last timed word ends, which is what the render measured once the silence was trimmed
#: (its newest render's audio_seconds: 4.83, 5.991, 5.991, 5.944, 7.662).
BABCF272_TEXT = {
    1: "Physicists spent fifty years chasing a particle that was mathematically invisible.",
    2: "The Higgs mechanism explains how matter acquires mass. Without it, nothing has mass.",
    3: "In 1964, three separate teams published the same theory simultaneously.",
    4: "But theory needed proof, so in 2013, CERN announced results consistent with the "
    "Higgs particle.",
    5: "Without this particle, atoms couldn’t hold together and you wouldn’t exist. "
    "It took the biggest machine ever built to prove why anything has mass.",
}
BABCF272_PLANS = {1: 4.4, 2: 5.2, 3: 4.0, 4: 6.0, 5: 9.0}
#: Its shots: (billed seconds, kind, status). Scene 5's PAID clip passed its clip QC.
BABCF272_SHOTS = {
    1: (5.0, "motion", "APPROVED"),
    2: (6.0, "test_shot", "APPROVED"),
    3: (5.0, "motion", "APPROVED"),
    4: (7.0, "motion", "APPROVED"),
    5: (10.0, "motion", "PAID"),
}


def a_passing_clip_qc(engine: Engine, take_id: str) -> None:
    from app.media.assembler import CLIP_QC_EVENT
    from app.services import append_event

    with Session(engine) as session, session.begin():
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            take_id,
            1,
            {"take_id": take_id, "verdict": "PASSED", "passed": True, "blocks_ro": []},
            "clip-qc",
        )


def babcf272_as_it_is(engine: Engine, tmp_path: Path, *, rendered: bool) -> str:
    storyboard_id = film_with_stills(engine, tmp_path, scenes=5)
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            row.voiceover_segment = BABCF272_TEXT[row.scene_index]
            row.duration_seconds = BABCF272_PLANS[row.scene_index]
            row.transition_in = "CUT"
    voiced: dict[int, str] = {}
    for index, (seconds, kind, status) in BABCF272_SHOTS.items():
        shot = a_shot_take(
            engine,
            storyboard_id,
            index,
            seconds,
            tmp_path / f"shot_{index}.mp4",
            kind=kind,
            status=status,
        )
        if status == "PAID":
            a_passing_clip_qc(engine, shot)
        voiced[index] = a_narration_take(
            engine,
            storyboard_id,
            tmp_path,
            index,
            BABCF272_NARRATION[index],
            words_end=BABCF272_WORDS_END[index],
        )
    if rendered:
        a_render_record(
            engine,
            storyboard_id,
            {index: (BABCF272_WORDS_END[index], [voiced[index]]) for index in voiced},
        )
    return storyboard_id


def readiness_of(engine: Engine, storyboard_id: str) -> dict[int, dict[str, Any]]:
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        return {
            item["scene_index"]: item
            for item in assembly_readiness(
                session,
                storyboard_id,
                scenes,
                {
                    int(scene["scene_index"]): still_sha(
                        engine, storyboard_id, int(scene["scene_index"])
                    )
                    for scene in scenes
                },
                environment="PRODUCTION",
                local_moves=set(),
            )
        }


@pytest.mark.parametrize("rendered", [True, False])
def test_babcf272_as_it_is_assembles_with_scene_3_slowed_20_percent(
    engine: Engine, tmp_path: Path, rendered: bool
) -> None:
    """The live film, hard cuts and all: scene 3's 5.0 s clip under 5.991 s of trimmed words
    (a 6.0 s span) is slowed 20% at 0 USD, no redo is raised, and the assembly is ready; read
    from its newest render, or (before any render) from its takes' own lengths."""
    storyboard_id = babcf272_as_it_is(engine, tmp_path, rendered=rendered)
    in_environment(engine, "PRODUCTION")
    readings = readiness_of(engine, storyboard_id)
    assert all(item["ok"] for item in readings.values()), readings
    if rendered:
        assert {n: item["span"] for n, item in readings.items()} == {
            1: 4.833,
            2: 6.0,
            3: 6.0,
            4: 6.0,
            5: 7.792,
        }
        assert {item["span_source"] for item in readings.values()} == {NARRATION_RENDERED}
        assert readings[3]["how"] == "slowed" and readings[3]["slowed_by"] == 1.2
        assert [readings[n]["how"] for n in (1, 2, 4, 5)] == ["shot"] * 4
    else:
        # The vendor's 6.06 s on whole frames: 6.083 s, 22% past scene 3's clip and 1.4%
        # past scene 2's 6.0 s test shot: both slowed.
        assert {item["span_source"] for item in readings.values()} == {NARRATION_MEASURED}
        assert readings[3]["how"] == "slowed" and readings[3]["span"] == 6.083
        assert [readings[n]["how"] for n in (1, 2, 4, 5)] == ["shot", "slowed", "shot", "shot"]
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    step = sheet["steps"]["assemble"]
    assert step["ready"] is True and step["blocked"] == []
    slowed = "Scena 3: clipul de 5,0 s se încetinește local"
    assert any(note.startswith(slowed) for note in step["notes_ro"])


def test_a_scene_said_by_two_voices_is_measured_and_its_redo_covers_both(
    engine: Engine, tmp_path: Path
) -> None:
    """A dialogue scene has one take per speaker, each in its own voice: its narration was
    read as never voiced (ESTIMATED) because no ONE voice said every part, even after a render
    measured it. The sheet said «Pregătit» for a clip the render refuses, and the redo was
    priced at the estimate, below what the render's refusal said the words need."""
    from app.media.assembler import redo_plan

    words = "Ana says the field is everywhere, and Ion asks why nobody has ever seen it."
    storyboard_id = a_board(engine, tmp_path, [words])  # 15 words: 6.0 s estimated
    in_environment(engine, "PRODUCTION")
    a_shot_take(engine, storyboard_id, 1, 5.0, tmp_path / "shot_1.mp4")
    ana = a_narration_take(
        engine, storyboard_id, tmp_path, 1, 3.6, voice_key="ana", part=0, parts=2, words_end=3.5
    )
    ion = a_narration_take(
        engine, storyboard_id, tmp_path, 1, 3.4, voice_key="ion", part=1, parts=2, words_end=3.3
    )
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        seconds, source = scene_narration_lengths(session, storyboard_id, scenes)[1]
    # Both speakers and the gap between them.
    assert source == NARRATION_MEASURED and math.isclose(seconds, 3.6 + 0.3 + 3.4)
    (reading,) = readiness_of(engine, storyboard_id).values()
    # Even its timed words (3.5 + 0.3 + 3.3 = 7.1 s) are 42% past the clip: certain.
    assert reading["ok"] is False and reading["code"] == CLIP_SHORT
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert sheet["steps"]["assemble"]["ready"] is False
    # 7.3 s + breath + two frames -> 7.542 s: 8 whole seconds, never the estimate's 7.
    plan = redo_plan(engine, storyboard_id, "motion", 1, capabilities=[SEEDANCE])
    assert plan["billed_seconds"] == 8

    # Once a render measured the two takes, its trimmed length is the reading.
    a_render_record(engine, storyboard_id, {1: (7.0, [ana, ion])})
    with Session(engine) as session:
        assert scene_narration_lengths(session, storyboard_id, scenes)[1] == (
            7.0,
            NARRATION_RENDERED,
        )
    (reading,) = readiness_of(engine, storyboard_id).values()
    assert reading["code"] == CLIP_SHORT and reading["span_source"] == NARRATION_RENDERED


def test_a_redo_is_never_sized_below_the_span_its_render_refusal_measured(
    engine: Engine, tmp_path: Path
) -> None:
    """When the narration cannot be read back (its takes were not kept), the clip is sized from
    the estimate; a render that refused the scene measured its span, and the redo is never
    bought shorter than that span for the same words."""
    from app.media.assembler import NARRATION_REFUSED, record_assembly_refused, redo_plan

    words = "Ana says the field is everywhere, and Ion asks why nobody has ever seen it."
    storyboard_id = a_board(engine, tmp_path, [words])
    in_environment(engine, "PRODUCTION")
    a_shot_take(engine, storyboard_id, 1, 5.0, tmp_path / "shot_1.mp4")
    record_assembly_refused(
        engine,
        storyboard_id,
        "continue-1",
        ClipsNotAccepted(
            [1],
            "Scena 1: clipul are 5,0 s, iar cadrul lui cere 7,33 s.",
            details=[
                {
                    "scene_index": 1,
                    "code": CLIP_SHORT,
                    "clip_seconds": 5.0,
                    "span": 7.333,
                    "needed_seconds": 5.867,
                }
            ],
        ),
        stage="render",
        environment="PRODUCTION",
        job_id="job-1",
    )
    scenes = scenes_of(engine, storyboard_id)
    with Session(engine) as session:
        size = clip_plan(session, storyboard_id, scenes)[1]
    # The estimate (6.0 s + breath + 10%) would buy 6.75 s; the render measured 7.333 s.
    assert size["source"] == NARRATION_REFUSED
    assert size["seconds"] == round(math.ceil((7.333 + 2 / 24) * 24 - 1e-6) / 24, 3)
    plan = redo_plan(engine, storyboard_id, "motion", 1, capabilities=[SEEDANCE])
    assert plan["billed_seconds"] == 8

    # New words are new narration: the old refusal's span no longer sizes the clip.
    with Session(engine) as session, session.begin():
        session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ).one().voiceover_segment = "Short words now."
    with Session(engine) as session:
        moved = clip_plan(session, storyboard_id, scenes_of(engine, storyboard_id))[1]
    assert moved["source"] == NARRATION_PLANNED


def test_words_not_voiced_yet_refuse_only_a_clip_no_voice_could_fit_and_promise_no_slowdown(
    engine: Engine, tmp_path: Path
) -> None:
    """Before a word is voiced the span is an estimate. A clip short of it past the 25% a clip
    may be slowed was read as ready AND «se încetinește local … (+140%), 0 USD», so his press
    bought the narration and the render then refused. Now a clip too short even for the
    fastest voice the studio measured is refused before anything is bought, and one that only
    may be too short is ready with the risk said, never promised a slow-down."""
    many = " ".join(["word"] * 30)  # 12.0 s estimated; 9.0 s at the fastest voice
    some = " ".join(["word"] * 16)  # 6.4 s estimated: 28% past 5.0 s; 4.8 s at the fastest
    storyboard_id = a_board(engine, tmp_path, [many, some])
    in_environment(engine, "PRODUCTION")
    for index in (1, 2):
        a_shot_take(engine, storyboard_id, index, 5.0, tmp_path / f"shot_{index}.mp4")
    readings = readiness_of(engine, storyboard_id)
    assert readings[1]["ok"] is False and readings[1]["code"] == CLIP_SHORT
    assert readings[1]["span_source"] == NARRATION_ESTIMATED
    assert "după narațiunea estimată" in readings[1]["reason_ro"]
    assert readings[2]["ok"] is True and readings[2]["how"] == "at_risk"
    assert readings[2]["slowed_by"] is None and readings[2]["reason_ro"] == ""
    assert "poate fi prea scurt" in readings[2]["risk_ro"]

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    step = sheet["steps"]["assemble"]
    assert step["ready"] is False and [b["scene_index"] for b in step["blocked"]] == [1]
    assert not any("se încetinește local" in note for note in step["notes_ro"])
    assert any("poate fi prea scurt" in note for note in step["notes_ro"])


def test_voiced_words_not_yet_rendered_are_read_by_their_timed_words_never_a_dead_end(
    engine: Engine, tmp_path: Path
) -> None:
    """Voiced words no render has measured were read at the vendor's untrimmed length: a clip
    the render would only slow read CLIP_SHORT at the sheet and the pre-check, the render never
    ran to measure it, and the film stayed blocked (or bought a redo it did not need). The
    words' own timing is the shortest the render can measure: within it the scene is ready
    (at risk; the narration is bought, so the render measures it for 0 USD); past it, certain."""
    storyboard_id = a_board(engine, tmp_path, WORDS[2:4])
    in_environment(engine, "PRODUCTION")
    for index in (1, 2):
        a_shot_take(engine, storyboard_id, index, 5.0, tmp_path / f"shot_{index}.mp4")
    # 6.3 s from the vendor (27% past the clip), its words ending at 6.0 s (20%).
    a_narration_take(engine, storyboard_id, tmp_path, 1, 6.3, words_end=6.0)
    # 6.7 s from the vendor, its words ending at 6.5 s: 30% even trimmed.
    a_narration_take(engine, storyboard_id, tmp_path, 2, 6.7, words_end=6.5)
    readings = readiness_of(engine, storyboard_id)
    assert readings[1]["span_source"] == NARRATION_MEASURED
    assert readings[1]["ok"] is True and readings[1]["how"] == "at_risk"
    assert readings[2]["ok"] is False and readings[2]["code"] == CLIP_SHORT
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert [b["scene_index"] for b in sheet["steps"]["assemble"]["blocked"]] == [2]


@requires_ffmpeg
def test_a_clip_delivered_shorter_than_billed_is_read_at_its_measured_length(
    engine: Engine, tmp_path: Path
) -> None:
    """The render measures the clip's file; the sheet and the pre-check read the billed seconds.
    A clip billed 7.0 s that holds 4.0 s was «Pregătit» on the sheet and refused by every
    render. One length now: the file's as measured, else the billed one."""
    from app.media.assembler import _longest_shot_since

    storyboard_id = a_board(engine, tmp_path, [WORDS[0]])
    in_environment(engine, "PRODUCTION")
    take_id = a_shot_take(engine, storyboard_id, 1, 7.0, a_clip(tmp_path / "short.mp4", 4.0))
    words = a_narration_take(engine, storyboard_id, tmp_path, 1, 6.06, words_end=6.0)
    a_render_record(engine, storyboard_id, {1: (6.0, [words])})
    (reading,) = readiness_of(engine, storyboard_id).values()
    assert reading["ok"] is False and reading["code"] == CLIP_SHORT
    assert reading["take_id"] == take_id and reading["clip_seconds"] == 4.0
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert sheet["steps"]["assemble"]["ready"] is False
    # A clip bought after a refusal counts by what it holds, not by its bill.
    assert _longest_shot_since(engine, storyboard_id, 1, "2026-01-01") == 4.0
