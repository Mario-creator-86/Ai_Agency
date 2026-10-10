"""A RunPod /run refused whole books nothing, from the batch up to the sheet and the day.

2026-10-09 17:24 UTC (live): the motion step's /run met «Endpoint is paused (max_workers=0)»
for longer than the studio waited. RunPod queued nothing and its rows cost 0, yet the 409 went
up raw: the meter kept the round, the sheet booked it as an interrupted purchase (an ESTIMATED
cost that ate the daily budget and the film's ceiling), wrote the Owner «Pasul … s-a oprit după
ce a plătit», and in the daily run the same path would have opened safe mode. Now the batch
raises such a refusal as an unsent `BatchRefused` in RunPod's words, and every layer above
turns it into a refusal that books nothing and lets the step's hold go.

Every RunPod, bucket and GPU call is faked; nothing reaches a vendor.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import AgentMessage
from app.economy.models import ProviderCostRecord, SpendReservation
from app.media import assembler
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import (  # noqa: F401 - clock, fake_session: fixtures
    Cloud,
    adapter,
    clock,
    fake_session,
    motion_table,
    paused,
    runpod_capability,
    stills_table,
)


@pytest.fixture
def gpu(fake_session, clock):  # noqa: F811 - test_runpod_batch's fixtures
    """The GPU session faked and recorded (test_runpod_batch), the paused wait on a fake
    clock: RunPod's «paused» answers run out the wait in no time."""
    return fake_session


def paused_cloud() -> Cloud:
    """RunPod's queue still answering «paused» long after the switch-on."""
    cloud = Cloud()
    cloud.run_answers = [paused() for _ in range(40)]
    return cloud


def nothing_booked(engine) -> None:
    """No purchase in the books, no «a plătit» letter or event, no hold kept."""
    from app.media.shooting_sheet import INTERRUPTED_EVENT

    with Session(engine) as s:
        assert s.scalars(select(ProviderCostRecord)).all() == []
        assert (
            s.scalars(select(DomainEvent).where(DomainEvent.event_type == INTERRUPTED_EVENT)).all()
            == []
        )
        subjects = [m.subject for m in s.scalars(select(AgentMessage))]
        assert not [subject for subject in subjects if "după ce a plătit" in str(subject)]
        held = s.scalars(select(SpendReservation).where(SpendReservation.status != "RELEASED"))
        assert held.all() == []


def mode_studio(engine) -> None:
    from test_shooting_sheet import mode_studio as studio

    studio(engine)  # AUTONOMOUS_CEO, paid media MODE: his press buys without a question


# ------------------------------------------------------------------------------ the sheet


def test_a_stills_press_runpod_never_queued_books_nothing(engine, tmp_path, gpu):
    from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
    from test_film_costing import SEEDANCE
    from test_stills_stage import a_film

    storyboard_id = a_film(engine, tmp_path)
    mode_studio(engine)
    cloud = paused_cloud()
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=30)
    table = stills_table()
    sheet = build_sheet(
        engine,
        storyboard_id,
        capabilities=[SEEDANCE],
        table=table,
        account=made,
        stills_model=made.model,
        read_live=False,
    )
    with pytest.raises(SheetStepRefused) as refused:
        run_sheet_step(
            engine,
            storyboard_id,
            "stills",
            sheet["sheet_hash"],
            correlation_id=str(uuid4()),
            capabilities=[SEEDANCE],
            table=table,
            account=made,
            image_adapter=made,
            storage_root=tmp_path / "media",
        )
    assert refused.value.status == "RUNPOD_PAUSED"
    assert "nu s-a cumpărat nimic" in refused.value.reason_ro
    assert "Endpoint is paused" in refused.value.reason_ro
    assert len(gpu) == 1 and gpu[0]["closed"]
    nothing_booked(engine)


def test_a_motion_press_runpod_never_queued_books_nothing(engine, tmp_path, gpu):
    from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
    from app.providers.runpod.adapters import RunPodVideoAdapter
    from test_film_costing import a_film
    from test_runpod_batch import serverless

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    mode_studio(engine)
    cloud = paused_cloud()
    made = RunPodVideoAdapter(
        serverless(paused_wait_seconds=30), engine, model="LTX-2.5", storage_root=tmp_path
    )
    made.core.transport = made.core.client.transport = cloud
    capability = runpod_capability()
    table = motion_table()
    models: Any = lambda model: made if model == "LTX-2.5" else None  # noqa: E731
    sheet = build_sheet(
        engine, storyboard_id, capabilities=[capability], table=table, read_live=False
    )
    with pytest.raises(SheetStepRefused) as refused:
        run_sheet_step(
            engine,
            storyboard_id,
            "test_shot",
            sheet["sheet_hash"],
            correlation_id=str(uuid4()),
            capabilities=[capability],
            table=table,
            adapter_for_model=models,
            storage_root=tmp_path / "media",
        )
    assert refused.value.status == "RUNPOD_PAUSED"
    assert len(cloud.posts()) > 1  # asked again while RunPod's queue caught up, then refused
    nothing_booked(engine)
    with Session(engine) as s:
        holds = s.scalars(
            select(DomainEvent).where(DomainEvent.event_type == assembler.MOTION_HOLD_EVENT)
        ).all()
        assert holds == []


def test_a_motion_press_that_bought_on_runway_first_books_it_when_runpod_refuses(
    engine, tmp_path, gpu
):
    """Review 2026-10-10: the motion step buys a scene set on a per-second model (Runway) in its
    own loop, on the step's meter, before the scenes it defers to RunPod. A RunPod round refused
    whole then went up as an unsent refusal: the sheet let the hold go and booked nothing, so
    the 340 Runway credits really spent left his daily budget and the film's ceiling, and his
    letter said nothing was bought. The step now ends on what it bought, booked."""
    from app.media.models import SceneTake
    from app.media.shooting_sheet import build_sheet, run_sheet_step, set_scene_model
    from app.providers.runpod.adapters import RunPodVideoAdapter
    from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film, hero_approved
    from test_runpod_batch import serverless

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    mode_studio(engine)
    table = motion_table()
    capabilities = [SEEDANCE, runpod_capability(selected_default=False)]
    set_scene_model(engine, storyboard_id, 2, "seedance2_5", issued_by="owner", table=table)
    set_scene_model(engine, storyboard_id, 3, "LTX-2.5", issued_by="owner", table=table)
    cloud = paused_cloud()
    made = RunPodVideoAdapter(
        serverless(paused_wait_seconds=30), engine, model="LTX-2.5", storage_root=tmp_path
    )
    made.core.transport = made.core.client.transport = cloud
    runway = SpyVideo("seedance2_5", account)
    models: Any = lambda model: {"LTX-2.5": made, "seedance2_5": runway}.get(model)  # noqa: E731
    sheet = build_sheet(
        engine,
        storyboard_id,
        capabilities=capabilities,
        table=table,
        account=account,
        read_live=False,
    )
    with Session(engine) as s:
        held_before = {r.id for r in s.scalars(select(SpendReservation))}
        booked_before = len(s.scalars(select(ProviderCostRecord)).all())
    shots_before = account.shots

    result = run_sheet_step(
        engine,
        storyboard_id,
        "motion",
        sheet["sheet_hash"],
        correlation_id=str(uuid4()),
        capabilities=capabilities,
        table=table,
        account=account,
        adapter_for_model=models,
        storage_root=tmp_path / "media",
    )

    assert account.shots - shots_before == 1 and len(cloud.posts()) > 1
    scenes = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert scenes[2]["status"] == "PAID" and scenes[3]["status"] == "NOT_BOUGHT"
    with Session(engine) as s:
        (paid,) = s.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.kind == "motion",
                SceneTake.status == "PAID",
            )
        ).all()
        spent = float(result["spent_credits_quoted"])
        assert spent == pytest.approx(float(paid.credits_quoted)) and spent > 0
        assert len(s.scalars(select(ProviderCostRecord)).all()) == booked_before + 1
        (hold,) = [r for r in s.scalars(select(SpendReservation)) if r.id not in held_before]
        assert hold.status != "RELEASED"
    # What RunPod refused is said in its own words, never as «nothing was bought».
    assert "nu s-a cumpărat nimic" not in str(result["stopped"])
    assert "ce s-a cumpărat înainte rămâne" in str(result["stopped"])
    assert result["gpu"]["refusal"]["code"] == "RUNPOD_PAUSED"


def test_a_still_redo_runpod_never_queued_books_nothing(engine, tmp_path, gpu):
    from app.media.assembler import SceneRedoRefused
    from test_approvals import answer
    from test_runpod_unsent_proof import redo_go
    from test_stills_stage import a_film

    storyboard_id = a_film(engine, tmp_path)
    cloud = paused_cloud()
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=30)
    with pytest.raises(SceneRedoRefused) as asked:
        redo_go(engine, made, storyboard_id, tmp_path)
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    with pytest.raises(SceneRedoRefused) as refused:
        redo_go(engine, made, storyboard_id, tmp_path)
    assert refused.value.status == "RUNPOD_PAUSED"
    assert "nu s-a cumpărat nimic" in refused.value.reason_ro
    nothing_booked(engine)
    with Session(engine) as s:
        holds = s.scalars(
            select(DomainEvent).where(DomainEvent.event_type == assembler.STILL_HOLD_EVENT)
        ).all()
        assert holds == []


# -------------------------------------------------------------------------- the daily run


def test_the_day_meets_a_paused_runpod_as_a_held_film_never_a_failure(
    engine, settings, tmp_path, monkeypatch, gpu
):
    """In the daily run the same refusal was a SpentStageError (HARD): media is a safe-mode
    stage, so the unattended studio would have stopped itself over a purchase that never
    happened. Now the stair is refused before spending: the film is HELD, nothing raised."""
    from app.media import shooting_sheet
    from app.runbook import stages
    from test_daily_run_stages import (
        _bottom_of_the_staircase,
        _paid_media_mode,
        _production,
        _staircase_world,
    )

    _production(engine)
    _paid_media_mode(engine)
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path)
    world = _staircase_world(engine, tmp_path, monkeypatch)
    cloud = paused_cloud()
    made = adapter(engine, tmp_path, cloud, paused_wait_seconds=30)
    monkeypatch.setattr(
        stages,
        "sheet_wiring",
        lambda engine_, vault, settings_: {
            "integration_id": None,
            "capabilities": [runpod_capability()],
            "image_adapter": made,
            "account": made,
            "adapter_for_model": world["models"],
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
    )
    monkeypatch.setattr(shooting_sheet, "price_table_for", lambda *args, **kwargs: stills_table())

    skipped: list[dict[str, Any]] = []
    day = stages._media_staircase(
        engine, settings, None, None, [storyboard_id], [], set(), "PRODUCTION", skipped=skipped
    )

    assert len(cloud.posts()) > 1, day
    (film,) = [f for f in day["artefacts"]["films"] if f["storyboard_id"] == storyboard_id]
    assert film["status"] == "HELD" and film["refusal"] == "RUNPOD_PAUSED", film
    (passed_over,) = [s for s in skipped if s["storyboard_id"] == storyboard_id]
    assert "nu s-a cumpărat nimic" in passed_over["reason"]
    nothing_booked(engine)
