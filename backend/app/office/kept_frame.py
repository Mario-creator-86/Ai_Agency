"""The studio's kept frame of its live Unreal headquarters, for a first visit's title (W24).

The page's title stands on a real frame of the Unreal building when it has one. Until now only a
browser that had already watched the stream kept one (IndexedDB), so a stranger's first visit
opened on the page renderer's building. While the Owner's signed-in page plays the stream it now
sends the newest frame it kept here, rarely (at most every five minutes): the same small WebP, with
the moment it was captured.

Exactly one frame is kept, the newest, outside the database: a file ``kept-<ms>.webp`` in the
data directory's ``office`` folder, written beside it and moved into place (``os.replace``), so a
reader sees the old frame or the new one, never half of one. Only a whole WebP of at most
KEPT_FRAME_MAX_BYTES is taken, with a capture time that is a real recent moment. Writing needs the
Owner's key in the Authorization header (never in a URL). Reading is public and read-only: the title
stands before the sign-in, and the frame shows only the building. Nothing kept is a 204 with no body
(a failed status would print an error in every stranger's console); the page then stands on its
plates, as it does on an older studio's 404. No frame is ever made up here.
"""

from __future__ import annotations

import asyncio
import os
import re
import struct
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url

from app.config import ROOT
from app.security import require_owner

KEPT_FRAME_PATH = "/office/kept-frame"
#: The page keeps a 1920 px WebP at quality 0.72 (stream_keep.js): about 130 KB at night. A day
#: frame carries more detail; this leaves it room and refuses anything that is not such a frame.
KEPT_FRAME_MAX_BYTES = 768 * 1024
#: A capture time this far ahead of the server's clock is a wrong clock, not a frame.
FUTURE_SLACK_MS = 60_000
#: The title never uses a frame older than a day, so an older one is not kept.
MAX_AGE_MS = 24 * 3600 * 1000
CAPTURED_AT_HEADER = "X-Captured-At"

_NAME = re.compile(r"^kept-(\d{1,16})\.webp$")
_write_lock = threading.Lock()

__all__ = [
    "KEPT_FRAME_MAX_BYTES",
    "KEPT_FRAME_PATH",
    "create_kept_frame_router",
    "is_webp",
    "kept_frame_dir",
    "newest_kept",
    "store_kept",
]


def kept_frame_dir(settings: Any) -> Path:
    """Where the kept frame lives: the configured folder, else ``office`` beside the database."""
    chosen = getattr(settings, "office_kept_frame_dir", None)
    if chosen:
        return Path(chosen)
    database = make_url(str(settings.database_url)).database or "data/studio.db"
    path = Path(database)
    if not path.is_absolute():
        path = ROOT / path
    return path.parent / "office"


#: The chunks a still WebP frame from a canvas is made of (Chrome writes VP8X, ICCP, VP8). No
#: metadata (EXIF, XMP), no animation, no chunk of another kind: nothing rides beside the picture.
_WEBP_CHUNKS = frozenset({b"VP8X", b"ICCP", b"ALPH", b"VP8 ", b"VP8L"})
_PICTURE_CHUNKS = frozenset({b"VP8 ", b"VP8L"})
#: No frame the page keeps is wider or taller than this (stream_keep.js keeps at most 1920 px).
MAX_FRAME_SIDE = 4096
_VP8X_REFUSED_FLAGS = 0x02 | 0x04 | 0x08  # animation, XMP, EXIF
_VP8_START = bytes((0x9D, 0x01, 0x2A))  # a VP8 key frame's start code


def _picture_size(fourcc: bytes, payload: bytes) -> tuple[int, int] | None:
    """The size a VP8 key frame or a VP8L picture declares, or None when it is not one."""
    if fourcc == b"VP8 ":
        # frame tag (3 bytes, bit 0 clear on a key frame), start code 9d 01 2a, 14-bit sizes
        if len(payload) < 10 or payload[0] & 1 or payload[3:6] != _VP8_START:
            return None
        width, height = struct.unpack("<HH", payload[6:10])
        return width & 0x3FFF, height & 0x3FFF
    # VP8L: signature 0x2f, then 14 bits of width - 1, 14 of height - 1, alpha, a version of 0
    if len(payload) < 5 or payload[0] != 0x2F:
        return None
    (bits,) = struct.unpack("<I", payload[1:5])
    if bits >> 29:
        return None
    return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1


def is_webp(data: bytes) -> bool:
    """A whole still WebP picture and nothing else (W25).

    RIFF with a size equal to what was sent, WEBP, then chunks that fill the file exactly: an
    optional VP8X first (no animation, no metadata, its canvas the picture's size), an optional
    ICCP or ALPH, and exactly one picture (a VP8 key frame or a VP8L), its size 1..MAX_FRAME_SIDE.
    A key holder cannot park other bytes behind a WebP header for every stranger to fetch.
    """
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    (riff_size,) = struct.unpack("<I", data[4:8])
    if riff_size + 8 != len(data):
        return False
    offset = 12
    canvas: tuple[int, int] | None = None
    picture: tuple[int, int] | None = None
    first = True
    while offset < len(data):
        if offset + 8 > len(data):
            return False
        fourcc = data[offset : offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        end = offset + 8 + size
        if end > len(data) or fourcc not in _WEBP_CHUNKS:
            return False
        payload = data[offset + 8 : end]
        if fourcc == b"VP8X":
            if not first or size != 10 or payload[0] & _VP8X_REFUSED_FLAGS:
                return False
            canvas = (
                int.from_bytes(payload[4:7], "little") + 1,
                int.from_bytes(payload[7:10], "little") + 1,
            )
        elif fourcc in _PICTURE_CHUNKS:
            if picture is not None:
                return False
            picture = _picture_size(fourcc, payload)
            if picture is None:
                return False
        elif canvas is None or picture is not None:
            return False  # ICCP and ALPH belong to a VP8X file, before its picture
        first = False
        offset = end + (size & 1)
    if offset != len(data) or picture is None:
        return False
    if not all(1 <= side <= MAX_FRAME_SIDE for side in picture):
        return False
    return canvas is None or canvas == picture


def newest_kept(folder: Path) -> tuple[int, Path] | None:
    """The kept frame and its capture time (ms), or None when none is kept."""
    best: tuple[int, Path] | None = None
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None
    for entry in entries:
        match = _NAME.match(entry.name)
        if not match:
            continue
        at = int(match.group(1))
        if best is None or at > best[0]:
            best = (at, entry)
    return best


def store_kept(folder: Path, at: int, data: bytes) -> tuple[bool, int]:
    """Keeps ``data`` as the frame captured at ``at`` unless a newer one is kept already.

    Returns (stored, the capture time now kept). The file is written beside its place and moved
    into it; the older frame is removed only after the new one stands.
    """
    with _write_lock:
        folder.mkdir(parents=True, exist_ok=True)
        current = newest_kept(folder)
        if current is not None and current[0] >= at:
            return False, current[0]
        scratch = folder / f".incoming-{uuid.uuid4().hex}.tmp"
        try:
            with open(scratch, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(scratch, folder / f"kept-{at}.webp")
        finally:
            if scratch.exists():
                scratch.unlink()
        for entry in folder.iterdir():
            match = _NAME.match(entry.name)
            if match and int(match.group(1)) != at:
                try:
                    entry.unlink()
                except OSError:
                    pass  # read by a GET right now; the next write removes it
        return True, at


def _captured_at(raw: str | None, now_ms: int) -> int | None:
    """The capture time the page sent, when it is a whole number of ms, recent and not ahead."""
    if raw is None or not re.fullmatch(r"\d{1,16}", raw.strip()):
        return None
    at = int(raw.strip())
    if at > now_ms + FUTURE_SLACK_MS or now_ms - at > MAX_AGE_MS:
        return None
    return at


async def _body(request: Request, limit: int) -> bytes | None:
    """The request's body, or None as soon as it is longer than ``limit``."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def create_kept_frame_router() -> APIRouter:
    router = APIRouter(prefix="/office")

    @router.get(KEPT_FRAME_PATH.removeprefix("/office"))
    def read_kept_frame(request: Request) -> Response:
        """The newest kept real frame of the live headquarters, with its capture time. Public."""
        found = newest_kept(kept_frame_dir(request.app.state.settings))
        if found is None:
            return Response(status_code=204)
        at, path = found
        try:
            data = path.read_bytes()
        except OSError:
            return Response(status_code=204)
        return Response(
            content=data, media_type="image/webp", headers={CAPTURED_AT_HEADER: str(at)}
        )

    @router.post(
        KEPT_FRAME_PATH.removeprefix("/office"),
        dependencies=[Depends(require_owner)],
        status_code=201,
    )
    async def keep_frame(request: Request) -> JSONResponse:
        """The Owner's page keeps its newest real frame for the title (a WebP, at most rarely)."""
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "image/webp":
            return JSONResponse({"detail": "A WebP image is expected"}, status_code=415)
        at = _captured_at(request.headers.get(CAPTURED_AT_HEADER), int(time.time() * 1000))
        if at is None:
            return JSONResponse(
                {"detail": "X-Captured-At must be a recent moment in ms"}, status_code=422
            )
        data = await _body(request, KEPT_FRAME_MAX_BYTES)
        if data is None:
            return JSONResponse({"detail": "The frame is too large"}, status_code=413)
        if not is_webp(data):
            return JSONResponse({"detail": "A WebP image is expected"}, status_code=415)
        folder = kept_frame_dir(request.app.state.settings)
        stored, kept_at = await asyncio.to_thread(store_kept, folder, at, data)
        return JSONResponse({"stored": stored, "at": kept_at}, status_code=201 if stored else 200)

    return router
