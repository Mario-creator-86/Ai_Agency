"""The Owner's renders cap: how many times one layer of one shot is made, read when it is used.

2026-10-15 12:20Z, the Owner: «Randările odată făcute, de maxim 3x pentru fiecare imagine sau
mișcare»; past the cap nothing of that layer is bought again, the Director chooses what is
closest to the plan and the film is published as it stands. 2026-10-16 ~12:00Z, with the
montage's shots longer and dearer: «limităm acum la 2 randări, pentru că sunt mai lungi și mai
costisitoare, maxim încă o randare» — the first render and at most one more.

The number lives in one place, `Settings.renders_per_layer` (STUDIO_RENDERS_PER_LAYER), and is
read at call time through `renders_per_layer`, never copied into a module constant: every
route that buys a still or a shot (the stills step and its re-rolls, the motion step and its
clip-QC retry, the test shot, the Director's paid redo, the studio's clip-redo proposal, the
release of a delivery retry), the budget holds sized for those purchases, and every sentence
that states the number read it here. A render is a paid request among the scene's takes of that
layer, whatever became of it (`assembler._paid_attempts`: a stills request's candidates share
its task id); a request that made nothing and cost nothing is not one. Each montage shot is its
own storyboard scene, so the cap counts per shot.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

#: The two layers a shot is made of: its picture and its motion (the test shot is motion).
LAYERS: tuple[str, ...] = ("still", "motion")
#: The setting's variable, read directly only when the studio's settings cannot be built.
ENV_NAME = "STUDIO_RENDERS_PER_LAYER"
#: The one retry clip quality control knows (seed + 1, the move asked more firmly).
CLIP_QC_RETRIES = 1


def _field() -> tuple[int, int, int]:
    """(default, lowest, highest) of `Settings.renders_per_layer`, read from the model."""
    from app.config import Settings  # noqa: PLC0415 - config is read, never imported early

    info = Settings.model_fields["renders_per_layer"]
    low, high = 1, 5
    for rule in info.metadata:
        low = int(getattr(rule, "ge", low) or low)
        high = int(getattr(rule, "le", high) or high)
    return int(info.default), low, high


def _valid(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def renders_per_layer(settings: Any = None) -> int:
    """How many times a shot's picture, or its motion, may be made, the first purchase
    included: ``settings.renders_per_layer`` when it carries one, else the studio's settings
    as they stand now (environment and .env), else the field's default."""
    default, low, high = _field()
    given = _valid(getattr(settings, "renders_per_layer", None), low, high)
    if given is not None:
        return given
    from app.config import Settings  # noqa: PLC0415

    try:
        built = Settings()  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001 - a studio without usable settings (no Owner token)
        built = None
    if built is not None:
        read = _valid(getattr(built, "renders_per_layer", None), low, high)
        if read is not None:
            return read
    raw = os.environ.get(ENV_NAME, "").strip()
    if raw.isdigit():
        parsed = _valid(int(raw), low, high)
        if parsed is not None:
            return parsed
    return default


def max_rerolls(settings: Any = None) -> int:
    """How many times a refused still is bought again inside one purchase: the renders cap
    less the first render."""
    return renders_per_layer(settings) - 1


def clip_retries(settings: Any = None) -> int:
    """How many retries clip quality control may buy for a refused clip: its one retry while
    the cap leaves room for a second render, none at a cap of one."""
    return min(CLIP_QC_RETRIES, renders_per_layer(settings) - 1)


def paid_redos_per_scene(settings: Any = None) -> int:
    """The paid redos the Director's repair may buy for one scene: what the renders cap leaves
    after the first purchase, or ``settings.film_max_paid_redos_per_scene`` when the Owner set
    a lower one (STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE); never more than the cap leaves, so no
    route of the repair is allowed a render past it."""
    room = max(0, renders_per_layer(settings) - 1)
    configured = getattr(settings, "film_max_paid_redos_per_scene", None)
    if isinstance(configured, int) and not isinstance(configured, bool) and configured >= 0:
        return min(configured, room)
    return room


def renders_left(made: int, settings: Any = None) -> int:
    """How many more times a layer may be made once ``made`` renders of it exist."""
    return max(0, renders_per_layer(settings) - int(made))


def renders_ro(count: int | None = None, settings: Any = None) -> str:
    """The cap said in Romanian: «2 randări», «o randare»."""
    from app.wording import count as count_ro  # noqa: PLC0415

    value = renders_per_layer(settings) if count is None else int(count)
    return "o randare" if value == 1 else count_ro(value, "randare", "randări")


def renders_of_ro(whose: str, count: int | None = None, settings: Any = None) -> str:
    """The cap said of a layer, in Romanian: «2 randări ale imaginii», «o randare a mișcării»."""
    value = renders_per_layer(settings) if count is None else int(count)
    return f"{renders_ro(value)} {'a' if value == 1 else 'ale'} {whose}"


def times_en(count: int | None = None, settings: Any = None) -> str:
    """The cap said in English: «once», «twice», «3 times»."""
    value = renders_per_layer(settings) if count is None else int(count)
    return {1: "once", 2: "twice"}.get(value, f"{value} times")


def _kinds(layer: str) -> tuple[str, ...]:
    from app.media.assembler import SHOT_TAKE_KINDS  # noqa: PLC0415 - the assembler imports us

    if layer == "still":
        return ("still",)
    if layer == "motion":
        return tuple(SHOT_TAKE_KINDS)
    raise ValueError(f"unknown layer: {layer}")


def renders_made(session: Session, storyboard_id: str, scene_number: int, layer: str) -> int:
    """How many times the scene's ``layer`` («still» or «motion») has been made: every paid
    request among its takes of that layer, whatever became of it."""
    from app.media.assembler import _paid_attempts  # noqa: PLC0415
    from app.media.models import SceneTake  # noqa: PLC0415

    rows = list(
        session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == int(scene_number),
                SceneTake.kind.in_(_kinds(layer)),
            )
        )
    )
    return _paid_attempts(rows, "still" if layer == "still" else "motion")


def renders_by_scene(session: Session, storyboard_id: str, layer: str) -> dict[int, int]:
    """Per scene of the film, how many times its ``layer`` has been made."""
    from app.media.assembler import _paid_attempts  # noqa: PLC0415
    from app.media.models import SceneTake  # noqa: PLC0415

    by_scene: dict[int, list[Any]] = {}
    for row in session.scalars(
        select(SceneTake).where(
            SceneTake.storyboard_id == storyboard_id, SceneTake.kind.in_(_kinds(layer))
        )
    ):
        by_scene.setdefault(int(row.scene_number), []).append(row)
    group = "still" if layer == "still" else "motion"
    return {scene: _paid_attempts(rows, group) for scene, rows in by_scene.items()}


def at_cap(
    session: Session, storyboard_id: str, scene_number: int, layer: str, settings: Any = None
) -> bool:
    """Whether the scene's ``layer`` has had its renders: nothing more of it is bought."""
    made = renders_made(session, storyboard_id, scene_number, layer)
    return made >= renders_per_layer(settings)
