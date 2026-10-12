import hashlib
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, and_, func, inspect, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.agents.models import AgentRun
from app.config import Settings
from app.models import (
    PAID_MEDIA_APPROVALS,
    ApprovalRequest,
    CommandRecord,
    DomainEvent,
    OwnerPolicy,
    Room,
    Studio,
)
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


#: The autonomy mode a NEW studio starts in (AR-09). A buyer's fresh install is MANUAL: agents
#: draft and the Owner moves each stage, as 51_AUTONOMY_MODE_SEMANTICS asks of a studio that has
#: no burn-in yet. Only his versioned command promotes it. Migration 0043's AUTONOMOUS_CEO stays
#: the column default and the recorded reading for the studios that existed then; an existing
#: row is never changed by a bootstrap.
NEW_STUDIO_AUTONOMY_MODE = "MANUAL"


def bootstrap_studio(
    engine: Engine, settings: Settings, *, autonomy_mode: str = NEW_STUDIO_AUTONOMY_MODE
) -> None:
    """Create the studio row, its policy and its first room, once; a second call changes nothing.

    ``autonomy_mode`` is the mode a studio created by this call starts in: MANUAL for a fresh
    install (scripts/bootstrap.py); the suite's studio passes the Owner's AUTONOMOUS_CEO.
    """
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
        # The mode only where the column exists (0043 and later): an older schema keeps its
        # own default, as every later column does.
        columns = {c["name"] for c in inspect(session.connection()).get_columns("owner_policy")}
        if "autonomy_mode" in columns:
            if autonomy_mode not in AUTONOMY_RANK:
                raise ValueError(f"Unknown autonomy mode: {autonomy_mode}")
            session.execute(
                update(OwnerPolicy).where(OwnerPolicy.id == 1).values(autonomy_mode=autonomy_mode)
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
    paid_rule, paid_threshold = paid_media_policy(policy)
    return PolicyView(
        version=policy.version,
        autonomy_stopped=policy.autonomy_stopped,
        # A row written before the column existed reads as None; TEST is the safe reading.
        environment=policy.environment or "TEST",  # type: ignore[arg-type]
        # A row written before the column existed reads as None. MANUAL is the safe reading
        # of an unknown mode: it grants the least.
        autonomy_mode=policy.autonomy_mode or "MANUAL",  # type: ignore[arg-type]
        public_publish_enabled=public,
        # Read as may_act reads it: anything incomplete or unknown shows as the strictest.
        paid_media_approval=paid_rule,  # type: ignore[arg-type]
        paid_media_approval_over_usd=paid_threshold,
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


#: The event a restored database's guard is recorded under, and the jobs it turns off.
RESTORE_GUARD_EVENT = "owner.restore_guard_applied"
RESTORE_GUARD_JOBS = ("daily_main",)


def apply_restore_guard(
    engine: Engine, *, restored_from: str, correlation_id: str
) -> dict[str, Any]:
    """The restore guard (document 25): a database put back from a backup starts stopped.

    Called by the Owner's own restore (`app.backup.restore_backup`, run from
    scripts/restore.py), never by an agent: the autonomy stop is set, the environment is
    TEST and the daily run's clock is off, so nothing is bought or published from a restored
    past until he has looked at it and turned them back on himself, from the page. One
    RESTORE_GUARD_EVENT records what was there before.
    """
    from app.workflows.models import ScheduledJob  # noqa: PLC0415 - workflows import us

    with Session(engine) as session, session.begin():
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise RuntimeError("Studio has not been initialized")
        before = {
            "autonomy_stopped": bool(policy.autonomy_stopped),
            "environment": policy.environment,
        }
        jobs = list(
            session.scalars(select(ScheduledJob).where(ScheduledJob.name.in_(RESTORE_GUARD_JOBS)))
        )
        active_before = [job.name for job in jobs if job.is_active]
        policy.autonomy_stopped = True
        policy.environment = "TEST"
        policy.version += 1
        policy.updated_at = utc_now()
        for job in jobs:
            job.is_active = False
        reason = (
            "Baza de date a fost restaurată dintr-o copie de siguranță: studioul pornește cu "
            "STOP autonomie, în mediul TEST și cu rularea zilnică oprită. Le repornești tu, din "
            "pagină, după ce verifici studioul."
        )
        event = append_event(
            session,
            RESTORE_GUARD_EVENT,
            "owner_policy",
            "1",
            policy.version,
            {
                "restored_from": restored_from,
                "before": before,
                "jobs_turned_off": active_before,
                "reason": reason,
            },
            correlation_id,
        )
        return {
            "autonomy_stopped": True,
            "environment": "TEST",
            "jobs_turned_off": active_before,
            "before": before,
            "event_id": event.event_id,
            "reason_ro": reason,
        }


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
    # The paid steps of a film on its shooting sheet (the Owner's rule of 2026-09-26, after
    # the Nepal film bought two whole films unasked). The stills are a few dozen credits
    # inside the budget, so T2 like `media.paid_generation`; the hero test shot, the rest of
    # the motion and a one-scene redo are the dear part, T3 like a render over threshold.
    # None is T4: T4 is refused in every mode, and a step nobody can ever buy is not a gate.
    # Whether the Owner is asked is not the tier's decision but `paid_media_approval`'s,
    # read in `may_act` (see `PAID_MEDIA_STEPS`).
    "media.stills_purchase": "T2",
    "media.test_shot": "T3",
    "media.motion_purchase": "T3",
    "media.scene_redo": "T3",
    # A character's reference pictures, the Owner's own press (2026-10-02, MONEY-13): a few
    # image credits inside the budget, so T2 like the stills. It had a label and no tier, so
    # the kernel would have refused it as unclassified had anything asked.
    "media.character_reference_set": "T2",
    # The RunPod Serverless GPU (2026-10-08, the Owner's cards). Switching it OFF spends
    # nothing and stops spending: T0, and `may_act` allows it before every other check, under
    # STOP AUTONOMY too (ADR-GPU-OFF-ALWAYS). Switching it ON is allowed only inside a paid
    # step of a film the kernel already lets run, under its cap (`_gpu_on_verdict`).
    "infra.gpu_off": "T0",
    "infra.gpu_on": "T2",
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


def _hours_setting(name: str, default: int) -> int:
    """One of the Owner's hour settings, read the way `approval_expires_after_hours` explains."""
    from app.config import Settings  # noqa: PLC0415

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001
        settings = None
    hours = getattr(settings, name, default)
    try:
        return max(1, int(hours))
    except (TypeError, ValueError):
        return default


#: What the paid-step questions fall back to with no usable settings (2026-10-02, AR-05).
DEFAULT_PAID_MEDIA_APPROVAL_EXPIRES_HOURS = 48


def paid_media_approval_expires_hours() -> int:
    """How long a question on a paid step of a film stands, from
    `Settings.paid_media_approval_expires_hours` (48 h by default): the day that raised it
    runs again 24 h later, so a one-day question was often dead before his yes could be spent
    (AR-05). Read like `approval_expires_after_hours`."""
    return _hours_setting(
        "paid_media_approval_expires_hours", DEFAULT_PAID_MEDIA_APPROVAL_EXPIRES_HOURS
    )


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
    return _hours_setting("approval_expires_after_hours", DEFAULT_APPROVAL_EXPIRES_AFTER_HOURS)


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
    "media.stills_purchase": "Imaginile unui film, înainte de orice mișcare",
    "media.test_shot": "Cadrul de probă al unui film, care rămâne în film",
    "media.motion_purchase": "Mișcarea pentru restul scenelor unui film",
    "media.scene_redo": "Refacerea unei singure scene a unui film",
    "infra.gpu_off": "Oprirea GPU-ului RunPod",
    "infra.gpu_on": "Pornirea GPU-ului RunPod într-un pas plătit aprobat",
}

#: The paid steps of a film's shooting sheet, each named by the step the sheet calls it. For
#: these actions `may_act` reads the Owner's `paid_media_approval` before the mode may allow
#: them, and binds his answer to the sheet's `plan_hash`.
PAID_MEDIA_STEPS: dict[str, str] = {
    "media.stills_purchase": "stills",
    "media.test_shot": "test_shot",
    "media.motion_purchase": "motion",
    "media.scene_redo": "scene_redo",
}

#: The value a missing, unknown or incomplete setting is read as: the strictest one.
STRICTEST_PAID_MEDIA_APPROVAL = PAID_MEDIA_APPROVALS[0]

#: The refusal of a paid step the studio would buy unasked in PRODUCTION with no active daily
#: budget (2026-10-02, MONEY-06 / AR-07): fail closed, never "no budget, no limit".
BLOCKED_NO_BUDGET = "BLOCKED_NO_BUDGET"
#: Where the Owner sets the budget, in the page's own words (`preflight.BUDGET_PLACE`).
BUDGET_PLACE_WORDS = "Autonomie → Buget și cheltuieli"


#: The step the sheet's narration question is bound to (`shooting_sheet.narration_gate`).
NARRATION_STEP = "assemble"
#: The task the Owner's yes on a paid step of a film queues (2026-10-02, A6 / AR-05): the film
#: is walked on at once (`runbook.stages.continue_film`) instead of at the next daily run.
FILM_CONTINUE_TASK = "FILM_CONTINUE"


def is_paid_media_question(action: str, proposed_diff: dict | None) -> bool:
    """Whether a question is about a paid step of a film: one of `PAID_MEDIA_STEPS`, or the
    sheet's narration (a paid generation bound to a sheet's ``plan_hash`` at the assemble
    step). Those stand for `paid_media_approval_expires_hours`, and his yes on one continues
    the film the same day."""
    if action in PAID_MEDIA_STEPS:
        return True
    diff = proposed_diff if isinstance(proposed_diff, dict) else {}
    return (
        action in ("media.paid_generation", "media.paid_generation_over_threshold")
        and diff.get("step") == NARRATION_STEP
        and bool(diff.get("plan_hash"))
    )


def queue_film_continue(
    session: Session, storyboard_id: str, *, key: str, payload: dict
) -> str | None:
    """Queue `FILM_CONTINUE_TASK` for one film inside the caller's transaction, once per
    ``key``; returns the task id (the standing one when the key was queued before).

    Only in PRODUCTION: in TEST the daily run buys nothing from a paid vendor (A3), so there
    is nothing for a continuation to do there. The task is written in the same transaction as
    the decision that causes it, so an answer is never recorded without its continuation."""
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415 - workflows import us

    if not storyboard_id:
        return None
    policy = session.get(OwnerPolicy, 1)
    if str(getattr(policy, "environment", None) or "TEST") != "PRODUCTION":
        return None
    standing = session.scalar(select(TaskQueueItem).where(TaskQueueItem.idempotency_key == key))
    if standing is not None:
        return str(standing.id)
    now = utc_now()
    task = TaskQueueItem(
        id=str(uuid4()),
        workflow_id=None,
        step_id=None,
        task_type=FILM_CONTINUE_TASK,
        payload={"storyboard_id": storyboard_id, **payload},
        # Above the scheduled work, below the day's own re-attempt (5): his answer is the
        # freshest decision in the studio.
        priority=4,
        status="QUEUED",
        attempts=0,
        # A continuation that failed is not re-run blind: the next daily run walks the film.
        max_attempts=1,
        backoff_seconds=60,
        next_attempt_at=now,
        lease_token=None,
        lease_expires_at=None,
        idempotency_key=key,
        error_detail=None,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.flush()
    return task.id


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


def approval_answers(session: Session, approval_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """The Owner's answers to the questions named, as plain values: what he answered, when the
    question expires, whether his yes was spent and his note. Reads only. The Director reads
    what came of the questions her decisions raised (2026-10-10) through here, so the row that
    carries his authority stays in this module (`test_phase_dg_closure_adversary`)."""
    found: dict[str, dict[str, Any]] = {}
    for approval_id in approval_ids:
        row = session.get(ApprovalRequest, approval_id)
        if row is not None:
            found[approval_id] = {
                "result": row.result,
                "expires_at": row.expires_at,
                "consumed_at": row.consumed_at,
                "note": row.note,
            }
    return found


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


def approval_context(request: ApprovalRequest) -> dict | None:
    """What a film's paid question is about, for the page (PAGE-03): the step it buys, the first
    12 characters of the plan its yes is bound to, and the storyboard. None for any other
    question, so the page approves those the way it always has."""
    if not is_paid_media_question(request.action, request.proposed_diff):
        return None
    diff = request.proposed_diff if isinstance(request.proposed_diff, dict) else {}
    step = diff.get("step") or PAID_MEDIA_STEPS.get(request.action)
    plan_hash = diff.get("plan_hash")
    return {
        "step": str(step) if step else None,
        "plan_hash": str(plan_hash)[:12] if plan_hash else None,
        "storyboard_id": request.subject or None,
    }


def film_titles(session: Session, requests: list[ApprovalRequest]) -> dict[str, str]:
    """The titles of the storyboards these paid questions are about, by storyboard id."""
    from app.media.models import Storyboard  # noqa: PLC0415 - media imports the kernel

    ids = {r.subject for r in requests if r.subject and approval_context(r) is not None}
    if not ids:
        return {}
    return {
        board.id: board.title
        for board in session.scalars(select(Storyboard).where(Storyboard.id.in_(ids)))
    }


def approval_view(request: ApprovalRequest, *, film_title: str | None = None) -> ApprovalView:
    """One request as the Owner reads it, with the word for a cost nobody could compute.

    A paid step of a film is asked with its cap, the most his yes lets it spend (MONEY-08),
    so its figure is named «plafon»; the expected cost is in the evidence beside it. A film's
    paid question also carries its step, plan and storyboard (`approval_context`) and, when
    the caller read it, the film's title."""
    if request.cost_usd is None:
        cost_label = COST_UNKNOWN
    elif request.action in PAID_MEDIA_STEPS:
        cost_label = f"plafon {request.cost_usd} USD"
    else:
        cost_label = f"{request.cost_usd} USD"
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
        cost_label=cost_label,
        reversible=bool(request.reversible),
        expires_at=request.expires_at,
        created_at=request.created_at,
        result=request.result,
        approver=request.approver,
        note=request.note,
        decided_at=request.decided_at,
        context=approval_context(request),
        film_title=film_title,
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
        requests = list(
            session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.result == "PENDING", ApprovalRequest.expires_at > now)
                .order_by(ApprovalRequest.created_at.desc())
            )
        )
        titles = film_titles(session, requests)
        return [
            approval_view(request, film_title=titles.get(request.subject or ""))
            for request in requests
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
        # His yes on a paid step of a film continues that film now, not at the next daily run
        # (A6 / AR-05): queued in this transaction, once per answer.
        continue_task_id = (
            queue_film_continue(
                session,
                str(request.subject or ""),
                key=f"film-continue-{request.subject}-{request.id}",
                payload={
                    "approval_id": request.id,
                    "action": request.action,
                    "cause": f"approval:{request.id}",
                },
            )
            if command.decision == "APPROVED"
            and is_paid_media_question(request.action, request.proposed_diff)
            else None
        )
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
                "continue_task_id": continue_task_id,
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
    hours = (
        paid_media_approval_expires_hours()
        if is_paid_media_question(action, proposed_diff)
        else approval_expires_after_hours()
    )
    expires = datetime.now(UTC) + timedelta(hours=hours)
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


#: The event written when a question can no longer buy anything and is closed unanswered.
APPROVAL_WITHDRAWN_EVENT = "governance.approval_withdrawn"


def withdraw_superseded_approvals(
    session: Session,
    *,
    action: str,
    subject: str,
    new_plan_hash: str,
    keep: str | None,
    reason: str,
    correlation_id: str,
) -> list[str]:
    """Close the Owner's unanswered questions about an older plan of this action and subject.

    His yes is spent only for the plan it names, so a question about a plan the studio has
    replaced (a different ``plan_hash`` in its ``proposed_diff``) can no longer buy anything.
    Each is closed as EXPIRED, never answered, with ``reason`` as its note and an
    ``APPROVAL_WITHDRAWN_EVENT``; ``keep`` (the question that can still buy) and any question
    already carrying a note are left alone. The caller decides *that* a plan was superseded
    and words the reason; only this module, the Owner's command kernel, touches the row.
    Returns the ids withdrawn, in the order they were found.
    """
    withdrawn: list[str] = []
    for request in session.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.action == action,
            ApprovalRequest.subject == subject,
            ApprovalRequest.result.in_(("PENDING", "EXPIRED")),
            ApprovalRequest.decided_at.is_(None),
        )
    ):
        if request.id == keep or request.note:
            continue
        asked_for = request.proposed_diff if isinstance(request.proposed_diff, dict) else {}
        if asked_for.get("plan_hash") == new_plan_hash:
            continue
        previous = request.result
        request.result = "EXPIRED"
        request.note = reason
        append_event(
            session,
            APPROVAL_WITHDRAWN_EVENT,
            "owner_approval_request",
            request.id,
            2,
            {
                "action": action,
                "subject": subject,
                "previous_result": previous,
                "old_plan_hash": asked_for.get("plan_hash"),
                "new_plan_hash": new_plan_hash,
                "replaced_by": keep,
                "reason": reason,
                "withdrawn_at": utc_now(),
            },
            correlation_id,
        )
        withdrawn.append(request.id)
    return withdrawn


def withdraw_subject_approvals(
    session: Session, *, subject: str, reason: str, correlation_id: str
) -> list[str]:
    """Close every unanswered question about one subject: a film the Owner closed.

    Nothing about the subject can be bought any more, so no question about it can buy
    anything: each PENDING request with this ``subject`` (whatever its action, plan or expiry)
    is closed as EXPIRED, never answered, with ``reason`` as its note and an
    ``APPROVAL_WITHDRAWN_EVENT``, as `withdraw_superseded_approvals` closes a question about a
    replaced plan. An answered request is left as it is: his answer is history. Only this
    module, the Owner's command kernel, touches the row; the caller decides *that* the subject
    is closed and words the reason. Returns the ids withdrawn, oldest first.
    """
    if not subject:
        return []
    withdrawn: list[str] = []
    for request in session.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.subject == subject,
            ApprovalRequest.result == "PENDING",
            ApprovalRequest.decided_at.is_(None),
        )
        .order_by(ApprovalRequest.created_at)
    ):
        request.result = "EXPIRED"
        request.note = reason
        append_event(
            session,
            APPROVAL_WITHDRAWN_EVENT,
            "owner_approval_request",
            request.id,
            2,
            {
                "action": request.action,
                "subject": subject,
                "previous_result": "PENDING",
                "reason": reason,
                "why": "SUBJECT_CLOSED",
                "withdrawn_at": utc_now(),
            },
            correlation_id,
        )
        withdrawn.append(request.id)
    return withdrawn


def paid_media_policy(policy: OwnerPolicy | None) -> tuple[str, float | None]:
    """The Owner's `paid_media_approval` as `may_act` reads it: (value, threshold in USD).

    The database refuses any other value (migration 0048), but this is the one place a
    wrong reading would spend money, so anything that is not a complete, known setting — a
    missing row, an unknown value, OVER_USD without a usable threshold — is read as the
    strictest one, EVERY_PAID_STEP. Never as MODE: an unreadable rule must ask, not allow.
    """
    value = getattr(policy, "paid_media_approval", None)
    if value not in PAID_MEDIA_APPROVALS:
        return STRICTEST_PAID_MEDIA_APPROVAL, None
    if value != "OVER_USD":
        return str(value), None
    raw = getattr(policy, "paid_media_approval_over_usd", None)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return STRICTEST_PAID_MEDIA_APPROVAL, None
    threshold = float(raw)
    if not math.isfinite(threshold) or threshold < 0:
        return STRICTEST_PAID_MEDIA_APPROVAL, None
    return "OVER_USD", threshold


def has_active_daily_budget(session: Session) -> bool:
    """Whether the Owner has an active DAILY spending budget, read in the caller's session."""
    from app.economy.models import SpendingBudget  # noqa: PLC0415 - economy imports services

    found = session.scalar(
        select(SpendingBudget.id)
        .where(SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True))
        .limit(1)
    )
    return found is not None


def buys_paid_media_unasked(policy: OwnerPolicy | None) -> bool:
    """Whether the Owner's rule and mode let the studio buy at least one paid step of a film
    without asking him: MODE, or OVER_USD below his threshold, under a mode that allows the
    cheapest of those steps (the T2 stills under SUPERVISED, every step under AUTONOMOUS_CEO).
    The preflight's budget line and `may_act`'s fail-closed refusal read the same answer."""
    rule, _threshold = paid_media_policy(policy)
    if rule == STRICTEST_PAID_MEDIA_APPROVAL:
        return False
    mode = str(getattr(policy, "autonomy_mode", None) or "MANUAL")
    cheapest = min(ACTION_RISK_TIERS[action] for action in PAID_MEDIA_STEPS)
    return cheapest <= MODE_ALLOWS.get(mode, "T1")


def _usd_words(amount: float) -> str:
    """An amount of dollars the Romanian way: 12,24 and 5 rather than 12.24 and 5.00."""
    text = f"{amount:.2f}".replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def _paid_media_context(step: str, context: dict | None) -> dict | None:
    """The plan a paid media step is asked about, or None when the caller named none.

    The answer is bound to this dict (`proposed_diff`, then `_context_matches`), so it must
    carry the sheet's `plan_hash`: an answer bound to nothing would match every plan. The
    step is the action's own; a caller that names another step is describing another
    purchase and gets no plan. `cap_credits` is always a key, None when the caller did not
    give one, so the Owner's question and his answer have the same shape.
    """
    if not isinstance(context, dict):
        return None
    plan_hash = context.get("plan_hash")
    if not isinstance(plan_hash, str) or not plan_hash.strip():
        return None
    if context.get("step", step) != step:
        return None
    return {**context, "step": step, "cap_credits": context.get("cap_credits")}


def _ask_or_spend(
    session: Session,
    action: str,
    tier: str,
    *,
    requester: str,
    subject: str,
    evidence: str | None,
    cost_usd: float | None,
    context: dict | None,
    ask_owner: bool,
    waiting: str,
) -> tuple[str, str, str | None]:
    """The one way the Owner's answer is read and spent: (status, reason, approval id).

    His standing answer about this subject in this exact context is looked for; a no is
    the answer, a yes is spent here — before the act it authorises — and a missing answer
    becomes one request carrying `context` as its proposed diff. With `ask_owner` False
    nothing is read, written or spent: the caller only wants to know that he would be asked.
    """
    if not ask_owner:
        return "NEEDS_APPROVAL", waiting, None
    answered = _answered_approval(session, action, subject, context)
    if answered is not None and answered.result == "REFUSED":
        return "REFUSED_BY_OWNER", _owner_refusal_reason(answered), answered.id
    if answered is not None:
        _spend_approval(session, answered)
        return "ALLOWED", "", answered.id
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
    return "NEEDS_APPROVAL", waiting, request.id


#: Why `infra.gpu_off` is always allowed, in the Owner's words.
GPU_OFF_ALLOWED_WORDS = (
    "Oprirea GPU-ului nu cheltuie nimic și este permisă oricând, inclusiv la STOP AUTONOMIE."
)
#: `infra.gpu_on` outside a paid step the kernel lets run.
BLOCKED_NOT_IN_STEP = "BLOCKED_NOT_IN_STEP"
GPU_NOT_IN_STEP_WORDS = "GPU-ul se pornește doar în interiorul unui pas plătit aprobat."
#: `infra.gpu_on` while the Owner has not accepted the card that lets agents switch it on.
BLOCKED_INFRA_DISABLED = "BLOCKED_INFRA_DISABLED"
GPU_INFRA_DISABLED_WORDS = (
    "Agenții nu au voie încă să pornească GPU-ul RunPod; acceptă cardul din fereastra Decizii."
)


def _runpod_infra_allowed(session: Session, integration_id: object) -> bool:
    """The Owner's card «Agenții pot porni singuri GPU-ul RunPod …» was accepted for this
    RunPod connection (its ``allow_infra_actions`` is true)."""
    from app.integrations.models import Integration  # noqa: PLC0415

    if not isinstance(integration_id, str) or not integration_id:
        return False
    row = session.get(Integration, integration_id)
    if row is None or row.kind != "runpod" or not isinstance(row.config, dict):
        return False
    return str(row.config.get("allow_infra_actions", "")).strip().lower() in ("true", "1", "yes")


def _gpu_on_verdict(
    session: Session,
    *,
    requester: str,
    subject: str,
    cost_usd: float | None,
    context: dict | None,
) -> tuple[str, str]:
    """`infra.gpu_on`, after the stop, T4 and safe mode (2026-10-08, the Owner's cards).

    ALLOWED only when ``context.step_action`` is a paid step of a film, the Owner accepted the
    RunPod card, and that step itself would run now: the kernel allows it; or it needs his yes
    and ``approval_id`` names his yes for this step and plan (granted, or already spent by the
    step); or it is his own press and the answer is one about agents acting unasked
    (`media.services.OWNER_PRESS_PASSES`). The inner question is read with ``ask_owner=False``:
    nothing is asked, written or spent here.
    """
    ctx = context if isinstance(context, dict) else {}
    step_action = ctx.get("step_action")
    if not isinstance(step_action, str) or step_action not in PAID_MEDIA_STEPS:
        return BLOCKED_NOT_IN_STEP, GPU_NOT_IN_STEP_WORDS
    if not _runpod_infra_allowed(session, ctx.get("integration_id")):
        return BLOCKED_INFRA_DISABLED, GPU_INFRA_DISABLED_WORDS
    plan_hash = ctx.get("plan_hash")
    inner = may_act(
        session,
        step_action,
        requester=requester,
        subject=subject,
        cost_usd=cost_usd,
        context={"plan_hash": plan_hash},
        ask_owner=False,
    )
    if inner["allowed"]:
        return "ALLOWED", ""
    status = str(inner["status"])
    approval_id = ctx.get("approval_id")
    if status == "NEEDS_APPROVAL" and isinstance(approval_id, str) and approval_id:
        answer = session.get(ApprovalRequest, approval_id)
        diff = answer.proposed_diff if answer is not None else None
        if (
            answer is not None
            and answer.action == step_action
            and answer.subject == subject
            and answer.result == "APPROVED"
            and isinstance(diff, dict)
            and diff.get("plan_hash") == plan_hash
            and (answer.consumed_at is not None or answer.expires_at > utc_now())
        ):
            return "ALLOWED", ""
    if ctx.get("owner_press") is True:
        from app.media.services import OWNER_PRESS_PASSES  # noqa: PLC0415 - media imports us

        if status in OWNER_PRESS_PASSES:
            return "ALLOWED", ""
    return BLOCKED_NOT_IN_STEP, f"{GPU_NOT_IN_STEP_WORDS} {inner['reason']}".strip()


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

    **The paid steps of a film** (`PAID_MEDIA_STEPS`: stills, the hero test shot, the rest of
    the motion, a one-scene redo) pass one more gate, after the stop, the unclassified check,
    T4 and safe mode and before the mode may allow them: the Owner's `paid_media_approval`.
    EVERY_PAID_STEP (the default) asks him in every mode, AUTONOMOUS_CEO included; OVER_USD
    asks above his threshold and whenever the cost is unknown; MODE hands the step back to
    the mode. `context` must carry the shooting sheet's `plan_hash` — the step is filled in
    from the action — and his answer is spent only for that same plan, so one yes buys
    exactly one step of one plan. Only his `change_paid_media_approval` moves the setting;
    nothing a caller passes here does. For these steps ``cost_usd`` is the step's cap, the
    most it may spend under his yes (2026-10-02, MONEY-08), and OVER_USD compares his
    threshold with it. In PRODUCTION a step the rule and the mode would let through unasked is
    refused BLOCKED_NO_BUDGET while no DAILY budget is active (MONEY-06): fail closed.
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

    if action == "infra.gpu_off":
        # First, before the stop, T4 and safe mode: switching the GPU off spends nothing and
        # only stops spending (ADR-GPU-OFF-ALWAYS, 51's dated amendment).
        return verdict("ALLOWED", GPU_OFF_ALLOWED_WORDS)

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

    if action == "infra.gpu_on":
        # After the stop, T4 and safe mode; never the mode's own ALLOWED: the GPU goes on only
        # inside a paid step the kernel already lets run (or the Owner's own press of it).
        status, reason = _gpu_on_verdict(
            session, requester=requester, subject=subject, cost_usd=cost_usd, context=context
        )
        return verdict(status, reason)

    step = PAID_MEDIA_STEPS.get(action)
    if step is not None:
        # The Owner's gate on paid media (his policy, stricter than 51's modes): read after
        # every refusal above, so a stop, safe mode or T4 leaves his yes unspent, and before
        # the mode's ALLOWED, so AUTONOMOUS_CEO no longer buys a film's motion unasked.
        plan = _paid_media_context(step, context)
        if plan is None:
            return verdict(
                "BLOCKED_NO_PLAN",
                f"«{action_words(action)}» se cumpără doar după foaia de filmare: cererea nu "
                "numește planul (plan_hash) pe care Proprietarul l-a văzut, așa că nu se "
                "cere și nu se cheltuie nicio aprobare.",
            )
        # Whatever decides below — the Owner or the mode — decides about this plan.
        context = plan
        rule, threshold = paid_media_policy(policy)
        # 2026-10-05, the Owner: «pe CEO autonom îmi cere acordul doar dacă generează cu
        # bani». A step whose cap is exactly 0 — the local ComfyUI selection — cannot spend
        # anything, so under AUTONOMOUS_CEO the mode alone decides it, whatever rule says;
        # a step that can spend even a cent still follows his `paid_media_approval`, and the
        # modes he chose to be asked in (MANUAL, SUPERVISED) keep asking about free steps too.
        free = cost_usd is not None and cost_usd == 0
        why = None
        if free and mode == "AUTONOMOUS_CEO":
            pass
        elif rule == "EVERY_PAID_STEP":
            why = "Politica Proprietarului cere aprobarea fiecărui pas plătit al unui film"
        elif rule == "OVER_USD" and threshold is not None:
            if cost_usd is None:
                why = (
                    f"Costul pentru «{action_words(action)}» este necunoscut, deci nu se "
                    f"poate spune că e sub pragul de {_usd_words(threshold)} USD al "
                    "Proprietarului"
                )
            elif cost_usd > threshold:
                # The callers pass the step's cap, the most his yes lets it spend (MONEY-08):
                # the expected cost is lower and stays in the evidence.
                why = (
                    f"«{action_words(action)}» are plafonul de {_usd_words(cost_usd)} USD, "
                    f"peste pragul de {_usd_words(threshold)} USD al Proprietarului"
                )
        if why is not None:
            status, reason, approval_id = _ask_or_spend(
                session,
                action,
                tier,
                requester=requester,
                subject=subject,
                evidence=evidence,
                cost_usd=cost_usd,
                context=context,
                ask_owner=ask_owner,
                waiting=(
                    f"{why}: «{action_words(action)}» ({tier}) așteaptă aprobarea lui pe "
                    "foaia de filmare."
                ),
            )
            return verdict(status, reason, approval_id)
        # MODE, or under his threshold: the autonomy mode decides, exactly as it does today,
        # except that in PRODUCTION nothing is bought unasked without a daily limit (fail
        # closed, MONEY-06 / AR-07): with no budget `reserve_spend` refuses nothing, and a fresh
        # install switched to AUTONOMOUS_CEO + MODE would buy on nothing but each sheet's cap.
        # A free step is exempt: its cap is 0, so it spends nothing, budget or no budget.
        if (
            not free
            and tier <= MODE_ALLOWS.get(mode, "T1")
            and str(policy.environment or "TEST") == "PRODUCTION"
            and not has_active_daily_budget(session)
        ):
            return verdict(
                BLOCKED_NO_BUDGET,
                f"Politica ta lasă studioul să cumpere «{action_words(action)}» fără să te "
                "întrebe, dar nu există niciun buget zilnic activ: în producție nu se cumpără "
                "nimic neîntrebat fără o limită zilnică. Setează bugetul zilnic în "
                f"{BUDGET_PLACE_WORDS}.",
            )

    if tier <= MODE_ALLOWS.get(mode, "T1"):
        return verdict("ALLOWED", "")

    if mode == "SUPERVISED" and tier == "T3":
        # A caller asking on behalf of something it cannot name — the daily run's stage
        # wrapper, before it knows which film — passes ask_owner=False, gets the answer and
        # leaves the Owner alone: nothing is written, nothing of his is spent, and the caller
        # that can name the film asks it properly.
        #
        # His answer is read only here, and only under the mode that asks. A yes given while
        # the studio was SUPERVISED is not a way past MANUAL, which he chose afterwards
        # precisely to be asked about everything; the mode branch above has already refused
        # that case without ever looking for an answer to spend.
        words = f"Modul de autonomie este supravegheat: acțiunea «{action_words(action)}» ({tier})"
        status, reason, approval_id = _ask_or_spend(
            session,
            action,
            tier,
            requester=requester,
            subject=subject,
            evidence=evidence,
            cost_usd=cost_usd,
            context=context,
            ask_owner=ask_owner,
            waiting=(
                f"{words} așteaptă aprobarea Proprietarului."
                if ask_owner
                else f"{words} cere aprobarea Proprietarului."
            ),
        )
        return verdict(status, reason, approval_id)

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


# ---------------------------------------------------------------------------
# SetPaidMediaApproval: when a paid step of a film asks the Owner
# ---------------------------------------------------------------------------


class PaidMediaApprovalRefused(Exception):
    """Someone other than the Owner tried to change when paid media asks him."""


class PaidMediaApprovalCommand(BaseModel):
    """The Owner sets when a paid step of a film (stills, hero test, motion, one-scene redo)
    waits for his yes: EVERY_PAID_STEP, OVER_USD with a threshold, or MODE.

    The same shape as the mode and the environment — versioned, idempotent by command id,
    recorded in the ledger — and the same shape the database accepts (migration 0048): a
    threshold exactly when the value is OVER_USD, never negative. Who issued it is not a
    field: it is the caller's `issued_by`, so no request body can name itself the Owner.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    paid_media_approval: Literal["EVERY_PAID_STEP", "OVER_USD", "MODE"]
    over_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _threshold_only_with_over_usd(self) -> "PaidMediaApprovalCommand":
        if (self.paid_media_approval == "OVER_USD") != (self.over_usd is not None):
            raise ValueError("Pragul în USD se dă doar, și obligatoriu, pentru OVER_USD.")
        return self


class PaidMediaApprovalResult(BaseModel):
    command_id: str
    status: Literal["COMMITTED", "NO_CHANGE"]
    paid_media_approval: str
    over_usd: float | None
    version: int
    event_id: str | None


#: What every agent is told when the rule moves, in the Owner's language.
PAID_MEDIA_MEMORY = {
    "EVERY_PAID_STEP": (
        "Proprietarul aprobă pe foaia de filmare fiecare pas plătit al unui film (imaginile, "
        "cadrul de probă, mișcarea, refacerea unei scene), în orice mod de autonomie. Un "
        "răspuns cumpără un singur pas, pentru un singur plan."
    ),
    "OVER_USD": (
        "Proprietarul aprobă pe foaia de filmare orice pas plătit al unui film care costă "
        "peste {threshold} USD sau al cărui cost nu se știe; sub prag decide modul de autonomie."
    ),
    "MODE": (
        "Proprietarul lasă pașii plătiți ai unui film în seama modului de autonomie; foaia "
        "de filmare și plafonul ei rămân obligatorii."
    ),
}


def change_paid_media_approval(
    engine: Engine, command: PaidMediaApprovalCommand, *, issued_by: str
) -> PaidMediaApprovalResult:
    """The Owner's command, and only his, that moves `owner_policy.paid_media_approval`.

    `issued_by` is keyword-only with no default: the route that serves the Owner's page
    names him after authenticating him, and every other caller — an agent's tool, the
    developer AUTORUN, the daily run — has to say who it is and is refused. Developer
    AUTORUN does not enable product autonomy, and an agent cannot loosen the gate it is
    waiting at. The refusal writes nothing.

    Otherwise it is the environment's command: idempotent by command id, refusing a stale
    version, one `owner.paid_media_approval_changed` event with the old rule and the new,
    the version bumped only when something changed, and one standing memory for the agents.
    """
    if issued_by != "owner":
        raise PaidMediaApprovalRefused(
            "Doar Proprietarul poate schimba când îl întreabă un pas plătit al unui film; "
            f"comanda venită de la «{issued_by or 'necunoscut'}» nu a schimbat nimic."
        )
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))
        previous = recall_command(session, command_id, payload_hash)
        if previous is not None:
            return PaidMediaApprovalResult.model_validate(previous)
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise RuntimeError("Studio has not been initialized")
        if command.expected_version != policy.version:
            raise CommandConflict("Policy changed; refresh the snapshot and retry")

        before = (policy.paid_media_approval, policy.paid_media_approval_over_usd)
        after = (command.paid_media_approval, command.over_usd)
        event_id = None
        changed = before != after
        if changed:
            policy.paid_media_approval, policy.paid_media_approval_over_usd = after
            policy.version += 1
            policy.updated_at = utc_now()
            event = append_event(
                session,
                "owner.paid_media_approval_changed",
                "owner_policy",
                "1",
                policy.version,
                {
                    "paid_media_approval": command.paid_media_approval,
                    "over_usd": command.over_usd,
                    "previous_paid_media_approval": before[0],
                    "previous_over_usd": before[1],
                },
                command_id,
            )
            event_id = event.event_id
            from app.agents.memory import remember  # noqa: PLC0415

            remember(
                session,
                memory_class="OWNER_POLICY",
                content=PAID_MEDIA_MEMORY[command.paid_media_approval].format(
                    threshold=_usd_words(command.over_usd or 0.0)
                ),
                source_type="owner",
                source_id=event_id,
                event_id=event_id,
            )
        result = PaidMediaApprovalResult(
            command_id=command_id,
            status="COMMITTED" if changed else "NO_CHANGE",
            paid_media_approval=policy.paid_media_approval,
            over_usd=policy.paid_media_approval_over_usd,
            version=policy.version,
            event_id=event_id,
        )
        remember_command(
            session, command_id, "SetPaidMediaApproval", payload_hash, result.model_dump()
        )
        return result


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


def studio_location(settings: Settings) -> dict:
    """Where the studio stands, as the page draws it (SELL-08): its coordinates for the sun, the
    city it names and the country whose holidays empty its street. The timezone is the studio
    row's own (``snapshot()['studio']['timezone']``)."""
    return {
        "latitude": settings.office_latitude,
        "longitude": settings.office_longitude,
        "city": settings.office_city,
        "holiday_country": settings.holiday_country,
    }


#: The demo's banner (SELL-03), on every screen of a studio started with --demo.
DEMO_BANNER_RO = "DEMO — furnizori simulați, nimic nu se publică"


def snapshot(
    engine: Engine,
    operations: dict | None = None,
    *,
    location: dict | None = None,
    demo: bool = False,
) -> dict:
    """The studio as the page reads it. ``operations`` is the running process's reading of
    its worker, disk, toolchain and backups (`app.operations.operations_reading`, passed by the
    route), for the page's banner; None outside a running studio. ``location`` is the studio's
    place from the settings (`studio_location`), and ``demo`` says the studio is the demo."""
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
        # The snapshot's events reach the page first and are the copies it keeps, so they carry
        # the register's words too (2026-10-12; `read_events` has them since 2026-10-11).
        from app.events_feed import enrich  # noqa: PLC0415 - the feed reads models only

        recent_events = enrich(
            session, [EventView.model_validate(e).model_dump() for e in reversed(recent)]
        )
        return {
            "schema_version": 1,
            "cursor": cursor,
            "captured_at": utc_now(),
            # What keeps the studio running, in the Owner's words (REL-07): the page shows
            # banner_ro when anything is wrong ("Lucrătorul nu a mai lucrat de 14 minute").
            "operations": operations,
            "studio": {
                "id": studio.id,
                "name": studio.name,
                "timezone": studio.timezone,
                "location": location,
            },
            # SELL-03: a demo studio says so on every screen; a real one carries no banner.
            "demo": {"active": True, "banner_ro": DEMO_BANNER_RO} if demo else None,
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
            # Virtual financing/procurement retired by Owner, 2026-10-08.
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
            },
            "events": recent_events,
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
        # Each event with its words for a person — the sentence, who did it, which film, the
        # office's bubble — where the studio has them (2026-10-11, the Owner's register).
        from app.events_feed import enrich  # noqa: PLC0415 - the feed reads models only

        page = {
            "schema_version": 1,
            "events": enrich(session, [EventView.model_validate(e).model_dump() for e in selected]),
            "next_cursor": selected[-1].sequence if selected else after,
            "has_more": len(events) > limit,
        }
        if since is not None:
            page["since"] = since
        return page
