"""Office layout and desk assignment services for the 2D visual projection."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord, Role

DEFAULT_OFFICE_LAYOUT: dict[str, Any] = {
    "width": 1200,
    "height": 1000,
    "grid_size": 20,
    "view_mode": "side_view_cutaway",
    "building": {
        "x": 120,
        "y": 60,
        "width": 960,
        "height": 740,
        "floors": 5,
        "elevator_x": 980,
        "elevator_width": 90,
    },
    "zones": [
        {
            "id": "director_suite",
            "name": "Floor 4 — Executive Penthouse (Director / CEO)",
            "zone_type": "DIRECTOR",
            "floor": 4,
            "x": 130,
            "y": 60,
            "width": 840,
            "height": 130,
            "color": "#1e293b",
            "desks": [
                {
                    "id": "desk_director",
                    "name": "Director Desk",
                    "x": 520,
                    "y": 140,
                    "role_name": "Director",
                }
            ],
        },
        {
            "id": "research_lab",
            "name": "Floor 3 — Research & Fact-Check Lab",
            "zone_type": "RESEARCH",
            "floor": 3,
            "x": 130,
            "y": 195,
            "width": 840,
            "height": 130,
            "color": "#0f3460",
            "desks": [
                {
                    "id": "desk_research_1",
                    "name": "Lead Researcher",
                    "x": 350,
                    "y": 275,
                    "role_name": "Researcher",
                },
                {
                    "id": "desk_research_2",
                    "name": "Fact Checker",
                    "x": 680,
                    "y": 275,
                    "role_name": "FactChecker",
                },
            ],
        },
        {
            "id": "script_room",
            "name": "Floor 2 — Creative Writing & Narrative Studio",
            "zone_type": "SCRIPT",
            "floor": 2,
            "x": 130,
            "y": 330,
            "width": 840,
            "height": 130,
            "color": "#1e3a8a",
            "desks": [
                {
                    "id": "desk_script",
                    "name": "Script Writer",
                    "x": 520,
                    "y": 410,
                    "role_name": "ScriptWriter",
                }
            ],
        },
        {
            "id": "audio_booth",
            "name": "Floor 1 — Audio & Voice Booth",
            "zone_type": "AUDIO",
            "floor": 1,
            "x": 130,
            "y": 465,
            "width": 415,
            "height": 130,
            "color": "#3b185f",
            "desks": [
                {
                    "id": "desk_audio",
                    "name": "Voice Artist",
                    "x": 330,
                    "y": 545,
                    "role_name": "VoiceArtist",
                }
            ],
        },
        {
            "id": "video_studio",
            "name": "Floor 1 — Video & Render Bay",
            "zone_type": "VIDEO",
            "floor": 1,
            "x": 555,
            "y": 465,
            "width": 415,
            "height": 130,
            "color": "#4a0e4e",
            "desks": [
                {
                    "id": "desk_video",
                    "name": "Video Editor",
                    "x": 750,
                    "y": 545,
                    "role_name": "VideoEditor",
                }
            ],
        },
        {
            "id": "server_corner",
            "name": "Ground Floor — AI Datacenter & Racks",
            "zone_type": "SERVER",
            "floor": 0,
            "x": 130,
            "y": 600,
            "width": 210,
            "height": 200,
            "color": "#16213e",
            "desks": [
                {
                    "id": "rack_ollama",
                    "name": "Ollama Cluster",
                    "x": 190,
                    "y": 788,
                    "role_name": "OllamaHost",
                },
                {
                    "id": "rack_cloud",
                    "name": "Cloud Gateway",
                    "x": 285,
                    "y": 788,
                    "role_name": "CloudGateway",
                },
            ],
        },
        {
            "id": "accounting_office",
            "name": "Ground Floor — Accounting & Treasury",
            "zone_type": "FINANCE",
            "floor": 0,
            "x": 350,
            "y": 600,
            "width": 230,
            "height": 200,
            "color": "#1f1a2e",
            "desks": [
                {
                    "id": "desk_accounting",
                    "name": "Accountant Desk",
                    "x": 465,
                    "y": 788,
                    "role_name": "Accountant",
                }
            ],
        },
        {
            "id": "publish_desk",
            "name": "Ground Floor — Publishing & Distribution",
            "zone_type": "PUBLISH",
            "floor": 0,
            "x": 590,
            "y": 600,
            "width": 200,
            "height": 200,
            "color": "#14532d",
            "desks": [
                {
                    "id": "desk_publish",
                    "name": "Release Desk",
                    "x": 690,
                    "y": 788,
                    "role_name": "Publisher",
                }
            ],
        },
        {
            "id": "ad_shop",
            "name": "Ground Floor — Ad Space Storefront",
            "zone_type": "SHOP",
            "floor": 0,
            "x": 800,
            "y": 600,
            "width": 170,
            "height": 200,
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
        # Load all hired/active agents
        agents = session.scalars(
            select(Agent).where(Agent.lifecycle.in_(["HIRED", "ACTIVE", "PAUSED", "SUSPENDED"]))
        ).all()

        role_map = {r.id: r.name for r in session.scalars(select(Role)).all()}

        # The model each agent is actually assigned, so the interface can show it instead of
        # a value written into the page. `is_available` travels with it: an agent can hold an
        # assignment to a model whose provider has not been verified, and saying "assigned"
        # without saying "unverified" would be the same half-truth as before.
        model_map = {
            m.id: {
                "model_name": m.model_name,
                "model_is_available": m.is_available,
                "provider_name": provider_names.get(m.provider_id, "Furnizor necunoscut"),
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

        layout["assignments"] = desk_assignments
        layout["unassigned_count"] = len(agents) - len(assigned_agents)
        return layout
