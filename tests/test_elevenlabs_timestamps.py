"""Narration comes back with its own clock: ElevenLabs /with-timestamps.

The captions of a film are timed to the words the voice says. Until now the adapter called the
plain text-to-speech endpoint, which returns audio and nothing else, so every caption was placed
by its share of the characters - close on a short line, visibly late or early on a long one.
The vendor's documented POST /v1/text-to-speech/{voice_id}/with-timestamps answers JSON instead:
``audio_base64`` plus ``alignment`` and ``normalized_alignment``, each
``{characters, character_start_times_seconds, character_end_times_seconds}``. It is billed per
character like the plain endpoint (the API pricing page lists no surcharge for timing).

Two things matter more than the happy path. A narration is a purchase, so once audio has come
back it is never asked for again, whatever is wrong with the timing beside it. And a timing that
is not about these words, or not this audio, is dropped rather than trusted: a wrong clock
drives captions that match nothing, which is worse than the character-share fallback.

Every vendor call here is a fake transport; nothing leaves the machine.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import pytest
from app.providers import elevenlabs
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import MediaProviderError

TIMED_PATH = "/v1/text-to-speech/v1/with-timestamps?output_format=mp3_44100_128"
PLAIN_PATH = "/v1/text-to-speech/v1?output_format=mp3_44100_128"

#: A Romanian line with diacritics (comma-below s, a with breve, i with circumflex), a comma, a
#: thousands dot, a dash standing alone and a closing full stop.
ROMANIAN = "Ziua începe în Kathmandu, la 1.400 de metri — și orașul încă doarme."


def mp3_bytes(frames: int) -> bytes:
    """Constant-bitrate MPEG-1 Layer III frames: 128 kbps, 44.1 kHz, 1152 samples each."""
    frame_length = int(144 * 128000 / 44100)
    return (bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * (frame_length - 4)) * frames


def alignment_for(text: str, step: float = 0.04, start: float = 0.1) -> dict:
    """The vendor's character alignment for `text`: one character every `step` seconds."""
    characters = list(text)
    starts = [round(start + i * step, 3) for i in range(len(characters))]
    ends = [round(s + step, 3) for s in starts]
    return {
        "characters": characters,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }


def expected_words(text: str) -> list[dict]:
    """Each word from its first character's start to its last character's end, read straight
    off the vendor's numbers (no rounding of our own)."""
    timing = alignment_for(text)
    starts = timing["character_start_times_seconds"]
    ends = timing["character_end_times_seconds"]
    words, index = [], 0
    for word in text.split(" "):
        first, last = index, index + len(word) - 1
        words.append({"word": word, "start": starts[first], "end": ends[last]})
        index += len(word) + 1
    return words


def timed_answer(
    audio: bytes,
    alignment: object = "default",
    normalized: object = "default",
    text: str = ROMANIAN,
) -> tuple[None, bytes, str]:
    body = {"audio_base64": base64.b64encode(audio).decode("ascii")}
    body["alignment"] = alignment_for(text) if alignment == "default" else alignment
    body["normalized_alignment"] = alignment_for(text) if normalized == "default" else normalized
    return None, json.dumps(body).encode("utf-8"), "application/json"


def refused(status: int, **kwargs) -> MediaProviderError:
    return MediaProviderError(
        f"api.elevenlabs.io refused the request (HTTP {status})", http_status=status, **kwargs
    )


class Transport:
    """Stands in for the network and remembers exactly what was asked of it."""

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
        total_seconds=None,
    ):
        self.calls.append(
            {
                "host": host,
                "method": method,
                "path": path,
                "headers": headers,
                "body": json.loads(body) if body else None,
                "expect_json": expect_json,
            }
        )
        if not self.responses:
            raise AssertionError("the adapter asked the vendor more times than the test allows")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def speak(monkeypatch, *responses, text: str = ROMANIAN):
    transport = Transport(*responses)
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")
    return transport, asyncio.run(adapter.synthesize(text))


# --- the request ------------------------------------------------------------------------


def test_narration_is_asked_for_with_its_timestamps(monkeypatch):
    transport, _ = speak(monkeypatch, timed_answer(mp3_bytes(120)))

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["host"] == "api.elevenlabs.io" and call["method"] == "POST"
    assert call["path"] == TIMED_PATH
    assert call["headers"]["Accept"] == "application/json"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["headers"]["xi-api-key"] == "key"
    assert call["body"]["text"] == ROMANIAN
    assert call["body"]["model_id"] == "test-model"
    assert call["body"]["voice_settings"]["speed"] == 1.0
    # The JSON answer carries the audio inline, so it is read under the media size cap, not
    # the small cap a catalogue answer gets: a long narration must not be refused for size.
    assert call["expect_json"] is False


# --- the answer -------------------------------------------------------------------------


def test_the_audio_is_decoded_and_measured_from_its_frames(monkeypatch):
    audio = mp3_bytes(120)
    _, result = speak(monkeypatch, timed_answer(audio))

    assert result.audio_bytes == audio
    assert result.format == "mp3"
    assert result.duration_seconds == pytest.approx(3.135, abs=0.002)
    assert result.raw_response["endpoint"] == "with-timestamps"
    assert result.raw_response["bytes"] == len(audio)
    assert result.raw_response["characters"] == len(ROMANIAN)


def test_the_alignment_is_kept_and_the_audio_is_not(monkeypatch):
    _, result = speak(monkeypatch, timed_answer(mp3_bytes(120)))

    assert result.raw_response["alignment"] == alignment_for(ROMANIAN)
    assert result.raw_response["normalized_alignment"] == alignment_for(ROMANIAN)
    # The audio is the result's bytes; a second, base64 copy would ride along wherever the
    # raw response is kept.
    assert "audio_base64" not in json.dumps(result.raw_response)


def test_a_romanian_line_is_timed_word_by_word_from_the_characters(monkeypatch):
    _, result = speak(monkeypatch, timed_answer(mp3_bytes(120)))

    assert result.word_timings == expected_words(ROMANIAN)
    assert [w["word"] for w in result.word_timings] == ROMANIAN.split()
    # Diacritics stay inside their word, punctuation stays with the word it follows, and a
    # dash said on its own is its own word, exactly as the caption splits the line.
    assert result.word_timings[1]["word"] == "începe"
    assert result.word_timings[3]["word"] == "Kathmandu,"
    assert result.word_timings[8]["word"] == "—"
    assert result.word_timings[-1]["word"] == "doarme."


def test_the_assembler_reads_the_same_clock_the_adapter_reports(monkeypatch):
    from app.media.assembler import take_word_timing

    _, result = speak(monkeypatch, timed_answer(mp3_bytes(120)))

    assert take_word_timing(result) == result.word_timings


def test_decomposed_diacritics_from_the_vendor_still_match_the_line(monkeypatch):
    """Unicode allows "ș" as s + combining comma below; the vendor may answer either way."""
    import unicodedata

    decomposed = unicodedata.normalize("NFD", ROMANIAN)
    _, result = speak(
        monkeypatch,
        timed_answer(mp3_bytes(120), alignment=alignment_for(decomposed), text=decomposed),
    )

    assert len(result.word_timings) == len(ROMANIAN.split())


def test_only_the_normalized_alignment_still_times_the_captions(monkeypatch):
    """The normalized text spells numbers out, so it is kept for the assembler (which checks
    it against the words said) but does not become the adapter's word timing."""
    spoken = "Ziua începe în Kathmandu, la o mie patru sute de metri — și orașul încă doarme."
    _, result = speak(
        monkeypatch,
        timed_answer(mp3_bytes(200), alignment=None, normalized=alignment_for(spoken)),
    )

    assert result.word_timings == []
    assert "alignment" not in result.raw_response
    assert result.raw_response["normalized_alignment"] == alignment_for(spoken)


# --- a timing that cannot be trusted ----------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [
        {"characters": ["a"], "character_start_times_seconds": [0.0]},
        {
            "characters": list("ab"),
            "character_start_times_seconds": [0.0, 0.1],
            "character_end_times_seconds": [0.1],
        },
        {
            "characters": list("ab"),
            "character_start_times_seconds": [0.0, "x"],
            "character_end_times_seconds": [0.1, 0.2],
        },
        {
            "characters": list("ab"),
            "character_start_times_seconds": [0.3, 0.1],
            "character_end_times_seconds": [0.4, 0.2],
        },
        {
            "characters": list("ab"),
            "character_start_times_seconds": [0.0, 0.1],
            "character_end_times_seconds": [-0.1, 0.2],
        },
        {
            "characters": list("ab"),
            "character_start_times_seconds": [0.0, float("nan")],
            "character_end_times_seconds": [0.1, 0.2],
        },
        "not an alignment",
        [],
    ],
)
def test_a_malformed_alignment_leaves_the_timing_empty_and_keeps_the_audio(
    monkeypatch, caplog, broken
):
    caplog.set_level(logging.WARNING, logger="app.providers.elevenlabs")
    audio = mp3_bytes(120)
    transport, result = speak(monkeypatch, timed_answer(audio, alignment=broken, normalized=None))

    assert len(transport.calls) == 1, "the narration was bought once and is not asked again"
    assert result.audio_bytes == audio
    assert result.word_timings == []
    assert "alignment" not in result.raw_response
    assert result.raw_response["alignment_problem"]
    assert any("alignment" in r.getMessage() for r in caplog.records)


def test_a_nan_in_the_answer_does_not_break_the_film(monkeypatch):
    """JSON from the wire can carry NaN; a timing with one is dropped, the audio kept."""
    audio = mp3_bytes(120)
    body = (
        '{"audio_base64": "' + base64.b64encode(audio).decode("ascii") + '", '
        '"alignment": {"characters": ["a"], "character_start_times_seconds": [NaN], '
        '"character_end_times_seconds": [0.1]}}'
    ).encode("utf-8")
    transport, result = speak(monkeypatch, (None, body, "application/json"), text="a")

    assert len(transport.calls) == 1
    assert result.word_timings == []


def test_a_timing_about_other_words_is_not_trusted(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.providers.elevenlabs")
    other = "Noaptea cade peste Kathmandu și orașul doarme."
    transport, result = speak(
        monkeypatch, timed_answer(mp3_bytes(120), alignment=alignment_for(other), normalized=None)
    )

    assert len(transport.calls) == 1
    assert result.word_timings == []
    assert "alignment" not in result.raw_response
    assert any("alignment" in r.getMessage() for r in caplog.records)


def test_a_timing_that_runs_past_the_audio_is_not_trusted(monkeypatch):
    # 20 frames = 0.52 s of audio; the line's alignment runs for almost three seconds.
    transport, result = speak(monkeypatch, timed_answer(mp3_bytes(20), normalized=None))

    assert len(transport.calls) == 1
    assert result.word_timings == []
    assert "alignment" not in result.raw_response


def test_audio_that_does_not_decode_raises_without_asking_again(monkeypatch):
    body = json.dumps({"audio_base64": "this is not base64 !!!", "alignment": None})
    transport = Transport((None, body.encode("utf-8"), "application/json"))
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    with pytest.raises(MediaProviderError, match="audio"):
        asyncio.run(adapter.synthesize(ROMANIAN))
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        (None, b"{not json", "application/json"),
        (None, json.dumps({"alignment": None}).encode(), "application/json"),
        (None, json.dumps({"audio_base64": ""}).encode(), "application/json"),
        (None, json.dumps(["audio"]).encode(), "application/json"),
        (None, b"<html>busy</html>", "text/html"),
    ],
)
def test_an_answer_without_audio_raises_without_asking_again(monkeypatch, answer):
    transport = Transport(answer)
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.synthesize(ROMANIAN))
    assert len(transport.calls) == 1


def test_audio_answered_directly_on_the_timed_endpoint_is_kept_not_bought_again(monkeypatch):
    """Should the vendor ever answer this endpoint with bare audio, that audio was billed."""
    audio = mp3_bytes(120)
    transport, result = speak(monkeypatch, (None, audio, "audio/mpeg"))

    assert len(transport.calls) == 1
    assert result.audio_bytes == audio and result.word_timings == []
    assert result.raw_response["alignment_problem"]


# --- the fallback -----------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 405, 422])
def test_a_contract_change_falls_back_to_the_plain_endpoint_once(monkeypatch, caplog, status):
    caplog.set_level(logging.WARNING, logger="app.providers.elevenlabs")
    audio = mp3_bytes(120)
    transport, result = speak(monkeypatch, refused(status), (None, audio, "audio/mpeg"))

    assert [c["path"] for c in transport.calls] == [TIMED_PATH, PLAIN_PATH]
    assert transport.calls[1]["headers"]["Accept"] == "audio/mpeg"
    assert transport.calls[1]["body"] == transport.calls[0]["body"], "the same narration"
    assert result.audio_bytes == audio
    assert result.word_timings == []
    assert result.raw_response["endpoint"] == "text-to-speech"
    assert result.raw_response["timestamps_refused"] == status
    assert any("with-timestamps" in r.getMessage() for r in caplog.records)


def test_the_fallback_is_tried_once_and_its_refusal_is_the_error(monkeypatch):
    transport = Transport(refused(404), refused(404, code="voice_not_found"))
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.synthesize(ROMANIAN))

    assert [c["path"] for c in transport.calls] == [TIMED_PATH, PLAIN_PATH]
    assert excinfo.value.http_status == 404 and excinfo.value.code == "voice_not_found"


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_a_refusal_that_is_not_about_the_endpoint_does_not_fall_back(monkeypatch, status):
    transport = Transport(refused(status, code="quota_exceeded"))
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.synthesize(ROMANIAN))

    assert len(transport.calls) == 1
    assert excinfo.value.http_status == status


def test_a_timed_request_that_got_no_answer_is_not_sent_again_anywhere(monkeypatch):
    """The silence may be a served, billed narration: neither endpoint is asked again."""
    transport = Transport(
        MediaProviderError("api.elevenlabs.io did not answer", unanswered=True),
        (None, mp3_bytes(10), "audio/mpeg"),
    )
    monkeypatch.setattr(elevenlabs, "request", transport)
    adapter = ElevenLabsTTSAdapter("key", voice_id="v1", model="test-model")

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.synthesize(ROMANIAN))
    assert len(transport.calls) == 1


def test_a_503_on_the_timed_endpoint_is_retried_there_not_on_the_plain_one(monkeypatch):
    transport, result = speak(monkeypatch, refused(503), timed_answer(mp3_bytes(120)))

    assert [c["path"] for c in transport.calls] == [TIMED_PATH, TIMED_PATH]
    assert result.word_timings == expected_words(ROMANIAN)


def test_a_broken_normalized_alignment_does_not_cost_the_words_their_clock(monkeypatch):
    _, result = speak(monkeypatch, timed_answer(mp3_bytes(120), normalized={"characters": "oops"}))

    assert result.word_timings == expected_words(ROMANIAN)
    assert result.raw_response["alignment"] == alignment_for(ROMANIAN)
    assert "normalized_alignment" not in result.raw_response
    assert result.raw_response["alignment_problem"].startswith("normalized_alignment")
