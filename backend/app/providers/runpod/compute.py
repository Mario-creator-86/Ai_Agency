"""Opt-in control of an existing Pod using the official REST v2 API."""

from __future__ import annotations

import asyncio
from typing import Any

from app.providers.runpod.client import RunPodClient, Transport
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import InfrastructureDisabled, RunPodProtocolError


class ComputeControl:
    def __init__(self, config: RunPodConfig, transport: Transport | None = None) -> None:
        self.config = config
        self.client = RunPodClient(
            config.model_copy(
                update={
                    "mode": "pod",
                    "generation_base_url": "https://api.runpod.io",
                }
            ),
            transport,
        )

    def require_resource(self, *, mutation: bool = False) -> None:
        c = self.config
        if (
            not c.enabled
            or c.mock
            or c.mode != "pod"
            or not c.pod_id
            or not c.api_key.get_secret_value()
            or (mutation and not c.allow_infra_actions)
        ):
            raise InfrastructureDisabled(
                "Pod control needs enabled real Pod configuration "
                "and explicit infrastructure permission"
            )

    async def status(self) -> dict[str, Any]:
        self.require_resource()
        data = await self.client.call("GET", "/v2/pods/" + str(self.config.pod_id))
        # The official response includes env and SSH credentials; never return or store those.
        return {k: data[k] for k in ("id", "status", "actions", "gpu", "cost") if k in data}

    async def action(self, action: str) -> dict[str, Any]:
        self.require_resource(mutation=True)
        if action not in ("start", "stop"):
            raise RunPodProtocolError("Only start and stop are supported")
        state = await self.status()
        if (
            action == "start"
            and state.get("status") == "RUNNING"
            or action == "stop"
            and state.get("status") == "EXITED"
        ):
            return state
        if action not in state.get("actions", []):
            raise RunPodProtocolError("Pod does not currently allow this action")
        data = await self.client.call(
            "POST", "/v2/pods/" + str(self.config.pod_id) + "/action", {"action": action}
        )
        return {k: data[k] for k in ("id", "status", "actions", "gpu", "cost") if k in data}

    async def ensure(self) -> None:
        state = await self.status()
        if state.get("status") == "RUNNING":
            return
        if not self.config.auto_start:
            raise InfrastructureDisabled("Pod is not running and automatic start is disabled")
        await self.action("start")

        async def ready() -> None:
            while (await self.status()).get("status") != "RUNNING":
                await asyncio.sleep(self.config.poll_interval)

        await asyncio.wait_for(ready(), timeout=self.config.job_timeout)
