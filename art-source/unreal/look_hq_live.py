"""
Unreal Engine 5.8 editor script: the look pass on the live headquarters (/Game/HQ/HQ_Dusk), applied
to the saved level in place, so the light can be tuned against the Owner's picture without
re-importing the Blender export. Run it after build_hq_scene.py and dress_hq_live.py, with the
stream stopped (the streamed game holds the level's packages):

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=look_hq_live.py

What the picture has and the first live passes did not (compared region by region, 2026-09-15):
soft, warm room light where the level threw hard coloured spot cones on the walls; a glowing, graded
dusk where the level was flat and crushed to black; a skyline of sparse lit windows in blue haze
where the level showed bright blocks with no depth; street lamps and headlights that light the
road without burning white patches on it; wet asphalt.

Every value is absolute (never a factor on the level's current value), so running the script again
gives the same level. Each tunable comes from the environment (AMN_LOOK_*).
"""

import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
META = json.load(open(os.path.join(HERE, "hq_scene.json"), "r", encoding="utf-8"))
BASELINE = os.path.join(HERE, "look_baseline.json")


def env(name, default):
    return float(os.environ.get(name, default))


# the build's own light balance (build_hq_scene.py), so a light's base is energy x lumens per watt
LUMENS_INTERIOR = env("AMN_LM_INTERIOR", os.environ.get("AMN_LM_PER_W", "1.0"))
LUMENS_EXTERIOR = env("AMN_LM_EXTERIOR", os.environ.get("AMN_LM_PER_W", "70"))
LEVEL_GAIN = {int(k): float(v) for k, v in (pair.split(":") for pair in os.environ.get("AMN_LEVEL_GAIN", "0:0.55,1:0.7,2:0.7,3:0.3,4:0.8").split(",") if ":" in pair)}
CEILINGS_M = [(655 - row) / 27.575 for row in (520, 410, 297, 195)]

# the look: factors on that base, per kind of light. Pass 1 (spot 0.45, road 0.12, city 0.45, fog
# 0.006 from 35 m, EV +0.35, bloom 1.1) made every region brighter than the picture (mean colour
# distance 24.2 -> 29.6), kept the green cones on L4's wall and turned the road into a mirror of
# the shopfronts; these defaults are pass 2.
SPOT = env("AMN_LOOK_SPOT", "0.2")           # interior spot rows: the hard cones on the walls
SPOT_SOFT = env("AMN_LOOK_SPOT_SOFT", "0.1")  # inner cone as a share of the outer: a soft edge
SPOT_WIDEN = env("AMN_LOOK_SPOT_WIDEN", "18")  # degrees added to the outer cone: a wash, not a disc
POINT = env("AMN_LOOK_POINT", "2.0")         # pendants, desk and floor lamps: the warm pools
FILL = env("AMN_LOOK_FILL", "1.6")           # the rooms' area fills
LAMP = env("AMN_LOOK_LAMP", "0.35")          # street lamps: they burnt white pools on the road
UPLIGHT = env("AMN_LOOK_UPLIGHT", "0.6")     # tree uplights
HEADLIGHT_LM = env("AMN_LOOK_HEADLIGHT_LM", "900")
TAILLIGHT_LM = env("AMN_LOOK_TAILLIGHT_LM", "160")
CITY = env("AMN_LOOK_CITY", "0.25")          # skyline window emission, on the imported value
ROAD_ROUGH = env("AMN_LOOK_ROAD_ROUGH", "0.32")  # wet, not a mirror
ROAD_SPECULAR = env("AMN_LOOK_ROAD_SPECULAR", "0.5")
FOG_DENSITY = env("AMN_LOOK_FOG", "0.02")
FOG_START_CM = env("AMN_LOOK_FOG_START", "6000")
EXPOSURE = env("AMN_LOOK_EV", "0")
BLOOM = env("AMN_LOOK_BLOOM", "0.8")

SPOT_NAMES = ("spot", "ops_spot", "feature_spot")
POINT_NAMES = ("pendant", "desk_lamp", "floor_lamp", "render_lamp", "ops_shelf_lamp")
FILL_NAMES = ("l2_fill", "l3_fill", "infra_fill", "lobby_fill", "lobby_spill", "ai_fill", "ai_logo_glow")
LAMP_NAMES = ("lamp_far_left", "lamp_left", "lamp_right")


def log(msg):
    unreal.log(f"AMN_LOOK {msg}")


def level_of(z_m):
    for level, ceiling in enumerate(CEILINGS_M):
        if z_m < ceiling:
            return level
    return len(CEILINGS_M)


def base_lumens(item):
    if item["group"] == "lights_interior":
        return item["energy"] * LUMENS_INTERIOR * LEVEL_GAIN.get(level_of(item["location_m"][2]), 1.0)
    return item["energy"] * LUMENS_EXTERIOR


def factor_for(name):
    if name.startswith(SPOT_NAMES):
        return SPOT
    if name.startswith(POINT_NAMES):
        return POINT
    if name.startswith(FILL_NAMES):
        return FILL
    if name.startswith(LAMP_NAMES):
        return LAMP
    if name.startswith("tree_uplight"):
        return UPLIGHT
    return 1.0


def tune_lights(actors):
    by_name = {item["name"]: item for item in META["lights"]}
    counts = {}
    for label, actor in actors.items():
        comp = actor.get_editor_property("light_component") if isinstance(actor, unreal.Light) else None
        if comp is None:
            continue
        if label.startswith("car_"):
            head = "head" in label
            comp.set_intensity(HEADLIGHT_LM if head else TAILLIGHT_LM)
            counts["vehicle"] = counts.get("vehicle", 0) + 1
            continue
        item = by_name.get(label)
        if item is None:
            continue
        f = factor_for(label)
        comp.set_intensity(base_lumens(item) * f)
        if isinstance(comp, unreal.SpotLightComponent) and item["group"] == "lights_interior":
            # from the scene's own cone, not the level's current one, so a rerun does not widen again
            outer = min(80.0, item["cone_deg"] / 2.0 + SPOT_WIDEN)
            comp.set_outer_cone_angle(outer)
            comp.set_inner_cone_angle(outer * SPOT_SOFT)
            comp.set_editor_property("source_radius", 8.0)
            comp.set_editor_property("soft_source_radius", 30.0)
        if isinstance(comp, unreal.PointLightComponent) and not isinstance(comp, unreal.SpotLightComponent):
            comp.set_editor_property("source_radius", 6.0)
        counts[f"x{f:g}"] = counts.get(f"x{f:g}", 0) + 1
    log(f"lights tuned {counts}")


def baseline():
    """The skyline's imported emission strengths, recorded the first time so reruns stay absolute."""
    if os.path.exists(BASELINE):
        return json.load(open(BASELINE, "r", encoding="utf-8"))
    return {}


def tune_materials(actors):
    mel = unreal.MaterialEditingLibrary
    base = baseline()
    city, road = 0, 0
    for label, actor in actors.items():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant):
                continue
            path = mat.get_path_name()
            scalars = [str(n) for n in mel.get_scalar_parameter_names(mat)]
            if label in ("skyline", "near_blocks") and "EmissiveStrength" in scalars:
                if path not in base:
                    base[path] = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
                mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", base[path] * CITY)
                mel.update_material_instance(mat)
                city += 1
            if label == "street_ground" and "asphalt" in path.lower() and "RoughnessFactor" in scalars:
                # only the factor: glTF instances also carry MetallicRoughnessTexture_TexCoord and
                # _Rotation, whose names contain "rough" too and would break the texture's UVs
                mel.set_material_instance_scalar_parameter_value(mat, "RoughnessFactor", ROAD_ROUGH)
                if "SpecularFactor" in scalars:
                    mel.set_material_instance_scalar_parameter_value(mat, "SpecularFactor", ROAD_SPECULAR)
                mel.update_material_instance(mat)
                road += 1
    with open(BASELINE, "w", encoding="utf-8") as fh:
        json.dump(base, fh, indent=1)
    log(f"skyline emission x{CITY} on {city} materials; road roughness {ROAD_ROUGH} on {road} parameters")


def apply_post(settings):
    values = (
        ("auto_exposure_bias", EXPOSURE),
        ("bloom_intensity", BLOOM),
        ("vignette_intensity", 0.3),
        # the picture's grade: a touch more colour, cool shadows, warm highlights
        ("color_saturation", unreal.Vector4(1.08, 1.08, 1.1, 1.0)),
        ("color_contrast", unreal.Vector4(1.05, 1.05, 1.05, 1.0)),
        ("color_gain_shadows", unreal.Vector4(0.9, 0.96, 1.12, 1.0)),
        ("color_gain_highlights", unreal.Vector4(1.08, 1.0, 0.9, 1.0)),
    )
    for name, value in values:
        try:
            setattr(settings, f"override_{name}", True)
            setattr(settings, name, value)
        except Exception as err:
            log(f"post-process {name} skipped: {err}")
    return settings


def tune_post_and_fog(actors):
    ppv = actors.get("DuskLook")
    if ppv is not None:
        ppv.settings = apply_post(ppv.settings)
    cam = actors.get("PlateCam")
    if cam is not None:
        comp = cam.camera_component
        comp.set_editor_property("post_process_settings", apply_post(comp.get_editor_property("post_process_settings")))
    fog = actors.get("HeightFog")
    if fog is not None:
        fc = fog.component
        fc.set_fog_density(FOG_DENSITY)
        for prop, value in (("start_distance", FOG_START_CM), ("fog_inscattering_luminance", unreal.LinearColor(0.3, 0.34, 0.55, 1.0))):
            try:
                fc.set_editor_property(prop, value)
            except Exception as err:
                log(f"fog {prop} skipped: {err}")
    log(f"post-process (exposure {EXPOSURE}, bloom {BLOOM}, grade) and fog ({FOG_DENSITY}, from {FOG_START_CM:.0f} cm)")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    tune_lights(actors)
    tune_materials(actors)
    tune_post_and_fog(actors)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log("saved")


main()
