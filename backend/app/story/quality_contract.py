"""Shared eight-question narrative contract. No model calls are made in this module.

Storycraft references (guidance, not imported external text):
https://johnaugust.com/2007/write-scene (necessary scene change, surprise, cut filler)
https://pixarpost.com/2012/07/former-pixarian-emma-coats-to-speak-at.html (stakes, causality, character choices)
https://perell.com/note/but-therefore-rule/ (cause/effect versus event lists)
https://support.google.com/youtube/answer/9314415 (intro engagement, moments and dips)
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

VERSION = "story-quality-v4-ensemble-dramedy"
AUDIENCE_PROFILE = (
    "English-speaking viewers who may join on any episode. They value sharp "
    "characters, curiosity, recognizable mistakes, humor, dilemmas, suspense, "
    "friendship, occasional romance and consequences, not studio status reports."
)
SATIRE_POLICY = (
    "Inside The Nexus is a FICTIONAL serialized ensemble dramedy. The office "
    "is the setting, not an operational report. Episodes can be comedies, "
    "rivalries, social mishaps, mysteries, friendships, betrayals, reconciliations "
    "or romances as the established characters and consequences naturally warrant. "
    "Romance is OPTIONAL; NEVER require flirting, love or jealousy in every episode. "
    "Do not make any single emotion or genre a quota. Every chapter must move "
    "a meaningful personal predicament, alliance, promise, secret or relationship "
    "forward with choices whose consequences persist. Not every long-running "
    "thread must be foregrounded in every chapter. No abrupt reset, instant "
    "forgiveness, unexplained reversal or convenient miracle. Each scene needs "
    "a reason to exist, a want or dramatic purpose, resistance or friction, "
    "and a clear before/after change; remove repetitive explanations. Connect "
    "scenes by cause and effect (BUT/THEREFORE) rather than AND THEN. Give an "
    "early concrete reason to watch, an earned turn, and a satisfying local "
    "payoff. Leave a naturally consequential future question, not a forced "
    "cliffhanger. Comedy should arise from character choices; avoid obligatory "
    "jokes and generic speeches. Keep established character voices recognizable "
    "without forcing their professional jargon into every sentence. Daily "
    "operational events are optional background references, not plot requirements. "
    "Fictional intrigues are NOT real agent actions: never claim invented "
    "owner messages, business decisions, publications, payments, vendor events "
    "or audience metrics actually happened. No confidential material may enter "
    "fiction or permanent memory. Preserve the actual ledger."
)
QUESTIONS = (
    ("Q1_HOOK", "Does the opening give a new viewer a concrete reason to keep watching?"),
    ("Q2_CHARACTER_GOAL", "Does a character want something specific and face an obstacle or consequential choice?"),
    ("Q3_CAUSAL_PROGRESS", "Does every scene cause a meaningful change, choice, obstacle or revelation instead of merely listing updates?"),
    ("Q4_MEMORABLE_MOMENT", "Is there a specific, earned, memorable moment (funny, painful, tense, surprising or moving) rather than a generic statement?"),
    ("Q5_CHARACTER_VOICES", "Do characters react as distinct people rather than read operational reports?"),
    ("Q6_CENTRAL_PROMISE", "Does this episode pay off its own premise AND respect all relevant established secrets, promises and character states?"),
    ("Q7_SATISFYING_ENDING", "Does the episode resolve a local beat while opening an earned serialized consequence or cliffhanger?"),
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
        "Write a varied fictional ensemble serial, not an operational status report or mandatory romance. "
        f"AUDIENCE: {AUDIENCE_PROFILE}\n"
        f"FICTION RULES: {SATIRE_POLICY}\n"
        "Before replying, mentally test and improve the script against these eight questions:\n"
        + questions_text()
        + '\nReturn "self_review" in the SAME episode JSON: eight objects with '
        '"question_id", "passed" (boolean), "evidence" (specific scene or line) and "reason". '
        "A YES without evidence is invalid. Repair weaknesses before returning the script. "
        "A label like 'turn' does not prove a turn; repeated failures are not dramatic progress. "
        "Choose concrete scenes with cause-and-effect turns; humor is welcome when earned, not obligatory. "
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
        "even when technical checks pass. Reject broken continuity, unjustified turns, repetitive filler and unsupported character updates. Do NOT reject an episode for lacking romance, jokes or arbitrary melodrama. Do not reject invented events merely because they "
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
