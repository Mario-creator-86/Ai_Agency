"""The AMN-AI headquarters building: shell, floors, rooms and the lift tower.

Every x is a world-pixel column and every wall height a world-pixel row measured on
art-source/reference/headquarters_dusk_primary.png (world = reference - (10, 50)).
Characters, lift cab passengers and anything that shows live state are not modelled here: the
web canvas draws those from backend data. What is exported instead are anchors (seats, screens,
lamps, lift stops) projected from the modelled geometry.
"""

import math
import os
import random

import bpy
from hq_lib import (
    BACK_WALL,
    MB,
    M,
    X,
    Z,
    bookshelf,
    brick_material,
    emissive,
    frame_picture,
    gradient_emission,
    image_material,
    lin,
    monitor,
    panel_material,
    plant,
    principled,
    project,
    screen_material,
    sofa,
    window_view_material,
)

FONTS = {
    "sign": "C:/Windows/Fonts/bahnschrift.ttf",
    "label": "C:/Windows/Fonts/seguisb.ttf",
    "bold": "C:/Windows/Fonts/segoeuib.ttf",
}
FLOORS = {4: (177, 85), 3: (282, 195), 2: (392, 297), 1: (500, 410), 0: (655, 520)}
LEFT = 447
RIGHT = 1205
BACK = BACK_WALL
BACK_G = 3.2
# The Unreal export's own object for the desk monitors and mugs (AMN_UNREAL_WORKSTATIONS=1); None
# keeps them with the desks, as the web plates need.
SCREENS = None

ANCHORS = {
    "rooms": {},
    "seats": {},
    "screens": {},
    "lamps": [],
    "displays": {},
    "lift": {},
    "labels": {},
}


def fz(level):
    return Z(FLOORS[level][0])


def cz(level):
    return Z(FLOORS[level][1])


def wz(row, y=None):
    """Height on the back wall for a screen row."""
    return Z(row, (BACK if y is None else y) - 0.02)


_font = {}


def font(kind="label"):
    if kind not in _font:
        _font[kind] = bpy.data.fonts.load(FONTS[kind])
    return _font[kind]


def text(coll, body, x, y, z, size, mat, align="LEFT", spacing=1.0, line=1.0, extrude=0.0, name="txt", face="label"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.font = font(face)
    cu.size = size
    cu.align_x = align
    cu.space_character = spacing
    cu.space_line = line
    cu.extrude = extrude
    cu.materials.append(mat)
    ob = bpy.data.objects.new(name, cu)
    ob.location = (x, y, z)
    ob.rotation_euler = (math.pi / 2, 0.0, 0.0)
    coll.objects.link(ob)
    return ob


def light(coll, kind, loc, energy, color, radius=0.1, cone=70, blend=0.5, rot=(0.0, 0.0, 0.0), name="L"):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = lin(color)[:3]
    if kind == "AREA":
        ld.size = radius
    else:
        ld.shadow_soft_size = radius
    if kind == "SPOT":
        ld.spot_size = math.radians(cone)
        ld.spot_blend = blend
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    ob.rotation_euler = rot
    ob.visible_camera = False
    coll.objects.link(ob)
    return ob


def px_rect(x0, x1, z0, z1, y):
    """A camera-facing rectangle given in metres -> [x, y, w, h] in world pixels."""
    a = project((x0, y, z0))
    b = project((x1, y, z1))
    return [round(a[0], 1), round(b[1], 1), round(b[0] - a[0], 1), round(a[1] - b[1], 1)]


def screen_anchor(key, x0, x1, z0, z1, y, **extra):
    """Record where a live display is, in world pixels (x, y, w, h)."""
    ANCHORS["screens"][key] = {"rect": px_rect(x0, x1, z0, z1, y), **extra}


def seat(desk_id, xpx, level, facing, zone, y=1.2):
    x = X(xpx)
    col, row = project((x, y, fz(level)))
    ANCHORS["seats"][desk_id] = {"x": round(col, 1), "y": round(row, 1), "facing": facing, "zone": zone, "level": level}


# ----------------------------------------------------------------------------- materials


def materials():
    return {
        "frame": principled("frame_dark", "#2f3a56", rough=0.4, metal=0.5),
        "frame_hi": principled("frame_hi", "#566077", rough=0.3, metal=0.6),
        "stone": brick_material("stone", "#6a6f7c", "#5f6470", "#2c2f36", brick_w=1.2, row_h=0.55, rough=0.75),
        # The roof stands against the sky and takes its light: in the picture that band reads
        # 28, 39, 65 where ours read 29, 30, 46 - short of the dusk's blue.
        # Still short once the deck came down to the picture's roofline: over columns 700-870 the
        # deck's top face reads 16, 19, 32 where the picture reads 15, 29, 57 (rows 28-38) - the
        # right darkness, half the dusk's blue. The face renders at about 0.57, 0.42, 0.41 of the
        # base colour, so the picture asks for roughly 26, 69, 139; #1c3c78 goes most of that way
        # and stops short of a colour that would read as paint rather than as a roof at dusk.
        "roof": principled("roof", "#1c3c78", rough=0.65),
        "slab": principled("slab", "#2f3857", rough=0.55, metal=0.15),
        "sign_glass": principled("sign_glass", "#080b16", rough=0.18, metal=0.2),
        # the sign band reads 11 to 17 brighter than the picture's over its rows
        "gold": emissive("gold_text", "#f4c47f", 4.2),
        "gold_dim": emissive("gold_dim", "#e9b56f", 2.5),
        "edge_led": emissive("edge_led", "#ffd7a0", 1.6),
        "edge_led_warm": emissive("edge_led_warm", "#ffc070", 3.0),
        "edge_led_slab": emissive("edge_led_slab", "#ffd7a0", 0.8),
        # The floor labels stand on the building's front, and the picture's read a deep blue
        # (37, 39, 75 at L1); ours came out 32, 33, 46 once the street lamps stopped lighting them.
        "label": principled("label_dark", "#262c4c", rough=0.4),
        "label_text": emissive("label_text", "#eef1f8", 3.2),
        "label_text_dim": emissive("label_text_dim", "#c9cfdc", 2.4),
        "glass": principled("glass", "#8fa6c0", rough=0.04, alpha=0.1),
        "glass_dark": principled("glass_dark", "#1b2633", rough=0.08, alpha=0.55),
        "console": principled("console", "#f1ebe2", rough=0.32, emit="#fff4e6", strength=0.12),
        "console_top": emissive("console_top", "#fff2dd", 1.8),
        "console_slot": principled("console_slot", "#2a2b33", rough=0.4),
        "desk": principled("desk_dark", "#2d2b31", rough=0.45),
        "desk_top": principled("desk_top", "#3a3439", rough=0.35),
        "desk_white": principled("desk_white", "#e3ded6", rough=0.35),
        "desk_panel": principled("desk_panel", "#cfc9bf", rough=0.5),
        "chair": principled("chair_fabric", "#23252c", rough=0.7),
        "mug": principled("mug", "#c2410c", rough=0.4),
        "wood": principled("wood", "#6a4a2e", rough=0.45),
        "wood_dark": principled("wood_dark", "#3b2a1e", rough=0.5),
        "black": principled("black", "#121318", rough=0.45),
        "metal": principled("metal", "#9aa3ad", rough=0.28, metal=0.85),
        "white": principled("white", "#dedad2", rough=0.4),
        "pot_white": principled("pot_white", "#d7d2c8", rough=0.45),
        "pot_dark": principled("pot_dark", "#2c2c33", rough=0.5),
        "leaf": principled("leaf", "#3f7a36", rough=0.6),
        "leaf_dark": principled("leaf_dark", "#28562a", rough=0.65),
        "mon_frame": principled("mon_frame", "#15161c", rough=0.35),
        "screen_blue": image_material("screen_blue", "ui_blue", 1.6),
        "screen_blue_chart": image_material("screen_blue_chart", "ui_blue_chart", 1.6),
        "screen_cyan": image_material("screen_cyan", "ui_cyan", 1.6),
        "screen_cyan_chart": image_material("screen_cyan_chart", "ui_cyan_chart", 1.6),
        "screen_dim": image_material("screen_dim", "ui_blue_chart", 0.7),
        "window": image_material("window_view", "window_city", 1.3),
        "window_b": image_material("window_view_b", "window_city_b", 1.3),
        # The upper floors' panes are frosted in the picture, not a view: an even blue, palest at
        # the head (L3 reads 184, 194, 226 at row 206) and deeper at the sill (119, 147, 210 at row
        # 232), with no skyline behind it. Against window_city L3's glass came out 43, 75, 93 short
        # and L4's 27, 54, 59. The names keep the window_view prefix so build_hq.daytime() still
        # finds them when it swaps the day view in.
        "window_l3": gradient_emission("window_view_l3", "#5878b4", "#93a6c6", 1.45),
        "window_l4": gradient_emission("window_view_l4", "#3f5f9c", "#7c93bb", 1.3),
        "lamp_shade": emissive("lamp_shade", "#ffd49a", 6.0),
        "lamp_bulb": emissive("lamp_bulb", "#fff0d6", 18.0),
        "books": [
            principled("book_red", "#7c2d22", rough=0.6),
            principled("book_blue", "#2d4a78", rough=0.6),
            principled("book_ochre", "#b88a34", rough=0.6),
            principled("book_green", "#3a6338", rough=0.6),
            principled("book_plum", "#5a3a68", rough=0.6),
            principled("book_cream", "#d9cfbd", rough=0.6),
            principled("book_brown", "#80542c", rough=0.6),
        ],
    }


# ----------------------------------------------------------------------------- pieces


def console(mb, cx, width_px, level, mat, y0=0.32, y1=0.9, height=0.95):
    """The lit front console every workstation has in the reference (in front of the seat)."""
    x0, x1 = X(cx - width_px / 2), X(cx + width_px / 2)
    f = fz(level)
    height = min(height, 0.66)
    mb.box(x0, x1, y0, y1, f, f + height - 0.05, mat["console"])
    mb.box(x0 - 0.02, x1 + 0.02, y0 - 0.02, y1, f + height - 0.05, f + height, mat["console_top"])
    mb.box(x0 + (x1 - x0) * 0.18, x1 - (x1 - x0) * 0.18, y0 - 0.01, y0, f + 0.16, f + 0.34, mat["console_slot"])
    mb.box(x0 + (x1 - x0) * 0.3, x1 - (x1 - x0) * 0.3, y0 - 0.012, y0 - 0.005, f + 0.21, f + 0.28, mat["console_top"])


def rack_front(mb, glow, x0, x1, z0, z1, y, seed):
    """A rack face: dark units with slot lines and a few steady status lamps. The canvas adds the
    blinking that follows how busy the studio is."""
    mb.front_quad(x0, x1, z0, z1, y, principled("rack_face", "#0b0e13", rough=0.35, metal=0.3))
    unit = principled("rack_unit", "#1c222b", rough=0.4, metal=0.4)
    green = emissive("rack_led_green", "#4ade80", 6.0)
    amber = emissive("rack_led_amber", "#fbbf24", 5.0)
    rng = random.Random(seed)
    z = z0 + 0.06
    while z < z1 - 0.1:
        mb.box(x0 + 0.02, x1 - 0.02, y - 0.012, y - 0.002, z, z + 0.012, unit)
        if rng.random() < 0.7:
            glow.box(x0 + 0.05, x0 + 0.08, y - 0.014, y - 0.004, z + 0.04, z + 0.07, amber if rng.random() < 0.15 else green)
        if rng.random() < 0.35:
            glow.box(x1 - 0.1, x1 - 0.07, y - 0.014, y - 0.004, z + 0.04, z + 0.07, green)
        z += 0.14
    glow.box(x0, x1, y - 0.012, y - 0.004, z1 - 0.05, z1 - 0.02, emissive("rack_top_bar", "#34d399", 3.0))


def vending_front(mb, glow, x0, x1, z0, z1, y, seed):
    """A lit vending window standing proud of the machine: shelves of cans before a bright panel."""
    glow.front_quad(x0, x1, z0, z1, y, emissive("vending_back", "#e8f1ff", 1.6))
    shelf = principled("vending_shelf", "#9aa3ad", rough=0.3, metal=0.8)
    cans = [principled(f"can_{c[1:]}", c, rough=0.3, metal=0.5) for c in ("#dc2626", "#2563eb", "#16a34a", "#f59e0b", "#f8fafc", "#7c3aed")]
    rng = random.Random(seed)
    rows = 5
    for r in range(rows):
        zb = z0 + (z1 - z0) * r / rows
        mb.box(x0, x1, y - 0.1, y - 0.005, zb, zb + 0.02, shelf)
        x = x0 + 0.03
        while x < x1 - 0.08:
            w = rng.uniform(0.05, 0.07)
            mb.box(x, x + w, y - 0.08, y - 0.03, zb + 0.02, zb + 0.02 + rng.uniform(0.12, 0.2), rng.choice(cans))
            x += w + 0.02
    mb.front_quad(x0, x1, z0, z1, y - 0.11, principled("vending_glass", "#9fb6cc", rough=0.05, alpha=0.12))


def workstation(fronts, props, cx, level, mat, screen_tex, zone, desk, side=1, seat_y=1.2):
    """One employee's own desk, seen from the front. The person sits behind it facing the viewer; the
    monitor is turned in from one side so it never hides them; the chair stands behind them in the
    rooms layer, so the canvas draws the person between the chair and the desk."""
    f = fz(level)
    ox = X(cx)
    yf, yb = seat_y - 0.95, seat_y - 0.3
    x0, x1 = ox - 0.72, ox + 0.72
    top = f + 0.75
    fronts.box(x0, x1, yf, yb, top - 0.035, top, mat["desk_white"])
    fronts.box(x0 + 0.02, x1 - 0.02, yf - 0.004, yf, top - 0.05, top - 0.037, mat["console_top"])
    for xx in (x0 + 0.02, x1 - 0.06):
        fronts.box(xx, xx + 0.04, yf + 0.05, yb - 0.05, f, top - 0.035, mat["frame"])
    fronts.box(x0 + 0.06, x1 - 0.06, yf + 0.08, yf + 0.1, f + 0.42, top - 0.05, mat["desk_panel"])
    fronts.box(ox - 0.2, ox + 0.2, yb - 0.2, yb - 0.05, top, top + 0.02, mat["black"])
    mx, my = ox + side * 0.5, yf + 0.3
    # For Unreal the monitor and mug are their own object ("desk_screens"), kept when the desk and
    # chair are replaced by real furniture.
    screens = SCREENS if SCREENS is not None else fronts
    monitor(screens, mx, my, top, 0.6, 0.38, mat["mon_frame"], image_material(f"desk_screen_{desk}", screen_tex, 3.0), rz=math.radians(-side * 50))
    screens.cyl(ox - side * 0.42, yf + 0.35, top, top + 0.1, 0.04, mat["mug"], seg=14)
    screen_anchor(f"{desk}_monitor", mx - 0.2, mx + 0.2, top + 0.13, top + 0.5, my - 0.01, zone=zone, desk=desk)
    # The Unreal export keeps a whole workstation in one object ("consoles"), so the live scene can
    # replace it with real furniture; the web plates keep the chair in the rooms layer.
    chair = fronts if os.environ.get("AMN_UNREAL_WORKSTATIONS") == "1" else props
    chair.box(ox - 0.24, ox + 0.24, seat_y + 0.14, seat_y + 0.22, f + 0.55, f + 1.12, mat["chair"])
    chair.box(ox - 0.23, ox + 0.23, seat_y - 0.28, seat_y + 0.18, f + 0.42, f + 0.5, mat["chair"])
    chair.cyl(ox, seat_y - 0.03, f + 0.05, f + 0.42, 0.025, mat["frame"], seg=10)
    chair.box(ox - 0.3, ox + 0.3, seat_y - 0.08, seat_y + 0.02, f + 0.02, f + 0.05, mat["frame"])


def back_desk(mb, x0px, x1px, level, mat, depth=(1.75, 2.3), top=0.78, top_mat=None):
    f = fz(level)
    x0, x1 = X(x0px), X(x1px)
    # Not every counter carries the same slab: under L3's windows the picture's tops are a lit
    # honey plank (121, 103, 89) where ours read 67, 69, 97. top_mat replaces the top of one
    # counter without touching the rest of the building.
    mb.box(x0, x1, depth[0], depth[1], f + top - 0.05, f + top, top_mat or mat["desk_top"])
    mb.box(x0 + 0.05, x0 + 0.12, depth[0] + 0.05, depth[1] - 0.05, f, f + top - 0.05, mat["desk"])
    mb.box(x1 - 0.12, x1 - 0.05, depth[0] + 0.05, depth[1] - 0.05, f, f + top - 0.05, mat["desk"])
    return f + top


def wall_window(mb, x0px, x1px, top_row, bottom_row, mat, mullion=True, view="window"):
    x0, x1 = X(x0px), X(x1px)
    z1, z0 = wz(top_row), wz(bottom_row)
    y = BACK - 0.02
    mb.box(x0 - 0.06, x1 + 0.06, y - 0.06, y, z0 - 0.06, z1 + 0.06, mat["frame"])
    mb.front_quad(x0, x1, z0, z1, y - 0.065, mat[view])
    if mullion:
        mb.box((x0 + x1) / 2 - 0.025, (x0 + x1) / 2 + 0.025, y - 0.09, y - 0.06, z0, z1, mat["frame"])
    mb.box(x0 - 0.08, x1 + 0.08, y - 0.18, y, z0 - 0.1, z0 - 0.04, mat["white"])


def pendant(mb, coll, xpx, level, drop, mat, color="#ffc98a", energy=35.0, shade="dome"):
    x = X(xpx)
    c = cz(level)
    zc = c - drop
    y = 1.6
    mb.box(x - 0.006, x + 0.006, y - 0.006, y + 0.006, zc + 0.15, c, mat["black"])
    if shade == "dome":
        # The picture's pendants read as a dark shade over a bright warm band, with the wall washed
        # behind it. Ours were a black cone with a 1.4 cm emissive disc under it: at the plate's
        # scale the disc fell under a pixel and only the dark cone showed. The cone keeps its dark
        # shell; the lit underside is 6 cm deep and as wide as the shade, which reads as the band.
        # (Tried in the stream first with the whole cone warm: it blew out into a white blob.)
        mb.cyl(x, y, zc + 0.02, zc + 0.2, 0.34, mat["black"], seg=20, r_top=0.05)
        mb.cyl(x, y, zc - 0.03, zc + 0.03, 0.33, mat["lamp_shade"], seg=20)
    else:
        mb.sphere((x, y, zc + 0.05), 0.09, mat["lamp_bulb"], seg=12, rings=8)
    light(coll, "POINT", (x, y, zc - 0.12), energy, color, radius=0.12, name="pendant")
    col, row = project((x, y, zc))
    ANCHORS["lamps"].append({"x": round(col, 1), "y": round(row, 1), "color": color, "kind": "pendant"})


def spot_row(coll, xs, level, color, energy, cone=78, blend=0.7, tilt=22, y=1.7, drop=0.55):
    for xpx in xs:
        light(
            coll, "SPOT", (X(xpx), y, cz(level) - drop), energy, color, radius=0.05, cone=cone, blend=blend,
            rot=(math.radians(tilt), 0, 0), name="spot",
        )


def downlight_fixtures(mb, xs, level, mat, y=2.1, drop=0.47):
    for xpx in xs:
        x = X(xpx)
        z = cz(level) - drop
        mb.box(x - 0.13, x + 0.13, y - 0.1, y + 0.1, z, z + 0.05, mat["black"])
        mb.box(x - 0.09, x + 0.09, y - 0.07, y + 0.07, z - 0.012, z, mat["lamp_bulb"])


def label_panel(mb, coll, level, big, small, mat, accent=None):
    x0, x1 = X(450), X(517)
    f, c = fz(level), cz(level)
    mb.box(x0, x1, -0.08, BACK, f, c, mat["label"])
    if accent:
        acc = emissive(f"label_accent_{level}", accent, 5.0)
        mb.box(x0, x1, -0.09, -0.08, c - 0.07, c - 0.035, acc)
        mb.box(x1 - 0.035, x1, -0.09, -0.08, f, c - 0.07, acc)
    rows = {4: (142, 154), 3: (240, 252), 2: (353, 365), 1: (463, 475)}[level]
    text(coll, big, X(459), -0.1, Z(rows[0] + 1, -0.1), 1.05, mat["label_text"], name=f"label_big_{level}")
    text(coll, small, X(459), -0.1, Z(rows[1] + 2, -0.1), 0.5, mat["label_text_dim"], spacing=1.0, name=f"label_small_{level}")


def room_shell(mb, x0px, x1px, level, wall, floor_mat, back=BACK):
    f, c = fz(level), cz(level)
    mb.box(X(x0px), X(x1px), back, back + 0.2, f, c, wall)
    mb.box(X(x0px), X(x1px), -0.14, back, f - 0.06, f, floor_mat)
    # Tried: a dark ceiling of each room's own under the floor above, because over L2 that underside
    # is L3's blue-grey and the band read 125, 104, 88 against the picture's 101, 74, 48. It took the
    # bounce out of every room instead: L4 2.4 -> 5.8, L3 4.6 -> 8.9, L2 6.4 -> 8.3, mean 4.5 -> 5.6.


def cove(mb, x0px, x1px, level, mat, drop=0.5, back=BACK):
    z = cz(level) - drop
    mb.box(X(x0px), X(x1px), back - 0.12, back - 0.02, z - 0.035, z, mat)


def ceiling_cove(shell, lights, level, mat, xs=(575, 690, 805, 920, 1035, 1150), line=None):
    """The picture's warm LED line under each office floor's ceiling, hung just behind the slab's
    face so it shows from the front, and a row of small warm lights beside it that wash the top of
    the room ("cove_wash"; the live look pass scales them with AMN_LOOK_COVE).

    `line` gives the line its own material where the storey above is not a lit room."""
    c = cz(level)
    # its own material, dimmer than the slabs' edge_led_warm (3.0) it first shared: in the live frame the
    # line burnt the band under each ceiling (L2's 111 against the picture's 71)
    shell.box(X(517), X(1205), -0.12, -0.02, c - 0.045, c - 0.015, line or emissive("cove_led", "#ffc98a", 1.2))
    for xpx in xs:
        light(lights, "POINT", (X(xpx), 0.25, c - 0.2), 18, "#ffc98a", radius=0.3, name="cove_wash")


def room_sign(coll, glow, label, x0px, level, mat, accent):
    """A small lit sign at the top of a room's back wall, naming the department that works there."""
    z = wz(FLOORS[level][1] + 24)
    key = label.lower().replace(" ", "_")
    glow.box(X(x0px), X(x0px) + 0.08, BACK - 0.06, BACK - 0.02, z - 0.04, z + 0.5, emissive(f"sign_bar_{key}", accent, 5.0))
    text(coll, label, X(x0px) + 0.26, BACK - 0.07, z + 0.42, 0.5, mat["label_text"], spacing=1.12, name=f"room_sign_{key}", face="bold")


def room_rect(zone_id, x0px, x1px, level, name):
    f = FLOORS[level]
    ANCHORS["rooms"][zone_id] = {"x": x0px, "y": f[1], "w": x1px - x0px, "h": f[0] - f[1], "level": level, "name": name}


# ----------------------------------------------------------------------------- the building


def build(colls):
    global SCREENS
    SCREENS = MB("desk_screens") if os.environ.get("AMN_UNREAL_WORKSTATIONS") == "1" else None
    mat = materials()
    back = colls["building_back"]
    front = colls["building_front"]
    shell_c = colls["building_shell"]
    lights = colls["lights_interior"]

    shell = MB("shell")
    rooms = MB("rooms")
    props = MB("props")
    leaves = MB("leaves")
    pots = MB("pots")
    fronts = MB("consoles")
    glow = MB("glow_details")

    # ---------------------------------------------------------------- frame, slabs, roof
    top_z = Z(38)
    shell.box(X(415), X(432), -0.4, BACK + 0.4, -0.35, top_z, mat["stone"])
    shell.box(X(432), X(447), -0.25, BACK + 0.4, -0.35, top_z, mat["frame"])
    shell.box(X(446), X(449), -0.26, -0.25, -0.35, top_z, mat["frame_hi"])
    for lower, upper in ((0, 1), (1, 2), (2, 3), (3, 4)):
        top = fz(upper)
        # The slab's body is drawn with the rooms, below the floor boards. In the shell's own layer
        # render the rooms are invisible, so a body there showed its whole top face and the canvas
        # painted it as a dark band over every floor. The shell keeps only the slab's face.
        rooms.box(X(432), X(1215), -0.14, BACK_G + 0.3, cz(lower), top - 0.06, mat["slab"])
        for x0, x1 in ((432, 517), (1205, 1215)):
            rooms.box(X(x0), X(x1), -0.14, BACK_G + 0.3, top - 0.06, top, mat["slab"])
        shell.box(X(432), X(1215), -0.18, -0.14, cz(lower), top, mat["slab"])
        shell.box(X(447), X(1205), -0.2, -0.18, top - 0.045, top - 0.01, mat["edge_led_slab"])
        mid = (cz(lower) + top) / 2
        shell.box(X(447), X(1205), -0.2, -0.18, mid - 0.015, mid + 0.01, mat["edge_led_warm"])
        shell.box(X(432), X(1215), -0.21, -0.18, cz(lower), cz(lower) + 0.05, mat["frame_hi"])
        if lower >= 1:  # the office floors; the ground floor has its header bars there
            ceiling_cove(shell, lights, lower, mat)
    # roof mass above L4
    # Z(30) is a height, and the edge that shows against the sky is the deck's far one: at y = 2.8
    # it computes to row 16.4, and the live frame turns solid at row 17. The picture's roofline is
    # at row 27 - over columns 700-870 it still reads 35, 52, 88 at row 21 and only goes dark at
    # row 28 - so ten rows of the picture's sky, right across the building's front, were roof.
    # At Z(41) the far edge lands on row 27.4 and the deck's own band, rows 27 to 42, is as deep as
    # the picture's, rows 27 to 39. Everything standing on the deck follows its base below; the
    # tops the picture fixes (the left plant box at row 18, the plant room at row 16) stay.
    shell.box(X(432), X(1215), -0.18, BACK + 0.4, cz(4), Z(41), mat["roof"])
    shell.box(X(432), X(1215), -0.2, -0.18, cz(4), cz(4) + 0.05, mat["frame_hi"])
    # Under L4's ceiling the picture has no lit room behind the line: that row is the soffit of
    # the sign band, a dark eave with a few warm pools under it. Over columns 700-1190 it rises to
    # 111, 74, 46 at row 87 and falls away over rows 83 to 91. The office cove_led burnt a white
    # line there instead - 230, 202, 151 at row 86, over four rows - so it takes its own material,
    # which the live look pass tunes as LEDS["sign_soffit"] without touching L1 to L3, whose lines
    # already sit on the picture's (L2 peaks at 252, 235, 202 against the picture's 246, 238, 213).
    ceiling_cove(shell, lights, 4, mat, line=emissive("sign_soffit", "#ffb070", 0.45))
    # roof railings and plant room
    rail = principled("rail", "#8c95aa", rough=0.3, metal=0.7)
    # The coping on the front of the parapet. It cannot simply follow the deck: a row under
    # Z(41) it would read at rows 43-44, under the sign band's top edge, as a light line the
    # picture has nowhere. Z(38) stands it 0.11 m proud of the deck, which is where a coping
    # belongs, and lands it on rows 39-40 - the lighter row the picture has just over the sign
    # (26, 37, 64 at row 38 against the parapet's 15, 29, 57 above it).
    shell.box(X(432), X(1215), -0.22, -0.18, Z(38) - 0.05, Z(38), rail)
    rail_y = 1.2
    for x0, x1 in ((436, 588), (606, 878)):
        # the railing stands on the deck: with its base on row 41 its 1.02 m spans rows 13 to 41,
        # of which 13 to 27 show against the sky, where the picture's railing shows over rows 11 to 27
        zr = Z(41, rail_y)
        # three rails and a top bar, as the picture's roof railing has; ours showed two
        shell.box(X(x0), X(x1), rail_y, rail_y + 0.05, zr + 0.95, zr + 1.02, rail)
        shell.box(X(x0), X(x1), rail_y, rail_y + 0.05, zr + 0.66, zr + 0.70, rail)
        shell.box(X(x0), X(x1), rail_y, rail_y + 0.05, zr + 0.38, zr + 0.42, rail)
        for xp in range(x0, x1 + 1, 16):
            shell.box(X(xp), X(xp) + 0.05, rail_y, rail_y + 0.05, zr, zr + 1.02, rail)
    # the small plant box on the left of the deck: its base follows the deck, its top stays on
    # row 18, where the picture has it
    shell.box(X(436), X(470), 1.4, 2.4, Z(41, 1.4), Z(18, 1.4), mat["roof"])
    # the plant room's base follows the deck too; it is hidden behind the parapet either way
    zr = Z(41, 2.0)
    # The plant room ran up to row 4, which put a dark wall where the picture has sky over the roof
    # (its rows 15-30 read 19, 22, 35 against 31, 43, 71). It stops at row 16 now.
    plant_top = Z(16, 1.8)
    shell.box(X(880), X(1190), 1.8, 3.2, zr, plant_top, mat["roof"])
    shell.box(X(880), X(1190), 1.78, 1.8, plant_top - 0.05, plant_top, rail)
    shell.box(X(880), X(1190), 1.78, 1.8, zr + 0.3, zr + 0.34, mat["edge_led"])
    for xp in range(884, 1190, 20):
        shell.box(X(xp), X(xp) + 0.04, 1.75, 1.78, plant_top, plant_top + 0.6, rail)
    shell.box(X(880), X(1190), 1.75, 1.78, plant_top + 0.56, plant_top + 0.62, rail)
    # sign band
    sy = -0.45
    shell.box(X(680), X(1205), sy, 0.2, Z(80, sy), Z(40, sy), mat["sign_glass"])
    shell.box(X(680), X(1205), sy - 0.01, sy, Z(80, sy), Z(79, sy), mat["frame_hi"])
    ANCHORS["labels"]["sign"] = {"x": 680, "y": 40, "w": 525, "h": 40}
    logo_mark(shell, X(712), sy - 0.02, Z(46, sy), 0.95, mat["gold"])
    # The type sat low in the band: the name's letters read over rows 58-71 where the picture's
    # read over 52-66, and the mark is already where the picture has it (rows 46-72 in both), so
    # the name alone moves, six rows, which centres it on the mark as the picture's is.
    text(shell_c, "AMN-AI", X(758), sy - 0.03, Z(65, sy), 1.12, mat["gold"], spacing=1.12, name="sign_name", face="bold")
    # bahnschrift's "I" is a single stroke 0.03 m wide, under a pixel in the live frame: the sign
    # read AUTONOMOUS MACH NE NEXUS. The bold face carries the same width at 0.38 (its advances are
    # a little wider) with strokes that survive.
    # and the subtitle five rows, from rows 61-66 to the picture's 56-63
    text(shell_c, "AUTONOMOUS MACHINE NEXUS", X(878), sy - 0.03, Z(61, sy), 0.38, mat["gold_dim"], spacing=1.5, name="sign_sub", face="bold")

    # ---------------------------------------------------------------- lift tower
    build_tower(shell, rooms, glow, lights, shell_c, mat)

    # ---------------------------------------------------------------- floors
    build_l4(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat)
    build_l3(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat)
    build_l2(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat)
    build_l1(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat)
    build_ground(shell, rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat)

    shell.build(shell_c, bevel=0.012)
    rooms.build(back)
    props.build(back, bevel=0.01)
    glow.build(back)
    leaves.build(back, smooth=True)
    pots.build(back, smooth=True)
    fronts.build(front, bevel=0.015)
    if SCREENS is not None:
        SCREENS.build(front, bevel=0.015)
    return ANCHORS


def logo_mark(mb, x, y, z_top, height, m):
    """The AMN-AI 'A' mark: two slanted strokes meeting at the apex, a short bar and pixel blocks."""
    # The mark read as a thin outline where the picture's is a solid one: 27 world pixels wide with
    # 117 of them lit, against the picture's 36 wide with 365 lit, and dimmer with it (a peak of 191
    # against 229 - a stroke under a pixel wide is averaged away before it can be bright). Wider and
    # heavier it spans columns 712-747, where the picture's spans 713-748.
    w = height * 1.30
    t = height * 0.30
    base = z_top - height
    apex = (x + w / 2, z_top)
    for side in (-1, 1):
        x_foot = x + (0 if side < 0 else w)
        pts = []
        if side < 0:
            pts = [(x_foot, y, base), (x_foot + t, y, base), (apex[0] + t * 0.15, y, z_top - t * 0.9), (apex[0] - t * 0.35, y, z_top)]
        else:
            pts = [(x_foot - t, y, base), (x_foot, y, base), (apex[0] + t * 0.35, y, z_top), (apex[0] - t * 0.15, y, z_top - t * 0.9)]
        mb.quad(pts, m)
    mb.box(x + w * 0.62, x + w * 0.74, y - 0.005, y, base + 0.0, base + height * 0.12, m)
    mb.box(x + w * 0.48, x + w * 0.58, y - 0.005, y, base + height * 0.15, base + height * 0.25, m)


def build_tower(shell, rooms, glow, lights, shell_c, mat):
    top = Z(38)
    stone = mat["stone"]
    shell.box(X(1312), X(1340), -0.4, 2.2, -0.35, top, stone)
    shell.box(X(1205), X(1215), -0.25, 2.2, -0.35, top, mat["frame"])
    shell.box(X(1277), X(1283), -0.25, 2.2, -0.35, top, mat["frame"])
    shell.box(X(1307), X(1313), -0.25, 2.2, -0.35, top, mat["frame"])
    # the tower's crown
    shell.box(X(1188), X(1353), -0.7, 2.6, Z(38, -0.7), Z(14, -0.7), principled("crown", "#333744", rough=0.4, metal=0.3))
    shell.box(X(1188), X(1353), -0.72, -0.7, Z(38, -0.7) - 0.04, Z(38, -0.7), mat["edge_led"])
    shell.box(X(1225), X(1300), 0.2, 2.4, Z(38, 0.2), Z(8, 1.0), mat["roof"])
    # floor bands across the tower
    for lower, upper in ((0, 1), (1, 2), (2, 3), (3, 4)):
        # shallow, so the warm shaft shows above each band as in the picture
        shell.box(X(1205), X(1312), -0.24, 0.25, cz(lower) + 0.15, fz(upper) - 0.1, mat["frame"])
    # shaft interior: warm lit back wall, rails, cables
    shaft_back = principled("shaft_back", "#4a3a2c", rough=0.4, metal=0.3)
    rooms.box(X(1215), X(1277), 1.7, 1.9, -0.3, top, shaft_back)
    for lvl in FLOORS:
        lo = fz(lvl) + 0.1
        hi = (fz(lvl + 1) - 0.1) if lvl < 4 else Z(40)
        glow.front_quad(X(1219), X(1273), lo, hi, 1.69, gradient_emission("shaft_section", "#5a4028", "#d09a60", 0.75))
        door_top = lo + min(2.4, (hi - lo) * 0.62)
        for xa, xb in ((1226, 1228), (1264, 1266), (1245, 1247)):
            glow.box(X(xa), X(xb), 1.6, 1.66, lo, door_top, mat["frame_hi"])
        glow.box(X(1226), X(1266), 1.6, 1.66, door_top, door_top + 0.06, mat["frame_hi"])
        glow.box(X(1215), X(1277), 1.6, 1.66, hi - 0.08, hi, mat["frame"])
        glow.box(X(1236), X(1256), 1.2, 1.5, hi - 0.35, hi - 0.3, mat["lamp_bulb"])
        light(lights, "POINT", (X(1246), 1.0, hi - 0.5), 45, "#ffcf92", radius=0.2, name="shaft_light")
    rooms.box(X(1283), X(1307), 1.7, 1.9, -0.3, top, principled("bay_back", "#3a302d", rough=0.5))
    # the narrow bay beside the shaft is a lit stair landing in the picture, not a black slot
    for lvl in FLOORS:
        lo = fz(lvl) + 0.1
        hi = (fz(lvl + 1) - 0.1) if lvl < 4 else Z(40)
        # Tried brighter (0.45 and 0.9) to cover the pale panels that show in this column: they are
        # not the landing, and the tower only drifted from the picture (its region 7.4 -> 10.6 and
        # 15.1). Back to the scene's own 0.2.
        glow.front_quad(X(1285), X(1305), lo, hi, 1.69, gradient_emission("bay_section", "#4a3524", "#b8844f", 0.2))
    strip = emissive("shaft_strip", "#ffd49c", 4.0)
    for xp in (1229, 1246, 1263):
        glow.box(X(xp) - 0.03, X(xp) + 0.03, 1.66, 1.7, -0.2, top - 0.3, strip if xp == 1246 else mat["frame_hi"])
    for lvl, row in ((4, 164), (3, 272), (2, 385), (1, 493), (0, 640)):
        if lvl:
            text(shell_c, f"L{lvl}", X(1284), -0.28, Z(row, -0.28), 0.7, mat["label_text"], name=f"lift_label_{lvl}")
    # lobby lift doors
    rooms.box(X(1224), X(1268), 1.55, 1.68, 0.0, 2.3, mat["metal"])
    glow.box(X(1245.5) - 0.01, X(1245.5) + 0.01, 1.54, 1.55, 0.05, 2.25, mat["black"])
    # Glass skin. The building's own glass (#8fa6c0, roughness 0.04) is a mirror: over the lift tower
    # it threw the dusk sky back at the camera as pale cyan panels, where the picture shows the warm
    # shaft and its cabins through the glass. The tower's own glass is darker and less polished, so
    # what is behind it shows.
    tower_glass = principled("glass_tower", "#5d6c80", rough=0.16, alpha=0.05)
    for x0, x1 in ((1215, 1277), (1283, 1307)):
        shell.front_quad(X(x0), X(x1), -0.3, top - 0.2, -0.26, tower_glass)
    # lift stops, for the canvas: cab floor row of each level at the shaft
    stops = {}
    for lvl in FLOORS:
        col, row = project((X(1246), 1.0, fz(lvl)))
        stops[str(lvl)] = round(row, 1)
    ANCHORS["lift"] = {"shaft": {"x": 1215, "w": 62, "top": 38, "bottom": 655}, "cab_y": 1.0, "stops": stops, "door_x": 1212}


def build_l4(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat):
    lv = 4
    room_rect("director_suite", 517, 1205, lv, "L4 Executive")
    wall = panel_material("wall_l4", "#37543d", "#1d2e22", 0.55, rough=0.6)
    # The picture's floor carries the room's light: L4's lowest rows read 66, 55, 46 there and 125
    # to 160 in front of the director's desk, against our 48, 34, 34 and 45 to 74. A lighter board
    # at a lower roughness takes the spots, as L1's production floor did.
    floor = principled("floor_l4", "#5f4530", rough=0.24)
    room_shell(rooms, 517, 1205, lv, wall, floor)
    label_panel(rooms, shell_c, lv, "L4", "EXECUTIVE", mat)
    f = fz(lv)
    # The picture lights this ceiling in two stretches, not end to end: 530-760 and 877-1055 read
    # about 135, 108, 58 and the gaps at 765-870 and 1060-1195 about 40, 33, 20. One strip the
    # width of the room left our band 75 short on the left and 87 over on the right. The pools sit
    # on the picture's own peaks (541, 637, 717, 889, 989); the old 860 and 1160 both stood in a
    # stretch it keeps dark, and 1160 is what washed the chalkboard corner (ours 98, 85, 63 against
    # its 33, 34, 39). At 145 W the row stops pushing rows 106-134 some 10 over the picture.
    cove(glow, 528, 762, lv, mat["edge_led"])
    cove(glow, 874, 1058, lv, mat["edge_led"])
    downlight_fixtures(glow, (541, 637, 717, 889, 989), lv, mat)
    spot_row(lights, (541, 637, 717, 889, 989), lv, "#ffd29a", 145)
    bookshelf(props, X(532), X(587), 1.85, 2.35, f, f + 1.6, mat["wood_dark"], mat["books"], shelves=4, seed=4)
    plant(leaves, pots, X(560), 2.1, f + 1.6, 0.45, mat["leaf"], mat["pot_white"], pot_h=0.14, pot_r=0.1, n=9, seed=41, style="bush")
    plant(leaves, pots, X(606), 1.7, f, 1.7, mat["leaf"], mat["pot_white"], pot_h=0.4, pot_r=0.17, n=12, seed=42)
    sofa(props, X(622), X(703), 1.55, 2.3, f, principled("leather", "#6b3b22", rough=0.45))
    wall_window(props, 622, 668, 107, 150, mat, view="window_l4")
    frame_picture(props, X(714), wz(127), BACK - 0.02, M(18), M(30), principled("gold_frame", "#b98a3c", rough=0.3, metal=0.8), image_material("art_l4", "art_warm", 1.1))
    plant(leaves, pots, X(757), 1.8, f, 1.9, mat["leaf_dark"], mat["pot_white"], pot_h=0.5, pot_r=0.2, n=14, seed=43)
    top = back_desk(props, 768, 880, lv, mat)
    for cx, scr in ((784, "screen_blue_chart"), (811, "screen_blue"), (838, "screen_blue_chart")):
        monitor(props, X(cx), 2.05, top, M(24), 0.5, mat["mon_frame"], mat[scr])
    screen_anchor("director_monitors", X(772), X(850), top + 0.12, top + 0.62, 2.03, zone="director_suite", desk="desk_director")
    frame_picture(props, X(811), wz(123), BACK - 0.02, M(38), M(34), mat["black"], image_material("art_director", "art_night", 1.0))
    workstation(fronts, props, 811, lv, mat, "ui_blue_chart", "director_suite", "desk_director", side=1)
    seat("desk_director", 811, lv, "front", "director_suite")
    props.box(X(858), X(884), 1.8, 2.2, f + 0.55, f + 0.6, mat["wood_dark"])
    props.box(X(870), X(872), 1.95, 2.05, f, f + 0.55, mat["wood_dark"])
    props.cyl(X(866), 2.0, f + 0.6, f + 0.9, 0.012, mat["metal"])
    props.cyl(X(866), 2.0, f + 0.88, f + 1.05, 0.12, mat["lamp_shade"], seg=16, r_top=0.07)
    # The lamp washed its corner to 155, 141, 88 where the picture keeps it at 85, 85, 60, and the
    # pendant by the door to 160, 147, 101 against 104, 92, 63. Only the wattage changes: the drop
    # stays, because hanging these lower was tried and reverted (they read as heavy dark cones).
    light(lights, "POINT", (X(866), 1.9, f + 0.95), 6, "#ffc98a", radius=0.08, name="desk_lamp")
    pendant(props, lights, 900, lv, 1.1, mat, energy=18)
    door_z0, door_z1 = f, wz(107)
    props.box(X(890), X(932), BACK - 0.08, BACK - 0.02, door_z0, door_z1, mat["frame"])
    props.front_quad(X(892), X(910), door_z0 + 0.05, door_z1 - 0.06, BACK - 0.085, mat["glass_dark"])
    props.front_quad(X(912), X(930), door_z0 + 0.05, door_z1 - 0.06, BACK - 0.085, mat["glass_dark"])
    props.box(X(908), X(909), BACK - 0.1, BACK - 0.085, f + 1.0, f + 1.4, mat["metal"])
    props.box(X(914), X(915), BACK - 0.1, BACK - 0.085, f + 1.0, f + 1.4, mat["metal"])
    props.box(X(941), X(961), 1.95, 2.35, f, f + 0.75, mat["black"])
    wall_window(props, 958, 1010, 107, 150, mat, view="window_l4")
    plant(leaves, pots, X(992), 1.75, f, 1.7, mat["leaf"], mat["pot_white"], pot_h=0.35, pot_r=0.15, n=12, seed=44)
    props.box(X(1010), X(1052), 1.7, 2.2, f + 0.5, f + 0.55, mat["wood"])
    for xp in (1014, 1048):
        props.box(X(xp), X(xp) + 0.05, 1.75, 2.15, f, f + 0.5, mat["wood"])
    plant(leaves, pots, X(1038), 1.95, f + 0.55, 0.5, mat["leaf"], mat["pot_dark"], pot_h=0.18, pot_r=0.09, n=8, seed=45, style="bush")
    # The picture's plank is lit honey (119, 87, 38) and the frames on it are bright warm-mounted
    # prints (121, 96, 53); ours read 58 and 46 short, dark rectangles on a dark plank, the same
    # fault L2's pinned photographs had. These three are landscape, so they stay our own geometry
    # rather than going to the pack as the portrait pictures do.
    props.box(X(1057), X(1128), BACK - 0.25, BACK - 0.02, wz(136), wz(134), mat["wood"])
    shelf_frame = principled("shelf_frame", "#cbbda4", rough=0.45)
    for i, cx in enumerate((1068, 1090, 1112)):
        frame_picture(props, X(cx), wz(126), BACK - 0.1, M(15), M(13), shelf_frame, image_material(f"art_shelf_{i}", f"photo_{i}", 2.0))
    sofa(props, X(1088), X(1128), 1.7, 2.3, f, principled("armchair", "#b08f64", rough=0.55), back_h=0.75, arm=0.12)
    # The picture keeps the ceiling above these two dark (40, 33, 20 over columns 1060-1195) where
    # ours read 127, 116, 73: bare bulbs throwing as much light up as down.
    pendant(props, lights, 1076, lv, 1.0, mat, shade="bulb", energy=10)
    pendant(props, lights, 1116, lv, 0.85, mat, shade="bulb", energy=10)
    board = principled("chalkboard", "#232a26", rough=0.8)
    props.box(X(1135), X(1172), BACK - 0.06, BACK - 0.02, wz(157), wz(100), mat["wood_dark"])
    props.front_quad(X(1137), X(1170), wz(155), wz(102), BACK - 0.065, board)
    text(shell_c, "GOOD\nIDEAS\nRUN\n24/7", X(1140), BACK - 0.07, wz(113), 0.34, emissive("chalk", "#e6e2d4", 2.2), line=1.0, name="chalk_text", face="sign")
    plant(leaves, pots, X(1186), 1.85, f, 1.5, mat["leaf"], mat["pot_white"], pot_h=0.3, pot_r=0.14, n=11, seed=46)


def build_l3(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat):
    lv = 3
    room_rect("research_lab", 517, 862, lv, "L3 Research")
    room_rect("factcheck_room", 868, 1205, lv, "L3 Fact Check")
    wall = principled("wall_l3", "#4b5a88", rough=0.85)
    # The room's open floor reads 43, 44, 64 over rows 268-278 against the picture's 75, 71, 77:
    # its blue board swallowed the light instead of carrying it. The picture's floor there is a
    # neutral grey with a violet hint. (Its bright front lip sits at rows 279-281 and ours at
    # 283-284; that is the slab's projection in build(), shared by every floor, not this board.)
    floor = principled("floor_l3", "#4a4753", rough=0.26)
    room_shell(rooms, 517, 862, lv, wall, floor)
    # Fact Check had its own terracotta walls; in the picture this floor is one blue room from end to
    # end and the brown half read as a different building. The room keeps its sign and its accent.
    room_shell(rooms, 862, 1205, lv, wall, floor)
    # The picture's pinboard crosses this column too (its cork reads 186, 163, 140 at x 861), so
    # the divider stops just under the board rather than cutting it in two.
    rooms.box(X(862), X(868), -0.2, BACK + 0.2, fz(lv), wz(250), mat["frame"])
    label_panel(rooms, shell_c, lv, "L3", "RESEARCH", mat)
    room_sign(shell_c, glow, "RESEARCH", 527, lv, mat, "#60a5fa")
    # At 878 the sign sat on the darkest stretch of the picture's wall (876-918 reads 62, 66, 104
    # there and ours 127, 137, 176). The picture's lit patch on this wall is 908-936.
    room_sign(shell_c, glow, "FACT CHECK", 908, lv, mat, "#fb923c")
    f = fz(lv)
    # Eight fixtures and one 9 m area light in the middle of the floor washed this room flat: its
    # ceiling band reads 99, 103, 159 from x 749 to 861 and then 64, 58, 60 from 941 rightward,
    # where the picture has five clean pools at 565, 733, 921, 1021 and 1133 (red peaks 126, 193,
    # 174, 201, 183) over a ceiling of about 58, 55, 80 between them. The same wash is the columns:
    # +42 blue at 825-888 where it sits, -33 and -35 at 573-636 and 1014-1077 where it never
    # reached. Two smaller fills now stand over those two dark stretches instead of one over the
    # bright one, and they lose the blue-white - the picture's pools read warm (201, 182, 188).
    downlight_fixtures(glow, (565, 733, 921, 1021, 1133), lv, mat)
    spot_row(lights, (565, 733, 921, 1021, 1133), lv, "#fff0e0", 190, cone=58, blend=0.5, tilt=26)
    light(lights, "AREA", (X(690), 0.4, cz(lv) - 0.9), 42.0, "#ecdfd2", radius=5.5, rot=(math.radians(35), 0, 0), name="l3_fill")
    light(lights, "AREA", (X(1035), 0.4, cz(lv) - 0.9), 42.0, "#ecdfd2", radius=5.5, rot=(math.radians(35), 0, 0), name="l3_fill_right")
    plant(leaves, pots, X(530), 1.6, f, 1.55, mat["leaf"], mat["pot_white"], pot_h=0.32, pot_r=0.15, n=12, seed=31)
    # The picture's bookcase reads 86, 71, 79 against our 67, 64, 73: its wood catches the light.
    bookshelf(props, X(537), X(587), 1.85, 2.35, f, f + 1.8, mat["wood"], mat["books"], shelves=5, seed=3)
    wall_window(props, 602, 652, 202, 235, mat, view="window_l3")
    # Under both of this floor's windows the picture runs a lit honey plank: its right counter's
    # top rows read 121, 103, 89 and its left 87, 85, 92, against our 67, 69, 97 and 77, 71, 85.
    counter_top = principled("counter_l3", "#7a5a34", rough=0.4)
    top = back_desk(props, 590, 722, lv, mat, top_mat=counter_top)
    props.box(X(598), X(618), 1.95, 2.3, top, top + 0.55, principled("crt", "#3a3a40", rough=0.5))
    props.front_quad(X(600), X(616), top + 0.12, top + 0.48, 1.945, image_material("crt_screen", "ui_cyan_chart", 0.9))
    plant(leaves, pots, X(628), 2.05, top, 0.35, mat["leaf"], mat["pot_white"], pot_h=0.15, pot_r=0.07, n=7, seed=32, style="bush")
    frame_picture(props, X(682), wz(230), BACK - 0.02, M(20), M(30), mat["black"], image_material("poster_l3a", "art_night", 0.8))
    for cx, scr in ((670, "screen_blue"), (700, "screen_blue_chart")):
        monitor(props, X(cx), 2.05, top, M(24), 0.46, mat["mon_frame"], mat[scr])
    screen_anchor("research_monitors", X(658), X(712), top + 0.12, top + 0.58, 2.03, zone="research_lab", desk="desk_research_1")
    workstation(fronts, props, 672, lv, mat, "ui_blue", "research_lab", "desk_research_1", side=1)
    seat("desk_research_1", 672, lv, "front", "research_lab")
    for xp in (732, 750):
        props.box(X(xp), X(xp + 14), 1.8, 2.3, f, f + 0.95, principled("tower_pc", "#1b1c22", rough=0.4))
        glow.box(X(xp + 4), X(xp + 5), 1.79, 1.8, f + 0.7, f + 0.85, emissive("pc_led_blue", "#60a5fa", 8.0))
    cork = principled("cork", "#8a6a44", rough=0.9)
    # The picture's board runs 773 to 875: its frame reads 149, 118, 83 at 774 and the wall behind
    # it 38, 48, 78 at 771, and by 876 it is gone (51, 48, 62). Ours stood 28 columns left of that,
    # so 745-773 read 108, 88, 40 over the wall and 850-878 read 62, 30 under the cork.
    props.box(X(773), X(878), BACK - 0.06, BACK - 0.02, wz(247), wz(207), mat["wood_dark"])
    props.front_quad(X(776), X(875), wz(245), wz(209), BACK - 0.065, cork)
    rng = random.Random(7)
    paper = emissive("paper", "#efe9dc", 0.6)
    pin_ink = principled("pin_ink", "#3b4a66", rough=0.6)
    for r in range(2):
        for c in range(3):
            x0 = 783 + c * 31 + rng.uniform(-2, 2)
            z1 = wz(213 + r * 17)
            props.front_quad(X(x0), X(x0 + 22), z1 - M(12), z1, BACK - 0.07, paper)
            # the notes carry lines of writing, as the picture's pinboard does
            for li in range(3):
                zl = z1 - M(3) - li * M(3)
                props.box(X(x0 + 3), X(x0 + 3 + rng.uniform(10, 17)), BACK - 0.076, BACK - 0.072, zl - 0.02, zl, pin_ink)
    top_r = back_desk(props, 770, 850, lv, mat, top_mat=counter_top)
    props.box(X(790), X(830), 1.9, 2.25, top_r, top_r + 0.18, mat["white"])
    top2 = back_desk(props, 880, 975, lv, mat)
    for cx, scr in ((905, "screen_cyan"), (933, "screen_cyan_chart")):
        monitor(props, X(cx), 2.05, top2, M(24), 0.46, mat["mon_frame"], mat[scr])
    screen_anchor("factcheck_monitors", X(893), X(945), top2 + 0.12, top2 + 0.58, 2.03, zone="factcheck_room", desk="desk_research_2")
    frame_picture(props, X(936), wz(230), BACK - 0.02, M(24), M(30), mat["black"], image_material("poster_l3b", "art_teal", 0.8))
    workstation(fronts, props, 926, lv, mat, "ui_cyan_chart", "factcheck_room", "desk_research_2", side=-1)
    seat("desk_research_2", 926, lv, "front", "factcheck_room")
    # The picture's board is a dim warm grey covered edge to edge in diagram scribble: it reads
    # 163, 145, 139 against our clean sheet's 222, 220, 220.
    wb = principled("whiteboard", "#bdb8ac", rough=0.5)
    props.box(X(970), X(1002), BACK - 0.06, BACK - 0.02, wz(252), wz(208), mat["metal"])
    props.front_quad(X(972), X(1000), wz(250), wz(210), BACK - 0.065, wb)
    ink = principled("ink", "#394150", rough=0.6)
    # nine lines of working down the whole board, as the picture's has, not six in its top corner
    for i in range(9):
        z = wz(214 + i * 4.0)
        props.box(X(975), X(975 + 10 + (i * 9) % 20), BACK - 0.07, BACK - 0.066, z - 0.03, z, ink)
    top3 = back_desk(props, 997, 1102, lv, mat, top_mat=counter_top)
    rng = random.Random(9)
    # The picture stands a row of warm amber and cream jars on this plank, taller than ours and
    # lit by it; ours were a cooler green, amber and white set and read 14, 10 short.
    bottle_mats = [principled("bottle_g", "#a8c98a", rough=0.1, alpha=0.7), principled("bottle_a", "#e8bc72", rough=0.1, alpha=0.8), principled("bottle_c", "#e6dcc4", rough=0.15)]
    for i in range(9):
        cx = X(1010 + i * 10 + rng.uniform(-2, 2))
        h = rng.uniform(0.24, 0.50)
        props.cyl(cx, 2.05, top3, top3 + h, 0.045, rng.choice(bottle_mats), seg=10)
    wall_window(props, 1050, 1098, 202, 235, mat, view="window_l3")
    plant(leaves, pots, X(1124), 1.7, f, 1.6, mat["leaf"], mat["pot_white"], pot_h=0.35, pot_r=0.16, n=13, seed=33)
    # The picture's fridge is a narrow unit half behind its plants and reads 81, 74, 62; ours was a
    # bright white slab at 124, 114, 103 and carried this whole end 13 over the picture.
    props.box(X(1158), X(1194), 1.8, 2.35, f, f + 1.55, principled("fridge", "#9a968c", rough=0.3))
    props.box(X(1160), X(1161), 1.79, 1.8, f + 0.8, f + 1.3, mat["metal"])
    plant(leaves, pots, X(1180), 1.3, f, 1.25, mat["leaf_dark"], mat["pot_white"], pot_h=0.3, pot_r=0.14, n=11, seed=34)
    props.box(X(1140), X(1158), 2.0, 2.35, f, f + 0.6, principled("crate", "#a08058", rough=0.7))


def build_l2(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat):
    lv = 2
    room_rect("script_room", 517, 862, lv, "L2 Content")
    room_rect("publish_desk", 868, 1205, lv, "L2 Distribution")
    wall = panel_material("wall_l2", "#5e4a2c", "#2e2210", 0.42, rough=0.45)
    floor = principled("floor_l2", "#3a2a1c", rough=0.3)
    room_shell(rooms, 517, 862, lv, wall, floor)
    # Distribution had green walls; the picture's L2 is warm from end to end, wood shelves and a
    # leather sofa against the same panelling as Content. The room keeps its sign and its accent.
    room_shell(rooms, 862, 1205, lv, wall, floor)
    rooms.box(X(862), X(868), -0.2, BACK + 0.2, fz(lv), cz(lv), mat["frame"])
    label_panel(rooms, shell_c, lv, "L2", "CONTENT", mat)
    room_sign(shell_c, glow, "CONTENT", 527, lv, mat, "#fbbf24")
    room_sign(shell_c, glow, "DISTRIBUTION", 878, lv, mat, "#2dd4bf")
    f = fz(lv)
    cove(glow, 525, 855, lv, mat["edge_led"], drop=0.42)
    cove(glow, 875, 1195, lv, mat["edge_led"], drop=0.42)
    # clear of the CONTENT and DISTRIBUTION signs at the top of each room. The left end (columns 517
    # to 600) had no lamp of its own and read 29 short of the picture there.
    for xp in (590, 660, 740, 820, 1040, 1110, 1180):
        # Hung lower (drop 1.0, to sit a third of the way into the room as the picture's seem to):
        # at the plate's scale the shade then covers the wall behind it and reads as a heavy dark
        # cone, and L2's region went 6.7 -> 7.4 (mean 4.4 -> 4.6). They stay under the ceiling.
        pendant(props, lights, xp, lv, 0.62, mat, energy=26, color="#ffd9a8")
    light(lights, "AREA", (X(860), 0.6, cz(lv) - 0.8), 60.0, "#ffc27a", radius=8.0, rot=(math.radians(35), 0, 0), name="l2_fill")
    plant(leaves, pots, X(538), 1.6, f, 1.5, mat["leaf"], mat["pot_white"], pot_h=0.35, pot_r=0.15, n=12, seed=21)
    frame_picture(props, X(563), wz(333), BACK - 0.02, M(22), M(24), mat["white"], image_material("photo_l2a", "art_warm", 0.9))
    cork = principled("cork_l2", "#8b6a45", rough=0.9)
    props.box(X(597), X(722), BACK - 0.06, BACK - 0.02, wz(362), wz(312), mat["wood_dark"])
    props.front_quad(X(600), X(719), wz(360), wz(314), BACK - 0.065, cork)
    # The picture's board is covered in big prints in white mounts, bright against the cork. Ours
    # were seven photographs 17 px wide at emission 0.9, and at the plate's scale they read as small
    # dark squares with no mount at all. Eight of them now, 18 to 28 px wide, in a mount twice as
    # wide, and the prints themselves three times brighter.
    # Half the prints are the dusk snapshots, half the brighter plates (a warm painting, a daylight
    # city, a teal one): eight of the same dark snapshot read as a grid of dark squares where the
    # picture's board carries photographs you can make out.
    for i, (px, pr, pw, ph, art) in enumerate((
        (618, 325, 22, 17, "photo_0"), (648, 324, 20, 16, "art_warm"),
        (676, 327, 18, 14, "photo_1"), (702, 324, 16, 13, "window_city_day"),
        (616, 349, 20, 16, "photo_2"), (646, 350, 18, 14, "art_teal"),
        (674, 348, 22, 17, "photo_3"), (702, 351, 16, 13, "art_night"),
    )):
        frame_picture(props, X(px), wz(pr), BACK - 0.07, M(pw), M(ph), mat["white"],
                      image_material(f"cork_photo_{i}", art, 1.6), border=0.04)
    # A long work table under the board, as in the picture, where ours had two thin metal rails at
    # hip height: the room's lower rows read 15 to 20 short of the picture's over that stretch.
    table_top = f + 0.74
    props.box(X(556), X(722), 1.02, 1.58, table_top - 0.06, table_top, mat["desk_top"])
    props.box(X(556), X(722), 1.04, 1.56, table_top - 0.07, table_top - 0.06, mat["metal"])
    for xl in (560, 634, 638, 716):
        props.box(X(xl), X(xl) + 0.06, 1.1, 1.5, f, table_top - 0.06, mat["desk"])
    props.box(X(560), X(722), 1.1, 1.5, f + 0.2, f + 0.24, mat["desk"])
    # what stands on it: a printer, two stacks of paper, archive boxes and a mug
    paper_l2 = emissive("paper_l2", "#efe9dc", 0.45)
    props.box(X(568), X(604), 1.1, 1.5, table_top, table_top + 0.3, principled("printer", "#c9c6bf", rough=0.5))
    props.box(X(572), X(600), 1.08, 1.1, table_top + 0.06, table_top + 0.1, paper_l2)
    for xp, w in ((614, 22), (648, 18)):
        props.box(X(xp), X(xp + w), 1.15, 1.45, table_top, table_top + 0.07, paper_l2)
    for xp in (672, 692):
        props.box(X(xp), X(xp + 16), 1.12, 1.48, table_top, table_top + 0.26, principled("archive_box", "#8a6b45", rough=0.75))
        props.box(X(xp + 3), X(xp + 13), 1.11, 1.12, table_top + 0.1, table_top + 0.16, paper_l2)
    props.cyl(X(710), 1.3, table_top, table_top + 0.1, 0.045, mat["white"], seg=12)
    for xp, w in ((566, 26), (600, 20), (660, 30)):
        props.box(X(xp), X(xp + w), 1.12, 1.48, f + 0.24, f + 0.5, principled("under_box", "#3a3a42", rough=0.6))
    top = back_desk(props, 700, 850, lv, mat)
    for cx, tex in ((784, "ui_script"), (826, "ui_blue")):
        monitor(props, X(cx), 2.05, top, M(40), 0.72, mat["mon_frame"], image_material(f"script_{tex}", tex, 1.5))
    screen_anchor("script_monitors", X(764), X(846), top + 0.12, top + 0.84, 2.03, zone="script_room", desk="desk_script")
    for sx in (756, 836):
        props.box(X(sx), X(sx + 9), 1.95, 2.25, top, top + 0.42, mat["black"])
        glow.box(X(sx + 3), X(sx + 6), 1.94, 1.95, top + 0.28, top + 0.36, emissive("spk_led", "#93c5fd", 5.0))
    props.box(X(776), X(836), BACK - 0.06, BACK - 0.02, wz(330), wz(301), mat["mon_frame"])
    props.front_quad(X(778), X(834), wz(328), wz(303), BACK - 0.065, image_material("script_tv", "art_night", 0.9))
    plant(leaves, pots, X(716), 2.05, top, 0.4, mat["leaf"], mat["pot_white"], pot_h=0.16, pot_r=0.08, n=8, seed=22, style="bush")
    workstation(fronts, props, 804, lv, mat, "ui_script", "script_room", "desk_script", side=1)
    seat("desk_script", 804, lv, "front", "script_room")
    # Distribution: Vera's desk and the release radar on the wall above the sofa
    workstation(fronts, props, 1000, lv, mat, "ui_radar", "publish_desk", "desk_publish", side=1)
    seat("desk_publish", 1000, lv, "front", "publish_desk")
    props.box(X(1100), X(1142), BACK - 0.08, BACK - 0.02, wz(350), wz(318), mat["mon_frame"])
    props.front_quad(X(1103), X(1139), wz(348), wz(320), BACK - 0.085, image_material("radar", "ui_radar", 1.5))
    screen_anchor("publish_radar", X(1103), X(1139), wz(348), wz(320), BACK - 0.085, zone="publish_desk", desk="desk_publish")
    frame_picture(props, X(898), wz(336), BACK - 0.02, M(23), M(32), mat["black"], image_material("art_l2b", "art_teal", 0.8))
    plant(leaves, pots, X(928), 1.8, f, 1.45, mat["leaf"], mat["pot_white"], pot_h=0.35, pot_r=0.15, n=11, seed=23)
    wall_window(props, 940, 990, 320, 362, mat)
    bookshelf(props, X(1015), X(1057), 1.85, 2.35, f, f + 1.75, mat["wood"], mat["books"], shelves=5, seed=12)
    bookshelf(props, X(1057), X(1100), 1.85, 2.35, f, f + 1.75, mat["wood"], mat["books"], shelves=5, seed=13)
    props.box(X(1070), X(1082), 2.0, 2.3, f + 1.75, f + 2.0, principled("vase", "#b8b0a0", rough=0.4))
    # brown leather, like the picture's sofa under the shelves (it was a red one)
    sofa(props, X(1096), X(1137), 1.6, 2.25, f, principled("leather", "#6b3b22", rough=0.45), back_h=0.72, arm=0.1)
    props.cyl(X(1148), 2.0, f, f + 0.03, 0.16, mat["black"])
    props.cyl(X(1148), 2.0, f, f + 1.75, 0.018, mat["metal"])
    props.cyl(X(1148), 2.0, f + 1.62, f + 1.98, 0.2, mat["lamp_shade"], seg=18, r_top=0.15)
    light(lights, "POINT", (X(1148), 1.9, f + 1.72), 26, "#ffc98a", radius=0.15, name="floor_lamp")
    # A backlit onyx column in the picture: dark stone with a warm glow through it. Ours was a flat
    # cream panel at emission 1.3, the brightest thing on the floor (its columns read 140, 111, 75
    # against the picture's 101, 72, 45).
    props.box(X(1170), X(1190), 2.0, 2.3, f, f + 2.2, principled("onyx", "#3a2c1e", rough=0.45, emit="#c89a5a", strength=0.35))
    plant(leaves, pots, X(1186), 1.3, f, 0.6, mat["leaf"], mat["pot_white"], pot_h=0.28, pot_r=0.13, n=10, seed=24)


def build_l1(rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat):
    lv = 1
    f = fz(lv)
    room_rect("audio_booth", 517, 862, lv, "L1 Production - Audio")
    room_rect("video_studio", 867, 1205, lv, "L1 Production - Render")
    # The picture's production floor is a deep blue-violet; ours read redder and paler (65, 51, 70
    # against 52, 40, 77 over the left half), which is the brick's own colour, not its light.
    # Tried deeper still (#34205f): the region went 9.0 -> 9.6, so it stays at this violet.
    brick = brick_material("wall_l1_audio", "#3f2b74", "#352363", "#1b1235", brick_w=0.36, row_h=0.14, rough=0.85, bump=0.3)
    # The picture's production floor has a polished floor that carries the room's purple; ours read
    # 30 darker than it over the room's lowest rows.
    floor = principled("floor_l1", "#2c2542", rough=0.22)
    room_shell(rooms, 517, 862, lv, brick, floor)
    room_shell(rooms, 862, 1205, lv, panel_material("wall_l1_render", "#304a5e", "#1c2b38", 1.1, rough=0.6), floor)
    label_panel(rooms, shell_c, lv, "L1", "PRODUCTION", mat, accent="#b26bff")
    rooms.box(X(862), X(868), -0.2, BACK + 0.2, f, cz(lv), mat["frame"])
    purple = "#b56cff"
    downlight_fixtures(glow, (566, 700, 812), lv, mat)
    spot_row(lights, (566, 700, 812), lv, purple, 150, cone=76, blend=0.65, tilt=22)
    neon = emissive("neon_purple", "#e7a6ff", 14.0)
    glow.box(X(548), X(551), BACK - 0.08, BACK - 0.03, wz(476), wz(425), neon)
    glow.box(X(548), X(556), BACK - 0.08, BACK - 0.03, wz(428), wz(425), neon)
    text(shell_c, "PIXELS\nPROCESS\nPOSSIBILITIES", X(560), BACK - 0.06, wz(438), 0.4, neon, spacing=1.1, line=1.0, name="neon_l1", face="sign")
    light(lights, "POINT", (X(590), BACK - 0.6, wz(450)), 30, "#d88cff", radius=0.4, name="neon_glow")
    glow.box(X(529), X(537), 1.2, 1.5, f, f + 0.32, emissive("cube_magenta", "#ff5cc8", 6.0))
    light(lights, "POINT", (X(533), 1.0, f + 0.25), 10, "#ff5cc8", radius=0.2, name="cube_glow")
    plant(leaves, pots, X(548), 1.65, f, 1.5, mat["leaf"], mat["pot_white"], pot_h=0.35, pot_r=0.15, n=12, seed=11)
    sofa(props, X(568), X(612), 1.7, 2.3, f, principled("sofa_purple", "#52307a", rough=0.6), back_h=0.72, arm=0.1)
    top = back_desk(props, 628, 722, lv, mat)
    for cx in (655, 694):
        monitor(props, X(cx), 2.05, top, M(26), 0.46, mat["mon_frame"], image_material("daw", "ui_daw", 1.6))
    screen_anchor("audio_monitors", X(641), X(708), top + 0.12, top + 0.58, 2.03, zone="audio_booth", desk="desk_audio")
    workstation(fronts, props, 668, lv, mat, "ui_daw", "audio_booth", "desk_audio", side=1)
    seat("desk_audio", 668, lv, "front", "audio_booth")
    # boom microphone on the desk, pointing at the seat
    ct = f + 0.75
    fronts.cyl(X(648), 0.6, ct, ct + 0.35, 0.015, mat["black"])
    fronts.box(X(648), X(662), 0.6, 0.62, ct + 0.34, ct + 0.36, mat["black"])
    fronts.cyl(X(663), 0.62, ct + 0.22, ct + 0.36, 0.05, principled("mic", "#2a2a2e", rough=0.3, metal=0.6), seg=12)
    props.box(X(704), X(707), 2.0, 2.1, top, wz(438), mat["black"])
    glow.box(X(703), X(708), 1.98, 2.0, wz(444), wz(438), emissive("stand_light", "#ffe3f5", 6.0))
    props.box(X(706), X(738), BACK - 0.08, BACK - 0.02, wz(476), wz(444), mat["mon_frame"])
    props.front_quad(X(708), X(736), wz(474), wz(446), BACK - 0.085, image_material("waveform", "ui_waveform", 1.6))
    screen_anchor("audio_waveform", X(708), X(736), wz(474), wz(446), BACK - 0.085, zone="audio_booth")
    plant(leaves, pots, X(752), 1.7, f, 1.35, mat["leaf"], emissive("pot_pink", "#ff79c6", 2.0), pot_h=0.32, pot_r=0.14, n=10, seed=12)
    props.box(X(770), X(812), BACK - 0.1, BACK - 0.02, f, wz(420), mat["black"])
    props.front_quad(X(773), X(809), f + 0.05, wz(424), BACK - 0.105, principled("door_panel", "#1d1b24", rough=0.35, metal=0.3))
    glow.box(X(786), X(796), BACK - 0.11, BACK - 0.105, wz(452), wz(446), emissive("door_sign", "#f5f5f5", 3.0))
    slat = principled("slat", "#241c30", rough=0.8)
    for i in range(6):
        xs = 822 + i * 5.2
        props.box(X(xs), X(xs + 3.4), BACK - 0.12, BACK - 0.02, wz(496), wz(424), slat)
    # render bay
    # the render bay reads 10 to 22 darker than the picture's over its columns
    spot_row(lights, (930, 1040, 1150), lv, "#cfd8ff", 130, cone=74, blend=0.65, tilt=22)
    downlight_fixtures(glow, (930, 1040, 1150), lv, mat)
    props.box(X(876), X(943), BACK - 0.1, BACK - 0.02, wz(484), wz(418), principled("render_frame", "#0d0f15", rough=0.3))
    # The render bay's panel: in the picture a lit blue screen, the brightest thing on this floor,
    # where ours read as a black rectangle (emissive #0c1a2c at 1.0 is all but unlit). It carries its
    # own name and nothing else - what the bay is doing at the time is the web canvas's to draw from
    # the studio's state, and a number baked in here would be a made-up one.
    props.front_quad(X(879), X(940), wz(481), wz(421), BACK - 0.105, principled("render_display", "#08182c", rough=0.12, emit="#123a63", strength=1.3))
    text(shell_c, "RENDER BAY", X(886), BACK - 0.11, wz(452), 0.34, emissive("render_label", "#bfe2ff", 3.0), name="render_label", face="sign")
    glow.box(X(886), X(933), BACK - 0.115, BACK - 0.11, wz(440), wz(438), emissive("render_rule", "#38bdf8", 4.0))
    screen_anchor("render_display", X(879), X(940), wz(481), wz(421), BACK - 0.105, zone="video_studio", kind="render_status")
    wall_window(props, 957, 991, 422, 462, mat)
    top = back_desk(props, 972, 1075, lv, mat)
    for cx, rz in ((1000, 0.25), (1023, 0.0), (1046, -0.25)):
        monitor(props, X(cx), 2.05, top, M(22), 0.44, mat["mon_frame"], image_material("timeline_small", "ui_timeline", 1.5), rz=rz)
    screen_anchor("video_monitors", X(988), X(1058), top + 0.12, top + 0.56, 2.03, zone="video_studio", desk="desk_video")
    props.box(X(1062), X(1072), 1.9, 2.3, top, top + 0.55, principled("pc_glass", "#101218", rough=0.2))
    glow.box(X(1063), X(1071), 1.89, 1.9, top + 0.08, top + 0.48, emissive("rgb", "#38bdf8", 4.0))
    workstation(fronts, props, 1022, lv, mat, "ui_timeline", "video_studio", "desk_video", side=-1)
    seat("desk_video", 1022, lv, "front", "video_studio")
    props.box(X(1072), X(1102), BACK - 0.08, BACK - 0.02, wz(464), wz(436), mat["mon_frame"])
    props.front_quad(X(1074), X(1100), wz(462), wz(438), BACK - 0.085, image_material("timeline", "ui_timeline", 1.4))
    plant(leaves, pots, X(1094), 1.5, f, 1.25, mat["leaf"], mat["pot_white"], pot_h=0.3, pot_r=0.13, n=10, seed=13)
    props.cyl(X(1116), 2.0, f, f + 1.8, 0.018, mat["metal"])
    props.box(X(1108), X(1124), 1.95, 2.05, f + 1.8, f + 1.95, mat["lamp_shade"])
    light(lights, "POINT", (X(1116), 1.9, f + 1.75), 22, "#ffd49a", radius=0.12, name="render_lamp")
    props.box(X(1135), X(1181), 1.8, 2.35, f, f + 1.7, principled("rack", "#14161c", rough=0.35, metal=0.3))
    rack_front(props, glow, X(1138), X(1178), f + 0.08, f + 1.62, 1.79, seed=1138)


def build_ground(shell, rooms, props, leaves, pots, fronts, glow, lights, back, shell_c, mat):
    lv = 0
    f, c = 0.0, cz(0)
    # columns between ground rooms and the ground frame
    for x0, x1 in ((447, 455), (637, 645), (885, 897), (1032, 1040), (1197, 1205)):
        shell.box(X(x0), X(x1), -0.25, BACK_G, -0.3, c, mat["frame"])
    shell.box(X(432), X(1215), -0.28, 0.4, -0.35, 0.0, principled("plinth", "#4b4448", rough=0.6))
    shell.box(X(415), X(1340), -0.3, -0.28, -0.12, -0.08, mat["edge_led"])
    # header bars
    header = principled("header_bar", "#191c27", rough=0.4)
    for zone, x0, x1, label in (("server_corner", 455, 637, "S1   INFRA"), ("treasury", 897, 1032, "S2   TREASURY"), ("ai_space", 1040, 1197, "S3   AI SPACE")):
        shell.box(X(x0), X(x1), -0.22, 0.1, Z(541), c, header)
        shell.box(X(x0), X(x1), -0.23, -0.22, Z(541), Z(540), mat["frame_hi"])
        text(shell_c, label, X(x0 + 8), -0.24, Z(537, -0.24), 0.52, mat["label_text"], name=f"header_{zone}")
    shell.box(X(645), X(885), -0.22, 0.1, Z(532), c, header)
    for xp in (700, 760, 790, 845):
        shell.box(X(xp), X(xp + 2), -0.2, -0.12, 0.0, Z(532), mat["frame"])
    # ---------------- S1 INFRA
    room_rect("server_corner", 455, 637, 0, "S1 Infra")
    rooms.box(X(455), X(637), BACK_G, BACK_G + 0.2, f, c, principled("infra_wall", "#16202a", rough=0.3, metal=0.2))
    rooms.box(X(455), X(637), -0.1, BACK_G, -0.05, 0.0, principled("infra_floor", "#141820", rough=0.2))
    grid = emissive("infra_grid", "#2dd4bf", 0.6)
    for zr in (560, 600):
        glow.box(X(458), X(634), BACK_G - 0.03, BACK_G, Z(zr, BACK_G), Z(zr, BACK_G) + 0.02, grid)
    for xp in range(470, 630, 30):
        glow.box(X(xp), X(xp) + 0.02, BACK_G - 0.03, BACK_G, 0.2, c - 0.6, grid)
    # The picture's racks stand as cabinets with their own edges and tops, on a floor you can see;
    # ours were near black (#101318) against a dark wall and read as flat LED panels. A lighter body
    # and a pale top rail give each one its shape without lighting the whole room cyan (the infra
    # fill at 1.8 did that: the ground floor's region 4.2 -> 8.2).
    rack_body = principled("rack_body", "#1e232d", rough=0.4, metal=0.35)
    rack_edge = principled("rack_edge", "#555d6b", rough=0.35, metal=0.5)
    for x0, x1 in ((466, 492), (500, 527), (556, 583), (591, 619)):
        props.box(X(x0), X(x1), 1.2, 2.2, f, 2.62, rack_body)
        props.box(X(x0) - 0.02, X(x1) + 0.02, 1.16, 2.24, 2.62, 2.68, rack_edge)
        props.box(X(x0) - 0.02, X(x0), 1.16, 2.2, f, 2.62, rack_edge)
        props.box(X(x1), X(x1) + 0.02, 1.16, 2.2, f, 2.62, rack_edge)
        rack_front(props, glow, X(x0 + 2), X(x1 - 2), 0.12, 2.5, 1.195, seed=x0)
    ANCHORS["displays"]["server_racks"] = {"rects": [px_rect(X(a), X(b), 0.12, 2.5, 1.19) for a, b in ((466, 492), (500, 527), (556, 583), (591, 619))], "zone": "server_corner"}
    for xp in (500, 590):
        glow.box(X(xp - 20), X(xp + 20), 1.0, 1.3, c - 0.62, c - 0.58, emissive("infra_bar", "#a5f3fc", 5.0))
    # The infra room read teal against the picture (12 short of red, 9 over on blue across its
    # columns): its glass was tinted #5fa7b0 and its fill was almost pure cyan.
    light(lights, "AREA", (X(546), 1.4, c - 0.7), 90, "#bcd9e2", radius=4.0, rot=(math.radians(20), 0, 0), name="infra_fill")
    for x0, x1 in ((455, 546), (546, 637)):
        shell.front_quad(X(x0), X(x1), 0.0, c, -0.2, principled("infra_glass", "#93a8bd", rough=0.05, alpha=0.08))
    shell.box(X(545), X(547), -0.22, -0.18, 0.0, c, mat["frame"])
    shell.box(X(455), X(637), -0.22, -0.18, Z(562), Z(560), mat["frame"])
    # ---------------- LOBBY
    room_rect("lobby", 645, 885, 0, "Lobby")
    lobby_floor = principled("lobby_floor", "#8a6b45", rough=0.12, coat=0.4)
    rooms.box(X(645), X(885), -0.1, BACK_G, -0.05, 0.0, lobby_floor)
    warm_wall = panel_material("lobby_side", "#6a5030", "#3a2a18", 0.6, rough=0.4)
    rooms.box(X(645), X(885), BACK_G, BACK_G + 0.2, f, c, warm_wall)
    feature = principled("feature_wall", "#403b3a", rough=0.55)
    rooms.box(X(713), X(782), BACK_G - 0.35, BACK_G, f, Z(527, BACK_G - 0.35), feature)
    fy = BACK_G - 0.36
    logo_mark(glow, X(734), fy - 0.005, Z(546, fy), 0.95, emissive("lobby_logo", "#f1e7d4", 4.0))
    text(shell_c, "AMN-AI", X(747.5), fy - 0.01, Z(588, fy), 0.62, emissive("lobby_name", "#efe6d6", 3.0), align="CENTER", spacing=1.06, name="lobby_name", face="bold")
    text(shell_c, "HUMAN CREATIVITY\n&\nMACHINE CAPACITY", X(747.5), fy - 0.01, Z(606, fy), 0.22, emissive("lobby_tag", "#d4ccbc", 2.0), align="CENTER", line=1.15, name="lobby_tag")
    light(lights, "SPOT", (X(747), 1.0, c - 0.4), 220, "#ffd7a0", radius=0.1, cone=55, blend=0.5, rot=(math.radians(30), 0, 0), name="feature_spot")
    light(lights, "AREA", (X(690), 1.6, c - 0.3), 260, "#ffcf8a", radius=2.0, name="lobby_fill_l")
    light(lights, "AREA", (X(840), 1.6, c - 0.3), 260, "#ffcf8a", radius=2.0, name="lobby_fill_r")
    light(lights, "AREA", (X(765), -0.6, 2.6), 80, "#ffc27a", radius=3.0, rot=(math.radians(-25), 0, 0), name="lobby_spill")
    for xp in (668, 720, 776, 830):
        glow.box(X(xp) - 0.12, X(xp) + 0.12, 1.0, 1.2, Z(533) - 0.05, Z(533), mat["lamp_bulb"])
    plant(leaves, pots, X(668), 2.5, f, 2.1, mat["leaf"], mat["pot_dark"], pot_h=0.55, pot_r=0.25, n=16, seed=51)
    sofa(props, X(686), X(712), 2.0, 2.7, f, principled("lobby_chair", "#8c8c89", rough=0.7), back_h=0.8, arm=0.1)
    props.box(X(720), X(738), 1.7, 2.1, 0.0, 0.38, mat["wood_dark"])
    plant(leaves, pots, X(812), 2.4, f, 1.7, mat["leaf_dark"], mat["pot_dark"], pot_h=0.5, pot_r=0.22, n=14, seed=52)
    step_mat = principled("stair_wood", "#a8773f", rough=0.45)
    nose = emissive("stair_nose", "#ffcf8a", 3.0)
    steps = 13
    x_start, x_end = 792, 880
    for i in range(steps):
        x0 = X(x_start + (x_end - x_start) * i / steps)
        z = (i + 1) * c / steps
        props.box(x0, X(x_end), 1.7, 2.8, z - 0.12, z, step_mat)
        glow.box(x0, x0 + 0.06, 1.69, 2.8, z - 0.03, z, nose)
    props.box(X(x_start), X(x_end), 2.8, 2.9, 0.0, c, principled("stair_stringer", "#2a2522", rough=0.5))
    for i in range(steps + 1):
        xr = X(x_start + (x_end - x_start) * i / steps)
        zr = i * c / steps
        props.box(xr, xr + 0.025, 1.6, 1.63, zr, zr + 0.95, mat["metal"])
    rail = MB("rail")
    x_a, x_b = X(x_start), X(x_end)
    rail.quad([(x_a, 1.58, 0.95), (x_b, 1.58, c + 0.95), (x_b, 1.58, c + 1.0), (x_a, 1.58, 1.0)], mat["metal"])
    rail.quad([(x_a, 1.6, 0.05), (x_b, 1.6, c + 0.05), (x_b, 1.6, c + 0.95), (x_a, 1.6, 0.95)], mat["glass"])
    rail.build(back)
    pendant(props, lights, 868, 0, 1.2, mat, shade="bulb", energy=30)
    for x0, x1 in ((647, 700), (702, 760), (762, 790), (792, 845), (847, 884)):
        shell.front_quad(X(x0), X(x1), 0.0, Z(532), -0.16, mat["glass"])
    # ---------------- S2 TREASURY (Nadia's office; Distribution has its own room on L2)
    room_rect("accounting_office", 897, 1032, 0, "S2 Treasury")
    # The picture's S2 is a slate room with warm accents, like S1 and S3 beside it; ours was a red one,
    # the only shopfront whose colour the picture does not have.
    rooms.box(X(897), X(1032), BACK_G, BACK_G + 0.2, f, c, principled("ops_wall", "#3c4655", rough=0.6))
    rooms.box(X(897), X(1032), -0.1, BACK_G, -0.05, 0.0, principled("ops_floor", "#2e3540", rough=0.25))
    props.box(X(945), X(1002), BACK_G - 0.4, BACK_G, Z(566, BACK_G - 0.4), Z(563, BACK_G - 0.4), mat["wood"])
    rng = random.Random(21)
    for i in range(5):
        xb = 948 + i * 10
        props.box(X(xb), X(xb + 6), BACK_G - 0.35, BACK_G - 0.1, Z(563, BACK_G - 0.4), Z(563, BACK_G - 0.4) + rng.uniform(0.2, 0.45), rng.choice(mat["books"]))
    light(lights, "POINT", (X(990), BACK_G - 0.5, Z(556, BACK_G - 0.5)), 14, "#ffcf8a", radius=0.1, name="ops_shelf_lamp")
    cab = principled("cabinet", "#2b2b30", rough=0.4, metal=0.3)
    line = emissive("cabinet_line", "#ffd49a", 2.0)
    props.box(X(902), X(972), BACK_G - 0.6, BACK_G, 0.0, Z(574, BACK_G - 0.6) - 0.0, cab)
    # a wall of drawers: five rows of four, each with its own front, gap and lit label, where this was
    # four lines crossed by three
    drawer = principled("drawer_front", "#39404c", rough=0.45, metal=0.2)
    label = emissive("drawer_label", "#ffcf8a", 0.7)
    top_z = Z(574, BACK_G - 0.6)
    rows, cols = 5, 4
    height = (top_z - 0.15) / rows
    width = (X(970) - X(904)) / cols
    for r in range(rows):
        z0 = 0.12 + r * height
        for cc in range(cols):
            x0 = X(904) + cc * width
            props.box(x0 + 0.01, x0 + width - 0.01, BACK_G - 0.62, BACK_G - 0.6, z0 + 0.015, z0 + height - 0.03, drawer)
            # the label strip in the middle of each drawer: small and dim, as the picture's are; at the
            # cabinet line's own strength they read as a grid of white dashes
            glow.box(x0 + width * 0.40, x0 + width * 0.60, BACK_G - 0.63, BACK_G - 0.62, z0 + height * 0.46, z0 + height * 0.54, label)
    props.box(X(918), X(924), 1.2, 1.4, 0.0, c - 0.5, mat["black"])
    # Tried: a long lit counter and a machine beside it, as the picture has. At this scale the
    # counter's top read as a white slab across the room and hid Nadia at her desk; the shopfront's
    # region went 5.4 -> 6.4, so the room keeps the desk it had.
    plant(leaves, pots, X(1016), BACK_G - 0.5, Z(590, BACK_G - 0.5), 0.6, mat["leaf"], mat["pot_white"], pot_h=0.25, pot_r=0.12, n=10, seed=53)
    props.box(X(1004), X(1030), BACK_G - 0.45, BACK_G - 0.4, Z(590, BACK_G - 0.45) - 0.05, Z(590, BACK_G - 0.45), mat["wood"])
    props.box(X(1003), X(1029), BACK_G - 0.08, BACK_G - 0.02, Z(624, BACK_G), Z(600, BACK_G), mat["mon_frame"])
    props.front_quad(X(1005), X(1027), Z(622, BACK_G), Z(602, BACK_G), BACK_G - 0.085, image_material("treasury_chart", "ui_ledger", 1.5))
    props.box(X(930), X(956), 1.9, 2.2, 0.95, 1.0, mat["desk_top"])
    monitor(props, X(943), 2.1, 1.0, M(20), 0.36, mat["mon_frame"], image_material("ledger_screen", "ui_ledger", 1.5))
    screen_anchor("treasury_monitor", X(935), X(951), 1.12, 1.48, 2.098, zone="accounting_office", desk="desk_accounting")
    light(lights, "SPOT", (X(930), 1.5, c - 0.5), 120, "#ffd29a", radius=0.08, cone=70, blend=0.4, rot=(math.radians(20), 0, 0), name="ops_spot_a")
    light(lights, "SPOT", (X(1000), 1.5, c - 0.5), 120, "#ffd29a", radius=0.08, cone=70, blend=0.4, rot=(math.radians(20), 0, 0), name="ops_spot_b")
    workstation(fronts, props, 965, 0, mat, "ui_ledger", "accounting_office", "desk_accounting", side=-1, seat_y=1.3)
    seat("desk_accounting", 965, 0, "front", "accounting_office", y=1.3)
    shell.front_quad(X(897), X(1032), 0.0, Z(541), -0.16, mat["glass"])
    # ---------------- S3 AI SPACE (the ad space storefront)
    room_rect("ad_shop", 1040, 1197, 0, "S3 AI Space")
    rooms.box(X(1040), X(1197), BACK_G, BACK_G + 0.2, f, c, principled("ai_wall", "#1d3a35", rough=0.25, metal=0.1))
    rooms.box(X(1040), X(1197), -0.1, BACK_G, -0.05, 0.0, principled("ai_floor", "#1a2624", rough=0.2))
    teal_glow = emissive("ai_logo", "#6ee7f0", 7.0)
    logo_mark(glow, X(1092), BACK_G - 0.03, Z(557, BACK_G), 1.25, teal_glow)
    light(lights, "POINT", (X(1113), BACK_G - 0.6, Z(574, BACK_G)), 40, "#5eead4", radius=0.6, name="ai_logo_glow")
    text(shell_c, "IDEAS\nTOOLS\nPEOPLE\nIMPACT", X(1146), BACK_G - 0.04, Z(582, BACK_G), 0.32, emissive("ai_words", "#d6dee2", 2.4), line=1.1, name="ai_words")
    ANCHORS["displays"]["ad_wall"] = {"rect": px_rect(X(1052), X(1190), Z(640, BACK_G), Z(548, BACK_G), BACK_G - 0.05), "zone": "ad_shop"}
    props.box(X(1056), X(1082), 1.6, 2.4, 0.0, 2.1, principled("vending", "#1c1f26", rough=0.35, metal=0.3))
    vending_front(props, glow, X(1058), X(1080), 0.6, 1.95, 1.595, seed=7)
    sofa(props, X(1102), X(1182), 2.0, 2.75, f, principled("sofa_orange", "#b9632c", rough=0.55))
    plant(leaves, pots, X(1128), 2.9, f + 0.3, 0.6, mat["leaf"], mat["pot_dark"], pot_h=0.3, pot_r=0.15, n=10, seed=54, style="bush")
    props.box(X(1162), X(1192), 1.7, 2.1, 0.0, 0.55, mat["white"])
    light(lights, "AREA", (X(1120), 1.2, c - 0.4), 120, "#ffd9a8", radius=3.0, name="ai_fill")
    shell.front_quad(X(1040), X(1197), 0.0, Z(541), -0.16, mat["glass"])
