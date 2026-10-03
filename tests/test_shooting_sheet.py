"""Foaia de filmare: everything the Owner sees before a credit is spent, and the steps it gates.

The Nepal film (2026-09-26) was bought twice from a button that showed no price, no prompt
and no model, and asked nothing. The shooting sheet is the page in front of every purchase:

- GET .../shooting-sheet costs 0 credits; its only live call is the free Runway balance read
  (GET /v1/organization). Per scene it shows the kind, the prompts exactly as they will be
  sent, the lint findings (every BLOCK), the model chosen for that scene with its price and
  the cheaper and the better alternative, and "Grafic compus local · 0 credite" for a card.
  The footer has the stills already paid, the hero, the rest, the total, the hard cap, the
  live balance, the daily budget, the priced alternatives and the sheet_hash.
- POST .../steps/{stills|test_shot|motion} {plan_hash} answers 202 with the Owner's question
  when he has not said yes, 409 with a Romanian reason when the plan is stale, a BLOCK is
  open, the balance is short or the daily budget would be exceeded without his explicit
  consent, and 200 once his yes for THIS sheet is spent and the step bought.
- The Owner changes a scene's model on the sheet (a model id or LOCAL_MOVE); that is part of
  the sheet_hash. He picks or rejects takes on the contact sheet.

Every provider is faked: the Runway transport is the conftest fake that records every call,
the adapters are spies that count their POSTs, and no socket is opened.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, set_budget
from app.integrations.models import Integration, ProviderResource
from app.integrations.vault import CredentialVault
from app.media.assembler import still_fields, take_hash
from app.media.faces import detector_available
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.prompt_lint import LintScene, lint_film
from app.media.shooting_sheet import (
    LOCAL_MOVE,
    SheetStepRefused,
    build_sheet,
    set_scene_model,
)
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, VEO_FAST, Account, Models, SpyVideo
from test_film_costing import a_film as film_with_stills
from test_scene_takes import nepal_like
from test_stills_stage import SpyStills, still_prompt
from test_stills_stage import a_film as film_without_stills

FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
PROMPTS = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))
#: The day the published table was read is 2026-09-27; the sheet is read four days later.
TODAY = date(2026, 10, 1)
#: The assembler's dissolve overlap, added to every filmed span (assembler.TRANSITION_SECONDS).
OVERLAP = 0.4

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def nepal_film(engine, tmp_path: Path) -> str:
    """The Nepal storyboard: its six scenes as the new writer marks them (four LIVE, the
    chart as a DATA_CARD, the black screen as BLACK), with the prompts exactly as they were
    sent on 2026-09-26 (tests/fixtures/nepal_1d530880/prompts.json) and its visual bible."""
    storyboard_id = nepal_like(engine, tmp_path)
    by_index = {scene["scene_index"]: scene for scene in PROMPTS["scenes"]}
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).visual_bible_json = dict(PROMPTS["visual_bible"])
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            sent = by_index[row.scene_index]
            row.duration_seconds = float(sent["duration_seconds"])
            if row.scene_kind != "LIVE":
                row.prompt_json = {"scene_kind": row.scene_kind, "source": "model"}
                continue
            row.visual_prompt = sent["writer_visual"]
            row.prompt_json = {
                "scene_kind": "LIVE",
                "source": "model",
                "still_prompt": sent["still_prompt"],
                "motion_prompt": sent["motion_prompt"],
            }
    return storyboard_id


def runway_connection(engine) -> str:
    """A verified Runway connection whose key sits in the app's own vault."""
    identifier = str(uuid4())
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="runway",
                name="runway",
                config={"credit_usd": 0.01},
                encrypted_secrets=vault.encrypt({"api_key": "test-key"}),
                secret_fields=["api_key"],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
    return identifier


def wire(client, tmp_path: Path, **state) -> None:
    """Hand the app the fakes the sheet and its steps use (as a test injects adapters)."""
    app_state = client.app.app.state
    app_state.media_storage_root = tmp_path / "media"
    app_state.scene_model_capabilities = state.pop("capabilities", [SEEDANCE])
    for name, value in state.items():
        setattr(app_state, name, value)


def billed(seconds: float) -> int:
    """seedance2_5 bills whole seconds rounded UP (4..30)."""
    return max(4, math.ceil(round(seconds + OVERLAP, 3) - 1e-9))


def approvals(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest)))
        session.expunge_all()
        return rows


def sheet_url(storyboard_id: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet"


def step_url(storyboard_id: str, step: str) -> str:
    return f"/api/v1/media/storyboards/{storyboard_id}/steps/{step}"


# ----------------------------------------------- 1. the sheet costs nothing and hides nothing


def test_the_nepal_sheet_reads_the_balance_once_and_lists_kinds_prices_and_every_block(
    client, engine, headers, tmp_path, runway_api
):
    storyboard_id = nepal_film(engine, tmp_path)
    runway_connection(engine)
    wire(client, tmp_path)

    response = client.get(sheet_url(storyboard_id), headers=headers)

    assert response.status_code == 200, response.text
    # Its only live call: the free balance read. Nothing was POSTed anywhere.
    assert runway_api.calls == [("api.dev.runwayml.com", "GET", "/v1/organization")]
    assert runway_api.bodies == []
    sheet = response.json()
    scenes = {scene["scene_index"]: scene for scene in sheet["scenes"]}
    assert [scenes[n]["kind"] for n in range(1, 7)] == [
        "LIVE",
        "LIVE",
        "LIVE",
        "LIVE",
        "DATA_CARD",
        "BLACK",
    ]
    durations = {s["scene_index"]: s["duration_seconds"] for s in PROMPTS["scenes"]}
    for n in range(1, 5):
        motion = scenes[n]["motion"]
        assert motion["model_id"] == "seedance2_5"
        assert motion["billed_seconds"] == billed(durations[n])
        assert motion["credits"] == billed(durations[n]) * 68
        assert motion["seed"] == sheet["seed"]
    expected = sum(billed(durations[n]) * 68 for n in range(1, 5))
    assert sheet["footer"]["motion_credits"] == expected
    assert sheet["footer"]["stills_to_buy_credits"] == 4 * 18
    assert sheet["footer"]["total_credits"] == expected + 72
    for n, label in ((5, "Grafic compus local · 0 credite"), (6, "Ecran negru")):
        assert scenes[n]["motion"]["credits"] == 0 and scenes[n]["still_credits"] == 0
        assert label in scenes[n]["price_line_ro"]
        assert scenes[n]["still_prompt"] == "" and scenes[n]["motion_prompt"] == ""
    # The prompts are shown as they would be sent (the template codes are still in them).
    assert "NEPAL_CLIMATE_CRISIS" in scenes[1]["still_prompt"]
    sent = " ".join(PROMPTS["scenes"][1]["motion_prompt"].split())
    assert scenes[2]["motion_prompt"] == sent

    # Every BLOCK the linter finds on those words is on the sheet, scene by scene.
    findings = lint_film(
        [
            LintScene(
                scene=n,
                kind=scenes[n]["kind"],
                still_prompt=scenes[n]["still_prompt"],
                motion_prompt=scenes[n]["motion_prompt"],
                model_id=scenes[n]["motion"]["model_id"],
            )
            for n in range(1, 7)
        ],
        bible=PROMPTS["visual_bible"],
    )
    blocks = sorted(f.as_dict().items() for f in findings if f.severity == "BLOCK")
    assert len(blocks) >= 20
    assert sorted(f.items() for f in sheet["blocks"]) == blocks
    assert len(sheet["blocks"]) == sum(1 for f in sheet["lint"] if f["severity"] == "BLOCK")
    assert sheet["lint_blocked"] is True and "blocaje" in sheet["lint_summary_ro"]
    for n in range(1, 5):
        assert {f["code"] for f in scenes[n]["lint"]} >= {"ENUM_CODE", "HEX_CODE"}

    # The footer: the live balance, the cap, the alternatives, the hash.
    footer = sheet["footer"]
    assert footer["balance"] == {"credits": 1200.0, "read": True, "problem": None}
    assert footer["cap_credits"] > footer["total_credits"]
    assert len(sheet["sheet_hash"]) == 64


@requires_ffmpeg
def test_editing_one_motion_prompt_changes_the_hash_and_an_old_yes_returns_409(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    wire(client, tmp_path, runway_account=account, video_adapter_for_model=models)
    first = client.get(sheet_url(storyboard_id), headers=headers).json()["sheet_hash"]

    asked = client.post(
        step_url(storyboard_id, "test_shot"), headers=headers, json={"plan_hash": first}
    )
    assert asked.status_code == 202, asked.text
    answer(engine, asked.json()["approval_id"], "APPROVED", note="Da.")

    # Scene 2's motion is rewritten (its world's motion), and nothing else.
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        ).one()
        package = dict(row.prompt_json)
        package["motion_intent"] = {**package["motion_intent"], "world": "Rain falls steadily."}
        row.prompt_json = package
    second = client.get(sheet_url(storyboard_id), headers=headers).json()
    assert second["sheet_hash"] != first
    assert "Rain falls steadily" in second["scenes"][1]["motion_prompt"]

    stale = client.post(
        step_url(storyboard_id, "test_shot"), headers=headers, json={"plan_hash": first}
    )

    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["status"] == "STALE_PLAN"
    assert "foaia de filmare" in stale.json()["detail"]["message"].lower()
    assert models.posts() == 0
    (yes,) = approvals(engine)
    assert yes.result == "APPROVED" and yes.consumed_at is None, "the old yes was spent"

    # The new sheet is a new question: the old yes does not answer it.
    again = client.post(
        step_url(storyboard_id, "test_shot"),
        headers=headers,
        json={"plan_hash": second["sheet_hash"]},
    )
    assert again.status_code == 202, again.text
    assert again.json()["approval_id"] != yes.id
    assert models.posts() == 0


# ------------------------------------------------------ 2. a step asks before it buys anything


def test_the_stills_step_without_a_yes_answers_202_and_buys_nothing(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    images = SpyStills(balance=10_000)
    wire(client, tmp_path, image_adapter=images)
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    assert sheet["steps"]["stills"]["to_buy"] == [1, 2, 3, 4]

    response = client.post(
        step_url(storyboard_id, "stills"), headers=headers, json={"plan_hash": sheet["sheet_hash"]}
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) >= {"approval_id", "cost_usd", "cap_credits"}
    assert body["cost_usd"] == pytest.approx(0.72)
    assert body["cap_credits"] == 216
    assert images.asked == [], "a question bought a still"
    (question,) = approvals(engine)
    assert question.action == "media.stills_purchase" and question.result == "PENDING"
    assert question.proposed_diff["plan_hash"] == sheet["sheet_hash"]


@requires_ffmpeg
def test_the_hero_step_answers_202_then_200_once_the_yes_for_this_sheet_is_spent(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    wire(client, tmp_path, runway_account=account, video_adapter_for_model=models)
    plan_hash = client.get(sheet_url(storyboard_id), headers=headers).json()["sheet_hash"]
    body = {"plan_hash": plan_hash}

    asked = client.post(step_url(storyboard_id, "test_shot"), headers=headers, json=body)
    assert asked.status_code == 202, asked.text
    assert asked.json()["cap_credits"] == 680 and asked.json()["cost_usd"] == pytest.approx(3.4)
    assert models.posts() == 0
    answer(engine, asked.json()["approval_id"], "APPROVED", note="Da, cadrul de probă.")

    bought = client.post(step_url(storyboard_id, "test_shot"), headers=headers, json=body)

    assert bought.status_code == 200, bought.text
    assert models.posts() == 1
    assert {s["scene_index"]: s["status"] for s in bought.json()["scenes"]}[1] == "PAID"
    (yes,) = approvals(engine)
    assert yes.consumed_at is not None
    # The same hash again buys nothing: the sheet changed (the hero is bought) and the yes
    # was spent.
    again = client.post(step_url(storyboard_id, "test_shot"), headers=headers, json=body)
    assert again.status_code == 409 and again.json()["detail"]["status"] == "STALE_PLAN"
    assert models.posts() == 1


# ------------------------------------------------------- 3. the balance and the daily budget


@requires_ffmpeg
def test_a_balance_under_the_next_round_returns_409_before_the_owner_is_asked(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    # The Owner's rule of 2026-10-03: the hero's one shot (340) with the 15% margin is 391;
    # its cap (680) stays the ceiling and is named, but it is not what the account must hold.
    account = Account(390)
    models = Models(SpyVideo("seedance2_5", account))
    wire(client, tmp_path, runway_account=account, video_adapter_for_model=models)
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    assert sheet["footer"]["balance"]["credits"] == 390.0
    assert sheet["footer"]["balance_needed_credits"]["test_shot"] == 391

    response = client.post(
        step_url(storyboard_id, "test_shot"),
        headers=headers,
        json={"plan_hash": sheet["sheet_hash"]},
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "LOW_BALANCE"
    assert "Sold Runway insuficient" in detail["message"]
    for words in ("390", "340", "391", "680"):
        assert words in detail["message"], (words, detail["message"])
    assert approvals(engine) == [] and models.posts() == 0


@requires_ffmpeg
def test_a_step_over_the_daily_budget_needs_his_explicit_consent(client, engine, headers, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    wire(client, tmp_path, runway_account=account, video_adapter_for_model=models)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="1"))
    plan_hash = client.get(sheet_url(storyboard_id), headers=headers).json()["sheet_hash"]

    refused = client.post(
        step_url(storyboard_id, "test_shot"), headers=headers, json={"plan_hash": plan_hash}
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["status"] == "OVER_DAILY_BUDGET"
    assert "Bugetul zilnic" in refused.json()["detail"]["message"]
    assert approvals(engine) == [] and models.posts() == 0

    consented = client.post(
        step_url(storyboard_id, "test_shot"),
        headers=headers,
        json={"plan_hash": plan_hash, "allow_over_budget": True},
    )
    assert consented.status_code == 202, consented.text
    assert models.posts() == 0
    with Session(engine) as session:
        excess = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.budget_excess_approved")
        ).all()
    assert len(excess) == 1 and excess[0].payload["step"] == "test_shot"


def test_a_refused_step_carries_its_status_and_romanian_reason():
    refused = SheetStepRefused("STALE_PLAN", "Foaia de filmare s-a schimbat.")
    assert refused.http_status == 409
    assert SheetStepRefused("NEEDS_APPROVAL", "Întrebare", approval_id="a").http_status == 202


# -------------------------------------------- 4. alternatives and where every price comes from


def test_the_sheet_prices_the_alternatives_and_names_each_price_source(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], today=TODAY)

    offered = {(alt["model_id"], alt["resolution"]): alt for alt in sheet["footer"]["alternatives"]}
    assert set(offered) == {
        ("seedance2_5", "720p"),
        ("seedance2", "1080p"),
        ("veo3.1_fast", "1080p"),
    }
    for alt in offered.values():
        assert alt["total_credits"] > 0 and alt["total_usd_micros"] > 0
        assert alt["price_source"] == "tarif publicat 27.09"
    assert offered[("seedance2_5", "720p")]["total_credits"] < sheet["footer"]["total_credits"]
    for scene in sheet["scenes"]:
        if scene["kind"] == "LIVE":
            assert scene["motion"]["price_source"] == "tarif publicat 27.09"
            assert scene["still_price_source"] == "tarif publicat 27.09"
    assert {row["source"] for row in sheet["prices"]} == {"tarif publicat 27.09"}

    # Thirty-odd days later the same published figures are no longer trusted.
    later = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], today=date(2026, 11, 30))
    assert {row["source"] for row in later["prices"]} == {"nevalidat"}
    assert later["footer"]["price_source"] == "nevalidat"

    # And what the account was charged outranks the page: a MEASURED seedance price.
    connection = runway_connection(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ProviderResource(
                id=str(uuid4()),
                integration_id=connection,
                resource_type="MODEL",
                remote_id="seedance2_5",
                name="seedance2_5",
                api_metadata={},
                api_available=True,
                last_seen_at=utc_now(),
                pricing={
                    "per_second_usd": 0.66,
                    "unit": "per second of video at 1080p",
                    "source": "measured",
                },
                price_verified_at="2026-09-30T12:00:00+00:00",
                capabilities={},
                metadata_version=1,
                production_status="PRODUCTION",
            )
        )
    measured = build_sheet(
        engine, storyboard_id, capabilities=[SEEDANCE], integration_id=connection, today=TODAY
    )
    live = [s for s in measured["scenes"] if s["kind"] == "LIVE"]
    assert {s["motion"]["price_source"] for s in live} == {"măsurat"}
    assert live[0]["motion"]["credits"] == math.ceil(
        66 * live[0]["motion"]["billed_seconds"] - 1e-9
    )
    sources = {(row["model_id"], row["resolution"]): row["source"] for row in measured["prices"]}
    assert sources[("seedance2_5", "1080p")] == "măsurat"
    assert sources[("seedream5_pro", "2K")] == "tarif publicat 27.09"
    assert measured["sheet_hash"] != sheet["sheet_hash"], "a new price is a new sheet"


# ------------------------------------------------------- 5. the Owner's own choices on the sheet


def test_the_owners_model_for_a_scene_wins_shows_both_alternatives_and_changes_the_hash(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path, capabilities=[SEEDANCE, VEO_FAST])
    before = client.get(sheet_url(storyboard_id), headers=headers).json()
    scene_2 = before["scenes"][1]["motion"]
    # STANDARD scene: the cheapest capable model; the dearer, better one is offered beside it.
    assert scene_2["model_id"] == "veo3.1_fast" and scene_2["decided_by"] == "policy"
    assert scene_2["better"]["model_id"] == "seedance2_5" and scene_2["better"]["credits"] > 0
    assert before["footer"]["saved_credits"] > 0

    changed = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/2/model",
        headers=headers,
        json={"model_id": "seedance2_5"},
    )
    assert changed.status_code == 200, changed.text
    after = client.get(sheet_url(storyboard_id), headers=headers).json()
    chosen = after["scenes"][1]["motion"]
    assert chosen["model_id"] == "seedance2_5" and chosen["decided_by"] == "owner"
    assert chosen["cheaper"]["model_id"] == "veo3.1_fast" and chosen["cheaper"]["credits"] > 0
    assert after["scenes"][1]["override"] == "seedance2_5"
    assert after["sheet_hash"] != before["sheet_hash"] == changed.json()["previous_sheet_hash"]
    assert changed.json()["sheet_hash"] == after["sheet_hash"]

    local = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/3/model",
        headers=headers,
        json={"model_id": LOCAL_MOVE},
    )
    assert local.status_code == 200, local.text
    scene_3 = client.get(sheet_url(storyboard_id), headers=headers).json()["scenes"][2]
    assert scene_3["motion"]["status"] == "LOCAL" and scene_3["motion"]["credits"] == 0
    assert "imagine fixă animată local" in scene_3["price_line_ro"]

    # A card has no model to choose, and an unpriced model is refused, in Romanian.
    card = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/5/model",
        headers=headers,
        json={"model_id": "seedance2_5"},
    )
    assert card.status_code == 422 and "compus" in card.json()["detail"]
    unknown = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/2/model",
        headers=headers,
        json={"model_id": "wan3_prime"},
    )
    assert unknown.status_code == 422 and "preț" in unknown.json()["detail"]


def test_only_the_owner_sets_a_scenes_model(engine, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    for who in ("director", "video_editor", "autorun", ""):
        with pytest.raises(PermissionError):
            set_scene_model(engine, storyboard_id, 2, "seedance2_5", issued_by=who)
    with Session(engine) as session:
        assert not session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.sheet_scene_model_set")
        ).all()


def test_the_owner_picks_a_candidate_and_rejects_another_on_the_contact_sheet(
    client, engine, headers, tmp_path
):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    identity = take_hash(still_fields(still_prompt(1), None), "seedream5_pro")
    files = []
    for n, (status, approved_by) in enumerate((("APPROVED", "still_gate"), ("PAID", None))):
        # inside the page's media folder (`wire`): the file routes serve nothing else (SEC-06)
        copy = tmp_path / "media" / storyboard_id / f"candidate_{n}.jpg"
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / f"scene_0{n + 1}.jpg", copy)
        files.append(copy)
        with Session(engine) as session, session.begin():
            session.add(
                SceneTake(
                    id=f"take-{n}",
                    storyboard_id=storyboard_id,
                    scene_number=1,
                    kind="still",
                    prompt_hash=identity,
                    model_id="seedream5_pro",
                    resolution="1530:2720",
                    status=status,
                    approved_by=approved_by,
                    path=str(copy),
                    sha256=hashlib.sha256(copy.read_bytes()).hexdigest(),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id="take-refused",
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="still",
                prompt_hash=identity,
                model_id="seedream5_pro",
                resolution="1530:2720",
                status="REJECTED",
                failure_code="LOCAL.STILL_GATE",
                failure_detail="YuNet a găsit 1 față.",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    sheet = client.get(sheet_url(storyboard_id), headers=headers).json()
    candidates = {c["take_id"]: c for c in sheet["scenes"][0]["candidates"]}
    assert candidates["take-refused"]["reason_ro"] == "YuNet a găsit 1 față."
    assert sheet["scenes"][0]["still"]["take_id"] == "take-0"
    # The approved still's faces are counted locally (YuNet), not taken from the prompt.
    badges = {b["code"]: b for b in sheet["scenes"][0]["badges"]}
    if detector_available():
        assert badges["faces"] == {
            "code": "faces",
            "label_ro": "fără fețe: da",
            "source": "măsurat",
        }
    assert badges["light"]["label_ro"] == "lumină: înnorat"
    assert badges["text"]["label_ro"] == "fără text: cerut în prompt"

    picked = client.post(
        "/api/v1/media/takes/take-1/decision",
        headers=headers,
        json={"decision": "APPROVED", "note": "Prefer lumina asta."},
    )
    assert picked.status_code == 200, picked.text
    with Session(engine) as session:
        statuses = {t.id: (t.status, t.approved_by) for t in session.scalars(select(SceneTake))}
    assert statuses["take-1"] == ("APPROVED", "owner")
    assert statuses["take-0"] == ("PAID", None), "two approved stills for one scene"

    rejected = client.post(
        "/api/v1/media/takes/take-0/decision", headers=headers, json={"decision": "REJECTED"}
    )
    assert rejected.status_code == 200, rejected.text
    with Session(engine) as session:
        assert session.get(SceneTake, "take-0").status == "REJECTED"
    missing = client.post(
        "/api/v1/media/takes/no-such-take/decision", headers=headers, json={"decision": "APPROVED"}
    )
    assert missing.status_code == 404
    # The picture itself, for the contact sheet.
    picture = client.get("/api/v1/media/takes/take-1/file", headers=headers)
    assert picture.status_code == 200 and picture.content == files[1].read_bytes()


@requires_ffmpeg
def test_a_card_preview_is_composed_locally_from_its_numbers(client, engine, headers, tmp_path):
    storyboard_id = film_without_stills(engine, tmp_path)
    wire(client, tmp_path)
    url = f"/api/v1/media/storyboards/{storyboard_id}/scenes/5/card-preview"

    picture = client.get(url, headers=headers)

    assert picture.status_code == 200, picture.text
    assert picture.headers["content-type"] == "image/png"
    body = picture.content
    assert body[:8] == bytes.fromhex("89504e470d0a1a0a")
    assert (int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")) == (1080, 1920)
    filmed = client.get(
        f"/api/v1/media/storyboards/{storyboard_id}/scenes/1/card-preview", headers=headers
    )
    assert filmed.status_code == 422


# ------------------------------------- a superseded question is withdrawn by the policy kernel


def test_a_superseded_sheet_question_is_withdrawn_by_the_policy_kernel(engine, monkeypatch):
    """Only `app.services` reaches an approval row (the closure adversary scans the tree).

    The sheet decides *that* an older question about the same step can no longer buy
    anything; the kernel closes it: EXPIRED, never answered, with the Romanian reason and the
    `governance.approval_withdrawn` event, and the question that can still buy is kept.
    """
    import app.services as kernel  # noqa: PLC0415
    from app.media import shooting_sheet  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        old = kernel.request_approval(
            session,
            "media.sheet.stills",
            "T2",
            "studio",
            subject="board-1",
            proposed_diff={"plan_hash": "a" * 64},
        ).id
        new = kernel.request_approval(
            session,
            "media.sheet.stills",
            "T2",
            "studio",
            subject="board-1",
            proposed_diff={"plan_hash": "b" * 64},
        ).id
        other_film = kernel.request_approval(
            session,
            "media.sheet.stills",
            "T2",
            "studio",
            subject="board-2",
            proposed_diff={"plan_hash": "a" * 64},
        ).id

    seen: list[dict] = []
    real = kernel.withdraw_superseded_approvals

    def spy(session, **kwargs):
        seen.append(kwargs)
        return real(session, **kwargs)

    monkeypatch.setattr(kernel, "withdraw_superseded_approvals", spy)
    withdrawn = shooting_sheet.withdraw_stale_questions(
        engine,
        "board-1",
        "media.sheet.stills",
        "b" * 64,
        keep=new,
        step_words="cadrele fixe",
        correlation_id="corr-1",
    )

    assert withdrawn == [old]
    assert len(seen) == 1 and seen[0]["new_plan_hash"] == "b" * 64 and seen[0]["keep"] == new
    rows = {row.id: row for row in approvals(engine)}
    assert rows[old].result == "EXPIRED" and rows[old].decided_at is None
    assert rows[old].consumed_at is None
    assert "foaie de filmare mai nouă" in rows[old].note and "«cadrele fixe»" in rows[old].note
    assert rows[new].result == "PENDING" and rows[new].note is None
    assert rows[other_film].result == "PENDING"
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == shooting_sheet.WITHDRAWN_EVENT)
        )
    assert shooting_sheet.WITHDRAWN_EVENT == kernel.APPROVAL_WITHDRAWN_EVENT
    assert event.aggregate_id == old
    assert event.correlation_id == "corr-1"
    assert event.payload["old_plan_hash"] == "a" * 64
    assert event.payload["new_plan_hash"] == "b" * 64
    assert event.payload["replaced_by"] == new
    # Asking about the newer plan already closed the old row without a word
    # (request_approval); the withdrawal is what gives it its reason and its event.
    assert event.payload["previous_result"] == "EXPIRED"
    assert event.payload["reason"] == rows[old].note

    # A second pass withdraws nothing more: the closed question carries its note.
    assert (
        shooting_sheet.withdraw_stale_questions(
            engine,
            "board-1",
            "media.sheet.stills",
            "b" * 64,
            keep=new,
            step_words="cadrele fixe",
            correlation_id="corr-2",
        )
        == []
    )


# ------------------------------------------- a film's paid steps, one buyer at a time (MONEY-04)
#
# Two presses of one step under MODE (no yes is spent, so nothing serialised them) bought an
# extra shot and lost a paid one to "database is locked". A film's paid steps now take its
# purchase lease first; a second buyer is told «Filmul este deja în lucru» and buys nothing.
# Each step also holds its cap against the budgets (AR-03) instead of reading them.


def mode_studio(engine) -> None:
    """AUTONOMOUS_CEO with the paid-media rule MODE: a step buys without asking."""
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.paid_media_approval = "MODE"


class HeldVideo(SpyVideo):
    """Its first POST waits until the test lets it go: another buyer arrives meanwhile."""

    def __init__(self, *args, **kwargs):
        import threading

        super().__init__(*args, **kwargs)
        self.posting = threading.Event()
        self.release = threading.Event()

    async def create_generation(self, prompt, **kwargs):
        if not self.posting.is_set():
            self.posting.set()
            assert self.release.wait(30), "the test never let the first POST go"
        return await super().create_generation(prompt, **kwargs)


def _sheet_step(engine, storyboard_id, models, account, tmp_path, step="test_shot", **kwargs):
    from app.media.shooting_sheet import run_sheet_step

    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    return run_sheet_step(
        engine,
        storyboard_id,
        step,
        plan_hash,
        correlation_id=str(uuid4()),
        capabilities=[SEEDANCE],
        account=account,
        adapter_for_model=models,
        storage_root=tmp_path / "media",
        **kwargs,
    )


def _in_a_thread(target):
    import threading

    outcome: dict = {}

    def run():
        try:
            outcome["result"] = target()
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            outcome["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


@requires_ffmpeg
def test_two_buyers_of_one_step_under_mode_buy_it_once_and_the_second_is_told_why(engine, tmp_path):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    account = Account(10_000)
    spy = HeldVideo("seedance2_5", account)
    models = Models(spy)
    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    to_buy = sheet["steps"]["test_shot"]["to_buy"]

    first, first_outcome = _in_a_thread(
        lambda: _sheet_step(engine, storyboard_id, models, account, tmp_path)
    )
    assert spy.posting.wait(30), "the first buyer never reached its POST"
    try:
        with pytest.raises(SheetStepRefused) as second:
            _sheet_step(engine, storyboard_id, models, account, tmp_path)
    finally:
        spy.release.set()
        first.join(60)

    assert "error" not in first_outcome, first_outcome.get("error")
    assert second.value.status == "FILM_BUSY"
    assert second.value.http_status == 409
    assert "Filmul este deja în lucru" in second.value.reason_ro
    assert models.posts() == len(to_buy) == 1
    # The lease is let go when the step ends: the film is free for its next stair.
    from app.media.shooting_sheet import current_lease

    assert current_lease(engine, storyboard_id) is None


@requires_ffmpeg
def test_a_scene_another_run_bought_after_the_plan_was_read_is_not_bought_again(
    engine, tmp_path, monkeypatch
):
    """The check behind the lease (MONEY-04): each scene's takes are read again right before
    its POST. A shot of the scene's identity that appeared since the plan was read (a writer
    the lease did not stop) means the scene is bought, and it is not bought a second time."""
    from app.media import assembler

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    hero = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)["steps"][
        "test_shot"
    ]["to_buy"][0]
    identities: list[str] = []
    real_hash = assembler.take_hash

    def recorded(*args, **kwargs):
        value = real_hash(*args, **kwargs)
        identities.append(value)
        return value

    monkeypatch.setattr(assembler, "take_hash", recorded)
    rival: dict[str, str] = {}

    class Rival(Account):
        """Its third balance read is the motion loop's, right before the hero's POST; the
        rival's paid take of that very shot lands then."""

        async def credit_balance(self):
            value = await super().credit_balance()
            if self.reads == 3:
                now = utc_now()
                rival["id"] = str(uuid4())
                with Session(engine) as session, session.begin():
                    session.add(
                        SceneTake(
                            id=rival["id"],
                            storyboard_id=storyboard_id,
                            scene_number=hero,
                            kind="test_shot",
                            prompt_hash=identities[-1],
                            model_id="seedance2_5",
                            resolution="1080:1920",
                            seconds=5,
                            credits_quoted=340,
                            status="PAID",
                            created_at=now,
                            updated_at=now,
                        )
                    )
            return value

    account = Rival(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    result = _sheet_step(engine, storyboard_id, models, account, tmp_path)

    assert rival, "the rival's take never landed before the POST"
    assert models.posts() == 0
    scene = next(s for s in result["scenes"] if s["scene_index"] == hero)
    assert scene["status"] == "BOUGHT_ELSEWHERE", scene
    assert "nu se cumpără a doua oară" in scene["reason"]
    with Session(engine) as session:
        shots = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "test_shot"
                )
            )
        )
    assert [take.id for take in shots] == [rival["id"]]


@requires_ffmpeg
def test_the_sheet_says_which_step_is_being_bought(engine, tmp_path):
    from app.media.shooting_sheet import film_purchase_lease

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    with film_purchase_lease(engine, storyboard_id, holder="day-1", step="test_shot"):
        sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
        busy = sheet["in_progress"]
        assert busy is not None and busy["step"] == "test_shot"
        assert sheet["steps"]["test_shot"]["in_progress"] is True
        assert sheet["steps"]["motion"]["in_progress"] is False
        # Being bought is not part of what is bought: the hash the Owner's yes is bound to
        # does not move while the step runs.
        inside = sheet["sheet_hash"]
    after = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    assert after["in_progress"] is None and after["sheet_hash"] == inside


@requires_ffmpeg
def test_a_repeated_command_id_returns_the_stored_result_and_buys_nothing(
    client, engine, headers, tmp_path
):
    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    mode_studio(engine)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    wire(client, tmp_path, runway_account=account, video_adapter_for_model=models)
    plan_hash = client.get(sheet_url(storyboard_id), headers=headers).json()["sheet_hash"]
    body = {"plan_hash": plan_hash, "command_id": str(uuid4())}

    first = client.post(step_url(storyboard_id, "test_shot"), headers=headers, json=body)
    again = client.post(step_url(storyboard_id, "test_shot"), headers=headers, json=body)

    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    assert models.posts() == 1
    assert again.json()["replayed"] is True
    assert again.json()["scenes"] == first.json()["scenes"]
    # The same id with another body is a mistake, not a repeat: refused, nothing bought.
    other = client.post(
        step_url(storyboard_id, "motion"), headers=headers, json={**body, "plan_hash": "f" * 64}
    )
    assert other.status_code == 409, other.text
    assert models.posts() == 1


@requires_ffmpeg
def test_two_films_against_one_budget_hold_their_caps_and_the_second_is_refused(engine, tmp_path):
    from app.economy.models import SpendReservation

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first_film = film_with_stills(engine, tmp_path / "a", scenes=3)
    second_film = film_with_stills(engine, tmp_path / "b", scenes=3)
    mode_studio(engine)
    # Each hero holds its cap of 680 credits (6.80 USD); together they do not fit in 10.
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    account = Account(10_000)
    spy = HeldVideo("seedance2_5", account)
    first_models = Models(spy)
    second_models = Models(SpyVideo("seedance2_5", account))

    first, first_outcome = _in_a_thread(
        lambda: _sheet_step(engine, first_film, first_models, account, tmp_path / "a")
    )
    assert spy.posting.wait(30)
    try:
        with pytest.raises(SheetStepRefused) as refused:
            _sheet_step(engine, second_film, second_models, account, tmp_path / "b")
    finally:
        spy.release.set()
        first.join(60)

    assert "error" not in first_outcome, first_outcome.get("error")
    assert refused.value.status == "OVER_DAILY_BUDGET", refused.value.reason_ro
    assert "Bugetul zilnic" in refused.value.reason_ro
    assert second_models.posts() == 0 and first_models.posts() == 1
    with Session(engine) as session:
        holds = list(session.scalars(select(SpendReservation)))
    # The first hold was settled by its booking; the refused one held nothing.
    assert [h.status for h in holds] == ["SETTLED"]
    assert holds[0].usd_micros == 6_800_000
    assert holds[0].purpose == "sheet:test_shot"


@requires_ffmpeg
def test_a_step_that_asks_or_fails_before_paying_lets_its_hold_go(engine, tmp_path):
    from app.economy.models import SpendReservation

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    account = Account(10_000)

    class Broken(SpyVideo):
        async def create_generation(self, prompt, **kwargs):
            raise RuntimeError("the adapter broke before sending anything")

    # EVERY_PAID_STEP (the default): the step asks him, and its hold is let go.
    spy = Models(SpyVideo("seedance2_5", account))
    with pytest.raises(SheetStepRefused) as asked:
        _sheet_step(engine, storyboard_id, spy, account, tmp_path)
    assert asked.value.status == "NEEDS_APPROVAL"

    # MODE, and the stage raises before anything was charged: the hold goes too.
    mode_studio(engine)
    with pytest.raises(RuntimeError):
        _sheet_step(
            engine, storyboard_id, Models(Broken("seedance2_5", account)), account, tmp_path
        )

    with Session(engine) as session:
        holds = list(session.scalars(select(SpendReservation)))
    assert len(holds) == 2
    assert {h.status for h in holds} == {"RELEASED"}


def test_a_step_that_failed_after_paying_answers_409_with_his_words_not_500(
    client, engine, headers, tmp_path, monkeypatch
):
    """BOOK_EVERY_PURCHASE books and letters it; the route now says it instead of a 500."""
    from app.media import router as media_router
    from app.media.assembler import SpentStageError

    storyboard_id = film_with_stills(engine, tmp_path, scenes=3)
    wire(client, tmp_path)

    def spent(*_args, **_kwargs):
        raise SpentStageError(
            "Pasul «cadrul de probă» s-a oprit după ce a cumpărat (340 de credite); nu se "
            "reia automat.",
            storyboard_id=storyboard_id,
            step="test_shot",
            credits=340.0,
            booked={"credits": 340.0},
        )

    monkeypatch.setattr(media_router, "run_sheet_step", spent)

    response = client.post(
        step_url(storyboard_id, "test_shot"), headers=headers, json={"plan_hash": "a" * 64}
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "SPENT_AND_STOPPED"
    assert "nu se reia automat" in detail["message"]
    assert detail["booked"] is True
