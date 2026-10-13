"""Render the studio's employees (and street pedestrians) as chibi sprite frames.

  blender -b --factory-startup --python art-source/blender/hq/build_characters.py -- \
      --out <frames dir> [--only sarah,kael] [--pedestrians] [--scale 4] [--samples 20]
  python art-source/blender/hq/pack_sprites.py <frames dir> frontend/public/assets/hq/characters

Colours come from the Character Bible (art-source/character_bible.json, exported from the
backend) through characters_style.json. The camera has the headquarters plates' pitch and pixel
scale, so a sprite drawn at its pivot stands on the floor it belongs to. Poses are the states the
office shows, and nothing else: typing, thinking, idle, talking, paused, error, standing,
reacting and walking. Which one plays is decided by backend state in the canvas.
"""

import argparse
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from hq_lib import COS, MB, PPM, SIN, THETA, lin, principled  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FRAME_W, FRAME_H = 48, 60
PIVOT = (24, 54)


# ----------------------------------------------------------------------------- scene


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--only", default="")
    p.add_argument("--pedestrians", action="store_true")
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--samples", type=int, default=20)
    p.add_argument("--view", default="Standard")
    p.add_argument("--look", default="None")
    p.add_argument("--exposure", type=float, default=-0.35)
    return p.parse_args(argv)


def setup_scene(a):
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
    scene.cycles.max_bounces = 4
    scene.render.film_transparent = True
    scene.render.resolution_x = FRAME_W * a.scale
    scene.render.resolution_y = FRAME_H * a.scale
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = a.view
    scene.view_settings.look = a.look
    scene.view_settings.exposure = a.exposure
    world = bpy.data.worlds.new("sprite_world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = lin("#8a92b0")
    bg.inputs["Strength"].default_value = 0.55
    scene.world = world

    cam_data = bpy.data.cameras.new("sprite_cam")
    cam_data.type = "ORTHO"
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.ortho_scale = FRAME_W / PPM
    cam = bpy.data.objects.new("sprite_cam", cam_data)
    scene.collection.objects.link(cam)
    up = Vector((0.0, SIN, COS))
    fwd = Vector((0.0, COS, -SIN))
    centre = up * ((PIVOT[1] - FRAME_H / 2) / PPM)
    cam.location = centre - fwd * 30.0
    cam.rotation_euler = (math.pi / 2 - THETA, 0.0, 0.0)
    scene.camera = cam

    def area(name, loc, energy, color, size):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.color = lin(color)[:3]
        ld.size = size
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        direction = Vector((0.0, 0.0, 0.55)) - Vector(loc)
        ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)

    area("key", (-1.4, -2.4, 2.4), 260.0, "#fff1e0", 1.6)
    area("fill", (1.8, -1.6, 1.0), 70.0, "#c9d6ff", 1.2)
    area("rim", (0.8, 2.2, 2.2), 180.0, "#ffd9b0", 1.0)
    return scene


# ----------------------------------------------------------------------------- rig


class Body:
    """A chibi body: empties for joints, meshes parented to them, poses as joint rotations."""

    REST = {
        "root": (0.0, 0.0, 0.0),
        "hips": (0.0, 0.0, 0.46),
        "chest": (0.0, 0.0, 0.64),
        "neck": (0.0, 0.0, 0.83),
        "head": (0.0, 0.0, 0.86),
        "shoulder_L": (0.172, 0.0, 0.79),
        "elbow_L": (0.19, 0.0, 0.615),
        "hand_L": (0.195, 0.0, 0.46),
        "shoulder_R": (-0.172, 0.0, 0.79),
        "elbow_R": (-0.19, 0.0, 0.615),
        "hand_R": (-0.195, 0.0, 0.46),
        "hip_L": (0.085, 0.0, 0.44),
        "knee_L": (0.085, 0.0, 0.25),
        "ankle_L": (0.085, 0.0, 0.07),
        "hip_R": (-0.085, 0.0, 0.44),
        "knee_R": (-0.085, 0.0, 0.25),
        "ankle_R": (-0.085, 0.0, 0.07),
    }
    PARENT = {
        "hips": "root",
        "chest": "hips",
        "neck": "chest",
        "head": "neck",
        "shoulder_L": "chest",
        "elbow_L": "shoulder_L",
        "hand_L": "elbow_L",
        "shoulder_R": "chest",
        "elbow_R": "shoulder_R",
        "hand_R": "elbow_R",
        "hip_L": "hips",
        "knee_L": "hip_L",
        "ankle_L": "knee_L",
        "hip_R": "hips",
        "knee_R": "hip_R",
        "ankle_R": "knee_R",
    }

    def __init__(self, name, coll):
        self.name = name
        self.coll = coll
        self.j = {}
        self.toggles = {}
        for joint in ["root"] + list(self.PARENT):
            e = bpy.data.objects.new(f"{name}_{joint}", None)
            coll.objects.link(e)
            parent = self.PARENT.get(joint)
            if parent:
                e.parent = self.j[parent]
                e.location = Vector(self.REST[joint]) - Vector(self.REST[parent])
            else:
                e.location = self.REST[joint]
            e.rotation_mode = "XYZ"
            self.j[joint] = e

    def part(self, joint, mb, smooth=True, bevel=0.0, toggle=None):
        ob = mb.build(self.coll, bevel=bevel, smooth=smooth)
        ob.parent = self.j[joint]
        ob.location = (0.0, 0.0, 0.0)
        if toggle:
            self.toggles.setdefault(toggle, []).append(ob)
        return ob

    def show(self, toggle, visible):
        for ob in self.toggles.get(toggle, []):
            ob.hide_render = not visible

    def pose(self, rotations, root_z=0.0, facing=0.0, root_x=0.0):
        for e in self.j.values():
            e.rotation_euler = (0.0, 0.0, 0.0)
        self.j["root"].location = (root_x, 0.0, root_z)
        self.j["root"].rotation_euler = (0.0, 0.0, math.radians(facing))
        for joint, (rx, ry, rz) in rotations.items():
            self.j[joint].rotation_euler = (math.radians(rx), math.radians(ry), math.radians(rz))


def local(joint):
    return Vector(Body.REST[joint])


# ----------------------------------------------------------------------------- appearance


def palette_colour(value, palette, fallback="#808080"):
    if not value:
        return fallback
    if value.startswith("#"):
        return value
    return palette.get(value, fallback)


def mats_for(key, style, palette):
    def cloth(name, colour, rough=0.75):
        return principled(f"{key}_{name}", colour, rough=rough)

    top = style["top"]
    m = {
        "skin": principled(f"{key}_skin", style["skin"], rough=0.55),
        "blush": principled(f"{key}_blush", "#f29a8a", rough=0.6),
        "hair": principled(f"{key}_hair", palette_colour(style["hair"]["color"], palette), rough=0.42),
        "top": cloth("top", palette_colour(top.get("color"), palette)),
        "inner": cloth("inner", palette_colour(top.get("inner"), palette, "#e5e7eb")),
        "legs": cloth("legs", palette_colour(style["legs"]["color"], palette, "#1f2937")),
        "shoes": principled(f"{key}_shoes", palette_colour(style["legs"].get("shoes"), palette, "#111216"), rough=0.35),
        "eye": principled(f"{key}_eye", "#2a1a14", rough=0.2),
        "eye_white": principled(f"{key}_eyewhite", "#ffffff", rough=0.3, emit="#ffffff", strength=0.6),
        "mouth": principled(f"{key}_mouth", "#8a3a34", rough=0.5),
        "dark": principled(f"{key}_dark", "#16171c", rough=0.4),
    }
    if top.get("tie"):
        m["tie"] = cloth("tie", palette_colour(top["tie"], palette))
    if style["hair"].get("streak"):
        m["streak"] = principled(f"{key}_streak", style["hair"]["streak"], rough=0.42)
    if style["hair"].get("temples"):
        m["temples"] = principled(f"{key}_temples", style["hair"]["temples"], rough=0.45)
    for acc in style.get("accessories", []):
        m[f"acc_{acc['kind']}"] = principled(f"{key}_{acc['kind']}", palette_colour(acc["color"], palette), rough=0.3, metal=0.4 if "glasses" in acc["kind"] else 0.0)
    return m


def build_character(key, style, palette, coll):
    b = Body(key, coll)
    m = mats_for(key, style, palette)
    top_kind = style["top"]["kind"]
    head_r = 0.235
    head_c = Vector((0.0, 0.0, 0.215))  # head centre relative to the head joint

    # ---- legs and feet
    for side in ("L", "R"):
        thigh = MB(f"{key}_thigh_{side}")
        thigh.cyl(0, 0, -0.2, 0.02, 0.062, m["legs"], seg=14)
        b.part(f"hip_{side}", thigh)
        shin = MB(f"{key}_shin_{side}")
        shin.cyl(0, 0, -0.19, 0.0, 0.055, m["legs"], seg=14, r_top=0.06)
        b.part(f"knee_{side}", shin)
        foot = MB(f"{key}_foot_{side}")
        foot.box(-0.055, 0.055, -0.13, 0.05, -0.075, -0.005, m["shoes"])
        b.part(f"ankle_{side}", foot, bevel=0.02)

    # ---- pelvis and torso
    pelvis = MB(f"{key}_pelvis")
    pelvis.box(-0.15, 0.15, -0.095, 0.095, -0.07, 0.19, m["legs"] if top_kind != "flightsuit" else m["top"])
    b.part("hips", pelvis, bevel=0.04)
    torso = MB(f"{key}_torso")
    torso.box(-0.16, 0.16, -0.1, 0.1, -0.02, 0.21, m["top"])
    torso.box(-0.175, 0.175, -0.105, 0.105, 0.12, 0.2, m["top"])
    if top_kind in ("blazer", "labcoat", "vest", "hoodie", "cardigan", "shirt"):
        torso.quad([(-0.05, -0.107, 0.2), (0.05, -0.107, 0.2), (0.0, -0.107, 0.02)], m["inner"])
        torso.box(-0.035, 0.035, -0.108, -0.104, -0.02, 0.2, m["inner"])
    if "tie" in m:
        torso.box(-0.014, 0.014, -0.112, -0.108, 0.0, 0.19, m["tie"])
    if top_kind == "hoodie":
        torso.cyl(0.0, 0.09, 0.19, 0.24, 0.12, m["top"], seg=14)
        for sx in (-0.03, 0.03):
            torso.box(sx - 0.004, sx + 0.004, -0.112, -0.106, 0.08, 0.18, principled(f"{key}_string", "#e5e7eb", rough=0.6))
    if top_kind == "flightsuit" or any(a["kind"] == "belt" for a in style.get("accessories", [])):
        torso.box(-0.165, 0.165, -0.106, 0.106, -0.02, 0.02, m.get("acc_belt", m["dark"]))
    if any(a["kind"] == "badge" for a in style.get("accessories", [])):
        torso.box(0.06, 0.1, -0.112, -0.106, 0.07, 0.12, m["acc_badge"])
    if any(a["kind"] == "pen_chain" for a in style.get("accessories", [])):
        torso.box(-0.004, 0.004, -0.113, -0.108, 0.05, 0.19, m["acc_pen_chain"])
    b.part("chest", torso, bevel=0.045)
    if top_kind == "labcoat":
        for sx0, sx1 in ((-0.19, -0.02), (0.02, 0.19)):
            skirt = MB(f"{key}_coat_{sx0}")
            skirt.box(sx0, sx1, -0.11, 0.11, -0.3, 0.02, m["top"])
            b.part("hips", skirt, bevel=0.02)

    # ---- arms
    rolled = style["top"].get("rolled", False)
    for side, sx in (("L", 1), ("R", -1)):
        upper = MB(f"{key}_upper_{side}")
        upper.cyl(0, 0, -0.18, 0.02, 0.058, m["top"], seg=12)
        b.part(f"shoulder_{side}", upper)
        fore = MB(f"{key}_fore_{side}")
        fore.cyl(0, 0, -0.16, 0.0, 0.05, m["skin"] if rolled else m["top"], seg=12)
        if rolled:
            fore.cyl(0, 0, -0.035, 0.005, 0.058, m["top"], seg=12)
        b.part(f"elbow_{side}", fore)
        hand = MB(f"{key}_hand_{side}")
        hand.sphere((0, -0.005, -0.03), 0.048, m["skin"], seg=12, rings=8, scale=(0.9, 0.8, 1.1))
        b.part(f"hand_{side}", hand)

    # ---- neck and head
    neck = MB(f"{key}_neck")
    neck.cyl(0, 0, -0.02, 0.06, 0.045, m["skin"], seg=12)
    b.part("neck", neck)
    head = MB(f"{key}_head")
    head.sphere(tuple(head_c), head_r, m["skin"], seg=28, rings=18, scale=(1.0, 0.94, 0.98))
    for sx in (-1, 1):
        head.sphere((sx * 0.225, 0.0, head_c.z - 0.01), 0.04, m["skin"], seg=10, rings=6)
    b.part("head", head)
    face_y = head_c.y - head_r * 0.92
    eyes = MB(f"{key}_eyes_open")
    for sx in (-1, 1):
        ex, ez = sx * 0.085, head_c.z - 0.015
        eyes.sphere((ex, face_y + 0.012, ez), 0.042, m["eye"], seg=14, rings=10, scale=(0.78, 0.35, 1.05))
        eyes.sphere((ex + sx * 0.01 - 0.012, face_y - 0.004, ez + 0.02), 0.012, m["eye_white"], seg=8, rings=6, scale=(1, 0.5, 1))
        eyes.box(ex - 0.045, ex + 0.045, face_y - 0.0, face_y + 0.02, ez + 0.058, ez + 0.07, m["hair"])
    b.part("head", eyes, toggle="eyes_open")
    closed = MB(f"{key}_eyes_closed")
    for sx in (-1, 1):
        ex, ez = sx * 0.085, head_c.z - 0.02
        closed.box(ex - 0.035, ex + 0.035, face_y - 0.002, face_y + 0.02, ez - 0.006, ez + 0.006, m["eye"])
    b.part("head", closed, toggle="eyes_closed")
    blush = MB(f"{key}_blush")
    for sx in (-1, 1):
        blush.sphere((sx * 0.13, face_y + 0.03, head_c.z - 0.075), 0.03, m["blush"], seg=10, rings=6, scale=(1.2, 0.25, 0.6))
    b.part("head", blush)
    mouth = MB(f"{key}_mouth_closed")
    mouth.box(-0.025, 0.025, face_y + 0.012, face_y + 0.03, head_c.z - 0.118, head_c.z - 0.108, m["mouth"])
    b.part("head", mouth, toggle="mouth_closed")
    mouth_o = MB(f"{key}_mouth_open")
    mouth_o.sphere((0.0, face_y + 0.02, head_c.z - 0.115), 0.022, m["mouth"], seg=10, rings=6, scale=(1.2, 0.4, 1.0))
    b.part("head", mouth_o, toggle="mouth_open")

    build_hair(b, key, style, m, head_c, head_r)
    for acc in style.get("accessories", []):
        build_accessory(b, key, acc, m, head_c, head_r, face_y)
    if style.get("seat_facing") == "front":
        chair = MB(f"{key}_chair")
        dark = principled("chair_dark", "#1b1c22", rough=0.45)
        chair.box(-0.2, 0.2, 0.16, 0.24, 0.3, 0.78, dark)
        chair.box(-0.18, 0.18, -0.22, 0.2, 0.2, 0.27, dark)
        b.part("root", chair, bevel=0.04, toggle="chair")
    return b


def hair_shell(mb, centre, radius, keep, m, scale=(1.08, 1.08, 1.05), seg=28, rings=18, jitter=0.0, seed=0):
    xf = Matrix.Translation(centre) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    ret = bmesh.ops.create_uvsphere(mb.bm, u_segments=seg, v_segments=rings, radius=radius, matrix=xf)
    verts = ret["verts"]
    if jitter:
        rng = random.Random(seed)
        for v in verts:
            v.co += Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * jitter
    drop = [v for v in verts if not keep(v.co - Vector(centre))]
    faces = {f for v in verts for f in v.link_faces}
    k = mb.mi(m)
    for f in faces:
        f.material_index = k
    bmesh.ops.delete(mb.bm, geom=drop, context="VERTS")


def build_hair(b, key, style, m, hc, hr):
    kind = style["hair"]["style"]
    hair = MB(f"{key}_hair")
    c = tuple(hc + Vector((0.0, 0.012, 0.01)))

    def fringe(p, bottom):
        # keep the back and top; open the face below the fringe line
        front = p.y < -0.06
        return not (front and p.z < bottom and abs(p.x) < 0.2)

    def nape(keep):
        # whatever a style trims at the sides, the back of the head stays covered to the neck
        return lambda p: keep(p) or (p.y > 0.02 and p.z > -0.2 and fringe(p, 0.1))

    if kind == "bob":
        hair_shell(hair, c, hr, lambda p: fringe(p, 0.07) and p.z > -0.2, m["hair"], scale=(1.12, 1.1, 1.06))
    elif kind == "bob_short":
        hair_shell(hair, c, hr, nape(lambda p: fringe(p, 0.09) and p.z > -0.12), m["hair"], scale=(1.1, 1.08, 1.05))
        hair.sphere((hc.x - 0.11, hc.y - 0.14, hc.z + 0.17), 0.075, m["hair"], seg=12, rings=8, scale=(1.4, 0.6, 0.55))
    elif kind == "short":
        hair_shell(hair, c, hr, nape(lambda p: fringe(p, 0.11) and p.z > -0.04), m["hair"], scale=(1.06, 1.06, 1.04))
        if "temples" in m:
            for sx in (-1, 1):
                hair.box(sx * 0.225, sx * 0.25, -0.05, 0.05, hc.z - 0.02, hc.z + 0.08, m["temples"])
    elif kind in ("high_bun", "low_bun"):
        hair_shell(hair, c, hr, nape(lambda p: fringe(p, 0.1) and p.z > -0.06), m["hair"], scale=(1.06, 1.06, 1.04))
        if kind == "high_bun":
            hair.sphere((0.0, hc.y + 0.06, hc.z + hr + 0.05), 0.1, m["hair"], seg=16, rings=10)
        else:
            hair.sphere((0.0, hc.y + hr + 0.02, hc.z - 0.07), 0.095, m["hair"], seg=16, rings=10)
    elif kind == "long":
        hair_shell(hair, c, hr, lambda p: fringe(p, 0.08), m["hair"], scale=(1.1, 1.1, 1.05))
        hair.box(-0.21, 0.21, hc.y + 0.08, hc.y + 0.22, hc.z - 0.62, hc.z - 0.02, m["hair"])
        for sx in (-1, 1):
            lock = m["streak"] if (sx > 0 and "streak" in m) else m["hair"]
            hair.box(sx * 0.175, sx * 0.24, hc.y - 0.12, hc.y + 0.1, hc.z - 0.42, hc.z + 0.02, lock)
    elif kind == "spiky":
        hair_shell(hair, c, hr, nape(lambda p: fringe(p, 0.1) and p.z > -0.05), m["hair"], scale=(1.08, 1.08, 1.06))
        rng = random.Random(7)
        for i in range(16):
            a = i / 16 * math.tau
            elev = rng.uniform(0.35, 1.2)
            d = Vector((math.cos(a) * math.cos(elev), math.sin(a) * math.cos(elev), math.sin(elev)))
            if d.y < -0.5 and d.z < 0.6:
                continue
            base = hc + d * hr * 0.9
            tip = hc + d * (hr + rng.uniform(0.08, 0.13))
            hair.bm.verts.ensure_lookup_table()
            _spike(hair, base, tip, 0.05, m["hair"])
    elif kind == "tousled":
        hair_shell(hair, c, hr, nape(lambda p: fringe(p, 0.09) and p.z > -0.06), m["hair"], scale=(1.08, 1.08, 1.06))
        rng = random.Random(11)
        for i in range(18):
            a = rng.uniform(0, math.tau)
            elev = rng.uniform(0.25, 1.3)
            d = Vector((math.cos(a) * math.cos(elev), math.sin(a) * math.cos(elev) * 0.9, math.sin(elev)))
            if d.y < -0.55 and d.z < 0.5:
                continue
            hair.sphere(tuple(hc + d * (hr + 0.02)), rng.uniform(0.05, 0.075), m["hair"], seg=10, rings=7)
    b.part("head", hair)


def _spike(mb, base, tip, width, m):
    d = (tip - base).normalized()
    t = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized() * width
    s = d.cross(t).normalized() * width
    verts = [mb.bm.verts.new(base + t), mb.bm.verts.new(base + s), mb.bm.verts.new(base - t), mb.bm.verts.new(base - s)]
    apex = mb.bm.verts.new(tip)
    k = mb.mi(m)
    for i in range(4):
        f = mb.bm.faces.new((verts[i], verts[(i + 1) % 4], apex))
        f.material_index = k


def ring(mb, centre, radius, thickness, m, seg=16):
    for i in range(seg):
        a0, a1 = i / seg * math.tau, (i + 1) / seg * math.tau
        p0 = centre + Vector((math.cos(a0) * radius, 0.0, math.sin(a0) * radius))
        p1 = centre + Vector((math.cos(a1) * radius, 0.0, math.sin(a1) * radius))
        mid = (p0 + p1) / 2
        length = (p1 - p0).length
        xf = Matrix.Translation(mid) @ Matrix.Rotation(-(a0 + a1) / 2 + math.pi / 2, 4, "Y")
        mb.box(-length / 2, length / 2, -thickness / 2, thickness / 2, -thickness / 2, thickness / 2, m, xf)


def build_accessory(b, key, acc, m, hc, hr, face_y):
    kind = acc["kind"]
    mat = m[f"acc_{kind}"]
    part = MB(f"{key}_{kind}")
    if kind in ("round_glasses", "glasses"):
        r = 0.052 if kind == "round_glasses" else 0.048
        lens = principled(f"{key}_lens", "#ffffff", rough=0.05, alpha=0.18, emit="#ffffff", strength=0.4)
        for sx in (-1, 1):
            cen = Vector((sx * 0.085, face_y - 0.03, hc.z - 0.015))
            ring(part, cen, r, 0.012, mat)
            part.cyl_y(cen.x, cen.y + 0.004, cen.z, 0.004, r * 0.92, lens, seg=14)
            part.box(sx * 0.14, sx * 0.23, face_y - 0.03, face_y + 0.12, cen.z + 0.02, cen.z + 0.03, mat)
        part.box(-0.035, 0.035, face_y - 0.034, face_y - 0.026, hc.z - 0.005, hc.z + 0.005, mat)
    elif kind == "headphones":
        for sx in (-1, 1):
            part.cyl_x(sx * 0.25, 0.0, hc.z - 0.01, 0.07, 0.085, mat, seg=16)
            part.cyl_x(sx * 0.29, 0.0, hc.z - 0.01, 0.02, 0.06, principled(f"{key}_cup_logo", "#1e1b2e", rough=0.3), seg=12)
        arc_pts = [Vector((math.cos(a) * 0.26, 0.0, hc.z + math.sin(a) * 0.29)) for a in [i / 12 * math.pi for i in range(13)]]
        for p0, p1 in zip(arc_pts, arc_pts[1:]):
            _beam(part, p0, p1, 0.022, mat)
    elif kind == "headset":
        part.cyl_x(-0.25, 0.0, hc.z - 0.01, 0.05, 0.055, principled(f"{key}_headset_body", "#16171c", rough=0.35), seg=14)
        part.cyl_x(-0.278, 0.0, hc.z - 0.01, 0.01, 0.032, mat, seg=12)
        arc_pts = [Vector((math.cos(a) * 0.25, 0.0, hc.z + math.sin(a) * 0.28)) for a in [i / 10 * math.pi for i in range(11)]]
        for p0, p1 in zip(arc_pts, arc_pts[1:]):
            _beam(part, p0, p1, 0.015, principled(f"{key}_headset_body", "#16171c", rough=0.35))
        _beam(part, Vector((-0.25, -0.03, hc.z - 0.05)), Vector((-0.08, face_y - 0.02, hc.z - 0.12)), 0.012, principled(f"{key}_headset_body", "#16171c", rough=0.35))
        part.sphere((-0.075, face_y - 0.025, hc.z - 0.12), 0.02, mat, seg=8, rings=6)
    elif kind == "earrings":
        for sx in (-1, 1):
            part.sphere((sx * 0.225, -0.02, hc.z - 0.07), 0.018, mat, seg=8, rings=6)
    elif kind == "stubble":
        part.sphere((0.0, face_y + 0.05, hc.z - 0.15), 0.1, principled(f"{key}_stubble", acc["color"], rough=0.8, alpha=0.16), seg=16, rings=8, scale=(1.25, 0.3, 0.42))
    else:
        return
    b.part("head", part)


def _beam(mb, p0, p1, r, m):
    d = p1 - p0
    length = d.length
    if length < 1e-6:
        return
    z = d.normalized()
    x = z.cross(Vector((0, 0, 1)) if abs(z.z) < 0.9 else Vector((1, 0, 0))).normalized() * r
    y = z.cross(x).normalized() * r
    corners = [p0 + x + y, p0 - x + y, p0 - x - y, p0 + x - y]
    v0 = [mb.bm.verts.new(cc) for cc in corners]
    v1 = [mb.bm.verts.new(cc + d) for cc in corners]
    k = mb.mi(m)
    for i in range(4):
        f = mb.bm.faces.new((v0[i], v0[(i + 1) % 4], v1[(i + 1) % 4], v1[i]))
        f.material_index = k


# ----------------------------------------------------------------------------- poses

SEAT_Z = -0.19


def seated(extra=None):
    base = {
        "hip_L": (-88, 0, 0),
        "hip_R": (-88, 0, 0),
        "knee_L": (88, 0, 0),
        "knee_R": (88, 0, 0),
    }
    base.update(extra or {})
    return base


def typing(phase):
    lift_l = 6 * math.sin(phase * math.pi)
    lift_r = 6 * math.cos(phase * math.pi)
    return seated(
        {
            "shoulder_L": (-55 - lift_l, 0, 8),
            "elbow_L": (-45, 0, -6),
            "shoulder_R": (-55 - lift_r, 0, -8),
            "elbow_R": (-45, 0, 6),
            "head": (6 + 2 * math.sin(phase * math.pi * 2), 0, 0),
        }
    )


POSES = {
    "sit_type": [lambda i=i: (typing(i / 2), {}) for i in range(4)],
    "sit_idle": [
        lambda: (seated({"shoulder_L": (-20, 0, 6), "shoulder_R": (-20, 0, -6), "elbow_L": (-60, 0, 0), "elbow_R": (-60, 0, 0)}), {}),
        lambda: (seated({"shoulder_L": (-20, 0, 6), "shoulder_R": (-20, 0, -6), "elbow_L": (-60, 0, 0), "elbow_R": (-60, 0, 0), "chest": (-2, 0, 0)}), {"eyes_open": False, "eyes_closed": True}),
    ],
    "sit_think": [
        lambda: (seated({"shoulder_R": (-120, 0, -25), "elbow_R": (-115, 0, 10), "shoulder_L": (-30, 0, 10), "elbow_L": (-60, 0, 0), "head": (4, 10, 6)}), {}),
        lambda: (seated({"shoulder_R": (-118, 0, -25), "elbow_R": (-118, 0, 10), "shoulder_L": (-30, 0, 10), "elbow_L": (-60, 0, 0), "head": (-4, 10, -6)}), {}),
    ],
    "sit_talk": [
        lambda: (seated({"shoulder_L": (-50, 0, 30), "elbow_L": (-50, 0, 0), "shoulder_R": (-30, 0, -8), "elbow_R": (-55, 0, 0), "head": (0, -4, 4)}), {"mouth_closed": False, "mouth_open": True}),
        lambda: (seated({"shoulder_L": (-60, 0, 18), "elbow_L": (-70, 0, 0), "shoulder_R": (-30, 0, -8), "elbow_R": (-55, 0, 0), "head": (0, 4, -4)}), {}),
    ],
    "sit_sleep": [
        lambda: (seated({"chest": (28, 0, 0), "head": (22, 0, 0), "shoulder_L": (-75, 0, -20), "shoulder_R": (-75, 0, 20), "elbow_L": (-80, 0, 30), "elbow_R": (-80, 0, -30)}), {"eyes_open": False, "eyes_closed": True}),
        lambda: (seated({"chest": (31, 0, 0), "head": (24, 0, 0), "shoulder_L": (-75, 0, -20), "shoulder_R": (-75, 0, 20), "elbow_L": (-80, 0, 30), "elbow_R": (-80, 0, -30)}), {"eyes_open": False, "eyes_closed": True}),
    ],
    "sit_error": [
        lambda: (seated({"shoulder_L": (-160, 0, 20), "shoulder_R": (-160, 0, -20), "elbow_L": (-70, 0, -30), "elbow_R": (-70, 0, 30), "head": (0, 0, 8)}), {"mouth_closed": False, "mouth_open": True}),
        lambda: (seated({"shoulder_L": (-160, 0, 20), "shoulder_R": (-160, 0, -20), "elbow_L": (-70, 0, -30), "elbow_R": (-70, 0, 30), "head": (0, 0, -8)}), {}),
    ],
    "stand_idle": [
        lambda: ({"shoulder_L": (0, 0, 4), "shoulder_R": (0, 0, -4)}, {}),
        lambda: ({"shoulder_L": (0, 0, 5), "shoulder_R": (0, 0, -5), "chest": (-1, 0, 0)}, {"eyes_open": False, "eyes_closed": True}),
    ],
    "stand_react": [
        lambda: ({"shoulder_R": (-150, 0, -20), "elbow_R": (-10, 0, 0), "head": (-12, 0, -25)}, {"mouth_closed": False, "mouth_open": True}),
        lambda: ({"shoulder_R": (-140, 0, -25), "elbow_R": (-20, 0, 0), "head": (-14, 0, -28)}, {}),
    ],
    "walk": [
        (lambda i=i: (
            {
                "hip_L": (32 * math.sin(i / 8 * math.tau), 0, 0),
                "hip_R": (-32 * math.sin(i / 8 * math.tau), 0, 0),
                "knee_L": (max(0.0, 45 * math.sin(i / 8 * math.tau + 1.2)), 0, 0),
                "knee_R": (max(0.0, -45 * math.sin(i / 8 * math.tau + 1.2)), 0, 0),
                "shoulder_L": (-26 * math.sin(i / 8 * math.tau), 0, 3),
                "shoulder_R": (26 * math.sin(i / 8 * math.tau), 0, -3),
                "elbow_L": (-20, 0, 0),
                "elbow_R": (-20, 0, 0),
            },
            {"_bob": 0.012 * abs(math.cos(i / 8 * math.tau))},
        ))
        for i in range(8)
    ],
}

SEATED_SETS = ["sit_type", "sit_idle", "sit_think", "sit_talk", "sit_sleep", "sit_error"]


def render_character(scene, b, key, out_dir, facing_default, a):
    os.makedirs(out_dir, exist_ok=True)
    index = []

    def shoot(anim, i, rot, toggles, facing, root_z, chair):
        for t in ("eyes_open", "mouth_closed"):
            b.show(t, True)
        for t in ("eyes_closed", "mouth_open"):
            b.show(t, False)
        b.show("chair", chair)
        bob = toggles.pop("_bob", 0.0)
        for t, vis in toggles.items():
            b.show(t, vis)
        b.pose(rot, root_z=root_z + bob, facing=facing)
        bpy.context.view_layer.update()
        name = f"{key}__{anim}__{i:02d}.png"
        scene.render.filepath = os.path.join(out_dir, name)
        bpy.ops.render.render(write_still=True)
        index.append({"file": name, "anim": anim, "frame": i})

    for anim in ([] if key.startswith("ped") else SEATED_SETS):
        for view, facing in (("front", 0.0), ("back", 180.0)):
            for i, make in enumerate(POSES[anim]):
                rot, toggles = make()
                shoot(f"{anim}_{view}", i, rot, dict(toggles), facing, SEAT_Z, chair=(view == "front"))
    for anim in ("stand_idle", "stand_react"):
        for i, make in enumerate(POSES[anim]):
            rot, toggles = make()
            shoot(anim, i, rot, dict(toggles), 0.0, 0.0, chair=False)
    for i, make in enumerate(POSES["walk"]):
        rot, toggles = make()
        shoot("walk_right", i, rot, dict(toggles), 90.0, 0.0, chair=False)
    return index


# ----------------------------------------------------------------------------- pedestrians

PED_TOPS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#6b7280", "#8b5cf6", "#0ea5e9", "#f97316", "#e5e7eb", "#1f2937", "#be185d", "#65a30d"]
PED_LEGS = ["#1f2937", "#374151", "#1e3a8a", "#78716c", "#111827", "#4b5563"]
PED_HAIR = ["#1c1917", "#3f2a1d", "#78350f", "#a16207", "#6b7280", "#111827", "#d6d3d1"]
PED_SKIN = ["#f1c9a5", "#e0ac84", "#c68b5e", "#8d5a3b", "#f3d2b8", "#b77a52"]
PED_STYLES = ["short", "bob", "tousled", "long", "spiky", "bob_short", "low_bun", "short"]


def pedestrian_style(i):
    rng = random.Random(1000 + i)
    kind = rng.choice(["shirt", "hoodie", "sweater", "blazer", "vest"])
    return {
        "skin": rng.choice(PED_SKIN),
        "hair": {"style": PED_STYLES[i % len(PED_STYLES)], "color": rng.choice(PED_HAIR)},
        "top": {"kind": kind, "color": rng.choice(PED_TOPS), "inner": rng.choice(["#e5e7eb", "#1f2937", "#f5f5f4"])},
        "legs": {"color": rng.choice(PED_LEGS), "shoes": rng.choice(["#111216", "#e5e7eb", "#5a3a22"])},
        "accessories": [],
        "seat_facing": "back",
    }


def main():
    a = args()
    scene = setup_scene(a)
    bible = {c["role"]: c for c in json.load(open(os.path.join(ROOT, "art-source", "character_bible.json"), encoding="utf-8"))}
    styles = json.load(open(os.path.join(HERE, "characters_style.json"), encoding="utf-8"))["employees"]
    only = {s for s in a.only.split(",") if s}
    manifest = {"frame": {"w": FRAME_W, "h": FRAME_H, "pivot": PIVOT, "scale": a.scale}, "characters": {}}
    jobs = []
    if a.pedestrians:
        for i in range(12):
            jobs.append((f"ped{i:02d}", pedestrian_style(i), {}, None))
    else:
        for role, style in styles.items():
            if only and style["sprite"] not in only:
                continue
            jobs.append((style["sprite"], style, bible.get(role, {}).get("palette", {}), role))
    for key, style, palette, role in jobs:
        coll = bpy.data.collections.new(key)
        scene.collection.children.link(coll)
        b = build_character(key, style, palette, coll)
        frames = render_character(scene, b, key, a.out, style.get("seat_facing", "front"), a)
        manifest["characters"][key] = {
            "role": role,
            "canonical_name": bible.get(role, {}).get("canonical_name") if role else None,
            "seat_facing": style.get("seat_facing", "front"),
            "frames": frames,
        }
        for ob in list(coll.all_objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(coll)
        print(f"AMN_CHARACTER {key} frames={len(frames)}")
    name = "pedestrians.json" if a.pedestrians else "characters.json"
    with open(os.path.join(a.out, name), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)


main()
