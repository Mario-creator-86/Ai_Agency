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
raises one (`decisions.sources.film_budget`), never as a letter from this pass. It is read film
by film (SAFE-003, 2026-10-16): the day stops on the budget only when every film it still owes
— the short, the episode — has its own newest round refused over what is left; a film whose
round still fits, or that was never refused, keeps the day going.

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


#: The films the day owes, as `day_goal` counts them, and how the budget's reason names them.
OWED_FILMS = {"short": "shortul", "serial": "episodul serialului"}


def _budget_spent(engine: Any, owed: list[str]) -> list[str]:
    """The films the day still owes (``owed``: "short", "serial") that the daily budget cannot
    carry now: every one of them when none of the budget is left; else each whose own newest
    round the budgets refused today (`STEP_HOLD_REFUSED_EVENT`, per storyboard) still needs
    more than its period has left. Raised by the Owner since, the round fits and the film goes
    on. The day stops on the budget only when every owed film is in this list (SAFE-003,
    2026-10-16): until then the newest refusal of any film stopped the whole day, and a short
    whose next round still fitted waited, with no run, card or reason, behind the episode's.

    Only a film the day can still make counts, either way: a refusal of a film that is closed
    (`shooting_sheet.film_is_closed`: retired by the Director, replaced by a newer board of its
    script, closed by the Owner, or out on the channel) is not the round the next run needs. Its
    round that fits kept a spent day going until the run cap wrote him «6 rulări», and its round
    over what is left held back a live film of its kind that was never refused (review of
    2026-10-16).

    A refusal whose storyboard the studio cannot find is read as before, for every owed film:
    the day cannot tell which film it was."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.economy.budget import budget_status  # noqa: PLC0415
    from app.media.models import Storyboard  # noqa: PLC0415
    from app.media.shooting_sheet import (  # noqa: PLC0415
        STEP_HOLD_REFUSED_EVENT,
        film_is_closed,
    )
    from app.models import DomainEvent  # noqa: PLC0415

    if not owed:
        return []
    try:
        periods = {str(p["period"]): p for p in budget_status(engine)["budgets"]}
    except Exception:  # noqa: BLE001 - a budget that cannot be read stops nothing here
        return []
    daily = periods.get("DAILY")
    if daily is None:
        return []
    if int(daily["remaining_usd_micros"]) <= 0:
        return list(owed)
    newest: dict[str, dict[str, Any] | None] = {}
    with Session(engine) as session:
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == STEP_HOLD_REFUSED_EVENT,
                DomainEvent.timestamp >= str(daily["since"]),
            )
            .order_by(DomainEvent.sequence.desc())
        ):
            board_id = str(event.aggregate_id or "")
            if board_id in newest:
                continue  # an older refusal of a film whose newest is already read
            board = session.get(Storyboard, board_id) if board_id else None
            if board is not None and film_is_closed(session, board_id):
                newest[board_id] = None  # not a film the day can still make
                continue
            kinds = (
                list(owed)
                if board is None
                else [
                    "serial"
                    if str(board.series_key or "").strip().lower() == SERIAL_SERIES_KEY
                    else "short"
                ]
            )
            payload = event.payload if isinstance(event.payload, dict) else {}
            newest[board_id] = {"kinds": kinds, "payload": payload, "known": board is not None}
    over: set[str] = set()
    fits: set[str] = set()
    for refusal in newest.values():
        if refusal is None:
            continue
        payload = refusal["payload"]
        period = periods.get(str(payload.get("period") or ""))
        if period is None:
            continue
        if int(payload.get("need_usd_micros") or 0) > int(period["remaining_usd_micros"]):
            over.update(refusal["kinds"])
        elif refusal["known"]:
            # Another film of the same kind whose round fits now: that kind goes on.
            fits.update(refusal["kinds"])
    return [kind for kind in owed if kind in over and kind not in fits]


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
    owed = [kind for kind in OWED_FILMS if int(goal.get(kind) or 0) < 1]
    waiting = _budget_spent(engine, owed)
    if owed and waiting == owed:
        # Money is his card, not a letter (2026-10-12): the film waiting on the budget carries
        # it when his rule raises one, and another run would meet the same refusal. Only when
        # every film the day still owes waits on it: a film whose round fits keeps the day
        # going (SAFE-003).
        films = " și ".join(OWED_FILMS[kind] for kind in waiting)
        return {
            "queued": None,
            "goal": goal,
            "why": (
                f"bugetul zilnic este cheltuit: runda următoare pentru {films} nu încape în ce "
                "a rămas"
            ),
            "letter": False,
            "budget": True,
            "waiting_on_budget": waiting,
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
