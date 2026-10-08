"""The Owner's policy, read again before every vendor request of a paid step bought unasked.

2026-10-04, 05:02 UTC: the day's stills step of the LHC film (storyboard 4d0da5d9) started under
AUTONOMOUS_CEO with his paid-media rule MODE. At 05:08:27 the mode was lowered to MANUAL from the
page's mode buttons (event 7525, direction REDUCTION). The step asked `may_act` once, at its
start, and between scenes read only the autonomy stop, so scenes 4 to 9 were still submitted from
05:09:04 to 05:21:18: 6 requests x 18 credits = 108 credits bought under a mode that forbade them.
51_AUTONOMY_MODE_SEMANTICS.md, «Lowering autonomy»: «Immediate and safe: future work uses lower
mode; active workflow external writes respect current policy at execution time».

`PurchaseGuard` is that reading inside a step. Before each vendor request (a stills request, a
re-roll, a shot, a clip-QC retry, a redo's re-roll) it asks the Policy Kernel the same question the
step asked at its start, with ``ask_owner=False``: nothing is written, no question is raised, and
no yes of his is read or spent (`services._ask_or_spend`). The step goes on when the answer is
still ALLOWED; when the step was bought on his yes for this plan and the kernel now only says he
would be asked (NEEDS_APPROVAL: the question he already answered); and when the step is his own
press on the sheet and the answer is one that speaks about agents acting unasked
(`media.services.OWNER_PRESS_PASSES`). Anything else (MANUAL, SUPERVISED with a T3 step, a
stricter paid-media rule, a removed daily budget in PRODUCTION, safe mode, the stop) stops the
step before the request: what was bought is kept and settled by the step as usual, the rest is not
bought, and the stop is recorded once (`MODE_STOP_EVENT`) with the sentence the Owner reads.

`unasked_refusal` is the same reading before a step starts on the unasked path (the day's
staircase, FILM_CONTINUE, the day's QC repairs): a step the kernel refuses outright is refused
before the vendor's balance is read, so MANUAL no longer raises a «top up the account» card for a
step the mode would refuse anyway. A question (NEEDS_APPROVAL) is not a refusal: the balance is
still read before he is asked, so he is never asked to buy what the account cannot pay for.

Comments in English; every sentence for the Owner in Romanian.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

#: A paid step stopped before a vendor request because the Owner's policy no longer let it buy:
#: {step, action, storyboard_id, scene_number, status, mode, reason_ro, mode_changed_sequence,
#: mode_changed_at, by_yes, unasked}.
MODE_STOP_EVENT = "media.paid_step_stopped_by_mode"
#: The event the Owner's mode change writes (`services.change_autonomy_mode`).
MODE_CHANGED_EVENT = "owner.autonomy_mode_changed"
#: What a stop says about what was already bought.
REST_NOT_BOUGHT = "ce s-a cumpărat până atunci rămâne; restul nu s-a cumpărat."
#: The studio's zone when the caller names none (`Settings.timezone`'s default).
DEFAULT_TIMEZONE = "Europe/Bucharest"


def _verdict(
    engine: Engine,
    action: str,
    *,
    requester: str,
    subject: str,
    cost_usd: float | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """`may_act`'s answer with ``ask_owner=False``: read, never written, never spent."""
    from app.services import may_act  # noqa: PLC0415 - services imports media

    with Session(engine) as session:
        verdict: dict[str, Any] = may_act(
            session,
            action,
            requester=requester,
            subject=subject,
            cost_usd=cost_usd,
            context=dict(context),
            ask_owner=False,
        )
        # Nothing may stay of this reading: the session is closed without a commit.
        session.rollback()
    return verdict


def unasked_refusal(
    engine: Engine,
    action: str,
    *,
    subject: str,
    context: dict[str, Any],
    cost_usd: float | None,
    requester: str = "video_editor",
) -> dict[str, Any] | None:
    """The kernel's verdict when it refuses an unasked purchase outright, else None.

    NEEDS_APPROVAL is None here: the step goes on to read the balance and then asks him with the
    film's name and price on the question (`may_act` inside the step)."""
    verdict = _verdict(
        engine, action, requester=requester, subject=subject, cost_usd=cost_usd, context=context
    )
    if verdict["allowed"] or verdict["status"] == "NEEDS_APPROVAL":
        return None
    return verdict


def _local_clock(stamp: str | None, timezone: str | None) -> str | None:
    """«08:08», the Owner's wall clock for an event's UTC timestamp."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(timezone or DEFAULT_TIMEZONE)
    except Exception:  # noqa: BLE001 - an unknown zone reads as UTC, named
        return moment.astimezone(UTC).strftime("%H:%M UTC")
    return moment.astimezone(zone).strftime("%H:%M")


def _mode_change_since(engine: Engine, since: str) -> dict[str, Any] | None:
    """The newest change of the mode recorded at or after ``since`` (UTC ISO), or None."""
    from app.models import DomainEvent  # noqa: PLC0415

    with Session(engine) as session:
        row = session.scalar(
            select(DomainEvent)
            .where(DomainEvent.event_type == MODE_CHANGED_EVENT, DomainEvent.timestamp >= since)
            .order_by(DomainEvent.sequence.desc())
            .limit(1)
        )
        if row is None:
            return None
        payload = row.payload if isinstance(row.payload, dict) else {}
        return {"sequence": row.sequence, "timestamp": row.timestamp, **payload}


def stop_words(verdict: dict[str, Any], change: dict[str, Any] | None, timezone: str | None) -> str:
    """Why the step stopped, in the Owner's words, ending with what happened to the rest."""
    from app.wording import autonomy_mode  # noqa: PLC0415

    if change is not None and change.get("direction") == "REDUCTION":
        at = _local_clock(change.get("timestamp"), timezone)
        when = f" la {at}" if at else ""
        return (
            f"Modul de autonomie a fost coborât la {autonomy_mode(change.get('autonomy_mode'))}"
            f"{when}, în timpul pasului: {REST_NOT_BOUGHT}"
        )
    said = " ".join(str(verdict.get("reason") or "").split()).rstrip(".")
    if not said:
        said = "Politica ta nu mai lasă studioul să cumpere singur acest pas"
    return f"{said}. Politica s-a schimbat în timpul pasului: {REST_NOT_BOUGHT}"


@dataclass
class PurchaseGuard:
    """One paid step's reading of the Owner's policy before each of its vendor requests.

    Build it with `PurchaseGuard.after` from the verdict that let the step start. ``unasked`` is
    False only for his own press on the sheet or on a redo; ``by_yes`` says the step spent his
    yes for this plan. `stop_reason` answers None while the next request may be sent; once it
    stops it keeps answering the same sentence, so every later scene of the step says it too.
    """

    engine: Engine
    action: str
    step: str
    storyboard_id: str
    requester: str
    cost_usd: float | None
    context: dict[str, Any]
    by_yes: bool
    unasked: bool
    correlation_id: str
    timezone: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    stopped: dict[str, Any] | None = None

    @classmethod
    def after(
        cls,
        engine: Engine,
        verdict: dict[str, Any],
        *,
        action: str,
        step: str,
        storyboard_id: str,
        requester: str,
        cost_usd: float | None,
        context: dict[str, Any],
        unasked: bool,
        correlation_id: str,
        timezone: str | None = None,
    ) -> PurchaseGuard:
        return cls(
            engine=engine,
            action=action,
            step=step,
            storyboard_id=storyboard_id,
            requester=requester,
            cost_usd=cost_usd,
            context=dict(context),
            by_yes=bool(verdict.get("allowed") and verdict.get("approval_id")),
            unasked=unasked,
            correlation_id=correlation_id,
            timezone=timezone,
        )

    def _goes_on(self, verdict: dict[str, Any]) -> bool:
        from app.media.services import OWNER_PRESS_PASSES  # noqa: PLC0415 - services imports us

        if verdict["allowed"]:
            return True
        status = str(verdict["status"])
        if self.by_yes and status == "NEEDS_APPROVAL":
            # The question the kernel would ask is the one he answered for this plan.
            return True
        return not self.unasked and status in OWNER_PRESS_PASSES

    def stop_reason(self, scene_number: int | None = None) -> str | None:
        """None while the next vendor request may be sent; else why not, recorded once."""
        if self.stopped is not None:
            return str(self.stopped["reason_ro"])
        verdict = _verdict(
            self.engine,
            self.action,
            requester=self.requester,
            subject=self.storyboard_id,
            cost_usd=self.cost_usd,
            context=self.context,
        )
        if self._goes_on(verdict):
            return None
        change = _mode_change_since(self.engine, self.started_at)
        reason = stop_words(verdict, change, self.timezone)
        self.stopped = {
            "step": self.step,
            "action": self.action,
            "storyboard_id": self.storyboard_id,
            "scene_number": scene_number,
            "status": verdict["status"],
            "mode": verdict.get("mode"),
            "reason_ro": reason,
            "kernel_reason": verdict.get("reason"),
            "mode_changed_sequence": (change or {}).get("sequence"),
            "mode_changed_at": (change or {}).get("timestamp"),
            "by_yes": self.by_yes,
            "unasked": self.unasked,
        }
        self._record()
        return reason

    def _record(self) -> None:
        from app.db import lock_for_write  # noqa: PLC0415
        from app.services import append_event  # noqa: PLC0415 - services imports media

        with Session(self.engine) as session, session.begin():
            lock_for_write(session)
            append_event(
                session,
                MODE_STOP_EVENT,
                "storyboard",
                self.storyboard_id,
                1,
                dict(self.stopped or {}),
                self.correlation_id,
            )
