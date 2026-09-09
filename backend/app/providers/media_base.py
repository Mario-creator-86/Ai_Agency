"""Abstract interfaces for Media Generation Providers (Image, Video, TTS).

Following docs/architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md:
Never fake or fabricate unknown/unsupported methods.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageResult:
    image_bytes: bytes
    format: str  # "png" | "jpeg" | "webp" | "svg"
    width: int
    height: int
    seed: int | None = None
    prompt: str = ""
    cost_vr: str | None = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class TTSResult:
    audio_bytes: bytes
    format: str  # "wav" | "mp3"
    duration_seconds: float
    sample_rate: int = 44100
    word_timings: list[dict[str, Any]] = field(default_factory=list)
    cost_vr: str | None = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class VideoGenerationResult:
    job_id: str
    status: str  # "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED"
    video_bytes: bytes | None = None
    video_path: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    cost_vr: str | None = None
    raw_response: dict = field(default_factory=dict)


class ImageProvider(abc.ABC):
    """Base interface for Image Generation Providers."""

    ADAPTER_VERSION: str = "1.0.0"

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return provider health status."""

    @abc.abstractmethod
    async def generate_image(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1920,
        style: str | None = None,
        seed: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ImageResult:
        """Generate a still visual asset."""


class TTSProvider(abc.ABC):
    """Base interface for Text-to-Speech Providers."""

    ADAPTER_VERSION: str = "1.0.0"

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return provider health status."""

    @abc.abstractmethod
    async def list_voices(self) -> list[dict[str, Any]]:
        """List available synthetic voices."""

    @abc.abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        extra: dict[str, Any] | None = None,
    ) -> TTSResult:
        """Synthesize voiceover narration."""


class VideoProvider(abc.ABC):
    """Base interface for Video Generation Providers."""

    ADAPTER_VERSION: str = "1.0.0"

    @abc.abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return provider health status."""

    @abc.abstractmethod
    async def create_generation(
        self,
        prompt: str,
        *,
        image_ref: bytes | None = None,
        duration_seconds: float = 4.0,
        aspect_ratio: str = "9:16",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Submit a video generation job and return remote job ID."""

    @abc.abstractmethod
    async def get_generation_status(self, job_id: str) -> VideoGenerationResult:
        """Poll the status of an active video generation job."""
