"""ProviderRegistry: maps provider IDs to adapter instances."""

from __future__ import annotations

from app.providers.base import HealthResult, LLMProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, LLMProvider] = {}
        self._health_cache: dict[str, HealthResult] = {}

    def register(self, provider_id: str, adapter: LLMProvider) -> None:
        self._adapters[provider_id] = adapter
        self._health_cache.pop(provider_id, None)

    def unregister(self, provider_id: str) -> None:
        self._adapters.pop(provider_id, None)
        self._health_cache.pop(provider_id, None)

    def get(self, provider_id: str) -> LLMProvider | None:
        return self._adapters.get(provider_id)

    async def check_health(self, provider_id: str) -> HealthResult:
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            result = HealthResult(status="NOT_CONFIGURED", detail="Provider not registered")
        else:
            result = await adapter.health_check()
        self._health_cache[provider_id] = result
        return result

    def cached_status(self, provider_id: str) -> str:
        cached = self._health_cache.get(provider_id)
        return cached.status if cached else "UNKNOWN"

    async def refresh_all(self) -> dict[str, HealthResult]:
        results = {}
        for pid in list(self._adapters.keys()):
            results[pid] = await self.check_health(pid)
        return results


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
