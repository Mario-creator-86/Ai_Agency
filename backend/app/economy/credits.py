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
