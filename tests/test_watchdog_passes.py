"""Watchdog passes register from their own files (2026-10-09, P0).

The self-repair plan of 2026-10-09 adds about a dozen repairs to the watchdog: a stuck film
becomes a card, a paused RunPod is retried, a letter closes itself. Written into
`run_watchdog` they would all queue on one function, so each now lives in a module of
`app.workflows.passes` and registers itself; `run_watchdog` runs its built-in parts exactly as
before and then every registered pass.

What is proven here, with every provider faked and no network: the registered passes run
after the built-in parts, in their declared order, each under its own name in the result; a
pass that raises, or answers with something that is not a dict, is reported with its error
shape and the next pass still runs; the Owner's STOP AUTONOMIE still skips everything; a
name that is one of the watchdog's own keys, or taken by another pass, is refused; a module
dropped in the package is found without being listed anywhere; no function, lambda or
import-time code of a registered pass or card producer reaches a paid call without the
Owner's gate and the books on its path; every registration hands the scans a callable they
read (a function of the module or a lambda); and none of that code answers in his name.
What a static read cannot see (getattr, a name held in a variable) is said where it applies.
"""

from __future__ import annotations

import ast
import copy
import importlib
import sys
import textwrap
from pathlib import Path
from typing import Any
from uuid import uuid4

import app.workflows.passes as passes_package
import pytest
from app.models import OwnerPolicy
from app.workflows import watchdog
from app.workflows.passes import (
    BUILT_IN_RESULT_KEYS,
    PASSES,
    WatchdogContext,
    register_pass,
    registered_passes,
    unregister_pass,
    watchdog_pass,
)
from app.workflows.watchdog import run_watchdog
from sqlalchemy.orm import Session

PACKAGE = "app.workflows.passes"


@pytest.fixture
def passes(monkeypatch):
    """Registers test passes in a registry of their own, emptied of the shipped ones.

    Review of 2026-10-09: these tests read the exact lists of what ran and what was skipped,
    and the first shipped pass (`unbooked_spend`, WP6) turned three of them red; about a
    dozen more are planned. The shipped modules are imported first (into the real registry,
    restored afterwards), so the load the watchdog asks for finds the package done and puts
    nothing into this one; each shipped pass is tested by its own package."""
    PASSES.load()
    monkeypatch.setattr(passes_package, "_PASSES", {})
    names: list[str] = []

    def add(name: str, run, *, order: int, on_error=None) -> None:
        register_pass(name, run, order=order, on_error=on_error)
        names.append(name)

    try:
        yield add
    finally:
        for name in names:
            unregister_pass(name)


def _autonomy(engine, stopped: bool) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = stopped


def _run(engine, settings, *, stopped: bool = False, correlation_id: str = "") -> dict[str, Any]:
    _autonomy(engine, stopped)
    return run_watchdog(
        engine,
        settings,
        correlation_id=correlation_id or str(uuid4()),
        publisher_for=lambda _channel: None,
    )


# ------------------------------------------------------------------------ the order


def test_registered_passes_run_after_the_built_in_parts_in_their_declared_order(
    engine, settings, passes, monkeypatch
):
    calls: list[str] = []
    real_sweep = watchdog._sweep_failed_intermediates

    def sweep(*args, **kwargs):
        # The last built-in part: every registered pass must come after it.
        calls.append("intermediates")
        return real_sweep(*args, **kwargs)

    monkeypatch.setattr(watchdog, "_sweep_failed_intermediates", sweep)

    def recorder(name: str):
        def run(context: WatchdogContext) -> dict[str, Any]:
            assert context.engine is engine and context.settings is settings
            calls.append(name)
            return {"seen": name, "correlation_id": context.correlation_id}

        return run

    passes("p0_late", recorder("p0_late"), order=20)
    passes("p0_early", recorder("p0_early"), order=10)
    passes("p0_late_b", recorder("p0_late_b"), order=20)  # a tie runs by name

    result = _run(engine, settings, correlation_id="corr-p0")

    assert result["status"] == "COMPLETED"
    assert calls == ["intermediates", "p0_early", "p0_late", "p0_late_b"]
    assert result["p0_early"] == {"seen": "p0_early", "correlation_id": "corr-p0"}
    assert [entry["name"] for entry in result["passes"]["ran"]] == [
        "p0_early",
        "p0_late",
        "p0_late_b",
    ]
    assert all(entry["status"] == "OK" for entry in result["passes"]["ran"])
    assert result["passes"]["failed"] == []


def test_one_failing_pass_does_not_stop_the_next(engine, settings, passes):
    def broken(_context):
        raise RuntimeError("a pass that broke")

    def not_a_dict(_context):
        return ["a list"]

    seen: list[str] = []

    def after(_context):
        seen.append("after")
        return {"ok": True}

    passes("p0_broken", broken, order=1, on_error={"cards": []})
    passes("p0_not_a_dict", not_a_dict, order=2)
    passes("p0_after", after, order=3)

    result = _run(engine, settings)

    assert result["status"] == "COMPLETED"
    assert result["p0_broken"] == {"cards": [], "error": True, "error_type": "RuntimeError"}
    assert result["p0_not_a_dict"]["error"] is True
    assert result["p0_after"] == {"ok": True} and seen == ["after"]
    assert result["passes"]["failed"] == ["p0_broken", "p0_not_a_dict"]
    # The built-in parts' results are all still there.
    assert BUILT_IN_RESULT_KEYS <= set(result)


@pytest.mark.parametrize(
    "part",
    [
        "_fail_stuck_renders",
        "_reconcile_publications",
        "_lapsed_leases",
        "release_stale_reservations",
    ],
)
def test_a_built_in_part_that_raises_still_lets_the_registered_passes_run(
    engine, settings, passes, monkeypatch, caplog, part
):
    """Review of 2026-10-09: the first built-in parts have no try of their own, and an
    exception there (a locked database) left `run_watchdog` before the registered passes,
    which carry the money repairs (unbooked spend, GPU receipts, held RunPod scenes): skipped
    that cycle, and every cycle while the cause lasted, with nothing saying so. They run now,
    and the watchdog still ends with that part's exception, as it always did."""

    def broken(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(watchdog, part, broken)
    called: list[str] = []
    passes("p0_after_a_broken_part", lambda _context: called.append("ran") or {}, order=1)
    caplog.set_level("INFO", logger="studio.watchdog")

    with pytest.raises(RuntimeError, match="database is locked"):
        _run(engine, settings)

    assert called == ["ran"]
    (line,) = [r for r in caplog.records if r.getMessage() == "watchdog_built_in_part_failed"]
    assert line.error == "RuntimeError"
    assert line.registered_passes_ran == ["p0_after_a_broken_part"]


def test_the_built_in_keys_are_exactly_what_the_watchdog_writes(engine, settings, passes):
    """A built-in part added to `run_watchdog` must reserve its key, or a registered pass
    could take the same name and overwrite it."""
    passes("p0_extra", lambda _context: {}, order=1)
    result = _run(engine, settings)
    registered = {entry.name for entry in registered_passes()}
    assert set(result) - registered == BUILT_IN_RESULT_KEYS


# ------------------------------------------------------------------------- the stop


def test_stop_autonomie_still_skips_every_pass(engine, settings, passes):
    called: list[str] = []
    passes("p0_must_not_run", lambda _context: called.append("ran") or {}, order=1)

    result = _run(engine, settings, stopped=True)

    assert result["status"] == "SKIPPED" and "oprit" in result["reason"]
    assert called == []
    # The early return is the one it always was: no registered key, no summary.
    assert "p0_must_not_run" not in result and "passes" not in result


def test_a_stop_pressed_while_the_built_in_parts_run_skips_every_registered_pass(
    engine, settings, passes, monkeypatch
):
    """The stop is read once at the start of the built-in parts, and those can take minutes
    (the paid collection asks the vendors). A stop he presses meanwhile must still hold for
    the registered passes: a stopped studio is one in which nothing moves, repair included."""
    real_sweep = watchdog._sweep_failed_intermediates

    def sweep(engine_, settings_, correlation):
        _autonomy(engine_, True)  # his press, while the last built-in part runs
        return real_sweep(engine_, settings_, correlation)

    monkeypatch.setattr(watchdog, "_sweep_failed_intermediates", sweep)
    called: list[str] = []
    passes("p0_after_stop", lambda _context: called.append("ran") or {}, order=1)

    result = _run(engine, settings)

    assert called == []
    assert "p0_after_stop" not in result
    assert result["passes"]["ran"] == [] and result["passes"]["skipped"] == ["p0_after_stop"]


def test_a_stop_pressed_during_one_registered_pass_skips_the_ones_after_it(
    engine, settings, passes
):
    called: list[str] = []

    def presses_stop(context):
        called.append("first")
        _autonomy(context.engine, True)
        return {"ok": True}

    passes("p0_first", presses_stop, order=1)
    passes("p0_second", lambda _context: called.append("second") or {}, order=2)

    result = _run(engine, settings)

    assert called == ["first"]
    assert result["p0_first"] == {"ok": True} and "p0_second" not in result
    assert [entry["name"] for entry in result["passes"]["ran"]] == ["p0_first"]
    assert result["passes"]["skipped"] == ["p0_second"]


# ---------------------------------------------------- a module that did not load is said


def test_a_module_that_did_not_load_is_named_in_the_log_and_once_in_the_events(
    engine, settings, caplog, monkeypatch
):
    """The worker keeps nothing of the watchdog's answer, so `load_errors` in the result
    alone would be read by nobody: a producer that failed to import leaves its cards unable
    to close or apply, and the studio must say so where it is read, the log line of every
    pass and one event per module and boot."""
    from app.decisions.producers import PRODUCERS

    PRODUCERS.load()
    broken = "app.decisions.producers.p0_gone"
    monkeypatch.setitem(PRODUCERS.errors, broken, "SyntaxError: invalid syntax")
    # A fresh boot: nothing reported yet.
    monkeypatch.setattr(watchdog, "_REPORTED_LOAD_ERRORS", set(), raising=False)
    caplog.set_level("INFO", logger="studio.watchdog")

    first = _run(engine, settings)
    second = _run(engine, settings)

    assert broken in first["passes"]["load_errors"] and broken in second["passes"]["load_errors"]
    lines = [record for record in caplog.records if record.getMessage() == "watchdog_pass"]
    assert len(lines) == 2
    assert all(getattr(line, "registered_load_errors", None) == [broken] for line in lines)
    events = _registry_events(engine, broken)
    assert len(events) == 1
    assert events[0].payload == {
        "module": broken,
        "error": "SyntaxError: invalid syntax",
        "registry": "decision_producers",
    }
    assert len(events[0].aggregate_id) <= 36


def test_the_event_waits_while_he_has_the_studio_stopped(engine, settings, monkeypatch):
    """The watchdog changes nothing while the stop is set: a stop pressed while the built-in
    parts ran holds the event back, and the first pass after he lets the studio go writes it."""
    from app.decisions.producers import PRODUCERS

    PRODUCERS.load()
    broken = "app.decisions.producers.p0_gone_stopped"
    monkeypatch.setitem(PRODUCERS.errors, broken, "ImportError: lipsește")
    monkeypatch.setattr(watchdog, "_REPORTED_LOAD_ERRORS", set(), raising=False)
    real_sweep = watchdog._sweep_failed_intermediates

    def sweep(engine_, settings_, correlation):
        _autonomy(engine_, True)
        return real_sweep(engine_, settings_, correlation)

    monkeypatch.setattr(watchdog, "_sweep_failed_intermediates", sweep)
    stopped = _run(engine, settings)
    assert broken in stopped["passes"]["load_errors"]
    assert _registry_events(engine, broken) == []

    monkeypatch.setattr(watchdog, "_sweep_failed_intermediates", real_sweep)
    _run(engine, settings)
    assert len(_registry_events(engine, broken)) == 1


def _registry_events(engine, module: str) -> list[Any]:
    from app.models import DomainEvent
    from sqlalchemy import select

    with Session(engine) as session:
        return [
            event
            for event in session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "studio.registry_module_failed")
            ).all()
            if event.payload.get("module") == module
        ]


# ---------------------------------------------------------------- the registration


def test_a_name_of_the_watchdog_or_of_another_pass_is_refused(passes):
    with pytest.raises(ValueError, match="own keys"):
        register_pass("renders", lambda _context: {}, order=1)
    with pytest.raises(ValueError, match="lower case"):
        register_pass("Stuck-Films", lambda _context: {}, order=1)
    with pytest.raises(ValueError, match="whole-number"):
        register_pass("p0_order", lambda _context: {}, order=1.5)  # type: ignore[arg-type]

    def first(_context):
        return {}

    passes("p0_taken", first, order=1)
    with pytest.raises(ValueError, match="already registered"):
        register_pass("p0_taken", lambda _context: {}, order=2)
    # The same function again (its module imported twice) is not a second owner.
    register_pass("p0_taken", first, order=1)


def test_the_decorator_registers_and_returns_the_function():
    @watchdog_pass("p0_decorated", order=5, on_error={"cards": []})
    def decorated(_context):
        return {"cards": []}

    try:
        (entry,) = [p for p in registered_passes() if p.name == "p0_decorated"]
        assert entry.function is decorated and entry.order == 5 and entry.on_error == {"cards": []}
    finally:
        unregister_pass("p0_decorated")


PASS_SOURCE = textwrap.dedent(
    """
    from app.workflows.passes import watchdog_pass


    @watchdog_pass("p0_from_a_file", order=7)
    def from_a_file(context):
        return {"found": True}
    """
)


def test_a_pass_module_in_the_package_is_found_without_being_listed(tmp_path, engine, settings):
    folder = tmp_path / "passes_extra"
    folder.mkdir()
    (folder / "p0_file_pass.py").write_text(PASS_SOURCE, encoding="utf-8")
    (folder / "p0_file_broken.py").write_text("raise ImportError('stricat')\n", encoding="utf-8")
    original_path = list(passes_package.__path__)
    passes_package.__path__[:] = [*original_path, str(folder)]
    PASSES.reset()
    importlib.invalidate_caches()
    try:
        result = _run(engine, settings)
        assert result["p0_from_a_file"] == {"found": True}
        assert set(result["passes"]["load_errors"]) == {f"{PACKAGE}.p0_file_broken"}
    finally:
        passes_package.__path__[:] = original_path
        unregister_pass("p0_from_a_file")
        for name in [n for n in sys.modules if n.startswith(f"{PACKAGE}.p0_")]:
            del sys.modules[name]
        PASSES.reset()
        importlib.invalidate_caches()


HALF_PASS_SOURCE = textwrap.dedent(
    """
    from app.workflows.passes import watchdog_pass


    @watchdog_pass("p0_half_pass", order=3)
    def half(context):
        return {"half": True}


    raise RuntimeError("stricat după înregistrare")
    """
)


def test_a_pass_module_that_fails_after_registering_leaves_no_pass_behind(
    tmp_path, engine, settings
):
    """A module that failed to import is named in `load_errors`; what it registered before
    failing must not run as if it had loaded."""
    folder = tmp_path / "passes_half"
    folder.mkdir()
    (folder / "p0_half_pass.py").write_text(HALF_PASS_SOURCE, encoding="utf-8")
    original_path = list(passes_package.__path__)
    passes_package.__path__[:] = [*original_path, str(folder)]
    PASSES.reset()
    importlib.invalidate_caches()
    try:
        result = _run(engine, settings)
        assert set(result["passes"]["load_errors"]) == {f"{PACKAGE}.p0_half_pass"}
        assert "p0_half_pass" not in result
        assert "p0_half_pass" not in {entry.name for entry in registered_passes()}
    finally:
        passes_package.__path__[:] = original_path
        unregister_pass("p0_half_pass")
        for name in [n for n in sys.modules if n.startswith(f"{PACKAGE}.p0_")]:
            del sys.modules[name]
        PASSES.reset()
        importlib.invalidate_caches()


def test_the_shipped_passes_load_without_errors():
    PASSES.load()
    assert PASSES.done and PASSES.errors == {}


def test_pass_modules_import_media_and_providers_inside_their_functions():
    """Media imports workflows: a pass imports media and providers inside its function, as
    the watchdog's built-in parts do."""
    folder = Path(passes_package.__file__).parent
    for path in sorted(folder.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                assert not name.startswith(("app.media", "app.providers")), (
                    f"{path.name}:{node.lineno} imports {name} at the top"
                )


# ------------------------------------------------- no registered code reaches money unguarded
#
# The paid-path scan (tests/test_no_paid_path_escapes.py) starts from the routes, the worker's
# tasks, `run_watchdog` and the day, and follows the call graph it can read. A registered pass
# or a card producer is called through a registry, which the graph cannot follow; so every
# function of those two packages is a root of its own here, and so is every lambda and the
# import-time code of each module (review of 2026-10-09), under the same two checks: no paid
# adapter method without the Owner's gate on the path, and none without the books. A callable
# registered any other way is refused by `unreadable_registrations` below.

REGISTRY_PACKAGES = ("app.workflows.passes", "app.decisions.producers")


def _registry_roots(routes) -> list[str]:
    """Every function of every module of the two packages (their registries in `__init__` are
    reached from `run_watchdog` and the routes already), with each module's lambdas and its
    import-time code (`_add_module_level_roots`)."""
    prefixes = tuple(f"{package}." for package in REGISTRY_PACKAGES)
    return sorted(
        qualname
        for qualname, (module, _node) in routes.functions.items()
        if module.startswith(prefixes)
    )


def _import_time(body: list[ast.stmt]):
    """The statements of a module that run when it is imported and belong to none of its
    functions: everything but a function, and of a class its decorators, bases and body."""
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # a root already, its decorators and defaults included
        if isinstance(statement, ast.ClassDef):
            heads = [*statement.decorator_list, *statement.bases]
            yield from (ast.Expr(value=head) for head in heads)
            yield from (ast.Expr(value=keyword.value) for keyword in statement.keywords)
            yield from _import_time(statement.body)
            continue
        yield statement


class _WithoutLambdas(ast.NodeTransformer):
    """A lambda is a root of its own: a door in one must not open another."""

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        return ast.copy_location(ast.Constant(value=None), node)


def _as_function(name: str, args: ast.arguments, body: list[ast.stmt]) -> ast.FunctionDef:
    function = ast.FunctionDef(
        name=name, args=args, body=body, decorator_list=[], returns=None, type_params=[]
    )
    function.lineno, function.col_offset = (body[0].lineno, 0) if body else (1, 0)
    return ast.fix_missing_locations(function)


def _add_module_level_roots(routes, module: str, tree: ast.Module) -> list[str]:
    """Review of 2026-10-09: the roots were the packages' top-level functions only, so a pass,
    a condition, an applier or the words of a condition registered as a lambda, and whatever a
    module runs when it is imported, were never read: a pass that bought with no gate and no
    booking passed every check. Each lambda of the import-time code becomes a function of its
    own (``module.<lambda:LINE:COL>``) and so does the rest of that code (``module.<import>``).
    The qualified names added are returned (a planted module removes them again)."""
    statements = list(_import_time(tree.body))
    added: list[str] = []
    for statement in statements:
        for sub in ast.walk(statement):
            if isinstance(sub, ast.Lambda):
                name = f"<lambda:{sub.lineno}:{sub.col_offset}>"
                body: list[ast.stmt] = [ast.copy_location(ast.Return(value=sub.body), sub.body)]
                routes.functions[f"{module}.{name}"] = (module, _as_function(name, sub.args, body))
                added.append(f"{module}.{name}")
    code = [_WithoutLambdas().visit(copy.deepcopy(statement)) for statement in statements]
    nothing = ast.arguments(
        posonlyargs=[], args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]
    )
    routes.functions[f"{module}.<import>"] = (
        module,
        _as_function("<import>", nothing, code or [ast.Pass()]),
    )
    added.append(f"{module}.<import>")
    return added


@pytest.fixture(scope="module")
def routes():
    from test_no_paid_path_escapes import _RouteSource

    source = _RouteSource()
    prefixes = tuple(f"{package}." for package in REGISTRY_PACKAGES)
    for module, tree in list(source.trees.items()):
        if module.startswith(prefixes):
            _add_module_level_roots(source, module, tree)
    return source


def _undoored(routes, roots: list[str]) -> list[tuple[str, str, str, str]]:
    from test_no_paid_path_escapes import CHECKS, _Graph, undoored_paths

    graph = _Graph(routes)
    return [
        (check, root, site, method)
        for check, (doors, methods) in CHECKS.items()
        for root in roots
        for site, method, _chain in undoored_paths(graph, root, doors, methods)
    ]


def test_no_registered_pass_or_producer_reaches_a_paid_call_without_its_doors(routes):
    escaped = _undoored(routes, _registry_roots(routes))
    assert not escaped, "\n".join(
        f"{check}: {root} reaches {site} .{method}()" for check, root, site, method in escaped
    )


def test_the_registry_scan_names_a_planted_paid_call(routes):
    """A check that cannot fail certifies nothing: a pass module whose function calls a paid
    adapter method with no gate and no booking on its path is named, twice."""
    module = "app.workflows.passes.p0_planted"
    qualname = f"{module}.buy"
    planted = ast.parse("def buy(context):\n    return context.adapter.create_generation({})\n")
    routes.trees[module] = planted
    routes.top_imports[module] = {}
    routes.top_defs[module] = {"buy"}
    routes.functions[qualname] = (module, planted.body[0])
    try:
        escaped = _undoored(routes, _registry_roots(routes))
    finally:
        del routes.functions[qualname]
        del routes.trees[module], routes.top_imports[module], routes.top_defs[module]
    assert ("gate", qualname, qualname, "create_generation") in escaped
    assert ("booking", qualname, qualname, "create_generation") in escaped


PLANTED_LAMBDA_PASS = textwrap.dedent(
    """
    from app.workflows.passes import register_pass

    ADAPTER = None

    register_pass(
        "p0_lambda", lambda context: context.adapter.create_generation({}), order=1
    )
    AT_IMPORT = ADAPTER.generate_image({})
    """
)

PLANTED_LAMBDA_PRODUCER = textwrap.dedent(
    """
    from app.decisions.services import register_condition

    register_condition(
        "p0_lambda_cleared",
        lambda session, row, params, settings: bool(params["adapter"].synthesize({})),
        missing_ro=lambda session, row, params: params["adapter"].generate({}),
    )
    """
)


def test_the_registry_scan_names_a_paid_call_registered_as_a_lambda(routes):
    """Review of 2026-10-09: the roots were the packages' top-level functions only, so a pass
    or a condition registered as a lambda, and code that runs when the module is imported,
    were never scanned; a pass buying with no gate and no booking passed every check. Each
    lambda of a module's import-time code is now a root of its own, and so is that code."""
    planted = {
        "app.workflows.passes.p0_lambda": ast.parse(PLANTED_LAMBDA_PASS),
        "app.decisions.producers.p0_lambda": ast.parse(PLANTED_LAMBDA_PRODUCER),
    }
    added: list[str] = []
    for module, tree in planted.items():
        routes.trees[module] = tree
        routes.top_imports[module] = routes._imports(module, tree.body)
        routes.top_defs[module] = {"ADAPTER", "AT_IMPORT"} if "passes" in module else set()
        added += _add_module_level_roots(routes, module, tree)
    try:
        escaped = _undoored(routes, _registry_roots(routes))
    finally:
        for qualname in added:
            del routes.functions[qualname]
        for module in planted:
            del routes.trees[module], routes.top_imports[module], routes.top_defs[module]
    found = {
        (check, root.rsplit(".", 1)[-1].split(":")[0], method)
        for check, root, _site, method in escaped
        if ".p0_lambda." in root
    }
    for check in ("gate", "booking"):
        assert (check, "<lambda", "create_generation") in found  # the pass
        assert (check, "<lambda", "synthesize") in found  # the condition
        assert (check, "<lambda", "generate") in found  # what his DONE is told
        assert (check, "<import>", "generate_image") in found  # what runs at import


def test_the_shipped_modules_import_time_code_is_scanned_too(routes):
    """The lambda and import-time roots are made for every module of the two packages, not
    only for planted ones."""
    shipped = [
        module
        for module in routes.trees
        if module.startswith(tuple(f"{package}." for package in REGISTRY_PACKAGES))
    ]
    roots = set(_registry_roots(routes))
    for module in shipped:
        assert f"{module}.<import>" in roots, module


# ------------------------------------------------ no registered code answers in his name
#
# Review of 2026-10-09: the scan above finds a vendor call with no gate or booking on its
# path; it cannot see code that acts AS the Owner, and his yes is what moves money policy.
# `decide_owner_decision` records his answer and runs the card's applier; an applier runs one
# of his own commands (`_apply_paid_media` -> `change_paid_media_approval(issued_by=OWNER)`);
# and those commands believe whoever names him. A pass that accepted its own «start the GPU»
# card, or called the paid-media applier itself, would spend on a yes he never pressed with
# every check above green. So, read from the source of every module of the two packages:
#
# - nothing names `decide_owner_decision` or `APPLIERS`: only the decisions router decides a
#   card, and a producer adds its applier with `register_applier`, never reads the table;
# - his commands, and his name given as the issuer, appear only inside a registered applier
#   (and the helpers only appliers reach): that code runs on his accept alone;
# - so do the core's own appliers and what they hand his accept to (`CORE_APPLIERS`: his
#   budget, his paid-media rule, the autonomy mode, the RunPod GPU switch, the paid copy pod),
#   named in any way, a top-level import included (second review of 2026-10-09);
# - a registered applier is reached only through its registration, never imported or called.
#
# And across the whole application, only the decisions core and its router name the two.
# What a static read cannot see: a name reached through getattr or a variable holding "owner".

APP_DIR = Path(passes_package.__file__).resolve().parents[2]

#: His commands: each IS his answer (the route serving his page calls it once it authenticated
#: him). Name -> the module that defines it, checked below so a rename cannot empty the list.
OWNER_COMMANDS = {
    "decide_approval": "app.services",
    "change_environment": "app.services",
    "change_stop": "app.services",
    "change_autonomy_mode": "app.services",
    "change_paid_media_approval": "app.services",
    "set_budget": "app.economy.budget",
    "set_price": "app.economy.prices",
    "record_owner_funding": "app.economy.services",
    "set_storyboard_production": "app.media.production_policy",
    "set_voice_binding": "app.media.production_policy",
    "set_identity_locks": "app.media.production_policy",
    "approve_model_fallback": "app.media.production_policy",
    "decide_identity_change": "app.media.production_policy",
    "set_scene_model": "app.media.shooting_sheet",
    "decide_sheet_take": "app.media.shooting_sheet",
    "allow_repair_retry": "app.media.blocker_repair",
    "close_film": "app.media.film_close",
}
#: What decides a card, or runs what his accept runs.
OWNER_ANSWER = frozenset({"decide_owner_decision", "APPLIERS"})


def _core_appliers() -> dict[str, str]:
    """The core's own appliers, name -> module, read from the ``APPLIERS`` literal in
    app/decisions/services.py: a function given by name, a factory (`_apply_policy`,
    `_from_sources`), and the functions of app.decisions.sources that `_from_sources` names.

    Second review of 2026-10-09: the scan knew his top-level commands and the table, and none
    of these. Each acts as his accept (``set_by``/``issued_by=OWNER`` inside, or a paid copy
    pod), and none is a PAID_METHOD the money scan would see."""
    path = APP_DIR / "decisions" / "services.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    (table,) = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "APPLIERS"
        and isinstance(node.value, ast.Dict)
    ]
    found: dict[str, str] = {}
    for value in table.values:
        if isinstance(value, ast.Name):
            found[value.id] = "app.decisions.services"
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            found[value.func.id] = "app.decisions.services"
            if value.func.id == "_from_sources":
                for argument in value.args:
                    assert isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    found[argument.value] = "app.decisions.sources"
        else:
            raise AssertionError(f"APPLIERS holds {ast.dump(value)}: teach _core_appliers it")
    return found


#: The core's appliers, and what they hand his accept to that OWNER_COMMANDS does not list
#: (the unsent RunPod release, the copy pod that costs money). Named anywhere in a pass or a
#: producer outside a registered applier, they are his yes given by someone else.
CORE_APPLIERS = {
    **_core_appliers(),
    "apply_release": "app.media.runpod_unsent",
    "start_copy": "app.providers.runpod.pods",
}
#: The keywords by which a command is told who issued it.
ISSUER_KEYWORDS = frozenset({"issued_by", "set_by", "decided_by"})

#: (where: module or module.function, line, what)
Problem = tuple[str, int, str]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _names_him(value: ast.expr) -> bool:
    """``"owner"``, or the constant ``OWNER`` however it is reached."""
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str) and value.value.strip().lower() == "owner"
    if isinstance(value, ast.Name):
        return value.id.upper() == "OWNER"
    if isinstance(value, ast.Attribute):
        return value.attr.upper() == "OWNER"
    return False


def _walk(node: ast.AST, skip: frozenset[int] = frozenset()):
    """`ast.walk` that does not enter the nodes in ``skip`` (an applier's registration)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if id(current) in skip:
            continue
        yield current
        stack.extend(ast.iter_child_nodes(current))


def _owner_acts(node: ast.AST, skip: frozenset[int] = frozenset()) -> list[tuple[int, str]]:
    acts: list[tuple[int, str]] = []
    for sub in _walk(node, skip):
        if not isinstance(sub, ast.Call):
            continue
        callee = _callee(sub)
        if callee in OWNER_COMMANDS:
            acts.append((sub.lineno, f"calls his command {callee}"))
        for keyword in sub.keywords:
            if keyword.arg in ISSUER_KEYWORDS and _names_him(keyword.value):
                acts.append((sub.lineno, f"names him as the issuer ({keyword.arg}=)"))
    return acts


def _named(node: ast.AST, skip: frozenset[int] = frozenset()):
    """Every name the code uses (a bare name, an attribute, an import), never a string."""
    for sub in _walk(node, skip):
        if isinstance(sub, ast.Name):
            yield sub.id, sub.lineno
        elif isinstance(sub, ast.Attribute):
            yield sub.attr, sub.lineno
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                yield alias.name.rsplit(".", 1)[-1], sub.lineno


def _registrations(tree: ast.Module) -> tuple[set[str], frozenset[int], list[tuple[int, str]]]:
    """The functions a module registers as appliers (by name), the ids of the expressions
    given to `register_applier` (a lambda among them is an applier), and what it registers
    in a way the scan cannot read."""
    names: set[str] = set()
    given_ids: set[int] = set()
    unreadable: list[tuple[int, str]] = []
    for sub in ast.walk(tree):
        if not (isinstance(sub, ast.Call) and _callee(sub) == "register_applier"):
            continue
        given = sub.args[1] if len(sub.args) > 1 else None
        for keyword in sub.keywords:
            if keyword.arg == "applier":
                given = keyword.value
        if isinstance(given, ast.Name):
            names.add(given.id)
            given_ids.add(id(given))
        elif isinstance(given, ast.Lambda):
            given_ids.add(id(given))
        else:
            unreadable.append((sub.lineno, "registers an applier the scan cannot read"))
    return names, frozenset(given_ids), unreadable


#: The registrars: name -> (position, keyword) of the callable they are given. `watchdog_pass`
#: is given its function by decorating it.
REGISTRARS = {
    "register_pass": (1, "run"),
    "register_applier": (1, "applier"),
    "register_condition": (1, "condition"),
    "watchdog_pass": None,
}
#: The tables behind the registrars: written by hand, an entry is one no scan has read.
#: (`APPLIERS` is refused above, with what decides a card.)
REGISTRY_TABLES = frozenset({"_PASSES", "CONDITIONS", "MISSING_RO", "_register"})


def _argument(call: ast.Call, position: int | None, keyword: str) -> ast.expr | None:
    for given in call.keywords:
        if given.arg == keyword:
            return given.value
    if position is None or any(isinstance(arg, ast.Starred) for arg in call.args):
        return None
    return call.args[position] if len(call.args) > position else None


def unreadable_registrations(tree: ast.Module) -> list[tuple[int, str]]:
    """What a module of the two packages registers in a way the scans cannot read.

    Review of 2026-10-09: the money scan's roots are the module's functions and its lambdas,
    and the Owner scan reads the same; a callable registered any other way (a partial, an
    instance, a closure made by a factory, a name imported from elsewhere, a lambda kept in a
    variable), the registrar called under another name, or a table written by hand, is a pass
    or a card both would certify without having read it. Readable: a function defined at the
    top of the module, given by its name or decorated, or a lambda written in the call; the
    words of a condition are also readable as a string, or a name bound to one at the top."""
    defs = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    strings = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    decorators = {
        id(decorator)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    }

    def readable(value: ast.expr | None) -> bool:
        return isinstance(value, ast.Lambda) or (isinstance(value, ast.Name) and value.id in defs)

    def readable_words(value: ast.expr | None) -> bool:
        return (
            readable(value)
            or (isinstance(value, ast.Constant) and isinstance(value.value, str))
            or (isinstance(value, ast.Name) and value.id in strings)
        )

    problems: list[tuple[int, str]] = []
    calling: set[int] = set()
    for sub in ast.walk(tree):
        if not isinstance(sub, ast.Call) or _callee(sub) not in REGISTRARS:
            continue
        callee = str(_callee(sub))
        calling.add(id(sub.func))
        where = REGISTRARS[callee]
        if where is None:
            if id(sub) not in decorators:
                problems.append(
                    (
                        sub.lineno,
                        f"{callee} decorates something other than a function of the module",
                    )
                )
            continue
        if not readable(_argument(sub, *where)):
            problems.append((sub.lineno, f"{callee} registers a callable the scans cannot read"))
        if callee == "register_condition" and not readable_words(
            _argument(sub, None, "missing_ro")
        ):
            problems.append(
                (sub.lineno, f"{callee} says what is missing with something the scans cannot read")
            )
    for sub in ast.walk(tree):
        if isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                name = alias.name.rsplit(".", 1)[-1]
                if name in REGISTRARS and alias.asname not in (None, name):
                    problems.append((sub.lineno, f"imports {name} as {alias.asname}"))
                if name in REGISTRY_TABLES:
                    problems.append((sub.lineno, f"names the registry table {name}"))
            continue
        if isinstance(sub, ast.Name):
            name, own = sub.id, False
        elif isinstance(sub, ast.Attribute):
            name, own = sub.attr, True
        else:
            continue
        if name in REGISTRARS and id(sub) not in calling:
            problems.append((sub.lineno, f"uses {name} other than by calling it"))
        # A helper of the module's own may be called `_register`; the core's is reached
        # only by importing it or through the module (`services._register`).
        if name in REGISTRY_TABLES and (name != "_register" or own):
            problems.append((sub.lineno, f"names the registry table {name}"))
    return problems


def _closure(start: set[str], calls: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(calls.get(name, ()))
    return seen


def owner_boundary_problems(modules: dict[str, ast.Module]) -> list[Problem]:
    problems: list[Problem] = []
    registered = {module: _registrations(tree) for module, tree in modules.items()}
    applier_names = {name for names, _ids, _bad in registered.values() for name in names}
    for module, tree in modules.items():
        appliers, given, unreadable = registered[module]
        problems += [(module, line, what) for line, what in unreadable]
        # Nothing decides a card or runs an applier from the table.
        problems += [
            (module, line, f"names {name}") for name, line in _named(tree) if name in OWNER_ANSWER
        ]
        defs = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # A registered applier is reached only through its registration.
        for name, line in _named(tree, given):
            if name in applier_names and name not in defs:
                problems.append((module, line, f"reaches the applier {name} of another module"))
        calls = {
            name: {
                sub.id
                for sub in ast.walk(node)
                if isinstance(sub, ast.Name) and sub.id in defs and sub.id != name
            }
            for name, node in defs.items()
        }
        his = _closure(appliers & set(defs), calls)
        for root in sorted(set(defs) - his):
            for reached in sorted(_closure({root}, calls)):
                where = f"{module}.{root}"
                if reached in appliers:
                    problems.append((where, defs[reached].lineno, f"reaches the applier {reached}"))
                problems += [
                    (where, line, f"{reached}: {act}") for line, act in _owner_acts(defs[reached])
                ]
                problems += [
                    (where, line, f"{reached}: {act}")
                    for line, act in _core_applier_named(defs[reached], set(defs))
                ]
        # Module-level code (a class, a table, a call at import) never acts as him either,
        # except inside a lambda given to `register_applier`.
        for statement in tree.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            problems += [(module, line, act) for line, act in _owner_acts(statement, given)]
            problems += [
                (module, line, f"reaches the applier {name}")
                for name, line in _named(statement, given)
                if name in appliers
            ]
            problems += [
                (module, line, act)
                for line, act in _core_applier_named(statement, set(defs), given)
            ]
    return problems


def _core_applier_named(
    node: ast.AST, own: set[str], skip: frozenset[int] = frozenset()
) -> list[tuple[int, str]]:
    """Every naming of one of the core's appliers (a call, an attribute such as
    ``services._apply_budget``, an import, a value handed on). A bare name the module defines
    as a function itself is its own, read like any other; reached through a module or
    imported, it is the core's."""
    found: list[tuple[int, str]] = []
    for sub in _walk(node, skip):
        if isinstance(sub, ast.Name):
            names = [] if sub.id in own else [sub.id]
        elif isinstance(sub, ast.Attribute):
            names = [sub.attr]
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            names = [alias.name.rsplit(".", 1)[-1] for alias in sub.names]
        else:
            continue
        found += [
            (sub.lineno, f"names {name}, which acts on his accept")
            for name in names
            if name in CORE_APPLIERS
        ]
    return found


def _registry_trees() -> dict[str, ast.Module]:
    import app.decisions.producers as producers_package

    trees: dict[str, ast.Module] = {}
    for package in (passes_package, producers_package):
        folder = Path(str(package.__file__)).parent
        for path in sorted(folder.rglob("*.py")):
            parts = path.relative_to(folder).with_suffix("").parts
            dotted = ".".join(part for part in parts if part != "__init__")
            module = f"{package.__name__}.{dotted}" if dotted else package.__name__
            trees[module] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return trees


def test_no_registered_pass_or_producer_answers_in_the_owners_name():
    problems = owner_boundary_problems(_registry_trees())
    assert not problems, "\n".join(f"{where}:{line} {what}" for where, line, what in problems)


def test_every_registration_hands_the_scans_a_callable_they_read():
    """The two scans above read a registered callable from the source: a function of the
    module, or a lambda (a root of its own). Anything else (a partial, an instance, a name
    imported from elsewhere, the registrar under another name, a table written by hand) is
    a pass or a card the scans would certify without having read it."""
    problems = [
        (module, line, what)
        for module, tree in _registry_trees().items()
        if module not in REGISTRY_PACKAGES  # the registries themselves
        for line, what in unreadable_registrations(tree)
    ]
    assert not problems, "\n".join(f"{where}:{line} {what}" for where, line, what in problems)


def test_only_the_decisions_core_and_its_router_decide_a_card_or_run_an_applier():
    allowed = {"app/decisions/services.py", "app/decisions/router.py"}
    found: dict[str, list[int]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        relative = path.relative_to(APP_DIR.parent).as_posix()
        if relative in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if not any(name in source for name in OWNER_ANSWER):
            continue
        for name, line in _named(ast.parse(source, filename=str(path))):
            if name in OWNER_ANSWER:
                found.setdefault(relative, []).append(line)
    assert not found, found


def test_every_owner_command_the_scan_names_still_exists():
    """A renamed command would leave the scan looking for a name nobody calls."""
    for name, module in OWNER_COMMANDS.items():
        path = APP_DIR.parent / f"{module.replace('.', '/')}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in defined, f"{module}.{name} is gone: update OWNER_COMMANDS"


PLANTED_PASS = textwrap.dedent(
    """
    from app.decisions.services import APPLIERS, OWNER, decide_owner_decision
    from app.services import change_paid_media_approval


    def accepts_its_own_card(context):
        return decide_owner_decision(context.engine, "card", None, issued_by="owner")


    def runs_the_paid_media_applier(context):
        return APPLIERS["paid_media_approval"](context.engine, {}, "inner", {})


    def changes_his_rule(context):
        return change_paid_media_approval(context.engine, None, issued_by=OWNER)


    def names_him(context):
        return some_command(context.engine, issued_by="Owner")
    """
)

PLANTED_PRODUCER = textwrap.dedent(
    """
    from app.decisions.services import OWNER, register_applier, register_condition
    from app.services import change_paid_media_approval


    def _change(engine, spec):
        return change_paid_media_approval(engine, spec, issued_by=OWNER)


    def apply_rule(engine, spec, inner, words):
        return {"command": "SetPaidMediaApproval", "result": _change(engine, spec)}


    def rule_cleared(session, row, params, settings):
        return True


    register_applier("p0_rule", apply_rule)
    register_applier(
        "p0_inline",
        lambda engine, spec, inner, words: change_paid_media_approval(
            engine, spec, issued_by=OWNER
        ),
    )
    register_condition("p0_rule_cleared", rule_cleared, missing_ro="Lipsește: proba.")
    """
)

PLANTED_PRODUCER_ABUSE = textwrap.dedent(
    """

    def propose(engine):
        return apply_rule(engine, {}, "x", {})


    def cleared_by_acting(session, row, params, settings):
        return _change(session.bind, {})


    AT_IMPORT = change_paid_media_approval(None, None, issued_by=OWNER)
    """
)

PLANTED_PASS_REACHING_AN_APPLIER = textwrap.dedent(
    """
    from app.decisions.producers.p0_rule import apply_rule


    def auto(context):
        return apply_rule(context.engine, {}, "x", {})
    """
)


def _whats(problems: list[Problem]) -> set[tuple[str, str]]:
    return {(where, what) for where, _line, what in problems}


def test_the_owner_scan_names_a_pass_that_answers_in_his_name():
    """A check that cannot fail certifies nothing: the four ways a pass could act as him."""
    module = "app.workflows.passes.p0_planted"
    found = _whats(owner_boundary_problems({module: ast.parse(PLANTED_PASS)}))
    assert (module, "names decide_owner_decision") in found
    assert (module, "names APPLIERS") in found
    assert (
        f"{module}.changes_his_rule",
        "changes_his_rule: calls his command change_paid_media_approval",
    ) in found
    assert (
        f"{module}.changes_his_rule",
        "changes_his_rule: names him as the issuer (issued_by=)",
    ) in found
    assert (f"{module}.names_him", "names_him: names him as the issuer (issued_by=)") in found
    assert (
        f"{module}.accepts_its_own_card",
        "accepts_its_own_card: names him as the issuer (issued_by=)",
    ) in found


def test_the_owner_scan_lets_an_applier_act_for_him_and_nothing_else():
    producer = "app.decisions.producers.p0_rule"
    # His command inside a registered applier, its helper, or a lambda registered as one:
    # that runs on his accept alone.
    assert owner_boundary_problems({producer: ast.parse(PLANTED_PRODUCER)}) == []

    found = _whats(
        owner_boundary_problems({producer: ast.parse(PLANTED_PRODUCER + PLANTED_PRODUCER_ABUSE)})
    )
    assert (f"{producer}.propose", "reaches the applier apply_rule") in found
    assert (
        f"{producer}.cleared_by_acting",
        "_change: calls his command change_paid_media_approval",
    ) in found
    assert (producer, "calls his command change_paid_media_approval") in found
    assert (producer, "names him as the issuer (issued_by=)") in found

    pass_module = "app.workflows.passes.p0_reaches"
    found = _whats(
        owner_boundary_problems(
            {
                producer: ast.parse(PLANTED_PRODUCER),
                pass_module: ast.parse(PLANTED_PASS_REACHING_AN_APPLIER),
            }
        )
    )
    assert (pass_module, "reaches the applier apply_rule of another module") in found


PLANTED_PASS_RUNNING_CORE_APPLIERS = textwrap.dedent(
    """
    from app.decisions import services, sources
    from app.workflows.passes import watchdog_pass


    @watchdog_pass("p0_core", order=1)
    def auto(context):
        from app.decisions.services import _apply_paid_media
        from app.media.runpod_unsent import apply_release
        from app.providers.runpod import pods

        services._apply_budget(context.engine, {"period": "DAILY", "limit_usd": "500"}, "i", {})
        services._apply_policy("autonomy_mode")(context.engine, {"to": "AUTONOMOUS_CEO"}, "i", {})
        _apply_paid_media(context.engine, {"to": "AUTO"}, "i", {})
        sources.apply_runpod_infra(context.engine, {"to": True, "integration_id": "x"}, "i", {})
        sources.apply_runpod_mirror_copy(context.engine, {"max_usd": "5"}, "i", {})
        apply_release(context.engine, {}, "i")
        pods.start_copy(context.engine, None, "x", max_minutes=60, max_usd="5")
        return {}


    LATER = services._from_sources("apply_sheet_local_move")
    """
)


def test_the_owner_scan_names_a_pass_that_runs_an_applier_of_the_core():
    """Second review of 2026-10-09: the scan knew his top-level commands and the table, not
    the core's own appliers or what they hand his accept to. Each acts as his yes (``set_by``
    or ``issued_by=OWNER`` inside): a pass calling them would raise his budget to 500 USD,
    switch the studio to AUTONOMOUS_CEO, let agents start the GPU and start a paid copy pod
    on every cycle, with every check here green."""
    module = "app.workflows.passes.p0_core"
    found = _whats(owner_boundary_problems({module: ast.parse(PLANTED_PASS_RUNNING_CORE_APPLIERS)}))
    for name in (
        "_apply_budget",
        "_apply_policy",
        "_apply_paid_media",
        "apply_runpod_infra",
        "apply_runpod_mirror_copy",
        "apply_release",
        "start_copy",
    ):
        assert (f"{module}.auto", f"auto: names {name}, which acts on his accept") in found, name
    assert (module, "names _from_sources, which acts on his accept") in found
    # A function of the module's own under the same name does not hide the core's.
    shadow = (
        "def start_copy(context):\n"
        "    from app.providers.runpod import pods\n"
        "    return pods.start_copy(context.engine)\n"
    )
    found = _whats(owner_boundary_problems({module: ast.parse(shadow)}))
    assert (
        f"{module}.start_copy",
        "start_copy: names start_copy, which acts on his accept",
    ) in found


PLANTED_PRODUCER_HANDING_TO_THE_CORE = textwrap.dedent(
    """
    from app.decisions.services import register_applier, register_condition


    def apply_raise(engine, spec, inner, words):
        from app.decisions.services import _apply_budget

        return _apply_budget(engine, spec, inner, words)


    def raise_cleared(session, row, params, settings):
        from app.decisions import sources

        sources.apply_runpod_infra(session.bind, {"to": True}, "x", {})
        return True


    register_applier("p0_raise", apply_raise)
    register_applier(
        "p0_raise_inline",
        lambda engine, spec, inner, words: __import__("x")._apply_budget(engine, spec, inner, {}),
    )
    register_condition("p0_raise_cleared", raise_cleared, missing_ro="Lipsește: proba.")
    """
)


def test_a_registered_applier_may_hand_his_accept_to_an_applier_of_the_core():
    """His accept runs a registered applier, which may hand it on to the core's own; nothing
    else in the module may (here a condition, which the studio runs by itself)."""
    producer = "app.decisions.producers.p0_raise"
    found = _whats(
        owner_boundary_problems({producer: ast.parse(PLANTED_PRODUCER_HANDING_TO_THE_CORE)})
    )
    assert found == {
        (
            f"{producer}.raise_cleared",
            "raise_cleared: names apply_runpod_infra, which acts on his accept",
        )
    }


def test_the_core_appliers_the_scan_names_are_the_core_table_and_still_exist():
    """The list is read from the core's table; a renamed function, a new factory or a new
    delegate must not leave the scan looking for names nobody calls."""
    import inspect

    from app.decisions import services, sources

    for name, module in CORE_APPLIERS.items():
        path = APP_DIR.parent / f"{module.replace('.', '/')}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert name in defined, f"{module}.{name} is gone: update CORE_APPLIERS"
    for kind, applier in dict.items(services.APPLIERS):
        if applier.__module__ != services.__name__:
            continue  # a producer's: the scan reads its module
        assert applier.__qualname__.split(".")[0] in CORE_APPLIERS, kind
        for value in inspect.getclosurevars(applier).nonlocals.values():
            if isinstance(value, str) and callable(getattr(sources, value, None)):
                assert value in CORE_APPLIERS, (kind, value)


PLANTED_READABLE = textwrap.dedent(
    """
    from app.decisions.services import register_condition
    from app.workflows.passes import register_pass, watchdog_pass

    WORDS = "Lipsește: proba."


    def tidy(context):
        return {}


    @watchdog_pass("p0_decorated", order=2)
    def decorated(context):
        return {}


    def cleared(session, row, params, settings):
        return True


    register_pass("p0_tidy", tidy, order=1)
    register_pass("p0_inline", lambda context: {}, order=3)
    register_condition("p0_cleared", cleared, missing_ro=WORDS)
    register_condition("p0_cleared_inline", lambda s, r, p, st: True, missing_ro="Lipsește.")
    """
)

PLANTED_UNREADABLE = textwrap.dedent(
    """
    import functools

    from app.decisions.services import CONDITIONS, register_condition
    from app.media.somewhere import buy_more
    from app.workflows.passes import register_pass
    from app.workflows.passes import register_pass as add_pass
    from app.workflows.passes import watchdog_pass


    def buy(context, amount):
        return {}


    class Buyer:
        def __call__(self, context):
            return {}


    later = lambda context: {}  # noqa: E731
    add = register_pass


    def cleared(session, row, params, settings):
        return True


    register_pass("p0_partial", functools.partial(buy, amount=1), order=1)
    register_pass("p0_instance", Buyer(), order=2)
    register_pass("p0_imported", buy_more, order=3)
    register_pass("p0_later", later, order=4)
    register_pass(*("p0_splat", buy))
    watchdog_pass("p0_called", order=5)(buy)
    register_condition("p0_words", cleared, missing_ro=buy_more())
    CONDITIONS["p0_by_hand"] = cleared
    """
)


def test_the_readability_scan_names_what_it_cannot_read():
    """A check that cannot fail certifies nothing: every way around a readable registration
    is named, and the readable ways are not."""
    assert unreadable_registrations(ast.parse(PLANTED_READABLE)) == []
    problems = unreadable_registrations(ast.parse(PLANTED_UNREADABLE))
    assert {what for _line, what in problems} == {
        "register_pass registers a callable the scans cannot read",
        "watchdog_pass decorates something other than a function of the module",
        "register_condition says what is missing with something the scans cannot read",
        "uses register_pass other than by calling it",
        "imports register_pass as add_pass",
        "names the registry table CONDITIONS",
    }
    # The partial, the instance, the imported name, the lambda kept in a name, the splat.
    unread = [line for line, what in problems if what.startswith("register_pass registers")]
    assert len(set(unread)) == 5
