"""
Unreal Engine 5.8 editor script: turns the seated MetaHuman employees of the live headquarters
(/Game/HQ/HQ_Dusk) in place to face the viewer, with the stream stopped:

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=people/turn_employees.py

The Owner wants every character facing the viewer, never side-on or from behind. seat_employees.py
spawned them at yaw 90 (the actor's +X forward pointing at the camera), but each blueprint's body mesh
keeps a relative rotation of 0, and a MetaHuman mesh faces along its own +Y: turned 90 degrees, that
front points across the frame, so every employee sat in profile (seen in the stream, 2026-09-15). The
actors are rotated, not respawned, so the object paths the backend's Remote Control bridge uses stay
valid. AMN_SEAT_YAW sets the yaw (degrees).
"""

import os

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
YAW = float(os.environ.get("AMN_SEAT_YAW", "0"))


def log(msg):
    unreal.log(f"AMN_TURN {msg}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    turned = []
    for actor in eas.get_all_level_actors():
        label = actor.get_actor_label()
        if not label.startswith("employee_"):
            continue
        rot = actor.get_actor_rotation()
        actor.set_actor_rotation(unreal.Rotator(roll=rot.roll, pitch=rot.pitch, yaw=YAW), False)
        turned.append(f"{label} {rot.yaw:g}->{YAW:g}")
    les.save_current_level()
    log(f"{len(turned)} employees turned: {turned}")


main()
