"""ElevenLabs text-to-speech adapter.

Uses the documented REST API at https://elevenlabs.io/docs/api-reference/introduction:

  GET  /v1/models                  -> models returned for this key
  GET  /v2/voices                  -> paginated voices this key can use
  POST /v1/text-to-speech/{voice_id} -> narration audio

The duration attached to a result is measured from the audio that came back, never derived from
the length of the text. A render job records how long each segment is, and the assembler cuts
video to it; a guessed number there would desynchronise the picture from the voice while
appearing to be a measurement.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import quote, urlencode

from app.providers.media_base import TTSProvider, TTSResult
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    mp3_duration_seconds,
    request,
)

HOST = "api.elevenlabs.io"


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
        self.model = model or ""
        #: Per-character voice settings from the bible's binding; the API's defaults otherwise.
        self.voice_settings: dict[str, Any] = {}

    def _headers(self, accept: str) -> dict[str, str]:
        return {"xi-api-key": self.api_key, "Accept": accept, "Content-Type": "application/json"}

    async def health_check(self) -> dict[str, Any]:
        """Ask the API who this key is. Reachability is reported, never assumed."""
        try:
            data, _, _ = await asyncio.to_thread(
                request, HOST, "GET", "/v1/user", self._headers("application/json"), timeout=20
            )
        except MediaProviderError as exc:
            return {
                "status": "OFFLINE",
                "detail": str(exc),
                "code": exc.code,
                "http_status": exc.http_status,
            }
        if not isinstance(data, dict) or not data.get("user_id"):
            return {"status": "OFFLINE", "detail": "ElevenLabs did not identify the account"}
        return {"status": "HEALTHY", "detail": ""}

    async def list_models(self) -> list[dict[str, Any]]:
        data, _, _ = await asyncio.to_thread(
            request, HOST, "GET", "/v1/models", self._headers("application/json"), timeout=20
        )
        return self._resources(data, "model_id")

    @staticmethod
    def _resources(data: Any, id_field: str) -> list[dict[str, Any]]:
        if not isinstance(data, list):
            raise MediaProviderError("ElevenLabs did not return a resource list")
        for item in data:
            identifier = item.get(id_field) if isinstance(item, dict) else None
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200:
                raise MediaProviderError("ElevenLabs returned a resource without a valid ID")
        return data

    async def list_voices(self) -> list[dict[str, Any]]:
        voices: dict[str, dict[str, Any]] = {}
        seen_tokens: set[str] = set()
        params = {"page_size": "100"}
        deadline = time.monotonic() + 120
        for _ in range(1000):
            if time.monotonic() >= deadline:
                raise MediaProviderError("ElevenLabs voice discovery timed out before completion")
            data, _, _ = await asyncio.to_thread(
                request,
                HOST,
                "GET",
                "/v2/voices?" + urlencode(params),
                self._headers("application/json"),
                timeout=20,
            )
            if not isinstance(data, dict):
                raise MediaProviderError("ElevenLabs did not return a voice list")
            for voice in self._resources(data.get("voices"), "voice_id"):
                voices[voice["voice_id"]] = voice
            if data.get("has_more") is False:
                return list(voices.values())
            token = data.get("next_page_token")
            if (
                data.get("has_more") is not True
                or not isinstance(token, str)
                or not token
                or token in seen_tokens
            ):
                raise MediaProviderError("ElevenLabs returned incomplete voice pagination")
            seen_tokens.add(token)
            params["next_page_token"] = token
        raise MediaProviderError("ElevenLabs voice pagination exceeded the safety limit")

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
        if not self.model:
            raise MediaProviderNotConfigured("Select an ElevenLabs production model in Settings")

        payload = json.dumps(
            {
                "text": narration,
                "model_id": self.model,
                # The API exposes no pitch control, so the adapter does not pretend to have one:
                # a pitch argument it silently dropped would read as applied.
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    **{k: v for k, v in self.voice_settings.items() if k != "speed"},
                    "speed": speed,
                },
            }
        ).encode("utf-8")

        _, audio, content_type = await asyncio.to_thread(
            request,
            HOST,
            "POST",
            f"/v1/text-to-speech/{quote(voice, safe='')}",
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
