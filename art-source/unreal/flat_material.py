"""A plain lit material in a given colour, for pack assets whose own materials read wrong in this
scene: the street bench and planters (dark where the picture has lit stone and wood) and the
passers-by's garments (white underclothes). Built once as /Game/HQ/Materials/M_HQ_Flat, with one
instance per colour name beside it.

Imported by dress_hq_live.py and people/street_people.py.
"""

import unreal

PARENT = "/Game/HQ/Materials/M_HQ_Flat"
FOLDER = "/Game/HQ/Materials"


def ensure_skeletal_usage(mat):
    """The same parent serves static props and the passers-by's skeletal garments."""
    mel = unreal.MaterialEditingLibrary
    usage = unreal.MaterialUsage.MATUSAGE_SKELETAL_MESH
    if not mel.has_material_usage(mat, usage):
        mel.set_base_material_usage(mat, usage, True)
        mel.recompile_material(mat)
        if not unreal.EditorAssetLibrary.save_loaded_asset(mat):
            raise RuntimeError(f"Could not persist skeletal usage on {mat.get_path_name()}")
    if not mel.has_material_usage(mat, usage):
        raise RuntimeError(f"Skeletal usage is still disabled on {mat.get_path_name()}")
    return mat


def parent_material(roughness=0.7):
    """Create the parent or repair the usage flag on an existing asset."""
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(PARENT):
        return ensure_skeletal_usage(unreal.load_asset(PARENT))
    folder, name = PARENT.rsplit("/", 1)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    colour = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -400, 0)
    colour.set_editor_property("parameter_name", "Colour")
    colour.set_editor_property("default_value", unreal.LinearColor(0.1, 0.1, 0.12, 1.0))
    mel.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -400, 200)
    rough.set_editor_property("parameter_name", "Roughness")
    rough.set_editor_property("default_value", roughness)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    ensure_skeletal_usage(mat)
    mel.recompile_material(mat)
    if not unreal.EditorAssetLibrary.save_loaded_asset(mat):
        raise RuntimeError(f"Could not save new material {PARENT}")
    return mat


def instance(name, colour, roughness=0.7):
    """The flat material in one colour, as /Game/HQ/Materials/MI_HQ_Flat_<name>."""
    mel = unreal.MaterialEditingLibrary
    path = f"{FOLDER}/MI_HQ_Flat_{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mi = unreal.load_asset(path)
    else:
        folder, asset = path.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(asset, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent_material())
    mel.set_material_instance_vector_parameter_value(mi, "Colour", unreal.LinearColor(colour[0], colour[1], colour[2], 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "Roughness", roughness)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    return mi


def paint(actor, name, colour, roughness=0.7):
    """Puts that colour on every material slot of a static mesh actor."""
    mi = instance(name, colour, roughness)
    comp = actor.static_mesh_component
    for slot in range(comp.get_num_materials()):
        comp.set_material(slot, mi)
    return mi
