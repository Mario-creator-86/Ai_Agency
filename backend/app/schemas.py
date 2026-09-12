from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    stopped: bool = Field(strict=True)


class EnvironmentCommand(BaseModel):
    """The Owner moves the studio between testing and publishing.

    The same shape as the autonomy stop, for the same reason: what the studio is allowed to
    spend changes with it, so it is a versioned command recorded in the ledger, never a
    setting a page can flip or an agent can assume.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    environment: Literal["TEST", "PRODUCTION"]


class PolicyView(BaseModel):
    version: int
    autonomy_stopped: bool
    #: Which environment the studio is in. The page shows it; the backend decides it.
    environment: Literal["TEST", "PRODUCTION"] = "TEST"
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
