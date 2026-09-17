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
from PIL import Image, ImageFilter

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
    # Raised to 1.18, 1.20 with the clouds at half (below): a third of the plate's light was in the
    # painted layer, and without it the sky falls the other way. Over the frame's left sky (columns
    # 20-390, rows 85-175) the halved plate would reach 56, 68, 113 where the picture is 62, 75, 117;
    # these gains put it on 61, 75, 117.
    p.add_argument("--tint", default="1.0,1.12,1.10", help="r,g,b gains applied to the composed sky")
    # The painted cloud layer is drawn for the page's own sky, at the page's width. Laid across
    # the plate it repeats as a fine mackerel pattern, where the picture has a few large, soft
    # bands. Zooming into the middle of the layer makes its clouds that much larger.
    # Zoomed further the bands do get larger, but the crop lands on a brighter part of the texture
    # and the sky low on the right went 10 out to 40 out; 1.7 stays.
    p.add_argument("--cloud-zoom", type=float, default=1.4)
    # The layer is drawn for the page, where it carries the whole look; over the plate it reads as
    # a cream mackerel where the picture has soft bands of a deeper blue. Over the frame's left sky
    # it takes the plate to 92, 88, 112 against the picture's 62, 75, 117 - 30 over in red and 5
    # short of blue - and its spread there is 24 in red against 6 in blue, where the picture's
    # varies by about as much in every channel. At half the plate is 74, 82, 118, the bands are
    # still there, and the picture's own tone comes back through them.
    p.add_argument("--cloud-strength", type=float, default=0.32, help="opacity of the painted cloud layers")
    # The picture's clouds are soft bands; the painted layer is sharp at any zoom, and sharp clouds put
    # pixel noise on a sky the picture keeps smooth (its region 5.1 -> 12.4 with the band means closer).
    p.add_argument("--cloud-blur", type=float, default=3.0, help="Gaussian blur of the cloud layer, in plate pixels")
    # the picture's clouds are pink-mauve, lit from the sunset; the painted layer is neutral
    p.add_argument("--cloud-tint", default="1.16,0.96,0.93", help="r,g,b gains on the cloud layer's colour")
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
    # The picture's sunset fills the lower-left sky - 140, 105, 107 over rows 250-300 against our 90,
    # 78, 94 at the old strength - so the glow is stronger and stands taller (y_scale 0.42, from 0.28).
    warm = radial(W, H, 0, HORIZON, W * 0.55, 0.42, [(0.0, (250, 165, 115), 0.85 * glow), (0.5, (218, 128, 112), 0.42 * glow), (1.0, (214, 120, 110), 0.0)])
    sky = over(sky, warm[..., :3], warm[..., 3])
    # The cool patch stood at 0.7 and made a daylight azure of the sky right of the lift tower:
    # over columns 1365-1595, rows 0-60 the frame reads 45, 86, 155 where the picture reads
    # 39, 59, 98 - 27 over in green, 57 in blue, and flat with it (a spread of 11 in blue against
    # the picture's 40). The picture is lighter on the right than over the middle of the roof
    # (39, 59, 98 against 20, 30, 57), so the patch earns its place, at a seventh of its weight:
    # at 0.1 that sky lands on 30, 63, 118.
    # 0.45, from 0.1: at 0.1 the right-hand corner read 30 to 47 short of the picture in blue over its
    # rows 100-300 (the city right of the building 2.0 -> 10.5); at 0.7 it had been +57 over.
    cool = radial(W, H, W * 0.86, 20, W * 0.26, 0.55, [(0.0, (100, 146, 220), 0.45 * glow), (1.0, (100, 146, 220), 0.0)])
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
        if a.cloud_zoom > 1.0:
            cw, ch = layer.width / a.cloud_zoom, layer.height / a.cloud_zoom
            left, top = (layer.width - cw) / 2, (layer.height - ch) / 2
            layer = layer.crop((round(left), round(top), round(left + cw), round(top + ch)))
        lh = round(layer.height * W / layer.width)
        layer = layer.resize((W, lh), Image.LANCZOS)
        if a.cloud_blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(a.cloud_blur))
        arr = np.asarray(layer, np.float32).copy()
        arr[..., :3] *= np.array([float(v) for v in a.cloud_tint.split(",")], np.float32)
        region = sky[:lh]
        sky[:lh] = over(region, arr[..., :3], arr[..., 3] / 255.0 * weight * a.cloud_strength)

    sky = sky * np.array([float(v) for v in a.tint.split(",")], np.float32)
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8), "RGB")
    img = img.resize((W * a.scale, H * a.scale), Image.LANCZOS)
    img.save(a.out)
    print(f"AMN_SKY daylight={daylight:.3f} dusk={dusk:.3f} tint={a.tint} cloud_zoom={a.cloud_zoom} -> {a.out} {img.size}")


main()
