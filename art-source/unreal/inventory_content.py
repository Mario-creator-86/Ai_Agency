"""
Unreal Engine 5.8 editor script: lists what content the AMNReference project holds, so the
headquarters scene can use packs the Owner adds from Fab (vehicles, MetaHuman outfits, office and
street props) without guessing their paths.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=inventory_content.py

Writes art-source/unreal/content_inventory.json (generated, ignored by Git): for every top-level
folder under /Game, the number of assets per class and the static meshes, skeletal meshes and
blueprints by path, with each static mesh's bounding box in centimetres, so a car, a desk or a
lamp can be told apart by size.
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "content_inventory.json")
LISTED = {"StaticMesh", "SkeletalMesh", "Blueprint", "MaterialInstanceConstant", "World"}


def size_from_tag(tag):
    """'450x180x140' (the registry's ApproxSize, in cm) -> [450.0, 180.0, 140.0], else None."""
    parts = tag.lower().split("x")
    if len(parts) != 3:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def main():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path("/Game", recursive=True)
    folders = {}
    for data in assets:
        path = str(data.package_name)
        parts = path.split("/")
        top = "/".join(parts[:3]) if len(parts) > 2 else path
        cls = str(data.asset_class_path.asset_name)
        entry = folders.setdefault(top, {"counts": {}, "assets": []})
        entry["counts"][cls] = entry["counts"].get(cls, 0) + 1
        if cls not in LISTED:
            continue
        item = {"path": path, "class": cls}
        if cls == "StaticMesh":
            # The registry already knows each mesh's size ("ApproxSize", e.g. "450x180x140"):
            # loading tens of GB of packs mesh by mesh would exhaust the machine's memory.
            size = size_from_tag(str(data.get_tag_value("ApproxSize") or ""))
            if size:
                item["size_cm"] = size
        entry["assets"].append(item)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(folders, fh, indent=1)
    for top, entry in sorted(folders.items()):
        summary = ", ".join(f"{k} {v}" for k, v in sorted(entry["counts"].items(), key=lambda kv: -kv[1])[:6])
        unreal.log(f"AMN_INVENTORY {top}: {summary}")
    unreal.log(f"AMN_INVENTORY wrote {OUT} ({len(assets)} assets)")


main()
