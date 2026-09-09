"""Phase 7 Pydantic schemas for Analytics, Experiments, and Continuous Learning."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class AnalyticsSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    publication_id: str
    channel_id: str
    window: str
    views: int
    watch_time_seconds: float
    average_view_percentage: float
    impressions: int
    ctr_percentage: float
    likes: int
    comments: int
    shares: int
    subscribers_gained: int
    subscribers_lost: int
    snapshot_at: str


class ContentExperimentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    name: str
    hypothesis: str
    target_metric: str
    guardrail_metrics_json: dict[str, Any]
    status: str
    control_variant: str
    treatment_variant: str
    sample_size_target: int
    control_count: int
    treatment_count: int
    confidence_score: float
    outcome_decision: str | None
    started_at: str
    concluded_at: str | None


class CreateExperimentCommand(BaseModel):
    channel_id: str
    name: str = Field(min_length=1, max_length=100)
    hypothesis: str = Field(min_length=1, max_length=1000)
    target_metric: str = Field(default="RETENTION_RATE")
    control_variant: str = Field(min_length=1, max_length=100)
    treatment_variant: str = Field(min_length=1, max_length=100)
    sample_size_target: int = Field(default=3, ge=1, le=100)
    guardrail_metrics: dict[str, Any] = Field(default_factory=dict)


class ContentStrategyView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    version: int
    topic_weights_json: dict[str, float]
    hook_weights_json: dict[str, float]
    target_duration_seconds: int
    cooldown_until: str | None
    notes: str
    is_active: bool
    created_at: str


class DirectorRecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    channel_id: str
    strategy_id: str | None
    recommendation_type: str
    target_entity: str
    suggested_weight_change: float
    sample_size: int
    mean_retention: float
    mean_ctr: float
    confidence_score: float
    evidence_summary: str
    status: str
    created_at: str


class CohortMetricView(BaseModel):
    cohort_key: str
    cohort_type: str  # topic | hook | duration
    sample_size: int
    mean_retention: float
    mean_ctr: float
    mean_views: float
    clickbait_penalty_applied: bool
    score: float


class ChannelAnalyticsSummaryView(BaseModel):
    channel_id: str
    total_views: int
    total_watch_time_seconds: float
    average_retention_percentage: float
    average_ctr_percentage: float
    total_publications: int
    total_snapshots: int
    active_strategy_version: int
    pending_recommendations_count: int


class IngestMetricsCommand(BaseModel):
    window: str = Field(default="LIFETIME")
