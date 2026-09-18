"""The serial's day, as one runbook stage: project, write, review, approve, storyboard.

The runbook's `serial_queue` stage wrote an episode and stopped. This runner carries the
newest closed day without an episode through to a storyboard the media stage can render in
the same run, and reports each step by count, so a run that produced no film says which step
it stopped at and why.

The contract is the one `app.runbook.stages` uses: ``{"status", "reason", "artefacts"}``;
COMPLETED means the stage ran to its end (a quiet day, a refused draft and an episode left
for the Owner all count), SKIPPED means it could not run (no language model). A content
refusal — the showrunner's answer was not an episode, a beat cited a private event, the
Director's FAIL twice — is recorded in the outcome and never raised: it is the grounding and
the review doing their work. Only a provider or network fault is raised, as
`TransientStageError`, so the runbook retries it in place instead of opening safe mode; a
hard fault is re-raised as it is, because retrying a bug is how a night is spent.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.media.serial_storyboard import SerialStoryboardError, storyboard_from_episode
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.review import ReviewError, review_episode
from app.story.services import (
    NothingHappened,
    StoryError,
    business_date,
    ensure_projection,
    write_episode,
)

logger = logging.getLogger("studio.story.stage")

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"
#: How many drafts one day gets: the first, and one rewrite with the Director's notes.
MAX_DRAFTS = 2


def _outcome(status: str, reason: str, **artefacts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason[:300], "artefacts": artefacts}


def _transient(exc: BaseException) -> bool:
    from app.runbook.services import TRANSIENT, classify_fault  # noqa: PLC0415

    return classify_fault(exc) == TRANSIENT


def pending_log(session: Session, before: str | None = None) -> DailyStudioLog | None:
    """The newest CLOSED log with no episode at all, of a day before ``before``.

    A log whose drafts were all rejected is finished with: the rewrite budget was spent on
    it, and a third attempt tomorrow would be the same day told a third time.

    ``before`` is today's business date: the day's own log is closed at the end of every
    attempt (the daily_log stage), so a same-day re-attempt found today's log closed and
    newest, and filmed an episode of a day not yet over — measured on 2026-09-19, a serial
    film the first attempt never decided on, bought by the re-attempt.
    """
    written = set(session.scalars(select(StoryEpisode.log_id)))
    query = select(DailyStudioLog).where(DailyStudioLog.status == "CLOSED")
    if before is not None:
        query = query.where(DailyStudioLog.business_date < before)
    for log in session.scalars(query.order_by(DailyStudioLog.business_date.desc()).limit(5)):
        if log.id not in written:
            return log
    return None


def run_serial_stage(
    engine: Engine, registry: Any, settings: Any, vault: Any = None
) -> dict[str, Any]:
    """Project -> write -> review (one rewrite) -> approve under policy -> storyboard."""
    if not registry.registered_ids():
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    counts: dict[str, Any] = {
        "projected": 0,
        "written": 0,
        "reviewed": 0,
        "rewritten": 0,
        "approved": 0,
        "episodes": 0,
        "storyboard_id": None,
        "episode_id": None,
        "refusal": None,
    }
    language = getattr(settings, "content_language", "en")
    correlation = str(uuid4())

    try:
        with Session(engine) as session, session.begin():
            log = pending_log(
                session, before=business_date(getattr(settings, "timezone", None) or "UTC")
            )
            if log is None:
                return _outcome(COMPLETED, "Nicio zi închisă fără episod.", **counts)
            log_id, date_iso = log.id, log.business_date
            counts["projected"] = len(ensure_projection(session, log))
        if counts["projected"] == 0:
            return _outcome(
                COMPLETED,
                f"În {date_iso} nu s-a întâmplat nimic de povestit public; o zi liniștită "
                "este un fapt, nu un motiv de a inventa un episod.",
                **counts,
            )

        notes: str | None = None
        rewrite_of: str | None = None
        episode: dict[str, Any] | None = None
        review: dict[str, Any] | None = None
        for attempt in range(1, MAX_DRAFTS + 1):
            try:
                written = write_episode(
                    engine,
                    registry,
                    log_id,
                    str(uuid4()),
                    language=language,
                    notes=notes,
                    rewrite_of=rewrite_of,
                )
            except NothingHappened as exc:
                return _outcome(COMPLETED, str(exc), **counts)
            except StoryError as exc:
                # The showrunner's answer was not an episode, or a beat cited what it may
                # not: nothing was stored, which is the grounding working. Not the day's
                # failure.
                logger.info("episode_refused", extra={"log_id": log_id, "reason": str(exc)[:200]})
                counts["refusal"] = str(exc)[:300]
                return _outcome(COMPLETED, f"Episod respins: {exc}", **counts)
            episode = written["episode"]
            counts["written"] += 1
            counts["episodes"] += 1
            counts["episode_id"] = episode["id"]
            if attempt > 1:
                counts["rewritten"] += 1
            try:
                review = review_episode(
                    engine, registry, episode["id"], str(uuid4()), language=language
                )
            except ReviewError as exc:
                counts["refusal"] = str(exc)[:300]
                return _outcome(COMPLETED, f"Episodul nu a putut fi citit: {exc}", **counts)
            counts["reviewed"] += 1
            if review["verdict"] == "PASS":
                break
            notes = review.get("notes") or "; ".join(review.get("reasons") or [])
            rewrite_of = episode["id"]

        assert episode is not None and review is not None  # the loop ran at least once
        if review["verdict"] != "PASS":
            counts["refusal"] = f"FAIL: {notes}"[:300]
            return _outcome(
                COMPLETED,
                f"Episodul pentru {date_iso} a fost respins de Director după o rescriere: {notes}",
                **counts,
            )
        if review["status"] != "APPROVED":
            return _outcome(
                COMPLETED,
                f"Episodul pentru {date_iso} a trecut citirea Directorului și așteaptă "
                "aprobarea ta; politica canalului nu îi permite Directorului să aprobe singură.",
                **counts,
            )
        counts["approved"] += 1
        try:
            counts["storyboard_id"] = storyboard_from_episode(engine, episode["id"], correlation)
        except SerialStoryboardError as exc:
            counts["refusal"] = str(exc)[:300]
            return _outcome(COMPLETED, f"Episodul aprobat nu a devenit storyboard: {exc}", **counts)
        return _outcome(
            COMPLETED,
            f"Episodul pentru {date_iso} a fost scris, citit, aprobat și pregătit de filmare.",
            **counts,
        )
    except Exception as exc:
        if _transient(exc):
            from app.runbook.services import TransientStageError  # noqa: PLC0415

            raise TransientStageError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        raise
