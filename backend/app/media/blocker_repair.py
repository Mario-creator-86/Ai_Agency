"""Durable shooting-sheet work: Director assignment, real tool, verified outcome.

No generation of media, funding, policy edit or publication happens here. Text-model calls
use the normal employee policy/budget kernel. A worker scan, not an open page, discovers work.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role
from app.agents.messages import post_message, resolve_message
from app.agents.models import AgentMessage
from app.agents.structured import structured_run
from app.db import lock_for_write
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.balance_rule import DEFAULT_MARGIN, needed_credits
from app.media.models import Storyboard
from app.media.prompt_agent import PROMPT_ROLE, PromptError, write_shot_prompts
from app.media.sheet_story_repair import progress as story_progress
from app.media.sheet_story_repair import repair_story
from app.media.shooting_sheet import (
    FilmClosed,
    build_sheet,
    current_lease,
    film_is_closed,
    film_purchase_lease,
)
from app.models import OwnerPolicy
from app.runbook.services import safe_mode_state, shutdown_requested
from app.services import append_event
from app.workflows.models import TaskQueueItem
from app.workflows.services import enqueue_task

REPAIR_TASK = "FILM_SHEET_REPAIR"
REPORT_KIND = "shooting_sheet_blockers"
WORK_KIND = "shooting_sheet_repair_work"
FINISHED_EVENT = "media.sheet_repair_finished"
logger = logging.getLogger("studio.sheet_repair")

# The safety the Owner asked for on 2026-10-03 ("pune și o siguranță să nu meargă la infinit"):
# on his studio the scan had queued a repair of the same sheet every five minutes for an hour,
# every one UNRESOLVED because every language-model call failed. The repair still continues
# without asking him; it backs off, has a daily ceiling per set of blockers, waits while the
# language model is failing, and tells him once when it pauses.
#: Letters to the Owner when the automatic repair of a sheet pauses.
PAUSED_KIND = "sheet_repair_paused"
#: The end of a repair whose film is closed («Închide filmul», or the Director's retirement).
CLOSED_FILM_NOTE = (
    "Filmul a fost închis: foaia lui nu se mai remediază și nu se cumpără nimic pentru el."
)
#: Attempts in 24 hours on the same blockers (the same sheet and the same issues).
MAX_SAME_ISSUES_PER_DAY = 5
#: The wait before the second retry of the same blockers; it doubles after each one.
BACKOFF_BASE_SECONDS = 300
#: The longest wait between two attempts on the same blockers.
BACKOFF_MAX_SECONDS = 6 * 3600
#: The latest model runs read to tell a failing language model from one bad answer.
MODEL_RUNS_READ = 3
#: When this studio process started. Attempts that failed before it do not count against the
#: ceiling or the back-off: a restart usually brings code that fixes what made them fail (the
#: Owner, 2026-10-03: "să reparăm, și să îi lăsăm pe ei să rezolve"). Within one run of the
#: studio the ceiling holds.
STUDIO_STARTED_AT = datetime.now(UTC)
#: The Owner let a paused repair try again now (his accept on the pause card, 2026-10-03):
#: the attempts before it no longer count against the guard.
RETRY_EVENT = "media.sheet_repair_retry_allowed"


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _language_model_failing(session: Session) -> str | None:
    """The last error when the studio's latest model runs all failed at the provider."""
    from app.agents.models import AgentRun  # noqa: PLC0415 - the agents import media

    runs = list(
        session.scalars(
            select(AgentRun).order_by(AgentRun.started_at.desc()).limit(MODEL_RUNS_READ)
        )
    )
    if len(runs) < MODEL_RUNS_READ:
        return None
    if all(
        r.status == "FAILED" and str(r.error_detail or "").startswith("ProviderHTTPError")
        for r in runs
    ):
        return str(runs[0].error_detail)
    return None


def _latest_retry(session: Session, identifier: str) -> datetime | None:
    """When the Owner last let this sheet's repair try again, or None."""
    from app.models import DomainEvent  # noqa: PLC0415

    stamp = session.scalars(
        select(DomainEvent.timestamp)
        .where(DomainEvent.event_type == RETRY_EVENT, DomainEvent.aggregate_id == identifier)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    return _when(stamp) if stamp else None


def allow_repair_retry(
    engine: Engine,
    storyboard_id: str,
    *,
    issued_by: str,
    correlation_id: str,
    fingerprint: Any = None,
) -> str:
    """The Owner lets a paused sheet repair try again now; returns the event's id.

    Only he does (his accept on the pause card; ``issued_by`` is the caller's, after his key).
    The attempts made before it stop counting against the day's ceiling and the back-off, so
    the next scan queues a repair. Idempotent by ``correlation_id``: the same accept retried
    records it once. Nothing is bought; the repair uses the language model only.
    """
    from app.models import DomainEvent  # noqa: PLC0415

    if issued_by != "owner":
        raise PermissionError(
            "Doar Proprietarul lasă remedierea foii să încerce din nou; cererea venită de la "
            f"«{issued_by or 'necunoscut'}» nu a schimbat nimic."
        )
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        done = session.scalars(
            select(DomainEvent.event_id).where(
                DomainEvent.event_type == RETRY_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.correlation_id == correlation_id,
            )
        ).first()
        if done is not None:
            return str(done)
        if session.get(Storyboard, storyboard_id) is None:
            raise LookupError("Filmul acestei foi nu mai există; nu s-a schimbat nimic.")
        event = append_event(
            session,
            RETRY_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {"decided_by": "owner", "fingerprint": fingerprint},
            correlation_id,
        )
        return str(event.event_id)


def issue_key(issues: list[dict[str, Any]]) -> str:
    """What «the same blockers» means to the ceiling and the back-off: the set of (kind, code,
    scene) of the sheet's issues, never their wording and never the sheet's hash.

    2026-10-11 (the serial's board f06808c9, «The Zero Script Club»): every round the Video
    Editor rewrote the prompts, so the sheet's hash changed, and the lint's wording with it
    («Camera:» and «Action:», then «Camera:» alone); the fingerprint never matched twice, and
    the repair ran every five minutes for half an hour on the same eight TEMPLATE_LABEL
    blockers, each round UNRESOLVED, with no back-off and no ceiling. Progress is fewer or
    different blockers, not different words for the same ones."""
    blockers = sorted(
        {
            (str(i.get("kind") or ""), str(i.get("code") or ""), str(i.get("scene_index")))
            for i in issues
        }
    )
    return hashlib.sha256(json.dumps(blockers).encode()).hexdigest()


def _same_blockers(item: TaskQueueItem, fingerprint: str, blockers: str | None) -> bool:
    """Whether an earlier attempt was on these blockers: by `issue_key` when both sides carry
    one, by the old fingerprint for attempts queued before 2026-10-11."""
    payload = item.payload or {}
    if blockers and payload.get("issue_key"):
        return str(payload.get("issue_key")) == blockers
    return payload.get("fingerprint") == fingerprint


def _repair_guard(
    session: Session,
    sheet: dict[str, Any],
    fingerprint: str,
    tasks: list[TaskQueueItem],
    blockers: str | None = None,
) -> dict[str, Any] | None:
    """Why no new attempt may start now (BACKING_OFF or PAUSED), or None when one may.

    ``blockers`` (`issue_key`) is what the attempts are counted on: a sheet rewritten with the
    same blockers still standing is the same problem, not a new one."""
    unresolved: list[datetime] = []
    window_start = datetime.now(UTC) - timedelta(days=1)
    # The Owner's "try again now": the attempts before it no longer count.
    retried = _latest_retry(session, str(sheet["storyboard_id"]))
    if retried is not None and retried > window_start:
        window_start = retried
    window_start = max(window_start, STUDIO_STARTED_AT)
    for item in tasks:
        if not _same_blockers(item, fingerprint, blockers):
            continue
        letter = session.get(AgentMessage, item.payload.get("message_id"))
        result = (letter.body_json or {}).get("repair_result") if letter else None
        if result and result.get("status") == "UNRESOLVED":
            started = _when(item.created_at)
            if started is not None and started >= window_start:
                unresolved.append(started)
    if not unresolved:
        return None
    failing = _language_model_failing(session)
    if failing is not None:
        return {
            "status": "PAUSED",
            "cause": "LANGUAGE_MODEL_DOWN",
            "reason_ro": (
                f"Remedierea automată a foii „{sheet.get('title') or sheet['storyboard_id']}” "
                f"stă în pauză: modelul de limbaj nu răspunde (ultima eroare: {failing}). "
                "Reconectează furnizorul în Setări → Furnizori AI; remedierea se reia singură "
                "după primul răspuns reușit al modelului. Nu s-a cumpărat nimic."
            ),
        }
    if len(unresolved) >= MAX_SAME_ISSUES_PER_DAY:
        return {
            "status": "PAUSED",
            "cause": "DAILY_LIMIT",
            "reason_ro": (
                f"Remedierea automată a foii „{sheet.get('title') or sheet['storyboard_id']}” "
                f"a încercat de {len(unresolved)} ori în ultimele 24 de ore aceleași blocaje "
                "(aceleași coduri pe aceleași scene, oricum ar fi fost rescrise prompturile), "
                "fără succes, și s-a oprit pentru restul zilei sau până când blocajele se "
                "schimbă. Blocajele rămân pe foaia de filmare; nu s-a cumpărat nimic."
            ),
        }
    wait = 0 if len(unresolved) < 2 else BACKOFF_BASE_SECONDS * 2 ** (len(unresolved) - 2)
    resume = max(unresolved) + timedelta(seconds=min(wait, BACKOFF_MAX_SECONDS))
    if datetime.now(UTC) < resume:
        return {"status": "BACKING_OFF", "retry_after": resume.isoformat()}
    return None


#: The pauses that are the Owner's to unblock: his language-model account. Every other pause is
#: the studio's own and never reaches him (see `_pause_letter`).
OWNER_PAUSE_CAUSES = frozenset({"LANGUAGE_MODEL_DOWN"})


def _pause_letter(session: Session, sheet: dict[str, Any], fingerprint: str, guard: dict) -> None:
    """One note per paused sheet, cause and blockers; never one per scan.

    A pause on his account (the language model not answering) is his: a letter and a card in
    his window of decisions (DECISION_SOURCES, 2026-10-03), the cause and what unblocks it.
    Any other pause is the studio's own business. 2026-10-10 (film «How NASA Keeps a Space
    Telescope Alive With Frozen Fuel»): the daily ceiling paused a story loop the studio had
    made itself and wrote to him «Remedierea foii e în pauză», and he answered «studioul
    trebuie să rezolve singur, fără intervenții». The ceiling stays (his 2026-10-03 «să nu
    meargă la infinit»); the note goes to the Director, and the repair resumes by itself the
    next day, after a restart or when the sheet changes."""
    from app.decisions import sources  # noqa: PLC0415 - the decisions read media lazily

    owners = guard.get("cause") in OWNER_PAUSE_CAUSES
    if owners:
        sources.sheet_repair_paused(session, sheet, fingerprint, guard)
    identifier = str(sheet["storyboard_id"])
    for message in session.scalars(select(AgentMessage).where(AgentMessage.status == "OPEN")):
        body = message.body_json or {}
        if body.get("kind") == PAUSED_KIND and body.get("storyboard_id") == identifier:
            return
    director = agent_for_role(session, "Director")
    post_message(
        session,
        intent="ESCALATE" if owners else "STATUS",
        subject=f"Remedierea foii e în pauză: {sheet.get('title') or identifier}"[:200],
        body={
            "kind": PAUSED_KIND,
            "storyboard_id": identifier,
            "fingerprint": fingerprint,
            "cause": guard["cause"],
        },
        body_text=guard["reason_ro"],
        from_agent_id=director.id if director else None,
        to_agent_id=None if owners else (director.id if director else None),
        to_owner=owners,
    )


def _close_pause_letters(session: Session, identifier: str) -> None:
    from app.decisions import sources  # noqa: PLC0415

    sources.sheet_repair_resumed(session, identifier)
    for message in session.scalars(select(AgentMessage).where(AgentMessage.status == "OPEN")):
        body = message.body_json or {}
        if body.get("kind") == PAUSED_KIND and body.get("storyboard_id") == identifier:
            resolve_message(
                session,
                message.id,
                resolution="Remedierea automată a foii a fost reluată.",
                resolved_by="Director",
                correlation_id=str(uuid4()),
            )


def allowed(engine: Engine) -> bool:
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        active = bool(policy and not policy.autonomy_stopped and policy.autonomy_mode != "MANUAL")
    return active and not shutdown_requested(engine) and not safe_mode_state(engine).get("active")


def sheet_issues(sheet: dict[str, Any]) -> list[dict[str, Any]]:
    issues = [
        dict(
            kind="PROMPT",
            code=f["code"],
            scene_index=f.get("scene", f.get("scene_index")),
            detail=f["message_ro"],
        )
        for f in sheet.get("blocks") or []
    ]
    issues += [
        dict(
            kind="PROMPT",
            code="NEEDS_SHOT_PLAN",
            scene_index=i,
            detail=f"Scena {i} nu are plan de cadre scris de model.",
        )
        for i in sheet.get("shot_plan_gaps") or []
    ]
    footer = sheet.get("footer") or {}
    for scene in sheet.get("scenes") or []:
        problem = (scene.get("card") or {}).get("problem_ro")
        if problem:
            issues.append(
                dict(
                    kind="STORY",
                    code="CARD_INVALID",
                    scene_index=scene["scene_index"],
                    detail=problem,
                )
            )
    review = sheet.get("story_review") or {}
    if review.get("passed") is False:
        issues.append(
            dict(
                kind="STORY",
                code="STORY_REVIEW_REQUIRED",
                scene_index=None,
                detail=str(review.get("reason") or "Povestea trebuie recenzată."),
            )
        )
    balance = footer.get("balance") or {}
    for name, step in (sheet.get("steps") or {}).items():
        if not step.get("to_buy"):
            continue
        if balance.get("read"):
            credits = balance.get("credits")
            # The footer's need is the step's next round x the margin (the Owner's rule of
            # 2026-10-03); a footer from before it is read by the same rule, never the cap.
            needed = (footer.get("balance_needed_credits") or {}).get(name)
            if needed is None:
                needed = needed_credits(float(step.get("cost_credits") or 0), DEFAULT_MARGIN)
            if credits is None:
                issues.append(
                    dict(
                        kind="OWNER",
                        code="BALANCE_UNVERIFIED",
                        scene_index=None,
                        detail="Soldul furnizorului nu a putut fi verificat.",
                    )
                )
            elif float(credits) < needed:
                issues.append(
                    dict(
                        kind="OWNER",
                        code="LOW_BALANCE",
                        scene_index=None,
                        detail=(
                            f"Sold {credits:g} credite; pasul {name} necesită "
                            f"{needed} credite cu marja."
                        ),
                    )
                )
        budget = footer.get("daily_budget")
        if budget and float(step.get("cap_usd") or 0) > float(budget.get("remaining_usd") or 0):
            issues.append(
                dict(
                    kind="OWNER",
                    code="OVER_DAILY_BUDGET",
                    scene_index=None,
                    detail=f"Plafonul pasului {name} depășește bugetul disponibil al zilei.",
                )
            )
        film = footer.get("film_budget") or {}
        if film and float(step.get("cap_usd") or 0) * 1_000_000 > int(
            film.get("remaining_usd_micros") or 0
        ):
            issues.append(
                dict(
                    kind="OWNER",
                    code="OVER_FILM_BUDGET",
                    scene_index=None,
                    detail=f"Plafonul pasului {name} depășește plafonul rămas al filmului.",
                )
            )
        if step.get("waiting_ro") and step.get("blocked"):
            issues.append(
                dict(
                    kind="OWNER",
                    code="STEP_BLOCKED",
                    scene_index=None,
                    detail=str(step["waiting_ro"]),
                )
            )
    if footer.get("catalogue_problem_ro"):
        issues.append(
            dict(
                kind="OWNER",
                code="CATALOGUE_INVALID",
                scene_index=None,
                detail=str(footer["catalogue_problem_ro"]),
            )
        )
    return issues


def submit_sheet_issues(engine: Engine, sheet: dict[str, Any]) -> dict[str, Any]:
    successor = story_progress(engine, str(sheet["storyboard_id"]))
    if successor.get("replacement_storyboard_id"):
        return {"status": "REVISED", **successor}
    issues = sheet_issues(sheet)
    if not issues:
        return {"status": "CLEAR"}
    identifier = str(sheet["storyboard_id"])
    fingerprint = hashlib.sha256(
        json.dumps([sheet["sheet_hash"], issues], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # The fingerprint tells one attempt from another (the sheet as it was, the issues as they
    # were worded); the ceiling and the back-off count on the blockers themselves.
    blockers = issue_key(issues)
    with Session(engine) as session:
        tasks = [
            t
            for t in session.scalars(
                select(TaskQueueItem)
                .where(TaskQueueItem.task_type == REPAIR_TASK)
                .order_by(TaskQueueItem.created_at.desc())
            )
            if t.payload.get("storyboard_id") == identifier
        ]
        existing = next(
            (t for t in tasks if t.status in ("QUEUED", "CLAIMED", "RUNNING", "RETRYING")), None
        )
        same = next((t for t in tasks if t.payload.get("fingerprint") == fingerprint), None)
        report = session.get(AgentMessage, same.payload.get("message_id")) if same else None
        result = (report.body_json or {}).get("repair_result") if report else None
        if (
            existing is None
            and same
            and result
            and result["status"] in ("RESOLVED", "WAITING_OWNER")
        ):
            existing = same
        if existing:
            return {
                "status": existing.status,
                "task_id": existing.id,
                "message_id": existing.payload.get("message_id"),
            }
        today = datetime.now(UTC).date().isoformat()
        attempts = [t for t in tasks if t.created_at >= today]
        guard = _repair_guard(session, sheet, fingerprint, tasks, blockers)
    if guard is not None:
        if guard["status"] == "PAUSED":
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                _pause_letter(session, sheet, fingerprint, guard)
        return guard
    attempt = len(attempts) + 1
    key = f"sheet-repair-{identifier}-{fingerprint}-{today}-{attempt}"
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        _close_pause_letters(session, identifier)
        # A report survives a process dying between the report commit and queue insertion.
        report = next(
            (
                m
                for m in session.scalars(
                    select(AgentMessage).where(AgentMessage.subject.like("Blocaje foaie:%"))
                )
                if (m.body_json or {}).get("dispatch_key") == key
            ),
            None,
        )
        director = agent_for_role(session, "Director")
        if report is None:
            report = post_message(
                session,
                intent="REQUEST_REVIEW",
                subject=f"Blocaje foaie: {sheet.get('title') or identifier}"[:200],
                body={
                    "kind": REPORT_KIND,
                    "storyboard_id": identifier,
                    "sheet_hash": sheet["sheet_hash"],
                    "fingerprint": fingerprint,
                    "issue_key": blockers,
                    "dispatch_key": key,
                    "attempt": attempt,
                    "issues": issues,
                    "executed_by_worker": True,
                },
                body_text=(
                    "Foaia de filmare este blocată. Repartizează corectarea prompturilor "
                    "editorului și escaladează numai ce cere Ownerul.\n"
                )
                + "\n".join(
                    f"Scena {i['scene_index'] or '—'} · {i['code']}: {i['detail']}" for i in issues
                ),
                to_agent_id=director.id if director else None,
                in_reply_to=same.payload.get("message_id") if same else None,
            )
        message_id = report.id
    queued = enqueue_task(
        engine,
        REPAIR_TASK,
        {
            "storyboard_id": identifier,
            "message_id": message_id,
            "sheet_hash": sheet["sheet_hash"],
            "fingerprint": fingerprint,
            "issue_key": blockers,
            "attempt": attempt,
        },
        priority=6,
        max_attempts=1,
        idempotency_key=key,
    )
    return {"status": queued["status"], "message_id": message_id, "task_id": queued["id"]}


class Assignment(BaseModel):
    note: str = Field(min_length=1, max_length=1200)
    repair_prompts: bool
    assign_to_role: str = PROMPT_ROLE


def director_assignment(
    engine: Engine,
    registry: Any,
    sheet: dict[str, Any],
    issues: list[dict[str, Any]],
    correlation: str,
) -> dict[str, Any]:
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        if director is None:
            raise ValueError("Niciun Director activ.")
        identifier = director.id
    instructions = (
        "The shooting sheet below is authoritative data. Assign its prompt and "
        "missing-shot-plan blockers "
        f"to {PROMPT_ROLE}, who owns write_shot_prompts. Ask for concrete natural language, "
        "camera and continuity, with every scene corrected. Never ask for paid media, "
        "funding, credentials or policy changes. For financial/configuration blockers the "
        "backend will escalate to the Owner. Return only JSON "
        '{"note":"specific repair instructions", "repair_prompts":true|false, '
        '"assign_to_role":"VideoEditor"}.\n'
    )
    parsed, first, second = structured_run(
        engine,
        registry,
        identifier,
        "sheet_repair_assignment",
        instructions
        + wrap_in_inert_boundary(
            json.dumps({"title": sheet.get("title"), "issues": issues}, ensure_ascii=False),
            "sheet-issues",
        ),
        "sheet-repair-v1",
        correlation,
        Assignment,
        "",
        summary="Repartizez remedierea foii de filmare.",
        max_tokens=1400,
    )
    final = second or first
    if parsed is None or final.get("status") != "SUCCEEDED" or parsed.assign_to_role != PROMPT_ROLE:
        raise ValueError("Directorul nu a dat o repartizare utilizabilă pentru foaia de filmare.")
    return {**parsed.model_dump(), "run_id": final.get("id")}


def _film_title(session: Session, storyboard_id: str) -> str:
    """The film's title, as the Owner knows it; its short id only when it has none."""
    board = session.get(Storyboard, storyboard_id)
    title = str(board.title or "").strip() if board is not None else ""
    return title or storyboard_id[:8]


def _finish(
    engine: Engine,
    payload: dict[str, Any],
    status: str,
    remaining: list[dict[str, Any]],
    note: str,
    correlation: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        if status == "WAITING_OWNER" and film_is_closed(session, payload["storyboard_id"]):
            # Closed while the repair ran outside its lease (the Director's assignment): a
            # sheet nobody films any more asks him nothing («Închide filmul»).
            status, remaining, note = "STALE", [], CLOSED_FILM_NOTE
        result = {
            "status": status,
            "remaining": remaining,
            "reason": note,
            "storyboard_id": payload["storyboard_id"],
            **(details or {}),
        }
        report = session.get(AgentMessage, payload["message_id"])
        director = agent_for_role(session, "Director")
        editor = agent_for_role(session, PROMPT_ROLE)
        if report:
            report.body_json = {**report.body_json, "repair_result": result}
            if status == "RESOLVED":
                resolve_message(
                    session,
                    report.id,
                    resolution=note,
                    resolved_by="verificarea foii",
                    correlation_id=correlation,
                )
            post_message(
                session,
                intent="STATUS",
                subject=f"Remediere foaie: {status}",
                body={"kind": "sheet_repair_result", "executed_by_worker": True, **result},
                body_text=note,
                from_agent_id=editor.id if editor else None,
                to_agent_id=director.id if director else None,
                in_reply_to=report.id,
                correlation_id=correlation,
            )
            if status == "WAITING_OWNER":
                # The film by its title, as he knows it (2026-10-03), not by its id.
                title = _film_title(session, payload["storyboard_id"])
                post_message(
                    session,
                    intent="ESCALATE",
                    subject=f"Foaia necesită intervenție: {title}"[:200],
                    body={"storyboard_id": payload["storyboard_id"], "kind": "sheet_repair_owner"},
                    body_text=note + "\n" + "\n".join(i["detail"] for i in remaining),
                    from_agent_id=director.id if director else None,
                    to_owner=True,
                    in_reply_to=report.id,
                )
        if status == "RESOLVED":
            for message in session.scalars(
                select(AgentMessage).where(AgentMessage.status == "OPEN")
            ):
                body = message.body_json or {}
                if body.get("storyboard_id") == payload["storyboard_id"] and body.get("kind") in (
                    REPORT_KIND,
                    WORK_KIND,
                    "sheet_repair_owner",
                    "sheet_repair_limit",
                ):
                    resolve_message(
                        session,
                        message.id,
                        resolution=note,
                        resolved_by="verificarea foii",
                        correlation_id=correlation,
                    )
        append_event(
            session, FINISHED_EVENT, "storyboard", payload["storyboard_id"], 1, result, correlation
        )
    return result


def process_sheet_repair(
    engine: Engine,
    registry: Any,
    payload: dict[str, Any],
    *,
    correlation_id: str | None = None,
    settings: Any = None,
    sheet_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not allowed(engine):
        return {"status": "BLOCKED", "reason": "Oprit de politica Ownerului sau de modul sigur."}
    correlation = correlation_id or str(uuid4())
    identifier = payload["storyboard_id"]
    with Session(engine) as session:
        closed = film_is_closed(session, identifier)
    if closed:
        # A film the Owner closed (or the Director retired) is not repaired: a story repair
        # would write a replacement storyboard of its topic, and the topic would hold the
        # studio again. Queued before the close, the task ends here without a model run.
        # Closed while it runs (the Director's assignment holds no lease), it meets the closed
        # film at the repair's own lease (`FilmClosed`, below) and ends the same way.
        return _finish(engine, payload, "STALE", [], CLOSED_FILM_NOTE, correlation)
    context = dict(sheet_context or {})
    context.pop("read_live", None)

    def read(*, live: bool = False) -> dict[str, Any]:
        return build_sheet(engine, identifier, read_live=live, settings=settings, **context)

    with Session(engine) as session:
        report = session.get(AgentMessage, payload["message_id"])
        previous = (report.body_json or {}).get("repair_result") if report else None
        if previous:
            return previous
    current = read()
    if current["sheet_hash"] != payload["sheet_hash"]:
        return _finish(
            engine,
            payload,
            "STALE",
            sheet_issues(current),
            "Foaia s-a schimbat; instrucțiunile vechi nu au fost executate.",
            correlation,
        )
    with Session(engine) as session:
        report = session.get(AgentMessage, payload["message_id"])
        original = list((report.body_json or {}).get("issues") or []) if report else []
        previous = (report.body_json or {}).get("repair_result") if report else None
        if previous:
            return previous

    try:
        if current_lease(engine, identifier):
            return _finish(
                engine,
                payload,
                "UNRESOLVED",
                original,
                "Altă operație lucrează la film; remedierea va continua.",
                correlation,
            )
        with film_purchase_lease(
            engine, identifier, step="story_repair", holder=correlation, ttl_seconds=3600
        ):
            if read()["sheet_hash"] != payload["sheet_hash"]:
                return _finish(
                    engine,
                    payload,
                    "STALE",
                    original,
                    "Foaia s-a schimbat; o reverific înainte de remediere.",
                    correlation,
                )
            prerequisites = repair_story(
                engine, registry, identifier, correlation, payload["message_id"], original
            )
        if prerequisites:
            replacement = prerequisites.get("replacement_storyboard_id")
            if replacement:
                submit_sheet_issues(
                    engine,
                    build_sheet(engine, replacement, read_live=False, settings=settings, **context),
                )
            return _finish(
                engine,
                payload,
                prerequisites["status"],
                original,
                prerequisites["reason"],
                correlation,
                prerequisites,
            )
        decision = director_assignment(engine, registry, current, original, correlation)
        prompt_issues = [i for i in original if i["kind"] == "PROMPT"]
        if prompt_issues:
            if current_lease(engine, identifier):
                return _finish(
                    engine,
                    payload,
                    "UNRESOLVED",
                    original,
                    "Altă operație lucrează la film; prompturile nu au fost schimbate.",
                    correlation,
                )
            with film_purchase_lease(
                engine, identifier, step="prompt_repair", holder=correlation, ttl_seconds=3600
            ):
                if read()["sheet_hash"] != payload["sheet_hash"]:
                    return _finish(
                        engine,
                        payload,
                        "STALE",
                        original,
                        "Foaia s-a schimbat în timpul repartizării Directorului.",
                        correlation,
                    )
                with Session(engine) as session, session.begin():
                    lock_for_write(session)
                    director = agent_for_role(session, "Director")
                    editor = agent_for_role(session, PROMPT_ROLE)
                    if director is None or editor is None:
                        raise ValueError("Directorul sau editorul nu este activ.")
                    work = post_message(
                        session,
                        intent="HANDOFF",
                        subject=f"Repară foaia: {current.get('title')}"[:200],
                        body={
                            "kind": WORK_KIND,
                            "executed_by_worker": True,
                            "storyboard_id": identifier,
                            "issues": prompt_issues,
                        },
                        body_text=decision["note"],
                        from_agent_id=director.id,
                        to_agent_id=editor.id,
                        in_reply_to=payload["message_id"],
                        run_id=decision.get("run_id"),
                        correlation_id=correlation,
                    )
                    work_id = work.id
                    board = session.get(Storyboard, identifier)
                    # Old whole-film renders keep their provenance and files. Save the old
                    # plan too, before repairing the unbought staircase's text instructions.
                    append_event(
                        session,
                        "media.sheet_repair_plan_saved",
                        "storyboard",
                        identifier,
                        1,
                        {
                            "visual_bible": board.visual_bible_json if board else {},
                            "scenes": current["scenes"],
                            "sheet_hash": current["sheet_hash"],
                        },
                        correlation,
                    )
                write_shot_prompts(
                    engine,
                    registry,
                    identifier,
                    correlation,
                    repair_context={
                        "instructions": decision["note"],
                        "issues": prompt_issues,
                        "exchange": int(payload.get("attempt") or 1),
                    },
                )
                after = read(live=context.get("account") is not None)
                remaining = sheet_issues(after)
                with Session(engine) as session, session.begin():
                    lock_for_write(session)
                    if not any(i["kind"] == "PROMPT" for i in remaining):
                        resolve_message(
                            session,
                            work_id,
                            resolution=(
                                "Prompturile și planul de cadre au trecut reverificarea foii."
                            ),
                            resolved_by="verificarea foii",
                            correlation_id=correlation,
                        )

        else:
            remaining = sheet_issues(read(live=context.get("account") is not None))
        # Live financial evidence survives the offline text recheck.
        if context.get("account") is None:
            remaining += [i for i in original if i["kind"] == "OWNER" and i not in remaining]
        status = (
            "UNRESOLVED"
            if any(i["kind"] == "PROMPT" for i in remaining)
            else ("WAITING_OWNER" if remaining else "RESOLVED")
        )
        note = "Foaia a fost reverificată: " + (
            "blocajele de prompt și plan sunt rezolvate."
            if status == "RESOLVED"
            else "blocajele de mai jos rămân deschise. Nu s-a cumpărat media."
        )
        return _finish(engine, payload, status, remaining, note, correlation)
    except FilmClosed:
        # Closed during the Director's assignment: nothing of the repair was written.
        return _finish(engine, payload, "STALE", [], CLOSED_FILM_NOTE, correlation)
    except Exception as error:
        # The state says unresolved; a failed model/tool never becomes a conversational success.
        logger.warning(
            "sheet_repair_unresolved",
            extra={"storyboard_id": identifier, "error_type": type(error).__name__},
        )
        return _finish(
            engine,
            payload,
            "UNRESOLVED",
            original,
            (
                (
                    str(error)[:1000]
                    if isinstance(error, PromptError)
                    else f"Instrumentul de remediere a eșuat ({type(error).__name__})."
                )
                + " Directorul păstrează sarcina și reia remedierea automat."
            ),
            correlation,
        )


def scan_sheet_issues(engine: Engine, **context: Any) -> dict[str, Any]:
    if not allowed(engine):
        return {"reported": [], "status": "BLOCKED"}
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for message in session.scalars(select(AgentMessage).where(AgentMessage.status == "OPEN")):
            if (message.body_json or {}).get("kind") == "sheet_repair_limit":
                resolve_message(
                    session,
                    message.id,
                    status="ANSWERED",
                    resolution=(
                        "Limita de încercări a fost eliminată. Directorul continuă "
                        "remedierea automat; nu este necesar răspunsul tău."
                    ),
                    resolved_by="Director",
                    correlation_id=str(uuid4()),
                )
    with Session(engine) as session:
        identifiers = list(
            session.scalars(
                select(Storyboard.id)
                .where(Storyboard.status.in_(("APPROVED", "NEEDS_SHOT_PLAN", "RENDERED")))
                .order_by(Storyboard.created_at.desc())
                .limit(30)
            )
        )
    reported = []
    for identifier in identifiers:
        try:
            if story_progress(engine, identifier).get("replacement_storyboard_id"):
                continue
            reading = build_sheet(engine, identifier, **({"read_live": False} | context))
            if sheet_issues(reading):
                submit_sheet_issues(engine, reading)
                reported.append(identifier)
            elif context.get("read_live") and not reading.get("in_progress"):
                # Funding/configuration corrected outside the task is verified on the next scan.
                with Session(engine) as session:
                    pending = next(
                        (
                            t
                            for t in session.scalars(
                                select(TaskQueueItem)
                                .where(TaskQueueItem.task_type == REPAIR_TASK)
                                .order_by(TaskQueueItem.created_at.desc())
                            )
                            if t.payload.get("storyboard_id") == identifier
                        ),
                        None,
                    )
                    report = (
                        session.get(AgentMessage, pending.payload.get("message_id"))
                        if pending
                        else None
                    )
                    result = (report.body_json or {}).get("repair_result") if report else None
                    task_payload = dict(pending.payload) if pending else None
                if task_payload and result and result.get("status") != "RESOLVED":
                    _finish(
                        engine,
                        task_payload,
                        "RESOLVED",
                        [],
                        "Foaia nu mai are blocaje la verificarea actuală.",
                        str(uuid4()),
                    )
        except (ValueError, OSError):
            continue
    return {"reported": reported}


def repair_status(engine: Engine, storyboard_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        tasks = session.scalars(
            select(TaskQueueItem)
            .where(TaskQueueItem.task_type == REPAIR_TASK)
            .order_by(TaskQueueItem.created_at.desc())
        )
        latest = next((t for t in tasks if t.payload.get("storyboard_id") == storyboard_id), None)
        if latest is None:
            return None
        report = session.get(AgentMessage, latest.payload.get("message_id"))
        result = (report.body_json or {}).get("repair_result") if report else None
        return {
            "task_id": latest.id,
            "thread_id": (report.thread_id or report.id) if report else None,
            "status": result.get("status") if result else latest.status,
            "reason": result.get("reason")
            if result
            else "Blocajele sunt trimise Directorului; sarcina este în coada studioului.",
        }
