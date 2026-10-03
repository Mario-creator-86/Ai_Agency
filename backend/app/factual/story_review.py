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
from app.factual.grounding import grounding_check, script_grounding
from app.factual.models import ScriptDraft, StoryReview
from app.factual.sanitizer import wrap_in_inert_boundary
from app.services import append_event, utc_now
from app.wording import review_verdict

logger = logging.getLogger("studio.story_review")

REVIEWER_ROLE = "Director"
TEMPLATE_VERSION = "story-review-v1"

#: The seconds a short is judged at. Three is where a viewer decides to stay, twenty-five is
#: where they decide whether the ending was worth it.
MARKS = ("0", "3", "5", "10", "15", "20", "25", "end")

#: Checks a rewrite cannot fix, because they are not about the writing. A scene with no
#: verified claim behind it is a research problem: the film waits for evidence, not for prose.
FATAL_CHECKS = ("every_scene_is_attributed",)

#: Checks that are measured and reported but do not refuse a script on their own.
#:
#: `ending_answers_the_hook` compares the content words of the hook with those of the payoff
#: onward — and a good ending answers its hook in different words. Found live: a hook of "it
#: was supposed to work 14 months; it guarded Earth for over a decade" closed with "it spent
#: eleven years watching for things that burn in our sky, and ended as one of them". That
#: ending answers that hook exactly. It shares no word with it, so the check refused the script
#: four times running and the story was spent on the wall. Whether an ending answers its
#: opening is a question about meaning, and nothing that counts words can decide it. It stays
#: measured, it reaches the Director as a flag to look at, and it no longer refuses by itself —
#: the reader decides.
#:
#: `ending_loops_to_hook` (2026-10-02, audit Q5) asks whether the last line leads back into
#: the opening, so a short watched in a loop reads as one story. The same limit applies: it
#: counts shared words, and a loop can be made in other words. It is a flag for the reader.
ADVISORY_CHECKS = ("ending_answers_the_hook", "ending_loops_to_hook")

#: How many times the studio asks for a rewrite before the story is refused.
#:
#: It was two, on the reasoning that a third attempt on the same evidence produces a third
#: version of the same weakness. That reasoning was about cost, and cost is not the constraint
#: here — the Owner settled it: "we have plenty of tokens; the day does not close after two
#: attempts. We can have ten or twenty exchanges until we have a film. The day closes when the
#: short is published." Rewriting text is the cheapest thing the studio does; a render is not.
#: So the writer's room stays open. The room is twenty exchanges (`MAX_SCRIPT_EXCHANGES`) and
#: the twentieth is the decision, which is why this number is nineteen: on the reading after
#: the last stalled round the Director must answer PASS or REJECT rather than ask again.
MAX_REVISIONS = 19

#: How many readings one story gets before the room closes — the Owner's number. The twentieth
#: is the decision, not another request.
MAX_EXCHANGES = 20


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


def blocking_count(review: StoryReview) -> int:
    """How many refusing checks a past reading found. Advisory flags do not count."""
    notes = review.notes_json or {}
    failures = list(notes.get("failed") or [])
    flagged = set(notes.get("flagged") or [])
    return len([name for name in failures if name not in flagged and name not in ADVISORY_CHECKS])


def stalled_rounds(history: list[StoryReview]) -> int:
    """Rewrites since the story last got better than it had ever been.

    Progress is measured the only way the studio can measure it without asking anyone: the
    number of checks that refuse. A draft that breaks fewer of them than any draft before it
    is progress, and the room reopens. Rounds after that, with nothing improving, are what the
    budget is counting — a conversation going in circles, not a conversation.
    """
    best: int | None = None
    stalled = 0
    for review in history:
        count = blocking_count(review)
        if best is None or count < best:
            best = count
            stalled = 0
            continue
        if review.verdict == "REVISE":
            stalled += 1
    return stalled


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
    # What the studio measured about whether the narration says what its claims and its topic
    # say (`app.factual.grounding`), so her reading can cite the numbers instead of guessing
    # them. None for a dramatisation of the serial, which makes no claims to say.
    grounding = script_grounding(session, script)
    return {
        "title": script.title,
        "topic": topic.title if topic else "",
        "thesis": (topic.thesis_json if topic and topic.thesis_json else {}),
        "story": dict(script.story_json or {}),
        "target_seconds": script.target_duration_seconds,
        "estimated_seconds": expected_seconds(script.scenes_json or []),
        "scenes": scenes,
        # Last, because the payload she reads is cut at a fixed length and the scenes are
        # what she must not lose.
        "grounding": grounding,
    }


def review_story(
    engine: Engine,
    registry: Any,
    script_id: str,
    correlation_id: str | None = None,
    *,
    target_seconds: int | None = None,
    continuous: bool = False,
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
        # Whether the narration says what its topic and its claims say. Measured on the
        # rehearsal of 2026-09-18: a telescope film on the Nepal climate-finance topic cited a
        # SUPPORTED Nepal claim and passed every check above, because none of them reads the
        # claims. It refuses as a rewrite (REVISE), not as a closed story: the writer can
        # write the film its claims allow, and the notes say which claim went unsaid.
        if facts["grounding"] is not None:
            checks["narration_is_grounded"] = grounding_check(facts["grounding"])
        earlier = session.scalar(
            select(StoryReview).where(StoryReview.script_id == script_id).limit(1)
        )
        # How many times this STORY has been sent back without getting anywhere.
        #
        # It counted rows first, and every rewrite writes a new row, so the budget never ran
        # out. Then it counted every rewrite of the topic — and spent the budget on drafts
        # that were getting better every time, including on rounds the studio's own faults
        # had caused. A story was refused at the wall while it was still improving, which is
        # the opposite of what a budget is for. The budget is for going nowhere: a draft that
        # is better than anything seen so far reopens the room, and the count starts again.
        history = list(
            session.scalars(
                select(StoryReview)
                .join(ScriptDraft, ScriptDraft.id == StoryReview.script_id)
                .where(ScriptDraft.topic_id == script.topic_id)
                .order_by(StoryReview.created_at)
            )
            if script.topic_id
            else session.scalars(
                select(StoryReview)
                .where(StoryReview.script_id == script_id)
                .order_by(StoryReview.created_at)
            )
        )
        revisions = stalled_rounds(history)
        # Two different numbers, and they were the same one by mistake: which reading this is
        # (what she is told, so she can see the conversation) and how many readings changed
        # nothing (what the budget counts).
        exchange = len(history) + 1
        reviewer = agent_for_role(session, REVIEWER_ROLE)
        reviewer_id = reviewer.id if reviewer else None
        # What she said the last time she read this story, so this reading continues the
        # conversation instead of starting a new one.
        previous = None
        if script.topic_id:
            previous = session.scalars(
                select(StoryReview)
                .join(ScriptDraft, ScriptDraft.id == StoryReview.script_id)
                .where(ScriptDraft.topic_id == script.topic_id)
                .order_by(StoryReview.created_at.desc())
            ).first()
        earlier_notes = list((previous.notes_json or {}).get("notes") or []) if previous else []

    every_failure = failed(checks)
    # What the arithmetic may refuse on, and what it may only point at.
    broken = [name for name in every_failure if name not in ADVISORY_CHECKS]
    # The wall: nothing has improved for the length of the budget, or the room is out of
    # readings. Either way there will be no rewrite after this one, so this reading has to be
    # a decision rather than another request.
    at_the_wall = not continuous and (revisions >= MAX_REVISIONS or exchange >= MAX_EXCHANGES)
    flagged = [name for name in every_failure if name in ADVISORY_CHECKS]
    notes = revision_notes(checks)
    verdict = "PASS" if not broken else "REVISE"
    if any(name in FATAL_CHECKS for name in broken):
        verdict = "REJECT"
    elif broken and at_the_wall:
        verdict = "REJECT"
        notes.append(
            f"Ultimele {revisions} rescrieri nu au îmbunătățit nimic măsurabil; povestea nu se "
            "susține pe dovezile existente."
        )

    scores: dict[str, Any] = {}
    retention: dict[str, Any] = {}
    run_id = None
    if reviewer_id is not None and registry is not None:
        try:
            opinion, run_id = _ask_director(
                engine,
                registry,
                reviewer_id,
                facts,
                correlation,
                broken,
                flagged=flagged,
                exchange=exchange,
                last_exchange=MAX_EXCHANGES,
                must_decide=at_the_wall,
                earlier_notes=earlier_notes,
                continuous=continuous,
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
                # At the last exchange her answer has to be a decision. Asking for another
                # rewrite when there will be no rewrite is a refusal, and the studio records
                # it as one rather than ending the day having quietly made nothing. Her
                # authority is untouched: what is refused here is still refused — it is only
                # named.
                if verdict == "REVISE" and at_the_wall:
                    verdict = "REJECT"
                    notes.append(
                        f"La ultimul schimb ({exchange}) Directorul a cerut din nou "
                        "modificări, deci povestea nu se publică: un REVISE fără o rescriere "
                        "care să urmeze este un refuz."
                    )

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
                "failed": every_failure[:6],
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
                notes_json={
                    "notes": notes[:12],
                    "failed": every_failure,
                    "flagged": flagged,
                },
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
                subject=f"Povestea «{facts['title'][:60]}»: {review_verdict(verdict)}",
                body={"kind": "story_review", "verdict": verdict, "failed": broken[:6]},
                body_text=(
                    "Scenariul nu poate intra în producție așa cum e "
                    f"({review_verdict(verdict)}). " + " ".join(notes[:6])
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
    *,
    flagged: list[str] | None = None,
    exchange: int = 1,
    last_exchange: int = 1,
    must_decide: bool = False,
    earlier_notes: list[str] | None = None,
    continuous: bool = False,
) -> tuple[StoryVerdict | None, str | None]:
    """The Director's own reading of the script. Her answer is an opinion, recorded as one.

    She used to be asked in a vacuum: here is a script, what is wrong with it. Asked that
    nine times about nine drafts of one story, she answered nine times — every draft passed
    every computed check from the second one on, and she still found something, because there
    is always something. A reviewer who cannot see the conversation cannot finish it. So she is
    told which exchange this is, what she asked for last time, and that the last exchange is a
    decision: a REVISE there is a refusal that will not say its name.
    """
    payload = json.dumps(facts, ensure_ascii=False, default=str)[:14000]
    prompt = _INSTRUCTIONS
    prompt += (
        f"\nThis is exchange {exchange}. Continue revising until the checks pass; "
        "there is no attempt limit. Never approve unsupported facts.\n"
        if continuous
        else f"\nThis is exchange {exchange} of at most {last_exchange} on this story.\n"
    )
    if earlier_notes:
        prompt += (
            "What you asked for last time:\n"
            + "\n".join(f"- {note}" for note in earlier_notes[:8])
            + "\nFor each one, say whether this draft addressed it. A note you have already "
            "given and the writer has acted on is settled — do not raise it again, and do not "
            "trade it for a new one of the same size. The question is whether the film is good "
            "enough to publish, not whether it is perfect.\n"
        )
    if must_decide:
        prompt += (
            "This is the LAST exchange. Answer PASS or REJECT, not REVISE: if you would "
            "publish it, say PASS; if the story cannot carry a short, say REJECT. A REVISE "
            "here is a refusal without the word, and the studio would end the day with "
            "nothing made.\n"
        )
    if broken:
        prompt += (
            "The studio's own checks already found: "
            + "; ".join(broken[:6])
            + ". Say what to change, and do not return PASS.\n"
        )
    if flagged:
        prompt += (
            "The studio's checks also flagged, without refusing: "
            + "; ".join(flagged[:4])
            + ". These count words as a proxy for a question only a reader can answer — an "
            "ending may answer its hook perfectly in entirely different words. Judge it "
            "yourself and say so; the flag is not a verdict.\n"
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
    # Measured again here rather than trusted from the review: a PASS written before the
    # narration was measured, or by hand, must not buy a shot for a film about something its
    # claims never say. The measurement is text against rows and costs nothing.
    grounding = script_grounding(session, session.get(ScriptDraft, script_id))
    if grounding is not None and not grounding["passed"]:
        return False, (
            "Narațiunea nu spune ce spun afirmațiile și subiectul ei. "
            + " ".join(grounding["reasons"][:3])
        )
    return True, ""
