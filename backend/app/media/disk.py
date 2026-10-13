"""The media disk: where films are written, how much room is left, and when that is too little.

Measured 2026-10-01 (REL-08): the studio's media folder held 299 GiB in 18,696 files, it was a
constant inside the repository (backend/storage/media), and nothing anywhere asked how much
free space was left before a paid step wrote its takes. A film writes up to about 1.1 GB while
it is made; a disk that fills half-way through a paid step loses work that was paid for.

- `media_root` is the folder films are written to: the Owner's ``STUDIO_MEDIA_ROOT`` when set,
  otherwise the studio's own default (read at call time, so a test's private folder holds);
- `free_bytes` is the one place the free space is read (a test replaces it);
- `disk_refusal` is the Romanian reason a paid step or the day's preflight refuses to start,
  or None when there is room. ``STUDIO_MIN_FREE_GB`` = 0 turns the guard off.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import ROOT

#: The minimum free space a paid step needs when no settings say otherwise.
DEFAULT_MIN_FREE_GB = 20.0
#: The status a paid step refuses with when the media disk is too full.
LOW_DISK = "LOW_DISK"
#: The setting the Owner changes, named in the technical part of a refusal.
MIN_FREE_SETTING = "STUDIO_MIN_FREE_GB"
MEDIA_ROOT_SETTING = "STUDIO_MEDIA_ROOT"
GB = 1024**3


class _DiskSetting(BaseSettings):
    """Just the free-space minimum, for a step that is not handed the studio's settings (the
    stills step): read from the same place, the environment or .env."""

    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=ROOT / ".env", extra="ignore")

    min_free_gb: float = Field(default=DEFAULT_MIN_FREE_GB, ge=0.0)


def media_root(settings: Any = None) -> Path:
    """The folder films are written to: the Owner's setting, else the studio's default."""
    configured = getattr(settings, "media_root", None)
    if configured:
        return Path(configured)
    from app.media import assembler  # noqa: PLC0415 - the assembler imports half the studio

    return Path(assembler.DEFAULT_STORAGE_ROOT)


def min_free_gb(settings: Any = None) -> float:
    """The minimum free space, in GB: the settings' when given, else the environment's."""
    value = getattr(settings, "min_free_gb", None)
    if value is None:
        try:
            value = _DiskSetting().min_free_gb
        except Exception:  # noqa: BLE001 - an unreadable .env is the default, not a crash
            value = DEFAULT_MIN_FREE_GB
    return max(0.0, float(value))


def _existing(path: Path) -> Path:
    """The nearest folder that exists on the way up to ``path``: a media root not created
    yet is measured on the disk it will be created on."""
    candidate = Path(path)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def free_bytes(path: Path) -> int:
    """Free bytes on the disk that holds ``path``."""
    return int(shutil.disk_usage(_existing(path)).free)


def gb_words(value_bytes: float) -> str:
    """«5 GB», «12,5 GB»: the way the Owner reads a size."""
    gb = value_bytes / GB
    text = f"{gb:.0f}" if gb >= 10 or abs(gb - round(gb)) < 0.05 else f"{gb:.1f}"
    return text.replace(".", ",") + " GB"


def disk_reading(storage_root: Path | None = None, settings: Any = None) -> dict[str, Any]:
    """The media disk now: its folder, the free space, the minimum and whether it is enough.
    ``status`` OK | LOW | UNKNOWN (the disk could not be read) | OFF (no minimum)."""
    root = Path(storage_root) if storage_root else media_root(settings)
    minimum = min_free_gb(settings)
    try:
        free = free_bytes(root)
    except OSError as exc:
        return {
            "status": "UNKNOWN",
            "root": str(root),
            "free_gb": None,
            "min_free_gb": minimum,
            "reason_ro": f"Spațiul liber de pe discul filmelor nu a putut fi citit ({exc}).",
        }
    status = "OFF" if minimum <= 0 else ("LOW" if free < minimum * GB else "OK")
    reason = ""
    if status == "LOW":
        reason = (
            f"Pe discul filmelor ({root}) au rămas {gb_words(free)} liberi, sub minimul de "
            f"{gb_words(minimum * GB)}: nu se cumpără nimic și nu se începe niciun film până "
            "nu se face spațiu (sau până nu se mută filmele pe alt disc)."
        )
    return {
        "status": status,
        "root": str(root),
        "free_gb": round(free / GB, 1),
        "min_free_gb": minimum,
        "reason_ro": reason,
    }


def disk_refusal(storage_root: Path | None = None, settings: Any = None) -> str | None:
    """The Romanian reason a paid step must not start for want of space, or None.

    A disk that cannot be read refuses nothing: the guard exists to stop a known shortage, and
    a step that fails to write says so on its own.
    """
    reading = disk_reading(storage_root, settings)
    return str(reading["reason_ro"]) if reading["status"] == "LOW" else None
