"""The day state's two small tools for the window (PREPARED 2026-09-24; pure Python, no Unreal):

  py -3.11 day_state.py merge  [--env-report P] [--towers-report P]   # add "day_state" to env_report.json
  py -3.11 day_state.py remove [--env-report P]                       # take it out again (rollback)
  py -3.11 day_state.py drive  --elevation E [--morning] [--haze] [--dry-run] [--rc URL]

merge: towers_day_hq_live.py and trees_day_hq_live.py write towers_report.json (the components that
carry TowerDaylight/WindowsOn and LeafDaylight). The backend reads only env_report.json, so the
components go there under a new key, "day_state", which today's backend ignores (load_env_report
reads only the keys it knows) and backend_day_state.patch reads. Every component must live in the
level env_report.json describes; the towers must be the very components env_report names for the
skyline and the near blocks. The old report is kept beside it (env_report.before_day_state.json) and
the new one replaces it atomically, since the Owner's running studio reads that file.

drive: the preview driver. rebuild_2c/drive_once.py sends what the committed backend plans for an
instant; this sends, right after it, what the committed backend does not know yet: TowerDaylight,
WindowsOn, LeafDaylight, Daylight on the skyline, and with --haze the Blender day haze on the four
haze planes. The values come from towers_day.py's curves for the real elevation given. Calls go to
Remote Control exactly as backend/app/office/unreal.py sends them (PUT /remote/object/call,
MeshComponent.Set*ParameterValueOnMaterials, which DefaultRemoteControl.ini already allows).
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("towers_day", os.path.join(HERE, "towers_day.py"))
td = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(td)

ENV_REPORT = os.path.join(td.REPO, "art-source", "unreal", "env_report.json")
TOWERS_REPORT = os.path.join(HERE, "towers_report.json")
BACKUP_SUFFIX = ".before_day_state.json"
RC = "http://127.0.0.1:30010"
CALL_PATH = "/remote/object/call"
SCALAR, VECTOR = "SetScalarParameterValueOnMaterials", "SetVectorParameterValueOnMaterials"
# scene_params.HAZE_LEFT / HAZE_RIGHT / HAZE_OPACITY / HAZE_FAR_SHARE (the build's dusk haze)
HAZE_DUSK = {"left": (0.11, 0.10, 0.19), "right": (0.16, 0.17, 0.26)}
HAZE_OPACITY, HAZE_FAR_SHARE = 0.55, 0.7


# ---------------------------------------------------------------- merge
def world_of(path: str) -> str:
    return path.split(":", 1)[0] if ":" in path else ""


def merged(env: dict, towers: dict) -> dict:
    """env_report with "day_state" from towers_report; raises ValueError on anything that does not
    belong to the level the report describes."""
    names = env.get("emissive_scaling") or {}
    expected = {k: (names.get(k) or {}).get("component") for k in ("skyline", "near_blocks")}
    worlds = {world_of(v) for v in expected.values() if v}
    if len(worlds) != 1:
        raise ValueError("env_report.json names no skyline/near_blocks component: not a built report")
    world = worlds.pop()
    towers_list = towers.get("towers") or []
    if {t["label"] for t in towers_list} != {"skyline", "near_blocks"}:
        raise ValueError(f"towers_report names {sorted(t['label'] for t in towers_list)}, not skyline and near_blocks")
    for t in towers_list:
        if t["component"] != expected[t["label"]]:
            raise ValueError(f"{t['label']}: towers_report {t['component']} is not env_report's {expected[t['label']]}")
        if not t.get("slots"):
            raise ValueError(f"{t['label']}: no facade slot was given a day state")
    trees = towers.get("trees") or []
    for t in trees:
        if world_of(t["component"]) != world:
            raise ValueError(f"tree {t['label']} lives in {world_of(t['component'])}, not {world}")
    skyline_daylight = towers.get("skyline_daylight")
    if skyline_daylight and skyline_daylight != expected["skyline"]:
        raise ValueError("skyline_daylight is not the skyline component")
    out = dict(env)
    out["day_state"] = {
        "towers": [{"label": t["label"], "component": t["component"], "parameters": ["TowerDaylight", "WindowsOn"]} for t in towers_list],
        "trees": [{"label": t["label"], "component": t["component"], "parameters": ["LeafDaylight"]} for t in trees],
        "skyline_daylight": skyline_daylight,
        "merged_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "towers_report_written_at": towers.get("written_at"),
    }
    return out


def write_atomic(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def merge(env_path: str, towers_path: str) -> dict:
    env = json.load(open(env_path, encoding="utf-8"))
    towers = json.load(open(towers_path, encoding="utf-8"))
    new = merged(env, towers)
    backup = env_path[: -len(".json")] + BACKUP_SUFFIX
    if "day_state" not in env:
        write_atomic(backup, env)
    write_atomic(env_path, new)
    return new


def remove(env_path: str) -> dict:
    env = json.load(open(env_path, encoding="utf-8"))
    env.pop("day_state", None)
    write_atomic(env_path, env)
    return env


# ---------------------------------------------------------------- drive
def day_values(elevation: float, morning: bool = False, few: float = td.WINDOWS_FEW, morning_share: float = 1.0) -> dict:
    day = td.day_weight(elevation)
    share = td.windows_share(elevation, few=few, morning=morning, morning_share=morning_share)
    return {"TowerDaylight": day, "WindowsOn": td.windows_on(share), "share": share, "LeafDaylight": day, "Daylight": day}


def body(path: str, function: str, name: str, value) -> dict:
    if function == SCALAR:
        params = {"ParameterName": name, "ParameterValue": float(value)}
    else:
        x, y, z = value
        params = {"ParameterName": name, "ParameterValue": {"X": x, "Y": y, "Z": z}}
    return {"objectPath": path, "functionName": function, "parameters": params, "generateTransaction": False}


def drive_bodies(env: dict, elevation: float, morning: bool = False, haze: bool = False, few: float = td.WINDOWS_FEW, morning_share: float = 1.0) -> list[dict]:
    state = env.get("day_state")
    if not state:
        raise ValueError("env_report.json has no day_state: run 'merge' first")
    v = day_values(elevation, morning, few, morning_share)
    out = []
    for t in state["towers"]:
        out.append(body(t["component"], SCALAR, "TowerDaylight", v["TowerDaylight"]))
        out.append(body(t["component"], SCALAR, "WindowsOn", v["WindowsOn"]))
    for t in state["trees"]:
        out.append(body(t["component"], SCALAR, "LeafDaylight", v["LeafDaylight"]))
    if state.get("skyline_daylight"):
        out.append(body(state["skyline_daylight"], SCALAR, "Daylight", v["Daylight"]))
    if haze and elevation >= td.REFERENCE_DUSK_ELEVATION:
        # above the reference scene_params' dim is 1; below it drive_once's own haze stands
        planes = (env.get("labels") or {}).get("skyline_haze") or {}
        h = td.haze_day()
        for label, entry in planes.items():
            dusk = HAZE_DUSK["right" if label.endswith("right") else "left"]
            opacity = HAZE_OPACITY * (HAZE_FAR_SHARE if "_far_" in label else 1.0)
            hv = td.haze_values(label, v["TowerDaylight"], dusk, opacity, 1.0, h)
            out.append(body(entry["component"], VECTOR, "HazeColor", hv["HazeColor"]))
            out.append(body(entry["component"], SCALAR, "Opacity", hv["Opacity"]))
    return out


def http_put(url: str, payload: dict, timeout: float = 2.0) -> int:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="PUT", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 127.0.0.1 only
            return response.status
    except urllib.error.HTTPError as refused:
        return refused.code


def send(bodies: list[dict], rc: str = RC, put=http_put) -> list[int]:
    if not rc.startswith("http://127.0.0.1:"):
        raise ValueError("Remote Control is only ever called on this machine")
    return [put(rc + CALL_PATH, b) for b in bodies]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("merge", "remove", "drive"))
    p.add_argument("--env-report", default=ENV_REPORT)
    p.add_argument("--towers-report", default=TOWERS_REPORT)
    p.add_argument("--elevation", type=float)
    p.add_argument("--morning", action="store_true")
    p.add_argument("--haze", action="store_true")
    p.add_argument("--few", type=float, default=td.WINDOWS_FEW)
    p.add_argument("--morning-share", type=float, default=1.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rc", default=RC)
    a = p.parse_args(argv)
    if a.mode == "merge":
        new = merge(a.env_report, a.towers_report)
        print(json.dumps(new["day_state"], indent=1))
        return 0
    if a.mode == "remove":
        remove(a.env_report)
        print("day_state removed")
        return 0
    if a.elevation is None:
        p.error("drive needs --elevation")
    env = json.load(open(a.env_report, encoding="utf-8"))
    bodies = drive_bodies(env, a.elevation, a.morning, a.haze, a.few, a.morning_share)
    v = day_values(a.elevation, a.morning, a.few, a.morning_share)
    print(json.dumps({"elevation": a.elevation, **v, "calls": len(bodies)}, indent=1))
    if a.dry_run:
        return 0
    codes = send(bodies, a.rc)
    refused = [(b["objectPath"].rsplit(".", 1)[-1], b["parameters"]["ParameterName"], c) for b, c in zip(bodies, codes, strict=True) if not 200 <= c < 300]
    print(f"landed {len(codes) - len(refused)}/{len(codes)}; refused {refused}")
    return 0 if not refused else 1


if __name__ == "__main__":
    sys.exit(main())
