"""Compose the sky backdrop for the Unreal scene: the same sky the web page draws (frontend/src/
hq_time.js skyStops + hq_sky.js afterglow and painted cloud layers) at a given sun elevation.

  py -3.11 art-source/unreal/compose_sky_backdrop.py [--elevation -2.5] [--out sky_dusk.png] [--scale 2]
  py -3.11 art-source/unreal/compose_sky_backdrop.py --atlas [art-source/unreal/sky_atlas.png]

Without --atlas it writes one plate, upscaled, exactly as it always did (the default elevation is
the Owner's picture, -2.5). With --atlas it composes one cell per elevation in ATLAS_ELEVATIONS at
the composer's own 1600 x 840, stacks them top to bottom into one image (1600 x 8400: the x2
upscale of ten cells would pass the engine's 16384 limit), and writes a sidecar .json with the
order. build_hq_scene.py puts the atlas on the backdrop's material, which blends two neighbouring
cells by the scalars the backend sets from the real sun (PlateA, PlateB, PlateBlend, Mirror). The
-2.5 cell is today's plate before its upscale, byte for byte (tests/test_sky_atlas.py), so the
approved dusk does not move.

An orthographic camera cannot see Unreal's sky atmosphere, so the sky is a picture on an unlit
backdrop behind the city. Generated, ignored by Git.
"""

import argparse
import json
import math
import os
from dataclasses import dataclass

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
REFERENCE_ELEVATION = -2.5  # hq_time.js REFERENCE_DUSK_ELEVATION: the Owner's picture
# The cells, low to high. Three plates (night, dusk, day) left a pink band at +15 deg, two and a
# half hours before sunset, from a straight crossfade between -2.5 and +35: dense where the sky
# changes fast (the half hour around sunset), sparse where it hardly does.
ATLAS_ELEVATIONS = (-18.0, -12.0, -8.0, -5.0, -2.5, 0.0, 3.0, 8.0, 15.0, 35.0)


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


def daylight_of(elevation):
    """How much of the day sky shows at this sun elevation (hq_time.js), 0..1."""
    return smoothstep(-8, 7, elevation)


def dusk_of(elevation):
    """How much of the dusk glow shows at this sun elevation (hq_time.js), 0..1, peaking at +1."""
    return math.exp(-(((elevation - 1) / 6.5) ** 2))


@dataclass
class Options:
    # Next to the Owner's picture the composed sky comes out warmer: over its upper half the live
    # frame reads about 7 short of green and 12 short of blue (the picture 77, 77, 105 against
    # 79, 69, 93). These gains close that without touching the page's own palette.
    # Raised to 1.18, 1.20 with the clouds at half (below): a third of the plate's light was in the
    # painted layer, and without it the sky falls the other way. Over the frame's left sky (columns
    # 20-390, rows 85-175) the halved plate would reach 56, 68, 113 where the picture is 62, 75, 117;
    # these gains put it on 61, 75, 117.
    tint: str = "1.0,1.12,1.10"
    # The painted cloud layer is drawn for the page's own sky, at the page's width. Laid across
    # the plate it repeats as a fine mackerel pattern, where the picture has a few large, soft
    # bands. Zooming into the middle of the layer makes its clouds that much larger.
    # Zoomed further the bands do get larger, but the crop lands on a brighter part of the texture
    # and the sky low on the right went 10 out to 40 out; 1.7 stays.
    cloud_zoom: float = 1.4
    # The layer is drawn for the page, where it carries the whole look; over the plate it reads as
    # a cream mackerel where the picture has soft bands of a deeper blue. Over the frame's left sky
    # it takes the plate to 92, 88, 112 against the picture's 62, 75, 117 - 30 over in red and 5
    # short of blue - and its spread there is 24 in red against 6 in blue, where the picture's
    # varies by about as much in every channel. At half the plate is 74, 82, 118, the bands are
    # still there, and the picture's own tone comes back through them.
    cloud_strength: float = 0.32
    # The picture's clouds are soft bands; the painted layer is sharp at any zoom, and sharp clouds put
    # pixel noise on a sky the picture keeps smooth (its region 5.1 -> 12.4 with the band means closer).
    cloud_blur: float = 3.0
    # the picture's clouds are pink-mauve, lit from the sunset; the painted layer is neutral
    cloud_tint: str = "1.16,0.96,0.93"


def compose_cell(elevation, a, w=W, h=H, horizon=HORIZON):
    """The sky at this sun elevation, as uint8 RGB (h, w, 3), before any upscale.

    At REFERENCE_ELEVATION and the default Options this is the plate the stream has shown since
    2026-09-16: the arithmetic below is that composition's, in the same order, so the approved
    dusk comes out byte for byte (tests/test_sky_atlas.py). Only the elevation became an argument.
    """
    daylight = daylight_of(elevation)
    dusk = dusk_of(elevation)

    stops = []
    for i, pos in enumerate(POSITIONS):
        base = mix(rgb(SKY["night"][i]), rgb(SKY["day"][i]), daylight)
        stops.append((pos, mix(base, rgb(SKY["dusk"][i]), dusk * 0.95)))
    rows = np.linspace(0, 1, h, dtype=np.float32)
    column = np.zeros((h, 3), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (rows >= p0) & (rows <= p1)
        t = ((rows[m] - p0) / (p1 - p0))[:, None]
        column[m] = c0 * (1 - t) + c1 * t
    column[rows > POSITIONS[-1]] = stops[-1][1]
    sky = np.repeat(column[:, None, :], w, axis=1)

    glow = dusk
    # The picture's sunset fills the lower-left sky - 140, 105, 107 over rows 250-300 against our 90,
    # 78, 94 at the old strength - so the glow is stronger and stands taller (y_scale 0.42, from 0.28).
    # It is always painted on the left: the evening side with the facade facing south (Owner decision
    # D1). A morning sky is this cell mirrored by the backdrop material's Mirror scalar, not a second
    # composition.
    warm = radial(w, h, 0, horizon, w * 0.55, 0.42, [(0.0, (250, 165, 115), 0.85 * glow), (0.5, (218, 128, 112), 0.42 * glow), (1.0, (214, 120, 110), 0.0)])
    sky = over(sky, warm[..., :3], warm[..., 3])
    # The cool patch stood at 0.7 and made a daylight azure of the sky right of the lift tower:
    # over columns 1365-1595, rows 0-60 the frame reads 45, 86, 155 where the picture reads
    # 39, 59, 98 - 27 over in green, 57 in blue, and flat with it (a spread of 11 in blue against
    # the picture's 40). The picture is lighter on the right than over the middle of the roof
    # (39, 59, 98 against 20, 30, 57), so the patch earns its place, at a seventh of its weight:
    # at 0.1 that sky lands on 30, 63, 118.
    # 0.45, from 0.1: at 0.1 the right-hand corner read 30 to 47 short of the picture in blue over its
    # rows 100-300 (the city right of the building 2.0 -> 10.5); at 0.7 it had been +57 over.
    cool = radial(w, h, w * 0.86, 20, w * 0.26, 0.55, [(0.0, (100, 146, 220), 0.45 * glow), (1.0, (100, 146, 220), 0.0)])
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
        lh = round(layer.height * w / layer.width)
        layer = layer.resize((w, lh), Image.LANCZOS)
        if a.cloud_blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(a.cloud_blur))
        arr = np.asarray(layer, np.float32).copy()
        arr[..., :3] *= np.array([float(v) for v in a.cloud_tint.split(",")], np.float32)
        region = sky[:lh]
        sky[:lh] = over(region, arr[..., :3], arr[..., 3] / 255.0 * weight * a.cloud_strength)

    sky = sky * np.array([float(v) for v in a.tint.split(",")], np.float32)
    return np.clip(sky, 0, 255).astype(np.uint8)


def write_atlas(path, elevations, a, w=W, h=H, horizon=HORIZON):
    """Every cell stacked top to bottom at the native size, and the sidecar that names them."""
    cells = [compose_cell(e, a, w=w, h=h, horizon=horizon) for e in elevations]
    Image.fromarray(np.vstack(cells), "RGB").save(path)
    reference = elevations.index(REFERENCE_ELEVATION)
    meta = {
        "cells": len(cells),
        "cell_width": w,
        "cell_height": h,
        # cell i fills rows i*cell_height .. (i+1)*cell_height; the material addresses it as
        # v = (i + v_cell) / cells
        "elevations": [float(e) for e in elevations],
        "reference_elevation": REFERENCE_ELEVATION,
        "reference_cell": reference,
        # the weights each cell was composed with, so the backend blends by the composer's own
        # functions rather than a copy of them
        "daylight": [round(daylight_of(e), 6) for e in elevations],
        "dusk": [round(dusk_of(e), 6) for e in elevations],
        "glow_side": "left: evening, facade facing south (Owner decision D1); Mirror=1 puts it right",
        "options": dict(a.__dict__),
    }
    with open(os.path.splitext(path)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    for e in elevations:
        print(f"AMN_SKY cell {e:+.1f} deg daylight={daylight_of(e):.3f} dusk={dusk_of(e):.3f}")
    print(f"AMN_SKY atlas {len(cells)} cells of {w}x{h} -> {path} ({w}x{h * len(cells)}), "
          f"reference {REFERENCE_ELEVATION} in cell {reference}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(HERE, "sky_dusk.png"))
    p.add_argument("--scale", type=int, default=2)
    p.add_argument("--elevation", type=float, default=REFERENCE_ELEVATION,
                   help="sun elevation in degrees of the single plate (ignored with --atlas)")
    p.add_argument("--atlas", nargs="?", const=os.path.join(HERE, "sky_atlas.png"), default=None,
                   help="compose every ATLAS_ELEVATIONS cell into one image at the native size")
    # w,h,horizon: the tests compose a small frame; the scene always uses the default
    p.add_argument("--size", default=f"{W},{H},{HORIZON}", help=argparse.SUPPRESS)
    defaults = Options()
    p.add_argument("--tint", default=defaults.tint, help="r,g,b gains applied to the composed sky")
    p.add_argument("--cloud-zoom", type=float, default=defaults.cloud_zoom)
    p.add_argument("--cloud-strength", type=float, default=defaults.cloud_strength, help="opacity of the painted cloud layers")
    p.add_argument("--cloud-blur", type=float, default=defaults.cloud_blur, help="Gaussian blur of the cloud layer, in plate pixels")
    p.add_argument("--cloud-tint", default=defaults.cloud_tint, help="r,g,b gains on the cloud layer's colour")
    args = p.parse_args(argv)
    a = Options(tint=args.tint, cloud_zoom=args.cloud_zoom, cloud_strength=args.cloud_strength,
                cloud_blur=args.cloud_blur, cloud_tint=args.cloud_tint)
    w, h, horizon = (int(v) for v in args.size.split(","))
    if args.atlas:
        write_atlas(args.atlas, list(ATLAS_ELEVATIONS), a, w=w, h=h, horizon=horizon)
        return
    img = Image.fromarray(compose_cell(args.elevation, a, w=w, h=h, horizon=horizon), "RGB")
    img = img.resize((w * args.scale, h * args.scale), Image.LANCZOS)
    img.save(args.out)
    print(f"AMN_SKY elevation={args.elevation} daylight={daylight_of(args.elevation):.3f} "
          f"dusk={dusk_of(args.elevation):.3f} tint={a.tint} cloud_zoom={a.cloud_zoom} -> {args.out} {img.size}")


if __name__ == "__main__":
    main()
