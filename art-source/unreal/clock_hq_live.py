"""
The bus-shelter clock of the live headquarters (/Game/HQ/HQ_Dusk) shows the real time.

Until now its face carried "15:18" as built geometry (hq_city.py CLOCK_TIME, the mesh
clock_digits_mesh with its emission baked into a texture): the picture's time, shown all day.
This pass hides that mesh and puts a display on the same face whose material works out hh:mm
itself, from the engine's game time plus one scalar the backend sets, ClockOffsetS:

    shown time = (game time + ClockOffsetS) mod 86400, as hh:mm

The backend is the source of the time. It sends ClockOffsetS = (local seconds of the day in
Europe/Bucharest) - (the game's world time) on every full refresh (20 s) and at a DST change, so
the display flips on the minute without the bridge having to send each minute (a 5 s tick plus
the Remote Control round trip would put it up to 7 s late), and if the backend stops, the face
drifts only by the frame clock's error instead of freezing. Until the first sync the material's
default is a sentinel and the face reads --:--, drawn by the build itself: never blank, never the
game's uptime dressed as a time.

Why it is drawn the way it is. The first live display (rebuild window 2026-09-19 08:38) could not
be read: five equal slots over the old digits' 34 px at 1920 x 1008 gave each glyph about 7 px,
its segments were 9 texels of a 64 x 128 cell (about one pixel), the atlas went in with the
import's defaults (sRGB, block-compressed, streamed) and the mask clipped at the default 0.333, so
the mip the GPU picked averaged the segments under the clip: fragments after the sync, and before
it nothing at all (the minus and the colon are the thinnest glyphs). The old baked "15:18" measured
37 x 13 px of lit mint. Now:

  - the digits fill the face the way a shelter's LED clock does: centred, FACE_FILL (86 %) of the
    face rect's width, which makes a glyph about 22 px tall and "88:88" about 63 px wide on the
    1920 stream, with a narrow colon slot instead of a fifth of the width;
  - segments are 0.146 of the glyph's height (28 of 192 texels), about 3.2 px on the stream and
    still 2.4 px when the page shows the stream at 1440 wide;
  - the atlas is 2048 x 256 (16 cells of 128 x 256, glyphs 96 x 192): the face shows a glyph at
    about 8.7 texels a pixel, so the GPU minifies by mip ~3.1 and never magnifies, and a segment is
    still 3.2 texels thick at that mip, its centre at full coverage;
  - the texture is linear (so the mask's 0.5 is half coverage), uncompressed G8 (no 4 x 4 blocks on
    a 3-texel stroke), trilinear, with box-averaged mips (which keep a straight edge exactly at 0.5),
    clamped, and never streamed (every mip resident from the first frame, so --:-- shows at load);
  - glyph cells keep 16 texels of margin across and 32 above and below, so no mip down to 4 bleeds;
  - the material clips at 0.5 and lights every kept pixel fully; TSR smooths the edge.

tests/test_clock_atlas.py renders the face the way the GPU does at those sizes and reads the time
back off the pixels, at every sub-pixel offset, and again at the page's fit size.

The digits are drawn here, seven-segment, with numpy (no font, so no font licence), in the mint
of today's display (#7df0c4) at the strength today's baked digits have (EmissiveStrength 4.357,
read off their material when it is found). The atlas also holds a minus and a degree sign so a
second line can show the temperature later; that line waits for the Owner's approval of its look
and place (decision D3), so nothing here shows a temperature.

Three ways to run it:

  py -3.11 art-source/unreal/clock_hq_live.py --atlas [art-source/unreal/clock_digits_atlas.png]
      draws the digit atlas (outside Unreal: the editor's Python has no numpy of its own)
  py -3.11 art-source/unreal/clock_hq_live.py --preview out.png [hh:mm]
      renders the face at the stream's size, as the tests do, magnified 8x for a look by eye
  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=clock_hq_live.py
      hides the baked digits and places the display, with the stream stopped

Importing this file outside Unreal does nothing (tests/test_clock_atlas.py imports it).
"""

import json
import math
import os
import sys

try:
    import unreal
except ImportError:  # the atlas step and the tests run in a plain Python
    unreal = None

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
ATLAS_PNG = os.path.join(HERE, "clock_digits_atlas.png")
AXIS_MAP = os.path.join(HERE, "axis_map.json")
FOLDER = "/Game/HQ/Clock"
TEXTURE = f"{FOLDER}/T_HQ_ClockDigits"
MATERIAL = f"{FOLDER}/M_HQ_DigitDisplay"
LABEL = "ClockDisplay"
BAKED_LABEL = "clock_digits_mesh"
TAG = "AMN_CLOCK"

# ---------------------------------------------------------------- the digits

# The atlas: one cell per glyph, left to right. 0-9, the colon, a blank, a minus and a degree sign
# (for the temperature line D3 may add), padded with blanks to 16 so the texture is a power of two
# and keeps its whole mip chain.
GLYPH_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", " ", "-", "°", " ", " "]
GLYPH_INDEX = {g: i for i, g in enumerate(GLYPH_ORDER[:14])}
CELLS = len(GLYPH_ORDER)
CELL_W, CELL_H = 128, 256
SUPERSAMPLE = 4

#  aaa
# f   b
#  ggg
# e   c
#  ddd
SEGMENTS = {
    "0": set("abcdef"), "1": set("bc"), "2": set("abdeg"), "3": set("abcdg"), "4": set("bcfg"),
    "5": set("acdfg"), "6": set("acdefg"), "7": set("abc"), "8": set("abcdefg"), "9": set("abcdfg"),
    "-": set("g"), "°": set("abfg"), " ": set(), ":": set(),
}

# The glyph inside a 128 x 256 cell: 96 x 192 texels, half as wide as tall like a shelter's LED
# digits, with 16 texels free across (a whole texel of mip 4) and 32 above and below.
GLYPH_X0, GLYPH_X1, GLYPH_Y0, GLYPH_Y1 = 16.0, 112.0, 32.0, 224.0
GLYPH_TEXELS_H = int(GLYPH_Y1 - GLYPH_Y0)
THICK = 28.0  # 0.146 of the glyph's height: 3.2 px on the stream, 3.2 texels at the mip it uses
GAP = 3.0  # the bevel's gap between segments: closed by the mip on the stream, seen close up
MASK_CLIP = 0.5  # box-filtered coverage crosses 0.5 exactly on a straight edge


def _mid_y():
    return (GLYPH_Y0 + GLYPH_Y1) / 2.0


def segment_centres():
    """Each segment's centre in cell texels (x right, y down)."""
    cx, ym, h = (GLYPH_X0 + GLYPH_X1) / 2.0, _mid_y(), THICK / 2.0
    upper, lower = (GLYPH_Y0 + ym) / 2.0, (ym + GLYPH_Y1) / 2.0
    return {"a": (cx, GLYPH_Y0 + h), "g": (cx, ym), "d": (cx, GLYPH_Y1 - h),
            "f": (GLYPH_X0 + h, upper), "b": (GLYPH_X1 - h, upper),
            "e": (GLYPH_X0 + h, lower), "c": (GLYPH_X1 - h, lower)}


def hole_centres():
    """The two dark counters of an 8: they must stay dark on the stream."""
    cx, ym = (GLYPH_X0 + GLYPH_X1) / 2.0, _mid_y()
    return [(cx, (GLYPH_Y0 + THICK + ym - THICK / 2.0) / 2.0), (cx, (ym + THICK / 2.0 + GLYPH_Y1 - THICK) / 2.0)]


def colon_centres():
    """The colon's dots, one in the middle of each counter of an 8, as on an LED clock."""
    top, bottom = hole_centres()
    return {"upper": top, "lower": bottom}


def _segment_mask(xs, ys, name):
    """Inside test of one bevelled segment (a hexagon: square across, pointed along)."""
    ym = _mid_y()
    half_t = THICK / 2.0
    cx, cy = segment_centres()[name]
    if name in "agd":
        half_len = (GLYPH_X1 - GLYPH_X0) / 2.0 - GAP
        along, across = abs(xs - cx), abs(ys - cy)
    else:
        half_len = (ym - GLYPH_Y0) / 2.0 - GAP
        along, across = abs(ys - cy), abs(xs - cx)
    return (across <= half_t) & (along + across <= half_len)


def draw_glyph(glyph):
    """One cell, 0..1 float, drawn at SUPERSAMPLE x and box-filtered down for soft edges."""
    import numpy as np

    n = SUPERSAMPLE
    ys, xs = np.mgrid[0 : CELL_H * n, 0 : CELL_W * n].astype(np.float64)
    xs, ys = (xs + 0.5) / n, (ys + 0.5) / n
    lit = np.zeros(xs.shape, bool)
    for name in SEGMENTS[glyph]:
        lit |= _segment_mask(xs, ys, name)
    if glyph == ":":
        for cx, cy in colon_centres().values():
            lit |= (abs(xs - cx) <= THICK / 2.0) & (abs(ys - cy) <= THICK / 2.0)
    return lit.reshape(CELL_H, n, CELL_W, n).mean(axis=(1, 3))


def digit_atlas():
    """The whole atlas, uint8 (CELL_H, CELL_W * CELLS): white segments on black."""
    import numpy as np

    cells = [draw_glyph(g) for g in GLYPH_ORDER]
    return np.round(np.hstack(cells) * 255.0).astype(np.uint8)


def atlas_cell(atlas, index):
    return atlas[:, index * CELL_W : (index + 1) * CELL_W]


def write_atlas(path):
    from PIL import Image

    atlas = digit_atlas()
    # one 8-bit grey channel: imported as G8 and set linear (ATLAS_TEXTURE_SETTINGS), so the value
    # the mask clips is the coverage drawn here
    Image.fromarray(atlas, "L").save(path)
    print(f"AMN_CLOCK atlas {CELLS} glyphs of {CELL_W}x{CELL_H} -> {path} ({atlas.shape[1]}x{atlas.shape[0]})")


# The texture's settings, stated rather than left to the import (whose defaults - sRGB, BC1 blocks,
# streamed - were the first display's). (enum, member) pairs are looked up in unreal at run time.
ATLAS_TEXTURE_SETTINGS = {
    "srgb": False,
    "compression_settings": ("TextureCompressionSettings", "TC_GRAYSCALE"),
    "filter": ("TextureFilter", "TF_TRILINEAR"),
    "mip_gen_settings": ("TextureMipGenSettings", "TMGS_SIMPLE_AVERAGE"),
    "address_x": ("TextureAddress", "TA_CLAMP"),
    "address_y": ("TextureAddress", "TA_CLAMP"),
    "never_stream": True,
    "lod_bias": 0,
}


def sampler_type_for(compression, srgb):
    """The material sampler a texture of this compression and colour space needs (a mismatch is a
    material compile error)."""
    grey = compression in ("TC_GRAYSCALE", "TC_ALPHA", "TC_DISPLACEMENTMAP")
    if grey:
        return "SAMPLERTYPE_GRAYSCALE" if srgb else "SAMPLERTYPE_LINEAR_GRAYSCALE"
    return "SAMPLERTYPE_COLOR" if srgb else "SAMPLERTYPE_LINEAR_COLOR"


# ---------------------------------------------------------------- the layout on the face

# In glyph heights: a digit's slot (its 0.5 wide glyph and 0.16 of spacing) and the colon's.
DIGIT_ADVANCE = 0.66
COLON_ADVANCE = 0.34
FACE_FILL = 0.86  # of the face rect's width; the rest is the panel's border, about 5.5 px a side


def hlsl_number(x):
    return f"{x:.6f}"


def _rounded(x):
    return float(hlsl_number(x))


def slot_layout():
    """(lo, hi, window) per slot h h : m m: the slot's span of the display's U, and the share of
    its atlas cell it shows, centred (the digits' glyph plus spacing, the colon's dots). Numbers
    rounded as the HLSL carries them, so this is the material's own layout."""
    advances = [DIGIT_ADVANCE, DIGIT_ADVANCE, COLON_ADVANCE, DIGIT_ADVANCE, DIGIT_ADVANCE]
    total = sum(advances)
    out, lo = [], 0.0
    for i, a in enumerate(advances):
        hi = 1.0 if i == len(advances) - 1 else _rounded(lo + a / total)
        out.append((lo, hi, _rounded(a * GLYPH_TEXELS_H / CELL_W)))
        lo = hi
    return out


def display_box(face):
    """Where U, V run 0..1 on the face, in Blender metres: centred on the shelter clock's rect,
    FACE_FILL of its width, and as tall as a whole cell at the glyph height that width gives."""
    advances = 4 * DIGIT_ADVANCE + COLON_ADVANCE
    width = (face["x1"] - face["x0"]) * FACE_FILL
    glyph_h = width / advances
    height = glyph_h * CELL_H / GLYPH_TEXELS_H
    if height > face["z1"] - face["z0"]:
        raise ValueError("the display would be taller than the clock's face")
    cx, cz = (face["x0"] + face["x1"]) / 2.0, (face["z0"] + face["z1"]) / 2.0
    return {"x0": cx - width / 2.0, "x1": cx + width / 2.0, "z0": cz - height / 2.0, "z1": cz + height / 2.0}


# ---------------------------------------------------------------- the time the material shows

# ClockOffsetS's default: far below any real offset (local seconds of day minus a game time of
# less than thirty years), so the face can tell "never synced" from any time of day.
UNSYNCED_OFFSET = -1.0e10
UNSYNCED_BELOW = -1.0e9
SLOTS = 5  # h h : m m

DIGIT_INPUTS = ("U", "V", "T", "Offset", "Cells")


def _digit_hlsl():
    (_, e1, wd), (_, e2, _), (_, e3, wc), (_, e4, _), _ = slot_layout()
    n = hlsl_number
    # The material's Custom node: (U, V) on the display box (0..1, V down), T the engine's game
    # time, Offset the backend's ClockOffsetS. Returns the atlas UV of the glyph under this pixel;
    # outside the box, the blank glyph. atlas_uv() and display_glyphs() below are the same
    # arithmetic in Python, under test.
    return f"""float g = 11.0;
float cu = 0.5;
if (U >= 0.0 && U <= 1.0 && V >= 0.0 && V <= 1.0)
{{
    float lo = 0.0; float hi = {n(e1)}; float w = {n(wd)}; float slot = 0.0;
    if (U >= {n(e1)}) {{ lo = {n(e1)}; hi = {n(e2)}; slot = 1.0; }}
    if (U >= {n(e2)}) {{ lo = {n(e2)}; hi = {n(e3)}; w = {n(wc)}; slot = 2.0; }}
    if (U >= {n(e3)}) {{ lo = {n(e3)}; hi = {n(e4)}; w = {n(wd)}; slot = 3.0; }}
    if (U >= {n(e4)}) {{ lo = {n(e4)}; hi = 1.0; slot = 4.0; }}
    cu = 0.5 + ((U - lo) / (hi - lo) - 0.5) * w;
    if (Offset < {UNSYNCED_BELOW:.1e})
    {{
        g = (slot == 2.0) ? 10.0 : 12.0;
    }}
    else
    {{
        float s = T + Offset;
        s = s - floor(s / 86400.0) * 86400.0;
        float mins = floor(s / 60.0);
        float h = floor(mins / 60.0);
        float m = mins - h * 60.0;
        float d[{SLOTS}] = {{ floor(h / 10.0), h - floor(h / 10.0) * 10.0, 10.0, floor(m / 10.0), m - floor(m / 10.0) * 10.0 }};
        g = d[(int)slot];
    }}
}}
return float2((g + cu) / Cells, V);"""


DIGIT_HLSL = _digit_hlsl()


def display_glyphs(game_time_s, offset_s, float32=False):
    """The five glyph indices the face shows, by the material's own arithmetic. With float32 the
    sums are rounded as the GPU rounds them."""
    if float32:
        import numpy as np

        f = np.float32
    else:
        def f(x):
            return float(x)
    if offset_s < UNSYNCED_BELOW:
        return [12, 12, 10, 12, 12]
    s = f(f(game_time_s) + f(offset_s))
    s = f(s - f(math.floor(f(s / f(86400.0)))) * f(86400.0))
    mins = math.floor(f(s / f(60.0)))
    h = math.floor(mins / 60.0)
    m = mins - h * 60
    return [h // 10, h % 10, 10, m // 10, m % 10]


def atlas_uv(U, V, glyphs):
    """The Custom node's output for arrays of (U, V), given the five glyphs display_glyphs()
    chose: the same slot search, window and blank outside the box."""
    import numpy as np

    U, V = np.asarray(U, np.float64), np.asarray(V, np.float64)
    inside = (U >= 0.0) & (U <= 1.0) & (V >= 0.0) & (V <= 1.0)
    g = np.full(U.shape, 11.0)
    cu = np.full(U.shape, 0.5)
    slots = slot_layout()
    slot = np.zeros(U.shape, int)
    for k in range(1, SLOTS):
        slot[U >= slots[k][0]] = k
    lo = np.array([s[0] for s in slots])[slot]
    hi = np.array([s[1] for s in slots])[slot]
    w = np.array([s[2] for s in slots])[slot]
    cu = np.where(inside, 0.5 + ((U - lo) / (hi - lo) - 0.5) * w, cu)
    g = np.where(inside, np.array(glyphs, np.float64)[slot], g)
    return (g + cu) / CELLS, V


# ---------------------------------------------------------------- what the stream shows

# hq_lib.py's projection, which placed the clock in Blender: world pixels (1600 x 840 at scale 1)
# seen by an orthographic camera pitched 10 degrees down. The live PlateCam frames the same view at
# 1920 x 1008: the clock box measured 1691-1776 across, 1408-1480 x 1.2.
PPM = 28.0
SIN, COS = math.sin(math.radians(10.0)), math.cos(math.radians(10.0))
CX, CY = 800.0, 420.0
GROUND_ROW = 655.0
ZC = (GROUND_ROW - CY) / PPM / COS
WALK_Z = -0.7  # hq_city.py
WORLD_W = 1600.0


def X(px):
    return (px - CX) / PPM


def Z(row, y=0.0):
    return ZC + ((CY - row) / PPM - y * SIN) / COS


def Y(row, z=0.0):
    return ((CY - row) / PPM - (z - ZC) * COS) / SIN


def project(p):
    v = p[1] * SIN + (p[2] - ZC) * COS
    return (CX + p[0] * PPM, CY - v * PPM)


def screen_rect(box, y, frame_w):
    """A face-plane box on a frame frame_w pixels wide: top-left x, y, width, height in pixels,
    and the glyph height a display box of that size shows."""
    k = frame_w / WORLD_W
    c0, r0 = project((box["x0"], y, box["z1"]))
    c1, r1 = project((box["x1"], y, box["z0"]))
    h = (r1 - r0) * k
    return {"x": c0 * k, "y": r0 * k, "w": (c1 - c0) * k, "h": h, "glyph_h_px": h * GLYPH_TEXELS_H / CELL_H}


def mip_chain(atlas):
    """The texture's mips as TMGS_SIMPLE_AVERAGE makes them: 2 x 2 box averages, down to one row."""
    import numpy as np

    level = atlas.astype(np.float64) / 255.0
    out = [level]
    while level.shape[0] > 1:
        h, w = level.shape
        level = level.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
        out.append(level)
    return out


def mip_level(rect):
    """The GPU's level of detail on the face: log2 of the larger texel-per-pixel rate, U or V."""
    lo, hi, window = slot_layout()[0]
    per_px_u = window * CELL_W / ((hi - lo) * rect["w"])
    per_px_v = CELL_H / rect["h"]
    return max(0.0, math.log2(max(per_px_u, per_px_v)))


def _bilinear(level, u, v):
    import numpy as np

    h, w = level.shape
    x, y = u * w - 0.5, v * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0

    def at(yy, xx):
        return level[np.clip(yy, 0, h - 1), np.clip(xx, 0, w - 1)]

    top = at(y0, x0) * (1 - fx) + at(y0, x0 + 1) * fx
    bottom = at(y0 + 1, x0) * (1 - fx) + at(y0 + 1, x0 + 1) * fx
    return top * (1 - fy) + bottom * fy


def render(glyphs, rect, mips, samples=1):
    """The face as the GPU draws it on a frame: for each pixel (samples x samples jittered sample
    points, as TSR accumulates them; 1 = the pixel centre only), the Custom node's UV, a trilinear
    sample at the face's mip, the mask's clip. Returns the coverage image, its top-left pixel and
    the rect."""
    import numpy as np

    ix0, iy0 = int(math.floor(rect["x"])) - 1, int(math.floor(rect["y"])) - 1
    ix1, iy1 = int(math.ceil(rect["x"] + rect["w"])) + 1, int(math.ceil(rect["y"] + rect["h"])) + 1
    lod = mip_level(rect)
    l0 = min(int(math.floor(lod)), len(mips) - 1)
    l1, frac = min(l0 + 1, len(mips) - 1), lod - math.floor(lod)
    image = np.zeros((iy1 - iy0, ix1 - ix0))
    offsets = [(i + 0.5) / samples for i in range(samples)]
    py, px = np.mgrid[iy0:iy1, ix0:ix1].astype(np.float64)
    for oy in offsets:
        for ox in offsets:
            U = (px + ox - rect["x"]) / rect["w"]
            V = (py + oy - rect["y"]) / rect["h"]
            u, v = atlas_uv(U, V, glyphs)
            value = _bilinear(mips[l0], u, v) * (1 - frac) + _bilinear(mips[l1], u, v) * frac
            image += value >= MASK_CLIP
    return {"image": image / samples**2, "origin": (ix0, iy0), "rect": dict(rect)}


def shrink(frame, scale):
    """The page showing the stream smaller: an area-weighted resample of the frame by scale < 1."""
    import numpy as np

    img = frame["image"]
    ox, oy = frame["origin"]
    h, w = img.shape
    nx0, ny0 = int(math.floor(ox * scale)), int(math.floor(oy * scale))
    nx1, ny1 = int(math.ceil((ox + w) * scale)), int(math.ceil((oy + h) * scale))

    def weights(n0, n1, o, size):
        # rows: new pixels; columns: old pixels; overlap length of [j, j+1)/scale with [o+i, o+i+1)
        m = np.zeros((n1 - n0, size))
        for j in range(n0, n1):
            a, b = j / scale, (j + 1) / scale
            for i in range(size):
                lo_, hi_ = max(a, o + i), min(b, o + i + 1)
                if hi_ > lo_:
                    m[j - n0, i] = hi_ - lo_
        return m / (1.0 / scale)

    wy, wx = weights(ny0, ny1, oy, h), weights(nx0, nx1, ox, w)
    r = frame["rect"]
    small = {k: r[k] * scale for k in ("x", "y", "w", "h", "glyph_h_px")}
    return {"image": wy @ img @ wx.T, "origin": (nx0, ny0), "rect": small}


def write_preview(path, text):
    """The face at 1920 x 1008, as the tests render it (4 x 4 samples), magnified 8x, mint on the
    clock box's own #0c1c22."""
    import numpy as np
    from PIL import Image

    face = shelter_clock_face()
    rect = screen_rect(display_box(face), face["y"], 1920)
    frame = render([GLYPH_INDEX[c] for c in text], rect, mip_chain(digit_atlas()), samples=4)
    a = frame["image"][..., None]
    box, mint = np.array([0x0C, 0x1C, 0x22], float), np.array([0x7D, 0xF0, 0xC4], float)
    rgb = (box * (1 - a) + mint * a).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")
    img.resize((img.width * 8, img.height * 8), Image.NEAREST).save(path)
    print(f"AMN_CLOCK preview '{text}': glyph {rect['glyph_h_px']:.1f} px tall, display "
          f"{rect['w']:.1f} x {rect['h']:.1f} px at 1920, mip {mip_level(rect):.2f} -> {path}")


# ---------------------------------------------------------------- where the face is


def shelter_clock_face():
    """STREET["shelter_clock"]'s rect in Blender metres (hq_city.py): the clock box stands at
    columns 1408-1480 between rows 657 and 620, 0.3 m behind the shelter's front; the rect is
    columns 1411-1477 inset 8 cm top and bottom. The display lies in the plane the baked digits
    stood in, 2 cm in front of the box's face, facing the camera."""
    y_walk = Y(717, WALK_Z)
    sy0 = y_walk + 1.2
    z0, z1 = Z(657, sy0 + 0.3), Z(620, sy0 + 0.3)
    return {"x0": X(1411), "x1": X(1477), "z0": z0 + 0.08, "z1": z1 - 0.08, "y": sy0 + 0.28}


def linear(hex_color):
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


MINT = "#7df0c4"  # hq_city.py emissive("clock_digits", "#7df0c4", 5.0): the display's colour today
TODAY_STRENGTH = 4.35684  # clock_digits_001's EmissiveStrength in the live level (2026-09-18)


# ---------------------------------------------------------------- inside Unreal


def log(msg):
    unreal.log(f"AMN_CLOCK {msg}")


class Axes:
    """Blender metres -> Unreal, as build_hq_scene.py measured them from its marker cubes
    (axis_map.json). Without that file, look_hq_live.py's convention (the importer maps Blender +y
    to Unreal -y, centimetres), which the same measurement gave."""

    def __init__(self):
        if os.path.exists(AXIS_MAP):
            m = json.load(open(AXIS_MAP, "r", encoding="utf-8"))
            self.o, self.bo = m["origin_unreal"], m["origin_scene_m"]
            self.ex, self.ey, self.ez = m["ex"], m["ey"], m["ez"]
            self.source = AXIS_MAP
        else:
            self.o, self.bo = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            self.ex, self.ey, self.ez = [100.0, 0.0, 0.0], [0.0, -100.0, 0.0], [0.0, 0.0, 100.0]
            self.source = "look_hq_live.py convention (no axis_map.json)"

    def point(self, p):
        d = [p[i] - self.bo[i] for i in range(3)]
        return [self.o[k] + self.ex[k] * d[0] + self.ey[k] * d[1] + self.ez[k] * d[2] for k in range(3)]


def aligned_axis(vector):
    """(index, sign) of the Unreal axis a scene axis runs along. The material reads one world
    coordinate per direction (the path the haze material already uses), so the map must be
    axis-aligned: the importer's is (measured ex=(100,0,0), ey=(0,-100,0), ez=(0,0,100))."""
    n = math.sqrt(sum(c * c for c in vector))
    k = max(range(3), key=lambda i: abs(vector[i]))
    if abs(vector[k]) / n < 0.999:
        raise RuntimeError(f"scene axis {vector} is not aligned with an Unreal axis")
    return k, 1.0 if vector[k] > 0 else -1.0


def baked_digits(actors):
    """Today's digit mesh and its emission strength (its box no longer sets the size: at 37 x 13 px
    it is what made the first display too small to read)."""
    actor = actors.get(BAKED_LABEL)
    if actor is None:
        return None, None
    strength = None
    comp = actor.static_mesh_component
    mat = comp.get_material(0) if comp.get_num_materials() else None
    if isinstance(mat, unreal.MaterialInstanceConstant):
        try:
            strength = unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
        except Exception as err:
            log(f"baked digits' EmissiveStrength unreadable: {err}")
    return actor, strength


def _setting_value(value):
    if isinstance(value, tuple):
        enum, member = value
        return getattr(getattr(unreal, enum), member)
    return value


def import_atlas():
    if not os.path.exists(ATLAS_PNG):
        raise RuntimeError(f"{ATLAS_PNG} missing: run `py -3.11 clock_hq_live.py --atlas` first")
    task = unreal.AssetImportTask()
    task.filename = ATLAS_PNG
    task.destination_path = FOLDER
    task.destination_name = TEXTURE.rsplit("/", 1)[-1]
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(TEXTURE)
    if texture is None:
        raise RuntimeError(f"could not import {ATLAS_PNG}")
    # Every setting stated and read back: a setting that did not take stops the rebuild here,
    # rather than a face the Owner cannot read reaching the stream.
    wrong = []
    for prop, value in ATLAS_TEXTURE_SETTINGS.items():
        want = _setting_value(value)
        texture.set_editor_property(prop, want)
        got = texture.get_editor_property(prop)
        if got != want:
            wrong.append(f"{prop}={got} (wanted {want})")
    if wrong:
        raise RuntimeError(f"the clock atlas refused its settings: {'; '.join(wrong)}")
    unreal.EditorAssetLibrary.save_loaded_asset(texture)
    size = f"{texture.blueprint_get_size_x()}x{texture.blueprint_get_size_y()}"
    if size != f"{CELL_W * CELLS}x{CELL_H}":
        raise RuntimeError(f"the clock atlas imported at {size}, not {CELL_W * CELLS}x{CELL_H}")
    return texture


def digit_material(texture, strength, right, down, placement):
    """Masked at 0.5, unlit, two-sided: the segments glow, the clock box shows between them.
    Parameters: ClockOffsetS (the backend's), EmissiveStrength, and where the display box lies in
    world space (BoxOriginU/V in cm along the Unreal axes the scene's +x and -z run on,
    BoxScaleU/V)."""
    mel = unreal.MaterialEditingLibrary
    mat = None
    if unreal.EditorAssetLibrary.does_asset_exist(MATERIAL):
        mat = unreal.load_asset(MATERIAL)
        mel.delete_all_material_expressions(mat)
    if mat is None:
        folder, name = MATERIAL.rsplit("/", 1)
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("opacity_mask_clip_value", MASK_CLIP)
    mat.set_editor_property("two_sided", True)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", value)
        return n

    def along(axis, origin_name, scale_name, y):
        pos = node(unreal.MaterialExpressionWorldPosition, -1400, y)
        mask = node(unreal.MaterialExpressionComponentMask, -1200, y)
        for i, c in enumerate(("r", "g", "b", "a")):
            mask.set_editor_property(c, i == axis)
        mel.connect_material_expressions(pos, "", mask, "")
        rel = node(unreal.MaterialExpressionSubtract, -1000, y)
        mel.connect_material_expressions(mask, "", rel, "A")
        mel.connect_material_expressions(scalar(origin_name, float(placement[origin_name]), -1200, y + 120), "", rel, "B")
        out = node(unreal.MaterialExpressionMultiply, -800, y)
        mel.connect_material_expressions(rel, "", out, "A")
        mel.connect_material_expressions(scalar(scale_name, float(placement[scale_name]), -1000, y + 120), "", out, "B")
        return out

    u = along(right[0], "BoxOriginU", "BoxScaleU", -300)
    v = along(down[0], "BoxOriginV", "BoxScaleV", 0)
    time = node(unreal.MaterialExpressionTime, -800, 250)
    offset = scalar("ClockOffsetS", UNSYNCED_OFFSET, -800, 350)
    cells = node(unreal.MaterialExpressionConstant, -800, 450)
    cells.set_editor_property("r", float(CELLS))
    custom = node(unreal.MaterialExpressionCustom, -550, 0)
    custom.set_editor_property("code", DIGIT_HLSL)
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT2)
    custom.set_editor_property("description", "hh:mm from game time + ClockOffsetS")
    inputs = []
    for name in DIGIT_INPUTS:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", name)
        inputs.append(ci)
    custom.set_editor_property("inputs", inputs)
    for src, name in ((u, "U"), (v, "V"), (time, "T"), (offset, "Offset"), (cells, "Cells")):
        if not mel.connect_material_expressions(src, "", custom, name):
            raise RuntimeError(f"could not wire the clock's {name} input")

    sample = node(unreal.MaterialExpressionTextureSampleParameter2D, -300, 0)
    sample.set_editor_property("parameter_name", "DigitAtlas")
    sample.set_editor_property("texture", texture)
    # the sampler the texture's own settings need, read back from the texture (linear grey here)
    setting = texture.get_editor_property("compression_settings")
    compression = str(getattr(setting, "name", "") or str(setting).rsplit(".", 1)[-1].split(":")[0]).upper()
    sampler = sampler_type_for(compression, bool(texture.get_editor_property("srgb")))
    sample.set_editor_property("sampler_type", getattr(unreal.MaterialSamplerType, sampler))
    mel.connect_material_expressions(custom, "", sample, "UVs")
    mel.connect_material_property(sample, "R", unreal.MaterialProperty.MP_OPACITY_MASK)
    colour = node(unreal.MaterialExpressionVectorParameter, -300, 250)
    colour.set_editor_property("parameter_name", "DisplayColor")
    r, g, b = linear(MINT)
    colour.set_editor_property("default_value", unreal.LinearColor(r, g, b, 1.0))
    # every pixel the mask keeps is a lit segment, at full strength: an LED is on or off
    glow = node(unreal.MaterialExpressionMultiply, 50, 150)
    mel.connect_material_expressions(colour, "RGB", glow, "A")
    mel.connect_material_expressions(scalar("EmissiveStrength", strength, -100, 300), "", glow, "B")
    mel.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat, sampler


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if TAG in [str(t) for t in actor.get_editor_property("tags")]:
            eas.destroy_actor(actor)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    ax = Axes()
    right, down = aligned_axis(ax.ex), aligned_axis([-c for c in ax.ez])
    face = shelter_clock_face()
    baked, baked_strength = baked_digits(actors)
    box = display_box(face)
    rect = screen_rect(box, face["y"], 1920)
    strength = baked_strength if baked_strength else TODAY_STRENGTH
    if baked is not None:
        # hidden, not destroyed: the level keeps it, and showing it again is one allow-listed call
        baked.set_actor_hidden_in_game(True)
        baked.set_editor_property("tags", [unreal.Name(TAG + "_BAKED")])
    log(f"baked digits {'hidden' if baked else 'NOT FOUND'}; display box x {box['x0']:.3f}..{box['x1']:.3f} m, "
        f"z {box['z0']:.3f}..{box['z1']:.3f} m; at 1920: {rect['w']:.1f} x {rect['h']:.1f} px, glyphs "
        f"{rect['glyph_h_px']:.1f} px tall, mip {mip_level(rect):.2f}; axes {ax.source}")

    texture = import_atlas()
    top_left = ax.point((box["x0"], face["y"], box["z1"]))
    width_cm = (box["x1"] - box["x0"]) * math.sqrt(sum(c * c for c in ax.ex))
    height_cm = (box["z1"] - box["z0"]) * math.sqrt(sum(c * c for c in ax.ez))
    # the box's corner and size are the material's own defaults: one display, one set of numbers
    placement = {"BoxOriginU": top_left[right[0]], "BoxScaleU": right[1] / width_cm,
                 "BoxOriginV": top_left[down[0]], "BoxScaleV": down[1] / height_cm}
    mat, sampler = digit_material(texture, strength, right, down, placement)

    # The carrier: the engine's 1 m plane, lying in the face's plane over the whole face (the
    # material masks everything but the segments, so the clock box shows around them).
    centre = ax.point(((face["x0"] + face["x1"]) / 2.0, face["y"], (face["z0"] + face["z1"]) / 2.0))
    normal = [-c for c in ax.ey]  # towards the camera: the scene's -y
    rot = unreal.MathLibrary.make_rot_from_zx(unreal.Vector(*normal), unreal.Vector(*ax.ex))
    display = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*centre), rot)
    display.set_actor_label(LABEL)
    display.set_editor_property("tags", [unreal.Name(TAG)])
    comp = display.static_mesh_component
    comp.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Plane"))
    comp.set_material(0, mat)
    comp.set_cast_shadow(False)
    unit_x = math.sqrt(sum(c * c for c in ax.ex)) / 100.0
    unit_z = math.sqrt(sum(c * c for c in ax.ez)) / 100.0
    display.set_actor_scale3d(unreal.Vector((face["x1"] - face["x0"]) * unit_x, (face["z1"] - face["z0"]) * unit_z, 1.0))
    comp.set_mobility(unreal.ComponentMobility.STATIC)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory(FOLDER)
    log(f"display {display.get_path_name()} at ({centre[0]:.0f},{centre[1]:.0f},{centre[2]:.0f}), "
        f"{width_cm:.0f} x {height_cm:.0f} cm, #7df0c4 x{strength:.3f}; atlas {CELL_W * CELLS}x{CELL_H} "
        f"linear G8 trilinear, never streamed, sampler {sampler}, mask clip {MASK_CLIP}; ClockOffsetS "
        f"unsynced until the backend's first refresh (the face reads --:--)")


if unreal is not None:
    main()
elif __name__ == "__main__":
    if "--atlas" in sys.argv:
        i = sys.argv.index("--atlas")
        target = sys.argv[i + 1] if i + 1 < len(sys.argv) else ATLAS_PNG
        write_atlas(target)
    elif "--preview" in sys.argv:
        i = sys.argv.index("--preview")
        target = sys.argv[i + 1] if i + 1 < len(sys.argv) else "clock_preview.png"
        shown = sys.argv[i + 2] if i + 2 < len(sys.argv) else "--:--"
        write_preview(target, shown)
    else:
        print(__doc__)
