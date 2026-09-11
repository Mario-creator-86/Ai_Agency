"""The Director watches the film before it goes out.

The Owner asked how a video with no story, in the wrong language, resting on one sourceless
claim, could be produced and published. The honest answer: every gate did its narrow job.
Quality control measured the file (decodable, 1080×1920, real images); the voice artist
checked pronunciation; the Publisher checked that the title described the content; the
factual gate saw a claim marked SUPPORTED and asked no further. Nobody asked whether it was
worth watching, and the Director only read her inbox after the upload.

This is the missing gate. Before anything reaches a channel, the Director reads the whole
film as data — the script and its claims with their sources, every scene's picture and
narration, what quality control measured, the audience language — and, when her model can
see and an encoder is at hand, looks at frames from the file itself. A few things are decided
without a model, because they are not matters of taste: a claim with no source is not a
fact; narration not in the audience's language does not go out; a film under forty words has
no story. Her verdict is a record (`editorial_review`), an event the ledger shows, and a
letter to each department that must change something. A REJECT closes the storyboard.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.agents.language import audience_language_line, language_name, looks_like_english
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.models import Agent, Role
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, TopicIdea
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import (
    EditorialReview,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.toolchain import find_ffmpeg
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now

logger = logging.getLogger("studio.editorial")

EDITORIAL_TASK = "editorial_review"
TEMPLATE_VERSION = "editorial-v1"
#: Under this many spoken words there is no story to tell, whatever the pictures.
MIN_WORDS = 40
FRAMES = 3
FRAME_WIDTH = 480

DEPARTMENTS = {
    "ScriptWriter": "ScriptWriter",
    "VideoEditor": "VideoEditor",
    "VoiceArtist": "VoiceArtist",
    "Publisher": "Publisher",
    "LeadResearcher": "LeadResearcher",
}


class EditorialVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(APPROVE|REJECT)$")
    story: str = Field(default="", max_length=400)
    reasons: list[str] = Field(default_factory=list, max_length=8)
    notes_for: dict[str, str] = Field(default_factory=dict)
    _clip_story = field_validator("story", mode="before")(clipped(400))


_INSTRUCTIONS = (
    "You are the Director, and this is the last look before a film leaves the studio. Below "
    "is everything the film is, as data: the topic, the script and the claims it rests on "
    "with their sources, each scene's picture and narration, what quality control measured"
    "{frames_note}. Judge it as the audience will: does it tell one clear story with a hook "
    "and a point; is every sentence something a viewer learns, backed by a real source; is it "
    "in the audience's language; do the pictures show the story rather than decorate it; is "
    "it worth their time. A film about the studio itself, a film that only describes its own "
    "process, or narration nobody would understand is REJECTED. Return only JSON: "
    '{{"verdict": "APPROVE" | "REJECT", "story": "one sentence: what the viewer learns", '
    '"reasons": ["..."], "notes_for": {{"ScriptWriter": "...", "VideoEditor": "...", '
    '"VoiceArtist": "...", "Publisher": "..."}}}} — notes only for departments that must '
    "change something.\n"
)


class EditorialError(ValueError):
    """The film could not be reviewed; nothing was decided."""


def gather_facts(session: Session, media_asset_id: str, language: str) -> dict[str, Any]:
    """Everything the Director reads, and the verdicts that need no model."""
    asset = session.get(MediaAsset, media_asset_id)
    if asset is None:
        raise EditorialError("Materialul nu există")
    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    )
    board = session.get(Storyboard, job.storyboard_id) if job else None
    script = session.get(ScriptDraft, board.script_draft_id) if board else None
    topic = session.get(TopicIdea, script.topic_id) if script else None
    scenes = (
        list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board.id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        if board
        else []
    )
    claims: list[dict[str, Any]] = []
    hard: list[str] = []
    for claim_id in list(script.claim_ids_json or []) if script else []:
        claim = session.get(FactualClaim, claim_id)
        if claim is None:
            hard.append(f"afirmația {claim_id[:8]} nu mai există")
            continue
        source = session.get(SourceSnapshot, claim.source_id) if claim.source_id else None
        claims.append(
            {
                "text": claim.claim_text,
                "status": claim.status,
                "source": (
                    {"url": source.url, "publisher": source.publisher, "title": source.title}
                    if source
                    else None
                ),
            }
        )
        if source is None:
            hard.append(f"afirmația «{claim.claim_text[:80]}» nu are nicio sursă")
        elif claim.status != "SUPPORTED":
            hard.append(f"afirmația «{claim.claim_text[:80]}» nu este verificată ({claim.status})")
    voiceover = script.voiceover_full_text if script else ""
    words = len(voiceover.split())
    if not script:
        hard.append("materialul nu are un scenariu de care să țină")
    elif words < MIN_WORDS:
        hard.append(f"fără poveste: narațiunea are {words} cuvinte, sub {MIN_WORDS}")
    if language.lower() == "en" and voiceover and not looks_like_english(voiceover):
        hard.append(f"narațiunea nu este în {language_name(language)}")
    if script and not claims:
        hard.append("scenariul nu se sprijină pe nicio afirmație")
    qc = session.scalar(
        select(QualityControlReport)
        .where(QualityControlReport.media_asset_id == media_asset_id)
        .order_by(QualityControlReport.verified_at.desc())
    )
    return {
        "asset_id": media_asset_id,
        "path": asset.uri_or_path,
        "storyboard_id": board.id if board else None,
        "topic": {"title": topic.title, "angle": topic.angle} if topic else None,
        "title": script.title if script else (board.title if board else ""),
        "voiceover": voiceover,
        "words": words,
        "claims": claims,
        "scenes": [
            {
                "index": s.scene_index,
                "seconds": s.duration_seconds,
                "narration": s.voiceover_segment,
                "picture": s.visual_prompt,
            }
            for s in scenes
        ],
        "quality_control": {
            "status": qc.status if qc else None,
            "measured": (
                {
                    k: v
                    for k, v in (qc.checks_json.get("technical_qc") or {}).items()
                    if k.startswith("measured")
                }
                if qc and isinstance(qc.checks_json, dict)
                else {}
            ),
        },
        "duration_seconds": asset.duration_seconds,
        "visual_provider": asset.provider_name,
        "audience_language": language_name(language),
        "hard_rejects": hard,
    }


def frames_for(path: str, ffmpeg_path: str | None, duration: float | None) -> list[str]:
    """Up to three frames from the film, as base64 JPEG, for a model that can see."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    file = Path(path)
    if not ffmpeg or not file.is_file() or not duration or duration <= 0:
        return []
    frames: list[str] = []
    for fraction in (0.2, 0.5, 0.8)[:FRAMES]:
        moment = max(0.0, duration * fraction)
        try:
            result = subprocess.run(  # noqa: S603 - argument list, no shell
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{moment:.2f}",
                    "-i",
                    str(file),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={FRAME_WIDTH}:-2",
                    "-f",
                    "image2",
                    "-c:v",
                    "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return frames
        if result.returncode == 0 and result.stdout:
            frames.append(base64.b64encode(result.stdout).decode("ascii"))
    return frames


def latest_editorial(session: Session, media_asset_id: str) -> EditorialReview | None:
    return session.scalar(
        select(EditorialReview)
        .where(EditorialReview.media_asset_id == media_asset_id)
        .order_by(EditorialReview.created_at.desc())
    )


def editorial_review(
    engine: Engine,
    registry: ProviderRegistry | None,
    media_asset_id: str,
    correlation_id: str | None = None,
    language: str = "en",
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """The Director's verdict on one finished film; recorded, announced, and written home."""
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        if director is None:
            raise EditorialError("Niciun Director activ care să vizioneze")
        director_id, director_name = director.id, director.display_name
        facts = gather_facts(session, media_asset_id, language)

    verdict: EditorialVerdict | None = None
    run_id: str | None = None
    frames: list[str] = []
    if facts["hard_rejects"]:
        verdict = EditorialVerdict(
            verdict="REJECT",
            story="",
            reasons=facts["hard_rejects"][:8],
            notes_for={"ScriptWriter": "; ".join(facts["hard_rejects"])[:600]},
        )
    elif registry is not None and registry.registered_ids():
        from app.agents.structured import structured_run  # noqa: PLC0415

        frames = frames_for(facts["path"], ffmpeg_path, facts["duration_seconds"])
        shown = {k: v for k, v in facts.items() if k not in ("path", "hard_rejects")}
        prompt = (
            audience_language_line(language)
            + _INSTRUCTIONS.format(
                frames_note=(
                    f", and {len(frames)} frames from the file itself are attached"
                    if frames
                    else ""
                )
            )
            + wrap_in_inert_boundary(json.dumps(shown, ensure_ascii=False)[:14000], "the-film")
        )
        parsed, first, second = structured_run(
            engine,
            registry,
            director_id,
            EDITORIAL_TASK,
            prompt,
            TEMPLATE_VERSION,
            correlation,
            EditorialVerdict,
            '{"verdict": "APPROVE|REJECT", "story": "...", "reasons": [...], "notes_for": {}}',
            summary=f"Vizionez «{facts['title']}» înainte de publicare ({len(frames)} cadre).",
            max_tokens=6000,
            temperature=0.1,
            extra={"images": frames} if frames else None,
        )
        run_id = (second or first)["id"]
        if parsed is None:
            raise EditorialError(
                f"{director_name} nu a dat un verdict utilizabil "
                f"({(second or first)['status']}: fără obiect)"
            )
        verdict = parsed
    else:
        raise EditorialError("Niciun model de limbaj: Directorul nu poate viziona materialul")

    with Session(engine) as session, session.begin():
        review_id = str(uuid4())
        event = append_event(
            session,
            "media.editorial_reviewed",
            "media_asset",
            media_asset_id,
            1,
            {
                "verdict": verdict.verdict,
                "story": verdict.story[:200],
                "reasons": verdict.reasons[:4],
                "frames_seen": len(frames),
                "title": facts["title"][:120],
            },
            correlation,
        )
        session.add(
            EditorialReview(
                id=review_id,
                media_asset_id=media_asset_id,
                storyboard_id=facts["storyboard_id"],
                verdict=verdict.verdict,
                story=verdict.story,
                reasons_json=list(verdict.reasons),
                notes_json=dict(verdict.notes_for),
                reviewer_agent_id=director_id,
                run_id=run_id,
                frames_seen=len(frames),
                model_used=run_id is not None,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        if verdict.verdict == "REJECT" and facts["storyboard_id"]:
            board = session.get(Storyboard, facts["storyboard_id"])
            if board is not None:
                board.status = "REJECTED"
        roles = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role)
                .join(Role, Agent.role_id == Role.id)
                .where(Agent.lifecycle == "ACTIVE")
            ).all()
        }
        subject = f"Vizionare: {verdict.verdict} — {facts['title'][:120]}"
        summary_text = (
            f"{'Aprobat' if verdict.verdict == 'APPROVE' else 'Respins'}: {facts['title']}. "
            + (f"Despre: {verdict.story} " if verdict.story else "")
            + (f"Motive: {'; '.join(verdict.reasons)}." if verdict.reasons else "")
        )
        post_message(
            session,
            intent="STATUS" if verdict.verdict == "APPROVE" else "ESCALATE",
            subject=subject[:200],
            body={"media_asset_id": media_asset_id, "verdict": verdict.verdict},
            body_text=summary_text[:4000] + f" — {director_name}",
            from_agent_id=director_id,
            to_agent_id=None,
            run_id=run_id,
            correlation_id=correlation,
        )
        sent = 0
        if verdict.verdict == "REJECT":
            for role_name, note in verdict.notes_for.items():
                target = roles.get(DEPARTMENTS.get(role_name, role_name))
                if target is None or not str(note).strip():
                    continue
                post_message(
                    session,
                    intent="HANDOFF",
                    subject=f"Refăcut: {facts['title'][:110]}"[:200],
                    body={
                        "media_asset_id": media_asset_id,
                        "storyboard_id": facts["storyboard_id"],
                    },
                    body_text=f"{note} — {director_name}"[:4000],
                    from_agent_id=director_id,
                    to_agent_id=target.id,
                    run_id=run_id,
                    correlation_id=correlation,
                )
                sent += 1
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=summary_text[:600],
            source_type="run" if run_id else "system",
            source_id=run_id or review_id,
            agent_id=director_id,
        )
    return {
        "review_id": review_id,
        "verdict": verdict.verdict,
        "story": verdict.story,
        "reasons": list(verdict.reasons),
        "letters": sent,
        "frames_seen": len(frames),
        "model_used": run_id is not None,
        "run_id": run_id,
    }
