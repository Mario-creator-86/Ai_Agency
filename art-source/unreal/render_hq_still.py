"""
Renders a still of the headquarters level through its PlateCam and quits the editor. Runs inside
the full editor (screenshots need a viewport):

  UnrealEditor.exe AMNReference.uproject -ExecCmds="py render_hq_still.py" -unattended -nosplash

Waits for Lumen and the volumetric clouds to settle before the shot. The PNG lands in
AMNReference/Saved/Screenshots/WindowsEditor/hq_dusk.png. Size from AMN_STILL (default 3200x1680,
twice the web scene's 1600x840 world).
"""

import os

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
WIDTH, HEIGHT = (int(v) for v in os.environ.get("AMN_STILL", "3200x1680").split("x"))
SETTLE_TICKS = int(os.environ.get("AMN_SETTLE", "400"))

state = {"ticks": 0, "shot": False, "handle": None}


def camera():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if actor.get_actor_label() == "PlateCam":
            return actor
    return None


EXPOSURE = float(os.environ.get("AMN_EV", "0"))


def tick(_dt):
    state["ticks"] += 1
    if state["ticks"] == 2:
        # The editor's screenshot ignores post-process exposure on the volume and on the camera
        # (probe_look.py and two renders showed identical images), so exposure is applied through
        # the renderer's own offset, with eye adaptation on so the offset takes effect.
        # Lights at a third of their intensity rendered the identical image, so the capture may be
        # unlit: force the lit view mode and the lighting show flags before anything else.
        for command in ("viewmode lit", "ShowFlag.Lighting 1", "ShowFlag.DirectLighting 1", "ShowFlag.GlobalIllumination 1", "ShowFlag.EyeAdaptation 1", f"r.ExposureOffset {EXPOSURE}"):
            unreal.SystemLibrary.execute_console_command(None, command)
            unreal.log(f"AMN_UE console {command}")
    if state["ticks"] == SETTLE_TICKS and not state["shot"]:
        state["shot"] = True
        cam = camera()
        unreal.log(f"AMN_UE screenshot {WIDTH}x{HEIGHT} via {cam.get_actor_label() if cam else 'viewport'}")
        unreal.AutomationLibrary.take_high_res_screenshot(WIDTH, HEIGHT, "hq_dusk.png", cam)
    if state["ticks"] == SETTLE_TICKS + 300:
        unreal.log("AMN_UE quitting")
        unreal.unregister_slate_post_tick_callback(state["handle"])
        unreal.SystemLibrary.quit_editor()


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not les.load_level(LEVEL):
    raise RuntimeError(f"cannot load {LEVEL}")
unreal.log(f"AMN_UE level {LEVEL} loaded")
state["handle"] = unreal.register_slate_post_tick_callback(tick)
