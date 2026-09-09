"""Phase 7 Deterministic Zero-Paywall Analytics Adapter.

Provides reproducible, deterministic performance metrics for local development,
CI environments, and automated verification without external API keys or cost.
Derives metrics deterministically from hashing video identifiers and metadata.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.providers.analytics_base import AnalyticsProvider, ChannelMetrics, VideoMetrics


class DeterministicAnalyticsAdapter(AnalyticsProvider):
    PROVIDER_NAME = "DETERMINISTIC_ANALYTICS"

    def __init__(self, seed_prefix: str = "studio_analytics_seed_") -> None:
        self.seed_prefix = seed_prefix

    def _hash_value(self, key: str) -> int:
        h = hashlib.sha256(f"{self.seed_prefix}{key}".encode()).hexdigest()
        return int(h[:8], 16)

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        h_val = self._hash_value(f"{remote_video_id}_{window}")

        # Window multiplier
        window_factors = {
            "1h": 0.05,
            "24h": 0.25,
            "7d": 0.70,
            "28d": 0.95,
            "LIFETIME": 1.0,
        }
        factor = window_factors.get(window, 1.0)

        # Baseline views between 1,500 and 65,000
        base_views = 1500 + (h_val % 63500)
        views = max(10, int(base_views * factor))

        # Check for special test flags in remote_video_id
        is_clickbait = "clickbait" in remote_video_id.lower()
        is_viral = "viral" in remote_video_id.lower()
        is_high_retention = "high_ret" in remote_video_id.lower()

        if is_clickbait:
            # High CTR, very low retention (triggers clickbait penalty)
            ctr_percentage = 14.5
            average_view_percentage = 24.0
        elif is_high_retention:
            ctr_percentage = 8.5
            average_view_percentage = 74.0
        elif is_viral:
            views = int(250000 * factor)
            ctr_percentage = 12.0
            average_view_percentage = 68.0
        else:
            # Normal realistic distribution
            average_view_percentage = round(40.0 + ((h_val >> 4) % 350) / 10.0, 1)  # 40.0% to 75.0%
            ctr_percentage = round(3.5 + ((h_val >> 8) % 75) / 10.0, 1)  # 3.5% to 11.0%

        impressions = max(views, int(views / max(0.01, ctr_percentage / 100.0)))
        watch_time_seconds = round(views * (average_view_percentage / 100.0) * 45.0, 1)

        likes = int(views * (0.04 + ((h_val >> 12) % 40) / 1000.0))
        comments = int(views * (0.005 + ((h_val >> 16) % 15) / 1000.0))
        shares = int(views * (0.002 + ((h_val >> 20) % 10) / 1000.0))
        subscribers_gained = max(0, int(views * 0.008))
        subscribers_lost = max(0, int(subscribers_gained * 0.1))

        return VideoMetrics(
            remote_video_id=remote_video_id,
            views=views,
            watch_time_seconds=watch_time_seconds,
            average_view_percentage=average_view_percentage,
            impressions=impressions,
            ctr_percentage=ctr_percentage,
            likes=likes,
            comments=comments,
            shares=shares,
            subscribers_gained=subscribers_gained,
            subscribers_lost=subscribers_lost,
            window=window,
            raw={
                "adapter": "DeterministicAnalyticsAdapter",
                "simulated": True,
                "remote_video_id": remote_video_id,
                "window": window,
            },
        )

    async def fetch_channel_metrics(
        self, remote_channel_id: str, window: str = "LIFETIME"
    ) -> ChannelMetrics:
        h_val = self._hash_value(f"chan_{remote_channel_id}_{window}")
        total_views = 50000 + (h_val % 450000)
        total_watch_time = float(total_views * 28.0)
        total_subs = 1200 + (h_val % 18000)
        total_videos = 12 + (h_val % 30)

        return ChannelMetrics(
            remote_channel_id=remote_channel_id,
            total_views=total_views,
            total_watch_time_seconds=total_watch_time,
            total_subscribers=total_subs,
            total_videos=total_videos,
            window=window,
            raw={
                "adapter": "DeterministicAnalyticsAdapter",
                "remote_channel_id": remote_channel_id,
            },
        )
