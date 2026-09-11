"""
Renders one still of the reference level through its PixelCam and quits the editor.
Runs inside the full editor (a viewport is needed for screenshots):

  UnrealEditor.exe AMNReference.uproject -ExecCmds="py <this file>" -unattended -nosplash

The PNG lands in AMNReference/Saved/Screenshots/WindowsEditor/. Reference material only.
"""

import os

import unreal

ZONE = os.environ.get("AMN_ZONE", "research")
LEVEL = f"/Game/Reference/{ZONE}/{ZONE.capitalize()}Floor"
WIDTH, HEIGHT = 1680, 284   # 2x the floor's 840 x 142 px frame

state = {"ticks": 0, "shot": False, "handle": None}


def find_camera():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if actor.get_actor_label() == "PixelCam":
            return actor
    return None


def tick(_dt):
    state["ticks"] += 1
    if state["ticks"] == 40 and not state["shot"]:
        state["shot"] = True
        cam = find_camera()
        unreal.log(f"AMN_UE screenshot via {cam.get_actor_label() if cam else 'viewport'}")
        unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, f"{ZONE}_reference.png", cam)
    if state["ticks"] == 260:
        unreal.log("AMN_UE quitting")
        unreal.unregister_slate_post_tick_callback(state["handle"])
        unreal.SystemLibrary.quit_editor()


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not les.load_level(LEVEL):
    raise RuntimeError(f"cannot load {LEVEL}")
unreal.log(f"AMN_UE level {LEVEL} loaded")
state["handle"] = unreal.register_slate_post_tick_callback(tick)
