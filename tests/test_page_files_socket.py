"""A socket on a path no route serves is closed cleanly, not a 500 with a traceback.

Seen in the Owner's console on 2026-10-02: a WebSocket to the page's root fell through every
route to the page's files, which only speak HTTP; Starlette's StaticFiles asserted
``scope["type"] == "http"``, printed a full traceback and the handshake answered 500, again on
every retry. The page's files now refuse such a socket with a policy close (the handshake
answers 403) and log its path at DEBUG only, without its query (a stranger's knock is not the
studio's error; tests/test_quiet_stranger_sockets.py keeps uvicorn's own lines out of the console).
"""

from __future__ import annotations

import logging

import pytest
from app.main import PageFiles
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def a_page(tmp_path) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>pagina</title>", encoding="utf-8")
    app = Starlette(routes=[Mount("/", PageFiles(directory=tmp_path, html=True))])
    return TestClient(app)


def test_a_socket_on_an_unknown_path_is_refused_without_a_server_error(tmp_path, caplog):
    client = a_page(tmp_path)

    with caplog.at_level(logging.DEBUG, logger="studio.api"):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/?token=SECRET"):
                pass

    assert closed.value.code == 1008
    logged = [r for r in caplog.records if r.getMessage() == "websocket_unknown_path"]
    assert len(logged) == 1 and logged[0].path == "/"
    assert "SECRET" not in caplog.text


def test_the_page_itself_is_still_served(tmp_path):
    client = a_page(tmp_path)

    response = client.get("/")

    assert response.status_code == 200 and "pagina" in response.text
