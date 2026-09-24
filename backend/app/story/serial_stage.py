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
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.media.serial_storyboard import (
    SerialStoryboardError,
    describe_serial_shots,
    storyboard_from_episode,
)
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.review import ReviewError, review_episode
from app.story.services import (
    DraftRefused,
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
#: How far back the stage takes up an episode an earlier run left unfinished. A week: the
#: serial tells recent days, and an episode older than that is left for the Owner's hand.
RESUME_WINDOW_DAYS = 7


def _outcome(status: str, reason: str, **artefacts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason[:300], "artefacts": artefacts}


def _transient(exc: BaseException) -> bool:
    from app.runbook.services import TRANSIENT, classify_fault  # noqa: PLC0415

    return classify_fault(exc) == TRANSIENT


def day_to_tell(session: Session, before: str) -> tuple[DailyStudioLog | None, list[str]]:
    """The newest CLOSED log of a day before ``before`` that has something public to tell,
    and the quiet days passed over on the way to it (newest first).

    Measured on 2026-09-24 on the readers' copy of his database: the stage took the newest
    closed day with no episode, which was yesterday, and yesterday had no event at all — so
    the click made no episode while 2026-09-19 held the studio's last real day. A quiet day
    is still a fact and still not told; the serial goes back to the newest day that happened.

    Three limits. ``before`` is today's business date: the day's own log is closed at the end
    of every attempt, and a same-day re-attempt once filmed a day not yet over (2026-09-19).
    Only days after the newest day that already has an episode, whatever became of it: canon
    runs forward, and a rejected day is finished with (its rewrite budget was spent). And only
    within `RESUME_WINDOW_DAYS`, the window the run closes missing days in.
    """
    since = (date.fromisoformat(before) - timedelta(days=RESUME_WINDOW_DAYS)).isoformat()
    told = session.scalar(
        select(func.max(DailyStudioLog.business_date)).join(
            StoryEpisode, StoryEpisode.log_id == DailyStudioLog.id
        )
    )
    query = select(DailyStudioLog).where(
        DailyStudioLog.status == "CLOSED",
        DailyStudioLog.business_date < before,
        DailyStudioLog.business_date >= since,
    )
    if told is not None:
        query = query.where(DailyStudioLog.business_date > told)
    quiet: list[str] = []
    for log in session.scalars(query.order_by(DailyStudioLog.business_date.desc())):
        if ensure_projection(session, log):
            return log, quiet
        quiet.append(log.business_date)
    return None, quiet


def _last_told(session: Session) -> tuple[str, str, str] | None:
    """(date, title, status) of the newest episode by the day it tells, or None."""
    row = session.execute(
        select(DailyStudioLog.business_date, StoryEpisode.title, StoryEpisode.status)
        .join(StoryEpisode, StoryEpisode.log_id == DailyStudioLog.id)
        .order_by(DailyStudioLog.business_date.desc(), StoryEpisode.created_at.desc())
        .limit(1)
    ).first()
    return (row[0], row[1], row[2]) if row is not None else None


def pending_log(session: Session, before: str) -> DailyStudioLog | None:
    """The log `day_to_tell` would tell, or None."""
    return day_to_tell(session, before)[0]


def _naming_the_day(outcome: dict[str, Any], date_iso: str, quiet: list[str]) -> dict[str, Any]:
    """The stage's reason, led by the day it told and the quiet days it passed over."""
    if quiet:
        lead = (
            f"Ziua povestită: {date_iso}; zilele de după ea ({', '.join(sorted(quiet))}) "
            "nu au evenimente publice. "
        )
    elif date_iso not in outcome["reason"]:
        lead = f"Ziua povestită: {date_iso}. "
    else:
        return outcome
    return {**outcome, "reason": (lead + outcome["reason"])[:300]}


def unfinished_episodes(session: Session, before: str) -> list[tuple[str, StoryEpisode]]:
    """What earlier runs left of the serial, in the order the stage takes it up.

    Measured on 2026-09-24: `pending_log` looks only for a day with no episode at all, so
    every episode already written was finished with. An episode the Owner approved by hand
    was never storyboarded and so never filmed; a Director's answer that could not be read
    lost the day for good; a draft passed and waiting for him was not even named. Returned
    here, oldest day first (the serial's canon order), as ``(kind, episode)``:

    - ``"storyboard"``: APPROVED, with no storyboard yet;
    - ``"review"``: a DRAFT the Director has not read (her answer could not be parsed, or
      the run stopped between the writing and the reading);
    - ``"owner"``: a DRAFT she passed, waiting for the Owner's approval.

    Only days before ``before`` (today's business date, as `pending_log`), and only within
    `RESUME_WINDOW_DAYS`: the Owner's own data holds one DRAFT of 2026-09-12, written before
    the review existed and never read; a draft that old tells a day long gone, and neither a
    model call nor the serial's waiting is spent on it.
    """
    since = (date.fromisoformat(before) - timedelta(days=RESUME_WINDOW_DAYS)).isoformat()
    rows = session.scalars(
        select(StoryEpisode)
        .join(DailyStudioLog, DailyStudioLog.id == StoryEpisode.log_id)
        .where(
            DailyStudioLog.business_date < before,
            DailyStudioLog.business_date >= since,
            StoryEpisode.status.in_(("APPROVED", "DRAFT")),
        )
        .order_by(DailyStudioLog.business_date, StoryEpisode.created_at)
    ).all()
    found: list[tuple[str, StoryEpisode]] = []
    found += [("storyboard", e) for e in rows if e.status == "APPROVED" and not e.storyboard_id]
    found += [("review", e) for e in rows if e.status == "DRAFT" and not e.review_json]
    found += [
        ("owner", e)
        for e in rows
        if e.status == "DRAFT" and (e.review_json or {}).get("verdict") == "PASS"
    ]
    return found


def _ready_for_filming(
    engine: Engine,
    episode_id: str,
    counts: dict[str, Any],
    correlation: str,
    registry: Any = None,
) -> bool:
    """Build the storyboard of an APPROVED episode; False (with the reason) when it cannot be.

    `storyboard_from_episode` returns the one an episode already has, so a second call never
    builds a second storyboard. Its shots are then described from the beats by the video
    editor's model (S8), once per series look: a second call asks no model again, and
    without a model the shots keep the look the storyboard composed them with.
    """
    try:
        counts["storyboard_id"] = storyboard_from_episode(engine, episode_id, correlation)
    except SerialStoryboardError as exc:
        counts["refusal"] = str(exc)[:300]
        return False
    described = describe_serial_shots(engine, registry, counts["storyboard_id"], correlation)
    counts["shots_described"] = len(described.get("shots") or [])
    return True


def _tell_the_day(
    engine: Engine,
    registry: Any,
    log_id: str,
    date_iso: str,
    counts: dict[str, Any],
    language: str,
    correlation: str,
    draft_id: str | None = None,
    drafts_spent: int = 0,
    film: bool = True,
) -> dict[str, Any]:
    """Write (or take up ``draft_id``), review, rewrite once on a FAIL, approve, storyboard.

    ``drafts_spent`` is how many drafts the day already had: the budget is `MAX_DRAFTS` per
    day over every run, so a first draft read on the second run and failed still gets its
    one rewrite, and a failed rewrite is the end of the day whenever it was read.

    ``film=False`` is tomorrow's script (`run_serial_next_stage`): everything up to the
    approval, and no storyboard, so nothing of a day not yet over can be filmed.
    """
    notes: str | None = None
    rewrite_of: str | None = None
    refused_answer: str | None = None
    episode_id = draft_id
    drafts = drafts_spent
    while True:
        if episode_id is None:
            try:
                written = write_episode(
                    engine,
                    registry,
                    log_id,
                    str(uuid4()),
                    language=language,
                    notes=notes,
                    rewrite_of=rewrite_of,
                    refused_answer=refused_answer,
                )
            except NothingHappened as exc:
                return _outcome(COMPLETED, str(exc), **counts)
            except DraftRefused as exc:
                # The showrunner's answer was not an episode, or cast or cited what it may
                # not: nothing was stored, which is the grounding working. Until 2026-09-24
                # that ended the day, and one misspelt name lost it; now the refusal spends
                # one of the day's drafts, and the next is asked with the reason and the
                # refused answer. Not stored, so a later run does not count it.
                logger.info("episode_refused", extra={"log_id": log_id, "reason": str(exc)[:200]})
                counts["refusal"] = str(exc)[:300]
                counts["refused"] += 1
                drafts += 1
                if drafts >= MAX_DRAFTS:
                    return _outcome(COMPLETED, f"Episod respins: {exc}", **counts)
                notes, refused_answer, rewrite_of = str(exc), exc.answer, None
                continue
            except StoryError as exc:
                # The showrunner produced no answer at all: nothing to correct, so no retry.
                logger.info("episode_refused", extra={"log_id": log_id, "reason": str(exc)[:200]})
                counts["refusal"] = str(exc)[:300]
                return _outcome(COMPLETED, f"Episod respins: {exc}", **counts)
            refused_answer = None
            episode_id = written["episode"]["id"]
            drafts += 1
            counts["written"] += 1
            counts["episodes"] += 1
            if rewrite_of is not None:
                counts["rewritten"] += 1
        counts["episode_id"] = episode_id
        try:
            review = review_episode(engine, registry, episode_id, str(uuid4()), language=language)
        except ReviewError as exc:
            # The draft stays a DRAFT with no review, and the next run reads it again.
            counts["refusal"] = str(exc)[:300]
            return _outcome(COMPLETED, f"Episodul nu a putut fi citit: {exc}", **counts)
        counts["reviewed"] += 1
        if review["verdict"] == "PASS":
            break
        notes = review.get("notes") or "; ".join(review.get("reasons") or [])
        if drafts >= MAX_DRAFTS:
            counts["refusal"] = f"FAIL: {notes}"[:300]
            return _outcome(
                COMPLETED,
                f"Episodul pentru {date_iso} a fost respins de Director după o rescriere: {notes}",
                **counts,
            )
        rewrite_of, episode_id = episode_id, None

    if review["status"] != "APPROVED":
        with Session(engine) as session:
            episode = session.get(StoryEpisode, episode_id)
            title = episode.title if episode is not None else ""
        return _outcome(
            COMPLETED,
            f"Episodul „{title[:80]}” pentru {date_iso} a trecut citirea Directorului și "
            "așteaptă aprobarea ta; politica canalului nu îi permite Directorului să aprobe "
            "singură.",
            **counts,
        )
    counts["approved"] += 1
    if not film:
        return _outcome(
            COMPLETED,
            f"Scenariul de mâine (ziua {date_iso}) a fost scris, citit și aprobat; rularea de "
            "mâine îl pregătește de filmare și îl filmează.",
            **counts,
        )
    if not _ready_for_filming(engine, episode_id, counts, correlation, registry):
        return _outcome(
            COMPLETED, f"Episodul aprobat nu a devenit storyboard: {counts['refusal']}", **counts
        )
    return _outcome(
        COMPLETED,
        f"Episodul pentru {date_iso} a fost scris, citit, aprobat și pregătit de filmare.",
        **counts,
    )


def _left_by_earlier_runs(engine: Engine, today: str) -> list[dict[str, Any]]:
    """`unfinished_episodes`, read into plain values the stage can use after the session."""
    with Session(engine) as session:
        left = []
        for kind, episode in unfinished_episodes(session, today):
            log = session.get(DailyStudioLog, episode.log_id)
            drafts = session.scalars(
                select(StoryEpisode.id).where(StoryEpisode.log_id == episode.log_id)
            ).all()
            left.append(
                {
                    "kind": kind,
                    "episode_id": episode.id,
                    "title": episode.title,
                    "log_id": episode.log_id,
                    "reviewed_by": episode.reviewed_by,
                    "date": log.business_date if log is not None else "?",
                    "drafts": len(drafts),
                }
            )
        return left


def _new_counts() -> dict[str, Any]:
    return {
        "projected": 0,
        "written": 0,
        #: Answers refused before they were stored (a stranger cast, an invented citation,
        #: not the schema); each spends one of the day's drafts.
        "refused": 0,
        "reviewed": 0,
        "rewritten": 0,
        "approved": 0,
        "episodes": 0,
        "storyboard_id": None,
        #: Shots the video editor's model described from the beats this run (S8).
        "shots_described": 0,
        "episode_id": None,
        "refusal": None,
        "resumed": None,
        #: The business date whose events this run told, when it told a new day.
        "told_date": None,
    }


def run_serial_stage(
    engine: Engine, registry: Any, settings: Any, vault: Any = None
) -> dict[str, Any]:
    """Resume what an earlier run left, else project -> write -> review -> approve -> storyboard.

    The order (see `unfinished_episodes`): an approved episode with no storyboard is readied
    for filming; a draft nobody read is read; a draft waiting for the Owner is named, and no
    new episode is written beside it (the canon number is fixed on his approval, so a second
    draft would claim the same number); only then is a new closed day told. One of these per
    run, as the media stage films one episode a day. Readying and naming need no model, so
    they run before the stage asks for one.
    """
    counts = _new_counts()
    language = getattr(settings, "content_language", "en")
    correlation = str(uuid4())
    today = business_date(getattr(settings, "timezone", None) or "UTC")
    has_model = bool(registry.registered_ids())
    no_model = "Niciun model de limbaj disponibil; agenții nu pot rula."

    try:
        for item in _left_by_earlier_runs(engine, today):
            counts["episode_id"], counts["resumed"] = item["episode_id"], item["kind"]
            title, date_iso = item["title"][:80], item["date"]
            # The day it tells, on the run card too: the morning that films yesterday's
            # script is every morning after the first (rehearsal on a copy, 2026-09-24).
            counts["told_date"] = date_iso
            if item["kind"] == "storyboard":
                if not _ready_for_filming(
                    engine, item["episode_id"], counts, correlation, registry
                ):
                    # Built from rows, so the failure repeats until the episode changes; it
                    # is logged and does not hold up the rest of the day.
                    logger.info(
                        "episode_not_storyboarded",
                        extra={"episode_id": item["episode_id"], "reason": counts["refusal"]},
                    )
                    continue
                who = "tine" if item["reviewed_by"] == "owner" else "Director"
                return _outcome(
                    COMPLETED,
                    f"Episodul „{title}” pentru {date_iso}, aprobat de {who}, a fost "
                    "pregătit de filmare.",
                    **counts,
                )
            if item["kind"] == "review":
                if not has_model:
                    return _outcome(SKIPPED, no_model, **counts)
                return _tell_the_day(
                    engine,
                    registry,
                    item["log_id"],
                    date_iso,
                    counts,
                    language,
                    correlation,
                    draft_id=item["episode_id"],
                    drafts_spent=item["drafts"],
                )
            return _outcome(
                COMPLETED,
                f"Episodul „{title}” pentru {date_iso} a trecut citirea Directorului și "
                "așteaptă aprobarea ta; niciun episod nou nu se scrie până nu decizi, pentru "
                "că numărul lui în serial se fixează la aprobare.",
                **counts,
            )
        counts["episode_id"] = counts["resumed"] = counts["told_date"] = None

        if not has_model:
            return _outcome(SKIPPED, no_model, **counts)
        with Session(engine) as session, session.begin():
            log, quiet = day_to_tell(session, today)
            if log is None:
                days = f" ({', '.join(sorted(quiet))})" if quiet else ""
                last = _last_told(session)
                if last is not None:
                    # Canon has reached the newest closed day: on his policy this is the
                    # click after he approved yesterday's episode, whose film the media
                    # stage makes in this same run. "No day has public events" said the
                    # opposite of what the run did (verifier, 2026-09-24).
                    date_told, title, status = last
                    state = {"APPROVED": "aprobat", "DRAFT": "ciornă", "REJECTED": "respins"}
                    return _outcome(
                        COMPLETED,
                        f"Ultima zi povestită este {date_told}: „{title[:80]}” "
                        f"({state.get(status, status.lower())}). Nicio zi încheiată de după ea "
                        f"nu are încă ce povesti{days}"
                        + (
                            "; o zi liniștită este un fapt, nu un motiv de a inventa un episod"
                            if quiet
                            else ""
                        )
                        + (
                            "; ziua de azi se scrie la sfârșitul rulării."
                            if date_told < today
                            else "."
                        ),
                        **counts,
                    )
                return _outcome(
                    COMPLETED,
                    f"Nicio zi încheiată din ultimele {RESUME_WINDOW_DAYS} zile, netrecută încă "
                    f"în serial, nu are evenimente publice de povestit{days}; o zi liniștită "
                    "este un fapt, nu un motiv de a inventa un episod.",
                    **counts,
                )
            log_id, date_iso = log.id, log.business_date
            counts["projected"] = len(ensure_projection(session, log))
        counts["told_date"] = date_iso
        outcome = _tell_the_day(engine, registry, log_id, date_iso, counts, language, correlation)
        return _naming_the_day(outcome, date_iso, quiet)
    except Exception as exc:
        if _transient(exc):
            from app.runbook.services import TransientStageError  # noqa: PLC0415

            raise TransientStageError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        raise


def run_serial_next_stage(
    engine: Engine, registry: Any, settings: Any, vault: Any = None
) -> dict[str, Any]:
    """Tomorrow's script: today's episode written, read and approved under policy, not filmed.

    Measured on 2026-09-24: nothing wrote the next episode, so the Owner's one click filmed
    an episode and left the next day with nothing written. This runs after the day's log is
    closed (runbook stage ``serial_next``) and tells TODAY, from its log closed at the run's
    hour. It builds no storyboard: the next morning's serial stage readies an APPROVED
    episode with none (`unfinished_episodes`, "storyboard") and that run's media stage films
    it, so no money is spent on a day before it is over, and a same-day re-run films nothing
    of today.

    It writes nothing when today's log is not closed, when today already has an episode (a
    re-run; a draft nobody read is read again), or when an earlier episode waits for the
    Owner or for a reading (the canon number is fixed on approval, and a script written
    beside a waiting episode would claim its number and continue a story it never read).
    """
    counts = _new_counts()
    language = getattr(settings, "content_language", "en")
    correlation = str(uuid4())
    today = business_date(getattr(settings, "timezone", None) or "UTC")
    has_model = bool(registry.registered_ids())
    no_model = "Niciun model de limbaj disponibil; agenții nu pot rula."

    try:
        with Session(engine) as session:
            log = session.scalar(
                select(DailyStudioLog).where(
                    DailyStudioLog.business_date == today, DailyStudioLog.status == "CLOSED"
                )
            )
            if log is None:
                return _outcome(
                    COMPLETED,
                    f"Jurnalul zilei {today} nu este închis; scenariul de mâine se scrie doar "
                    "din ziua închisă.",
                    **counts,
                )
            log_id = log.id
            existing = session.scalars(
                select(StoryEpisode)
                .where(StoryEpisode.log_id == log_id)
                .order_by(StoryEpisode.created_at)
            ).all()
            told = [(e.id, e.title, e.status, bool(e.review_json)) for e in existing]
            waiting = [
                (kind, episode.title, episode.id)
                for kind, episode in unfinished_episodes(session, today)
                if kind in ("review", "owner")
            ]
        counts["told_date"] = today

        if told:
            episode_id, title, status, reviewed = told[-1]
            counts["episode_id"] = episode_id
            if status == "DRAFT" and not reviewed:
                if not has_model:
                    return _outcome(SKIPPED, no_model, **counts)
                counts["resumed"] = "review"
                return _tell_the_day(
                    engine,
                    registry,
                    log_id,
                    today,
                    counts,
                    language,
                    correlation,
                    draft_id=episode_id,
                    drafts_spent=len(told),
                    film=False,
                )
            state = {"APPROVED": "aprobat", "DRAFT": "ciornă", "REJECTED": "respins"}
            return _outcome(
                COMPLETED,
                f"Scenariul de mâine pentru {today} este deja scris: „{title[:80]}” "
                f"({state.get(status, status.lower())}); nu se scrie din nou.",
                **counts,
            )
        if waiting:
            kind, title, episode_id = waiting[0]
            counts["episode_id"] = episode_id
            why = (
                "așteaptă aprobarea ta" if kind == "owner" else "așteaptă încă citirea Directorului"
            )
            return _outcome(
                COMPLETED,
                f"Scenariul de mâine nu se scrie: episodul „{title[:80]}” {why}, iar numărul "
                "lui în serial se fixează la aprobare.",
                **counts,
            )
        if not has_model:
            return _outcome(SKIPPED, no_model, **counts)
        with Session(engine) as session, session.begin():
            log = session.get(DailyStudioLog, log_id)
            assert log is not None  # read above, and a closed log is never deleted
            counts["projected"] = len(ensure_projection(session, log))
        return _tell_the_day(
            engine, registry, log_id, today, counts, language, correlation, film=False
        )
    except Exception as exc:
        if _transient(exc):
            from app.runbook.services import TransientStageError  # noqa: PLC0415

            raise TransientStageError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        raise
