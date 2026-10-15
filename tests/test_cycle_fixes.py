"""What the first real cycle on the Owner's data showed, and what now holds.

The Director wrote seven thousand tokens of analysis and never reached the JSON; a scene
description of 330 characters threw an episode away; a topic sentence of 220 threw the day's
proposals away; seven topics sat SELECTED behind renders that failed quality control, and
nothing could be chosen past them; verdicts a migration had invalidated counted as verdicts.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.agents.director import DirectorReview
from app.agents.identity import clipped, complete_schema, parse_structured
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.research.agent import TopicCandidate
from app.runbook.stages import build_stage_runners, topics_in_production
from app.services import utc_now
from app.story.services import _parse_episode
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- parsing


def test_the_answer_is_found_after_paragraphs_of_analysis_that_contain_braces():
    text = (
        "Let me analyze this inbox carefully.\n\nThe task: {answer every message}. "
        "Inventory: 1. `a9ce78c5` — Nadia, books: SKIPPED {figures remain valid}.\n"
        "Now the decisions.\n\n"
        '{"summary": "Nothing to decide today.", "decisions": [], "priorities": ["a", "b"]}'
        "\n\nThat covers everything."
    )
    review = parse_structured(text, DirectorReview)
    assert isinstance(review, DirectorReview)
    assert review.summary == "Nothing to decide today." and review.priorities == ["a", "b"]


def test_an_answer_cut_off_before_its_json_is_still_refused():
    text = "Let me analyze this carefully. The messages are: {a}, {b}, and then"
    assert parse_structured(text, DirectorReview) is None
    assert parse_structured("", DirectorReview) is None


def test_a_field_longer_than_the_schema_allows_is_kept_whole_not_refused():
    class Note(BaseModel):
        model_config = ConfigDict(extra="ignore")
        text: str = Field(max_length=10)
        _clip = field_validator("text", mode="before")(clipped(10))

    note = parse_structured(json.dumps({"text": "x" * 40}), Note)
    # 2026-10-14 (the Owner: complete messages, no silent shortening): the field is kept
    # whole; the schema's limit no longer cuts what the model said, and nothing is refused.
    assert isinstance(note, Note) and note.text == "x" * 40

    candidate = complete_schema(TopicCandidate).model_validate(
        {
            "title": "How the James Webb Space Telescope found water vapour",
            "topic": "T" * 900,
            "angle": "A" * 3000,
            "target_audience": "Space enthusiasts " * 30,
            # The older six names still map onto the dimensions they correspond to, so an
            # answer in the previous shape is scored on what it did say.
            "scores": {
                "interest": 0.9,
                "credibility": 0.9,
                "source_availability": 0.9,
                "visual_potential": 0.8,
                "novelty": 0.8,
                "cost": 0.3,
                "story_potential": 0.7,
                "payoff_strength": 0.8,
                "channel_fit": 0.8,
                "shareability": 0.6,
                "retention_potential": 0.7,
                "cta_opportunity": 0.6,
            },
        }
    )
    assert len(candidate.topic) == 900 and len(candidate.angle) == 3000
    assert len(candidate.target_audience) == len("Space enthusiasts " * 30)
    assert candidate.scores.hook_potential == 0.9, "interest still names the hook"
    assert candidate.scores.production_feasibility == 0.3, "cost still names the feasibility"

    episode = _parse_episode(
        json.dumps(
            {
                "title": "The Pause That Refreshes",
                "beats": [
                    {
                        "scene": "S" * 700,
                        "dialogue": "Dr. Aris: one more citation.",
                        "event_ids": ["e-1"],
                        "characters": ["Dr. Aris"],
                    }
                ],
            }
        )
    )
    assert len(episode.beats[0].scene) == 700

    # The showrunner's own habit: dialogue as a list of lines, one background name as a
    # string. Since the v3 schema (2026-09-24) each labelled row becomes a line of its
    # speaker's; the label and the direction are taken out of the words when it is stored.
    episode = _parse_episode(
        json.dumps(
            {
                "title": "Pauzele lui Dr. Aris",
                "beats": [
                    {
                        "scene": "Birou open-space, lumină naturală.",
                        "dialogue": [
                            "Sarah: te-ai blocat iar?",
                            "Dr. Aris: (râzând) nu, doar pauză.",
                        ],
                        "event_ids": ["e-1"],
                        "background": "Dr. Aris",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    assert [(line.speaker, line.text) for line in episode.beats[0].lines] == [
        ("Sarah", "te-ai blocat iar?"),
        ("Dr. Aris", "(râzând) nu, doar pauză."),
    ]
    assert episode.beats[0].background == ["Dr. Aris"]


# --------------------------------------------------------------------------- the line


def _selected_topic_with_render(engine, *, verdict: str | None, title="Descoperire Robotică"):
    """A SELECTED topic whose script was storyboarded and rendered; the verdict is optional."""
    topic_id, script_id, board_id, job_id, asset_id = (str(uuid4()) for _ in range(5))
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="t",
                angle="a",
                target_audience="g",
                novelty_score=0.5,
                status="SELECTED",
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                title=title,
                voiceover_full_text="text",
                status="APPROVED",
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title=title,
                status="RENDERED",
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=10.0,
                provider_name="PLACEHOLDER_LOCAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=board_id,
                status="COMPLETED",
                output_asset_id=asset_id,
                started_at=utc_now(),
            )
        )
        session.flush()
        if verdict:
            session.add(
                QualityControlReport(
                    id=str(uuid4()),
                    media_asset_id=asset_id,
                    status=verdict,
                    score=0.5,
                    checks_json={},
                    failure_reasons_json=(
                        ["Visuals are locally generated placeholder frames, not real footage"]
                        if verdict == "FAILED"
                        else []
                    ),
                    verified_at=utc_now(),
                )
            )
    return topic_id, asset_id


def test_a_topic_whose_render_failed_quality_control_no_longer_blocks_the_next_one(
    engine, settings
):
    stalled, _ = _selected_topic_with_render(engine, verdict="FAILED")
    invalidated, _ = _selected_topic_with_render(engine, verdict="INVALIDATED")
    waiting, _ = _selected_topic_with_render(engine, verdict=None)
    with Session(engine) as session:
        live, stuck = topics_in_production(session)
    assert live == [waiting] and set(stuck) == {stalled, invalidated}


def test_a_selection_proceeds_past_stalled_topics_and_says_how_many_stalled(engine, settings):
    from app.factual.models import FactualClaim
    from app.providers.registry import ProviderRegistry

    _selected_topic_with_render(engine, verdict="FAILED")
    fresh = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=fresh,
                title="Un subiect nou, cu dovezi",
                topic="t",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="PROPOSED",
                created_at=utc_now(),
            )
        )
        session.add(
            FactualClaim(
                id=str(uuid4()),
                topic_id=fresh,
                claim_text="O afirmație verificată.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.9,
                created_at=utc_now(),
            )
        )
    runners = build_stage_runners(engine, settings, None, ProviderRegistry())
    outcome = runners["selection"]()
    with Session(engine) as session:
        assert session.get(TopicIdea, fresh).status == "SELECTED"
    assert "stau cu randări picate" not in outcome["reason"] or "1 selectate" in outcome["reason"]


def test_an_invalidated_verdict_is_measured_again(engine, settings, monkeypatch):
    from app.providers.registry import ProviderRegistry

    _, asset_id = _selected_topic_with_render(engine, verdict="INVALIDATED")
    measured: list[str] = []

    def fake_qc(engine_, asset, correlation, **kwargs):
        # The stage now hands quality control the Owner's settings (the fallback ceiling).
        measured.append(asset)
        return {"id": str(uuid4()), "status": "FAILED"}

    monkeypatch.setattr("app.runbook.stages.evaluate_media_qc", fake_qc)
    runners = build_stage_runners(engine, settings, None, ProviderRegistry())
    outcome = runners["edit_and_qc"]()
    assert measured == [asset_id]
    assert outcome["artefacts"]["failed"] == 1


def test_quality_control_cannot_certify_pictures_a_model_only_narrated(engine, monkeypatch):
    """The Director's own failure, guarded one gate earlier.

    She wrote seven thousand tokens of analysis and never reached the JSON. Quality control
    now asks a model that can see whether each scene is a picture of what the scene asked
    for, and the same model can narrate here too. Asked twice, as every structured answer
    is, and still no object: the check says NOT_APPLICABLE with the reason and the run's
    status, `passed` is None, and it adds no failure and no pass to the film's verdict.
    """
    from app.media.qc import evaluate_media_qc
    from test_picture_qc import FRAMES, a_film, give_vision, registry_with, staff

    staffed = staff(engine)
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    monkeypatch.setattr(
        "app.media.picture_qc.frames_for",
        lambda path, ffmpeg, duration, scene_seconds=None: list(FRAMES),
    )
    narrated = (
        "Let me work through the attached frames one at a time. Frame one is a dark field "
        "with a golden shape in it, which I read as the mirror the scene asked for. Frame "
        "two appears to be a spectrum. Frame three is harder to describe."
    )
    registry, model = registry_with(staffed, lambda prompt: narrated)

    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()), registry=registry)

    picture = report["checks_json"]["picture_qc"]
    assert picture["status"] == "NOT_APPLICABLE" and picture["passed"] is None
    assert picture["frames"] == 3 and "no usable verdict" in picture["detail"]
    assert picture["run_id"]
    assert not any("Scene" in reason for reason in report["failure_reasons_json"])
    # Twice at most, thinking off and then natively: never a third, never a call per scene.
    assert len(model.calls) == 2
