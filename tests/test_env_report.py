"""The environment report the last rebuild step writes (art-source/unreal/env_report_hq_live.py).

Object names change on every rebuild (StaticMeshActor_223 today, another number tomorrow), so the
backend drives the sky, the sun, the lamps and the clock through this report: label -> object
path, the scene's axes in Unreal, north from the facade's heading (Owner decision D1), and which
components take one emissive factor for every slot. The report is assembled by pure functions,
tested here on records shaped like the ones the editor collects; a missing label fails the
rebuild instead of leaving the bridge to guess.
"""

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "env_report_hq_live.py"
LEVEL = "/Game/HQ/HQ_Dusk.HQ_Dusk:PersistentLevel"
GLTF = "/InterchangeAssets/gltf/MaterialInstances/MI_Default_Opaque_DS.MI_Default_Opaque_DS"


@pytest.fixture(scope="module")
def env():
    spec = importlib.util.spec_from_file_location("env_report_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no unreal here: importing must do nothing
    return module


def actor(label, cls, n, component="LightComponent0", comp_cls=None, slots=None):
    path = f"{LEVEL}.{cls}_{n}"
    return {
        "label": label,
        "class": cls,
        "actor": path,
        "components": [
            {
                "name": component,
                "class": comp_cls or f"{cls}Component",
                "path": f"{path}.{component}",
            }
        ],
        "slots": slots or [],
    }


def slot(i, name, factor=(1.0, 1.0, 1.0), root=GLTF):
    return {
        "index": i,
        "material": f"/Game/HQ/Scene_1/hq_scene/Materials/{name}.{name}",
        "root": root,
        "emissive_factor": list(factor) if factor is not None else None,
    }


def mesh(label, n, slots=None):
    return actor(label, "StaticMeshActor", n, "StaticMeshComponent0", "StaticMeshComponent", slots)


def full_level():
    records = [
        actor("Sun", "DirectionalLight", 1, comp_cls="DirectionalLightComponent"),
        actor("SkyLight", "SkyLight", 0, "SkyLightComponent0"),
        actor(
            "HeightFog",
            "ExponentialHeightFog",
            0,
            "HeightFogComponent0",
            "ExponentialHeightFogComponent",
        ),
        actor("DuskLook", "PostProcessVolume", 0, "Root", "SceneComponent"),
        actor("PlateCam", "CameraActor", 0, "CameraComponent", "CameraComponent"),
        mesh("SkyBackdrop", 223),
        mesh("ClockDisplay", 300),
        mesh("clock_digits_mesh", 177),
        actor("lamp_far_left", "PointLight", 1, comp_cls="PointLightComponent"),
        actor("lamp_left", "PointLight", 2, comp_cls="PointLightComponent"),
        actor("lamp_right", "PointLight", 3, comp_cls="PointLightComponent"),
        mesh("lamp_left_post", 90),  # dress_hq_live's lamp post: a mesh, never a lamp
        actor("shelter_light", "RectLight", 1, comp_cls="RectLightComponent"),
        actor("tree_uplight", "SpotLight", 10, comp_cls="SpotLightComponent"),
        actor("tree_uplight.001", "SpotLight", 11, comp_cls="SpotLightComponent"),
        actor("StreetFill", "RectLight", 5, comp_cls="RectLightComponent"),
        actor("WalkWash", "RectLight", 6, comp_cls="RectLightComponent"),
        actor("FacadeLight", "RectLight", 7, comp_cls="RectLightComponent"),
        actor("car_sedan_headlight_l", "SpotLight", 20, comp_cls="SpotLightComponent"),
        actor("car_sedan_headlight_r", "SpotLight", 21, comp_cls="SpotLightComponent"),
        actor("car_sedan_taillight_l", "PointLight", 22, comp_cls="PointLightComponent"),
        mesh("car_sedan", 60),
        mesh("skyline", 150, [slot(0, "tower_a_001"), slot(1, "tower_b_001")]),
        mesh("near_blocks", 151, [slot(0, "block_001")]),
        mesh(
            "shell", 152, [slot(0, "frame_dark_001"), slot(1, "slab_001", factor=(0.0, 0.0, 0.0))]
        ),
        mesh(
            "props",
            153,
            [
                slot(0, "screen_001"),
                slot(
                    1,
                    "MI_HQ_WindowView_window_city",
                    factor=None,
                    root="/Game/HQ/Materials/M_HQ_WindowView.M_HQ_WindowView",
                ),
            ],
        ),
        mesh(
            "street_ground",
            154,
            [
                slot(0, "sidewalk_001"),
                slot(
                    1,
                    "MI_HQ_AsphaltWet",
                    factor=None,
                    root="/Game/AutomotiveBridgeScene/M_Asphalt.M_Asphalt",
                ),
            ],
        ),
        mesh("SkylineHaze_near_left", 400),
        mesh("SkylineHaze_near_right", 401),
        mesh("SkylineHaze_far_left", 402),
        mesh("SkylineHaze_far_right", 403),
    ]
    by_label = {r["label"]: r for r in records}
    by_label["props"]["slots"][1]["material"] = (
        "/Game/HQ/Materials/MI_HQ_WindowView_window_city.MI_HQ_WindowView_window_city"
    )
    by_label["street_ground"]["slots"][1]["material"] = (
        "/Game/HQ/Materials/MI_HQ_AsphaltWet.MI_HQ_AsphaltWet"
    )
    return records


AXES = {
    "ex": [100.0, 0.0, 0.0],
    "ey": [0.0, -100.0, 0.0],
    "ez": [0.0, 0.0, 100.0],
    "origin_unreal": [0.0, 0.0, 6000.0],
    "origin_scene_m": [0.0, 0.0, 60.0],
}


def build(env, records=None, heading=180.0, uplights=2):
    return env.assemble(
        records if records is not None else full_level(),
        AXES,
        heading,
        expected_counts={"tree_uplights": uplights},
    )


# ---------------------------------------------------------------- labels


def test_every_label_the_bridge_drives_is_reported(env):
    report, missing = build(env)
    assert missing == []
    labels = report["labels"]
    assert labels["sun"]["component"] == f"{LEVEL}.DirectionalLight_1.LightComponent0"
    assert (
        labels["sky_backdrop"]["component"] == f"{LEVEL}.StaticMeshActor_223.StaticMeshComponent0"
    )
    assert labels["fog"]["component"].endswith("ExponentialHeightFog_0.HeightFogComponent0")
    assert set(labels["lamps"]) == {"lamp_far_left", "lamp_left", "lamp_right"}
    assert labels["lamps"]["lamp_left"]["actor"] == f"{LEVEL}.PointLight_2"
    assert [u["label"] for u in labels["tree_uplights"]] == ["tree_uplight", "tree_uplight.001"]
    assert len(labels["car_headlights"]) == 2 and len(labels["car_taillights"]) == 1
    assert set(labels["skyline_haze"]) == {
        "SkylineHaze_near_left",
        "SkylineHaze_near_right",
        "SkylineHaze_far_left",
        "SkylineHaze_far_right",
    }
    for key in (
        "sky_light",
        "post_process",
        "camera",
        "clock_display",
        "shelter_light",
        "street_fill",
        "walk_wash",
        "facade_light",
        "skyline",
        "near_blocks",
        "shell",
        "props",
        "street_ground",
    ):
        assert labels[key]["actor"].startswith(LEVEL), key


def test_a_lamp_post_mesh_is_never_taken_for_a_lamp(env):
    records = [r for r in full_level() if r["label"] != "lamp_left"]
    _, missing = build(env, records)
    assert "lamps: lamp_left" in missing


@pytest.mark.parametrize(
    "label",
    [
        "Sun",
        "SkyBackdrop",
        "ClockDisplay",
        "WalkWash",
        "props",
        "SkylineHaze_far_right",
        "HeightFog",
    ],
)
def test_a_missing_label_is_named(env, label):
    records = [r for r in full_level() if r["label"] != label]
    _, missing = build(env, records)
    assert missing and any(label in m for m in missing)


def test_the_old_sun_label_does_not_count(env):
    records = full_level()
    records[0]["label"] = "SunDusk"
    _, missing = build(env, records)
    assert any("Sun" in m for m in missing)


def test_fewer_uplights_than_the_scene_has_is_a_missing_label(env):
    _, missing = build(env, uplights=7)
    assert any("tree_uplight" in m for m in missing)


def test_the_road_is_the_asphalt_slot(env):
    report, _ = build(env)
    road = report["road"]
    assert road["slot"] == 1
    assert road["material"].endswith("MI_HQ_AsphaltWet")
    assert road["parameters"] == ["Roughness Min", "Roughness Max"]
    records = full_level()
    road = next(r for r in records if r["label"] == "street_ground")
    road["slots"] = road["slots"][:1]
    _, missing = build(env, records)
    assert any("asphalt" in m for m in missing)


def test_the_window_views_are_found_on_props(env):
    report, _ = build(env)
    assert report["window_view"]["parameter"] == "DayBlend"
    assert report["window_view"]["slots"] == [1]
    assert report["window_view"]["component"].endswith("StaticMeshActor_153.StaticMeshComponent0")


def test_each_light_carries_its_intensity_in_the_saved_level(env):
    """The bridge scales a lamp from its own saved intensity (the look pass's balance), never from
    a number of its own: the report is where it reads it."""
    records = full_level()
    for r in records:
        if r["class"].endswith("Light"):
            r["intensity"] = 22400.0 if r["label"] == "lamp_left" else 100.0
    report, _ = build(env, records)
    assert report["labels"]["lamps"]["lamp_left"]["intensity"] == 22400.0
    assert report["labels"]["tree_uplights"][0]["intensity"] == 100.0
    assert "intensity" not in report["labels"]["skyline"]


def test_the_sky_atmosphere_is_optional(env):
    report, missing = build(env)
    assert missing == [] and report["labels"].get("sky_atmosphere") is None


# ---------------------------------------------------------------- axes and north


def test_axes_are_unit_vectors_in_unreal(env):
    report, _ = build(env)
    a = report["axes"]
    assert a["scene_x"] == [1.0, 0.0, 0.0]
    assert a["scene_y"] == [0.0, -1.0, 0.0]
    assert a["scene_z"] == [0.0, 0.0, 1.0]
    assert a["units_per_m"] == 100.0


def test_facing_south_puts_north_into_the_frame_and_east_on_the_right(env):
    """D1: the viewer looks north, the facade faces south; evening sun left, morning sun right."""
    report, _ = build(env, heading=180.0)
    c = report["compass"]
    assert c["facade_heading_deg"] == 180.0
    assert c["north"] == pytest.approx([0.0, -1.0, 0.0])  # scene +y, into the frame
    assert c["east"] == pytest.approx([1.0, 0.0, 0.0])  # scene +x, the frame's right
    assert c["up"] == pytest.approx([0.0, 0.0, 1.0])
    assert c["facade_normal"] == pytest.approx([0.0, 1.0, 0.0])  # towards the camera


@pytest.mark.parametrize("heading", [0.0, 90.0, 135.0, 180.0, 270.0])
def test_north_and_east_follow_any_heading(env, heading):
    north, east = env.scene_north_east(heading)
    # the facade's outward normal is the scene's -y: its compass bearing is the heading
    facade = (0.0, -1.0)
    bearing = math.degrees(
        math.atan2(
            facade[0] * east[0] + facade[1] * east[1], facade[0] * north[0] + facade[1] * north[1]
        )
    )
    assert bearing % 360.0 == pytest.approx(heading % 360.0, abs=1e-9)
    assert north[0] * east[0] + north[1] * east[1] == pytest.approx(0.0, abs=1e-12)
    # east is a quarter turn clockwise from north, seen from above (z up)
    assert north[0] * east[1] - north[1] * east[0] == pytest.approx(-1.0)


# ---------------------------------------------------------------- emissive scaling


def test_uniform_when_every_slot_is_gltf_at_factor_one(env):
    report, _ = build(env)
    scaling = report["emissive_scaling"]
    assert scaling["skyline"]["uniform"] is True
    assert scaling["near_blocks"]["uniform"] is True


def test_a_slot_with_its_own_factor_or_another_parent_is_not_uniform(env):
    report, _ = build(env)
    scaling = report["emissive_scaling"]
    assert scaling["shell"]["uniform"] is False
    assert any("slab_001" in r for r in scaling["shell"]["reasons"])
    assert scaling["props"]["uniform"] is False
    assert any("WindowView" in r for r in scaling["props"]["reasons"])


def test_a_component_with_no_slots_is_not_uniform(env):
    assert env.emissive_uniform([])["uniform"] is False


# ---------------------------------------------------------------- the file


def test_the_report_carries_its_version_level_and_the_contracts(env):
    report, _ = build(env)
    assert report["version"] == 1
    assert report["level"] == "/Game/HQ/HQ_Dusk"
    assert report["clock"]["parameter"] == "ClockOffsetS"
    assert report["clock"]["unsynced_default"] < -1e9
    assert report["sky"]["parameters"] == ["PlateA", "PlateB", "PlateBlend", "Mirror", "Gain"]


def test_a_rebuilds_report_carries_no_day_state(env):
    """The day state is merged after the towers pass (art-source/unreal/towers_day/day_state.py),
    never written by the rebuild: a rebuilt level has not had that pass, and its fresh report
    leaves TowerDaylight, WindowsOn and LeafDaylight alone until the pass runs and the merge adds
    them. The backend reads the key only when it is there."""
    report, missing = build(env)
    assert missing == []
    assert "day_state" not in report
