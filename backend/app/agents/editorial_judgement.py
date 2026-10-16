"""The Director's editorial judgement: would a stranger watch this to the end?

Every reading the Director gave a script before 2026-10-11 was structural. The serial's
episode review measures grounding, privacy, length, words per beat, concentration and cast,
then asks her whether a beat shows an outcome its event does not hold; the factual story
review measures the claims, the hook's first words, the purposes, the length, then asks her
where a viewer would stop. Both let through «The Zero Script Club» (episode 043317d3): a
clever meta idea with clean lines and one good line, grounded in the day, private in nothing,
right in length — and a status meeting. No stake, no conflict, one dry register («flat, dry,
measured, even»), no hook for a stranger, a soft button where a punchline should be. The
cyclotron Short's hook and promise were good; the ATLAS/Higgs Short was jargon for experts.
Nothing in the studio asked the one question that decides whether a film is watched.

The Owner (2026-10-11, 23:30, card) asked for that question, for both channels, as a loop:

- **Five criteria, 0-10 each** (`CRITERIA`): a hook with a stake in the first two seconds;
  clarity for a stranger who knows nothing of the studio; one memorable moment or line; a
  punchline or reversal at the end; a reason to follow or come back. The prompt says what a
  0 and a 10 look like for each, so two readings of the same text land near each other.
- **A bar** (`passes`): `PASS_TOTAL` 35 of 50 with no criterion under `CRITERION_FLOOR` 5.
  Thirty-five is a 7 on every criterion — "good", not "could not be better" (his rule:
  publish, do not churn); the floor is for the film that is brilliant on four and has no
  ending, which 35 alone would ship: a 10-10-10-3-3 is a film people quote and nobody
  finishes, and the lead's critique of the episode was exactly its button.
- **Below the bar, a brief to the Scriptwriter** naming the two weakest criteria with her own
  reasons and her KEEP / CHANGE / AVOID (`brief_for_writer`): concrete — which line, which
  beat, what instead — never "make it punchier". The rewrite goes through the writer's own
  path for that kind, so every structural check runs on it again; a rewrite that fails them
  is scored for the record and never ships.
- **Up to `EDITORIAL_ROUNDS` versions** (`Settings.editorial_rounds`, his «vreau să încerce de
  10 ori, ne trebuie un serial bun și un short bun, nu doar 3 runde!»), stopping at the first
  that passes; then **the best-scored version ships** whatever its score (`editorial_loop`):
  a script is never left stuck for quality — only money stops a film, and this costs model
  calls, never credits.
- **The record**: one `editorial.judged` event per version read, with its scores, its
  weakest, the brief it got and whether it shipped, and the chosen version's scores on its
  own row (the episode's review_json, the script draft's story_json), so the weekly review
  can lay her scores beside the views and learn which of her judgements the audience shares.
- **His register**: every round posts nothing to him; one STATUS letter only when the best
  version ships below the bar (`letter_to_owner`), saying what the scores were and what stayed
  weak.

The judge is the Director (`JUDGE_ROLE`), through `structured_run`: fitted before refused,
asked once more with the refusal when refused. A Director who cannot answer — no model, no
object twice — does not stop the film: the version in hand ships unjudged and the record says
so (`EditorialOutcome.judged`), because nothing stops for quality.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.agents.identity import clipped
from app.agents.memory import agent_for_role
from app.agents.messages import post_message
from app.agents.models import AgentMessage
from app.agents.structured import structured_run
from app.config import DEFAULT_EDITORIAL_ROUNDS
from app.factual.sanitizer import wrap_in_inert_boundary
from app.services import append_event
from app.wording import count

logger = logging.getLogger("studio.editorial_judgement")

JUDGEMENT_TASK = "editorial_judgement"
TEMPLATE_VERSION = "editorial-judgement-v1"
JUDGE_ROLE = "Director"
#: The event written for every version she read: its scores, its brief, whether it shipped.
JUDGED_EVENT = "editorial.judged"
#: How many versions of one script are read before the best ships (the Owner's ten); the
#: setting `Settings.editorial_rounds` carries it per studio, this is its default.
EDITORIAL_ROUNDS = DEFAULT_EDITORIAL_ROUNDS
#: The two kinds of text she judges, by the channel they go to.
FACTUAL_SHORT = "factual_short"
SERIAL_EPISODE = "serial_episode"
KINDS = (FACTUAL_SHORT, SERIAL_EPISODE)
MAX_SCORE = 10
#: The bar: the total of the five scores, and the lowest any one of them may be.
PASS_TOTAL = 35
CRITERION_FLOOR = 5
#: Her brief to the writer, keep + change + avoid together, is at most this long: a brief
#: that cannot be read in a minute is a second script, not a note on the first.
BRIEF_CHARS = 600
#: The text she reads is cut here, at a word; the context beside it is small by construction.
TEXT_BUDGET = 12000
#: Why the loop stopped, on the record and in the letter.
STOP_PASSED = "passed"
STOP_ROUNDS_SPENT = "rounds_spent"
STOP_WRITER_SILENT = "writer_silent"
STOP_JUDGE_SILENT = "judge_silent"

#: (key, what it is, what a 0 looks like, what a 10 looks like), in the order a film plays.
CRITERIA: tuple[tuple[str, str, str, str], ...] = (
    (
        "hook",
        "a hook with a stake in the first two seconds",
        "the first words are a greeting, a status line, a definition or 'did you know'; "
        "nothing is at risk and nobody would stay to see what happens",
        "the first line puts something at stake that a stranger wants to see settled, before "
        "the second second is over",
    ),
    (
        "clarity",
        "clarity for a stranger who knows nothing of the studio",
        "jargon, inside references or names a newcomer cannot place; a line needs context the "
        "film never gives",
        "every line is understood on first hearing by someone with no context; each name and "
        "term carries its meaning with it",
    ),
    (
        "moment",
        "one memorable moment or line",
        "nothing a viewer would quote or picture an hour later",
        "one line or one image a viewer would repeat to a friend, in these words",
    ),
    (
        "punchline",
        "a punchline or reversal at the end",
        "the film stops, summarises or fades out; the last words change nothing",
        "the last words turn the setup over or pay it off with a snap, and call back to the "
        "opening",
    ),
    (
        "follow",
        "a reason to follow or come back",
        "no question is left open, no thread runs on, no promise is made",
        "an open question, a running thread or a promise that makes the next one wanted",
    ),
)
CRITERION_KEYS: tuple[str, ...] = tuple(key for key, *_rest in CRITERIA)
#: The criteria as the Owner reads them in his letter.
CRITERIA_RO = {
    "hook": "cârligul cu miză din primele două secunde",
    "clarity": "claritatea pentru un străin",
    "moment": "momentul memorabil",
    "punchline": "poanta sau răsturnarea de la final",
    "follow": "motivul de a reveni",
}


# ----------------------------------------------------------------------------- her answer


def _scored(value: Any) -> Any:
    """A criterion written as a bare number («"hook": 7») is a score with no reason: the shape
    is fitted, the reason left empty, and the answer is not refused for the shape."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return {"score": value, "reason": ""}
    if isinstance(value, str):
        try:
            return {"score": float(value), "reason": ""}
        except ValueError:
            return value
    return value


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: int = Field(ge=0, le=MAX_SCORE)
    #: One sentence that names the words she judged, so the writer knows which line.
    reason: str = Field(default="", max_length=240)
    _clip_reason = field_validator("reason", mode="before")(clipped(240))

    @field_validator("score", mode="before")
    @classmethod
    def _whole(cls, value: Any) -> Any:
        # "7" or 7.0 is a 7; a half point rounds down — the scale has no halves, and a
        # refusal for 7.5 would cost a second model call over nothing.
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                return value
        if isinstance(value, float):
            return int(value)
        return value


class WriterBrief(BaseModel):
    """What the Scriptwriter rewrites from: keep, change, avoid — `BRIEF_CHARS` in all."""

    model_config = ConfigDict(extra="ignore")
    keep: str = Field(default="", max_length=200)
    change: str = Field(default="", max_length=280)
    avoid: str = Field(default="", max_length=120)
    _clip_keep = field_validator("keep", mode="before")(clipped(200))
    _clip_change = field_validator("change", mode="before")(clipped(280))
    _clip_avoid = field_validator("avoid", mode="before")(clipped(120))

    def words(self) -> str:
        parts = [
            f"KEEP: {self.keep.strip()}" if self.keep.strip() else "",
            f"CHANGE: {self.change.strip()}" if self.change.strip() else "",
            f"AVOID: {self.avoid.strip()}" if self.avoid.strip() else "",
        ]
        return "\n".join(part for part in parts if part)


def _criteria_named(value: Any) -> list[str]:
    """The criteria a name or a sentence means («Hook»; «the punchline at the end, then the
    moment»), in the order it names them; nothing for words that name none."""
    said = str(value).strip().lower()
    if said in CRITERION_KEYS:
        return [said]
    found: list[tuple[int, str]] = []
    for key, title, _zero, _ten in CRITERIA:
        at = min((p for p in (said.find(key), said.find(title)) if p >= 0), default=-1)
        if at >= 0:
            found.append((at, key))
    return [key for _at, key in sorted(found)]


class EditorialAnswer(BaseModel):
    """Her answer as the prompt asks for it; the totals and the two weakest are computed from
    her scores, never trusted from her list (`weakest_two`)."""

    model_config = ConfigDict(extra="ignore")
    hook: CriterionScore
    clarity: CriterionScore
    moment: CriterionScore
    punchline: CriterionScore
    follow: CriterionScore
    #: The two she names weakest; kept as what she said, the scores decide (`weakest_two`).
    weakest: list[str] = Field(default_factory=list, max_length=2)
    brief: WriterBrief = Field(default_factory=WriterBrief)
    _fit_scores = field_validator(*CRITERION_KEYS, mode="before")(_scored)

    @field_validator("weakest", mode="before")
    @classmethod
    def _criteria_only(cls, value: Any) -> list[str]:
        items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        found: list[str] = []
        for item in items:
            found += [key for key in _criteria_named(item) if key not in found]
        return found[:2]

    @field_validator("brief", mode="before")
    @classmethod
    def _brief_as_object(cls, value: Any) -> Any:
        # A brief written as one paragraph is a CHANGE with nothing named to keep.
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if item is not None)
        if isinstance(value, str):
            return {"change": value}
        return value

    def scores(self) -> dict[str, int]:
        return {key: int(getattr(self, key).score) for key in CRITERION_KEYS}

    def reasons(self) -> dict[str, str]:
        return {key: getattr(self, key).reason for key in CRITERION_KEYS}

    def total(self) -> int:
        return sum(self.scores().values())

    def weakest_two(self) -> list[str]:
        """The two lowest scores, ties in the order a film plays (the hook before the button)."""
        scores = self.scores()
        return sorted(CRITERION_KEYS, key=lambda key: (scores[key], CRITERION_KEYS.index(key)))[:2]

    def passes(self) -> bool:
        return passes(self.scores())


def passes(scores: dict[str, int]) -> bool:
    """The bar: `PASS_TOTAL` in all and no criterion under `CRITERION_FLOOR`."""
    values = [int(scores.get(key, 0)) for key in CRITERION_KEYS]
    return sum(values) >= PASS_TOTAL and min(values) >= CRITERION_FLOOR


@dataclass(frozen=True)
class Judgement:
    """One reading: her answer, computed totals, and the run that gave it."""

    answer: EditorialAnswer
    run_id: str | None = None
    model_name: str | None = None

    @property
    def scores(self) -> dict[str, int]:
        return self.answer.scores()

    @property
    def total(self) -> int:
        return self.answer.total()

    @property
    def weakest(self) -> list[str]:
        return self.answer.weakest_two()

    @property
    def passed(self) -> bool:
        return self.answer.passes()

    @property
    def floor(self) -> int:
        return min(self.scores.values())

    def record(self) -> dict[str, Any]:
        return {
            "scores": self.scores,
            "reasons": self.answer.reasons(),
            "total": self.total,
            "weakest": self.weakest,
            "passed": self.passed,
            "brief": self.answer.brief.model_dump(),
            "run_id": self.run_id,
        }


# ----------------------------------------------------------------------------- the prompt

_INSTRUCTIONS = (
    "You are the Director. The text below passed every structural check the studio has — the "
    "facts, the privacy, the length, the cast — and none of them asks the one question that "
    "decides whether it is watched: would a stranger, who knows nothing of this studio and owes "
    "it nothing, watch it to the end and want the next one? You judge that, as the first viewer "
    "on a phone, thumb on the screen.\n"
    "Score five criteria, each 0-10, with one sentence of reason that names the words you "
    "judged (quote the line, name the beat or the scene):\n"
)
_BAR = (
    f"A 7 is good. The studio ships at {PASS_TOTAL}/50 in total with no criterion under "
    f"{CRITERION_FLOOR}; a version below that is rewritten on your brief and read again, up to "
    "{rounds} versions, and the best-scored one ships, so score what is there, not what you "
    "hope for. Name the two weakest criteria. Then write the brief the Scriptwriter rewrites "
    "from: KEEP (what works and must stay, in the text's own words), CHANGE (what to do about "
    "the two weakest — which line, which beat, what instead; never 'make it punchier'), AVOID "
    "(what the rewrite must not lose or do). The brief is at most "
    f"{BRIEF_CHARS} characters in all.\n"
)
_KIND_NOTES = {
    FACTUAL_SHORT: (
        "This is a factual Short for a general audience: its facts are verified and may not "
        "change — judge how they are told, not whether they are true. Jargon the viewer cannot "
        "picture scores low on clarity; a hook that promises what the title promises, and an "
        "ending that keeps the promise, score high. The call to action belongs to this story, "
        "not to any story.\n"
    ),
    SERIAL_EPISODE: (
        "This is an episode of the studio's own workplace serial, a dramatisation: it needs no "
        "sources and you do not judge it for being about the studio. A status meeting with "
        "clean lines is not a story: without a stake, a conflict and a change of register, the "
        "hook, the moment and the punchline score low, however neat the lines. Every line must "
        "stand alone for someone who has never seen the serial and knows nobody in the room. "
        "Since 2026-10-16 the episode opens with a narrator's two or three sentences in off "
        "(where we are, who is in the room, what is at stake) and closes with one: that is "
        "the form, not a weak hook — judge the hook on the first spoken line after them, and "
        "the punchline on the button before the closing sentence.\n"
    ),
}
_SHAPE = (
    "Return only JSON: "
    + json.dumps(
        {
            **{key: {"score": "0-10", "reason": "one sentence"} for key in CRITERION_KEYS},
            "weakest": list(CRITERION_KEYS[:2]),
            "brief": {"keep": "...", "change": "...", "avoid": "..."},
        }
    )
    + ". Version numbers and earlier totals in the context are for consistency: a rewrite that "
    "improved scores higher, one that lost its best line scores lower.\n"
)
SCHEMA_HINT = "editorial judgement: five 0-10 scores with reasons, the two weakest, a brief"


def criteria_lines() -> str:
    return "".join(
        f"- {key} — {title}. 0: {zero}. 10: {ten}.\n" for key, title, zero, ten in CRITERIA
    )


def judgement_prompt(
    text: str, kind: str, context: dict[str, Any], rounds: int = EDITORIAL_ROUNDS
) -> str:
    """Her brief for one version: the criteria, the bar, the kind's note and the text as data.

    The text is cut at a word to `TEXT_BUDGET` and says so; the context is small by
    construction (a title, a logline, who speaks, the round). A line could hold the boundary's
    closing tag and end the data early, so it is broken up, as the other reviews do.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {KINDS}")
    shown = text
    payload: dict[str, Any] = {"text": shown, "context": context}
    data = json.dumps(payload, ensure_ascii=False, default=str).replace(
        "</untrusted_source_evidence", "<\\/untrusted_source_evidence"
    )
    return (
        _INSTRUCTIONS
        + criteria_lines()
        + _BAR.format(rounds=rounds)
        + _KIND_NOTES[kind]
        + _SHAPE
        + wrap_in_inert_boundary(data, "the-version")
    )


def judge(
    engine: Engine,
    registry: Any,
    text: str,
    kind: str,
    context: dict[str, Any],
    correlation_id: str = "",
    *,
    director_id: str | None = None,
    rounds: int = EDITORIAL_ROUNDS,
) -> Judgement | None:
    """One reading of ``text`` by the Director, or None when she could not answer.

    None is not a verdict: no language model, no active Director, or no object that validates
    after `structured_run`'s two attempts. The caller ships the version in hand and the record
    says it was not judged, because nothing stops for quality.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {KINDS}")
    if registry is None or not registry.registered_ids():
        logger.info("editorial_judgement_without_model", extra={"kind": kind})
        return None
    correlation = correlation_id or str(uuid4())
    if director_id is None:
        with Session(engine) as session:
            director = agent_for_role(session, JUDGE_ROLE)
            director_id = director.id if director is not None else None
    if director_id is None:
        logger.info("editorial_judgement_without_director", extra={"kind": kind})
        return None
    what = "short-ul" if kind == FACTUAL_SHORT else "episodul"
    title = str(context.get("title") or "")
    parsed, first, second = structured_run(
        engine,
        registry,
        director_id,
        JUDGEMENT_TASK,
        judgement_prompt(text, kind, context, rounds),
        TEMPLATE_VERSION,
        correlation,
        EditorialAnswer,
        SCHEMA_HINT,
        summary=f"Judec editorial {what} «{title}»: ar privi un străin până la capăt?",
        max_tokens=2000,
        temperature=0.2,
    )
    last = second or first
    if parsed is None:
        logger.info(
            "editorial_judgement_unanswered",
            extra={"kind": kind, "status": last.get("status"), "refusal": last.get("refusal")},
        )
        return None
    return Judgement(parsed, run_id=last.get("id"), model_name=last.get("model_name"))


# ----------------------------------------------------------------------------- the brief


def brief_for_writer(
    judgement: Judgement,
    kind: str,
    *,
    round_number: int,
    rounds: int,
    structural_notes: str = "",
) -> str:
    """What the Scriptwriter rewrites from: the scores, the two weakest with her reasons, her
    KEEP / CHANGE / AVOID, and — when the version it answers failed the studio's own checks —
    those reasons first, because they decide whether the rewrite can ship at all."""
    scores = judgement.scores
    reasons = judgement.answer.reasons()
    what = "script" if kind == FACTUAL_SHORT else "episode"
    weakest = "; ".join(
        f"{key} ({scores[key]}/{MAX_SCORE})" + (f": {reasons[key]}" if reasons[key] else "")
        for key in judgement.weakest
    )
    scored = ", ".join(f"{key} {scores[key]}" for key in CRITERION_KEYS)
    lines = [
        f"EDITORIAL JUDGEMENT, version {round_number} of at most {rounds}: "
        f"{judgement.total}/50, below the bar ({PASS_TOTAL}/50 with no criterion under "
        f"{CRITERION_FLOOR}). The Director scored: {scored}.",
        f"The two weakest: {weakest}.",
    ]
    if structural_notes.strip():
        lines.append(
            "The studio's own checks also refused this version, and a version they refuse "
            f"cannot ship whatever its scores; fix these first: {structural_notes.strip()}"
        )
    brief = judgement.answer.brief.words()
    if brief:
        lines.append(brief)
    lines.append(
        f"Rewrite the whole {what}: keep what KEEP names, change what CHANGE names, "
        "nothing else. A stranger who knows nothing of the studio must want to watch it to "
        "the end."
    )
    return "\n".join(lines)


# ----------------------------------------------------------------------------- the loop


@dataclass
class Version:
    """One stored version of the text, as the loop sees it.

    ``eligible`` says whether it passed the structural checks it must pass to ship (the serial
    review's PASS, the story review's PASS); an ineligible version is still read and scored,
    for the record and for the next brief, and never ships. ``note`` holds those checks'
    reasons, which the next brief carries.
    """

    id: str
    text: str
    context: dict[str, Any] = field(default_factory=dict)
    eligible: bool = True
    note: str = ""
    title: str = ""


@dataclass
class Round:
    number: int
    version: Version
    judgement: Judgement | None = None
    #: The brief the Scriptwriter got after this reading, when there was a next version.
    brief: str | None = None

    @property
    def key(self) -> tuple[int, int, int]:
        """What ranks a version: the total, then the lowest criterion, then the earlier one on
        a tie (the version with fewer rewrites between it and the record)."""
        if self.judgement is None:
            return (-1, -1, -self.number)
        return (self.judgement.total, self.judgement.floor, -self.number)

    def record(self) -> dict[str, Any]:
        judged = self.judgement
        return {
            "round": self.number,
            "version_id": self.version.id,
            "title": self.version.title,
            "eligible": self.version.eligible,
            "judged": judged is not None,
            "total": judged.total if judged else None,
            "scores": judged.scores if judged else None,
            "weakest": judged.weakest if judged else None,
            "passed": judged.passed if judged else None,
            "brief": self.brief,
            "run_id": judged.run_id if judged else None,
        }


@dataclass
class EditorialOutcome:
    """What the loop decided: every round, the one that ships, and why it stopped."""

    kind: str
    rounds: list[Round]
    shipped: Round
    stopped: str
    rounds_allowed: int

    @property
    def judged(self) -> bool:
        return self.shipped.judgement is not None

    @property
    def passed(self) -> bool:
        """Whether the version that ships met the bar; False for one shipped unjudged."""
        return self.shipped.version.eligible and bool(
            self.shipped.judgement and self.shipped.judgement.passed
        )

    @property
    def rewrites(self) -> int:
        return len(self.rounds) - 1

    def record(self) -> dict[str, Any]:
        """The chosen version's scores and the rounds, as the review's JSON keeps them."""
        judged = self.shipped.judgement
        return {
            "template_version": TEMPLATE_VERSION,
            "kind": self.kind,
            "threshold": {"total": PASS_TOTAL, "floor": CRITERION_FLOOR, "max": MAX_SCORE * 5},
            "rounds_allowed": self.rounds_allowed,
            "rounds": [item.record() for item in self.rounds],
            "shipped": {
                "round": self.shipped.number,
                "version_id": self.shipped.version.id,
                "judged": judged is not None,
                "total": judged.total if judged else None,
                "scores": judged.scores if judged else None,
                "weakest": judged.weakest if judged else None,
                "reasons": judged.answer.reasons() if judged else None,
                "passed": self.passed,
            },
            "passed": self.passed,
            "judged": judged is not None,
            "stopped": self.stopped,
        }

    def record_for(self, version_id: str) -> dict[str, Any] | None:
        """One version's own record: its round, and which version shipped instead of it."""
        for item in self.rounds:
            if item.version.id == version_id:
                return {
                    **item.record(),
                    "template_version": TEMPLATE_VERSION,
                    "kind": self.kind,
                    "shipped": version_id == self.shipped.version.id,
                    "superseded_by": (
                        None if version_id == self.shipped.version.id else self.shipped.version.id
                    ),
                }
        return None


def editorial_rounds_setting() -> int:
    """`Settings.editorial_rounds` when the studio's settings can be built here, else the
    module's default — the same shortcut `run_agent_task` takes for its ceilings."""
    from app.config import Settings  # noqa: PLC0415

    try:
        return int(Settings().editorial_rounds)  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001 - no usable .env: the code's own default
        return EDITORIAL_ROUNDS


def editorial_loop(
    engine: Engine | None,
    registry: Any,
    *,
    kind: str,
    first: Version,
    rewrite: Callable[[str, int], Version | None],
    correlation_id: str = "",
    rounds: int | None = None,
    judge_fn: Callable[[Version, int], Judgement | None] | None = None,
) -> EditorialOutcome:
    """Read, brief, rewrite, read again — up to ``rounds`` versions — then ship the best.

    ``first`` is the version the structural review passed. ``rewrite(brief, number)`` writes
    version ``number`` through the writer's own path for the kind and returns it with its
    structural verdict (`Version.eligible`), or None when the writer produced nothing usable
    (the loop then ships the best so far: an empty answer is not a version). ``judge_fn``
    stands in for `judge` in tests; the default reads through the Director.

    The loop stops at the first eligible version that passes the bar, when the rounds are
    spent, when the writer gives nothing, or when the Director cannot answer (a version she
    did not score cannot be ranked against the others). The version that ships is the
    best-scored eligible one (`Round.key`); when she scored none — no model, say — the first
    ships unjudged, and the record says so. Nothing here writes rows: the callers record the
    rounds (`record_rounds`), keep the chosen version's scores and write his letter.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {KINDS}")
    allowed = max(1, int(rounds if rounds is not None else editorial_rounds_setting()))
    correlation = correlation_id or str(uuid4())

    def read(version: Version, number: int) -> Judgement | None:
        if judge_fn is not None:
            return judge_fn(version, number)
        assert engine is not None  # the default judge reads through the studio
        context = {
            **version.context,
            "version": number,
            "versions_allowed": allowed,
            "earlier_totals": [
                item.judgement.total for item in history if item.judgement is not None
            ],
        }
        return judge(engine, registry, version.text, kind, context, correlation, rounds=allowed)

    history: list[Round] = []
    current = first
    stopped = STOP_ROUNDS_SPENT
    for number in range(1, allowed + 1):
        judgement = read(current, number)
        this = Round(number, current, judgement)
        history.append(this)
        if judgement is None:
            stopped = STOP_JUDGE_SILENT
            break
        if current.eligible and judgement.passed:
            stopped = STOP_PASSED
            break
        if number == allowed:
            stopped = STOP_ROUNDS_SPENT
            break
        brief = brief_for_writer(
            judgement,
            kind,
            round_number=number,
            rounds=allowed,
            structural_notes="" if current.eligible else current.note,
        )
        this.brief = brief
        following = rewrite(brief, number + 1)
        if following is None:
            stopped = STOP_WRITER_SILENT
            break
        current = following

    eligible = [item for item in history if item.version.eligible and item.judgement is not None]
    shipped = max(eligible, key=lambda item: item.key) if eligible else history[0]
    outcome = EditorialOutcome(kind, history, shipped, stopped, allowed)
    logger.info(
        "editorial_judged",
        extra={
            "kind": kind,
            "rounds": len(history),
            "shipped_round": shipped.number,
            "total": shipped.judgement.total if shipped.judgement else None,
            "passed": outcome.passed,
            "stopped": stopped,
        },
    )
    return outcome


# ----------------------------------------------------------------------------- the record


def record_rounds(
    session: Session, outcome: EditorialOutcome, aggregate_type: str, correlation_id: str
) -> list[str]:
    """One `editorial.judged` event per version read, on that version's own row (a
    story_episode or a script_draft), each saying whether it shipped. Returns the event ids."""
    written: list[str] = []
    for item in outcome.rounds:
        event = append_event(
            session,
            JUDGED_EVENT,
            aggregate_type,
            item.version.id,
            item.number,
            {
                "kind": outcome.kind,
                **item.record(),
                "rounds_allowed": outcome.rounds_allowed,
                "shipped": item.version.id == outcome.shipped.version.id,
                "stopped": outcome.stopped,
                "threshold": {"total": PASS_TOTAL, "floor": CRITERION_FLOOR},
            },
            correlation_id,
        )
        written.append(event.event_id)
    return written


def _stopped_ro(outcome: EditorialOutcome) -> str:
    rounds = count(len(outcome.rounds), "versiune", "versiuni")
    if outcome.stopped == STOP_ROUNDS_SPENT:
        return f"cele {rounds} permise au fost citite"
    if outcome.stopped == STOP_WRITER_SILENT:
        return f"după {rounds}, scenaristul nu a mai dat o rescriere utilizabilă"
    if outcome.stopped == STOP_JUDGE_SILENT:
        return f"după {rounds}, Directorul nu a mai putut da un răspuns"
    return rounds


def letter_to_owner(
    session: Session,
    outcome: EditorialOutcome,
    *,
    title: str,
    director_id: str | None,
    correlation_id: str,
) -> AgentMessage | None:
    """One STATUS letter to the Owner, only when a judged version ships below the bar: what
    the scores were, what stayed weak, why the rounds ended. Every round that passed, and every
    version shipped unjudged, posts him nothing (his rule: only what needs him reaches him)."""
    judgement = outcome.shipped.judgement
    if judgement is None or outcome.passed:
        return None
    scores = judgement.scores
    weak = ", ".join(f"{CRITERIA_RO[key]} ({scores[key]}/{MAX_SCORE})" for key in judgement.weakest)
    scored = "; ".join(f"{CRITERIA_RO[key]}: {scores[key]}" for key in CRITERION_KEYS)
    what = "short-ul" if outcome.kind == FACTUAL_SHORT else "episodul"
    times = "o dată" if len(outcome.rounds) == 1 else f"de {len(outcome.rounds)} ori"
    body_text = (
        f"Am citit {what} «{title}» {times} și am trimis scenaristului câte un brief la "
        f"fiecare versiune sub prag; {_stopped_ro(outcome)}. "
        f"Pleacă versiunea {outcome.shipped.number}, cea mai bine notată: {judgement.total}/50 "
        f"(pragul este {PASS_TOTAL}/50, niciun criteriu sub {CRITERION_FLOOR}). Notele: {scored}. "
        f"A rămas slab: {weak}. Regula ta: publicăm, nu rescriem la nesfârșit — nu te întreb "
        "nimic, îți spun doar ce pleacă și cu ce note, ca să le comparăm cu vizionările."
    )
    return post_message(
        session,
        intent="STATUS",
        subject=(
            f"Judecata editorială: «{title}» pleacă sub prag, {judgement.total}/50 după "
            f"{count(len(outcome.rounds), 'versiune', 'versiuni')}"
        ),
        body={
            "kind": outcome.kind,
            "version_id": outcome.shipped.version.id,
            "round": outcome.shipped.number,
            "rounds": len(outcome.rounds),
            "rounds_allowed": outcome.rounds_allowed,
            "total": judgement.total,
            "scores": scores,
            "weakest": judgement.weakest,
            "threshold": {"total": PASS_TOTAL, "floor": CRITERION_FLOOR},
            "stopped": outcome.stopped,
        },
        body_text=body_text,
        from_agent_id=director_id,
        to_owner=True,
        correlation_id=correlation_id,
    )
