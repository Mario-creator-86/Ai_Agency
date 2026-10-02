"""The studio's logs: one JSON object per line, kept whole and kept safe (REL-05, SEC-07).

Every extra a call passes is written, not four chosen ones: the ``reason`` and ``error`` extras
are what makes a line worth reading. What could be a credential never is: a key that names a
secret (token, secret, key, authorization, password, cookie, credential) has its value blanked,
every other text value passes through the vendor-text sanitiser (`sanitise_vendor_text`: URLs,
bearer values, key-shaped tokens and long opaque runs cut) and is truncated. Identifiers and
paths are kept as they are, because the sanitiser would cut a UUID as an opaque run. A traceback
is written as its class and its frames (file:line:function), never its message or its locals:
an exception's text is where a vendor's echo of a key, a database row or a URL turns up.

Three namespaces are configured, ``studio``, ``amn`` and ``app`` (modules logging under their
own ``__name__``), to the console and to a rotating file beside the database
(`log_directory`). uvicorn's own loggers get `RedactUrlTokens`, which blanks every ``token=``
value of a line: uvicorn prints a WebSocket handshake with its path and query (SEC-02).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from app.providers.media_http import sanitise_vendor_text

if TYPE_CHECKING:
    from app.config import Settings

#: What a blanked value reads.
REDACTED = "[ascuns]"
#: The longest text value a line keeps, in characters.
MAX_VALUE_CHARS = 2000
#: The most frames of a traceback a line keeps (the innermost ones).
MAX_FRAMES = 30
#: The namespaces the studio's modules log under.
NAMESPACES = ("studio", "amn", "app")
#: uvicorn's loggers, whose lines can carry a URL with its query.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
LOG_FILE_NAME = "studio.log"

#: A key whose value is never written.
_SECRET_KEY = re.compile(r"token|secret|key|authori[sz]ation|passw(?:or)?d|cookie|credential", re.I)
#: A key whose value is an identifier or a path: kept as it is (control characters cut).
_PLAIN_KEY = re.compile(r"(?:^|_)(?:ids?|path|paths|lock|file|folder|dir|logger)$", re.I)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
#: The value of every ``token=`` in a URL-ish text, whatever the case.
_URL_TOKEN = re.compile(r"(?i)([?&;]token=)[^&#\s'\"`]*")

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}
_ROOT = Path(__file__).resolve().parents[2]


def redact_url_tokens(text: str) -> str:
    """Every ``token=`` value of a text blanked: ``?token=abc&x=1`` → ``?token=[ascuns]&x=1``."""
    return _URL_TOKEN.sub(lambda m: m.group(1) + REDACTED, text)


class RedactUrlTokens(logging.Filter):
    """Blanks every ``token=`` value of a record's message, then lets the record through."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed record is the handler's to report
            return True
        if "token=" in message.lower():
            record.msg, record.args = redact_url_tokens(message), None
        return True


#: The only paths the studio serves sockets on (workflows/router.py, office/stream.py).
STUDIO_SOCKET_PATHS = frozenset({"/api/v1/ws", "/api/v1/office/stream/signalling"})
#: How long after a stranger's refused handshake the websockets library's own
#: "connection rejected" line that follows it is still taken as that handshake's.
_REJECTION_FOLLOWS_S = 2.0


class QuietStrangerSockets(logging.Filter):
    """Drops uvicorn's lines for a refused WebSocket on a path the studio does not serve.

    Another program's page that once ran on the same port knocks on ``ws://…:8000/ws`` every
    few seconds (the Owner's console, 2026-10-02). The page's files refuse it (main.PageFiles),
    and each knock wrote '"WebSocket /ws" 403' and 'connection rejected (403 Forbidden)': not
    the studio's error, so not the console's business. A handshake on one of the studio's own
    socket paths, refused or not, is written as before, and so is every other line.
    """

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._dropped_at = float("-inf")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.msg if isinstance(record.msg, str) else ""
        args = record.args if isinstance(record.args, tuple) else ()
        if message.startswith('%s - "WebSocket %s"') and len(args) >= 2:
            path = str(args[1]).split("?", 1)[0]
            if path not in STUDIO_SOCKET_PATHS and not message.endswith("[accepted]"):
                self._dropped_at = time.monotonic()
                return False
            return True
        if message == "connection rejected (%d %s)" and args and args[0] in (403, 404):
            if time.monotonic() - self._dropped_at < _REJECTION_FOLLOWS_S:
                self._dropped_at = float("-inf")
                return False
        return True


def _safe_value(key: str, value: Any, depth: int = 0) -> Any:
    if _SECRET_KEY.search(key) and value is not None:
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if depth > 4:
        return sanitise_vendor_text(value, MAX_VALUE_CHARS)
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list | tuple | set | frozenset):
        return [_safe_value(key, item, depth + 1) for item in list(value)[:100]]
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str) and _PLAIN_KEY.search(key):
        return _CONTROL.sub(" ", value)[:MAX_VALUE_CHARS]
    return sanitise_vendor_text(value, MAX_VALUE_CHARS)


def _where(filename: str) -> str:
    path = Path(filename)
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except (ValueError, OSError):
        pass
    parts = path.as_posix().split("/site-packages/", 1)
    return parts[1] if len(parts) == 2 else path.name


def _exception_name(exc_type: type[BaseException]) -> str:
    module = exc_type.__module__
    name = exc_type.__qualname__
    return name if module in ("builtins", "__main__") else f"{module}.{name}"


def render_exception(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> dict[str, Any]:
    """An exception as its class, its frames and its cause's class: never its text or locals."""
    exc_type, exc, tb = exc_info
    frames = [
        f"{_where(frame.filename)}:{frame.lineno}:{frame.name}"
        for frame in traceback.extract_tb(tb)[-MAX_FRAMES:]
    ]
    rendered: dict[str, Any] = {"class": _exception_name(exc_type), "frames": frames}
    cause = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    if cause is not None:
        rendered["cause"] = _exception_name(type(cause))
    return rendered


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_url_tokens(_CONTROL.sub(" ", record.getMessage())),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD or key.startswith("_") or key in line:
                continue
            line[key] = _safe_value(key, value)
        exc_info = record.exc_info
        if exc_info and exc_info[0] is not None and exc_info[1] is not None:
            line["exception"] = render_exception(exc_info)  # type: ignore[arg-type]
        return json.dumps(line, ensure_ascii=False, default=str)


def log_directory(settings: Settings) -> Path | None:
    """Where the log file goes: STUDIO_LOG_DIR, else a ``logs`` folder beside the database
    file (``data/logs`` for the studio's own); None when file logging is off or the database
    is not a file (an in-memory database has no folder to sit beside)."""
    if not getattr(settings, "log_to_file", True):
        return None
    chosen = getattr(settings, "log_dir", None)
    if chosen:
        return Path(chosen)
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    try:
        url = make_url(settings.database_url)
    except Exception:  # noqa: BLE001 - an unreadable URL fails at the engine, not here
        return None
    database = url.database
    if not url.drivername.startswith("sqlite") or not database or database == ":memory:":
        return None
    return Path(database).parent / "logs"


def _studio_handler(handler: logging.Handler) -> logging.Handler:
    handler._studio_handler = True  # type: ignore[attr-defined]
    return handler


def configure_logging(
    level: str,
    *,
    log_dir: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 10,
    console_level: str | None = None,
) -> Path | None:
    """The studio's namespaces to the console (at ``console_level``, else ``level``) and, with
    ``log_dir``, to ``<log_dir>/studio.log`` rotated at ``max_bytes`` with ``backups`` kept.
    Called again (the next app in this process), it closes the handlers it put there before.
    Returns the log file, or None when there is none."""
    formatter = JsonFormatter()
    console = _studio_handler(logging.StreamHandler())
    console.setFormatter(formatter)
    console.setLevel(console_level or level)
    handlers: list[logging.Handler] = [console]
    log_file: Path | None = None
    if log_dir is not None:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            log_file = Path(log_dir) / LOG_FILE_NAME
            rotating = _studio_handler(
                logging.handlers.RotatingFileHandler(
                    log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
                )
            )
            rotating.setFormatter(formatter)
            handlers.append(rotating)
        except OSError as exc:
            log_file = None
            print(  # noqa: T201 - logging is what failed; the console is what is left
                json.dumps(
                    {
                        "level": "WARNING",
                        "message": "log_file_unavailable",
                        "error_class": type(exc).__name__,
                    }
                )
            )
    closed: set[int] = set()
    for name in NAMESPACES:
        logger = logging.getLogger(name)
        for old in list(logger.handlers):
            if getattr(old, "_studio_handler", False):
                logger.removeHandler(old)
                if id(old) not in closed:
                    closed.add(id(old))
                    old.close()
        for handler in handlers:
            logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, QuietStrangerSockets) for f in logger.filters):
            logger.addFilter(QuietStrangerSockets())
        if not any(isinstance(f, RedactUrlTokens) for f in logger.filters):
            logger.addFilter(RedactUrlTokens())
    return log_file
