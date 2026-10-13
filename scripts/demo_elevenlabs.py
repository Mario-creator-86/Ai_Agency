"""Browser acceptance against an isolated database. Only the ElevenLabs HTTPS boundary is mocked."""

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.db import create_db_engine, migrate  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers import elevenlabs  # noqa: E402
from app.services import bootstrap_studio  # noqa: E402


def main() -> int:
    key = secrets.token_urlsafe(32)
    models = [
        {
            "model_id": f"mock-model-{uuid4()}",
            "name": "Mock TTS model",
            "can_do_text_to_speech": True,
        }
    ]
    voices = [
        {"voice_id": f"mock-voice-{uuid4()}", "name": "Mock voice one"},
        {"voice_id": f"mock-voice-{uuid4()}", "name": "Mock voice two"},
    ]

    def transport(host, method, path, headers, *args, **kwargs):
        assert host == "api.elevenlabs.io" and method == "GET" and headers["xi-api-key"] == key
        parsed = urlsplit(path)
        if parsed.path == "/v1/user":
            data = {"user_id": "mock-account"}
        elif parsed.path == "/v1/models":
            data = models
        elif parsed.path == "/v2/voices":
            second = parse_qs(parsed.query).get("next_page_token") == ["second"]
            data = {
                "voices": voices[1:] if second else voices[:1],
                "has_more": not second,
                "next_page_token": None if second else "second",
            }
        else:
            raise AssertionError("Unexpected vendor request")
        return data, b"", "application/json"

    original = elevenlabs.request
    elevenlabs.request = transport
    try:
        with tempfile.TemporaryDirectory(prefix="studio-elevenlabs-mock-") as folder:
            settings = Settings(
                _env_file=None,
                owner_token=secrets.token_urlsafe(48),
                database_url="sqlite:///" + (Path(folder) / "studio.db").as_posix(),
                worker_enabled=False,
                provider_catalog_refresh_enabled=False,
            )
            engine = create_db_engine(settings.database_url)
            migrate(engine)
            bootstrap_studio(engine, settings)
            engine.dispose()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
                thread = threading.Thread(
                    target=server.run, kwargs={"sockets": [sock]}, daemon=True
                )
                thread.start()
                try:
                    for _ in range(100):
                        if server.started:
                            break
                        time.sleep(0.05)
                    if not server.started:
                        raise RuntimeError("Isolated browser test server did not start")
                    env = {
                        **os.environ,
                        "STUDIO_OWNER_TOKEN": settings.owner_token.get_secret_value(),
                        "ELEVENLABS_TEST_API_KEY": key,
                    }
                    return subprocess.run(
                        ["node", "scripts/verify_elevenlabs_ui.mjs", f"http://127.0.0.1:{port}"],
                        cwd=ROOT,
                        env=env,
                        check=False,
                    ).returncode
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
    finally:
        elevenlabs.request = original


if __name__ == "__main__":
    raise SystemExit(main())
