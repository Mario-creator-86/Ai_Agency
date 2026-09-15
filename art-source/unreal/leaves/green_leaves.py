"""Step 2 of 3 of the street trees' green leaves (system Python with numpy and Pillow): a green copy
of a leaf texture. Every pixel's hue is turned by the angle that brings the leaves' average hue (a
saturation-weighted circular mean over opaque, coloured pixels) to the target; saturation and value
are kept, with optional factors; the alpha, the leaf cut-out, is left untouched.

  py -3.11 green_leaves.py <in.png> <out.png> [target_hue_deg=105] [saturation=1.0] [value=0.9]
"""

import sys

import numpy as np
from PIL import Image


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g[rm] - b[rm]) / d[rm]) % 6
    h[gm] = (b[gm] - r[gm]) / d[gm] + 2
    h[bm] = (r[bm] - g[bm]) / d[bm] + 4
    h = h * 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return np.stack([h, s, mx], -1)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0] % 360.0, hsv[..., 1], hsv[..., 2]
    c = v * s
    x = c * (1 - np.abs((h / 60.0) % 2 - 1))
    m = v - c
    zeros = np.zeros_like(h)
    sector = (h // 60).astype(int)
    r = np.choose(sector, [c, x, zeros, zeros, x, c], mode="clip")
    g = np.choose(sector, [x, c, c, x, zeros, zeros], mode="clip")
    b = np.choose(sector, [zeros, zeros, x, c, c, x], mode="clip")
    return np.stack([r + m, g + m, b + m], -1)


def main():
    src, out = sys.argv[1], sys.argv[2]
    target = float(sys.argv[3]) if len(sys.argv) > 3 else 105.0
    sat_k = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    val_k = float(sys.argv[5]) if len(sys.argv) > 5 else 0.9
    a = np.asarray(Image.open(src).convert("RGBA"), dtype=np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    hsv = rgb_to_hsv(rgb)
    leaf = (alpha > 0.5) & (hsv[..., 1] > 0.15)
    ang = np.deg2rad(hsv[..., 0][leaf])
    w = hsv[..., 1][leaf]
    mean_hue = float(np.rad2deg(np.arctan2((np.sin(ang) * w).sum(), (np.cos(ang) * w).sum())) % 360.0)
    shift = target - mean_hue
    hsv[..., 0] = hsv[..., 0] + shift
    hsv[..., 1] = np.clip(hsv[..., 1] * sat_k, 0, 1)
    hsv[..., 2] = np.clip(hsv[..., 2] * val_k, 0, 1)
    out_rgb = hsv_to_rgb(hsv)
    result = np.concatenate([out_rgb, alpha[..., None]], -1)
    Image.fromarray((result * 255.0 + 0.5).astype(np.uint8), "RGBA").save(out)
    new_mean = [round(float(v) * 255, 1) for v in out_rgb[alpha > 0.5].mean(0)]
    print(f"leaf hue {mean_hue:.0f} deg -> {target:.0f} deg (shift {shift:+.0f}); mean RGB of leaves now {new_mean}; saved {out}")


main()
