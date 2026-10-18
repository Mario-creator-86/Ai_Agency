"""Final purchase protection for Kael/Sarah, with no GPU or vendor calls.

The autonomous staircase already asks Sarah to review prompts, but a direct
shooting-sheet/API purchase must enforce the same decision independently.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.media import prompt_audit, shooting_sheet
from app.media.models import StoryboardScene
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_rewrites_failed_scene import a_planned_film, studio  # noqa: F401


@pytest.mark.parametrize("step", ["stills", "test_shot", "motion"])
def test_owner_direct_purchase_cannot_skip_sarah_before_balance(
    engine, tmp_path, studio, monkeypatch, step
):
    """Even a direct Owner/API press stops before any balance read or vendor request."""
    from app.media import factory

    board = a_planned_film(engine, tmp_path)
    monkeypatch.setattr(
        factory, "reference_image_adapter",
        lambda *args, **kwargs: SimpleNamespace(model="offline"),
    )
    monkeypatch.setattr(
        shooting_sheet, "_context", lambda *args, **kwargs: SimpleNamespace()
    )
    monkeypatch.setattr(
        shooting_sheet, "_sheet",
        lambda *args, **kwargs: {
            "sheet_hash": "local",
            "shot_plan_gaps": [],
            "lint_blocked": False,
            "steps": {step: {"to_buy": [1], "waiting_ro": ""}},
        },
    )
    monkeypatch.setattr(
        shooting_sheet, "_read_balance",
        lambda *args, **kwargs: pytest.fail("No credits may be checked or spent yet"),
    )
    with pytest.raises(shooting_sheet.SheetStepRefused) as caught:
        shooting_sheet._run_sheet_step(
            engine, board, step, "local",
            correlation_id=str(uuid4()),
            capabilities=None, integration_id=None, table=None,
            account=None, image_adapter=None, adapter_for_model=None,
            registry=None, allow_over_budget=False, allowed=None,
            resolution=None, settings=SimpleNamespace(motion_resolution="1080p"),
            environment="PRODUCTION", storage_root=None, ffmpeg_path=None,
            today=None,
        )
    assert caught.value.status == prompt_audit.NEEDS_PROMPT_APPROVAL
    assert "1" in caught.value.reason_ro


@pytest.mark.parametrize(
    ("step", "layer", "field"),
    [
        ("stills", "still", "still_prompt"),
        ("test_shot", "motion", "motion_prompt"),
        ("motion", "motion", "motion_prompt"),
    ],
)
def test_sarah_approval_is_bound_to_current_exact_vendor_words(
    engine, tmp_path, studio, step, layer, field
):
    """A previous approval cannot license edited vendor text or the opposite layer."""
    board = a_planned_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        )
        package = dict(row.prompt_json or {})
        package["prompt_format"] = "editor_final_v1"
        package["still_prompt"] = str(package.get("still_prompt") or "Vertical still, a hillside.")
        package["motion_prompt"] = str(package.get("motion_prompt") or "A tracked cloud crossing the valley.")
        row.prompt_json = package

    assert prompt_audit.purchase_approval_gaps(engine, board, step, [1]) == [1]
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        )
        words = prompt_audit.prompt_text(row.prompt_json, layer)
    prompt_audit._record(
        engine, storyboard_id=board, scene=1, layer=layer,
        digest=prompt_audit.prompt_digest(words, exact=True),
        verdict=prompt_audit.APPROVED,
        reason="Reviewed these exact words",
        run_id=str(uuid4()), correlation_id=str(uuid4()),
    )
    assert prompt_audit.purchase_approval_gaps(engine, board, step, [1]) == []

    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
        )
        row.prompt_json = {**row.prompt_json, field: row.prompt_json[field] + " Changed."}
    assert prompt_audit.purchase_approval_gaps(engine, board, step, [1]) == [1]


def test_unknown_or_unplanned_scene_is_not_treated_as_approved(engine, tmp_path, studio):
    board = a_planned_film(engine, tmp_path)
    assert prompt_audit.purchase_approval_gaps(engine, board, "motion", [1, 99]) == [1, 99]
