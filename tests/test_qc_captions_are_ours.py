"""Film QC never reads the studio's own subtitles as text.

2026-10-10, film babcf272 «The Particle That Shouldn't Exist (But Does)»: the film-level look
(`qc.span_picture_qc` -> `picture_qc.judge_clip`) was shown frames of the finished film, read
the subtitles the studio itself burns in as «apare text sau un logo» in every scene, and the
film failed; the repair that followed retired the stills and the test shot the Owner had
approved. What is asserted here, on real films cut by ffmpeg with the studio's own captions
burnt in by the studio's own ASS script:

- a film whose only writing is its captions does not fail for text, whether its scenes' own
  shots are still beside it (the look is shown them) or were released (the look is shown the
  film with the caption band cut away, and told the subtitles are the studio's);
- a shot that is no longer the file the film was joined from is never judged in its place;
- lettering inside the generated picture still fails the scene, in both cases;
- the 2026-10-09 triptych (tests/fixtures/panels) still fails as panels, in both cases;
- the one-frame look (`evaluate_pictures`) is shown the shots too, and told about the captions;
- a bought clip, judged before any edit, is asked exactly as before.

No model is called. The provider's transport is faked by `PixelEye`, whose only sight is
white lettering: it answers readable_text for any image holding a patch of near-white pixels,
which on these dark test pictures only the studio's captions or the picture's own lettering
can make.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import pytest
from app.media.models import MediaAsset, VideoRenderJob
from app.media.toolchain import find_ffmpeg, has_filter
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from sqlalchemy.orm import Session
from test_picture_qc import a_film, give_vision, staff

FFMPEG = find_ffmpeg(None)
requires_burnt_captions = pytest.mark.skipif(
    FFMPEG is None or not has_filter(FFMPEG, "subtitles"),
    reason="ffmpeg with the subtitles filter is not installed",
)

#: The 2026-10-09 triptych: a tunnel with a glowing atom, a flat black band, an empty tunnel.
TRIPTYCH = Path(__file__).parent / "fixtures" / "panels" / "scene_05_c7c55abb_c1.jpg"

FPS = 24
SCENES = [
    {
        "scene_index": 1,
        "picture": "A golden mirror in a dark hall",
        "narration": "A mirror catches the first light",
    },
    {
        "scene_index": 2,
        "picture": "A spectrum crossing a dark room",
        "narration": "and the water line appears",
    },
]

#: A test picture with nothing near white in it: the pattern at 55 % of its levels.
DARK = "testsrc2=s=1080x1920:r={fps}:d=2,colorlevels=romax=0.55:gomax=0.55:bomax=0.55"
DARK_OTHER = "testsrc2=s=1080x1920:r={fps}:d=2,hflip,colorlevels=romax=0.5:gomax=0.5:bomax=0.5"

#: The least near-white pixels the eye counts as writing; a caption card is thousands.
WHITE_PIXELS = 150


# ------------------------------------------------------------------------- the fake eye


def _image(encoded: str) -> np.ndarray:
    data = np.frombuffer(base64.b64decode(encoded), np.uint8)
    picture = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert picture is not None, "the look was sent something that is not an image"
    return picture


def white_pixels(picture: np.ndarray) -> int:
    return int((picture >= 235).all(axis=2).sum())


def central_triptych_band(picture: np.ndarray) -> bool:
    """The fake vision model sees the broad central black stripe of our fixture.

    This detection is test-only; production panels remain the AI vision
    model's responsibility, never an automatic pixel-only approval.
    """
    grey = cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY)
    begin, end = int(grey.shape[0] * .20), int(grey.shape[0] * .80)
    zone = grey[begin:end]
    flat = (zone.std(axis=1) < 2) & (zone.mean(axis=1) < 18)
    run = 0
    for row in flat:
        run = run + 1 if row else 0
        if run >= max(18, int(grey.shape[0] * .035)):
            return True
    return False


class PixelEye:
    """The provider's transport, faked, with eyes that see one thing: white lettering.

    It answers the clip checklist (`judge_clip`) for the scene its prompt names, and the
    one-frame look (`evaluate_pictures`) for every scene; nothing else it is asked differs
    between the frames of these films, so nothing else is judged. It never calls a model."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        images = [_image(item) for item in (kwargs.get("extra") or {}).get("images") or []]
        sizes = [(picture.shape[1], picture.shape[0]) for picture in images]
        whites = [white_pixels(picture) for picture in images]
        self.calls.append({"prompt": prompt, "sizes": sizes, "white": whites})
        writing = any(count >= WHITE_PIXELS for count in whites)
        triptych = any(central_triptych_band(picture) for picture in images)
        if '{"clips"' in prompt:
            scene = int(re.search(r"for scene (\d+)", prompt).group(1))
            verdict = {
                "scene": scene,
                "faces_visible": False,
                "readable_text": writing,
                "matches_plan": True,
                "shows_scene": True,
                "look_ok": True,
                "technical_ok": True,
                "same_shot": True,
                "one_picture": not triptych,
                "bible_violations": "none",
                "verdict": "back_to_still" if triptych else "keep",
                "reason": (
                    "not one picture: triptych with a central black strip"
                    if triptych else "white lettering on the frame" if writing else "a dark test pattern"
                ),
            }
            return GenerateResult(json.dumps({"clips": [verdict]}), 10, 40, None)
        scenes = [
            {
                "scene": index,
                "is_a_picture": True,
                "one_picture": True,
                "shows_the_scene": True,
                "reason": "a dark test pattern",
            }
            for index in range(1, len(images) + 1)
        ]
        return GenerateResult(json.dumps({"scenes": scenes, "characters": []}), 10, 40, None)

    def clip_calls(self) -> list[dict]:
        return [call for call in self.calls if '{"clips"' in call["prompt"]]


@pytest.fixture
def staffed(engine):
    return staff(engine)


@pytest.fixture
def eye(engine, staffed):
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry = ProviderRegistry()
    model = PixelEye()
    registry.register(staffed["provider_id"], model)
    return registry, model


# ---------------------------------------------------------------------------- the films


def _ffmpeg(args: list[str]) -> None:
    result = subprocess.run(  # noqa: S603 - argument list, no shell
        [FFMPEG, "-v", "error", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1500:]


def _encode(source: list[str], out: Path, *, vf: str | None = None) -> Path:
    _ffmpeg(
        [
            *source,
            *(["-vf", vf] if vf else []),
            "-frames:v",
            str(2 * FPS),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
    )
    return out


def _shot(folder: Path, name: str, picture: str) -> Path:
    """One scene's shot, as the assembler keeps it beside the film: 2 s at 24 fps, 1080x1920."""
    if picture == "triptych":
        # Dimmed like the test patterns: its glowing atom is near white, and the fake eye
        # would read it as lettering. The black band between the panels stays black.
        return _encode(
            ["-loop", "1", "-framerate", str(FPS), "-t", "2", "-i", str(TRIPTYCH)],
            folder / name,
            vf=f"scale=1080:1920:flags=lanczos,fps={FPS},setsar=1,"
            "colorlevels=romax=0.55:gomax=0.55:bomax=0.55",
        )
    return _encode(["-f", "lavfi", "-i", picture.format(fps=FPS)], folder / name)


#: Where a picture's own writing sits: «EXIT 42» at the top of the frame, far above the caption
#: rows, or a vendor's watermark «VEO AI» in the bottom-right corner, below them (rows about
#: 1760-1860, the part of the frame the first crop of 2026-10-10 hid from the look).
SIGN = ("EXIT 42", 150, 8, 320)
WATERMARK = ("VEO AI", 100, 3, 60)
#: A sign low in the frame, inside the caption rows (about rows 1350-1500): visible to the look
#: only where no subtitle is on screen.
LOW_SIGN = ("EXIT 42", 120, 2, 430)


def _letter(folder: Path, shot: Path, writing: tuple[str, int, int, int] = SIGN) -> Path:
    """Writing inside the picture itself, as a generated picture can carry it, in white and
    burnt into the shot: ``writing`` is (text, size, ASS alignment, vertical margin)."""
    from app.media import assembler

    text, size, alignment, margin_v = writing
    assembler.install_caption_fonts(folder)
    (folder / "lettering.ass").write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "PlayResX: 1080",
                "PlayResY: 1920",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
                "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
                "MarginV, Encoding",
                f"Style: Sign,Inter,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,"
                f"100,100,0,0,1,0,0,{alignment},40,40,{margin_v},1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                f"Dialogue: 0,0:00:00.00,0:00:05.00,Sign,,0,0,0,,{text}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    lettered = folder / f"{shot.stem}_lettered.mp4"
    result = assembler.run_encoder(
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(shot),
            "-vf",
            "subtitles=filename=lettering.ass:fontsdir=fonts",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(lettered),
        ],
        folder,
        carry=("lettering.ass", assembler.CAPTION_FONTS_DIR),
    )
    assert result.returncode == 0, result.stderr[-1500:]
    lettered.replace(shot)
    return shot


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def captioned_film(
    engine,
    folder: Path,
    *,
    pictures=(DARK, DARK_OTHER),
    lettered=(),
    writing=SIGN,
    narrated=(1, 2),
):
    """a_film's storyboard for SCENES, rendered as the assembler leaves it: each scene's shot
    beside the film (shot_NN.mp4, its sha256 in production["shots"]), the two shots joined and
    the narration's captions burnt over them with the studio's own ASS script (Inter Bold,
    white, the default finish), captions.srt beside it, and the render's record of all three.
    ``lettered`` names the scenes whose picture carries ``writing`` of its own; ``narrated``
    the scenes with words (a scene without has no caption, as the assembler cues it)."""
    from app.media import assembler, cards

    folder.mkdir(parents=True, exist_ok=True)
    ids = a_film(
        engine,
        scenes=[{"picture": s["picture"], "narration": s["narration"]} for s in SCENES],
        title="The studio's own words",
    )
    shots = []
    for scene, picture in zip(SCENES, pictures, strict=True):
        shot = _shot(folder, f"shot_{scene['scene_index']:02d}.mp4", picture)
        if scene["scene_index"] in lettered:
            _letter(folder, shot, writing)
        shots.append(shot)
    cues = assembler.caption_cues(
        [
            {
                "scene_index": s["scene_index"],
                "duration_seconds": 2.0,
                "audio_seconds": 1.8,
                "voiceover_segment": s["narration"] if s["scene_index"] in narrated else "",
            }
            for s in SCENES
        ]
    )
    (folder / "captions.srt").write_text(assembler.srt_from_cues(cues), encoding="utf-8")
    finish = copy.deepcopy(cards.DEFAULT_FINISH)
    (folder / assembler.CAPTIONS_ASS_NAME).write_text(
        assembler.ass_from_cues(cues, finish=finish), encoding="utf-8"
    )
    assembler.install_caption_fonts(folder)
    film = folder / "final_short_9_16.mp4"
    result = assembler.run_encoder(
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(shots[0]),
            "-i",
            str(shots[1]),
            "-filter_complex",
            f"[0:v][1:v]concat=n=2:v=1:a=0,{assembler.ass_captions_filter()}[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(film),
        ],
        folder,
        carry=(assembler.CAPTIONS_ASS_NAME, assembler.CAPTION_FONTS_DIR),
    )
    assert result.returncode == 0, result.stderr[-1500:]
    production = {
        "scenes": [
            {"scene_index": s["scene_index"], "scene_kind": "LIVE", "audio_seconds": 1.8}
            for s in SCENES
        ],
        "timeline": {
            "fps": FPS,
            "spans": [
                {
                    "scene_index": s["scene_index"],
                    "start": 2.0 * position,
                    "end": 2.0 * (position + 1),
                    "dissolve_seconds": 0.0,
                    "composed": False,
                }
                for position, s in enumerate(SCENES)
            ],
        },
        "shots": [
            {
                "scene_index": s["scene_index"],
                "file": shot.name,
                "sha256": _sha256(shot),
                "span": 2.0,
                "duration_seconds": 2.0,
                "dissolve_seconds": 0.0,
                "source": {"fps": FPS, "still": None, "clip": None},
            }
            for s, shot in zip(SCENES, shots, strict=True)
        ],
        "captions": {
            "srt": str(folder / "captions.srt"),
            "ass": str(folder / assembler.CAPTIONS_ASS_NAME),
            "cues": len(cues),
            "burned_in": True,
            "style": {"font_size": assembler.CAPTION_FONT_SIZE, "headline": False},
        },
    }
    with Session(engine) as session, session.begin():
        asset = session.get(MediaAsset, ids["asset"])
        asset.uri_or_path = str(film)
        asset.duration_seconds = 4.0
        session.get(VideoRenderJob, ids["job"]).production_json = production
    return ids, film, shots


def release(shots: list[Path]) -> None:
    """What quality control does once its report is recorded: the shots are deleted (the
    Owner's re-QC finds none)."""
    for shot in shots:
        shot.unlink()


def _film_frame(film: Path, folder: Path, number: int) -> np.ndarray:
    from app.agents.vision import frames_at

    (frame,) = frames_at(str(film), None, [number], folder / "probe").values()
    picture = cv2.imread(str(frame))
    assert picture is not None
    return picture


def _scenes(record) -> dict[int, dict]:
    return {entry["scene_index"]: entry for entry in record["scenes"]}


# ------------------------------------------------- a film whose only writing is its captions


@requires_burnt_captions
def test_a_film_whose_only_writing_is_its_captions_is_judged_on_its_own_shots(
    engine, eye, tmp_path
):
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, film, _shots = captioned_film(engine, tmp_path / "film")
    # The film really carries the studio's captions: white words in the caption band of the
    # frame the viewer sees half a second in, and none above it.
    frame = _film_frame(film, tmp_path, FPS // 2)
    assert white_pixels(frame[1320:1520]) > 1000
    assert white_pixels(frame[:1320]) == 0

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    assert record["passed"] is True and record["failures"] == [], record
    assert record["frames_from"] == {"SHOT": 2}
    for scene in _scenes(record).values():
        assert scene["frames_from"] == "SHOT" and scene["status"] == "PASSED"
        assert "apare text" not in str(scene["reason"])
    calls = model.clip_calls()
    assert len(calls) == 2
    for call in calls:
        # The look saw the scene's own picture, whole, with none of the studio's writing on it.
        assert call["sizes"] == [(1080, 1920)] * 3
        assert call["white"] == [0, 0, 0]
        assert "scene's own shot" in call["prompt"]
        assert "studio's own writing" in call["prompt"]
        assert "finished film" in call["prompt"]
    assert "pe cadrul scenei, dinainte de subtitrări" in record["detail"]


@requires_burnt_captions
def test_with_the_shots_released_the_look_sees_the_film_without_its_caption_band(
    engine, eye, tmp_path
):
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, _film, shots = captioned_film(engine, tmp_path / "film")
    release(shots)

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    assert record["passed"] is True and record["failures"] == [], record
    assert record["frames_from"] == {"FILM_CROPPED": 2}
    scenes = _scenes(record)
    assert all(scene["frames_from"] == "FILM_CROPPED" for scene in scenes.values())
    # The band is still read on the film's own frame, captions and all, and still passes.
    assert all(scene["panels"]["status"] == "NOT_APPLICABLE" for scene in scenes.values())
    assert all(scene["picture"]["status"] == "PASSED" for scene in scenes.values())
    calls = model.clip_calls()
    assert len(calls) == 2
    for call in calls:
        # Cut, never covered: only the caption rows (1320-1520) are cut out, with no strip
        # painted over them. The three frames above them come first, then the strip of each
        # below them, the rest of the picture.
        assert call["sizes"] == [(1080, 1320)] * 3 + [(1080, 400)] * 3
        assert call["white"] == [0] * 6
        assert "rows near the bottom" in call["prompt"]
        assert "the bottom of each frame" in call["prompt"]
        assert "studio_subtitles" in call["prompt"]
        assert "studio's own writing" in call["prompt"]
    # Each scene's own subtitle words, inside the inert boundary with the plan.
    assert "A mirror catches" in calls[0]["prompt"] and "the first light" in calls[0]["prompt"]
    assert "and the water" in calls[1]["prompt"] and "A mirror" not in calls[1]["prompt"]


@requires_burnt_captions
def test_a_shot_rebuilt_since_by_another_render_is_never_judged_in_the_films_place(
    engine, eye, tmp_path
):
    """Another render of the storyboard writes shot_NN.mp4 into the same folder. A shot whose
    bytes are not the sha256 this film recorded is another film's picture: the film's own
    frames are judged instead."""
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, _film, shots = captioned_film(engine, tmp_path / "film")
    _letter(tmp_path / "film", shots[0])  # scene 1's file now carries writing of its own

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    scenes = _scenes(record)
    assert scenes[1]["frames_from"] == "FILM_CROPPED"
    assert scenes[2]["frames_from"] == "SHOT"
    assert record["passed"] is True, record
    calls = model.clip_calls()
    assert [len(call["white"]) for call in calls] == [6, 3]  # the film's, with strips; the shot
    assert all(max(call["white"]) == 0 for call in calls)


# --------------------------------------------------- writing in the picture still fails


@requires_burnt_captions
@pytest.mark.parametrize("shots_beside_the_film", [True, False], ids=["shots", "released"])
def test_lettering_inside_the_picture_still_fails_the_scene(
    engine, eye, tmp_path, shots_beside_the_film
):
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, _film, shots = captioned_film(engine, tmp_path / "film", lettered=(2,))
    if not shots_beside_the_film:
        release(shots)

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    scenes = _scenes(record)
    assert scenes[1]["passed"] is True
    assert scenes[2]["passed"] is False
    assert "apare text sau un logo" in scenes[2]["reason"]
    (failure,) = record["failures"]
    assert failure.startswith("Scena 2:") and "apare text" in failure
    assert record["passed"] is False
    looked = {
        int(re.search(r"for scene (\d+)", c["prompt"]).group(1)): c for c in model.clip_calls()
    }
    assert max(looked[2]["white"]) >= WHITE_PIXELS and max(looked[1]["white"]) == 0
    # Three frames from the shot; on the film, three above the caption rows and three below.
    assert len(looked[1]["white"]) == (3 if shots_beside_the_film else 6)


@requires_burnt_captions
@pytest.mark.parametrize("shots_beside_the_film", [True, False], ids=["shots", "released"])
def test_a_watermark_below_the_caption_rows_still_fails_the_scene(
    engine, eye, tmp_path, shots_beside_the_film
):
    """Review of 2026-10-10: the first crop cut away everything from row 1320 down, 600 rows,
    though the captions draw only in rows 1320-1520; a vendor's watermark in the bottom corner
    of the picture was never shown to the look once the shots were released, and the scene
    passed. The bottom of the frame below the caption rows is shown to the look as well."""
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, film, shots = captioned_film(engine, tmp_path / "film", lettered=(2,), writing=WATERMARK)
    # The watermark is in the picture, below the captions and nowhere near them.
    frame = _film_frame(film, tmp_path, 2 * FPS + FPS // 2)
    assert white_pixels(frame[1700:]) >= WHITE_PIXELS
    assert white_pixels(frame[:1320]) == 0
    if not shots_beside_the_film:
        release(shots)

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    scenes = _scenes(record)
    assert scenes[2]["frames_from"] == ("SHOT" if shots_beside_the_film else "FILM_CROPPED")
    assert scenes[2]["passed"] is False and "apare text sau un logo" in scenes[2]["reason"]
    assert scenes[1]["passed"] is True, scenes[1]
    (failure,) = record["failures"]
    assert failure.startswith("Scena 2:")
    looked = {
        int(re.search(r"for scene (\d+)", c["prompt"]).group(1)): c for c in model.clip_calls()
    }
    if not shots_beside_the_film:
        # The watermark reached the look in the strips below the caption rows, not above them.
        assert looked[2]["white"][:3] == [0, 0, 0]
        assert min(looked[2]["white"][3:]) >= WHITE_PIXELS
    assert looked[1]["white"] == [0] * len(looked[1]["white"])


@requires_burnt_captions
def test_a_scene_without_words_is_shown_whole_and_its_low_lettering_still_fails(
    engine, eye, tmp_path
):
    """Review of 2026-10-10: the first crop was decided for the whole film, so a scene with no
    narration, nothing burnt over it, lost its lower part to the cut all the same. With the
    shots released, a scene whose frames carry no subtitle (by the SRT's cues) is shown whole,
    and a sign low in its picture, in the very rows a subtitle would take, still fails it."""
    from app.media.qc import span_picture_qc

    registry, model = eye
    ids, film, shots = captioned_film(
        engine, tmp_path / "film", lettered=(2,), writing=LOW_SIGN, narrated=(1,)
    )
    frame = _film_frame(film, tmp_path, 2 * FPS + FPS // 2)
    assert white_pixels(frame[1320:1520]) >= WHITE_PIXELS  # the sign, not a caption
    release(shots)

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()))

    scenes = _scenes(record)
    assert scenes[2]["passed"] is False and "apare text sau un logo" in scenes[2]["reason"]
    assert scenes[2]["frames_from"] == "FILM_CLEAR"
    assert scenes[1]["frames_from"] == "FILM_CROPPED" and scenes[1]["passed"] is True
    assert record["frames_from"] == {"FILM_CROPPED": 1, "FILM_CLEAR": 1}
    assert "în clipe fără subtitrări pe ecran" in record["detail"]
    looked = {
        int(re.search(r"for scene (\d+)", c["prompt"]).group(1)): c for c in model.clip_calls()
    }
    assert looked[2]["sizes"] == [(1080, 1920)] * 3
    assert min(looked[2]["white"]) >= WHITE_PIXELS
    # Told that no subtitle is on these frames, and never handed words to excuse the sign with.
    assert "none of the studio's" in looked[2]["prompt"]
    assert "studio_subtitles" not in looked[2]["prompt"]


# ------------------------------------------------------------ the triptych is still panels


@requires_burnt_captions
@pytest.mark.parametrize("shots_beside_the_film", [True, False], ids=["shots", "released"])
def test_the_triptych_still_fails_as_panels_whoever_looks(
    engine, staffed, tmp_path, shots_beside_the_film
):
    """The band is free and read whether or not anybody looks: on the scene's own shot when it
    is beside the film, on the film's own uncut frame when it is not."""
    from app.media.qc import span_picture_qc

    ids, _film, shots = captioned_film(engine, tmp_path / "film", pictures=("triptych", DARK))
    if not shots_beside_the_film:
        release(shots)

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()))

    scenes = _scenes(record)
    # With no vision-capable model, the studio must not invent either PASS
    # or FAIL for panels. Publishing still requires a measured visual review.
    assert record["passed"] is None and record["status"] == "NOT_RUN", record
    assert scenes[1]["frames_from"] == ("SHOT" if shots_beside_the_film else "FILM")
    assert scenes[1]["panels"]["status"] == "NOT_APPLICABLE"
    assert scenes[1]["picture"]["status"] == "NOT_RUN"
    assert scenes[2]["passed"] is None
    assert record["failures"] == []


@requires_burnt_captions
def test_quality_control_fails_the_triptych_and_not_one_scene_for_its_captions(
    engine, eye, tmp_path
):
    """The whole report, as the incident's: the panels scene fails as panels, and no scene
    fails for text; the one-frame look was shown the shots as well."""
    from app.media.qc import evaluate_media_qc

    registry, model = eye
    ids, _film, _shots = captioned_film(engine, tmp_path / "film", pictures=("triptych", DARK))

    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()), registry=registry)

    spans = report["checks_json"]["picture_spans_qc"]
    scenes = _scenes(spans)
    assert scenes[1]["passed"] is False and scenes[1]["picture"]["status"] == "FAILED"
    assert scenes[1]["panels"]["status"] == "NOT_APPLICABLE"
    assert scenes[2]["passed"] is True, scenes[2]
    assert not any("apare text" in reason for reason in report["failure_reasons_json"])
    assert any(
        "Scena 1:" in reason and ("one picture" in reason or "triptych" in reason)
        for reason in report["failure_reasons_json"]
    ), report["failure_reasons_json"]
    assert report["checks_json"]["picture_qc"]["frames_from"] == "SHOT"


# ------------------------------------------------------------ the one-frame look, too


@requires_burnt_captions
def test_the_one_frame_look_is_shown_the_shots_middles_and_told_about_the_captions(
    engine, eye, tmp_path
):
    from app.media.picture_qc import evaluate_pictures

    registry, model = eye
    ids, _film, shots = captioned_film(engine, tmp_path / "film")

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["picture_qc"]["passed"] is True
    assert result["picture_qc"]["frames_from"] == "SHOT"
    (call,) = model.calls
    assert call["sizes"] == [(480, 854)] * 2
    assert call["white"] == [0, 0]
    assert "scene's own shot" in call["prompt"]

    release(shots)
    model.calls.clear()
    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["picture_qc"]["frames_from"] == "FILM"
    (call,) = model.calls
    # The film's own frames, captions and all, with the model told whose writing that is.
    assert max(call["white"]) > 0
    assert "studio's subtitles of the narration burnt in" in call["prompt"]
    assert "studio's own writing" in call["prompt"]


# ------------------------------------------------------- a bought clip is asked as before


@requires_burnt_captions
def test_a_bought_clip_is_asked_exactly_as_before(engine, eye, tmp_path):
    from app.agents.vision import frames_at
    from app.media.picture_qc import judge_clip
    from app.media.still_gate import StillPlan

    registry, model = eye
    shot = _shot(tmp_path, "clip.mp4", DARK)
    frames = list(frames_at(str(shot), None, [0, 24, 47], tmp_path / "cut").values())

    judged = judge_clip(
        engine,
        registry,
        frames,
        StillPlan(
            scene=3,
            still_prompt="A golden mirror",
            camera_move="slow push-in",
            faces_forbidden=False,
            bible_rules=(),
            look_block="",
        ),
        str(uuid4()),
    )

    assert judged.status == "MEASURED" and judged.verdict.readable_text is False
    (call,) = model.calls
    assert "has not been cut into the film yet" in call["prompt"]
    assert "subtitles" not in call["prompt"] and "studio_subtitles" not in call["prompt"]


# ---------------------------------------------------------------------- the pieces alone


def test_the_note_says_nothing_where_the_studio_wrote_nothing():
    from app.media.picture_qc import StudioText, studio_text_note

    assert studio_text_note(None) == ""
    assert studio_text_note(StudioText(source="FILM", captions_burned_in=False)) == ""
    shot = studio_text_note(StudioText(source="SHOT", captions_burned_in=True))
    assert "scene's own shot" in shot and "studio_subtitles" not in shot
    cropped = studio_text_note(
        StudioText(source="FILM_CROPPED", captions_burned_in=True, subtitles=("a b",))
    )
    assert "rows near the bottom" in cropped and "studio_subtitles" in cropped
    assert "bottom of each frame" not in cropped  # no strips travel with these frames
    with_strips = studio_text_note(
        StudioText(
            source="FILM_CROPPED",
            captions_burned_in=True,
            below_captions=(Path("a.png"), Path("b.png"), Path("c.png")),
        )
    )
    assert "come 3 more images" in with_strips and "bottom of each frame" in with_strips
    assert "lettering, numbers, signs, logos or faces there count" in with_strips
    clear = studio_text_note(StudioText(source="FILM_CLEAR", captions_burned_in=True))
    assert "none of the studio's" in clear and "studio_subtitles" not in clear
    assert "repeat the narration" not in clear
    film = studio_text_note(StudioText(source="FILM", captions_burned_in=True, headline=True))
    assert "repeat the narration" in film and "opening title" in film
    for note in (shot, cropped, with_strips, clear, film):
        assert "inside the generated picture" in note and note.endswith("\n")


def test_only_a_verified_shot_beside_the_film_is_clean(tmp_path):
    from app.media.picture_qc import clean_shots

    good = tmp_path / "shot_01.mp4"
    good.write_bytes(b"scene one")
    changed = tmp_path / "shot_02.mp4"
    changed.write_bytes(b"another render's scene two")
    unrecorded = tmp_path / "shot_03.mp4"
    unrecorded.write_bytes(b"a shot from before the sha256")
    production = {
        "shots": [
            {
                "scene_index": 1,
                "file": "shot_01.mp4",
                "sha256": hashlib.sha256(b"scene one").hexdigest(),
                "span": 2.5,
                "duration_seconds": 2.0,
                "source": {"fps": 24},
            },
            {
                "scene_index": 2,
                "file": "shot_02.mp4",
                "sha256": hashlib.sha256(b"scene two").hexdigest(),
            },
            {"scene_index": 3, "file": "shot_03.mp4", "sha256": None},
            {
                "scene_index": 4,
                "file": "shot_04.mp4",
                "sha256": hashlib.sha256(b"gone").hexdigest(),
            },
        ]
    }

    found = clean_shots(production, tmp_path)

    assert list(found) == [1]
    assert found[1].path == good and found[1].fps == 24.0
    assert (found[1].seconds, found[1].span) == (2.0, 2.5)
    assert clean_shots({}, tmp_path) == {} and clean_shots({"shots": "x"}, tmp_path) == {}


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
def test_only_the_caption_rows_are_cut_out_never_painted_over(tmp_path):
    from app.media.picture_qc import ASS_CAPTION_ROWS, LEGACY_CAPTION_ROWS, cut_caption_rows

    frame = tmp_path / "frame.png"
    _ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(frame)])
    original = cv2.imread(str(frame))

    for rows in (ASS_CAPTION_ROWS, LEGACY_CAPTION_ROWS):
        pieces = cut_caption_rows(
            FFMPEG,
            frame,
            rows,
            tmp_path / f"above_{rows[0]}.png",
            tmp_path / f"below_{rows[0]}.png",
        )
        assert pieces is not None
        above, below = (cv2.imread(str(piece)) for piece in pieces)
        # The pixels themselves, not a copy painted over: everything but the caption rows.
        assert np.array_equal(above, original[: rows[0]])
        assert np.array_equal(below, original[rows[1] :])
    assert ASS_CAPTION_ROWS == (1320, 1520)

    # A frame of another size is cut at the same share of its height, on even rows.
    small = tmp_path / "small.png"
    _ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=540x960:d=1", "-frames:v", "1", str(small)])
    pieces = cut_caption_rows(
        FFMPEG, small, ASS_CAPTION_ROWS, tmp_path / "small_a.png", tmp_path / "small_b.png"
    )
    assert pieces is not None
    assert [cv2.imread(str(piece)).shape[:2] for piece in pieces] == [(660, 540), (200, 540)]

    missing = tmp_path / "missing.png"
    assert (
        cut_caption_rows(FFMPEG, missing, ASS_CAPTION_ROWS, tmp_path / "x", tmp_path / "y") is None
    )
    assert cut_caption_rows(None, frame, ASS_CAPTION_ROWS, tmp_path / "x", tmp_path / "y") is None


def test_the_rows_cut_out_follow_the_script_the_film_burnt():
    from app.media.picture_qc import ASS_CAPTION_ROWS, LEGACY_CAPTION_ROWS, caption_rows

    ass = {"captions": {"burned_in": True, "ass": "x/captions.ass", "srt": "x/captions.srt"}}
    legacy = {"captions": {"burned_in": True, "srt": "x/captions.srt"}}
    assert caption_rows(ass) == ASS_CAPTION_ROWS
    assert caption_rows(legacy) == LEGACY_CAPTION_ROWS
    assert caption_rows({"captions": {"burned_in": False, "ass": "x"}}) is None
    assert caption_rows({}) is None


@requires_burnt_captions
@pytest.mark.parametrize("script", ["ass", "legacy_srt"])
def test_the_studio_captions_draw_only_inside_the_rows_cut_out(tmp_path, script):
    """The rows are a measurement, kept as one: the studio's own captions, two lines with
    diacritics over capitals and the largest shadow the finish allows, burnt as the assembler
    burns them (its ASS script, or a legacy film's SRT style), draw nothing outside them."""
    from app.media import assembler, cards
    from app.media.picture_qc import ASS_CAPTION_ROWS, LEGACY_CAPTION_ROWS

    cues = [
        {
            "scene_index": 1,
            "start": 0.0,
            "end": 1.0,
            "lines": ["ÎNGHEȚURI ȘI ȚĂRMURI gjpqy", "Şapte ÎNGHEŢURI gjpqy Åj"],
            "timing": "character_share",
        }
    ]
    finish = copy.deepcopy(cards.DEFAULT_FINISH)
    finish["captions"]["shadow_px"] = 4.0  # the most cards.film_finish accepts
    finish["captions"]["shadow_opacity"] = 1.0
    (tmp_path / "captions.srt").write_text(assembler.srt_from_cues(cues), encoding="utf-8")
    (tmp_path / "captions.ass").write_text(
        assembler.ass_from_cues(cues, finish=finish), encoding="utf-8"
    )
    assembler.install_caption_fonts(tmp_path)
    burn, rows = (
        (assembler.ass_captions_filter("captions.ass"), ASS_CAPTION_ROWS)
        if script == "ass"
        else (assembler.captions_filter("captions.srt"), LEGACY_CAPTION_ROWS)
    )
    frame = tmp_path / "frame.png"
    result = assembler.run_encoder(
        [
            FFMPEG,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=1080x1920:r=24:d=1",
            "-vf",
            burn,
            "-frames:v",
            "1",
            str(frame),
        ],
        tmp_path,
        carry=("captions.ass", "captions.srt", assembler.CAPTION_FONTS_DIR),
    )
    assert result.returncode == 0, result.stderr[-1500:]
    picture = cv2.imread(str(frame)).astype(int)
    drawn = np.abs(picture - picture[100:200, 100:200].mean(axis=(0, 1))).max(axis=2) > 6
    drawn_rows = np.where(drawn.any(axis=1))[0]
    assert len(drawn_rows) > 50, "nothing was burnt"
    assert rows[0] <= drawn_rows.min() and drawn_rows.max() < rows[1], (
        drawn_rows.min(),
        drawn_rows.max(),
    )


def test_strips_that_do_not_match_the_frames_leave_the_clip_unseen(engine, tmp_path):
    """The bottom of the frames is part of what is judged: a look that would see only the part
    above the caption rows does not happen."""
    from app.media.picture_qc import StudioText, judge_clip
    from app.media.still_gate import StillPlan

    frames = [tmp_path / f"f{n}.png" for n in range(3)]
    judged = judge_clip(
        engine,
        None,
        frames,
        StillPlan(
            scene=1,
            still_prompt="A golden mirror",
            camera_move="static",
            faces_forbidden=False,
            bible_rules=(),
            look_block="",
        ),
        str(uuid4()),
        studio_text=StudioText(
            source="FILM_CROPPED", captions_burned_in=True, below_captions=(frames[0],)
        ),
    )

    assert judged.status == "NOT_RUN" and judged.verdict is None
    assert "fâșii de sub subtitrări" in judged.detail_ro
