"""Paint the sky's cloud layers procedurally, in the style of the Owner's headquarters picture.

  python art-source/sky/paint_clouds.py [--out frontend/public/assets/hq/sky] [--scale 1] [--seed 7]
      [--preview <png>]

No image generator is involved: layered value noise is shaped into long banks of cloud with crisp
edges; the vertical slope of a blurred height field says which side faces the light. At dusk the sun
is below the horizon, so undersides glow warm and cores stay blue-grey, as in the picture; by day
tops are white and undersides grey; at night the clouds are dim and moonlit. The canvas crossfades
the three layers with the time of day, and live weather still thickens or clears them.

Writes clouds_dusk.webp, clouds_day.webp and clouds_night.webp (world width x 460 rows, at --scale).
"""

import argparse
import os

import numpy as np
from PIL import Image, ImageFilter

WORLD_W, ROWS = 1600, 460
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REFERENCE = os.path.join(ROOT, "art-source", "reference", "headquarters_dusk_primary.png")

# palette, coverage threshold (lower = more cloud), maximum opacity, lit from below
LOOKS = {
    "dusk": ({"shadow": "#222a48", "mid": "#46415e", "light": "#f5a06a", "warm_low": 1.3}, 0.43, 0.97, True),
    "day": ({"shadow": "#9aa8c2", "mid": "#dbe3ef", "light": "#ffffff"}, 0.52, 0.9, False),
    "night": ({"shadow": "#0f1426", "mid": "#1e2540", "light": "#3a4468"}, 0.5, 0.75, False),
}


def value_noise(w, h, cells_x, cells_y, rng):
    small = Image.fromarray((rng.random((cells_y, cells_x)) * 255).astype(np.uint8), "L")
    return np.asarray(small.resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0


def fbm(w, h, rng, base_x, base_y, octaves=6, gain=0.55):
    total = np.zeros((h, w), np.float32)
    amp, norm = 1.0, 0.0
    cx, cy = base_x, base_y
    for _ in range(octaves):
        total += value_noise(w, h, max(2, int(cx)), max(2, int(cy)), rng) * amp
        norm += amp
        amp *= gain
        cx *= 2.0
        cy *= 2.0
    return total / norm


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0


def paint(scale, seed, palette, coverage, alpha_max, light_from_below):
    w, h = WORLD_W * scale, ROWS * scale
    rng = np.random.default_rng(seed)
    # long banks: features several times wider than tall
    d = fbm(w, h, rng, base_x=7, base_y=5, octaves=7) * 0.75 + fbm(w, h, rng, base_x=30, base_y=14, octaves=5) * 0.25
    rows = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    # clouds fill the upper sky and thin out towards the horizon
    band = smoothstep(0.0, 0.08, rows) * (1.0 - smoothstep(0.5, 0.85, rows))
    density = d * (0.55 + 0.45 * band) - (1.0 - band) * 0.25
    alpha = smoothstep(coverage, coverage + 0.07, density)
    blur = ImageFilter.GaussianBlur(3 * scale)
    height = np.asarray(Image.fromarray((np.clip(density, 0, 1) * 255).astype(np.uint8)).filter(blur), np.float32) / 255.0
    slope = np.zeros_like(height)
    slope[1:-1] = height[2:] - height[:-2]
    lit = np.clip(0.42 + (slope if light_from_below else -slope) * 26.0, 0.0, 1.0)
    # thin edges catch more light than thick cores
    core = smoothstep(coverage + 0.05, coverage + 0.3, density)
    lit = np.clip(lit * (1.0 - 0.55 * core) + (1.0 - core) * 0.25, 0.0, 1.0)
    shadow, mid, light = hex_rgb(palette["shadow"]), hex_rgb(palette["mid"]), hex_rgb(palette["light"])
    lit3 = lit[..., None]
    colour = np.where(lit3 < 0.5, shadow + (mid - shadow) * (lit3 / 0.5), mid + (light - mid) * ((lit3 - 0.5) / 0.5))
    # lower clouds are warmer at dusk, nearer the glow
    warm = (rows * palette.get("warm_low", 0.0))[..., None]
    colour = colour + (light - colour) * np.clip(warm * lit3, 0, 1) * 0.6
    rgba = np.dstack([np.clip(colour, 0, 1), alpha * alpha_max])
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")


def preview(dusk, path):
    """The dusk layer over a dusk gradient like the canvas's, under the picture's sky, for review."""
    rows = np.linspace(0, 1, ROWS, dtype=np.float32)
    stops = [(0.0, "#1b2644"), (0.3, "#34416e"), (0.6, "#b56f6c"), (0.8, "#e59a74"), (1.0, "#d28a70")]
    grad = np.zeros((ROWS, 3), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (rows >= p0) & (rows <= p1)
        t = ((rows[m] - p0) / (p1 - p0))[:, None]
        grad[m] = hex_rgb(c0) * (1 - t) + hex_rgb(c1) * t
    sky = Image.fromarray((np.repeat(grad[:, None, :], WORLD_W, axis=1) * 255).astype(np.uint8), "RGB").convert("RGBA")
    sky.alpha_composite(dusk.resize((WORLD_W, ROWS), Image.LANCZOS))
    ref = Image.open(REFERENCE).convert("RGB").crop((10, 50, 10 + WORLD_W, 50 + ROWS))
    both = Image.new("RGB", (WORLD_W, ROWS * 2 + 6), (255, 0, 255))
    both.paste(ref, (0, 0))
    both.paste(sky.convert("RGB"), (0, ROWS + 6))
    both.save(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(ROOT, "frontend", "public", "assets", "hq", "sky"))
    p.add_argument("--scale", type=int, default=1)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--quality", type=int, default=88)
    p.add_argument("--preview", default="")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    layers = {}
    for name, (palette, coverage, alpha_max, below) in LOOKS.items():
        layers[name] = paint(a.scale, a.seed, palette, coverage, alpha_max, below)
        path = os.path.join(a.out, f"clouds_{name}.webp")
        layers[name].save(path, "WEBP", quality=a.quality, method=6)
        print(f"{name}: {layers[name].width}x{layers[name].height} -> {path} ({os.path.getsize(path) // 1024} KB)")
    if a.preview:
        preview(layers["dusk"], a.preview)


main()
