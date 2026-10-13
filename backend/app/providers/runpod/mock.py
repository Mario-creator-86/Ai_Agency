"""Explicit no-GPU development transport; outputs are real deterministic files."""

from __future__ import annotations

import asyncio
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any

from app.media.toolchain import find_ffmpeg
from app.providers.runpod.errors import RunPodProtocolError
from app.providers.runpod.jobs import JobStore


def png(width: int = 72, height: int = 128, variation: int = 0) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
        )

    pixels = b"".join(
        b"\0" + bytes([30 + y % 150, 70 + variation % 150, 110]) * width for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def video(seconds: float, fps: int) -> bytes:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RunPodProtocolError("Mock video requires the Agency's existing FFmpeg")
    with tempfile.TemporaryDirectory(prefix="amn-runpod-mock-") as tmp:
        output = Path(tmp) / "mock.mp4"
        result = subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=72x128:rate={fps}",
                "-t",
                str(seconds),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or not output.is_file():
            raise RunPodProtocolError("Mock video encoding failed")
        return output.read_bytes()


class MockRunPodClient:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    async def submit(self, operation: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        return {"job_id": "mock-" + key, "status": "QUEUED"}

    async def status(self, remote_id: str) -> dict[str, Any]:
        row = self.store.read(remote_id)
        state = "RUNNING" if row.poll_count == 0 else "COMPLETED"
        if row.poll_count and row.request.get("mock_failure"):
            state = "FAILED"
        return {
            "job_id": remote_id,
            "status": state,
            "gpu_seconds": 0,
            "output": {"url": "mock://" + row.id} if state == "COMPLETED" else {},
        }

    async def cancel(self, remote_id: str) -> dict[str, Any]:
        return {"job_id": remote_id, "status": "CANCELLED"}

    async def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "mock": True,
            "authenticated": False,
            "gpu_backend_status": "NO_GPU_MOCK",
        }

    async def models(self) -> dict[str, Any]:
        return {
            "models": [
                {
                    "id": "Qwen-Image-2512",
                    "name": "MOCK image",
                    "tasks": ["text_to_image"],
                    "purpose": "image",
                    "per_image_usd": 0,
                    "max_seconds": 5,
                },
            ]
            + [
                {
                    "id": name,
                    "name": "MOCK video " + name,
                    "tasks": ["image_to_video"],
                    "purpose": "video",
                    "per_second_usd": 0,
                    "max_seconds": 5,
                    "durations": {"image_to_video": {"min": 1, "max": 5}},
                    "ratios": {"image_to_video": ["9:16"]},
                }
                for name in ("LTX-2.5", "Wan-2.2-LightX2V", "AUTO")
            ]
        }

    async def download(self, url: str) -> tuple[bytes, str]:
        row = self.store.read(url.removeprefix("mock://"))
        if row.operation == "image":
            return png(variation=int(row.idempotency_key[:8], 16)), "image/png"
        return await asyncio.to_thread(
            video, float(row.request.get("duration", 5)), int(row.request.get("fps", 24))
        ), "video/mp4"
