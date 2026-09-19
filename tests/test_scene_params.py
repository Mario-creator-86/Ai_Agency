"""One pure function from the real world to every value the live scene takes.

The golden test is the Owner's approved dusk: at the reference instant (the sun at -2.5 deg, a
clear sky, rain in the past three hours) every value must be exactly the one the level is built
with today. Those values are read here from the build scripts themselves (their defaults), and
from what a live describe of the running level returned on 2026-09-18 (copied below, since the
survey that read them is not part of the repository), so a change on either side fails here.

The warm light of that dusk is the twilight key (SunDusk, kept Stationary as it was built): after
sunset a facade is lit by the still-bright sky over the sunset, not by the sun. The real sun is a
separate Movable light that carries direct light only above the horizon.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.office.scene_params import (
    ATLAS_ELEVATIONS,
    DRY_ROAD_ROUGHNESS,
    TWILIGHT_END_ELEVATION,
    SceneFrame,
    clock_offset_s,
    scene_params,
    sun_rotation,
    twilight_colour,
    twilight_intensity,
)
from app.office.world import Sun, Weather, WorldState

ROOT = Path(__file__).resolve().parents[1]
UNREAL = ROOT / "art-source" / "unreal"

# The importer's axes as the build measured them (look_hq_live.py ue(): Blender metres -> Unreal
# centimetres, +y -> -y), and D1: the facade faces south (180 deg).
FRAME = SceneFrame(
    x=(100.0, 0.0, 0.0), y=(0.0, -100.0, 0.0), z=(0.0, 0.0, 100.0), facade_heading_deg=180.0
)

# Live describe of the running level, 2026-09-18 (runtime_reachability.json / live_values.json)
LIVE = {
    "sun_intensity": 2.5,
    "sun_color_srgb8": (255, 206, 166),
    "sun_rotation": {"Pitch": -7.94, "Yaw": -25.54},
    "sun_mobility": "Stationary",
    "sky_light_intensity": 0.6,
    "sky_light_color": (1.0, 1.0, 1.0),
    "sky_light_lower_hemisphere": (0.0, 0.0, 0.0),
    "fog_density": 0.008,
    "fog_inscattering_luminance": (0.3, 0.34, 0.55),
}


def default(script: str, name: str) -> str:
    """The default an AMN_* environment variable takes in a build script."""
    text = (UNREAL / script).read_text(encoding="utf-8")
    match = re.search(rf'"{name}",\s*"([^"]+)"', text)
    assert match, f"{name} not found in {script}"
    return match.group(1)


def floats(value: str) -> tuple[float, ...]:
    return tuple(float(v) for v in value.split(","))


BUILD = (UNREAL / "build_hq_scene.py").read_text(encoding="utf-8")


def built(name: str) -> str:
    """A module-level constant of build_hq_scene.py, as written (the right-hand side)."""
    match = re.search(rf"^{name} = (.+?)(?:  #.*)?$", BUILD, re.MULTILINE)
    assert match, f"{name} not found in build_hq_scene.py"
    return match.group(1).strip()


def built_default(name: str) -> float:
    """The default of an AMN_* override on a build_hq_scene.py constant."""
    match = re.search(r'os\.environ\.get\("[A-Z_]+", "([^"]+)"\)', built(name))
    assert match, f"{name} has no environment default"
    return float(match.group(1))


def built_tuple(name: str) -> tuple[float, ...]:
    value = built(name)
    assert value.startswith("(") and value.endswith(")"), value
    out = []
    for part in value[1:-1].split(","):
        part = part.strip()
        # the build writes the key's slope as -math.sin(math.radians(8.0)), today's SunDusk
        sine = re.fullmatch(r"(-?)math\.sin\(math\.radians\(([-\d.]+)\)\)", part)
        if sine:
            sign = -1.0 if sine.group(1) else 1.0
            out.append(sign * math.sin(math.radians(float(sine.group(2)))))
        else:
            out.append(float(part))
    return tuple(out)


def weather(**overrides) -> Weather:
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


def world(
    elevation=-2.5, azimuth=274.9, weather_value=None, reason=None, seconds=19 * 3600 + 31 * 60
):
    now = datetime(2026, 9, 18, 16, 31, tzinfo=UTC)
    return WorldState(
        computed_at=now,
        local_time=now,
        seconds_of_day=float(seconds),
        sun=Sun(elevation_deg=elevation, azimuth_deg=azimuth),
        weather=weather_value,
        weather_reason=reason,
        weather_age_s=None,
        rehearsal=False,
    )


REFERENCE = world(weather_value=weather())


def srgb8(linear: float) -> int:
    """FLinearColor -> FColor with sRGB, as SetLightColor(bSRGB=true) stores it."""
    c = max(0.0, min(1.0, linear))
    s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return int(math.floor(s * 255.999))


# ---------------------------------------------------------------- the golden test
def test_the_reference_dusk_is_todays_build_exactly():
    p = scene_params(REFERENCE, FRAME)

    # the sky: today's plate is the -2.5 cell, alone, unmirrored, at the build's gain
    assert ATLAS_ELEVATIONS[p["sky"]["PlateA"]] == -2.5
    assert p["sky"]["PlateBlend"] == 0.0
    assert p["sky"]["Mirror"] == 0.0
    assert p["sky"]["Gain"] == float(default("build_hq_scene.py", "AMN_SKY_GAIN"))

    # every exterior light at the intensity the look pass gives it
    assert p["lights"] == {
        "lamps": 1.0,
        "shelter": 1.0,
        "uplights": 1.0,
        "fills": 1.0,
        "car_lights": 1.0,
    }

    # the city's windows, the room windows' dusk picture
    assert p["emissive_factor"] == {"skyline": 1.0, "near_blocks": 1.0}
    assert p["window_view"] == {"DayBlend": 0.0, "NightBlend": 0.0}
    # the near blocks' day colour at its build default: M_HQ_CityDay's Daylight is 0 as built
    assert p["near_blocks_day"] == {"Daylight": 0.0}
    city = (UNREAL / "city_emissive.py").read_text(encoding="utf-8")
    look_text = (UNREAL / "look_hq_live.py").read_text(encoding="utf-8")
    assert re.search(r'DAY_PARAMETER = "Daylight"', city)
    assert re.search(r"scalar\(_city\.DAY_PARAMETER, 0\.0,", look_text)

    # every output is held by this test: a new one must be added here, at its build value
    assert set(p) == {
        "sun",
        "twilight",
        "sky_light",
        "lights",
        "sky",
        "emissive_factor",
        "window_view",
        "near_blocks_day",
        "haze",
        "fog",
        "road",
        "exposure",
        "clock",
        "weather_note",
    }

    # the sky light and the fog as the running level has them
    assert p["sky_light"]["intensity"] == float(default("build_hq_scene.py", "AMN_SKYLIGHT"))
    assert p["sky_light"]["intensity"] == LIVE["sky_light_intensity"]
    assert p["sky_light"]["color"] == LIVE["sky_light_color"]
    assert p["sky_light"]["lower_hemisphere"] == LIVE["sky_light_lower_hemisphere"]
    assert p["fog"]["density"] == float(default("look_hq_live.py", "AMN_LOOK_FOG"))
    assert p["fog"]["density"] == LIVE["fog_density"]
    assert p["fog"]["inscattering"] == LIVE["fog_inscattering_luminance"]
    look = (UNREAL / "look_hq_live.py").read_text(encoding="utf-8")
    assert re.search(r'"fog_inscattering_luminance", unreal\.LinearColor\(0\.3, 0\.34, 0\.55', look)

    # the haze planes: the left and right colours, the near opacity and the far share
    near_left = p["haze"]["SkylineHaze_near_left"]
    far_right = p["haze"]["SkylineHaze_far_right"]
    opacity = float(default("haze_hq_live.py", "AMN_HAZE_OPACITY"))
    share = float(default("haze_hq_live.py", "AMN_HAZE_FAR_SHARE"))
    assert near_left["HazeColor"] == floats(default("haze_hq_live.py", "AMN_HAZE_COLOR"))
    assert far_right["HazeColor"] == floats(default("haze_hq_live.py", "AMN_HAZE_COLOR_RIGHT"))
    assert near_left["Opacity"] == opacity
    assert far_right["Opacity"] == pytest.approx(opacity * share, abs=1e-12)

    # the wet road: rain in the last three hours
    assert p["road"]["Roughness Min"] == float(
        default("look_hq_live.py", "AMN_LOOK_ROAD_ROUGH_MIN")
    )
    assert p["road"]["Roughness Max"] == float(
        default("look_hq_live.py", "AMN_LOOK_ROAD_ROUGH_MAX")
    )
    assert p["road"]["wetness"] == 1.0 and p["road"]["source"] == "observed"

    # exposure is never written (D2: not approved)
    assert p["exposure"] is None

    # every directional light at exactly what the build gives it. The evening twilight key is
    # today's SunDusk: its intensity and colour as the build writes them, the live FColor within
    # the one step of UE's own fast sRGB quantisation (ToFColorSRGB), Stationary as it runs today.
    key_colour = built_tuple("TWILIGHT_KEY_COLOR")
    evening = p["twilight"]["evening"]
    assert evening["intensity"] == float(built("TWILIGHT_KEY_INTENSITY"))
    assert evening["intensity"] == LIVE["sun_intensity"]
    assert evening["color"] == key_colour
    for ours, live in zip(
        (srgb8(c) for c in evening["color"]), LIVE["sun_color_srgb8"], strict=True
    ):
        assert abs(ours - live) <= 1
    mobility = f"unreal.ComponentMobility.{LIVE['sun_mobility'].upper()}"
    assert built("TWILIGHT_KEY_MOBILITY") == mobility
    # the morning key and the real sun are built dark, and dark is what the reference gives them
    assert p["twilight"]["morning"]["intensity"] == 0.0
    assert p["twilight"]["morning"]["intensity"] == float(built("TWILIGHT_MORNING_BUILD_INTENSITY"))
    assert p["twilight"]["morning"]["color"] == key_colour
    assert p["sun"]["intensity"] == float(built("SUN_BUILD_INTENSITY")) == 0.0
    assert p["sun"]["color"] == built_tuple("SUN_BUILD_COLOR") == key_colour


def test_the_real_sun_below_the_horizon_gives_no_light_at_the_reference_instant():
    """At -2.5 deg the real sun is below the horizon, so the direct light is zero (critic, hole 1;
    the rejected rebuild measured 10.3 with nothing in its place). The dusk's warm key is the sky
    over the sunset, which the twilight key carries: the evening key at SunDusk's 2.5."""
    p = scene_params(REFERENCE, FRAME)
    assert p["sun"]["intensity"] == 0.0
    assert p["twilight"]["evening"]["intensity"] == 2.5


def test_the_build_keeps_sundusk_and_mirrors_it_for_the_morning():
    """SunDusk is built exactly as before (Stationary, from the front-left, 8 deg down); SunDawn is
    its mirror from the front-right; the Movable sun is the one light that turns."""
    evening = built_tuple("TWILIGHT_KEY_TRAVEL_EVENING")
    morning = built_tuple("TWILIGHT_KEY_TRAVEL_MORNING")
    assert evening == (0.9, 0.43, -math.sin(math.radians(8.0)))
    assert morning == (-evening[0], evening[1], evening[2])
    # the evening key travels right (it comes from the left, the west with D1), the morning left
    assert evening[0] > 0 > morning[0]
    for label in ("SunDusk", "SunDawn", "Sun"):
        assert f'"{label}"' in BUILD, label
    assert built("SUN_MOBILITY") == "unreal.ComponentMobility.MOVABLE"

    # SunDusk's travel is the rotation the running level reports (live describe, 2026-09-18);
    # the morning key's is its mirror across the facade's normal
    def as_sun(travel):
        horizontal = math.hypot(travel[0], travel[1])
        elevation = math.degrees(math.atan2(-travel[2], horizontal))
        azimuth = math.degrees(math.atan2(-travel[0], -travel[1])) % 360.0
        return Sun(elevation, azimuth)

    e_rot, m_rot = sun_rotation(as_sun(evening), FRAME), sun_rotation(as_sun(morning), FRAME)
    assert e_rot["Pitch"] == pytest.approx(LIVE["sun_rotation"]["Pitch"], abs=0.01)
    assert e_rot["Yaw"] == pytest.approx(LIVE["sun_rotation"]["Yaw"], abs=0.01)
    assert m_rot["Pitch"] == pytest.approx(e_rot["Pitch"], abs=1e-9)
    assert m_rot["Yaw"] == pytest.approx(-180.0 - e_rot["Yaw"], abs=1e-9)


def test_the_movable_sun_shadows_as_sundusk_did():
    """The rejected build gave the Movable sun cascades to 200 m while the plate camera stands
    246 m from the facade, so no cascade reached the building. SunDusk, Stationary in a level whose
    lighting is never built, drew the engine's preview cascades in the game
    (r.Shadow.UnbuiltWholeSceneDynamicShadowRadius 200000, r.Shadow.UnbuiltNumWholeSceneDynamic-
    ShadowCascades 4, DirectionalLightComponent.cpp). The sun takes those same numbers."""
    distance_cm = built_default("SUN_SHADOW_DISTANCE_CM")
    assert distance_cm == 200000.0
    assert built_default("SUN_SHADOW_CASCADES") == 4
    camera_m = 246.2  # hq_scene.json camera location_m[1]; the facade stands at y = 0
    backdrop_m = 90.0  # build_hq_scene.py sky_backdrop depth behind the facade
    assert distance_cm / 100.0 > camera_m + backdrop_m


def test_the_sun_curve_meets_todays_key_light_where_that_light_stands():
    # SunDusk: 2.5 at 8 deg above the horizon (build_hq_scene.py dusk_environment)
    p = scene_params(world(elevation=8.0, azimuth=264.0), FRAME)
    assert p["sun"]["intensity"] == pytest.approx(LIVE["sun_intensity"], abs=1e-9)
    noon = scene_params(world(elevation=47.4, azimuth=180.0), FRAME)["sun"]["intensity"]
    assert 4.0 < noon < 12.0  # brighter at noon on the relative scale, exposure fixed (D2)
    low = scene_params(world(elevation=0.5, azimuth=270.0), FRAME)["sun"]["intensity"]
    assert 0.0 < low < 0.5  # it fades into the horizon, it does not switch


def test_todays_sun_direction_maps_to_todays_rotation():
    # SunDusk travels along scene (0.9, 0.43, -sin 8 deg): the sun at 8 deg, azimuth 244.5 (D1)
    travel = (0.9, 0.43, -math.sin(math.radians(8.0)))
    horizontal = math.hypot(travel[0], travel[1])
    elevation = math.degrees(math.atan2(-travel[2], horizontal))
    azimuth = (math.degrees(math.atan2(-travel[0], -travel[1]))) % 360.0
    rotation = sun_rotation(Sun(elevation, azimuth), FRAME)
    assert rotation["Pitch"] == pytest.approx(LIVE["sun_rotation"]["Pitch"], abs=0.01)
    assert rotation["Yaw"] == pytest.approx(LIVE["sun_rotation"]["Yaw"], abs=0.01)
    assert rotation["Roll"] == 0.0


def test_the_evening_sun_is_on_the_left_and_the_morning_sun_on_the_right():
    # the light travels towards +x (screen right) in the evening: it comes from the left
    evening = sun_rotation(Sun(10.0, 270.0), FRAME)
    morning = sun_rotation(Sun(10.0, 90.0), FRAME)
    assert abs(evening["Yaw"]) < 1.0  # travelling along Unreal +x = scene +x
    assert abs(abs(morning["Yaw"]) - 180.0) < 1.0
    # at noon the sun is behind the viewer (south): the light travels into the scene, scene +y
    noon = sun_rotation(Sun(45.0, 180.0), FRAME)
    assert noon["Yaw"] == pytest.approx(-90.0, abs=0.01)
    assert noon["Pitch"] == pytest.approx(-45.0, abs=0.01)


def test_no_frame_no_rotation():
    assert scene_params(REFERENCE, None)["sun"]["rotation"] is None


# ---------------------------------------------------------------- by the hour
def test_the_lights_switch_on_below_minus_two_degrees():
    for elevation, on in ((-1.9, 0.0), (-2.1, 1.0), (10.0, 0.0), (-30.0, 1.0)):
        lights = scene_params(world(elevation=elevation), FRAME)["lights"]
        assert set(lights.values()) == {on}, elevation


def test_the_plates_blend_between_the_two_neighbouring_cells():
    p = scene_params(world(elevation=1.5, azimuth=270.0), FRAME)["sky"]
    assert ATLAS_ELEVATIONS[p["PlateA"]] == 0.0 and ATLAS_ELEVATIONS[p["PlateB"]] == 3.0
    assert 0.0 < p["PlateBlend"] < 1.0
    # at a cell, that cell alone
    at_cell = scene_params(world(elevation=8.0, azimuth=270.0), FRAME)["sky"]
    assert ATLAS_ELEVATIONS[at_cell["PlateA"]] == 8.0 and at_cell["PlateBlend"] == 0.0
    # beyond the ends, the end cell
    deep = scene_params(world(elevation=-40.0, azimuth=0.0), FRAME)["sky"]
    assert deep["PlateA"] == deep["PlateB"] == 0 and deep["PlateBlend"] == 0.0
    high = scene_params(world(elevation=60.0, azimuth=180.0), FRAME)["sky"]
    assert high["PlateA"] == high["PlateB"] == len(ATLAS_ELEVATIONS) - 1


def test_the_blend_follows_the_elevation_monotonically_within_a_pair():
    blends = [
        scene_params(world(elevation=e, azimuth=270.0), FRAME)["sky"]["PlateBlend"]
        for e in (0.25, 0.75, 1.5, 2.25, 2.9)
    ]
    assert blends == sorted(blends)


def test_the_morning_glow_is_mirrored_to_the_right():
    assert scene_params(world(elevation=-2.5, azimuth=85.0), FRAME)["sky"]["Mirror"] == 1.0
    assert scene_params(world(elevation=-2.5, azimuth=275.0), FRAME)["sky"]["Mirror"] == 0.0


def test_by_day_the_city_dims_the_windows_show_day_and_the_haze_turns_pale():
    p = scene_params(world(elevation=40.0, azimuth=180.0, weather_value=weather()), FRAME)
    assert p["emissive_factor"]["skyline"] == pytest.approx(0.06)
    assert p["window_view"]["DayBlend"] == 1.0
    # Blender's day variant: haze #a9c0e2 at strength 0.7 (build_hq.py daytime)
    assert p["haze"]["SkylineHaze_near_left"]["HazeColor"] == pytest.approx(
        (0.7 * 0.3967552, 0.7 * 0.5271151, 0.7 * 0.7605245), abs=1e-4
    )
    assert p["sun"]["intensity"] > 2.5


def test_at_night_the_dusk_city_holds_and_the_sky_light_falls():
    night = scene_params(world(elevation=-30.0, azimuth=0.0), FRAME)
    assert night["emissive_factor"] == {"skyline": 1.0, "near_blocks": 1.0}
    assert night["sun"]["intensity"] == 0.0
    assert night["sky_light"]["intensity"] < 0.6
    assert max(night["fog"]["inscattering"]) < 0.55


# ---------------------------------------------------------------- the twilight key
def test_the_evening_key_lights_from_the_left_the_morning_key_from_the_right():
    evening = scene_params(world(elevation=-2.5, azimuth=274.3), FRAME)["twilight"]
    morning = scene_params(world(elevation=-2.5, azimuth=85.4), FRAME)["twilight"]
    assert evening["evening"]["intensity"] == 2.5 and evening["morning"]["intensity"] == 0.0
    assert morning["morning"]["intensity"] == 2.5 and morning["evening"]["intensity"] == 0.0
    # the mirror of the reference: the same colour on the other side
    assert morning["morning"]["color"] == evening["evening"]["color"]


def test_the_key_is_on_the_same_side_as_the_skys_glow():
    for azimuth in (60.0, 95.0, 179.9, 180.0, 250.0, 300.0):
        p = scene_params(world(elevation=-1.0, azimuth=azimuth), FRAME)
        lit = "morning" if p["sky"]["Mirror"] == 1.0 else "evening"
        dark = "evening" if lit == "morning" else "morning"
        assert p["twilight"][lit]["intensity"] > 0.0, azimuth
        assert p["twilight"][dark]["intensity"] == 0.0, azimuth


@pytest.mark.parametrize("elevation", [-6.0, -6.5, -9.0, -12.0, -18.0, -40.0])
def test_both_keys_are_dark_once_civil_twilight_is_over(elevation):
    assert TWILIGHT_END_ELEVATION == -6.0
    for azimuth in (80.0, 280.0):
        t = scene_params(world(elevation=elevation, azimuth=azimuth), FRAME)["twilight"]
        assert t["evening"]["intensity"] == 0.0 and t["morning"]["intensity"] == 0.0


@pytest.mark.parametrize("elevation", [6.0, 10.0, 20.9, 35.0, 46.97])
def test_both_keys_are_dark_in_full_day(elevation):
    for azimuth in (109.6, 180.0, 250.0):
        t = scene_params(world(elevation=elevation, azimuth=azimuth), FRAME)["twilight"]
        assert t["evening"]["intensity"] == 0.0 and t["morning"]["intensity"] == 0.0


def test_the_key_fades_with_the_real_depression_and_hands_over_to_the_sun():
    # below the reference it only fades, to nothing at -6 deg
    below = [twilight_intensity(e) for e in (-2.5, -3.0, -4.0, -5.0, -5.9, -6.0)]
    assert below == sorted(below, reverse=True)
    assert below[0] == 2.5 and below[-1] == 0.0 and 0.0 < below[-2] < 0.1
    # between the reference and full day the key yields as the sun takes over
    assert twilight_intensity(0.0) > 0.0 and twilight_intensity(3.0) > 0.0
    assert twilight_intensity(3.0) < twilight_intensity(0.0)
    assert twilight_intensity(5.9) < 0.1
    # it is a fade, never a switch: no step between neighbouring hundredths of a degree
    steps = [twilight_intensity(-7.0 + i * 0.01) for i in range(1400)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False)) < 0.02


def test_the_keys_colour_follows_the_depression_from_todays_colour():
    ref = twilight_colour(-2.5)
    assert ref == (1.0, 0.62, 0.38)
    deeper = twilight_colour(-5.0)
    # deeper in twilight the arch over the sunset cools: more blue against red than at the reference
    assert deeper[2] / deeper[0] > ref[2] / ref[0]
    assert max(deeper) == pytest.approx(1.0)
    for e in (-6.0, -4.0, -1.0, 0.0, 3.0, 6.0):
        assert all(0.0 <= c <= 1.0 for c in twilight_colour(e)), e


def test_the_direct_sun_is_lit_only_above_the_horizon():
    for elevation in (-0.01, -0.833, -2.5, -6.0, -30.0):
        assert scene_params(world(elevation=elevation), FRAME)["sun"]["intensity"] == 0.0
    for elevation in (0.1, 3.0, 20.9, 46.97):
        p = scene_params(world(elevation=elevation, azimuth=180.0), FRAME)
        assert p["sun"]["intensity"] > 0.0, elevation


def test_a_morning_at_the_reference_elevation_is_the_mirror_of_the_evening():
    evening = scene_params(world(elevation=-2.5, azimuth=274.3, weather_value=weather()), FRAME)
    morning = scene_params(world(elevation=-2.5, azimuth=85.4, weather_value=weather()), FRAME)
    assert morning["twilight"]["morning"] == evening["twilight"]["evening"]
    assert morning["sun"]["intensity"] == evening["sun"]["intensity"] == 0.0
    assert morning["sky"]["Mirror"] == 1.0 and evening["sky"]["Mirror"] == 0.0


# ---------------------------------------------------------------- the room window views
def test_the_window_view_is_dusk_at_the_reference_day_by_day_and_never_dusk_at_night():
    assert scene_params(REFERENCE, FRAME)["window_view"] == {"DayBlend": 0.0, "NightBlend": 0.0}
    noon = scene_params(world(elevation=46.97, azimuth=180.0), FRAME)["window_view"]
    assert noon == {"DayBlend": 1.0, "NightBlend": 0.0}
    for elevation in (-12.0, -18.0, -22.9):
        night = scene_params(world(elevation=elevation, azimuth=330.0), FRAME)["window_view"]
        assert night == {"DayBlend": 0.0, "NightBlend": 1.0}, elevation
    # between the reference and -12 the dusk picture gives way; day and night never mix
    for elevation in (-4.0, -8.0, 1.0, 4.0):
        v = scene_params(world(elevation=elevation), FRAME)["window_view"]
        assert v["DayBlend"] == 0.0 or v["NightBlend"] == 0.0


# ---------------------------------------------------------------- the road, from real rain only
def test_a_dry_road_when_no_rain_fell():
    p = scene_params(world(weather_value=weather(precip_last_3h_mm=0.0)), FRAME)["road"]
    assert (p["Roughness Min"], p["Roughness Max"]) == DRY_ROAD_ROUGHNESS
    assert p["wetness"] == 0.0


def test_rain_now_wets_the_road():
    w = weather(rain_mm=0.2, precip_last_3h_mm=0.0, precipitation_mm=0.2)
    assert scene_params(world(weather_value=w), FRAME)["road"]["wetness"] == 1.0


def test_no_weather_keeps_todays_road_and_says_why():
    p = scene_params(world(weather_value=None, reason="not_configured"), FRAME)
    assert p["road"]["Roughness Min"] == 0.14 and p["road"]["Roughness Max"] == 0.38
    assert p["road"]["wetness"] is None and p["road"]["source"] == "unavailable"
    assert "nu este disponibil" in p["weather_note"]


def test_an_unknown_rain_history_on_a_dry_hour_is_not_called_dry():
    w = weather(precip_last_3h_mm=None)
    p = scene_params(world(weather_value=w), FRAME)["road"]
    assert p["wetness"] is None and p["source"] == "unknown"
    assert (p["Roughness Min"], p["Roughness Max"]) == (0.14, 0.38)


# ---------------------------------------------------------------- the clock
def test_the_clock_offset_puts_game_time_on_the_wall_clock():
    assert clock_offset_s(19 * 3600 + 31 * 60, 125.0) == 19 * 3600 + 31 * 60 - 125.0
    # kept inside one day, so the material's float stays precise
    assert clock_offset_s(10.0, 100000.0) == pytest.approx((10.0 - 100000.0) % 86400.0)
    p = scene_params(REFERENCE, FRAME, game_time_s=125.0)
    assert p["clock"]["ClockOffsetS"] == 19 * 3600 + 31 * 60 - 125.0
    assert scene_params(REFERENCE, FRAME)["clock"]["ClockOffsetS"] is None


def test_the_function_is_pure():
    assert scene_params(REFERENCE, FRAME, game_time_s=5.0) == scene_params(
        REFERENCE, FRAME, game_time_s=5.0
    )
