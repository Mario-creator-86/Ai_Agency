"""Diagnostic: list the parameters of the materials the glTF import created under /Game/HQ/Scene,
so the scene script knows how to scale emission (lit windows, labels, screens) without guessing.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_materials.py
"""

import unreal

ROOT = "/Game/HQ/Scene"


def log(msg):
    unreal.log(f"AMN_PROBE {msg}")


registry = unreal.AssetRegistryHelpers.get_asset_registry()
assets = registry.get_assets_by_path(ROOT, recursive=True)
classes = {}
for data in assets:
    cls = str(data.asset_class_path.asset_name)
    classes[cls] = classes.get(cls, 0) + 1
log(f"classes under {ROOT}: {classes}")

shown = 0
mel = unreal.MaterialEditingLibrary
for data in assets:
    cls = str(data.asset_class_path.asset_name)
    if cls not in ("MaterialInstanceConstant", "Material") or shown >= 4:
        continue
    path = str(data.package_name)
    if not any(key in path.lower() for key in ("tower", "skyline", "label", "rooms", "sign")) and shown >= 1:
        continue
    mat = unreal.load_asset(path)
    if mat is None:
        continue
    shown += 1
    log(f"material {path} ({cls})")
    if isinstance(mat, unreal.MaterialInstanceConstant):
        parent = mat.get_editor_property("parent")
        log(f"  parent {parent.get_path_name() if parent else None}")
        for kind, getter in (("scalar", mel.get_scalar_parameter_names), ("vector", mel.get_vector_parameter_names), ("texture", mel.get_texture_parameter_names)):
            try:
                names = getter(mat)
                log(f"  {kind}: {[str(n) for n in names]}")
            except Exception as err:
                log(f"  {kind} unreadable: {err}")
        for value in mat.get_editor_property("scalar_parameter_values"):
            log(f"  scalar set {value.parameter_info.name} = {value.parameter_value}")
log("done")
