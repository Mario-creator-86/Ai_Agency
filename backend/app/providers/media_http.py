"""Shared HTTPS plumbing for the media provider adapters.

Every adapter here talks to a documented vendor endpoint over TLS and returns what came back.
The rules are the same as everywhere else in the studio: a request that fails raises, a response
that is not what the contract promised raises, and nothing invents a plausible substitute. An
adapter that quietly produced a fallback asset would put a file into the pipeline that QC and the
publishing gate would then reason about as if a provider had made it.
"""

from __future__ import annotations

import http.client
import json
import struct
from typing import Any
from urllib.parse import urlsplit


class MediaProviderError(RuntimeError):
    """The provider did not return a usable result, so the caller must not continue."""


class MediaProviderNotConfigured(MediaProviderError):
    """Credentials for this provider are absent, so it cannot be called at all."""


#: A generated still or a narration segment is large; a short is not. These caps stop a
#: mistaken endpoint from streaming an unbounded body into memory.
MAX_MEDIA_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024


def request(
    host: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None = None,
    *,
    timeout: float = 120,
    expect_json: bool = True,
) -> tuple[Any, bytes, str]:
    """Make one HTTPS request and return (parsed json | None, raw body, content type).

    Only HTTPS, only the host named by the adapter, and a hard cap on the response size. A
    non-200 status raises rather than returning an empty result that a caller might store.
    """
    connection = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        limit = MAX_JSON_BYTES if expect_json else MAX_MEDIA_BYTES
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise MediaProviderError(f"{host} returned more data than the adapter accepts")
        if response.status != 200:
            # The provider's own error text is not echoed: it can carry request details, and
            # the Owner needs the status and the fact that nothing was stored.
            raise MediaProviderError(f"{host} refused the request (HTTP {response.status})")
        content_type = response.headers.get_content_type()
        if not expect_json:
            return None, payload, content_type
        try:
            return json.loads(payload), payload, content_type
        except json.JSONDecodeError as exc:
            raise MediaProviderError(f"{host} returned a malformed response") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise MediaProviderError(f"{host} could not be reached") from exc
    finally:
        connection.close()


def host_of(base_url: str, default: str) -> str:
    parsed = urlsplit(base_url or "")
    if parsed.scheme and parsed.scheme != "https":
        raise MediaProviderError("Media providers are only called over HTTPS")
    return parsed.hostname or default


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Read width and height out of a PNG header.

    Measured from the bytes that arrived, never taken from what was requested: a provider that
    returns a different size than asked for must not be recorded as having honoured the request.
    """
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise MediaProviderError("The provider did not return a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise MediaProviderError("The returned image has implausible dimensions")
    return int(width), int(height)


def mp3_duration_seconds(data: bytes) -> float:
    """Estimate an MP3's duration by walking its frame headers.

    Constant-bitrate MP3 has no duration field, so the only honest way to know how long the
    audio is, is to count its frames. The alternative — assuming the length the text "should"
    take — would put a number into the render job that nothing measured.
    """
    bitrates = [
        0,
        32,
        40,
        48,
        56,
        64,
        80,
        96,
        112,
        128,
        160,
        192,
        224,
        256,
        320,
        0,
    ]  # MPEG-1 Layer III, kbps
    rates = {0: 44100, 1: 48000, 2: 32000}
    index = 0
    duration = 0.0
    frames = 0
    limit = len(data) - 4

    # Skip an ID3v2 tag if present; its size is a 28-bit synchsafe integer.
    if data[:3] == b"ID3" and len(data) > 10:
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        index = 10 + size

    while index < limit and frames < 200_000:
        if data[index] != 0xFF or (data[index + 1] & 0xE0) != 0xE0:
            index += 1
            continue
        header = data[index : index + 4]
        version_bits = (header[1] >> 3) & 0x03
        layer_bits = (header[1] >> 1) & 0x03
        bitrate_index = (header[2] >> 4) & 0x0F
        rate_index = (header[2] >> 2) & 0x03
        padding = (header[2] >> 1) & 0x01
        if version_bits != 0x03 or layer_bits != 0x01 or rate_index == 0x03:
            index += 1
            continue
        bitrate = bitrates[bitrate_index] * 1000
        sample_rate = rates[rate_index]
        if not bitrate:
            index += 1
            continue
        frame_length = int(144 * bitrate / sample_rate) + padding
        if frame_length <= 4:
            index += 1
            continue
        duration += 1152 / sample_rate
        frames += 1
        index += frame_length

    if not frames:
        raise MediaProviderError("The provider did not return decodable MP3 audio")
    return round(duration, 3)


def wav_duration_seconds(data: bytes) -> float:
    """Read a RIFF/WAVE header and compute the duration from its own fields."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise MediaProviderError("The provider did not return a WAV file")
    index = 12
    sample_rate = channels = bits = 0
    while index + 8 <= len(data):
        chunk_id = data[index : index + 4]
        (chunk_size,) = struct.unpack("<I", data[index + 4 : index + 8])
        payload = data[index + 8 : index + 8 + chunk_size]
        if chunk_id == b"fmt " and len(payload) >= 16:
            channels, sample_rate = struct.unpack("<HI", payload[2:8])
            (bits,) = struct.unpack("<H", payload[14:16])
        elif chunk_id == b"data":
            if not (sample_rate and channels and bits):
                raise MediaProviderError("The WAV file has no readable format header")
            frame_size = channels * (bits // 8)
            if frame_size <= 0:
                raise MediaProviderError("The WAV file declares an unusable frame size")
            return round(len(payload) / frame_size / sample_rate, 3)
        index += 8 + chunk_size + (chunk_size & 1)
    raise MediaProviderError("The WAV file contains no audio data")
