"""
Unreal Engine 5.8 editor script (PREPARED 2026-09-24, NEVER RUN YET): the skyline's towers and the
near blocks' facades get a day state, in place on the saved level, with the stream stopped:

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=<this file>

Run after look_hq_live.py (and after a rebuild's whole chain). Inputs: the mask/rank textures and
towers_day.json that towers_day.py wrote (AMN_TOWER_MASKS, default ./textures beside this file).

What it does, and why it cannot change today's dusk:
- Each facade slot (tower_*, city_*, classic, shopfront_block: hq_day.FACADES) keeps the glTF
  instance the import gave it and every value on it. Like the room windows (look_hq_live
  window_views), the instance is duplicated onto a versioned copy of its own parent chain
  (MI_Default_Opaque_DS -> M_Default, the Interchange glTF masters) whose master differs from the
  original only by nodes inserted at its outputs:
    base colour  lerp(original, day facade colour, TowerDaylight)
    emissive     original x saturate((WindowsOn - rank) x 50) + SkyTint x GlassSky x glass x TowerDaylight
    metallic     lerp(original, lerp(DayWallMetallic, DayMetallic, glass), TowerDaylight)
    roughness    lerp(original, DayRoughness, TowerDaylight)
  with TowerDaylight 0 and WindowsOn 1 by default. At those values every lerp returns its first
  input and the gate is exactly 1 (every stored rank <= 0.95, (1 - 0.95) x 50 >= 1), so the facade
  is painted by the untouched original graph. The old instance's values are compared with the new
  one's and the pass fails on any difference (window_view.differences).
- The day facade colour is hq_day.py's own (FACADES wall/glass, TOWER_ROOF on faces whose world
  normal points up), the glass mask and each window's rank come from the export's own window
  textures (towers_day.py), sampled on the facade's own UV (its BaseColorTexture_TexCoord and
  _OffsetScale), so the day picture lines up with the dusk one texel for texel.
- Nothing moves until something writes TowerDaylight / WindowsOn. The backend does not know them
  yet (backend_day_state.patch); the window's drive_day_extra.py sets them for the previews.

AMN_TOWER_SKY (default 0) is the strength of the day sky tint on the glass (SkyTint = the page's
noon horizon, hq_time.js SKY.day #cfe2f3); a window variant, off unless it is judged better.
AMN_TOWER_WALL_METAL (default 0) is the walls' metallic by day; hq_day.py uses 0.3 on the whole
facade, which in Cycles reflects a bright sky and in this level would reflect a dark one.
AMN_TOWER_SURFACES (default 1) gives the skyline's plain slots their day colour where hq_day.py has
one (SURFACES: the bridge); they are M_HQ_CityDay instances and follow Daylight on the skyline.
"""

import datetime
import importlib.util
import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("AMN_REPO", r"E:/AI Acency/Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP")
UNREAL_DIR = os.path.join(REPO, "art-source", "unreal")
LEVEL = "/Game/HQ/HQ_Dusk"
MASKS = os.environ.get("AMN_TOWER_MASKS", os.path.join(HERE, "textures"))
FACTS = json.load(open(os.path.join(MASKS, "towers_day.json"), "r", encoding="utf-8"))
REPORT = os.environ.get("AMN_TOWER_REPORT", os.path.join(HERE, "towers_report.json"))
TEXTURE_FOLDER = "/Game/HQ/Materials/Towers"
COPY_FOLDER = "/Game/HQ/Materials"
GRAPH_VERSION = 1
COPY_PREFIX = "M_HQ_TowerDay_"
INSTANCE_PREFIX = "MI_HQ_TowerDay_"
COMPONENT_LABELS = ("skyline", "near_blocks")
SKY = float(os.environ.get("AMN_TOWER_SKY", "0"))
WALL_METAL = float(os.environ.get("AMN_TOWER_WALL_METAL", "0"))
SURFACES = os.environ.get("AMN_TOWER_SURFACES", "1") == "1"
SKY_TINT = (0.604, 0.761, 0.905)  # hq_time.js SKY.day #cfe2f3, linear
RANK = FACTS["rank"]
ADDED_SCALARS = {"TowerDaylight": 0.0, "WindowsOn": 1.0, "TowerTexCoord": 1.0, "DayMetallic": 0.0,
                 "DayWallMetallic": 0.0, "DayRoughness": 0.35, "GlassSky": 0.0}
ADDED_VECTORS = {"DayWall": (1, 1, 1, 1), "DayGlass": (1, 1, 1, 1), "TowerRoof": (1, 1, 1, 1),
                 "TowerOffsetScale": (0, 0, 1, 1), "SkyTint": (1, 1, 1, 1)}

_wspec = importlib.util.spec_from_file_location("window_view", os.path.join(UNREAL_DIR, "window_view.py"))
_window = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(_window)
_cspec = importlib.util.spec_from_file_location("city_emissive", os.path.join(UNREAL_DIR, "city_emissive.py"))
_city = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(_city)

mel = unreal.MaterialEditingLibrary


def log(msg):
    unreal.log(f"AMN_TOWERS {msg}")


def facade_name(material_name):
    name = str(material_name)
    if name.startswith(INSTANCE_PREFIX):
        name = name[len(INSTANCE_PREFIX):]
    base = name.lower().rstrip("0123456789").rstrip("_")
    return base if base in FACTS["facades"] else None


def mask_texture(name):
    path = f"{TEXTURE_FOLDER}/T_HQ_TowerMask_{name}"
    source = FACTS["facades"][name]["texture"]
    if not os.path.exists(source):
        source = os.path.join(MASKS, f"T_HQ_TowerMask_{name}.png")
    task = unreal.AssetImportTask()
    task.filename = source
    task.destination_path = TEXTURE_FOLDER
    task.destination_name = f"T_HQ_TowerMask_{name}"
    task.automated = True
    task.replace_existing = True
    task.save = False
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = unreal.load_asset(path)
    if tex is None:
        raise RuntimeError(f"could not import {source} to {path}")
    # data, not colour: linear, uncompressed (a rank must survive to within 1/255)
    tex.set_editor_property("srgb", False)
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    return tex


def values(mat):
    out = {}
    for n in mel.get_scalar_parameter_names(mat):
        out[f"scalar:{n}"] = float(mel.get_material_instance_scalar_parameter_value(mat, n))
    for n in mel.get_vector_parameter_names(mat):
        c = mel.get_material_instance_vector_parameter_value(mat, n)
        out[f"vector:{n}"] = (c.r, c.g, c.b, c.a)
    for n in mel.get_texture_parameter_names(mat):
        t = mel.get_material_instance_texture_parameter_value(mat, n)
        out[f"texture:{n}"] = t.get_path_name() if t else None
    for n in mel.get_static_switch_parameter_names(mat):
        out[f"switch:{n}"] = bool(mel.get_material_instance_static_switch_parameter_value(mat, n))
    return out


def _package(obj):
    return obj.get_path_name().split(".", 1)[0]


def extend_master(mat, default_mask):
    """The inserted nodes (module docstring). Refuses (raises) when an output cannot be taken over
    as it is; metallic and roughness are optional (left alone when nothing drives them)."""
    if mat.get_editor_property("use_material_attributes"):
        raise RuntimeError(f"{mat.get_path_name()} uses material attributes")
    P = unreal.MaterialProperty
    originals = {}
    for prop, required in ((P.MP_BASE_COLOR, True), (P.MP_EMISSIVE_COLOR, True), (P.MP_METALLIC, False), (P.MP_ROUGHNESS, False)):
        node = mel.get_material_property_input_node(mat, prop)
        output = mel.get_material_property_input_node_output_name(mat, prop)
        if node is None:
            if required:
                raise RuntimeError(f"{mat.get_path_name()}: nothing drives {prop}")
            log(f"{prop} is not driven in {mat.get_name()}: left alone")
            continue
        if output == "" and len(mel.get_material_expression_output_names(node)) > 1:
            raise RuntimeError(f"{mat.get_path_name()}: {prop} comes from an unnamed output of {node.get_name()}")
        originals[prop] = (node, output)

    x0, y0 = 1600, -2400

    def node(cls, x, y):
        return mel.create_material_expression(mat, cls, x0 + x, y0 + y)

    def link(a, a_out, b, b_in):
        if not mel.connect_material_expressions(a, a_out, b, b_in):
            raise RuntimeError(f"could not connect {a.get_name()}.{a_out} -> {b.get_name()}.{b_in}")

    def scalar(name, x, y):
        n = node(unreal.MaterialExpressionScalarParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", ADDED_SCALARS[name])
        return n

    def vector(name, x, y):
        n = node(unreal.MaterialExpressionVectorParameter, x, y)
        n.set_editor_property("parameter_name", name)
        n.set_editor_property("default_value", unreal.LinearColor(*ADDED_VECTORS[name]))
        return n

    def op(cls, a, a_out, b, b_out, x, y):
        n = node(cls, x, y)
        link(a, a_out, n, "A")
        link(b, b_out, n, "B")
        return n

    def lerp(a, a_out, b, b_out, alpha, alpha_out, x, y):
        n = node(unreal.MaterialExpressionLinearInterpolate, x, y)
        link(a, a_out, n, "A")
        link(b, b_out, n, "B")
        link(alpha, alpha_out, n, "Alpha")
        return n

    def saturate(a, a_out, x, y):
        n = node(unreal.MaterialExpressionSaturate, x, y)
        link(a, a_out, n, "")
        return n

    def times_const(a, a_out, k, x, y):
        n = node(unreal.MaterialExpressionMultiply, x, y)
        link(a, a_out, n, "A")
        n.set_editor_property("const_b", k)
        return n

    def append(a, a_out, b, b_out, x, y):
        return op(unreal.MaterialExpressionAppendVector, a, a_out, b, b_out, x, y)

    # the facade's own UV: lerp(UV0, UV1, TowerTexCoord) x scale + offset (glTF OffsetScale = r,g offset; b,a scale)
    uv0 = node(unreal.MaterialExpressionTextureCoordinate, 0, 0)
    uv0.set_editor_property("coordinate_index", 0)
    uv1 = node(unreal.MaterialExpressionTextureCoordinate, 0, 120)
    uv1.set_editor_property("coordinate_index", 1)
    uv = lerp(uv0, "", uv1, "", scalar("TowerTexCoord", 0, 240), "", 250, 60)
    ofs = vector("TowerOffsetScale", 0, 360)
    uv = op(unreal.MaterialExpressionMultiply, uv, "", append(ofs, "B", ofs, "A", 250, 360), "", 450, 120)
    uv = op(unreal.MaterialExpressionAdd, uv, "", append(ofs, "R", ofs, "G", 250, 480), "", 650, 160)
    sample = node(unreal.MaterialExpressionTextureSampleParameter2D, 850, 160)
    sample.set_editor_property("parameter_name", "TowerMask")
    sample.set_editor_property("texture", default_mask)
    sample.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    sample.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    link(uv, "", sample, "UVs")

    day_alpha = scalar("TowerDaylight", 850, 500)
    # the gate: saturate((WindowsOn - rank) x sharpness)
    gate = saturate(times_const(op(unreal.MaterialExpressionSubtract, scalar("WindowsOn", 850, 620), "", sample, "G", 1100, 620), "", RANK["sharpness"], 1300, 620), "", 1500, 620)
    # the roof: saturate((world normal z - 0.5) x 20)
    normal = node(unreal.MaterialExpressionVertexNormalWS, 850, 800)
    nz = node(unreal.MaterialExpressionComponentMask, 1050, 800)
    for ch, on in (("r", False), ("g", False), ("b", True), ("a", False)):
        nz.set_editor_property(ch, on)
    link(normal, "", nz, "")
    sub = node(unreal.MaterialExpressionSubtract, 1250, 800)
    link(nz, "", sub, "A")
    sub.set_editor_property("const_b", 0.5)
    roof = saturate(times_const(sub, "", 20.0, 1450, 800), "", 1650, 800)
    # the day facade colour
    day_colour = lerp(vector("DayWall", 850, 950), "RGB", vector("DayGlass", 850, 1100), "RGB", sample, "R", 1250, 1000)
    day_colour = lerp(day_colour, "", vector("TowerRoof", 850, 1250), "RGB", roof, "", 1500, 1050)

    P_BC, P_EM = P.MP_BASE_COLOR, P.MP_EMISSIVE_COLOR
    new = {}
    src, out = originals[P_BC]
    new[P_BC] = lerp(src, out, day_colour, "", day_alpha, "", 1900, 1000)
    src, out = originals[P_EM]
    lit = op(unreal.MaterialExpressionMultiply, src, out, gate, "", 1900, 620)
    sky_amount = op(unreal.MaterialExpressionMultiply, op(unreal.MaterialExpressionMultiply, scalar("GlassSky", 1500, 1400), "", day_alpha, "", 1700, 1400), "", sample, "R", 1900, 1400)
    sky = op(unreal.MaterialExpressionMultiply, vector("SkyTint", 1500, 1550), "RGB", sky_amount, "", 2100, 1450)
    new[P_EM] = op(unreal.MaterialExpressionAdd, lit, "", sky, "", 2300, 800)
    if P.MP_METALLIC in originals:
        src, out = originals[P.MP_METALLIC]
        metal_day = lerp(scalar("DayWallMetallic", 1500, 1700), "", scalar("DayMetallic", 1500, 1800), "", sample, "R", 1700, 1750)
        new[P.MP_METALLIC] = lerp(src, out, metal_day, "", day_alpha, "", 1900, 1750)
    if P.MP_ROUGHNESS in originals:
        src, out = originals[P.MP_ROUGHNESS]
        new[P.MP_ROUGHNESS] = lerp(src, out, scalar("DayRoughness", 1700, 1950), "", day_alpha, "", 1900, 1950)
    for prop, n in new.items():
        if not mel.connect_material_property(n, "", prop):
            raise RuntimeError(f"could not connect the extended {prop}")
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log(f"master {mat.get_path_name()} extended on {sorted(str(p) for p in new)}")


def chain_copy(source, default_mask, parent=None):
    path = f"{COPY_FOLDER}/{COPY_PREFIX}{source.get_name()}_v{GRAPH_VERSION}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.load_asset(path)
    copy = unreal.EditorAssetLibrary.duplicate_asset(_package(source), path)
    if copy is None:
        raise RuntimeError(f"could not copy {source.get_path_name()} to {path}")
    if isinstance(copy, unreal.MaterialInstanceConstant):
        mel.set_material_instance_parent(copy, parent)
        mel.update_material_instance(copy)
        unreal.EditorAssetLibrary.save_loaded_asset(copy)
    else:
        extend_master(copy, default_mask)
    log(f"{source.get_path_name()} copied to {path}")
    return copy


def chain_parent(instance, default_mask):
    chain, m = [], instance.get_editor_property("parent")
    while isinstance(m, unreal.MaterialInstance):
        chain.append(m)
        m = m.get_editor_property("parent")
    if not isinstance(m, unreal.Material) or not m.get_path_name().startswith(_city.GLTF_ROOT):
        raise RuntimeError(f"{instance.get_path_name()}: master {m.get_path_name() if m else None} is not the glTF one")
    parent = chain_copy(m, default_mask)
    for link in reversed(chain):
        parent = chain_copy(link, default_mask, parent)
    return parent


def facade_uv(mat):
    """The facade's own texture coordinates, as the glTF instance samples its window textures."""
    v = values(mat)
    tc = v.get("scalar:BaseColorTexture_TexCoord")
    if tc is None or tc != v.get("scalar:EmissiveTexture_TexCoord") or tc not in (0.0, 1.0):
        raise RuntimeError(f"{mat.get_name()}: texcoord {tc} / {v.get('scalar:EmissiveTexture_TexCoord')} is not one index 0 or 1")
    for slot in ("BaseColorTexture", "EmissiveTexture"):
        if v.get(f"scalar:{slot}_Rotation", 0.0) != 0.0:
            raise RuntimeError(f"{mat.get_name()}: {slot} is rotated; the mask would not line up")
    ofs = v.get("vector:BaseColorTexture_OffsetScale", (0.0, 0.0, 1.0, 1.0))
    if ofs != v.get("vector:EmissiveTexture_OffsetScale", ofs):
        raise RuntimeError(f"{mat.get_name()}: colour and emission textures are placed differently")
    return tc, ofs


def set_day(mi, name, tex, tc, ofs):
    f = FACTS["facades"][name]
    mel.set_material_instance_texture_parameter_value(mi, "TowerMask", tex)
    mel.set_material_instance_scalar_parameter_value(mi, "TowerTexCoord", tc)
    mel.set_material_instance_vector_parameter_value(mi, "TowerOffsetScale", unreal.LinearColor(*ofs))
    for key in ("DayWall", "DayGlass", "TowerRoof"):
        mel.set_material_instance_vector_parameter_value(mi, key, unreal.LinearColor(*f[key], 1.0))
    mel.set_material_instance_scalar_parameter_value(mi, "DayMetallic", f["DayMetallic"])
    mel.set_material_instance_scalar_parameter_value(mi, "DayWallMetallic", WALL_METAL)
    mel.set_material_instance_scalar_parameter_value(mi, "DayRoughness", f["DayRoughness"])
    mel.set_material_instance_scalar_parameter_value(mi, "GlassSky", SKY)
    mel.set_material_instance_vector_parameter_value(mi, "SkyTint", unreal.LinearColor(*SKY_TINT, 1.0))
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)


def towers(actors):
    textures = {}
    made = {}
    components = []
    default_mask = None
    for label in COMPONENT_LABELS:
        actor = actors.get(label)
        if not isinstance(actor, unreal.StaticMeshActor):
            raise RuntimeError(f"no {label} actor in {LEVEL}")
        comp = actor.static_mesh_component
        slots = []
        for i in range(comp.get_num_materials()):
            mat = comp.get_material(i)
            if not isinstance(mat, unreal.MaterialInstanceConstant):
                continue
            name = facade_name(mat.get_name())
            if name is None:
                continue
            if name not in textures:
                textures[name] = mask_texture(name)
                default_mask = default_mask or textures[name]
            mi = made.get(name)
            if mi is None:
                if mat.get_name().startswith(INSTANCE_PREFIX):
                    mi = mat  # a rerun: already ours, checked when first made
                    tc, ofs = values(mi)["scalar:TowerTexCoord"], values(mi)["vector:TowerOffsetScale"]
                    before = None
                else:
                    tc, ofs = facade_uv(mat)
                    before = values(mat)
                    path = f"{_package(mat).rsplit('/', 1)[0]}/{INSTANCE_PREFIX}{name}"
                    if unreal.EditorAssetLibrary.does_asset_exist(path) and not unreal.EditorAssetLibrary.delete_asset(path):
                        raise RuntimeError(f"{path} exists and cannot be replaced")
                    mi = unreal.EditorAssetLibrary.duplicate_asset(_package(mat), path)
                    if mi is None:
                        raise RuntimeError(f"could not copy {mat.get_path_name()} to {path}")
                    mel.set_material_instance_parent(mi, chain_parent(mat, default_mask))
                set_day(mi, name, textures[name], tc, ofs)
                if before is not None:
                    changed = _window.differences(before, values(mi))
                    if changed:
                        raise RuntimeError(f"{name}: the copied chain does not repeat today's instance: {changed[:6]}")
                    log(f"{name}: {mat.get_name()} -> {mi.get_name()}, all {len(before)} old values unchanged, uv {tc:g} {ofs}")
                made[name] = mi
            comp.set_material(i, mi)
            slots.append(f"{i}:{name}")
        components.append({"label": label, "component": comp.get_path_name(), "slots": slots,
                           "parameters": ["TowerDaylight", "WindowsOn"]})
        log(f"{label}: day facades on {len(slots)} slots {slots}")
    return components


def skyline_surfaces(actors):
    """hq_day.SURFACES on the skyline's M_HQ_CityDay slots (the bridge's pale concrete): their
    DayBaseColor, reached by Daylight on the skyline component. Returns that component or None."""
    if not SURFACES:
        return None
    actor = actors.get("skyline")
    comp = actor.static_mesh_component
    done = []
    for i in range(comp.get_num_materials()):
        mat = comp.get_material(i)
        name = mat.get_name() if mat else ""
        if not name.startswith(_city.DAY_MI_PREFIX):
            continue
        key = name[len(_city.DAY_MI_PREFIX):].lower().rstrip("0123456789").rstrip("_")
        colour = FACTS["surfaces_day"].get(key)
        if colour is None:
            continue
        mel.set_material_instance_vector_parameter_value(mat, "DayBaseColor", unreal.LinearColor(*colour, 1.0))
        mel.update_material_instance(mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        done.append(f"{name}[{i}]")
    log(f"skyline plain slots with a day colour from hq_day.SURFACES: {done or 'none'}")
    return comp.get_path_name() if done else None


def write_report(section, payload):
    report = {}
    if os.path.exists(REPORT):
        report = json.load(open(REPORT, "r", encoding="utf-8"))
    report.update({"level": LEVEL, "written_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")})
    report[section] = payload
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    comps = towers(actors)
    skyline_daylight = skyline_surfaces(actors)
    write_report("towers", comps)
    write_report("skyline_daylight", skyline_daylight)
    les.save_current_level()
    unreal.EditorAssetLibrary.save_directory("/Game/HQ")
    log(f"saved; report {REPORT}")


main()
