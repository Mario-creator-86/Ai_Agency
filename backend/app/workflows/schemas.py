"""Phase 2 Pydantic schemas for workflows, steps, tasks, scheduled jobs, and replay."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateWorkflowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    workflow_type: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    config: dict = Field(default_factory=dict)


class WorkflowStepView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workflow_id: str
    stage: str
    status: str
    assigned_agent_id: str | None
    inputs: dict
    outputs: dict | None
    error_detail: str | None
    attempt: int
    started_at: str | None
    completed_at: str | None


class WorkflowView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workflow_type: str
    title: str
    status: str
    current_stage: str
    config: dict
    created_at: str
    updated_at: str
    event_id: str


class WorkflowDetailView(WorkflowView):
    steps: list[WorkflowStepView] = []


class TaskQueueItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workflow_id: str | None
    step_id: str | None
    task_type: str
    payload: dict
    priority: int
    status: str
    attempts: int
    max_attempts: int
    backoff_seconds: int
    next_attempt_at: str
    lease_token: str | None
    lease_expires_at: str | None
    idempotency_key: str | None
    error_detail: str | None
    created_at: str
    updated_at: str


class CreateScheduledJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    name: str = Field(min_length=1, max_length=100)
    workflow_type: str = Field(min_length=1, max_length=50)
    interval_seconds: int = Field(ge=5, le=86400 * 30)
    missed_policy: Literal["SKIP", "CATCH_UP"] = "SKIP"


class SetJobActiveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    active: bool


class ScheduledJobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    workflow_type: str
    interval_seconds: int
    is_active: bool
    last_run_at: str | None
    next_run_at: str
    missed_policy: str
    #: The wall-clock hour ("HH:MM") and the IANA zone a fixed-hour job fires at; both None
    #: for a job anchored to its interval. The panel used to see only `interval_seconds`, so a
    #: job on the clock read like one anchored to the moment the Owner activated it.
    run_at_local: str | None = None
    timezone: str | None = None
    created_at: str


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_sequence: int = Field(ge=0, default=0)
    limit: int = Field(ge=1, le=500, default=100)
