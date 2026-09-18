"""
The bus-shelter clock of the live headquarters (/Game/HQ/HQ_Dusk) shows the real time.

Until now its face carried "15:18" as built geometry (hq_city.py CLOCK_TIME, the mesh
clock_digits_mesh with its emission baked into a texture): the picture's time, shown all day.
This pass hides that mesh and puts a display on the same face whose material works out hh:mm
itself, from the engine's game time plus one scalar the backend sets, ClockOffsetS:

    shown time = (game time + ClockOffsetS) mod 86400, as hh:mm

The backend is the source of the time. It sends ClockOffsetS = (local seconds of the day in
Europe/Bucharest) - (the game's world time) on every full refresh (20 s) and at a DST change, so
the display flips on the minute without the bridge having to send each minute (a 5 s tick plus
the Remote Control round trip would put it up to 7 s late), and if the backend stops, the face
drifts only by the frame clock's error instead of freezing. Until the first sync the material's
default is a sentinel and the face reads --:--, never the game's uptime dressed as a time.

The digits are drawn here, seven-segment, with numpy (no font, so no font licence), in the mint
of today's display (#7df0c4) at the strength today's baked digits have (EmissiveStrength 4.357,
read off their material when it is found). The atlas also holds a minus and a degree sign so a
second line can show the temperature later; that line waits for the Owner's approval of its look
and place (decision D3), so nothing here shows a temperature.

Two ways to run it:

  py -3.11 art-source/unreal/clock_hq_live.py --atlas [art-source/unreal/clock_digits_atlas.png]
      draws the digit atlas (outside Unreal: the editor's Python has no numpy of its own)
  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=clock_hq_live.py
      hides the baked digits and places the display, with the stream stopped

Importing this file outside Unreal does nothing (tests/test_clock_atlas.py imports it).
"""

import json
import math
import os
import sys

try:
    import unreal
except ImportError:  # the atlas step and the tests run in a plain Python
    unreal = None

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
ATLAS_PNG = os.path.join(HERE, "clock_digits_atlas.png")
AXIS_MAP = os.path.join(HERE, "axis_map.json")
FOLDER = "/Game/HQ/Clock"
TEXTURE = f"{FOLDER}/T_HQ_ClockDigits"
MATERIAL = f"{FOLDER}/M_HQ_DigitDisplay"
LABEL = "ClockDisplay"
BAKED_LABEL = "clock_digits_mesh"
TAG = "AMN_CLOCK"

# ---------------------------------------------------------------- the digits

# The atlas: one cell per glyph, left to right. 0-9, the colon, a blank, a minus and a degree sign
# (for the temperature line D3 may add), padded with blanks to 16 so the texture is a power of two
# and keeps its mips at the few pixels the face covers in the frame.
GLYPH_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", " ", "-", "°", " ", " "]
GLYPH_INDEX = {g: i for i, g in enumerate(GLYPH_ORDER[:14])}
CELLS = len(GLYPH_ORDER)
CELL_W, CELL_H = 64, 128
SUPERSAMPLE = 4

#  aaa
# f   b
#  ggg
# e   c
#  ddd
SEGMENTS = {
    "0": set("abcdef"), "1": set("bc"), "2": set("abdeg"), "3": set("abcdg"), "4": set("bcfg"),
    "5": set("acdfg"), "6": set("acdefg"), "7": set("abc"), "8": set("abcdefg"), "9": set("abcdfg"),
    "-": set("g"), "°": set("abfg"), " ": set(), ":": set(),
}

# The glyph box inside a 64 x 128 cell. At least 4 px stay empty on every side so the lower mips do
# not bleed one glyph into the next.
BOX_X0, BOX_X1, BOX_Y0, BOX_Y1 = 12.0, 52.0, 12.0, 116.0
THICK = 9.0
GAP = 1.5


def _segment_mask(xs, ys, name):
    """Inside test of one bevelled segment (a hexagon: square across, pointed along)."""
    ym = (BOX_Y0 + BOX_Y1) / 2.0
    half_t = THICK / 2.0
    if name in "agd":
        cy = {"a": BOX_Y0 + half_t, "g": ym, "d": BOX_Y1 - half_t}[name]
        cx, half_len = (BOX_X0 + BOX_X1) / 2.0, (BOX_X1 - BOX_X0) / 2.0 - GAP
        along, across = abs(xs - cx), abs(ys - cy)
    else:
        cx = BOX_X0 + half_t if name in "fe" else BOX_X1 - half_t
        cy = (BOX_Y0 + ym) / 2.0 if name in "fb" else (ym + BOX_Y1) / 2.0
        half_len = (ym - BOX_Y0) / 2.0 - GAP
        along, across = abs(ys - cy), abs(xs - cx)
    return (across <= half_t) & (along + across <= half_len)


def draw_glyph(glyph):
    """One cell, 0..1 float, drawn at SUPERSAMPLE x and box-filtered down for soft edges."""
    import numpy as np

    n = SUPERSAMPLE
    ys, xs = np.mgrid[0 : CELL_H * n, 0 : CELL_W * n].astype(np.float64)
    xs, ys = (xs + 0.5) / n, (ys + 0.5) / n
    lit = np.zeros(xs.shape, bool)
    for name in SEGMENTS[glyph]:
        lit |= _segment_mask(xs, ys, name)
    if glyph == ":":
        cx = (BOX_X0 + BOX_X1) / 2.0
        for cy in (BOX_Y0 + (BOX_Y1 - BOX_Y0) * 0.3, BOX_Y0 + (BOX_Y1 - BOX_Y0) * 0.7):
            lit |= (abs(xs - cx) <= THICK / 2.0) & (abs(ys - cy) <= THICK / 2.0)
    return lit.reshape(CELL_H, n, CELL_W, n).mean(axis=(1, 3))


def digit_atlas():
    """The whole atlas, uint8 (CELL_H, CELL_W * CELLS): white segments on black."""
    import numpy as np

    cells = [draw_glyph(g) for g in GLYPH_ORDER]
    return np.round(np.hstack(cells) * 255.0).astype(np.uint8)


def atlas_cell(atlas, index):
    return atlas[:, index * CELL_W : (index + 1) * CELL_W]


def write_atlas(path):
    from PIL import Image

    atlas = digit_atlas()
    # RGB, white on black: imported with the engine's default (sRGB colour) settings, 0 and 255
    # survive the sRGB decode exactly and the sampler type is the default one
    Image.fromarray(atlas, "L").convert("RGB").save(path)
    print(f"AMN_CLOCK atlas {CELLS} glyphs of {CELL_W}x{CELL_H} -> {path} ({atlas.shape[1]}x{atlas.shape[0]})")


# ---------------------------------------------------------------- the time the material shows

# ClockOffsetS's default: far below any real offset (local seconds of day minus a game time of
# less than thirty years), so the face can tell "never synced" from any time of day.
UNSYNCED_OFFSET = -1.0e10
UNSYNCED_BELOW = -1.0e9
SLOTS = 5  # h h : m m

DIGIT_INPUTS = ("U", "V", "T", "Offset", "Cells")
# The material's Custom node: (U, V) on the digit box (0..1, V down), T the engine's game time,
# Offset the backend's ClockOffsetS. Returns the atlas UV of the glyph under this pixel; outside
# the box, the blank glyph. display_glyphs() below is the same arithmetic in Python, under test.
DIGIT_HLSL = f"""float g = 11.0;
if (U >= 0.0 && U <= 1.0 && V >= 0.0 && V <= 1.0)
{{
    float slot = min(floor(U * {SLOTS}.0), {SLOTS - 1}.0);
    if (Offset < {UNSYNCED_BELOW:.1e})
    {{
        g = (slot == 2.0) ? 10.0 : 12.0;
    }}
    else
    {{
        float s = T + Offset;
        s = s - floor(s / 86400.0) * 86400.0;
        float mins = floor(s / 60.0);
        float h = floor(mins / 60.0);
        float m = mins - h * 60.0;
        float d[{SLOTS}] = {{ floor(h / 10.0), h - floor(h / 10.0) * 10.0, 10.0, floor(m / 10.0), m - floor(m / 10.0) * 10.0 }};
        g = d[(int)slot];
    }}
}}
float lu = frac(saturate(U) * {SLOTS}.0);
return float2((g + lu) / Cells, V);"""


def display_glyphs(game_time_s, offset_s, float32=False):
    """The five glyph indices the face shows, by the material's own arithmetic. With float32 the
    sums are rounded as the GPU rounds them."""
    if float32:
        import numpy as np

        f = np.float32
    else:
        def f(x):
            return float(x)
    if offset_s < UNSYNCED_BELOW:
        return [12, 12, 10, 12, 12]
    s = f(f(game_time_s) + f(offset_s))
    s = f(s - f(math.floor(f(s / f(86400.0)))) * f(86400.0))
    mins = math.floor(f(s / f(60.0)))
    h = math.floor(mins / 60.0)
    m = mins - h * 60
    return [h // 10, h % 10, 10, m // 10, m % 10]


# ---------------------------------------------------------------- where the face is

# hq_lib.py's projection, which placed the clock in Blender: world pixels (1600 x 840 at scale 1)
# seen by an orthographic camera pitched 10 degrees down.
PPM = 28.0
SIN, COS = math.sin(math.radians(10.0)), math.cos(math.radians(10.0))
CX, CY = 800.0, 420.0
GROUND_ROW = 655.0
ZC = (GROUND_ROW - CY) / PPM / COS
WALK_Z = -0.7  # hq_city.py


def X(px):
    return (px - CX) / PPM


def Z(row, y=0.0):
    return ZC + ((CY - row) / PPM - y * SIN) / COS


def Y(row, z=0.0):
    return ((CY - row) / PPM - (z - ZC) * COS) / SIN


def project(p):
    v = p[1] * SIN + (p[2] - ZC) * COS
    return (CX + p[0] * PPM, CY - v * PPM)


def shelter_clock_face():
    """STREET["shelter_clock"]'s rect in Blender metres (hq_city.py): the clock box stands at
    columns 1408-1480 between rows 657 and 620, 0.3 m behind the shelter's front; the rect is
    columns 1411-1477 inset 8 cm top and bottom. The display lies in the plane the baked digits
    stood in, 2 cm in front of the box's face, facing the camera."""
    y_walk = Y(717, WALK_Z)
    sy0 = y_walk + 1.2
    z0, z1 = Z(657, sy0 + 0.3), Z(620, sy0 + 0.3)
    return {"x0": X(1411), "x1": X(1477), "z0": z0 + 0.08, "z1": z1 - 0.08, "y": sy0 + 0.28}


def digit_box(face, baked):
    """Where the digits go on the face: exactly where today's digits stand when their mesh is
    found (so the face reads as it did, same place, same size), else centred on the face at the
    size the Blender text was built at (0.55 of the box's height, about 0.8 of its width)."""
    if baked is not None:
        return dict(baked)
    cx = (face["x0"] + face["x1"]) / 2.0
    height = (face["z1"] - face["z0"] + 0.16) * 0.55 * 0.72  # the font's digit height is ~0.72 em
    width = (face["x1"] - face["x0"]) * 0.8
    cz = (face["z0"] + face["z1"]) / 2.0
    return {"x0": cx - width / 2.0, "x1": cx + width / 2.0, "z0": cz - height / 2.0, "z1": cz + height / 2.0}


def linear(hex_color):
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


MINT = "#7df0c4"  # hq_city.py emissive("clock_digits", "#7df0c4", 5.0): the display's colour today
TODAY_STRENGTH = 4.35684  # clock_digits_001's EmissiveStrength in the live level (2026-09-18)


# ---------------------------------------------------------------- inside Unreal


def log(msg):
    unreal.log(f"AMN_CLOCK {msg}")


class Axes:
    """Blender metres -> Unreal, as build_hq_scene.py measured them from its marker cubes
    (axis_map.json). Without that file, look_hq_live.py's convention (the importer maps Blender +y
    to Unreal -y, centimetres), which the same measurement gave."""

    def __init__(self):
        if os.path.exists(AXIS_MAP):
            m = json.load(open(AXIS_MAP, "r", encoding="utf-8"))
            self.o, self.bo = m["origin_unreal"], m["origin_scene_m"]
            self.ex, self.ey, self.ez = m["ex"], m["ey"], m["ez"]
            self.source = AXIS_MAP
        else:
            self.o, self.bo = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            self.ex, self.ey, self.ez = [100.0, 0.0, 0.0], [0.0, -100.0, 0.0], [0.0, 0.0, 100.0]
            self.source = "look_hq_live.py convention (no axis_map.json)"

    def point(self, p):
        d = [p[i] - self.bo[i] for i in range(3)]
        return [self.o[k] + self.ex[k] * d[0] + self.ey[k] * d[1] + self.ez[k] * d[2] for k in range(3)]

    def scene(self, u):
        """Unreal -> Blender metres (the inverse, for the axis-aligned maps the importer gives)."""
        out = [0.0, 0.0, 0.0]
        rel = [u[k] - self.o[k] for k in range(3)]
        for i, e in enumerate((self.ex, self.ey, self.ez)):
            n2 = sum(c * c for c in e)
            out[i] = self.bo[i] + sum(rel[k] * e[k] for k in range(3)) / n2
        return out


def aligned_axis(vector):
    """(index, sign) of the Unreal axis a scene axis runs along. The material reads one world
    coordinate per direction (the path the haze material already uses), so the map must be
    axis-aligned: the importer's is (measured ex=(100,0,0), ey=(0,-100,0), ez=(0,0,100))."""
    n = math.sqrt(sum(c * c for c in vector))
    k = max(range(3), key=lambda i: abs(vector[i]))
    if abs(vector[k]) / n < 0.999:
        raise RuntimeError(f"scene axis {vector} is not aligned with an Unreal axis")
    return k, 1.0 if vector[k] > 0 else -1.0


def baked_digits(actors, ax):
    """Today's digit mesh: its box in Blender metres and its emission strength."""
    actor = actors.get(BAKED_LABEL)
    if actor is None:
        return None, None, None
    origin, extent = actor.get_actor_bounds(False)
    lo = ax.scene([origin.x - extent.x, origin.y - extent.y, origin.z - extent.z])
    hi = ax.scene([origin.x + extent.x, origin.y + extent.y, origin.z + extent.z])
    box = {"x0": min(lo[0], hi[0]), "x1": max(lo[0], hi[0]), "z0": min(lo[2], hi[2]), "z1": max(lo[2], hi[2])}
    strength = None
    comp = actor.static_mesh_component
    mat = comp.get_material(0) if comp.get_num_materials() else None
    if isinstance(mat, unreal.MaterialInstanceConstant):
        try:
            strength = unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(mat, "EmissiveStrength")
        except Exception as err:
            log(f"baked digits' EmissiveStrength unreadable: {err}")
    return actor, box, strength


def import_atlas():
    if not os.path.exists(ATLAS_PNG):
        raise RuntimeError(f"{ATLAS_PNG} missing: run `py -3.11 clock_hq_live.py --atlas` first")
    task = unreal.AssetImportTask()
    task.filename = ATLAS_PNG
    task.destination_path = FOLDER
    task.destination_name = TEXTURE.rsplit("/", 1)[-1]
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(TEXTURE)
    if texture is None:
        raise RuntimeError(f"could not import {ATLAS_PNG}")
    return texture


def digit_material(texture, strength, right, down, placement):
    """Masked, unlit, two-sided: the segments glow, the clock box shows between them. Parameters:
    ClockOffsetS (the backend's), EmissiveStrength, and where the digit box lies in world space
    (BoxOriginU/V in cm along the Unreal axes the scene's +x and -z run on, BoxScaleU/V)."""
    mel = unreal.MaterialEditingLibrary
    mat = None
    if unreal.EditorAssetLibrary.does_asset_exist(MATERIAL):
        mat = unreal.load_asset(MATERIAL)
        mel.delete_all_material_expressions(mat)
    if mat is None:
        folder, name = MATERIAL.rsplit("/", 1)
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("two_sided", True)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", value)
        return n

    def along(axis, origin_name, scale_name, y):
        pos = node(unreal.MaterialExpressionWorldPosition, -1400, y)
        mask = node(unreal.MaterialExpressionComponentMask, -1200, y)
        for i, c in enumerate(("r", "g", "b", "a")):
            mask.set_editor_property(c, i == axis)
        mel.connect_material_expressions(pos, "", mask, "")
        rel = node(unreal.MaterialExpressionSubtract, -1000, y)
        mel.connect_material_expressions(mask, "", rel, "A")
        mel.connect_material_expressions(scalar(origin_name, float(placement[origin_name]), -1200, y + 120), "", rel, "B")
        out = node(unreal.MaterialExpressionMultiply, -800, y)
        mel.connect_material_expressions(rel, "", out, "A")
        mel.connect_material_expressions(scalar(scale_name, float(placement[scale_name]), -1000, y + 120), "", out, "B")
        return out

    u = along(right[0], "BoxOriginU", "BoxScaleU", -300)
    v = along(down[0], "BoxOriginV", "BoxScaleV", 0)
    time = node(unreal.MaterialExpressionTime, -800, 250)
    offset = scalar("ClockOffsetS", UNSYNCED_OFFSET, -800, 350)
    cells = node(unreal.MaterialExpressionConstant, -800, 450)
    cells.set_editor_property("r", float(CELLS))
    custom = node(unreal.MaterialExpressionCustom, -550, 0)
    custom.set_editor_property("code", DIGIT_HLSL)
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT2)
    custom.set_editor_property("description", "hh:mm from game time + ClockOffsetS")
    inputs = []
    for name in DIGIT_INPUTS:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", name)
        inputs.append(ci)
    custom.set_editor_property("inputs", inputs)
    for src, name in ((u, "U"), (v, "V"), (time, "T"), (offset, "Offset"), (cells, "Cells")):
        if not mel.connect_material_expressions(src, "", custom, name):
            raise RuntimeError(f"could not wire the clock's {name} input")

    sample = node(unreal.MaterialExpressionTextureSampleParameter2D, -300, 0)
    sample.set_editor_property("parameter_name", "DigitAtlas")
    sample.set_editor_property("texture", texture)
    mel.connect_material_expressions(custom, "", sample, "UVs")
    mel.connect_material_property(sample, "R", unreal.MaterialProperty.MP_OPACITY_MASK)
    colour = node(unreal.MaterialExpressionVectorParameter, -300, 250)
    colour.set_editor_property("parameter_name", "DisplayColor")
    r, g, b = linear(MINT)
    colour.set_editor_property("default_value", unreal.LinearColor(r, g, b, 1.0))
    lit = node(unreal.MaterialExpressionMultiply, -100, 150)
    mel.connect_material_expressions(sample, "R", lit, "A")
    mel.connect_material_expressions(colour, "RGB", lit, "B")
    glow = node(unreal.MaterialExpressionMultiply, 50, 150)
    mel.connect_material_expressions(lit, "", glow, "A")
    mel.connect_material_expressions(scalar("EmissiveStrength", strength, -100, 300), "", glow, "B")
    mel.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in eas.get_all_level_actors():
        if TAG in [str(t) for t in actor.get_editor_property("tags")]:
            eas.destroy_actor(actor)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    ax = Axes()
    right, down = aligned_axis(ax.ex), aligned_axis([-c for c in ax.ez])
    face = shelter_clock_face()
    baked, baked_box, baked_strength = baked_digits(actors, ax)
    box = digit_box(face, baked_box)
    strength = baked_strength if baked_strength else TODAY_STRENGTH
    if baked is not None:
        # hidden, not destroyed: the level keeps it, and showing it again is one allow-listed call
        baked.set_actor_hidden_in_game(True)
        baked.set_editor_property("tags", [unreal.Name(TAG + "_BAKED")])
    log(f"baked digits {'hidden' if baked else 'NOT FOUND'}; digit box x {box['x0']:.2f}..{box['x1']:.2f} m, "
        f"z {box['z0']:.2f}..{box['z1']:.2f} m ({'from the baked mesh' if baked_box else 'from the face'}); axes {ax.source}")

    texture = import_atlas()
    top_left = ax.point((box["x0"], face["y"], box["z1"]))
    width_cm = (box["x1"] - box["x0"]) * math.sqrt(sum(c * c for c in ax.ex))
    height_cm = (box["z1"] - box["z0"]) * math.sqrt(sum(c * c for c in ax.ez))
    # the box's corner and size are the material's own defaults: one display, one set of numbers
    placement = {"BoxOriginU": top_left[right[0]], "BoxScaleU": right[1] / width_cm,
                 "BoxOriginV": top_left[down[0]], "BoxScaleV": down[1] / height_cm}
    mat = digit_material(texture, strength, right, down, placement)

    # The carrier: the engine's 1 m plane, lying in the face's plane over the whole face (the
    # material masks everything but the segments, so the clock box shows around them).
    centre = ax.point(((face["x0"] + face["x1"]) / 2.0, face["y"], (face["z0"] + face["z1"]) / 2.0))
    normal = [-c for c in ax.ey]  # towards the camera: the scene's -y
    rot = unreal.MathLibrary.make_rot_from_zx(unreal.Vector(*normal), unreal.Vector(*ax.ex))
    display = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*centre), rot)
    display.set_actor_label(LABEL)
    display.set_editor_property("tags", [unreal.Name(TAG)])
    comp = display.static_mesh_component
    comp.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Plane"))
    comp.set_material(0, mat)
    comp.set_cast_shadow(False)
    unit_x = math.sqrt(sum(c * c for c in ax.ex)) / 100.0
    unit_z = math.sqrt(sum(c * c for c in ax.ez)) / 100.0
    display.set_actor_scale3d(unreal.Vector((face["x1"] - face["x0"]) * unit_x, (face["z1"] - face["z0"]) * unit_z, 1.0))
    comp.set_mobility(unreal.ComponentMobility.STATIC)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory(FOLDER)
    log(f"display {display.get_path_name()} at ({centre[0]:.0f},{centre[1]:.0f},{centre[2]:.0f}), "
        f"{width_cm:.0f} x {height_cm:.0f} cm of digits, #7df0c4 x{strength:.3f}; ClockOffsetS unsynced "
        f"until the backend's first refresh (the face reads --:--)")


if unreal is not None:
    main()
elif __name__ == "__main__":
    if "--atlas" in sys.argv:
        i = sys.argv.index("--atlas")
        target = sys.argv[i + 1] if i + 1 < len(sys.argv) else ATLAS_PNG
        write_atlas(target)
    else:
        print(__doc__)
