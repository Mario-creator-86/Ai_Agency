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
# L2 at 0.6 (0.7 before): its region 19.1 -> 17.9, mean 11.9 -> 11.7 (2026-09-15); its lower rows now read
# like the picture's, only the band under its ceiling (the line and the pendants) stays brighter
LEVEL_GAIN = {int(k): float(v) for k, v in (pair.split(":") for pair in os.environ.get("AMN_LEVEL_GAIN", "0:0.55,1:0.7,2:0.6,3:0.3,4:0.8").split(",") if ":" in pair)}
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
# the lobby's fills and spill, on top of FILL: at 0.75 the ground floor's region still read 81 against
# the picture's 66 (colour distance 25.7 once the S1 LEDs were lit); at 0.55 25.7 -> 18.8, mean 14.4 -> 13.7;
# at 0.4 18.8 -> 12.7 and the street 15.4 -> 11.5 (the lobby's spill had lit the pavement too), mean 12.8;
# at 0.3 the ground region 8.3, mean 12.6. Lower is not worth it: the floor's lower rows already read a
# little darker than the picture, only its upper rows brighter.
LOBBY = env("AMN_LOOK_LOBBY", "0.3")
LAMP = env("AMN_LOOK_LAMP", "0.5")           # street lamps: at full they burnt white pools on the road
UPLIGHT = env("AMN_LOOK_UPLIGHT", "0.3")     # tree uplights (the leafy crowns read too bright at 0.6)
# the small warm lights under each office ceiling (hq_building.ceiling_cove): at 1.0 the rooms read too
# bright (mean 15.7; L2 88 against the picture's 79), at 0.35 the closest pass so far (14.5)
COVE = env("AMN_LOOK_COVE", "0.35")
HEADLIGHT_LM = env("AMN_LOOK_HEADLIGHT_LM", "900")
TAILLIGHT_LM = env("AMN_LOOK_TAILLIGHT_LM", "160")
CITY = env("AMN_LOOK_CITY", "0.5")           # skyline window emission, on the imported value
# The skyline's windows are the export's tiling window textures, one window per 0.16-0.28 m cell:
# about 6 x 9 px in the live frame, where the picture's towers have windows of 2-3 px. The texture
# scale on the facade materials (glTF OffsetScale): 2 halves each window; 1 leaves the export's size.
# At 2 the towers read finer by eye, but the frame moved away from the picture (mean 14.7 -> 14.9, the
# city right of the building 11.9 -> 14.1), so the export's size stays.
CITY_WINDOW_SCALE = env("AMN_LOOK_CITY_WINDOW_SCALE", "1")
# The warm LED strips under each floor's ceiling and along the frame (edge_led_slab, edge_led_warm,
# edge_led): in the picture a bright band that washes the top of each room's wall, live a thin line.
# A factor on their imported emission strength (recorded once in look_baseline.json); 1 leaves them.
# At 3 the top floor's strip reads brighter and L4 came closer to the picture (7.8 -> 5.5; the roof
# sign 9.1 -> 10.2, the mean unchanged at 14.7). L3 and L2 have no ceiling strip in the scene at all:
# those are for the Blender scene, not this factor. Since hq_building.ceiling_cove() hangs a line of
# the same material under every office ceiling, 3 made those lines burn (129 and 103 against the
# picture's 64 and 62 in their rows); at 1.5 the mean is 14.1 (14.5 at 3), at 1 (the imported
# strength) 13.9, the closest: roof sign 11.8, L4 1.4, L1 9.2.
STRIP_MATERIALS = ("edge_led_slab", "edge_led_warm", "edge_led")
STRIP_GAIN = env("AMN_LOOK_STRIP_GAIN", "1")
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
# ...so the frame gets its own light: a wide, cool area light in front of the building facing it, on
# lighting channel 1, which only the "shell" actor (frame, stone, plinth, glass, roof; the rooms and
# their props are other actors) also receives. Lumens; 0 turns it off. Compared in the stream (mean
# colour distance, 15.0 without): 20,000 lm over the whole front 39.6 (a white frame); 3,000 lm 20.5
# (slate grey); 800 lm 15.4 (the upper floors closer, the ground floor and lift tower too bright);
# 800 lm held to the floors above the ground floor (below) 14.6, a dark navy frame like the picture's.
FACADE = env("AMN_LOOK_FACADE", "800")
FACADE_Y = env("AMN_LOOK_FACADE_Y", "-10")  # Blender metres in front of the building's front (y 0)
FACADE_ACTOR = "shell"
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
    if name.startswith("cove_wash"):
        return COVE
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
            if base_name in STRIP_MATERIALS and "EmissiveStrength" in scalars:
                if path not in base:
                    base[path] = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
                mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", base[path] * STRIP_GAIN)
                mel.update_material_instance(mat)
                log(f"strip {path.rsplit('.', 1)[-1]}: emission {base[path]:.2f} x{STRIP_GAIN:g}")
            if label in ("skyline", "near_blocks") and "EmissiveStrength" in scalars:
                if path not in base:
                    base[path] = mel.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
                mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", base[path] * CITY)
                if label == "skyline":
                    scale = unreal.LinearColor(0.0, 0.0, CITY_WINDOW_SCALE, CITY_WINDOW_SCALE)
                    for slot in ("BaseColorTexture", "EmissiveTexture"):
                        mel.set_material_instance_vector_parameter_value(mat, f"{slot}_OffsetScale", scale)
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


def facade_light(actors):
    """A wide area light in front of the building (Blender y FACADE_Y), facing it, cool like the dusk,
    without shadows, on lighting channel 1 only; the shell actor receives channels 0 and 1, every other
    actor channel 0 only, so the rooms behind the open front stay as they are. Facing the building
    (yaw -90), the light's width runs along the building and its height up it."""
    light = actors.get("FacadeLight")
    if light is None and FACADE <= 0:
        return
    top_m = CEILINGS_M[-1] + 4.0  # the roof's parapet and sign above the top floor
    # At 800 lm over the whole front the upper floors came closer to the picture (L4 10.2 -> 8.3,
    # the roof sign 12.7 -> 9.0) but the ground floor (21.3 -> 26.5) and the lift tower (11.1 -> 16.9)
    # took too much: the light's bottom edge (m), centre and width, and its barn doors, keep it on the
    # floors above the ground floor.
    bottom_m = env("AMN_LOOK_FACADE_BOTTOM", "5.2")      # just above the ground floor's ceiling (4.9 m)
    centre_x = env("AMN_LOOK_FACADE_X", "0.4")           # the main block, without the lift tower
    width_cm = env("AMN_LOOK_FACADE_WIDTH", "2850")
    where = ue(centre_x, FACADE_Y, (top_m + bottom_m) / 2.0)
    facing = unreal.Rotator(roll=0.0, pitch=0.0, yaw=-90.0)
    if light is None:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        light = eas.spawn_actor_from_class(unreal.RectLight, where, facing)
        light.set_actor_label("FacadeLight")
    light.set_actor_location_and_rotation(where, facing, False, False)
    comp = light.rect_light_component
    comp.set_mobility(unreal.ComponentMobility.MOVABLE)
    comp.set_intensity_units(unreal.LightUnits.LUMENS)
    comp.set_intensity(max(FACADE, 0.0))
    comp.set_light_color(unreal.LinearColor(0.72, 0.78, 1.0, 1.0))
    comp.set_editor_property("source_width", width_cm)
    comp.set_editor_property("source_height", (top_m - bottom_m) * 100.0)
    # the doors are planes along the light's edges: at 90 degrees they lie flat (no effect), at 0 they
    # stand straight out, and their length (cm) sets how far they hold the light to its own outline
    barn_angle = env("AMN_LOOK_FACADE_BARN_ANGLE", "5")
    barn_length = env("AMN_LOOK_FACADE_BARN_LENGTH", "1000")
    comp.set_editor_property("barn_door_angle", barn_angle)
    comp.set_editor_property("barn_door_length", barn_length)
    comp.set_attenuation_radius(3000.0)
    comp.set_cast_shadows(False)
    comp.set_editor_property("lighting_channels", unreal.LightingChannels(channel0=False, channel1=True, channel2=False))
    shell = actors.get(FACADE_ACTOR)
    if shell is not None:
        shell.static_mesh_component.set_editor_property("lighting_channels", unreal.LightingChannels(channel0=True, channel1=True, channel2=False))
    log(f"facade light {FACADE:.0f} lm at y {FACADE_Y} m, x {centre_x} m, {width_cm / 100.0:.1f} m wide, from {bottom_m} to {top_m:.1f} m, "
        f"barn doors {barn_angle:g} deg x {barn_length:g} cm, on channel 1 with {'the shell' if shell else 'NO shell actor'}")


# The rooms' windows onto the city (the Blender scene's image materials window_view and
# window_view_b) rendered as flat mauve panels: the export bakes them into the shared "props" atlas,
# where each window gets a few texels, the average of its dusk image. Their own images go back on
# them, on the model's own UVs (every face of the scene's meshes spans 0-1), with this emission
# strength; 0 leaves the baked atlas. At 1.5 (with the facade light) the windows show dark towers with
# lit windows against the dusk, and the rooms' regions came closer to the picture (mean 14.6).
WINDOW_VIEWS = {"window_view": "window_city", "window_view_b": "window_city_b"}
WINDOW_VIEW_DIR = os.path.join(os.path.dirname(HERE), "blender", "hq", "textures")
WINDOW_VIEW_STRENGTH = env("AMN_LOOK_WINDOW_VIEW", "1.5")


def window_views(actors):
    if WINDOW_VIEW_STRENGTH <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    textures = {}
    for image in set(WINDOW_VIEWS.values()):
        path = f"/Game/HQ/Materials/T_HQ_{image}"
        if not unreal.EditorAssetLibrary.does_asset_exist(path):
            task = unreal.AssetImportTask()
            task.filename = os.path.join(WINDOW_VIEW_DIR, f"{image}.png")
            task.destination_path = "/Game/HQ/Materials"
            task.destination_name = f"T_HQ_{image}"
            task.automated = True
            task.replace_existing = True
            task.save = True
            unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        textures[image] = unreal.load_asset(path)
    done = set()
    for actor in actors.values():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant) or mat.get_path_name() in done:
                continue
            base_name = mat.get_name().lower().rstrip("0123456789").rstrip("_")
            tex = textures.get(WINDOW_VIEWS.get(base_name, ""))
            if tex is None:
                continue
            for slot in ("BaseColorTexture", "EmissiveTexture"):
                mel.set_material_instance_texture_parameter_value(mat, slot, tex)
                mel.set_material_instance_scalar_parameter_value(mat, f"{slot}_TexCoord", 0.0)
            mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", WINDOW_VIEW_STRENGTH)
            mel.update_material_instance(mat)
            done.add(mat.get_path_name())
    log(f"room windows: city images at emission {WINDOW_VIEW_STRENGTH} on {len(done)} materials {sorted(p.rsplit('/', 1)[-1] for p in done)}")


# The small lights (server LEDs, the rack bars, the PCs' and speakers' LEDs, the infra room's bars
# and grid) are baked with the rest of "glow_details" into one shared emission texture, where an LED
# of a few millimetres is averaged away: the picture's server racks show rows of green lights, the
# live ones stood black. Each gets its own colour (the Blender scene's, hq_building.py) on a white
# texture, at the scene's strength times this gain; 0 leaves the bake.
# At the scene's strengths (gain 1) the rack tops and the infra room's grid glowed, but the LED dots
# did not show: each is 3 x 3 cm, under one pixel in the live frame, and anti-aliasing averages it
# away. The dots take LED_DOT_BOOST times their strength, so bloom makes a visible point of each; the
# grid and bars (lines, visible already, stronger than the picture's) take a share. The dots still
# did not show at any size or strength until the cause was found: Nanite dropped their small separate
# boxes (nanite_hq_live.py turns it off on the small lights' mesh). Since then the racks show rows of
# green and amber dots like the picture's; the grid's lines at 0.5 read stronger than the picture's and
# hid the "I" of the S1 INFRA sign in their glow, at 0.15 the sign reads whole.
LED_DOT_BOOST = env("AMN_LOOK_LED_DOT_BOOST", "8")
LED_LINE_SHARE = env("AMN_LOOK_LED_LINE_SHARE", "0.15")
LEDS = {
    "rack_led_green": ("#4ade80", 6.0 * LED_DOT_BOOST), "rack_led_amber": ("#fbbf24", 5.0 * LED_DOT_BOOST),
    "pc_led_blue": ("#60a5fa", 8.0 * LED_DOT_BOOST), "spk_led": ("#93c5fd", 5.0 * LED_DOT_BOOST),
    "rack_top_bar": ("#34d399", 3.0), "infra_bar": ("#a5f3fc", 5.0 * LED_LINE_SHARE),
    "infra_grid": ("#2dd4bf", 0.6 * LED_LINE_SHARE),
}
LED_GAIN = env("AMN_LOOK_LED_GAIN", "1")
WHITE = "/InterchangeAssets/gltf/Textures/T_White_srgb"


def linear(hex_color):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    return [channel(int(h[i:i + 2], 16)) for i in (0, 2, 4)]


def small_lights(actors):
    if LED_GAIN <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    white = unreal.load_asset(WHITE)
    done = set()
    for actor in actors.values():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant) or mat.get_path_name() in done:
                continue
            spec = LEDS.get(mat.get_name().lower().rstrip("0123456789").rstrip("_"))
            if spec is None:
                continue
            r, g, b = linear(spec[0])
            mel.set_material_instance_texture_parameter_value(mat, "EmissiveTexture", white)
            mel.set_material_instance_texture_parameter_value(mat, "BaseColorTexture", white)
            mel.set_material_instance_vector_parameter_value(mat, "EmissiveFactor", unreal.LinearColor(r, g, b, 1.0))
            mel.set_material_instance_vector_parameter_value(mat, "BaseColorFactor", unreal.LinearColor(r, g, b, 1.0))
            mel.set_material_instance_scalar_parameter_value(mat, "EmissiveStrength", spec[1] * LED_GAIN)
            mel.update_material_instance(mat)
            done.add(mat.get_path_name())
    log(f"small lights: own colours at x{LED_GAIN} of the scene's strength on {len(done)} materials")


# The rooms' plants of 0.9 m and taller are the restaurant scene's potted frond (dress_hq_live.py
# BIG_PLANT), and they render as dark silhouettes where the picture's plants are a lit green: the pack
# keeps the frond's colour at 0.143 (BaseColorMultiply) and relies on subsurface light in its own,
# brightly lit restaurant. A child instance under /Game/HQ (the pack's own stays untouched) with this
# colour factor goes on the frond slot of every plant placed from that mesh; 0 leaves the pack's.
# At 0.6 (15 plants) the fronds read a lighter green by eye and the mean held (14.0 against 13.9);
# they stay thinner than the picture's bushy plants, which is the model's shape, not its colour.
PLANT_MESH = "/Game/RestaurantScene/Meshes/SM_PlantPot"
PLANT_MI = "/Game/HQ/Materials/MI_HQ_PlantFrond"
PLANT_FROND = env("AMN_LOOK_PLANT_FROND", "0.6")


def plant_fronds(actors):
    if PLANT_FROND <= 0:
        return
    mel = unreal.MaterialEditingLibrary
    mesh = unreal.load_asset(PLANT_MESH)
    if mesh is None:
        log(f"plant fronds: {PLANT_MESH} missing")
        return
    parent = mesh.static_materials[0].material_interface
    if unreal.EditorAssetLibrary.does_asset_exist(PLANT_MI):
        mi = unreal.load_asset(PLANT_MI)
    else:
        folder, name = PLANT_MI.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    mel.set_material_instance_scalar_parameter_value(mi, "BaseColorMultiply", PLANT_FROND)
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    placed = 0
    for actor in actors.values():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        current = comp.get_editor_property("static_mesh")
        if current is not None and current.get_path_name() == mesh.get_path_name():
            comp.set_material(0, mi)
            placed += 1
    log(f"plant fronds: colour x{PLANT_FROND:g} (the pack's 0.143) on {placed} plants, parent {parent.get_name() if parent else None}")


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
    facade_light(actors)
    window_views(actors)
    small_lights(actors)
    plant_fronds(actors)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log("saved")


main()
