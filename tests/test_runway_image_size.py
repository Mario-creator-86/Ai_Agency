"""A picture sent inside a Runway request always fits the vendor's limit.

The Owner's shooting sheet, 2026-10-03: the stills of scenes 2 and 3 were refused by Runway with
"referenceImages[0].uri: Data URI is too large: 8.6MB exceeds the 5MB limit". The film's first
approved still (a 2K PNG, 1530x2720) went to the vendor as it was, as the light and palette
reference of the next scenes. The first frame of a motion shot was already re-encoded by the
assembler; the reference was not. Now the adapter fits every picture it sends: one that is
small enough goes as it is; a larger one is re-encoded to JPEG, smaller if it must be, keeping
its proportions; one that cannot be read is refused here, before anything is sent or paid.

The vendor is faked at its transport; no socket is opened.
"""

from __future__ import annotations

import asyncio
import base64
import json

import cv2
import numpy as np
import pytest
from app.providers import runway
from app.providers.media_http import MediaProviderError
from test_media_providers import _runway, png_bytes


def big_png(width: int = 1530, height: int = 2720) -> bytes:
    """A 2K still a generator could return: detail everywhere, so PNG cannot shrink it."""
    rng = np.random.default_rng(7)
    picture = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", picture)
    assert ok
    return encoded.tobytes()


def sent_reference(transport) -> str:
    (call,) = transport.calls[:1]
    return json.loads(call["body"])["referenceImages"][0]["uri"]


def test_a_2k_still_as_reference_is_sent_under_the_limit_with_its_proportions():
    reference = big_png()
    assert len(base64.b64encode(reference)) > 5_000_000, "the fixture must reproduce the refusal"

    uri = runway._image_data_uri(reference, "reference image")

    assert len(uri) <= runway.DATA_URI_TARGET_CHARS
    assert uri.startswith("data:image/jpeg;base64,")
    picture = cv2.imdecode(
        np.frombuffer(base64.b64decode(uri.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR
    )
    height, width = picture.shape[:2]
    assert abs(width / height - 1530 / 2720) < 0.01


def test_the_still_request_carries_the_fitted_reference(monkeypatch):
    adapter, transport = _runway(monkeypatch, png_bytes(1080, 1920))

    asyncio.run(
        adapter.generate_image(
            "The same valley, later in the day",
            width=1080,
            height=1920,
            extra={"reference_image": {"bytes": big_png(), "mime_type": "image/png"}},
        )
    )

    uri = sent_reference(transport)
    assert len(uri) <= runway.DATA_URI_TARGET_CHARS
    assert uri.startswith("data:image/jpeg;base64,")


def test_a_picture_that_already_fits_is_sent_as_it_is():
    small = png_bytes(64, 96)

    uri = runway._image_data_uri(small, "reference image")

    assert uri == "data:image/png;base64," + base64.b64encode(small).decode("ascii")


def test_a_picture_too_large_to_send_and_unreadable_is_refused_before_any_call(monkeypatch):
    adapter, transport = _runway(monkeypatch, png_bytes(8, 8))
    # A PNG signature and 6 MB that are not a picture: nothing can make it smaller.
    blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * 6_000_000

    with pytest.raises(MediaProviderError):
        asyncio.run(
            adapter.generate_image(
                "The same valley",
                extra={"reference_image": {"bytes": blob, "mime_type": "image/png"}},
            )
        )

    assert transport.calls == []
