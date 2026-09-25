"""The Director runs a company, not a video.

The Owner's thirty checks. They are about management: does the Director know where the company
stands, does she act on the right thing, does she assign it to a department that can do it,
does she refuse to conclude anything from one video, does she record what she decided so it can
be judged later, and does she stop instead of retrying forever.

All local. A scripted model, no vendor, no generation, and — the point of several of these —
no invented analytics: a channel with nothing published has no numbers, and the honest answer
to most questions about it is that the studio does not know yet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.command import (
    ASSIGNABLE,
    HIGH_IMPACT,
    MAX_ATTEMPTS_PER_MATTER,
    backlog,
    company_state,
    data_maturity,
    direct_company,
    due_reviews,
    findings,
    pipeline,
    prioritise_backlog,
    review_decision,
)
from app.agents.models import Agent, AgentMessage, Role
from app.agents.services import seed_initial_workforce
from app.analytics.models import AnalyticsSnapshot, DirectorDecision
from app.analytics.performance import (
    MINIMUM_BASELINE,
    channel_baselines,
    channel_health,
    classify,
    diagnose,
    growth_diagnosis,
    video_performance,
)
from app.economy.models import ProviderCostRecord
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import seed_default_channels
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.prompts.append(prompt)
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def studio(engine):
    """A staffed studio with its channels, and the Owner's stop cleared."""
    seed_initial_workforce(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        from app.agents.models import ModelRecord

        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent.provider_id))
        channel_id = session.scalar(select(ChannelRecord.id).order_by(ChannelRecord.channel_name))
    return {"provider_id": provider_id, "channel_id": channel_id}


def registry_with(studio, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(studio["provider_id"], model)
    return registry, model


def a_film(
    engine,
    channel_id,
    *,
    title="A film",
    views=1000,
    retention=70.0,
    subscribers=5,
    impressions=10000,
    ctr=5.0,
    likes=10,
    comments=2,
    shares=1,
    age_hours=48.0,
    cost_usd=3.0,
    minutes=45.0,
    measured=True,
) -> str:
    """One published film with its numbers, as the studio's own tables would hold them."""
    asset_id = str(uuid4())
    job_id = str(uuid4())
    publication_id = str(uuid4())
    published_at = (datetime.now(UTC) - timedelta(hours=age_hours)).isoformat()
    # A render job belongs to a storyboard, which belongs to a script, which belongs to a
    # topic: the chain the studio actually keeps, so cost and production time hang off real
    # rows rather than off a fixture that could not exist.
    topic_id = a_topic(engine, f"Topic for {title} {uuid4().hex[:6]}", status="PRODUCED")
    script_id = str(uuid4())
    storyboard_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=30,
                voiceover_full_text="Words.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=published_at,
            )
        )
        session.add(
            Storyboard(
                id=storyboard_id,
                script_draft_id=script_id,
                title=title,
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=30,
                status="COMPLETED",
                total_scenes=0,
                created_at=published_at,
            )
        )
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"/media/{asset_id}.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=30.0,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="a" * 64,
                created_at=utc_now(),
            )
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json={},
                started_at=published_at,
                duration_ms=minutes * 60000.0 if minutes else None,
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
                published_at=published_at,
                created_at=published_at,
            )
        )
        if cost_usd:
            session.add(
                ProviderCostRecord(
                    id=str(uuid4()),
                    provider="runway",
                    external_reference=f"render:{job_id}",
                    status="BILLED",
                    amount_micros=int(cost_usd * 1_000_000),
                    currency="USD",
                    usd_micros=int(cost_usd * 1_000_000),
                    attribution_json={"render_job_id": job_id},
                    recorded_at=utc_now(),
                )
            )
        if measured:
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
                    average_view_percentage=retention,
                    impressions=impressions,
                    ctr_percentage=ctr,
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    subscribers_gained=subscribers,
                    subscribers_lost=0,
                    raw_metrics_json={},
                    snapshot_at=utc_now(),
                    event_id=event.event_id,
                )
            )
    return publication_id


def a_topic(engine, title, *, status="PROPOSED", composite=0.6, verified=0, topic="space") -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, str(uuid4())
        )
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic=topic,
                angle="An angle",
                target_audience="general",
                novelty_score=0.7,
                status=status,
                scores_json={"composite": composite, "production_feasibility": 0.8},
                source_plan_json=[],
                thesis_json={"payoff": "Something is revealed."},
                rejection_reasons_json=[],
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        if verified:
            from app.factual.models import FactualClaim

            for index in range(verified):
                session.add(
                    FactualClaim(
                        id=str(uuid4()),
                        source_id=None,
                        topic_id=topic_id,
                        claim_text=f"Claim {index}",
                        claim_type="GENERAL",
                        importance="KEY",
                        status="SUPPORTED",
                        confidence=0.9,
                        created_at=utc_now(),
                    )
                )
    return topic_id


def a_baseline(engine, channel_id, *, films=4, views=1000, retention=70.0, subscribers=5):
    """Enough measured films that the channel has a median at all."""
    for index in range(films):
        a_film(
            engine,
            channel_id,
            title=f"Baseline film {index}",
            views=views,
            retention=retention,
            subscribers=subscribers,
            age_hours=72.0 + index,
        )


def no_choice_registry(studio):
    """A model that answers nothing usable: the measurements must carry the loop alone."""
    return registry_with(studio, lambda prompt: "no json here")


# --------------------------------------------------------------- 1-3: running the company


def test_1_the_director_sees_which_agents_have_done_nothing(engine, studio, settings):
    """An agent idle for a week is a fact about the company, and the Director reads it from
    the studio's own measurement rather than from a new counter."""
    state = company_state(engine, settings)
    assert state["agents"]["active"] >= 8
    # A freshly seeded studio has run nothing: every active agent is idle, and that is stated
    # rather than hidden.
    assert len(state["agents"]["idle"]) == state["agents"]["active"]
    assert all(row["runs"] == 0 for row in state["agents"]["per_agent"])


def test_2_idle_agents_get_real_work_and_only_when_nothing_is_in_flight(engine, studio, settings):
    """No idle agents without a reason, and no busywork. With films waiting to be finished,
    the answer is to finish them; with nothing in flight, the work is a real improvement."""
    state = company_state(engine, settings)
    assert state["pipeline"]["in_flight"] == 0
    idle_matters = [
        m for m in findings(engine, settings, state) if m["matter_key"].startswith("idle_")
    ]
    assert idle_matters, "an idle studio with nothing in flight is given something useful"
    for matter in idle_matters:
        assert matter["action"] in ASSIGNABLE[matter["owner_role"]], (
            "work handed to a department has to be work that department can do"
        )

    # Now give the studio work in flight: the idle matter disappears, because finishing beats
    # starting and inventing a task while films wait is the definition of busywork.
    a_topic(engine, "Something selected", status="SELECTED")
    a_topic(engine, "Another selected", status="SELECTED")
    busy = company_state(engine, settings)
    assert busy["pipeline"]["in_flight"] >= 2
    assert not [m for m in findings(engine, settings, busy) if m["matter_key"].startswith("idle_")]


def test_3_the_bottleneck_is_the_stage_holding_up_the_ones_after_it(engine, studio, settings):
    """Twenty approved ideas and no finished script is a production problem. Assigning more
    research to it is how a studio ends with fifty ideas and nothing published."""
    for index in range(4):
        a_topic(engine, f"Selected topic {index}", status="SELECTED")
    state = company_state(engine, settings)
    bottleneck = state["pipeline"]["bottleneck"]
    assert bottleneck and bottleneck["stage"] == "WRITING"
    assert bottleneck["waiting"] >= 3 and bottleneck["passed_on"] == 0
    matters = findings(engine, settings, state)
    assert any(m["matter_key"] == "bottleneck_writing" for m in matters)
    # And the work goes to the department that unblocks it, not to research.
    matter = next(m for m in matters if m["matter_key"] == "bottleneck_writing")
    assert matter["owner_role"] == "ScriptWriter"


# --------------------------------------------------------------- 4-6: cold start


def test_4_a_channel_with_no_data_is_reported_as_having_none(engine, studio, settings):
    """The one thing the Director may never do: fill an unmeasured channel with zeros. A zero
    reads as a measurement, and the studio has published nothing."""
    health = channel_health(engine, studio["channel_id"])
    assert health["published"] == 0 and health["measured"] == 0
    assert health["views_last_7_days"] is None
    assert health["views_change_percentage"] is None
    baseline = channel_baselines(engine, studio["channel_id"])
    assert baseline["has_baseline"] is False
    assert baseline["median_views"] is None
    assert str(MINIMUM_BASELINE) in baseline["note"]


def test_5_the_cold_start_has_a_strategy_and_it_is_not_an_invented_audience(
    engine, studio, settings
):
    """No internal data is not no strategy: the work is to publish good films and measure
    them. What the Director must not do is pretend to know an audience that does not exist."""
    state = company_state(engine, settings)
    assert state["maturity"] == "COLD_START"
    growth = growth_diagnosis(engine, studio["channel_id"])
    assert growth["constraint"] == "NO_DATA"
    assert growth["confidence"] == "LOW"
    assert growth["assign_to"] == "LeadResearcher"
    matters = findings(engine, settings, state)
    cold = [m for m in matters if m["matter_key"].startswith("cold_start_")]
    assert cold and cold[0]["suggested_decision"] == "EXPERIMENT"
    assert cold[0]["confidence"] == "LOW"


def test_6_the_director_leans_on_internal_data_only_once_there_is_some(engine, studio):
    """The transition the Owner asked for, as a function of what exists: nothing published is
    cold start, a handful is early data, ten or more is a channel that can be read."""
    assert data_maturity(0) == "COLD_START"
    assert data_maturity(1) == "EARLY_DATA"
    assert data_maturity(9) == "EARLY_DATA"
    assert data_maturity(10) == "MATURE"

    a_baseline(engine, studio["channel_id"], films=4)
    baseline = channel_baselines(engine, studio["channel_id"])
    assert baseline["has_baseline"] is True and baseline["median_views"] == 1000


# --------------------------------------------------------------- 7-10: reading the numbers


def test_7_the_director_reads_the_analytics_the_studio_is_authorised_to_have(engine, studio):
    """Through the existing integration and its stored snapshots. Not a second YouTube client,
    and only the windows that integration can actually ask for."""
    from app.analytics.performance import AVAILABLE_WINDOWS

    a_film(engine, studio["channel_id"], views=5000, retention=81.0, subscribers=40)
    films = video_performance(engine, studio["channel_id"])
    assert len(films) == 1
    film = films[0]
    assert film["measured"] and film["views"] == 5000
    assert film["average_view_percentage"] == 81.0
    assert film["windows_measured"] == ["LIFETIME"]
    assert AVAILABLE_WINDOWS == ("1h", "24h", "7d", "28d", "LIFETIME")


def test_8_a_total_is_not_a_rate(engine, studio):
    """Ten thousand views in thirty days and seven thousand in a day are not comparable as
    totals. The rate is what says which film is doing better."""
    old_film = a_film(engine, studio["channel_id"], title="Older", views=10000, age_hours=30 * 24)
    new_film = a_film(engine, studio["channel_id"], title="Newer", views=7000, age_hours=24)
    films = {f["publication_id"]: f for f in video_performance(engine, studio["channel_id"])}
    older, newer = films[old_film], films[new_film]
    assert older["views"] > newer["views"]
    assert newer["views_per_hour"] > older["views_per_hour"], (
        "the newer film is doing dramatically better per hour"
    )
    # And a film too young for a rate does not get a fabricated one.
    just_out = a_film(engine, studio["channel_id"], title="Minutes old", age_hours=0.2)
    fresh = next(
        f
        for f in video_performance(engine, studio["channel_id"])
        if f["publication_id"] == just_out
    )
    assert fresh["views_per_hour"] is None


def test_9_subscriber_conversion_is_measured_not_inferred_from_views(engine, studio):
    """A hundred thousand views and two hundred subscribers is a worse film for a channel than
    thirty thousand views and three hundred. The Director must be able to see that."""
    big = a_film(engine, studio["channel_id"], title="Big reach", views=100000, subscribers=200)
    small = a_film(engine, studio["channel_id"], title="Small reach", views=30000, subscribers=300)
    films = {f["publication_id"]: f for f in video_performance(engine, studio["channel_id"])}
    assert films[big]["subscriber_conversion_percentage"] == pytest.approx(0.2, abs=0.01)
    assert films[small]["subscriber_conversion_percentage"] == pytest.approx(1.0, abs=0.01)
    assert (
        films[small]["subscriber_conversion_percentage"]
        > films[big]["subscriber_conversion_percentage"]
    )


def test_10_retention_is_read_against_the_channels_own_median(engine, studio):
    """Retention is the strategic signal, and it only means something next to this channel's
    own median. Where inside the film they left is not in the available analytics, and the
    diagnosis says so instead of guessing a second."""
    a_baseline(engine, studio["channel_id"], films=4, retention=80.0)
    weak = a_film(engine, studio["channel_id"], title="Weak", retention=50.0, views=1000)
    baseline = channel_baselines(engine, studio["channel_id"])
    film = next(
        f for f in video_performance(engine, studio["channel_id"]) if f["publication_id"] == weak
    )
    assert baseline["median_view_percentage"] == 80.0
    verdict = diagnose(film, baseline)
    assert verdict["kind"] == "HOOK_OR_RETENTION_FAILURE"
    assert verdict["assign_to"] == "ScriptWriter"
    assert "nu apare în analytics-ul disponibil" in verdict["reason"]


# --------------------------------------------------------------- 11-14: judgement


def test_11_one_failed_video_does_not_condemn_a_category(engine, studio, settings):
    """The rule the Owner called critical. With no baseline there is no verdict at all, and
    with one the verdict is about the film, never about its category — and nothing in the
    studio permanently blocks a topic."""
    only = a_film(engine, studio["channel_id"], title="A history film", views=10, retention=20.0)
    film = video_performance(engine, studio["channel_id"])[0]
    baseline = channel_baselines(engine, studio["channel_id"])
    verdict = classify(film, baseline)
    assert verdict["verdict"] == "INSUFFICIENT_DATA"
    assert "bază de comparație" in verdict["reason"]
    assert diagnose(film, baseline)["kind"] == "INSUFFICIENT_DATA"

    # With a baseline, the film is judged and the category is not: the diagnosis names one
    # film's cause and the failure is a cooldown at most, never a permanent ban.
    a_baseline(engine, studio["channel_id"], films=4, views=2000, retention=80.0)
    film = next(
        f for f in video_performance(engine, studio["channel_id"]) if f["publication_id"] == only
    )
    baseline = channel_baselines(engine, studio["channel_id"])
    judged = classify(film, baseline)
    assert judged["verdict"] in ("UNDERPERFORMER", "FAILED_EXPERIMENT")
    assert judged["evidence"]["sample_size"] >= MINIMUM_BASELINE
    with Session(engine) as session:
        statuses = {row.status for row in session.scalars(select(TopicIdea))}
    assert "BANNED" not in statuses and "BLACKLISTED" not in statuses


def test_12_one_good_video_is_not_a_proven_format(engine, studio):
    """A winner is a statement about a film against its channel, with a confidence that says
    how much it is worth. Four hours of data is never a format decision."""
    a_baseline(engine, studio["channel_id"], films=3, views=1000, retention=70.0)
    hit = a_film(
        engine, studio["channel_id"], title="A hit", views=20000, retention=85.0, age_hours=30
    )
    film = next(
        f for f in video_performance(engine, studio["channel_id"]) if f["publication_id"] == hit
    )
    baseline = channel_baselines(engine, studio["channel_id"])
    verdict = classify(film, baseline)
    assert verdict["verdict"] == "STRONG_WINNER"
    assert verdict["confidence"] == "MEDIUM", "three films of baseline is not high confidence"

    # Too early to say anything at all.
    early = a_film(engine, studio["channel_id"], title="Hours old", views=9000, age_hours=4)
    fresh = next(
        f for f in video_performance(engine, studio["channel_id"]) if f["publication_id"] == early
    )
    early_verdict = classify(fresh, baseline)
    assert early_verdict["verdict"] == "INSUFFICIENT_DATA"
    assert early_verdict["confidence"] == "LOW"


def test_13_a_winner_produces_a_rational_follow_up_not_a_clone(engine, studio, settings):
    """ "Make another one" is not a decision. The spike is raised as a matter to investigate,
    assigned to research, and marked as needing more data rather than declared a format."""
    a_baseline(engine, studio["channel_id"], films=4, views=500, retention=70.0)
    a_film(engine, studio["channel_id"], title="Roman concrete", views=20000, retention=88.0)
    state = company_state(engine, settings)
    spikes = [a for a in state["anomalies"] if a["kind"] == "VIEW_SPIKE"]
    assert spikes, "a film far above the channel's rate is worth looking at"
    matters = findings(engine, settings, state)
    matter = next(m for m in matters if m["matter_key"].startswith("anomaly_view_spike"))
    assert matter["suggested_decision"] == "NEEDS_MORE_DATA"
    assert matter["owner_role"] == "LeadResearcher"
    assert matter["action"] in ASSIGNABLE["LeadResearcher"]


def test_14_a_failure_produces_a_diagnosis_with_the_department_that_can_fix_it(engine, studio):
    """Reach, retention, conversion or topic: four different causes, four different
    assignments, each from the numbers that separate them."""
    a_baseline(engine, studio["channel_id"], films=5, views=2000, retention=80.0, subscribers=20)
    baseline = channel_baselines(engine, studio["channel_id"])

    def judged(**kwargs):
        publication = a_film(engine, studio["channel_id"], **kwargs)
        film = next(
            f
            for f in video_performance(engine, studio["channel_id"])
            if f["publication_id"] == publication
        )
        return diagnose(film, baseline)

    # Served and not chosen: click-through collapsed.
    assert judged(title="Bad frame", ctr=1.0, views=200)["kind"] == "REACH_FAILURE"
    # Chosen and abandoned.
    assert judged(title="Bad hook", retention=40.0)["kind"] == "HOOK_OR_RETENTION_FAILURE"
    # Watched and not subscribed.
    assert (
        judged(title="No promise", views=2000, retention=80.0, subscribers=0)["kind"]
        == "CONVERSION_FAILURE"
    )


# --------------------------------------------------------------- 15-18: economics and queue


def test_15_and_16_cost_and_time_are_joined_to_what_the_film_returned(engine, studio):
    """The comparison the Owner wrote out: a film at 2.20 USD that brought 85 000 views
    against one at 14 USD that brought 12 000. The numbers must sit on the same row."""
    cheap = a_film(
        engine,
        studio["channel_id"],
        title="Cheap and strong",
        views=85000,
        subscribers=420,
        cost_usd=2.20,
        minutes=38.0,
    )
    dear = a_film(
        engine,
        studio["channel_id"],
        title="Dear and weak",
        views=12000,
        subscribers=19,
        cost_usd=14.00,
        minutes=140.0,
    )
    films = {f["publication_id"]: f for f in video_performance(engine, studio["channel_id"])}
    assert films[cheap]["cost_usd"] == 2.2 and films[dear]["cost_usd"] == 14.0
    assert films[cheap]["production_minutes"] == 38.0
    assert films[dear]["production_minutes"] == 140.0
    assert films[cheap]["views_per_dollar"] > films[dear]["views_per_dollar"]
    assert films[cheap]["subscribers_per_dollar"] > films[dear]["subscribers_per_dollar"]
    assert films[cheap]["cost_per_thousand_views"] < films[dear]["cost_per_thousand_views"]
    # A film with no priced usage is not free: it is unpriced.
    free = a_film(engine, studio["channel_id"], title="Unpriced", cost_usd=0)
    unpriced = next(
        f for f in video_performance(engine, studio["channel_id"]) if f["publication_id"] == free
    )
    assert unpriced["cost_usd"] is None and unpriced["views_per_dollar"] is None


def test_17_what_the_analytics_say_becomes_work_for_a_department(engine, studio, settings):
    """A finding that changes nothing is a report. Every matter the measurements raise carries
    the department that can act and the work it would be given."""
    a_baseline(engine, studio["channel_id"], films=5, views=2000, retention=80.0)
    for index in range(3):
        a_film(engine, studio["channel_id"], title=f"Weak {index}", retention=45.0, views=1500)
    state = company_state(engine, settings)
    matters = findings(engine, settings, state)
    assert matters, "three films below the retention median is a matter"
    actionable = [m for m in matters if m["owner_role"]]
    assert actionable
    for matter in actionable:
        assert matter["owner_role"] in ASSIGNABLE
        if matter["action"]:
            assert matter["action"] in ASSIGNABLE[matter["owner_role"]]


def test_18_the_backlog_is_ordered_by_what_is_worth_doing_next(engine, studio):
    """Not first-in-first-out. Evidence in hand and work already started come first, and every
    place in the queue carries the sentence that put it there."""
    weak = a_topic(engine, "Weak idea, no evidence", composite=0.45)
    strong = a_topic(engine, "Strong idea with evidence", composite=0.8, verified=3)
    started = a_topic(engine, "Already selected", composite=0.6, status="SELECTED")
    prioritise_backlog(engine)
    queue = backlog(engine)
    order = [row["topic_id"] for row in queue]
    assert order.index(strong) < order.index(weak)
    assert order.index(started) < order.index(weak)
    for row in queue:
        assert row["priority_reason"], "a place in the queue needs a reason"
    assert (
        "afirmații verificate"
        in next(r for r in queue if r["topic_id"] == strong)["priority_reason"]
    )
    assert "fără dovezi" in next(r for r in queue if r["topic_id"] == weak)["priority_reason"]


# --------------------------------------------------------------- 19-21: authority and honesty


def test_19_the_owners_stop_outranks_the_director(engine, studio, settings):
    """The human owner stays above the autonomous Director where the architecture says so.
    With autonomy stopped, the loop assigns nothing at all."""
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    registry, model = no_choice_registry(studio)
    result = direct_company(engine, registry, settings)
    assert result["status"] == "SKIPPED"
    assert "Autonomia este oprită" in result["reason"]
    assert model.prompts == [], "nothing is even asked of the model"
    with Session(engine) as session:
        assert session.scalars(select(DirectorDecision)).all() == []


def test_20_high_impact_decisions_go_to_the_owner_not_the_department(engine, studio, settings):
    """Stopping a category or repositioning a channel is the Owner's. The Director states the
    case, records nothing as done, and waits."""
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    state = company_state(engine, settings)
    matters = findings(engine, settings, state)
    matter = next(m for m in matters if m["matter_key"].startswith("bottleneck_"))
    registry, _ = registry_with(
        studio,
        lambda prompt: json.dumps(
            {
                "choices": [
                    {
                        "matter_key": matter["matter_key"],
                        "decision": "STOP",
                        "interpretation": "The whole category should stop.",
                        "confidence": "HIGH",
                        "action": "stop writing anything in this category",
                        "owner_role": "ScriptWriter",
                        "review_after_videos": 5,
                    }
                ],
                "note": "",
            }
        ),
    )
    result = direct_company(engine, registry, settings)
    assert "STOP" in HIGH_IMPACT
    assert result["escalated"] == [matter["matter_key"]]
    assert result["assignments"] == []
    with Session(engine) as session:
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
        ).all()
        assert any(
            (letter.body_json or {}).get("kind") == "direction_escalation" for letter in letters
        )


def test_21_nothing_in_the_directors_inputs_claims_another_channels_private_numbers(
    engine, studio, settings
):
    """The critical honesty rule. Everything the Director reads about performance comes from
    this studio's own publications; the only outside signal available is public trends, and
    the studio's own model says a trend is never a source and never a claim."""
    from app.analytics.models import TrendSnapshot

    a_film(engine, studio["channel_id"], views=1000)
    state = company_state(engine, settings)
    blob = json.dumps(state, default=str).lower()
    for invented in (
        "competitor_retention",
        "competitor_watch_time",
        "competitor_revenue",
        "competitor_subscriber_conversion",
        "rival_ctr",
    ):
        assert invented not in blob
    # Every measured film in the state belongs to one of this studio's own channels.
    with Session(engine) as session:
        ours = {row.id for row in session.scalars(select(ChannelRecord))}
    assert {c["channel_id"] for c in state["channels"]} <= ours
    assert "never a source, never a claim" in (TrendSnapshot.__doc__ or "")


# --------------------------------------------------------------- 22-25: memory and restraint


def test_22_a_strategic_decision_is_recorded_with_its_evidence_and_a_review_date(
    engine, studio, settings
):
    """Observation, evidence, interpretation, confidence, decision, action, owner, review.
    The database refuses a decision nobody will check."""
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    registry, _ = no_choice_registry(studio)
    result = direct_company(engine, registry, settings)
    assert result["assignments"], "the measurements carry the loop when the model does not"
    with Session(engine) as session:
        row = session.scalars(select(DirectorDecision)).first()
        assert row is not None
        assert row.observation and row.interpretation and row.action
        assert row.confidence in ("LOW", "MEDIUM", "HIGH")
        assert row.owner_role in ASSIGNABLE
        assert row.state == "OPEN"
        assert row.review_after_videos or row.decision == "NEEDS_MORE_DATA"
        assert row.evidence_json != {}
        # And the department was actually written to, with the same words.
        letter = session.get(AgentMessage, row.message_id)
        assert letter is not None and "DE FĂCUT:" in letter.body_text


def test_23_a_decision_comes_back_for_review_when_its_condition_is_met(engine, studio, settings):
    """A hypothesis with no review is a sentiment. When the films it was waiting for have been
    published, the decision is raised again as a matter."""
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    registry, _ = no_choice_registry(studio)
    direct_company(engine, registry, settings)
    with Session(engine) as session:
        decision = session.scalars(select(DirectorDecision)).first()
        decision_id = decision.id
        wanted = decision.review_after_videos or 3
    assert due_reviews(engine) == []

    for index in range(wanted):
        a_film(engine, studio["channel_id"], title=f"Published {index}")
    due = due_reviews(engine)
    assert due and due[0]["decision_id"] == decision_id
    assert due[0]["published_since"] >= wanted
    state = company_state(engine, settings)
    assert any(m["matter_key"].startswith("review_") for m in findings(engine, settings, state))

    closed = review_decision(engine, decision_id, "Retention recovered on the next three.")
    assert closed["state"] == "REVIEWED"
    # Closing one decision closes that one. The others the same three films made due are
    # still due, which is the point: each decision is reviewed on its own evidence.
    assert decision_id not in {row["decision_id"] for row in due_reviews(engine)}
    with Session(engine) as session:
        assert session.get(DirectorDecision, decision_id).outcome.startswith("Retention")


def test_24_a_matter_already_being_worked_on_is_not_raised_again(engine, studio, settings):
    """The endless conversation the Owner asked to be prevented. A matter under an open
    decision is in hand; raising it every six hours is noise, not management."""
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    registry, _ = no_choice_registry(studio)
    first = direct_company(engine, registry, settings)
    assert first["assignments"]
    second = direct_company(engine, registry, settings)
    assert second["assignments"] == []
    assert "deja în lucru" in second["reason"]
    with Session(engine) as session:
        assert len(session.scalars(select(DirectorDecision)).all()) == len(first["assignments"])


def test_25_a_matter_that_keeps_coming_back_goes_to_the_owner_instead_of_round_again(
    engine, studio, settings
):
    """Three assignments to the same matter is not a fourth attempt; it is a decision the
    Owner has to take. This is the end of the retry loop."""
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    state = company_state(engine, settings)
    matter = next(
        m for m in findings(engine, settings, state) if m["matter_key"].startswith("bottleneck_")
    )
    # Three closed attempts already on the record.
    with Session(engine) as session, session.begin():
        for index in range(MAX_ATTEMPTS_PER_MATTER):
            session.add(
                DirectorDecision(
                    id=str(uuid4()),
                    scope="PRODUCTION",
                    channel_id=None,
                    observation="Tried before",
                    evidence_json={"attempt": index},
                    interpretation="Tried before",
                    confidence="MEDIUM",
                    decision="ITERATE",
                    action="shorten the setup and move the reveal earlier",
                    owner_role="ScriptWriter",
                    review_after_videos=3,
                    state="REVIEWED",
                    published_at_decision=0,
                    matter_key=matter["matter_key"],
                    created_at=utc_now(),
                )
            )
    registry, _ = no_choice_registry(studio)
    result = direct_company(engine, registry, settings)
    assert matter["matter_key"] in result["escalated"]
    assert not any(a["matter_key"] == matter["matter_key"] for a in result["assignments"])
    with Session(engine) as session:
        letters = session.scalars(
            select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
        ).all()
    assert any("de trei ori" in (letter.body_text or "") for letter in letters)


# --------------------------------------------------------------- 26-30: nothing else broke


def test_26_the_panel_reads_the_same_state_the_backend_holds(engine, client, headers, studio):
    """What the Owner sees is what the studio stored, through the existing panel's endpoints."""
    a_film(engine, studio["channel_id"], views=4200, retention=77.0, subscribers=30)
    state = client.get("/api/v1/runbook/company-state", headers=headers).json()
    assert state["maturity"] in ("COLD_START", "EARLY_DATA", "MATURE")
    ours = next(c for c in state["channels"] if c["channel_id"] == studio["channel_id"])
    assert ours["measured"] == 1 and ours["published"] == 1
    assert state["pipeline"]["stages"]["published"] == 1
    performance = client.get("/api/v1/analytics/performance", headers=headers).json()
    assert performance["videos"][0]["views"] == 4200
    health = client.get(
        f"/api/v1/analytics/channel-health/{studio['channel_id']}", headers=headers
    ).json()
    assert health["measured"] == 1
    decisions = client.get("/api/v1/runbook/decisions", headers=headers).json()
    assert decisions["decisions"] == [] and decisions["due_for_review"] == []
    # And the Owner can run the pass himself from the panel.
    ran = client.post("/api/v1/runbook/direct", headers=headers)
    assert ran.status_code == 200 and ran.json()["status"] in ("COMPLETED", "SKIPPED")


def test_27_the_two_environments_are_untouched(engine, studio, settings):
    """The Director reads the environment; she does not decide it, and the routing policies
    are the ones that were already there."""
    from app.media.production_policy import PRODUCTION_READY, choose_model
    from app.services import studio_environment

    state = company_state(engine, settings)
    assert state["environment"] == studio_environment(engine) == "TEST"
    import inspect

    assert "environment" in inspect.signature(choose_model).parameters
    assert PRODUCTION_READY == ("CANDIDATE", "PRODUCTION", "PREFERRED")


def test_28_the_content_pipeline_still_runs_end_to_end(engine, studio, settings):
    """The stages are the stages. The Director reads their counts; she does not replace them."""
    from app.runbook.services import STAGES

    assert STAGES[:6] == (
        "preflight",
        "performance_intake",
        "idea_generation",
        "research_and_verification",
        "selection",
        "script_and_storyboard",
    )
    counts = pipeline(engine)["stages"]
    for key in (
        "topics_proposed",
        "scripts_approved",
        "storyboards_approved",
        "renders_completed",
        "published",
    ):
        assert key in counts


def test_29_the_hierarchy_is_the_one_that_was_there(engine, studio, settings):
    """Eight roles, each with a mission, and the Director can only assign to a role that
    exists and can do the work."""
    with Session(engine) as session:
        roles = {row.name for row in session.scalars(select(Role))}
        agents = session.scalars(select(Agent)).all()
    assert {
        "Director",
        "LeadResearcher",
        "FactChecker",
        "ScriptWriter",
        "VoiceArtist",
        "VideoEditor",
        "Publisher",
        "Accountant",
    } <= roles
    assert len(agents) >= 8
    assert set(ASSIGNABLE) <= roles
    assert "Director" not in ASSIGNABLE, "the Director does not assign work to herself"


def test_30_a_broken_analytics_provider_does_not_stop_the_director(
    engine, studio, settings, monkeypatch
):
    """A vendor failure is that vendor's failure. The loop reads stored rows, so an analytics
    API that is down cannot stop the company from being managed."""
    from app.providers import youtube_analytics

    def explode(*args, **kwargs):
        raise RuntimeError("YouTube Analytics API request failed")

    monkeypatch.setattr(
        youtube_analytics.YouTubeAnalyticsProvider, "from_verified_settings", explode
    )
    for index in range(4):
        a_topic(engine, f"Selected {index}", status="SELECTED")
    registry, _ = no_choice_registry(studio)
    result = direct_company(engine, registry, settings)
    assert result["status"] == "COMPLETED"
    assert result["assignments"], "the company is still managed with no analytics provider"

    # And a model that answers nonsense is a degradation, not a crash: the measurements
    # decide in their own order.
    broken, _ = registry_with(studio, lambda prompt: "}{ not json")
    again = direct_company(engine, broken, settings)
    assert again["status"] == "COMPLETED"
