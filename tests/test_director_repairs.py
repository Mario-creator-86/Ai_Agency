"""The Director repairs what the studio's own data can settle (2026-10-11).

The Owner: «vreau ca directoarea să poată repara asta. Agenția trebuie să fie autonomă; când
apar probleme, directoarea trebuie să fie în măsură să repare». Each test is one of the shapes
the studio had on that day, rebuilt on fakes: the 167 runs left unpriced by a price typed after
them, Nadia's 10-04 retry storm read as a fault of today, a model that does fail now, the
review sent to an Accountant who cannot see a film's cost, a thread that went round nine times,
decisions whose work was over, estimates no invoice ever replaced. Every provider is faked; no
network, no money, and nothing the Owner alone may do is done in his name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.agents.command import direct_company, findings
from app.agents.messages import post_message
from app.agents.models import (
    Agent,
    AgentMessage,
    AgentRun,
    Capability,
    ModelCapability,
    ModelRecord,
    ProviderRecord,
    Role,
)
from app.agents.repairs import registered_repairs
from app.agents.repairs.desk import (
    APPLIED_EVENT,
    REPAIR_TASK,
    execute_repair,
    repair_matters,
    submit_repair,
)
from app.agents.services import _owner_chose_models, owner_home_model, seed_initial_workforce
from app.analytics.models import AnalyticsSnapshot, DirectorDecision
from app.analytics.performance import video_performance
from app.decisions.models import OwnerDecision
from app.economy.models import ProviderCostRecord, ProviderPrice
from app.economy.prices import PriceCommand, llm_cost_vr, set_price
from app.economy.services import to_micros
from app.factual.models import ScriptDraft, TopicIdea
from app.integrations.models import Integration
from app.integrations.services import assign_agent
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import seed_default_channels
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem
from app.workflows.worker import DIRECTOR_REPAIR, build_task_handlers, work_once
from sqlalchemy import func, select
from sqlalchemy.orm import Session

NOW = datetime.now(UTC)

# ----------------------------------------------------------------------------- the studio


@pytest.fixture
def studio(engine):
    """A staffed studio with its channels, the stop cleared, AUTONOMOUS_CEO."""
    return staffed_studio(engine)


def staffed_studio(engine) -> dict[str, Any]:
    """The `studio` fixture's work, for the other modules that need the same studio."""
    seed_initial_workforce(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        channel_id = session.scalar(select(ChannelRecord.id).order_by(ChannelRecord.channel_name))
        local = session.scalar(
            select(ProviderRecord.id).where(ProviderRecord.name == "local-ollama")
        )
    return {"channel_id": channel_id, "local_provider": local}


def agent_of(engine, role: str) -> Agent:
    with Session(engine) as session:
        agent = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == role)
        )
        session.expunge(agent)
        return agent


def a_connection(engine, *, kind="ollama", name="Ollama Cloud", status="VERIFIED", models=()):
    """A model connection the Owner saved (and verified), with its models, as Settings
    leaves them: a ProviderRecord ``settings:<id>`` beside the Integration."""
    integration_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", integration_id, 1, {}, "c"
        )
        session.add(
            Integration(
                id=integration_id,
                kind=kind,
                name=name,
                config={},
                encrypted_secrets="",
                secret_fields=[],
                version=1,
                status=status,
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )
        session.add(
            ProviderRecord(
                id=integration_id,
                name=f"settings:{integration_id}",
                provider_type=kind,
                base_url="",
                status="HEALTHY",
                last_health_check=utc_now(),
                adapter_version="1.0.0",
                notes=name,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        session.flush()
        capability = session.scalar(
            select(Capability.id).where(Capability.name == "text_generation")
        )
        ids: dict[str, str] = {}
        for model_name in models:
            model_id = str(uuid4())
            session.add(
                ModelRecord(
                    id=model_id,
                    provider_id=integration_id,
                    model_name=model_name,
                    discovery_method="DECLARED_BY_PROVIDER",
                    context_length=None,
                    last_verified=utc_now(),
                    is_available=True,
                    notes="",
                )
            )
            session.flush()
            session.add(
                ModelCapability(model_id=model_id, capability_id=capability, confidence="DECLARED")
            )
            ids[model_name] = model_id
    return {"id": integration_id, "provider": f"settings:{integration_id}", "models": ids}


def this_month(engine, ago: timedelta) -> datetime:
    """``ago`` before now, kept inside the books' current month (the reprice window), so a
    run placed «a while ago» is this month's on the first days of a month too."""
    from app.agents.repairs.reprice import month_start

    return max(datetime.fromisoformat(month_start(engine)) + timedelta(seconds=1), NOW - ago)


def owner_price(engine, kind="ollama", usd="0.5"):
    """The Owner's own price on both token sides (his command, typed in the test as him)."""
    for unit in ("per_1m_input_tokens", "per_1m_output_tokens"):
        set_price(
            engine,
            PriceCommand(command_id=uuid4(), provider_kind=kind, resource="*", unit=unit, usd=usd),
        )


def runs(
    engine,
    agent_id,
    *,
    model,
    provider,
    at,
    n=1,
    status="SUCCEEDED",
    prompt=100,
    completion=10,
    cost=None,
    error=None,
    task="answer_mail",
    spacing_seconds=1.0,
):
    """``n`` runs as `run_agent_task` leaves them, from ``at`` on."""
    with Session(engine) as session, session.begin():
        for index in range(n):
            moment = (at + timedelta(seconds=index * spacing_seconds)).isoformat()
            ok = status == "SUCCEEDED"
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=agent_id,
                    task_type=task,
                    objective="x",
                    prompt_template_version="v1",
                    model_name=model,
                    provider_name=provider,
                    status=status,
                    output=None,
                    output_text="ok" if ok else None,
                    error_detail=error,
                    cost_vr=cost,
                    prompt_tokens=(prompt if isinstance(prompt, int) else prompt[index])
                    if ok
                    else None,
                    completion_tokens=(
                        completion if isinstance(completion, int) else completion[index]
                    )
                    if ok
                    else None,
                    correlation_id=str(uuid4()),
                    started_at=moment,
                    finished_at=moment,
                    event_id=None,
                    context_json={},
                )
            )


def run_repair(engine, settings, matter, registry=None, decision="ITERATE") -> dict[str, Any]:
    """The Director's choice of one matter's repair, then the worker's task, as the loop and
    the worker do it."""
    queued = submit_repair(
        engine,
        matter=matter,
        spec=matter["repair"],
        decision=decision,
        interpretation="",
        confidence="HIGH",
        correlation_id=str(uuid4()),
        run_id=None,
        published=0,
    )
    assert queued["status"] == "QUEUED", queued
    with Session(engine) as session:
        task = session.get(TaskQueueItem, queued["task_id"])
        payload, task_id = dict(task.payload), task.id
    return {
        "queued": queued,
        "result": execute_repair(engine, registry, settings, payload, correlation_id=task_id),
    }


def matter_of(engine, settings, key_prefix: str, registry=None) -> dict[str, Any]:
    found = [
        m
        for m in repair_matters(engine, settings, registry)
        if m["matter_key"].startswith(key_prefix)
    ]
    seen = [m["matter_key"] for m in repair_matters(engine, settings, registry)]
    assert found, f"no matter {key_prefix!r} among {seen}"
    return found[0]


def letters_to(engine, agent_id) -> list[AgentMessage]:
    with Session(engine) as session:
        return list(
            session.scalars(select(AgentMessage).where(AgentMessage.to_agent_id == agent_id))
        )


def owner_letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            m
            for m in session.scalars(select(AgentMessage).where(AgentMessage.to_agent_id.is_(None)))
            if (m.body_json or {}).get("to") == "Owner"
        ]


def director_reports(engine) -> list[AgentMessage]:
    """Her repairs' reports: information in her own thread, closed as written, never a letter
    to the Owner (2026-10-12: «nu trebuie să ajungă la mine, este la Director»)."""
    with Session(engine) as session:
        return [
            m
            for m in session.scalars(select(AgentMessage).where(AgentMessage.intent == "STATUS"))
            if (m.body_json or {}).get("kind") == "director_repair"
        ]


def assert_a_report_not_a_letter(engine, words: str) -> AgentMessage:
    """One report whose subject says ``words``, read as information: closed as written, in her
    own thread, and no letter waiting for the Owner."""
    assert owner_letters(engine) == [], "a report is not a letter waiting for the Owner"
    (report,) = director_reports(engine)
    assert words in report.subject
    assert report.status == "RESOLVED" and report.resolution.startswith("De citit")
    assert report.to_agent_id == report.from_agent_id, "her own thread"
    assert (report.body_json or {}).get("to") != "Owner"
    return report


def cards(engine, prefix="") -> list[OwnerDecision]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(OwnerDecision).where(OwnerDecision.dedupe_key.like(f"{prefix}%"))
            )
        )


def events(engine, event_type) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type))
        )


# ------------------------------------------------------------------- the desk is complete


def test_every_repair_of_the_day_is_registered_with_a_tier_she_may_hold():
    repairs = registered_repairs()
    assert set(repairs) >= {
        "reprice_unpriced_runs",
        "diagnose_agent",
        "switch_agent_model",
        "film_cost_report",
        "close_thread",
        "close_stale_decisions",
        "unbilled_estimates",
    }
    assert {name: r.tier for name, r in repairs.items()} == {
        **{name: r.tier for name, r in repairs.items()},
        "switch_agent_model": "T2",
        "reprice_unpriced_runs": "T1",
        "diagnose_agent": "T0",
        # It closes the decision it reviews and the letters that asked for it: a write.
        "film_cost_report": "T1",
    }
    assert repairs["switch_agent_model"].action == "agent.change_model"
    assert repairs["film_cost_report"].action != "analytics.read"
    assert all(r.tier in ("T0", "T1", "T2", "T3") for r in repairs.values())
    assert DIRECTOR_REPAIR == REPAIR_TASK


# ------------------------------------------------------------- 1. the 167 unpriced runs


TODAY_SHAPE = {
    # model: (runs, prompt tokens, completion tokens), the copy of 2026-10-11.
    "kimi-k3": (108, 792_318, 88_671),
    "mistral-large-3:675b": (34, 166_710, 17_872),
    "minimax-m3": (20, 76_851, 9_950),
    "nemotron-3-ultra": (3, 4_934, 159),
    "deepseek-v4-pro:0813": (2, 11_444, 154),
}


def _spread(total: int, n: int) -> list[int]:
    return [total // n + (1 if index < total % n else 0) for index in range(n)]


def test_the_167_runs_left_unpriced_are_priced_at_the_active_price_once(engine, studio, settings):
    cloud = a_connection(engine, models=tuple(TODAY_SHAPE))
    sarah = agent_of(engine, "Director")
    ran_at = this_month(engine, timedelta(hours=6))
    for model, (n, prompt, completion) in TODAY_SHAPE.items():
        runs(
            engine,
            sarah.id,
            model=model,
            provider=cloud["provider"],
            at=ran_at,
            n=n,
            prompt=_spread(prompt, n),
            completion=_spread(completion, n),
        )
    # Two on the seeded endpoint: its kind is its type, lower-cased, as the preflight reads it.
    runs(engine, sarah.id, model="kimi-k3:cloud", provider="local-ollama", at=ran_at, n=2)
    # A run that failed has no tokens to price, and one already priced keeps its cost.
    runs(engine, sarah.id, model="kimi-k3", provider=cloud["provider"], at=ran_at, status="FAILED")
    runs(engine, sarah.id, model="kimi-k3", provider=cloud["provider"], at=ran_at, cost="0.1")
    # Last month's, before any price existed: history, counted and left as it is.
    from app.agents.repairs.reprice import month_start

    last_month = datetime.fromisoformat(month_start(engine)) - timedelta(days=10)
    runs(engine, sarah.id, model="kimi-k3", provider=cloud["provider"], at=last_month, n=5)
    owner_price(engine)  # typed after the runs, as on 2026-10-05 13:46
    prices_before = _count(engine, ProviderPrice)

    matter = matter_of(engine, settings, "unpriced_usage")
    assert matter["repair"]["name"] == "reprice_unpriced_runs"
    assert matter["evidence"]["runs"] == 169
    assert matter["evidence"]["older_runs"] == 5 and "lunile trecute" in matter["observation"]
    done = run_repair(engine, settings, matter)
    assert done["result"]["status"] == "APPLIED"

    expected = 0
    with Session(engine) as session:
        priced = list(
            session.scalars(
                select(AgentRun).where(
                    AgentRun.status == "SUCCEEDED",
                    AgentRun.cost_vr.is_not(None),
                    AgentRun.cost_vr != "0.1",
                )
            )
        )
        assert len(priced) == 169
        assert (
            session.scalar(
                select(func.count()).where(
                    AgentRun.started_at < month_start(engine), AgentRun.cost_vr.is_(None)
                )
            )
            == 5
        )
        for run in priced:
            # The adapters' own arithmetic, at the price active now.
            assert run.cost_vr == llm_cost_vr(
                lambda _r, _u: 500_000, run.model_name, run.prompt_tokens, run.completion_tokens
            )
            stamp = run.context_json["priced_after"]
            assert stamp["by"] == "director" and len(stamp["price_ids"]) == 2
            expected += to_micros(run.cost_vr)
        assert session.scalar(select(AgentRun.cost_vr).where(AgentRun.cost_vr == "0.1")) == "0.1"
    today_shape = sum(
        to_micros(
            llm_cost_vr(lambda _r, _u: 500_000, "m", p, c)  # type: ignore[arg-type]
        )
        for model, (n, prompt, completion) in TODAY_SHAPE.items()
        for p, c in zip(_spread(prompt, n), _spread(completion, n), strict=True)
    )
    # 0.584531 USD on the copy, priced in aggregate; per run, rounded to the micro.
    assert abs(today_shape - 584_531) <= 167
    (repriced,) = events(engine, "economy.agent_runs_repriced")
    assert repriced.payload["count"] == 169 and repriced.payload["usd_micros"] == expected
    # Recorded, decided, told; and no price was written by anyone but the Owner.
    assert _count(engine, ProviderPrice) == prices_before
    (applied,) = events(engine, APPLIED_EVENT)
    assert applied.payload["repair"] == "reprice_unpriced_runs"
    with Session(engine) as session:
        decision = session.get(DirectorDecision, done["queued"]["decision_id"])
        assert decision.state == "REVIEWED" and "169" in decision.outcome
        assert decision.owner_role == "Director"
    # Reported, as information in her own thread: nothing here asks the Owner anything.
    assert_a_report_not_a_letter(engine, "169")
    assert not letters_to(engine, agent_of(engine, "Accountant").id)

    # Once is once: the same case is not offered again, and a second repair finds nothing.
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "unpriced_usage"]
    again = execute_repair(
        engine, None, settings, {"repair": "reprice_unpriced_runs"}, correlation_id=str(uuid4())
    )
    assert again["status"] == "NOTHING_TO_DO"
    assert len(events(engine, "economy.agent_runs_repriced")) == 1


def _count(engine, table) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_repricing_is_refused_when_it_would_push_a_budget_over_its_limit(engine, studio, settings):
    from app.economy.budget import BudgetCommand, set_budget

    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(seconds=5)),
        n=3,
        spacing_seconds=0.1,
        prompt=1_000_000,
        completion=1_000_000,
    )
    owner_price(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="2"))
    result = execute_repair(
        engine, None, settings, {"repair": "reprice_unpriced_runs"}, correlation_id=str(uuid4())
    )
    assert result["status"] == "DECLINED"
    assert "bugetul" in result["outcome"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).where(AgentRun.cost_vr.is_not(None))) == 0
    assert not events(engine, "economy.agent_runs_repriced")


def test_a_model_no_price_covers_is_one_card_for_the_owner_never_a_price(
    engine, studio, settings, monkeypatch
):
    from app.agents.repairs import reprice

    other = a_connection(engine, kind="openai", name="OpenAI", models=("gpt-x",))
    sarah = agent_of(engine, "Director")
    at = this_month(engine, timedelta(hours=1))
    runs(engine, sarah.id, model="gpt-x", provider=other["provider"], at=at, n=4)
    # Runs this fresh are not yet a question for him: he may be typing the price.
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "unpriced_usage"]
    # A day on (the grace made nought here), the Owner's question, through her repair.
    monkeypatch.setattr(reprice, "UNCOVERED_GRACE_HOURS", 0)
    assert matter_of(engine, settings, "unpriced_usage")["evidence"]["runs"] == 4
    prices_before = _count(engine, ProviderPrice)

    for _ in range(2):
        execute_repair(
            engine, None, settings, {"repair": "reprice_unpriced_runs"}, correlation_id=str(uuid4())
        )
    (card,) = cards(engine, "director_price:")
    assert card.dedupe_key == "director_price:openai" and card.status == "PENDING"
    assert card.options[0]["apply"]["place_ro"] == "Autonomie → Prețurile modelelor"
    assert _count(engine, ProviderPrice) == prices_before
    # With his card open the case is his: the loop does not raise it again.
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "unpriced_usage"]

    # He types the price; the next repair applies it and withdraws his card.
    owner_price(engine, kind="openai", usd="1")
    assert matter_of(engine, settings, "unpriced_usage")["evidence"]["runs"] == 4
    result = execute_repair(
        engine, None, settings, {"repair": "reprice_unpriced_runs"}, correlation_id=str(uuid4())
    )
    assert result["status"] == "APPLIED"
    (card,) = cards(engine, "director_price:")
    assert card.status == "WITHDRAWN"


# ------------------------------------------------------------- 2. Nadia's 10-04 storm


def test_the_retry_storm_of_ten_days_ago_is_stale_history_and_nothing_is_switched(
    engine, studio, settings
):
    cloud = a_connection(engine, models=("mistral-large-4",))
    nadia = agent_of(engine, "Accountant")
    assign_agent(engine, nadia.id, cloud["models"]["mistral-large-4"], nadia.version)
    storm = NOW - timedelta(days=7)
    # Three letters, each retried about 160 times at worker-pass cadence, on a model she has
    # left since, then her current model working.
    runs(
        engine,
        nadia.id,
        model="glm-5.3-flash:cloud",
        provider="local-ollama",
        at=storm,
        n=480,
        status="FAILED",
        error="HTTPError",
        spacing_seconds=18,
    )
    runs(
        engine,
        nadia.id,
        model="mistral-large-4",
        provider=cloud["provider"],
        at=NOW - timedelta(days=3),
        n=25,
        spacing_seconds=3600,
    )
    matter = matter_of(engine, settings, "agent_failing_")
    assert matter["repair"]["name"] == "diagnose_agent", "a 30-day rate is not a fault of today"
    assert matter["evidence"]["cause"] == "STALE_HISTORY"
    assert matter["evidence"]["failing_now"] is False
    (burst,) = matter["evidence"]["bursts"]
    assert burst["failures"] == 480
    assert burst["models"] == {"glm-5.3-flash:cloud @ local-ollama": 480}

    with Session(engine) as session:
        version = session.get(Agent, nadia.id).version
    done = run_repair(engine, settings, matter)
    assert done["result"]["status"] == "APPLIED"
    assert "STALE_HISTORY" in done["result"]["outcome"]
    assert "480" in done["result"]["outcome"]
    with Session(engine) as session:
        after = session.get(Agent, nadia.id)
        assert after.model_id == cloud["models"]["mistral-large-4"] and after.version == version
    assigned = [e for e in events(engine, "agent.model_assigned") if e.aggregate_id == nadia.id]
    assert [e.payload["assignment_origin"] for e in assigned] == ["OWNER"]


# ------------------------------------------------------------- 3. a model that fails now


class Models:
    """One provider's models, faked: a name that refuses answers like a refused key."""

    def __init__(self, refusing: set[str]):
        self.refusing = refusing
        self.asked: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        from app.integrations.llm import ProviderHTTPError

        self.asked.append(model)
        if model in self.refusing:
            raise ProviderHTTPError(401)
        return GenerateResult("OK", 12, 1, None)


def test_a_model_failing_now_is_switched_once_with_a_probe_and_what_to_revert_to(
    engine, studio, settings
):
    settings.model_deny_list = "denied-*"
    cloud = a_connection(
        engine,
        models=("broken-model", "claude-sonnet", "denied-model", "working-model"),
    )
    unpriced = a_connection(engine, kind="openai", name="OpenAI", models=("gpt-unpriced",))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["broken-model"], lyra.version)
    # Her model's last three runs since it was set were refused by the provider: it fails now.
    runs(
        engine,
        lyra.id,
        model="broken-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),
        n=3,
        status="FAILED",
        error="ProviderHTTPError: HTTP 401 — cheia conexiunii este respinsă",
    )
    fake = Models(refusing={"broken-model"})
    registry = ProviderRegistry()
    registry.register(cloud["id"], fake)
    registry.register(unpriced["id"], Models(refusing=set()))

    matter = matter_of(engine, settings, "agent_failing_", registry)
    assert matter["repair"]["name"] == "switch_agent_model"
    assert matter["evidence"]["cause"] == "PROVIDER_AUTH"
    done = run_repair(engine, settings, matter, registry)
    assert done["result"]["status"] == "APPLIED", done["result"]

    # Her own model asked first, and refused; then, not Anthropic, not denied, not unpriced:
    # the one that passed the probe.
    assert fake.asked == ["broken-model", "working-model"]
    with Session(engine) as session:
        moved = session.get(Agent, lyra.id)
        assert moved.model_id == cloud["models"]["working-model"]
        own, probe = session.scalars(
            select(AgentRun)
            .where(AgentRun.task_type == "TEST_CONNECTIVITY")
            .order_by(AgentRun.started_at)
        ).all()
        assert own.status == "FAILED" and own.model_name == "broken-model"
        assert probe.status == "SUCCEEDED" and probe.model_name == "working-model"
        # His choice stands behind the detour: home, and protected from the preference mover.
        assert owner_home_model(session, lyra.id) == cloud["models"]["broken-model"]
        assert _owner_chose_models(session, moved, "VoiceArtist") is True
    (assigned,) = [
        e
        for e in events(engine, "agent.model_assigned")
        if e.aggregate_id == lyra.id and e.payload["assignment_origin"] == "DIRECTOR_REPAIR"
    ]
    assert assigned.payload["previous"]["model_id"] == cloud["models"]["broken-model"]
    (applied,) = events(engine, APPLIED_EVENT)
    changed = applied.payload["changed"]
    assert changed["revert"]["model_id"] == cloud["models"]["broken-model"]
    assert changed["home_model_id"] == cloud["models"]["broken-model"]
    assert [p["run_id"] for p in changed["probes"]] == [own.id, probe.id]
    assert_a_report_not_a_letter(engine, "working-model")

    # The same day her new model fails too: not a second switch, one card for the Owner.
    fake.refusing.add("working-model")
    runs(
        engine,
        lyra.id,
        model="working-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),  # after the probe that put her there
        n=3,
        status="FAILED",
        error="ProviderHTTPError: HTTP 429 — limita",
    )
    again = run_repair(
        engine, settings, matter_of(engine, settings, "agent_failing_", registry), registry
    )
    assert again["result"]["status"] == "DECLINED"
    assert "o dată" in again["result"]["outcome"]
    # The same case is not offered twice; a second task for it changes nothing either.
    assert not [
        m
        for m in repair_matters(engine, settings, registry)
        if m["matter_key"].startswith("agent_")
    ]
    execute_repair(
        engine,
        registry,
        settings,
        {"repair": "switch_agent_model", "params": {"agent_id": lyra.id}},
        correlation_id=str(uuid4()),
    )
    (card,) = cards(engine, "director_model:")
    assert card.subject_id == lyra.id and card.status == "PENDING"
    with Session(engine) as session:
        assert session.get(Agent, lyra.id).model_id == cloud["models"]["working-model"]


def test_a_model_change_waits_for_the_owner_where_her_mode_does_not_reach_t2(
    engine, studio, settings
):
    cloud = a_connection(engine, models=("broken-model", "working-model"))
    owner_price(engine)
    lyra = agent_of(engine, "VoiceArtist")
    assign_agent(engine, lyra.id, cloud["models"]["broken-model"], lyra.version)
    runs(
        engine,
        lyra.id,
        model="broken-model",
        provider=cloud["provider"],
        at=datetime.now(UTC),
        n=3,
        status="FAILED",
        error="HTTPError",
    )
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "MANUAL"  # his mode, set as the suite does
    matter = matter_of(engine, settings, "agent_failing_")
    refused = submit_repair(
        engine,
        matter=matter,
        spec=matter["repair"],
        decision="ITERATE",
        interpretation="",
        confidence="HIGH",
        correlation_id=str(uuid4()),
        run_id=None,
        published=0,
    )
    assert refused["status"] == "REFUSED" and refused["verdict"] == "BLOCKED_MODE"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(DirectorDecision)) == 0
        assert session.scalar(select(func.count()).select_from(TaskQueueItem)) == 0


# ------------------------------------------------------------- 4. what a film cost


def a_published_film(engine, channel_id) -> dict[str, str]:
    """The Higgs film's shape: shots booked on the board (RunPod), narration on the render
    (ElevenLabs), a rejected first board of the same topic (Runway), measured returns."""
    topic_id, first_script, script = str(uuid4()), str(uuid4()), str(uuid4())
    rejected, board, job, asset, publication = (str(uuid4()) for _ in range(5))
    published_at = (NOW - timedelta(days=1)).isoformat()
    with Session(engine) as session, session.begin():
        event = append_event(session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, "c")
        session.add(
            TopicIdea(
                id=topic_id,
                title="The Higgs Boson",
                topic="physics",
                angle="",
                target_audience="general",
                novelty_score=0.5,
                status="PRODUCED",
                scores_json={},
                source_plan_json=[],
                thesis_json={},
                rejection_reasons_json=[],
                created_at=published_at,
                event_id=event.event_id,
            )
        )
        for script_id, board_id, status in (
            (first_script, rejected, "REJECTED"),
            (script, board, "COMPLETED"),
        ):
            session.add(
                ScriptDraft(
                    id=script_id,
                    topic_id=topic_id,
                    version=1,
                    title="The Higgs Boson",
                    target_duration_seconds=30,
                    voiceover_full_text="Words.",
                    scenes_json=[],
                    status="APPROVED",
                    claim_ids_json=[],
                    unverified_claim_ids_json=[],
                    created_at=published_at,
                )
            )
            session.flush()  # the board's script first: no relationship orders the inserts
            session.add(
                Storyboard(
                    id=board_id,
                    script_draft_id=script_id,
                    title="The Higgs Boson",
                    visual_style="MOTION_GRAPHIC",
                    aspect_ratio="9:16",
                    target_duration_seconds=30,
                    status=status,
                    total_scenes=0,
                    created_at=published_at,
                )
            )
        session.add(
            MediaAsset(
                id=asset,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"/media/{asset}.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=30.0,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="a" * 64,
                created_at=published_at,
            )
        )
        session.add(
            VideoRenderJob(
                id=job,
                storyboard_id=board,
                output_asset_id=asset,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json={},
                started_at=published_at,
                duration_ms=60000.0,
            )
        )
        session.add(
            PublicationRecord(
                id=publication,
                channel_id=channel_id,
                media_asset_id=asset,
                title="The Higgs Boson",
                description="",
                tags_json=[],
                privacy_status="public",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=f"yt-{publication[:8]}",
                published_at=published_at,
                created_at=published_at,
            )
        )
        costs = [("runpod", 509_383, {"storyboard_id": board}) for _ in range(9)]
        costs += [("elevenlabs", 56_760, {"render_job_id": job})]
        costs += [("runway", 1_620_000, {"storyboard_id": rejected, "credits": 162.0})]
        for provider, micros, attribution in costs:
            session.add(
                ProviderCostRecord(
                    id=str(uuid4()),
                    provider=provider,
                    external_reference=str(uuid4()),
                    status="ESTIMATED",
                    amount_micros=micros,
                    currency="USD",
                    usd_micros=micros,
                    attribution_json=attribution,
                    recorded_at=published_at,
                )
            )
        snapshot = append_event(
            session, "analytics.snapshot_ingested", "analytics_snapshot", str(uuid4()), 1, {}, "c"
        )
        session.add(
            AnalyticsSnapshot(
                id=str(uuid4()),
                publication_id=publication,
                channel_id=channel_id,
                window="LIFETIME",
                views=120,
                watch_time_seconds=1800.0,
                average_view_percentage=61.0,
                impressions=900,
                ctr_percentage=4.2,
                likes=7,
                comments=1,
                shares=0,
                subscribers_gained=2,
                subscribers_lost=0,
                raw_metrics_json={},
                snapshot_at=utc_now(),
                event_id=snapshot.event_id,
            )
        )
    return {"publication_id": publication, "storyboard_id": board, "rejected": rejected}


def test_the_performance_page_reads_a_films_cost_from_its_board_not_only_its_render(engine, studio):
    film = a_published_film(engine, studio["channel_id"])
    (row,) = [f for f in video_performance(engine) if f["publication_id"] == film["publication_id"]]
    # 9 RunPod rows on the board (4.584447) + the narration on the render; holds and the
    # rejected sibling board are not this film's.
    assert row["cost_usd"] == round((9 * 509_383 + 56_760) / 1_000_000, 4)
    assert row["views_per_dollar"] is not None


def an_open_decision(engine, *, matter_key, action, role, message_id=None, **extra) -> str:
    decision_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            DirectorDecision(
                id=decision_id,
                scope="COMPANY",
                channel_id=None,
                observation="o",
                evidence_json={},
                interpretation="i",
                confidence="MEDIUM",
                decision=extra.get("decision", "CONTINUE"),
                action=action,
                owner_role=role,
                review_after_videos=extra.get("review_after_videos", 1),
                review_after_at=None,
                state=extra.get("state", "OPEN"),
                outcome=extra.get("outcome"),
                published_at_decision=0,
                matter_key=matter_key,
                message_id=message_id,
                agent_id=None,
                run_id=None,
                created_at=extra.get("created_at", utc_now()),
                reviewed_at=extra.get("reviewed_at"),
            )
        )
    return decision_id


def a_handoff(engine, to_role, subject="Continuă: costul filmelor") -> str:
    sarah, target = agent_of(engine, "Director"), agent_of(engine, to_role)
    with Session(engine) as session, session.begin():
        return post_message(
            session,
            intent="HANDOFF",
            subject=subject,
            body={"kind": "direction"},
            body_text="DE FĂCUT: report what a film cost against what it returned",
            from_agent_id=sarah.id,
            to_agent_id=target.id,
        ).id


def test_a_review_is_closed_with_the_film_cost_report_and_no_letter_to_nadia(
    engine, studio, settings
):
    film = a_published_film(engine, studio["channel_id"])
    nadia = agent_of(engine, "Accountant")
    handoff = a_handoff(engine, "Accountant")
    reviewed = an_open_decision(
        engine,
        matter_key="cold_start_23d3ba8b",
        action="report what a film cost against what it returned",
        role="Accountant",
        message_id=handoff,
    )
    letters_before = len(letters_to(engine, nadia.id))
    state_matters = findings(engine, settings, _state(engine, settings))
    review = next(m for m in state_matters if m["matter_key"] == "review_cold_start_23d3ba8b")
    assert review["owner_role"] == "Director"
    assert review["repair"] == {
        "name": "film_cost_report",
        "params": {"decision_id": reviewed},
        "fingerprint": review["repair"]["fingerprint"],
    }

    # The loop, with a model that answers nothing usable: the measurements decide.
    registry = ProviderRegistry()
    registry.register(studio["local_provider"], Models(refusing=set()))
    result = direct_company(engine, registry, settings)
    assert "review_cold_start_23d3ba8b" in {r["matter_key"] for r in result["repairs"]}
    assert len(letters_to(engine, nadia.id)) == letters_before, "no letter to Nadia"

    handlers = build_task_handlers(engine, settings, None, None, registry)
    while (done := work_once(engine, handlers)) is not None:
        assert done["status"] == "COMPLETED", done
    with Session(engine) as session:
        closed = session.get(DirectorDecision, reviewed)
        assert closed.state == "REVIEWED"
        # 4,641207 on its board and 1,62 on the rejected board of the same topic, in two
        # decimals (2026-10-12, the Owner: «să îmi spună exact … nu trebuie să conțină cod»)
        assert "The Higgs Boson" in closed.outcome and "6,26 USD" in closed.outcome
        assert "din care 1,62 pe încercări refăcute" in closed.outcome
        assert "120 de vizualizări" in closed.outcome or "120 vizualizări" in closed.outcome
        assert "4,641207" not in closed.outcome and "neatribuit" not in closed.outcome
        letter = session.get(AgentMessage, handoff)
        assert letter.status == "RESOLVED" and "The Higgs Boson" in letter.resolution
        (own,) = session.scalars(
            select(DirectorDecision).where(
                DirectorDecision.matter_key == "review_cold_start_23d3ba8b"
            )
        ).all()
        assert own.state == "REVIEWED" and own.owner_role == "Director"
    assert any(e.payload["repair"] == "film_cost_report" for e in events(engine, APPLIED_EVENT))
    assert film["storyboard_id"]


def _state(engine, settings):
    from app.agents.command import company_state

    return company_state(engine, settings)


# ------------------------------------------------------------- 5. a thread going round


def test_a_looping_thread_is_closed_but_not_the_owners_letter(engine, studio, settings):
    a_published_film(engine, studio["channel_id"])
    nadia, sarah = agent_of(engine, "Accountant"), agent_of(engine, "Director")
    handoff = a_handoff(engine, "Accountant")
    decision = an_open_decision(
        engine,
        matter_key="review_bottleneck_research",
        action="report what a film cost against what it returned",
        role="Accountant",
        message_id=handoff,
        review_after_videos=50,
    )
    with Session(engine) as session, session.begin():
        reply = None
        for _ in range(3):
            reply = post_message(
                session,
                intent="STATUS",
                subject="Re: Continuă: costul filmelor",
                body={"done": False, "needs": "rate card", "about_message_id": handoff},
                body_text="Nu pot atribui costul fără lista de prețuri a modelelor.",
                from_agent_id=nadia.id,
                to_agent_id=None,
                in_reply_to=handoff,
            )
        asking = post_message(
            session,
            intent="REQUEST_INFO",
            subject="De investigat: cost",
            body={},
            body_text="Ce lipsește?",
            from_agent_id=sarah.id,
            to_agent_id=nadia.id,
            in_reply_to=reply.id,
        )
        his = post_message(
            session,
            intent="ESCALATE",
            subject="Decizia ta: prețuri",
            body={},
            body_text="Proprietare, ...",
            from_agent_id=sarah.id,
            to_owner=True,
            in_reply_to=reply.id,
        )
        asking_id, his_id = asking.id, his.id

    matter = matter_of(engine, settings, "thread_loops")
    assert matter["repair"]["name"] == "close_thread"
    assert "burst" in matter["evidence"]["threads"][0]["reasons"]
    assert "duplicate" in matter["evidence"]["threads"][0]["reasons"]
    done = run_repair(engine, settings, matter)
    assert done["result"]["status"] == "APPLIED"
    with Session(engine) as session:
        for letter_id in (handoff, asking_id):
            letter = session.get(AgentMessage, letter_id)
            assert letter.status == "RESOLVED" and letter.resolved_by == sarah.display_name
        assert session.get(AgentMessage, his_id).status == "OPEN", "his letter is his"
        closed = session.get(DirectorDecision, decision)
        assert closed.state == "REVIEWED" and "The Higgs Boson" in closed.outcome
    # Closed is closed: nothing loops any more.
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "thread_loops"]


def test_a_handoff_answered_not_done_yet_is_work_in_hand_not_a_loop(engine, studio, settings):
    """Review of 2026-10-11: one «not done yet» was read as a loop after three days, which on
    the studio's copy would have closed 15 of 19 open threads, the week's standing guidance
    and the HANDOFFs of decisions still inside their review among them."""
    nadia, kael, sarah = (agent_of(engine, r) for r in ("Accountant", "VideoEditor", "Director"))
    handoff = a_handoff(engine, "Accountant", subject="Raportează luna")
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="STATUS",
            subject="Re: Raportează luna",
            body={"done": False, "needs": "", "about_message_id": handoff},
            body_text="Încă lucrez.",
            from_agent_id=nadia.id,
            in_reply_to=handoff,
        )
        weekly = post_message(
            session,
            intent="HANDOFF",
            subject="Indicațiile Directorului pentru departamentul de video — 2026-W41",
            body={"instructions": "Primul cadru: mișcare din prima secundă.", "week": "2026-W41"},
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        ).id
        post_message(
            session,
            intent="STATUS",
            subject="Re: Indicațiile Directorului",
            body={"done": False, "needs": "", "about_message_id": weekly},
            body_text="Am notat; le aplic toată săptămâna.",
            from_agent_id=kael.id,
            in_reply_to=weekly,
        )
        for letter in session.scalars(select(AgentMessage)):
            letter.created_at = (NOW - timedelta(days=4)).isoformat()
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "thread_loops"]


def test_the_owners_own_conversation_is_never_closed_by_the_director(engine, studio, settings):
    from app.agents.repairs.threads import close_thread_letters

    nadia = agent_of(engine, "Accountant")
    with Session(engine) as session, session.begin():
        his = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Cât am cheltuit?",
            body={"from": "Owner"},
            body_text="Nadia, cât am cheltuit luna asta?",
            to_agent_id=nadia.id,
        )
        for _ in range(3):
            post_message(
                session,
                intent="STATUS",
                subject="Re: Cât am cheltuit?",
                body={"done": False, "about_message_id": his.id},
                body_text="Am cheltuit 7 USD.",
                from_agent_id=nadia.id,
                to_owner=False,
                in_reply_to=his.id,
            )
        his_id = his.id
    assert not [m for m in repair_matters(engine, settings) if m["matter_key"] == "thread_loops"]
    with Session(engine) as session, session.begin():
        closed = close_thread_letters(
            session, his_id, resolution="x", resolved_by="Sarah", correlation_id=str(uuid4())
        )
        assert his_id not in closed
        assert session.get(AgentMessage, his_id).status == "OPEN"


def choosing(choice: dict[str, Any]) -> type:
    """Her model, faked: it chooses ``choice`` and nothing else."""
    import json as json_module

    class Chooses(Models):
        async def generate(self, model, prompt, **kwargs):
            self.asked.append(prompt)
            return GenerateResult(json_module.dumps({"choices": [choice]}), 50, 20, None)

    return Chooses


def test_a_film_cost_asked_of_a_department_is_computed_not_written(engine, studio, settings):
    """Her model may still name the Accountant for the review of a decision that asked what
    a film cost: the work is one the studio computes, so it is done by the desk and nobody is
    written to (`ACTION_REPAIRS`); and the report is hers to read, not the Owner's letter."""
    from app.agents.repairs.film_cost import film_report, report_words
    from app.wording import owner_text_problems

    a_published_film(engine, studio["channel_id"])
    nadia = agent_of(engine, "Accountant")
    reviewed = an_open_decision(
        engine,
        matter_key="growth_reach_12345678",
        # her model's own words for it (2026-10-11)
        action="Report what a film cost against what it returned for the 3 measured films",
        role="Accountant",
    )
    model = choosing(
        {
            "matter_key": "review_growth_reach_12345678",
            "decision": "CONTINUE",
            "interpretation": "one film",
            "confidence": "LOW",
            "action": "report what a film cost against what it returned",
            "owner_role": "Accountant",
        }
    )(refusing=set())
    registry = ProviderRegistry()
    registry.register(studio["local_provider"], model)
    result = direct_company(engine, registry, settings)
    assert "director_repairs" in model.asked[0] and "film_cost_report" in model.asked[0]
    assert [r["matter_key"] for r in result["repairs"]] == ["review_growth_reach_12345678"]
    assert not letters_to(engine, nadia.id)
    handlers = build_task_handlers(engine, settings, None, None, registry)
    while work_once(engine, handlers) is not None:
        pass
    with Session(engine) as session:
        assert "The Higgs Boson" in session.get(DirectorDecision, reviewed).outcome
    report = assert_a_report_not_a_letter(engine, "Costul filmelor")
    assert report.body_text == report_words(film_report(engine))
    assert owner_text_problems(report.body_text) == [], report.body_text


def test_a_review_asks_what_its_decision_asked_and_the_prompts_go_to_the_video_editor(
    engine, studio, settings
):
    """2026-10-12, 17:20 UTC: the decision to «review the shot prompts of the two failed
    renders… rewrite the prompt pattern» (63acf8ef, renders_failed) was closed with the cost
    report as its outcome, the prompts were never reviewed, and the same cost letter went to
    the Owner again. Every review was a cost question by its ``review_`` key alone. A review
    asks what the decision it reviews asked: this one is Kael's prompt work, even when her
    model asks the cost report for it, and nobody is written to about a film's cost."""
    from app.agents.command import _repair_spec
    from app.agents.repairs.film_cost import asks_film_cost

    a_published_film(engine, studio["channel_id"])
    kael, nadia = agent_of(engine, "VideoEditor"), agent_of(engine, "Accountant")
    prompts = (
        "Review the shot prompts of the two failed renders against what the film actually "
        "looked like and rewrite the prompt pattern"
    )
    reviewed = an_open_decision(
        engine,
        matter_key="renders_failed",
        action=prompts,
        role="VideoEditor",
        decision="ITERATE",
        review_after_videos=1,
    )
    assert not asks_film_cost("review_renders_failed", prompts)
    review = next(
        m
        for m in findings(engine, settings, _state(engine, settings))
        if m["matter_key"] == "review_renders_failed"
    )
    assert "repair" not in review
    assert review["owner_role"] == "VideoEditor" and review["action"] == prompts[:200]
    assert review["evidence"]["decision_id"] == reviewed
    # Whatever words her choice uses, a review that offers no repair is not the cost report.
    from app.agents.command import Choice

    asked_cost = Choice(
        matter_key="review_renders_failed",
        decision="CONTINUE",
        action="Report what a film cost against what it returned",
        repair_action="film_cost_report",
    )
    assert _repair_spec(review, asked_cost) is None

    model = choosing(
        {
            "matter_key": "review_renders_failed",
            "decision": "CONTINUE",
            "interpretation": "two renders failed",
            "confidence": "MEDIUM",
            "action": "report what a film cost against what it returned",
            "owner_role": "Accountant",
            "repair_action": "film_cost_report",
        }
    )(refusing=set())
    registry = ProviderRegistry()
    registry.register(studio["local_provider"], model)
    result = direct_company(engine, registry, settings)
    assert "review_renders_failed" not in {r["matter_key"] for r in result["repairs"]}
    (assigned,) = [a for a in result["assignments"] if a["matter_key"] == "review_renders_failed"]
    assert assigned["owner_role"] == "VideoEditor" and assigned["action"] == prompts[:200]
    assert not letters_to(engine, nadia.id), "no cost question to the Accountant"
    (handoff,) = letters_to(engine, kael.id)
    assert handoff.intent == "HANDOFF" and "Review the shot prompts" in handoff.body_text

    handlers = build_task_handlers(engine, settings, None, None, registry)
    while work_once(engine, handlers) is not None:
        pass
    assert not any(e.payload["repair"] == "film_cost_report" for e in events(engine, APPLIED_EVENT))
    with Session(engine) as session:
        row = session.get(DirectorDecision, reviewed)
        assert row.state == "OPEN" and "USD" not in str(row.outcome or "")
        (own,) = session.scalars(
            select(DirectorDecision).where(DirectorDecision.matter_key == "review_renders_failed")
        ).all()
        assert own.state == "OPEN" and own.owner_role == "VideoEditor"
    assert owner_letters(engine) == []


def test_a_review_sent_on_as_work_never_becomes_a_letter_to_the_owner(engine, studio, settings):
    """The review of 2026-10-12 tried to break the routing. Until then a review was her cost
    report and never reached the Owner. Sent on as a department's work, it met the rules for
    a department's matter: three decisions under its key went to him as «Decizia ta», and a
    department the studio no longer has did too. A key like ``review_renders_failed`` is
    shared by every review its matter ever had (live on 2026-10-12, review_bottleneck_research
    had two cost reports already), so a matter's third review would have been his letter. A
    review is counted against the decision it reviews, and one with no department is not
    handed on; neither is it his."""
    import json as json_module

    a_published_film(engine, studio["channel_id"])
    kael = agent_of(engine, "VideoEditor")
    # Three earlier reviews of earlier renders_failed decisions, under the same key.
    for _ in range(3):
        earlier = an_open_decision(
            engine,
            matter_key="renders_failed",
            action="review the shot prompts",
            role="VideoEditor",
            state="REVIEWED",
            outcome="făcut",
        )
        done = an_open_decision(
            engine,
            matter_key="review_renders_failed",
            action="review the shot prompts",
            role="VideoEditor",
            state="REVIEWED",
            outcome="făcut",
        )
        with Session(engine) as session, session.begin():
            session.get(DirectorDecision, done).evidence_json = {"decision_id": earlier}
    # 63acf8ef's own words, 226 characters: its last order lay past the 200 a review kept.
    prompts = (
        "Review the shot prompts of the two failed renders against what the film actually "
        "looked like; identify which prompt elements failed and rewrite the prompt pattern for "
        "the next renders. Report which element caused each failure."
    )
    reviewed = an_open_decision(
        engine, matter_key="renders_failed", action=prompts, role="VideoEditor"
    )
    # A decision of a department the studio no longer has, its review due too.
    an_open_decision(
        engine, matter_key="bottleneck_lighting", action="relight the set", role="Gaffer"
    )
    due = {
        m["matter_key"]: m
        for m in findings(engine, settings, _state(engine, settings))
        if m["matter_key"].startswith("review_")
    }
    assert due["review_bottleneck_lighting"]["owner_role"] is None

    class Chooses(Models):
        async def generate(self, model, prompt, **kwargs):
            self.asked.append(prompt)
            choices = [
                {
                    "matter_key": key,
                    "decision": "CONTINUE",
                    "interpretation": "due",
                    "confidence": "MEDIUM",
                    "action": "",
                    "owner_role": "",
                }
                for key in ("review_renders_failed", "review_bottleneck_lighting")
            ]
            return GenerateResult(json_module.dumps({"choices": choices}), 50, 20, None)

    registry = ProviderRegistry()
    registry.register(studio["local_provider"], Chooses(refusing=set()))
    result = direct_company(engine, registry, settings)
    assert result["escalated"] == []
    (assigned,) = result["assignments"]
    assert assigned["matter_key"] == "review_renders_failed"
    assert assigned["owner_role"] == "VideoEditor" and assigned["action"] == prompts
    (handoff,) = letters_to(engine, kael.id)
    assert handoff.intent == "HANDOFF"
    assert "Report which element caused each failure." in handoff.body_text, "the whole work"
    assert owner_letters(engine) == [], "a review is hers: nothing of it is his letter"
    with Session(engine) as session:
        assert session.get(DirectorDecision, reviewed).state == "OPEN"


# ------------------------------------------------------------- 6. decisions whose work is over


def test_decisions_whose_work_is_over_are_closed_with_what_became_of_them(engine, studio, settings):
    handoff = a_handoff(engine, "Publisher", subject="Verifică coada")
    with Session(engine) as session, session.begin():
        from app.agents.messages import resolve_message

        resolve_message(session, handoff, resolution="Coada e goală.", resolved_by="Vera")
    by_letter = an_open_decision(
        engine,
        matter_key="publications_failed",
        action="check",
        role="Publisher",
        message_id=handoff,
        # Nothing to measure after it (the one kind of decision with no review): its letter
        # is its end.
        decision="NEEDS_MORE_DATA",
        review_after_videos=None,
    )
    earlier = (NOW - timedelta(days=2)).isoformat()
    reviewed = an_open_decision(
        engine,
        matter_key="bottleneck_writing",
        action="rewrite",
        role="ScriptWriter",
        created_at=earlier,
    )
    an_open_decision(
        engine,
        matter_key="review_bottleneck_writing",
        action="report what a film cost against what it returned",
        role="Director",
        state="REVIEWED",
        outcome="Trei filme publicate; retenția a crescut.",
        reviewed_at=utc_now(),
    )
    still_open = an_open_decision(
        engine, matter_key="renders_failed", action="review", role="VideoEditor"
    )
    # A repair whose task died with the process.
    task_key = f"director-repair:close_thread:x:{NOW.date()}"
    dead = an_open_decision(engine, matter_key="thread_loops", action="close", role="Director")
    with Session(engine) as session, session.begin():
        session.get(DirectorDecision, dead).evidence_json = {
            "repair": {"name": "close_thread", "fingerprint": "x", "task_key": task_key}
        }
        session.add(
            TaskQueueItem(
                id=str(uuid4()),
                task_type=REPAIR_TASK,
                payload={},
                priority=5,
                status="DEAD_LETTER",
                attempts=1,
                max_attempts=1,
                backoff_seconds=5,
                next_attempt_at=utc_now(),
                idempotency_key=task_key,
                error_detail="INTERRUPTED",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    matter = matter_of(engine, settings, "stale_decisions")
    assert set(matter["repair"]["params"]["decision_ids"]) == {by_letter, reviewed, dead}
    done = run_repair(engine, settings, matter)
    assert done["result"]["status"] == "APPLIED"
    with Session(engine) as session:
        assert "Coada e goală." in session.get(DirectorDecision, by_letter).outcome
        assert "retenția a crescut" in session.get(DirectorDecision, reviewed).outcome
        assert "INTERRUPTED" in session.get(DirectorDecision, dead).outcome
        assert session.get(DirectorDecision, still_open).state == "OPEN"


# ------------------------------------------------------------- 7. estimates with no invoice


def test_old_estimates_are_one_card_per_provider_and_month_never_a_letter_to_nadia(
    engine, studio, settings
):
    nadia = agent_of(engine, "Accountant")
    september, october, fresh = NOW - timedelta(days=40), NOW - timedelta(days=9), NOW
    board = str(uuid4())
    rows = [
        ("runway", september, 720_000, {"storyboard_id": board, "credits": 72.0, "measured": True}),
        ("runway", september, 300_000, {"storyboard_id": board, "credits": 30.0, "measured": True}),
        ("runway", october, 500_000, {"storyboard_id": str(uuid4()), "credits": 50.0}),
        ("runpod", october, 2_980_000, {"storyboard_id": str(uuid4())}),
        ("elevenlabs", fresh, 56_760, {"render_job_id": str(uuid4())}),
    ]
    with Session(engine) as session, session.begin():
        for provider, when, micros, attribution in rows:
            session.add(
                ProviderCostRecord(
                    id=str(uuid4()),
                    provider=provider,
                    external_reference=str(uuid4()),
                    status="ESTIMATED",
                    amount_micros=micros,
                    currency="USD",
                    usd_micros=micros,
                    attribution_json=attribution,
                    recorded_at=when.isoformat(),
                )
            )
        # The stills step measured the account's drop: 102 credits, as estimated.
        append_event(
            session,
            "media.stills_step_finished",
            "storyboard",
            board,
            1,
            {"balance_before": 500.0, "balance_after": 398.0, "credit_usd": 0.01},
            "c",
        )
    matter = matter_of(engine, settings, "unbilled_estimates")
    assert {(g["provider"], g["month"]) for g in matter["evidence"]["groups"]} == {
        ("runway", str(september.date())[:7]),
        ("runway", str(october.date())[:7]),
        ("runpod", str(october.date())[:7]),
    }
    done = run_repair(engine, settings, matter)
    assert done["result"]["status"] == "APPLIED"
    for _ in range(2):  # asked again, the same three cards
        execute_repair(
            engine, None, settings, {"repair": "unbilled_estimates"}, correlation_id=str(uuid4())
        )
    found = cards(engine, "unbilled:")
    assert sorted(c.subject_id for c in found) == sorted(
        {
            f"runway:{str(september.date())[:7]}",
            f"runway:{str(october.date())[:7]}",
            f"runpod:{str(october.date())[:7]}",
        }
    )
    assert len({c.dedupe_key for c in found}) == 3
    september_card = next(c for c in found if c.subject_id == f"runway:{str(september.date())[:7]}")
    # Booked from the balance drop it measured: said as measured, not «compared» with itself.
    assert "102,0 credite sunt scăderi de sold" in september_card.why_ro
    assert "se potrivesc" not in september_card.why_ro and "1,02" in september_card.why_ro
    october_card = next(c for c in found if c.subject_id == f"runway:{str(october.date())[:7]}")
    assert "50,0 credite sunt o estimare planificată" in october_card.why_ro
    applied = events(engine, APPLIED_EVENT)[0]
    check = applied.payload["changed"]["runway_checks"][f"runway:{str(september.date())[:7]}"]
    assert check["measured_credits"] == 102.0 and check["planned_credits"] == 0.0
    assert "agree" not in check
    # Nothing written in the books, and nothing asked of Nadia.
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count()).where(ProviderCostRecord.status == "BILLED")) == 0
        )
        assert (
            session.scalar(
                select(func.count()).where(ProviderCostRecord.reconciled_at.is_not(None))
            )
            == 0
        )
    assert not letters_to(engine, nadia.id)


# ------------------------------------------------------------- 8. the desk itself


def test_the_owners_stop_refuses_every_repair_and_a_queued_one_is_declined(
    engine, studio, settings
):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)
    matter = matter_of(engine, settings, "unpriced_usage")
    queued = submit_repair(
        engine,
        matter=matter,
        spec=matter["repair"],
        decision="ITERATE",
        interpretation="",
        confidence="HIGH",
        correlation_id=str(uuid4()),
        run_id=None,
        published=0,
    )
    assert queued["status"] == "QUEUED"
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    with Session(engine) as session:
        payload = dict(session.get(TaskQueueItem, queued["task_id"]).payload)
    result = execute_repair(engine, None, settings, payload, correlation_id=queued["task_id"])
    assert result["status"] == "DECLINED" and "OPRITĂ" in result["outcome"]
    with Session(engine) as session:
        assert session.scalar(select(AgentRun.cost_vr)) is None
        assert session.get(DirectorDecision, queued["decision_id"]).state == "REVIEWED"
    refused = submit_repair(
        engine,
        matter=matter,
        spec=matter["repair"],
        decision="ITERATE",
        interpretation="",
        confidence="HIGH",
        correlation_id=str(uuid4()),
        run_id=None,
        published=0,
    )
    assert refused["status"] == "REFUSED" and refused["verdict"] == "BLOCKED_STOP"
    # And a repair already done is not done twice by its task run again.
    again = execute_repair(engine, None, settings, payload, correlation_id=queued["task_id"])
    assert again["status"] == "ALREADY_CLOSED"


def test_the_loop_queues_free_repairs_and_the_worker_does_them_with_one_report_each(
    engine, studio, settings
):
    cloud = a_connection(engine, models=("kimi-k3",))
    sarah = agent_of(engine, "Director")
    runs(
        engine,
        sarah.id,
        model="kimi-k3",
        provider=cloud["provider"],
        at=this_month(engine, timedelta(days=3)),
    )
    owner_price(engine)
    registry = ProviderRegistry()
    # Her model answers nothing usable: the measurements decide, the free repair among them.
    registry.register(studio["local_provider"], Models(refusing=set()))
    first = direct_company(engine, registry, settings)
    assert [r["repair"] for r in first["repairs"]] == ["reprice_unpriced_runs"]
    second = direct_company(engine, registry, settings)
    assert second["repairs"] == [], "a matter under its open decision is not queued twice"
    handlers = build_task_handlers(engine, settings, None, None, registry)
    outcomes = []
    while (done := work_once(engine, handlers)) is not None:
        outcomes.append(done)
    assert [o["outcome"]["status"] for o in outcomes] == ["APPLIED"]
    assert len(director_reports(engine)) == 1
    assert owner_letters(engine) == []


def test_an_assignment_by_the_directors_repair_is_not_read_as_the_owners_choice(engine, studio):
    cloud = a_connection(engine, models=("a-model", "b-model"))
    kael = agent_of(engine, "VideoEditor")
    with Session(engine) as session:
        assert owner_home_model(session, kael.id) is None
    assigned = assign_agent(
        engine,
        kael.id,
        cloud["models"]["a-model"],
        kael.version,
        assignment_origin="DIRECTOR_REPAIR",
    )
    with Session(engine) as session:
        agent = session.get(Agent, kael.id)
        # No choice of his behind it: the preference mover may still place her.
        assert _owner_chose_models(session, agent, "VideoEditor") is False
        assert owner_home_model(session, kael.id) is None
    assign_agent(engine, kael.id, cloud["models"]["b-model"], assigned["version"])
    with Session(engine) as session:
        agent = session.get(Agent, kael.id)
        assert _owner_chose_models(session, agent, "VideoEditor") is True
        assert owner_home_model(session, kael.id) == cloud["models"]["b-model"]
    with pytest.raises(ValueError, match="Origine"):
        assign_agent(engine, kael.id, cloud["models"]["a-model"], 99, assignment_origin="AGENT")
