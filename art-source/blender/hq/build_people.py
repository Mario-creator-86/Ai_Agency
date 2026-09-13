"""Render the studio's employees and the street's pedestrians as sprite frames, with adult
proportions, every employee seated facing the viewer.

  blender -b --factory-startup --python art-source/blender/hq/build_people.py -- \
      --out <frames dir> [--only sarah,kael] [--pedestrians] [--scale 4] [--samples 24]
  python art-source/blender/hq/pack_sprites.py <frames dir> frontend/public/assets/hq/characters --downscale 2

Replaces the chibi figures of build_characters.py. The Owner asked for every employee to sit at
their own desk facing the viewer, the monitor to one side, the person fully visible: the desks and
chairs are in the plates (hq_building.workstation), the people are these sprites, drawn by the
canvas between the chair and the desk.

Bodies are metaballs, one family per material (skin, top, sleeves, legs, shoes), so shoulders,
elbows and hips blend into one figure; each frame is posed by placing the joints and rebuilding the
figure. Face, hair and accessories are meshes that turn with the head. Colours come from the
Character Bible (art-source/character_bible.json) through characters_style.json. Poses are the
states the office shows, and nothing else; which one plays is decided by backend state.
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

from hq_lib import COS, MB, PPM, SIN, THETA, Graph, emissive, lin, principled  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FRAME_W, FRAME_H = 48, 60
PIVOT = (24, 54)
VISIBLE = 0.575  # an isolated metaball's surface sits at this share of its radius (stiffness 2, threshold 0.6)
HEAD_R = 0.108
HEAD_SCALE = 1.12  # heads a little larger than life, so faces read at the canvas scale


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--only", default="")
    p.add_argument("--pedestrians", action="store_true")
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--samples", type=int, default=24)
    p.add_argument("--exposure", type=float, default=0.0)
    return p.parse_args(argv)


# ----------------------------------------------------------------------------- scene


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
    # the plates' look, so a person reads as lit by the same room
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.view_settings.exposure = a.exposure
    world = bpy.data.worlds.new("people_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = lin("#3b4c80")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35
    scene.world = world

    cam = bpy.data.objects.new("people_cam", bpy.data.cameras.new("people_cam"))
    cam.data.type = "ORTHO"
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.ortho_scale = FRAME_W / PPM
    scene.collection.objects.link(cam)
    up = Vector((0.0, SIN, COS))
    fwd = Vector((0.0, COS, -SIN))
    cam.location = up * ((PIVOT[1] - FRAME_H / 2) / PPM) - fwd * 30.0
    cam.rotation_euler = (math.pi / 2 - THETA, 0.0, 0.0)
    scene.camera = cam

    def area(name, loc, target, energy, color, size):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, lin(color)[:3]
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(ob)

    # a warm ceiling light, a cool fill from the room, a warm rim from behind
    area("key", (-0.6, -0.5, 2.5), (0.0, 0.0, 0.9), 300.0, "#ffd9a8", 1.2)
    area("fill", (1.4, -3.0, 1.4), (0.0, 0.0, 0.9), 70.0, "#c9d6ff", 1.5)
    area("rim", (0.4, 1.2, 2.0), (0.0, 0.0, 1.0), 220.0, "#ffc890", 0.8)
    return scene


# ----------------------------------------------------------------------------- materials


def edge_darken(mat, value=0.5, blend=0.5):
    """Darken the base colour towards the silhouette, as a painted figure's edges are darker."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if bsdf.inputs["Base Color"].is_linked:
        return mat
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Color"].default_value = bsdf.inputs["Base Color"].default_value
    hsv.inputs["Value"].default_value = value
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = blend
    nt.links.new(lw.outputs["Facing"], hsv.inputs["Fac"])
    nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


_MATS = {}


def cloth(name, colour, rough=0.82):
    """Woven cloth: a fine noise bump and a little sheen, so garments are not plastic."""
    if name in _MATS:
        return _MATS[name]
    g = Graph(name)
    g.bsdf.inputs["Base Color"].default_value = lin(colour)
    g.bsdf.inputs["Roughness"].default_value = rough
    g.bsdf.inputs["Sheen Weight"].default_value = 0.35
    n = g.node("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 220.0
    n.inputs["Detail"].default_value = 4.0
    b = g.node("ShaderNodeBump")
    b.inputs["Strength"].default_value = 0.18
    g.link(n.outputs["Fac"], b.inputs["Height"])
    g.link(b.outputs["Normal"], g.bsdf.inputs["Normal"])
    _MATS[name] = edge_darken(g.m, 0.45, 0.55)
    return _MATS[name]


def skin_material(name, colour):
    if name in _MATS:
        return _MATS[name]
    m = principled(name, colour, rough=0.48)
    for node in m.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            node.inputs["Subsurface Weight"].default_value = 0.25
            node.inputs["Subsurface Radius"].default_value = (0.02, 0.008, 0.004)
    _MATS[name] = edge_darken(m, 0.62, 0.4)
    return _MATS[name]


def palette_colour(value, palette, fallback="#808080"):
    if not value:
        return fallback
    return value if value.startswith("#") else palette.get(value, fallback)


def materials_for(key, style, palette):
    top = style["top"]
    kind = top["kind"]
    top_c = palette_colour(top.get("color"), palette)
    inner_c = palette_colour(top.get("inner"), palette, "#e5e7eb")
    m = {
        "skin": skin_material(f"{key}_skin", style["skin"]),
        "top": cloth(f"{key}_top", top_c),
        "inner": cloth(f"{key}_inner", inner_c, rough=0.7),
        "legs": cloth(f"{key}_legs", top_c if kind == "flightsuit" else palette_colour(style["legs"]["color"], palette, "#1f2937")),
        "shoes": principled(f"{key}_shoes", palette_colour(style["legs"].get("shoes"), palette, "#111216"), rough=0.35),
        "hair": edge_darken(principled(f"{key}_hair", palette_colour(style["hair"]["color"], palette), rough=0.45), 0.45, 0.5),
        "brow": principled(f"{key}_brow", palette_colour(style["hair"]["color"], palette), rough=0.6),
        "eye": principled(f"{key}_eye", "#1d1512", rough=0.3),
        "catch": emissive(f"{key}_catch", "#ffffff", 1.0),
        "lips": principled(f"{key}_lips", "#9a4a42", rough=0.5),
        "mouth": principled(f"{key}_mouth", "#4a1f1c", rough=0.5),
        "dark": principled(f"{key}_dark", "#16171c", rough=0.4),
    }
    # a vest shows the shirt's sleeves; every other top has its own
    m["sleeve"] = m["inner"] if kind == "vest" else m["top"]
    if top.get("tie"):
        m["tie"] = cloth(f"{key}_tie", palette_colour(top["tie"], palette), rough=0.5)
    if style["hair"].get("streak"):
        m["streak"] = principled(f"{key}_streak", style["hair"]["streak"], rough=0.42)
    if style["hair"].get("temples"):
        m["temples"] = principled(f"{key}_temples", style["hair"]["temples"], rough=0.45)
    for acc in style.get("accessories", []):
        m[f"acc_{acc['kind']}"] = principled(f"{key}_{acc['kind']}", palette_colour(acc["color"], palette), rough=0.3, metal=0.5 if acc["kind"] in ("earrings", "pen_chain", "round_glasses", "glasses") else 0.0)
    return m


# ----------------------------------------------------------------------------- figure


class Blobs:
    """One metaball object = one material family; all its elements blend into one surface."""

    def __init__(self, name, mat, coll):
        self.data = bpy.data.metaballs.new(name)
        self.data.resolution = 0.04
        self.data.render_resolution = 0.011
        self.data.threshold = 0.6
        self.data.materials.append(mat)
        self.ob = bpy.data.objects.new(name, self.data)
        coll.objects.link(self.ob)

    def capsule(self, p0, p1, r):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        el = self.data.elements.new(type="CAPSULE")
        el.co = (p0 + p1) / 2
        el.radius = r / VISIBLE
        el.size_x = max(1e-4, d.length / 2)
        if d.length > 1e-6:
            el.rotation = Vector((1.0, 0.0, 0.0)).rotation_difference(d.normalized())

    def ellipsoid(self, c, r, size, rot=None):
        el = self.data.elements.new(type="ELLIPSOID")
        el.co = c
        el.radius = r / VISIBLE
        el.size_x, el.size_y, el.size_z = size
        if rot is not None:
            el.rotation = rot.to_quaternion()


def rot(yaw=0.0, pitch=0.0, roll=0.0):
    """Orientation of a part whose front faces -y: yaw turns it (90 faces +x), pitch looks down."""
    return Matrix.Rotation(math.radians(yaw), 3, "Z") @ Matrix.Rotation(math.radians(pitch), 3, "X") @ Matrix.Rotation(math.radians(roll), 3, "Y")


def placed(mb, coll, origin, orientation, smooth=True, scale=1.0):
    ob = mb.build(coll, smooth=smooth)
    ob.matrix_world = Matrix.Translation(origin) @ orientation.to_4x4() @ Matrix.Scale(scale, 4)
    return ob


def build_figure(key, style, m, pose, coll):
    """Build the whole figure for one pose. pose: joints (world, metres, root at the floor under the
    hips), torso orientation, head orientation, eyes open, mouth open."""
    j = pose["joints"]
    t_rot = pose["torso"]
    h_rot = pose["head"]
    kind = style["top"]["kind"]
    rolled = style["top"].get("rolled", False)

    top = Blobs(f"{key}_top", m["top"], coll)
    top.ellipsoid(j["chest"], 0.1, (1.8, 1.1, 1.5), t_rot)
    top.ellipsoid(j["waist"], 0.1, (1.5, 1.0, 1.25), t_rot)
    top.capsule(j["shoulderL"], j["shoulderR"], 0.064)
    if kind == "hoodie":
        top.ellipsoid(j["chest"] + t_rot @ Vector((0.0, 0.1, 0.15)), 0.08, (1.4, 0.8, 0.9), t_rot)
    if kind == "labcoat":
        for s in ("L", "R"):
            top.capsule(j[f"hip{s}"], j[f"hip{s}"] + (j[f"knee{s}"] - j[f"hip{s}"]) * 0.55, 0.086)
    sleeve = Blobs(f"{key}_sleeve", m["sleeve"], coll) if m["sleeve"] is not m["top"] else top
    skin = Blobs(f"{key}_skin", m["skin"], coll)
    for s in ("L", "R"):
        sh, el, wr = j[f"shoulder{s}"], j[f"elbow{s}"], j[f"wrist{s}"]
        sleeve.capsule(sh, el, 0.052)
        if rolled:
            sleeve.capsule(el, el + (wr - el) * 0.2, 0.049)
            skin.capsule(el + (wr - el) * 0.15, wr, 0.036)
        else:
            sleeve.capsule(el, wr + (el - wr) * 0.12, 0.045)
        hand_dir = (wr - el).normalized() if (wr - el).length > 1e-6 else Vector((0, 0, -1))
        skin.ellipsoid(wr + hand_dir * 0.045, 0.036, (0.9, 0.9, 1.3), Vector((0, 0, 1)).rotation_difference(hand_dir).to_matrix())
    skin.capsule(j["neck"] - t_rot @ Vector((0, 0, 0.05)), j["neck"] + h_rot @ Vector((0, 0, 0.06)), 0.048)
    skin.ellipsoid(j["head"], 0.112, (1.0, 1.05, 1.22), h_rot)
    for sx in (-1, 1):
        skin.ellipsoid(j["head"] + h_rot @ Vector((sx * 0.112, 0.01, -0.01)), 0.025, (0.6, 1.0, 1.2), h_rot)

    legs = Blobs(f"{key}_legs", m["legs"], coll)
    legs.ellipsoid(j["pelvis"], 0.1, (1.7, 1.35, 0.9), t_rot)
    shoes = Blobs(f"{key}_shoes", m["shoes"], coll)
    for s in ("L", "R"):
        legs.capsule(j[f"hip{s}"], j[f"knee{s}"], 0.076)
        legs.capsule(j[f"knee{s}"], j[f"ankle{s}"], 0.062)
        foot_rot = pose.get("feet", t_rot)
        shoes.ellipsoid(j[f"ankle{s}"] + foot_rot @ Vector((0, -0.07, -0.045)), 0.066, (0.85, 1.9, 0.6), foot_rot)

    build_torso_front(key, style, m, j["chest"], t_rot, coll)
    build_face(key, m, j["head"], h_rot, pose.get("eyes", True), pose.get("mouth", False), coll)
    build_hair(key, style["hair"], m, j["head"], h_rot, coll)
    for acc in style.get("accessories", []):
        build_accessory(key, acc, m, j, t_rot, h_rot, coll)


def build_torso_front(key, style, m, chest, t_rot, coll):
    """Collar, lapels and tie, in the torso's own frame (origin at the chest joint)."""
    kind = style["top"]["kind"]
    front = MB(f"{key}_front")
    cy = -0.106
    if kind in ("blazer", "labcoat", "cardigan", "shirt", "vest", "hoodie", "flightsuit"):
        front.quad([(-0.07, cy, 0.112), (0.07, cy, 0.112), (0.0, cy - 0.004, -0.02)], m["inner"])
    if "tie" in m:
        front.box(-0.013, 0.013, cy - 0.012, cy - 0.006, -0.06, 0.1, m["tie"])
    if kind in ("blazer", "labcoat", "cardigan"):
        for s in (-1, 1):
            front.quad([(s * 0.07, cy - 0.003, 0.112), (s * 0.018, cy - 0.007, -0.03), (s * 0.05, cy - 0.005, -0.03)], m["top"])
    if kind == "hoodie":
        for sx in (-0.025, 0.025):
            front.box(sx - 0.003, sx + 0.003, cy - 0.01, cy - 0.005, -0.02, 0.09, principled(f"{key}_string", "#e5e7eb", rough=0.6))
    if not front.bm.faces:
        front.bm.free()
        return
    placed(front, coll, chest, t_rot, smooth=False)


def build_face(key, m, head, h_rot, eyes_open, mouth_open, coll):
    fy = -0.113
    face = MB(f"{key}_face")
    for s in (-1, 1):
        if eyes_open:
            face.sphere((s * 0.036, fy + 0.006, 0.012), 0.013, m["eye"], seg=12, rings=8, scale=(0.9, 0.45, 1.15))
            face.sphere((s * 0.036 - 0.004, fy - 0.001, 0.018), 0.0035, m["catch"], seg=6, rings=4)
        else:
            face.box(s * 0.036 - 0.013, s * 0.036 + 0.013, fy - 0.001, fy + 0.008, 0.008, 0.013, m["eye"])
        face.box(s * 0.02, s * 0.056, fy, fy + 0.012, 0.04, 0.047, m["brow"])
    face.sphere((0.0, fy - 0.004, -0.018), 0.012, m["skin"], seg=10, rings=6, scale=(0.8, 0.7, 1.0))
    if mouth_open:
        face.sphere((0.0, fy + 0.006, -0.056), 0.012, m["mouth"], seg=10, rings=6, scale=(1.3, 0.5, 0.9))
    else:
        face.box(-0.018, 0.018, fy + 0.004, fy + 0.012, -0.058, -0.052, m["lips"])
    placed(face, coll, head, h_rot, scale=HEAD_SCALE)


def shell(mb, centre, scale, keep, mat, seg=32, rings=20):
    xf = Matrix.Translation(centre) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    ret = bmesh.ops.create_uvsphere(mb.bm, u_segments=seg, v_segments=rings, radius=HEAD_R, matrix=xf)
    k = mb.mi(mat)
    for f in {f for v in ret["verts"] for f in v.link_faces}:
        f.material_index = k
    bmesh.ops.delete(mb.bm, geom=[v for v in ret["verts"] if not keep(v.co - Vector(centre))], context="VERTS")


def _spike(mb, base, tip, width, mat):
    d = (tip - base).normalized()
    t = d.cross(Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))).normalized() * width
    s = d.cross(t).normalized() * width
    ring = [mb.bm.verts.new(base + t), mb.bm.verts.new(base + s), mb.bm.verts.new(base - t), mb.bm.verts.new(base - s)]
    apex = mb.bm.verts.new(tip)
    k = mb.mi(mat)
    for i in range(4):
        mb.bm.faces.new((ring[i], ring[(i + 1) % 4], apex)).material_index = k


def build_hair(key, hair_style, m, head, h_rot, coll):
    """Hair in the head's frame (origin at the head centre, face towards -y)."""
    kind = hair_style["style"]
    mat = m["hair"]
    mb = MB(f"{key}_hairmesh")
    c = Vector((0.0, 0.008, 0.012))

    def face_open(p, fringe_z):
        return not (p.y < -0.04 and p.z < fringe_z and abs(p.x) < 0.085)

    def nape(keep):
        return lambda p: keep(p) or (p.y > 0.01 and p.z > -0.09 and face_open(p, 0.05))

    if kind in ("bob", "bob_short"):
        low = -0.1 if kind == "bob" else -0.06
        shell(mb, c, (1.12, 1.08, 1.06), lambda p: face_open(p, 0.03) and p.z > low, mat)
        mb.sphere((-0.035, -0.1, 0.07), 0.05, mat, seg=14, rings=8, scale=(1.5, 0.45, 0.55))
    elif kind == "short":
        shell(mb, c, (1.06, 1.06, 1.04), nape(lambda p: face_open(p, 0.05) and p.z > -0.01), mat)
        if "temples" in m:
            for sx in (-1, 1):
                mb.box(sx * 0.104, sx * 0.116, -0.03, 0.03, -0.01, 0.04, m["temples"])
    elif kind in ("high_bun", "low_bun"):
        shell(mb, c, (1.06, 1.06, 1.04), nape(lambda p: face_open(p, 0.05) and p.z > -0.03), mat)
        if kind == "high_bun":
            mb.sphere((0.0, 0.03, 0.15), 0.046, mat, seg=16, rings=10)
        else:
            mb.sphere((0.0, 0.12, -0.035), 0.044, mat, seg=16, rings=10)
    elif kind == "long":
        shell(mb, c, (1.1, 1.1, 1.05), lambda p: face_open(p, 0.04), mat)
        mb.box(-0.1, 0.1, 0.04, 0.1, -0.3, 0.0, mat)
        for sx in (-1, 1):
            lock = m["streak"] if (sx > 0 and "streak" in m) else mat
            mb.box(sx * 0.08, sx * 0.112, -0.055, 0.045, -0.2, 0.02, lock)
    elif kind == "spiky":
        shell(mb, c, (1.05, 1.05, 1.02), lambda p: face_open(p, 0.05) and (p.z > 0.0 or p.y > 0.02), mat)
        rng = random.Random(5)
        for _ in range(22):
            a = rng.uniform(0, math.tau)
            elev = rng.uniform(0.45, 1.35)
            d = Vector((math.cos(a) * math.cos(elev), math.sin(a) * math.cos(elev), math.sin(elev)))
            if d.y < -0.55 and d.z < 0.7:
                continue
            _spike(mb, d * HEAD_R * 0.95, d * (HEAD_R + rng.uniform(0.035, 0.06)) + Vector((0, 0, 0.012)), 0.022, mat)
    else:  # tousled
        shell(mb, c, (1.08, 1.08, 1.06), nape(lambda p: face_open(p, 0.045) and p.z > -0.02), mat)
        rng = random.Random(11)
        for _ in range(16):
            a = rng.uniform(0, math.tau)
            elev = rng.uniform(0.3, 1.3)
            d = Vector((math.cos(a) * math.cos(elev), math.sin(a) * math.cos(elev) * 0.9, math.sin(elev)))
            if d.y < -0.55 and d.z < 0.5:
                continue
            mb.sphere(tuple(d * (HEAD_R + 0.008)), rng.uniform(0.024, 0.034), mat, seg=10, rings=7)
    placed(mb, coll, head, h_rot, scale=HEAD_SCALE)


def build_accessory(key, acc, m, j, t_rot, h_rot, coll):
    kind = acc["kind"]
    mat = m[f"acc_{kind}"]
    fy = -0.113
    if kind in ("round_glasses", "glasses", "headphones", "headset", "earrings", "stubble"):
        mb = MB(f"{key}_{kind}")
        if kind in ("round_glasses", "glasses"):
            r = 0.024 if kind == "round_glasses" else 0.022
            lens = principled(f"{key}_lens", "#ffffff", rough=0.05, alpha=0.18)
            for s in (-1, 1):
                cx, cz = s * 0.036, 0.012
                for i in range(14):
                    a0, a1 = i / 14 * math.tau, (i + 1) / 14 * math.tau
                    p0 = Vector((cx + math.cos(a0) * r, fy - 0.016, cz + math.sin(a0) * r))
                    p1 = Vector((cx + math.cos(a1) * r, fy - 0.016, cz + math.sin(a1) * r))
                    mb.box(min(p0.x, p1.x) - 0.002, max(p0.x, p1.x) + 0.002, fy - 0.018, fy - 0.014, min(p0.z, p1.z) - 0.002, max(p0.z, p1.z) + 0.002, mat)
                mb.cyl_y(cx, fy - 0.015, cz, 0.002, r * 0.92, lens, seg=14)
                mb.box(s * 0.06, s * 0.108, fy - 0.016, fy + 0.06, cz + 0.008, cz + 0.013, mat)
            mb.box(-0.012, 0.012, fy - 0.018, fy - 0.014, 0.016, 0.02, mat)
        elif kind == "headphones":
            for sx in (-1, 1):
                mb.cyl_x(sx * 0.118, 0.0, -0.005, 0.034, 0.042, mat, seg=16)
            pts = [Vector((math.cos(a) * 0.12, 0.0, math.sin(a) * 0.14)) for a in [i / 12 * math.pi for i in range(13)]]
            for p0, p1 in zip(pts, pts[1:]):
                mb.box(min(p0.x, p1.x) - 0.009, max(p0.x, p1.x) + 0.009, -0.01, 0.01, min(p0.z, p1.z) - 0.009, max(p0.z, p1.z) + 0.009, mat)
        elif kind == "headset":
            body = principled(f"{key}_headset_body", "#16171c", rough=0.35)
            mb.cyl_x(-0.118, 0.0, -0.005, 0.03, 0.035, body, seg=14)
            pts = [Vector((math.cos(a) * 0.118, 0.0, math.sin(a) * 0.135)) for a in [i / 12 * math.pi for i in range(13)]]
            for p0, p1 in zip(pts, pts[1:]):
                mb.box(min(p0.x, p1.x) - 0.006, max(p0.x, p1.x) + 0.006, -0.008, 0.008, min(p0.z, p1.z) - 0.006, max(p0.z, p1.z) + 0.006, body)
            mb.box(-0.115, -0.05, fy + 0.01, fy + 0.02, -0.07, -0.062, body)
            mb.sphere((-0.045, fy + 0.005, -0.066), 0.01, mat, seg=8, rings=6)
        elif kind == "earrings":
            for s in (-1, 1):
                mb.sphere((s * 0.108, 0.0, -0.05), 0.008, mat, seg=8, rings=6)
        elif kind == "stubble":
            mb.sphere((0.0, fy + 0.035, -0.06), 0.05, principled(f"{key}_stubble", acc["color"], rough=0.8, alpha=0.2), seg=16, rings=8, scale=(1.3, 0.45, 0.55))
        placed(mb, coll, j["head"], h_rot, scale=HEAD_SCALE)
        return
    mb = MB(f"{key}_{kind}")
    cy = -0.108
    if kind == "badge":
        mb.box(0.045, 0.075, cy - 0.006, cy, 0.02, 0.06, mat)
    elif kind == "pen_chain":
        mb.box(-0.003, 0.003, cy - 0.006, cy - 0.002, -0.03, 0.1, mat)
    elif kind == "belt":
        mb.box(-0.14, 0.14, -0.1, 0.1, -0.215, -0.185, mat)
    else:
        mb.bm.free()
        return
    placed(mb, coll, j["chest"], t_rot, smooth=False)


# ----------------------------------------------------------------------------- poses


def lean_about(p, pivot, degrees):
    """Tilt a point about the pelvis: positive leans towards the viewer (-y)."""
    a = math.radians(degrees)
    dy, dz = p.y - pivot.y, p.z - pivot.z
    return Vector((p.x, pivot.y + dy * math.cos(a) - dz * math.sin(a), pivot.z + dy * math.sin(a) + dz * math.cos(a)))


def seated(arms, lean=0.0, head=(0.0, 0.0, 0.0), eyes=True, mouth=False):
    j = {
        "pelvis": Vector((0.0, 0.08, 0.53)),
        "waist": Vector((0.0, 0.08, 0.68)),
        "chest": Vector((0.0, 0.07, 0.86)),
        "neck": Vector((0.0, 0.06, 1.0)),
        "head": Vector((0.0, 0.04, 1.14)),
        "shoulderL": Vector((0.185, 0.07, 0.955)),
        "shoulderR": Vector((-0.185, 0.07, 0.955)),
        "hipL": Vector((0.1, 0.06, 0.5)),
        "hipR": Vector((-0.1, 0.06, 0.5)),
        "kneeL": Vector((0.11, -0.36, 0.52)),
        "kneeR": Vector((-0.11, -0.36, 0.52)),
        "ankleL": Vector((0.11, -0.4, 0.09)),
        "ankleR": Vector((-0.11, -0.4, 0.09)),
    }
    pivot = j["pelvis"]
    for name in ("waist", "chest", "neck", "head", "shoulderL", "shoulderR"):
        j[name] = lean_about(j[name], pivot, lean)
    for name, p in arms.items():
        j[name] = Vector(p)
    return {"joints": j, "torso": rot(pitch=lean), "head": rot(pitch=lean + head[0], yaw=head[1], roll=head[2]), "eyes": eyes, "mouth": mouth, "feet": rot()}


def arms_typing(phase):
    lift = 0.012 * math.sin(phase * math.pi)
    return {
        "elbowL": (0.2, -0.16, 0.8), "wristL": (0.11, -0.42, 0.79 + lift),
        "elbowR": (-0.2, -0.16, 0.8), "wristR": (-0.11, -0.42, 0.79 - lift),
    }


ARMS_REST = {"elbowL": (0.22, -0.12, 0.8), "wristL": (0.16, -0.38, 0.78), "elbowR": (-0.22, -0.12, 0.8), "wristR": (-0.16, -0.38, 0.78)}


def standing(arms=None, head=(0.0, 0.0, 0.0), eyes=True, mouth=False):
    j = {
        "pelvis": Vector((0.0, 0.02, 0.95)),
        "waist": Vector((0.0, 0.02, 1.1)),
        "chest": Vector((0.0, 0.02, 1.3)),
        "neck": Vector((0.0, 0.02, 1.46)),
        "head": Vector((0.0, 0.01, 1.6)),
        "shoulderL": Vector((0.185, 0.03, 1.41)),
        "shoulderR": Vector((-0.185, 0.03, 1.41)),
        "elbowL": Vector((0.22, 0.03, 1.13)),
        "elbowR": Vector((-0.22, 0.03, 1.13)),
        "wristL": Vector((0.23, 0.02, 0.88)),
        "wristR": Vector((-0.23, 0.02, 0.88)),
        "hipL": Vector((0.1, 0.02, 0.92)),
        "hipR": Vector((-0.1, 0.02, 0.92)),
        "kneeL": Vector((0.1, 0.0, 0.5)),
        "kneeR": Vector((-0.1, 0.0, 0.5)),
        "ankleL": Vector((0.1, 0.02, 0.09)),
        "ankleR": Vector((-0.1, 0.02, 0.09)),
    }
    for name, p in (arms or {}).items():
        j[name] = Vector(p)
    return {"joints": j, "torso": rot(), "head": rot(pitch=head[0], yaw=head[1], roll=head[2]), "eyes": eyes, "mouth": mouth, "feet": rot()}


def walking(i, frames=8):
    """Walking to the right (+x), seen side-on: legs and arms swing in the x-z plane."""
    t = i / frames * math.tau
    bob = 0.02 * abs(math.cos(t))
    yaw = rot(yaw=90.0)
    j = {
        "pelvis": Vector((0.0, 0.0, 0.95 + bob)),
        "waist": Vector((0.0, 0.0, 1.1 + bob)),
        "chest": Vector((0.02, 0.0, 1.3 + bob)),
        "neck": Vector((0.03, 0.0, 1.46 + bob)),
        "head": Vector((0.04, 0.0, 1.6 + bob)),
    }
    for s, side in ((1, "L"), (-1, "R")):
        swing = math.radians(26.0) * math.sin(t) * s
        bend = math.radians(max(0.0, 42.0 * math.sin(t * 1.0 + 1.2) * s))
        hip = Vector((0.0, -s * 0.1, 0.92 + bob))
        knee = hip + Vector((math.sin(swing) * 0.44, 0.0, -math.cos(swing) * 0.44))
        ankle = knee + Vector((math.sin(swing - bend) * 0.42, 0.0, -math.cos(swing - bend) * 0.42))
        j[f"hip{side}"], j[f"knee{side}"], j[f"ankle{side}"] = hip, knee, ankle
        arm = -swing * 0.85
        shoulder = Vector((0.02, -s * 0.185, 1.41 + bob))
        elbow = shoulder + Vector((math.sin(arm) * 0.28, 0.0, -math.cos(arm) * 0.28))
        wrist = elbow + Vector((math.sin(arm + math.radians(14)) * 0.26, 0.0, -math.cos(arm + math.radians(14)) * 0.26))
        j[f"shoulder{side}"], j[f"elbow{side}"], j[f"wrist{side}"] = shoulder, elbow, wrist
    return {"joints": j, "torso": yaw, "head": yaw, "eyes": True, "mouth": False, "feet": yaw}


SEATED = {
    "sit_type": [seated(arms_typing(k / 2), lean=4.0, head=(8.0, 0.0, 0.0)) for k in range(4)],
    "sit_idle": [seated(ARMS_REST), seated(ARMS_REST, eyes=False)],
    "sit_think": [
        seated({**ARMS_REST, "elbowR": (-0.17, -0.2, 0.84), "wristR": (-0.05, -0.1, 1.03)}, head=(-4.0, 0.0, 6.0)),
        seated({**ARMS_REST, "elbowR": (-0.17, -0.2, 0.84), "wristR": (-0.05, -0.1, 1.03)}, head=(-6.0, 0.0, -3.0)),
    ],
    "sit_talk": [
        seated({**ARMS_REST, "elbowL": (0.28, -0.12, 0.84), "wristL": (0.3, -0.3, 0.96)}, head=(0.0, -6.0, 3.0), mouth=True),
        seated({**ARMS_REST, "elbowL": (0.27, -0.12, 0.82), "wristL": (0.26, -0.33, 0.9)}, head=(0.0, 5.0, -2.0)),
    ],
    "sit_sleep": [
        seated({"elbowL": (0.2, -0.08, 0.8), "wristL": (-0.06, -0.06, 0.84), "elbowR": (-0.2, -0.08, 0.8), "wristR": (0.06, -0.06, 0.86)}, lean=-8.0, head=(20.0, 0.0, 0.0), eyes=False),
        seated({"elbowL": (0.2, -0.08, 0.8), "wristL": (-0.06, -0.06, 0.84), "elbowR": (-0.2, -0.08, 0.8), "wristR": (0.06, -0.06, 0.86)}, lean=-8.0, head=(23.0, 0.0, 2.0), eyes=False),
    ],
    "sit_error": [
        seated({"elbowL": (0.26, -0.02, 1.12), "wristL": (0.1, 0.0, 1.24), "elbowR": (-0.26, -0.02, 1.12), "wristR": (-0.1, 0.0, 1.24)}, head=(-4.0, 0.0, 5.0), mouth=True),
        seated({"elbowL": (0.26, -0.02, 1.1), "wristL": (0.11, 0.0, 1.22), "elbowR": (-0.26, -0.02, 1.1), "wristR": (-0.11, 0.0, 1.22)}, head=(-4.0, 0.0, -5.0)),
    ],
}

STANDING = {
    "stand_idle": [standing(), standing(eyes=False)],
    "stand_react": [
        standing({"elbowR": (-0.3, -0.02, 1.52), "wristR": (-0.35, -0.05, 1.8)}, head=(-8.0, -15.0, 0.0), mouth=True),
        standing({"elbowR": (-0.3, -0.02, 1.5), "wristR": (-0.38, -0.05, 1.75)}, head=(-10.0, -18.0, 0.0)),
    ],
}


# ----------------------------------------------------------------------------- rendering


def clear(coll):
    for ob in list(coll.all_objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if isinstance(data, bpy.types.MetaBall):
            bpy.data.metaballs.remove(data)
        elif isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def render_person(scene, key, style, palette, out_dir, employee):
    m = materials_for(key, style, palette)
    coll = bpy.data.collections.new(key)
    scene.collection.children.link(coll)
    index = []
    sets = []
    if employee:
        sets += [(f"{anim}_front", poses) for anim, poses in SEATED.items()]
    sets += list(STANDING.items())
    sets.append(("walk_right", [walking(i) for i in range(8)]))
    for anim, poses in sets:
        for i, pose in enumerate(poses):
            build_figure(key, style, m, pose, coll)
            bpy.context.view_layer.update()
            name = f"{key}__{anim}__{i:02d}.png"
            scene.render.filepath = os.path.join(out_dir, name)
            bpy.ops.render.render(write_still=True)
            index.append({"file": name, "anim": anim, "frame": i})
            clear(coll)
    bpy.data.collections.remove(coll)
    return index


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
        "seat_facing": "front",
    }


def main():
    a = args()
    scene = setup_scene(a)
    bible = {c["role"]: c for c in json.load(open(os.path.join(ROOT, "art-source", "character_bible.json"), encoding="utf-8"))}
    styles = json.load(open(os.path.join(HERE, "characters_style.json"), encoding="utf-8"))["employees"]
    only = {s for s in a.only.split(",") if s}
    os.makedirs(a.out, exist_ok=True)
    manifest = {"frame": {"w": FRAME_W, "h": FRAME_H, "pivot": PIVOT, "scale": a.scale}, "characters": {}}
    jobs = []
    if a.pedestrians:
        jobs = [(f"ped{i:02d}", pedestrian_style(i), {}, None) for i in range(12)]
    else:
        for role, style in styles.items():
            if not only or style["sprite"] in only:
                jobs.append((style["sprite"], style, bible.get(role, {}).get("palette", {}), role))
    for key, style, palette, role in jobs:
        frames = render_person(scene, key, style, palette, a.out, employee=not a.pedestrians)
        manifest["characters"][key] = {
            "role": role,
            "canonical_name": bible.get(role, {}).get("canonical_name") if role else None,
            "seat_facing": "front",
            "frames": frames,
        }
        print(f"AMN_PERSON {key} frames={len(frames)}")
    name = "pedestrians.json" if a.pedestrians else "characters.json"
    with open(os.path.join(a.out, name), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)


main()
