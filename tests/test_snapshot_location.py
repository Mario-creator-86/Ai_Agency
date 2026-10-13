"""The page draws the studio where the studio is (SELL-08, PAGE-13).

The clock, the sun, the street, the holidays and the labels of the page were hard-coded to
Bucharest, the first studio's city, while the backend already had a timezone and the office's
coordinates. The snapshot now serves the place from the settings, so a buyer in Lisbon sees
Lisbon; the page keeps Bucharest only as the fallback for a snapshot that names none.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.db import create_db_engine, migrate
from app.main import create_app
from app.services import bootstrap_studio, snapshot, studio_location
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _settings(tmp_path, **values) -> Settings:
    return Settings(
        _env_file=None,
        owner_token="l" * 48,  # pragma: allowlist secret
        database_url=f"sqlite:///{(tmp_path / 'place.db').as_posix()}",
        allowed_hosts=["testserver"],
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
        **values,
    )


def test_the_snapshot_serves_the_place_from_the_settings(tmp_path):
    settings = _settings(
        tmp_path,
        timezone="Europe/Lisbon",
        office_latitude=38.7223,
        office_longitude=-9.1393,
        office_city="Lisboa",
        holiday_country="PT",
    )
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    engine.dispose()
    headers = {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}
    with TestClient(create_app(settings)) as client:
        studio = client.get("/api/v1/snapshot", headers=headers).json()["studio"]
    assert studio["timezone"] == "Europe/Lisbon"
    assert studio["location"] == {
        "latitude": 38.7223,
        "longitude": -9.1393,
        "city": "Lisboa",
        "holiday_country": "PT",
    }


def test_the_defaults_are_the_first_studios_place_and_named_as_such(tmp_path):
    location = studio_location(_settings(tmp_path))
    assert location == {
        "latitude": 44.4268,
        "longitude": 26.1025,
        "city": "București",
        "holiday_country": "RO",
    }


def test_a_snapshot_without_a_place_still_answers(engine):
    # Read outside a running app (scripts, the rehearsal): no location is named, and the
    # page falls back to its own default.
    assert (
        "location" not in snapshot(engine)["studio"]
        or snapshot(engine)["studio"]["location"] is None
    )


@pytest.mark.parametrize(
    "values",
    [{"holiday_country": "Portugal"}, {"office_city": ""}, {"office_city": "x" * 81}],
)
def test_a_malformed_place_is_refused_at_start(tmp_path, values):
    with pytest.raises(ValidationError):
        _settings(tmp_path, **values)


def test_an_empty_holiday_country_means_no_holidays(tmp_path):
    assert studio_location(_settings(tmp_path, holiday_country=""))["holiday_country"] == ""
