"""Prepare approved purchases before dispatch, without releasing their leases or holds.

The synchronous APIs still execute immediately. The Director can instead advance each
purchase to its GPU boundary, combine compatible ready requests, then finish each purchase
through its existing QC, retirement restoration and accounting code.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, replace
from functools import wraps
from typing import Any, Literal

from app.providers.runpod.batch import BatchRefused, BatchRequest, ItemOutcome


def _close_flow(flow: Generator[Any, Any, Any]) -> None:
    if getattr(flow, "gi_frame", None) is not None:
        try:
            # GeneratorExit bypasses normal purchase error handlers. An interrupted flow
            # must first restore retired takes and release/settle its own budget hold.
            flow.throw(RuntimeError("Cumpărarea pregătită a fost întreruptă."))
        except Exception:  # noqa: BLE001 - cleanup never replaces the original interruption
            pass
    flow.close()


@dataclass
class RoundWork:
    engine: Any
    adapter: Any
    permit: Any
    purpose: Literal["image", "video"]
    first_round: list[BatchRequest]
    next_round: Callable[..., Any]
    price_credits: Callable[..., float]
    cap_left: Callable[[], float]
    guard: Any
    stopped: Callable[[], str | None]
    on_submitted: Callable[..., None]
    on_outcome: Callable[..., None]
    meter: Any
    sleep: Callable[..., None] | None = None
    credits_for_seconds: Callable[..., float] | None = None
    on_unsent: Callable[..., None] | None = None
    on_wait: Callable[[], None] | None = None
    #: The step's budget hold, grown before each round (`gpu_batch.run_rounds`); None: the
    #: purchase held its whole cap (a scene redo), and a bundle of them reads ``cap_left``.
    make_room: Callable[[float], Any] | None = None

    def run_purchase(self) -> dict[str, Any]:
        from app.media.gpu_batch import run_rounds  # noqa: PLC0415

        args = dict(vars(self))
        if self.sleep is None:
            args.pop("sleep")
        return run_rounds(**args)


def flow_call[**P, T](
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> Generator[RoundWork, dict[str, Any], T]:
    """Use a purchase's preparation flow, or an unchanged non-GPU implementation."""
    flow = getattr(function, "gpu_flow", None)
    if flow is not None:
        owner = getattr(function, "__self__", None)
        call_args = (owner, *args) if owner is not None else args
        return (yield from flow(*call_args, **kwargs))
    return function(*args, **kwargs)


def purchase_flow[**P, T](
    function: Callable[P, Generator[RoundWork, dict[str, Any], T]],
) -> Callable[P, T]:
    """Keep the public synchronous API, exposing its GPU suspension point to the bundle."""

    @wraps(function)
    def execute(*args: P.args, **kwargs: P.kwargs) -> T:
        flow = function(*args, **kwargs)
        try:
            work = next(flow)
            while True:
                try:
                    summary = work.run_purchase()
                except Exception as exc:
                    work = flow.throw(exc)
                else:
                    work = flow.send(summary)
        except StopIteration as finished:
            return finished.value
        finally:
            _close_flow(flow)

    execute.gpu_flow = function  # type: ignore[attr-defined]
    return execute


def _identity(request: BatchRequest) -> tuple[str, str]:
    return request.project_id, request.scene_id


def _compatible(left: RoundWork, right: RoundWork) -> bool:
    if left.engine is not right.engine or left.purpose != right.purpose:
        return False
    for_seconds = left.credits_for_seconds, right.credits_for_seconds
    if (for_seconds[0] is None) != (for_seconds[1] is None):
        return False
    if (
        for_seconds[0] is not None
        and for_seconds[1] is not None
        and for_seconds[0](1) != for_seconds[1](1)
    ):
        return False
    a, b = left.adapter, right.adapter
    if a is b:
        return True
    return (
        getattr(a, "config", None) is not None
        and a.config == getattr(b, "config", None)
        and getattr(a, "integration_id", None) == getattr(b, "integration_id", None)
        and getattr(a, "storage_root", None) == getattr(b, "storage_root", None)
        and getattr(getattr(a, "core", None), "transport", None)
        is getattr(getattr(b, "core", None), "transport", None)
    )


class _Bundle:
    def __init__(self, work: list[RoundWork]) -> None:
        self.work = work
        self.owners: dict[tuple[str, str], int] = {}
        self.kept: dict[int, float] = {}
        self.attempts = 0
        self.cap_stops: dict[int, str] = {}
        for index, purchase in enumerate(work):
            for request in purchase.first_round:
                key = _identity(request)
                if key in self.owners and self.owners[key] != index:
                    raise BatchRefused("DUPLICATE_SCENE", "Aceeași scenă apare în două refaceri.")
                self.owners[key] = index

    @property
    def committed(self) -> float:
        return sum(float(p.meter.committed) for p in self.work)

    def _split(self, requests: list[BatchRequest]) -> dict[int, list[BatchRequest]]:
        groups: dict[int, list[BatchRequest]] = {}
        for request in requests:
            groups.setdefault(self.owners[_identity(request)], []).append(request)
        return groups

    def price(self, requests: list[BatchRequest]) -> float:
        if not requests:
            return max(p.price_credits([]) for p in self.work)
        groups = self._split(requests)
        start = max(self.work[i].price_credits([]) for i in groups)
        return start + sum(
            self.work[i].price_credits(rs) - self.work[i].price_credits([])
            for i, rs in groups.items()
        )

    def commit(self, requests: list[BatchRequest], _price: float) -> None:
        self.kept = {}
        groups = self._split(requests)
        units = {
            i: float(self.work[i].price_credits(rs) - self.work[i].price_credits([]))
            for i, rs in groups.items()
        }
        total = sum(units.values())
        start = max(self.work[i].price_credits([]) for i in groups)
        for index, items in groups.items():
            purchase = self.work[index]
            share = units[index] / total if total else len(items) / len(requests)
            quote = units[index] + start * share
            purchase.meter.committed += quote
            purchase.meter.attempts += 1
            self.kept[index] = quote

    def refund(
        self, requests: list[BatchRequest], *, whole: bool = False, rollback: bool = False
    ) -> float:
        refunded = 0.0
        groups = self._split(requests)
        for index, quote in list(self.kept.items()):
            if index not in groups and not whole:
                continue
            purchase = self.work[index]
            share = (
                quote
                if whole
                else max(0.0, purchase.price_credits(groups[index]) - purchase.price_credits([]))
            )
            share = min(quote, share)
            purchase.meter.committed -= share
            self.kept[index] -= share
            refunded += share
            if rollback:
                purchase.meter.attempts -= 1
        return refunded

    def reconcile(self, extra: float) -> None:
        total = sum(self.kept.values())
        if total <= 0:
            return
        for index, quote in self.kept.items():
            self.work[index].meter.committed += extra * quote / total

    def fit(self, index: int, requests: list[BatchRequest]) -> list[BatchRequest]:
        from app.media.gpu_batch import CAP_STOP, fit_round  # noqa: PLC0415

        purchase = self.work[index]
        left = max(0.0, float(purchase.cap_left()))
        fitted = fit_round(requests, purchase.price_credits, left)
        if len(fitted) < len(requests):
            self.cap_stops[index] = CAP_STOP.format(
                price=purchase.price_credits(requests), left=left
            )
        return fitted

    def next(self, outcomes: list[ItemOutcome]) -> list[BatchRequest]:
        following: list[BatchRequest] = []
        for index, purchase in enumerate(self.work):
            own = [o for o in outcomes if self.owners[_identity(o.item.request)] == index]
            if not own:
                continue
            requests = purchase.next_round(own)
            for request in requests:
                key = _identity(request)
                owner = self.owners.setdefault(key, index)
                if owner != index:
                    raise BatchRefused("DUPLICATE_SCENE", "Aceeași scenă apare în două refaceri.")
            following += self.fit(index, requests)
        return following

    def stop_reason(self, _unused: Any = None) -> str | None:
        for purchase in self.work:
            reason = purchase.stopped()
            if not reason and purchase.guard is not None:
                reason = purchase.guard.stop_reason(None)
            if reason:
                return reason
        return None

    @property
    def stopped(self) -> dict[str, Any] | None:
        return next(
            (
                p.guard.stopped
                for p in self.work
                if p.guard is not None and getattr(p.guard, "stopped", None)
            ),
            None,
        )

    def submitted(self, item: Any) -> None:
        self.work[self.owners[_identity(item.request)]].on_submitted(item)

    def landed(self, outcome: ItemOutcome) -> None:
        self.work[self.owners[_identity(outcome.item.request)]].on_outcome(outcome)

    def unsent(self, outcomes: list[ItemOutcome], proof: dict[str, Any]) -> None:
        for index, purchase in enumerate(self.work):
            own = [o for o in outcomes if self.owners[_identity(o.item.request)] == index]
            if own and purchase.on_unsent is not None:
                purchase.on_unsent(own, proof)

    def run_purchase(self) -> list[dict[str, Any]]:
        from app.media.gpu_batch import run_rounds  # noqa: PLC0415

        first = [request for i, p in enumerate(self.work) for request in self.fit(i, p.first_round)]
        leader = self.work[0]
        permit = replace(leader.permit, batch_permits=tuple(p.permit for p in self.work[1:]))
        args: dict[str, Any] = {"credits_for_seconds": leader.credits_for_seconds}
        if leader.sleep is not None:
            args["sleep"] = leader.sleep
        summary = run_rounds(
            leader.engine,
            leader.adapter,
            permit=permit,
            purpose=leader.purpose,
            first_round=first,
            next_round=self.next,
            price_credits=self.price,
            cap_left=lambda: sum(max(0, p.cap_left()) for p in self.work),
            guard=self,
            stopped=lambda: None,
            on_submitted=self.submitted,
            on_outcome=self.landed,
            meter=self,
            accounting=self,
            on_unsent=self.unsent,
            on_wait=leader.on_wait,
            **args,
        )
        return [
            {
                **summary,
                "cap_stop": self.cap_stops.get(i),
                "stopped": self.cap_stops.get(i) or summary.get("stopped"),
            }
            for i in range(len(self.work))
        ]


def run_prepared(
    flows: list[Generator[RoundWork, dict[str, Any], Any]],
    *,
    before_prepare: Callable[[int], None] | None = None,
    on_prepared: Callable[[int, Any], None] | None = None,
) -> list[Any]:
    """Advance every purchase to GPU readiness, dispatch compatible bundles, finish safely.

    Failures go back through the purchase's existing error handlers, so its holds and retired
    takes are settled independently. Image/video work is never mixed in one GPU batch.
    """
    results: list[Any] = [None] * len(flows)
    pending: dict[int, RoundWork] = {}

    def advance(
        index: int, value: Any = None, error: Exception | None = None, initial: bool = False
    ) -> None:
        try:
            if initial and before_prepare is not None:
                before_prepare(index)
            flow = flows[index]
            work = next(flow) if initial else (flow.throw(error) if error else flow.send(value))
            if not isinstance(work, RoundWork):
                raise TypeError("a prepared purchase must yield RoundWork")
            if initial and on_prepared is not None:
                on_prepared(index, work)
            pending[index] = work
        except StopIteration as done:
            results[index] = done.value
            if initial and on_prepared is not None:
                on_prepared(index, done.value)
        except Exception as exc:
            results[index] = exc

    try:
        for index in range(len(flows)):
            advance(index, initial=True)
        while pending:
            ready, pending = pending, {}
            groups: list[list[int]] = []
            for index, work in ready.items():
                group = next((g for g in groups if _compatible(ready[g[0]], work)), None)
                if group is None:
                    groups.append([index])
                else:
                    group.append(index)
            completed: dict[int, Any] = {}
            for group in groups:
                try:
                    summaries = _Bundle([ready[i] for i in group]).run_purchase()
                    completed.update(zip(group, summaries, strict=True))
                except Exception as exc:
                    completed.update((i, exc) for i in group)
            for index, value in completed.items():
                advance(index, error=value if isinstance(value, Exception) else None, value=value)
        return results
    finally:
        for flow in flows:
            _close_flow(flow)
