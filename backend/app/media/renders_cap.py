"""The Owner's renders cap: how many times one layer of one shot is made, read when it is used.

2026-10-15 12:20Z, the Owner: «Randările odată făcute, de maxim 3x pentru fiecare imagine sau
mișcare»; past the cap nothing of that layer is bought again, the Director chooses what is
closest to the plan and the film is published as it stands. 2026-10-16 ~12:00Z, with the
montage's shots longer and dearer: «limităm acum la 2 randări, pentru că sunt mai lungi și mai
costisitoare, maxim încă o randare» — the first render and at most one more.

The number lives in one place, `Settings.renders_per_layer` (STUDIO_RENDERS_PER_LAYER), and is
read at call time through `renders_per_layer`, never copied into a module constant: every
route that buys a still or a shot (the stills step, its re-rolls and its technical retry, the
motion step and its clip-QC retry, the test shot, the Director's paid redo, the studio's
clip-redo proposal, the release of a delivery retry, and the Owner's own press of a scene redo,
whose plan says the cap is reached instead of pricing a render past it), the budget holds sized
for those purchases, and every sentence that states the number read it here. A render is a
paid request among the scene's takes of that layer, whatever became of it
(`assembler._paid_attempts`: a stills request's candidates share its task id; a charged vendor
failure is one); a request that made nothing and cost nothing is not one. Each montage shot is
its own storyboard scene, so the cap counts per shot. Past the cap the scene keeps what it has
(`stills_stage.settle_scene_under_cap`, `assembler.settle_motion_under_cap`): with two or more
takes of the layer the Director looks at them once and chooses the one closest to the plan,
with one it stays, and when she cannot look the studio keeps its own pick and says so
(`cap_choice`); a scene no clip can carry is shown as its still moved locally (below). Nothing
waits for the Owner.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

logger = logging.getLogger("studio.renders_cap")

#: The two layers a shot is made of: its picture and its motion (the test shot is motion).
LAYERS: tuple[str, ...] = ("still", "motion")
#: The setting's variable, read directly only when the studio's settings cannot be built.
ENV_NAME = "STUDIO_RENDERS_PER_LAYER"
#: The one retry clip quality control knows (seed + 1, the move asked more firmly).
CLIP_QC_RETRIES = 1
#: The failures already logged by `renders_per_layer` in this process (one warning each, not
#: one per call: the cap is read many times per walk).
_LOGGED: set[tuple[str, int]] = set()


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
    as they stand now (environment and .env), else the field's default.

    When the studio's settings cannot be built (a .env locked, a value it cannot read, no
    Owner token), the number is read safe (`_unbuilt_cap`): never more than any source sets,
    the lowest the setting allows when a source cannot be read, and the failure is logged.
    Before 2026-10-16 such a failure fell back to the environment alone, then to the default:
    a cap of 1 written only in .env read as 2, one paid render more than the Owner set."""
    default, low, high = _field()
    given = _valid(getattr(settings, "renders_per_layer", None), low, high)
    if given is not None:
        return given
    from app.config import Settings  # noqa: PLC0415

    try:
        built = Settings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - read safe below, and logged
        cap = _unbuilt_cap(default, low, high)
        key = (type(exc).__name__, cap)
        if key not in _LOGGED:
            _LOGGED.add(key)
            logger.warning(
                "renders_cap_settings_unreadable",
                extra={"error": type(exc).__name__, "renders_per_layer": cap},
            )
        return cap
    read = _valid(getattr(built, "renders_per_layer", None), low, high)
    return read if read is not None else default


def _named(raw: Any, low: int, high: int) -> int | None:
    """A source's value for the cap read as the setting would read it, or None when it names
    none it can hold (the caller then reads the lowest)."""
    text = str(raw).strip()
    return _valid(int(text), low, high) if text.isdigit() else None


def _unbuilt_cap(default: int, low: int, high: int) -> int:
    """The cap when the settings cannot be built: the lowest the environment and the .env file
    set (the settings read the environment first, the file second; the lower of the two can
    never be more than either), the field's default when neither sets one, and the lowest
    the setting allows when a source sets a value it cannot hold or the file cannot be read.
    Never more renders than the Owner configured."""
    from app.config import Settings  # noqa: PLC0415

    named: list[int] = []
    unreadable = False
    for key, value in os.environ.items():
        if key.upper() == ENV_NAME:
            parsed = _named(value, low, high)
            unreadable = unreadable or parsed is None
            named += [parsed] if parsed is not None else []
    env_file = Settings.model_config.get("env_file")
    files = env_file if isinstance(env_file, (list, tuple)) else [env_file] if env_file else []
    for file in files:
        path = Path(str(file))
        if not path.exists():
            continue
        try:
            from dotenv import dotenv_values  # noqa: PLC0415 - pydantic-settings' own reader

            values = dotenv_values(path)
        except Exception:  # noqa: BLE001 - a file that cannot be read sets the lowest
            unreadable = True
            continue
        for name, found in values.items():
            if name.upper() == ENV_NAME and found is not None:
                parsed = _named(found, low, high)
                unreadable = unreadable or parsed is None
                named += [parsed] if parsed is not None else []
    if unreadable:
        return low
    return min(named) if named else default


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


def paid_redos_setting(settings: Any = None) -> str:
    """The variable the per-scene paid redos come from, as `paid_redos_per_scene` reads them:
    the Owner's own STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE when he set one lower than the cap
    leaves, else the renders cap (STUDIO_RENDERS_PER_LAYER)."""
    room = max(0, renders_per_layer(settings) - 1)
    configured = getattr(settings, "film_max_paid_redos_per_scene", None)
    if isinstance(configured, int) and not isinstance(configured, bool) and 0 <= configured < room:
        return "STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE"
    return ENV_NAME


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


# ------------------------------------------------ the Director's local move under the cap
#
# Past the cap nothing more of a layer is bought, and the scene keeps what it has (the Owner,
# 2026-10-15: «publicăm cu ce Directoarea alege ca fiind cel mai apropiat»). For a filmed scene
# whose motion has had its renders, that is a clip it has (`assembler.settle_motion_under_cap`
# keeps it under the cap: the one it has, or the one the Director chooses among several,
# `cap_choice`); when none can carry the scene's span — none on disk, or the one kept too short
# for its words even slowed down — it is its approved still moved locally (0 credits), the way
# his LOCAL_MOVE on the sheet shows one: the Director's local move under the cap, which the
# Owner approved by card on 2026-10-16. The move is not a look: it is made when no clip is left
# to keep. It is recorded here and read by every reader of his: the motion plan (the scene is
# LOCAL, never planned), the sheet's and the render's readiness, the fallback gate and film QC
# (which record it apart from his own choices). It stands while the scene's motion has nothing
# left to buy (`motion_spent`: at its cap, or its picture at the cap and not to be animated
# again): a cap he raises (STUDIO_RENDERS_PER_LAYER) gives the scene its render back.

#: {storyboard_id, scene_index, renders, cap, reason_ro} on the storyboard.
CAP_LOCAL_MOVE_EVENT = "media.cap_local_move"
#: Who chose a cap local move (the sheet's ``decided_by``).
CAP_LOCAL_MOVE_BY = "director"


# --------------------------------------- a motion with nothing left to buy: its picture's cap
#
# 2026-10-16 21:45-22:07Z, 87c05891 «Zero Scripts, Blocked Log», scene 1: its picture had three
# renders, all refused by the gate, and the Director kept 8b7393c4 under the cap. Its one clip
# (1283e81e) was refused for a fault of that picture (a flat band across its bottom), so the
# same-input guard refused every new clip from it (SAME_INPUT_FAILED) and sent the picture back
# to the stills gate; the cap could buy no new picture and chose 8b7393c4 again; the motion,
# at one render of two, was never at its cap, so no clip was kept and no local move made. Each
# walk paid a look of hers and a rewrite of hers in tokens, and the film never assembled.
#
# The Owner's rule decides it: a picture at the cap that cannot be animated again leaves its
# motion nothing to buy, exactly as a motion at its own cap (`motion_spent`). The picture
# stays (`assembler._send_still_back_for_clip` sends a still at the cap back no more, and
# records `MOTION_SPENT_EVENT` instead), and the motion settles under the cap with what the
# scene has: its clip kept, or her local move of the still (0 credits). The flip-flop's guard:
# a picture sent back for a clip's fault and kept under the cap again (any route, past or
# future) is read as spent too, so a re-opened choice settles the motion at the next walk
# instead of turning for ever.

#: {storyboard_id, scene_index, still_take_id, still_renders, motion_renders, cap, cause,
#: reason_ro} on the storyboard: the picture kept under the cap cannot be animated again.
MOTION_SPENT_EVENT = "media.cap_motion_spent"
#: `assembler._send_still_back`/`_send_still_back_for_clip`'s event, on the still's take: a
#: clip from it was refused for a fault of that picture.
STILL_SENT_BACK_EVENT = "media.still_sent_back"


def _approved_at(session: Session, still: Any) -> str | None:
    """When the Owner's own look (`assembler.decide_take`) or her look at its refused clip
    (`fix_check.restore_sent_back_scenes`) last approved this still: "" when it stands
    approved by one of them with no moment recorded (nothing before it counts), None when
    neither ever did."""
    from app.media.assembler import TAKE_DECIDED_EVENT, TAKE_DECIDER  # noqa: PLC0415
    from app.media.fix_check import DIRECTOR_LOOK_APPROVER  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    moments = [
        str(event.timestamp)
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == TAKE_DECIDED_EVENT,
                DomainEvent.aggregate_id == str(still.id),
            )
        )
        if isinstance(event.payload, dict) and event.payload.get("decision") == "APPROVED"
    ]
    standing = still.status == "APPROVED"
    if standing and still.approved_by == DIRECTOR_LOOK_APPROVER:
        moments.append(str(still.updated_at or ""))
    if standing and still.approved_by == TAKE_DECIDER and not moments:
        moments.append("")
    if not moments:
        return None
    return "￿" if "" in moments else max(moments)


def picture_cannot_move(session: Session, storyboard_id: str, still_take_id: str) -> bool:
    """Whether a clip from this still was refused for the still's own fault: it was sent back
    to the stills gate for it (`STILL_SENT_BACK_EVENT`: clip QC's finding, the same-input
    guard's, a video model's safety refusal of it), or kept at the cap in its place
    (`MOTION_SPENT_EVENT`). Only such a word newer than the still's latest approval by the
    Owner himself or by her look at the refused clip counts (`_approved_at`): his own choice
    of the still, or her look that overturned the send-back, gives its motion back."""
    from app.media.models import SceneTake  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    still = session.get(SceneTake, str(still_take_id))
    since = _approved_at(session, still) if still is not None else None

    def newer(event: Any) -> bool:
        return since is None or str(event.timestamp) > since

    if any(
        isinstance(event.payload, dict)
        and str(event.payload.get("still_take_id") or "") == str(still_take_id)
        and newer(event)
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == MOTION_SPENT_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
            )
        )
    ):
        return True
    return any(
        newer(event)
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == STILL_SENT_BACK_EVENT,
                DomainEvent.aggregate_id == str(still_take_id),
            )
        )
    )


def _kept_still_id(session: Session, storyboard_id: str, scene_index: int) -> str | None:
    """The still the scene's motion starts from now (`assembler.scene_approved_still`)."""
    from app.media.assembler import scene_approved_still  # noqa: PLC0415 - it imports us

    bind = session.get_bind()
    engine = bind if isinstance(bind, Engine) else bind.engine
    kept = scene_approved_still(engine, storyboard_id, int(scene_index))
    return str(kept.id) if kept is not None else None


def motion_spent(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    settings: Any = None,
    *,
    still_take_id: str | None = None,
) -> bool:
    """Whether nothing more of the scene's motion can be bought under the Owner's cap: its
    motion had its renders, or its picture had its renders and the picture kept
    (``still_take_id``, else the scene's approved still) cannot be animated again
    (`picture_cannot_move`). Either way what the scene has stands
    (`assembler.settle_motion_under_cap`). A cap he raises gives the layer its render back."""
    cap = renders_per_layer(settings)
    if renders_made(session, storyboard_id, scene_index, "motion") >= cap:
        return True
    if renders_made(session, storyboard_id, scene_index, "still") < cap:
        return False
    kept = still_take_id or _kept_still_id(session, storyboard_id, scene_index)
    return kept is not None and picture_cannot_move(session, storyboard_id, kept)


def motion_spent_words(scene_index: int, settings: Any = None) -> str:
    """Why nothing more of a scene's motion is bought though its motion had fewer renders than
    the cap: its picture had its renders and the picture kept cannot be animated again."""
    return (
        f"Scena {scene_index}: imaginea ei a avut deja {renders_ro(None, settings)}, plafonul "
        "Proprietarului, iar un clip din imaginea păstrată sub plafon a fost refuzat pentru o "
        "greșeală a acelei imagini; nu se mai cumpără nici o imagine nouă, nici un clip din "
        "aceeași imagine, deci mișcarea ei nu mai are ce cumpăra: rămâne clipul pe care îl are "
        "scena, sub plafon, altfel imaginea ei animată local (0 credite), iar filmul merge mai "
        "departe."
    )


def record_motion_spent(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    still_take_id: str,
    correlation_id: str,
    *,
    cause: str,
    reason_ro: str = "",
    settings: Any = None,
) -> bool:
    """The picture kept under the cap that cannot be animated again, recorded once per still,
    inside the caller's transaction. False (nothing written) when the picture is not at the
    cap or it is already recorded."""
    from app.services import append_event  # noqa: PLC0415

    cap = renders_per_layer(settings)
    pictures = renders_made(session, storyboard_id, scene_index, "still")
    if pictures < cap or picture_cannot_move(session, storyboard_id, still_take_id):
        return False
    append_event(
        session,
        MOTION_SPENT_EVENT,
        "storyboard",
        storyboard_id,
        1,
        {
            "storyboard_id": storyboard_id,
            "scene_index": int(scene_index),
            "still_take_id": str(still_take_id),
            "still_renders": pictures,
            "motion_renders": renders_made(session, storyboard_id, scene_index, "motion"),
            "cap": cap,
            "cause": cause,
            "reason_ro": (
                motion_spent_words(int(scene_index), settings)
                + (f" Refuzul: {' '.join(reason_ro.split())}" if reason_ro.strip() else "")
            )[:1500],
        },
        correlation_id,
    )
    return True


def cap_local_moves(session: Session, storyboard_id: str, settings: Any = None) -> set[int]:
    """The scenes the Director moved locally under the renders cap, while their motion has
    nothing left to buy (`motion_spent`)."""
    from app.models import DomainEvent  # noqa: PLC0415

    chosen: set[int] = set()
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == CAP_LOCAL_MOVE_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        scene = payload.get("scene_index")
        if isinstance(scene, int) and not isinstance(scene, bool):
            chosen.add(scene)
    if not chosen:
        return chosen
    made = renders_by_scene(session, storyboard_id, "motion")
    cap = renders_per_layer(settings)
    return {
        scene
        for scene in chosen
        if made.get(scene, 0) >= cap or motion_spent(session, storyboard_id, scene, settings)
    }


def cap_local_move_words(scene_index: int, settings: Any = None, *, picture: bool = False) -> str:
    """The local move, said as it is made: the cap left no clip that can carry the scene, so
    its still is shown moved locally — no look, no choice among takes. ``picture``: the
    motion had fewer renders than the cap, and it is the picture's cap that left it nothing
    to buy (`motion_spent`)."""
    why = (
        f"imaginea ei a avut deja {renders_ro(None, settings)}, plafonul Proprietarului, iar "
        "imaginea păstrată sub plafon nu se mai poate anima"
        if picture
        else f"mișcarea ei a avut deja {renders_ro(None, settings)}, plafonul Proprietarului"
    )
    return (
        f"Scena {scene_index}: {why}, și niciun clip al ei nu acoperă scena; scena se arată ca "
        "imagine fixă animată local (0 credite), singurul lucru care o mai poate acoperi, iar "
        "filmul merge mai departe (mutarea locală sub plafon, aprobată de Proprietar pe "
        "2026-10-16)."
    )


def record_cap_local_move(
    session: Session,
    storyboard_id: str,
    scene_index: int,
    correlation_id: str,
    *,
    reason_ro: str = "",
    settings: Any = None,
) -> bool:
    """Her local move of a scene whose motion has nothing left to buy (`motion_spent`: at its
    cap, or its picture at the cap and not to be animated again), recorded once while it
    stands. False (nothing written) when the motion is not spent or the move already stands."""
    from app.services import append_event  # noqa: PLC0415

    made = renders_made(session, storyboard_id, scene_index, "motion")
    cap = renders_per_layer(settings)
    if not motion_spent(session, storyboard_id, scene_index, settings) or int(
        scene_index
    ) in cap_local_moves(session, storyboard_id, settings):
        return False
    picture = made < cap
    append_event(
        session,
        CAP_LOCAL_MOVE_EVENT,
        "storyboard",
        storyboard_id,
        1,
        {
            "storyboard_id": storyboard_id,
            "scene_index": int(scene_index),
            "renders": made,
            "cap": cap,
            "decided_by": CAP_LOCAL_MOVE_BY,
            # The picture's cap, when it is the picture that left the motion nothing to buy.
            **(
                {
                    "spent_by": "still",
                    "still_renders": renders_made(session, storyboard_id, scene_index, "still"),
                }
                if picture
                else {}
            ),
            "reason_ro": (
                reason_ro or cap_local_move_words(int(scene_index), settings, picture=picture)
            )[:1500],
        },
        correlation_id,
    )
    return True
