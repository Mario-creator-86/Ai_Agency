"""His yes for a corrected paid redo is spent on the resume, not asked again (2026-10-13).

Under the Owner's ask-me rule a paid REPAIR of a scene is corrected first (`_correct_before_redo`:
her brief, his rewrite, her review, the new words stored) and then asked, his yes bound to the
corrected plan. Read on the source on 2026-10-13: the walk that resumed after his yes corrected
the scene AGAIN before spending it — the same words came back and the redo was refused
PROMPT_NOT_CORRECTED, or new words made a new plan and he was asked again — so the redo he
approved was never bought. Now the words corrected for this film and not bought yet are the
words his yes was asked on (`stages._corrected_for_film`): the resume neither looks nor
corrects again, and the clip is bought on them.

Offline: `_apply_repairs` twice on one motion redo, faked vendor, scripted agents."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.models import MediaAsset, SceneTake, VideoRenderJob
from app.media.prompt_agent import motion_prompt_for
from app.media.scene_rewrite import BRIEF_EVENT
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, OwnerPolicy
from app.runbook import stages
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_clip_qc_wiring import events
from test_director_rewrites_failed_scene import (  # noqa: F401 - the studio fixture
    SHOT,
    Agents,
    a_planned_film,
    agents_say,
    scene,
    studio,
)
from test_film_costing import SEEDANCE, Account, Models, SpyVideo

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

#: What the editor would write if asked again on the resume: other words, another plan.
SHOT_V3 = {
    **SHOT,
    "motion": "a shaft of sunlight sweeps across the terraces as the cloud breaks",
    "camera_move": "slow push-in",
    "ending_frame": "the village lit by a passing shaft of light",
}


def _rewrites(engine, storyboard_id: str) -> list:
    return [
        e
        for e in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if e.payload.get("decided_by") == "director"
    ]


def _walk(engine, settings, registry, storyboard_id: str, reading: dict) -> dict:
    result: dict = {
        "applied": [],
        "bought": [],
        "asked": [],
        "refused": [],
        "limited": [],
        "made": [],
        "new_asset": None,
        "waiting": [],
        "skipped": [],
        "replaced_his": [],
        "overturned": [],
        "requalified": None,
        "requalified_report_id": None,
        "card_id": None,
    }
    stages._apply_repairs(engine, settings, None, registry, reading, result, False, str(uuid4()))
    return result


def _failed_film(engine, tmp_path, storyboard_id: str) -> str:
    """The failed film's render record: scene 1's clip made from its approved still, so the
    still is not newer than the film (`_still_newer_than_film` False, as in a real film)."""
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        still = session.scalar(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "still"
            )
        )
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(tmp_path / f"{asset_id}.mp4"),
                file_size_bytes=1024,
                mime_type="video/mp4",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="a" * 64,
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                production_json={
                    "scenes": [
                        {"scene_index": 1, "still_take": {"take_id": still.id}, "motion": None}
                    ]
                },
                started_at=utc_now(),
                finished_at=utc_now(),
            )
        )
    return asset_id


@pytest.mark.parametrize("second_shot", ["same", "different"])
def test_his_yes_on_a_corrected_motion_redo_is_spent_on_the_resume(
    engine,
    settings,
    tmp_path,
    studio,  # noqa: F811 - the fixture imported from test_director_rewrites_failed_scene
    monkeypatch,
    second_shot,
):
    storyboard_id = a_planned_film(engine, tmp_path, still_by="owner")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).paid_media_approval = "EVERY_PAID_STEP"
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    monkeypatch.setattr(
        stages,
        "sheet_wiring",
        lambda engine_, vault, settings_: {
            "integration_id": None,
            "capabilities": [SEEDANCE],
            "image_adapter": None,
            "account": account,
            "adapter_for_model": models,
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
    )
    asset_id = _failed_film(engine, tmp_path, storyboard_id)
    reading = {
        "storyboard_id": storyboard_id,
        "media_asset_id": asset_id,
        "report_id": str(uuid4()),
        "proposals": [
            SimpleNamespace(
                scene_index=1, redo="motion", reason="the clip barely moved", free=False
            )
        ],
        "findings": [{"scene_index": 1, "text": "Scena 1: clipul aproape nu se mișcă"}],
        "verdicts": [],
    }

    # Walk 1: her brief, his rewrite, her review; the redo is asked on the corrected words.
    first = _walk(engine, settings, agents_say(studio, Agents()), storyboard_id, reading)

    assert first["bought"] == [] and len(first["asked"]) == 1, first
    assert len(_rewrites(engine, storyboard_id)) == 1
    corrected = dict(scene(engine, storyboard_id).prompt_json)
    approval_id = first["asked"][0]["approval_id"]
    with Session(engine) as session:
        hash_asked = session.get(ApprovalRequest, approval_id).proposed_diff["plan_hash"]
    assert spy.asked == []

    # His yes; the walk resumes — with an editor who would say the same words, or others.
    answer(engine, approval_id, "APPROVED", note="Da, reface mișcarea scenei 1.")
    agents = Agents() if second_shot == "same" else Agents(shot=SHOT_V3)
    second = _walk(engine, settings, agents_say(studio, agents), storyboard_id, reading)

    assert second["asked"] == [] and second["refused"] == [], second
    assert [entry["scene_index"] for entry in second["bought"]] == [1], second
    assert len(_rewrites(engine, storyboard_id)) == 1, "nothing was rewritten again"
    assert len(events(engine, BRIEF_EVENT, storyboard_id)) == 1, "she was not asked again"
    assert dict(scene(engine, storyboard_id).prompt_json) == corrected
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at)))
        assert [row.proposed_diff.get("plan_hash") for row in rows] == [hash_asked]
        assert session.get(ApprovalRequest, approval_id).consumed_at is not None
    # The clip was bought once, on the corrected words.
    expected, _negative = motion_prompt_for(corrected, "seedance2_5", None)
    (asked,) = spy.asked
    assert asked["prompt"] == expected and "from left to right" in asked["prompt"]
