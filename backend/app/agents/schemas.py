"""Phase 1 Pydantic schemas for agents, roles, providers."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CapabilityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str


class RoleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    mission: str
    allowed_task_types: str
    prohibited_actions: str
    required_capabilities: list[str] = []


class ProviderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    provider_type: str
    base_url: str
    status: str
    last_health_check: str | None
    adapter_version: str
    notes: str


class ModelView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    provider_id: str
    model_name: str
    discovery_method: str
    context_length: int | None
    is_available: bool
    notes: str
    capabilities: list[str] = []


class AgentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    role_id: str
    provider_id: str
    model_id: str
    lifecycle: str
    runtime_state: str
    max_concurrent_tasks: int
    version: int
    hired_at: str
    terminated_at: str | None


class RunAgentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    task_type: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=2000)
    prompt_template_version: str = Field(default="v1", max_length=50)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    agent_id: str
    task_type: str
    objective: str
    model_name: str
    provider_name: str
    status: str
    output_text: str | None
    error_detail: str | None
    cost_vr: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    started_at: str
    finished_at: str | None
    event_id: str | None
