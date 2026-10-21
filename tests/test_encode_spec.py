"""The premium master: what the finished film is encoded as, read back from a real encode.

The Nepal film went out at 2.6 Mbps, tagged full range (``setrange=pc``) so every player showed
its blacks grey, and every shot had already been through a lossy veryfast encode before the
final one. None of that cost a credit to get wrong, and none of it costs one to get right:

- shots are compact, visually lossless intermediates (x264 High, CRF 4, measured on the Nepal
  stills and clips on 2026-10-01: half the size of ``-qp 0``, the final film within 0.6 dB of
  one made from lossless shots), so the film is encoded lossily once, at full quality;
- the final is H.264 High 4.2, CRF 17 on the slow preset, capped at 14 Mbps, a keyframe every
  half second, 4:2:0, tagged BT.709 limited range, with the index at the front;
- the audio is mastered once and copied into the film, never encoded twice.

Every fixture here is made locally by ffmpeg's own test sources. No provider is involved.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from app.media.toolchain import find_ffmpeg, find_ffprobe

FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()

requires_toolchain = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg and ffprobe are needed to read an encode"
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - argument list, no shell
        args,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
    )


def _probe(path: Path) -> dict:
    assert FFPROBE is not None
    result = _run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    )
    return json.loads(result.stdout)


def _stream(probe: dict, kind: str) -> dict:
    return next(s for s in probe["streams"] if s["codec_type"] == kind)


def _top_level_boxes(path: Path) -> list[str]:
    """The MP4's top-level box names in file order."""
    names: list[str] = []
    data = path.read_bytes()
    position = 0
    while position + 8 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        name = data[position + 4 : position + 8].decode("latin-1")
        if size == 1:
            size = int.from_bytes(data[position + 8 : position + 16], "big")
        elif size == 0:
            size = len(data) - position
        names.append(name)
        position += size
    return names


def _detailed_clip(target: Path, seconds: float = 3.0) -> None:
    """A vendor-like clip: 24 fps, detailed, moving grain — the kind of picture that needs bits."""
    assert FFMPEG is not None
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1080x1920:rate=24:duration={seconds}",
            "-vf",
            # Grain added to the RGB picture and then graded into limited range, as a vendor's
            # finished clip is: the noise itself must not invent super-whites.
            "format=rgb24,noise=alls=28:allf=t+u,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "8",
            "-preset",
            "ultrafast",
            str(target),
        ]
    )


def _still(target: Path) -> None:
    assert FFMPEG is not None
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=1:duration=1,noise=alls=28:allf=u",
            "-frames:v",
            "1",
            str(target),
        ]
    )


def _voice(target: Path, seconds: float) -> None:
    assert FFMPEG is not None
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='0.3*(0.3+0.7*abs(sin(2*PI*0.4*t)))*sin(2*PI*220*t)':s=44100:d={seconds}",
            str(target),
        ]
    )


# --------------------------------------------------------------------------- the arguments


def test_the_final_encode_is_made_again_tighter_until_it_meets_the_bitrate_floor(
    tmp_path, monkeypatch
):
    """2026-10-16 05:35Z, 7c26a7ce «Speed of Light»: a dark, nearly still film at 24 fps came
    out of CRF 17 at 4.4 Mbps, quality control failed it under its 6 Mbps floor, and the free
    re-encode from the same takes could only have made the same file again. The encoder now
    measures what it made and tightens the CRF in steps until the floor is met."""
    import subprocess

    from app.media import assembler

    runs: list[list[str]] = []
    rates = {17: 4_400_000, 12: 5_900_000, 8: 7_100_000}
    output = tmp_path / "final.mp4"

    def fake_run(args, work_dir, carry=()):
        runs.append(list(args))
        output.write_bytes(b"film")
        return subprocess.CompletedProcess(list(args), 0, "", "")

    monkeypatch.setattr(assembler, "run_encoder", fake_run)
    monkeypatch.setattr(
        assembler,
        "_video_bit_rate",
        lambda exe, path: rates[int(runs[-1][runs[-1].index("-crf") + 1])],
    )
    args = ["-i", "x", *assembler.final_video_args(24), str(output)]

    res, record = assembler.encode_to_floor("ffmpeg", args, tmp_path, output, floor=6_000_000)

    assert res.returncode == 0
    assert [int(r[r.index("-crf") + 1]) for r in runs] == [17, 12, 8]
    assert record["crf"] == 8 and record["video_bit_rate"] == 7_100_000
    assert [t["crf"] for t in record["tightened"]] == [17, 12]

    # At the floor from the first run: one encode, nothing tightened.
    runs.clear()
    rates[17] = 6_500_000
    res, record = assembler.encode_to_floor("ffmpeg", args, tmp_path, output, floor=6_000_000)
    assert len(runs) == 1 and record["crf"] == 17 and record["tightened"] == []

    # A failed run is returned as it is, never tightened.
    runs.clear()

    def failing(args, work_dir, carry=()):
        runs.append(list(args))
        return subprocess.CompletedProcess(list(args), 1, "", "boom")

    monkeypatch.setattr(assembler, "run_encoder", failing)
    res, record = assembler.encode_to_floor("ffmpeg", args, tmp_path, output, floor=6_000_000)
    assert res.returncode == 1 and len(runs) == 1 and record["video_bit_rate"] is None


def test_the_final_encode_is_named_in_full():
    from app.media.assembler import final_video_args

    args = final_video_args(30)
    joined = " ".join(args)

    def value(flag: str) -> str:
        return args[args.index(flag) + 1]

    assert value("-c:v") == "libx264"
    assert value("-profile:v") == "high"
    assert value("-level:v") == "4.2"
    assert value("-preset") == "slow"
    assert value("-crf") == "17"
    assert final_video_args(30, crf=12)[final_video_args(30).index("-crf") + 1] == "12"
    assert value("-maxrate") == "14M"
    assert value("-bufsize") == "28M"
    assert value("-bf") == "2"
    assert value("-g") == "15"  # half a second at 30 fps
    assert final_video_args(24)[final_video_args(24).index("-g") + 1] == "12"
    assert value("-sc_threshold") == "0"
    assert value("-pix_fmt") == "yuv420p"
    assert value("-color_range") == "tv"
    assert value("-colorspace") == "bt709"
    assert value("-color_primaries") == "bt709"
    assert value("-color_trc") == "bt709"
    assert value("-movflags") == "+faststart"
    assert "veryfast" not in joined


def test_a_shot_is_a_compact_limited_range_intermediate():
    """2026-10-01 (DISK_AND_BREATHS): a lossless (-qp 0) shot was about 16 MB a second at
    1080x1920, 1.1 GB a film. A shot is now x264 High at CRF 4: visually lossless for the one
    final encode, half the size, and a repeated frame still reads as one (qc)."""
    from app.media.assembler import INTERMEDIATE_VIDEO_ARGS, _shot_command

    for clip in (None, Path("motion_01.mp4")):
        args = _shot_command("ffmpeg", Path("scene_01.png"), clip, 4.4, Path("shot_01.mp4"))
        joined = " ".join(args)
        assert "setrange=pc" not in joined and "setrange" not in joined
        assert "-qp" not in args
        assert args[args.index("-crf") + 1] == "4"
        assert args[args.index("-profile:v") + 1] == "high"
        assert args[args.index("-preset") + 1] == "veryfast"
        assert args[args.index("-pix_fmt") + 1] == "yuv420p"
        assert "out_range=tv" in joined and "out_color_matrix=bt709" in joined
        assert args[args.index("-color_range") + 1] == "tv"
        assert tuple(args[-1 - len(INTERMEDIATE_VIDEO_ARGS) : -1]) == INTERMEDIATE_VIDEO_ARGS


def _x264_settings(path: Path) -> str:
    """The settings x264 wrote into the stream's SEI ("crf=4.0", "qp=0", ...)."""
    data = path.read_bytes()
    start = data.find(b"x264 - core")
    assert start >= 0, "not an x264 stream"
    return data[start : data.find(b"\x00", start)].decode("latin-1")


@requires_toolchain
def test_a_composed_card_is_the_same_compact_intermediate(tmp_path: Path):
    from app.media.cards import card_spec_from_json, compose_card

    card = compose_card(
        card_spec_from_json("TITLE_CARD", {"title": "Ploi în Nepal"}),
        tmp_path / "card_01.mp4",
        duration=1.5,
        ffmpeg=FFMPEG,
    )
    settings = _x264_settings(card.path)
    assert " crf=4.0 " in settings and " qp=0 " not in settings, settings
    video = _stream(_probe(card.path), "video")
    assert video["profile"] == "High" and video["pix_fmt"] == "yuv420p"
    assert video["color_range"] == "tv" and video["color_space"] == "bt709"


@requires_toolchain
def test_a_compact_shot_is_half_a_lossless_one_and_visually_the_same(tmp_path: Path):
    """The Nepal still with the local push-in, measured 2026-10-01 at 8.6 s: 139 MB lossless,
    66 MB at CRF 4, 51.6 dB against the lossless shot. The fixture is a Nepal still too."""
    import app.media.assembler as assembler
    from test_scene_takes import FIXTURES

    assert FFMPEG is not None
    still = FIXTURES / "scene_01.jpg"
    compact = tmp_path / "compact.mp4"
    _run(assembler._shot_command(FFMPEG, still, None, 3.0, compact))
    lossless = tmp_path / "lossless.mp4"
    codec = ["-c:v", "libx264", "-qp", "0", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    command = assembler._shot_command(FFMPEG, still, None, 3.0, lossless)
    cut = len(assembler.INTERMEDIATE_VIDEO_ARGS) + 1
    _run([*command[:-cut], *codec, str(lossless)])

    assert compact.stat().st_size <= 0.6 * lossless.stat().st_size, (
        compact.stat().st_size,
        lossless.stat().st_size,
    )
    compared = _run(
        [
            FFMPEG,
            "-nostdin",
            "-i",
            str(compact),
            "-i",
            str(lossless),
            "-lavfi",
            "[0:v][1:v]psnr",
            "-f",
            "null",
            "-",
        ]
    ).stderr
    found = re.search(r"PSNR .*?average:([0-9.]+)", compared)
    assert found is not None, compared[-400:]
    assert float(found.group(1)) >= 48.0, found.group(1)


def _shot_duplicates(shot: Path, span: float) -> float | None:
    """Quality control's own reading of one moving scene's shot: the share of repeated frames
    away from its edges (qc.shot_duplicate_share)."""
    from app.media.qc import shot_duplicate_share

    return shot_duplicate_share(
        FFMPEG,
        {"shots": [{"scene_index": 1, "file": shot.name}]},
        shot.parent,
        [(1, 0.0, span)],
    )


@requires_toolchain
def test_on_a_compact_shot_a_repeated_frame_still_counts_and_slow_motion_does_not(
    tmp_path: Path,
):
    """Measured 2026-10-01: in CRF 4 shots a repeated frame reads at most 0.013 (the Nepal
    motion_04 at 12 fps with a held end; 0 lossless), the slowest real Nepal clip 0.097 (0.104
    lossless). qc.LOSSLESS_DUPLICATE_YDIF sits between them, at 0.03."""
    from app.media.assembler import _shot_command
    from app.media.qc import LOSSLESS_DUPLICATE_YDIF

    assert LOSSLESS_DUPLICATE_YDIF == 0.03
    assert FFMPEG is not None
    # A grained vendor clip at 12 fps, held half a second past its end: on the 24 fps timeline
    # every other frame repeats, and so does every held one.
    twelve = tmp_path / "motion_12.mp4"
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=12:duration=3",
            "-vf",
            "format=rgb24,noise=alls=28:allf=t+u,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "8",
            "-preset",
            "ultrafast",
            str(twelve),
        ]
    )
    repeated = tmp_path / "shot_01.mp4"
    _run(_shot_command(FFMPEG, tmp_path / "unused.png", twelve, 3.5, repeated, hold=0.5))
    # 60 frames inside the edges, 30 of them a repeat of the frame before (12 fps doubled).
    share = _shot_duplicates(repeated, 3.5)
    assert share == pytest.approx(0.5, abs=0.02), share

    # A slow real picture: a detailed frame under faint grain, 0.13-0.17 a frame.
    slow = tmp_path / "motion_slow.mp4"
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1080x1920:rate=1:duration=1,noise=alls=28:allf=u",
            "-vf",
            "loop=72:1:0,fps=24,noise=c0s=2:c0f=t,format=yuv420p",
            "-frames:v",
            "72",
            "-c:v",
            "libx264",
            "-crf",
            "8",
            "-preset",
            "ultrafast",
            str(slow),
        ]
    )
    moving = tmp_path / "shot_02.mp4"
    _run(_shot_command(FFMPEG, tmp_path / "unused.png", slow, 3.0, moving))
    assert _shot_duplicates(moving, 3.0) == 0.0


def test_the_film_copies_a_mastered_track_and_never_encodes_audio_twice():
    from app.media.assembler import _dissolve_command

    shots = [Path("shot_01.mp4"), Path("shot_02.mp4")]
    scenes = [{"duration_seconds": 3.0}, {"duration_seconds": 3.0}]
    args = _dissolve_command(
        "ffmpeg", shots, scenes, Path("master.m4a"), Path("out.mp4"), audio_filter=None
    )
    assert args[args.index("-c:a") + 1] == "copy"
    assert "-af" not in args and "aac" not in args
    chain = args[args.index("-filter_complex") + 1]
    assert "setrange=pc" not in chain
    assert "range=tv" in chain


# --------------------------------------------------------------------------- a real encode


def _signal_stats(path: Path, crop: str | None = None) -> dict[str, list[float]]:
    """signalstats' YMIN, YMAX and YAVG for every frame, over the whole frame or a crop."""
    assert FFMPEG is not None
    look = f"crop={crop}," if crop else ""
    result = subprocess.run(  # noqa: S603
        [
            FFMPEG,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"{look}signalstats,metadata=print:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    stats = {
        key: [float(v) for v in re.findall(rf"{key}=([\d.]+)", result.stdout)]
        for key in ("YMIN", "YMAX", "YAVG")
    }
    assert all(stats.values()), result.stdout[-400:]
    return stats


@requires_toolchain
def test_a_film_from_a_detailed_source_probes_as_the_premium_master(tmp_path: Path):
    from app.media.assembler import _dissolve_command, _shot_command
    from app.media.toolchain import encode_master_audio

    assert FFMPEG is not None
    clip = tmp_path / "motion_01.mp4"
    _detailed_clip(clip)
    still = tmp_path / "scene_02.png"
    _still(still)
    scenes = [{"duration_seconds": 3.0}, {"duration_seconds": 3.0}]

    shots = []
    for index, (source_clip, span) in enumerate(((clip, 3.4), (None, 3.4)), start=1):
        target = tmp_path / f"shot_{index:02d}.mp4"
        _run(_shot_command(FFMPEG, still, source_clip, span, target))
        shots.append(target)

    # The intermediates are compact (High, CRF 4), and already limited range BT.709.
    for shot in shots:
        video = _stream(_probe(shot), "video")
        assert video["profile"] == "High", video
        assert " crf=4.0 " in _x264_settings(shot)
        assert video["color_range"] == "tv" and video["color_space"] == "bt709"

    voice = tmp_path / "voice.wav"
    _voice(voice, 5.5)
    mastered = tmp_path / "master.m4a"
    encode_master_audio(FFMPEG, voice, mastered, duration=6.0)

    film = tmp_path / "final.mp4"
    _run(_dissolve_command(FFMPEG, shots, scenes, mastered, film, audio_filter=None))

    probe = _probe(film)
    video = _stream(probe, "video")
    assert video["codec_name"] == "h264"
    assert video["profile"] == "High"
    assert video["level"] == 42
    assert video["pix_fmt"] == "yuv420p"
    assert video["color_range"] == "tv"
    assert video["color_space"] == "bt709"
    assert video["color_primaries"] == "bt709"
    assert video["color_transfer"] == "bt709"
    assert (video["width"], video["height"]) == (1080, 1920)
    # A detailed picture gets the bits it needs; the Nepal film had 2.6 Mbps for all of it.
    assert int(video["bit_rate"]) >= 8_000_000, video["bit_rate"]
    # And the ceiling holds: at most 14 Mbps, plus what the 28 Mbit buffer may spend up front
    # over a film this short.
    seconds = float(probe["format"]["duration"])
    assert int(video["bit_rate"]) <= 14_000_000 + 28_000_000 / seconds, video["bit_rate"]

    audio = _stream(probe, "audio")
    assert audio["codec_name"] == "aac" and audio["profile"] == "LC"
    assert int(audio["sample_rate"]) == 48000 and int(audio["channels"]) == 2

    # +faststart: the index comes before the media, so a phone starts playing at once.
    boxes = _top_level_boxes(film)
    assert boxes.index("moov") < boxes.index("mdat"), boxes


@requires_toolchain
def test_graded_black_and_white_land_on_16_and_235_not_only_in_the_tags(tmp_path: Path):
    """A graded picture — a flat black field beside a flat white one — through a clip shot,
    a still shot and the final encode: black measures 16 and white 235 everywhere in the
    fields. Full range would put them at 0 and 255; a range converted twice would lift the
    black to about 30. The fields are measured away from their edge, because a lossy encode
    rings at a sharp edge and the ringing says nothing about the levels.
    """
    from app.media.assembler import _dissolve_command, _shot_command
    from app.media.toolchain import encode_master_audio

    assert FFMPEG is not None
    fields = (
        "color=c=black:size=540x1920:rate={rate}:duration={seconds}[b];"
        "color=c=white:size=540x1920:rate={rate}:duration={seconds}[w];"
        "[b][w]hstack=inputs=2"
    )
    still = tmp_path / "fields.png"
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-filter_complex",
            fields.format(rate=1, seconds=1) + ",format=rgb24",
            "-frames:v",
            "1",
            str(still),
        ]
    )
    clip = tmp_path / "fields.mp4"
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-filter_complex",
            fields.format(rate=24, seconds=2)
            + ",format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "12",
            str(clip),
        ]
    )
    black, white = "300:700:120:600", "300:700:660:600"

    def levels(path: Path) -> tuple[float, float, float, float]:
        dark, light = _signal_stats(path, black), _signal_stats(path, white)
        return min(dark["YMIN"]), max(dark["YMAX"]), min(light["YMIN"]), max(light["YMAX"])

    shots = []
    for index, source_clip in enumerate((clip, None), start=1):
        target = tmp_path / f"shot_{index:02d}.mp4"
        _run(_shot_command(FFMPEG, still, source_clip, 1.9, target))
        assert levels(target) == (16, 16, 235, 235), index
        shots.append(target)

    voice = tmp_path / "voice.wav"
    _voice(voice, 3.0)
    mastered = tmp_path / "master.m4a"
    encode_master_audio(FFMPEG, voice, mastered, duration=3.0)
    film = tmp_path / "final.mp4"
    scenes = [{"duration_seconds": 1.5}, {"duration_seconds": 1.5}]
    _run(_dissolve_command(FFMPEG, shots, scenes, mastered, film, audio_filter=None))

    dark_min, dark_max, light_min, light_max = levels(film)
    # Limited range for real: nothing in the graded fields below 16 or above 235 ...
    assert dark_min >= 16 and light_max <= 235, levels(film)
    # ... and black and white sit on those levels, not near them.
    assert dark_max <= 17 and light_min >= 234, levels(film)


# --------------------------------------------------------------------------- the 24 fps timeline
# Measured on the four Nepal clips (render 2): the vendor delivers 24/1, one of them as 10-bit
# HEVC. The film was cut on a 30 fps timeline, so every fifth frame was a copy (QC measured 20%
# duplicated frames on a converted clip), and every shot dissolved into the next whether the
# script asked for it or not. These tests read the timeline back from real encodes.


def _has_encoder(name: str) -> bool:
    if FFMPEG is None:
        return False
    listed = subprocess.run(  # noqa: S603
        [FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
    )
    return f" {name} " in listed.stdout


def _vendor_clip(target: Path, *, seconds: float, ten_bit: bool, pattern: str = "testsrc2") -> None:
    """A vendor-like clip at 24/1: h264 8-bit, or 10-bit HEVC like the Nepal motion_01."""
    assert FFMPEG is not None
    codec = (
        ["-c:v", "libx265", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le"]
        if ten_bit
        else ["-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p"]
    )
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-threads",
            "2",
            "-f",
            "lavfi",
            "-i",
            f"{pattern}=size=1080x1920:rate=24:duration={seconds}",
            *codec,
            str(target),
        ]
    )


def _frame_count(path: Path, vf: str | None = None) -> int:
    """How many frames ffmpeg decodes from the file (after ``vf`` when given)."""
    assert FFMPEG is not None
    args = [FFMPEG, "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0"]
    if vf:
        args += ["-vf", vf]
    args += ["-f", "framemd5", "-"]
    out = _run(args).stdout
    return sum(1 for line in out.splitlines() if line and not line.startswith("#"))


def _run_bytes(args: list[str]) -> bytes:
    return subprocess.run(  # noqa: S603 - argument list, no shell
        args, check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=600
    ).stdout


def test_the_timeline_is_the_vendors_24_fps_and_the_final_keyframes_follow_it():
    from app.media.assembler import TIMELINE_FPS, _dissolve_command, _shot_command

    assert TIMELINE_FPS == 24
    shot = " ".join(_shot_command("ffmpeg", Path("s.png"), Path("m.mp4"), 2.5, Path("o.mp4")))
    push = " ".join(_shot_command("ffmpeg", Path("s.png"), None, 2.5, Path("o.mp4")))
    assert "fps=24" in shot and "fps=30" not in shot
    assert "-framerate 24" in push and "fps=24" in push and "fps=30" not in push
    # The trim never pads: a clip that covers its span is cut, never held on its last frame.
    assert "tpad" not in shot
    film = _dissolve_command(
        "ffmpeg",
        [Path("a.mp4"), Path("b.mp4")],
        [{"duration_seconds": 2.5}, {"duration_seconds": 2.5}],
        Path("m.m4a"),
        Path("o.mp4"),
        audio_filter=None,
    )
    assert film[film.index("-g") + 1] == "12"  # a keyframe every half second at 24 fps


@requires_toolchain
@pytest.mark.skipif(not _has_encoder("libx265"), reason="needs libx265 for a 10-bit HEVC source")
def test_24_fps_clips_one_of_them_10_bit_hevc_make_a_24_fps_8_bit_film_with_no_copied_frames(
    tmp_path: Path,
):
    from app.media.assembler import _dissolve_command, _shot_command
    from app.media.toolchain import encode_master_audio

    assert FFMPEG is not None
    eight = tmp_path / "motion_01.mp4"
    ten = tmp_path / "motion_02.mp4"
    _vendor_clip(eight, seconds=3.0, ten_bit=False)
    _vendor_clip(ten, seconds=3.0, ten_bit=True, pattern="testsrc")
    assert _stream(_probe(ten), "video")["pix_fmt"] == "yuv420p10le"

    shots = []
    for index, clip in enumerate((eight, ten), start=1):
        target = tmp_path / f"shot_{index:02d}.mp4"
        _run(_shot_command(FFMPEG, tmp_path / "unused.png", clip, 2.5, target))
        video = _stream(_probe(target), "video")
        assert video["r_frame_rate"] == "24/1" and video["pix_fmt"] == "yuv420p", video
        assert _frame_count(target) == 60
        shots.append(target)

    voice = tmp_path / "voice.wav"
    _voice(voice, 4.8)
    mastered = tmp_path / "master.m4a"
    encode_master_audio(FFMPEG, voice, mastered, duration=5.0)
    film = tmp_path / "final.mp4"
    scenes = [{"duration_seconds": 2.5}, {"duration_seconds": 2.5}]
    _run(_dissolve_command(FFMPEG, shots, scenes, mastered, film, audio_filter=None))

    video = _stream(_probe(film), "video")
    assert video["r_frame_rate"] == "24/1" and video["avg_frame_rate"] == "24/1", video
    assert video["pix_fmt"] == "yuv420p" and video["profile"] == "High"
    total = _frame_count(film)
    assert total == 120
    # mpdecimate drops every frame that repeats the one before it: none does.
    assert _frame_count(film, "mpdecimate") == total

    # The contrast that makes the test mean something: the same 24 fps clip on the old 30 fps
    # timeline copies every fifth frame, and mpdecimate finds them.
    old = tmp_path / "shot_30.mp4"
    _run(_shot_command(FFMPEG, tmp_path / "unused.png", eight, 2.5, old, fps=30))
    assert _frame_count(old, "mpdecimate") <= 0.85 * _frame_count(old)


@requires_toolchain
@pytest.mark.skipif(not _has_encoder("libx265"), reason="needs libx265 for a 10-bit HEVC source")
def test_a_10_bit_source_is_dithered_down_to_8_bits_not_banded(tmp_path: Path):
    """A 10-bit ramp four 8-bit steps wide. Truncated it is four flat bands; error diffusion
    spreads every step over the pixels around it, so most columns carry more than one level."""
    from app.media.assembler import _shot_command

    assert FFMPEG is not None
    ramp = tmp_path / "ramp.mp4"
    _run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=1080x1920:rate=24:duration=0.5,format=yuv420p10le,"
            "geq=lum='400+16*X/W':cb=512:cr=512",
            "-c:v",
            "libx265",
            "-x265-params",
            "lossless=1:log-level=error",
            "-pix_fmt",
            "yuv420p10le",
            str(ramp),
        ]
    )

    def mixed_columns(shot: Path) -> float:
        assert FFMPEG is not None
        raw = _run_bytes(
            [
                FFMPEG,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(shot),
                "-frames:v",
                "1",
                "-vf",
                "crop=1080:200:0:800,format=gray",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        width, height = 1080, 200
        columns = range(0, width, 7)
        mixed = sum(1 for x in columns if len({raw[y * width + x] for y in range(height)}) > 1)
        return mixed / len(columns)

    dithered = tmp_path / "shot_dithered.mp4"
    _run(_shot_command(FFMPEG, tmp_path / "unused.png", ramp, 0.5, dithered))
    plain = tmp_path / "shot_plain.mp4"
    _run(_shot_command(FFMPEG, tmp_path / "unused.png", ramp, 0.5, plain, dither=False))
    assert _stream(_probe(dithered), "video")["pix_fmt"] == "yuv420p"
    # Measured 2026-10-01: error diffusion mixes about 74% of the columns, swscale's ordered
    # dither about 50%; a truncation would mix only the four step edges.
    assert mixed_columns(dithered) >= 0.65
    assert mixed_columns(dithered) > mixed_columns(plain)


# --------------------------------------------------------------------------- cuts and dissolves


def test_scenes_join_by_hard_cuts_unless_the_script_asks_for_a_dissolve():
    from app.media.assembler import DISSOLVE_SECONDS, _dissolve_command, scene_joins, shot_spans

    assert 0.25 <= DISSOLVE_SECONDS <= 0.4
    scenes = [
        {"duration_seconds": 2.0, "transition_in": "DISSOLVE"},  # nothing before it to mix
        {"duration_seconds": 3.0, "transition_in": "CUT"},
        {"duration_seconds": 2.5},
        {"duration_seconds": 2.0, "transition_in": "dissolve"},
    ]
    joins = scene_joins(scenes)
    assert joins == [0.0, 0.0, 0.0, DISSOLVE_SECONDS]
    # Only the shot a dissolve leaves is longer than its scene, by exactly the dissolve.
    assert shot_spans(scenes, joins) == pytest.approx([2.0, 3.0, 2.5 + DISSOLVE_SECONDS, 2.0])

    args = _dissolve_command(
        "ffmpeg", [Path(f"s{i}.mp4") for i in range(4)], scenes, Path("m.m4a"), Path("o.mp4")
    )
    chain = args[args.index("-filter_complex") + 1]
    assert chain.count("xfade") == 1
    assert f"duration={DISSOLVE_SECONDS:.6f}" in chain and "offset=7.500000" in chain
    assert chain.count("concat=n=2") == 2
    assert "trim=end_frame=228" in chain

    # A script that names no transition is cut throughout: no xfade at all.
    plain = [{"duration_seconds": 2.0}, {"duration_seconds": 2.0}, {"duration_seconds": 2.0}]
    args = _dissolve_command(
        "ffmpeg", [Path(f"s{i}.mp4") for i in range(3)], plain, Path("m.m4a"), Path("o.mp4")
    )
    assert "xfade" not in args[args.index("-filter_complex") + 1]


@requires_toolchain
def test_a_cut_changes_the_picture_on_one_frame_and_a_dissolve_over_several(tmp_path: Path):
    from app.media.assembler import DISSOLVE_SECONDS, _dissolve_command, _shot_command, shot_spans
    from app.media.toolchain import encode_master_audio

    assert FFMPEG is not None
    scenes = [
        {"duration_seconds": 1.5},
        {"duration_seconds": 1.5, "transition_in": "CUT"},
        {"duration_seconds": 1.5, "transition_in": "DISSOLVE"},
    ]
    spans = shot_spans(scenes)
    shots = []
    for index, (colour, span) in enumerate(
        zip(("0x1A1A1A", "0x808080", "white"), spans, strict=True)
    ):
        clip = tmp_path / f"flat_{index}.mp4"
        _run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={colour}:size=1080x1920:rate=24:duration=2.5",
                "-c:v",
                "libx264",
                "-qp",
                "0",
                "-pix_fmt",
                "yuv420p",
                str(clip),
            ]
        )
        target = tmp_path / f"shot_{index}.mp4"
        _run(_shot_command(FFMPEG, tmp_path / "unused.png", clip, span, target))
        shots.append(target)
    voice = tmp_path / "voice.wav"
    _voice(voice, 4.5)
    mastered = tmp_path / "master.m4a"
    encode_master_audio(FFMPEG, voice, mastered, duration=4.5)
    film = tmp_path / "final.mp4"
    _run(_dissolve_command(FFMPEG, shots, scenes, mastered, film, audio_filter=None))

    levels = _signal_stats(film)["YAVG"]
    assert len(levels) == 108  # 4.5 s at 24 fps
    first, second, third = levels[10], levels[50], levels[100]
    # Frames that are neither one shot's level nor the next one's are mixed frames.
    cut = [y for y in levels[30:42] if min(abs(y - first), abs(y - second)) > 3]
    dissolve = [y for y in levels[66:82] if min(abs(y - second), abs(y - third)) > 3]
    assert cut == [], "the cut at 1.5 s mixes no frames"
    assert len(dissolve) >= round(DISSOLVE_SECONDS * 24) - 2, dissolve
