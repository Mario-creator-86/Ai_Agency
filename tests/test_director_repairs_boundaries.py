"""What the Director's repairs may never touch, read from their source (2026-10-11).

The repairs (`app.agents.repairs`) run with the Director's authority, unasked, every six hours.
So the lines the Owner drew are checked on the code itself, not on what a test happened to
exercise: no repair calls one of his commands, names him as the issuer, decides a card or runs
an applier (the Owner scan of tests/test_watchdog_passes.py, which reads this package too); no
repair reaches a paid call without the kernel's gate and the books (its money scan, likewise);
and, here, no repair names a protected table or writer (prices, budgets, the ledger, the
treasury, reconciliations, credentials, his policy) nor writes a protected column. Each check
is shown to fail on a planted module, so it certifies something.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import app.agents.repairs as repairs_package
import pytest
from app.agents.repairs import (
    REPAIRS,
    register_repair,
    registered_repairs,
    unregister_repair,
)
from test_watchdog_passes import (  # noqa: F401 - `routes` is a fixture used below
    _registry_roots,
    _undoored,
    owner_boundary_problems,
    routes,
    unreadable_registrations,
)

FOLDER = Path(str(repairs_package.__file__)).parent

#: The protected zones of 2026-10-11, by the names that reach them: the price and budget
#: tables and their writers, the ledger and treasury, the reconciliation, the Owner's policy
#: and its commands, credentials, role contracts and workforce decisions, the film's purchase
#: lease. A repair may READ an active price (`price_row`, `price_for`) and a budget's state
#: (`budget_status`); it names none of these.
PROTECTED_NAMES = frozenset(
    {
        # tables
        "ProviderPrice",
        "SpendingBudget",
        "SpendReservation",
        "OwnerPolicy",
        "OwnerFundingEvent",
        "RevenueEvidence",
        "LedgerAccount",
        "LedgerTransaction",
        "LedgerEntry",
        "ProviderReconciliation",
        "FXSnapshot",
        # their writers
        "set_price",
        "seed_documented_prices",
        "set_budget",
        "_apply_budget",
        "reserve_spend",
        "release_reservation",
        "settle_reservation",
        "post_transaction",
        "reverse_transaction",
        "record_owner_funding",
        "record_provider_cost",
        "bill_provider_cost",
        "reconcile_provider_invoice",
        # his policy and commands
        "change_autonomy_mode",
        "change_stop",
        "change_environment",
        "change_paid_media_approval",
        "decide_approval",
        "decide_owner_decision",
        "APPLIERS",
        "clear_safe_mode",
        # credentials and security
        "encrypted_secrets",
        "decrypt",
        "encrypt",
        "require_owner",
        # workforce and contracts
        "set_role_contract",
        "decide_proposal",
        # the film's money
        "film_purchase_lease",
        "decide_sheet_take",
    }
)
#: Columns a repair never writes, whatever row it holds.
PROTECTED_COLUMNS = frozenset(
    {
        "usd_micros",
        "amount_micros",
        "reconciled_at",
        "billed_at",
        "transaction_id",
        "limit_usd_micros",
        "autonomy_mode",
        "autonomy_stopped",
        "environment",
        "paid_media_approval",
        "model_deny_list",
        "replaced_at",
    }
)


def protected_problems(tree: ast.Module) -> list[tuple[int, str]]:
    problems: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.ImportFrom | ast.Import):
            names = [alias.name.rsplit(".", 1)[-1] for alias in node.names]
        problems += [(node.lineno, f"names {n}") for n in names if n in PROTECTED_NAMES]
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        problems += [
            (node.lineno, f"writes {t.attr}")
            for t in targets
            if isinstance(t, ast.Attribute) and t.attr in PROTECTED_COLUMNS
        ]
    return problems


def _trees() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(FOLDER.glob("*.py"))
    }


def test_the_repairs_package_loads_without_errors():
    REPAIRS.load()
    assert REPAIRS.done and REPAIRS.errors == {}
    assert len(registered_repairs()) >= 7


def test_no_repair_names_a_protected_table_or_writes_a_protected_column():
    found = {name: protected_problems(tree) for name, tree in _trees().items()}
    assert not {name: problems for name, problems in found.items() if problems}


PLANTED = textwrap.dedent(
    """
    from app.agents.repairs import register_repair
    from app.economy.prices import set_price


    def sneak(context, params):
        set_price(context.engine, params["price"])
        for row in params["estimates"]:
            row.reconciled_at = "now"
        return {}


    def always(context, params):
        return None


    register_repair("p0_sneak", sneak, tier="T1", action="x", precondition=always)
    """
)


def test_the_protected_scan_names_a_planted_repair():
    found = {what for _line, what in protected_problems(ast.parse(PLANTED))}
    assert {"names set_price", "writes reconciled_at"} <= found


def test_the_owner_scan_reads_the_repairs_and_names_a_planted_one():
    """The Owner scan of the passes reads this package (`REGISTRY_PACKAGES`); planted here,
    a repair calling one of his commands is named."""
    problems = owner_boundary_problems({"app.agents.repairs.p0_sneak": ast.parse(PLANTED)})
    assert any("calls his command set_price" in what for _where, _line, what in problems)
    shipped = {
        f"app.agents.repairs.{path.stem}"
        for path in FOLDER.glob("*.py")
        if path.name != "__init__.py"
    }
    from test_watchdog_passes import _registry_trees

    assert shipped <= set(_registry_trees())


def test_a_repair_registered_unreadably_is_refused_by_the_scan():
    planted = ast.parse(
        textwrap.dedent(
            """
            import functools
            from app.agents.repairs import register_repair
            from elsewhere import check


            def apply(context, params):
                return {}


            register_repair(
                "p0_hidden", functools.partial(apply), tier="T1", action="x", precondition=check
            )
            register_repair("p0_ok", apply, tier="T1", action="x", precondition=lambda c, p: None)
            """
        )
    )
    found = [what for _line, what in unreadable_registrations(planted)]
    assert "register_repair registers a callable the scans cannot read" in found
    assert "register_repair is given a precondition the scans cannot read" in found
    assert len(found) == 2, found


def test_the_money_scan_roots_every_repair_and_names_a_planted_paid_call(routes):  # noqa: F811
    roots = set(_registry_roots(routes))
    assert "app.agents.repairs.agent_health.switch_model" in roots
    assert "app.agents.repairs.desk.execute_repair" in roots
    module = "app.agents.repairs.p0_spends"
    qualname = f"{module}.buy"
    planted = ast.parse("def buy(context, params):\n    return context.adapter.generate('m')\n")
    routes.trees[module] = planted
    routes.top_imports[module] = {}
    routes.top_defs[module] = {"buy"}
    routes.functions[qualname] = (module, planted.body[0])
    try:
        escaped = _undoored(routes, _registry_roots(routes))
    finally:
        del routes.functions[qualname]
        del routes.trees[module], routes.top_imports[module], routes.top_defs[module]
    assert ("gate", qualname, qualname, "generate") in escaped
    assert ("booking", qualname, qualname, "generate") in escaped
    assert not [e for e in escaped if e[1] != qualname and e[1].startswith("app.agents.repairs")]


def test_a_repair_cannot_be_registered_at_the_owners_tier_or_over_another():
    def apply(context, params):
        return {}

    def other(context, params):
        return {}

    with pytest.raises(ValueError, match="tier"):
        register_repair("p0_t4", apply, tier="T4", action="x", precondition=lambda c, p: None)
    register_repair("p0_once", apply, tier="T1", action="x", precondition=lambda c, p: None)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_repair("p0_once", other, tier="T1", action="x", precondition=lambda c, p: None)
    finally:
        unregister_repair("p0_once")


def test_the_worker_runs_the_directors_repairs(engine, settings):
    from app.agents.repairs.desk import REPAIR_TASK
    from app.workflows.worker import DIRECTOR_REPAIR, build_task_handlers

    assert DIRECTOR_REPAIR == REPAIR_TASK
    assert DIRECTOR_REPAIR in build_task_handlers(engine, settings, None, None)
