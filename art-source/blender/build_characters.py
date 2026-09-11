"""
Renders the character parts in characters.PARTS to frontend/public/assets/sprites/characters/
in KEY colours (no outline, no shadow: the renderer composites the parts, recolours them per
agent and outlines the result). Writes parts.json with sizes and anchors, plus a 6x contact
sheet with a sample recolour to output/art/characters_contact.png.

Run: "<blender>" -b --python art-source/blender/build_characters.py
"""

from __future__ import annotations

import json
import os
import sys
import time

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pixelart as pa  # noqa: E402
import characters as ch  # noqa: E402

OUT_DIR = os.path.join(pa.ROOT, "frontend", "public", "assets", "sprites", "characters")
REVIEW_DIR = os.path.join(pa.ROOT, "output", "art")


def render_part(name: str) -> tuple[dict, np.ndarray]:
    builder_fn, frame, opts = ch.PARTS[name]
    x0, y0, w, h = frame
    pa.reset_scene()
    pa.add_lights()
    cam = pa.Camera(w, h, origin_x=x0, origin_y=y0)
    cam.build()
    b = pa.Builder()
    m = ch.KeyMats()
    points = builder_fn(b, m, **opts) or {}
    tmp = os.path.join(REVIEW_DIR, "tmp", name + ".png")
    pa.render_to(tmp)
    img = pa.read_png(tmp)
    os.remove(tmp)
    sprite = pa.snap_to_palette(img, list(dict.fromkeys(m.used)))
    # Keep the full frame (parts must share one coordinate system); anchor = screen (0, 0).
    ax, ay = cam.sprite_px(0, 0)
    entry = {"file": f"{name}.png", "w": int(w), "h": int(h), "anchor": {"x": int(ax), "y": int(ay)}, "points": {}}
    for key, val in points.items():
        if len(val) == 4:
            sx, sy, pw, ph = val
            px, py = cam.sprite_px(sx, sy + ph)
            entry["points"][key] = {"x": int(px), "y": int(py), "w": int(pw), "h": int(ph)}
    pa.write_png(os.path.join(OUT_DIR, entry["file"]), sprite)
    return entry, sprite


def recolour(sprite: np.ndarray, palette: dict, look: dict) -> np.ndarray:
    """Sample recolour for the contact sheet, mirroring what the renderer does."""
    out = sprite.copy()
    rgb = out[..., :3].astype(np.int32)
    mapping = {}
    for kind, ramp in (("skin", look["skin"]), ("hair", look["hair"]), ("garment", look["garment"]),
                       ("second", look["second"]), ("trim", look["trim"])):
        for i, key in enumerate(pa.KEY_RAMPS[kind]):
            mapping[key] = ramp[i]
    mapping[ch.EYE_WHITE] = "#f6f2ea"
    mapping[ch.EYE_DARK] = palette["ambient"]["shadow"]
    for src, dst in mapping.items():
        s = pa.hex_list_to_array([src])[0]
        d = pa.hex_list_to_array([dst])[0]
        mask = (rgb == s).all(axis=2) & (out[..., 3] > 0)
        out[..., :3][mask] = d.astype(np.uint8)
    return out


def composite(parts: dict, names: list[str], offsets: dict | None = None) -> np.ndarray:
    """Overlay parts (all share the anchor) in order; returns an image the size of the largest."""
    offsets = offsets or {}
    H = max(parts[n][0]["h"] + parts[n][0]["anchor"]["y"] * 0 for n in names)
    top = max(parts[n][0]["anchor"]["y"] for n in names)
    bottom = max(parts[n][0]["h"] - parts[n][0]["anchor"]["y"] for n in names)
    left = max(parts[n][0]["anchor"]["x"] for n in names)
    right = max(parts[n][0]["w"] - parts[n][0]["anchor"]["x"] for n in names)
    canvas = np.zeros((top + bottom, left + right, 4), dtype=np.uint8)
    for n in names:
        e, img = parts[n]
        dx, dy = offsets.get(n, (0, 0))
        ox, oy = left - e["anchor"]["x"] + dx, top - e["anchor"]["y"] + dy
        region = canvas[oy:oy + e["h"], ox:ox + e["w"]]
        mask = img[..., 3] > 0
        region[mask] = img[mask]
    return canvas, (left, top)


def main() -> None:
    palette = pa.load_palette()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.join(REVIEW_DIR, "tmp"), exist_ok=True)
    parts = {}
    t0 = time.time()
    for name in ch.PARTS:
        entry, sprite = render_part(name)
        parts[name] = (entry, sprite)
        print(f"PART {name}: {entry['w']}x{entry['h']} anchor=({entry['anchor']['x']},{entry['anchor']['y']}) colors={len(pa.unique_colors(sprite))}")
    with open(os.path.join(OUT_DIR, "parts.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "keys": pa.KEY_RAMPS, "eye_white": ch.EYE_WHITE, "eye_dark": ch.EYE_DARK,
                   "parts": {n: e for n, (e, _) in parts.items()}}, fh, indent=2)

    # Contact sheet: six sample looks (skin/hair/garment from the palette), various parts.
    looks = []
    cloth = palette["cloth"]
    combos = [("navy", "white", "mustard", "short", "square"), ("white", "teal", "teal", "bob", None),
              ("olive", "cream", "olive", "curly", "round"), ("rust", "cream", "rust", "long", None),
              ("plum", "wine", "plum", "fade", None), ("charcoal", "sky", "sky", "bun", "square")]
    for i, (g, s, t, hair, glasses) in enumerate(combos):
        looks.append({"skin": palette["skin"][i % len(palette["skin"])], "hair": palette["hair"][(i * 3) % len(palette["hair"])],
                      "garment": cloth[g], "second": cloth[s], "trim": cloth[t], "hair_style": hair, "glasses": glasses})
    cells = []
    poses = [("open", "rest"), ("open", "type_a"), ("blink", "type_b"), ("open", "chin"), ("sleep", "sleep"), ("talk", "rest")]
    for look, (face, pose) in zip(looks, poses):
        names = [f"body_{face}", f"hair_{look['hair_style']}"]
        offsets = {}
        if face == "sleep":
            offsets[f"hair_{look['hair_style']}"] = (0, 3)
        if look["glasses"]:
            names.append(f"glasses_{look['glasses']}")
            if face == "sleep":
                offsets[f"glasses_{look['glasses']}"] = (0, 3)
        if look["hair_style"] == "fade":
            names.append("headset")
        body, (bl, bt) = composite(parts, names, offsets)
        body = recolour(body, palette, look)
        body = pa.outline(body, palette["ambient"]["shadow"])
        hands, (hl, ht) = composite(parts, [f"hands_{pose}"])
        hands = pa.outline(recolour(hands, palette, look), palette["ambient"]["shadow"])
        # Draw over a desk-coloured band so the occlusion reads: body, desk band, hands.
        W, H = 44, 64
        cell = np.zeros((H, W, 4), dtype=np.uint8)
        cell[..., :3] = (0x2c, 0x34, 0x52)
        cell[..., 3] = 255
        cx, desk_y = W // 2, 46
        def paste(img, ax, ay):
            h, w = img.shape[:2]
            x0, y0 = cx - ax, desk_y - ay
            for yy in range(h):
                for xx in range(w):
                    if img[yy, xx, 3] > 0 and 0 <= y0 + yy < H and 0 <= x0 + xx < W:
                        cell[y0 + yy, x0 + xx] = img[yy, xx]
        paste(body, bl, bt)
        cell[desk_y:desk_y + 9, 4:W - 4, :3] = pa.hex_list_to_array([palette["materials"]["walnut"][3]])[0]
        cell[desk_y, 4:W - 4, :3] = pa.hex_list_to_array([palette["materials"]["walnut"][4]])[0]
        paste(hands, hl, ht)
        cells.append(cell)
    sheet = np.concatenate(cells, axis=1)
    pa.write_png(os.path.join(REVIEW_DIR, "characters_contact.png"), pa.scale_nearest(sheet, 6))
    print(f"DONE {len(parts)} parts in {time.time() - t0:.1f}s -> {OUT_DIR}")


main()
