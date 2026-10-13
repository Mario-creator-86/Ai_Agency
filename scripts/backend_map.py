"""Static inventory of the backend: every function, what it calls, and how far it is from the LLM.

Every language-model call in the studio leaves through one function,
`app.agents.services.run_agent_task` (it composes the agent's identity, applies the policy
kernel and the token/USD ceilings, calls the provider adapter and records the run). So "does
this function involve an LLM?" has an exact static answer: is there a call path from it to
that function, and how many hops long is it.

    uv run python scripts/backend_map.py

writes, under docs/project/backend_map/:

- inventory.json  every module and function: lines, first docstring line, HTTP route if it
                  is one, `llm_distance` (1 = calls run_agent_task itself, 2 = calls a
                  function that does, ...; null = no path), and the LLM-reaching callees.
- callgraph.json  resolved internal call edges (caller -> callees), for anyone tracing a path.
- STATS.md        the numbers per package, generated; never edit it by hand.

The resolution is by name through each module's imports, `self.`/`cls.` methods and module
attributes; a function handed over as a value (a callback, `partial(...)`) counts as an edge.
Calls through objects whose type is not visible statically (a provider instance, a dict of
handlers) are not resolved, so a distance is a lower bound on reach, never a claim of absence
for dynamic dispatch. The narrative map beside these files says what each part decides.
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
OUT = ROOT / "docs" / "project" / "backend_map"
LLM_CORE = "app.agents.services.run_agent_task"
#: Plumbing every agent call passes through, adding no decision of its own: the choke point,
#: the structured-answer retry, the employee's multi-model strategy and two modules' thin
#: "failure is a degradation" wrappers. A function that calls one of these is a call site.
LLM_GATEWAY = {
    LLM_CORE,
    "app.agents.structured.structured_run",
    "app.agents.ensemble.run_with_strategy",
    "app.agents.reviews._run",
    "app.media.prompt_agent._run",
}
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "websocket"}
#: A string constant at least this long is counted as prompt or message text, not logic.
LONG_TEXT = 160


def module_name(path: Path) -> str:
    parts = path.relative_to(APP.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def first_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    return " ".join(doc.strip().split("\n\n")[0].split())


class Module:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = module_name(path)
        self.is_package = path.name == "__init__.py"
        self.source = path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source, filename=str(path))
        self.lines = len(self.source.splitlines())
        self.imports: dict[str, str] = {}
        self.defs: dict[str, ast.AST] = {}  # qualified name -> node
        self.classes: set[str] = set()
        #: Route handlers declared inside a router factory: recorded as defs of their own,
        #: and left out of the factory's own walk.
        self.nested: set[int] = set()

    def package(self) -> str:
        return self.name if self.is_package else self.name.rsplit(".", 1)[0]

    def collect(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.imports[alias.asname] = alias.name
                    else:
                        self.imports[alias.name.split(".")[0]] = alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    pkg = self.package().split(".")
                    pkg = pkg[: len(pkg) - (node.level - 1)]
                    base = ".".join(pkg + ([base] if base else []))
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = f"{base}.{alias.name}"
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defs[f"{self.name}.{node.name}"] = node
            elif isinstance(node, ast.ClassDef):
                self.classes.add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.defs[f"{self.name}.{node.name}.{item.name}"] = item
        for parent, node in list(self.defs.items()):
            for sub in ast.walk(node):
                if (
                    sub is not node
                    and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and route_of(sub)
                ):
                    self.defs[f"{parent}.{sub.name}"] = sub
                    self.nested.add(id(sub))


def walk_own(node: ast.AST, nested: set[int]) -> list[ast.AST]:
    """`ast.walk`, leaving out the subtrees recorded as defs of their own."""
    out, stack = [], [node]
    while stack:
        current = stack.pop()
        out.append(current)
        for child in ast.iter_child_nodes(current):
            if id(child) not in nested:
                stack.append(child)
    return out


def route_of(node: ast.AST) -> str | None:
    for deco in getattr(node, "decorator_list", []):
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr in HTTP_VERBS
            and deco.args
            and isinstance(deco.args[0], ast.Constant)
            and isinstance(deco.args[0].value, str)
        ):
            return f"{deco.func.attr.upper()} {deco.args[0].value}"
    return None


def resolve(
    module: Module, node: ast.AST, cls: str | None, known: set[str], modules: set[str]
) -> str | None:
    """The qualified name a Name/Attribute refers to, when it is a function we know."""
    if isinstance(node, ast.Name):
        local = f"{module.name}.{node.id}"
        if local in known:
            return local
        target = module.imports.get(node.id)
        if target in known:
            return target
        return None
    if isinstance(node, ast.Attribute):
        value = node.value
        if isinstance(value, ast.Name):
            if value.id in {"self", "cls"} and cls:
                candidate = f"{module.name}.{cls}.{node.attr}"
                return candidate if candidate in known else None
            if value.id in module.classes:
                candidate = f"{module.name}.{value.id}.{node.attr}"
                return candidate if candidate in known else None
            target = module.imports.get(value.id)
            if target:
                candidate = f"{target}.{node.attr}"
                if candidate in known:
                    return candidate
        dotted = []
        cursor: ast.AST = node
        while isinstance(cursor, ast.Attribute):
            dotted.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            head = module.imports.get(cursor.id, cursor.id)
            candidate = ".".join([head, *reversed(dotted)])
            if candidate in known:
                return candidate
    return None


def main() -> None:
    modules = [Module(p) for p in sorted(APP.rglob("*.py")) if "__pycache__" not in p.parts]
    for module in modules:
        module.collect()
    known = {name for module in modules for name in module.defs}
    module_names = {module.name for module in modules}
    # A renamed gateway would silently turn every call site into "no LLM": refuse instead.
    if missing := sorted(LLM_GATEWAY - known):
        raise SystemExit(f"LLM gateway functions not found (renamed?): {missing}")

    edges: dict[str, set[str]] = defaultdict(set)
    meta: dict[str, dict] = {}
    for module in modules:
        for qualified, node in module.defs.items():
            rest = qualified[len(module.name) + 1 :].split(".")
            cls = rest[0] if len(rest) == 2 else None
            long_text = 0
            for sub in walk_own(node, module.nested):
                if isinstance(sub, (ast.Name, ast.Attribute)) and isinstance(
                    getattr(sub, "ctx", None), ast.Load
                ):
                    target = resolve(module, sub, cls, known, module_names)
                    if target and target != qualified:
                        edges[qualified].add(target)
                elif (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                    and len(sub.value) >= LONG_TEXT
                ):
                    long_text += len(sub.value)
            end = getattr(node, "end_lineno", node.lineno)
            meta[qualified] = {
                "name": ".".join(rest),
                "line": node.lineno,
                "lines": end - node.lineno + 1,
                "doc": first_line(ast.get_docstring(node)),
                "route": route_of(node),
                "async": isinstance(node, ast.AsyncFunctionDef),
                "long_text_chars": long_text,
            }

    # Distance to the LLM: breadth-first over the reversed graph from run_agent_task.
    callers: dict[str, set[str]] = defaultdict(set)
    for caller, callees in edges.items():
        for callee in callees:
            callers[callee].add(caller)
    distance: dict[str, int] = {LLM_CORE: 0}
    queue = deque([LLM_CORE])
    while queue:
        current = queue.popleft()
        for caller in callers[current]:
            if caller not in distance:
                distance[caller] = distance[current] + 1
                queue.append(caller)

    inventory = []
    for module in modules:
        functions = []
        for qualified in module.defs:
            record = dict(meta[qualified])
            record["llm_distance"] = distance.get(qualified)
            record["llm_callees"] = sorted(c for c in edges[qualified] if c in distance)
            record["llm_call_site"] = qualified not in LLM_GATEWAY and bool(
                edges[qualified] & LLM_GATEWAY
            )
            record["llm_gateway"] = qualified in LLM_GATEWAY
            functions.append(record)
        inventory.append(
            {
                "module": module.name,
                "path": module.path.relative_to(ROOT).as_posix(),
                "lines": module.lines,
                "doc": first_paragraph(ast.get_docstring(module.tree)),
                "functions": functions,
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inventory.json").write_text(
        json.dumps(
            {
                "generated_by": "scripts/backend_map.py",
                "llm_core": LLM_CORE,
                "note": (
                    "llm_distance: 0 = the LLM choke point, 1 = calls it directly, n = n hops; "
                    "null = no static path. Static, name-based; dynamic dispatch not resolved. "
                    "llm_call_site: calls one of llm_gateway (the plumbing) itself, i.e. the "
                    "function that writes the question and uses the answer."
                ),
                "llm_gateway": sorted(LLM_GATEWAY),
                "modules": inventory,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (OUT / "callgraph.json").write_text(
        json.dumps(
            {k: sorted(v) for k, v in sorted(edges.items()) if v}, ensure_ascii=False, indent=0
        ),
        encoding="utf-8",
    )
    write_stats(inventory)


def package_of(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 2 else module


def write_stats(inventory: list[dict]) -> None:
    rows: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    total: dict[str, int] = defaultdict(int)
    for module in inventory:
        for bucket in (rows[package_of(module["module"])], total):
            bucket["files"] += 1
            bucket["lines"] += module["lines"]
            for fn in module["functions"]:
                d = fn["llm_distance"]
                bucket["functions"] += 1
                bucket["routes"] += 1 if fn["route"] else 0
                bucket["fn_lines"] += fn["lines"]
                bucket["text_chars"] += fn["long_text_chars"]
                if d == 1:
                    bucket["direct"] += 1
                    bucket["direct_lines"] += fn["lines"]
                if d is not None and d >= 1:
                    bucket["reach"] += 1
                    bucket["reach_lines"] += fn["lines"]
                if d is not None and d <= 2 and d >= 1:
                    bucket["near"] += 1
                if fn["llm_call_site"]:
                    bucket["sites"] += 1
                    bucket["site_lines"] += fn["lines"]

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.0f}%" if b else "—"

    out = [
        "# Backend statistics (generated)",
        "",
        "Generated by `scripts/backend_map.py` from the AST of `backend/app`. Do not edit by hand;",
        "re-run the script. `direct` = functions that call `run_agent_task` (the one function",
        "every LLM call goes through) themselves; `≤2 hops` adds the functions one call further",
        "out; `reach` = any static path to it. Lines are the functions' own lines.",
        "",
        "| package | files | lines | functions | HTTP routes | LLM call sites | direct LLM fns | "
        "≤2 hops | reach LLM (fns) | reach LLM (lines) | prompt/message text (chars) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def row(label: str, r: dict) -> str:
        return (
            f"| {label} | {r['files']} | {r['lines']} | {r['functions']} | {r['routes']} | "
            f"{r['sites']} | {r['direct']} | {r['near']} | "
            f"{r['reach']} ({pct(r['reach'], r['functions'])}) | "
            f"{r['reach_lines']} ({pct(r['reach_lines'], r['fn_lines'])}) | {r['text_chars']} |"
        )

    for name in sorted(rows, key=lambda n: -rows[n]["lines"]):
        out.append(row(f"`{name}`", rows[name]))
    t = total
    out.append(row("**total**", t))
    out += [
        "",
        f"Functions that call `run_agent_task` directly: **{t['direct']}** of {t['functions']} "
        f"({pct(t['direct'], t['functions'])}), holding {t['direct_lines']} lines "
        f"({pct(t['direct_lines'], t['fn_lines'])} of all function lines).",
        "",
        f"LLM call sites (functions that write a question to a model and use the answer, i.e. "
        f"call the gateway {sorted(LLM_GATEWAY)} themselves): **{t['sites']}**, holding "
        f"{t['site_lines']} lines ({pct(t['site_lines'], t['fn_lines'])} of all function lines).",
        "",
        "## The LLM call sites",
        "",
        "| module | function | lines | docstring |",
        "|---|---|---:|---|",
    ]
    for module in inventory:
        for fn in module["functions"]:
            if fn["llm_call_site"]:
                out.append(
                    f"| `{module['module']}` | `{fn['name']}` (L{fn['line']}) | {fn['lines']} | "
                    f"{fn['doc'].replace('|', '/')} |"
                )
    (OUT / "STATS.md").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
