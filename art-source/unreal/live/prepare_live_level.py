"""
Readies /Game/HQ/HQ_Dusk to run as the live, streamed headquarters without rebuilding the scene.

The stream runs the level as a game, so player 0 has to look through the plate camera instead of
a free-flying default pawn. build_hq_scene.py sets this on every rebuild; this script applies it to
the level that already exists.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=live/prepare_live_level.py
"""

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
CAMERA_LABEL = "PlateCam"


def log(msg):
    unreal.log(f"AMN_LIVE {msg}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    cams = [a for a in actors if isinstance(a, unreal.CameraActor) and a.get_actor_label() == CAMERA_LABEL]
    if len(cams) != 1:
        raise RuntimeError(f"expected one {CAMERA_LABEL}, found {len(cams)}")
    cams[0].set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
    log(f"{CAMERA_LABEL} is player 0's camera")
    les.save_current_level()
    log(f"level saved {LEVEL}")


main()
