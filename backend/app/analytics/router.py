"""Phase 7 FastAPI router for Autonomous Analytics & Continuous Learning.

Analytics report what a platform measured. There is no local substitute for that, so when no
analytics provider is configured these endpoints return HTTP 503 and record nothing. The studio
never derives, estimates or simulates an audience figure — a fabricated view count would corrupt
the learning loop that reads it back and, through the Director's recommendations, the editorial
strategy itself.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.analytics.schemas import (
    AnalyticsSnapshotView,
    ChannelAnalyticsSummaryView,
    CohortMetricView,
    ContentExperimentView,
    ContentStrategyView,
    CreateExperimentCommand,
    DirectorRecommendationView,
    IngestMetricsCommand,
)
from app.analytics.services import (
    MetricsUnavailable,
    apply_director_recommendation,
    compute_cohort_metrics,
    create_experiment,
    generate_director_recommendations,
    get_active_strategy,
    get_channel_summary,
    ingest_publication_metrics,
    list_channel_experiments,
    list_channel_recommendations,
    story_performance,
)
from app.providers.analytics_base import AnalyticsProvider
from app.providers.youtube_analytics import YouTubeAnalyticsProvider
from app.security import require_owner

ANALYTICS_NOT_CONFIGURED_DETAIL = (
    "Analiza performanței nu este disponibilă: nu există nicio conexiune YouTube verificată. "
    "Adaugă și verifică o conexiune YouTube în Settings. Studioul nu estimează și nu simulează "
    "cifre de audiență."
)


def get_analytics_provider(request: Request) -> AnalyticsProvider:
    """Return the configured analytics provider, or refuse.

    Tests inject their own adapter through ``app.state.analytics_provider``; there is no
    production fallback, because the only thing a fallback could report is an invention.
    """
    injected = getattr(request.app.state, "analytics_provider", None)
    if injected is not None:
        return injected  # type: ignore[no-any-return]

    provider = YouTubeAnalyticsProvider.from_verified_settings(
        request.app.state.engine, request.app.state.credential_vault
    )
    if provider is None:
        raise HTTPException(status_code=503, detail=ANALYTICS_NOT_CONFIGURED_DETAIL)
    return provider


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/analytics", dependencies=[Depends(require_owner)])

    @router.get("/trends")
    def get_trends(request: Request) -> dict:
        """What people in the studio's country are searching for, as last read."""
        from app.analytics.trends import trending_now  # noqa: PLC0415

        settings = request.app.state.settings
        return {
            "geo": settings.trends_geo,
            "enabled": settings.trends_enabled,
            "items": trending_now(request.app.state.engine, settings.trends_geo, limit=25),
        }

    @router.post("/trends/refresh")
    def post_trends_refresh(request: Request) -> dict:
        """Read the feed now. Says what happened, including a feed that did not answer."""
        from app.analytics.trends import refresh_trends  # noqa: PLC0415

        return refresh_trends(request.app.state.engine, request.app.state.settings)

    @router.get("/channels/{channel_id}/summary", response_model=ChannelAnalyticsSummaryView)
    def get_summary(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return get_channel_summary(request.app.state.engine, channel_id)

    @router.get("/story-performance")
    def read_story_performance(request: Request, channel_id: str | None = None) -> dict:
        """What the studio predicted about each film, beside what the audience actually did."""
        return story_performance(request.app.state.engine, channel_id)

    @router.get("/cohorts/{channel_id}", response_model=list[CohortMetricView])
    def get_cohorts(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
        cohort_by: Annotated[str, Query(pattern="^(topic|hook|duration)$")] = "topic",
    ) -> list[dict]:
        return compute_cohort_metrics(request.app.state.engine, channel_id, cohort_by=cohort_by)

    @router.post("/ingest/{publication_id}", response_model=AnalyticsSnapshotView)
    def ingest_metrics(
        request: Request,
        publication_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: IngestMetricsCommand | None = None,
    ) -> dict:
        window = cmd.window if cmd else "LIFETIME"
        provider = get_analytics_provider(request)
        try:
            return ingest_publication_metrics(
                request.app.state.engine,
                publication_id,
                provider,
                window=window,
                correlation_id=request.headers.get("X-Correlation-ID", ""),
            )
        except MetricsUnavailable as exc:
            # The publication exists but nothing measurable is attached to it yet.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SQLAlchemyError:
            raise HTTPException(status_code=500, detail="Internal error") from None
        except (OSError, RuntimeError) as exc:
            # The platform did not answer. Nothing was stored, and we say so.
            raise HTTPException(
                status_code=502,
                detail=(
                    "Platforma nu a returnat date de performanță, deci nu s-a înregistrat "
                    "nicio măsurătoare. Încearcă din nou mai târziu."
                ),
            ) from exc

    @router.get("/strategy/{channel_id}", response_model=ContentStrategyView)
    def get_strategy(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        strat = get_active_strategy(request.app.state.engine, channel_id)
        if strat is None:
            raise HTTPException(status_code=404, detail="No active strategy found")
        return strat

    @router.get("/recommendations/{channel_id}", response_model=list[DirectorRecommendationView])
    def get_recommendations(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> list[dict]:
        return list_channel_recommendations(request.app.state.engine, channel_id)

    @router.post(
        "/recommendations/{channel_id}/generate", response_model=list[DirectorRecommendationView]
    )
    def generate_recommendations(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> list[dict]:
        return generate_director_recommendations(
            request.app.state.engine,
            channel_id,
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        )

    @router.post("/recommendations/{rec_id}/apply", response_model=ContentStrategyView)
    def apply_recommendation(
        request: Request,
        rec_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        try:
            return apply_director_recommendation(
                request.app.state.engine,
                rec_id,
                correlation_id=request.headers.get("X-Correlation-ID", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/experiments/{channel_id}", response_model=list[ContentExperimentView])
    def get_experiments(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> list[dict]:
        return list_channel_experiments(request.app.state.engine, channel_id)

    @router.post("/experiments", response_model=ContentExperimentView)
    def create_new_experiment(
        request: Request,
        cmd: CreateExperimentCommand,
    ) -> dict:
        return create_experiment(
            request.app.state.engine,
            cmd.channel_id,
            cmd.name,
            cmd.hypothesis,
            cmd.control_variant,
            cmd.treatment_variant,
            target_metric=cmd.target_metric,
            sample_size_target=cmd.sample_size_target,
            guardrail_metrics=cmd.guardrail_metrics,
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        )

    return router
