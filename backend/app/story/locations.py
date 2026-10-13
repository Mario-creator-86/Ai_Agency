"""Where a scene of the serial can happen: the studio's own rooms, and nowhere else.

Measured before this (2026-09-24): the showrunner was told nothing about the building, so a
beat was set in "Redacția" or "the open-space" and the still was drawn in whatever office the
image model imagined, a different one in every episode. The studio has one building, drawn in
the headquarters scene; its rooms are the backend's `DEFAULT_OFFICE_LAYOUT` (kept in step
with the HQ manifest by tests/test_office_layout_matches_scene.py) and the office's own
`room` table. A beat names one of them by id, and the storyboard draws that room.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Room
from app.office.services import DEFAULT_OFFICE_LAYOUT


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def _floor(floor: Any) -> str:
    return "ground floor" if floor in (0, "0") else f"floor {floor}"


def studio_locations(session: Session, roster: list[dict[str, Any]] | None = None) -> list[dict]:
    """The rooms a scene may be set in, each ``{id, name, where, who}``.

    ``who`` is the roster members whose desk is in that room, matched by role as the office
    view matches them, so the writer can put a person at their own desk.
    """
    members = [
        (str(m.get("display_name") or ""), str(m.get("role_name") or "")) for m in roster or []
    ]
    found: list[dict] = []
    for zone in DEFAULT_OFFICE_LAYOUT["zones"]:
        name = str(zone.get("name") or zone["id"]).split("—")[-1].strip()
        desks = [str(desk.get("role_name") or "").lower() for desk in zone.get("desks") or []]
        who = [
            display
            for display, role in members
            if display and any(desk and desk in role.lower() for desk in desks)
        ]
        found.append(
            {"id": zone["id"], "name": name, "where": _floor(zone.get("floor")), "who": who}
        )
    for room in session.scalars(select(Room).order_by(Room.name)):
        found.append(
            {
                "id": f"room-{_slug(room.name)}",
                "name": room.name,
                "where": room.purpose or "",
                "who": [],
            }
        )
    return found


def location_id(written: Any, locations: list[dict]) -> str | None:
    """The id of the room a model named, by its id or its name; None when it is no room."""
    key = " ".join(str(written or "").casefold().split())
    if not key:
        return None
    for place in locations:
        if key in (place["id"].casefold(), place["name"].casefold(), _slug(place["name"])):
            return str(place["id"])
    return None


def location_name(written: Any, locations: list[dict]) -> str:
    """How the storyboard names a beat's room: its name and floor, or the text as written."""
    found = location_id(written, locations)
    for place in locations:
        if place["id"] == found:
            return f"{place['name']}, {place['where']}" if place["where"] else place["name"]
    return str(written or "").strip()
