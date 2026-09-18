"""The live weather over the office, as the scene draws it.

The office page may only talk to its own origin (its Content-Security-Policy allows
``connect-src 'self'``), so the backend reads the current observation and the page asks the
backend. Which service to ask is configuration (``STUDIO_OFFICE_WEATHER_HOST``); with none
configured, or when the service cannot be reached, the answer says the weather is unavailable
and the scene draws no weather at all rather than an invented one.

The service is expected to speak the Open-Meteo forecast API (``/v1/forecast`` with a
``current`` block and WMO weather codes). Open-Meteo serves every hourly variable in the
``current`` block too (its own documentation), so the scene's rain, snow, wind and visibility
come from the same 15-minute observation; the rain of the past three hours comes from the
``hourly`` block, and only from hours that have already happened.

Never invented: a variable the service does not return is None, never zero. Zero rain is an
observation; a missing rain value is not one.

Licence note for the Owner (the adversary's review, 2026-09-18): the free api.open-meteo.com tier
is licensed for non-commercial use. The host is configuration, so a self-hosted Open-Meteo server
or another compatible host changes nothing here.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from app.providers.media_http import MediaProviderError, request

logger = logging.getLogger("studio.office")

#: An observation is fresh for ten minutes; a failure is retried after two.
CACHE_SECONDS = 600
FAILURE_SECONDS = 120

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "at": 0.0, "value": None, "ttl": 0.0}

#: WMO weather interpretation codes -> (scene condition, intensity 0..1).
WMO: dict[int, tuple[str, float]] = {
    0: ("clear", 0.0),
    1: ("partly_cloudy", 0.3),
    2: ("partly_cloudy", 0.7),
    3: ("cloudy", 0.8),
    45: ("fog", 0.6),
    48: ("fog", 0.9),
    51: ("drizzle", 0.3),
    53: ("drizzle", 0.6),
    55: ("drizzle", 0.9),
    56: ("drizzle", 0.5),
    57: ("drizzle", 0.9),
    61: ("rain", 0.3),
    63: ("rain", 0.6),
    65: ("rain", 1.0),
    66: ("rain", 0.5),
    67: ("rain", 0.9),
    71: ("snow", 0.3),
    73: ("snow", 0.6),
    75: ("snow", 1.0),
    77: ("snow", 0.4),
    80: ("rain", 0.4),
    81: ("rain", 0.7),
    82: ("rain", 1.0),
    85: ("snow", 0.5),
    86: ("snow", 0.9),
    95: ("storm", 0.8),
    96: ("storm", 0.9),
    99: ("storm", 1.0),
}


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def parse_observation(data: Any, source: str) -> dict[str, Any]:
    """Normalise a forecast response's ``current`` block, or raise ValueError."""
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        raise ValueError("no current observation")
    current = data["current"]
    code = current.get("weather_code")
    if not isinstance(code, int) or code not in WMO:
        raise ValueError("unknown weather code")
    condition, intensity = WMO[code]

    def number(key: str) -> float | None:
        value = current.get(key)
        return float(value) if isinstance(value, int | float) else None

    is_day = current.get("is_day")
    observed_at = current.get("time") if isinstance(current.get("time"), str) else None
    return {
        "available": True,
        "condition": condition,
        "intensity": intensity,
        "weather_code": code,
        "temperature_c": number("temperature_2m"),
        "wind_kph": number("wind_speed_10m"),
        "cloud_cover": number("cloud_cover"),
        "precipitation_mm": number("precipitation"),
        "is_day": bool(is_day) if isinstance(is_day, int) else None,
        "observed_at": observed_at,
        "apparent_temperature_c": number("apparent_temperature"),
        # the 15-minute block's sums, in the service's own units (mm, snowfall in cm)
        "rain_mm": number("rain"),
        "showers_mm": number("showers"),
        "snowfall_cm": number("snowfall"),
        "snow_depth_m": number("snow_depth"),
        "wind_from_deg": number("wind_direction_10m"),
        "wind_gust_kph": number("wind_gusts_10m"),
        "visibility_m": number("visibility"),
        "cloud_cover_low": number("cloud_cover_low"),
        "precip_last_3h_mm": precipitation_last_hours(data.get("hourly"), observed_at, 3),
        "source": source,
    }


def precipitation_last_hours(hourly: Any, observed_at: str | None, hours: int) -> float | None:
    """The precipitation of the last ``hours`` hourly values at or before the observation.

    Each hourly value is the sum of the hour before its time stamp. Hours after the observation
    are the service's forecast and are never counted as rain that fell. With fewer hours than
    asked, or a gap among them, the sum is unknown (None): a missing hour is not a dry one.
    """
    if not isinstance(hourly, dict) or observed_at is None:
        return None
    times, values = hourly.get("time"), hourly.get("precipitation")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        return None
    # ISO local times of one zone compare as strings, as the service writes them
    past = [
        v for t, v in zip(times, values, strict=True) if isinstance(t, str) and t <= observed_at
    ]
    if len(past) < hours:
        return None
    window = past[-hours:]
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in window):
        return None
    return float(sum(window))


def fetch_observation(host: str, latitude: float, longitude: float, timezone: str) -> Any:
    query = urlencode(
        {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "current": ",".join(
                (
                    "temperature_2m",
                    "weather_code",
                    "is_day",
                    "wind_speed_10m",
                    "cloud_cover",
                    "precipitation",
                    "apparent_temperature",
                    "rain",
                    "showers",
                    "snowfall",
                    "snow_depth",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "visibility",
                    "cloud_cover_low",
                )
            ),
            # the hours before now, for the road: wet from rain that really fell. One hour of
            # forecast comes with it (the service counts the current hour as forecast); it is
            # dropped by precipitation_last_hours, never read as rain that fell.
            "hourly": "precipitation",
            "past_hours": 3,
            "forecast_hours": 1,
            "wind_speed_unit": "kmh",
            "timezone": timezone,
        }
    )
    data, _, _ = request(
        host,
        "GET",
        f"/v1/forecast?{query}",
        {"Accept": "application/json", "User-Agent": "AMN-AI-studio-office"},
        timeout=10,
    )
    return data


def current_weather(
    settings: Any,
    *,
    clock: Callable[[], float] = time.monotonic,
    fetch: Callable[[str, float, float, str], Any] = fetch_observation,
) -> dict[str, Any]:
    """The current weather for the office, cached; never raises."""
    host = getattr(settings, "office_weather_host", None)
    if not host:
        return unavailable("not_configured")
    latitude = float(settings.office_latitude)
    longitude = float(settings.office_longitude)
    key = (host, round(latitude, 4), round(longitude, 4))
    now = clock()
    with _lock:
        if (
            _cache["key"] == key
            and _cache["value"] is not None
            and now - _cache["at"] < _cache["ttl"]
        ):
            return dict(_cache["value"])
    try:
        value = parse_observation(fetch(host, latitude, longitude, settings.timezone), host)
        ttl = CACHE_SECONDS
    except (MediaProviderError, ValueError, TypeError) as exc:
        logger.info("office_weather_unavailable", extra={"error": type(exc).__name__})
        value = unavailable("unreachable")
        ttl = FAILURE_SECONDS
    with _lock:
        _cache.update({"key": key, "at": now, "value": value, "ttl": ttl})
    return dict(value)


def reset_cache() -> None:
    with _lock:
        _cache.update({"key": None, "at": 0.0, "value": None, "ttl": 0.0})
