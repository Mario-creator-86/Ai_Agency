"""day_state.py: the env_report merge refuses what is not this level, keeps a backup and rolls back;
the preview driver sends only the new parameters, the dusk values at the reference, and only to
127.0.0.1.

    py -3.14 -m pytest test_day_state.py -q
"""

import copy
import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("day_state", os.path.join(HERE, "day_state.py"))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

W = "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel"
ENV = {
    "labels": {
        "skyline_haze": {
            "SkylineHaze_near_left": {"component": f"{W}.StaticMeshActor_163.StaticMeshComponent0"},
            "SkylineHaze_far_right": {"component": f"{W}.StaticMeshActor_166.StaticMeshComponent0"},
        }
    },
    "emissive_scaling": {
        "skyline": {"uniform": True, "component": f"{W}.StaticMeshActor_262.StaticMeshComponent0"},
        "near_blocks": {"uniform": True, "component": f"{W}.StaticMeshActor_247.StaticMeshComponent0"},
    },
}
TOWERS = {
    "written_at": "2026-09-25T10:00:00+03:00",
    "towers": [
        {"label": "skyline", "component": f"{W}.StaticMeshActor_262.StaticMeshComponent0", "slots": ["0:city_dense"]},
        {"label": "near_blocks", "component": f"{W}.StaticMeshActor_247.StaticMeshComponent0", "slots": ["5:classic"]},
    ],
    "trees": [{"label": "tree_0", "component": f"{W}.StaticMeshActor_12.StaticMeshComponent0"}],
    "skyline_daylight": f"{W}.StaticMeshActor_262.StaticMeshComponent0",
}


def test_merge_adds_day_state_and_leaves_everything_else():
    out = ds.merged(ENV, TOWERS)
    assert {k: v for k, v in out.items() if k != "day_state"} == ENV
    assert [t["label"] for t in out["day_state"]["towers"]] == ["skyline", "near_blocks"]
    assert out["day_state"]["trees"][0]["parameters"] == ["LeafDaylight"]


@pytest.mark.parametrize("breaks", ["other_component", "other_world_tree", "no_slots", "missing_label"])
def test_merge_refuses_what_is_not_this_level(breaks):
    t = copy.deepcopy(TOWERS)
    if breaks == "other_component":
        t["towers"][0]["component"] = f"{W}.StaticMeshActor_999.StaticMeshComponent0"
    elif breaks == "other_world_tree":
        t["trees"][0]["component"] = "/Game/Other.Other:PersistentLevel.A.B"
    elif breaks == "no_slots":
        t["towers"][1]["slots"] = []
    else:
        t["towers"] = t["towers"][:1]
    with pytest.raises(ValueError):
        ds.merged(ENV, t)


def test_merge_on_disk_keeps_a_backup_and_remove_rolls_back(tmp_path):
    env_path, towers_path = tmp_path / "env_report.json", tmp_path / "towers_report.json"
    env_path.write_text(json.dumps(ENV), encoding="utf-8")
    towers_path.write_text(json.dumps(TOWERS), encoding="utf-8")
    ds.merge(str(env_path), str(towers_path))
    ds.merge(str(env_path), str(towers_path))  # twice: the backup stays the original
    backup = json.loads((tmp_path / "env_report.before_day_state.json").read_text(encoding="utf-8"))
    assert backup == ENV
    assert "day_state" in json.loads(env_path.read_text(encoding="utf-8"))
    ds.remove(str(env_path))
    assert json.loads(env_path.read_text(encoding="utf-8")) == ENV


def test_at_the_reference_the_driver_sends_today_s_dusk():
    env = ds.merged(ENV, TOWERS)
    bodies = ds.drive_bodies(env, -2.5, haze=True)
    values = {(b["objectPath"].rsplit(".", 2)[-2], b["parameters"]["ParameterName"]): b["parameters"]["ParameterValue"] for b in bodies}
    assert values[("StaticMeshActor_262", "TowerDaylight")] == 0.0
    assert values[("StaticMeshActor_262", "WindowsOn")] == 1.0
    assert values[("StaticMeshActor_12", "LeafDaylight")] == 0.0
    assert values[("StaticMeshActor_163", "Opacity")] == pytest.approx(0.55)
    assert values[("StaticMeshActor_166", "Opacity")] == pytest.approx(0.55 * 0.7)
    assert values[("StaticMeshActor_163", "HazeColor")] == pytest.approx({"X": 0.11, "Y": 0.10, "Z": 0.19})


def test_at_noon_no_window_is_lit_and_the_day_is_full():
    env = ds.merged(ENV, TOWERS)
    v = ds.day_values(45.0)
    assert v["TowerDaylight"] == 1.0 and v["WindowsOn"] == 0.0 and v["LeafDaylight"] == 1.0
    bodies = ds.drive_bodies(env, 45.0)
    assert all(b["functionName"] in (ds.SCALAR, ds.VECTOR) for b in bodies)
    assert not any(b["parameters"]["ParameterName"] == "Opacity" for b in bodies)  # haze only on --haze


def test_below_the_reference_the_haze_is_left_to_the_backend():
    env = ds.merged(ENV, TOWERS)
    assert not any(b["parameters"]["ParameterName"] == "HazeColor" for b in ds.drive_bodies(env, -10.0, haze=True))


def test_send_only_to_this_machine():
    seen = []
    codes = ds.send([{"x": 1}], "http://127.0.0.1:30010", put=lambda url, b: seen.append(url) or 200)
    assert codes == [200] and seen == ["http://127.0.0.1:30010/remote/object/call"]
    with pytest.raises(ValueError):
        ds.send([{"x": 1}], "http://example.com:30010", put=lambda url, b: 200)


def test_drive_needs_the_merge_first():
    with pytest.raises(ValueError):
        ds.drive_bodies(ENV, 10.0)
