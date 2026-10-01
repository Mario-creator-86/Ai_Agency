"""The shooting sheet, finished: plan to master on the Owner's clicks, and no money hole.

- (a) POST .../steps/assemble assembles the film from its takes (`assemble_from_takes`, which
  runs `require_chosen_fallbacks` and books the measured spend), voices the narration (its own
  line on the sheet and inside the hashed plan, asked through `may_act` bound to the
  plan_hash), runs quality control and writes the QC letter; 409 with Romanian reasons, scene
  by scene, when a filmed scene has no accepted take and no LOCAL_MOVE chosen by him.
- (b) The legacy whole-film path (POST /media/render/{id}, the TEST daily stage) refuses
  whenever it would reach a real paid vendor adapter, in every environment: the real adapter
  classes are constructed here and never called.
- (c) Every bought step is booked once, inside `run_sheet_step`, whoever pressed it.
- (d) A newer sheet's question withdraws the older, unanswerable one, with a reason.
- (e) The sheet carries shot sizes, the SAFETY suggestion, the redo prices with their hashes,
  the Owner's catalogue choices and the narration price.
- (f) prompt_lint counts the Romanian way.

Every provider is faked; no socket is opened and no credit is spent.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.economy.prices import PriceCommand, set_price
from app.media.models import SceneTake, StoryboardScene, VideoRenderJob
from app.media.production_policy import LOCAL_MOVE, load_film_models
from app.media.prompt_lint import Finding, lint_motion_prompt, lint_still_prompt, summary_ro
from app.media.shooting_sheet import (
    SheetStepRefused,
    build_sheet,
    may_spend_step,
    run_sheet_step,
    set_scene_model,
)
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.services import append_event, pending_approvals
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, VEO_FAST, Account, Models, SpyVideo
from test_film_costing import a_film as film_with_stills
from test_stills_stage import SpyStills
from test_stills_stage import a_film as film_without_stills

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def sheet_url(storyboard_id: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet"


def step_url(storyboard_id: str, step: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/steps/{step}"


def wire(client, tmp_path: Path, **state: Any) -> None:
    app_state = client.app.app.state
    app_state.media_storage_root = tmp_path / "media"
    app_state.scene_model_capabilities = state.pop("capabilities", [SEEDANCE])
    for name, value in state.items():
        setattr(app_state, name, value)


def in_environment(engine, environment: str, mode: str | None = None) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = environment
        if mode:
            policy.autonomy_mode = mode


def approvals(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at)))
        session.expunge_all()
        return rows


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


def jobs(engine) -> list[VideoRenderJob]:
    with Session(engine) as session:
        rows = list(session.scalars(select(VideoRenderJob)))
        session.expunge_all()
        return rows


def provider_costs(engine) -> list[Any]:
    from app.economy.models import ProviderCostRecord

    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
        session.expunge_all()
        return rows


def narration_price(engine, usd: str = "0.30") -> None:
    """The Owner's ElevenLabs price per thousand characters, as his price form writes it."""
    set_price(
        engine,
        PriceCommand(
            command_id=uuid4(),
            provider_kind="elevenlabs",
            resource="*",
            unit="per_1k_characters",
            usd=usd,
        ),
    )


# ------------------------------------------------------------------- (f) Romanian plurals


def _findings(blocks: int, warns: int) -> list[Finding]:
    return [Finding("X", "BLOCK", 1, "e", "Primul.")] * blocks + [
        Finding("Y", "WARN", 1, "e", "w")
    ] * warns


def test_the_lint_summary_counts_blocks_and_warnings_the_romanian_way():
    assert summary_ro(_findings(1, 1)).startswith("Prompturile au 1 blocaj și 1 avertisment.")
    assert summary_ro(_findings(2, 3)).startswith("Prompturile au 2 blocaje și 3 avertismente.")
    assert summary_ro(_findings(20, 21)).startswith(
        "Prompturile au 20 de blocaje și 21 de avertismente."
    )
    assert summary_ro(_findings(101, 0)).startswith("Prompturile au 101 blocaje și 0 avertismente.")


def test_the_counts_inside_the_lint_messages_agree_with_their_numbers():
    one = {f.code: f.message_ro for f in lint_still_prompt("River.", scene=1)}
    assert "are 1 cuvânt (" in one["STILL_LENGTH"]
    many = {f.code: f.message_ro for f in lint_still_prompt(" ".join(["river"] * 21), scene=1)}
    assert "are 21 de cuvinte (" in many["STILL_LENGTH"]
    excluded = {
        f.code: f.message_ro
        for f in lint_still_prompt("A river valley at dusk, no people, no text, no logo.", scene=1)
    }
    assert "are 3 excluderi;" in excluded["TOO_MANY_EXCLUSIONS"]
    moves = {
        f.code: f.message_ro
        for f in lint_motion_prompt("Slow dolly in, then a pan left over the river.", scene=1)
    }
    assert "are 2 mișcări de cameră (" in moves["CAMERA_COUNT"]
    assert "are 10 cuvinte (" in moves["MOTION_LENGTH"]


# ------------------------------------------------------------------- (b) the money hole


def test_every_real_paid_adapter_class_is_recognised_constructed_and_never_called(runway_api):
    """The marker is where an adapter class comes from: every module under app/providers
    that is not one of the free ones is a vendor, so a sixth vendor is paid until someone
    decides otherwise in review. Constructing an adapter opens no connection."""
    import importlib
    import pkgutil

    import app.providers as providers
    from app.media.factory import (
        FREE_PROVIDER_MODULES,
        is_paid_vendor_adapter,
        is_paid_vendor_class,
    )
    from app.providers.deterministic_media import (
        DeterministicTTSAdapter,
        DeterministicVisualAdapter,
    )
    from app.providers.elevenlabs import ElevenLabsTTSAdapter
    from app.providers.media_base import ImageProvider, TTSProvider, VideoProvider
    from app.providers.openai_media import OpenAIImageAdapter
    from app.providers.runway import RunwayImageAdapter, RunwayVideoAdapter

    real = [
        RunwayImageAdapter("test-key", runway_api.image_model, {}),
        RunwayVideoAdapter("test-key", runway_api.video_models[0], {}),
        OpenAIImageAdapter("test-key", "gpt-image-1"),
        ElevenLabsTTSAdapter("test-key", "voice-id", "eleven_multilingual_v2"),
    ]
    for adapter in real:
        assert is_paid_vendor_adapter(adapter), type(adapter).__name__
    for free in (DeterministicVisualAdapter(), DeterministicTTSAdapter(), SpyStills(), None):
        assert not is_paid_vendor_adapter(free)
    assert not is_paid_vendor_adapter(SpyVideo("seedance2_5", Account(1)))
    assert runway_api.calls == [], "constructing an adapter called its vendor"

    # Every concrete media adapter the vendor modules define is recognised, by its class.
    for info in pkgutil.iter_modules(providers.__path__, "app.providers."):
        module = importlib.import_module(info.name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == info.name
                and issubclass(value, ImageProvider | TTSProvider | VideoProvider)
            ):
                expected = info.name not in FREE_PROVIDER_MODULES
                assert is_paid_vendor_class(value) is expected, value

    # A new vendor nobody listed is paid, not free: it cannot slip past by being new.
    newcomer = type("NewVendorVideo", (VideoProvider,), {"__module__": "app.providers.newvendor"})
    assert is_paid_vendor_class(newcomer)


def test_the_render_button_in_test_refuses_a_real_vendor_and_asks_it_nothing(
    client, engine, headers, tmp_path, monkeypatch, runway_api
):
    from app.providers.runway import RunwayImageAdapter
    from test_phase5_media import _approved_storyboard, _planner

    storyboard_id = _approved_storyboard(engine, tmp_path)
    real = RunwayImageAdapter("test-key", runway_api.image_model, {})
    monkeypatch.setattr("app.media.router.render_plan", _planner([real], lambda scene: None))
    rendered: list[Any] = []
    monkeypatch.setattr(
        "app.media.router.assemble_video_job", lambda *a, **k: rendered.append(k) or {}
    )

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "UseShootingSheet"
    assert detail["message"].startswith("Folosește foaia de filmare")
    assert "RUNWAY_IMAGES" in detail["paid_vendors"]
    assert detail["sheet_url"] == sheet_url(storyboard_id)
    assert rendered == [] and runway_api.calls == [] and jobs(engine) == []


def test_a_real_motion_model_chosen_mid_render_is_refused_before_it_is_used(
    client, engine, headers, tmp_path, monkeypatch, runway_api
):
    """The motion model is chosen per scene inside the render; the guard sits on that
    choice, so a real adapter is refused before a single call to it."""
    from app.providers.runway import RunwayVideoAdapter
    from test_phase5_media import _approved_storyboard, _planner

    storyboard_id = _approved_storyboard(engine, tmp_path)
    real = RunwayVideoAdapter("test-key", runway_api.video_models[0], {})
    monkeypatch.setattr("app.media.router.render_plan", _planner(None, lambda scene: None))
    monkeypatch.setattr(
        "app.media.router.motion_for_scene",
        lambda *a, **k: (real, {"model_id": real.model, "reason": "the router's choice"}),
    )
    chosen: list[Any] = []

    def render(engine_, board, correlation, **kwargs):
        chosen.append(kwargs["motion_chooser"]({"scene_index": 1}, "HERO", 5.0, 1.0, ()))
        raise AssertionError("the render went on after a real model was chosen")

    monkeypatch.setattr("app.media.router.assemble_video_job", render)

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "UseShootingSheet" and "RUNWAY" in " ".join(detail["paid_vendors"])
    assert chosen == [] and runway_api.calls == []


def test_the_test_day_refuses_a_real_vendor_on_the_whole_film_path_and_lets_its_hold_go(
    engine, settings, tmp_path, monkeypatch, runway_api
):
    from app.economy.models import SpendReservation
    from app.providers.elevenlabs import ElevenLabsTTSAdapter
    from app.runbook import stages
    from test_daily_run_stages import (
        _approved_board,
        _autonomy_on,
        _media_stage_with_a_fake_camera,
    )

    _autonomy_on(engine)
    _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)
    voice = ElevenLabsTTSAdapter("test-key", "voice-id", "eleven_multilingual_v2")
    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board: {
            "image": None,
            "tts_for_scene": lambda *a: voice,
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
    )

    outcome = stages._media(engine, settings, None, None)

    assert rendered == [], "the whole-film path rendered with a real voice"
    assert outcome["status"] == "SKIPPED", outcome
    assert "Folosește foaia de filmare" in outcome["reason"]
    assert outcome["artefacts"]["use_the_sheet"][0]["paid_vendors"] == ["ELEVENLABS"]
    with Session(engine) as session:
        (hold,) = session.scalars(select(SpendReservation)).all()
        assert hold.status == "RELEASED"
    assert runway_api.calls == []


# ---------------------------------------------------- (c) one booking per bought step


@requires_ffmpeg
def test_the_owners_own_step_is_booked_once_and_the_day_does_not_book_it_again(
    engine, settings, tmp_path, monkeypatch
):
    import app.economy.services as economy
    from app.runbook import stages

    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    booked: list[str] = []
    original = economy.record_provider_cost

    def counting(*args: Any, **kwargs: Any) -> Any:
        booked.append(kwargs["external_reference"])
        return original(*args, **kwargs)

    monkeypatch.setattr(economy, "record_provider_cost", counting)
    context = {
        "capabilities": [SEEDANCE],
        "account": account,
        "adapter_for_model": models,
        "storage_root": tmp_path / "media",
        "environment": "TEST",
    }
    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    with pytest.raises(SheetStepRefused) as asked:
        run_sheet_step(engine, storyboard_id, "test_shot", plan_hash, correlation_id="c", **context)
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")

    result = run_sheet_step(
        engine, storyboard_id, "test_shot", plan_hash, correlation_id="c", **context
    )

    assert result["booked"] == {"step": "test_shot", "credits": 340.0, "usd": 3.4}
    (cost,) = provider_costs(engine)
    assert cost.external_reference.startswith(f"foaie:{storyboard_id}:test_shot:")
    assert cost.attribution_json["measured"] is True and cost.usd_micros == 3_400_000
    assert booked == [cost.external_reference]
    assert not hasattr(stages, "_book_step"), "the day still books a step of its own"

    # The day climbs the same sheet: it buys nothing new here (the hero waits for his look),
    # and what it reports as booked is the step's own booking, not a second row.
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": SpyStills(balance=10_000),
        "account": account,
        "adapter_for_model": models,
        "resolution": "1080p",
        "storage_root": tmp_path / "media",
    }
    film = stages._film_staircase(engine, settings, None, storyboard_id, wiring, "TEST", "c2")
    assert film["status"] in ("WAITING", "ASKED"), film
    assert len(provider_costs(engine)) == 1 and len(booked) == 1


def test_the_budget_check_of_a_step_is_public_and_says_why_in_romanian(engine):
    from app.economy.budget import BudgetCommand, set_budget

    assert may_spend_step(engine, 1_000_000) is None
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    period, reason = may_spend_step(engine, 3_400_000)
    assert period == "DAILY" and reason.startswith("Bugetul zilnic de 1")


# ------------------------------------------------------ (d) the old question is withdrawn


def test_a_newer_sheets_question_withdraws_the_older_one_with_a_romanian_reason(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    images = SpyStills(balance=10_000)
    context = {"capabilities": [SEEDANCE], "image_adapter": images, "environment": "TEST"}
    first = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    with pytest.raises(SheetStepRefused) as old:
        run_sheet_step(
            engine, storyboard_id, "stills", first["sheet_hash"], correlation_id="a", **context
        )
    set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")
    second = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert second["sheet_hash"] != first["sheet_hash"]

    with pytest.raises(SheetStepRefused) as new:
        run_sheet_step(
            engine, storyboard_id, "stills", second["sheet_hash"], correlation_id="b", **context
        )

    assert new.value.status == "NEEDS_APPROVAL"
    assert new.value.approval_id != old.value.approval_id
    assert new.value.withdrawn == [old.value.approval_id]
    assert new.value.as_dict()["withdrawn"] == [old.value.approval_id]
    rows = {row.id: row for row in approvals(engine)}
    stale = rows[old.value.approval_id]
    assert stale.result == "EXPIRED" and stale.consumed_at is None
    assert "foaie de filmare mai nouă" in stale.note
    assert [a.id for a in pending_approvals(engine)] == [new.value.approval_id]
    (withdrawn,) = events(engine, "governance.approval_withdrawn")
    assert withdrawn.aggregate_id == old.value.approval_id
    assert withdrawn.payload["replaced_by"] == new.value.approval_id
    assert images.asked == []

    # Asking again about the same sheet withdraws nothing more.
    with pytest.raises(SheetStepRefused) as same:
        run_sheet_step(
            engine, storyboard_id, "stills", second["sheet_hash"], correlation_id="c", **context
        )
    assert same.value.approval_id == new.value.approval_id and same.value.withdrawn == []
    assert len(events(engine, "governance.approval_withdrawn")) == 1


# ----------------------------------------------------- (e) what the sheet carries now


def test_the_sheet_carries_shot_sizes_the_safety_move_redo_prices_and_the_owners_catalogue(
    engine, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        ).one()
        row.prompt_json = {**dict(row.prompt_json), "shot_size": "wide"}
        append_event(
            session,
            "media.motion_needs_owner",
            "storyboard",
            storyboard_id,
            1,
            {
                "severity": "WARNING",
                "scene_number": 3,
                "status": "NEEDS_STILL",
                "reason": "Scena 3: refuzat din motive de siguranță.",
                "failure_kind": "SAFETY",
                "suggested": {
                    "model_id": "veo3.1_fast",
                    "credits": 120,
                    "status": "PLANNED",
                    "reason_ro": "următorul model capabil",
                },
            },
            str(uuid4()),
        )

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE, VEO_FAST])

    scenes = {scene["scene_index"]: scene for scene in sheet["scenes"]}
    assert scenes[1]["shot_size"] == "wide" and scenes[2]["shot_size"] is None
    safety = scenes[3]["motion"]["safety_suggested"]
    assert safety["model_id"] == "veo3.1_fast" and safety["credits"] == 120
    assert safety["failure_kind"] == "SAFETY"
    assert scenes[1]["motion"]["safety_suggested"] is None
    for n in (1, 2, 3, 4):
        redo = scenes[n]["redo"]
        assert set(redo) == {"still", "motion"}
        assert len(redo["still"]["plan_hash"]) == 64 and redo["still"]["credits"] > 0
        assert redo["still"]["cost_usd"] > 0 and redo["still"]["reason_ro"]
        # No approved still yet: a motion redo has nothing to start from, and says so.
        assert redo["motion"]["available"] is False and redo["motion"]["plan_hash"] is None
        assert redo["motion"]["reason_ro"]
    assert set(scenes[5]["redo"]) == {"card"} and scenes[5]["redo"]["card"]["credits"] == 0
    assert scenes[6]["redo"]["card"]["free"] is True
    footer = sheet["footer"]
    assert footer["audio_redo"]["credits"] == 0 and len(footer["audio_redo"]["plan_hash"]) == 64
    catalogue = load_film_models()
    assert footer["premium_model_id"] == catalogue.premium_reference[0]
    assert footer["premium_resolution"] == catalogue.premium_reference[1]
    assert footer["allowed_models"] == sorted(catalogue.allowed or [])
    assert footer["hero_threshold"] == catalogue.hero_threshold == 0.93
    # No price for the voice: the narration line says so and costs nothing it cannot name.
    assert footer["narration"]["usd_micros"] == 0 and footer["narration"]["priced"] is False
    assert "Narațiune" in footer["narration"]["line_ro"]


def test_a_filmed_scene_with_its_still_has_a_priced_motion_redo(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE])

    motion = sheet["scenes"][1]["redo"]["motion"]
    assert motion["available"] is True and len(motion["plan_hash"]) == 64
    assert motion["model_id"] == "seedance2_5" and motion["credits"] > 0
    assert motion["cap_credits"] >= motion["credits"] and motion["buyable"] is True


def test_the_narration_price_is_its_own_line_and_part_of_the_hashed_plan(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    before = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    narration_price(engine, "0.30")

    after = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)

    narration = after["footer"]["narration"]
    with Session(engine) as session:
        characters = sum(
            len(" ".join(str(row.voiceover_segment or "").split()))
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
        )
    assert narration["characters"] == characters > 0
    assert narration["usd_micros"] == math.floor((characters * 300_000 + 500) / 1000)
    assert narration["priced"] is True
    assert "caractere" in narration["line_ro"] and "USD" in narration["line_ro"]
    assert after["steps"]["assemble"]["narration"]["usd_micros"] == narration["usd_micros"]
    assert after["sheet_hash"] != before["sheet_hash"], "the narration is not in the plan"


def test_the_sheets_redo_hash_is_the_one_the_redo_route_checks(client, engine, headers, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)

    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    route = client.get(
        f"/api/v1/media/storyboards/{storyboard_id}/redo-plan?kind=still&scene=1",
        headers=headers,
    ).json()

    assert sheet["scenes"][0]["redo"]["still"]["plan_hash"] == route["plan_hash"]


# ---------------------------------------------------------------- (a) the assemble step


def test_the_assemble_step_refuses_a_stale_plan_before_anything(client, engine, headers, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=1)
    wire(client, tmp_path)

    response = client.post(
        step_url(storyboard_id, "assemble"), headers=headers, json={"plan_hash": "0" * 64}
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["status"] == "STALE_PLAN"
    assert jobs(engine) == []


def test_in_production_assembly_is_refused_per_scene_without_an_accepted_take_or_his_choice(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)
    in_environment(engine, "PRODUCTION")
    wire(client, tmp_path)
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    step = sheet["steps"]["assemble"]
    assert step["ready"] is False
    assert [item["scene_index"] for item in step["blocked"]] == [1, 2]
    assert "imagine fixă animată local" in step["blocked"][0]["reason_ro"]

    response = client.post(
        step_url(storyboard_id, "assemble"),
        headers=headers,
        json={"plan_hash": sheet["sheet_hash"]},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "TAKES_NOT_ACCEPTED"
    assert "Scena 1" in detail["message"] and "Scena 2" in detail["message"]
    assert [item["scene_index"] for item in detail["scenes"]] == [1, 2]
    assert jobs(engine) == [] and approvals(engine) == []


@requires_ffmpeg
def test_after_his_local_move_the_film_is_assembled_checked_and_written_to_him(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)
    in_environment(engine, "PRODUCTION")
    wire(client, tmp_path)
    for scene in (1, 2):
        chosen = client.put(
            f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/{scene}/model",
            headers=headers,
            json={"model_id": LOCAL_MOVE},
        )
        assert chosen.status_code == 200, chosen.text
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    assert sheet["steps"]["assemble"]["ready"] is True, sheet["steps"]["assemble"]

    response = client.post(
        step_url(storyboard_id, "assemble"),
        headers=headers,
        json={"plan_hash": sheet["sheet_hash"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ASSEMBLED" and body["plan_hash"] == sheet["sheet_hash"]
    (job,) = jobs(engine)
    assert job.status == "COMPLETED" and body["job_id"] == job.id
    assert job.production_json["fallback_gate"]["owner_chosen"] == [1, 2]
    assert body["qc"]["media_asset_id"] == body["asset_id"]
    assert body["qc_letter_ro"].startswith("Controlul calității")
    assert body["narration"]["usd_micros"] == 0 and approvals(engine) == []
    (done,) = events(engine, "media.sheet_assembled")
    assert done.payload["plan_hash"] == sheet["sheet_hash"]
    assert done.payload["asset_id"] == body["asset_id"]


@requires_ffmpeg
def test_the_assembled_films_intermediates_go_with_its_qc_report_and_the_film_stays(
    client, engine, headers, tmp_path
):
    # About a gigabyte of shots per film used to wait for the next render's sweep (or for
    # ever): they go the moment the sheet's film has its QC report.
    from app.media.models import MediaAsset

    storyboard_id = film_with_stills(engine, tmp_path, scenes=2)
    in_environment(engine, "PRODUCTION")
    wire(client, tmp_path)
    for scene in (1, 2):
        client.put(
            f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/{scene}/model",
            headers=headers,
            json={"model_id": LOCAL_MOVE},
        )
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()

    response = client.post(
        step_url(storyboard_id, "assemble"),
        headers=headers,
        json={"plan_hash": sheet["sheet_hash"]},
    )

    assert response.status_code == 200, response.text
    asset_id = response.json()["asset_id"]
    (released,) = events(engine, "media.intermediates_released")
    assert released.aggregate_id == asset_id
    with Session(engine) as session:
        film = Path(session.get(MediaAsset, asset_id).uri_or_path)
    shots = [name for name in released.payload["files"] if Path(name).name.startswith("shot_")]
    assert len(shots) == 2, released.payload
    assert not any((film.parent / name).exists() for name in shots)
    assert film.is_file()


@requires_ffmpeg
def test_the_narration_is_asked_bound_to_the_plan_hash_and_bought_on_his_yes(
    client, engine, headers, settings, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=1)
    in_environment(engine, "TEST", mode="SUPERVISED")
    settings.paid_generation_approval_threshold_usd = 0.0
    narration_price(engine, "0.30")
    wire(client, tmp_path)
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    narration = sheet["steps"]["assemble"]["narration"]
    assert narration["usd_micros"] > 0
    body = {"plan_hash": sheet["sheet_hash"]}

    asked = client.post(step_url(storyboard_id, "assemble"), headers=headers, json=body)

    assert asked.status_code == 202, asked.text
    assert jobs(engine) == []
    (question,) = approvals(engine)
    assert question.action == "media.paid_generation_over_threshold"
    assert question.subject == storyboard_id
    assert question.proposed_diff["plan_hash"] == sheet["sheet_hash"]
    assert question.proposed_diff["step"] == "assemble"
    assert asked.json()["approval_id"] == question.id
    answer(engine, question.id, "APPROVED", note="Da, narațiunea.")

    made = client.post(step_url(storyboard_id, "assemble"), headers=headers, json=body)

    assert made.status_code == 200, made.text
    assert made.json()["status"] == "ASSEMBLED"
    (spent,) = approvals(engine)
    assert spent.consumed_at is not None


def test_the_days_narration_question_is_bound_to_the_same_plan(
    engine, settings, tmp_path, monkeypatch
):
    from app.runbook import stages

    storyboard_id = film_with_stills(engine, tmp_path, scenes=1)
    in_environment(engine, "TEST", mode="SUPERVISED")
    settings.paid_generation_approval_threshold_usd = 0.0
    monkeypatch.setattr(
        "app.media.assembler.assemble_from_takes",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("assembled before the yes")),
    )

    made = stages._assemble_from_takes(
        engine,
        settings,
        None,
        storyboard_id,
        {"storage_root": tmp_path / "media"},
        "TEST",
        {"narration_usd_micros": 2_400, "caveat": ""},
        "corr",
        sheet_hash="a" * 64,
    )

    assert made["status"] == "ASKED", made
    (question,) = approvals(engine)
    assert question.proposed_diff["plan_hash"] == "a" * 64
    assert question.proposed_diff["step"] == "assemble"
    with Session(engine) as session:
        assert session.scalars(select(SceneTake)).first() is not None


def test_the_day_does_not_ask_about_a_narration_for_a_film_it_cannot_assemble(
    engine, settings, monkeypatch
):
    """Nothing left to buy, but a filmed scene with no accepted take and no LOCAL_MOVE of
    his: the day writes him the sheet and waits, and asks nothing about the narration."""
    from app.runbook import stages

    reason = "Scena 2 nu are un cadru acceptat (...)."
    nothing = {"to_buy": [], "cost_credits": 0, "cap_credits": 0, "cost_usd": 0.0}

    def build(engine_, board, **_context):
        return {
            "storyboard_id": board,
            "title": "A film",
            "sheet_hash": "e" * 64,
            "credit_usd": 0.01,
            "scenes": [],
            "steps": {
                "stills": nothing,
                "test_shot": nothing,
                "motion": nothing,
                "assemble": {"blocked": [{"scene_index": 2, "reason_ro": reason}]},
            },
            "footer": {},
        }

    monkeypatch.setattr("app.media.shooting_sheet.build_sheet", build)

    film = stages._film_staircase(engine, settings, None, "board-1", {}, "PRODUCTION", "c")

    assert film["status"] == "WAITING" and film["refusal"] == "TAKES_NOT_ACCEPTED"
    assert film["reason"] == reason and film["bought"] == []
    assert approvals(engine) == []
