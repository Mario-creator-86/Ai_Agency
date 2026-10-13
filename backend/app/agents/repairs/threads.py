"""Letter threads that go round without closing, closed by the Director (2026-10-11).

At 10:50 on 2026-10-11 Sarah's loop sent Nadia three HANDOFFs about what a film cost. Nadia
answered each, with done=false (she had no figure), so each HANDOFF stayed OPEN; the Director's
review asked her again in the same thread; and the mail round, which answers the oldest open
asking letter of a thread, had her answer the same HANDOFF three times in two minutes, nine
near-identical letters, while a REQUEST_INFO to her and Dr. Aris's letters in those threads
waited. Only the Owner's own button could close a letter addressed to an employee.

A thread is looping when one employee wrote three replies in it within ten minutes, or two of
her replies say the same thing, in the last two days and since the Director last closed it:
a burst of September is history, not a loop of today. ``close_thread`` resolves every OPEN
letter of such a thread, resolved by the Director with the reason; a letter to the Owner is
his and is never touched, nor are the worker's own reports, the Director's standing weekly
guidance to a department (it stays open all week by design, `agents.identity._open_messages`)
or a budget request the Accountant's close forwards to the Owner while it is open. When the
thread is the letter of one of her DirectorDecisions, that decision is closed too (the matter
goes back to her loop, with the reason as its outcome), and a decision that asked what a film
cost is closed with the film cost report itself; a decision whose department had already said
the work is done waits for its review instead (`stale_decisions.review_pending`).

A HANDOFF answered «not done yet» is not a loop: it is how a department says the work is in
hand, and the HANDOFF stays in her runs until she says it is done. The first version closed
such a HANDOFF after three days, which on the studio's copy of 2026-10-11 would have closed 15
of 19 open threads, the week's standing guidance among them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.repairs import (
    APPLIED,
    RepairContext,
    finding,
    outcome,
    register_repair,
)
from app.agents.repairs.desk import close_decision, director_of, fingerprint
from app.db import lock_for_write
from app.wording import count

#: Replies of one employee in one thread within this window, from this many on, are a loop.
LOOP_REPLIES = 3
LOOP_WINDOW_SECONDS = 600
#: Two replies of one employee sharing this much of their subject words say the same thing
#: (`agents.ensemble.agreement`).
SAME_REPLY = 0.8
#: Only replies this recent are read for a loop; the loop runs every six hours, so a loop of
#: today is seen long before it is two days old, and an old one is history.
LOOP_RECENT_HOURS = 48
#: Threads closed by one repair; the rest wait for the next loop.
THREADS_PER_REPAIR = 50
#: Stamped on a letter the Director closed (`close_thread_letters`): the replies before the
#: last such close are the loop she already ended, not a new one.
CLOSED_MARK = "closed_by_director"

REASONS_RO = {
    "burst": "același angajat a răspuns de cel puțin trei ori în zece minute",
    "duplicate": "două răspunsuri ale aceluiași angajat spun același lucru",
}


def _when(stamp: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def loop_reasons(letters: list[Any], now: datetime | None = None) -> list[str]:
    """Why a thread (its letters, oldest first) is looping; empty when it is not. Only the
    replies of the last `LOOP_RECENT_HOURS` written after the Director last closed the thread
    are read. The worker's own reports (`the_workers`) are its state, not a conversation, and
    are not read as replies."""
    from app.agents.ensemble import agreement  # noqa: PLC0415

    moment = now or datetime.now(UTC)
    floor = moment - timedelta(hours=LOOP_RECENT_HOURS)
    for letter in letters:
        body = letter.body_json if isinstance(letter.body_json, dict) else {}
        closed = _when(letter.resolved_at) if body.get(CLOSED_MARK) else None
        if closed is not None and closed > floor:
            floor = closed
    reasons: list[str] = []
    replies: dict[str, list[Any]] = defaultdict(list)
    for letter in letters:
        written = _when(letter.created_at)
        if (
            letter.in_reply_to
            and letter.from_agent_id
            and not the_workers(letter)
            and written is not None
            and written > floor
        ):
            replies[letter.from_agent_id].append(letter)
    for own in replies.values():
        times = [t for t in (_when(r.created_at) for r in own) if t is not None]
        if any(
            (times[i + LOOP_REPLIES - 1] - times[i]).total_seconds() <= LOOP_WINDOW_SECONDS
            for i in range(len(times) - LOOP_REPLIES + 1)
        ):
            reasons.append("burst")
            break
    for own in replies.values():
        texts = [str(r.body_text or "") for r in own if str(r.body_text or "").strip()]
        if any(agreement(a, b) >= SAME_REPLY for a, b in zip(texts, texts[1:], strict=False)):
            reasons.append("duplicate")
            break
    return reasons


def his(letter: Any) -> bool:
    """A letter to the Owner, or one he wrote (`agents.router`: ``{"from": "Owner"}``): his
    to answer or to close, never the Director's."""
    from app.agents.messages import is_for_owner  # noqa: PLC0415

    body = letter.body_json if isinstance(letter.body_json, dict) else {}
    return is_for_owner(letter) or body.get("from") == "Owner"


def the_workers(letter: Any) -> bool:
    """A letter the worker writes as the state of its own repair: a shooting sheet's blockers,
    the attempt and its result (`media.blocker_repair`, which reads them back). Some carry
    ``executed_by_worker``; those written before it was added are known by their kind."""
    body = letter.body_json if isinstance(letter.body_json, dict) else {}
    kind = str(body.get("kind") or "")
    return bool(body.get("executed_by_worker")) or kind.startswith(
        ("shooting_sheet", "sheet_repair")
    )


def standing(letter: Any) -> bool:
    """A letter that is meant to stay open: the Director's weekly guidance to a department
    (`runbook.weekly`: its body carries the week and the instructions), which enters that
    employee's every run all week, and a budget request to the Accountant, which her daily
    close passes to the Owner only while it is open (`economy.accountant`)."""
    body = letter.body_json if isinstance(letter.body_json, dict) else {}
    weekly = letter.intent == "HANDOFF" and bool(body.get("week")) and "instructions" in body
    return weekly or bool(body.get("budget_request"))


def closable(letter: Any) -> bool:
    """An OPEN letter the Director may close: not the Owner's (`his`), not the worker's, and
    not one meant to stay open (`standing`)."""
    return (
        letter.status == "OPEN"
        and not his(letter)
        and not the_workers(letter)
        and not standing(letter)
    )


def _open_threads(session: Session) -> list[str]:
    """The threads that have an OPEN letter the Director may close."""
    from app.agents.models import AgentMessage  # noqa: PLC0415

    threads: set[str] = set()
    for letter in session.scalars(select(AgentMessage).where(AgentMessage.status == "OPEN")):
        if closable(letter):
            threads.add(letter.thread_id or letter.id)
    return sorted(threads)


def close_thread_letters(
    session: Session,
    thread_id: str,
    *,
    resolution: str,
    resolved_by: str,
    correlation_id: str,
) -> list[str]:
    """Resolve every OPEN letter of a thread the Director may close (`closable`), in the
    caller's transaction: a letter to the Owner waits for his own answer, and one he wrote is
    his to close. Each is stamped `CLOSED_MARK`, so what was said before is not read as a new
    loop. The letters closed."""
    from app.agents.messages import resolve_message, thread_messages  # noqa: PLC0415

    closed: list[str] = []
    for letter in thread_messages(session, thread_id):
        if not closable(letter):
            continue
        resolve_message(
            session,
            letter.id,
            resolution=resolution,
            resolved_by=resolved_by,
            status="RESOLVED",
            correlation_id=correlation_id,
        )
        body = letter.body_json if isinstance(letter.body_json, dict) else {}
        letter.body_json = {**body, CLOSED_MARK: correlation_id}
        closed.append(letter.id)
    return closed


# ----------------------------------------------------------------------------- detect


def thread_loops(context: RepairContext) -> list[dict[str, Any]]:
    from app.agents.messages import thread_messages  # noqa: PLC0415

    looping: list[dict[str, Any]] = []
    with Session(context.engine) as session:
        for thread_id in _open_threads(session):
            letters = thread_messages(session, thread_id)
            if any((m.body_json or {}).get("from") == "Owner" for m in letters):
                continue  # his own conversation: nobody but him ends it
            reasons = loop_reasons(letters)
            if reasons:
                looping.append(
                    {
                        "thread_id": thread_id,
                        "subject": letters[0].subject if letters else "",
                        "reasons": reasons,
                        "open": [m.id for m in letters if m.status == "OPEN"],
                    }
                )
    if not looping:
        return []
    looping = looping[:THREADS_PER_REPAIR]
    return [
        finding(
            "thread_loops",
            "close_thread",
            observation=(
                f"{count(len(looping), 'fir de scrisori se învârte', 'fire de scrisori se învârt')}"
                " fără să se închidă: "
                + "; ".join(
                    f"«{t['subject'][:80]}» ({', '.join(REASONS_RO[r] for r in t['reasons'])})"
                    for t in looping[:3]
                )
                + "."
            ),
            evidence={"threads": [{k: t[k] for k in ("thread_id", "reasons")} for t in looping]},
            params={"thread_ids": [t["thread_id"] for t in looping]},
            fingerprint=fingerprint([(t["thread_id"], sorted(t["open"])) for t in looping]),
            scope="AGENT",
        )
    ]


# ----------------------------------------------------------------------------- apply


def threads_still_open(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    from app.agents.messages import thread_messages  # noqa: PLC0415

    with Session(context.engine) as session:
        for thread_id in params.get("thread_ids") or []:
            if any(closable(m) for m in thread_messages(session, str(thread_id))):
                return None
    return "Firele au fost deja închise; nu am avut ce închide."


def _film_cost_decisions(session: Session, thread_ids: list[str]) -> bool:
    """Whether one of the threads is the letter of a decision that asked what a film cost."""
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.agents.repairs.film_cost import asks_film_cost  # noqa: PLC0415
    from app.analytics.models import DirectorDecision  # noqa: PLC0415

    for row in session.scalars(
        select(DirectorDecision).where(
            DirectorDecision.state == "OPEN", DirectorDecision.message_id.is_not(None)
        )
    ):
        letter = session.get(AgentMessage, row.message_id)
        if letter is not None and (letter.thread_id or letter.id) in thread_ids:
            if asks_film_cost(row.matter_key, row.action):
                return True
    return False


def close_threads(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from app.agents.messages import thread_messages  # noqa: PLC0415
    from app.agents.repairs.film_cost import (  # noqa: PLC0415
        asks_film_cost,
        film_report,
        report_words,
    )
    from app.agents.repairs.stale_decisions import (  # noqa: PLC0415
        published_films,
        review_pending,
        work_done,
    )
    from app.analytics.models import DirectorDecision  # noqa: PLC0415

    thread_ids = [str(t) for t in params.get("thread_ids") or []][:THREADS_PER_REPAIR]
    given = str(params.get("resolution") or "").strip()
    # The film cost report, read before the write lock, for a decision that asked for it.
    with Session(context.engine) as session:
        needs_report = _film_cost_decisions(session, thread_ids)
    film_words = report_words(film_report(context.engine)) if needs_report else ""
    closed_letters: list[str] = []
    closed_decisions: list[str] = []
    with Session(context.engine) as session, session.begin():
        lock_for_write(session)
        _director_id, director_name = director_of(session)
        published = published_films(session)
        for thread_id in thread_ids:
            letters = thread_messages(session, thread_id)
            reasons = loop_reasons(letters)
            resolution = given or (
                "Închis de Directoare: firul se învârtea fără să ajungă la un rezultat ("
                + (", ".join(REASONS_RO[r] for r in reasons) or "închis la cererea ei")
                + "). Ce rămâne de făcut îl hotărăște ea, nu încă un răspuns în fir."
            )
            by_id = {m.id: m for m in letters}
            for row in session.scalars(
                select(DirectorDecision).where(
                    DirectorDecision.state == "OPEN", DirectorDecision.message_id.in_(by_id)
                )
            ):
                asked_cost = bool(film_words) and asks_film_cost(row.matter_key, row.action)
                if (
                    not asked_cost
                    and work_done(session, by_id[str(row.message_id)])
                    and review_pending(row, published)
                ):
                    # Its department said the work is done; the loop was only the letters
                    # after it. The decision waits for its review, as any other: closed now,
                    # its matter would go back to the same department before anything was
                    # measured.
                    continue
                if close_decision(session, row.id, film_words if asked_cost else resolution):
                    closed_decisions.append(row.id)
            closed_letters += close_thread_letters(
                session,
                thread_id,
                resolution=resolution,
                resolved_by=director_name,
                correlation_id=context.correlation_id,
            )
    return outcome(
        APPLIED,
        f"Am închis {count(len(thread_ids), 'fir de scrisori', 'fire de scrisori')} care se "
        f"învârteau: {count(len(closed_letters), 'scrisoare deschisă', 'scrisori deschise')}"
        + (f" și {count(len(closed_decisions), 'decizie', 'decizii')}" if closed_decisions else "")
        + ". Scrisorile către tine au rămas neatinse."
        + (
            f" Costul filmelor, pe care îl cerea una dintre ele: {film_words}" if film_words else ""
        ),
        changed={
            "threads": thread_ids,
            "letters_closed": closed_letters,
            "decisions_closed": closed_decisions,
        },
        letter_subject_ro=(
            f"Am închis {count(len(thread_ids), 'fir care se învârtea', 'fire care se învârteau')}"
        ),
    )


register_repair(
    "close_thread",
    close_threads,
    tier="T1",
    action="director.close_thread",
    precondition=threads_still_open,
    detector=thread_loops,
    summary=(
        "resolve every open letter of a looping thread (the Owner's letters excepted) and "
        "close the decision that thread carries"
    ),
)
