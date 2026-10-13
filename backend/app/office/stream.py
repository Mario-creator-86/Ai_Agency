"""The headquarters rendered live in Unreal Engine, relayed to the office page.

Unreal streams the scene over Pixel Streaming: its video travels peer to peer (WebRTC), but the
peers first meet on Epic's signalling server. The page may only talk to its own origin (its
Content-Security-Policy allows ``connect-src 'self'``), so the backend relays that signalling
WebSocket, message for message, to the address in configuration
(``STUDIO_OFFICE_STREAM_SIGNALLING_URL``). Unset or unreachable, the relay closes and the page
keeps its own renderer; nothing is shown in the stream's place.

The Owner's key (2026-09-25) is the socket's first message, not its URL: the page sends
``{"type": "auth", "token": ...}`` when GET /office/stream says ``auth: "first_message"``. Only once
the key is right and the signalling server has answered does the relay send the page
``{"type": "relay_ready"}``, and the page's stream client then begins, as it did when the socket
opened. The key is never forwarded to the signalling server, never echoed and never logged. A key
in the query string is refused outright since 2026-10-01 (SEC-02): uvicorn logs a handshake's path
with its query, and the Windows service kept that log on disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from app.security import (
    SOCKET_AUTH,
    SOCKET_AUTH_TIMEOUT_S,
    refuse_key_in_url,
    socket_first_message_auth,
)

logger = logging.getLogger(__name__)

RELAY_PATH = "/api/v1/office/stream/signalling"
OPEN_TIMEOUT_S = 5.0
#: What the relay tells the page once the key is right and the signalling server has answered.
RELAY_READY = json.dumps({"type": "relay_ready"})

__all__ = [
    "RELAY_PATH",
    "SOCKET_AUTH_TIMEOUT_S",
    "register_stream_gateway",
    "signalling_target",
    "stream_status",
]


def signalling_target(settings: Any) -> str | None:
    """The configured signalling address, or None when unset or not a ws/wss URL."""
    url = (getattr(settings, "office_stream_signalling_url", None) or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.netloc:
        return None
    return url


def stream_status(settings: Any) -> dict[str, Any]:
    """Whether the page should try the live stream at all, and how its sockets say the key."""
    return {
        "available": signalling_target(settings) is not None,
        "relay": RELAY_PATH,
        "auth": SOCKET_AUTH,
    }


def register_stream_gateway(
    app: FastAPI,
    *,
    connect: Callable[..., Any] = websockets.connect,
    auth_timeout_s: float = SOCKET_AUTH_TIMEOUT_S,
) -> None:
    """Registers the relay; ``connect`` opens the upstream connection (replaced in tests)."""

    @app.websocket(RELAY_PATH)
    async def office_stream_signalling(websocket: WebSocket) -> None:
        # a key in the URL is refused before the handshake, whatever it is (SEC-02)
        if await refuse_key_in_url(websocket):
            return
        settings = app.state.settings
        expected = settings.owner_token.get_secret_value()
        await websocket.accept()
        if not await socket_first_message_auth(websocket, expected, timeout_s=auth_timeout_s):
            return
        target = signalling_target(settings)
        if target is None:
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
            return
        try:
            upstream = await connect(target, open_timeout=OPEN_TIMEOUT_S, max_size=None)
        except (OSError, TimeoutError, websockets.WebSocketException) as err:
            logger.info("office_stream_unreachable", extra={"error": type(err).__name__})
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
            return
        # the page's stream client starts only now, as it did when the socket opened
        await websocket.send_text(RELAY_READY)
        try:
            await _relay(websocket, upstream)
        finally:
            await upstream.close()


async def _relay(page: WebSocket, upstream: Any) -> None:
    """Copies messages both ways until either side goes away, then closes the other."""

    async def page_to_upstream() -> None:
        while True:
            message = await page.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("text")
            if data is None:
                data = message.get("bytes")
            if data is not None:
                await upstream.send(data)

    async def upstream_to_page() -> None:
        async for data in upstream:
            if isinstance(data, bytes):
                await page.send_bytes(data)
            else:
                await page.send_text(data)

    tasks = [asyncio.create_task(page_to_upstream()), asyncio.create_task(upstream_to_page())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        err = task.exception()
        if err is not None and not isinstance(
            err, (WebSocketDisconnect, websockets.ConnectionClosed, RuntimeError)
        ):
            logger.warning("office_stream_relay_failed", extra={"error": type(err).__name__})
    try:
        await page.close()
    except RuntimeError:
        pass  # the page had already gone
