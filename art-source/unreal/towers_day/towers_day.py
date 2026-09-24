"""The skyline's towers by day, the pure part (no Unreal, no Blender; system Python 3.11 with numpy
and Pillow for the command line). Prepared 2026-09-24 for the next live-HQ window; nothing here has
run inside Unreal yet.

How the towers reach Unreal today (read from export_hq_scene.py, hq_city.py, look_hq_live.py):
every tower facade is a Blender windows_material. The export rebuilds each as a glTF material on two
tiling 384 x 384 textures, 24 x 24 window cells of 16 px on world-aligned UVs (the mesh's "bake"
UV layer): <name>_win_color.png (the dusk glass and wall colours, navy, linear albedo 0.005-0.03) and
<name>_win_emit.png (the lit windows). The import makes them glTF instances of the Interchange master
(M_Default); the look pass scales their EmissiveStrength (CITY 0.5) and the backend writes one
EmissiveFactor per component (1 at dusk, 0.06 at noon). Nothing else about them moves by day, so
at noon they stay navy (the dusk albedo) behind a haze at 0.55/0.385 opacity: "blue cardboard".

The Blender day plates solved the same towers (art-source/blender/hq/hq_day.py, commit 00d92ce) by
repainting each facade's two colours (FACADES: wall, glass), turning roofs (normal z > 0.5) into
concrete (TOWER_ROOF), switching emission off and thinning the haze. This module carries exactly
those numbers to Unreal, read from hq_day.py's source (never copied by hand), and adds what a live
picture needs and a still did not: which windows stay lit as the sun goes down.

What it makes, per facade, from the bake PNGs already on disk (no re-export):
  T_HQ_TowerMask_<name>.png  R = glass (255) or wall/mullion (0), G = the window's rank (0.02-0.95),
                             B = 255 where the dusk lights that window (for checking only)
The Unreal pass (towers_day_hq_live.py) samples it on the same UV as the facade textures and
paints, with TowerDaylight and WindowsOn at their defaults (0 and 1), exactly today's dusk.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import sys

CELLS = 24  # export_hq_scene.WINDOW_CELLS
CELL_PX = 16  # export_hq_scene.WINDOW_CELL_PX
# export_hq_scene.window_material: a one-texel mullion "down the middle of each window", at the cell
# columns where |x + 0.5/16 - 0.5| < 1/16, i.e. columns 7 and 8 of 16; it is wall-coloured, never lit
MULLION_COLUMNS = (7, 8)

# Ranks: every cell gets one, lit or not, inside [RANK_MIN, RANK_MAX]. With WindowsOn = 1 (the
# material's default and the backend's value at and below the reference dusk) the gate
# saturate((WindowsOn - rank) * GATE_SHARPNESS) is 1 for every rank and for every filtered blend of
# ranks, because (1 - 0.95) * 50 = 2.5 >= 1: the dusk is today's to the bit. With WindowsOn = 0 it is
# 0 everywhere (rank >= 0). Lit cells are spread evenly over (RANK_MIN, RANK_MAX], shuffled, so a
# WindowsOn between them lights that share of the dusk's lit windows.
RANK_MIN = 0.02
RANK_MAX = 0.95
GATE_SHARPNESS = 50.0
UNLIT_RANK = 0.0  # a cell the dusk never lights: its emission texture is 0 there whatever the gate

# The art director's reading of 2026-09-24 (real_sky/rebuild_2c/artdir): no lit windows while the sun
# is up, "only a few windows should light once elevation drops below about +5 deg", and the approved
# dusk at the reference (-2.5 deg). FEW is a judgement to be made by eye in the window (0.1-0.3).
WINDOWS_OFF_ABOVE = 5.0
WINDOWS_FEW_AT = 0.0
WINDOWS_FEW = 0.2
REFERENCE_DUSK_ELEVATION = -2.5  # backend/app/office/world.py
DAY_FULL_ELEVATION = 6.0  # backend/app/office/scene_params.py

# Rec. 709 luminance of linear RGB
LUMA = (0.2126, 0.7152, 0.0722)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get(
    "AMN_REPO", r"E:\AI Acency\Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP"
)
HQ_DAY = os.path.join(REPO, "art-source", "blender", "hq", "hq_day.py")
BAKE_DIR = os.path.join(REPO, "art-source", "unreal", "bake")
LEAVES_DIR = os.path.join(REPO, "art-source", "unreal", "leaves", "generated")


# ---------------------------------------------------------------- colour helpers
def to_linear(byte: float) -> float:
    c = byte / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_linear(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    return tuple(to_linear(int(h[i : i + 2], 16)) for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(rgb) -> float:
    return sum(c * k for c, k in zip(rgb[:3], LUMA, strict=True))


def smoothstep(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


# ---------------------------------------------------------------- hq_day.py, read without Blender
def hq_day_constants(path: str = HQ_DAY) -> dict:
    """The day variant's module-level constants, read from its source with ast (hq_day.py imports
    bpy, so it cannot be imported here). Only literal assignments are taken."""
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    for key in ("FACADES", "TOWER_ROOF", "GLASS_METALLIC", "SURFACES"):
        if key not in out:
            raise KeyError(f"{path} has no literal {key}: the day palette cannot be read")
    return out


def facade_day(name: str, consts: dict) -> dict:
    """What M_HQ_TowerDay paints on one facade by day, from hq_day.py: the wall and the glass in
    their day colours (linear), a concrete roof, and the day's metal and roughness (hq_day._facade
    sets metallic GLASS_METALLIC and roughness 0.22 on the whole facade)."""
    wall, glass = consts["FACADES"][name]
    return {
        "DayWall": hex_linear(wall),
        "DayGlass": hex_linear(glass),
        "TowerRoof": hex_linear(consts["TOWER_ROOF"]),
        "DayMetallic": float(consts["GLASS_METALLIC"]),
        "DayRoughness": 0.22,  # hq_day._facade: b.inputs["Roughness"].default_value = 0.22
    }


# ---------------------------------------------------------------- the elevation curves
def day_weight(elevation: float) -> float:
    """scene_params.day_weight: 0 at and below the reference dusk, 1 from DAY_FULL_ELEVATION up."""
    return smoothstep(REFERENCE_DUSK_ELEVATION, DAY_FULL_ELEVATION, elevation)


def windows_share(
    elevation: float,
    few: float = WINDOWS_FEW,
    off_above: float = WINDOWS_OFF_ABOVE,
    few_at: float = WINDOWS_FEW_AT,
    morning: bool = False,
    morning_share: float = 1.0,
) -> float:
    """The share of the dusk's lit windows that are lit at this real solar elevation.

    None while the sun stands above off_above; a few (0 -> few) as it sinks to few_at; from few to
    all of them between few_at and the reference dusk; all of them at and below the reference, so
    the approved dusk and the night are today's. morning_share (an Owner decision, 1 = off) scales
    the morning side only: at 06:55 an office city has fewer windows lit than at 19:19."""
    if elevation >= off_above:
        share = 0.0
    elif elevation >= few_at:
        share = few * smoothstep(off_above, few_at, elevation)
    elif elevation > REFERENCE_DUSK_ELEVATION:
        share = mix(few, 1.0, smoothstep(few_at, REFERENCE_DUSK_ELEVATION, elevation))
    else:
        share = 1.0
    return share * (morning_share if morning else 1.0)


def windows_on(share: float) -> float:
    """The WindowsOn parameter that lights `share` of the lit windows: lit ranks are spread evenly
    over (RANK_MIN, RANK_MAX], so this is the rank of the last window to light, plus half a step.
    1.0 (all, exactly today's dusk) for share >= 1, 0.0 (none) for share <= 0."""
    if share >= 1.0:
        return 1.0
    if share <= 0.0:
        return 0.0
    return RANK_MIN + (RANK_MAX - RANK_MIN) * share


def gate(windows_on_value: float, rank: float) -> float:
    """What the material multiplies a window's emission by (towers_day_hq_live.py builds the same
    nodes): saturate((WindowsOn - rank) * GATE_SHARPNESS)."""
    return min(1.0, max(0.0, (windows_on_value - rank) * GATE_SHARPNESS))


def lit_ranks(n: int, seed: int) -> list[float]:
    """n lit windows' ranks: evenly spread over (RANK_MIN, RANK_MAX], shuffled with the seed."""
    import random

    ranks = [RANK_MIN + (RANK_MAX - RANK_MIN) * (i + 1) / n for i in range(n)]
    random.Random(seed).shuffle(ranks)
    return ranks


# ---------------------------------------------------------------- what the material paints
def day_base(orig_rgb, mask: float, roof: float, params: dict, tower_daylight: float):
    """Base colour of the extended master: lerp(original, day, TowerDaylight), the day colour being
    lerp(DayWall, DayGlass, mask), a concrete roof where roof = 1. TowerDaylight 0 gives orig."""
    day = [mix(w, g, mask) for w, g in zip(params["DayWall"], params["DayGlass"], strict=True)]
    day = [mix(d, r, roof) for d, r in zip(day, params["TowerRoof"], strict=True)]
    return tuple(o + (d - o) * tower_daylight for o, d in zip(orig_rgb, day, strict=True))


def roof_weight(normal_z: float) -> float:
    """saturate((normal.z - 0.5) * 20): 1 on a roof, 0 on a wall (hq_day._facade: z > 0.5)."""
    return min(1.0, max(0.0, (normal_z - 0.5) * 20.0))


# ---------------------------------------------------------------- the haze by day (hq_day._haze)
def haze_day(consts_source: str = HQ_DAY) -> dict:
    """The day haze of the Blender day plates, read from hq_day.apply's two _haze calls: near
    ("#d2e0ef", strength 1.0, alpha x0.3) and far ("#c3d5ea", strength 1.05, alpha x0.62)."""
    tree = ast.parse(open(consts_source, encoding="utf-8").read())

    def haze_call(stmts):
        for stmt in stmts:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_haze" and len(node.args) == 4:
                    colour, strength, alpha = (ast.literal_eval(a) for a in node.args[1:])
                    return (colour, float(strength), float(alpha))
        return None

    far = near = None
    for node in ast.walk(tree):
        # apply(): if name.startswith("haze_far"): _haze(far...) else: _haze(near...)
        if isinstance(node, ast.If) and "haze_far" in ast.unparse(node.test):
            far, near = haze_call(node.body), haze_call(node.orelse)
    if far is None or near is None:
        raise ValueError(f"no haze_far / near _haze pair in {consts_source}")
    return {
        "near": {"colour": hex_linear(near[0]), "strength": near[1], "alpha_share": near[2]},
        "far": {"colour": hex_linear(far[0]), "strength": far[1], "alpha_share": far[2]},
    }


def haze_values(label: str, day: float, dusk_colour, dusk_opacity: float, dim: float, haze=None) -> dict:
    """One skyline haze plane: its colour from the dusk one (x dim below the reference, as
    scene_params does) to the Blender day one, and its opacity from the dusk one to the day share
    of it. At day 0 both are exactly scene_params' values today."""
    haze = haze or haze_day()
    side = haze["far"] if "_far_" in label else haze["near"]
    day_colour = tuple(c * side["strength"] for c in side["colour"])
    colour = tuple(mix(c * dim, d, day) for c, d in zip(dusk_colour, day_colour, strict=True))
    return {"HazeColor": colour, "Opacity": dusk_opacity * mix(1.0, side["alpha_share"], day)}


# ---------------------------------------------------------------- the street trees by day
def leaf_day_gain(green_png: str, pack_png: str) -> float:
    """The factor that brings the darkened green leaf texture (T_HQ_Leaves_Green, value 0.4 for the
    dusk) back to the pack's own leaf albedo (T_Foliage_Leaves_D) by day: the ratio of their mean
    linear luminance over the opaque texels. Measured 2026-09-24: 0.0212 and 0.0997, about 4.7."""
    import numpy as np
    from PIL import Image

    def mean_lum(path):
        a = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64) / 255.0
        opaque = a[..., 3] > 0.5
        rgb = a[..., :3][opaque]
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        return float((lin @ np.array(LUMA)).mean())

    return mean_lum(pack_png) / mean_lum(green_png)


# ---------------------------------------------------------------- the mask and rank texture
def analyse_facade(color, emit):
    """One facade's two exported textures (uint8 H x W x 3 arrays) -> its glass and wall colours,
    the glass mask (H x W bool) and the dusk's lit cells (CELLS x CELLS bool).

    The wall colour is read on the mullion (every cell's columns 7-8 are wall by construction); the
    glass is the texture's other colour. Refuses a texture that is not the export's 24 x 24 grid of
    two colours."""
    import numpy as np

    h, w = color.shape[:2]
    if (h, w) != (CELLS * CELL_PX, CELLS * CELL_PX) or emit.shape[:2] != (h, w):
        raise ValueError(f"not a {CELLS}x{CELLS} window grid of {CELL_PX} px: {color.shape}, {emit.shape}")
    flat = color.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    if len(colours) != 2:
        raise ValueError(f"expected exactly two colours (glass, wall), found {len(colours)}")
    wall = color[CELL_PX // 2, MULLION_COLUMNS[0]]
    if not (color[:, MULLION_COLUMNS[0] :: CELL_PX] == wall).all():
        raise ValueError("the mullion columns are not one colour: not the export's window grid")
    glass = colours[0] if (colours[0] != wall).any() else colours[1]
    mask = (color == glass).all(axis=-1)
    lit_px = emit.max(axis=-1) > 0
    if (lit_px & ~mask).any():
        raise ValueError("emission outside the glass: not the export's window grid")
    lit_cells = lit_px.reshape(CELLS, CELL_PX, CELLS, CELL_PX).any(axis=(1, 3))
    return {"glass": tuple(int(c) for c in glass), "wall": tuple(int(c) for c in wall), "mask": mask, "lit_cells": lit_cells}


def mask_rank_texture(analysis, seed: int):
    """R glass mask, G rank, B dusk-lit flag, as uint8 H x W x 3. Every pixel of a cell carries the
    cell's rank, so filtering never mixes ranks inside a window."""
    import numpy as np

    lit = analysis["lit_cells"]
    ranks = np.full((CELLS, CELLS), UNLIT_RANK, dtype=np.float64)
    idx = np.argwhere(lit)
    for (cy, cx), r in zip(idx, lit_ranks(len(idx), seed), strict=True):
        ranks[cy, cx] = r
    rank_px = np.repeat(np.repeat(ranks, CELL_PX, axis=0), CELL_PX, axis=1)
    lit_px = np.repeat(np.repeat(lit, CELL_PX, axis=0), CELL_PX, axis=1)
    out = np.zeros(analysis["mask"].shape + (3,), dtype=np.uint8)
    out[..., 0] = analysis["mask"] * 255
    # floor, not round: a stored rank is never above RANK_MAX, so the dusk gate stays 1
    out[..., 1] = np.floor(rank_px * 255.0).astype(np.uint8)
    out[..., 2] = lit_px * 255
    return out


def stored_rank(byte: int) -> float:
    return byte / 255.0


def main(argv=None) -> int:
    import numpy as np
    from PIL import Image

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--bake", default=BAKE_DIR)
    p.add_argument("--out", default=os.path.join(HERE, "textures"))
    p.add_argument("--hq-day", default=HQ_DAY)
    a = p.parse_args(argv)
    consts = hq_day_constants(a.hq_day)
    os.makedirs(a.out, exist_ok=True)
    facts = {"source": {"hq_day": a.hq_day, "bake": a.bake}, "rank": {"min": RANK_MIN, "max": RANK_MAX, "sharpness": GATE_SHARPNESS}, "facades": {}}
    for i, name in enumerate(sorted(consts["FACADES"])):
        cpath = os.path.join(a.bake, f"{name}_win_color.png")
        epath = os.path.join(a.bake, f"{name}_win_emit.png")
        if not (os.path.exists(cpath) and os.path.exists(epath)):
            print(f"AMN_TOWERS {name}: no bake on disk ({cpath}), skipped")
            continue
        color = np.asarray(Image.open(cpath).convert("RGB"))
        emit = np.asarray(Image.open(epath).convert("RGB"))
        info = analyse_facade(color, emit)
        tex = mask_rank_texture(info, seed=1000 + i)
        out = os.path.join(a.out, f"T_HQ_TowerMask_{name}.png")
        Image.fromarray(tex, "RGB").save(out)
        facts["facades"][name] = {
            "texture": out,
            "glass_srgb": info["glass"],
            "wall_srgb": info["wall"],
            "glass_share": round(float(info["mask"].mean()), 4),
            "lit_windows": int(info["lit_cells"].sum()),
            "windows": CELLS * CELLS,
            **{k: v for k, v in facade_day(name, consts).items()},
        }
        print(f"AMN_TOWERS {name}: glass {info['glass']} wall {info['wall']} lit {int(info['lit_cells'].sum())}/{CELLS * CELLS} -> {out}")
    green = os.path.join(LEAVES_DIR, "T_HQ_Leaves_Green.png")
    pack = os.path.join(LEAVES_DIR, "T_Foliage_Leaves_D.png")
    if os.path.exists(green) and os.path.exists(pack):
        facts["leaf_day_gain"] = round(leaf_day_gain(green, pack), 3)
    facts["haze_day"] = haze_day(a.hq_day)
    facts["surfaces_day"] = {k: hex_linear(v) for k, v in consts["SURFACES"].items()}
    with open(os.path.join(a.out, "towers_day.json"), "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=1)
    print(f"AMN_TOWERS {len(facts['facades'])} facades, leaf day gain {facts.get('leaf_day_gain')}")
    return 0 if facts["facades"] else 1


if __name__ == "__main__":
    sys.exit(main())
