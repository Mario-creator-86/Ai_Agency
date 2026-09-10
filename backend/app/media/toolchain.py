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
"""

from __future__ import annotations

import os
import shutil
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
