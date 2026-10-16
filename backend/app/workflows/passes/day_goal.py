"""The day's goal keeps the day going: a short and a serial episode published, or a problem
only the Owner can solve (2026-10-15, 15:20Z).

«Noi ar trebui să avem un flux și să ne oprim doar atunci când am publicat ceva. Ăsta este rolul
agenției într-o zi, să publice un short și un serial. Ziua se oprește când apare o problemă peste
care nu poate trece — un bug, ceva ce are nevoie de intervenția mea — sau după ce cele două au
fost publicate. Altfel nu are voie să se oprească și trebuie să rezolve problema.»

Until this pass a day's run ended when its stages ended: a script refused by its form, a topic
sent back to research, an episode refused by the Director's reading all waited for the next
morning's run, and the day closed with nothing out. On 2026-10-15 the Owner pressed «Pornește
rularea de azi» three times by hand; this pass presses it for him. Every `WATCHDOG` fire it
reads the business day's goal — one factual short and one serial episode out on a channel today
(`day_goal`) — and, while it is not met, queues the day's run again (the same queued run his
button queues, ``manual``), once the last run finished and nothing of the day is at work: no
run queued or running, no film continuation at work (the serial's filming is the day's own
work, walked by the worker), `DAY_GOAL_GAP_MINUTES` after the last run ended. It stops when
the day cannot be moved by another run: his autonomy stop, safe mode, the daily budget spent,
or `DAY_GOAL_RUNS_PER_DAY` runs queued by this pass already (the same refusal many times over
is a problem for him: a letter to the Owner, once a day).

The budget is spent when nothing is left of it, and also when a film's next round could not be
held within what is left (`shooting_sheet.STEP_HOLD_REFUSED_EVENT`, 2026-10-16). Before, a
day whose remaining budget could not hold a film's step still counted as unspent: it queued
six more runs that each met the same refusal, then wrote him «6 rulări» for what was his
budget. A spent budget is money, so it reaches him as the film's budget card when his rule
raises one (`decisions.sources.film_budget`), never as a letter from this pass.

Nothing here buys or decides: the run it queues asks for anything paid under his rule, behind
his stop, safe mode and his mode, exactly as his own button does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How many runs this pass may queue for one business day before the day is his problem.
DAY_GOAL_RUNS_PER_DAY = 6
#: How long after the last run ended the next is queued (the worker's own passes, the serial's
#: continuation and a vendor's late delivery get their turn in between).
DAY_GOAL_GAP_MINUTES = 5
#: The cause written on the queued run and on its letter.
CAUSE = "day_goal"
#: Publication states that count as «out on a channel» (`runbook.stages.OUT_ON_THE_CHANNEL`).
OUT = ("PUBLISHED", "PUBLISHED_SIMULATED", "SCHEDULED", "REMOTE_CONFIRMED")
#: The serial's series key (`media.prompt_agent.SERIAL_SERIES_KEY`).
SERIAL_SERIES_KEY = "office_serial"
LETTER_SUBJECT = "Ziua nu și-a atins ținta și nu mai pornește singură"


def day_goal(session: Any, date_iso: str, timezone: str = "UTC") -> dict[str, Any]:
    """What the business day ``date_iso`` has out on a channel: ``{"short": n, "serial": n,
    "met": bool}`` — the Owner's goal is one of each (a publication belongs to the business
    day of its ``created_at`` in the studio's timezone, `story.services.business_date`)."""
    from datetime import datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.media.models import Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.publishing.models import PublicationRecord  # noqa: PLC0415
    from app.story.services import business_date  # noqa: PLC0415

    short = serial = 0
    for record, board in session.execute(
        select(PublicationRecord, Storyboard)
        .join(VideoRenderJob, VideoRenderJob.output_asset_id == PublicationRecord.media_asset_id)
        .join(Storyboard, Storyboard.id == VideoRenderJob.storyboard_id)
        .where(PublicationRecord.status.in_(OUT))
    ):
        try:
            moment = datetime.fromisoformat(str(record.created_at))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        if business_date(timezone, moment) != date_iso:
            continue
        if str(board.series_key or "").strip().lower() == SERIAL_SERIES_KEY:
            serial += 1
        else:
            short += 1
    return {"short": short, "serial": serial, "met": short >= 1 and serial >= 1}


def _runs_queued_today(session: Any, date_iso: str) -> int:
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    return int(
        session.scalar(
            select(func.count(TaskQueueItem.id)).where(
                TaskQueueItem.idempotency_key.like(f"day-goal-{date_iso}-%")
            )
        )
        or 0
    )


def _last_run_ended(session: Any, date_iso: str) -> str | None:
    """When the business day's newest finished run ended (ISO), None with no finished run or
    while one runs."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.runbook.models import DailyRun  # noqa: PLC0415

    newest = session.scalar(
        select(DailyRun)
        .where(DailyRun.business_date == date_iso)
        .order_by(DailyRun.started_at.desc())
    )
    if newest is None:
        return ""
    if newest.status == "RUNNING" or not newest.finished_at:
        return None
    return str(newest.finished_at)


def _film_at_work(session: Any) -> bool:
    from sqlalchemy import select  # noqa: PLC0415

    from app.services import FILM_CONTINUE_TASK  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    return (
        session.scalar(
            select(TaskQueueItem.id).where(
                TaskQueueItem.task_type == FILM_CONTINUE_TASK,
                TaskQueueItem.status.in_(("QUEUED", "RETRYING", "CLAIMED", "RUNNING")),
            )
        )
        is not None
    )


def _budget_spent(engine: Any) -> bool:
    """Whether the daily budget can buy nothing more today: none of it is left, or the newest
    round the budgets refused today (`STEP_HOLD_REFUSED_EVENT`) still needs more than its
    period has left now. Raised by the Owner since, the round fits and the day goes on."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.economy.budget import budget_status  # noqa: PLC0415
    from app.media.shooting_sheet import STEP_HOLD_REFUSED_EVENT  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    try:
        periods = {str(p["period"]): p for p in budget_status(engine)["budgets"]}
    except Exception:  # noqa: BLE001 - a budget that cannot be read stops nothing here
        return False
    daily = periods.get("DAILY")
    if daily is None:
        return False
    if int(daily["remaining_usd_micros"]) <= 0:
        return True
    with Session(engine) as session:
        refused = session.scalar(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == STEP_HOLD_REFUSED_EVENT,
                DomainEvent.timestamp >= str(daily["since"]),
            )
            .order_by(DomainEvent.sequence.desc())
            .limit(1)
        )
    payload = refused.payload if refused is not None and isinstance(refused.payload, dict) else {}
    period = periods.get(str(payload.get("period") or ""))
    if period is None:
        return False
    return int(payload.get("need_usd_micros") or 0) > int(period["remaining_usd_micros"])


def _letter_once(session: Any, date_iso: str, why: str, goal: dict[str, Any]) -> bool:
    from app.agents.messages import post_message, repeated_letter  # noqa: PLC0415

    text = (
        f"Ziua {date_iso} nu și-a atins ținta (un short și un episod al serialului publicate): "
        f"{goal['short']} short, {goal['serial']} episod. Studioul a pornit rularea zilei de "
        f"{DAY_GOAL_RUNS_PER_DAY} ori singur și nu mai pornește alta: {why}. Ce a oprit fiecare "
        "rulare este în registrul zilei; dacă este o problemă de cod, o repar eu; dacă vrei încă "
        "o încercare azi, apasă «Pornește rularea de azi»."
    )
    if repeated_letter(session, subject=LETTER_SUBJECT, body_text=text, to_owner=True):
        return False
    post_message(
        session,
        intent="ESCALATE",
        subject=LETTER_SUBJECT,
        body={"kind": CAUSE, "date": date_iso, "goal": goal, "why": why},
        body_text=text,
        to_owner=True,
    )
    return True


@watchdog_pass("day_goal", order=190, on_error={"queued": None})
def keep_the_day_going(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.db import lock_for_write  # noqa: PLC0415
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.runbook.services import (  # noqa: PLC0415 - the runbook imports the studio
        DAILY_RUN_TASK,
        pending_daily_run,
        safe_mode_state,
        stop_requested,
    )
    from app.services import utc_now  # noqa: PLC0415
    from app.story.services import business_date  # noqa: PLC0415
    from app.workflows.services import enqueue_task  # noqa: PLC0415

    engine = context.engine
    settings = context.settings
    today = business_date(str(getattr(settings, "timezone", "") or "UTC"))
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if str(getattr(policy, "environment", None) or "TEST") != "PRODUCTION":
            return {"queued": None, "why": "not production"}
        if policy is not None and getattr(policy, "autonomy_stopped", False):
            return {"queued": None, "why": "autonomy stopped"}
        goal = day_goal(session, today, str(getattr(settings, "timezone", "") or "UTC"))
        if goal["met"]:
            return {"queued": None, "goal": goal, "why": "met"}
        ended = _last_run_ended(session, today)
        queued_today = _runs_queued_today(session, today)
        film_busy = _film_at_work(session)
    if ended is None:
        return {"queued": None, "goal": goal, "why": "a run is on its way"}
    if film_busy:
        return {"queued": None, "goal": goal, "why": "a film is at work"}
    if pending_daily_run(engine) is not None:
        return {"queued": None, "goal": goal, "why": "a run is queued"}
    if stop_requested(engine) or safe_mode_state(engine).get("active"):
        return {"queued": None, "goal": goal, "why": "stopped"}
    if ended:
        last = datetime.fromisoformat(ended)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if datetime.now(UTC) - last < timedelta(minutes=DAY_GOAL_GAP_MINUTES):
            return {"queued": None, "goal": goal, "why": "the last run just ended"}
    if _budget_spent(engine):
        # Money is his card, not a letter (2026-10-12): the film waiting on the budget carries
        # it when his rule raises one, and another run would meet the same refusal.
        return {
            "queued": None,
            "goal": goal,
            "why": "bugetul zilnic este cheltuit: runda următoare nu încape în ce a rămas",
            "letter": False,
            "budget": True,
        }
    stop_why = None
    if queued_today >= DAY_GOAL_RUNS_PER_DAY:
        stop_why = f"{DAY_GOAL_RUNS_PER_DAY} rulări pornite de studio azi, fără cele două publicări"
    if stop_why:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            wrote = _letter_once(session, today, stop_why, goal)
        return {"queued": None, "goal": goal, "why": stop_why, "letter": wrote}
    key = f"day-goal-{today}-{queued_today + 1}"
    task = enqueue_task(
        engine,
        DAILY_RUN_TASK,
        {"manual": True, "requested_at": utc_now(), "date": today, "cause": CAUSE},
        priority=9,
        max_attempts=1,
        idempotency_key=key,
    )
    return {"queued": task["id"], "goal": goal, "run": queued_today + 1}
