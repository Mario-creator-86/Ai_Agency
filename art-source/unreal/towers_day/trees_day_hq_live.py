"""
Unreal Engine 5.8 editor script (PREPARED 2026-09-24, NEVER RUN YET): the street trees' leaves take
the day's light, in place on the saved level, with the stream stopped:

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=<this file>

Why the crowns read as near-black cards at noon (measured on disk 2026-09-24): the leaves are the
SoulCity tree SM_S_BuildingSetA_Tree_02_OP02 with /Game/HQ/Materials/MI_HQ_TreeLeavesGreen (parent
M_LV_Soul_Tree02: Default Lit, masked, two-sided, base colour from the DiffuseandAlpha texture).
Its texture is T_HQ_Leaves_Green, which green_leaves.py darkened to value 0.4 so the uplit crowns
matched the dusk picture: a mean linear albedo of 0.021, where the pack's own leaves are 0.100 and
real foliage about 0.08-0.12. Under the noon sun a 2 % albedo is black.

What this does: M_LV_Soul_Tree02 is duplicated to /Game/HQ/Materials/M_HQ_TreeLeaves_v1 (the pack's
own stays untouched) with one change at its base colour output:
    original x lerp(1, LeafDayGain, LeafDaylight)
LeafDaylight is 0 by default, so the copy paints the dusk crowns exactly; MI_HQ_TreeLeavesGreen is
re-parented onto it, its values compared before and after (the pass fails on any difference), and
LeafDayGain set to towers_day.json's leaf_day_gain (the pack's albedo over ours, about 4.7): by day
the leaves are the pack's own brightness, still green. Nothing moves until something writes
LeafDaylight on the tree actors' components (drive_day_extra.py in the window; the backend patch).

dress_hq_live.py re-parents MI_HQ_TreeLeavesGreen to the pack master on every rebuild, so a rebuild
must run this again after it (see the window brief).
"""

import datetime
import importlib.util
import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("AMN_REPO", r"E:/AI Acency/Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP")
UNREAL_DIR = os.path.join(REPO, "art-source", "unreal")
LEVEL = "/Game/HQ/HQ_Dusk"
MASKS = os.environ.get("AMN_TOWER_MASKS", os.path.join(HERE, "textures"))
FACTS = json.load(open(os.path.join(MASKS, "towers_day.json"), "r", encoding="utf-8"))
REPORT = os.environ.get("AMN_TOWER_REPORT", os.path.join(HERE, "towers_report.json"))
PACK_MASTER = "/Game/SoulCity/Environment/Materials/Foliage/M_LV_Soul_Tree02"
LEAF_MI = "/Game/HQ/Materials/MI_HQ_TreeLeavesGreen"
COPY = "/Game/HQ/Materials/M_HQ_TreeLeaves_v1"
GAIN = float(os.environ.get("AMN_LEAF_DAY_GAIN", str(FACTS.get("leaf_day_gain", 4.7))))

_wspec = importlib.util.spec_from_file_location("window_view", os.path.join(UNREAL_DIR, "window_view.py"))
_window = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(_window)
mel = unreal.MaterialEditingLibrary


def log(msg):
    unreal.log(f"AMN_TREES_DAY {msg}")


def values(mat):
    out = {}
    for n in mel.get_scalar_parameter_names(mat):
        out[f"scalar:{n}"] = float(mel.get_material_instance_scalar_parameter_value(mat, n))
    for n in mel.get_vector_parameter_names(mat):
        c = mel.get_material_instance_vector_parameter_value(mat, n)
        out[f"vector:{n}"] = (c.r, c.g, c.b, c.a)
    for n in mel.get_texture_parameter_names(mat):
        t = mel.get_material_instance_texture_parameter_value(mat, n)
        out[f"texture:{n}"] = t.get_path_name() if t else None
    for n in mel.get_static_switch_parameter_names(mat):
        out[f"switch:{n}"] = bool(mel.get_material_instance_static_switch_parameter_value(mat, n))
    return out


def leaves_master():
    if unreal.EditorAssetLibrary.does_asset_exist(COPY):
        return unreal.load_asset(COPY)
    mat = unreal.EditorAssetLibrary.duplicate_asset(PACK_MASTER, COPY)
    if mat is None:
        raise RuntimeError(f"could not copy {PACK_MASTER} to {COPY}")
    if mat.get_editor_property("use_material_attributes"):
        raise RuntimeError(f"{COPY} uses material attributes")
    prop = unreal.MaterialProperty.MP_BASE_COLOR
    src = mel.get_material_property_input_node(mat, prop)
    out = mel.get_material_property_input_node_output_name(mat, prop)
    if src is None:
        raise RuntimeError(f"{COPY}: nothing drives the base colour")
    if out == "" and len(mel.get_material_expression_output_names(src)) > 1:
        raise RuntimeError(f"{COPY}: the base colour comes from an unnamed output of {src.get_name()}")

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, 1200 + x, -1200 + y)

    daylight = node(unreal.MaterialExpressionScalarParameter, 0, 0)
    daylight.set_editor_property("parameter_name", "LeafDaylight")
    daylight.set_editor_property("default_value", 0.0)
    gain = node(unreal.MaterialExpressionScalarParameter, 0, 150)
    gain.set_editor_property("parameter_name", "LeafDayGain")
    gain.set_editor_property("default_value", 1.0)
    factor = node(unreal.MaterialExpressionLinearInterpolate, 250, 50)
    factor.set_editor_property("const_a", 1.0)
    mel.connect_material_expressions(gain, "", factor, "B")
    mel.connect_material_expressions(daylight, "", factor, "Alpha")
    times = node(unreal.MaterialExpressionMultiply, 500, 0)
    mel.connect_material_expressions(src, out, times, "A")
    mel.connect_material_expressions(factor, "", times, "B")
    clamp = node(unreal.MaterialExpressionSaturate, 700, 0)
    mel.connect_material_expressions(times, "", clamp, "")
    if not mel.connect_material_property(clamp, "", prop):
        raise RuntimeError("could not connect the extended base colour")
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log(f"{PACK_MASTER} copied to {COPY}, base colour x lerp(1, LeafDayGain, LeafDaylight)")
    return mat


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    mi = unreal.load_asset(LEAF_MI)
    if mi is None:
        raise RuntimeError(f"{LEAF_MI} missing: dress_hq_live.py makes it (AMN_TREES=soul)")
    master = leaves_master()
    before = values(mi)
    # a saturate after the multiply: at LeafDaylight 0 the factor is 1 and the texture is in 0..1,
    # so saturate changes nothing there
    if mi.get_editor_property("parent") != master:
        mel.set_material_instance_parent(mi, master)
    mel.set_material_instance_scalar_parameter_value(mi, "LeafDayGain", GAIN)
    mel.update_material_instance(mi)
    changed = _window.differences(before, values(mi))
    if changed:
        raise RuntimeError(f"re-parented leaves do not repeat today's values: {changed[:6]}")
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    trees = []
    for actor in eas.get_all_level_actors():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        if any(comp.get_material(i) == mi for i in range(comp.get_num_materials())):
            trees.append({"label": actor.get_actor_label(), "component": comp.get_path_name(), "parameters": ["LeafDaylight"]})
    log(f"leaves re-parented, all {len(before)} old values unchanged, day gain {GAIN:g}; {len(trees)} tree actors: {[t['label'] for t in trees]}")
    report = json.load(open(REPORT, "r", encoding="utf-8")) if os.path.exists(REPORT) else {}
    report.update({"level": LEVEL, "written_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "trees": trees})
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log("saved")


main()
