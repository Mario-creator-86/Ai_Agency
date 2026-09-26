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

import ast
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.office.scene_params import (
    ATLAS_ELEVATIONS,
    CITY_DAY_EMISSION,
    DAWN_CITY_WINDOWS,
    DRY_ROAD_ROUGHNESS,
    FILL_BUILT_SRGB8,
    FILL_SUN_EQUIVALENT,
    FILL_WARM_RISE,
    GOLDEN_HANDOVER,
    GOLDEN_KEY_INTENSITY,
    OVERCAST_CLEAR_FROM,
    OVERCAST_PLATES,
    RAIN_ROAD_ROUGHNESS,
    SKY_GAIN,
    SUN_DUSK_COLOR,
    TWILIGHT_END_ELEVATION,
    WALK_WASH_MAX,
    WET_ROAD_ROUGHNESS,
    WINDOWS_FEW,
    WINDOWS_OFF_ABOVE,
    SceneFrame,
    clear_facade,
    clear_fill,
    clock_offset_s,
    cloudiness,
    dawn_plate_elevation,
    day_weight,
    deck_fill,
    facade_factor,
    fill_colours,
    fill_factor,
    key_colour,
    key_intensity,
    overcast_weight,
    precipitating,
    scene_params,
    sun_colour,
    sun_ground_share,
    sun_intensity,
    sun_rotation,
    tower_windows_share,
    twilight_colour,
    twilight_intensity,
    windows_on,
    windows_share,
)
from app.office.world import Sun, Weather, WorldState

ROOT = Path(__file__).resolve().parents[1]
UNREAL = ROOT / "art-source" / "unreal"


@pytest.fixture
def weather_look(monkeypatch):
    """The weather's look is held in the shipped scene (WEATHER_LOOK, 2026-09-24); its rules are
    still tested as written, with the look switched on."""
    import app.office.scene_params as sp

    monkeypatch.setattr(sp, "WEATHER_LOOK", True)


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
        "facade": 1.0,
        "walk_wash": 1.0,
        "car_lights": 1.0,
    }
    # the fills' colours as built: look_hq_live.py's LinearColor, stored as the FColor bytes the
    # running level answered over Remote Control (2026-09-24), within UE's one sRGB step
    look_colours = {
        "StreetFill": r"STREET_FILL_COLOR = unreal\.LinearColor\(([\d., ]+), 1\.0\)",
        "WalkWash": r"WALK_WASH_COLOR = unreal\.LinearColor\(([\d., ]+), 1\.0\)",
        "FacadeLight": r"comp\.set_light_color\(unreal\.LinearColor\(([\d., ]+), 1\.0\)\)",
    }
    look_source = (UNREAL / "look_hq_live.py").read_text(encoding="utf-8")
    assert set(p["fill_colors"]) == set(FILL_BUILT_SRGB8) == set(look_colours)
    for label, pattern in look_colours.items():
        match = re.search(pattern, look_source)
        assert match, label
        built_linear = floats(match.group(1))
        for ours, byte, lin in zip(
            p["fill_colors"][label], FILL_BUILT_SRGB8[label], built_linear, strict=True
        ):
            assert abs(srgb8(lin) - byte) <= 1, label
            assert abs(srgb8(ours) - byte) <= 1, label

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
        "fill_colors",
        "sky",
        "emissive_factor",
        "window_view",
        "near_blocks_day",
        "towers",
        "trees",
        "skyline_day",
        "emissive_factor_counted",
        "haze",
        "fog",
        "road",
        "exposure",
        "clock",
        "weather_note",
    }
    # the day state (art-source/unreal/towers_day): every new value at the default the in-place
    # passes build into their materials, so the approved dusk cannot move when the backend sends
    # them. M_HQ_TowerDay: TowerDaylight 0 and WindowsOn 1 (towers_day_hq_live.py ADDED_SCALARS);
    # M_HQ_TreeLeaves: LeafDaylight 0 (trees_day_hq_live.py); the skyline's M_HQ_CityDay slots:
    # Daylight 0 (look_hq_live.py, as the near blocks' above); the counted glow is today's.
    towers_pass = (UNREAL / "towers_day" / "towers_day_hq_live.py").read_text(encoding="utf-8")
    added = re.search(r"^ADDED_SCALARS = (\{.*?\})\n", towers_pass, re.MULTILINE | re.DOTALL)
    assert added, "ADDED_SCALARS not found in towers_day_hq_live.py"
    scalars = ast.literal_eval(added.group(1))
    assert p["towers"] == {
        "TowerDaylight": scalars["TowerDaylight"],
        "WindowsOn": scalars["WindowsOn"],
    }
    assert p["towers"] == {"TowerDaylight": 0.0, "WindowsOn": 1.0}
    trees_pass = (UNREAL / "towers_day" / "trees_day_hq_live.py").read_text(encoding="utf-8")
    assert re.search(
        r'"parameter_name", "LeafDaylight"\)\s*\n\s*daylight\.set_editor_property\('
        r'"default_value", 0\.0\)',
        trees_pass,
    )
    assert p["trees"] == {"LeafDaylight": 0.0}
    assert p["skyline_day"] == {"Daylight": 0.0}
    assert p["emissive_factor_counted"] == p["emissive_factor"]

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
        switched = {k: v for k, v in lights.items() if k not in ("fills", "facade", "walk_wash")}
        assert set(switched.values()) == {on}, elevation
        # the fills are the sky's light on the street and the facade: on with the lamps, and above
        # them the sky's
        assert lights["fills"] == fill_factor(elevation), elevation
        assert lights["facade"] == facade_factor(elevation), elevation
        assert lights["facade"] >= on, elevation
        # StreetFill comes up with the lamps as a fade: at its build level by the reference
        if elevation <= -2.5:
            assert lights["fills"] == 1.0, elevation
        assert lights["walk_wash"] == min(WALK_WASH_MAX, lights["fills"]), elevation


# ---------------------------------------------------------------- the golden hour (wave 3)
def test_the_facade_fill_follows_the_sky_and_never_switches():
    """FacadeLight stands in for the sky's light on the facade: 1 at the reference, a peak around
    sunset, lower through the golden hour where the key and the sun take the facade, handed to the
    direct sun by noon (noon as before), and never a step. (Until round 3 of wave 3 it drove
    StreetFill too; the street's own curve is below.)"""
    assert facade_factor(-2.5) == 1.0 and clear_facade(-2.5) == 1.0
    assert facade_factor(-0.7) > 1.5  # the facade at sunset brighter than under the lamps
    assert facade_factor(45.0) == 0.0 == facade_factor(60.0)  # noon: the Movable sun lights it
    for night in (-6.0, -12.0, -30.0):
        assert facade_factor(night) == 1.0  # on with the lamps, as before
    steps = [facade_factor(-8.0 + i * 0.01) for i in range(6000)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False)) < 0.02
    # the reference to the sunset's peak only rises; noon's side only falls from +11.9 deg (17:58;
    # at +7.1 the key at its full golden strength carries the facade, and the fill is lower there
    # so the building keeps its evening order)
    rising = [facade_factor(-2.5 + i * 0.01) for i in range(181)]
    assert rising == sorted(rising)
    falling = [facade_factor(11.9 + i * 0.01) for i in range(3311)]
    assert falling == sorted(falling, reverse=True)
    assert facade_factor(7.1) < facade_factor(11.9) < facade_factor(2.7)
    # lower than wave 3 step 1's log-of-lux curve through the golden hour (2.14 to 2.25)
    assert max(facade_factor(e) for e in (2.7, 6.0, 10.0)) < 1.9


def test_the_front_ground_is_never_lit_brighter_than_under_the_noon_sun():
    """StreetFill (the road and the front pavement) is held on the noon's budget from noon down to
    the lamps (wave 3, round 3): the art director measured the front pavement at 105-115 of 255
    from 17:45 to 19:09 against the noon sun's 70.7, the physical inversion the Owner sees at fit
    zoom. The street's fill never rises above its build level (the lamps' dusk), never above the
    facade's, darkens toward the lamps and never switches; the evening's warmth is the fills' hue
    (test_the_fills_warm_...), not their strength."""
    assert fill_factor(-2.5) == 1.0 == fill_factor(-6.0)
    assert fill_factor(45.0) == 0.0 == fill_factor(60.0)
    day = [-1.99 + i * 0.01 for i in range(4700)]  # -2 .. +45 deg
    assert max(fill_factor(e) for e in day) <= 1.0
    for e in day:
        assert fill_factor(e) <= facade_factor(e) + 1e-12, e
    # the evening darkens toward the lamps: from the golden hour's +2.7 deg down to -2 it only falls
    evening = [fill_factor(2.7 - i * 0.01) for i in range(470)]
    assert evening == sorted(evening, reverse=True)
    assert max(fill_factor(e) for e in day) < 0.75
    # with the lamps it comes up to its build level between -2 and -2.5 deg (about three minutes
    # of the real sun): a fade, never a switch
    steps = [fill_factor(-8.0 + i * 0.01) for i in range(6000)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False)) < 0.03


def test_the_shopfronts_spill_never_rises_with_the_sky(weather_look):
    """WalkWash is the shopfronts' warm spill: at its build level with the lamps, with the street's
    fill below that, never above it (at 2.25x the pavement glowed brighter than under the noon
    sun)."""
    for e in (-30.0, -2.5):
        p = scene_params(world(elevation=e, azimuth=266.0, weather_value=weather()), FRAME)
        assert p["lights"]["walk_wash"] == 1.0, e
    for e in (-0.7, 2.7, 6.0, 10.0, 14.0):
        p = scene_params(world(elevation=e, azimuth=266.0, weather_value=weather()), FRAME)
        lights = p["lights"]
        assert lights["walk_wash"] == min(WALK_WASH_MAX, lights["fills"]) <= 1.0, e
    noon = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=weather()), FRAME)
    assert noon["lights"]["walk_wash"] == 0.0
    grey = weather(cloud_cover=100.0, precip_last_3h_mm=0.0)
    under = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=grey), FRAME)
    assert 0.0 < under["lights"]["walk_wash"] == under["lights"]["fills"] < WALK_WASH_MAX


def test_the_key_carries_the_low_sun_and_the_evening_falls_monotonically():
    """From +10 deg down to the end of civil twilight the key on the sun's side only falls, and
    with the Movable sun it leaves no hole at the crossover (the "power cut" of 2026-09-24: 18:50
    darker than 19:19)."""
    assert key_intensity(-2.5) == 2.5
    elevations = [-6.0 + i * 0.01 for i in range(1601)]  # -6 .. +10 deg
    evening = [key_intensity(e) for e in elevations]
    assert evening == sorted(evening)
    lit = [key_intensity(e) + sun_intensity(e) for e in elevations]
    assert lit == sorted(lit)
    assert key_intensity(2.7) > 2.0 * key_intensity(-2.5)  # 18:50 well above 19:19
    assert key_intensity(1.0) == GOLDEN_KEY_INTENSITY
    assert key_intensity(10.0) == GOLDEN_KEY_INTENSITY
    # handed to the Movable sun between +10 and +20, as a fade
    assert key_intensity(GOLDEN_HANDOVER[1]) == 0.0
    assert 0.0 < key_intensity(15.0) < GOLDEN_KEY_INTENSITY
    steps = [key_intensity(-7.0 + i * 0.01) for i in range(3000)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False)) < 0.02


def test_the_low_sun_warms_toward_amber():
    def blue_over_red(c):
        return c[2] / c[0]  # less blue against red is warmer

    assert key_colour(-2.5) == SUN_DUSK_COLOR and sun_colour(-2.5) == SUN_DUSK_COLOR
    for e in (0.5, 1.0, 2.7):
        assert blue_over_red(key_colour(e)) < 0.5 * blue_over_red(SUN_DUSK_COLOR), e
        assert sun_colour(e) == key_colour(e), e
    # back to SunDusk's colour at its own 8 deg, where the sun's day curve starts
    assert sun_colour(8.0) == SUN_DUSK_COLOR
    assert blue_over_red(sun_colour(45.0)) > blue_over_red(SUN_DUSK_COLOR)


def test_the_golden_hour_air_is_warm_and_the_day_air_blue():
    golden = scene_params(world(elevation=2.7, azimuth=266.0, weather_value=weather()), FRAME)
    fog = golden["fog"]["inscattering"]
    assert fog[0] > fog[2]  # a warm veil, not the day's blue
    noon = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=weather()), FRAME)
    assert noon["fog"]["inscattering"][2] > noon["fog"]["inscattering"][0]


def test_the_fills_warm_with_the_key_in_the_golden_hour_and_are_as_built_outside_it():
    """The street's and the facade's fills are cool as built (the dusk sky's ambient); under the
    golden hour's key they read lavender. Between about +10 and -2 deg they take the key's hue at
    their own luminance, and outside that window they are exactly as built."""

    def blue_over_red(c):
        return c[2] / c[0]

    built = fill_colours(-2.5)
    for e in (-1.0, -1.5, -2.5, -6.0, -30.0, 12.0, 20.0, 45.0):
        assert fill_colours(e) == built, e
    for e in (1.0, 2.7, 6.0):
        warm = fill_colours(e)
        for label in ("StreetFill", "FacadeLight"):
            assert blue_over_red(warm[label]) < 0.7 * blue_over_red(built[label]), (e, label)
            assert blue_over_red(warm[label]) > blue_over_red(key_colour(e)), (e, label)
        assert all(0.0 <= c <= 1.0 for colour in warm.values() for c in colour), e
    # half-way out at +10, gone by +12; the dawn's are cooler than the dusk's
    assert blue_over_red(built["StreetFill"]) > blue_over_red(fill_colours(10.0)["StreetFill"])
    dusk = fill_colours(2.7, morning=False)["StreetFill"]
    dawn = fill_colours(2.7, morning=True)["StreetFill"]
    assert blue_over_red(dawn) > blue_over_red(dusk)
    # under a closed deck no low sun gets through: as built
    assert fill_colours(2.7, overcast=1.0) == built


def test_no_fill_is_sun_coloured_after_sunset():
    """The warm fill at 19:09 (-0.7 deg) gave the brightest pavement of the day (art director,
    round 2). After sunset the street's light is the lamps' and the blue hour's: the fills' hue is
    back to its build colour by -1 deg, and warms only as the sun rises toward +1."""
    assert FILL_WARM_RISE == (-1.0, 1.0)
    built = fill_colours(-2.5)
    for e in (-1.0, -1.2, -1.9, -2.0):
        assert fill_colours(e) == built, e
        assert fill_colours(e, morning=True) == built, e

    def blue_over_red(c):
        return c[2] / c[0]

    near_sunset = fill_colours(-0.7)["StreetFill"]
    golden = fill_colours(2.7)["StreetFill"]
    assert blue_over_red(near_sunset) > blue_over_red(golden)  # mostly as built by 19:09
    # the plan carries them, one per fill
    p = scene_params(world(elevation=2.7, azimuth=266.0, weather_value=weather()), FRAME)
    assert p["fill_colors"] == fill_colours(2.7)


def test_the_measured_evening_order_holds_in_the_plan():
    """The instants measured on the stream (2026-09-24): +10, +6, +2.7, sunset (-0.71 at 19:09),
    -2.5, -6.2. The key and the sun (the facade's light) fall in that order; the fills (the
    street's) stay above the lamp-lit dusk's at sunset."""
    order = (10.0, 6.0, 2.7, -0.71, -2.5, -6.2)
    keys = [key_intensity(e) + sun_intensity(e) for e in order]
    assert keys == sorted(keys, reverse=True)
    assert facade_factor(-0.71) > facade_factor(-2.5)
    # the street's ground darkens into the dusk, under the lamps' level until they come on
    ground = [fill_factor(e) for e in (2.7, -0.71, -1.99)]
    assert ground == sorted(ground, reverse=True) and ground[0] <= fill_factor(-2.5)


# ---------------------------------------------------------------- morning is not evening
def test_the_dawn_is_cooler_than_the_dusk():
    dusk = scene_params(world(elevation=-2.5, azimuth=271.5, weather_value=weather()), FRAME)
    dawn = scene_params(world(elevation=-2.5, azimuth=88.1, weather_value=weather()), FRAME)
    k_dusk, k_dawn = dusk["twilight"]["evening"], dawn["twilight"]["morning"]
    assert k_dawn["intensity"] == k_dusk["intensity"]
    assert k_dawn["color"][2] / k_dawn["color"][0] > k_dusk["color"][2] / k_dusk["color"][0]
    # the dawn's plate is a deeper sun's: a thinner, bluer glow
    a, b, t = (dawn["sky"][k] for k in ("PlateA", "PlateB", "PlateBlend"))
    assert a + t * (b - a) < ATLAS_ELEVATIONS.index(-2.5)
    assert dawn_plate_elevation(-2.5) < -2.5 and dawn_plate_elevation(5.0) == 5.0
    ramp = [dawn_plate_elevation(-10.0 + i * 0.01) for i in range(2000)]
    assert ramp == sorted(ramp)  # it only rises: the dawn's sky never jumps back


def test_fewer_city_windows_are_lit_at_dawn_than_at_dusk():
    dusk = scene_params(world(elevation=-2.5, azimuth=271.5), FRAME)["emissive_factor"]
    dawn = scene_params(world(elevation=-2.5, azimuth=88.1), FRAME)["emissive_factor"]
    assert dusk["skyline"] == 1.0
    assert dawn["skyline"] == pytest.approx(DAWN_CITY_WINDOWS)
    assert dawn["near_blocks"] == dawn["skyline"]
    # continuous at solar midnight, where the side flips: both at the night's full city
    before = scene_params(world(elevation=-44.0, azimuth=359.9), FRAME)["emissive_factor"]
    after = scene_params(world(elevation=-44.0, azimuth=0.1), FRAME)["emissive_factor"]
    assert before == after == {"skyline": 1.0, "near_blocks": 1.0}
    # the lamps' timing is the evening's
    assert scene_params(world(elevation=-2.1, azimuth=88.0), FRAME)["lights"]["lamps"] == 1.0
    assert scene_params(world(elevation=-1.9, azimuth=88.0), FRAME)["lights"]["lamps"] == 0.0


# ---------------------------------------------------------------- the real weather
def test_the_weather_reads_cloud_cover_first_then_the_condition(weather_look):
    assert cloudiness(None) == 0.0
    assert cloudiness(weather(cloud_cover=80.0, condition="clear")) == 0.8
    assert cloudiness(weather(cloud_cover=None, condition="cloudy")) == 0.9
    assert overcast_weight(weather(cloud_cover=100.0)) == 1.0
    assert overcast_weight(weather(cloud_cover=30.0)) == 0.0
    assert precipitating(weather(rain_mm=0.4)) and overcast_weight(weather(rain_mm=0.4)) == 1.0
    assert precipitating(weather(condition="rain", rain_mm=None, precipitation_mm=None))
    assert not precipitating(weather()) and not precipitating(None)


def test_overcast_dims_the_sun_greys_the_haze_and_thickens_the_air(weather_look):
    clear = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=weather()), FRAME)
    grey = scene_params(
        world(elevation=45.0, azimuth=180.0, weather_value=weather(cloud_cover=100.0)), FRAME
    )
    assert grey["sun"]["intensity"] < 0.3 * clear["sun"]["intensity"]
    assert grey["fog"]["density"] > clear["fog"]["density"]
    g_fog, c_fog = grey["fog"]["inscattering"], clear["fog"]["inscattering"]
    assert max(g_fog) - min(g_fog) < max(c_fog) - min(c_fog)
    for label, plane in grey["haze"].items():
        assert plane["Opacity"] > clear["haze"][label]["Opacity"]
        g, c = plane["HazeColor"], clear["haze"][label]["HazeColor"]
        assert max(g) - min(g) < 0.5 * (max(c) - min(c)), label  # the deck's grey, not blue


def test_the_overcast_sky_by_day_is_the_clear_hours_and_never_darker_or_bluer(weather_look):
    """The atlas has no grey deck: every day cell is blue, and wave 3 step 1's -8/+8 blend made the
    overcast noon darker and bluer than the clear one (112 against 154 of 255). By day the deck
    keeps the clear hour's plate, as before wave 3, at a gain a little higher than the clear sky's
    (its denser fog veils the plate); below +8 deg, where the clear cells carry the sunset's glow,
    it takes the glowless pair, meeting the clear plate at +8 exactly."""
    grey = weather(cloud_cover=100.0, precip_last_3h_mm=0.0)
    for e in (8.0, 15.0, 30.0, 45.0, 60.0):
        clear = scene_params(world(elevation=e, azimuth=200.0, weather_value=weather()), FRAME)
        deck = scene_params(world(elevation=e, azimuth=200.0, weather_value=grey), FRAME)
        for key in ("PlateA", "PlateB", "PlateBlend", "Mirror"):
            assert deck["sky"][key] == clear["sky"][key], (e, key)
        assert clear["sky"]["Gain"] < deck["sky"]["Gain"] <= 1.05 * clear["sky"]["Gain"] + 1e-12, e
    dusk = scene_params(world(elevation=-2.5, azimuth=271.0, weather_value=grey), FRAME)["sky"]
    assert (dusk["PlateA"], dusk["PlateB"]) == OVERCAST_PLATES
    assert dusk["Gain"] < SKY_GAIN  # a dimmer deck in the dusk
    for cell in OVERCAST_PLATES:  # never a cell with the sunset's glow in it
        assert ATLAS_ELEVATIONS[cell] not in (-5.0, -2.5, 0.0, 3.0)
    below = scene_params(world(elevation=7.99, azimuth=260.0, weather_value=grey), FRAME)["sky"]
    at = scene_params(world(elevation=8.0, azimuth=260.0, weather_value=grey), FRAME)["sky"]
    assert OVERCAST_CLEAR_FROM == 8.0
    assert ATLAS_ELEVATIONS[below["PlateB"]] == 8.0 and below["PlateBlend"] == pytest.approx(1.0)
    assert ATLAS_ELEVATIONS[at["PlateA"]] == 8.0 and at["PlateBlend"] == 0.0
    assert below["Gain"] == pytest.approx(at["Gain"])


def test_weather_never_lights_the_street_brighter_than_the_clear_day():
    """Under a closed deck the fills carry the street alone, at a share of the clear day's light at
    the same hour: the clear fills plus the sun's share at FILL_SUN_EQUIVALENT. Measured at 13:07:
    fills 1.0 under the deck put the front pavement at 87 against the clear noon's 70.6."""
    for i in range(0, 6001):
        e = -10.0 + i * 0.01
        for clear in (clear_fill, clear_facade):
            day_light = clear(e) + FILL_SUN_EQUIVALENT * sun_ground_share(e)
            assert deck_fill(e, clear) < day_light + 1e-12, e
        assert fill_factor(e, 1.0, raining=True) <= fill_factor(e, 1.0), e
        assert facade_factor(e, 1.0, raining=True) <= facade_factor(e, 1.0), e
    noon_deck = fill_factor(45.0, 1.0)
    assert 0.0 < noon_deck < 0.55  # 0.5 put the pavement at 63 and the road at 49 (13:07)
    # partly cloudy is the clear sky; a closed deck the deck's; between them a blend
    assert fill_factor(20.0, 0.0) == clear_fill(20.0)
    assert fill_factor(20.0, 1.0) == pytest.approx(deck_fill(20.0, clear_fill))
    assert facade_factor(20.0, 1.0) == pytest.approx(deck_fill(20.0, clear_facade))
    # the lamps still own the dusk and the night, whatever the sky
    for e in (-2.5, -6.0, -20.0):
        assert fill_factor(e, 1.0, raining=True) == 1.0


def test_rain_is_denser_and_darker_than_overcast_and_wets_the_road(weather_look):
    w_grey = weather(cloud_cover=100.0, precip_last_3h_mm=0.0)
    w_rain = weather(cloud_cover=100.0, rain_mm=1.2, precipitation_mm=1.2, condition="rain")
    grey = scene_params(world(elevation=-2.5, azimuth=271.0, weather_value=w_grey), FRAME)
    rain = scene_params(world(elevation=-2.5, azimuth=271.0, weather_value=w_rain), FRAME)
    assert rain["fog"]["density"] > grey["fog"]["density"]
    assert rain["sky"]["Gain"] < grey["sky"]["Gain"]
    assert rain["road"]["wetness"] == 1.0 and grey["road"]["wetness"] == 0.0
    # the dusk key thins under the deck
    assert grey["twilight"]["evening"]["intensity"] < 2.5
    # by day the rain's thicker deck and the wet road's film dim the street below the dry deck's
    noon_grey = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=w_grey), FRAME)
    noon_rain = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=w_rain), FRAME)
    assert noon_rain["lights"]["fills"] < noon_grey["lights"]["fills"]
    assert noon_rain["sky"]["Gain"] < noon_grey["sky"]["Gain"]


def test_under_the_deck_the_dome_lights_the_foliage_from_above(weather_look):
    """Under a closed deck the sky's dome is the main light, and it lights foliage from above: the
    planters' shrubs read 37 against the clear noon's 64 with the sun dimmed and the fills carrying
    the street (round 2), because the fills barely reach them. The sky light takes the dome's share
    by day under the deck (measured 2026-09-24 at 13:07: its intensity 1.28 -> 20 lifted the shrubs
    37 -> 49 and left the front pavement where it was); the fills give back what it adds on the
    ground. Rain's darker deck gives less. In the dusk and at night, where the lamps own the street,
    the sky light is the clear sky's, and at the reference exactly the build's."""
    w_grey = weather(cloud_cover=100.0, precip_last_3h_mm=0.0)
    w_rain = weather(cloud_cover=100.0, rain_mm=1.2, precipitation_mm=1.2, condition="rain")

    def sky(e, azimuth, w):
        p = scene_params(world(elevation=e, azimuth=azimuth, weather_value=w), FRAME)
        return p["sky_light"]

    clear, grey, rain = (sky(45.0, 180.0, w) for w in (weather(), w_grey, w_rain))
    assert grey["intensity"] > 12.0 * clear["intensity"]
    assert clear["intensity"] < rain["intensity"] < grey["intensity"]
    spread = max(clear["color"]) - min(clear["color"])
    assert max(grey["color"]) - min(grey["color"]) < 0.5 * spread  # the deck's neutral light
    for e in (-2.5, -6.0, -20.0):
        assert sky(e, 271.0, w_grey)["intensity"] == sky(e, 271.0, weather())["intensity"], e
    # the lift follows the day in, never a step
    steps = [sky(-3.0 + i * 0.05, 250.0, w_grey)["intensity"] for i in range(400)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:], strict=False)) < 0.5
    # under the deck the fills carry less of the street than round 2's 0.48 at noon
    assert fill_factor(45.0, 1.0) < 0.4


def test_unknown_weather_is_the_clear_sky_and_says_so():
    clear = scene_params(world(elevation=2.7, azimuth=266.0, weather_value=weather()), FRAME)
    none = scene_params(world(elevation=2.7, azimuth=266.0, reason="unreachable"), FRAME)
    for key in ("sun", "twilight", "sky", "fog", "haze", "lights", "emissive_factor"):
        assert none[key] == clear[key], key
    assert none["weather_note"] is not None and clear["weather_note"] is None


# ---------------------------------------------------------------- the night over a lit city
def test_the_night_sky_carries_the_citys_glow():
    dusk = scene_params(REFERENCE, FRAME)
    night = scene_params(world(elevation=-23.0, azimuth=293.0, weather_value=weather()), FRAME)
    assert dusk["sky"]["Gain"] == SKY_GAIN
    assert night["sky"]["Gain"] > 1.5 * SKY_GAIN
    haze = night["haze"]["SkylineHaze_near_left"]["HazeColor"]
    assert haze[0] > haze[2]  # a warm grey, not the dusk's lilac
    fog = night["fog"]["inscattering"]
    assert fog[0] > fog[2] and max(fog) < 0.55


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
    # the mirror of the reference in strength; the dawn's colour is cooler (wave 3)
    e_c, m_c = evening["evening"]["color"], morning["morning"]["color"]
    assert m_c[2] / m_c[0] > e_c[2] / e_c[0]


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


@pytest.mark.parametrize("elevation", [20.0, 20.9, 35.0, 46.97])
def test_both_keys_are_dark_in_full_day(elevation):
    # until wave 3 dark from +6 deg; the key now carries the low sun up to GOLDEN_HANDOVER
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
    # the same strength on the other side; the colour cools (test_the_dawn_is_cooler_than_...)
    m_key, e_key = morning["twilight"]["morning"], evening["twilight"]["evening"]
    assert m_key["intensity"] == e_key["intensity"]
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


def test_falling_rain_makes_the_road_a_traced_mirror(weather_look):
    """While rain falls the road carries a water film: below the post-process's
    LumenMaxRoughnessToTraceReflections (look_hq_live.py AMN_LOOK_TRACE_ROUGHNESS) across its whole
    range, and glossier than the build's damp road, so the lamps and the shopfronts lie on it in
    streaks (the look pass's 0.08-0.24, 2026-09-16, where the streaks first appeared). Rain in the
    last three hours alone is the build's damp road, as the reference is."""
    trace = float(default("look_hq_live.py", "AMN_LOOK_TRACE_ROUGHNESS"))
    assert WET_ROAD_ROUGHNESS == (0.14, 0.38)
    assert RAIN_ROAD_ROUGHNESS[1] < trace and RAIN_ROAD_ROUGHNESS[1] < WET_ROAD_ROUGHNESS[1]
    assert RAIN_ROAD_ROUGHNESS[0] < WET_ROAD_ROUGHNESS[0]
    falling = weather(rain_mm=0.8, precipitation_mm=0.8, condition="rain", cloud_cover=100.0)
    road = scene_params(world(elevation=45.0, azimuth=180.0, weather_value=falling), FRAME)["road"]
    assert (road["Roughness Min"], road["Roughness Max"]) == RAIN_ROAD_ROUGHNESS
    assert road["wetness"] == 1.0
    damp = scene_params(REFERENCE, FRAME)["road"]
    assert (damp["Roughness Min"], damp["Roughness Max"]) == WET_ROAD_ROUGHNESS


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


def test_the_weathers_look_is_held_so_a_grey_or_rainy_day_is_the_clear_skys_light():
    """Held on 2026-09-24 (WEATHER_LOOK): no atlas cell is a grey deck, so the look waits for one.
    A closed deck or falling rain then changes nothing but the road, which is wet from the real
    rain exactly as the committed scene made it."""
    clear = weather(cloud_cover=0.0, precip_last_3h_mm=0.0)
    deck = weather(condition="cloudy", cloud_cover=100.0, precip_last_3h_mm=0.0)
    rain = weather(condition="rain", cloud_cover=100.0, rain_mm=1.5, precip_last_3h_mm=2.0)
    for e, az in ((45.0, 180.0), (2.7, 266.0), (-2.5, 274.9)):
        base = scene_params(world(elevation=e, azimuth=az, weather_value=clear), FRAME)
        for grey in (deck, rain):
            p = scene_params(world(elevation=e, azimuth=az, weather_value=grey), FRAME)
            assert overcast_weight(grey) == 0.0
            assert {k: v for k, v in p.items() if k not in ("road", "weather")} == {
                k: v for k, v in base.items() if k not in ("road", "weather")
            }, (e, grey.condition)
        wet = scene_params(world(elevation=e, azimuth=az, weather_value=rain), FRAME)["road"]
        assert (wet["Roughness Min"], wet["Roughness Max"]) == WET_ROAD_ROUGHNESS


# ---------------------------------------------------------------- the towers, the trees by day
def towers(elevation: float, azimuth: float) -> dict[str, float]:
    return scene_params(world(elevation=elevation, azimuth=azimuth), FRAME)["towers"]


def test_the_towers_light_no_window_by_day_a_few_below_five_degrees_all_at_dusk():
    """The art director's reading of 2026-09-24: no lit window while the sun is up, only a few once
    it drops below about +5 deg, the dusk's every window from the reference down; the facades in
    their day colours by the same day weight as the rest of the city."""
    assert towers(46.97, 180.0) == {"TowerDaylight": 1.0, "WindowsOn": 0.0}  # a September noon
    assert towers(11.9, 250.0)["WindowsOn"] == 0.0  # 17:58
    assert towers(WINDOWS_OFF_ABOVE, 262.0)["WindowsOn"] == 0.0
    assert 0.0 < windows_share(2.7) < WINDOWS_FEW  # 18:50: a few
    assert 0.0 < towers(2.7, 266.0)["WindowsOn"] < windows_on(WINDOWS_FEW)
    assert windows_share(0.0) == WINDOWS_FEW
    assert towers(-2.5, 274.9) == {"TowerDaylight": 0.0, "WindowsOn": 1.0}  # the approved dusk
    assert towers(-30.0, 330.0) == {"TowerDaylight": 0.0, "WindowsOn": 1.0}
    assert towers(6.0, 260.0)["TowerDaylight"] == 1.0
    assert 0.0 < towers(2.7, 266.0)["TowerDaylight"] < 1.0
    # the evening only darkens: as the sun sinks the facades lose the day and windows come on
    evening = [towers(tenth / 10.0, 265.0) for tenth in range(500, -300, -1)]
    daylight = [t["TowerDaylight"] for t in evening]
    windows = [t["WindowsOn"] for t in evening]
    assert daylight == sorted(daylight, reverse=True)
    assert windows == sorted(windows)


def test_fewer_tower_windows_are_lit_at_dawn_than_at_dusk():
    """The city's dawn rule (DAWN_CITY_WINDOWS: offices empty, homes waking) counts the towers'
    windows once they can be counted: at the same elevation the morning lights fewer of them."""
    for tenth in range(-110, 50):
        e = tenth / 10.0
        dawn = tower_windows_share(Sun(elevation_deg=e, azimuth_deg=95.0))
        dusk = tower_windows_share(Sun(elevation_deg=e, azimuth_deg=265.0))
        assert dawn < dusk, e
    at_reference = tower_windows_share(Sun(elevation_deg=-2.5, azimuth_deg=88.1))
    assert at_reference == pytest.approx(DAWN_CITY_WINDOWS)
    assert towers(-2.5, 88.1)["WindowsOn"] == pytest.approx(windows_on(DAWN_CITY_WINDOWS))
    # the deep night and the day are the same on both sides; continuous at solar midnight
    assert towers(-44.0, 359.9) == towers(-44.0, 0.1) == {"TowerDaylight": 0.0, "WindowsOn": 1.0}
    assert towers(20.0, 110.0) == towers(20.0, 250.0)
    # the morning only brightens: windows go off and the facades come to day as the sun rises
    morning = [towers(tenth / 10.0, 95.0) for tenth in range(-300, 500)]
    assert [t["WindowsOn"] for t in morning] == sorted(
        (t["WindowsOn"] for t in morning), reverse=True
    )


def test_once_the_windows_are_counted_the_dawn_is_not_dimmed_twice():
    """Today the whole skyline's glow falls to DAWN_CITY_WINDOWS at dawn (EmissiveFactor), since no
    window could be switched off. Where the day state counts the windows (WindowsOn), the glow
    keeps only the day's dimming, so the dawn city is DAWN_CITY_WINDOWS of the dusk's, not its
    square. On the evening side the two are the same."""
    for e, az in ((-2.5, 274.9), (2.7, 266.0), (46.97, 180.0), (-30.0, 330.0), (-8.0, 290.0)):
        p = scene_params(world(elevation=e, azimuth=az), FRAME)
        assert p["emissive_factor_counted"] == p["emissive_factor"], e
    for e in (-10.0, -6.0, -2.5, 0.0, 3.0):
        p = scene_params(world(elevation=e, azimuth=95.0), FRAME)
        today = p["emissive_factor"]["skyline"]
        counted = p["emissive_factor_counted"]["skyline"]
        assert counted > today, e
        assert counted == pytest.approx(1.0 + (CITY_DAY_EMISSION - 1.0) * day_weight(e))
        assert p["emissive_factor_counted"]["near_blocks"] == counted
    p = scene_params(world(elevation=-6.0, azimuth=95.0), FRAME)
    assert p["emissive_factor"]["skyline"] == pytest.approx(DAWN_CITY_WINDOWS)
    assert p["emissive_factor_counted"]["skyline"] == 1.0


def test_the_trees_and_the_skylines_plain_slots_take_the_day_with_the_facades():
    for e, az in ((-30.0, 330.0), (-2.5, 274.9), (0.0, 268.0), (2.7, 266.0), (46.97, 180.0)):
        p = scene_params(world(elevation=e, azimuth=az), FRAME)
        day = day_weight(e)
        assert p["trees"] == {"LeafDaylight": day}
        assert p["skyline_day"] == {"Daylight": day}
        assert p["near_blocks_day"] == {"Daylight": day}
        assert p["towers"]["TowerDaylight"] == day
    assert scene_params(world(elevation=46.97, azimuth=180.0), FRAME)["trees"] == {
        "LeafDaylight": 1.0
    }


def test_the_day_state_follows_the_sun_only_while_the_weathers_look_is_held():
    clear = weather(cloud_cover=0.0, precip_last_3h_mm=0.0)
    rain = weather(condition="rain", cloud_cover=100.0, rain_mm=1.5, precip_last_3h_mm=2.0)
    for e, az in ((46.97, 180.0), (2.7, 266.0), (-2.5, 274.9)):
        a = scene_params(world(elevation=e, azimuth=az, weather_value=clear), FRAME)
        b = scene_params(world(elevation=e, azimuth=az, weather_value=rain), FRAME)
        for key in ("towers", "trees", "skyline_day", "emissive_factor_counted"):
            assert a[key] == b[key], (e, key)
