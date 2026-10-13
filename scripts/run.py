import copy
import sys
from pathlib import Path
from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402

#: How long uvicorn waits for open connections (the page's socket, a request in flight) when
#: the studio is stopped, before it closes them. The day running in the worker is not cut by
#: this: the lifespan asks it to stop at its next boundary (`request_shutdown`) and waits for
#: the scene in flight to end, so a stop never lands in the middle of a purchase (REL-10).
GRACEFUL_SHUTDOWN_SECONDS = 30


def uvicorn_log_config() -> dict[str, Any]:
    """uvicorn's own logging, with every ``token=`` value blanked on its handlers (SEC-02).

    uvicorn writes each WebSocket handshake on 'uvicorn.error' with the path and its query
    (websockets_impl.py, '[accepted]' and '403'), and the Windows service sends the console to
    a file. The studio's sockets refuse a key in the URL, but the line is written before the
    refusal: the filter sits on the handlers, so it holds for every uvicorn logger, before the
    application has configured anything (app.logging adds the same filter on the loggers).
    """
    config = copy.deepcopy(LOGGING_CONFIG)
    filters = config.setdefault("filters", {})
    # A refused socket on a path the studio does not serve (another program's page knocking on
    # this port) is not the studio's error and leaves no line (app.logging.QuietStrangerSockets).
    filters["quiet_stranger_sockets"] = {"()": "app.logging.QuietStrangerSockets"}
    filters["redact_url_tokens"] = {"()": "app.logging.RedactUrlTokens"}
    for handler in config.get("handlers", {}).values():
        handler["filters"] = [
            *handler.get("filters", []),
            "quiet_stranger_sockets",
            "redact_url_tokens",
        ]
    return config


if __name__ == "__main__":
    settings = Settings()  # type: ignore[call-arg]
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build frontend first: npm run build --prefix frontend")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_config=uvicorn_log_config(),
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
