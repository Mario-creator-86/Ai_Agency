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

    def __call__(
        self,
        host,
        method,
        path,
        headers,
        body=None,
        *,
        timeout=120,
        expect_json=True,
        public_only=False,
    ):
        self.calls.append(
            {
                "host": host,
                "method": method,
                "path": path,
                "headers": headers,
                "body": json.loads(body) if body and expect_json is not False else body,
                "public_only": public_only,
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
    # Bare audio carries no alignment, so none is reported (the timed answer is covered in
    # test_elevenlabs_timestamps.py).
    assert result.word_timings == []
    assert recorder.calls[0]["path"] == (
        "/v1/text-to-speech/v1/with-timestamps?output_format=mp3_44100_128"
    )


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
    assert [c["path"] for c in recorder.calls] == [
        "/v1/text-to-speech/v1/with-timestamps?output_format=mp3_44100_128"
    ] * 2


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


# --- the same picture, handed to Runway -------------------------------------------------
# Measured before this work: `RunwayImageAdapter` had no way to be given a reference, so
# `accepts_reference_image` read False for it, the chain dropped the character's sheet and a
# Runway-drawn still of a character with a locked look was honestly recorded as drawn from
# the words. Runway's text_to_image task publishes `referenceImages`; this is that field.

RUNWAY_CONTRACT = {
    "tasks": ["text_to_image"],
    "ratios": {"text_to_image": ["1080:1920"]},
    "needs_references": {"text_to_image": False},
}


class RunwayTransport:
    """Runway's HTTPS boundary, faked: submit a task, poll it once, download the still.

    No request leaves the machine and no credit is spent; what is asserted is the body the
    adapter built, which is the only thing a test may know about a vendor it never called.
    """

    def __init__(self, still: bytes) -> None:
        self.still = still
        self.calls: list[dict] = []

    def __call__(self, host, method, path, headers, body=None, **_kwargs):
        self.calls.append({"host": host, "method": method, "path": path, "body": body})
        if path == "/v1/text_to_image":
            return {"id": "task-1"}, b"", "application/json"
        if path.startswith("/v1/tasks/"):
            return (
                {"status": "SUCCEEDED", "output": ["https://files.test/still.png"]},
                b"",
                "application/json",
            )
        if host == "files.test":
            return None, self.still, "image/png"
        raise AssertionError(f"the adapter asked for {host}{path}, which the test did not expect")


def _runway(monkeypatch, still: bytes, contract: dict | None = None):
    from app.providers import runway
    from app.providers.runway import RunwayImageAdapter

    transport = RunwayTransport(still)
    monkeypatch.setattr(runway, "request", transport)
    adapter = RunwayImageAdapter("key", "gen4_image", dict(contract or RUNWAY_CONTRACT))
    return adapter, transport


def test_a_runway_still_is_drawn_from_the_characters_reference_picture(monkeypatch):
    """The reference reaches the task body as `referenceImages`, in the documented shape."""
    import asyncio

    from app.media.factory import accepts_reference_image

    reference = png_bytes(16, 24)
    adapter, transport = _runway(monkeypatch, png_bytes(1080, 1920))
    assert accepts_reference_image(adapter) is True

    result = asyncio.run(
        adapter.generate_image(
            "Sarah at her desk",
            width=1080,
            height=1920,
            extra={"reference_image": {"bytes": reference, "mime_type": "image/png"}},
        )
    )

    submitted = json.loads(transport.calls[0]["body"])
    assert transport.calls[0]["path"] == "/v1/text_to_image"
    # An array of objects whose one required member is a URI. The studio holds the bytes and
    # not a URL the vendor could fetch, so it is the data-URI form.
    assert submitted["referenceImages"] == [
        {"uri": "data:image/png;base64," + base64.b64encode(reference).decode("ascii")}
    ]
    assert submitted["promptText"] == "Sarah at her desk"
    assert result.raw_response["reference_images"] == 1
    assert (result.width, result.height) == (1080, 1920)


def test_a_runway_reference_that_is_not_a_picture_is_refused_before_any_call(monkeypatch):
    """A path, an id or a description is not a picture; nor are bytes that are not an image.
    Either would be a 400 for every scene of a film, after the task was submitted."""
    import asyncio

    for reference in (
        {"bytes": "/storage/character_references/sarah/portrait.png"},
        {"bytes": b"this is not a picture"},
        "portrait.png",
    ):
        adapter, transport = _runway(monkeypatch, png_bytes(8, 8))
        with pytest.raises(MediaProviderError):
            asyncio.run(
                adapter.generate_image("Sarah at her desk", extra={"reference_image": reference})
            )
        assert transport.calls == [], f"{reference!r} reached the vendor"


def test_a_runway_model_that_takes_no_reference_still_draws_from_words(monkeypatch):
    """A scene with nobody in it is the film the studio has always made: the same task, the
    same body, and no field that was not there before."""
    import asyncio

    adapter, transport = _runway(monkeypatch, png_bytes(1080, 1920))

    result = asyncio.run(adapter.generate_image("a telescope", extra={"scene_index": 1}))

    submitted = json.loads(transport.calls[0]["body"])
    assert "referenceImages" not in submitted
    assert result.raw_response["reference_images"] == 0


def test_a_runway_model_that_requires_a_reference_is_refused_only_without_one(monkeypatch):
    """gen4_image_turbo edits pictures it is given; it answered HTTP 400 to every scene of a
    day drawn from words alone, and the contract says so before the call. Now that the studio
    can hand it the character's sheet, the refusal is about the missing picture and not about
    the model: with one, the same model draws."""
    import asyncio

    contract = {**RUNWAY_CONTRACT, "needs_references": {"text_to_image": True}}
    reference = png_bytes(16, 24)

    adapter, transport = _runway(monkeypatch, png_bytes(1080, 1920), contract)
    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.generate_image("Sarah at her desk"))
    assert excinfo.value.code == "reference_images_required"
    assert transport.calls == []

    adapter, transport = _runway(monkeypatch, png_bytes(1080, 1920), contract)
    result = asyncio.run(
        adapter.generate_image(
            "Sarah at her desk",
            extra={"reference_image": {"bytes": reference, "mime_type": "image/png"}},
        )
    )
    assert result.raw_response["reference_images"] == 1


def test_no_runway_reference_path_is_marked_verified():
    """The code sends the field; the account has never answered it. `REFERENCE_IMAGE_VERIFIED`
    is the statement about the vendor, and it stays False until an Owner-approved live run
    has actually drawn a scene this way."""
    from app.providers.runway import RunwayImageAdapter

    adapter = RunwayImageAdapter("key", "gen4_image", dict(RUNWAY_CONTRACT))
    assert adapter.ACCEPTS_REFERENCE_IMAGE is True
    assert adapter.REFERENCE_IMAGE_VERIFIED is False
    assert OpenAIImageAdapter("key").REFERENCE_IMAGE_VERIFIED is False


# --- RUNWAY_TRUTH: the body a motion task is bought with ---------------------------------
# The Nepal film (2026-09-26) paid for clips whose requests were wrong in ways no test saw:
# generated soundtracks nobody used, a veo request with its exclusions written into the
# picture's own words, a first frame of a different aspect than the one asked for. What is
# asserted here is the body the adapter built, recorded by a fake transport; no request
# leaves the machine and no credit is spent.


def jpeg_bytes() -> bytes:
    """A minimal JPEG header (SOI + SOF0 for 1080x1920), enough to be told from a PNG."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 1920, 1080, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + sof


def _video_contract(fields: list[str], ratios: list[str], durations) -> dict:
    return {
        "tasks": ["image_to_video", "text_to_video"],
        "ratios": {"image_to_video": ratios, "text_to_video": ratios},
        "durations": {"image_to_video": durations, "text_to_video": durations},
        "fields": {"image_to_video": fields, "text_to_video": fields},
    }


SEEDANCE = _video_contract(
    ["audio", "duration", "model", "promptImage", "promptText", "ratio", "seed"],
    ["1080:1920", "720:1280", "1920:1080"],
    {"min": 4, "max": 30},
)
VEO = _video_contract(
    ["duration", "model", "negativePrompt", "promptImage", "promptText", "ratio", "seed"],
    ["1080:1920", "1920:1080"],
    [4, 6, 8],
)
WAN = _video_contract(
    ["duration", "model", "promptImage", "promptText", "ratio", "seed"],
    ["1280:720", "720:1280", "auto_720p", "auto_1080p"],
    [5, 10],
)


def _runway_video(monkeypatch, model: str, contract: dict):
    from app.providers import runway
    from app.providers.runway import RunwayVideoAdapter

    recorder = Recorder(({"id": "task-1"}, b"", "application/json"))
    monkeypatch.setattr(runway, "request", recorder)
    return RunwayVideoAdapter("key", model, dict(contract)), recorder


def _submit(adapter, prompt: str = "Slow push-in. Continuous, seamless shot.", **kwargs):
    import asyncio

    kwargs.setdefault("image_ref", jpeg_bytes())
    kwargs.setdefault("duration_seconds", 4.4)
    return asyncio.run(adapter.create_generation(prompt, aspect_ratio="9:16", **kwargs))


def test_a_seedance_shot_is_bought_silent_with_the_films_seed(monkeypatch):
    """The narration is the film's only sound: a generated soundtrack is paid for and
    thrown away. The film's one seed goes with every shot."""
    adapter, recorder = _runway_video(monkeypatch, "seedance2_5", SEEDANCE)

    _submit(adapter, extra={"seed": 1234567})

    body = recorder.calls[0]["body"]
    assert recorder.calls[0]["path"] == "/v1/image_to_video"
    assert body["audio"] is False
    assert body["seed"] == 1234567
    assert body["ratio"] == "1080:1920"
    assert body["duration"] == 5  # 4.4 s rounded up, never down


def test_a_model_whose_contract_has_no_audio_field_is_not_sent_one(monkeypatch):
    """A field the contract does not declare is a 400 waiting to happen, or worse, a
    field the vendor reads some other way."""
    adapter, recorder = _runway_video(monkeypatch, "wan3_prime", WAN)

    _submit(adapter, extra={"seed": 7, "negative_prompt": "human faces, text"})

    body = recorder.calls[0]["body"]
    assert "audio" not in body and "negativePrompt" not in body
    assert body["seed"] == 7


def test_a_veo_shot_carries_its_exclusions_as_a_negative_prompt(monkeypatch):
    adapter, recorder = _runway_video(monkeypatch, "veo3.1", VEO)

    _submit(
        adapter,
        prompt="Slow push-in over terraced fields, mist drifting.",
        extra={"negative_prompt": "human faces, text, subtitles, logo, watermark"},
    )

    body = recorder.calls[0]["body"]
    assert body["negativePrompt"] == "human faces, text, subtitles, logo, watermark"
    assert body["promptText"] == "Slow push-in over terraced fields, mist drifting."
    assert body["duration"] == 6  # veo takes 4, 6 or 8


def test_a_wan_keyframe_shot_keeps_the_frames_own_ratio_at_1080p(monkeypatch):
    """wan3_prime offers explicit ratios only at 720p; `auto_1080p` keeps the 9:16 still's
    framing at the higher resolution."""
    adapter, recorder = _runway_video(monkeypatch, "wan3_prime", WAN)

    _submit(adapter)

    assert recorder.calls[0]["body"]["ratio"] == "auto_1080p"


def test_without_a_first_frame_an_auto_ratio_is_never_chosen(monkeypatch):
    """`auto` follows a picture; with no picture there is nothing for it to follow."""
    adapter, recorder = _runway_video(monkeypatch, "wan3_prime", WAN)

    _submit(adapter, image_ref=None)

    assert recorder.calls[0]["body"]["ratio"] == "720:1280"


def test_the_first_frame_travels_as_a_jpeg(monkeypatch):
    frame = jpeg_bytes()
    adapter, recorder = _runway_video(monkeypatch, "seedance2_5", SEEDANCE)

    _submit(adapter, image_ref=frame)

    image = recorder.calls[0]["body"]["promptImage"]
    assert image == "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")


def test_a_long_prompt_is_cut_at_a_sentence_within_the_contracts_cap(monkeypatch):
    """Sliced at a character count, a prompt ended mid-word in the Nepal film. The cap is
    the contract's, counted in UTF-16 units as the vendor counts."""
    contract = {**VEO, "prompt_max": {"image_to_video": 120, "text_to_video": 120}}
    adapter, recorder = _runway_video(monkeypatch, "veo3.1", contract)
    first = "Slow push-in over terraced fields in Nepal, mist drifting past the ridge."
    prompt = first + " Continuous, seamless shot. " + "Aerial drift forward. " * 20

    _submit(adapter, prompt=prompt)

    sent = recorder.calls[0]["body"]["promptText"]
    assert len(sent.encode("utf-16-le")) // 2 <= 120
    assert sent == first + " Continuous, seamless shot."


def test_a_prompt_with_no_sentence_end_in_reach_is_cut_at_a_word(monkeypatch):
    contract = {**VEO, "prompt_max": {"image_to_video": 40, "text_to_video": 40}}
    adapter, recorder = _runway_video(monkeypatch, "veo3.1", contract)

    _submit(adapter, prompt="terraced fields and mist and rivers and more mist and ridges")

    sent = recorder.calls[0]["body"]["promptText"]
    assert len(sent) <= 40 and not sent.endswith(" ")
    assert "terraced fields and mist and rivers and more mist and ridges".startswith(sent)


# --- a refusal keeps its reason, and nothing secret ---------------------------------------


def test_a_400_body_survives_sanitised_and_capped(https_script):
    """Runway's 400 names the field it refused. The studio threw that away and changed
    the model instead; now the reason survives, without a key, a picture or a signed URL."""
    from app.providers.media_http import request

    secret = "key_" + "a1b2c3d4" * 8
    frame = "data:image/jpeg;base64," + "QUJD" * 200
    body = {
        "error": f"Validation of body failed (Authorization: Bearer {secret})",
        "issues": [
            {"path": ["ratio"], "message": "Invalid enum value. Expected '720:1280'"},
            {"path": ["promptImage"], "message": f"Image too large: {frame}"},
            {"path": "duration", "message": "See https://files.test/x.mp4?sig=abcdef"},
        ]
        + [{"path": ["promptText"], "message": "String must contain at most 1000 characters"}] * 20,
    }
    https_script.append({"status": 400, "body": json.dumps(body).encode()})

    with pytest.raises(MediaProviderError) as excinfo:
        request("api.dev.runwayml.com", "POST", "/v1/image_to_video", {}, b"{}")

    error = excinfo.value
    assert error.http_status == 400
    assert error.detail is not None and len(error.detail) <= 500
    assert "Validation of body failed" in error.detail
    assert "ratio: Invalid enum value. Expected '720:1280'" in error.detail
    assert error.issues[0] == {
        "path": "ratio",
        "message": "Invalid enum value. Expected '720:1280'",
    }
    assert len(error.issues) <= 10
    everything = error.detail + json.dumps(error.issues) + str(error)
    for leaked in (secret, "QUJDQUJD", "sig=abcdef", "Bearer key_"):
        assert leaked not in everything
    # The message the Owner already knew stays as it was; the reason travels beside it.
    assert str(error) == "api.dev.runwayml.com refused the request (HTTP 400)"


def test_an_error_body_that_is_not_json_leaves_no_detail(https_script):
    from app.providers.media_http import request

    https_script.append({"status": 502, "body": b"<html>bad gateway</html>"})

    with pytest.raises(MediaProviderError) as excinfo:
        request("api.dev.runwayml.com", "GET", "/v1/tasks/t", {})

    assert excinfo.value.detail is None and excinfo.value.issues == []


def test_a_failed_tasks_reason_is_kept_sanitised(monkeypatch):
    import asyncio

    from app.providers import runway
    from app.providers.runway import RunwayVideoAdapter

    failed = {
        "id": "task-1",
        "status": "FAILED",
        "failureCode": "INPUT_PREPROCESSING.SAFETY.THIRD_PARTY",
        "failure": "Input rejected: https://files.test/frame.jpg?sig=zzz9999",
    }
    monkeypatch.setattr(runway, "request", Recorder((failed, b"", "application/json")))

    status = asyncio.run(RunwayVideoAdapter("key", "m", {}).get_generation_status("task-1"))

    assert status.status == "FAILED"
    assert status.raw_response["failure_code"] == "INPUT_PREPROCESSING.SAFETY.THIRD_PARTY"
    assert status.raw_response["failure"].startswith("Input rejected:")
    assert "sig=zzz9999" not in status.raw_response["failure"]


# --- a Runway output is fetched only from a public address (SEC-08) ----------------------
#
# The vendor names the address its output is served from. A compromised or confused answer
# could name an address inside the Owner's network; the studio would then fetch it. Runway's
# docs (https://docs.dev.runwayml.com/assets/outputs/, read 2026-10-01) show an example output
# host but publish no list of output domains, so no domain is pinned: what is enforced is that
# the address is public, before any socket (a literal or a private-use name) and again at the
# connection (the name resolved, every address public, the socket pinned to one of them).


def _finished_task(url: str) -> Recorder:
    return Recorder(({"id": "task-1", "status": "SUCCEEDED", "output": [url]}, b"", "x/json"))


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/x",
        "https://intranet.local/x",
        "https://localhost/out.mp4",
        "https://studio.localhost/out.mp4",
        "https://10.0.0.5/out.mp4",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/out.mp4",
        "https://intranet/out.mp4",
        "https://files.internal/out.mp4",
        "http://cdn.example.com/out.mp4",
    ],
)
def test_a_runway_output_on_a_private_address_is_refused_before_any_socket(monkeypatch, url):
    import asyncio

    from app.providers import runway
    from app.providers.runway import RunwayVideoAdapter

    recorder = _finished_task(url)
    monkeypatch.setattr(runway, "request", recorder)

    with pytest.raises(MediaProviderError):
        asyncio.run(RunwayVideoAdapter("key", "gen4_turbo", {}).get_generation_status("task-1"))

    # The task was read; nothing was asked of the address it named.
    assert [call["path"] for call in recorder.calls] == ["/v1/tasks/task-1"]


def test_a_runway_output_is_downloaded_only_through_a_public_pinned_connection(monkeypatch):
    import asyncio

    from app.providers import runway
    from app.providers.runway import RunwayVideoAdapter

    recorder = Recorder(
        (
            {"id": "task-1", "status": "SUCCEEDED", "output": ["https://cdn.vendor.example/o.mp4"]},
            b"",
            "application/json",
        ),
        (None, b"MP4BYTES", "video/mp4"),
    )
    monkeypatch.setattr(runway, "request", recorder)

    done = asyncio.run(RunwayVideoAdapter("key", "gen4_turbo", {}).get_generation_status("t"))

    assert done.video_bytes == b"MP4BYTES"
    assert recorder.calls[-1]["host"] == "cdn.vendor.example"
    assert recorder.calls[-1]["public_only"] is True
    # The API itself is asked as before: its name is the vendor's, written in the code.
    assert recorder.calls[0]["public_only"] is False


def test_a_public_only_request_to_a_name_that_resolves_inside_is_refused(monkeypatch):
    import socket

    from app.providers import media_http

    def lookup(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443))]

    opened: list[str] = []
    monkeypatch.setattr(media_http.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(media_http, "PinnedHTTPSConnection", lambda *a, **k: opened.append("x"))

    with pytest.raises(MediaProviderError) as excinfo:
        media_http.request(
            "cdn.vendor.example", "GET", "/o.mp4", {}, expect_json=False, public_only=True
        )
    assert excinfo.value.unsent is True and opened == []


def test_a_public_only_request_connects_to_the_address_it_checked(monkeypatch):
    import socket

    from app.providers import media_http

    def lookup(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

    class Pinned:
        made: list[tuple[str, str]] = []

        def __init__(self, host, address, timeout=None):
            Pinned.made.append((host, address))

        def request(self, *_args):
            return None

        def getresponse(self):
            answer = MagicMock()
            answer.status = 200
            answer.read = MagicMock(return_value=b"MP4BYTES")
            answer.headers.get_content_type = MagicMock(return_value="video/mp4")
            return answer

        def close(self):
            return None

    monkeypatch.setattr(media_http.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(media_http, "PinnedHTTPSConnection", Pinned)

    _, payload, kind = media_http.request(
        "cdn.vendor.example", "GET", "/o.mp4", {}, expect_json=False, public_only=True
    )

    assert payload == b"MP4BYTES" and kind == "video/mp4"
    assert Pinned.made == [("cdn.vendor.example", "93.184.215.14")]
