"""
Diagnostic: why the skyline renders flat white in the streamed level.

Lists the skyline mesh's material slots, each material's class and texture parameters (which
texture asset it reads, whether that asset exists, its size, and whether it streams as a virtual
texture), and every skyline texture copy the re-imports left in /Game/HQ/Scene.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_skyline_material.py
"""

import unreal

# build_hq_scene.py imports into /Game/HQ/Scene_<timestamp>: look the assets up by name under /Game/HQ
ROOT = "/Game/HQ"


def log(msg):
    unreal.log(f"AMN_SKY {msg}")


def describe_texture(tex):
    if tex is None:
        return "None"
    try:
        vt = tex.get_editor_property("virtual_texture_streaming")
    except Exception:
        vt = "?"
    try:
        size = f"{tex.blueprint_get_size_x()}x{tex.blueprint_get_size_y()}"
    except Exception:
        size = "?"
    return f"{tex.get_path_name()} size={size} vt={vt}"


def main():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = sorted((a for a in registry.get_assets_by_path(ROOT, recursive=True)
                    if str(a.asset_name) == "skyline" and str(a.asset_class_path.asset_name) == "StaticMesh"),
                   key=lambda a: str(a.package_name))
    if not found:
        log(f"no skyline mesh under {ROOT}")
        return
    mesh_path = str(found[-1].package_name)  # the newest Scene_<timestamp> sorts last
    log(f"mesh {mesh_path} ({len(found)} skyline meshes under {ROOT})")
    mesh = unreal.load_asset(mesh_path)
    for i, slot in enumerate(mesh.get_editor_property("static_materials")):
        mat = slot.get_editor_property("material_interface")
        name = slot.get_editor_property("material_slot_name")
        if mat is None:
            log(f"slot {i} {name}: no material")
            continue
        log(f"slot {i} {name}: {mat.get_class().get_name()} {mat.get_path_name()}")
        if isinstance(mat, unreal.MaterialInstance):
            parent = mat.get_editor_property("parent")
            log(f"   parent {parent.get_path_name() if parent else None}")
            for p in mat.get_editor_property("texture_parameter_values"):
                info = p.get_editor_property("parameter_info")
                log(f"   texture param {info.get_editor_property('name')}: {describe_texture(p.get_editor_property('parameter_value'))}")
    copies = [a for a in registry.get_assets_by_path(ROOT, recursive=True)
              if str(a.asset_name).startswith("skyline") and str(a.asset_class_path.asset_name) == "Texture2D"]
    for data in sorted(copies, key=lambda a: str(a.asset_name)):
        log(f"copy {data.asset_name}: {describe_texture(unreal.load_asset(str(data.package_name)))}")


main()
