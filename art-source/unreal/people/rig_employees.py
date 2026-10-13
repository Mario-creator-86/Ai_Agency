"""
Unreal Engine 5.8 editor script: turns each employee of people/employees.json into a MetaHuman.

For every employee: the named MetaHuman Creator preset is duplicated to <people_path>/<Name>, rigged
by the MetaHuman service (auto-rigging, blocking), given its source textures (blocking), and built
with the default pipeline into <built_path>/<Name>. Employees already built are skipped, so the
script can be run again after a failure.

The rigging and texture services need the Owner's Epic account. The first time, run it inside an
editor the Epic Games Launcher opens (a commandlet with no Epic session asks for a device login),
from the Output Log's Cmd box:

  py "E:/AI Acency/Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP/art-source/unreal/people/rig_employees.py"

Once that login is remembered, rig_in_editor.py runs it unattended in the full editor. Not in a
commandlet: the build's groom texture bake (TextureGraph) crashes there before the engine ticks.
Stop the live stream first; builds are memory-hungry.

AMN_PEOPLE_ONLY=Sarah,Aris limits the run to some employees; AMN_PEOPLE_CONFIG=street_people.json
builds the street's passers-by instead.
"""

import json
import os
import traceback

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
# AMN_PEOPLE_CONFIG names another file of the same shape (street_people.json: the passers-by on
# the pavement, built the same way into their own folder)
CONFIG_NAME = os.environ.get("AMN_PEOPLE_CONFIG", "employees.json")
CONFIG = json.load(open(os.path.join(HERE, CONFIG_NAME), "r", encoding="utf-8"))
PRESETS = "/MetaHumanCharacter/Optional/Presets"
ONLY = {n.strip() for n in os.environ.get("AMN_PEOPLE_ONLY", "").split(",") if n.strip()}


def log(msg):
    unreal.log(f"AMN_PEOPLE {msg}")


def built_already(name):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    return bool(registry.get_assets_by_path(f"{CONFIG['built_path']}/{name}", recursive=True))


def character_for(person):
    target = f"{CONFIG['people_path']}/{person['name']}"
    if unreal.EditorAssetLibrary.does_asset_exist(target):
        return unreal.load_asset(target)
    source = f"{PRESETS}/{person['preset']}"
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([PRESETS], True)
    if not unreal.EditorAssetLibrary.does_asset_exist(source):
        raise RuntimeError(f"preset {source} not found")
    return unreal.EditorAssetLibrary.duplicate_asset(source, target)


def rig(sub, character):
    params = unreal.MetaHumanCharacterAutoRiggingRequestParams()
    params.set_editor_property("blocking", True)
    params.set_editor_property("report_progress", False)
    return sub.request_auto_rigging(character, params)


def textures(sub, character):
    params = unreal.MetaHumanCharacterTextureRequestParams()
    params.set_editor_property("blocking", True)
    params.set_editor_property("report_progress", False)
    return sub.request_texture_sources(character, params)


def build(sub, character, name):
    params = unreal.MetaHumanCharacterEditorBuildParameters()
    params.set_editor_property("absolute_build_path", f"{CONFIG['built_path']}/{name}")
    params.set_editor_property("name_override", name)
    return sub.build_meta_human(character, params)


def main():
    sub = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
    results = {}
    for person in CONFIG.get("employees") or CONFIG["people"]:
        name = person["name"]
        if ONLY and name not in ONLY:
            continue
        if built_already(name):
            results[name] = "already built"
            continue
        try:
            character = character_for(person)
            if not sub.try_add_object_to_edit(character):
                raise RuntimeError("could not open the character for editing")
            try:
                if not sub.can_build_meta_human(character):
                    log(f"{name}: rigging")
                    rig(sub, character)
                    log(f"{name}: textures")
                    textures(sub, character)
                if not sub.can_build_meta_human(character):
                    raise RuntimeError("still not ready to build after rigging (see LogMetaHumanCharacterEditor)")
                log(f"{name}: building")
                build(sub, character, name)
            finally:
                if sub.is_object_added_for_editing(character):
                    sub.remove_object_to_edit(character)
            unreal.EditorAssetLibrary.save_directory(CONFIG["people_path"])
            results[name] = "built" if built_already(name) else "build ran, nothing in the built folder"
        except Exception as err:
            results[name] = f"FAILED {type(err).__name__}: {err}"
            for line in traceback.format_exc().splitlines()[-4:]:
                log(f"  {line}")
        log(f"{name}: {results[name]}")
    log(f"summary {json.dumps(results)}")


main()
