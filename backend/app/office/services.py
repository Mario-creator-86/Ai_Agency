"""Office layout and desk assignment services for the 2D visual projection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord, Role

PIXEL_OFFICE = json.loads(
    (Path(__file__).resolve().parents[3] / "config/pixel_office.json").read_text(encoding="utf-8")
)
VISIBLE_LIFECYCLES = {"HIRED", "ACTIVE", "PAUSED", "SUSPENDED"}


def personal_pixel_slots(agents: list[Agent], role_map: dict[str, str]) -> dict[str, int]:
    """Reserve an employee's personal seat from immutable hiring order, including former staff.

    The first hire in a seeded role gets its illustrated room; later hires get annex seats.
    Retained offboarded rows keep their reservation, so pausing, leaving or hiring cannot move
    another employee. A seat is presentation metadata, never an agent policy/capability.
    """
    primary = {station["role"].casefold(): i for i, station in enumerate(PIXEL_OFFICE["stations"])}
    primary["researcher"] = primary["leadresearcher"]
    used: set[int] = set()
    slots: dict[str, int] = {}
    extra = len(PIXEL_OFFICE["stations"])
    for agent in sorted(agents, key=lambda a: (a.hired_at, a.id)):
        preferred = primary.get(role_map.get(agent.role_id, "").casefold())
        slot = preferred if preferred is not None and preferred not in used else extra
        if slot == extra:
            extra += 1
        slots[agent.id] = slot
        used.add(slot)
    return slots


DEFAULT_OFFICE_LAYOUT: dict[str, Any] = {
    # World pixels of the headquarters scene (frontend/public/assets/hq/manifest.json, built in
    # Blender from art-source/blender/hq). Rooms and seats are the ones the rendered building
    # has; tests/test_office_layout_matches_scene.py keeps the two in step.
    "width": 1600,
    "height": 840,
    "grid_size": 20,
    "view_mode": "side_view_cutaway",
    "building": {
        "x": 415,
        "y": 10,
        "width": 937,
        "height": 665,
        "floors": 5,
        "elevator_x": 1215,
        "elevator_width": 62,
    },
    "zones": [
        {
            "id": "director_suite",
            "name": "Floor 4 — Executive Penthouse (Director / CEO)",
            "zone_type": "DIRECTOR",
            "floor": 4,
            "x": 517,
            "y": 85,
            "width": 688,
            "height": 92,
            "color": "#1e293b",
            "desks": [
                {
                    "id": "desk_director",
                    "name": "Director Desk",
                    "x": 811,
                    "y": 171,
                    "role_name": "Director",
                }
            ],
        },
        {
            "id": "research_lab",
            "name": "Floor 3 — Research",
            "zone_type": "RESEARCH",
            "floor": 3,
            "x": 517,
            "y": 195,
            "width": 345,
            "height": 87,
            "color": "#0f3460",
            "desks": [
                {
                    "id": "desk_research_1",
                    "name": "Lead Researcher",
                    "x": 672,
                    "y": 276,
                    "role_name": "Researcher",
                },
            ],
        },
        {
            # Every department has its own office (the Owner, 2026-09-13).
            "id": "factcheck_room",
            "name": "Floor 3 — Fact Check",
            "zone_type": "FACT_CHECK",
            "floor": 3,
            "x": 868,
            "y": 195,
            "width": 337,
            "height": 87,
            "color": "#5a2e22",
            "desks": [
                {
                    "id": "desk_research_2",
                    "name": "Fact Checker",
                    "x": 926,
                    "y": 276,
                    "role_name": "FactChecker",
                },
            ],
        },
        {
            "id": "script_room",
            "name": "Floor 2 — Content",
            "zone_type": "SCRIPT",
            "floor": 2,
            "x": 517,
            "y": 297,
            "width": 345,
            "height": 95,
            "color": "#1e3a8a",
            "desks": [
                {
                    "id": "desk_script",
                    "name": "Script Writer",
                    "x": 804,
                    "y": 386,
                    "role_name": "ScriptWriter",
                }
            ],
        },
        {
            # Distribution has its own office beside Content (the Owner, 2026-09-13).
            "id": "publish_desk",
            "name": "Floor 2 — Distribution",
            "zone_type": "PUBLISH",
            "floor": 2,
            "x": 868,
            "y": 297,
            "width": 337,
            "height": 95,
            "color": "#134e4a",
            "desks": [
                {
                    "id": "desk_publish",
                    "name": "Release Desk",
                    "x": 1000,
                    "y": 386,
                    "role_name": "Publisher",
                }
            ],
        },
        {
            "id": "audio_booth",
            "name": "Floor 1 — Audio & Voice Booth",
            "zone_type": "AUDIO",
            "floor": 1,
            "x": 517,
            "y": 410,
            "width": 345,
            "height": 90,
            "color": "#3b185f",
            "desks": [
                {
                    "id": "desk_audio",
                    "name": "Voice Artist",
                    "x": 668,
                    "y": 494,
                    "role_name": "VoiceArtist",
                }
            ],
        },
        {
            "id": "video_studio",
            "name": "Floor 1 — Video & Render Bay",
            "zone_type": "VIDEO",
            "floor": 1,
            "x": 867,
            "y": 410,
            "width": 338,
            "height": 90,
            "color": "#4a0e4e",
            "desks": [
                {
                    "id": "desk_video",
                    "name": "Video Editor",
                    "x": 1022,
                    "y": 494,
                    "role_name": "VideoEditor",
                }
            ],
        },
        {
            "id": "server_corner",
            "name": "Ground Floor — AI Datacenter & Racks",
            "zone_type": "SERVER",
            "floor": 0,
            "x": 455,
            "y": 520,
            "width": 182,
            "height": 135,
            "color": "#16213e",
            "desks": [
                {
                    "id": "rack_ollama",
                    "name": "Ollama Cluster",
                    "x": 496,
                    "y": 648,
                    "role_name": "OllamaHost",
                },
                {
                    "id": "rack_cloud",
                    "name": "Cloud Gateway",
                    "x": 587,
                    "y": 648,
                    "role_name": "CloudGateway",
                },
            ],
        },
        {
            "id": "lobby",
            "name": "Ground Floor — Lobby",
            "zone_type": "LOBBY",
            "floor": 0,
            "x": 645,
            "y": 520,
            "width": 240,
            "height": 135,
            "color": "#3a2c1c",
            "desks": [],
        },
        {
            "id": "accounting_office",
            "name": "Ground Floor — Accounting & Treasury",
            "zone_type": "FINANCE",
            "floor": 0,
            "x": 897,
            "y": 520,
            "width": 135,
            "height": 135,
            "color": "#5c2a33",
            "desks": [
                {
                    "id": "desk_accounting",
                    "name": "Accountant Desk",
                    "x": 965,
                    "y": 648,
                    "role_name": "Accountant",
                }
            ],
        },
        {
            "id": "ad_shop",
            "name": "Ground Floor — Ad Space Storefront",
            "zone_type": "SHOP",
            "floor": 0,
            "x": 1040,
            "y": 520,
            "width": 157,
            "height": 135,
            "color": "#2a2318",
            "desks": [],
        },
    ],
}


def get_office_layout_with_assignments(engine: Engine) -> dict[str, Any]:
    """Return the authoritative office layout with active agents assigned to desks."""
    layout = {**DEFAULT_OFFICE_LAYOUT}
    layout["zones"] = [dict(z) for z in DEFAULT_OFFICE_LAYOUT["zones"]]

    with Session(engine) as session:
        provider_names = {p.id: p.name for p in session.scalars(select(ProviderRecord))}
        # Former employees reserve their old seat; they are never drawn as current staff.
        all_agents = list(session.scalars(select(Agent)).all())
        agents = [agent for agent in all_agents if agent.lifecycle in VISIBLE_LIFECYCLES]

        role_map = {r.id: r.name for r in session.scalars(select(Role)).all()}
        pixel_slots = personal_pixel_slots(all_agents, role_map)

        # The model each agent is actually assigned, so the interface can show it instead of
        # a value written into the page. `is_available` travels with it: an agent can hold an
        # assignment to a model whose provider has not been verified, and saying "assigned"
        # without saying "unverified" would be the same half-truth as before.
        model_map = {
            m.id: {
                "model_name": m.model_name,
                "model_is_available": m.is_available,
                "provider_name": provider_names.get(m.provider_id, "Unknown provider"),
            }
            for m in session.scalars(select(ModelRecord))
        }

        # Assign agents to desks matching role or sequentially
        assigned_agents = set()
        desk_assignments = []

        for zone in layout["zones"]:
            if zone.get("zone_type") == "SERVER":
                continue
            for desk in zone.get("desks", []):
                # Look for matching unassigned agent
                desk_agent = None
                for a in agents:
                    if a.id not in assigned_agents:
                        role_name = role_map.get(a.role_id, "")
                        if (
                            role_name.lower() in desk["name"].lower()
                            or desk["role_name"].lower() in role_name.lower()
                        ):
                            desk_agent = a
                            break

                # If no role match, assign first unassigned
                if desk_agent is None:
                    for a in agents:
                        if a.id not in assigned_agents:
                            desk_agent = a
                            break

                if desk_agent:
                    assigned_agents.add(desk_agent.id)
                    desk_assignments.append(
                        {
                            "desk_id": desk["id"],
                            "agent_id": desk_agent.id,
                            "display_name": desk_agent.display_name,
                            "role_name": role_map.get(desk_agent.role_id, "Agent"),
                            "runtime_state": desk_agent.runtime_state,
                            "lifecycle": desk_agent.lifecycle,
                            "version": desk_agent.version,
                            "x": desk["x"],
                            "y": desk["y"],
                            # None when the Owner has not assigned a model yet; the
                            # interface says so rather than showing a plausible default.
                            "model_id": desk_agent.model_id,
                            **(
                                model_map.get(desk_agent.model_id or "")
                                or {
                                    "model_name": None,
                                    "model_is_available": False,
                                    "provider_name": None,
                                }
                            ),
                        }
                    )

        # Extra staff also have a personal desk. The active pixel view displays another office
        # page instead of squeezing multiple employees onto one desk or silently hiding them.
        for agent in agents:
            if agent.id in assigned_agents:
                continue
            station = PIXEL_OFFICE["stations"][
                pixel_slots[agent.id] % len(PIXEL_OFFICE["stations"])
            ]
            desk_assignments.append(
                {
                    "desk_id": f"desk_agent_{agent.id}",
                    "agent_id": agent.id,
                    "display_name": agent.display_name,
                    "role_name": role_map.get(agent.role_id, "Agent"),
                    "runtime_state": agent.runtime_state,
                    "lifecycle": agent.lifecycle,
                    "version": agent.version,
                    "x": station["x"],
                    "y": station["y"],
                    "model_id": agent.model_id,
                    **(
                        model_map.get(agent.model_id or "")
                        or {
                            "model_name": None,
                            "model_is_available": False,
                            "provider_name": None,
                        }
                    ),
                }
            )
        for assignment in desk_assignments:
            assignment["pixel_slot"] = pixel_slots[assignment["agent_id"]]
            assignment["pixel_desk_id"] = f"pixel_desk_{assignment['agent_id']}"
        layout["pixel_office"] = PIXEL_OFFICE
        layout["assignments"] = desk_assignments
        layout["unassigned_count"] = 0
        return layout
