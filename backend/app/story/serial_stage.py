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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.media.serial_storyboard import (
    SerialStoryboardError,
    describe_serial_shots,
    storyboard_from_episode,
)
from app.services import queue_film_continue
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
#: How many drafts one run writes for a day: a draft, and one rewrite with the Director's
#: notes (an answer refused before it was stored counts as one).
MAX_DRAFTS = 2
#: How many drafts a day gets over every run. Until 2026-10-10 it was `MAX_DRAFTS`, and a day
#: whose two drafts were refused was finished with: measured on a copy of his database, every
#: day from 2026-09-19 to 2026-10-10 ended so, nothing was approved and the serial made nothing.
#: A refused day is now told again by a later run, with the reasons, up to this many drafts;
#: then the serial moves to another day (`day_to_retell`).
MAX_DRAFTS_PER_DAY = 3
#: How far back the stage takes up an episode an earlier run left unfinished. A week: the
#: serial tells recent days, and an episode older than that is left for the Owner's hand.
RESUME_WINDOW_DAYS = 7
#: The cause on the continuation queued for an episode approved at the end of the day
#: (`queue_film_continue`): the worker walks its storyboard tonight, under the Owner's money
#: rules, instead of the next morning's run.
SERIAL_APPROVED_CAUSE = "serial_approved"
#: What the stage says of the filming, after the storyboard: queued (PRODUCTION), or left to
#: the next run (TEST buys nothing, so nothing continues there; a queue fault is logged).
FILMING_QUEUED = (
    "filmarea lui a fost pusă la coadă și continuă în seara aceasta, sub regulile tale pentru bani."
)
FILMING_TOMORROW = "rularea de mâine îl filmează."


def serial_continuation_key(storyboard_id: str) -> str:
    """The idempotency key of the one continuation an approved episode's storyboard gets.

    The stage that approves the episode and the watchdog pass that finishes one left behind
    (`app.workflows.passes.serial_unfilmed`) both queue under this key, so the two never
    queue twice for one storyboard.
    """
    return f"film-continue-{storyboard_id}-{SERIAL_APPROVED_CAUSE}"


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
    runs forward, and a refused day is told again by `day_to_retell`, not here. And only
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


def day_to_retell(session: Session, before: str) -> dict[str, Any] | None:
    """A closed day to tell again, with the reasons its last draft was refused, or None.

    Measured on 2026-10-10 on a copy of his database: sixteen drafts of eight days, every one
    REJECTED by the computed checks, none approved. `day_to_tell` takes only a day after the
    newest told day and the script for tomorrow writes nothing for a day already told, so
    once a day's drafts were refused the serial made nothing more. The candidates are the
    closed days of the window before ``before`` that tell something and come after the newest
    APPROVED day (canon runs forward), whose every draft was REJECTED (nothing waits), with
    fewer than `MAX_DRAFTS_PER_DAY` drafts. In this order:

    1. the newest day told, while its budget lasts: it is the day the serial was on;
    2. the oldest day of the window no episode tells: it falls out of the window first;
    3. the other refused days, newest first.

    Returns ``{"log_id", "date", "drafts", "rewrite_of", "notes"}``: the newest refused draft
    of the day and its notes, for the next draft to be written as its rewrite.
    """
    since = (date.fromisoformat(before) - timedelta(days=RESUME_WINDOW_DAYS)).isoformat()
    approved = session.scalar(
        select(func.max(DailyStudioLog.business_date))
        .join(StoryEpisode, StoryEpisode.log_id == DailyStudioLog.id)
        .where(StoryEpisode.status == "APPROVED")
    )
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
    if approved is not None:
        query = query.where(DailyStudioLog.business_date > approved)
    refused: list[tuple[DailyStudioLog, list[StoryEpisode]]] = []
    untold: list[DailyStudioLog] = []
    for log in session.scalars(query.order_by(DailyStudioLog.business_date)):
        drafts = list(
            session.scalars(
                select(StoryEpisode)
                .where(StoryEpisode.log_id == log.id)
                .order_by(StoryEpisode.created_at)
            )
        )
        if any(draft.status != "REJECTED" for draft in drafts):
            continue
        if len(drafts) >= MAX_DRAFTS_PER_DAY or not ensure_projection(session, log):
            continue
        if drafts:
            refused.append((log, drafts))
        else:
            untold.append(log)

    def chosen(log: DailyStudioLog, drafts: list[StoryEpisode]) -> dict[str, Any]:
        last = drafts[-1] if drafts else None
        return {
            "log_id": log.id,
            "date": log.business_date,
            "drafts": len(drafts),
            "rewrite_of": last.id if last is not None else None,
            "notes": (last.notes or None) if last is not None else None,
        }

    if refused and refused[-1][0].business_date == told:
        return chosen(*refused[-1])
    if untold:
        return chosen(untold[0], [])
    if refused:
        return chosen(*refused[-1])
    return None


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


def ready_for_filming(
    engine: Engine, episode_id: str, correlation: str, registry: Any = None
) -> tuple[str | None, str | None]:
    """`_ready_for_filming` for a caller with no run card: (storyboard id, refusal)."""
    counts: dict[str, Any] = {}
    if _ready_for_filming(engine, episode_id, counts, correlation, registry):
        return str(counts["storyboard_id"]), None
    return None, counts.get("refusal")


def _queue_filming(engine: Engine, counts: dict[str, Any], episode_id: str) -> str | None:
    """Queue the one FILM_CONTINUE that walks the storyboard just built, and say so on the card.

    Measured on a copy of his database, 2026-10-11: episode 043317d3 «The Zero Script Club»
    was approved at 12:46 UTC by the stage that runs last in the day, built no storyboard by
    design, and would have been filmed by the next morning's run at the earliest; the serial
    had never made one public episode. Finishing an episode his run approved is unfinished
    work, not new work (his rule: new work starts at the 05:00 run or on his «Pornește
    rularea de azi»), so the walk is queued now; what it buys stays behind his money rules,
    his stop, safe mode and his mode (`runbook.stages.continue_film`). PRODUCTION only
    (`queue_film_continue`); a queue fault is logged and the watchdog's `serial_unfilmed`
    pass queues the same key later.
    """
    storyboard_id = str(counts["storyboard_id"])
    try:
        with Session(engine) as session, session.begin():
            # Read-then-write in the queue: the write lock first (the 2026-10-09 14:17 loss).
            lock_for_write(session)
            task_id = queue_film_continue(
                session,
                storyboard_id,
                key=serial_continuation_key(storyboard_id),
                payload={"cause": SERIAL_APPROVED_CAUSE, "episode_id": episode_id},
            )
    except SQLAlchemyError:
        logger.warning("serial_continue_not_queued", extra={"storyboard_id": storyboard_id})
        task_id = None
    counts["film_continue_task_id"] = task_id
    return task_id


def _filming_words(task_id: str | None) -> str:
    return FILMING_QUEUED if task_id else FILMING_TOMORROW


def _tell_the_day(
    engine: Engine,
    registry: Any,
    log_id: str,
    date_iso: str,
    counts: dict[str, Any],
    language: str,
    correlation: str,
    draft_id: str | None = None,
    day_drafts: int = 0,
    media_stage_follows: bool = True,
    notes: str | None = None,
    rewrite_of: str | None = None,
) -> dict[str, Any]:
    """Write (or take up ``draft_id``), review, rewrite once on a FAIL, approve, storyboard.

    ``day_drafts`` is how many drafts the day already had. One run writes at most
    `MAX_DRAFTS` (a draft and one rewrite), and a day gets at most `MAX_DRAFTS_PER_DAY` over
    every run: a first draft read on a later run and failed still gets its rewrite, and a
    day refused with budget left is told again by a later run (`day_to_retell`).

    ``notes`` and ``rewrite_of`` start a retelling: the first draft is written as the
    rewrite of the day's last refused draft, with the reasons it was refused.

    ``media_stage_follows=False`` is the evening's script (`run_serial_next_stage`, the run's
    last stage): no media stage of this run films the storyboard, so its filming is queued
    (`_queue_filming`). Until 2026-10-11 that script built no storyboard at all and waited
    for the next morning's run; see `run_serial_next_stage`.
    """
    refused_answer: str | None = None
    episode_id = draft_id
    stored = day_drafts
    drafts = 0
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
            stored += 1
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
        if drafts >= MAX_DRAFTS or stored >= MAX_DRAFTS_PER_DAY:
            counts["refusal"] = f"FAIL: {notes}"[:300]
            then = (
                "o rulare următoare o scrie din nou, cu motivele"
                if stored < MAX_DRAFTS_PER_DAY
                else f"ziua și-a folosit cele {MAX_DRAFTS_PER_DAY} ciorne; serialul trece la "
                "altă zi"
            )
            return _outcome(
                COMPLETED,
                f"Episodul pentru {date_iso} a fost respins de Director ({then}): {notes}",
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
    if not _ready_for_filming(engine, episode_id, counts, correlation, registry):
        return _outcome(
            COMPLETED, f"Episodul aprobat nu a devenit storyboard: {counts['refusal']}", **counts
        )
    if media_stage_follows:
        return _outcome(
            COMPLETED,
            f"Episodul pentru {date_iso} a fost scris, citit, aprobat și pregătit de filmare.",
            **counts,
        )
    return _outcome(
        COMPLETED,
        f"Episodul zilei {date_iso} a fost scris, citit, aprobat și pregătit de filmare; "
        + _filming_words(_queue_filming(engine, counts, episode_id)),
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
        #: The FILM_CONTINUE the evening's stage queued for the storyboard it built (PRODUCTION).
        "film_continue_task_id": None,
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
    draft would claim the same number); only then is a new closed day told, and with none, a
    refused day is told again with its reasons (`day_to_retell`). One of these per run, as
    the media stage films one episode a day. Readying and naming need no model, so they run
    before the stage asks for one.
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
                    day_drafts=item["drafts"],
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
            again = day_to_retell(session, today) if log is None else None
            if again is not None:
                log = session.get(DailyStudioLog, again["log_id"])
                counts["resumed"] = "retell"
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
        if again is not None:
            # A refused day told again, or a day the serial passed over untold: the first
            # draft is the rewrite of the day's last refused one, with its reasons.
            outcome = _tell_the_day(
                engine,
                registry,
                log_id,
                date_iso,
                counts,
                language,
                correlation,
                day_drafts=again["drafts"],
                notes=again["notes"],
                rewrite_of=again["rewrite_of"],
            )
            lead = (
                f"Ziua {date_iso} se scrie din nou: ciornele ei au fost respinse "
                f"({again['drafts']} din cel mult {MAX_DRAFTS_PER_DAY}). "
                if again["drafts"]
                else f"Ziua {date_iso}, sărită până acum, se povestește. "
            )
            return {**outcome, "reason": (lead + outcome["reason"])[:300]}
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
    """The evening's script: today's episode written, read, approved under policy, readied.

    Measured on 2026-09-24: nothing wrote the next episode, so the Owner's one click filmed
    an episode and left the next day with nothing written. This runs after the day's log is
    closed (runbook stage ``serial_next``) and tells TODAY, from its log closed at the run's
    hour.

    Until 2026-10-11 it built no storyboard, so that no money was spent on a day before it
    was over: the next morning's serial stage readied the APPROVED episode
    (`unfinished_episodes`, "storyboard") and that run's media stage filmed it. Measured on a
    copy of his database that day: the first episode the Director ever approved under his
    policy (043317d3, canon episode 1, 12:46 UTC) stood with no storyboard until the next
    morning at the earliest, and the serial had never made one public episode. The log it
    tells is CLOSED and frozen, so the day it tells cannot change; and finishing an episode
    his run approved is unfinished work, not new work (his rule: new work starts at the 05:00
    run or on his «Pornește rularea de azi»). So the approved episode is readied here, as the
    morning would (`_ready_for_filming`), and its walk is queued (`_queue_filming`,
    PRODUCTION): the worker films it tonight under his money rules. The day's own media
    stage still films a serial episode only once its day is over (`serial_films_due`), so a
    same-day re-run buys nothing twice; an approved episode an older run left with no
    storyboard is readied and queued by the re-run too.

    It writes nothing when today's log is not closed, when today already has an episode (a
    re-run; a draft nobody read is read again, and a day whose every draft was refused is
    written again with the reasons while `MAX_DRAFTS_PER_DAY` lasts), or when an earlier
    episode waits for the Owner or for a reading (the canon number is fixed on approval, and
    a script written beside a waiting episode would claim its number and continue a story it
    never read).
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
            told = [
                (e.id, e.title, e.status, bool(e.review_json), e.storyboard_id) for e in existing
            ]
            last_notes = existing[-1].notes if existing else None
            waiting = [
                (kind, episode.title, episode.id)
                for kind, episode in unfinished_episodes(session, today)
                if kind in ("review", "owner")
            ]
        counts["told_date"] = today
        # Today told and every draft refused, with budget left: written again with the
        # reasons, instead of "already written (rejected)" until the day was out of the window.
        refused = bool(told) and all(status == "REJECTED" for _i, _t, status, _r, _s in told)
        retell = refused and len(told) < MAX_DRAFTS_PER_DAY

        if told and not retell:
            episode_id, title, status, reviewed, storyboard_id = told[-1]
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
                    day_drafts=len(told),
                    media_stage_follows=False,
                )
            if status == "APPROVED" and not storyboard_id:
                # Approved by a run that built no storyboard (every run before 2026-10-11, or
                # a build that failed): his re-run finishes the day's own work, as the morning
                # would, and queues the filming. Built from rows, so a refusal repeats until
                # the episode changes; it is on the card below.
                counts["resumed"] = "storyboard"
                if _ready_for_filming(engine, episode_id, counts, correlation, registry):
                    return _outcome(
                        COMPLETED,
                        f"Scenariul de mâine pentru {today} era deja scris și aprobat: "
                        f"„{title[:80]}”; a fost pregătit de filmare acum, iar "
                        + _filming_words(_queue_filming(engine, counts, episode_id)),
                        **counts,
                    )
            state = {"APPROVED": "aprobat", "DRAFT": "ciornă", "REJECTED": "respins"}
            spent = f"; ziua și-a folosit cele {MAX_DRAFTS_PER_DAY} ciorne" if refused else ""
            not_readied = (
                f" Nu a devenit storyboard: {counts['refusal']}" if counts.get("refusal") else ""
            )
            return _outcome(
                COMPLETED,
                f"Scenariul de mâine pentru {today} este deja scris: „{title[:80]}” "
                f"({state.get(status, status.lower())}{spent}); nu se scrie din nou." + not_readied,
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
        if retell:
            counts["resumed"] = "retell"
            return _tell_the_day(
                engine,
                registry,
                log_id,
                today,
                counts,
                language,
                correlation,
                day_drafts=len(told),
                media_stage_follows=False,
                notes=last_notes,
                rewrite_of=told[-1][0],
            )
        return _tell_the_day(
            engine,
            registry,
            log_id,
            today,
            counts,
            language,
            correlation,
            media_stage_follows=False,
        )
    except Exception as exc:
        if _transient(exc):
            from app.runbook.services import TransientStageError  # noqa: PLC0415

            raise TransientStageError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        raise
