"""AI-only panel decisions: pixel bands never spend money or certify a picture.

No GPU, external provider or real FFmpeg required.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.media.qc import _panels_check, still_is_degenerate
from app.media.still_gate import StillPlan, local_checks


def test_still_panel_heuristic_cannot_block_even_in_production():
    plan = StillPlan(
        scene=1,
        still_prompt="A desk beneath a dark evening window",
        camera_move="static",
        faces_forbidden=False,
    )
    # No encoder and even no image on disk: only the AI review decides panels.
    (check,) = local_checks(
        Path("not-a-real-image.png"),
        plan,
        environment="PRODUCTION",
        measure=("panels",),
    )
    assert check.code == "panels"
    assert check.status == "NOT_APPLICABLE"
    assert check.blocking is False


def test_clip_panel_heuristic_does_not_measure_frames_or_block():
    measured = {}
    result = _panels_check(
        None,
        [("first", 0.0, Path("absent.png"))],
        measured=measured,
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.blocking is False
    assert measured["panels"] == {"method": "vision_only", "frames": []}


@pytest.mark.parametrize(
    ("columns", "rows", "blank"),
    [
        (0.98, 0.10, False),  # vertical stripes: content is for AI
        (0.10, 0.98, False),  # horizontal bands: content is for AI
        (0.98, 0.98, True),   # essentially uniform still: objective technical failure
    ],
)
def test_ssim_single_axis_never_refuses_as_band(tmp_path, monkeypatch, columns, rows, blank):
    image = tmp_path / "frame.png"
    image.write_bytes(b"file exists: ffmpeg is stubbed")

    def fake_run(args, **_kwargs):
        is_columns = "scale=270:1" in " ".join(args)
        score = columns if is_columns else rows
        return SimpleNamespace(stderr=f"SSIM All:{score:.4f}")

    monkeypatch.setattr("subprocess.run", fake_run)
    problem = still_is_degenerate("ffmpeg", image)
    assert (problem is not None) is blank
    if blank:
        assert "blank or uniform" in problem
