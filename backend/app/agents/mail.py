"""Employees answer their mail.

A message addressed to an employee used to wait for the evening: the Director read the inbox
once a day, and an employee asked something had no way to write back. The Owner wants an
office — the Director writes to the fact checker, the fact checker answers, the writer is
told what to change and says when it is changed. This module is the employee's side of that:
one run that reads the whole thread, writes a reply in the employee's own voice, and says
whether the matter is done.

The reply is a letter, not a status flag. It goes into the same thread; when the letter came
from the Director or the Owner, the reply lands in the Director's inbox, where her review
reads it and decides — ask more, send it on, close it. That is the shape of the exchange, and
what keeps it from becoming two models answering each other every thirty seconds: only a
letter that asks for something waits for an answer, a report does not; a thread that has
grown long is left for the evening review or the Owner; and the Director's review runs after
a round only when the round put something new in her inbox. A HANDOFF stays open until the
employee says the work is done; a question is answered once.

2026-10-11 taught the rest. Three handoffs to the Accountant were answered three times each
in two minutes: the round answered a thread's OLDEST open letter — the handoff, open while
the work was not done — whenever the thread's last word was not hers, so every letter the
Director's review added to the thread, even one to Dr. Aris, made her answer the handoff
again, and Dr. Aris's letter, behind it in the same thread, was never answered. Now each
addressee answers the NEWEST letter each sender wrote to them in a thread, in reply to that
letter, and the answer closes that sender's questions before it — never another sender's: the
Owner, the Director and a colleague each get their own answer; an employee writes in a thread
at most once a quarter of an hour; a reply that asks for the same thing, in much the same
words, as the employee's last one to that sender is not sent again — the sender's handoff is
marked blocked on it and the Director is told once, by a STATUS in her inbox; an employee
whose model keeps failing waits, as a person and not letter by letter, longer after each
failure (2026-10-04: about 160 attempts per letter), and a letter whose answer failed waits
on its own clock as well; and a reply in a thread the Director decided in this hour waits for
her next review, which a later round calls once the hour has passed.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.director import DirectorError, director_review, threads_decided_since
from app.agents.ensemble import agreement
from app.agents.identity import blocker_of
from app.agents.memory import agent_for_role
from app.agents.messages import (
    open_messages,
    post_message,
    resolve_message,
    thread_messages,
)
from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord, ProviderRecord, Role
from app.agents.reviews import mark_unproven_claims
from app.economy.budget import studio_timezone
from app.factual.sanitizer import wrap_in_inert_boundary
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now

logger = logging.getLogger("studio.mail")

MAIL_TASK = "answer_mail"
MAIL_TEMPLATE_VERSION = "mail-v2"

#: How many letters one round answers. The worker comes round every half minute; a bound
#: keeps a burst of mail from holding it for an hour.
LETTERS_PER_ROUND = 6

#: Letters that ask for something and so wait for an answer. A STATUS report or an ESCALATE
#: is information for the reader, not a question; nobody is made to answer it.
ASKING_INTENTS = ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "HANDOFF")

#: A thread with this many letters has had its exchange; what it still needs is a decision,
#: from the evening review or the Owner, not another automatic round.
THREAD_ROUNDS = 8

#: How many reviews the Director may run in an hour, counting the evening's. One night she
#: reviewed nine times in twenty-four minutes — every answer triggered a review and every
#: review asked more — at twenty thousand tokens a time. Answers that arrive after the third
#: wait for the next hour or the evening.
REVIEWS_PER_HOUR = 3

#: A reply in a thread the Director decided in within this window waits for her next review.
DECIDED_THREAD_WINDOW = timedelta(hours=1)

#: The least time between two letters of one employee in one thread: a colleague who has
#: just written waits for an answer before writing again. The Owner's own letters are
#: answered at once; he does not write every half minute.
REPLY_INTERVAL = timedelta(minutes=15)

#: After a letter's answer failed it waits this long, doubled after each failure on the same
#: model, at most the maximum — the guard of `media.blocker_repair`, for mail. An employee
#: whose model keeps failing waits on the same scale (`_model_resumes_at`).
ANSWER_BACKOFF_BASE_SECONDS = 300
ANSWER_BACKOFF_MAX_SECONDS = 6 * 3600

#: An employee whose latest this-many attempts on her model all failed has a failing model:
#: she waits as a person, not letter by letter, and is then tried with one letter, not all —
#: one try is enough to learn whether the model answers again.
FAILING_ATTEMPTS = 3

#: How many of her latest runs are read to find her latest attempts. An attempt is one call
#: of a task with its second try: the runs that share a correlation. Enough for the streak
#: that reaches the longest wait.
ATTEMPT_RUNS_READ = 24

#: The run statuses that say the provider failed, not the letter: the call raised
#: (`run_agent_task` records FAILED only then) or the provider's health gate refused it.
PROVIDER_FAILURES = ("FAILED", "BLOCKED_PROVIDER")

#: The run statuses that say the model failed the call, whatever the task: the provider's
#: failures and an answer with no text. A refused budget is not the model's.
MODEL_FAULTS = (*PROVIDER_FAILURES, "EMPTY_OUTPUT")

#: How alike two «needs», and two replies, must be to be the same request again
#: (`ensemble.agreement`).
SAME_REQUEST_AGREEMENT = 0.6

#: «Needs» that name nothing: what a model writes when it owes nothing. Two of them are not
#: the same request, and a handoff is never blocked on one.
NOTHING_NEEDED = frozenset(
    {"", "-", "n/a", "na", "no", "none", "nothing", "nu", "nimic", "nimic altceva", "niciuna"}
)

_INSTRUCTIONS = (
    "You have a letter in your inbox, with the whole thread it belongs to, below. Answer it as "
    "yourself: say what you did, found or decided, what you still need and from whom, in the "
    "language the letter uses. Be concrete — name the claim, the scene, the figure. Close the "
    "letter as a colleague would. If the request needs work you have not done yet, say what "
    "you will do and when; do not claim it is done.\n"
    'Return only JSON: {"reply": "the letter, two to eight sentences", '
    '"done": true|false, "needs": "what you still need, or empty"}. '
    '"done" is true only when nothing more is owed on this thread.\n'
)

_BOOKS_INSTRUCTIONS = (
    "\nAfter the thread are your books, computed by the studio this minute: today's and this "
    "month's spend per provider, the budgets, the usage no price covered per model with "
    "whether a price active now covers it, and what each published film cost. Answer from "
    "them; do not ask anyone for a figure or a price the books already hold.\n"
)


class MailReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reply: str = Field(min_length=1, max_length=4000)
    done: bool = False
    needs: str = Field(default="", max_length=600)

    @field_validator("reply")
    @classmethod
    def _words_not_placeholder(cls, value: str) -> str:
        # A model restating the schema's example writes {"reply": "..."}; that is not a letter.
        if sum(ch.isalpha() for ch in value) < 3:
            raise ValueError("a reply is written in words")
        return value


class MailError(ValueError):
    """The letter could not be answered; nothing was sent. ``run_status`` and ``run_id`` are
    those of the run that did not answer, when a run was made."""

    def __init__(
        self, message: str, *, run_status: str | None = None, run_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.run_status = run_status
        self.run_id = run_id


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _owed(row: AgentMessage, agent_id: str) -> bool:
    """An open letter to this employee that asks for something and that conversation can
    answer (a durable tool task owns the letters it executes)."""
    return (
        row.status == "OPEN"
        and row.to_agent_id == agent_id
        and row.intent in ASKING_INTENTS
        and not (row.body_json or {}).get("executed_by_worker")
    )


def _thread_text(messages: list[AgentMessage], names: dict[str, str]) -> str:
    lines = []
    for m in messages:
        sender = names.get(m.from_agent_id or "", "the Owner" if m.from_agent_id is None else "?")
        receiver = names.get(m.to_agent_id or "", "the Director's inbox")
        lines.append(f"[{m.created_at[:16]}] {sender} → {receiver} · {m.intent}: {m.subject}")
        text = (m.body_text or "").strip()
        if text:
            lines.append(text)
        if m.body_json:
            lines.append(
                "Structured evidence: " + json.dumps(m.body_json, ensure_ascii=False, default=str)
            )
        lines.append("")
    return "\n".join(lines).strip()


def _books_for(engine: Engine, role: str | None) -> str | None:
    """The figures the addressee's desk keeps, when it keeps any: the Accountant's books.

    Her letters were answered from the thread alone, so she asked the Director for the rate
    card and for film costs that her own books held (2026-10-11). Computed, never asked for;
    a fault in the books leaves the letter answered from the thread as before.
    """
    from app.economy.accountant import ACCOUNTANT_ROLE, daily_figures  # noqa: PLC0415

    if role != ACCOUNTANT_ROLE:
        return None
    try:
        figures = daily_figures(engine)
    except (SQLAlchemyError, ValueError, KeyError):
        logger.warning("mail_books_unreadable", exc_info=True)
        return None
    return json.dumps(figures, ensure_ascii=False, default=str)


def _answered_letter(reply: AgentMessage, letters: dict[str, AgentMessage]) -> AgentMessage | None:
    """The letter a reply written by this module answers, when it is in the thread."""
    about = (reply.body_json or {}).get("about_message_id")
    return letters.get(str(about)) if about else None


def _last_reply(
    thread: list[AgentMessage], agent_id: str, sender: str | None
) -> AgentMessage | None:
    """The employee's latest answer in the thread to a letter of this sender (the Owner when
    None). The STATUS that reports a block is not one: the next reply is compared with what
    the employee last wrote, not with the studio's notice."""
    letters = {m.id: m for m in thread}
    replies = [
        m
        for m in thread
        if m.from_agent_id == agent_id
        and not (m.body_json or {}).get("blocked_on")
        and (answered := _answered_letter(m, letters)) is not None
        and answered.from_agent_id == sender
    ]
    return replies[-1] if replies else None


def _real_need(needs: object) -> str:
    """The need in plain form, or "" when it names nothing («N/A», «Nimic.»)."""
    plain = " ".join(str(needs or "").casefold().split()).strip(" .!-–—")
    return "" if plain in NOTHING_NEEDED else plain


def _repeats(previous: AgentMessage, reply: MailReply) -> bool:
    """Whether a reply asks again for what the employee's previous one asked, in much the same
    words. The same need alone is not a repeat: a reply that gives a film's cost while the
    invoice is still awaited is news, and holding it lost the figure. Nor are the same words
    asking for nothing: that is routine, not a block."""
    earlier = previous.body_json or {}
    if reply.done or earlier.get("done"):
        return False
    left, right = _real_need(earlier.get("needs")), _real_need(reply.needs)
    if not left or not right:
        return False
    same_need = left == right or agreement(left, right) >= SAME_REQUEST_AGREEMENT
    same_words = agreement(previous.body_text or "", reply.reply) >= SAME_REQUEST_AGREEMENT
    return same_need and same_words


def _studio_clock(session: Session, moment: str) -> str:
    """A stored UTC moment as the studio's clock reads it, for words the Owner reads."""
    when = _when(moment)
    if when is None:
        return str(moment)[:16].replace("T", " ")
    return when.astimezone(ZoneInfo(studio_timezone(session))).strftime("%Y-%m-%d %H:%M")


def _close_earlier(
    session: Session,
    thread_id: str,
    agent_id: str,
    letter: AgentMessage,
    *,
    done: bool,
    resolution: str,
    resolved_by: str,
    correlation: str,
) -> list[str]:
    """Close what the reply answers: the letter and every earlier open letter its sender wrote
    to the same employee in the thread. Another sender's letter is not answered by a reply
    that does not reach them — a reply to the Owner closed the Director's open question while
    her inbox got nothing. A question is answered by the answer; a HANDOFF is an instruction
    that follows the employee into every run until the work is done, so it closes only on the
    employee's word — and a new reply lifts a block set on an earlier, repeated one."""
    closed: list[str] = []
    for row in thread_messages(session, thread_id):
        if (
            not _owed(row, agent_id)
            or row.from_agent_id != letter.from_agent_id
            or row.created_at > letter.created_at
        ):
            continue
        if row.intent == "HANDOFF" and not done:
            body = dict(row.body_json or {})
            if body.pop("blocked", None) is not None:
                row.body_json = body
            continue
        resolve_message(
            session,
            row.id,
            resolution=resolution,
            resolved_by=resolved_by,
            status="ANSWERED",
            correlation_id=correlation,
        )
        closed.append(row.id)
    return closed


def _hold_repeated_request(
    engine: Engine,
    *,
    message_id: str,
    thread_id: str,
    agent_id: str,
    name: str,
    previous: AgentMessage,
    needs: str,
    run_id: str,
    correlation: str,
) -> dict[str, Any]:
    """The employee asked again, in much the same words, for what the last reply to this
    sender asked: that reply is not sent again.

    The sender's questions it would have answered are answered by the earlier reply, the
    sender's open HANDOFFs in the thread are marked blocked on what is needed, and the
    Director is told, by one STATUS in her inbox while that notice stands unread: a block
    nobody reads is a thread gone silent while work is still owed."""
    with Session(engine) as session, session.begin():
        letter = session.get(AgentMessage, message_id)
        if letter is None:
            raise MailError("The letter is gone")
        written = _studio_clock(session, previous.created_at)
        marker = {
            "needs": needs,
            "since": utc_now(),
            "by": name,
            "repeats_message_id": previous.id,
            "run_id": run_id,
        }
        answered = _close_earlier(
            session,
            thread_id,
            agent_id,
            letter,
            done=False,
            resolution=(
                f"Același răspuns ca în scrisoarea din {written}: are nevoie în continuare de "
                f"{needs}"
            ),
            resolved_by=name,
            correlation=correlation,
        )
        thread = thread_messages(session, thread_id)
        blocked: list[str] = []
        for row in thread:
            if (
                _owed(row, agent_id)
                and row.intent == "HANDOFF"
                and row.from_agent_id == letter.from_agent_id
            ):
                row.body_json = {**(row.body_json or {}), "blocked": marker}
                blocked.append(row.id)
        told = next(
            (
                m
                for m in thread
                if m.from_agent_id == agent_id
                and m.status == "OPEN"
                and (m.body_json or {}).get("blocked_on")
            ),
            None,
        )
        if told is None:
            told = post_message(
                session,
                intent="STATUS",
                subject=f"Re: {letter.subject}"[:200],
                body={
                    "blocked_on": needs,
                    "repeats_message_id": previous.id,
                    "about_message_id": message_id,
                    "done": False,
                    "needs": needs,
                },
                body_text=(
                    f"Nu pot continua fără: {needs.strip().rstrip('.')}. Am cerut asta în "
                    f"scrisoarea din {written} și nu o repet."
                ),
                from_agent_id=agent_id,
                run_id=run_id,
                in_reply_to=message_id,
                correlation_id=correlation,
            )
        told_id = told.id
        append_event(
            session,
            "agent.mail_repeated",
            "agent_message",
            message_id,
            1,
            {
                "thread_id": thread_id,
                "agent_id": agent_id,
                "needs": needs,
                "repeats_message_id": previous.id,
                "answered": answered,
                "blocked": blocked,
                "told": told_id,
                "run_id": run_id,
            },
            correlation,
        )
    return {
        "message_id": None,
        "thread_id": thread_id,
        "held": True,
        "repeats_message_id": previous.id,
        "answered": answered,
        "blocked": blocked,
        "told": told_id,
        "needs": needs,
        "run_id": run_id,
    }


def answer_mail(
    engine: Engine,
    registry: ProviderRegistry,
    message_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Have the addressee answer one letter, in its thread. Returns what was sent.

    The reply answers this letter (``in_reply_to``) and closes the earlier ones of the same
    sender it answers (`_close_earlier`). A reply that is not done and asks, in much the same
    words, for what the employee's previous reply to this sender asked is not sent
    (`_hold_repeated_request`); the result then has no ``message_id`` and says ``held``.
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        letter = session.get(AgentMessage, message_id)
        if letter is None or letter.to_agent_id is None:
            raise MailError("The letter has no addressee")
        agent = session.get(Agent, letter.to_agent_id)
        if agent is None or agent.lifecycle != "ACTIVE":
            raise MailError("The addressee is not an active employee")
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        thread_id = letter.thread_id or letter.id
        thread = thread_messages(session, thread_id)
        sender_name = names.get(letter.from_agent_id or "", "the Owner")
        agent_id, subject, name = agent.id, letter.subject, agent.display_name
        transcript = _thread_text(thread, names)
        previous = _last_reply(thread, agent_id, letter.from_agent_id)
        role = session.get(Role, agent.role_id)
        role_name = role.name if role is not None else None
        director = agent_for_role(session, "Director")
        # A reply to the Owner goes to the Owner; a reply to the Director goes to her inbox,
        # where the review reads it; a reply to a colleague goes to the colleague.
        owner_wrote = letter.from_agent_id is None
        reply_to = (
            None
            if owner_wrote or (director and letter.from_agent_id == director.id)
            else letter.from_agent_id
        )
    prompt = _INSTRUCTIONS
    books = _books_for(engine, role_name)
    if books is not None:
        prompt += _BOOKS_INSTRUCTIONS
    prompt += wrap_in_inert_boundary(transcript, "mail-thread")
    if books is not None:
        prompt += "\n" + wrap_in_inert_boundary(books, "books")
    from app.agents.structured import structured_run  # noqa: PLC0415

    answer, result, second = structured_run(
        engine,
        registry,
        agent_id,
        MAIL_TASK,
        prompt,
        MAIL_TEMPLATE_VERSION,
        correlation,
        MailReply,
        '{"reply": "...", "done": true|false, "needs": "..."}',
        summary=f"Răspund la «{subject}» de la {sender_name}.",
        max_tokens=3600,
        temperature=0.3,
    )
    final = second or result
    text = final.get("output_text") or ""
    if final["status"] != "SUCCEEDED" or not text.strip():
        raise MailError(
            f"{agent_id} did not answer ({final['status']}: "
            f"{final.get('error_detail') or 'no visible text'})",
            run_status=str(final["status"]),
            run_id=str(final["id"]),
        )
    result = final
    blocker = blocker_of(text)
    if blocker is not None:
        # An employee who cannot do what the letter asks says so in words, not in a JSON
        # blob pasted into a letter: what stops them and what they need.
        parsed = MailReply(
            reply=(
                f"Nu pot răspunde la asta: {blocker.reason}"
                + (f" Am nevoie de: {blocker.needs}" if blocker.needs else "")
            )[:4000],
            done=False,
            needs=blocker.needs[:600],
        )
        intent_out = "ESCALATE"
    else:
        intent_out = "STATUS"
        # Prose instead of the schema is still a letter; it is sent as written.
        parsed = (
            answer
            if isinstance(answer, MailReply)
            else MailReply(reply=" ".join(text.split())[:4000], done=False)
        )
    # The Owner's own letter is always answered, even with what he was told before.
    if previous is not None and not owner_wrote and _repeats(previous, parsed):
        return _hold_repeated_request(
            engine,
            message_id=message_id,
            thread_id=thread_id,
            agent_id=agent_id,
            name=name,
            previous=previous,
            needs=parsed.needs,
            run_id=result["id"],
            correlation=correlation,
        )
    with Session(engine) as session, session.begin():
        sent = post_message(
            session,
            intent=intent_out,
            subject=f"Re: {subject}"[:200],
            body={"done": parsed.done, "needs": parsed.needs, "about_message_id": message_id},
            body_text=parsed.reply,
            from_agent_id=agent_id,
            to_agent_id=reply_to,
            to_owner=owner_wrote,
            run_id=result["id"],
            in_reply_to=message_id,
            correlation_id=correlation,
        )
        # A letter that says media work was done, with no media.* event since the thread
        # began, is labelled NEEFĂCUT before the Director reads it (Nepal, 2026-09-26: "Am
        # re-randat pista audio", and nothing had been rendered).
        mark_unproven_claims(session, sent, correlation)
        original = session.get(AgentMessage, message_id)
        if original is not None:
            _close_earlier(
                session,
                thread_id,
                agent_id,
                original,
                done=parsed.done,
                resolution=parsed.reply[:2000],
                resolved_by=name,
                correlation=correlation,
            )
        return {
            "message_id": sent.id,
            "thread_id": sent.thread_id,
            "done": parsed.done,
            "needs": parsed.needs,
            "run_id": result["id"],
        }


def reviews_this_hour(session: Session) -> int:
    """How many Director reviews started in the last hour, whatever triggered them."""
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    return len(
        session.scalars(
            select(AgentRun.id).where(
                AgentRun.task_type == "director_review", AgentRun.started_at >= since
            )
        ).all()
    )


def _model_of(session: Session, model_id: str | None) -> tuple[str, str] | None:
    """The model's name and its provider's, as runs record them."""
    model = session.get(ModelRecord, model_id) if model_id else None
    provider = session.get(ProviderRecord, model.provider_id) if model is not None else None
    return (model.model_name, provider.name) if model is not None and provider else None


def _latest_attempts(
    session: Session, agent_id: str, model: tuple[str, str]
) -> list[tuple[str, str, str | None]]:
    """The employee's latest attempts on a model, newest first: per correlation the status of
    its last run, when that run started and when it ended. A first try that narrated followed
    by a second try the provider refused is one failed attempt, not a success and a failure."""
    seen: set[str] = set()
    attempts: list[tuple[str, str, str | None]] = []
    for run_id, correlation, status, started, finished in session.execute(
        select(
            AgentRun.id,
            AgentRun.correlation_id,
            AgentRun.status,
            AgentRun.started_at,
            AgentRun.finished_at,
        )
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.model_name == model[0],
            AgentRun.provider_name == model[1],
        )
        .order_by(AgentRun.started_at.desc())
        .limit(ATTEMPT_RUNS_READ)
    ):
        key = str(correlation or run_id)
        if key not in seen:
            seen.add(key)
            attempts.append((str(status), str(started), finished))
    return attempts


def _model_resumes_at(
    session: Session, agent_id: str, model: tuple[str, str] | None
) -> datetime | None:
    """When an employee whose model keeps failing may be tried again; None when it does not.

    Her model fails when her latest `FAILING_ATTEMPTS` attempts on it, whatever the task,
    all failed (`MODEL_FAULTS`). The wait is hers, not a letter's: kept per letter, thirty
    open letters each waiting on its own clock asked a model that refused every call on 135
    passes of 148. It runs from the end of the last failed attempt and doubles with each
    further one, up to `ANSWER_BACKOFF_MAX_SECONDS`; a success, or another model, ends it."""
    if model is None:
        return None
    attempts = _latest_attempts(session, agent_id, model)
    streak = 0
    for status, _started, _finished in attempts:
        if status not in MODEL_FAULTS:
            break
        streak += 1
    if streak < FAILING_ATTEMPTS:
        return None
    _status, started, finished = attempts[0]
    last = _when(finished or started)
    if last is None:
        return None
    wait = min(
        ANSWER_BACKOFF_BASE_SECONDS * 2 ** (streak - FAILING_ATTEMPTS),
        ANSWER_BACKOFF_MAX_SECONDS,
    )
    return last + timedelta(seconds=wait)


def _backing_off(
    session: Session,
    attempts: Any,
    moment: datetime,
    agent_id: str,
    model_id: str | None,
    model: tuple[str, str] | None,
) -> bool:
    """Whether a letter whose answer failed is still waiting. The wait was for the model the
    letter was tried on: a change of the employee's model ends it. When the provider was what
    failed (the call raised, or its health gate refused), it ends too when her latest attempt
    on that model, begun after the failure ended, succeeded — the model answers again
    (`media.blocker_repair` resumes the same way). The letter's own first try is not such an
    attempt: it began before the failure, and a narrated first try whose second try failed
    voided the wait at once, so the letter was asked every pass. A failure of the letter's
    own (an empty answer, a refused budget) waits it out."""
    if not isinstance(attempts, dict) or attempts.get("model_id") != model_id:
        return False
    resume = _when(attempts.get("retry_after"))
    if resume is None or moment >= resume:
        return False
    if attempts.get("run_status") not in PROVIDER_FAILURES or model is None:
        return True
    latest = _latest_attempts(session, agent_id, model)[:1]
    failed_at = str(attempts.get("last_failed_at") or "")
    return not (latest and latest[0][0] == "SUCCEEDED" and latest[0][1] > failed_at)


def _addressees_turn(
    session: Session,
    row: AgentMessage,
    thread_id: str,
    moment: datetime,
    model_id: str | None,
    model: tuple[str, str] | None,
) -> bool:
    """Whether the newest letter of its sender to an employee in a thread waits for them now."""
    addressee = row.to_agent_id
    if row.from_agent_id == addressee:
        # A note to oneself (the Director files investigations to her own desk) is not a
        # letter anyone answers; the thread's last word was always hers.
        return False
    body = row.body_json if isinstance(row.body_json, dict) else {}
    if body.get("blocked"):
        return False  # the reply repeated the last one; a newer letter reopens the exchange
    attempts = body.get("answer_attempts")
    if _backing_off(session, attempts, moment, str(addressee), model_id, model):
        return False
    thread = thread_messages(session, thread_id)
    if len(thread) >= THREAD_ROUNDS:
        return False
    letters = {m.id: m for m in thread}
    for m in thread:
        answered = _answered_letter(m, letters) if m.from_agent_id == addressee else None
        if (
            answered is not None
            and answered.from_agent_id == row.from_agent_id
            and answered.created_at >= row.created_at
        ):
            # She has answered this letter, or a later one of the same sender. Anything else
            # she wrote does not answer it: a letter that came while her model was answering
            # an older one was masked by that answer and never picked again.
            return False
    if row.from_agent_id is None:
        return True
    written = [_when(m.created_at) for m in thread if m.from_agent_id == addressee]
    last = max((w for w in written if w is not None), default=None)
    return last is None or moment - last >= REPLY_INTERVAL


def letters_awaiting_answer(
    session: Session, limit: int = LETTERS_PER_ROUND, now: datetime | None = None
) -> list[str]:
    """The letters it is an employee's turn to answer, the longest waiting first.

    Per thread, addressee and sender only the newest open letter that asks for something
    counts: the addressee answers that one, and the answer closes that sender's ones before
    it. Another sender's letter in the same thread — the Owner's beside the Director's, a
    letter to someone else — is its own turn, not hidden behind it. The newest letter waits
    when the addressee has answered it or a later one of its sender, or wrote in the thread
    less than `REPLY_INTERVAL` ago, or is answering another letter of the thread this round
    (a letter from the Owner waits for neither); when the employee's previous reply was
    repeated (`blocked`); when its last answer failed and the back-off on the same model has
    not run out; and when the thread has had its exchange. An employee whose model keeps
    failing waits until `_model_resumes_at`, then gets one letter.
    """
    moment = now or datetime.now(UTC)
    newest: dict[tuple[str, str, str], AgentMessage] = {}
    for row in session.scalars(
        select(AgentMessage)
        .where(
            AgentMessage.status == "OPEN",
            AgentMessage.to_agent_id.is_not(None),
            AgentMessage.intent.in_(ASKING_INTENTS),
        )
        .order_by(AgentMessage.created_at.desc())
    ):
        if (row.body_json or {}).get("executed_by_worker"):
            # A durable tool task owns this letter; conversation cannot fulfil it.
            continue
        key = (row.thread_id or row.id, str(row.to_agent_id), row.from_agent_id or "")
        newest.setdefault(key, row)
    model_ids = {
        agent_id: model_id
        for agent_id, model_id in session.execute(select(Agent.id, Agent.model_id))
    }
    models: dict[str, tuple[str, str] | None] = {}
    resumes: dict[str, datetime | None] = {}
    tried: set[str] = set()
    writing: set[tuple[str, str]] = set()  # (thread, addressee) answered this round
    waiting: list[str] = []
    for (thread_id, addressee, _sender), row in sorted(
        newest.items(), key=lambda item: item[1].created_at
    ):
        if addressee not in models:
            models[addressee] = _model_of(session, model_ids.get(addressee))
            resumes[addressee] = _model_resumes_at(session, addressee, models[addressee])
        resume = resumes[addressee]
        if resume is not None and (moment < resume or addressee in tried):
            continue  # her model keeps failing: one try when her wait is over, not one a letter
        if row.from_agent_id is not None and (thread_id, addressee) in writing:
            continue  # one letter of hers in a thread per round, the Owner's answer apart
        if not _addressees_turn(
            session, row, thread_id, moment, model_ids.get(addressee), models[addressee]
        ):
            continue
        tried.add(addressee)
        writing.add((thread_id, addressee))
        waiting.append(row.id)
        if len(waiting) >= limit:
            break
    return waiting


def note_failed_answer(
    engine: Engine,
    message_id: str,
    reason: str,
    *,
    run_status: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Count a failed answer on the letter and say when it may be tried again.

    The wait doubles with each failure on the same model, from `ANSWER_BACKOFF_BASE_SECONDS`
    to `ANSWER_BACKOFF_MAX_SECONDS`; a different model starts the count again. Kept on the
    letter (``answer_attempts``) so it outlives the pass and the process, with the status of
    the run that failed and the moment it ended (`_backing_off` reads them): the round's own
    moment came before the letter's first try, which then read as a success since."""
    moment = now or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        row = session.get(AgentMessage, message_id)
        if row is None:
            return None
        agent = session.get(Agent, row.to_agent_id) if row.to_agent_id else None
        model_id = agent.model_id if agent is not None else None
        run = session.get(AgentRun, run_id) if run_id else None
        failed_at = (run.finished_at or run.started_at) if run is not None else None
        body = dict(row.body_json or {})
        before = body.get("answer_attempts")
        before = before if isinstance(before, dict) else {}
        count = int(before.get("count") or 0) + 1 if before.get("model_id") == model_id else 1
        wait = min(ANSWER_BACKOFF_BASE_SECONDS * 2 ** (count - 1), ANSWER_BACKOFF_MAX_SECONDS)
        attempts = {
            "count": count,
            "total": int(before.get("total") or 0) + 1,
            "model_id": model_id,
            "last_failed_at": failed_at or moment.isoformat(),
            "retry_after": (moment + timedelta(seconds=wait)).isoformat(),
            "error": " ".join(reason.split())[:200],
            "run_status": run_status,
            "run_id": run_id,
        }
        body["answer_attempts"] = attempts
        row.body_json = body
        return attempts


def _unread_replies(session: Session) -> list[AgentMessage]:
    """The employees' answers in the Director's inbox that came after her last review began:
    what no review of hers has read yet."""
    last = (
        session.scalar(
            select(func.max(AgentRun.started_at)).where(AgentRun.task_type == "director_review")
        )
        or ""
    )
    return [
        m
        for m in open_messages(session, inbox=True, limit=200)
        if m.from_agent_id is not None
        and "about_message_id" in (m.body_json or {})
        and m.created_at > last
    ]


def correspondence_round(
    engine: Engine,
    registry: ProviderRegistry,
    now: datetime | None = None,
    *,
    limit: int = LETTERS_PER_ROUND,
) -> dict[str, Any]:
    """Answer the letters that are waiting, then let the Director read what came back.

    Called by the worker between its tasks. The Director's review runs when this round put a
    letter in her inbox in a thread she has not decided in this hour — so an employee's
    answer is read and decided within a pass, a quiet studio costs nothing, and an exchange
    she has just decided waits for her next review instead of feeding itself. An answer that
    waited (a thread she had decided, or the hour's reviews spent) is read once it has waited
    `DECIDED_THREAD_WINDOW` and no review has read it since: nothing else called her before
    the evening, and it sat in her inbox for most of a day.
    """
    moment = now or datetime.now(UTC)
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy is not None and policy.autonomy_stopped:
            return {"answered": [], "refused": [], "review": None, "reason": "autonomy stopped"}
        waiting = letters_awaiting_answer(session, limit=max(1, limit), now=moment)
    answered: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for message_id in waiting:
        try:
            outcome = answer_mail(engine, registry, message_id)
        except (MailError, ValueError) as exc:
            logger.info("mail_not_answered", extra={"message_id": message_id})
            attempts = note_failed_answer(
                engine,
                message_id,
                str(exc),
                run_status=getattr(exc, "run_status", None),
                run_id=getattr(exc, "run_id", None),
                now=moment,
            )
            refused.append(
                {
                    "message_id": message_id,
                    "reason": str(exc)[:200],
                    "attempt": (attempts or {}).get("count"),
                    "retry_after": (attempts or {}).get("retry_after"),
                }
            )
            continue
        (held if outcome.get("held") else answered).append(outcome)
    review: dict[str, Any] | None = None
    with Session(engine) as session:
        unread = _unread_replies(session)
        sent = {a["message_id"] for a in answered}
        arrived = [m for m in unread if m.id in sent]
        decided = threads_decided_since(session, (moment - DECIDED_THREAD_WINDOW).isoformat())
        new_in_inbox = any((m.thread_id or m.id) not in decided for m in arrived)
        overdue = any(
            (_when(m.created_at) or moment) <= moment - DECIDED_THREAD_WINDOW for m in unread
        )
        rationed = reviews_this_hour(session) >= REVIEWS_PER_HOUR
    if (new_in_inbox or overdue) and rationed:
        review = {"deferred": f"{REVIEWS_PER_HOUR} reviews this hour already; later"}
    elif new_in_inbox or overdue:
        try:
            review = director_review(engine, registry, str(uuid4()))
        except (DirectorError, ValueError) as exc:
            logger.info("director_review_refused", extra={"reason": str(exc)[:200]})
            review = {"refused": str(exc)[:200]}
    elif arrived:
        review = {"deferred": "a thread she decided in this hour; her next review reads it"}
    return {"answered": answered, "held": held, "refused": refused, "review": review}
