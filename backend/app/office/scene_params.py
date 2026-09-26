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

* A real day, not a dusk with a switch (wave 3, 2026-09-24). The evening darkens monotonically
  from +10 deg to the end of civil twilight: the key on the sun's side carries the low sun through
  the golden hour and warms toward amber, the fills follow the sky's light on the street instead
  of the lamps' switch (a measured curve, no brighter than the noon) and warm with the key, and
  the air warms. The dawn is cooler and bluer than the dusk and the city has fewer lit windows. A
  cloud deck dims the sun and the key, lights the street with a share of the clear day's light
  (never more than the sun gives), greys the haze and thickens the air; it hides the sunset's glow,
  but by day the atlas has no grey deck, so the sky stays the clear hour's. Rain darkens the
  street again. The night sky carries the city's glow. Where a value is measured or a look (the
  amber, the glow's colour) it says so where it is defined, with what it was measured against.
* The front ground on the noon's budget (wave 3, round 3). From noon down to the lamps the road
  and the front pavement are never lit brighter than under the noon sun: the street's fill has its
  own measured curve, lower than the facade's, and the evening's warmth is the fills' hue, not
  their strength. The fills are as built again by -1 deg: after sunset the street's light is the
  blue hour's until the lamps. Under a cloud deck the dome is the main light and lights the
  foliage from above (the sky light), and falling rain turns the road into a traced mirror.
* The weather's look is HELD (``WEATHER_LOOK``, the art director's third read, 2026-09-24): the
  deck and rain rules above are written and tested but not shipped, because no atlas cell is a
  grey deck and the dome's lift washed the sign. Until a rebuild adds grey deck cells the scene is
  the clear sky's at the real hour, and only the road follows the real rain, as before.
* The towers, the trees and the skyline by day (the day state, 2026-09-26): the facades take their
  day colours and switch their windows off by the real sun (TowerDaylight, WindowsOn: off only in
  the day's glare, most of them lit by +2.5 deg, the near blocks never below their own floor, the
  dawn capped by the city's dawn rule), the leaves and the skyline's plain slots take the day
  (LeafDaylight, Daylight). Every value is its material's default at the reference, and none is
  sent to a level whose report has no day state.

Owner decisions taken as proposed (2026-09-18, he did not object); each lives in one place:
D1 the viewer looks north and the facade faces south (``office_facade_heading_deg``, config);
D2 exposure is not written (``exposure`` is always None); D5 with no weather the sky is the clear
sky of the real hour and the road keeps today's values, and the page says so; D6 the sky is the
pre-built plate atlas below.
"""

from __future__ import annotations

import math
from collections.abc import Callable
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
#: While rain falls the road carries a water film: look_hq_live.py's 0.08-0.24 (2026-09-16), where
#: the lamps' and the shopfronts' streaks first appeared on the road, all of it below the
#: post-process's LumenMaxRoughnessToTraceReflections (AMN_LOOK_TRACE_ROUGHNESS, 0.5), so every
#: part of it is traced. (0.03-0.16 had made a full mirror.) Rain in the last three hours alone is
#: the build's damp road, WET_ROAD_ROUGHNESS.
RAIN_ROAD_ROUGHNESS = (0.08, 0.24)

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

# ---------------------------------------------------------------- the golden hour (wave 3)
#: From the horizon to about +10 deg the real sun stands low in the west (evenings) or the east
#: (mornings): the facade faces south (D1), so the Movable sun at its real azimuth only grazes it
#: (measured 2026-09-24 at 18:50, sun 266 deg: its intensity 0.87 -> 3.0 moved the building by +0.9
#: of 255). The Stationary key on the sun's side (SunDusk / SunDawn, fixed 8 deg up at azimuth
#: ~244 / ~116, within ~20 deg of where the low sun really stands) carries the low sun's light on
#: the facade and the street: it rises from SunDusk's 2.5 at the reference to this by
#: GOLDEN_RISE_TOP, holds, and hands over to the Movable sun between GOLDEN_HANDOVER. Measured on
#: the stream at 18:50: key 6.0 lifts the building by +12 and the street by +9 over the committed
#: 1.06, so the evening no longer goes dark before the dusk (the "power cut" of 2026-09-24).
GOLDEN_KEY_INTENSITY = 6.0
GOLDEN_RISE_TOP = 1.0
GOLDEN_HANDOVER = (10.0, 20.0)
#: The low sun's colour: a 3000 K blackbody (Helland's fit, sRGB 255, 180, 107). The key and the
#: sun warm toward it from the reference to just above the horizon and come back to SunDusk's
#: colour by its own 8 deg (GOLDEN_WARM_RISE, GOLDEN_WARM_FADE).
GOLDEN_AMBER_SRGB: Vec3 = (255.0, 180.0, 107.0)
GOLDEN_WARM_RISE = (REFERENCE_DUSK_ELEVATION, 0.5)
GOLDEN_WARM_FADE = (3.0, SUN_KEY_ELEVATION)

#: The golden hour's air: the fog's inscattering and the haze planes move this share toward the
#: colour the plate paints over the sunset (twilight_arch_linear, at the fog's own luminance),
#: across GOLDEN_AIR_RISE and back by GOLDEN_AIR_FADE. Measured at 18:50: the blue day veil made
#: the lit evening read lavender; the warm veil reads as a low sun.
GOLDEN_AIR_SHARE = 0.5
GOLDEN_AIR_RISE = (REFERENCE_DUSK_ELEVATION, 0.5)
GOLDEN_AIR_FADE = (6.0, 12.0)

# ---------------------------------------------------------------- the sky's light on the street
#: FacadeLight (the facade above the ground floor) and StreetFill (over the road) are the level's
#: stand-in for the sky's light on the facade and the street: the sky light's real-time
#: capture sees little of this level (measured at 18:50: SkyLight 0.68 -> 1.5 moved the street by
#: +1 of 255, the fills 0 -> 1 by +27). Below -2 deg the lamps keep them at the build's level, as
#: before. Above the reference the sky is the street's only light until the sun rises, so they rise
#: to a peak around sunset; as the sun climbs the key and the Movable sun take the street, the
#: fills keep what the sky adds, and by noon the sun lights the street alone (noon as before).
#: The shape is measured, not modelled: on the stream on 2026-09-24 (wave 3, step 2), with the fills
#: warmed (fill_colours), WalkWash held at its build level and the key and the sun as planned, the
#: fill at each instant of the evening that spaces the street (lum.py's band, the mean of 9 frames:
#: the passing traffic moves a 3-frame mean by about 1.3 of 255) evenly between the lamp-lit
#: 19:19 (-2.5 deg, 67.1) and the clear noon (79.6): sunset (19:09, -0.7) 70.4, 18:50 (+2.7) 73.6,
#: 18:25 (+7.1) 77.4, 17:58 (+11.9) 80.3. Measured slopes, of 255 per unit of fill: 15 at sunset,
#: 17 at +2.7, 13.7 at +7.1, 20 at +11.9. Between the anchors a smoothstep, so the fill never
#: jumps. The fills fall after sunset because the key and the Movable sun take the street (at
#: equal fills +7.1 read 7 above +2.7). A log-of-lux curve (wave 3, step 1) put the street at
#: +7..+12 above the noon's (89 against 80), and 19:19 up to 67 leaves only 12 of 255 below noon
#: for four steps of the evening, so the margins are about 3.2 each. Since round 3 this curve drives
#: FacadeLight alone; StreetFill has STREET_CLEAR_ANCHORS below. At +7.1 (18:25) the key stands at
#: its full golden 6.0 and carries the facade, and the facade's fill is lower there so the building
#: keeps a margin of 3 of 255 below 17:58 (measured 2026-09-24: FacadeLight 1.46 -> 1.0 moved the
#: building 81.2 -> 80.7 at 18:25; 17:58 reads 83.9).
FACADE_CLEAR_ANCHORS: tuple[tuple[float, float], ...] = (
    (REFERENCE_DUSK_ELEVATION, 1.0),
    (-0.7, 1.88),
    (2.7, 1.77),
    (7.1, 0.9),
    (11.9, 1.46),
    (14.1, 1.40),
    (45.0, 0.0),
)
#: The front ground's budget (round 3). With the facade's curve the front pavement read 105-115 of
#: 255 from 17:45 to 19:09 and the road's median 70-78, against the noon sun's 70.7 and 47.7 (art
#: director, 2026-09-24): the ground was brightest while the sun was lowest. StreetFill (and
#: WalkWash with it) takes its own curve, measured on the stream on 2026-09-24 so that the front
#: pavement and the road's median (lum2.py's regions, 9 frames) stay at or under the noon's plus
#: 3 at every instant from noon down to -2 deg and darken toward the lamps. Measured slopes (of
#: 255 per unit of fill, 17:45 to 19:09): the pavement 62-71, the road's median 41-45, lum.py's
#: street band 26-29. What the anchors gave (9 frames each; pavement / road median / street band):
#: 13:07 70.6 / 47.6 / 79.5, 17:45 65.1 / 47.8 / 61.3, 17:58 65.2 / 47.1 / 61.4, 18:25 58.0 /
#: 43.6 / 56.7, 18:50 59.8 / 43.6 / 52.9 (amber, 78/54/42), 19:09 52.1 / 37.4 / 45.9, 07:25 65.4 /
#: 48.2 / 58.3. The +2.7 anchor sits above +7.1 so the golden hour keeps a lit amber ground while
#: the street band still falls by 3 or more at each evening step. Below -2 deg the lamps come on
#: and the fill rises with them to its build level by the reference (LAMP_FILL_RAMP), as the dusk
#: was built; the lamp-lit 19:19 (street band 67.6) is brighter than the sunset before it.
STREET_CLEAR_ANCHORS: tuple[tuple[float, float], ...] = (
    (-2.0, 0.4),
    (-0.7, 0.5),
    (2.7, 0.62),
    (7.1, 0.44),
    (11.9, 0.5),
    (14.1, 0.48),
    (45.0, 0.0),
)
#: The span over which StreetFill comes up to its build level with the lamps (they switch at
#: LIGHTS_ON_BELOW): from the evening's fill at -2 deg to 1 at the reference, as a fade.
LAMP_FILL_RAMP = (-2.0, REFERENCE_DUSK_ELEVATION)
#: WalkWash is the shopfronts' warm spill on the pavement in front of the building (look_hq_live.py
#: walk_wash), not the sky's light: it never rises above its build level (wave 3, step 1 drove it
#: with the fills up to 2.25x).
WALK_WASH_MAX = 1.0

# ---------------------------------------------------------------- under a cloud deck
#: A closed deck passes about a fifth to a third of a clear day's light, all of it diffuse, so the
#: fills (the diffuse light's stand-in) carry the street alone: a share of the clear day's street
#: light at the same hour, in fill units the clear fills plus the sun's share of the street at
#: FILL_SUN_EQUIVALENT. That is the fills alone that light the front pavement as the clear noon sun
#: does (measured 2026-09-24 at 13:07, the sun off: fills 2.0 put it at 118 of 255 against the
#: sun's 70.6, about 40 per unit, so about 0.8). OVERCAST_FILL_SHARE, measured the same day under
#: the deck at 13:07: fills 1.0 put the pavement at 87 and the road at 63 (the clear noon's: 70.6
#: and 62.3, "weather lighting the street brighter than the sun"), 0.5 at 63 and 49.
FILL_SUN_EQUIVALENT = 0.8
#: Round 3: the sky light now carries the deck's dome (DECK_SKY_LIGHT_LIFT), so the fills keep a
#: smaller share; see DECK_SKY_LIGHT_LIFT for the measurement.
OVERCAST_FILL_SHARE = 0.44
#: Rain falls from a thicker deck (nimbostratus against stratus: roughly half its light again), and
#: the wet road's film traps diffuse light, so while it rains the fills lose this share too: the
#: level's asphalt exposes only its roughness, and the rain's thicker fog had lifted the rainy road
#: above the dry one (50.7 against 49.3 at fills 0.5, 13:07).
RAIN_FILL_LOSS = 0.3
#: Under a closed deck the dome is the main light, and it lights from above: foliage takes it on
#: its upper leaves, where the fills (rect lights aimed at the road and the facade) barely reach.
#: The sky light is the level's only dome, and its real-time capture sees little of this level, so
#: its multiplier has to be large for the dome's share to show. Measured on 2026-09-24 at 13:07
#: under the deck (the planters' shrubs / the front pavement, lum2.py): sky light 1.28 and fills
#: 0.48 (round 2) 37.0 / 62.1; sky light 20, fills 0.3 46.8 / 53.0; sky light 40, fills 0.2 55.1 /
#: 48.0 (the clear noon: 64.2 / 70.7, ratio 0.91). By day under the deck the sky light is lifted by
#: this factor (by the day weight: the lamps own the dusk), less in rain's darker deck, and its
#: colour is the deck's neutral grey.
DECK_SKY_LIGHT_LIFT = 20.0
RAIN_SKY_LIGHT_LOSS = 0.25

# ---------------------------------------------------------------- the fills' own colour
#: The fills' colour as the saved level has it, read over Remote Control from the running game on
#: 2026-09-24 (PUT /remote/object/property, LightColor, READ_ACCESS, on each RectLight's
#: LightComponent0): FColor bytes, sRGB. They are look_hq_live.py's LinearColor (0.7, 0.73, 0.88),
#: (1.0, 0.88, 0.74) and (0.72, 0.78, 1.0) stored with sRGB on. The street's and the facade's fill
#: are cool (a blue dusk sky's ambient); under the warm key of the golden hour they made the lit
#: street and the lower facade read grey-lavender (art director, 2026-09-24).
FILL_BUILT_SRGB8: dict[str, Vec3] = {
    "StreetFill": (218.0, 222.0, 241.0),
    "WalkWash": (255.0, 241.0, 223.0),
    "FacadeLight": (221.0, 229.0, 255.0),
}
#: Between about +10 deg and the sunset the street's light is the low sun's: the fills take this
#: share of the key's hue (at their own luminance) across FILL_WARM_RISE and give it back across
#: FILL_WARM_FADE. After sunset the street's light is the blue hour's until the lamps: the warm
#: fill at 19:09 (-0.7 deg) made the brightest pavement of the day (art director, round 2), so the
#: hue is back to its build colour by -1 deg (round 3) and full only from +1.
FILL_WARM_SHARE = 0.7
FILL_WARM_RISE = (-1.0, 1.0)
FILL_WARM_FADE = (9.0, 12.0)

# ---------------------------------------------------------------- morning is not evening
#: The dawn is cooler than the dusk: the air after the night is cleaner (less aerosol, a shallow
#: boundary layer), so the low sun and the sky over the sunrise are less orange. The key's and the
#: sun's colour move this share toward the pale day sky (hq_time.js day stop "#cfe2f3") on the
#: morning side, fading by DAWN_COOL_FADE.
DAWN_COOLING = 0.35
DAWN_COOL_SRGB = "#cfe2f3"
DAWN_COOL_FADE = (SUN_KEY_ELEVATION, 20.0)
#: The sky over the sunrise is cooler: until the glow peaks just above the horizon the dawn takes
#: the plate of a sun DAWN_PLATE_SHIFT deg deeper (a thinner, bluer glow), easing back to the
#: real elevation across DAWN_PLATE_SHIFT_FADE (dawn_plate_elevation).
DAWN_PLATE_SHIFT = 2.0
DAWN_PLATE_SHIFT_FADE = (-1.0, 3.0)
#: Fewer lit windows in the city at dawn than at dusk (offices empty, homes waking): the city's
#: emission on the morning side, from nautical twilight (-12 deg) to -6 deg, falls to this share
#: of the dusk's before the day dims it further. Continuous at solar midnight (the weight is 0
#: that deep), so the city never jumps.
DAWN_CITY_WINDOWS = 0.45
DAWN_CITY_RISE = (-12.0, -6.0)

# ---------------------------------------------------------------- the towers by day (day state)
#: The skyline's and the near blocks' facades bake their navy and their lit windows into the
#: export's window textures, so at noon they were "blue cardboard" with lit windows, and the street
#: trees' crowns (darkened for the dusk) black cards. The in-place passes of
#: art-source/unreal/towers_day give those materials parameters whose defaults paint exactly
#: today's dusk: M_HQ_TowerDay's TowerDaylight (0 = the dusk facade, 1 = hq_day.py's day facade)
#: and WindowsOn (1 = every window the dusk lights, 0 = none), M_HQ_TreeLeaves' LeafDaylight
#: (0 = the dusk crowns, 1 = the pack's own leaf albedo), and Daylight on the skyline's
#: M_HQ_CityDay slots (the bridge), as on the near blocks'. Nothing moves until the backend writes
#: them, and only where the report's "day_state" names the components (unreal.py).
#:
#: The towers' lit windows, the art director's reading of 2026-09-26 (run 2 of the towers window,
#: refused: at 18:50, the sun at +2.7 deg, a tenth of the windows left the towers "muddy mauve
#: slabs" and the right near block a black box, and 07:25 an empty skyline; the 09-24 reading in
#: towers_day.py switched them off from +5 deg): none only while the sun stands above
#: WINDOWS_OFF_ABOVE, where the day's glare hides a lit window; as it sinks they come on, most of
#: them (WINDOWS_MOST of the dusk's) by WINDOWS_MOST_AT, so they hold against the dimming sky;
#: from those to all of them at the reference dusk, all of them below it. Smoothsteps between the
#: knots, so the curve never jumps or turns back (windows_share).
WINDOWS_OFF_ABOVE = 15.0
WINDOWS_MOST_AT = 2.5
WINDOWS_MOST = 0.7
#: The near blocks (homes and shops over the street, the frame's right) keep their own floor: at
#: least NEAR_WINDOWS_FLOOR of their dusk windows while the sun is low, on both sides of the day,
#: so a lit near block never goes black; the floor fades out as the sun climbs over
#: NEAR_WINDOWS_FLOOR_FADE (whole at and below its second value, gone at and above its first).
#: At dawn it stands above the city's ceiling (DAWN_CITY_WINDOWS): homes wake before offices.
NEAR_WINDOWS_FLOOR = 0.5
NEAR_WINDOWS_FLOOR_FADE = (10.0, 6.0)
#: towers_day.py's window ranks: every lit window of the dusk carries a rank spread evenly over
#: (TOWER_RANK_MIN, TOWER_RANK_MAX] (stored as 8-bit floors), and M_HQ_TowerDay multiplies its
#: emission by saturate((WindowsOn - rank) x TOWER_GATE_SHARPNESS). WindowsOn 1 lights every rank,
#: since (1 - 0.95) x 50 >= 1: the dusk to the bit.
TOWER_RANK_MIN = 0.02
TOWER_RANK_MAX = 0.95
TOWER_GATE_SHARPNESS = 50.0

# ---------------------------------------------------------------- the night over a lit city
#: A city's night sky is never the astronomical black: its lights glow on the low air. The
#: backdrop's gain rises by this share at full night (the -18 cell read 15 of 255 on the stream:
#: "a flat black void"), and the haze planes (lowest, densest near the horizon) and the fog's
#: inscattering take a warm grey (sodium and LED light scattered by the low air) by the same
#: night weight, NIGHT_GLOW_RISE.
NIGHT_SKY_GAIN_BOOST = 1.2
NIGHT_GLOW_RISE = (-6.0, -12.0)
CITY_GLOW_HAZE: Vec3 = (0.1, 0.085, 0.072)
CITY_GLOW_FOG: Vec3 = (0.16, 0.14, 0.125)

# ---------------------------------------------------------------- the real weather
#: Cloud cover (0..1) for a condition when the service gave no cloud cover.
CONDITION_CLOUD = {
    "clear": 0.0,
    "partly_cloudy": 0.5,
    "cloudy": 0.9,
    "fog": 1.0,
    "drizzle": 1.0,
    "rain": 1.0,
    "snow": 1.0,
    "storm": 1.0,
}
#: Conditions that mean precipitation is falling now.
PRECIPITATING = frozenset({"drizzle", "rain", "snow", "storm"})
#: The weather's look (the cloud deck's light, rain's darker sky and traced road) is HELD, off,
#: since the art director's third read on 2026-09-24: no cell of the sky atlas is a grey deck, so
#: an overcast noon kept the clear day's blue over a dim street, and the dome's lift washed the
#: AMN-AI sign's black panel to slate. Its rules and their tests stay; they come back when a
#: rebuild adds grey deck cells to the atlas. While held, the scene is the clear sky's at the real
#: hour, and the road is wet or dry from the real rain exactly as before.
WEATHER_LOOK = False
#: Overcast (0..1) grows from this much cloud cover to a closed deck.
OVERCAST_FROM = 0.5
#: Under a closed deck the direct sun is mostly blocked, the low sun's and the glow's key too.
OVERCAST_SUN_LOSS = 0.85
OVERCAST_KEY_LOSS = 0.7
#: The atlas has no overcast cell (it was composed for clear skies), and no honest deck can be
#: made from it: a real deck by day is a light grey, at least as bright as the clear sky and with no
#: blue, and every day cell is blue. Measured at 13:07 (the sky's top rows, sRGB mean): the clear
#: +35 cell (94, 177, 215); the +15 cell at gain 1.3 (106, 182, 218), brighter but as blue; the +8
#: cell blended with the dim -8 cell (wave 3, step 1) (67, 116, 168), a darker, bluer sky that made
#: the overcast noon read as an evening (art director). So by day, from OVERCAST_CLEAR_FROM (where
#: the clear cells carry no sunset glow), the deck keeps the clear sky of the real hour, as before
#: wave 3, and only the haze and the air say it is grey. Below it the deck hides the sunset's glow:
#: the -8 cell (dim, grey-blue, the faintest glow) blended toward the +8 cell (the palest) by the
#: real daylight, which meets the clear plate at +8 exactly, at a lower gain in the dusk. The next
#: rebuild must compose real overcast cells (a flat light-grey deck by day, a dim one at dusk, one
#: lit from below by the city at night); see the scene notes. Nothing else the allow-list reaches
#: can grey the sky's top rows (round 3, 2026-09-24, 13:07 under the deck): the fog veils the street
#: more than the sky (density 0.06 in light grey took the top rows' chroma 114 -> 62 but the road
#: 48 -> 106 and the building 76 -> 127), the haze planes end at frame row 80 (TopZ raised to it,
#: falloff 0.3: chroma 114 -> 97 with a hard grey edge across the sky), the backdrop's Gain only
#: scales and PlateBlend only mixes blue cells.
OVERCAST_PLATE_FROM = 0.5
OVERCAST_PLATES = (2, 7)
OVERCAST_CLEAR_FROM = SUN_KEY_ELEVATION
#: The backdrop's gain under the deck: lower in the dusk; by day the clear hour's, lifted by
#: OVERCAST_DAY_LIFT so the deck is never darker than the clear sky (measured at 13:07: the deck's
#: denser grey fog veiled the same plate to 154.2 against the clear 156.6 of 255, the sky's top
#: rows). Rain lowers it again at every hour (a darker, lower deck).
OVERCAST_GAIN_LOSS = 0.15
OVERCAST_DAY_LIFT = 0.05
RAIN_GAIN_LOSS = 0.1
#: By day the haze planes in front of the skyline take the deck's light grey (measured at 13:07:
#: grey 0.5 at opacity 0.8 greyed and lightened the far city, 88 -> 108 of 255, without touching
#: the building or the street), by the overcast weight and the plate's daylight.
DECK_HAZE: Vec3 = (0.5, 0.5, 0.52)
#: The fog thickens and greys under cloud and more in rain; the haze planes likewise. Its
#: inscattering dims under the deck (a darker sky scatters less light): measured, x2.5 density in
#: rain with the clear sky's inscattering lifted the rainy noon to 113 of 255 against 99 clear.
OVERCAST_FOG = 1.0
RAIN_FOG = 0.5
OVERCAST_FOG_DIM = 0.35
OVERCAST_GREY = 0.6
OVERCAST_HAZE_OPACITY = 0.45
HAZE_OPACITY_MAX = 0.9

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


def golden_warmth(elevation: float) -> float:
    """0 at and below the reference, 1 from just above the horizon to +3 deg, 0 again by 8 deg."""
    return smoothstep(*GOLDEN_WARM_RISE, elevation) * (
        1.0 - smoothstep(*GOLDEN_WARM_FADE, elevation)
    )


def golden_amber() -> Vec3:
    return normalised(linear3(GOLDEN_AMBER_SRGB))


def golden_air(colour: Vec3, elevation: float, morning: bool = False) -> Vec3:
    """``colour`` (the fog's or a haze plane's) moved toward the sunset arch's colour at the same
    luminance, by GOLDEN_AIR_SHARE across the golden hour (less at dawn, DAWN_COOLING); the very
    same tuple outside it."""
    share = (
        GOLDEN_AIR_SHARE
        * (1.0 - DAWN_COOLING if morning else 1.0)
        * smoothstep(*GOLDEN_AIR_RISE, elevation)
        * (1.0 - smoothstep(*GOLDEN_AIR_FADE, elevation))
    )
    if share <= 0.0:
        return colour
    arch = twilight_arch_linear(elevation)
    scale = luminance(colour) / max(1e-9, luminance(arch))
    return mix3(colour, scale3(arch, scale), share)


def dawn_cool(colour: Vec3, elevation: float, morning: bool) -> Vec3:
    """On the morning side, the colour moved DAWN_COOLING toward the pale day sky (fading by
    DAWN_COOL_FADE); the evening side's colour is returned unchanged, the very same tuple."""
    if not morning:
        return colour
    share = DAWN_COOLING * (1.0 - smoothstep(*DAWN_COOL_FADE, elevation))
    if share <= 0.0:
        return colour
    return normalised(mix3(colour, normalised(linear3(srgb_bytes(DAWN_COOL_SRGB))), share))


def sun_colour(elevation: float, morning: bool = False) -> Vec3:
    """Today's warm dusk sun at its own 8 deg, the clear-sky 5800 K from 30 deg, between them
    linearly; below 8 deg it warms toward the low sun's amber (golden_warmth). Below the horizon
    the colour is today's (its light is zero there). Mornings are cooler (dawn_cool)."""
    if elevation <= REFERENCE_DUSK_ELEVATION:
        return dawn_cool(SUN_DUSK_COLOR, elevation, morning)
    if elevation < SUN_KEY_ELEVATION:
        warm = golden_warmth(elevation)
        base = (
            normalised(mix3(SUN_DUSK_COLOR, golden_amber(), warm)) if warm > 0 else SUN_DUSK_COLOR
        )
        return dawn_cool(base, elevation, morning)
    t = min(
        1.0,
        max(0.0, (elevation - SUN_KEY_ELEVATION) / (SUN_COLOR_DAY_ELEVATION - SUN_KEY_ELEVATION)),
    )
    base = mix3(SUN_DUSK_COLOR, SUN_COLOR_DAY, t) if t > 0.0 else SUN_DUSK_COLOR
    return dawn_cool(base, elevation, morning)


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


def golden_key_intensity(elevation: float) -> float:
    """The key as the low sun (above the reference): SunDusk's 2.5 at the reference, rising to
    GOLDEN_KEY_INTENSITY by GOLDEN_RISE_TOP, held, and handed to the Movable sun across
    GOLDEN_HANDOVER. Zero at and below the reference, where the twilight glow alone is the key."""
    if elevation <= REFERENCE_DUSK_ELEVATION or elevation >= GOLDEN_HANDOVER[1]:
        return 0.0
    rise = smoothstep(REFERENCE_DUSK_ELEVATION, GOLDEN_RISE_TOP, elevation)
    value = SUN_KEY_INTENSITY + (GOLDEN_KEY_INTENSITY - SUN_KEY_INTENSITY) * rise
    return value * (1.0 - smoothstep(*GOLDEN_HANDOVER, elevation))


def key_intensity(elevation: float) -> float:
    """The key on the sun's side: the stronger of the twilight glow and the low sun. Exactly
    SunDusk's 2.5 at the reference; rising through the golden hour, so the evening darkens
    monotonically from +10 deg to the end of civil twilight with no hole at the crossover."""
    return max(twilight_intensity(elevation), golden_key_intensity(elevation))


def key_colour(elevation: float, morning: bool = False) -> Vec3:
    """The key's colour: the twilight arch's below the reference (twilight_colour), the low sun's
    above it (sun_colour: SunDusk's warming toward amber near the horizon, then the day's), cooler
    on the morning side. At the reference, SunDusk's exactly."""
    if elevation <= REFERENCE_DUSK_ELEVATION:
        return dawn_cool(twilight_colour(elevation), elevation, morning)
    return sun_colour(elevation, morning)


def twilight_keys(sun: Sun, overcast: float = 0.0) -> dict[str, dict[str, Any]]:
    """Both keys: the one on the sun's side of the sky at key_intensity (dimmed by the real cloud
    deck), the other dark. Each carries the colour of the hour, so a key that comes on starts from
    the right colour."""
    morning = sunrise_side(sun)
    lit = "morning" if morning else "evening"
    intensity = key_intensity(sun.elevation_deg)
    if overcast > 0.0:
        intensity *= 1.0 - OVERCAST_KEY_LOSS * overcast
    colour = key_colour(sun.elevation_deg, morning)
    return {
        side: {"intensity": intensity if side == lit else 0.0, "color": colour}
        for side in ("evening", "morning")
    }


# ---------------------------------------------------------------- the sky's light (the fills)
def anchored(anchors: tuple[tuple[float, float], ...], elevation: float) -> float:
    """A measured curve: the first anchor's value below it, the last's above, and a smoothstep
    between neighbouring anchors, so it never jumps."""
    if elevation <= anchors[0][0]:
        return anchors[0][1]
    for (e0, f0), (e1, f1) in zip(anchors, anchors[1:], strict=False):
        if elevation <= e1:
            return mix(f0, f1, smoothstep(e0, e1, elevation))
    return anchors[-1][1]


def clear_facade(elevation: float) -> float:
    """FacadeLight under a clear sky (FACADE_CLEAR_ANCHORS): the build's 1 at and below the
    reference, the sunset's peak, 0 from the noon anchor up."""
    return anchored(FACADE_CLEAR_ANCHORS, elevation)


def clear_fill(elevation: float) -> float:
    """StreetFill under a clear sky (STREET_CLEAR_ANCHORS), from noon down to the lamps: the front
    ground on the noon's budget. Below -2 deg fill_factor brings it up with the lamps."""
    return anchored(STREET_CLEAR_ANCHORS, elevation)


def sun_ground_share(elevation: float) -> float:
    """How much of the street's light the direct sun gives, 0 at the horizon to 1 at 45 deg
    (its light on the ground, intensity x sin(elevation), against the same at 45 deg)."""
    if elevation <= 0.0:
        return 0.0
    here = sun_intensity(elevation) * math.sin(math.radians(elevation))
    top = sun_intensity(45.0) * math.sin(math.radians(45.0))
    return min(1.0, here / top)


def deck_fill(elevation: float, clear: Callable[[float], float] = clear_fill) -> float:
    """A fill under a closed deck: OVERCAST_FILL_SHARE of the clear day's light at the same hour
    (the fill's clear curve, ``clear``, plus the sun's share of the street at
    FILL_SUN_EQUIVALENT)."""
    clear_day = clear(elevation) + FILL_SUN_EQUIVALENT * sun_ground_share(elevation)
    return OVERCAST_FILL_SHARE * clear_day


def sky_fill(
    clear: Callable[[float], float], elevation: float, overcast: float, raining: bool
) -> float:
    """A fill's sky light: its clear curve toward the deck's by the overcast weight, less again
    while it rains. A deck never lights more than the clear day does at the same hour."""
    sky = mix(clear(elevation), deck_fill(elevation, clear), overcast)
    if raining:
        sky *= 1.0 - RAIN_FILL_LOSS
    return sky


def fill_factor(elevation: float, overcast: float = 0.0, raining: bool = False) -> float:
    """StreetFill's factor (the road and the front pavement): above LIGHTS_ON_BELOW the sky's light
    on the street on the noon's budget (clear_fill); below it the fill comes up with the lamps to
    its build level by the reference (LAMP_FILL_RAMP), a fade, never a switch. Exactly 1 at the
    reference, 1 at night."""
    sky = sky_fill(clear_fill, elevation, overcast, raining)
    if elevation >= LIGHTS_ON_BELOW:
        return sky
    return max(sky, mix(sky, 1.0, smoothstep(*LAMP_FILL_RAMP, elevation)))


def facade_factor(elevation: float, overcast: float = 0.0, raining: bool = False) -> float:
    """FacadeLight's factor: at the build's intensity with the lamps (below LIGHTS_ON_BELOW), and
    above that the sky's light on the facade (clear_facade), toward the deck's by the overcast
    weight, less again while it rains. Exactly 1 at the reference."""
    sky = sky_fill(clear_facade, elevation, overcast, raining)
    lamps = 1.0 if elevation < LIGHTS_ON_BELOW else 0.0
    return max(lamps, sky)


def walk_wash_factor(elevation: float, overcast: float = 0.0, raining: bool = False) -> float:
    """WalkWash (the shopfronts' spill on the pavement before the building): with StreetFill,
    never above its build level (WALK_WASH_MAX). Exactly 1 at the reference."""
    return min(WALK_WASH_MAX, fill_factor(elevation, overcast, raining))


def deck_sky_light(elevation: float, overcast: float, raining: bool) -> float:
    """The sky light's multiplier under the deck: DECK_SKY_LIGHT_LIFT by day under a closed deck
    (less in rain), faded in by the day weight, so the dusk and the night (the lamps' hours) keep
    the clear sky's light; exactly 1 under a clear sky."""
    if overcast <= 0.0:
        return 1.0
    lift = (DECK_SKY_LIGHT_LIFT - 1.0) * overcast * day_weight(elevation)
    if raining:
        lift *= 1.0 - RAIN_SKY_LIGHT_LOSS
    return 1.0 + lift


def fill_built_colour(label: str) -> Vec3:
    """A fill's colour as built (FILL_BUILT_SRGB8), linear, as SetLightColor(bSRGB) takes it."""
    return linear3(FILL_BUILT_SRGB8[label])


def fill_warmth(elevation: float) -> float:
    """0 as built, up to 1 through the golden hour and the sunset (FILL_WARM_RISE/_FADE)."""
    return smoothstep(*FILL_WARM_RISE, elevation) * (1.0 - smoothstep(*FILL_WARM_FADE, elevation))


def fill_colours(elevation: float, morning: bool = False, overcast: float = 0.0) -> dict[str, Vec3]:
    """Each fill's colour: as built, except in the golden hour, where it takes FILL_WARM_SHARE of
    the key's hue at its own luminance (a channel over 1 scales the whole colour down), less under
    a cloud deck (no low sun gets through). At the reference every colour is exactly as built."""
    share = FILL_WARM_SHARE * fill_warmth(elevation) * (1.0 - overcast)
    out: dict[str, Vec3] = {}
    for label in FILL_BUILT_SRGB8:
        built = fill_built_colour(label)
        if share <= 0.0:
            out[label] = built
            continue
        key = key_colour(elevation, morning)
        tinted = (built[0] * key[0], built[1] * key[1], built[2] * key[2])
        tinted = scale3(tinted, luminance(built) / max(1e-9, luminance(tinted)))
        mixed = mix3(built, tinted, share)
        top = max(mixed)
        out[label] = scale3(mixed, 1.0 / top) if top > 1.0 else mixed
    return out


# ---------------------------------------------------------------- the real weather
def cloudiness(weather: Weather | None) -> float:
    """The real cloud cover, 0..1: the service's cloud cover, else its condition's; 0 without a
    weather (D5: the clear sky of the real hour)."""
    if weather is None:
        return 0.0
    if weather.cloud_cover is not None:
        return min(1.0, max(0.0, weather.cloud_cover / 100.0))
    return CONDITION_CLOUD.get(weather.condition or "", 0.0)


def precipitating(weather: Weather | None) -> bool:
    """Whether rain, showers or snow are falling now (the observation's own sums or condition)."""
    if weather is None:
        return False
    now = (weather.rain_mm, weather.showers_mm, weather.precipitation_mm, weather.snowfall_cm)
    return any(v is not None and v > 0.0 for v in now) or weather.condition in PRECIPITATING


def overcast_weight(weather: Weather | None) -> float:
    """0 under a clear or broken sky, 1 under a closed deck (and whenever it rains or snows); 0
    for every weather while the weather's look is held (WEATHER_LOOK)."""
    if not WEATHER_LOOK:
        return 0.0
    if precipitating(weather):
        return 1.0
    return smoothstep(OVERCAST_FROM, 1.0, cloudiness(weather))


def rain_look(weather: Weather | None) -> bool:
    """Whether the scene shows falling rain (a darker sky, a traced road): only while the weather's
    look is on (WEATHER_LOOK) and rain really falls."""
    return WEATHER_LOOK and precipitating(weather)


def greyed(colour: Vec3, share: float) -> Vec3:
    """``colour`` moved ``share`` toward the grey of its own luminance."""
    if share <= 0.0:
        return colour
    y = luminance(colour)
    return mix3(colour, (y, y, y), share)


def night_weight(elevation: float) -> float:
    """0 in civil twilight, 1 from nautical twilight's end down: how much the city's glow shows."""
    return smoothstep(*NIGHT_GLOW_RISE, elevation)


def city_windows(sun: Sun) -> float:
    """The city's lit windows before the day dims them: the dusk's 1 on the evening side and in
    the deep night, DAWN_CITY_WINDOWS through the dawn."""
    if not sunrise_side(sun):
        return 1.0
    return mix(1.0, DAWN_CITY_WINDOWS, smoothstep(*DAWN_CITY_RISE, sun.elevation_deg))


def windows_share(elevation: float) -> float:
    """The share of the dusk's lit tower windows lit at this real elevation, on the evening side
    (WINDOWS_* above): 0 from WINDOWS_OFF_ABOVE up (the glare), WINDOWS_MOST at WINDOWS_MOST_AT,
    1 at and below the reference dusk. Smoothsteps between, so it never jumps."""
    if elevation >= WINDOWS_OFF_ABOVE:
        return 0.0
    if elevation >= WINDOWS_MOST_AT:
        return WINDOWS_MOST * smoothstep(WINDOWS_OFF_ABOVE, WINDOWS_MOST_AT, elevation)
    if elevation > REFERENCE_DUSK_ELEVATION:
        return mix(
            WINDOWS_MOST, 1.0, smoothstep(WINDOWS_MOST_AT, REFERENCE_DUSK_ELEVATION, elevation)
        )
    return 1.0


def tower_windows_share(sun: Sun) -> float:
    """The skyline's share lit for the real sun: the evening's curve, capped on the morning side
    by the city's dawn rule (city_windows: DAWN_CITY_WINDOWS from -6 deg up), so the dawn lights
    fewer windows than the dusk at the same low elevation, and the curve's own once it lights
    fewer than the cap. A ceiling, not a second dimming: the two multiplied left 07:25's skyline
    windowless (run 2). Continuous at solar midnight, where both are 1."""
    return min(windows_share(sun.elevation_deg), city_windows(sun))


def near_windows_floor(elevation: float) -> float:
    """The fewest of their dusk windows the near blocks light: NEAR_WINDOWS_FLOOR while the sun
    is low, fading out over NEAR_WINDOWS_FLOOR_FADE as it climbs, 0 by day."""
    return NEAR_WINDOWS_FLOOR * smoothstep(*NEAR_WINDOWS_FLOOR_FADE, elevation)


def near_windows_share(sun: Sun) -> float:
    """The near blocks' share lit for the real sun: the skyline's (tower_windows_share), never
    below their own floor, so a lit near block never goes black. Monotone on both sides, since
    both parts are."""
    return max(tower_windows_share(sun), near_windows_floor(sun.elevation_deg))


def windows_on(share: float) -> float:
    """M_HQ_TowerDay's WindowsOn that lights ``share`` of the dusk's lit windows: 0 (none) at 0,
    exactly 1 (every window, the material's default, the dusk) at 1. Between them the gate's
    half-lit rank sweeps the ranks' range, widened by one gate width so the ends meet: just above
    0 no window is lit, just below 1 every one is fully lit, so neither end jumps. (towers_day.py's
    RANK_MIN + span x share lit about 1 % fewer than asked and stepped the top windows at 1.)"""
    if share <= 0.0:
        return 0.0
    if share >= 1.0:
        return 1.0
    span = TOWER_RANK_MAX - TOWER_RANK_MIN + 1.0 / TOWER_GATE_SHARPNESS
    return TOWER_RANK_MIN + span * share


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
def dawn_plate_elevation(elevation: float) -> float:
    """The elevation the dawn's plate is taken at: DAWN_PLATE_SHIFT deeper than the real sun
    before the glow's peak, the real elevation again from DAWN_PLATE_SHIFT_FADE's end. Deeper
    cells carry a thinner, bluer glow; the mapping only rises, so the plate never jumps back."""
    return elevation - DAWN_PLATE_SHIFT * (1.0 - smoothstep(*DAWN_PLATE_SHIFT_FADE, elevation))


def sky_plates(sun: Sun, weather: Weather | None = None) -> dict[str, float]:
    """The atlas cells and the blend between them, and the backdrop's gain.

    The blend is not linear in elevation: it is where the real elevation's (daylight, dusk) pair
    - compose's own two functions - falls between the two cells' pairs, so a blended plate reads
    as the plate compose would have made at that elevation. The dawn takes a deeper sun's plate
    (dawn_plate_elevation), a cooler and bluer sky. A closed cloud deck takes the atlas' most
    honest overcast pair (OVERCAST_PLATES) below OVERCAST_CLEAR_FROM, dimmer in the dusk, and
    the clear hour's plate above it (no cell is a grey deck); rain lowers the gain. At night the
    gain rises with the city's glow (NIGHT_SKY_GAIN_BOOST). At the reference it is today's plate."""
    e = sun.elevation_deg
    morning = sunrise_side(sun)
    mirror = 1.0 if morning else 0.0  # the glow on the sun's side: right mornings
    cells = ATLAS_ELEVATIONS
    overcast = overcast_weight(weather)
    gain = SKY_GAIN
    if night_weight(e) > 0.0:
        gain *= 1.0 + NIGHT_SKY_GAIN_BOOST * night_weight(e)
    if overcast > 0.0:  # a dimmer deck in the dusk; by day the clear hour's, through the fog
        daylight = plate_daylight(e)
        gain *= mix(
            1.0 - OVERCAST_GAIN_LOSS * overcast, 1.0 + OVERCAST_DAY_LIFT * overcast, daylight
        )
    if rain_look(weather):
        gain *= 1.0 - RAIN_GAIN_LOSS
    if overcast >= OVERCAST_PLATE_FROM and e < OVERCAST_CLEAR_FROM:
        low, high = OVERCAST_PLATES
        return {
            "PlateA": low,
            "PlateB": high,
            "PlateBlend": plate_daylight(e),
            "Mirror": mirror,
            "Gain": gain,
        }
    if e <= cells[0]:
        return {"PlateA": 0, "PlateB": 0, "PlateBlend": 0.0, "Mirror": mirror, "Gain": gain}
    if e >= cells[-1]:
        last = len(cells) - 1
        return {
            "PlateA": last,
            "PlateB": last,
            "PlateBlend": 0.0,
            "Mirror": mirror,
            "Gain": gain,
        }
    if morning:
        e = dawn_plate_elevation(e)
        if e <= cells[0]:
            return {"PlateA": 0, "PlateB": 0, "PlateBlend": 0.0, "Mirror": mirror, "Gain": gain}
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
    return {"PlateA": i, "PlateB": i + 1, "PlateBlend": t, "Mirror": mirror, "Gain": gain}


# ---------------------------------------------------------------- the road
def road(weather: Weather | None) -> dict[str, Any]:
    """The asphalt's roughness from real rain only: a traced water film while rain is falling
    (RAIN_ROAD_ROUGHNESS), the build's damp road when rain fell in the last three hours, dry when
    the record says none fell, today's (damp) when that cannot be known."""
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
    if raining and WEATHER_LOOK:
        # a water film while it falls: the lamps and the shopfronts traced in the road
        return {
            "Roughness Min": RAIN_ROAD_ROUGHNESS[0],
            "Roughness Max": RAIN_ROAD_ROUGHNESS[1],
            "wetness": 1.0,
            "source": "observed",
        }
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
    weather = world.weather
    overcast = overcast_weight(weather)
    rain = 1.0 if rain_look(weather) else 0.0
    glow = night_weight(e)
    morning = sunrise_side(sun)

    day_haze = scale3(linear3(srgb_bytes(DAY_HAZE_SRGB)), DAY_HAZE_STRENGTH)
    haze: dict[str, dict[str, Any]] = {}
    for label in HAZE_LABELS:
        dusk_colour = HAZE_RIGHT if label.endswith("right") else HAZE_LEFT
        opacity = HAZE_OPACITY * (HAZE_FAR_SHARE if "_far_" in label else 1.0)
        # exactly today's at the reference: dim is 1 and day 0 there, and a + (b - a) * 0 == a
        colour = mix3(scale3(dusk_colour, dim), day_haze, day)
        colour = golden_air(colour, e, morning)
        if glow > 0.0:  # the city's warm glow on the low air at night
            colour = mix3(colour, CITY_GLOW_HAZE, glow)
        if overcast > 0.0:  # a greyer, denser haze under cloud, the deck's light grey by day
            colour = greyed(colour, OVERCAST_GREY * overcast)
            colour = mix3(colour, DECK_HAZE, overcast * plate_daylight(e))
            opacity = min(HAZE_OPACITY_MAX, opacity * (1.0 + OVERCAST_HAZE_OPACITY * overcast))
        haze[label] = {"HazeColor": colour, "Opacity": opacity}

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
    if overcast > 0.0:  # under the deck the dome is the main light, and neutral
        sky_intensity *= deck_sky_light(e, overcast, rain > 0.0)
        sky_colour = greyed(sky_colour, overcast * day)

    fog_day = linear3(srgb_bytes(DAY_HAZE_SRGB))  # Blender's day haze colour, unscaled
    fog = mix3(scale3(FOG_DUSK, dim), fog_day, day)
    fog = golden_air(fog, e, morning)
    if glow > 0.0:
        fog = mix3(fog, CITY_GLOW_FOG, glow)
    if overcast > 0.0:
        fog = scale3(greyed(fog, OVERCAST_GREY * overcast), 1.0 - OVERCAST_FOG_DIM * overcast)
    fog_density = FOG_DENSITY
    if overcast > 0.0 or rain > 0.0:
        fog_density = FOG_DENSITY * (1.0 + OVERCAST_FOG * overcast + RAIN_FOG * rain)

    reason = world.weather_reason
    if weather is None:
        note = WEATHER_NOTES.get(reason or "", "Vremea nu este disponibilă.")
    elif reason == "stale":
        note = "Serviciul meteo nu răspunde: scena păstrează ultima observație reală."
    else:
        note = None

    city = mix(city_windows(sun), CITY_DAY_EMISSION, day)
    # where WindowsOn counts the towers' windows the dawn's fewer windows are fewer windows, not a
    # dimmer city: the glow keeps only the day's dimming (the evening side is the same as city)
    counted = mix(1.0, CITY_DAY_EMISSION, day)
    sun_light = sun_intensity(e)
    if overcast > 0.0:
        sun_light *= 1.0 - OVERCAST_SUN_LOSS * overcast
    return {
        # the direct sun: the Movable light, lit only above the horizon
        "sun": {
            "elevation_deg": e,
            "azimuth_deg": sun.azimuth_deg,
            "intensity": sun_light,
            "color": sun_colour(e, morning),
            "rotation": sun_rotation(sun, frame) if frame is not None else None,
        },
        # the sky over the sunset (or the sunrise): the Stationary keys, intensity and colour only
        "twilight": twilight_keys(sun, overcast),
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
            # StreetFill: the sky's light on the road and the front pavement, on the noon's budget
            # above -2 deg, up to its build level with the lamps below
            "fills": fill_factor(e, overcast, rain > 0.0),
            # FacadeLight: the sky's light on the facade, on with the lamps below -2 deg
            "facade": facade_factor(e, overcast, rain > 0.0),
            # the shopfronts' spill on the pavement: with StreetFill, never above its build level
            "walk_wash": walk_wash_factor(e, overcast, rain > 0.0),
            "car_lights": on,
        },
        # the fills' colour (each by its label): as built, warmed with the key in the golden hour
        "fill_colors": fill_colours(e, morning, overcast),
        "sky": sky_plates(sun, weather),
        "emissive_factor": {"skyline": city, "near_blocks": city},
        # the room windows' picture: dusk at the reference, the day picture by day, the night
        # state from the reference down to -12 deg (the same weight the sky light and the haze
        # darken by), so no window shows the dusk horizon in the night
        "window_view": {"DayBlend": day, "NightBlend": night},
        # the near blocks' darkest plain slots (M_HQ_CityDay, look_hq_live.near_blocks_day): their
        # dusk colour at 0, their own hue at a facade's albedo by day, by the same day weight; the
        # rejected rebuild showed them as black cardboard at noon
        "near_blocks_day": {"Daylight": day},
        # the day state (sent only where the report's "day_state" names the components): the
        # facades' day colours by the same day weight and their lit windows by the real sun
        # (M_HQ_TowerDay), one value per tower component by its label (the skyline's curve, the
        # near blocks' with their own floor), the leaves' own albedo by day (M_HQ_TreeLeaves),
        # the skyline's plain slots' day colour (M_HQ_CityDay, as the near blocks'); at the
        # reference every value is the material's default, TowerDaylight 0, WindowsOn 1,
        # LeafDaylight 0, Daylight 0
        "towers": {
            "skyline": {
                "TowerDaylight": day,
                "WindowsOn": windows_on(tower_windows_share(sun)),
            },
            "near_blocks": {
                "TowerDaylight": day,
                "WindowsOn": windows_on(near_windows_share(sun)),
            },
        },
        "trees": {"LeafDaylight": day},
        "skyline_day": {"Daylight": day},
        # the towers' glow where WindowsOn counts their windows (the day state): today's by day
        # and in the evening, without the dawn's dimming, which WindowsOn carries instead
        "emissive_factor_counted": {"skyline": counted, "near_blocks": counted},
        "haze": haze,
        "fog": {"inscattering": fog, "density": fog_density},
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
