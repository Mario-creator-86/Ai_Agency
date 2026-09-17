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
#: is left quiet). The true-peak ceiling of -1 dBTP leaves the AAC encoder its overshoot.
LOUDNESS_TARGET_LUFS = -14.0
TRUE_PEAK_TARGET_DBTP = -1.0
#: The loudness range the filter may leave in place. loudnorm falls back from a linear gain to
#: its dynamic mode whenever the input's range exceeds this, and a dynamic pass pumps speech;
#: narration measures 5–9 LU, so 11 keeps the gain linear for every voice the studio has met.
LOUDNESS_RANGE_LU = 11.0

#: What quality control accepts: two LU either side of the target, and nothing over the
#: ceiling. Wider than the filter's own precision (about 0.5 LU) because the film is measured
#: after the AAC encode, which moves the reading a little.
LOUDNESS_BAND_LUFS = (-16.0, -12.0)
TRUE_PEAK_CEILING_DBTP = -1.0

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
        return f"{base}:print_format=json"
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
