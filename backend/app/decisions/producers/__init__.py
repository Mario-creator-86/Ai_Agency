"""The studio's card producers, one module each (2026-10-09, P0).

A card that asks the Owner something needs, besides the code that proposes it, two entries in
the decisions core: what his accept runs (an *applier*, `services.APPLIERS`) and what the studio
reads to know the question went away (a *condition*, `services.CONDITIONS`, with the words his
«Am făcut-o» gets while it is still unmet, `services.MISSING_RO`). Until 2026-10-09 both were
written into the core's tables, which `register_applier` existed for and nothing called. The
self-repair plan adds about fifteen cards; each now lives in a module of its own here:

    # app/decisions/producers/close_film.py
    from app.decisions.services import register_applier, register_condition

    def apply_close_film(engine, spec, inner_command_id, words): ...
    def film_no_longer_stuck(session, card, params, settings): ...

    register_applier("close_film", apply_close_film)
    register_condition(
        "film_no_longer_stuck",
        film_no_longer_stuck,
        missing_ro="Lipsește: filmul așteaptă încă răspunsul tău.",
    )

The core imports every module of this package the first time any of its tables is read
(`PRODUCERS.load`, see `app.registry_loader`), so nothing has to list the modules anywhere.

The rules a producer module keeps:

- Importing it only defines and registers. Media and providers are imported inside the
  functions, as the core's own conditions do: the module is imported from inside the core.
- An applier, a condition and a condition's words (when a function) are functions defined at
  the top of the module, given by name, or lambdas written in the call; words may also be a
  string. Never a partial, an instance, a closure or a name imported from elsewhere, and never
  `CONDITIONS`/`MISSING_RO` written by hand: the money and Owner scans in
  tests/test_watchdog_passes.py read only those (review of 2026-10-09).
- An applier runs one of the Owner's OWN existing commands (his budget, his paid-media rule, a
  sheet command) under the inner command id it is given, and raises `DecisionApplyFailed`
  with a Romanian reason when the command refuses; it commits nothing then. It never buys,
  approves or moves money by itself: whatever spends is behind his existing gates (may_act,
  plan hashes, caps, his one-use yes).
- A condition only reads. It returns True when the question went away; an exception reads
  UNREADABLE and keeps the card open.
- A name is registered once: a second module registering the same applier or condition is
  refused at import and named in `PRODUCERS.errors`. A module whose import fails leaves
  nothing registered, whoever imported it (what it added before failing is taken out again,
  at the latest on the next read of a table), and the watchdog
  names it on every pass's log line and once per boot in a `studio.registry_module_failed`
  event.
- It never answers in the Owner's name: no `decide_owner_decision`, no `APPLIERS[...]`, and
  his commands (or ``issued_by=OWNER``) and the core's own appliers (`_apply_budget`,
  `sources.apply_runpod_infra`, `pods.start_copy`...) only inside a registered applier, which
  runs on his accept alone; such an applier imports them inside its function
  (tests/test_watchdog_passes.py, the Owner boundary scan).
"""

from __future__ import annotations

from app.registry_loader import PackageLoader

#: Imports this package's modules on the first read of the core's tables.
PRODUCERS = PackageLoader(__name__)

__all__ = ["PRODUCERS"]
