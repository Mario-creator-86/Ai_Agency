"""The shelter clock of the live headquarters (art-source/unreal/clock_hq_live.py), without Unreal.

The scene script draws its own seven-segment digits with numpy (no font, so no font licence), and
its material turns the engine's game time plus the backend's ClockOffsetS into hh:mm. The pieces
that decide what the Owner reads - the segment table, the atlas, the time-to-glyph arithmetic the
material's HLSL carries, and where the display sits - are pure and tested here. Run with
``uv run --with numpy --with pillow pytest -q tests/test_clock_atlas.py``.
"""

import importlib.util
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "clock_hq_live.py"


@pytest.fixture(scope="module")
def clock():
    spec = importlib.util.spec_from_file_location("clock_hq_live_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no unreal here: importing must do nothing
    return module


# ---------------------------------------------------------------- the glyphs


def test_the_segment_table_is_the_standard_seven_segment_one(clock):
    seg = clock.SEGMENTS
    assert seg["8"] == set("abcdefg")
    assert seg["1"] == set("bc")
    assert seg["7"] == set("abc")
    assert seg["0"] == set("abcdef")
    assert seg["-"] == set("g")
    assert seg["°"] == set("abfg")
    assert seg[" "] == set()
    assert len({frozenset(seg[d]) for d in "0123456789"}) == 10


def test_the_atlas_order_is_digits_colon_blank_minus_degree(clock):
    assert clock.GLYPH_ORDER[:14] == [
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        ":",
        " ",
        "-",
        "°",
    ]
    assert clock.GLYPH_INDEX[":"] == 10 and clock.GLYPH_INDEX[" "] == 11
    assert clock.GLYPH_INDEX["-"] == 12 and clock.GLYPH_INDEX["°"] == 13
    assert clock.CELLS == 16  # padded to a power of two so the texture keeps its mips


def test_the_atlas_is_a_power_of_two_mask(clock):
    atlas = clock.digit_atlas()
    assert atlas.dtype == np.uint8
    assert atlas.shape == (clock.CELL_H, clock.CELL_W * clock.CELLS)
    h, w = atlas.shape
    assert h & (h - 1) == 0 and w & (w - 1) == 0
    assert atlas.max() == 255


def test_blank_cells_are_empty_and_eight_covers_every_digit(clock):
    atlas = clock.digit_atlas()
    cell = clock.atlas_cell
    for blank in (11, 14, 15):
        assert cell(atlas, blank).max() == 0
    eight = cell(atlas, 8) > 127
    for d in range(10):
        lit = cell(atlas, d) > 127
        assert lit.any()
        assert not (lit & ~eight).any(), d


def test_glyphs_keep_a_margin_so_mips_do_not_bleed_between_cells(clock):
    atlas = clock.digit_atlas()
    for i in range(clock.CELLS):
        c = clock.atlas_cell(atlas, i)
        assert c[:, :4].max() == 0 and c[:, -4:].max() == 0
        assert c[:4, :].max() == 0 and c[-4:, :].max() == 0


def test_the_colon_is_two_dots(clock):
    colon = clock.atlas_cell(clock.digit_atlas(), 10) > 127
    rows = np.flatnonzero(colon.any(axis=1))
    gaps = np.flatnonzero(np.diff(rows) > 1)
    assert len(gaps) == 1  # two separate runs of rows


def test_the_atlas_is_drawn_the_same_every_time(clock):
    assert np.array_equal(clock.digit_atlas(), clock.digit_atlas())


# ---------------------------------------------------------------- the time the material shows


def hhmm(clock, glyphs):
    return "".join(clock.GLYPH_ORDER[g] for g in glyphs)


def test_the_display_reads_hours_and_minutes(clock):
    at = clock.display_glyphs
    assert hhmm(clock, at(game_time_s=0.0, offset_s=15 * 3600 + 18 * 60)) == "15:18"
    assert hhmm(clock, at(game_time_s=100.0, offset_s=9 * 3600 + 5 * 60 - 100.0 + 59.9)) == "09:05"
    assert hhmm(clock, at(game_time_s=0.0, offset_s=23 * 3600 + 59 * 60 + 59.9)) == "23:59"


def test_the_minute_flips_on_the_second(clock):
    at = clock.display_glyphs
    offset = 19 * 3600 + 30 * 60 - 1000.0  # the backend's sync: local seconds of day - game time
    assert hhmm(clock, at(game_time_s=1000.0 + 59.9, offset_s=offset)) == "19:30"
    assert hhmm(clock, at(game_time_s=1000.0 + 60.0, offset_s=offset)) == "19:31"


def test_midnight_wraps_and_a_negative_sum_still_reads_a_time(clock):
    at = clock.display_glyphs
    assert hhmm(clock, at(game_time_s=0.0, offset_s=86400.0)) == "00:00"
    assert hhmm(clock, at(game_time_s=10.0, offset_s=-70.0)) == "23:59"


def test_after_days_of_uptime_the_float32_game_time_still_lands_on_the_minute(clock):
    """The GPU sees the game time as a float32: 30 days of uptime is 2.6 million seconds, a step
    of a quarter second. The minute the Owner reads must not move by it."""
    game = float(np.float32(30 * 86400 + 1234.5))
    offset = 7 * 3600 + 45 * 60 + 30.0 - game
    got = clock.display_glyphs(game_time_s=game, offset_s=offset, float32=True)
    assert hhmm(clock, got) == "07:45"


def test_until_the_backend_syncs_the_clock_shows_dashes_not_the_uptime(clock):
    """Nothing invented: before the first ClockOffsetS the material's default is a sentinel, and
    the face reads --:-- rather than the game's uptime dressed as a time of day."""
    got = clock.display_glyphs(game_time_s=5000.0, offset_s=clock.UNSYNCED_OFFSET)
    assert hhmm(clock, got) == "--:--"
    assert clock.UNSYNCED_OFFSET < clock.UNSYNCED_BELOW < -30 * 365 * 86400


def test_the_material_hlsl_carries_the_same_arithmetic(clock):
    code = clock.DIGIT_HLSL
    for fragment in (
        "86400.0",
        "60.0",
        "10.0",
        "floor",
        f"{clock.UNSYNCED_BELOW:.1e}",
        "Offset",
        "T",
        "U",
        "V",
        "Cells",
    ):
        assert fragment in code
    assert clock.DIGIT_INPUTS == ("U", "V", "T", "Offset", "Cells")


# ---------------------------------------------------------------- where it stands


def test_the_face_is_the_shelter_clock_rect_of_the_blender_street(clock):
    """hq_city.py: the box from columns 1408-1480, the rect 1411-1477 inset 8 cm top and bottom,
    between rows 657 and 620 at the box's front, in the plane just in front of it."""
    face = clock.shelter_clock_face()
    col0, row0 = clock.project((face["x0"], face["y"], face["z0"]))
    col1, row1 = clock.project((face["x1"], face["y"], face["z1"]))
    assert math.isclose(col0, 1411, abs_tol=1e-6) and math.isclose(col1, 1477, abs_tol=1e-6)
    ppm_z = clock.PPM * math.cos(math.radians(10))  # rows per metre of height
    assert math.isclose(row0, 657 - 0.08 * ppm_z, abs_tol=0.2)
    assert math.isclose(row1, 620 + 0.08 * ppm_z, abs_tol=0.2)
    assert face["z1"] - face["z0"] > 1.0 and face["x1"] - face["x0"] > 2.3


def test_the_digit_box_follows_todays_digits_when_they_are_found(clock):
    face = clock.shelter_clock_face()
    centre = (face["x0"] + face["x1"]) / 2.0
    baked = {
        "x0": centre - 0.9,
        "x1": centre + 0.9,
        "z0": face["z0"] + 0.2,
        "z1": face["z0"] + 0.75,
    }
    assert clock.digit_box(face, baked) == baked


def test_without_todays_digits_the_box_sits_inside_the_face(clock):
    face = clock.shelter_clock_face()
    box = clock.digit_box(face, None)
    assert face["x0"] < box["x0"] < box["x1"] < face["x1"]
    assert face["z0"] < box["z0"] < box["z1"] < face["z1"]


def test_the_colour_is_the_mint_of_the_display_in_linear(clock):
    r, g, b = clock.linear("#7df0c4")
    assert math.isclose(r, ((0x7D / 255 + 0.055) / 1.055) ** 2.4)
    assert g > b > r
    assert clock.TODAY_STRENGTH == pytest.approx(4.35684)
