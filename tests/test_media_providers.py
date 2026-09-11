"""Media provider adapters: what they measure, and what they refuse to invent.

These adapters are the point where an outside vendor's output becomes a studio asset, so two
things matter more than the happy path.

Every number attached to a result must be measured from the bytes that came back — a duration
counted from the audio, a size read out of the image header — because the assembler cuts video
to those numbers and QC reasons about them. A figure taken from the request instead would be a
measurement nobody made.

And an adapter must never substitute. A vendor that fails has to raise, so the render fails
honestly, rather than returning something plausible that then flows into a publication gate.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib

import pytest
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    mp3_duration_seconds,
    png_dimensions,
    wav_duration_seconds,
)
from app.providers.openai_media import OpenAIImageAdapter

# --- fixtures that build real file bytes ------------------------------------------------


def png_bytes(width: int, height: int) -> bytes:
    """A minimal but structurally valid PNG of the given size."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def mp3_bytes(frames: int) -> bytes:
    """Constant-bitrate MPEG-1 Layer III frames: 128 kbps, 44.1 kHz, 1152 samples each."""
    frame_length = int(144 * 128000 / 44100)  # 417 bytes, no padding
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    return (header + b"\x00" * (frame_length - 4)) * frames


def wav_bytes(seconds: float, sample_rate: int = 44100) -> bytes:
    frames = int(seconds * sample_rate)
    data = b"\x00\x00" * frames
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


class Recorder:
    """Stands in for the network, and remembers exactly what was asked of it."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, host, method, path, headers, body=None, *, timeout=120, expect_json=True):
        self.calls.append(
            {
                "host": host,
                "method": method,
                "path": path,
                "headers": headers,
                "body": json.loads(body) if body and expect_json is not False else body,
            }
        )
        if not self.responses:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --- measurement ------------------------------------------------------------------------


def test_an_mp3_duration_is_counted_from_its_frames():
    # 100 frames x 1152 samples / 44100 Hz = 2.612 s
    assert mp3_duration_seconds(mp3_bytes(100)) == pytest.approx(2.612, abs=0.002)


def test_an_id3_tag_does_not_confuse_the_frame_count():
    tag = b"ID3\x04\x00\x00" + bytes([0, 0, 0x02, 0x00]) + b"\x00" * 256
    assert mp3_duration_seconds(tag + mp3_bytes(50)) == pytest.approx(1.306, abs=0.002)


def test_audio_that_is_not_decodable_raises_instead_of_returning_zero():
    """Zero would flow into the render as a real measurement of a silent segment."""
    with pytest.raises(MediaProviderError):
        mp3_duration_seconds(b"not audio at all, just some bytes")


def test_a_wav_duration_comes_from_its_own_header():
    assert wav_duration_seconds(wav_bytes(1.5)) == pytest.approx(1.5, abs=0.01)


def test_png_dimensions_are_read_from_the_image():
    assert png_dimensions(png_bytes(1024, 1536)) == (1024, 1536)


@pytest.mark.parametrize("data", [b"", b"GIF89a", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8])
def test_something_that_is_not_a_png_raises(data):
    with pytest.raises(MediaProviderError):
        png_dimensions(data)


# --- ElevenLabs -------------------------------------------------------------------------


def test_tts_reports_the_duration_of_the_audio_it_received(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder((None, mp3_bytes(120), "audio/mpeg"))
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    result = asyncio.run(adapter.synthesize("Hubble was launched in 1990."))

    # 120 frames, not the length the sentence "should" take.
    assert result.duration_seconds == pytest.approx(3.135, abs=0.002)
    assert result.format == "mp3"
    assert result.word_timings == [], "the endpoint returns no alignment, so none is reported"
    assert recorder.calls[0]["path"] == "/v1/text-to-speech/v1"


def test_tts_without_a_voice_refuses_before_calling_the_vendor(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder()
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key")

    import asyncio

    with pytest.raises(MediaProviderNotConfigured):
        asyncio.run(adapter.synthesize("Some narration."))

    assert recorder.calls == []


def test_tts_without_a_key_cannot_be_constructed():
    with pytest.raises(MediaProviderNotConfigured):
        ElevenLabsTTSAdapter("")


def test_a_non_audio_response_raises_rather_than_producing_a_silent_segment(monkeypatch):
    from app.providers import elevenlabs

    monkeypatch.setattr(
        elevenlabs, "request", Recorder((None, b'{"error": "quota"}', "application/json"))
    )
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.synthesize("Some narration."))


def test_an_unreachable_tts_provider_is_reported_offline_not_healthy(monkeypatch):
    from app.providers import elevenlabs

    monkeypatch.setattr(elevenlabs, "request", Recorder(MediaProviderError("unreachable")))

    import asyncio

    health = asyncio.run(ElevenLabsTTSAdapter("key").health_check())

    assert health["status"] == "OFFLINE"


# --- OpenAI images ----------------------------------------------------------------------


def test_image_dimensions_come_from_the_returned_bytes_not_the_request(monkeypatch):
    """The provider returned 1024x1536; the caller asked for 1080x1920. The truth is the file."""
    from app.providers import openai_media

    payload = {"data": [{"b64_json": base64.b64encode(png_bytes(1024, 1536)).decode()}]}
    monkeypatch.setattr(openai_media, "request", Recorder((payload, b"", "application/json")))
    adapter = OpenAIImageAdapter("key")

    import asyncio

    result = asyncio.run(adapter.generate_image("a telescope", width=1080, height=1920))

    assert (result.width, result.height) == (1024, 1536)
    assert result.format == "png"
    assert result.seed is None, "the API takes no seed, so none is echoed back as if it applied"


def test_a_response_with_only_a_url_raises_rather_than_fetching_it(monkeypatch):
    """Following the URL would be a second request to whatever host the response named."""
    from app.providers import openai_media

    payload = {"data": [{"url": "https://elsewhere.example/image.png"}]}
    monkeypatch.setattr(openai_media, "request", Recorder((payload, b"", "application/json")))

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))


def test_an_empty_image_list_raises(monkeypatch):
    from app.providers import openai_media

    monkeypatch.setattr(openai_media, "request", Recorder(({"data": []}, b"", "application/json")))

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))


def test_image_data_that_is_not_a_png_raises(monkeypatch):
    from app.providers import openai_media

    payload = {"data": [{"b64_json": base64.b64encode(b"GIF89a not a png").decode()}]}
    monkeypatch.setattr(openai_media, "request", Recorder((payload, b"", "application/json")))

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))


def test_an_empty_prompt_never_reaches_the_vendor(monkeypatch):
    from app.providers import openai_media

    recorder = Recorder()
    monkeypatch.setattr(openai_media, "request", recorder)

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(OpenAIImageAdapter("key").generate_image("   "))

    assert recorder.calls == []


def test_vendor_error_identifiers_are_read_from_error_bodies_but_never_free_text():
    from app.providers.media_http import error_code

    assert error_code(b'{"detail": {"status": "missing_permissions", "message": "x"}}') == (
        "missing_permissions"
    )
    assert error_code(b'{"detail": "invalid_api_key"}') == "invalid_api_key"
    assert error_code(b'{"error": {"code": "rate_limited"}}') == "rate_limited"
    assert error_code(b'{"detail": "The key sk_live_123 is not valid"}') is None
    assert error_code(b'{"detail": {"status": "Bad Request"}}') is None
    assert error_code(b"<html>") is None
