"""No paid path escapes the tests: every vendor call site the day can reach is faked.

Measured 2026-09-18: the end-to-end fixture faked the camera, the voice, the render plan and
the publisher, and still a TEST day on the Owner's own data chose Runway models for two
scenes of each film and made four paid ``text_to_video`` attempts, three tries each. Only the
rehearsal's DNS guard stopped them, because the fixture's studio had no video connection and
so never met the motion chooser. A list of fakes written by hand is a list of the paths
someone remembered.

So this file does two things. It proves the suite's own network guard (``tests/conftest.py``)
refuses a name lookup the way it refuses a socket: a public name is never resolved, loopback
still is, and a test that deliberately fakes ``getaddrinfo`` still can. And it reads the
whole of ``backend/app`` — without importing or running any of it — for every place that
constructs or calls a paid adapter (Runway, ElevenLabs, OpenAI media, Ollama, YouTube upload
and analytics, the search engine: every module under ``app/providers`` that is not one of
the free ones named below), and asserts each is either behind a fake the end-to-end fixture
installs or unreachable from the day. A new vendor call added to the day without a fake
fails here with the site and the path the day takes to it, before any test can spend.

How "reachable" is decided, so that a pass certifies no more than it measured: a call graph
over the source, from ``execute_daily_run`` and ``build_stage_runners`` (the day receives
its stage runners from the latter). A bare name is followed through its own module's
imports; ``module.attribute`` through the module it names; ``anything.method()`` to *every*
method of that name in the application, which over-approximates on purpose. A reference to
a function counts as a call, because the day passes functions as callbacks. A fake cuts the
path only where the patch is really seen: a module that imported the name at its top binds
the original, so a fake on the defining module does not cover it — only a patch on the
importing module does. What this cannot see: ``getattr`` by string, ``importlib`` and code
built at run time. The network guard is the backstop for those.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import socket
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
APP = BACKEND / "app"

#: The provider modules that cost nothing: interfaces, the deterministic stand-ins, the
#: registry, and the transport helpers the vendor adapters share. Every other module under
#: app/providers is a vendor and is paid until someone decides otherwise here, in review.
FREE_PROVIDER_MODULES = frozenset(
    {
        "app.providers",
        "app.providers.base",
        "app.providers.media_base",
        "app.providers.analytics_base",
        "app.providers.publishing_base",
        "app.providers.deterministic_analytics",
        "app.providers.deterministic_media",
        "app.providers.deterministic_pub",
        "app.providers.registry",
        "app.providers.retry",
        "app.providers.media_http",
        "app.providers.runpod.config",  # settings and validation; no vendor transport
    }
)

#: Where the day starts. `execute_daily_run` runs the twelve stages it is handed, and
#: `build_stage_runners` is what hands them over (the worker builds them for it).
ROOTS = (
    "app.runbook.services.execute_daily_run",
    "app.runbook.stages.build_stage_runners",
)

#: The vendors this file must find at least one site of, so a pass is never a scan of
#: nothing (a renamed module would otherwise make every check vacuous).
EXPECTED_VENDORS = frozenset(
    {
        "app.providers.runway",
        "app.providers.elevenlabs",
        "app.providers.openai_media",
        "app.providers.ollama",
        "app.providers.youtube",
        "app.providers.youtube_analytics",
        "app.providers.search",
    }
)


# ----------------------------------------------------------------- DNS, guarded like a socket


def test_a_public_name_is_refused_before_it_is_resolved(no_network):
    """The guard used to refuse `connect` and `connect_ex` only, so a public name was looked
    up first and refused after — the lookup itself is traffic, and a vendor client that
    resolves and then connects through a path the guard does not cover (the Windows
    proactor's ConnectEx) would have gone out."""
    for resolve in (socket.getaddrinfo, lambda host, *a: socket.gethostbyname(host)):
        with pytest.raises(AssertionError, match="api.dev.runwayml.com"):
            resolve("api.dev.runwayml.com", 443)
    with pytest.raises(AssertionError, match="api.elevenlabs.io"):
        socket.gethostbyname_ex("api.elevenlabs.io")
    # A public address written as a literal is no more local than its name.
    with pytest.raises(AssertionError):
        socket.getaddrinfo("192.0.2.1", 443)
    assert [entry["target"] for entry in no_network.refused][:2] == [
        "'api.dev.runwayml.com'",
        "'api.dev.runwayml.com'",
    ]


def test_loopback_still_resolves(no_network):
    """A test that serves itself on this machine keeps working."""
    for host in ("localhost", "127.0.0.1", "::1", None):
        assert socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)
    assert socket.gethostbyname("localhost").startswith("127.")
    assert no_network.refused == []


def test_a_test_that_fakes_getaddrinfo_still_can(monkeypatch):
    """The research tests answer the lookup themselves, to prove what the studio does with
    an address. Their patch is applied after the guard's and so it is theirs that answers."""
    answer = [(2, 1, 6, "", ("93.184.215.14", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: answer)
    assert socket.getaddrinfo("www.nasa.gov", 443) == answer


def test_asyncio_connect_to_a_public_address_is_refused(no_network):
    """The Windows proactor connects with ConnectEx, not `socket.connect`: an async vendor
    client went round the old guard entirely."""

    async def attempt():
        loop = asyncio.get_running_loop()
        sock = socket.socket()
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, ("192.0.2.1", 443))
        finally:
            sock.close()

    with pytest.raises(AssertionError, match="192.0.2.1"):
        asyncio.run(attempt())


# --------------------------------------------------------------------------- the source scan


@dataclass(frozen=True)
class Site:
    """One place in backend/app that constructs or calls a paid adapter."""

    function: str  # the enclosing function or method, fully qualified
    target: str  # the paid class or function, fully qualified
    vendor: str  # the paid module
    path: str
    line: int
    patch: tuple[str, str]  # the (module, attribute) a fake would have to replace here


@dataclass
class _Edge:
    target: str
    patch: tuple[str, str] | None
    line: int
    loose: bool = False  # resolved by method name alone


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _Source:
    """The application's source, indexed for name resolution and nothing else."""

    def __init__(self) -> None:
        self.trees: dict[str, ast.Module] = {}
        self.paths: dict[str, Path] = {}
        for path in sorted(APP.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            name = _module_name(path)
            self.trees[name] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            self.paths[name] = path
        self.functions: dict[str, tuple[str, ast.AST]] = {}  # qualname -> (module, node)
        self.classes: dict[str, ast.ClassDef] = {}
        self.methods_by_name: dict[str, set[str]] = {}
        self.top_defs: dict[str, set[str]] = {}
        self.top_imports: dict[str, dict[str, tuple[str, str | None]]] = {}
        for module, tree in self.trees.items():
            self.top_defs[module] = set()
            self.top_imports[module] = self._imports(module, tree.body)
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    self.functions[f"{module}.{node.name}"] = (module, node)
                    self.top_defs[module].add(node.name)
                elif isinstance(node, ast.ClassDef):
                    self.classes[f"{module}.{node.name}"] = node
                    self.top_defs[module].add(node.name)
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                            qualname = f"{module}.{node.name}.{item.name}"
                            self.functions[qualname] = (module, item)
                            self.methods_by_name.setdefault(item.name, set()).add(qualname)
                elif isinstance(node, ast.Assign | ast.AnnAssign):
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        if isinstance(target, ast.Name):
                            self.top_defs[module].add(target.id)

    def _absolute(self, module: str, level: int, name: str | None) -> str:
        if not level:
            return name or ""
        # `from . import x` inside a package's __init__ is relative to the package itself.
        package = module.split(".")
        if self.paths[module].name != "__init__.py":
            package = package[:-1]
        base = package[: len(package) - (level - 1)]
        return ".".join([*base, name] if name else base)

    def _imports(self, module: str, body: list[ast.stmt]) -> dict[str, tuple[str, str | None]]:
        """name -> (module, attribute) for `from m import a`, (module, None) for a module."""
        table: dict[str, tuple[str, str | None]] = {}
        for node in body:
            if isinstance(node, ast.ImportFrom):
                source = self._absolute(module, node.level, node.module)
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if f"{source}.{alias.name}" in self.trees:
                        table[bound] = (f"{source}.{alias.name}", None)
                    else:
                        table[bound] = (source, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        table[alias.asname] = (alias.name, None)
                    else:
                        table[alias.name.split(".")[0]] = (alias.name.split(".")[0], None)
        return table

    def definition(self, module: str, attribute: str, depth: int = 0) -> str | None:
        """The qualified definition `module.attribute` names, following re-exports."""
        qualname = f"{module}.{attribute}"
        if qualname in self.functions or qualname in self.classes:
            return qualname
        if module in self.trees and attribute in self.top_imports[module] and depth < 8:
            source, name = self.top_imports[module][attribute]
            return self.definition(source, name, depth + 1) if name else None
        return None


#: Paid modules outside app/providers: the configured language model (OpenAI, Anthropic)
#: is built and called through app.integrations.llm (MONEY-14, 2026-10-02).
PAID_MODULES_ELSEWHERE = frozenset({"app.integrations.llm"})


def _paid_module(source: _Source, module: str) -> bool:
    if module in PAID_MODULES_ELSEWHERE:
        return module in source.trees
    return (
        module.startswith("app.providers.")
        and module not in FREE_PROVIDER_MODULES
        and (module in source.trees)
    )


def _edges(source: _Source, qualname: str) -> list[_Edge]:
    module, node = source.functions[qualname]
    # Imports written inside the function bind late: a patch on the source module is seen.
    local = source._imports(
        module,
        [n for n in ast.walk(node) if isinstance(n, ast.Import | ast.ImportFrom)],
    )
    top = source.top_imports[module]
    edges: list[_Edge] = []

    def module_of(name: str) -> str | None:
        for table in (local, top):
            if name in table:
                target, attribute = table[name]
                if attribute is None and target in source.trees:
                    return target
                if attribute is not None and f"{target}.{attribute}" in source.trees:
                    return f"{target}.{attribute}"
                return None
        return None

    # A type annotation names a class without calling anything.
    annotations = {
        id(inner)
        for holder in ast.walk(node)
        for annotation in (
            [getattr(holder, "returns", None)]
            if isinstance(holder, ast.FunctionDef | ast.AsyncFunctionDef)
            else [holder.annotation]
            if isinstance(holder, ast.arg | ast.AnnAssign)
            else []
        )
        if annotation is not None
        for inner in ast.walk(annotation)
    }

    # The second argument of a builtin type check names types without constructing them.
    # Only plain names/attributes/tuples qualify: a nested constructor still counts as paid.
    def type_reference(value: ast.AST) -> bool:
        return (
            isinstance(value, ast.Name)
            or (isinstance(value, ast.Attribute) and type_reference(value.value))
            or (isinstance(value, ast.Tuple) and all(type_reference(v) for v in value.elts))
        )

    for holder in ast.walk(node):
        if (
            isinstance(holder, ast.Call)
            and isinstance(holder.func, ast.Name)
            and holder.func.id in {"isinstance", "issubclass"}
            and holder.func.id not in local
            and holder.func.id not in top
            and holder.func.id not in source.top_defs.get(module, ())
            and len(holder.args) == 2
            and type_reference(holder.args[1])
        ):
            annotations.update(id(inner) for inner in ast.walk(holder.args[1]))
    for child in ast.walk(node):
        if id(child) in annotations:
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            name = child.id
            if name in local:
                target, attribute = local[name]
                if attribute is None:
                    continue
                definition = source.definition(target, attribute)
                patch = (target, attribute)
            elif name in top:
                target, attribute = top[name]
                if attribute is None:
                    continue
                definition = source.definition(target, attribute)
                # Bound when the module was imported: only a patch on this module is seen.
                patch = (module, name)
            elif name in source.top_defs.get(module, ()):
                definition = source.definition(module, name)
                patch = (module, name)
            else:
                continue
            if definition:
                edges.append(_Edge(definition, patch, child.lineno))
        elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            owner = module_of(child.value.id)
            if owner is not None:
                definition = source.definition(owner, child.attr)
                if definition:
                    edges.append(_Edge(definition, (owner, child.attr), child.lineno))
                continue
            # A library module's function (`asyncio.run`, `json.dumps`) leads nowhere in the
            # application: it is not "any method of that name" (measured 2026-10-02:
            # `asyncio.run` in sync_provider_models was followed to every `.run` method).
            bound = local.get(child.value.id) or top.get(child.value.id)
            if bound is not None and bound[1] is None and bound[0] not in source.trees:
                continue
            # A class named directly (`Provider.from_verified_settings`) is resolved like a
            # module attribute; an instance's method is any method of that name.
            for table in (local, top):
                if child.value.id in table and table[child.value.id][1] is not None:
                    target, attribute = table[child.value.id]
                    klass = source.definition(target, attribute)
                    if klass in source.classes:
                        edges.append(_Edge(klass, None, child.lineno))
                    break
            else:
                edges.extend(_any_method(source, child.attr, child.lineno))
        elif isinstance(child, ast.Attribute):
            edges.extend(_any_method(source, child.attr, child.lineno))
    return edges


def _any_method(source: _Source, name: str, line: int) -> list[_Edge]:
    """`something.name` whose owner is unknown: every method of that name, on purpose.

    Never a vendor's own method: an adapter instance exists only where it was constructed,
    and that construction is the site this file checks. Never a dunder either: those are
    called by the language, and construction is followed from the class itself.
    """
    if name.startswith("__"):
        return []
    return [
        _Edge(method, None, line, loose=True)
        for method in source.methods_by_name.get(name, ())
        if not _paid_module(source, source.functions[method][0])
    ]


def _owner_module(source: _Source, qualname: str) -> str:
    if qualname in source.functions:
        return source.functions[qualname][0]
    return qualname.rsplit(".", 1)[0]


def _base_names(node: ast.ClassDef) -> list[str]:
    return [
        base.id if isinstance(base, ast.Name) else getattr(base, "attr", "") for base in node.bases
    ]


#: The studio's declarative base (backend/app/models.py): what a table row's class line names.
DECLARATIVE_BASE = ("app.models", "Base")


def _is_table_row(source: _Source, module: str, node: ast.ClassDef) -> bool:
    """A class of the studio's declarative base: a database table row of `module`.

    The second WP29 review (2026-10-10) measured the bare name ``Base`` on the class line
    deciding it: `from app.providers.runpod.client import RunPodClient as Base` (or a vendor
    module's own ``class Base`` with a ``run``) made every empty subclass a record. So ``Base``
    counts only while the module binds it once, by `from app.models import Base`, and nowhere
    else: no other import, assignment, definition, star import or ``global Base`` (a condition
    or a function that rebinds it is read like a line of the module)."""
    if not any(isinstance(base, ast.Name) and base.id == "Base" for base in node.bases):
        return False
    scope = _module_scope(source, module)
    return (
        "Base" not in scope.rebound
        and "*" not in scope.bindings
        and scope.bindings.get("Base") == [DECLARATIVE_BASE]
    )


#: What a table row's function may be decorated with to count as a property of its columns.
_PROPERTY_DECORATORS = frozenset(
    {"property", "cached_property", "hybrid_property", "setter", "getter", "deleter", "expression"}
)


def _is_property(item: ast.stmt) -> bool:
    return (
        isinstance(item, ast.FunctionDef)
        and bool(item.decorator_list)
        and all(
            (d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")) in _PROPERTY_DECORATORS
            for d in item.decorator_list
        )
    )


#: What a table row of a vendor module may name besides its own columns, its locals and its
#: module's plain constants (WP29 review, 2026-10-09). Each was read: none reaches a vendor,
#: the network or the application. A row that needs more adds it here, in review.
ROW_LIBRARIES = frozenset(
    {"sqlalchemy", "typing", "decimal", "datetime", "json", "uuid", "hashlib", "enum", "functools"}
)
ROW_BUILTINS = frozenset(
    {
        *("abs", "all", "any", "bool", "bytes", "dict", "float", "frozenset", "int"),
        *("isinstance", "len", "list", "max", "min", "object", "property", "repr", "round"),
        *("set", "sorted", "str", "sum", "tuple"),
    }
)
#: The methods a row may call on a value (a column, a local, what a library returned): text,
#: number, date and mapping methods. `get` is left out on purpose: `client.get(url)` reads
#: exactly like `dict.get`.
ROW_VALUE_METHODS = frozenset(
    {
        *("endswith", "isoformat", "items", "join", "keys", "lower", "lstrip", "partition"),
        *("quantize", "replace", "rsplit", "rstrip", "split", "startswith", "strip", "upper"),
        "values",
    }
)
#: What a module constant a row may read is built of: immutable values only. No dict, list or
#: set display: written once as a literal, it can still be filled later by anything in the
#: module (a registering decorator, `.update()`, `NAME[k] = v` in a function), and the third
#: WP29 review (2026-10-10) measured a row's property handing back such a registry of the
#: vendor's functions as a record.
_PLAIN_VALUE_NODES = (
    ast.Constant,
    ast.Tuple,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Subscript,
    ast.Slice,
    ast.Name,
    ast.operator,
    ast.unaryop,
    ast.boolop,
    ast.cmpop,
    ast.expr_context,
)


def _module_values(source: _Source, module: str, name: str) -> list[ast.expr]:
    """What `module` assigns to `name` at its top (`A, B = "A", "B"` included)."""
    values: list[ast.expr] = []
    for statement in source.trees[module].body:
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
            if isinstance(statement, ast.AnnAssign)
            else []
        )
        value = getattr(statement, "value", None)
        if value is not None and any(
            isinstance(bound, ast.Name) and bound.id == name
            for target in targets
            for bound in ast.walk(target)
        ):
            values.append(value)
    return values


#: How one scope binds a name: an import's (module, attribute), or None for any other binding
#: (an argument, an assignment, a definition, a loop or an `except ... as` variable).
_Binding = tuple[str, str | None] | None
_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_SCOPES = (*_FUNCTION_SCOPES, *_COMPREHENSIONS, ast.ClassDef)


def _own_code(nodes: list[ast.AST]) -> Iterator[ast.AST]:
    """Every node of one scope's code, without the insides of the scopes nested in it."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _arguments(function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.arg]:
    given = function.args
    return [
        argument
        for argument in (
            *given.posonlyargs,
            *given.args,
            *given.kwonlyargs,
            given.vararg,
            given.kwarg,
        )
        if argument is not None
    ]


def _scope_bindings(source: _Source, module: str, scope: ast.AST) -> dict[str, list[_Binding]]:
    """The names one scope binds (a module, a class body, a function, a lambda or a
    comprehension), each with every way the scope binds it.

    Python decides once per scope whether a name is that scope's own: bound anywhere in a
    function, it is the function's on every line of it, and on no line of any other."""
    bound: dict[str, list[_Binding]] = {}
    code: list[ast.AST]
    if isinstance(scope, _FUNCTION_SCOPES):
        for argument in _arguments(scope):
            bound.setdefault(argument.arg, []).append(None)
        code = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    elif isinstance(scope, _COMPREHENSIONS):
        code = [generator.target for generator in scope.generators]
    elif isinstance(scope, ast.Module | ast.ClassDef):
        code = list(scope.body)
    else:
        raise TypeError(f"not a scope: {type(scope).__name__}")
    for node in _own_code(code):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bound.setdefault(node.id, []).append(None)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.setdefault(node.name, []).append(None)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for name, origin in source._imports(module, [node]).items():
                bound.setdefault(name, []).append(origin)
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
            bound.setdefault(node.name, []).append(None)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.setdefault(node.rest, []).append(None)
    return bound


@dataclass
class _ModuleScope:
    """How a vendor module binds its top-level names, read once per row."""

    bindings: dict[str, list[_Binding]]
    rebound: set[str]  # named by a `global` statement somewhere in the module


def _module_scope(source: _Source, module: str) -> _ModuleScope:
    tree = source.trees[module]
    return _ModuleScope(
        _scope_bindings(source, module, tree),
        {name for node in ast.walk(tree) if isinstance(node, ast.Global) for name in node.names},
    )


def _module_constant(
    source: _Source, module: str, scope: _ModuleScope, name: str, depth: int = 0
) -> bool:
    """Whether `module`'s `name` is a plain constant: bound only by assignments at its top,
    of immutable literals and names of other constants.

    `SESSION_STATUSES = (OPENING, OPEN, ...)` is one; `logger = logging.getLogger(...)`, a
    lock, a client, an alias of a class (`_CLIENT = RunPodClient`), a dict, list or set the
    module can fill later (`_HANDLERS = {}`), or a name bound again under a condition, by a
    loop or from a function (`global`) is not."""
    values = _module_values(source, module, name)
    bindings = scope.bindings.get(name, [])
    if (
        not values
        or depth > 8
        or name in scope.rebound
        or len(bindings) != len(values)
        or any(binding is not None for binding in bindings)
    ):
        return False
    return all(
        isinstance(part, _PLAIN_VALUE_NODES)
        and (
            not isinstance(part, ast.Name)
            or _module_constant(source, module, scope, part.id, depth + 1)
        )
        for value in values
        for part in ast.walk(value)
    )


def _origin_problem(source: _Source, name: str, origin: tuple[str, str | None]) -> str | None:
    target, attribute = origin
    said = f"{target}.{attribute}" if attribute else target
    if target.split(".")[0] == "app" or target in source.trees:
        return f"names {name} from the application ({said})"
    if target.split(".")[0] not in ROW_LIBRARIES:
        return f"names {name} from {said}, a library a record has no use for"
    return None


def _row_name_problem(
    source: _Source,
    module: str,
    scope: _ModuleScope,
    name: str,
    bindings: list[_Binding] | None,
) -> str | None:
    """Why a row may not read `name` where `bindings` bind it; None when it may.

    `bindings` are how the row's own scope binds the name there (an argument, a local, a
    local import), or None when no scope of the row binds it: then it is the module's, and
    every way the module binds it is judged, or, bound by nothing, a builtin."""
    if bindings is not None:
        for origin in bindings:
            if origin is not None and (problem := _origin_problem(source, name, origin)):
                return problem
        return None
    at_top = scope.bindings.get(name, [])
    for origin in at_top:
        if origin is not None and (problem := _origin_problem(source, name, origin)):
            return problem
    if f"{module}.{name}" in source.functions or f"{module}.{name}" in source.classes:
        return f"names {name}, a function or class of {module}"
    if None in at_top or name in scope.rebound:
        if _module_constant(source, module, scope, name):
            return None
        return f"names {name}, which {module} builds or binds again: not a constant"
    if at_top:
        return None  # imported from an allowlisted library, and only so
    if "*" in scope.bindings:
        return f"names {name}, which {module} may take from its star import"
    if name in ROW_BUILTINS:
        return None
    return f"names {name}, which a record has no use for"


def _row_reads(
    source: _Source, module: str, node: ast.ClassDef
) -> dict[int, list[_Binding] | None]:
    """How each name the row reads (by the id of its ast.Name) is bound where it is read.

    The bindings of the innermost of the row's scopes that binds it, as Python looks them up,
    or None when no scope of the row does (the module's name, or a builtin). A function, a
    lambda or a comprehension of the row never sees the class body's names: a column named
    like an import does not hide the import from a property, and a local of one property does
    not hide it from another (the second WP29 review, 2026-10-10, measured both passing)."""
    reads: dict[int, list[_Binding] | None] = {}
    class_scope = _scope_bindings(source, module, node)

    def look(part: ast.AST, chain: list[dict[str, list[_Binding]]]) -> None:
        if isinstance(part, ast.Name):
            if isinstance(part.ctx, ast.Load):
                reads[id(part)] = next(
                    (scope[part.id] for scope in chain if part.id in scope), None
                )
            return
        inside = [scope for scope in chain if scope is not class_scope]
        if isinstance(part, _FUNCTION_SCOPES):
            # Decorators, defaults and annotations are read where the function is defined.
            outer: list[ast.AST] = [
                *part.args.defaults,
                *(default for default in part.args.kw_defaults if default is not None),
            ]
            if not isinstance(part, ast.Lambda):
                outer.extend(part.decorator_list)
                outer.extend(a.annotation for a in _arguments(part) if a.annotation is not None)
                outer.extend([part.returns] if part.returns is not None else [])
            for piece in outer:
                look(piece, chain)
            own = [_scope_bindings(source, module, part), *inside]
            for piece in part.body if isinstance(part.body, list) else [part.body]:
                look(piece, own)
            return
        if isinstance(part, _COMPREHENSIONS):
            first, *others = part.generators
            look(first.iter, chain)  # the first iterable is read where the comprehension is
            pieces: list[ast.AST] = (
                [part.key, part.value] if isinstance(part, ast.DictComp) else [part.elt]
            )
            pieces.extend([first.target, *first.ifs])
            for generator in others:
                pieces.extend([generator.target, generator.iter, *generator.ifs])
            own = [_scope_bindings(source, module, part), *inside]
            for piece in pieces:
                look(piece, own)
            return
        for child in ast.iter_child_nodes(part):
            look(child, chain)

    for part in (*node.bases, *(keyword.value for keyword in node.keywords)):
        look(part, [])
    for item in node.body:
        look(item, [class_scope])
    return reads


def _row_problems(
    source: _Source,
    module: str,
    node: ast.ClassDef,
    attachments: dict[str, list[str]] | None = None,
) -> list[str]:
    """Why a table row (a ``Base`` class) of a vendor module is more than a plain record.

    af6ef05 (2026-10-09) let every class with ``Base`` among its bases pass as a record, by
    name: the never-queued proof reads GpuSessionRow and GenerationJob, and the scan had
    counted those rows as adapters. By name alone, a method added to such a row later (a
    resubmit helper on GenerationJob that builds the client) would never be reported, and
    nothing else would see it either: `_any_method` never follows a vendor module's methods.

    The first narrowing (WP29) followed the row's names through the call graph and so dropped
    every loose edge: its review measured `self.rounds.run()` (the assembler's paid rounds),
    a vendor-only `self.client.submit(...)`, `urllib.request.urlopen(...)` and a class
    decorator or metaclass all passing as a record. So a row is judged by what it may hold,
    not by what the graph can resolve. A row passes only while:

    - its class line is ``Base`` (the declarative one: `_is_table_row`) and allowlisted
      libraries, with no decorator and only constant keywords (a decorator or a metaclass runs
      code the body never shows);
    - its body holds columns, relationships, table arguments and properties;
    - every name it reads is its own where it reads it (`_row_reads`: Python's scopes, so a
      column or one property's local never hides a module's import from another property), an
      allowlisted library's (`ROW_LIBRARIES`), a value builtin (`ROW_BUILTINS`) or a plain
      constant of its module; nothing of the application, nothing its module built at import
      (a logger, a lock, a client), no other library, no ``global``;
    - every ``self.x`` is one of its own columns or properties, so a property can neither call
      nor hand back an object it was given (`self.client.submit`, called or not); a lambda or
      an inner function that takes an argument, which could be handed the row as well, is
      refused (the second WP29 review, 2026-10-10, measured
      ``sender = lambda self: self.client.submit`` passing); and ``self`` is never used but
      in front of such an attribute, so the row is not copied, stored or handed on where its
      attributes go unread (the third WP29 review, 2026-10-10: `row = self`);
    - every method it calls on a value is a text, number, date or mapping method
      (`ROW_VALUE_METHODS`), it calls no local it took at run time, and it names no paid
      method, called or not;
    - no vendor module gives it more from outside its class (`_row_attachments`: a listener,
      a method set on the class, a decorator that names it). `attachments` is that reading
      for every row at once, when the caller already has it.

    What this still cannot see: code built at run time from strings. The network guard is the
    backstop, as for the rest of this file.
    """
    problems: list[str] = []
    bases = [base for base in node.bases if not (isinstance(base, ast.Name) and base.id == "Base")]
    problems.extend(
        f"line {decorator.lineno}: the class is decorated with {ast.unparse(decorator)}"
        for decorator in node.decorator_list
    )
    problems.extend(
        f"line {keyword.value.lineno}: the class takes {keyword.arg or '**'}="
        f"{ast.unparse(keyword.value)}"
        for keyword in node.keywords
        if not isinstance(keyword.value, ast.Constant)
    )
    for item in node.body:
        if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
            continue  # its docstring
        if isinstance(item, ast.Assign | ast.AnnAssign | ast.Pass) or _is_property(item):
            continue
        what = getattr(item, "name", type(item).__name__)
        problems.append(f"line {item.lineno}: {what} is not a column, a relationship or a property")

    tree = ast.Module(body=[*(ast.Expr(base) for base in bases), *node.body], type_ignores=[])
    scope = _module_scope(source, module)
    reads = _row_reads(source, module, node)
    # What `self.x` may name: the row's columns and properties.
    own = {
        item.name
        for item in node.body
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    } | {
        target.id
        for item in node.body
        if isinstance(item, ast.Assign | ast.AnnAssign)
        for target in (item.targets if isinstance(item, ast.Assign) else [item.target])
        if isinstance(target, ast.Name)
    }
    # The instance a property reads its columns from (`self`, or `cls` in a hybrid expression).
    # Only the row's own functions are handed the row; a lambda or an inner function that takes
    # an argument could be handed it too, and is refused below rather than guessed at.
    instances = {
        item.args.args[0].arg
        for item in node.body
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.args.args
    }
    # The only way a row is read: `self.<its own column or property>` (an attribute that is not
    # its own is refused below). The third WP29 review (2026-10-10) measured the row copied
    # anywhere else (`row = self`, `(self,)[0]`, `for row in (self,)`) reading
    # `row.adapter.submit_batch` unchecked, so the instance name is refused everywhere but in
    # front of an attribute: the row can be neither aliased, nor stored, nor handed on.
    read_through_attribute = {
        id(child.value)
        for child in ast.walk(tree)
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
    }
    paid = PAID_METHODS | GATED_ONLY_METHODS
    top_level = {id(item) for item in node.body}
    for child in ast.walk(tree):
        line = getattr(child, "lineno", node.lineno)
        # A paid method named at all, called or not: handed back, or given to `sorted` as its
        # key (which calls it on every read of the property), it is the vendor all the same.
        if isinstance(child, ast.Attribute) and child.attr in paid:
            problems.append(f"line {line}: names the paid method .{child.attr}")
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
            and child.id in instances
            and id(child) not in read_through_attribute
        ):
            problems.append(
                f"line {line}: uses {child.id} as a value; a row is read only through "
                f"{child.id}.<its own column or property>"
            )
        if (
            isinstance(child, _FUNCTION_SCOPES)
            and id(child) not in top_level
            and (taken := _arguments(child))
        ):
            problems.append(
                f"line {line}: a function inside the row takes "
                f"{', '.join(argument.arg for argument in taken)}; only the row's own "
                "properties are handed the row"
            )
        elif isinstance(child, ast.ClassDef) and id(child) not in top_level:
            problems.append(f"line {line}: defines the class {child.name} inside the row")
        elif isinstance(child, ast.Global):
            problems.append(f"line {line}: binds the module's {', '.join(child.names)}")
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            problem = _row_name_problem(source, module, scope, child.id, reads.get(id(child)))
            if problem:
                problems.append(f"line {line}: {problem}")
        elif (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id in instances
            and child.attr not in own
        ):
            problems.append(f"line {line}: uses {child.value.id}.{child.attr}, not a column")
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            bound = reads.get(id(func))
            if bound is not None and None in bound:
                problems.append(f"line {line}: calls {func.id}(), something taken at run time")
        elif isinstance(func, ast.Attribute):
            root = func.value
            while isinstance(root, ast.Attribute):
                root = root.value
            # An imported module's function (`datetime.now`, `json.dumps`): the import itself
            # is judged above. Anything else is a value, and only a value's methods are called.
            bound = reads.get(id(root), [None]) if isinstance(root, ast.Name) else [None]
            imported = (bound is not None and bool(bound) and None not in bound) or (
                bound is None
                and isinstance(root, ast.Name)
                and None not in scope.bindings.get(root.id, [None])
            )
            if not imported and func.attr not in ROW_VALUE_METHODS:
                problems.append(f"line {line}: calls .{func.attr}() on an object")
        else:
            problems.append(f"line {line}: calls what {ast.unparse(func)} returns")
    problems.extend(
        f"calls the paid method .{method}()"
        for method in sorted(_paid_calls(tree, PAID_METHODS | GATED_ONLY_METHODS))
    )
    if attachments is None:
        attachments = _row_attachments(source)
    problems.extend(attachments.get(f"{module}.{node.name}", []))
    return problems


#: SQLAlchemy's event registration (`event.listen`, `@event.listens_for`): what it registers
#: runs inside the studio's own writes, called by no function this file can follow.
_LISTENERS = frozenset({"listen", "listens_for"})


def _dotted(expr: ast.AST) -> list[str] | None:
    """`a.b[k].c` as ["a", "b", "c"]; None when it does not start from a plain name."""
    parts: list[str] = []
    while isinstance(expr, ast.Attribute | ast.Subscript):
        if isinstance(expr, ast.Attribute):
            parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return parts[::-1]


@dataclass
class _RowReader:
    """How one vendor module names the vendor rows: its imports (top and local) and aliases."""

    source: _Source
    rows: set[str]
    imports: dict[str, tuple[str, str | None]]
    aliases: dict[str, str]  # a name bound in the module -> the qualified name it stands for

    def full(self, expr: ast.AST) -> str | None:
        parts = _dotted(expr)
        if parts is None:
            return None
        head, rest = parts[0], parts[1:]
        if head in self.aliases:
            return ".".join([self.aliases[head], *rest])
        if head in self.imports:
            target, attribute = self.imports[head]
            return ".".join([target, *([attribute] if attribute else []), *rest])
        return None

    def row(self, expr: ast.AST) -> str | None:
        """The vendor row `expr` is, or an attribute of (`GenerationJob.status`)."""
        full = self.full(expr)
        if full is None:
            return None
        path = full.split(".")
        for end in range(len(path) - 1, 0, -1):
            module = ".".join(path[:end])
            if module in self.source.trees:
                definition = self.source.definition(module, path[end])
                return definition if definition in self.rows else None
        return None

    def rows_in(self, nodes: list[ast.AST]) -> set[str]:
        return {
            row
            for node in nodes
            for part in ast.walk(node)
            if isinstance(part, ast.Name | ast.Attribute)
            for row in [self.row(part)]
            if row is not None
        }

    def listener(self, expr: ast.AST) -> bool:
        full = self.full(expr)
        return (
            full is not None
            and full.split(".")[0] == "sqlalchemy"
            and full.rsplit(".", 1)[-1] in _LISTENERS
        )


def _row_attachments(source: _Source) -> dict[str, list[str]]:
    """What the vendor modules give their table rows from outside the rows' classes, per row.

    The WP29 review (2026-10-09) measured `_row_problems` reading the class body only: a
    listener SQLAlchemy runs at every insert of a GenerationJob
    (``@event.listens_for(GenerationJob, "before_insert")``), or a method set on the class
    from outside (``GenerationJob.resubmit = _resubmit``), left the row a record, and the
    studio code that writes or reads it no paid site. So every vendor module is read whole
    (its functions too: an ``_install()`` runs as surely as a module line), and a row is
    charged with:

    - an attribute of it set or deleted (``Row.x = ...``, ``del Row.x``), also through an alias
      of the class or its module (``jobs.GenerationJob.x = ...``), or ``setattr``/``delattr``
      on it;
    - a decorator that names it or its columns, whatever the decorator is called;
    - a SQLAlchemy listener that names it or its columns. A listener that names no vendor row
      (on the Session, a mapper, an engine), or a listener function passed around uncalled,
      charges every vendor row: it runs at the studio's own writes, where this scan cannot
      follow it. No vendor module holds one today; the studio's own (app/db.py) are not read.

    Only vendor modules are read: anywhere else, what a row is given is the studio's own code,
    and this file follows that. What this cannot see: a class reached at run time
    (``type(row).x = ...``), names built from strings.
    """
    rows = {
        qualname
        for qualname, node in source.classes.items()
        if _paid_module(source, owner := qualname.rsplit(".", 1)[0])
        and _is_table_row(source, owner, node)
    }
    found: dict[str, list[str]] = {row: [] for row in rows}

    def charge(module: str, rows_charged: set[str], line: int, what: str, node: ast.AST) -> None:
        said = ast.unparse(node)
        said = said if len(said) <= 100 else said[:97] + "..."
        for row in sorted(rows_charged):
            found[row].append(f"{module} line {line}: {what}: {said}")

    for module, tree in source.trees.items():
        if not _paid_module(source, module):
            continue
        nodes = list(ast.walk(tree))
        reader = _RowReader(
            source,
            rows,
            source._imports(
                module, [n for n in nodes if isinstance(n, ast.Import | ast.ImportFrom)]
            ),
            {q.rsplit(".", 1)[1]: q for q in rows if q.rsplit(".", 1)[0] == module},
        )
        assignments = [n for n in nodes if isinstance(n, ast.Assign | ast.AnnAssign) and n.value]
        grown = True
        while grown:  # `_Row = GenerationJob`, `Other = _Row`: an alias of an alias
            grown = False
            for assignment in assignments:
                value = assignment.value
                full = reader.full(value) if value is not None and reader.row(value) else None
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                for target in targets:
                    if full and isinstance(target, ast.Name) and target.id not in reader.aliases:
                        reader.aliases[target.id] = full
                        grown = True

        listener_calls: set[int] = set()
        for node in nodes:
            if isinstance(node, ast.Call) and reader.listener(node.func):
                listener_calls.update({id(node), id(node.func)})
                named = reader.rows_in([*node.args, *(k.value for k in node.keywords)])
                if named:
                    charge(module, named, node.lineno, "a database listener on the row", node)
                else:
                    charge(
                        module,
                        rows,
                        node.lineno,
                        "a database listener that runs at the studio's own writes, where this "
                        "scan cannot follow it",
                        node,
                    )
        for node in nodes:
            line = getattr(node, "lineno", 0)
            if (
                isinstance(node, ast.Attribute | ast.Subscript)
                and isinstance(node.ctx, ast.Store | ast.Del)
                and (row := reader.row(node.value)) is not None
            ):
                charge(module, {row}, line, "changes the class from outside it", node)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"setattr", "delattr"}
                and node.args
                and (row := reader.row(node.args[0])) is not None
            ):
                charge(module, {row}, line, "changes the class from outside it", node)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                for decorator in node.decorator_list:
                    if id(decorator) in listener_calls:
                        continue  # charged above, as the listener it is
                    named = reader.rows_in([decorator])
                    if named:
                        charge(
                            module, named, decorator.lineno, "a decorator names the row", decorator
                        )
            elif (
                isinstance(node, ast.Name | ast.Attribute)
                and id(node) not in listener_calls
                and reader.listener(node)
            ):
                charge(
                    module,
                    rows,
                    line,
                    "a database listener passed around uncalled; it runs where this scan "
                    "cannot follow it",
                    node,
                )
    return found


def _is_record(
    source: _Source,
    module: str,
    node: ast.ClassDef,
    attachments: dict[str, list[str]] | None = None,
) -> bool:
    """An exception or a plain record: something a vendor module defines that calls nobody."""
    # A database table row: read and written by the studio (the never-queued proof reads
    # GpuSessionRow and GenerationJob), never a way to the vendor while it holds nothing but
    # its columns and no vendor module gives it more from outside (narrowed 2026-10-09, WP29:
    # see `_row_problems` and `_row_attachments`). Judged before the names below: a row named
    # JobError passed by its name, whatever its body held (the second WP29 review, 2026-10-10).
    if _is_table_row(source, module, node):
        return not _row_problems(source, module, node, attachments)
    names = [node.name, *_base_names(node)]
    if any(name.endswith(("Error", "Exception")) for name in names):
        return True
    return any(
        (decorator.id if isinstance(decorator, ast.Name) else getattr(decorator, "attr", ""))
        == "dataclass"
        or (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "dataclass")
        for decorator in node.decorator_list
    )


def paid_targets(source: _Source) -> set[str]:
    """The adapters of every paid module, and the module functions that build one.

    A vendor module's exceptions and records are not a way to the vendor, nor are its pure
    helpers (parsing a contract, picking a ratio); a function that constructs an adapter is.
    """
    attachments = _row_attachments(source)
    adapters = {
        qualname
        for qualname, node in source.classes.items()
        if _paid_module(source, qualname.rsplit(".", 1)[0])
        and not _is_record(source, qualname.rsplit(".", 1)[0], node, attachments)
    }
    builders: set[str] = set()
    for qualname, (module, node) in source.functions.items():
        if not _paid_module(source, module) or qualname.count(".") != module.count(".") + 1:
            continue
        if any(
            isinstance(child, ast.Name) and f"{module}.{child.id}" in adapters
            for child in ast.walk(node)
        ):
            builders.add(qualname)
    return adapters | builders


def paid_sites(source: _Source | None = None) -> list[Site]:
    """Every site outside the vendor modules that names a paid adapter or its builder."""
    source = source or _Source()
    paid = paid_targets(source)
    sites: list[Site] = []
    for qualname, (module, _node) in source.functions.items():
        if _paid_module(source, module):
            continue  # the adapters' own insides are the vendor, not a way to it
        for edge in _edges(source, qualname):
            if edge.loose:
                continue  # an unknown object's method: its construction is the site
            vendor = _owner_module(source, edge.target)
            if edge.target in source.classes:
                vendor = edge.target.rsplit(".", 1)[0]
            if edge.target in paid:
                sites.append(
                    Site(
                        function=qualname,
                        target=edge.target,
                        vendor=vendor,
                        path=str(source.paths[module].relative_to(ROOT)),
                        line=edge.line,
                        patch=edge.patch or (module, qualname.rsplit(".", 1)[-1]),
                    )
                )
    return sites


def escaped_sites(
    fakes: set[tuple[str, str]], source: _Source | None = None
) -> list[tuple[Site, list[str]]]:
    """The paid sites the day reaches with `fakes` installed, each with the path it takes."""
    source = source or _Source()
    parent: dict[str, str | None] = {}
    queue: deque[str] = deque()
    for root in ROOTS:
        assert root in source.functions, f"the day's entry point {root} moved; update ROOTS"
        parent[root] = None
        queue.append(root)
    while queue:
        current = queue.popleft()
        module = source.functions[current][0]
        if _paid_module(source, module):
            continue
        for edge in _edges(source, current):
            if edge.patch in fakes:
                continue  # the fixture replaced this name where this caller reads it
            targets = [edge.target]
            if edge.target in source.classes:
                targets = [
                    f"{edge.target}.{m}"
                    for m in ("__init__", "__post_init__")
                    if f"{edge.target}.{m}" in source.functions
                ]
            for target in targets:
                if target in source.functions and target not in parent:
                    parent[target] = current
                    queue.append(target)

    def path_to(function: str) -> list[str]:
        chain: list[str] = []
        step: str | None = function
        while step is not None:
            chain.append(step)
            step = parent[step]
        return list(reversed(chain))

    return [
        (site, path_to(site.function))
        for site in paid_sites(source)
        if site.function in parent and site.patch not in fakes
    ]


def _describe(escaped: list[tuple[Site, list[str]]]) -> str:
    lines = []
    for site, chain in escaped:
        lines.append(
            f"{site.path}:{site.line} {site.function} -> {site.target}\n"
            f"    reached by: {' -> '.join(chain)}"
        )
    return "\n".join(lines)


@pytest.fixture(scope="module")
def source() -> _Source:
    return _Source()


def test_the_scan_finds_every_vendor(source):
    """A scan that found nothing would pass for the wrong reason."""
    sites = paid_sites(source)
    assert EXPECTED_VENDORS <= {site.vendor for site in sites}, sorted(
        {site.vendor for site in sites}
    )


def test_type_checks_do_not_construct_adapters_but_nested_calls_do(source):
    module = "app.media.local_media"
    qualname = f"{module}.is_local"
    original = source.functions[qualname]
    assert not any(
        e.target == "app.providers.comfyui.ComfyConnection" for e in _edges(source, qualname)
    )
    source.functions[qualname] = (
        module,
        ast.parse(
            "def is_local(adapter):\n"
            "    from app.providers.comfyui import ComfyConnection\n"
            "    return isinstance(adapter, ComfyConnection())\n"
        ).body[0],
    )
    try:
        assert any(
            e.target == "app.providers.comfyui.ComfyConnection" for e in _edges(source, qualname)
        )
    finally:
        source.functions[qualname] = original


def test_runpod_transport_still_counts_as_paid(source):
    assert "app.providers.runpod.client.RunPodClient" in paid_targets(source)
    assert "app.providers.runpod.provider.RunPodGenerationProvider" in paid_targets(source)
    assert "app.providers.runpod.config.RunPodConfig" not in paid_targets(source)


#: The table rows the never-queued proof reads (af6ef05), and the copy pod's row.
VENDOR_TABLE_ROWS = frozenset(
    {
        "app.providers.runpod.jobs.GenerationJob",
        "app.providers.runpod.gpu_session.GpuSessionRow",
        "app.providers.runpod.pods.CopyPodRow",
    }
)


def test_every_table_row_in_a_vendor_module_holds_only_its_columns(source):
    """2026-10-09 (WP29): a row of a vendor module is a record only while it holds columns,
    relationships, table arguments and properties that reach nothing of the application. A
    method added to one later fails here, with its line, before it can hide a vendor call."""
    rows = {
        qualname: _row_problems(source, qualname.rsplit(".", 1)[0], node)
        for qualname, node in source.classes.items()
        if _paid_module(source, owner := qualname.rsplit(".", 1)[0])
        and _is_table_row(source, owner, node)
    }
    assert VENDOR_TABLE_ROWS <= set(rows), sorted(rows)
    assert {qualname: found for qualname, found in rows.items() if found} == {}
    assert not VENDOR_TABLE_ROWS & paid_targets(source)


_GROWN_ROWS = {
    "a method that builds the client": (
        "def resubmit(self, config):\n"
        "    from app.providers.runpod.client import RunPodClient\n"
        "    return RunPodClient(config).run(self.request)\n"
    ),
    "a property that builds the client": (
        "@property\n"
        "def client(self):\n"
        "    from app.providers.runpod.client import RunPodClient\n"
        "    return RunPodClient(None)\n"
    ),
    "a property that calls a paid method": (
        "@property\ndef resent(self):\n    return self.adapter.submit_batch([])\n"
    ),
    "a property that calls a paid method by name": (
        "@property\ndef resent(self):\n    return getattr(self.adapter, 'submit_batch')([])\n"
    ),
    "a column whose default is application code": (
        "stamped_at: Mapped[str] = mapped_column(String(40), default=now)\n"
    ),
    "a plain method that calls nobody": "def __repr__(self):\n    return self.id\n",
    # The WP29 review (2026-10-09) found these four passing: a method called on an object was
    # dropped as a loose edge, and a library module resolves to no edge at all.
    "a property that runs a round through an object it holds": (
        "@property\ndef resubmitted(self):\n    return self.rounds.run()\n"
    ),
    "a property that calls a method only the vendor's client has": (
        "@property\n"
        "def resent(self):\n"
        "    return self.client.submit('image', self.request, self.idempotency_key)\n"
    ),
    "a property that calls a bound method it took from an object": (
        "@property\ndef resent(self):\n    send = self.adapter.submit_batch\n    return send([])\n"
    ),
    "a property that hands back an object's method uncalled": (
        "@property\ndef sender(self):\n    return self.client.submit\n"
    ),
    "a property that calls a transport library": (
        "@property\n"
        "def resent(self):\n"
        "    import urllib.request\n"
        "    return urllib.request.urlopen('https://vendor.example/run', data=b'{}')\n"
    ),
    # The class line itself: a decorator or a metaclass runs code the body never shows.
    "a class decorator that names the job store": (
        "@JobStore\nclass GenerationJob(Base):\n    pass\n"
    ),
    "a metaclass from the application": (
        "class GenerationJob(Base, metaclass=JobStore):\n    pass\n"
    ),
    # The second WP29 review (2026-10-10) found these passing on GpuSessionRow and CopyPodRow:
    # only the first argument of a row's own functions was read as the row, so a lambda's or
    # an inner function's was not; and one set of local names served the whole class, so a
    # local in one property hid the module's import from every other.
    "a lambda that hands back an object's method": "sender = lambda self: self.client.submit\n",
    "a property built from a lambda": (
        "sender = property(lambda self: self.client.submit_batch)\n"
    ),
    "a function inside a property that takes the row": (
        "@property\n"
        "def sender(self):\n"
        "    def bound(row):\n"
        "        return row.client.submit\n"
        "    return bound\n"
    ),
    "a local in one property hides the module's import from another": (
        "@property\n"
        "def plain(self):\n"
        "    lock_for_write = self.id\n"
        "    return lock_for_write\n"
        "\n"
        "@property\n"
        "def locker(self):\n"
        "    return lock_for_write\n"
    ),
    "an import in one property hides the module's import from another": (
        "@property\n"
        "def plain(self):\n"
        "    from decimal import Decimal as lock_for_write\n"
        "    return lock_for_write(0)\n"
        "\n"
        "@property\n"
        "def locker(self):\n"
        "    return lock_for_write\n"
    ),
    "a column hides the module's import from a property": (
        "lock_for_write: Mapped[str] = mapped_column(String(40))\n"
        "\n"
        "@property\n"
        "def locker(self):\n"
        "    return lock_for_write\n"
    ),
    "a name bound twice in one property, once from the application": (
        "@property\n"
        "def locker(self):\n"
        "    from app.db import lock_for_write as held\n"
        "    held = held\n"
        "    return held\n"
    ),
    "a row that declares a module global": (
        "@property\ndef locker(self):\n    global lock_for_write\n    return self.id\n"
    ),
    # The third WP29 review (2026-10-10) found these passing on all three rows: only an
    # attribute read straight off `self` was checked, so the row copied anywhere else (a local,
    # a tuple, a comprehension's variable) read anything through the copy; and a paid method
    # was refused only when called right there, not handed on or given to `sorted` as its key
    # (which calls it on every read of the property).
    "a property that hands back a paid method through a local copy of the row": (
        "@property\ndef sender(self):\n    row = self\n    return row.adapter.submit_batch\n"
    ),
    "a property that takes the row back out of a tuple": (
        "@property\ndef sender(self):\n    return (self,)[0].adapter.submit_batch\n"
    ),
    "a comprehension that walks over the row": (
        "@property\n"
        "def sender(self):\n"
        "    return [row.adapter.submit_batch for row in (self,)][0]\n"
    ),
    "a property that calls a paid method as the key of a sort": (
        "@property\n"
        "def resent(self):\n"
        "    row = self\n"
        "    return sorted([[]], key=row.adapter.submit_batch)\n"
    ),
    "a property that hands back a paid method of its own column": (
        "@property\ndef sender(self):\n    return self.status.submit_batch\n"
    ),
}


def _grown(original: ast.ClassDef, code: str) -> ast.ClassDef:
    """`original` with `code` added to its body, or with its class line replaced by `code`'s."""
    changed = copy.deepcopy(original)
    added = ast.parse(code).body
    if len(added) == 1 and isinstance(added[0], ast.ClassDef):
        line = added[0]
        changed.decorator_list, changed.keywords, changed.bases = (
            line.decorator_list,
            line.keywords,
            line.bases,
        )
        added = [item for item in line.body if not isinstance(item, ast.Pass)]
    changed.body.extend(added)
    return changed


@pytest.mark.parametrize("grown", sorted(_GROWN_ROWS))
def test_a_table_row_that_gains_a_way_to_the_vendor_is_flagged(source, grown):
    """The test af6ef05's exemption could not fail: GenerationJob, given a method (or a
    property, or a column default) that could reach RunPod, counts as an adapter again, and
    the studio's readers of the row become paid sites the scan follows."""
    module = "app.providers.runpod.jobs"
    qualname = f"{module}.GenerationJob"
    original = source.classes[qualname]
    assert _is_record(source, module, original)
    changed = _grown(original, _GROWN_ROWS[grown])
    assert _row_problems(source, module, changed)
    assert not _is_record(source, module, changed)
    source.classes[qualname] = changed
    try:
        assert qualname in paid_targets(source)
        readers = {site.function for site in paid_sites(source) if site.target == qualname}
        assert "app.workflows.watchdog" in {name.rsplit(".", 1)[0] for name in readers}, readers
    finally:
        source.classes[qualname] = original


@pytest.fixture(scope="module")
def attachments(source) -> dict[str, list[str]]:
    """What the vendor modules give their rows from outside, read once for the tests below."""
    return _row_attachments(source)


@pytest.mark.parametrize("row", sorted(VENDOR_TABLE_ROWS))
@pytest.mark.parametrize("grown", sorted(_GROWN_ROWS))
def test_every_vendor_row_that_gains_a_way_to_the_vendor_is_flagged(
    source, attachments, row, grown
):
    """The second WP29 review (2026-10-10) measured a lambda handing back the client's method
    passing on GpuSessionRow and CopyPodRow only because, unlike GenerationJob, they have no
    property of their own: what a row may hold must not depend on what else it holds."""
    module = row.rsplit(".", 1)[0]
    changed = _grown(source.classes[row], _GROWN_ROWS[grown])
    assert _row_problems(source, module, changed, attachments), grown
    assert not _is_record(source, module, changed, attachments)


@pytest.mark.parametrize(
    ("name", "bases"),
    [
        ("JobError", "Base"),
        ("JobException", "Base"),
        ("GenerationJob", "Base, RunPodProtocolError"),
    ],
)
def test_a_table_row_named_like_an_error_is_judged_by_its_body(source, name, bases):
    """The second WP29 review (2026-10-10): `_is_record` let a class pass by an Error or
    Exception in its name or its bases' before it read a row's body, so a table of RunPod
    refusals called JobError could carry a resubmit method that builds the client."""
    module = "app.providers.runpod.jobs"
    changed = _grown(
        source.classes[f"{module}.GenerationJob"],
        f"class {name}({bases}):\n"
        "    def resubmit(self, config):\n"
        "        from app.providers.runpod.client import RunPodClient\n"
        "        return RunPodClient(config).run(self.request)\n",
    )
    changed.name = name
    assert _is_table_row(source, module, changed)
    assert _row_problems(source, module, changed)
    assert not _is_record(source, module, changed)


@contextmanager
def _module_grown(source: _Source, module: str, code: str) -> Iterator[list[ast.stmt]]:
    """`module` with `code` appended at its top level, as if written there; restored after."""
    tree = source.trees[module]
    saved = (
        list(tree.body),
        source.top_imports[module],
        set(source.top_defs[module]),
        dict(source.classes),
        dict(source.functions),
    )
    added = ast.parse(code).body
    tree.body.extend(added)
    source.top_imports[module] = source._imports(module, tree.body)
    for node in added:
        if isinstance(node, ast.ClassDef):
            source.classes[f"{module}.{node.name}"] = node
            source.top_defs[module].add(node.name)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            source.functions[f"{module}.{node.name}"] = (module, node)
            source.top_defs[module].add(node.name)
    try:
        yield added
    finally:
        tree.body[:] = saved[0]
        source.top_imports[module] = saved[1]
        source.top_defs[module] = saved[2]
        source.classes.clear()
        source.classes.update(saved[3])
        source.functions.clear()
        source.functions.update(saved[4])


#: A ``Base`` on a class line that is not the studio's declarative base (app.models.Base).
_NOT_THE_DECLARATIVE_BASE = {
    "the vendor client imported as Base": (
        "from app.providers.runpod.client import RunPodClient as Base\n"
    ),
    "a Base class of the vendor module": (
        "class Base:\n"
        "    def run(self, request):\n"
        "        from app.providers.runpod.client import RunPodClient\n"
        "        return RunPodClient(None).run(request)\n"
    ),
    "Base rebound after its import": (
        "from app.providers.runpod.client import RunPodClient\nBase = RunPodClient\n"
    ),
    "Base bound under a condition": (
        "if not Base:\n    from app.providers.runpod.client import RunPodClient as Base\n"
    ),
    "Base rebound from a function": (
        "def _install():\n"
        "    global Base\n"
        "    from app.providers.runpod.client import RunPodClient as Base\n"
    ),
}


@pytest.mark.parametrize("rebound", sorted(_NOT_THE_DECLARATIVE_BASE))
def test_a_class_on_another_base_named_base_is_no_table_row(source, rebound):
    """The second WP29 review (2026-10-10): a table row was told by the bare name ``Base`` on
    its class line, and `_row_problems` then left that name unread. A vendor module that
    imports its client as Base (or defines its own Base) made every empty subclass a record,
    and the studio code that builds one and calls its inherited ``.run()`` no paid site."""
    module = "app.providers.runpod.jobs"
    resubmitter = f"{module}.Resubmitter"
    original = source.classes[f"{module}.GenerationJob"]
    assert _is_table_row(source, module, original)
    with _module_grown(
        source, module, _NOT_THE_DECLARATIVE_BASE[rebound] + "class Resubmitter(Base):\n    pass\n"
    ):
        assert not _is_table_row(source, module, source.classes[resubmitter])
        assert not _is_record(source, module, source.classes[resubmitter])
        assert resubmitter in paid_targets(source)
        # GenerationJob's class line names that same Base now: no longer a row either.
        assert not _is_table_row(source, module, original)
    assert _is_table_row(source, module, original)
    assert resubmitter not in source.classes


def test_a_column_default_that_takes_nothing_stays_a_record(source):
    """A lambda that takes no argument cannot be handed the row: a stamp of the time is a
    value like any other."""
    module = "app.providers.runpod.jobs"
    changed = _grown(
        source.classes[f"{module}.GenerationJob"],
        "stamped_at: Mapped[str] = mapped_column(\n"
        "    String(40), default=lambda: datetime.now(UTC).isoformat()\n"
        ")\n"
        "\n"
        "@property\n"
        "def stamps(self) -> list[str]:\n"
        "    return [stamp.strip() for stamp in (self.created_at, self.finished_at) if stamp]\n",
    )
    assert _row_problems(source, module, changed) == []


def test_a_row_property_that_only_converts_its_column_stays_a_record(source):
    module = "app.providers.runpod.jobs"
    changed = _grown(
        source.classes[f"{module}.GenerationJob"],
        "@property\n"
        "def billed_seconds(self) -> Decimal | None:\n"
        "    '''A column read as a number.'''\n"
        "    value = self.billed_seconds_value\n"
        "    return Decimal(value.strip()) if value is not None else None\n"
        "\n"
        "@property\n"
        "def created(self) -> datetime:\n"
        "    return datetime.fromisoformat(self.created_at).replace(tzinfo=UTC)\n"
        "\n"
        "@property\n"
        "def output_keys(self) -> list[str]:\n"
        "    return sorted(str(key).lower() for key, _value in self.output.items())\n"
        "\n"
        "@created.setter\n"
        "def created(self, value: datetime) -> None:\n"
        "    self.created_at = value.isoformat()\n",
    )
    assert _row_problems(source, module, changed) == []


@pytest.mark.parametrize(
    ("column", "a_record"),
    [
        # A plain constant of the module: a value, built by no one.
        ("kind: Mapped[str] = mapped_column(String(20), default=SESSION_STATUSES[0])", True),
        ("words: Mapped[str] = mapped_column(String(200), default=NOT_IN_STEP_WORDS)", True),
        # Something the module built at import: an object whose method SQLAlchemy would call.
        ("noted: Mapped[str] = mapped_column(String(20), default=logger.info)", False),
        ("held: Mapped[bool] = mapped_column(Boolean, default=_LOCKS_GUARD.acquire)", False),
    ],
)
def test_a_row_may_name_its_module_s_constants_but_not_what_it_builds(source, column, a_record):
    """A column default is called by SQLAlchemy at every insert: a reference to a function
    counts as a call here as everywhere in this file, and an object the vendor module built at
    import (its logger, its locks, a client) is not a value of the row."""
    module = "app.providers.runpod.gpu_session"
    changed = _grown(source.classes[f"{module}.GpuSessionRow"], column + "\n")
    assert (_row_problems(source, module, changed) == []) is a_record


_SEND = (
    "from app.providers.runpod.client import RunPodClient\n"
    "def _send(request):\n"
    "    return RunPodClient(None).run(request)\n"
)
#: A container a vendor module writes once as a literal and fills later, and the property of a
#: row that reads it, as (the module's code, the property). The third WP29 review (2026-10-10)
#: measured each passing on GenerationJob: `_module_constant` called a dict, a list or a set
#: display a constant by its one assignment, though anything in the module may fill it later
#: with the vendor's functions; the same function named directly was refused.
_FILLED_CONTAINERS = {
    "a registry its decorator fills": (
        _SEND + "_HANDLERS = {}\n"
        "def register(name):\n"
        "    def wrap(fn):\n"
        "        _HANDLERS[name] = fn\n"
        "        return fn\n"
        "    return wrap\n"
        "@register('image')\n"
        "def _resubmit_image(request):\n"
        "    return RunPodClient(None).run(request)\n",
        "@property\ndef handler(self):\n    return _HANDLERS[self.status]\n",
    ),
    "a mapping filled by update at import": (
        _SEND + "_ROUTES = {}\n_ROUTES.update(client=RunPodClient)\n",
        "@property\ndef route(self):\n    return _ROUTES['client']\n",
    ),
    "a mapping filled from a function": (
        _SEND + "_ROUTES = {}\ndef _install():\n    _ROUTES['client'] = RunPodClient\n",
        "@property\ndef route(self):\n    return _ROUTES['client']\n",
    ),
    "a list whose sender is the key of a sort": (
        _SEND + "_SENDERS = []\n_SENDERS.append(_send)\n",
        "@property\ndef resent(self):\n    return sorted([[]], key=_SENDERS[0])\n",
    ),
    "a set filled at import": (
        _SEND + "_HELD = {None}\n_HELD.add(_send)\n",
        "@property\ndef held(self):\n    return sorted(_HELD, key=str)\n",
    ),
}


@pytest.mark.parametrize("row", sorted(VENDOR_TABLE_ROWS))
@pytest.mark.parametrize("filled", sorted(_FILLED_CONTAINERS))
def test_a_row_may_not_read_a_container_its_module_can_fill(source, row, filled):
    """Only an immutable value (a string, a number, a tuple of them) is a constant a row may
    read: a dict, a list or a set its module wrote as a literal can hold the vendor's functions
    by the time a property reads it."""
    module = row.rsplit(".", 1)[0]
    code, prop = _FILLED_CONTAINERS[filled]
    original = source.classes[row]
    with _module_grown(source, module, code):
        changed = _grown(original, prop)
        assert _row_problems(source, module, changed), filled
        assert not _is_record(source, module, changed)
        source.classes[row] = changed
        assert row in paid_targets(source)
    assert source.classes[row] is original


_RESUBMIT = (
    "def _resubmit(self, config):\n"
    "    from app.providers.runpod.client import RunPodClient\n"
    "    return RunPodClient(config).run(self.request)\n"
)
_ON_INSERT = (
    "def _resubmit_on_insert(mapper, connection, target):\n"
    "    from app.providers.runpod.client import RunPodClient\n"
    "    RunPodClient(None).run(target.request)\n"
)
#: Code a vendor module holds outside a row's class that gives the row a way to the vendor,
#: as (the module it is written in, the code). The WP29 review (2026-10-09) measured the first
#: two passing: `_row_problems` read the class body only, so a listener SQLAlchemy runs at every
#: insert of a GenerationJob, or a method set on the class from outside, left it a record and
#: the studio's readers of the row no paid site.
_ATTACHED_TO_ROWS = {
    "a database listener on the row": (
        "app.providers.runpod.jobs",
        "from sqlalchemy import event\n"
        "@event.listens_for(GenerationJob, 'before_insert')\n" + _ON_INSERT,
    ),
    "a method set on the class from outside it": (
        "app.providers.runpod.jobs",
        _RESUBMIT + "GenerationJob.resubmit = _resubmit\n",
    ),
    "a method set by setattr": (
        "app.providers.runpod.jobs",
        _RESUBMIT + "setattr(GenerationJob, 'resubmit', _resubmit)\n",
    ),
    "a method set through an alias of the class": (
        "app.providers.runpod.jobs",
        _RESUBMIT + "_Row = GenerationJob\n_Row.resubmit = _resubmit\n",
    ),
    "a listener registered by a call, from a function": (
        "app.providers.runpod.jobs",
        _ON_INSERT + "def _install():\n"
        "    from sqlalchemy.event import listen\n"
        "    listen(GenerationJob, 'before_insert', _resubmit_on_insert)\n",
    ),
    "a listener on a column of the row": (
        "app.providers.runpod.jobs",
        "import sqlalchemy as sa\n"
        "@sa.event.listens_for(GenerationJob.status, 'set')\n" + _ON_INSERT,
    ),
    "a decorator of any name that names the row": (
        "app.providers.runpod.jobs",
        "from sqlalchemy import event\non_insert = event.listens_for\n"
        "@on_insert(GenerationJob, 'before_insert')\n" + _ON_INSERT,
    ),
    "a listener on every row (the session's flush)": (
        "app.providers.runpod.jobs",
        "from sqlalchemy import event\nfrom sqlalchemy.orm import Session\n"
        "@event.listens_for(Session, 'before_flush')\n"
        "def _on_flush(session, context, instances):\n"
        "    from app.providers.runpod.client import RunPodClient\n"
        "    RunPodClient(None).run({})\n",
    ),
    "a method set from another vendor module, through its import": (
        "app.providers.runpod.batch",
        _RESUBMIT + "GenerationJob.resubmit = _resubmit\n",
    ),
    "a method set from another vendor module, through the module": (
        "app.providers.runpod.gpu_session",
        _RESUBMIT + "def _install():\n"
        "    from app.providers.runpod import jobs\n"
        "    jobs.GenerationJob.resubmit = _resubmit\n",
    ),
}


@pytest.mark.parametrize("attached", sorted(_ATTACHED_TO_ROWS))
def test_a_row_given_a_way_to_the_vendor_from_outside_its_class_is_flagged(source, attached):
    """The class body is not the whole row: SQLAlchemy runs a listener on the row at every
    write the studio makes, and a method set on the class from outside is called like its
    own. Either makes GenerationJob an adapter again and its readers paid sites."""
    module = "app.providers.runpod.jobs"
    qualname = f"{module}.GenerationJob"
    row = source.classes[qualname]
    written_in, code = _ATTACHED_TO_ROWS[attached]
    tree = source.trees[written_in]
    before = list(tree.body)
    assert _is_record(source, module, row)
    tree.body.extend(ast.parse(code).body)
    try:
        problems = _row_problems(source, module, row)
        assert any(problem.startswith(f"{written_in} line ") for problem in problems), problems
        assert not _is_record(source, module, row)
        assert qualname in paid_targets(source)
        readers = {site.function for site in paid_sites(source) if site.target == qualname}
        assert "app.workflows.watchdog" in {name.rsplit(".", 1)[0] for name in readers}, readers
    finally:
        tree.body[:] = before
    assert _is_record(source, module, row)


@pytest.mark.parametrize(
    "code",
    [
        # What the vendor modules do with their rows today: query, read, build, type.
        "def _ready(session):\n"
        "    return session.scalars(select(GenerationJob).where(\n"
        "        GenerationJob.status.in_(('QUEUED',)), GenerationJob.attempt >= 1\n"
        "    ).order_by(GenerationJob.created_at.desc())).all()\n",
        "def _keep(row: GenerationJob, values: dict) -> GenerationJob:\n"
        "    for key, value in values.items():\n"
        "        setattr(row, key, value)\n"
        "    return GenerationJob(id=row.id)\n",
    ],
)
def test_what_vendor_modules_do_with_their_rows_keeps_them_records(source, code):
    module = "app.providers.runpod.jobs"
    row = source.classes[f"{module}.GenerationJob"]
    tree = source.trees[module]
    before = list(tree.body)
    tree.body.extend(ast.parse(code).body)
    try:
        assert _row_problems(source, module, row) == []
    finally:
        tree.body[:] = before


def test_every_paid_site_the_day_can_reach_is_behind_a_fake(source):
    """Each paid call site in backend/app is faked by the end-to-end fixture or is not on
    the day's path. A sixth vendor call added to the day without a fake fails here."""
    from test_autonomous_day_end_to_end import VENDOR_FAKES

    escaped = escaped_sites(set(VENDOR_FAKES), source)
    assert not escaped, "paid calls the day reaches with no fake in front of them:\n" + (
        _describe(escaped)
    )


def test_the_scan_names_the_motion_chooser_when_its_fake_is_missing(source):
    """The fake list as it stood before 2026-09-18, and the site the rehearsal met on the
    Owner's data: without the motion chooser's fake the day reaches RunwayVideoAdapter."""
    from test_autonomous_day_end_to_end import VENDOR_FAKES

    incomplete = set(VENDOR_FAKES) - {("app.media.factory", "motion_for_scene")}
    named = {(site.function, site.target) for site, _ in escaped_sites(incomplete, source)}
    assert (
        "app.media.factory.video_provider_for",
        "app.providers.runway.RunwayVideoAdapter",
    ) in named, named


def test_every_fake_names_something_that_exists(source):
    """A fake of a name the code no longer has would cut nothing and still read as cover."""
    from test_autonomous_day_end_to_end import VENDOR_FAKES

    for module, attribute in VENDOR_FAKES:
        assert module in source.trees, module
        assert attribute in source.top_defs[module] or attribute in source.top_imports[module], (
            module,
            attribute,
        )


# ------------------------------------------- every paid path is authorised and booked (TS-09)
#
# 2026-10-02 (CONTINUE_REDOS_E2E; TS-09, MONEY-14). The scan above certifies that the tests fake
# every vendor the *day* can reach. It does not certify that a real spend is behind the Owner's
# policy: it starts only from the day, and only app/providers counted as paid, so the routes
# (his presses on the sheet, a redo, the reference set, a render), the worker's other tasks
# (FILM_CONTINUE above all), the watchdog and the configured language model
# (app.integrations.llm: OpenAI and Anthropic) were outside it.
#
# This second scan starts from every route (each function a router factory or app.main
# registers, one root per route), every task the worker runs (one root per handler), the
# worker's pass, the watchdog and the day, and follows the same call graph. A function that
# calls the Policy Kernel or a gate of its own (`GATE_NAMES`) is a door: nothing behind it is
# followed for the gate check. A function that writes the books (`BOOKING_NAMES`) is a door
# for the booking check. Every function that calls a paid method of an adapter
# (`PAID_METHODS`, by attribute or by `getattr` string) and that a root reaches through no door
# is named with its path, unless (root, site, check) is in the reviewed allowlist with its
# reason. Uploading spends nothing and is checked for the gate only. Over-approximated like the
# scan above: a method called on an unknown object is followed to every method of that name.
# What it cannot see: the order of calls inside one function (a door counts wherever it
# stands in the function), `getattr` by computed string, code built at run time.

#: The adapter methods that spend: a still, a shot, candidates, a voice, a language model's
#: tokens; and the upload, which spends nothing but must pass the publishing gate.
PAID_METHODS = frozenset(
    {
        "create_generation",
        "generate_image",
        "generate_candidates",
        "synthesize",
        "generate",
        # A RunPod Serverless round (2026-10-08): one batch job carrying every item of a paid
        # round, sent only inside an approved paid step's GPU session (`media.gpu_batch`).
        "submit_batch",
    }
)
GATED_ONLY_METHODS = frozenset({"upload_video"})
#: The Policy Kernel and the gates in front of money or a channel. `legacy_render_vendors` is
#: the whole-film render's refusal of every paid vendor (PaidVendorRefused, 2026-09-26):
#: that path buys only from fakes and local stand-ins.
GATE_NAMES = frozenset(
    {
        "may_act",
        "mode_refusal",
        "evaluate_publishing_gate",
        "may_run_agent",
        "may_spend_step",
        "legacy_render_vendors",
    }
)
#: What writes a purchase into the books: the sheet's bookings, the render's cost rows, the
#: credit ledger, and the agent run record that carries a model's tokens.
BOOKING_NAMES = frozenset(
    {
        "book_purchase",
        "book_step_cost",
        "book_interrupted_step",
        "_book_redo",
        "record_render_costs",
        "record_failed_render_cost",
        "record_credit_spend",
        "record_provider_cost",
        "AgentRun",
    }
)
#: The other ways work starts without a person: the worker's tasks, its pass, the watchdog,
#: and the day.
TASK_ROOTS = (
    "app.workflows.worker.build_task_handlers",
    "app.workflows.worker.worker_pass",
    "app.workflows.watchdog.run_watchdog",
    *ROOTS,
)
_ROUTE_DECORATORS = frozenset(
    {"get", "post", "put", "patch", "delete", "websocket", "api_route", "api_websocket_route"}
)

#: Reviewed exceptions: (root, paid call site, check) -> why no door of that kind is needed
#: on that path, or which item owns closing it. Each one was read on 2026-10-02.
AUTHORISATION_ALLOWLIST: dict[tuple[str, str, str], str] = {}

# The suspended RunPod prepared-batch runner hides two existing protective
# boundaries from this conservative interprocedural AST scan:
#
# * authorisation: the redo has an Owner/Policy permit, and every round in
#   gpu_batch.run_rounds calls its stop_reason() BEFORE submit_batch;
# * booking: run_rounds commits the quote to SpendMeter before submit_batch,
#   and the outer purchase_flow resumes the owning step to settle that quote
#   against its held budget. The static graph cannot follow the generator's
#   send(summary) back to each stage's book_* function.
#
# Only these exact roots and this exact purchase site are exceptions; adding
# another route still requires a review. In particular, nothing here
# allowlists unrelated vendor purchases or removes the runtime money guard.
_RUNPOD_ROUNDS_SITE = "app.media.gpu_batch.run_rounds"
AUTHORISATION_ALLOWLIST[
    ("app.media.router.create_media_router.post_scene_redo", _RUNPOD_ROUNDS_SITE, "gate")
] = "The redo's StepPermit and the guard's stop_reason are verified before the next RunPod round."
for _root in (
    "app.media.router.create_media_router.post_scene_redo",
    "app.workflows.worker.build_task_handlers.film_continue",
    "app.runbook.stages.build_stage_runners",
):
    AUTHORISATION_ALLOWLIST[(_root, _RUNPOD_ROUNDS_SITE, "booking")] = (
        "The prepared purchase resumes its outer step after run_rounds: "
        "the SpendMeter quote is charged before the batch and settled by "
        "that step's budget booking; the AST graph loses the generator return."
    )

#: No upload is allowlisted (2026-10-02, PUB-04): `execute_publication` asks
#: `evaluate_publishing_gate` again before every upload, the Owner's press and the
#: watchdog's retry alike, so the gate is a door on those paths now.
#: The rehearsal assembles the paid files already on disk (`rehearsal.rehearse`): no image,
#: video or voice adapter is handed to the render (the narration is the recorded voice played
#: back), so the vendor calls the graph reaches inside `assemble_video_job` cannot happen there.
for _site in (
    "app.media.assembler.assemble_video_job",
    "app.media.assembler._generate_motion",
    "app.media.factory.still_from_chain",
):
    for _check in ("gate", "booking"):
        AUTHORISATION_ALLOWLIST[
            ("app.media.router.create_media_router.post_adopt_existing_files", _site, _check)
        ] = (
            "rehearse() passes assemble_from_takes no image, video or voice adapter (recorded "
            "voices only); the statically reachable vendor calls have no adapter to call."
        )


class _RouteSource(_Source):
    """The source, with each route and each worker task as a function of its own: the
    factories that register them are one function to the scan above, so one gate anywhere in
    a router would have counted as a door for every route in it."""

    def __init__(self) -> None:
        super().__init__()
        self.route_roots: list[str] = []
        routers = {
            _module_name(path)
            for path in APP.glob("*/router.py")
            if "__pycache__" not in path.parts
        } | {"app.main"}
        factories = [
            qualname
            for qualname, (module, _node) in list(self.functions.items())
            if module in routers and qualname.count(".") == module.count(".") + 1
        ]
        for factory in [*factories, "app.workflows.worker.build_task_handlers"]:
            module, node = self.functions[factory]
            imports = [
                child
                for child in getattr(node, "body", [])
                if isinstance(child, ast.Import | ast.ImportFrom)
            ]
            nested = [
                child
                for child in getattr(node, "body", [])
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            routes = [n for n in nested if factory.endswith("build_task_handlers") or _a_route(n)]
            if not routes:
                if module in routers and _a_route(node):
                    self.route_roots.append(factory)
                continue
            for route in routes:
                # The factory's own imports are in scope for the route; nothing else of it.
                body = [*imports, *route.body]
                copy = ast.FunctionDef(
                    name=route.name,
                    args=route.args,
                    body=body,
                    decorator_list=[],
                    returns=None,
                    type_params=[],
                )
                ast.copy_location(copy, route)
                qualname = f"{factory}.{route.name}"
                self.functions[qualname] = (module, copy)
                self.route_roots.append(qualname)


def _a_route(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        call = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(call, ast.Attribute) and call.attr in _ROUTE_DECORATORS:
            return True
    return False


@pytest.fixture(scope="module")
def routes() -> _RouteSource:
    return _RouteSource()


def _roots(source: _RouteSource) -> list[str]:
    tasks = [root for root in TASK_ROOTS if root in source.functions]
    handlers = [r for r in source.route_roots if ".build_task_handlers." in r]
    return [
        *[r for r in source.route_roots if ".build_task_handlers." not in r],
        *handlers,
        *[t for t in tasks if t != "app.workflows.worker.build_task_handlers"],
    ]


def _names_called(node: ast.AST) -> set[str]:
    """Every name a function's body refers to by a bare name or an attribute."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _paid_calls(node: ast.AST, methods: frozenset[str]) -> set[str]:
    """The paid adapter methods a function calls: `x.method(...)`, or `getattr(x, "method")`."""
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in methods:
            found.add(func.attr)
        elif (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and len(child.args) >= 2
            and isinstance(child.args[1], ast.Constant)
            and child.args[1].value in methods
        ):
            found.add(str(child.args[1].value))
    return found


class _Graph:
    """The call graph of `_edges`, computed once per function."""

    def __init__(self, source: _RouteSource) -> None:
        self.source = source
        self.edges: dict[str, list[str]] = {}
        self.names: dict[str, set[str]] = {}

    def callees(self, qualname: str) -> list[str]:
        if qualname not in self.edges:
            targets: list[str] = []
            for edge in _edges(self.source, qualname):
                if edge.target in self.source.classes:
                    targets.extend(
                        f"{edge.target}.{m}"
                        for m in ("__init__", "__post_init__")
                        if f"{edge.target}.{m}" in self.source.functions
                    )
                elif edge.target in self.source.functions:
                    targets.append(edge.target)
            self.edges[qualname] = list(dict.fromkeys(targets))
        return self.edges[qualname]

    def calls(self, qualname: str) -> set[str]:
        if qualname not in self.names:
            self.names[qualname] = _names_called(self.source.functions[qualname][1])
        return self.names[qualname]


def undoored_paths(
    graph: _Graph, root: str, doors: frozenset[str], methods: frozenset[str]
) -> list[tuple[str, str, list[str]]]:
    """(site, method, path) for every function calling a paid method that ``root`` reaches
    through functions none of which calls a door."""
    source = graph.source
    parent: dict[str, str | None] = {root: None}
    queue: deque[str] = deque([root])
    found: list[tuple[str, str, list[str]]] = []
    while queue:
        current = queue.popleft()
        module, node = source.functions[current]
        if _paid_module(source, module):
            continue  # the vendor's own insides; its callers are the sites
        if graph.calls(current) & doors:
            continue  # a door: what lies behind it is decided here
        for method in sorted(_paid_calls(node, methods)):
            chain: list[str] = []
            step: str | None = current
            while step is not None:
                chain.append(step)
                step = parent[step]
            found.append((current, method, list(reversed(chain))))
        for target in graph.callees(current):
            if target not in parent:
                parent[target] = current
                queue.append(target)
    return found


CHECKS = {
    "gate": (GATE_NAMES, PAID_METHODS | GATED_ONLY_METHODS),
    "booking": (BOOKING_NAMES, PAID_METHODS),
}


@pytest.fixture(scope="module")
def undoored(routes) -> dict[str, list[tuple[str, str, str, list[str]]]]:
    graph = _Graph(routes)
    found: dict[str, list[tuple[str, str, str, list[str]]]] = {}
    for check, (doors, methods) in CHECKS.items():
        found[check] = [
            (root, site, method, chain)
            for root in _roots(routes)
            for site, method, chain in undoored_paths(graph, root, doors, methods)
        ]
    return found


def _say(escaped: list[tuple[str, str, str, list[str]]]) -> str:
    return "\n".join(
        f"{site} calls .{method}()\n    reached by: {' -> '.join(chain)}"
        for _root, site, method, chain in escaped
    )


def test_the_authorisation_scan_starts_from_each_route_each_task_and_the_day(routes):
    roots = _roots(routes)
    assert "app.media.router.create_media_router.post_sheet_step" in roots
    assert "app.media.router.create_media_router.post_scene_redo" in roots
    assert "app.workflows.worker.build_task_handlers.film_continue" in roots
    assert "app.workflows.worker.build_task_handlers.daily_run" in roots
    assert "app.runbook.services.execute_daily_run" in roots
    assert len([r for r in roots if ".router." in r]) > 100, len(roots)
    # It sees every paid method the studio calls, including the stills step's getattr.
    called = {
        method
        for _qualname, (module, node) in routes.functions.items()
        if not _paid_module(routes, module)
        for method in _paid_calls(node, PAID_METHODS | GATED_ONLY_METHODS)
    }
    assert called == PAID_METHODS | GATED_ONLY_METHODS, called


def test_the_configured_language_model_counts_as_paid(source):
    """MONEY-14: OpenAI and Anthropic run through app.integrations.llm, outside app/providers;
    the first scan names its construction sites too (none of them on the day's path)."""
    sites = {site.function for site in paid_sites(source) if site.vendor == "app.integrations.llm"}
    assert sites, "no construction of the configured language model was found"


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_every_paid_call_has_its_door_on_every_path(undoored, check):
    """Every paid call is behind the Owner's policy or a gate (``gate``) and its purchase is
    written into the books on the same path (``booking``), or reviewed in the allowlist."""
    escaped = [
        item for item in undoored[check] if (item[0], item[1], check) not in AUTHORISATION_ALLOWLIST
    ]
    assert not escaped, f"paid calls reachable with no {check} door:\n" + _say(escaped)


def test_the_allowlist_names_only_paths_that_still_exist(undoored):
    seen = {(root, site, check) for check in CHECKS for root, site, _m, _c in undoored[check]}
    stale = set(AUTHORISATION_ALLOWLIST) - seen
    assert not stale, f"allowlisted paths the scan no longer finds: {sorted(stale)}"


def test_the_scan_names_a_paid_call_when_its_door_is_taken_away(routes):
    """A check that cannot fail certifies nothing: without the Policy Kernel among the doors,
    the Owner's press on the sheet's motion step reaches the motion purchase undoored."""
    graph = _Graph(routes)
    escaped = undoored_paths(
        graph,
        "app.media.router.create_media_router.post_sheet_step",
        GATE_NAMES - {"may_act", "mode_refusal", "may_spend_step"},
        PAID_METHODS,
    )
    assert any(method == "create_generation" for _site, method, _chain in escaped), escaped


def test_runpod_rounds_count_as_paid_and_their_modules_as_vendors(source):
    """2026-10-08: RunPod Serverless buys a round as one batch job (`batch.submit_batch`,
    through `media.gpu_batch.run_rounds`), with its inputs in the Owner's bucket (`s3`) and
    its GPU switched by `endpoint`/`gpu_session`. Each of those modules is a vendor to this
    scan, and the round's call is a paid method the gate and booking checks follow."""
    for module in (
        "app.providers.runpod.batch",
        "app.providers.runpod.s3",
        "app.providers.runpod.endpoint",
        "app.providers.runpod.gpu_session",
    ):
        assert module in source.paths, module
        assert _paid_module(source, module), module
    assert "submit_batch" in PAID_METHODS
    callers = {
        qualname
        for qualname, (module, node) in source.functions.items()
        if not _paid_module(source, module) and "submit_batch" in _paid_calls(node, PAID_METHODS)
    }
    assert callers == {"app.media.gpu_batch.run_rounds"}, callers


def test_a_runpod_round_with_the_real_transport_never_leaves_the_machine(engine, tmp_path):
    """The backstop: a round handed the studio's real transport in a test is refused by the
    network guard before any byte reaches RunPod or the bucket; nothing is reserved as sent."""
    from decimal import Decimal

    from app.providers.media_http import MediaProviderError
    from app.providers.runpod.adapters import RunPodImageAdapter
    from app.providers.runpod.batch import BatchRequest
    from app.providers.runpod.config import RunPodConfig
    from app.providers.runpod.jobs import GenerationJob
    from sqlalchemy import select
    from sqlalchemy.orm import Session as SqlSession

    adapter = RunPodImageAdapter(
        RunPodConfig(
            _env_file=None,
            enabled=True,
            mode="serverless",
            api_key="fake-key",  # pragma: allowlist secret — synthetic test value
            stills_endpoint_id="stills-ep",
            s3_endpoint_url="https://account.r2.example",
            s3_bucket="amn-films",
            s3_access_key_id="AKIDEXAMPLE",  # pragma: allowlist secret
            s3_secret_access_key="synthetic",  # pragma: allowlist secret
            max_retries=0,
        ),
        engine,
        storage_root=tmp_path,
    )
    picture = b"\x89PNG\r\n\x1a\n" + b"\0" * 32

    noted: list[str] = []
    submitted: list[object] = []

    class Session:
        id = "s"

        def note_job(self, job, *, session=None):
            noted.append(job)

    # The guard refuses the lookup with an AssertionError; the adapter may wrap it.
    with pytest.raises((MediaProviderError, AssertionError)):
        adapter.submit_batch(
            [
                BatchRequest(
                    "image",
                    "film",
                    "1",
                    0,
                    1,
                    "Qwen-Image-2512",
                    "words",
                    None,
                    1,
                    1530,
                    2720,
                    None,
                    None,
                    (picture,),
                    None,
                    Decimal(0),
                )
            ],
            session=Session(),
            on_submitted=submitted.append,
        )
    # Refused at the bucket upload (the first byte out): no job id, no take, no RunPod call.
    assert noted == [] and submitted == []
    with SqlSession(engine) as s:
        assert all(row.remote_job_id is None for row in s.scalars(select(GenerationJob)))
