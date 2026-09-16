"""
Unreal Engine 5.8 editor script: dresses the live headquarters (/Game/HQ/HQ_Dusk, built by
build_hq_scene.py) with the Fab packs the Owner added, in place of the Blender stand-ins.

- Every employee's workstation (the eight seats of the web scene's manifest): desk, office chair,
  monitor turned in from the side, keyboard, mouse, desk lamp and PC, from Apartment Tech Props and
  25 Office Desktop Items. The Blender workstations ("consoles") are removed.
- The rooms' plants and portrait pictures: Palms Pack indoor plants (the model nearest in height)
  and the restaurant scene's framed paintings, where the Blender build recorded its own
  (hq_scene.json "props_m", written when the export ran with AMN_UNREAL_PROPS=1).
- The street: lamp posts at the Blender lamps (whose lights stay), the bench, the bus shelter,
  planters and trees from the street packs and Megaplants; City Sample Vehicles in the two lanes;
  the bridge scene's cracked asphalt, made wet, on the road. The Blender street furniture and
  trees are removed.

Positions come from the same projection the Blender build and the web scene use (hq_lib: 28 px per
metre, camera pitched 10 degrees), converted to Unreal (x, -y, z) centimetres, so pack assets stand
exactly where the scene's anchors are. Each asset is scaled to its target height and set on the
ground by its measured bounds, never by its pivot. Sizes and final bounds are written to
dress_report.json for tuning; AMN_DRESS_ONLY=desks|street limits the pass.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=dress_hq_live.py
"""

import importlib.util
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
# "soul" since 2026-09-15: Soul: City's leafy tree with the green leaf texture (leaves/), which read as
# real crowns next to the picture where the Blender crowns read as foam
TREE_MODE = os.environ.get("AMN_TREES", "soul")
TREES = {
    "blender": (),
    "static": ("/Game/SoulCity/Environment/Meshes/Foliage/SM_LV_Soul_Tree01_B",
               "/Game/SoulCity/Environment/Meshes/Foliage/SM_Aspen_Tree_01",
               "/Game/SoulCity/Environment/Meshes/Foliage/SM_tree2"),
    "megaplants": ("/Game/Megaplant_Library/Tree_Black_Alder/Tree_Black_Alder_01/Tree_Black_Alder_01_A",
                   "/Game/Megaplant_Library/Tree_Black_Poplar/Tree_Black_Poplar_01/Tree_Black_Poplar_01_A"),
    # Soul: City's leafy tree. The first static set above read bare and pale: the aspen's leaves are a
    # translucent material (poorly lit and without depth in this scene), SM_LV_Soul_Tree01_B is a pine
    # and SM_tree2 a twisted bare tree. Of three more compared side by side in the stream, only this
    # one kept a full crown (masked, two-sided leaves); SM_S_Soul_Tree2 and SM_S_Soul_bush read as
    # bare white branches.
    "soul": ("/Game/SoulCity/Environment/Meshes/Foliage/SM_S_BuildingSetA_Tree_02_OP02_S_BuildingSetA_Tree_02_OP02",),
    # static Nanite copies of Megaplants trees (convert_trees_static.py): leafy like the picture's,
    # without the skeleton that stopped the stream's capture. Only the round crowns: the black alder
    # (5.5 m wide, 10.9 m tall) and the Japanese medlar (3.5 m, 2.7 m); scaled to the street's tree
    # heights the black poplar (31.8 m tall) became a pole and the goat willow (2.1 m) a wide mound.
    "megastatic": ("/Game/HQ/Trees/SM_Tree_Black_Alder_01_B", "/Game/HQ/Trees/SM_Tree_Japanese_Medlar_01_B"),
}[TREE_MODE]
# The Soul: City tree's leaf material tints its leaf texture with one colour, LitColor, orange by
# default (1.0, 0.6, 0.4): in the stream the crowns read autumn orange where the picture's trees are
# green. A material instance under /Game/HQ/Materials sets it (AMN_TREE_LEAF_COLOR="r,g,b").
LEAF_PARENT = "/Game/SoulCity/Environment/Materials/Foliage/M_LV_Soul_Tree02"
LEAF_MI = "/Game/HQ/Materials/MI_HQ_TreeLeavesGreen"
LEAF_TEXTURE = "/Game/HQ/Materials/T_HQ_Leaves_Green"
LEAF_COLOR = [float(v) for v in os.environ.get("AMN_TREE_LEAF_COLOR", "0.32,0.52,0.22").split(",")]


def leaf_material():
    """The green leaf instance (created once, colour set every run), or None if the parent is missing."""
    parent = find_asset(LEAF_PARENT)
    if parent is None:
        return None
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(LEAF_MI):
        mi = unreal.load_asset(LEAF_MI)
    else:
        folder, name = LEAF_MI.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    mel.set_material_instance_vector_parameter_value(mi, "LitColor", unreal.LinearColor(LEAF_COLOR[0], LEAF_COLOR[1], LEAF_COLOR[2], 1.0))
    # LitColor alone left the crowns orange: the leaf texture itself is autumn-coloured (leaves average
    # RGB 102, 75, 43). A green copy of it, when imported, replaces the texture.
    green = unreal.load_asset(LEAF_TEXTURE) if unreal.EditorAssetLibrary.does_asset_exist(LEAF_TEXTURE) else None
    if green is not None:
        mel.set_material_instance_texture_parameter_value(mi, "DiffuseandAlpha", green)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    log(f"tree leaves: LitColor {LEAF_COLOR}, texture {'green copy' if green else 'the pack original'}")
    return mi


# headlights and tail lights ride on each vehicle (attached, so the traffic sequence carries them)
HEADLIGHT_LM = float(os.environ.get("AMN_HEADLIGHT_LM", "4000"))
TAILLIGHT_LM = float(os.environ.get("AMN_TAILLIGHT_LM", "120"))
CARS = "/Game/CitySampleVehicles"

REPORT = {"sizes": {}, "placed": [], "missing": [], "removed": []}

# the plain lit material the street furniture and the passers-by's clothes share
_flat_spec = importlib.util.spec_from_file_location("flat_material", os.path.join(HERE, "flat_material.py"))
_flat = importlib.util.module_from_spec(_flat_spec)
_flat_spec.loader.exec_module(_flat)


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
# "pack" puts Apartment Tech Props' desk and chair in place of the scene's own workstation (the
# "consoles" object). "blender" keeps the scene's: a white desk with a light front panel and a lit
# edge, like the picture's desks, where the pack's desk is dark wood; only the keyboard, mouse and
# lamp come from the pack, on the same 75 cm top. Compared in the stream (2026-09-15): with the
# scene's desks every employee sits at a white, lit-fronted desk like the picture's, and the mean held
# (14.0; L3 14.6 -> 13.9, L2 18.2 -> 18.8).
CONSOLES = os.environ.get("AMN_DRESS_CONSOLES", "blender")


def desks():
    kit = {k: find_asset(p) for k, p in KIT.items()}
    for desk_id, cx, level, side, seat_y in SEATS:
        f = fz(level)
        ox = X(cx)
        yf, yb = seat_y - 0.95, seat_y - 0.3
        top = f + 0.75
        if CONSOLES != "blender":
            place("desk", kit["desk"], ue(ox, (yf + yb) / 2, f), height=75.0, label=f"{desk_id}_desk")
        # The chair comes from the pack whichever desk is in use. 115 cm, not its own 107: the build's
        # planks (48 x 8 cm back to f + 1.12, 46 x 46 cm seat) stand at the same spot and this pass
        # cannot remove them - they are inside the shared "props" object - so the chair is spawned a
        # little large and its bounds enclose them. Back at its own height once hq_building.workstation
        # gives its chairs their own object for clear() to take away.
        place("chair", kit["chair"], ue(ox, seat_y + 0.05, f), height=115.0, label=f"{desk_id}_chair")
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
    # The pack's bench and planters are near black in this light, where the picture has a wood bench
    # and pale stone troughs; without them the passer-by sitting there looked unsupported.
    bench = place("bench", find_asset(STREET["bench"]), ue(X(917), by + 0.22, WALK_Z), max_len=250.0, label="lobby_bench")
    if bench is not None:
        # 0.34, 0.21, 0.11 (0.14, 0.08, 0.04 before): the picture's bench is lit wood, 98, 77, 65
        # over its slats with a 90th percentile of 126, where ours read 75, 53, 47 and 68 - dark
        # enough that the passer-by sitting on it looked unsupported again.
        _flat.paint(bench, "BenchWood", (0.34, 0.21, 0.11), roughness=0.55)
    sy0 = y_walk + 1.2
    place("bus_stop", find_asset(STREET["bus_stop"]), ue(X(1461), sy0 + 0.9, WALK_Z), max_len=(X(1545) - X(1378)) * 100.0, label="bus_shelter")
    pot = find_asset(STREET["planter"])
    for i, (x0, x1, y0, y1) in enumerate(((140, 300, 1.0, 2.2), (312, 412, 1.0, 2.2), (1352, 1420, 0.6, 1.6), (1545, 1600, 0.6, 1.6), (612, 660, -1.4, -0.5), (1200, 1240, -1.6, -0.6))):
        trough = place("planter", pot, ue(X((x0 + x1) / 2), (y0 + y1) / 2, TERRACE_Z), max_len=min((X(x1) - X(x0)) * 100.0, 180.0), label=f"planter_{i}")
        if trough is not None:
            _flat.paint(trough, "PlanterStone", (0.10, 0.10, 0.11), roughness=0.6)
    # AMN_DRESS_TREES=0 leaves the trees out (the wind-animated Megaplants weigh heavily on the stream)
    trees = [find_asset(p) for p in TREES] if os.environ.get("AMN_DRESS_TREES", "1") != "0" else []
    leaves = leaf_material() if TREE_MODE == "soul" else None
    # Four tall trees on the left grew into one wall of leaves that hid the city behind them; the
    # picture has a row of smaller trees with gaps of lit city between their crowns. Seven smaller
    # ones stand there now (a crown scales with the height, so lower is also narrower).
    for i, (xpx, ty, top_row) in enumerate(((150, 4.0, 520), (205, 3.0, 505), (258, 1.6, 500), (312, 0.2, 498),
                                            (366, -1.4, 496), (1378, -1.0, 480), (1466, 1.5, 462), (1580, 3.0, 478)) if trees else ()):
        base = TERRACE_Z if ty > -3.0 else WALK_Z
        tree = place("tree", trees[i % len(trees)], ue(X(xpx), ty, base), height=(Z(top_row, ty) - base) * 100.0, label=f"tree_{i}")
        if tree is not None and leaves is not None:
            comp = tree.static_mesh_component
            for slot in range(comp.get_num_materials()):
                if comp.get_material(slot) is not None and comp.get_material(slot).get_name() == LEAF_PARENT.rsplit(".", 1)[-1].rsplit("/", 1)[-1]:
                    comp.set_material(slot, leaves)
    cars()
    log("street dressed")


def cars():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    every = {str(a.asset_name): str(a.package_name) for a in registry.get_assets_by_path(CARS, recursive=True)
             if str(a.asset_class_path.asset_name) == "StaticMesh"}
    meshes = {n: p for n, p in every.items() if n.endswith("_LOD")}
    # the windows: the pack keeps each vehicle's glass as its own mesh on the same origin as the body
    glazing = {n: p for n, p in every.items() if "Trans" in n and "Wheel" not in n}
    log(f"city sample static vehicles: {sorted(meshes)}")
    y_walk = Y(717, WALK_Z)
    y_road = Y(790, ROAD_Z)
    near, far = y_road + 3.4, y_walk - 3.4
    # (mesh name fragment, column px, lane depth, heading +1 = towards +x)
    # Five again, not eight. Eight was right while every car made one pass per loop and then parked off
    # frame: they still averaged only 1.88 on frame and left the road empty for 2.2 % of every loop.
    # Since traffic_hq_live.py drives them as a conveyor each car is on frame for 79 % of its crossing,
    # so five put 4.31 on frame on average and never fewer than three - the picture's four. Eight would
    # now crowd the street with six or seven, and each vehicle carries four dynamic lights the stream
    # has to pay for.
    # Only vehicles that ship a complete static body (SM_*_No_Wheel beside the _LOD). vehicle02 and
    # vehicle06 have none: their _LOD is a distance proxy with the doors left out, and on the stream
    # they drove past with their sides open even once their glass was attached (2026-09-16).
    fleet = (("vehicle03", 150, near, 1), ("vehicle12", 800, near, 1), ("vehicle09", 1180, near, 1),
             ("vehicle10", 1060, far, -1), ("vehicle05", 560, far, -1))
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
            car_glass(car, frag, glazing)


def car_glass(car, frag, glazing):
    """The vehicle's own window mesh, on the body's transform and riding with it. The `_LOD` body has
    open window frames: without the glass a car shows its far side through them, which on the stream
    read as a door missing."""
    name = next((n for n in glazing if frag in n), None)
    if name is None:
        log(f"{frag}: no glazing mesh in the pack")
        return
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    glass = eas.spawn_actor_from_class(unreal.StaticMeshActor, car.get_actor_location(), car.get_actor_rotation())
    glass.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    glass.static_mesh_component.set_static_mesh(unreal.load_asset(glazing[name]))
    glass.set_actor_scale3d(car.get_actor_scale3d())
    glass.set_actor_label(f"{car.get_actor_label()}_glass")
    glass.set_editor_property("tags", list(car.get_editor_property("tags")))
    glass.attach_to_actor(car, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD,
                          unreal.AttachmentRule.KEEP_WORLD, False)


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


# ---------------------------------------------------------------- the rooms' plants and pictures
# Indoor plants of Palms Pack (static meshes; the wind is in their materials, not a skeleton) by
# native height in cm, and framed paintings of the restaurant scene, 67 x 93 cm, portrait. Only
# the full ones: the slender models (SM_Plant_07_*, 16-33 cm wide for 75-106 cm tall) read as thin
# dark sprigs in the live frame where the picture has leafy plants. Plants taller than BIG_PLANT_CM
# (the lobby's) are the restaurant scene's large potted frond instead.
PLANTS = (
    ("/Game/Palms_Pack_01/Add_Props/Plants/Meshes/SM_Plant_09_3_G", 57.0),
    ("/Game/Palms_Pack_01/Add_Props/Plants/Meshes/SM_Plant_06_2_G", 120.0),
)
BIG_PLANT = "/Game/RestaurantScene/Meshes/SM_PlantPot"
# the sofa pack's seat block (232 x 100 x 75 cm): a plain modern sofa, scaled to the build's own width
SOFA = "/Game/Furniture_Sofa_14/Mesh/SM_Block1"
# 90: the fronds also read leafy on L3 and L4, where Palms' plants stayed dark silhouettes. Tried
# again once the rooms were better lit (2026-09-15, 999 = Palms' plants everywhere): thin dark stems,
# fainter than the fronds the look pass lightens, and the mean slipped (14.0 -> 14.1).
BIG_PLANT_CM = float(os.environ.get("AMN_BIG_PLANT_CM", "90"))
# The frond is 151 x 161 x 159 cm of its own. Five of the recorded plants are 2.05 to 2.65 m tall, and
# stretching one frond to those made it 2.0 to 2.5 m wide as well: a leaf blob the width of a desk,
# where the picture has a slim plant in a pot. Above this it stands shorter rather than wider than the
# model is built to be. A real 2.5 m indoor plant needs a pack we do not own.
PLANT_MAX_CM = float(os.environ.get("AMN_PLANT_MAX_CM", "175"))
PAINTINGS = ("/Game/RestaurantScene/Meshes/SM_WallPainting_1", "/Game/RestaurantScene/Meshes/SM_WallPainting_2")
FRONT_YAW.setdefault("plant", float(os.environ.get("AMN_YAW_PLANT", "0")))
FRONT_YAW.setdefault("sofa", float(os.environ.get("AMN_YAW_SOFA", "0")))
FRONT_YAW.setdefault("painting", float(os.environ.get("AMN_YAW_PAINTING", "0")))


def props():
    """Pack plants and paintings where the Blender build recorded its own (hq_scene.json props_m)."""
    meta = json.load(open(os.path.join(HERE, "hq_scene.json"), "r", encoding="utf-8"))
    recorded = meta.get("props_m") or {}
    plants = [(find_asset(p), h) for p, h in PLANTS]
    plants = [(a, h) for a, h in plants if a is not None]
    big = find_asset(BIG_PLANT)
    for i, item in enumerate(recorded.get("plants", [])):
        target = item["height"] * 100.0
        if big is not None and target >= BIG_PLANT_CM:
            asset = big
            target = min(target, PLANT_MAX_CM)
        else:
            # the model whose own height is nearest, so none is stretched far from its shape
            asset = min(plants, key=lambda ah: abs(math.log(target / ah[1])))[0] if plants else None
        # Sixteen of the twenty-one plants are the same frond; all turned the same way they repeat from
        # floor to floor. A different yaw each time hides that at no cost.
        place("plant", asset, ue(item["x"], item["y"], item["z"]), yaw_extra=(i * 47) % 360,
              height=target, label=f"plant_{i}")
    paintings = [a for a in (find_asset(p) for p in PAINTINGS) if a is not None]
    for i, item in enumerate(recorded.get("pictures", [])):
        if not paintings:
            break
        # hung on the wall: bottom-centre just in front of it, as tall as the picture it replaces
        place("painting", paintings[i % len(paintings)], ue(item["x"], item["y"] - 0.02, item["z"] - item["h"] / 2.0),
              height=item["h"] * 100.0, label=f"painting_{i}")
    # The sofas: the picture's are leather with cushions and highlights, and the build's six boxes read
    # as six boxes. The sofa pack's block is a plain seat with a low back; sized by the width the build
    # gave the sofa, it lands where the boxes were and the room's light does the rest.
    sofa = find_asset(SOFA)
    for i, item in enumerate(recorded.get("sofas", [])):
        place("sofa", sofa, ue(item["x"], item["y"], item["z"]), max_len=item["width"] * 100.0, label=f"sofa_{i}")
    log(f"props: {len(recorded.get('plants', []))} plants, {len(recorded.get('pictures', []))} paintings, "
        f"{len(recorded.get('sofas', []))} sofas")


# ---------------------------------------------------------------- the road
ROAD_PARENT = "/Game/AutomotiveBridgeScene/Materials/Environment/MI_AsphaltFine"
ROAD_MI = "/Game/HQ/Materials/MI_HQ_AsphaltWet"
# The bridge scene's cracked asphalt (world-space triplanar, so no UVs are needed), made wet: the
# picture's road shines with streaks of light, the pack's is dry (roughness 0.85-1.0).
ROAD_PARAMS = {
    # the closest pass (15.8); smoother (0.12-0.35) and untinted, it only lit the building's base
    "Roughness Min": float(os.environ.get("AMN_ROAD_ROUGH_MIN", "0.14")),
    "Roughness Max": float(os.environ.get("AMN_ROAD_ROUGH_MAX", "0.42")),
    # 0.95 (0.85 before): with the road this wet most of what it shows is reflection, and its own
    # tone had been pulled down under that until the far lane read 53 against the picture's 69 and the
    # near lane 52 against 63, with 14.3 % of the far lane under luma 30 where the picture has 8.4 %.
    "Base Color Multiply": float(os.environ.get("AMN_ROAD_DARKEN", "0.95")),
    "Specular": 0.5,
    "UV Tile U": 2.0,
    "UV Tile V": 2.0,
}


def road_material():
    """The wet asphalt instance (created once), on the street's asphalt slot."""
    mel = unreal.MaterialEditingLibrary
    parent = find_asset(ROAD_PARENT)
    if parent is None:
        return
    if unreal.EditorAssetLibrary.does_asset_exist(ROAD_MI):
        mi = unreal.load_asset(ROAD_MI)
    else:
        folder, name = ROAD_MI.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    for key, value in ROAD_PARAMS.items():
        mel.set_material_instance_scalar_parameter_value(mi, key, value)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    slots = 0
    for actor in eas.get_all_level_actors():
        if actor.get_actor_label() != "street_ground" or not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if mat is not None and "asphalt" in mat.get_path_name().lower():
                comp.set_material(i, mi)
                slots += 1
    log(f"road: wet cracked asphalt on {slots} slot(s) {ROAD_PARAMS}")


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


# ---------------------------------------------------------------- the rooms' clutter
# Next to the picture, our rooms read emptier: there the counters are covered in gear and papers,
# books and lamps stand in every gap and a leafy plant fills each corner. The Blender build lays out
# the big pieces; this pass adds the small pack objects over the stretches it leaves bare. Each
# position was read off the build (hq_building.py) and the reference crops, and is clear of the
# workstations, of the seats and of the scene's own props. AMN_DRESS_CLUTTER=0 leaves them out.
CLUTTER_ON = os.environ.get("AMN_DRESS_CLUTTER", "1") != "0"
CLUTTER_ASSETS = {
    "laptop": f"{OFFICE}/SM_laptop",
    "tray": f"{OFFICE}/SM_document_tray",
    "folder": f"{OFFICE}/SM_folder",
    "books": f"{OFFICE}/SM_book_stand",
    "open_book": f"{OFFICE}/SM_open_book",
    "pencils": f"{OFFICE}/SM_pencil_holder",
    "speakers": f"{APT}/SM_ComputerSpeakers_A01_N1",
    "table_lamp": f"{OFFICE}/SM_table_lamp",
    "headphones": f"{OFFICE}/SM_headphones",
    "mug": f"{OFFICE}/SM_tea_cup",
    # the restaurant scene's potted frond, the one plant of the packs that reads leafy at this scale
    "frond": BIG_PLANT,
    "armchair": "/Game/MafiaBarnPack/Meshes/Props/Furniture/SM_ClassicArmchair",
    "cabinet": "/Game/Modern_House_V1/Mesh/SM_Cabinet_2",
    # a small white cabinet for under the counters, where the picture keeps boxes and drawers
    "underbox": "/Game/Modern_House_V1/Mesh/SM_Cabinet_6",
    # The picture's counters carry a printer and stacks of paper and its floors a filing cabinet in
    # every gap; we had a mesh for none of those. Sizes are each pack's own (33 x 20 x 15 for the
    # printer, 49 x 37 x 25 for the papers, 76 x 38 x 42 for the archive box, 42 x 50 x 120 for the
    # filing cabinet, 49 x 86 x 85 for the cart, 32 x 27 x 16 for the phone), so none is stretched.
    "printer": f"{APT}/SM_ComputerPrinter_A01_N1",
    "papers": "/Game/MafiaBarnPack/Meshes/Props/Paper/SM_Documents1",
    "docubox": "/Game/MafiaBarnPack/Meshes/Props/Boxes/SM_DocuBox",
    "filing": "/Game/Modern_House_V1/Mesh/SM_Cabinet_10",
    "cart": "/Game/RestaurantScene/Meshes/SM_UtilityCart",
    "phone": f"{APT}/SM_Phone_A01_N1",
}
# (level, kind, column px, depth m, height above the floor m, "h" for total height or "l" for the
#  longest horizontal side, that size in cm)
CLUTTER = (
    # L4 Executive: the bookshelf's top, the cabinet by the door and the low table on the right
    (4, "books", 548, 2.05, 1.60, "h", 24),
    (4, "frond", 574, 2.05, 1.60, "h", 55),
    (4, "tray", 948, 2.05, 0.75, "l", 32),
    (4, "open_book", 1018, 1.95, 0.55, "l", 30),
    (4, "mug", 1029, 1.90, 0.55, "h", 9),
    (4, "table_lamp", 1046, 1.95, 0.55, "h", 40),
    (4, "headphones", 857, 2.00, 0.60, "h", 20),
    (4, "underbox", 800, 2.05, 0.00, "h", 50),
    # L3 Research / Fact Check: the bookshelf's top and the bare ends of the three counters
    (3, "books", 548, 2.05, 1.80, "h", 24),
    (3, "frond", 572, 2.05, 1.80, "h", 50),
    (3, "speakers", 778, 2.05, 0.78, "h", 24),
    (3, "tray", 840, 2.05, 0.78, "l", 30),
    (3, "frond", 854, 1.70, 0.00, "h", 110),
    (3, "laptop", 958, 2.00, 0.78, "l", 34),
    (3, "mug", 970, 1.95, 0.78, "h", 9),
    (3, "folder", 1002, 2.05, 0.78, "l", 28),
    (3, "mug", 623, 2.00, 0.78, "h", 9),
    (3, "books", 716, 2.05, 0.78, "h", 22),
    (3, "headphones", 784, 2.05, 0.78, "h", 20),
    (3, "pencils", 950, 2.05, 0.78, "h", 14),
    (3, "books", 1172, 2.05, 1.55, "h", 22),
    (3, "underbox", 648, 2.05, 0.00, "h", 50),
    (3, "underbox", 806, 2.05, 0.00, "h", 50),
    (3, "underbox", 1042, 2.05, 0.00, "h", 50),
    # L2 Content: the long bench under the pinboard, bare in the stream where the picture has it full
    (2, "tray", 566, 1.25, 0.46, "l", 32),
    (2, "books", 592, 1.25, 0.46, "h", 24),
    (2, "open_book", 612, 1.25, 0.46, "l", 30),
    (2, "laptop", 650, 1.25, 0.46, "l", 34),
    (2, "folder", 676, 1.25, 0.46, "l", 28),
    (2, "table_lamp", 700, 1.25, 0.46, "h", 40),
    (2, "laptop", 706, 2.00, 0.78, "l", 34),
    (2, "tray", 734, 2.05, 0.78, "l", 30),
    (2, "mug", 748, 1.95, 0.78, "h", 9),
    (2, "pencils", 714, 2.05, 0.78, "h", 14),
    (2, "underbox", 762, 2.05, 0.00, "h", 50),
    # L2 Distribution: the top of the two bookshelves
    (2, "frond", 1028, 2.10, 1.75, "h", 45),
    (2, "books", 1046, 2.10, 1.75, "h", 22),
    # L1 Production: the audio and render counters, and a rack cabinet like the picture's by the door
    (1, "headphones", 633, 2.05, 0.78, "h", 20),
    (1, "speakers", 716, 2.05, 0.78, "h", 24),
    (1, "cabinet", 742, 2.10, 0.00, "h", 175),
    (1, "tray", 978, 2.05, 0.78, "l", 30),
    (1, "mug", 987, 1.95, 0.78, "h", 9),
    (1, "tray", 1150, 2.05, 1.70, "l", 30),
    (1, "underbox", 680, 2.05, 0.00, "h", 50),
    (1, "underbox", 1000, 2.05, 0.00, "h", 50),
    # Ground: the lobby's seating group (the picture has two seats and a table around the low table),
    # a plant in the ad space and one by the treasury's chart
    (0, "armchair", 700, 2.35, 0.00, "h", 100),
    (0, "armchair", 754, 2.35, 0.00, "h", 100),
    (0, "frond", 1092, 2.20, 0.00, "h", 130),
    (0, "pencils", 1006, 2.05, 0.95, "h", 14),
    # the treasury: the picture's operations room stands full of equipment, ours held only the desk
    (0, "cabinet", 1010, 2.10, 0.00, "h", 170),
    (0, "underbox", 930, 2.10, 0.00, "h", 50),
    (0, "frond", 1026, 1.70, 0.00, "h", 95),
    (0, "tray", 938, 2.05, 0.95, "l", 30),
    # The gaps the rooms still leave bare, each read off the build and clear of what stands there:
    # L4's window bay (958-1010, the plant at 992); L3's white unit (790-830, its top f + 0.96) and
    # the 22 px floor gap between the whiteboard desk (880-975) and the bottle counter (997-1102);
    # L2's stretch between the work table's end (722) and the back desk's left leg (705-712), and the
    # floor under the Distribution window (940-990), clear of the workstation at 1000; L1's gap
    # between the two DAW monitors (668, 681), the slat wall (822-853, so y 2.00 keeps the cabinet's
    # 50 cm depth clear of the slats at 2.28-2.38) and the render bay floor under the standing lamp.
    (4, "docubox", 972, 2.15, 0.00, "h", 42),
    (3, "printer", 800, 2.15, 0.96, "l", 34),
    (3, "papers", 818, 2.15, 0.96, "l", 30),
    (3, "filing", 986, 2.10, 0.00, "h", 105),
    (2, "cart", 736, 2.15, 0.00, "h", 85),
    (2, "filing", 958, 2.10, 0.00, "h", 105),
    (1, "phone", 675, 2.20, 0.78, "h", 16),
    (1, "filing", 832, 2.00, 0.00, "h", 105),
    (1, "docubox", 1118, 2.20, 0.00, "h", 42),
)
# the lobby's second seat turns in towards the first, as the picture's pair face each other
CLUTTER_YAW = {(0, "armchair", 754): 200.0, (0, "armchair", 700): 160.0,
               # the cart is 86 cm long and 49 deep: turned, its length runs along the room, not into
               # the back wall
               (2, "cart", 736): 90.0}


# Pack pieces whose own materials read wrong in these rooms: the tall cabinet is a green rusted
# locker and the low one a white kitchen unit, where the picture has slate office furniture.
CLUTTER_PAINT = {"cabinet": (0.10, 0.11, 0.13), "underbox": (0.12, 0.13, 0.15),
                 # the filing cabinet is a plain white column of the house pack, where the picture has
                 # slate office furniture, like the other two
                 "filing": (0.12, 0.13, 0.15)}


# ---------------------------------------------------------------- the ceiling pendants
# Measured off the reference at 8x, one of the picture's pendants is a wide shallow dark dish, 67 cm
# across and 18 cm deep, with a warm band of light round its rim, on a 25 cm stem. Ours is a 68 cm
# black cone with a 66 cm lit disc under it (hq_building.pendant): the right width, but no shade wall,
# no reflector and no stem, so it reads as a flat black saucer over a white blob.
# The barn pack's enamel pendant is the one shade of the packs with those proportions - 39 x 40 x 70 cm,
# dark teal-grey outside with a pale radial reflector inside - so the shade is nearly as wide as the
# whole lamp is tall and a reference-width dish does not drag a metre of rod down with it. Its warm
# band costs nothing: the build's own POINT light hangs 12 cm under each pendant and stays there.
# (SM_2_HangingLamp, 41 x 42 x 47, is the same shade on a shorter cord, with its own glass slot for the
# lit underside, if the 70 cm above turns out to be mostly cord.)
PENDANT = "/Game/MafiaBarnPack/Meshes/Props/Lighting/SM_HangingLamp"
# (level, column px, the build's drop in metres, the shade's width in cm, what the build draws there)
PENDANTS = (
    (4, 900, 1.10, 66, "dome"),
    (4, 1076, 1.00, 34, "bulb"),
    (4, 1116, 0.85, 34, "bulb"),
    (2, 590, 0.62, 60, "dome"),
    (2, 660, 0.62, 60, "dome"),
    (2, 740, 0.62, 60, "dome"),
    (2, 820, 0.62, 60, "dome"),
    (2, 1040, 0.62, 60, "dome"),
    (2, 1110, 0.62, 60, "dome"),
    (2, 1180, 0.62, 60, "dome"),
    (0, 868, 1.20, 38, "bulb"),
)
# The eight dome ones are off until the Blender build stops drawing its cone. hq_building.pendant()
# builds into the shared "props" object, so clear() cannot take one cone away, and a 60 cm shade set
# inside a 68 cm cone only leaves a black collar round it. The three bulb ones go in now: there the
# build draws a 9 cm sphere, which a 34 cm shade swallows whole.
# To finish the other eight, give pendant() the early return hq_lib.plant() already has - record the
# anchor into UNREAL_PROPS, keep the light, skip the cone - and turn this on.
PENDANTS_DOME = os.environ.get("AMN_DRESS_PENDANTS", "0") != "0"
PENDANT_Y = 1.6  # hq_building.pendant hangs every one of them at this depth
FRONT_YAW.setdefault("pendant", float(os.environ.get("AMN_YAW_PENDANT", "0")))


def cz(level):
    """The room's ceiling: the second row of the floor's pair, as hq_building.cz reads it."""
    return Z(FLOORS[level][1])


SHADE_CM = {"dome": 60.0, "bulb": 34.0}


def pendants():
    """Pack shades where the build hangs its own, hung by the shade's rim. The build records each
    pendant it would have drawn (hq_scene.json props_m.pendants) and draws no cone there, so every
    one takes a shade; the table below is the fallback for an export that recorded none."""
    lamp = find_asset(PENDANT)
    if lamp is None:
        return
    meta = json.load(open(os.path.join(HERE, "hq_scene.json"), "r", encoding="utf-8"))
    recorded = (meta.get("props_m") or {}).get("pendants") or []
    if recorded:
        for i, item in enumerate(recorded):
            place("pendant", lamp, ue(item["x"], item["y"], item["z"] - 0.03), max_len=SHADE_CM.get(item["shade"], 60.0),
                  label=f"pendant_{i}")
        log(f"pendants: {len(recorded)} from the build's own anchors")
        return
    n = 0
    for level, xpx, drop, shade_cm, kind in PENDANTS:
        if kind == "dome" and not PENDANTS_DOME:
            continue
        # The build's shade ends 3 cm below its drop and place() sets the bounds' bottom on the target,
        # which on this mesh is the shade's rim: so the rim lands where the build's disc is and the cord
        # runs up from it. Sized by the shade's width, not by height - at 60 cm the lamp is 108 cm long,
        # so on L2 the cord ends 43 cm above the ceiling, inside the 54 cm slab where the floor above
        # hides it. Every level has the room (0.65 m on L3 and L1, 0.73 on the ground, the roof on L4).
        place("pendant", lamp, ue(X(xpx), PENDANT_Y, cz(level) - drop - 0.03), max_len=float(shade_cm),
              label=f"pendant_{level}_{xpx}")
        n += 1
    log(f"pendants: {n} of {len(PENDANTS)} ({'all' if PENDANTS_DOME else 'the bulbs only'})")


def room_clutter():
    if not CLUTTER_ON:
        return
    assets = {k: find_asset(p) for k, p in CLUTTER_ASSETS.items()}
    n = 0
    for level, kind, xpx, y, dz, mode, size in CLUTTER:
        asset = assets.get(kind)
        if asset is None:
            continue
        target = ue(X(xpx), y, fz(level) + dz)
        yaw = CLUTTER_YAW.get((level, kind, xpx), 0.0)
        actor = place(kind, asset, target, yaw_extra=yaw, height=size if mode == "h" else None,
                      max_len=size if mode == "l" else None, label=f"clutter_{level}_{kind}_{xpx}")
        if actor is not None and kind in CLUTTER_PAINT:
            _flat.paint(actor, kind.title(), CLUTTER_PAINT[kind], roughness=0.5)
        n += 1
    log(f"room clutter: {n} objects")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    replaced = []
    if ONLY in ("", "desks") and CONSOLES != "blender":
        replaced += ["consoles"]
    if ONLY in ("", "street"):
        replaced += ["street_props"] + (["tree_trunks", "tree_crowns"] if TREES else [])
    clear(set(replaced))
    if ONLY in ("", "desks"):
        desks()
    if ONLY in ("", "props"):
        props()
        room_clutter()
        pendants()
    if ONLY in ("", "street"):
        street()
        road_material()
    metahuman_presets()
    les.save_current_level()
    out = os.path.join(HERE, "dress_report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, indent=1)
    log(f"placed {len(REPORT['placed'])}, removed {REPORT['removed']}, missing {REPORT['missing']} -> {out}")


main()
