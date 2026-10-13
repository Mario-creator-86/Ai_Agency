"""The answers these routers write for the Owner are Romanian (PAGE-11).

The page shows a refusal's ``detail`` as it is: «Storyboard not found», «Internal error» and
«A budget cannot be negative.» reached the Owner word for word. This reads every literal a
route hands to ``HTTPException(detail=...)`` (and every literal refusal of the budget module)
and fails on English. Details built from an exception's own text are out of reach of a static
check and stay the service's responsibility.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ROUTERS = (
    "backend/app/media/router.py",
    "backend/app/agents/router.py",
    "backend/app/analytics/router.py",
)
BUDGET = "backend/app/economy/budget.py"

ENGLISH = re.compile(
    r"\b(not|found|error|errors|failed|missing|internal|database|during|execution|asset|"
    r"agent|strategy|reservation|active|entry|rendered|render|job|report|"
    r"file|disk|cannot|the|no|run|on|for|is|present)\b",
    re.IGNORECASE,
)


def _literal_text(node: ast.AST) -> list[str]:
    """The literal words of a string or f-string expression (format fields left out)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
    if isinstance(node, ast.BinOp):
        return _literal_text(node.left) + _literal_text(node.right)
    if isinstance(node, ast.Dict):
        return [text for value in node.values if value for text in _literal_text(value)]
    return []


def _details(path: str) -> list[tuple[int, str]]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "HTTPException":
            for keyword in node.keywords:
                if keyword.arg == "detail":
                    found += [(node.lineno, text) for text in _literal_text(keyword.value)]
    return found


def _refusals(path: str) -> list[tuple[int, str]]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
            found += [(node.lineno, text) for text in _literal_text(node.exc.args[0])]
    return found


@pytest.mark.parametrize("path", ROUTERS)
def test_no_english_detail_is_left_in_the_router(path):
    english = [
        f"{path}:{line} {text!r}"
        for line, text in _details(path)
        if text.strip() and ENGLISH.search(text)
    ]
    assert english == []


def test_the_budget_refuses_in_romanian():
    english = [
        f"{BUDGET}:{line} {text!r}"
        for line, text in _refusals(BUDGET)
        if text.strip() and ENGLISH.search(text)
    ]
    assert english == []


def test_the_scan_sees_an_english_detail():
    """The check itself: an English literal is found, a Romanian one is not."""
    assert ENGLISH.search("Storyboard not found")
    assert ENGLISH.search("Internal error")
    assert not ENGLISH.search("Filmul nu există.")
    assert not ENGLISH.search("Pas necunoscut: ")
