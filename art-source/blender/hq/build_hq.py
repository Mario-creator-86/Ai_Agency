"""Build and render the AMN-AI headquarters plates.

  blender -b --factory-startup --python art-source/blender/hq/build_hq.py -- \
      --out frontend/public/assets/hq --scale 2 --samples 192 --variant night --layers all
  blender ... -- --preview --out <dir> --scale 1 --samples 48     (one flattened image for review)

Layers (drawn by the canvas in this order, live actors in between):
  city            skyline, bridge, billboard, side buildings
  street_back     tree trunks and crowns
  street_ground   terrace, pavement, road
  building_back   rooms, furniture, shaft          -> seated agents are drawn after this
  building_front  the lit consoles in front of the seats
  building_shell  frame, slabs, labels, sign, glass
  street_props    lamps, planters, bench, shelter  -> pedestrians are drawn after this
  street_kerb     bollards                         -> vehicles are drawn after this
  street_front    near planters
Every layer is rendered with the other layers present but invisible to the camera, so light,
shadow and reflections are those of the whole scene.

--variant day is the same building on a clear Bucharest noon: hq_day.py sets its world and sun and
turns the built night scene into the day one. The night path does not call it.
"""

import argparse
import json
import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hq_building  # noqa: E402
import hq_city  # noqa: E402
import hq_day  # noqa: E402  (the day variant only: world, sun and the noon pass)
from hq_lib import CX, CY, PPM, SIN, COS, THETA, WORLD_H, WORLD_W, ZC, collection, lin  # noqa: E402

LAYERS = [
    "city",
    "street_back",
    "street_ground",
    "building_back",
    "building_front",
    "building_shell",
    "street_props",
    "street_kerb",
    "street_front",
]
LIGHT_COLLECTIONS = ["lights_interior", "lights_exterior"]


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--samples", type=int, default=48)
    p.add_argument("--variant", default="night", choices=["night", "day"])
    p.add_argument("--layers", default="all")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--blend", default="")
    p.add_argument("--look", default="AgX - Base Contrast")
    p.add_argument("--exposure", type=float, default=0.2)
    p.add_argument("--name", default="")
    return p.parse_args(argv)


def setup_render(scene, a):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "HIP"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "HIP"
    scene.cycles.device = "GPU"
    scene.cycles.samples = a.samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 3
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.cycles.sample_clamp_indirect = 8.0
    scene.cycles.blur_glossy = 1.0
    scene.render.resolution_x = int(WORLD_W * a.scale)
    scene.render.resolution_y = int(WORLD_H * a.scale)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = not a.preview
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = a.look
    except TypeError:
        pass
    scene.view_settings.exposure = a.exposure
    print("AMN_LOOK", scene.view_settings.view_transform, scene.view_settings.look)


def setup_camera(scene):
    cam_data = bpy.data.cameras.new("hq_camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = WORLD_W / PPM
    cam_data.clip_start = 1.0
    cam_data.clip_end = 600.0
    cam = bpy.data.objects.new("hq_camera", cam_data)
    scene.collection.objects.link(cam)
    dist = 250.0
    cam.location = (0.0, -dist * COS, ZC + dist * SIN)
    cam.rotation_euler = (math.pi / 2 - THETA, 0.0, 0.0)
    scene.camera = cam


def setup_world(scene, variant, preview):
    if variant == "day":
        hq_day.world(scene, preview)
        return
    w = bpy.data.worlds.new("hq_world")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    ambient = nt.nodes.new("ShaderNodeBackground")
    ambient.inputs["Color"].default_value = lin("#3b4c80")
    ambient.inputs["Strength"].default_value = 1.1
    if preview:
        sky = nt.nodes.new("ShaderNodeBackground")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        els = ramp.color_ramp.elements
        els[0].position = 0.0
        els[0].color = lin("#3a3450")
        els[1].position = 1.0
        els[1].color = lin("#1f2a48")
        for pos, col in ((0.45, "#6a5a74"), (0.6, "#a0706e"), (0.75, "#3a4570")):
            els.new(pos).color = lin(col)
        nt.links.new(tc.outputs["Window"], sep.inputs[0])
        nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], sky.inputs["Color"])
        lp = nt.nodes.new("ShaderNodeLightPath")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
        nt.links.new(ambient.outputs["Background"], mix.inputs[1])
        nt.links.new(sky.outputs["Background"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    else:
        nt.links.new(ambient.outputs["Background"], out.inputs["Surface"])
    scene.world = w


def setup_sun(colls, variant):
    coll = colls["lights_exterior"]
    def sun(name, color, strength, rot, angle=5.0):
        ld = bpy.data.lights.new(name, "SUN")
        ld.color = lin(color)[:3]
        ld.energy = strength
        ld.angle = math.radians(angle)
        ob = bpy.data.objects.new(name, ld)
        ob.rotation_euler = rot
        coll.objects.link(ob)
    if variant == "day":
        hq_day.sun(colls)
        return
    sun("dusk_glow", "#ff9f86", 1.2, (math.radians(80), 0, math.radians(-35)), angle=10)
    sun("moon", "#9fb2ff", 0.6, (math.radians(35), 0, math.radians(25)), angle=3)


def main():
    a = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    setup_render(scene, a)
    setup_camera(scene)
    setup_world(scene, a.variant, a.preview)
    colls = {name: collection(name) for name in LAYERS + LIGHT_COLLECTIONS}
    setup_sun(colls, a.variant)
    t0 = time.time()
    anchors = hq_building.build(colls)
    street = hq_city.build(colls)
    for ob in colls["lights_interior"].objects:
        ob.data.energy *= 3.15
    if a.variant == "day":
        hq_day.apply(colls)
    print(f"AMN_BUILD seconds={time.time() - t0:.1f} objects={len(bpy.data.objects)}")
    os.makedirs(a.out, exist_ok=True)
    manifest = {
        "world": {"width": WORLD_W, "height": WORLD_H},
        "camera": {"pixels_per_metre": PPM, "pitch_degrees": math.degrees(THETA)},
        "scale": a.scale,
        "layers": LAYERS,
        **anchors,
        "street": street,
    }
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    if a.blend:
        bpy.ops.wm.save_as_mainfile(filepath=a.blend)
    if a.preview:
        scene.render.filepath = os.path.join(a.out, a.name or f"preview_{a.variant}.png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"AMN_RENDER preview seconds={time.time() - t1:.1f}")
        return
    wanted = LAYERS if a.layers == "all" else a.layers.split(",")
    base = scene.view_layers[0]
    for layer in wanted:
        for child in base.layer_collection.children:
            name = child.name
            if name in LIGHT_COLLECTIONS:
                child.exclude = False
                child.indirect_only = False
                continue
            child.exclude = False
            child.indirect_only = name != layer
        scene.render.filepath = os.path.join(a.out, f"{a.variant}_{layer}.png")
        t1 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"AMN_RENDER layer={layer} seconds={time.time() - t1:.1f}")


main()
