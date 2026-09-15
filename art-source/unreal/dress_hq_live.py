"""
Unreal Engine 5.8 editor script: dresses the live headquarters (/Game/HQ/HQ_Dusk, built by
build_hq_scene.py) with the Fab packs the Owner added, in place of the Blender stand-ins.

- Every employee's workstation (the eight seats of the web scene's manifest): desk, office chair,
  monitor turned in from the side, keyboard, mouse, desk lamp and PC, from Apartment Tech Props and
  25 Office Desktop Items. The Blender workstations ("consoles") are removed.
- The street: lamp posts at the Blender lamps (whose lights stay), the bench, the bus shelter,
  planters and trees from the street packs and Megaplants; City Sample Vehicles in the two lanes.
  The Blender street furniture and trees are removed.

Positions come from the same projection the Blender build and the web scene use (hq_lib: 28 px per
metre, camera pitched 10 degrees), converted to Unreal (x, -y, z) centimetres, so pack assets stand
exactly where the scene's anchors are. Each asset is scaled to its target height and set on the
ground by its measured bounds, never by its pivot. Sizes and final bounds are written to
dress_report.json for tuning; AMN_DRESS_ONLY=desks|street limits the pass.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=dress_hq_live.py
"""

import json
import math
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
TAG = "AMN_DRESS"
ONLY = os.environ.get("AMN_DRESS_ONLY", "")

# ---------------------------------------------------------------- projection (hq_lib, hq_city)
PPM = 28.0
THETA = math.radians(10.0)
SIN, COS = math.sin(THETA), math.cos(THETA)
CX, CY = 800.0, 420.0
ZC = (655.0 - CY) / PPM / COS
TERRACE_Z, WALK_Z, ROAD_Z = -0.35, -0.7, -0.85
FLOORS = {4: (177, 85), 3: (282, 195), 2: (392, 297), 1: (500, 410), 0: (655, 520)}


def X(px):
    return (px - CX) / PPM


def Z(row, y=0.0):
    return ZC + ((CY - row) / PPM - y * SIN) / COS


def Y(row, z=0.0):
    return ((CY - row) / PPM - (z - ZC) * COS) / SIN


def fz(level):
    return Z(FLOORS[level][0])


def ue(x_m, y_m, z_m):
    """Blender metres -> Unreal centimetres (the importer maps Blender +y to Unreal -y)."""
    return unreal.Vector(x_m * 100.0, -y_m * 100.0, z_m * 100.0)


# the web scene's seats: (desk id, column px, level, monitor side, seat depth m)
SEATS = (
    ("desk_director", 811, 4, 1, 1.2),
    ("desk_research_1", 672, 3, 1, 1.2),
    ("desk_research_2", 926, 3, -1, 1.2),
    ("desk_script", 804, 2, 1, 1.2),
    ("desk_publish", 1000, 2, 1, 1.2),
    ("desk_audio", 668, 1, 1, 1.2),
    ("desk_video", 1022, 1, -1, 1.2),
    ("desk_accounting", 965, 0, -1, 1.3),
)

APT = "/Game/Deko_MatrixDemo/Apartment/Meshes"
OFFICE = "/Game/25_Office_Desktop_Items/Models"
KIT = {
    "desk": f"{APT}/SM_Desk_A01_N1",
    "chair": f"{APT}/SM_DeskChair_A01_N1",
    "monitor": f"{APT}/SM_ComputerMonitor_A01_N1",
    "keyboard": f"{APT}/SM_ComputerKeyboard_A01_N1",
    "mouse": f"{APT}/SM_ComputerMouse_A01_N1",
    "lamp": f"{APT}/SM_DeskLamp_A01_N1",
    "tower": f"{APT}/SM_ComputerTower_A01_N1",
    "mug": f"{OFFICE}/SM_tea_cup",
}
# Yaw that turns each asset's front towards the camera (the camera looks along -Y); corrected from
# the rendered still, with AMN_YAW_<KIND>=degrees to try alternatives without editing the script.
FRONT_YAW = {k: float(os.environ.get(f"AMN_YAW_{k.upper()}", v)) for k, v in {
    "desk": 0.0, "chair": 180.0, "monitor": 0.0, "keyboard": 180.0, "mouse": 180.0, "lamp": 0.0,
    "tower": 90.0, "mug": 0.0, "street_lamp": 0.0, "bench": 0.0, "bus_stop": 0.0, "planter": 0.0,
    "car": 0.0, "tree": 0.0,
}.items()}

STREET = {
    # a slim classic lantern post, like the picture's (the arm lamps read as black crosses when scaled)
    "street_lamp": "/Game/Mega_Street_Props_Pack/Street_Props_Pack_V1/Mesh/SM_Lantern_1",
    "bench": "/Game/Mega_Street_Props_Pack/Street_Props_Pack_V1/Mesh/SM_Bench",
    # the first shelter model has red neon edges the picture does not have
    "bus_stop": "/Game/Mega_Street_Props_Pack/Street_Props_Pack_V1/Mesh/SM_Bus_Stop_2",
    "planter": "/Game/Mega_Street_Props_Pack/Street_Props_Pack_V1/Mesh/SM_Flower_Pot",
}
# The scene keeps its own leafy trees by default ("blender"): Soul: City's static trees rendered
# bare and pale, and the wind-animated Megaplants stopped the stream's capture. AMN_TREES=static or
# megaplants places pack trees instead (the latter for stills).
TREE_MODE = os.environ.get("AMN_TREES", "blender")
TREES = {
    "blender": (),
    "static": ("/Game/SoulCity/Environment/Meshes/Foliage/SM_LV_Soul_Tree01_B",
               "/Game/SoulCity/Environment/Meshes/Foliage/SM_Aspen_Tree_01",
               "/Game/SoulCity/Environment/Meshes/Foliage/SM_tree2"),
    "megaplants": ("/Game/Megaplant_Library/Tree_Black_Alder/Tree_Black_Alder_01/Tree_Black_Alder_01_A",
                   "/Game/Megaplant_Library/Tree_Black_Poplar/Tree_Black_Poplar_01/Tree_Black_Poplar_01_A"),
}[TREE_MODE]
# headlights and tail lights ride on each vehicle (attached, so the traffic sequence carries them)
HEADLIGHT_LM = float(os.environ.get("AMN_HEADLIGHT_LM", "4000"))
TAILLIGHT_LM = float(os.environ.get("AMN_TAILLIGHT_LM", "120"))
CARS = "/Game/CitySampleVehicles"

REPORT = {"sizes": {}, "placed": [], "missing": [], "removed": []}


def log(msg):
    unreal.log(f"AMN_DRESS {msg}")


# ---------------------------------------------------------------- helpers
def find_asset(path):
    """Loads an asset by path; if the exact path is absent, searches its folder by name."""
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    folder, name = path.rsplit("/", 1)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    top = "/".join(path.split("/")[:3])
    for data in registry.get_assets_by_path(top, recursive=True):
        if str(data.asset_name) == name:
            return unreal.load_asset(str(data.package_name))
    REPORT["missing"].append(path)
    log(f"missing asset {path}")
    return None


def local_size(asset):
    if isinstance(asset, unreal.StaticMesh):
        box = asset.get_bounding_box()
        return box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z
    bounds = asset.get_bounds()
    e = bounds.box_extent
    return e.x * 2.0, e.y * 2.0, e.z * 2.0


def place(kind, asset, target, yaw_extra=0.0, height=None, max_len=None, label=None):
    """Spawns `asset` with its front to the camera (plus yaw_extra), scaled to `height` (cm) or so its
    longest horizontal side is `max_len` (cm), standing with its bounds' bottom-centre on `target`."""
    if asset is None:
        return None
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    skeletal = isinstance(asset, unreal.SkeletalMesh)
    cls = unreal.SkeletalMeshActor if skeletal else unreal.StaticMeshActor
    actor = eas.spawn_actor_from_class(cls, target, unreal.Rotator(roll=0.0, pitch=0.0, yaw=FRONT_YAW.get(kind, 0.0) + yaw_extra))
    if skeletal:
        actor.skeletal_mesh_component.set_skinned_asset_and_update(asset)
    else:
        actor.static_mesh_component.set_static_mesh(asset)
    sx, sy, sz = local_size(asset)
    REPORT["sizes"][asset.get_path_name()] = [round(sx), round(sy), round(sz)]
    k = 1.0
    if height and sz > 1.0:
        k = height / sz
    elif max_len and max(sx, sy) > 1.0:
        k = max_len / max(sx, sy)
    actor.set_actor_scale3d(unreal.Vector(k, k, k))
    origin, extent = actor.get_actor_bounds(False)
    bottom = unreal.Vector(origin.x, origin.y, origin.z - extent.z)
    loc = actor.get_actor_location()
    actor.set_actor_location(unreal.Vector(loc.x + target.x - bottom.x, loc.y + target.y - bottom.y, loc.z + target.z - bottom.z), False, False)
    actor.set_actor_label(label or kind)
    actor.set_editor_property("tags", [unreal.Name(TAG)])
    origin, extent = actor.get_actor_bounds(False)
    # "path" is how Remote Control addresses the actor in the running game (it has no label search)
    REPORT["placed"].append({"label": actor.get_actor_label(), "path": actor.get_path_name(), "asset": asset.get_path_name(), "scale": round(k, 3),
                             "centre_cm": [round(origin.x), round(origin.y), round(origin.z)],
                             "size_cm": [round(extent.x * 2), round(extent.y * 2), round(extent.z * 2)]})
    return actor


def clear(labels):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        tags = [str(t) for t in actor.get_editor_property("tags")]
        if TAG in tags or actor.get_actor_label() in labels:
            if actor.get_actor_label() in labels:
                REPORT["removed"].append(actor.get_actor_label())
            eas.destroy_actor(actor)


# ---------------------------------------------------------------- the workstations
def desks():
    kit = {k: find_asset(p) for k, p in KIT.items()}
    for desk_id, cx, level, side, seat_y in SEATS:
        f = fz(level)
        ox = X(cx)
        yf, yb = seat_y - 0.95, seat_y - 0.3
        top = f + 0.75
        place("desk", kit["desk"], ue(ox, (yf + yb) / 2, f), height=75.0, label=f"{desk_id}_desk")
        place("chair", kit["chair"], ue(ox, seat_y + 0.05, f), height=105.0, label=f"{desk_id}_chair")
        # The flat monitors with the studio's live screens stay the scene's own ("desk_screens"): the
        # pack's monitor and tower are 1999 hardware, far from the picture's modern desks.
        place("keyboard", kit["keyboard"], ue(ox - side * 0.05, yb - 0.14, top), max_len=44.0, label=f"{desk_id}_keyboard")
        place("mouse", kit["mouse"], ue(ox - side * 0.05 + 0.3, yb - 0.14, top), max_len=11.0, label=f"{desk_id}_mouse")
        place("lamp", kit["lamp"], ue(ox - side * 0.55, yb - 0.12, top), height=42.0, label=f"{desk_id}_lamp")
    log(f"workstations dressed: {len(SEATS)}")


# ---------------------------------------------------------------- the street
def ground_z(y):
    y_terrace = Y(676, TERRACE_Z)
    y_walk = Y(717, WALK_Z)
    if y >= y_terrace:
        return TERRACE_Z
    if y >= y_walk - 0.25:
        return WALK_Z
    return ROAD_Z


def street():
    y_terrace = Y(676, TERRACE_Z)
    y_walk = Y(717, WALK_Z)
    y_road = Y(790, ROAD_Z)
    lamp = find_asset(STREET["street_lamp"])
    for name, xpx, y, top_row in (("lamp_far_left", 92, y_walk + 0.5, 410), ("lamp_left", 322, y_terrace + 1.2, 505), ("lamp_right", 1406, y_walk + 0.6, 485)):
        base = ground_z(y)
        place("street_lamp", lamp, ue(X(xpx), y, base), height=(Z(top_row, y) + 0.34 - base) * 100.0, label=f"{name}_post")
    by = y_terrace - 1.6
    place("bench", find_asset(STREET["bench"]), ue(X(917), by + 0.22, WALK_Z), max_len=250.0, label="lobby_bench")
    sy0 = y_walk + 1.2
    place("bus_stop", find_asset(STREET["bus_stop"]), ue(X(1461), sy0 + 0.9, WALK_Z), max_len=(X(1545) - X(1378)) * 100.0, label="bus_shelter")
    pot = find_asset(STREET["planter"])
    for i, (x0, x1, y0, y1) in enumerate(((140, 300, 1.0, 2.2), (312, 412, 1.0, 2.2), (1352, 1420, 0.6, 1.6), (1545, 1600, 0.6, 1.6), (612, 660, -1.4, -0.5), (1200, 1240, -1.6, -0.6))):
        place("planter", pot, ue(X((x0 + x1) / 2), (y0 + y1) / 2, TERRACE_Z), max_len=min((X(x1) - X(x0)) * 100.0, 180.0), label=f"planter_{i}")
    # AMN_DRESS_TREES=0 leaves the trees out (the wind-animated Megaplants weigh heavily on the stream)
    trees = [find_asset(p) for p in TREES] if os.environ.get("AMN_DRESS_TREES", "1") != "0" else []
    for i, (xpx, ty, top_row) in enumerate(((225, 3.0, 440), (300, 0.2, 470), (372, -1.4, 470), (150, 4.0, 500), (1378, -1.0, 450), (1466, 1.5, 420), (1580, 3.0, 450)) if trees else ()):
        base = TERRACE_Z if ty > -3.0 else WALK_Z
        place("tree", trees[i % len(trees)], ue(X(xpx), ty, base), height=(Z(top_row, ty) - base) * 100.0, label=f"tree_{i}")
    cars()
    log("street dressed")


def cars():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    meshes = {str(a.asset_name): str(a.package_name) for a in registry.get_assets_by_path(CARS, recursive=True)
              if str(a.asset_class_path.asset_name) == "StaticMesh" and str(a.asset_name).endswith("_LOD")}
    log(f"city sample static vehicles: {sorted(meshes)}")
    y_walk = Y(717, WALK_Z)
    y_road = Y(790, ROAD_Z)
    near, far = y_road + 3.4, y_walk - 3.4
    # (mesh name fragment, column px, lane depth, heading +1 = towards +x)
    fleet = (("vehicle02", 150, near, 1), ("vehicle05", 330, near, 1), ("vehicle03", 1400, near, 1),
             ("vehicle10", 1060, far, -1), ("vehicle06", 560, far, -1))
    for frag, xpx, lane, heading in fleet:
        name = next((n for n in meshes if frag in n), None)
        if name is None:
            REPORT["missing"].append(frag)
            continue
        asset = unreal.load_asset(meshes[name])
        sx, sy, _ = local_size(asset)
        # length along the lane: turn the long side onto x, then point it the way it drives
        yaw = (0.0 if sx >= sy else 90.0) + (0.0 if heading > 0 else 180.0)
        car = place("car", asset, ue(X(xpx), lane, ROAD_Z), yaw_extra=yaw, label=f"car_{frag}")
        if car is not None:
            car_lights(car, heading)


def car_lights(car, heading):
    """Two headlights (spots along the lane, tipped at the road) and two red tail lights, attached."""
    car.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    origin, extent = car.get_actor_bounds(False)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    front_x = origin.x + heading * extent.x * 0.97
    rear_x = origin.x - heading * extent.x * 0.97
    lamp_z = origin.z - extent.z * 0.35
    for side in (-1.0, 1.0):
        y = origin.y + side * extent.y * 0.62
        head = eas.spawn_actor_from_class(unreal.SpotLight, unreal.Vector(front_x, y, lamp_z),
                                          unreal.Rotator(roll=0.0, pitch=-6.0, yaw=0.0 if heading > 0 else 180.0))
        comp = head.spot_light_component
        comp.set_mobility(unreal.ComponentMobility.MOVABLE)
        comp.set_intensity_units(unreal.LightUnits.LUMENS)
        comp.set_intensity(HEADLIGHT_LM)
        comp.set_light_color(unreal.LinearColor(1.0, 0.93, 0.8, 1.0))
        comp.set_outer_cone_angle(32.0)
        comp.set_inner_cone_angle(12.0)
        comp.set_attenuation_radius(2600.0)
        comp.set_cast_shadows(False)
        tail = eas.spawn_actor_from_class(unreal.PointLight, unreal.Vector(rear_x, y, lamp_z + 8.0))
        tcomp = tail.point_light_component
        tcomp.set_mobility(unreal.ComponentMobility.MOVABLE)
        tcomp.set_intensity_units(unreal.LightUnits.LUMENS)
        tcomp.set_intensity(TAILLIGHT_LM)
        tcomp.set_light_color(unreal.LinearColor(1.0, 0.05, 0.03, 1.0))
        tcomp.set_attenuation_radius(260.0)
        tcomp.set_cast_shadows(False)
        for light, kind in ((head, "headlight"), (tail, "taillight")):
            light.set_actor_label(f"{car.get_actor_label()}_{kind}_{'l' if side < 0 else 'r'}")
            light.set_editor_property("tags", [unreal.Name(TAG)])
            light.attach_to_actor(car, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                                  unreal.AttachmentRule.KEEP_WORLD, False)


def candidate_sizes():
    """Logs the size of every desk, monitor, chair and laptop the packs offer, to pick real ones."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    for folder, words in ((APT, ("Desk", "Monitor", "Chair", "Keyboard")), (OFFICE, ("laptop", "table_lamp", "headphones")),
                          ("/Game/Modern_House_V1", ("Desk", "Chair", "TV", "Monitor", "Table", "Lamp", "Shelf", "Sofa", "Plant"))):
        for data in registry.get_assets_by_path(folder, recursive=True):
            name = str(data.asset_name)
            if str(data.asset_class_path.asset_name) == "StaticMesh" and any(w.lower() in name.lower() for w in words):
                REPORT["sizes"][str(data.package_name)] = str(data.get_tag_value("ApproxSize") or "")


def metahuman_presets():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous(["/MetaHumanCharacter/Optional/Presets"], True)
    items = registry.get_assets_by_path("/MetaHumanCharacter/Optional/Presets", recursive=False)
    log("presets: " + ", ".join(f"{a.asset_name}:{a.asset_class_path.asset_name}" for a in items[:40]))


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    replaced = []
    if ONLY in ("", "desks"):
        replaced += ["consoles"]
    if ONLY in ("", "street"):
        replaced += ["street_props"] + (["tree_trunks", "tree_crowns"] if TREES else [])
    clear(set(replaced))
    if ONLY in ("", "desks"):
        desks()
    if ONLY in ("", "street"):
        street()
    metahuman_presets()
    les.save_current_level()
    out = os.path.join(HERE, "dress_report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, indent=1)
    log(f"placed {len(REPORT['placed'])}, removed {REPORT['removed']}, missing {REPORT['missing']} -> {out}")


main()
