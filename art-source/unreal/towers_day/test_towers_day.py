"""towers_day.py: the day palette read from hq_day.py, the window gate that keeps the dusk exact, the
elevation curve, the haze by day and the mask/rank textures made from the bake PNGs on disk.

    py -3.11 -m pytest test_towers_day.py -q
"""

import importlib.util
import os

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("towers_day", os.path.join(HERE, "towers_day.py"))
td = importlib.util.module_from_spec(spec)
spec.loader.exec_module(td)

FACADES_EXPECTED = {
    "tower_dark_l", "tower_blue_l", "tower_mauve_l", "tower_dark", "tower_blue", "tower_mauve",
    "tower_cool", "tower_right", "city_dense", "city_mid", "classic", "shopfront_block",
}
HAVE_REPO = os.path.exists(td.HQ_DAY)
needs_repo = pytest.mark.skipif(not HAVE_REPO, reason="repository not on this machine")


@needs_repo
def test_day_palette_is_hq_day_s_own():
    c = td.hq_day_constants()
    assert set(c["FACADES"]) == FACADES_EXPECTED
    assert c["TOWER_ROOF"] == "#7b8088" and c["GLASS_METALLIC"] == 0.3
    p = td.facade_day("tower_blue", c)
    assert p["DayWall"] == pytest.approx(td.hex_linear("#8e9cb0"))
    assert p["DayGlass"] == pytest.approx(td.hex_linear("#47698f"))
    # a day facade is a real facade's albedo, not the dusk's navy (0.005-0.03)
    for name in FACADES_EXPECTED:
        q = td.facade_day(name, c)
        assert 0.08 <= td.luminance(q["DayWall"]) <= 0.7
        assert 0.02 <= td.luminance(q["DayGlass"]) <= 0.35


def test_the_gate_keeps_today_s_dusk_exactly_and_is_dark_by_day():
    ranks = [td.RANK_MIN, 0.3, td.RANK_MAX, td.UNLIT_RANK]
    # every stored byte a rank can become, and any filtered blend of two of them
    stored = [td.stored_rank(int(np.floor(r * 255))) for r in ranks]
    blends = [a * t + b * (1 - t) for a in stored for b in stored for t in (0.0, 0.25, 0.5, 1.0)]
    assert all(td.gate(1.0, r) == 1.0 for r in stored + blends)
    assert all(td.gate(0.0, r) == 0.0 for r in stored + blends)
    assert td.windows_on(1.0) == 1.0 and td.windows_on(0.0) == 0.0


@pytest.mark.parametrize("share", [0.1, 0.2, 0.5, 0.9])
def test_windows_on_lights_that_share_of_the_lit_windows(share):
    n = 61  # tower_blue's lit windows
    ranks = [td.stored_rank(int(np.floor(r * 255))) for r in td.lit_ranks(n, seed=1)]
    on = td.windows_on(share)
    lit = sum(td.gate(on, r) >= 0.5 for r in ranks)
    assert abs(lit - share * n) <= 2


def test_the_curve_no_windows_by_day_a_few_below_five_all_at_the_reference():
    assert td.windows_share(45.0) == 0.0
    assert td.windows_share(5.0) == 0.0
    assert 0.0 < td.windows_share(3.0) < td.WINDOWS_FEW
    assert td.windows_share(0.0) == pytest.approx(td.WINDOWS_FEW)
    assert td.WINDOWS_FEW < td.windows_share(-1.5) < 1.0
    assert td.windows_share(-2.5) == 1.0 and td.windows_share(-18.0) == 1.0
    # monotonic as the sun sinks
    es = [x / 10 for x in range(80, -40, -1)]
    shares = [td.windows_share(e) for e in es]
    assert all(b >= a - 1e-12 for a, b in zip(shares, shares[1:], strict=False))
    # the morning share is an Owner decision: off by default
    assert td.windows_share(-2.5, morning=True) == 1.0
    assert td.windows_share(-2.5, morning=True, morning_share=0.5) == 0.5


def test_base_colour_is_the_original_at_daylight_zero_and_the_day_colour_at_one():
    params = {"DayWall": (0.3, 0.3, 0.4), "DayGlass": (0.06, 0.14, 0.27), "TowerRoof": (0.2, 0.2, 0.25)}
    orig = (0.01, 0.012, 0.02)
    assert td.day_base(orig, 1.0, 0.0, params, 0.0) == orig
    assert td.day_base(orig, 1.0, 0.0, params, 1.0) == pytest.approx(params["DayGlass"])
    assert td.day_base(orig, 0.0, 0.0, params, 1.0) == pytest.approx(params["DayWall"])
    assert td.day_base(orig, 0.4, td.roof_weight(1.0), params, 1.0) == pytest.approx(params["TowerRoof"])
    assert td.roof_weight(0.0) == 0.0 and td.roof_weight(0.17) == 0.0  # a wall, even pitched


@needs_repo
def test_haze_by_day_is_the_blender_day_haze_and_the_dusk_is_untouched():
    h = td.haze_day()
    assert h["near"]["alpha_share"] == 0.3 and h["far"]["alpha_share"] == 0.62
    assert h["near"]["colour"] == pytest.approx(td.hex_linear("#d2e0ef"))
    dusk = (0.11, 0.10, 0.19)
    at_ref = td.haze_values("SkylineHaze_near_left", 0.0, dusk, 0.55, 1.0, h)
    assert at_ref == {"HazeColor": dusk, "Opacity": 0.55}
    noon = td.haze_values("SkylineHaze_far_right", 1.0, dusk, 0.385, 1.0, h)
    assert noon["Opacity"] == pytest.approx(0.385 * 0.62)
    assert noon["HazeColor"] == pytest.approx(tuple(c * 1.05 for c in td.hex_linear("#c3d5ea")))


def synthetic_facade(lit_cells):
    glass, wall = (16, 21, 31), (38, 48, 79)
    n, c = td.CELLS, td.CELL_PX
    color = np.zeros((n * c, n * c, 3), np.uint8)
    color[:] = wall
    inside = np.zeros((c, c), bool)
    inside[2:14, 3:13] = True
    inside[:, list(td.MULLION_COLUMNS)] = False
    tile = np.tile(inside, (n, n))
    color[tile] = glass
    emit = np.zeros_like(color)
    for cy, cx in lit_cells:
        cell = np.zeros((n * c, n * c), bool)
        cell[cy * c:(cy + 1) * c, cx * c:(cx + 1) * c] = True
        emit[cell & tile] = (233, 163, 83)
    return color, emit


def test_analysis_reads_glass_wall_and_lit_cells():
    color, emit = synthetic_facade([(0, 0), (5, 7), (23, 23)])
    a = td.analyse_facade(color, emit)
    assert a["glass"] == (16, 21, 31) and a["wall"] == (38, 48, 79)
    assert a["lit_cells"].sum() == 3 and a["lit_cells"][5, 7]
    tex = td.mask_rank_texture(a, seed=3)
    assert tex.shape == color.shape
    assert set(np.unique(tex[..., 0])) == {0, 255}
    # every pixel of a cell carries its cell's rank; no stored rank above RANK_MAX
    assert (tex[..., 1] <= int(np.floor(td.RANK_MAX * 255))).all()
    c = td.CELL_PX
    assert len(np.unique(tex[5 * c:6 * c, 7 * c:8 * c, 1])) == 1
    assert tex[0, 0, 2] == 255 and tex[c, c, 2] == 0


def test_analysis_refuses_what_is_not_the_export_s_grid():
    color, emit = synthetic_facade([(1, 1)])
    color[3, 3] = (200, 0, 0)  # a third colour
    with pytest.raises(ValueError):
        td.analyse_facade(color, emit)
    with pytest.raises(ValueError):
        td.analyse_facade(color[:100, :100], emit[:100, :100])


@needs_repo
@pytest.mark.parametrize("name", sorted(FACADES_EXPECTED))
def test_every_exported_facade_on_disk_is_the_grid_this_reads(name):
    cpath = os.path.join(td.BAKE_DIR, f"{name}_win_color.png")
    if not os.path.exists(cpath):
        pytest.skip("no bake on disk")
    color = np.asarray(Image.open(cpath).convert("RGB"))
    emit = np.asarray(Image.open(os.path.join(td.BAKE_DIR, f"{name}_win_emit.png")).convert("RGB"))
    a = td.analyse_facade(color, emit)
    assert 0 < a["lit_cells"].sum() < td.CELLS * td.CELLS
    # the glass is the default windows_material glass or the facade's own, never the wall
    assert a["glass"] != a["wall"]


@needs_repo
def test_leaf_day_gain_brings_back_the_pack_s_albedo():
    green = os.path.join(td.LEAVES_DIR, "T_HQ_Leaves_Green.png")
    pack = os.path.join(td.LEAVES_DIR, "T_Foliage_Leaves_D.png")
    if not (os.path.exists(green) and os.path.exists(pack)):
        pytest.skip("generated leaves not on disk")
    assert td.leaf_day_gain(green, pack) == pytest.approx(4.7, abs=0.2)
