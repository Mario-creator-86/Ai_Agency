"""Inspect HQ flat materials in a separate Unreal Python commandlet.

AMN_MATERIAL_REPORT is required. Default is read-only. AMN_MATERIAL_REPAIR=1
uses flat_material.parent_material() to repair the parent and resaves only the
cloth instances. Run against a copied material project before the real project.
"""

import importlib.util
import json
import os
from pathlib import Path

import unreal

PARENT = "/Game/HQ/Materials/M_HQ_Flat"
FOLDER = "/Game/HQ/Materials"
USAGE = unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH


def snapshot():
    mel = unreal.MaterialEditingLibrary
    parent = unreal.load_asset(PARENT)
    if parent is None:
        raise RuntimeError(f"Missing material: {PARENT}")
    instances = []
    for path in unreal.EditorAssetLibrary.list_assets(FOLDER, recursive=False, include_folder=False):
        if "MI_HQ_Flat_Cloth_" not in path:
            continue
        material = unreal.load_asset(path)
        instances.append({
            "path": material.get_path_name(),
            "parent": material.get_editor_property("parent").get_path_name(),
            "skeletal_mesh": mel.has_material_usage(material, USAGE),
            "usage_override": mel.has_material_usage_override(material, USAGE),
        })
    return {"parent": PARENT, "skeletal_mesh": mel.has_material_usage(parent, USAGE),
            "instances": sorted(instances, key=lambda item: item["path"])}


def main():
    report_path = Path(os.environ["AMN_MATERIAL_REPORT"])
    before = snapshot()
    repair = os.environ.get("AMN_MATERIAL_REPAIR") == "1"
    if repair:
        if not before["instances"]:
            raise RuntimeError("No HQ cloth instances found; refusing an unverified repair target")
        for item in before["instances"]:
            if item["usage_override"]:
                raise RuntimeError(f"Inspect existing usage override before repair: {item['path']}")
        spec = importlib.util.spec_from_file_location("flat_material", Path(__file__).with_name("flat_material.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.parent_material()
        for item in before["instances"]:
            material = unreal.load_asset(item["path"])
            unreal.MaterialEditingLibrary.update_material_instance(material)
            if not unreal.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False):
                raise RuntimeError(f"Could not save {item['path']}")
    after = snapshot()
    report = {"project": unreal.Paths.get_project_file_path(), "repair": repair,
              "before": before, "after": after}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if repair and (not after["skeletal_mesh"] or not all(item["skeletal_mesh"] for item in after["instances"])):
        raise RuntimeError("Skeletal material usage repair did not take effect")
    unreal.log(f"AMN_MATERIAL_AUDIT repair={repair} skeletal={after['skeletal_mesh']} instances={len(after['instances'])} report={report_path}")


if __name__ == "__main__":
    main()
