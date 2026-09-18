"""Ollama HTTP adapter.

Uses the official Ollama REST API:
  GET  /api/tags     -> list models
  POST /api/generate -> text generation (non-streaming)

If Ollama is not running, returns OFFLINE status. A refused connection or a 5xx is asked
again a bounded number of times (`app.providers.retry`) before it is one.
Never fabricates a model response, and never presents a model's private reasoning as one:
generation asks for thinking off, and what comes back in `response` is the whole answer.
"""

from __future__ import annotations

import json as _json
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.economy.prices import PriceLookup, llm_cost_vr
from app.providers.base import GenerateResult, HealthResult, LLMProvider, ModelInfo
from app.providers.retry import call_with_retries

ADAPTER_VERSION = "1.0.0"


class OllamaProvider(LLMProvider):
    ADAPTER_VERSION = ADAPTER_VERSION

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        api_key: str | None = None,
        price_lookup: PriceLookup | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        #: The Owner's prices for this kind (`app.economy.prices.price_lookup`). A local
        #: model has none and costs nothing; a cloud model served through this endpoint
        #: costs what the Owner typed, and None — never zero — until he has.
        self.price_lookup = price_lookup

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _open(self, req: Request, timeout: int, *, repeatable: bool) -> dict:
        """One request with the studio's retry policy; `urlopen` is looked up here so the
        tests keep replacing it."""

        def once() -> dict:
            with urlopen(req, timeout=timeout) as resp:
                return _json.loads(resp.read())

        return call_with_retries(
            once,
            repeatable=repeatable,
            what=f"ollama {req.get_method()} {req.selector.split('?', 1)[0]}",
        )

    def _get(self, path: str, timeout: int = 10) -> dict:
        url = f"{self.base_url}{path}"
        req = Request(url, method="GET", headers=self._get_headers())
        return self._open(req, timeout, repeatable=True)

    def _post(self, path: str, body: dict, timeout: int = 600, *, repeatable: bool) -> dict:
        url = f"{self.base_url}{path}"
        data = _json.dumps(body).encode()
        req = Request(
            url,
            data=data,
            method="POST",
            headers=self._get_headers(),
        )
        return self._open(req, timeout, repeatable=repeatable)

    async def health_check(self) -> HealthResult:
        t0 = time.perf_counter()
        try:
            self._get("/api/tags", timeout=5)
            latency = (time.perf_counter() - t0) * 1000
            return HealthResult(status="HEALTHY", latency_ms=round(latency, 1))
        except (URLError, OSError) as exc:
            return HealthResult(status="OFFLINE", detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            return HealthResult(status="UNKNOWN", detail=str(exc))

    async def list_models(self) -> list[ModelInfo]:
        """List models from Ollama, supporting both local and cloud models (e.g. :cloud)."""
        data = self._get("/api/tags")
        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            details = m.get("details", {})
            ctx = details.get("parameter_size")
            is_cloud = ":cloud" in name or "cloud" in name.lower()
            note_parts = []
            if ctx:
                note_parts.append(f"parameter_size={ctx}")
            if is_cloud:
                note_parts.append("cloud_model=true")
            listed = m.get("capabilities")
            models.append(
                ModelInfo(
                    model_name=name,
                    context_length=None,
                    is_available=True,
                    notes=", ".join(note_parts),
                    is_cloud=is_cloud,
                    capabilities=(
                        tuple(str(c) for c in listed if isinstance(c, str))
                        if isinstance(listed, list)
                        else ()
                    ),
                )
            )
        return models

    async def show_model(self, model: str) -> dict:
        """Fetch full model metadata from Ollama /api/show."""
        # A read that Ollama serves by POST; asking twice costs nothing.
        return self._post("/api/show", {"name": model}, repeatable=True)

    async def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> GenerateResult:
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            # Thinking off, deliberately. Ollama counts a model's private reasoning against
            # `num_predict`, so a thinking model asked for 700 tokens can spend all 700 on
            # reasoning and return `response: ""` with `done_reason: "length"` — a run that
            # cost tokens and said nothing. Every model on this provider accepts the flag,
            # including those that do not declare the capability. It also matches the rule
            # that no hidden chain-of-thought is required or persisted
            # (../../../docs/architecture/README.md).
            "think": False,
        }
        if system:
            body["system"] = system
        if max_tokens is not None:
            body.setdefault("options", {})["num_predict"] = max_tokens
        if temperature is not None:
            body.setdefault("options", {})["temperature"] = temperature
        if extra:
            body.update(extra)
        # Not repeatable: a generation that timed out may still be running, and on a cloud
        # model the tokens are spent either way. A refusal (429, 5xx) is retried; silence is not.
        data = self._post("/api/generate", body, repeatable=False)
        text = data.get("response", "")
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        # `thinking` is reported by models that reason anyway; it is never the answer and is
        # not stored. Its length is kept so an empty answer can say what happened instead.
        thinking = data.get("thinking") or ""
        return GenerateResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            # From the tokens Ollama counted at the Owner's per-million prices for this
            # model; None without them. 391 cloud runs carried no cost before this.
            cost_vr=llm_cost_vr(self.price_lookup, model, prompt_tokens, completion_tokens),
            raw_response={
                "done_reason": data.get("done_reason"),
                "thinking_chars": len(thinking),
            },
        )
