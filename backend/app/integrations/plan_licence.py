"""Plan licence: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

logger = logging.getLogger("studio.integrations")

#: ElevenLabs plans that carry a commercial licence (every paid plan; the free plan does not).
PAID_TIERS = frozenset(
    {"starter", "creator", "pro", "scale", "business", "growing_business", "enterprise"}
)
#: Subscription states in which the plan's licence holds.
ACTIVE_STATUSES = frozenset({"active", "trialing"})
#: How often a connection without the licence is read again: a free plan may be upgraded, and
#: the Owner chose to upgrade his (card 2026-10-10 21:10, «Trec eu pe plan plătit»), so the
#: studio sees it within the hour. One GET an hour buys nothing.
RECHECK = timedelta(hours=1)
#: The connection's answer the rights check counts (`media.factory.COMMERCIAL_USE_YES`).
YES = "da"
LICENCE_EVENT = "integrations.licence_recorded"

PlanReader = Callable[[str], dict[str, Any]]


def is_paid_tier(tier: str) -> bool:
    """A paid plan by the vendor's own name for it: one of `PAID_TIERS`, or one of them with a
    suffix the vendor adds to a billing variant («creator_annual», «pro_2024»). A free plan,
    whatever its suffix, is never paid, and a name that is neither is not guessed into one."""
    name = tier.strip().lower()
    if not name or name.startswith("free"):
        return False
    return name in PAID_TIERS or any(name.startswith(f"{paid}_") for paid in PAID_TIERS)


def _read_plan(api_key: str) -> dict[str, Any]:
    from app.providers.elevenlabs import ElevenLabsTTSAdapter  # noqa: PLC0415

    return asyncio.run(ElevenLabsTTSAdapter(api_key).subscription())


def record_plan_licences(
    engine: Engine,
    vault: Any,
    *,
    read_plan: PlanReader | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read each verified ElevenLabs connection's plan and record its commercial licence when the
    plan is paid and active. Returns what was recorded and what was only checked. A GET that
    buys nothing; never raises (a vendor that cannot answer is read again later)."""
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    read = read_plan or _read_plan
    moment = now or datetime.now(UTC)
    due: list[tuple[str, str]] = []
    with Session(engine) as session:
        for row in session.scalars(select(Integration).where(Integration.kind == "elevenlabs")):
            config = dict(row.config or {})
            if row.status != "VERIFIED" or str(config.get("commercial_use") or "").lower() == YES:
                continue
            checked = str(config.get("licence_checked_at") or "")
            if checked:
                try:
                    if moment - datetime.fromisoformat(checked) < RECHECK:
                        continue
                except ValueError:
                    pass
            try:
                key = str((vault.decrypt(row.encrypted_secrets) or {}).get("api_key") or "")
            except Exception:  # noqa: BLE001 - an unreadable secret is simply not read
                continue
            if key:
                due.append((row.id, key))

    recorded: list[str] = []
    checked_only: list[dict[str, Any]] = []
    for integration_id, key in due:
        try:
            plan = read(key)
        except AssertionError:
            raise  # the test suite's network guard: a test must fake this read, never reach it
        except Exception as exc:  # noqa: BLE001 - read again on a later pass
            logger.info("plan_licence_unread", extra={"error": type(exc).__name__})
            continue
        tier = str(plan.get("tier") or "").strip().lower()
        status = str(plan.get("status") or "").strip().lower()
        paid = is_paid_tier(tier) and (not status or status in ACTIVE_STATUSES)
        day = moment.date().isoformat()
        with Session(engine) as session, session.begin():
            record = session.get(Integration, integration_id)
            if record is None:
                continue
            config = dict(record.config or {})
            config["licence_checked_at"] = moment.isoformat()
            config["licence_plan_tier"] = tier or None
            if paid:
                config["commercial_use"] = YES
                config["licence_terms"] = (
                    f"ElevenLabs, planul «{tier}» ({status or 'activ'}): planurile plătite includ "
                    f"licența comercială; citit din cont prin API la {day}."
                )
                config["licence_source"] = "vendor_api"
                # A recorded licence is a new version of the connection, with its event.
                record.version = int(record.version or 0) + 1
                event = append_event(
                    session,
                    LICENCE_EVENT,
                    "integration",
                    integration_id,
                    int(record.version),
                    {"vendor": "elevenlabs", "tier": tier, "status": status, "read_at": utc_now()},
                    str(uuid4()),
                )
                record.event_id = event.event_id
            # A plan without the licence only notes when it was read: no new version, so the
            # Owner's own edit of the connection never meets a conflict from a daily reading.
            record.config = config
        if paid:
            recorded.append(integration_id)
        else:
            checked_only.append({"integration_id": integration_id, "tier": tier, "status": status})
    return {"recorded": recorded, "checked": checked_only}
