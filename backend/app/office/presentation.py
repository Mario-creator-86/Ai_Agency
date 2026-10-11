"""Read-only scene choreography. Domain state remains the agent's actual state."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.media.models import MediaAsset
from app.publishing.models import ChannelRecord, PublicationRecord
from app.office.services import get_office_layout_with_assignments
from app.media.storage import media_file_inside

CONFIG = json.loads((Path(__file__).resolve().parents[3] / "config/pixel_presentation.json").read_text(encoding="utf-8"))
ALIASES = {"EXECUTING": "WORKING", "RUNNING": "WORKING", "PLANNING": "THINKING", "FAILED": "ERROR"}


def agent_presentation(agent: dict, now_ms: int) -> dict:
    state = str(agent.get("runtime_state", "UNKNOWN")).upper()
    mode = ALIASES.get(state, state)
    active = agent.get("lifecycle") == "ACTIVE"
    cycle = CONFIG["cycles"].get(mode, []) if active else []
    seed = int.from_bytes(hashlib.sha256(str(agent["agent_id"]).encode()).digest()[:4], "big")
    duration = sum(item[1] for item in cycle)
    return {
        "agent_id": agent["agent_id"], "version": agent.get("version", 0),
        "runtime_state": state, "lifecycle": agent.get("lifecycle"),
        "mode": mode if active else "PAUSED", "cycle": cycle,
        "phase_ms": (now_ms + seed) % duration if duration else 0,
        "desk_id": agent.get("pixel_desk_id"),
        "kind": "presentation_only", "monitor": "on" if active and cycle else "off",
    }


def monitor_media(engine, roots: list[Path] | None = None) -> dict:
    """Only confirmed real public/unlisted publications, no provider call or simulation."""
    with Session(engine) as session:
        channels = session.scalars(select(ChannelRecord).where(ChannelRecord.platform == "YOUTUBE")).all()
        publications = session.scalars(select(PublicationRecord).join(
            ChannelRecord, PublicationRecord.channel_id == ChannelRecord.id,
        ).where(
            ChannelRecord.platform == "YOUTUBE",
            PublicationRecord.status == "PUBLISHED",
            PublicationRecord.remote_privacy_status.in_(["public", "unlisted"]),
            PublicationRecord.remote_upload_status == "processed",
        ).order_by(PublicationRecord.published_at.desc()).limit(12)).all()
        videos = [{"id": p.remote_video_id, "title": p.title, "channel_id": p.channel_id}
                  for p in publications if re.fullmatch(r"[A-Za-z0-9_-]{11}", p.remote_video_id or "")]
        assets = session.scalars(select(MediaAsset).where(
            MediaAsset.asset_type == "RENDERED_VIDEO", MediaAsset.mime_type == "video/mp4",
        ).order_by(MediaAsset.created_at.desc()).limit(12)).all()
        local = []
        for asset in assets:
            path = media_file_inside(asset.uri_or_path, roots or [])
            if path is None or asset.provider_name in {"FAKE", "SIMULATED", "DUMMY"}:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= CONFIG['media_max_bytes']:
                local.append({"id": asset.id, "stream": f"/media/assets/{asset.id}/stream", "size": size})
            if len(local) >= 3:
                break
        return {"youtube": videos, "local": local,
                "channels": [{"id": c.id, "name": c.channel_name, "remote_id": c.remote_channel_id} for c in channels],
                "empty_reason": None if videos or local else "Nu există încă un film redabil în biblioteca studioului."}


def presentation_snapshot(engine, *, now_ms: int | None = None, roots: list[Path] | None = None) -> dict:
    at = int(time.time() * 1000) if now_ms is None else now_ms
    layout = get_office_layout_with_assignments(engine)
    return {"schema": 1, "server_ms": at, "valid_ms": CONFIG["valid_ms"],
            "agents": [agent_presentation(a, at) for a in layout["assignments"]],
            "media": monitor_media(engine, roots)}
