"""
Composes one department floor (default: the RESEARCH quality-bar floor) as a 3D scene from the
same prop builders the sprites come from, at the positions office_rooms.js uses, and exports it
as glTF for the Unreal Engine reference scene (lighting, contrast, depth and atmosphere tests).

Materials are exported as plain Principled BSDF base colours (the toon ramps are for the sprite
renders; Unreal lights the scene itself).

Run: "<blender>" -b --python art-source/blender/export_floor_scene.py -- [ZONE_TYPE]
"""

from __future__ import annotations

import json
import os
import random
import sys

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import pixelart as pa  # noqa: E402
import props  # noqa: E402
import environment  # noqa: E402
from pixelart import FLOOR_DEPTH_PX as FL  # noqa: E402

CEILING_H = 7
SLAB_H = 12
ROOM_DEPTH_PX = 60   # reference scene is a real room, deeper than the 10 px sprite floor


class Placer:
    """Runs a prop builder, then moves what it built to a world position."""

    def __init__(self, b: pa.Builder, m: props.Mats, seed: int):
        self.b, self.m, self.seed = b, m, seed

    def prop(self, name: str, x: float, y_from_floor: float = 0.0, depth_units: float = 0.0):
        fn, kind, frame, opts = props.PROPS[name]
        opts = dict(opts)
        before = len(self.b.objects)
        fn(self.b, self.m, random.Random(self.seed + hash(name) % 1000), **opts)
        for o in self.b.objects[before:]:
            o.location.x += x
            o.location.z += y_from_floor / pa.COS
            o.location.y += depth_units


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    zone_type = args[0] if args else "RESEARCH"
    with open(os.path.join(pa.ROOT, "art-source", "layout.json"), "r", encoding="utf-8") as fh:
        layout = json.load(fh)
    zone = next(z for z in layout["zones"] if z["zone_type"] == zone_type)
    palette = pa.load_palette()
    dept = palette["departments"][zone_type]
    pa.reset_scene()
    b = pa.Builder()
    m = props.Mats(palette)
    seed = 7
    # Coordinates: x = world px from the zone's left edge; floor line at screen y = FL.
    zx, zw = 0.0, zone["width"]
    wall_h = zone["height"] - CEILING_H - SLAB_H
    wall_top = FL + wall_h
    # Room shell: floor, back wall, ceiling, side walls.
    floor_mat = m.ramp("floor", dept["floor"])
    wall_mat = m.ramp("wall", dept["wall"])
    ceil_mat = m.ramp("ceiling", palette["facade"]["roof"])
    room_depth = pa.Builder.units_deep(ROOM_DEPTH_PX)
    b.box("floor", zx, 0, zw, 0, ROOM_DEPTH_PX, floor_mat, y0=props.FLOOR_FAR - room_depth)
    b.box("wall_back", zx, FL, zw, wall_h, 0, wall_mat, y0=props.FLOOR_FAR)
    b.box("ceiling", zx, wall_top, zw, 0, ROOM_DEPTH_PX, ceil_mat, y0=props.FLOOR_FAR - room_depth)
    for sx in (zx - 1, zx + zw):
        b.box(f"wall_side{sx}", sx, FL, 1, wall_h, ROOM_DEPTH_PX, wall_mat, y0=props.FLOOR_FAR - room_depth)
    # Wainscot and rails along the back wall, tiled.
    tile_w = environment.WALL_TILE_W
    for i in range(int(zw // tile_w) + 1):
        before = len(b.objects)
        environment.build_wall(b, m, random.Random(seed), dept, wall_h)
        for o in b.objects[before:]:
            o.location.x += zx + i * tile_w
    # Props at the positions office_rooms.js uses for this department.
    p = Placer(b, m, seed)
    cx = zx + zw / 2
    if zone_type == "RESEARCH":
        p.prop("evidence_board", cx - 70, wall_top - 12 - FL)
        p.prop("window_46x38", zx + 100, wall_top - 14 - FL)
        p.prop("window_46x38", zx + zw - 150, wall_top - 14 - FL)
        p.prop("bookshelf_ash", zx + 16)
        p.prop("lab_bench", zx + zw - 236)
        p.prop("archive_boxes", zx + zw - 72)
        p.prop("plant_large", zx + zw - 20)
        p.prop("filing_cabinet", zx + 230)
        p.prop("whiteboard", zx + zw - 150, wall_top - 14 - FL)
    for i, d in enumerate(zone.get("desks", [])):
        dx = d["x"] - zone["x"] + zx
        wood = "walnut" if i % 2 == 0 else "oak"
        p.prop(f"workstation_{wood}_back", dx)
        p.prop(f"workstation_{wood}", dx)
    # Ceiling fixtures (the renderer's fixtures(): one per ~118 px).
    step = 118
    count = max(1, round((zw - 40) / step))
    fixture_mat = m.ramp("fixture", palette["materials"]["steel"])
    for i in range(count):
        fx = zx + zw * (i + 0.5) / count
        b.box(f"fixture{i}", fx - 13, wall_top - 4, 26, 4, 6, fixture_mat, y0=props.FLOOR_FAR - room_depth / 2)

    # Replace toon materials with plain Principled base colours for the export.
    for mat in bpy.data.materials:
        nt = mat.node_tree
        if not nt:
            continue
        ramp = next((n for n in nt.nodes if n.type == "VALTORGB"), None)
        base = ramp.color_ramp.elements[2].color if ramp and len(ramp.color_ramp.elements) > 2 else (0.5, 0.5, 0.5, 1)
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = base
        bsdf.inputs["Roughness"].default_value = 0.7
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Bake every object's transform into its mesh so the importer can place each static mesh
    # at the origin and the scene still assembles correctly.
    bpy.context.view_layer.update()   # headless: matrix_world is stale until the layer updates
    for o in b.objects:
        if o.type == "MESH":
            o.data.transform(o.matrix_world)
            o.matrix_world.identity()

    out_dir = os.path.join(pa.ROOT, "art-source", "unreal")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{zone_type.lower()}_floor.glb")
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_apply=True, export_yup=True,
                              use_selection=False, export_materials="EXPORT", export_lights=False, export_cameras=False)
    meta = {"zone": zone, "wall_h": wall_h, "floor_depth_px": FL, "room_depth_px": ROOM_DEPTH_PX,
            "pitch_deg": pa.PITCH, "fixtures": count, "lamp": dept["lamp"], "accent": dept["accent"]}
    with open(os.path.join(out_dir, f"{zone_type.lower()}_floor.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"EXPORTED {out} objects={len(b.objects)}")


main()
