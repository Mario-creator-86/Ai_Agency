"""ElevenLabs text-to-speech adapter.

Uses the documented REST API at https://elevenlabs.io/docs/api-reference/introduction:

  GET  /v1/models                  -> models returned for this key
  GET  /v2/voices                  -> paginated voices this key can use
  POST /v1/text-to-speech/{voice_id}/with-timestamps -> narration audio with its own clock
  POST /v1/text-to-speech/{voice_id} -> narration audio only (the fallback)

The duration attached to a result is measured from the audio that came back, never derived from
the length of the text. A render job records how long each segment is, and the assembler cuts
video to it; a guessed number there would desynchronise the picture from the voice while
appearing to be a measurement.

Narration is asked for on /with-timestamps. Its documented answer is JSON: ``audio_base64`` and
two character alignments, ``alignment`` (the text sent) and ``normalized_alignment`` (the text
as spoken, numbers spelled out), each ``{characters, character_start_times_seconds,
character_end_times_seconds}``. It is billed per character like the plain endpoint (the API
pricing page lists no surcharge for timing). The captions are timed from it word by word;
without it they fall back to each word's share of the line.

A narration is a purchase. The plain endpoint is tried only when the timed one is refused as a
shape the vendor does not serve (404, 405, 422: no audio was made, nothing was billed), and only
once. Once audio has come back it is never asked for again: a timing that is malformed, about
other words or longer than the audio is dropped with a warning and the audio is kept.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import math
import time
import unicodedata
from typing import Any
from urllib.parse import quote, urlencode

from app.economy.prices import PriceLookup, tts_cost_vr
from app.providers.media_base import TTSProvider, TTSResult
from app.providers.media_http import (
    MediaProviderError,
    MediaProviderNotConfigured,
    mp3_duration_seconds,
    request,
    retrying,
)
from app.wording import settings_place

HOST = "api.elevenlabs.io"

logger = logging.getLogger(__name__)

#: The documented default, named so the result's `format` and `sample_rate` are what was
#: asked for rather than whatever the vendor defaults to that day.
OUTPUT_FORMAT = "mp3_44100_128"
#: The end of one paid narration request as a whole (`media_http.request`'s ``total_seconds``,
#: REDO_HANG 2026-10-03): a socket timeout bounds one read, never an answer that keeps
#: trickling, and the narration is bought inside the sheet's assemble step under the film's
#: purchase lease, which a live holder keeps renewing. Past it the request is unanswered: it
#: may have been billed, so it is never sent again.
NARRATION_TOTAL_SECONDS = 180
#: Refusals that mean "this endpoint shape is not served" (a contract change): no audio was
#: made, so asking the plain endpoint once buys nothing twice.
CONTRACT_REFUSALS = frozenset({404, 405, 422})
#: Refusals of a request's *fields* (a validation answer): no audio was made and nothing was
#: billed, so the optional fields below are dropped once and the same endpoint asked again.
FIELD_REFUSALS = frozenset({400, 422})
#: The documented voice settings ("Create speech with timing", read 2026-10-02). Anything
#: else a binding holds is never sent: an unknown key is a refusal waiting to happen.
VOICE_SETTING_KEYS = ("stability", "similarity_boost", "style", "use_speaker_boost")
#: The studio's defaults when the bible's binding sets nothing.
DEFAULT_VOICE_SETTINGS: dict[str, Any] = {"stability": 0.5, "similarity_boost": 0.75}
#: Fields that improve a recording but are not needed for one. Request stitching
#: (previous_text / next_text / previous_request_ids / next_request_ids) keeps the intonation
#: running across scenes instead of falling at every cut (audit Q3); text normalisation and a
#: pronunciation dictionary make numbers and names read right (Q13).
OPTIONAL_FIELDS = (
    "previous_text",
    "next_text",
    "previous_request_ids",
    "next_request_ids",
    "apply_text_normalization",
    "pronunciation_dictionary_locators",
)
#: The vendor takes at most three request ids and three dictionary locators per request.
MAX_REQUEST_IDS = 3
MAX_LOCATORS = 3
#: How much neighbouring text is sent as context: the sentence before and after, never the
#: whole script.
MAX_CONTEXT_CHARACTERS = 400
#: The small, fast models. ElevenLabs documents that Flash v2.5 reads "$1,000,000" as "one
#: thousand thousand dollars" on its own: these are asked to normalise numbers always ("on");
#: the large models keep the vendor's "auto".
SMALL_MODEL_MARKERS = ("flash", "turbo")


def wants_text_normalisation(model: str | None) -> bool:
    """Whether this model is asked for ``apply_text_normalization: "on"``."""
    name = str(model or "").lower()
    return any(marker in name for marker in SMALL_MODEL_MARKERS)


def _context_text(value: Any, *, tail: bool) -> str | None:
    """A neighbour's words, whitespace-folded and cut to MAX_CONTEXT_CHARACTERS at a word
    boundary (its end for the text before, its start for the text after); None when empty."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) <= MAX_CONTEXT_CHARACTERS:
        return text
    if tail:
        cut = text[-MAX_CONTEXT_CHARACTERS:]
        return cut.split(" ", 1)[1] if " " in cut else cut
    cut = text[:MAX_CONTEXT_CHARACTERS]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def _request_ids(value: Any, *, last: bool) -> list[str] | None:
    """At most MAX_REQUEST_IDS ids: the latest before this request, the first after it."""
    if not isinstance(value, list | tuple):
        return None
    ids = [str(item) for item in value if isinstance(item, str) and item.strip()]
    if not ids:
        return None
    return ids[-MAX_REQUEST_IDS:] if last else ids[:MAX_REQUEST_IDS]


def checked_locators(value: Any) -> list[dict[str, str]]:
    """The documented locator shape only, at most three: {pronunciation_dictionary_id,
    version_id}, both non-empty strings."""
    found: list[dict[str, str]] = []
    for item in value if isinstance(value, list | tuple) else []:
        if not isinstance(item, dict):
            continue
        dictionary, version = item.get("pronunciation_dictionary_id"), item.get("version_id")
        if (
            isinstance(dictionary, str)
            and dictionary.strip()
            and isinstance(version, str)
            and version.strip()
        ):
            found.append({"pronunciation_dictionary_id": dictionary, "version_id": version})
    return found[:MAX_LOCATORS]


#: How far past the measured audio an alignment may end and still be about this audio. MP3
#: frames and the vendor's own clock disagree by a frame or two, never by half a second.
ALIGNMENT_SLACK_SECONDS = 0.5
ALIGNMENT_KEYS = (
    "characters",
    "character_start_times_seconds",
    "character_end_times_seconds",
)


class AlignmentProblem(ValueError):
    """The vendor's alignment cannot be trusted; the reason is kept, the timing dropped."""


def checked_alignment(alignment: Any, duration: float) -> dict[str, list[Any]]:
    """The vendor's character alignment, only its three documented lists, or AlignmentProblem.

    Trusted only when it is that shape, every time is a finite non-negative number, each
    character ends no earlier than it starts, starts never run backwards, and nothing ends
    after the audio does.
    """
    if not isinstance(alignment, dict):
        raise AlignmentProblem("the alignment is not an object")
    characters, starts, ends = (alignment.get(key) for key in ALIGNMENT_KEYS)
    if not (isinstance(characters, list) and isinstance(starts, list) and isinstance(ends, list)):
        raise AlignmentProblem("the alignment is missing one of its three lists")
    if not characters or not len(characters) == len(starts) == len(ends):
        raise AlignmentProblem("the alignment lists are empty or of different lengths")
    previous = 0.0
    for char, start, end in zip(characters, starts, ends, strict=True):
        if not isinstance(char, str):
            raise AlignmentProblem("the alignment has a character that is not text")
        for value in (start, end):
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise AlignmentProblem("the alignment has a time that is not a number")
            if not math.isfinite(value) or value < 0:
                raise AlignmentProblem("the alignment has a time that is not a real moment")
        if end < start or start < previous:
            raise AlignmentProblem("the alignment runs backwards")
        if end > duration + ALIGNMENT_SLACK_SECONDS:
            raise AlignmentProblem(
                f"the alignment ends at {end:.2f} s, after the {duration:.2f} s of audio"
            )
        previous = start
    return {
        "characters": characters,
        "character_start_times_seconds": starts,
        "character_end_times_seconds": ends,
    }


def words_of(alignment: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Each run of non-space characters as {word, start, end}: from its first character's
    start to its last character's end, the vendor's numbers as they came."""
    words: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for char, start, end in zip(*(alignment[key] for key in ALIGNMENT_KEYS), strict=True):
        if not char.strip():
            current = None
            continue
        if current is None:
            current = {"word": char, "start": float(start), "end": float(end)}
            words.append(current)
        else:
            current["word"] += char
            current["end"] = float(end)
    for word in words:
        word["word"] = unicodedata.normalize("NFC", word["word"])
    return words


def word_timings_for(narration: str, alignment: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """The words said, timed, when the alignment is about exactly these words; otherwise
    AlignmentProblem. Compared after NFC, since "ș" may arrive as s + a combining comma."""
    words = words_of(alignment)
    said = unicodedata.normalize("NFC", narration).split()
    if [w["word"] for w in words] != said:
        raise AlignmentProblem(
            f"the alignment times {len(words)} words that are not the {len(said)} words sent"
        )
    return words


class ElevenLabsTTSAdapter(TTSProvider):
    PROVIDER_NAME = "ELEVENLABS"
    ADAPTER_VERSION = "1.1.0"
    #: The assembler sends each scene's neighbours (``extra={"previous_text", "next_text"}``)
    #: only to a voice that says it can use them.
    ACCEPTS_STITCHING = True

    def __init__(
        self,
        api_key: str,
        voice_id: str | None = None,
        model: str | None = None,
        price_lookup: PriceLookup | None = None,
    ) -> None:
        if not api_key:
            raise MediaProviderNotConfigured("ElevenLabs needs an API key")
        self.api_key = api_key
        self.voice_id = voice_id or ""
        self.model = model or ""
        #: Per-character voice settings from the bible's binding; the API's defaults otherwise.
        self.voice_settings: dict[str, Any] = {}
        #: The binding's pronunciation dictionaries, as the vendor's locators. Creating a
        #: dictionary is the Owner's act in his ElevenLabs account; the studio only names it.
        self.pronunciation_locators: list[dict[str, str]] = []
        #: Optional fields the vendor refused for this voice (a 400/422 on them): never
        #: offered again by this adapter, so one refusal is not paid in time per scene.
        self.refused_fields: set[str] = set()
        #: The Owner's per-thousand-character prices (`app.economy.prices.price_lookup`).
        #: Nine live models carried `pricing {}` and narration was never costed; with a
        #: price every synthesis reports what its characters cost, and None without one.
        self.price_lookup = price_lookup

    def request_settings(self) -> dict[str, Any]:
        """What every request of this voice carries besides the words and their context: the
        documented voice settings, text normalisation for the small models, and the
        pronunciation dictionaries. Part of a narration's identity (`assembler.narration_key`):
        the same words said under other settings are another recording."""
        settings = dict(DEFAULT_VOICE_SETTINGS)
        settings.update({k: v for k, v in self.voice_settings.items() if k in VOICE_SETTING_KEYS})
        options: dict[str, Any] = {"voice_settings": settings}
        if wants_text_normalisation(self.model):
            options["apply_text_normalization"] = "on"
        locators = checked_locators(self.pronunciation_locators)
        if locators:
            options["pronunciation_dictionary_locators"] = locators
        return {k: v for k, v in options.items() if k not in self.refused_fields}

    def _headers(self, accept: str) -> dict[str, str]:
        return {"xi-api-key": self.api_key, "Accept": accept, "Content-Type": "application/json"}

    async def health_check(self) -> dict[str, Any]:
        """Ask the API who this key is. Reachability is reported, never assumed."""
        try:
            data, _, _ = await asyncio.to_thread(
                retrying,
                request,
                HOST,
                "GET",
                "/v1/user",
                self._headers("application/json"),
                timeout=20,
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

    async def subscription(self) -> dict[str, Any]:
        """What this key's plan has used and allows, counted the way the vendor bills it."""
        data, _, _ = await asyncio.to_thread(
            retrying,
            request,
            HOST,
            "GET",
            "/v1/user/subscription",
            self._headers("application/json"),
            timeout=20,
        )
        if not isinstance(data, dict):
            raise MediaProviderError("ElevenLabs did not describe the subscription")
        return data

    async def list_models(self) -> list[dict[str, Any]]:
        data, _, _ = await asyncio.to_thread(
            retrying,
            request,
            HOST,
            "GET",
            "/v1/models",
            self._headers("application/json"),
            timeout=20,
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
                retrying,
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
                f"Nicio voce ElevenLabs aleasă; alege una în {settings_place('media')}"
            )
        if not self.model:
            raise MediaProviderNotConfigured(
                "Niciun model ElevenLabs de producție ales; alege unul în "
                f"{settings_place('media')}"
            )

        options = self.request_settings()
        fields: dict[str, Any] = {
            "text": narration,
            "model_id": self.model,
            # The API exposes no pitch control, so the adapter does not pretend to have one:
            # a pitch argument it silently dropped would read as applied.
            "voice_settings": {**options.pop("voice_settings"), "speed": speed},
            **options,
        }
        context = extra or {}
        stitched = {
            "previous_text": _context_text(context.get("previous_text"), tail=True),
            "next_text": _context_text(context.get("next_text"), tail=False),
            "previous_request_ids": _request_ids(context.get("previous_request_ids"), last=True),
            "next_request_ids": _request_ids(context.get("next_request_ids"), last=False),
        }
        fields.update(
            {
                key: value
                for key, value in stitched.items()
                if value is not None and key not in self.refused_fields
            }
        )

        voice_path = f"/v1/text-to-speech/{quote(voice, safe='')}"
        query = "?" + urlencode({"output_format": OUTPUT_FORMAT})
        timed_path = f"{voice_path}/with-timestamps{query}"
        alignments: dict[str, Any] = {}
        dropped: dict[str, Any] | None = None
        try:
            try:
                # The JSON answer carries the audio inline (base64), so it is read under the
                # media size cap, not the small one a catalogue answer gets, and parsed here.
                _, body, content_type = await self._post_timed(timed_path, fields)
            except MediaProviderError as exc:
                optional = sorted(key for key in fields if key in OPTIONAL_FIELDS)
                if exc.http_status not in FIELD_REFUSALS or not optional:
                    raise
                # A validation refusal made no audio and billed nothing. The fields that only
                # improve the recording are dropped, once, and remembered for this voice; the
                # words, the model and the voice settings are asked for again as they were.
                logger.warning(
                    "ElevenLabs refused the request with its optional fields (HTTP %s); "
                    "asking once more without %s",
                    exc.http_status,
                    ", ".join(optional),
                )
                self.refused_fields.update(optional)
                dropped = {"http_status": exc.http_status, "fields": optional}
                for key in optional:
                    fields.pop(key, None)
                _, body, content_type = await self._post_timed(timed_path, fields)
        except MediaProviderError as exc:
            if exc.http_status not in CONTRACT_REFUSALS:
                raise
            # A refused shape made no audio. The plain endpoint, once: its own refusal or
            # silence is the error, and the timed endpoint is not asked again.
            logger.warning(
                "ElevenLabs refused /with-timestamps (HTTP %s); the narration falls back to "
                "the plain endpoint and its captions to each word's share of the line",
                exc.http_status,
            )
            _, audio, content_type = await asyncio.to_thread(
                retrying,
                request,
                HOST,
                "POST",
                f"{voice_path}{query}",
                self._headers("audio/mpeg"),
                json.dumps(fields).encode("utf-8"),
                expect_json=False,
                total_seconds=NARRATION_TOTAL_SECONDS,
            )
            if not audio or "audio" not in content_type:
                raise MediaProviderError("ElevenLabs did not return audio") from None
            raw: dict[str, Any] = {
                "endpoint": "text-to-speech",
                "timestamps_refused": exc.http_status,
            }
        else:
            audio, alignments = self._timed_answer(body, content_type)
            raw = {"endpoint": "with-timestamps"}
        if dropped is not None:
            raw["options_dropped"] = dropped
        # What the recording was asked with besides its words and their neighbours.
        raw["request_options"] = {
            key: fields[key]
            for key in (
                "voice_settings",
                "apply_text_normalization",
                "pronunciation_dictionary_locators",
            )
            if key in fields
        }
        raw["stitched"] = sorted(
            key
            for key in ("previous_text", "next_text", "previous_request_ids", "next_request_ids")
            if key in fields
        )

        # Counted from the returned frames, not estimated from the words sent.
        duration = mp3_duration_seconds(audio)
        word_timings: list[dict[str, Any]] = []
        problems: list[str] = []
        for key in ("alignment", "normalized_alignment"):
            if alignments.get(key) is None:
                continue
            try:
                checked = checked_alignment(alignments[key], duration)
                if key == "alignment":
                    # The alignment of the text sent is the captions' clock. The normalized
                    # one spells numbers out, so its words are not the caption's words: it
                    # is kept for the assembler, which matches it against the words itself.
                    word_timings = word_timings_for(narration, checked)
            except AlignmentProblem as problem:
                problems.append(f"{key}: {problem}")
                continue
            raw[key] = checked
        if raw["endpoint"] == "with-timestamps" and not word_timings and not problems:
            problems.append("the answer carried no alignment of the text sent")
        if problems:
            raw["alignment_problem"] = "; ".join(problems)
            # The narration stands; only its clock is dropped. Never a second purchase.
            logger.warning(
                "ElevenLabs narration kept, %s: %s",
                "its word timing intact"
                if word_timings
                else "without its word timing (captions fall back to each word's share)",
                raw["alignment_problem"],
            )

        return TTSResult(
            audio_bytes=audio,
            format="mp3",
            duration_seconds=duration,
            sample_rate=44100,
            # From the vendor's own character clock, or none at all. An invented alignment
            # would drive subtitle timing that matches nothing.
            word_timings=word_timings,
            # The characters sent, at the Owner's price per thousand for this model — the
            # unit the vendor bills in. None when no price covers the model, never zero.
            cost_vr=tts_cost_vr(self.price_lookup, self.model, len(narration)),
            raw_response={
                "provider": self.PROVIDER_NAME,
                "model": self.model,
                "voice_id": voice,
                "content_type": content_type,
                "output_format": OUTPUT_FORMAT,
                "bytes": len(audio),
                "characters": len(narration),
                **raw,
            },
        )

    async def _post_timed(self, path: str, fields: dict[str, Any]) -> tuple[Any, bytes, str]:
        """One POST of ``fields`` to the timed endpoint, under the studio's retry policy (a
        purchase that got no answer is never sent again)."""
        return await asyncio.to_thread(
            retrying,
            request,
            HOST,
            "POST",
            path,
            self._headers("application/json"),
            json.dumps(fields).encode("utf-8"),
            expect_json=False,
            total_seconds=NARRATION_TOTAL_SECONDS,
        )

    @staticmethod
    def _timed_answer(body: bytes, content_type: str) -> tuple[bytes, dict[str, Any]]:
        """(audio, the two alignments as they came) from a /with-timestamps answer.

        Raises when there is no audio in it. Either way the request is not sent again: it
        may have been served and billed.
        """
        if "audio" in content_type and body:
            # Bare audio on the timed endpoint would be a contract change; it was billed, so
            # it is kept, without a clock.
            return body, {}
        if "json" not in content_type:
            raise MediaProviderError("ElevenLabs did not return audio")
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MediaProviderError("ElevenLabs answered without readable audio") from None
        encoded = data.get("audio_base64") if isinstance(data, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise MediaProviderError("ElevenLabs did not return audio")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise MediaProviderError("ElevenLabs returned audio that does not decode") from None
        if not audio:
            raise MediaProviderError("ElevenLabs did not return audio")
        return audio, {key: data.get(key) for key in ("alignment", "normalized_alignment")}
