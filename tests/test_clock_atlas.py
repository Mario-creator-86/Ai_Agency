"""The shelter clock of the live headquarters (art-source/unreal/clock_hq_live.py), without Unreal.

The scene script draws its own seven-segment digits with numpy (no font, so no font licence), and
its material turns the engine's game time plus the backend's ClockOffsetS into hh:mm. The pieces
that decide what the Owner reads - the segment table, the atlas, the time-to-glyph arithmetic the
material's HLSL carries, the layout on the shelter clock's face, and what that face looks like at
the stream's own size - are pure and tested here.

The first live display (rebuild window 2026-09-19 08:38) was unreadable: the digits were about
7 px a slot at 1920 x 1008, their segments 9 texels of a 64 x 128 cell, so the mip the GPU picked
averaged every segment under the mask's clip and the face showed fragments after the sync and
nothing at all before it (the minus and the colon are the thinnest glyphs). The old baked "15:18"
measured 37 x 13 px of lit mint in old_level_before_0.png. These tests render the new face the way
the GPU does - box-filtered mips, trilinear sampling at the pixel centre, the mask's clip - at the
stream's size and at the page's fit size, and read the time back off the pixels.

Run with ``uv run --with numpy --with pillow pytest -q tests/test_clock_atlas.py``.
"""

import importlib.util
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "clock_hq_live.py"

# measured in the rebuild window's frames (scratchpad real_sky/rebuild/frames, 1920 x 1008)
OLD_BAKED_W_PX, OLD_BAKED_H_PX = 37, 13  # "15:18", lit mint pixels, old_level_before_0.png
STREAM_W = 1920


@pytest.fixture(scope="module")
def clock():
    spec = importlib.util.spec_from_file_location("clock_hq_live_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no unreal here: importing must do nothing
    return module


@pytest.fixture(scope="module")
def atlas(clock):
    return clock.digit_atlas()


@pytest.fixture(scope="module")
def mips(clock, atlas):
    return clock.mip_chain(atlas)


@pytest.fixture(scope="module")
def rect(clock):
    face = clock.shelter_clock_face()
    return clock.screen_rect(clock.display_box(face), face["y"], STREAM_W)


def text_of(clock, glyphs):
    return "".join(clock.GLYPH_ORDER[g] for g in glyphs)


def glyphs_of(clock, text):
    return [clock.GLYPH_INDEX[c] for c in text]


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


def test_the_atlas_is_a_power_of_two_mask_of_2048_by_256(clock, atlas):
    assert atlas.dtype == np.uint8
    assert atlas.shape == (clock.CELL_H, clock.CELL_W * clock.CELLS) == (256, 2048)
    h, w = atlas.shape
    assert h & (h - 1) == 0 and w & (w - 1) == 0
    assert atlas.max() == 255


def test_the_atlas_is_only_ever_shrunk_on_screen_by_a_few_mips(clock, rect):
    """Enough texels that the face never magnifies the atlas (a blurry edge), few enough that the
    mip the GPU picks is a small, predictable step: about 8 texels a pixel, mip 3."""
    glyph_px = rect["glyph_h_px"]
    texels_per_px = clock.GLYPH_TEXELS_H / glyph_px
    assert 4.0 <= texels_per_px <= 16.0, texels_per_px
    assert clock.mip_level(rect) == pytest.approx(math.log2(texels_per_px), abs=0.05)


def test_blank_cells_are_empty_and_eight_covers_every_digit(clock, atlas):
    cell = clock.atlas_cell
    for blank in (11, 14, 15):
        assert cell(atlas, blank).max() == 0
    eight = cell(atlas, 8) > 127
    for d in range(10):
        lit = cell(atlas, d) > 127
        assert lit.any()
        assert not (lit & ~eight).any(), d


def test_glyphs_keep_margins_so_the_mips_the_face_uses_do_not_bleed(clock, atlas):
    """16 texels across (a whole texel of mip 4, a mip beyond the one the face uses) and 32 above
    and below, so neither a neighbour nor the clamped edge reaches a glyph."""
    for i in range(clock.CELLS):
        c = clock.atlas_cell(atlas, i)
        assert c[:, :16].max() == 0 and c[:, -16:].max() == 0
        assert c[:32, :].max() == 0 and c[-32:, :].max() == 0


def test_the_segments_are_thick_enough_to_survive_the_mip(clock):
    assert clock.THICK / clock.GLYPH_TEXELS_H >= 0.14
    assert clock.GLYPH_TEXELS_H == clock.GLYPH_Y1 - clock.GLYPH_Y0 == 192


def test_the_colon_is_two_dots_and_the_minus_one_bar_as_thick_as_a_segment(clock, atlas):
    colon = clock.atlas_cell(atlas, 10) > 127
    rows = np.flatnonzero(colon.any(axis=1))
    assert len(np.flatnonzero(np.diff(rows) > 1)) == 1  # two separate runs of rows
    minus = clock.atlas_cell(atlas, 12) > 127
    rows = np.flatnonzero(minus.any(axis=1))
    assert len(np.flatnonzero(np.diff(rows) > 1)) == 0
    assert len(rows) == pytest.approx(clock.THICK, abs=1)


def test_the_atlas_is_drawn_the_same_every_time(clock, atlas):
    assert np.array_equal(atlas, clock.digit_atlas())


def test_the_mips_are_plain_box_averages(clock, atlas, mips):
    base = atlas.astype(np.float64) / 255.0
    assert np.allclose(mips[0], base)
    assert mips[1].shape == (128, 1024)
    assert np.allclose(mips[1][3, 5], base[6:8, 10:12].mean())
    assert mips[-1].shape[0] == 1


# ---------------------------------------------------------------- the time the material shows


def test_the_display_reads_hours_and_minutes(clock):
    at = clock.display_glyphs
    assert text_of(clock, at(game_time_s=0.0, offset_s=15 * 3600 + 18 * 60)) == "15:18"
    assert (
        text_of(clock, at(game_time_s=100.0, offset_s=9 * 3600 + 5 * 60 - 100.0 + 59.9)) == "09:05"
    )
    assert text_of(clock, at(game_time_s=0.0, offset_s=23 * 3600 + 59 * 60 + 59.9)) == "23:59"


def test_the_minute_flips_on_the_second(clock):
    at = clock.display_glyphs
    offset = 19 * 3600 + 30 * 60 - 1000.0  # the backend's sync: local seconds of day - game time
    assert text_of(clock, at(game_time_s=1000.0 + 59.9, offset_s=offset)) == "19:30"
    assert text_of(clock, at(game_time_s=1000.0 + 60.0, offset_s=offset)) == "19:31"


def test_midnight_wraps_and_a_negative_sum_still_reads_a_time(clock):
    at = clock.display_glyphs
    assert text_of(clock, at(game_time_s=0.0, offset_s=86400.0)) == "00:00"
    assert text_of(clock, at(game_time_s=10.0, offset_s=-70.0)) == "23:59"


def test_after_days_of_uptime_the_float32_game_time_still_lands_on_the_minute(clock):
    """The GPU sees the game time as a float32: 30 days of uptime is 2.6 million seconds, a step
    of a quarter second. The minute the Owner reads must not move by it."""
    game = float(np.float32(30 * 86400 + 1234.5))
    offset = 7 * 3600 + 45 * 60 + 30.0 - game
    got = clock.display_glyphs(game_time_s=game, offset_s=offset, float32=True)
    assert text_of(clock, got) == "07:45"


def test_until_the_backend_syncs_the_clock_shows_dashes_not_the_uptime(clock):
    """Nothing invented: before the first ClockOffsetS the material's default is a sentinel, and
    the face reads --:-- rather than the game's uptime dressed as a time of day."""
    got = clock.display_glyphs(game_time_s=5000.0, offset_s=clock.UNSYNCED_OFFSET)
    assert text_of(clock, got) == "--:--"
    assert clock.UNSYNCED_OFFSET < clock.UNSYNCED_BELOW < -30 * 365 * 86400


def test_the_material_hlsl_carries_the_same_arithmetic_and_layout(clock):
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
    for _lo, hi, window in clock.slot_layout():
        assert clock.hlsl_number(hi) in code or hi == 1.0
        assert clock.hlsl_number(window) in code
    assert clock.DIGIT_INPUTS == ("U", "V", "T", "Offset", "Cells")


# ---------------------------------------------------------------- the layout


def test_the_slots_are_four_digits_and_a_narrow_colon_edge_to_edge(clock):
    slots = clock.slot_layout()
    assert len(slots) == 5
    assert slots[0][0] == 0.0 and slots[-1][1] == pytest.approx(1.0)
    for (_, hi), (lo, _) in zip(
        [s[:2] for s in slots[:-1]], [s[:2] for s in slots[1:]], strict=True
    ):
        assert hi == pytest.approx(lo)
    widths = [hi - lo for lo, hi, _ in slots]
    for w in (widths[1], widths[3], widths[4]):
        assert w == pytest.approx(widths[0], abs=1e-5)  # rounded to the HLSL's six decimals
    assert widths[2] < 0.6 * widths[0]


def test_the_glyphs_are_not_stretched(clock):
    """A slot's share of the cell, in texels, over its share of the display, in glyph heights,
    is the same number both ways: one texel is as wide as it is tall on the face."""
    face = clock.shelter_clock_face()
    box = clock.display_box(face)
    glyph_h_m = (box["z1"] - box["z0"]) * clock.GLYPH_TEXELS_H / clock.CELL_H
    width_m = box["x1"] - box["x0"]
    for lo, hi, window in clock.slot_layout():
        texels_per_m_u = window * clock.CELL_W / ((hi - lo) * width_m)
        texels_per_m_v = clock.GLYPH_TEXELS_H / glyph_h_m
        assert texels_per_m_u == pytest.approx(texels_per_m_v, rel=1e-3)


def test_every_window_stays_inside_its_own_cell(clock):
    for _, _, window in clock.slot_layout():
        assert 0.0 < window <= 1.0


def test_the_display_box_is_centred_in_the_face_and_fills_most_of_it(clock):
    face = clock.shelter_clock_face()
    box = clock.display_box(face)
    assert face["x0"] < box["x0"] < box["x1"] < face["x1"]
    assert face["z0"] < box["z0"] < box["z1"] < face["z1"]
    assert (box["x0"] + box["x1"]) / 2 == pytest.approx((face["x0"] + face["x1"]) / 2)
    assert (box["z0"] + box["z1"]) / 2 == pytest.approx((face["z0"] + face["z1"]) / 2)
    assert (box["x1"] - box["x0"]) / (face["x1"] - face["x0"]) == pytest.approx(clock.FACE_FILL)


def test_the_digits_are_larger_than_the_baked_ones_on_the_stream(clock, rect, mips):
    """Measured on the frame, not assumed: the lit extent of the rendered face at 1920 x 1008."""
    assert rect["glyph_h_px"] >= 1.6 * OLD_BAKED_H_PX
    widest = clock.render(glyphs_of(clock, "88:88"), rect, mips)
    lit_cols = np.flatnonzero((widest["image"] >= 0.5).any(axis=0))
    assert lit_cols[-1] - lit_cols[0] + 1 >= 60
    lit_rows = np.flatnonzero((widest["image"] >= 0.5).any(axis=1))
    assert lit_rows[-1] - lit_rows[0] + 1 >= 1.6 * OLD_BAKED_H_PX
    same = clock.render(glyphs_of(clock, "15:18"), rect, mips)
    lit_cols = np.flatnonzero((same["image"] >= 0.5).any(axis=0))
    assert lit_cols[-1] - lit_cols[0] + 1 >= 1.4 * OLD_BAKED_W_PX


def test_a_segment_is_at_least_three_pixels_thick_on_the_stream(clock, rect):
    assert clock.THICK / clock.GLYPH_TEXELS_H * rect["glyph_h_px"] >= 3.0


# ---------------------------------------------------------------- read back off the pixels


def segment_points(clock, slot, glyph):
    """Screen points of each segment's centre (and each colon dot's) in one slot."""
    lo, hi, window = clock.slot_layout()[slot]
    points = clock.segment_centres() if glyph != ":" else clock.colon_centres()
    return lo, hi, window, points


def read_face(clock, frame, threshold=0.5):
    """The text a pair of eyes reads off the rendered face: each digit slot's lit segments looked
    up in the segment table, the colon slot read by its two dots. '?' where nothing matches."""
    img, ox, oy, r = frame["image"], frame["origin"][0], frame["origin"][1], frame["rect"]

    def lit(tx, ty, lo, hi, window):
        t = (tx / clock.CELL_W - 0.5) / window + 0.5
        sx = r["x"] + (lo + t * (hi - lo)) * r["w"]
        sy = r["y"] + ty / clock.CELL_H * r["h"]
        return img[int(math.floor(sy)) - oy, int(math.floor(sx)) - ox] >= threshold

    out = []
    for slot, (lo, hi, window) in enumerate(clock.slot_layout()):
        if slot == 2:
            dots = [lit(x, y, lo, hi, window) for x, y in clock.colon_centres().values()]
            out.append(":" if all(dots) else ("?" if any(dots) else " "))
            continue
        on = {s for s, (x, y) in clock.segment_centres().items() if lit(x, y, lo, hi, window)}
        match = [g for g in "0123456789- " if clock.SEGMENTS[g] == on]
        out.append(match[0] if match else "?")
    return "".join(out)


READINGS = ["01:23", "45:67", "89:00", "15:18", "20:08", "23:59", "07:41", "--:--"]


@pytest.mark.parametrize("sub_px", [0.0, 0.25, 0.5, 0.75])
def test_every_digit_reads_back_off_the_stream_frame_with_one_sample_a_pixel(
    clock, rect, mips, sub_px
):
    """The worst case: one sample at each pixel centre, no temporal anti-aliasing, at any
    sub-pixel position of the face. Every digit, the colon and the dashes must read back."""
    shifted = dict(rect, x=rect["x"] + sub_px, y=rect["y"] + sub_px)
    for text in READINGS:
        frame = clock.render(glyphs_of(clock, text), shifted, mips)
        assert read_face(clock, frame) == text, (text, sub_px)


def test_the_holes_of_an_eight_stay_dark(clock, rect, mips):
    frame = clock.render(glyphs_of(clock, "88:88"), rect, mips)
    img, (ox, oy), r = frame["image"], frame["origin"], frame["rect"]
    lo, hi, window = clock.slot_layout()[0]
    for tx, ty in clock.hole_centres():
        t = (tx / clock.CELL_W - 0.5) / window + 0.5
        sx, sy = r["x"] + (lo + t * (hi - lo)) * r["w"], r["y"] + ty / clock.CELL_H * r["h"]
        assert img[int(sy) - oy, int(sx) - ox] < 0.5


@pytest.mark.parametrize("page_w", [1440, 1280])
def test_the_face_still_reads_when_the_page_shrinks_the_stream_to_fit(clock, rect, mips, page_w):
    """The page shows the 1920-wide stream at fit: the browser shrinks the decoded frame. Render
    as TSR resolves (4 x 4 jittered samples a pixel), shrink by area as a browser does, read."""
    scale = page_w / STREAM_W
    for text in READINGS:
        frame = clock.render(glyphs_of(clock, text), rect, mips, samples=4)
        small = clock.shrink(frame, scale)
        assert read_face(clock, small, threshold=0.45) == text, (text, page_w)


def test_before_the_first_sync_the_face_shows_dashes_drawn_by_the_build(clock, rect, mips):
    glyphs = clock.display_glyphs(game_time_s=12.0, offset_s=clock.UNSYNCED_OFFSET)
    frame = clock.render(glyphs, rect, mips)
    assert read_face(clock, frame) == "--:--"
    assert (frame["image"] >= 0.5).sum() > 40  # lit pixels, not a blank face


def test_outside_the_digit_box_the_face_is_blank(clock):
    u, v = clock.atlas_uv(
        np.array([-0.1, 1.1, 0.5]), np.array([0.5, 0.5, 1.2]), glyphs_of(clock, "88:88")
    )
    cell = np.floor(u * clock.CELLS)
    assert (cell == clock.GLYPH_INDEX[" "]).all()


# ---------------------------------------------------------------- the texture's settings


def test_the_atlas_texture_is_linear_uncompressed_trilinear_with_box_mips_and_resident(clock):
    s = clock.ATLAS_TEXTURE_SETTINGS
    assert s["srgb"] is False  # the mask's 0.5 must be coverage 0.5, not an sRGB-decoded 0.21
    # G8, no blocks
    assert s["compression_settings"] == ("TextureCompressionSettings", "TC_GRAYSCALE")
    assert s["filter"] == ("TextureFilter", "TF_TRILINEAR")
    assert s["mip_gen_settings"] == ("TextureMipGenSettings", "TMGS_SIMPLE_AVERAGE")
    assert s["address_x"] == s["address_y"] == ("TextureAddress", "TA_CLAMP")
    assert s["never_stream"] is True  # all mips resident from the first frame, so --:-- shows
    assert s["lod_bias"] == 0


def test_the_sampler_type_follows_the_texture(clock):
    assert clock.sampler_type_for("TC_GRAYSCALE", False) == "SAMPLERTYPE_LINEAR_GRAYSCALE"
    assert clock.sampler_type_for("TC_GRAYSCALE", True) == "SAMPLERTYPE_GRAYSCALE"
    assert clock.sampler_type_for("TC_DEFAULT", True) == "SAMPLERTYPE_COLOR"
    assert clock.sampler_type_for("TC_DEFAULT", False) == "SAMPLERTYPE_LINEAR_COLOR"


def test_the_mask_clips_at_half_coverage(clock):
    assert clock.MASK_CLIP == 0.5


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


def test_the_face_on_the_stream_is_where_the_frames_show_it(clock):
    """The clock box measured 1691-1776 across in the rebuild's frames; its face rect is inset."""
    face = clock.shelter_clock_face()
    r = clock.screen_rect(face, face["y"], STREAM_W)
    assert r["x"] == pytest.approx(1411 * 1.2, abs=0.01) and r["x"] + r["w"] == pytest.approx(
        1477 * 1.2, abs=0.01
    )
    assert 1691 < r["x"] and r["x"] + r["w"] < 1776


def test_the_colour_is_the_mint_of_the_display_in_linear(clock):
    r, g, b = clock.linear("#7df0c4")
    assert math.isclose(r, ((0x7D / 255 + 0.055) / 1.055) ** 2.4)
    assert g > b > r
    assert clock.TODAY_STRENGTH == pytest.approx(4.35684)


# ------------------------------------------------------------ the environment report's clock entry


@pytest.fixture(scope="module")
def env_report():
    path = ROOT / "art-source" / "unreal" / "env_report_hq_live.py"
    spec = importlib.util.spec_from_file_location("env_report_for_the_clock", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no unreal here: importing must do nothing
    return module


def test_the_report_names_the_clock_the_scene_script_builds(clock, env_report):
    assert env_report.CLOCK_UNSYNCED == clock.UNSYNCED_OFFSET
    assert env_report.CLOCK_ATLAS == clock.TEXTURE
    assert env_report.CLOCK_MATERIAL == clock.MATERIAL
    assert set(env_report.CLOCK_ATLAS_READ) <= set(clock.ATLAS_TEXTURE_SETTINGS)


def test_the_clock_entry_says_what_the_face_reads_before_the_sync(env_report):
    entry = env_report.clock_entry()
    assert entry["parameter"] == "ClockOffsetS"
    assert entry["unsynced_default"] < -1e9
    assert entry["unsynced_reads"] == "--:--"
    assert "atlas" not in entry and "material" not in entry
    assert env_report._clock_build() == (None, None)  # outside Unreal nothing is read


def test_the_clock_entry_carries_the_settings_read_in_unreal(env_report):
    atlas = {"path": env_report.CLOCK_ATLAS, "size": [2048, 256], "srgb": "False"}
    material = {"path": env_report.CLOCK_MATERIAL, "opacity_mask_clip_value": 0.5}
    entry = env_report.clock_entry(atlas, material)
    assert entry["atlas"] == atlas and entry["material"] == material
