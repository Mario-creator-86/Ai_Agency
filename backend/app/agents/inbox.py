"""The inbox: read by the mail tasks only, a page at a time; asks that lost their object expire.

The Owner's decision of 2026-10-16, «Context pe sarcină»: an employee's work call reads its role,
his rules and the memory of the film it works on (`agents.identity`); the inbox is read only by
the mail tasks, one thread at a time; and the asks of closed films expire. Until then every open
letter rode in every identity. On the studio's copy of 2026-10-16 Sarah had 182 open letters,
42 of them «Blocaje foaie» about films published or closed since 2026-10-03, and Marcus 68:
his answer_mail failed 51 times in 103 on the model's context window, and a letter whose answer
failed was never answered, so the pile grew.

Two things live here:

- `inbox_page`: whole letters, newest first, while they fit a character budget. The Director's
  review reads her inbox in such pages; a letter is never cut, and one longer than the whole
  page is read alone, whole.
- `expire_stale_asks`: an ask (HANDOFF, REQUEST_INFO, REQUEST_REVIEW, CHALLENGE) addressed to
  an employee is closed by the studio, with an ``agent.ask_expired`` event that says why, when
  its film is over (`media.shooting_sheet.film_is_closed`: uploaded, or closed unrendered), its
  episode was replaced by a rewrite or its film is over, or its topic was refused; when a newer
  letter repeats it word for word (the Director's weekly direction to a department: when a
  newer week's replaces it); and when it is older than `STALE_ASK_DAYS` and nothing above
  keeps it. The Owner's own letters are never touched (he is always answered), nor are the
  letters of her decisions (`agents.repairs.stale_decisions` closes those with the decision),
  a matter flagged for his attention, or a budget request. A letter a worker task executes is
  closed when its film is over or it is repeated, never by age: its task owns its time.

An expired ask is marked ANSWERED, not RESOLVED: code that later resolves a letter it wrote
(`media.blocker_repair` resolves its report when the repair ends) may still do so, while every
reader of the inbox — the mail round, her review, the thread repairs — reads OPEN letters only.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.messages import resolve_message
from app.agents.models import AgentMessage
from app.db import lock_for_write
from app.services import append_event

logger = logging.getLogger("studio.inbox")

#: Letters that ask for something (`agents.mail.ASKING_INTENTS`): the ones that can go stale.
ASK_INTENTS = ("HANDOFF", "REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE")
#: An ask nothing keeps open expires after this many days. Three: the serial is written every
#: day and a film is shot within a day or two, so an ask about the work in hand is answered or
#: repeated inside three days; what is older and tied to nothing live is history. The standing
#: weekly direction and her decisions' letters, which live a week by design
#: (`agents.repairs.threads`), are not closed by age.
STALE_ASK_DAYS = 3
#: Characters of whole letters one page of the inbox carries (about 6,000 tokens): a dozen
#: letters of the usual size, the most her review decides in one answer (`REVIEW_BATCH`).
INBOX_PAGE_CHARS = 24_000
EXPIRED_EVENT = "agent.ask_expired"
EXPIRED_BY = "Studioul (cereri expirate)"

FILM_CLOSED = "FILM_CLOSED"
EPISODE_CLOSED = "EPISODE_CLOSED"
TOPIC_REJECTED = "TOPIC_REJECTED"
DUPLICATE = "DUPLICATE"
EXPIRED = "EXPIRED"

#: What a letter's body keeps that changes while it waits, and so never makes two letters
#: different: the mail round's tries, a block, a worker's result and its dispatch.
_BOOKKEEPING = frozenset({"answer_attempts", "blocked", "repair_result", "dispatch_key", "attempt"})


@dataclass(frozen=True)
class StaleAsk:
    """One open ask the studio closes, and why."""

    message_id: str
    reason: str
    words: str
    detail: dict[str, Any] = field(default_factory=dict)


def inbox_page[T](
    items: Sequence[T], size: Callable[[T], int], budget: int = INBOX_PAGE_CHARS
) -> tuple[list[T], list[T]]:
    """(the page, what waits): whole items in the order given while they fit ``budget``.

    The first is always read — a letter longer than the whole page goes alone and whole, and the
    size is logged — and the page stops at the first item that does not fit, so what waits is
    the next page, in order. Nothing is cut."""
    page: list[T] = []
    used = 0
    for index, item in enumerate(items):
        length = max(0, int(size(item)))
        if page and used + length > budget:
            return page, list(items[index:])
        if not page and length > budget:
            logger.warning("inbox_letter_over_page", extra={"chars": length, "budget": budget})
        page.append(item)
        used += length
    return page, []


def _body(row: AgentMessage) -> dict[str, Any]:
    return row.body_json if isinstance(row.body_json, dict) else {}


def _plain(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def weekly_department(row: AgentMessage) -> str | None:
    """The department a letter of the Director's standing weekly direction is for, or None
    when the letter is not one (`runbook.weekly`: a HANDOFF with «instructions» and «week»).
    Letters filed before 2026-10-13 carry no «department»; their subject names it
    («Indicațiile Directorului pentru departamentul de video — 2026-S41»)."""
    body = _body(row)
    if row.intent != "HANDOFF" or not body.get("week") or not str(body.get("instructions") or ""):
        return None
    named = str(body.get("department") or "").strip()
    if not named:
        named = str(row.subject or "").rsplit(" — ", 1)[0]
    return _plain(named) or None


def _worker(body: dict[str, Any]) -> bool:
    return bool(body.get("executed_by_worker"))


def _kept(row: AgentMessage, body: dict[str, Any]) -> bool:
    """Letters the studio never closes on its own: the Owner's (a worker's report on his behalf
    apart), her decisions' (closed with the decision), and his matters."""
    if row.from_agent_id is None and not _worker(body):
        return True
    return bool(body.get("matter_key") or body.get("owner_attention") or body.get("budget_request"))


def _duplicate_key(row: AgentMessage, body: dict[str, Any]) -> tuple[Any, ...]:
    department = weekly_department(row)
    if department is not None:
        return ("direction", row.to_agent_id, department)
    content = {k: v for k, v in body.items() if k not in _BOOKKEEPING}
    return (
        "ask",
        row.to_agent_id,
        row.from_agent_id,
        row.intent,
        _plain(row.subject),
        _plain(row.body_text),
        json.dumps(content, sort_keys=True, ensure_ascii=False, default=str),
    )


class _Subjects:
    """What the studio knows of the films, episodes and topics the letters name, read once."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.films: dict[str, tuple[bool, str]] = {}

    def film(self, storyboard_id: str) -> tuple[bool, str]:
        if storyboard_id not in self.films:
            from app.media.models import Storyboard  # noqa: PLC0415 - media imports agents
            from app.media.shooting_sheet import film_is_closed  # noqa: PLC0415 - a large module

            board = self.session.get(Storyboard, storyboard_id)
            closed = board is not None and film_is_closed(self.session, storyboard_id)
            title = str(board.title) if board is not None else storyboard_id[:8]
            self.films[storyboard_id] = (closed, title)
        return self.films[storyboard_id]

    def closed(self, body: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
        """(reason, the words, detail) when the letter's film, episode or topic is over."""
        storyboard_id = str(body.get("storyboard_id") or "")
        if storyboard_id:
            closed, title = self.film(storyboard_id)
            if closed:
                return (
                    FILM_CLOSED,
                    f"filmul «{title}» este încheiat (publicat sau închis)",
                    {"storyboard_id": storyboard_id},
                )
        episode_id = str(body.get("episode_id") or "")
        if episode_id:
            from app.story.models import StoryEpisode  # noqa: PLC0415 - story imports agents

            episode = self.session.get(StoryEpisode, episode_id)
            if episode is not None:
                rewritten = (
                    episode.status == "REJECTED"
                    and self.session.scalar(
                        select(StoryEpisode.id)
                        .where(StoryEpisode.rewrite_of_id == episode_id)
                        .limit(1)
                    )
                    is not None
                )
                film_over = bool(episode.storyboard_id) and self.film(str(episode.storyboard_id))[0]
                if rewritten or film_over:
                    why = "a fost înlocuit de o rescriere" if rewritten else "are filmul încheiat"
                    return (
                        EPISODE_CLOSED,
                        f"episodul «{episode.title}» {why}",
                        {"episode_id": episode_id},
                    )
        topic_id = str(body.get("topic_id") or "")
        if topic_id:
            from app.factual.models import TopicIdea  # noqa: PLC0415 - factual imports agents

            topic = self.session.get(TopicIdea, topic_id)
            if topic is not None and topic.status == "REJECTED":
                return (
                    TOPIC_REJECTED,
                    f"subiectul «{topic.title}» a fost respins",
                    {"topic_id": topic_id},
                )
        return None


def stale_asks(session: Session, now: datetime | None = None) -> list[StaleAsk]:
    """The open asks addressed to employees that the studio closes now, newest first (read
    only; `expire_stale_asks` closes them)."""
    moment = now or datetime.now(UTC)
    cutoff = (moment - timedelta(days=STALE_ASK_DAYS)).isoformat()
    rows = session.scalars(
        select(AgentMessage)
        .where(
            AgentMessage.status == "OPEN",
            AgentMessage.to_agent_id.is_not(None),
            AgentMessage.intent.in_(ASK_INTENTS),
        )
        .order_by(AgentMessage.created_at.desc())
    ).all()
    subjects = _Subjects(session)
    newer: dict[tuple[Any, ...], AgentMessage] = {}
    out: list[StaleAsk] = []
    for row in rows:
        body = _body(row)
        if _kept(row, body):
            continue
        over = subjects.closed(body)
        if over is not None:
            reason, said, detail = over
            out.append(
                StaleAsk(
                    row.id,
                    reason,
                    f"Închisă de studio: {said}; cererea nu mai are obiect.",
                    detail,
                )
            )
            continue
        key = _duplicate_key(row, body)
        kept = newer.get(key)
        if kept is not None:
            out.append(
                StaleAsk(
                    row.id,
                    DUPLICATE,
                    "Închisă de studio: aceeași cerere a venit din nou la "
                    f"{str(kept.created_at)[:16].replace('T', ' ')} (UTC); rămâne deschisă "
                    "numai cea mai nouă.",
                    {"kept_message_id": kept.id},
                )
            )
            continue
        newer[key] = row
        if weekly_department(row) is not None or _worker(body):
            continue  # a week by design; a worker task's own time
        if str(row.created_at) < cutoff:
            out.append(
                StaleAsk(
                    row.id,
                    EXPIRED,
                    f"Închisă de studio: cererea a stat deschisă mai mult de {STALE_ASK_DAYS} "
                    "zile fără să țină de un film în lucru; dacă mai contează, se trimite din nou.",
                    {"days": STALE_ASK_DAYS},
                )
            )
    return out


def expire_stale_asks(
    engine: Engine, now: datetime | None = None, correlation_id: str | None = None
) -> dict[str, Any]:
    """Close the stale asks (`stale_asks`), each with an ``agent.ask_expired`` event saying
    why. Reads first and takes the write lock only when something is to be closed; what is
    closed is read again under the lock. Returns {"expired": [ids], "by_reason": {...}}."""
    with Session(engine) as session:
        if not stale_asks(session, now):
            return {"expired": [], "by_reason": {}}
    correlation = correlation_id or str(uuid4())
    closed: list[StaleAsk] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for ask in stale_asks(session, now):
            resolve_message(
                session,
                ask.message_id,
                resolution=ask.words,
                resolved_by=EXPIRED_BY,
                status="ANSWERED",
                correlation_id=correlation,
            )
            append_event(
                session,
                EXPIRED_EVENT,
                "agent_message",
                ask.message_id,
                2,
                {"reason": ask.reason, "resolution": ask.words, **ask.detail},
                correlation,
            )
            closed.append(ask)
    by_reason = dict(Counter(ask.reason for ask in closed))
    if closed:
        logger.info("asks_expired", extra={"count": len(closed), "by_reason": by_reason})
    return {"expired": [ask.message_id for ask in closed], "by_reason": by_reason}
