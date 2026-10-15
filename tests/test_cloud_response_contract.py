"""Cloud agency requests use the vendor window and incremental complete responses."""

import asyncio
import io
import json
from uuid import uuid4

import pytest
from app.agents.services import _failure_detail, run_agent_task
from app.integrations.llm import ConfiguredLLM, ProviderHTTPError, ProviderUnreachable
from app.providers.registry import ProviderRegistry
from test_agent_identity import staffed  # noqa: F401


def cloud():
    return ConfiguredLLM("ollama", {"base_url": "https://ollama.com"}, {})


def test_agency_cloud_uses_native_output_without_changing_complete_input(engine, staffed):  # noqa: F811
    calls = []
    adapter = cloud()

    def request(method, path, body=None):
        calls.append(body)
        return {"response": "Complete decision", "done": True, "done_reason": "stop"}

    adapter.request = request
    registry = ProviderRegistry()
    registry.register(staffed["provider_id"], adapter)
    objective = "Complete report. " * 2000 + "FINAL REQUIRED CONDITION"
    result = run_agent_task(
        engine,
        registry,
        staffed["agents"]["Director"].id,
        "director_review",
        objective,
        "cloud-contract-v1",
        str(uuid4()),
        max_tokens=24000,
    )
    assert result["status"] == "SUCCEEDED"
    assert "num_predict" not in calls[0]["options"]
    assert calls[0]["stream"] is True
    assert calls[0]["prompt"] == objective
    limits = result["context_json"]["generation_limits"]
    assert limits["effective_max_tokens"] is None
    assert limits["output_limit_source"] == "provider_native"
    assert limits["requested_max_tokens"] == 24000


class Response:
    def __init__(self, rows, status=200):
        self.status = status
        self.data = io.BytesIO(b"".join(json.dumps(r).encode() + b"\n" for r in rows))

    def getheader(self, name):
        return None

    def read(self, size=-1):
        return self.data.read(size)

    def readline(self, size=-1):
        return self.data.readline(size)


def wire(monkeypatch, response):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            calls.append({"timeout": kwargs["timeout"]})

        def request(self, method, path, body, headers):
            calls[-1]["body"] = json.loads(body)

        def getresponse(self):
            return response

        def close(self):
            calls[-1]["closed"] = True

    monkeypatch.setattr("app.integrations.llm.http.client.HTTPSConnection", Connection)
    return calls


def test_cloud_stream_preserves_every_visible_chunk_and_no_private_reasoning(monkeypatch):
    rows = [
        {"thinking": "PRIVATE REASONING", "response": "First ", "done": False},
        {"response": "last required condition.", "done": False},
        {"done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 11},
    ]
    calls = wire(monkeypatch, Response(rows))
    result = asyncio.run(cloud().generate("vendor-model", "complete prompt", max_tokens=None))
    assert result.text == "First last required condition."
    assert result.prompt_tokens == 9 and result.completion_tokens == 11
    assert result.raw_response["thinking_chars"] == len("PRIVATE REASONING")
    assert "PRIVATE REASONING" not in repr(result)
    assert calls[0]["closed"] is True


def test_stream_ending_without_done_is_unanswered_and_never_retried(monkeypatch):
    calls = wire(monkeypatch, Response([{"response": "unfinished", "done": False}]))
    with pytest.raises(ProviderUnreachable) as raised:
        asyncio.run(cloud().generate("vendor-model", "complete prompt"))
    assert raised.value.unanswered is True
    assert len(calls) == 1 and calls[0]["closed"] is True


@pytest.mark.parametrize(
    "message,reason",
    [
        ("max_tokens must be less than 209715 https://secret.invalid?key=SECRET", "OUTPUT_LIMIT"),
        ("input exceeds context window SECRET", "CONTEXT_LIMIT"),
        ("this model does not support thinking SECRET", "UNSUPPORTED_THINKING"),
    ],
)
def test_bad_request_keeps_safe_cause_without_echoing_vendor_body(monkeypatch, message, reason):
    wire(monkeypatch, Response([{"error": message}], status=400))
    with pytest.raises(ProviderHTTPError) as raised:
        cloud().request("POST", "/api/generate", {"stream": True})
    assert raised.value.reason_code == reason
    words = _failure_detail(raised.value)
    assert "HTTP 400" in words and " — " in words
    assert "SECRET" not in words and "secret.invalid" not in words


def test_explicit_small_connection_test_remains_bounded(monkeypatch):
    calls = []
    adapter = cloud()
    monkeypatch.setattr(
        adapter, "request", lambda method, path, body: calls.append(body) or {"response": "ok"}
    )
    asyncio.run(adapter.generate("vendor-model", "reply ok", max_tokens=32))
    assert calls[0]["options"]["num_predict"] == 32


def test_stream_can_exceed_old_total_body_limit_without_cutting(monkeypatch):
    first = "a" * 2_100_000
    last = "b" * 2_100_000 + "REQUIRED END"
    wire(
        monkeypatch,
        Response(
            [
                {"response": first, "done": False},
                {"response": last, "done": True, "done_reason": "stop"},
            ]
        ),
    )
    result = asyncio.run(cloud().generate("vendor-model", "complete prompt"))
    assert result.text == first + last


def test_socket_timeout_after_send_is_not_retried(monkeypatch):
    class Quiet(Response):
        def readline(self, size=-1):
            raise TimeoutError("https://secret.invalid?key=SECRET")

    calls = wire(monkeypatch, Quiet([]))
    with pytest.raises(ProviderUnreachable) as raised:
        asyncio.run(cloud().generate("vendor-model", "complete prompt"))
    assert raised.value.unanswered is True
    assert len(calls) == 1
    assert "SECRET" not in _failure_detail(raised.value)
