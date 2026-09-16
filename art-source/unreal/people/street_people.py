"""
Unreal Engine 5.8 editor script: the passers-by on the pavement of the live headquarters.

The Owner's picture has people on the terrace in front of the building, not only at the desks. This
places the MetaHumans built from people/street_people.json (rig_employees.py with
AMN_PEOPLE_CONFIG=street_people.json) on the pavement, each facing the viewer, with a standing loop
from ActorCore Sample Motions retargeted onto the MetaHuman skeleton (people/mh_retarget.py).

They stand rather than walk on purpose: the Owner asked that every character face the viewer, and a
walk loop across the frame would show them in profile. Actors are labelled street_<Name> and tagged
AMN_STREET, so a rerun replaces them and nothing else in the level is touched.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=people/street_people.py
"""

import importlib.util
import json
import math
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "street_people.json"), "r", encoding="utf-8"))
LEVEL = "/Game/HQ/HQ_Dusk"
TAG = "AMN_STREET"
YAW = float(os.environ.get("AMN_STREET_YAW", "0"))  # 0: the MetaHuman body's +Y faces the camera

# (name, column px, depth in metres, the dummy the motion was recorded on, the motion)
# Depth: the terrace in front of the building ends at y = -2.33 m and the pavement runs from there to
# -8.78 m, so the passers-by stand between them, around the bench at y = -3.7 (the first placing put
# them at y = +1, which is inside the rooms).
# The motions are named so their retargeted copies cannot collide: the pack has an "Idle_Anim" in the
# male folder and another in the female dance folder, and both would be cached as "Idle_Anim_MH".
STANDS = (
    ("Passer_Radu", 872, -3.4, "Dummy_Male", "Idle_walk_sit_Male_Motion/Male_idle_Anim"),
    ("Passer_Ana", 947, -2.9, "Dummy_Female", "Idle_walk_sit_Female_Motion/Stand_talk_Anim"),
    ("Passer_Dan", 1243, -3.2, "Dummy_Male", "Idle_walk_sit_Male_Motion/Male_idle_Anim"),
)

# The MetaHuman plugin ships one garment (a shirt and shorts in white), and each built person gets
# its own material instances for it. In front of the building three people in white underclothes read
# as exactly that, so each passer-by's shirt and shorts are tinted: at the plate's scale (a person is
# about 50 px tall) a dark top over darker legs reads as street clothes.
CLOTHES = {
    "Passer_Radu": ((0.06, 0.08, 0.14), (0.16, 0.16, 0.18)),
    "Passer_Ana": ((0.20, 0.10, 0.12), (0.10, 0.11, 0.16)),
    "Passer_Dan": ((0.10, 0.14, 0.12), (0.13, 0.12, 0.12)),
    "Passer_Irina": ((0.22, 0.09, 0.10), (0.09, 0.10, 0.14)),
}
# what the garment's material (M_DG_bodyShapeB_Shirt / _Short) exposes for its colour: the fabric's
# two diffuse tints, its "C" layer and the second body-shape's tint. All of them are set, since which
# one shows depends on the garment's masks.
COLOR_PARAMS = ("diffuse_color_1", "diffuse_color_2", "B_diffuse_color_1", "C_color")


def dress_actor(actor, name):
    """Puts a plain lit material on every garment component of a spawned passer-by. The plugin's one
    garment is white underclothes; tinting its own material instances left some pieces white."""
    shirt, _ = CLOTHES.get(name, (None, None))
    if shirt is None:
        return "no colours"
    mi = flat.instance(f"Cloth_{name}", shirt, roughness=0.8)
    dressed = []
    for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
        label = comp.get_name().lower()
        if label.startswith(("body", "face", "hair", "eyebrow", "eyelash", "beard", "mustache", "fuzz", "eye")):
            continue
        for slot in range(comp.get_num_materials()):
            comp.set_material(slot, mi)
        dressed.append(comp.get_name())
    return ",".join(dressed) if dressed else "no garment component"


def write_overrides(mi, names, value):
    """Sets vector parameter overrides on a material instance by hand; returns the names written."""
    values = list(mi.get_editor_property("vector_parameter_values"))
    by_name = {str(v.get_editor_property("parameter_info").get_editor_property("name")): v for v in values}
    written = []
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            info = unreal.MaterialParameterInfo()
            info.set_editor_property("name", unreal.Name(name))
            entry = unreal.VectorParameterValue()
            entry.set_editor_property("parameter_info", info)
            values.append(entry)
        entry.set_editor_property("parameter_value", value)
        written.append(name)
    mi.set_editor_property("vector_parameter_values", values)
    return written


def tint_clothes(name):
    """Colours a passer-by's shirt and shorts; returns what was set, for the report."""
    shirt, shorts = CLOTHES.get(name, (None, None))
    if shirt is None:
        return "no colours"
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    mel = unreal.MaterialEditingLibrary
    done = []
    for data in registry.get_assets_by_path(f"{CONFIG['built_path']}/{name}", recursive=True):
        asset_name = str(data.asset_name)
        if not asset_name.startswith("MI_WI_DefaultGarment"):
            continue
        colour = shorts if asset_name.endswith("Short") else shirt
        mi = unreal.load_asset(str(data.package_name))
        value = unreal.LinearColor(colour[0], colour[1], colour[2], 1.0)
        took = [param for param in COLOR_PARAMS
                if mel.set_material_instance_vector_parameter_value(mi, param, value)]
        if not took:
            # MaterialEditingLibrary refuses parameters the instance does not already override, so the
            # overrides are written straight onto the instance
            took = write_overrides(mi, COLOR_PARAMS, value)
        if took:
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            done.append(f"{asset_name.split('_')[-1]}:{len(took)}")
    return ", ".join(done) if done else "no colour parameter took"


# (name, column px, depth m, dummy, seated motion, the second of the loop where the face is towards
# the viewer). The bench the dressing script places stands at column 917, y -3.71.
SITS = (
    ("Passer_Irina", 917, -3.71, "Dummy_Female", "Idle_walk_sit_Female_Motion/Female_Sit_talk_Anim", 9.0),
)

_dress = importlib.util.spec_from_file_location("dress", os.path.join(os.path.dirname(HERE), "dress_hq_live.py"))
_retarget = importlib.util.spec_from_file_location("mh_retarget", os.path.join(HERE, "mh_retarget.py"))
_flat_spec = importlib.util.spec_from_file_location("flat_material", os.path.join(os.path.dirname(HERE), "flat_material.py"))
flat = importlib.util.module_from_spec(_flat_spec)
_flat_spec.loader.exec_module(flat)


def log(msg):
    unreal.log(f"AMN_STREET {msg}")


def projection():
    """X(), Y(), ue() and the pavement heights from the dressing script, without running it."""
    source = open(_dress.origin, "r", encoding="utf-8").read()
    head = source.split("APT = ")[0]
    ns = {"os": os, "math": math, "unreal": unreal, "__file__": _dress.origin, "__name__": "dress_head"}
    exec(compile(head, _dress.origin, "exec"), ns)
    return ns


def retarget_module():
    module = importlib.util.module_from_spec(_retarget)
    _retarget.loader.exec_module(module)
    return module


def built(name):
    """(blueprint class, body mesh) of a built passer-by, or (None, None)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    folder = f"{CONFIG['built_path']}/{name}"
    assets = registry.get_assets_by_path(folder, recursive=True)
    blueprints = [a for a in assets if str(a.asset_class_path.asset_name) == "Blueprint"]
    bodies = [a for a in assets if str(a.asset_class_path.asset_name) == "SkeletalMesh" and "body" in str(a.asset_name).lower()]
    bodies = bodies or [a for a in assets if str(a.asset_class_path.asset_name) == "SkeletalMesh"]
    if not blueprints or not bodies:
        return None, None
    return (unreal.EditorAssetLibrary.load_blueprint_class(str(blueprints[0].package_name)),
            unreal.load_asset(str(bodies[0].package_name)))


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if TAG in [str(t) for t in actor.get_editor_property("tags")] or actor.get_actor_label().startswith("street_Passer"):
            eas.destroy_actor(actor)
    ns = projection()
    retarget = retarget_module()
    report = {}
    for name, xpx, y_m, dummy, anim_rel in STANDS:
        bp_class, body_mesh = built(name)
        if bp_class is None:
            report[name] = "not built yet"
            continue
        try:
            anim = retarget.retargeted(dummy, anim_rel, body_mesh)
            # the terrace in front of the building, or the pavement below it
            ground = ns["TERRACE_Z"] if y_m >= ns["Y"](676, ns["TERRACE_Z"]) else ns["WALK_Z"]
            actor = eas.spawn_actor_from_class(bp_class, ns["ue"](ns["X"](xpx), y_m, ground),
                                               unreal.Rotator(roll=0.0, pitch=0.0, yaw=YAW))
            actor.set_actor_label(f"street_{name}")
            actor.set_editor_property("tags", [unreal.Name(TAG)])
            played = False
            for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                if comp.get_name().lower().startswith("body") and anim is not None:
                    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                    comp.set_animation(anim)
                    comp.set_editor_property("animation_data", unreal.SingleAnimationPlayData(anim_to_play=anim, saved_looping=True, saved_playing=True))
                    played = True
            dressed = f"{tint_clothes(name)} / {dress_actor(actor, name)}"
            report[name] = f"standing at column {xpx}, clothes {dressed}" + ("" if played else " (no standing loop)")
        except Exception as err:  # noqa: BLE001 - one passer-by must not stop the others
            report[name] = f"FAILED {type(err).__name__}: {err}"
    for name, xpx, y_m, dummy, anim_rel, front_s in SITS:
        bp_class, body_mesh = built(name)
        if bp_class is None:
            report[name] = "not built yet"
            continue
        try:
            anim = retarget.retargeted(dummy, anim_rel, body_mesh)
            actor = eas.spawn_actor_from_class(bp_class, ns["ue"](ns["X"](xpx), y_m, ns["WALK_Z"]),
                                               unreal.Rotator(roll=0.0, pitch=0.0, yaw=YAW))
            actor.set_actor_label(f"street_{name}")
            actor.set_editor_property("tags", [unreal.Name(TAG)])
            for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                if comp.get_name().lower().startswith("body") and anim is not None:
                    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                    comp.set_animation(anim)
                    # held on the frame that faces the viewer, as the employees are: played on, the
                    # seated loop turns her away
                    comp.set_editor_property("animation_data", unreal.SingleAnimationPlayData(
                        anim_to_play=anim, saved_looping=False, saved_playing=False, saved_position=front_s))
            report[name] = f"sitting on the bench at column {xpx}, clothes {tint_clothes(name)} / {dress_actor(actor, name)}"
        except Exception as err:  # noqa: BLE001 - one passer-by must not stop the others
            report[name] = f"FAILED {type(err).__name__}: {err}"
    # the retargeted loops live in the people folder: without saving it the game finds no animation
    # and every passer-by stands in the mesh's own A-pose
    unreal.EditorAssetLibrary.save_directory(retarget.ANIM_OUT)
    les.save_current_level()
    log(f"summary {json.dumps(report)}")


main()
