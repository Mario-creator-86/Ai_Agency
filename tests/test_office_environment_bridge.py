"""The environment pass: the real world sent to the live level, and only through the named calls.

It follows the people pass: send on change, everything again every 20 s, a 2 s timeout, quiet
when Unreal is down. It reads object paths only from the report the rebuild writes
(env_report.json); without it, it does nothing and says so once. It calls only the Remote Control
functions the scene's allow-list names (critic's corrected phase 1, DefaultRemoteControl.ini).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.office import unreal
from app.office.scene_params import scene_params
from app.office.unreal import (
    CLOCK_TIME_READ,
    ENVIRONMENT_CALLS,
    EnvironmentPass,
    environment_calls,
    load_env_report,
    run_unreal_bridge,
)
from app.office.world import LIVE_DATABASE, ROOT, Sun, Weather, WorldState

# the Owner's own database, named only through world.py's path: nothing here opens it
LIVE_URL = f"sqlite:///{LIVE_DATABASE.relative_to(ROOT).as_posix()}"

LEVEL = "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel"


def entry(label, actor, component, **extra):
    """One label as env_report_hq_live.py's _entry writes it (plus a light's intensity)."""
    return {
        "label": label,
        "actor": f"{LEVEL}.{actor}",
        "class": actor.rsplit("_", 1)[0],
        "component": f"{LEVEL}.{actor}.{component}",
        "component_class": "",
        **extra,
    }


# The report's shape is env_report_hq_live.py's (assemble()); the light intensities are the saved
# level's own, which the report must carry for the pass to scale them (today: lamps 1000 W x 70
# lm/W x 0.32, uplights 1500 x 70 x 0.15, the shelter 60 x 70, the look pass's car lights).
REPORT = {
    "version": 1,
    "level": "/Game/HQ/HQ_Dusk",
    "labels": {
        "sun": entry("Sun", "DirectionalLight_1", "LightComponent0", intensity=0.0),
        "twilight_evening": entry(
            "SunDusk", "DirectionalLight_2", "LightComponent0", intensity=2.5
        ),
        "twilight_morning": entry(
            "SunDawn", "DirectionalLight_3", "LightComponent0", intensity=0.0
        ),
        "sky_light": entry("SkyLight", "SkyLight_0", "SkyLightComponent0"),
        "fog": entry("HeightFog", "ExponentialHeightFog_0", "HeightFogComponent0"),
        "sky_backdrop": entry("SkyBackdrop", "StaticMeshActor_223", "StaticMeshComponent0"),
        "clock_display": entry("ClockDisplay", "StaticMeshActor_300", "StaticMeshComponent0"),
        "shelter_light": entry("shelter_light", "RectLight_2", "LightComponent0", intensity=4200.0),
        "street_fill": entry("StreetFill", "RectLight_9", "LightComponent0", intensity=3300.0),
        "walk_wash": entry("WalkWash", "RectLight_10", "LightComponent0", intensity=150.0),
        "facade_light": entry("FacadeLight", "RectLight_11", "LightComponent0", intensity=800.0),
        "skyline": entry("skyline", "StaticMeshActor_10", "StaticMeshComponent0"),
        "near_blocks": entry("near_blocks", "StaticMeshActor_11", "StaticMeshComponent0"),
        "props": entry("props", "StaticMeshActor_12", "StaticMeshComponent0"),
        "street_ground": entry("street_ground", "StaticMeshActor_13", "StaticMeshComponent0"),
        "sky_atmosphere": None,
        "clock_digits_baked": entry(
            "clock_digits_mesh", "StaticMeshActor_177", "StaticMeshComponent0"
        ),
        "lamps": {
            "lamp_left": entry("lamp_left", "PointLight_5", "LightComponent0", intensity=22400.0),
        },
        "skyline_haze": {
            "SkylineHaze_near_left": entry(
                "SkylineHaze_near_left", "StaticMeshActor_20", "StaticMeshComponent0"
            ),
            "SkylineHaze_far_right": entry(
                "SkylineHaze_far_right", "StaticMeshActor_21", "StaticMeshComponent0"
            ),
        },
        "tree_uplights": [
            entry("tree_uplight", "SpotLight_7", "LightComponent0", intensity=15750.0),
        ],
        "car_headlights": [
            entry("car_sedan_headlight_l", "SpotLight_40", "LightComponent0", intensity=900.0),
        ],
        "car_taillights": [
            entry("car_sedan_taillight_l", "PointLight_41", "LightComponent0", intensity=160.0),
        ],
    },
    "axes": {
        "scene_x": [1.0, 0.0, 0.0],
        "scene_y": [0.0, -1.0, 0.0],
        "scene_z": [0.0, 0.0, 1.0],
        "units_per_m": 100.0,
    },
    "compass": {
        "facade_heading_deg": 180.0,
        "north": [0.0, -1.0, 0.0],
        "east": [1.0, 0.0, 0.0],
        "up": [0.0, 0.0, 1.0],
    },
    "emissive_scaling": {
        "skyline": {
            "uniform": True,
            "reasons": [],
            "component": f"{LEVEL}.StaticMeshActor_10.StaticMeshComponent0",
        },
        "near_blocks": {
            "uniform": False,
            "reasons": ["slot 3 glow: EmissiveFactor not 1,1,1"],
            "component": f"{LEVEL}.StaticMeshActor_11.StaticMeshComponent0",
        },
    },
    "road": {
        "component": f"{LEVEL}.StaticMeshActor_13.StaticMeshComponent0",
        "slot": 2,
        "parameters": ["Roughness Min", "Roughness Max"],
    },
    "window_view": {
        "component": f"{LEVEL}.StaticMeshActor_12.StaticMeshComponent0",
        "slots": [7, 8],
        "parameter": "DayBlend",
    },
    "clock": {"parameter": "ClockOffsetS", "unsynced_default": -1.0e10},
}


def write_report(tmp_path, report=REPORT):
    path = tmp_path / "env_report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def weather(**overrides):
    base = dict(
        observed_at="2026-09-18T19:30",
        condition="clear",
        weather_code=0,
        temperature_c=17.0,
        apparent_temperature_c=16.0,
        cloud_cover=0.0,
        cloud_cover_low=0.0,
        precipitation_mm=0.0,
        rain_mm=0.0,
        showers_mm=0.0,
        snowfall_cm=0.0,
        snow_depth_m=0.0,
        visibility_m=24000.0,
        wind_kph=8.0,
        wind_gust_kph=15.0,
        wind_from_deg=300.0,
        precip_last_3h_mm=1.2,
        is_day=False,
    )
    base.update(overrides)
    return Weather(**base)


def world(elevation=-2.5, azimuth=274.9, w="default"):
    now = datetime(2026, 9, 18, 16, 31, tzinfo=UTC)
    return WorldState(
        computed_at=now,
        local_time=now,
        seconds_of_day=70260.0,
        sun=Sun(elevation, azimuth),
        weather=weather() if w == "default" else w,
        weather_reason=None,
        weather_age_s=None,
        rehearsal=False,
    )


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Recorder:
    """A fake Remote Control: records every call; answers each with a status code."""

    def __init__(self, refuse=()):
        self.batches = []
        self.refuse = set(refuse)
        self.down = False

    def __call__(self, bodies):
        if self.down:
            raise ConnectionRefusedError("unreal not running")
        self.batches.append(list(bodies))
        return [400 if b["functionName"] in self.refuse else 200 for b in bodies]

    @property
    def calls(self):
        return [b for batch in self.batches for b in batch]

    def last(self, path_end, function, name=None):
        found = [
            b
            for b in self.calls
            if b["objectPath"].endswith(path_end)
            and b["functionName"] == function
            and (name is None or b["parameters"].get("ParameterName") == name)
        ]
        return found[-1] if found else None


def report(tmp_path):
    return load_env_report(write_report(tmp_path))


# ---------------------------------------------------------------- the report
def test_without_the_report_nothing_is_sent_and_it_is_said_once(tmp_path, caplog):
    assert load_env_report(tmp_path / "missing.json") is None
    sender = Recorder()
    env = EnvironmentPass(sender, clock=Clock())
    with caplog.at_level(logging.INFO):
        assert env.sync(world(), None, 180.0) == 0
        assert env.sync(world(), None, 180.0) == 0
    assert sender.calls == []
    assert [r.message for r in caplog.records].count("office_unreal_env_report_missing") == 1


def test_a_report_without_axes_is_not_read_as_some_axes(tmp_path):
    broken = {k: v for k, v in REPORT.items() if k != "axes"}
    assert load_env_report(write_report(tmp_path, broken)) is None
    assert load_env_report(write_report(tmp_path, {"labels": "nonsense"})) is None
    (tmp_path / "env_report.json").write_text("{not json", encoding="utf-8")
    assert load_env_report(tmp_path / "env_report.json") is None


def test_a_report_written_for_another_heading_drives_nothing(tmp_path, caplog):
    other = json.loads(json.dumps(REPORT))
    other["compass"]["facade_heading_deg"] = 90.0
    sender = Recorder()
    with caplog.at_level(logging.INFO):
        assert (
            EnvironmentPass(sender, clock=Clock()).sync(
                world(), load_env_report(write_report(tmp_path, other)), 180.0
            )
            == 0
        )
    assert sender.calls == []
    assert any(r.message == "office_unreal_env_report_heading_mismatch" for r in caplog.records)


def test_the_window_view_is_left_alone_while_props_carry_no_window_view_material(tmp_path):
    none_yet = json.loads(json.dumps(REPORT))
    none_yet["window_view"]["slots"] = []
    rep = load_env_report(write_report(tmp_path, none_yet))
    plan = scene_params(world(), rep.frame(180.0))
    assert not any(c.name == "DayBlend" for c in environment_calls(plan, rep))


def test_the_report_gives_the_world_to_read_the_game_time_in(tmp_path):
    assert report(tmp_path).world == "/Game/HQ/HQ_Dusk.HQ_Dusk"


# ---------------------------------------------------------------- only the named calls
def test_every_call_is_one_the_allow_list_names(tmp_path):
    rep = report(tmp_path)
    for elevation in (-30.0, -2.5, 1.0, 47.0):
        plan = scene_params(world(elevation=elevation), rep.frame(180.0), game_time_s=12.0)
        for call in environment_calls(plan, rep):
            body = call.body()
            assert (call.cls, body["functionName"]) in ENVIRONMENT_CALLS
            assert body["generateTransaction"] is False
    # the allow-list the spec names, and nothing broader
    assert ENVIRONMENT_CALLS == frozenset(
        {
            ("LightComponent", "SetIntensity"),
            ("LightComponent", "SetLightColor"),
            ("SceneComponent", "K2_SetWorldRotation"),
            ("SkyLightComponent", "SetIntensity"),
            ("SkyLightComponent", "SetLightColor"),
            ("SkyLightComponent", "SetLowerHemisphereColor"),
            ("ExponentialHeightFogComponent", "SetFogInscatteringColor"),
            ("ExponentialHeightFogComponent", "SetFogDensity"),
            ("MeshComponent", "SetScalarParameterValueOnMaterials"),
            ("MeshComponent", "SetVectorParameterValueOnMaterials"),
        }
    )
    assert CLOCK_TIME_READ == ("/Script/Engine.Default__GameplayStatics", "GetTimeSeconds")


def test_an_emissive_component_not_flagged_uniform_is_never_scaled(tmp_path):
    rep = report(tmp_path)
    plan = scene_params(world(elevation=40.0, azimuth=180.0), rep.frame(180.0))
    targets = [c.path for c in environment_calls(plan, rep) if c.name == "EmissiveFactor"]
    assert any(p.endswith("StaticMeshActor_10.StaticMeshComponent0") for p in targets)
    assert not any(p.endswith("StaticMeshActor_11.StaticMeshComponent0") for p in targets)


def test_a_light_without_its_build_intensity_is_left_alone(tmp_path):
    rep_dict = json.loads(json.dumps(REPORT))
    rep_dict["labels"]["lamps"]["lamp_far_left"] = entry(
        "lamp_far_left", "PointLight_6", "LightComponent0"
    )
    rep = load_env_report(write_report(tmp_path, rep_dict))
    plan = scene_params(world(), rep.frame(180.0))
    assert not any(
        c.path.endswith("PointLight_6.LightComponent0") for c in environment_calls(plan, rep)
    )


# ---------------------------------------------------------------- what is sent
def test_the_reference_dusk_sends_todays_values(tmp_path):
    rep, sender = report(tmp_path), Recorder()
    env = EnvironmentPass(sender, clock=Clock())
    assert env.sync(world(), rep, 180.0, game_time_s=100.0) > 0
    assert sender.last("PointLight_5.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 22400.0
    }
    assert sender.last("SpotLight_40.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 900.0
    }
    road = sender.last(
        "StaticMeshActor_13.StaticMeshComponent0",
        "SetScalarParameterValueOnMaterials",
        "Roughness Min",
    )
    assert road["parameters"]["ParameterValue"] == 0.14
    fog = sender.last("HeightFogComponent0", "SetFogInscatteringColor")["parameters"]["Value"]
    assert (fog["R"], fog["G"], fog["B"]) == (0.3, 0.34, 0.55)
    clock = sender.last(
        "StaticMeshActor_300.StaticMeshComponent0",
        "SetScalarParameterValueOnMaterials",
        "ClockOffsetS",
    )
    assert clock["parameters"]["ParameterValue"] == 70260.0 - 100.0
    rotation = sender.last("DirectionalLight_1.LightComponent0", "K2_SetWorldRotation")
    assert set(rotation["parameters"]) == {"NewRotation", "bSweep", "bTeleport"}
    assert rotation["parameters"]["bTeleport"] is True
    assert sender.last("DirectionalLight_1.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 0.0
    }
    # the warm key of the dusk is SunDusk as built: 2.5, its own colour, never turned
    assert sender.last("DirectionalLight_2.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 2.5
    }
    colour = sender.last("DirectionalLight_2.LightComponent0", "SetLightColor")["parameters"]
    assert colour == {"NewLightColor": {"R": 1.0, "G": 0.62, "B": 0.38, "A": 1.0}, "bSRGB": True}
    assert sender.last("DirectionalLight_3.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 0.0
    }
    # the room windows: the dusk picture, neither the day nor the night state
    for name in ("DayBlend", "NightBlend"):
        view = sender.last(
            "StaticMeshActor_12.StaticMeshComponent0", "SetScalarParameterValueOnMaterials", name
        )
        assert view["parameters"]["ParameterValue"] == 0.0, name


# ---------------------------------------------------------------- the twilight keys
def test_the_twilight_keys_are_never_turned(tmp_path):
    """SunDusk and SunDawn are Stationary: the game refuses to rotate them, and their direction is
    the sunset's and the sunrise's side by construction. Only intensity and colour are sent."""
    rep, sender, clock = report(tmp_path), Recorder(), Clock()
    env = EnvironmentPass(sender, clock=clock)
    for i, (elevation, azimuth) in enumerate(
        ((-2.5, 274.3), (-4.0, 280.0), (-2.5, 85.4), (1.0, 95.0), (20.9, 109.6), (-22.9, 330.0))
    ):
        clock.now = 30.0 * i
        env.sync(world(elevation, azimuth), rep, 180.0)
    for key in ("DirectionalLight_2", "DirectionalLight_3"):
        functions = {b["functionName"] for b in sender.calls if key in b["objectPath"]}
        assert functions == {"SetIntensity", "SetLightColor"}, key
    turned = {b["objectPath"] for b in sender.calls if b["functionName"] == "K2_SetWorldRotation"}
    assert turned == {f"{LEVEL}.DirectionalLight_1.LightComponent0"}


def test_a_morning_lights_the_morning_key_and_leaves_the_evening_one_dark(tmp_path):
    rep, sender = report(tmp_path), Recorder()
    EnvironmentPass(sender, clock=Clock()).sync(world(-2.5, 85.4), rep, 180.0)
    assert sender.last("DirectionalLight_3.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 2.5
    }
    assert sender.last("DirectionalLight_2.LightComponent0", "SetIntensity")["parameters"] == {
        "NewIntensity": 0.0
    }


def test_by_day_the_sun_carries_the_light_and_at_night_nothing_does(tmp_path):
    rep = report(tmp_path)
    day, night = Recorder(), Recorder()
    EnvironmentPass(day, clock=Clock()).sync(world(46.97, 180.0), rep, 180.0)
    EnvironmentPass(night, clock=Clock()).sync(world(-22.9, 330.0), rep, 180.0)

    def lit(sender, key):
        return sender.last(f"{key}.LightComponent0", "SetIntensity")["parameters"]["NewIntensity"]

    assert lit(day, "DirectionalLight_1") > 2.5
    assert lit(day, "DirectionalLight_2") == lit(day, "DirectionalLight_3") == 0.0
    for key in ("DirectionalLight_1", "DirectionalLight_2", "DirectionalLight_3"):
        assert lit(night, key) == 0.0, key
    view = night.last(
        "StaticMeshActor_12.StaticMeshComponent0",
        "SetScalarParameterValueOnMaterials",
        "NightBlend",
    )
    assert view["parameters"]["ParameterValue"] == 1.0


def test_the_near_blocks_take_their_day_colour_from_the_real_sun(tmp_path):
    """look_hq_live.near_blocks_day gives the near blocks' darkest plain slots M_HQ_CityDay, whose
    Daylight blends the dusk colour (0, the build's value) to the slot's own hue at a facade's
    albedo (1). The backend sets it from the same day weight as the room windows' DayBlend, on the
    near_blocks component whether or not its glow scales uniformly: no other slot has Daylight."""

    def daylight(elevation, azimuth):
        sender = Recorder()
        EnvironmentPass(sender, clock=Clock()).sync(world(elevation, azimuth), rep, 180.0)
        found = [b for b in sender.calls if b["parameters"].get("ParameterName") == "Daylight"]
        assert [b["objectPath"] for b in found] == [
            f"{LEVEL}.StaticMeshActor_11.StaticMeshComponent0"
        ]
        assert found[0]["functionName"] == "SetScalarParameterValueOnMaterials"
        return found[0]["parameters"]["ParameterValue"]

    rep = report(tmp_path)
    assert daylight(-2.5, 274.3) == 0.0
    assert daylight(-22.9, 330.0) == 0.0
    assert daylight(46.97, 180.0) == 1.0
    assert 0.0 < daylight(1.0, 95.0) < 1.0


def test_a_report_without_the_twilight_keys_drives_the_rest(tmp_path):
    older = json.loads(json.dumps(REPORT))
    del older["labels"]["twilight_evening"], older["labels"]["twilight_morning"]
    rep, sender = load_env_report(write_report(tmp_path, older)), Recorder()
    assert EnvironmentPass(sender, clock=Clock()).sync(world(), rep, 180.0) > 0
    assert not any("DirectionalLight_2" in b["objectPath"] for b in sender.calls)
    assert sender.last("DirectionalLight_1.LightComponent0", "SetIntensity") is not None


def test_the_sky_scalars_travel_in_one_batch(tmp_path):
    rep, sender = report(tmp_path), Recorder()
    EnvironmentPass(sender, clock=Clock()).sync(world(), rep, 180.0)
    sky_batches = [
        batch
        for batch in sender.batches
        if any(b["objectPath"].endswith("StaticMeshActor_223.StaticMeshComponent0") for b in batch)
    ]
    assert len(sky_batches) == 1
    names = {
        b["parameters"]["ParameterName"]
        for b in sky_batches[0]
        if b["objectPath"].endswith("StaticMeshActor_223.StaticMeshComponent0")
    }
    assert names == {"PlateA", "PlateB", "PlateBlend", "Mirror", "Gain"}


def test_without_a_game_time_the_clock_is_not_set(tmp_path):
    rep, sender = report(tmp_path), Recorder()
    EnvironmentPass(sender, clock=Clock()).sync(world(), rep, 180.0, game_time_s=None)
    assert (
        sender.last(
            "StaticMeshActor_300.StaticMeshComponent0",
            "SetScalarParameterValueOnMaterials",
            "ClockOffsetS",
        )
        is None
    )


def test_nothing_is_sent_again_until_it_changes_or_the_refresh(tmp_path):
    rep, sender, clock = report(tmp_path), Recorder(), Clock()
    env = EnvironmentPass(sender, clock=clock)
    env.sync(world(), rep, 180.0, game_time_s=100.0)
    first = len(sender.calls)
    clock.now = 5.0
    assert env.sync(world(), rep, 180.0, game_time_s=100.0) == 0
    assert len(sender.calls) == first
    clock.now = 20.0
    env.sync(world(), rep, 180.0, game_time_s=120.0)
    assert len(sender.calls) == 2 * first  # the 20 s refresh resends all, the clock with it


def test_the_sun_turns_only_when_it_moved_a_quarter_degree(tmp_path):
    rep, sender, clock = report(tmp_path), Recorder(), Clock()
    env = EnvironmentPass(sender, clock=clock)
    env.sync(world(elevation=20.0, azimuth=200.0), rep, 180.0)
    count = lambda: len([b for b in sender.calls if b["functionName"] == "K2_SetWorldRotation"])  # noqa: E731
    clock.now = 5.0
    env.sync(world(elevation=20.1, azimuth=200.1), rep, 180.0)
    assert count() == 1
    clock.now = 10.0
    env.sync(world(elevation=20.3, azimuth=200.2), rep, 180.0)
    assert count() == 2


def test_a_change_of_light_is_eased_over_thirty_seconds(tmp_path):
    rep, sender, clock = report(tmp_path), Recorder(), Clock()
    env = EnvironmentPass(sender, clock=clock, ease_s=30.0)
    env.sync(world(elevation=-1.0), rep, 180.0)  # lamps off

    def lamp():
        return sender.last("PointLight_5.LightComponent0", "SetIntensity")["parameters"][
            "NewIntensity"
        ]

    assert lamp() == 0.0
    clock.now = 5.0
    env.sync(world(elevation=-2.2), rep, 180.0)  # below -2: on, eased in
    assert lamp() == 0.0  # the ease starts from what is on screen
    clock.now = 20.0
    env.sync(world(elevation=-2.2), rep, 180.0)
    assert lamp() == pytest.approx(22400.0 * 15.0 / 30.0)
    clock.now = 40.0
    env.sync(world(elevation=-2.2), rep, 180.0)
    assert lamp() == 22400.0


def test_unreal_down_is_quiet_and_everything_is_resent_when_it_answers(tmp_path, caplog):
    rep, sender, clock = report(tmp_path), Recorder(), Clock()
    env = EnvironmentPass(sender, clock=clock)
    sender.down = True
    with caplog.at_level(logging.INFO):
        assert env.sync(world(), rep, 180.0) == 0
        clock.now = 5.0
        assert env.sync(world(), rep, 180.0) == 0
    assert [r.message for r in caplog.records].count("office_unreal_env_unreachable") == 1
    sender.down = False
    clock.now = 10.0
    assert env.sync(world(), rep, 180.0) > 0


def test_a_refused_call_is_said_once_and_the_rest_still_lands(tmp_path, caplog):
    rep, sender, clock = report(tmp_path), Recorder(refuse={"SetFogDensity"}), Clock()
    env = EnvironmentPass(sender, clock=clock)
    with caplog.at_level(logging.INFO):
        env.sync(world(), rep, 180.0)
        clock.now = 20.0
        env.sync(world(), rep, 180.0)
    refusals = [r for r in caplog.records if r.message == "office_unreal_env_call_refused"]
    assert len(refusals) == 1
    assert sender.last("SkyLight_0.SkyLightComponent0", "SetIntensity") is not None


# ---------------------------------------------------------------- the running loop
def test_the_loop_reads_the_weather_every_ten_minutes_and_never_guesses_paths(
    tmp_path, monkeypatch
):
    fetched = []
    sent = []

    def fake_weather(settings):
        fetched.append(1)
        return {"available": False, "reason": "not_configured"}

    monkeypatch.setattr(unreal, "current_weather", fake_weather)
    monkeypatch.setattr(
        unreal, "get_office_layout_with_assignments", lambda engine: {"assignments": []}
    )
    monkeypatch.setattr(unreal, "http_sender", lambda target: lambda body: sent.append(body))
    monkeypatch.setattr(
        unreal,
        "http_batch_sender",
        lambda target: lambda bodies: sent.extend(bodies) or [200] * len(bodies),
    )
    monkeypatch.setattr(unreal, "http_game_time_reader", lambda target: lambda world: 50.0)
    settings = SimpleNamespace(
        office_unreal_remote_url="http://127.0.0.1:30010",
        office_unreal_seat_report=tmp_path / "no_seats.json",
        office_unreal_sync_seconds=0.3,
        office_unreal_env_report=tmp_path / "env_report.json",  # missing: the pass does nothing
        office_unreal_env_refresh_seconds=20.0,
        office_unreal_env_ease_seconds=30.0,
        office_weather_refresh_seconds=600.0,
        office_facade_heading_deg=180.0,
        office_latitude=44.4268,
        office_longitude=26.1025,
        timezone="Europe/Bucharest",
        database_url=LIVE_URL,
        office_world_rehearsal_at=None,
        office_weather_host=None,
    )

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(run_unreal_bridge(None, settings, stop))
        await asyncio.sleep(0.8)
        stop.set()
        await task

    asyncio.run(run())
    assert sent == []  # no report: no environment call, and no seat either
    assert len(fetched) == 1  # three passes, one weather read (the next is due in 10 min)


def test_a_rehearsal_hour_on_the_live_studio_is_refused_and_the_real_clock_kept(caplog):
    settings = SimpleNamespace(
        office_latitude=44.4268,
        office_longitude=26.1025,
        timezone="Europe/Bucharest",
        database_url=LIVE_URL,
        office_world_rehearsal_at=datetime(2026, 1, 15, 6, 0, tzinfo=UTC),
    )
    with caplog.at_level(logging.WARNING):
        clock, rehearsal = unreal.environment_clock(settings)
    assert rehearsal is False
    assert abs((clock() - datetime.now(UTC)).total_seconds()) < 2
    assert any(r.message == "office_world_rehearsal_refused_live" for r in caplog.records)


# ---------------------------------------------------------------- the wire, on loopback
class FakeRemoteControl:
    """A local HTTP server answering like Remote Control (/remote/batch, /remote/object/call)."""

    def __init__(self, refuse=(), game_time=321.5):
        import http.server
        import threading

        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):  # noqa: N802 - the stdlib's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                if self.path == "/remote/batch":
                    answer = {
                        "Responses": [
                            {
                                "RequestId": r["RequestId"],
                                "ResponseCode": 400 if r["Body"]["functionName"] in refuse else 200,
                                "ResponseBody": None,
                            }
                            for r in body["Requests"]
                        ]
                    }
                    code = 200
                elif body["functionName"] in refuse:
                    answer, code = {"errorMessage": "not allowed"}, 400
                elif body["functionName"] == "GetTimeSeconds":
                    answer, code = {"ReturnValue": game_time}, 200
                else:
                    answer, code = {}, 200
                data = json.dumps(answer).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_the_batch_goes_out_as_remote_controls_batch_and_refusals_come_back_per_call():
    rc = FakeRemoteControl(refuse={"SetFogDensity"})
    try:
        send = unreal.http_batch_sender(rc.url)
        a = {
            "objectPath": "/A",
            "functionName": "SetIntensity",
            "parameters": {},
            "generateTransaction": False,
        }
        b = {
            "objectPath": "/B",
            "functionName": "SetFogDensity",
            "parameters": {},
            "generateTransaction": False,
        }
        assert send([a, b]) == [200, 400]
        path, body = rc.requests[-1]
        assert path == "/remote/batch"
        assert [r["URL"] for r in body["Requests"]] == ["/remote/object/call"] * 2
        assert [r["Body"] for r in body["Requests"]] == [a, b]
        assert send([b]) == [400]
        assert rc.requests[-1][0] == "/remote/object/call"
    finally:
        rc.close()


def test_the_game_time_is_read_in_the_levels_world_and_a_refusal_raises():
    rc = FakeRemoteControl()
    try:
        assert unreal.http_game_time_reader(rc.url)("/Game/HQ/HQ_Dusk.HQ_Dusk") == 321.5
        _, body = rc.requests[-1]
        assert body["objectPath"] == "/Script/Engine.Default__GameplayStatics"
        assert body["parameters"] == {"WorldContextObject": "/Game/HQ/HQ_Dusk.HQ_Dusk"}
    finally:
        rc.close()
    refused = FakeRemoteControl(refuse={"GetTimeSeconds"})
    try:
        with pytest.raises(OSError):
            unreal.http_game_time_reader(refused.url)("/Game/HQ/HQ_Dusk.HQ_Dusk")
    finally:
        refused.close()


def runner_settings(tmp_path, **overrides):
    base = dict(
        office_unreal_env_report=write_report(tmp_path),
        office_weather_refresh_seconds=600.0,
        office_facade_heading_deg=180.0,
        office_latitude=44.4268,
        office_longitude=26.1025,
        timezone="Europe/Bucharest",
        database_url=LIVE_URL,
        office_world_rehearsal_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_the_runner_sets_the_clock_from_the_game_time_it_read(tmp_path, monkeypatch):
    monkeypatch.setattr(
        unreal, "current_weather", lambda s: {"available": False, "reason": "not_configured"}
    )
    sender = Recorder()
    runner = unreal.EnvironmentRunner(
        runner_settings(tmp_path), EnvironmentPass(sender, clock=Clock()), lambda world: 1000.0
    )
    runner.tick()
    offset = sender.last(
        "StaticMeshActor_300.StaticMeshComponent0",
        "SetScalarParameterValueOnMaterials",
        "ClockOffsetS",
    )
    local = datetime.now(UTC).astimezone(__import__("zoneinfo").ZoneInfo("Europe/Bucharest"))
    wall = local.hour * 3600 + local.minute * 60 + local.second
    assert abs((offset["parameters"]["ParameterValue"] + 1000.0) % 86400 - wall) < 3


def test_an_unreadable_game_time_leaves_the_clock_alone_and_is_said_once(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(
        unreal, "current_weather", lambda s: {"available": False, "reason": "not_configured"}
    )
    sender, clock = Recorder(), Clock()

    def refused(world):
        raise OSError("400 not allowed")

    runner = unreal.EnvironmentRunner(
        runner_settings(tmp_path), EnvironmentPass(sender, clock=clock), refused
    )
    with caplog.at_level(logging.INFO):
        runner.tick()
        clock.now = 25.0
        runner.tick()
    assert [r.message for r in caplog.records].count("office_unreal_clock_time_unread") == 1
    assert not any(b["parameters"].get("ParameterName") == "ClockOffsetS" for b in sender.calls)


def test_a_rehearsal_on_a_copy_reads_no_weather_and_says_so(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(unreal, "current_weather", lambda s: fetched.append(1))
    sender = Recorder()
    settings = runner_settings(
        tmp_path,
        database_url=f"sqlite:///{tmp_path.as_posix()}/copy.db",
        office_world_rehearsal_at=datetime(2026, 1, 15, 6, 0, tzinfo=UTC),
    )
    runner = unreal.EnvironmentRunner(
        settings, EnvironmentPass(sender, clock=Clock()), lambda w: 1.0
    )
    runner.tick()
    assert fetched == []
    # the rehearsed hour (08:00 in Bucharest, 15 Jan: the sun just under the horizon) drives the sun
    assert sender.last("DirectionalLight_1.LightComponent0", "SetIntensity") is not None


# ---------------------------------------------------------------- the contract with the writer
def test_the_report_the_rebuild_writes_is_the_report_the_bridge_reads(tmp_path):
    """env_report_hq_live.py's own assemble() on its own test level, read back by the bridge."""
    import importlib.util
    from pathlib import Path

    tests = Path(__file__).resolve().parent
    script = tests.parent / "art-source" / "unreal" / "env_report_hq_live.py"
    if not script.exists():
        pytest.skip("env_report_hq_live.py not written yet")
    modules = {}
    for name, path in (("env_writer", script), ("env_writer_tests", tests / "test_env_report.py")):
        spec = importlib.util.spec_from_file_location(name, path)
        modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules[name])
    level = modules["env_writer_tests"]
    records = level.full_level() + [
        level.actor("SunDusk", "DirectionalLight", 2, comp_cls="DirectionalLightComponent"),
        level.actor("SunDawn", "DirectionalLight", 3, comp_cls="DirectionalLightComponent"),
    ]
    written, missing = modules["env_writer"].assemble(
        records, level.AXES, 180.0, expected_counts={"tree_uplights": 2}
    )
    assert missing == []
    assert modules["env_writer"].missing_twilight_keys(written) == []
    rep = load_env_report(write_report(tmp_path, written))
    assert rep is not None
    assert rep.world == "/Game/HQ/HQ_Dusk.HQ_Dusk"
    assert rep.heading_deg == 180.0
    assert rep.axes == ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0))
    for role in (
        "sun",
        "twilight:evening",
        "twilight:morning",
        "sky_light",
        "fog",
        "sky_backdrop",
        "clock_display",
        "road",
        "window_view",
        "skyline",
        "near_blocks",
    ):
        assert len(rep.of(role)) == 1, role
    assert rep.of("skyline")[0].emissive_uniform is True
    assert len(rep.of("haze")) == 4
    assert len(rep.of("light:lamps")) == 3 and len(rep.of("light:uplights")) == 2
    assert len(rep.of("light:car_lights")) == 3 and len(rep.of("light:fills")) == 3
    plan = scene_params(world(), rep.frame(180.0), game_time_s=10.0)
    for call in environment_calls(plan, rep):
        assert (call.cls, call.function) in ENVIRONMENT_CALLS


def test_the_rebuild_fails_without_both_twilight_keys(tmp_path):
    """env_report_hq_live.py's main() refuses a level without SunDusk and SunDawn: the bridge would
    leave the dusk without its warm key rather than guess an object."""
    import importlib.util
    from pathlib import Path

    tests = Path(__file__).resolve().parent
    script = tests.parent / "art-source" / "unreal" / "env_report_hq_live.py"
    modules = {}
    for name, path in (
        ("env_writer2", script),
        ("env_writer_tests2", tests / "test_env_report.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules[name])
    level, writer = modules["env_writer_tests2"], modules["env_writer2"]
    dawn = level.actor("SunDawn", "DirectionalLight", 3, comp_cls="DirectionalLightComponent")
    written, _ = writer.assemble(
        level.full_level() + [dawn], level.AXES, 180.0, expected_counts={"tree_uplights": 2}
    )
    assert writer.missing_twilight_keys(written) == ["twilight_evening: SunDusk"]
    # a mesh called SunDusk is not a light
    fake = level.mesh("SunDusk", 99)
    written, _ = writer.assemble(
        level.full_level() + [dawn, fake], level.AXES, 180.0, expected_counts={"tree_uplights": 2}
    )
    assert writer.missing_twilight_keys(written) == ["twilight_evening: SunDusk"]
