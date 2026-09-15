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
# the shopfronts. The defaults below are the balance of the closest full pass (with the pack plants,
# paintings and wet asphalt: mean colour distance 15.8): spot 0.15, fills 1.4, lamps 0.5, city 0.5,
# fog 0.008 from 30 m, no exposure offset. Lamps at 0.8 lit the lift tower and the ground floor and
# left the road as dark.
SPOT = env("AMN_LOOK_SPOT", "0.15")          # interior spot rows: the hard cones on the walls
SPOT_SOFT = env("AMN_LOOK_SPOT_SOFT", "0.1")  # inner cone as a share of the outer: a soft edge
SPOT_WIDEN = env("AMN_LOOK_SPOT_WIDEN", "18")  # degrees added to the outer cone: a wash, not a disc
POINT = env("AMN_LOOK_POINT", "2.0")         # pendants, desk and floor lamps: the warm pools
FILL = env("AMN_LOOK_FILL", "1.4")           # the rooms' area fills
LOBBY = env("AMN_LOOK_LOBBY", "0.75")        # the lobby's fills and spill, on top of FILL (it read 83 against the picture's 68)
LAMP = env("AMN_LOOK_LAMP", "0.5")           # street lamps: at full they burnt white pools on the road
UPLIGHT = env("AMN_LOOK_UPLIGHT", "0.3")     # tree uplights (the leafy crowns read too bright at 0.6)
HEADLIGHT_LM = env("AMN_LOOK_HEADLIGHT_LM", "900")
TAILLIGHT_LM = env("AMN_LOOK_TAILLIGHT_LM", "160")
CITY = env("AMN_LOOK_CITY", "0.5")           # skyline window emission, on the imported value
ROAD_ROUGH = env("AMN_LOOK_ROAD_ROUGH", "0.32")  # wet, not a mirror (only for the imported asphalt)
ROAD_SPECULAR = env("AMN_LOOK_ROAD_SPECULAR", "0.5")
# the wet asphalt instance dress_hq_live.py puts on the road (its roughness texture is remapped to this
# range), and the roughness up to which Lumen traces real reflections (the engine's own default is
# 0.4, so most of the road at 0.25-0.5 fell back to a dull reflection without the lights' streaks)
ROAD_MI = "/Game/HQ/Materials/MI_HQ_AsphaltWet"
ROAD_ROUGH_MIN = env("AMN_LOOK_ROAD_ROUGH_MIN", "0.25")
ROAD_ROUGH_MAX = env("AMN_LOOK_ROAD_ROUGH_MAX", "0.5")
TRACE_ROUGHNESS = env("AMN_LOOK_TRACE_ROUGHNESS", "0.4")
# The building's frame (the Blender scene's dark blue metal, 0.5-0.6 metallic) renders black in the
# live frame where the picture's frame is a lit grey: metal shows only what it reflects, and the dusk
# around it is dark. AMN_LOOK_FRAME_METAL sets those materials' metallic factor (below 0 leaves them).
# Tried at 0.1 on all 8 frame materials (2026-09-15): no visible change and no region moved, so the
# frame is black for want of light on it, not for its metal; left off.
FRAME_MATERIALS = ("frame_dark", "frame_hi", "slab")
FRAME_METAL = env("AMN_LOOK_FRAME_METAL", "-1")
FOG_DENSITY = env("AMN_LOOK_FOG", "0.008")    # 0.02 greyed the street and brightened the sky
FOG_START_CM = env("AMN_LOOK_FOG_START", "3000")
# Distances are from the plate camera, 246 m in front of the building (the street at ~220 m, the
# building's back at ~262 m, the skyline's towers at 264-315 m, the sky backdrop at ~340 m). Past
# the cutoff nothing is fogged (0 = no cutoff), so the skyline can take haze the sky backdrop does not.
FOG_CUTOFF_CM = env("AMN_LOOK_FOG_CUTOFF", "0")
EXPOSURE = env("AMN_LOOK_EV", "0")
BLOOM = env("AMN_LOOK_BLOOM", "0.8")
# The road and the near pavement: no lamp reaches them (the lamps' pools stay on the far pavement)
# and the dusk sky light alone left them at 15-45 of 255 where the picture's are a lit, cool grey at
# 55-100 (mean colour of the street's bands, 2026-09-15). Lumens of a wide cool area light straight
# down over them; 0 turns it off. Compared in the stream (street region colour distance, 28.4 without):
# 4000 lm over the near pavement (y -24 m, 24 m across) 20.3, the pale pavement overshot lavender;
# 6000 lm over the road (y -16 m, 16 m) 46.4, a flat grey street; 3000 lm at y -16 m 18.2; 3000 lm
# at y -19 m, 14 m across 13.5 (mean over all regions 15.6, the closest pass so far).
STREET_FILL = env("AMN_LOOK_STREET_FILL", "3000")
STREET_FILL_Y = env("AMN_LOOK_STREET_FILL_Y", "-19")          # Blender metres; the road spans -23 to -9
STREET_FILL_DEPTH = env("AMN_LOOK_STREET_FILL_DEPTH", "1400")  # cm across the street
STREET_FILL_COLOR = unreal.LinearColor(0.7, 0.73, 0.88, 1.0)

SPOT_NAMES = ("spot", "ops_spot", "feature_spot")
POINT_NAMES = ("pendant", "desk_lamp", "floor_lamp", "render_lamp", "ops_shelf_lamp")
FILL_NAMES = ("l2_fill", "l3_fill", "infra_fill", "lobby_fill", "lobby_spill", "ai_fill", "ai_logo_glow")
LAMP_NAMES = ("lamp_far_left", "lamp_left", "lamp_right")


def log(msg):
    unreal.log(f"AMN_LOOK {msg}")


def ue(x_m, y_m, z_m):
    """Blender metres -> Unreal centimetres (the importer maps Blender +y to Unreal -y)."""
    return unreal.Vector(x_m * 100.0, -y_m * 100.0, z_m * 100.0)


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
    if name.startswith("lobby_"):
        return FILL * LOBBY
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
    frames = {}
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
            # the import numbers each material ("frame_dark_001"); compare the scene's own name, so
            # "mon_frame_001" or "edge_led_slab_001" stay out
            base_name = path.rsplit("/", 1)[-1].split(".")[0].lower().rstrip("0123456789").rstrip("_")
            if FRAME_METAL >= 0 and base_name in FRAME_MATERIALS and path not in frames:
                if "MetallicFactor" in scalars:
                    mel.set_material_instance_scalar_parameter_value(mat, "MetallicFactor", FRAME_METAL)
                    mel.update_material_instance(mat)
                frames[path] = scalars
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
    if FRAME_METAL >= 0:
        with_metal = [p for p, s in frames.items() if "MetallicFactor" in s]
        log(f"frame metallic {FRAME_METAL} on {len(with_metal)} of {len(frames)} frame materials {sorted(frames)[:6]}")
    if unreal.EditorAssetLibrary.does_asset_exist(ROAD_MI):
        wet = unreal.load_asset(ROAD_MI)
        mel.set_material_instance_scalar_parameter_value(wet, "Roughness Min", ROAD_ROUGH_MIN)
        mel.set_material_instance_scalar_parameter_value(wet, "Roughness Max", ROAD_ROUGH_MAX)
        mel.update_material_instance(wet)
        unreal.EditorAssetLibrary.save_loaded_asset(wet)
        log(f"wet asphalt roughness {ROAD_ROUGH_MIN}-{ROAD_ROUGH_MAX}")


def apply_post(settings):
    values = (
        ("auto_exposure_bias", EXPOSURE),
        ("bloom_intensity", BLOOM),
        ("lumen_max_roughness_to_trace_reflections", TRACE_ROUGHNESS),
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
        for prop, value in (("start_distance", FOG_START_CM), ("fog_cutoff_distance", FOG_CUTOFF_CM),
                            ("fog_inscattering_luminance", unreal.LinearColor(0.3, 0.34, 0.55, 1.0))):
            try:
                fc.set_editor_property(prop, value)
            except Exception as err:
                log(f"fog {prop} skipped: {err}")
    log(f"post-process (exposure {EXPOSURE}, bloom {BLOOM}, grade) and fog ({FOG_DENSITY}, from {FOG_START_CM:.0f} cm, cutoff {FOG_CUTOFF_CM:.0f} cm)")


def street_fill(actors):
    """A wide area light 6 m up, straight down over the street (the building's front is at Blender
    y 0, so the light stays off the rooms), cool like the dusk sky, without shadows. Pointing down,
    the light's width runs across the street and its height along it."""
    fill = actors.get("StreetFill")
    if fill is None and STREET_FILL <= 0:
        return
    where, down = ue(0.0, STREET_FILL_Y, 6.0), unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0)
    if fill is None:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        fill = eas.spawn_actor_from_class(unreal.RectLight, where, down)
        fill.set_actor_label("StreetFill")
    fill.set_actor_location_and_rotation(where, down, False, False)
    comp = fill.rect_light_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_intensity_units(unreal.LightUnits.LUMENS)
    comp.set_intensity(max(STREET_FILL, 0.0))
    comp.set_light_color(STREET_FILL_COLOR)
    comp.set_editor_property("source_width", STREET_FILL_DEPTH)
    comp.set_editor_property("source_height", 6000.0)
    comp.set_attenuation_radius(3000.0)
    comp.set_cast_shadows(False)
    lamp = actors.get("lamp_left")
    check = f"; lamp_left stands at {lamp.get_actor_location()} (scene -17.07, -1.43, 5.59 m)" if lamp else ""
    log(f"street fill {STREET_FILL:.0f} lm at {fill.get_actor_location()}{check}")


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    tune_lights(actors)
    tune_materials(actors)
    tune_post_and_fog(actors)
    street_fill(actors)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log("saved")


main()
