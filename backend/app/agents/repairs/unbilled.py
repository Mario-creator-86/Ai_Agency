"""Provider costs still estimated weeks later: the Owner's invoice, asked once (2026-10-11).

A cost the studio books itself is ESTIMATED (a measured Runway balance drop, RunPod GPU
seconds at the hourly rate, narration at the documented price) and never posted; only a
vendor's invoice makes it BILLED, through the reconciliation in the Treasury, and only the
Owner sees that invoice: no adapter returns a billed amount, and every write of the books is
his (`economy.router`). On 2026-10-11 all 47 cost rows were ESTIMATED, the oldest from 09-12,
and the Accountant's contract told Nadia to investigate an estimate that stays unbilled for
weeks, which she could only do by asking.

So the Director does what the books allow her: she groups the estimates older than a week by
provider and month, says how much of Runway's is a balance drop its paid steps measured and
how much a planned figure no balance reading stands behind (a prepaid account has no
per-render invoice; the drop is the best evidence there is), and puts ONE card per provider,
month and set of estimates in front of the Owner: the period, the sum, where to enter the
invoice, or that the account is prepaid and nothing will come. A card he answered is not asked
again for the same estimates (its key names them); estimates added to or reconciled out of
the month are a new question, and the open card for the old set is withdrawn. She never
posts, bills or reconciles anything, and never writes to Nadia about it.
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
    NOTHING_TO_DO,
    RepairContext,
    finding,
    outcome,
    register_repair,
)
from app.agents.repairs.desk import (
    fingerprint,
    open_card_keys,
    owner_card_once,
    usd_ro,
    withdraw_card,
)
from app.db import lock_for_write
from app.wording import count, decimal

#: An estimate this old with no invoice behind it is worth asking about.
UNBILLED_AFTER_DAYS = 7
INVOICE_CARD = "unbilled:"
TREASURY_PLACE_RO = "Trezorerie → Reconcilierea facturilor"
VENDOR_RO = {"runway": "Runway", "runpod": "RunPod", "elevenlabs": "ElevenLabs"}


def _vendor(provider: str) -> str:
    return VENDOR_RO.get(str(provider).lower(), str(provider))


def _open_estimates(session: Session, older_than: str | None) -> dict[tuple[str, str], list[Any]]:
    """ESTIMATED rows no invoice has replaced, by (provider, month of recording)."""
    from app.economy.models import ProviderCostRecord  # noqa: PLC0415

    query = select(ProviderCostRecord).where(
        ProviderCostRecord.status == "ESTIMATED", ProviderCostRecord.reconciled_at.is_(None)
    )
    if older_than is not None:
        query = query.where(ProviderCostRecord.recorded_at < older_than)
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in session.scalars(query.order_by(ProviderCostRecord.recorded_at)):
        groups[(str(row.provider), str(row.recorded_at)[:7])].append(row)
    return dict(groups)


def _cutoff() -> str:
    return (datetime.now(UTC) - timedelta(days=UNBILLED_AFTER_DAYS)).isoformat()


def rows_fingerprint(rows: list[Any]) -> str:
    """The estimates a card asks about: the same rows, the same question."""
    return fingerprint(sorted(str(row.id) for row in rows))[:12]


def card_key(provider: str, month: str, rows: list[Any]) -> str:
    return f"{INVOICE_CARD}{provider}:{month}:{rows_fingerprint(rows)}"


def _card_case(key: str) -> tuple[str, str, str]:
    """(provider, month, rows) of a card's key; rows empty for a key without them."""
    parts = key.removeprefix(INVOICE_CARD).split(":")
    return (parts[0], parts[1], parts[2]) if len(parts) >= 3 else (parts[0], parts[-1], "")


def _asked(session: Session, keys: set[str]) -> set[str]:
    """The keys that have had a card, open or answered: each asks about its rows once."""
    from app.decisions.models import OwnerDecision  # noqa: PLC0415

    if not keys:
        return set()
    return set(
        session.scalars(select(OwnerDecision.dedupe_key).where(OwnerDecision.dedupe_key.in_(keys)))
    )


# ----------------------------------------------------------------------------- detect


def unbilled_estimates(context: RepairContext) -> list[dict[str, Any]]:
    with Session(context.engine) as session:
        groups = _open_estimates(session, _cutoff())
        asked = _asked(session, {card_key(p, m, rows) for (p, m), rows in groups.items()})
    waiting = {key: rows for key, rows in groups.items() if card_key(*key, rows) not in asked}
    if not waiting:
        return []
    summary: list[dict[str, Any]] = [
        {
            "provider": provider,
            "month": month,
            "rows": len(rows),
            "usd_micros": sum(int(r.usd_micros) for r in rows),
            "case": rows_fingerprint(rows),
        }
        for (provider, month), rows in sorted(waiting.items())
    ]
    return [
        finding(
            "unbilled_estimates",
            "unbilled_estimates",
            observation=(
                f"{count(sum(s['rows'] for s in summary), 'cost estimat', 'costuri estimate')} "
                f"mai vechi de {UNBILLED_AFTER_DAYS} zile nu au nicio factură: "
                + ", ".join(
                    f"{_vendor(s['provider'])} {s['month']}: {usd_ro(s['usd_micros'])} USD"
                    for s in summary
                )
                + ". Factura o vede doar Proprietarul."
            ),
            evidence={"groups": summary},
            params={"groups": [{"provider": s["provider"], "month": s["month"]} for s in summary]},
            fingerprint=fingerprint([(s["provider"], s["month"], s["case"]) for s in summary]),
            scope="COMPANY",
            confidence="HIGH",
        )
    ]


# ----------------------------------------------------------------------------- apply


def _runway_check(context: RepairContext, rows: list[Any]) -> dict[str, Any]:
    """How much of Runway's estimates is a measured balance drop and how much a plan.

    `media.shooting_sheet.book_purchase` books a step that read the balance with the drop it
    measured (``measured`` true): comparing it with that same drop (`film_step_spend`) agrees
    by construction, so it proves nothing and no verdict is given. A planned figure has no
    reading behind it to compare with. What the Owner can use is the split, with the drops
    the films' steps measured beside it.
    """
    from app.media.assembler import film_step_spend  # noqa: PLC0415

    measured: dict[str, float] = defaultdict(float)
    planned: dict[str, float] = defaultdict(float)
    unnamed = 0
    for row in rows:
        attribution = row.attribution_json if isinstance(row.attribution_json, dict) else {}
        board = attribution.get("storyboard_id")
        credits = attribution.get("credits")
        if not board or not isinstance(credits, int | float) or isinstance(credits, bool):
            unnamed += 1
            continue
        side = measured if attribution.get("measured") is True else planned
        side[str(board)] += float(credits)
    boards = sorted(set(measured) | set(planned))
    drops = {
        board: sum(
            float(item.get("spent") or 0)
            for item in film_step_spend(context.engine, board).values()
        )
        for board in boards
    }
    return {
        "films": [
            {
                "storyboard_id": board,
                "measured_credits": round(measured.get(board, 0.0), 4),
                "planned_credits": round(planned.get(board, 0.0), 4),
                "balance_drop_credits": round(drops[board], 4),
            }
            for board in boards
        ],
        "measured_credits": round(sum(measured.values()), 4),
        "planned_credits": round(sum(planned.values()), 4),
        "balance_drop_credits": round(sum(drops.values()), 4),
        "unnamed_rows": unnamed,
    }


def _runway_words(check: Mapping[str, Any]) -> str:
    if not check["films"]:
        return " Estimările nu numesc filmul și creditele, așa că nu știu cât din ele s-a măsurat."
    words = (
        f" Din ele, {decimal(check['measured_credits'], 1)} credite sunt scăderi de sold "
        "măsurate la pașii plătiți"
    )
    if check["planned_credits"]:
        words += (
            f", iar {decimal(check['planned_credits'], 1)} credite sunt o estimare "
            "planificată, fără o citire a soldului în spate"
        )
    return words + "."


def invoice_card(
    provider: str, month: str, rows: list[Any], usd_micros: int, note: str
) -> dict[str, Any]:
    vendor = _vendor(provider)
    return {
        "kind": "provider_invoice_missing",
        "dedupe_key": card_key(provider, month, rows),
        "title_ro": f"Introdu factura {vendor} pentru {month}",
        "why_ro": (
            f"{count(len(rows), 'cost estimat', 'costuri estimate')} {vendor} din {month}, "
            f"{usd_ro(usd_micros)} USD, nu au încă o factură în cărți. Doar tu vezi factura "
            "furnizorului; până atunci cheltuiala rămâne o estimare." + note
        ),
        "effect_ro": "Cărțile țin suma facturată, iar estimările acoperite se închid.",
        "subject_type": "provider_month",
        "subject_id": f"{provider}:{month}",
        "options": [
            {
                "key": "invoice",
                "label_ro": "Introduc factura",
                "effect_ro": "Factura sau reconcilierea perioadei, în Trezorerie.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": TREASURY_PLACE_RO,
                    "steps_ro": (
                        f"Introdu factura {vendor} sau reconcilierea pentru {month} "
                        f"({usd_ro(usd_micros)} USD estimați)."
                    ),
                },
            },
            {
                "key": "prepaid",
                "label_ro": "Cont preplătit: nu vine factură",
                "effect_ro": (
                    "Estimările rămân cifra studioului; nu se mai întreabă de aceste costuri."
                ),
                "recommended": False,
                "apply": {
                    "type": "none",
                    "result_ro": (
                        f"Contul {vendor} este preplătit: estimările din {month} rămân cifra "
                        "cărților."
                    ),
                },
            },
        ],
    }


def still_unbilled(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    wanted = {(str(g.get("provider")), str(g.get("month"))) for g in params.get("groups") or []}
    with Session(context.engine) as session:
        groups = _open_estimates(session, _cutoff())
    if not groups:
        return "Nicio estimare veche nu mai așteaptă o factură."
    if wanted and not wanted & set(groups):
        return "Estimările acestor luni au fost reconciliate între timp."
    return None


def ask_for_invoices(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    wanted = {(str(g.get("provider")), str(g.get("month"))) for g in params.get("groups") or []}
    with Session(context.engine) as session:
        groups = _open_estimates(session, _cutoff())
        everything = _open_estimates(session, None)
        rows_of = {key: rows for key, rows in groups.items() if not wanted or key in wanted}
        current = {card_key(p, m, rows) for (p, m), rows in groups.items()}
    checks = {
        key: _runway_check(context, rows)
        for key, rows in rows_of.items()
        if key[0].lower() == "runway"
    }
    cards: dict[str, str | None] = {}
    with Session(context.engine) as session, session.begin():
        lock_for_write(session)
        for (provider, month), rows in sorted(rows_of.items()):
            check = checks.get((provider, month))
            # Once per set of estimates: a card he answered («introduc factura» and done, or
            # «cont preplătit») is not put back in front of him for the same rows.
            cards[card_key(provider, month, rows)] = owner_card_once(
                session,
                quiet_days=None,
                **invoice_card(
                    provider,
                    month,
                    rows,
                    sum(int(r.usd_micros) for r in rows),
                    _runway_words(check) if check is not None else "",
                ),
            )
        # A month whose estimates were all reconciled meanwhile needs no question any more,
        # and a card about a set of estimates that has since changed is the new card's.
        for key in open_card_keys(session, INVOICE_CARD):
            provider, month, _rows = _card_case(key)
            if (provider, month) not in everything:
                withdraw_card(session, key, "Estimările lunii au fost reconciliate.")
            elif (provider, month) in groups and key not in current:
                withdraw_card(session, key, "Estimările lunii s-au schimbat; cardul nou le ține.")
    if not rows_of:
        return outcome(NOTHING_TO_DO, "Nicio estimare veche nu mai așteaptă o factură.")
    shown = {
        (p, m): r for (p, m), r in sorted(rows_of.items()) if cards[card_key(p, m, r)] is not None
    }
    if not shown:
        return outcome(
            NOTHING_TO_DO,
            "Fiecare estimare veche are deja cardul ei în fața ta sau răspunsul tău.",
            changed={"cards": cards},
        )
    words = (
        "Am pus în fața ta câte un card pentru fiecare furnizor și lună fără factură: "
        + "; ".join(
            f"{_vendor(p)} {m}: {count(len(r), 'estimare', 'estimări')}, "
            f"{usd_ro(sum(int(x.usd_micros) for x in r))} USD"
            + (_runway_words(checks[(p, m)]) if (p, m) in checks else "")
            for (p, m), r in shown.items()
        )
        + ". Nu am scris nimic în cărți: factura și reconcilierea sunt ale tale."
    )
    return outcome(
        APPLIED,
        words,
        changed={
            "groups": [
                {
                    "provider": p,
                    "month": m,
                    "rows": len(r),
                    "usd_micros": sum(int(x.usd_micros) for x in r),
                }
                for (p, m), r in shown.items()
            ],
            "runway_checks": {f"{p}:{m}": c for (p, m), c in checks.items()},
            "cards": cards,
        },
        letter_subject_ro="Estimări fără factură: un card pentru fiecare furnizor și lună",
    )


register_repair(
    "unbilled_estimates",
    ask_for_invoices,
    tier="T1",
    action="director.ask_for_invoices",
    precondition=still_unbilled,
    detector=unbilled_estimates,
    summary=(
        "group estimated provider costs older than a week by provider and month, say how much "
        "of Runway's is a measured balance drop, and ask the Owner for each invoice in one card"
    ),
    place_ro=TREASURY_PLACE_RO,
)
