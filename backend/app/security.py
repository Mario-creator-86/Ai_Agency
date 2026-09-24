import asyncio
import json
import logging
import secrets
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import HTTPException, Request, Security, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def require_owner(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> None:
    expected = request.app.state.settings.owner_token.get_secret_value()
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="Owner authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------------------------
# THE OWNER'S KEY ON A WEBSOCKET (2026-09-25). A browser cannot set a header on a WebSocket, so
# the page used to put the key in the socket's query string. A URL is printed by the browser when
# the socket fails and reaches proxy and server access logs. The page now sends the key as the
# socket's first message, ``{"type": "auth", "token": "<key>"}``, once the backend says it can
# (GET /office/stream ``auth``). The key is compared in constant time, never logged, never echoed
# and never forwarded; a socket that does not say it within SOCKET_AUTH_TIMEOUT_S is closed.
# ---------------------------------------------------------------------------------------------

SOCKET_AUTH = "first_message"
SOCKET_AUTH_TIMEOUT_S = 5.0
SOCKET_AUTH_MAX_CHARS = 4096

_socket_log = logging.getLogger("studio.socket_auth")


def owner_key_matches(candidate: str | None, expected: str) -> bool:
    """Whether a key the page sent is the Owner's, in constant time; an empty key never is."""
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate.encode(), expected.encode())


def _first_message_key(message: Mapping[str, Any]) -> str | None:
    """The key in an ``auth`` message, or None for anything else (bytes, not JSON, too long)."""
    if message.get("type") != "websocket.receive":
        return None
    text = message.get("text")
    if not isinstance(text, str) or len(text) > SOCKET_AUTH_MAX_CHARS:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None
    token = data.get("token")
    return token if isinstance(token, str) else None


async def socket_first_message_auth(
    websocket: WebSocket, expected: str, *, timeout_s: float = SOCKET_AUTH_TIMEOUT_S
) -> bool:
    """On an accepted socket, waits for the key as its first message.

    Returns True when it is the Owner's. Otherwise closes the socket with 1008 and returns False;
    only the reason is logged (``timeout``, ``malformed`` or ``wrong``), never what was sent.
    """
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=timeout_s)
    except TimeoutError:
        reason = "timeout"
    else:
        if message.get("type") == "websocket.disconnect":
            return False
        key = _first_message_key(message)
        if key is not None and owner_key_matches(key, expected):
            return True
        reason = "malformed" if key is None else "wrong"
    _socket_log.info("owner_socket_refused", extra={"reason": reason, "path": websocket.url.path})
    try:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except RuntimeError:
        pass  # the page had already gone
    return False
