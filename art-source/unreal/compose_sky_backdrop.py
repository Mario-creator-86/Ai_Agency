"""Compose the dusk sky backdrop for the Unreal scene: the same sky the web page draws at the light
of the Owner's picture (frontend/src/hq_time.js skyStops + hq_sky.js afterglow and painted cloud
layers), as one image.

  python art-source/unreal/compose_sky_backdrop.py [--out art-source/unreal/sky_dusk.png] [--scale 2]

An orthographic camera cannot see Unreal's sky atmosphere properly, so build_hq_scene.py shows this
image on an unlit backdrop behind the city. Generated, ignored by Git.
"""

import argparse
import math
import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SKY_DIR = os.path.join(ROOT, "frontend", "public", "assets", "hq", "sky")
W, H, HORIZON = 1600, 840, 350

# hq_time.js SKY and skyStops positions
SKY = {
    "night": ["#070b1a", "#0f1630", "#1a2244", "#232a4a"],
    "dusk": ["#1b2644", "#3b4a7c", "#d0806c", "#7a5c70"],
    "day": ["#3f78c8", "#79a9e0", "#cfe2f3", "#b9cde2"],
}
POSITIONS = [0.0, 0.24, 0.4, 0.62]
ELEVATION = -2.5  # hq_time.js REFERENCE_DUSK_ELEVATION


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], np.float32)


def mix(a, b, t):
    return a + (b - a) * min(1.0, max(0.0, t))


def radial(w, h, cx, cy, radius, y_scale, stops):
    """Premultiplied RGBA of a radial gradient squashed vertically, as the canvas's ctx.scale does."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xs - cx) ** 2 + ((ys - cy) / y_scale) ** 2) / radius
    out = np.zeros((h, w, 4), np.float32)
    for (p0, c0, a0), (p1, c1, a1) in zip(stops, stops[1:]):
        m = (d >= p0) & (d <= p1)
        t = ((d[m] - p0) / (p1 - p0))[:, None]
        col = np.array(c0, np.float32) * (1 - t) + np.array(c1, np.float32) * t
        alpha = a0 * (1 - t[:, 0]) + a1 * t[:, 0]
        out[m, :3] = col
        out[m, 3] = alpha
    return out


def over(base, layer_rgb, alpha):
    a = alpha[..., None]
    return base * (1 - a) + layer_rgb * a


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(HERE, "sky_dusk.png"))
    p.add_argument("--scale", type=int, default=2)
    # Next to the Owner's picture the composed sky comes out warmer: over its upper half the live
    # frame reads about 7 short of green and 12 short of blue (the picture 77, 77, 105 against
    # 79, 69, 93). These gains close that without touching the page's own palette.
    p.add_argument("--tint", default="1.0,1.10,1.14", help="r,g,b gains applied to the composed sky")
    a = p.parse_args()
    daylight = smoothstep(-8, 7, ELEVATION)
    dusk = math.exp(-(((ELEVATION - 1) / 6.5) ** 2))

    stops = []
    for i, pos in enumerate(POSITIONS):
        base = mix(rgb(SKY["night"][i]), rgb(SKY["day"][i]), daylight)
        stops.append((pos, mix(base, rgb(SKY["dusk"][i]), dusk * 0.95)))
    rows = np.linspace(0, 1, H, dtype=np.float32)
    column = np.zeros((H, 3), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (rows >= p0) & (rows <= p1)
        t = ((rows[m] - p0) / (p1 - p0))[:, None]
        column[m] = c0 * (1 - t) + c1 * t
    column[rows > POSITIONS[-1]] = stops[-1][1]
    sky = np.repeat(column[:, None, :], W, axis=1)

    glow = dusk
    warm = radial(W, H, 0, HORIZON, W * 0.5, 0.28, [(0.0, (250, 160, 110), 0.5 * glow), (0.5, (214, 120, 110), 0.22 * glow), (1.0, (214, 120, 110), 0.0)])
    sky = over(sky, warm[..., :3], warm[..., 3])
    cool = radial(W, H, W * 0.86, 20, W * 0.26, 0.55, [(0.0, (100, 146, 220), 0.7 * glow), (1.0, (100, 146, 220), 0.0)])
    sky = over(sky, cool[..., :3], cool[..., 3])

    # hq_sky.js cloudLayerWeights
    day_w = daylight * (1 - dusk)
    night_w = (1 - daylight) * (1 - dusk)
    total = dusk + day_w + night_w
    for look, weight in (("night", night_w / total), ("day", day_w / total), ("dusk", dusk / total)):
        path = os.path.join(SKY_DIR, f"clouds_{look}.webp")
        if weight < 0.01 or not os.path.exists(path):
            continue
        layer = Image.open(path).convert("RGBA")
        lh = round(layer.height * W / layer.width)
        arr = np.asarray(layer.resize((W, lh), Image.LANCZOS), np.float32)
        region = sky[:lh]
        sky[:lh] = over(region, arr[..., :3], arr[..., 3] / 255.0 * weight * 0.9)

    sky = sky * np.array([float(v) for v in a.tint.split(",")], np.float32)
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8), "RGB")
    img = img.resize((W * a.scale, H * a.scale), Image.LANCZOS)
    img.save(a.out)
    print(f"AMN_SKY daylight={daylight:.3f} dusk={dusk:.3f} tint={a.tint} -> {a.out} {img.size}")


main()
