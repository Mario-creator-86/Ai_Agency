"""Phase 1 FastAPI routes for agents and providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.director import DirectorError, director_review
from app.agents.identity import ContractCommand, identity_view, set_role_contract
from app.agents.memory import MemoryError, invalidate, list_memory
from app.agents.messages import MessageError, list_messages, resolve_message
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


class ResolveMessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=1, max_length=2000)


class InvalidateMemoryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=600)


def create_agents_router(registry: ProviderRegistry) -> APIRouter:
    router = APIRouter(prefix="/agents", dependencies=[Depends(require_owner)])

    @router.get("/roles")
    def get_roles(request: Request) -> dict:
        return {"roles": list_roles(request.app.state.engine)}

    @router.put("/roles/{role_id}/contract")
    def put_role_contract(
        request: Request,
        role_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: ContractCommand,
    ) -> dict:
        try:
            return set_role_contract(request.app.state.engine, role_id, command)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/messages")
    def get_messages(
        request: Request, status: str | None = None, agent_id: str | None = None
    ) -> dict:
        return {
            "messages": list_messages(request.app.state.engine, status=status, agent_id=agent_id)
        }

    @router.post("/messages/{message_id}/resolve")
    def post_resolve_message(
        request: Request,
        message_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: ResolveMessageCommand,
    ) -> dict:
        from app.agents.messages import message_view

        try:
            with Session(request.app.state.engine) as session, session.begin():
                row = resolve_message(
                    session, message_id, resolution=command.resolution, resolved_by="Owner"
                )
                return message_view(row)
        except MessageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/director/review")
    def post_director_review(request: Request) -> dict:
        """The Owner asks the Director to review the inbox now, outside the daily run."""
        try:
            return director_review(request.app.state.engine, request.app.state.registry)
        except DirectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    @router.get("/{agent_id}/identity")
    def get_agent_identity(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        """The identity the model is given: contract, character, memory, the prompt itself."""
        identity = identity_view(request.app.state.engine, agent_id)
        if identity is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        identity["messages"] = list_messages(request.app.state.engine, agent_id=agent_id, limit=20)
        return identity

    @router.get("/{agent_id}/memory")
    def get_agent_memory(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        if get_agent(request.app.state.engine, agent_id) is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"memory": list_memory(request.app.state.engine, agent_id)}

    @router.post("/{agent_id}/memory/{record_id}/invalidate")
    def post_invalidate_memory(
        request: Request,
        agent_id: Annotated[str, Path(min_length=36, max_length=36)],
        record_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: InvalidateMemoryCommand,
    ) -> dict:
        from app.agents.memory import memory_view

        try:
            with Session(request.app.state.engine) as session, session.begin():
                return memory_view(invalidate(session, record_id, command.reason))
        except MemoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
