"""Why an employee's runs fail, and a working model for her when hers fails now (2026-10-11).

Sarah read «Nadia: 92,9 % eșecuri» on 2026-10-11 and could only ask Nadia about it. The figure
was a 30-day window: 492 of the 497 failures were one retry storm on 2026-10-04 05:23-07:51,
three letters retried at every worker pass on glm-5.3-flash:cloud @ local-ollama, a model
Nadia had not used since; on mistral-large-4, her model since 10-08, she had failed nothing.
A rate over thirty days says nothing about today.

So two repairs, both on the same `diagnosis`:

- ``diagnose_agent`` groups the employee's runs by status, model and provider, task, error and
  burst, puts the current model's rate over 24 hours and 7 days beside the 30-day one, and
  names a cause: STALE_HISTORY (the failures are behind her), PROVIDER_AUTH (the key is
  refused), MODEL_GONE (the model is not there any more), RATE_LIMIT, EMPTY_OUTPUT (answers
  with no text), SCHEMA (answers in the wrong form) or PROVIDER_ERROR (the provider fails with
  no code, the urllib HTTPError of 10-04). A diagnosis changes nothing; it is the decision's
  outcome and the Owner's letter, with no model asked.
- ``switch_agent_model`` only when her CURRENT model fails now: it is gone, or its last three
  runs since it was last assigned to her failed at the model, the latest within a day; and
  before anything moves, a probe of that model itself fails too. A failure from before the
  Owner (re)chose her model is not evidence against his choice, and three failures of an hour
  say it failed then, not that it fails now. The kernel's ``agent.change_model`` (T2) is asked
  by the desk. The replacement is on a connection the Owner verified (never the seeded
  local-ollama endpoint), available, able to do the role, not on his deny list (no settings
  to read it from, no candidate), not an Anthropic model, and priced on both token sides so
  the switch adds no unpriced usage; a probe run on it answered. She is moved with origin
  DIRECTOR_REPAIR, the slots she had are kept in the event, and the model the Owner chose stays
  her home (`agents.services.owner_home_model`). At most one switch per employee per day: a
  second is his, as one card.

The probes are runs of hers (`PROBE_TEMPLATE`) and are left out of the diagnosis: a failed
probe is not one more failure of her work, nor a new case to probe again.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.repairs import (
    APPLIED,
    DECLINED,
    NOTHING_TO_DO,
    RepairContext,
    finding,
    outcome,
    register_repair,
)
from app.agents.repairs.desk import fingerprint, owner_card
from app.db import lock_for_write
from app.wording import count, decimal, settings_place

#: The window the workforce measure reads (`workforce.services.OBSERVATION_DAYS`) and the
#: thresholds it judges by: fewer runs is an anecdote, half failed is a matter.
OBSERVATION_DAYS = 30
MIN_RUNS = 5
FAILURE_RATE = 0.5
#: The current model fails now when its last this-many runs since it was assigned to her all
#: failed at the model...
FAILING_RUNS = 3
#: ...and the latest of them is this recent; older than that it is history, not now.
FAILING_NOW_HOURS = 24
#: The diagnosis's week, and the record a candidate model is ranked by.
RECENT_DAYS = 7
#: Failures this close together are one burst (the worker passes of a retry storm).
BURST_GAP_SECONDS = 600
BURST_MIN = 5
#: A run that failed at the model: not the budget, the stop or a process that died (not the
#: model's to answer for), nor BLOCKED_PROVIDER, the studio's own cached refusal of a provider
#: whose health check failed, which asked no model and is one provider's state, not hers.
MODEL_FAULTS = ("FAILED", "EMPTY_OUTPUT")
#: What a probe run is recorded under; such runs are not her work and the diagnosis skips them.
PROBE_TEMPLATE = "director-probe-v1"
#: What a probe of her own model may come back as and still say the model is down.
DOWN = (*MODEL_FAULTS, "BLOCKED_PROVIDER", "ValueError")
#: Switches the Director may make for one employee in a day before it is the Owner's.
SWITCHES_PER_DAY = 1
#: How many replacements are probed before she gives up and asks him.
PROBES = 3
PROBE_PROMPT = "Reply with the single word OK."
#: The connection statuses the Owner's «Verifică» leaves (`media.factory.VERIFIED_STATUSES`).
VERIFIED_STATUSES = ("VERIFIED", "ACCESS_VERIFIED")
ORIGIN = "DIRECTOR_REPAIR"
MODEL_CARD = "director_model:"

CAUSE_RO = {
    "STALE_HISTORY": "istoric vechi, nu o defecțiune de azi",
    "PROVIDER_AUTH": "furnizorul refuză cheia conexiunii",
    "MODEL_GONE": "modelul nu mai este disponibil",
    "RATE_LIMIT": "limita de cereri a furnizorului",
    "EMPTY_OUTPUT": "modelul răspunde fără text",
    "SCHEMA": "răspunsurile nu au forma cerută",
    "PROVIDER_ERROR": "furnizorul eșuează fără un cod de eroare",
}


def _when(stamp: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _error_class(detail: str | None) -> str:
    """The error as the run kept it, without the sentence for the Owner after « — »."""
    text = str(detail or "").split(" — ")[0].strip()
    return text[:80] or "—"


def _rate(rows: list[Any]) -> dict[str, Any]:
    failed = sum(1 for row in rows if row.status in MODEL_FAULTS)
    return {
        "runs": len(rows),
        "failed": failed,
        "rate": round(failed / len(rows), 3) if rows else None,
    }


def _bursts(failed: list[Any]) -> list[dict[str, Any]]:
    """Failures grouped where each followed the last within `BURST_GAP_SECONDS`; the three
    largest of at least `BURST_MIN`."""
    groups: list[list[Any]] = []
    previous: datetime | None = None
    for row in failed:
        moment = _when(row.started_at)
        if moment is None:
            continue
        if previous is None or (moment - previous).total_seconds() > BURST_GAP_SECONDS:
            groups.append([])
        groups[-1].append(row)
        previous = moment
    out = [
        {
            "first": group[0].started_at,
            "last": group[-1].started_at,
            "failures": len(group),
            "models": dict(Counter(f"{r.model_name} @ {r.provider_name}" for r in group)),
            "task_types": dict(Counter(r.task_type for r in group)),
            "errors": dict(Counter(_error_class(r.error_detail) for r in group)),
        }
        for group in groups
        if len(group) >= BURST_MIN
    ]
    return sorted(out, key=lambda b: -b["failures"])[:3]


def _class_of(rows: list[Any]) -> str:
    """What a set of failed runs says about the model: the HTTP status the run kept first."""
    details = " ".join(str(row.error_detail or "") for row in rows)
    statuses = {int(code) for code in re.findall(r"HTTP (\d{3})", details)}
    if statuses & {401, 402, 403}:
        return "PROVIDER_AUTH"
    if 404 in statuses or "unavailable" in details.lower():
        return "MODEL_GONE"
    if 429 in statuses:
        return "RATE_LIMIT"
    if rows and all(row.status == "EMPTY_OUTPUT" for row in rows):
        return "EMPTY_OUTPUT"
    if re.search(r"schema|json|validation", details, re.IGNORECASE):
        return "SCHEMA"
    return "PROVIDER_ERROR"


def provider_label(session: Session, provider_name: str | None) -> str:
    """A provider as the Owner named it: a saved connection by its name, else as recorded."""
    from app.agents.models import ProviderRecord  # noqa: PLC0415

    name = str(provider_name or "")
    if name.startswith("settings:"):
        row = session.scalar(select(ProviderRecord).where(ProviderRecord.name == name))
        if row is not None and str(row.notes or "").strip():
            return str(row.notes).strip()
    return name or "—"


def assigned_at(session: Session, agent_id: str) -> datetime | None:
    """When her model was last set (by the Owner, the allocation, the preference mover or a
    repair): her runs before it were on another choice, or on this one before it was made
    again."""
    from app.models import DomainEvent  # noqa: PLC0415

    stamp = session.scalars(
        select(DomainEvent.timestamp)
        .where(
            DomainEvent.aggregate_id == agent_id,
            DomainEvent.event_type.in_(("agent.model_assigned", "agent.model_preferred")),
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    return _when(stamp) if stamp else None


def diagnosis(session: Session, agent: Any, now: datetime | None = None) -> dict[str, Any]:
    """What the employee's last thirty days of runs say, and about which model."""
    from app.agents.models import AgentRun, ModelRecord, ProviderRecord  # noqa: PLC0415

    moment = now or datetime.now(UTC)
    since = (moment - timedelta(days=OBSERVATION_DAYS)).isoformat()
    model = session.get(ModelRecord, agent.model_id)
    provider = session.get(ProviderRecord, agent.provider_id)
    current = {
        "model_id": agent.model_id,
        "model": model.model_name if model else None,
        "provider": provider.name if provider else None,
        "provider_label": provider_label(session, provider.name if provider else None),
        "available": bool(model is not None and model.is_available),
        # Gone: verified once and missing from the provider's list since (`sync_provider_models`
        # marks it so). A seeded model nobody ever verified is not gone; it was never there,
        # and the preflight says so.
        "gone": model is None or (not model.is_available and model.last_verified is not None),
    }
    runs = list(
        session.scalars(
            select(AgentRun)
            .where(
                AgentRun.agent_id == agent.id,
                AgentRun.started_at >= since,
                AgentRun.prompt_template_version != PROBE_TEMPLATE,
            )
            .order_by(AgentRun.started_at)
        )
    )
    failed = [row for row in runs if row.status != "SUCCEEDED"]
    on_current = [
        row
        for row in runs
        if (row.model_name, row.provider_name) == (current["model"], current["provider"])
    ]
    windows = {
        label: _rate(
            [r for r in on_current if r.started_at >= (moment - timedelta(days=days)).isoformat()]
        )
        for label, days in (("24h", 1), ("7d", RECENT_DAYS), ("30d", OBSERVATION_DAYS))
    }
    # Only what her model did since it was set: a failure before the Owner chose it again is
    # no evidence against his choice (review of 2026-10-11).
    chosen = assigned_at(session, agent.id)
    since_chosen = [
        row
        for row in on_current
        if chosen is None or ((started := _when(row.started_at)) is not None and started > chosen)
    ]
    last = since_chosen[-FAILING_RUNS:]
    latest = _when(last[-1].started_at) if last else None
    failing_runs = (
        len(last) >= FAILING_RUNS
        and all(row.status in MODEL_FAULTS for row in last)
        and latest is not None
        and latest >= moment - timedelta(hours=FAILING_NOW_HOURS)
    )
    failing_now = current["gone"] or failing_runs
    recent = [
        row
        for row in on_current
        if row.status in MODEL_FAULTS
        and row.started_at >= (moment - timedelta(days=RECENT_DAYS)).isoformat()
    ]
    week = windows["7d"]
    if current["gone"]:
        cause = "MODEL_GONE"
    elif failing_runs:
        cause = _class_of(last)
    elif week["runs"] >= FAILING_RUNS and (week["rate"] or 0) >= FAILURE_RATE:
        cause = _class_of(recent)
    else:
        cause = "STALE_HISTORY"
    return {
        "agent_id": agent.id,
        "current": current,
        "runs": len(runs),
        "failed": len(failed),
        "failure_rate": round(len(failed) / len(runs), 3) if runs else None,
        "windows": windows,
        "failing_now": failing_now,
        "cause": cause,
        "model_set_at": chosen.isoformat() if chosen else None,
        "last_failure": failed[-1].started_at if failed else None,
        "by_status": dict(Counter(row.status for row in runs)),
        "by_model": dict(Counter(f"{row.model_name} @ {row.provider_name}" for row in runs)),
        "failed_by_model": dict(
            Counter(f"{row.model_name} @ {row.provider_name}" for row in failed)
        ),
        "failed_by_task": dict(Counter(row.task_type for row in failed)),
        "failed_by_error": dict(Counter(_error_class(row.error_detail) for row in failed)),
        "bursts": _bursts(failed),
    }


def _percent(rate: float | None) -> str:
    return f"{decimal(rate * 100, 1)} %" if rate is not None else "—"


def diagnosis_words(session: Session, agent: Any, diag: Mapping[str, Any]) -> str:
    """The diagnosis in a few sentences for the Owner."""
    name = str(agent.display_name)
    sentences = [
        f"{name}: în ultimele {OBSERVATION_DAYS} de zile "
        f"{count(int(diag['failed']), 'rulare nu a reușit', 'rulări nu au reușit')} din "
        f"{int(diag['runs'])} ({_percent(diag['failure_rate'])})."
    ]
    for burst in diag["bursts"][:1]:
        model = max(burst["models"], key=burst["models"].get)
        error = max(burst["errors"], key=burst["errors"].get)
        sentences.append(
            f"{burst['failures']} dintre ele sunt o singură rafală, "
            f"{burst['first'][:16].replace('T', ' ')} – "
            f"{burst['last'][11:16]} UTC, pe {model} ({error})."
        )
    current = diag["current"]
    week, day = diag["windows"]["7d"], diag["windows"]["24h"]
    sentences.append(
        f"Modelul de acum, {current['model']} la {current['provider_label']}"
        + ("" if current["available"] else ", nu mai este disponibil")
        + f": {count(week['failed'], 'eșec', 'eșecuri')} din {week['runs']} în 7 zile, "
        f"{day['failed']} din {day['runs']} în 24 de ore."
    )
    sentences.append(f"Cauza: {CAUSE_RO[str(diag['cause'])]} ({diag['cause']}).")
    return " ".join(sentences)


def _compact(diag: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("current", "runs", "failed", "failure_rate", "windows", "failing_now", "cause")
    return {key: diag[key] for key in keys} | {"bursts": list(diag["bursts"])[:3]}


# ----------------------------------------------------------------------------- detect


def agents_failing(context: RepairContext) -> list[dict[str, Any]]:
    """An employee whose current model fails now (a switch), or whose thirty days read as
    failing while her model of today does not (a diagnosis, said once per case)."""
    from app.agents.models import Agent  # noqa: PLC0415

    found: list[dict[str, Any]] = []
    with Session(context.engine) as session:
        for agent in session.scalars(select(Agent).where(Agent.lifecycle == "ACTIVE")):
            diag = diagnosis(session, agent)
            failing_history = (
                diag["runs"] >= MIN_RUNS and (diag["failure_rate"] or 0) >= FAILURE_RATE
            )
            if not diag["failing_now"] and not failing_history:
                continue
            repair = "switch_agent_model" if diag["failing_now"] else "diagnose_agent"
            found.append(
                finding(
                    f"agent_failing_{agent.id[:8]}",
                    repair,
                    observation=diagnosis_words(session, agent, diag),
                    evidence=_compact(diag),
                    params={"agent_id": agent.id},
                    fingerprint=fingerprint(
                        repair, agent.id, agent.model_id, diag["cause"], diag["last_failure"]
                    ),
                    scope="AGENT",
                    decision="ITERATE" if diag["failing_now"] else "NEEDS_MORE_DATA",
                )
            )
    return found


# ----------------------------------------------------------------------------- diagnose


def _agent(session: Session, params: Mapping[str, Any]) -> Any:
    from app.agents.models import Agent  # noqa: PLC0415

    agent = session.get(Agent, str(params.get("agent_id") or ""))
    return agent if agent is not None and agent.lifecycle == "ACTIVE" else None


def agent_exists(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    with Session(context.engine) as session:
        if _agent(session, params) is None:
            return "Angajatul nu mai este activ în companie; nu am ce diagnostica."
    return None


def diagnose(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    with Session(context.engine) as session:
        agent = _agent(session, params)
        diag = diagnosis(session, agent)
        words = diagnosis_words(session, agent, diag)
        name = str(agent.display_name)
    if diag["failing_now"]:
        words += " Modelul de acum eșuează acum: îl schimb doar ca reparație separată."
    else:
        words += " Nu schimb nimic: modelul de acum lucrează."
    return outcome(
        APPLIED,
        words,
        changed={"diagnosis": _compact(diag)},
        letter_subject_ro=f"Diagnoza rulărilor: {name} — {CAUSE_RO[str(diag['cause'])]}",
    )


# ----------------------------------------------------------------------------- switch


def still_failing(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    with Session(context.engine) as session:
        agent = _agent(session, params)
        if agent is None:
            return "Angajatul nu mai este activ în companie; nu am ce schimba."
        if not diagnosis(session, agent)["failing_now"]:
            return f"Modelul lui {agent.display_name} nu mai eșuează acum; nu l-am schimbat."
    return None


def _switches_today(session: Session, agent_id: str) -> int:
    from app.models import DomainEvent  # noqa: PLC0415

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    return sum(
        1
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "agent.model_assigned",
                DomainEvent.aggregate_id == agent_id,
                DomainEvent.timestamp >= since,
            )
        )
        if (event.payload or {}).get("assignment_origin") == ORIGIN
    )


def _anthropic(model_name: str, kind: str) -> bool:
    """No Anthropic or Claude model works in the product (the Owner's rule)."""
    text = f"{model_name} {kind}".lower()
    return "claude" in text or "anthropic" in text


def _failing_elsewhere(session: Session, model_name: str, provider_name: str) -> bool:
    """Whether the model's own last runs, whoever ran them, all failed at the provider."""
    from app.agents.models import AgentRun  # noqa: PLC0415

    last = list(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.model_name == model_name, AgentRun.provider_name == provider_name)
            .order_by(AgentRun.started_at.desc())
            .limit(FAILING_RUNS)
        )
    )
    return len(last) >= FAILING_RUNS and all(row.status in MODEL_FAULTS for row in last)


def candidates(session: Session, agent: Any, settings: Any, registry: Any) -> list[Any]:
    """The models she could move to, best first; see the module for what each must pass."""
    from app.agents.models import AgentRun, ModelRecord, ProviderRecord, Role  # noqa: PLC0415
    from app.agents.services import (  # noqa: PLC0415
        PolicyKernelError,
        _allocation_entry,
        _check_required_capabilities,
        owner_home_model,
    )
    from app.economy.prices import price_for  # noqa: PLC0415
    from app.integrations.lifecycle import deny_patterns, is_denied  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415

    if registry is None or settings is None:
        # No registry, no probe; no settings, no deny list to keep to: no candidate at all,
        # rather than one the Owner may have barred.
        return []
    deny = deny_patterns(settings)
    home = owner_home_model(session, agent.id)
    role = session.get(Role, agent.role_id)
    entry = _allocation_entry(role.name) if role is not None else None
    seeded = {
        str(entry.get(slot)).split(":")[0]
        for slot in ("primary", "secondary", "tertiary")
        if entry and entry.get(slot)
    }
    week = (datetime.now(UTC) - timedelta(days=RECENT_DAYS)).isoformat()
    ranked: list[tuple[tuple[Any, ...], Any]] = []
    for model, provider in session.execute(
        select(ModelRecord, ProviderRecord)
        .join(ProviderRecord, ProviderRecord.id == ModelRecord.provider_id)
        .where(ModelRecord.is_available.is_(True), ProviderRecord.name.like("settings:%"))
    ).all():
        if model.id == agent.model_id:
            continue
        integration = session.get(Integration, provider.name.removeprefix("settings:"))
        if integration is None or integration.status not in VERIFIED_STATUSES:
            continue
        if registry.get(provider.id) is None:
            continue
        if registry.cached_status(provider.id) not in ("HEALTHY", "UNKNOWN"):
            continue
        kind = str(integration.kind).lower()
        if _anthropic(model.model_name, kind) or is_denied(model.model_name, deny):
            continue
        try:
            _check_required_capabilities(session, agent, model_id=model.id)
        except PolicyKernelError:
            continue
        units = ("per_1m_input_tokens", "per_1m_output_tokens")
        if any(price_for(session, kind, model.model_name, unit) is None for unit in units):
            continue
        if _failing_elsewhere(session, model.model_name, provider.name):
            continue
        proven = sum(
            1
            for _ in session.scalars(
                select(AgentRun.id).where(
                    AgentRun.model_name == model.model_name,
                    AgentRun.provider_name == provider.name,
                    AgentRun.status == "SUCCEEDED",
                    AgentRun.started_at >= week,
                )
            )
        )
        rank = (
            0 if model.id == home else 1,
            0 if model.model_name.split(":")[0] in seeded else 1,
            -proven,
            model.model_name,
        )
        ranked.append((rank, model))
    return [model for _rank, model in sorted(ranked, key=lambda item: item[0])]


def model_card(agent: Any, why_ro: str) -> dict[str, Any]:
    """The Owner's card when the Director cannot (or may not again today) move her."""
    return {
        "kind": "agent_model_failing",
        "dedupe_key": f"{MODEL_CARD}{agent.id}",
        "title_ro": f"Alege un model care lucrează pentru {agent.display_name}",
        "why_ro": why_ro,
        "effect_ro": f"{agent.display_name} lucrează din nou pe un model care răspunde.",
        "subject_type": "agent",
        "subject_id": agent.id,
        "options": [
            {
                "key": "choose",
                "label_ro": "Aleg eu modelul",
                "effect_ro": "Alegi modelul angajatului și salvezi.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place": "agents",
                    "steps_ro": (
                        f"Deschide {agent.display_name}, alege un model disponibil pe o "
                        "conexiune verificată și salvează."
                    ),
                },
            }
        ],
    }


def _ask_owner(context: RepairContext, agent_id: str, why_ro: str) -> str | None:
    from app.agents.models import Agent  # noqa: PLC0415

    with Session(context.engine) as session, session.begin():
        lock_for_write(session)
        agent = session.get(Agent, agent_id)
        return owner_card(session, **model_card(agent, why_ro)) if agent is not None else None


def _probe(
    context: RepairContext, agent_id: str, model_id: str, model_name: str, name: str
) -> dict[str, Any]:
    """One short run of hers on a model (`PROBE_TEMPLATE`): whether it answers now."""
    from app.agents.services import PolicyKernelError, run_agent_task  # noqa: PLC0415

    try:
        run = run_agent_task(
            context.engine,
            context.registry,
            agent_id,
            "TEST_CONNECTIVITY",
            PROBE_PROMPT,
            PROBE_TEMPLATE,
            context.correlation_id,
            max_tokens=64,
            temperature=0.0,
            emit_message=False,
            summary=f"Proba Directoarei: răspunde {model_name} pentru {name}?",
            model_id=model_id,
        )
    except (PolicyKernelError, ValueError) as exc:
        return {"model": model_name, "status": type(exc).__name__, "answered": False}
    answered = run["status"] == "SUCCEEDED" and bool(str(run.get("output_text") or "").strip())
    return {
        "model": model_name,
        "status": run["status"],
        "run_id": run["id"],
        "answered": answered,
        "reason": str(run.get("error_detail") or "")[:200],
    }


def switch_model(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from app.agents.models import Agent, ModelRecord  # noqa: PLC0415
    from app.agents.services import owner_home_model  # noqa: PLC0415
    from app.integrations.services import assign_agent  # noqa: PLC0415

    agent_id = str(params.get("agent_id") or "")
    with Session(context.engine) as session:
        agent = _agent(session, params)
        diag = diagnosis(session, agent)
        name = str(agent.display_name)
        before = {
            "model_id": agent.model_id,
            "model": diag["current"]["model"],
            "provider_id": agent.provider_id,
            "secondary_model_id": agent.secondary_model_id,
            "tertiary_model_id": agent.tertiary_model_id,
            "multi_llm_strategy": agent.multi_llm_strategy,
            "additional_llm_policy": agent.additional_llm_policy,
            "min_importance": agent.min_importance,
            "min_confidence": agent.min_confidence,
        }
        home = owner_home_model(session, agent.id)
        switched = _switches_today(session, agent.id)
        found = (
            []
            if switched >= SWITCHES_PER_DAY
            else candidates(session, agent, context.settings, context.registry)
        )
        options = [(model.id, model.model_name) for model in found[:PROBES]]
    # Her own model first: its failures say it failed, not that it fails at this moment (an
    # hour's outage at the provider). If it answers, there is nothing to repair; if the probe
    # could not run at all (her budget, the stop, a task of hers in flight), no other model's
    # probe would either, and nothing is decided now.
    own = _probe(context, agent_id, str(before["model_id"]), str(before["model"]), name)
    if own["answered"]:
        return outcome(
            NOTHING_TO_DO,
            f"{name}: modelul de acum, {before['model']}, a răspuns la probă; nu l-am schimbat.",
            changed={"probes": [own]},
        )
    if own["status"] not in DOWN:
        return outcome(
            DECLINED,
            f"Nu am putut încerca modelul lui {name} ({own.get('reason') or own['status']}): "
            "nu schimb nimic acum.",
            changed={"probes": [own]},
        )
    failing = (
        f"{name}: modelul de acum, {before['model']}, eșuează acum "
        f"({CAUSE_RO[str(diag['cause'])]})."
    )
    if switched >= SWITCHES_PER_DAY:
        card = _ask_owner(
            context,
            agent_id,
            f"{failing} I-am schimbat deja modelul o dată azi; a doua schimbare în aceeași zi "
            "este a ta.",
        )
        return outcome(
            DECLINED,
            f"{failing} I-am schimbat deja modelul o dată azi, deci nu i-l schimb a doua oară: "
            "ți-am pus întrebarea în Decizii.",
            changed={"card": card, "switches_today": switched, "probes": [own]},
        )
    probes: list[dict[str, Any]] = [own]
    chosen: tuple[str, str] | None = None
    for model_id, model_name in options:
        probe = _probe(context, agent_id, model_id, model_name, name)
        probes.append(probe)
        if probe["answered"]:
            chosen = (model_id, model_name)
            break
    if chosen is None and len(probes) > 1 and all(p["status"] in DOWN for p in probes):
        # Her model and every candidate failed the same way at the same moment: the provider
        # is down, not her model (2026-10-14 21:38Z, HTTP 400 on every model for four minutes:
        # three cards «Aleg eu modelul» reached the Owner, who refused all three — the choice
        # of a model is hers, and an outage is nobody's decision). Nothing changes; the next
        # loop probes again, and a fresh failure of hers raises a fresh case.
        return outcome(
            DECLINED,
            f"{failing} Niciun model de pe o conexiune verificată nu a răspuns la probă: "
            "furnizorul nu răspunde acum pentru niciunul. Nu te întreb; reîncerc la trecerea "
            "următoare.",
            changed={"probes": probes, "provider_down": True},
        )
    if chosen is None:
        why = (
            f"{failing} Niciun model de pe o conexiune verificată, prețuit și potrivit rolului "
            + ("nu a trecut proba." if len(probes) > 1 else "nu este disponibil acum.")
        )
        card = _ask_owner(context, agent_id, why)
        return outcome(
            DECLINED,
            why + " Ți-am pus întrebarea în Decizii.",
            changed={"probes": probes, "card": card},
        )
    with Session(context.engine) as session:
        agent = session.get(Agent, agent_id)
        state, version = (agent.runtime_state, agent.version) if agent else ("GONE", 0)
    if state != "IDLE":
        return outcome(
            DECLINED,
            f"{name} lucrează acum; nu îi schimb modelul în timpul unei sarcini. Proba pe "
            f"{chosen[1]} a reușit; reîncerc la următoarea trecere.",
            changed={"probes": probes, "runtime_state": state},
        )
    try:
        assigned = assign_agent(
            context.engine,
            agent_id,
            chosen[0],
            version,
            secondary_model_id=before["secondary_model_id"],
            tertiary_model_id=before["tertiary_model_id"],
            multi_llm_strategy=before["multi_llm_strategy"],
            additional_llm_policy=before["additional_llm_policy"],
            min_importance=before["min_importance"],
            min_confidence=before["min_confidence"],
            assignment_origin=ORIGIN,
        )
    except ValueError as exc:
        return outcome(
            DECLINED,
            f"Nu am putut trece {name} pe {chosen[1]}: {exc}.",
            changed={"probes": probes},
        )
    with Session(context.engine) as session:
        home_row = session.get(ModelRecord, home) if home else None
        home_name = home_row.model_name if home_row is not None else None
    words = (
        f"{failing} L-am înlocuit cu {chosen[1]}: e pe o conexiune verificată, are preț pe "
        "ambele părți și proba a răspuns."
        + (
            f" Modelul ales de tine, {home_name}, rămâne cel la care {name} se întoarce: îl "
            "poți pune înapoi oricând din Setări → Angajați."
            if home_name
            else ""
        )
    )
    return outcome(
        APPLIED,
        words,
        changed={
            "agent_id": agent_id,
            "from": before,
            "to": {"model_id": chosen[0], "model": chosen[1], "version": assigned["version"]},
            "probes": probes,
            "home_model_id": home,
            "revert": {
                key: before[key]
                for key in (
                    "model_id",
                    "secondary_model_id",
                    "tertiary_model_id",
                    "multi_llm_strategy",
                )
            },
        },
        letter_subject_ro=f"Am trecut {name} pe {chosen[1]}",
    )


register_repair(
    "diagnose_agent",
    diagnose,
    tier="T0",
    action="analytics.read",
    precondition=agent_exists,
    detector=agents_failing,
    summary=(
        "group an employee's failed runs by model, provider, task, error and burst, and say "
        "whether her current model fails now or the rate is old history"
    ),
    place_ro=settings_place("agents"),
)

register_repair(
    "switch_agent_model",
    switch_model,
    tier="T2",
    action="agent.change_model",
    precondition=still_failing,
    summary=(
        "move an employee whose current model fails now to a verified, priced model that "
        "passed a probe run, keeping the Owner's model as her home"
    ),
    place_ro=settings_place("agents"),
)


__all__ = ["CAUSE_RO", "agents_failing", "candidates", "diagnosis", "diagnosis_words"]
