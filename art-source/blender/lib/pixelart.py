"""
Pixel-art toolkit for Blender (5.x, EEVEE) — renders 3D assets straight into crisp,
palette-exact sprites at 1 world px = 1 sprite px.

Conventions
-----------
- Screen space: x right, y up, in world pixels. World space: X right, Z up, Y depth (away
  from the viewer). The camera is orthographic, looking along +Y, pitched PITCH degrees down,
  so a horizontal face of depth d shows as d*sin(PITCH) screen px and a vertical face of
  height h shows as h*cos(PITCH) screen px. `Builder` takes screen-space sizes and converts.
- The room floor is FLOOR_DEPTH_PX (10) screen px deep: the far edge (wall junction) is at
  screen y = 10 = the renderer's `floorLine`, the near edge at screen y = 0.
- Materials are toon ramps: Diffuse -> Shader to RGB -> constant ColorRamp over the five tones
  of a palette ramp (darkest -> lightest), emitted unlit. Faces land on exactly one tone.
- Key materials: the same ramp mechanism but with index colours, so a sprite can be recoloured
  per agent at load time (skin/hair/garment) without re-rendering.
- Post-process: nearest-colour snap to the allowed ramps, then a 1 px outline in
  AMBIENT.shadow around the silhouette (the same rule PixelGrid.outline() applies).
- Cast shadows are rendered as a separate layer (`<name>_shadow.png`) from a white shadow
  catcher (floor + back wall), so the renderer can blend them at a fixed alpha.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PALETTE_PATH = os.path.join(ROOT, "art-source", "palette.json")

PITCH = 16.0
SIN = math.sin(math.radians(PITCH))
COS = math.cos(math.radians(PITCH))
FLOOR_DEPTH_PX = 10                     # visible floor surface depth of a premium (atlas) floor
FLOOR_FAR = FLOOR_DEPTH_PX / SIN        # world depth (units) of the wall junction
SHADOW_ALPHA = 0.34                     # what the renderer blends shadow layers with

KEY_RAMPS = {
    "skin":    ["#ff0000", "#ff2020", "#ff4040", "#ff6060", "#ff8080"],
    "hair":    ["#00ff00", "#20ff20", "#40ff40", "#60ff60", "#80ff80"],
    "garment": ["#0000ff", "#2020ff", "#4040ff", "#6060ff", "#8080ff"],
    "second":  ["#ffff00", "#ffff20", "#ffff40", "#ffff60", "#ffff80"],
    "trim":    ["#ff00ff", "#ff20ff", "#ff40ff", "#ff60ff", "#ff80ff"],
}


# ----------------------------------------------------------------------------- palette

def load_palette() -> dict:
    with open(PALETTE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(h: str) -> tuple[float, float, float, float]:
    r, g, b = hex_to_rgb(h)
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)


def mix_hex(a: str, b: str, t: float) -> str:
    ra, ga, ba = (round(x * 255) for x in hex_to_rgb(a))
    rb, gb, bb = (round(x * 255) for x in hex_to_rgb(b))
    c = lambda p, q: max(0, min(255, round(p + (q - p) * t)))  # noqa: E731
    return "#%02x%02x%02x" % (c(ra, rb), c(ga, gb), c(ba, bb))


def ramp_from(base: str, palette: dict, dark: float = 0.62, light: float = 0.42) -> list[str]:
    """Mirror of office_palette.ramp(): five hue-shifted tones around a base colour."""
    sh, li = palette["ambient"]["shadow"], palette["ambient"]["light"]
    return [mix_hex(base, sh, dark), mix_hex(base, sh, dark * 0.5), base,
            mix_hex(base, li, light * 0.5), mix_hex(base, li, light)]


# ----------------------------------------------------------------------------- scene

def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _MAT_CACHE.clear()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.filter_size = 0.0          # no anti-aliasing: hard pixel edges
    scene.render.dither_intensity = 0.0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 15
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1
    scene.render.pixel_aspect_y = 1
    ee = scene.eevee
    ee.taa_render_samples = 1
    ee.taa_samples = 1
    ee.use_shadows = True
    ee.shadow_ray_count = 1
    ee.shadow_step_count = 1
    ee.shadow_resolution_scale = 1.0
    for attr, val in (("use_shadow_jitter_viewport", False),):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    vs = scene.view_settings
    for attr, val in (("view_transform", "Standard"), ("look", "None")):
        try:
            setattr(vs, attr, val)
        except TypeError:
            pass
    vs.exposure = 0.0
    vs.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 0.06


def add_lights(key_strength: float = math.pi) -> None:
    """Key sun from above-front-left (hard shadow); weak fill from the right so right faces
    sit one tone above bottom faces, matching slab(): top lit, left lit, right shadow, bottom deep."""
    def sun(name: str, direction: Vector, strength: float, angle: float, shadow: bool):
        data = bpy.data.lights.new(name, "SUN")
        data.energy = strength
        data.angle = angle
        data.use_shadow = shadow
        for attr, val in (("shadow_filter_radius", 0.0), ("use_shadow_jitter", False),
                          ("shadow_softness_factor", 0.0), ("shadow_jitter_overblur", 0.0)):
            if hasattr(data, attr):
                setattr(data, attr, val)
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return obj
    # Steep key (short cast shadows): up 0.92, front 0.30, left 0.25.
    sun("Key", Vector((0.25, 0.30, -0.92)).normalized(), key_strength, math.radians(0.5), True)
    # Left fill without shadows lifts left faces one tone: left +0.31, front +0.07, up +0.13.
    sun("Left", Vector((0.9, 0.2, -0.38)).normalized(), key_strength * 0.35, math.radians(10), False)
    # Right fill keeps right faces one tone above bottom faces.
    sun("Right", Vector((-1.0, 0.0, -0.15)).normalized(), key_strength * 0.16, math.radians(10), False)


@dataclass
class Camera:
    """Frame `width` x `height` px whose bottom-left corner is screen point (origin_x, origin_y)."""
    width: int
    height: int
    origin_x: float = 0.0
    origin_y: float = 0.0
    obj: bpy.types.Object | None = None

    def build(self) -> bpy.types.Object:
        scene = bpy.context.scene
        scene.render.resolution_x = self.width
        scene.render.resolution_y = self.height
        cam = bpy.data.cameras.new("PixelCam")
        cam.type = "ORTHO"
        cam.sensor_fit = "HORIZONTAL"
        cam.ortho_scale = float(self.width)
        cam.clip_start = 1.0
        cam.clip_end = 100000.0
        obj = bpy.data.objects.new("PixelCam", cam)
        bpy.context.collection.objects.link(obj)
        scene.camera = obj
        cx = self.origin_x + self.width / 2.0
        cy = self.origin_y + self.height / 2.0
        target = Vector((cx, 0.0, cy / COS))
        forward = Vector((0.0, COS, -SIN))
        obj.location = target - forward * 5000.0
        obj.rotation_euler = (math.radians(90.0 - PITCH), 0.0, 0.0)
        self.obj = obj
        return obj

    def sprite_px(self, sx: float, sy: float) -> tuple[int, int]:
        """Screen point -> pixel (col, row) in the rendered image (row 0 = top)."""
        return int(round(sx - self.origin_x)), int(round((self.origin_y + self.height - 1) - sy))


# ----------------------------------------------------------------------------- materials

_MAT_CACHE: dict[str, bpy.types.Material] = {}


def toon_material(name: str, tones: list[str], thresholds=(0.09, 0.30, 0.50, 0.66)) -> bpy.types.Material:
    """Five-tone material: lit intensity is quantised to one of `tones` (dark -> light)."""
    key = f"{name}|{'|'.join(tones)}|{thresholds}"
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    s2rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    while len(cr.elements) < len(tones):
        cr.elements.new(0.5)
    positions = (0.0,) + tuple(thresholds)
    for i, (pos, tone) in enumerate(zip(positions, tones)):
        cr.elements[i].position = pos
        cr.elements[i].color = hex_to_linear(tone)
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(diff.outputs["BSDF"], s2rgb.inputs["Shader"])
    nt.links.new(s2rgb.outputs["Color"], bw.inputs["Color"])
    nt.links.new(bw.outputs["Val"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    _MAT_CACHE[key] = mat
    return mat


def flat_material(name: str, hex_color: str) -> bpy.types.Material:
    """Unlit single colour (screens, glowing parts, paper)."""
    return toon_material(name, [hex_color] * 5)


def key_material(kind: str) -> bpy.types.Material:
    return toon_material(f"key_{kind}", KEY_RAMPS[kind])


def catcher_material() -> bpy.types.Material:
    """White where lit by the key sun, black in its shadow."""
    return toon_material("catcher", ["#000000", "#ffffff"], thresholds=(0.09,))


# ----------------------------------------------------------------------------- geometry

def _new_object(name: str, bm: bmesh.types.BMesh, mat: bpy.types.Material, collection=None):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.collection).objects.link(obj)
    if mat is not None:
        mesh.materials.append(mat)
    for p in mesh.polygons:
        p.use_smooth = False
    return obj


@dataclass
class Builder:
    """Places primitives by screen-space pixel sizes. All world coordinates are derived from
    (screen x, screen y, depth y0 in units) so edges land on whole pixels."""
    collection: bpy.types.Collection | None = None
    objects: list = field(default_factory=list)
    shadow_only: list = field(default_factory=list)   # objects that cast but never render

    @staticmethod
    def units_deep(d_px: float) -> float:
        return d_px / SIN

    @staticmethod
    def units_tall(h_px: float) -> float:
        return h_px / COS

    @staticmethod
    def z_for(sy: float, y0: float) -> float:
        """World z whose screen y is `sy` at depth y0."""
        return (sy - y0 * SIN) / COS

    def box(self, name, sx, sy, w, h_px, d_px, mat, y0=0.0, bevel=0.0, dx_scale=1.0):
        """Box whose front-bottom-left corner is at screen (sx, sy) and depth y0 (units);
        w px wide, h_px front-face height on screen, d_px top-face depth on screen."""
        depth = self.units_deep(d_px) if d_px > 0 else 0.02
        height = self.units_tall(h_px) if h_px > 0 else 0.02
        z0 = self.z_for(sy, y0)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(w, depth, height), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(sx + w / 2.0, y0 + depth / 2.0, z0 + height / 2.0), verts=bm.verts)
        if bevel > 0:
            bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=1, affect="EDGES")
        obj = _new_object(name, bm, mat, self.collection)
        self.objects.append(obj)
        return obj

    def wedge(self, name, sx, sy, w, h_px, d_px, mat, y0=0.0, slope="back"):
        """Box whose top face slopes: 'back' = high at the back (like a lectern), 'right' = high on the right."""
        obj = self.box(name, sx, sy, w, h_px, d_px, mat, y0)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        zmax = max(v.co.z for v in bm.verts)
        for v in bm.verts:
            if abs(v.co.z - zmax) < 1e-6:
                if slope == "back" and v.co.y < y0 + 1e-6:
                    v.co.z -= self.units_tall(h_px) * 0.5
                if slope == "right" and v.co.x < sx + 1e-6:
                    v.co.z -= self.units_tall(h_px) * 0.5
        bm.to_mesh(obj.data)
        bm.free()
        return obj

    def cylinder(self, name, sx, sy, radius_px, length_px, mat, y0=0.0, axis="Z", verts=24):
        """axis Z: standing, (sx, sy) = centre-bottom. axis X: lying left-right, sx = left end,
        sy = bottom. axis Y: pointing into the screen, sx = centre, sy = bottom."""
        bm = bmesh.new()
        r = radius_px
        if axis == "Z":
            length = self.units_tall(length_px)
            bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=length)
            bmesh.ops.translate(bm, vec=(sx, y0, self.z_for(sy, y0) + length / 2.0), verts=bm.verts)
        elif axis == "X":
            bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=length_px)
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"), verts=bm.verts)
            bmesh.ops.translate(bm, vec=(sx + length_px / 2.0, y0, self.z_for(sy + r, y0)), verts=bm.verts)
        else:
            length = self.units_deep(length_px)
            bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r, depth=length)
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"), verts=bm.verts)
            bmesh.ops.translate(bm, vec=(sx, y0 + length / 2.0, self.z_for(sy + r, y0)), verts=bm.verts)
        obj = _new_object(name, bm, mat, self.collection)
        self.objects.append(obj)
        return obj

    def sphere(self, name, sx, sy, radius_px, mat, y0=0.0, scale=(1.0, 1.0, 1.0), segments=20):
        """(sx, sy) = centre on screen."""
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=max(6, segments // 2), radius=radius_px)
        bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
        bmesh.ops.translate(bm, vec=(sx, y0, self.z_for(sy, y0)), verts=bm.verts)
        obj = _new_object(name, bm, mat, self.collection)
        self.objects.append(obj)
        return obj

    def catcher(self, sx0, sx1, wall_height_px=140):
        """Shadow catcher: the floor strip (screen y 0..7) plus the back wall above it."""
        mat = catcher_material()
        floor = self.box("catcher_floor", sx0, 0, sx1 - sx0, 0, FLOOR_DEPTH_PX, mat, y0=0.0)
        wall = self.box("catcher_wall", sx0, FLOOR_DEPTH_PX, sx1 - sx0, wall_height_px, 0, mat, y0=FLOOR_FAR)
        for o in (floor, wall):
            self.objects.remove(o)
        return [floor, wall]


# ----------------------------------------------------------------------------- render + post

def render_to(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def read_png(path: str) -> np.ndarray:
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    arr = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return np.clip(np.round(np.flipud(arr) * 255.0), 0, 255).astype(np.uint8)


def write_png(path: str, rgba: np.ndarray) -> None:
    h, w = rgba.shape[:2]
    img = bpy.data.images.new("out", w, h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    img.pixels = (np.flipud(rgba).astype(np.float32) / 255.0).ravel().tolist()
    img.file_format = "PNG"
    img.filepath_raw = path
    img.alpha_mode = "STRAIGHT"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save()
    bpy.data.images.remove(img)


def hex_list_to_array(colors: list[str]) -> np.ndarray:
    return np.array([[int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)] for c in colors], dtype=np.int32)


def snap_to_palette(rgba: np.ndarray, colors: list[str], alpha_cut: int = 128) -> np.ndarray:
    out = rgba.copy()
    pal = hex_list_to_array(list(dict.fromkeys(colors)))
    alpha = out[..., 3] >= alpha_cut
    flat = out[..., :3].astype(np.int32)[alpha]
    if flat.size:
        d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
        out[..., :3][alpha] = pal[d.argmin(axis=1)].astype(np.uint8)
    out[..., 3] = np.where(alpha, 255, 0).astype(np.uint8)
    out[..., :3][~alpha] = 0
    return out


def outline(rgba: np.ndarray, color: str, mask: np.ndarray | None = None) -> np.ndarray:
    """1 px outline around the silhouette (4-connected), like PixelGrid.outline()."""
    out = rgba.copy()
    a = out[..., 3] > 0
    touch = np.zeros_like(a)
    touch[1:, :] |= a[:-1, :]
    touch[:-1, :] |= a[1:, :]
    touch[:, 1:] |= a[:, :-1]
    touch[:, :-1] |= a[:, 1:]
    edge = touch & ~a
    if mask is not None:
        edge &= mask
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    out[edge] = (r, g, b, 255)
    return out


def scale_nearest(rgba: np.ndarray, k: int) -> np.ndarray:
    return np.repeat(np.repeat(rgba, k, axis=0), k, axis=1)


def unique_colors(rgba: np.ndarray) -> list[str]:
    a = rgba[..., 3] > 0
    px = np.unique(rgba[..., :3][a].reshape(-1, 3), axis=0)
    return ["#%02x%02x%02x" % tuple(int(v) for v in p) for p in px]


def render_layers(scene_objects: list, catcher_objects: list, tmp: str, allowed: list[str],
                  outline_color: str, shadow_color: str, no_outline_mask=None):
    """Render the prop (transparent) and its cast shadow on the catcher. Returns
    (sprite_rgba, shadow_rgba) — the shadow layer is opaque shadow colour where shadowed."""
    for o in catcher_objects:
        o.hide_render = True
    render_to(tmp + "_prop.png")
    prop = read_png(tmp + "_prop.png")
    for o in catcher_objects:
        o.hide_render = False
    render_to(tmp + "_shadow.png")
    with_catcher = read_png(tmp + "_shadow.png")
    for o in scene_objects:
        o.hide_render = True
    render_to(tmp + "_catcher.png")
    catcher_only = read_png(tmp + "_catcher.png")
    for o in scene_objects:
        o.hide_render = False

    sprite = snap_to_palette(prop, allowed)
    if outline_color:
        sprite = outline(sprite, outline_color, no_outline_mask)
    prop_alpha = sprite[..., 3] > 0
    on_catcher = catcher_only[..., 3] > 128
    dark = with_catcher[..., :3].sum(axis=2) < 3 * 128
    shadow_mask = on_catcher & dark & ~prop_alpha & (with_catcher[..., 3] > 128)
    r, g, b = (int(shadow_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    shadow = np.zeros_like(sprite)
    shadow[shadow_mask] = (r, g, b, 255)
    for f in ("_prop.png", "_shadow.png", "_catcher.png"):
        try:
            os.remove(tmp + f)
        except OSError:
            pass
    return sprite, shadow
