"""The sky atlas for the live headquarters (art-source/unreal/compose_sky_backdrop.py).

The Owner approved today's dusk. The atlas's -2.5 cell is what the stream shows at the reference
parameters, so it has to be today's composition exactly, byte for byte, before the upscale that
the single plate used to get. ``_today`` below is the composition as it stood at commit 39caeb0,
copied verbatim with only the frame size turned into arguments, so a small frame keeps the test
fast. The scene scripts run inside Unreal's or Blender's Python; this one runs anywhere numpy
and Pillow do (``uv run --with numpy --with pillow pytest -q tests/test_sky_atlas.py``).
"""

import importlib.util
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
ImageFilter = pytest.importorskip("PIL.ImageFilter")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "compose_sky_backdrop.py"
SKY_DIR = ROOT / "frontend" / "public" / "assets" / "hq" / "sky"
SMALL = (160, 84, 35)  # a tenth of the plate: 1600 x 840, horizon at row 350


def _load():
    spec = importlib.util.spec_from_file_location("compose_sky_backdrop_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- today's composition (39caeb0)

_SKY = {
    "night": ["#070b1a", "#0f1630", "#1a2244", "#232a4a"],
    "dusk": ["#1b2644", "#3b4a7c", "#d0806c", "#7a5c70"],
    "day": ["#3f78c8", "#79a9e0", "#cfe2f3", "#b9cde2"],
}
_POSITIONS = [0.0, 0.24, 0.4, 0.62]
_ELEVATION = -2.5


def _smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def _rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) for i in (0, 2, 4)], np.float32)


def _mix(a, b, t):
    return a + (b - a) * min(1.0, max(0.0, t))


def _radial(w, h, cx, cy, radius, y_scale, stops):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xs - cx) ** 2 + ((ys - cy) / y_scale) ** 2) / radius
    out = np.zeros((h, w, 4), np.float32)
    for (p0, c0, a0), (p1, c1, a1) in zip(stops, stops[1:], strict=False):
        m = (d >= p0) & (d <= p1)
        t = ((d[m] - p0) / (p1 - p0))[:, None]
        col = np.array(c0, np.float32) * (1 - t) + np.array(c1, np.float32) * t
        alpha = a0 * (1 - t[:, 0]) + a1 * t[:, 0]
        out[m, :3] = col
        out[m, 3] = alpha
    return out


def _over(base, layer_rgb, alpha):
    a = alpha[..., None]
    return base * (1 - a) + layer_rgb * a


def _today(a, W, H, HORIZON):
    """compose_sky_backdrop.main() at 39caeb0 up to the uint8 image, before its upscale."""
    daylight = _smoothstep(-8, 7, _ELEVATION)
    dusk = math.exp(-(((_ELEVATION - 1) / 6.5) ** 2))

    stops = []
    for i, pos in enumerate(_POSITIONS):
        base = _mix(_rgb(_SKY["night"][i]), _rgb(_SKY["day"][i]), daylight)
        stops.append((pos, _mix(base, _rgb(_SKY["dusk"][i]), dusk * 0.95)))
    rows = np.linspace(0, 1, H, dtype=np.float32)
    column = np.zeros((H, 3), np.float32)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:], strict=False):
        m = (rows >= p0) & (rows <= p1)
        t = ((rows[m] - p0) / (p1 - p0))[:, None]
        column[m] = c0 * (1 - t) + c1 * t
    column[rows > _POSITIONS[-1]] = stops[-1][1]
    sky = np.repeat(column[:, None, :], W, axis=1)

    glow = dusk
    warm = _radial(
        W,
        H,
        0,
        HORIZON,
        W * 0.55,
        0.42,
        [
            (0.0, (250, 165, 115), 0.85 * glow),
            (0.5, (218, 128, 112), 0.42 * glow),
            (1.0, (214, 120, 110), 0.0),
        ],
    )
    sky = _over(sky, warm[..., :3], warm[..., 3])
    cool = _radial(
        W,
        H,
        W * 0.86,
        20,
        W * 0.26,
        0.55,
        [(0.0, (100, 146, 220), 0.45 * glow), (1.0, (100, 146, 220), 0.0)],
    )
    sky = _over(sky, cool[..., :3], cool[..., 3])

    day_w = daylight * (1 - dusk)
    night_w = (1 - daylight) * (1 - dusk)
    total = dusk + day_w + night_w
    for look, weight in (
        ("night", night_w / total),
        ("day", day_w / total),
        ("dusk", dusk / total),
    ):
        path = os.path.join(SKY_DIR, f"clouds_{look}.webp")
        if weight < 0.01 or not os.path.exists(path):
            continue
        layer = Image.open(path).convert("RGBA")
        if a.cloud_zoom > 1.0:
            cw, ch = layer.width / a.cloud_zoom, layer.height / a.cloud_zoom
            left, top = (layer.width - cw) / 2, (layer.height - ch) / 2
            layer = layer.crop((round(left), round(top), round(left + cw), round(top + ch)))
        lh = round(layer.height * W / layer.width)
        layer = layer.resize((W, lh), Image.LANCZOS)
        if a.cloud_blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(a.cloud_blur))
        arr = np.asarray(layer, np.float32).copy()
        arr[..., :3] *= np.array([float(v) for v in a.cloud_tint.split(",")], np.float32)
        region = sky[:lh]
        sky[:lh] = _over(region, arr[..., :3], arr[..., 3] / 255.0 * weight * a.cloud_strength)

    sky = sky * np.array([float(v) for v in a.tint.split(",")], np.float32)
    return np.clip(sky, 0, 255).astype(np.uint8)


TODAY_ARGS = SimpleNamespace(
    tint="1.0,1.12,1.10",
    cloud_zoom=1.4,
    cloud_strength=0.32,
    cloud_blur=3.0,
    cloud_tint="1.16,0.96,0.93",
)


# ---------------------------------------------------------------- the tests


def test_cloud_layers_are_present_so_the_comparison_covers_them():
    for look in ("night", "day", "dusk"):
        assert (SKY_DIR / f"clouds_{look}.webp").exists()


def test_the_reference_cell_is_todays_composition_pixel_for_pixel():
    compose = _load()
    w, h, horizon = SMALL
    cell = compose.compose_cell(-2.5, compose.Options(), w=w, h=h, horizon=horizon)
    expected = _today(TODAY_ARGS, w, h, horizon)
    assert cell.dtype == np.uint8 and cell.shape == (h, w, 3)
    assert np.array_equal(cell, expected)


def test_the_default_options_are_todays_tuning():
    compose = _load()
    o = compose.Options()
    assert (o.tint, o.cloud_zoom, o.cloud_strength, o.cloud_blur, o.cloud_tint) == (
        TODAY_ARGS.tint,
        TODAY_ARGS.cloud_zoom,
        TODAY_ARGS.cloud_strength,
        TODAY_ARGS.cloud_blur,
        TODAY_ARGS.cloud_tint,
    )


def test_the_single_plate_still_comes_out_as_before(tmp_path):
    """Without --atlas the script writes the plate it always wrote: today's cell, upscaled x2."""
    compose = _load()
    out = tmp_path / "sky.png"
    compose.main(["--out", str(out), "--size", "160,84,35"])
    expected = Image.fromarray(_today(TODAY_ARGS, *SMALL), "RGB").resize((320, 168), Image.LANCZOS)
    assert np.array_equal(np.asarray(Image.open(out)), np.asarray(expected))


def test_the_atlas_stacks_the_listed_cells_at_the_native_size(tmp_path):
    compose = _load()
    out = tmp_path / "sky_atlas.png"
    compose.main(["--atlas", str(out), "--size", "160,84,35"])
    atlas = np.asarray(Image.open(out))
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    elevations = [-18.0, -12.0, -8.0, -5.0, -2.5, 0.0, 3.0, 8.0, 15.0, 35.0]
    assert meta["elevations"] == elevations
    assert (meta["cell_width"], meta["cell_height"], meta["cells"]) == (160, 84, 10)
    assert meta["reference_elevation"] == -2.5 and meta["reference_cell"] == 4
    assert atlas.shape == (84 * 10, 160, 3)  # no upscale: the composer's own size
    ref = atlas[4 * 84 : 5 * 84]
    assert np.array_equal(ref, _today(TODAY_ARGS, *SMALL))
    for i, elevation in enumerate(elevations):
        cell = compose.compose_cell(elevation, compose.Options(), w=160, h=84, horizon=35)
        assert np.array_equal(atlas[i * 84 : (i + 1) * 84], cell)


def test_the_default_atlas_is_the_full_plate_size():
    compose = _load()
    assert (compose.W, compose.H, compose.HORIZON) == (1600, 840, 350)
    assert compose.ATLAS_ELEVATIONS == (-18.0, -12.0, -8.0, -5.0, -2.5, 0.0, 3.0, 8.0, 15.0, 35.0)
    # 1600 x 8400: under the engine's 16384 limit, and a multiple of 4 for block compression
    assert compose.H * len(compose.ATLAS_ELEVATIONS) <= 16384
    assert compose.W % 4 == 0 and (compose.H * len(compose.ATLAS_ELEVATIONS)) % 4 == 0


def test_the_cells_follow_the_hour():
    """Night is darker than dusk, day is lighter and bluer; the reference is the dusk it was."""
    compose = _load()
    w, h, horizon = SMALL
    night = compose.compose_cell(-18, compose.Options(), w=w, h=h, horizon=horizon).astype(float)
    dusk = compose.compose_cell(-2.5, compose.Options(), w=w, h=h, horizon=horizon).astype(float)
    day = compose.compose_cell(35, compose.Options(), w=w, h=h, horizon=horizon).astype(float)
    assert night.mean() < dusk.mean() < day.mean()
    assert day[..., 2].mean() > day[..., 0].mean()


def test_the_blend_weights_are_the_composers_own_functions():
    compose = _load()
    assert compose.daylight_of(-2.5) == _smoothstep(-8, 7, -2.5)
    assert compose.dusk_of(-2.5) == math.exp(-(((-2.5 - 1) / 6.5) ** 2))


def test_importing_the_script_composes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _load()
    assert list(tmp_path.iterdir()) == []
