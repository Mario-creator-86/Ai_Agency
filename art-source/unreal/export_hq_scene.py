"""Export the headquarters scene (building, street, city) from the Blender build for Unreal.

  blender -b --factory-startup --python art-source/unreal/export_hq_scene.py -- [--out art-source/unreal/hq_scene.glb]

Builds the same geometry, materials and lights as art-source/blender/hq/build_hq.py (without
rendering) and writes:

- hq_scene.glb: every mesh with its world transform baked in (each sits at the origin, so an asset
  import places it without the glTF node hierarchy), text objects turned into meshes;
- hq_scene.json: the lights (kind, position in metres, rotation, energy, colour, radius, cone),
  the camera the plates use, and axis markers, so the Unreal script measures how the importer maps
  Blender's axes and units instead of assuming it.

glTF carries only flat colours, so procedural materials (panels, brick, window grids, asphalt,
screen and window images) arrived in Unreal white. Each mesh that uses one gets its own UV map and
two baked textures (colour, and emission scaled to 8 bits with its strength kept separately), and
those materials are rebuilt as a plain Principled BSDF on the baked images. Transparent materials
are exported as they are. The haze planes, which only make sense in the plate renderer, are left
out; Unreal's height fog does their job. Texture size per mesh follows its surface area, up to
AMN_BAKE (default 4096). All outputs are generated and ignored by Git.
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
HQ = os.path.abspath(os.path.join(HERE, "..", "blender", "hq"))
sys.path.insert(0, HQ)

import hq_building  # noqa: E402
import hq_city  # noqa: E402
from hq_lib import COS, MB, PPM, SIN, THETA, ZC, collection, principled  # noqa: E402

LAYERS = ["city", "street_back", "street_ground", "building_back", "building_front", "building_shell", "street_props", "street_kerb", "street_front"]
LIGHTS = ["lights_interior", "lights_exterior"]
WORLD_W, WORLD_H = 1600, 840
BAKE_MAX = int(os.environ.get("AMN_BAKE", "4096"))
TEXELS_PER_M = 2 * PPM  # the plates render at twice the world's pixels


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(HERE, "hq_scene.glb"))
    return p.parse_args(argv)


# ----------------------------------------------------------------------------- scene preparation


def texts_to_meshes():
    """glTF has no text objects: replace each with the mesh it evaluates to, in the same collections."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    count = 0
    for ob in [o for o in bpy.data.objects if o.type in ("FONT", "CURVE")]:
        mesh = bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph))
        new = bpy.data.objects.new(ob.name + "_mesh", mesh)
        new.matrix_world = ob.matrix_world.copy()
        for coll in ob.users_collection:
            coll.objects.link(new)
        bpy.data.objects.remove(ob, do_unlink=True)
        count += 1
    return count


def drop_haze():
    removed = [o.name for o in bpy.data.objects if o.name.startswith("haze")]
    for name in removed:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    return removed


def bake_transforms():
    """Apply modifiers and world transforms into each mesh, so every mesh object sits at the origin."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for ob in [o for o in bpy.data.objects if o.type == "MESH"]:
        mesh = bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph))
        mesh.transform(ob.matrix_world)
        ob.modifiers.clear()
        ob.data = mesh
        ob.matrix_world = Matrix.Identity(4)


def markers(coll):
    """Small cubes at known metres: Unreal measures its axis mapping from them."""
    mat = principled("amn_marker", "#ff00ff", rough=0.5)
    out = {}
    for name, (x, y, z) in (("AMN_MARKER_O", (0.0, 0.0, 60.0)), ("AMN_MARKER_X", (10.0, 0.0, 60.0)), ("AMN_MARKER_Z", (0.0, 0.0, 70.0)), ("AMN_MARKER_Y", (0.0, 10.0, 60.0))):
        mb = MB(name)
        mb.box(x - 0.25, x + 0.25, y - 0.25, y + 0.25, z - 0.25, z + 0.25, mat)
        mb.build(coll)
        out[name] = [x, y, z]
    return out


# ----------------------------------------------------------------------------- material baking


def principled_node(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat and mat.use_nodes else None


def is_transparent(mat):
    if not mat or not mat.use_nodes:
        return False
    nodes = mat.node_tree.nodes
    if any(n.type in ("BSDF_TRANSPARENT", "BSDF_GLASS", "BSDF_REFRACTION") for n in nodes):
        return True
    bsdf = principled_node(mat)
    return bool(bsdf and (bsdf.inputs["Alpha"].is_linked or bsdf.inputs["Alpha"].default_value < 0.999 or bsdf.inputs["Transmission Weight"].default_value > 0.01))


def needs_bake(mat):
    """A material glTF cannot carry: anything driving colour or emission through nodes."""
    if not mat or not mat.use_nodes or is_transparent(mat):
        return False
    bsdf = principled_node(mat)
    if bsdf is None:
        return True  # an emission shader or a node mix
    return any(bsdf.inputs[k].is_linked for k in ("Base Color", "Emission Color", "Emission Strength"))


def to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def bake_size(ob):
    area = sum(p.area for p in ob.data.polygons)
    wanted = math.sqrt(max(area, 1e-4)) * TEXELS_PER_M
    size = 256
    while size < wanted and size < BAKE_MAX:
        size *= 2
    return size


WINDOW_CELLS = 24
WINDOW_CELL_PX = 16


def window_params(mat):
    """The parameters of a hq_lib.windows_material, read back from its node graph (None otherwise).

    A skyline facade is a grid of windows; baked into one texture for a whole mesh of towers each
    window gets a few blurred texels. Instead each facade material gets a tiling texture of
    WINDOW_CELLS x WINDOW_CELLS windows on world-aligned UVs.
    """
    if not mat or not mat.node_tree:
        return None
    nodes = mat.node_tree.nodes
    brick = next((n for n in nodes if n.type == "TEX_BRICK"), None)
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if brick is None or bsdf is None:
        return None
    ramps = [n for n in nodes if n.type == "VALTORGB"]
    lit = next((r for r in ramps if len(r.color_ramp.elements) >= 4), None)
    base = next((r for r in ramps if r is not lit and len(r.color_ramp.elements) == 2 and tuple(r.color_ramp.elements[0].color)[:3] != (1.0, 1.0, 1.0)), None)
    if lit is None or base is None:
        return None
    return {
        "w": brick.inputs["Brick Width"].default_value,
        "h": brick.inputs["Row Height"].default_value,
        "mortar": brick.inputs["Mortar Size"].default_value,
        "lit": [(e.position, tuple(e.color)[:3]) for e in lit.color_ramp.elements],
        "glass": tuple(base.color_ramp.elements[0].color)[:3],
        "wall": tuple(base.color_ramp.elements[1].color)[:3],
        "strength": bsdf.inputs["Emission Strength"].default_value,
        "rough": bsdf.inputs["Roughness"].default_value if not bsdf.inputs["Roughness"].is_linked else 0.35,
    }


def byte_image(name, rgb_linear, path):
    """An 8-bit sRGB PNG from a linear (h, w, 3) array."""
    h, w, _ = rgb_linear.shape
    img = bpy.data.images.new(name, w, h, alpha=False)
    out = np.ones((h, w, 4), np.float32)
    out[..., :3] = to_srgb(rgb_linear)
    img.pixels.foreach_set(out.ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return img


# Seen live next to the Owner's picture (2026-09-15), the skyline read as bright blocks: nearly half
# the windows lit, all at full strength, each a flat square. The picture's towers have fewer lit
# windows, of uneven brightness, divided by mullions. AMN_WINDOW_LIT_SHARE keeps that share of the
# lit windows the Blender material would light; AMN_WINDOW_DIM_MIN is the dimmest a lit window gets.
WINDOW_LIT_SHARE = float(os.environ.get("AMN_WINDOW_LIT_SHARE", "0.6"))
WINDOW_DIM_MIN = float(os.environ.get("AMN_WINDOW_DIM_MIN", "0.35"))


def window_material(mat, p, bake_dir, seed):
    """Rebuild a facade material as tiling colour and emission textures of lit and dark windows."""
    rng = np.random.default_rng(seed)
    n, c = WINDOW_CELLS, WINDOW_CELL_PX
    positions = np.array([e[0] for e in p["lit"]], np.float32)
    colours = np.array([e[1] for e in p["lit"]], np.float32)
    idx = np.clip(np.searchsorted(positions, rng.random((n, n)), side="right") - 1, 0, len(positions) - 1)
    cell_lit = colours[idx]
    # fewer lit windows, each at its own brightness
    lit = cell_lit.max(axis=-1) > 0.05
    cell_lit[lit & (rng.random((n, n)) > WINDOW_LIT_SHARE)] = 0.0
    cell_lit *= rng.uniform(WINDOW_DIM_MIN, 1.0, (n, n)).astype(np.float32)[..., None]
    mx = min(0.45, p["mortar"] / max(p["w"], 1e-4))
    my = min(0.45, p["mortar"] / max(p["h"], 1e-4))
    ys, xs = np.mgrid[0:c, 0:c].astype(np.float32) / c
    # a one-texel mullion down the middle of each window
    mullion = np.abs(xs + 0.5 / c - 0.5) < 1.0 / c
    inside = ((xs >= mx / 2) & (xs < 1 - mx / 2) & (ys >= my / 2) & (ys < 1 - my / 2) & ~mullion).astype(np.float32)
    mask = np.tile(inside, (n, n))[..., None]
    emit = np.repeat(np.repeat(cell_lit, c, axis=0), c, axis=1) * mask
    base = np.array(p["glass"], np.float32) * mask + np.array(p["wall"], np.float32) * (1 - mask)
    color_img = byte_image(f"{mat.name}_win_color", base, os.path.join(bake_dir, f"{mat.name}_win_color.png"))
    emit_img = byte_image(f"{mat.name}_win_emit", emit, os.path.join(bake_dir, f"{mat.name}_win_emit.png"))
    rebuild(mat, color_img, emit_img, p["strength"])
    bsdf = principled_node(mat)
    if bsdf:
        bsdf.inputs["Roughness"].default_value = p["rough"]


def world_uvs(ob, params_by_slot):
    """World-aligned UVs (in window cells) on the faces of facade materials, in the 'bake' layer."""
    me = ob.data
    uv = me.uv_layers.get("bake") or me.uv_layers.new(name="bake")
    for poly in me.polygons:
        p = params_by_slot.get(poly.material_index)
        if not p:
            continue
        nx, ny, nz = poly.normal
        su, sv = WINDOW_CELLS * p["w"], WINDOW_CELLS * p["h"]
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if abs(nz) > 0.7:
                u, v = co.x, co.y
            elif abs(nx) > abs(ny):
                u, v = co.y, co.z
            else:
                u, v = co.x, co.z
            uv.data[li].uv = (u / su, v / sv)


def select_only(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def set_bake_target(mats, image):
    """Every material of the mesh gets an unconnected image node, active, pointing at the bake image."""
    for mat in mats:
        nt = mat.node_tree
        node = nt.nodes.get("AMN_BAKE_TARGET") or nt.nodes.new("ShaderNodeTexImage")
        node.name = "AMN_BAKE_TARGET"
        node.image = image
        for n in nt.nodes:
            n.select = False
        node.select = True
        nt.nodes.active = node


def rebuild(mat, color_img, emit_img, strength):
    """Replace the node graph with a Principled BSDF on the baked images (UV map 'bake')."""
    old = principled_node(mat)
    rough = old.inputs["Roughness"].default_value if old and not old.inputs["Roughness"].is_linked else 0.6
    metal = old.inputs["Metallic"].default_value if old and not old.inputs["Metallic"].is_linked else 0.0
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "bake"
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = color_img
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if emit_img is not None:
        etex = nt.nodes.new("ShaderNodeTexImage")
        etex.image = emit_img
        nt.links.new(uv.outputs["UV"], etex.inputs["Vector"])
        nt.links.new(etex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def bake_materials(scene, bake_dir):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "HIP"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "HIP"
    scene.cycles.device = "GPU"
    scene.cycles.samples = 1
    scene.render.bake.margin = 4
    os.makedirs(bake_dir, exist_ok=True)
    baked = 0
    window_mats = {}
    for ob in [o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith("AMN_MARKER")]:
        slots = [s for s in ob.material_slots if s.material]
        if not any(needs_bake(s.material) for s in slots):
            continue
        windows = {i: p for i, s in enumerate(ob.material_slots) if s.material and (p := window_params(s.material))}
        # each mesh owns copies of its baked materials, so its baked images stay its own;
        # facade materials are shared, their tiling textures do not depend on the mesh
        for i, s in enumerate(ob.material_slots):
            if s.material and i not in windows:
                s.material = s.material.copy()
        mats = [s.material for s in ob.material_slots if s.material]
        targets = [s.material for i, s in enumerate(ob.material_slots) if s.material and i not in windows and needs_bake(s.material)]
        me = ob.data
        render_uv = me.uv_layers.get("UVMap")
        bake_uv = me.uv_layers.new(name="bake")
        if render_uv:
            render_uv.active_render = True
        me.uv_layers.active = bake_uv
        if not targets:
            world_uvs(ob, windows)
            for i, p in windows.items():
                mat = ob.material_slots[i].material
                if mat.name not in window_mats:
                    window_material(mat, p, bake_dir, seed=len(window_mats) + 1)
                    window_mats[mat.name] = True
            print(f"AMN_WINDOWS {ob.name} facades={len(windows)}")
            continue
        select_only(ob)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.001)
        bpy.ops.object.mode_set(mode="OBJECT")
        size = bake_size(ob)

        color = bpy.data.images.new(f"{ob.name}_color", size, size, alpha=False)
        set_bake_target(mats, color)
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_clear=True, margin=4)
        color.filepath_raw = os.path.join(bake_dir, f"{ob.name}_color.png")
        color.file_format = "PNG"
        color.save()

        emit_f = bpy.data.images.new(f"{ob.name}_emit_f", size, size, alpha=False, float_buffer=True)
        set_bake_target(mats, emit_f)
        bpy.ops.object.bake(type="EMIT", use_clear=True, margin=4)
        px = np.empty(size * size * 4, dtype=np.float32)
        emit_f.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        peak = float(px[:, :3].max())
        emit = None
        if peak > 0.005:
            emit = bpy.data.images.new(f"{ob.name}_emit", size, size, alpha=False)
            out = np.ones_like(px)
            out[:, :3] = to_srgb(px[:, :3] / peak)
            emit.pixels.foreach_set(out.ravel())
            emit.filepath_raw = os.path.join(bake_dir, f"{ob.name}_emit.png")
            emit.file_format = "PNG"
            emit.save()
        bpy.data.images.remove(emit_f)
        for mat in mats:
            node = mat.node_tree.nodes.get("AMN_BAKE_TARGET")
            if node:
                mat.node_tree.nodes.remove(node)
        for mat in targets:
            rebuild(mat, color, emit, peak)
        if windows:
            world_uvs(ob, windows)
            for i, p in windows.items():
                mat = ob.material_slots[i].material
                if mat.name not in window_mats:
                    window_material(mat, p, bake_dir, seed=len(window_mats) + 1)
                    window_mats[mat.name] = True
        baked += 1
        print(f"AMN_BAKE {ob.name} {size}px materials={len(targets)} facades={len(windows)} emission_peak={peak:.2f}")
    return baked


# ----------------------------------------------------------------------------- metadata


def lights_json():
    out = []
    for cname in LIGHTS:
        for ob in bpy.data.collections[cname].objects:
            if ob.type != "LIGHT":
                continue
            d = ob.data
            loc = ob.matrix_world.translation
            direction = ob.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
            item = {
                "name": ob.name,
                "group": cname,
                "kind": d.type,
                "location_m": [round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)],
                "direction": [round(direction.x, 4), round(direction.y, 4), round(direction.z, 4)],
                "energy": d.energy,
                "color": [round(c, 4) for c in d.color],
            }
            if d.type in ("POINT", "SPOT"):
                item["radius_m"] = d.shadow_soft_size
            if d.type == "SPOT":
                item["cone_deg"] = math.degrees(d.spot_size)
                item["blend"] = d.spot_blend
            if d.type == "AREA":
                item["size_m"] = d.size
            if d.type == "SUN":
                item["angle_deg"] = math.degrees(d.angle)
            out.append(item)
    return out


def main():
    a = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    colls = {name: collection(name) for name in LAYERS + LIGHTS}
    hq_building.build(colls)
    hq_city.build(colls)
    for ob in colls["lights_interior"].objects:
        ob.data.energy *= 3.15
    marks = markers(colls["street_front"])
    bpy.context.view_layer.update()
    converted = texts_to_meshes()
    haze = drop_haze()
    bpy.context.view_layer.update()
    bake_transforms()
    bake_dir = os.path.join(HERE, "bake")
    baked = bake_materials(scene, bake_dir)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", export_lights=False, export_apply=True, export_yup=True, export_extras=True)
    meta = {
        "world_px": [WORLD_W, WORLD_H],
        "pixels_per_metre": PPM,
        "camera": {
            "type": "orthographic",
            "pitch_deg": math.degrees(THETA),
            "width_m": WORLD_W / PPM,
            "aspect": WORLD_W / WORLD_H,
            "location_m": [0.0, -250.0 * COS, ZC + 250.0 * SIN],
            "look_direction": [0.0, COS, -SIN],
        },
        "markers_m": marks,
        "layers": {name: sorted(o.name for o in colls[name].objects) for name in LAYERS},
        "lights": lights_json(),
    }
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    print(f"AMN_EXPORT meshes={sum(1 for o in bpy.data.objects if o.type == 'MESH')} texts={converted} baked={baked} haze_dropped={len(haze)} lights={len(meta['lights'])} -> {a.out}")


main()
