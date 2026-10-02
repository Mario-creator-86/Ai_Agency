"""The studio's logs keep what they are handed, safely (REL-05, SEC-07, SEC-02).

The JSON formatter used to keep only four fields of a record's extras, so the 27 ``reason`` and
14 ``error`` extras the code passes, and every traceback, were dropped: a failed worker pass
logged «worker_pass_failed» and nothing else. Loggers outside ``studio`` (``amn.*`` and the
modules logging under their own ``__name__``) were never configured, and there was no log file.
Now every extra is kept, values pass through the vendor-text sanitiser, keys that name a secret
are blanked, a traceback is rendered as its frames (file:line:function, never the message or
the locals), the three namespaces are configured, and a rotating file sits beside the database.
uvicorn's handshake line, which prints a socket's path with its query, has every ``token=``
value blanked.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid

import pytest
from app.logging import (
    REDACTED,
    JsonFormatter,
    RedactUrlTokens,
    configure_logging,
    log_directory,
)

FAKE_KEY = "sk-" + "a1B2c3D4e5" * 4  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging changes process-wide loggers; each test leaves them as it found them."""
    names = ("studio", "amn", "app", "uvicorn.error", "uvicorn.access")
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            list(logging.getLogger(name).filters),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    yield
    for name, (handlers, filters, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers, logger.filters = handlers, filters
        logger.setLevel(level)
        logger.propagate = propagate


def _line(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def _record(message="event", level=logging.INFO, exc_info=None, **extra) -> logging.LogRecord:
    logger = logging.getLogger("studio.test")
    return logger.makeRecord(
        logger.name, level, __file__, 1, message, (), exc_info, extra=extra or None
    )


def test_the_extras_a_call_passes_are_kept():
    task_id = str(uuid.uuid4())
    line = _line(
        _record(
            "worker_pass_failed",
            reason="Etapa «media» s-a oprit: soldul Runway nu ajunge.",
            error="OperationalError",
            task_id=task_id,
            correlation_id=task_id,
            ran=["COMPLETED", "FAILED"],
            triggered=2,
        )
    )
    assert line["message"] == "worker_pass_failed"
    assert line["reason"] == "Etapa «media» s-a oprit: soldul Runway nu ajunge."
    assert line["error"] == "OperationalError"
    # identifiers are kept whole: the sanitiser would cut a UUID as an «opaque run»
    assert line["task_id"] == task_id and line["correlation_id"] == task_id
    assert line["ran"] == ["COMPLETED", "FAILED"] and line["triggered"] == 2


def test_keys_that_name_a_secret_are_blanked_and_secret_shaped_values_cut():
    line = _line(
        _record(
            token="owner-token-value",  # pragma: allowlist secret
            api_key=FAKE_KEY,
            authorization="Bearer abc.def",
            password="hunter22",  # pragma: allowlist secret
            reason=f"vendor said: invalid key {FAKE_KEY} at https://x.example/out.mp4?sig=1",
            nested={"secret": "s3", "detail": f"retry with {FAKE_KEY}"},  # pragma: allowlist secret
        )
    )
    for key in ("token", "api_key", "authorization", "password"):
        assert line[key] == REDACTED, key
    assert line["nested"]["secret"] == REDACTED
    text = json.dumps(line)
    assert FAKE_KEY not in text
    assert "x.example" not in text, "a signed URL is a credential in its query"
    assert "hunter22" not in text and "owner-token-value" not in text
    assert "vendor said: invalid key" in line["reason"]


def test_a_long_value_is_truncated():
    line = _line(_record(reason="cuvânt " * 2000))
    assert len(line["reason"]) <= 2000


def _raise_inner():
    raise ValueError(f"the vendor echoed {FAKE_KEY}")


def test_a_traceback_is_kept_as_its_frames_without_message_or_locals():
    secret_local = FAKE_KEY  # noqa: F841 - a local the rendering must never show
    try:
        _raise_inner()
    except ValueError:
        import sys

        line = _line(_record("request_failed", level=logging.ERROR, exc_info=sys.exc_info()))
    exception = line["exception"]
    assert exception["class"] == "ValueError"
    frames = exception["frames"]
    assert any(f.endswith(":_raise_inner") and "test_logging.py:" in f for f in frames), frames
    assert any(":test_a_traceback_is_kept" in f for f in frames), frames
    text = json.dumps(line)
    assert FAKE_KEY not in text and "the vendor echoed" not in text


def test_a_chained_cause_is_named():
    try:
        try:
            raise OSError("disk")
        except OSError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError:
        import sys

        line = _line(_record(level=logging.ERROR, exc_info=sys.exc_info()))
    assert line["exception"]["class"] == "RuntimeError"
    assert line["exception"]["cause"] == "OSError"


def test_the_three_namespaces_reach_the_file_and_the_file_rotates(tmp_path):
    configure_logging("INFO", log_dir=tmp_path / "logs", max_bytes=4000, backups=2)
    for name in ("studio.api", "amn.maintenance", "app.office.stream", "app.providers.elevenlabs"):
        logging.getLogger(name).info("hello_from", extra={"source": name})
    lines = [
        json.loads(text)
        for text in (tmp_path / "logs" / "studio.log").read_text(encoding="utf-8").splitlines()
    ]
    assert {line["source"] for line in lines} == {
        "studio.api",
        "amn.maintenance",
        "app.office.stream",
        "app.providers.elevenlabs",
    }
    for n in range(400):
        logging.getLogger("studio.api").info("filler", extra={"n": n, "pad": "x" * 40})
    files = sorted(p.name for p in (tmp_path / "logs").iterdir())
    assert files == ["studio.log", "studio.log.1", "studio.log.2"], files
    assert all(p.stat().st_size <= 4000 + 400 for p in (tmp_path / "logs").iterdir())


def test_configuring_again_replaces_and_closes_the_handlers(tmp_path):
    configure_logging("INFO", log_dir=tmp_path / "a")
    # only its own handlers: another test may have put a capturing one there
    first = [h for h in logging.getLogger("studio").handlers if getattr(h, "_studio_handler", 0)]
    configure_logging("INFO", log_dir=tmp_path / "b")
    assert all(h not in logging.getLogger("studio").handlers for h in first)
    files = [h for h in first if isinstance(h, logging.FileHandler)]
    assert files and all(h.stream is None for h in files), "the old file is closed"
    logging.getLogger("studio.x").warning("second")
    assert (tmp_path / "b" / "studio.log").read_text(encoding="utf-8").count("second") == 1
    assert "second" not in (
        (tmp_path / "a" / "studio.log").read_text(encoding="utf-8")
        if (tmp_path / "a" / "studio.log").exists()
        else ""
    )


def test_the_log_folder_follows_the_database_unless_set():
    from app.config import Settings

    base = dict(_env_file=None, owner_token=secrets.token_urlsafe(32))
    on_disk = Settings(**base, database_url="sqlite:///E:/elsewhere/var/amn.db")
    assert log_directory(on_disk).as_posix().endswith("elsewhere/var/logs")
    assert log_directory(Settings(**base, database_url="sqlite:///:memory:")) is None
    assert log_directory(Settings(**base, database_url="sqlite://")) is None
    chosen = Settings(**base, log_dir="E:/elsewhere/logs")
    assert log_directory(chosen).as_posix() == "E:/elsewhere/logs"
    assert log_directory(Settings(**base, log_to_file=False)) is None


def test_uvicorns_handshake_line_never_carries_the_key(caplog, tmp_path):
    """uvicorn prints a socket's path with its query on 'uvicorn.error' (websockets_impl.py)."""
    configure_logging("INFO", log_dir=tmp_path)
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    secret = "s3cr3t-owner-key-0123456789"  # pragma: allowlist secret
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]', "127.0.0.1:5123", f"/api/v1/ws?a=1&token={secret}&b=2"
    )
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" %d', "127.0.0.1:5123", f"/office?TOKEN={secret}", 403
    )
    assert secret not in caplog.text
    assert "/api/v1/ws?a=1&token=[ascuns]&b=2" in caplog.text
    for record in caplog.records:
        assert secret not in record.getMessage()


def test_the_url_token_filter_on_its_own():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "GET %s", ("/x?token=abc&y=1",), None
    )
    assert RedactUrlTokens().filter(record) is True
    assert record.getMessage() == "GET /x?token=[ascuns]&y=1"


def test_a_failing_request_logs_its_frames(settings, engine, tmp_path):
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings.log_dir = tmp_path / "logs"
    application = create_app(settings)
    inner = application
    while not hasattr(inner, "router"):
        inner = inner.app

    def boom() -> dict:
        raise RuntimeError(f"secret detail {FAKE_KEY}")

    # ahead of the page's own catch-all routes
    inner.add_api_route("/boom-for-the-log-test", boom)
    inner.router.routes.insert(0, inner.router.routes.pop())

    with TestClient(application) as client:
        assert client.get("/boom-for-the-log-test").status_code == 500
    text = (tmp_path / "logs" / "studio.log").read_text(encoding="utf-8")
    failed = [json.loads(line) for line in text.splitlines() if '"request_failed"' in line]
    assert failed, text
    assert failed[0]["exception"]["class"] == "RuntimeError"
    assert any(":boom" in frame for frame in failed[0]["exception"]["frames"])
    assert FAKE_KEY not in text and "secret detail" not in text
