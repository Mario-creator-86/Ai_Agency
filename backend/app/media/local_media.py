"""Local media's catalog prices and provider identity, shared by the existing film steps."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.media.cost_plan import DOCUMENTED, PriceRow, PriceTable


def is_local(adapter: Any) -> bool:
    from app.providers.comfyui import ComfyConnection  # noqa: PLC0415

    return isinstance(adapter, ComfyConnection)


def writer_constraints(engine: Engine, target_seconds: int) -> str:
    """Tell the writer the selected local model's actual shot limit before it writes."""
    with Session(engine) as session:
        selection = session.get(ServiceSelection, "video")
        if not selection or not selection.integration_id:
            return ""
        connection = session.get(Integration, selection.integration_id)
        production = session.get(MediaProductionConfig, selection.integration_id)
        if not connection or connection.kind != "comfyui" or not production:
            return ""
        resource = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == connection.id,
                ProviderResource.remote_id == production.model_id,
            )
        )
        if resource is None:
            return ""
        maximum = float((resource.api_metadata or {}).get("max_seconds", 0))
    if maximum <= 1:
        return ""
    from app.factual.editorial import WORDS_PER_SECOND  # noqa: PLC0415
    from app.media.assembler import TRANSITION_SECONDS  # noqa: PLC0415

    shot_seconds = maximum - TRANSITION_SECONDS
    words = max(1, math.floor((shot_seconds - 0.4) * WORDS_PER_SECOND))
    shots = math.ceil(target_seconds / max(1, shot_seconds - 0.4))
    return (
        f"\nLOCAL VIDEO CONSTRAINT (takes precedence over generic scene counts): "
        f"the selected profile generates at most {maximum:g} seconds per shot, including "
        f"{TRANSITION_SECONDS:g}s for transitions. Write about {shots} short scenes, "
        f"each narration at most {words} words, with one simple visible action. "
        "Split a beat across distinct short shots when necessary. Do not stretch a still "
        "or request a long shot. Keep the story coherent and cite each scene. "
        "Describe generated visuals as illustrations, not actual archival footage.\n"
    )


def local_prices(engine: Engine, table: PriceTable) -> PriceTable:
    rows = list(table.rows)
    seconds = dict(table.seconds)
    stills_model = table.stills_model
    with Session(engine) as session:
        resources = session.execute(
            select(ProviderResource, Integration)
            .join(Integration, Integration.id == ProviderResource.integration_id)
            .where(
                Integration.kind == "comfyui",
                Integration.status == "VERIFIED",
                ProviderResource.api_available.is_(True),
            )
        ).all()
        for resource, _integration in resources:
            meta = resource.api_metadata or {}
            purpose = meta.get("purpose")
            if purpose not in ("image", "video"):
                continue
            rows = [row for row in rows if row.model_id != resource.remote_id]
            rows.append(
                PriceRow(
                    model_id=resource.remote_id,
                    kind=purpose,
                    resolution="*",
                    source_url=str(meta.get("source") or "local execution"),
                    date=datetime.now(UTC).date().isoformat(),
                    provenance=DOCUMENTED,
                    credits_per_image=0.0 if purpose == "image" else None,
                    credits_per_second=0.0 if purpose == "video" else None,
                )
            )
            if purpose == "video":
                seconds[resource.remote_id] = {"min": 1, "max": int(meta["max_seconds"])}
        selection = session.get(ServiceSelection, "image")
        if selection and selection.integration_id:
            row = session.get(Integration, selection.integration_id)
            config = session.get(MediaProductionConfig, selection.integration_id)
            if row and row.kind == "comfyui" and config and config.image_model_id:
                stills_model = config.image_model_id
    return replace(table, rows=tuple(rows), seconds=seconds, stills_model=stills_model)
