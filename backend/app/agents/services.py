"""Phase 1 agent/role/provider services and the Owner Policy Kernel gate.

The policy kernel runs before every LLM invocation:
1. the day's token ceiling (`economy.accountant.may_run_agent`)
2. autonomy_stopped check
3. agent lifecycle check
4. capability match check
5. provider health check (cached)
6. adapter presence check

The ceiling is first because it is the only one of the six that costs money to learn the
hard way: the others refuse a run that would have been wrong, this one refuses a run that
would have been paid for. A refusal is recorded as BLOCKED_BUDGET on the run row, like
every other block, and the Accountant writes to the Owner once that day.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.identity import compose_identity, seed_role_contracts
from app.agents.models import (
    Agent,
    AgentRun,
    Capability,
    ModelCapability,
    ModelRecord,
    ProviderRecord,
    Role,
    RoleCapability,
)
from app.agents.schemas import AgentRunView, AgentView, ModelView, ProviderView, RoleView
from app.config import DEFAULT_DIRECTOR_TOKEN_MULTIPLIER
from app.db import lock_for_write
from app.economy.accountant import may_run_agent
from app.models import DomainEvent, OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.services import append_event, may_act, utc_now
from app.wording import AUTONOMY_STOPPED
from app.workflows.services import append_event_with_outbox

logger = logging.getLogger("studio.agents")


# ------------------------------------------------------------------ work without a model --


def mark_working(engine: Engine, role_name: str, task_type: str, detail: str = "") -> str | None:
    """Say that the employee holding this role is working, and on what. Returns her id.

    An employee's state used to change only when she thought with a model. Recording a voice,
    generating a shot, cutting the film — the paid part of the day — ran in her name without
    touching it: Lyra read the narration (THINKING, then IDLE) and her voice was then recorded
    for five minutes while the office showed her IDLE and the ledger said nothing at all. The
    Owner watched a studio spending money look like a studio doing nothing. The office already
    draws WORKING as typing; the backend simply never said it.

    Best effort by design: a state that could not be written is logged and the work goes on.
    A paid render must never die because a status line failed.
    """
    from app.agents.memory import agent_for_role  # noqa: PLC0415

    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            agent = agent_for_role(session, role_name)
            if agent is None:
                return None
            agent.runtime_state = "WORKING"
            agent.version += 1
            append_event_with_outbox(
                session,
                "agent.state_changed",
                "agent",
                agent.id,
                agent.version,
                {"runtime_state": "WORKING", "task_type": task_type, "detail": detail[:160]},
                str(uuid4()),
            )
            return agent.id
    except Exception as exc:  # noqa: BLE001 - a status line must not stop a paid render
        logger.warning(
            "work_state_not_recorded",
            extra={"role": role_name, "state": "WORKING", "error": type(exc).__name__},
        )
        return None


def mark_idle(engine: Engine, agent_id: str | None, task_type: str) -> None:
    """The work `mark_working` announced is over. A no-op when nobody was marked."""
    if agent_id is None:
        return
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            agent = session.get(Agent, agent_id)
            if agent is None or agent.runtime_state != "WORKING":
                return  # something else already took her state; do not overwrite it
            agent.runtime_state = "IDLE"
            agent.version += 1
            append_event_with_outbox(
                session,
                "agent.state_changed",
                "agent",
                agent.id,
                agent.version,
                {"runtime_state": "IDLE", "task_type": task_type},
                str(uuid4()),
            )
    except Exception as exc:  # noqa: BLE001 - same reason as above
        logger.warning(
            "work_state_not_recorded",
            extra={"agent_id": agent_id, "state": "IDLE", "error": type(exc).__name__},
        )


@contextmanager
def at_work(engine: Engine, role_name: str, task_type: str, detail: str = "") -> Iterator[None]:
    """WORKING for exactly as long as the block runs — and IDLE again even if it fails."""
    agent_id = mark_working(engine, role_name, task_type, detail)
    try:
        yield
    finally:
        mark_idle(engine, agent_id, task_type)


# ---------------------------------------------------------------------------
# Read projections
# ---------------------------------------------------------------------------


def list_roles(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        roles = session.scalars(select(Role).order_by(Role.name)).all()
        result = []
        for role in roles:
            # The two levels are kept apart in two fields, never merged into one list: a
            # preference listed as a requirement would tell the Owner his Video Editor needs a
            # seeing model to work at all, and she works without one. `preferred_capabilities`
            # is what her page reads to say why she is on the model she is on.
            caps = session.scalars(
                select(Capability.name)
                .join(RoleCapability, RoleCapability.capability_id == Capability.id)
                .where(
                    RoleCapability.role_id == role.id,
                    RoleCapability.requirement_level == REQUIRED,
                )
            ).all()
            preferred = session.scalars(
                select(Capability.name)
                .join(RoleCapability, RoleCapability.capability_id == Capability.id)
                .where(
                    RoleCapability.role_id == role.id,
                    RoleCapability.requirement_level == PREFERRED,
                )
                .order_by(Capability.name)
            ).all()
            view = RoleView.model_validate(role)
            view.required_capabilities = list(caps)
            view.preferred_capabilities = list(preferred)
            result.append(view.model_dump())
        return result


def list_agents(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        agents = session.scalars(select(Agent).order_by(Agent.hired_at)).all()
        return [AgentView.model_validate(a).model_dump() for a in agents]


def get_agent(engine: Engine, agent_id: str) -> dict | None:
    with Session(engine) as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            return None
        return AgentView.model_validate(agent).model_dump()


class AgentLifecycleRefused(Exception):
    """A pause or a resume that would change nothing, or that no longer can: the API's 409.

    Until 2026-09-25 both accepted any state but TERMINATED and always wrote their event, so
    resuming an employee already at work recorded an «agent.resumed» that never happened and
    the register said «a reluat lucrul» about someone who had never stopped. ``code`` is the
    structured reason; the message is the Romanian sentence the Owner reads.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: The states from which a pause is a real change, and those from which a resume is.
PAUSABLE = frozenset({"ACTIVE", "HIRED"})
RESUMABLE = frozenset({"PAUSED", "SUSPENDED"})


def _refuse_lifecycle(agent: Agent, wanted: str) -> None:
    """Refuse a lifecycle change that changes nothing, in words that fit every employee.

    The employees' genders differ, so the sentences use invariable forms («în pauză», «nu mai
    face parte din companie») rather than a participle that would agree with only some.
    """
    name = agent.display_name
    state = str(agent.lifecycle or "")
    if state == "TERMINATED":
        raise AgentLifecycleRefused(
            "TERMINATED",
            f"{name} nu mai face parte din companie; o concediere nu se pune pe pauză și nu "
            "se reia.",
        )
    if wanted == "PAUSED" and state not in PAUSABLE:
        if state == "PAUSED":
            raise AgentLifecycleRefused(
                "ALREADY_PAUSED", f"{name} este deja în pauză; pauza nu ar schimba nimic."
            )
        raise AgentLifecycleRefused(
            "NOT_WORKING",
            f"{name} nu lucrează acum (suspendare hotărâtă de companie); pauza nu ar schimba "
            "nimic.",
        )
    if wanted == "ACTIVE" and state not in RESUMABLE:
        raise AgentLifecycleRefused(
            "ALREADY_ACTIVE", f"{name} lucrează deja; reluarea nu ar schimba nimic."
        )


def pause_agent(engine: Engine, agent_id: str) -> dict:
    """Pause an active agent, preventing autonomous tasks. A pause of someone who is not at
    work is refused (`AgentLifecycleRefused`) and records nothing."""
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Angajatul {agent_id} nu există.")
        _refuse_lifecycle(agent, "PAUSED")

        agent.lifecycle = "PAUSED"
        agent.version += 1
        event, _ = append_event_with_outbox(
            session,
            "agent.paused",
            "agent",
            agent_id,
            agent.version,
            {"display_name": agent.display_name, "lifecycle": "PAUSED"},
            str(uuid4()),
        )
        agent.event_id = event.event_id
        session.flush()
        return AgentView.model_validate(agent).model_dump()


def resume_agent(engine: Engine, agent_id: str) -> dict:
    """Resume a paused or suspended agent to ACTIVE. A resume of someone already at work is
    refused (`AgentLifecycleRefused`) and records nothing."""
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Angajatul {agent_id} nu există.")
        _refuse_lifecycle(agent, "ACTIVE")

        agent.lifecycle = "ACTIVE"
        agent.version += 1
        event, _ = append_event_with_outbox(
            session,
            "agent.resumed",
            "agent",
            agent_id,
            agent.version,
            {"display_name": agent.display_name, "lifecycle": "ACTIVE"},
            str(uuid4()),
        )
        agent.event_id = event.event_id
        session.flush()
        return AgentView.model_validate(agent).model_dump()


def list_providers(engine: Engine) -> list[dict]:
    with Session(engine) as session:
        providers = session.scalars(select(ProviderRecord).order_by(ProviderRecord.name)).all()
        return [ProviderView.model_validate(p).model_dump() for p in providers]


def list_provider_models(engine: Engine, provider_id: str) -> list[dict]:
    with Session(engine) as session:
        models = session.scalars(
            select(ModelRecord)
            .where(ModelRecord.provider_id == provider_id)
            .order_by(ModelRecord.model_name)
        ).all()
        result = []
        for m in models:
            caps = session.scalars(
                select(Capability.name)
                .join(ModelCapability, ModelCapability.capability_id == Capability.id)
                .where(ModelCapability.model_id == m.id)
            ).all()
            view = ModelView.model_validate(m)
            view.capabilities = list(caps)
            result.append(view.model_dump())
        return result


def sync_provider_models(
    engine: Engine,
    registry: ProviderRegistry,
    provider_id: str,
) -> list[dict]:
    """Dynamically discover models from provider and update model_record in DB.

    Discovers both local models and cloud-backed models (e.g. glm-5.2:cloud,
    kimi-k2.6:cloud, qwen3-coder:480b-cloud). Emits provider.model_discovered
    events for new models and tracks availability.
    """
    adapter = registry.get(provider_id)
    if adapter is None:
        raise ValueError(f"No adapter registered for provider {provider_id}")

    discovered_models = asyncio.run(adapter.list_models())
    now_str = utc_now()
    discovered_names = {m.model_name for m in discovered_models}

    with Session(engine) as session, session.begin():
        provider = session.get(ProviderRecord, provider_id)
        if provider is None:
            raise ValueError(f"Provider {provider_id} not found")

        existing_models = {
            m.model_name: m
            for m in session.scalars(
                select(ModelRecord).where(ModelRecord.provider_id == provider_id)
            ).all()
        }

        text_cap = session.scalars(
            select(Capability).where(Capability.name == "text_generation")
        ).first()

        def record_declared(model_id: str, declared: tuple[str, ...]) -> None:
            """Store what the provider said this model can do, in the provider's own words.

            A capability the studio has never heard of is created as a row rather than
            dropped: the vocabulary is the provider's, and the editorial gate needs to know
            which models can actually see a frame.
            """
            if not declared:
                return
            known = {
                row.name: row.id
                for row in session.scalars(
                    select(Capability).where(Capability.name.in_(list(declared)))
                )
            }
            held = set(
                session.scalars(
                    select(ModelCapability.capability_id).where(
                        ModelCapability.model_id == model_id
                    )
                )
            )
            for name in declared:
                capability_id = known.get(name)
                if capability_id is None:
                    capability_id = str(uuid4())
                    session.add(
                        Capability(
                            id=capability_id,
                            name=name,
                            description=f"Declared by the provider for its models ({name}).",
                        )
                    )
                    session.flush()
                    known[name] = capability_id
                if capability_id not in held:
                    session.add(
                        ModelCapability(
                            model_id=model_id,
                            capability_id=capability_id,
                            confidence="DECLARED_BY_PROVIDER",
                        )
                    )
                    held.add(capability_id)

        for info in discovered_models:
            m_name = info.model_name
            if m_name in existing_models:
                m_rec = existing_models[m_name]
                m_rec.is_available = info.is_available
                m_rec.last_verified = now_str
                # The provider has now actually named this model, so a row that was only
                # seeded from configuration stops being an unverified guess.
                m_rec.discovery_method = "DECLARED_BY_PROVIDER"
                if info.notes and info.notes not in m_rec.notes:
                    m_rec.notes = (m_rec.notes + " " + info.notes).strip()
                record_declared(m_rec.id, tuple(info.capabilities))
            else:
                m_id = str(uuid4())
                m_rec = ModelRecord(
                    id=m_id,
                    provider_id=provider_id,
                    model_name=m_name,
                    discovery_method="DECLARED_BY_PROVIDER",
                    context_length=info.context_length,
                    last_verified=now_str,
                    is_available=info.is_available,
                    notes=info.notes,
                )
                session.add(m_rec)
                session.flush()

                if text_cap:
                    mc = ModelCapability(
                        model_id=m_id,
                        capability_id=text_cap.id,
                        confidence="DECLARED_BY_PROVIDER",
                    )
                    session.add(mc)
                    session.flush()
                record_declared(m_id, tuple(info.capabilities))

                append_event(
                    session,
                    "provider.model_discovered",
                    "provider_model",
                    m_id,
                    1,
                    {
                        "provider_id": provider_id,
                        "model_name": m_name,
                        "is_cloud": getattr(info, "is_cloud", False),
                    },
                    str(uuid4()),
                )

        # Mark disappeared models as unavailable
        for m_name, m_rec in existing_models.items():
            if m_name not in discovered_names:
                m_rec.is_available = False
                m_rec.last_verified = now_str

        # Reaching this line means adapter.list_models() returned; the endpoint answered.
        # This is the only place allowed to record the provider as healthy.
        provider.status = "HEALTHY"
        provider.last_health_check = now_str
        session.flush()

    # The studio now knows which models exist, which is the first moment the starting
    # allocation can mean anything: before a sync every model is unavailable, and a slot
    # pointing at a model nobody has verified would be worse than an empty slot. Only
    # employees whose slots nobody has configured are touched — an Owner's own choice from
    # Settings is never overwritten by a file.
    from app.agents.ensemble import apply_llm_allocation  # noqa: PLC0415

    try:
        allocation = apply_llm_allocation(engine)
        if allocation["applied"] or allocation["skipped"]:
            logger.info(
                "llm_allocation_after_sync",
                extra={
                    "applied": len(allocation["applied"]),
                    "skipped": len(allocation["skipped"]),
                },
            )
    except (ValueError, RuntimeError) as exc:
        # A configuration file that cannot be applied is a thing to report, not a reason to
        # fail the model sync the Owner asked for.
        logger.warning("llm_allocation_failed", extra={"reason": str(exc)[:200]})

    # And then what a role *prefers*, which only a sync can satisfy: `record_declared` above
    # is the only place in the studio that ever writes `vision` on a model, so this call is
    # the first moment at which a seeing model exists as a row. After the allocation and not
    # before it: the allocation is the studio's baseline and skips only employees who already
    # carry `agent.model_assigned`, which a preferred move deliberately does not write — run
    # first, the preference would be undone by the file three lines later. Measured
    # 2026-09-18: without this call the only caller was `seed_initial_workforce`, i.e.
    # `scripts/bootstrap.py`, so a model the Owner admitted after his first start reached
    # nobody, `vision_agent` returned None at 05:00 and the picture gate stood down on every
    # film. Idempotent, and it never moves an employee he placed himself.
    try:
        preference = prefer_capable_models(engine)
        if preference["moved"] or preference["skipped"]:
            logger.info(
                "role_preference_after_sync",
                extra={
                    "moved": len(preference["moved"]),
                    "skipped": len(preference["skipped"]),
                },
            )
    except (ValueError, RuntimeError) as exc:
        # Same rule as the allocation above: a preference that cannot be applied is reported,
        # and the models the sync did record are kept.
        logger.warning("role_preference_failed", extra={"reason": str(exc)[:200]})

    return list_provider_models(engine, provider_id)


# ---------------------------------------------------------------------------
# Policy Kernel
# ---------------------------------------------------------------------------


class PolicyKernelError(Exception):
    """Raised when a policy gate blocks agent execution."""

    def __init__(self, block_reason: str, status: str) -> None:
        super().__init__(block_reason)
        self.block_reason = block_reason
        self.status = status


def _check_required_capabilities(
    session: Session, agent: Agent, model_id: str | None = None
) -> None:
    """Raise PolicyKernelError if the model lacks a capability the role requires.

    `model_id` names the model to check when it is not the agent's assigned one — a second or
    third model the Owner put in a slot. A role's requirements apply to whichever model is
    about to do the work, not only to the primary.

    Only REQUIRED is a gate, and that is deliberate: a role may also PREFER a capability
    (`ROLE_PREFERENCES`), which `prefer_capable_models` acts on when a model that has it is
    admitted and which must never stop an employee from working when none is.
    """
    required_caps = list(
        session.scalars(
            select(Capability.name)
            .join(RoleCapability, RoleCapability.capability_id == Capability.id)
            .where(
                RoleCapability.role_id == agent.role_id,
                RoleCapability.requirement_level == "REQUIRED",
            )
        ).all()
    )
    if not required_caps:
        return  # no requirements -> pass

    model_caps = set(
        session.scalars(
            select(Capability.name)
            .join(ModelCapability, ModelCapability.capability_id == Capability.id)
            .where(ModelCapability.model_id == (model_id or agent.model_id))
        ).all()
    )

    missing = [c for c in required_caps if c not in model_caps]
    if missing:
        raise PolicyKernelError(
            f"Model lacks required capabilities: {missing}",
            "BLOCKED_CAPABILITY",
        )


#: A run still marked RUNNING after this long is one the process never came back to.
RUN_STALE_AFTER_SECONDS = 45 * 60


def _has_live_run(session: Session, agent_id: str) -> bool:
    """Whether a run of this employee is genuinely in progress.

    A run is written when it starts, so "in progress" is a RUNNING row younger than the
    stale limit. Older RUNNING rows are closed as ABANDONED here, with the reason, so the
    record says what happened instead of pretending the model is still thinking.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    live = False
    limit = (datetime.now(UTC) - timedelta(seconds=RUN_STALE_AFTER_SECONDS)).isoformat()
    for run in session.scalars(
        select(AgentRun).where(AgentRun.agent_id == agent_id, AgentRun.status == "RUNNING")
    ):
        if run.started_at >= limit:
            live = True
            continue
        run.status = "ABANDONED"
        run.error_detail = "Rularea nu s-a mai încheiat: procesul s-a oprit în timpul apelului."
        run.finished_at = utc_now()
    return live


@lru_cache(maxsize=1)
def _studio_settings() -> Any:
    """The studio's settings when they can be built here, else None.

    `run_agent_task` is called from twenty places, none of which carry a settings object;
    the same shortcut `providers.retry` takes for the vendors' retry policy. A studio
    without a usable `.env` gets None, and every ceiling read through `getattr` falls back
    to the code's own default — which for the token ceiling is 0, no ceiling, as the studio
    has run until now. Cached, because a settings object read once per process is a
    configuration, not a measurement; a test overrides this function.
    """
    from app.config import Settings  # noqa: PLC0415

    try:
        return Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001
        return None


def _assert_policy_allows_run(
    session: Session, agent: Agent, registry: ProviderRegistry, model_id: str | None = None
) -> None:
    """Full policy kernel gate. Raises PolicyKernelError on any block.

    ``model_id`` is the model that will answer when it is not the agent's own (a slot, or the
    Director's probe of a replacement, 2026-10-11): its availability and its provider's health
    are what decide, not those of the model it stands in for. Before, a call on a working
    second model was refused because the first one had gone, which is when it was needed.
    """
    # 1. Autonomy stop
    policy = session.get(OwnerPolicy, 1)
    if policy and policy.autonomy_stopped:
        raise PolicyKernelError(AUTONOMY_STOPPED, "BLOCKED_POLICY")

    # 1b. Autonomy mode. A run is an employee thinking: a reversible internal write (T1,
    # 31's "create draft"), which every mode allows. Asking anyway is what makes the mode
    # real rather than a label, and it is what refuses the run should the Owner ever take
    # the studio below MANUAL's floor or should safe mode open under a run in flight. The
    # tier of what the agent's answer is then *used* for — a page fetched, a shot bought, a
    # film uploaded — is asked separately by the stage that does it (`STAGE_ACTIONS` in
    # app.runbook.stages), because the kernel cannot know from a prompt what will follow it.
    verdict = may_act(session, "agent.run", "T1", requester=agent.id)
    if not verdict["allowed"]:
        raise PolicyKernelError(verdict["reason"], verdict["status"])

    # 2. Lifecycle
    if agent.lifecycle != "ACTIVE":
        raise PolicyKernelError(
            f"Agent lifecycle is {agent.lifecycle!r}; only ACTIVE agents can run.",
            "BLOCKED_POLICY",
        )

    answering = model_id or agent.model_id
    model = session.get(ModelRecord, answering)
    if (
        model is None
        or not model.is_available
        or (answering == agent.model_id and model.provider_id != agent.provider_id)
    ):
        raise PolicyKernelError("Assigned model is unavailable or not verified", "BLOCKED_PROVIDER")
    # WORKING is production without a model (a voice being recorded) and has no AgentRun
    # behind it by nature, so it is not "stale" — a model task may run beside it.
    if agent.runtime_state not in ("IDLE", "BLOCKED", "ERROR", "WORKING"):
        if _has_live_run(session, agent.id):
            raise PolicyKernelError("Agent already has an active task", "BLOCKED_POLICY")
        # THINKING with no run in flight is a flag left behind — a restart mid-call, a
        # process killed between the two transactions. Dr. Aris sat like that for a whole
        # day and every stage that needed him was refused with "already has an active
        # task". A state nothing is backing is cleared, not obeyed.
        agent.runtime_state = "IDLE"
        agent.version += 1
        append_event_with_outbox(
            session,
            "agent.state_changed",
            "agent",
            agent.id,
            agent.version,
            {"runtime_state": "IDLE", "reason": "stale THINKING with no run in flight"},
            str(uuid4()),
        )

    # 3. Capabilities
    _check_required_capabilities(session, agent, model_id=answering)

    # 4. Provider health (in-process cache), of the provider that will answer
    provider_status = registry.cached_status(model.provider_id)
    if provider_status not in ("HEALTHY", "UNKNOWN"):
        raise PolicyKernelError(
            f"Provider status is {provider_status!r}; cannot run.",
            "BLOCKED_PROVIDER",
        )


# ---------------------------------------------------------------------------
# Run an agent task
# ---------------------------------------------------------------------------


#: What a provider's HTTP status tells the Owner to fix, in his words.
_HTTP_MEANING_RO: dict[int, str] = {
    401: "cheia conexiunii este respinsă (expirată, revocată sau greșită); reintrodu cheia",
    403: "cheia conexiunii nu are acces la acest model; verifică cheia și abonamentul",
    402: "abonamentul sau creditul furnizorului s-a terminat",
    404: "modelul nu mai există la furnizor; alege alt model pentru acest angajat",
    429: "limita de cereri a furnizorului a fost atinsă; se reîncearcă mai târziu",
}


def _failure_detail(exc: BaseException) -> str:
    """The error class, with the provider's HTTP status, its one-word code and its meaning
    when it has them.

    Never the exception's message: a vendor's text can carry a URL with a key in it. The
    code is the vendor's single word («unauthorized», «PERMISSION_DENIED»), which tells two
    refusals with the same status apart; the adapter keeps nothing longer. A refusal of a
    call that carried no key (``keyless``: the seeded local endpoint) is not a key to
    re-enter — there is none in Settings — but that service's own sign-in, or another model.
    """
    name = type(exc).__name__
    status = getattr(exc, "http_status", None)
    if not isinstance(status, int) or isinstance(status, bool):
        return name
    keyless_meaning = {
        401: "serviciul local nu este autentificat la contul furnizorului (nu are cheie în "
        "Setări); autentifică-l sau mută angajatul pe un model al unei conexiuni verificate",
        403: "contul serviciului local nu are acces la acest model; mută angajatul pe un "
        "model al unei conexiuni verificate",
    }
    meaning = (
        keyless_meaning.get(status) if getattr(exc, "keyless", False) is True else None
    ) or _HTTP_MEANING_RO.get(status)
    if meaning is None and 500 <= status < 600:
        meaning = "furnizorul are o problemă de partea lui; se reîncearcă mai târziu"
    word = getattr(exc, "word", None)
    one_word = (
        isinstance(word, str)
        and len(word) <= 60
        and word.isascii()
        and word.replace("_", "").replace("-", "").isalpha()
    )
    code = f" ({word})" if one_word else ""
    return f"{name}: HTTP {status}{code}" + (f" — {meaning}" if meaning else "")


def run_agent_task(
    engine: Engine,
    registry: ProviderRegistry,
    agent_id: str,
    task_type: str,
    objective: str,
    prompt_template_version: str,
    correlation_id: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    emit_message: bool = True,
    summary: str | None = None,
    extra: dict | None = None,
    model_id: str | None = None,
) -> dict:
    """Execute an agent LLM run through the policy kernel. Returns AgentRunView dict.

    Every run carries the agent's identity as the system prompt — name, role, mission,
    contract, persona and memory (`compose_identity`) — and records what it was given as the
    run's context manifest. The task text is the user prompt; it never has to repeat who the
    agent is.

    ``summary`` is that prompt in one sentence the Owner can read — "Verific afirmația «…»"
    rather than nine hundred words of instructions with the claim buried in the middle. The
    history shows it in place of the prompt; the prompt itself stays one click away.

    ``model_id`` runs this call on a model other than the agent's assigned one — the second or
    third slot the Owner configured. The agent, its identity, its policy and its record are
    the same; only which model answers changes, and the run records the model that actually
    answered, so changing a slot tomorrow cannot rewrite what yesterday was answered by.
    """
    run_id = str(uuid4())
    started_at = utc_now()
    system_prompt: str | None = None
    context: dict = {}
    effective_max_tokens = max_tokens

    # The day's token ceiling, before the run's write transaction opens: the Accountant's
    # letter to the Owner writes in a transaction of its own, and two writers on one SQLite
    # connection are a lock, not a policy. Measured on a copy of the live database:
    # 391 runs on Ollama Cloud, the Director's loop and the mail rounds among them, ran
    # under no ceiling at all. The verdict is carried into the kernel below and refused
    # there, so a blocked run is recorded exactly like every other BLOCKED_* — a row with
    # the reason, not an exception the twenty callers would each have to learn.
    # An exceeded USD budget refuses the run as well (MONEY-10); the Accountant's own close,
    # which reports it, is the one run it does not stop (`BUDGET_EXEMPT_TASKS`).
    gate: dict[str, Any] = {"correlation_id": correlation_id, "task_type": task_type}
    settings = _studio_settings()
    budget_verdict = may_run_agent(engine, settings, **gate)

    with Session(engine) as session, session.begin():
        # This transaction reads the agent and its identity and then writes the run: it is
        # a writer from the start, so it says so before it reads anything.
        lock_for_write(session)
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        identity = compose_identity(session, agent, task_type=task_type)
        system_prompt, context = identity.system, identity.context
        role = session.get(Role, agent.role_id)
        multiplier = (
            getattr(settings, "director_token_multiplier", DEFAULT_DIRECTOR_TOKEN_MULTIPLIER)
            if role is not None and role.name == "Director"
            else 1
        )
        effective_max_tokens = max_tokens * multiplier if max_tokens is not None else None
        context = {
            **context,
            "generation_limits": {
                "requested_max_tokens": max_tokens,
                "token_multiplier": multiplier,
                "effective_max_tokens": effective_max_tokens,
            },
        }
        if summary:
            context = {**context, "task_summary": " ".join(str(summary).split())[:300]}

        # Which model answers this call: the agent's own, or the slot the caller named.
        # A named model must exist, be available, and satisfy what the role requires — a
        # fallback onto a model that cannot do the job is not a fallback.
        model_rec = session.get(ModelRecord, model_id or agent.model_id)
        if model_rec is None:
            raise ValueError("Agent model record missing")
        provider_rec = session.get(ProviderRecord, model_rec.provider_id)
        if provider_rec is None:
            raise ValueError("Agent provider record missing")
        if model_id and model_id != agent.model_id:
            if not model_rec.is_available:
                raise PolicyKernelError(
                    "Modelul din slotul cerut nu este disponibil", "BLOCKED_PROVIDER"
                )
            _check_required_capabilities(session, agent, model_id=model_id)
            context = {**context, "model_slot": "secondary_or_tertiary"}

        # --- Policy kernel ---
        try:
            if not budget_verdict["allowed"]:
                raise PolicyKernelError(budget_verdict["reason"], budget_verdict["status"])
            _assert_policy_allows_run(session, agent, registry, model_id=model_rec.id)
        except PolicyKernelError as exc:
            run = AgentRun(
                id=run_id,
                agent_id=agent_id,
                task_type=task_type,
                objective=objective,
                prompt_template_version=prompt_template_version,
                model_name=model_rec.model_name,
                provider_name=provider_rec.name,
                status=exc.status,
                output=None,
                output_text=None,
                error_detail=exc.block_reason,
                cost_vr=None,
                prompt_tokens=None,
                completion_tokens=None,
                correlation_id=correlation_id,
                started_at=started_at,
                finished_at=utc_now(),
                event_id=None,
                context_json=context,
            )
            session.add(run)
            session.flush()
            return AgentRunView.model_validate(run).model_dump()

        # --- Check adapter present ---
        adapter = registry.get(model_rec.provider_id)
        if adapter is None:
            run = AgentRun(
                id=run_id,
                agent_id=agent_id,
                task_type=task_type,
                objective=objective,
                prompt_template_version=prompt_template_version,
                model_name=model_rec.model_name,
                provider_name=provider_rec.name,
                status="BLOCKED_PROVIDER",
                output=None,
                output_text=None,
                error_detail="No adapter registered for provider",
                cost_vr=None,
                prompt_tokens=None,
                completion_tokens=None,
                correlation_id=correlation_id,
                started_at=started_at,
                finished_at=utc_now(),
                event_id=None,
            )
            session.add(run)
            session.flush()
            return AgentRunView.model_validate(run).model_dump()

        model_name = model_rec.model_name
        provider_name = provider_rec.name
        provider_id = provider_rec.id
        agent.runtime_state = "THINKING"
        agent.version += 1
        append_event_with_outbox(
            session,
            "agent.state_changed",
            "agent",
            agent_id,
            agent.version,
            {"runtime_state": "THINKING", "task_type": task_type, "run_id": run_id},
            correlation_id,
        )
        # The run exists from the moment the model is called. What the employee is doing
        # right now is then a fact in the record, and a process that dies mid-call leaves a
        # RUNNING row to be closed as ABANDONED, not a THINKING flag nothing can explain.
        session.add(
            AgentRun(
                id=run_id,
                agent_id=agent_id,
                task_type=task_type,
                objective=objective,
                prompt_template_version=prompt_template_version,
                model_name=model_name,
                provider_name=provider_name,
                status="RUNNING",
                output=None,
                output_text=None,
                error_detail=None,
                cost_vr=None,
                prompt_tokens=None,
                completion_tokens=None,
                correlation_id=correlation_id,
                started_at=started_at,
                finished_at=None,
                event_id=None,
                context_json=context,
            )
        )

    # Execute outside the DB transaction to avoid holding locks during LLM call
    try:
        gen_result = asyncio.run(
            adapter.generate(
                model_name,
                objective,
                system=system_prompt,
                max_tokens=effective_max_tokens,
                temperature=temperature,
                extra=extra,
            )
        )
        output_text = gen_result.text
        # A call that returned no text is not a run that succeeded. It costs tokens, it takes
        # a minute of the day, and every caller that needs an answer then fails on its own
        # with "no usable answer" — while the history showed the Owner a green SUCCEEDED with
        # nothing under it. The usual cause is a model that reasoned until the token budget
        # was gone; `raw_response` says so when the provider reports it.
        raw = gen_result.raw_response if isinstance(gen_result.raw_response, dict) else {}
        http_status: int | None = None
        if (output_text or "").strip():
            status = "SUCCEEDED"
            error_detail = None
        else:
            status = "EMPTY_OUTPUT"
            error_detail = (
                "Modelul a atins limita de tokeni înainte să răspundă: a folosit bugetul pe "
                "raționament intern. Niciun răspuns de folosit."
                if raw.get("done_reason") == "length"
                else "Modelul a răspuns fără niciun text. Niciun răspuns de folosit."
            )
        cost_vr = gen_result.cost_vr
        prompt_tokens = gen_result.prompt_tokens
        completion_tokens = gen_result.completion_tokens
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "agent_run_failed",
            extra={"agent_id": agent_id, "error": type(exc).__name__},
            exc_info=exc,
        )
        status = "FAILED"
        output_text = None
        # Never echo full message (may contain URLs/secrets); the provider's HTTP status is a
        # number and says what to fix.
        error_detail = _failure_detail(exc)
        code = getattr(exc, "http_status", None)
        http_status = code if isinstance(code, int) and not isinstance(code, bool) else None
        cost_vr = None
        prompt_tokens = None
        completion_tokens = None

    finished_at = utc_now()

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        agent = session.get(Agent, agent_id)
        if agent:
            agent.runtime_state = "IDLE"
            agent.version += 1
            append_event_with_outbox(
                session,
                "agent.state_changed",
                "agent",
                agent_id,
                agent.version,
                {"runtime_state": "IDLE", "task_type": task_type},
                correlation_id,
            )

        event = append_event(
            session,
            "agent.run_completed",
            "agent_run",
            run_id,
            1,
            {
                "agent_id": agent_id,
                "status": status,
                "task_type": task_type,
                "model_name": model_name,
            },
            correlation_id,
        )
        stored = session.get(AgentRun, run_id)
        if stored is None:  # pragma: no cover - the row was written when the call started
            raise RuntimeError(f"Run {run_id} vanished while the model was answering")
        stored.status = status
        stored.output_text = output_text
        stored.error_detail = error_detail
        stored.cost_vr = cost_vr
        stored.prompt_tokens = prompt_tokens
        stored.completion_tokens = completion_tokens
        stored.finished_at = finished_at
        stored.event_id = event.event_id
        session.flush()
        run = stored
        # A connection its provider refused for a reason only the Owner fixes (401/402/403) is
        # a card in his window of decisions; the next run that succeeds on it withdraws it
        # (DECISION_SOURCES). Proposed in a savepoint: a card never fails the run's record.
        from app.decisions.sources import model_run_finished  # noqa: PLC0415

        model_run_finished(session, provider_id, status, http_status, error_detail)

        # The model's real output is the agent's operational message. Emitting it as
        # agent.message_sent (through the outbox, so it reaches the live office) is what the
        # speech-bubble projection consumes — only real messages may become live bubbles
        # (../architecture/06_BACKEND_EVENT_MODEL.md §7). Reasoning models can succeed with
        # no visible text; then there is nothing real to say and no event is emitted.
        # The bubble pages through the text at reading speed and the chat shows all of it;
        # the payload is capped only so an event stays an event, not a document.
        message_text = " ".join((output_text or "").split())[:1200]
        if emit_message and status == "SUCCEEDED" and message_text:
            append_event_with_outbox(
                session,
                "agent.message_sent",
                "agent",
                agent_id,
                agent.version if agent else 1,
                {"text": message_text, "run_id": run_id, "task_type": task_type},
                correlation_id,
            )
        return AgentRunView.model_validate(run).model_dump()


#: The provider's own word for "this model can look at a picture" — the same string
#: `app.agents.editorial.VISION` holds. It is not imported from there: that module reaches
#: into the film code, and the workforce seed must not depend on it to hire anybody.
VISION = "vision"

#: The two levels a role's capability row can carry. REQUIRED is a gate: `run_agent_task`
#: refuses a run whose model lacks it. PREFERRED is not a gate and never becomes one — it
#: only decides, where the studio has a choice, which model an employee is hired or kept on.
REQUIRED = "REQUIRED"
PREFERRED = "PREFERRED"

#: What a role would rather its employee's model could do. The Video Editor's department
#: owns the pictures and is the first department `picture_qc` asks to look at them, so she is
#: the one the studio would rather put on a model that sees. Measured 2026-09-18: the seed
#: gave her glm-5.3, which declares completion, thinking and tools and no vision, so
#: `vision_agent` found nobody and the picture and character checks reported NOT_APPLICABLE
#: on every film a live studio has ever made. Preferred, never required: a studio whose Owner
#: has admitted no seeing model must keep cutting film.
ROLE_PREFERENCES: dict[str, tuple[str, ...]] = {"VideoEditor": (VISION,)}

#: What a seeded model is recorded as being able to do. Vision is deliberately absent:
#: nothing in the seed contacts a provider, and a seeded guess that a model can see would
#: hand the picture check a look nobody took. `sync_provider_models` attaches vision when the
#: vendor itself declares it.
SEEDED_MODEL_CAPABILITIES = (
    "text_generation",
    "structured_output",
    "fact_checking",
    "creative_writing",
)


_ROLE_DEFINITIONS = [
    (
        "Director",
        "Grow the studio's audience: raising views and retention is her primary charge. She "
        "directs every department in writing, steers channels and topics from measured "
        "analytics, and documents every decision",
        "plan,review,direct,decide,editorial_judgement",
        "self_escalate,bypass_policy",
    ),
    (
        "LeadResearcher",
        "Discover and analyze viral, factual, high-retention topics and source evidence",
        "research,ingest_source,extract_claims",
        "unverified_speculation",
    ),
    (
        "FactChecker",
        "Verify atomic claims against authoritative sources and enforce factual gate",
        "verify_claim,gate_check",
        "bypass_unverified_claims",
    ),
    (
        "ScriptWriter",
        "Draft narrative scripts, scene breakdowns, and voiceover pacing",
        "draft_script,write_scenes",
        "fabricate_facts",
    ),
    (
        "VoiceArtist",
        "Synthesize speech, narration timing, and vocal emotional inflection",
        # sound_design (2026-10-11): the sound department plans the music under the words
        # (`app.media.sound_design`); `seed_role_task_types` gives it to a studio hired before.
        "synthesize_voice,audio_align,sound_design",
        "unauthorized_cloning",
    ),
    (
        "VideoEditor",
        "Compose video assets, timeline pacing, transitions, and visual rendering",
        "render_video,edit_scenes,qc_video",
        "corrupt_timeline",
    ),
    (
        "Publisher",
        "Oversee final QC, metadata optimization, packaging, and distribution schedule",
        "prepare_release,schedule_publish",
        "bypass_owner_policy",
    ),
    (
        "Accountant",
        "Keep the books of what the studio spends, hold it to its budget, and close "
        "every day with figures the Owner can read",
        "reconcile_costs,report_budget,record_costs",
        "post_without_reference,pay_anyone,change_budget",
    ),
]


#: A seed role's task types reached a studio that already had the role (`seed_role_task_types`).
ROLE_TASK_TYPES_EXTENDED_EVENT = "role.task_types_extended"


def seed_role_task_types(engine: Engine) -> dict[str, list[str]]:
    """Give every seeded role the task types its seed definition names and it lacks.

    A role is created once, with the seed's list of that day; a task type added to the seed
    later (sound_design for the Voice Artist, 2026-10-11) never reached a studio that already
    existed, and her identity kept saying she may not do it. Runs on every start
    (`seed_initial_workforce`, as the contracts and preferences do): what a role has is kept,
    what the seed added is appended, each extension an event. Returns {role: added}.
    """
    added: dict[str, list[str]] = {}
    with Session(engine) as session, session.begin():
        roles = {role.name: role for role in session.scalars(select(Role))}
        correlation_id = str(uuid4())
        for name, _mission, allowed, _prohibited in _ROLE_DEFINITIONS:
            role = roles.get(name)
            if role is None:
                continue
            have = [item.strip() for item in (role.allowed_task_types or "").split(",")]
            have = [item for item in have if item]
            missing = [item for item in allowed.split(",") if item and item not in have]
            if not missing:
                continue
            role.allowed_task_types = ",".join([*have, *missing])
            append_event(
                session,
                ROLE_TASK_TYPES_EXTENDED_EVENT,
                "role",
                role.id,
                1,
                {"name": name, "added": missing, "allowed_task_types": role.allowed_task_types},
                correlation_id,
            )
            added[name] = missing
    return added


def seed_missing_workforce(engine: Engine) -> list[str]:
    """Hire the seed employees a studio does not have yet. Returns the display names hired.

    `seed_initial_workforce` stops at the first hire, by design: it never overwrites a studio
    the Owner has shaped. But a role added to the seed later (the Accountant) has to reach a
    studio that already exists. This creates the missing role from the seed's own definition
    and hires its employee on the seed's model if that model exists, otherwise on the model
    the Director already runs, so the new hire can work today. Every hire is an event.
    """
    from app.agents.seed_config import load_seed_config

    seed_config = load_seed_config()
    hired: list[str] = []
    with Session(engine) as session, session.begin():
        existing_roles = {r.name: r for r in session.scalars(select(Role))}
        agents = list(session.scalars(select(Agent).where(Agent.lifecycle == "ACTIVE")))
        if not agents:
            return hired
        held = {
            role.name
            for role in existing_roles.values()
            if any(a.role_id == role.id for a in agents)
        }
        correlation_id = str(uuid4())
        models = {m.model_name: m for m in session.scalars(select(ModelRecord))}
        director = next(
            (
                a
                for a in agents
                if existing_roles.get("Director") and a.role_id == existing_roles["Director"].id
            ),
            agents[0],
        )
        role_specs = {
            name: (mission, allowed, prohibited)
            for name, mission, allowed, prohibited in _ROLE_DEFINITIONS
        }
        for display_name, role_name, model_name in seed_config["agents_def"]:
            if role_name in held:
                continue
            role = existing_roles.get(role_name)
            if role is None:
                spec = role_specs.get(role_name)
                if spec is None:
                    continue
                event = append_event(
                    session,
                    "role.created",
                    "role",
                    str(uuid4()),
                    1,
                    {"name": role_name, "mission": spec[0]},
                    correlation_id,
                )
                role = Role(
                    id=event.aggregate_id,
                    name=role_name,
                    mission=spec[0],
                    allowed_task_types=spec[1],
                    prohibited_actions=spec[2],
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
                session.add(role)
                session.flush()
                existing_roles[role_name] = role
            # The seed's model only if the provider has confirmed it; otherwise the model the
            # Director already runs on, so the new hire can work today rather than wait for a
            # verification nobody asked for.
            model = models.get(model_name)
            usable = model is not None and model.is_available
            provider_id = model.provider_id if usable and model else director.provider_id
            model_id = model.id if usable and model else director.model_id
            event = append_event(
                session,
                "agent.hired",
                "agent",
                str(uuid4()),
                1,
                {"display_name": display_name, "role": role_name, "model": model_name},
                correlation_id,
            )
            session.add(
                Agent(
                    id=event.aggregate_id,
                    display_name=display_name,
                    role_id=role.id,
                    provider_id=provider_id,
                    model_id=model_id,
                    lifecycle="ACTIVE",
                    runtime_state="IDLE",
                    cost_limit_per_task=None,
                    max_concurrent_tasks=1,
                    version=1,
                    hired_at=utc_now(),
                    terminated_at=None,
                    event_id=event.event_id,
                )
            )
            held.add(role_name)
            hired.append(display_name)
    return hired


def seed_role_preferences(engine: Engine) -> list[str]:
    """Record what a role would rather its employee's model could do. Returns the roles written.

    `ROLE_PREFERENCES` is the studio's own judgement about a job, so it belongs beside the
    role and not beside a model name: the Video Editor answers for the pictures, therefore her
    role prefers a model that can see. The row is written at PREFERRED, which no gate reads —
    `_check_required_capabilities` enforces REQUIRED alone — so a studio whose Owner has
    admitted no seeing model hires exactly as it did and keeps cutting film.

    Idempotent, and written on every seed: a studio whose roles were created before this
    preference existed gets it on its next start, like the role contracts below.
    """
    written: list[str] = []
    with Session(engine) as session, session.begin():
        for role_name, capabilities in ROLE_PREFERENCES.items():
            role = session.scalars(select(Role).where(Role.name == role_name)).first()
            if role is None:
                continue
            for cap_name in capabilities:
                capability = session.scalars(
                    select(Capability).where(Capability.name == cap_name)
                ).first()
                if capability is None:
                    capability = Capability(
                        id=str(uuid4()),
                        name=cap_name,
                        description=f"Preferred by a role; declared per model ({cap_name}).",
                    )
                    session.add(capability)
                    session.flush()
                held = session.scalars(
                    select(RoleCapability).where(
                        RoleCapability.role_id == role.id,
                        RoleCapability.capability_id == capability.id,
                    )
                ).first()
                if held is None:
                    session.add(
                        RoleCapability(
                            role_id=role.id,
                            capability_id=capability.id,
                            requirement_level=PREFERRED,
                        )
                    )
                    written.append(f"{role_name}:{cap_name}")
    return written


def prefer_capable_models(engine: Engine) -> dict[str, list[dict[str, str]]]:
    """Put an employee on a model that has what her role prefers, when one is admitted.

    Measured 2026-09-18: PREFERRED was a word no code anywhere read — assignment checked
    REQUIRED and nothing else — so the studio's preference for a seeing Video Editor would
    have changed nothing. This is where it means something.

    Three rules keep it from being an assignment nobody asked for:

    - **The Owner's own choice stands.** An employee he put on a model by hand is left alone
      (`_owner_chose_models`), or the next start would quietly undo what he chose. The
      studio's own starting allocation is not his hand, and is refined.
    - **A candidate must do the whole job.** It must be available, declare every capability
      the role *requires*, and declare what the role prefers; otherwise the move would trade
      a working employee for a blocked one.
    - **No model, no move.** A studio with nothing that sees keeps the employee it has. This
      function never blocks, never hires and never terminates.

    Returns what moved and what did not, with the reason, for the caller's log.
    """
    moved: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    with Session(engine) as session, session.begin():
        for role_name, capabilities in ROLE_PREFERENCES.items():
            role = session.scalars(select(Role).where(Role.name == role_name)).first()
            if role is None:
                continue
            agent = session.scalars(
                select(Agent).where(Agent.role_id == role.id, Agent.lifecycle == "ACTIVE")
            ).first()
            if agent is None:
                skipped.append({"role": role_name, "why": "niciun angajat activ pe rol"})
                continue
            preferred = set(
                session.scalars(
                    select(Capability.name)
                    .join(RoleCapability, RoleCapability.capability_id == Capability.id)
                    .where(
                        RoleCapability.role_id == role.id,
                        RoleCapability.requirement_level == PREFERRED,
                    )
                ).all()
            ) & set(capabilities)
            if not preferred:
                continue
            required = set(
                session.scalars(
                    select(Capability.name)
                    .join(RoleCapability, RoleCapability.capability_id == Capability.id)
                    .where(
                        RoleCapability.role_id == role.id,
                        RoleCapability.requirement_level == REQUIRED,
                    )
                ).all()
            )
            if preferred <= _model_capabilities(session, agent.model_id):
                continue  # her model already has it; nothing to prefer
            if _owner_chose_models(session, agent, role_name):
                skipped.append({"role": role_name, "why": "modelele au fost alese de Owner"})
                continue
            if agent.runtime_state not in ("IDLE", "BLOCKED", "ERROR"):
                skipped.append({"role": role_name, "why": "angajatul lucrează acum"})
                continue
            candidate = next(
                (
                    model
                    for model in session.scalars(
                        select(ModelRecord)
                        .where(ModelRecord.is_available.is_(True))
                        .order_by(ModelRecord.model_name)
                    )
                    if (preferred | required) <= _model_capabilities(session, model.id)
                ),
                None,
            )
            if candidate is None:
                skipped.append(
                    {
                        "role": role_name,
                        "why": "niciun model admis nu declară " + ", ".join(sorted(preferred)),
                    }
                )
                continue
            agent.provider_id, agent.model_id = candidate.provider_id, candidate.id
            agent.version += 1
            # Not `agent.model_assigned`: that event is the record of the Owner's own choice,
            # and writing it here would make the next start read this move as his and stop
            # applying his allocation file.
            event = append_event(
                session,
                "agent.model_preferred",
                "agent",
                agent.id,
                agent.version,
                {
                    "role": role_name,
                    "model_name": candidate.model_name,
                    "capabilities": sorted(preferred),
                },
                str(uuid4()),
            )
            agent.event_id = event.event_id
            session.flush()
            moved.append({"role": role_name, "model": candidate.model_name})
    if moved or skipped:
        logger.info(
            "role_capability_preference", extra={"moved": len(moved), "skipped": len(skipped)}
        )
    return {"moved": moved, "skipped": skipped}


#: The origin of a model the Director put an employee on because hers had stopped working
#: (`app.agents.repairs.agent_health`, 2026-10-11). Not the Owner's choice, and never read as it.
DIRECTOR_REPAIR_ORIGIN = "DIRECTOR_REPAIR"


def _assignments(session: Session, agent_id: str) -> list[DomainEvent]:
    """The employee's model assignments and preferred moves, newest first, without the
    Director's repairs: a detour while a model is down is not anyone's choice of model."""
    rows = session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.aggregate_id == agent_id,
            DomainEvent.event_type.in_(("agent.model_assigned", "agent.model_preferred")),
        )
        .order_by(DomainEvent.sequence.desc())
    )
    return [
        row
        for row in rows
        if (row.payload or {}).get("assignment_origin") != DIRECTOR_REPAIR_ORIGIN
    ]


def owner_home_model(session: Session, agent_id: str) -> str | None:
    """The model the Owner last put this employee on himself, or None.

    Where she goes back to once that model works again: the Director's repair moves her off
    it while it fails and keeps it as her home, and the preference mover leaves her alone
    (`_owner_chose_models`), because his choice still stands behind the detour.
    """
    for row in _assignments(session, agent_id):
        if row.event_type != "agent.model_assigned":
            continue
        origin = (row.payload or {}).get("assignment_origin")
        if origin in (None, "OWNER"):
            model_id = (row.payload or {}).get("model_id")
            return str(model_id) if model_id else None
    return None


def _owner_chose_models(session: Session, agent: Agent, role_name: str) -> bool:
    """Protect explicit assignments even when they match the current seed configuration.

    New assignment events record their origin. Minimal legacy events came from the Owner's
    command and stay protected. Older ensemble events have no origin; retain their slot
    comparison for compatibility, protecting them when the seed cannot be read. The
    Director's repairs (``DIRECTOR_REPAIR``) are skipped: what decides is the choice behind
    them, so an employee he placed stays his while she stands in on another model.
    """
    from app.agents.ensemble import resolve_model  # noqa: PLC0415

    found = _assignments(session, agent.id)
    last = found[0] if found else None
    if last is None or last.event_type == "agent.model_preferred":
        return False
    origin = last.payload.get("assignment_origin")
    if origin is not None:
        return origin != "SEED_ALLOCATION"
    ensemble_fields = {"secondary_model_id", "tertiary_model_id", "multi_llm_strategy"}
    if not ensemble_fields.issubset(last.payload):
        return True
    entry = _allocation_entry(role_name)
    if entry is None:
        return True
    held = {
        "primary": agent.model_id,
        "secondary": agent.secondary_model_id,
        "tertiary": agent.tertiary_model_id,
    }
    for slot, model_id in held.items():
        wanted = entry.get(slot)
        # `resolve_model`, not the name, because the file may spell a model the way the Owner
        # types it and the registry the way the vendor returns it (":cloud", "-cloud").
        row = resolve_model(session, wanted) if wanted else None
        if (row.id if row is not None else None) != (model_id or None):
            return True
    return False


def _allocation_entry(role_name: str) -> dict[str, Any] | None:
    """What the studio's own starting allocation says about this role, or None.

    None also when the file cannot be read: the caller reads that as the Owner's own choice,
    which leaves the employee exactly where she is.
    """
    from app.agents.seed_config import load_seed_config  # noqa: PLC0415

    try:
        allocation = load_seed_config().get("llm_allocation") or []
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("llm_allocation_unreadable", extra={"reason": str(exc)[:200]})
        return None
    for entry in allocation:
        if isinstance(entry, dict) and entry.get("role") == role_name:
            return dict(entry)
    return None


def _model_capabilities(session: Session, model_id: str | None) -> set[str]:
    """What the studio has recorded that this model can do, by name."""
    if not model_id:
        return set()
    return set(
        session.scalars(
            select(Capability.name)
            .join(ModelCapability, ModelCapability.capability_id == Capability.id)
            .where(ModelCapability.model_id == model_id)
        ).all()
    )


def seed_initial_workforce(engine: Engine) -> None:
    """Seed baseline roles, the Ollama endpoint, its expected models, and the agents.

    Role work contracts (config/role_contracts.json) are seeded afterwards, on every call,
    because they also have to reach a studio whose roles were created before contracts
    existed; that seed fills only what the Owner has not written. The same is true of what a
    role prefers of a model, and of acting on that preference: both run on every call, so a
    studio that existed before either gets them on its next start.

    Seeding writes intent, never observation. The provider is recorded NOT_CONFIGURED with no
    health-check timestamp and its models unavailable with no verification timestamp, because
    nothing in this function contacts Ollama. Only ``sync_provider_models`` — which does make
    the call — may mark a model available or stamp ``last_verified``.
    """
    _seed_initial_workforce(engine)
    seed_missing_workforce(engine)
    seed_role_task_types(engine)
    seed_role_contracts(engine)
    seed_role_preferences(engine)
    prefer_capable_models(engine)


def _seed_initial_workforce(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        existing_agents = session.scalar(select(func.count()).select_from(Agent))
        if existing_agents and existing_agents > 0:
            return

        correlation_id = str(uuid4())

        # 1. Capabilities
        cap_map: dict[str, str] = {}
        caps_data = [
            ("text_generation", "Basic and advanced LLM text generation"),
            ("structured_output", "Strict JSON schema parsing and generation"),
            ("fact_checking", "Claim verification and source analysis"),
            ("creative_writing", "Scripts, storyboards, and hooks"),
            # A row, not a claim about any model: a role can only prefer a capability the
            # studio has a name for, and nothing below attaches this one to a seeded model.
            (VISION, "Looking at a picture and saying what is in it"),
        ]
        for name, desc in caps_data:
            existing_cap = session.scalars(
                select(Capability).where(Capability.name == name)
            ).first()
            if not existing_cap:
                cap = Capability(id=str(uuid4()), name=name, description=desc)
                session.add(cap)
                session.flush()
                cap_map[name] = cap.id
            else:
                cap_map[name] = existing_cap.id

        # 2. Ollama Provider
        provider = session.scalars(
            select(ProviderRecord).where(ProviderRecord.name == "local-ollama")
        ).first()
        if not provider:
            event = append_event(
                session,
                "provider.registered",
                "provider_record",
                str(uuid4()),
                1,
                {"name": "local-ollama", "provider_type": "OLLAMA"},
                correlation_id,
            )
            provider = ProviderRecord(
                id=event.aggregate_id,
                name="local-ollama",
                provider_type="OLLAMA",
                base_url="http://127.0.0.1:11434",
                # Seeding registers an endpoint; it does not contact it. Nothing here may
                # claim the provider answered — the owner runs the health check.
                status="NOT_CONFIGURED",
                last_health_check=None,
                adapter_version="1.0.0",
                notes=(
                    "Ollama local & cloud models adapter. Endpoint declared at seed time and "
                    "never contacted; run the provider check to establish whether it answers."
                ),
                created_at=utc_now(),
                event_id=event.event_id,
            )
            session.add(provider)
            session.flush()

        # Initial model proposals come from editable seed configuration, never discovery.
        from app.agents.seed_config import load_seed_config

        seed_config = load_seed_config()
        models_data = seed_config["models_data"]
        model_map: dict[str, str] = {}
        for m_name, ctx_len, notes in models_data:
            existing_model = session.scalars(
                select(ModelRecord).where(
                    ModelRecord.provider_id == provider.id, ModelRecord.model_name == m_name
                )
            ).first()
            if not existing_model:
                model = ModelRecord(
                    id=str(uuid4()),
                    provider_id=provider.id,
                    model_name=m_name,
                    # SEEDED_UNVERIFIED, not DECLARED_BY_PROVIDER: the provider never
                    # declared anything here, this list is written from configuration.
                    discovery_method="SEEDED_UNVERIFIED",
                    context_length=ctx_len,
                    last_verified=None,
                    is_available=False,
                    notes=f"{notes}; cloud_model=true; not verified against the provider",
                )
                session.add(model)
                session.flush()
                # Only what a text model is proposed for. Vision is left out on purpose: see
                # SEEDED_MODEL_CAPABILITIES — a seeded guess that a model can see would make
                # the picture check certify a look nobody took.
                for cap_name in SEEDED_MODEL_CAPABILITIES:
                    session.add(
                        ModelCapability(
                            model_id=model.id,
                            capability_id=cap_map[cap_name],
                            confidence="SEEDED_UNVERIFIED",
                        )
                    )
                model_map[m_name] = model.id
            else:
                model_map[m_name] = existing_model.id

        # 4. Roles matching office workstations
        roles_def = _ROLE_DEFINITIONS
        role_map: dict[str, str] = {}
        for r_name, mission, allowed, prohibited in roles_def:
            existing_role = session.scalars(select(Role).where(Role.name == r_name)).first()
            if not existing_role:
                r_id = str(uuid4())
                event = append_event(
                    session,
                    "role.created",
                    "role",
                    r_id,
                    1,
                    {"name": r_name, "mission": mission},
                    correlation_id,
                )
                role = Role(
                    id=r_id,
                    name=r_name,
                    mission=mission,
                    allowed_task_types=allowed,
                    prohibited_actions=prohibited,
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
                session.add(role)
                session.flush()
                if "text_generation" in cap_map:
                    session.add(
                        RoleCapability(
                            role_id=role.id,
                            capability_id=cap_map["text_generation"],
                            requirement_level="REQUIRED",
                        )
                    )
                role_map[r_name] = role.id
            else:
                role_map[r_name] = existing_role.id

        # 5. Hired Agents placed at their desks
        agents_def = seed_config["agents_def"]
        for display_name, r_name, m_name in agents_def:
            a_id = str(uuid4())
            event = append_event(
                session,
                "agent.hired",
                "agent",
                a_id,
                1,
                {"display_name": display_name, "role": r_name, "model": m_name},
                correlation_id,
            )
            agent = Agent(
                id=a_id,
                display_name=display_name,
                role_id=role_map[r_name],
                provider_id=provider.id,
                model_id=model_map[m_name],
                lifecycle="ACTIVE",
                runtime_state="IDLE",
                cost_limit_per_task=None,
                max_concurrent_tasks=1,
                version=1,
                hired_at=utc_now(),
                terminated_at=None,
                event_id=event.event_id,
            )
            session.add(agent)
