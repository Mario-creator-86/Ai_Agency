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

- **Then her editorial judgement** (2026-10-11, the Owner's card of 23:30; `judged_story`):
  the review above passed the ATLAS/Higgs Short — attributed, in length, a hook that was not
  «did you know» — and it was jargon for experts, with a call to action for experts. So a
  PASS is read once more as a stranger hears it (`script_as_text`) and scored on five
  criteria by `app.agents.editorial_judgement`; below the bar the Scriptwriter rewrites on her
  brief (`agent_write_script` with the brief as its notes: a new draft, its claims checked, its
  story reviewed again), up to `Settings.editorial_rounds` versions, and the best-scored
  version whose story review passed ships — the runbook approves and storyboards that one.
  Every version read is an `editorial.judged` event; the chosen version's scores stay on its
  story_json (`editorial`) for the weekly review, and a version it supersedes is marked so,
  owing the room nothing more (`runbook.stages.script_work`).

- **Her letter reaches the writer** (2026-10-13, the Owner: «Directorul comunică cu fiecare
  și poate întoarce către el indicații noi?»): a REVISE or REJECT used to be posted to her
  own inbox, where the Scriptwriter never read it. It is now a REQUEST_REVIEW addressed to
  him, with her retention row and the span where she loses the viewer in its words
  (`letter_to_writer`); it enters his every run until a later draft of the story passes and
  `_settle_writer_letters` resolves it. When a story ships, what it scored and her last note
  become one AGENT_OPINION on his memory (`remember_shipped_story`).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.editorial_judgement import (
    CRITERION_KEYS,
    FACTUAL_SHORT,
    MAX_SCORE,
    EditorialOutcome,
    Version,
    editorial_loop,
    letter_to_owner,
    record_rounds,
)
from app.agents.identity import cut_at_word, parse_structured
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message, resolve_message
from app.agents.models import AgentMessage
from app.agents.services import run_agent_task
from app.factual.agent_pipeline import (
    PREFERRED_WRITER_ROLE,
    NoVerifiedClaims,
    ScriptRejected,
    agent_write_script,
)
from app.factual.editorial import failed, revision_notes, story_checks
from app.factual.grounding import grounding_check, script_grounding
from app.factual.models import ScriptDraft, StoryReview
from app.factual.sanitizer import wrap_in_inert_boundary
from app.factual.services import FactualGateError
from app.media.film_length import factual_film_length, factual_rows
from app.services import append_event, utc_now
from app.wording import count, decimal, review_verdict

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

#: Said when the studio goes on past a second matter-of-taste REVISE (see `_taste_only`).
TASTE_SETTLED_RO = (
    "Scenariul trece toate verificările, iar Directorul a cerut din nou doar retușuri de gust, "
    "după ce povestea fusese deja rescrisă o dată pentru gust: studioul merge mai departe, iar "
    "notele lui rămân sugestii pentru filmare."
)


def _taste_only(review: StoryReview | None) -> bool:
    """Whether a past reading sent the story back on taste alone: REVISE while every check
    that may refuse had passed.

    2026-10-10 (film «How NASA Keeps a Space Telescope Alive With Frozen Fuel»): the sheet
    repair sent the story round five times; the last two drafts passed every computed check
    and the Director still answered REVISE, each rewrite a new draft she could find something
    in, until the repair paused and wrote to the Owner. Taste may send a passing draft back
    once, with her notes for the writer; a second time in a row it is a loop, not a review,
    and the studio decides on its own (the Owner: «studioul trebuie să rezolve singur, fără
    intervenții»). Once per story, not once in a row: the same day the rewrites alternated
    between her taste and a check the rewrite broke, and never met twice in a row. A reading
    recorded before the marker counts when its failures were stored and none of them refuses."""
    if review is None or review.verdict != "REVISE":
        return False
    notes = review.notes_json or {}
    if notes.get("taste_only") is True:
        return True
    return "failed" in notes and blocking_count(review) == 0


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


def retention_sentence(retention: dict[str, Any]) -> str:
    """Her retention row as a sentence the writer reads: «Reținerea la care se așteaptă
    Directorul: 100% la 0 s, 70% la 3 s, 40% la final; pierde publicul la 3-9: …». A mark she
    left at 0 is not said (the row's default is 0 for a mark she did not give); empty when no
    model answered and the row is empty."""
    marks = []
    for mark in MARKS:
        value = retention.get(f"at_{mark}")
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        if value <= 0 and mark != "0":
            continue
        marks.append(f"{int(value)}% la {'final' if mark == 'end' else f'{mark} s'}")
    if not marks:
        return ""
    said = "Reținerea la care se așteaptă Directorul: " + ", ".join(marks)
    span = " ".join(str(retention.get("collapse_at") or "").split())
    why = " ".join(str(retention.get("why") or "").split())
    if span:
        said += f"; pierde publicul la {span}" + (f": {why}" if why else "")
    elif why:
        said += f"; {why}"
    return said + "."


def letter_to_writer(verdict: str, notes: list[str], retention: dict[str, Any]) -> str:
    """The words of her letter to the Scriptwriter: the verdict, her notes, and where she
    expects to lose the viewer (`retention_sentence`), so the next draft is written to the
    row she judged against, not only to the notes."""
    words = (
        f"Scenariul nu poate intra în producție așa cum e ({review_verdict(verdict)}). "
        + " ".join(str(note) for note in notes)
    ).strip()
    expected = retention_sentence(retention)
    return f"{words} {expected}".strip() if expected else words


def _settle_writer_letters(
    session: Session,
    *,
    writer_id: str | None,
    topic_id: str | None,
    script_id: str,
    resolved_by: str,
    correlation_id: str,
) -> int:
    """The story-review letters still open on the writer's desk for this topic, resolved now
    that a draft of it passed: what they asked for is done, and a letter left open would sit
    in his every prompt beside the next story's. Returns how many were resolved."""
    if writer_id is None or not topic_id:
        return 0
    rows = session.scalars(
        select(AgentMessage).where(
            AgentMessage.to_agent_id == writer_id, AgentMessage.status == "OPEN"
        )
    ).all()
    settled = 0
    for row in rows:
        body = row.body_json if isinstance(row.body_json, dict) else {}
        if body.get("kind") != "story_review" or body.get("topic_id") != topic_id:
            continue
        resolve_message(
            session,
            row.id,
            resolution=f"Versiunea {script_id[:8]} a trecut recenzia de poveste.",
            resolved_by=resolved_by,
            correlation_id=correlation_id,
        )
        settled += 1
    return settled


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
        # The film the montage will cut, as the length check measures it.
        "estimated_seconds": factual_film_length(script.scenes_json or []).seconds,
        "scenes": scenes,
        # Last, because the payload she reads is cut at a fixed length and the scenes are
        # what she must not lose.
        "grounding": grounding,
    }


def scene_clip_check(engine: Engine, scenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Whether every filmed scene fits one clip of the studio's motion model, slowed down
    locally by at most SLOWDOWN_ALLOWANCE; None when no motion model is selected.

    2026-10-10 (film «How NASA Keeps a Space Telescope Alive With Frozen Fuel»): two scenes
    carried words for 11.1 s and 12.5 s of clip under a model whose clips end at 10 s, and
    nothing said so until the shooting sheet, after the story had passed. The length is
    estimated as the motion step will buy it (`assembler.script_clip_seconds`), and the
    refusal names each scene's seconds, so the writer splits it in the next draft.

    Since 2026-10-16 the montage cuts a LIVE scene into shots of its own, each its own clip
    (`montage.factual_shots`): what must fit one clip is each shot as the storyboard will cut
    it (`film_length.factual_rows`), and a scene is measured by its longest shot, as the
    serial's review measures a beat (`story.review._filmable`). With the montage off a scene is
    one shot, and the whole scene is measured as before. A 28-word scene was refused at 12.75 s
    while the montage would have filmed it as three shots of about four seconds."""
    from app.media.assembler import script_clip_seconds, spoken_words  # noqa: PLC0415
    from app.media.cost_plan import SLOWDOWN_ALLOWANCE  # noqa: PLC0415
    from app.media.shooting_sheet import motion_clip_limit  # noqa: PLC0415 - media reads us

    limit = motion_clip_limit(engine)
    if limit is None:
        return None
    model_id, longest = limit
    most = longest * (1 + SLOWDOWN_ALLOWANCE)
    rows = factual_rows(scenes)
    # Each writer's scene by its longest shot: (seconds, the shot's row).
    longest_shot: dict[int, tuple[float, dict[str, Any]]] = {}
    for position, seconds in script_clip_seconds(rows).items():
        row = rows[position - 1]
        number = int(row["scene_number"])
        if number not in longest_shot or seconds > longest_shot[number][0]:
            longest_shot[number] = (seconds, row)
    over = [
        (number, seconds, row)
        for number, (seconds, row) in sorted(longest_shot.items())
        if seconds > most + 1e-9
    ]
    if not over:
        return {
            "passed": True,
            "reason": (
                f"Fiecare scenă filmată încape într-un cadru de {model_id} (cel mult "
                f"{decimal(most)} s, încetinit local)."
            ),
        }

    def refusal(number: int, seconds: float, row: dict[str, Any]) -> str:
        said = spoken_words(str(row.get("narration") or ""))
        shots = int(row.get("of") or 1)
        where = (
            f", în cel mai lung din cele {shots} cadre în care o taie montajul" if shots > 1 else ""
        )
        return (
            f"Scena {number} cere un cadru de {decimal(seconds)} s "
            f"({count(said, 'cuvânt rostit', 'cuvinte rostite')}{where}); {model_id} filmează "
            f"cel mult {longest} s într-un cadru, iar studioul îl încetinește local cu cel mult "
            f"{round(SLOWDOWN_ALLOWANCE * 100)}% ({decimal(most)} s). Împarte scena în două "
            "scene, fiecare cu imaginea ei, sau scurtează-i narațiunea."
        )

    return {
        "passed": False,
        "reason": " ".join(refusal(number, seconds, row) for number, seconds, row in over),
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
        fits = scene_clip_check(engine, list(script.scenes_json or []))
        if fits is not None:
            checks["every_scene_fits_one_clip"] = fits
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
        reviewer_name = reviewer.display_name if reviewer else REVIEWER_ROLE
        # The writer her letter goes to (2026-10-13): the one who holds the role, as
        # `agent_write_script` resolves him; without one, her inbox, as before.
        writer = agent_for_role(session, PREFERRED_WRITER_ROLE)
        writer_id = writer.id if writer else None
        topic_id = script.topic_id
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
        # Whether any earlier reading of this story already sent it back on taste alone. Not
        # only the last one: live the same day, the rewrites alternated (taste, a check the
        # rewrite broke, taste again...), and "twice in a row" never came.
        taste_spent = any(_taste_only(review) for review in history)

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
    # REVISE on her taste alone, every refusing check passed (recorded, so the next reading
    # knows it), and whether this reading went on past such a REVISE.
    taste_only = False
    taste_settled = False
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
            notes.extend(str(note) for note in opinion.notes)
            # The Director may send back a script the checks did not catch; she may not wave
            # through one they did. Taste can be stricter than a rule, never looser — once per
            # story: a second REVISE on taste alone, on a draft that passes every check, is a
            # loop, and the studio goes on (`_taste_only`). Her REJECT stays hers.
            if opinion.verdict == "REVISE" and verdict == "PASS" and taste_spent:
                taste_settled = True
                notes.append(TASTE_SETTLED_RO)
            elif opinion.verdict != "PASS" and verdict == "PASS":
                verdict = opinion.verdict
                taste_only = verdict == "REVISE"
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
                    "notes": notes,
                    "failed": every_failure,
                    "flagged": flagged,
                    "taste_only": taste_only and verdict == "REVISE",
                    "taste_settled": taste_settled,
                },
                estimated_seconds=float(facts["estimated_seconds"]),
                reviewer_agent_id=reviewer_id,
                run_id=run_id,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        if verdict == "PASS":
            _settle_writer_letters(
                session,
                writer_id=writer_id,
                topic_id=topic_id,
                script_id=script_id,
                resolved_by=reviewer_name,
                correlation_id=correlation,
            )
        elif reviewer_id is not None:
            # Her letter goes to the writer (2026-10-13, the Owner: «Directorul comunică cu
            # fiecare și poate întoarce către el indicații noi?»). It was posted to her own
            # inbox (`to_agent_id=None`), so the one employee who had to act on it never read
            # it in his prompt; the retention row she judged against was stored and never
            # told. A REQUEST_REVIEW addressed to him enters his every run
            # (`identity._open_messages`) until a later draft of this story passes.
            post_message(
                session,
                intent="REQUEST_REVIEW",
                subject=f"Povestea «{facts['title']}»: {review_verdict(verdict)}",
                body={
                    "kind": "story_review",
                    "verdict": verdict,
                    "failed": broken[:6],
                    "topic_id": topic_id,
                    "script_id": script_id,
                    "exchange": exchange,
                    "retention": retention,
                },
                body_text=letter_to_writer(verdict, notes, retention),
                from_agent_id=reviewer_id,
                to_agent_id=writer_id,
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
        "notes": notes,
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
    payload = json.dumps(facts, ensure_ascii=False, default=str)
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
            + "\n".join(f"- {note}" for note in earlier_notes)
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
    from app.media.local_media import writer_constraints  # noqa: PLC0415

    local_constraints = writer_constraints(engine, int(facts.get("target_seconds") or 20))
    if local_constraints:
        prompt += local_constraints + (
            "These production limits apply to this review too. A narrative beat may span "
            "adjacent short shots: do not require merging them into a shot longer than the "
            "model supports. Judge the current script supplied below; earlier notes may "
            "describe scenes removed or replaced. Never request unsupported facts or "
            "numbers from an earlier draft.\n"
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
        summary=f"Citesc povestea «{facts['title']}» înainte de producție.",
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
            + " ".join(str(note) for note in notes)
        )
    # Measured again here rather than trusted from the review: a PASS written before the
    # narration was measured, or by hand, must not buy a shot for a film about something its
    # claims never say. The measurement is text against rows and costs nothing.
    grounding = script_grounding(session, session.get(ScriptDraft, script_id))
    if grounding is not None and not grounding["passed"]:
        return False, (
            "Narațiunea nu spune ce spun afirmațiile și subiectul ei. "
            + " ".join(grounding["reasons"])
        )
    return True, ""


# ----------------------------------------------------------------- the editorial judgement
#
# 2026-10-11, the Owner's card of 23:30. The review above asks whether the script is attributed,
# shaped and the right length, and where a viewer would stop; nothing asked whether a stranger
# would start. The judgement below does, after a PASS and before the approval, through
# `app.agents.editorial_judgement`.


def script_as_text(script: ScriptDraft) -> tuple[str, dict[str, Any]]:
    """The script as the viewer meets it, for the editorial judgement: the title, then each
    scene's narration under its purpose and kind, with what is seen in a bracket; beside it the
    small context she may use (the hook, the ending, the call to action, the seconds). The
    claims are not here: they are verified and may not change, and she judges how they are told."""
    story = dict(script.story_json or {})
    scenes = list(script.scenes_json or [])
    rows = [str(script.title or "").strip()]
    purposes: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        purpose = str(scene.get("purpose") or scene.get("story_purpose") or "").upper()
        kind = str(scene.get("scene_kind") or "").upper()
        narration = " ".join(
            str(scene.get("narration") or scene.get("voiceover_segment") or "").split()
        )
        visual = " ".join(
            str(scene.get("visual_description") or scene.get("visual_prompt") or "").split()
        )
        head = f"[{scene.get('scene_number') or index}. {purpose}" + (f", {kind}]" if kind else "]")
        rows.append(f"\n{head} {narration}".rstrip())
        if visual:
            rows.append(f"(seen: {visual[:200]})")
        purposes.append(purpose)
    context = {
        "title": script.title,
        "core_message": story.get("core_message"),
        "hook": story.get("hook"),
        "ending": story.get("ending"),
        "cta": story.get("cta"),
        "cta_kind": story.get("cta_kind"),
        "scenes": len(scenes),
        "purposes": purposes,
        "estimated_seconds": factual_film_length(scenes).seconds,
        "target_seconds": script.target_duration_seconds,
    }
    return "\n".join(rows), context


def _version_of_script(
    script: ScriptDraft, review: dict[str, Any] | None, note: str = ""
) -> Version:
    """One stored draft as the loop reads it: eligible when its story review passed."""
    text, context = script_as_text(script)
    passed = review is not None and review.get("verdict") == "PASS"
    reasons = " ".join(str(n) for n in (review or {}).get("notes") or [])
    return Version(
        id=script.id,
        text=text,
        context=context,
        eligible=passed,
        note=note or ("" if passed else reasons),
        title=str(script.title or ""),
    )


def remember_shipped_story(
    session: Session, outcome: EditorialOutcome, *, title: str, writer_id: str
) -> None:
    """One AGENT_OPINION on the writer's own memory when a story ships (2026-10-13): the
    title, how many versions she read, what the shipped one scored, and her last note — her
    KEEP / CHANGE / AVOID after the last version she sent back, else her reasons on the two
    weakest criteria of the one that shipped. The weekly review measures the film later; this
    is what he can learn before any measurement, among the records his next run recalls."""
    shipped = outcome.shipped
    judged = shipped.judgement
    if judged is None:
        said = f"a plecat nejudecată ({outcome.stopped})"
    else:
        scored = ", ".join(f"{key} {judged.scores[key]}" for key in CRITERION_KEYS)
        said = f"a plecat versiunea {shipped.number} cu {judged.total}/50 ({scored})" + (
            "" if outcome.passed else ", sub prag"
        )
    briefed = next(
        (item for item in reversed(outcome.rounds) if item.brief and item.judgement), None
    )
    if briefed is not None and briefed.judgement is not None:
        note = " ".join(briefed.judgement.answer.brief.words().split())
    elif judged is not None:
        reasons = judged.answer.reasons()
        note = "; ".join(
            f"{key} ({judged.scores[key]}/{MAX_SCORE}): {reasons[key]}"
            for key in judged.weakest
            if reasons.get(key)
        )
    else:
        note = ""
    remember(
        session,
        memory_class="AGENT_OPINION",
        content=(
            f"Povestea «{title}»: "
            f"{count(len(outcome.rounds), 'versiune citită', 'versiuni citite')} de Director; "
            f"{said}. Ultima ei notă: {cut_at_word(note, 300) or 'niciuna'}"
        ),
        source_type="run" if judged is not None and judged.run_id else "system",
        source_id=judged.run_id if judged is not None and judged.run_id else shipped.version.id,
        agent_id=writer_id,
    )


def judged_story(
    engine: Engine,
    registry: Any,
    script_id: str,
    *,
    target_seconds: int,
    language: str = "en",
    correlation_id: str = "",
    rounds: int | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The Director's editorial judgement of a script whose story review passed (2026-10-11).

    ``review`` is that PASS (`review_story`'s answer). The script is read as a stranger hears
    it and scored; below the bar the Scriptwriter rewrites on her brief (`agent_write_script`,
    the brief as its notes: a new draft, its claims checked, read by `review_story` again, so a
    rewrite the review sends back is scored only for the record and never ships), up to
    ``rounds`` versions (`Settings.editorial_rounds`), and the best-scored version whose review
    passed ships. Every version is an `editorial.judged` event; each draft's story_json keeps
    its own record (``editorial``), the shipped one the whole loop, the others which version
    superseded them; one letter to the Owner only when it ships below the bar. A judgement
    she could not give ships the reviewed draft as it is, unjudged.

    Returns ``{"script_id", "review", "editorial", "rewrites", "versions"}``: the version that
    ships (not always ``script_id``), its review for the approval, the loop's record, how many
    rewrites were written, and each version's verdict and total for the day's card.
    """
    correlation = correlation_id or str(uuid4())
    passed = dict(review or {"verdict": "PASS", "failed": [], "notes": []})
    with Session(engine) as session:
        script = session.get(ScriptDraft, script_id)
        if script is None:
            raise StoryReviewError(f"Script {script_id} not found")
        topic_id = script.topic_id
        director = agent_for_role(session, REVIEWER_ROLE)
        director_id = director.id if director is not None else None
        first = _version_of_script(script, passed)
    reviews: dict[str, dict[str, Any]] = {script_id: passed}

    def rewrite(brief: str, number: int) -> Version | None:
        try:
            written = agent_write_script(
                engine,
                registry,
                topic_id,
                str(uuid4()),
                target_duration_seconds=target_seconds,
                language=language,
                notes=[brief],
            )
        except (ScriptRejected, NoVerifiedClaims, FactualGateError, ValueError) as exc:
            # Unattributable narration, no claims, a claim refuted meanwhile, or no answer:
            # nothing was stored, and the loop ships the best it has.
            logger.info(
                "editorial_rewrite_not_stored",
                extra={"topic_id": topic_id, "version": number, "reason": str(exc)[:200]},
            )
            return None
        new_id = str(written["script"]["id"])
        try:
            verdict = review_story(
                engine, registry, new_id, str(uuid4()), target_seconds=target_seconds
            )
        except StoryReviewError as exc:
            with Session(engine) as session:
                row = session.get(ScriptDraft, new_id)
                assert row is not None  # stored above, in this same process
                return _version_of_script(row, None, note=str(exc))
        reviews[new_id] = verdict
        with Session(engine) as session:
            row = session.get(ScriptDraft, new_id)
            assert row is not None
            return _version_of_script(row, verdict)

    outcome = editorial_loop(
        engine,
        registry,
        kind=FACTUAL_SHORT,
        first=first,
        rewrite=rewrite,
        correlation_id=correlation,
        rounds=rounds,
    )
    shipped = outcome.shipped
    shipped_id = shipped.version.id
    with Session(engine) as session, session.begin():
        record_rounds(session, outcome, "script_draft", correlation)
        for item in outcome.rounds:
            row = session.get(ScriptDraft, item.version.id)
            if row is None:
                continue
            own = outcome.record() if row.id == shipped_id else outcome.record_for(row.id)
            row.story_json = {**dict(row.story_json or {}), "editorial": own}
        letter_to_owner(
            session,
            outcome,
            title=shipped.version.title,
            director_id=director_id,
            correlation_id=correlation,
        )
        writer = agent_for_role(session, PREFERRED_WRITER_ROLE)
        if writer is not None:
            remember_shipped_story(
                session, outcome, title=shipped.version.title, writer_id=writer.id
            )
    return {
        "script_id": shipped_id,
        "review": reviews.get(shipped_id, passed),
        "editorial": outcome.record(),
        "rewrites": outcome.rewrites,
        "versions": [
            {
                "script_id": item.version.id,
                "verdict": reviews.get(item.version.id, {}).get("verdict"),
                "editorial_total": item.judgement.total if item.judgement else None,
                "shipped": item.version.id == shipped_id,
            }
            for item in outcome.rounds
        ],
    }
