"""
Unreal Engine 5.8 editor script: builds the AMN-AI headquarters at the light of the Owner's
picture (dusk), from the Blender export made by art-source/unreal/export_hq_scene.py
(hq_scene.glb + hq_scene.json).

Creates /Game/HQ/Scene (imported meshes, materials, textures) and the level /Game/HQ/HQ_Dusk:
every mesh at the origin (the exporter bakes world transforms), the scene's lights, a dusk sky
(atmosphere, volumetric clouds, height fog, a sun just under the horizon on the picture's sunset
side, a real-time sky light), the plates' orthographic camera and a fixed-exposure look.

The importer's axis convention and unit scale are measured from marker cubes the exporter places
at known positions, never assumed.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=build_hq_scene.py
  UnrealEditor.exe     AMNReference.uproject -ExecCmds="py render_hq_still.py" -unattended -nosplash

Tunables come from the environment: AMN_LM_PER_W (lumens per Blender watt, default 120) and
AMN_EV (exposure compensation, default 0).
"""

import json
import math
import os

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
SKY_GAIN = float(os.environ.get("AMN_SKY_GAIN", "1.35"))
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
SUN_ELEVATION = -2.5  # degrees: the picture's light, as in the web scene's reference_dusk


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


def import_glb():
    task = unreal.AssetImportTask()
    task.filename = GLB
    task.destination_path = f"{PKG}/Scene"
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
    """The picture's dusk sky (compose_sky_backdrop.py) on an unlit backdrop behind the city.

    An orthographic camera cannot see the sky atmosphere, so the sky is an image. The backdrop
    stands 90 m behind the building, wide and tall enough to fill the camera's frame at that depth.
    """
    png = os.path.join(HERE, "sky_dusk.png")
    task = unreal.AssetImportTask()
    task.filename = png
    task.destination_path = f"{PKG}/Sky"
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(f"{PKG}/Sky/sky_dusk")
    mat_path = f"{PKG}/Sky/M_SkyBackdrop"
    if unreal.EditorAssetLibrary.does_asset_exist(mat_path):
        unreal.EditorAssetLibrary.delete_asset(mat_path)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_SkyBackdrop", f"{PKG}/Sky", unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    mel = unreal.MaterialEditingLibrary
    sample = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -400, 0)
    sample.set_editor_property("texture", texture)
    # lit, the backdrop reads darker than the web page's sky; AMN_SKY_GAIN brightens it
    gain = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -400, 220)
    gain.set_editor_property("r", SKY_GAIN)
    boost = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -200, 0)
    mel.connect_material_expressions(sample, "RGB", boost, "A")
    mel.connect_material_expressions(gain, "", boost, "B")
    mel.connect_material_property(boost, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)

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


def dusk_environment(ax):
    """The picture's dusk: a warm low sun from the left, slightly from above so it rims the building
    instead of lighting it from below; ambient light from the captured sky backdrop; light fog."""
    travel = ax.direction((0.9, 0.43, -math.sin(math.radians(8.0))))
    sun = spawn(unreal.DirectionalLight, vec(0, 0, 0), unreal.MathLibrary.make_rot_from_x(travel), "SunDusk")
    sun_comp = sun.light_component
    sun_comp.set_intensity(2.5)
    sun_comp.set_light_color(unreal.LinearColor(1.0, 0.62, 0.38, 1.0))
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
    log("dusk environment placed")


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
    lights(ax)
    dusk_environment(ax)
    scale_city_emission(actors)
    street_fill(ax)
    cam = camera(ax)
    look(cam)
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    unreal.EditorAssetLibrary.save_directory(PKG)
    log(f"level saved {LEVEL}")


main()
