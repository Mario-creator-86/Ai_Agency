"""
Unreal Engine 5.8 editor script: the blue haze over the live headquarters' skyline (/Game/HQ/HQ_Dusk),
applied to the saved level in place, with the stream stopped (like look_hq_live.py):

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=haze_hq_live.py

The picture's city fades into a blue haze towards its base; the live skyline stands as black blocks
with sharp lit windows. Height fog cannot give that alone: its distances count from the plate
camera, 246 m in front of the building, and the scene's own fog (0.008 from 30 m) is also the veil
that lifts the building's black frame and the rooms; fog pushed out to the skyline only (0.12 from
260 m) hazed the towers but crushed the rest (mean colour distance 15.6 -> 29.7, 2026-09-15).

So the haze is drawn: two unlit, translucent planes across the frame, behind the building (whose
rooms end 2.5 m back) and in front of the city's layers, each fading from full strength at the
skyline's base to nothing towards the tower tops. The building, the street and its trees stand in
front of them and are untouched. Each tunable comes from the environment (AMN_HAZE_*); every value
is absolute, so a rerun gives the same level; AMN_HAZE_OPACITY=0 hides the planes.
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
META = json.load(open(os.path.join(HERE, "hq_scene.json"), "r", encoding="utf-8"))
MATERIAL = "/Game/HQ/Materials/M_HQ_SkylineHaze"
TAG = "AMN_HAZE"


def env(name, default):
    return float(os.environ.get(name, default))


def env_color(name, default):
    return [float(v) for v in os.environ.get(name, default).split(",")]


# Compared in the stream (mean colour distance over all regions; city left / city right): no haze
# 15.6 (22.2 / 20.2); opacity 0.35 fading out at row 260, 15.3 (20.9 / 17.4); opacity 0.55 fading
# out at row 160, 15.0 (24.1 / 12.0): the towers read blue and hazy on both sides, the left a little
# lighter than the picture's.
OPACITY = env("AMN_HAZE_OPACITY", "0.55")        # at the skyline's base, on the near plane
FAR_SHARE = env("AMN_HAZE_FAR_SHARE", "0.7")     # the far plane's opacity as a share of the near one's
COLOR = env_color("AMN_HAZE_COLOR", "0.07,0.09,0.2")  # linear, emissive: the near plane
# The far plane's own colour, so the towers behind the city can fade towards a lighter dusk than the
# streets in front of them. Tried light (0.30, 0.30, 0.42): on both planes it washed the left-hand
# city bright (its region 18.3 -> 50.1, mean 9.2 -> 12.1); on the far plane alone the right-hand city
# came to 9.0 (12.7) but the left went to 26.6 and the mean to 10.0, because the left's towers stand
# behind that plane too. Both planes keep the dark colour; the knob stays for the next attempt.
COLOR_FAR = env_color("AMN_HAZE_COLOR_FAR", "0.07,0.09,0.2")
BASE_ROW = env("AMN_HAZE_BASE_ROW", "560")       # frame row (of 840) below which the haze is full
TOP_ROW = env("AMN_HAZE_TOP_ROW", "160")         # frame row above which there is none
FALLOFF = env("AMN_HAZE_FALLOFF", "1.5")         # >1 keeps the haze low, near the base
# (label, Blender depth in metres): in front of the mid-rise city (14-20 m) and of the towers (30-65 m)
PLANES = (("SkylineHaze_near", 12.0), ("SkylineHaze_far", 27.0))


def log(msg):
    unreal.log(f"AMN_HAZE {msg}")


def ue(x_m, y_m, z_m):
    """Blender metres -> Unreal centimetres (the importer maps Blender +y to Unreal -y)."""
    return unreal.Vector(x_m * 100.0, -y_m * 100.0, z_m * 100.0)


def z_of(row, depth_m):
    """Height in metres that frame row `row` (0..840) shows at Blender depth `depth_m`
    (the plate camera's projection: row = 655 - 27.575 z - 4.862 y, as in build_hq_scene.py)."""
    return (655.0 - row - 4.862 * depth_m) / 27.575


def haze_material():
    """Unlit, translucent, two-sided: HazeColor as emission, and an opacity that is Opacity below
    BottomZ, nothing above TopZ, and a ((TopZ - z) / (TopZ - BottomZ)) ^ Falloff ramp between."""
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(MATERIAL):
        mat = unreal.load_asset(MATERIAL)
        mel.delete_all_material_expressions(mat)
    else:
        folder, name = MATERIAL.rsplit("/", 1)
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property("two_sided", True)

    def param(cls, name, value, x, y):
        node = mel.create_material_expression(mat, cls, x, y)
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("default_value", value)
        return node

    color = param(unreal.MaterialExpressionVectorParameter, "HazeColor", unreal.LinearColor(*COLOR, 1.0), -300, -200)
    mel.connect_material_property(color, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    world = mel.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -1200, 100)
    mask = mel.create_material_expression(mat, unreal.MaterialExpressionComponentMask, -1000, 100)
    for channel, keep in (("r", False), ("g", False), ("b", True), ("a", False)):
        mask.set_editor_property(channel, keep)
    mel.connect_material_expressions(world, "", mask, "")
    top = param(unreal.MaterialExpressionScalarParameter, "TopZ", 1000.0, -1000, 300)
    bottom = param(unreal.MaterialExpressionScalarParameter, "BottomZ", 0.0, -1000, 450)
    above = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -800, 150)
    mel.connect_material_expressions(top, "", above, "A")
    mel.connect_material_expressions(mask, "", above, "B")
    span = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -800, 350)
    mel.connect_material_expressions(top, "", span, "A")
    mel.connect_material_expressions(bottom, "", span, "B")
    ratio = mel.create_material_expression(mat, unreal.MaterialExpressionDivide, -600, 200)
    mel.connect_material_expressions(above, "", ratio, "A")
    mel.connect_material_expressions(span, "", ratio, "B")
    clamp = mel.create_material_expression(mat, unreal.MaterialExpressionSaturate, -450, 200)
    mel.connect_material_expressions(ratio, "", clamp, "")
    falloff = param(unreal.MaterialExpressionScalarParameter, "Falloff", 1.5, -450, 350)
    ramp = mel.create_material_expression(mat, unreal.MaterialExpressionPower, -300, 200)
    mel.connect_material_expressions(clamp, "", ramp, "Base")
    mel.connect_material_expressions(falloff, "", ramp, "Exp")
    opacity = param(unreal.MaterialExpressionScalarParameter, "Opacity", 0.3, -300, 400)
    strength = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -150, 250)
    mel.connect_material_expressions(ramp, "", strength, "A")
    mel.connect_material_expressions(opacity, "", strength, "B")
    mel.connect_material_property(strength, "", unreal.MaterialProperty.MP_OPACITY)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


def instance(parent, label, depth_m, opacity, color):
    mel = unreal.MaterialEditingLibrary
    path = f"/Game/HQ/Materials/MI_HQ_{label}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mi = unreal.load_asset(path)
    else:
        folder, name = path.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    mel.set_material_instance_vector_parameter_value(mi, "HazeColor", unreal.LinearColor(*color, 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "BottomZ", z_of(BASE_ROW, depth_m) * 100.0)
    mel.set_material_instance_scalar_parameter_value(mi, "TopZ", z_of(TOP_ROW, depth_m) * 100.0)
    mel.set_material_instance_scalar_parameter_value(mi, "Falloff", FALLOFF)
    mel.set_material_instance_scalar_parameter_value(mi, "Opacity", opacity)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    return mi


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if TAG in [str(t) for t in actor.get_editor_property("tags")]:
            eas.destroy_actor(actor)
    parent = haze_material()
    plane_mesh = unreal.load_asset("/Engine/BasicShapes/Plane")  # 100 x 100 cm, facing up
    width_m = META["camera"]["width_m"] + 12.0
    for label, depth_m in PLANES:
        far = label.endswith("far")
        opacity = OPACITY * (FAR_SHARE if far else 1.0)
        mi = instance(parent, label, depth_m, opacity, COLOR_FAR if far else COLOR)
        z0, z1 = z_of(760, depth_m), z_of(80, depth_m)
        # rolled a quarter turn about x, the plane stands upright across the frame; its local y
        # (scale y) becomes the height
        actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, ue(0.0, depth_m, (z0 + z1) / 2.0), unreal.Rotator(roll=90.0, pitch=0.0, yaw=0.0))
        comp = actor.static_mesh_component
        comp.set_static_mesh(plane_mesh)
        comp.set_material(0, mi)
        comp.set_cast_shadow(False)
        actor.set_actor_scale3d(unreal.Vector(width_m, z1 - z0, 1.0))
        actor.set_actor_label(label)
        actor.set_editor_property("tags", [unreal.Name(TAG)])
        actor.set_actor_hidden_in_game(opacity <= 0.0)
        origin, extent = actor.get_actor_bounds(False)
        log(f"{label} at depth {depth_m} m: opacity {opacity:.2f}, colour {COLOR_FAR if far else COLOR}, full below z {z_of(BASE_ROW, depth_m):.1f} m, none above {z_of(TOP_ROW, depth_m):.1f} m; "
            f"bounds centre ({origin.x:.0f}, {origin.y:.0f}, {origin.z:.0f}) extent ({extent.x:.0f}, {extent.y:.0f}, {extent.z:.0f}) cm")
    les.save_current_level()
    log("saved")


main()
