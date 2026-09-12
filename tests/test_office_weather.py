"""The office scene's live weather: read by the backend, never invented."""

from types import SimpleNamespace

import pytest
from app.office.weather import WMO, current_weather, parse_observation, reset_cache
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
