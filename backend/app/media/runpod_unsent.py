"""Scenes held by a RunPod /run that failed with no job id, released (2026-10-09).

The film «The Particle That Shouldn't Exist (But Does)» (storyboard babcf272): the Owner
approved the stills step on RunPod, the GPU session opened at 11:45:36 UTC and the /run for
scene 1's two candidates failed in 0.12 s without RunPod's job id and without proof that it
never left. Both journal rows stayed SUBMISSION_UNCERTAIN, both takes REFUSED
VENDOR.UNANSWERED with their credits counted, scene 1 was held «Decide Proprietarul pe foaia
de filmare» and, scene 1 being Figure 1, the whole stills step had nothing to buy. RunPod's
console showed no job, no worker, no log and $0.

From now on the GPU-off keeps the proof (the queue read before its purge, RunPod's own purge
count, the verified off, the worker's bucket record) and the step itself turns a proven
round into UNSENT items with no hold (`providers.runpod.batch.BatchRun.prove_unsent`). This
module deals with what is held anyway:

* **What a hold rests on.** A hold written since 2026-10-09 names its journal rows and takes
  (`assembler.RUNPOD_HOLD_ITEMS`). An older one is matched to its GPU session by its
  correlation; its rows are those the session's proof listed (`batch.PROOF_EVENT`) or, for
  the sessions of 2026-10-09 and before, the scene's rows created while the session was open
  and left uncertain, plus (only when that step had one session and the count of takes asks
  for them) its uncertain rows that name no session, reused from an earlier attempt with an
  older creation time. A row is still found after a redo sent its key again: the send keeps
  which session had left it uncertain (``output.resent``). A hold that cannot be matched is
  logged (``runpod_unsent_hold_unmapped``) and left as it is.
* **What became of each row**: OPEN (still uncertain, last sent by this hold's session),
  ELSEWHERE (uncertain, sent again since by another session, whose own hold asks about it),
  PROVEN (a later round's proof), OWNER (released on his card), UNSENT_AT_SEND (sent again
  and proven never to have left), IN_FLIGHT (being sent again now), CHANGED (RunPod answered
  it with a job id since, or it failed otherwise).
* **Released by proof, no card** (`settle_proven_holds`): every row PROVEN. A later round with
  the same keys (a redo) proved at its GPU-off that nothing waited in the queue and that the
  worker never started any of those keys (it writes ``claims/<key>.json`` before any GPU work):
  that covers the earlier /run of the same keys too. Run right after such a proof
  (`gpu_batch`), at boot (`decisions.seed`) and by the watchdog.
* **His card**, «Nu s-a trimis nimic: eliberez scena N?», when the record is clean: a verified
  off reading of 0/0/0 with max 0, no job RunPod accepted in that session, no other session on
  the endpoint meanwhile, nothing billed, no row answered or being sent, and an in-step proof
  (2026-10-09 on) that found only GAPS (something unread or not recorded: the queue before the
  purge, the purge's count, the bucket), never a SIGN (a claim or a manifest in the bucket, a
  purge that removed a job, a count above 0, a shared endpoint). The card says what is known
  and what is missing, as recorded. His yes, through the decisions system (`apply_release`),
  releases the scene; his no keeps it held and he is not asked again about that hold.
* **What 2026-10-09 recorded is NOT a proof.** The session's record says RunPod accepted no
  job (``remote_job_ids`` []), the endpoint read OFF after the close's purge and max=0 (0
  queued, 0 in progress, 0 running, max 0), and no second was billed. But the purge's answer
  was not kept and the queue was not read before it, so the studio cannot tell «never
  queued» from «queued and purged» (both harmless) and, more to the point, a snapshot taken
  after the purge cannot see a job that ran and ended before it. The worker's bucket record
  would settle it, but a boot pass that calls the bucket is a network pass, and his RunPod
  console (no job, $0) is the stronger evidence anyway, and it is his. So nothing is released
  on that evidence alone: it is his card. (A redo of the scene that proves its keys never
  queued releases it without him, as above.)
* **Cleared** (his open card withdrawn): the hold released, superseded by his own decision on
  the scene (a decided or retired take, an approved one, a model set for it), or a row of it
  answered since. Never because its rows moved from uncertain to proven: the hold still holds
  the scene until it is released (2026-10-09 review).

Releasing writes, in one transaction: on his card the OPEN rows FAILED/UNSENT at 0 cost with
the release on them (their keys stay reusable; the next switch-on of the endpoint purges its
queue first while such a release is recent, `gpu_session.booked_unsent_sessions`), the hold's
takes RUNPOD.NOT_QUEUED with no credits (`assembler.recode_not_queued`), and one
`assembler.RUNPOD_UNSENT_RELEASED_EVENT` that `assembler.scene_memory` reads. Idempotent;
nothing is sent and nothing is bought. The estimate the step booked for that round stays in
the books: an ESTIMATED provider cost has no correction entry yet (an open point).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.media.assembler import (
    _OWNER_RETIRED_CODES,
    MOTION_HOLD_EVENT,
    RUNPOD_HOLD_ITEMS,
    RUNPOD_UNSENT_RELEASED_EVENT,
    SCENE_MODEL_SET_EVENT,
    SHOT_TAKE_KINDS,
    STILL_HOLD_EVENT,
    TAKE_DECIDED_EVENT,
    UNANSWERED_FAILURE_CODE,
    _event_holds,
    _released_holds,
    recode_not_queued,
)
from app.media.models import SceneTake
from app.models import DomainEvent
from app.providers.runpod.batch import PROOF_EVENT, UNCERTAIN, UNSENT
from app.providers.runpod.gpu_session import CLOSED, GpuSessionRow, overlapping_sessions
from app.providers.runpod.jobs import GenerationJob
from app.providers.runpod.models import TERMINAL
from app.services import append_event, utc_now

logger = logging.getLogger("studio.media")

#: The card, its option's apply type and the condition that withdraws it.
CARD_KIND = "runpod_unsent_release"
APPLY_TYPE = "runpod_unsent_release"
CONDITION = "runpod_unsent_hold_cleared"
SOURCE = "stage:runpod_unsent"
#: The command his accept is remembered under (idempotent by the decision's inner id).
COMMAND = "ReleaseRunPodUnsentHold"

#: What became of one row a hold rests on (see the module's text).
OPEN, ELSEWHERE, PROVEN, OWNER = "OPEN", "ELSEWHERE", "PROVEN", "OWNER"
UNSENT_AT_SEND, IN_FLIGHT, CHANGED = "UNSENT_AT_SEND", "IN_FLIGHT", "CHANGED"

#: What an in-step proof may find that is only a GAP in the record: something not read or not
#: recorded (`batch.queue_problems`, `BatchRun._worker_records`). His card is for these. Any
#: other problem (a claim or a manifest in his bucket, a purge that removed a job, a count
#: above 0, a shared endpoint, an off not verified) is a SIGN, and no card is offered.
PROOF_GAPS: tuple[str, ...] = (
    "NO_EVIDENCE",
    "QUEUE_UNREAD_BEFORE_PURGE",
    "QUEUED_UNREAD",
    "IN_PROGRESS_UNREAD",
    "RUNNING_UNREAD",
    "PURGE_UNANSWERED",
    "BUCKET_UNREADABLE",
    "NO_BUCKET",
)

#: The words of a hold released on a later round's proof.
PROOF_DETAIL = (
    "RunPod nu a făcut nimic din această cerere: o rundă ulterioară cu aceleași chei a dovedit "
    "la oprirea GPU-ului că nu aștepta nimic la coadă și că lucrătorul nu a început niciuna "
    "dintre ele. Nu s-a făcut și nu s-a plătit nimic."
)
OWNER_DETAIL = (
    "RunPod nu a pus cererea la coadă (Proprietarul a eliberat scena pe cardul lui, după ce "
    "a văzut ce a înregistrat studioul): nu s-a făcut și nu s-a plătit nimic."
)
#: What a legacy record (2026-10-09 and before) does not prove, on his card.
LEGACY_GAP_RO = (
    "Răspunsul golirii cozii nu a fost înregistrat atunci (studioul îl păstrează abia de acum), "
    "așa că studioul singur nu poate dovedi că nimic nu a ajuns la coadă: o lucrare încheiată "
    "înainte de oprire nu s-ar vedea în această citire."
)


def card_key(hold_event_id: str) -> str:
    """One card per hold, ever: his no stands."""
    return f"runpod_unsent:{hold_event_id}"


@dataclass
class Candidate:
    """A hold whose cause is a RunPod /run with no job id, with what the studio recorded."""

    hold_event_id: str
    hold_sequence: int
    hold_event: str
    held_at: str
    storyboard_id: str
    scene_number: int
    purpose: str
    gpu_session_id: str
    endpoint_id: str
    opened_at: str
    closed_at: str | None
    off_reading: dict[str, Any]
    verified_off: bool | None
    remote_job_ids: list[str]
    job_row_ids: list[str] = field(default_factory=list)
    take_ids: list[str] = field(default_factory=list)
    #: Journal row id -> what became of it (OPEN, PROVEN, ...).
    classes: dict[str, str] = field(default_factory=dict)
    #: What the session's own proof found (`batch.PROOF_EVENT`); None when none was recorded.
    proof_problems: list[str] | None = None

    def rows_in(self, *names: str) -> list[str]:
        return [row for row in self.job_row_ids if self.classes.get(row) in names]

    @property
    def all_proven(self) -> bool:
        return bool(self.job_row_ids) and all(
            self.classes.get(row) == PROVEN for row in self.job_row_ids
        )


def _moment(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _output(row: GenerationJob) -> dict[str, Any]:
    return row.output if isinstance(row.output, dict) else {}


def _uncertain_row(row: GenerationJob) -> bool:
    return (
        row.error_code == UNCERTAIN
        and row.status not in TERMINAL
        and not row.remote_job_id
        and not row.batch_remote_id
    )


def _resent_uncertain(row: GenerationJob) -> list[dict[str, Any]]:
    """The times this row was sent again while uncertain (`batch.reserve_item`)."""
    return [
        entry
        for entry in _output(row).get("resent") or []
        if isinstance(entry, dict) and entry.get("error_code") == UNCERTAIN
    ]


def _was_uncertain(row: GenerationJob) -> bool:
    """A /run of this row got no job id at some point (now, before a later send, or before a
    proof or his card booked it as never queued)."""
    return (
        row.error_code == UNCERTAIN
        or isinstance(_output(row).get("not_queued"), dict)
        or bool(_resent_uncertain(row))
    )


def _unnamed_uncertain(row: GenerationJob) -> bool:
    """Left uncertain by a session that named none on its rows (2026-10-09 and before)."""
    if _uncertain_row(row) and row.gpu_session_id is None:
        return True
    return any(entry.get("gpu_session_id") is None for entry in _resent_uncertain(row))


def _row_class(row: GenerationJob, gpu_session_id: str) -> str:
    if row.remote_job_id or row.batch_remote_id:
        return CHANGED
    if _uncertain_row(row):
        return OPEN if row.gpu_session_id in (None, gpu_session_id) else ELSEWHERE
    code = str(row.error_code or "")
    if row.status == "FAILED" and (code == UNSENT or code.startswith("HTTP_")):
        mark = _output(row).get("not_queued")
        if code == UNSENT and isinstance(mark, dict):
            if mark.get("by") == "proof" and mark.get("proven") is True:
                return PROVEN
            if mark.get("by") == "owner":
                return OWNER
        return UNSENT_AT_SEND
    if row.status not in TERMINAL:
        return IN_FLIGHT
    return CHANGED


def _rows_by_id(session: Session, ids: Iterable[Any]) -> list[GenerationJob]:
    found: list[GenerationJob] = []
    for identifier in dict.fromkeys(str(value) for value in ids if value):
        row = session.get(GenerationJob, identifier)
        if row is not None:
            found.append(row)
    return found


def _proof_payloads(session: Session, gpu_session_id: str) -> list[dict[str, Any]]:
    """What the session's own proof recorded (`batch.BatchRun.prove_unsent`)."""
    return [
        event.payload
        for event in session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == PROOF_EVENT,
                DomainEvent.aggregate_id == gpu_session_id[:36],
            )
            .order_by(DomainEvent.sequence)
        )
        if isinstance(event.payload, dict)
    ]


def _hold_rows(
    session: Session,
    event: DomainEvent,
    gpu: GpuSessionRow,
    scene: int,
    purpose: str,
    proofs: list[dict[str, Any]],
) -> tuple[list[GenerationJob], list[GenerationJob]]:
    """The journal rows the hold rests on, whatever became of them since, and (for a session of
    2026-10-09 and before) the uncertain rows naming no session that were created before it
    opened (a key reused from an earlier attempt keeps its first creation time)."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    items = payload.get(RUNPOD_HOLD_ITEMS)
    if isinstance(items, dict) and isinstance(items.get("job_row_ids"), list):
        return _rows_by_id(session, items["job_row_ids"]), []
    if proofs:
        listed = [
            item.get("job_row_id")
            for proof in proofs
            for item in proof.get("items") or []
            if isinstance(item, dict)
        ]
        return [
            row
            for row in _rows_by_id(session, listed)
            if row.project_id == event.aggregate_id
            and row.scene_id == str(scene)
            and row.operation == purpose
        ], []
    start, end = _moment(gpu.opened_at), _moment(gpu.closed_at)
    rows: list[GenerationJob] = []
    reused: list[GenerationJob] = []
    for row in session.scalars(
        select(GenerationJob)
        .where(
            GenerationJob.project_id == event.aggregate_id,
            GenerationJob.scene_id == str(scene),
            GenerationJob.operation == purpose,
        )
        .order_by(GenerationJob.created_at, GenerationJob.id)
    ):
        if not _was_uncertain(row):
            continue
        if row.gpu_session_id == gpu.id:
            rows.append(row)
            continue
        made = _moment(row.created_at)
        if made is None or start is None or end is None:
            continue
        if start <= made <= end:
            rows.append(row)  # reserved while it was open: sent in it, whatever came after
        elif made < start and _unnamed_uncertain(row):
            reused.append(row)
    return rows, reused


def _holding_take(take: SceneTake) -> bool:
    return (
        take.status == "REFUSED"
        and take.failure_code == UNANSWERED_FAILURE_CODE
        and not take.sha256
        and take.credits_measured is None
    )


def _hold_takes(
    session: Session, event: DomainEvent, scene: int, kinds: tuple[str, ...]
) -> list[str]:
    """The scene's «unanswered» refused takes the same step recorded before its hold."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    items = payload.get(RUNPOD_HOLD_ITEMS)
    if isinstance(items, dict) and isinstance(items.get("take_ids"), list):
        named: list[str] = []
        for identifier in dict.fromkeys(str(value) for value in items["take_ids"] if value):
            take = session.get(SceneTake, identifier)
            if take is not None and _holding_take(take):
                named.append(take.id)
        return named
    held = _moment(event.timestamp)
    found: list[str] = []
    for take, _recorded in session.execute(
        select(SceneTake, DomainEvent)
        .join(DomainEvent, DomainEvent.event_id == SceneTake.event_id)
        .where(
            SceneTake.storyboard_id == event.aggregate_id,
            SceneTake.scene_number == scene,
            SceneTake.kind.in_(kinds),
            SceneTake.status == "REFUSED",
            SceneTake.failure_code == UNANSWERED_FAILURE_CODE,
            SceneTake.sha256.is_(None),
            SceneTake.credits_measured.is_(None),
            DomainEvent.correlation_id == event.correlation_id,
        )
        .order_by(SceneTake.created_at, SceneTake.id)
    ):
        made = _moment(take.created_at)
        if held is not None and made is not None and made > held:
            continue
        found.append(take.id)
    return found


def _hold_shape(event: DomainEvent) -> tuple[int, str, tuple[str, ...]] | None:
    """(scene, purpose, take kinds) of a hold an unanswered /run left; None for any other."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    scene = payload.get("scene_number")
    if (
        event.event_type not in (STILL_HOLD_EVENT, MOTION_HOLD_EVENT)
        or not isinstance(scene, int)
        or isinstance(scene, bool)
        or str(payload.get("failure_kind") or "") != "UNANSWERED"
        or not _event_holds(payload)
    ):
        return None
    if event.event_type == STILL_HOLD_EVENT:
        return scene, "image", ("still",)
    return scene, "video", tuple(SHOT_TAKE_KINDS)


def _superseded(session: Session, event: DomainEvent) -> bool:
    """His own decision on the scene since the hold, as `assembler.scene_memory` reads one (a
    decided take, a take he retired, a model he set for it), or a take of it approved since:
    the hold no longer holds the scene."""
    shape = _hold_shape(event)
    held = _moment(event.timestamp)
    if shape is None or held is None:
        return False
    scene, _purpose, kinds = shape

    def after(value: Any) -> bool:
        moment = _moment(value)
        return moment is not None and moment > held

    takes = list(
        session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == event.aggregate_id,
                SceneTake.scene_number == scene,
                SceneTake.kind.in_(kinds),
            )
        )
    )
    for take in takes:
        if take.failure_code in _OWNER_RETIRED_CODES and after(take.updated_at):
            return True
        if take.status == "APPROVED" and after(take.updated_at or take.created_at):
            return True
    ids = [take.id for take in takes]
    if ids and any(
        after(stamp)
        for stamp in session.scalars(
            select(DomainEvent.timestamp).where(
                DomainEvent.event_type == TAKE_DECIDED_EVENT, DomainEvent.aggregate_id.in_(ids)
            )
        )
    ):
        return True
    if kinds != ("still",):
        for payload, stamp in session.execute(
            select(DomainEvent.payload, DomainEvent.timestamp).where(
                DomainEvent.event_type == SCENE_MODEL_SET_EVENT,
                DomainEvent.aggregate_id == event.aggregate_id,
            )
        ):
            if isinstance(payload, dict) and payload.get("scene_index") == scene and after(stamp):
                return True
    return False


def _candidate(session: Session, event: DomainEvent) -> Candidate | None:
    shape = _hold_shape(event)
    if shape is None:
        return None
    scene, purpose, kinds = shape
    sessions = session.scalars(
        select(GpuSessionRow)
        .where(
            GpuSessionRow.correlation_id == str(event.correlation_id)[:100],
            GpuSessionRow.storyboard_id == event.aggregate_id,
            GpuSessionRow.purpose == purpose,
            GpuSessionRow.status == CLOSED,
        )
        .order_by(GpuSessionRow.opened_at.desc())
    ).all()
    for gpu in sessions:
        proofs = _proof_payloads(session, gpu.id)
        rows, reused = _hold_rows(session, event, gpu, scene, purpose, proofs)
        if not rows and not reused:
            continue
        takes = _hold_takes(session, event, scene, kinds)
        if len(takes) != len(rows) and reused and len(sessions) == 1:
            # Its keys were reserved by an earlier attempt (proven unsent, or refused with a
            # 4xx) and sent again by this one, the only session of the step: they are its rows.
            rows = rows + reused
        if not rows or len(takes) != len(rows):
            # Every uncertain item has its refused take, or nothing is released or asked.
            logger.warning(
                "runpod_unsent_hold_unmapped",
                extra={
                    "hold_event_id": event.event_id,
                    "storyboard_id": event.aggregate_id,
                    "scene_number": scene,
                    "gpu_session_id": gpu.id,
                    "rows": len(rows),
                    "takes": len(takes),
                },
            )
            return None
        problems: list[str] | None = None
        if proofs:
            problems = [str(p) for proof in proofs for p in proof.get("problems") or []]
        return Candidate(
            hold_event_id=event.event_id,
            hold_sequence=int(event.sequence),
            hold_event=event.event_type,
            held_at=str(event.timestamp),
            storyboard_id=event.aggregate_id,
            scene_number=scene,
            purpose=purpose,
            gpu_session_id=gpu.id,
            endpoint_id=gpu.endpoint_id,
            opened_at=gpu.opened_at,
            closed_at=gpu.closed_at,
            off_reading=dict(gpu.off_reading or {}),
            verified_off=gpu.verified_off,
            remote_job_ids=list(gpu.remote_job_ids or []),
            job_row_ids=[row.id for row in rows],
            take_ids=takes,
            classes={row.id: _row_class(row, gpu.id) for row in rows},
            proof_problems=problems,
        )
    return None


def candidates(session: Session) -> list[Candidate]:
    """Every hold not released and not decided since whose cause is a RunPod /run with no
    job id."""
    released = _released_holds(session)
    found: list[Candidate] = []
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type.in_((STILL_HOLD_EVENT, MOTION_HOLD_EVENT)))
        .order_by(DomainEvent.sequence)
    ):
        if event.event_id in released or _hold_shape(event) is None:
            continue
        if _superseded(session, event):
            continue
        candidate = _candidate(session, event)
        if candidate is not None:
            found.append(candidate)
    return found


def _is_gap(problem: str) -> bool:
    return any(problem == gap or problem.startswith(gap + ":") for gap in PROOF_GAPS)


def recorded_problems(session: Session, candidate: Candidate) -> list[str]:
    """Why what the studio recorded about the session is not clean enough to even ask him (an
    empty list when it is). Unread counts from before 2026-10-09, and the gaps an in-step proof
    found (`PROOF_GAPS`), are what his card is for; a count that is not 0, a job RunPod
    accepted, a billed second, a shared endpoint or a SIGN the proof found (a claim or a
    manifest in his bucket: the worker started or made the item) is not."""
    problems: list[str] = []
    if candidate.remote_job_ids:
        problems.append("JOBS_ACCEPTED")
    reading = candidate.off_reading
    if candidate.verified_off is not True or reading.get("off") is not True:
        problems.append("OFF_NOT_VERIFIED")
    for name in ("workers_max", "running", "in_progress", "in_queue"):
        if _count(reading.get(name)) != 0:
            problems.append(f"OFF_{name.upper()}:{reading.get(name)}")
    evidence = reading.get("evidence")
    if isinstance(evidence, dict):
        if evidence.get("shared") or evidence.get("other_sessions"):
            problems.append("SHARED_ENDPOINT")
        before = evidence.get("before_purge")
        if isinstance(before, dict):
            for name in ("in_queue", "in_progress", "running"):
                value = _count(before.get(name))
                if value is not None and value != 0:
                    problems.append(f"BEFORE_PURGE_{name.upper()}:{value}")
        removed = _count(evidence.get("purge_removed"))
        if removed is not None and removed != 0:
            problems.append(f"PURGE_REMOVED:{removed}")
    for problem in candidate.proof_problems or []:
        if not _is_gap(problem):
            problems.append("PROOF:" + problem)
    if overlapping_sessions(
        session,
        candidate.endpoint_id,
        candidate.gpu_session_id,
        candidate.opened_at,
        candidate.closed_at,
    ):
        problems.append("SHARED_ENDPOINT")
    if any(_billed(session, row_id) for row_id in candidate.job_row_ids):
        problems.append("BILLED")
    return list(dict.fromkeys(problems))


def _billed(session: Session, row_id: str) -> bool:
    row = session.get(GenerationJob, row_id)
    if row is None:
        return True  # a row that cannot be read is never taken for one that cost nothing
    return any(
        _nonzero(amount)
        for amount in (row.billed_seconds_value, row.cost_value, row.gpu_seconds_value)
    )


def _nonzero(amount: str | None) -> bool:
    """A recorded amount that is not nothing: an unreadable one counts as something."""
    if amount is None or not str(amount).strip():
        return False
    try:
        return Decimal(str(amount)) != 0
    except InvalidOperation:
        return True


def _blockers(session: Session, candidate: Candidate) -> list[str]:
    """Why no card is offered (or his yes refused) for this hold; empty when it may be."""
    classes = set(candidate.classes.values())
    blockers: list[str] = []
    if CHANGED in classes:
        blockers.append("ANSWERED_SINCE")
    if IN_FLIGHT in classes:
        blockers.append("BEING_SENT")
    return blockers + recorded_problems(session, candidate)


# --------------------------------------------------------------------------------- the card


def _when_ro(value: str) -> str:
    moment = _moment(value)
    if moment is None:
        return "la ora înregistrată"
    moment = moment.astimezone(UTC)
    return f"pe {moment:%d.%m.%Y} la {moment:%H:%M} UTC"


def _first_upper(text: str) -> str:
    """The first letter upper case, the rest as written («UTC» stays «UTC»)."""
    return text[:1].upper() + text[1:]


def _record_ro(candidate: Candidate) -> str:
    """What the close and the in-step proof recorded beyond the off reading, and what they
    could not: built from what was recorded, never assumed (2026-10-09 review)."""
    reading = candidate.off_reading
    evidence = reading.get("evidence")
    if not isinstance(evidence, dict):
        return LEGACY_GAP_RO
    known: list[str] = []
    missing: list[str] = []
    before = evidence.get("before_purge")
    if isinstance(before, dict) and all(
        _count(before.get(name)) == 0 for name in ("in_queue", "in_progress", "running")
    ):
        known.append("coada citită înainte de golire era goală")
    else:
        missing.append("coada nu a putut fi citită înainte de golire")
    if _count(evidence.get("purge_removed")) == 0:
        known.append("golirea cozii nu a scos nicio lucrare")
    else:
        missing.append("răspunsul golirii cozii nu a spus câte lucrări a scos")
    problems = candidate.proof_problems or []
    if any(problem.startswith("BUCKET_UNREADABLE") for problem in problems):
        missing.append("ce a lăsat lucrătorul în bucket nu s-a putut citi")
    elif "NO_BUCKET" in problems:
        missing.append(
            "bucketul pentru rezultate nu era configurat, deci ce a lăsat lucrătorul nu s-a "
            "putut citi"
        )
    else:
        # The proof reads the bucket only once the queue part is complete (or it never ran).
        missing.append("ce a lăsat lucrătorul în bucket nu a fost citit")
    said = _first_upper("; ".join(known)) + ". " if known else ""
    return (
        said
        + _first_upper(", ".join(missing))
        + ", așa că studioul singur nu poate dovedi că nimic nu s-a făcut."
    )


def release_card(candidate: Candidate) -> dict[str, Any]:
    """His card: what was recorded, what it does not prove, where he checks, and his choice."""
    count = len(candidate.job_row_ids)
    what = "imagini" if candidate.purpose == "image" else "cadre"
    if count == 1:
        what = "o imagine" if candidate.purpose == "image" else "un cadru"
    else:
        what = f"{count} {what}"
    endpoint = candidate.endpoint_id
    later = ""
    if candidate.rows_in(ELSEWHERE, PROVEN, OWNER, UNSENT_AT_SEND):
        later = (
            " Între timp aceleași cereri au fost trimise din nou (o refacere); ce s-a întâmplat "
            "atunci are propria înregistrare, aici decizi doar pentru prima trimitere."
        )
    return {
        "kind": CARD_KIND,
        "dedupe_key": card_key(candidate.hold_event_id),
        "title_ro": f"Nu s-a trimis nimic la RunPod: eliberez scena {candidate.scene_number}?",
        "why_ro": (
            f"{_first_upper(_when_ro(candidate.opened_at))}, cererea pentru scena "
            f"{candidate.scene_number} ({what}) a primit de la RunPod o eroare fără numărul "
            "lucrării, așa că studioul a ținut scena pentru tine (poate fi taxată). Ce a "
            "înregistrat studioul atunci: RunPod nu a acceptat nicio lucrare în acea sesiune "
            f"GPU; la oprirea GPU-ului, după golirea cozii, endpoint-ul {endpoint} citea 0 la "
            "coadă, 0 în lucru, 0 workeri care rulează, cu limita de workeri 0; nicio secundă "
            "facturată pe aceste cereri; niciun alt pas nu a folosit GPU-ul între timp. "
            f"{_record_ro(candidate)}{later} Verifică în consola RunPod (Serverless → "
            f"{endpoint}: Requests, Logs, Billing) că la acea oră nu există nicio lucrare și "
            "niciun cost."
        ),
        "effect_ro": (
            f"«Eliberez scena»: cererile ({what}) se trec ca netrimise, cu 0 credite; refuzurile "
            f"lor nu mai țin scena {candidate.scene_number}, care se poate cumpăra din nou, cu "
            "aprobarea ta, cu aceleași chei (o lucrare făcută totuși ar fi refolosită, nu "
            "plătită de două ori). Acum nu se trimite și nu se cumpără nimic. Estimarea deja "
            "trecută în registru pentru acea rundă rămâne cum este."
        ),
        "subject_type": "storyboard",
        "subject_id": candidate.storyboard_id,
        "options": [
            {
                "key": "release",
                "label_ro": f"Da, eliberez scena {candidate.scene_number}",
                "effect_ro": "Cererile se trec ca netrimise (0 credite) și scena se poate "
                "cumpăra din nou, cu aprobarea ta.",
                "recommended": True,
                "apply": {
                    "type": APPLY_TYPE,
                    "hold_event_id": candidate.hold_event_id,
                    "storyboard_id": candidate.storyboard_id,
                    "scene_number": candidate.scene_number,
                    "gpu_session_id": candidate.gpu_session_id,
                },
            },
            {
                "key": "keep",
                "label_ro": "Nu, scena rămâne ținută",
                "effect_ro": "Nu se schimbă nimic; decizi pe foaia de filmare.",
                "apply": {"type": "none"},
            },
        ],
        "clears_when": {"type": CONDITION, "hold_event_id": candidate.hold_event_id},
    }


def release_cards(session: Session) -> list[dict[str, Any]]:
    """The cards for the holds whose record is clean, for the audit's seed (at boot). A hold
    every row of which a later proof covered is released without him (`settle_proven_holds`)."""
    return [
        release_card(candidate)
        for candidate in candidates(session)
        if not candidate.all_proven and not _blockers(session, candidate)
    ]


def _ever_asked(session: Session, dedupe_key: str) -> bool:
    from app.decisions.models import OwnerDecision  # noqa: PLC0415 - decisions read media

    return (
        session.scalars(
            select(OwnerDecision.id).where(OwnerDecision.dedupe_key == dedupe_key).limit(1)
        ).first()
        is not None
    )


# ---------------------------------------------------------------------------- the release


def _release(
    session: Session, candidate: Candidate, *, by: str, correlation_id: str
) -> dict[str, Any]:
    """The hold released, in the caller's transaction (which holds the write lock): on his
    card (``by`` "owner") its OPEN rows FAILED/UNSENT at 0 cost with the release on them; on a
    later proof (``by`` "proof") the rows already carry it. Its takes not queued either way.
    A row sent again since by another session (ELSEWHERE) is left to that session's hold."""
    moment = utc_now()
    note = {
        "by": by,
        "gpu_session_id": candidate.gpu_session_id,
        "released_at": moment,
        "correlation_id": correlation_id,
    }
    marked: list[str] = []
    proven_by: set[str] = set()
    for row_id in candidate.job_row_ids:
        row = session.get(GenerationJob, row_id)
        if row is None:
            continue
        mark = _output(row).get("not_queued")
        if candidate.classes.get(row_id) == PROVEN and isinstance(mark, dict):
            proven_by.add(str(mark.get("gpu_session_id") or ""))
        if by != "owner" or candidate.classes.get(row_id) != OPEN or not _uncertain_row(row):
            continue
        row.status, row.error_code, row.finished_at = "FAILED", UNSENT, moment
        row.cost_value = row.gpu_seconds_value = "0"
        row.output = {**_output(row), "not_queued": {"proven": False, **note}}
        marked.append(row.id)
    number = candidate.scene_number
    if by == "owner":
        detail = OWNER_DETAIL
        reason = (
            f"Scena {number} nu mai așteaptă decizia Proprietarului: el a confirmat pe card că "
            "cererea nu a ajuns la RunPod. Se poate cumpăra din nou, cu aprobarea lui; nu s-a "
            "cumpărat nimic acum."
        )
    else:
        detail = PROOF_DETAIL
        reason = (
            f"Scena {number} nu mai așteaptă decizia Proprietarului: o rundă ulterioară cu "
            "aceleași chei a dovedit că cererea fără răspuns nu a ajuns la lucrător. Se poate "
            "cumpăra din nou, cu aprobarea lui; nu s-a cumpărat nimic acum."
        )
    takes = recode_not_queued(
        session, candidate.take_ids, detail=detail, correlation_id=correlation_id, by=by
    )
    record = {
        "released_event_id": candidate.hold_event_id,
        "released_sequence": candidate.hold_sequence,
        "hold_event": candidate.hold_event,
        "scene_number": number,
        "take_ids": takes,
        "job_row_ids": list(candidate.job_row_ids),
        "rows": dict(candidate.classes),
        "marked_unsent": marked,
        "proven_by": sorted(identifier for identifier in proven_by if identifier),
        "gpu_session_id": candidate.gpu_session_id,
        "endpoint_id": candidate.endpoint_id,
        "off_reading": candidate.off_reading,
        "proof_problems": candidate.proof_problems,
        "by": by,
        "reason_ro": reason,
    }
    event = append_event(
        session,
        RUNPOD_UNSENT_RELEASED_EVENT,
        "storyboard",
        candidate.storyboard_id,
        1,
        record,
        correlation_id,
    )
    logger.info(
        "runpod_unsent_hold_released",
        extra={
            "storyboard_id": candidate.storyboard_id,
            "scene_number": number,
            "by": by,
            "rows": len(candidate.job_row_ids),
            "marked_unsent": len(marked),
        },
    )
    return {**record, "storyboard_id": candidate.storyboard_id, "event_id": event.event_id}


def _hold_event(session: Session, hold_event_id: str) -> DomainEvent | None:
    if not hold_event_id:
        return None
    return session.scalars(select(DomainEvent).where(DomainEvent.event_id == hold_event_id)).first()


def settle_proven_holds(engine: Engine, *, correlation_id: str) -> list[dict[str, Any]]:
    """Release, without him, every hold whose rows a later round's proof all covered (a redo
    sent the same keys: nothing waited in the queue and the worker never started any of
    them). Checked again under the write lock; idempotent; nothing sent, nothing bought."""
    with Session(engine) as session:
        ready = [
            candidate.hold_event_id
            for candidate in candidates(session)
            if candidate.all_proven
            and not any(_billed(session, row) for row in candidate.job_row_ids)
        ]
    if not ready:
        return []
    released: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        done = _released_holds(session)
        for hold_event_id in ready:
            event = _hold_event(session, hold_event_id)
            if event is None or hold_event_id in done or _superseded(session, event):
                continue
            candidate = _candidate(session, event)
            if (
                candidate is None
                or not candidate.all_proven
                or any(_billed(session, row) for row in candidate.job_row_ids)
            ):
                continue
            released.append(_release(session, candidate, by="proof", correlation_id=correlation_id))
    return released


def propose_release_cards(engine: Engine, *, correlation_id: str) -> dict[str, Any]:
    """The watchdog's pass (the seed's at boot): first the holds a later proof covered are
    released (`settle_proven_holds`), then a hold with a clean record is his card, once per
    hold, ever. His yes releases it (`apply_release`). Nothing sent, nothing bought."""
    from app.decisions.services import propose_owner_decision  # noqa: PLC0415

    released = settle_proven_holds(engine, correlation_id=correlation_id)
    with Session(engine) as session:
        asked = release_cards(session)
    cards: list[str] = []
    if asked:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            for card in asked:
                if _ever_asked(session, card["dedupe_key"]):
                    continue
                row = propose_owner_decision(session, source=SOURCE, **card)
                cards.append(row.id)
    if cards:
        logger.info("runpod_unsent_cards_proposed", extra={"cards": len(cards)})
    return {"cards": cards, "released": [item["event_id"] for item in released]}


def apply_release(engine: Engine, spec: dict[str, Any], inner: str) -> dict[str, Any]:
    """His accept of the card: the hold is checked again under the write lock (still held by
    the same unanswered /run, not decided since, nothing of it answered, the record still
    clean) and released. Idempotent by the inner command id; a hold that changed meanwhile
    refuses with his reason and changes nothing."""
    from app.decisions.services import DecisionApplyFailed  # noqa: PLC0415
    from app.models import CommandRecord  # noqa: PLC0415
    from app.services import command_hash, remember_command  # noqa: PLC0415

    hold_event_id = str(spec.get("hold_event_id") or "")
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        previous = session.get(CommandRecord, inner)
        if previous is not None:
            done = dict(previous.response)
            return {"command": COMMAND, "result": done, "event_id": done.get("event_id")}
        event = _hold_event(session, hold_event_id)
        candidate = (
            _candidate(session, event)
            if event is not None
            and hold_event_id not in _released_holds(session)
            and not _superseded(session, event)
            else None
        )
        if candidate is None or candidate.storyboard_id != spec.get("storyboard_id"):
            raise DecisionApplyFailed(
                "Scena nu mai este ținută de această cerere RunPod (a fost eliberată, refăcută "
                "sau decisă între timp); nu s-a aplicat nimic."
            )
        problems = _blockers(session, candidate)
        if problems:
            raise DecisionApplyFailed(
                "Ce a înregistrat studioul despre acea sesiune GPU nu mai este curat ("
                + ", ".join(problems)
                + "); nu s-a aplicat nimic."
            )
        record = _release(session, candidate, by="owner", correlation_id=inner)
        remember_command(session, inner, COMMAND, command_hash(dict(spec)), record)
    return {"command": COMMAND, "result": record, "event_id": record["event_id"]}


def hold_cleared(session: Session, hold_event_id: str) -> bool:
    """His card's question has gone away: the hold was released, his own decision on the scene
    superseded it, or RunPod answered one of its requests since (a redo sent the same key and
    got a job id: what happened is no longer «nothing was sent»). Not when its rows merely
    moved from uncertain to proven: the hold still holds the scene until it is released."""
    if hold_event_id in _released_holds(session):
        return True
    event = _hold_event(session, hold_event_id)
    if event is None or _superseded(session, event):
        return True
    candidate = _candidate(session, event)
    return candidate is None or CHANGED in candidate.classes.values()
