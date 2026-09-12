"""Put a render beside the reference so the difference can be seen and measured.

  python art-source/reference/compare.py <render.png> <out.png> [--crop x0,y0,x1,y1] [--zoom 2]

The reference is cropped to the office world (reference - (10, 50), 1600 x 840) so both images
share coordinates. Writes a stacked image (reference on top, render below) and prints, per region:
the mean colour distance, the brightness and contrast of each image, and a structural similarity
(SSIM on a blurred greyscale), so a pass is judged by numbers as well as by eye.
"""

import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "headquarters_dusk_primary.png")
OFFSET = (10, 50)
WORLD = (1600, 840)

REGIONS = {
    "sky_left": (0, 0, 400, 300),
    "city_left": (0, 300, 415, 640),
    "roof_sign": (415, 0, 1352, 90),
    "l4": (447, 85, 1205, 177),
    "l3": (447, 195, 1205, 282),
    "l2": (447, 297, 1205, 392),
    "l1": (447, 410, 1205, 500),
    "ground": (447, 520, 1205, 655),
    "tower": (1205, 0, 1352, 655),
    "city_right": (1352, 0, 1600, 640),
    "street": (0, 655, 1600, 840),
}


def reference_world():
    ref = Image.open(REFERENCE).convert("RGB")
    return ref.crop((OFFSET[0], OFFSET[1], OFFSET[0] + WORLD[0], OFFSET[1] + WORLD[1]))


def grey(img, box):
    g = img.crop(box).convert("L").filter(ImageFilter.GaussianBlur(1.5))
    return np.asarray(g, dtype=np.float64)


def ssim(a, b):
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = a.mean(), b.mean()
    va, vb = a.var(), b.var()
    cov = ((a - ma) * (b - mb)).mean()
    return ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma**2 + mb**2 + c1) * (va + vb + c2))


def windowed_ssim(a, b, win=24):
    scores = []
    for y in range(0, a.shape[0] - win + 1, win // 2):
        for x in range(0, a.shape[1] - win + 1, win // 2):
            scores.append(ssim(a[y : y + win, x : x + win], b[y : y + win, x : x + win]))
    return float(np.mean(scores)) if scores else ssim(a, b)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("render")
    p.add_argument("out")
    p.add_argument("--crop", default="")
    p.add_argument("--zoom", type=float, default=1.0)
    a = p.parse_args()
    ref = reference_world()
    ren = Image.open(a.render).convert("RGB")
    if ren.size != WORLD:
        ren = ren.resize(WORLD, Image.LANCZOS)
    rows = []
    for name, box in REGIONS.items():
        ra = np.asarray(ref.crop(box), dtype=np.float64).reshape(-1, 3).mean(0)
        ga = np.asarray(ren.crop(box), dtype=np.float64).reshape(-1, 3).mean(0)
        dist = float(np.sqrt(((ra - ga) ** 2).sum()))
        gr, gg = grey(ref, box), grey(ren, box)
        s = windowed_ssim(gr, gg)
        rows.append((name, dist, gr.mean(), gg.mean(), gr.std(), gg.std(), s))
        print(
            f"{name:11s} colour {dist:5.1f} | light ref {gr.mean():5.1f} ren {gg.mean():5.1f}"
            f" | contrast ref {gr.std():5.1f} ren {gg.std():5.1f} | ssim {s:.3f}"
        )
    print(
        f"MEAN colour {np.mean([r[1] for r in rows]):.1f}  light-gap {np.mean([abs(r[2] - r[3]) for r in rows]):.1f}"
        f"  contrast-gap {np.mean([abs(r[4] - r[5]) for r in rows]):.1f}  ssim {np.mean([r[6] for r in rows]):.3f}"
    )
    if a.crop:
        box = tuple(int(v) for v in a.crop.split(","))
        ref, ren = ref.crop(box), ren.crop(box)
    if a.zoom != 1.0:
        size = (int(ref.width * a.zoom), int(ref.height * a.zoom))
        ref, ren = ref.resize(size, Image.LANCZOS), ren.resize(size, Image.LANCZOS)
    sheet = Image.new("RGB", (ref.width, ref.height * 2 + 6), (255, 0, 255))
    sheet.paste(ref, (0, 0))
    sheet.paste(ren, (0, ref.height + 6))
    ImageDraw.Draw(sheet).text((6, 4), "REFERENCE", fill=(255, 255, 0))
    ImageDraw.Draw(sheet).text((6, ref.height + 10), "RENDER", fill=(255, 255, 0))
    sheet.save(a.out)


main()
