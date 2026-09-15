"""
Unreal Engine 5.8 editor script: static copies of Megaplants trees for the live headquarters.

The Megaplants trees are skeletal meshes (their wind is a skeleton). Placed in the streamed level
they stopped Pixel Streaming's capture (the capture was recreated again and again and no frame
reached the page), and the scene fell back to its Blender trees, which read as foam next to the
Owner's picture. Geometry Script copies each tree's geometry out of the skeletal mesh
(CopyMeshFromSkeletalMesh) into a new Nanite static mesh (CreateNewStaticMeshAssetFromMesh) under
/Game/HQ/Trees, with the tree's own materials. Trees already converted are skipped.

Needs the GeometryScripting plugin (enabled in AMNReference.uproject).

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=convert_trees_static.py

AMN_TREES_CONVERT=Tree_Black_Alder_01_B,... picks the trees (default: a small set for the street).
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = "/Game/Megaplant_Library"
OUT = "/Game/HQ/Trees"
DEFAULT = "Tree_Black_Alder_01_B,Tree_Black_Poplar_01_A,Tree_Goat_Willow_01_D,Tree_Japanese_Medlar_01_B"
WANTED = [n.strip() for n in os.environ.get("AMN_TREES_CONVERT", DEFAULT).split(",") if n.strip()]


def log(msg):
    unreal.log(f"AMN_TREES {msg}")


def find_skeletal(name):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for data in registry.get_assets_by_path(SOURCE, recursive=True):
        if str(data.asset_name) == name and str(data.asset_class_path.asset_name) == "SkeletalMesh":
            return unreal.load_asset(str(data.package_name))
    return None


def outcome_ok(result):
    """Geometry Script returns (value, ..., outcome) when it has output pins; success is the last item."""
    items = result if isinstance(result, tuple) else (result,)
    return items[0], items[-1] == unreal.GeometryScriptOutcomePins.SUCCESS if len(items) > 1 else items[0] is not None


def convert(name):
    target = f"{OUT}/SM_{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(target):
        mesh = unreal.load_asset(target)
        return {"asset": target, "status": "exists", "size_cm": size(mesh)}
    skel = find_skeletal(name)
    if skel is None:
        return {"status": "skeletal mesh not found"}
    dynamic = unreal.new_object(unreal.DynamicMesh)
    copied, ok = outcome_ok(unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(
        skel, dynamic, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD()))
    if not ok:
        return {"status": "copy from skeletal mesh failed"}
    options = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
    options.set_editor_property("enable_nanite", True)
    options.set_editor_property("enable_collision", False)
    mesh, ok = outcome_ok(unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(copied, target, options))
    if not ok or mesh is None:
        return {"status": "static mesh asset not created"}
    # the tree's own materials, slot by slot
    materials = [m.get_editor_property("material_interface") for m in skel.get_editor_property("materials")]
    for i, material in enumerate(materials):
        if material is not None and i < len(mesh.get_editor_property("static_materials")):
            mesh.set_material(i, material)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    return {"asset": target, "status": "converted", "materials": len(materials), "size_cm": size(mesh)}


def size(mesh):
    box = mesh.get_bounding_box()
    return [round(box.max.x - box.min.x), round(box.max.y - box.min.y), round(box.max.z - box.min.z)]


def main():
    report = {}
    for name in WANTED:
        try:
            report[name] = convert(name)
        except Exception as err:
            report[name] = {"status": f"FAILED {type(err).__name__}: {err}"}
        log(f"{name}: {report[name]}")
    with open(os.path.join(HERE, "trees_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    log("done")


main()
