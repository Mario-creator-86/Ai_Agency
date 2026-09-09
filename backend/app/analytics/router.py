"""Phase 7 FastAPI router for Autonomous Analytics & Continuous Learning."""

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
    apply_director_recommendation,
    compute_cohort_metrics,
    create_experiment,
    generate_director_recommendations,
    get_active_strategy,
    get_channel_summary,
    ingest_publication_metrics,
    list_channel_experiments,
    list_channel_recommendations,
)
from app.providers.deterministic_analytics import DeterministicAnalyticsAdapter
from app.providers.youtube_analytics import YouTubeAnalyticsProvider
from app.security import require_owner


def get_analytics_provider() -> DeterministicAnalyticsAdapter | YouTubeAnalyticsProvider:
    """Select the configured analytics provider (YouTube if OAuth configured, else Deterministic)."""
    yt = YouTubeAnalyticsProvider()
    if yt.is_configured():
        return yt
    return DeterministicAnalyticsAdapter()


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/analytics", dependencies=[Depends(require_owner)])

    @router.get("/channels/{channel_id}/summary", response_model=ChannelAnalyticsSummaryView)
    def get_summary(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return get_channel_summary(request.app.state.engine, channel_id)

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
        provider = get_analytics_provider()
        try:
            return ingest_publication_metrics(
                request.app.state.engine,
                publication_id,
                provider,
                window=window,
                correlation_id=request.headers.get("X-Correlation-ID", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
