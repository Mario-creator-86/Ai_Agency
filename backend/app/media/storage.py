"""Which files the media routes may serve (SEC-06).

The take and asset routes used to hand `FileResponse` whatever path the row held. Every path is
written by the pipeline today, but one bad row (an import, a rehearsal adopting a folder that
holds a link, a migration) would have served any file the process can read. A file is served
only when it resolves inside one of the studio's media folders and is not itself a link.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def media_roots(state: Any) -> list[Path]:
    """The folders media files may live in: the page's media root (`media_storage_root`, set by
    a test or a rehearsal), the studio's default media folder (rehearsals live inside it) and
    the character references folder. Read at call time, so a changed setting holds at once."""
    from app.media import assembler  # noqa: PLC0415 - the assembler imports half the studio
    from app.media import services as media_services  # noqa: PLC0415

    roots: list[Path] = []
    for candidate in (
        getattr(state, "media_storage_root", None),
        assembler.DEFAULT_STORAGE_ROOT,
        media_services.REFERENCE_STORAGE_ROOT,
    ):
        if candidate and Path(candidate) not in roots:
            roots.append(Path(candidate))
    return roots


def media_file_inside(path: str | Path | None, roots: list[Path]) -> Path | None:
    """The resolved file when ``path`` is a regular file, not a link, inside one of ``roots``
    (links and junctions along the way are followed and the result must still be inside);
    None otherwise, including for a path that does not exist."""
    if not path:
        return None
    candidate = Path(path)
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file():
        return None
    for root in roots:
        try:
            base = Path(root).resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if resolved.is_relative_to(base):
            return resolved
    return None
