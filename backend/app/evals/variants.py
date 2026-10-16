"""What the writers' evaluation compares: named variants of the brief and the identity.

The Owner's decision of 2026-10-16: no playbook or judge change goes live without a comparison
on the frozen harness (`scripts/writer_eval.py`). A variant is a name the harness is run with
(``--variant``) and the patches it installs for the length of each writer's call — a slimmer
identity profile, a playbook appended to the brief, a rewritten paragraph. ``baseline`` is
today's code, untouched.

The next steps of the quality plan register theirs here, for example::

    register(Variant(
        "slim-identity",
        "the CRAFT profile: role, contract slice, Owner policies, no 120 newest memories",
        lambda: replaced(agent_services, "compose_identity", craft_profile),
    ))

`replaced` fails loudly when the patched name no longer exists, so a variant written against
a function that moved can never measure today's code under its own name. `fingerprint` hashes
what the writer is given as the variant leaves it, so every result names the brief it was
measured on (the audit's EVAL HINT 7: ``write_script`` was stamped «v1» for 111 runs across
two different briefs).
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Variant:
    """A named change to what the writers are given, installed around each writer's call."""

    name: str
    description: str
    install: Callable[[], AbstractContextManager[Any]]


_VARIANTS: dict[str, Variant] = {}


def register(variant: Variant) -> Variant:
    """Add a variant; a name already taken is refused (two variants under one name would make
    two different measurements look like one)."""
    if not variant.name or variant.name != variant.name.strip() or "/" in variant.name:
        raise ValueError(f"Numele variantei nu este bun: {variant.name!r}")
    if variant.name in _VARIANTS:
        raise ValueError(f"Varianta {variant.name!r} există deja")
    _VARIANTS[variant.name] = variant
    return variant


def variant(name: str) -> Variant:
    """The variant called ``name``; ValueError naming the known ones otherwise."""
    try:
        return _VARIANTS[name]
    except KeyError:
        known = ", ".join(sorted(_VARIANTS))
        raise ValueError(f"Varianta {name!r} nu există; cunoscute: {known}") from None


def names() -> list[str]:
    return sorted(_VARIANTS)


@contextmanager
def replaced(owner: Any, attribute: str, value: Any) -> Iterator[None]:
    """``owner.attribute`` is ``value`` inside the block and what it was after it. A name the
    owner does not have is an AttributeError, never a silent new attribute."""
    if not hasattr(owner, attribute):
        raise AttributeError(f"{owner!r} nu are {attribute!r}: varianta a rămas în urma codului")
    before = getattr(owner, attribute)
    setattr(owner, attribute, value)
    try:
        yield
    finally:
        setattr(owner, attribute, before)


register(
    Variant(
        "baseline",
        "today's code: the writers' brief and identity exactly as the studio composes them",
        nullcontext,
    )
)


#: What each writer is given, by module and name: the brief's text and the functions that
#: assemble it, and the identity every run carries (`agents.identity`).
BRIEF_PARTS: dict[str, tuple[tuple[str, str], ...]] = {
    "serial": (
        ("app.story.services", "_INSTRUCTIONS"),
        ("app.story.services", "SHOW_TONE"),
        ("app.story.services", "EPISODE_TEMPLATE_VERSION"),
        ("app.story.services", "_PICTURE_LESSONS_HEAD"),
        ("app.story.services", "_rewrite_section"),
        ("app.story.services", "_events_block"),
        ("app.story.services", "_plan_block"),
        ("app.story.services", "_previously"),
        ("app.story.services", "_who_they_are"),
        ("app.story.services", "_in_one_line"),
        ("app.agents.language", "audience_language_line"),
    ),
    "factual": (
        ("app.factual.agent_pipeline", "_WRITE_INSTRUCTIONS"),
        ("app.factual.agent_pipeline", "_write_instructions"),
        ("app.factual.agent_pipeline", "_platform_paragraph"),
        ("app.factual.agent_pipeline", "_judgement_paragraph"),
        ("app.factual.agent_pipeline", "_chosen_idea_paragraph"),
        ("app.factual.agent_pipeline", "_cost_paragraph"),
        ("app.factual.agent_pipeline", "_measured_paragraph"),
        ("app.agents.language", "audience_language_line"),
    ),
}
IDENTITY_PARTS: tuple[tuple[str, str], ...] = (
    ("app.agents.identity", "IDENTITY_VERSION"),
    ("app.agents.identity", "STANDING_RULES"),
    ("app.agents.identity", "CONTRACT_SECTIONS"),
    ("app.agents.services", "compose_identity"),
    ("app.agents.memory", "recall"),
)
#: What a writer is told that the parts above only template, hashed as it is said now: the
#: standing rules state the Owner's renders cap from his setting (STUDIO_RENDERS_PER_LAYER,
#: `agents.identity.standing_rules`), so runs told «twice» and «3 times» are two identities.
IDENTITY_SAID: tuple[tuple[str, str], ...] = (("app.agents.identity", "standing_rules"),)


def _described(value: Any) -> str:
    """A part as text: a function's source, a constant's JSON, else its repr."""
    if inspect.isfunction(value) or inspect.ismethod(value):
        try:
            return inspect.getsource(value)
        except (OSError, TypeError):
            return repr(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        return repr(value)


def _sha(parts: tuple[tuple[str, str], ...], said: tuple[tuple[str, str], ...] = ()) -> str:
    """The parts as text (`_described`), then each of ``said`` called and its answer: what
    the writer is told, beside the code that tells it."""
    digest = hashlib.sha256()
    for module_name, attribute in parts:
        value = getattr(importlib.import_module(module_name), attribute)
        digest.update(f"{module_name}.{attribute}\n".encode())
        digest.update(_described(value).encode("utf-8"))
        digest.update(b"\n\0")
    for module_name, attribute in said:
        answer = getattr(importlib.import_module(module_name), attribute)()
        digest.update(f"{module_name}.{attribute}()\n".encode())
        digest.update(_described(answer).encode("utf-8"))
        digest.update(b"\n\0")
    return digest.hexdigest()


def fingerprint(kind: str) -> dict[str, Any]:
    """The hashes of the brief and of the identity a ``kind`` ("serial" | "factual") writer is
    given right now — inside a variant's block, as the variant left them."""
    if kind not in BRIEF_PARTS:
        raise ValueError(f"Nu există scenarist de tipul {kind!r}")
    return {
        "brief_sha256": _sha(BRIEF_PARTS[kind]),
        "identity_sha256": _sha(IDENTITY_PARTS, IDENTITY_SAID),
        "parts": [f"{module}.{name}" for module, name in BRIEF_PARTS[kind] + IDENTITY_PARTS]
        + [f"{module}.{name}()" for module, name in IDENTITY_SAID],
    }
