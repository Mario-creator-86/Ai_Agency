"""Turn rendered plate layers into the files the web canvas loads.

  python art-source/blender/hq/export_plates.py <render dir> frontend/public/assets/hq

For each variant (night, day) and layer: add bloom, crop to what the layer actually covers (most
layers are a strip or a building-sized block, not the whole world), and save as WebP. plates.json
records where each crop sits in world pixels. The anchor manifest the Blender build wrote is
copied next to it, so the canvas and the art always come from the same build.

  python art-source/blender/hq/export_plates.py <render dir> frontend/public/assets/hq --variants day

--variants exports only the named variants: every other variant keeps its files and its entry in
the existing plates.json untouched, and the anchor manifest is copied only if it is the same one
(a day plate must be drawn over the night plate's building, never a different one).
"""

import argparse
import json
import os
import shutil
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from post_bloom import bloom  # noqa: E402

# Bloom is the glow around lights. By day the lamps are off or faint against the sun, and what
# crosses the threshold is sunlit white paint (a whiteboard, a console), which must not glow.
VARIANT_BLOOM = {"night": 1.0, "day": 0.35}
BLOOM = {"city": 0.8, "street_back": 0.5, "street_ground": 0.7, "building_back": 1.0, "building_front": 0.8, "building_shell": 0.9, "street_props": 1.1, "street_kerb": 0.4, "street_front": 0.5}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--variants", default="night,day")
    a = p.parse_args()
    wanted = [v for v in a.variants.split(",") if v]
    manifest = json.load(open(os.path.join(a.src, "manifest.json"), encoding="utf-8"))
    scale = manifest["scale"]
    plates_dir = os.path.join(a.out, "plates")
    os.makedirs(plates_dir, exist_ok=True)
    result = {"scale": scale, "world": manifest["world"], "variants": {}}
    kept = {}
    existing = os.path.join(plates_dir, "plates.json")
    if set(wanted) != {"night", "day"} and os.path.exists(existing):
        old = json.load(open(existing, encoding="utf-8"))
        if old.get("scale") != scale or old.get("world") != manifest["world"]:
            sys.exit("export_plates: the existing plates are at another scale or world size; export every variant")
        kept = {k: v for k, v in old.get("variants", {}).items() if k not in wanted}
    target = os.path.join(a.out, "manifest.json")
    if kept and os.path.exists(target) and json.load(open(target, encoding="utf-8")) != manifest:
        sys.exit("export_plates: this build's anchor manifest differs from the one the kept variants were drawn with")
    for variant in ("night", "day"):
        if variant not in wanted:
            if variant in kept:
                result["variants"][variant] = kept[variant]
            continue
        layers = {}
        for layer in manifest["layers"]:
            path = os.path.join(a.src, f"{variant}_{layer}.png")
            if not os.path.exists(path):
                continue
            im = bloom(Image.open(path), BLOOM.get(layer, 0.8) * VARIANT_BLOOM[variant])
            box = im.getchannel("A").point(lambda v: 255 if v > 3 else 0).getbbox()
            if box is None:
                continue
            pad = 4
            box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
            crop = im.crop(box)
            name = f"{variant}_{layer}.webp"
            crop.save(os.path.join(plates_dir, name), "WEBP", quality=a.quality, alpha_quality=95, method=5)
            layers[layer] = {"file": name, "x": box[0] / scale, "y": box[1] / scale, "w": crop.width / scale, "h": crop.height / scale}
            print(f"{variant}/{layer}: {crop.width}x{crop.height} at {box[0]},{box[1]}")
        if layers:
            result["variants"][variant] = layers
    with open(os.path.join(plates_dir, "plates.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    if kept:
        print("manifest: unchanged, kept")
        return
    shutil.copyfile(os.path.join(a.src, "manifest.json"), target)


main()
