"""
Prop library for the AMN-AI office, built from screen-space pixel sizes with pixelart.Builder.

Every prop is a function `build_<name>(b, mats, rnd, **opts) -> dict` that places geometry so
its anchor is at screen (0, FLOOR_LINE) for floor-standing props (the point the renderer
places at (x, floorLine)) or at screen (0, 0) top-left for wall-mounted props. The returned
dict lists named screen points the renderer needs (screen rectangles, lamp positions).

Sizes mirror the procedural drawings in frontend/src/office_rooms.js so the layout contract
(desk top at floorLine - 24, seat at deskX + 8, monitor at deskX - 34) is unchanged.
"""

from __future__ import annotations

import math
import random

import pixelart as pa
from pixelart import FLOOR_DEPTH_PX as FL, FLOOR_FAR

DEEP = pa.Builder.units_deep


def wall_y0(d_px: float) -> float:
    """Depth (units) of the front face of a box d_px deep whose back touches the wall."""
    return FLOOR_FAR - DEEP(d_px)


class Mats:
    """Toon materials for every palette ramp, created lazily per scene."""

    def __init__(self, palette: dict):
        self.p = palette
        self.M = palette["materials"]
        self.used: list[str] = []

    def ramp(self, name: str, tones: list[str]):
        self.used.extend(tones)
        return pa.toon_material(name, tones)

    def mat(self, key: str):
        ramp = self.M.get(key) or self.p["facade"].get(key)
        if ramp is None:
            raise KeyError(f"no palette ramp named {key}")
        return self.ramp(key, ramp)

    def flat(self, hex_color: str):
        self.used.append(hex_color)
        return pa.flat_material(f"flat_{hex_color}", hex_color)

    def tinted(self, key: str, tint: str, t: float):
        tones = [pa.mix_hex(c, tint, t) for c in self.M[key]]
        return self.ramp(f"{key}_{tint}_{t}", tones)


# ----------------------------------------------------------------------------- workstation

def build_workstation(b: pa.Builder, m: Mats, rnd, variant: int = 0, layer: str = "front", dept_lamp: str = "#e8f4ff"):
    """Desk centred at screen x=0. `layer` 'back' = chair only; 'front' = desk and equipment."""
    wood = m.mat("walnut" if variant % 2 == 0 else "oak")
    steel, black, chrome, brass = m.mat("steel"), m.mat("black"), m.mat("chrome"), m.mat("brass")
    points = {}
    w = 76
    x = -w // 2
    seat_x = 8
    desk_top = FL + 24          # screen y of the far edge of the top surface
    if layer == "back":
        fabric = m.mat("fabricBlue")
        trim = m.mat("ash")
        cx = seat_x
        # Backrest against the wall, seat hidden by the desk, armrests beside the hips.
        # Tall upholstered back: wider than the torso and rising behind the head, so it reads
        # around the seated figure; a headrest, a stitch line and the armrests beside the hips.
        b.box("chair_back", cx - 14, desk_top + 2, 28, 30, 3, fabric, y0=wall_y0(3), bevel=1.2)
        b.box("chair_headrest", cx - 9, desk_top + 32, 18, 5, 3, fabric, y0=wall_y0(3), bevel=1.2)
        b.box("chair_stitch", cx - 10, desk_top + 14, 20, 1, 0.5, m.ramp("fabricBlue_d", [m.M["fabricBlue"][1]] * 5), y0=wall_y0(3) - 0.3)
        b.box("chair_post", cx - 2, desk_top - 2, 4, 6, 1, steel, y0=wall_y0(3) + 0.5)
        for side in (-1, 1):
            ax = cx + (side * 16) - 3
            b.box(f"arm{side}", ax, desk_top + 9, 6, 2, 6, trim, y0=wall_y0(8))
            b.box(f"armpost{side}", ax + 2, desk_top + 2, 2, 7, 1, steel, y0=wall_y0(4))
        return points

    # Desk top: 7 px deep (the whole floor depth), lit slab with a front lip.
    top = b.box("desk_top", x, desk_top - 7 - 2, w, 2, 7, wood, y0=0.0)
    b.box("desk_lip", x, desk_top - 7 - 3, w, 1, 0, m.ramp("wood_d", [m.M["walnut" if variant % 2 == 0 else "oak"][1]] * 5), y0=-0.3)
    # Legs: slim steel frame at the front corners, back legs hidden.
    for lx in (x + 4, x + w - 7):
        b.box(f"leg{lx}", lx, 0, 3, desk_top - 10, 2, steel, y0=0.5)
    # Drawer pedestal.
    dx = x + w - 30 if variant % 2 == 0 else x + 8
    b.box("pedestal", dx, 1, 22, desk_top - 11, 5, wood, y0=1.0)
    for i, dy in enumerate((5, 11)):
        b.box(f"handle{i}", dx + 7, dy, 8, 1, 1, brass, y0=0.4)
        b.box(f"drawer_line{i}", dx + 1, dy + 4, 20, 0.6, 0, m.ramp("wood_dd", [m.M["walnut"][0]] * 5), y0=0.6)
    # Keyboard and mouse on the top surface, in front of the seat.
    kb_y = desk_top - 5
    b.box("keyboard", seat_x - 11, kb_y, 22, 1, 3, black, y0=DEEP(1.5))
    for kx in range(seat_x - 9, seat_x + 10, 2):
        b.box(f"key{kx}", kx, kb_y + 1, 1, 0.3, 1, m.ramp("keys", [m.M["black"][4]] * 5), y0=DEEP(2.0))
    b.box("mouse", seat_x + 14, kb_y, 4, 1, 3, chrome, y0=DEEP(2.0), bevel=0.4)
    # Monitor: bezel, stand, foot; screen is a flat dark plane the renderer paints over.
    mon_x = x + 4
    mon_w, mon_h = 28, 22
    foot_y = desk_top - 4
    b.box("mon_foot", mon_x + mon_w / 2 - 7, foot_y, 14, 1, 3, black, y0=DEEP(3.0))
    b.box("mon_stand", mon_x + mon_w / 2 - 2, foot_y, 4, 5, 2, black, y0=DEEP(4.0))
    bezel_bottom = foot_y + 4
    b.box("mon_bezel", mon_x, bezel_bottom, mon_w, mon_h, 1, black, y0=DEEP(4.0))
    b.box("mon_screen", mon_x + 2, bezel_bottom + 2, mon_w - 4, mon_h - 4, 0, m.flat(m.M["screen"][1]), y0=DEEP(4.0) - 0.4)
    b.box("mon_led", mon_x + mon_w - 3, bezel_bottom + 1, 1, 1, 0, m.flat(m.p["ui"]["amber"]), y0=DEEP(4.0) - 0.4)
    points["screen"] = (mon_x + 2, bezel_bottom + 2, mon_w - 4, mon_h - 4)
    # Papers, mug, desk lamp on the right.
    px_, py_ = seat_x + 20, desk_top - 4
    for i in range(3):
        b.box(f"paper{i}", px_ + i, py_ + i * 0.6, 14, 0.6, 3, m.ramp("paper", m.M["paper"]), y0=DEEP(2.5) - i * 0.2)
    mug_x = seat_x + 26
    b.cylinder("mug", mug_x + 3, desk_top - 6, 3, 6, m.ramp("mug", pa.ramp_from("#3f8a7a", m.p)), y0=DEEP(1.5))
    b.box("mug_handle", mug_x + 6, desk_top - 4, 2, 3, 1, m.ramp("mug2", pa.ramp_from("#3f8a7a", m.p)), y0=DEEP(1.5))
    lamp_x = seat_x + 34
    b.box("lamp_base", lamp_x - 4, desk_top - 6, 9, 2, 3, black, y0=DEEP(3.0))
    b.cylinder("lamp_arm", lamp_x + 1, desk_top - 5, 1, 15, black, y0=DEEP(4.0))
    b.box("lamp_head", lamp_x - 10, desk_top + 9, 12, 4, 3, black, y0=DEEP(3.0), bevel=0.5)
    b.box("lamp_bulb", lamp_x - 8, desk_top + 8, 8, 1, 2, m.flat("#fff2c8"), y0=DEEP(3.3))
    points["lamp"] = (lamp_x - 4, desk_top + 5)
    return points


# ----------------------------------------------------------------------------- furniture

def build_bookshelf(b: pa.Builder, m: Mats, rnd, w=66, h=72, wood="ash"):
    """Standing shelf unit against the wall, anchor (0, FL) = bottom-left."""
    frame = m.mat(wood)
    back = m.ramp(f"{wood}_back", [m.M[wood][0]] * 5)
    d = 4
    y0 = wall_y0(d)
    b.box("shelf_back", 0, FL - d + 0.5, w, h, 0.3, back, y0=y0 + DEEP(d) - 0.5)
    b.box("shelf_left", 0, FL - d, 3, h, d, frame, y0=y0)
    b.box("shelf_right", w - 3, FL - d, 3, h, d, frame, y0=y0)
    b.box("shelf_top", 0, FL - d + h - 3, w, 3, d, frame, y0=y0)
    b.box("shelf_bottom", 0, FL - d, w, 3, d, frame, y0=y0)
    shelves = max(2, h // 18)
    pitch = (h - 6) / shelves
    book_colors = ["#b84a3a", "#2f7a6a", "#d8a44a", "#5a5a9a", "#8a3a5a", "#e8dcc0", "#4a7ab0", "#c07a3a"]
    for s in range(shelves):
        shelf_y = FL - d + 3 + s * pitch
        if s > 0:
            b.box(f"shelf{s}", 3, shelf_y, w - 6, 2, d, frame, y0=y0)
        bx = 5
        base_y = shelf_y + (2 if s > 0 else 0)
        while bx < w - 8:
            bw = 3 + int(rnd.random() * 4)
            bh = 8 + int(rnd.random() * 6)
            c = rnd.choice(book_colors)
            lean = rnd.random() > 0.85
            if lean:
                b.box(f"stack{s}{bx}", bx, base_y, bw + 4, 3, 2, m.ramp(f"book_{c}", pa.ramp_from(c, m.p, 0.5, 0.35)), y0=y0 + 0.6)
                b.box(f"stack2{s}{bx}", bx + 1, base_y + 3, bw + 2, 2, 2, m.ramp("book_x", pa.ramp_from(rnd.choice(book_colors), m.p, 0.5, 0.35)), y0=y0 + 0.6)
                bx += bw + 6
                continue
            b.box(f"book{s}{bx}", bx, base_y, bw, bh, 2.5, m.ramp(f"book_{c}", pa.ramp_from(c, m.p, 0.5, 0.35)), y0=y0 + 0.4)
            if rnd.random() > 0.6:
                b.box(f"label{s}{bx}", bx, base_y + 2, bw, 1, 0, m.flat(m.M["paper"][3]), y0=y0 + 0.2)
            bx += bw + (3 if rnd.random() > 0.8 else 1)
    return {}


def build_evidence_board(b: pa.Builder, m: Mats, rnd, w=140, h=52):
    """Cork board with pinned cards and red string. Wall-mounted: anchor (0,0) = top-left."""
    frame = m.mat("walnut")
    cork = m.ramp("cork", pa.ramp_from("#8a6a48", m.p, 0.5, 0.3))
    d = 2
    y0 = wall_y0(d)
    b.box("board_frame", 0, -h, w, h, d, frame, y0=y0)
    b.box("board_cork", 2, -h + 2, w - 4, h - 4, 0.6, cork, y0=y0 - 0.5)
    cards = []
    tones = [m.M["paper"][3], "#dfe6cf", "#f2dfb0", "#d9e6ee"]
    for i in range(6):
        cx = 8 + (i % 3) * 44 + int(rnd.random() * 4)
        cy = -h + 6 + (1 - i // 3) * 24 + int(rnd.random() * 2)
        tone = rnd.choice(tones)
        b.box(f"card{i}", cx, cy, 28, 17, 0.4, m.flat(tone), y0=y0 - 1.0)
        for li, (lx, lw) in enumerate(((3, 20), (3, 16), (3, 18))):
            b.box(f"line{i}{li}", cx + lx, cy + 12 - li * 4, lw, 1, 0, m.flat("#6a6a70"), y0=y0 - 1.4)
        if i % 2:
            b.box(f"photo{i}", cx + 18, cy + 8, 6, 6, 0.2, m.flat(rnd.choice(["#c04a4a", "#3a7ab0", "#3a9a6a"])), y0=y0 - 1.4)
        b.sphere(f"pin{i}", cx + 14, cy + 17, 1.2, m.flat("#e04a4a"), y0=y0 - 1.8)
        cards.append((cx + 14, cy + 17))
    red = m.flat("#d04646")
    for (x1, y1), (x2, y2) in zip(cards, cards[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        ang = math.atan2(y2 - y1, x2 - x1)
        obj = b.cylinder(f"string{x1}{y1}", 0, 0, 0.45, length, red, y0=y0 - 1.6, axis="X", verts=6)
        # cylinder(axis X) is centred at (length/2, r); move and rotate around Z... the screen
        # plane is X/Z, so rotate about Y by -ang (screen y is world z).
        import bmesh
        from mathutils import Matrix
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.translate(bm, vec=(-length / 2.0, 0, -pa.Builder.z_for(0.45, y0 - 1.6)), verts=bm.verts)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(-ang, 3, "Y"), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(x1, 0, pa.Builder.z_for(y1, y0 - 1.6)), verts=bm.verts)
        bm.to_mesh(obj.data)
        bm.free()
    return {}


def build_window(b: pa.Builder, m: Mats, rnd, w=46, h=38):
    """Window frame with a transparent opening (the renderer paints the view). Anchor top-left."""
    mullion = m.mat("mullion")
    sill = m.ramp("mullion_l", [m.p["facade"]["mullion"][4]] * 5)
    d = 3
    y0 = wall_y0(d)
    # Reveal: the frame sits inside the wall, so the outer frame is thin and the sill projects.
    for name, sx, sy, bw, bh in (("f_top", -1, -1, w + 2, 2), ("f_bot", -1, -h - 1, w + 2, 2),
                                 ("f_left", -1, -h - 1, 2, h + 2), ("f_right", w - 1, -h - 1, 2, h + 2)):
        b.box(name, sx, sy, bw, bh, 1.5, mullion, y0=y0 + DEEP(1.5))
    b.box("mullion_v", w // 2 - 1, -h, 2, h, 1, mullion, y0=y0 + DEEP(2.0))
    b.box("mullion_h", 0, -h // 2, w, 1, 1, mullion, y0=y0 + DEEP(2.0))
    b.box("sill", -3, -h - 3, w + 6, 2, 3, sill, y0=y0)
    return {"opening": (0, -h, w, h)}


def build_lab_bench(b: pa.Builder, m: Mats, rnd):
    """Steel bench with a ceramic top, flasks, a microscope and a notebook. Anchor (0, FL) bottom-left."""
    steel, ceramic, black, chrome, glass = m.mat("steel"), m.mat("ceramic"), m.mat("black"), m.mat("chrome"), m.mat("glass")
    w, top_h = 88, 30
    d = 6
    y0 = wall_y0(d)
    b.box("bench_top", 0, FL - d + top_h - 6, w, 3, d, ceramic, y0=y0)
    b.box("bench_rail", 3, FL - d + top_h - 9, w - 6, 2, 1, steel, y0=y0 + 1)
    for lx in (3, w - 6):
        b.box(f"bleg{lx}", lx, FL - d, 3, top_h - 6, 3, steel, y0=y0 + DEEP(d) - DEEP(3))
    b.box("bench_shelf", 6, FL - d + 8, w - 12, 1, d - 1, steel, y0=y0 + 1)
    shelf_top = FL - d + top_h - 3
    # Flasks in a row.
    for i, c in enumerate(("#5ee0c8", "#ffb35c", "#e08ae4")):
        fx = 8 + i * 12
        liquid = m.ramp(f"liq{c}", pa.ramp_from(c, m.p, 0.4, 0.3))
        b.box(f"flask{i}", fx, shelf_top, 6, 8, 3, glass, y0=y0 + 1.5)
        b.box(f"liquid{i}", fx + 1, shelf_top + 1, 4, 3, 2, liquid, y0=y0 + 1.5 - 0.2)
        b.box(f"neck{i}", fx + 2, shelf_top + 8, 2, 6, 2, glass, y0=y0 + 2.0)
    # Microscope.
    mx = 50
    b.box("scope_base", mx + 1, shelf_top, 10, 2, 4, black, y0=y0 + 1.0)
    b.box("scope_arm", mx + 8, shelf_top + 2, 3, 16, 2, black, y0=y0 + 2.0)
    b.box("scope_stage", mx + 3, shelf_top + 7, 6, 1, 3, black, y0=y0 + 1.5)
    b.cylinder("scope_tube", mx + 6, shelf_top + 8, 1.4, 8, chrome, y0=y0 + 1.2)
    b.wedge("scope_eye", mx + 4, shelf_top + 16, 5, 3, 2, chrome, y0=y0 + 1.0, slope="back")
    # Notebook.
    b.box("notebook", 68, shelf_top, 14, 1.2, 4, m.ramp("paper", m.M["paper"]), y0=y0 + 1.0)
    b.box("notebook_line", 70, shelf_top + 1.2, 10, 0.3, 2, m.flat(m.M["paper"][0]), y0=y0 + 1.5)
    return {}


def build_archive_boxes(b: pa.Builder, m: Mats, rnd):
    box_mat = m.tinted("oak", "#c8a060", 0.2)
    dark = m.ramp("oak0", [m.M["oak"][0]] * 5)
    for i, (dx, dy) in enumerate(((0, 0), (30, 0), (15, 18))):
        b.box(f"abox{i}", dx, FL - 2 + dy, 28, 18, 3, box_mat, y0=wall_y0(3) - dy * 0.0, bevel=0.5)
        b.box(f"alid{i}", dx, FL - 2 + dy + 13, 28, 1, 3, box_mat, y0=wall_y0(3) - 0.6)
        b.box(f"ahandle{i}", dx + 10, FL - 2 + dy + 6, 8, 3, 0, dark, y0=wall_y0(3) - 0.5)
        b.box(f"alabel{i}", dx + 6, FL - 2 + dy + 3, 16, 1.5, 0, m.flat(m.M["paper"][3]), y0=wall_y0(3) - 0.5)
    return {}


def build_plant(b: pa.Builder, m: Mats, rnd, size: float = 1.0):
    """Ceramic pot and a leafy plant, anchor (0, FL) = centre-bottom."""
    pot = m.mat("terracotta")
    leaf = m.mat("plant")
    pw, ph = round(14 * size), round(12 * size)
    d = 4
    y0 = wall_y0(d)
    b.box("pot", -pw / 2, FL - d, pw, ph, d, pot, y0=y0, bevel=0.6)
    b.box("pot_rim", -pw / 2 - 1, FL - d + ph - 2, pw + 2, 2, d + 1, pot, y0=y0 - 0.5)
    b.box("soil", -pw / 2 + 1, FL - d + ph - 1, pw - 2, 0.3, d - 1, m.ramp("soil", [m.M["walnut"][0]] * 5), y0=y0 + 0.5)
    top = FL - d + ph
    leaves = 5 + int(rnd.random() * 3)
    spread = 12 * size
    height = 24 * size
    for i in range(leaves):
        a = (i / leaves) * math.pi + rnd.random() * 0.5
        lx = math.cos(a) * spread * (0.4 + rnd.random() * 0.6)
        ly = top + math.sin(a) * height * (0.5 + rnd.random() * 0.5) + 2
        lw = 5 + rnd.random() * 5
        lh = 4 + rnd.random() * 3
        b.sphere(f"leaf{i}", lx, ly, 1.0, leaf, y0=y0 + rnd.random() * 2, scale=(lw / 2, 1.5, lh / 2), segments=12)
        b.cylinder(f"stem{i}", lx * 0.4, top, 0.5, max(1, ly - lh / 2 - top), m.ramp("stem", [m.M["plant"][1]] * 5), y0=y0 + 1.5)
    return {}


def build_filing_cabinet(b: pa.Builder, m: Mats, rnd, accent="#5ee0c8"):
    steel, chrome = m.mat("steel"), m.mat("chrome")
    d = 4
    y0 = wall_y0(d)
    b.box("cab", 0, FL - d, 24, 36, d, steel, y0=y0)
    for i in range(3):
        b.box(f"drawer{i}", 2, FL - d + 3 + i * 11, 20, 9, 0.6, m.ramp("steel_d", [m.M["steel"][1]] * 5), y0=y0 - 0.4)
        b.box(f"pull{i}", 8, FL - d + 7 + i * 11, 8, 2, 1, chrome, y0=y0 - 1.0)
    b.box("tag", 4, FL - d + 30, 6, 3, 0, m.flat(accent), y0=y0 - 0.8)
    return {}


def build_coat_stand(b: pa.Builder, m: Mats, rnd):
    wood = m.mat("walnut")
    d = 3
    y0 = wall_y0(d)
    b.cylinder("pole", 0, FL - d, 1.2, 64, wood, y0=y0)
    b.box("foot", -7, FL - d, 15, 3, 3, wood, y0=y0 - 0.5)
    b.box("hooks", -6, FL - d + 62, 13, 2, 3, wood, y0=y0 - 0.5)
    coat = m.mat(rnd.choice(["fabricRed", "fabricOlive", "fabricBlue", "leather"]))
    b.box("coat", -11, FL - d + 40, 8, 22, 3, coat, y0=y0 - 1.0, bevel=0.6)
    b.box("collar", -11, FL - d + 60, 8, 2, 3, coat, y0=y0 - 1.5)
    scarf = m.mat(rnd.choice(["fabricRed", "fabricOlive", "brass"]))
    b.box("scarf", 4, FL - d + 46, 4, 14, 2, scarf, y0=y0 - 1.0)
    return {}


def build_bin(b: pa.Builder, m: Mats, rnd):
    steel = m.mat("steel")
    d = 3
    y0 = wall_y0(d)
    b.cylinder("bin", 6, FL - d, 6, 13, steel, y0=y0 + 3)
    b.box("paper_ball", 3, FL - d + 12, 5, 3, 2, m.ramp("paper", m.M["paper"]), y0=y0 + 2)
    return {}


def build_extinguisher(b: pa.Builder, m: Mats, rnd):
    red = m.ramp("ext_red", pa.ramp_from("#c8483a", m.p, 0.5, 0.35))
    black, chrome = m.mat("black"), m.mat("chrome")
    d = 3
    y0 = wall_y0(d)
    b.box("bracket", -3, FL - d + 8, 2, 16, 1, black, y0=y0 + 1.5)
    b.cylinder("body", 3.5, FL - d + 10, 3.5, 18, red, y0=y0)
    b.box("band", 0, FL - d + 14, 7, 2, 0.5, chrome, y0=y0 - 0.5)
    b.cylinder("valve", 3.5, FL - d + 28, 1.5, 4, black, y0=y0)
    b.box("hose", 0, FL - d + 12, 1.5, 14, 0.5, black, y0=y0 - 1.2)
    return {}


def build_poster(b: pa.Builder, m: Mats, rnd, w=30, h=38):
    """Framed poster, anchor top-left."""
    frame = m.mat("black")
    d = 1.5
    y0 = wall_y0(d)
    b.box("frame", 0, -h, w, h, d, frame, y0=y0)
    art = rnd.choice([("#28405a", "#4a7a9a", "#c8d8e0"), ("#4a2a40", "#a05a80", "#f0c8d0"),
                      ("#2a4a34", "#5a9a60", "#e0f0c0"), ("#5a3a20", "#c08040", "#f0e0b0")])
    b.box("art_bg", 2, -h + 2, w - 4, h - 4, 0.2, m.flat(art[0]), y0=y0 - 0.4)
    b.box("art_ground", 2, -h + 2, w - 4, (h - 4) * 0.45, 0.2, m.flat(art[1]), y0=y0 - 0.6)
    b.sphere("art_sun", w * 0.6, -8, 3.5, m.flat(art[2]), y0=y0 - 0.8, scale=(1, 0.2, 1))
    b.box("art_title", 5, -h + 7, w - 10, 2, 0.1, m.flat(art[2]), y0=y0 - 0.8)
    b.box("art_sub", 5, -h + 4, (w - 10) * 0.6, 1, 0.1, m.flat("#5ee0c8"), y0=y0 - 0.8)
    return {}


def build_wall_shelf(b: pa.Builder, m: Mats, rnd):
    """Small shelf with books and a plant, anchor top-left of a 42 x 15 box."""
    oak = m.mat("oak")
    d = 4
    y0 = wall_y0(d)
    b.box("shelf", 0, -14, 40, 2, d, oak, y0=y0)
    b.box("bracket_l", 2, -20, 1, 6, 2, m.mat("steel"), y0=y0 + 1)
    b.box("bracket_r", 37, -20, 1, 6, 2, m.mat("steel"), y0=y0 + 1)
    bx = 3
    colors = ["#b84a3a", "#2f7a6a", "#d8a44a", "#5a5a9a", "#e8dcc0"]
    while bx < 30:
        bw = 3 + int(rnd.random() * 3)
        bh = 7 + int(rnd.random() * 4)
        c = rnd.choice(colors)
        b.box(f"book{bx}", bx, -12, bw, bh, 2.5, m.ramp(f"book_{c}", pa.ramp_from(c, m.p, 0.5, 0.35)), y0=y0 + 0.5)
        bx += bw + 1
    b.box("pot", 33, -12, 5, 5, 2.5, m.mat("terracotta"), y0=y0 + 0.5)
    b.sphere("leaf", 35.5, -5, 3.5, m.mat("plant"), y0=y0 + 1.0, scale=(1, 0.6, 0.8), segments=10)
    return {}


def build_whiteboard(b: pa.Builder, m: Mats, rnd, w=104, h=48, accent="#5ee0c8"):
    chrome, board = m.mat("chrome"), m.ramp("board", m.M["ceramic"])
    d = 1.5
    y0 = wall_y0(d)
    b.box("wb_frame", -1, -h - 1, w + 2, h + 2, d, chrome, y0=y0)
    b.box("wb_face", 0, -h, w, h, 0.3, board, y0=y0 - 0.5)
    for i in range(5):
        lx = 6 + int(rnd.random() * 10)
        ly = -7 - i * ((h - 14) // 5)
        lw = 14 + int(rnd.random() * 26)
        b.box(f"mk{i}", lx, ly, lw, 1.5, 0.1, m.flat("#3a6a9a" if i % 2 else pa.mix_hex(accent, m.p["ambient"]["shadow"], 0.35)), y0=y0 - 0.8)
    # A red box diagram, a blue arrow, a sticky note.
    for name, sx, sy, bw, bh in (("box_t", w - 34, -8, 24, 1.2), ("box_b", w - 34, -24, 24, 1.2), ("box_l", w - 34, -24, 1.2, 17), ("box_r", w - 11, -24, 1.2, 17)):
        b.box(name, sx, sy, bw, bh, 0.1, m.flat("#c04a4a"), y0=y0 - 0.8)
    b.box("arrow", w - 30, -18, 10, 1.5, 0.1, m.flat("#3a6a9a"), y0=y0 - 0.8)
    b.box("sticky", w - 46, -h + 6, 10, 10, 0.4, m.flat("#f4d86a"), y0=y0 - 1.0)
    b.box("tray", 6, -h - 4, w - 12, 2.5, 3, chrome, y0=y0 - 1.0)
    b.box("pen_r", 10, -h - 2, 6, 1.5, 1.5, m.flat("#c04a4a"), y0=y0 - 1.8)
    b.box("pen_b", 18, -h - 2, 6, 1.5, 1.5, m.flat("#3a6a9a"), y0=y0 - 1.8)
    return {}


def build_water_cooler(b: pa.Builder, m: Mats, rnd):
    steel, glass = m.mat("steel"), m.mat("glass")
    d = 4
    y0 = wall_y0(d)
    b.box("cooler", 0, FL - d, 20, 46, d, steel, y0=y0)
    b.box("taps", 6, FL - d + 26, 8, 3, 1, m.mat("black"), y0=y0 - 1)
    b.box("tap_blue", 7, FL - d + 27, 2, 1, 0.5, m.flat("#5a9ad8"), y0=y0 - 1.6)
    b.box("tap_red", 11, FL - d + 27, 2, 1, 0.5, m.flat("#d85a5a"), y0=y0 - 1.6)
    b.cylinder("bottle", 10, FL - d + 46, 7, 18, glass, y0=y0 + DEEP(d) / 2)
    return {"bubbles": (10, FL - d + 54)}


# Registry: name -> (builder, kind, frame (x0, y0, w, h) in screen px, options)
# kind 'floor' anchors at (0, FL); kind 'wall' anchors at (0, 0) top-left.
PROPS = {
    "workstation_walnut_back":  (build_workstation, "floor", (-44, -2, 92, 90), {"variant": 0, "layer": "back"}),
    "workstation_walnut":       (build_workstation, "floor", (-44, -2, 100, 80), {"variant": 0, "layer": "front"}),
    "workstation_oak_back":     (build_workstation, "floor", (-44, -2, 92, 90), {"variant": 1, "layer": "back"}),
    "workstation_oak":          (build_workstation, "floor", (-44, -2, 100, 80), {"variant": 1, "layer": "front"}),
    "bookshelf_ash":            (build_bookshelf, "floor", (-2, -2, 84, 84), {"wood": "ash"}),
    "bookshelf_walnut":         (build_bookshelf, "floor", (-2, -2, 104, 86), {"w": 84, "h": 74, "wood": "walnut"}),
    "evidence_board":           (build_evidence_board, "wall", (-3, -58, 150, 62), {}),
    "window_46x38":             (build_window, "wall", (-5, -45, 58, 50), {}),
    "lab_bench":                (build_lab_bench, "floor", (-2, -2, 108, 60), {}),
    "archive_boxes":            (build_archive_boxes, "floor", (-2, -2, 74, 44), {}),
    "plant_large":              (build_plant, "floor", (-22, -2, 52, 54), {"size": 1.1}),
    "plant_small":              (build_plant, "floor", (-18, -2, 44, 44), {"size": 0.8}),
    "filing_cabinet":           (build_filing_cabinet, "floor", (-2, -2, 40, 46), {}),
    "coat_stand":               (build_coat_stand, "floor", (-16, -2, 42, 74), {}),
    "bin":                      (build_bin, "floor", (-2, -2, 26, 24), {}),
    "extinguisher":             (build_extinguisher, "floor", (-6, -2, 24, 42), {}),
    "poster_a":                 (build_poster, "wall", (-2, -42, 44, 46), {"w": 30, "h": 38}),
    "poster_b":                 (build_poster, "wall", (-2, -40, 40, 44), {"w": 26, "h": 34}),
    "wall_shelf":               (build_wall_shelf, "wall", (-2, -24, 54, 30), {}),
    "whiteboard":               (build_whiteboard, "wall", (-3, -56, 118, 62), {}),
    "water_cooler":             (build_water_cooler, "floor", (-2, -2, 36, 72), {}),
}
