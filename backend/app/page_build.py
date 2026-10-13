"""Whether the page the studio serves was built from the sources on disk (PAGE-01).

On 2026-10-01 the studio served a bundle built four days earlier, before the shooting sheet and
the paid-media switch existed, and nothing said so. `scripts/start.py` now writes
``frontend/dist/build.json`` with the hash of the sources it built from; the snapshot compares it
with the hash of the sources now (`page_build`), so the page can say «Pagina e mai veche decât
studioul: repornește studioul».

The hash covers ``frontend/index.html`` and every file under ``frontend/src``, by their paths
relative to ``frontend`` and their bytes with CRLF folded to LF, so a Windows checkout and a
POSIX one of the same commit hash the same. A bundle with no record (built before this, or by a
bare ``npm run build``) is judged by the file times instead, which is what the launcher already
uses to decide whether to build. Standard library only: the launcher imports it before anything
else of the studio is installed.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

#: The record the launcher writes beside the built page.
BUILD_RECORD = "build.json"

_lock = threading.Lock()
#: (frontend folder) -> (the files' fingerprint, the hash it gave): the snapshot is read every
#: few seconds, and hashing the sources again when no file moved would be work for nothing.
_cache: dict[str, tuple[tuple[tuple[str, int, int], ...], str]] = {}


def _sources(frontend: Path) -> list[Path]:
    files = []
    index = frontend / "index.html"
    if index.is_file():
        files.append(index)
    src = frontend / "src"
    if src.is_dir():
        files.extend(path for path in src.rglob("*") if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(frontend).as_posix())


def _fingerprint(frontend: Path, files: list[Path]) -> tuple[tuple[str, int, int], ...]:
    stamps = []
    for path in files:
        stat = path.stat()
        stamps.append((path.relative_to(frontend).as_posix(), stat.st_mtime_ns, stat.st_size))
    return tuple(stamps)


def source_hash(frontend: Path) -> str:
    """SHA-256 over the page's sources: each relative path and its LF-folded bytes."""
    files = _sources(frontend)
    key = str(frontend.resolve())
    fingerprint = _fingerprint(frontend, files)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(frontend).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    value = digest.hexdigest()
    with _lock:
        _cache[key] = (fingerprint, value)
    return value


def write_build_record(frontend: Path, source_sha256: str) -> Path:
    """Record, beside the built page, which sources it was built from."""
    target = frontend / "dist" / BUILD_RECORD
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": 1, "source_sha256": source_sha256}, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _recorded(frontend: Path) -> str | None:
    try:
        data = json.loads((frontend / "dist" / BUILD_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("source_sha256") if isinstance(data, dict) else None
    return value if isinstance(value, str) and len(value) == 64 else None


def page_build(frontend: Path) -> dict[str, Any]:
    """{built, source, stale, basis}: the hash the page was built from (None when the bundle
    carries no record), the sources' hash now, whether the page is older than the sources, and
    what that was judged by: ``hash``, ``mtime`` (no record) or ``none`` (no page built)."""
    source = source_hash(frontend)
    built = _recorded(frontend)
    if built is not None:
        return {"built": built, "source": source, "stale": built != source, "basis": "hash"}
    index = frontend / "dist" / "index.html"
    if not index.is_file():
        return {"built": None, "source": source, "stale": False, "basis": "none"}
    built_at = index.stat().st_mtime
    newer = any(path.stat().st_mtime > built_at for path in _sources(frontend))
    return {"built": None, "source": source, "stale": newer, "basis": "mtime"}
