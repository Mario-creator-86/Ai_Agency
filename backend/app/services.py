import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ApprovalRequest, CommandRecord, DomainEvent, OwnerPolicy, Room, Studio
from app.publishing.models import ChannelRecord
from app.schemas import (
    AUTONOMY_RANK,
    AutonomyModeCommand,
    EnvironmentCommand,
    EventView,
    PolicyCommand,
    PolicyResult,
    PolicyView,
)


class CommandConflict(Exception):
    pass


class AutonomyRefused(Exception):
    """The Owner asked for a mode the studio's own state does not allow it to take."""


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
        raise CommandConflict("Command ID already used with different input")
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
                raise CommandConflict("Command ID already used with different input")
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
                raise CommandConflict("Command ID already used with different input")
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

#: How long an unanswered approval request stands before it must be asked again. 31: an
#: expired approval cannot be reused. A day, so the Owner's morning is the natural answer;
#: the integrator may lift it into config.py when the Owner wants another number.
APPROVAL_EXPIRES_AFTER_HOURS = 24


def _safe_mode_is_open(session: Session) -> bool:
    """Whether an incident is still open, read in the caller's own transaction."""
    from app.runbook.models import SafeModeRecord  # noqa: PLC0415

    return (
        session.scalars(
            select(SafeModeRecord).where(SafeModeRecord.cleared_at.is_(None)).limit(1)
        ).first()
        is not None
    )


def _open_approval(session: Session, action: str) -> ApprovalRequest | None:
    """The request already standing for this action, if it has not expired."""
    now = utc_now()
    for request in session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.action == action, ApprovalRequest.result == "PENDING"
        )
    ):
        if request.expires_at > now:
            return request
        # 31: an expired approval cannot be reused. Saying so is part of the record.
        request.result = "EXPIRED"
    return None


def request_approval(
    session: Session,
    action: str,
    tier: str,
    requester: str,
    *,
    evidence: str | None = None,
    proposed_diff: dict | None = None,
    cost_usd: float | None = None,
    reversible: bool = False,
) -> ApprovalRequest:
    """Put an action in front of the Owner and return the request standing for it.

    Asking twice for the same action returns the same request: a queue of duplicates would
    bury the one decision the Owner has to make. `cost_usd` stays None when nothing in the
    studio can price the action — a cost that could not be computed is not zero.
    """
    existing = _open_approval(session, action)
    if existing is not None:
        return existing
    identifier = str(uuid4())
    expires = datetime.now(UTC) + timedelta(hours=APPROVAL_EXPIRES_AFTER_HOURS)
    event = append_event(
        session,
        "governance.approval_requested",
        "owner_approval_request",
        identifier,
        1,
        {"action": action, "risk_tier": tier, "requester": requester, "cost_usd": cost_usd},
        identifier,
    )
    request = ApprovalRequest(
        id=identifier,
        action=action,
        risk_tier=tier,
        requester=requester,
        evidence=evidence,
        proposed_diff=proposed_diff,
        cost_usd=cost_usd,
        reversible=reversible,
        expires_at=expires.isoformat(),
        approver=None,
        result="PENDING",
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
    evidence: str | None = None,
    cost_usd: float | None = None,
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
            f"Acțiunea «{action}» nu are o treaptă de risc; fără treaptă nu se acordă permisiune.",
        )

    if policy is None or policy.autonomy_stopped:
        return verdict(
            "BLOCKED_STOP",
            "AUTONOMIE OPRITĂ: nicio acțiune autonomă până când Proprietarul nu ridică oprirea.",
        )

    if tier == "T4":
        return verdict(
            "BLOCKED_OWNER_ONLY",
            f"Nicio autonomie nu deschide treapta T4: acțiunea «{action}» rămâne exclusiv a "
            "Proprietarului.",
        )

    if _safe_mode_is_open(session) and tier > SAFE_MODE_ALLOWS:
        return verdict(
            "BLOCKED_SAFE_MODE",
            f"Studioul este în SAFE_MODE: doar citiri și reparații interne, nu «{action}» "
            f"({tier}).",
        )

    if tier <= MODE_ALLOWS.get(mode, "T1"):
        return verdict("ALLOWED", "")

    if mode == "SUPERVISED" and tier == "T3":
        request = request_approval(
            session,
            action,
            tier,
            requester,
            evidence=evidence,
            cost_usd=cost_usd,
        )
        return verdict(
            "NEEDS_APPROVAL",
            f"Modul de autonomie este SUPERVISED: acțiunea «{action}» ({tier}) așteaptă "
            "aprobarea Proprietarului.",
            request.id,
        )

    return verdict(
        "BLOCKED_MODE",
        f"Modul de autonomie este {mode}: acțiunea «{action}» ({tier}) cere decizia "
        "Proprietarului.",
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
                raise CommandConflict("Command ID already used with different input")
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
                    f"{command.autonomy_mode} până când Proprietarul nu ridică oprirea. "
                    + unmeasured
                )
            if _safe_mode_is_open(session):
                raise AutonomyRefused(
                    "Studioul este în SAFE_MODE: un incident P0 este încă deschis, așa că "
                    f"modul nu poate fi ridicat la {command.autonomy_mode}. " + unmeasured
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
        "Modul de autonomie este MANUAL: agenții pot pregăti și analiza, dar Proprietarul "
        "aprobă trecerile între etape; nimic nu iese în afara studioului."
    ),
    "SUPERVISED": (
        "Modul de autonomie este SUPERVISED: etapele interne de rutină merg singure, iar o "
        "scriere în afară cere mai întâi aprobarea Proprietarului."
    ),
    "AUTONOMOUS_CEO": (
        "Modul de autonomie este AUTONOMOUS_CEO: Directoarea execută singură treptele T0-T3 "
        "în limitele politicii; treapta T4 rămâne a Proprietarului, iar porțile dure rămân "
        "la fel de închise."
    ),
}


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
            # Implementation maturity is release metadata, not external provider health.
            "modules": {
                "agents": "IMPLEMENTED",
                "providers": "IMPLEMENTED",
                "settings": "IMPLEMENTED",
                "workflows": "PARTIAL",
                "research": "PARTIAL",
                "media": "PARTIAL",
                "publishing": "PARTIAL",
                "analytics": "PARTIAL",
                "story": "NOT_IMPLEMENTED",
                "treasury": "PARTIAL",
                "procurement": "NOT_IMPLEMENTED",
                "financing": "NOT_IMPLEMENTED",
            },
            "events": [EventView.model_validate(e).model_dump() for e in reversed(recent)],
        }


def read_events(engine: Engine, after: int, limit: int) -> dict:
    from app.maintenance import ledger_floor  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        # A history that was deleted is not read back: the ledger begins at the reset line.
        after = max(after, ledger_floor(session) - 1)
        events = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.sequence > after)
            .order_by(DomainEvent.sequence)
            .limit(limit + 1)
        ).all()
        selected = events[:limit]
        return {
            "schema_version": 1,
            "events": [EventView.model_validate(e).model_dump() for e in selected],
            "next_cursor": selected[-1].sequence if selected else after,
            "has_more": len(events) > limit,
        }
