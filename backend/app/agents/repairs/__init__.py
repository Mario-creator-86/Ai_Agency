"""The Director's repair desk: what she puts right herself (2026-10-11).

The Owner, 2026-10-11: «vreau ca directoarea să poată repara asta. Agenția trebuie să fie
autonomă; când apar probleme, directoarea trebuie să fie în măsură să repare». Until that day
her loop (`app.agents.command.direct_company`) could only write letters. The 167 runs left
unpriced because the Owner typed the Ollama price after they ran went to Nadia three mornings
running, and Nadia, who cannot write a price, asked for a rate card that already existed; a
failure rate read over thirty days made a retry storm of 2026-10-04 look like a fault of
today; and three HANDOFFs about what a film cost went round the same thread while the cost
was one join away in the books. Each of those is a repair the Director can make herself, with
data the studio already holds, and none of them needs an employee's letter.

Each repair lives in a module of its own here and registers itself:

    # app/agents/repairs/reprice.py
    from app.agents.repairs import register_repair

    def unpriced_usage(context): ...      # what it sees: the matters, each with its params
    def still_unpriced(context, params): ...  # at apply time: why it is no longer needed
    def apply_active_price(context, params): ...  # the repair; returns what changed

    register_repair(
        "reprice_unpriced_runs",
        apply_active_price,
        tier="T1",
        action="economy.apply_active_price",
        precondition=still_unpriced,
        detector=unpriced_usage,
        summary="apply the price active now to agent runs stored without a cost",
    )

`app.agents.repairs.desk` does the rest the same way for every repair: it offers what the
detectors see to the Director's choice (`command.findings`), asks the Policy Kernel
(`may_act` with the repair's action and tier) before it queues the repair as a durable
DIRECTOR_REPAIR task and again before it applies it, and afterwards records the event
``director.repair_applied`` (or ``director.repair_declined``) with what changed, closes the
repair's DirectorDecision with the outcome, and tells the Owner in one STATUS letter.

The rules a repair keeps, the passes' rules (`app.workflows.passes`) and the Owner's:

- It repairs data and configuration the studio owns. It never buys, approves or moves money,
  never writes a price, a budget, the ledger, a reconciliation, a credential or the Owner's
  policy, and never decides one of his cards or calls one of his commands (the Owner and
  money scans in tests/test_watchdog_passes.py read this package too). What only he can do
  is ONE deduped card in his Decisions window (`app.decisions.sources.ask`), never a letter
  to an employee.
- It is idempotent: applied twice, the second finds nothing left to do.
- Its precondition is read again at the moment it applies: the studio moves between the loop
  that chose it and the worker that runs it.
- Importing its module only defines and registers (no database, no network).
- What it registers are functions defined at the top of its module (or lambdas written in
  the call), never a partial, an instance or a name imported from elsewhere.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from app.registry_loader import PackageLoader

#: The tiers a repair may declare. T4 is the Owner's alone in every mode (`app.services`), so
#: no repair is ever registered at it.
REPAIR_TIERS = ("T0", "T1", "T2", "T3")

#: What a repair reports, beside what changed: it did the work, there was nothing left to do
#: (its precondition no longer held), or it was refused or could not be done.
APPLIED = "APPLIED"
NOTHING_TO_DO = "NOTHING_TO_DO"
DECLINED = "DECLINED"

_REPAIR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


@dataclass(frozen=True)
class RepairContext:
    """What the desk hands a repair: the studio, and on whose behalf it acts."""

    engine: Engine
    settings: Any
    #: The language models (`app.providers.registry.ProviderRegistry`), None when the worker
    #: has none; a repair that needs a model (a probe run) declines without it.
    registry: Any
    #: The DIRECTOR_REPAIR task's id (or the loop's correlation, for a detector).
    correlation_id: str
    director_id: str | None = None
    #: The Director's decision this repair carries out, closed by the desk afterwards.
    decision_id: str | None = None


#: The repair itself: params in, ``outcome(...)`` out.
RepairRun = Callable[[RepairContext, Mapping[str, Any]], Mapping[str, Any]]
#: Why the repair is no longer needed, in the Owner's words, or None when it still is.
RepairPrecondition = Callable[[RepairContext, Mapping[str, Any]], str | None]
#: The matters this repair sees, each a `finding(...)`.
RepairDetector = Callable[[RepairContext], list[dict[str, Any]]]


@dataclass(frozen=True)
class Repair:
    name: str
    tier: str
    #: The Policy Kernel's action asked before it is queued and before it applies.
    action: str
    #: What it does, in a phrase the Director's model reads beside the matters.
    summary: str
    #: Not called ``run``: the paid-path scan follows ``x.run`` to every method of that name
    #: (tests/test_no_paid_path_escapes.py). The same for the two names below.
    function: RepairRun
    precondition: RepairPrecondition
    detector: RepairDetector | None = None
    #: Where the Owner does the same work by hand («Setări → Angajați»), named on his card
    #: when the kernel will not let her make it; empty when there is nothing for him to do
    #: there (applying a price to runs is not something he does by hand).
    place_ro: str = ""


_REPAIRS: dict[str, Repair] = {}

#: Imports this package's modules the first time the desk asks for its repairs.
REPAIRS = PackageLoader(__name__)


def register_repair(
    name: str,
    apply: RepairRun,
    *,
    tier: str,
    action: str,
    precondition: RepairPrecondition,
    detector: RepairDetector | None = None,
    summary: str = "",
    place_ro: str = "",
) -> Repair:
    """Add a repair the Director can choose. A name taken by another function, a tier the
    Director cannot hold (T4) or an action with no name is refused (ValueError)."""
    if not _REPAIR_NAME.match(name):
        raise ValueError(f"repair name {name!r} must be lower case letters, digits and _")
    if tier not in REPAIR_TIERS:
        raise ValueError(f"repair {name!r}: tier {tier!r} is not one the Director may hold")
    if not action or not isinstance(action, str):
        raise ValueError(f"repair {name!r} needs the Policy Kernel's action name")
    standing = _REPAIRS.get(name)
    if standing is not None and not _same(standing.function, apply):
        raise ValueError(f"repair {name!r} is already registered (by {standing.function!r})")
    entry = Repair(
        name=name,
        tier=tier,
        action=action,
        summary=summary,
        function=apply,
        precondition=precondition,
        detector=detector,
        place_ro=place_ro,
    )
    _REPAIRS[name] = entry
    if standing is None:
        # Taken out again if the module registering it fails to import.
        REPAIRS.added(_REPAIRS, name, owner=apply)
    return entry


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


def registered_repairs() -> dict[str, Repair]:
    """Every registered repair by name; the first call imports the package's modules."""
    REPAIRS.load()
    return dict(sorted(_REPAIRS.items()))


def repair_named(name: str) -> Repair | None:
    REPAIRS.load()
    return _REPAIRS.get(str(name or ""))


def unregister_repair(name: str) -> None:
    """Remove a repair (tests that register one of their own)."""
    _REPAIRS.pop(name, None)


def outcome(
    status: str,
    outcome_ro: str,
    *,
    changed: Mapping[str, Any] | None = None,
    letter_subject_ro: str | None = None,
) -> dict[str, Any]:
    """What a repair returns: its status, the decision's outcome in the Owner's words, what
    changed (recorded in the event), and for an applied repair the subject of his letter."""
    if status not in (APPLIED, NOTHING_TO_DO, DECLINED):
        raise ValueError(f"unknown repair status {status!r}")
    return {
        "status": status,
        "outcome_ro": outcome_ro,
        "changed": dict(changed or {}),
        "letter_subject_ro": letter_subject_ro,
    }


def finding(
    key: str,
    repair: str,
    *,
    observation: str,
    evidence: Mapping[str, Any],
    params: Mapping[str, Any] | None = None,
    fingerprint: str,
    scope: str = "COMPANY",
    decision: str = "ITERATE",
    confidence: str = "HIGH",
) -> dict[str, Any]:
    """One matter a detector raises, in the shape `command.findings` gives the Director, with
    the repair that answers it. ``fingerprint`` names this case: a case already decided is not
    offered again (`desk.repair_matters`), so the same 167 runs are one decision, not one per
    loop."""
    return {
        "matter_key": key,
        "scope": scope,
        "observation": observation,
        "evidence": dict(evidence),
        "suggested_decision": decision,
        "action": repair,
        "owner_role": "Director",
        "confidence": confidence,
        "channel_id": None,
        "review_after_videos": None,
        "repair": {"name": repair, "params": dict(params or {}), "fingerprint": fingerprint},
    }


__all__ = [
    "APPLIED",
    "DECLINED",
    "NOTHING_TO_DO",
    "REPAIRS",
    "REPAIR_TIERS",
    "Repair",
    "RepairContext",
    "RepairDetector",
    "RepairPrecondition",
    "RepairRun",
    "finding",
    "outcome",
    "register_repair",
    "registered_repairs",
    "repair_named",
    "unregister_repair",
]
