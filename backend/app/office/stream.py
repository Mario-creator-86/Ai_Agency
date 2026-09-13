"""The headquarters rendered live in Unreal Engine, relayed to the office page.

Unreal streams the scene over Pixel Streaming: its video travels peer to peer (WebRTC), but the
peers first meet on Epic's signalling server. The page may only talk to its own origin (its
Content-Security-Policy allows ``connect-src 'self'``), so the backend relays that signalling
WebSocket, message for message, to the address in configuration
(``STUDIO_OFFICE_STREAM_SIGNALLING_URL``). Unset or unreachable, the relay closes and the page
keeps its own renderer; nothing is shown in the stream's place.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import websockets
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)

RELAY_PATH = "/api/v1/office/stream/signalling"
OPEN_TIMEOUT_S = 5.0


def signalling_target(settings: Any) -> str | None:
    """The configured signalling address, or None when unset or not a ws/wss URL."""
    url = (getattr(settings, "office_stream_signalling_url", None) or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.netloc:
        return None
    return url


def stream_status(settings: Any) -> dict[str, Any]:
    """Whether the page should try the live stream at all."""
    return {"available": signalling_target(settings) is not None, "relay": RELAY_PATH}


def register_stream_gateway(
    app: FastAPI, *, connect: Callable[..., Any] = websockets.connect
) -> None:
    """Registers the relay; ``connect`` opens the upstream connection (replaced in tests)."""

    @app.websocket(RELAY_PATH)
    async def office_stream_signalling(
        websocket: WebSocket,
        token: str | None = Query(default=None),
    ) -> None:
        settings = app.state.settings
        expected = settings.owner_token.get_secret_value()
        if token is None or not secrets.compare_digest(token.encode(), expected.encode()):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
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
        await websocket.accept()
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
