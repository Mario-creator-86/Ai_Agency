"""Shooting-sheet failures become executable, continuing work, never conversational success."""

from uuid import uuid4

import pytest
from app.agents.models import AgentMessage
from app.agents.services import seed_initial_workforce
from app.media import blocker_repair as repair
from app.media.models import Storyboard, StoryboardScene
from app.media.shooting_sheet import build_sheet
from app.models import OwnerPolicy
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_shooting_sheet import nepal_film


@pytest.fixture
def film(engine, tmp_path, monkeypatch):
    from app.factual import story_review

    # This module isolates prompt/queue behavior; prerequisites have their own tests.
    monkeypatch.setattr(repair, "repair_story", lambda *a, **kw: None)
    monkeypatch.setattr(story_review, "story_gate", lambda *a: (True, ""))
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
    return nepal_film(engine, tmp_path)


def sheet(engine, identifier):
    reading = build_sheet(engine, identifier, read_live=False)
    reading["story_review"] = {"passed": True}
    return reading


def task(engine):
    with Session(engine) as session:
        return session.scalar(
            select(TaskQueueItem).where(TaskQueueItem.task_type == repair.REPAIR_TASK)
        )


def test_every_prompt_block_and_missing_scene_is_in_the_directors_evidence(engine, film):
    with Session(engine) as session, session.begin():
        scene = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == film))
        scene.prompt_json = {**scene.prompt_json, "source": "template"}
    reading = sheet(engine, film)
    issues = repair.sheet_issues(reading)
    assert len(
        [i for i in issues if i["kind"] == "PROMPT" and i["code"] != "NEEDS_SHOT_PLAN"]
    ) == len(reading["blocks"])
    assert any(i["code"] == "NEEDS_SHOT_PLAN" and i["scene_index"] == 1 for i in issues)
    assert all(i["detail"] for i in issues)


def test_identical_polling_creates_one_director_report_and_one_durable_task(engine, film):
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    again = repair.submit_sheet_issues(engine, reading)
    assert first["task_id"] == again["task_id"]
    with Session(engine) as session:
        reports = list(
            session.scalars(
                select(AgentMessage).where(AgentMessage.subject.like("Blocaje foaie:%"))
            )
        )
        tasks = list(
            session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == repair.REPAIR_TASK)
            )
        )
        assert len(reports) == len(tasks) == 1
        assert reports[0].to_agent_id
        assert reports[0].body_json["issues"] == repair.sheet_issues(reading)


def test_director_assigns_real_prompt_work_and_result_is_rechecked(engine, film, monkeypatch):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    order = []
    monkeypatch.setattr(
        repair,
        "director_assignment",
        lambda *a, **kw: order.append("Director") or {"note": "Rescrie cadrele.", "run_id": None},
    )

    def rewrite(engine, registry, identifier, correlation, **kwargs):
        order.append("VideoEditor")
        assert kwargs["repair_context"]["issues"]
        with Session(engine) as session, session.begin():
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == identifier)
            ):
                row.prompt_json = {
                    **(row.prompt_json or {}),
                    "source": "model",
                    "still_prompt": "A distant landscape in soft blue daylight.",
                    "motion_prompt": [
                        "One slow push-in.",
                        "One slow pull-back.",
                        "One tilt up.",
                        "One slow pan left.",
                        "Static camera.",
                        "Static camera.",
                    ][row.scene_index - 1],
                }
                row.visual_prompt = row.prompt_json["still_prompt"]
            session.get(Storyboard, identifier).visual_bible_json = {}
        return {"run_id": None}

    monkeypatch.setattr(repair, "write_shot_prompts", rewrite)
    result = repair.process_sheet_repair(engine, object(), queued.payload, correlation_id=queued.id)
    assert order == ["Director", "VideoEditor"]
    assert result["status"] == "RESOLVED"
    assert result["remaining"] == []
    with Session(engine) as session:
        handoffs = [
            m
            for m in session.scalars(select(AgentMessage))
            if m.body_json.get("kind") == repair.WORK_KIND
        ]
        assert len(handoffs) == 1 and handoffs[0].from_agent_id and handoffs[0].to_agent_id
        assert handoffs[0].status == "RESOLVED"


def test_employee_saying_done_without_changing_prompts_does_not_resolve_the_report(
    engine, film, monkeypatch
):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    monkeypatch.setattr(
        repair, "director_assignment", lambda *a, **kw: {"note": "Rescrie.", "run_id": None}
    )
    monkeypatch.setattr(repair, "write_shot_prompts", lambda *a, **kw: {"run_id": None})
    result = repair.process_sheet_repair(engine, object(), queued.payload, correlation_id=queued.id)
    assert result["status"] == "UNRESOLVED"
    assert result["remaining"]
    with Session(engine) as session:
        assert session.get(AgentMessage, queued.payload["message_id"]).status == "OPEN"


def test_balance_block_is_escalated_and_never_funded_or_bought(engine, film, monkeypatch):
    reading = sheet(engine, film)
    reading["blocks"] = []
    reading["lint"] = []
    reading["shot_plan_gaps"] = []
    reading["footer"]["balance"] = {"read": True, "credits": 370, "problem": None}
    reading["footer"]["balance_needed_credits"] = {"stills": 373}
    reading["steps"] = {"stills": {"to_buy": [1], "cap_credits": 324}}
    monkeypatch.setattr(repair, "build_sheet", lambda *a, **kw: reading)
    repair.submit_sheet_issues(engine, reading)
    queued = task(engine)
    monkeypatch.setattr(
        repair,
        "director_assignment",
        lambda *a, **kw: {"note": "Este nevoie de sold.", "run_id": None},
    )
    monkeypatch.setattr(
        repair,
        "write_shot_prompts",
        lambda *a, **kw: pytest.fail("must not rewrite for a financial blocker"),
    )
    result = repair.process_sheet_repair(engine, object(), queued.payload, correlation_id=queued.id)
    assert result["status"] == "WAITING_OWNER"
    with Session(engine) as session:
        assert any(
            m.body_json.get("owner_attention") for m in session.scalars(select(AgentMessage))
        )
        # His letter names the film by its title, not by eight characters of its id.
        title = session.get(Storyboard, film).title
        (letter,) = [
            m
            for m in session.scalars(select(AgentMessage))
            if m.body_json.get("kind") == "sheet_repair_owner"
        ]
        assert letter.subject == f"Foaia necesită intervenție: {title}"
        assert film[:8] not in letter.subject


@pytest.mark.parametrize("stop,mode", [(True, "AUTONOMOUS_CEO"), (False, "MANUAL")])
def test_scan_and_processing_obey_the_owners_stop_and_manual_mode(
    engine, film, monkeypatch, stop, mode
):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped, policy.autonomy_mode = stop, mode
    monkeypatch.setattr(
        repair, "director_assignment", lambda *a, **kw: pytest.fail("policy must stop model calls")
    )
    assert repair.process_sheet_repair(engine, object(), queued.payload)["status"] == "BLOCKED"


def test_a_changed_sheet_is_not_rewritten_from_stale_instructions(engine, film, monkeypatch):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == film))
        row.visual_prompt = "An Owner correction to this shot."
        row.prompt_json = {**row.prompt_json, "still_prompt": row.visual_prompt}
    monkeypatch.setattr(repair, "director_assignment", lambda *a, **kw: pytest.fail("stale report"))
    assert repair.process_sheet_repair(engine, object(), queued.payload)["status"] == "STALE"


def test_repairs_continue_beyond_two_attempts_without_asking_the_owner(engine, film):
    """Up to the day's ceiling on the same blockers (`MAX_SAME_ISSUES_PER_DAY`, each attempt
    after its back-off), the repair goes on by itself; nothing asks the Owner."""
    from datetime import UTC, datetime, timedelta

    reading = sheet(engine, film)
    rounds = repair.MAX_SAME_ISSUES_PER_DAY
    for n in range(rounds):
        reading = {**reading, "sheet_hash": str(uuid4())}
        dispatched = repair.submit_sheet_issues(engine, reading)
        assert dispatched.get("task_id"), (n, dispatched)
        with Session(engine) as session, session.begin():
            task_row = session.get(TaskQueueItem, dispatched["task_id"])
            task_row.status = "COMPLETED"
            # Its back-off passed: the attempt is dated back within the day.
            task_row.created_at = (datetime.now(UTC) - timedelta(minutes=600 - n)).isoformat()
            report = session.get(AgentMessage, dispatched["message_id"])
            report.body_json = {**report.body_json, "repair_result": {"status": "UNRESOLVED"}}
    with Session(engine) as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(TaskQueueItem).where(TaskQueueItem.task_type == repair.REPAIR_TASK)
                    )
                )
            )
            == rounds
        )
        assert not any(
            m.body_json.get("owner_attention") for m in session.scalars(select(AgentMessage))
        )


def test_the_scan_includes_legacy_rendered_films_with_bad_sheets(engine, film, monkeypatch):
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film).status = "RENDERED"
    monkeypatch.setattr(
        repair, "build_sheet", lambda engine, identifier, **kw: sheet(engine, identifier)
    )
    result = repair.scan_sheet_issues(engine)
    assert film in result["reported"]


def test_an_unsuccessful_completed_repair_is_retried_once_instead_of_deduplicated_forever(
    engine, film
):
    reading = sheet(engine, film)
    first = repair.submit_sheet_issues(engine, reading)
    with Session(engine) as session, session.begin():
        queued = session.get(TaskQueueItem, first["task_id"])
        queued.status = "COMPLETED"
        report = session.get(AgentMessage, first["message_id"])
        report.body_json = {**report.body_json, "repair_result": {"status": "UNRESOLVED"}}
    retry = repair.submit_sheet_issues(engine, reading)
    assert retry["task_id"] != first["task_id"]
    assert repair.submit_sheet_issues(engine, reading)["task_id"] == retry["task_id"]


def test_catalogue_errors_from_the_footer_reach_the_director(engine, film):
    reading = sheet(engine, film)
    reading["footer"]["catalogue_problem_ro"] = "Catalogue unusable"
    assert any(i["code"] == "CATALOGUE_INVALID" for i in repair.sheet_issues(reading))


def test_processing_uses_the_same_provider_and_camera_configuration_as_the_scan(
    engine, film, monkeypatch
):
    reading = sheet(engine, film)
    repair.submit_sheet_issues(engine, reading)
    queued = task(engine)
    contexts = []

    def read(*args, **kwargs):
        contexts.append(kwargs)
        return reading

    monkeypatch.setattr(repair, "build_sheet", read)
    monkeypatch.setattr(
        repair, "director_assignment", lambda *a, **kw: {"note": "Work", "repair_prompts": False}
    )
    repair.process_sheet_repair(
        engine,
        object(),
        queued.payload,
        sheet_context={"integration_id": "saved", "resolution": "720p"},
    )
    assert all(c["integration_id"] == "saved" and c["resolution"] == "720p" for c in contexts)


def test_director_and_editor_use_real_agent_kernel_and_real_prompt_compiler(engine, film):
    import json

    from app.agents.models import Agent, AgentRun, ModelRecord
    from app.factual.story_review import story_gate
    from app.media.services import seed_default_character_bibles
    from app.publishing.services import seed_default_channels
    from test_editorial_quality import BIBLE_ANSWER, registry_with
    from test_shot_plan_parse import _nepal_board, _valid_pack

    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    film = _nepal_board(engine)
    with Session(engine) as session, session.begin():
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
        board = session.get(Storyboard, film)
        assert story_gate(session, board.script_draft_id)[0]
        provider = session.scalar(select(Agent.provider_id))

    calls = []

    def answer(prompt):
        if '"repair_prompts":true|false' in prompt:
            calls.append("Director")
            return json.dumps(
                {
                    "note": (
                        "Correct every listed shot using natural words, hidden faces "
                        "and varied camera moves."
                    ),
                    "repair_prompts": True,
                    "assign_to_role": "VideoEditor",
                }
            )
        if '"shots": [' in prompt:
            calls.append("VideoEditor")
            assert "repair_context" in prompt and "issues" in prompt
            return json.dumps(_valid_pack())
        return json.dumps(BIBLE_ANSWER)

    registry, _ = registry_with({"provider_id": provider}, answer)
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    result = repair.process_sheet_repair(engine, registry, queued.payload, correlation_id=queued.id)
    assert calls == ["Director", "VideoEditor"]
    assert not any(i["kind"] == "PROMPT" for i in result["remaining"]), result
    with Session(engine) as session:
        runs = list(session.scalars(select(AgentRun)))
        assert len(runs) == 3 and all(r.status == "SUCCEEDED" for r in runs)
        assert all(
            s.prompt_json["source"] == "model"
            for s in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == film)
            )
        )


def test_duplicate_delivery_returns_the_verified_result_without_relabeling_it_stale(
    engine, film, monkeypatch
):
    queued = repair.submit_sheet_issues(engine, sheet(engine, film))
    saved = {"status": "RESOLVED", "remaining": [], "reason": "verified"}
    with Session(engine) as session, session.begin():
        report = session.get(AgentMessage, queued["message_id"])
        report.body_json = {**report.body_json, "repair_result": saved}
        payload = dict(session.get(TaskQueueItem, queued["task_id"]).payload)
    monkeypatch.setattr(
        repair, "build_sheet", lambda *a, **kw: pytest.fail("completed delivery must be inert")
    )
    assert repair.process_sheet_repair(engine, object(), payload) == saved


def test_a_current_purchase_lease_prevents_the_editor_from_rewriting(engine, film, monkeypatch):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    monkeypatch.setattr(
        repair, "director_assignment", lambda *a, **kw: {"note": "Correct", "repair_prompts": True}
    )
    monkeypatch.setattr(
        repair, "write_shot_prompts", lambda *a, **kw: pytest.fail("purchase in progress")
    )
    with repair.film_purchase_lease(engine, film, holder="other", step="stills"):
        result = repair.process_sheet_repair(engine, object(), queued.payload)
    assert result["status"] == "UNRESOLVED"


def test_failed_prompt_repairs_stay_with_the_director_and_never_ask_the_owner(
    engine, film, monkeypatch
):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    calls = []
    monkeypatch.setattr(
        repair,
        "director_assignment",
        lambda *a, **kw: {"note": "Correct the shots", "repair_prompts": True},
    )
    monkeypatch.setattr(
        repair,
        "write_shot_prompts",
        lambda *a, **kw: calls.append(kw["repair_context"]["exchange"]),
    )
    result = repair.process_sheet_repair(engine, object(), queued.payload)
    assert result["status"] == "UNRESOLVED"
    assert calls == [1]  # next worker scan continues; no attempt ceiling
    with Session(engine) as session:
        assert not any(
            m.body_json.get("owner_attention") for m in session.scalars(select(AgentMessage))
        )


def test_the_daily_prompt_refusal_is_sent_to_the_director_not_the_owner(engine, film):
    from app.runbook.stages import _sheet_letter

    reading = sheet(engine, film)
    report = _sheet_letter(
        engine,
        film,
        {"sheet": reading, "status": "HELD", "refusal": "LINT_BLOCKED", "step": "stills"},
        None,
        str(uuid4()),
    )
    with Session(engine) as session:
        message = session.get(AgentMessage, report)
        assert message.to_agent_id and not message.body_json.get("owner_attention")
