"""The Accountant reads her books with what she needs to answer from them.

2026-10-11: asked about «167 rulări fără preț», she asked the Director for the model list and
a rate card. The runs were from 10-03..05, before the Owner's Ollama price of 10-05 13:46 —
a run's cost is computed once, when the model answers — and the price had been active for
six days; her figures held only the count. Asked what a film cost against what it returned,
she wrote that the cost could not be attributed, while the film's RunPod rows sat in the
books under its board. What is asserted here: the month's unpriced usage is given per model,
with its tokens apart from the month's totals and whether a price active now covers it, and
each published film carries its cost, estimated, reconciled and billed, beside its views,
with the attempts rejected before it apart; the per-model reading stays out of the money
gate every run passes. Read only: nothing here writes a cost or a price (the price below is
the Owner's, set as he sets it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import app.economy.prices as prices
import pytest
from app.agents.models import Agent, AgentRun, ProviderRecord
from app.agents.services import seed_initial_workforce
from app.analytics.models import AnalyticsSnapshot
from app.economy.accountant import AGENT_COST_PER_FILM_RO, daily_figures
from app.economy.budget import budget_status
from app.economy.models import ProviderCostRecord
from app.economy.prices import PriceCommand, set_price
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import seed_default_channels
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def books(engine):
    seed_initial_workforce(engine)
    seed_default_channels(engine)
    with Session(engine) as session:
        agent_id = session.scalar(select(Agent.id))
        channel_id = session.scalar(select(ChannelRecord.id))
    return {"agent_id": agent_id, "channel_id": channel_id}


def a_run(engine, agent_id, *, provider, model, at, prompt, completion, cost=None):
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=agent_id,
                task_type="answer_mail",
                objective="o scrisoare",
                prompt_template_version="mail-v1",
                model_name=model,
                provider_name=provider,
                status="SUCCEEDED",
                output_text="Gata.",
                cost_vr=cost,
                prompt_tokens=prompt,
                completion_tokens=completion,
                correlation_id=str(uuid4()),
                started_at=at,
                finished_at=at,
                context_json={},
            )
        )


def the_owners_ollama_price(engine):
    for unit in ("per_1m_input_tokens", "per_1m_output_tokens"):
        set_price(
            engine,
            PriceCommand(
                command_id=uuid4(),
                provider_kind="ollama",
                resource="*",
                unit=unit,
                usd="0.5",
            ),
        )


def a_paid_connection(engine, kind):
    """A connection saved in Settings, as its provider record names it."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "provider.registered", "provider_record", identifier, 1, {}, str(uuid4())
        )
        session.add(
            ProviderRecord(
                id=identifier,
                name=f"settings:{identifier}",
                provider_type=kind,
                base_url="",
                status="UNKNOWN",
                adapter_version="1.0.0",
                notes="",
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return f"settings:{identifier}"


def test_the_months_unpriced_runs_are_given_per_model_with_the_price_that_covers_them(
    engine, books
):
    agent_id = books["agent_id"]
    # Before the Owner's price: the kimi and mistral runs of 10-03..05, never re-priced.
    for at, prompt, completion in (
        ("2026-10-03T06:15:12+00:00", 1000, 100),
        ("2026-10-04T09:00:00+00:00", 2000, 200),
        ("2026-10-05T13:44:34+00:00", 3000, 300),
    ):
        a_run(
            engine,
            agent_id,
            provider="local-ollama",
            model="kimi-k3",
            at=at,
            prompt=prompt,
            completion=completion,
        )
    a_run(
        engine,
        agent_id,
        provider="local-ollama",
        model="mistral-large-3:675b",
        at="2026-10-04T10:00:00+00:00",
        prompt=4000,
        completion=400,
    )
    # A model on a kind the Owner never priced: his, not the studio's, to price.
    openai = a_paid_connection(engine, "openai")
    a_run(
        engine,
        agent_id,
        provider=openai,
        model="gpt-5-mini",
        at="2026-10-06T10:00:00+00:00",
        prompt=500,
        completion=50,
    )
    # After the price: priced at call time, counted in the totals, not among the unpriced.
    the_owners_ollama_price(engine)
    a_run(
        engine,
        agent_id,
        provider="local-ollama",
        model="kimi-k3",
        at="2026-10-08T10:00:00+00:00",
        prompt=10000,
        completion=1000,
        cost="0.0055",
    )

    month = daily_figures(engine, NOW)["month"]

    assert month["unpriced_agent_runs"] == 5
    # The month's totals count every run; the unpriced tokens are given apart.
    assert month["prompt_tokens"] == 20500 and month["completion_tokens"] == 2050
    assert month["unpriced_prompt_tokens"] == 10500
    assert month["unpriced_completion_tokens"] == 1050
    groups = {g["model"]: g for g in month["unpriced_by_model"]}
    kimi = groups["kimi-k3"]
    assert (kimi["provider_kind"], kimi["runs"]) == ("ollama", 3)
    assert (kimi["prompt_tokens"], kimi["completion_tokens"]) == (6000, 600)
    assert kimi["first_run_at"] == "2026-10-03T06:15:12+00:00"
    assert kimi["last_run_at"] == "2026-10-05T13:44:34+00:00"
    # Covered by an active price: yes — 6600 tokens at 0.50 USD per million each side.
    assert kimi["covered_by_active_price"] is True and kimi["at_active_price_usd"] == "0.0033"
    assert groups["mistral-large-3:675b"]["covered_by_active_price"] is True
    gpt = groups["gpt-5-mini"]
    assert gpt["provider_kind"] == "openai" and gpt["covered_by_active_price"] is False
    assert gpt["at_active_price_usd"] is None
    # Nothing was written: the runs are as unpriced as they were.
    with Session(engine) as session:
        assert (
            session.scalar(
                select(AgentRun).where(AgentRun.cost_vr.is_(None), AgentRun.model_name == "kimi-k3")
            )
            is not None
        )


def test_a_month_with_every_run_priced_says_so_in_few_words(engine, books):
    a_run(
        engine,
        books["agent_id"],
        provider="local-ollama",
        model="kimi-k3",
        at="2026-10-08T10:00:00+00:00",
        prompt=100,
        completion=10,
        cost="0.000055",
    )
    month = daily_figures(engine, NOW)["month"]
    assert month["unpriced_agent_runs"] == 0 and month["unpriced_by_model"] == []
    assert month["unpriced_prompt_tokens"] == 0 and month["prompt_tokens"] == 100


# ------------------------------------------------------------------ what a film cost


def a_board(engine, topic_id, title, status="RENDERED"):
    script_id, board_id = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=30,
                voiceover_full_text="Cuvinte.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=utc_now(),
            )
        )
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title=title,
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=30,
                status=status,
                total_scenes=0,
                created_at=utc_now(),
            )
        )
    return board_id


def a_topic(engine):
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, str(uuid4())
        )
        session.add(
            TopicIdea(
                id=topic_id,
                title="Bosonul Higgs",
                topic="physics",
                angle="Cum a fost prins",
                target_audience="general",
                novelty_score=0.7,
                status="PRODUCED",
                scores_json={},
                source_plan_json=[],
                thesis_json={},
                rejection_reasons_json=[],
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return topic_id


def a_cost(engine, provider, status, usd, attribution, *, reconciled=False):
    with Session(engine) as session, session.begin():
        session.add(
            ProviderCostRecord(
                id=str(uuid4()),
                provider=provider,
                external_reference=f"test:{uuid4()}",
                status=status,
                amount_micros=int(usd * 1_000_000),
                currency="USD",
                usd_micros=int(usd * 1_000_000),
                attribution_json=attribution,
                recorded_at="2026-10-10T08:00:00+00:00",
                # As `reconcile_provider_invoice` leaves an estimate its invoice replaced.
                reconciled_at="2026-10-11T09:00:00+00:00" if reconciled else None,
                reconciled_by_id=str(uuid4()) if reconciled else None,
            )
        )


def a_published_film(engine, channel_id, board_id, *, views, title="The Higgs Boson"):
    asset_id, job_id, publication_id = str(uuid4()), str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"/media/{asset_id}.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="a" * 64,
                created_at=utc_now(),
            )
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=board_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json={},
                started_at=utc_now(),
            )
        )
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title=title,
                description="",
                tags_json=[],
                privacy_status="public",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=f"yt-{publication_id[:8]}",
                published_at="2026-10-10T09:00:00+00:00",
                created_at=utc_now(),
            )
        )
        event = append_event(
            session,
            "analytics.snapshot_ingested",
            "analytics_snapshot",
            str(uuid4()),
            1,
            {},
            str(uuid4()),
        )
        session.add(
            AnalyticsSnapshot(
                id=str(uuid4()),
                publication_id=publication_id,
                channel_id=channel_id,
                window="LIFETIME",
                views=views,
                watch_time_seconds=views * 20.0,
                average_view_percentage=60.0,
                impressions=views * 10,
                ctr_percentage=4.0,
                likes=1,
                comments=0,
                shares=0,
                subscribers_gained=0,
                subscribers_lost=0,
                raw_metrics_json={},
                snapshot_at="2026-10-11T08:00:00+00:00",
                event_id=event.event_id,
            )
        )
    return publication_id, job_id


def test_a_published_film_carries_its_cost_estimated_and_billed_beside_its_views(engine, books):
    topic_id = a_topic(engine)
    rejected = a_board(engine, topic_id, "Bosonul Higgs, prima variantă", status="REJECTED")
    board = a_board(engine, topic_id, "Bosonul Higgs")
    publication_id, job_id = a_published_film(engine, books["channel_id"], board, views=1200)
    # The shots, booked under the board; one already invoiced; the narration under the render.
    a_cost(engine, "runpod", "ESTIMATED", 2.5, {"storyboard_id": board, "step": "motion"})
    a_cost(engine, "runpod", "BILLED", 0.5, {"storyboard_id": board, "step": "stills"})
    a_cost(engine, "elevenlabs", "ESTIMATED", 0.05, {"render_job_id": job_id})
    # The attempt rejected before it, same topic, paid for all the same.
    a_cost(engine, "runway", "ESTIMATED", 1.62, {"storyboard_id": rejected})
    # Someone else's film is not this one's.
    a_cost(engine, "runpod", "ESTIMATED", 9.0, {"storyboard_id": str(uuid4())})

    films = daily_figures(engine, NOW)["films"]

    assert films["agent_cost"] == AGENT_COST_PER_FILM_RO
    [film] = films["published"]
    assert film["publication_id"] == publication_id and film["storyboard_id"] == board
    assert film["cost_usd"] == "3.05"
    assert (film["estimated_usd"], film["billed_usd"], film["held_usd"]) == ("2.55", "0.5", "0")
    assert film["reconciled_usd"] == "0"
    assert film["rejected_boards_same_topic_usd"] == "1.62"
    assert film["views"] == 1200 and film["views_measured_at"] == "2026-10-11T08:00:00+00:00"


def test_an_estimate_the_owner_reconciled_is_not_shown_as_unbilled(engine, books):
    """The invoice's BILLED row covers a provider and a period, not a film: after the Owner
    reconciles it, the film's estimate is reconciled, not «ESTIMATED» with nothing billed."""
    board = a_board(engine, a_topic(engine), "Bosonul Higgs")
    _, job_id = a_published_film(engine, books["channel_id"], board, views=1200)
    a_cost(engine, "runpod", "ESTIMATED", 2.5, {"storyboard_id": board}, reconciled=True)
    a_cost(engine, "runpod", "BILLED", 2.7, {"reconciliation_id": str(uuid4())})
    a_cost(engine, "elevenlabs", "ESTIMATED", 0.05, {"render_job_id": job_id})

    [film] = daily_figures(engine, NOW)["films"]["published"]

    assert film["cost_usd"] == "2.55"
    assert (film["estimated_usd"], film["reconciled_usd"]) == ("0.05", "2.5")
    assert (film["billed_usd"], film["held_usd"]) == ("0", "0")


def test_only_the_attempts_rejected_before_a_film_are_counted_as_its_attempts(engine, books):
    topic_id = a_topic(engine)
    rejected = a_board(engine, topic_id, "Bosonul Higgs, prima variantă", status="REJECTED")
    board = a_board(engine, topic_id, "Bosonul Higgs")
    a_published_film(engine, books["channel_id"], board, views=1200)
    # Another film published on the same topic, and a remake still in work after it.
    other = a_board(engine, topic_id, "Bosonul Higgs, partea a doua")
    a_published_film(engine, books["channel_id"], other, views=300, title="Higgs, part two")
    remake = a_board(engine, topic_id, "Bosonul Higgs, refăcut", status="APPROVED")
    a_cost(engine, "runway", "ESTIMATED", 1.62, {"storyboard_id": rejected})
    a_cost(engine, "runpod", "ESTIMATED", 3.0, {"storyboard_id": other})
    a_cost(engine, "runpod", "ESTIMATED", 0.7, {"storyboard_id": remake})

    films = {f["storyboard_id"]: f for f in daily_figures(engine, NOW)["films"]["published"]}

    assert films[board]["rejected_boards_same_topic_usd"] == "1.62"
    # The second film's attempts are those after the first: none. The first film's board is
    # not an attempt of the second, and the remake in work is nobody's yet.
    assert films[other]["rejected_boards_same_topic_usd"] == "0"


def test_the_money_gate_reads_no_price_per_model(engine, books, monkeypatch):
    """`spend_since` is the sum every agent run's budget check reads: the per-model reading
    is the Accountant's, and a fault in it never reaches the gate."""
    a_run(
        engine,
        books["agent_id"],
        provider="local-ollama",
        model="kimi-k3",
        at="2026-10-04T09:00:00+00:00",
        prompt=2000,
        completion=200,
    )
    the_owners_ollama_price(engine)

    def unreadable(*args, **kwargs):
        raise RuntimeError("the price table is being rewritten")

    monkeypatch.setattr(prices, "price_row", unreadable)

    status = budget_status(engine, NOW)

    assert status["month"]["unpriced_agent_runs"] == 1
    assert "unpriced_by_model" not in status["month"]
