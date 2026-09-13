"""The live Unreal headquarters: its signalling relayed on the page's own origin, never faked."""

import asyncio
from types import SimpleNamespace

import pytest
from app.office.stream import (
    RELAY_PATH,
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
    }
