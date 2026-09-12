"""The review that happens before anything is bought.

Every gate the studio had ran after the money was spent. Quality control measured a file that
had already been rendered; the Director watched a film that had already been generated shot by
shot at two dollars sixty a shot. The one question nobody asked while the answer was still
text was whether the thing was worth watching.

This is that question. It runs on the script, in two parts that stay separate on purpose:

- **The checks are computed.** `app.factual.editorial.story_checks` asks whether the film has
  a hook that is not "did you know", a purpose behind every shot, an attribution behind every
  sentence, a payoff in the second half that answers the hook, an ending, a call to action
  that belongs to this story, and narration that can actually be said in the target length.
  No model is consulted, nothing is generated, and the answers carry their reasons.
- **The judgement is the Director's.** Given the script as data, she says where a viewer would
  stop watching — at three seconds, at ten, at twenty — and what to change. Her answer is an
  opinion and is recorded as one; the computed checks decide the verdict on their own when no
  model can be reached, so the gate works in a studio with no language model at all.

A REVISE is not a failure of the pipeline: it is the pipeline doing the one thing that saves
money, because rewriting text costs nothing and re-filming a shot costs dollars.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.identity import parse_structured
from app.agents.memory import agent_for_role
from app.agents.messages import post_message
from app.agents.services import run_agent_task
from app.factual.editorial import expected_seconds, failed, revision_notes, story_checks
from app.factual.models import ScriptDraft, StoryReview
from app.factual.sanitizer import wrap_in_inert_boundary
from app.services import append_event, utc_now

logger = logging.getLogger("studio.story_review")

REVIEWER_ROLE = "Director"
TEMPLATE_VERSION = "story-review-v1"

#: The seconds a short is judged at. Three is where a viewer decides to stay, twenty-five is
#: where they decide whether the ending was worth it.
MARKS = ("0", "3", "5", "10", "15", "20", "25", "end")

#: Checks a rewrite cannot fix, because they are not about the writing. A scene with no
#: verified claim behind it is a research problem: the film waits for evidence, not for prose.
FATAL_CHECKS = ("every_scene_is_attributed",)

#: How many times the studio asks for a rewrite before the story is refused. A third attempt
#: on the same evidence produces a third version of the same weakness.
MAX_REVISIONS = 2


class StoryReviewError(ValueError):
    """The review could not be produced; nothing was decided and nothing was stored."""


class Retention(BaseModel):
    """Where the Director expects a viewer to still be watching, 0..100 at each mark."""

    model_config = ConfigDict(extra="ignore")
    at_0: int = Field(default=100, ge=0, le=100)
    at_3: int = Field(default=0, ge=0, le=100)
    at_5: int = Field(default=0, ge=0, le=100)
    at_10: int = Field(default=0, ge=0, le=100)
    at_15: int = Field(default=0, ge=0, le=100)
    at_20: int = Field(default=0, ge=0, le=100)
    at_25: int = Field(default=0, ge=0, le=100)
    at_end: int = Field(default=0, ge=0, le=100)
    collapse_at: str = Field(default="", max_length=40)
    why: str = Field(default="", max_length=600)


class StoryVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    verdict: str = Field(pattern="^(PASS|REVISE|REJECT)$")
    hook_strength: int = Field(default=0, ge=0, le=100)
    clarity: int = Field(default=0, ge=0, le=100)
    payoff: int = Field(default=0, ge=0, le=100)
    cta_fit: int = Field(default=0, ge=0, le=100)
    retention: Retention = Field(default_factory=Retention)
    notes: list[str] = Field(default_factory=list, max_length=10)


_INSTRUCTIONS = (
    "You are the Director, and this script has not been produced yet — changing it now costs "
    "nothing, while re-filming a shot costs real money. Below is the whole script as data: "
    "the topic, the story it means to tell, and every scene with its narration, its purpose "
    "and the verified claims behind it. Read it as a viewer on a phone will.\n\n"
    "Answer, in order: do the first three seconds open a gap worth staying for; is there one "
    "clear idea; does every sentence move the story rather than restate it; is there a real "
    "payoff that answers the hook; does the ending close the film; is the closing question "
    "about this story; could the pictures actually carry this narration; would someone with "
    "no prior context understand it. Then say where interest would collapse — give the share "
    "of viewers you expect to still be watching at 0, 3, 5, 10, 15, 20, 25 seconds and at the "
    "end, and name the span where you expect to lose them.\n\n"
    "Verdict PASS only if you would put your name on it as it stands. REVISE with specific, "
    "actionable notes if a rewrite would fix it. REJECT if the idea cannot carry a short at "
    "all. A weak film that is cheap to make is still a weak film. Return only JSON: "
    '{"verdict": "PASS" | "REVISE" | "REJECT", "hook_strength": 0, "clarity": 0, '
    '"payoff": 0, "cta_fit": 0, "retention": {"at_0": 100, "at_3": 0, "at_5": 0, "at_10": 0, '
    '"at_15": 0, "at_20": 0, "at_25": 0, "at_end": 0, "collapse_at": "3-9", "why": "..."}, '
    '"notes": ["..."]}.\n'
)


def _script_facts(session: Session, script: ScriptDraft) -> dict[str, Any]:
    """Everything the review reads, from the rows the studio already has."""
    from app.factual.models import FactualClaim, TopicIdea  # noqa: PLC0415

    topic = session.get(TopicIdea, script.topic_id)
    claims = {
        row.id: row.claim_text
        for row in session.scalars(
            select(FactualClaim).where(FactualClaim.topic_id == script.topic_id)
        )
    }
    scenes = [
        {
            "scene": scene.get("scene_number") or index,
            "purpose": scene.get("purpose") or "",
            "narration": scene.get("narration") or scene.get("voiceover_segment") or "",
            "visual": scene.get("visual_description") or scene.get("visual_prompt") or "",
            "claims": [claims.get(cid, "") for cid in (scene.get("claim_ids") or [])],
        }
        for index, scene in enumerate(script.scenes_json or [], start=1)
    ]
    return {
        "title": script.title,
        "topic": topic.title if topic else "",
        "thesis": (topic.thesis_json if topic and topic.thesis_json else {}),
        "story": dict(script.story_json or {}),
        "target_seconds": script.target_duration_seconds,
        "estimated_seconds": expected_seconds(script.scenes_json or []),
        "scenes": scenes,
    }


def review_story(
    engine: Engine,
    registry: Any,
    script_id: str,
    correlation_id: str | None = None,
    *,
    target_seconds: int | None = None,
) -> dict[str, Any]:
    """Review a script before anything is generated, and record the verdict.

    The computed checks decide on their own: a script that fails one of them is sent back
    whatever a model thinks of it, and a script that passes them all is only PASS if the
    Director agrees (or if no model could be reached, in which case the checks stand alone).
    """
    correlation = correlation_id or str(uuid4())
    with Session(engine) as session:
        script = session.get(ScriptDraft, script_id)
        if script is None:
            raise StoryReviewError(f"Script {script_id} not found")
        facts = _script_facts(session, script)
        target = int(target_seconds or script.target_duration_seconds)
        checks = story_checks(
            title=script.title,
            scenes=list(script.scenes_json or []),
            story=dict(script.story_json or {}),
            target_seconds=target,
        )
        earlier = session.scalar(
            select(StoryReview).where(StoryReview.script_id == script_id).limit(1)
        )
        revisions = len(
            list(
                session.scalars(
                    select(StoryReview).where(
                        StoryReview.script_id == script_id, StoryReview.verdict == "REVISE"
                    )
                )
            )
        )
        reviewer = agent_for_role(session, REVIEWER_ROLE)
        reviewer_id = reviewer.id if reviewer else None

    broken = failed(checks)
    notes = revision_notes(checks)
    verdict = "PASS" if not broken else "REVISE"
    if any(name in FATAL_CHECKS for name in broken):
        verdict = "REJECT"
    elif broken and revisions >= MAX_REVISIONS:
        verdict = "REJECT"
        notes.append(
            f"Scenariul a fost trimis înapoi de {revisions} ori; povestea nu se susține pe "
            "dovezile existente."
        )

    scores: dict[str, Any] = {}
    retention: dict[str, Any] = {}
    run_id = None
    if reviewer_id is not None and registry is not None:
        try:
            opinion, run_id = _ask_director(
                engine, registry, reviewer_id, facts, correlation, broken
            )
        except StoryReviewError as exc:
            logger.info("story_review_without_model", extra={"reason": str(exc)[:160]})
            opinion = None
        if opinion is not None:
            scores = {
                "hook_strength": opinion.hook_strength,
                "clarity": opinion.clarity,
                "payoff": opinion.payoff,
                "cta_fit": opinion.cta_fit,
            }
            retention = opinion.retention.model_dump()
            notes.extend(str(note) for note in opinion.notes[:6])
            # The Director may send back a script the checks did not catch; she may not wave
            # through one they did. Taste can be stricter than a rule, never looser.
            if opinion.verdict != "PASS" and verdict == "PASS":
                verdict = opinion.verdict

    review_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "factual.story_reviewed",
            "script_draft",
            script_id,
            (revisions + 1) if earlier is not None else 1,
            {
                "verdict": verdict,
                "failed": broken[:6],
                "estimated_seconds": facts["estimated_seconds"],
            },
            correlation,
        )
        session.add(
            StoryReview(
                id=review_id,
                script_id=script_id,
                verdict=verdict,
                checks_json=checks,
                retention_json=retention,
                scores_json=scores,
                notes_json={"notes": notes[:12], "failed": broken},
                estimated_seconds=float(facts["estimated_seconds"]),
                reviewer_agent_id=reviewer_id,
                run_id=run_id,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        if verdict != "PASS" and reviewer_id is not None:
            post_message(
                session,
                intent="CHALLENGE" if verdict == "REJECT" else "REQUEST_REVIEW",
                subject=f"Povestea «{facts['title'][:60]}»: {verdict}",
                body={"kind": "story_review", "verdict": verdict, "failed": broken[:6]},
                body_text=(
                    f"Scenariul nu poate intra în producție așa cum e ({verdict}). "
                    + " ".join(notes[:6])
                ),
                from_agent_id=reviewer_id,
                to_agent_id=None,
                correlation_id=correlation,
            )
    logger.info(
        "story_reviewed",
        extra={"script_id": script_id, "verdict": verdict, "failed": len(broken)},
    )
    return {
        "id": review_id,
        "script_id": script_id,
        "verdict": verdict,
        "checks": checks,
        "failed": broken,
        "notes": notes[:12],
        "retention": retention,
        "scores": scores,
        "estimated_seconds": facts["estimated_seconds"],
        "model_used": bool(scores),
    }


def _ask_director(
    engine: Engine,
    registry: Any,
    reviewer_id: str,
    facts: dict[str, Any],
    correlation: str,
    broken: list[str],
) -> tuple[StoryVerdict | None, str | None]:
    """The Director's own reading of the script. Her answer is an opinion, recorded as one."""
    payload = json.dumps(facts, ensure_ascii=False, default=str)[:14000]
    prompt = _INSTRUCTIONS
    if broken:
        prompt += (
            "The studio's own checks already found: "
            + "; ".join(broken[:6])
            + ". Say what to change, and do not return PASS.\n"
        )
    prompt += wrap_in_inert_boundary(payload, "script-under-review")
    result = run_agent_task(
        engine,
        registry,
        reviewer_id,
        "story_review",
        prompt,
        TEMPLATE_VERSION,
        correlation,
        summary=f"Citesc povestea «{facts['title'][:50]}» înainte de producție.",
        max_tokens=3000,
        temperature=0.2,
        emit_message=False,
    )
    text = result.get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        raise StoryReviewError(result.get("error_detail") or "no visible text")
    opinion = parse_structured(text, StoryVerdict)
    if not isinstance(opinion, StoryVerdict):
        raise StoryReviewError("the review did not match its schema")
    return opinion, result["id"]


def latest_review(session: Session, script_id: str) -> StoryReview | None:
    """The most recent story review of this script, or None if it has never been reviewed."""
    return session.scalars(
        select(StoryReview)
        .where(StoryReview.script_id == script_id)
        .order_by(StoryReview.created_at.desc())
    ).first()


def story_gate(session: Session, script_id: str) -> tuple[bool, str]:
    """Whether this script may be produced, and why not when it may not.

    The gate the Owner asked for: a script does not reach the prompt agent — the step that
    spends money — until the story has been reviewed and passed. A script nobody has reviewed
    is not refused for being unreviewed; it is refused for having no review, which is the
    same sentence read honestly, and the runbook always produces one.
    """
    review = latest_review(session, script_id)
    if review is None:
        return False, (
            "Scenariul nu a trecut prin recenzia de poveste. Nimic nu intră în producție "
            "înainte ca povestea să fie citită: o rescriere de text nu costă nimic, un cadru "
            "regenerat costă dolari."
        )
    if review.verdict != "PASS":
        notes = (review.notes_json or {}).get("notes") or []
        return False, (
            f"Recenzia de poveste s-a încheiat cu {review.verdict}. "
            + " ".join(str(note) for note in notes[:3])
        )
    return True, ""
