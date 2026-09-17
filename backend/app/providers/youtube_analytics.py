"""Phase 7 YouTube Analytics & Reporting API adapter.

Uses the YouTube Analytics REST API at
https://youtubeanalytics.googleapis.com/v2/reports, which requires Google OAuth credentials
carrying the https://www.googleapis.com/auth/yt-analytics.readonly scope.

Every number this adapter returns was reported by YouTube for the window that was asked for.
Nothing is estimated: if YouTube does not return impressions for a query, impressions and CTR
come back as zero and ``raw["impressions_reported"]`` is false, rather than being back-computed
from views. The adapter raises when it is not configured or when the API does not answer; it
never falls back to a plausible-looking figure.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
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
        channel_id: str | None = None,
    ) -> None:
        # Explicit credentials are one account's and are taken whole. The constructor used
        # to fill every argument left None from STUDIO_YOUTUBE_*, so an adapter built from a
        # channel's bound connection still carried the environment's access token — which
        # `_refresh_access_token` prefers — and reported another account's numbers as this
        # channel's. The environment is read only when nothing at all was given: the
        # pre-Settings path, where the environment is the account.
        explicit = (client_id, client_secret, refresh_token, access_token)
        if any(value is not None for value in explicit):
            self.client_id = client_id
            self.client_secret = client_secret
            self.refresh_token = refresh_token
            self.access_token = access_token
        else:
            self.client_id = os.environ.get("STUDIO_YOUTUBE_CLIENT_ID")
            self.client_secret = os.environ.get("STUDIO_YOUTUBE_CLIENT_SECRET")
            self.refresh_token = os.environ.get("STUDIO_YOUTUBE_REFRESH_TOKEN")
            self.access_token = os.environ.get("STUDIO_YOUTUBE_ACCESS_TOKEN")
        #: Whose numbers these are: the bound connection's remote channel id, so a reader can
        #: check the account against the slot's binding. None on the environment path.
        self.channel_id = channel_id

    @classmethod
    def from_verified_settings(
        cls, engine: object, vault: object, connection_id: str | None = None
    ) -> YouTubeAnalyticsProvider | None:
        """Build the adapter from a *verified* YouTube connection, or return None.

        A connection the Owner saved but never checked does not count: `SAVED` means the
        credentials were typed in, not that YouTube accepted them. Environment credentials are
        honoured as the pre-Settings path.
        """
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.orm import Session  # noqa: PLC0415

        from app.youtube.models import YouTubeConnection  # noqa: PLC0415

        with Session(engine) as session:  # type: ignore[arg-type]
            query = select(YouTubeConnection).where(YouTubeConnection.status == "CONNECTED")
            # A channel slot that names its account removes the ambiguity below: these are that
            # account's numbers because that is the account this channel publishes through.
            if connection_id:
                query = query.where(YouTubeConnection.id == connection_id)
            connected = session.scalars(query.order_by(YouTubeConnection.created_at)).all()
            # Exactly one, or none: with several channels connected there is no way to tell
            # whose statistics were asked for, and answering with the first row would attribute
            # one channel's numbers to another.
            if len(connected) == 1:
                row = connected[0]
                secrets = vault.decrypt(row.encrypted_secrets)  # type: ignore[attr-defined]
                return cls(
                    client_id=row.client_id,
                    client_secret=secrets.get("client_secret"),
                    refresh_token=secrets.get("refresh_token"),
                )

        candidate = cls()
        return candidate if candidate.is_configured() else None

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

    @staticmethod
    def _date_range(window: str) -> tuple[str, str]:
        """Translate a reporting window into the date range YouTube is actually asked for.

        The window used to be ignored entirely — every query returned an all-time report that
        was then stored under a "24h" or "7d" label. A snapshot must cover the period it claims.
        """
        today = date.today()
        spans = {"1h": 1, "24h": 1, "7d": 7, "28d": 28}
        if window == "LIFETIME":
            # YouTube launched in 2005; anything earlier is outside the platform's history.
            return "2005-01-01", today.isoformat()
        days = spans.get(window)
        if days is None:
            raise ValueError(f"Unsupported analytics window {window!r}")
        return (today - timedelta(days=days)).isoformat(), today.isoformat()

    def _report(self, params: dict[str, str], token: str) -> dict:
        url = f"https://youtubeanalytics.googleapis.com/v2/reports?{urlencode(params)}"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(req, timeout=20) as resp:
                body = resp.read(4_000_001)
                if len(body) > 4_000_000:
                    raise RuntimeError("YouTube Analytics response exceeds the size limit")
                return json.loads(body.decode("utf-8"))
        except (HTTPError, URLError) as exc:
            logger.error("youtube_analytics_api_error: %s", exc)
            raise RuntimeError(f"YouTube Analytics API request failed: {exc}") from exc

    async def fetch_video_metrics(
        self, remote_video_id: str, window: str = "LIFETIME"
    ) -> VideoMetrics:
        if not self.is_configured():
            raise RuntimeError(
                "YouTube Analytics API credentials not configured (STUDIO_YOUTUBE_CLIENT_ID, etc.)"
            )
        start_date, end_date = self._date_range(window)
        token = self._refresh_access_token()

        base_metrics = [
            "views",
            "estimatedMinutesWatched",
            "averageViewPercentage",
            "likes",
            "comments",
            "shares",
            "subscribersGained",
            "subscribersLost",
        ]
        impression_metrics = ["impressions", "impressionClickThroughRate"]
        params = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": ",".join(base_metrics + impression_metrics),
            "filters": f"video=={remote_video_id}",
        }

        impressions_reported = True
        try:
            data = self._report(params, token)
        except RuntimeError:
            # Impression metrics are not available for every account or query shape. Retry with
            # the core metrics and report no impressions rather than inventing them.
            impressions_reported = False
            params["metrics"] = ",".join(base_metrics)
            data = self._report(params, token)

        columns = [c.get("name") for c in data.get("columnHeaders", [])]
        rows = data.get("rows", [])
        values: dict[str, float] = {}
        if rows:
            values = {
                name: float(value)
                for name, value in zip(columns, rows[0], strict=False)
                if isinstance(value, (int, float))
            }

        raw = dict(data)
        raw["requested_window"] = window
        raw["start_date"] = start_date
        raw["end_date"] = end_date
        raw["impressions_reported"] = impressions_reported and bool(rows)
        raw["rows_returned"] = len(rows)

        return VideoMetrics(
            remote_video_id=remote_video_id,
            views=int(values.get("views", 0)),
            watch_time_seconds=values.get("estimatedMinutesWatched", 0.0) * 60.0,
            average_view_percentage=values.get("averageViewPercentage", 0.0),
            # Never back-computed from views: zero means YouTube reported nothing.
            impressions=int(values.get("impressions", 0)),
            ctr_percentage=values.get("impressionClickThroughRate", 0.0),
            likes=int(values.get("likes", 0)),
            comments=int(values.get("comments", 0)),
            shares=int(values.get("shares", 0)),
            subscribers_gained=int(values.get("subscribersGained", 0)),
            subscribers_lost=int(values.get("subscribersLost", 0)),
            window=window,
            raw=raw,
        )

    async def fetch_channel_metrics(
        self, remote_channel_id: str, window: str = "LIFETIME"
    ) -> ChannelMetrics:
        if not self.is_configured():
            raise RuntimeError("YouTube Analytics API credentials not configured")
        start_date, end_date = self._date_range(window)
        token = self._refresh_access_token()
        data = self._report(
            {
                "ids": "channel==MINE",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": "views,estimatedMinutesWatched,subscribersGained,subscribersLost",
            },
            token,
        )
        columns = [c.get("name") for c in data.get("columnHeaders", [])]
        rows = data.get("rows", [])
        values: dict[str, float] = {}
        if rows:
            values = {
                name: float(value)
                for name, value in zip(columns, rows[0], strict=False)
                if isinstance(value, (int, float))
            }

        raw = dict(data)
        raw["requested_window"] = window
        raw["start_date"] = start_date
        raw["end_date"] = end_date
        # A net change over the window is not a subscriber total, and this report does not
        # carry one; the field says what it is.
        raw["subscribers_is_net_change_over_window"] = True
        raw["total_videos_reported"] = False

        return ChannelMetrics(
            remote_channel_id=remote_channel_id,
            total_views=int(values.get("views", 0)),
            total_watch_time_seconds=values.get("estimatedMinutesWatched", 0.0) * 60.0,
            total_subscribers=int(
                values.get("subscribersGained", 0.0) - values.get("subscribersLost", 0.0)
            ),
            # This report returns metrics, not a video inventory; do not guess a count.
            total_videos=0,
            window=window,
            raw=raw,
        )
