"""The studio's kept frame of the live Unreal headquarters, for a first visit's title (W24).

Until now only a browser that had already watched the stream kept a real frame of the building
(IndexedDB, stream_keep.js), so a stranger's first visit opened on the page renderer's title. While
the Owner's signed-in page plays the stream it now sends the newest kept frame to the backend,
rarely. The backend keeps exactly one, the newest, outside the database; the Owner's key is needed
to write it (a header, never a URL). A public read-only GET serves it with its capture time, since
the title stands before the sign-in and shows only the building. No such frame is ever invented:
nothing kept is a 204 with no body (a stranger's console stays clean), and the page then stands on
its plates; an older studio without the route answers 404, which means the plates too.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.office import kept_frame as kf
from app.office.kept_frame import (
    KEPT_FRAME_MAX_BYTES,
    KEPT_FRAME_PATH,
    create_kept_frame_router,
    kept_frame_dir,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

TOKEN = "owner-token-for-the-kept-frame-tests-0123456789"
URL = "/api/v1" + KEPT_FRAME_PATH


def chunk(fourcc: bytes, payload: bytes) -> bytes:
    """One RIFF chunk, padded to an even length."""
    return (
        fourcc + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")
    )


def riff(*chunks: bytes) -> bytes:
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def vp8l(width: int = 64, height: int = 36, payload_len: int = 64, fill: bytes = b"\x2f") -> bytes:
    """A VP8L chunk's payload: the signature, the size (14 bits each, minus one), version 0."""
    bits = (width - 1) | ((height - 1) << 14)
    return b"\x2f" + struct.pack("<I", bits) + fill * payload_len


def vp8(width: int = 1920, height: int = 1008, payload_len: int = 64) -> bytes:
    """A lossy VP8 key frame's payload: the frame tag, the start code, the size."""
    return (
        b"\x10\x02\x00"
        + b"\x9d\x01\x2a"
        + struct.pack("<HH", width, height)
        + b"\x00" * payload_len
    )


def vp8x(width: int, height: int, flags: int = 0x20) -> bytes:
    """A VP8X header: flags (0x20 an ICC profile, as Chrome's canvas writes), the canvas size."""
    size = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return bytes([flags, 0, 0, 0]) + size


def webp(payload_len: int = 64, fill: bytes = b"\x2f") -> bytes:
    """A whole lossless WebP file: RIFF header, WEBP, one VP8L chunk."""
    return riff(chunk(b"VP8L", vp8l(payload_len=payload_len, fill=fill)))


def chrome_frame() -> bytes:
    """The shape of the frame the Owner's page sends (canvas.toBlob WebP): VP8X, ICCP, VP8."""
    return riff(
        chunk(b"VP8X", vp8x(1920, 1008)), chunk(b"ICCP", b"\x00" * 456), chunk(b"VP8 ", vp8())
    )


def make(tmp_path: Path) -> tuple[TestClient, Path]:
    folder = tmp_path / "office"
    app = FastAPI()
    app.state.settings = SimpleNamespace(owner_token=SecretStr(TOKEN), office_kept_frame_dir=folder)
    app.include_router(create_kept_frame_router(), prefix="/api/v1")
    return TestClient(app), folder


def now_ms() -> int:
    return int(time.time() * 1000)


def post(client: TestClient, body: bytes, at: int | None, **headers: str):
    sent = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "image/webp"}
    if at is not None:
        sent["X-Captured-At"] = str(at)
    sent.update(headers)
    return client.post(URL, content=body, headers=sent)


def test_nothing_kept_is_a_204_so_the_title_keeps_its_plates(tmp_path):
    client, _ = make(tmp_path)
    response = client.get(URL)
    assert response.status_code == 204
    assert response.content == b""
    assert "x-captured-at" not in response.headers


def test_the_owner_keeps_a_frame_and_anyone_reads_it_back_with_its_time(tmp_path):
    client, folder = make(tmp_path)
    at = now_ms() - 5000
    frame = webp(300)
    stored = post(client, frame, at)
    assert stored.status_code == 201
    assert stored.json() == {"stored": True, "at": at}
    read = client.get(URL)  # no key: the title stands before the sign-in
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/webp"
    assert read.headers["x-captured-at"] == str(at)
    assert read.content == frame
    assert [p.name for p in folder.iterdir()] == [f"kept-{at}.webp"]


def test_writing_needs_the_owners_key_in_a_header_never_in_the_url(tmp_path):
    client, folder = make(tmp_path)
    at = now_ms()
    frame = webp()
    headers = {"Content-Type": "image/webp", "X-Captured-At": str(at)}
    assert client.post(URL, content=frame, headers=headers).status_code == 401
    assert client.post(f"{URL}?token={TOKEN}", content=frame, headers=headers).status_code == 401
    wrong = {**headers, "Authorization": "Bearer not-the-owner"}
    assert client.post(URL, content=frame, headers=wrong).status_code == 401
    assert not folder.exists() or not any(folder.iterdir())
    assert client.get(URL).status_code == 204


def test_exactly_one_frame_is_kept_the_newest(tmp_path):
    client, folder = make(tmp_path)
    t = now_ms()
    assert post(client, webp(10, b"a"), t - 60000).status_code == 201
    assert post(client, webp(10, b"b"), t - 1000).status_code == 201
    older = post(client, webp(10, b"c"), t - 30000)
    # a second tab's older frame arriving late does not replace the newer one
    assert older.status_code == 200
    assert older.json() == {"stored": False, "at": t - 1000}
    read = client.get(URL)
    assert read.headers["x-captured-at"] == str(t - 1000)
    assert read.content == webp(10, b"b")
    assert [p.name for p in folder.iterdir()] == [f"kept-{t - 1000}.webp"]


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("image/png", webp()),
        ("image/webp", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
        ("image/webp", b"RIFF" + struct.pack("<I", 4) + b"WAVE"),
        ("image/webp", webp()[:-5]),  # the RIFF size says more than was sent
        ("image/webp", b""),
    ],
)
def test_only_a_whole_webp_is_kept(tmp_path, content_type, body):
    client, folder = make(tmp_path)
    response = post(client, body, now_ms(), **{"Content-Type": content_type})
    assert response.status_code == 415
    assert client.get(URL).status_code == 204


def test_the_frame_the_owners_page_sends_is_kept(tmp_path):
    client, _ = make(tmp_path)
    frame = chrome_frame()
    assert post(client, frame, now_ms()).status_code == 201
    assert client.get(URL).content == frame


@pytest.mark.parametrize(
    "body",
    [
        # anything carried after the picture, in a chunk no still frame has
        riff(chunk(b"VP8L", vp8l()), chunk(b"HTML", b"<script>alert(1)</script>")),
        # metadata chunks: the canvas never writes them, and they can carry any text
        riff(chunk(b"VP8X", vp8x(64, 36, 0x08)), chunk(b"VP8L", vp8l()), chunk(b"EXIF", b"x" * 40)),
        riff(chunk(b"VP8X", vp8x(64, 36, 0x04)), chunk(b"VP8L", vp8l()), chunk(b"XMP ", b"x" * 40)),
        # an animation is not a frame
        riff(chunk(b"VP8X", vp8x(64, 36, 0x02)), chunk(b"ANIM", b"\x00" * 6)),
        # two pictures in one file
        riff(chunk(b"VP8L", vp8l()), chunk(b"VP8L", vp8l())),
        # a picture chunk that is not one: no VP8L signature, no VP8 key frame start code
        riff(chunk(b"VP8L", b"\x00" + vp8l()[1:])),
        riff(chunk(b"VP8 ", vp8()[:3] + b"abc" + vp8()[6:])),
        # sizes no frame has: nothing, or larger than any screen the page keeps
        riff(chunk(b"VP8 ", vp8(0, 1008))),
        riff(chunk(b"VP8L", vp8l(8000, 36))),
        # a canvas that is not the picture's
        riff(chunk(b"VP8X", vp8x(64, 64)), chunk(b"VP8L", vp8l(64, 36))),
        # a chunk that says it is longer than the file, and bytes after the last chunk
        riff(b"VP8L" + struct.pack("<I", 9999) + vp8l()),
        riff(chunk(b"VP8L", vp8l())) + b"tail",
        # no picture at all
        riff(chunk(b"VP8X", vp8x(64, 36)), chunk(b"ICCP", b"\x00" * 16)),
    ],
)
def test_only_a_still_picture_is_kept_nothing_carried_beside_it(tmp_path, body):
    # W25: a key holder cannot park arbitrary bytes behind a WebP header for every stranger
    client, _ = make(tmp_path)
    assert post(client, body, now_ms()).status_code == 415
    assert client.get(URL).status_code == 204


def test_a_frame_over_the_cap_is_refused(tmp_path):
    client, _ = make(tmp_path)
    big = webp(KEPT_FRAME_MAX_BYTES)
    assert len(big) > KEPT_FRAME_MAX_BYTES
    assert post(client, big, now_ms()).status_code == 413
    assert client.get(URL).status_code == 204


@pytest.mark.parametrize(
    "at",
    [None, "soon", "-5", "12.5", str(now_ms() + 10 * 60000), str(now_ms() - 25 * 3600 * 1000)],
)
def test_the_capture_time_is_a_real_recent_moment(tmp_path, at):
    client, _ = make(tmp_path)
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "image/webp"}
    if at is not None:
        headers["X-Captured-At"] = at
    assert client.post(URL, content=webp(), headers=headers).status_code == 422
    assert client.get(URL).status_code == 204


def test_a_failed_write_leaves_the_kept_frame_whole(tmp_path, monkeypatch):
    client, folder = make(tmp_path)
    t = now_ms()
    assert post(client, webp(10, b"a"), t - 5000).status_code == 201

    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(kf.os, "replace", refuse)
    with pytest.raises(OSError):
        post(client, webp(10, b"b"), t)
    monkeypatch.undo()
    read = client.get(URL)
    assert read.status_code == 200
    assert read.content == webp(10, b"a")
    # no half-written file is left beside it
    assert [p.name for p in folder.iterdir()] == [f"kept-{t - 5000}.webp"]


def test_the_frame_lives_beside_the_database_by_default(tmp_path):
    settings = SimpleNamespace(
        office_kept_frame_dir=None,
        database_url=f"sqlite:///{(tmp_path / 'studio.db').as_posix()}",
    )
    assert kept_frame_dir(settings) == tmp_path / "office"
    chosen = SimpleNamespace(office_kept_frame_dir=tmp_path / "x", database_url="sqlite:///y.db")
    assert kept_frame_dir(chosen) == tmp_path / "x"


def test_the_studio_serves_the_kept_frame_publicly_and_writes_it_only_for_the_owner(
    client, settings
):
    at = now_ms() - 1000
    frame = webp(50)
    assert client.get(URL).status_code == 204
    refused = client.post(
        URL, content=frame, headers={"Content-Type": "image/webp", "X-Captured-At": str(at)}
    )
    assert refused.status_code == 401
    stored = client.post(
        URL,
        content=frame,
        headers={
            "Authorization": f"Bearer {settings.owner_token.get_secret_value()}",
            "Content-Type": "image/webp",
            "X-Captured-At": str(at),
        },
    )
    assert stored.status_code == 201
    read = client.get(URL)
    assert read.status_code == 200
    assert read.content == frame
    assert read.headers["cache-control"] == "no-store"
    assert read.headers["x-content-type-options"] == "nosniff"
