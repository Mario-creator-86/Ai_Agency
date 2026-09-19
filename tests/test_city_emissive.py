"""The city behind the headquarters by day (art-source/unreal/city_emissive.py, applied by
look_hq_live.py to the skyline's and the near blocks' material slots).

Measured in the rebuild window of 2026-09-19: env_report said emissive_scaling skyline.uniform=False
and near_blocks.uniform=False, because five slots of each sat at the glTF EmissiveFactor 0, 0, 0.
The backend writes one EmissiveFactor per component, so it could not dim either, and noon showed a
lit night city. The look pass now moves every grey factor into its slot's strength (the glTF
master multiplies texture x factor x strength), which leaves every pixel of the dusk as it was and
every factor at 1, 1, 1. These tests hold the arithmetic, the dusk, and the report's verdict on the
result; no Unreal here.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNREAL = ROOT / "art-source" / "unreal"
GLTF = "/InterchangeAssets/gltf/MaterialInstances/MI_Default_Opaque_DS.MI_Default_Opaque_DS"
SCENE = "/Game/HQ/Scene_20260919_085234/hq_scene/Materials"
# the slots env_report found at factor 0 on 2026-09-19, with the imported strengths
# look_baseline.json holds for them (0.7 each), and the lit facades beside them
SKYLINE_DARK = ("antenna_001", "spire_001", "billboard_frame_001", "bridge_001", "slogan_panel_001")
NEAR_DARK = (
    "same_city_001",
    "same_city_edge_001",
    "pole_001",
    "sign_panel_001",
    "classic_stone_001",
)
LIT = {"tower_blue": 5.25, "tower_dark": 5.25, "city_dense": 4.9, "beacon_001": 28.0}
CITY = 0.5  # look_hq_live.CITY, AMN_LOOK_CITY


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", UNREAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no unreal here: importing must do nothing
    return module


@pytest.fixture(scope="module")
def city():
    return load("city_emissive")


@pytest.fixture(scope="module")
def env():
    return load("env_report_hq_live")


def linear(hex_colour):
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    h = hex_colour.lstrip("#")
    return tuple(channel(int(h[i : i + 2], 16)) for i in (0, 2, 4))


def record(i, name, factor, root=GLTF):
    return {
        "index": i,
        "material": f"{SCENE}/{name}.{name}",
        "root": root,
        "emissive_factor": list(factor) if factor is not None else None,
    }


# ---------------------------------------------------------------- the fold


def test_a_slot_at_factor_zero_gets_factor_one_and_no_strength(city):
    plan = city.fold_emission([0.0, 0.0, 0.0], 0.7 * CITY)
    assert plan["action"] == "fold"
    assert plan["factor"] == (1.0, 1.0, 1.0)
    assert plan["strength"] == 0.0


def test_a_slot_at_factor_one_keeps_the_city_gain_it_always_had(city):
    plan = city.fold_emission([1.0, 1.0, 1.0], 5.25 * CITY)
    assert plan["action"] == "keep"
    assert plan["strength"] == 5.25 * CITY


def test_a_grey_factor_moves_into_the_strength(city):
    plan = city.fold_emission([0.4, 0.4, 0.4], 10.0)
    assert plan["action"] == "fold"
    assert plan["factor"] == (1.0, 1.0, 1.0)
    assert plan["strength"] == pytest.approx(4.0)


def test_a_coloured_factor_is_named_not_flattened(city):
    # shell's cove_led_001 carries (1.0, 0.527, 0.195): a colour cannot live in a scalar
    plan = city.fold_emission([1.0, 0.5271, 0.1946], 2.2)
    assert plan["action"] == "cannot"
    assert "colour" in plan["reason"]


def test_a_slot_without_a_factor_or_a_strength_to_carry_it_is_named(city):
    assert city.fold_emission(None, 1.0)["action"] == "cannot"
    assert city.fold_emission([0.0, 0.0, 0.0], None)["action"] == "cannot"


@pytest.mark.parametrize("factor", [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.35, 0.35, 0.35)])
def test_the_dusk_is_the_same_pixel_after_the_fold(city, factor):
    # the glTF master: emission = texture x factor x strength (MF_Emissive). At the backend's dusk
    # factor 1 the folded slot glows exactly as the unfolded one; by day it scales in proportion.
    strength = 5.25 * CITY
    plan = city.fold_emission(list(factor), strength)
    for texel in ((1.0, 0.85, 0.6), (0.2, 0.3, 0.9), (0.0, 0.0, 0.0)):
        before = city.emission(texel, factor, strength)
        after = city.emission(texel, plan["factor"], plan["strength"])
        assert after == pytest.approx(before, abs=1e-12)
        k = 0.06  # scene_params.CITY_DAY_EMISSION: the backend's factor at full day
        day = city.emission(texel, tuple(c * k for c in plan["factor"]), plan["strength"])
        assert day == pytest.approx(tuple(k * c for c in before), abs=1e-12)


def test_a_dark_slot_stays_dark_under_any_factor_the_backend_writes(city):
    plan = city.fold_emission([0.0, 0.0, 0.0], 0.7 * CITY)
    for k in (0.0, 0.06, 0.5, 1.0):
        assert city.emission((1.0, 1.0, 1.0), (k, k, k), plan["strength"]) == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------- the report's verdict afterwards


def folded_records(city, names_dark, lit):
    records, i = [], 0
    for name in names_dark:
        plan = city.fold_emission([0.0, 0.0, 0.0], 0.7 * CITY)
        records.append(record(i, name, plan["factor"]))
        i += 1
    for name, strength in lit.items():
        plan = city.fold_emission([1.0, 1.0, 1.0], strength * CITY)
        records.append(record(i, name, plan["factor"]))
        i += 1
    return records


def test_the_measured_components_are_uniform_after_the_fold(city, env):
    # before: the measured verdict, five dark slots each
    before = [record(i, n, (0.0, 0.0, 0.0)) for i, n in enumerate(SKYLINE_DARK)]
    assert env.emissive_uniform(before)["uniform"] is False
    for dark in (SKYLINE_DARK, NEAR_DARK):
        verdict = env.emissive_uniform(folded_records(city, dark, LIT))
        assert verdict["uniform"] is True, verdict["reasons"]


def test_the_near_blocks_day_slots_do_not_break_the_city_factor(city, env):
    # near_blocks_day moves the darkest plain slots to M_HQ_CityDay: no EmissiveFactor, no glow
    records = folded_records(city, NEAR_DARK[2:], LIT)
    day_root = f"{city.DAY_MASTER}.{city.DAY_MASTER.rsplit('/', 1)[-1]}"
    for i, name in enumerate(("MI_HQ_CityDay_same_city_001", "MI_HQ_CityDay_same_city_edge_001")):
        records.append(record(100 + i, name, None, root=day_root))
    assert env.emissive_uniform(records)["uniform"] is True


def test_only_the_day_master_is_excused_from_the_factor(city, env):
    # the window views glow without an EmissiveFactor: the factor would miss them, so they count
    window = "/Game/HQ/Materials/M_HQ_WindowView.M_HQ_WindowView"
    records = folded_records(city, NEAR_DARK, LIT) + [
        record(50, "MI_HQ_WindowView_x", None, window)
    ]
    assert env.emissive_uniform(records)["uniform"] is False
    # and a day-master slot that somehow carried a factor is judged like any other
    day_root = f"{city.DAY_MASTER}.M_HQ_CityDay"
    odd = folded_records(city, NEAR_DARK, LIT) + [record(51, "odd", (1.0, 1.0, 1.0), day_root)]
    assert env.emissive_uniform(odd)["uniform"] is False


def test_the_report_and_the_look_pass_name_the_same_day_master(city, env):
    assert city.DAY_MASTER in env.NO_GLOW_ROOTS
    assert city.GLTF_ROOT == env.GLTF_ROOT


def test_the_parameter_is_the_one_the_backend_writes():
    # backend/app/office/unreal.py writes EmissiveFactor (f, f, f) on skyline and near_blocks when
    # the report says uniform; scene_params gives f = 1 at dusk and night, 0.06 at full day
    bridge = (ROOT / "backend" / "app" / "office" / "unreal.py").read_text(encoding="utf-8")
    assert '"EmissiveFactor", (f, f, f)' in bridge
    params = (ROOT / "backend" / "app" / "office" / "scene_params.py").read_text(encoding="utf-8")
    assert re.search(r'"emissive_factor": \{"skyline": city, "near_blocks": city\}', params)


# ---------------------------------------------------------------- the near blocks by day


def test_the_same_city_block_takes_a_facade_albedo_by_day_with_its_own_hue(city):
    dusk = linear("#24242e")  # hq_city.py same_city: 0.018, darker than fresh asphalt
    assert city.luminance(dusk) < 0.02
    day = city.day_albedo(dusk)
    assert city.luminance(day) == pytest.approx(city.DAY_ALBEDO_FLOOR)
    # the hue is its own: every channel scaled alike
    ratios = [d / n for d, n in zip(day, dusk, strict=True)]
    assert max(ratios) == pytest.approx(min(ratios))


def test_a_slot_already_as_light_as_a_facade_is_left_alone(city):
    assert city.day_albedo(linear("#d6d6d0")) is None  # sign_panel
    assert city.day_albedo(linear("#7a5e50")) is None  # the classic block's wall
    assert city.day_albedo(linear("#24242e"), floor=0) is None  # AMN_LOOK_NEAR_DAY_ALBEDO=0


def test_black_and_saturated_colours_stay_in_range(city):
    assert city.day_albedo((0.0, 0.0, 0.0)) == (0.1, 0.1, 0.1)
    day = city.day_albedo((0.0, 0.0, 0.02), floor=0.5)
    assert max(day) <= 1.0


def test_at_daylight_zero_the_block_is_the_dusk_colour_exactly(city):
    dusk = linear("#24242e")
    day = city.day_albedo(dusk)
    assert city.blended_albedo(dusk, day, 0.0) == dusk  # bit for bit: the dusk gate
    assert city.blended_albedo(dusk, day, 1.0) == pytest.approx(day)
    assert city.luminance(city.blended_albedo(dusk, day, 0.5)) == pytest.approx(
        (city.luminance(dusk) + city.luminance(day)) / 2
    )


def test_only_slots_that_paint_with_factors_alone_move(city):
    assert city.paints_with_factors_alone(
        [
            "/InterchangeAssets/gltf/Textures/T_White_srgb.T_White_srgb",
            "/InterchangeAssets/gltf/Textures/T_Generic_N.T_Generic_N",
            None,
        ]
    )
    # a baked atlas or a window picture: the swap the surfaces pass measured at ~6 units
    assert not city.paints_with_factors_alone([f"{SCENE}/../Textures/near_blocks_color"])


def test_reruns_fold_from_the_imported_values(city):
    path = f"{SCENE}/antenna_001.antenna_001"
    assert city.baseline_key(path, "EmissiveStrength") == path  # as since 2026-09-15
    assert city.baseline_key(path, "EmissiveFactor") == f"{path}#EmissiveFactor"


# ---------------------------------------------------------------- the look pass uses all of it


def look_code():
    return (UNREAL / "look_hq_live.py").read_text(encoding="utf-8")


def test_the_look_pass_folds_both_components_and_lifts_the_near_blocks_after():
    code = look_code()
    assert 'os.path.join(HERE, "city_emissive.py")' in code
    assert 'CITY_LABELS = ("skyline", "near_blocks")' in code
    assert "_city.fold_emission(" in code
    main = code[code.index("def main():") :]
    assert main.index("tune_materials(actors)") < main.index("near_blocks_day(actors)")


def test_the_near_blocks_day_material_blends_by_the_real_sun_from_the_dusk(city):
    code = look_code()
    body = code[code.index("def city_day_master():") : code.index("def near_blocks_day(")]
    assert 'vector("BaseColorFactor"' in body and '"RGB", colour, "A"' in body
    assert 'vector("DayBaseColor"' in body and '"RGB", colour, "B"' in body
    assert "scalar(_city.DAY_PARAMETER, 0.0" in body  # 0 = the build's dusk
    assert "EmissiveFactor" not in body.split('"""')[2]  # no glow for the city factor to reach
    assert city.DAY_PARAMETER == "Daylight"
