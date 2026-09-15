"""
Unreal Engine 5.8 commandlet, step 3 of 3 of the street trees' green leaves: imports
leaves/generated/T_HQ_Leaves_Green.png as /Game/HQ/Materials/T_HQ_Leaves_Green (sRGB, alpha kept) and
sets it as DiffuseandAlpha on the leaf instance MI_HQ_TreeLeavesGreen. dress_hq_live.py puts that
texture on the instance on every later pass as long as the asset exists.
"""

import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "generated", "T_HQ_Leaves_Green.png")
FOLDER = "/Game/HQ/Materials"
TEXTURE = f"{FOLDER}/T_HQ_Leaves_Green"
MI = f"{FOLDER}/MI_HQ_TreeLeavesGreen"
mel = unreal.MaterialEditingLibrary

if not os.path.exists(PNG):
    unreal.log_error(f"AMN_LEAF no green texture to import: {PNG} (run export_leaf_texture.py and green_leaves.py first)")
else:
    task = unreal.AssetImportTask()
    task.filename = PNG
    task.destination_path = FOLDER
    task.destination_name = "T_HQ_Leaves_Green"
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = unreal.load_asset(TEXTURE)
    if tex is None:
        unreal.log_error(f"AMN_LEAF import failed: {PNG}")
    else:
        tex.set_editor_property("srgb", True)
        unreal.EditorAssetLibrary.save_loaded_asset(tex)
        mi = unreal.load_asset(MI)
        if mi is None:
            unreal.log(f"AMN_LEAF {TEXTURE} imported; {MI} does not exist yet (dress_hq_live.py creates it and sets the texture)")
        else:
            mel.set_material_instance_texture_parameter_value(mi, "DiffuseandAlpha", tex)
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            unreal.log(f"AMN_LEAF {TEXTURE} ({tex.blueprint_get_size_x()}x{tex.blueprint_get_size_y()}) set on {MI}")
