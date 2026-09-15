"""
Unreal Engine 5.8 editor script: turns Nanite off on the live headquarters' merged scene meshes named in
AMN_NANITE_OFF (comma-separated actor labels, default "glow_details"), in place, with the stream stopped:

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=nanite_hq_live.py

The import makes every merged mesh a Nanite mesh. On the S1 server racks the green LEDs (small,
separate boxes) never showed, at any size or strength, while long continuous lights of the same
"glow_details" mesh (the rack bars, the room's grid) did. Nanite's simplification of small disconnected
parts was the cause: with Nanite off on that mesh (904 -> 2586 triangles) the racks show rows of green
and amber dots like the Owner's picture (2026-09-15). rebuild_live_hq.ps1 runs this after every level
build, since the import makes the meshes Nanite again. Tried on "props" as well (the rooms' furniture,
books and desk items): the same 105,688 triangles, no visible change and the same mean (14.4), so only
the small lights' mesh is changed.

StaticMeshEditorSubsystem.set_nanite_settings is not available in a commandlet, so the mesh's own
nanite_settings property is set (set_editor_property notifies the change, which rebuilds the mesh) and
the asset is saved.
"""

import os

import unreal

LEVEL = "/Game/HQ/HQ_Dusk"
OFF = [n.strip() for n in os.environ.get("AMN_NANITE_OFF", "glow_details").split(",") if n.strip()]


def log(msg):
    unreal.log(f"AMN_NANITE {msg}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    done = 0
    for actor in eas.get_all_level_actors():
        if actor.get_actor_label() not in OFF or not isinstance(actor, unreal.StaticMeshActor):
            continue
        mesh = actor.static_mesh_component.get_editor_property("static_mesh")
        if mesh is None:
            continue
        settings = mesh.get_editor_property("nanite_settings")
        before = settings.get_editor_property("enabled")
        settings.set_editor_property("enabled", False)
        mesh.set_editor_property("nanite_settings", settings)
        after = mesh.get_editor_property("nanite_settings").get_editor_property("enabled")
        saved = unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        log(f"{actor.get_actor_label()}: {mesh.get_path_name()} nanite {before} -> {after}, "
            f"triangles now {mesh.get_num_triangles(0)}, saved {saved}")
        done += 1
    log(f"{done} mesh(es) changed")


main()
