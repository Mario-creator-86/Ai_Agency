"""The Owner's page on his own machine enters without the sign-in form (LOCAL_AUTO_LOGIN).

The Owner, 2026-10-08: «Te rog sa elimini pagina de logare, nu trebuie momentan». The key is not
dropped: every other route still requires it. This route hands it to the page that asks from this
machine, through the studio's own loopback address, and to nobody else:

- the setting is on (STUDIO_LOCAL_AUTO_LOGIN, default true);
- the studio listens on loopback only: bound to 0.0.0.0 or a LAN address, a proxy or another
  machine could reach the route with a loopback peer, so the key is never handed over;
- the TCP peer is loopback (127.0.0.1, ::1, ::ffff:127.0.0.1);
- the request came through no proxy (no Forwarded, X-Forwarded-*, X-Real-IP, Via or other
  client-address header a proxy or tunnel adds);
- the Host header is exactly localhost, 127.0.0.1 or [::1] with the studio's own port. A page
  that rebinds its own DNS name to 127.0.0.1 still sends its own name here, so it is refused;
- an Origin, when sent, is that same address (http://<Host>), and a Sec-Fetch-Site, when sent,
  is same-origin or none. The answer carries no CORS header, so another origin cannot read it;
- the request carries the page's own header (X-Studio-Local-Session: 1). An <img>, <script>,
  frame, form, link or typed address cannot add a header, and a cross-origin fetch that adds one
  must first pass a CORS preflight the studio never answers. This holds in a browser that sends
  no Origin or Sec-Fetch-Site, and against a program's plain GET.

Every refusal is the same 404 an unknown path gets, so the route is not revealed, and it is left
out of the API description. The answer is Cache-Control: no-store and Cross-Origin-Resource-Policy:
same-origin (no other origin may even load it). Each hand-over is one INFO line, without the
key; a refusal is one DEBUG line with its reason.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

LOCAL_SESSION_PATH = "/owner/local-session"

#: The TCP peers that are this machine. Exact strings: uvicorn reports the socket's address.
LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
#: The addresses the studio may be bound to and still hand the key over.
LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})
#: The names the page may use in the Host header, each followed by the studio's own port.
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
#: Headers a reverse proxy adds; their presence means the request did not start on this machine.
PROXY_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-forwarded-server",
    "x-real-ip",
    "via",
    "cf-connecting-ip",
    "true-client-ip",
    "x-client-ip",
    "x-cluster-client-ip",
    "x-original-forwarded-for",
)
#: The header only the page's own fetch sends (frontend/src/local_entry.js), and its one value.
LOCAL_SESSION_HEADER = "x-studio-local-session"
LOCAL_SESSION_HEADER_VALUE = "1"
SAME_ORIGIN_FETCH = frozenset({"same-origin", "none"})

_log = logging.getLogger("studio.security")


def is_loopback_peer(peer: str | None) -> bool:
    """Whether the TCP peer's address is this machine's loopback."""
    return bool(peer) and peer in LOOPBACK_PEERS


def local_handover_refusal(
    *,
    enabled: bool,
    bind_host: str,
    port: int,
    peer: str | None,
    headers: Mapping[str, str],
) -> str | None:
    """Why the key may not be handed over, or None when it may.

    ``headers`` is read case-insensitively by the caller's mapping (Starlette's headers are); a
    plain dict must use lowercase names.
    """
    if not enabled:
        return "disabled"
    if bind_host not in LOOPBACK_BINDS:
        return "bind"
    if not is_loopback_peer(peer):
        return "peer"
    if any(name in headers for name in PROXY_HEADERS):
        return "proxy"
    host = headers.get("host", "")
    if host not in {f"{name}:{port}" for name in LOOPBACK_NAMES}:
        return "host"
    origin = headers.get("origin")
    if origin is not None and origin != f"http://{host}":
        return "origin"
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in SAME_ORIGIN_FETCH:
        return "fetch_site"
    if headers.get(LOCAL_SESSION_HEADER) != LOCAL_SESSION_HEADER_VALUE:
        return "page"
    return None


def create_local_session_router() -> APIRouter:
    """GET /owner/local-session: the Owner key for his page on this machine, else 404."""
    router = APIRouter(tags=["owner"])

    @router.get(LOCAL_SESSION_PATH, response_model=None, include_in_schema=False)
    def local_session(request: Request) -> JSONResponse:
        settings: Any = request.app.state.settings
        peer = request.client.host if request.client else None
        reason = local_handover_refusal(
            enabled=bool(getattr(settings, "local_auto_login", False)),
            bind_host=str(settings.host),
            port=int(settings.port),
            peer=peer,
            headers=request.headers,
        )
        if reason is not None:
            _log.debug("owner_local_session_refused", extra={"reason": reason, "peer": peer})
            raise HTTPException(status_code=404, detail="Not Found")
        _log.info("owner_local_session_handed", extra={"peer": peer})
        return JSONResponse(
            {"token": settings.owner_token.get_secret_value()},
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Cross-Origin-Resource-Policy": "same-origin",
            },
        )

    return router
