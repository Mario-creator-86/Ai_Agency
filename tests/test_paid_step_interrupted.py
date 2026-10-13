"""A paid step that fails after it has paid is never bought again by a retry (REL-01).

Measured on fakes before 2026-10-02: a media stage whose step paid Runway and then met
SQLite's "database is locked" was classified TRANSIENT and run again by the runbook's stage
retry, four times: four purchases, and none of them in the books, because the step booked its
spend only when it returned.

Now the shooting sheet's step books what it had committed the moment it fails (the balance
drop when the account could be read again, else the credits it counted), writes one Romanian
letter to the Owner, and raises `SpentStageError`, which the runbook classifies HARD: no
retry in place and no second attempt of the day.

Every provider is faked; no socket is opened (conftest refuses them).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.models import AgentMessage
from app.economy.models import ProviderCostRecord
from app.media.assembler import SpentStageError
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent
from app.runbook.services import HARD, _run_with_retries, classify_fault
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def costs(engine) -> list[ProviderCostRecord]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
        session.expunge_all()
        return rows


def letters(engine, kind: str) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = [
            row
            for row in session.scalars(select(AgentMessage))
            if isinstance(row.body_json, dict) and row.body_json.get("kind") == kind
        ]
        session.expunge_all()
        return rows


def asked_and_answered(engine, storyboard_id: str, context: dict[str, Any]) -> str:
    """The Owner is asked about the hero test shot and says yes; the sheet's hash."""
    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    with pytest.raises(SheetStepRefused) as asked:
        run_sheet_step(
            engine, storyboard_id, "test_shot", plan_hash, correlation_id="ask", **context
        )
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    return plan_hash


def test_a_step_that_fails_after_paying_is_booked_once_hard_and_never_retried(
    engine, settings, tmp_path, monkeypatch
):
    from app.media import assembler

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    video = SpyVideo("seedance2_5", account)
    models = Models(video)
    context = {
        "capabilities": [SEEDANCE],
        "account": account,
        "adapter_for_model": models,
        "storage_root": tmp_path / "media",
        "environment": "TEST",
    }
    plan_hash = asked_and_answered(engine, storyboard_id, context)

    # The take that says the clip was paid for meets a busy database, once, after Runway has
    # charged for the shot: the outbox dispatcher writes every second.
    original = assembler.record_take
    met: list[str] = []

    def busy_once(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("status") == "PAID" and not met:
            met.append("locked")
            raise OperationalError("INSERT INTO domain_event", {}, Exception("database is locked"))
        return original(*args, **kwargs)

    monkeypatch.setattr(assembler, "record_take", busy_once)
    settings.stage_retry_attempts = 3
    settings.stage_retry_backoff_seconds = 0
    waits: list[float] = []

    def media_stage() -> dict[str, Any]:
        return run_sheet_step(
            engine, storyboard_id, "test_shot", plan_hash, correlation_id="day-1", **context
        )

    outcome, error, attempts = _run_with_retries(
        engine, settings, "run-1", "media", media_stage, waits.append, "day-1"
    )

    assert outcome is None and isinstance(error, SpentStageError)
    assert attempts == 1 and waits == [], "a stage that had paid was run again"
    assert classify_fault(error) == HARD
    assert models.posts() == 1, "the shot was bought again"
    (cost,) = costs(engine)
    assert cost.provider == "runway" and cost.status == "ESTIMATED"
    assert cost.attribution_json["credits"] == pytest.approx(340)
    assert cost.attribution_json["interrupted"] is True
    assert cost.usd_micros == 3_400_000
    assert "day-1" in cost.external_reference
    (letter,) = letters(engine, "paid_step_interrupted")
    with Session(engine) as session:
        text = session.get(AgentMessage, letter.id).body_text or ""
    assert "credite" in text and "nu se cumpără din nou" in text, text
    with Session(engine) as session:
        warned = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.paid_step_interrupted")
        ).all()
    assert len(warned) == 1 and warned[0].payload["severity"] == "WARNING"


def test_a_step_that_fails_before_any_purchase_stays_transient(engine, settings, tmp_path):
    """Nothing was sent to the vendor: the stage may be tried again, as before."""
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    context = {
        "capabilities": [SEEDANCE],
        "account": account,
        "adapter_for_model": models,
        "storage_root": tmp_path / "media",
        "environment": "TEST",
    }
    plan_hash = asked_and_answered(engine, storyboard_id, context)

    def locked_models(model_id: str) -> Any:
        raise OperationalError("SELECT", {}, Exception("database is locked"))

    with pytest.raises(OperationalError) as raised:
        run_sheet_step(
            engine,
            storyboard_id,
            "test_shot",
            plan_hash,
            correlation_id="day-2",
            **{**context, "adapter_for_model": locked_models},
        )
    assert not isinstance(raised.value, SpentStageError)
    assert classify_fault(raised.value) != HARD
    assert models.posts() == 0 and costs(engine) == []
