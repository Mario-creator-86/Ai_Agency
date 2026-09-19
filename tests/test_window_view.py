"""The room windows' three states (art-source/unreal/window_view.py, used by look_hq_live.py).

The windows keep the glTF instance the import gives them, re-textured exactly as every build since
2026-09-15 has done; the day and night pictures ride on a copy of that instance's own parent chain
with two blends inserted at weight 0. These are the pure rules the look pass follows: which slot
shows which picture, what the night state is when no night picture exists, and the check that the
copied chain paints today's window at DayBlend = NightBlend = 0 (every parameter the old instance
had, unchanged). No Unreal is needed.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "window_view.py"


@pytest.fixture(scope="module")
def wv():
    spec = importlib.util.spec_from_file_location("window_view_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_window_slot_takes_its_own_dusk_picture(wv):
    assert wv.dusk_picture("window_view") == "window_city"
    assert wv.dusk_picture("window_view_b") == "window_city_b"
    # the importer numbers duplicates; the look pass's own instance names its picture
    assert wv.dusk_picture("Window_View_3") == "window_city"
    assert wv.dusk_picture("MI_HQ_WindowView_window_city_b") == "window_city_b"
    for other in ("props_screen", "window_frame", "MI_HQ_WindowView_nonsense", "window_view_c"):
        assert wv.dusk_picture(other) is None, other


def test_the_night_picture_comes_from_make_textures_or_the_window_goes_dark(wv, tmp_path):
    (tmp_path / "window_city.png").write_bytes(b"png")
    missing = wv.night_state(tmp_path)
    # no night picture: the darkest honest state, never the dusk horizon at night
    assert missing["picture"] is None and missing["NightPicture"] == 0.0
    assert "make_textures.py" in missing["note"] and "window_city_night" in missing["note"]
    (tmp_path / "window_city_night.png").write_bytes(b"png")
    present = wv.night_state(tmp_path)
    assert present["picture"] == str(tmp_path / "window_city_night.png")
    assert present["NightPicture"] == 1.0


def test_the_copy_paints_todays_window_when_every_old_value_is_unchanged(wv):
    before = {
        "scalar:EmissiveStrength": 1.5,
        "scalar:BaseColorTexture_TexCoord": 0.0,
        "vector:EmissiveFactor": (1.0, 1.0, 1.0, 1.0),
        "texture:BaseColorTexture": "/Game/HQ/Materials/T_HQ_window_city.T_HQ_window_city",
        "switch:UseVertexColor": False,
    }
    after = dict(before)
    after.update({"scalar:DayBlend": 0.0, "scalar:NightBlend": 0.0, "texture:DayTex": "/Game/x"})
    assert wv.differences(before, after) == []


def test_any_changed_or_lost_old_value_is_named(wv):
    before = {
        "scalar:EmissiveStrength": 1.5,
        "vector:BaseColorFactor": (1.0, 1.0, 1.0, 1.0),
        "texture:EmissiveTexture": "/Game/HQ/Materials/T_HQ_window_city.T_HQ_window_city",
        "switch:TwoSided": True,
    }
    after = {
        "scalar:EmissiveStrength": 1.5000001,
        "vector:BaseColorFactor": (1.0, 1.0, 0.5, 1.0),
        "switch:TwoSided": False,
    }
    found = wv.differences(before, after)
    assert found == [
        "scalar:EmissiveStrength: 1.5 -> 1.5000001",
        "vector:BaseColorFactor: (1.0, 1.0, 1.0, 1.0) -> (1.0, 1.0, 0.5, 1.0)",
        "texture:EmissiveTexture: lost",
        "switch:TwoSided: True -> False",
    ]


def test_the_new_parameters_exist_only_in_the_window_views_parent(wv):
    # the backend writes DayBlend and NightBlend on the props mesh as a whole
    # (SetScalarParameterValueOnMaterials), so no glTF instance may carry either name
    assert {"DayBlend", "NightBlend"} <= set(wv.ADDED_PARAMETERS)
    for name in wv.ADDED_PARAMETERS:
        assert not name.startswith(("BaseColor", "Emissive", "Metallic", "Roughness", "Normal"))
    # both blends start at 0: the copy is today's window until the backend says otherwise
    assert wv.ADDED_DEFAULTS["DayBlend"] == 0.0 and wv.ADDED_DEFAULTS["NightBlend"] == 0.0
    assert wv.ADDED_DEFAULTS["NightPicture"] == 0.0


def test_the_copied_chain_is_versioned_so_a_rerun_never_mixes_two_graphs(wv):
    assert wv.copy_name("M_Default") == f"M_HQ_WindowView_M_Default_v{wv.GRAPH_VERSION}"
    assert wv.copy_name("MI_Default_Opaque_DS") == (
        f"M_HQ_WindowView_MI_Default_Opaque_DS_v{wv.GRAPH_VERSION}"
    )
    # never a name env_report_hq_live.py takes for a window slot (MI_HQ_WindowView...)
    assert not wv.copy_name("M_Default").startswith("MI_HQ_WindowView")
    assert wv.instance_name("window_city").startswith("MI_HQ_WindowView")
