"""The towers', the trees' and the skyline's day state, as the backend plans it.

At noon the live skyline read as navy "blue cardboard" with lit windows and the crowns as black
cards: the facades' navy and their lit windows are baked into the export's window textures. The
prepared pass (art-source/unreal/towers_day, README.md) gives those materials new parameters whose
defaults paint exactly today's dusk: TowerDaylight 0 and WindowsOn 1 on the facades (M_HQ_TowerDay),
LeafDaylight 0 on the leaves (M_HQ_TreeLeaves), Daylight 0 on the skyline's plain slots
(M_HQ_CityDay). The backend sets them from the real sun only. These tests hold the backend to the
pass's own numbers, read from its source: the window ranks' range and the gate's sharpness, the
day weight, and the defaults the materials are built with. The window curve itself is the
backend's (scene_params WINDOWS_*, the art director's reading of 2026-09-26, test_scene_params):
the pass's own windows_share is the reading of 09-24 the refused run 2 drove with.
"""

from __future__ import annotations

import ast
import importlib.util
import math
import re
from pathlib import Path

import pytest
from app.office import scene_params as sp
from app.office.world import REFERENCE_DUSK_ELEVATION, Sun

ROOT = Path(__file__).resolve().parents[1]
TOWERS_DAY = ROOT / "art-source" / "unreal" / "towers_day"


@pytest.fixture(scope="module")
def td():
    """towers_day.py, the pass's pure part (its module level imports the standard library only)."""
    spec = importlib.util.spec_from_file_location(
        "towers_day_under_test", TOWERS_DAY / "towers_day.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pass_scalars() -> dict[str, float]:
    """towers_day_hq_live.py's ADDED_SCALARS: the defaults M_HQ_TowerDay is built with."""
    source = (TOWERS_DAY / "towers_day_hq_live.py").read_text(encoding="utf-8")
    match = re.search(r"^ADDED_SCALARS = (\{.*?\})\n", source, re.MULTILINE | re.DOTALL)
    assert match, "ADDED_SCALARS not found in towers_day_hq_live.py"
    return ast.literal_eval(match.group(1))


# ---------------------------------------------------------------- the pass's own numbers
def test_the_backend_uses_the_passs_ranks_gate_and_day_weight(td):
    assert sp.TOWER_RANK_MIN == td.RANK_MIN
    assert sp.TOWER_RANK_MAX == td.RANK_MAX
    assert sp.TOWER_GATE_SHARPNESS == td.GATE_SHARPNESS
    assert td.REFERENCE_DUSK_ELEVATION == REFERENCE_DUSK_ELEVATION
    assert td.DAY_FULL_ELEVATION == sp.DAY_FULL_ELEVATION
    for tenth in range(-300, 500):
        e = tenth / 10.0
        assert sp.day_weight(e) == pytest.approx(td.day_weight(e), abs=1e-12), e
    # the window curve is the backend's now: where the pass's 09-24 reading switched the windows
    # off (+5 deg) the backend still lights more than half of them, and at 18:50 most of them
    assert td.windows_share(td.WINDOWS_OFF_ABOVE) == 0.0
    assert sp.windows_share(td.WINDOWS_OFF_ABOVE) > 0.5
    assert sp.windows_share(2.7) > 0.6 > td.WINDOWS_FEW > td.windows_share(2.7)
    # both agree where the art director kept the level pass: the dusk and the night are today's
    for e in (-2.5, -6.0, -30.0):
        assert sp.windows_share(e) == td.windows_share(e) == 1.0


def test_the_materials_defaults_are_the_dusk_the_backend_sends_at_the_reference():
    scalars = pass_scalars()
    assert scalars["TowerDaylight"] == 0.0 and scalars["WindowsOn"] == 1.0
    trees = (TOWERS_DAY / "trees_day_hq_live.py").read_text(encoding="utf-8")
    assert re.search(
        r'daylight\.set_editor_property\("parameter_name", "LeafDaylight"\)\s*\n'
        r'\s*daylight\.set_editor_property\("default_value", 0\.0\)',
        trees,
    )
    evening = Sun(elevation_deg=REFERENCE_DUSK_ELEVATION, azimuth_deg=274.9)
    assert sp.windows_on(sp.tower_windows_share(evening)) == scalars["WindowsOn"]
    assert sp.windows_on(sp.near_windows_share(evening)) == scalars["WindowsOn"]
    assert sp.day_weight(REFERENCE_DUSK_ELEVATION) == scalars["TowerDaylight"]


def test_windows_on_lights_the_share_it_is_asked_for(td):
    """The gate the material builds, saturate((WindowsOn - rank) x 50), over the ranks towers_day.py
    writes (evenly spread, stored as 8-bit floors): the lit windows' summed gate is the share asked
    for, to within about one window of the gate's width. All of them at 1, none at 0."""
    for n in (40, 137, 300):
        stored = [math.floor(r * 255.0) / 255.0 for r in td.lit_ranks(n, seed=7)]
        assert max(stored) <= td.RANK_MAX
        assert all(td.gate(1.0, r) == 1.0 for r in stored)  # the dusk, to the bit
        assert all(td.gate(sp.windows_on(0.0), r) == 0.0 for r in stored)
        for step in range(1, 20):
            share = step / 20.0
            lit = sum(td.gate(sp.windows_on(share), r) for r in stored) / n
            assert lit == pytest.approx(share, abs=0.012 + 1.0 / n), (n, share)
        # continuous at both ends: just above none lights nothing, just below all lights all
        assert all(td.gate(sp.windows_on(1e-4), r) < 0.05 for r in stored)
        assert all(td.gate(sp.windows_on(1.0 - 1e-4), r) > 0.99 for r in stored)
    # the mapping only rises, from none (0) to the dusk's every window (1)
    values = [sp.windows_on(k / 1000.0) for k in range(1001)]
    assert values == sorted(values)
    assert values[0] == 0.0 and values[-1] == 1.0
