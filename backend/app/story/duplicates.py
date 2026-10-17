"""One day of the serial: one approved episode, one film (2026-10-17).

Measured on his database at 2026-10-16 23:15:17Z, the day run for 2026-10-17, stage
serial_queue. The log of 2026-10-16 («Zero Scripts, Blocked Log») had two REJECTED drafts,
8caad7d9 — a DRAFT whose PASS was held for the editorial judgement — and b8684fc5, the
Director's rewrite of 8caad7d9 (``rewrite_of_id``), APPROVED the evening before, its film
87c05891 in production with paid stills and clips. A run had stopped inside the judgement, so
its last step — retire the versions that do not ship, approve the one that does — never ran;
the evening's script approved the newest version and left the older one a held PASS. The next
morning `unfinished_episodes` took that held PASS up as unfinished work and approved it: canon
moved to episode 5 on it, and a second film of the same day, a7db1594, was built from it — a
second film on a subject already made, about 9 USD of a 30 USD day, nothing bought yet.

So, here:

- a DRAFT is *superseded* (`superseded_by`) when its day already has an approved episode, or
  when a newer version of it in its rewrite chain still stands (a DRAFT or APPROVED: a rewrite
  the review refused replaces nothing). A superseded draft is never resumed, approved or
  filmed; an approval closes the day's other drafts at once (`close_superseded_drafts`);
- a day never gets a second approved episode (`approved_sibling`, read by every approval) nor
  a second live film (`live_film_of_day`, read by the storyboard build), and a film that is a
  day's second, or whose episode is no longer approved, is closed for every purchase
  (`serial_film_superseded`, read by `media.shooting_sheet.film_is_closed`);
- what the bug already made is repaired by the studio itself (`repair_duplicate_days`, run by
  the serial stage and by the watchdog pass `serial_duplicates` before the day is resumed):
  the day's first approved episode keeps its number and its film; a later one is closed as
  superseded, its film retired through the Director's own closing
  (`runbook.stages.close_film_books`), and canon is told again without it
  (`story.services.rebuild_continuity`). No letter, no card: the register says it.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import DomainEvent
from app.story.models import DailyStudioLog, StoryEpisode

logger = logging.getLogger("studio.story.duplicates")

#: The event of an episode closed because its day already has its approved episode.
SUPERSEDED_EVENT = "story.episode_superseded"
#: The event every approval leaves, the Director's or the Owner's: the order of approvals.
APPROVED_EVENT = "story.episode_approved"
#: The rule, in the words every note and reason here ends on.
ONE_DAY_ONE_FILM_RO = "O zi a serialului are un singur episod aprobat și un singur film."


def _approval_order(session: Session, episode: StoryEpisode) -> tuple[int, str]:
    """Where ``episode`` stands among the day's approvals: its first approval event, then its
    writing; an episode approved with no event (none is) comes last."""
    sequence = session.scalar(
        select(func.min(DomainEvent.sequence)).where(
            DomainEvent.event_type == APPROVED_EVENT, DomainEvent.aggregate_id == episode.id
        )
    )
    return (int(sequence) if sequence is not None else 1 << 62, str(episode.created_at))


def _approved_at(session: Session, episode: StoryEpisode) -> str:
    moment = session.scalar(
        select(DomainEvent.timestamp)
        .where(DomainEvent.event_type == APPROVED_EVENT, DomainEvent.aggregate_id == episode.id)
        .order_by(DomainEvent.sequence)
        .limit(1)
    )
    return str(moment or episode.created_at)[:16].replace("T", " ")


def approved_sibling(session: Session, episode: StoryEpisode) -> StoryEpisode | None:
    """The day's approved episode other than ``episode`` (the first approved), or None."""
    rows = session.scalars(
        select(StoryEpisode).where(
            StoryEpisode.log_id == episode.log_id,
            StoryEpisode.status == "APPROVED",
            StoryEpisode.id != episode.id,
        )
    ).all()
    return min(rows, key=lambda row: _approval_order(session, row)) if rows else None


def second_approval(session: Session, episode: StoryEpisode) -> bool:
    """Whether an APPROVED ``episode`` was approved after another approved episode of its day."""
    first = approved_sibling(session, episode)
    return first is not None and _approval_order(session, first) < _approval_order(session, episode)


def live_rewrite(session: Session, episode: StoryEpisode) -> StoryEpisode | None:
    """The newest version written after ``episode`` in its rewrite chain that still stands
    (DRAFT or APPROVED), or None. A rewrite the review refused replaces nothing."""
    frontier, seen, standing = [episode.id], {episode.id}, []
    while frontier:
        children = session.scalars(
            select(StoryEpisode).where(
                StoryEpisode.rewrite_of_id.in_(frontier),
                StoryEpisode.log_id == episode.log_id,
            )
        ).all()
        frontier = []
        for child in children:
            if child.id in seen:
                continue
            seen.add(child.id)
            frontier.append(child.id)
            if child.status in ("DRAFT", "APPROVED"):
                standing.append(child)
    return max(standing, key=lambda row: str(row.created_at)) if standing else None


def superseded_by(session: Session, episode: StoryEpisode) -> StoryEpisode | None:
    """What replaced a DRAFT: its day's approved episode, else a newer standing version of it;
    None while it is still the day's draft to take up."""
    return approved_sibling(session, episode) or live_rewrite(session, episode)


def _rewrote(session: Session, newer: StoryEpisode, older: StoryEpisode) -> bool:
    """Whether ``newer`` descends from ``older`` in the rewrite chain."""
    seen: set[str] = set()
    step = newer.rewrite_of_id
    while step and step not in seen:
        if step == older.id:
            return True
        seen.add(step)
        row = session.get(StoryEpisode, step)
        step = row.rewrite_of_id if row is not None else None
    return False


def live_film_of_day(session: Session, episode: StoryEpisode) -> tuple[StoryEpisode, str] | None:
    """Another episode of ``episode``'s day with a film still standing (a storyboard not
    REJECTED), as (that episode, its storyboard id), or None."""
    from app.media.models import Storyboard  # noqa: PLC0415 - media imports story

    row = session.execute(
        select(StoryEpisode, Storyboard.id)
        .join(Storyboard, Storyboard.id == StoryEpisode.storyboard_id)
        .where(
            StoryEpisode.log_id == episode.log_id,
            StoryEpisode.id != episode.id,
            Storyboard.status != "REJECTED",
        )
        .order_by(Storyboard.created_at)
        .limit(1)
    ).first()
    return (row[0], str(row[1])) if row is not None else None


def serial_film_superseded(session: Session, storyboard_id: str) -> bool:
    """Refuse production when its episode is no longer APPROVED or was approved after
    another episode of the same day. Approval events, not storyboard timestamps, decide."""
    episode = session.scalar(
        select(StoryEpisode).where(StoryEpisode.storyboard_id == storyboard_id).limit(1)
    )
    if episode is None:
        return False
    if episode.status != "APPROVED":
        return True
    # Approval order is durable and remains decisive even when creation timestamps tie
    # or the first film is temporarily REJECTED by QC.
    return second_approval(session, episode)


def _close(
    session: Session, episode: StoryEpisode, newer: StoryEpisode, note: str, correlation: str
) -> None:
    """``episode`` closed as superseded by ``newer``: REJECTED as the Director's, the reason as
    its note, and one `SUPERSEDED_EVENT` that says it."""
    from app.services import append_event  # noqa: PLC0415 - app.services is large

    was = episode.status
    episode.status = "REJECTED"
    episode.notes = note[:2000]
    episode.reviewed_by = "director"
    review = dict(episode.review_json or {})
    if review:
        episode.review_json = {**review, "held_for_judgement": False, "superseded_by": newer.id}
    episode.event_id = append_event(
        session,
        SUPERSEDED_EVENT,
        "story_episode",
        episode.id,
        4,
        {
            "log_id": episode.log_id,
            "title": episode.title,
            "was": was,
            "superseded_by": newer.id,
            "superseded_by_title": newer.title,
            "storyboard_id": episode.storyboard_id,
            "reason": note[:600],
        },
        correlation,
    ).event_id


def _draft_note(session: Session, episode: StoryEpisode, newer: StoryEpisode) -> str:
    named = f"«{newer.title}» ({newer.id[:8]})"
    if _rewrote(session, newer, episode):
        lead = f"Înlocuit: Directoarea l-a rescris în {named}, " + (
            "aprobat pentru aceeași zi."
            if newer.status == "APPROVED"
            else "versiunea care merge mai departe."
        )
    else:
        lead = f"Înlocuit: ziua lui are deja episodul aprobat {named}."
    return f"{lead} {ONE_DAY_ONE_FILM_RO}"


def close_as_superseded(
    session: Session, draft: StoryEpisode, newer: StoryEpisode, correlation: str
) -> None:
    """A DRAFT an approval would have made the day's second approved episode, closed instead."""
    _close(session, draft, newer, _draft_note(session, draft, newer), correlation)


def close_superseded_drafts(
    session: Session, approved: StoryEpisode, correlation: str
) -> list[str]:
    """The day's other DRAFTs, closed as superseded by ``approved``, in the approval's own
    transaction: a draft left standing beside the day's approved episode was taken up as
    unfinished work and approved a second time (2026-10-16 23:15Z)."""
    closed: list[str] = []
    for draft in session.scalars(
        select(StoryEpisode).where(
            StoryEpisode.log_id == approved.log_id,
            StoryEpisode.status == "DRAFT",
            StoryEpisode.id != approved.id,
        )
    ).all():
        _close(session, draft, approved, _draft_note(session, draft, approved), correlation)
        closed.append(draft.id)
    return closed


def _duplicate_words(
    session: Session,
    episode: StoryEpisode,
    keeper: StoryEpisode,
    date_iso: str,
    board_id: str | None,
    items: list[str] | None,
) -> str:
    named = f"«{keeper.title}» ({keeper.id[:8]})"
    if _rewrote(session, keeper, episode):
        lead = (
            "Aprobare retrasă, era o dublură: o versiune mai veche, pe care Directoarea o "
            f"rescrisese deja în {named}, aprobat la {_approved_at(session, keeper)} UTC și "
            "aflat la filmare."
        )
    else:
        lead = (
            f"Aprobare retrasă, era o dublură: ziua {date_iso} avea deja episodul aprobat "
            f"{named}, aflat la filmare."
        )
    film = ""
    if board_id:
        bought = (
            f"cumpărat pentru el: {', '.join(items)}"
            if items
            else "fără să se fi cumpărat ceva pentru el"
        )
        film = f" Al doilea film al aceleiași zile ({board_id[:8]}) a fost închis, {bought}."
    return f"{lead}{film} Numărul din serial rămâne al episodului {keeper.id[:8]}. " + (
        ONE_DAY_ONE_FILM_RO
    )


def _retire_duplicate(
    engine: Engine, episode_id: str, keeper_id: str, board_id: str | None, correlation: str
) -> dict[str, Any] | None:
    """One later approval of a day undone: its film closed, canon told again without it, the
    episode closed as superseded — one transaction. None when nothing is to be done; with
    ``waiting`` when a purchase of its film may be in flight (the next pass tries again)."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.film_close import _in_flight  # noqa: PLC0415 - media imports story
    from app.media.models import Storyboard  # noqa: PLC0415
    from app.media.shooting_sheet import current_lease  # noqa: PLC0415
    from app.runbook.stages import close_film_books, film_spent_micros  # noqa: PLC0415
    from app.story.services import rebuild_continuity  # noqa: PLC0415 - services imports us

    if board_id and current_lease(engine, board_id) is not None:
        return {"episode_id": episode_id, "waiting": board_id}
    spent = film_spent_micros(engine, board_id) if board_id else 0
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        episode = session.get(StoryEpisode, episode_id)
        keeper = session.get(StoryEpisode, keeper_id)
        if episode is None or keeper is None:
            return None
        if episode.status != "APPROVED" or keeper.status != "APPROVED":
            return None
        log = session.get(DailyStudioLog, episode.log_id)
        date_iso = log.business_date if log is not None else "?"
        board = session.get(Storyboard, board_id) if board_id else None
        items: list[str] | None = None
        film: dict[str, Any] | None = None
        if board is not None and board.status != "REJECTED":
            title = str(board.title or board.id[:8]).removeprefix("Storyboard: ")
            if _in_flight(session, board.id, title) is not None:
                return {"episode_id": episode_id, "waiting": board.id}
            film = close_film_books(
                session,
                board,
                spent=spent,
                retired_by="Director",
                correlation=correlation,
                details={
                    "reason": (
                        f"Dublura zilei {date_iso}: episodul «{episode.title}» a fost "
                        f"aprobat a doua oară ({episode.id[:8]}), deși ziua avea deja "
                        f"episodul aprobat {keeper.id[:8]} cu filmul "
                        f"{str(keeper.storyboard_id or '')[:8] or 'lui'}. Filmul zilei rămâne "
                        "acela; pentru acesta nu se mai cumpără nimic. " + ONE_DAY_ONE_FILM_RO
                    ),
                    "episode_id": episode.id,
                    "kept_episode_id": keeper.id,
                    "kept_storyboard_id": keeper.storyboard_id,
                    "business_date": date_iso,
                },
            )
            items = list(film["items"])
        continuity = rebuild_continuity(
            session,
            {episode.id},
            f"Episodul {episode.id[:8]} («{episode.title}») a fost aprobat a doua oară pentru "
            f"ziua {date_iso}, care își avea deja episodul aprobat {keeper.id[:8]}; canonul "
            "serialului este refăcut fără el.",
            correlation,
        )
        note = _duplicate_words(session, episode, keeper, date_iso, board_id, items)
        _close(session, episode, keeper, note, correlation)
        drafts = close_superseded_drafts(session, keeper, correlation)
        title = episode.title
    logger.info(
        "serial_duplicate_retired",
        extra={"episode_id": episode_id, "kept": keeper_id, "storyboard_id": board_id},
    )
    return {
        "episode_id": episode_id,
        "kept_episode_id": keeper_id,
        "title": title,
        "date": date_iso,
        "storyboard_id": board_id if film is not None else None,
        "bought_takes": (film or {}).get("bought_takes") or {},
        "drafts_closed": drafts,
        "canon_episode_number": (continuity or {}).get("canon_episode_number"),
        "canon_before": (continuity or {}).get("before"),
        "canon_method": (continuity or {}).get("method"),
    }


def repair_duplicate_days(engine: Engine, correlation: str | None = None) -> dict[str, Any]:
    """Every day with two approved episodes put back to one, and every draft left standing
    beside a day's approved episode closed. Idempotent: a second call finds nothing; a quiet
    call takes no write lock.

    Returns ``retired`` (one item per later approval undone: its film, what was bought for it,
    canon before and after), ``waiting`` (a film with a purchase in flight, tried again by the
    next call) and ``drafts_closed``."""
    from app.db import lock_for_write  # noqa: PLC0415

    correlation = correlation or str(uuid4())
    done: dict[str, Any] = {"retired": [], "waiting": [], "drafts_closed": []}
    with Session(engine) as session:
        doubled = session.scalars(
            select(StoryEpisode.log_id)
            .where(StoryEpisode.status == "APPROVED")
            .group_by(StoryEpisode.log_id)
            .having(func.count(StoryEpisode.id) > 1)
        ).all()
        pairs: list[tuple[str, str, str | None]] = []
        for log_id in doubled:
            approved = sorted(
                session.scalars(
                    select(StoryEpisode).where(
                        StoryEpisode.log_id == log_id, StoryEpisode.status == "APPROVED"
                    )
                ).all(),
                key=lambda row: _approval_order(session, row),
            )
            pairs += [(row.id, approved[0].id, row.storyboard_id) for row in approved[1:]]
        stray = session.scalars(
            select(StoryEpisode.id).where(
                StoryEpisode.status == "DRAFT",
                StoryEpisode.log_id.in_(
                    select(StoryEpisode.log_id).where(StoryEpisode.status == "APPROVED")
                ),
            )
        ).all()
    for episode_id, keeper_id, board_id in pairs:
        retired = _retire_duplicate(engine, episode_id, keeper_id, board_id, correlation)
        if retired is None:
            continue
        if retired.get("waiting"):
            done["waiting"].append(retired)
            continue
        done["retired"].append(retired)
        done["drafts_closed"] += retired.get("drafts_closed") or []
    stray = [episode_id for episode_id in stray if episode_id not in done["drafts_closed"]]
    if stray:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            for episode_id in stray:
                draft = session.get(StoryEpisode, episode_id)
                if draft is None or draft.status != "DRAFT":
                    continue
                newer = approved_sibling(session, draft)
                if newer is None:
                    continue
                _close(session, draft, newer, _draft_note(session, draft, newer), correlation)
                done["drafts_closed"].append(episode_id)
    return done


def repair_words(done: dict[str, Any]) -> str:
    """What `repair_duplicate_days` did, in one or two sentences for the stage's reason; ""
    when it did nothing."""
    parts: list[str] = []
    for item in done.get("retired") or []:
        bought = item.get("bought_takes") or {}
        film = (
            f"filmul ei dublură ({str(item['storyboard_id'])[:8]}) a fost închis"
            + (" fără nimic cumpărat" if not any(bought.values()) else "")
            if item.get("storyboard_id")
            else "nu avea film"
        )
        canon = (
            f"; serialul revine la episodul {item['canon_episode_number']}"
            if item.get("canon_episode_number") is not None
            and item.get("canon_episode_number") != item.get("canon_before")
            else ""
        )
        parts.append(
            f"Ziua {item.get('date')} avea două episoade aprobate: dublura "
            f"{str(item['episode_id'])[:8]} a fost retrasă, {film}{canon}."
        )
    if done.get("waiting"):
        parts.append("Un film dublură are o cumpărare în curs; se închide la trecerea următoare.")
    return " ".join(parts)
