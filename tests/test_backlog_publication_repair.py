"""Existing approved films precede new production; rewrite limits follow the real route."""

from types import SimpleNamespace

import pytest
from app.media import scene_rewrite
from app.media.models import Storyboard, StoryboardScene
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def approved_film(engine, tmp_path):
    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board).status = "APPROVED"
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == board))
        row.prompt_json = {
            **(row.prompt_json or {}),
            "subject": "A distant telescope",
            "action": "A steady field",
        }
    return board


def test_rewrite_context_carries_the_selected_runpod_model_allowance(engine, tmp_path, monkeypatch):
    from app.media import production_policy, prompt_lint
    from runpod_worker.contract import MAX_PROMPT

    board = approved_film(engine, tmp_path)
    monkeypatch.setattr(
        production_policy,
        "resolve_storyboard_plan",
        lambda *a: {
            "purposes": {"image": {"model_id": "Qwen-Image-2512"}},
            "scenes": [{"scene_index": 1, "video": {"model_id": "LTX-2.5"}}],
        },
    )
    ctx = scene_rewrite.scene_context(engine, board, 1)
    assert ctx is not None
    assert ctx["contract"]["model_id"] == "LTX-2.5"
    assert prompt_lint.prompt_cap(ctx["contract"], "motion") == MAX_PROMPT


def test_backlog_defers_new_stages_but_leaves_repair_and_publication_running(
    engine, tmp_path, settings, monkeypatch
):
    from app.runbook import stages

    board = approved_film(engine, tmp_path)

    def forbidden(*a, **kw):
        raise AssertionError("New production must wait for existing films")

    monkeypatch.setattr(stages, "mode_refusal", lambda *a, **kw: None)
    monkeypatch.setattr(stages, "_idea_generation", forbidden)
    monkeypatch.setattr(stages, "_serial_next", forbidden)
    monkeypatch.setattr(stages, "_media", lambda *a: {"status": "COMPLETED", "reason": "repair"})
    monkeypatch.setattr(
        stages, "_publish", lambda *a, **kw: {"status": "COMPLETED", "reason": "publish"}
    )
    monkeypatch.setattr(stages, "publication_footer", lambda *a: "")
    runners = stages.build_stage_runners(engine, settings, None, object())
    for stage in ["idea_generation", "serial_next"]:
        outcome = runners[stage]()
        assert outcome["status"] == "SKIPPED"
        assert board in outcome["artefacts"]["unfinished_storyboards"]
    assert runners["media"]()["reason"] == "repair"
    assert runners["publish"]()["reason"] == "publish"


def test_serial_direct_entry_waits_before_calling_a_model(engine, tmp_path, settings):
    from app.story.serial_stage import run_serial_next_stage

    board = approved_film(engine, tmp_path)

    class ForbiddenRegistry:
        def registered_ids(self):
            raise AssertionError("No model call or selection before backlog check")

    result = run_serial_next_stage(engine, ForbiddenRegistry(), settings)
    assert result["status"] == "SKIPPED"
    assert board in result["artefacts"]["unfinished_storyboards"]


def test_closed_film_releases_the_backlog_gate(engine, tmp_path):
    from app.media.backlog import new_production_wait

    board = approved_film(engine, tmp_path)
    assert new_production_wait(engine, SimpleNamespace()) is not None
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board).status = "REJECTED"
    assert new_production_wait(engine, SimpleNamespace()) is None


def test_config_can_explicitly_disable_backlog_admission(engine, tmp_path):
    from app.media.backlog import new_production_wait

    approved_film(engine, tmp_path)
    assert new_production_wait(engine, SimpleNamespace(finish_existing_films_first=False)) is None


@pytest.mark.parametrize("serial", [False, True])
def test_runpod_rewrite_lint_accepts_supported_length_without_truncation(serial):
    motion = "The camera moves slowly across the cool star field. " * 24
    ctx = {
        "scene_index": 1,
        "serial": serial,
        "look": {"max_prompt_chars": 20000},
        "contract": {"model_id": "LTX-2.5", "still_model_id": "Qwen-Image-2512"},
        "package": {
            "prompt_format": "editor_final_v1",
            "still_prompt": "A cool star field.",
            "motion_prompt": "A steady star field.",
        },
        "visual_prompt": "A cool star field.",
        "bible": {},
    }
    candidate = {**ctx["package"], "motion_prompt": motion}
    blocks = scene_rewrite._lint_blocks(ctx, candidate, ctx["visual_prompt"], layer="motion")
    assert not any("limita" in b for b in blocks)
    assert candidate["motion_prompt"] == motion
    ctx["contract"] = {"model_id": "unknown-vendor"}
    blocks = scene_rewrite._lint_blocks(ctx, candidate, ctx["visual_prompt"], layer="motion")
    assert any("limita de 1000" in b for b in blocks)


def test_older_film_precedes_newer_film_even_if_recovery_queued_it_later(engine, tmp_path):
    from app.models import OwnerPolicy
    from app.workflows.services import claim_task, enqueue_task

    old = approved_film(engine, tmp_path)
    new = approved_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.get(Storyboard, old).created_at = "2026-10-17T00:00:00+00:00"
        session.get(Storyboard, new).created_at = "2026-10-19T00:00:00+00:00"
    enqueue_task(engine, "FILM_CONTINUE", {"storyboard_id": new}, priority=4)
    enqueue_task(engine, "FILM_CONTINUE", {"storyboard_id": old}, priority=4)
    assert claim_task(engine, "test")["payload"]["storyboard_id"] == old


def test_newer_sheet_repair_cannot_overtake_old_film_continuation(engine, tmp_path):
    from app.models import OwnerPolicy
    from app.workflows.services import claim_task, enqueue_task

    old = approved_film(engine, tmp_path)
    new = approved_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.get(Storyboard, old).created_at = "2026-10-17T00:00:00+00:00"
        session.get(Storyboard, new).created_at = "2026-10-19T00:00:00+00:00"
    enqueue_task(engine, "FILM_SHEET_REPAIR", {"storyboard_id": new}, priority=6)
    enqueue_task(engine, "FILM_CONTINUE", {"storyboard_id": old}, priority=4)
    assert claim_task(engine, "test")["payload"]["storyboard_id"] == old


def test_same_film_repair_and_urgent_nonfilm_priority_are_preserved(engine, tmp_path):
    from app.models import OwnerPolicy
    from app.workflows.services import claim_task, enqueue_task

    board = approved_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    enqueue_task(engine, "FILM_CONTINUE", {"storyboard_id": board}, priority=4)
    enqueue_task(engine, "FILM_SHEET_REPAIR", {"storyboard_id": board}, priority=6)
    enqueue_task(engine, "URGENT_OWNER_WORK", {}, priority=9)
    assert claim_task(engine, "test")["task_type"] == "URGENT_OWNER_WORK"
    assert claim_task(engine, "test")["task_type"] == "FILM_SHEET_REPAIR"
    assert claim_task(engine, "test")["task_type"] == "FILM_CONTINUE"


def test_automatic_preclaim_scan_recovers_existing_films_before_selecting_newer_work(
    engine, settings, monkeypatch
):
    from app.workflows.worker import build_task_handlers

    seen = []
    monkeypatch.setattr("app.media.blocker_repair.allowed", lambda *a: True)
    monkeypatch.setattr(
        "app.media.blocker_repair.scan_sheet_issues", lambda *a, **kw: {"reported": []}
    )
    monkeypatch.setattr(
        "app.workflows.passes.owner_choice_continuation.queue_missed_continuations",
        lambda ctx: seen.append("factual"),
    )
    monkeypatch.setattr(
        "app.workflows.passes.serial_unfilmed.finish_approved_episodes",
        lambda ctx: seen.append("serial"),
    )
    monkeypatch.setattr(
        "app.runbook.stages.sheet_wiring",
        lambda *a: {
            "capabilities": [],
            "integration_id": None,
            "image_adapter": None,
            "account": None,
            "resolution": None,
        },
    )
    handlers = build_task_handlers(engine, settings, None, stage_runners={}, registry=object())
    handlers["SCAN_FILM_SHEETS"]({"payload": {}})
    assert seen == ["factual", "serial"]
