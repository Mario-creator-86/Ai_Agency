"""How much the studio may spend, and whether it still may.

The books say what was spent; the treasury says what is spendable. Neither says what the
Owner allows, so no stage could refuse a render that would blow the month, and the
Accountant had nothing to report against. A `SpendingBudget` is that allowance: one active
limit per period, set by the Owner, in USD micros like every amount in the books. Spend is
measured from `provider_cost_record` — ESTIMATED and BILLED alike, because an estimate is a
commitment the studio already made, and a budget that counted only invoices would report
"fine" until the invoices arrived — and from `agent_run.cost_vr` where a run was priced.
Unpriced usage (a model without a stored price) cannot be counted; it is reported as such
rather than as zero.

Two things measured on a copy of the live database (2026-09-18) shaped this module's second
version. The period opened at UTC midnight while the studio's day is Europe/Bucharest, so
the first two hours of a day's spend were counted against the day before; the window now
opens at the studio's own midnight, read from the studio row the way the day's log reads
it. And the pre-render check asked `may_spend(engine, 0)` from a snapshot, so a day at
14.99 of 15 USD started a full film and two films asked together were both told the last
ten dollars were free; a `SpendReservation` is decided behind the write lock and counts
against the period until the real cost replaces it or it is let go.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentRun
from app.db import lock_for_write
from app.economy.models import ProviderCostRecord, SpendingBudget, SpendReservation
from app.economy.services import EconomyError, format_micros, to_micros
from app.models import Studio
from app.services import append_event, utc_now

PERIODS = ("DAILY", "MONTHLY")

#: How long a reservation may stand before the watchdog lets it go: a film takes minutes,
#: a day's worth of retries hours; six hours without a settlement is a process that died.
#: Read through `settings.reservation_ttl_seconds` when the settings carry it.
DEFAULT_RESERVATION_TTL_SECONDS = 6 * 3600


class BudgetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(pattern="^(DAILY|MONTHLY)$")
    #: The limit in USD, as a decimal string; "0" or "" retires the active budget.
    limit_usd: str = Field(max_length=20)
    warn_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    notes: str | None = Field(default=None, max_length=2000)


def studio_timezone(session: Session) -> str:
    """The studio's own zone, from the row bootstrap wrote from the settings. UTC only for a
    database with no studio row, which is not a studio."""
    studio = session.get(Studio, 1)
    return studio.timezone if studio is not None and studio.timezone else "UTC"


def _period_start(period: str, now: datetime, timezone: str = "UTC") -> str:
    """When the period opened, as the UTC instant the books' `recorded_at` stamps compare to.

    Local midnight (or the local first of the month) in the studio's zone, converted back:
    2026-09-18 00:00 in Bucharest is 2026-09-17T21:00:00+00:00, and a cost recorded at
    22:30 UTC on the 17th belongs to the 18th where the studio is.
    """
    moment = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local = moment.astimezone(ZoneInfo(timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "MONTHLY":
        start = start.replace(day=1)
    return start.astimezone(UTC).isoformat()


def _budget_view(row: SpendingBudget) -> dict[str, Any]:
    return {
        "id": row.id,
        "period": row.period,
        "limit_usd": format_micros(row.limit_usd_micros),
        "limit_usd_micros": row.limit_usd_micros,
        "warn_ratio": row.warn_ratio,
        "active": bool(row.active),
        "set_by": row.set_by,
        "notes": row.notes,
        "created_at": row.created_at,
        "replaced_at": row.replaced_at,
    }


def set_budget(
    engine: Engine,
    command: BudgetCommand,
    *,
    set_by: str = "owner",
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Set (or retire) the active budget for a period. The previous one is kept, replaced."""
    correlation = correlation_id or str(uuid4())
    limit_micros = to_micros(command.limit_usd or "0") if (command.limit_usd or "").strip() else 0
    if limit_micros < 0:
        raise EconomyError("A budget cannot be negative.")
    with Session(engine) as session, session.begin():
        now = utc_now()
        for previous in session.scalars(
            select(SpendingBudget).where(
                SpendingBudget.period == command.period, SpendingBudget.active.is_(True)
            )
        ):
            previous.active = False
            previous.replaced_at = now
        if limit_micros == 0:
            append_event(
                session,
                "economy.budget_retired",
                "spending_budget",
                command.period,
                1,
                {"period": command.period, "set_by": set_by},
                correlation,
            )
            return {"period": command.period, "active": False}
        row = SpendingBudget(
            id=str(uuid4()),
            period=command.period,
            limit_usd_micros=limit_micros,
            warn_ratio=command.warn_ratio,
            active=True,
            set_by=set_by[:100],
            notes=(command.notes or "").strip()[:2000] or None,
            created_at=now,
        )
        session.add(row)
        session.flush()
        event = append_event(
            session,
            "economy.budget_set",
            "spending_budget",
            row.id,
            1,
            {"period": row.period, "limit_usd": format_micros(limit_micros), "set_by": set_by},
            correlation,
        )
        row.event_id = event.event_id
        return _budget_view(row)


def _agent_spend_micros(session: Session, since_iso: str) -> int:
    """What the priced agent runs cost since a moment. `cost_vr` is a decimal string written
    by the adapter from the Owner's prices; summed here in micros, never as floats."""
    total = 0
    for cost in session.scalars(
        select(AgentRun.cost_vr).where(
            AgentRun.started_at >= since_iso, AgentRun.cost_vr.is_not(None)
        )
    ):
        if cost is None:
            continue  # filtered above; typed nullable, so the checker is told as well
        try:
            total += to_micros(cost)
        except EconomyError:
            continue  # a malformed string is not money; it is reported nowhere as such
    return total


def reserved_since(session: Session, since_iso: str) -> int:
    """What is held against the period right now: every RESERVED row made since it opened."""
    return int(
        session.scalar(
            select(func.coalesce(func.sum(SpendReservation.usd_micros), 0)).where(
                SpendReservation.status == "RESERVED", SpendReservation.reserved_at >= since_iso
            )
        )
        or 0
    )


def spend_since(session: Session, since_iso: str) -> dict[str, Any]:
    """What the books say was spent since a moment: priced costs, priced agent runs, the
    usage nobody priced, and the sums still held by films in progress."""
    rows = session.execute(
        select(
            ProviderCostRecord.provider,
            ProviderCostRecord.status,
            func.sum(ProviderCostRecord.usd_micros),
            func.count(),
        )
        # A row a vendor's invoice has replaced is skipped, never subtracted: the BILLED row
        # the reconciliation wrote carries the hour of the last spend it pays for, so the
        # period counts the estimate until the invoice arrives and the invoice afterwards.
        # Measured before `reconciled_at` existed: 4.20 estimated and 4.55 billed for the same
        # render charged the period 8.75.
        .where(
            ProviderCostRecord.recorded_at >= since_iso,
            ProviderCostRecord.reconciled_at.is_(None),
        )
        .group_by(ProviderCostRecord.provider, ProviderCostRecord.status)
    ).all()
    by_provider: dict[str, dict[str, Any]] = {}
    total = 0
    for provider, status, micros, count in rows:
        entry = by_provider.setdefault(
            provider,
            {"provider": provider, "estimated_usd_micros": 0, "billed_usd_micros": 0, "records": 0},
        )
        key = "billed_usd_micros" if status == "BILLED" else "estimated_usd_micros"
        entry[key] += int(micros or 0)
        entry["records"] += int(count or 0)
        total += int(micros or 0)
    failed = int(
        session.scalar(
            select(func.coalesce(func.sum(ProviderCostRecord.usd_micros), 0)).where(
                ProviderCostRecord.recorded_at >= since_iso,
                ProviderCostRecord.failed.is_(True),
                ProviderCostRecord.reconciled_at.is_(None),
            )
        )
        or 0
    )
    runs = session.execute(
        select(
            func.count(), func.sum(AgentRun.prompt_tokens), func.sum(AgentRun.completion_tokens)
        ).where(AgentRun.started_at >= since_iso, AgentRun.status == "SUCCEEDED")
    ).one()
    unpriced_runs = session.scalar(
        select(func.count()).where(
            AgentRun.started_at >= since_iso,
            AgentRun.status == "SUCCEEDED",
            AgentRun.cost_vr.is_(None),
        )
    )
    agent_micros = _agent_spend_micros(session, since_iso)
    total += agent_micros
    reserved = reserved_since(session, since_iso)
    return {
        "since": since_iso,
        "spent_usd_micros": total,
        "spent_usd": format_micros(total),
        "by_provider": sorted(by_provider.values(), key=lambda e: e["provider"]),
        # The priced agent runs, inside the total; shown apart so the Owner can see the tokens.
        "agent_usd_micros": agent_micros,
        "agent_usd": format_micros(agent_micros),
        # The cost of renders that failed midway, inside the total: paid for, never delivered.
        "failed_render_usd_micros": failed,
        "failed_render_usd": format_micros(failed),
        # Held by films in progress: not spent yet, and not free either.
        "reserved_usd_micros": reserved,
        "reserved_usd": format_micros(reserved),
        "agent_runs": int(runs[0] or 0),
        "prompt_tokens": int(runs[1] or 0),
        "completion_tokens": int(runs[2] or 0),
        # Runs whose model has no stored price: real usage the books cannot value yet.
        "unpriced_agent_runs": int(unpriced_runs or 0),
    }


def _period_status(session: Session, moment: datetime, timezone: str) -> list[dict[str, Any]]:
    """Every active budget against its period's spend and holds. Session-based so a
    reservation can be decided inside the transaction that writes it."""
    periods = []
    for row in session.scalars(select(SpendingBudget).where(SpendingBudget.active.is_(True))):
        since = _period_start(row.period, moment, timezone)
        spend = spend_since(session, since)
        spent = spend["spent_usd_micros"]
        reserved = spend["reserved_usd_micros"]
        committed = spent + reserved
        ratio = committed / row.limit_usd_micros if row.limit_usd_micros else 0.0
        periods.append(
            {
                **_budget_view(row),
                "since": since,
                "spent_usd": format_micros(spent),
                "spent_usd_micros": spent,
                "reserved_usd": format_micros(reserved),
                "reserved_usd_micros": reserved,
                "remaining_usd": format_micros(max(0, row.limit_usd_micros - committed)),
                "remaining_usd_micros": row.limit_usd_micros - committed,
                "ratio": round(ratio, 4),
                "state": (
                    "EXCEEDED"
                    if committed > row.limit_usd_micros
                    else "WARNING"
                    if ratio >= row.warn_ratio
                    else "OK"
                ),
                "unpriced_agent_runs": spend["unpriced_agent_runs"],
            }
        )
    return periods


def budget_status(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    """Every active budget against the spend of its period, plus the spend itself."""
    moment = now or datetime.now(UTC)
    with Session(engine) as session:
        timezone = studio_timezone(session)
        periods = _period_status(session, moment, timezone)
        today = spend_since(session, _period_start("DAILY", moment, timezone))
        month = spend_since(session, _period_start("MONTHLY", moment, timezone))
    return {
        "budgets": periods,
        "today": today,
        "month": month,
        "timezone": timezone,
        "measured_at": utc_now(),
    }


def _refusal(period: dict[str, Any], usd_micros: int) -> dict[str, Any]:
    held = (
        f", {period['reserved_usd']} USD rezervați pentru filme în lucru"
        if period["reserved_usd_micros"]
        else ""
    )
    return {
        "allowed": False,
        "period": period["period"],
        "reason": (
            f"Bugetul {period['period'].lower()} de {period['limit_usd']} USD ar fi "
            f"depășit: {period['spent_usd']} USD cheltuiți deja{held}, cererea este de "
            f"{format_micros(max(0, usd_micros))} USD."
        ),
    }


def may_spend(engine: Engine, usd_micros: int, now: datetime | None = None) -> dict[str, Any]:
    """Whether a spend of this size fits every active budget; with no budget, it always does.

    An estimate of zero (unpriced) still has to pass: a budget already exceeded refuses even
    what it cannot value, because it cannot value it. Sums reserved by films in progress
    count as spent. This is a reading, not a hold: a stage that is about to spend should
    `reserve_spend` instead, so the next caller sees the money as taken.
    """
    status = budget_status(engine, now)
    for period in status["budgets"]:
        committed = period["spent_usd_micros"] + period["reserved_usd_micros"]
        if committed + max(0, usd_micros) > period["limit_usd_micros"]:
            return {**_refusal(period, usd_micros), "status": status}
    return {"allowed": True, "period": None, "reason": "", "status": status}


def reserve_spend(
    engine: Engine,
    usd_micros: int,
    purpose: str,
    correlation_id: str,
    *,
    now: datetime | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Hold a sum against every active budget, or refuse. Decided behind the write lock.

    `may_spend` reads a snapshot; two films asked in the same second were both told the last
    ten dollars were free. Here the check and the hold are one transaction that took the
    studio's write lock before reading anything, so the second caller reads the first one's
    row. A sum of zero (an unpriced plan) is checked and holds nothing: there is nothing to
    hold, and the refusal of an exceeded budget still applies.
    """
    moment = now or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        periods = _period_status(session, moment, studio_timezone(session))
        for period in periods:
            committed = period["spent_usd_micros"] + period["reserved_usd_micros"]
            if committed + max(0, usd_micros) > period["limit_usd_micros"]:
                return {**_refusal(period, usd_micros), "reservation_id": None}
        if usd_micros <= 0:
            return {"allowed": True, "period": None, "reason": "", "reservation_id": None}
        row = SpendReservation(
            id=str(uuid4()),
            purpose=" ".join(str(purpose).split())[:200] or "film",
            correlation_id=correlation_id[:36],
            usd_micros=int(usd_micros),
            status="RESERVED",
            reserved_at=utc_now(),
            note=(note or "").strip()[:2000] or None,
        )
        session.add(row)
        session.flush()
        event = append_event(
            session,
            "economy.spend_reserved",
            "spend_reservation",
            row.id,
            1,
            {"purpose": row.purpose, "usd": format_micros(row.usd_micros)},
            correlation_id,
        )
        row.event_id = event.event_id
        return {
            "allowed": True,
            "period": None,
            "reason": "",
            "reservation_id": row.id,
            "usd_micros": row.usd_micros,
            "usd": format_micros(row.usd_micros),
        }


def _close_reservation(
    session: Session, reservation_id: str, status: str, reference: str, correlation: str
) -> dict[str, Any]:
    row = session.get(SpendReservation, reservation_id)
    if row is None:
        raise EconomyError("Reservation not found")
    if row.status != "RESERVED":
        return {"reservation_id": row.id, "status": row.status, "released": False, "changed": False}
    row.status = status
    row.released_at = utc_now()
    row.settled_reference = reference[:120]
    event = append_event(
        session,
        "economy.spend_reservation_closed",
        "spend_reservation",
        row.id,
        2,
        {
            "status": status,
            "reference": row.settled_reference,
            "usd": format_micros(row.usd_micros),
        },
        correlation,
    )
    row.event_id = event.event_id
    return {
        "reservation_id": row.id,
        "status": status,
        "released": status == "RELEASED",
        "changed": True,
        "usd": format_micros(row.usd_micros),
    }


def release_reservation(
    engine: Engine, reservation_id: str, reason: str, *, correlation_id: str | None = None
) -> dict[str, Any]:
    """Let a hold go: the film was not made. A second release changes nothing."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        return _close_reservation(
            session, reservation_id, "RELEASED", reason, correlation_id or str(uuid4())
        )


def settle_reservation(
    engine: Engine,
    reservation_id: str,
    *,
    settled_reference: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """The real cost rows are in the books; the hold stops counting. Called after
    `record_render_costs`, with the render job as the reference."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        return _close_reservation(
            session, reservation_id, "SETTLED", settled_reference, correlation_id or str(uuid4())
        )


def release_stale_reservations(
    engine: Engine,
    *,
    ttl_seconds: int = DEFAULT_RESERVATION_TTL_SECONDS,
    correlation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The watchdog's hand: a hold older than the TTL was left by a process that died under
    it, and a day's budget must not stay pledged to a film nobody is making."""
    moment = now or datetime.now(UTC)
    cutoff = (moment - timedelta(seconds=int(ttl_seconds))).isoformat()
    correlation = correlation_id or str(uuid4())
    released: list[str] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        stale = session.scalars(
            select(SpendReservation).where(
                SpendReservation.status == "RESERVED", SpendReservation.reserved_at < cutoff
            )
        ).all()
        for row in stale:
            _close_reservation(
                session,
                row.id,
                "RELEASED",
                f"watchdog: older than {int(ttl_seconds)} s with no settlement",
                correlation,
            )
            released.append(row.id)
    return {"released": released, "ttl_seconds": int(ttl_seconds), "cutoff": cutoff}


#: What a part of a film is called when the studio has to say it could not price it. One
#: place, because the letter, the question and the reservation must name it in the same words.
UNPRICED_PART_LABELS: dict[str, str] = {"narration": "narația"}

#: The first words of that sentence, so a reader of a stored note or of the Owner's question
#: can find the caveat inside a longer line without the sentence being parsed or guessed at.
UNPRICED_CAVEAT_PREFIX = "estimare incompletă"


def unpriced_caveat(parts: Sequence[str]) -> str:
    """The one sentence the studio says about a figure it could not complete, or "".

    An estimate that counted a part of the film as nothing is not wrong by a rounding: the
    part is simply absent from it. Said in the Owner's language, and said identically wherever
    the figure is shown, because a total that reads as complete in one place and incomplete in
    another is worse than either.
    """
    if not parts:
        return ""
    names = ", ".join(UNPRICED_PART_LABELS.get(part, part) for part in parts)
    tail = (
        "nu are preț stocat și este numărată ca zero"
        if len(parts) == 1
        else "nu au preț stocat și sunt numărate ca zero"
    )
    return f"{UNPRICED_CAVEAT_PREFIX}: {names} {tail}"


def estimate_film_cost_micros(
    engine: Engine,
    storyboard_id: str,
    *,
    environment: str,
    settings: Any,
) -> dict[str, Any]:
    """What a film is expected to cost before it is made, for the reservation.

    Conservative on purpose: the motion is taken at the ceiling the render will be given
    (the per-film motion budget in PRODUCTION, the test shots at the test ceiling in TEST),
    and the narration at the dearest active ElevenLabs price per thousand characters over
    the storyboard's own voiceover. A film that costs less settles for less; a film that was
    let through on a hopeful estimate is the one that spends the week.

    It also returns what it could not price. With no active ElevenLabs price per thousand
    characters the narration was counted as zero and the total read as a complete estimate of
    the film, so a SUPERVISED Owner answered a question about a figure that was missing a part
    of it; `unpriced`, `caveat` and `complete` travel with the figure to the reservation's
    note, to that question and to the letter about it, so all three say the same thing.
    """
    from app.economy.models import ProviderPrice  # noqa: PLC0415
    from app.media.models import StoryboardScene  # noqa: PLC0415

    with Session(engine) as session:
        characters = sum(
            len(" ".join(str(segment or "").split()))
            for segment in session.scalars(
                select(StoryboardScene.voiceover_segment).where(
                    StoryboardScene.storyboard_id == storyboard_id
                )
            )
        )
        per_1k = session.scalar(
            select(func.max(ProviderPrice.usd_micros)).where(
                ProviderPrice.provider_kind == "elevenlabs",
                ProviderPrice.unit == "per_1k_characters",
                ProviderPrice.active.is_(True),
            )
        )
    narration = (characters * int(per_1k) + 500) // 1000 if per_1k else 0
    # What the figure below does not contain. Only where there was something to price: a
    # storyboard with no voiceover costs nothing for narration whatever the books hold, and a
    # caveat on every film would teach the Owner to read past the one that matters.
    unpriced = ["narration"] if characters and not per_1k else []
    if environment == "TEST":
        motion_usd = float(getattr(settings, "test_max_cost_per_generation_usd", 0.0)) * int(
            getattr(settings, "test_motion_scenes", 0)
        )
    else:
        motion_usd = float(getattr(settings, "motion_budget_usd", 0.0))
    motion = to_micros(f"{max(0.0, motion_usd):.6f}")
    total = narration + motion
    return {
        "usd_micros": total,
        "usd": format_micros(total),
        "narration_usd_micros": narration,
        "narration_priced": bool(per_1k),
        "characters": characters,
        "motion_usd_micros": motion,
        # The three the callers carry onward: the parts as data, the sentence the Owner
        # reads, and the one flag a caller can branch on without knowing either. `complete`
        # means every part this function *tried* to price was priced — the narration and the
        # motion ceiling — and never that the figure is the whole film: the stills are not
        # priced here at all, so a film's image spend is outside the estimate rather than
        # inside it as a zero. A caller that reads this as "the whole cost" would be making
        # the claim the caveat exists to stop.
        "unpriced": unpriced,
        "caveat": unpriced_caveat(unpriced),
        "complete": not unpriced,
    }
