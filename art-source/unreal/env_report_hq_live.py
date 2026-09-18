"""
The last step of every rebuild of the live headquarters (/Game/HQ/HQ_Dusk): the environment report.

  UnrealEditor-Cmd.exe AMNReference.uproject -run=pythonscript -script=env_report_hq_live.py

Object names change on every rebuild (the sky backdrop was StaticMeshActor_223 on 2026-09-18 and
will be another number after the next one), and the backend drives the sun, the sky, the lamps,
the haze, the road and the clock by object path over Remote Control. So after every pass has saved
the level, this step reads the saved level once and writes art-source/unreal/env_report.json:

  - each label the backend drives, with its actor's and its component's object path;
  - the Unreal unit vectors of the scene's +x, +y and +z (as build_hq_scene.py measured them from
    its marker cubes, axis_map.json), and north, east and up from the facade's heading;
  - per emissive component, whether one EmissiveFactor scales every slot alike (every slot a glTF
    instance with its factor at 1, 1, 1): only those may take one factor for the whole mesh;
  - the road's asphalt slot, the window views' DayBlend slots, and the sky's and the clock's
    parameters.

If any label is missing the report is written as env_report.failed.json, never over the good one,
and the step raises: the rebuild stops rather than leave the bridge driving the wrong objects.

The facade's heading is the Owner's decision D1, taken as proposed: the viewer looks north and the
facade faces south (180), so the evening sun is on the left as in his picture, the morning sun on
the right and the noon sun behind the viewer. The backend holds it in one setting,
office_facade_heading_deg; AMN_FACADE_HEADING_DEG here must equal it, and the report records the
heading it was written with so the bridge can refuse a report that disagrees with its setting.

Importing this file outside Unreal does nothing (tests/test_env_report.py imports it).
"""

import json
import math
import os
import re
import time

try:
    import unreal
except ImportError:  # the tests run in a plain Python
    unreal = None

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = "/Game/HQ/HQ_Dusk"
REPORT = os.path.join(HERE, "env_report.json")
FAILED = os.path.join(HERE, "env_report.failed.json")
AXIS_MAP = os.path.join(HERE, "axis_map.json")
SKY_ATLAS = os.path.join(HERE, "sky_atlas.json")
META = os.path.join(HERE, "hq_scene.json")
# Owner decision D1 (see above); the backend's office_facade_heading_deg must hold the same number
FACADE_HEADING_DEG = float(os.environ.get("AMN_FACADE_HEADING_DEG", "180"))

# key -> (label, kind): one actor each, all required
SINGLES = (
    ("sun", "Sun", "light"),
    ("sky_light", "SkyLight", "light"),
    ("fog", "HeightFog", "any"),
    ("post_process", "DuskLook", "any"),
    ("camera", "PlateCam", "any"),
    ("sky_backdrop", "SkyBackdrop", "mesh"),
    ("clock_display", "ClockDisplay", "mesh"),
    ("shelter_light", "shelter_light", "light"),
    ("street_fill", "StreetFill", "light"),
    ("walk_wash", "WalkWash", "light"),
    ("facade_light", "FacadeLight", "light"),
    ("skyline", "skyline", "mesh"),
    ("near_blocks", "near_blocks", "mesh"),
    ("shell", "shell", "mesh"),
    ("props", "props", "mesh"),
    ("street_ground", "street_ground", "mesh"),
)
# reported when present: the lighting-only atmosphere exists only with AMN_SKY_ATMOSPHERE=1, and the
# baked digits stay in the level, hidden, once clock_hq_live.py has put the live display over them
OPTIONAL = (
    ("sky_atmosphere", "SkyAtmosphere", "any"),
    ("clock_digits_baked", "clock_digits_mesh", "mesh"),
)
# key -> exact labels, every one required
NAMED_GROUPS = (
    ("lamps", ("lamp_far_left", "lamp_left", "lamp_right"), "light"),
    ("skyline_haze", ("SkylineHaze_near_left", "SkylineHaze_near_right",
                      "SkylineHaze_far_left", "SkylineHaze_far_right"), "mesh"),
)
# key -> label pattern; at least expected_counts[key] of them (1 when the scene does not say)
PATTERN_GROUPS = (
    ("tree_uplights", r"^tree_uplight(\.\d+)?$", "light"),
    ("car_headlights", r"^car_.+_headlight_[lr]$", "light"),
    ("car_taillights", r"^car_.+_taillight_[lr]$", "light"),
)
EMISSIVE_COMPONENTS = ("skyline", "near_blocks", "shell", "props")
GLTF_ROOT = "/InterchangeAssets/gltf/"
WINDOW_VIEW_PREFIX = "MI_HQ_WindowView"
SKY_PARAMETERS = ["PlateA", "PlateB", "PlateBlend", "Mirror", "Gain"]
CLOCK_UNSYNCED = -1.0e10  # clock_hq_live.UNSYNCED_OFFSET


# ---------------------------------------------------------------- pure: the report from records


def _kind_ok(record, kind):
    if kind == "light":
        return record["class"].endswith("Light")
    if kind == "mesh":
        return record["class"] == "StaticMeshActor"
    return True


def _entry(record):
    comp = record["components"][0] if record["components"] else {}
    entry = {"label": record["label"], "actor": record["actor"], "class": record["class"],
             "component": comp.get("path"), "component_class": comp.get("class")}
    # a light's intensity as the passes left it in the saved level: the bridge scales each light
    # from its own balance, never from a number of its own
    if record.get("intensity") is not None:
        entry["intensity"] = float(record["intensity"])
    return entry


def emissive_uniform(slots):
    """One EmissiveFactor may scale this component only if every slot is a glTF instance (whose
    parent multiplies emission by EmissiveFactor, glTF's own definition) with its factor at 1, 1, 1:
    then factor x keeps each slot's own strength (0.7 to 17.5 in look_baseline.json) in proportion.
    A slot with its own colour in the factor (glow_details' LEDs) or another parent would be
    flattened or missed."""
    reasons = []
    if not slots:
        reasons.append("no material slots")
    for s in slots:
        name = s["material"].rsplit("/", 1)[-1].split(".")[0]
        if not str(s.get("root") or "").startswith(GLTF_ROOT):
            reasons.append(f"slot {s['index']} {name}: parent {s.get('root')} is not a glTF master")
            continue
        factor = s.get("emissive_factor")
        if factor is None:
            reasons.append(f"slot {s['index']} {name}: no EmissiveFactor")
        elif any(abs(c - 1.0) > 1e-4 for c in factor[:3]):
            reasons.append(f"slot {s['index']} {name}: EmissiveFactor {factor[:3]}, not 1,1,1")
    return {"uniform": not reasons, "reasons": reasons}


def scene_north_east(heading_deg):
    """North and east as horizontal scene vectors (x right, y into the frame) for a facade whose
    outward normal - the scene's -y, towards the viewer - points at this compass heading.
    At 180 (Owner decision D1) north is +y, into the frame, and east is +x, the frame's right."""
    h = math.radians(heading_deg)
    return (math.sin(h), -math.cos(h)), (-math.cos(h), -math.sin(h))


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def _round(v):
    return [round(c, 6) + 0.0 for c in v]


def compass(axes, heading_deg):
    ex, ey, ez = _unit(axes["ex"]), _unit(axes["ey"]), _unit(axes["ez"])
    (nx, ny), (ex_, ey_) = scene_north_east(heading_deg)

    def to_unreal(x, y, z):
        return _round(_unit([ex[k] * x + ey[k] * y + ez[k] * z for k in range(3)]))

    return {
        "facade_heading_deg": float(heading_deg),
        "north": to_unreal(nx, ny, 0.0),
        "east": to_unreal(ex_, ey_, 0.0),
        "up": to_unreal(0.0, 0.0, 1.0),
        "facade_normal": to_unreal(0.0, -1.0, 0.0),
        "note": "Unreal unit vectors; a sun at azimuth A (clockwise from north) and elevation E "
                "stands along cos(E)*(cos(A)*north + sin(A)*east) + sin(E)*up; its light travels the other way",
    }


def assemble(records, axes, heading_deg, expected_counts=None, sky_atlas=None, reference=None, written_at=None):
    """(report, missing): missing names every required label not found, as "key: label"."""
    expected_counts = expected_counts or {}
    by_label = {}
    for r in records:
        by_label.setdefault(r["label"], []).append(r)

    def find(label, kind):
        return next((r for r in by_label.get(label, []) if _kind_ok(r, kind)), None)

    labels, missing = {}, []
    for key, label, kind in SINGLES:
        r = find(label, kind)
        if r is None:
            missing.append(f"{key}: {label}")
        else:
            labels[key] = _entry(r)
    for key, label, kind in OPTIONAL:
        r = find(label, kind)
        labels[key] = _entry(r) if r else None
    for key, names, kind in NAMED_GROUPS:
        group = {}
        for name in names:
            r = find(name, kind)
            if r is None:
                missing.append(f"{key}: {name}")
            else:
                group[name] = _entry(r)
        labels[key] = group
    for key, pattern, kind in PATTERN_GROUPS:
        found = sorted((r for r in records if re.match(pattern, r["label"]) and _kind_ok(r, kind)),
                       key=lambda r: r["label"])
        want = int(expected_counts.get(key, 1))
        if len(found) < want:
            missing.append(f"{key}: {len(found)} of {want} ({pattern})")
        labels[key] = [_entry(r) for r in found]

    def slots_of(label):
        r = find(label, "mesh")
        return (r or {}).get("slots", []), r

    scaling = {}
    for key in EMISSIVE_COMPONENTS:
        slots, r = slots_of(key)
        scaling[key] = {**emissive_uniform(slots), "component": _entry(r)["component"] if r else None}

    road_slots, road = slots_of("street_ground")
    asphalt = next((s for s in road_slots if "asphalt" in s["material"].lower()), None)
    if road is not None and asphalt is None:
        missing.append("road: no asphalt slot on street_ground")
    props_slots, props = slots_of("props")
    windows = [s["index"] for s in props_slots
               if s["material"].rsplit("/", 1)[-1].startswith(WINDOW_VIEW_PREFIX)]

    ex, ey, ez = axes["ex"], axes["ey"], axes["ez"]
    report = {
        "version": 1,
        "level": LEVEL,
        "written_at": written_at,
        "labels": labels,
        "axes": {
            "scene_x": _round(_unit(ex)), "scene_y": _round(_unit(ey)), "scene_z": _round(_unit(ez)),
            "units_per_m": round(math.sqrt(sum(c * c for c in ex)), 6),
            "origin_unreal": axes.get("origin_unreal"), "origin_scene_m": axes.get("origin_scene_m"),
        },
        "compass": compass(axes, heading_deg),
        "emissive_scaling": scaling,
        "road": {
            "component": _entry(road)["component"] if road else None,
            "slot": asphalt["index"] if asphalt else None,
            "material": asphalt["material"] if asphalt else None,
            "parameters": ["Roughness Min", "Roughness Max"],
        },
        "window_view": {
            "component": _entry(props)["component"] if props else None,
            "slots": windows,
            "parameter": "DayBlend",
        },
        "sky": {"parameters": list(SKY_PARAMETERS), "atlas": sky_atlas},
        "clock": {
            "parameter": "ClockOffsetS",
            "unsynced_default": CLOCK_UNSYNCED,
            "time": "the material's Time node: the world's game seconds (the live game is never paused)",
            "offset": "local seconds of the day in Europe/Bucharest minus that game time, "
                      "resent on every full refresh and at a DST change",
        },
        "reference": reference or {},
    }
    return report, missing


# ---------------------------------------------------------------- inside Unreal


def log(msg):
    unreal.log(f"AMN_ENV {msg}")


def _root_of(material):
    m, seen = material, 0
    while isinstance(m, unreal.MaterialInstance) and seen < 16:
        parent = m.get_editor_property("parent")
        if parent is None:
            break
        m, seen = parent, seen + 1
    return m.get_path_name() if m is not None else None


def _slots(comp):
    mel = unreal.MaterialEditingLibrary
    out = []
    for i in range(comp.get_num_materials()):
        mat = comp.get_material(i)
        if mat is None:
            out.append({"index": i, "material": "None", "root": None, "emissive_factor": None})
            continue
        factor = None
        if isinstance(mat, unreal.MaterialInstance):
            try:
                if "EmissiveFactor" in [str(n) for n in mel.get_vector_parameter_names(mat)]:
                    c = mel.get_material_instance_vector_parameter_value(mat, "EmissiveFactor")
                    factor = [c.r, c.g, c.b]
            except Exception as err:
                log(f"EmissiveFactor of {mat.get_name()} unreadable: {err}")
        out.append({"index": i, "material": mat.get_path_name(), "root": _root_of(mat), "emissive_factor": factor})
    return out


SLOT_LABELS = set(EMISSIVE_COMPONENTS) | {"street_ground"}


def collect():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    records = []
    for actor in eas.get_all_level_actors():
        comp = actor.camera_component if isinstance(actor, unreal.CameraActor) else actor.root_component
        label = actor.get_actor_label()
        record = {
            "label": label,
            "class": actor.get_class().get_name(),
            "actor": actor.get_path_name(),
            "components": [{"name": comp.get_name(), "class": comp.get_class().get_name(),
                            "path": f"{actor.get_path_name()}.{comp.get_name()}"}] if comp else [],
            "slots": _slots(actor.static_mesh_component) if isinstance(actor, unreal.StaticMeshActor) and label in SLOT_LABELS else [],
        }
        if isinstance(comp, unreal.LightComponentBase):
            try:
                record["intensity"] = float(comp.get_editor_property("intensity"))
            except Exception as err:
                log(f"{label}: intensity unreadable: {err}")
        records.append(record)
    return records


def _reference(records):
    """Today's values in the saved level, so the backend's golden test can hold its reference
    instant to exactly what the build left (read, never written)."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()}
    out = {}
    try:
        sun = actors["Sun"].light_component
        rot = sun.get_world_rotation()
        c = sun.get_editor_property("light_color")
        out["sun"] = {"intensity": sun.get_editor_property("intensity"), "light_color": [c.r, c.g, c.b],
                      "rotation": {"pitch": rot.pitch, "yaw": rot.yaw, "roll": rot.roll},
                      "mobility": str(sun.get_editor_property("mobility"))}
    except Exception as err:
        out["sun"] = f"unreadable: {err}"
    try:
        sky = actors["SkyLight"].light_component
        out["sky_light"] = {"intensity": sky.get_editor_property("intensity")}
    except Exception as err:
        out["sky_light"] = f"unreadable: {err}"
    try:
        fog = actors["HeightFog"].component
        lum = fog.get_editor_property("fog_inscattering_luminance")
        out["fog"] = {"density": fog.get_editor_property("fog_density"), "inscattering_luminance": [lum.r, lum.g, lum.b]}
    except Exception as err:
        out["fog"] = f"unreadable: {err}"
    mel = unreal.MaterialEditingLibrary
    haze = {}
    for name in ("SkylineHaze_near_left", "SkylineHaze_near_right", "SkylineHaze_far_left", "SkylineHaze_far_right"):
        try:
            mat = actors[name].static_mesh_component.get_material(0)
            c = mel.get_material_instance_vector_parameter_value(mat, "HazeColor")
            haze[name] = {"HazeColor": [c.r, c.g, c.b], "Opacity": mel.get_material_instance_scalar_parameter_value(mat, "Opacity")}
        except Exception as err:
            haze[name] = f"unreadable: {err}"
    out["haze"] = haze
    try:
        road = unreal.load_asset("/Game/HQ/Materials/MI_HQ_AsphaltWet")
        out["road"] = {p: mel.get_material_instance_scalar_parameter_value(road, p) for p in ("Roughness Min", "Roughness Max")}
    except Exception as err:
        out["road"] = f"unreadable: {err}"
    return out


def main():
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError(f"could not load {LEVEL}")
    if not os.path.exists(AXIS_MAP):
        raise RuntimeError(f"{AXIS_MAP} missing: build_hq_scene.py writes it when it measures the axes")
    axes = json.load(open(AXIS_MAP, "r", encoding="utf-8"))
    sky_atlas = json.load(open(SKY_ATLAS, "r", encoding="utf-8")) if os.path.exists(SKY_ATLAS) else None
    expected = {}
    if os.path.exists(META):
        lights = json.load(open(META, "r", encoding="utf-8")).get("lights", [])
        expected["tree_uplights"] = sum(1 for item in lights if item["name"].startswith("tree_uplight"))
    records = collect()
    report, missing = assemble(records, axes, FACADE_HEADING_DEG, expected_counts=expected,
                               sky_atlas=sky_atlas, reference=_reference(records),
                               written_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    if missing:
        with open(FAILED, "w", encoding="utf-8") as fh:
            json.dump({**report, "missing": missing}, fh, indent=1)
        raise RuntimeError(f"env report: {len(missing)} label(s) missing: {'; '.join(missing)} (see {FAILED})")
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    if os.path.exists(FAILED):
        os.remove(FAILED)
    uniform = [k for k, v in report["emissive_scaling"].items() if v["uniform"]]
    log(f"written {REPORT}: {len(records)} actors read, every label found; north {report['compass']['north']} "
        f"at heading {FACADE_HEADING_DEG:g}; one-factor emission on {uniform or 'none'}; "
        f"window views on props slots {report['window_view']['slots']}; road slot {report['road']['slot']}")
    for key, value in report["emissive_scaling"].items():
        if not value["uniform"]:
            log(f"{key}: not one factor - {'; '.join(value['reasons'][:4])}")


if unreal is not None:
    main()
