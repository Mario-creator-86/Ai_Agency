"""
Diagnostic: can an employee be built from one of the MetaHuman Creator's presets on this machine,
without the cloud rigging service?

Scans the Creator's optional content, lists the presets, duplicates one into /Game/AMN/People,
asks the editor subsystem whether it can be built, tries to build it with the default pipeline and
lists what the build produced.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_metahuman_build.py
"""

import traceback

import unreal

PRESET_ROOTS = ("/MetaHumanCharacter/Optional/Presets", "/MetaHumanCharacter/Optional")
PEOPLE = "/Game/AMN/People"
PROBE = "Probe_Preset"


def log(msg):
    unreal.log(f"AMN_MHB {msg}")


def main():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([PRESET_ROOTS[0]], True)
    presets = registry.get_assets_by_path(PRESET_ROOTS[0], recursive=False)
    chars = [a for a in presets if str(a.asset_class_path.asset_name) == "MetaHumanCharacter"]
    log(f"presets: {sorted(str(a.asset_name) for a in chars)}")
    log(f"MetaHumanCharacter presets: {len(chars)}")
    if not chars:
        return

    source = str(chars[0].package_name)
    target = f"{PEOPLE}/{PROBE}"
    if unreal.EditorAssetLibrary.does_asset_exist(target):
        unreal.EditorAssetLibrary.delete_asset(target)
    character = unreal.EditorAssetLibrary.duplicate_asset(source, target)
    log(f"duplicated {source} -> {target}: {character is not None}")
    if character is None:
        return
    for attr in ("has_face_dna", "has_body_dna", "has_synthesized_textures", "has_high_resolution_textures", "is_rigged"):
        fn = getattr(character, attr, None)
        if fn:
            try:
                log(f"character {attr} = {fn()}")
            except Exception as err:
                log(f"character {attr} unreadable: {err}")

    sub = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
    added = sub.try_add_object_to_edit(character)
    log(f"opened for editing: {added}")
    try:
        log(f"can_build_meta_human: {sub.can_build_meta_human(character)}")
        params = unreal.MetaHumanCharacterEditorBuildParameters()
        log("build params: " + ", ".join(n for n in dir(params) if not n.startswith("_") and n not in ("cast", "static_struct", "export_text", "import_text", "to_tuple")))
        try:
            params.set_editor_property("absolute_build_path", f"{PEOPLE}/Built")
        except Exception as err:
            log(f"absolute_build_path not set: {err}")
        result = sub.build_meta_human(character, params)
        log(f"build_meta_human returned {result!r}")
    except Exception as err:
        log(f"build ERROR {type(err).__name__}: {err}")
        for line in traceback.format_exc().splitlines()[-5:]:
            log(f"  {line}")
    finally:
        if sub.is_object_added_for_editing(character):
            sub.remove_object_to_edit(character)
    built = registry.get_assets_by_path(PEOPLE, recursive=True)
    log(f"assets now under {PEOPLE}: {len(built)}")
    for a in built[:40]:
        log(f"  {a.asset_class_path.asset_name} {a.package_name}")
    unreal.EditorAssetLibrary.save_directory(PEOPLE)


main()
