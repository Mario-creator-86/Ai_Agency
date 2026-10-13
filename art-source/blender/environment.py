"""
Environment tiles: the parts of a room shell that benefit from real volume and light —
wainscot panelling, dado and picture rails, skirting, sockets, and the 3/4 floor with its
grout lines and slab edge. Rendered per department from the palette's material story, as
horizontally tileable strips the renderer repeats across the zone.

The plain plaster above the dado stays transparent: the renderer keeps painting its own
lit-to-shadow wall gradient and baked light cones behind these tiles.
"""

from __future__ import annotations

import pixelart as pa
from pixelart import FLOOR_DEPTH_PX as FL, FLOOR_FAR
from props import Mats, wall_y0

DEEP = pa.Builder.units_deep

WALL_TILE_W = 56
FLOOR_TILE_W = 84
SLAB_EDGE_PX = 2


def build_wall(b: pa.Builder, m: Mats, rnd, dept: dict, wall_h: int = 111):
    """Wall features for one tile: anchor (0, FL) = bottom-left at the wall/floor junction."""
    wall = dept["wall"]
    trim = m.ramp("trim", dept["trim"])
    wall_mat = m.ramp("wall", wall)
    # Wall material that reads as the *shadow* tones on lit faces: panel frames sit below the
    # dado where the renderer's wall gradient is already dark.
    wall_low = m.ramp("wall_low", [wall[0], wall[1], wall[2], wall[3], wall[3]])
    dado = FL + 25                       # renderer: dado = floorY - 25, i.e. 25 px above the floor line
    y0 = wall_y0(0)
    # Wainscot: a flat dark board with raised panel frames; every panel gets a lit top edge.
    b.box("wainscot", 0, FL, WALL_TILE_W, dado - FL, 0.02, m.ramp("wainscot", [wall[0], wall[0], wall[1], wall[1], wall[2]]), y0=y0 - 0.02)
    panel_w = 28
    for i in range(WALL_TILE_W // panel_w):
        px0 = i * panel_w + 3
        pw = panel_w - 6
        frame_bottom = FL + 6
        frame_top = dado - 4
        b.box(f"pf_l{i}", px0, frame_bottom, 2, frame_top - frame_bottom, 1.2, wall_low, y0=y0 - DEEP(1.2))
        b.box(f"pf_r{i}", px0 + pw - 2, frame_bottom, 2, frame_top - frame_bottom, 1.2, wall_low, y0=y0 - DEEP(1.2))
        b.box(f"pf_t{i}", px0, frame_top - 2, pw, 2, 1.2, wall_low, y0=y0 - DEEP(1.2))
        b.box(f"pf_b{i}", px0, frame_bottom, pw, 2, 1.2, wall_low, y0=y0 - DEEP(1.2))
    # Dado rail: a moulded strip that catches the light.
    b.box("dado", 0, dado, WALL_TILE_W, 2, 2, trim, y0=y0 - DEEP(2))
    b.box("dado_shadow", 0, dado - 1, WALL_TILE_W, 1, 0.02, m.ramp("dado_s", [wall[0]] * 5), y0=y0 - 0.5)
    # Skirting board.
    b.box("skirting", 0, FL, WALL_TILE_W, 4, 1.5, trim, y0=y0 - DEEP(1.5))
    b.box("skirting_top", 0, FL + 4, WALL_TILE_W, 1, 1.8, trim, y0=y0 - DEEP(1.8))
    # Plaster joint: a faint lit seam at the tile edge between dado and picture rail.
    b.box("joint", WALL_TILE_W - 1, dado + 3, 1, wall_h - 14 - 25 - 5, 0.3, m.ramp("joint", [wall[2], wall[2], wall[3], wall[3], wall[3]]), y0=y0 - 0.3)
    # Picture rail near the ceiling.
    b.box("picture_rail", 0, FL + wall_h - 14, WALL_TILE_W, 1, 1.5, trim, y0=y0 - DEEP(1.5))
    # Socket in the middle of the tile, just above the skirting.
    b.box("socket", WALL_TILE_W // 2 - 3, FL + 7, 6, 4, 0.6, m.ramp("socket", m.M["ceramic"]), y0=y0 - DEEP(0.6))
    b.box("socket_h1", WALL_TILE_W // 2 - 2, FL + 8, 1, 2, 0, m.flat(m.M["black"][1]), y0=y0 - DEEP(0.6) - 0.3)
    b.box("socket_h2", WALL_TILE_W // 2 + 1, FL + 8, 1, 2, 0, m.flat(m.M["black"][1]), y0=y0 - DEEP(0.6) - 0.3)
    return {}


def build_floor(b: pa.Builder, m: Mats, rnd, dept: dict, style: str = "tiles"):
    """Floor strip: tiles seen in 3/4, grout lines, and the concrete slab edge below the near
    edge. Anchor (0, FL) = top-left of the strip at the wall junction."""
    f = dept["floor"]
    # Lit top faces should read as the base tone, with grout one tone darker.
    tile = m.ramp("tile", [f[0], f[1], f[1], f[2], f[3]])
    grout = m.ramp("grout", [f[0], f[0], f[1], f[1], f[1]])
    slab = m.ramp("slab", m.p["facade"]["slab"])
    b.box("bed", 0, 0, FLOOR_TILE_W, 0, FL, grout, y0=0.0)
    if style == "tiles":
        tw = 14
        for i in range(FLOOR_TILE_W // tw):
            for row, (d0, d1) in enumerate(((0.0, FL / 2 - 0.5), (FL / 2 + 0.5, FL))):
                x = i * tw + ((row % 2) * 7)
                b.box(f"tile{i}{row}", x + 0.5, 0, tw - 1, 0.3, d1 - d0, tile, y0=DEEP(d0))
    elif style == "planks":
        for i, (x, w) in enumerate(((0, 30), (30, 26), (56, 28))):
            b.box(f"plank{i}", x + 0.3, 0, w - 0.6, 0.3, FL, tile, y0=0.0)
    else:
        b.box("surface", 0, 0, FLOOR_TILE_W, 0.3, FL, tile, y0=0.0)
    # Slab edge below the near edge (front face only).
    b.box("slab_edge", 0, -SLAB_EDGE_PX, FLOOR_TILE_W, SLAB_EDGE_PX, 0, slab, y0=-0.5)
    return {}


# name -> (builder, kind, frame, options). Both anchor at screen (0, FL).
ENVIRONMENT = {
    "wall_RESEARCH_h111": (build_wall, "floor", (0, FL - 1, WALL_TILE_W, 112), {"dept_key": "RESEARCH", "wall_h": 111}),
    "floor_RESEARCH": (build_floor, "floor", (0, -SLAB_EDGE_PX, FLOOR_TILE_W, FL + SLAB_EDGE_PX + 1), {"dept_key": "RESEARCH", "style": "tiles"}),
}
