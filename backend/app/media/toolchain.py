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
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The repository root, matching how `app.config` locates the same .env file.
ROOT = Path(__file__).resolve().parents[3]

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


def _configured_ffmpeg() -> str | None:
    """The Owner's configured encoder path, or None when unreadable.

    A configuration that cannot be read means we do not know where ffmpeg is, which is the same
    answer as not having one — so the failure is swallowed rather than raised into a QC run.
    """
    try:
        return _EncoderSetting().ffmpeg_path
    except Exception:  # noqa: BLE001
        return None


def find_ffmpeg(configured: str | None = None) -> str | None:
    """The ffmpeg binary to use, or None when there is not one."""
    candidate = configured or _configured_ffmpeg()
    if candidate and Path(candidate).is_file():
        return candidate
    return shutil.which("ffmpeg")


def find_ffprobe(configured_ffmpeg: str | None = None) -> str | None:
    """The ffprobe binary to use, or None when there is not one.

    ``configured_ffmpeg`` is the studio's ffmpeg setting, used to look in the right folder when
    ffprobe is not on PATH.
    """
    explicit = os.environ.get("STUDIO_FFPROBE_PATH")
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
