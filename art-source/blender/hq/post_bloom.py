"""Add the soft glow around lights that the reference has (bloom), keeping alpha correct.

  python art-source/blender/hq/post_bloom.py <in.png> [<out.png>] [--strength 1.0]

Bright pixels are blurred at two radii and added back. For a layer with transparency the glow is
added in premultiplied space and the alpha grows where the glow is, so a lamp's halo still shows
when the layer is drawn over the sky or another layer.
"""

import argparse

import numpy as np
from PIL import Image, ImageFilter


def bloom(img, strength=1.0, threshold=0.72):
    rgba = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
    rgb, alpha = rgba[..., :3], rgba[..., 3:4]
    premul = rgb * alpha
    luma = (premul * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(-1, keepdims=True)
    bright = premul * np.clip((luma - threshold) / (1.0 - threshold), 0.0, 1.0)
    src = Image.fromarray((np.clip(bright, 0, 1) * 255).astype(np.uint8))
    scale = max(1.0, img.width / 1600.0)
    glow = np.zeros_like(premul)
    for radius, weight in ((4 * scale, 0.55), (14 * scale, 0.45), (38 * scale, 0.35)):
        blurred = np.asarray(src.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0
        glow += blurred * weight
    glow *= strength
    out_premul = np.clip(premul + glow, 0.0, 1.0)
    glow_alpha = np.clip(glow.max(-1, keepdims=True) * 1.2, 0.0, 1.0)
    out_alpha = np.clip(alpha + glow_alpha * (1.0 - alpha), 0.0, 1.0)
    out_rgb = np.where(out_alpha > 1e-4, out_premul / np.maximum(out_alpha, 1e-4), 0.0)
    out = np.concatenate([np.clip(out_rgb, 0, 1), out_alpha], -1)
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("dst", nargs="?")
    p.add_argument("--strength", type=float, default=1.0)
    a = p.parse_args()
    bloom(Image.open(a.src), a.strength).save(a.dst or a.src)


if __name__ == "__main__":
    main()
