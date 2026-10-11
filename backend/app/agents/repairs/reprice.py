"""Agent runs stored without a cost, priced at the price active now (2026-10-11).

A run's cost is computed once, when the model answers (`economy.prices.llm_cost_vr`, called
by the adapter). The Owner typed the Ollama price (0.50/0.50 USD per million tokens) on
2026-10-05 at 13:46; the 167 runs of 10-03..05 before it stayed `cost_vr` NULL for good, and
every daily close since sent Nadia a question about «unpriced usage» she could not answer:
the price existed, nothing applied it. This repair applies it.

What it may do, and what it may not. It APPLIES a price that is active now, with the same
arithmetic the adapters use, to SUCCEEDED runs that still have no cost and both token counts;
each run keeps a stamp of the price it was given (`context_json.priced_after`) and one event,
``economy.agent_runs_repriced``, carries the count and the sum. It never writes a price:
`set_price` is the Owner's command. A model no active price covers stays unpriced and becomes
one card per provider kind, pointing at «Autonomie → Prețurile modelelor»; the card is
withdrawn here once his price covers those runs. And it refuses when the runs it would price
fall in an active budget period that this would push over its limit: an EXCEEDED budget stops
every employee (`economy.accountant.may_run_agent`), a decision that is his, not a side effect
of book-keeping: it is put to him as one card. A repriced run keeps the moment it was priced
(`priced_after.at`), so the day's replay (`economy.as_of`) still shows it unpriced before then.

Which runs: those of the books' current month (`budget_status()["month"]["since"]`), the
period whose unpriced usage the daily close reports, unless ``since``/``until`` name another
window. On the studio's copy of 2026-10-11 that is the 167 runs of 10-03..05; the 451 of
September ran before any Ollama price existed, and a price typed in October is no evidence of
what his plan cost then (`economy.prices`: a guess in the books is worse than a gap). They are
counted in the evidence and left as they are.
"""

from __future__ import annotations

from collections import defaultdict
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
from app.agents.repairs.desk import (
    fingerprint,
    open_card_keys,
    owner_card,
    usd_ro,
    withdraw_card,
)
from app.db import lock_for_write
from app.wording import count

TOKEN_UNITS = ("per_1m_input_tokens", "per_1m_output_tokens")
#: One card per provider kind whose runs no active price covers.
PRICE_CARD = "director_price:"
#: One card per budget period that pricing the runs would push over its limit.
BUDGET_CARD = "director_reprice_budget:"
PRICES_PLACE_RO = "Autonomie → Prețurile modelelor"
#: Who stamps a run's late price.
STAMPED_BY = "director"
#: Runs no price covers become the Owner's question only once the oldest of them is this old:
#: on 2026-10-05 he typed the Ollama price two hours after the first runs it would have
#: covered, and a card about runs made minutes ago would be asking what he is already doing.
#: The preflight's price check names them from the first run.
UNCOVERED_GRACE_HOURS = 24


def provider_kinds(session: Session) -> dict[str, str]:
    """Provider name as a run records it -> the kind the price table is keyed by.

    ``settings:<integration id>`` is a connection the Owner saved: its Integration's kind. The
    seeded ``local-ollama`` (and any other) is its ProviderRecord's type, lower-cased, exactly
    as the preflight's price check reads it (`runbook.preflight._price_check`).
    """
    from app.agents.models import ProviderRecord  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415

    kinds: dict[str, str] = {}
    for provider in session.scalars(select(ProviderRecord)):
        kind = str(provider.provider_type or "").lower()
        if provider.name.startswith("settings:"):
            integration = session.get(Integration, provider.name.removeprefix("settings:"))
            if integration is not None:
                kind = str(integration.kind).lower()
        if kind:
            kinds[provider.name] = kind
    return kinds


def month_start(engine: Any) -> str:
    """When the books' current month opened (UTC ISO), as the budget reads it."""
    from app.economy.budget import budget_status  # noqa: PLC0415

    return str(budget_status(engine)["month"]["since"])


def window(context: RepairContext, params: Mapping[str, Any]) -> tuple[str, str | None]:
    """The runs a repair looks at: ``since``/``until`` from its params, else this month."""
    since = str(params.get("since") or "") or month_start(context.engine)
    until = str(params.get("until") or "") or None
    return since, until


def _unpriced(session: Session, since: str, until: str | None = None) -> list[Any]:
    from app.agents.models import AgentRun  # noqa: PLC0415

    query = select(AgentRun).where(
        AgentRun.status == "SUCCEEDED",
        AgentRun.cost_vr.is_(None),
        AgentRun.prompt_tokens.is_not(None),
        AgentRun.completion_tokens.is_not(None),
        AgentRun.started_at >= since,
    )
    if until is not None:
        query = query.where(AgentRun.started_at < until)
    return list(session.scalars(query.order_by(AgentRun.started_at)))


def _older(session: Session, since: str) -> int:
    """Unpriced runs from before the window: history, counted and left as it is."""
    from app.agents.models import AgentRun  # noqa: PLC0415

    return len(
        session.scalars(
            select(AgentRun.id).where(
                AgentRun.status == "SUCCEEDED",
                AgentRun.cost_vr.is_(None),
                AgentRun.prompt_tokens.is_not(None),
                AgentRun.completion_tokens.is_not(None),
                AgentRun.started_at < since,
            )
        ).all()
    )


def _prices(session: Session, kind: str, model: str) -> tuple[Any, Any] | None:
    """The active input and output price rows that cover this model, or None when a side is
    missing (half a price would understate the run, as `llm_cost_vr` says)."""
    from app.economy.prices import price_row  # noqa: PLC0415

    rows = [price_row(session, kind, model, unit) for unit in TOKEN_UNITS]
    if rows[0] is None or rows[1] is None:
        return None
    return rows[0], rows[1]


def _cost(prices: tuple[Any, Any], model: str, run: Any) -> str | None:
    """The run's cost with the adapters' own arithmetic."""
    from app.economy.prices import llm_cost_vr  # noqa: PLC0415

    by_unit = {TOKEN_UNITS[0]: int(prices[0].usd_micros), TOKEN_UNITS[1]: int(prices[1].usd_micros)}
    return llm_cost_vr(
        lambda _resource, unit: by_unit.get(unit),
        model,
        run.prompt_tokens,
        run.completion_tokens,
    )


def _survey(session: Session, since: str) -> list[dict[str, Any]]:
    """The window's unpriced runs grouped by provider kind and model, each group with what the
    price active now would make of it."""
    from app.economy.services import to_micros  # noqa: PLC0415

    kinds = provider_kinds(session)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for run in _unpriced(session, since):
        kind = kinds.get(run.provider_name, "")
        group = groups.get((kind, run.model_name))
        if group is None:
            group = groups[(kind, run.model_name)] = {
                "provider_kind": kind or None,
                "model": run.model_name,
                "runs": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "first": run.started_at,
                "last": run.started_at,
                "prices": _prices(session, kind, run.model_name) if kind else None,
                "usd_micros": 0,
            }
        group["runs"] += 1
        group["prompt_tokens"] += int(run.prompt_tokens or 0)
        group["completion_tokens"] += int(run.completion_tokens or 0)
        group["last"] = run.started_at
        cost = _cost(group["prices"], run.model_name, run) if group["prices"] else None
        group["usd_micros"] += to_micros(cost) if cost else 0
    for group in groups.values():
        group["covered"] = group.pop("prices") is not None
    return sorted(groups.values(), key=lambda g: (str(g["provider_kind"]), g["model"]))


# ----------------------------------------------------------------------------- detect


def unpriced_usage(context: RepairContext) -> list[dict[str, Any]]:
    """One matter while agent runs have no cost that a price covers now, or, a day on, that
    no price covers and whose kind has no card in front of the Owner yet."""
    grace = (datetime.now(UTC) - timedelta(hours=UNCOVERED_GRACE_HOURS)).isoformat()
    since = month_start(context.engine)
    with Session(context.engine) as session:
        groups = _survey(session, since)
        older = _older(session, since)
        asked = open_card_keys(session, PRICE_CARD)
    actionable = [
        g
        for g in groups
        if g["covered"]
        or (
            g["provider_kind"]
            and f"{PRICE_CARD}{g['provider_kind']}" not in asked
            and str(g["first"]) <= grace
        )
    ]
    if not actionable:
        return []
    runs = sum(g["runs"] for g in actionable)
    covered = [g for g in actionable if g["covered"]]
    uncovered = [g for g in actionable if not g["covered"]]
    sentences = [
        f"{count(runs, 'rulare a angajaților este', 'rulări ale angajaților sunt')} fără cost "
        f"({sum(g['prompt_tokens'] for g in actionable)} tokeni la intrare, "
        f"{sum(g['completion_tokens'] for g in actionable)} la ieșire): costul se calculează o "
        "singură dată, când răspunde modelul."
    ]
    if covered:
        sentences.append(
            "Prețul activ acum acoperă "
            f"{count(sum(g['runs'] for g in covered), 'rulare', 'rulări')}: "
            f"{usd_ro(sum(g['usd_micros'] for g in covered))} USD."
        )
    if uncovered:
        sentences.append(
            "Niciun preț activ pentru "
            + ", ".join(f"{g['model']} ({g['provider_kind']})" for g in uncovered)
            + ": prețul este al Proprietarului."
        )
    if older:
        sentences.append(
            f"Alte {count(older, 'rulare', 'rulări')} din lunile trecute "
            f"{'rămâne' if older == 1 else 'rămân'} fără cost: prețul de acum nu spune ce "
            "costau atunci."
        )
    return [
        finding(
            "unpriced_usage",
            "reprice_unpriced_runs",
            observation=" ".join(sentences),
            params={"since": since},
            evidence={
                "runs": runs,
                "since": since,
                "older_runs": older,
                "by_model": [
                    {
                        k: g[k]
                        for k in ("provider_kind", "model", "runs", "first", "last", "covered")
                    }
                    for g in actionable
                ],
            },
            fingerprint=fingerprint(
                [(g["provider_kind"], g["model"], g["runs"], g["last"]) for g in actionable]
            ),
            scope="AGENT",
        )
    ]


def still_unpriced(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    since, until = window(context, params)
    with Session(context.engine) as session:
        if _unpriced(session, since, until):
            return None
    return "Nicio rulare a angajaților nu mai este fără cost: nu am avut ce să prețuiesc."


# ----------------------------------------------------------------------------- apply


def apply_active_price(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from app.economy.budget import PERIOD_RO, budget_status  # noqa: PLC0415
    from app.economy.services import format_micros, to_micros  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    # Read before the write lock: `budget_status` opens its own session.
    since, until = window(context, params)
    periods = [p for p in budget_status(context.engine)["budgets"] if p["state"] != "EXCEEDED"]
    grace = (datetime.now(UTC) - timedelta(hours=UNCOVERED_GRACE_HOURS)).isoformat()
    with Session(context.engine) as session, session.begin():
        lock_for_write(session)
        kinds = provider_kinds(session)
        priced: list[tuple[Any, str, tuple[Any, Any]]] = []
        uncovered: dict[str, dict[str, Any]] = {}
        unknown = 0
        for run in _unpriced(session, since, until):
            kind = kinds.get(run.provider_name)
            if not kind:
                unknown += 1
                continue
            prices = _prices(session, kind, run.model_name)
            cost = _cost(prices, run.model_name, run) if prices else None
            if prices is None or cost is None:
                entry = uncovered.setdefault(
                    kind, {"models": set(), "runs": 0, "first": run.started_at}
                )
                entry["models"].add(run.model_name)
                entry["runs"] += 1
                continue
            priced.append((run, cost, prices))
        # An active period this would push over its limit: refused, nothing written but his
        # one card, since only he can raise a budget (the desk offers the case again a day on,
        # and finds the card still open).
        for period in periods:
            added = sum(
                to_micros(cost) for run, cost, _ in priced if run.started_at >= period["since"]
            )
            committed = int(period["spent_usd_micros"]) + int(period["reserved_usd_micros"])
            if added and committed + added > int(period["limit_usd_micros"]):
                refusal = (
                    f"Nu am prețuit rulările: costul lor ({usd_ro(added)} USD) ar trece "
                    f"bugetul {PERIOD_RO.get(str(period['period']), '')} de "
                    f"{usd_ro(int(period['limit_usd_micros']))} USD peste "
                    "limită, iar un buget depășit oprește toți angajații. Asta este decizia "
                    "Proprietarului, nu o urmare a unei corecturi în cărți."
                )
                card = owner_card(
                    session, **budget_card(str(period["period"]), len(priced), added, refusal)
                )
                return outcome(
                    DECLINED,
                    refusal + (" Ți-am pus întrebarea în Decizii." if card else ""),
                    changed={
                        "refused_by_budget": period["period"],
                        "would_add_usd": format_micros(added),
                        "card": card,
                    },
                )
        now = utc_now()
        by_model: dict[str, dict[str, Any]] = defaultdict(lambda: {"runs": 0, "usd_micros": 0})
        total = 0
        for run, cost, (price_in, price_out) in priced:
            run.cost_vr = cost
            run.context_json = {
                **(run.context_json if isinstance(run.context_json, dict) else {}),
                "priced_after": {
                    "price_ids": [price_in.id, price_out.id],
                    "versions": [price_in.version, price_out.version],
                    "provenance": [price_in.provenance, price_out.provenance],
                    "at": now,
                    "by": STAMPED_BY,
                    "correlation_id": context.correlation_id,
                },
            }
            micros = to_micros(cost)
            total += micros
            by_model[run.model_name]["runs"] += 1
            by_model[run.model_name]["usd_micros"] += micros
        if priced:
            append_event(
                session,
                "economy.agent_runs_repriced",
                "agent_run",
                context.correlation_id,
                1,
                {
                    "count": len(priced),
                    "usd": format_micros(total),
                    "usd_micros": total,
                    "by_model": {
                        model: {"runs": v["runs"], "usd": format_micros(v["usd_micros"])}
                        for model, v in sorted(by_model.items())
                    },
                    "by": STAMPED_BY,
                    "decision_id": context.decision_id,
                },
                context.correlation_id,
            )
        cards: list[str] = []
        for kind, entry in sorted(uncovered.items()):
            # The detector's grace, here too: runs this fresh may be priced by him already.
            if str(entry["first"]) > grace:
                continue
            card = owner_card(session, **price_card(kind, sorted(entry["models"]), entry["runs"]))
            if card is not None:
                cards.append(card)
        # A kind whose runs are all priced now needs no question any more.
        for key in open_card_keys(session, PRICE_CARD):
            if key.removeprefix(PRICE_CARD) not in uncovered:
                withdraw_card(session, key, "Prețul activ acoperă acum rulările acestui furnizor.")
    if not priced and not cards:
        return outcome(
            NOTHING_TO_DO,
            "Nicio rulare fără cost nu are încă un preț activ, iar întrebarea despre preț este "
            "deja în fața Proprietarului.",
            changed={"uncovered": {k: v["runs"] for k, v in uncovered.items()}, "unknown": unknown},
        )
    words = []
    if priced:
        words.append(
            f"Am aplicat prețul activ acum la {count(len(priced), 'rulare', 'rulări')} fără cost "
            f"ale angajaților: {usd_ro(total)} USD în total ("
            + ", ".join(
                f"{model}: {count(v['runs'], 'rulare', 'rulări')}, {usd_ro(v['usd_micros'])} USD"
                for model, v in sorted(by_model.items())
            )
            + "). Fiecare rulare păstrează prețul cu care a fost socotită; niciun preț nu a fost "
            "scris sau schimbat."
        )
    if uncovered:
        words.append(
            "Fără preț activ rămân "
            + ", ".join(
                f"{count(v['runs'], 'rulare', 'rulări')} la {k} ({', '.join(sorted(v['models']))})"
                for k, v in sorted(uncovered.items())
            )
            + f": prețul este al tău, în {PRICES_PLACE_RO}."
        )
    return outcome(
        APPLIED,
        " ".join(words),
        changed={
            "runs_priced": len(priced),
            "usd": format_micros(total),
            "by_model": {m: v["runs"] for m, v in sorted(by_model.items())},
            "uncovered": {k: v["runs"] for k, v in sorted(uncovered.items())},
            "cards": cards,
        },
        letter_subject_ro=(
            f"Am prețuit {count(len(priced), 'rulare fără cost', 'rulări fără cost')}"
            if priced
            else "Rulări fără preț: întrebarea este la tine"
        ),
    )


def price_card(kind: str, models: list[str], runs: int) -> dict[str, Any]:
    """The Owner's card for a provider kind whose runs no active price covers."""
    return {
        "kind": "agent_model_price",
        "dedupe_key": f"{PRICE_CARD}{kind}",
        "title_ro": f"Pune prețul modelelor de la {kind}",
        "why_ro": (
            f"{count(runs, 'rulare a angajaților', 'rulări ale angajaților')} pe "
            f"{', '.join(models)} ({kind}) nu au niciun preț activ, așa că bugetul nu le vede "
            "costul. Prețul este al tău: studioul nu îl inventează și nu îl scrie."
        ),
        "effect_ro": (
            "Directoarea aplică prețul tău rulărilor rămase fără cost, iar bugetul vede ce au "
            "costat."
        ),
        "subject_type": "provider_kind",
        "subject_id": kind,
        "options": [
            {
                "key": "price",
                "label_ro": "Pun prețul",
                "effect_ro": "Prețul pe milionul de tokeni, la intrare și la ieșire.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": PRICES_PLACE_RO,
                    "steps_ro": (
                        f"Pune prețul la «{kind}», pentru «*» sau pentru fiecare model "
                        f"({', '.join(models)}), pe ambele părți: intrare și ieșire."
                    ),
                },
            }
        ],
    }


def budget_card(period: str, runs: int, usd_micros: int, why_ro: str) -> dict[str, Any]:
    """The Owner's card when pricing the runs would push a budget over its limit: raising
    it, or leaving the runs without a cost, is his decision; she writes no budget."""
    from app.services import BUDGET_PLACE_WORDS  # noqa: PLC0415

    return {
        "kind": "agent_runs_over_budget",
        "dedupe_key": f"{BUDGET_CARD}{period}",
        "title_ro": "Rulările fără cost ar trece bugetul",
        "why_ro": why_ro,
        "effect_ro": (
            f"Cu bugetul mărit, Directoarea aplică prețul celor "
            f"{count(runs, 'rulare', 'rulări')} ({usd_ro(usd_micros)} USD) la următoarea "
            "trecere; fără, rămân fără cost."
        ),
        "subject_type": "budget_period",
        "subject_id": period,
        "options": [
            {
                "key": "budget",
                "label_ro": "Mă uit la buget",
                "effect_ro": "Hotărăști tu limita bugetului.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": BUDGET_PLACE_WORDS,
                    "steps_ro": f"Deschide {BUDGET_PLACE_WORDS} și hotărăște limita.",
                },
            },
            {
                "key": "keep",
                "label_ro": "Las rulările fără cost",
                "effect_ro": "Bugetul rămâne cum este; rulările rămân fără cost.",
                "recommended": False,
                "apply": {"type": "none", "result_ro": "Bugetul rămâne cum este."},
            },
        ],
    }


register_repair(
    "reprice_unpriced_runs",
    apply_active_price,
    tier="T1",
    action="economy.apply_active_price",
    precondition=still_unpriced,
    detector=unpriced_usage,
    summary=(
        "apply the price that is active now to agent runs stored without a cost; a model no "
        "price covers becomes one card for the Owner"
    ),
)
