"""How a repair is offered, queued, applied and recorded (2026-10-11).

The same steps for every repair registered in `app.agents.repairs`, so a repair module holds
only what it sees and what it changes:

1. `repair_matters`: what the detectors see, for the Director's choice (`command.findings`).
   A case (the same matter and fingerprint) that a repair settled is not offered again; one
   that was declined, held or whose task died is offered again a day on, a few times at most
   (`undecided`): the stop she was refused under may have been lifted since.
2. `submit_repair`: the Director chose it. The Policy Kernel is asked with the repair's own
   action and tier (`may_act`, requester the Director); allowed, her DirectorDecision is
   recorded OPEN and a DIRECTOR_REPAIR task queued under a key of the case and the day, so a
   loop run twice queues it once (the pattern of `media.blocker_repair.submit_sheet_issues`).
   Refused, nothing is written and the loop puts ONE card in front of the Owner
   (`ask_owner_about_repair`), not a letter at every loop. Her choice that the matter waits
   (HOLD, ...) is recorded as such (`hold_repair`) and nothing is done.
3. `execute_repair`, the worker's DIRECTOR_REPAIR handler: the kernel is asked again (the
   Owner may have stopped the studio meanwhile), the precondition is read again, the repair
   runs, and in one transaction the event ``director.repair_applied`` (or
   ``director.repair_declined``) with what changed, the decision closed with the outcome (and
   the repair's status kept on it), and for an applied repair one STATUS letter to the Owner:
   a statement, never a question.

What only the Owner can do is one card in his Decisions window (`owner_card`), never a letter
to an employee: the loop of 2026-10-09..11 was Nadia asked, every morning, for what only he
could give.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.repairs import (
    APPLIED,
    DECLINED,
    NOTHING_TO_DO,
    RepairContext,
    outcome,
    registered_repairs,
    repair_named,
)
from app.db import lock_for_write

logger = logging.getLogger("studio.repairs")

#: The durable task the worker runs (`app.workflows.worker.DIRECTOR_REPAIR`).
REPAIR_TASK = "DIRECTOR_REPAIR"
APPLIED_EVENT = "director.repair_applied"
DECLINED_EVENT = "director.repair_declined"
#: The Director, as the Policy Kernel and the letters name her when she has no agent row.
DIRECTOR = "Director"
#: A repair decision nothing closed (its task died with the process) is due for a look this
#: much later; `close_stale_decisions` closes it with what became of the task before then.
REVIEW_AFTER_HOURS = 24
#: What a card proposed by a repair says it came from.
CARD_SOURCE = "director_repair"
#: A repair that did its work, or found none left: the case is settled and never offered again.
SETTLED = (APPLIED, NOTHING_TO_DO)
#: Her choice that a matter waits (`hold_repair`): recorded, nothing done.
HELD = "HELD"
#: A case declined (the kernel refused it when it ran, the budget, an error), held, or whose
#: task died is offered again this long after the last try, at most `MAX_TRIES` times: a stop
#: lifted or a lock gone must not leave it unrepaired for good, and a repair that keeps
#: failing must not be tried at every loop.
RETRY_HOURS = 24
MAX_TRIES = 3
#: The Owner's one card for a repair the kernel will not let her make, or that does not hold.
BLOCKED_CARD = "director_repair:"
#: Such a card he has answered is not asked again for this long (`decisions.sources`' quiet).
BLOCKED_QUIET_DAYS = 7


def fingerprint(*parts: Any) -> str:
    """A short stable name for a case: the same rows give the same fingerprint."""
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _now() -> datetime:
    return datetime.now(UTC)


def usd_ro(micros: int) -> str:
    """A sum in USD as the Owner reads it: a comma, up to six decimals («0,584531», «4,58»),
    from the books' own exact formatting."""
    from app.economy.services import format_micros  # noqa: PLC0415

    return format_micros(int(micros)).replace(".", ",")


def director_of(session: Session) -> tuple[str | None, str]:
    """The Director's agent id and name, or (None, «Director») in a studio without her."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415

    director = agent_for_role(session, DIRECTOR)
    if director is None:
        return None, DIRECTOR
    return director.id, director.display_name


# ------------------------------------------------------------------------- 1. what she sees


def _when(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def undecided(engine: Engine, matters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The matters whose repair case is still to be decided; a matter without a repair passes.

    A case is decided while a decision for it is OPEN, and for good once a repair settled it
    (`SETTLED`). A case declined, held or whose task died is offered again `RETRY_HOURS` after
    its last try, `MAX_TRIES` times in all. Her choice to wait holds the whole matter for those
    hours, whatever new case it shows meanwhile (one more unpriced run is not a reason to do
    behind her back what she chose to wait on). Before 2026-10-11's review any decision
    counted: a re-pricing refused under the Owner's stop stayed refused after he lifted it,
    with the runs still unpriced and nothing left to say so.
    """
    from app.analytics.models import DirectorDecision  # noqa: PLC0415

    keys = {m["matter_key"] for m in matters if (m.get("repair") or {}).get("fingerprint")}
    if not keys:
        return list(matters)
    settled: set[tuple[str, str]] = set()
    tries: Counter[tuple[str, str]] = Counter()
    last: dict[tuple[str, str], datetime] = {}
    held: dict[str, datetime] = {}
    with Session(engine) as session:
        for key, state, evidence, created, reviewed in session.execute(
            select(
                DirectorDecision.matter_key,
                DirectorDecision.state,
                DirectorDecision.evidence_json,
                DirectorDecision.created_at,
                DirectorDecision.reviewed_at,
            ).where(DirectorDecision.matter_key.in_(keys))
        ):
            spec = (evidence or {}).get("repair") if isinstance(evidence, dict) else None
            if not isinstance(spec, dict) or not spec.get("fingerprint"):
                continue
            case = (str(key), str(spec["fingerprint"]))
            if state == "OPEN" or spec.get("status") in SETTLED:
                settled.add(case)
                continue
            tries[case] += 1
            moment = _when(reviewed or created)
            if moment is not None and (case not in last or moment > last[case]):
                last[case] = moment
            if moment is not None and spec.get("status") == HELD:
                held[case[0]] = max(moment, held.get(case[0], moment))
    again_after = _now() - timedelta(hours=RETRY_HOURS)

    def waiting(case: tuple[str, str]) -> bool:
        return (
            case in settled
            or tries[case] >= MAX_TRIES
            or (case in last and last[case] > again_after)
            or (case[0] in held and held[case[0]] > again_after)
        )

    return [
        m
        for m in matters
        if not (m.get("repair") or {}).get("fingerprint")
        or not waiting((m["matter_key"], str(m["repair"]["fingerprint"])))
    ]


def repair_matters(
    engine: Engine, settings: Any, registry: Any = None, correlation_id: str = ""
) -> list[dict[str, Any]]:
    """Every matter the registered detectors raise, less the cases decided (`undecided`).

    A detector that raises is logged and skipped: one broken repair must not take the
    Director's loop down with it, nor hide what the others see.
    """
    context = RepairContext(engine, settings, registry, correlation_id or str(uuid4()))
    found: list[dict[str, Any]] = []
    for repair in registered_repairs().values():
        if repair.detector is None:
            continue
        try:
            found.extend(repair.detector(context))
        except Exception as exc:  # noqa: BLE001 - a detector is never worth the loop
            logger.warning(
                "repair_detector_failed",
                extra={"repair": repair.name, "error_class": type(exc).__name__},
                exc_info=exc,
            )
    return undecided(engine, found) if found else []


# ------------------------------------------------------------------------- 2. her choice


def _record_decision(
    session: Session,
    *,
    repair: Any,
    matter: Mapping[str, Any],
    params: Mapping[str, Any],
    case: str,
    task_key: str | None,
    decision: str,
    interpretation: str,
    confidence: str,
    correlation_id: str,
    run_id: str | None,
    published: int,
    director_id: str | None,
    status: str | None = None,
    outcome_ro: str | None = None,
) -> str:
    """Her DirectorDecision for a repair, in the caller's transaction: OPEN until its task
    closes it, or closed at once with ``outcome_ro`` (a choice to wait)."""
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415

    decision_id = str(uuid4())
    event = append_event(
        session,
        "director.decision_recorded",
        "director_decision",
        decision_id,
        1,
        {
            "matter_key": matter["matter_key"],
            "decision": decision,
            "owner_role": DIRECTOR,
            "repair": repair.name,
            **({"status": status} if status else {}),
        },
        correlation_id,
    )
    spec: dict[str, Any] = {"name": repair.name, "params": dict(params), "fingerprint": case}
    if task_key:
        spec["task_key"] = task_key
    if status:
        spec["status"] = status
    now = utc_now()
    session.add(
        DirectorDecision(
            id=decision_id,
            scope=str(matter.get("scope") or "COMPANY")[:20],
            channel_id=matter.get("channel_id"),
            observation=str(matter["observation"]),
            evidence_json={"matter": dict(matter.get("evidence") or {}), "repair": spec},
            interpretation=interpretation or str(matter["observation"]),
            confidence=confidence,
            decision=decision,
            action=f"{repair.name}: {repair.summary}"[:1200],
            owner_role=DIRECTOR,
            review_after_videos=None,
            review_after_at=(_now() + timedelta(hours=REVIEW_AFTER_HOURS)).isoformat(),
            state="OPEN" if outcome_ro is None else "REVIEWED",
            outcome=None if outcome_ro is None else str(outcome_ro)[:4000],
            reviewed_at=None if outcome_ro is None else now,
            published_at_decision=published,
            matter_key=str(matter["matter_key"]),
            message_id=None,
            agent_id=director_id,
            run_id=run_id,
            created_at=now,
            event_id=event.event_id,
        )
    )
    return decision_id


def submit_repair(
    engine: Engine,
    *,
    matter: Mapping[str, Any],
    spec: Mapping[str, Any],
    decision: str,
    interpretation: str,
    confidence: str,
    correlation_id: str,
    run_id: str | None,
    published: int,
) -> dict[str, Any]:
    """Record the Director's decision to repair and queue the repair; see the module.

    Returns ``status`` QUEUED (with the decision and the task), REFUSED (the kernel's
    verdict, mode and reason: nothing was written), ALREADY_DECIDED (the case has its task
    today, or the matter an open decision: nothing was written) or UNKNOWN (no such repair).
    """
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.services import may_act  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415
    from app.workflows.services import enqueue_task  # noqa: PLC0415

    repair = repair_named(str(spec.get("name") or ""))
    if repair is None:
        return {"status": "UNKNOWN", "matter_key": matter["matter_key"], "repair": spec.get("name")}
    params = dict(spec.get("params") or {})
    case = str(spec.get("fingerprint") or fingerprint(repair.name, params))
    key = f"director-repair:{repair.name}:{case}:{_now().date().isoformat()}"[:100]
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        director_id, _name = director_of(session)
        verdict = may_act(
            session,
            repair.action,
            repair.tier,
            requester=director_id or DIRECTOR,
            subject=str(matter["matter_key"]),
            ask_owner=False,
        )
        if not verdict["allowed"]:
            return {
                "status": "REFUSED",
                "matter_key": matter["matter_key"],
                "repair": repair.name,
                "verdict": verdict["status"],
                "mode": verdict.get("mode"),
                "reason": verdict["reason"],
            }
        # The same case asked twice (one matter chosen twice in a Direction, a review offered
        # again the same day): the queue would hand back the first task, and a second
        # decision would stay OPEN with no task to close it. The first one stands.
        task = session.scalars(
            select(TaskQueueItem.id).where(TaskQueueItem.idempotency_key == key)
        ).first()
        standing = session.scalars(
            select(DirectorDecision.id).where(
                DirectorDecision.matter_key == str(matter["matter_key"]),
                DirectorDecision.state == "OPEN",
            )
        ).first()
        if task is not None or standing is not None:
            return {
                "status": "ALREADY_DECIDED",
                "matter_key": matter["matter_key"],
                "repair": repair.name,
                "task_id": task,
                "decision_id": standing,
            }
        decision_id = _record_decision(
            session,
            repair=repair,
            matter=matter,
            params=params,
            case=case,
            task_key=key,
            decision=decision,
            interpretation=interpretation,
            confidence=confidence,
            correlation_id=correlation_id,
            run_id=run_id,
            published=published,
            director_id=director_id,
        )
    queued = enqueue_task(
        engine,
        REPAIR_TASK,
        {
            "repair": repair.name,
            "params": params,
            "decision_id": decision_id,
            "matter_key": matter["matter_key"],
            "fingerprint": case,
        },
        priority=5,
        # One attempt: the executor records its own failure on the decision; a process that
        # died under it leaves a dead letter that `close_stale_decisions` closes.
        max_attempts=1,
        idempotency_key=key,
    )
    return {
        "status": "QUEUED",
        "decision_id": decision_id,
        "matter_key": matter["matter_key"],
        "repair": repair.name,
        "tier": repair.tier,
        "task_id": queued["id"],
    }


def hold_repair(
    engine: Engine,
    *,
    matter: Mapping[str, Any],
    spec: Mapping[str, Any],
    decision: str,
    interpretation: str,
    confidence: str,
    correlation_id: str,
    run_id: str | None,
    published: int,
) -> dict[str, Any]:
    """Her choice that the matter waits (HOLD, COOLDOWN, ...): her decision recorded and
    closed at once, the repair not made. The case comes back a day on (`undecided`); until
    then the repairs that follow her choice unasked do not make it behind her back."""
    repair = repair_named(str(spec.get("name") or ""))
    if repair is None:
        return {"status": "UNKNOWN", "matter_key": matter["matter_key"], "repair": spec.get("name")}
    params = dict(spec.get("params") or {})
    case = str(spec.get("fingerprint") or fingerprint(repair.name, params))
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        director_id, _name = director_of(session)
        decision_id = _record_decision(
            session,
            repair=repair,
            matter=matter,
            params=params,
            case=case,
            task_key=None,
            decision=decision,
            interpretation=interpretation,
            confidence=confidence,
            correlation_id=correlation_id,
            run_id=run_id,
            published=published,
            director_id=director_id,
            status=HELD,
            outcome_ro=(
                f"Directoarea a hotărât să aștepte ({decision}): reparația nu s-a făcut acum."
            ),
        )
    return {
        "status": HELD,
        "decision_id": decision_id,
        "matter_key": matter["matter_key"],
        "repair": repair.name,
    }


def blocked_card(
    matter: Mapping[str, Any], repair: Any, *, cause: str, about_ro: str, why_ro: str
) -> dict[str, Any]:
    """The Owner's card for a repair she may not make (or that does not hold): what she saw,
    why she stopped, and where he does it himself when there is such a place."""
    options: list[dict[str, Any]] = []
    place = str(getattr(repair, "place_ro", "") or "")
    if place:
        options.append(
            {
                "key": "self",
                "label_ro": "Mă ocup eu",
                "effect_ro": f"Faci tu, în {place}, ce ar fi reparat Directoarea.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": place,
                    "steps_ro": f"Deschide {place} și rezolvă: {about_ro}.",
                },
            }
        )
    options.append(
        {
            "key": "keep",
            "label_ro": "Las cum este",
            "effect_ro": (
                f"Nu se schimbă nimic; Directoarea nu mai întreabă despre asta "
                f"{BLOCKED_QUIET_DAYS} zile."
            ),
            "recommended": not options,
            "apply": {"type": "none", "result_ro": "Rămâne cum este."},
        }
    )
    return {
        "kind": "director_repair_blocked",
        "dedupe_key": f"{BLOCKED_CARD}{matter['matter_key']}:{cause}"[:200],
        "title_ro": f"Directoarea nu poate repara singură: {about_ro}",
        "why_ro": why_ro,
        "effect_ro": "Ce era de reparat îl faci tu, sau rămâne cum este.",
        "subject_type": "director_matter",
        "subject_id": str(matter["matter_key"])[:100],
        "options": options,
    }


def ask_owner_about_repair(
    engine: Engine,
    *,
    matter: Mapping[str, Any],
    spec: Mapping[str, Any],
    cause: str,
    about_ro: str,
    why_ro: str,
) -> str | None:
    """ONE card for the Owner when the kernel refuses her a repair, or the repair does not
    hold (`command.direct_company`): keyed by the matter and the cause (the kernel's verdict
    and his mode), so the loop of every six hours puts no new question in front of him, and
    one he answered is not asked again for `BLOCKED_QUIET_DAYS` (his mode changing is a new
    cause). Before 2026-10-11's review this was an ESCALATE letter at every loop, its subject
    changing with each new failure count."""
    repair = repair_named(str(spec.get("name") or ""))
    card = blocked_card(matter, repair, cause=cause, about_ro=about_ro, why_ro=why_ro)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        return owner_card_once(session, quiet_days=BLOCKED_QUIET_DAYS, **card)


# ------------------------------------------------------------------------- 3. the work


def execute_repair(
    engine: Engine,
    registry: Any,
    settings: Any,
    payload: Mapping[str, Any],
    *,
    correlation_id: str,
) -> dict[str, Any]:
    """Apply one queued repair and record it; see the module. Idempotent by its decision (a
    closed decision is not repaired again) and by ``correlation_id`` (the task's id)."""
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.services import may_act  # noqa: PLC0415

    name = str(payload.get("repair") or "")
    params = dict(payload.get("params") or {})
    decision_id = str(payload.get("decision_id") or "") or None
    with Session(engine) as session:
        director_id, _director_name = director_of(session)
        row = session.get(DirectorDecision, decision_id) if decision_id else None
        if row is not None and row.state != "OPEN":
            return {"status": "ALREADY_CLOSED", "repair": name, "decision_id": decision_id}
        done = session.scalars(
            select(DomainEvent.event_id).where(
                DomainEvent.event_type.in_((APPLIED_EVENT, DECLINED_EVENT)),
                DomainEvent.correlation_id == correlation_id,
            )
        ).first()
        if done is not None:
            return {"status": "ALREADY_DONE", "repair": name, "decision_id": decision_id}

    repair = repair_named(name)
    if repair is None:
        result = outcome(
            DECLINED,
            f"Reparația «{name}» nu există în această versiune a studioului; nu s-a schimbat "
            "nimic.",
        )
    else:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            verdict = may_act(
                session,
                repair.action,
                repair.tier,
                requester=director_id or DIRECTOR,
                subject=str(payload.get("matter_key") or repair.name),
                ask_owner=False,
            )
        if not verdict["allowed"]:
            result = outcome(
                DECLINED,
                f"Nu am aplicat reparația: {verdict['reason']}",
                changed={"policy": verdict["status"]},
            )
        else:
            context = RepairContext(
                engine,
                settings,
                registry,
                correlation_id,
                director_id=director_id,
                decision_id=decision_id,
            )
            try:
                why = repair.precondition(context, params)
                result = (
                    outcome(NOTHING_TO_DO, why) if why else dict(repair.function(context, params))
                )
            except Exception as exc:  # noqa: BLE001 - the failure is the decision's outcome
                logger.error(
                    "director_repair_failed",
                    extra={"repair": name, "error_class": type(exc).__name__},
                    exc_info=exc,
                )
                result = outcome(
                    DECLINED,
                    f"Reparația s-a oprit cu o eroare ({type(exc).__name__}); ce nu s-a "
                    "terminat rămâne cum era.",
                    changed={"error": type(exc).__name__},
                )
    _record(engine, name, params, decision_id, director_id, result, correlation_id)
    return {
        "status": result["status"],
        "repair": name,
        "decision_id": decision_id,
        "outcome": str(result["outcome_ro"])[:500],
        "changed": result.get("changed") or {},
    }


def _record(
    engine: Engine,
    name: str,
    params: Mapping[str, Any],
    decision_id: str | None,
    director_id: str | None,
    result: Mapping[str, Any],
    correlation_id: str,
) -> None:
    """The event, the decision closed with the repair's status kept on it (what `undecided`
    reads), and the Owner's letter, in one transaction."""
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    status = str(result["status"])
    words = str(result["outcome_ro"])
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        append_event(
            session,
            APPLIED_EVENT if status == APPLIED else DECLINED_EVENT,
            "director_repair",
            decision_id or correlation_id,
            1,
            {
                "repair": name,
                "status": status,
                "params": dict(params),
                "changed": dict(result.get("changed") or {}),
                "decision_id": decision_id,
                "outcome_ro": words[:2000],
            },
            correlation_id,
        )
        row = session.get(DirectorDecision, decision_id) if decision_id else None
        if row is not None and row.state == "OPEN":
            evidence = dict(row.evidence_json) if isinstance(row.evidence_json, dict) else {}
            spec: dict[str, Any] = (
                evidence["repair"] if isinstance(evidence.get("repair"), dict) else {}
            )
            row.evidence_json = {**evidence, "repair": {**spec, "status": status}}
            close_decision(session, row.id, words)
        subject = result.get("letter_subject_ro")
        if status == APPLIED and subject:
            status_letter(
                session,
                director_id,
                subject=str(subject),
                text=words,
                body={"repair": name, "decision_id": decision_id},
                correlation_id=correlation_id,
            )


# ------------------------------------------------------------------------- shared helpers


def close_decision(session: Session, decision_id: str, outcome_ro: str) -> bool:
    """Close an OPEN DirectorDecision with what became of it, in the caller's transaction (as
    `command.review_decision` does for the Owner's own review). False when it was not open."""
    from app.analytics.models import DirectorDecision  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415

    row = session.get(DirectorDecision, decision_id)
    if row is None or row.state != "OPEN":
        return False
    row.state = "REVIEWED"
    row.outcome = str(outcome_ro)[:4000]
    row.reviewed_at = utc_now()
    return True


def status_letter(
    session: Session,
    director_id: str | None,
    *,
    subject: str,
    text: str,
    body: Mapping[str, Any],
    correlation_id: str,
) -> str:
    """One STATUS letter to the Owner saying what the Director repaired: a statement, never a
    question. The same subject still open is that letter (`post_message` dedupes it)."""
    from app.agents.messages import post_message  # noqa: PLC0415

    letter = post_message(
        session,
        intent="STATUS",
        subject=subject,
        body={"kind": "director_repair", **dict(body)},
        body_text=text,
        from_agent_id=director_id,
        to_owner=True,
        correlation_id=correlation_id,
    )
    return letter.id


def owner_card(session: Session, **card: Any) -> str | None:
    """Propose one card to the Owner, deduped by its key, in a savepoint of the caller's
    transaction: a card that cannot be proposed is logged and never undoes the repair. The
    card's id, or None (refused lately, or not proposed)."""
    from app.decisions.sources import ask  # noqa: PLC0415

    try:
        with session.begin_nested():
            row = ask(session, source=CARD_SOURCE, **card)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.warning(
            "director_repair_card_not_proposed",
            extra={"card": card.get("dedupe_key")},
            exc_info=exc,
        )
        return None
    return row.id if row is not None else None


def owner_card_once(session: Session, *, quiet_days: int | None, **card: Any) -> str | None:
    """`owner_card` for a question that is answered once: an open card with the key is that
    card, and one already closed (he answered it, or it was withdrawn) is not asked again for
    ``quiet_days``, or ever with None (a key that names the exact case, so a new case is a
    new key). `decisions.sources.ask` re-asks after a guided «I did it»; here it does not."""
    from app.decisions.models import OPEN_STATUSES, OwnerDecision  # noqa: PLC0415

    latest = session.scalars(
        select(OwnerDecision)
        .where(OwnerDecision.dedupe_key == str(card.get("dedupe_key") or ""))
        .order_by(OwnerDecision.created_at.desc())
        .limit(1)
    ).first()
    if latest is not None and latest.status in OPEN_STATUSES:
        return latest.id
    if latest is not None:
        closed = _when(latest.decided_at or latest.updated_at)
        if quiet_days is None or (
            closed is not None and closed > _now() - timedelta(days=quiet_days)
        ):
            return None
    return owner_card(session, **card)


def withdraw_card(session: Session, dedupe_key: str, reason_ro: str) -> bool:
    """Withdraw an open card whose question went away (the studio saw it cleared). Not a
    decision: the Owner's answer is never given in his name."""
    from app.decisions.services import withdraw_owner_decision  # noqa: PLC0415

    return (
        withdraw_owner_decision(
            session, reason_ro=reason_ro, dedupe_key=dedupe_key, source=CARD_SOURCE
        )
        is not None
    )


def open_card_keys(session: Session, prefix: str) -> set[str]:
    """The dedupe keys of the open cards whose key starts with ``prefix``."""
    from app.decisions.models import OPEN_STATUSES, OwnerDecision  # noqa: PLC0415

    return set(
        session.scalars(
            select(OwnerDecision.dedupe_key).where(
                OwnerDecision.status.in_(OPEN_STATUSES),
                OwnerDecision.dedupe_key.like(f"{prefix}%"),
            )
        )
    )


__all__ = [
    "APPLIED_EVENT",
    "DECLINED_EVENT",
    "HELD",
    "REPAIR_TASK",
    "ask_owner_about_repair",
    "blocked_card",
    "close_decision",
    "director_of",
    "execute_repair",
    "fingerprint",
    "hold_repair",
    "open_card_keys",
    "owner_card",
    "owner_card_once",
    "repair_matters",
    "status_letter",
    "submit_repair",
    "undecided",
    "usd_ro",
    "withdraw_card",
]
