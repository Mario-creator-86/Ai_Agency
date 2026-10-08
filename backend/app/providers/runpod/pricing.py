"""Cloud estimates in the existing sheet's budget units; never a vendor credit balance.

RunPod Serverless is priced at the Owner's budget rate (`RunPodConfig.hourly_rate`: 4.00 USD/h
for the RTX PRO 6000; the pricing page says 3.49, the endpoint settings page 0.00111 USD/s, so
the higher figure is budgeted until a real billing record settles it): a still costs its GPU
seconds x rate/3600, a clip its GPU seconds per video second x seconds x rate/3600, and every
ROUND adds its cold start + idle tail ((cold_start_seconds + idle_timeout_seconds) x rate/3600,
`PriceTable.overhead_credits_per_round`). The figures are ESTIMATES from
config/runpod_models.json until the paid bake-off measures them.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.media.cost_plan import ESTIMATED, PriceRow, PriceTable
from app.providers.runpod.config import RunPodConfig


def estimated_prices(engine: Engine, table: PriceTable) -> PriceTable:
    rows, seconds, stills = list(table.rows), dict(table.seconds), table.stills_model
    overhead = dict(table.overhead_credits_per_round)
    round_models = set(table.round_models)
    with Session(engine) as session:
        for resource, integration in session.execute(
            select(ProviderResource, Integration)
            .join(Integration, Integration.id == ProviderResource.integration_id)
            .where(
                Integration.kind == "runpod",
                Integration.status.in_(("VERIFIED", "ACCESS_VERIFIED")),
                ProviderResource.api_available.is_(True),
            )
        ):
            meta = resource.api_metadata or {}
            purpose = meta.get("purpose")
            if purpose not in ("image", "video"):
                continue
            unit = "per_image_usd" if purpose == "image" else "per_second_usd"
            price = (resource.pricing or {}).get(unit)
            if price is None:
                gpu = meta.get(
                    "gpu_seconds_per_image"
                    if purpose == "image"
                    else "gpu_seconds_per_video_second"
                )
                if (
                    isinstance(gpu, int | float)
                    and not isinstance(gpu, bool)
                    and math.isfinite(gpu)
                    and gpu > 0
                ):
                    rate = RunPodConfig.from_integration(dict(integration.config), {}).hourly_rate
                    price = float(rate) * float(gpu) / 3600
            # No forecast => no purchase. Zero is permitted only for the explicit offline mock.
            if (
                isinstance(price, bool)
                or not isinstance(price, int | float)
                or not math.isfinite(price)
                or price < 0
                or (price == 0 and str(integration.config.get("mock")).lower() != "true")
            ):
                continue
            rows = [r for r in rows if r.model_id != resource.remote_id]
            settings = RunPodConfig.from_integration(dict(integration.config), {})
            if settings.mode == "serverless":
                # One batch job per round: its cold start and idle tail, once per round.
                round_models.add(resource.remote_id)
                per_round = (
                    0.0
                    if settings.mock
                    else float(
                        (settings.cold_start_seconds + settings.idle_timeout_seconds)
                        * settings.hourly_rate
                        / 3600
                    )
                )
                overhead[purpose] = max(overhead.get(purpose, 0.0), per_round / table.credit_usd)
            rows.append(
                PriceRow(
                    model_id=resource.remote_id,
                    kind=purpose,
                    resolution="*",
                    source_url="RunPod estimate (config/runpod_models.json, buget 4,00 USD/oră)"
                    if settings.mode == "serverless"
                    else "RunPod /models backend estimate",
                    date=datetime.now(UTC).date().isoformat(),
                    # The studio's GPU-second forecast, never a published tariff.
                    provenance=ESTIMATED,
                    credits_per_image=float(price) / table.credit_usd
                    if purpose == "image"
                    else None,
                    credits_per_second=float(price) / table.credit_usd
                    if purpose == "video"
                    else None,
                )
            )
            maximum = meta.get("max_seconds")
            if (
                purpose == "video"
                and isinstance(maximum, int | float)
                and math.isfinite(maximum)
                and maximum >= 1
            ):
                seconds[resource.remote_id] = {"min": 1, "max": int(maximum)}
        selection = session.get(ServiceSelection, "image")
        integration = (
            session.get(Integration, selection.integration_id)
            if selection and selection.integration_id
            else None
        )
        production = session.get(MediaProductionConfig, integration.id) if integration else None
        if (
            integration
            and integration.kind == "runpod"
            and production
            and production.image_model_id
        ):
            stills = production.image_model_id
    return replace(
        table,
        rows=tuple(rows),
        seconds=seconds,
        stills_model=stills,
        overhead_credits_per_round=overhead,
        round_models=frozenset(round_models),
    )
