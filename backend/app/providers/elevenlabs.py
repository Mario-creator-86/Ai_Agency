"""ElevenLabs text-to-speech adapter.

Uses the documented REST API at https://elevenlabs.io/docs/api-reference/introduction:

  GET  /v1/voices                    -> the voices this key can use
  POST /v1/text-to-speech/{voice_id} -> narration audio

The duration attached to a result is measured from the audio that came back, never derived from
the length of the text. A render job records how long each segment is, and the assembler cuts
video to it; a guessed number there would desynchronise the picture from the voice while
appearing to be a measurement.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.providers.media_base import TTSProvider, TTSResult
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    mp3_duration_seconds,
    request,
)

HOST = "api.elevenlabs.io"
DEFAULT_MODEL = "eleven_multilingual_v2"


class ElevenLabsTTSAdapter(TTSProvider):
    PROVIDER_NAME = "ELEVENLABS"
    ADAPTER_VERSION = "1.0.0"

    def __init__(
        self,
        api_key: str,
        voice_id: str | None = None,
        model: str | None = None,
    ) -> None:
        if not api_key:
            raise MediaProviderNotConfigured("ElevenLabs needs an API key")
        self.api_key = api_key
        self.voice_id = voice_id or ""
        self.model = model or DEFAULT_MODEL

    def _headers(self, accept: str) -> dict[str, str]:
        return {"xi-api-key": self.api_key, "Accept": accept, "Content-Type": "application/json"}

    async def health_check(self) -> dict[str, Any]:
        """Ask the API who this key is. Reachability is reported, never assumed."""
        try:
            data, _, _ = await asyncio.to_thread(
                request, HOST, "GET", "/v1/user", self._headers("application/json")
            )
        except MediaProviderError as exc:
            return {"status": "OFFLINE", "detail": str(exc)}
        return {"status": "HEALTHY", "detail": "", "user_id": (data or {}).get("user_id")}

    async def list_voices(self) -> list[dict[str, Any]]:
        data, _, _ = await asyncio.to_thread(
            request, HOST, "GET", "/v1/voices", self._headers("application/json")
        )
        voices = (data or {}).get("voices")
        if not isinstance(voices, list):
            raise MediaProviderError("ElevenLabs did not return a voice list")
        return [
            {
                "voice_id": voice.get("voice_id", ""),
                "name": voice.get("name", ""),
                "category": voice.get("category", ""),
            }
            for voice in voices
            if isinstance(voice, dict)
        ]

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        extra: dict[str, Any] | None = None,
    ) -> TTSResult:
        narration = " ".join(str(text).split())
        if not narration:
            raise MediaProviderError("There is no narration text to synthesise")
        voice = voice_id or self.voice_id
        if not voice:
            raise MediaProviderNotConfigured(
                "No ElevenLabs voice is selected; set a voice id in Settings"
            )

        payload = json.dumps(
            {
                "text": narration,
                "model_id": self.model,
                # The API exposes no pitch control, so the adapter does not pretend to have one:
                # a pitch argument it silently dropped would read as applied.
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": speed},
            }
        ).encode("utf-8")

        _, audio, content_type = await asyncio.to_thread(
            request,
            HOST,
            "POST",
            f"/v1/text-to-speech/{voice}",
            self._headers("audio/mpeg"),
            payload,
            expect_json=False,
        )
        if not audio or "audio" not in content_type:
            raise MediaProviderError("ElevenLabs did not return audio")

        return TTSResult(
            audio_bytes=audio,
            format="mp3",
            # Counted from the returned frames, not estimated from the words sent.
            duration_seconds=mp3_duration_seconds(audio),
            sample_rate=44100,
            # The API returns no word timings on this endpoint, so none are reported. An
            # invented alignment would drive subtitle timing that matches nothing.
            word_timings=[],
            raw_response={
                "provider": self.PROVIDER_NAME,
                "model": self.model,
                "voice_id": voice,
                "content_type": content_type,
                "bytes": len(audio),
            },
        )
