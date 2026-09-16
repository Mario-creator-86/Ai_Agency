"""The street in front of the headquarters and the Bucharest skyline behind it.

Rows and columns are world pixels measured on the reference (world = reference - (10, 50)).
Vehicles, pedestrians, the sky, the live clock and the rotating advertisements are drawn by the
web canvas; this file only builds what stands still, and exports the lanes and walk lines.
"""

import math
import random

import bpy
from hq_building import light, text
from hq_lib import (
    MB,
    COS,
    M,
    X,
    Y,
    Z,
    asphalt_material,
    emissive,
    haze_material,
    foliage_material,
    leaf_cards,
    gradient_emission,
    lin,
    principled,
    project,
    windows_material,
)
from mathutils import Vector

TERRACE_Z = -0.35
WALK_Z = -0.7
ROAD_Z = -0.85

STREET = {}


def row_of(z, y):
    return project((0.0, y, z))[1]


def beam(mb, p0, p1, r, m):
    """A thin square beam between two points (cables, arms)."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    length = d.length
    if length < 1e-6:
        return
    z = d.normalized()
    helper = Vector((0, 0, 1)) if abs(z.z) < 0.9 else Vector((1, 0, 0))
    x = z.cross(helper).normalized() * r
    y = z.cross(x).normalized() * r
    corners = [p0 + x + y, p0 - x + y, p0 - x - y, p0 + x - y]
    top = [c + d for c in corners]
    v0 = [mb.bm.verts.new(c) for c in corners]
    v1 = [mb.bm.verts.new(c) for c in top]
    k = mb.mi(m)
    for i in range(4):
        j = (i + 1) % 4
        f = mb.bm.faces.new((v0[i], v0[j], v1[j], v1[i]))
        f.material_index = k


def tree(trunks, crowns, xpx, y, top_row, radius, bark, leaf, seed, lean=0.0):
    rng = random.Random(seed)
    base_z = TERRACE_Z if y > -3.0 else WALK_Z
    top_z = Z(top_row, y)
    x = X(xpx)
    crown_c = Vector((x + lean, y, top_z - radius * 0.9))
    trunks.cyl(x, y, base_z, crown_c.z - radius * 0.3, 0.13, bark, seg=10, r_top=0.08)
    for b in range(3):
        a = rng.uniform(0, math.tau)
        end = crown_c + Vector((math.cos(a) * radius * 0.55, math.sin(a) * radius * 0.3, rng.uniform(-0.4, 0.3) * radius))
        beam(trunks, (x, y, crown_c.z - radius * 0.6), end, 0.035, bark)
    for i in range(6):
        sub = crown_c + Vector((rng.uniform(-0.5, 0.5) * radius, rng.uniform(-0.2, 0.2) * radius, rng.uniform(-0.35, 0.4) * radius))
        leaf_cards(crowns, sub, (radius * 0.62, radius * 0.42, radius * 0.52), 950, 0.11, leaf, seed * 7 + i, core=principled("crown_core", "#1c2e17", rough=0.9))


def lamp_post(mb, lights, xpx, y, top_row, mats, side=1, name="street_lamp"):
    x = X(xpx)
    top = Z(top_row, y)
    mb.cyl(x, y, WALK_Z, WALK_Z + 0.35, 0.14, mats["pole"], seg=14)
    mb.cyl(x, y, WALK_Z, top - 0.25, 0.065, mats["pole"], seg=12, r_top=0.05)
    mb.box(x - 0.2, x + 0.2, y - 0.2, y + 0.2, top - 0.42, top - 0.34, mats["pole"])
    mb.box(x - 0.17, x + 0.17, y - 0.17, y + 0.17, top - 0.34, top + 0.14, mats["lamp_glass"])
    mb.cyl(x, y, top + 0.14, top + 0.34, 0.26, mats["pole"], seg=4, r_top=0.04)
    light(lights, "POINT", (x, y - 0.3, top - 0.05), 1000, "#ffc27a", radius=0.25, name=name)
    col, row = project((x, y, top))
    STREET.setdefault("lamps", []).append({"x": round(col, 1), "y": round(row, 1)})


def planter(mb, leaves, x0px, x1px, y0, y1, z0, z1, mats, seed, bush_height=0.8):
    rng = random.Random(seed)
    mb.box(X(x0px), X(x1px), y0, y1, z0, z1, mats["planter"])
    mb.box(X(x0px) - 0.02, X(x1px) + 0.02, y0 - 0.02, y1 + 0.02, z1 - 0.04, z1, mats["planter_rim"])
    x = X(x0px) + 0.3
    while x < X(x1px) - 0.2:
        c = (x, (y0 + y1) / 2 + rng.uniform(-0.1, 0.1), z1 + bush_height * rng.uniform(0.3, 0.45))
        leaf_cards(leaves, c, (0.42, max(0.2, (y1 - y0) * 0.4), bush_height * 0.5), 260, 0.075, mats["bush"], seed * 17 + int(x * 10), core=mats["bush_core"])
        x += rng.uniform(0.5, 0.7)


def tower(mb, x0px, x1px, top_row, y, facade, crown=None, beacon=None, depth=8.0, base_z=-25.0):
    top = Z(top_row, y)
    mb.box(X(x0px), X(x1px), y, y + depth, base_z, top, facade)
    if crown:
        cx0, cx1, crow = crown
        ctop = Z(crow, y + 1.0)
        mb.box(X(cx0), X(cx1), y + 1.0, y + depth - 1.0, top, ctop, facade)
        top = ctop
    if beacon:
        mb.sphere((X((x0px + x1px) / 2), y - 0.1, top + 0.08), 0.1, beacon, seg=8, rings=5)
    return top


def build(colls):
    city = colls["city"]
    back = colls["street_back"]
    ground = colls["street_ground"]
    props_c = colls["street_props"]
    front = colls["street_front"]
    lights = colls["lights_exterior"]

    mats = {
        "pole": principled("pole", "#202430", rough=0.4, metal=0.6),
        "lamp_glass": emissive("lamp_glass", "#ffd08a", 28.0),
        "planter": principled("planter", "#3a3b48", rough=0.7),
        "planter_rim": principled("planter_rim", "#3d3f4c", rough=0.4),
        # the picture's planters hold bright, full bushes; ours read as dark clumps in their boxes
        "bush": foliage_material("bush", "#2f5f35", "#9ccf61", translucent=0.45),
        "bush_core": principled("bush_core", "#12220f", rough=0.9),
        "tree": foliage_material("tree_leaf", "#46803a", "#cfe07a", translucent=0.6),
        "bark": principled("bark", "#2c241f", rough=0.8),
        # the crossing reads as blown-out white under the street fill; the picture's is a worn grey
        "paint": principled("road_paint", "#4a4b55", rough=0.55),
        # the pavement in front of the shopfronts reads 20 darker than the picture's
        "led": emissive("terrace_led", "#ffd7a0", 8.5),
    }

    # ------------------------------------------------------------------ ground planes
    g = MB("street_ground")
    y_bld = -0.28
    y_terrace = Y(676, TERRACE_Z)
    y_walk = Y(717, WALK_Z)
    y_road = Y(790, ROAD_Z)
    terrace = principled("terrace", "#6e5c52", rough=0.42, coat=0.12)
    # The picture's pavement is wet like its road: the shopfronts and the lamps lie on it in long
    # streaks. At 0.82 ours scattered all of it and read as a flat grey band.
    walk = principled("sidewalk", "#484652", rough=0.5)
    curb = principled("curb", "#3c3a4a", rough=0.8)
    g.box(X(0), X(1600), y_terrace, 12.0, TERRACE_Z - 0.3, TERRACE_Z, terrace)
    g.box(X(0), X(1600), y_terrace - 0.02, y_terrace, TERRACE_Z - 0.05, TERRACE_Z - 0.01, mats["led"])
    g.box(X(0), X(1600), y_walk, y_terrace, WALK_Z - 0.3, WALK_Z, walk)
    tiles = principled("sidewalk_joint", "#2a2429", rough=0.6)
    for xp in range(0, 1601, 42):
        g.box(X(xp), X(xp) + 0.03, y_walk, y_terrace, WALK_Z, WALK_Z + 0.002, tiles)
    g.box(X(0), X(1600), y_walk - 0.25, y_walk, ROAD_Z, WALK_Z, curb)
    g.box(X(0), X(1600), y_road, y_walk - 0.25, ROAD_Z - 0.3, ROAD_Z, asphalt_material("asphalt_wet", wet=1.0))
    g.box(X(0), X(1600), y_road - 0.25, y_road, ROAD_Z, WALK_Z, curb)
    # The near pavement is out of the lamps' pools. It was a light, cool grey, and the frame's lowest
    # rows came out at 43, 42, 55 against the picture's 11, 20, 38 — a pale band across the bottom of
    # the shot where the picture has the dark edge of the street.
    g.box(X(0), X(1600), -60.0, y_road - 0.25, WALK_Z - 0.3, WALK_Z, principled("sidewalk_near", "#31303c", rough=0.7))
    for x0 in range(674, 852, 22):
        g.box(X(x0), X(x0 + 13), y_road + 0.6, y_walk - 0.7, ROAD_Z, ROAD_Z + 0.004, mats["paint"])
    y_mid = (y_road + y_walk) / 2
    x = 0
    while x < 1600:
        if not (650 < x < 880):
            g.box(X(x), X(min(x + 56, 1600)), y_mid - 0.07, y_mid + 0.07, ROAD_Z, ROAD_Z + 0.004, mats["paint"])
        x += 96
    for yy in (y_walk - 0.6, y_road + 0.5):
        g.box(X(0), X(1600), yy - 0.05, yy + 0.05, ROAD_Z, ROAD_Z + 0.004, principled("lane_edge", "#8a8578", rough=0.6))
    # steps from the terrace down to the pavement in front of the lobby
    for i in range(2):
        z = TERRACE_Z - (i + 1) * 0.12
        g.box(X(600), X(905), y_terrace - 0.35 * (i + 1), y_terrace - 0.35 * i, WALK_Z - 0.2, z, terrace)
    g.build(ground)

    STREET["terrace_row"] = round(row_of(TERRACE_Z, y_terrace), 1)
    STREET["walk"] = {
        "far": round(row_of(WALK_Z, y_terrace - 0.8), 1),
        "near": round(row_of(WALK_Z, y_walk + 1.4), 1),
    }
    lane_far = y_walk - 3.4
    lane_near = y_road + 3.4
    STREET["lanes"] = [
        {"id": "far", "row": round(row_of(ROAD_Z, lane_far), 1), "direction": -1},
        {"id": "near", "row": round(row_of(ROAD_Z, lane_near), 1), "direction": 1},
    ]
    STREET["road"] = {"top": round(row_of(ROAD_Z, y_walk), 1), "bottom": round(row_of(ROAD_Z, y_road), 1)}
    STREET["crosswalk"] = {"x": 674, "w": 178}
    STREET["near_walk_row"] = round(row_of(WALK_Z, y_road - 1.2), 1)
    STREET["pixels_per_metre_x"] = 28.0
    STREET["pixels_per_metre_up"] = round(28.0 * COS, 3)

    # ------------------------------------------------------------------ street furniture (behind people)
    p = MB("street_props")
    trunks = MB("tree_trunks")
    crowns = MB("tree_crowns")
    leaves = MB("street_bushes")
    planter(p, leaves, 140, 300, 1.0, 2.2, TERRACE_Z, TERRACE_Z + 0.55, mats, 1)
    planter(p, leaves, 312, 412, 1.0, 2.2, TERRACE_Z, TERRACE_Z + 0.55, mats, 2)
    planter(p, leaves, 1352, 1420, 0.6, 1.6, TERRACE_Z, TERRACE_Z + 0.55, mats, 3)
    planter(p, leaves, 1545, 1600, 0.6, 1.6, TERRACE_Z, TERRACE_Z + 0.55, mats, 4)
    planter(p, leaves, 612, 660, -1.4, -0.5, TERRACE_Z, TERRACE_Z + 0.5, mats, 5, bush_height=0.6)
    planter(p, leaves, 1200, 1240, -1.6, -0.6, TERRACE_Z, TERRACE_Z + 0.5, mats, 6, bush_height=0.6)
    for xpx, ty, top_row, radius, seed, lean in (
        (225, 3.0, 440, 3.2, 11, 0.0),
        (300, 0.2, 470, 2.9, 12, 0.0),
        (372, -1.4, 470, 2.6, 13, -0.4),
        (150, 4.0, 500, 2.6, 14, 0.0),
        (1378, -1.0, 450, 2.7, 15, -0.2),
        (1466, 1.5, 420, 3.0, 16, 0.0),
        (1580, 3.0, 450, 2.8, 17, 0.0),
    ):
        tree(trunks, crowns, xpx, ty, top_row, radius, mats["bark"], mats["tree"], seed, lean=lean)
        base = TERRACE_Z if ty > -3.0 else WALK_Z
        light(lights, "SPOT", (X(xpx), ty - 1.2, base + 0.25), 1500, "#ffc27a", radius=0.15, cone=95, blend=0.6, rot=(math.radians(-10), 0, 0), name="tree_uplight")
    lamp_post(p, lights, 92, y_walk + 0.5, 410, mats, name="lamp_far_left")
    lamp_post(p, lights, 322, y_terrace + 1.2, 505, mats, name="lamp_left")
    lamp_post(p, lights, 1406, y_walk + 0.6, 485, mats, name="lamp_right")
    # bench in front of the lobby
    wood = principled("bench_wood", "#8a6a44", rough=0.5)
    by = y_terrace - 1.6
    p.box(X(882), X(952), by, by + 0.45, WALK_Z + 0.42, WALK_Z + 0.48, wood)
    p.box(X(882), X(952), by + 0.4, by + 0.48, WALK_Z + 0.55, WALK_Z + 0.9, wood)
    for xp in (886, 946):
        p.box(X(xp), X(xp) + 0.06, by, by + 0.45, WALK_Z, WALK_Z + 0.42, mats["pole"])
    STREET["bench"] = {"x": 882, "w": 70, "row": round(row_of(WALK_Z + 0.45, by + 0.2), 1)}
    # bus shelter
    sy0 = y_walk + 1.2
    sy1 = sy0 + 1.8
    roof_z = Z(596, sy0)
    shelter_metal = principled("shelter_metal", "#2a2f3b", rough=0.35, metal=0.6)
    p.box(X(1378), X(1545), sy0 - 0.2, sy1, roof_z - 0.12, roof_z, shelter_metal)
    p.box(X(1378), X(1545), sy0 - 0.21, sy0 - 0.2, roof_z - 0.12, roof_z - 0.08, mats["led"])
    for xp in (1382, 1482):
        p.box(X(xp), X(xp) + 0.1, sy0, sy0 + 0.1, WALK_Z, roof_z - 0.12, shelter_metal)
    p.front_quad(X(1386), X(1482), WALK_Z + 0.1, roof_z - 0.2, sy1 - 0.05, principled("shelter_glass", "#9fb4c8", rough=0.05, alpha=0.12))
    clock_z0, clock_z1 = Z(657, sy0 + 0.3), Z(620, sy0 + 0.3)
    p.box(X(1408), X(1480), sy0 + 0.3, sy0 + 0.45, clock_z0, clock_z1, principled("clock_box", "#0c1c22", rough=0.3))
    STREET["shelter_clock"] = {"rect": _rect(X(1411), X(1477), clock_z0 + 0.08, clock_z1 - 0.08, sy0 + 0.29)}
    ad_z0, ad_z1 = WALK_Z + 0.15, Z(606, sy0 + 0.1)
    p.box(X(1484), X(1540), sy0 + 0.1, sy0 + 0.3, ad_z0, ad_z1, shelter_metal)
    p.front_quad(X(1487), X(1537), ad_z0 + 0.1, ad_z1 - 0.1, sy0 + 0.09, gradient_emission("shelter_ad", "#10325a", "#3a7ac8", 2.2))
    STREET["shelter_ad"] = {"rect": _rect(X(1487), X(1537), ad_z0 + 0.1, ad_z1 - 0.1, sy0 + 0.08)}
    light(lights, "AREA", (X(1460), sy0 + 0.9, roof_z - 0.3), 60, "#ffe2b0", radius=1.5, name="shelter_light")
    p.build(props_c, bevel=0.01)
    trunks.build(back)
    crowns.build(back, smooth=True)
    leaves.build(props_c, smooth=True)

    # bollards along the kerb, drawn after pedestrians walking behind them
    b = MB("bollards")
    bollard = principled("bollard", "#1c1d24", rough=0.35, metal=0.4)
    yb = y_walk + 0.45
    for xp in (22, 92, 180, 252, 460, 548, 612, 700, 792, 960, 1006, 1075, 1136, 1188, 1250, 1320, 1440, 1560):
        b.cyl(X(xp), yb, WALK_Z, WALK_Z + 1.0, 0.1, bollard, seg=12)
        b.cyl(X(xp), yb, WALK_Z + 1.0, WALK_Z + 1.06, 0.085, bollard, seg=12, r_top=0.04)
    b.build(colls["street_kerb"], bevel=0.0)
    STREET["kerb_row"] = round(row_of(WALK_Z, yb), 1)

    # near planters, in front of the traffic
    nf = MB("near_planters")
    nleaves = MB("near_bushes")
    for i, (x0, x1) in enumerate(((39, 281), (415, 536), (702, 763), (1091, 1237), (1305, 1508), (1512, 1593))):
        planter(nf, nleaves, x0, x1, -32.0, -30.4, WALK_Z, WALK_Z + 1.0, mats, 40 + i, bush_height=0.75)
    nf.build(front, bevel=0.02)
    nleaves.build(front, smooth=True)

    build_city(city, mats)
    return STREET


def _rect(x0, x1, z0, z1, y):
    a = project((x0, y, z0))
    c = project((x1, y, z1))
    return [round(a[0], 1), round(c[1], 1), round(c[0] - a[0], 1), round(a[1] - c[1], 1)]


def build_city(city, mats):
    t = MB("skyline")
    rng = random.Random(3)
    # The picture's towers keep most of their windows dark: a scattering of lit ones, in bands,
    # against the dusk. Ours had a third to a half of every grid alight, which read as a wall of
    # yellow squares and made the skyline look near. The ratios below are halved.
    dark = windows_material("tower_dark", "#1c2440", lit_ratio=0.18, win_w=0.18, win_h=0.28, strength=7.5)
    blue = windows_material("tower_blue", "#26304f", lit_ratio=0.19, win_w=0.17, win_h=0.27, strength=7.5)
    mauve = windows_material("tower_mauve", "#343652", lit_ratio=0.18, win_w=0.19, win_h=0.29, strength=7.5)
    dense = windows_material("city_dense", "#1f2438", lit_ratio=0.18, win_w=0.16, win_h=0.26, strength=7.0)
    cool = windows_material("tower_cool", "#1e2640", lit_ratio=0.2, win_w=0.22, win_h=0.34, strength=6.5, warm=False)
    beacon = emissive("beacon", "#ff3b3b", 25.0)
    # far city band (lowest, densest lights)
    for i in range(40):
        x0 = rng.uniform(-40, 1640)
        w = rng.uniform(24, 70)
        top = rng.uniform(470, 600)
        tower(t, x0, x0 + w, top, 60.0 + rng.uniform(0, 5), dense, depth=5.0)
    # mid-rise blocks in front of the towers (the dense lit city under the bridge)
    mid = windows_material("city_mid", "#1d2134", lit_ratio=0.18, win_w=0.28, win_h=0.42, strength=7.0)
    for i in range(22):
        x0 = rng.uniform(-20, 430)
        w = rng.uniform(26, 60)
        tower(t, x0, x0 + w, rng.uniform(385, 520), 14.0 + rng.uniform(0, 6), mid, depth=4.0)
    for i in range(10):
        x0 = rng.uniform(1345, 1600)
        w = rng.uniform(26, 60)
        tower(t, x0, x0 + w, rng.uniform(380, 500), 14.0 + rng.uniform(0, 6), mid, depth=4.0)
    # left
    tower(t, 30, 92, 330, 45.0, blue, beacon=beacon)
    tower(t, 92, 128, 385, 50.0, mauve)
    tower(t, 127, 200, 175, 40.0, dark, crown=(140, 186, 150), beacon=beacon)
    strip = emissive("tower_strip", "#f6f2ff", 9.0)
    for i in range(26):
        rr = 240 + i * 6.2
        xx = 192 + 6 * math.sin(i / 26 * math.pi)
        t.box(X(xx), X(xx + 4), 39.8, 39.9, Z(rr + 3, 39.8), Z(rr, 39.8), strip)
    tower(t, 200, 236, 250, 42.0, cool)
    tower(t, 236, 300, 385, 55.0, mauve)
    tower(t, 300, 350, 330, 44.0, blue, beacon=beacon)
    top = tower(t, 352, 388, 158, 38.0, dark)
    t.box(X(369), X(371), 38.5, 38.7, top, top + 2.2, principled("antenna", "#303442", rough=0.5))
    t.sphere((X(370), 38.4, top + 2.25), 0.18, beacon, seg=8, rings=6)
    tower(t, 388, 430, 280, 46.0, cool)
    top = tower(t, 256, 274, 262, 47.0, dark)
    t.cyl(X(265), 47.0, top, top + 3.6, 0.2, principled("spire", "#2a3350", rough=0.4, metal=0.4), seg=8, r_top=0.02)
    crown_glow = emissive("crown_glow", "#ffcf9a", 6.0)
    t.box(X(142), X(184), 39.8, 39.9, Z(152, 39.8), Z(149, 39.8), crown_glow)
    t.box(X(1480), X(1556), 39.8, 39.9, Z(125, 39.8), Z(122, 39.8), emissive("crown_glow_cool", "#9fd0ff", 5.0))
    # billboard building with its sign
    tower(t, 95, 212, 404, 30.0, dense)
    board = principled("billboard_frame", "#101522", rough=0.4)
    t.box(X(95), X(184), 29.6, 29.9, Z(404, 29.6), Z(360, 29.6), board)
    t.front_quad(X(98), X(181), Z(401, 29.55), Z(363, 29.55), 29.55, gradient_emission("billboard", "#2a4c96", "#3f68b8", 2.4))
    text(city, "BUCHAREST\nAI DISTRICT", X(139.5), 29.5, Z(378, 29.5), 0.52, emissive("billboard_text", "#f5f7ff", 4.0), align="CENTER", spacing=1.05, line=1.05, name="billboard_text")
    STREET["billboard"] = {"rect": _rect(X(98), X(181), Z(401, 29.55), Z(363, 29.55), 29.55)}
    # cable-stayed bridge
    br = principled("bridge", "#3a3f52", rough=0.4, metal=0.5)
    by = 34.0
    deck_z = Z(368, by)
    pylon_top = Z(262, by)
    t.box(X(233), X(241), by, by + 0.6, deck_z - 6.0, pylon_top, br)
    # a warm line up the pylon: against the towers behind it, a dark pylon alone does not read
    t.box(X(236.5), X(237.5), by - 0.02, by, deck_z, pylon_top, emissive("pylon_edge", "#ffb870", 1.5))
    t.box(X(186), X(292), by - 0.3, by + 0.9, deck_z - 0.25, deck_z, br)
    cable = emissive("bridge_cable", "#e8a86a", 0.9)
    # the cables leave the pylon at many heights and fan down to the deck
    for i in range(1, 11):
        for side in (-1, 1):
            xe = 237 + side * i * 5.2
            beam(t, (X(237), by - 0.05, pylon_top - 0.3 - (10 - i) * 0.32), (X(xe), by - 0.05, deck_z), 0.012, cable)
    deck_light = emissive("bridge_light", "#ffc98a", 14.0)
    for xp in range(188, 292, 6):
        t.sphere((X(xp), by - 0.35, deck_z + 0.05), 0.055, deck_light, seg=8, rings=5)
    # low block "SAME CITY BRIGHTER MINDS"
    near = MB("near_blocks")
    same = principled("same_city", "#24242e", rough=0.5)
    near.box(X(0), X(156), 3.0, 9.0, -1.5, Z(517, 3.0), same)
    near.box(X(0), X(156), 2.98, 3.0, Z(518, 3.0), Z(517, 3.0), principled("same_city_edge", "#3a3a48", rough=0.4))
    teal = emissive("teal_dash", "#2dd4bf", 5.0)
    near.box(X(25), X(33), 2.97, 2.98, Z(548, 3.0), Z(546, 3.0), teal)
    near.box(X(25), X(33), 2.97, 2.98, Z(640, 3.0), Z(638, 3.0), teal)
    text(city, "SAME\nCITY\nBRIGHTER\nMINDS", X(24), 2.96, Z(572, 2.96), 0.44, emissive("same_city_text", "#dcdfe8", 2.2), spacing=1.1, line=1.2, name="same_city_text", face="sign")
    near.box(X(95), X(99), 2.0, 2.2, WALK_Z, Z(650, 2.0), mats["pole"])
    near.box(X(92), X(103), 1.9, 2.0, Z(632, 1.9), Z(602, 1.9), principled("sign_panel", "#d6d6d0", rough=0.5))
    # right side
    # The city right of the building reads darker than the picture (its region 59 against 50 in the
    # stream), and it lost light again when the towers' lit share was halved, so the two facades
    # only this side uses keep more of theirs.
    right_dark = windows_material("tower_right", "#1c2233", lit_ratio=0.4, win_w=0.28, win_h=0.4, strength=7.5)
    tower(t, 1350, 1402, 290, 48.0, blue)
    tower(t, 1400, 1456, 150, 45.0, dark, beacon=beacon)
    tower(t, 1458, 1578, 175, 40.0, right_dark, crown=(1478, 1558, 122))
    tower(t, 1560, 1640, 230, 50.0, mauve)
    t.box(X(1490), X(1566), 39.7, 39.8, Z(345, 39.7), Z(250, 39.7), principled("slogan_panel", "#1b2130", rough=0.5))
    text(city, "CREATE\nAUTOMATE\nSCALE\nTOGETHER", X(1497), 39.6, Z(284, 39.6), 0.46, emissive("slogan_text", "#d5dbe6", 3.0), spacing=1.1, line=1.2, name="slogan_text", face="sign")
    text(city, "//", X(1545), 39.6, Z(266, 39.6), 0.5, teal, name="slogan_dash_top")
    text(city, "//", X(1500), 39.6, Z(338, 39.6), 0.5, teal, name="slogan_dash_bottom")
    classic = windows_material("classic", "#7a5e50", lit_ratio=0.55, win_w=0.9, win_h=1.5, strength=5.5)
    near.box(X(1490), X(1600), 4.0, 5.2, -1.5, Z(372, 4.0), classic)
    stone = principled("classic_stone", "#6a5446", rough=0.6)
    near.box(X(1486), X(1600), 3.7, 5.4, Z(372, 3.7), Z(362, 3.7), stone)
    near.box(X(1492), X(1600), 4.2, 5.3, Z(362, 4.2), Z(352, 4.2), stone)
    for rr in (430, 500):
        near.box(X(1488), X(1600), 3.8, 4.0, Z(rr + 3, 3.8), Z(rr, 3.8), stone)
    near.build(city, bevel=0.01)
    haze = MB("haze")
    haze.front_quad(X(-20), X(1620), Z(700, 22.0), Z(250, 22.0), 22.0, haze_material("haze_near", "#2f3658", 0.42, 0.0, 1.0))
    haze.front_quad(X(-20), X(1620), Z(640, 52.0), Z(300, 52.0), 52.0, haze_material("haze_far", "#6f7aa6", 0.5, 0.0, 1.1))
    haze.build(city)
    t.build(city)
