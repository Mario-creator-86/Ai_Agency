"""Phase 1 agent/role/provider services and the Owner Policy Kernel gate.

The policy kernel runs before every LLM invocation:
1. autonomy_stopped check
2. agent lifecycle check
3. capability match check
4. provider health check (cached)
5. adapter presence check
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

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
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from app.workflows.services import append_event_with_outbox

logger = logging.getLogger("studio.agents")


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


def _check_required_capabilities(session: Session, agent: Agent) -> None:
    """Raise PolicyKernelError if the agent model lacks a required role capability."""
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
            .where(ModelCapability.model_id == agent.model_id)
        ).all()
    )

    missing = [c for c in required_caps if c not in model_caps]
    if missing:
        raise PolicyKernelError(
            f"Model lacks required capabilities: {missing}",
            "BLOCKED_CAPABILITY",
        )


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
) -> dict:
    """Execute an agent LLM run through the policy kernel. Returns AgentRunView dict."""
    run_id = str(uuid4())
    started_at = utc_now()

    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        provider_rec = session.get(ProviderRecord, agent.provider_id)
        model_rec = session.get(ModelRecord, agent.model_id)
        if provider_rec is None or model_rec is None:
            raise ValueError("Agent provider or model record missing")

        # --- Policy kernel ---
        try:
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
            )
            session.add(run)
            session.flush()
            return AgentRunView.model_validate(run).model_dump()

        # --- Check adapter present ---
        adapter = registry.get(agent.provider_id)
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
            {"runtime_state": "THINKING", "task_type": task_type},
            correlation_id,
        )

    # Execute outside the DB transaction to avoid holding locks during LLM call
    try:
        gen_result = asyncio.run(
            adapter.generate(
                model_name,
                objective,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        )
        status = "SUCCEEDED"
        output_text = gen_result.text
        error_detail = None
        cost_vr = gen_result.cost_vr
        prompt_tokens = gen_result.prompt_tokens
        completion_tokens = gen_result.completion_tokens
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "agent_run_failed",
            extra={"agent_id": agent_id, "error": type(exc).__name__},
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
        run = AgentRun(
            id=run_id,
            agent_id=agent_id,
            task_type=task_type,
            objective=objective,
            prompt_template_version=prompt_template_version,
            model_name=model_name,
            provider_name=provider_name,
            status=status,
            output=None,
            output_text=output_text,
            error_detail=error_detail,
            cost_vr=cost_vr,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            correlation_id=correlation_id,
            started_at=started_at,
            finished_at=finished_at,
            event_id=event.event_id,
        )
        session.add(run)
        session.flush()

        # The model's real output is the agent's operational message. Emitting it as
        # agent.message_sent (through the outbox, so it reaches the live office) is what the
        # speech-bubble projection consumes — only real messages may become live bubbles
        # (../architecture/06_BACKEND_EVENT_MODEL.md §7). Reasoning models can succeed with
        # no visible text; then there is nothing real to say and no event is emitted.
        message_text = " ".join((output_text or "").split())[:200]
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


def seed_initial_workforce(engine: Engine) -> None:
    """Seed baseline roles, the Ollama endpoint, its expected models, and the agents.

    Seeding writes intent, never observation. The provider is recorded NOT_CONFIGURED with no
    health-check timestamp and its models unavailable with no verification timestamp, because
    nothing in this function contacts Ollama. Only ``sync_provider_models`` — which does make
    the call — may mark a model available or stamp ``last_verified``.
    """
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

        # 3. Cloud Models (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud)
        models_data = [
            ("glm-5.2:cloud", 131072, "General reasoning & direction"),
            ("kimi-k2.6:cloud", 262144, "Long-context research & fact-checking"),
            ("qwen3-coder:480b-cloud", 131072, "Code, script structure & media pipelines"),
        ]
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
                            confidence="DECLARED_BY_PROVIDER",
                        )
                    )
                model_map[m_name] = model.id
            else:
                model_map[m_name] = existing_model.id

        # 4. Roles matching office workstations
        roles_def = [
            (
                "Director",
                "Supervise autonomous studio operations, strategy, and quality",
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
        ]
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
        agents_def = [
            ("Sarah (Director)", "Director", "glm-5.2:cloud"),
            ("Dr. Aris (Researcher)", "LeadResearcher", "kimi-k2.6:cloud"),
            ("Elena (Fact Checker)", "FactChecker", "glm-5.2:cloud"),
            ("Marcus (Script Writer)", "ScriptWriter", "qwen3-coder:480b-cloud"),
            ("Lyra (Voice Artist)", "VoiceArtist", "glm-5.2:cloud"),
            ("Kael (Video Editor)", "VideoEditor", "qwen3-coder:480b-cloud"),
            ("Vera (Publisher)", "Publisher", "glm-5.2:cloud"),
        ]
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
