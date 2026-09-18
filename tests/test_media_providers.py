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
from unittest.mock import MagicMock

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


# --- transient failures are retried, and never billed twice --------------------------------
#
# Before 2026-09-17 no adapter retried anything: one 503 from the voice vendor was a failed
# scene. The helper in app.providers.retry does the waiting; these tests pin what each adapter
# asks of it — which calls may be repeated and which must not.


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch):
    from app.providers import retry

    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    return slept


def refused(host: str, status: int, **kwargs) -> MediaProviderError:
    return MediaProviderError(
        f"{host} refused the request (HTTP {status})", http_status=status, **kwargs
    )


def test_a_503_from_the_voice_vendor_is_retried_once_and_the_audio_kept(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder(refused("api.elevenlabs.io", 503), (None, mp3_bytes(120), "audio/mpeg"))
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    result = asyncio.run(adapter.synthesize("Hubble was launched in 1990."))

    assert result.duration_seconds == pytest.approx(3.135, abs=0.002)
    assert [c["path"] for c in recorder.calls] == ["/v1/text-to-speech/v1"] * 2


def test_a_400_from_the_voice_vendor_is_not_retried(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder(refused("api.elevenlabs.io", 400, code="invalid_voice_settings"))
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.synthesize("Some narration."))

    assert len(recorder.calls) == 1
    assert excinfo.value.code == "invalid_voice_settings" and excinfo.value.http_status == 400


def test_after_three_refusals_the_voice_vendor_error_carries_the_count(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder(*[refused("api.elevenlabs.io", 503) for _ in range(3)])
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.synthesize("Some narration."))

    assert len(recorder.calls) == 3
    assert excinfo.value.http_status == 503 and "3 attempts" in str(excinfo.value)


def test_a_narration_request_that_left_and_got_no_answer_is_not_sent_again(monkeypatch):
    """ElevenLabs bills the characters it synthesised; the silence may be a served request."""
    from app.providers import elevenlabs

    recorder = Recorder(
        MediaProviderError("api.elevenlabs.io did not answer", unanswered=True),
        (None, mp3_bytes(10), "audio/mpeg"),
    )
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.synthesize("Some narration."))

    assert len(recorder.calls) == 1


def test_the_voice_catalogue_is_a_read_and_is_asked_again_after_a_silence(monkeypatch):
    from app.providers import elevenlabs

    recorder = Recorder(
        MediaProviderError("api.elevenlabs.io did not answer", unanswered=True),
        ([{"model_id": "m1"}], b"", "application/json"),
    )
    monkeypatch.setattr(elevenlabs, "request", recorder)

    import asyncio

    assert asyncio.run(ElevenLabsTTSAdapter("key").list_models()) == [{"model_id": "m1"}]
    assert len(recorder.calls) == 2


def test_a_concurrency_limit_from_the_voice_vendor_waits_what_it_asks(monkeypatch, instant_retries):
    """ElevenLabs answers 429 too_many_concurrent_requests; a Retry-After is the vendor's own
    number and is waited out rather than guessed at."""
    from app.providers import elevenlabs

    recorder = Recorder(
        refused("api.elevenlabs.io", 429, code="too_many_concurrent_requests", retry_after=2.0),
        (None, mp3_bytes(10), "audio/mpeg"),
    )
    monkeypatch.setattr(elevenlabs, "request", recorder)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    import asyncio

    asyncio.run(adapter.synthesize("Some narration."))

    assert instant_retries == [2.0] and len(recorder.calls) == 2


def test_an_image_vendor_503_is_retried_once(monkeypatch):
    from app.providers import openai_media

    payload = {"data": [{"b64_json": base64.b64encode(png_bytes(64, 64)).decode()}]}
    recorder = Recorder(refused("api.openai.com", 503), (payload, b"", "application/json"))
    monkeypatch.setattr(openai_media, "request", recorder)

    import asyncio

    result = asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))

    assert (result.width, result.height) == (64, 64)
    assert [c["path"] for c in recorder.calls] == ["/v1/images/generations"] * 2


def test_an_image_vendor_400_is_not_retried(monkeypatch):
    from app.providers import openai_media

    recorder = Recorder(refused("api.openai.com", 400, code="content_policy_violation"))
    monkeypatch.setattr(openai_media, "request", recorder)

    import asyncio

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))

    assert len(recorder.calls) == 1 and excinfo.value.code == "content_policy_violation"


def test_an_image_vendor_that_keeps_refusing_raises_its_own_error_with_the_count(monkeypatch):
    from app.providers import openai_media

    recorder = Recorder(*[refused("api.openai.com", 502) for _ in range(3)])
    monkeypatch.setattr(openai_media, "request", recorder)

    import asyncio

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))

    assert len(recorder.calls) == 3
    assert excinfo.value.http_status == 502 and "3 attempts" in str(excinfo.value)


def test_an_image_request_that_left_and_got_no_answer_is_not_sent_again(monkeypatch):
    from app.providers import openai_media

    recorder = Recorder(
        MediaProviderError("api.openai.com did not answer", unanswered=True),
        ({"data": []}, b"", "application/json"),
    )
    monkeypatch.setattr(openai_media, "request", recorder)

    import asyncio

    with pytest.raises(MediaProviderError):
        asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope"))

    assert len(recorder.calls) == 1


# --- the HTTPS boundary says what kind of failure it saw ----------------------------------


class FakeHTTPSConnection:
    """One scripted exchange over `http.client`, for media_http.request itself."""

    script: list = []

    def __init__(self, host, timeout=None):
        self.host = host
        self.timeout = timeout

    def request(self, method, path, body, headers):
        step = self.script[0]
        if step.get("connect") is not None:
            self.script.pop(0)
            raise step["connect"]

    def getresponse(self):
        step = self.script.pop(0)
        if step.get("read") is not None:
            raise step["read"]
        resp = MagicMock()
        resp.status = step["status"]
        resp.read = MagicMock(return_value=step.get("body", b"{}"))
        resp.headers.get_content_type = MagicMock(return_value="application/json")
        resp.getheader = lambda name, default=None: step.get("headers", {}).get(name, default)
        return resp

    def close(self):
        pass


@pytest.fixture
def https_script(monkeypatch):
    from app.providers import media_http

    FakeHTTPSConnection.script = []
    monkeypatch.setattr(media_http.http.client, "HTTPSConnection", FakeHTTPSConnection)
    return FakeHTTPSConnection.script


def test_the_boundary_reports_the_status_and_the_vendors_retry_after(https_script):
    from app.providers.media_http import request

    https_script.append(
        {
            "status": 429,
            "body": b'{"detail": {"status": "too_many_concurrent_requests"}}',
            "headers": {"Retry-After": "3"},
        }
    )
    with pytest.raises(MediaProviderError) as excinfo:
        request("api.elevenlabs.io", "POST", "/v1/text-to-speech/v", {}, b"{}")
    error = excinfo.value
    assert (error.http_status, error.retry_after) == (429, 3.0)
    assert error.code == "too_many_concurrent_requests"
    assert not error.unsent and not error.unanswered


def test_the_boundary_says_when_the_request_never_left(https_script):
    from app.providers.media_http import request

    https_script.append({"connect": ConnectionRefusedError("refused")})
    with pytest.raises(MediaProviderError) as excinfo:
        request("api.elevenlabs.io", "POST", "/v1/text-to-speech/v", {}, b"{}")
    assert excinfo.value.unsent and not excinfo.value.unanswered
    assert excinfo.value.http_status is None


def test_the_boundary_says_when_the_request_left_but_nothing_came_back(https_script):
    from app.providers.media_http import request

    https_script.append({"read": TimeoutError("timed out")})
    with pytest.raises(MediaProviderError) as excinfo:
        request("api.elevenlabs.io", "POST", "/v1/text-to-speech/v", {}, b"{}")
    assert excinfo.value.unanswered and not excinfo.value.unsent
    assert "did not answer" in str(excinfo.value)


# --- a character's reference picture at the adapter boundary ----------------------------


class RawRecorder(Recorder):
    """Like `Recorder`, but keeps the body exactly as the adapter built it.

    A multipart body is not JSON, and reading it as JSON is how a test would fail to notice
    that the reference bytes never left.
    """

    def __call__(self, host, method, path, headers, body=None, *, timeout=120, expect_json=True):
        self.calls.append(
            {"host": host, "method": method, "path": path, "headers": headers, "body": body}
        )
        if not self.responses:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_an_adapter_declares_whether_it_can_be_given_a_reference_picture():
    """The studio asks before it hands one over, rather than hoping the vendor ignores it."""
    from app.media.factory import accepts_reference_image

    assert OpenAIImageAdapter("key").ACCEPTS_REFERENCE_IMAGE is True
    assert accepts_reference_image(OpenAIImageAdapter("key")) is True

    class SomeOtherVendor:
        PROVIDER_NAME = "SOMETHING_ELSE"

    # An adapter that says nothing cannot take one: silence is not a capability.
    assert accepts_reference_image(SomeOtherVendor()) is False


def test_a_reference_picture_is_sent_as_the_image_to_work_from(monkeypatch):
    """The character's stored reference goes to the edits endpoint as a file part."""
    import asyncio

    from app.providers import openai_media

    reference = png_bytes(16, 24)
    payload = {"data": [{"b64_json": base64.b64encode(png_bytes(1024, 1536)).decode()}]}
    recorder = RawRecorder((payload, b"", "application/json"))
    monkeypatch.setattr(openai_media, "request", recorder)

    result = asyncio.run(
        OpenAIImageAdapter("key").generate_image(
            "Sarah at her desk",
            width=1080,
            height=1920,
            extra={"reference_image": {"bytes": reference, "mime_type": "image/png"}},
        )
    )

    assert (result.width, result.height) == (1024, 1536)
    call = recorder.calls[0]
    assert call["path"] == "/v1/images/edits"
    assert call["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert reference in call["body"], "the reference bytes never left the adapter"
    assert b'name="image[]"' in call["body"]
    assert b"Sarah at her desk" in call["body"]
    assert result.raw_response["reference_images"] == 1


def test_without_a_reference_the_adapter_keeps_asking_for_a_plain_generation(monkeypatch):
    """Nothing changes for a scene with no character: the same endpoint, the same body."""
    import asyncio

    from app.providers import openai_media

    payload = {"data": [{"b64_json": base64.b64encode(png_bytes(1024, 1536)).decode()}]}
    recorder = Recorder((payload, b"", "application/json"))
    monkeypatch.setattr(openai_media, "request", recorder)

    asyncio.run(OpenAIImageAdapter("key").generate_image("a telescope", extra={"scene_index": 1}))

    assert recorder.calls[0]["path"] == "/v1/images/generations"


def test_a_reference_that_is_not_bytes_is_refused_before_the_vendor_is_called(monkeypatch):
    """A path, a description or an id is not a picture, and would be sent as a form field."""
    import asyncio

    from app.providers import openai_media

    recorder = RawRecorder()
    monkeypatch.setattr(openai_media, "request", recorder)

    with pytest.raises(MediaProviderError):
        asyncio.run(
            OpenAIImageAdapter("key").generate_image(
                "Sarah at her desk",
                extra={"reference_image": {"bytes": "/storage/portrait.png"}},
            )
        )

    assert recorder.calls == []
