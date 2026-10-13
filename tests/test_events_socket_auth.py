"""The events socket (/api/v1/ws) takes the Owner's key in its first message, never in its URL.

A key in a WebSocket's query string is printed by the browser when the socket fails and reaches
proxy and server access logs (2026-09-25). The page sends it as the socket's first message once the
backend says it can (GET /office/stream ``auth: "first_message"``). Since 2026-10-01 (SEC-02) the
query form is refused outright: uvicorn logs a handshake's path with its query. A socket that does
not say the key in time, or says another, is closed with 1008 and never joins the broadcast.
"""

import json
import logging
import time
from types import SimpleNamespace

import pytest
from app.workflows.publisher import ConnectionManager
from app.workflows.router import register_websocket_gateway
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

TOKEN = "owner-token-for-the-events-socket-tests-0123456789"
AUTH = json.dumps({"type": "auth", "token": TOKEN})


def make(timeout=0.3):
    app = FastAPI()
    app.state.settings = SimpleNamespace(owner_token=SecretStr(TOKEN))
    app.state.engine = None
    manager = ConnectionManager()
    register_websocket_gateway(app, manager, auth_timeout_s=timeout)
    return TestClient(app), manager


def test_the_key_in_the_first_message_opens_the_socket_and_joins_the_broadcast():
    client, manager = make()
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_text(AUTH)
        assert ws.receive_json() == {"type": "auth_ok"}
        assert manager.active_count == 1
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.portal.call(manager.broadcast, {"type": "event", "data": {"sequence": 7}})
        assert ws.receive_json() == {"type": "event", "data": {"sequence": 7}}


@pytest.mark.parametrize(
    "first",
    [
        json.dumps({"type": "auth", "token": "not-the-owner"}),
        json.dumps({"type": "auth"}),
        json.dumps({"type": "ping"}),
        "not json",
    ],
)
def test_a_first_message_without_the_key_is_refused_and_hears_nothing(first):
    client, manager = make()
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(first)
            ws.receive_text()
    assert refused.value.code == 1008
    assert manager.active_count == 0


def test_a_silent_socket_is_closed_after_a_short_time_without_joining():
    client, manager = make(timeout=0.2)
    started = time.monotonic()
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/api/v1/ws") as ws:
            assert manager.active_count == 0
            ws.receive_text()
    assert refused.value.code == 1008
    assert time.monotonic() - started < 3
    assert manager.active_count == 0


@pytest.mark.parametrize(
    "query", ["?token=", "?token=not-the-owner", f"?token={TOKEN}", f"?a=1&TOKEN={TOKEN}"]
)
def test_a_key_in_the_url_is_refused_even_the_right_one(query):
    """SEC-02 (2026-10-01): uvicorn prints a socket's path with its query, and the service log
    kept it on disk. The query form is no longer read at all: any socket that carries a key in
    its URL is closed 1008 before it is accepted, and never joins the broadcast."""
    client, manager = make()
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(f"/api/v1/ws{query}") as ws:
            ws.send_text(AUTH)
            ws.receive_text()
    assert refused.value.code == 1008
    assert manager.active_count == 0


def test_the_key_is_never_logged_nor_echoed(caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = make()
    heard = []
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_text(AUTH)
        heard.append(ws.receive_text())
    for first in (json.dumps({"type": "auth", "token": TOKEN + "x"}), "junk " + TOKEN):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/v1/ws") as ws:
                ws.send_text(first)
                heard.append(ws.receive_text())
    assert all(TOKEN not in h for h in heard)
    assert TOKEN not in caplog.text
    for record in caplog.records:
        assert TOKEN not in repr(record.__dict__)


# ---------------------------------------------------------------------------------------------
# W24: sockets that have not said the key yet are few at a time. Each one holds a task and a
# 5 s timer; a page opens two, so a handful is plenty. Past the limit a socket is closed at once
# with 1013 (try again later) and never waits; the count falls again as each one is answered.
# ---------------------------------------------------------------------------------------------


def test_sockets_waiting_for_the_key_are_limited_per_process(monkeypatch):
    import app.security as security

    monkeypatch.setattr(security, "SOCKET_AUTH_MAX_PENDING", 2)
    client, manager = make(timeout=2.0)
    with (
        client.websocket_connect("/api/v1/ws") as first,
        client.websocket_connect("/api/v1/ws") as second,
    ):
        assert security.pending_socket_auths() == 2
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as busy:
            with client.websocket_connect("/api/v1/ws") as third:
                third.receive_text()
        assert busy.value.code == 1013
        assert time.monotonic() - started < 1.0, "the third never waited for a key"
        # the two already waiting are unaffected and may still say the key
        first.send_text(AUTH)
        assert first.receive_json() == {"type": "auth_ok"}
        second.send_text(AUTH)
        assert second.receive_json() == {"type": "auth_ok"}
        assert manager.active_count == 2
        assert security.pending_socket_auths() == 0
        # a place is free again: a new socket is heard
        with client.websocket_connect("/api/v1/ws") as fourth:
            fourth.send_text(AUTH)
            assert fourth.receive_json() == {"type": "auth_ok"}


def test_every_way_out_of_the_wait_gives_its_place_back(monkeypatch):
    import app.security as security

    monkeypatch.setattr(security, "SOCKET_AUTH_MAX_PENDING", 1)
    client, _ = make(timeout=0.2)
    # a wrong key, a silent socket, and one that goes away: each frees its place
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": "nope"}))
            ws.receive_text()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.receive_text()
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.close()
    time.sleep(0.3)
    assert security.pending_socket_auths() == 0
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_text(AUTH)
        assert ws.receive_json() == {"type": "auth_ok"}


def test_a_refusal_for_a_full_house_is_logged_without_anything_the_page_sent(monkeypatch, caplog):
    import app.security as security

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(security, "SOCKET_AUTH_MAX_PENDING", 0)
    client, _ = make()
    with pytest.raises(WebSocketDisconnect) as busy:
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.receive_text()
    assert busy.value.code == 1013
    reasons = [getattr(r, "reason", None) for r in caplog.records]
    assert "busy" in reasons


# ---------------------------------------------------------------------------------------------
# SEC-02: the handshake line uvicorn itself writes. Served by a real uvicorn on a loopback port,
# with the log configuration scripts/run.py gives it: the key a socket carries in its URL never
# reaches the console, whether the socket is refused (403) or not.
# ---------------------------------------------------------------------------------------------


def test_uvicorns_own_handshake_line_never_carries_the_key():
    import asyncio
    import importlib.util
    import io
    import threading
    from pathlib import Path

    import uvicorn
    from websockets.exceptions import InvalidStatus, WebSocketException
    from websockets.sync.client import connect

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("studio_run_script", root / "scripts" / "run.py")
    run_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_script)

    app = FastAPI()
    app.state.settings = SimpleNamespace(owner_token=SecretStr(TOKEN))
    app.state.engine = None
    register_websocket_gateway(app, ConnectionManager(), auth_timeout_s=0.3)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_config=run_script.uvicorn_log_config(), lifespan="off"
    )
    server = uvicorn.Server(config)
    written = io.StringIO()
    loggers = [logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access")]
    try:
        thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        for logger in loggers:
            for handler in logger.handlers:
                handler.setStream(written)
        port = server.servers[0].sockets[0].getsockname()[1]
        for query in (f"?token={TOKEN}", f"?x=1&token={TOKEN}"):
            try:
                with connect(f"ws://127.0.0.1:{port}/api/v1/ws{query}", open_timeout=5) as ws:
                    ws.recv(timeout=2)
            except (InvalidStatus, WebSocketException, TimeoutError):
                pass
        with connect(f"ws://127.0.0.1:{port}/api/v1/ws", open_timeout=5) as ws:
            ws.send(AUTH)
            assert json.loads(ws.recv(timeout=5)) == {"type": "auth_ok"}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    text = written.getvalue()
    assert "/api/v1/ws" in text, "the handshake lines were written"
    assert TOKEN not in text
    assert "token=[ascuns]" in text
