"""The office layout the backend serves and the rendered headquarters must describe one building.

The rooms and seats live twice: in DEFAULT_OFFICE_LAYOUT (where work happens, which desk an agent
has) and in the Blender build's manifest (where that room and seat are drawn). If they drift, an
agent is drawn in the wrong room and the lift is sent to the wrong floor, so they are compared.
"""

import json
from pathlib import Path

from app.office.services import DEFAULT_OFFICE_LAYOUT

MANIFEST = (
    Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets" / "hq" / "manifest.json"
)


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_world_has_the_size_of_the_rendered_scene():
    m = manifest()
    assert DEFAULT_OFFICE_LAYOUT["width"] == m["world"]["width"]
    assert DEFAULT_OFFICE_LAYOUT["height"] == m["world"]["height"]


def test_every_room_is_where_the_building_draws_it():
    rooms = manifest()["rooms"]
    for zone in DEFAULT_OFFICE_LAYOUT["zones"]:
        room = rooms[zone["id"]]
        assert (zone["x"], zone["y"], zone["width"], zone["height"]) == (
            room["x"],
            room["y"],
            room["w"],
            room["h"],
        ), zone["id"]
        assert zone["floor"] == room["level"], zone["id"]


def test_every_desk_is_a_seat_in_the_scene():
    seats = manifest()["seats"]
    for zone in DEFAULT_OFFICE_LAYOUT["zones"]:
        for desk in zone["desks"]:
            if desk["id"].startswith("rack_"):
                continue
            seat = seats[desk["id"]]
            assert seat["zone"] == zone["id"], desk["id"]
            assert abs(seat["x"] - desk["x"]) <= 1 and abs(seat["y"] - desk["y"]) <= 1, desk["id"]


def test_the_lift_stops_at_every_floor():
    m = manifest()
    floors = {str(z["floor"]) for z in DEFAULT_OFFICE_LAYOUT["zones"]}
    assert floors <= set(m["lift"]["stops"])
    assert DEFAULT_OFFICE_LAYOUT["building"]["elevator_x"] == m["lift"]["shaft"]["x"]
