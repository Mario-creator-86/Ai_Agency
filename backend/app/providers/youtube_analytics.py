"""Phase 7 YouTube Analytics & Reporting API adapter.

Uses YouTube Analytics REST API:
  https://youtubeanalytics.googleapis.com/v2/reports
Requires valid Google OAuth credentials with https://www.googleapis.com/auth/yt-analytics.readonly scope.
Never fabricates fake numbers; reports status or raises when not configured.
"""

from __future__ import annotations

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.providers.analytics_base import AnalyticsProvider, ChannelMetrics, VideoMetrics

logger = logging.getLogger("studio.analytics.youtube")


class YouTubeAnalyticsProvider(AnalyticsProvider):
    PROVIDER_NAME = "YOUTUBE_ANALYTICS"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self.client_id = client_id or os.environ.get("STUDIO_YOUTUBE_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("STUDIO_YOUTUBE_CLIENT_SECRET")
        self.refresh_token = refresh_token or os.environ.get("STUDIO_YOUTUBE_REFRESH_TOKEN")
        self.access_token = access_token or os.environ.get("STUDIO_YOUTUBE_ACCESS_TOKEN")

    def is_configured(self) -> bool:
        return bool(
            self.access_token or (self.client_id and self.client_secret and self.refresh_token)
        )

    def _refresh_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise RuntimeError("YouTube Analytics credentials not configured in environment")

        token_url = "https://oauth2.googleapis.com/token"
        payload = urlencode(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        req = Request(
            token_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.access_token = data["access_token"]
            return self.access_token

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        if not self.is_configured():
            raise RuntimeError(
                "YouTube Analytics API credentials not configured (STUDIO_YOUTUBE_CLIENT_ID, etc.)"
            )

        token = self._refresh_access_token()
        params = {
            "ids": "channel==MINE",
            "startDate": "2024-01-01",
            "endDate": "2026-12-31",
            "metrics": "views,estimatedMinutesWatched,averageViewPercentage,annotationClickThroughRate,likes,comments,shares,subscribersGained,subscribersLost",
            "filters": f"video=={remote_video_id}",
        }
        url = f"https://youtubeanalytics.googleapis.com/v2/reports?{urlencode(params)}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                rows = data.get("rows", [])
                if not rows:
                    return VideoMetrics(
                        remote_video_id=remote_video_id,
                        views=0,
                        watch_time_seconds=0.0,
                        average_view_percentage=0.0,
                        impressions=0,
                        ctr_percentage=0.0,
                        likes=0,
                        comments=0,
                        shares=0,
                        subscribers_gained=0,
                        subscribers_lost=0,
                        window=window,
                        raw=data,
                    )
                row = rows[0]
                views = int(row[0])
                watch_time_sec = float(row[1]) * 60.0
                retention = float(row[2])
                ctr = float(row[3]) if len(row) > 3 else 0.0
                likes = int(row[4]) if len(row) > 4 else 0
                comments = int(row[5]) if len(row) > 5 else 0
                shares = int(row[6]) if len(row) > 6 else 0
                subs_gained = int(row[7]) if len(row) > 7 else 0
                subs_lost = int(row[8]) if len(row) > 8 else 0
                impressions = int(views / max(0.01, ctr / 100.0)) if ctr > 0 else views * 10
                return VideoMetrics(
                    remote_video_id=remote_video_id,
                    views=views,
                    watch_time_seconds=watch_time_sec,
                    average_view_percentage=retention,
                    impressions=impressions,
                    ctr_percentage=ctr,
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    subscribers_gained=subs_gained,
                    subscribers_lost=subs_lost,
                    window=window,
                    raw=data,
                )
        except (HTTPError, URLError) as exc:
            logger.error("youtube_analytics_api_error: %s", exc)
            raise RuntimeError(f"YouTube Analytics API request failed: {exc}") from exc

    async def fetch_channel_metrics(
        self, remote_channel_id: str, window: str = "LIFETIME"
    ) -> ChannelMetrics:
        if not self.is_configured():
            raise RuntimeError("YouTube Analytics API credentials not configured")
        token = self._refresh_access_token()
        params = {
            "ids": "channel==MINE",
            "startDate": "2024-01-01",
            "endDate": "2026-12-31",
            "metrics": "views,estimatedMinutesWatched,subscribersGained",
        }
        url = f"https://youtubeanalytics.googleapis.com/v2/reports?{urlencode(params)}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            rows = data.get("rows", [])
            views = int(rows[0][0]) if rows else 0
            watch_sec = float(rows[0][1]) * 60.0 if rows else 0.0
            subs = int(rows[0][2]) if rows else 0
            return ChannelMetrics(
                remote_channel_id=remote_channel_id,
                total_views=views,
                total_watch_time_seconds=watch_sec,
                total_subscribers=subs,
                total_videos=len(rows),
                window=window,
                raw=data,
            )
