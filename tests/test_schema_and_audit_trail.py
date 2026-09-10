"""Two structural claims the studio makes about itself, checked rather than assumed.

**The schema the migrations build is the schema the models declare.** Drift between them is
silent until something reads a column that is not there, usually in production and usually at the
worst moment. Alembic can answer the question directly, so it is asked on every run.

**A change to audited state leaves an event behind.** The history is append-only and it is the
only account of why the studio's state is what it is. Two writes were found without one: an
exchange rate, which decides how a foreign payout converts and therefore how much VR$ is minted,
and a scheduled job, which decides that a workflow will run again and again without being asked.
Both now append and link their event, and these tests hold them to it.
"""

from __future__ import annotations

from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.economy.models import FXSnapshot
from app.economy.services import record_fx_snapshot, seed_chart_of_accounts
from app.models import Base, DomainEvent
from app.workflows.models import ScheduledJob
from app.workflows.schemas import CreateScheduledJobCommand
from app.workflows.services import create_scheduled_job
from sqlalchemy import select
from sqlalchemy.orm import Session


def test_the_migrations_build_exactly_what_the_models_declare(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        difference = compare_metadata(context, Base.metadata)
    assert difference == [], f"schema drift between migrations and models: {difference}"


def _event_for(session, event_type: str, aggregate_id: str) -> DomainEvent:
    return session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == event_type,
            DomainEvent.aggregate_id == aggregate_id,
        )
    ).one()


def test_an_exchange_rate_arrives_with_an_event_that_explains_it(engine):
    seed_chart_of_accounts(engine)

    snapshot = record_fx_snapshot(
        engine,
        base_currency="eur",
        quote_currency="usd",
        rate="1.08",
        source="ECB reference rate",
        observed_at="2026-09-11T09:00:00+00:00",
    )

    with Session(engine) as session:
        row = session.get(FXSnapshot, snapshot["id"])
        event = _event_for(session, "economy.fx_snapshot_recorded", snapshot["id"])
        # The row points at the event, so an auditor reading the books can reach the reason.
        assert row.event_id == event.event_id
        assert event.payload["pair"] == "EUR/USD"
        assert event.payload["rate"] == "1.08"
        assert event.payload["source"] == "ECB reference rate"


def test_scheduling_a_recurring_workflow_is_recorded_as_a_decision(engine):
    job = create_scheduled_job(
        engine,
        CreateScheduledJobCommand(
            command_id=uuid4(),
            name=f"job-{uuid4().hex[:8]}",
            workflow_type="RESEARCH",
            interval_seconds=3600,
            missed_policy="SKIP",
        ),
    )

    with Session(engine) as session:
        row = session.get(ScheduledJob, job["id"])
        event = _event_for(session, "workflow.job_scheduled", job["id"])
        assert row.event_id == event.event_id
        assert event.payload["workflow_type"] == "RESEARCH"
        assert event.payload["interval_seconds"] == 3600
