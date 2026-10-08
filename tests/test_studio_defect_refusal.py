"""A vendor 400 that names our own request's parameters is the studio's defect, not the model's.

2026-10-03 20:56 UTC, the Nepal film (storyboard 81438d13): its test shot on wan3 was refused by
Runway with «Keyframe image-to-video requests must use `auto_480p`, `auto_720p`, or
`auto_1080p` because the output aspect ratio follows the first frame.» That is our request
shape (fixed since in `runway.pick_ratio`), yet the refusal was classed CONTRACT: wan3 (0.98,
above the 0.93 hero threshold) was dropped for the scene and the scene was held for the Owner
with seedance2_5 at 0.75 and 340 credits as the «choice». Earlier the same day stills were
refused for a reference picture over Runway's 5 MB data-URI limit (fixed in 626b59d), and those
scenes were held too.

Now such a refusal is STUDIO_DEFECT: the scene is not held for him, the model is not dropped,
the step stops (the next request would carry the same defect), and a startup or watchdog pass
releases the holds those refusals left before, once, on the books. Nothing is bought.

Every provider is faked; no credit is spent.
"""

from __future__ import annotations

from app.media import production_policy
from app.media.assembler import (
    STUDIO_DEFECT_RELEASED_EVENT,
    motion_plan,
    release_studio_defect_holds,
    take_failure,
)
from app.media.models import SceneTake
from app.media.production_policy import classify_failure
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, approved, by_scene
from test_film_costing import a_film as film_with_stills

KEYFRAME = (
    "Keyframe image-to-video requests must use `auto_480p`, `auto_720p`, or `auto_1080p` "
    "because the output aspect ratio follows the first frame."
)
TOO_LARGE = (
    "Validation of body failed; referenceImages.[0]..uri: Data URI is too large: 8.6MB "
    "exceeds the 5MB limit. Upload the file and pass the returned URI instead."
)


def keyframe_refusal() -> MediaProviderError:
    return MediaProviderError(
        "api.dev.runwayml.com refused the request (HTTP 400)",
        http_status=400,
        detail=KEYFRAME,
    )


def events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == event_type)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


# --------------------------------------------------------------------- 1. the classification


def test_a_400_naming_our_request_parameters_is_a_studio_defect():
    for detail in (KEYFRAME, TOO_LARGE):
        verdict = classify_failure("HTTP_400", http_status=400, detail=detail)
        assert verdict.kind == "STUDIO_DEFECT", detail
        assert verdict.blame_model is False
        assert verdict.stop_step is True
        assert not verdict.move_scene
        assert "studioului" in verdict.reason_ro
    # Even right after a contract refusal: the request, not the model, is wrong.
    again = classify_failure(None, http_status=400, detail=KEYFRAME, previous="CONTRACT")
    assert again.kind == "STUDIO_DEFECT"


def test_a_400_that_names_no_studio_parameter_stays_a_contract_refusal():
    verdict = classify_failure(
        None, http_status=400, detail="Validation of body failed; ratio: Invalid enum value"
    )
    assert (verdict.kind, verdict.action) == ("CONTRACT", "move_scene")


def test_a_refused_take_of_ours_says_nothing_about_the_scene():
    row = SceneTake(
        id="t",
        storyboard_id="s",
        scene_number=1,
        kind="test_shot",
        prompt_hash="h",
        model_id="wan3",
        resolution="1080:1920",
        status="REFUSED",
        failure_code="HTTP_400",
        failure_detail=KEYFRAME,
    )
    assert take_failure(row) is None


# ------------------------------------------------------------------ 2. the step, from now on


def test_a_keyframe_refusal_neither_holds_the_scene_nor_drops_its_model(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account, refuse={1: keyframe_refusal()})

    result = approved(engine, storyboard_id, tmp_path, "test_shot", Models(spy), account)

    scene = by_scene(result)[1]
    assert scene["status"] == "NOT_BOUGHT"
    assert scene["failure_kind"] == "STUDIO_DEFECT"
    assert "studioului" in result["stopped"]
    assert len(spy.asked) == 1, "the same defective request was sent twice"
    assert result["spent_credits_quoted"] == 0
    # No hold for the Owner: the scene is planned again on its own model.
    holds = [
        e
        for e in events(engine, "media.motion_needs_owner")
        if e.payload.get("holds") and e.payload.get("scene_number") == 1
    ]
    assert holds == []
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert plan["steps"]["test_shot"]["to_buy"] == [1]
    assert plan["scenes"][0]["model_id"] == "seedance2_5"


# ------------------------------------------------- 3. the holds such refusals left before


def _held_as_on_10_03(engine, storyboard_id, tmp_path, monkeypatch) -> None:
    """The test shot refused exactly as on 2026-10-03, classified as it was then (CONTRACT)."""
    monkeypatch.setattr(production_policy, "STUDIO_DEFECT_PATTERNS", ())
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account, refuse={1: keyframe_refusal()})
    result = approved(engine, storyboard_id, tmp_path, "test_shot", Models(spy), account)
    assert by_scene(result)[1]["failure_kind"] == "CONTRACT"
    monkeypatch.undo()


def test_an_old_hold_caused_by_our_own_request_is_released_once(engine, tmp_path, monkeypatch):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    _held_as_on_10_03(engine, storyboard_id, tmp_path, monkeypatch)
    held = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert held["steps"]["test_shot"]["to_buy"] == []

    released = release_studio_defect_holds(engine, correlation_id="watchdog-pass")

    assert [(item["storyboard_id"], item["scene_number"]) for item in released] == [
        (storyboard_id, 1)
    ]
    (event,) = events(engine, STUDIO_DEFECT_RELEASED_EVENT)
    assert event.payload["scene_number"] == 1
    assert event.payload["failure_detail"].startswith("Keyframe image-to-video")
    assert "Proprietar" in event.payload["reason_ro"]
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert plan["steps"]["test_shot"]["to_buy"] == [1]
    assert plan["scenes"][0]["model_id"] == "seedance2_5"

    # Idempotent: a second pass finds nothing and writes nothing.
    assert release_studio_defect_holds(engine, correlation_id="watchdog-pass") == []
    assert len(events(engine, STUDIO_DEFECT_RELEASED_EVENT)) == 1


def test_a_genuine_contract_hold_is_left_to_the_owner(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)
    refusal = MediaProviderError(
        "api.dev.runwayml.com refused the request (HTTP 400)",
        http_status=400,
        detail="Validation of body failed",
        issues=[{"path": "duration", "message": "Invalid enum value"}],
    )
    spy = SpyVideo("seedance2_5", account, refuse={1: refusal})
    approved(engine, storyboard_id, tmp_path, "test_shot", Models(spy), account)

    assert release_studio_defect_holds(engine, correlation_id="watchdog-pass") == []
    assert events(engine, STUDIO_DEFECT_RELEASED_EVENT) == []


def test_the_watchdog_pass_releases_such_a_hold(engine, settings, tmp_path, monkeypatch):
    from app.workflows.watchdog import run_watchdog

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    _held_as_on_10_03(engine, storyboard_id, tmp_path, monkeypatch)

    result = run_watchdog(
        engine, settings, correlation_id="watchdog", collector_for=lambda _t: None
    )

    assert [item["scene_number"] for item in result["defect_holds"]["released"]] == [1]
    assert motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["steps"]["test_shot"][
        "to_buy"
    ] == [1]
