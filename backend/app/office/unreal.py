"""The live Unreal headquarters, kept in step with the studio's state.

Unreal runs the level as a game (see ``stream.py``) and answers Remote Control's HTTP API at the
address in configuration (``STUDIO_OFFICE_UNREAL_REMOTE_URL``, e.g. ``http://127.0.0.1:30010``).
``art-source/unreal/people/seat_employees.py`` seats the built MetaHumans and records, desk by
desk, the actor, its body and its seated animation in ``seat_report.json``.

This bridge reads the same office layout the page reads and tells Unreal, desk by desk, what the
backend says and nothing more: an employee is on screen only while an agent holds that desk. Every
employee shown is held still on the seated loop's frame that faces the viewer (``front_s`` in the
report): played on, the talking loop turns each of them towards their monitor, and the Owner wants
every character facing the viewer. When Unreal is not running the calls fail, nothing is retried in
a hurry, and everything is sent again once it answers.

Beside the people, an environment pass tells the level the real world outside (``world.py``:
the wall clock, the sun computed from the real time, the real weather or why there is none),
turned into scene values by ``scene_params.py``. It reads the level's object paths from the
report the rebuild's last step writes (``env_report.json``) and calls only the Remote Control
functions the scene's allow-list names (``ENVIRONMENT_CALLS``). Without the report it does
nothing and says so once: an object path is never guessed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine

from app.office.scene_params import SceneFrame, Vec3, scene_params
from app.office.services import get_office_layout_with_assignments
from app.office.weather import current_weather
from app.office.world import (
    LiveOverrideRefused,
    WeatherKeeper,
    WorldState,
    build_world_state,
    world_clock,
)

logger = logging.getLogger(__name__)

CALL_PATH = "/remote/object/call"
CALL_TIMEOUT_S = 2.0
#: Unreal may have restarted without the bridge seeing a failure; send everything again this often.
#: A restarted level plays the seated loops again, so for up to this long the employees turn
#: with the animation instead of holding the frame that faces the viewer: 20 s keeps that window
#: short, and the resend is three calls a seat against a local endpoint.
REFRESH_S = 20.0

Sender = Callable[[dict[str, Any]], None]


def remote_control_target(settings: Any) -> str | None:
    """The configured Remote Control address, or None when unset or not an http(s) URL."""
    url = (getattr(settings, "office_unreal_remote_url", None) or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return url


def load_seats(path: Path) -> dict[str, dict[str, Any]]:
    """desk id -> the seated employee's object paths and front-facing frame (``front_s``, seconds,
    0 when the report has none); empty when the report cannot be read."""
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    seats: dict[str, dict[str, Any]] = {}
    for seat in report.get("seats", []) if isinstance(report, dict) else []:
        if not isinstance(seat, dict):
            continue
        fields = {key: seat.get(key) for key in ("desk", "actor", "body", "animation")}
        paths: dict[str, Any] = {
            key: value for key, value in fields.items() if isinstance(value, str) and value
        }
        if len(paths) == len(fields):
            desk = paths.pop("desk")
            front = seat.get("front_s")
            # a number at or above zero; a bool is an int to Python and a lie here
            paths["front_s"] = (
                float(front)
                if isinstance(front, (int, float)) and not isinstance(front, bool) and front >= 0
                else 0.0
            )
            seats[desk] = paths
    return seats


def state_of(assignment: Mapping[str, Any]) -> str:
    """The same reading of an agent as the page's AgentVisualStateManager (hq_agents.js)."""
    lifecycle = str(assignment.get("lifecycle") or "").upper()
    if lifecycle in ("PAUSED", "SUSPENDED"):
        return "PAUSED"
    return str(assignment.get("runtime_state") or "IDLE").upper()


def desired_states(
    layout: Mapping[str, Any], seats: Mapping[str, Any]
) -> dict[str, dict[str, bool]]:
    """For every seated desk: whether its employee is shown, and whether they move."""
    by_desk = {a.get("desk_id"): a for a in layout.get("assignments", [])}
    desired = {}
    for desk in seats:
        assignment = by_desk.get(desk)
        if assignment is None:
            desired[desk] = {"visible": False, "moving": False}
        else:
            desired[desk] = {"visible": True, "moving": state_of(assignment) != "PAUSED"}
    return desired


def calls_for(seat: Mapping[str, Any], state: Mapping[str, bool]) -> list[dict[str, Any]]:
    """The Remote Control calls that put one seat in its state."""
    calls: list[dict[str, Any]] = [
        {
            "objectPath": seat["actor"],
            "functionName": "SetActorHiddenInGame",
            "parameters": {"bNewHidden": not state["visible"]},
            "generateTransaction": False,
        }
    ]
    if state["visible"]:
        # Working or paused, the employee is held on the seated loop's frame that faces the viewer.
        # Played on, the installed talking loop turns them towards their monitor for most of its
        # length (seen in the stream, 2026-09-15), and the Owner wants every character facing the
        # viewer. The loop is stopped first, so the position holds.
        calls.append(
            {
                "objectPath": seat["body"],
                "functionName": "SetPlayRate",
                "parameters": {"Rate": 0.0},
                "generateTransaction": False,
            }
        )
        calls.append(
            {
                "objectPath": seat["body"],
                "functionName": "SetPosition",
                "parameters": {"InPos": float(seat.get("front_s", 0.0)), "bFireNotifies": False},
                "generateTransaction": False,
            }
        )
    return calls


def http_sender(base_url: str, timeout: float = CALL_TIMEOUT_S) -> Sender:
    """Sends one call to Remote Control; raises OSError (URLError, HTTPError) when it fails."""
    endpoint = f"{base_url}{CALL_PATH}"

    def send(body: dict[str, Any]) -> None:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured http(s) only
            response.read()

    return send


class UnrealBridge:
    """Sends each seat's state when it changes, and everything again after a failure or a while."""

    def __init__(self, send: Sender, clock: Callable[[], float] = time.monotonic) -> None:
        self._send = send
        self._clock = clock
        self._pushed: dict[str, dict[str, bool]] = {}
        self._refreshed_at: float | None = None
        self._failing = False

    def sync(self, layout: Mapping[str, Any], seats: Mapping[str, Mapping[str, Any]]) -> int:
        """Pushes what changed; returns the number of seats sent (0 when Unreal did not answer)."""
        now = self._clock()
        if self._refreshed_at is None or now - self._refreshed_at >= REFRESH_S:
            self._pushed.clear()
            self._refreshed_at = now
        sent = 0
        for desk, state in desired_states(layout, seats).items():
            if self._pushed.get(desk) == state:
                continue
            try:
                for call in calls_for(seats[desk], state):
                    self._send(call)
            except (OSError, ValueError) as err:
                if not self._failing:
                    logger.info("office_unreal_unreachable", extra={"error": type(err).__name__})
                self._failing = True
                self._pushed.clear()
                return 0
            self._pushed[desk] = dict(state)
            sent += 1
        if self._failing:
            logger.info("office_unreal_reachable")
        self._failing = False
        return sent


# ---------------------------------------------------------------- the environment pass
BATCH_PATH = "/remote/batch"

#: The Remote Control functions the environment pass may call, as (class, function): exactly the
#: allow-list entries of the critic's corrected phase 1 (DefaultRemoteControl.ini, each with
#: bAllowChildClasses=True, so DirectionalLight/Point/Spot/RectLightComponent pass as
#: LightComponent and StaticMeshComponent as MeshComponent). Nothing else is ever called.
ENVIRONMENT_CALLS = frozenset(
    {
        ("LightComponent", "SetIntensity"),
        ("LightComponent", "SetLightColor"),
        ("SceneComponent", "K2_SetWorldRotation"),
        ("SkyLightComponent", "SetIntensity"),
        ("SkyLightComponent", "SetLightColor"),
        ("SkyLightComponent", "SetLowerHemisphereColor"),
        ("ExponentialHeightFogComponent", "SetFogInscatteringColor"),
        ("ExponentialHeightFogComponent", "SetFogDensity"),
        ("MeshComponent", "SetScalarParameterValueOnMaterials"),
        ("MeshComponent", "SetVectorParameterValueOnMaterials"),
    }
)
#: The one read the clock needs: the game's own time, which the display's material adds
#: ClockOffsetS to. The critic's list had no getter; the review added this one entry to
#: DefaultRemoteControl.ini (child classes refused; tests/test_remote_control_allowlist.py). A game
#: started before that entry answers 400: the offset is not sent, the face stays at --:--, and the
#: log says so once. Never estimated.
CLOCK_TIME_READ = ("/Script/Engine.Default__GameplayStatics", "GetTimeSeconds")

#: The sun turns only when it has moved this far: each move of a movable directional light
#: re-renders its cascaded shadows, and a quarter degree is about a minute of the real sun.
SUN_STEP_DEG = 0.25
#: A light, a colour or a material value is sent again when it moved by more than this share.
VALUE_STEP = 0.01
#: ClockOffsetS is sent again between refreshes when it moved by more than this (a DST change,
#: a restarted game): well under the one second the Owner checks the clock to.
CLOCK_STEP_S = 0.25

BatchSender = Callable[[Sequence[dict[str, Any]]], list[int]]
Value = float | tuple[float, ...]


@dataclass(frozen=True)
class EnvObject:
    role: str  # what the environment pass sets on it (SINGLE_ROLES, GROUP_ROLES, below)
    label: str
    path: str  # the component's object path: the calls act on components
    intensity: float | None = None  # a light's own intensity in the saved level
    emissive_uniform: bool = False  # every slot's EmissiveFactor (1,1,1), multiplied by the parent


@dataclass(frozen=True)
class EnvReport:
    """What env_report_hq_live.py recorded after the level's save (the rebuild's last step)."""

    world: str  # the UWorld the paths live in, for the game-time read
    axes: tuple[Vec3, Vec3, Vec3]  # Unreal vectors of scene +x, +y, +z
    heading_deg: float | None  # the facade heading the report was written with (D1)
    objects: tuple[EnvObject, ...]

    def frame(self, facade_heading_deg: float) -> SceneFrame:
        x, y, z = self.axes
        return SceneFrame(x=x, y=y, z=z, facade_heading_deg=facade_heading_deg)

    def of(self, role: str) -> list[EnvObject]:
        return [o for o in self.objects if o.role == role]


#: report "labels" key -> role; a light role names the scene_params light factor that drives it
SINGLE_ROLES = {
    "sun": "sun",
    "sky_light": "sky_light",
    "fog": "fog",
    "sky_backdrop": "sky_backdrop",
    "clock_display": "clock_display",
    "shelter_light": "light:shelter",
    "street_fill": "light:fills",
    "walk_wash": "light:fills",
    "facade_light": "light:fills",
}
GROUP_ROLES = {
    "lamps": "light:lamps",
    "tree_uplights": "light:uplights",
    "car_headlights": "light:car_lights",
    "car_taillights": "light:car_lights",
    "skyline_haze": "haze",
}


def _vector(value: Any) -> Vec3 | None:
    if (
        isinstance(value, list | tuple)
        and len(value) == 3
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
        and any(v != 0 for v in value)
    ):
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _object(role: str, entry: Any) -> EnvObject | None:
    if not isinstance(entry, Mapping):
        return None
    path = entry.get("component")
    if not isinstance(path, str) or not path:
        return None
    label = entry.get("label")
    intensity = _number(entry.get("intensity"))
    return EnvObject(
        role=role,
        label=label if isinstance(label, str) else role,
        path=path,
        intensity=intensity if intensity is not None and intensity >= 0 else None,
    )


def load_env_report(path: Path) -> EnvReport | None:
    """The report env_report_hq_live.py writes, or None when it is missing or not one.

    Read from it: ``labels`` (each entry's ``component`` path; groups as a dict or a list of
    entries; a light's ``intensity`` when its entry carries one), ``axes`` (``scene_x``,
    ``scene_y``, ``scene_z``), ``compass.facade_heading_deg``, ``emissive_scaling`` (``uniform``
    and ``component`` per mesh), ``road.component`` and ``window_view`` (``component``,
    ``slots``). Nothing is guessed: what the report does not name is not driven.
    """
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict) or not isinstance(report.get("labels"), Mapping):
        return None
    raw_axes = report.get("axes")
    if not isinstance(raw_axes, Mapping):
        return None
    x, y, z = (_vector(raw_axes.get(f"scene_{k}")) for k in ("x", "y", "z"))
    if x is None or y is None or z is None:
        return None
    labels: Mapping[str, Any] = report["labels"]
    objects: list[EnvObject] = []
    for key, role in SINGLE_ROLES.items():
        found = _object(role, labels.get(key))
        if found is not None:
            objects.append(found)
    for key, role in GROUP_ROLES.items():
        group = labels.get(key)
        entries: Iterable[Any] = (
            group.values()
            if isinstance(group, Mapping)
            else group
            if isinstance(group, list)
            else ()
        )
        for entry in entries:
            found = _object(role, entry)
            if found is not None:
                objects.append(found)
    scaling = report.get("emissive_scaling")
    for key in ("skyline", "near_blocks"):
        item = scaling.get(key) if isinstance(scaling, Mapping) else None
        if isinstance(item, Mapping) and isinstance(item.get("component"), str):
            objects.append(
                EnvObject(
                    role=key,
                    label=key,
                    path=item["component"],
                    emissive_uniform=item.get("uniform") is True,
                )
            )
    road = report.get("road")
    if isinstance(road, Mapping) and isinstance(road.get("component"), str):
        objects.append(EnvObject(role="road", label="street_ground", path=road["component"]))
    window = report.get("window_view")
    # DayBlend lives only in M_HQ_WindowView: with no slot of it on props there is nothing to set
    if (
        isinstance(window, Mapping)
        and isinstance(window.get("component"), str)
        and isinstance(window.get("slots"), list)
        and window["slots"]
    ):
        objects.append(EnvObject(role="window_view", label="props", path=window["component"]))
    if not objects:
        return None
    heads = {o.path.split(":", 1)[0] for o in objects if ":" in o.path}
    world = heads.pop() if len(heads) == 1 else ""
    compass = report.get("compass")
    heading = _number(compass.get("facade_heading_deg")) if isinstance(compass, Mapping) else None
    return EnvReport(world=world, axes=(x, y, z), heading_deg=heading, objects=tuple(objects))


@dataclass(frozen=True)
class EnvCall:
    """One Remote Control call. ``key`` names what it sets, for send-on-change."""

    cls: str  # the allow-list class the call passes as
    path: str
    function: str
    name: str  # a material parameter's name, or the call's own role
    value: Value
    kind: str = "value"  # "value" (eased), "rotation", "sky", "clock"
    group: str = ""  # calls of one group travel in one batch

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.function, self.name)

    def body(self, value: Value | None = None) -> dict[str, Any]:
        v = self.value if value is None else value
        if self.function in ("SetIntensity",):
            params: dict[str, Any] = {"NewIntensity": _scalar(v)}
        elif self.function == "SetLightColor":
            params = {"NewLightColor": _colour(v)}
            if self.cls == "LightComponent":
                params["bSRGB"] = True
        elif self.function == "SetLowerHemisphereColor":
            params = {"InLowerHemisphereColor": _colour(v)}
        elif self.function == "SetFogInscatteringColor":
            params = {"Value": _colour(v)}
        elif self.function == "SetFogDensity":
            params = {"Value": _scalar(v)}
        elif self.function == "K2_SetWorldRotation":
            pitch, yaw, roll = v if isinstance(v, tuple) else (v, 0.0, 0.0)
            params = {
                "NewRotation": {"Pitch": pitch, "Yaw": yaw, "Roll": roll},
                "bSweep": False,
                "bTeleport": True,
            }
        elif self.function == "SetScalarParameterValueOnMaterials":
            params = {"ParameterName": self.name, "ParameterValue": _scalar(v)}
        elif self.function == "SetVectorParameterValueOnMaterials":
            x, y, z = v if isinstance(v, tuple) else (v, v, v)
            params = {"ParameterName": self.name, "ParameterValue": {"X": x, "Y": y, "Z": z}}
        else:  # pragma: no cover - environment_calls makes no other
            raise ValueError(f"not an environment call: {self.function}")
        return {
            "objectPath": self.path,
            "functionName": self.function,
            "parameters": params,
            "generateTransaction": False,
        }


def _scalar(v: Value) -> float:
    return float(v[0]) if isinstance(v, tuple) else float(v)


def _colour(v: Value) -> dict[str, float]:
    r, g, b = v if isinstance(v, tuple) else (v, v, v)
    return {"R": r, "G": g, "B": b, "A": 1.0}


def environment_calls(plan: Mapping[str, Any], report: EnvReport) -> list[EnvCall]:
    """Every call that puts the level on ``plan`` (scene_params' output), for the objects the
    report names. An object the report does not name is not touched."""
    calls: list[EnvCall] = []
    for sun in report.of("sun")[:1]:
        s = plan["sun"]
        calls.append(EnvCall("LightComponent", sun.path, "SetIntensity", "sun", s["intensity"]))
        calls.append(EnvCall("LightComponent", sun.path, "SetLightColor", "sun", tuple(s["color"])))
        rotation = s.get("rotation")
        if rotation is not None:
            calls.append(
                EnvCall(
                    "SceneComponent",
                    sun.path,
                    "K2_SetWorldRotation",
                    "sun",
                    (rotation["Pitch"], rotation["Yaw"], rotation["Roll"]),
                    kind="rotation",
                )
            )
    for sky_light in report.of("sky_light")[:1]:
        k = plan["sky_light"]
        path = sky_light.path
        calls.append(EnvCall("SkyLightComponent", path, "SetIntensity", "sky", k["intensity"]))
        calls.append(EnvCall("SkyLightComponent", path, "SetLightColor", "sky", tuple(k["color"])))
        calls.append(
            EnvCall(
                "SkyLightComponent",
                path,
                "SetLowerHemisphereColor",
                "sky",
                tuple(k["lower_hemisphere"]),
            )
        )
    for fog in report.of("fog")[:1]:
        f = plan["fog"]
        cls = "ExponentialHeightFogComponent"
        calls.append(
            EnvCall(cls, fog.path, "SetFogInscatteringColor", "fog", tuple(f["inscattering"]))
        )
        calls.append(EnvCall(cls, fog.path, "SetFogDensity", "fog", f["density"]))
    for light in report.objects:
        if not light.role.startswith("light:") or light.intensity is None:
            continue  # without the saved level's own intensity there is nothing to scale
        factor = float(plan["lights"][light.role.split(":", 1)[1]])
        calls.append(
            EnvCall("LightComponent", light.path, "SetIntensity", "light", light.intensity * factor)
        )
    scalar, vector = "SetScalarParameterValueOnMaterials", "SetVectorParameterValueOnMaterials"
    for backdrop in report.of("sky_backdrop")[:1]:
        for name in ("PlateA", "PlateB", "PlateBlend", "Mirror", "Gain"):
            calls.append(
                EnvCall(
                    "MeshComponent",
                    backdrop.path,
                    scalar,
                    name,
                    float(plan["sky"][name]),
                    kind="sky",
                    group="sky",
                )
            )
    offset = plan["clock"].get("ClockOffsetS")
    for clock in report.of("clock_display")[:1]:
        if offset is not None:
            calls.append(
                EnvCall(
                    "MeshComponent",
                    clock.path,
                    scalar,
                    "ClockOffsetS",
                    float(offset),
                    kind="clock",
                )
            )
    for key in ("skyline", "near_blocks"):
        # one call writes every slot: only where every slot's factor is (1,1,1) and its parent
        # multiplies by it is that a scaling (critic, hole 2); otherwise it would flatten
        for component in report.of(key)[:1]:
            if component.emissive_uniform:
                f = float(plan["emissive_factor"][key])
                calls.append(
                    EnvCall("MeshComponent", component.path, vector, "EmissiveFactor", (f, f, f))
                )
    for props in report.of("window_view")[:1]:
        calls.append(
            EnvCall(
                "MeshComponent",
                props.path,
                scalar,
                "DayBlend",
                float(plan["window_view"]["DayBlend"]),
            )
        )
    for ground in report.of("road")[:1]:
        for name in ("Roughness Min", "Roughness Max"):
            calls.append(
                EnvCall("MeshComponent", ground.path, scalar, name, float(plan["road"][name]))
            )
    for plane in report.of("haze"):
        haze = plan["haze"].get(plane.label)
        if haze is None:
            continue
        calls.append(
            EnvCall("MeshComponent", plane.path, vector, "HazeColor", tuple(haze["HazeColor"]))
        )
        calls.append(
            EnvCall("MeshComponent", plane.path, scalar, "Opacity", float(haze["Opacity"]))
        )
    return calls


def _as_tuple(v: Value) -> tuple[float, ...]:
    return v if isinstance(v, tuple) else (float(v),)


def _moved(old: Value, new: Value, kind: str) -> bool:
    a, b = _as_tuple(old), _as_tuple(new)
    if len(a) != len(b):
        return True
    if kind == "rotation":
        return any(
            abs((x - y + 180.0) % 360.0 - 180.0) >= SUN_STEP_DEG for x, y in zip(a, b, strict=True)
        )
    if kind == "clock":
        return any(abs(x - y) > CLOCK_STEP_S for x, y in zip(a, b, strict=True))
    if kind == "sky":
        return a != b
    return any(abs(x - y) > max(1e-4, VALUE_STEP * abs(x)) for x, y in zip(a, b, strict=True))


@dataclass
class _Ease:
    start: tuple[float, ...]
    target: tuple[float, ...]
    t0: float
    shown: tuple[float, ...] = field(default_factory=tuple)


class EnvironmentPass:
    """Sends the environment when it changes, eased, and everything again every refresh."""

    def __init__(
        self,
        send: BatchSender,
        clock: Callable[[], float] = time.monotonic,
        refresh_s: float = REFRESH_S,
        ease_s: float = 30.0,
    ) -> None:
        self._send = send
        self._clock = clock
        self._refresh_s = refresh_s
        self._ease_s = ease_s
        self._sent: dict[tuple[str, str, str], Value] = {}
        self._eases: dict[tuple[str, str, str], _Ease] = {}
        self._refreshed_at: float | None = None
        self._failing = False
        self._said: set[str] = set()

    def _once(self, message: str, **extra: Any) -> None:
        if message not in self._said:
            self._said.add(message)
            logger.info(message, extra=extra or None)

    def _eased(self, call: EnvCall, now: float) -> Value:
        """A real change of light reaches the screen over ``ease_s``, from what is shown now."""
        target = _as_tuple(call.value)
        ease = self._eases.get(call.key)
        if ease is None or len(ease.target) != len(target) or self._ease_s <= 0:
            self._eases[call.key] = _Ease(target, target, now, target)
            return call.value
        if ease.target != target:
            ease.start, ease.target, ease.t0 = ease.shown, target, now
        t = min(1.0, (now - ease.t0) / self._ease_s)
        ease.shown = tuple(s + (g - s) * t for s, g in zip(ease.start, ease.target, strict=True))
        return ease.shown if isinstance(call.value, tuple) else ease.shown[0]

    def sync(
        self,
        world: WorldState,
        report: EnvReport | None,
        facade_heading_deg: float,
        game_time_s: float | None = None,
    ) -> int:
        """Pushes what changed; returns the number of calls that landed."""
        if report is None:
            self._once("office_unreal_env_report_missing")
            return 0
        self._said.discard("office_unreal_env_report_missing")
        if report.heading_deg is not None and abs(report.heading_deg - facade_heading_deg) > 1e-6:
            # the level's north was written for another heading than the backend's (D1): the
            # sun would stand on the wrong side, so nothing is sent until the two agree
            self._once(
                "office_unreal_env_report_heading_mismatch",
                report=report.heading_deg,
                setting=facade_heading_deg,
            )
            return 0
        self._said.discard("office_unreal_env_report_heading_mismatch")
        now = self._clock()
        if self._refreshed_at is None or now - self._refreshed_at >= self._refresh_s:
            self._sent.clear()
            self._refreshed_at = now
        plan = scene_params(world, report.frame(facade_heading_deg), game_time_s)
        calls = environment_calls(plan, report)
        pending: list[tuple[EnvCall, Value]] = []
        for call in calls:
            value = self._eased(call, now) if call.kind == "value" else call.value
            last = self._sent.get(call.key)
            if last is not None and not _moved(last, value, call.kind):
                continue
            pending.append((call, value))
        # a group (the sky's plate pair and blend) travels whole, so no frame shows half of it
        groups = {c.group for c, _ in pending if c.group}
        for call in calls:
            if call.group in groups and not any(c.key == call.key for c, _ in pending):
                pending.append((call, call.value))
        if not pending:
            return 0
        bodies = [c.body(v) for c, v in pending]
        try:
            codes = self._send(bodies)
        except (OSError, ValueError) as err:
            if not self._failing:
                logger.info("office_unreal_env_unreachable", extra={"error": type(err).__name__})
            self._failing = True
            self._sent.clear()
            return 0
        if self._failing:
            logger.info("office_unreal_env_reachable")
        self._failing = False
        landed = 0
        for (call, value), code in zip(pending, codes, strict=False):
            if 200 <= code < 300:
                self._sent[call.key] = value
                landed += 1
            else:
                self._once("office_unreal_env_call_refused", function=call.function, status=code)
        return landed


def http_batch_sender(base_url: str, timeout: float = CALL_TIMEOUT_S) -> BatchSender:
    """Sends calls to Remote Control, several in one /remote/batch request; returns each call's
    status. Raises OSError when Unreal does not answer."""

    def put(route: str, payload: dict[str, Any]) -> tuple[int, Any]:
        request = urllib.request.Request(
            f"{base_url}{route}",
            data=json.dumps(payload).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured http(s) only
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as refused:  # a refused call is an answer, not an outage
            return refused.code, None
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, None

    def send(bodies: Sequence[dict[str, Any]]) -> list[int]:
        if len(bodies) == 1:
            return [put(CALL_PATH, dict(bodies[0]))[0]]
        status, answer = put(
            BATCH_PATH,
            {
                "Requests": [
                    {"RequestId": i, "URL": CALL_PATH, "Verb": "PUT", "Body": body}
                    for i, body in enumerate(bodies)
                ]
            },
        )
        responses = answer.get("Responses") if isinstance(answer, dict) else None
        if not isinstance(responses, list):
            return [status if status >= 400 else 500] * len(bodies)
        codes = {
            r.get("RequestId"): r.get("ResponseCode") for r in responses if isinstance(r, dict)
        }
        return [c if isinstance(c := codes.get(i), int) else 500 for i in range(len(bodies))]

    return send


def http_game_time_reader(base_url: str, timeout: float = CALL_TIMEOUT_S) -> Callable[[str], float]:
    """Reads the game's time (GameplayStatics.GetTimeSeconds in the level's world): what the
    clock display's material Time node shows. Raises OSError when it cannot be read."""
    target, function = CLOCK_TIME_READ

    def read(world: str) -> float:
        request = urllib.request.Request(
            f"{base_url}{CALL_PATH}",
            data=json.dumps(
                {
                    "objectPath": target,
                    "functionName": function,
                    "parameters": {"WorldContextObject": world},
                    "generateTransaction": False,
                }
            ).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured http(s) only
            answer = json.loads(response.read() or b"null")
        value = answer.get("ReturnValue") if isinstance(answer, dict) else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("no game time in the answer")
        return float(value)

    return read


def environment_clock(settings: Any) -> tuple[Callable[[], datetime], bool]:
    """The clock the scene is shown at and whether it is a rehearsal's. A rehearsal hour on the
    live studio is refused: the real clock is kept and the refusal logged."""
    try:
        clock = world_clock(settings)
    except LiveOverrideRefused:
        logger.warning("office_world_rehearsal_refused_live")
        return world_clock(_without_rehearsal(settings)), False
    return clock, getattr(settings, "office_world_rehearsal_at", None) is not None


class _without_rehearsal:  # noqa: N801 - a view of the settings, read like them
    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def __getattr__(self, name: str) -> Any:
        if name == "office_world_rehearsal_at":
            return None
        return getattr(self._settings, name)


class EnvironmentRunner:
    """One environment tick: the weather on its cadence, the game time, the world, the pass."""

    def __init__(
        self,
        settings: Any,
        env: EnvironmentPass,
        read_game_time: Callable[[str], float],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._env = env
        self._read_game_time = read_game_time
        self._monotonic = monotonic
        self._clock, self._rehearsal = environment_clock(settings)
        self._keeper = WeatherKeeper()
        self._observation: Mapping[str, Any] = {"available": False, "reason": "unavailable"}
        self._next_weather = 0.0
        self._clock_unread_said = False

    def _weather(self) -> tuple[Mapping[str, Any], str | None, float]:
        now = self._monotonic()
        if self._rehearsal:
            # the weather now is not the rehearsed hour's, and an archive is not wired in: none
            return {"available": False, "reason": "rehearsal"}, "rehearsal", 0.0
        if now >= self._next_weather:
            self._observation = current_weather(self._settings)
            ok = self._observation.get("available") is True
            self._next_weather = now + (
                float(self._settings.office_weather_refresh_seconds) if ok else 120.0
            )
        return self._keeper.observe(self._observation, now)

    def tick(self) -> int:
        observation, reason, age = self._weather()
        report = load_env_report(self._settings.office_unreal_env_report)
        game_time: float | None = None
        if report is not None and report.world:
            before = self._monotonic()
            try:
                game_time = self._read_game_time(report.world)
                # the time was read mid-request: move it to the instant the world is taken at
                game_time += (self._monotonic() - before) / 2.0
                self._clock_unread_said = False
            except (OSError, ValueError) as err:
                if not self._clock_unread_said:
                    logger.info(
                        "office_unreal_clock_time_unread", extra={"error": type(err).__name__}
                    )
                self._clock_unread_said = True
                game_time = None
        world = build_world_state(
            self._clock(),
            self._settings,
            observation,
            weather_reason=reason,
            weather_age_s=age if reason == "stale" else None,
            rehearsal=self._rehearsal,
        )
        return self._env.sync(
            world, report, float(self._settings.office_facade_heading_deg), game_time
        )


async def run_unreal_bridge(engine: Engine, settings: Any, stop: asyncio.Event) -> None:
    """Keeps the live level in step with the studio and the world until ``stop`` is set."""
    target = remote_control_target(settings)
    if target is None:
        return
    bridge = UnrealBridge(http_sender(target))
    environment = EnvironmentRunner(
        settings,
        EnvironmentPass(
            http_batch_sender(target),
            refresh_s=float(settings.office_unreal_env_refresh_seconds),
            ease_s=float(settings.office_unreal_env_ease_seconds),
        ),
        http_game_time_reader(target),
    )
    while not stop.is_set():
        try:
            layout = await asyncio.to_thread(get_office_layout_with_assignments, engine)
            seats = load_seats(settings.office_unreal_seat_report)
            await asyncio.to_thread(bridge.sync, layout, seats)
        except Exception as exc:  # noqa: BLE001 - a failed pass must not end the loop
            logger.warning("office_unreal_sync_failed", extra={"error": type(exc).__name__})
        try:
            await asyncio.to_thread(environment.tick)
        except Exception as exc:  # noqa: BLE001 - nor may a failed environment pass
            logger.warning("office_unreal_env_failed", extra={"error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.office_unreal_sync_seconds)
        except TimeoutError:
            pass
