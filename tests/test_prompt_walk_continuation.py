"""A bounded prompt-repair walk yields durable work rather than an Owner decision."""

import pytest
from app.media import factory, fix_check, prompt_audit, shooting_sheet
from app.models import OwnerPolicy
from app.runbook import stages
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def setup_walk(engine, tmp_path, monkeypatch, *, progress=True):
    board = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    state = {"version": 0, "bought": False, "approved": False, "audits": 0, "purchases": []}
    boundary = len(shooting_sheet.SHEET_STEPS) + 1
    monkeypatch.setattr(factory, "reference_image_adapter", lambda *a: None)
    monkeypatch.setattr(fix_check, "restore_sent_back_scenes", lambda *a, **kw: [])
    monkeypatch.setattr(shooting_sheet, "recover_paid_takes", lambda *a, **kw: {})
    monkeypatch.setattr(stages, "stop_requested", lambda *a: False)

    def sheet(*args, **kwargs):
        return {
            "sheet_hash": f"reviewed-words-{state['version'] if progress else 0}",
            "steps": {
                "stills": {"to_buy": [], "held": [], "needs_reference": []},
                "test_shot": {"to_buy": [], "held": []},
                "motion": {"to_buy": [] if state["bought"] else [1], "held": []},
                "assemble": {"blocked": []},
            },
        }

    def audit(*args, **kwargs):
        state["audits"] += 1
        if state["version"] < boundary:
            state["version"] += 1
            return {"rewritten": [1], "approved": [], "held": [], "skipped": [], "asked": True}
        state["approved"] = True
        return {"rewritten": [], "approved": [1], "held": [], "skipped": [], "asked": True}

    def purchase(*args, **kwargs):
        assert state["approved"], "No purchase without a fresh Director approval"
        assert args[3] == f"reviewed-words-{state['version']}"
        state["purchases"].append(args[2])
        state["bought"] = True
        return {}

    monkeypatch.setattr(shooting_sheet, "build_sheet", sheet)
    monkeypatch.setattr(prompt_audit, "audit_before_purchase", audit)
    monkeypatch.setattr(shooting_sheet, "run_sheet_step", purchase)
    return board, state


def walk(engine, settings, board, correlation="first-walk", environment="PRODUCTION"):
    return stages._walk_staircase(engine, settings, object(), board, {}, environment, correlation)


def test_last_valid_rewrite_queues_a_fresh_walk_and_purchases_only_after_reaudit(
    engine, settings, tmp_path, monkeypatch
):
    board, state = setup_walk(engine, tmp_path, monkeypatch)
    first = walk(engine, settings, board)
    assert first["status"] == "WAITING"
    assert first["refusal"] == prompt_audit.NEEDS_PROMPT_APPROVAL
    assert state["purchases"] == []
    with Session(engine) as session:
        task = session.scalar(
            select(TaskQueueItem).where(TaskQueueItem.task_type == "FILM_CONTINUE")
        )
        assert task is not None and task.status == "QUEUED"
        assert task.payload["storyboard_id"] == board
        assert task.id == first["continues"]
        next_correlation = task.id
    assert stages._sheet_letter(engine, board, first, None, "test") is None
    second = walk(engine, settings, board, correlation=next_correlation)
    assert second["status"] == "READY"
    assert state["purchases"] == ["motion"]


def test_a_rewrite_that_leaves_the_same_sheet_does_not_turn_or_queue_forever(
    engine, settings, tmp_path, monkeypatch
):
    board, state = setup_walk(engine, tmp_path, monkeypatch, progress=False)
    result = walk(engine, settings, board)
    assert result["refusal"] == prompt_audit.NEEDS_PROMPT_APPROVAL
    assert result["no_prompt_progress"] is True
    assert state["audits"] == 1
    assert not state["purchases"]
    with Session(engine) as session:
        assert session.scalar(select(TaskQueueItem.id)) is None


def test_replayed_handoff_deduplicates_its_durable_continuation(
    engine, settings, tmp_path, monkeypatch
):
    board, state = setup_walk(engine, tmp_path, monkeypatch)
    first = walk(engine, settings, board)
    state["version"] = 0
    second = walk(engine, settings, board)
    assert first["continues"] == second["continues"]
    with Session(engine) as session:
        assert len(list(session.scalars(select(TaskQueueItem)))) == 1


@pytest.mark.parametrize("environment", ["TEST", "DEMO"])
def test_nonproduction_walk_does_not_queue_a_production_continuation(
    engine, settings, tmp_path, monkeypatch, environment
):
    board, state = setup_walk(engine, tmp_path, monkeypatch)
    result = walk(engine, settings, board, environment=environment)
    assert result["refusal"] == prompt_audit.NEEDS_PROMPT_APPROVAL
    assert result.get("continues") is None
    with Session(engine) as session:
        assert session.scalar(select(TaskQueueItem.id)) is None


def test_stop_after_last_rewrite_prevents_new_continuation(engine, settings, tmp_path, monkeypatch):
    board, state = setup_walk(engine, tmp_path, monkeypatch)
    boundary = len(shooting_sheet.SHEET_STEPS) + 1
    monkeypatch.setattr(stages, "stop_requested", lambda *a: state["audits"] >= boundary)
    result = walk(engine, settings, board)
    assert result["refusal"] == "STOPPED"
    assert not state["purchases"]
    with Session(engine) as session:
        assert session.scalar(select(TaskQueueItem.id)) is None


@pytest.mark.parametrize(
    "refusal", ["OVER_DAILY_BUDGET", "OVER_FILM_BUDGET", "NEEDS_APPROVAL", "BLOCKED_MODE"]
)
def test_resumed_walk_keeps_payment_budget_and_mode_refusals(
    engine, settings, tmp_path, monkeypatch, refusal
):
    board, state = setup_walk(engine, tmp_path, monkeypatch)
    state["version"] = len(shooting_sheet.SHEET_STEPS) + 1

    def refused_payment(*args, **kwargs):
        assert state["approved"]
        raise shooting_sheet.SheetStepRefused(refusal, "Standing payment gate")

    monkeypatch.setattr(shooting_sheet, "run_sheet_step", refused_payment)
    result = walk(engine, settings, board)
    assert result["refusal"] == refusal
    assert not state["purchases"]
    with Session(engine) as session:
        assert session.scalar(select(TaskQueueItem.id)) is None
