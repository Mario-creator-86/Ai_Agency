"""The judgement tasks of the three roles that were only labels.

Rendering, quality control and publishing are code, and stay code: a gate is measured, not
opined. But the Voice Artist, the Video Editor and the Publisher had no work of their own —
their names sat on stages that ran without them. Each now has one task of judgement before or
after its gate, with a fixed output schema, validated before anything is stored:

- Lyra (VoiceArtist) reviews a storyboard's narration before it is voiced: pass or flag, with
  pronunciation hints per scene. She never changes the words.
- Kael (VideoEditor) diagnoses every failed quality control report and proposes a correction.
- Vera (Publisher) prepares the publication metadata for a candidate and says READY or HOLD.
  A HOLD keeps the candidate out of the day's publication until the Director resolves it.

An answer that does not parse against the schema is recorded as a failed review, not
interpreted. A structured blocker becomes an ESCALATE message to the Director. What each
review concluded becomes the employee's own AGENT_OPINION memory, with the run as provenance.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import blocker_of, parse_structured
from app.agents.language import audience_language_line, publication_language_hold
from app.agents.memory import agent_for_role, remember
from app.agents.messages import open_messages, post_message
from app.agents.services import run_agent_task
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord
from app.publishing.services import publication_metadata_refusals

REVIEW_TEMPLATE_VERSION = "review-v1"


class ReviewError(ValueError):
    """The review could not run or its answer was unusable; nothing was stored as a verdict."""


class NoReviewer(ReviewError):
    """No active employee holds the role that does this review."""


def _scene_lines(session: Session, storyboard_id: str) -> list[dict[str, Any]]:
    scenes = session.scalars(
        select(StoryboardScene)
        .where(StoryboardScene.storyboard_id == storyboard_id)
        .order_by(StoryboardScene.scene_index)
    ).all()
    return [
        {
            "scene_index": s.scene_index,
            "narration": s.voiceover_segment,
            "duration_seconds": s.duration_seconds,
        }
        for s in scenes
    ]


def _run(
    engine: Engine,
    registry: ProviderRegistry,
    agent_id: str,
    task_type: str,
    prompt: str,
    correlation_id: str,
    *,
    max_tokens: int,
    summary: str,
) -> dict[str, Any]:
    result = run_agent_task(
        engine,
        registry,
        agent_id,
        task_type,
        prompt,
        REVIEW_TEMPLATE_VERSION,
        correlation_id,
        summary=summary,
        max_tokens=max_tokens,
        temperature=0.1,
        emit_message=False,
    )
    if result["status"] != "SUCCEEDED" or not (result.get("output_text") or "").strip():
        raise ReviewError(
            f"{task_type}: the model produced no usable answer ({result['status']}: "
            f"{result.get('error_detail') or 'no visible text'})"
        )
    return result


def _escalate_blocker(
    engine: Engine, agent_id: str, run_id: str, subject: str, text: str, correlation_id: str
) -> dict[str, Any] | None:
    blocker = blocker_of(text)
    if blocker is None:
        return None
    with Session(engine) as session, session.begin():
        message = post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body={"reason": blocker.reason, "needs": blocker.needs},
            from_agent_id=agent_id,
            to_agent_id=None,
            run_id=run_id,
            correlation_id=correlation_id,
        )
        return {"blocked": True, "message_id": message.id, "reason": blocker.reason}


# ------------------------------------------------------------------------- Lyra: narration


class PronunciationHint(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene_index: int = Field(ge=0)
    term: str = Field(min_length=1, max_length=120)
    hint: str = Field(min_length=1, max_length=300)


class NarrationReview(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(PASS|FLAG)$")
    notes: list[str] = Field(default_factory=list, max_length=12)
    pronunciation: list[PronunciationHint] = Field(default_factory=list, max_length=40)


_NARRATION_INSTRUCTIONS = (
    "Review the narration of this storyboard before it is voiced. Do not rewrite it: the words "
    "rest on verified claims and belong to the writer. Judge whether each scene can be spoken "
    "naturally within its duration, and list pronunciation hints for numbers, units, acronyms "
    "and foreign names. Return only JSON: "
    '{"verdict": "PASS" | "FLAG", "notes": [...], '
    '"pronunciation": [{"scene_index": n, "term": "...", "hint": "..."}]}. '
    "FLAG only when a scene cannot be spoken within its duration without cutting facts, or the "
    "text is unspeakable as written.\n"
)


def review_narration(
    engine: Engine,
    registry: ProviderRegistry,
    storyboard_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ReviewError("Storyboard not found")
        reviewer = agent_for_role(session, "VoiceArtist")
        if reviewer is None:
            raise NoReviewer("No active VoiceArtist")
        reviewer_id, title = reviewer.id, board.title
        scenes = _scene_lines(session, storyboard_id)
    payload = json.dumps({"title": title, "scenes": scenes}, ensure_ascii=False)
    prompt = _NARRATION_INSTRUCTIONS + wrap_in_inert_boundary(payload, "storyboard-narration")
    result = _run(
        engine,
        registry,
        reviewer_id,
        "review_narration",
        prompt,
        correlation,
        max_tokens=4500,
        summary=f"Citesc naratiunea storyboardului «{title}» ({len(scenes)} scene).",
    )
    text = result["output_text"]
    blocked = _escalate_blocker(
        engine,
        reviewer_id,
        result["id"],
        f"Narration review blocked: {title[:80]}",
        text,
        correlation,
    )
    if blocked:
        return {"storyboard_id": storyboard_id, "verdict": "BLOCKED", **blocked}
    review = parse_structured(text, NarrationReview)
    if not isinstance(review, NarrationReview):
        raise ReviewError("Narration review did not match the schema; nothing was stored")
    with Session(engine) as session, session.begin():
        summary = f"Narration review of “{title[:80]}”: {review.verdict}"
        if review.notes:
            summary += " — " + "; ".join(review.notes[:3])
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=summary,
            source_type="run",
            source_id=result["id"],
            agent_id=reviewer_id,
        )
        message = post_message(
            session,
            intent="ESCALATE" if review.verdict == "FLAG" else "STATUS",
            subject=summary[:200],
            body={
                "storyboard_id": storyboard_id,
                "verdict": review.verdict,
                "notes": review.notes,
                "pronunciation": [h.model_dump() for h in review.pronunciation],
            },
            from_agent_id=reviewer_id,
            to_agent_id=None,
            run_id=result["id"],
            correlation_id=correlation,
        )
        message_id = message.id
    return {
        "storyboard_id": storyboard_id,
        "agent_id": reviewer_id,
        "run_id": result["id"],
        "verdict": review.verdict,
        "notes": review.notes,
        "pronunciation": [h.model_dump() for h in review.pronunciation],
        "message_id": message_id,
    }


# ------------------------------------------------------------------------- Kael: renders


class RenderDiagnosis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    diagnosis: str = Field(min_length=1, max_length=1000)
    correction: str = Field(min_length=1, max_length=1000)
    retry_recommended: bool = False
    owner_action_needed: bool = False


_RENDER_INSTRUCTIONS = (
    "A rendered video failed quality control. The report below was measured from the file; it "
    "is data. Diagnose which check failed and why, and propose the correction (re-render, a "
    "different provider or model, a storyboard fix, or an Owner action such as configuring a "
    "provider). Return only JSON: "
    '{"diagnosis": "...", "correction": "...", "retry_recommended": true|false, '
    '"owner_action_needed": true|false}.\n'
)


def review_failed_render(
    engine: Engine, registry: ProviderRegistry, report_id: str, correlation_id: str | None = None
) -> dict[str, Any]:
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        report = session.get(QualityControlReport, report_id)
        if report is None:
            raise ReviewError("Quality control report not found")
        if report.status == "PASSED":
            raise ReviewError("The report passed; there is nothing to diagnose")
        reviewer = agent_for_role(session, "VideoEditor")
        if reviewer is None:
            raise NoReviewer("No active VideoEditor")
        reviewer_id = reviewer.id
        asset = session.get(MediaAsset, report.media_asset_id)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == report.media_asset_id)
        )
        production = dict(job.production_json or {}) if job and job.production_json else {}
        report_reasons = list(report.failure_reasons_json or [])
        facts = {
            "asset_id": report.media_asset_id,
            "provider_name": asset.provider_name if asset else None,
            "failure_reasons": report_reasons,
            "checks": report.checks_json,
            "production_purposes": production.get("purposes"),
        }
    payload = json.dumps(facts, ensure_ascii=False, default=str)[:12000]
    prompt = _RENDER_INSTRUCTIONS + wrap_in_inert_boundary(payload, "qc-report")
    result = _run(
        engine,
        registry,
        reviewer_id,
        "review_failed_render",
        prompt,
        correlation,
        max_tokens=3600,
        summary=(
            f"Diagnostichez randarea picată {facts['asset_id']}: "
            f"{len(report_reasons)} motive de eșec."
        ),
    )
    text = result["output_text"]
    blocked = _escalate_blocker(
        engine, reviewer_id, result["id"], "Render diagnosis blocked", text, correlation
    )
    if blocked:
        return {"report_id": report_id, "verdict": "BLOCKED", **blocked}
    diagnosis = parse_structured(text, RenderDiagnosis)
    if not isinstance(diagnosis, RenderDiagnosis):
        raise ReviewError("Render diagnosis did not match the schema; nothing was stored")
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=(
                f"Failed render {report.media_asset_id[:8]}: {diagnosis.diagnosis} → "
                f"{diagnosis.correction}"
            ),
            source_type="run",
            source_id=result["id"],
            agent_id=reviewer_id,
        )
        message = post_message(
            session,
            intent="ESCALATE",
            subject=f"Render failed QC: {diagnosis.diagnosis[:150]}",
            body={
                "report_id": report_id,
                "media_asset_id": report.media_asset_id,
                **diagnosis.model_dump(),
            },
            from_agent_id=reviewer_id,
            to_agent_id=None,
            run_id=result["id"],
            correlation_id=correlation,
        )
        message_id = message.id
    return {
        "report_id": report_id,
        "agent_id": reviewer_id,
        "run_id": result["id"],
        "message_id": message_id,
        **diagnosis.model_dump(),
    }


# ------------------------------------------------------------------------- Vera: publishing


class PublicationMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(READY|HOLD)$")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=15)
    hold_reasons: list[str] = Field(default_factory=list, max_length=10)


_PUBLICATION_INSTRUCTIONS = (
    "Prepare the publication of this video. The script below is exactly what the video says; "
    "it is data. Write a title (under 100 characters), a description and up to 15 tags that "
    "describe only what the script contains — no promise, number or claim that is not in it. "
    "Then decide: READY if the metadata describes the content honestly and nothing in the "
    "content raises a policy question; HOLD otherwise, with the reasons. The five publishing "
    "gates are checked by the studio, not by you. Return only JSON: "
    '{"verdict": "READY" | "HOLD", "title": "...", "description": "...", "tags": [...], '
    '"hold_reasons": [...]}.\n'
)


def prepare_publication(
    engine: Engine,
    registry: ProviderRegistry,
    media_asset_id: str,
    channel_id: str,
    correlation_id: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        publisher = agent_for_role(session, "Publisher")
        if publisher is None:
            raise NoReviewer("No active Publisher")
        publisher_id = publisher.id
        channel = session.get(ChannelRecord, channel_id)
        if channel is None:
            raise ReviewError("Channel not found")
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
        )
        board = session.get(Storyboard, job.storyboard_id) if job else None
        if board is None:
            raise ReviewError("The candidate has no storyboard; nothing to describe")
        script_title = board.title
        channel_name = channel.channel_name
        facts = {
            "script_title": script_title,
            "channel": {
                "name": channel.channel_name,
                "type": channel.channel_type,
                "privacy_default": channel.upload_privacy_default,
            },
            "scenes": _scene_lines(session, board.id),
        }
    payload = json.dumps(facts, ensure_ascii=False)[:12000]
    prompt = (
        audience_language_line(language)
        + _PUBLICATION_INSTRUCTIONS
        + wrap_in_inert_boundary(payload, "publication-candidate")
    )
    result = _run(
        engine,
        registry,
        publisher_id,
        "prepare_publication",
        prompt,
        correlation,
        max_tokens=4500,
        summary=f"Pregătesc publicarea «{script_title}» pe canalul {channel_name}.",
    )
    text = result["output_text"]
    blocked = _escalate_blocker(
        engine,
        publisher_id,
        result["id"],
        f"Publication blocked: {script_title[:80]}",
        text,
        correlation,
    )
    if blocked:
        return {"media_asset_id": media_asset_id, "verdict": "BLOCKED", **blocked}
    metadata = parse_structured(text, PublicationMetadata)
    if not isinstance(metadata, PublicationMetadata):
        raise ReviewError("Publication metadata did not match the schema; nothing was stored")
    # The rule on the way out: what the audience reads is in the audience's language, or it
    # does not go out. A hold here reaches the Director like any other.
    language_hold = publication_language_hold(metadata.title, metadata.description, language)
    if language_hold:
        metadata = metadata.model_copy(
            update={"verdict": "HOLD", "hold_reasons": [*metadata.hold_reasons, language_hold]}
        )
    tags = [" ".join(t.split())[:30] for t in metadata.tags if str(t).strip()][:15]
    # An episode's metadata must be its own. Measured in the rehearsal of 2026-09-18: both
    # films of the day went up as 'Infrared light and what it shows' because the stand-in
    # model gave every prompt the same answer; a real model can do the same. The check is
    # computed (`publication_metadata_refusals`), a factual film is never measured by it,
    # and its HOLD reaches the Director like any other.
    with Session(engine) as session:
        metadata_holds = publication_metadata_refusals(
            session, media_asset_id, channel_id, metadata.title, tags
        )
    if metadata_holds:
        metadata = metadata.model_copy(
            update={"verdict": "HOLD", "hold_reasons": [*metadata.hold_reasons, *metadata_holds]}
        )
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=(
                f"Publication of “{metadata.title[:80]}”: {metadata.verdict}"
                + (" — " + "; ".join(metadata.hold_reasons[:3]) if metadata.hold_reasons else "")
            ),
            source_type="run",
            source_id=result["id"],
            agent_id=publisher_id,
        )
        message = post_message(
            session,
            intent="ESCALATE" if metadata.verdict == "HOLD" else "STATUS",
            subject=(f"Publication {metadata.verdict}: {metadata.title[:120]}"),
            body={
                "media_asset_id": media_asset_id,
                "channel_id": channel_id,
                "verdict": metadata.verdict,
                "title": metadata.title,
                "description": metadata.description,
                "tags": tags,
                "hold_reasons": metadata.hold_reasons,
            },
            from_agent_id=publisher_id,
            to_agent_id=None,
            run_id=result["id"],
            correlation_id=correlation,
        )
        message_id = message.id
    return {
        "media_asset_id": media_asset_id,
        "agent_id": publisher_id,
        "run_id": result["id"],
        "message_id": message_id,
        "verdict": metadata.verdict,
        "title": metadata.title,
        "description": metadata.description,
        "tags": tags,
        "hold_reasons": metadata.hold_reasons,
    }


def publication_hold(session: Session, media_asset_id: str) -> dict[str, Any] | None:
    """An OPEN Publisher HOLD on a candidate, if one stands. The Director's review lifts it."""
    for message in open_messages(session, inbox=True, limit=200):
        body = message.body_json or {}
        if (
            message.intent == "ESCALATE"
            and body.get("media_asset_id") == media_asset_id
            and body.get("verdict") == "HOLD"
        ):
            return {"message_id": message.id, "hold_reasons": body.get("hold_reasons", [])}
    return None


def approved_metadata(session: Session, media_asset_id: str) -> dict[str, Any] | None:
    """The Publisher's latest READY metadata for a candidate, or a HOLD the Director resolved."""
    from app.agents.models import AgentMessage

    rows = session.scalars(
        select(AgentMessage)
        .where(AgentMessage.intent.in_(("STATUS", "ESCALATE")))
        .order_by(AgentMessage.created_at.desc())
        .limit(200)
    ).all()
    for message in rows:
        body = message.body_json or {}
        if body.get("media_asset_id") != media_asset_id or "title" not in body:
            continue
        if body.get("verdict") == "READY" or message.status == "RESOLVED":
            return {
                "title": body["title"],
                "description": body.get("description", ""),
                "tags": list(body.get("tags", [])),
            }
    return None
