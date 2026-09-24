"""The events socket (/api/v1/ws) takes the Owner's key in its first message, never in its URL.

A key in a WebSocket's query string is printed by the browser when the socket fails and reaches
proxy and server access logs (2026-09-25). The page sends it as the socket's first message once the
backend says it can (GET /office/stream ``auth: "first_message"``); a page from before keeps the
query string until the Owner reloads it, so that form is still read. A socket that does not say
the key in time, or says another, is closed with 1008 and never joins the broadcast.
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


def test_a_page_from_before_still_opens_with_the_key_in_its_url():
    client, manager = make()
    with client.websocket_connect(f"/api/v1/ws?token={TOKEN}") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        assert manager.active_count == 1


@pytest.mark.parametrize("query", ["?token=", "?token=not-the-owner"])
def test_a_wrong_key_in_the_url_is_refused(query):
    client, _ = make()
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(f"/api/v1/ws{query}") as ws:
            ws.receive_text()
    assert refused.value.code == 1008


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
