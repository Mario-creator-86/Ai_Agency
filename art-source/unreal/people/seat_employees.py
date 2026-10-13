"""
Unreal Engine 5.8 editor script: seats the built MetaHuman employees at their desks in the live
headquarters (/Game/HQ/HQ_Dusk), facing the viewer, with a seated animation.

1. Retargets ActorCore Sample Motions' seated animations (Male_Sit_talk_Anim, Female_Sit_talk_Anim)
   from the ActorCore dummies' IK rigs onto the MetaHuman IK rig, once, into
   /Game/AMN/People/Animations (an IK Retargeter is created for each dummy and its chains mapped
   automatically).
2. For every employee of employees.json built into <built_path>/<Name>, spawns the built MetaHuman
   blueprint at the employee's seat (the same seats and projection dress_hq_live.py uses), turned
   to the camera, and plays the seated animation on its body in a loop (single-node animation mode,
   so no Animation Blueprint is needed). Earlier employees placed by this script are replaced.

3. Writes seat_report.json beside this script: desk by desk, the actor, its body component and its
   animation as object paths. The backend's Unreal bridge (backend/app/office/unreal.py) reads it
   to show and animate each employee from the studio's state over Remote Control.

Employees not built yet are skipped and reported. Run after rig_employees.py and dress_hq_live.py:

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=people/seat_employees.py
"""

import importlib.util
import json
import math
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "employees.json"), "r", encoding="utf-8"))
LEVEL = "/Game/HQ/HQ_Dusk"
TAG = "AMN_EMPLOYEE"
ANIM_OUT = f"{CONFIG['people_path']}/Animations"  # where mh_retarget.py keeps the retargeted loops
SOURCES = {
    "man": ("Dummy_Male", "Idle_walk_sit_Male_Motion/Male_Sit_talk_Anim"),
    "woman": ("Dummy_Female", "Idle_walk_sit_Female_Motion/Female_Sit_talk_Anim"),
}
# The seated loops' frame (seconds) where the head looks the way the body faces, towards the viewer:
# played on, the talking loops turn the employees to their monitors, so the backend's bridge holds
# each one on this frame (the Owner wants every character facing the viewer). Found by sampling the
# head's direction over the loops and checked in the stream (2026-09-15).
# The men's 7.25 s was read off the head's direction alone; photographed at nine frames of the loop
# in the stream (0, 2, 4, 7.25, 10, 13, 16, 19, 22 s), it holds them with the head bowed over the
# desk. At 2 s the head is up and the face towards the viewer.
FRONT_S = {"Male_Sit_talk_Anim_MH": 2.0, "Female_Sit_talk_Anim_MH": 9.0}

# the seats and projection come from the dressing script, so both always agree
_spec = importlib.util.spec_from_file_location("dress", os.path.join(os.path.dirname(HERE), "dress_hq_live.py"))
# the retarget itself is shared with street_people.py
_retarget = importlib.util.spec_from_file_location("mh_retarget", os.path.join(HERE, "mh_retarget.py"))


def log(msg):
    unreal.log(f"AMN_SEAT {msg}")


def seats():
    """desk id -> (x_m, seat_y_m, floor_z_m), read from dress_hq_live.py without running it."""
    source = open(_spec.origin, "r", encoding="utf-8").read()
    head = source.split("APT = ")[0]  # constants and projection only, before any asset loading
    # the dressing script's head computes HERE from __file__; give it its own path
    ns = {"os": os, "math": math, "unreal": unreal, "__file__": _spec.origin, "__name__": "dress_head"}
    exec(compile(head, _spec.origin, "exec"), ns)
    return {d: (ns["X"](cx), seat_y, ns["fz"](level)) for d, cx, level, _side, seat_y in ns["SEATS"]}, ns["ue"]


def gender(person):
    return "woman" if person["bible"].lower().startswith("woman") else "man"


def asset_of_class(folder, class_name, name_part=""):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = [a for a in registry.get_assets_by_path(folder, recursive=True)
             if str(a.asset_class_path.asset_name) == class_name and name_part.lower() in str(a.asset_name).lower()]
    return sorted(found, key=lambda a: str(a.package_name))


def retargeted_sit(kind, target_mesh):
    """The seated animation for a dummy kind, retargeted onto the MetaHuman skeleton (cached)."""
    dummy, anim_rel = SOURCES[kind]
    module = importlib.util.module_from_spec(_retarget)
    _retarget.loader.exec_module(module)
    return module.retargeted(dummy, anim_rel, target_mesh)


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        # by label as well, so an actor of an earlier pass that failed before its tag was set is
        # still cleared instead of standing in the level twice
        if TAG in [str(t) for t in actor.get_editor_property("tags")] or actor.get_actor_label().startswith("employee_"):
            eas.destroy_actor(actor)
    seat_of, ue = seats()
    report = {}
    seated = []
    for person in CONFIG["employees"]:
        name = person["name"]
        built = f"{CONFIG['built_path']}/{name}"
        blueprints = asset_of_class(built, "Blueprint")
        bodies = asset_of_class(built, "SkeletalMesh", "body") or asset_of_class(built, "SkeletalMesh")
        if not blueprints or not bodies:
            report[name] = "not built yet"
            continue
        try:
            bp_class = unreal.EditorAssetLibrary.load_blueprint_class(str(blueprints[0].package_name))
            body_mesh = unreal.load_asset(str(bodies[0].package_name))
            # Retarget before spawning: creating the animation reinstances the blueprint, and an
            # actor spawned earlier had its components replaced (the first pass animated and
            # recorded "TRASH_SkeletalMeshComponent_8", which the game does not have).
            anim = retargeted_sit(gender(person), body_mesh)
            x_m, seat_y, floor_z = seat_of[person["desk"]]
            # the person sits between the desk (towards the camera) and the chair, facing the camera
            # Yaw 0: a MetaHuman body faces its own +Y and the blueprint leaves it unrotated, so at yaw 90
            # (the actor's +X toward the camera) every employee sat in profile; the Owner wants every
            # character facing the viewer (2026-09-15). turn_employees.py applies the same in place.
            yaw = float(os.environ.get("AMN_SEAT_YAW", "0"))
            actor = eas.spawn_actor_from_class(bp_class, ue(x_m, seat_y - 0.15, floor_z), unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
            actor.set_actor_label(f"employee_{name}")
            actor.set_editor_property("tags", [unreal.Name(TAG)])
            body = None
            for comp in actor.get_components_by_class(unreal.SkeletalMeshComponent):
                if comp.get_name().lower().startswith("body") and anim is not None:
                    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                    comp.set_animation(anim)
                    comp.set_editor_property("animation_data", unreal.SingleAnimationPlayData(anim_to_play=anim, saved_looping=True, saved_playing=True))
                    body = comp
            report[name] = f"seated at {person['desk']}" + ("" if body else " (no seated animation)")
            if body is not None:
                seated.append((person["desk"], name, actor, anim))
        except Exception as err:
            report[name] = f"FAILED {type(err).__name__}: {err}"
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory(CONFIG["people_path"])
    # The paths the running game will have, read after saving: the body is the actor's own "Body"
    # component, never a component a blueprint reinstance left behind as TRASH_*.
    entries = []
    for desk, name, actor, anim in seated:
        bodies_now = [c for c in actor.get_components_by_class(unreal.SkeletalMeshComponent)
                      if c.get_name().lower().startswith("body")]
        if not bodies_now:
            report[name] += " (no Body component after saving)"
            continue
        entries.append({"desk": desk, "name": name, "actor": actor.get_path_name(),
                        "body": f"{actor.get_path_name()}.{bodies_now[0].get_name()}", "animation": anim.get_path_name(),
                        "front_s": FRONT_S.get(anim.get_name(), 0.0)})
    seated = entries
    with open(os.path.join(HERE, "seat_report.json"), "w", encoding="utf-8") as out:
        json.dump({"level": LEVEL, "seats": seated}, out, indent=1)
    log(f"summary {json.dumps(report)}")


main()
