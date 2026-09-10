"""Phase 1 FastAPI routes for agents and providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from app.agents.schemas import AgentRunView, RunAgentCommand
from app.agents.services import (
    get_agent,
    list_agents,
    list_provider_models,
    list_providers,
    list_roles,
    pause_agent,
    resume_agent,
    run_agent_task,
    sync_provider_models,
)
from app.providers.registry import ProviderRegistry
from app.security import require_owner


def create_agents_router(registry: ProviderRegistry) -> APIRouter:
    router = APIRouter(prefix="/agents", dependencies=[Depends(require_owner)])

    @router.get("/roles")
    def get_roles(request: Request) -> dict:
        return {"roles": list_roles(request.app.state.engine)}

    @router.get("/")
    def get_agents(request: Request) -> dict:
        return {"agents": list_agents(request.app.state.engine)}

    @router.get("/{agent_id}")
    def get_agent_detail(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        agent = get_agent(request.app.state.engine, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @router.post("/{agent_id}/run", response_model=AgentRunView)
    def run_agent(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: RunAgentCommand,
    ) -> dict:
        try:
            return run_agent_task(
                request.app.state.engine,
                request.app.state.registry,
                agent_id,
                command.task_type,
                command.objective,
                command.prompt_template_version,
                str(command.command_id),
                max_tokens=command.max_tokens,
                temperature=command.temperature,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SQLAlchemyError:
            raise HTTPException(status_code=500, detail="Internal error") from None

    @router.post("/{agent_id}/pause")
    def post_pause_agent(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return pause_agent(request.app.state.engine, agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/{agent_id}/resume")
    def post_resume_agent(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return resume_agent(request.app.state.engine, agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def create_providers_router(registry: ProviderRegistry) -> APIRouter:
    router = APIRouter(prefix="/providers", dependencies=[Depends(require_owner)])

    @router.get("/")
    def get_providers(request: Request) -> dict:
        providers = list_providers(request.app.state.engine)
        for p in providers:
            p["runtime_status"] = registry.cached_status(p["id"])
        return {"providers": providers}

    @router.get("/{provider_id}/models")
    def get_provider_models(
        request: Request,
        provider_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return {"models": list_provider_models(request.app.state.engine, provider_id)}

    @router.post("/{provider_id}/sync-models")
    def sync_models(
        request: Request,
        provider_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            models = sync_provider_models(request.app.state.engine, registry, provider_id)
            return {"synced_count": len(models), "models": models}
        except SQLAlchemyError:
            raise HTTPException(status_code=500, detail="Internal error") from None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            # URLError, HTTPError, TimeoutError and ConnectionRefusedError all land here.
            # The endpoint did not answer. Say so plainly instead of a generic server error:
            # the Owner needs to know the provider is unreachable, and nothing was recorded.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Furnizorul nu a răspuns, deci nu s-a înregistrat niciun model. "
                    "Pornește serviciul sau verifică adresa, apoi încearcă din nou."
                ),
            ) from exc

    return router
