"""
Renders every prop in props.PROPS to frontend/public/assets/pixel/office/<name>.png (+ a
cast-shadow layer <name>_shadow.png) and writes atlas.json with sizes, anchors and named
points. Also writes a 4x contact sheet to output/art/props_contact.png for review.

Run (from the repository root):
  "<blender>" -b --python art-source/blender/build_props.py -- [name ...]
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pixelart as pa  # noqa: E402
import props  # noqa: E402
import environment  # noqa: E402

ROOT = pa.ROOT
OUT_DIR = os.path.join(ROOT, "frontend", "public", "assets", "pixel", "office")
ENV_DIR = os.path.join(ROOT, "frontend", "public", "assets", "environment")
ALL = {**{n: (*v, "props") for n, v in props.PROPS.items()},
       **{n: (*v, "environment") for n, v in environment.ENVIRONMENT.items()}}
REVIEW_DIR = os.path.join(ROOT, "output", "art")
TMP = os.path.join(REVIEW_DIR, "tmp")


def render_prop(name: str, palette: dict) -> dict:
    builder_fn, kind, frame, opts, group = ALL[name]
    opts = dict(opts)
    if "dept_key" in opts:
        opts["dept"] = palette["departments"][opts.pop("dept_key")]
    x0, y0, w, h = frame
    pa.reset_scene()
    pa.add_lights()
    cam = pa.Camera(w, h, origin_x=x0, origin_y=y0)
    cam.build()
    b = pa.Builder()
    m = props.Mats(palette)
    rnd = random.Random(hash(name) & 0xFFFF)
    points = builder_fn(b, m, rnd, **opts) or {}
    catchers = b.catcher(x0 - 40, x0 + w + 40)
    allowed = list(dict.fromkeys(m.used))
    os.makedirs(TMP, exist_ok=True)
    tile = group == "environment"
    sprite, shadow = pa.render_layers(b.objects, catchers, os.path.join(TMP, name), allowed,
                                      None if tile else palette["ambient"]["shadow"], palette["ambient"]["shadow"])
    if tile:
        # Tiles keep their exact frame (they repeat edge to edge) and carry no cast shadow.
        top, bottom, left, right = 0, h, 0, w
        shadow = np.zeros_like(shadow)
    else:
        # Trim to the union of sprite and shadow, keeping a 1 px margin.
        union = (sprite[..., 3] > 0) | (shadow[..., 3] > 0)
        ys, xs = np.where(union)
        top, bottom = max(0, ys.min() - 1), min(h, ys.max() + 2)
        left, right = max(0, xs.min() - 1), min(w, xs.max() + 2)
    sprite, shadow = sprite[top:bottom, left:right], shadow[top:bottom, left:right]
    out_dir = ENV_DIR if tile else OUT_DIR
    rel = "environment" if tile else "pixel/office"
    anchor_screen = (0, pa.FLOOR_DEPTH_PX) if kind == "floor" else (0, 0)
    ax, ay = cam.sprite_px(*anchor_screen)
    entry = {
        "file": f"{name}.png",
        "path": f"{rel}/{name}.png",
        "shadow": f"{name}_shadow.png" if shadow[..., 3].any() else None,
        "shadow_path": f"{rel}/{name}_shadow.png" if shadow[..., 3].any() else None,
        "w": int(right - left), "h": int(bottom - top),
        "anchor": {"x": int(ax - left), "y": int(ay - top)},
        "kind": kind,
        "points": {},
    }
    for key, val in points.items():
        if len(val) == 4:
            sx, sy, pw, ph = val
            px, py = cam.sprite_px(sx, sy + ph)   # top-left of the rect on screen
            entry["points"][key] = {"x": int(px - left), "y": int(py - top), "w": int(pw), "h": int(ph)}
        else:
            px, py = cam.sprite_px(*val)
            entry["points"][key] = {"x": int(px - left), "y": int(py - top)}
    pa.write_png(os.path.join(out_dir, entry["file"]), sprite)
    if entry["shadow"]:
        pa.write_png(os.path.join(out_dir, entry["shadow"]), shadow)
    return entry, sprite, shadow


def contact_sheet(entries: dict, sprites: dict, palette: dict, scale: int = 4) -> None:
    """Sprites over their shadows on a neutral floor band, 4x, for review."""
    pad = 6
    widths = [e["w"] for e in entries.values()]
    heights = [e["h"] for e in entries.values()]
    cols = 6
    cell_w, cell_h = max(widths) + pad, max(heights) + pad
    rows = (len(entries) + cols - 1) // cols
    W, H = cols * cell_w, rows * cell_h
    canvas = np.zeros((H, W, 4), dtype=np.uint8)
    bg = [int(c, 16) for c in ("2c", "34", "52")]
    canvas[..., :3] = bg
    canvas[..., 3] = 255
    sh = [int(palette["ambient"]["shadow"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    for i, (name, e) in enumerate(entries.items()):
        cx, cy = (i % cols) * cell_w + pad // 2, (i // cols) * cell_h + pad // 2
        sprite, shadow = sprites[name]
        h, w = sprite.shape[:2]
        region = canvas[cy:cy + h, cx:cx + w]
        smask = shadow[..., 3] > 0
        region[smask, :3] = (region[smask, :3] * (1 - pa.SHADOW_ALPHA) + np.array(sh) * pa.SHADOW_ALPHA).astype(np.uint8)
        pmask = sprite[..., 3] > 0
        region[pmask] = sprite[pmask]
    os.makedirs(REVIEW_DIR, exist_ok=True)
    pa.write_png(os.path.join(REVIEW_DIR, "props_contact.png"), pa.scale_nearest(canvas, scale))


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    names = args or list(ALL.keys())
    palette = pa.load_palette()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ENV_DIR, exist_ok=True)
    atlas_path = os.path.join(OUT_DIR, "atlas.json")
    atlas = {"version": 1, "sprites": {}}
    if os.path.exists(atlas_path):
        with open(atlas_path, "r", encoding="utf-8") as fh:
            atlas = json.load(fh)
    sprites = {}
    t0 = time.time()
    for name in names:
        t = time.time()
        entry, sprite, shadow = render_prop(name, palette)
        atlas["sprites"][name] = entry
        sprites[name] = (sprite, shadow)
        print(f"PROP {name}: {entry['w']}x{entry['h']} anchor=({entry['anchor']['x']},{entry['anchor']['y']}) "
              f"colors={len(pa.unique_colors(sprite))} {time.time() - t:.1f}s")
    atlas["shadow_alpha"] = pa.SHADOW_ALPHA
    atlas["outline"] = palette["ambient"]["shadow"]
    with open(atlas_path, "w", encoding="utf-8") as fh:
        json.dump(atlas, fh, indent=2)
    contact_sheet({n: atlas["sprites"][n] for n in sprites}, sprites, palette)
    print(f"DONE {len(names)} props in {time.time() - t0:.1f}s -> {OUT_DIR}")


main()
