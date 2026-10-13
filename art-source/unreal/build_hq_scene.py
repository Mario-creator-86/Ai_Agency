"""
Unreal Engine 5.8 editor script: builds the AMN-AI headquarters at the light of the Owner's
picture (dusk), from the Blender export made by art-source/unreal/export_hq_scene.py
(hq_scene.glb + hq_scene.json).

Creates /Game/HQ/Scene_<timestamp> (imported meshes, materials, textures; earlier builds' folders
are deleted once the level is saved) and the level /Game/HQ/HQ_Dusk:
every mesh at the origin (the exporter bakes world transforms), the scene's lights, the sky as a
picture on an unlit backdrop (an orthographic camera cannot see a sky atmosphere or volumetric
clouds: its rays all run 10 degrees below the horizon), light height fog, the two twilight keys
(SunDusk, SunDawn), a movable sun labelled "Sun", a sky light, the plates' orthographic camera and
a fixed-exposure look.

Everything is built at the Owner's picture (dusk, sun at -2.5 degrees), the look he approved. The
backend then moves it to the real hour over Remote Control: the twilight keys' intensity and colour,
the sun's rotation, intensity and colour, and the sky backdrop's cells (compose_sky_backdrop.py
--atlas; PlateA, PlateB, PlateBlend, Mirror, Gain). At those parameters' defaults the backdrop shows
today's dusk plate, and the lights are today's: SunDusk at 2.5, the morning key and the sun dark.

The importer's axis convention and unit scale are measured from marker cubes the exporter places
at known positions, never assumed, and written to axis_map.json for the passes after this one
(clock_hq_live.py, env_report_hq_live.py).

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=build_hq_scene.py
  UnrealEditor.exe     AMNReference.uproject -ExecCmds="py render_hq_still.py" -unattended -nosplash

Tunables come from the environment: AMN_LM_PER_W (lumens per Blender watt, default 120),
AMN_EV (exposure compensation, default 0; the Owner has not approved a moving exposure, D2, so it
stays fixed), AMN_SKY_ATMOSPHERE (a lighting-only sky atmosphere, off by default: D7) and
AMN_SUN_SHADOW_DISTANCE_CM / AMN_SUN_SHADOW_CASCADES (the movable sun's cascaded shadows; the
defaults are the cascades SunDusk draws, see SUN_SHADOW_DISTANCE_CM).
"""

import json
import math
import os
import time

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
# AMN_GLB picks another export (its .json sits next to it); the default is the standard export
GLB = os.environ.get("AMN_GLB") or os.path.join(HERE, "hq_scene.glb")
META = json.load(open(os.path.splitext(GLB)[0] + ".json", "r", encoding="utf-8"))
PKG = "/Game/HQ"
LEVEL = f"{PKG}/HQ_Dusk"
# Defaults are the balance measured closest to the picture (lit, 2026-09-13): interior 1.0 lm/W,
# exterior 70, sky 1.35, the floors below; the environment overrides each for experiments.
LUMENS_INTERIOR = float(os.environ.get("AMN_LM_INTERIOR", os.environ.get("AMN_LM_PER_W", "1.0")))
LUMENS_EXTERIOR = float(os.environ.get("AMN_LM_EXTERIOR", os.environ.get("AMN_LM_PER_W", "70")))
# 1.1 since the look pass (look_hq_live.py): at 1.35 the sky read brighter than the picture's
SKY_GAIN = float(os.environ.get("AMN_SKY_GAIN", "1.1"))
# multiplies the emission of the skyline's lit windows (lit, the city read brighter than the picture)
CITY_EMISSIVE = float(os.environ.get("AMN_CITY_EMISSIVE", "0.7"))
# lumens of a wide cool fill over the road, for what the street lamps do not reach (0 = none).
# Off by default: at 120000 lm it lifted the street a little but mirrored as a hard white oval on
# the wet road.
STREET_FILL = float(os.environ.get("AMN_STREET_FILL", "0"))
# Per-floor factors for interior lights, "level:gain,..." (0 = ground floor). Lit in Unreal the floors
# did not respond alike: L3 blew out long before L4 reached the picture's brightness.
LEVEL_GAIN = {int(k): float(v) for k, v in (pair.split(":") for pair in os.environ.get("AMN_LEVEL_GAIN", "0:0.55,1:0.7,2:0.7,3:0.3,4:0.8").split(",") if ":" in pair)}
# Ceiling heights (m) of the ground floor and L1..L4, from hq_building's FLOORS rows at the front plane:
# z = (655 - row) / 27.575 for ceiling rows 520, 410, 297, 195.
CEILINGS_M = [(655 - row) / 27.575 for row in (520, 410, 297, 195)]


def level_of(z_m):
    for level, ceiling in enumerate(CEILINGS_M):
        if z_m < ceiling:
            return level
    return len(CEILINGS_M)
SKYLIGHT = float(os.environ.get("AMN_SKYLIGHT", "0.6"))
EXPOSURE = float(os.environ.get("AMN_EV", "0"))
# The sky atlas compose_sky_backdrop.py --atlas writes (cells stacked top to bottom, the order in
# its sidecar .json). The rebuild composes it in its sky step.
SKY_ATLAS_PNG = os.path.join(HERE, "sky_atlas.png")
SKY_ATLAS_JSON = os.path.join(HERE, "sky_atlas.json")
AXIS_MAP_JSON = os.path.join(HERE, "axis_map.json")
# The lights of the hour. After sunset the warm light on a facade comes from the still-bright sky
# over the sunset, not from the sun, and the approved dusk is lit exactly that way: SunDusk, a warm
# key from the front-left (the west with D1), 8 degrees down, 2.5. It stays as every build since
# 2026-09-13 has made it - Stationary, same direction, colour and intensity - as the evening
# twilight key. SunDawn is its mirror from the front-right for the morning, built dark. A Stationary
# light may change its intensity and colour in the game but never its direction, and the backend
# sends only those two (from the real solar depression, on the real side of the sky).
#
# The rebuild of 2026-09-19 (rolled back) had turned SunDusk itself into the Movable sun, with
# cascades to 20000 cm. The build frame, before any value was sent, then scored 7.7-7.8 against the
# reference (6.3-6.4 for the old level): L1 and the ground floor 4-7 grey levels brighter. The plate
# camera stands 246 m in front of the facade, so a 200 m cascade range never reached the building
# and the sun lit the rooms through their unshadowed shells. At the real -2.5 degrees that one sun
# was also at 0 and the frame scored 10.3. Hence two roles in separate lights.
TWILIGHT_KEY_INTENSITY = 2.5
TWILIGHT_KEY_COLOR = (1.0, 0.62, 0.38)
TWILIGHT_KEY_MOBILITY = unreal.ComponentMobility.STATIONARY
TWILIGHT_KEY_TRAVEL_EVENING = (0.9, 0.43, -math.sin(math.radians(8.0)))
TWILIGHT_KEY_TRAVEL_MORNING = (-0.9, 0.43, -math.sin(math.radians(8.0)))
TWILIGHT_MORNING_BUILD_INTENSITY = 0.0
# The direct sun: Movable so the backend can turn it to the real elevation and azimuth, lit only
# while the real sun is above the horizon. Built at 0, so the build frame is today's: a light
# whose colour times intensity is black is not drawn at all, shadows included
# (FLightSceneInfo::ShouldRenderLightViewIndependent, LightSceneInfo.cpp in 5.8). Its colour is
# SunDusk's, which is also what the backend gives it at the reference.
SUN_BUILD_INTENSITY = 0.0
SUN_BUILD_COLOR = (1.0, 0.62, 0.38)
SUN_MOBILITY = unreal.ComponentMobility.MOVABLE
# Its cascades are the ones SunDusk draws in the game today: the level's lighting is never built,
# so a Stationary directional light previews its shadows with r.Shadow.UnbuiltWholeSceneDynamic-
# ShadowRadius (200000 cm) and r.Shadow.UnbuiltNumWholeSceneDynamicShadowCascades (4)
# (DirectionalLightComponent.cpp, with r.Shadow.UnbuiltPreviewInGame 1 by default). The same range
# covers the facade at 246 m and the backdrop behind it, so daylight shadows fall where the dusk's
# do. Ray-traced distance-field shadows (on by default for a Movable light) are turned off: the
# cascades already reach everything in the frame, and a Stationary light never used them. The
# rebuild window still measures p95 frame time with the sun lit (the day), not only at dusk, where
# it is not drawn.
SUN_SHADOW_DISTANCE_CM = float(os.environ.get("AMN_SUN_SHADOW_DISTANCE_CM", "200000"))
SUN_SHADOW_CASCADES = int(os.environ.get("AMN_SUN_SHADOW_CASCADES", "4"))
# Owner decision D7, not taken: an invisible SkyAtmosphere for lighting only (the sun's colour
# through the air, and something for the sky light's real-time capture to see). Off until the
# rehearsal gate at the reference dusk passes with it on (compare.py mean <= 6.4 over five frames).
SKY_ATMOSPHERE = os.environ.get("AMN_SKY_ATMOSPHERE", "0") == "1"


def log(msg):
    unreal.log(f"AMN_UE {msg}")


def vec(x, y, z):
    return unreal.Vector(float(x), float(y), float(z))


def add(a, b):
    return vec(a.x + b.x, a.y + b.y, a.z + b.z)


def sub(a, b):
    return vec(a.x - b.x, a.y - b.y, a.z - b.z)


def scale(a, k):
    return vec(a.x * k, a.y * k, a.z * k)


def length(a):
    return math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z)


def spawn(cls, location, rotation=None, label=None):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = eas.spawn_actor_from_class(cls, location, rotation or unreal.Rotator(0.0, 0.0, 0.0))
    if actor and label:
        actor.set_actor_label(label)
    return actor


# Each build imports into its own folder. Re-importing over the previous import, while the level
# still referenced it, could not replace the assets in use: textures piled up as renamed copies
# (props_color x37) and the skyline's facade materials lost their window textures (flat white
# towers). The folders of earlier builds are deleted once the new level is saved.
SCENE = f"{PKG}/Scene_{time.strftime('%Y%m%d_%H%M%S')}"


def import_glb():
    task = unreal.AssetImportTask()
    task.filename = GLB
    task.destination_path = SCENE
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths = list(task.imported_object_paths)
    log(f"imported {len(paths)} objects from {GLB}")
    return paths


def new_level():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(LEVEL):
        if not les.load_level(LEVEL):
            raise RuntimeError("could not load the existing level")
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        eas.destroy_actors(eas.get_all_level_actors())
        log(f"reusing level {LEVEL}")
    elif not les.new_level(LEVEL):
        raise RuntimeError("could not create level")


def place_meshes(paths):
    actors = {}
    for p in paths:
        asset = unreal.load_asset(p)
        if not isinstance(asset, unreal.StaticMesh):
            continue
        actor = spawn(unreal.StaticMeshActor, vec(0, 0, 0), label=asset.get_name())
        if actor is None:
            continue
        actor.static_mesh_component.set_static_mesh(asset)
        actor.static_mesh_component.set_mobility(unreal.ComponentMobility.STATIC)
        actors[asset.get_name()] = actor
    log(f"placed {len(actors)} mesh actors")
    return actors


class AxisMap:
    """Blender metres -> Unreal location, measured from the exporter's marker cubes."""

    def __init__(self, actors):
        def centre(prefix):
            for label, actor in actors.items():
                if label.startswith(prefix):
                    origin, _ = actor.get_actor_bounds(False)
                    return origin, actor
            raise RuntimeError(f"marker {prefix} not imported")

        marks = META["markers_m"]
        self.o, o_actor = centre("AMN_MARKER_O")
        x, x_actor = centre("AMN_MARKER_X")
        y, y_actor = centre("AMN_MARKER_Y")
        z, z_actor = centre("AMN_MARKER_Z")
        self.bo = marks["AMN_MARKER_O"]
        self.ex = scale(sub(x, self.o), 1.0 / (marks["AMN_MARKER_X"][0] - self.bo[0]))
        self.ey = scale(sub(y, self.o), 1.0 / (marks["AMN_MARKER_Y"][1] - self.bo[1]))
        self.ez = scale(sub(z, self.o), 1.0 / (marks["AMN_MARKER_Z"][2] - self.bo[2]))
        self.unit = length(self.ex)
        for a in (o_actor, x_actor, y_actor, z_actor):
            a.destroy_actor()
        log(f"axes ex=({self.ex.x:.1f},{self.ex.y:.1f},{self.ex.z:.1f}) ey=({self.ey.x:.1f},{self.ey.y:.1f},{self.ey.z:.1f}) "
            f"ez=({self.ez.x:.1f},{self.ez.y:.1f},{self.ez.z:.1f}) units/m={self.unit:.1f}")

    def point(self, p):
        d = (p[0] - self.bo[0], p[1] - self.bo[1], p[2] - self.bo[2])
        return add(self.o, add(scale(self.ex, d[0]), add(scale(self.ey, d[1]), scale(self.ez, d[2]))))

    def direction(self, d):
        v = add(scale(self.ex, d[0]), add(scale(self.ey, d[1]), scale(self.ez, d[2])))
        n = length(v) or 1.0
        return scale(v, 1.0 / n)

    def write(self, path):
        """The measurement, for the passes that place things after this one and for the report the
        backend reads (the sun's azimuth has to be turned into Unreal through these same axes)."""
        def xyz(v):
            return [round(v.x, 6), round(v.y, 6), round(v.z, 6)]

        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"origin_unreal": xyz(self.o), "origin_scene_m": list(self.bo), "ex": xyz(self.ex),
                       "ey": xyz(self.ey), "ez": xyz(self.ez), "units_per_m": round(self.unit, 6),
                       "note": "Unreal units per Blender metre along the scene's +x, +y, +z, measured "
                               "from the exporter's marker cubes by build_hq_scene.py"}, fh, indent=1)
        log(f"axis map written to {path}")


def lights(ax):
    count = 0
    for item in META["lights"]:
        kind = item["kind"]
        if kind == "SUN":
            continue
        loc = ax.point(item["location_m"])
        rot = unreal.MathLibrary.make_rot_from_x(ax.direction(item["direction"]))
        if kind == "POINT":
            actor = spawn(unreal.PointLight, loc, label=item["name"])
            comp = actor.point_light_component
        elif kind == "SPOT":
            actor = spawn(unreal.SpotLight, loc, rot, item["name"])
            comp = actor.spot_light_component
            half = item["cone_deg"] / 2.0
            comp.set_outer_cone_angle(half)
            comp.set_inner_cone_angle(half * max(0.0, 1.0 - item.get("blend", 0.3)))
        elif kind == "AREA":
            actor = spawn(unreal.RectLight, loc, rot, item["name"])
            comp = actor.rect_light_component
            size = item.get("size_m", 1.0) * ax.unit
            comp.set_editor_property("source_width", size)
            comp.set_editor_property("source_height", size)
        else:
            continue
        comp.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
        # interior and exterior are balanced separately: lit, the rooms blew out long before the
        # sky and the street were bright enough
        per_watt = LUMENS_INTERIOR if item["group"] == "lights_interior" else LUMENS_EXTERIOR
        if item["group"] == "lights_interior":
            per_watt *= LEVEL_GAIN.get(level_of(item["location_m"][2]), 1.0)
        comp.set_intensity(item["energy"] * per_watt)
        comp.set_light_color(unreal.LinearColor(item["color"][0], item["color"][1], item["color"][2], 1.0))
        comp.set_attenuation_radius((25.0 if item["group"] == "lights_exterior" else 10.0) * ax.unit)
        count += 1
    log(f"placed {count} lights (interior {LUMENS_INTERIOR} lm/W, exterior {LUMENS_EXTERIOR} lm/W)")


def sky_backdrop(ax):
    """The sky of the hour (compose_sky_backdrop.py --atlas) on an unlit backdrop behind the city.

    An orthographic camera cannot see the sky atmosphere, so the sky is a picture. The backdrop
    stands 90 m behind the building, wide and tall enough to fill the camera's frame at that depth.

    Its material samples two cells of the atlas and blends them: PlateA and PlateB are cell indices
    (the order of sky_atlas.json's "elevations"), PlateBlend goes from A to B, Mirror flips the
    picture left to right (the plates paint the evening glow on the left; a morning sky has it on
    the right), Gain brightens it (AMN_SKY_GAIN). Scalars only: a texture swap through Remote
    Control is unproven. The defaults are the reference cell (-2.5 degrees), no blend, no mirror, and
    today's gain, so until the backend sends anything the backdrop is today's dusk plate: the same
    image before its x2 upscale (the atlas is at the composer's native 1600 x 840 per cell; ten
    upscaled cells would pass the engine's 16384 limit), without mips as before (a texture whose
    size is not a power of two gets none), and at the import's default compression, as before.
    """
    if not (os.path.exists(SKY_ATLAS_PNG) and os.path.exists(SKY_ATLAS_JSON)):
        raise RuntimeError(f"{SKY_ATLAS_PNG} missing: run `py -3.11 compose_sky_backdrop.py --atlas` first")
    atlas = json.load(open(SKY_ATLAS_JSON, "r", encoding="utf-8"))
    cells = int(atlas["cells"])
    reference = int(atlas["reference_cell"])
    task = unreal.AssetImportTask()
    task.filename = SKY_ATLAS_PNG
    task.destination_path = f"{PKG}/Sky"
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(f"{PKG}/Sky/sky_atlas")
    if texture is None:
        raise RuntimeError(f"could not import {SKY_ATLAS_PNG}")
    # stated, not left to the size: a mip of a stacked atlas would blend neighbouring cells
    texture.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    unreal.EditorAssetLibrary.save_loaded_asset(texture)
    mat_path = f"{PKG}/Sky/M_SkyBackdrop"
    mel = unreal.MaterialEditingLibrary
    mat = None
    if unreal.EditorAssetLibrary.does_asset_exist(mat_path) and not unreal.EditorAssetLibrary.delete_asset(mat_path):
        # still referenced (the reused level, or another process): rebuild the existing material's graph
        mat = unreal.load_asset(mat_path)
        mel.delete_all_material_expressions(mat)
        log("sky material kept and its graph rebuilt (it could not be deleted)")
    if mat is None:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SkyBackdrop", f"{PKG}/Sky", unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError(f"could not create or load {mat_path}")
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", float(value))
        return n

    def into_clamp(src, clamp):
        # a Clamp has three inputs; the editing library names its first "" or "Input" depending
        # on the version, and answers False rather than raising when a name does not fit
        if not any(mel.connect_material_expressions(src, "", clamp, name) for name in ("", "Input")):
            raise RuntimeError("could not wire the sky material's clamp")

    # u across the plate, flipped by Mirror (lerp(u, 1 - u, Mirror) is u itself at 0)
    uv = node(unreal.MaterialExpressionTextureCoordinate, -1600, 0)
    u = node(unreal.MaterialExpressionComponentMask, -1400, -100)
    v = node(unreal.MaterialExpressionComponentMask, -1400, 150)
    for mask, channel in ((u, "r"), (v, "g")):
        for c in ("r", "g", "b", "a"):
            mask.set_editor_property(c, c == channel)
        mel.connect_material_expressions(uv, "", mask, "")
    flipped = node(unreal.MaterialExpressionOneMinus, -1200, -50)
    mel.connect_material_expressions(u, "", flipped, "")
    mirrored = node(unreal.MaterialExpressionLinearInterpolate, -1000, -100)
    mel.connect_material_expressions(u, "", mirrored, "A")
    mel.connect_material_expressions(flipped, "", mirrored, "B")
    mel.connect_material_expressions(scalar("Mirror", 0.0, -1200, -200), "", mirrored, "Alpha")
    # v inside one cell, held half a texel off its edges so the bilinear filter never reaches into
    # the cell above or below (the backdrop's top and bottom rows lie 2 m outside the frame anyway)
    held = node(unreal.MaterialExpressionClamp, -1200, 150)
    held.set_editor_property("min_default", 0.5 / float(atlas["cell_height"]))
    held.set_editor_property("max_default", 1.0 - 0.5 / float(atlas["cell_height"]))
    into_clamp(v, held)

    def cell_sample(param, y):
        """The atlas at cell `param` (floored and clamped to the cells there are): v = (i + v) / n."""
        index = node(unreal.MaterialExpressionFloor, -1200, y)
        mel.connect_material_expressions(scalar(param, reference, -1400, y), "", index, "")
        inside = node(unreal.MaterialExpressionClamp, -1050, y)
        inside.set_editor_property("min_default", 0.0)
        inside.set_editor_property("max_default", float(cells - 1))
        into_clamp(index, inside)
        row = node(unreal.MaterialExpressionAdd, -900, y)
        mel.connect_material_expressions(inside, "", row, "A")
        mel.connect_material_expressions(held, "", row, "B")
        atlas_v = node(unreal.MaterialExpressionMultiply, -750, y)
        atlas_v.set_editor_property("const_b", 1.0 / cells)
        mel.connect_material_expressions(row, "", atlas_v, "A")
        at = node(unreal.MaterialExpressionAppendVector, -600, y)
        mel.connect_material_expressions(mirrored, "", at, "A")
        mel.connect_material_expressions(atlas_v, "", at, "B")
        # both samplers are the one SkyAtlas parameter (same name, same texture)
        sample = node(unreal.MaterialExpressionTextureSampleParameter2D, -400, y)
        sample.set_editor_property("parameter_name", "SkyAtlas")
        sample.set_editor_property("texture", texture)
        mel.connect_material_expressions(at, "", sample, "UVs")
        return sample

    plate_a = cell_sample("PlateA", 350)
    plate_b = cell_sample("PlateB", 650)
    blend = node(unreal.MaterialExpressionLinearInterpolate, -200, 450)
    mel.connect_material_expressions(plate_a, "RGB", blend, "A")
    mel.connect_material_expressions(plate_b, "RGB", blend, "B")
    mel.connect_material_expressions(scalar("PlateBlend", 0.0, -400, 900), "", blend, "Alpha")
    # lit, the backdrop reads darker than the web page's sky; AMN_SKY_GAIN brightens it
    boost = node(unreal.MaterialExpressionMultiply, 0, 450)
    mel.connect_material_expressions(blend, "", boost, "A")
    mel.connect_material_expressions(scalar("Gain", SKY_GAIN, -200, 650), "", boost, "B")
    mel.connect_material_property(boost, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log(f"sky material: {cells} cells ({', '.join(f'{e:g}' for e in atlas['elevations'])} deg), "
        f"PlateA = PlateB = {reference} ({atlas['reference_elevation']} deg), Gain {SKY_GAIN}")

    depth_m = 90.0
    # rows 0..840 at this depth: row = 655 - 27.575 z - 4.862 y
    z_top = (655.0 - 0.0 - 4.862 * depth_m) / 27.575 + 2.0
    z_bottom = (655.0 - 840.0 - 4.862 * depth_m) / 27.575 - 2.0
    width_m = META["camera"]["width_m"] + 6.0
    centre = ax.point((0.0, depth_m, (z_top + z_bottom) / 2.0))
    plane = spawn(unreal.StaticMeshActor, centre, unreal.Rotator(0.0, 0.0, 0.0), "SkyBackdrop")
    comp = plane.static_mesh_component
    comp.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
    comp.set_material(0, mat)
    comp.set_cast_shadow(False)
    plane.set_actor_scale3d(vec(width_m, 0.02, z_top - z_bottom))
    log(f"sky backdrop {width_m:.0f} x {z_top - z_bottom:.0f} m at {depth_m} m")


def scale_city_emission(actors):
    """Scale EmissiveStrength on the skyline's materials (glTF import instances expose it)."""
    if abs(CITY_EMISSIVE - 1.0) < 1e-3:
        return
    mel = unreal.MaterialEditingLibrary
    seen = set()
    changed = 0
    for label, actor in actors.items():
        if not any(key in label.lower() for key in ("skyline", "near_blocks")):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant) or mat.get_path_name() in seen:
                continue
            seen.add(mat.get_path_name())
            try:
                value = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
            except Exception:
                continue
            if value > 0:
                mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", value * CITY_EMISSIVE)
                mel.update_material_instance(mat)
                changed += 1
    log(f"city emission x{CITY_EMISSIVE} on {changed} materials")


def street_fill(ax):
    """A wide, cool, shadowless area light over the road, pointing down."""
    if STREET_FILL <= 0:
        return
    loc = ax.point((0.0, -16.0, 8.0))
    fill = spawn(unreal.RectLight, loc, unreal.MathLibrary.make_rot_from_x(ax.direction((0.0, 0.0, -1.0))), "StreetFill")
    comp = fill.rect_light_component
    comp.set_editor_property("intensity_units", unreal.LightUnits.LUMENS)
    comp.set_intensity(STREET_FILL)
    comp.set_light_color(unreal.LinearColor(0.55, 0.62, 0.9, 1.0))
    comp.set_editor_property("source_width", 60.0 * ax.unit)
    comp.set_editor_property("source_height", 16.0 * ax.unit)
    comp.set_attenuation_radius(30.0 * ax.unit)
    comp.set_cast_shadows(False)
    log(f"street fill {STREET_FILL:.0f} lm")


def directional(ax, label, travel, mobility, intensity, colour):
    light = spawn(unreal.DirectionalLight, vec(0, 0, 0), unreal.MathLibrary.make_rot_from_x(ax.direction(travel)), label)
    comp = light.light_component
    comp.set_mobility(mobility)
    comp.set_intensity(intensity)
    comp.set_light_color(unreal.LinearColor(colour[0], colour[1], colour[2], 1.0))
    return comp


def dusk_environment(ax):
    """The picture's dusk: the evening twilight key, a warm light from the left slightly from above
    so it rims the building instead of lighting it from below; its morning mirror and the real sun,
    both dark; a sky light; light fog.

    SunDusk is spawned first and exactly as before (TWILIGHT_KEY_*), so the frame the level shows
    before the backend sends anything is today's. The height fog's directional inscattering follows
    the brightest atmosphere-sun light (FScene::ProcessAtmosphereLightAddition), which at the build
    is SunDusk alone, as today. The sky light stays Stationary: its real-time capture works as it
    is and its intensity and colour are settable, so Movable would only add risk. That capture sees
    only a sky atmosphere, clouds and IsSky meshes, none of which this level has by default (the
    backdrop is an ordinary unlit mesh), so it gathers almost nothing; with AMN_SKY_ATMOSPHERE it has
    the atmosphere to see."""
    evening = directional(ax, "SunDusk", TWILIGHT_KEY_TRAVEL_EVENING, TWILIGHT_KEY_MOBILITY,
                          TWILIGHT_KEY_INTENSITY, TWILIGHT_KEY_COLOR)
    morning = directional(ax, "SunDawn", TWILIGHT_KEY_TRAVEL_MORNING, TWILIGHT_KEY_MOBILITY,
                          TWILIGHT_MORNING_BUILD_INTENSITY, TWILIGHT_KEY_COLOR)
    # built along SunDusk's travel; the backend turns it to the real sun before it is ever lit
    sun_comp = directional(ax, "Sun", TWILIGHT_KEY_TRAVEL_EVENING, SUN_MOBILITY, SUN_BUILD_INTENSITY, SUN_BUILD_COLOR)
    for prop, value in (("dynamic_shadow_distance_movable_light", SUN_SHADOW_DISTANCE_CM),
                        ("dynamic_shadow_cascades", SUN_SHADOW_CASCADES),
                        ("use_ray_traced_distance_field_shadows", False)):
        try:
            sun_comp.set_editor_property(prop, value)
        except Exception as err:
            raise RuntimeError(f"sun shadow setting {prop} refused: {err}") from err
    log(f"twilight keys SunDusk ({TWILIGHT_KEY_INTENSITY}) and SunDawn ({TWILIGHT_MORNING_BUILD_INTENSITY}) Stationary; "
        f"sun Movable at {SUN_BUILD_INTENSITY}, cascaded shadows to {SUN_SHADOW_DISTANCE_CM:.0f} cm in {SUN_SHADOW_CASCADES} cascades")
    sky_backdrop(ax)
    sky = spawn(unreal.SkyLight, vec(0, 0, 500), label="SkyLight")
    sky_comp = sky.light_component
    try:
        sky_comp.set_editor_property("real_time_capture", True)
    except Exception as err:
        log(f"sky light real-time capture skipped: {err}")
    # ambient for what no lamp reaches: the building's frame, the pavement, the planters
    sky_comp.set_intensity(SKYLIGHT)
    fog = spawn(unreal.ExponentialHeightFog, vec(0, 0, 0), label="HeightFog")
    try:
        fc = fog.component
        fc.set_fog_density(0.0015)
        fc.set_editor_property("fog_inscattering_luminance", unreal.LinearColor(0.22, 0.24, 0.4, 1.0))
    except Exception as err:
        log(f"fog settings skipped: {err}")
    if SKY_ATMOSPHERE:
        sky_atmosphere(fog)
        # only the real sun lights the atmosphere; the keys stand at 8 degrees above the horizon,
        # where the real sky does not have them
        for key in (evening, morning):
            key.set_editor_property("atmosphere_sun_light", False)
    log(f"dusk environment placed (sky atmosphere {'ON, lighting only' if SKY_ATMOSPHERE else 'off'})")


def sky_atmosphere(fog):
    """AMN_SKY_ATMOSPHERE=1 only: a SkyAtmosphere that lights and is not seen. The sun already has
    bAtmosphereSunLight, so the atmosphere gives it the colour of its path through the air and its
    fade below the horizon, and the sky light's real-time capture gets a warm western sky to gather.
    The visible frame is kept as it is: its aerial perspective starts 1 km out, past the backdrop
    (about 340 m from the plate camera), and the fog takes none of its ambient light. Whether it
    stays is the rehearsal gate's call (the reference dusk, compare.py mean <= 6.4 over five frames)."""
    atmosphere = spawn(unreal.SkyAtmosphere, vec(0, 0, 0), label="SkyAtmosphere")
    comp = atmosphere.get_component_by_class(unreal.SkyAtmosphereComponent)
    comp.set_editor_property("aerial_perspective_start_depth", 1.0)  # km
    try:
        fog.component.set_editor_property("sky_atmosphere_ambient_contribution_color_scale",
                                          unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    except Exception as err:
        raise RuntimeError(f"fog would take the atmosphere's ambient light: {err}") from err
    log("sky atmosphere placed: lighting only, aerial perspective from 1 km")


def camera(ax):
    c = META["camera"]
    loc = ax.point(c["location_m"])
    rot = unreal.MathLibrary.make_rot_from_x(ax.direction(c["look_direction"]))
    cam = spawn(unreal.CameraActor, loc, rot, "PlateCam")
    comp = cam.camera_component
    comp.set_projection_mode(unreal.CameraProjectionMode.ORTHOGRAPHIC)
    comp.set_ortho_width(c["width_m"] * ax.unit)
    comp.set_aspect_ratio(c["aspect"])
    for prop, val in (("constrain_aspect_ratio", True), ("auto_calculate_ortho_planes", False), ("ortho_near_clip_plane", 1.0), ("ortho_far_clip_plane", 2000.0 * ax.unit)):
        try:
            comp.set_editor_property(prop, val)
        except Exception as err:
            log(f"camera property {prop} skipped: {err}")
    # The live stream runs the level as a game: player 0 must look through this camera.
    cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
    log(f"camera at ({loc.x:.0f},{loc.y:.0f},{loc.z:.0f}) rot=({rot.pitch:.1f},{rot.yaw:.1f},{rot.roll:.1f}) ortho={c['width_m'] * ax.unit:.0f}")
    return cam


def look(cam=None):
    """Fixed exposure and bloom, on an unbound volume and on the plate camera itself: the editor's
    high-resolution screenshot through the camera uses the camera's post-process settings (a probe
    showed the volume's exposure stored but ignored in the still)."""
    ppv = spawn(unreal.PostProcessVolume, vec(0, 0, 0), label="DuskLook")
    ppv.set_editor_property("unbound", True)
    s = ppv.settings
    apply_look(s)
    ppv.settings = s
    if cam is not None:
        comp = cam.camera_component
        cs = comp.get_editor_property("post_process_settings")
        apply_look(cs)
        comp.set_editor_property("post_process_settings", cs)
        comp.set_editor_property("post_process_blend_weight", 1.0)
    log(f"look placed (exposure {EXPOSURE}, camera {'yes' if cam else 'no'})")


def apply_look(s):
    settings = (
        ("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL),
        ("auto_exposure_apply_physical_camera_exposure", False),
        ("auto_exposure_bias", EXPOSURE),
        ("dynamic_global_illumination_method", unreal.DynamicGlobalIlluminationMethod.LUMEN),
        ("reflection_method", unreal.ReflectionMethod.LUMEN),
        ("bloom_intensity", 0.6),
        ("vignette_intensity", 0.25),
        ("film_grain_intensity", 0.0),
    )
    for name, value in settings:
        try:
            setattr(s, f"override_{name}", True)
            setattr(s, name, value)
        except Exception as err:
            log(f"post-process {name} skipped: {err}")


def main():
    paths = import_glb()
    new_level()
    actors = place_meshes(paths)
    ax = AxisMap(actors)
    ax.write(AXIS_MAP_JSON)
    lights(ax)
    dusk_environment(ax)
    scale_city_emission(actors)
    street_fill(ax)
    cam = camera(ax)
    look(cam)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    unreal.EditorAssetLibrary.save_directory(PKG)
    log(f"level saved {LEVEL}")
    # Deleting earlier builds' Scene_ folders is a memory spike after the work is saved: on
    # 2026-09-19 it killed this commandlet twice ("Ran out of memory ... paging file is too
    # small", 20.5 GiB used with another program holding 20.8 GB of commit). The saved level no
    # longer references them, so they are only disk; a run that wants them gone asks for it.
    if os.environ.get("AMN_REMOVE_OLD_SCENES") == "1":
        remove_old_scenes()
    else:
        log("old scene folders kept (set AMN_REMOVE_OLD_SCENES=1 to delete them)")


def remove_old_scenes():
    """Deletes the scene folders of earlier builds; the saved level now references only SCENE."""
    root = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())
    hq = os.path.join(root, "HQ")
    for name in sorted(os.listdir(hq)):
        path = f"{PKG}/{name}"
        if (name == "Scene" or name.startswith("Scene_")) and path != SCENE and os.path.isdir(os.path.join(hq, name)):
            ok = unreal.EditorAssetLibrary.delete_directory(path)
            log(f"old scene folder {path} {'deleted' if ok else 'NOT deleted (still referenced?)'}")


main()
