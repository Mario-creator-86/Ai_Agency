"""The day variant: the same headquarters on a clear Bucharest noon.

build_hq.py calls this module only under `--variant day`; the night build never imports it, so the
night plates stay what they were. The web canvas crossfades to the day plates as the real sun
climbs (hq_world.plateDayMix), and from about 7 degrees of solar elevation it shows them alone, so
this is what a visitor sees from mid-morning to late afternoon.

What changes against the night build, and why:
- The sun stands where the real one does at 12:00 EEST on 2026-09-24 over Bucharest (NOAA:
  elevation 42.2 deg, azimuth 157 deg, 23 deg east of south). The camera looks north, so the sun is
  behind it and to the right: the fronts are sunlit and the shadows fall back and to the left.
- The world is a clear sky: deep blue at the zenith, pale at the horizon, the ground's warm grey
  below it. It lights and reflects; the page paints its own sky behind the plates (hq_sky.js).
- The city's towers switch their windows off and take daylight colours: glass curtain walls in
  blue and grey, concrete and stone blocks in cream, beige and warm stone. Their night colours were
  navy masses chosen to stand dark against a dusk; under the sun they read as a city at night.
- Street lamps, uplights, LED lines and beacons go dark; what was only an emission becomes paint
  (a lamp's glass, a sign's letters, a bridge's white cables), so nothing turns into a black hole.
- The haze thins to a pale blue veil that only softens the far towers.
- The offices keep their lights on, dimmer and cooler, and their windows show the day: daylight
  comes through the glass in front and through the windows at the back of each room.
- The street is dry: the night's wet road is weather, and the page draws the real weather.
"""

import math
import os

import bpy
from hq_lib import TEXTURES, lin

SUN_ELEVATION = 42.0
SUN_EAST_OF_SOUTH = 23.0
SUN_COLOR = "#fff1de"
SUN_STRENGTH = 4.2

# The page's own noon sky (hq_time.js SKY.day), top to below the horizon: the preview's backdrop.
PAGE_SKY = [(0.0, "#3f78c8"), (0.24, "#79a9e0"), (0.4, "#cfe2f3"), (0.62, "#b9cde2")]

# windows_material facades by day: (wall between the windows, the window glass)
FACADES = {
    "tower_dark_l": ("#7c8a9b", "#4d6680"),
    "tower_blue_l": ("#9aa7b8", "#56789c"),
    "tower_mauve_l": ("#c2b6a8", "#6a7486"),
    "tower_dark": ("#6f7e90", "#3f5872"),
    "tower_blue": ("#8e9cb0", "#47698f"),
    "tower_mauve": ("#b8ab9d", "#5d6778"),
    "tower_cool": ("#d4d8dc", "#7394b6"),
    "tower_right": ("#7f8b98", "#44607e"),
    "city_dense": ("#b4b3ae", "#6c7b8e"),
    "city_mid": ("#cbbfac", "#5a6470"),
    "classic": ("#cfae8e", "#4c4a4e"),
    "shopfront_block": ("#a8927e", "#3c3c42"),
}

# Emission-only materials by day, by name prefix: (what is left of the light, the paint it shows,
# or None for the light's own colour). First match wins; anything not named keeps its light, which
# is right for screens, rack LEDs and the other devices an office leaves on.
PAINTS = [
    # the street and the skyline's lamps are off by day
    ("lamp_glass", 0.0, "#e9e6df"),
    ("terrace_led", 0.0, "#d9d2c6"),
    ("edge_led", 0.0, "#c9c6c0"),
    ("mullion_led", 0.0, "#b8b4ac"),
    ("shop_sill", 0.0, "#cfc8bc"),
    ("shop_head_led", 0.0, "#cfc8bc"),
    ("sign_soffit", 0.0, "#6e6558"),
    ("stair_nose", 0.15, "#c9b08a"),
    ("tower_strip", 0.0, "#dfe3ea"),
    ("crown_glow", 0.0, "#d9dde4"),
    ("pylon_edge", 0.0, "#c2c6ce"),
    ("bridge_cable", 0.0, "#eceef1"),
    ("bridge_light", 0.0, "#b9bdc6"),
    ("beacon", 0.12, "#d23a3a"),
    # signs: painted letters, a little backlight left
    ("billboard_text", 0.3, None),
    ("same_city_text", 0.2, None),
    ("slogan_text", 0.2, None),
    ("teal_dash", 0.25, None),
    ("gold", 0.45, None),
    ("label_text", 0.35, None),
    ("lobby_", 0.4, None),
    ("ai_logo", 0.5, None),
    ("ai_words", 0.5, None),
    ("render_label", 0.5, None),
    ("chalk", 0.3, None),
    ("door_sign", 0.5, None),
    ("drawer_label", 0.3, None),
    ("cabinet_line", 0.3, None),
    ("cove_led", 0.35, None),
    ("shaft_strip", 0.5, None),
    # the offices' own lamps stay on, softer
    ("lamp_shade", 0.55, None),
    ("lamp_bulb", 0.5, None),
    ("paper", 0.6, None),
]

# gradient_emission materials: what is left of their light (the lit panels, the lift shaft)
PANELS = {"billboard": 0.9, "shelter_ad": 0.75, "shopfront": 0.25, "shaft_section": 0.6, "bay_section": 0.6}

# plain surfaces whose night colour stood in for the dusk's light
SURFACES = {
    # the roof took the dusk's blue (hq_building.materials); under the sun it is a dark roof deck
    "roof": "#4b5261",
    # the bridge is pale concrete and white steel
    "bridge": "#c3c8d0",
}

# the street surfaces the night build makes wet
DRY = {"asphalt_wet", "sidewalk", "sidewalk_near", "terrace", "curb"}

INTERIOR_LIGHT = 0.55  # of the night's interior lamps
INTERIOR_COOL = "#eef3ff"
INTERIOR_COOL_MIX = 0.45
WINDOW_VIEW_GAIN = 1.15  # the day seen through a back window is brighter than the dusk
# The sky's light through each floor's open front: one soft, cool panel per floor, just outside
# the facade and turned into the rooms. Without it the rooms are lit by their lamps alone and read
# as night rooms under a day sky.
DAYLIGHT_FILL = 1000.0
DAYLIGHT_FILL_GROUND = 600.0
DAYLIGHT_COLOR = "#e3ecfb"
GLASS_METALLIC = 0.3
TOWER_ROOF = "#7b8088"

# For tuning passes only: AMN_DAY_TUNE='{"SUN_STRENGTH": 5}' overrides a constant above.
if os.environ.get("AMN_DAY_TUNE"):
    import json

    globals().update(json.loads(os.environ["AMN_DAY_TUNE"]))


def _sun_rotation():
    rx = math.radians(90.0 - SUN_ELEVATION)
    # a sun light shines down its local -Z; turning it about Z by +a sends the light toward -x
    # (west, left in the frame), which is a sun standing east of south
    rz = math.radians(SUN_EAST_OF_SOUTH)
    return (rx, 0.0, rz)


def world(scene, preview):
    """The clear-sky world: lights and reflections; the preview also sees the page's noon sky."""
    w = bpy.data.worlds.new("hq_world")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    fac = nt.nodes.new("ShaderNodeMapRange")
    fac.inputs["From Min"].default_value = -1.0
    fac.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], fac.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    els[0].color = lin("#6c675e")
    els[1].position = 1.0
    els[1].color = lin("#3f78c8")
    for pos, col in ((0.495, "#8c877c"), (0.5, "#dce7f2"), (0.62, "#a6c5e8"), (0.8, "#6a9bd8")):
        els.new(pos).color = lin(col)
    nt.links.new(fac.outputs["Result"], ramp.inputs["Fac"])
    ambient = nt.nodes.new("ShaderNodeBackground")
    ambient.inputs["Strength"].default_value = 1.0
    nt.links.new(ramp.outputs["Color"], ambient.inputs["Color"])
    if preview:
        sky = nt.nodes.new("ShaderNodeBackground")
        wsep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Window"], wsep.inputs[0])
        inv = nt.nodes.new("ShaderNodeMath")
        inv.operation = "SUBTRACT"
        inv.inputs[0].default_value = 1.0
        nt.links.new(wsep.outputs["Y"], inv.inputs[1])
        sramp = nt.nodes.new("ShaderNodeValToRGB")
        sels = sramp.color_ramp.elements
        sels[0].position, sels[0].color = PAGE_SKY[0][0], lin(PAGE_SKY[0][1])
        sels[1].position, sels[1].color = PAGE_SKY[-1][0], lin(PAGE_SKY[-1][1])
        for pos, col in PAGE_SKY[1:-1]:
            sels.new(pos).color = lin(col)
        nt.links.new(inv.outputs[0], sramp.inputs["Fac"])
        nt.links.new(sramp.outputs["Color"], sky.inputs["Color"])
        sky.inputs["Strength"].default_value = 1.0
        lp = nt.nodes.new("ShaderNodeLightPath")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
        nt.links.new(ambient.outputs["Background"], mix.inputs[1])
        nt.links.new(sky.outputs["Background"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    else:
        nt.links.new(ambient.outputs["Background"], out.inputs["Surface"])
    scene.world = w


def sun(colls):
    ld = bpy.data.lights.new("sun", "SUN")
    ld.color = lin(SUN_COLOR)[:3]
    ld.energy = SUN_STRENGTH
    ld.angle = math.radians(1.0)
    ob = bpy.data.objects.new("sun", ld)
    ob.rotation_euler = _sun_rotation()
    colls["lights_exterior"].objects.link(ob)


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _surface(mat):
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].links:
        return None
    return out.inputs["Surface"].links[0].from_node


def _bsdf(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _ramp_into(mat, bsdf, socket):
    for link in mat.node_tree.links:
        if link.to_node == bsdf and link.to_socket.name == socket and link.from_node.type == "VALTORGB":
            return link.from_node
    return None


def _paint(mat, emission, keep, paint):
    """An emission-only material becomes a painted surface with `keep` of its light left."""
    nt = mat.node_tree
    col = tuple(emission.inputs["Color"].default_value)
    strength = emission.inputs["Strength"].default_value
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    base = lin(paint) if paint else (min(col[0], 0.8), min(col[1], 0.8), min(col[2], 0.8), 1.0)
    b.inputs["Base Color"].default_value = base
    b.inputs["Roughness"].default_value = 0.45
    b.inputs["Emission Color"].default_value = col
    b.inputs["Emission Strength"].default_value = strength * keep
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])


def _facade(mat, wall, glass):
    b = _bsdf(mat)
    base = _ramp_into(mat, b, "Base Color")
    if b is None or base is None:
        return
    els = base.color_ramp.elements
    els[0].color = lin(glass)
    els[-1].color = lin(wall)
    # The window grid is laid out on x and z, so a tower's roof carries it as stripes. At night the
    # roof is as dark as the sky; under a high sun it is the brightest face of the tower, and the
    # stripes read as a glass cap. Roofs are concrete.
    nt = mat.node_tree
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep.inputs[0])
    up = nt.nodes.new("ShaderNodeMath")
    up.operation = "GREATER_THAN"
    up.inputs[1].default_value = 0.5
    nt.links.new(sep.outputs["Z"], up.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    a_in = next(i for i in mix.inputs if i.name == "A" and i.type == "RGBA")
    b_in = next(i for i in mix.inputs if i.name == "B" and i.type == "RGBA")
    out = next(o for o in mix.outputs if o.name == "Result" and o.type == "RGBA")
    nt.links.new(up.outputs[0], mix.inputs["Factor"])
    nt.links.new(base.outputs["Color"], a_in)
    b_in.default_value = lin(TOWER_ROOF)
    nt.links.new(out, b.inputs["Base Color"])
    b.inputs["Emission Strength"].default_value = 0.0
    b.inputs["Metallic"].default_value = GLASS_METALLIC
    b.inputs["Roughness"].default_value = 0.22


def _haze(mat, color, strength, alpha):
    nt = mat.node_tree
    for node in nt.nodes:
        if node.type == "EMISSION":
            node.inputs["Color"].default_value = lin(color)
            node.inputs["Strength"].default_value = strength
        elif node.type == "VALTORGB":
            for el in node.color_ramp.elements:
                v = el.color[0] * alpha
                el.color = (v, v, v, 1.0)


def _window_view(mat, day_view):
    nt = mat.node_tree
    b = _bsdf(mat)
    for node in nt.nodes:
        if node.type == "TEX_IMAGE":
            node.image = day_view
    grad = _ramp_into(mat, b, "Emission Color") if b else None
    if grad is not None and not any(n.type == "TEX_IMAGE" for n in nt.nodes):
        # the frosted upper-floor panes: the day's pale blue, lighter at the head
        els = grad.color_ramp.elements
        els[0].color = lin("#9fbde6")
        els[-1].color = lin("#d9e6f4")
    if b is not None:
        b.inputs["Emission Strength"].default_value *= WINDOW_VIEW_GAIN


def _dry(mat):
    """The night road is wet; a clear noon is dry, and the page draws the real rain itself."""
    b = _bsdf(mat)
    if b is None:
        return
    rough = _ramp_into(mat, b, "Roughness")
    if rough is not None:
        rough.color_ramp.elements[0].color = (0.72, 0.72, 0.72, 1.0)
        rough.color_ramp.elements[-1].color = (0.9, 0.9, 0.9, 1.0)
    elif not b.inputs["Roughness"].links:
        b.inputs["Roughness"].default_value = max(b.inputs["Roughness"].default_value, 0.78)


def _daylight_fill(coll):
    import hq_building
    from hq_lib import X

    x0, x1 = X(hq_building.LEFT), X(hq_building.RIGHT)
    for level in sorted(hq_building.FLOORS):
        f, c = hq_building.fz(level), hq_building.cz(level)
        ld = bpy.data.lights.new(f"daylight_{level}", "AREA")
        ld.shape = "RECTANGLE"
        ld.size = x1 - x0
        ld.size_y = (c - f) * 0.8
        ld.energy = DAYLIGHT_FILL_GROUND if level == 0 else DAYLIGHT_FILL
        ld.color = lin(DAYLIGHT_COLOR)[:3]
        ob = bpy.data.objects.new(f"daylight_{level}", ld)
        ob.location = ((x0 + x1) / 2, -0.9, (f + c) / 2 + 0.3)
        # an area light shines down its local -Z; 75 degrees about X turns it into the rooms, a
        # little downward, as the sky's light comes in over a sill
        ob.rotation_euler = (math.radians(75), 0.0, 0.0)
        ob.visible_camera = False
        ob.visible_glossy = False
        coll.objects.link(ob)


def apply(colls):
    """Turn the built night scene into the noon one."""
    cool = lin(INTERIOR_COOL)[:3]
    for ob in colls["lights_interior"].objects:
        ob.data.energy *= INTERIOR_LIGHT
        ob.data.color = _mix(tuple(ob.data.color), cool, INTERIOR_COOL_MIX)
    for ob in colls["lights_exterior"].objects:
        if ob.data.type != "SUN":
            ob.data.energy = 0.0
    _daylight_fill(colls["lights_interior"])
    day_view = bpy.data.images.load(os.path.join(TEXTURES, "window_city_day.png"), check_existing=True)
    for mat in list(bpy.data.materials):
        if mat.node_tree is None:
            continue
        name = mat.name
        if name in FACADES:
            _facade(mat, *FACADES[name])
            continue
        if name.startswith("haze"):
            if name.startswith("haze_far"):
                _haze(mat, "#c3d5ea", 1.05, 0.62)
            else:
                _haze(mat, "#d2e0ef", 1.0, 0.3)
            continue
        if name.startswith("window_view"):
            _window_view(mat, day_view)
            continue
        if name in DRY:
            _dry(mat)
            continue
        if name in SURFACES:
            b = _bsdf(mat)
            if b is not None and not b.inputs["Base Color"].links:
                b.inputs["Base Color"].default_value = lin(SURFACES[name])
            continue
        panel = next((k for k in PANELS if name.startswith(k)), None)
        if panel is not None:
            b = _bsdf(mat)
            if b is not None:
                b.inputs["Emission Strength"].default_value *= PANELS[panel]
            continue
        surface = _surface(mat)
        if surface is None or surface.type != "EMISSION":
            continue
        rule = next((r for r in PAINTS if name.startswith(r[0])), None)
        if rule is not None:
            _paint(mat, surface, rule[1], rule[2])
