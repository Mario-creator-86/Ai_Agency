"""Phase 7 Abstract Analytics Provider interface and metric data structures."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VideoMetrics:
    remote_video_id: str
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
    window: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelMetrics:
    remote_channel_id: str
    total_views: int
    total_watch_time_seconds: float
    total_subscribers: int
    total_videos: int
    window: str
    raw: dict[str, Any] = field(default_factory=dict)


class AnalyticsProvider(abc.ABC):
    """Base abstract class for external analytics adapters."""

    PROVIDER_NAME: str = "BASE"

    @abc.abstractmethod
    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        """Fetch real performance metrics for a specific remote video ID."""

    @abc.abstractmethod
    async def fetch_channel_metrics(
        self, remote_channel_id: str, window: str = "LIFETIME"
    ) -> ChannelMetrics:
        """Fetch aggregate channel performance metrics."""
