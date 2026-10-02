"""Bounded retries for the calls the studio makes to its vendors.

Until 2026-09-17 no adapter retried anything: one 503 from the voice vendor, one 429 while
Runway was polled, one connection reset by a proxy became a failed scene or a SKIPPED stage,
and the daily run treated the vendor's bad minute as a fault of the studio. The rule in
`docs/architecture/18_AUTOMATION_ORCHESTRATION.md` is bounded exponential backoff with
jitter on network failures, rate limits and transient 5xx, and no retry at all on the errors
that mean the request itself is wrong (a bad key, a bad body, a missing resource).

What is retried is decided by two questions, not one. The first is the usual one: did the
vendor say "not now" (429, 5xx), or did the request never leave this machine (a refused
connection, a DNS miss)? Those are always safe to send again. The second is asked when the
request left and nothing came back: a read timeout on a billed request — a narration, a still,
a Runway task — may be a request the vendor served, and sending it again is how a scene gets
paid for twice. So a caller says whether its request is `repeatable`; only a repeatable one is
retried after silence. Reads are; purchases are not.

The error that finally surfaces is the vendor's own — same class, same fields — with the
attempt count on it, so the Owner reads "refused (HTTP 503) (after 3 attempts)" and not a
new exception that hides which vendor answered what. Nothing here logs the error text, which
for some vendors echoes the request; only numbers and a class name go to the log.
"""

from __future__ import annotations

import http.client
import logging
import random
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError

logger = logging.getLogger("studio.providers.retry")

DEFAULT_ATTEMPTS = 3
DEFAULT_MAX_SECONDS = 30.0
DEFAULT_BASE_SECONDS = 1.0

#: The statuses after which a billed request may be sent again: the vendor answered "not now"
#: and did not serve it. Runway's error page (https://docs.dev.runwayml.com/errors/errors/,
#: read 2026-10-01) lists exactly 429, 502, 503 and 504 as "May retry"; the studio applies the
#: same narrow list to every vendor it buys from. Any other 5xx on a purchase (a 500 answered
#: after the task was created, say) may be a request the vendor served and billed, so it is
#: never resent: it is reported as possibly charged (`unanswered`).
SAFE_TO_RESEND_STATUSES = frozenset({429, 502, 503, 504})

#: The wait between attempts. A module attribute, not a default argument, so a test can make
#: every adapter's retries instant with one monkeypatch instead of threading a parameter
#: through each call site.
sleep: Callable[[float], None] = time.sleep


@lru_cache(maxsize=1)
def _settings() -> Any:
    """The studio's settings when they can be built here, else None.

    Adapters have no handle on the application; the same shortcut `integrations.autoconfig`
    takes. A studio without a usable `.env` (the test suite) gets the defaults.
    """
    from app.config import Settings  # noqa: PLC0415

    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001
        return None


def retry_defaults() -> tuple[int, float]:
    """(attempts, max_seconds) from Settings when it has them; three and thirty otherwise.

    Read with getattr because the fields (`provider_retry_attempts`,
    `provider_retry_max_seconds`) are the runbook's to add to `app.config`; until they exist
    the defaults here are the studio's policy.
    """
    settings = _settings()
    attempts = getattr(settings, "provider_retry_attempts", DEFAULT_ATTEMPTS)
    max_seconds = getattr(settings, "provider_retry_max_seconds", DEFAULT_MAX_SECONDS)
    try:
        attempts = max(1, int(attempts))
    except (TypeError, ValueError):
        attempts = DEFAULT_ATTEMPTS
    try:
        max_seconds = max(0.0, float(max_seconds))
    except (TypeError, ValueError):
        max_seconds = DEFAULT_MAX_SECONDS
    return attempts, max_seconds


def _now_timestamp() -> float:
    return time.time()


def parse_retry_after(value: str | None) -> float | None:
    """Seconds to wait from a Retry-After header: an integer, or an HTTP date (RFC 7231).

    A date in the past means "now". Anything unreadable is None, and the caller backs off as
    it would without the header, rather than trusting a number it could not parse.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(int(text)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - _now_timestamp())


def _status_of(exc: BaseException) -> int | None:
    if isinstance(exc, HTTPError):
        return int(exc.code)
    status = getattr(exc, "http_status", None)
    return int(status) if isinstance(status, int) else None


def retry_after_seconds(exc: BaseException) -> float | None:
    """The wait the vendor asked for, if the exception carries its response."""
    if isinstance(exc, HTTPError):
        headers = exc.headers
        return parse_retry_after(headers.get("Retry-After") if headers is not None else None)
    value = getattr(exc, "retry_after", None)
    return float(value) if isinstance(value, int | float) else None


def is_transient(exc: BaseException, *, repeatable: bool = True) -> bool:
    """Whether asking again could get a different answer, and is safe to do.

    Retried: 429, 502, 503 and 504 (the vendor answered "not now",
    `SAFE_TO_RESEND_STATUSES`), and a request that never left (`unsent`, `URLError`).
    Retried only when `repeatable`: any other 5xx, and a request that left and got no answer
    (`unanswered`, a bare socket error or timeout, a dropped connection), because the vendor
    may have served it. Never retried: every other 4xx, and an answer that arrived but could
    not be read — asking again would get the same body.
    """
    status = _status_of(exc)
    if status is not None:
        if status in SAFE_TO_RESEND_STATUSES:
            return True
        return repeatable and 500 <= status <= 599
    if getattr(exc, "unsent", False):
        return True
    if getattr(exc, "unanswered", False):
        return repeatable
    if isinstance(exc, HTTPError):
        return False
    if isinstance(exc, URLError):
        # urllib raises URLError only when the request could not be sent; a failure while
        # reading the answer comes through as the socket's own OSError.
        return True
    if isinstance(exc, OSError | http.client.HTTPException):
        return repeatable
    return False


def _annotate(exc: BaseException, attempts: int) -> None:
    """Put the attempt count on the error without changing what it is."""
    note = f"after {attempts} attempts"
    if exc.args and isinstance(exc.args[0], str):
        exc.args = (f"{exc.args[0]} ({note})",) + tuple(exc.args[1:])
    exc.add_note(f"Raised after {attempts} attempts; this is the provider's last answer.")


def call_with_retries[T](
    fn: Callable[[], T],
    *,
    attempts: int | None = None,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    max_seconds: float | None = None,
    repeatable: bool = True,
    retry_on: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
    log: logging.Logger = logger,
    what: str = "",
) -> T:
    """Call `fn` until it returns, giving up after `attempts` tries.

    Between attempts the wait doubles from `base_seconds`, capped at `max_seconds`, with
    jitter in the upper half of the window so a fleet of scenes retrying together does not
    knock on the vendor's door in step. A Retry-After the vendor sent replaces the computed
    wait when it fits under the cap; one that does not fit is a refusal for now, raised at
    once rather than slept through — the worker's lease is an hour, and a ten-minute wait
    inside one scene would spend it.

    `attempts` and `max_seconds` default to the studio's settings. `retry_on` replaces the
    transience test; `repeatable=False` is for a billed request (see `is_transient`).
    `sleep` is injectable so tests are instant; `what` names the call in the log.
    """
    default_attempts, default_max = retry_defaults()
    attempts = attempts if attempts is not None else default_attempts
    max_seconds = max_seconds if max_seconds is not None else default_max
    attempts = max(1, int(attempts))
    wait = sleep if sleep is not None else globals()["sleep"]
    should_retry = (
        retry_on if retry_on is not None else (lambda exc: is_transient(exc, repeatable=repeatable))
    )

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — classified below, re-raised when not ours
            last = attempt == attempts
            if last or not should_retry(exc):
                if attempt > 1:
                    _annotate(exc, attempt)
                raise
            asked = retry_after_seconds(exc)
            if asked is not None and asked > max_seconds:
                # Honouring it would sleep past the cap; not honouring it would be refused
                # again. Either way the vendor is not offering a retry the studio can take.
                _annotate(exc, attempt)
                log.warning(
                    "provider_retry_refused",
                    extra={
                        "what": what,
                        "attempt": attempt,
                        "attempts": attempts,
                        "retry_after": asked,
                        "max_seconds": max_seconds,
                        "http_status": _status_of(exc),
                        "error": type(exc).__name__,
                    },
                )
                raise
            if asked is not None:
                delay = asked
            else:
                ceiling = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
                delay = ceiling / 2 + random.uniform(0, ceiling / 2)  # noqa: S311 — jitter
            log.warning(
                "provider_retry",
                extra={
                    "what": what,
                    "attempt": attempt,
                    "attempts": attempts,
                    "delay": round(delay, 3),
                    "http_status": _status_of(exc),
                    "error": type(exc).__name__,
                },
            )
            wait(delay)
    raise AssertionError("unreachable: every attempt returns or raises")
