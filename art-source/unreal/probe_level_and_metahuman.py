"""
Diagnostic for the live headquarters rebuild:

1. lists every actor of /Game/HQ/HQ_Dusk (label, class, mesh, bounds centre and size in cm) into
   art-source/unreal/level_actors.json, so pack assets can replace the Blender stand-ins by name;
2. lists every function the MetaHuman Creator's editor subsystem offers and what a preset
   character (MetaHumanCharacter assets in the Creator's optional content) exposes, so the
   employees can be built from presets if the engine allows it without the cloud services.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_level_and_metahuman.py
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"


def log(msg):
    unreal.log(f"AMN_PROBE2 {msg}")


def level_actors():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        log("could not load level")
        return
    out = []
    for actor in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        origin, extent = actor.get_actor_bounds(False)
        item = {
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "centre_cm": [round(origin.x), round(origin.y), round(origin.z)],
            "size_cm": [round(extent.x * 2), round(extent.y * 2), round(extent.z * 2)],
        }
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp and comp.static_mesh:
            item["mesh"] = comp.static_mesh.get_path_name()
        out.append(item)
    path = os.path.join(HERE, "level_actors.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    classes = {}
    for item in out:
        classes[item["class"]] = classes.get(item["class"], 0) + 1
    log(f"{len(out)} actors {classes} -> {path}")


def metahuman():
    cls = getattr(unreal, "MetaHumanCharacterEditorSubsystem", None)
    if cls is None:
        log("no MetaHumanCharacterEditorSubsystem")
        return
    sub = unreal.get_editor_subsystem(cls)
    log("subsystem: " + ", ".join(n for n in dir(sub) if not n.startswith("_")))
    for name in dir(unreal):
        if name.startswith("MetaHuman") and ("Param" in name or "Pipeline" in name or "Build" in name or "Library" in name):
            log(f"type {name}")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    presets = [a for a in registry.get_assets_by_path("/MetaHumanCharacter/Optional/Presets", recursive=True)]
    log(f"presets found: {len(presets)} e.g. {[str(a.package_name) for a in presets[:3]]}")
    if presets:
        asset = unreal.load_asset(str(presets[0].package_name))
        log(f"preset class {asset.get_class().get_name()}")
        props = []
        for n in dir(asset):
            if n.startswith("_"):
                continue
            props.append(n)
        log("preset attributes: " + ", ".join(props))
        try:
            log(f"can_build_meta_human: {sub.can_build_meta_human(asset)}")
        except Exception as err:
            log(f"can_build_meta_human failed: {type(err).__name__}: {err}")


level_actors()
metahuman()
