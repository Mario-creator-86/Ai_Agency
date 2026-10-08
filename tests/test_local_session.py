"""The page on the Owner's own machine enters without the sign-in form (LOCAL_AUTO_LOGIN).

The Owner, 2026-10-08: «Te rog sa elimini pagina de logare, nu trebuie momentan». The key is not
dropped: every route still asks for it. One route, GET /api/v1/owner/local-session, hands it to a
page that asks from this machine, through the studio's own address, and to nobody else: the TCP
peer is loopback, the Host header is the studio's own loopback address and port (a DNS-rebinding
page has its own name there), an Origin or Sec-Fetch-Site that says another site is refused, a
request that came through a proxy is refused, and a studio bound to anything but loopback never
hands it over. Every refusal is the same 404 an unknown path gets. STUDIO_LOCAL_AUTO_LOGIN=false
turns it off.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from app.config import Settings
from app.local_session import (
    LOCAL_SESSION_HEADER,
    LOCAL_SESSION_PATH,
    is_loopback_peer,
    local_handover_refusal,
)
from app.main import create_app
from fastapi.testclient import TestClient
from pydantic import SecretStr

ROUTE = f"/api/v1{LOCAL_SESSION_PATH}"
PORT = 8000
#: What the page's own fetch sends (frontend/src/local_entry.js): its address and its own header.
GOOD_HOST = {"host": f"127.0.0.1:{PORT}", "x-studio-local-session": "1"}


def _refusal(*, enabled=True, bind="127.0.0.1", port=PORT, peer="127.0.0.1", headers=None):
    return local_handover_refusal(
        enabled=enabled,
        bind_host=bind,
        port=port,
        peer=peer,
        headers=GOOD_HOST if headers is None else headers,
    )


# ------------------------------------------------------------------------- the decision itself


def test_the_owners_own_page_on_this_machine_is_handed_the_key():
    assert _refusal() is None


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_every_loopback_peer_is_this_machine(peer):
    assert is_loopback_peer(peer)
    assert _refusal(peer=peer) is None


@pytest.mark.parametrize(
    "peer", [None, "", "testclient", "192.168.1.20", "10.0.0.5", "8.8.8.8", "::ffff:10.0.0.5"]
)
def test_another_machine_is_never_handed_the_key(peer):
    assert not is_loopback_peer(peer)
    assert _refusal(peer=peer) == "peer"


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"])
def test_the_studios_own_loopback_names_are_accepted(host):
    assert _refusal(headers={**GOOD_HOST, "host": host}) is None


@pytest.mark.parametrize(
    "host",
    [
        "",
        "127.0.0.1",  # no port: not the studio's own address
        "localhost",
        f"127.0.0.1:{PORT + 1}",  # another port on this machine
        f"evil.example:{PORT}",  # a DNS-rebinding page keeps its own name in Host
        f"attacker.localhost:{PORT}",
        f"127.0.0.1.nip.io:{PORT}",
        f"LOCALHOST:{PORT}",
        f"localhost.:{PORT}",
    ],
)
def test_any_other_host_header_is_refused(host):
    assert _refusal(headers={"host": host}) == "host"


def test_a_request_without_a_host_header_is_refused():
    assert _refusal(headers={}) == "host"


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",
        "null",
        f"http://localhost:{PORT}",  # another origin than the Host the request went to
        f"https://127.0.0.1:{PORT}",
        f"http://127.0.0.1:{PORT + 1}",
    ],
)
def test_another_origin_is_refused(origin):
    assert _refusal(headers={**GOOD_HOST, "origin": origin}) == "origin"


def test_the_studios_own_origin_is_accepted():
    assert _refusal(headers={**GOOD_HOST, "origin": f"http://127.0.0.1:{PORT}"}) is None


@pytest.mark.parametrize("site", ["cross-site", "same-site", "garbage"])
def test_a_fetch_from_another_site_is_refused(site):
    assert _refusal(headers={**GOOD_HOST, "sec-fetch-site": site}) == "fetch_site"


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_a_same_origin_fetch_is_accepted(site):
    assert _refusal(headers={**GOOD_HOST, "sec-fetch-site": site}) is None


@pytest.mark.parametrize(
    "header",
    [
        "x-forwarded-for",
        "forwarded",
        "x-forwarded-host",
        "x-real-ip",
        # a tunnel or proxy that adds one of these but no X-Forwarded-For (cloudflared, CDNs,
        # an Apache or nginx left at its defaults) is still a proxy
        "via",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-forwarded-server",
        "cf-connecting-ip",
        "true-client-ip",
        "x-client-ip",
        "x-cluster-client-ip",
        "x-original-forwarded-for",
    ],
)
def test_a_request_that_came_through_a_proxy_is_refused(header):
    assert _refusal(headers={**GOOD_HOST, header: "127.0.0.1"}) == "proxy"


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "192.168.1.20", "studio.lan", ""])
def test_a_studio_listening_beyond_this_machine_never_hands_it_over(bind):
    assert _refusal(bind=bind) == "bind"


@pytest.mark.parametrize("bind", ["127.0.0.1", "localhost", "::1"])
def test_a_studio_listening_on_loopback_may(bind):
    assert _refusal(bind=bind) is None


def test_the_setting_turns_it_off():
    assert _refusal(enabled=False) == "disabled"


@pytest.mark.parametrize("value", [None, "", "0", "true", "1 "])
def test_a_request_without_the_pages_own_header_is_refused(value):
    """Only the page's own fetch sets it. An <img>, <script>, <iframe>, a form, a link, a typed
    address or a no-cors fetch cannot add a header, and a cross-origin fetch that adds one must
    pass a CORS preflight the studio never answers. So even a browser that sends no Origin and no
    Sec-Fetch-Site (an old one), or a plain GET from a program, is refused."""
    headers = {"host": GOOD_HOST["host"]}
    if value is not None:
        headers[LOCAL_SESSION_HEADER] = value
    assert _refusal(headers=headers) == "page"


# ---------------------------------------------------------------------------------- the setting


def test_the_setting_is_on_by_default_and_can_be_turned_off(monkeypatch):
    token = "k" * 48
    assert Settings(_env_file=None, owner_token=token).local_auto_login is True
    monkeypatch.setenv("STUDIO_LOCAL_AUTO_LOGIN", "false")
    assert Settings(_env_file=None, owner_token=token).local_auto_login is False


# ------------------------------------------------------------------------------------ the route


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _local_client(app):
    return TestClient(app, client=("127.0.0.1", 50123))


def test_the_route_hands_the_key_to_this_machine_and_logs_without_it(engine, settings):
    key = settings.owner_token.get_secret_value()
    records = _Records()
    logger = logging.getLogger("studio.security")
    logger.addHandler(records)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        with _local_client(create_app(settings)) as client:
            response = client.get(ROUTE, headers={**GOOD_HOST, "sec-fetch-site": "same-origin"})
    finally:
        logger.removeHandler(records)
        logger.setLevel(previous)
    assert response.status_code == 200
    assert response.json() == {"token": key}
    assert "no-store" in response.headers["cache-control"]
    assert "access-control-allow-origin" not in response.headers
    # no other origin may even load it (an old browser's no-cors <script>/<img>, a Spectre read)
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["x-content-type-options"] == "nosniff"
    handed = [r for r in records.records if r.getMessage() == "owner_local_session_handed"]
    assert len(handed) == 1 and handed[0].levelno == logging.INFO
    for record in records.records:
        assert key not in record.getMessage()
        assert key not in repr(record.__dict__)


def test_the_key_handed_over_opens_the_studio(engine, settings):
    with _local_client(create_app(settings)) as client:
        key = client.get(ROUTE, headers=GOOD_HOST).json()["token"]
        snapshot = client.get(
            "/api/v1/snapshot", headers={**GOOD_HOST, "Authorization": f"Bearer {key}"}
        )
    assert snapshot.status_code == 200


def test_a_refusal_is_the_same_404_as_an_unknown_path(engine, settings):
    with TestClient(create_app(settings)) as client:  # peer "testclient": not this machine
        refused = client.get(ROUTE)
        unknown = client.get("/api/v1/owner/no-such-route")
    assert refused.status_code == 404
    assert refused.json() == unknown.json()
    assert "token" not in refused.text


def test_another_origin_gets_no_key_and_no_cors(engine, settings):
    with _local_client(create_app(settings)) as client:
        response = client.get(ROUTE, headers={**GOOD_HOST, "origin": "http://evil.example"})
    assert response.status_code == 404
    assert "access-control-allow-origin" not in response.headers
    assert settings.owner_token.get_secret_value() not in response.text


def test_turned_off_the_route_answers_404(engine, settings):
    off = settings.model_copy(update={"local_auto_login": False})
    with _local_client(create_app(off)) as client:
        assert client.get(ROUTE, headers=GOOD_HOST).status_code == 404


def test_a_studio_bound_to_every_address_answers_404(engine, settings):
    exposed = settings.model_copy(update={"host": "0.0.0.0"})
    with _local_client(create_app(exposed)) as client:
        assert client.get(ROUTE, headers=GOOD_HOST).status_code == 404


def test_an_old_browsers_no_cors_load_gets_no_key(engine, settings):
    # no Origin, no Sec-Fetch-*: what an <img>/<script> of another site sent by an old browser
    with _local_client(create_app(settings)) as client:
        response = client.get(ROUTE, headers={"host": GOOD_HOST["host"]})
    assert response.status_code == 404
    assert settings.owner_token.get_secret_value() not in response.text


def test_the_route_is_not_in_the_api_description(engine, settings):
    app = create_app(settings)
    inner = app.app  # create_app wraps the FastAPI app in TrustedHostMiddleware
    assert ROUTE not in inner.openapi()["paths"]
    with _local_client(app) as client:
        assert client.get("/openapi.json", headers=GOOD_HOST).status_code == 404
        assert client.get("/docs", headers=GOOD_HOST).status_code == 404


def test_behind_a_proxy_the_route_answers_404(engine, settings):
    with _local_client(create_app(settings)) as client:
        response = client.get(ROUTE, headers={**GOOD_HOST, "x-forwarded-for": "203.0.113.9"})
    assert response.status_code == 404


# ------------------------------------------------------------ a real uvicorn on a loopback port


def test_a_real_server_on_loopback_hands_it_to_its_own_address_only():
    import uvicorn
    from app.local_session import create_local_session_router
    from fastapi import FastAPI

    key = "r" * 48
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        owner_token=SecretStr(key), local_auto_login=True, host="127.0.0.1", port=0
    )
    app.include_router(create_local_session_router(), prefix="/api/v1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off"))
    written = io.StringIO()
    capture = logging.StreamHandler(written)
    watched = [logging.getLogger(n) for n in ("uvicorn.access", "uvicorn.error", "studio")]
    for logger in watched:
        logger.addHandler(capture)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        app.state.settings.port = port
        url = f"http://127.0.0.1:{port}{ROUTE}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no system proxy

        plain = urllib.request.Request(url)  # a program's plain GET: no page header
        with pytest.raises(urllib.error.HTTPError) as unasked:
            opener.open(plain, timeout=5)
        assert unasked.value.code == 404

        page = urllib.request.Request(url, headers={"X-Studio-Local-Session": "1"})
        with opener.open(page, timeout=5) as answer:  # Host: 127.0.0.1:<port>
            assert answer.status == 200
            assert "no-store" in answer.headers["Cache-Control"]
            assert answer.read().decode() == f'{{"token":"{key}"}}'

        rebound = urllib.request.Request(
            url, headers={"Host": f"evil.example:{port}", "X-Studio-Local-Session": "1"}
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            opener.open(rebound, timeout=5)
        assert refused.value.code == 404
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        for logger in watched:
            logger.removeHandler(capture)
    assert key not in written.getvalue()
