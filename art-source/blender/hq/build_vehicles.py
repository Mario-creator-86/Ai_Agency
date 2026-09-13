"""Render the street's vehicles as sprites seen by the headquarters camera.

  blender -b --factory-startup --python art-source/blender/hq/build_vehicles.py -- --out <dir> [--only bus,taxi]
  python art-source/blender/hq/pack_vehicles.py <dir> frontend/public/assets/hq/vehicles

Each vehicle is rendered driving right and driving left, yawed a little towards the camera like
the reference's three-quarter cars, with a few wheel-turn frames. A second pass renders only the
lamps (the body held out), which the canvas adds on top after dark; emergency vehicles get two
alternating light-bar frames. Cars are lofted from side profiles (PROFILES); the catalogue records
where each visible head and tail lamp sits so the canvas can bloom them. Advertising panels use
textures from make_textures.py.
"""

import argparse
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
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
        ("rim", (2.0, 6.0, 5.0), 700.0, "#ffd9b0", 6.0),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, lin(color)[:3]
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector((0, 0, 1)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        # key and fill shape the body but stay out of reflections: their mirror-bright squares on
        # windows and bonnets read as white paint, where the reference reflects a dusk sky. Only
        # the broad rim light behind the car leaves a soft sheen.
        ob.visible_glossy = name == "rim"
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


def side_strip(mb, x0, x1, z0, z1, hw, m, t=0.004, n=12):
    """A band on both flanks that follows a body whose width changes along its length."""
    for i in range(n):
        a = x0 + (x1 - x0) * i / n
        b = x0 + (x1 - x0) * (i + 1) / n
        side_box(mb, a, b, z0, z1, hw((a + b) / 2), m, t=t)


def lamp_anchors(ob, rot, frame, path):
    """Where the head and tail lamps that the lamp pass actually shows sit in the frame, in world px.

    The lamp mesh is made of boxes (eight vertices each); a lamp counts when the rendered lamp
    image is lit around its projected centre, so a lamp hidden behind the body is left out.
    """
    out = {"head": [], "tail": []}
    me = ob.data
    if not len(me.vertices) or not len(me.materials):
        return out
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    kinds = {}
    for poly in me.polygons:
        kinds[poly.vertices[0] // 8] = me.materials[poly.material_index].name
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    bpy.data.images.remove(img)
    for box, name in sorted(kinds.items()):
        cls = "head" if name.startswith("headlight") else "tail" if name.startswith("taillight") else None
        if not cls:
            continue
        p = rot @ Vector(co[box * 8 : box * 8 + 8].mean(axis=0))
        fx = p.x * PPM + frame["pivot"][0]
        fy = -(p.y * SIN + p.z * COS) * PPM + frame["pivot"][1]
        ix, iy, rad = int(fx * SCALE), int(fy * SCALE), 3 * SCALE
        win = px[max(0, h - 1 - iy - rad) : max(0, h - iy + rad), max(0, ix - rad) : max(0, ix + rad)]
        # a lamp and its wrap-round seen at the same spot bloom once
        if win.size and float(win[..., 3].max()) > 0.2 and all(abs(fx - q[0]) + abs(fy - q[1]) > 8 for q in out[cls]):
            out[cls].append([round(fx, 1), round(fy, 1)])
    return out


def mats():
    return {
        "glass": principled("veh_glass", "#0e141d", rough=0.08, metal=0.0, coat=0.4),
        "tyre": principled("tyre", "#111114", rough=0.8),
        "rim": principled("rim", "#b8bec8", rough=0.25, metal=0.9),
        "chrome": principled("chrome", "#cfd5dd", rough=0.15, metal=1.0),
        "black": principled("veh_black", "#151619", rough=0.4),
        "head": emissive("headlight", "#fff6de", 14.0),
        "tail": emissive("taillight", "#ff2a2a", 10.0),
        "amber": emissive("indicator", "#ffae2a", 8.0),
        "red_bar": emissive("bar_red", "#ff2a3a", 7.0),
        "blue_bar": emissive("bar_blue", "#2a6bff", 7.0),
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


SEDAN = [(2.30, 0.58, 0.58), (2.10, 0.74, 0.74), (1.00, 0.84, 0.84), (0.85, 0.86, 0.86), (-0.05, 0.88, 1.40), (-0.90, 0.88, 1.38), (-1.60, 0.90, 0.90), (-2.15, 0.88, 0.88), (-2.30, 0.70, 0.70)]


def stretch(knots, f):
    return [(x * f, zs, zr) for x, zs, zr in knots]


# Side profiles as (x, beltline, roof) knots in metres from the car's centre, nose at +x. The roof
# equals the beltline over the bonnet and the boot; where it rises is the glasshouse.
PROFILES = {
    "sedan": dict(L=4.6, W=1.82, clearance=0.2, r=0.32, paint="#2f3a4a", knots=SEDAN, pillars=(-0.45,), doors=(0.85, -0.45, -1.55), handles=(-0.3, -1.4)),
    "taxi": dict(L=4.6, W=1.82, clearance=0.2, r=0.32, paint="#e8b923", knots=SEDAN, pillars=(-0.45,), doors=(0.85, -0.45, -1.55), handles=(-0.3, -1.4)),
    "police": dict(L=4.7, W=1.85, clearance=0.2, r=0.33, paint="#f3f4f6", knots=stretch(SEDAN, 4.7 / 4.6), pillars=(-0.46,), doors=(0.87, -0.46, -1.58), handles=(-0.31, -1.43)),
    "coupe": dict(L=4.4, W=1.8, clearance=0.18, r=0.31, paint="#7a1f24", knots=[(2.20, 0.52, 0.52), (2.00, 0.68, 0.68), (0.80, 0.77, 0.77), (0.65, 0.79, 0.79), (-0.30, 0.80, 1.24), (-0.85, 0.80, 1.22), (-1.95, 0.84, 0.86), (-2.20, 0.66, 0.66)], pillars=(-1.0,), doors=(0.65, -0.95), handles=(-0.8,)),
    "hatchback": dict(L=3.95, W=1.75, clearance=0.2, r=0.31, paint="#8a8f98", knots=[(1.975, 0.58, 0.58), (1.80, 0.72, 0.72), (0.95, 0.82, 0.82), (0.80, 0.84, 0.84), (0.00, 0.86, 1.42), (-1.55, 0.88, 1.38), (-1.90, 0.88, 1.02), (-1.975, 0.82, 0.92)], pillars=(-0.4,), doors=(0.8, -0.4, -1.45), handles=(-0.25, -1.3)),
    "suv": dict(L=4.75, W=1.95, clearance=0.3, r=0.36, paint="#3b4250", knots=[(2.375, 0.82, 0.82), (2.20, 0.98, 0.98), (1.30, 1.08, 1.08), (1.15, 1.10, 1.10), (0.40, 1.12, 1.74), (-1.95, 1.14, 1.72), (-2.30, 1.14, 1.50), (-2.375, 1.04, 1.30)], pillars=(-0.4, -1.55), doors=(1.15, -0.4, -1.5), handles=(-0.25, -1.35)),
    "ev": dict(L=4.7, W=1.9, clearance=0.18, r=0.33, paint="#e9edf2", knots=[(2.35, 0.56, 0.56), (2.15, 0.70, 0.70), (1.25, 0.80, 0.80), (1.10, 0.82, 0.82), (0.10, 0.84, 1.40), (-1.05, 0.86, 1.40), (-2.05, 0.88, 0.98), (-2.35, 0.74, 0.74)], pillars=(-0.5,), doors=(1.1, -0.5, -1.6), handles=(-0.35, -1.45)),
}


def profile_at(knots, x):
    """(beltline, roof) at x, linear between knots."""
    ks = sorted(knots)
    if x <= ks[0][0]:
        return ks[0][1], ks[0][2]
    for a, b in zip(ks, ks[1:]):
        if x <= b[0]:
            t = (x - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t
    return ks[-1][1], ks[-1][2]


def car_shell(mb, m, paint, knots, L, W, clearance, pillars=(), inset=0.17, glass_roof=False):
    """Loft the body along its length: each station is a cross-section with a tucked sill, straight
    flanks, a shoulder at the beltline and a glasshouse leaning in to the roof. The plan rounds off
    at both bumpers. Returns the half-width and underside height as functions of x."""

    def hw(x):
        e = max(0.0, abs(x) - (L / 2 - 0.55)) / 0.55
        return W / 2 * (1 - 0.13 * e * e)

    def zb(x):
        e = max(0.0, abs(x) - (L / 2 - 0.5)) / 0.5
        return clearance + 0.14 * e * e

    stations = {round(-L / 2 + L * i / 56, 4) for i in range(57)} | {round(k[0], 4) for k in knots}
    for p in pillars:
        stations |= {round(p - 0.05, 4), round(p + 0.05, 4)}
    rings = []
    for x in sorted(stations):
        zs, zr = profile_at(knots, x)
        zr = max(zr, zs)
        h, b = hw(x), zb(x)
        r = h - inset
        cabin = zr - zs > 0.06
        near = [(-h * 0.9, b), (-h, b + 0.16), (-h, zs - 0.07), (-h * 0.975, zs), (-r, zr - 0.05 if cabin else zs), (-r * 0.88, zr if cabin else zs + 0.002)]
        ring = near + [(-y, z) for y, z in reversed(near)]
        rings.append((x, zr, cabin, [mb.bm.verts.new((x, y, z)) for y, z in ring]))
    k_glass, k_paint, k_black = mb.mi(m["glass"]), mb.mi(paint), mb.mi(m["black"])
    faces = []
    n = 12
    for (xa, ra, ca, va), (xb, rb, cb, vb) in zip(rings, rings[1:]):
        slope = abs(rb - ra) / max(1e-6, xb - xa)
        pillar = any(abs((xa + xb) / 2 - p) < 0.05 for p in pillars)
        cabin = ca and cb
        for k in range(n):
            f = mb.bm.faces.new((va[k], vb[k], vb[(k + 1) % n], va[(k + 1) % n]))
            if k in (0, 10, 11):
                f.material_index = k_black
            elif k in (3, 7) and cabin:
                f.material_index = k_black if pillar else k_glass
            elif k in (4, 6) and cabin and slope > 0.25:
                f.material_index = k_black
            elif k == 5 and cabin and (slope > 0.25 or glass_roof):
                f.material_index = k_glass
            else:
                f.material_index = k_paint
            faces.append(f)
    for _, _, _, v in (rings[0], rings[-1]):
        f = mb.bm.faces.new(v)
        f.material_index = k_paint
        faces.append(f)
    bmesh.ops.recalc_face_normals(mb.bm, faces=faces)
    return hw, zb


def mark_sharp(mb, degrees):
    """Faces meeting at more than this angle keep a crisp edge on a smooth-shaded body."""
    mb.bm.normal_update()
    limit = math.radians(degrees)
    for e in mb.bm.edges:
        if len(e.link_faces) != 2 or e.calc_face_angle(0.0) > limit:
            e.smooth = False


def car_body(mb, lights, m, paint, kind, spec):
    L, W, r, knots = spec["L"], spec["W"], spec["r"], spec["knots"]
    hw, zb = car_shell(mb, m, paint, knots, L, W, spec["clearance"], pillars=spec["pillars"], glass_roof=kind == "ev")
    belt = lambda x: profile_at(knots, x)[0]  # noqa: E731
    # wheel arches: a dark half-disc on each flank behind the tyre
    for wx in (L / 2 - 0.85, -L / 2 + 0.8):
        R = r + 0.06
        pts = [(wx + R, zb(wx) - 0.01)] + [(wx + R * math.cos(i / 12 * math.pi), r + R * math.sin(i / 12 * math.pi)) for i in range(13)] + [(wx - R, zb(wx) - 0.01)]
        y = hw(wx) + 0.004
        mb.quad([(px, -y, pz) for px, pz in pts], m["black"])
        mb.quad([(px, y, pz) for px, pz in reversed(pts)], m["black"])
    for sx in spec["doors"]:
        side_box(mb, sx - 0.006, sx + 0.006, zb(sx) + 0.17, belt(sx) - 0.08, hw(sx), m["black"], t=0.003)
    for hx in spec["handles"]:
        side_box(mb, hx - 0.1, hx + 0.1, belt(hx) - 0.17, belt(hx) - 0.13, hw(hx), m["chrome"], t=0.012)
    mx = spec["doors"][0] - 0.12
    for sgn in (-1, 1):
        mb.box(mx - 0.06, mx + 0.05, sgn * (hw(mx) - 0.06), sgn * (hw(mx) + 0.1), belt(mx) + 0.03, belt(mx) + 0.12, paint)
    nose, tail = L / 2, -L / 2
    zn, zt = belt(nose), belt(tail)
    mb.box(nose - 0.04, nose + 0.006, -0.42, 0.42, zb(nose) + 0.04, zn - 0.1, m["black"])
    he, te = hw(nose - 0.16), hw(tail + 0.14)
    for sgn in (-1, 1):
        lights.box(nose - 0.16, nose + 0.008, sgn * (he - 0.1), sgn * (he - 0.46), zn - 0.1, zn + 0.02, m["head"])
        lights.box(tail - 0.008, tail + 0.14, sgn * (te - 0.08), sgn * (te - 0.52), zt - 0.14, zt - 0.02, m["tail"])
    # the lamps wrap round the corners, so a car seen side-on still shows them
    hx0, tx0 = nose - 0.3, tail + 0.06
    side_box(lights, hx0, nose - 0.08, zn - 0.08, zn + 0.02, hw(nose - 0.08) - 0.002, m["head"], t=0.05)
    side_box(lights, tx0, tail + 0.3, zt - 0.14, zt - 0.02, hw(tail + 0.06) - 0.002, m["tail"], t=0.05)
    return hw, zb


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
    if kind in PROFILES:
        spec = PROFILES[kind]
        paint = principled(f"{kind}_paint", spec["paint"], rough=0.22, metal=0.4, coat=1.0)
        L, W, r = spec["L"], spec["W"], spec["r"]
        hw, zb = car_body(body, lights, m, paint, kind, spec)
        roof = lambda x: profile_at(spec["knots"], x)[1]  # noqa: E731
        for wx in (L / 2 - 0.85, -L / 2 + 0.8):
            wheels.append((wx, -W / 2 + 0.1, r))
            wheels.append((wx, W / 2 - 0.1, r))
        if kind == "taxi":
            top = min(roof(-0.72), roof(-0.2))
            body.box(-0.72, -0.2, -0.16, 0.16, top - 0.01, top + 0.2, m["black"])
            lights.box(-0.69, -0.23, -0.17, 0.17, top + 0.02, top + 0.18, m["taxi_sign"])
            side_strip(body, -L / 2 + 0.35, L / 2 - 0.35, 0.5, 0.58, hw, principled("taxi_check", "#151515", rough=0.4))
        if kind == "police":
            top = min(roof(-0.85), roof(-0.05))
            side_strip(body, -L / 2 + 0.3, L / 2 - 0.3, 0.4, 0.64, hw, principled("police_blue", "#1d4ed8", rough=0.3))
            body.box(-0.85, -0.05, -0.4, 0.4, top - 0.01, top + 0.06, m["black"])
            bar.box(-0.83, -0.47, -0.38, 0.38, top + 0.06, top + 0.16, m["blue_bar"])
            bar.box(-0.43, -0.07, -0.38, 0.38, top + 0.06, top + 0.16, m["red_bar"])
            info["siren"] = True
        if kind == "ev":
            zn = profile_at(spec["knots"], L / 2)[0]
            lights.box(L / 2 - 0.05, L / 2 + 0.012, -hw(L / 2) + 0.12, hw(L / 2) - 0.12, zn - 0.03, zn + 0.01, emissive("ev_bar", "#9ff5ff", 10.0))
        info["length"] = L
        info["rounded"] = True
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
                rounded = bool(info.get("rounded"))
                if rounded:
                    mark_sharp(body, 30)
                obs = [body.build(coll, bevel=0.0 if rounded else 0.03, smooth=rounded), lights.build(coll), bar.build(coll), wheels.build(coll, smooth=True)]
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
                    lights_path = os.path.join(a.out, f"{kind}__{direction}__lights.png")
                    scene.render.filepath = lights_path
                    bpy.ops.render.render(write_still=True)
                    lamps = lamp_anchors(obs[1], rot, frame, lights_path)
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
                    entry["frames"][direction] = {"w": frame["w"], "h": frame["h"], "pivot": frame["pivot"], "lamps": lamps}
                for ob in list(coll.all_objects):
                    bpy.data.objects.remove(ob, do_unlink=True)
                bpy.data.collections.remove(coll)
        catalogue["vehicles"][kind] = entry
        print(f"AMN_VEHICLE {kind}")
    with open(os.path.join(a.out, "vehicles.json"), "w", encoding="utf-8") as fh:
        json.dump(catalogue, fh, indent=1)


main()
