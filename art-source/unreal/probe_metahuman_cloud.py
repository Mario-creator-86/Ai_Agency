"""
Diagnostic: can this editor use the Owner's Epic session for MetaHuman cloud services?

Creates /Game/AMN/People/Probe_MetaHuman, then asks the MetaHuman service for texture sources and
for auto-rigging (both blocking, as the plugin's own batch examples do), logging each result or
error, and lists the subsystem's functions that mention login, auth or cloud.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_metahuman_cloud.py
  UnrealEditor.exe     AMNReference.uproject -ExecCmds="py probe_metahuman_cloud.py" -unattended
"""

import traceback

import unreal

PATH = "/Game/AMN/People"
NAME = "Probe_MetaHuman"


def log(msg):
    unreal.log(f"AMN_MH {msg}")


def main():
    subsystem = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
    names = [n for n in dir(subsystem) if any(k in n.lower() for k in ("login", "auth", "cloud", "logged", "service", "request", "can_"))]
    log(f"subsystem functions: {names}")

    asset_path = f"{PATH}/{NAME}"
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        character = unreal.load_asset(asset_path)
        log("reusing existing probe character")
    else:
        character = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name=NAME,
            package_path=PATH,
            asset_class=unreal.MetaHumanCharacter,
            factory=unreal.new_object(type=unreal.MetaHumanCharacterFactoryNew),
        )
        log(f"created character: {character is not None}")
    if character is None:
        log("RESULT create FAILED")
        return

    if not subsystem.try_add_object_to_edit(character):
        log("RESULT could not open the character for editing")
        return
    try:
        for label, run in (
            ("textures", lambda: _textures(subsystem, character)),
            ("auto_rigging", lambda: _rig(subsystem, character)),
        ):
            try:
                result = run()
                log(f"RESULT {label} returned {result!r}")
            except Exception as err:  # the probe reports every failure, it does not stop at the first
                log(f"RESULT {label} ERROR {type(err).__name__}: {err}")
                for line in traceback.format_exc().splitlines()[-6:]:
                    log(f"  {line}")
        for check in ("has_high_resolution_textures", "is_rigged", "get_rig_state", "has_face_rig"):
            fn = getattr(subsystem, check, None)
            if fn:
                try:
                    log(f"STATE {check} = {fn(character)!r}")
                except Exception as err:
                    log(f"STATE {check} unreadable: {err}")
    finally:
        if subsystem.is_object_added_for_editing(character):
            subsystem.remove_object_to_edit(character)
    unreal.EditorAssetLibrary.save_directory(PATH)
    log("done")


def _textures(subsystem, character):
    params = unreal.MetaHumanCharacterTextureRequestParams()
    params.blocking = True
    params.report_progress = False
    return subsystem.request_texture_sources(character, params)


def _rig(subsystem, character):
    params = unreal.MetaHumanCharacterAutoRiggingRequestParams()
    params.blocking = True
    params.report_progress = False
    params.rig_type = unreal.MetaHumanRigType.JOINTS_ONLY
    return subsystem.request_auto_rigging(character, params)


main()
