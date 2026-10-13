"""What a render cost, as the vendors count it: the balance before, and the balance after.

The books priced a render from catalogue prices: the ATLAS film was recorded at 0.316 USD,
all of it Runway, with the narration unpriced because its model carries no price, and motion
estimated from a documented rather than a measured rate. The Owner's instruction was to verify
the cost from the credits — and the studio had never written a balance down, so "before" could
not be proven afterwards, and Runway's own usage report does not yet include the current day.

So the balance is read from each vendor immediately before a render and immediately after it,
and the difference is written on the render and into the event stream. Runway reports credits
(a hundred to the dollar on the Owner's account); ElevenLabs reports characters used this
period. Anything else spent on the same key during the render — another tool, a person in the
web app — is inside the difference too, and is said to be.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

logger = logging.getLogger("studio.economy")


def credit_balances(engine: Engine, vault: Any) -> dict[str, dict[str, Any]]:
    """What each verified vendor says the account holds right now. Best effort, never raises."""
    from app.integrations.models import Integration, ProviderResource  # noqa: PLC0415
    from app.providers.elevenlabs import ElevenLabsTTSAdapter  # noqa: PLC0415
    from app.providers.runway import RunwayVideoAdapter  # noqa: PLC0415

    wanted: list[tuple[str, str, str, str | None]] = []
    with Session(engine) as session:
        for row in session.scalars(select(Integration)):
            if row.kind not in ("runway", "elevenlabs") or row.status != "VERIFIED":
                continue
            try:
                key = str((vault.decrypt(row.encrypted_secrets) or {}).get("api_key") or "")
            except Exception:  # noqa: BLE001 - an unreadable secret is simply not measured
                continue
            model = session.scalar(
                select(ProviderResource.remote_id)
                .where(
                    ProviderResource.integration_id == row.id,
                    ProviderResource.resource_type == "MODEL",
                )
                .limit(1)
            )
            if key:
                wanted.append((row.id, row.kind, key, model))

    readings: dict[str, dict[str, Any]] = {}
    for integration_id, kind, key, model in wanted:
        try:
            if kind == "runway":
                organization = asyncio.run(RunwayVideoAdapter(key, model or "", {}).organization())
                balance = organization.get("creditBalance")
                if isinstance(balance, int | float):
                    readings[integration_id] = {
                        "kind": kind,
                        "unit": "credits",
                        "balance": float(balance),
                    }
            else:
                plan = asyncio.run(ElevenLabsTTSAdapter(key).subscription())
                used = plan.get("character_count")
                if isinstance(used, int | float):
                    readings[integration_id] = {
                        "kind": kind,
                        "unit": "characters",
                        "used": float(used),
                        "limit": plan.get("character_limit"),
                    }
        except Exception as exc:  # noqa: BLE001 - a vendor that cannot answer is not measured
            logger.info(
                "credit_balance_unavailable", extra={"kind": kind, "error": type(exc).__name__}
            )
    return readings


def credit_spend(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """The difference between two readings, per vendor, in the vendor's own unit."""
    spent: dict[str, dict[str, Any]] = {}
    for integration_id, first in before.items():
        last = after.get(integration_id)
        if not last or last.get("kind") != first.get("kind"):
            continue
        if first["kind"] == "runway":
            spent[integration_id] = {
                "kind": "runway",
                "unit": "credits",
                "before": first["balance"],
                "after": last["balance"],
                "spent": first["balance"] - last["balance"],
            }
        else:
            spent[integration_id] = {
                "kind": "elevenlabs",
                "unit": "characters",
                "before": first["used"],
                "after": last["used"],
                "spent": last["used"] - first["used"],
                "limit": last.get("limit"),
            }
    return spent


def record_credit_spend(
    engine: Engine,
    render_job_id: str,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> str:
    """Write what the vendors say this render used on the render and in the event stream."""
    from app.media.models import VideoRenderJob  # noqa: PLC0415
    from app.media.production_policy import credit_usd  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    spent = credit_spend(before, after)
    if not spent:
        return ""
    lines: list[str] = []
    with Session(engine) as session, session.begin():
        for integration_id, item in spent.items():
            if item["kind"] == "runway":
                per_credit = credit_usd(session, integration_id)
                if per_credit:
                    item["usd"] = round(float(item["spent"]) * float(per_credit), 4)
                lines.append(
                    f"Runway {item['before']:.0f} → {item['after']:.0f} credite "
                    f"(−{item['spent']:.0f}"
                    + (f", {item['usd']:.2f} USD)" if "usd" in item else ")")
                )
            else:
                lines.append(
                    f"ElevenLabs {item['before']:.0f} → {item['after']:.0f} caractere "
                    f"(+{item['spent']:.0f})"
                )
        job = session.get(VideoRenderJob, render_job_id)
        if job is not None:
            production = dict(job.production_json) if isinstance(job.production_json, dict) else {}
            production["credits_measured"] = spent
            job.production_json = production
        append_event(
            session,
            "economy.credits_measured",
            "video_render_job",
            render_job_id,
            1,
            {"render_job_id": render_job_id, "measured": spent},
            str(uuid4()),
        )
    return "; ".join(lines)


# ------------------------------------------------ what the account was charged, per model
#
# A measured balance drop is the dearest evidence about a price there is. The Nepal film's
# first render moved the balance by 966 credits while the studio's books said 0.74 USD. The drop
# over one purchase step is shared across what the step bought (app.media.cost_plan, in
# proportion to the published prices) and written back over the documented figures, so the
# next shooting sheet prices with what was paid and says "măsurat" beside it.

#: The unit words ``record_measured_price`` stores; the resolution rides after " at " so the
#: sheet can read the measurement back for the resolution it was measured at.
_UNIT_VIDEO = "per second of video at "
_UNIT_IMAGE = "per image at "


def record_measured_prices(
    engine: Engine,
    integration_id: str,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    takes: list[dict[str, Any]],
    *,
    table: Any = None,
    measured_on: date | None = None,
) -> dict[str, Any]:
    """Turn one step's Runway balance drop into MEASURED prices on the models it bought.

    ``takes`` are what the step bought, in the shapes ``cost_plan.attribute_measured_credits``
    reads. No drop (or no reading) writes nothing: a price is never measured as zero. Each
    measured rate goes through ``record_measured_price`` (per second or per image, in USD at
    the Owner's credit rate), so the old price is kept and a big move reaches the Owner; one
    ``economy.prices_measured`` event carries the whole attribution.
    """
    from app.media.cost_plan import attribute_measured_credits, load_price_table  # noqa: PLC0415
    from app.media.production_policy import credit_usd, record_measured_price  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    prices = table if table is not None else load_price_table()
    spent = credit_spend(before, after).get(integration_id) or {}
    credits = float(spent.get("spent") or 0.0) if spent.get("kind") == "runway" else 0.0
    if credits <= 0:
        return {"spent_credits": 0, "attribution": None, "rows": [], "moves": []}
    attribution = attribute_measured_credits(credits, takes, table=prices, measured_on=measured_on)
    with Session(engine) as session:
        per_credit = credit_usd(session, integration_id) or float(prices.credit_usd)
    moves: list[dict[str, Any]] = []
    for row in attribution["rows"]:
        if row.kind == "image":
            rate, unit = row.credits_per_image, _UNIT_IMAGE + row.resolution
        else:
            rate, unit = row.credits_per_second, _UNIT_VIDEO + row.resolution
        if not rate:
            continue
        for move in record_measured_price(
            engine, integration_id, row.model_id, float(rate) * per_credit, unit
        ):
            moves.append({**move, "model_id": row.model_id})
    payload = {
        "integration_id": integration_id,
        "spent_credits": credits,
        "quoted_credits": attribution["quoted_credits"],
        "attribution": attribution["attribution"],
        "credit_usd": per_credit,
        "shares": attribution["shares"],
        "rows": [row.as_dict() for row in attribution["rows"]],
    }
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "economy.prices_measured",
            "integration",
            integration_id,
            1,
            payload,
            str(uuid4()),
        )
    logger.info(
        "prices_measured",
        extra={"spent_credits": credits, "attribution": attribution["attribution"]},
    )
    return {
        "spent_credits": credits,
        "attribution": attribution["attribution"],
        "rows": attribution["rows"],
        "moves": moves,
    }


def measured_price_table(engine: Engine, integration_id: str, table: Any = None) -> Any:
    """The published table with this connection's MEASURED prices laid over it.

    Reads what ``record_measured_prices`` wrote on each model (``source: measured``, the
    resolution in the unit words) and converts it back to credits at the Owner's rate. A model
    or resolution nobody measured keeps its published row.
    """
    from dataclasses import replace  # noqa: PLC0415

    from app.integrations.models import ProviderResource  # noqa: PLC0415
    from app.media.cost_plan import (  # noqa: PLC0415
        MEASURED,
        UnpricedError,
        apply_measured,
        load_price_table,
    )
    from app.media.production_policy import credit_usd  # noqa: PLC0415

    prices = table if table is not None else load_price_table()
    measured = []
    with Session(engine) as session:
        per_credit = credit_usd(session, integration_id) or float(prices.credit_usd)
        models = session.scalars(
            select(ProviderResource).where(
                ProviderResource.integration_id == integration_id,
                ProviderResource.resource_type == "MODEL",
            )
        )
        for model in models:
            pricing = model.pricing if isinstance(model.pricing, dict) else {}
            unit = str(pricing.get("unit") or "")
            if pricing.get("source") != "measured":
                continue
            if unit.startswith(_UNIT_VIDEO):
                key, resolution = "per_second_usd", unit[len(_UNIT_VIDEO) :]
                field = "credits_per_second"
            elif unit.startswith(_UNIT_IMAGE):
                key, resolution = "per_image_usd", unit[len(_UNIT_IMAGE) :]
                field = "credits_per_image"
            else:
                continue
            usd = pricing.get(key)
            if not isinstance(usd, int | float) or usd <= 0:
                continue
            try:
                documented = prices.row(str(model.remote_id), resolution)
            except UnpricedError:
                continue
            day = str(model.price_verified_at or "")[:10] or date.today().isoformat()
            measured.append(
                replace(
                    documented,
                    provenance=MEASURED,
                    date=day,
                    **{field: float(usd) / per_credit},
                )
            )
    return apply_measured(prices, measured)
