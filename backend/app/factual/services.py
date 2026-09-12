"""Phase 4 Factual Intelligence & Verification services.

Implements Idea generation, source snapshot hashing, atomic claim extraction,
strict fact-checking gate matrix, and scriptwriting with verified citations.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.factual.models import FactualClaim, HookOption, ScriptDraft, SourceSnapshot, TopicIdea
from app.factual.sanitizer import sanitize_untrusted_text
from app.factual.schemas import (
    ExtractClaimItem,
    FactualClaimView,
    HookOptionView,
    ScriptDraftView,
    SourceSnapshotView,
    TopicIdeaView,
)
from app.services import append_event, utc_now

logger = logging.getLogger("studio.factual")


class FactualGateError(Exception):
    """Raised when a script references unverified or refuted claims."""

    def __init__(self, message: str, unverified_claim_ids: list[str]) -> None:
        super().__init__(message)
        self.unverified_claim_ids = unverified_claim_ids


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 digest of normalized text."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def compute_novelty_score(session: Session, new_topic: str) -> float:
    """Compute novelty score (0.1 to 1.0) against recent historical topics.

    Prevents repetitive content drift per 44_CONTENT_DEDUPLICATION_NOVELTY.md.
    """
    recent_topics = session.scalars(
        select(TopicIdea.topic).order_by(TopicIdea.created_at.desc()).limit(20)
    ).all()
    if not recent_topics:
        return 1.0

    norm_new = set(new_topic.lower().split())
    max_overlap = 0.0
    for t in recent_topics:
        norm_t = set(t.lower().split())
        if not norm_t:
            continue
        overlap = len(norm_new & norm_t) / max(len(norm_new | norm_t), 1)
        if overlap > max_overlap:
            max_overlap = overlap

    novelty = round(max(0.1, 1.0 - max_overlap), 2)
    return novelty


def propose_topic_idea(
    engine: Engine,
    title: str,
    topic: str,
    angle: str,
    target_audience: str,
    correlation_id: str,
) -> dict:
    """Create a candidate topic idea with deduplication/novelty scoring."""
    idea_id = str(uuid4())
    now = utc_now()

    with Session(engine) as session, session.begin():
        novelty = compute_novelty_score(session, topic)
        event = append_event(
            session,
            "factual.topic_proposed",
            "topic_idea",
            idea_id,
            1,
            {"title": title, "topic": topic, "novelty_score": novelty},
            correlation_id,
        )
        idea = TopicIdea(
            id=idea_id,
            title=title,
            topic=topic,
            angle=angle,
            target_audience=target_audience,
            novelty_score=novelty,
            status="PROPOSED",
            created_at=now,
            event_id=event.event_id,
        )
        session.add(idea)
        session.flush()
        return TopicIdeaView.model_validate(idea).model_dump()


class TopicNotProducible(ValueError):
    """The topic cannot go into production, and the reason says why."""


def select_topic(
    engine: Engine,
    topic_id: str,
    correlation_id: str,
    decided_by: str | None = None,
    decision_notes: str | None = None,
) -> dict:
    """Move a topic into production, but only if there is something true to say about it.

    Selection is the point where a candidate becomes the day's work, so the condition is the one
    that matters downstream: at least one claim about this topic has been verified as SUPPORTED.
    A topic whose claims are all unverified or refuted has nothing a script could be written
    from, and selecting it would only push the refusal one stage later.

    Idempotent: selecting an already selected topic returns it unchanged rather than appending a
    second event for a decision that was already taken.
    """
    with Session(engine) as session, session.begin():
        topic = session.get(TopicIdea, topic_id)
        if topic is None:
            raise TopicNotProducible(f"Topic {topic_id} not found")
        if topic.status == "SELECTED":
            return TopicIdeaView.model_validate(topic).model_dump()
        if topic.status not in ("PROPOSED", "RESEARCHED"):
            raise TopicNotProducible(
                f"Topic is {topic.status}; only a proposed or researched topic can be selected."
            )
        supported = session.scalar(
            select(func.count())
            .select_from(FactualClaim)
            .where(FactualClaim.topic_id == topic_id, FactualClaim.status == "SUPPORTED")
        )
        if not supported:
            raise TopicNotProducible(
                "The topic has no SUPPORTED claim; there is nothing verified to write from."
            )
        event = append_event(
            session,
            "factual.topic_selected",
            "topic_idea",
            topic_id,
            2,
            {"title": topic.title, "supported_claims": int(supported)},
            correlation_id,
        )
        topic.status = "SELECTED"
        topic.event_id = event.event_id
        topic.selected_at = utc_now()
        if decided_by:
            topic.decided_by = decided_by[:100]
            topic.decision_notes = (decision_notes or "").strip()[:2000] or None
        session.flush()
        return TopicIdeaView.model_validate(topic).model_dump()


def list_topic_ideas(engine: Engine, status: str | None = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(TopicIdea).order_by(TopicIdea.created_at.desc())
        if status:
            stmt = stmt.where(TopicIdea.status == status)
        ideas = session.scalars(stmt).all()
        return [TopicIdeaView.model_validate(i).model_dump() for i in ideas]


def ingest_source_snapshot(
    engine: Engine,
    url: str,
    title: str,
    publisher: str,
    author: str | None,
    raw_content: str,
    credibility_score: float,
    correlation_id: str,
    topic_id: str | None = None,
) -> dict:
    """Ingest research source with SHA-256 hashing and prompt-injection sanitization."""
    snapshot_id = str(uuid4())
    content_hash = compute_content_hash(raw_content)
    now = utc_now()

    san_res = sanitize_untrusted_text(raw_content)
    sanitized_content = san_res.sanitized_text

    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "factual.source_ingested",
            "source_snapshot",
            snapshot_id,
            1,
            {
                "url": url,
                "publisher": publisher,
                "content_hash": content_hash,
                "has_injection": san_res.has_injection,
                "flagged_reasons": san_res.flagged_reasons,
            },
            correlation_id,
        )
        snapshot = SourceSnapshot(
            id=snapshot_id,
            topic_id=topic_id,
            url=url,
            title=title,
            publisher=publisher,
            author=author,
            content_hash=content_hash,
            raw_content=raw_content,
            sanitized_content=sanitized_content,
            credibility_score=credibility_score,
            fetched_at=now,
            event_id=event.event_id,
        )
        session.add(snapshot)
        session.flush()
        return SourceSnapshotView.model_validate(snapshot).model_dump()


def extract_claims(
    engine: Engine,
    source_id: str,
    claims_data: list[ExtractClaimItem],
    correlation_id: str,
    topic_id: str | None = None,
    extracted_by_agent_id: str | None = None,
) -> list[dict]:
    """Record atomic claims from a source snapshot, all UNVERIFIED.

    ``extracted_by_agent_id`` names the agent that read the source, when one did. It is what
    later lets verification refuse to use that same agent as its own fact-checker.
    """
    now = utc_now()
    results = []

    with Session(engine) as session, session.begin():
        source = session.get(SourceSnapshot, source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        resolved_topic_id = topic_id or source.topic_id

        for item in claims_data:
            claim_id = str(uuid4())
            event = append_event(
                session,
                "factual.claim_extracted",
                "factual_claim",
                claim_id,
                1,
                {"claim_type": item.claim_type, "importance": item.importance},
                correlation_id,
            )
            claim = FactualClaim(
                id=claim_id,
                source_id=source_id,
                topic_id=resolved_topic_id,
                claim_text=item.claim_text,
                claim_type=item.claim_type,
                importance=item.importance,
                status="UNVERIFIED",
                confidence=item.confidence,
                created_at=now,
                extracted_by_agent_id=extracted_by_agent_id,
                event_id=event.event_id,
            )
            session.add(claim)
            session.flush()
            results.append(FactualClaimView.model_validate(claim).model_dump())

    return results


def verify_claim(
    engine: Engine,
    claim_id: str,
    status: str,
    confidence: float,
    verifier_notes: str,
    evidence_text: str | None,
    correlation_id: str,
    verified_by_agent_id: str | None = None,
) -> dict:
    """Record a verdict on a claim, with the evidence and the notes behind it.

    UNCERTAIN is a real outcome, not a failure: a fact-checker that cannot find support in the
    source must be able to say so, and the content gate treats anything short of SUPPORTED as
    unusable. Forcing a binary verdict would push a guess into the record.
    """
    if status not in ("SUPPORTED", "REFUTED", "UNCERTAIN", "UNVERIFIED"):
        raise ValueError(f"Invalid claim verification status: {status}")

    now = utc_now()
    with Session(engine) as session, session.begin():
        claim = session.get(FactualClaim, claim_id)
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")

        claim.status = status
        claim.confidence = confidence
        claim.verifier_notes = verifier_notes
        claim.evidence_text = evidence_text
        claim.verified_at = now
        claim.verified_by_agent_id = verified_by_agent_id

        event = append_event(
            session,
            "factual.claim_verified",
            "factual_claim",
            claim_id,
            1,
            {
                "status": status,
                "confidence": confidence,
                "verified_by_agent_id": verified_by_agent_id,
            },
            correlation_id,
        )
        claim.event_id = event.event_id
        session.flush()
        return FactualClaimView.model_validate(claim).model_dump()


def list_claims(
    engine: Engine,
    topic_id: str | None = None,
    source_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    with Session(engine) as session:
        stmt = select(FactualClaim).order_by(FactualClaim.created_at.desc())
        if topic_id:
            stmt = stmt.where(FactualClaim.topic_id == topic_id)
        if source_id:
            stmt = stmt.where(FactualClaim.source_id == source_id)
        if status:
            stmt = stmt.where(FactualClaim.status == status)
        claims = session.scalars(stmt).all()
        return [FactualClaimView.model_validate(c).model_dump() for c in claims]


def evaluate_factual_gate(session: Session, claim_ids: list[str]) -> tuple[bool, list[str]]:
    """Strict Content Gate: All referenced claims must have status SUPPORTED.

    Returns (gate_passed, unverified_or_refuted_claim_ids).
    Any REFUTED or UNVERIFIED claim fails the gate.
    """
    if not claim_ids:
        return False, []

    unverified_or_refuted = []
    for cid in claim_ids:
        claim = session.get(FactualClaim, cid)
        if not claim or claim.status != "SUPPORTED":
            unverified_or_refuted.append(cid)

    passed = len(unverified_or_refuted) == 0
    return passed, unverified_or_refuted


def generate_script_draft(
    engine: Engine,
    topic_id: str,
    title: str,
    target_duration_seconds: int,
    voiceover_full_text: str,
    scenes: list[dict[str, Any]],
    referenced_claim_ids: list[str],
    correlation_id: str,
    story: dict[str, Any] | None = None,
) -> dict:
    """Generate script draft, enforcing strict factual verification gate.

    `story` is what the script is about as a story — one message, the takeaway, the hook, the
    ending, the call to action and its kind, the structure and the narration length. It is
    stored with the draft because the review before production, the prompt agent and the
    Director all need the same answer to "what is this film for".
    """
    draft_id = str(uuid4())
    now = utc_now()

    with Session(engine) as session:
        topic = session.get(TopicIdea, topic_id)
        if not topic:
            raise ValueError(f"Topic {topic_id} not found")

        # Determine version number for topic
        existing_count = session.scalars(
            select(ScriptDraft).where(ScriptDraft.topic_id == topic_id)
        ).all()
        version = len(existing_count) + 1

        # Check factual gate
        gate_passed, unverified_ids = evaluate_factual_gate(session, referenced_claim_ids)

        if not gate_passed:
            # Gate FAILED: record blocked draft with unverified claims
            event = append_event(
                session,
                "factual.script_blocked_by_gate",
                "script_draft",
                draft_id,
                1,
                {"topic_id": topic_id, "unverified_claim_ids": unverified_ids},
                correlation_id,
            )
            draft = ScriptDraft(
                id=draft_id,
                topic_id=topic_id,
                version=version,
                title=title,
                target_duration_seconds=target_duration_seconds,
                voiceover_full_text=voiceover_full_text,
                scenes_json=scenes,
                status="BLOCKED_UNVERIFIED_CLAIMS",
                claim_ids_json=referenced_claim_ids,
                unverified_claim_ids_json=unverified_ids,
                story_json=dict(story or {}),
                created_at=now,
                event_id=event.event_id,
            )
            session.add(draft)
            session.commit()
            raise FactualGateError(
                f"Factual gate failed: referenced claims {unverified_ids} are not SUPPORTED",
                unverified_ids,
            )

        # Gate PASSED: create valid verified draft
        event = append_event(
            session,
            "factual.script_verified_pass",
            "script_draft",
            draft_id,
            1,
            {"topic_id": topic_id, "claims_count": len(referenced_claim_ids)},
            correlation_id,
        )
        draft = ScriptDraft(
            id=draft_id,
            topic_id=topic_id,
            version=version,
            title=title,
            target_duration_seconds=target_duration_seconds,
            voiceover_full_text=voiceover_full_text,
            scenes_json=scenes,
            status="VERIFIED_PASS",
            claim_ids_json=referenced_claim_ids,
            unverified_claim_ids_json=[],
            story_json=dict(story or {}),
            created_at=now,
            event_id=event.event_id,
        )
        session.add(draft)
        session.commit()
        return ScriptDraftView.model_validate(draft).model_dump()


def approve_script_draft(engine: Engine, script_id: str, correlation_id: str) -> dict:
    """Owner approval of a script draft, re-checking the factual gate at approval time.

    Without this step a draft created through the real API (`VERIFIED_PASS`) could never reach
    the `APPROVED` status that storyboarding requires — before the audit, only a fixture
    endpoint that wrote `APPROVED` directly could feed the media pipeline.

    Approval re-evaluates every referenced claim rather than trusting the status recorded when
    the draft was written: a claim may have been refuted since (50_CONTENT_GATE_MATRIX.md,
    "if content changes materially after a gate passes, invalidate/re-run affected gates").
    """
    with Session(engine) as session:
        draft = session.get(ScriptDraft, script_id)
        if not draft:
            raise ValueError(f"Script draft {script_id} not found")
        already_approved = draft.status == "APPROVED"
        if draft.status not in ("DRAFT", "VERIFIED_PASS", "APPROVED", "BLOCKED_UNVERIFIED_CLAIMS"):
            raise ValueError(f"Cannot approve a script with status {draft.status!r}")

        gate_passed, unverified_ids = evaluate_factual_gate(session, list(draft.claim_ids_json))
        if not gate_passed:
            draft.status = "BLOCKED_UNVERIFIED_CLAIMS"
            draft.unverified_claim_ids_json = unverified_ids
            append_event(
                session,
                "factual.script_blocked_by_gate",
                "script_draft",
                script_id,
                1,
                {"unverified_claim_ids": unverified_ids, "at": "approval"},
                correlation_id,
            )
            session.commit()
            raise FactualGateError(
                f"Cannot approve: referenced claims {unverified_ids} are not SUPPORTED",
                unverified_ids,
            )

        if already_approved:
            return ScriptDraftView.model_validate(draft).model_dump()

        event = append_event(
            session,
            "factual.script_approved",
            "script_draft",
            script_id,
            1,
            {"claims_count": len(draft.claim_ids_json)},
            correlation_id,
        )
        draft.status = "APPROVED"
        draft.unverified_claim_ids_json = []
        draft.event_id = event.event_id
        session.commit()
        session.refresh(draft)
        return ScriptDraftView.model_validate(draft).model_dump()


def generate_hook_options(
    engine: Engine,
    script_id: str,
    hooks_data: list[dict[str, Any]],
    correlation_id: str,
) -> list[dict]:
    """Generate hook options for a verified script."""
    now = utc_now()
    results = []

    with Session(engine) as session, session.begin():
        script = session.get(ScriptDraft, script_id)
        if not script:
            raise ValueError(f"Script {script_id} not found")

        for item in hooks_data:
            hook_id = str(uuid4())
            hook = HookOption(
                id=hook_id,
                script_id=script_id,
                hook_text=item["hook_text"],
                hook_technique=item.get("hook_technique", "CURIOSITY_GAP"),
                retention_score_estimate=item.get("retention_score_estimate", 7.0),
                is_selected=False,
                created_at=now,
            )
            session.add(hook)
            session.flush()
            results.append(HookOptionView.model_validate(hook).model_dump())

        append_event(
            session,
            "factual.hooks_generated",
            "script_draft",
            script_id,
            1,
            {"count": len(results)},
            correlation_id,
        )

    return results


def list_scripts(engine: Engine, topic_id: str | None = None) -> list[dict]:
    with Session(engine) as session:
        stmt = select(ScriptDraft).order_by(ScriptDraft.created_at.desc())
        if topic_id:
            stmt = stmt.where(ScriptDraft.topic_id == topic_id)
        scripts = session.scalars(stmt).all()
        return [ScriptDraftView.model_validate(s).model_dump() for s in scripts]


def list_hooks(engine: Engine, script_id: str) -> list[dict]:
    with Session(engine) as session:
        stmt = (
            select(HookOption)
            .where(HookOption.script_id == script_id)
            .order_by(HookOption.retention_score_estimate.desc())
        )
        hooks = session.scalars(stmt).all()
        return [HookOptionView.model_validate(h).model_dump() for h in hooks]
