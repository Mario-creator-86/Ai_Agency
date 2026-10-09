"""A paid step on RunPod Serverless, bought in ROUNDS: one batch job per round, inside one GPU
session that is switched off right after the step's last result.

The Owner, 2026-10-08: «trebuie sa se opreasca imediat dupa, nu la 30 sec. Sunt taxat la
secunda, deci trebuie oprit imediat dupa generare». So:

* The step opens ONE GPU session (`providers.runpod.gpu_session.gpu_session`: the Policy
  Kernel's ``infra.gpu_on`` inside this already approved step, workers.max=1) and closes it in
  ``finally`` (purge the queue, cancel what is left, workers.max=0, verify OFF), whatever
  happens. A refusal to switch on (`GpuSessionRefused`) happens before anything is sent.
* Round 1 is every item the step buys; a later round is only what QC sent back (the caller's
  ``next_round``). Each round is ONE batch (`RunPodConnection.submit_batch`): the worker loads
  its models once, makes every item, and scales to zero 1 s after the last (idleTimeout), so
  the QC between rounds costs nothing.
* Before a round is sent it is priced whole (its items + one round overhead: cold start + idle
  tail, ``price_credits``); a round that does not fit what is left of the step's cap is cut in
  a fixed order (scene, then candidate) until it does; an empty round stops the step. The
  Owner's mode, the autonomy stop and the plan are read once before each round
  (`PurchaseGuard.stop_reason`), never per item inside a batch.
* While a round runs the studio polls: the mode, the stop, the session (`GpuSession.renew`:
  the Owner's «Oprește GPU acum», the guard or a shutdown raise `GpuForcedOff`). A stop cancels
  every unfinished job: what finished is collected and booked, the rest «nu s-a cumpărat».
* The meter counts a round's price when it is submitted (possibly charged), and gives back the
  items RunPod never made (cancelled, or never sent).
* A result that proves the endpoint's weights wrong (another mirror revision, MODELS_MISSING;
  `providers.runpod.weights`) stops the step: what is left is cancelled, no further round is
  sent, the session's close sets workers.max=0, and the Owner gets a card with the console
  step (the cached-model field cannot be set through the API, 2026-10-09).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal

from sqlalchemy import Engine

from app.providers.media_http import MediaProviderError
from app.providers.runpod.batch import (
    NOT_QUEUED_STOP,
    UNCERTAIN,
    UNSENT,
    BatchRequest,
    ItemOutcome,
    SubmittedItem,
)
from app.providers.runpod.gpu_session import GpuForcedOff, StepPermit, gpu_session, precheck

logger = logging.getLogger("studio.media")

#: Why a round was cut or not sent at all: the step's cap, in the Owner's words.
CAP_STOP = (
    "STOPPED_AT_CAP: runda următoare ({price:.0f} credite cu pornirea GPU-ului) ar depăși ce a "
    "rămas din plafonul aprobat ({left:.0f} credite); nu se mai cumpără nimic în acest pas."
)
#: A round RunPod did not finish within its executionTimeout + queue wait.
TIMEOUT_STOP = (
    "RunPod nu a terminat runda în timpul ei maxim; ce s-a terminat rămâne, restul nu s-a cumpărat."
)


def gpu_precheck(
    engine: Engine,
    adapter: Any,
    *,
    purpose: Literal["image", "video"],
    integration_id: str | None = None,
) -> None:
    """Called by a paid step on a batch adapter BEFORE it asks for or spends the Owner's yes:
    raises `GpuSessionRefused` (unsent) when the GPU session could not open anyway
    (`gpu_session.precheck`)."""
    precheck(engine, adapter, purpose=purpose, integration_id=integration_id)


def _order(request: BatchRequest) -> tuple[int, str, int]:
    scene = request.scene_id
    return (int(scene) if scene.isdigit() else 10**9, scene, request.candidate_index)


def fit_round(
    requests: Sequence[BatchRequest],
    price_credits: Callable[[list[BatchRequest]], float],
    left: float,
) -> list[BatchRequest]:
    """The round, cut from its end (highest scene, then candidate) until its price fits."""
    fitted = sorted(requests, key=_order)
    while fitted and price_credits(fitted) > left + 1e-9:
        fitted.pop()
    return fitted


def _keep_alive(session: Any) -> str | None:
    """Renew the GPU session; the forced-off words when it was switched off from outside."""
    try:
        session.renew()
    except GpuForcedOff as exc:
        return exc.reason_ro
    return None


def _settle_earlier_holds(engine: Engine, session: Any) -> None:
    """A scene an earlier unanswered /run held, whose items this proof just covered (a redo
    sends the same keys): no claim and no manifest for those keys and nothing queued means
    that earlier /run made nothing either, so its hold is released now (`media.runpod_unsent.
    settle_proven_holds`). Local writes only; a failure is logged and the watchdog's pass (and
    the boot's) does it later."""
    from uuid import uuid4  # noqa: PLC0415

    from app.media.runpod_unsent import settle_proven_holds  # noqa: PLC0415 - it reads us

    try:
        settle_proven_holds(
            engine, correlation_id=str(getattr(session, "correlation_id", None) or uuid4())
        )
    except Exception as exc:  # noqa: BLE001 - the step's own result stands; the pass retries
        logger.warning("runpod_unsent_settle_failed", extra={"error": type(exc).__name__})


def _prove_unsent(
    engine: Engine,
    session: Any,
    uncertain_round: tuple[Any, list[ItemOutcome], float],
    summary: dict[str, Any],
    *,
    meter: Any,
    price_credits: Callable[[list[BatchRequest]], float],
    overhead: float,
    on_unsent: Callable[[list[ItemOutcome], dict[str, Any]], None] | None,
) -> None:
    """The proof of nothing queued for the round that ended the step (`BatchRun.prove_unsent`),
    read after the session's close. Never sends anything."""
    run, outcomes, kept = uncertain_round
    prove = getattr(run, "prove_unsent", None)
    proof = prove(session) if callable(prove) else None
    if proof is None:
        return
    summary["unsent_proof"] = {
        "proven": bool(proof.get("proven")),
        "problems": list(proof.get("problems") or []),
        "gpu_session_id": proof.get("gpu_session_id"),
    }
    if not proof.get("proven"):
        return
    ids = {str(item["job_row_id"]) for item in proof.get("items") or []}
    proven = [o for o in outcomes if o.error == UNCERTAIN and o.item.job_row_id in ids]
    if not proven:
        return
    every_uncertain = all(o.item.job_row_id in ids for o in outcomes if o.error == UNCERTAIN)
    whole = len(proven) == len(outcomes) and not list(getattr(run, "remote_job_ids", []) or [])
    # Nothing of the round reached RunPod: what the meter kept for it goes back, its GPU start
    # included (no worker started for it). Otherwise only the proven items' share.
    given_back = (
        kept
        if whole
        else max(0.0, float(price_credits([o.item.request for o in proven])) - overhead)
    )
    # The stage's takes first, the journal rows second: a process that stops in between leaves
    # rows still uncertain (the next step sends the same keys again: a free reuse at worst)
    # and takes that no longer hold the scene, never a scene held by a round proven unsent.
    if on_unsent is not None:
        on_unsent(proven, proof)
    mark = getattr(run, "mark_unsent", None)
    if callable(mark):
        mark(proof)
        _settle_earlier_holds(engine, session)
    meter.committed -= given_back
    summary["not_queued_items"] = len(proven)
    summary["not_queued_credits"] = given_back
    if every_uncertain and summary.get("stopped") == UNCERTAIN:
        summary["stopped"] = NOT_QUEUED_STOP


def run_rounds(
    engine: Engine,
    adapter: Any,
    *,
    permit: StepPermit,
    purpose: Literal["image", "video"],
    first_round: list[BatchRequest],
    next_round: Callable[[list[ItemOutcome]], list[BatchRequest]],
    price_credits: Callable[[list[BatchRequest]], float],
    cap_left: Callable[[], float],
    guard: Any,
    stopped: Callable[[], str | None],
    on_submitted: Callable[[SubmittedItem], None],
    on_outcome: Callable[[ItemOutcome], None],
    meter: Any,
    sleep: Callable[[float], None] = time.sleep,
    credits_for_seconds: Callable[[float], float] | None = None,
    on_unsent: Callable[[list[ItemOutcome], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Buy the step's rounds inside one GPU session; returns what happened.

    Raises `GpuSessionRefused` / `BatchRefused` when the first round could not even be sent
    (nothing spent): the stage turns them into its own refusal. ``stopped()`` is the autonomy
    stop (or any reason to stop the step), ``guard`` the step's `PurchaseGuard` (or None).

    ``credits_for_seconds`` turns billed GPU-seconds into the step's credits (the budget rate,
    `media.assembler.gpu_seconds_to_credits`). When a round's jobs report their times, the
    round's billed estimate ((delayTime + executionTime)/1000 + idleTimeout per job, an upper
    bound: queue and throttled time are counted too) is compared with what the meter kept for
    the round, and the meter is RAISED to it when RunPod used more than estimated: the books
    and the cap left for the next rounds never sit below what the GPU used. A measure below the
    estimate never lowers it (the Owner approved the estimate; a billing read settles it).

    A round whose /run failed with no job id (SUBMISSION_UNCERTAIN) stops the step. Once the
    session is closed (its off read the queue, `gpu_session.close_session`), the round asks
    `BatchRun.prove_unsent` whether RunPod queued and made nothing (2026-10-09). Proven: those
    items were never bought, so their credits go back to the meter (the whole round's, its GPU
    start too, when no job of the round was accepted), the stop says so (`NOT_QUEUED_STOP`)
    and ``on_unsent(outcomes, proof)`` lets the stage re-record its takes. Not proven: today's
    behaviour, the items counted and nothing sent again. ``summary['unsent_proof']`` says which."""
    summary: dict[str, Any] = {
        "rounds": 0,
        "items_sent": 0,
        "stopped": None,
        "cap_stop": None,
        "cancelled_items": 0,
        "remote_job_ids": [],
        "billed_seconds": None,
        "overhead_credits": 0.0,
        "forced_off": False,
        # Credits added to the meter because RunPod's measured times exceeded the estimate.
        "reconciled_credits": 0.0,
        # The weights the endpoint loaded were not the expected ones (`weights.WeightsProblem`).
        "weights_problem": None,
    }
    problem: Any = None
    billed: list[float | None] = []
    overhead = float(price_credits([]))
    poll_every = float(getattr(getattr(adapter, "config", None), "poll_interval", 2.0))
    # The round that ended the step with an uncertain /run: its run, outcomes and what the
    # meter kept for it, for the proof read once the session is closed.
    uncertain_round: tuple[Any, list[ItemOutcome], float] | None = None

    def stop_reason() -> str | None:
        reason = stopped()
        if reason:
            return reason
        return guard.stop_reason(None) if guard is not None else None

    with gpu_session(engine, adapter, purpose=purpose, permit=permit) as session:
        requests = list(first_round)
        while requests:
            reason = stop_reason()
            if reason:
                summary["stopped"] = reason
                break
            left = float(cap_left())
            fitted = fit_round(requests, price_credits, left)
            if len(fitted) < len(requests):
                summary["cap_stop"] = CAP_STOP.format(price=price_credits(requests), left=left)
            if not fitted:
                summary["stopped"] = summary["cap_stop"]
                break
            price = float(price_credits(fitted))
            meter.committed += price
            meter.attempts += 1
            try:
                run = adapter.submit_batch(fitted, session=session, on_submitted=on_submitted)
            except MediaProviderError as exc:
                if exc.unsent or exc.http_status in (400, 401, 403, 404, 413, 422):
                    # Proven not sent (or refused before anything was made): nothing charged.
                    meter.committed -= price
                    meter.attempts -= 1
                    if summary["rounds"] == 0:
                        raise
                    summary["stopped"] = str(getattr(exc, "reason_ro", None) or exc)
                    break
                raise
            summary["rounds"] += 1
            summary["items_sent"] += len(fitted)
            summary["overhead_credits"] += overhead
            summary["remote_job_ids"] += list(run.remote_job_ids)
            outcomes: list[ItemOutcome] = []
            halted: str | None = None
            forced: str | None = None
            drains = 0
            while True:
                for outcome in run.poll():
                    outcomes.append(outcome)
                    on_outcome(outcome)
                    if halted is None and forced is None:
                        # A judgement may take minutes: the session is renewed after each one,
                        # so the guard never takes a judging step for a dead one.
                        forced = _keep_alive(session)
                if forced is not None and halted is None:
                    summary["forced_off"] = True
                    halted = summary["stopped"] = forced
                    if not run.done():
                        run.cancel(halted)
                    continue
                found = getattr(run, "weights_problem", None)
                if found is not None and problem is None:
                    # The endpoint holds other weights: nothing more is made with them.
                    problem = found
                    summary["weights_problem"] = found.as_dict()
                    if halted is None:
                        halted = summary["stopped"] = found.words_ro()
                        if not run.done():
                            run.cancel(halted)
                        continue
                if run.done():
                    break
                if halted is not None:
                    # Cancelled: the remaining outcomes arrive on the next polls; the session's
                    # close cancels and purges again whatever is still there.
                    drains += 1
                    if drains > 3:
                        break
                    sleep(poll_every)
                    continue
                if run.deadline_passed():
                    halted = TIMEOUT_STOP
                else:
                    halted = stop_reason()
                    if halted is None:
                        try:
                            session.renew()
                        except GpuForcedOff as exc:
                            summary["forced_off"] = True
                            halted = exc.reason_ro
                if halted is not None:
                    run.cancel(halted)
                    summary["stopped"] = halted
                    continue
                sleep(poll_every)
            # Items RunPod never made are not charged: their share of the round goes back.
            unmade = [
                o.item.request
                for o in outcomes
                if o.state == "CANCELLED" or (o.state == "FAILED" and o.error == UNSENT)
            ]
            kept = price
            if unmade:
                given_back = max(0.0, price_credits(unmade) - overhead)
                meter.committed -= given_back
                kept -= given_back
                summary["cancelled_items"] += len(unmade)
            settle = getattr(run, "settle", None)
            if callable(settle):
                settle()  # the jobs' final times (items came from manifests)
            measured_seconds = run.billed_seconds_estimate()
            billed.append(measured_seconds)
            if credits_for_seconds is not None and measured_seconds is not None:
                measured = float(credits_for_seconds(measured_seconds))
                if measured > kept + 1e-9:
                    meter.committed += measured - kept
                    summary["reconciled_credits"] += measured - kept
            if any(o.error == UNCERTAIN for o in outcomes):
                uncertain_round = (run, outcomes, kept)
            if halted is not None:
                break
            if uncertain_round is not None:
                # A round whose answer was lost: its items may have been served. Nothing more
                # is sent in this step; the same keys go out again in a later step, where the
                # worker's manifest makes them a free reuse.
                summary["stopped"] = summary["stopped"] or UNCERTAIN
                break
            requests = list(next_round(outcomes))
    if uncertain_round is not None:
        _prove_unsent(
            engine,
            session,
            uncertain_round,
            summary,
            meter=meter,
            price_credits=price_credits,
            overhead=overhead,
            on_unsent=on_unsent,
        )
    if problem is not None:
        # After the close (workers.max=0): the card in his Decisions window, once per endpoint.
        from app.providers.runpod.weights import raise_weights_card  # noqa: PLC0415

        raise_weights_card(
            engine, problem, getattr(adapter, "integration_id", None) or permit.integration_id
        )
    known = [b for b in billed if b is not None]
    summary["billed_seconds"] = sum(known) if known and len(known) == len(billed) else None
    logger.info(
        "gpu_rounds_done",
        extra={"rounds": summary["rounds"], "items": summary["items_sent"], "purpose": purpose},
    )
    return summary
