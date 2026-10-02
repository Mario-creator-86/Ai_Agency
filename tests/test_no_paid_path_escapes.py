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
import socket
from collections import deque
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


def _is_record(node: ast.ClassDef) -> bool:
    """An exception or a plain record: something a vendor module defines that calls nobody."""
    names = [node.name] + [
        base.id if isinstance(base, ast.Name) else getattr(base, "attr", "") for base in node.bases
    ]
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
    adapters = {
        qualname
        for qualname, node in source.classes.items()
        if _paid_module(source, qualname.rsplit(".", 1)[0]) and not _is_record(node)
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
    {"create_generation", "generate_image", "generate_candidates", "synthesize", "generate"}
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
