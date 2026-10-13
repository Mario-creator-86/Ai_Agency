"""What an employee says it did is checked against what the studio recorded.

Local tests with a scripted model; nothing reaches a vendor and no credit is spent. Measured on
the Nepal film (2026-09-26): after the first render failed quality control, the Video Editor
answered the Director "Am re-randat pista audio ... promptul rescris ... trimis către Runway",
and none of it had happened; the Director read it as done. What is asserted here:

- a reply that claims media work with no media.* event recorded since its thread began is
  labelled "NEEFĂCUT — afirmație fără dovadă" in its text and in the body the Director's
  review reads, before she reads it; with a matching event it is left as written;
- a claim denied or promised ("nu am re-randat", "voi re-randa") is not a claim of work done;
- the Video Editor's diagnosis of a failed render becomes concrete, priced redo proposals per
  scene (still | motion | card | audio), never "render it again".
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.director import director_review
from app.agents.mail import answer_mail
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.reviews import (
    UNPROVEN_LABEL,
    check_work_claims,
    redo_sheet,
    review_failed_render,
)
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.cost_plan import (
    STILL_CANDIDATES,
    STILLS_MODEL,
    STILLS_RESOLUTION,
    price_shot,
    price_still,
)
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

FIXTURE = Path(__file__).parent / "fixtures" / "factual_sample" / "qc_report.json"

#: The Video Editor's letter of 2026-09-26, as the model wrote it (abridged).
NEPAL_CLAIM = (
    "Am re-randat pista audio pentru 00000163: true peak normalizat la -1.2 dBTP, acum sub "
    "plafonul de -1 dBTP. Scene 5: promptul rescris — 'two vertical bars, right bar 30% "
    "shorter' — trimis către Runway Gen-4. Kael"
)


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def office(staffed, reply: str):
    """A registry whose one model answers mail with `reply` and the Director with a summary."""

    def answer(prompt: str) -> str:
        if "director-inbox" in prompt:
            return json.dumps({"summary": "Am citit inboxul.", "decisions": [], "priorities": []})
        return json.dumps({"reply": reply, "done": True, "needs": ""}, ensure_ascii=False)

    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


def director_asks_kael(engine, staffed) -> str:
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        letter = post_message(
            session,
            intent="REQUEST_INFO",
            subject="De investigat: Randarea nu a trecut QC",
            body_text="Kael, repară vârful audio și scenele 5 și 6. Sarah",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        )
        return letter.id


def the_reply(engine, message_id: str) -> AgentMessage:
    with Session(engine) as session:
        row = session.get(AgentMessage, message_id)
        assert row is not None
        session.expunge(row)
        return row


# ------------------------------------------------------------------ claims without proof


def test_a_claim_of_work_with_no_media_event_is_labelled_before_the_director_reads_it(
    engine, staffed
):
    letter_id = director_asks_kael(engine, staffed)
    registry, model = office(staffed, NEPAL_CLAIM)

    sent = answer_mail(engine, registry, letter_id)
    reply = the_reply(engine, sent["message_id"])

    assert reply.body_text is not None
    assert reply.body_text.startswith(f"[{UNPROVEN_LABEL}")
    assert NEPAL_CLAIM in reply.body_text  # the letter itself is kept, not rewritten
    check = reply.body_json["claim_check"]
    assert check["label"] == UNPROVEN_LABEL
    kinds = {c["kind"] for c in check["unproven"]}
    assert {"render", "audio", "prompt", "sent"} <= kinds
    assert all(c["quote"] and c["needs"] for c in check["unproven"])
    with Session(engine) as session:
        flagged = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "agent.claim_unproven")
        ).all()
        assert [e.aggregate_id for e in flagged] == [sent["message_id"]]

    # The Director's review reads the label in the letter's body.
    director_review(engine, registry)
    director_prompt = next(c["prompt"] for c in model.calls if "director-inbox" in c["prompt"])
    assert UNPROVEN_LABEL in director_prompt


def test_the_same_claim_with_a_matching_media_event_is_not_labelled(engine, staffed):
    letter_id = director_asks_kael(engine, staffed)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.video_rendered",
            "media_asset",
            str(uuid4()),
            1,
            {"storyboard_id": "0000003f"},
            str(uuid4()),
        )
        append_event(
            session, "media.shot_prompts_written", "storyboard", str(uuid4()), 1, {}, str(uuid4())
        )
        append_event(
            session, "media.paid_generation", "media_asset", str(uuid4()), 1, {}, str(uuid4())
        )
    registry, _ = office(staffed, NEPAL_CLAIM)

    sent = answer_mail(engine, registry, letter_id)
    reply = the_reply(engine, sent["message_id"])

    assert reply.body_text == NEPAL_CLAIM
    assert UNPROVEN_LABEL not in json.dumps(reply.body_json, ensure_ascii=False)


def test_a_media_event_from_before_the_thread_does_not_prove_the_claim(engine, staffed):
    with Session(engine) as session, session.begin():
        # The render that failed: it happened before anyone asked for the fix.
        append_event(
            session, "media.video_rendered", "media_asset", str(uuid4()), 1, {}, str(uuid4())
        )
    letter_id = director_asks_kael(engine, staffed)
    registry, _ = office(staffed, "Am re-randat pista audio. Kael")

    sent = answer_mail(engine, registry, letter_id)

    assert the_reply(engine, sent["message_id"]).body_text.startswith(f"[{UNPROVEN_LABEL}")


def test_a_letter_with_no_claim_of_media_work_is_left_alone(engine, staffed):
    letter_id = director_asks_kael(engine, staffed)
    text = "Voi re-randa doar pista audio după aprobarea ta. Nu am re-randat nimic încă. Kael"
    registry, _ = office(staffed, text)

    sent = answer_mail(engine, registry, letter_id)
    reply = the_reply(engine, sent["message_id"])

    assert reply.body_text == text
    assert "claim_check" not in reply.body_json


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("Am re-randat pista audio.", {"render"}),
        ("Sunetul a fost renormalizat la -14 LUFS.", {"audio"}),
        ("I re-rendered scene 5 and rewrote the prompt.", {"render", "prompt"}),
        ("Promptul a fost rescris și trimis către Runway.", {"prompt", "sent"}),
        ("Am refăcut scena 6.", {"render"}),
        ("Nu am re-randat nimic.", set()),
        ("Scena va fi re-randată mâine.", set()),
        ("I will re-render it after approval.", set()),
        ("Am verificat raportul și am găsit cauza.", set()),
    ],
)
def test_what_counts_as_a_claim_of_work_done(engine, text, kinds):
    with Session(engine) as session:
        found = check_work_claims(session, text, since="2000-01-01T00:00:00+00:00")
    assert {c["kind"] for c in found} == kinds
    assert all(not c["proven"] for c in found)


# ------------------------------------------------------------------ priced redo proposals


def a_failed_nepal_render(engine) -> dict[str, str]:
    """The Nepal film's first render as rows: six scenes, its report, what it measured."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = {k: str(uuid4()) for k in ("topic", "script", "board", "asset", "job", "report")}
    now = utc_now()
    seconds = {1: 4.0, 2: 5.6, 3: 4.0, 4: 6.0, 5: 5.2, 6: 6.8}
    motion = {
        1: {"model": "seedance2_5", "tier": "HERO"},
        2: {"model": "seedance2", "tier": "STANDARD"},
        3: {"model": "seedance2", "tier": "STANDARD"},
        4: {"model": "seedance2", "tier": "STANDARD"},
        5: {"model": "seedance2", "tier": "STANDARD"},
        6: {"model": "seedance2_5", "tier": "PREMIUM"},
    }
    report = fixture["report"]
    # Scene 3 also failed its picture check here, so one LIVE scene needs credits.
    for scene in report["checks_json"]["picture_qc"]["scenes"]:
        if scene["scene"] == 3:
            scene["shows_the_scene"] = False
            scene["reason"] = "A woman's face fills the frame; the plan asked for distant figures."
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title="Nepal",
                topic="climate finance",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title="Why Nepal Is Being Handed a Climate Bill It Cannot Pay",
                voiceover_full_text="text",
                claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title="Why Nepal Is Being Handed a Climate Bill It Cannot Pay",
                status="RENDERED",
                total_scenes=6,
                created_at=now,
            )
        )
        session.flush()
        for index in range(1, 7):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=fixture["scene_prompts"][str(index)],
                    duration_seconds=seconds[index],
                    voiceover_segment="text",
                    created_at=now,
                )
            )
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=31.6,
                provider_name="RUNWAY_IMAGES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
                production_json={
                    "scenes": [{"scene_index": i, "motion": motion[i]} for i in range(1, 7)],
                    "credits_measured": fixture["credits_measured"],
                },
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=ids["report"],
                media_asset_id=ids["asset"],
                status=report["status"],
                score=report["score"],
                checks_json=report["checks_json"],
                failure_reasons_json=report["failure_reasons_json"],
                verified_at=now,
            )
        )
    return ids


def test_a_failed_render_becomes_priced_redo_proposals_never_render_again(engine, staffed):
    ids = a_failed_nepal_render(engine)
    diagnosis = {
        "diagnosis": "True peak over the ceiling; scenes 3, 5 and 6 do not show what they ask.",
        "correction": "Re-render the whole film with a limiter and new prompts.",
        "retry_recommended": True,
        "owner_action_needed": False,
    }
    registry = ProviderRegistry()
    model = ScriptedModel(lambda prompt: json.dumps(diagnosis))
    registry.register(staffed["provider_id"], model)

    result = review_failed_render(engine, registry, ids["report"])

    redo = result["redo"]
    assert {p["redo"] for p in redo} <= {"still", "motion", "card", "audio"}
    by = {(p["scene_index"], p["redo"]): p for p in redo}
    assert set(by) == {(None, "audio"), (3, "still"), (3, "motion"), (5, "card"), (6, "card")}
    assert by[(None, "audio")]["credits"] == 0
    assert by[(5, "card")]["credits"] == 0 and by[(6, "card")]["credits"] == 0
    still = price_still(STILLS_MODEL, STILLS_RESOLUTION, STILL_CANDIDATES)
    shot = price_shot("seedance2", "1080p", 4.0)
    assert by[(3, "still")]["credits"] == still
    assert by[(3, "motion")]["credits"] == shot
    assert by[(3, "motion")]["model_id"] == "seedance2"
    assert result["redo_credits"] == still + shot
    # The whole-film render the model proposed is refused, in words, and not recommended.
    assert result["retry_recommended"] is False
    assert result["model_correction"] == diagnosis["correction"]
    assert result["model_correction_refused"]
    for word in ("re-render", "render again", "randare nouă", "randează din nou"):
        assert word not in result["correction"].lower()
    assert "Scena 3" in result["correction"] and "Scena 5" in result["correction"]
    # Buying scene 3 again needs the Owner's yes on the sheet.
    assert result["owner_action_needed"] is True
    # The model was given the priced proposals and told not to propose a whole render.
    prompt = model.calls[-1]["prompt"]
    assert '"redo"' in prompt and "never propose rendering the whole film" in prompt

    with Session(engine) as session:
        message = session.get(AgentMessage, result["message_id"])
        assert message.body_json["redo"] == redo
        assert message.body_json["redo_credits"] == still + shot
        assert message.body_json["retry_recommended"] is False
        # The Owner's report goes with it, from measured credits.
        assert "123 de credite" in (message.body_text or "")
        assert "−0,93 dBTP" in (message.body_text or "")


def _scene(index: int, prompt: str, seconds: float = 5.0) -> StoryboardScene:
    return StoryboardScene(
        id=str(uuid4()),
        storyboard_id="b",
        scene_index=index,
        visual_prompt=prompt,
        duration_seconds=seconds,
        voiceover_segment="text",
        scene_kind="LIVE",
        created_at=utc_now(),
    )


def test_the_redo_sheet_prices_each_scene_on_its_own_model_and_reads_cards():
    scenes = [
        _scene(1, "Aerial view of Himalayan mountains", 4.0),
        _scene(2, "Two vertical bars side by side"),
        _scene(3, "A black screen, silent and still"),
    ]
    production = {"scenes": [{"scene_index": 1, "motion": {"model": "veo3.1_fast"}}]}
    sheet = redo_sheet(scenes, production)
    rows = {row["scene_index"]: row for row in sheet["scenes"]}
    assert rows[1]["kind"] == "LIVE"
    assert rows[1]["credits"] == price_shot("veo3.1_fast", "1080p", 4.0)
    assert rows[1]["model_id"] == "veo3.1_fast"
    assert (rows[2]["kind"], rows[2]["credits"]) == ("DATA_CARD", 0)
    assert (rows[3]["kind"], rows[3]["credits"]) == ("BLACK", 0)
    # A sheet recorded with the render wins over the table.
    recorded = {"scenes": [{"scene_index": 1, "kind": "LIVE", "credits": 7}], "credit_usd": 0.01}
    assert redo_sheet(scenes, {**production, "sheet": recorded}) == recorded


def test_an_unreadable_price_table_leaves_the_redo_unpriced_not_broken(monkeypatch):
    import app.agents.reviews as reviews

    def broken():
        raise OSError("config/runway_prices.json is missing")

    monkeypatch.setattr(reviews, "load_price_table", broken)
    sheet = redo_sheet([_scene(1, "Aerial view")], {"scenes": []})
    assert sheet["scenes"][0]["credits"] is None
    assert sheet["scenes"][0]["still_credits"] is None
    assert sheet["credit_usd"] is None
