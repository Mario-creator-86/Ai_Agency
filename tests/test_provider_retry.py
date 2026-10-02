"""A transient refusal from a vendor is retried; it does not fail the day.

Before this, no adapter retried anything: one 503, one 429, one reset connection became a
failed scene or a SKIPPED stage, and the daily run counted it as a fault of the studio. The
rule from `docs/architecture/18_AUTOMATION_ORCHESTRATION.md` is bounded exponential backoff
with jitter on network failures, rate limits and transient 5xx, and no retry at all on the
errors that mean the request itself is wrong.

Two things the helper must not do. It must not spend money twice: a billed request whose
answer never came may have been served, so it is not sent again — only a request the vendor
answered "not now" to, or one that never left this machine, is. And it must not hide what
happened: the error that finally surfaces is the vendor's own, with the attempt count on it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from email.message import Message
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest
from app.providers import retry
from app.providers.media_http import MediaProviderError
from app.providers.retry import call_with_retries, is_transient, retry_after_seconds


class Flaky:
    """A callable that fails the way a vendor does, in the order the test says."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("called more often than the test expected")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def refused(status: int, **kwargs: Any) -> MediaProviderError:
    return MediaProviderError(
        f"vendor.test refused the request (HTTP {status})", http_status=status, **kwargs
    )


# --- the helper ---------------------------------------------------------------------------


def test_a_503_then_200_succeeds_with_one_retry():
    slept: list[float] = []
    flaky = Flaky(refused(503), "answer")

    assert call_with_retries(flaky, attempts=3, sleep=slept.append) == "answer"

    assert flaky.calls == 2
    assert len(slept) == 1 and 0.5 <= slept[0] <= 1.0


def test_a_400_is_not_retried():
    slept: list[float] = []
    flaky = Flaky(refused(400))

    with pytest.raises(MediaProviderError) as excinfo:
        call_with_retries(flaky, attempts=3, sleep=slept.append)

    assert flaky.calls == 1 and slept == []
    assert excinfo.value.http_status == 400
    # An error raised on the first attempt is the vendor's message, untouched.
    assert "attempt" not in str(excinfo.value)


@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_no_other_4xx_is_retried(status):
    flaky = Flaky(refused(status))
    with pytest.raises(MediaProviderError):
        call_with_retries(flaky, attempts=3, sleep=lambda _: None)
    assert flaky.calls == 1


def test_after_the_configured_attempts_the_last_error_is_raised_with_the_count():
    slept: list[float] = []
    flaky = Flaky(refused(503), refused(502), refused(503, code="server_busy"))

    with pytest.raises(MediaProviderError) as excinfo:
        call_with_retries(flaky, attempts=3, sleep=slept.append)

    assert flaky.calls == 3 and len(slept) == 2
    # The last error, its own class and its own fields, so callers keep matching on them.
    assert type(excinfo.value) is MediaProviderError
    assert excinfo.value.http_status == 503 and excinfo.value.code == "server_busy"
    assert "3 attempts" in str(excinfo.value)


def test_backoff_doubles_with_jitter_and_is_capped():
    slept: list[float] = []
    flaky = Flaky(refused(503), refused(503), refused(503), refused(503), "late")

    call_with_retries(flaky, attempts=5, base_seconds=1.0, max_seconds=3.0, sleep=slept.append)

    assert len(slept) == 4
    for delay, ceiling in zip(slept, (1.0, 2.0, 3.0, 3.0), strict=True):
        assert ceiling / 2 <= delay <= ceiling


def test_a_retry_after_within_the_cap_is_waited_out_exactly():
    slept: list[float] = []
    flaky = Flaky(refused(429, retry_after=7.0), "answer")

    assert call_with_retries(flaky, attempts=3, max_seconds=30.0, sleep=slept.append) == "answer"

    assert slept == [7.0]


def test_a_retry_after_beyond_the_cap_is_a_refusal_not_a_wait():
    """A vendor asking for ten minutes is not offering a retry; sleeping through the worker's
    lease to find out would be worse than reporting it."""
    slept: list[float] = []
    flaky = Flaky(refused(429, retry_after=600.0), "never")

    with pytest.raises(MediaProviderError) as excinfo:
        call_with_retries(flaky, attempts=3, max_seconds=30.0, sleep=slept.append)

    assert flaky.calls == 1 and slept == []
    assert excinfo.value.http_status == 429


def test_a_failure_before_the_request_left_is_retried_even_for_a_billed_call():
    flaky = Flaky(MediaProviderError("vendor.test could not be reached", unsent=True), "answer")

    assert call_with_retries(flaky, attempts=3, repeatable=False, sleep=lambda _: None) == "answer"
    assert flaky.calls == 2


def test_a_billed_request_that_left_and_got_no_answer_is_not_sent_again():
    """The vendor may have served it. Sending it again is how a scene gets paid for twice."""
    unanswered = MediaProviderError("vendor.test did not answer", unanswered=True)
    flaky = Flaky(unanswered, "answer")

    with pytest.raises(MediaProviderError):
        call_with_retries(flaky, attempts=3, repeatable=False, sleep=lambda _: None)
    assert flaky.calls == 1

    # The same silence on a request that can be repeated without consequence is retried.
    flaky = Flaky(MediaProviderError("vendor.test did not answer", unanswered=True), "answer")
    assert call_with_retries(flaky, attempts=3, repeatable=True, sleep=lambda _: None) == "answer"


def test_a_malformed_answer_is_not_a_transient_failure():
    """The vendor answered; asking again would get the same body."""
    assert not is_transient(MediaProviderError("vendor.test returned a malformed response"))


def test_urllib_errors_are_classified_the_same_way():
    def http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
        message = Message()
        for key, value in (headers or {}).items():
            message[key] = value
        return HTTPError("https://vendor.test/x", code, "reason", message, None)

    assert is_transient(http_error(503))
    assert is_transient(http_error(429))
    assert not is_transient(http_error(404))
    assert not is_transient(http_error(308)), "a resumable-upload checkpoint is not an error"
    # The request never left: a refused connection, a DNS miss.
    assert is_transient(URLError("Connection refused"), repeatable=False)
    # The request left and the socket went quiet: only safe when repeating is safe.
    assert is_transient(TimeoutError("timed out"), repeatable=True)
    assert not is_transient(TimeoutError("timed out"), repeatable=False)
    assert retry_after_seconds(http_error(429, {"Retry-After": "12"})) == 12.0
    assert retry_after_seconds(http_error(503)) is None
    assert not is_transient(ValueError("not a transport error"))


def test_retry_after_parses_seconds_and_http_dates(monkeypatch):
    assert retry_after_seconds(refused(429, retry_after=3.0)) == 3.0
    assert retry.parse_retry_after("5") == 5.0
    assert retry.parse_retry_after(" 0 ") == 0.0
    assert retry.parse_retry_after("-4") == 0.0
    assert retry.parse_retry_after("soon") is None
    assert retry.parse_retry_after(None) is None
    monkeypatch.setattr(retry, "_now_timestamp", lambda: 1_700_000_000.0)
    # RFC 7231 date form: 90 seconds after the pinned "now" (2023-11-14 22:13:20 GMT).
    assert retry.parse_retry_after("Tue, 14 Nov 2023 22:14:50 GMT") == 90.0
    # A date already in the past means "now", not a negative wait.
    assert retry.parse_retry_after("Tue, 14 Nov 2023 22:00:00 GMT") == 0.0


def test_each_retry_is_logged_with_the_attempt_and_never_the_error_text(caplog):
    """The vendor's error body can carry request details; the log gets numbers and a class."""
    flaky = Flaky(refused(503, code="server_busy"), "answer")
    with caplog.at_level(logging.WARNING, logger="studio.providers.retry"):
        call_with_retries(flaky, attempts=3, sleep=lambda _: None, what="vendor.test GET /x")
    records = [r for r in caplog.records if r.getMessage() == "provider_retry"]
    assert len(records) == 1
    record = records[0]
    assert record.what == "vendor.test GET /x"
    assert (record.attempt, record.attempts, record.http_status) == (1, 3, 503)
    assert record.error == "MediaProviderError"
    assert "refused the request" not in str(record.__dict__)


def test_defaults_come_from_settings_when_the_studio_has_them(monkeypatch):
    monkeypatch.setattr(
        retry,
        "_settings",
        lambda: SimpleNamespace(provider_retry_attempts=2, provider_retry_max_seconds=5),
    )
    slept: list[float] = []
    flaky = Flaky(refused(503), refused(503), "never")
    with pytest.raises(MediaProviderError) as excinfo:
        call_with_retries(flaky, sleep=slept.append)
    assert flaky.calls == 2 and "2 attempts" in str(excinfo.value)

    # And the cap: a Retry-After of 6 is beyond a cap of 5, so it is refused at once.
    flaky = Flaky(refused(429, retry_after=6.0), "never")
    with pytest.raises(MediaProviderError):
        call_with_retries(flaky, sleep=slept.append)
    assert flaky.calls == 1


def test_without_settings_the_defaults_are_three_attempts_and_thirty_seconds(monkeypatch):
    monkeypatch.setattr(retry, "_settings", lambda: None)
    assert retry.retry_defaults() == (3, 30.0)


def test_the_module_sleep_is_used_when_none_is_injected(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    assert call_with_retries(Flaky(refused(503), "answer"), attempts=2) == "answer"
    assert len(slept) == 1


# --- Runway: the adapter with the most calls per scene ------------------------------------


class Recorder:
    """Stands in for the network, and remembers exactly what was asked of it."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self,
        host: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None = None,
        *,
        timeout: float = 120,
        expect_json: bool = True,
    ) -> Any:
        self.calls.append((host, method, path))
        if not self.responses:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    return slept


def runway_video(monkeypatch, recorder):
    from app.providers import runway

    monkeypatch.setattr(runway, "request", recorder)
    return runway.RunwayVideoAdapter(
        "key",
        model="test-video",
        model_metadata={
            "tasks": ["text_to_video"],
            "ratios": {"text_to_video": ["720:1280"]},
            "durations": {"text_to_video": [5, 10]},
        },
    )


def test_runway_submit_survives_a_503_and_records_the_estimate_once(monkeypatch):
    recorder = Recorder(
        MediaProviderError("api.dev.runwayml.com refused the request (HTTP 503)", http_status=503),
        # The contract's shape: an object carrying the credits, not a bare number.
        ({"id": "task-1", "estimatedCost": {"credits": 25}}, b"", "application/json"),
    )
    adapter = runway_video(monkeypatch, recorder)

    job_id = asyncio.run(adapter.create_generation("a comet over the sea"))

    assert job_id == "task-1"
    assert [c[1:] for c in recorder.calls] == [("POST", "/v1/text_to_video")] * 2
    assert adapter.last_estimated_credits == 25.0


def test_runway_submit_that_left_and_got_no_answer_is_not_sent_again(monkeypatch):
    """A task may have been created and billed; a second one would be a second charge."""
    recorder = Recorder(
        MediaProviderError("api.dev.runwayml.com did not answer", unanswered=True),
        ({"id": "task-2", "estimatedCost": {"credits": 25}}, b"", "application/json"),
    )
    adapter = runway_video(monkeypatch, recorder)

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.create_generation("a comet over the sea"))

    assert len(recorder.calls) == 1
    assert adapter.last_estimated_credits is None


def test_runway_estimate_is_read_from_the_contracts_credits_object(monkeypatch):
    """Runway states `estimatedCost` as {"credits": n}. Read as a bare number only, the
    Nepal film's price was dropped and the books showed 0.74 USD for two whole films."""
    recorder = Recorder(({"id": "t", "estimatedCost": {"credits": 340}}, b"", "application/json"))
    adapter = runway_video(monkeypatch, recorder)

    asyncio.run(adapter.create_generation("a comet over the sea"))

    assert adapter.last_estimated_credits == 340.0


def test_runway_estimate_as_a_bare_number_is_still_read(monkeypatch):
    recorder = Recorder(({"id": "t", "estimatedCost": 25}, b"", "application/json"))
    adapter = runway_video(monkeypatch, recorder)

    asyncio.run(adapter.create_generation("a comet over the sea"))

    assert adapter.last_estimated_credits == 25.0


def test_runway_missing_estimate_stays_unknown_and_is_never_the_last_tasks(monkeypatch):
    """No figure is None, never 0, and never the previous shot's price carried over."""
    recorder = Recorder(
        ({"id": "t1", "estimatedCost": {"credits": 340}}, b"", "application/json"),
        ({"id": "t2"}, b"", "application/json"),
        ({"id": "t3", "estimatedCost": {"credits": "a lot"}}, b"", "application/json"),
    )
    adapter = runway_video(monkeypatch, recorder)

    asyncio.run(adapter.create_generation("first shot"))
    assert adapter.last_estimated_credits == 340.0
    asyncio.run(adapter.create_generation("second shot"))
    assert adapter.last_estimated_credits is None
    asyncio.run(adapter.create_generation("third shot"))
    assert adapter.last_estimated_credits is None


def test_runway_estimate_is_read_from_the_task_while_it_is_pending(monkeypatch):
    """The submit answer may omit the price; the task itself states it while it waits."""
    recorder = Recorder(
        ({"id": "task-9"}, b"", "application/json"),
        (
            {"id": "task-9", "status": "PENDING", "estimatedCost": {"credits": 68}},
            b"",
            "application/json",
        ),
        # A poll of some other, older task does not overwrite the price of this one.
        (
            {"id": "task-old", "status": "PENDING", "estimatedCost": {"credits": 999}},
            b"",
            "application/json",
        ),
    )
    adapter = runway_video(monkeypatch, recorder)

    job_id = asyncio.run(adapter.create_generation("a comet over the sea"))
    assert adapter.last_estimated_credits is None
    status = asyncio.run(adapter.get_generation_status(job_id))
    assert status.status == "PENDING"
    assert adapter.last_estimated_credits == 68.0
    asyncio.run(adapter.get_generation_status("task-old"))
    assert adapter.last_estimated_credits == 68.0


def test_runway_rejects_a_400_without_asking_again(monkeypatch):
    recorder = Recorder(
        MediaProviderError("api.dev.runwayml.com refused the request (HTTP 400)", http_status=400)
    )
    adapter = runway_video(monkeypatch, recorder)

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.create_generation("a comet over the sea"))

    assert len(recorder.calls) == 1 and excinfo.value.http_status == 400


def test_runway_polling_honours_retry_after_on_a_rate_limit(monkeypatch, instant_retries):
    recorder = Recorder(
        MediaProviderError(
            "api.dev.runwayml.com refused the request (HTTP 429)",
            http_status=429,
            retry_after=4.0,
        ),
        ({"id": "task-1", "status": "RUNNING"}, b"", "application/json"),
    )
    adapter = runway_video(monkeypatch, recorder)

    status = asyncio.run(adapter.get_generation_status("task-1"))

    assert status.status == "PROCESSING"
    assert instant_retries == [4.0]
    assert [c[1:] for c in recorder.calls] == [("GET", "/v1/tasks/task-1")] * 2


def test_runway_after_three_refusals_raises_its_own_error_with_the_count(monkeypatch):
    recorder = Recorder(
        *[
            MediaProviderError(
                "api.dev.runwayml.com refused the request (HTTP 503)", http_status=503
            )
            for _ in range(3)
        ]
    )
    adapter = runway_video(monkeypatch, recorder)

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.get_generation_status("task-1"))

    assert len(recorder.calls) == 3
    assert excinfo.value.http_status == 503 and "3 attempts" in str(excinfo.value)


# --- YouTube: the adapter that must reconcile before it repeats a side effect -------------


def _response(body: dict, headers: dict[str, str] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read = MagicMock(return_value=json.dumps(body).encode())
    resp.headers = headers or {}
    return resp


def _http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError("https://www.googleapis.com/x", code, "reason", message, None)


def youtube_provider(monkeypatch, outcomes: list[Any]):
    from app.providers.youtube import YouTubeProvider

    provider = YouTubeProvider(
        client_id="client",
        client_secret="secret",  # pragma: allowlist secret
        refresh_token="refresh",
        channel_id="UC_test",
    )
    monkeypatch.setattr(provider, "_get_access_token", lambda: "token")
    calls: list[str] = []

    def urlopen(req: Any, timeout: float | None = None) -> Any:
        calls.append(req.get_method())
        if not outcomes:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("app.providers.youtube.urlopen", urlopen)
    return provider, calls


def test_youtube_status_query_survives_a_503(monkeypatch):
    provider, calls = youtube_provider(
        monkeypatch,
        [_http_error(503), _response({"items": [{"status": {"privacyStatus": "private"}}]})],
    )

    status = asyncio.run(provider.get_video_status("vid"))

    assert status.exists is True and status.privacy_status == "private"
    assert calls == ["GET", "GET"]


def test_youtube_does_not_repeat_a_request_google_called_invalid(monkeypatch):
    from app.providers.publishing_base import RemoteStateUnavailable

    provider, calls = youtube_provider(monkeypatch, [_http_error(400)])

    with pytest.raises(RemoteStateUnavailable):
        asyncio.run(provider.get_video_status("vid"))

    assert calls == ["GET"]


def test_youtube_token_refresh_gives_up_after_the_configured_attempts(monkeypatch):
    from app.providers.youtube import YouTubeProvider

    provider = YouTubeProvider(
        client_id="client",
        client_secret="secret",  # pragma: allowlist secret
        refresh_token="refresh",
    )
    outcomes: list[Any] = [_http_error(502), _http_error(503), _http_error(500)]
    calls: list[str] = []

    def urlopen(req: Any, timeout: float | None = None) -> Any:
        calls.append(req.get_method())
        raise outcomes.pop(0)

    monkeypatch.setattr("app.providers.youtube.urlopen", urlopen)

    with pytest.raises(HTTPError) as excinfo:
        provider._get_access_token()

    assert calls == ["POST"] * 3
    assert excinfo.value.code == 500
    assert any("3 attempts" in note for note in getattr(excinfo.value, "__notes__", []))


def test_youtube_resumable_checkpoint_is_still_a_checkpoint_not_a_retry(monkeypatch, tmp_path):
    """Google answers 308 to every accepted chunk; the retry must leave that to the uploader."""
    video = tmp_path / "film.mp4"
    video.write_bytes(b"x" * 20)
    checkpoint = _http_error(308, {"Range": "bytes=0-9"})
    provider, calls = youtube_provider(
        monkeypatch,
        [
            _response({}, {"Location": "https://www.googleapis.com/upload/session"}),
            checkpoint,
            _response({"id": "vid-1"}),
        ],
    )
    monkeypatch.setattr("app.providers.youtube.UPLOAD_CHUNK_BYTES", 10)

    result = asyncio.run(
        provider.upload_video(video, title="t", description="d", tags=[], privacy_status="private")
    )

    assert result.status == "CONFIRMED" and result.remote_video_id == "vid-1"
    assert calls == ["POST", "PUT", "PUT"]


# --- a billed request is resent only on the statuses the vendor calls safe ----------------
#
# Runway's error page (https://docs.dev.runwayml.com/errors/errors/, read 2026-10-01) lists
# 429, 502, 503 and 504 as "May retry" and no other status. A 500 answered after the vendor
# created the task is a task that exists and is billed; sending the POST again buys it twice.


def test_a_billed_request_answered_500_is_sent_once():
    flaky = Flaky(refused(500), "a second purchase")

    with pytest.raises(MediaProviderError) as excinfo:
        call_with_retries(flaky, attempts=3, repeatable=False, sleep=lambda _: None)

    assert flaky.calls == 1
    assert excinfo.value.http_status == 500


@pytest.mark.parametrize("status", [500, 501, 505, 520, 599])
def test_no_unlisted_5xx_resends_a_billed_request(status):
    flaky = Flaky(refused(status), "never")
    with pytest.raises(MediaProviderError):
        call_with_retries(flaky, attempts=3, repeatable=False, sleep=lambda _: None)
    assert flaky.calls == 1
    assert not is_transient(refused(status), repeatable=False)


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_the_statuses_the_vendor_calls_safe_are_retried_even_for_a_billed_request(status):
    flaky = Flaky(refused(status), "answer")
    assert call_with_retries(flaky, attempts=3, repeatable=False, sleep=lambda _: None) == "answer"
    assert flaky.calls == 2


def test_a_read_answered_500_is_still_retried():
    """A GET buys nothing: asking again after a 500 costs nothing."""
    flaky = Flaky(refused(500), "answer")
    assert call_with_retries(flaky, attempts=3, repeatable=True, sleep=lambda _: None) == "answer"
    assert flaky.calls == 2


def test_media_http_marks_an_unlisted_5xx_as_possibly_served(monkeypatch):
    """The transport says what a 500 means for money: the request may have been served."""
    from app.providers import media_http

    class Answer:
        status = 500
        headers = SimpleNamespace(get_content_type=lambda: "application/json")

        def read(self, _limit):
            return b'{"error": "internal"}'

        def getheader(self, _name):
            return None

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return Answer()

        def close(self):
            return None

    monkeypatch.setattr(media_http.http.client, "HTTPSConnection", Connection)
    with pytest.raises(MediaProviderError) as excinfo:
        media_http.request("vendor.test", "POST", "/v1/buy", {}, b"{}")
    assert excinfo.value.http_status == 500 and excinfo.value.unanswered is True

    Answer.status = 503
    with pytest.raises(MediaProviderError) as excinfo:
        media_http.request("vendor.test", "POST", "/v1/buy", {}, b"{}")
    assert excinfo.value.http_status == 503 and excinfo.value.unanswered is False


def test_a_runway_submit_answered_500_is_not_sent_again(monkeypatch):
    recorder = Recorder(
        MediaProviderError(
            "api.dev.runwayml.com refused the request (HTTP 500)", http_status=500, unanswered=True
        ),
        ({"id": "task-2", "estimatedCost": {"credits": 25}}, b"", "application/json"),
    )
    adapter = runway_video(monkeypatch, recorder)

    with pytest.raises(MediaProviderError) as excinfo:
        asyncio.run(adapter.create_generation("a comet over the sea"))

    assert len(recorder.calls) == 1
    assert excinfo.value.http_status == 500


# --- the configured LLM: a generation is a purchase too ------------------------------------


class LLMConnection:
    """`http.client` for ConfiguredLLM, scripted: each entry is a status, or an exception."""

    script: list[Any] = []
    sent: list[tuple[str, str]] = []

    def __init__(self, *_args, **_kwargs):
        pass

    def request(self, method, path, *_args, **_kwargs):
        LLMConnection.sent.append((method, path))

    def getresponse(self):
        status = LLMConnection.script.pop(0)
        body = json.dumps({"response": "ok", "choices": [{"message": {"content": "ok"}}]})

        class Answer:
            def __init__(self) -> None:
                self.status = status

            def getheader(self, _name):
                return None

            def read(self, _limit):
                return body.encode()

        return Answer()

    def close(self):
        return None


def llm(monkeypatch, *statuses: int):
    import http.client

    from app.integrations.llm import ConfiguredLLM

    LLMConnection.script = list(statuses)
    LLMConnection.sent = []
    monkeypatch.setattr(http.client, "HTTPSConnection", LLMConnection)
    monkeypatch.setattr(http.client, "HTTPConnection", LLMConnection)
    return ConfiguredLLM("openai", {}, {"api_key": "sk-test"})  # pragma: allowlist secret


def test_an_llm_generation_answered_500_is_sent_once(monkeypatch):
    from app.integrations.llm import ProviderHTTPError

    model = llm(monkeypatch, 500, 200)
    with pytest.raises(ProviderHTTPError) as excinfo:
        model.request("POST", "/chat/completions", {"model": "m"})
    assert LLMConnection.sent == [("POST", "/v1/chat/completions")]
    assert excinfo.value.http_status == 500 and excinfo.value.unanswered is True


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_an_llm_generation_refused_for_now_is_asked_again(monkeypatch, status):
    model = llm(monkeypatch, status, 200)
    assert model.request("POST", "/chat/completions", {"model": "m"})["response"] == "ok"
    assert len(LLMConnection.sent) == 2


def test_an_llm_read_answered_500_is_asked_again(monkeypatch):
    model = llm(monkeypatch, 500, 200)
    assert model.request("GET", "/models")["response"] == "ok"
    assert LLMConnection.sent == [("GET", "/v1/models")] * 2
