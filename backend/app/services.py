import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, and_, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.agents.models import AgentRun
from app.config import Settings
from app.models import ApprovalRequest, CommandRecord, DomainEvent, OwnerPolicy, Room, Studio
from app.publishing.models import ChannelRecord
from app.schemas import (
    AUTONOMY_RANK,
    ApprovalDecisionCommand,
    ApprovalDecisionResult,
    ApprovalView,
    AutonomyModeCommand,
    EnvironmentCommand,
    EventView,
    PolicyCommand,
    PolicyResult,
    PolicyView,
)
from app.wording import COMMAND_REUSED
from app.wording import autonomy_mode as mode_words


class CommandConflict(Exception):
    pass


class AutonomyRefused(Exception):
    """The Owner asked for a mode the studio's own state does not allow it to take."""


class ApprovalClosed(Exception):
    """The Owner answered a request that is no longer open: already decided, or expired."""


class ApprovalMissing(ApprovalClosed):
    """The Owner answered a request the studio has no record of ever making."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def append_event(
    session: Session,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    version: int,
    payload: dict,
    correlation_id: str,
) -> DomainEvent:
    event = DomainEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        timestamp=utc_now(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        correlation_id=correlation_id,
        causation_id=None,
        schema_version=1,
        visibility="OWNER",
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event


def bootstrap_studio(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session, session.begin():
        created = session.execute(
            insert(Studio)
            .values(id=1, name=settings.name, timezone=settings.timezone, created_at=utc_now())
            .on_conflict_do_nothing(index_elements=[Studio.id])
            .returning(Studio.id)
        ).scalar_one_or_none()
        if not created:
            return
        # Written column by column, like the studio row above: a bootstrap that runs against
        # an older schema (the upgrade path a migration test walks) must not depend on
        # columns that revision never had. Later columns take their database defaults.
        session.execute(
            insert(OwnerPolicy).values(id=1, version=1, autonomy_stopped=True, updated_at=utc_now())
        )
        correlation = str(uuid4())
        append_event(
            session,
            "studio.created",
            "studio",
            "1",
            1,
            {"name": settings.name, "timezone": settings.timezone},
            correlation,
        )
        room_id = str(uuid4())
        event = append_event(
            session,
            "office.room_created",
            "room",
            room_id,
            1,
            {"name": "Studio principal"},
            correlation,
        )
        # A real empty initial world, not simulated staff or purchased furniture.
        session.add(
            Room(
                id=room_id,
                studio_id=1,
                name="Studio principal",
                purpose="Open-plan",
                width=24,
                height=16,
                version=1,
                event_id=event.event_id,
            )
        )


def command_hash(payload: dict) -> str:
    """A stable fingerprint of a command's input, for spotting a replay from a repeat."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def recall_command(session: Session, command_id: str, payload_hash: str) -> dict | None:
    """The answer this command already produced, if it has run before.

    Returning the original answer is what makes a retry safe: the caller sees what it would have
    seen, and nothing happens a second time. A different payload under the same id is a mistake
    worth refusing rather than guessing about.
    """
    previous = session.get(CommandRecord, command_id)
    if previous is None:
        return None
    if previous.payload_hash != payload_hash:
        raise CommandConflict(COMMAND_REUSED)
    return dict(previous.response)


def remember_command(
    session: Session, command_id: str, command_type: str, payload_hash: str, response: dict
) -> None:
    """Record what a command did, inside the same transaction that did it."""
    session.add(
        CommandRecord(
            idempotency_key=command_id,
            command_type=command_type,
            payload_hash=payload_hash,
            response=response,
            created_at=utc_now(),
        )
    )


def policy_view(policy: OwnerPolicy, session: Session | None = None) -> PolicyView:
    """The studio's policy as the page reads it.

    `public_publish_enabled` is per channel (the Owner's publish-policy command, on
    `ChannelView`); here it is "any channel may publish publicly", read from the channel
    rows when the caller's session is given. Every caller in this module has one; a bare
    call answers False, the safe reading, never a guess.
    """
    public = False
    if session is not None:
        public = bool(
            session.scalar(
                select(func.count())
                .select_from(ChannelRecord)
                .where(ChannelRecord.public_publish_enabled.is_(True))
            )
        )
    return PolicyView(
        version=policy.version,
        autonomy_stopped=policy.autonomy_stopped,
        # A row written before the column existed reads as None; TEST is the safe reading.
        environment=policy.environment or "TEST",  # type: ignore[arg-type]
        # A row written before the column existed reads as None. MANUAL is the safe reading
        # of an unknown mode: it grants the least.
        autonomy_mode=policy.autonomy_mode or "MANUAL",  # type: ignore[arg-type]
        public_publish_enabled=public,
    )


def studio_environment(engine: Engine) -> str:
    """Which environment the studio is in, read from its own state.

    Every selection that spends money asks this, and nothing else may answer it: not a query
    parameter, not a header, not an agent's belief about what it is doing. A studio whose
    policy row is missing is treated as TEST — the cheap answer, never the expensive one.
    """
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        return str(policy.environment or "TEST") if policy else "TEST"


def change_environment(engine: Engine, command: EnvironmentCommand) -> PolicyResult:
    """Move the studio between TEST and PRODUCTION, the way autonomy is stopped.

    Idempotent by command id, refusing a stale version, and recorded as an event, because
    the difference between the two environments is what a shot is allowed to cost.
    """
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        previous = session.get(CommandRecord, command_id)
        if previous:
            if previous.payload_hash != payload_hash:
                raise CommandConflict(COMMAND_REUSED)
            return PolicyResult.model_validate(previous.response)
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise RuntimeError("Studio has not been initialized")
        if command.expected_version != policy.version:
            raise CommandConflict("Policy changed; refresh the snapshot and retry")
        event_id = None
        changed = policy.environment != command.environment
        if changed:
            policy.environment = command.environment
            policy.version += 1
            policy.updated_at = utc_now()
            event = append_event(
                session,
                "owner.environment_changed",
                "owner_policy",
                "1",
                policy.version,
                {"environment": command.environment},
                command_id,
            )
            event_id = event.event_id
            from app.agents.memory import remember  # noqa: PLC0415

            remember(
                session,
                memory_class="OWNER_POLICY",
                content=(
                    "The studio is in TEST: every generation takes the cheapest model that "
                    "can do the job, and nothing is bought to look better."
                    if command.environment == "TEST"
                    else "The studio is in PRODUCTION: a scene gets the least expensive "
                    "model that reliably reaches the quality it needs."
                ),
                source_type="owner",
                source_id=event_id,
                event_id=event_id,
            )
        result = PolicyResult(
            command_id=command_id,
            status="COMMITTED" if changed else "NO_CHANGE",
            policy=policy_view(policy, session),
            event_id=event_id,
        )
        session.add(
            CommandRecord(
                idempotency_key=command_id,
                command_type="SetEnvironment",
                payload_hash=payload_hash,
                response=result.model_dump(),
                created_at=utc_now(),
            )
        )
        return result


def change_stop(engine: Engine, command: PolicyCommand) -> PolicyResult:
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        # Acquire SQLite's write lock before reading the policy/idempotency record.
        # This serializes Owner commands across API processes; stale versions still fail.
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        previous = session.get(CommandRecord, command_id)
        if previous:
            if previous.payload_hash != payload_hash:
                raise CommandConflict(COMMAND_REUSED)
            return PolicyResult.model_validate(previous.response)
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise RuntimeError("Studio has not been initialized")
        if command.expected_version != policy.version:
            raise CommandConflict("Policy changed; refresh the snapshot and retry")
        event_id = None
        changed = policy.autonomy_stopped != command.stopped
        if changed:
            policy.autonomy_stopped = command.stopped
            policy.version += 1
            policy.updated_at = utc_now()
            event = append_event(
                session,
                "autonomy.stopped" if command.stopped else "autonomy.stop_cleared",
                "owner_policy",
                "1",
                policy.version,
                # The mode the studio is actually in, not the constant this used to carry.
                {"stopped": command.stopped, "mode": policy.autonomy_mode or "MANUAL"},
                command_id,
            )
            event_id = event.event_id
            from app.agents.memory import remember

            remember(
                session,
                memory_class="OWNER_POLICY",
                content=(
                    "The Owner stopped autonomy: no autonomous work until it is cleared."
                    if command.stopped
                    else "The Owner cleared the autonomy stop: the studio may work on its own."
                ),
                source_type="owner",
                source_id=event_id,
                event_id=event_id,
            )
        result = PolicyResult(
            command_id=command_id,
            status="COMMITTED" if changed else "NO_CHANGE",
            policy=policy_view(policy, session),
            event_id=event_id,
        )
        session.add(
            CommandRecord(
                idempotency_key=command_id,
                command_type="SetAutonomyStop",
                payload_hash=payload_hash,
                response=result.model_dump(),
                created_at=utc_now(),
            )
        )
        return result


# ---------------------------------------------------------------------------
# The autonomy mode: which risk tiers the studio may act in on its own
# ---------------------------------------------------------------------------

#: The risk tier of every action the studio takes on its own, mapped from
#: `31_GOVERNANCE_APPROVAL_POLICY` ("Action risk tiers") and the tool risk classes of
#: `32_AGENT_TOOL_PERMISSION_MATRIX`. Nothing here is invented: each entry is one of the
#: documents' own examples, named as the code names the operation.
#:
#: T0 — read-only (READ_INTERNAL, READ_PUBLIC): may be autonomous if the tool is permitted.
#: T1 — reversible internal (WRITE_INTERNAL): typically autonomous.
#: T2 — material internal, plus the money already inside a budget and the reads that leave
#:      the studio (EXTERNAL_READ): configurable approval.
#: T3 — external, financial or public (EXTERNAL_WRITE, FINANCIAL, WORKFORCE, WORLD_CHANGE):
#:      stricter policy.
#: T4 — the Owner's alone (POLICY_ADMIN, CREDENTIAL_ADMIN, hard budget, legal): the Director
#:      cannot execute it in any mode.
ACTION_RISK_TIERS: dict[str, str] = {
    # T0 — read analytics; inspect provider health; search public sources.
    "analytics.read": "T0",
    "provider.health_read": "T0",
    "research.search_public": "T0",
    "memory.read": "T0",
    # T1 — create draft; change task priority; run benchmark.
    "idea.create": "T1",
    "script.draft": "T1",
    "storyboard.draft": "T1",
    "task.reprioritise": "T1",
    "benchmark.run": "T1",
    # T2 — change employee model; change prompt; hire/suspend agent; create office room
    # draft; plus the external read and the paid generation that stays inside the budget
    # the Owner set (31 reserves T3 for "paid generation beyond threshold").
    "agent.change_model": "T2",
    "agent.change_prompt": "T2",
    "agent.hire": "T2",
    "agent.suspend": "T2",
    "office.room_draft": "T2",
    "research.fetch_page": "T2",
    "media.paid_generation": "T2",
    # T3 — public publish; paid generation beyond threshold; fire employee; activate new
    # provider; public world/story change.
    "publishing.public_publish": "T3",
    "media.paid_generation_over_threshold": "T3",
    "agent.fire": "T3",
    "provider.activate": "T3",
    "story.public_world_change": "T3",
    # T4 — alter hard budget; change the Policy Kernel; reveal/rotate credentials; accept
    # legal terms; disable core audit or security protections.
    "budget.change_hard_limit": "T4",
    "policy.change_kernel": "T4",
    "credential.reveal": "T4",
    "credential.rotate": "T4",
    "legal.accept_terms": "T4",
    "audit.disable": "T4",
}

#: The highest tier each mode may execute without asking. T4 is in no list, by design.
MODE_ALLOWS: dict[str, str] = {"MANUAL": "T1", "SUPERVISED": "T2", "AUTONOMOUS_CEO": "T3"}

#: Safe mode: monitoring stays available and repair is the priority, so internal reads and
#: reversible internal writes continue; money and anything leaving the studio do not.
SAFE_MODE_ALLOWS = "T1"

#: What the studio falls back to when it cannot build its settings at all — a copy with no
#: usable `.env`, which is what the test suite is. The day this module has always used.
DEFAULT_APPROVAL_EXPIRES_AFTER_HOURS = 24


def approval_expires_after_hours() -> int:
    """How long one approval request stands, from `Settings.approval_expires_after_hours`.

    31: an expired approval cannot be reused. The same clock decides three things — how long
    an unanswered question stands, how long a refusal keeps the studio from asking again, and
    how long a yes can be spent — which is why the number is the Owner's configuration rather
    than the module constant it used to be here.

    Read with a local import and getattr, the shortcut `providers.retry` and
    `integrations.autoconfig` already take: this module is called from inside a session and has
    no handle on the application, and a studio whose settings cannot be built gets the number
    it always had rather than an exception raised while asking the Owner a question.
    """
    from app.config import Settings  # noqa: PLC0415

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001
        settings = None
    hours = getattr(settings, "approval_expires_after_hours", DEFAULT_APPROVAL_EXPIRES_AFTER_HOURS)
    try:
        return max(1, int(hours))
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_EXPIRES_AFTER_HOURS


#: What each action is called in the Owner's own language, for the list he decides from. An
#: action with no entry is shown by its code name rather than by an invented translation.
APPROVAL_ACTION_LABELS: dict[str, str] = {
    "publishing.public_publish": "Publicarea unui film pe canalul lui",
    "media.paid_generation": "Un randat plătit, în limita bugetului",
    "media.paid_generation_over_threshold": "Un randat plătit peste pragul stabilit",
    "media.character_reference_set": "Producerea setului de referință al unui personaj",
    "research.fetch_page": "Citirea unei pagini din afara studioului",
    "agent.fire": "Concedierea unui angajat",
    "provider.activate": "Activarea unui furnizor nou",
    "story.public_world_change": "O schimbare publică în lumea serialului",
}


def action_words(action: str) -> str:
    """An action as the Owner calls it (`APPROVAL_ACTION_LABELS`), for a sentence; an action
    with no entry keeps its code name rather than an invented translation."""
    return APPROVAL_ACTION_LABELS.get(action, action)


#: A cost the studio cannot compute is None, never zero — and the page must be able to say
#: so without inventing "0 USD" for a question nobody can price.
COST_UNKNOWN = "necunoscut"


def _safe_mode_is_open(session: Session) -> bool:
    """Whether an incident is still open, read in the caller's own transaction."""
    from app.runbook.models import SafeModeRecord  # noqa: PLC0415

    return (
        session.scalars(
            select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None)).limit(1)
        ).first()
        is not None
    )


def _context_matches(stored: dict | None, context: dict | None) -> bool:
    """Whether the Owner was answering about the state the caller is acting in now.

    The proposed diff *is* the context he was shown — for an upload, the channel and the
    policy version that decides who will see the film. If any of it has moved since he
    answered, his yes was given about something else, so it is not spent here and a fresh
    request naming the new state is raised instead. A caller that names no context asks
    nothing of the past, which is the reading for an action with no state around it.
    """
    if not context:
        return True
    if not isinstance(stored, dict):
        return False
    return all(stored.get(key) == value for key, value in context.items())


def _open_approval(
    session: Session, action: str, subject: str, proposed_diff: dict | None
) -> ApprovalRequest | None:
    """The request already standing for this action *about this thing*, if it is still live.

    Measured before the subject was part of the key: the second, dearer film of a SUPERVISED
    day reused the first film's row, so the Owner's inbox held one question carrying the
    first film's evidence and the first film's price for both.

    "Still live" is the expiry and the state the question named. A question stands for a day
    and the channel policy can move inside that day: measured before this, the standing row
    was handed back unchanged, so the Owner read a question naming the old policy version and
    the old visibility, and his answer to it was then discarded by `_answered_approval`
    because the yes had been given about something else. Two wrongs that cancel into a safe
    outcome are still a decision he made for nothing, so a question whose state has moved is
    closed and asked again in the present tense.
    """
    now = utc_now()
    for request in session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.action == action,
            ApprovalRequest.subject == subject,
            ApprovalRequest.result == "PENDING",
        )
    ):
        if request.expires_at > now and request.proposed_diff == proposed_diff:
            return request
        # 31: an expired approval cannot be reused. Saying so is part of the record, and a
        # question about a state the studio has left is as dead as one the clock has passed.
        request.result = "EXPIRED"
    return None


def _answered_approval(
    session: Session, action: str, subject: str, context: dict | None
) -> ApprovalRequest | None:
    """The Owner's standing answer about this exact thing, or None if he has not given one.

    "Standing" is three conditions and each of them is a rule of 31 read literally: the
    request has not expired (an expired approval cannot be reused), the yes has not already
    been spent (`consumed_at`), and what he was shown is still what the studio is about to
    do. The newest answer wins, because a second question about the same film only exists
    when the first one aged out.
    """
    now = utc_now()
    standing = [
        request
        for request in session.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.action == action,
                ApprovalRequest.subject == subject,
                ApprovalRequest.result.in_(("APPROVED", "REFUSED")),
            )
        )
        if request.expires_at > now
        and request.consumed_at is None
        and _context_matches(request.proposed_diff, context)
    ]
    standing.sort(key=lambda request: request.decided_at or request.created_at, reverse=True)
    return standing[0] if standing else None


def _spend_approval(session: Session, request: ApprovalRequest) -> None:
    """Mark the Owner's yes as spent, here, before the act it authorises is attempted.

    One approval authorises one act. The column is the lock rather than the ledger, because
    a gate that had to walk the event history for every film would make the day's riskiest
    decision depend on a scan; the event is written beside it so the day's record says the
    studio acted on his answer and when. Spending it before the act rather than after is
    deliberate: an upload that then fails does not get a second free attempt on yesterday's
    answer — tomorrow's run asks again.
    """
    request.consumed_at = utc_now()
    append_event(
        session,
        "governance.approval_consumed",
        "owner_approval_request",
        request.id,
        3,
        {
            "action": request.action,
            "subject": request.subject,
            "risk_tier": request.risk_tier,
            "cost_usd": request.cost_usd,
        },
        request.id,
    )


def _owner_refusal_reason(request: ApprovalRequest) -> str:
    """What the stage tells the Owner back when he has already said no."""
    label = APPROVAL_ACTION_LABELS.get(request.action, request.action)
    words = f" Motivul lui: {request.note}" if request.note else ""
    return (
        f"Proprietarul a refuzat «{label}».{words} Studioul nu cere din nou până când "
        "decizia lui expiră."
    )


def approval_view(request: ApprovalRequest) -> ApprovalView:
    """One request as the Owner reads it, with the word for a cost nobody could compute."""
    return ApprovalView(
        id=request.id,
        action=request.action,
        action_label=APPROVAL_ACTION_LABELS.get(request.action, request.action),
        subject=request.subject or "",
        risk_tier=request.risk_tier,
        requester=request.requester,
        evidence=request.evidence,
        proposed_diff=request.proposed_diff,
        cost_usd=request.cost_usd,
        cost_label=COST_UNKNOWN if request.cost_usd is None else f"{request.cost_usd} USD",
        reversible=bool(request.reversible),
        expires_at=request.expires_at,
        created_at=request.created_at,
        result=request.result,
        approver=request.approver,
        note=request.note,
        decided_at=request.decided_at,
    )


def pending_approvals(engine: Engine) -> list[ApprovalView]:
    """What is waiting for the Owner right now, newest first.

    Only PENDING and only unexpired: a request the studio has stopped waiting on is not a
    decision he still has to make, and answering one would authorise something nobody is
    asking for any more. Reading the list writes nothing — an expired row is marked EXPIRED
    by the next thing that asks about that action, not by the page that shows it.
    """
    now = utc_now()
    with Session(engine) as session:
        return [
            approval_view(request)
            for request in session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.result == "PENDING", ApprovalRequest.expires_at > now)
                .order_by(ApprovalRequest.created_at.desc())
            )
        ]


def decide_approval(engine: Engine, command: ApprovalDecisionCommand) -> ApprovalDecisionResult:
    """The Owner answers one request: APPROVED or REFUSED, with a word of his own.

    Versioned and idempotent by command id, behind the same write lock as the rest of his
    commands, and recorded as one `governance.approval_decided` event carrying the old
    result and the new. A request that was already answered or has expired is refused
    rather than re-answered: 31 says an expired approval cannot be reused, and a request
    answered twice would be two authorities for one act.

    Nothing is written into the agents' memory here, unlike the mode and the environment: an
    answer is about one film, not a standing rule of the studio, and a letter to every agent
    for every upload would be the noise that makes the standing rules unreadable.
    """
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        # The same serialisation point the other Owner commands take: one answer at a time,
        # across processes.
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        previous = recall_command(session, command_id, payload_hash)
        if previous is not None:
            return ApprovalDecisionResult.model_validate(previous)
        request = session.get(ApprovalRequest, command.approval_id)
        if request is None:
            raise ApprovalMissing(
                f"Nu există nicio cerere de aprobare cu identificatorul «{command.approval_id}»."
            )
        if request.result != "PENDING":
            raise ApprovalClosed(
                f"Cererea a primit deja răspunsul {request.result}; o cerere nu se răspunde "
                "de două ori."
            )
        if request.expires_at <= utc_now():
            # Left PENDING rather than rewritten on the way out: the row is filtered out of
            # everything that reads it by its own expiry, and a failed command must not be
            # the thing that changes state.
            raise ApprovalClosed(
                f"Cererea a expirat la {request.expires_at}; o cerere expirată nu mai poate "
                "fi aprobată. Studioul o va pune din nou când are din nou nevoie de ea."
            )

        previous_result = request.result
        request.result = command.decision
        request.approver = "owner"
        request.note = command.note
        request.decided_at = utc_now()
        event = append_event(
            session,
            "governance.approval_decided",
            "owner_approval_request",
            request.id,
            2,
            {
                "action": request.action,
                "subject": request.subject,
                "risk_tier": request.risk_tier,
                "previous_result": previous_result,
                "result": command.decision,
                "approver": "owner",
                "note": command.note,
                "cost_usd": request.cost_usd,
            },
            command_id,
        )
        result = ApprovalDecisionResult(
            command_id=command_id,
            status="COMMITTED",
            approval=approval_view(request),
            event_id=event.event_id,
        )
        remember_command(session, command_id, "DecideApproval", payload_hash, result.model_dump())
        return result


def request_approval(
    session: Session,
    action: str,
    tier: str,
    requester: str,
    *,
    subject: str = "",
    evidence: str | None = None,
    proposed_diff: dict | None = None,
    cost_usd: float | None = None,
    reversible: bool = False,
) -> ApprovalRequest:
    """Put an action in front of the Owner and return the request standing for it.

    Asking twice about the same thing returns the same request: a queue of duplicates would
    bury the one decision the Owner has to make. Asking about a *different* thing raises a
    different request, which is what `subject` is for — the film, the storyboard. `cost_usd`
    stays None when nothing in the studio can price the action; a cost that could not be
    computed is not zero. A question whose `proposed_diff` no longer describes what the
    studio is about to do is closed rather than shown again: he must never be asked about a
    state the studio has already left.
    """
    existing = _open_approval(session, action, subject, proposed_diff)
    if existing is not None:
        return existing
    identifier = str(uuid4())
    expires = datetime.now(UTC) + timedelta(hours=approval_expires_after_hours())
    event = append_event(
        session,
        "governance.approval_requested",
        "owner_approval_request",
        identifier,
        1,
        {
            "action": action,
            "subject": subject,
            "risk_tier": tier,
            "requester": requester,
            "cost_usd": cost_usd,
        },
        identifier,
    )
    request = ApprovalRequest(
        id=identifier,
        action=action,
        subject=subject,
        risk_tier=tier,
        requester=requester,
        evidence=evidence,
        proposed_diff=proposed_diff,
        cost_usd=cost_usd,
        reversible=reversible,
        expires_at=expires.isoformat(),
        approver=None,
        result="PENDING",
        note=None,
        decided_at=None,
        consumed_at=None,
        created_at=utc_now(),
        event_id=event.event_id,
    )
    session.add(request)
    session.flush()
    return request


def may_act(
    session: Session,
    action: str,
    tier: str | None = None,
    *,
    requester: str = "director",
    subject: str = "",
    evidence: str | None = None,
    cost_usd: float | None = None,
    context: dict | None = None,
    ask_owner: bool = True,
) -> dict:
    """What the Policy Kernel asks before an agent acts on the studio's behalf.

    The order is the authority hierarchy of 31, top down. STOP AUTONOMY outranks every mode
    and is never bypassable. SAFE_MODE is next: monitoring and repair continue, money and
    external writes do not. T4 is refused in every mode, because the Director cannot execute
    what belongs to the Owner. Only then does the mode decide, and under SUPERVISED an
    external write becomes an Approval request rather than a flat refusal.

    This gate says whether the studio may *attempt* something. It is not a gate result: the
    publishing gate, the factual gate and the hard budget reach their own conclusions after
    this one, and no mode changes what they conclude.

    `tier` names the tier when the caller knows it. The table wins whenever it knows the
    action, and a caller's tier is only ever taken upward — no lower layer grants itself
    authority above a higher one. An action the table does not know and the caller does not
    classify is refused: a permission that could not be reasoned about is not granted.

    `subject` names the thing the action is about — this film, this storyboard — and
    `context` the state the Owner is being shown it in. Together they decide which of his
    answers, if any, is about what is happening now. An answer only ever does what this
    gate would otherwise have made him wait for: it turns SUPERVISED's "ask him" into
    "allowed, once". It never reaches a refusal above it — the stop, safe mode, T4 and a
    mode that was not asking are all read first, and all of them leave his yes unspent.
    """
    known = ACTION_RISK_TIERS.get(action)
    if known and tier:
        tier = max(known, tier)
    else:
        tier = known or tier

    def verdict(status: str, reason: str, approval_id: str | None = None) -> dict:
        return {
            "action": action,
            "tier": tier,
            "mode": mode,
            "allowed": status == "ALLOWED",
            "status": status,
            "reason": reason,
            "approval_id": approval_id,
        }

    policy = session.get(OwnerPolicy, 1)
    mode = str(policy.autonomy_mode or "MANUAL") if policy else "MANUAL"

    if tier is None:
        return verdict(
            "BLOCKED_UNCLASSIFIED",
            f"Acțiunea «{action_words(action)}» nu are o treaptă de risc; fără treaptă nu se "
            "acordă permisiune.",
        )

    if policy is None or policy.autonomy_stopped:
        return verdict(
            "BLOCKED_STOP",
            "AUTONOMIE OPRITĂ: nicio acțiune autonomă până când Proprietarul nu ridică oprirea.",
        )

    if tier == "T4":
        return verdict(
            "BLOCKED_OWNER_ONLY",
            f"Nicio autonomie nu deschide treapta T4: acțiunea «{action_words(action)}» rămâne "
            "exclusiv a "
            "Proprietarului.",
        )

    if _safe_mode_is_open(session) and tier > SAFE_MODE_ALLOWS:
        return verdict(
            "BLOCKED_SAFE_MODE",
            "Studioul este în modul sigur: doar citiri și reparații interne, nu "
            f"«{action_words(action)}» ({tier}).",
        )

    if tier <= MODE_ALLOWS.get(mode, "T1"):
        return verdict("ALLOWED", "")

    if mode == "SUPERVISED" and tier == "T3":
        if not ask_owner:
            # A caller asking on behalf of something it cannot name — the daily run's stage
            # wrapper, before it knows which film — gets the answer and leaves the Owner
            # alone: nothing is written, nothing of his is spent, and the caller that can
            # name the film asks it properly.
            return verdict(
                "NEEDS_APPROVAL",
                f"Modul de autonomie este supravegheat: acțiunea «{action_words(action)}» "
                f"({tier}) cere aprobarea Proprietarului.",
            )
        # His answer is read only here, and only under the mode that asks. A yes given while
        # the studio was SUPERVISED is not a way past MANUAL, which he chose afterwards
        # precisely to be asked about everything; the mode branch above has already refused
        # that case without ever looking for an answer to spend.
        answered = _answered_approval(session, action, subject, context)
        if answered is not None and answered.result == "REFUSED":
            return verdict("REFUSED_BY_OWNER", _owner_refusal_reason(answered), answered.id)
        if answered is not None:
            _spend_approval(session, answered)
            return verdict("ALLOWED", "", answered.id)
        request = request_approval(
            session,
            action,
            tier,
            requester,
            subject=subject,
            evidence=evidence,
            proposed_diff=context,
            cost_usd=cost_usd,
        )
        return verdict(
            "NEEDS_APPROVAL",
            f"Modul de autonomie este supravegheat: acțiunea «{action_words(action)}» "
            f"({tier}) așteaptă aprobarea Proprietarului.",
            request.id,
        )

    return verdict(
        "BLOCKED_MODE",
        f"Modul de autonomie este {mode_words(mode)}: acțiunea «{action_words(action)}» "
        f"({tier}) cere decizia Proprietarului.",
    )


def change_autonomy_mode(engine: Engine, command: AutonomyModeCommand) -> PolicyResult:
    """Move the studio between MANUAL, SUPERVISED and AUTONOMOUS_CEO.

    Idempotent by command id, refusing a stale version, recorded as an event with the old
    mode and the new, exactly as the environment and the stop are — the mode decides which
    risk tiers an agent may act in at all, so it cannot be a setting a page flips.

    **What this function can check and what it cannot.** 51 requires four things before the
    studio takes a higher mode: acceptance criteria, a burn-in, no unresolved P0, and the
    Owner's action. Two of them are readable here — an open safe-mode record is an
    unresolved P0, and the autonomy stop is the Owner saying the studio should not act — and
    a promotion is refused on either. Acceptance criteria and burn-in are judgements about
    evidence outside this database; nothing here measures them, and the refusal names them
    to the Owner rather than letting the command imply they were verified. Lowering the mode
    is always allowed: 51 calls it immediate and safe, and a safety state must never be the
    thing that blocks the safer choice.
    """
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        previous = session.get(CommandRecord, command_id)
        if previous:
            if previous.payload_hash != payload_hash:
                raise CommandConflict(COMMAND_REUSED)
            return PolicyResult.model_validate(previous.response)
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise RuntimeError("Studio has not been initialized")
        if command.expected_version != policy.version:
            raise CommandConflict("Policy changed; refresh the snapshot and retry")

        current = str(policy.autonomy_mode or "MANUAL")
        promotion = AUTONOMY_RANK[command.autonomy_mode] > AUTONOMY_RANK[current]
        if promotion:
            unmeasured = (
                "Ridicarea autonomiei mai cere criterii de acceptare îndeplinite și un "
                "rodaj încheiat, pe care studioul nu le poate verifica singur."
            )
            if policy.autonomy_stopped:
                raise AutonomyRefused(
                    "AUTONOMIA ESTE OPRITĂ: modul nu poate fi ridicat la "
                    f"{mode_words(command.autonomy_mode)} până când Proprietarul nu ridică "
                    "oprirea. " + unmeasured
                )
            if _safe_mode_is_open(session):
                raise AutonomyRefused(
                    "Studioul este în modul sigur: un incident P0 este încă deschis, așa că "
                    f"modul nu poate fi ridicat la {mode_words(command.autonomy_mode)}. "
                    + unmeasured
                )

        event_id = None
        changed = current != command.autonomy_mode
        if changed:
            policy.autonomy_mode = command.autonomy_mode
            policy.version += 1
            policy.updated_at = utc_now()
            event = append_event(
                session,
                "owner.autonomy_mode_changed",
                "owner_policy",
                "1",
                policy.version,
                {
                    "autonomy_mode": command.autonomy_mode,
                    "previous_autonomy_mode": current,
                    "direction": "PROMOTION" if promotion else "REDUCTION",
                },
                command_id,
            )
            event_id = event.event_id
            from app.agents.memory import remember  # noqa: PLC0415

            remember(
                session,
                memory_class="OWNER_POLICY",
                content=MODE_MEMORY[command.autonomy_mode],
                source_type="owner",
                source_id=event_id,
                event_id=event_id,
            )
        result = PolicyResult(
            command_id=command_id,
            status="COMMITTED" if changed else "NO_CHANGE",
            policy=policy_view(policy, session),
            event_id=event_id,
        )
        session.add(
            CommandRecord(
                idempotency_key=command_id,
                command_type="SetAutonomyMode",
                payload_hash=payload_hash,
                response=result.model_dump(),
                created_at=utc_now(),
            )
        )
        return result


#: What every agent is told when the mode moves, in the Owner's language.
MODE_MEMORY = {
    "MANUAL": (
        "Modul de autonomie este manual: angajații pot pregăti și analiza, dar Proprietarul "
        "aprobă trecerile între etape; nimic nu iese în afara studioului."
    ),
    "SUPERVISED": (
        "Modul de autonomie este supravegheat: etapele interne de rutină merg singure, iar o "
        "scriere în afară cere mai întâi aprobarea Proprietarului."
    ),
    "AUTONOMOUS_CEO": (
        "Modul de autonomie este CEO autonom: Directoarea execută singură treptele T0-T3 "
        "în limitele politicii; treapta T4 rămâne a Proprietarului, iar porțile dure rămân "
        "la fel de închise."
    ),
}


def last_task_per_agent(session: Session) -> dict[str, dict]:
    """Each employee's newest run, started or finished, from the studio's own records.

    A run is written the moment its model call starts (agents/services.py run_agent_task), so
    the newest row by ``started_at`` is the last task the employee took up: a RUNNING one while
    the call is out, or how the last one ended. An employee with no run has no entry. One
    grouped query over ``ix_agent_run_agent_started`` (migration 0046), because the snapshot
    that carries it is read every five seconds.
    """
    newest = (
        select(AgentRun.agent_id.label("agent_id"), func.max(AgentRun.started_at).label("at"))
        .group_by(AgentRun.agent_id)
        .subquery()
    )
    rows = session.execute(
        select(
            AgentRun.agent_id,
            AgentRun.task_type,
            AgentRun.status,
            AgentRun.started_at,
            AgentRun.finished_at,
        )
        .join(
            newest,
            and_(AgentRun.agent_id == newest.c.agent_id, AgentRun.started_at == newest.c.at),
        )
        .order_by(AgentRun.agent_id, AgentRun.id)
    ).all()
    tasks: dict[str, dict] = {}
    for agent_id, task_type, status, started_at, finished_at in rows:
        # two runs started in the same microsecond: the first by id, so the answer is stable
        tasks.setdefault(
            agent_id,
            {
                "task_type": task_type,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
    return tasks


def snapshot(engine: Engine) -> dict:
    with Session(engine) as session, session.begin():
        studio = session.get(Studio, 1)
        policy = session.get(OwnerPolicy, 1)
        if studio is None or policy is None:
            raise RuntimeError("Studio has not been initialized")
        cursor = session.scalar(select(func.max(DomainEvent.sequence))) or 0
        rooms = session.scalars(select(Room).order_by(Room.id)).all()
        recent = session.scalars(
            select(DomainEvent).order_by(DomainEvent.sequence.desc()).limit(20)
        ).all()
        return {
            "schema_version": 1,
            "cursor": cursor,
            "captured_at": utc_now(),
            "studio": {"id": studio.id, "name": studio.name, "timezone": studio.timezone},
            "maturity": "DEVELOPMENT",
            "deployment_mode": "LOCAL_STUDIO",
            "policy": policy_view(policy, session).model_dump(),
            "office": {
                "rooms": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "width": r.width,
                        "height": r.height,
                        "version": r.version,
                        "event_id": r.event_id,
                    }
                    for r in rooms
                ]
            },
            # Implementation maturity is release metadata, not external provider health. A module
            # is IMPLEMENTED only when its path runs end to end in the code; PARTIAL when a real
            # part of it runs and a named part does not; NOT_IMPLEMENTED when no code does its job.
            # Read against the code on 2026-09-24:
            #   story      PARTIAL, was NOT_IMPLEMENTED. The day closes into a counted log
            #              (story/services.close_daily_log), the showrunner writes a grounded
            #              episode, the Director reviews it, the Owner decides it, and the runbook's
            #              serial stage carries an approved one to a storyboard
            #              (story/serial_stage.py). Not end to end: an episode the Owner approves by
            #              hand is never storyboarded, a day that already has a draft is never
            #              returned to, and nothing writes tomorrow's episode.
            #   financing  PARTIAL, was NOT_IMPLEMENTED. Owner funding runs: a capital
            #              contribution or an Owner loan with its terms is recorded in the VR$
            #              books (economy/services.record_owner_funding, POST
            #              /economy/owner-funding, the Treasury dialog). Not built: the CEO's
            #              financing request, the market-benchmarked terms and the interest that
            #              accrues on its own.
            #   procurement stays NOT_IMPLEMENTED: no VendorShop or purchase code exists
            #              (economy/services.py says spending VR$ has no code yet).
            "modules": {
                "agents": "IMPLEMENTED",
                "providers": "IMPLEMENTED",
                "settings": "IMPLEMENTED",
                "workflows": "PARTIAL",
                "research": "PARTIAL",
                "media": "PARTIAL",
                "publishing": "PARTIAL",
                "analytics": "PARTIAL",
                "story": "PARTIAL",
                "treasury": "PARTIAL",
                "procurement": "NOT_IMPLEMENTED",
                "financing": "PARTIAL",
            },
            "events": [EventView.model_validate(e).model_dump() for e in reversed(recent)],
            # The name tags in the headquarters read each employee's last task from here,
            # not only from the events the page happened to replay (W12).
            "last_tasks": last_task_per_agent(session),
        }


def read_instant(value: str) -> str:
    """An instant a page asks the record about, as the record stamps its rows: UTC, ISO 8601.

    A naive time is read as UTC. Anything that is not an instant raises ValueError. The stamps
    are ``datetime.isoformat()`` strings in UTC, so the answer compares with them as text.
    """
    moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def read_events(engine: Engine, after: int, limit: int, since: str | None = None) -> dict:
    """A page of the record, in sequence order, after `after`.

    With `since` (an instant from `read_instant`), the page starts at the first event stamped at
    or after it: the lowest sequence among those stamps, so an event two writers committed a
    moment apart in the other order is not skipped. It is one query, the stamp found through
    ``ix_domain_event_timestamp``; the replay of a day finds its run's start with it at once
    instead of bisecting the log. The answer names the instant, so a page can tell a studio that
    read it from one that ignored it.
    """
    from app.maintenance import ledger_floor  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        # A history that was deleted is not read back: the ledger begins at the reset line.
        after = max(after, ledger_floor(session) - 1)
        query = select(DomainEvent).where(DomainEvent.sequence > after)
        if since is not None:
            # `sequence + 0`: a bare MIN(sequence) lets SQLite walk the whole log by sequence
            # until a stamp is late enough; this way it reads only the stamps from the instant
            # on, from the index alone.
            first = (
                select(func.min(DomainEvent.sequence + 0))
                .where(DomainEvent.timestamp >= since)
                .scalar_subquery()
            )
            query = query.where(DomainEvent.sequence >= first)
        events = session.scalars(query.order_by(DomainEvent.sequence).limit(limit + 1)).all()
        selected = events[:limit]
        page = {
            "schema_version": 1,
            "events": [EventView.model_validate(e).model_dump() for e in selected],
            "next_cursor": selected[-1].sequence if selected else after,
            "has_more": len(events) > limit,
        }
        if since is not None:
            page["since"] = since
        return page
