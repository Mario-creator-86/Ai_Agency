"""Pack rendered sprite frames into one sheet per character and write the atlas the canvas reads.

  python art-source/blender/hq/pack_sprites.py <frames dir> <out dir> [--manifest characters.json]

Every frame keeps the same size and pivot, so the canvas draws frame N of an animation at the
seat or walk position without per-frame offsets. Frames are trimmed to a shared box per
character to keep sheets small.
"""

import argparse
import json
import os

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frames")
    p.add_argument("out")
    p.add_argument("--manifest", default="characters.json")
    p.add_argument("--downscale", type=int, default=1)
    a = p.parse_args()
    src = json.load(open(os.path.join(a.frames, a.manifest), encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    frame = src["frame"]
    scale = frame["scale"] // a.downscale
    fw, fh = frame["w"] * scale, frame["h"] * scale
    atlas = {"frame": {"w": frame["w"], "h": frame["h"], "pivot": frame["pivot"], "scale": scale}, "characters": {}}
    for key, info in src["characters"].items():
        images = []
        for f in info["frames"]:
            im = Image.open(os.path.join(a.frames, f["file"])).convert("RGBA")
            if a.downscale > 1:
                im = im.resize((fw, fh), Image.LANCZOS)
            images.append((f, im))
        cols = 8
        rows = (len(images) + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
        anims = {}
        for i, (f, im) in enumerate(images):
            sheet.paste(im, ((i % cols) * fw, (i // cols) * fh))
            anims.setdefault(f["anim"], []).append(i)
        name = f"{key}.png"
        sheet.save(os.path.join(a.out, name), optimize=True)
        atlas["characters"][key] = {
            "sheet": name,
            "columns": cols,
            "role": info.get("role"),
            "canonical_name": info.get("canonical_name"),
            "seat_facing": info.get("seat_facing"),
            "animations": anims,
        }
        print(f"{key}: {len(images)} frames -> {name} ({sheet.width}x{sheet.height})")
    out_name = os.path.splitext(a.manifest)[0] + ".json"
    with open(os.path.join(a.out, out_name), "w", encoding="utf-8") as fh:
        json.dump(atlas, fh, indent=1)


main()
