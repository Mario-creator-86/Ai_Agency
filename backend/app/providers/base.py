"""Abstract LLM provider interface.

Every adapter must implement these methods honestly.
Do not expose a method if the underlying provider cannot support it truthfully.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelInfo:
    model_name: str
    context_length: int | None
    is_available: bool
    notes: str = ""
    is_cloud: bool = False
    #: What the provider itself says this model can do, in the provider's own words
    #: (Ollama answers "completion", "thinking", "tools", "vision"). Empty when the
    #: provider does not say; never a guess of the studio's.
    capabilities: tuple[str, ...] = ()


@dataclass
class GenerateResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_vr: str | None
    raw_response: dict = field(default_factory=dict)


@dataclass
class HealthResult:
    # HEALTHY | DEGRADED | RATE_LIMITED | OFFLINE | AUTH_REQUIRED | NOT_CONFIGURED | UNKNOWN
    status: str
    detail: str = ""
    latency_ms: float | None = None


class LLMProvider(abc.ABC):
    """Base class for LLM provider adapters."""

    ADAPTER_VERSION: str = "0.0.0"

    @abc.abstractmethod
    async def health_check(self) -> HealthResult:
        """Return the current health of the provider endpoint."""

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return available models. Raise ProviderOfflineError if not reachable."""

    @abc.abstractmethod
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
        """Run a text-generation request. Returns real model output only."""
