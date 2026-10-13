"""Delivery sizes and provenance for what ComfyUI saved.

A still leaves the worker as a PNG of exactly 1530x2720; it is re-encoded (Pillow center-crop
and Lanczos) only when the graph did not already deliver that size, and its text chunks
(ComfyUI's prompt/workflow) are carried over. A clip leaves as 1080x1920, 24 fps, H.264
yuv420p, without audio (LTX-2.5 can render an audio track; the studio voices its own films),
with the source's metadata kept (``-map_metadata 0``).

The LTX-2.x Community Licence forbids removing "metadata, watermarking, content provenance"
from any output. Nothing here strips anything knowingly; but a re-encode cannot carry a C2PA
or ``uuid`` box over, so every such box found in the source is listed in
``provenance_boxes`` and, when the delivered file no longer has it, also as ``lost:<box>``.
The bake-off decides what to do about a lost box (flagged, never hidden).
"""

from __future__ import annotations

import io
import shutil
import struct
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from runpod_worker.contract import CLIP_FPS, CLIP_SIZE, STILL_SIZE

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: The C2PA manifest store's usertype in an ISO BMFF ``uuid`` box (C2PA spec, 2.x).
C2PA_UUID = "d8fec3d61b0e483c92975828877ec481"  # pragma: allowlist secret
#: Boxes whose children the walker descends into (``meta`` is a full box: 4 bytes first).
CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"edts", b"dinf", b"meta"}
ENCODE_TIMEOUT_SECONDS = 900


class PostprocessError(RuntimeError):
    """The delivered file does not meet the delivery spec: the item FAILS."""


@dataclass(frozen=True)
class FinishedStill:
    data: bytes
    width: int
    height: int
    provenance_boxes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinishedClip:
    data: bytes
    width: int
    height: int
    fps: int
    duration: float
    provenance_boxes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------- formats


def _png_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        return
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[offset : offset + 8])
        payload = data[offset + 8 : offset + 8 + length]
        yield kind, payload
        offset += 12 + length
        if kind == b"IEND":
            return


def png_provenance(data: bytes) -> list[str]:
    """Text chunks (by keyword), EXIF and C2PA (``caBX``) of a PNG, in file order."""
    found: list[str] = []
    for kind, payload in _png_chunks(data):
        if kind in (b"tEXt", b"iTXt", b"zTXt"):
            keyword = payload.split(b"\x00", 1)[0].decode("latin-1", "replace")
            found.append(f"png:{kind.decode()}:{keyword}")
        elif kind in (b"caBX", b"eXIf"):
            found.append(f"png:{kind.decode()}")
    return found


def _mp4_boxes(
    data: bytes, start: int = 0, end: int | None = None
) -> Iterator[tuple[bytes, bytes]]:
    end = len(data) if end is None else end
    offset = start
    while offset + 8 <= end:
        size, kind = struct.unpack(">I4s", data[offset : offset + 8])
        header = 8
        if size == 1:
            if offset + 16 > end:
                return
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            return
        payload_start = offset + header
        yield kind, data[payload_start : offset + size]
        if kind in CONTAINERS:
            inner = payload_start + (4 if kind == b"meta" else 0)
            yield from _mp4_boxes(data, inner, offset + size)
        offset += size


def mp4_provenance(data: bytes) -> list[str]:
    """``c2pa`` for a C2PA uuid box, ``uuid:<hex>`` for any other uuid box, ``jumbf`` for a
    bare JUMBF box; at any depth, in file order."""
    found: list[str] = []
    for kind, payload in _mp4_boxes(data):
        if kind == b"uuid" and len(payload) >= 16:
            usertype = payload[:16].hex()
            found.append("c2pa" if usertype == C2PA_UUID else f"uuid:{usertype}")
        elif kind == b"jumb":
            found.append("jumbf")
    return found


def video_size(data: bytes) -> tuple[int, int] | None:
    """The first track header with a picture size (16.16 fixed point), or None."""
    for kind, payload in _mp4_boxes(data):
        if kind != b"tkhd" or not payload:
            continue
        # ISO 14496-12 tkhd: width/height follow the matrix, at byte 88 (v1) or 76 (v0).
        offset = 88 if payload[0] == 1 else 76
        if len(payload) < offset + 8:
            continue
        width, height = struct.unpack(">II", payload[offset : offset + 8])
        if width >> 16 and height >> 16:
            return width >> 16, height >> 16
    return None


def _with_losses(source: list[str], delivered: list[str]) -> list[str]:
    return source + [f"lost:{name}" for name in source if name not in delivered]


# ------------------------------------------------------------------------------------ stills


def finish_still(source: bytes, size: tuple[int, int] = STILL_SIZE) -> FinishedStill:
    """Exactly ``size`` as PNG: kept byte for byte when it already is."""
    from PIL import Image, PngImagePlugin

    found = png_provenance(source)
    try:
        image = Image.open(io.BytesIO(source))
        image.load()
    except Exception as exc:
        raise PostprocessError(f"unreadable still ({type(exc).__name__})") from exc
    if image.size == size and image.format == "PNG":
        return FinishedStill(source, size[0], size[1], found)
    width, height = image.size
    target = size[0] / size[1]
    if width / height > target:
        crop_width = round(height * target)
        left = (width - crop_width) // 2
        box = (left, 0, left + crop_width, height)
    else:
        crop_height = round(width / target)
        top = (height - crop_height) // 2
        box = (0, top, width, top + crop_height)
    mode = "RGBA" if image.mode in ("RGBA", "LA") else "RGB"
    fitted = image.convert(mode).crop(box).resize(size, Image.Resampling.LANCZOS)
    info = PngImagePlugin.PngInfo()
    for key, value in getattr(image, "text", {}).items():
        info.add_text(key, value)
    buffer = io.BytesIO()
    fitted.save(buffer, "PNG", pnginfo=info)
    data = buffer.getvalue()
    return FinishedStill(data, size[0], size[1], _with_losses(found, png_provenance(data)))


# ------------------------------------------------------------------------------------- clips


def clip_args(ffmpeg: str, source: Path, target: Path, duration: float) -> list[str]:
    """1080x1920 (a portrait 1088 crops to 1080; 720x1280 scales up), 24 fps, H.264 yuv420p,
    no audio, the source's metadata kept, trimmed to the asked duration."""
    width, height = CLIP_SIZE
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},fps={CLIP_FPS},setsar=1,format=yuv420p"
    )
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map_metadata",
        "0",
        "-vf",
        video_filter,
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "16",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(target),
    ]


def run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=ENCODE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PostprocessError(f"encode failed ({type(exc).__name__})") from exc


def finish_clip(source: Path, target: Path, duration: float, *, ffmpeg: str = "") -> FinishedClip:
    executable = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
    original = source.read_bytes()
    run_ffmpeg(clip_args(executable, source, target, duration))
    if not target.is_file():
        raise PostprocessError("the encode wrote no file")
    data = target.read_bytes()
    size = video_size(data)
    if size != CLIP_SIZE:
        raise PostprocessError(f"the clip is {size}, not {CLIP_SIZE}")
    found = _with_losses(mp4_provenance(original), mp4_provenance(data))
    return FinishedClip(data, size[0], size[1], CLIP_FPS, float(duration), found)
