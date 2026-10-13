"""Diagnostic: load /Game/HQ/HQ_Dusk and log what the post-process volume and the plate camera
actually store (exposure overrides, method, bias, unbound, blend weights).

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_look.py
"""

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"


def log(msg):
    unreal.log(f"AMN_PROBE {msg}")


def dump(label, s):
    for name in ("override_auto_exposure_method", "auto_exposure_method", "override_auto_exposure_bias", "auto_exposure_bias",
                 "override_auto_exposure_apply_physical_camera_exposure", "auto_exposure_apply_physical_camera_exposure",
                 "override_bloom_intensity", "bloom_intensity"):
        try:
            log(f"{label}.{name} = {getattr(s, name)}")
        except Exception as err:
            log(f"{label}.{name} unreadable: {err}")


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if not les.load_level(LEVEL):
    raise RuntimeError(f"cannot load {LEVEL}")
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for actor in eas.get_all_level_actors():
    if isinstance(actor, unreal.PostProcessVolume):
        log(f"volume {actor.get_actor_label()} unbound={actor.get_editor_property('unbound')} priority={actor.get_editor_property('priority')} blend_weight={actor.get_editor_property('blend_weight')} enabled={actor.get_editor_property('enabled')}")
        dump("volume", actor.get_editor_property("settings"))
    if isinstance(actor, unreal.CameraActor):
        comp = actor.camera_component
        log(f"camera {actor.get_actor_label()} pp_blend_weight={comp.get_editor_property('post_process_blend_weight')}")
        dump("camera", comp.get_editor_property("post_process_settings"))
log("done")
