"""Two environments, one router, and a model that has to earn its place.

The Owner paid twenty-one dollars in an afternoon for experiments, because the studio could
not tell a test from a film: both bought the best shot the account could make. And it kept
buying the dearest model because "premium" had been read as "expensive" rather than as "good
enough for what this scene needs".

These are the eighteen checks the Owner asked for. They are about decisions, not plumbing:
what a test may buy, what a film must reach, who decides which of the two is happening, when
a new model may film something people will see, and what happens when a vendor changes a
price without telling anyone.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.integrations.models import Integration, ModelOutcome, ProviderResource
from app.integrations.vault import CredentialVault
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


def _connection(engine, kind="runway"):
    identifier = str(uuid4())
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind=kind,
                name=kind,
                config={"credit_usd": 0.01},
                encrypted_secrets=vault.encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
    return identifier


def _model(
    engine,
    integration_id,
    remote_id,
    *,
    price_per_second=0.10,
    quality=0.9,
    status="PRODUCTION",
    ratios=("1080:1920",),
    tasks=("text_to_video", "image_to_video"),
):
    """One model in the catalogue, as a catalog refresh would have written it."""
    with Session(engine) as session, session.begin():
        session.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=integration_id,
                resource_type="MODEL",
                remote_id=remote_id,
                name=remote_id,
                api_metadata={
                    "tasks": list(tasks),
                    "ratios": {task: list(ratios) for task in tasks},
                    "needs_references": {task: False for task in tasks},
                    "dry_run": {task: False for task in tasks},
                },
                api_available=True,
                last_seen_at=utc_now(),
                pricing={"per_second_usd": price_per_second, "unit": "per second of video"},
                capabilities={"quality_score": quality, "reliability_score": 0.9},
                metadata_version=1,
                production_status=status,
            )
        )


def _requirement(**kwargs):
    from app.media.production_policy import SceneRequirement

    base = {
        "purpose": "video",
        "tasks": ("text_to_video",),
        "tier": "STANDARD",
        "seconds": 6.0,
    }
    base.update(kwargs)
    return SceneRequirement(**base)


def _choose(engine, integration_id, requirement, **kwargs):
    from app.media.production_policy import choose_model

    with Session(engine) as session:
        return choose_model(session, integration_id, requirement, **kwargs)


def _outcomes(engine, integration_id, remote_id, *, count, accepted=True, run_kind="PRODUCTION"):
    with Session(engine) as session, session.begin():
        for _ in range(count):
            session.add(
                ModelOutcome(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    remote_id=remote_id,
                    purpose="video",
                    run_kind=run_kind,
                    environment="PRODUCTION" if run_kind == "PRODUCTION" else "TEST",
                    scene_category="GENERAL",
                    quality_tier="STANDARD",
                    seconds_requested=6.0,
                    seconds_accepted=6.0 if accepted else 0.0,
                    credits=60.0,
                    usd=0.60,
                    first_pass=accepted,
                    accepted=accepted,
                    failure_kind=None if accepted else "TECHNICAL",
                    created_at=utc_now(),
                )
            )


# --------------------------------------------------------------------- 1-7: the test bench


def test_1_test_takes_the_cheapest_compatible_model_and_ignores_the_quality_ranking(engine):
    """A test answers "does this work". A mediocre picture is a pass, and the cheapest model
    that can do the task is the right one — the ranking is not consulted at all."""
    connection = _connection(engine)
    _model(engine, connection, "beautiful", price_per_second=0.43, quality=0.95)
    _model(engine, connection, "plain", price_per_second=0.02, quality=0.40)

    decision = _choose(engine, connection, _requirement(), environment="TEST")

    assert decision["model_id"] == "plain"
    assert "cheapest" in decision["reason"].lower()


def test_2_a_test_that_loses_its_model_falls_back_to_the_next_cheapest_never_to_the_best(engine):
    """The fallback of a cheap model is a slightly less cheap model. A test whose first
    choice fails must not quietly escalate to the model a film would use."""
    connection = _connection(engine)
    _model(engine, connection, "beautiful", price_per_second=0.43, quality=0.95)
    _model(engine, connection, "middle", price_per_second=0.08, quality=0.7)
    _model(engine, connection, "plain", price_per_second=0.02, quality=0.4)

    decision = _choose(engine, connection, _requirement(), environment="TEST", exclude=("plain",))

    assert decision["model_id"] == "middle"


def test_3_a_test_generation_over_the_cost_ceiling_is_refused_not_bought(engine):
    """The ceiling the Owner set after the afternoon that cost twenty-one dollars. A shot
    above it is not generated: no model is returned, and the reason says why."""
    connection = _connection(engine)
    _model(engine, connection, "dear", price_per_second=0.43, quality=0.95)

    decision = _choose(engine, connection, _requirement(budget_usd=0.60), environment="TEST")

    assert decision["model_id"] is None
    assert decision["blocked_by_ceiling"] is True
    assert "ceiling" in decision["reason"]


def test_4_a_test_second_over_the_per_second_ceiling_is_refused(engine):
    """The second ceiling is per second, so a short shot on a dear model is refused too —
    it is the rate that says whether a model belongs in a test."""
    connection = _connection(engine)
    _model(engine, connection, "dear", price_per_second=0.43, quality=0.95)

    decision = _choose(
        engine,
        connection,
        _requirement(seconds=1.0, max_usd_per_second=0.12),
        environment="TEST",
    )

    assert decision["model_id"] is None and decision["blocked_by_ceiling"] is True


def test_5_the_director_can_name_a_model_by_hand_and_the_decision_says_so(engine):
    """An override exists in both environments, and it is recorded as an override: a
    decision nobody can attribute is a decision nobody can review."""
    connection = _connection(engine)
    _model(engine, connection, "beautiful", price_per_second=0.43, quality=0.95)
    _model(engine, connection, "plain", price_per_second=0.02, quality=0.4)

    decision = _choose(engine, connection, _requirement(), environment="TEST", forced="beautiful")

    assert decision["model_id"] == "beautiful"
    assert decision["forced"] is True
    assert "Director" in decision["reason"]


def test_6_the_environment_is_the_studios_own_state_and_a_page_cannot_spoof_it(
    engine, client, headers
):
    """A render request carries no environment. It is read from the policy the server owns
    and changed only by the Owner's versioned command — the whole point of putting it there
    instead of in a query parameter a page could set."""
    from app.services import studio_environment

    assert studio_environment(engine) == "TEST"
    policy = client.get("/api/v1/snapshot", headers=headers).json()["policy"]
    assert policy["environment"] == "TEST"

    changed = client.post(
        "/api/v1/owner/environment",
        headers=headers,
        json={
            "schema_version": 1,
            "command_id": str(uuid4()),
            "expected_version": policy["version"],
            "environment": "PRODUCTION",
        },
    )
    assert changed.status_code == 200
    assert studio_environment(engine) == "PRODUCTION"

    # And a stale version is refused, so two tabs cannot fight over it.
    stale = client.post(
        "/api/v1/owner/environment",
        headers=headers,
        json={
            "schema_version": 1,
            "command_id": str(uuid4()),
            "expected_version": policy["version"],
            "environment": "TEST",
        },
    )
    assert stale.status_code == 409
    assert studio_environment(engine) == "PRODUCTION"


def test_7_a_test_render_films_the_minimum_and_a_production_render_does_not(settings):
    """ "La teste redam doar minimul." The scene limit and the budget both change with the
    environment, and the settings are where the numbers live."""
    assert settings.test_motion_scenes == 2
    assert settings.motion_scenes_max is None
    assert settings.test_max_cost_per_generation_usd < settings.motion_budget_usd
    assert settings.test_max_cost_per_second_usd < 0.43


# --------------------------------------------------------------------- 8-13: the film


def test_8_production_takes_the_least_expensive_model_that_reaches_the_quality(engine):
    """Not the dearest, and not the cheapest: the least expensive model that reaches what
    the scene requires. The Owner's question — is three times the price worth it — is
    answered in the decision itself."""
    connection = _connection(engine)
    _model(engine, connection, "dear", price_per_second=0.30, quality=0.95)
    _model(engine, connection, "good", price_per_second=0.10, quality=0.88)
    _model(engine, connection, "poor", price_per_second=0.02, quality=0.50)

    decision = _choose(engine, connection, _requirement(tier="PREMIUM"), environment="PRODUCTION")

    assert decision["model_id"] == "good"
    assert "3.0x" in decision["reason"] or "x the cost" in decision["reason"]


def test_9_the_scene_decides_the_tier_and_the_hook_is_asked_for_more(engine):
    """A tier describes what the scene needs, never what a model costs. The first shot
    decides whether anyone watches and the last whether anyone comments, so they are asked
    for more than the middle — and a middle scene does not buy a hero shot."""
    from app.media.assembler import scene_tier
    from app.media.production_policy import required_quality, scene_role

    assert scene_role(1, 8) == "HOOK"
    assert scene_role(8, 8) == "ENDING"
    assert scene_role(4, 8) == "NORMAL"
    assert required_quality("HERO") > required_quality("PREMIUM") > required_quality("STANDARD")
    assert scene_tier({"scene_index": 1}, 8) != scene_tier({"scene_index": 4}, 8)
    # A tier a person set by hand is kept as it is.
    assert scene_tier({"scene_index": 4, "quality_tier": "HERO"}, 8) == "HERO"

    connection = _connection(engine)
    _model(engine, connection, "good", price_per_second=0.10, quality=0.88)
    _model(engine, connection, "best", price_per_second=0.30, quality=0.95)
    normal = _choose(engine, connection, _requirement(tier="STANDARD"), environment="PRODUCTION")
    hook = _choose(engine, connection, _requirement(tier="HERO"), environment="PRODUCTION")
    assert normal["model_id"] == "good"
    assert hook["model_id"] == "best"


def test_10_the_decision_says_what_it_did_not_buy_and_what_the_multiple_would_have_been(engine):
    """The marginal question, in the record: a better model existed, this is what it would
    have cost, and this is why the scene did not need it."""
    connection = _connection(engine)
    _model(engine, connection, "good", price_per_second=0.10, quality=0.88)
    _model(engine, connection, "best", price_per_second=0.30, quality=0.96)

    decision = _choose(engine, connection, _requirement(tier="PREMIUM"), environment="PRODUCTION")

    assert decision["model_id"] == "good"
    assert "best" in decision["reason"]
    assert "does not need" in decision["reason"]
    assert any(c["model_id"] == "best" for c in decision["alternatives"])


def test_11_when_nothing_reaches_the_tier_the_best_available_is_used_and_said_so(engine):
    """A studio that cannot reach a tier says so. Silence here would be a claim that the
    quality was met."""
    connection = _connection(engine)
    _model(engine, connection, "ordinary", price_per_second=0.05, quality=0.60)
    _model(engine, connection, "less", price_per_second=0.02, quality=0.40)

    decision = _choose(engine, connection, _requirement(tier="HERO"), environment="PRODUCTION")

    assert decision["model_id"] == "ordinary"
    assert decision["requirement_met"] is False
    assert "No model reaches" in decision["reason"]


def test_12_a_model_outside_production_cannot_film_a_scene_that_will_be_published(engine):
    """A model the vendor exposed today has filmed nothing. It may be tried in a test; it
    may not film something people will see until its own results say it can."""
    connection = _connection(engine)
    _model(engine, connection, "unknown", price_per_second=0.02, quality=0.99, status="QUARANTINE")

    production = _choose(engine, connection, _requirement(), environment="PRODUCTION")
    assert production["model_id"] is None
    assert production["blocked_by_lifecycle"] is True

    # In a test it is exactly what the studio wants to try, and it is the cheapest.
    assert _choose(engine, connection, _requirement(), environment="TEST")["model_id"] == "unknown"


def test_13_a_retired_or_denied_model_is_never_chosen_in_either_environment(engine, settings):
    """Retired for what it delivered, or named by the Owner's deny list: either way it is
    out everywhere, and only the Director naming it by hand brings it back."""
    from app.integrations.lifecycle import deny_patterns, is_denied

    connection = _connection(engine)
    _model(engine, connection, "retired", price_per_second=0.01, quality=0.99, status="DEPRECATED")
    _model(engine, connection, "working", price_per_second=0.10, quality=0.88)

    assert _choose(engine, connection, _requirement(), environment="TEST")["model_id"] == "working"
    assert (
        _choose(engine, connection, _requirement(), environment="PRODUCTION")["model_id"]
        == "working"
    )
    forced = _choose(engine, connection, _requirement(), environment="TEST", forced="retired")
    assert forced["model_id"] == "retired" and forced["forced"] is True

    patterns = deny_patterns(settings.model_copy(update={"model_deny_list": "seedance*, old-*"}))
    assert is_denied("seedance2_5", patterns)
    assert is_denied("OLD-model", patterns)
    assert not is_denied("wan3", patterns)


# --------------------------------------------------------------------- 14-18: learning


def test_14_every_generation_is_recorded_with_its_environment_and_kind(engine):
    """What a model delivered, for what it cost, in what kind of scene — and whether this
    was a film, a benchmark or a cheap functional test. Without the last of those, a test
    that deliberately bought a poor shot would teach the studio that the model is poor."""
    from app.media.production_policy import model_record

    connection = _connection(engine)
    _model(engine, connection, "m", price_per_second=0.10)
    _outcomes(engine, connection, "m", count=2, accepted=True, run_kind="TEST_FUNCTIONAL")

    with Session(engine) as session:
        record = model_record(session, connection, "video", "m")
    assert record["generations"] == 2
    # Recorded, and not judged: a functional test says the pipeline worked, nothing more.
    assert record["judged"] == 0 and record["acceptance"] is None

    _outcomes(engine, connection, "m", count=3, accepted=True, run_kind="TEST_BENCHMARK")
    with Session(engine) as session:
        record = model_record(session, connection, "video", "m")
    assert record["judged"] == 3 and record["acceptance"] == 1.0


def test_15_what_a_model_actually_delivered_outweighs_what_a_page_said_about_it(engine):
    """A steward's reading is a starting point. Once the studio has enough of its own
    results, they carry — and the cost that matters is per accepted second, not per second
    billed, because a shot that was thrown away was still paid for."""
    from app.media.production_policy import model_record

    connection = _connection(engine)
    _model(engine, connection, "flaky", price_per_second=0.02, quality=0.95)
    _model(engine, connection, "steady", price_per_second=0.10, quality=0.88)
    # Twelve judged generations, half of them refused: the cheap model is not cheap.
    _outcomes(engine, connection, "flaky", count=6, accepted=True)
    _outcomes(engine, connection, "flaky", count=6, accepted=False)

    with Session(engine) as session:
        record = model_record(session, connection, "video", "flaky")
    assert record["acceptance"] == 0.5
    assert record["cost_per_accepted_second"] > 0.02

    decision = _choose(engine, connection, _requirement(tier="PREMIUM"), environment="PRODUCTION")
    assert decision["model_id"] == "steady"


def test_16_the_review_promotes_what_delivers_and_demotes_what_does_not(engine, settings):
    """The daily review reads the studio's own results and moves models between stations.
    It generates nothing, so it costs nothing, and a model that has started failing stops
    being chosen within a day."""
    from app.integrations.lifecycle import review_models

    connection = _connection(engine)
    _model(engine, connection, "proven", price_per_second=0.05, status="DISCOVERED")
    _model(engine, connection, "failing", price_per_second=0.05, status="PRODUCTION")
    _outcomes(engine, connection, "proven", count=4, accepted=True)
    _outcomes(engine, connection, "failing", count=3, accepted=False)

    result = review_models(engine, settings, full=True)
    moves = {change["model_id"]: change for change in result["changes"]}

    assert moves["proven"]["now"] == "CANDIDATE"
    assert moves["failing"]["now"] == "QUARANTINE"
    assert result["frontier"], "a full review reports the frontier it saw"
    # And the promoted model may now film a published scene, while the other may not.
    assert _choose(engine, connection, _requirement(), environment="PRODUCTION")["model_id"] == (
        "proven"
    )


def test_17_a_price_that_moves_keeps_the_old_one_and_a_big_move_reaches_the_owner(engine):
    """A price is never overwritten in silence. What it was is kept with the date and how
    the new one was established, and a move past the Owner's threshold is a letter."""
    from app.integrations.lifecycle import price_changes
    from app.media.production_policy import record_measured_price

    connection = _connection(engine)
    _model(engine, connection, "m", price_per_second=0.025)

    moves = record_measured_price(engine, connection, "m", 0.43, "per second of video")

    assert moves and moves[0]["key"] == "per_second_usd"
    assert moves[0]["was"] == 0.025 and moves[0]["now"] == 0.43
    assert moves[0]["percent"] > 1000
    with Session(engine) as session:
        row = session.scalar(select(ProviderResource).where(ProviderResource.remote_id == "m"))
        assert row.previous_pricing_json["per_second_usd"] == 0.025
        assert row.price_verification == "BILLED"
        assert row.pricing_version == 2
        assert row.price_verified_at

    # A first price is a fact, not a change; an unchanged price moves nothing.
    assert price_changes({}, {"per_second_usd": 0.1}) == []
    assert record_measured_price(engine, connection, "m", 0.43, "per second of video") == []


def test_18_a_vendors_quote_can_mark_a_stored_price_stale_and_a_new_model_waits_outside(engine):
    """Two facts the studio could not state before. That a price it wrote down no longer
    matches what the vendor quotes for the shot in hand — and that a model which appeared in
    the catalogue today is new, so it waits outside production until it has results."""
    from app.integrations.lifecycle import classify_discovered
    from app.media.production_policy import record_quoted_price

    connection = _connection(engine)
    _model(engine, connection, "m", price_per_second=0.10)

    # Within tolerance the stored price stands: a quote is for one shot, at one length.
    assert (
        record_quoted_price(engine, connection, "m", 0.103, "per_second_usd", tolerance_percent=5.0)
        is None
    )
    stale = record_quoted_price(
        engine, connection, "m", 0.20, "per_second_usd", tolerance_percent=5.0
    )
    assert stale and stale["stored"] == 0.10 and stale["observed"] == 0.20
    with Session(engine) as session:
        row = session.scalar(select(ProviderResource).where(ProviderResource.remote_id == "m"))
        assert row.price_verification == "ESTIMATED"
        assert row.pricing["per_second_usd"] == 0.20

    # And what a newly discovered model's standing is, by what the vendor said about it.
    assert classify_discovered("wan3", {"tasks": ["text_to_video"]})[0] == "DISCOVERED"
    assert classify_discovered("mystery", {})[0] == "QUARANTINE"
    assert classify_discovered("seedance2_5", {"tasks": ["x"]}, patterns=("seedance*",))[0] == (
        "DEPRECATED"
    )
