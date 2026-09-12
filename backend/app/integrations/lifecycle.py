"""A model has a life, and a price has a date.

The studio buys generations from vendors whose catalogues change under it. A model the
account gained today is not a model the studio has filmed with; a price a steward read on a
page last week is not what the account was charged yesterday; and a model that was the best
choice in March can be three times the price of a better one by September. None of that can
be written into the code, because every one of those facts changes without asking.

So this module keeps three things, and nothing else:

- **Standing.** DISCOVERED → QUARANTINE → BENCHMARKING → CANDIDATE → PRODUCTION → PREFERRED,
  and DEPRECATED at the end or the side. A model may film a scene that will be published
  only from CANDIDATE upwards. What a model can do is read from the vendor's contract; a
  model whose capabilities are unknown waits in quarantine rather than being tried on a film.
- **Provenance of a price.** Which version, when it was verified, how (a vendor page, a dry
  run, a real charge), and what it was before. A price that changed is a fact with a date,
  never a silent overwrite, and a change past the Owner's threshold is a letter.
- **Judgement from the studio's own results.** Promotion and demotion are decided on what
  models actually delivered — acceptance, first-pass rate, cost per accepted second — from
  `model_outcome`, where a cheap functional test is recorded but never allowed to teach the
  studio that a model's picture is poor.

Nothing here names a model, a vendor or a price.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.models import Integration, ProviderResource
from app.services import append_event, utc_now

logger = logging.getLogger("studio.model_lifecycle")

#: The stations of a model's life, in order. A model may only film something that will be
#: published from `CANDIDATE` on; everything before that is "not yet", and `DEPRECATED` is
#: "no longer" — which is also where a model the Owner's deny list names is put.
LIFECYCLE = (
    "DISCOVERED",
    "QUARANTINE",
    "BENCHMARKING",
    "CANDIDATE",
    "PRODUCTION",
    "PREFERRED",
    "DEPRECATED",
)
#: The stations from which a model may film a published scene (also read by the router).
ADMITTED = ("CANDIDATE", "PRODUCTION", "PREFERRED")

#: The three units a generation can be priced in. Whatever a vendor calls its unit, the
#: studio stores the price under one of these, and a change is measured per key.
PRICE_KEYS = ("per_1k_characters_usd", "per_image_usd", "per_second_usd")

#: How a price was established, dearest evidence last: a page someone read, a dry run the
#: vendor answered, the charge a real generation incurred. Accounting uses what was billed.
VERIFICATION = ("DOCUMENTED", "ESTIMATED", "BILLED")


def deny_patterns(settings: Settings) -> tuple[str, ...]:
    """The model names the Owner refuses, as shell patterns (`STUDIO_MODEL_DENY_LIST`).

    A deny list is the one thing about models that belongs in configuration: it is the
    Owner's judgement, not a fact about the vendor's catalogue.
    """
    raw = str(getattr(settings, "model_deny_list", "") or "")
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def is_denied(remote_id: str, patterns: tuple[str, ...]) -> bool:
    name = str(remote_id).lower()
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def classify_discovered(
    remote_id: str, metadata: dict[str, Any] | None, *, patterns: tuple[str, ...] = ()
) -> tuple[str, str]:
    """Where a model the vendor has just exposed starts, and why.

    Three answers. A model the Owner's deny list names is retired on sight. A model whose
    contract the studio could not read has unknown capabilities, and an unknown model waits
    in quarantine — it is not tried on a film to find out. Everything else is discovered,
    which is where benchmarking starts.
    """
    if is_denied(remote_id, patterns):
        return "DEPRECATED", "Refuzat de lista Ownerului."
    meta = metadata if isinstance(metadata, dict) else {}
    tasks = meta.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return (
            "QUARANTINE",
            "Contractul vendorului nu spune ce poate face acest model; stă în carantină "
            "până se știe.",
        )
    return "DISCOVERED", "Model nou în catalogul vendorului; nu a filmat încă nimic."


# ------------------------------------------------------------------ what a price costs now


def price_changes(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> list[dict]:
    """Every priced unit that moved, with the size of the move.

    A new price where there was none is not a change — it is the first fact. A price that
    disappeared is reported, because a model that stops being priced stops being choosable.
    """
    was = previous if isinstance(previous, dict) else {}
    now = current if isinstance(current, dict) else {}
    moves: list[dict] = []
    for key in PRICE_KEYS:
        before, after = was.get(key), now.get(key)
        if not isinstance(before, int | float) or float(before) <= 0:
            continue
        if not isinstance(after, int | float):
            moves.append({"key": key, "was": float(before), "now": None, "percent": None})
            continue
        if abs(float(after) - float(before)) < 1e-9:
            continue
        percent = (float(after) - float(before)) / float(before) * 100.0
        moves.append(
            {"key": key, "was": float(before), "now": float(after), "percent": round(percent, 2)}
        )
    return moves


def stamp_price(
    row: ProviderResource,
    pricing: dict[str, Any] | None,
    *,
    verification: str,
    source: str,
) -> list[dict]:
    """Write a price onto a model with its provenance, and return what moved.

    The row keeps what the price was before, so nothing is lost by being corrected, and the
    caller decides whether the size of the move is worth the Owner's attention.

    **What the account was charged outranks what a page says.** A steward read
    "0.08 USD a second" on the vendor's documentation for the model four renders had
    measured at 0.43, and the reading replaced the measurement — which would have let a test
    through a ceiling of 0.12 and been billed 3.6 times that. So a documented price never
    overwrites a billed one: the billed figure stays the price the studio budgets with, the
    documented figure is kept beside it as `documented_<unit>`, and the disagreement is
    returned to the caller to put in a letter.
    """
    before = dict(row.pricing) if isinstance(row.pricing, dict) else {}
    wanted = dict(pricing or {})
    kind = verification if verification in VERIFICATION else "DOCUMENTED"
    billed = str(row.price_verification or "") == "BILLED"
    disputed: list[dict] = []
    if billed and kind == "DOCUMENTED":
        for key in PRICE_KEYS:
            charged, documented = before.get(key), wanted.get(key)
            if not isinstance(charged, int | float) or not isinstance(documented, int | float):
                continue
            wanted[key] = charged
            wanted[f"documented_{key}"] = documented
            if abs(float(documented) - float(charged)) > 1e-9:
                disputed.append(
                    {
                        "key": key,
                        "was": float(charged),
                        "now": float(documented),
                        "percent": round(
                            (float(documented) - float(charged)) / float(charged) * 100.0, 2
                        ),
                        "documented_only": True,
                    }
                )
    moves = price_changes(before, wanted)
    row.pricing = wanted
    if moves:
        row.previous_pricing_json = before
    row.pricing_version = int(row.pricing_version or 1) + 1
    row.price_verified_at = utc_now()
    # A page cannot demote a measurement: the provenance stays BILLED until the account is
    # charged something else, or the vendor quotes something else.
    row.price_verification = "BILLED" if billed and kind == "DOCUMENTED" else kind
    row.metadata_source = source[:2000]
    row.metadata_updated_at = utc_now()
    return moves + disputed


def price_is_stale(
    row: ProviderResource, observed_usd: float, *, unit_key: str, tolerance_percent: float
) -> dict | None:
    """Whether what the vendor just quoted disagrees with what the studio has written down.

    A dry run or a real charge is the vendor speaking about today's price. When it differs
    from the stored price by more than the tolerance, the stored price is stale and the
    difference is the fact — a steward's reading of one page once outlived four renders that
    measured seventeen times more.
    """
    stored = (row.pricing or {}).get(unit_key) if isinstance(row.pricing, dict) else None
    if not isinstance(stored, int | float) or float(stored) <= 0 or observed_usd <= 0:
        return None
    drift = (observed_usd - float(stored)) / float(stored) * 100.0
    if abs(drift) <= abs(tolerance_percent):
        return None
    return {
        "model_id": str(row.remote_id),
        "unit": unit_key,
        "stored": round(float(stored), 6),
        "observed": round(observed_usd, 6),
        "percent": round(drift, 2),
    }


# ------------------------------------------------------------------ who is admitted, and why


def _verdict(
    status: str,
    record: dict[str, Any],
    *,
    settings: Settings,
    cheapest_admitted: float | None,
) -> tuple[str, str] | None:
    """The one promotion or demotion this model's own results justify, if any.

    Read as a ladder: enough judged generations with a high acceptance rate move a model up
    one station, a model that keeps failing technically goes back to quarantine, and a model
    that costs a multiple of an admitted model per accepted second is retired. One step at a
    time, so a single good day cannot carry a model from discovered to preferred.
    """
    judged = int(record.get("judged") or 0)
    acceptance = record.get("acceptance")
    technical = int(record.get("technical_failures") or 0)
    minimum = max(1, int(settings.min_test_samples_for_promotion))
    cost = record.get("cost_per_accepted_second")

    # Demotion first: a model that cannot deliver is not promoted by its price.
    if status in ADMITTED and judged >= minimum and acceptance is not None and acceptance < 0.5:
        return (
            "QUARANTINE",
            f"A livrat {acceptance:.0%} din {judged} generări judecate; se întoarce în carantină.",
        )
    if status in ADMITTED and technical >= 3 and judged == 0:
        return (
            "QUARANTINE",
            f"{technical} eșecuri tehnice și nicio generare acceptată.",
        )
    if (
        settings.auto_demote_expensive_models
        and status in ADMITTED
        and isinstance(cost, int | float)
        and isinstance(cheapest_admitted, int | float)
        and cheapest_admitted > 0
        and float(cost) > cheapest_admitted * 3
    ):
        return (
            "DEPRECATED",
            f"Costă {float(cost) / cheapest_admitted:.1f}x pe secundă acceptată față de cel "
            "mai ieftin model admis, la aceeași calitate cerută.",
        )

    # A discovered model the Owner allows the studio to try is moved to benchmarking, which
    # is what a TEST render picks up: it films the cheapest compatible model, and a model in
    # benchmarking has its results judged instead of discarded as a functional check.
    if (
        status == "DISCOVERED"
        and settings.auto_benchmark_new_models
        and judged == 0
        and technical == 0
    ):
        return (
            "BENCHMARKING",
            "Model nou pe care studioul are voie să îl încerce; intră la testare, cu "
            f"cel mult {settings.max_benchmark_budget_usd:.2f} USD pe rundă.",
        )

    if not settings.auto_promote_cheaper_better_models:
        return None
    if judged < minimum or acceptance is None or acceptance < 0.8:
        return None
    if status in ("DISCOVERED", "QUARANTINE", "BENCHMARKING"):
        return (
            "CANDIDATE",
            f"A livrat {acceptance:.0%} din {judged} generări judecate; intră ca candidat.",
        )
    if status == "CANDIDATE" and judged >= minimum * 2:
        return (
            "PRODUCTION",
            f"A livrat {acceptance:.0%} din {judged} generări judecate; intră în producție.",
        )
    return None


def review_models(
    engine: Engine,
    settings: Settings,
    *,
    full: bool = False,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Re-judge every model the studio can call, on what it has actually delivered.

    The light review (daily) moves models between stations on the evidence already recorded.
    The full review (weekly) does the same and also reports the frontier — what each purpose
    would cost per accepted second at each admitted model — so the Owner can see whether the
    studio is paying a multiple for a quality it is not asking for.

    Nothing here generates anything, so the review itself costs nothing.
    """
    from app.media.production_policy import model_record  # noqa: PLC0415

    correlation = correlation_id or str(uuid4())
    patterns = deny_patterns(settings)
    changes: list[dict[str, Any]] = []
    frontier: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        integrations = {row.id: row for row in session.scalars(select(Integration))}
        rows = list(
            session.scalars(
                select(ProviderResource).where(ProviderResource.resource_type == "MODEL")
            )
        )
        # The cheapest admitted model per connection and purpose is the yardstick a dear
        # model is measured against; without it "expensive" means nothing.
        records: dict[str, dict[str, Any]] = {}
        cheapest: dict[tuple[str, str], float] = {}
        for row in rows:
            integration = integrations.get(row.integration_id)
            if integration is None:
                continue
            purpose = _purpose_of(session, integration.kind, row)
            if purpose is None:
                continue
            record = model_record(session, row.integration_id, purpose, str(row.remote_id))
            records[row.id] = {"purpose": purpose, "record": record}
            cost = record.get("cost_per_accepted_second")
            if str(row.production_status or "") in ADMITTED and isinstance(cost, int | float):
                key = (row.integration_id, purpose)
                cheapest[key] = min(cheapest.get(key, float("inf")), float(cost))

        for row in rows:
            entry = records.get(row.id)
            if entry is None:
                continue
            status = str(row.production_status or "PRODUCTION")
            # The deny list outranks every result: it is the Owner's decision, not a measure.
            if is_denied(str(row.remote_id), patterns) and status != "DEPRECATED":
                changes.append(
                    _move(session, row, "DEPRECATED", "Refuzat de lista Ownerului.", correlation)
                )
                continue
            purpose = str(entry["purpose"])
            record = entry["record"]
            verdict = _verdict(
                status,
                record,
                settings=settings,
                cheapest_admitted=cheapest.get((row.integration_id, purpose)),
            )
            if verdict is not None and verdict[0] != status:
                changes.append(_move(session, row, verdict[0], verdict[1], correlation))
            if full:
                frontier.append(
                    {
                        "model_id": str(row.remote_id),
                        "purpose": purpose,
                        "status": str(row.production_status or ""),
                        "judged": record.get("judged"),
                        "acceptance": record.get("acceptance"),
                        "cost_per_accepted_second": record.get("cost_per_accepted_second"),
                    }
                )
    logger.info(
        "model_review", extra={"full": full, "changed": len(changes), "models": len(frontier)}
    )
    return {
        "status": "COMPLETED",
        "kind": "FULL" if full else "LIGHT",
        "changes": changes,
        "frontier": sorted(
            frontier,
            key=lambda f: (
                f["purpose"],
                f["cost_per_accepted_second"]
                if isinstance(f["cost_per_accepted_second"], int | float)
                else float("inf"),
            ),
        ),
    }


def _purpose_of(session: Session, kind: str, row: ProviderResource) -> str | None:
    """Which purpose this model serves, as the connection's own catalogue declares it."""
    from app.integrations.discovery import usable_purposes  # noqa: PLC0415

    purposes = usable_purposes(kind, row)
    for purpose in ("video", "image", "voice"):
        if purpose in purposes:
            return purpose
    return None


def _move(
    session: Session, row: ProviderResource, status: str, note: str, correlation: str
) -> dict[str, Any]:
    was = str(row.production_status or "")
    row.production_status = status
    row.lifecycle_note = note[:2000]
    append_event(
        session,
        "provider.model_lifecycle_changed",
        "provider_resource",
        row.id,
        int(row.metadata_version or 0) + 1,
        {"model_id": str(row.remote_id), "was": was, "now": status, "note": note[:400]},
        correlation,
    )
    logger.info(
        "model_lifecycle_changed",
        extra={"model": str(row.remote_id), "was": was, "now": status},
    )
    return {"model_id": str(row.remote_id), "was": was, "now": status, "note": note}
