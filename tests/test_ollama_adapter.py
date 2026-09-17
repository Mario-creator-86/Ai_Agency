"""Unit tests for Ollama adapter using mock HTTP responses.

Real provider tests are skip-marked unless STUDIO_OLLAMA_URL is set.
"""

from __future__ import annotations

import asyncio
import json
import os
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from app.providers.ollama import OllamaProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(body: dict) -> MagicMock:
    """Create a mock HTTP response context manager."""
    m = MagicMock()
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    m.read = MagicMock(return_value=json.dumps(body).encode())
    return m


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_healthy():
    provider = OllamaProvider()
    mock_resp = _make_response({"models": []})
    with patch("app.providers.ollama.urlopen", return_value=mock_resp):
        result = run(provider.health_check())
    assert result.status == "HEALTHY"
    assert result.latency_ms is not None and result.latency_ms >= 0


def test_health_check_offline():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=URLError("Connection refused")):
        result = run(provider.health_check())
    assert result.status == "OFFLINE"
    assert "Connection refused" in result.detail


def test_health_check_unknown_error():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=RuntimeError("unexpected")):
        result = run(provider.health_check())
    assert result.status == "UNKNOWN"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


def test_list_models_parses_response():
    provider = OllamaProvider()
    body = {
        "models": [
            {"name": "llama3.2:latest", "details": {"parameter_size": "3B"}},
            {"name": "phi3:mini", "details": {}},
        ]
    }
    mock_resp = _make_response(body)
    with patch("app.providers.ollama.urlopen", return_value=mock_resp):
        models = run(provider.list_models())
    assert len(models) == 2
    assert models[0].model_name == "llama3.2:latest"
    assert models[0].is_available is True
    assert "3B" in models[0].notes
    assert models[1].notes == ""


def test_list_models_empty():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", return_value=_make_response({"models": []})):
        models = run(provider.list_models())
    assert models == []


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def test_generate_returns_real_text():
    provider = OllamaProvider()
    body = {
        "response": "The sky is blue.",
        "prompt_eval_count": 10,
        "eval_count": 5,
        "done": True,
    }
    mock_resp = _make_response(body)
    with patch("app.providers.ollama.urlopen", return_value=mock_resp):
        result = run(provider.generate("llama3.2:latest", "Why is the sky blue?"))
    assert result.text == "The sky is blue."
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.cost_vr is None  # Ollama is local


def test_generate_with_system_and_options():
    provider = OllamaProvider()
    body = {"response": "ok", "prompt_eval_count": 2, "eval_count": 1, "done": True}
    captured_body = {}

    def fake_urlopen(req, timeout=None):
        import json as _json

        captured_body.update(_json.loads(req.data))
        return _make_response(body)

    with patch("app.providers.ollama.urlopen", side_effect=fake_urlopen):
        run(
            provider.generate(
                "llama3.2:latest",
                "Hello",
                system="You are concise.",
                max_tokens=50,
                temperature=0.7,
            )
        )

    assert captured_body["system"] == "You are concise."
    assert captured_body["options"]["num_predict"] == 50
    assert captured_body["options"]["temperature"] == 0.7
    assert captured_body["stream"] is False


def test_generation_asks_for_thinking_off_so_the_budget_goes_to_the_answer():
    """Ollama counts private reasoning against num_predict; the answer would get none."""
    provider = OllamaProvider()
    captured_body: dict = {}

    def fake_urlopen(req, timeout=None):
        import json as _json

        captured_body.update(_json.loads(req.data))
        return _make_response({"response": "ok", "eval_count": 1, "done": True})

    with patch("app.providers.ollama.urlopen", side_effect=fake_urlopen):
        run(provider.generate("qwen3.5:397b", "Hello", max_tokens=700))

    assert captured_body["think"] is False


def test_an_answer_eaten_by_reasoning_comes_back_empty_and_says_why():
    """What the studio actually saw: eval_count at the cap, no response, done_reason length."""
    provider = OllamaProvider()
    body = {
        "response": "",
        "thinking": "Thinking Process: the user asks..." * 20,
        "done_reason": "length",
        "eval_count": 702,
        "done": True,
    }
    with patch("app.providers.ollama.urlopen", return_value=_make_response(body)):
        result = run(provider.generate("qwen3.5:397b", "Verify this", max_tokens=700))

    assert result.text == ""
    assert result.completion_tokens == 702
    assert result.raw_response["done_reason"] == "length"
    # The reasoning itself is measured, never carried out of the adapter as an answer.
    assert result.raw_response["thinking_chars"] > 0
    assert "thinking" not in result.raw_response


def test_generate_propagates_connection_error():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=URLError("refused")):
        with pytest.raises(URLError):
            run(provider.generate("llama3.2:latest", "test"))


# ---------------------------------------------------------------------------
# Real provider test (skipped unless STUDIO_OLLAMA_URL is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("STUDIO_OLLAMA_URL"),
    reason="Real Ollama not configured (set STUDIO_OLLAMA_URL to enable)",
)
def test_real_ollama_health_and_generate():
    url = os.environ["STUDIO_OLLAMA_URL"]
    provider = OllamaProvider(base_url=url)

    health = run(provider.health_check())
    assert health.status == "HEALTHY", f"Ollama not healthy: {health}"

    models = run(provider.list_models())
    assert len(models) > 0, "No models found in real Ollama"

    model_name = models[0].model_name
    result = run(provider.generate(model_name, "Say hello in one word.", max_tokens=5))
    assert isinstance(result.text, str) and len(result.text) > 0
    assert result.prompt_tokens is not None


# ---------------------------------------------------------------------------
# transient failures are retried (2026-09-17)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch):
    from app.providers import retry

    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    return slept


def _http_error(code: int) -> HTTPError:
    return HTTPError("http://127.0.0.1:11434/api/generate", code, "reason", Message(), None)


def test_a_503_then_200_generates_after_one_retry():
    provider = OllamaProvider()
    body = {"response": "The sky is blue.", "eval_count": 5, "done": True}
    with patch(
        "app.providers.ollama.urlopen", side_effect=[_http_error(503), _make_response(body)]
    ) as urlopen:
        result = run(provider.generate("llama3.2:latest", "Why is the sky blue?"))
    assert result.text == "The sky is blue."
    assert urlopen.call_count == 2


def test_a_400_is_not_retried():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=_http_error(400)) as urlopen:
        with pytest.raises(HTTPError) as excinfo:
            run(provider.generate("llama3.2:latest", "test"))
    assert excinfo.value.code == 400 and urlopen.call_count == 1


def test_after_three_refusals_the_original_error_class_is_raised():
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=URLError("refused")) as urlopen:
        with pytest.raises(URLError):
            run(provider.list_models())
    assert urlopen.call_count == 3


def test_a_generation_that_left_and_timed_out_is_not_sent_again():
    """A cloud model may be answering; a second request would cost the same tokens again."""
    provider = OllamaProvider()
    with patch("app.providers.ollama.urlopen", side_effect=TimeoutError("timed out")) as urlopen:
        with pytest.raises(TimeoutError):
            run(provider.generate("llama3.2:latest", "test"))
    assert urlopen.call_count == 1
