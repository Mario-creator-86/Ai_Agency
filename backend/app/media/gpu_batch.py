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
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal

from sqlalchemy import Engine

from app.providers.media_http import MediaProviderError
from app.providers.runpod.batch import (
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
    estimate never lowers it (the Owner approved the estimate; a billing read settles it)."""
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
    }
    billed: list[float | None] = []
    overhead = float(price_credits([]))
    poll_every = float(getattr(getattr(adapter, "config", None), "poll_interval", 2.0))

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
            if halted is not None:
                break
            if any(o.error == UNCERTAIN for o in outcomes):
                # A round whose answer was lost: its items may have been served. Nothing more
                # is sent in this step; the same keys go out again in a later step, where the
                # worker's manifest makes them a free reuse.
                summary["stopped"] = summary["stopped"] or UNCERTAIN
                break
            requests = list(next_round(outcomes))
    known = [b for b in billed if b is not None]
    summary["billed_seconds"] = sum(known) if known and len(known) == len(billed) else None
    logger.info(
        "gpu_rounds_done",
        extra={"rounds": summary["rounds"], "items": summary["items_sent"], "purpose": purpose},
    )
    return summary
