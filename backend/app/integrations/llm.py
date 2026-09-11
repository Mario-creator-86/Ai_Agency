"""Configured LLM adapter; bounded responses and no credential-bearing redirects.

This is the adapter behind every connection made in Settings — the Owner's Ollama Cloud
included — not `app.providers.ollama`, which serves only the seeded local endpoint. Anything
that must hold for the studio's real runs belongs here first.

Ollama generation asks for thinking off. Ollama counts a model's private reasoning against
`num_predict`, so a thinking model asked for 700 tokens could spend all 700 reasoning and
return an empty `response` — seventeen of eighteen fact-checks did exactly that, recorded
as successes with nothing under them. The whole budget now goes to the answer, and the
response's `done_reason` travels back so an empty answer can say why.
"""

import asyncio
import http.client
import json
from typing import Any
from urllib.parse import urlsplit

from app.providers.base import GenerateResult, HealthResult, LLMProvider, ModelInfo

BASE_URLS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1"}

#: How long one generation may take. The daily run's worker lease is an hour; an answer that
#: needs ten minutes is slow, not broken.
REQUEST_TIMEOUT_SECONDS = 600


class ConfiguredLLM(LLMProvider):
    ADAPTER_VERSION = "1.0.0"

    def __init__(self, kind: str, config: dict, secrets: dict) -> None:
        self.kind = kind
        self.base_url = BASE_URLS.get(kind, config.get("base_url", "")).rstrip("/")
        self.key = secrets.get("api_key", "")

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        parsed = urlsplit(self.base_url)
        cls = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        # A cloud model writing several thousand tokens takes minutes, not seconds; a
        # thirty-second socket timeout turned long, good answers into "time-out" failures.
        connection = cls(parsed.hostname, parsed.port, timeout=REQUEST_TIMEOUT_SECONDS)
        headers = {"Content-Type": "application/json"}
        if self.kind == "anthropic":
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        elif self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        try:
            connection.request(
                method, parsed.path + path, json.dumps(body) if body is not None else None, headers
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f"Provider request failed (HTTP {response.status})")
            data = response.read(4_000_001)
            if len(data) > 4_000_000:
                raise ValueError("Provider response exceeds limit")
            return json.loads(data)
        finally:
            connection.close()

    async def health_check(self) -> HealthResult:
        try:
            await self.list_models()
            return HealthResult("HEALTHY")
        except Exception:
            return HealthResult("OFFLINE", "Connection or authentication could not be verified")

    async def list_models(self) -> list[ModelInfo]:
        path = "/api/tags" if self.kind == "ollama" else "/models"
        data = await asyncio.to_thread(self.request, "GET", path)
        items = data.get("models", []) if self.kind == "ollama" else data.get("data", [])
        return [ModelInfo(item.get("name") or item["id"], None, True) for item in items]

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
        body: dict[str, Any] = {"model": model}
        if self.kind == "ollama":
            body.update(prompt=prompt, stream=False, think=False)
            if system:
                body["system"] = system
            options: dict[str, Any] = {}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            if temperature is not None:
                options["temperature"] = temperature
            body["options"] = options
            if extra:
                body.update(extra)
            data = await asyncio.to_thread(self.request, "POST", "/api/generate", body)
            return GenerateResult(
                data.get("response") or "",
                data.get("prompt_eval_count"),
                data.get("eval_count"),
                None,
                # Never the reasoning itself — only that there was some, and how the call ended.
                raw_response={
                    "done_reason": data.get("done_reason"),
                    "thinking_chars": len(data.get("thinking") or ""),
                },
            )
        messages = [{"role": "user", "content": prompt}]
        if self.kind == "anthropic":
            body["max_tokens"] = max_tokens or 1024
            if system:
                body["system"] = system
        else:
            if system:
                messages.insert(0, {"role": "system", "content": system})
            if max_tokens is not None:
                body["max_completion_tokens" if self.kind == "openai" else "max_tokens"] = (
                    max_tokens
                )
        body["messages"] = messages
        if temperature is not None:
            body["temperature"] = temperature
        path = "/messages" if self.kind == "anthropic" else "/chat/completions"
        data = await asyncio.to_thread(self.request, "POST", path, body)
        usage = data.get("usage", {})
        if self.kind == "anthropic":
            text = "".join(x["text"] for x in data["content"] if x.get("type") == "text")
            return GenerateResult(text, usage.get("input_tokens"), usage.get("output_tokens"), None)
        return GenerateResult(
            data["choices"][0]["message"]["content"],
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            None,
        )
