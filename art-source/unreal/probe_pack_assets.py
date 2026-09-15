"""
Diagnostic: loads one representative asset from each Fab pack the headquarters will use and logs
whether it loads in this engine, its class and its size, so a pack that needs another engine
version or a missing plugin shows up before the scene depends on it.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=probe_pack_assets.py

Paths are searched by name inside each pack folder (the packs' own layout), not hardcoded.
"""

import unreal

PROBES = (
    ("/Game/CitySampleVehicles", ("SM_vehBus_vehicle10_LOD", "SKM_vehCar_vehicle02", "BP_vehicle02_Car")),
    ("/Game/VehicleVarietyPack", ("SM_SUV", "BP_SUV")),
    ("/Game/ModularBuildingSet", ("store_", "upper_")),
    ("/Game/AutomotiveBridgeScene", ("SM_BridgeArches", "SM_Lamp")),
    ("/Game/Deko_MatrixDemo", ("SM_",)),
    ("/Game/Mega_Street_Props_Pack", ("SM_Bus_stop",)),
    ("/Game/Megaplant_Library", ("SKM_", "Tree_")),
    ("/Game/SoulCity", ("SM_",)),
)


def log(msg):
    unreal.log(f"AMN_PROBE {msg}")


def size_of(asset):
    for getter in ("get_bounding_box", "get_bounds"):
        fn = getattr(asset, getter, None)
        if fn is None:
            continue
        try:
            box = fn()
            ext = box.max - box.min if hasattr(box, "max") else box.box_extent * 2.0
            return f"{ext.x:.0f}x{ext.y:.0f}x{ext.z:.0f} cm"
        except Exception:
            continue
    return "-"


def main():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for folder, names in PROBES:
        assets = registry.get_assets_by_path(folder, recursive=True)
        if not assets:
            log(f"{folder}: MISSING")
            continue
        for name in names:
            match = next((a for a in assets if str(a.asset_name).startswith(name)), None)
            if match is None:
                log(f"{folder}: no asset named {name}*")
                continue
            path = str(match.package_name)
            try:
                asset = unreal.load_asset(path)
            except Exception as err:
                log(f"{folder}: {path} FAILED {type(err).__name__}: {err}")
                continue
            if asset is None:
                log(f"{folder}: {path} FAILED to load")
                continue
            log(f"{folder}: {path} OK {asset.get_class().get_name()} {size_of(asset)}")


main()
