"""One paid round on RunPod Serverless: ONE /run job carrying every item (``amn.batch.v1``).

The Owner, 2026-10-08: «trebuie sa se opreasca imediat dupa, nu la 30 sec. Sunt taxat la
secunda, deci trebuie oprit imediat dupa generare». RunPod bills a worker from when it starts
until it fully stops, rounded up to the second: the cold start (the models loading), the
execution and the idle timeout (https://docs.runpod.io/serverless/pricing). So a round is not
one job per still: it is one job whose input lists every item, and the worker loads its models
once, makes every item in index order, and scales to zero 1 s (idleTimeout) after the last.

* Each item keeps its own journal row (`jobs.GenerationJob`), its own idempotency key and its
  own SceneTake. The row is reserved before /run; the /run answer's job id is saved on every
  item row ("<job>:<index>", ``batch_remote_id``, ``batch_index``, ``gpu_session_id``) and the
  GPU session notes the job, then each item's take is written SUBMITTED, all before any poll.
* Pictures (references, first frames) go to the Owner's bucket content-addressed
  (``inputs/<sha256>.<ext>``) through a presigned PUT and travel as presigned GET URLs: the
  /run body stays tiny (RunPod's limit is 10 MB) and the journal keeps {sha256, bytes, mime},
  never base64.
* A round longer than the per-job executionTimeout cap is cut into chunks that are all POSTed
  back-to-back before any poll, so the queue never empties and the one worker keeps its models.
  Each chunk carries ``policy.executionTimeout`` (cold start + its item budgets, capped) and
  ``policy.ttl`` (that + the queue wait), https://docs.runpod.io/serverless/endpoints/send-requests.
* An item is collected from its bucket manifest first (``manifests/<key>.json``, written by the
  worker as each item finishes), then from GET /status/<job>: RunPod keeps a /run result only
  30 minutes (https://docs.runpod.io/serverless/endpoints/operation-reference.md), the manifest
  as long as the bucket does. A /status 404 with no manifest is EXPIRED_UNDELIVERED.
* An uncertain /run (sent, no answer) leaves its items SUBMISSION_UNCERTAIN: never sent again
  outside a GPU session, re-included with the SAME keys in the next round or step, where the
  worker's manifest/claim makes it a free reuse, never a second generation. Once the session
  is closed, `BatchRun.prove_unsent` reads what its off recorded (the queue before the purge,
  RunPod's purge count, the verified off) and the worker's bucket record: proven never queued
  and never made, the items are UNSENT at 0 cost (2026-10-09); otherwise they stay uncertain.
* A /run RunPod refused whole (`refused_unqueued`: never left, a paused 409, its 4xx refusals,
  429) is raised as `BatchRefused` (unsent) with RunPod's words when nothing of the round left
  the studio: every layer above already turns that into a refusal that books nothing. Live
  2026-10-09 17:24 UTC a paused 409 travelled up raw instead, and the sheet booked the round as
  a purchase and wrote the Owner «s-a oprit după ce a plătit»; in the daily run it would have
  opened safe mode. Each refused row keeps RunPod's answer (``output.run_refusal``); those
  journal writes are best effort, so a «database is locked» never turns a refusal that queued
  nothing into a purchase (review 2026-10-10, `_journal_failed`).

Nothing here switches the GPU on or off: that is `gpu_session` (the caller's ``session``).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote

from runpod_worker import contract
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.providers.media_http import MediaProviderError
from app.providers.runpod import s3, weights
from app.providers.runpod.client import RunPodClient, Transport
from app.providers.runpod.config import BucketConfig, RunPodConfig
from app.providers.runpod.errors import IdempotencyConflict, RunPodProtocolError
from app.providers.runpod.jobs import GenerationJob, JobStore, digest, now, target_identity
from app.providers.runpod.models import TERMINAL, reference_spec

if TYPE_CHECKING:
    from app.providers.runpod.gpu_session import GpuSession

logger = logging.getLogger("studio.runpod")

#: How long a presigned GET of an input picture lives: the job runs inside its ttl.
INPUT_URL_TTL = 7200
#: Margin between the job's executionTimeout and the handler's own time budget.
HANDLER_MARGIN_SECONDS = 15
#: RunPod's /run states mapped onto the journal's.
RUN_STATES = {"IN_QUEUE": "QUEUED", "IN_PROGRESS": "RUNNING"}
#: The error codes of items this run never sent or never got an answer for.
UNSENT = "UNSENT"
UNCERTAIN = "SUBMISSION_UNCERTAIN"
EXPIRED = "EXPIRED_UNDELIVERED"
#: The Owner's line for what a round costs besides its items.
OVERHEAD_LINE_RO = "GPU: pornire și încărcarea modelelor"
#: Why a step stopped when its /run failed and the GPU-off proved RunPod queued nothing
#: (`BatchRun.prove_unsent`, 2026-10-09): nothing was bought, nothing is sent again by itself.
NOT_QUEUED_STOP = (
    "RunPod nu a primit cererea: la oprirea GPU-ului coada era goală (nicio lucrare scoasă, "
    "nimic în lucru, niciun worker pornit), iar lucrătorul nu a început nimic din ea. Nu s-a "
    "cumpărat nimic și nu se retrimite automat; pasul se poate porni din nou."
)
#: The same proof for a step that had already bought an earlier round (or, in the motion step,
#: a scene on a per-second model): what was bought stays (review 2026-10-10: «Nu s-a cumpărat
#: nimic» stood next to the round booked before it).
NOT_QUEUED_REST_STOP = (
    "RunPod nu a primit ultima cerere: la oprirea GPU-ului coada era goală (nicio lucrare "
    "scoasă, nimic în lucru, niciun worker pornit), iar lucrătorul nu a început nimic din ea. "
    "Restul pasului nu s-a cumpărat și nu se retrimite automat; ce s-a cumpărat înainte rămâne."
)
#: The event of each proof attempt, proven or not (aggregate: the GPU session).
PROOF_EVENT = "runpod.run_queue_proof"
#: The item states an outcome takes.
OutcomeState = Literal["COMPLETED", "FAILED", "CANCELLED", "PENDING"]


class BatchRefused(MediaProviderError):
    """Nothing was queued and nothing spent: the round could not even be prepared, or RunPod
    refused its /run whole (`refused_unqueued`). ``http_status`` and ``detail`` are RunPod's
    answer when it gave one. ``after_purchase_ro`` is the same refusal for a step that had
    already bought an earlier round or chunk (`refusal_words`), when ``reason_ro`` says that
    nothing was bought."""

    def __init__(
        self,
        code: str,
        reason_ro: str,
        *,
        http_status: int | None = None,
        detail: str | None = None,
        after_purchase_ro: str | None = None,
    ) -> None:
        super().__init__(reason_ro, code=code, unsent=True, http_status=http_status, detail=detail)
        self.reason_ro = reason_ro
        self.after_purchase_ro = after_purchase_ro


#: The clause of a refusal written for a step that bought nothing («; nu s-a trimis și nu s-a
#: cheltuit nimic», «Nu s-a trimis și nu s-a cumpărat nimic; …»), up to its sentence's end.
_NOTHING_CLAUSE = re.compile(r"[;,]?\s*nu s-a (?:trimis|cheltuit|cumpărat)\b[^.]*\.?", re.I)


def refusal_words(exc: BaseException, *, bought_before: bool) -> str:
    """The Owner's words for a refusal that stopped a step. Once the step had bought an earlier
    round or chunk (or, in the motion step, a scene on a per-second model before its RunPod
    part), the words never say it bought nothing (review 2026-10-09: «nu s-a cumpărat nimic»
    stood in his letter next to the credits booked for that stair). A refusal with no words of
    its own for that case (the GPU would not switch on: GPU_BUSY, COMPUTE_NOT_READY,
    RUNPOD_OFF …) keeps its reason without the «nothing spent» clause, its code, and says
    what stays (review 2026-10-10)."""
    said = str(getattr(exc, "reason_ro", None) or exc)
    if not bought_before:
        return said
    later = getattr(exc, "after_purchase_ro", None)
    if later:
        return str(later)
    code = getattr(exc, "code", None)
    if code == "GPU_FORCED_OFF":
        return said  # `gpu_session.FORCED_OFF_WORDS`: what was bought stays, the rest was not
    core = _NOTHING_CLAUSE.sub("", said).strip().rstrip(".;:, ")
    named = f" ({code})" if code else ""
    return f"{core}{named}. {REST_NOT_SENT_RO}" if core else f"{code}: {REST_NOT_SENT_RO}"


#: RunPod's statuses that refuse a /run whole: the request was judged and turned away before
#: any job existed (no job id), so nothing was queued and no worker ran for it. 400/401/403/
#: 404/413/422 were already the studio's list (docs/RUNPOD_INTEGRATION.md: «definite
#: non-billable … refusal»). 429 was not, so a rate-limited /run became SUBMISSION_UNCERTAIN and
#: held its scene until the close-time proof (2026-10-09 audit). RunPod's own pages were not
#: read for it here (no network); the studio already takes 429 for «not served, ask again»
#: from every vendor it buys from (`app.providers.retry.SAFE_TO_RESEND_STATUSES`, Runway's
#: documented "May retry"; `media.assembler.possibly_charged`: any 4xx made nothing).
REFUSED_STATUSES = frozenset({400, 401, 403, 404, 413, 422, 429})


def endpoint_paused(exc: BaseException) -> bool:
    """RunPod's «Endpoint is paused (max_workers=0)» refusal of a /run: answered, 409, its
    words say so. Nothing is queued: the endpoint takes no job while workers.max is 0."""
    if not isinstance(exc, MediaProviderError):
        return False
    words = f"{exc.detail or ''} {exc}".lower()
    return (
        exc.http_status == 409
        and not exc.unanswered
        and ("paused" in words or "max_workers" in words)
    )


def refused_unqueued(exc: BaseException) -> bool:
    """Whether a failed /run (or a lone Pod submit) proves RunPod queued nothing: it never
    left this machine, or RunPod answered a refusal (`REFUSED_STATUSES`, a paused 409).

    The one list (2026-10-09): four copies disagreed, and the one the step's meter read had no
    409, so a paused endpoint's refusal was booked as a purchase. A 409 in other words is NOT
    proof (it could name a job that exists): its items stay SUBMISSION_UNCERTAIN, and the GPU
    session's close proves them never queued for free (`BatchRun.prove_unsent`)."""
    if not isinstance(exc, MediaProviderError):
        return False
    if exc.unsent:
        return True
    if exc.unanswered:
        return False
    return exc.http_status in REFUSED_STATUSES or endpoint_paused(exc)


#: The step's stop (the autonomy stop, his mode, his plan: `gpu_batch.run_rounds`' stop
#: reason), read before each wait for a paused endpoint and before each /run sent again after
#: it (2026-10-09 audit: a STOP pressed during the ~3 minute wait did not stop the /run). It rides
#: on the context because the adapter's ``submit_batch`` (adapters.py) has no parameter for it;
#: `submit_round` also takes it explicitly (``should_stop``), which wins.
STEP_STOP: ContextVar[Callable[[], str | None] | None] = ContextVar(
    "runpod_step_stop", default=None
)


@contextmanager
def step_stop(should_stop: Callable[[], str | None] | None) -> Iterator[None]:
    """``should_stop`` is the step's stop for every round submitted inside the block."""
    token = STEP_STOP.set(should_stop)
    try:
        yield
    finally:
        STEP_STOP.reset(token)


@dataclass(frozen=True)
class BatchRequest:
    """One item a stage wants made in this round."""

    operation: Literal["image", "video"]
    project_id: str
    scene_id: str
    candidate_index: int
    attempt_number: int
    model: str
    prompt: str
    negative_prompt: str | None
    seed: int
    width: int
    height: int
    duration: float | None
    fps: int | None
    references: tuple[bytes, ...]
    source_image: bytes | None
    price_usd: Decimal


@dataclass
class SubmittedItem:
    request: BatchRequest
    job_row_id: str
    idempotency_key: str
    #: "<job>:<index>" once RunPod accepted the job; None while uncertain or unsent.
    remote_item_id: str | None


@dataclass
class ItemOutcome:
    item: SubmittedItem
    state: OutcomeState
    path: Path | None
    mime: str | None
    gpu_seconds: float | None
    error: str | None


def item_seed(storyboard_id: str, scene: int | str, attempt: int, candidate: int) -> int:
    """A deterministic seed per item (a re-roll is a new attempt, so a new seed)."""
    text = f"{storyboard_id}|{scene}|{attempt}|{candidate}"
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def picture_kind(content: bytes) -> tuple[str, str]:
    """(mime, extension) of a picture sent as a reference or first frame."""
    if content.startswith(b"\x89PNG"):
        return "image/png", "png"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg", "jpg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise RunPodProtocolError("Source image must be PNG, JPEG or WebP")


def picture_digest(content: bytes) -> dict[str, Any]:
    """What the journal keeps of a picture: its sha256, its size and its type."""
    mime, _ext = picture_kind(content)
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content), "mime": mime}


def supports_batch(adapter: Any) -> bool:
    """Whether a paid step buys through rounds of batches (RunPod Serverless, or its mock)."""
    check = getattr(adapter, "supports_batch", None)
    return bool(callable(check) and check())


def journal_payload(request: BatchRequest) -> dict[str, Any]:
    """The item's request as journalled and hashed: the pictures by digest only."""
    payload: dict[str, Any] = {
        "batch": True,
        "project_id": request.project_id,
        "scene_id": request.scene_id,
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "seed": request.seed,
        "model": request.model,
        "candidate_index": request.candidate_index,
        "attempt_number": request.attempt_number,
        "width": request.width,
        "height": request.height,
        "reference_images": [picture_digest(b) for b in request.references],
    }
    spec = reference_spec(request.model)
    if request.references and spec is not None:
        # Which workflow input each picture was bound to: what the model really received.
        payload["reference_bindings"] = list(spec["bindings"][: len(request.references)])
    if request.operation == "video":
        payload["duration"] = request.duration
        payload["fps"] = request.fps or contract.CLIP_FPS
        payload["source_image"] = (
            picture_digest(request.source_image) if request.source_image else None
        )
    return payload


def route_references(request: BatchRequest) -> BatchRequest:
    """The item as the worker will really make it (the 2511 route, 2026-10-09).

    A model whose catalogue entry declares no reference binding never receives a picture
    (refused unsent: the record would otherwise say a still was drawn from a picture the graph
    ignored); more pictures than it binds are refused too; an item with fewer than it needs is
    drawn by the route's text model on the same endpoint, and its journal row says so."""
    if request.operation != "image":
        return request
    spec = reference_spec(request.model)
    if spec is None:
        if request.references:
            raise BatchRefused(
                "REFERENCE_NOT_ACCEPTED",
                f"Modelul {request.model} nu primește imagini de referință; nu se trimite nimic.",
            )
        return request
    if len(request.references) > int(spec.get("max") or 0):
        raise BatchRefused(
            "TOO_MANY_REFERENCES",
            f"Modelul {request.model} primește cel mult {spec.get('max')} imagini de referință; "
            "nu se trimite nimic.",
        )
    if len(request.references) < int(spec.get("min") or 0):
        text_model = spec.get("text_model")
        if not isinstance(text_model, str) or not text_model:
            raise BatchRefused(
                "NEEDS_REFERENCE",
                f"Modelul {request.model} desenează doar din imagini de referință.",
            )
        from dataclasses import replace  # noqa: PLC0415

        return replace(request, model=text_model)
    return request


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def queue_problems(evidence: Any) -> list[str]:
    """Why the GPU-off evidence of a session does NOT prove that RunPod queued nothing; an
    empty list when it does (`BatchRun.prove_unsent`). Each count must have been read and be 0:
    an unread count, or a purge answer without its count, is never taken for zero."""
    if not isinstance(evidence, dict):
        return ["NO_EVIDENCE"]
    problems: list[str] = []
    if evidence.get("shared") or evidence.get("other_sessions"):
        problems.append("SHARED_ENDPOINT")
    before = evidence.get("before_purge")
    if not isinstance(before, dict):
        problems.append("QUEUE_UNREAD_BEFORE_PURGE")
    else:
        for field_name, code in (
            ("in_queue", "QUEUED"),
            ("in_progress", "IN_PROGRESS"),
            ("running", "RUNNING"),
        ):
            value = _count(before.get(field_name))
            if value is None:
                problems.append(f"{code}_UNREAD")
            elif value != 0:
                problems.append(f"{code}_BEFORE_PURGE:{value}")
    removed = _count(evidence.get("purge_removed"))
    if removed is None:
        problems.append("PURGE_UNANSWERED")
    elif removed != 0:
        problems.append(f"PURGE_REMOVED:{removed}")
    off = evidence.get("off")
    if not isinstance(off, dict) or off.get("off") is not True:
        problems.append("OFF_NOT_VERIFIED")
    return problems


def item_budget(config: RunPodConfig, operation: str) -> int:
    return int(
        config.still_item_budget_seconds
        if operation == "image"
        else config.clip_item_budget_seconds
    )


def chunk_items(config: RunPodConfig, operation: str, count: int) -> list[range]:
    """Index ranges of the round's chunks: each fits the executionTimeout cap and MAX_ITEMS."""
    budget = item_budget(config, operation)
    room = int(config.execution_timeout_cap_seconds) - int(config.cold_start_seconds)
    per_chunk = max(1, min(contract.MAX_ITEMS, room // budget if budget else contract.MAX_ITEMS))
    return [range(start, min(count, start + per_chunk)) for start in range(0, count, per_chunk)]


def chunk_policy(config: RunPodConfig, operation: str, items: int) -> dict[str, int]:
    """RunPod's per-job policy: the execution timeout (ms) and the ttl (ms)."""
    seconds = min(
        int(config.execution_timeout_cap_seconds),
        int(config.cold_start_seconds) + items * item_budget(config, operation),
    )
    seconds = max(5, seconds)  # RunPod's documented minimum executionTimeout is 5 s
    # A cache miss can happen on ANY round (RunPod «tries» a host that holds the model, else
    # delays the worker until the download ends, unbilled), and the ttl counts from the
    # submission: under the cached-model source the unbilled wait is always inside the ttl.
    # The billed executionTimeout never grows with it.
    cache_wait = (
        int(config.model_cache_wait_seconds)
        if config.model_source == "cache" and not config.mock
        else 0
    )
    return {
        "executionTimeout": seconds * 1000,
        "ttl": (seconds + int(config.queue_wait_seconds) + cache_wait) * 1000,
    }


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


# --------------------------------------------------------------------------- the journal


def _key(config: RunPodConfig, integration_id: str | None, payload: dict[str, Any], op: str) -> str:
    return digest(
        [
            target_identity(config, integration_id),
            payload["project_id"],
            payload["scene_id"],
            payload["attempt_number"],
            op,
            payload.get("candidate_index", 0),
        ]
    )


def reserve_item(
    store: JobStore,
    config: RunPodConfig,
    integration_id: str | None,
    request: BatchRequest,
) -> tuple[GenerationJob, str, BatchRequest]:
    """The item's journal row and what to do with it: SEND, RESEND (same key, uncertain or
    reserved and never answered before), TRACK (already accepted remotely, still open).

    A key whose row was used up (judged, collected, failed, cancelled) moves to the next
    attempt: a redo without a verdict never reuses a spent key."""
    attempt = request.attempt_number
    for _ in range(1000):
        current = request if attempt == request.attempt_number else _with_attempt(request, attempt)
        payload = journal_payload(current)
        key = _key(config, integration_id, payload, request.operation)
        hashed = digest(payload)
        with Session(store.engine, expire_on_commit=False) as s, s.begin():
            lock_for_write(s)
            row = s.scalar(select(GenerationJob).where(GenerationJob.idempotency_key == key))
            if row is None:
                row = GenerationJob(
                    id=_uuid(),
                    idempotency_key=key,
                    payload_hash=hashed,
                    request_digest=hashed,
                    integration_id=integration_id,
                    provider="RUNPOD_MOCK" if config.mock else "RUNPOD",
                    target=target_identity(config, integration_id),
                    project_id=current.project_id,
                    scene_id=current.scene_id,
                    attempt=attempt,
                    operation=current.operation,
                    model=current.model,
                    gpu="MOCK_CPU" if config.mock else config.gpu_name,
                    hourly_rate=str(config.hourly_rate),
                    status="STARTING",
                    request=payload,
                    output={},
                    created_at=now(),
                    poll_count=0,
                )
                s.add(row)
                return row, "SEND", current
            same = (row.request_digest or row.payload_hash) == hashed
            terminal = row.status in TERMINAL
            if not same and not terminal:
                # A purchase still open is never replaced by a different request.
                raise IdempotencyConflict("Generation key was already used for another payload")
            if same and not terminal:
                if row.remote_job_id:
                    return row, "TRACK", current
                if row.error_code == UNCERTAIN:
                    # Which session left it uncertain is kept before the send names another
                    # (2026-10-09): a scene that /run held is still found by its hold after a
                    # redo sent the same keys again (`media.runpod_unsent`).
                    previous = list(dict(row.output or {}).get("resent") or [])
                    previous.append(
                        {"gpu_session_id": row.gpu_session_id, "error_code": UNCERTAIN, "at": now()}
                    )
                    row.output = {**dict(row.output or {}), "resent": previous[-20:]}
                    return row, "RESEND", current
                # Reserved and never sent (a crash before /run): send it now, same key.
                return row, "RESEND", current
            if (
                same
                and row.status == "FAILED"
                and not row.remote_job_id
                and (row.error_code == UNSENT or str(row.error_code).startswith("HTTP_"))
            ):
                # Proven never served: the creative attempt and its key are reusable.
                row.status, row.error_code, row.finished_at = "STARTING", None, None
                row.cost_value = row.gpu_seconds_value = None
                return row, "SEND", current
        # Used up (collected, judged, failed, cancelled): a new attempt, never the spent key.
        attempt += 1
    raise RunPodProtocolError("No free attempt number for this item")


def _with_attempt(request: BatchRequest, attempt: int) -> BatchRequest:
    from dataclasses import replace  # noqa: PLC0415

    return replace(request, attempt_number=attempt)


def _uuid() -> str:
    from uuid import uuid4  # noqa: PLC0415

    return str(uuid4())


# ------------------------------------------------------------------------------ the run


@dataclass
class _Chunk:
    remote_id: str | None
    items: list[SubmittedItem]
    policy: dict[str, int]
    sent_at: float
    finished: bool = False
    status: dict[str, Any] | None = None
    #: Its /run got no answer (no job id, SUBMISSION_UNCERTAIN): RunPod may have run it anyway.
    uncertain: bool = False


@dataclass
class BatchRun:
    """A round submitted to RunPod: its jobs, its items and their collection."""

    config: RunPodConfig
    engine: Engine
    integration_id: str | None
    storage_root: Path
    transport: Transport | None
    session_id: str | None
    remote_job_ids: list[str] = field(default_factory=list)
    items: list[SubmittedItem] = field(default_factory=list)
    chunks: list[_Chunk] = field(default_factory=list)
    _reported: set[str] = field(default_factory=set)
    _pending_report: list[ItemOutcome] = field(default_factory=list)
    _deadline: float = 0.0
    #: What the results proved about the endpoint's weights (`weights.check_result`).
    weights_problems: list[weights.WeightsProblem] = field(default_factory=list)
    #: Why the round stopped sending before its last chunk although an earlier chunk had left
    #: (a paused endpoint past its wait, the GPU switched off or the step stopped meanwhile):
    #: the rest was never sent, and `gpu_batch.run_rounds` sends no further round.
    refused: BatchRefused | None = None

    @property
    def weights_problem(self) -> weights.WeightsProblem | None:
        """The first result that proved the endpoint's weights wrong, or None."""
        return self.weights_problems[0] if self.weights_problems else None

    @property
    def store(self) -> JobStore:
        return JobStore(self.engine)

    def done(self) -> bool:
        return all(item.job_row_id in self._reported for item in self.items) and not (
            self._pending_report
        )

    def deadline_passed(self) -> bool:
        """Past the longest chunk's executionTimeout + queue wait: RunPod has dropped it."""
        return bool(self._deadline) and time.monotonic() > self._deadline

    def poll(self) -> list[ItemOutcome]:
        """Every item that became terminal since the last poll, each reported once."""
        outcomes = list(self._pending_report)
        self._pending_report.clear()
        if self.config.mock:
            outcomes += self._poll_mock()
        else:
            outcomes += asyncio.run(self._poll())
        fresh: list[ItemOutcome] = []
        for outcome in outcomes:
            if outcome.state == "PENDING" or outcome.item.job_row_id in self._reported:
                continue
            self._reported.add(outcome.item.job_row_id)
            fresh.append(outcome)
        if not self.config.mock:
            self._note_queue()
        return fresh

    def cancel(self, reason: str) -> None:
        """POST /cancel for every unfinished chunk; what already finished stays collectable,
        the rest is CANCELLED with no item cost (the next poll reports it)."""
        if not self.config.mock:
            asyncio.run(self._cancel_remote())
            # What finished before the cancel landed is collected (manifests), not lost.
            for outcome in asyncio.run(self._poll()):
                if outcome.state != "PENDING":
                    self._pending_report.append(outcome)
        reported = {o.item.job_row_id for o in self._pending_report} | self._reported
        for item in self.items:
            if item.job_row_id in reported:
                continue
            row = self.store.read(item.job_row_id)
            if row.status in TERMINAL:
                continue
            self.store.update(
                row.id,
                status="CANCELLED",
                error_code="CANCELLED_BY_STUDIO",
                finished_at=now(),
                cost_value="0",
                gpu_seconds_value="0",
            )
            self._pending_report.append(
                ItemOutcome(item, "CANCELLED", None, None, 0.0, "CANCELLED_BY_STUDIO")
            )
        endpoint = self.config.endpoint_for(self._operation())
        if endpoint:
            weights.clear_queue(endpoint)
        logger.info("runpod_batch_cancelled", extra={"reason": reason[:200]})

    def billed_seconds_estimate(self) -> float | None:
        """What RunPod bills for the round: `billed_seconds` of each job it accepted, summed
        (Σ executionTime + each worker start, at most ``cold_start_seconds``, + its idle tail),
        or None until every such job reported its times."""
        jobs = self._billed()
        if any(seconds is None for _chunk, seconds in jobs):
            return None
        return float(sum((seconds for _chunk, seconds in jobs if seconds is not None), Decimal(0)))

    def _billed(self) -> list[tuple[_Chunk, Decimal | None]]:
        """Each job RunPod accepted in this round, in the order it was sent, with what RunPod
        bills for it (`billed_seconds`), or None while it has not reported its times.

        A job is read against the accepted job sent just before it (the chunks go back to back
        to one worker, workers.max=1), and against the run budget (``policy.executionTimeout``)
        of every job between them whose /run got no answer: such a job may have run on the
        worker meanwhile, and its run is then inside this job's wait (2026-10-09 review)."""
        jobs: list[tuple[_Chunk, Decimal | None]] = []
        previous: dict[str, Any] | None = None
        unseen: Decimal | None = Decimal(0)
        for chunk in self.chunks:
            if chunk.remote_id is None:
                if chunk.uncertain and unseen is not None:
                    budget = _decimal(chunk.policy.get("executionTimeout"))
                    unseen = None if budget is None else unseen + budget / 1000
                continue
            jobs.append(
                (chunk, billed_seconds(self.config, chunk.status, previous=previous, unseen=unseen))
            )
            previous, unseen = chunk.status or {}, Decimal(0)
        return jobs

    def _book(self) -> None:
        """Each finished job's billed seconds onto its items (`_book_batch`). A job is booked
        again once the one before it reports: how much of its wait is a new worker start
        depends on that job's times (until then it is booked as the round's first)."""
        for chunk, seconds in self._billed():
            if chunk.finished and seconds is not None:
                _book_batch(self.engine, chunk, seconds)

    def settle(self) -> None:
        """Read each sent job's final /status once its items are in, for its times.

        Items normally arrive through their bucket manifests, so /status is never read while
        the round runs; without this read the billed seconds (`billed_seconds`: the execution,
        the worker's start and the idle tail) would stay unknown and the step would book only
        its estimate. A free GET per job; a job not final yet, or an unreadable answer, leaves
        the estimate as it is."""
        if self.config.mock:
            return
        pending = [
            c
            for c in self.chunks
            if c.remote_id is not None and not (c.finished and _has_times(c.status))
        ]
        if not pending:
            return

        async def read() -> None:
            client = self._client()
            for chunk in pending:
                try:
                    status = await client.call(
                        "GET", "/status/" + quote(str(chunk.remote_id), safe="")
                    )
                except MediaProviderError:
                    continue
                if not isinstance(status, dict):
                    continue
                chunk.status = status
                chunk.finished = str(status.get("status")) in _FINAL_RUN_STATES

        asyncio.run(read())
        self._book()

    # ------------------------------------------------------------ the proof of nothing queued

    def prove_unsent(self, session: Any) -> dict[str, Any] | None:
        """After the GPU session closed: are this round's SUBMISSION_UNCERTAIN items (a /run
        that failed with no job id and no proof it never left) proven never queued and never
        made? None when the round has no such item.

        2026-10-09: the first live stills /run failed in 0.12 s; RunPod showed no job, no
        worker and $0, but the items stayed uncertain and the film could not move. The proof
        reads nothing new from RunPod's API and guesses nothing:

        * the session's close (`gpu_session.close_session`) read the endpoint's queue BEFORE
          its purge (inQueue 0, inProgress 0, workers.running 0), RunPod's own purge answer
          removed exactly 0 jobs («Remove all pending jobs from the queue»: a job of ours still
          waiting would have been one of them), the endpoint then read OFF (max 0, nothing
          queued, in progress or running), and no other session used the endpoint meanwhile;
        * the worker's own record says it never started an item: it writes
          ``claims/<key>.json`` before any GPU work and ``manifests/<key>.json`` after (the
          worker contract), and neither exists for any of the keys (free GETs on his bucket).

        The first says nothing of ours waits or runs; the second that nothing of ours was ever
        made, even by a job that ran and ended before the close looked (the queue counts alone
        cannot see that). Only both together are a proof (``proven``); anything less (a count
        unread, a purge that removed something, a claim, an unreadable bucket, a shared
        endpoint) proves nothing and the items stay uncertain, counted and held, as before.
        This reads and judges only: `mark_unsent` writes the rows, after the stage has
        re-recorded its takes (`gpu_batch.run_rounds`). Nothing is ever sent again from here.
        The outcome is logged (``runpod_run_proof``) and written as `PROOF_EVENT`."""
        uncertain: list[GenerationJob] = []
        for item in self.items:
            row = self.store.read(item.job_row_id)
            if row.error_code == UNCERTAIN and not row.remote_job_id and row.status not in TERMINAL:
                uncertain.append(row)
        if not uncertain:
            return None
        evidence = getattr(session, "off_evidence", None)
        problems = queue_problems(evidence)
        if not problems:
            problems = asyncio.run(self._worker_records(uncertain))
        proven = not problems
        record: dict[str, Any] = {
            "proven": proven,
            "problems": problems,
            "gpu_session_id": self.session_id,
            "endpoint_id": self.config.endpoint_for(self._operation()),
            "items": [
                {"job_row_id": row.id, "idempotency_key": row.idempotency_key} for row in uncertain
            ],
            "evidence": evidence if isinstance(evidence, dict) else None,
            "checked_at": now(),
        }
        before = (evidence or {}).get("before_purge") if isinstance(evidence, dict) else None
        logger.log(
            logging.INFO if proven else logging.WARNING,
            "runpod_run_proof",
            extra={
                "proven": proven,
                "problems": problems,
                "items": len(uncertain),
                "gpu_session_id": self.session_id,
                "purge_removed": (evidence or {}).get("purge_removed")
                if isinstance(evidence, dict)
                else None,
                "before_purge": before,
                "off": (evidence or {}).get("off") if isinstance(evidence, dict) else None,
            },
        )
        if self.session_id:
            from app.providers.runpod.gpu_session import _write_event  # noqa: PLC0415 - cycle

            _write_event(self.engine, PROOF_EVENT, self.session_id, record, self.session_id)
        return record

    def mark_unsent(self, proof: dict[str, Any]) -> list[str]:
        """The items a proof (`prove_unsent`) found never queued: FAILED/UNSENT at 0 cost, the
        proof on the row. Their keys stay reusable (`reserve_item`: «proven never served»), so
        a job that somehow ran anyway would be a free reuse, never a second purchase. Only a
        row still uncertain is changed. Returns the rows changed."""
        if not proof.get("proven"):
            return []
        note = {key: proof.get(key) for key in ("proven", "gpu_session_id", "checked_at")}
        changed: list[str] = []
        for item in proof.get("items") or []:
            row = self.store.read(str(item["job_row_id"]))
            if row.error_code != UNCERTAIN or row.remote_job_id or row.status in TERMINAL:
                continue
            self.store.update(
                row.id,
                status="FAILED",
                error_code=UNSENT,
                finished_at=now(),
                cost_value="0",
                gpu_seconds_value="0",
                output={**dict(row.output or {}), "not_queued": {**note, "by": "proof"}},
            )
            changed.append(row.id)
        return changed

    async def _worker_records(self, rows: Sequence[GenerationJob]) -> list[str]:
        """What the worker left in his bucket for these keys: a claim (GPU work started) or a
        manifest (an item made). A read that fails is a problem too, never «nothing there»."""
        bucket = self.config.bucket()
        if bucket is None:
            return ["NO_BUCKET"]
        transport = self.transport or _default()
        problems: list[str] = []
        for row in rows:
            for kind, key in (
                ("CLAIM", contract.claim_key(bucket.prefix, row.idempotency_key)),
                ("MANIFEST", contract.manifest_key(bucket.prefix, row.idempotency_key)),
            ):
                try:
                    found = await s3.get_json(bucket, key, transport)
                except MediaProviderError as exc:
                    problems.append(
                        f"BUCKET_UNREADABLE:{kind}:{exc.http_status or type(exc).__name__}"
                    )
                    continue
                if found is not None:
                    problems.append(f"WORKER_{kind}:{row.idempotency_key[:12]}")
        return problems

    # ----------------------------------------------------------------- remote collection

    def _client(self) -> RunPodClient:
        endpoint = self.config.endpoint_for(self._operation())
        return RunPodClient(
            self.config.model_copy(update={"mode": "serverless", "endpoint_id": endpoint}),
            self.transport,
        )

    def _operation(self) -> Literal["image", "video"]:
        return self.items[0].request.operation if self.items else "image"

    async def _cancel_remote(self) -> None:
        client = self._client()
        for chunk in self.chunks:
            if chunk.remote_id is None or chunk.finished:
                continue
            try:
                await client.cancel(chunk.remote_id)
            except MediaProviderError as exc:
                # The session's close purges and cancels again, then sets workers.max=0.
                logger.warning(
                    "runpod_batch_cancel_failed",
                    extra={"http_status": exc.http_status, "job": chunk.remote_id},
                )

    async def _poll(self) -> list[ItemOutcome]:
        outcomes: list[ItemOutcome] = []
        client = self._client()
        bucket = self.config.bucket()
        statuses: dict[str, dict[str, Any] | None] = {}
        finished = False
        for chunk in self.chunks:
            for item in chunk.items:
                if item.job_row_id in self._reported:
                    continue
                row = self.store.read(item.job_row_id)
                if row.status in TERMINAL:
                    outcomes.append(_outcome_of(item, row))
                    continue
                if chunk.remote_id is None:
                    continue
                try:
                    outcome = await collect_row(
                        self.config,
                        self.engine,
                        row,
                        item,
                        client=client,
                        bucket=bucket,
                        storage_root=self.storage_root,
                        transport=self.transport,
                        statuses=statuses,
                        problems=self.weights_problems,
                    )
                except (RunPodProtocolError, contract.ContractError) as exc:
                    # One item whose result is wrong (a checksum, a manifest, an echo that does
                    # not match) fails alone: it was made and stays counted, the round goes on
                    # (a re-roll may buy it again inside the cap) instead of the whole paid batch
                    # being cancelled with the step.
                    outcome = _bad_output(self.engine, item, row, exc)
                except MediaProviderError as exc:
                    if not _passing(exc):
                        raise
                    # A passing network error after the client's own retries: the item stays
                    # pending and is read again on the next poll (the round's deadline bounds it).
                    logger.warning(
                        "runpod_batch_poll_retry",
                        extra={"http_status": exc.http_status, "job": chunk.remote_id},
                    )
                    break
                outcomes.append(outcome)
            if chunk.remote_id and chunk.remote_id in statuses:
                status = statuses[chunk.remote_id]
                if status is not None:
                    chunk.status = status
                    chunk.finished = str(status.get("status")) in _FINAL_RUN_STATES
                    finished = finished or chunk.finished
        if finished:
            self._book()
        return outcomes

    def _note_queue(self) -> None:
        """A job still IN_QUEUE has no worker yet: on a cache miss RunPod is downloading the
        model, unbilled. The GPU switch says so (`weights.model_wait`)."""
        endpoint = self.config.endpoint_for(self._operation())
        if not endpoint:
            return
        queued = [
            c.sent_at
            for c in self.chunks
            if c.remote_id
            and not c.finished
            and str((c.status or {}).get("status")) == "IN_QUEUE"
            and any(item.job_row_id not in self._reported for item in c.items)
        ]
        if queued:
            weights.note_queue(
                endpoint, since=min(queued), notice_seconds=self.config.model_wait_notice_seconds
            )
        else:
            weights.clear_queue(endpoint)

    # ------------------------------------------------------------------------ mock run

    def _poll_mock(self) -> list[ItemOutcome]:
        """The offline transport: no GPU, deterministic synthetic files, 0 credits."""
        from app.providers.runpod.mock import png, video  # noqa: PLC0415

        outcomes: list[ItemOutcome] = []
        for item in self.items:
            if item.job_row_id in self._reported:
                continue
            row = self.store.read(item.job_row_id)
            if row.status in TERMINAL:
                outcomes.append(_outcome_of(item, row))
                continue
            if row.poll_count == 0:
                self.store.update(row.id, status="RUNNING", poll_count=1, started_at=now())
                outcomes.append(ItemOutcome(item, "PENDING", None, None, None, None))
                continue
            if item.request.operation == "image":
                content, mime, ext = (
                    png(variation=int(row.idempotency_key[:8], 16)),
                    "image/png",
                    "png",
                )
            else:
                content = video(float(item.request.duration or 5), int(item.request.fps or 24))
                mime, ext = "video/mp4", "mp4"
            path = _write_asset(self.storage_root, row.id, ext, content)
            self.store.update(
                row.id,
                status="COMPLETED",
                finished_at=now(),
                gpu_seconds_value="0",
                cost_value="0",
                billed_seconds_value="0",
                output={"mime": mime, "sha256": hashlib.sha256(content).hexdigest()},
                asset_path=str(path),
                asset_sha256=hashlib.sha256(content).hexdigest(),
            )
            outcomes.append(ItemOutcome(item, "COMPLETED", path, mime, 0.0, None))
        return outcomes


_FINAL_RUN_STATES = ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT")
#: The code of an item whose result could not be taken (checksum, manifest, key echo).
BAD_OUTPUT = "BAD_OUTPUT"


def _has_times(status: dict[str, Any] | None) -> bool:
    status = status or {}
    return all(
        isinstance(status.get(k), int | float) and not isinstance(status.get(k), bool)
        for k in ("delayTime", "executionTime")
    )


def billed_seconds(
    config: RunPodConfig,
    status: dict[str, Any] | None,
    *,
    previous: dict[str, Any] | None = None,
    unseen: Decimal | None = Decimal(0),
) -> Decimal | None:
    """What RunPod bills for one job of a round, from its /status times (seconds), or None
    until the job reported them.

    RunPod bills a worker from when it starts running until it fully stops: its start (mostly
    the models loading), the execution and the idle timeout; «Pulling the container image and
    downloading cached models happen before the worker starts running and are not billed»
    (https://docs.runpod.io/serverless/pricing; «You aren't billed for worker time while the
    model downloads», https://docs.runpod.io/serverless/endpoints/model-caching). /status gives
    ``executionTime`` and ``delayTime``, the whole time from the /run to a worker taking the
    job: the queue while no worker ran, the image pull and the cached model's download (none of
    it billed) and the worker's own start (billed). The two cannot be told apart from /status,
    so a job books its execution and, of its wait:

    * the round's first job (``previous`` None, or its times unknown): at most
      ``cold_start_seconds`` (the start the plan priced each round with) + the idle tail
      (``idle_timeout_seconds``, counted once per worker);
    * a later chunk of the same round (``previous``: the /status of the accepted job sent just
      before it, to the same worker, workers.max=1): only the part of its wait that job's own
      wait and run do not explain, ``delayTime - (previous delayTime + executionTime)``, at most
      one worker start + one idle tail. Normally nothing: it waited for the worker to finish
      the job before it, whose execution is counted there. More when that worker stopped in
      between (a job past its executionTimeout «fails and the worker stops»; a crash): the
      next one paid a new start;
    * ``unseen``: the run budget (``policy.executionTimeout``) of the jobs sent between them
      whose /run got no answer. RunPod may have run such a job on the worker before this one;
      its run is then inside this job's wait and is counted, up to that budget, on top of the
      start (None: a budget unknown, the whole wait counts).

    So a round books its jobs' execution + one start and one idle tail per worker that ran it,
    never the queue wait while no worker ran or the model downloaded.

    2026-10-09, «The Particle That Shouldn't Exist (But Does)»: the job waited 28 minutes for the
    model's download ($0.00000/s on RunPod's console) and the worker ran about 340 s; RunPod
    charged 0.27 USD for the session, while (delayTime + executionTime) + idle per job booked
    about 2,074 s, 2.3 USD of the step's 2.94 USD cap at the 4.00 USD/h budget rate."""
    if not _has_times(status):
        return None
    times = status or {}
    execution = max(Decimal(0), Decimal(str(times["executionTime"])) / 1000)
    wait = max(Decimal(0), Decimal(str(times["delayTime"])) / 1000)
    start = Decimal(config.cold_start_seconds)
    idle = Decimal(config.idle_timeout_seconds)
    if previous is None or not _has_times(previous):
        ceiling = None if unseen is None else start + unseen
        return execution + (wait if ceiling is None else min(wait, ceiling)) + idle
    before = Decimal(str(previous["delayTime"])) / 1000
    before += max(Decimal(0), Decimal(str(previous["executionTime"])) / 1000)
    extra = wait - before
    if extra <= 0:
        return execution
    ceiling = None if unseen is None else start + idle + unseen
    return execution + (extra if ceiling is None else min(extra, ceiling))


def _passing(exc: MediaProviderError) -> bool:
    """A read that may succeed if simply asked again (no answer, throttled, a server error)."""
    status = exc.http_status
    return bool(
        exc.unsent or exc.unanswered or status is None or status in (408, 425, 429) or status >= 500
    )


def _bad_output(
    engine: Engine, item: SubmittedItem, row: GenerationJob, exc: Exception
) -> ItemOutcome:
    """The item was made (its GPU time is paid) but its result cannot be taken."""
    logger.warning(
        "runpod_batch_bad_output", extra={"job": row.remote_job_id, "error": str(exc)[:200]}
    )
    JobStore(engine).update(row.id, status="FAILED", error_code=BAD_OUTPUT, finished_at=now())
    return ItemOutcome(item, "FAILED", None, None, None, BAD_OUTPUT)


def _outcome_of(item: SubmittedItem, row: GenerationJob) -> ItemOutcome:
    """The outcome a terminal journal row stands for."""
    if row.status == "COMPLETED":
        mime = (row.output or {}).get("mime")
        path = Path(row.asset_path) if row.asset_path else None
        return ItemOutcome(item, "COMPLETED", path, mime, row.gpu_seconds, None)
    state: OutcomeState = "CANCELLED" if row.status == "CANCELLED" else "FAILED"
    return ItemOutcome(item, state, None, None, row.gpu_seconds, row.error_code or row.status)


def _write_asset(storage_root: Path, row_id: str, ext: str, content: bytes) -> Path:
    root = Path(storage_root).resolve()
    directory = root / "runpod"
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root):
        raise RunPodProtocolError("RunPod output folder escapes the media root")
    target = directory / f"{row_id}.{ext}"
    temporary = target.with_suffix(target.suffix + ".part")
    if target.is_symlink() or temporary.is_symlink():
        raise RunPodProtocolError("RunPod output destination is a link")
    temporary.write_bytes(content)
    temporary.replace(target)
    return target


def _book_batch(engine: Engine, chunk: _Chunk, billed: Decimal) -> None:
    """The job's billed seconds (`billed_seconds`), apportioned to its items by their GPU
    seconds: a worker's start and idle tail ride on the job that started that worker."""
    with Session(engine) as s, s.begin():
        lock_for_write(s)
        rows = [s.get(GenerationJob, item.job_row_id) for item in chunk.items]
        present = [row for row in rows if row is not None]
        seconds = [_decimal(row.gpu_seconds_value) or Decimal(0) for row in present]
        total = sum(seconds, Decimal(0))
        for row, own in zip(present, seconds, strict=True):
            share = billed * own / total if total > 0 else billed / max(1, len(present))
            row.billed_seconds_value = str(share.quantize(Decimal("0.001")))


async def collect_row(
    config: RunPodConfig,
    engine: Engine,
    row: GenerationJob,
    item: SubmittedItem | None,
    *,
    client: RunPodClient,
    bucket: BucketConfig | None,
    storage_root: Path,
    transport: Transport | None,
    statuses: dict[str, dict[str, Any] | None] | None = None,
    problems: list[weights.WeightsProblem] | None = None,
) -> ItemOutcome:
    """One batch item collected: the bucket manifest first, then GET /status of its job.

    Also the watchdog's path after a restart (``item`` None: an outcome is still built).
    What a result says about the endpoint's weights (``weights_revision``, MODELS_MISSING) is
    added to ``problems`` (`weights.check_result`): the round's caller stops the step."""
    store = JobStore(engine)
    statuses = statuses if statuses is not None else {}
    purpose: Literal["image", "video"] = "video" if row.operation == "video" else "image"

    def check(raw: Any, error: Any = None) -> str | None:
        """Record a weights problem; return the revision the result reported."""
        mapping = raw if isinstance(raw, dict) else None
        problem = weights.check_result(config, purpose, mapping, error=error)
        if problem is not None and problems is not None and problem not in problems:
            problems.append(problem)
        return weights.reported_revision(mapping)

    holder = item or SubmittedItem(
        request=_request_of(row),
        job_row_id=row.id,
        idempotency_key=row.idempotency_key,
        remote_item_id=row.remote_job_id,
    )
    prefix = bucket.prefix if bucket else config.s3_prefix
    if bucket is not None:
        manifest = await s3.get_json(
            bucket, contract.manifest_key(prefix, row.idempotency_key), transport or _default()
        )
        if manifest is not None:
            revision = check(manifest)
            result = contract.validate_item_result(manifest, "manifest")
            if result["status"] == "COMPLETED":
                return await _land(
                    config, engine, row, holder, result, bucket, storage_root, client, revision
                )
    batch = row.batch_remote_id
    if not batch:
        return ItemOutcome(holder, "PENDING", None, None, None, None)
    if batch not in statuses:
        try:
            statuses[batch] = await client.call("GET", "/status/" + quote(batch, safe=""))
        except MediaProviderError as exc:
            if exc.http_status == 404 and not exc.unanswered:
                statuses[batch] = None  # RunPod forgot the job (30 min): only the bucket remains
            else:
                raise
    status = statuses[batch]
    if status is None:
        store.update(row.id, status="FAILED", error_code=EXPIRED, finished_at=now(), cost_value="0")
        return ItemOutcome(holder, "FAILED", None, None, None, EXPIRED)
    state = str(status.get("status"))
    if state in RUN_STATES:
        mapped = RUN_STATES[state]
        if row.status != mapped:
            store.update(
                row.id,
                status=mapped,
                started_at=row.started_at or (now() if mapped == "RUNNING" else None),
                poll_count=row.poll_count + 1,
            )
        return ItemOutcome(holder, "PENDING", None, None, None, None)
    if state == "COMPLETED":
        raw_output = status.get("output")
        job_revision = check(raw_output)
        raw_items = raw_output.get("items") if isinstance(raw_output, dict) else None
        raw_mine = next(
            (
                it
                for it in (raw_items if isinstance(raw_items, list) else [])
                if isinstance(it, dict) and it.get("index") == row.batch_index
            ),
            None,
        )
        revision = check(raw_mine) or job_revision
        output = contract.validate_output(raw_output)
        mine = next((it for it in output["items"] if it["index"] == row.batch_index), None)
        if mine is None:
            # The job ended without this item (the time guard skipped it before it started).
            store.update(
                row.id,
                status="FAILED",
                error_code="SKIPPED_TIME",
                finished_at=now(),
                cost_value="0",
                gpu_seconds_value="0",
            )
            return ItemOutcome(holder, "FAILED", None, None, 0.0, "SKIPPED_TIME")
        if mine["idempotency_key"] != row.idempotency_key:
            raise RunPodProtocolError("RunPod output does not echo the item's idempotency key")
        if mine["status"] == "COMPLETED":
            return await _land(
                config, engine, row, holder, mine, bucket, storage_root, client, revision
            )
        code = str(mine.get("error") or mine["status"])[:100]
        seconds = float(mine.get("gpu_seconds") or 0.0)
        store.update(
            row.id,
            status="FAILED",
            error_code=code,
            finished_at=now(),
            gpu_seconds_value=str(seconds),
            cost_value=str(Decimal(str(seconds)) * Decimal(row.hourly_rate) / 3600),
        )
        return ItemOutcome(holder, "FAILED", None, None, seconds, code)
    if state in ("FAILED", "CANCELLED", "TIMED_OUT"):
        check(status, status.get("error"))
        journal = {"FAILED": "FAILED", "CANCELLED": "CANCELLED", "TIMED_OUT": "TIMEOUT"}[state]
        store.update(row.id, status=journal, error_code=state, finished_at=now())
        outcome_state: OutcomeState = "CANCELLED" if state == "CANCELLED" else "FAILED"
        return ItemOutcome(holder, outcome_state, None, None, None, state)
    raise RunPodProtocolError("RunPod returned an unknown job state")


def _default() -> Transport:
    from app.providers.media_http import request  # noqa: PLC0415

    return request


def _request_of(row: GenerationJob) -> BatchRequest:
    """A stand-in request for a row collected without its round (the watchdog)."""
    data = dict(row.request or {})
    return BatchRequest(
        operation="video" if row.operation == "video" else "image",
        project_id=row.project_id,
        scene_id=row.scene_id,
        candidate_index=int(data.get("candidate_index") or 0),
        attempt_number=row.attempt,
        model=row.model,
        prompt=str(data.get("prompt") or ""),
        negative_prompt=data.get("negative_prompt"),
        seed=int(data.get("seed") or 0),
        width=int(data.get("width") or 0),
        height=int(data.get("height") or 0),
        duration=data.get("duration"),
        fps=data.get("fps"),
        references=(),
        source_image=None,
        price_usd=Decimal(0),
    )


async def _land(
    config: RunPodConfig,
    engine: Engine,
    row: GenerationJob,
    item: SubmittedItem,
    result: contract.ItemResult,
    bucket: BucketConfig | None,
    storage_root: Path,
    client: RunPodClient,
    revision: str | None = None,
) -> ItemOutcome:
    """Download a finished item (its URL, else a fresh studio-signed GET), check its sha256
    and keep it under the media root; the journal row becomes COMPLETED with its cost."""
    if result["idempotency_key"] != row.idempotency_key:
        raise RunPodProtocolError("RunPod output does not echo the item's idempotency key")
    fields = cast(dict[str, Any], result)
    content: bytes | None = None
    url = fields.get("url")
    if url:
        try:
            content, _kind = await client.download(str(url))
        except MediaProviderError:
            content = None  # an expired URL: the studio signs a fresh one below
    if content is None:
        if bucket is None:
            raise RunPodProtocolError("RunPod output needs the bucket to be downloaded")
        content, _kind = await client.download(s3.presign(bucket, "GET", result["key"], 900))
    if hashlib.sha256(content).hexdigest() != result["sha256"]:
        raise RunPodProtocolError("RunPod result checksum does not match")
    mime = result["mime"]
    if mime == "video/mp4" and b"ftyp" not in content[:32]:
        raise RunPodProtocolError("RunPod result is not an MP4 file")
    path = _write_asset(storage_root, row.id, "png" if mime == "image/png" else "mp4", content)
    seconds = Decimal(str(fields.get("gpu_seconds") or 0))
    JobStore(engine).update(
        row.id,
        status="COMPLETED",
        finished_at=now(),
        started_at=row.started_at or now(),
        gpu_seconds_value=str(seconds),
        cost_value=str(Decimal(0) if config.mock else seconds * Decimal(row.hourly_rate) / 3600),
        # Never the presigned URL: a signed address is a credential for 7 days.
        output={
            k: fields.get(k)
            for k in (
                "key",
                "sha256",
                "bytes",
                "mime",
                "width",
                "height",
                "duration",
                "fps",
                "model",
                "seed",
                "gpu_seconds",
                "reused",
                "provenance_boxes",
            )
        }
        # The mirror commit the worker's snapshot resolved to (the bake-off reads it too).
        | {"weights_revision": revision},
        asset_path=str(path),
        asset_sha256=result["sha256"],
    )
    return ItemOutcome(item, "COMPLETED", path, mime, float(seconds), None)


# --------------------------------------------------------------------------- submission


async def _upload(
    bucket: BucketConfig, content: bytes, transport: Transport, cache: dict[str, contract.InputRef]
) -> contract.InputRef:
    sha = hashlib.sha256(content).hexdigest()
    if sha in cache:
        return cache[sha]
    mime, ext = picture_kind(content)
    key = contract.input_key(bucket.prefix, sha, ext)
    await s3.put_bytes(bucket, key, content, mime, transport)
    ref: contract.InputRef = {
        "url": s3.presign(bucket, "GET", key, INPUT_URL_TTL),
        "sha256": sha,
        "mime": mime,
    }
    cache[sha] = ref
    return ref


def submit_round(
    config: RunPodConfig,
    engine: Engine,
    requests: Sequence[BatchRequest],
    *,
    integration_id: str | None,
    storage_root: Path,
    session: GpuSession,
    on_submitted: Callable[[SubmittedItem], None],
    transport: Transport | None = None,
    should_stop: Callable[[], str | None] | None = None,
) -> BatchRun:
    """Reserve every item, upload the pictures, POST the round's chunks back-to-back, save
    each job id on its items and call ``on_submitted`` per item; no poll here.

    Raises `BatchRefused` when nothing of the round left (nothing queued, nothing bought).
    ``should_stop`` (else `STEP_STOP`) is the step's stop: words when no /run may leave now."""
    if not requests:
        raise ValueError("an empty round is not submitted")
    operations = {r.operation for r in requests}
    if len(operations) != 1:
        raise ValueError("one round is one operation (image or video)")
    operation = requests[0].operation
    requests = [route_references(request) for request in requests]
    if not config.ready_for_generation:
        raise BatchRefused(
            "NOT_CONFIGURED",
            "RunPod nu are bucketul de rezultate configurat; nu se pornește GPU-ul și nu se "
            "trimite nimic.",
        )
    for request in requests:
        workflow = contract.WORKFLOWS.get(request.model)
        if not config.mock and (workflow is None or workflow[0] != operation):
            raise BatchRefused(
                "UNKNOWN_MODEL",
                f"Modelul {request.model} nu este în lucrătorul RunPod al studioului.",
            )
    store = JobStore(engine)
    run = BatchRun(
        config=config,
        engine=engine,
        integration_id=integration_id,
        storage_root=storage_root,
        transport=transport,
        session_id=getattr(session, "id", None),
    )
    to_send: list[tuple[SubmittedItem, GenerationJob]] = []
    for request in requests:
        try:
            row, action, effective = reserve_item(store, config, integration_id, request)
        except IdempotencyConflict as exc:
            # Before any upload or /run: this round bought nothing (the open purchase under
            # that key was booked by its own step), so it refuses unsent, never «paid».
            said = (
                f"Scena {request.scene_id} are deja o cumpărare deschisă cu alt conținut sub "
                "aceeași cheie."
            )
            raise BatchRefused(
                "IDEMPOTENCY_CONFLICT",
                f"{said} {_NOTHING_SENT_RO}",
                after_purchase_ro=f"{said} {REST_NOT_SENT_RO}",
            ) from exc
        except SQLAlchemyError as exc:
            # Review 2026-10-10: a «database is locked» (REL-01) while reserving went up raw
            # with the round already on the step's meter, and the sheet booked as a purchase a
            # round that never left the studio. Before any upload or /run: refused unsent.
            logger.warning(
                "runpod_reserve_unwritable",
                extra={"scene_id": request.scene_id, "error_class": type(exc).__name__},
            )
            raise BatchRefused(
                JOURNAL_UNWRITABLE,
                f"{JOURNAL_UNWRITABLE_RO} {_NOTHING_SENT_RO}",
                after_purchase_ro=f"{JOURNAL_UNWRITABLE_RO} {REST_NOT_SENT_RO}",
            ) from exc
        item = SubmittedItem(effective, row.id, row.idempotency_key, row.remote_job_id)
        run.items.append(item)
        if action == "TRACK":
            run.chunks.append(_Chunk(row.batch_remote_id, [item], {}, time.monotonic()))
            continue
        to_send.append((item, row))
    if not to_send:
        return run
    if config.mock:
        _submit_mock(run, to_send, session, on_submitted)
        return run
    stop = should_stop if should_stop is not None else STEP_STOP.get()
    asyncio.run(_submit_remote(run, to_send, session, on_submitted, operation, stop))
    return run


#: RunPod's /run answers 409 «Endpoint is paused (max_workers=0)» for a while after the
#: switch-on PATCH was applied: live 2026-10-09 the queue saw it after ~3 s (stills), ~15 s
#: (test shot) and more than 30 s (motion). A 409 is a refusal, nothing queued and no worker
#: running, so the same body goes again after each wait: these first, then every
#: `PAUSED_EVERY_SECONDS`, until ``RunPodConfig.paused_wait_seconds`` (180 s) is spent.
PAUSED_RETRY_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 15.0)
PAUSED_EVERY_SECONDS = 30.0
#: The paused wait's clock and sleep: module attributes, so a test runs the time budget on a
#: fake clock instead of waiting for it.
paused_clock: Callable[[], float] = time.monotonic
paused_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
#: The event of each paused wait, cleared or not (aggregate: the GPU session): how long
#: RunPod really took to see the switch-on, the figure ``paused_wait_seconds`` is tuned from
#: (2026-10-09: it was read off studio.log timestamps by hand).
PAUSE_EVENT = "runpod.run_paused"

#: The Owner's words for a /run RunPod refused whole, by its status (RunPod's own follow).
_REFUSED_RO = {
    400: "RunPod a refuzat cererea: nu are forma pe care o acceptă",
    401: "RunPod nu a acceptat cheia studioului",
    403: "cheia RunPod nu are acces la acest endpoint",
    404: "RunPod nu găsește endpointul",
    413: "cererea este prea mare pentru RunPod",
    422: "RunPod nu acceptă conținutul cererii",
    429: "RunPod primește prea multe cereri acum",
}
#: What every refusal of this kind adds: nothing was bought, the step may run again.
_NOTHING_BOUGHT_RO = (
    "RunPod nu a pus lucrarea la coadă, deci nu s-a cumpărat nimic; pasul se poate porni din nou."
)
#: The same refusal once the step had already bought an earlier round or chunk: what was
#: bought stays (review 2026-10-09: «nu s-a cumpărat nimic» sat in his letter next to the
#: credits booked for that stair).
REST_NOT_QUEUED_RO = (
    "RunPod nu a pus la coadă restul pasului, deci restul nu s-a cumpărat; ce s-a cumpărat "
    "înainte rămâne."
)
#: The same pair for a round the studio itself never sent.
_NOTHING_SENT_RO = "Nu s-a trimis și nu s-a cumpărat nimic; pasul se poate porni din nou."
REST_NOT_SENT_RO = (
    "Restul pasului nu s-a trimis la RunPod și nu s-a cumpărat; ce s-a cumpărat înainte rămâne."
)
#: The paused wait could not read the session or the step's stop (`_wait_ended`).
WAIT_UNREADABLE = "WAIT_UNREADABLE"
WAIT_UNREADABLE_RO = (
    "Starea pasului nu a putut fi citită (baza de date a studioului nu a răspuns la timp), "
    "așa că nu s-a mai trimis nicio cerere."
)


def _wait_ended(
    session: Any, should_stop: Callable[[], str | None] | None, *, renew: bool
) -> tuple[str, str] | None:
    """(code, words) when no /run may leave now: the step's GPU session was switched off
    from outside (`GpuForcedOff`: his «Oprește GPU acum», the guard, a shutdown) or the step
    was stopped (``should_stop``), or either could not be read (`WAIT_UNREADABLE`); else None.
    ``renew`` keeps the session alive while the studio waits on RunPod (2026-10-09 audit: the
    paused wait only checked it, and the guard could take a step waiting ~3 minutes for a dead
    one). It never raises: the round is on the step's meter while it runs."""
    from app.providers.runpod.gpu_session import GpuForcedOff  # noqa: PLC0415 - import cycle

    keep = getattr(session, "renew", None) if renew else None
    if not callable(keep):
        keep = getattr(session, "check", None)
    try:
        if callable(keep):
            keep()
        reason = should_stop() if should_stop is not None else None
    except GpuForcedOff as exc:
        return "GPU_FORCED_OFF", str(exc.reason_ro)
    except Exception as exc:  # noqa: BLE001 - an unread stop ends the wait, never books it
        # Review 2026-10-09: the renewal and the step's stop (the guard writes its record) take
        # the write lock while the round sits on the meter; a «database is locked» (REL-01,
        # busy_timeout 30 s) went up raw past every layer that refuses unsent, and the sheet
        # booked a round RunPod never queued. Nothing more leaves: what was answered «paused»
        # is refused unsent, in RunPod's words.
        logger.warning(
            "runpod_wait_unreadable",
            extra={"error_class": type(exc).__name__, "renew": renew},
        )
        return WAIT_UNREADABLE, WAIT_UNREADABLE_RO
    if reason:
        return "STOPPED", str(reason)
    return None


def _runpod_words(failure: MediaProviderError) -> str:
    """RunPod's own answer, already sanitised by media_http, as the Owner reads it."""
    detail = " ".join(str(failure.detail or "").split())[:300]
    if not detail:
        return ""
    status = f" (HTTP {failure.http_status})" if failure.http_status else ""
    return f" Răspunsul RunPod{status}: «{detail}»."


def _refusal(
    failure: MediaProviderError, ended: tuple[str, str] | None, waited: float
) -> BatchRefused:
    """The refusal of a /run RunPod queued nothing of (`refused_unqueued`), in the Owner's
    words with RunPod's own (2026-10-09: a failed /run said only «refused, reason unknown»;
    RunPod's answer reached studio.log alone)."""
    words = _runpod_words(failure)
    status = failure.http_status if not failure.unsent else None
    if ended is not None:
        code, said = ended
        if code == "RUNPOD_PAUSED":
            said = (
                "RunPod a răspuns că endpointul este în pauză (0 workeri permiși) la fiecare "
                f"cerere, timp de {round(waited)} s după pornirea GPU-ului."
            )
        else:
            said = f"{said} RunPod încă răspundea că endpointul este în pauză."
        reason = f"{said} {_NOTHING_BOUGHT_RO}{words}"
    elif failure.unsent:
        code = "RUNPOD_UNSENT"
        said = "Cererea nu a putut pleca spre RunPod (conexiunea nu s-a deschis)."
        reason = (
            "Cererea nu a putut pleca spre RunPod (conexiunea nu s-a deschis); nu s-a trimis "
            "și nu s-a cumpărat nimic; pasul se poate porni din nou."
        )
    else:
        code = f"RUNPOD_HTTP_{status}"
        said = f"{_REFUSED_RO.get(int(status or 0), 'RunPod a refuzat cererea')} (HTTP {status})."
        reason = f"{said} {_NOTHING_BOUGHT_RO}{words}"
    return BatchRefused(
        code,
        reason,
        http_status=status,
        detail=failure.detail,
        after_purchase_ro=f"{said} {REST_NOT_QUEUED_RO}{words}",
    )


def _save_job(
    engine: Engine,
    rows: list[tuple[SubmittedItem, GenerationJob]],
    job: str,
    session_id: str | None,
    gpu: GpuSession | None = None,
) -> None:
    """The job id on every item row of the chunk and on the GPU session, in one transaction,
    before anything else (the session's close cancels what it noted)."""
    with Session(engine) as s, s.begin():
        lock_for_write(s)
        if gpu is not None:
            gpu.note_job(job, session=s)
        for index, (item, row) in enumerate(rows):
            saved = s.get(GenerationJob, row.id)
            if saved is None:
                continue
            saved.remote_job_id = f"{job}:{index}"
            saved.batch_remote_id = job
            saved.batch_index = index
            saved.gpu_session_id = session_id
            saved.status = "QUEUED"
            saved.error_code = None
            item.remote_item_id = saved.remote_job_id


def _submit_mock(
    run: BatchRun,
    to_send: list[tuple[SubmittedItem, GenerationJob]],
    session: GpuSession,
    on_submitted: Callable[[SubmittedItem], None],
) -> None:
    job = "mock-batch-" + contract.batch_key(item.idempotency_key for item, _ in to_send)[:24]
    _save_job(run.engine, to_send, job, run.session_id, session)
    run.remote_job_ids.append(job)
    run.chunks.append(_Chunk(job, [item for item, _ in to_send], {}, time.monotonic()))
    for item, _row in to_send:
        on_submitted(item)


@dataclass
class _Posted:
    """What one chunk's /run came to (`_post_run`)."""

    job: str | None = None
    #: The last failure, when RunPod gave no job id.
    failure: MediaProviderError | None = None
    #: (code, words) when the wait for a paused endpoint ended without a job: its time budget
    #: spent (RUNPOD_PAUSED), the GPU switched off (GPU_FORCED_OFF), the step stopped (STOPPED).
    ended: tuple[str, str] | None = None
    #: Seconds from the first /run to the last answer (0 when RunPod answered at once).
    waited: float = 0.0
    #: The paused wait's record for `PAUSE_EVENT` (None when RunPod never answered «paused»),
    #: written by `_note_pause` only once the chunk's job id, if any, is saved.
    pause: dict[str, Any] | None = None


async def _post_run(
    run: BatchRun,
    client: RunPodClient,
    body: dict[str, Any],
    key: str,
    *,
    session: Any,
    should_stop: Callable[[], str | None] | None,
    endpoint: str | None,
    items: int,
) -> _Posted:
    """POST the chunk's /run; while RunPod answers «paused», the same body again after each
    wait, inside ``paused_wait_seconds`` on a monotonic clock. Before each wait and before each
    /run sent again the session is renewed and the step's stop read, so a press of his «Oprește
    GPU acum» or STOP AUTONOMIE sends no further /run (2026-10-09 audit)."""
    started = paused_clock()
    budget = float(run.config.paused_wait_seconds)
    schedule = iter(PAUSED_RETRY_SECONDS)
    paused = 0
    posted = _Posted()
    while True:
        try:
            data = await client.call("POST", "/run", body, key=key)
            job = data.get("id")
            if not isinstance(job, str) or not job or len(job) > 90:
                raise RunPodProtocolError("RunPod did not return a valid job id")
            posted.job, posted.failure = job, None
            break
        except MediaProviderError as refusal:
            posted.failure = refusal
            if not endpoint_paused(refusal):
                break
            paused += 1
            posted.waited = paused_clock() - started
            left = budget - posted.waited
            if left <= 0:
                posted.ended = ("RUNPOD_PAUSED", "")
                break
            # A refusal, nothing queued: the same body again once the switch-on reached
            # RunPod's queue. No worker runs meanwhile, so the wait costs nothing.
            posted.ended = _wait_ended(session, should_stop, renew=True)
            if posted.ended is not None:
                break
            wait = min(next(schedule, PAUSED_EVERY_SECONDS), left)
            logger.info(
                "runpod_run_paused_retry",
                extra={"endpoint_id": endpoint, "items": items, "wait_seconds": wait},
            )
            await paused_sleep(wait)
            posted.ended = _wait_ended(session, should_stop, renew=True)
            if posted.ended is not None:
                posted.waited = paused_clock() - started
                break
    if paused:
        posted.waited = paused_clock() - started
        cleared = posted.job is not None
        record = {
            "endpoint_id": endpoint,
            "items": items,
            "cleared": cleared,
            "seconds": round(posted.waited, 3),
            "paused_answers": paused,
            "ended": posted.ended[0] if posted.ended else None,
            "budget_seconds": budget,
        }
        logger.log(
            logging.INFO if cleared else logging.WARNING,
            "runpod_run_paused_cleared" if cleared else "runpod_run_paused_refused",
            extra=record,
        )
        posted.pause = record
    return posted


def _note_pause(run: BatchRun, posted: _Posted) -> None:
    """The paused wait's event on the GPU session. Called AFTER `_save_job` for a /run RunPod
    took (review 2026-10-09: written before it, a write that may wait out the 30 s busy timeout
    held an accepted, billing job id in memory alone, so a «Oprește GPU acum» meanwhile could
    not cancel it by id). `_write_event` never raises."""
    if posted.pause is None or not run.session_id:
        return
    from app.providers.runpod.gpu_session import _write_event  # noqa: PLC0415 - cycle

    _write_event(run.engine, PAUSE_EVENT, run.session_id, posted.pause, run.session_id)


#: The studio's own journal could not reserve a row before anything was sent (`submit_round`).
JOURNAL_UNWRITABLE = "JOURNAL_UNWRITABLE"
JOURNAL_UNWRITABLE_RO = (
    "Jurnalul cumpărăturilor RunPod nu a putut fi scris (baza de date a studioului nu a "
    "răspuns la timp), așa că nu s-a trimis nicio cerere."
)


def _journal_failed(what: str, exc: BaseException) -> None:
    """A journal write of a refusal already proven to have queued nothing could not be made:
    logged, never raised (review 2026-10-10). The «database is locked» that ends a paused wait
    (`_wait_ended`, REL-01) can outlive it and reach these writes; raised raw (not a
    MediaProviderError) it left the round on the step's meter and the sheet booked a round
    RunPod never queued, with the «a plătit» letter. A row left unwritten is safe: it holds no
    job id, so `reserve_item` sends it again under the SAME key (RESEND), and nothing of it was
    queued (RunPod refused it, or it never left), so there is nothing to collect or book."""
    logger.warning(
        "runpod_refusal_journal_failed",
        extra={"what": what, "error_class": type(exc).__name__},
    )


def _journal_answer(
    store: JobStore,
    pairs: Sequence[tuple[SubmittedItem, GenerationJob]],
    failure: MediaProviderError,
    answer: dict[str, Any],
    *,
    proven: bool,
    session_id: str | None,
) -> None:
    """RunPod's answer on every row of a chunk whose /run gave no job id (2026-10-09: it
    reached studio.log only), so the sheet, the takes and the watchdog can read why without
    the log. A proven refusal's writes are best effort (`_journal_failed`); an uncertain one's
    are not: a /run RunPod may have queued stays on the step's meter if its mark fails."""
    try:
        for _item, row in pairs:
            output = {**dict(store.read(row.id).output or {}), "run_refusal": answer}
            if proven:
                store.update(
                    row.id,
                    status="FAILED",
                    finished_at=now(),
                    error_code=UNSENT if failure.unsent else f"HTTP_{failure.http_status}",
                    cost_value="0",
                    gpu_seconds_value="0",
                    output=output,
                )
            else:
                # The session is named on the row (2026-10-09): what its close reads about
                # RunPod's queue is the evidence for these items (`BatchRun.prove_unsent`).
                store.update(
                    row.id,
                    error_code=UNCERTAIN,
                    gpu_session_id=session_id,
                    output=output,
                )
    except Exception as exc:  # noqa: BLE001 - a proven refusal is never turned into a purchase
        if not proven:
            raise
        _journal_failed("run_refused", exc)


def _unsent_rest(
    run: BatchRun,
    store: JobStore,
    left: Sequence[tuple[SubmittedItem, GenerationJob]],
    refusal: BatchRefused,
) -> None:
    """The round stops sending: ``left`` never left the studio and costs nothing (FAILED
    UNSENT, its keys reusable). The round goes on with what was sent; `BatchRun.refused`
    tells the step to send no further round. The journal writes are best effort
    (`_journal_failed`): the refusal and the round's own account never depend on them."""
    try:
        for _item, row in left:
            store.update(
                row.id,
                status="FAILED",
                finished_at=now(),
                error_code=UNSENT,
                cost_value="0",
                gpu_seconds_value="0",
            )
    except Exception as exc:  # noqa: BLE001 - never sent: never turned into a purchase
        _journal_failed("unsent_rest", exc)
    run.refused = refusal
    if not left:
        return
    run.chunks.append(_Chunk(None, [item for item, _ in left], {}, time.monotonic()))
    for item, _row in left:
        run._pending_report.append(ItemOutcome(item, "FAILED", None, None, None, UNSENT))


async def _submit_remote(
    run: BatchRun,
    to_send: list[tuple[SubmittedItem, GenerationJob]],
    session: GpuSession,
    on_submitted: Callable[[SubmittedItem], None],
    operation: Literal["image", "video"],
    should_stop: Callable[[], str | None] | None = None,
) -> None:
    config = run.config
    bucket = config.bucket()
    if bucket is None:  # ready_for_generation checked it; kept for the type checker
        raise BatchRefused("NOT_CONFIGURED", "RunPod nu are bucketul de rezultate configurat.")
    transport = run.transport or _default()
    store = JobStore(run.engine)
    cache: dict[str, contract.InputRef] = {}
    built: list[contract.BatchItem] = []
    try:
        for item, row in to_send:
            request = item.request
            refs = [await _upload(bucket, b, transport, cache) for b in request.references]
            entry: dict[str, Any] = {
                "idempotency_key": row.idempotency_key,
                "model": request.model,
                "workflow": contract.WORKFLOWS[request.model][1],
                "project_id": request.project_id,
                "scene_id": request.scene_id,
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "seed": request.seed,
                "reference_images": refs,
            }
            if operation == "image":
                entry["width"], entry["height"] = contract.STILL_SIZE
            else:
                if request.source_image is None:
                    raise BatchRefused("NO_FIRST_FRAME", "Cadrul nu are imaginea de pornire.")
                entry["source_image"] = await _upload(
                    bucket, request.source_image, transport, cache
                )
                entry["duration"] = float(request.duration or 5)
                entry["fps"] = contract.CLIP_FPS
            built.append(cast(contract.BatchItem, entry))
    except MediaProviderError as exc:
        # Nothing was sent to RunPod: the rows stay reusable under their keys (best effort,
        # `_journal_failed`: a row left reserved is sent again under the same key).
        try:
            for _item, row in to_send:
                store.update(
                    row.id,
                    status="FAILED",
                    error_code=UNSENT,
                    finished_at=now(),
                    cost_value="0",
                    gpu_seconds_value="0",
                )
        except Exception as journal_exc:  # noqa: BLE001 - never sent: never a purchase
            _journal_failed("upload_refused", journal_exc)
        if isinstance(exc, BatchRefused):
            raise
        raise BatchRefused(
            "INPUT_UPLOAD_FAILED",
            "Imaginile de pornire nu au putut fi urcate în bucket; nu s-a trimis nimic la RunPod.",
            after_purchase_ro=(
                f"Imaginile de pornire nu au putut fi urcate în bucket. {REST_NOT_SENT_RO}"
            ),
        ) from exc
    endpoint = config.endpoint_for(operation)
    client = RunPodClient(
        config.model_copy(update={"mode": "serverless", "endpoint_id": endpoint}),
        run.transport,
    )
    longest = 0.0
    sent_any = False
    # A chunk whose /run got no answer may be running on the GPU: once one is, the round can no
    # longer be refused as "nothing sent" (all refunded), whatever the later chunks do.
    uncertain_any = False
    spans = chunk_items(config, operation, len(to_send))
    for number, span in enumerate(spans):
        pairs = [to_send[i] for i in span]
        rest = [to_send[i] for later in spans[number + 1 :] for i in later]
        # The step's own stop is read by `gpu_batch.run_rounds` before each round (and inside
        # the paused wait below); the chunks of one round leave back to back.
        stop = _wait_ended(session, None, renew=False)
        if stop is not None:
            # The Owner's «Oprește GPU acum», the guard or a shutdown ended the session (or it
            # could not be read): no /run leaves the studio outside it (a late job would wait in
            # RunPod's queue for the next step's GPU and bill there). What is left was never
            # sent and costs nothing.
            code, said = stop
            refused = (
                BatchRefused(code, said)  # its words already say what stays and what not
                if code == "GPU_FORCED_OFF"
                else BatchRefused(
                    code,
                    f"{said} {_NOTHING_SENT_RO}",
                    after_purchase_ro=f"{said} {REST_NOT_SENT_RO}",
                )
            )
            _unsent_rest(run, store, [*pairs, *rest], refused)
            if not sent_any and not uncertain_any:
                raise refused
            break
        items: list[dict[str, Any]] = [{**built[i], "index": n} for n, i in enumerate(span)]
        keys = [str(it["idempotency_key"]) for it in items]
        policy = chunk_policy(config, operation, len(items))
        body = {
            "input": {
                "contract": contract.CONTRACT,
                "operation": operation,
                "batch_key": contract.batch_key(keys),
                "items": items,
                "output": {"prefix": bucket.prefix, "url_ttl_seconds": bucket.url_ttl_seconds},
                "time_budget_seconds": max(
                    1, policy["executionTimeout"] // 1000 - HANDLER_MARGIN_SECONDS
                ),
            },
            "policy": policy,
        }
        try:
            contract.validate_input(body["input"])
        except contract.ContractError as exc:
            # The studio's own request breaks the worker's contract: refused here, before any
            # /run, so nothing of it was bought (before, it went up raw and the step booked
            # the round as a purchase).
            said = f"Cererea către RunPod nu respectă contractul lucrătorului ({str(exc)[:200]})."
            refused = BatchRefused(
                "REQUEST_INVALID",
                f"{said} {_NOTHING_SENT_RO}",
                after_purchase_ro=f"{said} {REST_NOT_SENT_RO}",
            )
            _unsent_rest(run, store, [*pairs, *rest], refused)
            if not sent_any and not uncertain_any:
                raise refused from exc
            break
        chunk_items_list = [item for item, _row in pairs]
        posted = await _post_run(
            run,
            client,
            body,
            contract.batch_key(keys),
            session=session,
            should_stop=should_stop,
            endpoint=endpoint,
            items=len(pairs),
        )
        failure = posted.failure
        if posted.job is None and failure is not None:
            _note_pause(run, posted)  # no job id to save first
            proven = refused_unqueued(failure)
            refusal = _refusal(failure, posted.ended, posted.waited) if proven else None
            # RunPod's own answer, already sanitised by media_http: without it a failed /run
            # read only «refused, reason unknown» (2026-10-09, the first live stills round).
            logger.warning(
                "runpod_run_failed",
                extra={
                    "endpoint_id": endpoint,
                    "items": len(pairs),
                    "http_status": failure.http_status,
                    "unsent": failure.unsent,
                    "unanswered": failure.unanswered,
                    "vendor_code": failure.code,
                    "detail": (failure.detail or "")[:300],
                    "error_class": type(failure).__name__,
                    "cause_class": type(failure.__cause__).__name__ if failure.__cause__ else None,
                    "refusal_code": refusal.code if refusal is not None else None,
                },
            )
            answer = {
                "http_status": failure.http_status,
                "detail": (failure.detail or "")[:300] or None,
                "code": refusal.code if refusal is not None else UNCERTAIN,
                "at": now(),
            }
            _journal_answer(store, pairs, failure, answer, proven=proven, session_id=run.session_id)
            if not proven:
                note = getattr(session, "note_uncertain", None)
                if callable(note):
                    note([row.idempotency_key for _item, row in pairs])
            run.chunks.append(
                _Chunk(None, chunk_items_list, policy, time.monotonic(), uncertain=not proven)
            )
            uncertain_any = uncertain_any or not proven
            if refusal is not None and not sent_any and not uncertain_any:
                # Nothing of the round left: the step refuses before spending, in RunPod's
                # words (unsent: the meter gives the round back, the stage books nothing).
                if rest:
                    _unsent_rest(run, store, rest, refusal)
                raise refusal from failure
            for item, _row in pairs:
                run._pending_report.append(
                    ItemOutcome(item, "FAILED", None, None, None, UNSENT if proven else UNCERTAIN)
                )
            if refusal is not None and posted.ended is not None:
                # The wait for a paused endpoint ended (its budget, the GPU off, a stop): no
                # later chunk is sent either, and the step sends no further round.
                _unsent_rest(run, store, rest, refusal)
                break
            continue
        # Saved BEFORE the session note, the takes or any poll.
        job = str(posted.job)
        _save_job(run.engine, pairs, job, run.session_id, session)
        _note_pause(run, posted)  # after the id is saved, never before (`_note_pause`)
        sent_any = True
        run.remote_job_ids.append(job)
        run.chunks.append(_Chunk(job, chunk_items_list, policy, time.monotonic()))
        longest = max(longest, policy["ttl"] / 1000)
        logger.info("runpod_batch_submitted", extra={"items": len(pairs), "operation": operation})
        # The takes SUBMITTED now (a few local writes, no gap worth a cold start), before the
        # next chunk's POST and before any poll.
        for item in chunk_items_list:
            on_submitted(item)
    run._deadline = time.monotonic() + longest if longest else 0.0
