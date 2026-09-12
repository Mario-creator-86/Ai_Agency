"""Render the street's vehicles as sprites seen by the headquarters camera.

  blender -b --factory-startup --python art-source/blender/hq/build_vehicles.py -- --out <dir> [--only bus,taxi]
  python art-source/blender/hq/pack_vehicles.py <dir> frontend/public/assets/hq/vehicles

Each vehicle is rendered driving right and driving left, yawed a little towards the camera like
the reference's three-quarter cars, with a few wheel-turn frames. A second pass renders only the
lamps (the body held out), which the canvas adds on top after dark; emergency vehicles get two
alternating light-bar frames. Advertising panels use textures from make_textures.py.
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hq_lib import COS, MB, PPM, SIN, THETA, emissive, image_material, lin, principled  # noqa: E402

SCALE = 4
YAW = 16.0


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--only", default="")
    p.add_argument("--samples", type=int, default=20)
    return p.parse_args(argv)


def setup(a):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "HIP"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "HIP"
    scene.cycles.device = "GPU"
    scene.cycles.samples = a.samples
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = -0.4
    world = bpy.data.worlds.new("veh_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = lin("#8a92b0")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
    scene.world = world
    cam = bpy.data.objects.new("veh_cam", bpy.data.cameras.new("veh_cam"))
    cam.data.type = "ORTHO"
    cam.data.sensor_fit = "HORIZONTAL"
    scene.collection.objects.link(cam)
    scene.camera = cam
    for name, loc, energy, color, size in (
        ("key", (-4.0, -7.0, 6.0), 1400.0, "#fff1e0", 4.0),
        ("fill", (5.0, -5.0, 2.5), 400.0, "#c9d6ff", 3.0),
        ("rim", (2.0, 6.0, 5.0), 700.0, "#ffd9b0", 3.0),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, lin(color)[:3]
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector((0, 0, 1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)
    return scene


def frame_camera(scene, corners):
    """Fit the camera to the projected corners; return the pivot (ground centre) in world px."""
    def proj(p):
        v = p.y * SIN + p.z * COS
        return (p.x * PPM, -v * PPM)

    pts = [proj(c) for c in corners] + [proj(Vector((0, 0, 0)))]
    x0 = min(p[0] for p in pts) - 4
    x1 = max(p[0] for p in pts) + 4
    y0 = min(p[1] for p in pts) - 4
    y1 = max(p[1] for p in pts) + 4
    w = int(math.ceil(x1 - x0))
    h = int(math.ceil(y1 - y0))
    cam = scene.camera
    cam.data.ortho_scale = w / PPM
    scene.render.resolution_x = w * SCALE
    scene.render.resolution_y = h * SCALE
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    up = Vector((0.0, SIN, COS))
    fwd = Vector((0.0, COS, -SIN))
    centre = Vector((cx / PPM, 0.0, 0.0)) + up * (-cy / PPM)
    cam.location = centre - fwd * 40.0
    cam.rotation_euler = (math.pi / 2 - THETA, 0.0, 0.0)
    return {"w": w, "h": h, "pivot": [round(-x0, 1), round(-y0, 1)]}


# ----------------------------------------------------------------------------- parts


def side_quad(mb, x0, x1, z0, z1, half, m, off=0.006):
    """A panel on both flanks; each reads left to right when that flank faces the camera."""
    y = -half - off
    mb.quad([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], m)
    y = half + off
    mb.quad([(x1, y, z0), (x0, y, z0), (x0, y, z1), (x1, y, z1)], m)


def side_box(mb, x0, x1, z0, z1, half, m, t=0.006):
    mb.box(x0, x1, -half - t, -half, z0, z1, m)
    mb.box(x0, x1, half, half + t, z0, z1, m)

GLASS = None


def mats():
    return {
        "glass": principled("veh_glass", "#16202e", rough=0.05, metal=0.2, coat=1.0),
        "tyre": principled("tyre", "#111114", rough=0.8),
        "rim": principled("rim", "#b8bec8", rough=0.25, metal=0.9),
        "chrome": principled("chrome", "#cfd5dd", rough=0.15, metal=1.0),
        "black": principled("veh_black", "#151619", rough=0.4),
        "head": emissive("headlight", "#fff6de", 14.0),
        "tail": emissive("taillight", "#ff2a2a", 10.0),
        "amber": emissive("indicator", "#ffae2a", 8.0),
        "red_bar": emissive("bar_red", "#ff2a3a", 20.0),
        "blue_bar": emissive("bar_blue", "#2a6bff", 20.0),
        "bar_off": principled("bar_off", "#3a3a44", rough=0.3),
        "taxi_sign": emissive("taxi_sign", "#fff3b0", 6.0),
    }


def wheel(mb, x, y, r, width, m, spin):
    mb.cyl_y(x, y, r, width, r, m["tyre"], seg=20)
    mb.cyl_y(x, y - width * 0.52 * (1 if y < 0 else -1), r, 0.02, r * 0.62, m["rim"], seg=16)
    for k in range(5):
        a = spin + k / 5 * math.tau
        xf = Matrix.Translation((x, y - width * 0.54 * (1 if y < 0 else -1), r)) @ Matrix.Rotation(a, 4, "Y")
        mb.box(-0.02, 0.02, -0.012, 0.012, 0.0, r * 0.58, m["black"], xf)


def car_body(mb, lights, m, paint, length, width, h_body, h_cab, cab_front, cab_back, clearance=0.18, cab_inset=0.12, roof_taper=0.35):
    L, W = length, width
    mb.box(-L / 2, L / 2, -W / 2, W / 2, clearance, clearance + h_body, paint)
    z0 = clearance + h_body
    fx, bx = L / 2 - cab_front, -L / 2 + cab_back
    top = z0 + h_cab
    wi = W / 2 - cab_inset
    pts_near = [(bx, -wi, z0), (fx, -wi, z0), (fx - roof_taper, -wi, top), (bx + roof_taper * 0.5, -wi, top)]
    pts_far = [(x, -y, z) for x, y, z in pts_near]
    mb.quad(pts_near, m["glass"])
    mb.quad(list(reversed(pts_far)), m["glass"])
    mb.quad([(fx, -wi, z0), (fx, wi, z0), (fx - roof_taper, wi, top), (fx - roof_taper, -wi, top)], m["glass"])
    mb.quad([(bx, wi, z0), (bx, -wi, z0), (bx + roof_taper * 0.5, -wi, top), (bx + roof_taper * 0.5, wi, top)], m["glass"])
    mb.box(bx + roof_taper * 0.5, fx - roof_taper, -wi, wi, top - 0.04, top, paint)
    pillar = (bx + fx) / 2
    mb.box(pillar - 0.05, pillar + 0.05, -wi - 0.01, -wi, z0, top, paint)
    lights.box(L / 2 - 0.02, L / 2 + 0.01, -W / 2 + 0.12, -W / 2 + 0.42, z0 - 0.22, z0 - 0.08, m["head"])
    lights.box(L / 2 - 0.02, L / 2 + 0.01, W / 2 - 0.42, W / 2 - 0.12, z0 - 0.22, z0 - 0.08, m["head"])
    lights.box(-L / 2 - 0.01, -L / 2 + 0.02, -W / 2 + 0.1, -W / 2 + 0.38, z0 - 0.2, z0 - 0.07, m["tail"])
    lights.box(-L / 2 - 0.01, -L / 2 + 0.02, W / 2 - 0.38, W / 2 - 0.1, z0 - 0.2, z0 - 0.07, m["tail"])
    mb.box(L / 2 - 0.05, L / 2 + 0.03, -W / 2 + 0.05, W / 2 - 0.05, clearance - 0.02, clearance + 0.1, m["black"])
    mb.box(-L / 2 - 0.03, -L / 2 + 0.05, -W / 2 + 0.05, W / 2 - 0.05, clearance - 0.02, clearance + 0.1, m["black"])
    mb.box(fx - 0.3, fx - 0.18, -W / 2 - 0.12, -W / 2, z0 - 0.02, z0 + 0.1, paint)
    return top


def box_vehicle(mb, lights, m, paint, length, width, height, cab_len, cab_h, clearance=0.35, windows=True):
    L, W = length, width
    mb.box(-L / 2, L / 2 - cab_len, -W / 2, W / 2, clearance, clearance + height, paint)
    mb.box(L / 2 - cab_len, L / 2, -W / 2, W / 2, clearance, clearance + cab_h * 0.55, paint)
    z0 = clearance + cab_h * 0.55
    mb.box(L / 2 - cab_len, L / 2 - 0.35, -W / 2, W / 2, z0, clearance + cab_h, paint)
    mb.quad([(L / 2 - 0.35, -W / 2 + 0.08, z0), (L / 2, -W / 2 + 0.08, z0), (L / 2 - 0.35, -W / 2 + 0.08, clearance + cab_h - 0.05), (L / 2 - 0.35, -W / 2 + 0.08, clearance + cab_h - 0.05)][:3] + [(L / 2 - 0.35, -W / 2 + 0.08, clearance + cab_h - 0.05)], m["glass"])
    side_quad(mb, L / 2 - cab_len + 0.15, L / 2 - 0.4, z0 + 0.05, clearance + cab_h - 0.08, W / 2, m["glass"], off=0.005)
    mb.quad([(L / 2 + 0.005, -W / 2 + 0.1, z0 + 0.05), (L / 2 + 0.005, W / 2 - 0.1, z0 + 0.05), (L / 2 - 0.3, W / 2 - 0.1, clearance + cab_h - 0.06), (L / 2 - 0.3, -W / 2 + 0.1, clearance + cab_h - 0.06)], m["glass"])
    lights.box(L / 2, L / 2 + 0.02, -W / 2 + 0.1, -W / 2 + 0.4, clearance + 0.3, clearance + 0.48, m["head"])
    lights.box(L / 2, L / 2 + 0.02, W / 2 - 0.4, W / 2 - 0.1, clearance + 0.3, clearance + 0.48, m["head"])
    lights.box(-L / 2 - 0.02, -L / 2, -W / 2 + 0.08, -W / 2 + 0.3, clearance + 0.3, clearance + 0.6, m["tail"])
    lights.box(-L / 2 - 0.02, -L / 2, W / 2 - 0.3, W / 2 - 0.08, clearance + 0.3, clearance + 0.6, m["tail"])
    mb.box(-L / 2 - 0.05, L / 2 + 0.05, -W / 2 - 0.02, W / 2 + 0.02, clearance - 0.05, clearance + 0.12, m["black"])


def rider(mb, x, z_seat, m, coat, helmet):
    skin = principled("rider_skin", "#e0ac84", rough=0.55)
    mb.box(x - 0.2, x + 0.2, -0.18, 0.18, z_seat, z_seat + 0.62, coat)
    mb.sphere((x + 0.05, 0.0, z_seat + 0.85), 0.2, skin, seg=14, rings=10)
    mb.sphere((x + 0.03, 0.0, z_seat + 0.9), 0.215, helmet, seg=14, rings=10, scale=(1.0, 1.0, 0.85))
    for sy in (-0.14, 0.14):
        mb.box(x - 0.05, x + 0.45, sy - 0.05, sy + 0.05, z_seat + 0.42, z_seat + 0.52, coat)
        mb.box(x - 0.05, x + 0.3, sy - 0.06, sy + 0.06, z_seat - 0.05, z_seat + 0.08, principled("rider_legs", "#1f2937", rough=0.7))


# ----------------------------------------------------------------------------- catalogue


def build(kind, m, spin):
    body = MB(f"{kind}_body")
    lights = MB(f"{kind}_lights")
    bar = MB(f"{kind}_bar")
    wheels = []
    info = {"kind": kind}
    if kind in ("sedan", "hatchback", "suv", "taxi", "ev", "police", "coupe"):
        spec = {
            "sedan": dict(length=4.6, width=1.82, h_body=0.62, h_cab=0.52, cab_front=1.45, cab_back=1.0, paint="#2f3a4a"),
            "coupe": dict(length=4.4, width=1.8, h_body=0.55, h_cab=0.45, cab_front=1.55, cab_back=1.2, paint="#7a1f24"),
            "hatchback": dict(length=3.95, width=1.75, h_body=0.62, h_cab=0.6, cab_front=1.25, cab_back=0.35, paint="#8a8f98"),
            "suv": dict(length=4.75, width=1.95, h_body=0.85, h_cab=0.62, cab_front=1.25, cab_back=0.45, paint="#3b4250"),
            "taxi": dict(length=4.6, width=1.82, h_body=0.62, h_cab=0.52, cab_front=1.45, cab_back=1.0, paint="#e8b923"),
            "ev": dict(length=4.7, width=1.9, h_body=0.6, h_cab=0.5, cab_front=1.7, cab_back=0.9, paint="#e9edf2"),
            "police": dict(length=4.7, width=1.85, h_body=0.65, h_cab=0.52, cab_front=1.45, cab_back=1.0, paint="#f3f4f6"),
        }[kind]
        paint = principled(f"{kind}_paint", spec.pop("paint"), rough=0.22, metal=0.4, coat=1.0)
        clearance = 0.3 if kind == "suv" else 0.2
        top = car_body(body, lights, m, paint, clearance=clearance, **spec)
        L, W = spec["length"], spec["width"]
        r = 0.36 if kind == "suv" else 0.32
        for wx in (L / 2 - 0.85, -L / 2 + 0.8):
            wheels.append((wx, -W / 2 + 0.05, r))
            wheels.append((wx, W / 2 - 0.05, r))
        if kind == "taxi":
            body.box(-0.35, 0.35, -0.15, 0.15, top, top + 0.22, m["black"])
            lights.box(-0.32, 0.32, -0.16, 0.16, top + 0.02, top + 0.2, m["taxi_sign"])
            side_box(body, -L / 2 + 0.3, L / 2 - 0.3, clearance + 0.25, clearance + 0.33, W / 2, principled("taxi_check", "#151515", rough=0.4), t=0.004)
        if kind == "police":
            side_box(body, -L / 2 + 0.2, L / 2 - 0.2, clearance + 0.12, clearance + 0.42, W / 2, principled("police_blue", "#1d4ed8", rough=0.3), t=0.005)
            body.box(-0.45, 0.45, -0.4, 0.4, top, top + 0.06, m["black"])
            bar.box(-0.43, -0.02, -0.38, 0.38, top + 0.06, top + 0.16, m["blue_bar"])
            bar.box(0.02, 0.43, -0.38, 0.38, top + 0.06, top + 0.16, m["red_bar"])
            info["siren"] = True
        if kind == "ev":
            lights.box(L / 2 - 0.02, L / 2 + 0.01, -W / 2 + 0.1, W / 2 - 0.1, clearance + spec["h_body"] - 0.08, clearance + spec["h_body"] - 0.04, emissive("ev_bar", "#9ff5ff", 10.0))
        info["length"] = L
    elif kind in ("van", "delivery", "ambulance"):
        paint = principled(f"{kind}_paint", {"van": "#4b5563", "delivery": "#f4f4f5", "ambulance": "#f8fafc"}[kind], rough=0.3, metal=0.2, coat=0.6)
        L, W = 5.2, 2.0
        box_vehicle(body, lights, m, paint, L, W, 2.1, 1.3, 1.95, clearance=0.32)
        for wx in (L / 2 - 0.8, -L / 2 + 0.9):
            wheels.append((wx, -W / 2 + 0.05, 0.36))
            wheels.append((wx, W / 2 - 0.05, 0.36))
        if kind == "delivery":
            side_quad(body, -L / 2 + 0.25, L / 2 - 1.5, 0.75, 2.2, W / 2, image_material("ad_delivery", "ad_delivery", 0.35))
        if kind == "ambulance":
            side_box(body, -L / 2, L / 2, 0.9, 1.15, W / 2, principled("amb_red", "#dc2626", rough=0.3), t=0.005)
            side_box(body, -L / 2 + 1.0, -L / 2 + 1.5, 1.35, 1.95, W / 2, principled("amb_cross", "#dc2626", rough=0.3), t=0.006)
            side_box(body, -L / 2 + 0.85, -L / 2 + 1.65, 1.52, 1.78, W / 2, principled("amb_cross", "#dc2626", rough=0.3), t=0.006)
            bar.box(L / 2 - 1.2, L / 2 - 0.85, -0.5, 0.5, 2.45, 2.6, m["red_bar"])
            bar.box(L / 2 - 0.8, L / 2 - 0.45, -0.5, 0.5, 2.45, 2.6, m["blue_bar"])
            info["siren"] = True
        info["length"] = L
    elif kind in ("bus", "bus_amn", "bus_curiosity", "bus_nexus", "truck", "firetruck"):
        if kind.startswith("bus"):
            L, W, H = 12.0, 2.5, 2.9
            livery = {"bus": "#e5e7eb", "bus_amn": "#101a33", "bus_curiosity": "#e5e7eb", "bus_nexus": "#e5e7eb"}[kind]
            paint = principled(f"{kind}_paint", livery, rough=0.45, metal=0.15, coat=0.2)
            body.box(-L / 2, L / 2, -W / 2, W / 2, 0.35, 0.35 + H, paint)
            side_quad(body, -L / 2 + 0.4, L / 2 - 0.3, 1.45, 2.85, W / 2, m["glass"])
            for wx in [(-L / 2 + 0.4) + i * 1.28 for i in range(9)]:
                side_box(body, wx - 0.05, wx + 0.05, 1.45, 2.85, W / 2 + 0.006, paint)
            side_box(body, L / 2 - 1.6, L / 2 - 0.6, 0.45, 2.85, W / 2 + 0.006, m["glass"])
            body.quad([(L / 2 + 0.005, -W / 2 + 0.1, 1.2), (L / 2 + 0.005, W / 2 - 0.1, 1.2), (L / 2 + 0.005, W / 2 - 0.1, 2.9), (L / 2 + 0.005, -W / 2 + 0.1, 2.9)], m["glass"])
            ad = {"bus": "ad_city", "bus_amn": "ad_amn_ai", "bus_curiosity": "ad_nexus_curiosity", "bus_nexus": "ad_inside_the_nexus"}[kind]
            side_quad(body, -L / 2 + 0.6, L / 2 - 2.0, 0.55, 1.35, W / 2, image_material(f"{kind}_ad", ad, 0.5), off=0.008)
            if kind == "bus_amn":
                side_box(body, -L / 2, L / 2, 1.36, 1.44, W / 2, emissive("amn_stripe", "#2dd4bf", 3.0), t=0.004)
            lights.box(L / 2, L / 2 + 0.02, -W / 2 + 0.15, -W / 2 + 0.45, 0.6, 0.8, m["head"])
            lights.box(L / 2, L / 2 + 0.02, W / 2 - 0.45, W / 2 - 0.15, 0.6, 0.8, m["head"])
            lights.box(-L / 2 - 0.02, -L / 2, -W / 2 + 0.1, -W / 2 + 0.3, 0.6, 1.1, m["tail"])
            lights.box(-L / 2 - 0.02, -L / 2, W / 2 - 0.3, W / 2 - 0.1, 0.6, 1.1, m["tail"])
            lights.box(L / 2 - 0.02, L / 2 + 0.01, -0.9, 0.9, 2.95, 3.15, emissive("bus_route", "#ffb020", 5.0))
            for wx in (L / 2 - 2.2, -L / 2 + 2.6):
                wheels.append((wx, -W / 2 + 0.1, 0.5))
                wheels.append((wx, W / 2 - 0.1, 0.5))
        else:
            L, W = (9.0, 2.5) if kind == "truck" else (9.5, 2.5)
            paint = principled(f"{kind}_paint", "#3f5a7a" if kind == "truck" else "#b91c1c", rough=0.3, metal=0.3, coat=0.8)
            box_vehicle(body, lights, m, paint, L, W, 2.8, 2.2, 2.4, clearance=0.45)
            if kind == "truck":
                side_quad(body, -L / 2 + 0.3, L / 2 - 2.5, 0.9, 3.0, W / 2, image_material("truck_side", "ad_logistics", 0.35))
            else:
                for i in range(12):
                    xx = -L / 2 + 0.5 + i * 0.55
                    body.box(xx, xx + 0.06, -0.6, 0.6, 3.3, 3.45, m["chrome"])
                body.box(-L / 2 + 0.4, L / 2 - 2.6, -0.62, -0.56, 3.3, 3.34, m["chrome"])
                body.box(-L / 2 + 0.4, L / 2 - 2.6, 0.56, 0.62, 3.3, 3.34, m["chrome"])
                side_box(body, -L / 2, L / 2, 1.5, 1.65, W / 2, principled("fire_stripe", "#f5f5f4", rough=0.3), t=0.005)
                bar.box(L / 2 - 1.9, L / 2 - 1.2, -0.6, 0.6, 2.7, 2.85, m["red_bar"])
                bar.box(L / 2 - 1.1, L / 2 - 0.4, -0.6, 0.6, 2.7, 2.85, m["blue_bar"])
                info["siren"] = True
            for wx in (L / 2 - 1.2, -L / 2 + 1.6, -L / 2 + 2.9):
                wheels.append((wx, -W / 2 + 0.1, 0.5))
                wheels.append((wx, W / 2 - 0.1, 0.5))
        info["length"] = L
    elif kind in ("motorcycle", "scooter", "bicycle"):
        frame = principled(f"{kind}_frame", {"motorcycle": "#1f2937", "scooter": "#0ea5e9", "bicycle": "#16a34a"}[kind], rough=0.3, metal=0.5)
        r = {"motorcycle": 0.33, "scooter": 0.22, "bicycle": 0.34}[kind]
        L = {"motorcycle": 2.1, "scooter": 1.6, "bicycle": 1.75}[kind]
        wheels.append((L / 2 - r, 0.0, r))
        wheels.append((-L / 2 + r, 0.0, r))
        if kind == "bicycle":
            for p0, p1 in (((-L / 2 + r, r), (0.0, r + 0.45)), ((0.0, r + 0.45), (L / 2 - r, r)), ((-L / 2 + r, r), (0.1, r)), ((0.1, r), (0.0, r + 0.45))):
                body.box(min(p0[0], p1[0]), max(p0[0], p1[0]) + 0.04, -0.03, 0.03, min(p0[1], p1[1]), max(p0[1], p1[1]) + 0.04, frame)
        else:
            body.box(-L / 2 + r, L / 2 - r, -0.16, 0.16, r, r + 0.35, frame)
            body.box(-0.2, 0.35, -0.18, 0.18, r + 0.35, r + 0.45, m["black"])
        body.box(L / 2 - r - 0.05, L / 2 - r + 0.05, -0.3, 0.3, r + 0.7, r + 0.75, m["chrome"])
        rider(body, -0.1, r + 0.45, m, principled(f"{kind}_coat", {"motorcycle": "#111827", "scooter": "#f59e0b", "bicycle": "#ef4444"}[kind], rough=0.7), principled(f"{kind}_helmet", {"motorcycle": "#dc2626", "scooter": "#f8fafc", "bicycle": "#22c55e"}[kind], rough=0.2, coat=1.0))
        if kind != "bicycle":
            lights.box(L / 2 - r + 0.05, L / 2 - r + 0.12, -0.08, 0.08, r + 0.55, r + 0.7, m["head"])
            lights.box(-L / 2 + r - 0.12, -L / 2 + r - 0.05, -0.06, 0.06, r + 0.4, r + 0.5, m["tail"])
        info["length"] = L
        info["two_wheeler"] = True
    wheel_mb = MB(f"{kind}_wheels")
    for wx, wy, r in wheels:
        wheel(wheel_mb, wx, wy, r, 0.26 if not info.get("two_wheeler") else 0.1, m, spin)
    return body, lights, bar, wheel_mb, info


KINDS = [
    "sedan", "coupe", "hatchback", "suv", "taxi", "ev", "police", "van", "delivery", "ambulance",
    "bus", "bus_amn", "bus_curiosity", "bus_nexus", "truck", "firetruck", "motorcycle", "scooter", "bicycle",
]


def main():
    a = args()
    scene = setup(a)
    m = mats()
    only = {s for s in a.only.split(",") if s}
    os.makedirs(a.out, exist_ok=True)
    catalogue = {"scale": SCALE, "vehicles": {}}
    for kind in KINDS:
        if only and kind not in only:
            continue
        entry = None
        for direction, yaw in (("right", -YAW), ("left", 180.0 + YAW)):
            for spin_i in range(3):
                coll = bpy.data.collections.new(f"{kind}_{direction}_{spin_i}")
                scene.collection.children.link(coll)
                body, lights, bar, wheels, info = build(kind, m, spin_i / 3 * (math.tau / 5))
                obs = [body.build(coll, bevel=0.03), lights.build(coll), bar.build(coll), wheels.build(coll, smooth=True)]
                rot = Matrix.Rotation(math.radians(yaw), 4, "Z")
                corners = []
                for ob in obs:
                    ob.matrix_world = rot
                    corners += [rot @ Vector(c) for c in ob.bound_box]
                frame = frame_camera(scene, corners)
                base = f"{kind}__{direction}__{spin_i}"
                for ob in obs:
                    ob.is_holdout = False
                scene.render.filepath = os.path.join(a.out, base + ".png")
                bpy.ops.render.render(write_still=True)
                if spin_i == 0:
                    # lamps only: the body is held out so a lamp behind the body stays hidden
                    obs[0].is_holdout = True
                    obs[3].is_holdout = True
                    obs[2].hide_render = True
                    scene.render.filepath = os.path.join(a.out, f"{kind}__{direction}__lights.png")
                    bpy.ops.render.render(write_still=True)
                    if info.get("siren"):
                        obs[1].hide_render = True
                        obs[2].hide_render = False
                        for phase, (mat_a, mat_b) in enumerate(((m["red_bar"], m["blue_bar"]), (m["blue_bar"], m["red_bar"]))):
                            scene.render.filepath = os.path.join(a.out, f"{kind}__{direction}__siren{phase}.png")
                            swap = {m["red_bar"].name: mat_a, m["blue_bar"].name: mat_b}
                            me = obs[2].data
                            originals = list(me.materials)
                            for idx, mt in enumerate(originals):
                                me.materials[idx] = swap.get(mt.name, mt)
                            bpy.ops.render.render(write_still=True)
                            for idx, mt in enumerate(originals):
                                me.materials[idx] = mt
                    entry = entry or {"length_m": info.get("length"), "siren": bool(info.get("siren")), "two_wheeler": bool(info.get("two_wheeler")), "frames": {}}
                    entry["frames"][direction] = {"w": frame["w"], "h": frame["h"], "pivot": frame["pivot"]}
                for ob in list(coll.all_objects):
                    bpy.data.objects.remove(ob, do_unlink=True)
                bpy.data.collections.remove(coll)
        catalogue["vehicles"][kind] = entry
        print(f"AMN_VEHICLE {kind}")
    with open(os.path.join(a.out, "vehicles.json"), "w", encoding="utf-8") as fh:
        json.dump(catalogue, fh, indent=1)


main()
