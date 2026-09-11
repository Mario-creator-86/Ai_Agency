"""
Unreal Engine 5.8 editor script: builds the lighting / composition reference scene for one
office floor from the glTF exported by art-source/blender/export_floor_scene.py.

Creates /Game/Reference/<zone>/ with the imported meshes and a level: an orthographic camera
pitched like the sprite camera, key + fill directional lights, a violet ambient sky light, one
warm point light per ceiling fixture and a fixed-exposure post-process volume. Framing is
measured from the placed meshes, so the importer's unit scale and axis convention are never
assumed. `render_still.py` then takes the still through that camera.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=build_reference_scene.py
  UnrealEditor.exe     AMNReference.uproject -ExecCmds="py render_still.py" -unattended -nosplash

Unreal is a reference tool here; nothing it produces ships in the application.
"""

import json
import math
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
ZONE = os.environ.get("AMN_ZONE", "research")
GLB = os.path.join(HERE, f"{ZONE}_floor.glb")
META = json.load(open(os.path.join(HERE, f"{ZONE}_floor.json"), "r", encoding="utf-8"))
PKG = f"/Game/Reference/{ZONE}"

zone = META["zone"]
W = float(zone["width"])
H = float(zone["height"])
WALL_H = float(META["wall_h"])
FL = float(META["floor_depth_px"])
PITCH = float(META["pitch_deg"])


def log(msg):
    unreal.log(f"AMN_UE {msg}")


def import_glb():
    task = unreal.AssetImportTask()
    task.filename = GLB
    task.destination_path = f"{PKG}/Meshes"
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths = list(task.imported_object_paths)
    log(f"imported {len(paths)} objects from {GLB}")
    return paths


def new_level():
    level_path = f"{PKG}/{ZONE.capitalize()}Floor"
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(level_path):
        # Re-run: reuse the map and empty it, so the scene is rebuilt from scratch.
        if not les.load_level(level_path):
            raise RuntimeError("could not load the existing level")
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        eas.destroy_actors(eas.get_all_level_actors())
        log(f"reusing level {level_path}")
    elif not les.new_level(level_path):
        raise RuntimeError("could not create level")
    return level_path


def spawn(cls, location=(0, 0, 0), rotation=(0, 0, 0), label=None):
    """rotation is (pitch, yaw, roll); unreal.Rotator's positional order is (roll, pitch, yaw)."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    rot = unreal.Rotator(roll=rotation[2], pitch=rotation[0], yaw=rotation[1])
    actor = eas.spawn_actor_from_class(cls, unreal.Vector(*location), rot)
    if label:
        actor.set_actor_label(label)
    return actor


def place_meshes(paths):
    """Transforms are baked into the meshes by the exporter: every mesh sits at the origin."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    count = 0
    for p in paths:
        asset = unreal.load_asset(p)
        if not isinstance(asset, unreal.StaticMesh):
            continue
        actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if actor is None:
            actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, unreal.Vector(0, 0, 0))
        if actor is None:
            continue
        actor.set_actor_label(asset.get_name())
        actor.static_mesh_component.set_static_mesh(asset)
        actor.static_mesh_component.set_mobility(unreal.ComponentMobility.STATIC)
        count += 1
    log(f"placed {count} mesh actors")


class Frame:
    """Where the imported room actually is, measured from the placed actors."""

    def __init__(self):
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.StaticMeshActor)]
        lo = [1e9, 1e9, 1e9]
        hi = [-1e9, -1e9, -1e9]
        wall_c = None
        for a in actors:
            origin, extent = a.get_actor_bounds(False)
            o = [origin.x, origin.y, origin.z]
            e = [extent.x, extent.y, extent.z]
            for i in range(3):
                lo[i] = min(lo[i], o[i] - e[i])
                hi[i] = max(hi[i], o[i] + e[i])
            if a.get_actor_label().startswith("wall_back"):
                wall_c = o
        self.lo, self.hi = lo, hi
        self.size = [hi[i] - lo[i] for i in range(3)]
        self.center = [(lo[i] + hi[i]) / 2 for i in range(3)]
        # Width is the largest horizontal extent; depth is the other horizontal axis.
        self.wa = 0 if self.size[0] >= self.size[1] else 1
        self.da = 1 - self.wa
        wall_d = wall_c[self.da] if wall_c else hi[self.da]
        # The viewer stands on the side opposite the back wall.
        self.toward_wall = 1.0 if wall_d >= self.center[self.da] else -1.0
        self.width = self.size[self.wa]
        self.height = self.size[2]
        if self.da == 0:
            self.yaw = 0.0 if self.toward_wall > 0 else 180.0
        else:
            self.yaw = 90.0 if self.toward_wall > 0 else -90.0
        self.px = self.width / W   # Unreal units per world px
        log(f"frame size=({self.size[0]:.0f},{self.size[1]:.0f},{self.size[2]:.0f}) width_axis={self.wa} "
            f"toward_wall={self.toward_wall:+.0f} yaw={self.yaw:.0f} units/px={self.px:.2f}")

    def point(self, along_width, along_depth, z):
        """Width fraction (0..1 across the room), depth (units, + towards the wall), height."""
        v = list(self.center)
        v[self.wa] = self.lo[self.wa] + along_width * self.width
        v[self.da] = self.center[self.da] + along_depth * self.toward_wall
        v[2] = z
        return unreal.Vector(v[0], v[1], v[2])


def lights(fr):
    # Key light: steep, from the viewer's side, a little from the left (short hard shadows).
    key = spawn(unreal.DirectionalLight, (0, 0, 500), (-68, fr.yaw - 25, 0), "KeySun")
    key.light_component.set_intensity(3.0)
    key.light_component.set_light_color(unreal.LinearColor(1.0, 0.95, 0.88, 1.0))
    fill = spawn(unreal.DirectionalLight, (0, 0, 500), (-20, fr.yaw - 70, 0), "FillLeft")
    fill.light_component.set_intensity(0.8)
    fill.light_component.set_light_color(unreal.LinearColor(0.75, 0.82, 1.0, 1.0))
    fill.light_component.set_cast_shadows(False)
    sky = spawn(unreal.SkyLight, (0, 0, 400), (0, 0, 0), "Ambient")
    sky.light_component.set_intensity(0.25)
    sky.light_component.set_light_color(unreal.LinearColor(0.35, 0.33, 0.55, 1.0))
    # One warm pool per ceiling fixture, the department's lamp colour.
    lamp = META["lamp"].lstrip("#")
    r, g, b = (int(lamp[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    count = int(META["fixtures"])
    for i in range(count):
        pos = fr.point((i + 0.5) / count, 0.0, fr.hi[2] - 6 * fr.px)
        pl = spawn(unreal.PointLight, (pos.x, pos.y, pos.z), (0, 0, 0), f"Fixture{i}")
        pl.point_light_component.set_intensity(1800.0 * fr.px * fr.px)
        pl.point_light_component.set_light_color(unreal.LinearColor(r, g, b, 1.0))
        pl.point_light_component.set_attenuation_radius(220.0 * fr.px)
    log("lights placed")


def camera(fr):
    """Orthographic, pitched like the sprite camera, looking at the back wall from the front."""
    dist = fr.width * 4.0
    target_z = fr.lo[2] + fr.height * 0.5
    pos = fr.point(0.5, -dist * math.cos(math.radians(PITCH)), target_z + dist * math.sin(math.radians(PITCH)))
    cam = spawn(unreal.CameraActor, (pos.x, pos.y, pos.z), (-PITCH, fr.yaw, 0), "PixelCam")
    comp = cam.camera_component
    comp.set_projection_mode(unreal.CameraProjectionMode.ORTHOGRAPHIC)
    comp.set_ortho_width(fr.width * 1.02)
    comp.set_aspect_ratio(W / (H + 2 * FL))
    for prop, val in (("constrain_aspect_ratio", True), ("ortho_near_clip_plane", 1.0), ("ortho_far_clip_plane", dist * 4.0)):
        try:
            comp.set_editor_property(prop, val)
        except Exception as err:  # property names differ between engine versions
            log(f"camera property {prop} skipped: {err}")
    try:
        cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
    except Exception as err:
        log(f"camera auto-activate skipped: {err}")
    log("camera placed")
    return cam


def post_process():
    ppv = spawn(unreal.PostProcessVolume, (0, 0, 0), (0, 0, 0), "Look")
    ppv.unbound = True
    s = ppv.settings
    s.override_auto_exposure_method = True
    s.auto_exposure_method = unreal.AutoExposureMethod.AEM_MANUAL
    s.override_auto_exposure_bias = True
    s.auto_exposure_bias = 1.0
    s.override_bloom_intensity = True
    s.bloom_intensity = 0.25
    s.override_vignette_intensity = True
    s.vignette_intensity = 0.35
    s.override_film_grain_intensity = True
    s.film_grain_intensity = 0.0
    ppv.settings = s
    log("post process placed")


def main():
    paths = import_glb()
    level_path = new_level()
    place_meshes(paths)
    fr = Frame()
    lights(fr)
    camera(fr)
    try:
        post_process()
    except Exception as err:  # the look is optional; the scene must still be saved
        log(f"post process skipped: {err}")
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).save_current_level()
    log(f"level saved {level_path}")
    unreal.EditorAssetLibrary.save_directory(PKG)
    log("done")


main()
