import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CommandRecord, DomainEvent, OwnerPolicy, Room, Studio
from app.schemas import EventView, PolicyCommand, PolicyResult, PolicyView


class CommandConflict(Exception):
    pass


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
        session.add(OwnerPolicy(id=1, version=1, autonomy_stopped=True, updated_at=utc_now()))
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


def policy_view(policy: OwnerPolicy) -> PolicyView:
    return PolicyView(version=policy.version, autonomy_stopped=policy.autonomy_stopped)


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
                {"stopped": command.stopped, "mode": "MANUAL"},
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
            policy=policy_view(policy),
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
            "policy": policy_view(policy).model_dump(),
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
    with Session(engine) as session, session.begin():
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
