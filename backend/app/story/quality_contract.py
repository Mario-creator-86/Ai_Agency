"""Shared eight-question narrative contract. No model calls are made in this module."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

VERSION = "story-quality-v2-satire"
AUDIENCE_PROFILE = (
    "English-speaking short-form viewers who do not know the studio, its agents, its "
    "tools or previous episodes. Give them accessible stakes, vivid personality, "
    "fast emotional changes, visual comedy and a payoff; avoid operational jargon."
)
SATIRE_POLICY = (
    "Inside The Nexus is explicitly fictional workplace satire inspired by a real "
    "autonomous studio. The event log supplies optional seeds, not a transcript or a "
    "limit on imagined plot. Fictional AI characters may argue, compete, sulk, laugh, "
    "cry, fall in love, panic, reconcile, experience absurd setbacks or take part in "
    "non-graphic slapstick scuffles. Invent consequential scenes, fictional dialogue, "
    "motives, mistaken beliefs and comic outcomes. Variety matters: not every story "
    "needs a fight or a joke. Never imply these invented scenes really occurred. "
    "Keep actual metrics, money, private information, real vendor incidents, "
    "publication results and decisions by the human Owner or other real people out "
    "of invented factual claims. Operational logs remain unchanged."
)
QUESTIONS = (
    ("Q1_HOOK", "Does the opening give a new viewer a concrete reason to keep watching?"),
    ("Q2_CHARACTER_GOAL", "Does a character want something specific and face an obstacle or consequential choice?"),
    ("Q3_CAUSAL_PROGRESS", "Does every major scene change the situation, not just report another update?"),
    ("Q4_MEMORABLE_MOMENT", "Is there a vivid, earned comic, emotional, surprising or satirical moment rather than only a status update?"),
    ("Q5_CHARACTER_VOICES", "Do characters react as distinct people rather than read operational reports?"),
    ("Q6_CENTRAL_PROMISE", "Does the story develop its opening promise instead of abandoning its most interesting idea?"),
    ("Q7_SATISFYING_ENDING", "Does the ending earn a payoff or consequence instead of restating the opening problem?"),
    ("Q8_FRESH_AND_CLEAR", "Can a new viewer understand it, and is its conflict and ending distinct from recent episodes?"),
)
KEYS = tuple(key for key, _ in QUESTIONS)


class QualityAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_id: str = Field(min_length=2, max_length=50)
    passed: bool
    evidence: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=300)


def questions_text() -> str:
    return "\n".join(f"{key}: {question}" for key, question in QUESTIONS)


def writer_instructions() -> str:
    return (
        "\nSTORY SELF-REVIEW IN THE SAME write_episode CALL (no extra model call). "
        "Write an entertaining fictional satire, not an operational status report. "
        f"AUDIENCE: {AUDIENCE_PROFILE}\n"
        f"FICTION RULES: {SATIRE_POLICY}\n"
        "Before replying, mentally test and improve the script against these eight questions:\n"
        + questions_text()
        + '\nReturn "self_review" in the SAME episode JSON: eight objects with '
        '"question_id", "passed" (boolean), "evidence" (specific scene or line) and "reason". '
        "A YES without evidence is invalid. Repair weaknesses before returning the script. "
        "A label like 'turn' does not prove a turn; repeated failures are not dramatic progress. "
        "Invent full fictional situations, disagreements and dramatic consequences, not merely framing. "
        "Do not present inventions as verified operational facts or fabricate actual documents. "
        "Respect the character bibles and the distinction between satire and real records. "
        "Never insert the review into speech or scenes.\n"
    )


def director_instructions() -> str:
    return (
        "\nINDEPENDENT STORY REVIEW IN THIS SAME episode_review CALL (no extra model call). "
        f"AUDIENCE: {AUDIENCE_PROFILE}\n"
        f"FICTION RULES: {SATIRE_POLICY}\n"
        "Judge scenes and dialogue rather than their structural labels. "
        "A technical update is not a plot turn and a callback is not necessarily a satisfying ending. "
        "Do not trust the writer's self-review; it is not included in the evidence. "
        "Answer these same eight questions honestly:\n"
        + questions_text()
        + '\nAdd "quality" to your existing JSON verdict: exactly eight objects with '
        '"question_id", "passed" (boolean), "evidence" (specific beat/line), "reason". '
        "If a major question is NO, return FAIL and a precise minimal rewrite note, "
        "even when technical checks pass. Do not reject invented events merely because they "
        "are missing from the operational log; reject confusing fiction with real-world "
        "claims, privacy leaks and dull storytelling.\n"
    )


def quality_issues(answers: list[QualityAnswer]) -> list[str]:
    """Validate a present independent review; legacy responses without it stay readable."""
    if not answers:
        return []
    seen = set()
    problems = []
    for answer in answers:
        if answer.question_id not in KEYS or answer.question_id in seen:
            problems.append(f"Invalid or duplicated question {answer.question_id}")
            continue
        seen.add(answer.question_id)
        if not answer.passed:
            problems.append(f"{answer.question_id}: {answer.reason or 'Not satisfied'}")
        elif not answer.evidence.strip() or not answer.reason.strip():
            problems.append(f"{answer.question_id}: unsupported YES")
    problems.extend(f"{key}: missing answer" for key in KEYS if key not in seen)
    return problems
