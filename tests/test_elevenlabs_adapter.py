"""What the narration request carries: continuity, normalisation, pronunciation, the voice.

Each scene used to be voiced as an isolated request: the payload carried the text, the model
and two fixed voice settings, so the intonation fell at the end of every scene as if the film
ended there (Q3), Flash read numbers digit by digit (Q13), the binding's pronunciation
dictionary never reached the vendor, and the bible's voice settings were sent with whatever
else the binding happened to hold.

Documented request fields (ElevenLabs "Create speech with timing", read 2026-10-02):
``previous_text`` / ``next_text`` ("to improve the speech's continuity when concatenating
together multiple generations"), ``previous_request_ids`` (at most three),
``apply_text_normalization`` (auto | on | off), ``pronunciation_dictionary_locators`` (at most
three ``{pronunciation_dictionary_id, version_id}``) and ``voice_settings`` (stability,
similarity_boost, style, use_speaker_boost, speed).

A narration is a purchase. A refusal of these optional fields is a 400/422: no audio was made,
nothing was billed, so they are dropped once and the request is made again without them,
never a second purchase of audio that came back.

Every vendor call here is a fake transport; nothing leaves the machine.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from app.providers import elevenlabs
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import MediaProviderError

TEXT = "Ziua începe în Kathmandu, la 1.400 de metri."


def _mp3(frames: int = 40) -> bytes:
    frame_length = int(144 * 128000 / 44100)
    return (bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * (frame_length - 4)) * frames


def _alignment(text: str) -> dict:
    characters = list(text)
    starts = [round(0.02 * i, 3) for i in range(len(characters))]
    return {
        "characters": characters,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": [round(s + 0.02, 3) for s in starts],
    }


def _answer(text: str = TEXT) -> tuple[None, bytes, str]:
    body = {
        "audio_base64": base64.b64encode(_mp3()).decode("ascii"),
        "alignment": _alignment(text),
        "normalized_alignment": _alignment(text),
    }
    return None, json.dumps(body).encode("utf-8"), "application/json"


class Transport:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, host, method, path, headers, body=None, *, timeout=120, expect_json=True):
        self.calls.append({"path": path, "body": json.loads(body) if body else None})
        if not self.responses:
            raise AssertionError("the adapter asked the vendor more times than the test allows")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _adapter(monkeypatch, *responses, model: str = "eleven_multilingual_v2"):
    transport = Transport(*responses)
    monkeypatch.setattr(elevenlabs, "request", transport)
    return transport, ElevenLabsTTSAdapter("key", voice_id="v1", model=model)


def _refused(status: int) -> MediaProviderError:
    return MediaProviderError(
        f"api.elevenlabs.io refused the request (HTTP {status})", http_status=status
    )


def test_the_neighbouring_scenes_travel_as_previous_and_next_text(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    asyncio.run(
        adapter.synthesize(
            TEXT,
            extra={"previous_text": "Scena dinainte.", "next_text": "Scena de după."},
        )
    )
    sent = transport.calls[0]["body"]
    assert sent["previous_text"] == "Scena dinainte."
    assert sent["next_text"] == "Scena de după."
    # The text bought is only this scene's words: the context is never part of it.
    assert sent["text"] == TEXT


def test_previous_request_ids_are_sent_at_most_three(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    asyncio.run(adapter.synthesize(TEXT, extra={"previous_request_ids": ["a", "b", "c", "d"]}))
    assert transport.calls[0]["body"]["previous_request_ids"] == ["b", "c", "d"]


def test_a_scene_without_neighbours_sends_no_empty_context(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    asyncio.run(adapter.synthesize(TEXT, extra={"previous_text": "", "next_text": None}))
    sent = transport.calls[0]["body"]
    assert "previous_text" not in sent and "next_text" not in sent


@pytest.mark.parametrize(
    ("model", "normalised"),
    [
        ("eleven_flash_v2_5", True),
        ("eleven_turbo_v2_5", True),
        ("eleven_multilingual_v2", False),
    ],
)
def test_flash_models_are_asked_to_spell_numbers_out(monkeypatch, model, normalised):
    transport, adapter = _adapter(monkeypatch, _answer(), model=model)
    asyncio.run(adapter.synthesize(TEXT))
    sent = transport.calls[0]["body"]
    if normalised:
        assert sent["apply_text_normalization"] == "on"
    else:
        # The large model normalises well on the vendor's own "auto"; nothing is forced.
        assert "apply_text_normalization" not in sent


def test_the_bindings_pronunciation_dictionary_is_sent_by_locator(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    adapter.pronunciation_locators = [
        {"pronunciation_dictionary_id": "dict-1", "version_id": "ver-1"},
    ]
    asyncio.run(adapter.synthesize(TEXT))
    assert transport.calls[0]["body"]["pronunciation_dictionary_locators"] == [
        {"pronunciation_dictionary_id": "dict-1", "version_id": "ver-1"}
    ]


def test_the_bindings_voice_settings_are_sent_and_only_the_documented_ones(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    adapter.voice_settings = {
        "stability": 0.35,
        "similarity_boost": 0.9,
        "style": 0.2,
        "use_speaker_boost": True,
        "pitch": 3,  # not a setting the vendor documents: never sent
    }
    asyncio.run(adapter.synthesize(TEXT, speed=1.05))
    assert transport.calls[0]["body"]["voice_settings"] == {
        "stability": 0.35,
        "similarity_boost": 0.9,
        "style": 0.2,
        "use_speaker_boost": True,
        "speed": 1.05,
    }


def test_without_a_binding_the_voice_keeps_the_studios_defaults(monkeypatch):
    transport, adapter = _adapter(monkeypatch, _answer())
    asyncio.run(adapter.synthesize(TEXT))
    assert transport.calls[0]["body"]["voice_settings"] == {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "speed": 1.0,
    }


@pytest.mark.parametrize("status", [400, 422])
def test_a_refusal_of_the_optional_fields_drops_them_once_and_buys_once(monkeypatch, status):
    transport, adapter = _adapter(monkeypatch, _refused(status), _answer(), _answer())
    adapter.pronunciation_locators = [{"pronunciation_dictionary_id": "d", "version_id": "v"}]
    said = asyncio.run(
        adapter.synthesize(TEXT, extra={"previous_text": "Înainte.", "next_text": "După."})
    )
    first, second = (call["body"] for call in transport.calls)
    assert "previous_text" in first and "pronunciation_dictionary_locators" in first
    for field in ("previous_text", "next_text", "pronunciation_dictionary_locators"):
        assert field not in second
    # Both asked the timed endpoint: the refusal was about the fields, not the endpoint.
    assert all("/with-timestamps" in call["path"] for call in transport.calls)
    assert said.raw_response["options_dropped"]["http_status"] == status
    assert said.audio_bytes == _mp3()
    # Once dropped, this voice no longer offers what the vendor refused: no second refusal.
    asyncio.run(adapter.synthesize(TEXT, extra={"previous_text": "Înainte."}))
    assert "previous_text" not in transport.calls[2]["body"]
    assert len(transport.calls) == 3


def test_a_refusal_without_optional_fields_is_not_retried_with_the_same_body(monkeypatch):
    # Nothing optional to drop: the existing contract fallback (the plain endpoint, once).
    transport, adapter = _adapter(
        monkeypatch, _refused(422), (None, _mp3(), "audio/mpeg"), model="eleven_v3"
    )
    asyncio.run(adapter.synthesize(TEXT))
    assert [("/with-timestamps" in c["path"]) for c in transport.calls] == [True, False]


def test_a_server_error_after_the_optional_fields_is_never_sent_again(monkeypatch):
    # A 500 may have been served and billed: nothing is dropped and nothing is sent again.
    error = MediaProviderError("refused (HTTP 500)", http_status=500, unanswered=True)
    transport, adapter = _adapter(monkeypatch, error)
    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.synthesize(TEXT, extra={"previous_text": "Înainte."}))
    assert len(transport.calls) == 1


def test_the_request_settings_are_part_of_what_the_narration_is():
    from app.media.assembler import narration_key

    flash = ElevenLabsTTSAdapter("key", voice_id="v1", model="eleven_flash_v2_5")
    other = ElevenLabsTTSAdapter("key", voice_id="v1", model="eleven_flash_v2_5")
    other.pronunciation_locators = [{"pronunciation_dictionary_id": "d", "version_id": "v"}]
    assert narration_key(TEXT, flash) != narration_key(TEXT, other)
    # The neighbours shape the recording, so they are part of its identity too.
    assert narration_key(TEXT, flash) != narration_key(
        TEXT, flash, context={"previous_text": "Înainte.", "next_text": None}
    )
    assert narration_key(TEXT, flash, context={"previous_text": "", "next_text": None}) == (
        narration_key(TEXT, flash)
    )


def test_the_factory_reads_pronunciation_locators_from_the_character_binding():
    from app.media.factory import pronunciation_locators

    assert pronunciation_locators(
        {
            "pronunciation_rules": [
                {"term": "Kathmandu", "hint": "Kat-man-du"},  # a hint for the voice artist
                {"pronunciation_dictionary_id": "d1", "version_id": "v1"},
                {"pronunciation_dictionary_id": "d2"},  # no version: not a locator
            ]
        }
    ) == [{"pronunciation_dictionary_id": "d1", "version_id": "v1"}]
    assert pronunciation_locators({}) == []
    assert pronunciation_locators(None) == []


class StitchingVoice:
    """A narrator that says it can use its neighbours' words, and remembers what it got."""

    PROVIDER_NAME = "TEST_STITCHING_VOICE"
    ACCEPTS_STITCHING = True
    model = "test-voice"
    voice_id = "voice-1"
    integration_id = "conn-voice"

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict | None]] = []

    async def synthesize(self, text, *, extra=None, **_kwargs):
        from test_phase5_media import AlignedVoice

        self.asked.append((text, extra))
        return await AlignedVoice(aligned=True).synthesize(text)


def test_the_render_tells_each_scene_the_words_around_it_and_keys_them(engine, tmp_path):
    from uuid import uuid4

    from app.media.assembler import assemble_video_job
    from app.media.toolchain import find_ffmpeg
    from test_motion import StubImages
    from test_phase5_media import _seeded_storyboard

    if find_ffmpeg() is None:
        pytest.skip("FFmpeg is not installed")
    sb_id, _ = _seeded_storyboard(engine, tmp_path, scenes=3)
    voice = StitchingVoice()

    def render():
        return assemble_video_job(
            engine,
            sb_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            image_adapter=StubImages(),
            tts_adapter=voice,
            environment="TEST",
        )

    render()
    said = {text: extra for text, extra in voice.asked}
    first, second, third = (f"Fixture narration segment {i}." for i in (1, 2, 3))
    assert said[first] == {"next_text": second}
    assert said[second] == {"previous_text": first, "next_text": third}
    assert said[third] == {"previous_text": second}
    # The same words in the same places are the same recordings: nothing is bought again.
    render()
    assert len(voice.asked) == 3
