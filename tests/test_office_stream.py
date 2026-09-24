"""The live Unreal headquarters: its signalling relayed on the page's own origin, never faked."""

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest
from app.office.stream import (
    RELAY_PATH,
    SOCKET_AUTH_TIMEOUT_S,
    register_stream_gateway,
    signalling_target,
    stream_status,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

TOKEN = "owner-token-for-the-stream-relay-tests-0123456789"


def settings(url="ws://127.0.0.1:8890"):
    return SimpleNamespace(owner_token=SecretStr(TOKEN), office_stream_signalling_url=url)


class FakeSignalling:
    """Epic's signalling server as the relay sees it: greets, then answers each message."""

    def __init__(self, greeting):
        self.sent = []
        self.inbox = asyncio.Queue()
        for message in greeting:
            self.inbox.put_nowait(message)

    async def send(self, data):
        self.sent.append(data)
        await self.inbox.put(f"answer:{data}")

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.inbox.get()
        if message is None:
            raise StopAsyncIteration
        return message

    async def close(self):
        await self.inbox.put(None)


def client_for(settings_obj, connect):
    app = FastAPI()
    app.state.settings = settings_obj
    register_stream_gateway(app, connect=connect)
    return TestClient(app)


async def never_connect(*args, **kwargs):
    raise AssertionError("the relay must not reach out")


def test_the_relay_carries_signalling_both_ways():
    opened = []

    async def connect(url, **kwargs):
        upstream = FakeSignalling(['{"type":"config"}'])
        opened.append((url, upstream))
        return upstream

    client = client_for(settings(), connect)
    with client.websocket_connect(f"{RELAY_PATH}?token={TOKEN}") as ws:
        assert ws.receive_text() == '{"type":"config"}'
        ws.send_text('{"type":"listStreamers"}')
        assert ws.receive_text() == 'answer:{"type":"listStreamers"}'
    url, upstream = opened[0]
    assert url == "ws://127.0.0.1:8890"
    assert upstream.sent == ['{"type":"listStreamers"}']


@pytest.mark.parametrize("query", ["", "?token=", "?token=not-the-owner"])
def test_without_the_owner_token_the_relay_refuses(query):
    client = client_for(settings(), never_connect)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(f"{RELAY_PATH}{query}") as ws:
            ws.receive_text()
    assert refused.value.code == 1008


def test_with_no_stream_configured_the_relay_closes_without_reaching_out():
    client = client_for(settings(url=None), never_connect)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"{RELAY_PATH}?token={TOKEN}") as ws:
            ws.receive_text()
    assert closed.value.code == 1013


def test_when_the_stream_is_not_running_the_relay_closes_and_the_page_keeps_its_renderer():
    async def unreachable(*args, **kwargs):
        raise ConnectionRefusedError("nothing on the port")

    client = client_for(settings(), unreachable)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"{RELAY_PATH}?token={TOKEN}") as ws:
            ws.receive_text()
    assert closed.value.code == 1013


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("ws://127.0.0.1:8890", "ws://127.0.0.1:8890"),
        ("  wss://hq.example/signalling ", "wss://hq.example/signalling"),
        ("http://127.0.0.1:8890", None),
        ("127.0.0.1:8890", None),
        ("", None),
        (None, None),
    ],
)
def test_only_a_websocket_address_counts_as_configured(url, target):
    assert signalling_target(settings(url=url)) == target
    assert stream_status(settings(url=url)) == {
        "available": target is not None,
        "relay": RELAY_PATH,
        "auth": "first_message",
    }


# ---------------------------------------------------------------------------------------------
# The Owner's key out of the URL (2026-09-25). A key in a WebSocket's query string is printed by
# the browser when the socket fails and reaches proxy and server access logs. The page now sends
# it as the socket's first message; the relay answers «relay_ready» only once it has the key and
# the signalling server, and refuses a socket that does not say the key in time.
# ---------------------------------------------------------------------------------------------

AUTH = json.dumps({"type": "auth", "token": TOKEN})


def quick_client(settings_obj, connect, timeout=0.3):
    app = FastAPI()
    app.state.settings = settings_obj
    register_stream_gateway(app, connect=connect, auth_timeout_s=timeout)
    return TestClient(app)


def test_the_route_tells_the_page_the_key_goes_in_the_first_message():
    assert stream_status(settings())["auth"] == "first_message"


def test_the_key_in_the_first_message_opens_the_relay_and_is_never_forwarded():
    opened = []

    async def connect(url, **kwargs):
        upstream = FakeSignalling(['{"type":"config"}'])
        opened.append(upstream)
        return upstream

    client = quick_client(settings(), connect)
    with client.websocket_connect(RELAY_PATH) as ws:
        ws.send_text(AUTH)
        assert json.loads(ws.receive_text()) == {"type": "relay_ready"}
        assert ws.receive_text() == '{"type":"config"}'
        ws.send_text('{"type":"listStreamers"}')
        assert ws.receive_text() == 'answer:{"type":"listStreamers"}'
    assert opened[0].sent == ['{"type":"listStreamers"}']
    assert all(TOKEN not in m for m in opened[0].sent)


@pytest.mark.parametrize(
    "first",
    [
        json.dumps({"type": "auth", "token": "not-the-owner"}),
        json.dumps({"type": "auth", "token": ""}),
        json.dumps({"type": "auth"}),
        json.dumps({"type": "listStreamers"}),
        json.dumps(["auth", TOKEN]),
        "not json",
        json.dumps({"type": "auth", "token": TOKEN, "pad": "x" * 5000}),
    ],
)
def test_a_first_message_without_the_key_is_refused_before_reaching_out(first):
    client = quick_client(settings(), never_connect)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(RELAY_PATH) as ws:
            ws.send_text(first)
            ws.receive_text()
    assert refused.value.code == 1008


def test_a_binary_first_message_is_refused():
    client = quick_client(settings(), never_connect)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(RELAY_PATH) as ws:
            ws.send_bytes(AUTH.encode())
            ws.receive_text()
    assert refused.value.code == 1008


def test_a_socket_that_never_says_the_key_is_closed_after_a_short_time():
    client = quick_client(settings(), never_connect, timeout=0.2)
    started = time.monotonic()
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(RELAY_PATH) as ws:
            ws.receive_text()
    assert refused.value.code == 1008
    assert time.monotonic() - started < 3


def test_the_default_wait_for_the_key_is_short():
    assert 0 < SOCKET_AUTH_TIMEOUT_S <= 10


def test_after_the_key_an_unreachable_stream_closes_without_saying_ready():
    async def unreachable(*args, **kwargs):
        raise ConnectionRefusedError("nothing on the port")

    client = quick_client(settings(), unreachable)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(RELAY_PATH) as ws:
            ws.send_text(AUTH)
            ws.receive_text()
    assert closed.value.code == 1013


def test_after_the_key_with_no_stream_configured_the_relay_closes():
    client = quick_client(settings(url=None), never_connect)
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(RELAY_PATH) as ws:
            ws.send_text(AUTH)
            ws.receive_text()
    assert closed.value.code == 1013


def test_the_key_is_never_logged_nor_echoed(caplog):
    caplog.set_level(logging.DEBUG)

    async def connect(url, **kwargs):
        return FakeSignalling(['{"type":"config"}'])

    async def unreachable(*args, **kwargs):
        raise ConnectionRefusedError(f"refused {TOKEN}")

    heard = []
    with quick_client(settings(), connect).websocket_connect(RELAY_PATH) as ws:
        ws.send_text(AUTH)
        heard.append(ws.receive_text())
        heard.append(ws.receive_text())
    for first in (json.dumps({"type": "auth", "token": TOKEN + "x"}), "junk " + TOKEN):
        with pytest.raises(WebSocketDisconnect):
            with quick_client(settings(), never_connect).websocket_connect(RELAY_PATH) as ws:
                ws.send_text(first)
                heard.append(ws.receive_text())
    with pytest.raises(WebSocketDisconnect):
        with quick_client(settings(), unreachable).websocket_connect(RELAY_PATH) as ws:
            ws.send_text(AUTH)
            heard.append(ws.receive_text())
    assert all(TOKEN not in h for h in heard)
    assert TOKEN not in caplog.text
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in repr(record.__dict__)
