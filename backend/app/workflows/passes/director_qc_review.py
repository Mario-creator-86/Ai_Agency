"""A film whose QC failed is read by the Director, never left to a mechanical redo (2026-10-10).

Film babcf272: its QC report d4ea68d2 failed at 11:04 UTC and the mechanical repair redid scenes
1 and 2 unasked, retiring the takes the Owner had approved; nothing was delivered and he
stopped the studio. Since the same day nothing is redone before the Director has read a failed
report and decided (`app.runbook.stages.director_decides_failed_film`). A report nobody put
before her (d4ea68d2 itself, after the restart) or one she could not decide yet (no model, an
answer that did not validate twice: the report then waits in her inbox) would stand forever:
the day's QC only measures films not measured yet.

So this pass finds each film whose newest finished render's newest QC report FAILED and has no
final decision of hers (`app.media.director_qc.decision_state`), and queues the film's
continuation (FILM_CONTINUE, `app.services.queue_film_continue`): the walk reads the report,
she decides, and what she decided is carried out under his rules. A REPAIR of hers that waits
on a take bought for it (BOUGHT_WAITING) is queued again once that take is approved (``ready``:
a still the vendor delivered late and the gate approved has no look of his to queue it), and
when candidates bought for it that a gate refused wait for her own look (``look``: the walk
shows them to her, 2026-10-10, the Owner: she decides whether the picture is good); one whose
wait lapsed (his no, an expired question) is hers again and queued like an undecided one.

One continuation per report and run of it (the key counts the continuations that already ran
for the report). Once she was asked, the next waits `RETRY_MINUTES`; a walk that never reached
her (refused by safe mode or his mode, the film busy) waits twice as long each time, up to
`MAX_WAIT_MINUTES`, and does not count as a try (2026-10-10 review: two dozen walks refused by
his mode used up the tries, and the film was dropped with no note anywhere). After `MAX_TRIES`
rounds that reached her without a decision the film waits in her inbox (each such round left
the note there, `wait_for_director`) until a new report or his answer moves it. Only reports
of the last `LOOKBACK_DAYS`: a film that failed weeks ago is not woken up to be published or
bought for. A film closed, a film with a continuation queued or at work, a studio outside
PRODUCTION: nothing is queued. Nothing here buys or decides; the walk asks for anything paid
under his rule, behind his stop, safe mode and his mode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass

#: How long after she was last asked (or a walk last ran) she is asked again.
RETRY_MINUTES = 60
#: The longest wait after walks that never reached her (doubling from `RETRY_MINUTES`).
MAX_WAIT_MINUTES = 24 * 60
#: How old a failed report may be and still be put before her by this pass.
LOOKBACK_DAYS = 7
#: How many rounds that reached her without a decision a report gets before it waits in her
#: inbox for good.
MAX_TRIES = 24
#: The continuation's cause, per report: the walk records it on `runbook.film_continued`.
CAUSE_PREFIX = "director_qc:"
#: How long after her newest decision a walk's record still belongs to the walk that produced
#: it: that walk heard her (`_heard_until`); a later one did not.
HEARD_WINDOW = timedelta(minutes=5)


def _heard_until(asked_at: str) -> str:
    """The ISO moment until which a walk's record counts as the walk that produced her
    newest decision (``asked_at`` + `HEARD_WINDOW`); ``asked_at`` itself when it is not a
    moment (no decision yet: every walk is unheard)."""
    try:
        moment = datetime.fromisoformat(asked_at)
    except (TypeError, ValueError):
        return asked_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment + HEARD_WINDOW).isoformat()


#: A continuation of the film already queued or at work: it reads the report itself.
PENDING_TASK_STATES = ("QUEUED", "RETRYING", "CLAIMED", "RUNNING")


def _his_card_open(session: Any, storyboard_id: str) -> bool:
    """Whether the film's paid-redo cap card still waits for the Owner."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.decisions.models import OwnerDecision  # noqa: PLC0415
    from app.decisions.producers.redo_cap import dedupe_key  # noqa: PLC0415

    return (
        session.scalar(
            select(OwnerDecision.id).where(
                OwnerDecision.dedupe_key == dedupe_key(storyboard_id),
                OwnerDecision.status.in_(("PENDING", "WAITING_FOR_OWNER_ACTION")),
            )
        )
        is not None
    )


#: How long after a walk that could not publish a film accepted under the cap the next one
#: waits (doubling after each).
PUBLISH_RETRY_MINUTES = 10


def _walks_since(session: Any, storyboard_id: str, cause: str, viewing_id: str) -> list[datetime]:
    """When the film's walks under ``cause`` ended since the refused viewing ``viewing_id``
    was written, oldest first."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.media.models import EditorialReview  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    review = session.get(EditorialReview, viewing_id)
    since = str(review.created_at) if review is not None else ""
    moments: list[datetime] = []
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == "runbook.film_continued",
            DomainEvent.aggregate_id == storyboard_id,
        )
    ):
        if (event.payload or {}).get("cause") != cause or str(event.timestamp) <= since:
            continue
        moment = datetime.fromisoformat(str(event.timestamp))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moments.append(moment)
    return sorted(moments)


def _refused_viewing_to_publish(session: Any, asset_id: str) -> str | None:
    """The id of the newest viewing that refused a film accepted under the Owner's cap and
    not out on a channel, else None: its walk is queued once per such viewing (the key names
    it), and `runbook.stages._publish_one` has her view the film again, as notes."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.agents.editorial import accepted_under_cap  # noqa: PLC0415
    from app.media.models import EditorialReview  # noqa: PLC0415
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    newest = session.scalar(
        select(EditorialReview)
        .where(EditorialReview.media_asset_id == asset_id)
        .order_by(EditorialReview.created_at.desc())
    )
    if newest is None or str(newest.verdict) == "APPROVE":
        return None
    if accepted_under_cap(session, asset_id) is None:
        return None
    out = session.scalar(
        select(PublicationRecord.id).where(
            PublicationRecord.media_asset_id == asset_id,
            PublicationRecord.status.in_(("PUBLISHED", "SCHEDULED", "REMOTE_CONFIRMED")),
        )
    )
    return None if out is not None else str(newest.id)


def _developer_waits(session: Any, report_id: str) -> bool:
    """Whether this failed report waits on the developer: its only fix, a free one, was made
    `runbook.stages.FREE_FIXES_PER_FILM` times without curing a measured serious defect, and
    the Director noted it for the developer (`runbook.stages._free_fix_defect_note`). She is
    not asked again about the same report every hour; a new report (a new film) reads anew."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.agents.director import DEVELOPER_DEFECT_KIND  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.runbook.stages import FREE_FIX_NOTE_SUBJECT  # noqa: PLC0415

    for row in session.scalars(
        select(AgentMessage).where(AgentMessage.subject.like(f"{FREE_FIX_NOTE_SUBJECT}%"))
    ):
        body = row.body_json if isinstance(row.body_json, dict) else {}
        if body.get("kind") == DEVELOPER_DEFECT_KIND and body.get("report_id") == report_id:
            return True
    return False


@watchdog_pass("director_qc_review", order=160, on_error={"queued": []})
def queue_director_reviews(context: WatchdogContext) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.agents.editorial import accepted_under_cap  # noqa: PLC0415
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.director_qc import decision_state  # noqa: PLC0415
    from app.media.models import QualityControlReport, Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.models import DomainEvent, OwnerPolicy  # noqa: PLC0415
    from app.services import FILM_CONTINUE_TASK, queue_film_continue  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    owed: list[tuple[str, str, str, str]] = []
    now = datetime.now(UTC)
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    with Session(context.engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if str(getattr(policy, "environment", None) or "TEST") != "PRODUCTION":
            return {"queued": []}
        newest: dict[str, str] = {}
        for job in session.scalars(
            select(VideoRenderJob)
            .where(
                VideoRenderJob.status == "COMPLETED",
                VideoRenderJob.output_asset_id.is_not(None),
            )
            .order_by(VideoRenderJob.finished_at, VideoRenderJob.started_at)
        ):
            newest[str(job.storyboard_id)] = str(job.output_asset_id)
        busy = {
            str((task.payload or {}).get("storyboard_id") or "")
            for task in session.scalars(
                select(TaskQueueItem).where(
                    TaskQueueItem.task_type == FILM_CONTINUE_TASK,
                    TaskQueueItem.status.in_(PENDING_TASK_STATES),
                )
            )
        }
        for storyboard_id, asset_id in sorted(newest.items()):
            if storyboard_id in busy:
                continue
            board = session.get(Storyboard, storyboard_id)
            if board is None:
                continue
            if board.status == "REJECTED" and accepted_under_cap(session, asset_id) is None:
                # Closed by her, or a viewing refused it: nothing to decide. A film accepted
                # under the Owner's cap that a viewing refused is not closed (2026-10-15,
                # 13:10Z: the pass skipped 2d276038 on that status and nothing moved).
                continue
            if _his_card_open(session, storyboard_id):
                # His cap stopped her repair and his card asks what becomes of the film
                # (`decisions.producers.redo_cap`): she is not asked again until he answers.
                continue
            report = session.scalar(
                select(QualityControlReport)
                .where(
                    QualityControlReport.media_asset_id == asset_id,
                    QualityControlReport.status != "INVALIDATED",
                )
                .order_by(QualityControlReport.verified_at.desc())
                .limit(1)
            )
            if report is not None and report.status == "PASSED":
                # Accepted under the Owner's cap (the PASSED report her decision stands on),
                # then refused by her viewing on the publish path (12:49Z, 2d276038): walked
                # again once per such viewing, so the walk publishes it, her viewing being
                # notes now, not a veto (`editorial_review`); once out, nothing more.
                viewing = _refused_viewing_to_publish(session, asset_id)
                shipped = accepted_under_cap(session, asset_id) if viewing else None
                if viewing and shipped and shipped.get("report_id"):
                    failed_report = str(shipped["report_id"])
                    cause = f"{CAUSE_PREFIX}{failed_report}"
                    # The walks under this cause since the refused viewing: the next waits
                    # twice as long after each (13:31Z: the first walk found «niciun material
                    # aprobat de QC» on the queue's own reading of that refusal), so a
                    # publication that cannot go out is neither a loop nor forgotten.
                    walks = _walks_since(session, storyboard_id, cause, viewing)
                    wait = min(
                        PUBLISH_RETRY_MINUTES * 2 ** max(len(walks) - 1, 0), MAX_WAIT_MINUTES
                    )
                    key = f"film-continue-{storyboard_id}-publish-again-{viewing}-{len(walks)}"
                    standing = session.scalar(
                        select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key)
                    )
                    recent = walks and now - walks[-1] < timedelta(minutes=wait)
                    if standing is None and not recent:
                        owed.append((storyboard_id, key, cause, failed_report))
                continue
            if report is None or report.status != "FAILED" or str(report.verified_at) < since:
                continue
            if _developer_waits(session, str(report.id)):
                continue
            state = decision_state(context.engine, str(report.id))
            if state["final"] and not (state["pending"] and (state["ready"] or state["look"])):
                continue
            cause = f"{CAUSE_PREFIX}{report.id}"
            runs = sorted(
                str(event.timestamp)
                for event in session.scalars(
                    select(DomainEvent).where(
                        DomainEvent.event_type == "runbook.film_continued",
                        DomainEvent.aggregate_id == storyboard_id,
                    )
                )
                if (event.payload or {}).get("cause") == cause and event.timestamp
            )
            if int(state["tries"]) >= MAX_TRIES:
                continue  # it waits in her inbox; a new report or his answer moves it
            # Asked before (a wait of hers, or a walk that ran): not again before RETRY_MINUTES,
            # and after walks that never reached her (safe mode, his mode, the film busy) twice
            # as long each time, so a refusal is neither a loop nor the end of the film.
            asked_at = str(state["last_at"] or "")
            # A walk that ended within HEARD_WINDOW of her newest decision is the walk that
            # produced it (the decision is written first, the walk's record seconds later):
            # heard, not unheard. 11:29:53Z, 2d276038: the walk's record came 19 ms after her
            # decision and was counted as a walk that never reached her, so the lapsed repair
            # waited the hour after the 11:42Z restart while nothing moved.
            heard_until = _heard_until(asked_at)
            unheard = sum(1 for moment in runs if moment > heard_until)
            moments = [moment for moment in (*runs, asked_at) if moment]
            # What her REPAIR waited for has come (``ready``: a take bought for her list is
            # approved; ``look``: candidates wait for her own look) and no walk has read it
            # since her decision: carried on now, not an hour from now. 2026-10-15, 2d276038:
            # her repair's new still was approved at 10:14Z and the film stood until the
            # hour after her 10:24Z decision had passed, the Owner asking where the
            # publication was. A walk that ran since (``unheard``) is throttled as before, so
            # a film the walk cannot move is not walked every ten minutes.
            # A repair that lapsed (what was bought for it came back refused, his no) is hers
            # again on the same terms: read now, once; walked since, it waits the hour.
            carried_on_now = (state["ready"] or state["look"] or state["lapsed"]) and unheard == 0
            if moments and not carried_on_now:
                last = datetime.fromisoformat(max(moments))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                wait = min(RETRY_MINUTES * 2 ** min(max(unheard - 1, 0), 10), MAX_WAIT_MINUTES)
                if now - last < timedelta(minutes=wait):
                    continue
            key = f"film-continue-{storyboard_id}-director-qc-{report.id}-{len(runs)}"
            standing = session.scalar(
                select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key)
            )
            if standing is not None:
                continue
            owed.append((storyboard_id, key, cause, str(report.id)))
    if not owed:
        return {"queued": []}
    done: list[str] = []
    with Session(context.engine) as session, session.begin():
        # Written only when something is owed, so a quiet pass takes no write lock.
        lock_for_write(session)
        for storyboard_id, key, cause, report_id in owed:
            if queue_film_continue(
                session, storyboard_id, key=key, payload={"cause": cause, "report_id": report_id}
            ):
                done.append(storyboard_id)
    return {"queued": done}
