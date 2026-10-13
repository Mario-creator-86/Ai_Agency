"""The legacy render button stops buying in PRODUCTION, and the Owner's rule reaches his page.

The second Nepal render (2026-09-26, 18:16) started from POST /media/render/{id}: it showed no
price, asked nothing and bought every still and every clip again. In PRODUCTION that route
now answers 409 with the way to the shooting sheet, and asks no adapter at all; in TEST,
with the fakes a test injects, it behaves as before.

Also here, the three gaps the earlier items left for the sheet: the Owner's command that sets
when a paid step asks him (SetPaidMediaApproval) has a route, the policy his page reads shows
the rule, and the storyboard views stop stripping each scene's kind and card.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.media.models import Storyboard, StoryboardScene
from app.media.schemas import StoryboardSceneView, StoryboardView
from app.media.services import get_storyboard
from app.models import DomainEvent, OwnerPolicy
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_phase5_media import (
    _approved_storyboard,
    _planner,
    _recording_assembler,
    _recording_qc,
)


def in_production(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"


def model_written(engine, storyboard_id: str) -> None:
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            row.prompt_json = {"scene_kind": "LIVE", "source": "model", "still_prompt": "x"}


def nothing_may_be_asked(monkeypatch) -> list[str]:
    """Every door to a vendor on the legacy route, each one recording that it was opened."""
    opened: list[str] = []

    def door(name):
        def opened_door(*_args, **_kwargs):
            opened.append(name)
            raise AssertionError(f"the legacy render opened {name} in PRODUCTION")

        return opened_door

    for name in ("render_plan", "assemble_video_job", "motion_for_scene", "tts_provider"):
        monkeypatch.setattr(f"app.media.router.{name}", door(name))
    return opened


def test_in_production_the_render_button_answers_409_with_the_sheet_and_asks_no_vendor(
    client, engine, headers, tmp_path: Path, monkeypatch
):
    storyboard_id = _approved_storyboard(engine, tmp_path)
    model_written(engine, storyboard_id)
    in_production(engine)
    opened = nothing_may_be_asked(monkeypatch)

    class NeverAsked:
        def __getattr__(self, name):
            opened.append(name)
            raise AssertionError(f"a video adapter was asked: {name}")

    client.app.app.state.image_adapter = NeverAsked()
    client.app.app.state.tts_adapter = NeverAsked()

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "UseShootingSheet"
    assert detail["message"].startswith("Folosește foaia de filmare")
    assert detail["sheet_url"] == f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet"
    assert detail["shot_plan_gaps"] == []
    assert opened == []
    # Query parameters a page could add change nothing.
    forced = client.post(
        f"/api/v1/media/render/{storyboard_id}?model=seedance2_5&motion_scenes=1", headers=headers
    )
    assert forced.status_code == 409 and opened == []


def test_in_production_a_film_with_template_prompts_is_held_for_its_shot_plan(
    client, engine, headers, tmp_path: Path, monkeypatch
):
    storyboard_id = _approved_storyboard(engine, tmp_path)  # no model-written package
    in_production(engine)
    opened = nothing_may_be_asked(monkeypatch)

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["shot_plan_gaps"] == [1, 2]
    assert "planul de cadre" in response.json()["detail"]["message"]
    assert opened == []
    with Session(engine) as session:
        assert session.get(Storyboard, storyboard_id).status == "NEEDS_SHOT_PLAN"
        held = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.shot_prompts_incomplete")
        ).all()
    assert len(held) == 1


def test_in_test_the_render_button_with_injected_fakes_is_unchanged(
    client, engine, headers, settings, tmp_path: Path, monkeypatch
):
    storyboard_id = _approved_storyboard(engine, tmp_path)  # template prompts: TEST allows them
    received: dict[str, dict] = {}
    monkeypatch.setattr("app.media.router.render_plan", _planner(None, lambda scene: None))
    monkeypatch.setattr(
        "app.media.router.assemble_video_job", _recording_assembler(received, str(uuid4()))
    )
    monkeypatch.setattr("app.media.router.evaluate_media_qc", _recording_qc(received))

    response = client.post(f"/api/v1/media/render/{storyboard_id}", headers=headers)

    assert response.status_code == 200, response.text
    assert received["render"]["environment"] == "TEST"
    assert received["render"]["settings"] is settings
    with Session(engine) as session:
        assert session.get(Storyboard, storyboard_id).status != "NEEDS_SHOT_PLAN"


# ------------------------------------------------------------ the Owner's rule, on his page


def test_the_owner_sets_when_a_paid_step_asks_him_through_his_own_route(client, headers):
    snapshot = client.get("/api/v1/snapshot", headers=headers).json()
    policy = snapshot["policy"]
    assert policy["paid_media_approval"] == "EVERY_PAID_STEP"
    assert policy["paid_media_approval_over_usd"] is None
    url = "/api/v1/owner/paid-media-approval"
    command = {
        "command_id": str(uuid4()),
        "expected_version": policy["version"],
        "paid_media_approval": "OVER_USD",
        "over_usd": 5,
    }

    assert client.post(url, json=command).status_code == 401
    changed = client.post(url, headers=headers, json=command)

    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "COMMITTED"
    after = client.get("/api/v1/snapshot", headers=headers).json()["policy"]
    assert (after["paid_media_approval"], after["paid_media_approval_over_usd"]) == ("OVER_USD", 5)

    stale = client.post(url, headers=headers, json={**command, "command_id": str(uuid4())})
    assert stale.status_code == 409
    no_threshold = client.post(
        url,
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "expected_version": after["version"],
            "paid_media_approval": "OVER_USD",
        },
    )
    assert no_threshold.status_code == 422
    agent_field = client.post(
        url, headers=headers, json={**command, "issued_by": "director", "command_id": str(uuid4())}
    )
    assert agent_field.status_code == 422, "a body may not name who issues the command"


def test_a_refused_issuer_answers_403(client, headers, monkeypatch):
    from app.services import PaidMediaApprovalRefused

    def refuse(*_args, **_kwargs):
        raise PaidMediaApprovalRefused("Doar Proprietarul poate schimba regula.")

    monkeypatch.setattr("app.main.change_paid_media_approval", refuse)
    response = client.post(
        "/api/v1/owner/paid-media-approval",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "expected_version": 1,
            "paid_media_approval": "MODE",
        },
    )
    assert response.status_code == 403
    assert "Proprietarul" in response.json()["detail"]


# ---------------------------------------------------------- the storyboard views keep kinds


def test_the_storyboard_views_keep_each_scenes_kind_and_card(engine, tmp_path: Path):
    from test_scene_takes import NEPAL_CARD, nepal_like

    assert {"scene_kind", "card_json"} <= set(StoryboardSceneView.model_fields)
    storyboard_id = nepal_like(engine, tmp_path)

    view = StoryboardView.model_validate(get_storyboard(engine, storyboard_id))

    kinds = [scene.scene_kind for scene in view.scenes]
    assert kinds == ["LIVE", "LIVE", "LIVE", "LIVE", "DATA_CARD", "BLACK"]
    assert view.scenes[4].card_json == NEPAL_CARD
    assert view.scenes[0].card_json is None
    dumped = view.model_dump()
    assert dumped["scenes"][4]["scene_kind"] == "DATA_CARD"
