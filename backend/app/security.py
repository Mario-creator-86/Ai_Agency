import asyncio
import json
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import HTTPException, Request, Security, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------------------------
# WRONG KEYS ARE SEEN (SEC-07). A wrong key used to be refused without a line anywhere, so
# repeated probing was invisible. Each one is now logged with the client's address and the path,
# never the header, and a client past REFUSALS_PER_MINUTE wrong keys in a minute is answered 429
# with Retry-After (and logged once per window as owner_auth_throttled). The right key still
# passes from the same address: on the Owner's machine a prober and his page share 127.0.0.1,
# and a lock-out would lock him out. A missing key is not a guess and is not counted.
# ---------------------------------------------------------------------------------------------

REFUSALS_PER_MINUTE = 20
REFUSAL_WINDOW_S = 60.0
#: The most client addresses remembered at once; the oldest is forgotten past it.
REFUSAL_CLIENTS_MAX = 1024

_auth_log = logging.getLogger("studio.security")
_refusals_lock = threading.Lock()


def _refusals(request: Request) -> dict[str, deque[float]]:
    state = request.app.state
    with _refusals_lock:
        table = getattr(state, "owner_auth_refusals", None)
        if table is None:
            table = {}
            state.owner_auth_refusals = table
        return table


def _count_refusal(request: Request, host: str) -> tuple[int, float]:
    """Records one wrong key from ``host``; returns how many in the window, and the seconds until
    the oldest of them leaves it."""
    table = _refusals(request)
    now = time.monotonic()
    with _refusals_lock:
        seen = table.pop(host, None) or deque()
        while seen and now - seen[0] > REFUSAL_WINDOW_S:
            seen.popleft()
        seen.append(now)
        table[host] = seen  # re-inserted: the most recent client is the last one forgotten
        while len(table) > REFUSAL_CLIENTS_MAX:
            table.pop(next(iter(table)))
        return len(seen), max(1.0, REFUSAL_WINDOW_S - (now - seen[0]))


def require_owner(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> None:
    expected = request.app.state.settings.owner_token.get_secret_value()
    if credentials is not None and secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        return
    if credentials is not None:
        host = request.client.host if request.client else "necunoscut"
        count, wait = _count_refusal(request, host)
        path = request.url.path
        if count > REFUSALS_PER_MINUTE:
            if count == REFUSALS_PER_MINUTE + 1:
                _auth_log.warning(
                    "owner_auth_throttled", extra={"host": host, "path": path, "refusals": count}
                )
            raise HTTPException(
                status_code=429,
                detail="Prea multe chei greșite; încearcă din nou peste un minut.",
                headers={"Retry-After": str(int(wait + 0.999))},
            )
        _auth_log.warning("owner_auth_refused", extra={"host": host, "path": path})
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
#: How many sockets of this process may wait for the key at once (W24). Each one waiting holds a
#: task and a timer for up to SOCKET_AUTH_TIMEOUT_S, and anyone who can reach the port can open one;
#: a page opens two (the stream's relay and the events), so a handful is plenty for the Owner's
#: tabs. Past it a socket is closed at once with 1013 (try again later) and never waits.
SOCKET_AUTH_MAX_PENDING = 16

_socket_log = logging.getLogger("studio.socket_auth")
#: The sockets of this process now waiting for the key (one event loop: no lock is needed).
_pending_socket_auths = 0


def pending_socket_auths() -> int:
    """How many sockets of this process are now waiting to say the key."""
    return _pending_socket_auths


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
    only the reason is logged (``timeout``, ``malformed`` or ``wrong``), never what was sent. When
    SOCKET_AUTH_MAX_PENDING sockets are already waiting, it closes this one at once with 1013
    (reason ``busy``) without waiting.
    """
    global _pending_socket_auths
    if _pending_socket_auths >= SOCKET_AUTH_MAX_PENDING:
        return await _refuse(websocket, "busy", status.WS_1013_TRY_AGAIN_LATER)
    _pending_socket_auths += 1
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
    finally:
        _pending_socket_auths -= 1
    return await _refuse(websocket, reason, status.WS_1008_POLICY_VIOLATION)


def url_carries_key(websocket: WebSocket) -> bool:
    """Whether the socket's URL has a ``token`` parameter (in any case), empty or not."""
    return any(name.lower() == "token" for name in websocket.query_params.keys())


async def refuse_key_in_url(websocket: WebSocket) -> bool:
    """SEC-02 (2026-10-01): a socket whose URL carries a key is closed 1008 before it is
    accepted, whatever the key. uvicorn logs a handshake's path with its query (the service log
    kept it on disk), so the query form is not read at all, not even to compare. True when the
    socket was refused."""
    if not url_carries_key(websocket):
        return False
    await _refuse(websocket, "key_in_url", status.WS_1008_POLICY_VIOLATION)
    return True


async def _refuse(websocket: WebSocket, reason: str, code: int) -> bool:
    """Closes a socket that did not say the key, logging only why."""
    _socket_log.info("owner_socket_refused", extra={"reason": reason, "path": websocket.url.path})
    try:
        await websocket.close(code=code)
    except RuntimeError:
        pass  # the page had already gone
    return False
