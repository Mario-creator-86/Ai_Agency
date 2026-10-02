"""A socket on a path the studio does not serve leaves nothing in the console.

The Owner's console, 2026-10-02: another program's page that once ran on port 8000 knocks on
ws://127.0.0.1:8000/ws every six seconds. The studio refuses it (PageFiles), but each knock
wrote three lines: the studio's own note and uvicorn's '"WebSocket /ws" 403' and 'connection
rejected (403 Forbidden)'. His words: "nu vreau să apară eroarea în consolă, dacă nu-i o eroare,
nu ar trebui să fie". A stranger's knock is not the studio's error, so it is not written; the
handshakes on the studio's own socket paths, refused or not, are written as before.

Served by a real uvicorn on a loopback port with the log configuration scripts/run.py gives it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from app.logging import QuietStrangerSockets
from app.main import PageFiles
from app.workflows.publisher import ConnectionManager
from app.workflows.router import register_websocket_gateway
from fastapi import FastAPI
from pydantic import SecretStr

TOKEN = "cheia-proprietarului-de-test"
AUTH = json.dumps({"type": "auth", "token": TOKEN})


def record(msg: str, *args: object, name: str = "uvicorn.error") -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, None)


def test_a_strangers_refused_handshake_and_its_rejection_line_are_dropped():
    quiet = QuietStrangerSockets()

    assert not quiet.filter(record('%s - "WebSocket %s" 403', "127.0.0.1:5", "/ws"))
    assert not quiet.filter(record("connection rejected (%d %s)", 403, "Forbidden"))
    assert not quiet.filter(record('%s - "WebSocket %s" %d', "127.0.0.1:6", "/socket?x=1", 404))


def test_the_studios_own_socket_lines_are_kept():
    quiet = QuietStrangerSockets()

    for path in ("/api/v1/ws", "/api/v1/ws?token=[ascuns]", "/api/v1/office/stream/signalling"):
        assert quiet.filter(record('%s - "WebSocket %s" 403', "127.0.0.1:5", path))
        assert quiet.filter(record("connection rejected (%d %s)", 403, "Forbidden"))
    assert quiet.filter(record('%s - "WebSocket %s" [accepted]', "127.0.0.1:5", "/ws"))
    assert quiet.filter(record("Application startup complete."))
    assert quiet.filter(record("connection rejected (%d %s)", 500, "Internal Server Error"))


def test_a_strangers_knocks_never_reach_the_console_and_the_studios_refusals_do(tmp_path):
    import uvicorn
    from websockets.exceptions import InvalidStatus, WebSocketException
    from websockets.sync.client import connect

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("studio_run_script", root / "scripts" / "run.py")
    run_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_script)

    (tmp_path / "index.html").write_text("<!doctype html><title>pagina</title>", encoding="utf-8")
    app = FastAPI()
    app.state.settings = SimpleNamespace(owner_token=SecretStr(TOKEN))
    app.state.engine = None
    register_websocket_gateway(app, ConnectionManager(), auth_timeout_s=0.3)
    app.mount("/", PageFiles(directory=tmp_path, html=True), name="frontend")
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
        for _ in range(3):
            try:
                with connect(f"ws://127.0.0.1:{port}/ws", open_timeout=5):
                    pass
            except (InvalidStatus, WebSocketException):
                pass
        try:
            with connect(f"ws://127.0.0.1:{port}/api/v1/ws?token={TOKEN}", open_timeout=5):
                pass
        except (InvalidStatus, WebSocketException):
            pass
        with connect(f"ws://127.0.0.1:{port}/api/v1/ws", open_timeout=5) as ws:
            ws.send(AUTH)
            assert json.loads(ws.recv(timeout=5)) == {"type": "auth_ok"}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    text = written.getvalue()
    assert '"WebSocket /ws"' not in text, text
    assert text.count("connection rejected") == 1, text
    assert '"WebSocket /api/v1/ws?token=[ascuns]" 403' in text, text
    assert TOKEN not in text
