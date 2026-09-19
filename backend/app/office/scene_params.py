"""Every value the live headquarters takes, from the real world - one pure function.

``scene_params(world, frame, game_time_s)`` turns ``world.WorldState`` (the real clock, the real
sun, the real weather or why there is none) into the numbers the Unreal level is sent over
Remote Control (``unreal.py``'s environment pass). Nothing here reads a clock, a file or the
network, so every value can be tested against fixed instants with no Unreal running.

Two rules shape it:

* The approved dusk does not drift. At the reference instant (the sun at -2.5 deg, a clear sky,
  rain in the last three hours) every output is exactly the value the level is built with today
  (tests/test_scene_params.py reads them from the build scripts), every light included.
* After sunset the warm light on a facade comes from the still-bright twilight sky over the
  sunset, not from the sun, and that is how the dusk is lit. The level keeps the build's SunDusk
  (Stationary, from the front-left, 8 deg down, warm, 2.5) as the evening twilight key and its
  mirror SunDawn as the morning key; their direction is fixed, and only their intensity and colour
  follow the real solar depression on the real side of the sky, fading to nothing by the end of
  civil twilight (-6 deg). The real sun is a separate Movable light that turns to the real
  elevation and azimuth and carries direct light only while it is above the horizon. The rejected
  rebuild of 2026-09-19 had one sun doing both: at the real -2.5 deg it was 0, the warm key was
  gone and the reference moment scored 10.3 against the limit of 6.4.
* Nothing is invented. Where the look between two real states needs a shape (how fast the city's
  windows dim at sunrise, how blue the day haze is), the shape comes from the scene's own sources:
  the plate palette of ``frontend/src/hq_time.js`` and ``compose_sky_backdrop.py`` and the Blender
  day variant (``art-source/blender/hq/build_hq.py`` ``daytime``). The input is always the real
  sun and the real weather.

Owner decisions taken as proposed (2026-09-18, he did not object); each lives in one place:
D1 the viewer looks north and the facade faces south (``office_facade_heading_deg``, config);
D2 exposure is not written (``exposure`` is always None); D5 with no weather the sky is the clear
sky of the real hour and the road keeps today's values, and the page says so; D6 the sky is the
pre-built plate atlas below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.office.world import REFERENCE_DUSK_ELEVATION, Sun, Weather, WorldState

Vec3 = tuple[float, float, float]

# ---------------------------------------------------------------- today's build (the dusk)
#: build_hq_scene.py SKY_GAIN default (AMN_SKY_GAIN): the backdrop's gain since the look pass.
SKY_GAIN = 1.1
#: build_hq_scene.py SKYLIGHT (AMN_SKYLIGHT) and the live describe: 0.6, white, black below.
SKY_LIGHT_DUSK = 0.6
#: build_hq_scene.py SunDusk: 2.5, lighting from 8 deg above the horizon, LinearColor(1.0, 0.62,
#: 0.38) (live: FColor 255/206/166, Stationary). It is the evening twilight key at the reference
#: (TWILIGHT_KEY_*), and the direct sun's curve below passes through its 2.5 at its 8 deg, so a
#: real sun standing where SunDusk seems to stand gives the light the approved look gives.
SUN_KEY_ELEVATION = 8.0
SUN_KEY_INTENSITY = 2.5
SUN_DUSK_COLOR: Vec3 = (1.0, 0.62, 0.38)
#: build_hq_scene.py TWILIGHT_KEY_INTENSITY and TWILIGHT_KEY_COLOR: the twilight key at the
#: reference is SunDusk exactly.
TWILIGHT_KEY_INTENSITY = SUN_KEY_INTENSITY
TWILIGHT_KEY_COLOR: Vec3 = SUN_DUSK_COLOR
#: The end of civil twilight: with the sun this far below the horizon the sky over the sunset no
#: longer lights a facade (the ground illuminance is down to about 3 lux against about 400 at
#: sunset), so the key is dark from here down.
TWILIGHT_END_ELEVATION = -6.0
#: look_hq_live.py AMN_LOOK_FOG and fog_inscattering_luminance (live: 0.008, 0.3/0.34/0.55).
FOG_DENSITY = 0.008
FOG_DUSK: Vec3 = (0.3, 0.34, 0.55)
#: haze_hq_live.py: AMN_HAZE_COLOR (left of the building), AMN_HAZE_COLOR_RIGHT, the near
#: plane's opacity AMN_HAZE_OPACITY and the far plane's share of it AMN_HAZE_FAR_SHARE.
HAZE_LEFT: Vec3 = (0.11, 0.10, 0.19)
HAZE_RIGHT: Vec3 = (0.16, 0.17, 0.26)
HAZE_OPACITY = 0.55
HAZE_FAR_SHARE = 0.7
#: look_hq_live.py AMN_LOOK_ROAD_ROUGH_MIN / _MAX on MI_HQ_AsphaltWet: today's wet road.
WET_ROAD_ROUGHNESS = (0.14, 0.38)
#: The same asphalt dry. No build has made a dry road yet, so this is the first estimate for
#: dry asphalt (roughness 0.6-0.9 in physically based libraries), to be judged by eye in the
#: rebuild window on a dry day; it is shown only when the real record says no rain fell.
DRY_ROAD_ROUGHNESS = (0.6, 0.9)

# ---------------------------------------------------------------- the day, from the scene's sources
#: Blender day variant (build_hq.py daytime): the city's glow materials at x0.06 (principled
#: emission; x0.08 on pure emission nodes, which the glTF export does not carry).
CITY_DAY_EMISSION = 0.06
#: Blender day variant: the haze turns #a9c0e2 at emission strength 0.7.
DAY_HAZE_SRGB = "#a9c0e2"
DAY_HAZE_STRENGTH = 0.7
#: Full day: the sun this high is past the golden hour's colour; the city's lamps and windows
#: are the dusk's at and below the reference elevation and the day's from here up.
DAY_FULL_ELEVATION = 6.0
#: Below this the street lamps, the shelter, the tree uplights, the fills and the cars' lights
#: are on (the plan: "on below about -2 deg"; photocells switch in civil twilight).
LIGHTS_ON_BELOW = -2.0
#: The sun's light is relative (exposure is fixed, D2): Meinel's clear-sky direct beam,
#: 0.7^(AM^0.678) with the Kasten-Young air mass, scaled to meet SunDusk's 2.5 at 8 deg.
SUN_COLOR_DAY_ELEVATION = 30.0
#: 5800 K (Helland's blackbody fit: sRGB 255, 243, 231), linear: the sun high in a clear sky.
SUN_COLOR_DAY: Vec3 = (1.0, 0.8963, 0.7991)

#: The sky atlas' cells, top to bottom (critic's corrected phase 1: compose at these elevations,
#: the -2.5 cell being today's plate). PlateA/PlateB are indices into this list.
ATLAS_ELEVATIONS: tuple[float, ...] = (-18.0, -12.0, -8.0, -5.0, -2.5, 0.0, 3.0, 8.0, 15.0, 35.0)

# hq_time.js SKY and skyStops positions, as compose_sky_backdrop.py composes them
SKY_STOPS = {
    "night": ("#070b1a", "#0f1630", "#1a2244", "#232a4a"),
    "dusk": ("#1b2644", "#3b4a7c", "#d0806c", "#7a5c70"),
    "day": ("#3f78c8", "#79a9e0", "#cfe2f3", "#b9cde2"),
}
STOP_POSITIONS = (0.0, 0.24, 0.4, 0.62)
#: compose_sky_backdrop.py: the plate's horizon row (HORIZON 350 of H 840), where the warm glow is
#: centred, and the glow's colour and opacity there (its radial "warm" layer, first stop).
PLATE_HORIZON_ROW = 350.0 / 840.0
PLATE_GLOW_SRGB: Vec3 = (250.0, 165.0, 115.0)
PLATE_GLOW_OPACITY = 0.85

HAZE_LABELS = (
    "SkylineHaze_near_left",
    "SkylineHaze_near_right",
    "SkylineHaze_far_left",
    "SkylineHaze_far_right",
)

WEATHER_NOTES = {
    "not_configured": "Vremea nu este disponibilă: niciun serviciu meteo nu este configurat.",
    "unreachable": "Vremea nu este disponibilă: serviciul meteo nu răspunde.",
    "rehearsal": "Repetiție: vremea reală a orei repetate nu este citită.",
}


@dataclass(frozen=True)
class SceneFrame:
    """The level's axes (Unreal vectors of the Blender scene's +x, +y, +z, measured by the build
    from the exporter's marker cubes and written to env_report.json) and the facade's heading.

    The plate camera looks along scene +y; D1 puts that towards north, so the facade (which
    faces the viewer) faces south: heading 180."""

    x: Vec3
    y: Vec3
    z: Vec3
    facade_heading_deg: float


# ---------------------------------------------------------------- small helpers
def smoothstep(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix3(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (mix(a[0], b[0], t), mix(a[1], b[1], t), mix(a[2], b[2], t))


def scale3(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def srgb_bytes(hex_colour: str) -> Vec3:
    h = hex_colour.lstrip("#")
    return (float(int(h[0:2], 16)), float(int(h[2:4], 16)), float(int(h[4:6], 16)))


def to_linear(byte: float) -> float:
    c = byte / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear3(srgb: Vec3) -> Vec3:
    return (to_linear(srgb[0]), to_linear(srgb[1]), to_linear(srgb[2]))


def normalised(c: Vec3) -> Vec3:
    top = max(c) or 1.0
    return (c[0] / top, c[1] / top, c[2] / top)


def luminance(c: Vec3) -> float:
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


# ---------------------------------------------------------------- compose's own elevation functions
def plate_daylight(elevation: float) -> float:
    """compose_sky_backdrop.py: daylight = smoothstep(-8, 7, elevation)."""
    return smoothstep(-8.0, 7.0, elevation)


def plate_dusk(elevation: float) -> float:
    """compose_sky_backdrop.py: dusk = exp(-((elevation - 1) / 6.5)^2)."""
    return math.exp(-(((elevation - 1.0) / 6.5) ** 2))


def plate_stops(elevation: float) -> list[Vec3]:
    """The sky gradient's four stops (sRGB bytes) as compose mixes them at ``elevation``."""
    daylight, dusk = plate_daylight(elevation), plate_dusk(elevation)
    stops = []
    for i in range(4):
        base = mix3(srgb_bytes(SKY_STOPS["night"][i]), srgb_bytes(SKY_STOPS["day"][i]), daylight)
        stops.append(mix3(base, srgb_bytes(SKY_STOPS["dusk"][i]), min(1.0, dusk * 0.95)))
    return stops


def gradient_at(stops: list[Vec3], row: float) -> Vec3:
    """The plate's gradient (sRGB bytes) at ``row`` (0 top, 1 bottom), as compose fills it."""
    for i in range(3):
        if STOP_POSITIONS[i] <= row <= STOP_POSITIONS[i + 1]:
            t = (row - STOP_POSITIONS[i]) / (STOP_POSITIONS[i + 1] - STOP_POSITIONS[i])
            return mix3(stops[i], stops[i + 1], t)
    return stops[-1]


def plate_mean_linear(elevation: float, samples: int = 64) -> Vec3:
    """The plate gradient's mean colour, linear: how much light that sky gives."""
    stops = plate_stops(elevation)
    acc = [0.0, 0.0, 0.0]
    for j in range(samples):
        row = (j + 0.5) / samples
        lin = linear3(gradient_at(stops, row))
        for q in range(3):
            acc[q] += lin[q] / samples
    return (acc[0], acc[1], acc[2])


def sky_brightness(elevation: float) -> float:
    """The plate's light relative to the reference dusk's (1.0 at -2.5 deg)."""
    return luminance(plate_mean_linear(elevation)) / luminance(
        plate_mean_linear(REFERENCE_DUSK_ELEVATION)
    )


def day_weight(elevation: float) -> float:
    """0 at and below the reference dusk, 1 from DAY_FULL_ELEVATION up."""
    return smoothstep(REFERENCE_DUSK_ELEVATION, DAY_FULL_ELEVATION, elevation)


def night_scale(elevation: float) -> float:
    """Below the reference, how much of the dusk's light the sky still gives (the plates' own
    brightness, square-rooted as a camera at fixed exposure would compress it); 1 above."""
    if elevation >= REFERENCE_DUSK_ELEVATION:
        return 1.0
    return math.sqrt(min(1.0, sky_brightness(elevation)))


# ---------------------------------------------------------------- the sun
def air_mass(elevation: float) -> float:
    """Kasten and Young (1989), elevation in degrees above the horizon."""
    return 1.0 / (math.sin(math.radians(elevation)) + 0.50572 * (elevation + 6.07995) ** -1.6364)


def direct_beam(elevation: float) -> float:
    """Meinel's clear-sky direct beam, relative to the sun overhead (0.7^(AM^0.678))."""
    if elevation <= 0.0:
        return 0.0
    return 0.7 ** (air_mass(elevation) ** 0.678)


def sun_intensity(elevation: float) -> float:
    """The sun's light: none below the horizon, SunDusk's 2.5 at 8 deg, about 6 at a September
    noon. Relative, because the exposure stays fixed (D2)."""
    if elevation <= 0.0:
        return 0.0
    return SUN_KEY_INTENSITY * direct_beam(elevation) / direct_beam(SUN_KEY_ELEVATION)


def sun_colour(elevation: float) -> Vec3:
    """Today's warm dusk sun up to its own 8 deg, the clear-sky 5800 K from 30 deg, between them
    linearly. Below the horizon the colour is today's (its light is zero there)."""
    t = min(
        1.0,
        max(0.0, (elevation - SUN_KEY_ELEVATION) / (SUN_COLOR_DAY_ELEVATION - SUN_KEY_ELEVATION)),
    )
    return mix3(SUN_DUSK_COLOR, SUN_COLOR_DAY, t) if t > 0.0 else SUN_DUSK_COLOR


def sunrise_side(sun: Sun) -> bool:
    """True while the sun is in the eastern half of the sky: the morning side, on the frame's
    right with D1 (the facade faces south). The sky plate's glow is mirrored by the same rule, so
    the twilight key always lights from the side the glow is painted on."""
    return sun.azimuth_deg < 180.0


# ---------------------------------------------------------------- the twilight key
def twilight_intensity(elevation: float) -> float:
    """The twilight key's intensity for the real sun's elevation (either side of the sky).

    It is the light of the bright sky over the sunset, so it rises and falls with the glow the
    plates paint there (compose's dusk_of, peaking just above the horizon), normalised to
    SunDusk's 2.5 at the reference. Below the reference it fades to nothing at the end of civil
    twilight; above it, it yields to the direct sun as the day comes (day_weight, the same weight
    that brings the city and the windows to day), dark from DAY_FULL_ELEVATION. At the reference
    every factor is exactly 1, so the value is exactly SunDusk's."""
    if elevation <= TWILIGHT_END_ELEVATION or elevation >= DAY_FULL_ELEVATION:
        return 0.0
    glow = plate_dusk(elevation) / plate_dusk(REFERENCE_DUSK_ELEVATION)
    dusk_fade = smoothstep(TWILIGHT_END_ELEVATION, REFERENCE_DUSK_ELEVATION, elevation)
    return TWILIGHT_KEY_INTENSITY * glow * dusk_fade * (1.0 - day_weight(elevation))


def twilight_arch_linear(elevation: float) -> Vec3:
    """The plate's own colour where its glow is centred (the horizon row on the glow's side), as
    compose paints it at this elevation: the gradient there under the warm glow at its opacity.
    Linear. compose's final tint multiplies every channel by a constant, which cancels in the
    ratio twilight_colour takes, so it is left out."""
    base = gradient_at(plate_stops(elevation), PLATE_HORIZON_ROW)
    alpha = PLATE_GLOW_OPACITY * plate_dusk(elevation)
    return linear3(mix3(base, PLATE_GLOW_SRGB, alpha))


def twilight_colour(elevation: float) -> Vec3:
    """The key's colour: SunDusk's, turned as the sky over the sunset turns from the reference to
    this elevation (the arch's colour here over its colour at the reference, channel by channel),
    brightest channel at 1. Deeper in twilight the glow thins and the blue sky shows through, so
    the key cools; at the reference the ratio is 1 in every channel and the colour is SunDusk's."""
    here = twilight_arch_linear(elevation)
    ref = twilight_arch_linear(REFERENCE_DUSK_ELEVATION)
    turned = (
        TWILIGHT_KEY_COLOR[0] * here[0] / ref[0],
        TWILIGHT_KEY_COLOR[1] * here[1] / ref[1],
        TWILIGHT_KEY_COLOR[2] * here[2] / ref[2],
    )
    return normalised(turned)


def twilight_keys(sun: Sun) -> dict[str, dict[str, Any]]:
    """Both keys: the one on the sun's side of the sky at twilight_intensity, the other dark. Each
    carries the colour of the hour, so a key that comes on starts from the right colour."""
    lit = "morning" if sunrise_side(sun) else "evening"
    intensity = twilight_intensity(sun.elevation_deg)
    colour = twilight_colour(sun.elevation_deg)
    return {
        side: {"intensity": intensity if side == lit else 0.0, "color": colour}
        for side in ("evening", "morning")
    }


def sun_rotation(sun: Sun, frame: SceneFrame) -> dict[str, float]:
    """The directional light's world rotation (degrees) for the real sun, through the level's
    measured axes and the facade's heading (D1). The light travels away from the sun."""
    look_bearing = (frame.facade_heading_deg + 180.0) % 360.0  # the camera looks along scene +y
    relative = math.radians(sun.azimuth_deg - look_bearing)  # clockwise from scene +y, to +x
    elevation = math.radians(sun.elevation_deg)
    to_sun = (
        math.cos(elevation) * math.sin(relative),
        math.cos(elevation) * math.cos(relative),
        math.sin(elevation),
    )

    def unit(v: Vec3) -> Vec3:
        n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
        return (v[0] / n, v[1] / n, v[2] / n)

    ex, ey, ez = unit(frame.x), unit(frame.y), unit(frame.z)
    travel = tuple(-(to_sun[0] * ex[i] + to_sun[1] * ey[i] + to_sun[2] * ez[i]) for i in range(3))
    yaw = math.degrees(math.atan2(travel[1], travel[0]))
    pitch = math.degrees(math.atan2(travel[2], math.hypot(travel[0], travel[1])))
    return {"Pitch": pitch, "Yaw": yaw, "Roll": 0.0}


# ---------------------------------------------------------------- the sky plates
def sky_plates(sun: Sun) -> dict[str, float]:
    """The two neighbouring atlas cells and the blend between them.

    The blend is not linear in elevation: it is where the real elevation's (daylight, dusk) pair
    - compose's own two functions - falls between the two cells' pairs, so a blended plate reads
    as the plate compose would have made at that elevation."""
    e = sun.elevation_deg
    mirror = 1.0 if sunrise_side(sun) else 0.0  # the glow on the sun's side: right mornings
    cells = ATLAS_ELEVATIONS
    if e <= cells[0]:
        return {"PlateA": 0, "PlateB": 0, "PlateBlend": 0.0, "Mirror": mirror, "Gain": SKY_GAIN}
    if e >= cells[-1]:
        last = len(cells) - 1
        return {
            "PlateA": last,
            "PlateB": last,
            "PlateBlend": 0.0,
            "Mirror": mirror,
            "Gain": SKY_GAIN,
        }
    i = max(k for k in range(len(cells) - 1) if cells[k] <= e)
    a, b = cells[i], cells[i + 1]
    va = (plate_daylight(a), plate_dusk(a))
    vb = (plate_daylight(b), plate_dusk(b))
    ve = (plate_daylight(e), plate_dusk(e))
    d = (vb[0] - va[0], vb[1] - va[1])
    norm = d[0] ** 2 + d[1] ** 2
    if e == a:
        t = 0.0
    elif norm < 1e-12:
        t = (e - a) / (b - a)
    else:
        t = ((ve[0] - va[0]) * d[0] + (ve[1] - va[1]) * d[1]) / norm
    t = min(1.0, max(0.0, t))
    return {"PlateA": i, "PlateB": i + 1, "PlateBlend": t, "Mirror": mirror, "Gain": SKY_GAIN}


# ---------------------------------------------------------------- the road
def road(weather: Weather | None) -> dict[str, Any]:
    """The asphalt's roughness from real rain only: wet when rain is falling or fell in the last
    three hours, dry when the record says none fell, today's (wet) when that cannot be known."""
    if weather is None:
        return {
            "Roughness Min": WET_ROAD_ROUGHNESS[0],
            "Roughness Max": WET_ROAD_ROUGHNESS[1],
            "wetness": None,
            "source": "unavailable",
        }
    now = [
        v for v in (weather.rain_mm, weather.showers_mm, weather.precipitation_mm) if v is not None
    ]
    raining = any(v > 0.0 for v in now)
    history = weather.precip_last_3h_mm
    if raining or (history is not None and history > 0.0):
        wetness: float | None = 1.0
    elif history is not None and now:
        wetness = 0.0
    else:
        wetness = None
    if wetness is None:
        return {
            "Roughness Min": WET_ROAD_ROUGHNESS[0],
            "Roughness Max": WET_ROAD_ROUGHNESS[1],
            "wetness": None,
            "source": "unknown",
        }
    return {
        "Roughness Min": mix(DRY_ROAD_ROUGHNESS[0], WET_ROAD_ROUGHNESS[0], wetness),
        "Roughness Max": mix(DRY_ROAD_ROUGHNESS[1], WET_ROAD_ROUGHNESS[1], wetness),
        "wetness": wetness,
        "source": "observed",
    }


# ---------------------------------------------------------------- the clock
def clock_offset_s(seconds_of_day: float, game_time_s: float) -> float:
    """ClockOffsetS: the display shows (game Time + offset) as hh:mm, so the offset is the wall
    clock's seconds of the day minus the game's time at the same instant, kept within one day
    so the material's 32-bit float stays exact to well under a second."""
    return (seconds_of_day - game_time_s) % 86400.0


# ---------------------------------------------------------------- everything
def scene_params(
    world: WorldState, frame: SceneFrame | None = None, game_time_s: float | None = None
) -> dict[str, Any]:
    """Every value the scene takes, for this world. Pure: same inputs, same numbers."""
    sun = world.sun
    e = sun.elevation_deg
    day = day_weight(e)
    night = smoothstep(REFERENCE_DUSK_ELEVATION, -12.0, e)
    dim = night_scale(e)
    on = 1.0 if e < LIGHTS_ON_BELOW else 0.0

    day_haze = scale3(linear3(srgb_bytes(DAY_HAZE_SRGB)), DAY_HAZE_STRENGTH)
    haze: dict[str, dict[str, Any]] = {}
    for label in HAZE_LABELS:
        dusk_colour = HAZE_RIGHT if label.endswith("right") else HAZE_LEFT
        opacity = HAZE_OPACITY * (HAZE_FAR_SHARE if "_far_" in label else 1.0)
        haze[label] = {
            # exactly today's at the reference: dim is 1 and day 0 there, and a + (b - a) * 0 == a
            "HazeColor": mix3(scale3(dusk_colour, dim), day_haze, day),
            "Opacity": opacity,
        }

    day_horizon = normalised(linear3(srgb_bytes(SKY_STOPS["day"][3])))
    night_horizon = normalised(linear3(srgb_bytes(SKY_STOPS["night"][3])))
    white: Vec3 = (1.0, 1.0, 1.0)
    if day > 0.0:
        sky_colour = mix3(white, day_horizon, day)
    elif night > 0.0:
        sky_colour = mix3(white, night_horizon, night)
    else:
        sky_colour = white
    # the plates' own light, square-rooted as at fixed exposure: 0.24 at night, 1.28 by day.
    # The real-time capture sees little of this level (no atmosphere, no IsSky mesh; critic, hole
    # 7), so this mostly scales the ambient the build set; its colour is the plate's horizon.
    sky_intensity = SKY_LIGHT_DUSK * math.sqrt(sky_brightness(e))

    fog_day = linear3(srgb_bytes(DAY_HAZE_SRGB))  # Blender's day haze colour, unscaled
    fog = mix3(scale3(FOG_DUSK, dim), fog_day, day)

    weather = world.weather
    reason = world.weather_reason
    if weather is None:
        note = WEATHER_NOTES.get(reason or "", "Vremea nu este disponibilă.")
    elif reason == "stale":
        note = "Serviciul meteo nu răspunde: scena păstrează ultima observație reală."
    else:
        note = None

    city = mix(1.0, CITY_DAY_EMISSION, day)
    return {
        # the direct sun: the Movable light, lit only above the horizon
        "sun": {
            "elevation_deg": e,
            "azimuth_deg": sun.azimuth_deg,
            "intensity": sun_intensity(e),
            "color": sun_colour(e),
            "rotation": sun_rotation(sun, frame) if frame is not None else None,
        },
        # the sky over the sunset (or the sunrise): the Stationary keys, intensity and colour only
        "twilight": twilight_keys(sun),
        "sky_light": {
            "intensity": sky_intensity,
            "color": sky_colour,
            # today black below (bLowerHemisphereIsBlack): by day the lit ground bounces a little
            # of the sky back, at the ~10 % a street's albedo gives
            "lower_hemisphere": scale3(day_horizon, 0.1 * day) if day > 0.0 else (0.0, 0.0, 0.0),
        },
        "lights": {
            "lamps": on,
            "shelter": on,
            "uplights": on,
            "fills": on,
            "car_lights": on,
        },
        "sky": sky_plates(sun),
        "emissive_factor": {"skyline": city, "near_blocks": city},
        # the room windows' picture: dusk at the reference, the day picture by day, the night
        # state from the reference down to -12 deg (the same weight the sky light and the haze
        # darken by), so no window shows the dusk horizon in the night
        "window_view": {"DayBlend": day, "NightBlend": night},
        # the near blocks' darkest plain slots (M_HQ_CityDay, look_hq_live.near_blocks_day): their
        # dusk colour at 0, their own hue at a facade's albedo by day, by the same day weight; the
        # rejected rebuild showed them as black cardboard at noon
        "near_blocks_day": {"Daylight": day},
        "haze": haze,
        "fog": {"inscattering": fog, "density": FOG_DENSITY},
        "road": road(weather),
        "clock": {
            "seconds_of_day": world.seconds_of_day,
            "ClockOffsetS": clock_offset_s(world.seconds_of_day, game_time_s)
            if game_time_s is not None
            else None,
        },
        # D2: not approved. The exposure stays as built; the sun's scale is relative instead.
        "exposure": None,
        "weather_note": note,
    }
