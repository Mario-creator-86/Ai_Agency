"""SCENE_MODEL_POLICY: the model is chosen per scene, as cheap as that scene allows.

The Owner, 2026-09-27: "Nu trebuie un singur model pe tot filmul! Trebuie sa optimizam
costurile!" So there is no one-model-per-film lock (the file keeps its planned name). Every
scene says what it needs - its kind, its tier (HERO for the hook and the moments that carry
the film, STANDARD for the rest), its camera move, whether people, water or fast motion are
in frame, its seconds - and the studio buys the CHEAPEST model in the Owner's allowed set
whose documented or measured capability covers that need. A premium model is bought only
where the need requires it; a card, a black screen or a still the Owner accepted with a local
camera move costs no motion credit at all.

Everything here is pure arithmetic over the published price table and capability records:
no provider, no socket, no credit. Prices are the table's (config/runway_prices.json).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.media import cost_plan
from app.media.production_policy import (
    LOCAL_MOVE,
    FailureRecord,
    ModelCapability,
    SceneNeed,
    classify_failure,
    need_from_scene,
    plan_scene_models,
    replan_after_failure,
)

# ------------------------------------------------------------------------------ fixtures

#: Capability records as a steward's research and the studio's own results would leave them.
#: Durations are the vendor's contracts; quality is 0..1 on the catalogue's scale.
CAPS = (
    ModelCapability(
        model_id="seedance2_5",
        quality=0.95,
        seconds={"min": 4, "max": 30},
        ratios=("1080:1920", "720:1280"),
    ),
    ModelCapability(
        model_id="seedance2",
        quality=0.88,
        seconds={"min": 4, "max": 30},
        ratios=("1080:1920", "720:1280"),
    ),
    ModelCapability(
        model_id="veo3.1",
        quality=0.92,
        seconds={"values": [4, 6, 8]},
        ratios=("1080:1920", "720:1280"),
    ),
    ModelCapability(
        model_id="veo3.1_fast",
        quality=0.84,
        seconds={"values": [4, 6, 8]},
        ratios=("1080:1920", "720:1280"),
        need_quality={"people": 0.70},
    ),
    ModelCapability(
        model_id="wan3",
        quality=0.82,
        seconds={"min": 2, "max": 10},
        ratios=("auto_1080p", "720:1280"),
        need_quality={"water": 0.72},
    ),
    ModelCapability(
        model_id="gen4_turbo",
        quality=0.70,
        seconds={"values": [5, 10]},
        ratios=("720:1280",),
    ),
)

TABLE = cost_plan.load_price_table()


def film() -> list[SceneNeed]:
    """Seven scenes: a hero hook, landscapes, people, a card, a long shot and a black end."""
    return [
        SceneNeed(1, tier="HERO", seconds=5.0, camera_move="aerial drift forward"),
        SceneNeed(2, seconds=4.4, camera_move="slow pan right"),
        SceneNeed(3, seconds=5.0, camera_move="slow push-in", people=True),
        SceneNeed(4, kind="DATA_CARD", seconds=5.0),
        SceneNeed(5, seconds=12.0, camera_move="slow pull-back"),
        SceneNeed(6, seconds=5.0, camera_move="slow pan left", people=True),
        SceneNeed(7, kind="BLACK", seconds=3.0),
    ]


def scene(plan: dict, index: int) -> dict:
    return next(s for s in plan["scenes"] if s["scene_index"] == index)


# --------------------------------------------------- 1. the cheapest capable model per scene


def test_the_cheapest_capable_model_is_chosen_per_scene():
    plan = plan_scene_models(film(), CAPS, table=TABLE)

    # A landscape needs STANDARD (0.80): veo3.1_fast reaches 0.84 and costs 6 s x 10 = 60.
    # 4.4 s is billed as veo's next legal length, 6 s, never rounded down to 4.
    two = scene(plan, 2)
    assert (two["model_id"], two["billed_seconds"], two["credits"]) == ("veo3.1_fast", 6, 60)
    assert two["decided_by"] == "policy"
    assert "cel mai ieftin" in two["reason_ro"]

    # People in frame: veo3.1_fast is documented at 0.70 on people, so the scene goes to the
    # next cheapest model that covers them, wan3 (5 s x 20 = 100), and says why.
    three = scene(plan, 3)
    assert (three["model_id"], three["credits"]) == ("wan3", 100)
    excluded = {e["model_id"]: e["why_ro"] for e in three["excluded"]}
    assert "oameni" in excluded["veo3.1_fast"]

    # 12 s in one shot: veo (max 8) and wan3 (max 10) cannot hold it; seedance2 at 40/s is
    # cheaper than seedance2_5 at 68/s.
    five = scene(plan, 5)
    assert (five["model_id"], five["credits"]) == ("seedance2", 480)
    assert "12 s" in {e["model_id"]: e["why_ro"] for e in five["excluded"]}["veo3.1_fast"]

    # Composed scenes never reach a model and cost nothing.
    for index in (4, 7):
        composed = scene(plan, index)
        assert composed["model_id"] is None
        assert composed["credits"] == 0 and composed["still_credits"] == 0
        assert composed["status"] == "COMPOSED"

    # Different scenes, different models: there is no film-wide lock.
    assert len(plan["models"]) >= 3

    # The sheet shows the cheaper and the better alternative, with prices. gen4_turbo is
    # cheaper for scene 2 but below the tier (and cannot fill 1080x1920); wan3 is the next
    # step up in quality, at its price.
    assert two["cheaper"]["model_id"] == "gen4_turbo"
    assert two["cheaper"]["credits"] == cost_plan.price_shot("gen4_turbo", "1080p", 4.4)
    assert two["cheaper"]["why_ro"]
    assert two["better"]["model_id"] in {"wan3", "seedance2", "veo3.1", "seedance2_5"}
    assert two["better"]["quality"] > two["quality"]
    assert two["better"]["credits"] > two["credits"]


def test_only_models_in_the_owners_allowed_set_are_bought():
    allowed = {"seedance2_5", "seedance2", "veo3.1"}
    plan = plan_scene_models(film(), CAPS, allowed=allowed, table=TABLE)
    for entry in plan["scenes"]:
        assert entry["model_id"] in allowed | {None}
    # veo3.1 (6 s x 20 = 120) is now the cheapest capable for the landscape.
    assert scene(plan, 2)["model_id"] == "veo3.1"
    reasons = {e["model_id"]: e["why_ro"] for e in scene(plan, 2)["excluded"]}
    assert "aprobat" in reasons["veo3.1_fast"]


def test_a_scene_no_allowed_model_can_film_goes_to_the_owner_and_is_not_bought():
    plan = plan_scene_models(
        [SceneNeed(1, seconds=40.0, camera_move="slow push-in")], CAPS, table=TABLE
    )
    only = scene(plan, 1)
    assert only["model_id"] is None and only["status"] == "NEEDS_OWNER"
    assert only["reason_ro"].startswith("Niciun model")
    assert plan["buyable"] is False
    assert plan["to_buy"] == []


# ------------------------------------------------------------ 2. a HERO scene may go premium


def test_a_hero_scene_may_take_a_premium_model_and_a_standard_one_does_not():
    plan = plan_scene_models(film(), CAPS, table=TABLE)
    hero = scene(plan, 1)
    # HERO needs 0.93: only seedance2_5 (0.95) reaches it; veo3.1 at 0.92 does not.
    assert (hero["model_id"], hero["credits"]) == ("seedance2_5", 340)
    assert hero["tier"] == "HERO"
    assert "HERO" in hero["reason_ro"]
    assert "0,92" in {e["model_id"]: e["why_ro"] for e in hero["excluded"]}["veo3.1"]
    assert plan["hero_scene"] == 1
    assert plan["hero_credits"] == 340

    # The same shot as STANDARD is bought on the cheap capable model instead.
    ordinary = plan_scene_models(
        [SceneNeed(1, tier="STANDARD", seconds=5.0, camera_move="aerial drift forward")],
        CAPS,
        table=TABLE,
    )
    assert scene(ordinary, 1)["model_id"] == "veo3.1_fast"

    # The premium model is never bought where a cheaper one covers the need.
    for entry in plan["scenes"]:
        if entry["model_id"] == "seedance2_5":
            assert entry["tier"] == "HERO"


def test_the_tier_comes_from_the_scene_and_the_hook_is_hero_by_default():
    first = need_from_scene(
        {
            "scene_index": 1,
            "scene_kind": "LIVE",
            "duration_seconds": 4.2,
            "prompt_json": {
                "still_prompt": "Terraced fields in the Himalayan foothills under low cloud.",
                "motion_prompt": "Slow push-in. Mist drifts across the slope, gently.",
                "camera_move": "slow push-in",
            },
        },
        total_scenes=6,
    )
    assert (first.tier, first.camera_move, first.seconds) == ("HERO", "slow push-in", 4.2)
    assert not first.people

    middle = need_from_scene(
        {
            "scene_index": 3,
            "scene_kind": "LIVE",
            "duration_seconds": 5,
            "visual_prompt": "A farmer seen from behind walks beside a flooded river.",
        },
        total_scenes=6,
    )
    assert middle.tier == "STANDARD" and middle.people and middle.water

    marked = need_from_scene(
        {"scene_index": 4, "scene_kind": "LIVE", "duration_seconds": 5, "tier": "HERO"},
        total_scenes=6,
    )
    assert marked.tier == "HERO"

    card = need_from_scene({"scene_index": 5, "scene_kind": "DATA_CARD"}, total_scenes=6)
    assert card.kind == "DATA_CARD"


# ---------------------------------------------------- 3. the Owner's override on the sheet wins


def test_the_owners_per_scene_override_on_the_sheet_wins():
    policy = plan_scene_models(film(), CAPS, table=TABLE)
    owner = plan_scene_models(
        film(),
        CAPS,
        overrides={2: "seedance2_5", 6: LOCAL_MOVE},
        table=TABLE,
    )

    # His model for scene 2, although a cheaper one covers it; the cheaper one is still shown.
    two = scene(owner, 2)
    assert two["model_id"] == "seedance2_5" and two["decided_by"] == "owner"
    assert two["credits"] == cost_plan.price_shot("seedance2_5", "1080p", 4.4)
    assert "Proprietar" in two["reason_ro"]
    assert two["cheaper"]["model_id"] == "veo3.1_fast"

    # His local camera move on the approved still: the still is still bought, the motion
    # costs nothing and no adapter is ever asked for it.
    six = scene(owner, 6)
    assert six["model_id"] is None and six["status"] == "LOCAL"
    assert six["credits"] == 0
    assert six["still_credits"] == cost_plan.price_still("seedream5_pro", "2K", 2)
    assert 6 not in owner["to_buy"]
    assert "local" in six["reason_ro"]

    # The film's price moves with his choices; the other scenes do not.
    assert owner["total_credits"] == (
        policy["total_credits"] - 60 + two["credits"] - scene(policy, 6)["credits"]
    )
    for index in (1, 3, 5):
        assert scene(owner, index)["model_id"] == scene(policy, index)["model_id"]


def test_an_override_the_contract_cannot_take_is_not_bought_but_sent_back_to_him():
    plan = plan_scene_models(film(), CAPS, overrides={5: "veo3.1", 2: "unknown_x"}, table=TABLE)
    five = scene(plan, 5)
    assert five["model_id"] is None and five["status"] == "NEEDS_OWNER"
    assert "veo3.1" in five["reason_ro"] and "12 s" in five["reason_ro"]
    two = scene(plan, 2)
    assert two["status"] == "NEEDS_OWNER" and "unknown_x" in two["reason_ro"]
    assert plan["buyable"] is False
    assert 2 not in plan["to_buy"] and 5 not in plan["to_buy"]


# ------------------------------------------- 4. the total stays within the cap; the saving


def test_the_film_total_never_exceeds_the_cap_and_reports_the_saving():
    plan = plan_scene_models(film(), CAPS, table=TABLE)
    live = [s for s in plan["scenes"] if s["kind"] == "LIVE"]
    stills = sum(s["still_credits"] for s in live)
    motion = sum(s["credits"] for s in live)

    # The film is the SUM of the per-scene choices.
    assert plan["stills_credits"] == stills == 5 * 18
    assert plan["motion_credits"] == motion == 340 + 60 + 100 + 480 + 100
    assert plan["total_credits"] == stills + motion
    assert plan["hero_credits"] + plan["rest_credits"] == motion
    # The cap: the total, one redo of the dearest shot, one more round of stills.
    assert plan["cap_credits"] == plan["total_credits"] + 480 + stills
    assert plan["total_credits"] <= plan["cap_credits"]
    assert plan["committed_credits"] <= plan["cap_credits"]
    assert plan["status"] == "READY" and plan["buyable"] is True

    # Against the premium model on every LIVE scene.
    premium = stills + sum(cost_plan.price_shot("seedance2_5", "1080p", s["seconds"]) for s in live)
    assert plan["premium_credits"] == premium
    assert plan["saved_credits"] == premium - plan["total_credits"] > 0
    assert plan["saved_usd_micros"] == cost_plan.credits_to_micros(plan["saved_credits"], 0.01)
    assert plan["total_usd_micros"] == cost_plan.credits_to_micros(plan["total_credits"], 0.01)
    assert "economisește" in plan["summary_ro"]

    # The same choices priced by cost_plan.plan_film come to the same money.
    reference = cost_plan.plan_film(plan["plan_film_scenes"], table=TABLE)
    assert reference["total_credits"] == plan["total_credits"]
    assert reference["cap_credits"] == plan["cap_credits"]
    assert reference["hero_scene"] == plan["hero_scene"]


def test_a_film_over_the_owners_budget_is_not_buyable_and_nothing_is_downgraded_silently():
    policy = plan_scene_models(film(), CAPS, table=TABLE)
    tight = plan_scene_models(film(), CAPS, budget_credits=policy["total_credits"] - 1, table=TABLE)
    assert tight["status"] == "OVER_BUDGET" and tight["buyable"] is False
    assert tight["to_buy"] == []
    assert "buget" in tight["summary_ro"]
    # The HERO still asks for its premium model: the Owner decides, not a silent downgrade.
    assert scene(tight, 1)["model_id"] == "seedance2_5"


# -------------------------- 5. a failure moves only that scene; nothing is bought twice


def test_failures_are_classified_by_kind():
    safety = classify_failure("SAFETY.INPUT.IMAGE")
    assert (safety.kind, safety.action, safety.blame_model) == ("SAFETY", "move_scene", False)
    assert classify_failure("INPUT_PREPROCESSING.SAFETY.THIRD_PARTY").kind == "SAFETY"

    contract = classify_failure(None, http_status=400, detail="duration: must be one of 4, 6, 8")
    assert (contract.kind, contract.action) == ("CONTRACT", "move_scene")
    assert contract.detail == "duration: must be one of 4, 6, 8"
    again = classify_failure(None, http_status=400, detail="ratio", previous="CONTRACT")
    assert (again.kind, again.action, again.stop_step) == ("CONTRACT", "stop_step", True)

    broke = classify_failure(None, http_status=400, detail="Not enough credits: insufficient")
    assert (broke.kind, broke.stop_step) == ("ACCOUNT", True)
    assert classify_failure(None, http_status=401).kind == "ACCOUNT"

    busy = classify_failure("THIRD_PARTY.UNAVAILABLE")
    assert (busy.kind, busy.action) == ("TRANSIENT", "retry_same")
    assert classify_failure("INTERNAL").kind == "TRANSIENT"
    bad = classify_failure("INTERNAL.BAD_OUTPUT.CODE01")
    assert (bad.kind, bad.action) == ("BAD_OUTPUT", "retry_same")
    assert classify_failure("SOMETHING.NEW").action == "needs_owner"
    # The detail kept is sanitised and bounded.
    long = classify_failure(None, http_status=400, detail="x" * 900)
    assert len(long.detail or "") <= 500
    for verdict in (safety, contract, broke, busy, bad):
        assert verdict.reason_ro


def test_a_failure_moves_only_that_scene_and_nothing_is_bought_twice():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    assert scene(first, 3)["model_id"] == scene(first, 6)["model_id"] == "wan3"

    # Scenes 1 and 2 are bought and accepted; scene 3's wan3 shot is refused for safety
    # (and a refusal is paid like a success).
    spent = first["stills_credits"] + 340 + 60 + 100
    failure = classify_failure("INPUT_PREPROCESSING.SAFETY.THIRD_PARTY")
    again = replan_after_failure(
        first,
        film(),
        CAPS,
        scene_index=3,
        failure=failure,
        bought=(1, 2),
        spent_credits=spent,
        table=TABLE,
    )

    three = scene(again, 3)
    # The next-cheapest capable model for people at 5 s: veo3.1, 6 s x 20 = 120.
    assert (three["model_id"], three["credits"]) == ("veo3.1", 120)
    assert "wan3" in {e["model_id"] for e in three["excluded"]}
    assert three["failures"][0]["kind"] == "SAFETY"

    # Only scene 3 moved. Scene 6 keeps wan3: a refusal on one scene blames nothing else.
    for index in (1, 2, 5, 6):
        assert scene(again, index)["model_id"] == scene(first, index)["model_id"]
    assert scene(again, 6)["model_id"] == "wan3"

    # Nothing is bought twice: the accepted scenes are frozen and out of the purchase list.
    assert scene(again, 1)["status"] == scene(again, 2)["status"] == "BOUGHT"
    assert again["to_buy"] == [3, 5, 6]
    assert again["remaining_credits"] == 120 + 480 + 100
    assert again["spent_credits"] == spent
    # The cap approved with the first sheet still binds, and the move fits under it.
    assert again["cap_credits"] == first["cap_credits"]
    assert again["committed_credits"] == spent + 700 <= again["cap_credits"]
    assert again["status"] == "READY"


def test_a_move_that_would_break_the_cap_sends_that_scene_to_the_owner():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    spent = first["cap_credits"] - (480 + 100 + 60)  # room for 5 and 6, not for veo3.1 on 3
    again = replan_after_failure(
        first,
        film(),
        CAPS,
        scene_index=3,
        failure=classify_failure(None, http_status=400, detail="bad ratio"),
        bought=(1, 2),
        spent_credits=spent,
        table=TABLE,
    )
    three = scene(again, 3)
    assert three["status"] == "NEEDS_OWNER" and "plafon" in three["reason_ro"]
    assert again["to_buy"] == [5, 6]
    assert again["committed_credits"] <= again["cap_credits"]


def test_a_second_safety_refusal_sends_the_scene_back_to_the_stills_gate():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    history = {3: [FailureRecord(model_id="wan3", kind="SAFETY")]}
    once = plan_scene_models(film(), CAPS, failures=history, table=TABLE)
    assert scene(once, 3)["model_id"] == "veo3.1"
    twice = replan_after_failure(
        once,
        film(),
        CAPS,
        scene_index=3,
        failure=classify_failure("SAFETY.INPUT.IMAGE"),
        failures=history,
        bought=(1, 2),
        spent_credits=first["stills_credits"] + 400 + 120,
        table=TABLE,
    )
    three = scene(twice, 3)
    assert three["status"] == "NEEDS_STILL" and three["model_id"] is None
    assert "imagin" in three["reason_ro"]
    assert 3 not in twice["to_buy"]


def test_a_transient_failure_retries_the_same_model_once_then_asks_the_owner():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    busy = classify_failure("THIRD_PARTY.UNAVAILABLE")
    retry = replan_after_failure(
        first, film(), CAPS, scene_index=5, failure=busy, bought=(1, 2), table=TABLE
    )
    assert scene(retry, 5)["model_id"] == "seedance2" and 5 in retry["to_buy"]
    assert scene(retry, 5)["retry"] is True
    stuck = replan_after_failure(
        retry,
        film(),
        CAPS,
        scene_index=5,
        failure=busy,
        failures={5: [FailureRecord(model_id="seedance2", kind="TRANSIENT")]},
        bought=(1, 2),
        table=TABLE,
    )
    assert scene(stuck, 5)["status"] == "NEEDS_OWNER"
    assert 5 not in stuck["to_buy"]


def test_an_account_failure_stops_the_step():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    stopped = replan_after_failure(
        first,
        film(),
        CAPS,
        scene_index=3,
        failure=classify_failure(None, http_status=402, detail="insufficient credits"),
        bought=(1, 2),
        table=TABLE,
    )
    assert stopped["status"] == "STOPPED" and stopped["to_buy"] == []
    assert stopped["buyable"] is False


def test_two_contract_refusals_in_a_row_stop_the_step():
    first = plan_scene_models(film(), CAPS, table=TABLE)
    one = replan_after_failure(
        first,
        film(),
        CAPS,
        scene_index=3,
        failure=classify_failure(None, http_status=400, detail="ratio"),
        bought=(1, 2),
        table=TABLE,
    )
    assert one["status"] == "READY" and one["last_failure_kind"] == "CONTRACT"
    two = replan_after_failure(
        one,
        film(),
        CAPS,
        scene_index=5,
        failure=classify_failure(
            None, http_status=400, detail="duration", previous=one["last_failure_kind"]
        ),
        bought=(1, 2),
        table=TABLE,
    )
    assert two["status"] == "STOPPED" and two["to_buy"] == []


# ------------------------------------------- what the studio has learnt about each model


def test_a_models_failure_history_on_a_kind_of_scene_counts_against_it():
    worn = tuple(
        ModelCapability(**{**c.as_dict(), "failures": {"people": (2, 3)}})
        if c.model_id == "wan3"
        else c
        for c in CAPS
    )
    plan = plan_scene_models(film(), worn, table=TABLE)
    three = scene(plan, 3)
    assert three["model_id"] == "veo3.1"
    assert "2 din 3" in {e["model_id"]: e["why_ro"] for e in three["excluded"]}["wan3"]
    # A landscape does not carry the people history.
    assert scene(plan_scene_models([SceneNeed(1, seconds=5.0, water=True)], worn, table=TABLE), 1)[
        "model_id"
    ] in {"wan3", "veo3.1_fast"}


def test_capabilities_are_read_from_the_catalogue_and_the_studios_own_results(engine):
    from app.integrations.models import Integration, ModelOutcome, ProviderResource
    from app.media.production_policy import scene_model_capabilities
    from app.services import append_event, utc_now
    from sqlalchemy.orm import Session

    integration_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", integration_id, 1, {}, "t"
        )
        session.add(
            Integration(
                id=integration_id,
                kind="runway",
                name="runway",
                config={},
                encrypted_secrets="",
                secret_fields=[],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.flush()
        for remote_id, status, quality, durations in (
            ("wan3", "PRODUCTION", 0.82, {"min": 2, "max": 10}),
            ("veo3.1_fast", "PREFERRED", 0.84, [4, 6, 8]),
            ("gen4_turbo", "DEPRECATED", 0.7, [5, 10]),
            ("new_model", "QUARANTINE", 0.99, [5]),
        ):
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    resource_type="MODEL",
                    remote_id=remote_id,
                    name=remote_id,
                    api_metadata={
                        "tasks": ["image_to_video"],
                        "ratios": {"image_to_video": ["1080:1920"]},
                        "durations": {"image_to_video": durations},
                    },
                    api_available=True,
                    last_seen_at=utc_now(),
                    # A steward's sourced research: it outranks config/film_models.json.
                    capabilities={
                        "basis": "steward",
                        "sources": ["https://docs.dev.runwayml.com/guides/models/"],
                        "quality_score": quality,
                        "need_quality": {"people": 0.7},
                        "camera_moves": ["static", "slow push-in"],
                    },
                    production_status=status,
                    metadata_version=1,
                )
            )
        for accepted, category in ((False, "PEOPLE"), (False, "people"), (True, "GENERAL")):
            session.add(
                ModelOutcome(
                    id=str(uuid4()),
                    integration_id=integration_id,
                    remote_id="wan3",
                    purpose="video",
                    run_kind="PRODUCTION",
                    environment="PRODUCTION",
                    scene_category=category,
                    accepted=accepted,
                    failure_kind=None if accepted else "QUALITY",
                    created_at=utc_now(),
                )
            )

    with Session(engine) as session:
        caps = {c.model_id: c for c in scene_model_capabilities(session, integration_id)}

    assert set(caps) == {"wan3", "veo3.1_fast", "new_model"}  # the retired one is gone
    assert caps["new_model"].admitted is False
    assert caps["wan3"].admitted and caps["veo3.1_fast"].admitted
    assert caps["veo3.1_fast"].seconds == {"values": [4, 6, 8]}
    assert caps["wan3"].seconds == {"min": 2, "max": 10}
    assert caps["wan3"].ratios == ("1080:1920",)
    assert caps["wan3"].tasks == ("image_to_video",)
    # The steward's people figure; the needs he did not research come from the documented file.
    assert caps["wan3"].need_quality["people"] == 0.7
    assert set(caps["wan3"].need_quality) == {"people", "water", "fast_motion"}
    assert caps["wan3"].camera_moves == ("static", "slow push-in")
    assert caps["wan3"].failures["people"] == (2, 2)
    # Three judged generations: its own results now weigh on the documented score.
    assert caps["wan3"].quality_source == "măsurat"
    assert caps["wan3"].quality < 0.82
    assert caps["veo3.1_fast"].quality_source == "documentat"

    # A model outside production is never bought, whatever its score.
    plan = plan_scene_models(
        [SceneNeed(1, seconds=5.0, camera_move="slow push-in")],
        list(caps.values()),
        table=TABLE,
    )
    assert scene(plan, 1)["model_id"] != "new_model"
    why = {e["model_id"]: e["why_ro"] for e in scene(plan, 1)["excluded"]}
    assert "producție" in why["new_model"]
    # Nor is a model the Owner's allowed set (config/film_models.json) does not name.
    assert caps["new_model"].owner_allowed is False
    assert "aprobat" in why["new_model"]


def test_the_policy_module_calls_no_provider(monkeypatch):
    """Planning is arithmetic: it may not import an adapter or open a socket."""
    import app.media.production_policy as policy

    source = open(policy.__file__, encoding="utf-8").read()
    assert "app.providers" not in source
    assert "httpx" not in source
    pytest.importorskip("app.media.cost_plan")
