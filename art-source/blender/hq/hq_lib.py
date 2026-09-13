"""Shared helpers for the AMN-AI headquarters scene.

Projection: an orthographic camera pitched 10 degrees down looks at the building front. World
pixels (1600 x 840 at scale 1) are the coordinates the web canvas uses, so every object is placed
from the pixel rows and columns measured on the reference and every exported anchor is projected
back with `project`, never guessed.
"""

import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

PPM = 28.0  # world pixels per metre at scale 1
THETA = math.radians(10.0)
SIN = math.sin(THETA)
COS = math.cos(THETA)
WORLD_W = 1600
WORLD_H = 840
CX = WORLD_W / 2
CY = WORLD_H / 2
GROUND_ROW = 655.0  # screen row of the ground-floor front edge (z = 0, y = 0)
ZC = (GROUND_ROW - CY) / PPM / COS
BACK_WALL = 2.4  # depth of an upper-floor room's back wall
TEXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures")


def X(px):
    """World pixel column -> Blender x."""
    return (px - CX) / PPM


def M(px):
    """A horizontal length in world pixels -> metres."""
    return px / PPM


def Z(row, y=0.0):
    """Height of a point at depth y that appears on screen row `row`."""
    v = (CY - row) / PPM
    return ZC + (v - y * SIN) / COS


def Y(row, z=0.0):
    """Depth of a point at height z that appears on screen row `row`."""
    v = (CY - row) / PPM
    return (v - (z - ZC) * COS) / SIN


def project(p):
    """Blender point -> (column, row) in world pixels."""
    v = p[1] * SIN + (p[2] - ZC) * COS
    return (CX + p[0] * PPM, CY - v * PPM)


# ----------------------------------------------------------------------------- colour


def lin(hex_color, alpha=1.0):
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        u = int(h[i : i + 2], 16) / 255.0
        out.append(u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2], alpha)


# ----------------------------------------------------------------------------- collections


def collection(name, parent=None):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


# ----------------------------------------------------------------------------- materials

MATS = {}


def _principled(m):
    return m.node_tree.nodes["Principled BSDF"]


def principled(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0, alpha=1.0, coat=0.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = _principled(m)
    b.inputs["Base Color"].default_value = lin(color)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat:
        b.inputs["Coat Weight"].default_value = coat
    if emit:
        b.inputs["Emission Color"].default_value = lin(emit)
        b.inputs["Emission Strength"].default_value = strength
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
    MATS[name] = m
    return m


def emissive(name, color, strength):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(_principled(m))
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = lin(color)
    e.inputs["Strength"].default_value = strength
    nt.links.new(e.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    MATS[name] = m
    return m


class Graph:
    """Tiny node-graph builder for procedural materials."""

    def __init__(self, name):
        self.m = bpy.data.materials.new(name)
        self.m.use_nodes = True
        self.nt = self.m.node_tree
        self.bsdf = _principled(self.m)
        MATS[name] = self.m

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, out, inp):
        self.nt.links.new(out, inp)

    def ramp(self, fac_socket, stops, constant=False):
        r = self.node("ShaderNodeValToRGB")
        if constant:
            r.color_ramp.interpolation = "CONSTANT"
        els = r.color_ramp.elements
        els[0].position = stops[0][0]
        els[0].color = lin(stops[0][1]) if isinstance(stops[0][1], str) else stops[0][1]
        els[1].position = stops[-1][0]
        els[1].color = lin(stops[-1][1]) if isinstance(stops[-1][1], str) else stops[-1][1]
        for pos, col in stops[1:-1]:
            e = els.new(pos)
            e.color = lin(col) if isinstance(col, str) else col
        self.link(fac_socket, r.inputs["Fac"])
        return r

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.link(v, n.inputs[i])
        return n.outputs[0]

    def vmul(self, a, b):
        n = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(a, n.inputs[0])
        if isinstance(b, (tuple, list)):
            n.inputs[1].default_value = b[:3]
        else:
            self.link(b, n.inputs[1])
        return n.outputs["Vector"]

    def vadd(self, a, b):
        n = self.node("ShaderNodeVectorMath", operation="ADD")
        self.link(a, n.inputs[0])
        self.link(b, n.inputs[1])
        return n.outputs["Vector"]

    def coords(self, kind="Object"):
        tc = self.node("ShaderNodeTexCoord")
        sep = self.node("ShaderNodeSeparateXYZ")
        self.link(tc.outputs[kind], sep.inputs[0])
        return sep

    def combine(self, x=None, y=None, z=None):
        c = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            if v is not None:
                self.link(v, c.inputs[i])
        return c.outputs[0]


def panel_material(name, base, seam, spacing, rough=0.55, seam_width=0.06, vertical=True, gloss=0.0):
    """Wall panels with regular seams (vertical grooves by default)."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords()
    axis = sep.outputs["X"] if vertical else sep.outputs["Z"]
    fr = g.math("FRACT", g.math("DIVIDE", axis, spacing))
    edge = g.math("LESS_THAN", fr, seam_width)
    noisy = g.node("ShaderNodeTexNoise")
    noisy.inputs["Scale"].default_value = 3.0
    noisy.inputs["Detail"].default_value = 4.0
    tone = g.ramp(noisy.outputs["Fac"], [(0.3, (0.88, 0.88, 0.88, 1.0)), (0.7, (1.1, 1.1, 1.1, 1.0))])
    col = g.ramp(edge, [(0.0, base), (0.5, seam)], constant=True)
    g.link(g.vmul(col.outputs["Color"], tone.outputs["Color"]), g.bsdf.inputs["Base Color"])
    g.bsdf.inputs["Roughness"].default_value = rough
    if gloss:
        g.bsdf.inputs["Coat Weight"].default_value = gloss
    bump = g.node("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.01
    g.link(g.math("SUBTRACT", 1.0, edge), bump.inputs["Height"])
    g.link(bump.outputs["Normal"], g.bsdf.inputs["Normal"])
    return g.m


def brick_material(name, c1, c2, mortar, brick_w=0.5, row_h=0.22, scale=1.0, rough=0.8, bump=0.4):
    """Bricks or stone tiles on a wall that faces the camera (x/z plane)."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords()
    vec = g.combine(sep.outputs["X"], sep.outputs["Z"])
    b = g.node("ShaderNodeTexBrick", offset=0.5)
    b.inputs["Color1"].default_value = lin(c1)
    b.inputs["Color2"].default_value = lin(c2)
    b.inputs["Mortar"].default_value = lin(mortar)
    b.inputs["Scale"].default_value = scale
    b.inputs["Mortar Size"].default_value = 0.012
    b.inputs["Brick Width"].default_value = brick_w
    b.inputs["Row Height"].default_value = row_h
    g.link(vec, b.inputs["Vector"])
    g.link(b.outputs["Color"], g.bsdf.inputs["Base Color"])
    g.bsdf.inputs["Roughness"].default_value = rough
    bp = g.node("ShaderNodeBump")
    bp.inputs["Strength"].default_value = bump
    bp.inputs["Distance"].default_value = 0.02
    g.link(g.math("SUBTRACT", 1.0, b.outputs["Fac"]), bp.inputs["Height"])
    g.link(bp.outputs["Normal"], g.bsdf.inputs["Normal"])
    return g.m


def windows_material(name, wall, lit_ratio=0.35, win_w=0.9, win_h=1.3, strength=6.0, warm=True, rough=0.35):
    """A tower facade: a grid of windows, a share of them lit (for the skyline)."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords()
    vec = g.combine(sep.outputs["X"], sep.outputs["Z"])
    b = g.node("ShaderNodeTexBrick", offset=0.0, offset_frequency=1, squash=1.0, squash_frequency=1)
    b.inputs["Color1"].default_value = (0, 0, 0, 1)
    b.inputs["Color2"].default_value = (1, 1, 1, 1)
    b.inputs["Mortar"].default_value = (0, 0, 0, 1)
    b.inputs["Scale"].default_value = 1.0
    b.inputs["Mortar Size"].default_value = min(win_w, win_h) * 0.32
    b.inputs["Mortar Smooth"].default_value = 0.0
    b.inputs["Bias"].default_value = 0.0
    b.inputs["Brick Width"].default_value = win_w
    b.inputs["Row Height"].default_value = win_h
    g.link(vec, b.inputs["Vector"])
    cut = 1.0 - lit_ratio
    stops = [(0.0, "#000000"), (cut, "#4a2e16" if warm else "#1c2c4a"), (cut + lit_ratio * 0.35, "#ffb35c" if warm else "#9cc4ff"), (cut + lit_ratio * 0.8, "#ffe0a8"), (0.999, "#ffe9c4" if warm else "#cfe2ff")]
    lit = g.ramp(b.outputs["Color"], stops, constant=True)
    mask = g.ramp(b.outputs["Fac"], [(0.0, "#ffffff"), (0.5, "#000000")], constant=True)
    emit = g.vmul(lit.outputs["Color"], mask.outputs["Color"])
    g.link(emit, g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    base = g.ramp(b.outputs["Fac"], [(0.0, "#10151f"), (0.5, wall)], constant=True)
    g.link(base.outputs["Color"], g.bsdf.inputs["Base Color"])
    g.bsdf.inputs["Roughness"].default_value = rough
    g.bsdf.inputs["Metallic"].default_value = 0.2
    return g.m


def screen_material(name, color, strength=1.8, lines=26.0, dim="#081020"):
    """A monitor showing a user interface: bright rows of text-like marks."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    tc = g.node("ShaderNodeTexCoord")
    mp = g.node("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (4.0, lines, 1.0)
    g.link(tc.outputs["UV"], mp.inputs["Vector"])
    n = g.node("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 2.5
    n.inputs["Detail"].default_value = 1.0
    g.link(mp.outputs["Vector"], n.inputs["Vector"])
    col = g.ramp(n.outputs["Fac"], [(0.0, dim), (0.52, dim), (0.56, color), (1.0, "#ffffff")], constant=False)
    g.link(col.outputs["Color"], g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    g.bsdf.inputs["Base Color"].default_value = lin("#05070c")
    g.bsdf.inputs["Roughness"].default_value = 0.15
    return g.m


def led_material(name, on="#4ade80", accent="#fbbf24", strength=8.0, cell=0.05):
    """Server rack front: a grid of small LEDs, most green, a few amber, some dark."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords()
    vec = g.combine(sep.outputs["X"], sep.outputs["Z"])
    b = g.node("ShaderNodeTexBrick", offset=0.0)
    b.inputs["Color1"].default_value = (0, 0, 0, 1)
    b.inputs["Color2"].default_value = (1, 1, 1, 1)
    b.inputs["Mortar"].default_value = (0, 0, 0, 1)
    b.inputs["Scale"].default_value = 1.0
    b.inputs["Mortar Size"].default_value = cell * 0.35
    b.inputs["Brick Width"].default_value = cell * 1.6
    b.inputs["Row Height"].default_value = cell
    g.link(vec, b.inputs["Vector"])
    lit = g.ramp(b.outputs["Color"], [(0.0, "#000000"), (0.45, on), (0.9, accent), (0.97, "#60a5fa")], constant=True)
    mask = g.ramp(b.outputs["Fac"], [(0.0, "#ffffff"), (0.5, "#000000")], constant=True)
    g.link(g.vmul(lit.outputs["Color"], mask.outputs["Color"]), g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    g.bsdf.inputs["Base Color"].default_value = lin("#0b0f14")
    g.bsdf.inputs["Roughness"].default_value = 0.3
    return g.m


def asphalt_material(name, wet=1.0):
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    n = g.node("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 0.18
    n.inputs["Detail"].default_value = 6.0
    n.inputs["Roughness"].default_value = 0.6
    rough = g.ramp(n.outputs["Fac"], [(0.35, (0.5, 0.5, 0.5, 1)), (0.62, (0.85, 0.85, 0.85, 1))])
    if wet <= 0:
        rough.color_ramp.elements[0].color = (0.7, 0.7, 0.7, 1)
        rough.color_ramp.elements[1].color = (0.9, 0.9, 0.9, 1)
    g.link(rough.outputs["Color"], g.bsdf.inputs["Roughness"])
    grain = g.node("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 60.0
    col = g.ramp(grain.outputs["Fac"], [(0.3, "#11141f"), (0.7, "#202538")])
    g.link(col.outputs["Color"], g.bsdf.inputs["Base Color"])
    g.bsdf.inputs["Specular IOR Level"].default_value = 0.25
    return g.m


def window_view_material(name, top="#34457a", mid="#8f6a86", horizon="#f0a070", strength=1.6):
    """What a room window shows: the evening sky over the city."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords("UV")
    col = g.ramp(sep.outputs["Y"], [(0.0, "#1a2340"), (0.25, horizon), (0.55, mid), (1.0, top)])
    g.link(col.outputs["Color"], g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    g.bsdf.inputs["Base Color"].default_value = lin("#0a0d16")
    g.bsdf.inputs["Roughness"].default_value = 0.05
    return g.m


def gradient_emission(name, bottom, top, strength=2.0, axis="Y"):
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    sep = g.coords("UV")
    col = g.ramp(sep.outputs[axis], [(0.0, bottom), (1.0, top)])
    g.link(col.outputs["Color"], g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    g.bsdf.inputs["Base Color"].default_value = lin("#05060a")
    return g.m


def foliage_material(name, dark="#1f3a1c", light="#6f9a3a", rough=0.7, translucent=0.25):
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    n = g.node("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 9.0
    n.inputs["Detail"].default_value = 3.0
    col = g.ramp(n.outputs["Fac"], [(0.3, dark), (0.72, light)])
    g.link(col.outputs["Color"], g.bsdf.inputs["Base Color"])
    g.bsdf.inputs["Roughness"].default_value = rough
    g.bsdf.inputs["Subsurface Weight"].default_value = translucent
    return g.m


# ----------------------------------------------------------------------------- mesh builder


class MB:
    """Accumulates many primitives into one mesh with material slots (fast to render)."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.mats = []

    def _uv(self, f):
        for loop, c in zip(f.loops, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
            loop[self.uv].uv = c

    def mi(self, m):
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def _faces_of(self, verts, m):
        k = self.mi(m)
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = k

    def box(self, x0, x1, y0, y1, z0, z1, m, xf=None):
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        z0, z1 = min(z0, z1), max(z0, z1)
        co = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        if xf is not None:
            co = [xf @ Vector(c) for c in co]
        v = [self.bm.verts.new(c) for c in co]
        k = self.mi(m)
        for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (3, 0, 4, 7), (1, 2, 6, 5)):
            f = self.bm.faces.new([v[i] for i in idx])
            f.material_index = k
            self._uv(f)

    def boxc(self, cx, cy, cz, sx, sy, sz, m, rz=0.0):
        xf = Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(rz, 4, "Z")
        self.box(-sx / 2, sx / 2, -sy / 2, sy / 2, -sz / 2, sz / 2, m, xf)

    def quad(self, pts, m):
        v = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(v)
        f.material_index = self.mi(m)
        if len(pts) == 4:
            self._uv(f)

    def front_quad(self, x0, x1, z0, z1, y, m):
        """A plane facing the camera (normal -Y)."""
        self.quad([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], m)

    def cyl(self, cx, cy, z0, z1, r, m, seg=16, r_top=None):
        ret = bmesh.ops.create_cone(
            self.bm,
            cap_ends=True,
            cap_tris=False,
            segments=seg,
            radius1=r,
            radius2=r if r_top is None else r_top,
            depth=abs(z1 - z0),
            matrix=Matrix.Translation((cx, cy, (z0 + z1) / 2)),
        )
        self._faces_of(ret["verts"], m)

    def cyl_x(self, cx, cy, cz, length, r, m, seg=12):
        ret = bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r, depth=length,
            matrix=Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(math.pi / 2, 4, "Y"),
        )
        self._faces_of(ret["verts"], m)

    def cyl_y(self, cx, cy, cz, length, r, m, seg=12):
        ret = bmesh.ops.create_cone(
            self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r, depth=length,
            matrix=Matrix.Translation((cx, cy, cz)) @ Matrix.Rotation(math.pi / 2, 4, "X"),
        )
        self._faces_of(ret["verts"], m)

    def sphere(self, c, r, m, seg=14, rings=9, scale=(1, 1, 1), jitter=0.0, seed=0):
        xf = Matrix.Translation(c) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        ret = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=rings, radius=r, matrix=xf)
        if jitter:
            off = Vector((seed * 1.37, seed * 0.71, seed * 2.13))
            for v in ret["verts"]:
                d = noise.noise_vector(v.co * 2.2 + off)
                v.co += d * jitter
        self._faces_of(ret["verts"], m)

    def ico(self, c, r, m, subdiv=2, jitter=0.0, seed=0, scale=(1, 1, 1)):
        xf = Matrix.Translation(c) @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
        ret = bmesh.ops.create_icosphere(self.bm, subdivisions=subdiv, radius=r, matrix=xf)
        if jitter:
            off = Vector((seed * 1.37, seed * 0.71, seed * 2.13))
            for v in ret["verts"]:
                v.co += noise.noise_vector(v.co * 1.7 + off) * jitter
        self._faces_of(ret["verts"], m)

    def leaf(self, base, ang, tilt, length, width, m, seg=6, droop=0.35):
        d = Vector((math.cos(ang), math.sin(ang), 0.0))
        side = Vector((-math.sin(ang), math.cos(ang), 0.0))
        left, right = [], []
        for i in range(seg + 1):
            t = i / seg
            out = length * t * math.sin(tilt)
            up = length * t * math.cos(tilt) - length * droop * t * t * math.sin(tilt)
            c = Vector(base) + d * out + Vector((0.0, 0.0, up))
            half = width * 0.5 * math.sin(math.pi * min(1.0, 0.08 + t * 0.95)) + 0.002
            left.append(self.bm.verts.new(c - side * half))
            right.append(self.bm.verts.new(c + side * half))
        k = self.mi(m)
        for i in range(seg):
            f = self.bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
            f.material_index = k

    def build(self, coll, bevel=0.0, smooth=False):
        me = bpy.data.meshes.new(self.name)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        if smooth:
            for p in me.polygons:
                p.use_smooth = True
        ob = bpy.data.objects.new(self.name, me)
        coll.objects.link(ob)
        if bevel > 0:
            mod = ob.modifiers.new("Bevel", "BEVEL")
            mod.width = bevel
            mod.segments = 2
            mod.limit_method = "ANGLE"
        return ob


# ----------------------------------------------------------------------------- furniture kit


def plant(mb_leaf, mb_pot, x, y, z, height, leaf_mat, pot_mat, pot_h=0.45, pot_r=0.2, n=10, seed=0, spread=1.0, style="palm"):
    rng = random.Random(seed)
    mb_pot.cyl(x, y, z, z + pot_h, pot_r * 0.8, pot_mat, seg=18, r_top=pot_r)
    base = (x, y, z + pot_h * 0.92)
    if style == "bush":
        for i in range(n):
            a = rng.uniform(0, math.tau)
            rr = rng.uniform(0.0, pot_r * 1.2) * spread
            c = (x + math.cos(a) * rr, y + math.sin(a) * rr * 0.5, z + pot_h + rng.uniform(0.05, height))
            mb_leaf.ico(c, rng.uniform(0.12, 0.22) * spread, leaf_mat, subdiv=1, jitter=0.05, seed=seed + i)
        return
    for i in range(n):
        a = rng.uniform(0, math.tau)
        tilt = rng.uniform(0.25, 1.15)
        length = height * rng.uniform(0.65, 1.0)
        width = height * rng.uniform(0.14, 0.22) * spread
        mb_leaf.leaf(base, a, tilt, length, width, leaf_mat, droop=rng.uniform(0.2, 0.5))


def bookshelf(mb, x0, x1, y0, y1, z0, z1, frame, book_mats, shelves=4, seed=0, fill=0.85):
    rng = random.Random(seed)
    t = 0.035
    mb.box(x0, x1, y1 - 0.02, y1, z0, z1, frame)  # back
    mb.box(x0, x0 + t, y0, y1, z0, z1, frame)
    mb.box(x1 - t, x1, y0, y1, z0, z1, frame)
    step = (z1 - z0) / shelves
    for s in range(shelves + 1):
        zz = z0 + s * step
        mb.box(x0, x1, y0, y1, zz - t / 2, zz + t / 2, frame)
        if s == shelves:
            break
        bx = x0 + t
        while bx < x1 - t - 0.03:
            w = rng.uniform(0.025, 0.06)
            if rng.random() > fill:
                bx += w * 2
                continue
            h = step * rng.uniform(0.55, 0.85)
            lean = 0
            mb.box(bx, min(bx + w, x1 - t), y0 + 0.03, y1 - 0.03, zz + t / 2, zz + t / 2 + h, rng.choice(book_mats))
            bx += w + 0.004 + lean


def monitor(mb, cx, y, z, w, h, frame, screen, stand=True, thickness=0.03, rz=0.0):
    xf = Matrix.Translation((cx, y, z)) @ Matrix.Rotation(rz, 4, "Z")
    mb.box(-w / 2, w / 2, 0, thickness, 0.12, 0.12 + h, frame, xf)
    mb.box(-w / 2 + 0.012, w / 2 - 0.012, -0.002, 0.0, 0.132, 0.12 + h - 0.012, screen, xf)
    if stand:
        mb.box(-0.02, 0.02, 0.01, 0.04, 0.0, 0.14, frame, xf)
        mb.box(-0.09, 0.09, -0.04, 0.08, 0.0, 0.015, frame, xf)


def frame_picture(mb, cx, cz, y, w, h, frame, art, depth=0.03, border=0.025):
    mb.box(cx - w / 2, cx + w / 2, y - depth, y, cz - h / 2, cz + h / 2, frame)
    mb.front_quad(cx - w / 2 + border, cx + w / 2 - border, cz - h / 2 + border, cz + h / 2 - border, y - depth - 0.002, art)


def sofa(mb, x0, x1, y0, y1, z, mat, seat_h=0.42, back_h=0.8, arm=0.14):
    mb.box(x0, x1, y0, y1, z + 0.08, z + seat_h, mat)
    mb.box(x0, x1, y1 - 0.2, y1, z + seat_h, z + back_h, mat)
    mb.box(x0, x0 + arm, y0, y1, z + 0.08, z + seat_h + 0.2, mat)
    mb.box(x1 - arm, x1, y0, y1, z + 0.08, z + seat_h + 0.2, mat)
    mb.box(x0 + arm, (x0 + x1) / 2 - 0.01, y0 + 0.02, y1 - 0.2, z + seat_h, z + seat_h + 0.08, mat)
    mb.box((x0 + x1) / 2 + 0.01, x1 - arm, y0 + 0.02, y1 - 0.2, z + seat_h, z + seat_h + 0.08, mat)


def haze_material(name, color, bottom_alpha, top_alpha, strength=1.0):
    """A band of evening haze: semi-opaque, self-lit, thicker at the bottom."""
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    out = nt.nodes["Material Output"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (bottom_alpha, bottom_alpha, bottom_alpha, 1)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (top_alpha, top_alpha, top_alpha, 1)
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = lin(color)
    em.inputs["Strength"].default_value = strength
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(tc.outputs["UV"], sep.inputs[0])
    nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(em.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    MATS[name] = m
    return m


def image_material(name, texture, strength=1.4, rough=0.2):
    """A self-lit picture (screen, window view, painting) read from art-source/blender/hq/textures."""
    if name in MATS:
        return MATS[name]
    g = Graph(name)
    tc = g.node("ShaderNodeTexCoord")
    img = g.node("ShaderNodeTexImage")
    img.image = bpy.data.images.load(os.path.join(TEXTURES, f"{texture}.png"), check_existing=True)
    img.interpolation = "Linear"
    g.link(tc.outputs["UV"], img.inputs["Vector"])
    g.link(img.outputs["Color"], g.bsdf.inputs["Emission Color"])
    g.bsdf.inputs["Emission Strength"].default_value = strength
    g.bsdf.inputs["Base Color"].default_value = lin("#05060a")
    g.bsdf.inputs["Roughness"].default_value = rough
    return g.m


def leaf_cards(mb, centre, radii, count, size, m, seed, core=None):
    """A tree crown as many small leaf quads in an ellipsoid, with an optional dark core."""
    rng = random.Random(seed)
    k = mb.mi(m)
    cx, cy, cz = centre
    for _ in range(count):
        while True:
            u = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
            if u[0] ** 2 + u[1] ** 2 + u[2] ** 2 <= 1.0:
                break
        shell = 0.55 + 0.45 * rng.random()
        p = Vector((cx + u[0] * radii[0] * shell, cy + u[1] * radii[1] * shell, cz + u[2] * radii[2] * shell))
        n = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized()
        t = n.cross(Vector((0.0, 0.0, 1.0)) if abs(n.z) < 0.9 else Vector((1.0, 0.0, 0.0))).normalized()
        b = n.cross(t)
        s = size * rng.uniform(0.6, 1.3)
        corners = [p + t * s + b * s * 0.6, p - t * s + b * s * 0.6, p - t * s - b * s * 0.6, p + t * s - b * s * 0.6]
        f = mb.bm.faces.new([mb.bm.verts.new(c) for c in corners])
        f.material_index = k
    if core is not None:
        for i in range(10):
            off = (rng.uniform(-0.5, 0.5) * radii[0], rng.uniform(-0.3, 0.3) * radii[1], rng.uniform(-0.4, 0.4) * radii[2])
            mb.ico((cx + off[0], cy + off[1], cz + off[2]), min(radii) * rng.uniform(0.35, 0.55), core, subdiv=1, jitter=0.1, seed=seed + i)
