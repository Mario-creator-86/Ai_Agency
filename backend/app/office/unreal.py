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
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine

from app.office.services import get_office_layout_with_assignments

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


async def run_unreal_bridge(engine: Engine, settings: Any, stop: asyncio.Event) -> None:
    """Keeps the live level in step with the studio until ``stop`` is set."""
    target = remote_control_target(settings)
    if target is None:
        return
    bridge = UnrealBridge(http_sender(target))
    while not stop.is_set():
        try:
            layout = await asyncio.to_thread(get_office_layout_with_assignments, engine)
            seats = load_seats(settings.office_unreal_seat_report)
            await asyncio.to_thread(bridge.sync, layout, seats)
        except Exception as exc:  # noqa: BLE001 - a failed pass must not end the loop
            logger.warning("office_unreal_sync_failed", extra={"error": type(exc).__name__})
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.office_unreal_sync_seconds)
        except TimeoutError:
            pass
