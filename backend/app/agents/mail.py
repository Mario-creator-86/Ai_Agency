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
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.director import DirectorError, director_review
from app.agents.identity import blocker_of
from app.agents.memory import agent_for_role
from app.agents.messages import (
    open_messages,
    post_message,
    resolve_message,
    thread_messages,
)
from app.agents.models import Agent, AgentMessage
from app.factual.sanitizer import wrap_in_inert_boundary
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry

logger = logging.getLogger("studio.mail")

MAIL_TASK = "answer_mail"
MAIL_TEMPLATE_VERSION = "mail-v1"

#: How many letters one round answers. The worker comes round every half minute; a bound
#: keeps a burst of mail from holding it for an hour.
LETTERS_PER_ROUND = 6

#: Letters that ask for something and so wait for an answer. A STATUS report or an ESCALATE
#: is information for the reader, not a question; nobody is made to answer it.
ASKING_INTENTS = ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "HANDOFF")

#: A thread with this many letters has had its exchange; what it still needs is a decision,
#: from the evening review or the Owner, not another automatic round.
THREAD_ROUNDS = 8

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
    """The letter could not be answered; nothing was sent."""


def _thread_text(messages: list[AgentMessage], names: dict[str, str]) -> str:
    lines = []
    for m in messages:
        sender = names.get(m.from_agent_id or "", "the Owner" if m.from_agent_id is None else "?")
        receiver = names.get(m.to_agent_id or "", "the Director's inbox")
        lines.append(f"[{m.created_at[:16]}] {sender} → {receiver} · {m.intent}: {m.subject}")
        text = (m.body_text or "").strip()
        if text:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def answer_mail(
    engine: Engine,
    registry: ProviderRegistry,
    message_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Have the addressee answer one letter, in its thread. Returns what was sent."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        letter = session.get(AgentMessage, message_id)
        if letter is None or letter.to_agent_id is None:
            raise MailError("The letter has no addressee")
        agent = session.get(Agent, letter.to_agent_id)
        if agent is None or agent.lifecycle != "ACTIVE":
            raise MailError("The addressee is not an active employee")
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        thread = thread_messages(session, letter.thread_id or letter.id)
        sender_name = names.get(letter.from_agent_id or "", "the Owner")
        agent_id, subject, intent = agent.id, letter.subject, letter.intent
        transcript = _thread_text(thread, names)
        director = agent_for_role(session, "Director")
        # A reply to the Owner goes to the Owner; a reply to the Director goes to her inbox,
        # where the review reads it; a reply to a colleague goes to the colleague.
        owner_wrote = letter.from_agent_id is None
        reply_to = (
            None
            if owner_wrote or (director and letter.from_agent_id == director.id)
            else letter.from_agent_id
        )
    prompt = _INSTRUCTIONS + wrap_in_inert_boundary(transcript, "mail-thread")
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
            f"{final.get('error_detail') or 'no visible text'})"
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
        original = session.get(AgentMessage, message_id)
        # A HANDOFF is an instruction: it follows the employee into every run until the
        # work is done, so it closes only on the employee's word. A question or a request
        # for information is answered by the answer.
        if (
            original is not None
            and original.status == "OPEN"
            and (parsed.done or intent in ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE"))
        ):
            resolve_message(
                session,
                message_id,
                resolution=parsed.reply[:2000],
                resolved_by=names.get(agent_id, agent_id),
                status="ANSWERED",
                correlation_id=correlation,
            )
        return {
            "message_id": sent.id,
            "thread_id": sent.thread_id,
            "done": parsed.done,
            "needs": parsed.needs,
            "run_id": result["id"],
        }


def letters_awaiting_answer(session: Session, limit: int = LETTERS_PER_ROUND) -> list[str]:
    """Open letters to an employee whose thread's last word is not the employee's own."""
    waiting: list[str] = []
    rows = session.scalars(
        select(AgentMessage)
        .where(
            AgentMessage.status == "OPEN",
            AgentMessage.to_agent_id.is_not(None),
            AgentMessage.intent.in_(ASKING_INTENTS),
        )
        .order_by(AgentMessage.created_at.asc())
    ).all()
    seen_threads: set[str] = set()
    for row in rows:
        thread_id = row.thread_id or row.id
        if thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        thread = thread_messages(session, thread_id)
        if len(thread) >= THREAD_ROUNDS or thread[-1].from_agent_id == row.to_agent_id:
            continue
        waiting.append(row.id)
        if len(waiting) >= limit:
            break
    return waiting


def correspondence_round(engine: Engine, registry: ProviderRegistry) -> dict[str, Any]:
    """Answer the letters that are waiting, then let the Director read what came back.

    Called by the worker between its tasks. The Director's review runs only when this round
    put a letter in her inbox — so an employee's answer is read and decided within a pass,
    and a quiet studio costs nothing.
    """
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy is not None and policy.autonomy_stopped:
            return {"answered": [], "refused": [], "review": None, "reason": "autonomy stopped"}
        waiting = letters_awaiting_answer(session)
    answered: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    for message_id in waiting:
        try:
            answered.append(answer_mail(engine, registry, message_id))
        except (MailError, ValueError) as exc:
            logger.info("mail_not_answered", extra={"message_id": message_id})
            refused.append({"message_id": message_id, "reason": str(exc)[:200]})
    review: dict[str, Any] | None = None
    if answered:
        with Session(engine) as session:
            new_in_inbox = any(
                m.id in {a["message_id"] for a in answered}
                for m in open_messages(session, inbox=True, limit=200)
            )
        if new_in_inbox:
            try:
                review = director_review(engine, registry, str(uuid4()))
            except (DirectorError, ValueError) as exc:
                logger.info("director_review_refused", extra={"reason": str(exc)[:200]})
                review = {"refused": str(exc)[:200]}
    return {"answered": answered, "refused": refused, "review": review}
