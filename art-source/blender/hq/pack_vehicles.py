"""Pack vehicle renders into one sheet per vehicle and write the catalogue the canvas reads.

  python art-source/blender/hq/pack_vehicles.py <renders dir> <out dir> [--downscale 2]

Sheet columns per direction: wheel frames 0..2, then the lamp overlay, then siren frames when the
vehicle has a light bar. Row 0 drives right, row 1 drives left.
"""

import argparse
import json
import os

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--downscale", type=int, default=2)
    a = p.parse_args()
    cat = json.load(open(os.path.join(a.src, "vehicles.json"), encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    scale = cat["scale"] // a.downscale
    out = {"scale": scale, "vehicles": {}}
    for kind, entry in cat["vehicles"].items():
        if not entry:
            continue
        columns = ["0", "1", "2", "lights"] + (["siren0", "siren1"] if entry["siren"] else [])
        cells = {}
        cw = max(entry["frames"][d]["w"] for d in ("right", "left")) * scale
        ch = max(entry["frames"][d]["h"] for d in ("right", "left")) * scale
        sheet = Image.new("RGBA", (cw * len(columns), ch * 2), (0, 0, 0, 0))
        for row, direction in enumerate(("right", "left")):
            f = entry["frames"][direction]
            w, h = f["w"] * scale, f["h"] * scale
            for col, name in enumerate(columns):
                path = os.path.join(a.src, f"{kind}__{direction}__{name}.png")
                im = Image.open(path).convert("RGBA")
                if im.size != (w, h):
                    im = im.resize((w, h), Image.LANCZOS)
                sheet.paste(im, (col * cw, row * ch))
            cells[direction] = {"w": f["w"], "h": f["h"], "pivot": f["pivot"], "row": row}
        sheet.save(os.path.join(a.out, f"{kind}.png"), optimize=True)
        out["vehicles"][kind] = {
            "sheet": f"{kind}.png",
            "cell": {"w": cw // scale, "h": ch // scale},
            "columns": columns,
            "directions": cells,
            "length_m": entry["length_m"],
            "siren": entry["siren"],
            "two_wheeler": entry["two_wheeler"],
        }
        print(f"{kind}: {sheet.width}x{sheet.height}")
    with open(os.path.join(a.out, "vehicles.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)


main()
