"""«Închide filmul»: the Owner closes one film (2026-10-09).

The daily run chose no new topic for days: three old factual films each waited for his look at
one scene of the shooting sheet, `_selection` refuses while a selected topic is live, and the
Director never retires a film with a question of his PENDING. Nothing let him close a film.

POST /api/v1/media/storyboards/{id}/close (`close_film`), the Owner's alone:

- the film becomes REJECTED, the terminal state of the Director's retirement, through the same
  `runbook.stages.close_film_books`: its topic counts as stalled and the next run chooses
  another, and one `runbook.film_retired` event (``retired_by: "Owner"``) records what was
  bought for it and what the books hold. No letter: he pressed it himself, and a letter would
  be one more card about the film in his Decisions window;
- everything still asking him about THIS film is withdrawn through its own service: the paid
  questions by the Policy Kernel (`withdraw_subject_approvals`), the decision cards whose
  subject is the film (`withdraw_owner_decision`), the open letters to him that ask him to buy
  or decide something about it (`resolve_message`, `ASKING_LETTER_KINDS`). A letter about the
  books or money (a paid step that stopped, a purchase abandoned, a sum not booked) stays in
  his inbox: closing the film does not answer it;
- what it says about the topic is read, not assumed (`_topic_after_close`): a newer film of the
  same topic (a story repair writes one) still holds the studio, and the answer names it;
- refused (409, in Romanian) while a purchase of the film is in flight: its purchase lease (the
  close takes it, so no purchase can start or be running while it closes), an open RunPod GPU
  session of the film, a FILM_CONTINUE at work for it, a render of it still writing. Takes
  already SUBMITTED to a vendor stay as they are: the watchdog's collector still fetches them
  by task id (a GET, free), and nothing new is bought (`shooting_sheet.FilmClosed` at the
  lease);
- refused for a film with a finished render (see `_unclosable`) and for an episode of the
  office serial;
- idempotent: the same command id answers what it answered, and an already closed film answers
  CLOSED again with no second event.
"""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.models import Storyboard, VideoRenderJob
from app.media.prompt_agent import NEEDS_SHOT_PLAN
from app.media.shooting_sheet import (
    CLOSE_LEASE_STEP,
    FILM_BUSY,
    FilmBusy,
    current_lease,
    film_is_closed,
    film_purchase_lease,
)
from app.models import DomainEvent
from app.services import command_hash, recall_command, remember_command, utc_now
from app.wording import count, sentence

logger = logging.getLogger("studio.media.film_close")

#: The Owner's command, in the studio's record of commands.
CLOSE_COMMAND = "CloseFilm"
#: Who closed it, in the closing event (`runbook.film_retired`'s ``retired_by``).
OWNER = "Owner"
#: The films that can be closed: not rendered yet (see `_unclosable`).
CLOSABLE_STATUSES = ("DRAFT", "APPROVED", NEEDS_SHOT_PLAN)
#: A FILM_CONTINUE at work (`workflows.services.LEASED_STATES`, its task lease not lapsed): it
#: may be buying, or writing to him about the film once its purchase lease is given back. One
#: only QUEUED or RETRYING is not at work and does not refuse the close: it holds nothing, and
#: once claimed it skips the closed film (`continue_film`) and meets it at the lease. Under
#: STOP AUTONOMIE nothing is claimed at all, so a queued one would refuse the close for as long
#: as he kept the studio stopped.
LIVE_TASK_STATUSES = ("CLAIMED", "RUNNING")
#: A RunPod GPU session that may still be billing (`providers.runpod.gpu_session`).
LIVE_GPU_STATUSES = ("OPENING", "OPEN", "CLOSING")
#: A render of the film still writing (`assembler._RENDERING_STATUSES`): an assembly buys its
#: narration. One stuck past the watchdog's threshold is failed by it (`_fail_stuck_renders`).
LIVE_RENDER_STATUSES = ("PENDING", "RENDERING")

#: The day's list of his standing questions (`economy.accountant.waiting_approvals_letter`).
WAITING_LETTER_KIND = "owner_waiting"
#: The sheet repair's letter when only he can move the sheet on (`blocker_repair._finish`).
SHEET_REPAIR_OWNER_KIND = "sheet_repair_owner"

#: The 409's status for a film that cannot be closed at all.
FILM_RENDERED = "FILM_RENDERED"
SERIAL_EPISODE = "SERIAL_EPISODE"
NOT_CLOSABLE = "NOT_CLOSABLE"

NOT_WHILE_BUYING_RO = (
    "Filmul nu se închide în timpul unei cumpărări: nimic nu s-a schimbat. Apasă din nou după "
    "ce se termină."
)
CLOSING_NOW_RO = (
    "Filmul se închide chiar acum, la o apăsare de dinainte: reîncarcă foaia peste câteva "
    "secunde ca să vezi filmul închis."
)
WITHDRAWN_REASON_RO = (
    "Retrasă: Ownerul a închis filmul «{title}». Pentru el nu se mai cumpără nimic, deci "
    "întrebarea nu mai are ce cumpăra."
)
LETTER_RESOLUTION_RO = (
    "Ownerul a închis filmul «{title}»: pentru el nu se mai cumpără nimic, iar scrisoarea nu mai "
    "are nimic de cerut."
)
#: What a close does, in his words (the page's confirmation says the same three things).
CLOSED_WORDS_RO = (
    "Filmul «{title}» este închis: nimic nu se mai cumpără pentru el; {bought_words}; "
    "{topic_words}."
)


class CloseFilmCommand(BaseModel):
    """The Owner closes one film. Versioned and idempotent by command id, like his other
    commands; who issued it is the route's (his key), never a body field."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    #: His own words, kept in the closing event.
    note: str | None = Field(default=None, max_length=500)


class FilmCloseNotFound(LookupError):
    """No such film (404)."""


class FilmCloseRefused(RuntimeError):
    """The film was not closed (409); ``status`` says why, ``reason_ro`` is the Owner's."""

    def __init__(self, status: str, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.status = status
        self.reason_ro = reason_ro

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "message": self.reason_ro}


def _title(board: Storyboard) -> str:
    """The film as he knows it: its title without the storyboard's own prefix."""
    words = str(board.title or board.id[:8])
    return words.removeprefix("Storyboard: ").strip() or board.id[:8]


def _rendered(session: Session, storyboard_id: str) -> bool:
    return (
        session.scalar(
            select(VideoRenderJob.id)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status == "COMPLETED",
            )
            .limit(1)
        )
        is not None
    )


def _unclosable(session: Session, board: Storyboard) -> FilmCloseRefused | None:
    """Why this (not yet closed) film cannot be closed here, or None.

    A film with a finished render is refused: it no longer waits to be filmed, so it does not
    hold the studio the way the films this command is for do (`topics_in_production` counts it
    stalled once its QC fails or the Director refuses the viewing, done once published), and
    REJECTED would not stop it: the publish stage works from the rendered file, not from the
    storyboard. Such a film is ended where it is decided, by its QC verdict, the Director's
    viewing or his answer on its publication.

    An episode of the office serial is refused: the serial's day points to its storyboard, and
    a closed episode would leave that day without a film that nothing writes again. The
    Director's retirement leaves the serial alone for the same reason (`retire_stale_films`)."""
    from app.runbook.stages import is_serial_storyboard  # noqa: PLC0415 - runbook imports media

    title = _title(board)
    if _rendered(session, board.id):
        return FilmCloseRefused(
            FILM_RENDERED,
            f"Filmul «{title}» are deja o randare terminată: nu se închide de aici. Un film "
            "randat se încheie prin controlul calității, vizionarea Directoarei sau răspunsul "
            "tău la publicare. Nimic nu s-a schimbat.",
        )
    if is_serial_storyboard(board):
        return FilmCloseRefused(
            SERIAL_EPISODE,
            f"«{title}» este un episod al serialului: un episod nu se închide de aici, pentru "
            "că ziua lui din serial ar rămâne fără film. Nimic nu s-a schimbat.",
        )
    if board.status not in CLOSABLE_STATUSES:
        return FilmCloseRefused(
            NOT_CLOSABLE,
            f"Filmul «{title}» este în starea {board.status}: nu este un film care așteaptă "
            "filmarea, deci nu are ce închide. Nimic nu s-a schimbat.",
        )
    return None


def _in_flight(session: Session, storyboard_id: str, title: str) -> FilmCloseRefused | None:
    """A purchase of the film that may still be running, or None: an open RunPod GPU session
    of the film, a render of it still writing (the day's assembly buys its narration), or a
    FILM_CONTINUE of it at work. (Its purchase lease is the close's own gate: `close_film`
    takes it.)"""
    from app.providers.runpod.gpu_session import GpuSessionRow  # noqa: PLC0415
    from app.services import FILM_CONTINUE_TASK  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415 - workflows import media

    gpu = session.scalar(
        select(GpuSessionRow.id)
        .where(
            GpuSessionRow.storyboard_id == storyboard_id,
            GpuSessionRow.status.in_(LIVE_GPU_STATUSES),
        )
        .limit(1)
    )
    if gpu is not None:
        return FilmCloseRefused(
            FILM_BUSY,
            f"Filmul «{title}» are GPU-ul RunPod pornit pentru un pas al lui. "
            + NOT_WHILE_BUYING_RO,
        )
    render = session.scalar(
        select(VideoRenderJob.id)
        .where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.status.in_(LIVE_RENDER_STATUSES),
            VideoRenderJob.finished_at.is_(None),
        )
        .limit(1)
    )
    if render is not None:
        return FilmCloseRefused(
            FILM_BUSY,
            f"Filmul «{title}» se asamblează chiar acum (narațiunea și codarea). "
            + NOT_WHILE_BUYING_RO,
        )
    now = utc_now()
    for task in session.scalars(
        select(TaskQueueItem).where(
            TaskQueueItem.task_type == FILM_CONTINUE_TASK,
            TaskQueueItem.status.in_(LIVE_TASK_STATUSES),
        )
    ):
        if str((task.payload or {}).get("storyboard_id") or "") != storyboard_id:
            continue
        if task.lease_expires_at is not None and str(task.lease_expires_at) < now:
            continue  # its worker is gone; the queue's reaper ends it, and it bought nothing more
        return FilmCloseRefused(
            FILM_BUSY,
            f"Filmul «{title}» continuă chiar acum (după un răspuns al tău) și poate cumpăra "
            "pasul următor. " + NOT_WHILE_BUYING_RO,
        )
    return None


def _asking_letter_kinds() -> frozenset[str]:
    """The letters to him that ask him to buy or decide something about one film, named by
    ``storyboard_id``: the sheet's letter, the TEST environment's letter, the sheet repair's
    letter when only he can move it on, and the Director's retirement letter. The letters about
    the books or money (`paid_step_interrupted`, a purchase abandoned, takes lost) are not
    among them: closing the film does not answer what they report."""
    from app.runbook.stages import (  # noqa: PLC0415 - runbook imports media
        FILM_RETIRED_LETTER_KIND,
        SHEET_LETTER_KIND,
        TEST_ENVIRONMENT_LETTER_KIND,
    )

    return frozenset(
        {
            SHEET_LETTER_KIND,
            TEST_ENVIRONMENT_LETTER_KIND,
            SHEET_REPAIR_OWNER_KIND,
            FILM_RETIRED_LETTER_KIND,
        }
    )


def _asks_only_about(body: dict[str, Any], storyboard_id: str, kinds: frozenset[str]) -> bool:
    """Whether a letter to the Owner asks about this film alone: a letter of an asking kind
    (``kinds``) that names the film, or the day's list of his standing questions («N întrebări
    așteaptă») when every question on it is about this film. A list that also asks about
    another film stays, and so does every other letter."""
    kind = str(body.get("kind") or "")
    if kind == WAITING_LETTER_KIND:
        questions = body.get("questions")
        return (
            isinstance(questions, list)
            and bool(questions)
            and all(
                isinstance(question, dict) and str(question.get("subject") or "") == storyboard_id
                for question in questions
            )
        )
    return kind in kinds and str(body.get("storyboard_id") or "") == storyboard_id


def _withdraw_questions(
    session: Session, storyboard_id: str, title: str, correlation: str
) -> dict[str, list[str]]:
    """Everything still asking him about the film, closed by its own service, in the caller's
    transaction: his paid questions (the Policy Kernel's rows), the open decision cards whose
    subject is the film, and the open letters to him that ask about it."""
    from app import services as kernel  # noqa: PLC0415 - services imports media
    from app.agents.messages import is_for_owner, resolve_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.decisions.models import OPEN_STATUSES, OwnerDecision  # noqa: PLC0415
    from app.decisions.services import (  # noqa: PLC0415 - decisions import media
        ASKING_INTENTS,
        withdraw_owner_decision,
    )

    approvals = kernel.withdraw_subject_approvals(
        session,
        subject=storyboard_id,
        reason=WITHDRAWN_REASON_RO.format(title=title),
        correlation_id=correlation,
    )
    decisions: list[str] = []
    for row in list(
        session.scalars(
            select(OwnerDecision)
            .where(
                OwnerDecision.subject_id == storyboard_id,
                OwnerDecision.status.in_(OPEN_STATUSES),
            )
            .order_by(OwnerDecision.created_at)
        )
    ):
        closed = withdraw_owner_decision(
            session,
            decision_id=row.id,
            reason_ro=WITHDRAWN_REASON_RO.format(title=title),
            source="owner",
        )
        if closed is not None:
            decisions.append(str(closed.id))
    kinds = _asking_letter_kinds()
    letters: list[str] = []
    for message in list(
        session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.status == "OPEN",
                AgentMessage.to_agent_id.is_(None),
                AgentMessage.intent.in_(ASKING_INTENTS),
            )
            .order_by(AgentMessage.created_at)
        )
    ):
        body = message.body_json if isinstance(message.body_json, dict) else {}
        if not is_for_owner(message) or not _asks_only_about(body, storyboard_id, kinds):
            continue
        resolve_message(
            session,
            message.id,
            resolution=LETTER_RESOLUTION_RO.format(title=title),
            resolved_by="owner",
            correlation_id=correlation,
        )
        letters.append(str(message.id))
    return {"approvals": approvals, "decisions": decisions, "letters": letters}


def _topic_after_close(session: Session, board: Storyboard) -> dict[str, Any]:
    """What holds the film's topic once the film is closed, read the way the day's selection
    reads it (`runbook.stages.topics_in_production`: a topic by its newest script, and that
    script's newest storyboard). Asked before the close it says what the close will do; asked
    after it, what it did. Returns:

    - ``freed``: the topic no longer holds the studio (this film was what held it, or the
      topic is not in production at all);
    - ``held_by``: the newer film of the same topic that still holds it (a sheet's story repair
      writes a new script and storyboard and leaves this one as it was), or None when what
      holds it is a newer script with no storyboard yet;
    - ``others``: how many other topics are in production; the next run continues them before
      it chooses a new one (`_selection` refuses while any is live)."""
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.runbook.stages import topics_in_production  # noqa: PLC0415 - runbook imports media

    live, _stalled = topics_in_production(session)
    script = session.get(ScriptDraft, board.script_draft_id) if board.script_draft_id else None
    topic_id = script.topic_id if script is not None else None
    others = len([topic for topic in live if topic != topic_id])
    freed = {"topic_id": topic_id, "freed": True, "held_by": None, "others": others}
    if topic_id is None or topic_id not in live:
        return freed
    # The newest script of the topic, and its newest storyboard, as `topics_in_production`
    # picks them (oldest first, the last one wins).
    newest: ScriptDraft | None = None
    for row in session.scalars(
        select(ScriptDraft).where(ScriptDraft.topic_id == topic_id).order_by(ScriptDraft.created_at)
    ):
        newest = row
    holder: Storyboard | None = None
    if newest is not None:
        for candidate in session.scalars(
            select(Storyboard)
            .where(Storyboard.script_draft_id == newest.id)
            .order_by(Storyboard.created_at)
        ):
            holder = candidate
    if holder is not None and holder.id == board.id:
        return freed  # before the close: this film holds its topic, and closing it frees it
    return {
        "topic_id": topic_id,
        "freed": False,
        "held_by": (
            {"storyboard_id": holder.id, "title": _title(holder)} if holder is not None else None
        ),
        "others": others,
    }


def topic_words(topic: dict[str, Any]) -> str:
    """What the close does to the film's topic, as a clause (`_topic_after_close`)."""
    if not topic.get("freed", True):
        held = topic.get("held_by")
        if isinstance(held, dict):
            return (
                f"subiectul lui rămâne în lucru prin filmul mai nou «{held.get('title')}», deci "
                "rularea următoare nu alege alt subiect cât timp acela stă deschis"
            )
        return (
            "subiectul lui rămâne în lucru printr-un scenariu mai nou, încă fără storyboard, "
            "deci rularea următoare nu alege încă alt subiect"
        )
    others = int(topic.get("others") or 0)
    if not others:
        return "subiectul lui nu mai ține studioul pe loc, iar rularea următoare alege alt subiect"
    rest = (
        "alt subiect este încă în lucru, iar rularea următoare îl continuă"
        if others == 1
        else f"alte {count(others, 'subiect', 'subiecte')} sunt încă în lucru, iar rularea "
        "următoare le continuă"
    )
    return f"subiectul lui nu mai ține studioul pe loc; {rest} înainte să aleagă unul nou"


def _closing(session: Session, storyboard_id: str, spent: int) -> dict[str, Any]:
    """How the film was closed, from its newest closing event (`runbook.film_retired`). A film
    REJECTED some other way (a storyboard its script's newer one replaced) has no such event:
    its bought takes are counted from the books now and ``spent`` (read live by the caller)
    stands for what the books hold, so it is never said that nothing was bought for it."""
    from app.runbook.stages import (  # noqa: PLC0415 - runbook imports media
        FILM_RETIRED_EVENT,
        bought_takes_of,
    )

    event = session.scalar(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == FILM_RETIRED_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    )
    if event is None:
        return {
            "closed_by": None,
            "closed_at": None,
            "bought_takes": bought_takes_of(session, storyboard_id),
            "spent_usd_micros": int(spent),
            "event_id": None,
        }
    payload = event.payload if isinstance(event.payload, dict) else {}
    return {
        "closed_by": payload.get("retired_by"),
        "closed_at": event.timestamp,
        "bought_takes": dict(payload.get("bought_takes") or {}),
        "spent_usd_micros": int(payload.get("spent_usd_micros") or 0),
        "event_id": event.event_id,
    }


def closed_words(title: str, bought: dict[str, int], spent: int, topic: dict[str, Any]) -> str:
    """The close in his words: nothing more is bought, what was bought stays in the books, and
    what now holds its topic (`topic_words`)."""
    from app.runbook.stages import TAKE_WORDS, _usd_words  # noqa: PLC0415 - runbook imports media

    items = [count(bought[kind], *TAKE_WORDS[kind]) for kind in TAKE_WORDS if bought.get(kind)]
    if items or spent:
        what = (
            f"ce s-a cumpărat pentru el ({', '.join(items) or 'fără preluări'}; "
            f"{_usd_words(spent)} în registre) rămâne în registre"
        )
    else:
        what = "pentru el nu s-a cumpărat nimic"
    return CLOSED_WORDS_RO.format(title=title, bought_words=what, topic_words=topic_words(topic))


def _answer(
    storyboard_id: str,
    title: str,
    closing: dict[str, Any],
    withdrawn: dict[str, list[str]],
    topic: dict[str, Any],
    *,
    already: bool,
    command_id: str,
) -> dict[str, Any]:
    bought = dict(closing.get("bought_takes") or {})
    spent = int(closing.get("spent_usd_micros") or 0)
    words = closed_words(title, bought, spent, topic)
    asked = sum(len(ids) for ids in withdrawn.values())
    if asked:
        words += " " + count(asked, "întrebare către tine retrasă", "întrebări către tine retrase")
        words += "."
    if already:
        words = "Filmul era deja închis. " + words
    return {
        "command_id": command_id,
        "status": "CLOSED",
        "storyboard_id": storyboard_id,
        "title": title,
        "already_closed": already,
        "closed_by": closing.get("closed_by"),
        "closed_at": closing.get("closed_at"),
        "bought_takes": bought,
        "spent_usd_micros": spent,
        "event_id": closing.get("event_id"),
        "withdrawn": withdrawn,
        "topic": topic,
        "words_ro": words,
    }


def close_film(engine: Engine, storyboard_id: str, command: CloseFilmCommand) -> dict[str, Any]:
    """Close one film for the Owner. Raises `FilmCloseNotFound` (404), `FilmCloseRefused`
    (409) and `app.services.CommandConflict` (409, a command id reused for another command);
    otherwise returns what the close did (``status: CLOSED``)."""
    from app.runbook.stages import film_spent_micros  # noqa: PLC0415 - runbook imports media

    identifier = str(command.command_id)
    digest = command_hash({"storyboard_id": storyboard_id, **command.model_dump(mode="json")})
    with Session(engine) as session:
        previous = recall_command(session, identifier, digest)
        if previous is not None:
            return previous
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise FilmCloseNotFound("Filmul nu există.")
        title = _title(board)
        # Closed: REJECTED with no finished render. A REJECTED film with one (a viewing the
        # Director refused) is not closed here; `_unclosable` says why.
        closed = film_is_closed(session, storyboard_id)
        if not closed:
            # The refusals that need no lease are said before the film is held at all.
            refused = _unclosable(session, board) or _in_flight(session, storyboard_id, title)
            if refused is not None:
                raise refused
    if closed:
        # Nothing is bought for a closed film, so its books are read without its lease.
        spent = film_spent_micros(engine, storyboard_id)
        return _commit(engine, storyboard_id, command, digest, spent=spent)
    correlation = str(uuid4())
    try:
        # The film's purchase lease, as a buyer takes it: a purchase running now refuses the
        # close (FILM_BUSY), and none can start while it closes; after it, every holder meets
        # the closed film at the lease (`shooting_sheet.FilmClosed`).
        with film_purchase_lease(
            engine, storyboard_id, holder=correlation, step=CLOSE_LEASE_STEP, ttl_seconds=600
        ):
            # Read under the lease: every purchase that finished before it is in this figure,
            # as its takes are in the count `close_film_books` makes.
            spent = film_spent_micros(engine, storyboard_id)
            return _commit(
                engine, storyboard_id, command, digest, spent=spent, correlation=correlation
            )
    except FilmBusy as exc:
        if exc.lease.get("step") == CLOSE_LEASE_STEP:
            # Another press of «Închide filmul» holds it: that one closes the film.
            raise FilmCloseRefused(FILM_BUSY, CLOSING_NOW_RO) from exc
        raise FilmCloseRefused(FILM_BUSY, f"{exc.reason_ro} {NOT_WHILE_BUYING_RO}") from exc


def _commit(
    engine: Engine,
    storyboard_id: str,
    command: CloseFilmCommand,
    digest: str,
    *,
    spent: int,
    correlation: str | None = None,
) -> dict[str, Any]:
    """The close itself, in one transaction behind the studio's write lock: the film read again,
    the questions withdrawn, the film closed (or found closed), the answer remembered."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.runbook.stages import close_film_books  # noqa: PLC0415 - runbook imports media

    identifier = str(command.command_id)
    correlation = correlation or str(uuid4())
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        previous = recall_command(session, identifier, digest)
        if previous is not None:
            return previous  # a double press of the same command got here first
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise FilmCloseNotFound("Filmul nu există.")
        title = _title(board)
        already = film_is_closed(session, storyboard_id)
        if not already:
            # Read again under the lease and the write lock: what was true before may not be.
            refused = _unclosable(session, board) or _in_flight(session, storyboard_id, title)
            if refused is not None:
                raise refused
        withdrawn = _withdraw_questions(session, storyboard_id, title, correlation)
        if already:
            closing = _closing(session, storyboard_id, spent)
        else:
            previous_status = str(board.status)
            # What the close will do to the topic, for its event; the answer reads it again
            # once the film is closed (the same reading, after the fact).
            expected = _topic_after_close(session, board)
            closing = close_film_books(
                session,
                board,
                spent=spent,
                retired_by=OWNER,
                correlation=correlation,
                details={
                    "previous_status": previous_status,
                    "reason": "Închis de Owner («Închide filmul»).",
                    "note": command.note,
                    "command_id": identifier,
                    "withdrawn": {key: len(ids) for key, ids in withdrawn.items()},
                    "topic": expected,
                },
            )
            closing = {**closing, "closed_by": OWNER}
            session.flush()
        topic = _topic_after_close(session, board)
        answer = _answer(
            storyboard_id,
            title,
            closing,
            withdrawn,
            topic,
            already=already,
            command_id=identifier,
        )
        remember_command(session, identifier, CLOSE_COMMAND, digest, answer)
    logger.info(
        "film_closed_by_owner",
        extra={"storyboard_id": storyboard_id, "already_closed": already},
    )
    return answer


def closure_view(engine: Engine, storyboard_id: str) -> dict[str, Any]:
    """What the shooting sheet shows about closing the film: whether it is closed (by whom,
    when, with what), or whether «Închide filmul» can close it now, with the reason it cannot,
    and what the close does to its topic (``topic_ro``). A read: nothing is held, written or
    called."""
    from app.runbook.stages import film_spent_micros  # noqa: PLC0415 - runbook imports media

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise FilmCloseNotFound("Filmul nu există.")
        closed = film_is_closed(session, storyboard_id)
    # The books are read in a session of their own (`film_spend_micros`), never inside another.
    spent = film_spent_micros(engine, storyboard_id) if closed else 0
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise FilmCloseNotFound("Filmul nu există.")
        title = _title(board)
        topic = _topic_after_close(session, board)
        if closed:
            closing = _closing(session, storyboard_id, spent)
            bought = dict(closing.get("bought_takes") or {})
            spent_books = int(closing.get("spent_usd_micros") or 0)
            return {
                "closed": True,
                "closable": False,
                "reason_ro": None,
                "closed_by": closing.get("closed_by"),
                "closed_at": closing.get("closed_at"),
                "bought_takes": bought,
                "spent_usd_micros": spent_books,
                "topic": topic,
                "topic_ro": sentence(topic_words(topic)),
                "words_ro": closed_words(title, bought, spent_books, topic),
            }
        refused = _unclosable(session, board)
    lease = current_lease(engine, storyboard_id)
    return {
        "closed": False,
        "closable": refused is None,
        "reason_ro": refused.reason_ro if refused is not None else None,
        "busy": lease is not None,
        "closed_by": None,
        "closed_at": None,
        "bought_takes": {},
        "spent_usd_micros": 0,
        "topic": topic,
        # What closing would do to the topic, for the confirmation of «Închide filmul».
        "topic_ro": sentence(topic_words(topic)),
        "words_ro": None,
    }
