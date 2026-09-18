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
from app.db import lock_for_write
from app.economy.accountant import may_run_agent
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
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
            caps = session.scalars(
                select(Capability.name)
                .join(RoleCapability, RoleCapability.capability_id == Capability.id)
                .where(RoleCapability.role_id == role.id)
            ).all()
            view = RoleView.model_validate(role)
            view.required_capabilities = list(caps)
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


def pause_agent(engine: Engine, agent_id: str) -> dict:
    """Pause an active agent, preventing autonomous tasks."""
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        if agent.lifecycle == "TERMINATED":
            raise ValueError("Cannot pause a TERMINATED agent")

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
    """Resume a paused agent to ACTIVE lifecycle."""
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        if agent.lifecycle == "TERMINATED":
            raise ValueError("Cannot resume a TERMINATED agent")

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


def _assert_policy_allows_run(session: Session, agent: Agent, registry: ProviderRegistry) -> None:
    """Full policy kernel gate. Raises PolicyKernelError on any block."""
    # 1. Autonomy stop
    policy = session.get(OwnerPolicy, 1)
    if policy and policy.autonomy_stopped:
        raise PolicyKernelError(
            "Global autonomy stop is active; Owner must clear it first.",
            "BLOCKED_POLICY",
        )

    # 2. Lifecycle
    if agent.lifecycle != "ACTIVE":
        raise PolicyKernelError(
            f"Agent lifecycle is {agent.lifecycle!r}; only ACTIVE agents can run.",
            "BLOCKED_POLICY",
        )

    model = session.get(ModelRecord, agent.model_id)
    if model is None or model.provider_id != agent.provider_id or not model.is_available:
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
    _check_required_capabilities(session, agent)

    # 4. Provider health (in-process cache)
    provider_status = registry.cached_status(agent.provider_id)
    if provider_status not in ("HEALTHY", "UNKNOWN"):
        raise PolicyKernelError(
            f"Provider status is {provider_status!r}; cannot run.",
            "BLOCKED_PROVIDER",
        )


# ---------------------------------------------------------------------------
# Run an agent task
# ---------------------------------------------------------------------------


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

    # The day's token ceiling, before the run's write transaction opens: the Accountant's
    # letter to the Owner writes in a transaction of its own, and two writers on one SQLite
    # connection are a lock, not a policy. Measured on a copy of the live database:
    # 391 runs on Ollama Cloud, the Director's loop and the mail rounds among them, ran
    # under no ceiling at all. The verdict is carried into the kernel below and refused
    # there, so a blocked run is recorded exactly like every other BLOCKED_* — a row with
    # the reason, not an exception the twenty callers would each have to learn.
    budget_verdict = may_run_agent(engine, _studio_settings(), correlation_id=correlation_id)

    with Session(engine) as session, session.begin():
        # This transaction reads the agent and its identity and then writes the run: it is
        # a writer from the start, so it says so before it reads anything.
        lock_for_write(session)
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        identity = compose_identity(session, agent, task_type=task_type)
        system_prompt, context = identity.system, identity.context
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
            _assert_policy_allows_run(session, agent, registry)
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
                max_tokens=max_tokens,
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
        # Never echo full message (may contain URLs/secrets)
        error_detail = type(exc).__name__
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


_ROLE_DEFINITIONS = [
    (
        "Director",
        "Grow the studio's audience: raising views and retention is her primary charge. She "
        "directs every department in writing, steers channels and topics from measured "
        "analytics, and documents every decision",
        "plan,review,direct,decide",
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
        "synthesize_voice,audio_align",
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


def seed_initial_workforce(engine: Engine) -> None:
    """Seed baseline roles, the Ollama endpoint, its expected models, and the agents.

    Role work contracts (config/role_contracts.json) are seeded afterwards, on every call,
    because they also have to reach a studio whose roles were created before contracts
    existed; that seed fills only what the Owner has not written.

    Seeding writes intent, never observation. The provider is recorded NOT_CONFIGURED with no
    health-check timestamp and its models unavailable with no verification timestamp, because
    nothing in this function contacts Ollama. Only ``sync_provider_models`` — which does make
    the call — may mark a model available or stamp ``last_verified``.
    """
    _seed_initial_workforce(engine)
    seed_missing_workforce(engine)
    seed_role_contracts(engine)


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
                for c_id in cap_map.values():
                    session.add(
                        ModelCapability(
                            model_id=model.id,
                            capability_id=c_id,
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
