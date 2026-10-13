"""Measure the exported plates alone against the reference, composed the way the canvas stacks them.

  python art-source/reference/plates_compare.py frontend/public/assets/hq/plates out.png [--daylight 0.07]

A live screenshot also carries traffic, people, the sky and the day/night crossfade, so two shots of
the same plates can measure differently. This composes only the plate layers (night, with the day
plates blended in at --daylight, which should be what the canvas uses: plateDayMix of the scene's
daylight) and reports the building and street regions of compare.py. Sky and city regions are
dropped: the sky is drawn by the canvas.
"""

import argparse
import json
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["city", "street_back", "street_ground", "building_back", "building_front", "building_shell", "street_props", "street_kerb", "street_front"]
KEEP = ("roof_sign", "l4", "l3", "l2", "l1", "ground", "tower", "street")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plates")
    p.add_argument("out")
    p.add_argument("--variant", default="night")
    p.add_argument("--daylight", type=float, default=0.0, help="weight of the day plates over each night layer")
    a = p.parse_args()
    meta = json.load(open(os.path.join(a.plates, "plates.json"), encoding="utf-8"))
    world = meta["world"]
    scale = meta["scale"]
    canvas = Image.new("RGBA", (world["width"], world["height"]), (18, 22, 40, 255))

    def placed(entry):
        im = Image.open(os.path.join(a.plates, entry["file"])).convert("RGBA")
        im = im.resize((round(im.width / scale), round(im.height / scale)), Image.LANCZOS)
        full = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        full.alpha_composite(im, (round(entry["x"]), round(entry["y"])))
        return full

    for name in ORDER:
        night = meta["variants"][a.variant].get(name)
        if night:
            canvas.alpha_composite(placed(night))
        day = meta["variants"].get("day", {}).get(name)
        if a.daylight > 0 and day:
            layer = placed(day)
            layer.putalpha(layer.getchannel("A").point(lambda v: round(v * a.daylight)))
            canvas.alpha_composite(layer)
    canvas.convert("RGB").save(a.out)
    res = subprocess.run([sys.executable, os.path.join(HERE, "compare.py"), a.out, a.out.replace(".png", "_cmp.png")], capture_output=True, text=True)
    rows = [line for line in res.stdout.splitlines() if line.split(" ")[0] in KEEP]
    for line in rows:
        print(line)
    colours = [float(line.split("colour")[1].split("|")[0]) for line in rows]
    if colours:
        print(f"PLATES MEAN colour {sum(colours) / len(colours):.1f} over {len(colours)} regions")


main()
