"""Decisions whose work is over, closed with what became of them (2026-10-11).

A DirectorDecision stays OPEN until it is reviewed, and until this day only the Owner's own
button reviewed one (`runbook.router` → `command.review_decision`). Nothing closed a decision
when the HANDOFF it sent was resolved, nor when the review of it was itself decided; on the
studio's copy of 2026-10-11 ten were OPEN, five of them from 09-12..17, and every one kept its
matter out of the Director's loop (a matter under an open decision is not raised again).

A decision's work is over when:

- the letter it sent is closed with the work done (its addressee answered a HANDOFF with
  done=true, or someone resolved it), and no review of it is still to come: its outcome is
  that letter's resolution. A decision whose review after N films (or a date) is not due yet
  stays OPEN until the review measures it: closed earlier, its matter is free again at the
  next loop and handed to the same department before anything was measured;
- a later ``review_<its matter>`` decision was reviewed: its outcome is that review's;
- it is one of her repairs and the DIRECTOR_REPAIR task that should have closed it ended
  without doing so (the process died under it), or was never queued: its outcome says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.repairs import (
    APPLIED,
    RepairContext,
    finding,
    outcome,
    register_repair,
)
from app.agents.repairs.desk import close_decision, fingerprint
from app.db import lock_for_write
from app.wording import count

#: A repair decision whose task cannot be found after this long was never queued.
UNQUEUED_AFTER_MINUTES = 60
#: Task states in which a DIRECTOR_REPAIR has ended (`workflows.services`).
ENDED = ("COMPLETED", "DEAD_LETTER", "FAILED", "CANCELLED")


def published_films(session: Session) -> int:
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    return int(
        session.scalar(
            select(func.count())
            .select_from(PublicationRecord)
            .where(PublicationRecord.status == "PUBLISHED")
        )
        or 0
    )


def review_pending(row: Any, published: int, now: str | None = None) -> bool:
    """Whether the decision waits for a review that is not due yet: after N more published
    films, or a date (`command.due_reviews` reads the same two)."""
    moment = now or datetime.now(UTC).isoformat()
    by_videos = row.review_after_videos is not None
    by_date = row.review_after_at is not None
    if not by_videos and not by_date:
        return False
    since = published - int(row.published_at_decision or 0)
    due = (by_videos and since >= int(row.review_after_videos)) or (
        by_date and str(row.review_after_at) <= moment
    )
    return not due


def work_done(session: Session, letter: Any) -> bool:
    """A decision's letter closed with its work done: a HANDOFF that someone resolved, or that
    its addressee answered done=true in its thread after it (`agents.mail` closes a HANDOFF on
    nothing else, and a done=true reply closes the sender's earlier letters with the one it
    answers); any other letter answered."""
    from app.agents.messages import thread_messages  # noqa: PLC0415

    if letter.status == "RESOLVED":
        return True
    if letter.status != "ANSWERED":
        return False
    if letter.intent != "HANDOFF":
        return True
    return any(
        reply.from_agent_id == letter.to_agent_id
        and str(reply.created_at) >= str(letter.created_at)
        and isinstance(reply.body_json, dict)
        and reply.body_json.get("done") is True
        for reply in thread_messages(session, letter.thread_id or letter.id)
    )


def why_closed(session: Session, row: Any, published: int | None = None) -> str | None:
    """Why an OPEN decision's work is over, in the words its outcome keeps, or None."""
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415

    if row.message_id:
        letter = session.get(AgentMessage, row.message_id)
        films = published_films(session) if published is None else published
        if letter is not None and work_done(session, letter) and not review_pending(row, films):
            said = str(letter.resolution or "").strip()
            return f"Scrisoarea deciziei a fost închisă de {letter.resolved_by or 'cineva'}" + (
                f": {said}" if said else "."
            )
    review = session.scalars(
        select(DirectorDecision)
        .where(
            DirectorDecision.matter_key == f"review_{row.matter_key}",
            DirectorDecision.state == "REVIEWED",
            DirectorDecision.created_at >= row.created_at,
        )
        .order_by(DirectorDecision.reviewed_at.desc())
    ).first()
    if review is not None:
        return f"Revizuirea ei s-a încheiat: {review.outcome or 'fără rezultat scris'}"
    spec = (row.evidence_json or {}).get("repair") if isinstance(row.evidence_json, dict) else None
    if isinstance(spec, dict) and spec.get("task_key"):
        task = session.scalars(
            select(TaskQueueItem).where(TaskQueueItem.idempotency_key == spec["task_key"])
        ).first()
        if task is None:
            created = datetime.fromisoformat(str(row.created_at))
            created = created if created.tzinfo else created.replace(tzinfo=UTC)
            if created < datetime.now(UTC) - timedelta(minutes=UNQUEUED_AFTER_MINUTES):
                return "Reparația nu a ajuns în coadă (procesul s-a oprit între decizie și coadă)."
        elif task.status in ENDED:
            return f"Sarcina reparației s-a încheiat ({task.status}) fără să o închidă" + (
                f": {task.error_detail}" if task.error_detail else "."
            )
    return None


def _stale(session: Session) -> list[tuple[Any, str]]:
    from app.analytics.models import DirectorDecision  # noqa: PLC0415

    found: list[tuple[Any, str]] = []
    published = published_films(session)
    for row in session.scalars(
        select(DirectorDecision)
        .where(DirectorDecision.state == "OPEN")
        .order_by(DirectorDecision.created_at)
    ):
        reason = why_closed(session, row, published)
        if reason:
            found.append((row, reason))
    return found


def stale_decisions(context: RepairContext) -> list[dict[str, Any]]:
    with Session(context.engine) as session:
        stale = [(row.id, row.matter_key, reason) for row, reason in _stale(session)]
    if not stale:
        return []
    return [
        finding(
            "stale_decisions",
            "close_stale_decisions",
            observation=(
                f"{count(len(stale), 'decizie deschisă are', 'decizii deschise au')} munca "
                "încheiată și stau totuși deschise, ținând chestiunile lor în afara buclei."
            ),
            evidence={"decisions": [{"id": i, "matter_key": k} for i, k, _ in stale]},
            params={"decision_ids": [i for i, _, _ in stale]},
            fingerprint=fingerprint(sorted(i for i, _, _ in stale)),
        )
    ]


def any_still_stale(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    wanted = {str(i) for i in params.get("decision_ids") or []}
    with Session(context.engine) as session:
        if any(row.id in wanted for row, _ in _stale(session)):
            return None
    return "Deciziile acestea au fost deja închise; nu am avut ce închide."


def close_stale(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    wanted = {str(i) for i in params.get("decision_ids") or []}
    closed: dict[str, str] = {}
    with Session(context.engine) as session, session.begin():
        lock_for_write(session)
        for row, reason in _stale(session):
            if row.id in wanted and close_decision(session, row.id, reason):
                closed[row.id] = row.matter_key
    return outcome(
        APPLIED,
        f"Am închis {count(len(closed), 'decizie', 'decizii')} a căror muncă se încheiase, "
        "fiecare cu ce a ieșit din ea: " + ", ".join(sorted(set(closed.values()))[:8]) + ".",
        changed={"decisions_closed": sorted(closed)},
        letter_subject_ro=(
            f"Am închis {count(len(closed), 'decizie încheiată', 'decizii încheiate')}"
        ),
    )


register_repair(
    "close_stale_decisions",
    close_stale,
    tier="T1",
    action="director.close_decisions",
    precondition=any_still_stale,
    detector=stale_decisions,
    summary=(
        "close open decisions whose letter was closed, whose review was decided, or whose "
        "repair task ended without closing them, each with what became of it"
    ),
)
