"""Configured LLM adapter; bounded responses and no credential-bearing redirects.

This is the adapter behind every connection made in Settings — the Owner's Ollama Cloud
included — not `app.providers.ollama`, which serves only the seeded local endpoint. Anything
that must hold for the studio's real runs belongs here first.

Local Ollama generation asks for thinking off. Ollama counts a model's private reasoning
against `num_predict`, so a thinking model asked for 700 tokens could spend all 700 reasoning
and return an empty `response` — seventeen of eighteen fact-checks did exactly that, recorded
as successes with nothing under them. The whole budget goes to the answer there, and the
response's `done_reason` travels back so an empty answer can say why.

Ollama Cloud is asked nothing about thinking (2026-10-15). It gets no `num_predict` either, so
reasoning cannot starve the answer; and `think: false` was breaking a model: glm-5.3-flash,
told not to think, narrated its reasoning INTO the visible answer — 38,000 to 74,000 tokens of
«Let me work through this carefully…» and no JSON, four episodes in a row, three scripts —
while every model asked natively put its reasoning in the separate `thinking` field and
answered the object (probed on the Owner's account: deepseek-v4-pro, deepseek-v4.1-flash,
glm-5.3-flash, kimi-k3, mistral-large-4; with `format: json` as well). The reasoning is never
returned to a caller; only its length is, as `thinking_chars`. A caller that must say
(`extra={"think": ...}`, `agents.structured`) still can.
"""

import asyncio
import http.client
import json
import time
from typing import Any
from urllib.parse import urlsplit

from app.economy.prices import PriceLookup, llm_cost_vr
from app.providers.base import GenerateResult, HealthResult, LLMProvider, ModelInfo
from app.providers.media_http import _DeadlineGuard
from app.providers.retry import SAFE_TO_RESEND_STATUSES, call_with_retries, parse_retry_after

BASE_URLS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1"}

#: Socket idle timeout. The configurable whole-generation deadline also bounds a stream
#: that remains active without completing an answer.
REQUEST_TIMEOUT_SECONDS = 600


class ProviderHTTPError(ValueError):
    """The provider answered with a status other than 200.

    A ValueError as before, so every caller that catches one still does; the status and the
    vendor's Retry-After ride along so the retry policy can tell "not now" from "never".
    """

    def __init__(
        self,
        http_status: int,
        retry_after: float | None = None,
        *,
        word: str | None = None,
        keyless: bool = False,
        reason_code: str | None = None,
    ) -> None:
        super().__init__(f"Provider request failed (HTTP {http_status})")
        self.http_status = http_status
        self.retry_after = retry_after
        #: The vendor's own one-word code for the refusal («unauthorized», «PERMISSION_DENIED»)
        #: when its body carried one; never the body's message, which can quote the request.
        self.word = word
        self.reason_code = reason_code
        #: The call carried no key of the studio's (the seeded local endpoint): a refused
        #: authorisation is that service's own sign-in, not a key to re-enter in Settings.
        self.keyless = keyless
        #: A 5xx the vendor does not call safe to retry may come after the model wrote (and
        #: billed) the answer: a generation is not asked again on it.
        self.unanswered = 500 <= http_status <= 599 and http_status not in SAFE_TO_RESEND_STATUSES


def refusal_reason(data: Any) -> str | None:
    """Classify a vendor refusal; no quoted message or request enters the record."""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        error = error.get("message") or error.get("code")
    if not isinstance(error, str):
        return None
    text = error.casefold()
    if "num_predict" in text:
        return "OUTPUT_LIMIT"
    if any(
        k in text for k in ("max_tokens", "max_completion_tokens", "num_predict", "output tokens")
    ) and any(
        k in text for k in ("less than", "maximum", "exceed", "too large", "at most", "range")
    ):
        return "OUTPUT_LIMIT"
    if any(k in text for k in ("context window", "context length", "input tokens")) and any(
        k in text for k in ("exceed", "too long", "maximum", "limit")
    ):
        return "CONTEXT_LIMIT"
    if "thinking" in text and any(
        k in text for k in ("does not support", "unsupported", "not supported")
    ):
        return "UNSUPPORTED_THINKING"
    return None


def _read_ollama_stream(response: Any, *, deadline: float | None = None) -> dict[str, Any]:
    """Read complete progress within both socket and whole-generation deadlines."""
    chunks: list[str] = []
    thinking_chars = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise ProviderUnreachable("Provider generation deadline exceeded", unanswered=True)
        line = response.readline(4_000_001)
        if deadline is not None and time.monotonic() >= deadline:
            raise ProviderUnreachable("Provider generation deadline exceeded", unanswered=True)
        if not line:
            raise ProviderUnreachable("Provider stream ended before completion", unanswered=True)
        if len(line) > 4_000_000:
            raise ValueError("Provider response line exceeds limit")
        if not line.strip():
            continue
        part = json.loads(line)
        if not isinstance(part, dict):
            raise ValueError("Provider response has invalid stream shape")
        if part.get("error"):
            raise ProviderUnreachable("Provider stream reported a failure", unanswered=True)
        chunk = part.get("response") or ""
        if not isinstance(chunk, str):
            raise ValueError("Provider response has invalid text shape")
        chunks.append(chunk)
        thinking = part.get("thinking") or ""
        thinking_chars += len(thinking) if isinstance(thinking, str) else 0
        if part.get("done") is True:
            return {
                "response": "".join(chunks),
                "done_reason": part.get("done_reason"),
                "prompt_eval_count": part.get("prompt_eval_count"),
                "eval_count": part.get("eval_count"),
                "thinking_chars": thinking_chars,
            }


class ProviderUnreachable(OSError):
    """The provider could not be reached (`unsent`) or went quiet after the request left
    (`unanswered`). An OSError as before; the phase decides whether it is sent again."""

    def __init__(self, message: str, *, unsent: bool = False, unanswered: bool = False) -> None:
        super().__init__(message)
        self.unsent = unsent
        self.unanswered = unanswered


class ConfiguredLLM(LLMProvider):
    ADAPTER_VERSION = "1.0.0"

    def __init__(
        self,
        kind: str,
        config: dict,
        secrets: dict,
        price_lookup: PriceLookup | None = None,
    ) -> None:
        self.kind = kind
        self.base_url = BASE_URLS.get(kind, config.get("base_url", "")).rstrip("/")
        self.key = secrets.get("api_key", "")
        #: The Owner's per-million-token prices for this kind of connection
        #: (`app.economy.prices.price_lookup`). Every run used to say `cost_vr=None` — 391
        #: Ollama Cloud runs on the live copy with no cost — and the budget could not see
        #: the tokens. With a price for the model, the run carries what it cost; without
        #: one it still says None, never zero.
        self.price_lookup = price_lookup
        from app.config import Settings  # noqa: PLC0415

        settings = Settings()  # type: ignore[call-arg]
        self.generation_deadline_seconds = float(
            config.get(
                "generation_deadline_seconds",
                settings.llm_generation_deadline_seconds,
            )
        )
        if not 0 < self.generation_deadline_seconds <= 3300:
            raise ValueError(
                "Generation deadline must be positive and shorter than the worker lease"
            )

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        """One call to the provider, asked again a bounded number of times on 429, 502, 503,
        504 and a connection that never opened. A generation that left and got no answer, or
        got any other 5xx, is not sent again: the model may have written it, and the tokens
        are billed either way. The one POST that is a read — Ollama's /api/show — may be
        repeated, on any 5xx.
        """
        repeatable = method.upper() != "POST" or path.endswith(("/api/show", "/api/me"))
        return call_with_retries(
            lambda: self._request_once(method, path, body),
            repeatable=repeatable,
            what=f"{self.kind} {method} {path}",
        )

    def _request_once(self, method: str, path: str, body: dict | None = None) -> dict:
        parsed = urlsplit(self.base_url)
        cls = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        # A cloud model writing several thousand tokens takes minutes, not seconds; a
        # thirty-second socket timeout turned long, good answers into "time-out" failures.
        connection = cls(
            parsed.hostname,
            parsed.port,
            timeout=20 if path == "/api/me" else REQUEST_TIMEOUT_SECONDS,
        )
        headers = {"Content-Type": "application/json"}
        if self.kind == "anthropic":
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        elif self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        generation = method.upper() == "POST" and not path.endswith(("/api/show", "/api/me"))
        deadline = time.monotonic() + self.generation_deadline_seconds if generation else None
        guard = _DeadlineGuard(connection, deadline) if deadline is not None else None
        try:
            # Two failure phases, told apart for the retry policy: before the request left
            # (nothing happened at the vendor) and after (it may be answering). Neither
            # message repeats the socket's text, which can carry the host and the path.
            try:
                connection.request(
                    method,
                    parsed.path + path,
                    json.dumps(body) if body is not None else None,
                    headers,
                )
            except (OSError, http.client.HTTPException) as exc:
                if guard is not None and guard.fired:
                    raise ProviderUnreachable(
                        "Provider generation deadline exceeded", unanswered=True
                    ) from exc
                raise ProviderUnreachable("Provider could not be reached", unsent=True) from exc
            try:
                response = connection.getresponse()
                if guard is not None:
                    guard.watch_response(response)
                if response.status != 200:
                    try:
                        refused = json.loads(response.read(16_384))
                    except (ValueError, TypeError):
                        refused = None
                    raise ProviderHTTPError(
                        response.status,
                        parse_retry_after(response.getheader("Retry-After")),
                        reason_code=refusal_reason(refused),
                    )
                if (
                    self.kind == "ollama"
                    and path == "/api/generate"
                    and body
                    and body.get("stream")
                ):
                    return _read_ollama_stream(response, deadline=deadline)
                data = response.read(4_000_001)
            except (OSError, http.client.HTTPException) as exc:
                raise ProviderUnreachable("Provider did not answer", unanswered=True) from exc
            if deadline is not None and time.monotonic() >= deadline:
                raise ProviderUnreachable("Provider generation deadline exceeded", unanswered=True)
            if len(data) > 4_000_000:
                raise ValueError("Provider response exceeds limit")
            return json.loads(data)
        finally:
            if guard is not None:
                guard.cancel()
            connection.close()

    async def health_check(self) -> HealthResult:
        try:
            await self.list_models()
            return HealthResult("HEALTHY")
        except Exception:
            return HealthResult("OFFLINE", "Connection or authentication could not be verified")

    @property
    def is_ollama_cloud(self) -> bool:
        return self.kind == "ollama" and urlsplit(self.base_url).hostname == "ollama.com"

    def _verify_cloud_access(self) -> None:
        # /api/tags is public. Only the authenticated identity proves this saved key.
        if not self.key.strip():
            raise ProviderHTTPError(401)
        identity = self.request("POST", "/api/me", {})
        identifier = (
            identity.get("id") or identity.get("ID") if isinstance(identity, dict) else None
        )
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Provider authentication response could not be verified")

    async def list_models(self) -> list[ModelInfo]:
        if self.is_ollama_cloud:
            await asyncio.to_thread(self._verify_cloud_access)
        path = "/api/tags" if self.kind == "ollama" else "/models"
        data = await asyncio.to_thread(self.request, "GET", path)
        items = data.get("models", []) if self.kind == "ollama" else data.get("data", [])
        names = [item.get("name") or item["id"] for item in items]
        declared = await asyncio.to_thread(self._declared_capabilities, names)
        return [ModelInfo(name, None, True, capabilities=declared.get(name, ())) for name in names]

    def _declared_capabilities(self, names: list[str]) -> dict[str, tuple[str, ...]]:
        """What the provider says each model can do. Ollama answers this per model.

        The editorial gate sends frames of a film to the Director's model; a model without
        vision refuses the whole call, so a review could never happen. What a model can see
        is the provider's statement, asked for here and stored — never assumed from a name.
        """
        if self.kind != "ollama":
            return {}
        found: dict[str, tuple[str, ...]] = {}
        for name in names:
            try:
                shown = self.request("POST", "/api/show", {"model": name})
            except (OSError, ValueError, KeyError):
                continue  # the model answered nothing about itself; the studio assumes nothing
            listed = shown.get("capabilities") if isinstance(shown, dict) else None
            if isinstance(listed, list):
                found[name] = tuple(str(c) for c in listed if isinstance(c, str))
        return found

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
            body.update(prompt=prompt, stream=self.is_ollama_cloud)
            if not self.is_ollama_cloud:
                # Local only: `num_predict` counts the reasoning there. Cloud models think
                # natively (see the module docstring); `extra` may still say otherwise.
                body["think"] = False
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
            if self.is_ollama_cloud and max_tokens is None:
                # Cloud validation refuses local unlimited sentinels. Let the vendor
                # select its valid output allowance rather than sending an invented cap.
                body["options"] = {
                    k: v for k, v in body.get("options", {}).items() if k != "num_predict"
                }
            data = await asyncio.to_thread(self.request, "POST", "/api/generate", body)
            return GenerateResult(
                data.get("response") or "",
                data.get("prompt_eval_count"),
                data.get("eval_count"),
                llm_cost_vr(
                    self.price_lookup, model, data.get("prompt_eval_count"), data.get("eval_count")
                ),
                # Never the reasoning itself — only that there was some, and how the call ended.
                raw_response={
                    "done_reason": data.get("done_reason"),
                    "thinking_chars": data.get("thinking_chars", len(data.get("thinking") or "")),
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
            prompt_tokens, completion_tokens = usage.get("input_tokens"), usage.get("output_tokens")
            return GenerateResult(
                text,
                prompt_tokens,
                completion_tokens,
                llm_cost_vr(self.price_lookup, model, prompt_tokens, completion_tokens),
            )
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        return GenerateResult(
            data["choices"][0]["message"]["content"],
            prompt_tokens,
            completion_tokens,
            llm_cost_vr(self.price_lookup, model, prompt_tokens, completion_tokens),
        )
