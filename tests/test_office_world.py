"""The world over the office: the real clock, the real sun, the real weather - or why not.

The sun is computed (NOAA's solar position algorithm) from the real UTC time and the office's
coordinates; no service is asked and nothing is assumed. Its sunrise and sunset are checked here
against a table published by someone else: the U.S. Naval Observatory's rise/set tables for
Bucharest (aa.usno.navy.mil, "rstt/oneday", 44.4268 N 26.1025 E, read 2026-09-19), on both of
2026's daylight-saving days and the solstices.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from app.office.world import (
    LIVE_DATABASE,
    REFERENCE_DUSK_ELEVATION,
    ROOT,
    LiveOverrideRefused,
    WeatherKeeper,
    build_world_state,
    check_instants,
    is_live_studio,
    solar_position,
    world_clock,
)

BUCHAREST = ZoneInfo("Europe/Bucharest")
# The Owner's own database, named only by the path world.py holds; no test here opens anything.
LIVE_RELATIVE = LIVE_DATABASE.relative_to(ROOT).as_posix()
LIVE_URL = f"sqlite:///{LIVE_RELATIVE}"
LAT, LON = 44.4268, 26.1025


def settings(**overrides):
    base = {
        "office_latitude": LAT,
        "office_longitude": LON,
        "timezone": "Europe/Bucharest",
        "database_url": LIVE_URL,
        "office_world_rehearsal_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# USNO: (local date, UTC offset hours the table was asked in, rise, set, end of civil twilight)
USNO = [
    (date(2026, 3, 28), 2, "06:04", "18:38", "19:07"),  # the last day on EET
    (date(2026, 3, 29), 3, "07:03", "19:39", "20:08"),  # clocks go forward at 03:00
    (date(2026, 6, 21), 3, "05:31", "21:04", "21:41"),
    (date(2026, 9, 18), 3, "06:58", "19:21", "19:50"),
    (date(2026, 10, 24), 3, "07:42", "18:17", "18:47"),  # the last day on EEST
    (date(2026, 10, 25), 2, "06:43", "17:15", "17:45"),  # clocks go back at 04:00
    (date(2026, 12, 21), 2, "07:49", "16:39", "17:12"),
]


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def local_minutes(when: datetime) -> float:
    local = when.astimezone(BUCHAREST)
    return local.hour * 60 + local.minute + local.second / 60


@pytest.mark.parametrize(("day", "offset", "rise", "set_", "civil_end"), USNO)
def test_sunrise_and_sunset_match_the_published_table_within_two_minutes(
    day, offset, rise, set_, civil_end
):
    instants = check_instants(day, settings())
    # the table was asked in the zone's own offset of that day: zoneinfo must agree with it
    assert instants["sunrise"].astimezone(BUCHAREST).utcoffset() == timedelta(hours=offset)
    assert abs(local_minutes(instants["sunrise"]) - minutes(rise)) <= 2
    assert abs(local_minutes(instants["sunset"]) - minutes(set_)) <= 2
    assert abs(local_minutes(instants["evening_-6"]) - minutes(civil_end)) <= 2


def test_the_check_instants_of_the_owner_reference_evening():
    # 18 Sep 2026: -2.5 deg at 19:31 and -18 at 21:00, solar noon 13:10 (the critic's table)
    instants = check_instants(date(2026, 9, 18), settings())
    assert abs(local_minutes(instants["solar_noon"]) - minutes("13:10")) <= 1
    assert abs(local_minutes(instants["evening_-2.5"]) - minutes("19:31")) <= 1
    assert abs(local_minutes(instants["evening_-18"]) - minutes("21:00")) <= 1
    reference = solar_position(instants["evening_-2.5"], LAT, LON)
    assert reference.elevation_deg == pytest.approx(REFERENCE_DUSK_ELEVATION, abs=0.02)
    # the evening sun stands in the west: left of a viewer who looks north (D1)
    assert 265 < reference.azimuth_deg < 285


def test_the_sun_is_south_and_highest_at_solar_noon_and_east_in_the_morning():
    noon = check_instants(date(2026, 9, 18), settings())["solar_noon"]
    sun = solar_position(noon, LAT, LON)
    assert sun.elevation_deg == pytest.approx(47.4, abs=0.2)
    morning = solar_position(datetime(2026, 9, 18, 5, 0, tzinfo=UTC), LAT, LON)  # 08:00 local
    assert 90 < morning.azimuth_deg < 120 and morning.elevation_deg > 0
    night = solar_position(datetime(2026, 9, 18, 22, 0, tzinfo=UTC), LAT, LON)  # 01:00 local
    assert night.elevation_deg < -18


def test_a_naive_time_is_refused_rather_than_read_as_some_zone():
    with pytest.raises(ValueError):
        solar_position(datetime(2026, 9, 18, 12, 0), LAT, LON)


def test_the_wall_clock_follows_daylight_saving_both_ways():
    # 29 Mar 2026, 01:00 UTC: 02:59:59 EET is followed by 04:00:00 EEST
    before = build_world_state(datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC), settings(), None)
    after = build_world_state(datetime(2026, 3, 29, 1, 0, 0, tzinfo=UTC), settings(), None)
    assert (before.local_time.hour, before.local_time.minute) == (2, 59)
    assert (after.local_time.hour, after.local_time.minute) == (4, 0)
    assert after.seconds_of_day == 4 * 3600
    # 25 Oct 2026, 01:00 UTC: 03:59:59 EEST is followed by 03:00:00 EET
    before = build_world_state(datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC), settings(), None)
    after = build_world_state(datetime(2026, 10, 25, 1, 0, 0, tzinfo=UTC), settings(), None)
    assert (before.local_time.hour, before.local_time.minute) == (3, 59)
    assert (after.local_time.hour, after.local_time.minute) == (3, 0)
    assert after.seconds_of_day == 3 * 3600


OBSERVED = {
    "available": True,
    "condition": "rain",
    "intensity": 0.3,
    "weather_code": 61,
    "temperature_c": 17.2,
    "apparent_temperature_c": 16.1,
    "wind_kph": 11.2,
    "wind_gust_kph": 24.5,
    "wind_from_deg": 305.0,
    "cloud_cover": 88.0,
    "cloud_cover_low": 40.0,
    "precipitation_mm": 0.3,
    "rain_mm": 0.3,
    "showers_mm": 0.0,
    "snowfall_cm": 0.0,
    "snow_depth_m": 0.0,
    "visibility_m": 24140.0,
    "precip_last_3h_mm": 1.7,
    "is_day": False,
    "observed_at": "2026-09-18T19:30",
    "source": "api.example-weather.test",
}


def test_the_world_state_is_one_typed_value_with_the_real_weather():
    now = datetime(2026, 9, 18, 16, 31, tzinfo=UTC)
    world = build_world_state(now, settings(), OBSERVED)
    assert world.computed_at == now
    assert world.local_time.tzinfo is not None and world.local_time.hour == 19
    assert world.sun == solar_position(now, LAT, LON)
    assert world.weather is not None and world.weather_reason is None
    assert world.weather.rain_mm == 0.3 and world.weather.precip_last_3h_mm == 1.7
    assert world.weather.visibility_m == 24140.0
    assert world.rehearsal is False


def test_unavailable_weather_is_said_not_replaced():
    world = build_world_state(
        datetime(2026, 9, 18, 16, 31, tzinfo=UTC),
        settings(),
        {"available": False, "reason": "not_configured"},
    )
    assert world.weather is None and world.weather_reason == "not_configured"


def test_a_missing_field_stays_unknown_in_the_world_state():
    partial = {k: v for k, v in OBSERVED.items() if k not in ("rain_mm", "precip_last_3h_mm")}
    world = build_world_state(datetime(2026, 9, 18, 16, 31, tzinfo=UTC), settings(), partial)
    assert world.weather.rain_mm is None and world.weather.precip_last_3h_mm is None


def test_the_last_real_observation_is_kept_for_an_hour_and_marked_stale():
    keeper = WeatherKeeper()
    assert keeper.observe(OBSERVED, 0.0) == (OBSERVED, None, 0.0)
    down = {"available": False, "reason": "unreachable"}
    observation, reason, age = keeper.observe(down, 1800.0)
    assert observation == OBSERVED and reason == "stale" and age == 1800.0
    observation, reason, _ = keeper.observe(down, 3601.0)
    assert observation == {"available": False, "reason": "unreachable"} and reason == "unreachable"


def test_the_weather_is_never_stale_before_a_first_observation():
    keeper = WeatherKeeper()
    observation, reason, _ = keeper.observe({"available": False, "reason": "unreachable"}, 10.0)
    assert observation["available"] is False and reason == "unreachable"


# ---------------------------------------------------------------- the verification override
def test_the_owners_studio_is_live_and_a_copy_is_not(tmp_path):
    assert is_live_studio(settings()) is True
    assert is_live_studio(settings(database_url=f"sqlite:///./{LIVE_RELATIVE}")) is True
    assert is_live_studio(settings(database_url=f"sqlite:///{LIVE_DATABASE.as_posix()}")) is True
    copy = (tmp_path / LIVE_DATABASE.name).as_posix()
    assert is_live_studio(settings(database_url=f"sqlite:///{copy}")) is False


def test_the_real_clock_is_the_default():
    clock = world_clock(settings())
    before = datetime.now(UTC)
    now = clock()
    assert before <= now <= datetime.now(UTC) + timedelta(seconds=1)


def test_a_rehearsal_time_is_refused_on_the_live_studio():
    at = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
    with pytest.raises(LiveOverrideRefused):
        world_clock(settings(office_world_rehearsal_at=at))


def test_a_rehearsal_time_runs_on_from_its_start_on_a_copy(tmp_path):
    at = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
    ticks = [100.0]
    clock = world_clock(
        settings(
            office_world_rehearsal_at=at, database_url=f"sqlite:///{tmp_path.as_posix()}/copy.db"
        ),
        monotonic=lambda: ticks[0],
    )
    assert clock() == at
    ticks[0] += 90.0
    assert clock() == at + timedelta(seconds=90)
