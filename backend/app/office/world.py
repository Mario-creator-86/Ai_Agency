"""The real world over the office: the wall clock, the sun and the weather, as one value.

The Owner's rule (2026-09-18): the sky and the light over the headquarters are the real ones
outside - time, sun, temperature, rain, snow, wind. So the scene is told three things and nothing
else: the time on the office's wall clock (zoneinfo, so daylight saving is the law's, not a rule
of thumb), where the sun really stands (computed, below), and the weather the configured service
really reported (``weather.py``), or why there is none.

The sun comes from NOAA's solar position algorithm (the one of the NOAA Solar Calculator and of
the web page's ``frontend/src/hq_time.js``), from the real UTC time and the office's coordinates:
no service is asked, so it cannot fail and cannot be stale. Elevations are geometric (no
refraction); sunrise and sunset are the moments the centre stands at -0.833 deg, the published
tables' convention, and a test holds them to the U.S. Naval Observatory's table within 2 min.

A verification override of the time exists for tests and rehearsals only. It is refused on the
Owner's live studio: the scene he watches never shows an hour that is not now.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
LIVE_DATABASE = ROOT / "data" / "studio.db"

#: The sun elevation at which the Owner's reference picture is lit (hq_time.js
#: REFERENCE_DUSK_ELEVATION, compose_sky_backdrop.py ELEVATION): the approved dusk.
REFERENCE_DUSK_ELEVATION = -2.5
#: Sunrise and sunset: the upper limb on a refracted horizon (0.567 deg of refraction plus the
#: sun's 0.267 deg semi-diameter), the convention of every published table.
HORIZON_ELEVATION = -0.833
#: A kept observation older than this is no longer the weather outside (plan, "When the backend
#: has no weather": the last real observation for up to 60 min, marked stale, then none).
STALE_WEATHER_S = 3600.0


@dataclass(frozen=True)
class Sun:
    elevation_deg: float  # geometric, above the horizon
    azimuth_deg: float  # true north, clockwise, 0..360


@dataclass(frozen=True)
class Weather:
    """One real observation. Every field the service did not return is None, never zero."""

    observed_at: str | None
    condition: str | None
    weather_code: int | None
    temperature_c: float | None
    apparent_temperature_c: float | None
    cloud_cover: float | None
    cloud_cover_low: float | None
    precipitation_mm: float | None
    rain_mm: float | None
    showers_mm: float | None
    snowfall_cm: float | None
    snow_depth_m: float | None
    visibility_m: float | None
    wind_kph: float | None
    wind_gust_kph: float | None
    wind_from_deg: float | None
    precip_last_3h_mm: float | None
    is_day: bool | None

    @classmethod
    def from_observation(cls, observation: Mapping[str, Any]) -> Weather:
        def number(key: str) -> float | None:
            value = observation.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            return float(value)

        code = observation.get("weather_code")
        condition = observation.get("condition")
        is_day = observation.get("is_day")
        observed_at = observation.get("observed_at")
        return cls(
            observed_at=observed_at if isinstance(observed_at, str) else None,
            condition=condition if isinstance(condition, str) else None,
            weather_code=code if isinstance(code, int) and not isinstance(code, bool) else None,
            temperature_c=number("temperature_c"),
            apparent_temperature_c=number("apparent_temperature_c"),
            cloud_cover=number("cloud_cover"),
            cloud_cover_low=number("cloud_cover_low"),
            precipitation_mm=number("precipitation_mm"),
            rain_mm=number("rain_mm"),
            showers_mm=number("showers_mm"),
            snowfall_cm=number("snowfall_cm"),
            snow_depth_m=number("snow_depth_m"),
            visibility_m=number("visibility_m"),
            wind_kph=number("wind_kph"),
            wind_gust_kph=number("wind_gust_kph"),
            wind_from_deg=number("wind_from_deg"),
            precip_last_3h_mm=number("precip_last_3h_mm"),
            is_day=is_day if isinstance(is_day, bool) else None,
        )


@dataclass(frozen=True)
class WorldState:
    """What the scene is told: the instant, the office's wall clock, the sun, the weather."""

    computed_at: datetime  # UTC
    local_time: datetime  # the office's zone
    seconds_of_day: float  # on the office's wall clock
    sun: Sun
    weather: Weather | None
    #: None with a fresh observation; "stale" for a kept one; otherwise why there is none
    #: ("not_configured", "unreachable", "rehearsal")
    weather_reason: str | None
    weather_age_s: float | None
    rehearsal: bool


def _julian_century(when: datetime) -> float:
    julian_day = when.timestamp() / 86400.0 + 2440587.5
    return (julian_day - 2451545.0) / 36525.0


def solar_position(when: datetime, latitude: float, longitude: float) -> Sun:
    """NOAA's solar position for an aware instant (the NOAA Solar Calculator's equations)."""
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("an aware time is required: a naive one names no instant")
    utc = when.astimezone(UTC)
    t = _julian_century(utc)
    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    m = math.radians(mean_anom)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (
        math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m) * 0.000289
    )
    omega = math.radians(125.04 - 1934.136 * t)
    apparent_long = mean_long + centre - 0.00569 - 0.00478 * math.sin(omega)
    mean_obliq = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliq = math.radians(mean_obliq + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliq) * math.sin(math.radians(apparent_long)))
    y = math.tan(obliq / 2) ** 2
    l0 = math.radians(mean_long)
    equation_of_time = 4 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * ecc * math.sin(m)
        + 4 * ecc * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * ecc * ecc * math.sin(2 * m)
    )
    minutes = utc.hour * 60 + utc.minute + (utc.second + utc.microsecond / 1e6) / 60
    true_solar = (minutes + equation_of_time + 4 * longitude) % 1440
    hour_angle = math.radians(true_solar / 4 - 180)
    lat = math.radians(latitude)
    elevation = math.asin(
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    azimuth = math.degrees(
        math.atan2(
            math.sin(hour_angle),
            math.cos(hour_angle) * math.sin(lat) - math.tan(declination) * math.cos(lat),
        )
    )
    return Sun(elevation_deg=math.degrees(elevation), azimuth_deg=(azimuth + 180.0) % 360.0)


def _zone(settings: Any) -> ZoneInfo:
    return ZoneInfo(str(getattr(settings, "timezone", "Europe/Bucharest")))


def build_world_state(
    now: datetime,
    settings: Any,
    observation: Mapping[str, Any] | None,
    *,
    weather_reason: str | None = None,
    weather_age_s: float | None = None,
    rehearsal: bool = False,
) -> WorldState:
    """The world at ``now`` (aware) with the weather ``observation`` (``weather.py``'s shape)."""
    if now.tzinfo is None:
        raise ValueError("an aware time is required")
    utc = now.astimezone(UTC)
    local = utc.astimezone(_zone(settings))
    sun = solar_position(utc, float(settings.office_latitude), float(settings.office_longitude))
    weather: Weather | None = None
    reason = weather_reason
    if observation is not None and observation.get("available") is True:
        weather = Weather.from_observation(observation)
    else:
        weather_age_s = None
        if reason is None or reason == "stale":
            given = observation.get("reason") if observation is not None else None
            reason = given if isinstance(given, str) else "unavailable"
    return WorldState(
        computed_at=utc,
        local_time=local,
        seconds_of_day=local.hour * 3600
        + local.minute * 60
        + local.second
        + local.microsecond / 1e6,
        sun=sun,
        weather=weather,
        weather_reason=reason,
        weather_age_s=weather_age_s,
        rehearsal=rehearsal,
    )


class WeatherKeeper:
    """Keeps the last real observation through an outage of up to an hour, marked stale."""

    def __init__(self) -> None:
        self._last: Mapping[str, Any] | None = None
        self._at = 0.0

    def observe(
        self, observation: Mapping[str, Any], now: float
    ) -> tuple[Mapping[str, Any], str | None, float]:
        """(observation to show, reason or None, its age in seconds)."""
        if observation.get("available") is True:
            self._last, self._at = observation, now
            return observation, None, 0.0
        if self._last is not None and now - self._at <= STALE_WEATHER_S:
            return self._last, "stale", now - self._at
        reason = observation.get("reason")
        return observation, reason if isinstance(reason, str) else "unavailable", 0.0


# ---------------------------------------------------------------- the day's check instants
def _crossing(
    start: datetime, end: datetime, target: float, latitude: float, longitude: float
) -> datetime | None:
    """The first instant in [start, end] where the elevation crosses ``target``, to a second."""
    step = timedelta(minutes=5)
    t = start
    before = solar_position(t, latitude, longitude).elevation_deg - target
    while t < end:
        nxt = min(t + step, end)
        after = solar_position(nxt, latitude, longitude).elevation_deg - target
        if before == 0:
            return t
        if (before < 0) != (after < 0):
            lo, hi = t, nxt
            while hi - lo > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if (solar_position(mid, latitude, longitude).elevation_deg - target < 0) == (
                    before < 0
                ):
                    lo = mid
                else:
                    hi = mid
            return lo + (hi - lo) / 2
        t, before = nxt, after
    return None


def check_instants(day: date, settings: Any) -> dict[str, datetime]:
    """The moments of ``day`` (the office's local date) an on-screen check is made at: sunrise,
    sunset, solar noon, and the mornings and evenings at +6, -2.5 (the reference), -6, -12 and
    -18 deg. Printed for the day of the check, never hard-coded from another day."""
    zone = _zone(settings)
    lat, lon = float(settings.office_latitude), float(settings.office_longitude)
    start = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)
    end = (datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(days=1)).astimezone(UTC)
    # solar noon: the highest sun, found to a second by golden-section search around the minute
    best = max(
        (start + timedelta(minutes=i) for i in range(int((end - start).total_seconds() // 60))),
        key=lambda t: solar_position(t, lat, lon).elevation_deg,
    )
    lo, hi = best - timedelta(minutes=1), best + timedelta(minutes=1)
    while hi - lo > timedelta(seconds=1):
        a, b = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if solar_position(a, lat, lon).elevation_deg < solar_position(b, lat, lon).elevation_deg:
            lo = a
        else:
            hi = b
    noon = lo + (hi - lo) / 2
    out: dict[str, datetime] = {"solar_noon": noon}
    for name, target in (("sunrise", HORIZON_ELEVATION),):
        found = _crossing(start, noon, target, lat, lon)
        if found is not None:
            out[name] = found
    found = _crossing(noon, end, HORIZON_ELEVATION, lat, lon)
    if found is not None:
        out["sunset"] = found
    for target in (6.0, REFERENCE_DUSK_ELEVATION, -6.0, -12.0, -18.0):
        label = f"{target:+g}" if target > 0 else f"{target:g}"
        morning = _crossing(start, noon, target, lat, lon)
        evening = _crossing(noon, end, target, lat, lon)
        if morning is not None:
            out[f"morning_{label}"] = morning
        if evening is not None:
            out[f"evening_{label}"] = evening
    return out


# ---------------------------------------------------------------- the clock and its override
class LiveOverrideRefused(RuntimeError):
    """A rehearsal time was configured on the Owner's live studio."""


def is_live_studio(settings: Any) -> bool:
    """Whether this backend is the Owner's own studio (``data/studio.db``), by its path alone.

    The database is never opened here. Anything that is not a SQLite file somewhere else counts
    as live: a rehearsal proves itself by running on a copy (tests/test_rehearsal_on_a_copy.py).
    """
    url = str(getattr(settings, "database_url", "") or "")
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return True
    raw = url[len(prefix) :].split("?", 1)[0]
    if raw in ("", ":memory:"):
        return False
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return path.resolve() == LIVE_DATABASE.resolve()
    except OSError:
        return True


def world_clock(
    settings: Any, *, monotonic: Callable[[], float] = time.monotonic
) -> Callable[[], datetime]:
    """The instant the scene is shown: now, or - on a copy only - a rehearsal time running on.

    ``office_world_rehearsal_at`` (STUDIO_OFFICE_WORLD_REHEARSAL_AT) is for rehearsals on a copy;
    on the live studio it raises LiveOverrideRefused and the caller keeps the real clock.
    """
    at = getattr(settings, "office_world_rehearsal_at", None)
    if at is None:
        return lambda: datetime.now(UTC)
    if is_live_studio(settings):
        raise LiveOverrideRefused("a rehearsal time is refused on the live studio")
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("a rehearsal time must be an aware datetime")
    start = monotonic()
    anchor = at.astimezone(UTC)
    return lambda: anchor + timedelta(seconds=monotonic() - start)


def main() -> None:  # pragma: no cover - a print for the Owner's check day
    """Prints the check instants of today (or of the date given as YYYY-MM-DD)."""
    import sys

    from app.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:  # the Windows console is cp1252; the labels are Romanian
        reconfigure(encoding="utf-8")
    day = (
        date.fromisoformat(sys.argv[1])
        if len(sys.argv) > 1
        else datetime.now(_zone(settings)).date()
    )
    lat, lon = float(settings.office_latitude), float(settings.office_longitude)
    for name, when in sorted(check_instants(day, settings).items(), key=lambda kv: kv[1]):
        sun = solar_position(when, lat, lon)
        local = when.astimezone(_zone(settings)).strftime("%H:%M:%S")
        print(
            f"{name:14} {local}  elevație {sun.elevation_deg:6.2f}°  azimut {sun.azimuth_deg:6.1f}°"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
