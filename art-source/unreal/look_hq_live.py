"""
Unreal Engine 5.8 editor script: the look pass on the live headquarters (/Game/HQ/HQ_Dusk), applied
to the saved level in place, so the light can be tuned against the Owner's picture without
re-importing the Blender export. Run it after build_hq_scene.py and dress_hq_live.py, with the
stream stopped (the streamed game holds the level's packages):

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=look_hq_live.py

What the picture has and the first live passes did not (compared region by region, 2026-09-15):
soft, warm room light where the level threw hard coloured spot cones on the walls; a glowing, graded
dusk where the level was flat and crushed to black; a skyline of sparse lit windows in blue haze
where the level showed bright blocks with no depth; street lamps and headlights that light the
road without burning white patches on it; wet asphalt.

Every value is absolute (never a factor on the level's current value), so running the script again
gives the same level. Each tunable comes from the environment (AMN_LOOK_*).

The values here are the dusk the Owner approved, and they stay the build's values: the backend
moves the lights, the haze, the road and the room windows from them to the real hour over Remote
Control, by the labels env_report_hq_live.py records. The room windows keep the glTF instance and
its dusk picture as before; their day and night pictures ride on a copy of its parent chain, with
DayBlend and NightBlend at 0 by default (window_view.py).
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
META = json.load(open(os.path.join(HERE, "hq_scene.json"), "r", encoding="utf-8"))
BASELINE = os.path.join(HERE, "look_baseline.json")


def env(name, default):
    return float(os.environ.get(name, default))


# the build's own light balance (build_hq_scene.py), so a light's base is energy x lumens per watt
LUMENS_INTERIOR = env("AMN_LM_INTERIOR", os.environ.get("AMN_LM_PER_W", "1.0"))
LUMENS_EXTERIOR = env("AMN_LM_EXTERIOR", os.environ.get("AMN_LM_PER_W", "70"))
# L2 at 0.52 (0.6, and 0.7 before that): with a seventh pendant over its left end - which had no lamp
# of its own and read 29 short of the picture there - the floor came out brighter than the picture
# (81.8 against 78.8). At 0.52 its region 8.7 -> 6.5 and the mean 5.3 -> 5.1.
# L1 at 0.5 (0.7 before, 2026-09-16, once the render bay's panel was lit): its region 11.6 -> 8.6
# (its light 58 against the picture's 51), ssim 0.183 -> 0.196, mean 6.6 -> 6.3
# L3 at 0.38 (0.3 before): once the streamed game ran at Epic quality the room read darker than the
# picture (72.8 against 79.7) and its region went 8.0 -> 11.4; at 0.38 it is 6.4 and the mean 6.0.
# L1 at 0.6 and the ground floor at 0.58 (0.45 and 0.55): once the street lamps stopped washing the
# building's front (street_channel), both read darker than the picture. L1's region 10.5 -> 6.4,
# the mean 5.6 -> 5.2.
# The streamed game renders at half again its own width (r.ScreenPercentage 150, for the detail the
# Owner asks for) and Lumen then carries less of the rooms' bounce: at the old gains every floor lost
# about a tenth of its light (L3 79.7 -> 66.0 against the picture, its region 5.1 -> 23.1). These
# gains put each floor back on the picture's light: L4 64.2/63.7, L3 79.7/79.1, L1 51.2/50.7, the
# ground floor 68.2/69.1. Raising the area fills with them (AMN_LOOK_FILL 1.9) lit the lobby too
# brightly (the ground floor 5.7 -> 12.9), so the fills stay at 1.4.
# L3 then took its own rebuild: a lighter floor, five ceiling pools and two small warm fills in
# place of one 9 m blue wash. That room carries its own light now, so its gain comes back from
# 0.66 to 0.40 and it reads the picture's 79.7 exactly (its region 5.1 -> 2.7, its ssim 0.14 ->
# 0.32). L4, whose cove was cut to the two stretches the picture lights, goes the other way to 1.15.
# The ground floor comes down to 0.58 once its shopfronts got the picture's own lit lines - a
# line under each header, a strip down every mullion and a lit sill: its region 8.2 -> 5.2.
LEVEL_GAIN = {int(k): float(v) for k, v in (pair.split(":") for pair in os.environ.get("AMN_LEVEL_GAIN", "0:0.58,1:0.84,2:0.73,3:0.40,4:1.15").split(",") if ":" in pair)}
CEILINGS_M = [(655 - row) / 27.575 for row in (520, 410, 297, 195)]

# the look: factors on that base, per kind of light. Pass 1 (spot 0.45, road 0.12, city 0.45, fog
# 0.006 from 35 m, EV +0.35, bloom 1.1) made every region brighter than the picture (mean colour
# distance 24.2 -> 29.6), kept the green cones on L4's wall and turned the road into a mirror of
# the shopfronts. The defaults below are the balance of the closest full pass (with the pack plants,
# paintings and wet asphalt: mean colour distance 15.8): spot 0.15, fills 1.4, lamps 0.5, city 0.5,
# fog 0.008 from 30 m, no exposure offset. Lamps at 0.8 lit the lift tower and the ground floor and
# left the road as dark.
# 0.10 with a wider, softer cone (below): at 0.15 the rows of spots drew hard discs on every wall
# where the picture has a wash that fades down from the cove. Judged by eye first; the numbers
# followed (L4 4.7 -> 2.4, L1 4.0 -> 4.9 either way, L3 kept its five pools at 3.4).
SPOT = env("AMN_LOOK_SPOT", "0.10")          # interior spot rows: the hard cones on the walls
SPOT_SOFT = env("AMN_LOOK_SPOT_SOFT", "0.45")  # inner cone as a share of the outer: a soft edge
SPOT_WIDEN = env("AMN_LOOK_SPOT_WIDEN", "26")  # degrees added to the outer cone: a wash, not a disc
POINT = env("AMN_LOOK_POINT", "2.0")         # pendants, desk and floor lamps: the warm pools
FILL = env("AMN_LOOK_FILL", "1.4")           # the rooms' area fills
# the lobby's fills and spill, on top of FILL: at 0.75 the ground floor's region still read 81 against
# the picture's 66 (colour distance 25.7 once the S1 LEDs were lit); at 0.55 25.7 -> 18.8, mean 14.4 -> 13.7;
# at 0.4 18.8 -> 12.7 and the street 15.4 -> 11.5 (the lobby's spill had lit the pavement too), mean 12.8;
# at 0.3 the ground region 8.3, mean 12.6. Lower is not worth it: the floor's lower rows already read a
# little darker than the picture, only its upper rows brighter.
# The picture's lobby is its brightest, warmest room - golden glass, lit plants, a lit wall behind
# the logo - and at 0.3 ours was the darkest thing on the ground floor. 1.2 burnt it (85.8 against
# 68.2), 0.6 reads right by eye and over by the mean; 0.5 is the balance.
LOBBY = env("AMN_LOOK_LOBBY", "0.5")
# Street lamps: at full they burnt white pools on the road. Once they were taken off the building
# (street_channel), their own pools still read 23 to 27 brighter than the picture's over the
# columns they stand in; at 0.35 the street's region 6.6 -> 5.5 but the pavement in front of the
# shopfronts went dark (the ground floor 5.6 -> 6.2). 0.42 split it.
# 0.16 (0.42 before, 2026-09-16). At 0.42 the pools were still burning: over the pavement they read
# 138.7 and 199.1 against the picture's 48.7 and 66.4, their 99th percentiles clipped at 253 and 251
# against its 160, and 69.6 % of the band under the right-hand lamp sat over luma 200 where the
# picture has none of it. That is the whole of the street's contrast gap (42.9 against 31.2). What
# went dark before was the middle of the pavement, and the picture does not light that with lamps at
# all - it lights it with the shopfronts behind it, so WALK_WASH below carries it now and the lamps
# only have to make their own pools. Swept over the six board frames' tone with that wash: the
# street's contrast 41.8-43.4 -> 30.6-33.4 (the picture's 31.2) and its colour 6.1-7.5 -> 3.8-5.0.
# 0.32, not the 0.16 the pools alone asked for: at 0.16 the trees and bushes down the left of the
# frame, which these lamps are the only light for, went 7 short of the picture (the city left
# 3.9 -> 12.0). With the soft source below, 0.32 no longer clips the pools.
LAMP = env("AMN_LOOK_LAMP", "0.32")
# A lamp-sized source and a wide soft one for the three street lamps. At the 6 cm source every point
# light gets they were points five metres over wet pavement, and their pools had a clipped core with a
# hard edge; the picture's lamps lay a soft wash. Only the street lamps: indoors a small source is
# what the pendants and desk lamps want.
LAMP_RADIUS = env("AMN_LOOK_LAMP_RADIUS", "25")
LAMP_SOFT = env("AMN_LOOK_LAMP_SOFT", "120")
# The infra room's own fill. In the picture S1 is a lit room: the racks stand as cabinets with
# their own edges, on a floor you can see. Ours was a flat dark wall with LED dots on it.
INFRA = env("AMN_LOOK_INFRA", "1")
# The treasury's own lights. Against the picture that shopfront reads 12 short of red and 13 of
# green over its columns: the picture's operations room is a lit room, ours a dark red one.
# 3 (1 before): the picture's operations room is lit, and with the slate walls ours read 20 to 40
# short over its columns.
# What OPS reaches: only names starting "ops_" that no earlier branch claims. factor_for tests
# SPOT_NAMES ("ops_spot") and POINT_NAMES ("ops_shelf_lamp") first, so from 2026-09-16 that is the
# ops_wash_* pair washing the treasury's back wall, and nothing else. Do not move the "ops_"
# branch above SPOT to "fix" this: it would take ops_spot_a and ops_spot_b from 0.15 to 3.
OPS = env("AMN_LOOK_OPS", "3")
# tree uplights: the leafy crowns read too bright at 0.6, and at 0.3 the city left of the building
# still came 12.1 against the picture (its light 71 against 63). At 0.15: city left 11.7, the
# street 7.5 -> 6.8, the ground floor 3.9 -> 3.4, mean 7.1 -> 6.9.
UPLIGHT = env("AMN_LOOK_UPLIGHT", "0.15")
# the small warm lights under each office ceiling (hq_building.ceiling_cove): at 1.0 the rooms read too
# bright (mean 15.7; L2 88 against the picture's 79), at 0.35 the closest pass so far (14.5)
# 0.6 (0.35 before): once the game ran at Epic the rooms took the wash better, and the picture's
# ceiling band is a wide warm glow down the wall. L4 3.3 -> 1.9, L3 7.0 -> 5.3, mean 5.9 -> 5.7.
COVE = env("AMN_LOOK_COVE", "1.0")
HEADLIGHT_LM = env("AMN_LOOK_HEADLIGHT_LM", "900")
TAILLIGHT_LM = env("AMN_LOOK_TAILLIGHT_LM", "160")
CITY = env("AMN_LOOK_CITY", "0.5")           # skyline window emission, on the imported value
# The skyline's windows are the export's tiling window textures, one window per 0.16-0.28 m cell:
# about 6 x 9 px in the live frame, where the picture's towers have windows of 2-3 px. The texture
# scale on the facade materials (glTF OffsetScale): 2 halves each window; 1 leaves the export's size.
# At 2 the towers read finer by eye, but the frame moved away from the picture (mean 14.7 -> 14.9, the
# city right of the building 11.9 -> 14.1), so the export's size stays.
CITY_WINDOW_SCALE = env("AMN_LOOK_CITY_WINDOW_SCALE", "1")
# The warm LED strips under each floor's ceiling and along the frame (edge_led_slab, edge_led_warm,
# edge_led): in the picture a bright band that washes the top of each room's wall, live a thin line.
# A factor on their imported emission strength (recorded once in look_baseline.json); 1 leaves them.
# At 3 the top floor's strip reads brighter and L4 came closer to the picture (7.8 -> 5.5; the roof
# sign 9.1 -> 10.2, the mean unchanged at 14.7). L3 and L2 have no ceiling strip in the scene at all:
# those are for the Blender scene, not this factor. Since hq_building.ceiling_cove() hangs a line of
# the same material under every office ceiling, 3 made those lines burn (129 and 103 against the
# picture's 64 and 62 in their rows); at 1.5 the mean is 14.1 (14.5 at 3), at 1 (the imported
# strength) 13.9, the closest: roof sign 11.8, L4 1.4, L1 9.2.
STRIP_MATERIALS = ("edge_led_slab", "edge_led_warm", "edge_led")
# 0.5 (1, the imported strength, before): with the ceiling cove at 0.6 the strips read as a white
# line along every ceiling where the picture has a warm glow. At half, L2 7.5 -> 6.6, the street
# 6.5 -> 6.1 and the mean 5.7 -> 5.6.
STRIP_GAIN = env("AMN_LOOK_STRIP_GAIN", "0.8")
ROAD_ROUGH = env("AMN_LOOK_ROAD_ROUGH", "0.32")  # wet, not a mirror (only for the imported asphalt)
ROAD_SPECULAR = env("AMN_LOOK_ROAD_SPECULAR", "0.5")
# the wet asphalt instance dress_hq_live.py puts on the road (its roughness texture is remapped to this
# range), and the roughness up to which Lumen traces real reflections (the engine's own default is
# 0.4, so most of the road at 0.25-0.5 fell back to a dull reflection without the lights' streaks)
ROAD_MI = "/Game/HQ/Materials/MI_HQ_AsphaltWet"
# 0.25-0.5 over the road and 0.4 traced: the asphalt read flat, where the picture's carries the
# shopfronts and the cars' lights in long streaks. At 0.1-0.32, with Lumen tracing reflections up
# to 0.6 roughness, the lights lie on the road as they do in the picture (its region 7.0 -> 7.5,
# the mean held at 6.4: the road is darker where it has nothing to reflect).
# 0.08-0.24 (0.1-0.32): with the pavement wet as well, the picture's streaks appear. Tried
# 0.03-0.16: the road turned into water, a full mirror of the building, and its region went
# 6.0 -> 10.3.
# 0.14-0.38 traced to 0.5 (0.08-0.24 to 0.6 before, 2026-09-16): at 0.08-0.24 the road had gone past
# wet and become a mirror, so its tone was only ever what it reflected and there was nothing between
# the streaks. The far lane read 52.6 against the picture's 69.1 and the near lane 51.7 against 62.8;
# 14.3 % of the far lane sat under luma 30 where the picture has 8.4 %, and the painted crossing read
# 61.8 against 80.5 because it was showing its own reflection rather than its paint. One step back
# towards the pass before this one (0.1-0.32), which is where the streaks first appeared.
ROAD_ROUGH_MIN = env("AMN_LOOK_ROAD_ROUGH_MIN", "0.14")
ROAD_ROUGH_MAX = env("AMN_LOOK_ROAD_ROUGH_MAX", "0.38")
TRACE_ROUGHNESS = env("AMN_LOOK_TRACE_ROUGHNESS", "0.5")
# The building's frame (the Blender scene's dark blue metal, 0.5-0.6 metallic) renders black in the
# live frame where the picture's frame is a lit grey: metal shows only what it reflects, and the dusk
# around it is dark. AMN_LOOK_FRAME_METAL sets those materials' metallic factor (below 0 leaves them).
# Tried at 0.1 on all 8 frame materials (2026-09-15): no visible change and no region moved, so the
# frame is black for want of light on it, not for its metal; left off.
FRAME_MATERIALS = ("frame_dark", "frame_hi", "slab")
FRAME_METAL = env("AMN_LOOK_FRAME_METAL", "-1")
# ...so the frame gets its own light: a wide, cool area light in front of the building facing it, on
# lighting channel 1, which only the "shell" actor (frame, stone, plinth, glass, roof; the rooms and
# their props are other actors) also receives. Lumens; 0 turns it off. Compared in the stream (mean
# colour distance, 15.0 without): 20,000 lm over the whole front 39.6 (a white frame); 3,000 lm 20.5
# (slate grey); 800 lm 15.4 (the upper floors closer, the ground floor and lift tower too bright);
# 800 lm held to the floors above the ground floor (below) 14.6, a dark navy frame like the picture's.
FACADE = env("AMN_LOOK_FACADE", "800")
FACADE_Y = env("AMN_LOOK_FACADE_Y", "-10")  # Blender metres in front of the building's front (y 0)
FACADE_ACTOR = "shell"
FOG_DENSITY = env("AMN_LOOK_FOG", "0.008")    # 0.02 greyed the street and brightened the sky
FOG_START_CM = env("AMN_LOOK_FOG_START", "3000")
# Distances are from the plate camera, 246 m in front of the building (the street at ~220 m, the
# building's back at ~262 m, the skyline's towers at 264-315 m, the sky backdrop at ~340 m). Past
# the cutoff nothing is fogged (0 = no cutoff), so the skyline can take haze the sky backdrop does not.
FOG_CUTOFF_CM = env("AMN_LOOK_FOG_CUTOFF", "0")
EXPOSURE = env("AMN_LOOK_EV", "0")
# The frame reads more contrasty than the picture everywhere (its street 45.9 against 31.2, its city
# 42.7 against 35.3): the picture is a softer, hazier dusk. Tried softer: at 0.94 the contrast gap
# closed (6.2 -> 4.7) and ssim rose, but lowering contrast lifts the mid-tones, so every region came
# out brighter than the picture and the mean went 5.1 -> 7.6; at 0.98 with a tenth of a stop less
# exposure, 5.9. The softness the picture has is in its haze, not in its grade, so this stays.
CONTRAST = env("AMN_LOOK_CONTRAST", "1.05")
BLOOM = env("AMN_LOOK_BLOOM", "0.8")
# The road and the near pavement: no lamp reaches them (the lamps' pools stay on the far pavement)
# and the dusk sky light alone left them at 15-45 of 255 where the picture's are a lit, cool grey at
# 55-100 (mean colour of the street's bands, 2026-09-15). Lumens of a wide cool area light straight
# down over them; 0 turns it off. Compared in the stream (street region colour distance, 28.4 without):
# 4000 lm over the near pavement (y -24 m, 24 m across) 20.3, the pale pavement overshot lavender;
# 6000 lm over the road (y -16 m, 16 m) 46.4, a flat grey street; 3000 lm at y -16 m 18.2; 3000 lm
# at y -19 m, 14 m across 13.5 (mean over all regions 15.6, the closest pass so far).
# 3300 (3000 before): the wetter road reflects rather than scatters, so the street read darker than
# the picture once the reflections came in (57.7 against 60.6). At 3600 it overshot to 64.8.
STREET_FILL = env("AMN_LOOK_STREET_FILL", "3300")
# -18 (-19 before): 14 m deep centred at -19 the fill covered y -26 to -12 while the road runs -23 to
# -9, so its near three metres landed on the near pavement instead - rows 786 to 800 read 75.4 against
# the picture's 62.4. At -18 it covers -25 to -11 and sits on the road it is for.
STREET_FILL_Y = env("AMN_LOOK_STREET_FILL_Y", "-18")          # Blender metres; the road spans -23 to -9
STREET_FILL_DEPTH = env("AMN_LOOK_STREET_FILL_DEPTH", "1400")  # cm across the street
STREET_FILL_COLOR = unreal.LinearColor(0.7, 0.73, 0.88, 1.0)

# The picture's pavement is lit by the shopfronts behind it: a dome, 85 to 96 of 255 over the middle
# columns, falling to 38 to 60 at both ends of the frame. Ours was the other way round - two burnt
# pools under the street lamps (124 to 151 over columns 200-450 and 1275-1600, against the picture's
# 43 to 72) with a trough of 44 to 75 between them, a mean column error of 32.2. With the lamps down
# to LAMP this warm wash puts the dome back: a rect light five metres over the pavement, pointing
# down, as wide along the frame as the building's own front so it falls away towards both ends, warm
# like the shopfronts rather than cool like the dusk, and on the street lamps' own lighting channel so
# that like them it never washes the building behind. Swept over the live frames' tone, a dome of +18
# luma with a 15 m sigma took that column error 32.2 -> 19.0, where a flat wash of the same energy
# left it at 21.7. 1800 lm is the first estimate for this height and area, scaled from the street
# fill's 3300 over its own rect: if the middle still reads short of 85-96 try 2400, if it overshoots
# try 1200.
# 150 lm, not the 1800 the simulation asked for: at 1800 the pavement read 72 against the picture's
# 61 (the street's region 18.3), and once the pavement's own grain gave it something to catch the
# light with, 400 still left it at 67. At 150 the street is 4.8.
WALK_WASH = env("AMN_LOOK_WALK_WASH", "150")
WALK_WASH_Y = env("AMN_LOOK_WALK_WASH_Y", "-5.5")           # Blender metres; the pavement runs -8.78 to -2.34
WALK_WASH_WIDTH = env("AMN_LOOK_WALK_WASH_WIDTH", "2800")    # cm along the frame: the building's own front
WALK_WASH_DEPTH = env("AMN_LOOK_WALK_WASH_DEPTH", "700")     # cm across the pavement
WALK_WASH_COLOR = unreal.LinearColor(1.0, 0.88, 0.74, 1.0)
WALK_WASH_LABEL = "WalkWash"

SPOT_NAMES = ("spot", "ops_spot", "feature_spot")
POINT_NAMES = ("pendant", "desk_lamp", "floor_lamp", "render_lamp", "ops_shelf_lamp")
FILL_NAMES = ("l2_fill", "l3_fill", "infra_fill", "lobby_fill", "lobby_spill", "ai_fill", "ai_logo_glow")
LAMP_NAMES = ("lamp_far_left", "lamp_left", "lamp_right")
# what street_channel puts on lighting channel 2: the three lamps and the pavement wash, the lights
# that must reach the street and nothing of the building standing a metre behind them
CHANNEL_2_NAMES = LAMP_NAMES + (WALK_WASH_LABEL,)


def log(msg):
    unreal.log(f"AMN_LOOK {msg}")


def ue(x_m, y_m, z_m):
    """Blender metres -> Unreal centimetres (the importer maps Blender +y to Unreal -y)."""
    return unreal.Vector(x_m * 100.0, -y_m * 100.0, z_m * 100.0)


def level_of(z_m):
    for level, ceiling in enumerate(CEILINGS_M):
        if z_m < ceiling:
            return level
    return len(CEILINGS_M)


def base_lumens(item):
    if item["group"] == "lights_interior":
        return item["energy"] * LUMENS_INTERIOR * LEVEL_GAIN.get(level_of(item["location_m"][2]), 1.0)
    return item["energy"] * LUMENS_EXTERIOR


def factor_for(name):
    if name.startswith("lobby_"):
        return FILL * LOBBY
    if name.startswith(SPOT_NAMES):
        return SPOT
    if name.startswith(POINT_NAMES):
        return POINT
    if name.startswith("infra_"):
        return FILL * INFRA
    if name.startswith("ops_"):
        return OPS
    if name.startswith(FILL_NAMES):
        return FILL
    if name.startswith(LAMP_NAMES):
        return LAMP
    if name.startswith("tree_uplight"):
        return UPLIGHT
    if name.startswith("cove_wash"):
        return COVE
    return 1.0


def tune_lights(actors):
    by_name = {item["name"]: item for item in META["lights"]}
    counts = {}
    for label, actor in actors.items():
        comp = actor.get_editor_property("light_component") if isinstance(actor, unreal.Light) else None
        if comp is None:
            continue
        if label.startswith("car_"):
            head = "head" in label
            comp.set_intensity(HEADLIGHT_LM if head else TAILLIGHT_LM)
            counts["vehicle"] = counts.get("vehicle", 0) + 1
            continue
        item = by_name.get(label)
        if item is None:
            continue
        f = factor_for(label)
        comp.set_intensity(base_lumens(item) * f)
        if isinstance(comp, unreal.SpotLightComponent) and item["group"] == "lights_interior":
            # from the scene's own cone, not the level's current one, so a rerun does not widen again
            outer = min(80.0, item["cone_deg"] / 2.0 + SPOT_WIDEN)
            comp.set_outer_cone_angle(outer)
            comp.set_inner_cone_angle(outer * SPOT_SOFT)
            comp.set_editor_property("source_radius", 8.0)
            comp.set_editor_property("soft_source_radius", 30.0)
        if isinstance(comp, unreal.PointLightComponent) and not isinstance(comp, unreal.SpotLightComponent):
            # the street lamps get a lamp-sized source and a wide soft one: at 6 cm their pools had a
            # clipped core (99th percentile 253 and 251 against the picture's 160) and a hard edge
            street = label.startswith(LAMP_NAMES)
            comp.set_editor_property("source_radius", LAMP_RADIUS if street else 6.0)
            if street:
                comp.set_editor_property("soft_source_radius", LAMP_SOFT)
        counts[f"x{f:g}"] = counts.get(f"x{f:g}", 0) + 1
    log(f"lights tuned {counts}")


def baseline():
    """The skyline's imported emission strengths, recorded the first time so reruns stay absolute."""
    if os.path.exists(BASELINE):
        return json.load(open(BASELINE, "r", encoding="utf-8"))
    return {}


# ---------------------------------------------------------------- the city by day
# The skyline's and near blocks' windows go dark by day and light at dusk through ONE parameter the
# backend writes on each component: EmissiveFactor (k, k, k), k in 0..1, 1 = the dusk the Owner
# approved. The 2026-09-19 window measured why it could not: five slots of each component sat at the
# glTF EmissiveFactor 0, so env_report said uniform=False and the backend wrote nothing (a lit night
# city at 09:02 and 13:09). city_emissive.py holds the arithmetic and its reasons; tests/
# test_city_emissive.py holds city_emissive.py.
import importlib.util  # noqa: E402  (kept beside the only code that uses it)

_city_spec = importlib.util.spec_from_file_location("city_emissive", os.path.join(HERE, "city_emissive.py"))
_city = importlib.util.module_from_spec(_city_spec)
_city_spec.loader.exec_module(_city)

CITY_LABELS = ("skyline", "near_blocks")
# the near blocks' daytime colour: slots darker than this linear luminance are lifted to it by day,
# hue kept (city_emissive.day_albedo); 0 leaves every slot on its glTF instance (no day colour)
NEAR_DAY_FLOOR = env("AMN_LOOK_NEAR_DAY_ALBEDO", str(_city.DAY_ALBEDO_FLOOR))


def city_slot(mat, path, label, scalars, base, folds):
    """One slot of the skyline or the near blocks: its glow at the city gain as before, and its
    EmissiveFactor at 1, 1, 1 with any grey factor moved into its strength, so the backend's one
    factor scales it in proportion. A slot at factor 0 becomes factor 1, strength 0: dark at dusk
    as it was, and dark under whatever factor the backend writes. Returns True when the slot
    carries EmissiveStrength (the count the log has always given)."""
    mel = unreal.MaterialEditingLibrary
    vectors = [str(n) for n in mel.get_vector_parameter_names(mat)]
    has_strength = "EmissiveStrength" in scalars
    if has_strength and path not in base:
        base[path] = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
    factor_key = _city.baseline_key(path, "EmissiveFactor")
    if "EmissiveFactor" in vectors and factor_key not in base:
        c = mel.get_material_instance_vector_parameter_value(mat, "EmissiveFactor")
        base[factor_key] = [c.r, c.g, c.b]
    strength = base[path] * CITY if has_strength else None
    plan = _city.fold_emission(base.get(factor_key), strength)
    name = path.rsplit(".", 1)[-1]
    entry = name if plan["action"] != "cannot" else f"{name}: {plan['reason']}"
    folds.setdefault(label, {}).setdefault(plan["action"], []).append(entry)
    touched = False
    if plan["action"] == "fold":
        mel.set_material_instance_vector_parameter_value(mat, "EmissiveFactor", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
        mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", plan["strength"])
        touched = True
    elif has_strength:  # kept at 1, 1, 1, or a colour that cannot fold: the city gain as before
        mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", strength)
        touched = True
    if label == "skyline" and has_strength:
        scale = unreal.LinearColor(0.0, 0.0, CITY_WINDOW_SCALE, CITY_WINDOW_SCALE)
        for slot in ("BaseColorTexture", "EmissiveTexture"):
            mel.set_material_instance_vector_parameter_value(mat, f"{slot}_OffsetScale", scale)
        touched = True
    if touched:
        mel.update_material_instance(mat)
    return has_strength


def _root_path(mat):
    m, seen = mat, 0
    while isinstance(m, unreal.MaterialInstance) and seen < 16:
        parent = m.get_editor_property("parent")
        if parent is None:
            break
        m, seen = parent, seen + 1
    return m.get_path_name() if m is not None else ""


def city_day_master():
    """M_HQ_CityDay: what a glTF instance paints when it paints with factors alone (no picture of
    its own), plus a day colour. BaseColor = Lerp(BaseColorFactor, DayBaseColor, Daylight), so at
    Daylight 0 (its default, the build's value) it is the glTF instance's colour exactly; metallic
    and roughness are the factors; specular 0.5 x SpecularFactor (glTF's IOR 1.5, F0 0.04, which
    Unreal writes as 0.5); flat normal, no occlusion and no emission, which is what the glTF defaults
    give such a slot. Two-sided like MI_Default_Opaque_DS. No EmissiveFactor: the backend's city
    factor never reaches these slots, and they have no glow for it to reach."""
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(_city.DAY_MASTER):
        mat = unreal.load_asset(_city.DAY_MASTER)
        mel.delete_all_material_expressions(mat)
    else:
        folder, name = _city.DAY_MASTER.rsplit("/", 1)
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", True)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", value)
        return n

    def vector(name, x, y):
        n = node(unreal.MaterialExpressionVectorParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
        return n

    colour = node(unreal.MaterialExpressionLinearInterpolate, -300, 0)
    mel.connect_material_expressions(vector("BaseColorFactor", -700, -150), "RGB", colour, "A")
    mel.connect_material_expressions(vector("DayBaseColor", -700, 50), "RGB", colour, "B")
    mel.connect_material_expressions(scalar(_city.DAY_PARAMETER, 0.0, -700, 250), "", colour, "Alpha")
    mel.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(scalar("MetallicFactor", 0.0, -300, 250), "", unreal.MaterialProperty.MP_METALLIC)
    mel.connect_material_property(scalar("RoughnessFactor", 1.0, -300, 350), "", unreal.MaterialProperty.MP_ROUGHNESS)
    specular = node(unreal.MaterialExpressionMultiply, -300, 450)
    mel.connect_material_expressions(scalar("SpecularFactor", 1.0, -500, 450), "", specular, "A")
    specular.set_editor_property("const_b", 0.5)
    mel.connect_material_property(specular, "", unreal.MaterialProperty.MP_SPECULAR)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


def near_blocks_day(actors):
    """The near blocks' plain slots (a glTF instance painting with factors alone, emitting nothing)
    darker than NEAR_DAY_FLOOR get their own instance of M_HQ_CityDay: the same colour at
    Daylight 0, their own hue at a facade's albedo at Daylight 1. Every other slot - the facades
    with their window pictures, the shop fronts, the glowing dashes, anything already as light as
    the floor - stays on its glTF instance, untouched."""
    if NEAR_DAY_FLOOR <= 0:
        log("near blocks by day: off (AMN_LOOK_NEAR_DAY_ALBEDO 0)")
        return
    actor = actors.get("near_blocks")
    if not isinstance(actor, unreal.StaticMeshActor):
        log("near blocks by day: NO near_blocks actor")
        return
    mel = unreal.MaterialEditingLibrary
    comp = actor.static_mesh_component
    master, lifted, left = None, [], []
    for i in range(comp.get_num_materials()):
        mat = comp.get_material(i)
        if not isinstance(mat, unreal.MaterialInstanceConstant):
            continue
        name = mat.get_name()
        ours = name.startswith(_city.DAY_MI_PREFIX)
        vectors = [str(n) for n in mel.get_vector_parameter_names(mat)]
        scalars = [str(n) for n in mel.get_scalar_parameter_names(mat)]
        if "BaseColorFactor" not in vectors:
            continue
        if not ours:
            if not _root_path(mat).startswith(_city.GLTF_ROOT):
                continue
            textures = [mel.get_material_instance_texture_parameter_value(mat, str(n)) for n in mel.get_texture_parameter_names(mat)]
            if not _city.paints_with_factors_alone([t.get_path_name() if t else None for t in textures]):
                continue
            if "EmissiveFactor" in vectors:
                f = mel.get_material_instance_vector_parameter_value(mat, "EmissiveFactor")
                s = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength") if "EmissiveStrength" in scalars else 1.0
                if max(f.r, f.g, f.b) * s > _city.EPS:
                    continue  # it glows: its glow belongs to the city factor, on its glTF instance
        dusk = mel.get_material_instance_vector_parameter_value(mat, "BaseColorFactor")
        day = _city.day_albedo((dusk.r, dusk.g, dusk.b), NEAR_DAY_FLOOR)
        if day is None and not ours:
            left.append(name)
            continue
        if day is None:  # ours from an earlier run, now above a lowered floor: the same by day
            day = (dusk.r, dusk.g, dusk.b)
        if master is None:
            master = city_day_master()
        if ours:
            mi = mat
        else:
            # the slot's own name (same_city_001): two plain slots never share one day colour
            path = f"/Game/HQ/Materials/{_city.DAY_MI_PREFIX}{name}"
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                mi = unreal.load_asset(path)
            else:
                folder, mi_name = path.rsplit("/", 1)
                mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    mi_name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        carried = {key: mel.get_material_instance_scalar_parameter_value(mat, key)
                   for key in ("MetallicFactor", "RoughnessFactor", "SpecularFactor") if key in scalars}
        mel.set_material_instance_parent(mi, master)
        mel.set_material_instance_vector_parameter_value(mi, "BaseColorFactor", dusk)
        mel.set_material_instance_vector_parameter_value(mi, "DayBaseColor", unreal.LinearColor(day[0], day[1], day[2], 1.0))
        for key, value in carried.items():
            mel.set_material_instance_scalar_parameter_value(mi, key, value)
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        comp.set_material(i, mi)
        lifted.append(f"{name}[{i}] {_city.luminance((dusk.r, dusk.g, dusk.b)):.3f}->{_city.luminance(day):.3f}")
    log(f"near blocks by day: {_city.DAY_PARAMETER} 0 = dusk as built, 1 = own colour at albedo >= {NEAR_DAY_FLOOR:g}; "
        f"lifted {lifted or 'none'}; left on glTF (already that light) {left or 'none'}")


def tune_materials(actors):
    mel = unreal.MaterialEditingLibrary
    base = baseline()
    city, road = 0, 0
    city_folds = {}
    frames = {}
    for label, actor in actors.items():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant):
                continue
            path = mat.get_path_name()
            scalars = [str(n) for n in mel.get_scalar_parameter_names(mat)]
            # the import numbers each material ("frame_dark_001"); compare the scene's own name, so
            # "mon_frame_001" or "edge_led_slab_001" stay out
            base_name = path.rsplit("/", 1)[-1].split(".")[0].lower().rstrip("0123456789").rstrip("_")
            if FRAME_METAL >= 0 and base_name in FRAME_MATERIALS and path not in frames:
                if "MetallicFactor" in scalars:
                    mel.set_material_instance_scalar_parameter_value(mat, "MetallicFactor", FRAME_METAL)
                    mel.update_material_instance(mat)
                frames[path] = scalars
            if base_name in STRIP_MATERIALS and "EmissiveStrength" in scalars:
                if path not in base:
                    base[path] = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
                mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", base[path] * STRIP_GAIN)
                mel.update_material_instance(mat)
                log(f"strip {path.rsplit('.', 1)[-1]}: emission {base[path]:.2f} x{STRIP_GAIN:g}")
            if label in CITY_LABELS:
                if city_slot(mat, path, label, scalars, base, city_folds):
                    city += 1
            if label == "street_ground" and "asphalt" in path.lower() and "RoughnessFactor" in scalars:
                # only the factor: glTF instances also carry MetallicRoughnessTexture_TexCoord and
                # _Rotation, whose names contain "rough" too and would break the texture's UVs
                mel.set_material_instance_scalar_parameter_value(mat, "RoughnessFactor", ROAD_ROUGH)
                if "SpecularFactor" in scalars:
                    mel.set_material_instance_scalar_parameter_value(mat, "SpecularFactor", ROAD_SPECULAR)
                mel.update_material_instance(mat)
                road += 1
    with open(BASELINE, "w", encoding="utf-8") as fh:
        json.dump(base, fh, indent=1)
    log(f"skyline emission x{CITY} on {city} materials; road roughness {ROAD_ROUGH} on {road} parameters")
    for label in CITY_LABELS:
        folds = city_folds.get(label, {})
        cannot = folds.get("cannot", [])
        log(f"{label}: one EmissiveFactor scales it {'on every slot' if not cannot else 'NOT on every slot'} "
            f"(kept {len(folds.get('keep', []))}, folded {len(folds.get('fold', []))}: {folds.get('fold', [])[:8]}"
            f"{'; cannot: ' + '; '.join(cannot[:6]) if cannot else ''})")
    if FRAME_METAL >= 0:
        with_metal = [p for p, s in frames.items() if "MetallicFactor" in s]
        log(f"frame metallic {FRAME_METAL} on {len(with_metal)} of {len(frames)} frame materials {sorted(frames)[:6]}")
    if unreal.EditorAssetLibrary.does_asset_exist(ROAD_MI):
        wet = unreal.load_asset(ROAD_MI)
        mel.set_material_instance_scalar_parameter_value(wet, "Roughness Min", ROAD_ROUGH_MIN)
        mel.set_material_instance_scalar_parameter_value(wet, "Roughness Max", ROAD_ROUGH_MAX)
        mel.update_material_instance(wet)
        unreal.EditorAssetLibrary.save_loaded_asset(wet)
        log(f"wet asphalt roughness {ROAD_ROUGH_MIN}-{ROAD_ROUGH_MAX}")


def apply_post(settings):
    values = (
        ("auto_exposure_bias", EXPOSURE),
        ("bloom_intensity", BLOOM),
        ("lumen_max_roughness_to_trace_reflections", TRACE_ROUGHNESS),
        ("vignette_intensity", 0.3),
        # the picture's grade: a touch more colour, cool shadows, warm highlights
        ("color_saturation", unreal.Vector4(1.08, 1.08, 1.1, 1.0)),
        ("color_contrast", unreal.Vector4(CONTRAST, CONTRAST, CONTRAST, 1.0)),
        ("color_gain_shadows", unreal.Vector4(0.9, 0.96, 1.12, 1.0)),
        ("color_gain_highlights", unreal.Vector4(1.08, 1.0, 0.9, 1.0)),
    )
    for name, value in values:
        try:
            setattr(settings, f"override_{name}", True)
            setattr(settings, name, value)
        except Exception as err:
            log(f"post-process {name} skipped: {err}")
    return settings


def tune_post_and_fog(actors):
    ppv = actors.get("DuskLook")
    if ppv is not None:
        ppv.settings = apply_post(ppv.settings)
    cam = actors.get("PlateCam")
    if cam is not None:
        comp = cam.camera_component
        comp.set_editor_property("post_process_settings", apply_post(comp.get_editor_property("post_process_settings")))
    fog = actors.get("HeightFog")
    if fog is not None:
        fc = fog.component
        fc.set_fog_density(FOG_DENSITY)
        for prop, value in (("start_distance", FOG_START_CM), ("fog_cutoff_distance", FOG_CUTOFF_CM),
                            ("fog_inscattering_luminance", unreal.LinearColor(0.3, 0.34, 0.55, 1.0))):
            try:
                fc.set_editor_property(prop, value)
            except Exception as err:
                log(f"fog {prop} skipped: {err}")
    log(f"post-process (exposure {EXPOSURE}, bloom {BLOOM}, grade) and fog ({FOG_DENSITY}, from {FOG_START_CM:.0f} cm, cutoff {FOG_CUTOFF_CM:.0f} cm)")


def street_fill(actors):
    """A wide area light 6 m up, straight down over the street (the building's front is at Blender
    y 0, so the light stays off the rooms), cool like the dusk sky, without shadows. Pointing down,
    the light's width runs across the street and its height along it."""
    fill = actors.get("StreetFill")
    if fill is None and STREET_FILL <= 0:
        return
    where, down = ue(0.0, STREET_FILL_Y, 6.0), unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0)
    if fill is None:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        fill = eas.spawn_actor_from_class(unreal.RectLight, where, down)
        fill.set_actor_label("StreetFill")
    fill.set_actor_location_and_rotation(where, down, False, False)
    comp = fill.rect_light_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_intensity_units(unreal.LightUnits.LUMENS)
    comp.set_intensity(max(STREET_FILL, 0.0))
    comp.set_light_color(STREET_FILL_COLOR)
    comp.set_editor_property("source_width", STREET_FILL_DEPTH)
    comp.set_editor_property("source_height", 6000.0)
    comp.set_attenuation_radius(3000.0)
    comp.set_cast_shadows(False)
    lamp = actors.get("lamp_left")
    check = f"; lamp_left stands at {lamp.get_actor_location()} (scene -17.07, -1.43, 5.59 m)" if lamp else ""
    log(f"street fill {STREET_FILL:.0f} lm at {fill.get_actor_location()}{check}")


# The three street lamps are 1000 W in the scene (70 lm/W, halved by AMN_LOOK_LAMP): enough to light
# the pavement, and enough to wash the building's own front, which stands a metre behind them. The
# floor labels showed it plainly - L1's panel read 117, 89, 72 against the picture's 37, 39, 75, and
# with the lamps off 32, 33, 46. So the lamps light channel 2 only, and the street's own actors (its
# ground, its props, the vehicles and the passers-by) are the ones that receive that channel.
STREET_LIT_PREFIXES = ("street_ground", "street_back", "street_front", "street_props", "car_", "tree_",
                       "planter_", "lamp_far_left", "lamp_left", "lamp_right", "lobby_bench",
                       "bus_shelter", "street_Passer")


def walk_wash(actors):
    """A warm wash over the pavement, five metres up and pointing straight down, as wide along the
    frame as the building's own front so it falls away towards both ends the way the picture's
    pavement does. It stands on the street lamps' lighting channel, so like them it never reaches the
    building a metre behind it. Pointing down, the light's width runs across the pavement and its
    height along it."""
    wash = actors.get(WALK_WASH_LABEL)
    if wash is None and WALK_WASH <= 0:
        return
    where, down = ue(0.0, WALK_WASH_Y, 5.0), unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0)
    if wash is None:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        wash = eas.spawn_actor_from_class(unreal.RectLight, where, down)
        wash.set_actor_label(WALK_WASH_LABEL)
    # street_channel reads this map straight after, and it has to find the wash in it
    actors[WALK_WASH_LABEL] = wash
    wash.set_actor_location_and_rotation(where, down, False, False)
    comp = wash.rect_light_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_intensity_units(unreal.LightUnits.LUMENS)
    comp.set_intensity(max(WALK_WASH, 0.0))
    comp.set_light_color(WALK_WASH_COLOR)
    comp.set_editor_property("source_width", WALK_WASH_DEPTH)
    comp.set_editor_property("source_height", WALK_WASH_WIDTH)
    comp.set_attenuation_radius(1800.0)
    comp.set_cast_shadows(False)
    log(f"pavement wash {WALK_WASH:.0f} lm at {wash.get_actor_location()}, "
        f"{WALK_WASH_WIDTH / 100.0:.0f} m along the frame by {WALK_WASH_DEPTH / 100.0:.0f} m across")


def street_channel(actors):
    """The street lamps and the pavement wash on channel 2, and everything on the street set to
    receive it as well."""
    lamps = 0
    for label, actor in actors.items():
        comp = actor.get_editor_property("light_component") if isinstance(actor, unreal.Light) else None
        if comp is None or not label.startswith(CHANNEL_2_NAMES):
            continue
        comp.set_editor_property("lighting_channels", unreal.LightingChannels(channel0=False, channel1=False, channel2=True))
        lamps += 1
    lit = 0
    for label, actor in actors.items():
        if not label.startswith(STREET_LIT_PREFIXES):
            continue
        for comp in actor.get_components_by_class(unreal.PrimitiveComponent):
            channels = comp.get_editor_property("lighting_channels")
            comp.set_editor_property("lighting_channels", unreal.LightingChannels(
                channel0=channels.channel0, channel1=channels.channel1, channel2=True))
        lit += 1
    log(f"street lamps on channel 2: {lamps} lamps, {lit} actors receiving")


def facade_light(actors):
    """A wide area light in front of the building (Blender y FACADE_Y), facing it, cool like the dusk,
    without shadows, on lighting channel 1 only; the shell actor receives channels 0 and 1, every other
    actor channel 0 only, so the rooms behind the open front stay as they are. Facing the building
    (yaw -90), the light's width runs along the building and its height up it."""
    light = actors.get("FacadeLight")
    if light is None and FACADE <= 0:
        return
    top_m = CEILINGS_M[-1] + 4.0  # the roof's parapet and sign above the top floor
    # At 800 lm over the whole front the upper floors came closer to the picture (L4 10.2 -> 8.3,
    # the roof sign 12.7 -> 9.0) but the ground floor (21.3 -> 26.5) and the lift tower (11.1 -> 16.9)
    # took too much: the light's bottom edge (m), centre and width, and its barn doors, keep it on the
    # floors above the ground floor.
    bottom_m = env("AMN_LOOK_FACADE_BOTTOM", "5.2")      # just above the ground floor's ceiling (4.9 m)
    centre_x = env("AMN_LOOK_FACADE_X", "0.4")           # the main block, without the lift tower
    width_cm = env("AMN_LOOK_FACADE_WIDTH", "2850")
    where = ue(centre_x, FACADE_Y, (top_m + bottom_m) / 2.0)
    facing = unreal.Rotator(roll=0.0, pitch=0.0, yaw=-90.0)
    if light is None:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        light = eas.spawn_actor_from_class(unreal.RectLight, where, facing)
        light.set_actor_label("FacadeLight")
    light.set_actor_location_and_rotation(where, facing, False, False)
    comp = light.rect_light_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_intensity_units(unreal.LightUnits.LUMENS)
    comp.set_intensity(max(FACADE, 0.0))
    comp.set_light_color(unreal.LinearColor(0.72, 0.78, 1.0, 1.0))
    comp.set_editor_property("source_width", width_cm)
    comp.set_editor_property("source_height", (top_m - bottom_m) * 100.0)
    # the doors are planes along the light's edges: at 90 degrees they lie flat (no effect), at 0 they
    # stand straight out, and their length (cm) sets how far they hold the light to its own outline
    barn_angle = env("AMN_LOOK_FACADE_BARN_ANGLE", "5")
    barn_length = env("AMN_LOOK_FACADE_BARN_LENGTH", "1000")
    comp.set_editor_property("barn_door_angle", barn_angle)
    comp.set_editor_property("barn_door_length", barn_length)
    comp.set_attenuation_radius(3000.0)
    comp.set_cast_shadows(False)
    comp.set_editor_property("lighting_channels", unreal.LightingChannels(channel0=False, channel1=True, channel2=False))
    # The slab faces between the floors read as a light slate strip, and darkening their colour did not
    # change it: the strip is this light's glare on faces turned straight towards it. Its specular share
    # (1 leaves the engine's); the frame's navy is its diffuse light, which this leaves. At 0 the strips'
    # rows came down by 19-26 (L2's 93 -> 73 and 87 -> 64, L3's 89 -> 68 and 74 -> 47, against the
    # picture's 42-77), mean 11.1 (2026-09-15).
    facade_specular = env("AMN_LOOK_FACADE_SPECULAR", "0")
    comp.set_editor_property("specular_scale", facade_specular)
    log(f"facade light specular x{facade_specular:g}")
    shell = actors.get(FACADE_ACTOR)
    if shell is not None:
        shell.static_mesh_component.set_editor_property("lighting_channels", unreal.LightingChannels(channel0=True, channel1=True, channel2=False))
    log(f"facade light {FACADE:.0f} lm at y {FACADE_Y} m, x {centre_x} m, {width_cm / 100.0:.1f} m wide, from {bottom_m} to {top_m:.1f} m, "
        f"barn doors {barn_angle:g} deg x {barn_length:g} cm, on channel 1 with {'the shell' if shell else 'NO shell actor'}")


# The rooms' windows onto the city (the Blender scene's image materials window_view and
# window_view_b) rendered as flat mauve panels: the export bakes them into the shared "props" atlas,
# where each window gets a few texels, the average of its dusk image. Their own images go back on
# them, on the model's own UVs (every face of the scene's meshes spans 0-1), with this emission
# strength; 0 leaves the baked atlas. At 1.5 (with the facade light) the windows show dark towers with
# lit windows against the dusk, and the rooms' regions came closer to the picture (mean 14.6).
WINDOW_VIEW_DIR = os.path.join(os.path.dirname(HERE), "blender", "hq", "textures")
WINDOW_VIEW_STRENGTH = env("AMN_LOOK_WINDOW_VIEW", "1.5")
# By day and by night the same windows show make_textures.py's day picture (the image the Blender
# scene's own daytime variant puts on both window_view slots) and its night picture, when there is
# one. window_view.py holds the rules and says why the windows keep the glTF instance: the hand-built
# M_HQ_WindowView of the rejected 2026-09-19 rebuild could not be shown to paint today's window.
# The instance keeps its dusk picture exactly as before; the pictures of the other hours ride on a
# versioned copy of its own parent chain, whose master differs from the glTF one only by two lerps
# at weight 0 on its base colour and emissive outputs (DayBlend, NightBlend).
import importlib.util  # noqa: E402  (kept beside the code that uses it)

_window_spec = importlib.util.spec_from_file_location("window_view", os.path.join(HERE, "window_view.py"))
_window = importlib.util.module_from_spec(_window_spec)
_window_spec.loader.exec_module(_window)
WINDOW_COPY_FOLDER = "/Game/HQ/Materials"


def window_texture(image):
    path = f"/Game/HQ/Materials/T_HQ_{image}"
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        source = os.path.join(WINDOW_VIEW_DIR, f"{image}.png")
        if not os.path.exists(source):
            raise RuntimeError(f"{source} missing: art-source/blender/hq/make_textures.py draws it")
        task = unreal.AssetImportTask()
        task.filename = source
        task.destination_path = "/Game/HQ/Materials"
        task.destination_name = f"T_HQ_{image}"
        task.automated = True
        task.replace_existing = True
        task.save = True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return unreal.load_asset(path)


def window_parameter_values(mat):
    """Every parameter the instance resolves, by kind and name, for window_view.differences()."""
    mel = unreal.MaterialEditingLibrary
    out = {}
    for name in mel.get_scalar_parameter_names(mat):
        out[f"scalar:{name}"] = float(mel.get_material_instance_scalar_parameter_value(mat, name))
    for name in mel.get_vector_parameter_names(mat):
        c = mel.get_material_instance_vector_parameter_value(mat, name)
        out[f"vector:{name}"] = (c.r, c.g, c.b, c.a)
    for name in mel.get_texture_parameter_names(mat):
        tex = mel.get_material_instance_texture_parameter_value(mat, name)
        out[f"texture:{name}"] = tex.get_path_name() if tex else None
    for name in mel.get_static_switch_parameter_names(mat):
        out[f"switch:{name}"] = bool(mel.get_material_instance_static_switch_parameter_value(mat, name))
    return out


def _package(obj):
    return obj.get_path_name().split(".", 1)[0]


def _extend_window_master(mat, day, night):
    """The one change in the copied glTF master: at its base colour and emissive outputs,
    lerp(original, day, DayBlend) then lerp(that, night, NightBlend), both blends 0 by default.
    Refuses (raises) when the original outputs cannot be taken over as they are."""
    mel = unreal.MaterialEditingLibrary
    if mat.get_editor_property("use_material_attributes"):
        raise RuntimeError(f"{mat.get_path_name()} uses material attributes: its outputs cannot be taken over unchanged")
    originals = {}
    for prop in (unreal.MaterialProperty.MP_BASE_COLOR, unreal.MaterialProperty.MP_EMISSIVE_COLOR):
        node = mel.get_material_property_input_node(mat, prop)
        output = mel.get_material_property_input_node_output_name(mat, prop)
        if node is None:
            raise RuntimeError(f"{mat.get_path_name()}: nothing drives {prop}")
        if output == "" and len(mel.get_material_expression_output_names(node)) > 1:
            raise RuntimeError(f"{mat.get_path_name()}: {prop} comes from an unnamed output of {node.get_name()}")
        originals[prop] = (node, output)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", _window.ADDED_DEFAULTS[name])
        return n

    def vector(name, x, y):
        n = node(unreal.MaterialExpressionVectorParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
        return n

    def sampler(name, texture, x, y):
        n = node(unreal.MaterialExpressionTextureSampleParameter2D, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("texture", texture)
        # a shared sampler: the glTF master already spends many of its 16 slots
        n.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        return n

    def times(a, a_out, b, b_out, x, y):
        n = node(unreal.MaterialExpressionMultiply, x, y)
        mel.connect_material_expressions(a, a_out, n, "A")
        mel.connect_material_expressions(b, b_out, n, "B")
        return n

    x0, y0 = 1200, -1600  # beside the original graph, never over it
    day_rgb = sampler("DayTex", day, x0, y0)
    night_rgb = times(sampler("NightTex", night, x0, y0 + 300), "RGB", scalar("NightPicture", x0, y0 + 550), "", x0 + 250, y0 + 400)
    base_factor = vector("ViewBaseFactor", x0, y0 + 700)
    emissive_factor = vector("ViewEmissiveFactor", x0, y0 + 900)
    emissive_strength = scalar("ViewEmissiveStrength", x0, y0 + 1100)
    blends = {"DayBlend": scalar("DayBlend", x0, y0 + 1300), "NightBlend": scalar("NightBlend", x0, y0 + 1450)}
    branches = {
        unreal.MaterialProperty.MP_BASE_COLOR: (
            times(day_rgb, "RGB", base_factor, "RGB", x0 + 500, y0),
            times(night_rgb, "", base_factor, "RGB", x0 + 500, y0 + 300),
        ),
        unreal.MaterialProperty.MP_EMISSIVE_COLOR: (
            times(times(day_rgb, "RGB", emissive_factor, "RGB", x0 + 500, y0 + 600), "", emissive_strength, "", x0 + 700, y0 + 600),
            times(times(night_rgb, "", emissive_factor, "RGB", x0 + 500, y0 + 900), "", emissive_strength, "", x0 + 700, y0 + 900),
        ),
    }
    for row, (prop, (day_branch, night_branch)) in enumerate(branches.items()):
        source, output = originals[prop]
        to_day = node(unreal.MaterialExpressionLinearInterpolate, x0 + 950, y0 + 600 * row)
        mel.connect_material_expressions(source, output, to_day, "A")
        mel.connect_material_expressions(day_branch, "", to_day, "B")
        mel.connect_material_expressions(blends["DayBlend"], "", to_day, "Alpha")
        to_night = node(unreal.MaterialExpressionLinearInterpolate, x0 + 1150, y0 + 600 * row)
        mel.connect_material_expressions(to_day, "", to_night, "A")
        mel.connect_material_expressions(night_branch, "", to_night, "B")
        mel.connect_material_expressions(blends["NightBlend"], "", to_night, "Alpha")
        if not mel.connect_material_property(to_night, "", prop):
            raise RuntimeError(f"could not connect the extended {prop}")
    errors = mel.recompile_material(mat) or []
    if errors:
        raise RuntimeError(f"extended window master does not compile: {errors[:5]}")
    unreal.EditorAssetLibrary.save_loaded_asset(mat)


def _window_copy(source, day, night, parent=None):
    """The versioned copy of one link of the glTF chain: reused when this graph version exists,
    otherwise duplicated from the engine's asset (and extended, for the master)."""
    path = f"{WINDOW_COPY_FOLDER}/{_window.copy_name(source.get_name())}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    copy = unreal.EditorAssetLibrary.duplicate_asset(_package(source), path)
    if copy is None:
        raise RuntimeError(f"could not copy {source.get_path_name()} to {path}")
    if isinstance(copy, unreal.MaterialInstanceConstant):
        unreal.MaterialEditingLibrary.set_material_instance_parent(copy, parent)
        unreal.MaterialEditingLibrary.update_material_instance(copy)
        unreal.EditorAssetLibrary.save_loaded_asset(copy)
    else:
        _extend_window_master(copy, day, night)
    log(f"window view: {source.get_path_name()} copied to {path}")
    return copy


def _window_parent(instance, day, night):
    """The copy of the instance's parent chain, master first, returning the new direct parent."""
    chain, m = [], instance.get_editor_property("parent")
    while isinstance(m, unreal.MaterialInstance):
        chain.append(m)
        m = m.get_editor_property("parent")
    if not isinstance(m, unreal.Material):
        raise RuntimeError(f"{instance.get_path_name()} has no master material")
    parent = _window_copy(m, day, night)
    for link in reversed(chain):
        parent = _window_copy(link, day, night, parent)
    return parent


def window_views(actors):
    if WINDOW_VIEW_STRENGTH <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    day = window_texture(_window.DAY_PICTURE)
    textures = {image: window_texture(image) for image in set(_window.DUSK_PICTURES.values())}
    night = _window.night_state(WINDOW_VIEW_DIR)
    night_texture = window_texture(_window.NIGHT_PICTURE) if night["picture"] else None
    log(f"window view at night: {night['note']}")
    made, slots = {}, []
    for label, actor in actors.items():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant):
                continue
            image = _window.dusk_picture(mat.get_name())
            if image is None:
                continue
            mi = made.get(image)
            if mi is None:
                if mat.get_name().startswith(_window.INSTANCE_PREFIX):
                    # a rerun of this pass on a level that already has ours: its chain is already
                    # the copy, and the check below was made when it was first built
                    mi, before = mat, None
                else:
                    # today's window, exactly as every build since 2026-09-15 made it: the import's
                    # own instance re-textured with its dusk picture on UV0, at this strength
                    for slot in ("BaseColorTexture", "EmissiveTexture"):
                        mel.set_material_instance_texture_parameter_value(mat, slot, textures[image])
                        mel.set_material_instance_scalar_parameter_value(mat, f"{slot}_TexCoord", 0.0)
                    mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", WINDOW_VIEW_STRENGTH)
                    mel.update_material_instance(mat)
                    before = window_parameter_values(mat)
                    # its twin in the build's own Scene_ folder, which the next build deletes with it
                    path = f"{_package(mat).rsplit('/', 1)[0]}/{_window.instance_name(image)}"
                    if unreal.EditorAssetLibrary.does_asset_exist(path) and not unreal.EditorAssetLibrary.delete_asset(path):
                        raise RuntimeError(f"{path} exists and cannot be replaced")
                    mi = unreal.EditorAssetLibrary.duplicate_asset(_package(mat), path)
                    if mi is None:
                        raise RuntimeError(f"could not copy {mat.get_path_name()} to {path}")
                    mel.set_material_instance_parent(mi, _window_parent(mat, day, textures[image]))
                values = window_parameter_values(mi)
                base_factor = values.get("vector:BaseColorFactor", (1.0, 1.0, 1.0, 1.0))
                emissive_factor = values.get("vector:EmissiveFactor", (1.0, 1.0, 1.0, 1.0))
                mel.set_material_instance_texture_parameter_value(mi, "DayTex", day)
                mel.set_material_instance_texture_parameter_value(mi, "NightTex", night_texture or textures[image])
                mel.set_material_instance_scalar_parameter_value(mi, "NightPicture", night["NightPicture"])
                mel.set_material_instance_vector_parameter_value(mi, "ViewBaseFactor", unreal.LinearColor(*base_factor))
                mel.set_material_instance_vector_parameter_value(mi, "ViewEmissiveFactor", unreal.LinearColor(*emissive_factor))
                mel.set_material_instance_scalar_parameter_value(mi, "ViewEmissiveStrength", values.get("scalar:EmissiveStrength", WINDOW_VIEW_STRENGTH))
                mel.update_material_instance(mi)
                unreal.EditorAssetLibrary.save_loaded_asset(mi)
                if before is not None:
                    changed = _window.differences(before, window_parameter_values(mi))
                    if changed:
                        raise RuntimeError(f"window view {image}: the copied chain does not repeat today's instance: {changed[:6]}")
                    log(f"window view {image}: {mat.get_name()} -> {mi.get_name()}, all {len(before)} old values unchanged")
                made[image] = mi
            comp.set_material(i, mi)
            slots.append(f"{label}[{i}]")
    log(f"room windows: dusk picture as before (DayBlend 0, NightBlend 0), day picture, night "
        f"{'picture' if night['picture'] else 'dark (no picture)'}, emission {WINDOW_VIEW_STRENGTH}, on {len(slots)} slots {slots}")


# The small lights (server LEDs, the rack bars, the PCs' and speakers' LEDs, the infra room's bars
# and grid) are baked with the rest of "glow_details" into one shared emission texture, where an LED
# of a few millimetres is averaged away: the picture's server racks show rows of green lights, the
# live ones stood black. Each gets its own colour (the Blender scene's, hq_building.py) on a white
# texture, at the scene's strength times this gain; 0 leaves the bake.
# At the scene's strengths (gain 1) the rack tops and the infra room's grid glowed, but the LED dots
# did not show: each is 3 x 3 cm, under one pixel in the live frame, and anti-aliasing averages it
# away. The dots take LED_DOT_BOOST times their strength, so bloom makes a visible point of each; the
# grid and bars (lines, visible already, stronger than the picture's) take a share. The dots still
# did not show at any size or strength until the cause was found: Nanite dropped their small separate
# boxes (nanite_hq_live.py turns it off on the small lights' mesh). Since then the racks show rows of
# green and amber dots like the picture's; the grid's lines at 0.5 read stronger than the picture's and
# hid the "I" of the S1 INFRA sign in their glow, at 0.15 the sign reads whole.
LED_DOT_BOOST = env("AMN_LOOK_LED_DOT_BOOST", "8")
LED_LINE_SHARE = env("AMN_LOOK_LED_LINE_SHARE", "0.15")
LAMP_GLOW = env("AMN_LOOK_LAMP_GLOW", "1")
LEDS = {
    "rack_led_green": ("#4ade80", 6.0 * LED_DOT_BOOST), "rack_led_amber": ("#fbbf24", 5.0 * LED_DOT_BOOST),
    "pc_led_blue": ("#60a5fa", 8.0 * LED_DOT_BOOST), "spk_led": ("#93c5fd", 5.0 * LED_DOT_BOOST),
    "rack_top_bar": ("#34d399", 3.0), "infra_bar": ("#a5f3fc", 5.0 * LED_LINE_SHARE),
    "infra_grid": ("#2dd4bf", 0.6 * LED_LINE_SHARE),
    # the pendant and floor lamp shades and the lobby's wall bulbs: warm and lit, as in the picture,
    # where ours hung dark. AMN_LOOK_LAMP_GLOW tunes them without another scene rebuild.
    "lamp_shade": ("#ffd49a", 4.0 * LAMP_GLOW), "lamp_bulb": ("#fff0d6", 14.0 * LAMP_GLOW),
    # the line under each office ceiling: the picture's is amber, ours burnt white
    "cove_led": ("#ffc07a", 2.2 * LAMP_GLOW),
    # L1's neon sign: white-pink tubes that throw purple on the brick around them in the picture
    "neon_purple": ("#e7a6ff", 9.0),
    # the same line under L4, where the picture has the sign band's soffit rather than a lit room:
    # a dim amber eave, 111, 74, 46 at its brightest row, where cove_led at 2.2 gave 230, 202, 151
    # over four rows. A third of the cove's strength and a warmer colour; worth one pass against
    # the stream, since an emissive that near the top of the curve does not dim in proportion.
    "sign_soffit": ("#ffb070", 0.7 * LAMP_GLOW),
}
LED_GAIN = env("AMN_LOOK_LED_GAIN", "1")
WHITE = "/InterchangeAssets/gltf/Textures/T_White_srgb"


def linear(hex_color):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    return [channel(int(h[i:i + 2], 16)) for i in (0, 2, 4)]


def small_lights(actors):
    if LED_GAIN <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    white = unreal.load_asset(WHITE)
    done = set()
    for actor in actors.values():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant) or mat.get_path_name() in done:
                continue
            spec = LEDS.get(mat.get_name().lower().rstrip("0123456789").rstrip("_"))
            if spec is None:
                continue
            r, g, b = linear(spec[0])
            mel.set_material_instance_texture_parameter_value(mat, "EmissiveTexture", white)
            mel.set_material_instance_texture_parameter_value(mat, "BaseColorTexture", white)
            mel.set_material_instance_vector_parameter_value(mat, "EmissiveFactor", unreal.LinearColor(r, g, b, 1.0))
            mel.set_material_instance_vector_parameter_value(mat, "BaseColorFactor", unreal.LinearColor(r, g, b, 1.0))
            mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", spec[1] * LED_GAIN)
            mel.update_material_instance(mat)
            done.add(mat.get_path_name())
    log(f"small lights: own colours at x{LED_GAIN} of the scene's strength on {len(done)} materials")


# The rooms' plants of 0.9 m and taller are the restaurant scene's potted frond (dress_hq_live.py
# BIG_PLANT), and they render as dark silhouettes where the picture's plants are a lit green: the pack
# keeps the frond's colour at 0.143 (BaseColorMultiply) and relies on subsurface light in its own,
# brightly lit restaurant. A child instance under /Game/HQ (the pack's own stays untouched) with this
# colour factor goes on the frond slot of every plant placed from that mesh; 0 leaves the pack's.
# At 0.6 (15 plants) the fronds read a lighter green by eye and the mean held (14.0 against 13.9);
# they stay thinner than the picture's bushy plants, which is the model's shape, not its colour.
PLANT_MESH = "/Game/RestaurantScene/Meshes/SM_PlantPot"
PLANT_MI = "/Game/HQ/Materials/MI_HQ_PlantFrond"
PLANT_FROND = env("AMN_LOOK_PLANT_FROND", "0.6")


def plant_fronds(actors):
    if PLANT_FROND <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    mesh = unreal.load_asset(PLANT_MESH)
    if mesh is None:
        log(f"plant fronds: {PLANT_MESH} missing")
        return
    parent = mesh.static_materials[0].material_interface
    if unreal.EditorAssetLibrary.does_asset_exist(PLANT_MI):
        mi = unreal.load_asset(PLANT_MI)
    else:
        folder, name = PLANT_MI.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    mel.set_material_instance_scalar_parameter_value(mi, "BaseColorMultiply", PLANT_FROND)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    placed = 0
    for actor in actors.values():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        current = comp.get_editor_property("static_mesh")
        if current is not None and current.get_path_name() == mesh.get_path_name():
            comp.set_material(0, mi)
            placed += 1
    log(f"plant fronds: colour x{PLANT_FROND:g} (the pack's 0.143) on {placed} plants, parent {parent.get_name() if parent else None}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    tune_lights(actors)
    tune_materials(actors)
    near_blocks_day(actors)
    tune_post_and_fog(actors)
    street_fill(actors)
    walk_wash(actors)
    street_channel(actors)
    facade_light(actors)
    window_views(actors)
    small_lights(actors)
    plant_fronds(actors)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log("saved")


main()
