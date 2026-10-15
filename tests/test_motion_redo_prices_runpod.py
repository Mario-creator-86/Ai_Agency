"""A motion plan with no table of its own prices the RunPod profile as the sheet does (2026-10-12).

Live, film aa170155 (the cyclotron), from 2026-10-11 20:17 UTC: the Director's QC decided a
REPAIR of scenes 4 and 5, her brief rewrote the motion, and the paid redo (`_paid_redo` →
`run_motion_step` → `_motion_state`) priced the scene with the raw published table — no row for
the Owner's RunPod profile (LTX-2.5, an estimate laid over the tariff by `price_table_for`) —
and held the scene NEEDS_OWNER: «Profilul RunPod selectat nu poate filma această scenă: nu are
preț publicat la 1080p». The sheet's own motion step had priced the same model the same day.
The hourly `director_qc_review` pass re-asked her, the walk said «s-a cumpărat (1 refacere
cumpărată)» over a redo that bought nothing, five times through the night. Every provider is
faked (RunPod's offline mock); nothing is bought.
"""

from __future__ import annotations

import json

from app.media.assembler import _motion_state, motion_plan
from app.media.cost_plan import load_price_table
from app.media.shooting_sheet import connection_capabilities
from test_film_costing import a_film
from test_runpod_pipeline import connect

PROFILE = "LTX-2.5"


def profile_delivers_the_frame(engine, identity: str) -> None:
    """The offline mock's LTX-2.5 names no frame; the Owner's real profile delivers 1080×1920
    (the studio's frame), and so does the one these tests price."""
    from app.integrations.models import ProviderResource
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == identity, ProviderResource.remote_id == PROFILE
            )
        )
        row.api_metadata = {**(row.api_metadata or {}), "ratios": ["1080:1920", "720:1280"]}


def scenes_of(plan: dict) -> list[dict]:
    return [s for s in plan["scenes"] if str(s.get("scene_kind") or "LIVE").upper() == "LIVE"]


def test_a_motion_plan_without_a_table_prices_the_runpod_profile(engine, tmp_path, monkeypatch):
    _vault, identity = connect(engine, tmp_path, monkeypatch)
    profile_delivers_the_frame(engine, identity)
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    capabilities = connection_capabilities(engine, identity)
    assert any(c.model_id == PROFILE and c.selected_default for c in capabilities)

    plan = motion_plan(engine, storyboard_id, capabilities=capabilities)

    filmed = scenes_of(plan)
    assert filmed, plan
    for scene in filmed:
        assert scene.get("model_id") == PROFILE, json.dumps(scene, ensure_ascii=False)
        assert scene.get("status") != "NEEDS_OWNER", scene
        assert "nu are preț publicat" not in str(scene.get("reason_ro") or ""), scene


def test_the_raw_published_table_alone_could_not_price_it(engine, tmp_path, monkeypatch):
    """What the redo did before: the tariff knows no RunPod profile, so every scene was held."""
    _vault, identity = connect(engine, tmp_path, monkeypatch)
    profile_delivers_the_frame(engine, identity)
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    capabilities = connection_capabilities(engine, identity)

    raw = _motion_state(engine, storyboard_id, capabilities=capabilities, table=load_price_table())
    held = scenes_of(raw["plan"])
    assert held and all(s.get("status") == "NEEDS_OWNER" for s in held), held
    for scene in held:
        assert "nu are preț publicat" in str(scene.get("reason_ro") or ""), json.dumps(
            scene, ensure_ascii=False
        )

    # The same scenes, the same capabilities, no table given: priced as the sheet prices.
    fixed = _motion_state(engine, storyboard_id, capabilities=capabilities)
    assert all(s.get("model_id") == PROFILE for s in scenes_of(fixed["plan"])), fixed["plan"]


def test_motion_lint_uses_the_accepted_stills_actual_model_limit(engine, tmp_path, monkeypatch):
    from app.media import assembler
    from app.media.models import SceneTake, StoryboardScene
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    _vault, identity = connect(engine, tmp_path, monkeypatch)
    profile_delivers_the_frame(engine, identity)
    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == board))
        words = "A calm mountain landscape under warm light. " * 40
        row.visual_prompt = words
        row.prompt_json = {**(row.prompt_json or {}), "still_prompt": words}
        take = session.scalar(
            select(SceneTake).where(SceneTake.storyboard_id == board, SceneTake.kind == "still")
        )
        take.model_id = "Qwen-Image-2512"
        take.prompt_hash = assembler.take_hash(
            assembler.scene_still_fields(engine, {"visual_prompt": words, "character_ids": []}),
            take.model_id,
        )
    state = _motion_state(engine, board, capabilities=connection_capabilities(engine, identity))
    assert not any(f.code == "OVER_CAP" and f.field == "still_prompt" for f in state["findings"])
