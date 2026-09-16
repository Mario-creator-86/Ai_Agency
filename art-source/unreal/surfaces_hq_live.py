"""
Unreal Engine 5.8 editor script: real surfaces on the live headquarters (/Game/HQ/HQ_Dusk).

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=surfaces_hq_live.py

The building is modelled in Blender and exported with every material baked into one flat-colour
atlas per mesh. That carries the layout and the painted detail - the labels, the brick courses, the
room colours - but no grain, no weave and no wear: measured against the Owner's picture our rooms
carry about 1800 units of fine detail where his carries 3100, and by eye the walls read as painted
card.

This pass keeps the baked colour and adds the material on top of it. Each surface named in
hq_surfaces.json gets an instance of one master material (M_HQ_Surface) that samples:

  - the mesh's own baked atlas on UV0, exactly as the glTF material did (so nothing painted is lost);
  - a tiling detail colour, normal and roughness from the packs, projected on world axes at a size
    given in centimetres, so the grain is the same on every wall whatever its UVs.

Base colour is the baked colour times the detail (around its own mean, so the surface keeps its
brightness), the normal comes from the detail set, and roughness is mapped between two values per
surface. AMN_SURF_DETAIL scales every detail strength at once (0 gives back a flat surface but keeps
the normals), AMN_SURF=0 skips the pass.
"""

import json
import os
import re

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
MASTER = "/Game/HQ/Materials/M_HQ_Surface"
TABLE = os.path.join(HERE, "hq_surfaces.json")
FOLDER = "/Game/HQ/Materials"
WHITE = "/Engine/EngineResources/WhiteSquareTexture"
FLAT_NORMAL = "/Engine/EngineMaterials/DefaultNormal"


def env(name, default):
    return float(os.environ.get(name, default))


ON = env("AMN_SURF", "1")
DETAIL = env("AMN_SURF_DETAIL", "1")


def log(msg):
    unreal.log(f"AMN_SURF {msg}")


def base_name(name):
    """'wall_l2_001' -> 'wall_l2': the importer numbers the Blender materials it brings in."""
    return re.sub(r"_\d+$", "", str(name).lower())


def master_material():
    """Baked colour (UV0) x tiling detail (world axes), with the detail's normal and roughness."""
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(MASTER):
        mat = unreal.load_asset(MASTER)
        mel.delete_all_material_expressions(mat)
    else:
        folder, name = MASTER.rsplit("/", 1)
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, folder, unreal.Material, unreal.MaterialFactoryNew())
    white = unreal.load_asset(WHITE)
    flat = unreal.load_asset(FLAT_NORMAL)

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x, y)

    def scalar(name, value, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", value)
        return n

    def sampler(name, texture, x, y, sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_COLOR):
        n = node(unreal.MaterialExpressionTextureSampleParameter2D, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("texture", texture)
        n.set_editor_property("sampler_type", sampler_type)
        return n

    # ---- world-aligned UVs: (x, z) up a wall, (x, y) across a floor, chosen per instance
    pos = node(unreal.MaterialExpressionWorldPosition, -1700, 0)
    parts = {}
    for key, channels in (("x", "r"), ("y", "g"), ("z", "b")):
        m = node(unreal.MaterialExpressionComponentMask, -1500, {"x": -200, "y": 0, "z": 200}[key])
        for c in ("r", "g", "b", "a"):
            m.set_editor_property(c, c == channels)
        mel.connect_material_expressions(pos, "", m, "")
        parts[key] = m
    wall_uv = node(unreal.MaterialExpressionAppendVector, -1300, -150)
    mel.connect_material_expressions(parts["x"], "", wall_uv, "A")
    mel.connect_material_expressions(parts["z"], "", wall_uv, "B")
    floor_uv = node(unreal.MaterialExpressionAppendVector, -1300, 100)
    mel.connect_material_expressions(parts["x"], "", floor_uv, "A")
    mel.connect_material_expressions(parts["y"], "", floor_uv, "B")
    projection = scalar("Projection", 0.0, -1300, 300)   # 0 wall (x, z), 1 floor (x, y)
    picked = node(unreal.MaterialExpressionLinearInterpolate, -1100, 0)
    mel.connect_material_expressions(wall_uv, "", picked, "A")
    mel.connect_material_expressions(floor_uv, "", picked, "B")
    mel.connect_material_expressions(projection, "", picked, "Alpha")
    tile = scalar("TileCm", 200.0, -1100, 250)
    uv = node(unreal.MaterialExpressionDivide, -900, 0)
    mel.connect_material_expressions(picked, "", uv, "A")
    mel.connect_material_expressions(tile, "", uv, "B")

    # ---- the mesh's own baked colour, on the UVs the exporter wrote
    baked = sampler("BakedColor", white, -900, -450)
    tint = node(unreal.MaterialExpressionVectorParameter, -900, -650)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

    # ---- the tiling detail set
    detail = sampler("DetailColor", white, -700, 150)
    mel.connect_material_expressions(uv, "", detail, "UVs")
    normal = sampler("DetailNormal", flat, -700, 500, unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    mel.connect_material_expressions(uv, "", normal, "UVs")
    rough = sampler("DetailRough", white, -700, 850, unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    mel.connect_material_expressions(uv, "", rough, "UVs")

    # The detail texture has a brightness of its own, and it must not change the surface's: the same
    # texture is sampled again at its smallest mip, which is its own average colour, and the pattern
    # is the ratio between the two. So any texture, dark or pale, only adds grain. DetailStrength
    # fades the whole thing towards white.
    # The mip is set as the node's own constant, not through a wire: a wire into "MipLevel" is
    # accepted silently and does nothing, which leaves both samples identical and the whole ratio
    # at 1 (measured: detail strength 0 and 1 gave the same frame).
    average = sampler("DetailColorAverage", white, -700, 350)
    average.set_editor_property("mip_value_mode", unreal.TextureMipValueMode.TMVM_MIP_LEVEL)
    average.set_editor_property("const_mip_value", 14.0)
    mel.connect_material_expressions(uv, "", average, "UVs")
    over = node(unreal.MaterialExpressionDivide, -500, 200)
    mel.connect_material_expressions(detail, "", over, "A")
    mel.connect_material_expressions(average, "", over, "B")
    one = node(unreal.MaterialExpressionConstant, -500, 380)
    one.set_editor_property("r", 1.0)
    strength = scalar("DetailStrength", 1.0, -500, 450)
    faded = node(unreal.MaterialExpressionLinearInterpolate, -350, 250)
    mel.connect_material_expressions(one, "", faded, "A")
    mel.connect_material_expressions(over, "", faded, "B")
    mel.connect_material_expressions(strength, "", faded, "Alpha")

    colour = node(unreal.MaterialExpressionMultiply, -200, -200)
    mel.connect_material_expressions(baked, "", colour, "A")
    mel.connect_material_expressions(tint, "", colour, "B")
    lit = node(unreal.MaterialExpressionMultiply, -60, -100)
    mel.connect_material_expressions(colour, "", lit, "A")
    mel.connect_material_expressions(faded, "", lit, "B")
    mel.connect_material_property(lit, "", unreal.MaterialProperty.MP_BASE_COLOR)

    # The glTF material did two more things and both have to be carried over, or the surface changes
    # even with no detail at all: it multiplied its atlas by a colour factor (the export writes the
    # material's own colour there, as dark as 0.04 on a floor), and it lit itself from a baked
    # emission atlas. Dropping them once cost 6 units of mean colour distance - the ground floor read
    # 80 against the picture's 68 while L3 read 67 against 80.
    emit_tex = sampler("EmissiveTexture", white, -900, -900)
    emit_factor = node(unreal.MaterialExpressionVectorParameter, -900, -1100)
    emit_factor.set_editor_property("parameter_name", "EmissiveFactor")
    emit_factor.set_editor_property("default_value", unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    emit_strength = scalar("EmissiveStrength", 1.0, -900, -1250)
    emit_a = node(unreal.MaterialExpressionMultiply, -600, -1000)
    mel.connect_material_expressions(emit_tex, "", emit_a, "A")
    mel.connect_material_expressions(emit_factor, "", emit_a, "B")
    emit_b = node(unreal.MaterialExpressionMultiply, -400, -1000)
    mel.connect_material_expressions(emit_a, "", emit_b, "A")
    mel.connect_material_expressions(emit_strength, "", emit_b, "B")
    mel.connect_material_property(emit_b, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    # FlattenNormal is a material function, not an expression: the same thing is a lerp towards the
    # flat normal (0, 0, 1), with NormalFlatten at 0 keeping the set's own.
    straight = node(unreal.MaterialExpressionConstant3Vector, -500, 560)
    straight.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0))
    flat_amount = scalar("NormalFlatten", 0.0, -500, 680)
    flatten = node(unreal.MaterialExpressionLinearInterpolate, -350, 550)
    mel.connect_material_expressions(normal, "", flatten, "A")
    mel.connect_material_expressions(straight, "", flatten, "B")
    mel.connect_material_expressions(flat_amount, "", flatten, "Alpha")
    mel.connect_material_property(flatten, "", unreal.MaterialProperty.MP_NORMAL)

    # Which channel carries roughness is a per-pack convention: a plain grayscale map is in red, an
    # ORM map keeps it in green. RoughMask picks it out per instance.
    mask = node(unreal.MaterialExpressionVectorParameter, -500, 780)
    mask.set_editor_property("parameter_name", "RoughMask")
    mask.set_editor_property("default_value", unreal.LinearColor(1.0, 0.0, 0.0, 0.0))
    picked_rough = node(unreal.MaterialExpressionDotProduct, -350, 820)
    mel.connect_material_expressions(rough, "RGB", picked_rough, "A")
    mel.connect_material_expressions(mask, "RGB", picked_rough, "B")
    low = scalar("RoughLow", 0.25, -500, 900)
    high = scalar("RoughHigh", 0.75, -500, 1000)
    rough_mix = node(unreal.MaterialExpressionLinearInterpolate, -200, 900)
    mel.connect_material_expressions(low, "", rough_mix, "A")
    mel.connect_material_expressions(high, "", rough_mix, "B")
    mel.connect_material_expressions(picked_rough, "", rough_mix, "Alpha")
    mel.connect_material_property(rough_mix, "", unreal.MaterialProperty.MP_ROUGHNESS)

    metal = scalar("Metallic", 0.0, -300, 1100)
    mel.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)

    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


def texture(path):
    if not path:
        return None
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        log(f"texture missing: {path}")
        return None
    return unreal.load_asset(path)


def instance(parent, key, spec, carried):
    """One instance per (surface, baked atlas): the atlas differs from mesh to mesh."""
    mel = unreal.MaterialEditingLibrary
    baked_texture = carried.get("baked")
    stem = baked_texture.get_name() if baked_texture else "flat"
    path = f"{FOLDER}/MI_HQ_Surf_{key}_{stem}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        mi = unreal.load_asset(path)
    else:
        folder, name = path.rsplit("/", 1)
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, parent)
    if baked_texture is not None:
        mel.set_material_instance_texture_parameter_value(mi, "BakedColor", baked_texture)
    for param, path_key in (("DetailColor", "base"), ("DetailColorAverage", "base"),
                            ("DetailNormal", "normal"), ("DetailRough", "roughness")):
        tex = texture(spec.get(path_key))
        if tex is not None:
            mel.set_material_instance_texture_parameter_value(mi, param, tex)
    # the colour factor, the emission and its strength, exactly as the glTF material had them
    factor = carried.get("base_factor")
    if factor is None:
        tint = spec.get("tint") or [1.0, 1.0, 1.0]
        factor = unreal.LinearColor(tint[0], tint[1], tint[2], 1.0)
    mel.set_material_instance_vector_parameter_value(mi, "Tint", factor)
    emissive = carried.get("emissive_factor")
    mel.set_material_instance_vector_parameter_value(
        mi, "EmissiveFactor", emissive if emissive is not None else unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    strength = carried.get("emissive_strength")
    mel.set_material_instance_scalar_parameter_value(mi, "EmissiveStrength", 1.0 if strength is None else float(strength))
    emissive_texture = carried.get("emissive_texture")
    if emissive_texture is not None:
        mel.set_material_instance_texture_parameter_value(mi, "EmissiveTexture", emissive_texture)
    mel.set_material_instance_scalar_parameter_value(mi, "TileCm", float(spec.get("tile_cm", 200)))
    mel.set_material_instance_scalar_parameter_value(mi, "Projection", 1.0 if spec.get("projection") == "floor" else 0.0)
    mel.set_material_instance_scalar_parameter_value(mi, "DetailStrength", float(spec.get("strength", 1.0)) * DETAIL)
    rough_mask = spec.get("rough_mask") or [1.0, 0.0, 0.0]
    mel.set_material_instance_vector_parameter_value(
        mi, "RoughMask", unreal.LinearColor(rough_mask[0], rough_mask[1], rough_mask[2], 0.0))
    mel.set_material_instance_scalar_parameter_value(mi, "NormalFlatten", float(spec.get("flatten", 0.0)))
    mel.set_material_instance_scalar_parameter_value(mi, "RoughLow", float(spec.get("rough_low", 0.25)))
    mel.set_material_instance_scalar_parameter_value(mi, "RoughHigh", float(spec.get("rough_high", 0.75)))
    mel.set_material_instance_scalar_parameter_value(mi, "Metallic", float(spec.get("metallic", 0.0)))
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    return mi


def overrides_of(material, kind):
    """What the glTF import wrote on this instance: {parameter name in lower case: value}, read off
    the instance's own override list (the library getters are not in every engine build)."""
    out = {}
    try:
        for entry in material.get_editor_property(f"{kind}_parameter_values"):
            name = str(entry.get_editor_property("parameter_info").get_editor_property("name")).lower()
            out[name] = entry.get_editor_property("parameter_value")
    except Exception as err:
        log(f"reading the {kind} parameters off {material.get_name()}: {err}")
    return out


def carried_over(material):
    """The atlas, the colour factor and the baked emission, so the new material keeps painting what
    the glTF one painted."""
    textures = overrides_of(material, "texture")
    vectors = overrides_of(material, "vector")
    scalars = overrides_of(material, "scalar")
    return {
        "baked": textures.get("basecolortexture"),
        "emissive_texture": textures.get("emissivetexture"),
        "base_factor": vectors.get("basecolorfactor"),
        "emissive_factor": vectors.get("emissivefactor"),
        "emissive_strength": scalars.get("emissivestrength"),
    }


def main():
    if ON <= 0:
        log("skipped (AMN_SURF=0)")
        return
    if not os.path.exists(TABLE):
        log(f"no surface table at {TABLE}: nothing to do")
        return
    table = {base_name(k): v for k, v in json.load(open(TABLE, "r", encoding="utf-8")).items()}
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    parent = master_material()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    made = {}
    done = 0
    seen = set()
    flat_only = set()
    for actor in eas.get_all_level_actors():
        if not isinstance(actor, unreal.StaticMeshActor):
            continue
        comp = actor.static_mesh_component
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if mat is None:
                continue
            key = base_name(mat.get_name())
            if key.startswith("mi_hq_surf"):
                continue
            spec = table.get(key)
            if spec is None:
                continue
            seen.add(key)
            carried = carried_over(mat) if isinstance(mat, unreal.MaterialInstanceConstant) else {}
            baked = carried.get("baked")
            # Without the atlas the new material would paint the surface white and lose everything
            # the bake carried, so the slot keeps the material it has.
            if baked is None and not spec.get("allow_flat"):
                if key not in flat_only:
                    flat_only.add(key)
                    log(f"{key}: no baked atlas on {mat.get_name()}, left as it is")
                continue
            cache_key = (key, baked.get_path_name() if baked else "flat")
            mi = made.get(cache_key)
            if mi is None:
                mi = instance(parent, key, spec, carried)
                made[cache_key] = mi
            comp.set_material(i, mi)
            done += 1
    les.save_current_level()
    missing = sorted(set(table) - seen)
    log(f"real surfaces on {done} slots, {len(made)} instances, detail x{DETAIL:g}")
    if missing:
        log(f"not found in the level: {', '.join(missing)}")


main()
