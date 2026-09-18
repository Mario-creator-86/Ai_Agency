from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: The three modes of `51_AUTONOMY_MODE_SEMANTICS`, in the order of increasing autonomy.
#: MANUAL: agents draft, the Owner approves the stage transitions. SUPERVISED: routine
#: internal stages run themselves and an external write asks for an Approval.
#: AUTONOMOUS_CEO: the Director executes T0-T3 within policy, T4 stays the Owner's.
AutonomyMode = Literal["MANUAL", "SUPERVISED", "AUTONOMOUS_CEO"]

#: Rank, so "is this a promotion?" is a comparison rather than a list of special cases.
AUTONOMY_RANK: dict[str, int] = {"MANUAL": 0, "SUPERVISED": 1, "AUTONOMOUS_CEO": 2}


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


class AutonomyModeCommand(BaseModel):
    """The Owner moves the studio between autonomy modes.

    The same shape as the environment and the stop, for the same reason: the mode decides
    which risk tiers an agent may act in at all, so it is a versioned command recorded in the
    ledger, never a setting a page can flip or an agent can assume about itself.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    autonomy_mode: AutonomyMode


class PolicyView(BaseModel):
    version: int
    autonomy_stopped: bool
    #: Which environment the studio is in. The page shows it; the backend decides it.
    environment: Literal["TEST", "PRODUCTION"] = "TEST"
    #: The mode the studio is really in, read from `owner_policy.autonomy_mode`. It was the
    #: constant "MANUAL" while the studio ran its whole day unattended; the page now reads
    #: what the backend decided, and only the Owner's command moves it.
    autonomy_mode: AutonomyMode = "AUTONOMOUS_CEO"
    #: Whether any channel may publish publicly. The switch itself is per channel
    #: (`ChannelView.public_publish_enabled`, set only by the Owner's publish-policy
    #: command); the studio view sums them, so a page reading it is not told "never"
    #: while a channel's own policy says otherwise.
    public_publish_enabled: bool = False
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


class ApprovalDecisionCommand(BaseModel):
    """The Owner answers one approval request: APPROVED or REFUSED, with a word of his own.

    The same shape as the mode, the environment and the stop — versioned, idempotent by
    command id — with one difference: there is no `expected_version`. The request row
    carries no version because its whole life is one transition, PENDING to answered, and
    the command refuses an already-answered or expired request outright (409). A version
    would guard against a stale read of a field nothing else can move; the closed state
    guards against the only thing that can actually go wrong, which is answering twice.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    approval_id: str = Field(min_length=1, max_length=36)
    decision: Literal["APPROVED", "REFUSED"]
    #: The Owner's own words, carried into the refusal the stage reports back to him.
    note: str | None = Field(default=None, max_length=500)


class ApprovalView(BaseModel):
    """One request as the Owner reads it before deciding.

    `cost_label` exists beside `cost_usd` because a cost the studio could not compute is
    None and never zero: the page must be able to show "necunoscut" without inventing a
    figure, and a reader that sees only the number would show "0 USD" for a question about
    an upload nobody can price.
    """

    model_config = ConfigDict(from_attributes=True)
    id: str
    action: str
    #: What the action is, in the Owner's language.
    action_label: str
    #: The specific thing the request is about: this film, this storyboard.
    subject: str
    risk_tier: str
    requester: str
    evidence: str | None
    proposed_diff: dict | None
    cost_usd: float | None
    cost_label: str
    reversible: bool
    expires_at: str
    created_at: str
    result: str
    approver: str | None
    note: str | None
    decided_at: str | None


class ApprovalDecisionResult(BaseModel):
    command_id: str
    #: Always COMMITTED: a request that was already answered is refused, never re-answered,
    #: so there is no "nothing changed" outcome to report.
    status: Literal["COMMITTED"]
    approval: ApprovalView
    event_id: str | None
