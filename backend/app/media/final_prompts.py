"""Kael-owned final vendor prompts: validate and transport, never rewrite prose.

New shots carry format=editor_final_v1. Old shots have no format marker and
keep the composer/intent path so existing paid scene identities remain stable.
The selected provider may refuse unsupported caps; it must not silently change
the approved words after Sarah's audit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runpod_worker.contract import MAX_PROMPT

EDITOR_FINAL = "editor_final_v1"


class FinalPromptError(ValueError):
    """Reject invalid editor output before a vendor can be charged."""


def validate_final(
    package: Mapping[str, Any],
    *,
    max_utf16: int = MAX_PROMPT,
    motion_max_utf16: int | None = None,
) -> tuple[str, str]:
    """Return the exact still and motion text only if both pass technical limits."""
    from app.media.prompt_lint import CAMERA_MOVES, utf16_units  # noqa: PLC0415

    still = package.get("still_prompt")
    motion = package.get("motion_prompt")
    move = package.get("camera_move")
    for name, value in (("still_prompt", still), ("motion_prompt", motion)):
        if not isinstance(value, str) or not value.strip():
            raise FinalPromptError(f"Kael trebuie sa scrie {name} integral.")
        if value != value.strip():
            raise FinalPromptError(f"{name} are spatii exterioare; cerem corectare Kael.")
        if "\x00" in value or "\r" in value:
            raise FinalPromptError(f"{name} contine caractere de control.")
        cap = (
            motion_max_utf16
            if name == "motion_prompt" and motion_max_utf16 is not None
            else max_utf16
        )
        if utf16_units(value) > cap:
            raise FinalPromptError(
                f"{name} depaseste {cap} unitati UTF-16; Kael trebuie sa il scurteze, nu Python."
            )
    if not isinstance(move, str) or move not in CAMERA_MOVES:
        raise FinalPromptError("Kael trebuie sa indice un camera_move valid.")
    negative = package.get("negative_prompt")
    if negative is not None and (
        not isinstance(negative, str)
        or utf16_units(negative) > 400
        or negative != negative.strip()
        or "\x00" in negative
        or "\r" in negative
    ):
        raise FinalPromptError("negative_prompt nu respecta limita tehnica.")
    assert isinstance(still, str) and isinstance(motion, str)
    return still, motion


def editor_compiled(
    package: Mapping[str, Any],
    *,
    model_id: str | None = None,
    cap: int = MAX_PROMPT,
    motion_cap: int | None = None,
) -> dict[str, Any]:
    """Package unchanged vendor prose in the shape the purchase pipeline knows."""
    from app.media import prompt_lint as lint  # noqa: PLC0415

    if package.get("prompt_format") != EDITOR_FINAL:
        raise FinalPromptError("Promptul nu este in formatul final al lui Kael.")
    still, motion = validate_final(package, max_utf16=cap, motion_max_utf16=motion_cap)
    return {
        "scene_kind": "LIVE",
        "still_prompt": still,
        "motion_prompt": motion,
        "negative_prompt": package.get("negative_prompt") or None,
        "look_block": package.get("look_block") or "",
        "camera_move": package["camera_move"],
        "shot_size": str(package.get("shot_size") or "").lower(),
        "motion_family": lint.model_family(model_id) if model_id else "editor_final",
        "motion_intent": None,
        "composition_issues": [],
        "prompt_format": EDITOR_FINAL,
    }


def editor_motion_for(
    package: Mapping[str, Any], *, model_cap: int | None = None
) -> tuple[str, str | None]:
    """Only pass the reviewed text through; a smaller vendor cap is a hard stop."""
    from app.media.prompt_lint import utf16_units  # noqa: PLC0415

    still, motion = validate_final(package)
    del still
    if model_cap is not None and utf16_units(motion) > model_cap:
        raise FinalPromptError("Modelul selectat nu accepta promptul aprobat.")
    negative = package.get("negative_prompt")
    return motion, negative if isinstance(negative, str) and negative else None
