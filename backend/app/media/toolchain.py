"""Finding the FFmpeg toolchain, including the half of it that is not on PATH.

`ffprobe` ships in the same directory as `ffmpeg` in every distribution of it. Several Windows
installers — the WinGet package among them — put only `ffmpeg.exe` on PATH, so a studio with a
perfectly good toolchain reported that media inspection was unavailable and degraded itself while
the tool sat in the folder next door.

Resolution order, most explicit first:

1. ``STUDIO_FFPROBE_PATH`` / ``STUDIO_FFMPEG_PATH``, because an Owner who names a path means it;
2. PATH;
3. beside the resolved ``ffmpeg``, which is where it almost always is.

Nothing here runs the binaries or claims they work — it only says where they are.

The loudness half of this module is the one reading of one filter that both the renderer and
quality control use, so the two can never disagree about how loud a film is. Before it, nothing
in the studio measured loudness at all: a film left at whatever level the voice vendor returned
was a film the platform turned down or up on its own terms.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The repository root, matching how `app.config` locates the same .env file.
ROOT = Path(__file__).resolve().parents[3]

#: The .env file the settings are read from (a test points it at its own tmp file).
ENV_FILE = ROOT / ".env"

#: Windows needs the suffix; everywhere else the bare name is right.
_SUFFIXES = (".exe", "") if os.name == "nt" else ("", ".exe")


class _EncoderSetting(BaseSettings):
    """Just the encoder path, read from the same place the application's settings read it.

    Quality control is handed an asset id and an engine, not a configuration object, and
    threading the whole of `Settings` through it to locate one binary would be a worse trade
    than reading the one field here. This reads the identical source — ``STUDIO_FFMPEG_PATH``
    in the environment or in ``.env`` — without the required fields that have nothing to do
    with finding a binary.
    """

    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=ROOT / ".env", extra="ignore")

    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None


def _read_setting() -> _EncoderSetting | None:
    try:
        return _EncoderSetting(_env_file=ENV_FILE)  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001
        return None


def _configured_ffmpeg() -> str | None:
    """The Owner's configured encoder path, or None when unreadable.

    A configuration that cannot be read means we do not know where ffmpeg is, which is the same
    answer as not having one — so the failure is swallowed rather than raised into a QC run.
    """
    setting = _read_setting()
    return setting.ffmpeg_path if setting else None


def _configured_ffprobe() -> str | None:
    """STUDIO_FFPROBE_PATH, from the process environment or from .env (REL-13: it used to be
    read from the environment only, while the preflight told the Owner to set it in .env)."""
    setting = _read_setting()
    return setting.ffprobe_path if setting else None


def find_ffmpeg(configured: str | None = None) -> str | None:
    """The ffmpeg binary to use, or None when there is not one."""
    candidate = configured or _configured_ffmpeg()
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which("ffmpeg")


def find_ffprobe(
    configured_ffmpeg: str | None = None, *, configured: str | None = None
) -> str | None:
    """The ffprobe binary to use, or None when there is not one.

    ``configured`` is the studio's ffprobe setting (`Settings.ffprobe_path`) when the caller
    holds the settings; otherwise STUDIO_FFPROBE_PATH is read from the environment and .env.
    ``configured_ffmpeg`` is the studio's ffmpeg setting, used to look in the right folder when
    ffprobe is not on PATH.
    """
    explicit = configured or _configured_ffprobe()
    if explicit and Path(explicit).is_file():
        return explicit

    on_path = shutil.which("ffprobe")
    if on_path:
        return on_path

    ffmpeg = find_ffmpeg(configured_ffmpeg)
    if not ffmpeg:
        return None
    folder = Path(ffmpeg).parent
    for suffix in _SUFFIXES:
        candidate = folder / f"ffprobe{suffix}"
        if candidate.is_file():
            return str(candidate)
    return None


# --------------------------------------------------------------------------- loudness

#: The platform norm for a vertical short: YouTube and TikTok both level programme audio at
#: -14 LUFS integrated, and a film delivered louder is turned down (and one delivered quieter
#: is left quiet).
LOUDNESS_TARGET_LUFS = -14.0
#: What the normaliser aims the true peak at: a full dB under the ceiling quality control
#: holds the delivered film to. The Nepal film was normalised to -1.0 exactly, the AAC encode
#: overshot it to -0.93, and quality control refused the film for 0.07 dB. The margin is the
#: AAC encoder's overshoot, measured on the delivered file, never assumed away.
TRUE_PEAK_TARGET_DBTP = -2.0
#: The loudness range the filter may leave in place. loudnorm falls back from a linear gain to
#: its dynamic mode whenever the input's range exceeds this, and a dynamic pass pumps speech;
#: narration measures 5–9 LU, so 11 keeps the gain linear for every voice the studio has met.
LOUDNESS_RANGE_LU = 11.0

#: What quality control accepts: two LU either side of the target, and nothing over the
#: ceiling. Wider than the filter's own precision (about 0.5 LU) because the film is measured
#: after the AAC encode, which moves the reading a little. The ceiling is not the target:
#: the target is aimed under it (see TRUE_PEAK_TARGET_DBTP).
LOUDNESS_BAND_LUFS = (-16.0, -12.0)
TRUE_PEAK_CEILING_DBTP = -1.0

#: The sample-peak limit after the normaliser, as a fraction of full scale: 0.79 is -2.05 dBFS,
#: the target, not the ceiling. loudnorm limits true peaks only in its dynamic mode; in its
#: linear mode, and after the resample back to 48 kHz, nothing else holds the peaks.
LIMITER_LIMIT = 0.79
#: The one sample rate the master works at and is delivered at.
MASTER_SAMPLE_RATE = 48000
#: The film's audio, encoded once: AAC-LC, 256 kb/s, stereo, 48 kHz. The narration used to be
#: encoded to AAC when the takes were joined and again when the film was encoded.
AUDIO_CODEC_ARGS: tuple[str, ...] = (
    "-c:a",
    "aac",
    "-profile:a",
    "aac_low",
    "-b:a",
    "256k",
    "-ac",
    "2",
    "-ar",
    str(MASTER_SAMPLE_RATE),
)
#: How the codec above is written down in a render's manifest.
AUDIO_CODEC_LABEL = "aac-lc 256k stereo 48 kHz"

#: How long the measurement of one film may take. A minute of narration measures in a second.
_MEASURE_TIMEOUT_SECONDS = 300

_LOUDNORM_REPORT = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def parse_loudnorm_json(stderr: str) -> dict[str, float | str | dict] | None:
    """The loudnorm filter's own report, read out of the encoder's stderr.

    With ``print_format=json`` the filter prints one JSON object of quoted numbers among the
    encoder's chatter; this finds it and turns it into readings. None when there is no report
    — chatter without a measurement is never a number. A silent input measures as ``-inf``,
    which is a reading too: there is nothing to normalise.
    """
    match = _LOUDNORM_REPORT.search(stderr or "")
    if match is None:
        return None
    try:
        raw = json.loads(match.group(0))
    except ValueError:
        return None

    def number(key: str) -> float:
        try:
            return float(raw.get(key))
        except (TypeError, ValueError):
            return math.nan

    return {
        "integrated_lufs": number("input_i"),
        "true_peak_dbtp": number("input_tp"),
        "loudness_range_lu": number("input_lra"),
        "threshold_lufs": number("input_thresh"),
        "target_offset_lu": number("target_offset"),
        "normalization_type": str(raw.get("normalization_type") or ""),
        "output": {
            "integrated_lufs": number("output_i"),
            "true_peak_dbtp": number("output_tp"),
            "loudness_range_lu": number("output_lra"),
            "threshold_lufs": number("output_thresh"),
        },
    }


def _measured_is_usable(measured: dict | None) -> bool:
    """A first-pass measurement can steer a second pass only when every reading is a number."""
    if not measured:
        return False
    keys = ("integrated_lufs", "true_peak_dbtp", "loudness_range_lu", "threshold_lufs")
    return all(
        isinstance(measured.get(key), int | float) and math.isfinite(float(measured[key]))
        for key in keys
    )


def loudnorm_filter(measured: dict | None) -> str:
    """The normalising filter: two-pass linear gain from a measurement, one pass without.

    The one-pass filter normalises as it goes, with a three-second window, which is what a
    live broadcast does and audibly breathes on speech. Given the film's own first-pass
    measurement the filter applies one linear gain to the whole film instead, and the picture
    of the voice is left exactly as the narrator made it, only at the right level. The report
    is printed either way, so the encode's log carries the output reading.
    """
    base = (
        f"loudnorm=I={LOUDNESS_TARGET_LUFS:.1f}:TP={TRUE_PEAK_TARGET_DBTP:.1f}"
        f":LRA={LOUDNESS_RANGE_LU:.1f}"
    )
    if not _measured_is_usable(measured):
        # linear=true asks for the linear gain whenever the filter can give it; without a
        # measurement it cannot, the report then says "dynamic", and the master records it.
        return f"{base}:linear=true:print_format=json"
    assert measured is not None
    offset = measured.get("target_offset_lu")
    offset_value = (
        float(offset) if isinstance(offset, int | float) and math.isfinite(offset) else 0.0
    )
    return (
        f"{base}:measured_I={float(measured['integrated_lufs']):.2f}"
        f":measured_TP={float(measured['true_peak_dbtp']):.2f}"
        f":measured_LRA={float(measured['loudness_range_lu']):.2f}"
        f":measured_thresh={float(measured['threshold_lufs']):.2f}"
        f":offset={offset_value:.2f}:linear=true:print_format=json"
    )


def measure_loudness(ffmpeg: str | None, path: Path | str) -> dict | None:
    """Measure a file's loudness with the same filter that normalises it, or None.

    None when there is no encoder, no file, or the encoder could not read it — this measures,
    it never invents a reading. The filter is run at the studio's targets so the report's
    output half says what a one-pass normalisation of this file would have produced.
    """
    if not ffmpeg or not Path(path).is_file():
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-v",
                "info",
                "-nostats",
                "-i",
                str(path),
                "-vn",
                "-af",
                loudnorm_filter(None),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=_MEASURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_loudnorm_json(result.stderr)


@lru_cache(maxsize=32)
def has_filter(ffmpeg: str | None, name: str) -> bool:
    """Whether this encoder was built with the named filter.

    Asked once per encoder and filter: the answer is a property of the binary, and the renderer
    asks it for every film. A build without ``loudnorm`` or ``subtitles`` is answered honestly
    so the render records what it could not do instead of failing on an unknown filter.
    """
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for line in (result.stdout or "").splitlines():
        columns = line.split()
        # A row reads "flags name inputs->outputs description"; the flag column is present
        # on every filter row, so the name is always the second token.
        if len(columns) >= 3 and columns[1] == name:
            return True
    return False


# --------------------------------------------------------------------------- the master


class AudioMasterError(RuntimeError):
    """The narration could not be mastered: the encoder failed, or wrote nothing."""


def limiter_filter() -> str:
    """The sample limiter after the normaliser, with its automatic level switched off.

    ``level`` defaults to on in ffmpeg, and it would normalise the limited signal back up to
    the limit — undoing the loudness the pass before it set.
    """
    return f"alimiter=limit={LIMITER_LIMIT:.2f}:level=0"


def master_audio_filter(
    measured: dict | None, *, duration: float | None = None, normalise: bool = True
) -> str:
    """The master's whole audio chain: loudness, back to 48 kHz, the limiter, then the length.

    loudnorm works at 192 kHz internally and hands that on, so the resample comes after it
    and before the limiter, which then holds the peaks at the rate that is delivered. With a
    ``duration`` the track is padded with silence to it and cut there, so the audio is exactly
    as long as the picture it goes under. ``normalise`` is False for an encoder built without
    loudnorm, which still gets the resample and the limiter.
    """
    steps = [loudnorm_filter(measured)] if normalise else []
    steps += [f"aresample={MASTER_SAMPLE_RATE}", limiter_filter()]
    if duration is not None and duration > 0:
        steps += [f"apad=whole_dur={duration:.3f}", f"atrim=duration={duration:.3f}"]
    return ",".join(steps)


def loudnorm_warning(report: dict | None) -> str | None:
    """The Owner's warning when loudnorm gave up its linear gain, or None.

    In dynamic mode the filter rides the level through the film on a three-second window,
    which is audible on speech as breathing. It happens when the narration's peaks or range
    leave no room for one gain; the film still measures in band, so it is a warning, not a
    failure — but he should hear it before it goes out. No report means nothing is known.
    """
    if not report or str(report.get("normalization_type") or "") != "dynamic":
        return None
    return (
        "Sunetul a fost nivelat în mod dinamic: loudnorm nu a putut aplica un singur câștig "
        "liniar pe toată narațiunea, iar vocea poate să „respire”. Ascultați filmul înainte "
        "de publicare."
    )


#: The pre-limiter's ceiling: 0.5 dB under the true-peak target, because alimiter holds
#: sample peaks and the true peak between samples reads a little higher.
PRELIMIT_LIMIT = round(10 ** ((TRUE_PEAK_TARGET_DBTP - 0.5) / 20), 3)
#: How close the pre-limited narration must land to the target before the master pass.
PRELIMIT_TOLERANCE_LU = 0.3
PRELIMIT_ROUNDS = 3


def prelimit_gain(measured: dict | None) -> float | None:
    """The gain that brings a quiet narration to the target when one linear gain would push
    its peaks over the true-peak target; None when one linear gain fits (or nothing is known).

    ElevenLabs takes measure -23 to -25 LUFS with peaks of -3 to -6 dBTP: +10 dB of gain
    leaves no headroom, loudnorm falls back to dynamic mode and undershoots by 1.5 LU.
    """
    if not _measured_is_usable(measured):
        return None
    assert measured is not None
    gain = LOUDNESS_TARGET_LUFS - float(measured["integrated_lufs"])
    if gain <= 0 or float(measured["true_peak_dbtp"]) + gain <= TRUE_PEAK_TARGET_DBTP:
        return None
    return gain


#: Dual mono at full level against the same mono channel, as BS.1770 sums the channels.
MONO_TO_STEREO_LU = 3.01


def _channels(ffmpeg: str, source: Path | str) -> int | None:
    """How many channels the source's first audio stream has; None when it cannot be read."""
    ffprobe = find_ffprobe(ffmpeg)
    if not ffprobe:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels",
                "-of",
                "csv=p=0",
                str(source),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or "").strip().splitlines()
    return int(text[0]) if text and text[0].strip().isdigit() else None


def _prelimit(
    ffmpeg: str, source: Path | str, work: Path, gain: float, timeout: int
) -> tuple[dict, list[float]]:
    """Raise the narration by ``gain`` with a fast look-ahead limiter holding its peaks, and
    correct the gain until it measures at the target. Returns the last reading and the
    gains tried; the limited narration is written to ``work`` (lossless WAV)."""
    gains: list[float] = []
    # A mono narration goes stereo first, at full level on both sides: the encoder's default
    # upmix lowers each side 3 dB, so limiting in mono would cost 3 dB more limiting than the
    # delivered film needs. Stereo at full level reads 3 LU louder, hence the smaller gain.
    mono = _channels(ffmpeg, source) == 1
    upmix = "pan=stereo|c0=c0|c1=c0," if mono else ""
    current = gain - MONO_TO_STEREO_LU if mono else gain
    reading: dict | None = None
    for _ in range(PRELIMIT_ROUNDS):
        gains.append(round(current, 2))
        chain = (
            f"{upmix}aresample={MASTER_SAMPLE_RATE},volume={current:.2f}dB,"
            f"alimiter=limit={PRELIMIT_LIMIT:.3f}:attack=1:release=10:level=0"
        )
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-af",
                chain,
                "-c:a",
                "pcm_s24le",
                str(work),
            ],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0 or not work.is_file():
            raise AudioMasterError(
                f"FFmpeg could not limit the narration (exit code {result.returncode})"
            )
        reading = measure_loudness(ffmpeg, work)
        if not _measured_is_usable(reading):
            raise AudioMasterError("The limited narration could not be measured")
        assert reading is not None
        miss = LOUDNESS_TARGET_LUFS - float(reading["integrated_lufs"])
        if abs(miss) <= PRELIMIT_TOLERANCE_LU:
            break
        current += miss
    assert reading is not None
    return reading, gains


def encode_master_audio(
    ffmpeg: str,
    source: Path | str,
    target: Path | str,
    *,
    duration: float | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """Master the joined narration into the film's audio track, encoded once.

    First pass: the source is measured. Second pass: one linear gain from that measurement
    (loudnorm falls back to dynamic mode when it cannot), 48 kHz, the limiter, and the AAC
    encode. The delivered file is then measured again, because the AAC encode moves the true
    peak and that is the reading quality control will take. Raises AudioMasterError when the
    encoder fails; it never returns a track it did not write.
    """
    normalise = has_filter(ffmpeg, "loudnorm")
    measured = measure_loudness(ffmpeg, source) if normalise else None
    # Quiet narration with hot peaks: limit first, so the master pass is one linear gain.
    prelimit: dict[str, Any] | None = None
    gain = prelimit_gain(measured) if normalise else None
    work = Path(target).with_name(Path(target).stem + ".prelimit.wav")
    if gain is not None:
        measured, gains = _prelimit(ffmpeg, source, work, gain, timeout)
        prelimit = {
            "gain_db": gains[-1],
            "gains_tried_db": gains,
            "limit": PRELIMIT_LIMIT,
            "measured": measured,
        }
        source = work
    chain = master_audio_filter(measured, duration=duration, normalise=normalise)
    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "info",
        "-nostats",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-af",
        chain,
        *AUDIO_CODEC_ARGS,
        str(target),
    ]
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            command,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioMasterError(f"FFmpeg could not master the narration: {exc}") from exc
    written = Path(target)
    if result.returncode != 0 or not written.is_file() or written.stat().st_size == 0:
        raise AudioMasterError(
            f"FFmpeg could not master the narration (exit code {result.returncode})"
        )
    report = parse_loudnorm_json(result.stderr) if normalise else None
    normalization_type = str((report or {}).get("normalization_type") or "") or None
    if prelimit is not None:
        work.unlink(missing_ok=True)
    return {
        "applied": normalise,
        "prelimit": prelimit,
        "passes": (2 if "measured_I=" in chain else 1) if normalise else 0,
        "filter": chain,
        "command": command,
        "measured": measured,
        "report": report,
        "normalization_type": normalization_type,
        "delivered": measure_loudness(ffmpeg, written),
        "warning": loudnorm_warning(report),
    }


# --------------------------------------------------------------------------- dead air and the bed
#
# Measured on the rehearsal film (2026-10-01, audit Q1/Q4): every cut carried 0.28-0.61 s of
# digital silence (-87 dB), the voice vendor's own trailing silence plus the timeline's
# breath, and nothing sat under the narration. A take's silent edges are now measured and cut
# before the scene lengths are computed, and a licensed bed (`app.media.music_library`) is
# ducked under the voice before the master.

#: What counts as silence at a take's edges and inside the narration: under -45 dBFS for at
#: least 50 ms. A breath between two words reads around -40 to -30 dB and is kept.
SILENCE_THRESHOLD_DB = -45.0
SILENCE_MIN_SECONDS = 0.05
#: How much of a take's measured silence is kept before its first sound and after its last:
#: a consonant's attack and a word's decay sit under the threshold and must not be clipped.
EDGE_KEEP_SECONDS = 0.03

#: Where the bed sits under the voice, as integrated loudness: 20 LU under (QC accepts
#: 18-22), so the words always lead. Measured on the ducked, faded bed against the voice as it
#: is heard in the mix (stereo, full level on both sides).
BED_UNDER_VOICE_LU = 20.0
BED_UNDER_VOICE_BAND_LU = (18.0, 22.0)
BED_FADE_IN_SECONDS = 0.3
BED_FADE_OUT_SECONDS = 0.8
#: The ducking: keyed by the voice, the bed drops while a word is said and comes back up in
#: the pauses, over 15 ms down and 350 ms back.
DUCK_FILTER = "sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350:knee=4"
#: An ambience sits under the voice at about -30 LUFS once the film is mastered at -14.
AMBIENCE_UNDER_VOICE_LU = 16.0
AMBIENCE_FADE_SECONDS = 0.15
#: The three levels a sound plan may ask of the bed per scene (`app.media.sound_design`):
#: "under" (where it always is), "soft" (6 dB further down: the words stand alone) and "lift"
#: (8 dB up, and only inside a silence of the voice). The Owner, 2026-10-11: «să fie încet sau
#: tare, acolo unde trebuie. Mare grijă totuși să nu acopere vocea.»
LEVEL_GAIN_DB: dict[str, float] = {"under": 0.0, "soft": -6.0, "lift": 8.0}
#: How long the bed takes to move between two levels, inside the span that asks for it.
LEVEL_RAMP_SECONDS = 0.4
#: A silence of the voice a lift may use: under -35 dBFS for at least 0.8 s. A pause between
#: two sentences reads 0.3-0.6 s and is left to the ducking; the head before the first word and
#: the tail after the last count as silence. The lift keeps clear of the words at both ends.
LIFT_SILENCE_DB = -35.0
LIFT_SILENCE_MIN_SECONDS = 0.8
LIFT_EDGE_GUARD_SECONDS = 0.1
#: What a sound plan may ask of the bed's fades, in seconds.
BED_FADE_BOUNDS = (0.3, 4.0)
#: The least of a film's speech or silence a loudness can be read from (one gating block).
MIN_MEASURE_SECONDS = 0.5
#: How many spans a selection may name before the measure falls back to the whole file.
MAX_MEASURE_SPANS = 120
#: Ten-millisecond frames, so a span's edges land within 10 ms of where the voice has them.
_SELECT_FRAME_SAMPLES = 480
#: How far a track may be turned down or up to sit where it belongs. A mastered music track
#: (-8 to -14 LUFS) goes 30-40 dB down under a vendor's narration (-23 to -25 LUFS); a track
#: that would need more than +30 dB is silence or a broken file, not a quiet track.
MAX_LEVEL_CUT_DB = 60.0
MAX_LEVEL_BOOST_DB = 30.0
#: The mix's own ceiling, under full scale, so summing a bed never clips the stem.
MIX_LIMIT = 0.97

_SILENCE_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[0-9.]+)")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class AudioMixError(RuntimeError):
    """The bed or the ambience could not be mixed under the voice."""


def silence_spans(
    ffmpeg: str | None,
    path: Path | str,
    *,
    threshold_db: float = SILENCE_THRESHOLD_DB,
    min_seconds: float = SILENCE_MIN_SECONDS,
) -> list[tuple[float, float]] | None:
    """Every silence in ``path`` (its first audio stream) as (start, end) seconds, read from
    FFmpeg's silencedetect. A silence still open at the end ends at the file's duration. None
    when the file cannot be read: this measures, it never invents a reading."""
    if not ffmpeg or not Path(path).is_file():
        return None
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "info",
                "-nostats",
                "-i",
                str(path),
                "-vn",
                "-af",
                f"silencedetect=noise={threshold_db:.1f}dB:d={min_seconds:.3f}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_MEASURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    duration_match = _DURATION.search(result.stderr or "")
    duration = (
        int(duration_match.group(1)) * 3600
        + int(duration_match.group(2)) * 60
        + float(duration_match.group(3))
        if duration_match
        else None
    )
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for line in (result.stderr or "").splitlines():
        opened = _SILENCE_START.search(line)
        if opened:
            start = max(0.0, float(opened.group(1)))
            continue
        closed = _SILENCE_END.search(line)
        if closed and start is not None:
            spans.append((start, float(closed.group(1))))
            start = None
    if start is not None:
        spans.append((start, duration if duration is not None else start))
    return spans


def speech_edges(ffmpeg: str | None, path: Path | str, duration: float) -> tuple[float, float]:
    """(silence before the first sound, silence after the last) of a take ``duration`` long,
    in seconds; (0, 0) when nothing could be measured or the take is silence throughout."""
    spans = silence_spans(ffmpeg, path)
    if not spans:
        return 0.0, 0.0
    lead = spans[0][1] if spans[0][0] <= 0.005 else 0.0
    trail = duration - spans[-1][0] if spans[-1][1] >= duration - 0.02 else 0.0
    if lead + trail >= duration:  # nothing but silence: there is nothing to keep apart
        return 0.0, 0.0
    return max(0.0, lead), max(0.0, trail)


# ----------------------------------------------------------------- where the voice is silent
#
# The sound plan (2026-10-11, `app.media.sound_design`) asks the bed to rise only where nobody
# speaks. Where that is comes from the voice itself, never from the plan's word: the silences
# silencedetect finds, the speech their complement. The same spans are what the bed is
# measured in afterwards, so the number quality control judges (the bed under the words) is
# read where the words are.

Span = tuple[float, float]


def merge_spans(spans: Sequence[Span]) -> list[Span]:
    """``spans`` sorted and joined where they touch or overlap, each kept only when it lasts."""
    merged: list[Span] = []
    for start, end in sorted((float(a), float(b)) for a, b in spans):
        if end - start < 0.01:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def complement_spans(spans: Sequence[Span], duration: float) -> list[Span]:
    """The parts of [0, ``duration``] outside ``spans``, each at least 10 ms long."""
    out: list[Span] = []
    cursor = 0.0
    for start, end in merge_spans(spans):
        if start - cursor >= 0.01:
            out.append((cursor, min(start, duration)))
        cursor = max(cursor, end)
    if duration - cursor >= 0.01:
        out.append((cursor, duration))
    return [(a, b) for a, b in out if b - a >= 0.01]


def speech_and_gaps(
    ffmpeg: str | None, voice: Path | str, duration: float
) -> tuple[list[Span], list[Span], bool]:
    """(the voice's speech spans, its silences, whether they were measured) over ``duration``.

    The silences are what silencedetect finds at LIFT_SILENCE_DB for LIFT_SILENCE_MIN_SECONDS;
    the speech is their complement. When the voice cannot be read the whole film is speech and
    there is no gap: nothing is lifted, and the record says the silences were not measured."""
    silences = silence_spans(
        ffmpeg, voice, threshold_db=LIFT_SILENCE_DB, min_seconds=LIFT_SILENCE_MIN_SECONDS
    )
    if silences is None:
        return [(0.0, duration)], [], False
    gaps = [(max(0.0, a), min(duration, b)) for a, b in merge_spans(silences) if b > a]
    gaps = [(a, b) for a, b in gaps if b - a >= 0.01]
    return complement_spans(gaps, duration), gaps, True


def level_segments(
    levels: Sequence[Mapping[str, Any]], gaps: Sequence[Span], duration: float
) -> list[tuple[float, float, float]]:
    """Where the bed leaves its level, as (start, end, gain dB): a "soft" scene over its whole
    span; a "lift" only inside the voice's silences that fall in the scene, clear of the words
    by LIFT_EDGE_GUARD_SECONDS at both ends. "under" asks nothing."""
    segments: list[tuple[float, float, float]] = []
    for item in levels:
        level = str(item.get("level") or "under").strip().lower()
        gain = LEVEL_GAIN_DB.get(level, 0.0)
        start = max(0.0, float(item.get("start") or 0.0))
        end = min(duration, start + float(item.get("seconds") or 0.0))
        if gain == 0.0 or end - start < 0.05:
            continue
        if level != "lift":
            segments.append((start, end, gain))
            continue
        for gap_start, gap_end in gaps:
            low = max(gap_start, start) + LIFT_EDGE_GUARD_SECONDS
            high = min(gap_end, end) - LIFT_EDGE_GUARD_SECONDS
            if high - low >= 0.3:
                segments.append((low, high, gain))
    return segments


def level_expression(
    segments: Sequence[tuple[float, float, float]], ramp: float = LEVEL_RAMP_SECONDS
) -> str | None:
    """The `volume` filter's expression for ``segments``: each a trapezoid of its gain, up over
    ``ramp`` seconds from its start and down over ``ramp`` to its end (a segment shorter than
    two ramps peaks in the middle), summed in dB and turned into a gain. None without one."""
    if not segments:
        return None
    terms = [
        f"{gain:.1f}*clip(min(t-{start:.3f},{end:.3f}-t)/{ramp:.3f},0,1)"
        for start, end, gain in segments
    ]
    return f"pow(10,({'+'.join(terms)})/20)"


def _selection(spans: Sequence[Span]) -> str:
    """The filters that keep only ``spans`` of a stream, timestamps made continuous again."""
    inside = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
    return f"asetnsamples=n={_SELECT_FRAME_SAMPLES},aselect='{inside}',asetpts=N/SR/TB"


def measure_loudness_in(ffmpeg: str | None, path: Path | str, spans: Sequence[Span]) -> dict | None:
    """`measure_loudness` of the parts of ``path`` inside ``spans``, joined end to end. None
    when there is nothing long enough to read (under MIN_MEASURE_SECONDS in all), or the file
    cannot be read; the whole file when the spans are too many to name (MAX_MEASURE_SPANS)."""
    kept = merge_spans(spans)
    if not ffmpeg or not Path(path).is_file():
        return None
    if sum(b - a for a, b in kept) < MIN_MEASURE_SECONDS:
        return None
    if len(kept) > MAX_MEASURE_SPANS:
        return measure_loudness(ffmpeg, path)
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "info",
                "-nostats",
                "-i",
                str(path),
                "-vn",
                "-af",
                f"{_selection(kept)},{loudnorm_filter(None)}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_MEASURE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_loudnorm_json(result.stderr)


def _run_mix(ffmpeg: str, command: list[str], what: str, timeout: int) -> None:
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [ffmpeg, "-nostdin", "-v", "error", "-y", *command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioMixError(f"FFmpeg could not {what}: {exc}") from exc
    output = Path(command[-1])
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise AudioMixError(f"FFmpeg could not {what} (exit code {result.returncode})")


def _integrated(ffmpeg: str, path: Path | str, what: str) -> float:
    reading = measure_loudness(ffmpeg, path)
    value = reading.get("integrated_lufs") if reading else None
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise AudioMixError(f"The {what} could not be measured")
    return float(value)


def _integrated_in(ffmpeg: str, path: Path | str, spans: Sequence[Span], what: str) -> float:
    """The integrated loudness of ``path`` inside ``spans``; the whole file when the spans
    cover it. Raises AudioMixError when it cannot be read: the correction needs a number."""
    reading = measure_loudness_in(ffmpeg, path, spans)
    value = reading.get("integrated_lufs") if reading else None
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        raise AudioMixError(f"The {what} could not be measured where the voice speaks")
    return float(value)


def _loudness_in(ffmpeg: str, path: Path | str, spans: Sequence[Span]) -> float | None:
    """`_integrated_in` for a reading that may be absent (the gaps of a voice that never
    pauses): None instead of an error."""
    reading = measure_loudness_in(ffmpeg, path, spans)
    value = reading.get("integrated_lufs") if reading else None
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        return None
    return float(value)


def _level_counts(levels: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {level: 0 for level in LEVEL_GAIN_DB}
    for item in levels:
        level = str(item.get("level") or "under").strip().lower()
        counts[level if level in counts else "under"] += 1
    return counts


def _stereo(position: int) -> str:
    """Input ``position`` at the master's rate, as stereo at full level on both sides."""
    return (
        f"[{position}:a]aresample={MASTER_SAMPLE_RATE},"
        "aformat=sample_fmts=fltp:channel_layouts=stereo"
    )


def _correction(target: float, measured: float, what: str) -> float:
    gain = target - measured
    if not -MAX_LEVEL_CUT_DB <= gain <= MAX_LEVEL_BOOST_DB:
        raise AudioMixError(f"The {what} would need {gain:+.1f} dB: its level is not usable")
    return gain


_STEM_ARGS: tuple[str, ...] = ("-c:a", "pcm_s24le", "-ar", str(MASTER_SAMPLE_RATE), "-ac", "2")


def mix_bed(
    ffmpeg: str,
    voice: Path | str,
    target: Path | str,
    *,
    bed: Path | str | None,
    duration: float,
    work_dir: Path | str,
    ambience: list[dict[str, Any]] | None = None,
    under_lu: float = BED_UNDER_VOICE_LU,
    fade_in: float = BED_FADE_IN_SECONDS,
    fade_out: float = BED_FADE_OUT_SECONDS,
    timeout: int = 600,
    levels: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The narration with a bed ducked under it, and any ambience, as one stem for the master.

    Without a bed and without ambience the voice is returned as it is (``path`` is ``voice``).
    Otherwise:

    1. the voice is taken to stereo at full level (as the master hears it) and measured;
    2. the bed is looped or cut to ``duration``, set ``under_lu`` under the voice, ducked by
       the voice (sidechaincompress), faded in over ``fade_in`` and out over ``fade_out``;
    3. the ducked bed is measured and corrected with one linear gain, so it lands at
       ``under_lu`` under the voice whatever the ducking took away, and kept as its own stem;
    4. each ambience ({"path", "start", "seconds"}) is set AMBIENCE_UNDER_VOICE_LU under the
       voice, faded at its edges and placed at its scene;
    5. everything is summed at unity (no automatic rescaling) under a sample ceiling.

    ``levels`` is the sound plan's level per scene ({"start", "seconds", "level"}, the levels
    of LEVEL_GAIN_DB; `app.media.sound_design`). With one, the bed is shaped by time before
    the ducking (`level_segments`, `level_expression`): "soft" over its scene, "lift" only
    inside the voice's own silences (`speech_and_gaps`), never under a word. The correction
    then lands the bed ``under_lu`` under the voice WHERE THE VOICE SPEAKS, not over the whole
    film (a lifted gap would otherwise pull the words' bed down), and the record carries the
    measure that matters, ``measured_lu_under_voice_in_speech``, beside the whole-film one and
    the bed's level in the gaps (``measured_lu_under_voice_in_gaps``, where a lift shows).
    Without ``levels`` the mix is as it was before the plan existed, judged over the film.

    Returns {"path", "bed": {...} | None, "ambience": [...]}. Raises AudioMixError; never a
    stem it did not write.
    """
    folder = Path(work_dir)
    ambience = [item for item in (ambience or []) if Path(item["path"]).is_file()]
    if bed is None and not ambience:
        return {"path": Path(voice), "bed": None, "ambience": []}
    low_fade, high_fade = BED_FADE_BOUNDS
    fade_in = min(max(float(fade_in), low_fade), high_fade, max(0.05, duration / 2))
    fade_out = min(max(float(fade_out), low_fade), high_fade, max(0.05, duration / 2))
    seconds = f"{duration:.3f}"
    voice_stereo = folder / "mix_voice_stereo.wav"
    mono = _channels(ffmpeg, voice) == 1
    upmix = "pan=stereo|c0=c0|c1=c0," if mono else ""
    _run_mix(
        ffmpeg,
        [
            "-i",
            str(voice),
            "-af",
            f"{upmix}aresample={MASTER_SAMPLE_RATE},apad=whole_dur={seconds},atrim=duration={seconds}",
            *_STEM_ARGS,
            str(voice_stereo),
        ],
        "take the voice to stereo",
        timeout,
    )
    voice_lufs = _integrated(ffmpeg, voice_stereo, "voice")
    planned = levels is not None
    speech: list[Span] = [(0.0, duration)]
    gaps: list[Span] = []
    silences_measured = False
    if planned:
        speech, gaps, silences_measured = speech_and_gaps(ffmpeg, voice_stereo, duration)
    stems: list[Path] = []
    bed_record: dict[str, Any] | None = None
    if bed is not None:
        raw_lufs = _integrated(ffmpeg, bed, "bed")
        pre = _correction(voice_lufs - under_lu, raw_lufs, "bed")
        segments = level_segments(levels or [], gaps, duration) if planned else []
        shaping = level_expression(segments)
        shape = f"volume='{shaping}':eval=frame," if shaping else ""
        ducked = folder / "mix_bed_ducked.wav"
        out_at = max(0.0, duration - fade_out)
        _run_mix(
            ffmpeg,
            [
                "-stream_loop",
                "-1",
                "-i",
                str(bed),
                "-i",
                str(voice_stereo),
                "-filter_complex",
                # The bed runs a second past the film and the key never ends: the compressor
                # drops its last partial block at an input's end, so the cut comes after it.
                # The plan's shaping sits on the film's own clock (after asetpts), before the
                # ducking, which reads only the voice and so ducks the shaped bed the same.
                f"{_stereo(0)},atrim=duration={duration + 1.0:.3f},asetpts=N/SR/TB,"
                f"volume={pre:.2f}dB,{shape}aformat=sample_fmts=fltp[b];{_stereo(1)},apad[k];"
                f"[b][k]{DUCK_FILTER},"
                f"atrim=duration={seconds},afade=t=in:st=0:d={fade_in:.3f},"
                f"afade=t=out:st={out_at:.3f}:d={fade_out:.3f}[out]",
                "-map",
                "[out]",
                "-t",
                seconds,
                *_STEM_ARGS,
                str(ducked),
            ],
            "duck the bed under the voice",
            timeout,
        )
        if planned:
            # Corrected where the words are: the voice and the ducked bed read in the same
            # speech spans, so a lift in the gaps cannot pull the bed under the words down.
            voice_ref = _integrated_in(ffmpeg, voice_stereo, speech, "voice")
            ducked_ref = _integrated_in(ffmpeg, ducked, speech, "ducked bed")
        else:
            voice_ref, ducked_ref = voice_lufs, _integrated(ffmpeg, ducked, "ducked bed")
        fix = _correction(voice_ref - under_lu, ducked_ref, "ducked bed")
        stem = folder / "mix_bed.wav"
        _run_mix(
            ffmpeg,
            ["-i", str(ducked), "-af", f"volume={fix:.2f}dB", *_STEM_ARGS, str(stem)],
            "set the bed's level",
            timeout,
        )
        ducked.unlink(missing_ok=True)
        bed_lufs = _integrated(ffmpeg, stem, "bed")
        stems.append(stem)
        bed_record = {
            "stem": str(stem),
            "voice_lufs": round(voice_lufs, 2),
            "bed_lufs": round(bed_lufs, 2),
            "measured_lu_under_voice": round(voice_lufs - bed_lufs, 2),
            "target_lu_under_voice": under_lu,
            "gain_db": round(pre + fix, 2),
            "ducking": DUCK_FILTER,
            "fade_in_seconds": fade_in,
            "fade_out_seconds": fade_out,
        }
        if planned:
            bed_speech = _integrated_in(ffmpeg, stem, speech, "bed")
            bed_gaps = _loudness_in(ffmpeg, stem, gaps)
            lifted = [(a, b) for a, b, gain in segments if gain > 0]
            bed_record.update(
                {
                    "corrected_in": "speech",
                    "voice_speech_lufs": round(voice_ref, 2),
                    "bed_speech_lufs": round(bed_speech, 2),
                    "measured_lu_under_voice_in_speech": round(voice_ref - bed_speech, 2),
                    "bed_gaps_lufs": round(bed_gaps, 2) if bed_gaps is not None else None,
                    "measured_lu_under_voice_in_gaps": (
                        round(voice_ref - bed_gaps, 2) if bed_gaps is not None else None
                    ),
                    "speech_seconds": round(sum(b - a for a, b in speech), 2),
                    "gap_seconds": round(sum(b - a for a, b in gaps), 2),
                    "voice_silences_measured": silences_measured,
                    "levels": _level_counts(levels or []),
                    "lift_spans": [[round(a, 2), round(b, 2)] for a, b in lifted[:40]],
                    "lifted_seconds": round(sum(b - a for a, b in lifted), 2),
                    "soft_seconds": round(sum(b - a for a, b, gain in segments if gain < 0), 2),
                }
            )
    placed: list[dict[str, Any]] = []
    for position, item in enumerate(ambience):
        start = max(0.0, float(item.get("start") or 0.0))
        length = max(0.1, min(float(item.get("seconds") or 0.0), duration - start))
        gain = _correction(
            voice_lufs - AMBIENCE_UNDER_VOICE_LU,
            _integrated(ffmpeg, item["path"], "ambience"),
            "ambience",
        )
        stem = folder / f"mix_ambience_{position + 1:02d}.wav"
        fade = min(AMBIENCE_FADE_SECONDS, length / 4)
        delay = int(round(start * 1000))
        _run_mix(
            ffmpeg,
            [
                "-stream_loop",
                "-1",
                "-i",
                str(item["path"]),
                "-filter_complex",
                f"{_stereo(0)},atrim=duration={length:.3f},asetpts=N/SR/TB,volume={gain:.2f}dB,"
                f"afade=t=in:st=0:d={fade:.3f},afade=t=out:st={length - fade:.3f}:d={fade:.3f},"
                f"adelay={delay}|{delay},apad=whole_dur={seconds},atrim=duration={seconds}[out]",
                "-map",
                "[out]",
                "-t",
                seconds,
                *_STEM_ARGS,
                str(stem),
            ],
            "place the ambience",
            timeout,
        )
        stems.append(stem)
        placed.append(
            {
                **{k: v for k, v in item.items() if k != "path"},
                "start": round(start, 3),
                "seconds": round(length, 3),
                "gain_db": round(gain, 2),
                "stem": str(stem),
            }
        )
    inputs: list[str] = ["-i", str(voice_stereo)]
    for stem in stems:
        inputs += ["-i", str(stem)]
    labels = "".join(f"[{position}:a]" for position in range(len(stems) + 1))
    _run_mix(
        ffmpeg,
        [
            *inputs,
            "-filter_complex",
            f"{labels}amix=inputs={len(stems) + 1}:normalize=0:duration=first,"
            f"alimiter=limit={MIX_LIMIT:.2f}:attack=1:release=20:level=0[out]",
            "-map",
            "[out]",
            "-t",
            seconds,
            *_STEM_ARGS,
            str(target),
        ],
        "mix the bed under the voice",
        timeout,
    )
    voice_stereo.unlink(missing_ok=True)
    return {"path": Path(target), "bed": bed_record, "ambience": placed}
