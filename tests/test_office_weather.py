"""The office scene's live weather: read by the backend, never invented."""

from types import SimpleNamespace

import pytest
from app.office.weather import WMO, current_weather, observation_utc, parse_observation, reset_cache
from app.providers.media_http import MediaProviderError


@pytest.fixture(autouse=True)
def fresh_cache():
    reset_cache()
    yield
    reset_cache()


def settings(host="api.example-weather.test"):
    return SimpleNamespace(
        office_weather_host=host,
        office_latitude=44.4268,
        office_longitude=26.1025,
        timezone="Europe/Bucharest",
    )


OBSERVATION = {
    "current": {
        "time": "2026-09-13T18:15",
        "temperature_2m": 21.4,
        "weather_code": 63,
        "is_day": 1,
        "wind_speed_10m": 14.0,
        "cloud_cover": 96,
        "precipitation": 1.2,
    }
}


@pytest.mark.parametrize(
    ("stamp", "offset", "expected"),
    [
        ("2026-10-08T15:15", 10800, "2026-10-08T12:15:00+00:00"),
        ("2026-12-08T15:15", 7200, "2026-12-08T13:15:00+00:00"),
        ("2026-10-08T00:15", 10800, "2026-10-07T21:15:00+00:00"),
        ("2026-10-08T15:15+03:00", None, "2026-10-08T12:15:00+00:00"),
        ("2026-10-08T15:15Z", None, "2026-10-08T15:15:00+00:00"),
        ("2026-10-08T15:15", None, None),
        ("2026-10-08T15:15", True, None),
        ("2026-10-08T15:15", 999999, None),
        ("invalid", 10800, None),
        (None, 10800, None),
    ],
)
def test_observation_timestamp_is_unambiguous(stamp, offset, expected):
    assert observation_utc(stamp, offset) == expected


def test_parser_retains_local_time_and_exposes_utc_age():
    result = parse_observation({**OBSERVATION, "utc_offset_seconds": 10800}, "test")
    assert result["observed_at"] == "2026-09-13T18:15"
    assert result["observed_at_utc"] == "2026-09-13T15:15:00+00:00"


def test_timezone_changes_do_not_reuse_other_zones_cached_observation():
    calls = []
    config = settings()

    def fetch(*args):
        calls.append(args)
        return OBSERVATION

    current_weather(config, fetch=fetch)
    config.timezone = "UTC"
    current_weather(config, fetch=fetch)
    assert [args[3] for args in calls] == ["Europe/Bucharest", "UTC"]


def test_weather_endpoint_is_owner_only_and_serves_cached_utc_metadata(
    client, headers, settings, monkeypatch
):
    from app.office import weather

    calls = []
    monkeypatch.setattr(settings, "office_weather_host", "api.example-weather.test")

    def transport(*args, **kwargs):
        calls.append(args)
        return {**OBSERVATION, "utc_offset_seconds": 10800}, 200, {}

    monkeypatch.setattr(weather, "request", transport)
    assert client.get("/api/v1/office/weather").status_code == 401
    assert not calls
    response = client.get("/api/v1/office/weather", headers=headers)
    assert response.status_code == 200
    assert response.json()["observed_at_utc"] == "2026-09-13T15:15:00+00:00"
    assert client.get("/api/v1/office/weather", headers=headers).json() == response.json()
    assert len(calls) == 1


def test_without_a_configured_service_the_weather_is_unavailable():
    called = []
    result = current_weather(settings(host=None), fetch=lambda *a: called.append(a))
    assert result == {"available": False, "reason": "not_configured"}
    assert called == [], "nothing is fetched when nothing is configured"


def test_an_observation_becomes_the_scene_condition():
    result = current_weather(settings(), fetch=lambda *a: OBSERVATION)
    assert result["available"] is True
    assert result["condition"] == "rain" and result["intensity"] == 0.6
    assert result["temperature_c"] == 21.4
    assert result["is_day"] is True
    assert result["observed_at"] == "2026-09-13T18:15"


def test_the_request_carries_the_office_location_and_timezone():
    seen = {}

    def fetch(host, lat, lon, tz):
        seen.update(host=host, lat=lat, lon=lon, tz=tz)
        return OBSERVATION

    current_weather(settings(), fetch=fetch)
    assert seen == {
        "host": "api.example-weather.test",
        "lat": 44.4268,
        "lon": 26.1025,
        "tz": "Europe/Bucharest",
    }


def test_a_failure_is_reported_not_replaced_by_a_guess():
    def broken(*a):
        raise MediaProviderError("down")

    result = current_weather(settings(), fetch=broken)
    assert result == {"available": False, "reason": "unreachable"}


def test_an_unknown_code_is_not_drawn_as_some_weather():
    with pytest.raises(ValueError):
        parse_observation({"current": {"weather_code": 1234}}, "host")
    assert (
        current_weather(settings(), fetch=lambda *a: {"current": {"weather_code": 1234}})[
            "available"
        ]
        is False
    )


def test_observations_are_cached_for_ten_minutes():
    calls = []
    now = [1000.0]

    def fetch(*a):
        calls.append(a)
        return OBSERVATION

    current_weather(settings(), clock=lambda: now[0], fetch=fetch)
    now[0] += 599
    current_weather(settings(), clock=lambda: now[0], fetch=fetch)
    assert len(calls) == 1
    now[0] += 2
    current_weather(settings(), clock=lambda: now[0], fetch=fetch)
    assert len(calls) == 2


def test_every_wmo_code_maps_to_a_condition_the_scene_draws():
    drawn = {"clear", "partly_cloudy", "cloudy", "fog", "drizzle", "rain", "snow", "storm"}
    for condition, intensity in WMO.values():
        assert condition in drawn
        assert 0.0 <= intensity <= 1.0


# ---------------------------------------------------------------- the full observation (phase 1)
# A response shaped like Open-Meteo's own for Bucharest, with every variable the scene reads:
# the current block (15-minute values) and the hourly precipitation of the hours before it.
FULL = {
    "current": {
        "time": "2026-09-18T19:30",
        "temperature_2m": 17.2,
        "apparent_temperature": 16.1,
        "weather_code": 61,
        "is_day": 0,
        "wind_speed_10m": 11.2,
        "wind_direction_10m": 305,
        "wind_gusts_10m": 24.5,
        "cloud_cover": 88,
        "cloud_cover_low": 40,
        "precipitation": 0.3,
        "rain": 0.3,
        "showers": 0.0,
        "snowfall": 0.0,
        "snow_depth": 0.0,
        "visibility": 24140.0,
    },
    "hourly": {
        "time": [
            "2026-09-18T16:00",
            "2026-09-18T17:00",
            "2026-09-18T18:00",
            "2026-09-18T19:00",
            "2026-09-18T20:00",
        ],
        "precipitation": [0.0, 0.4, 1.1, 0.2, 3.0],
    },
}


def test_every_field_the_scene_reads_is_parsed():
    result = parse_observation(FULL, "host")
    assert result["apparent_temperature_c"] == 16.1
    assert result["rain_mm"] == 0.3
    assert result["showers_mm"] == 0.0
    assert result["snowfall_cm"] == 0.0
    assert result["snow_depth_m"] == 0.0
    assert result["wind_from_deg"] == 305.0
    assert result["wind_gust_kph"] == 24.5
    assert result["visibility_m"] == 24140.0
    assert result["cloud_cover_low"] == 40.0


def test_the_past_three_hours_are_summed_from_observed_hours_only():
    # 20:00 lies after the observation: a forecast, never counted as rain that fell
    result = parse_observation(FULL, "host")
    assert result["precip_last_3h_mm"] == pytest.approx(0.4 + 1.1 + 0.2)


def test_a_field_the_service_does_not_return_is_none_not_zero():
    result = parse_observation(OBSERVATION, "host")
    for key in (
        "apparent_temperature_c",
        "rain_mm",
        "showers_mm",
        "snowfall_cm",
        "snow_depth_m",
        "wind_from_deg",
        "wind_gust_kph",
        "visibility_m",
        "cloud_cover_low",
        "precip_last_3h_mm",
    ):
        assert result[key] is None, key


def test_a_gap_in_the_past_hours_leaves_their_sum_unknown():
    data = {
        **FULL,
        "hourly": {"time": FULL["hourly"]["time"], "precipitation": [0.0, None, 1.1, 0.2, 0.0]},
    }
    assert parse_observation(data, "host")["precip_last_3h_mm"] is None
    short = {**FULL, "hourly": {"time": ["2026-09-18T19:00"], "precipitation": [0.2]}}
    assert parse_observation(short, "host")["precip_last_3h_mm"] is None


def test_the_request_asks_for_every_variable_and_the_past_hours(monkeypatch):
    from app.office import weather

    seen = {}

    def fake_request(host, method, path, headers, timeout):
        seen["path"] = path
        return FULL, 200, {}

    monkeypatch.setattr(weather, "request", fake_request)
    weather.fetch_observation("api.example-weather.test", 44.4268, 26.1025, "Europe/Bucharest")
    path = seen["path"]
    for variable in (
        "rain",
        "showers",
        "snowfall",
        "snow_depth",
        "wind_direction_10m",
        "wind_gusts_10m",
        "visibility",
        "apparent_temperature",
        "cloud_cover_low",
    ):
        assert variable in path
    assert "hourly=precipitation" in path and "past_hours=3" in path
