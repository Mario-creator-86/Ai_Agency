"""Watchdog passes that register from their own files (2026-10-09, P0).

The watchdog (`app.workflows.watchdog.run_watchdog`) is where the studio notices what a dead
process, a vendor or its own mistake left behind and repairs it, 0 credits, every few minutes.
The self-repair plan of 2026-10-09 adds about a dozen such repairs (a stuck film becomes a
card, a paused RunPod is retried, an answered letter closes...). Written into `run_watchdog`
itself they would all queue on one function; so each lives in a module of its own here and
registers itself:

    # app/workflows/passes/stuck_films.py
    from app.workflows.passes import WatchdogContext, watchdog_pass

    @watchdog_pass("stuck_films", order=200, on_error={"cards": []})
    def propose_close_cards(context: WatchdogContext) -> dict:
        from app.media.film_close import ...  # media imports workflows: import inside
        return {"cards": [...]}

`run_watchdog` runs its built-in parts exactly as before, then every registered pass in the
declared order (``order``, then the name), each in its own try: one pass that fails is logged
and reported as ``{**on_error, "error": True}`` and the next one still runs. Its result is
the pass's dict, under the pass's name, beside the built-in keys; ``passes`` lists what ran.
Nothing runs while the Owner's autonomy stop is set: the watchdog's early return is unchanged,
and the stop is read again before each registered pass, so one he pressed while the built-in
parts ran skips every pass still to run (``passes.skipped``).

The rules a pass keeps:

- It repairs for free or proposes a card: local reads and writes, a GET that buys nothing.
  It never buys, approves or moves money; whatever spends stays behind the Owner's gates
  (may_act, plan hashes, caps, his one-use yes), and a question only he can answer becomes
  a card in his Decisions window (`app.decisions.services.propose_owner_decision`).
- It never answers in the Owner's name: it does not decide a card (`decide_owner_decision`),
  run an applier (`APPLIERS`, or one of the core's own such as `_apply_budget`,
  `sources.apply_runpod_infra`, and what they hand on to, such as `pods.start_copy`), call one
  of his commands or name him as the issuer (``issued_by=OWNER``). A question only he can
  answer is a card he presses (the Owner boundary scan in tests/test_watchdog_passes.py).
- It is idempotent: the next pass, minutes later, finds the same rows and must not write a
  second card, letter or event for them.
- Importing its module only defines and registers (no database, no network). The package is
  imported the first time the watchdog runs (`PASSES.load`, see `app.registry_loader`).
- What it registers is a function defined at the top of its module (decorated, or given by
  name) or a lambda written in the call; never a partial, an instance, a closure or a name
  imported from elsewhere, and never by writing the table: the money and Owner scans in
  tests/test_watchdog_passes.py read only those two (review of 2026-10-09).
- Its result is a small JSON-able dict, and its name is not one of the built-in keys.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from app.registry_loader import PackageLoader

#: The keys `run_watchdog` writes itself; a registered pass may not take one of them.
BUILT_IN_RESULT_KEYS = frozenset(
    {
        "status",
        "reason",
        "renders",
        "publications",
        "processing",
        "leases",
        "reservations",
        "takes",
        "film_leases",
        "days",
        "intermediates",
        "defect_holds",
        "runpod_unsent_holds",
        "answered_letters",
        "correlation_id",
        # What the registered passes did, in order.
        "passes",
    }
)

_PASS_NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


@dataclass(frozen=True)
class WatchdogContext:
    """What one watchdog pass hands every registered pass."""

    engine: Engine
    settings: Any
    correlation_id: str


#: A registered pass: the context in, a small JSON-able summary out.
PassRun = Callable[[WatchdogContext], Mapping[str, Any]]


@dataclass(frozen=True)
class WatchdogPass:
    name: str
    order: int
    #: Not called ``run``: the paid-path scan follows ``x.run`` to every method of that name
    #: (tests/test_no_paid_path_escapes.py), and the stills rounds have one.
    function: PassRun
    #: The shape the pass reports when it raised, with ``"error": True`` added.
    on_error: Mapping[str, Any] = field(default_factory=dict)


_PASSES: dict[str, WatchdogPass] = {}

#: Imports this package's modules the first time the watchdog asks for its passes.
PASSES = PackageLoader(__name__)


def register_pass(
    name: str, run: PassRun, *, order: int, on_error: Mapping[str, Any] | None = None
) -> WatchdogPass:
    """Add a pass `run_watchdog` runs after its built-in parts. ``order`` places it among the
    registered passes (lower first, then by name). A name already taken by another function,
    or one of the built-in keys, is refused (ValueError)."""
    if not _PASS_NAME.match(name):
        raise ValueError(f"watchdog pass name {name!r} must be lower case letters, digits and _")
    if name in BUILT_IN_RESULT_KEYS:
        raise ValueError(f"watchdog pass name {name!r} is one of the watchdog's own keys")
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError(f"watchdog pass {name!r} needs a whole-number order")
    standing = _PASSES.get(name)
    if standing is not None and not _same(standing.function, run):
        raise ValueError(f"watchdog pass {name!r} is already registered (by {standing.function!r})")
    entry = WatchdogPass(name=name, order=order, function=run, on_error=dict(on_error or {}))
    _PASSES[name] = entry
    if standing is None:
        # Taken out again if the module registering it fails to import, whichever import was
        # running when it registered (`PackageLoader.added`).
        PASSES.added(_PASSES, name, owner=run)
    return entry


def watchdog_pass(
    name: str, *, order: int, on_error: Mapping[str, Any] | None = None
) -> Callable[[PassRun], PassRun]:
    """`register_pass` as a decorator; the function is returned unchanged."""

    def register(run: PassRun) -> PassRun:
        register_pass(name, run, order=order, on_error=on_error)
        return run

    return register


def _same(first: object, second: object) -> bool:
    """The same function registered again (its module imported twice)."""
    if first is second:
        return True
    name = getattr(first, "__qualname__", None)
    return (
        isinstance(name, str)
        and "<locals>" not in name
        and (getattr(first, "__module__", None), name)
        == (getattr(second, "__module__", None), getattr(second, "__qualname__", None))
    )


def registered_passes() -> list[WatchdogPass]:
    """Every registered pass in the order the watchdog runs them; the first call imports the
    package's modules."""
    PASSES.load()
    return sorted(_PASSES.values(), key=lambda entry: (entry.order, entry.name))


def unregister_pass(name: str) -> None:
    """Remove a pass (tests that register one of their own)."""
    _PASSES.pop(name, None)


__all__ = [
    "BUILT_IN_RESULT_KEYS",
    "PASSES",
    "PassRun",
    "WatchdogContext",
    "WatchdogPass",
    "register_pass",
    "registered_passes",
    "unregister_pass",
    "watchdog_pass",
]
