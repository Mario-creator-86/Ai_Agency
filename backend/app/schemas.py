from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    stopped: bool = Field(strict=True)


class PolicyView(BaseModel):
    version: int
    autonomy_stopped: bool
    autonomy_mode: Literal["MANUAL"] = "MANUAL"
    public_publish_enabled: Literal[False] = False
    external_payments_enabled: Literal[False] = False
    autonomous_firing_enabled: Literal[False] = False
    provider_auto_switch_enabled: Literal[False] = False
    world_generation_enabled: Literal[False] = False


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sequence: int
    event_id: str
    event_type: str
    timestamp: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    correlation_id: str
    causation_id: str | None
    schema_version: int
    visibility: str
    payload: dict


class PolicyResult(BaseModel):
    command_id: str
    status: Literal["COMMITTED", "NO_CHANGE"]
    policy: PolicyView
    event_id: str | None
