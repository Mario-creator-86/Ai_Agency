"""The stranger: a blind judge who gets only what a viewer gets.

The Owner, 2026-10-16, on «Zero Scripts, Blocked Log»: «Eu nu înțeleg nimic». The Director had
approved it. Her judgement sees the writer's parts, purposes, her own earlier totals and her
brief; a viewer sees none of that. The research behind the studio's quality plan
(STORYCRAFT_RESEARCH_2026-10-16) found three things this module is built on:

- an uncalibrated judge agrees with experts at about chance (TTCW: Cohen's kappa ≈ 0), so the
  judge answers exactly the Owner's own five questions and its agreement with him is measured
  (`agreement`, `cohen_kappa`) before anyone trusts it;
- a robust rubric is binary tests, each with a short justification, summed, with no veto
  (TTCW), and the order of the criteria moves the marks: three balanced orders recover most of
  what ten would (Xu et al., EMNLP 2026), so every text is asked three times (`ORDERS`) and the
  answers are averaged per question;
- a pairwise judge flips its preference when the two options swap places (GPT-4 in a quarter
  of cases), so a comparison is asked in both orders and a flip is a tie, as MT-Bench does
  (`pairwise_outcome`).

What the stranger is shown is built here, never by the caller (`serial_view`, `factual_view`):
the title, then per beat or scene what is on screen (the picture line) and what is heard (the
spoken words, the narrator's as narration), with rough times so «the first 10 seconds» can be
answered. Never the writer's parts or purposes, the claim ids, the event ids, the rooms' codes,
the stage directions, a score, a version number or an earlier draft: a stranger has none of
them. A speaker's role in brackets is dropped too; the name stands for the voice and the face
the viewer meets on screen.

No model is named here: the harness pins the judge's model (`scripts/writer_eval.py`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.factual.editorial import SCENE_BEAT_SECONDS
from app.factual.editorial import WORDS_PER_SECOND as FACTUAL_WORDS_PER_SECOND
from app.story.lines import beat_lines

#: The serial's speaking rate, the one its review measures length with (`story.review`).
SERIAL_WORDS_PER_SECOND = 2.5
#: A beat or a scene with no words still holds the screen for a moment.
SILENT_MOMENT_SECONDS = 1.5

STRANGER_TASK = "stranger_judgement"
PAIRWISE_TASK = "stranger_pairwise"
TEMPLATE_VERSION = "stranger-v1"
PAIRWISE_TEMPLATE_VERSION = "stranger-pairwise-v1"
#: What the judge's run records as its identity: bare, no memory, no inbox, no persona.
IDENTITY_VERSION = "stranger-bare-v1"
#: How long a justification may be once read (a longer one is cut, never refused).
WHY_CHARS = 600


@dataclass(frozen=True)
class Question:
    """One of the Owner's five questions: the key results carry, the model's English, his
    Romanian (the calibration form)."""

    key: str
    en: str
    ro: str


#: The Owner's five questions (card of 2026-10-16), the judge's whole rubric, in his order.
QUESTIONS: tuple[Question, ...] = (
    Question(
        "orient",
        "Do I understand where we are and what is going on in the first 10 seconds?",
        "Înțeleg unde suntem și ce se întâmplă în primele 10 secunde?",
    ),
    Question(
        "story",
        "Is there a story (someone wants something, something changes)?",
        "Există o poveste (cineva vrea ceva, ceva se schimbă)?",
    ),
    Question("finish", "Would I watch it to the end?", "M-aș uita până la capăt?"),
    Question("ending", "Is the ending earned?", "Finalul este meritat?"),
    Question("surprise", "Is it funny or surprising?", "Este amuzant sau surprinzător?"),
)
QUESTION_KEYS: tuple[str, ...] = tuple(question.key for question in QUESTIONS)

#: The three orders the five questions are asked in. No order can give every question the
#: same mean position (five questions, three orders), so these are the closest: each question
#: sits in three different places, each order opens and closes on a different question, and
#: every question's mean position is within a third of the middle (2 ± 1/3).
ORDERS: tuple[tuple[int, ...], ...] = ((0, 1, 2, 3, 4), (1, 2, 3, 4, 0), (4, 3, 0, 2, 1))

#: The judge's identity: who it is, and nothing about the studio (`IDENTITY_VERSION`).
STRANGER_SYSTEM = (
    "You are a stranger scrolling short vertical videos on a phone. You have never heard of the "
    "people who made this video, its channel, its characters or any earlier episode, and you "
    "know nothing beyond what the video itself shows and says. You answer as that viewer: "
    "honestly, briefly, from what you saw and heard. Begin your reply with the JSON object "
    "itself."
)


# ----------------------------------------------------------------------------- the view


@dataclass(frozen=True)
class Heard:
    """One spoken line: who the viewer hears (NARRATOR for the voice in off) and the words."""

    voice: str
    words: str


@dataclass(frozen=True)
class Moment:
    """One beat or scene as the viewer meets it, with its rough place in time (seconds)."""

    seen: str
    heard: tuple[Heard, ...]
    start: float
    end: float


NARRATOR = "NARRATOR"


def _clock(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


@dataclass(frozen=True)
class ViewerText:
    """What a viewer gets of one script, and nothing else."""

    title: str
    moments: tuple[Moment, ...]

    @property
    def seconds(self) -> float:
        return self.moments[-1].end if self.moments else 0.0

    def render(self) -> str:
        """The text the judge reads (and the Owner, on the calibration form)."""
        rows = [f"TITLE: {self.title or '(no title)'}"]
        for moment in self.moments:
            rows.append("")
            rows.append(
                f"[{_clock(moment.start)}-{_clock(moment.end)}] ON SCREEN: "
                f"{moment.seen or '(nothing described)'}"
            )
            for line in moment.heard:
                voice = "NARRATOR (voice-over)" if line.voice == NARRATOR else line.voice
                rows.append(f'  {voice}: "{line.words}"')
            if not moment.heard:
                rows.append("  (nothing is said)")
        return "\n".join(rows)

    def sha256(self) -> str:
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _words(text: str) -> int:
    return len(text.split())


#: A speaker's role in brackets, «Sarah (Director)»: the viewer is never told it.
_ROLE = re.compile(r"\s*\([^()]*\)\s*$")


def voice_of(speaker: Any) -> str:
    """Who the viewer hears: NARRATOR for the voice in off (no speaker, or «Narrator»), else
    the speaker's name without the role in brackets."""
    name = _one_line(speaker)
    if not name or name.lower() == "narrator":
        return NARRATOR
    return _ROLE.sub("", name).strip() or name


def _timed(parts: Iterable[tuple[str, tuple[Heard, ...], float]], gap: float) -> tuple[Moment, ...]:
    moments: list[Moment] = []
    clock = 0.0
    for index, (seen, heard, seconds) in enumerate(parts):
        if index:
            clock += gap
        moments.append(Moment(seen, heard, round(clock, 1), round(clock + seconds, 1)))
        clock += seconds
    return tuple(moments)


def serial_view(title: Any, beats: Sequence[Mapping[str, Any]]) -> ViewerText:
    """An episode as the viewer meets it: per beat its picture line («scene») and its lines."""
    parts = []
    for beat in beats:
        heard = tuple(
            Heard(voice_of(line.get("speaker")), _one_line(line.get("text")))
            for line in beat_lines(dict(beat))
            if _one_line(line.get("text"))
        )
        words = sum(_words(line.words) for line in heard)
        seconds = max(SILENT_MOMENT_SECONDS, words / SERIAL_WORDS_PER_SECOND)
        parts.append((_one_line(beat.get("scene")), heard, seconds))
    return ViewerText(_one_line(title), _timed(parts, 0.0))


def _number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _one_line(value)


def _card_seen(kind: str, card: Any) -> str:
    """What a composed scene puts on screen: the chart's bars or the title card's words."""
    card = card if isinstance(card, Mapping) else {}
    title = _one_line(card.get("title"))
    if kind == "TITLE_CARD":
        return f"Words on screen: «{title}»." if title else "A title card."
    bars = [
        " ".join(
            part
            for part in (
                _one_line(bar.get("label")),
                _number(bar.get("value")),
                _one_line(bar.get("unit")),
            )
            if part
        )
        for bar in card.get("bars") or []
        if isinstance(bar, Mapping)
    ]
    said = f"A chart titled «{title}»" if title else "A chart"
    if bars:
        said += ": " + "; ".join(bars)
    highlight = _one_line(card.get("highlight"))
    if highlight:
        said += f" (highlighted: {highlight})"
    return said + "."


def factual_view(title: Any, scenes: Sequence[Mapping[str, Any]]) -> ViewerText:
    """A factual short as the viewer meets it: per scene what is on screen (the picture asked
    for, or the card the studio composes) and the narration."""
    parts = []
    for scene in scenes:
        kind = _one_line(scene.get("scene_kind") or scene.get("kind")).upper()
        narration = _one_line(scene.get("narration") or scene.get("voiceover_segment"))
        if kind in ("DATA_CARD", "TITLE_CARD"):
            seen = _card_seen(kind, scene.get("card"))
        elif kind == "BLACK":
            seen = "A black screen."
        else:
            seen = _one_line(
                scene.get("visual_description") or scene.get("visual") or scene.get("visual_prompt")
            )
        heard = (Heard(NARRATOR, narration),) if narration else ()
        seconds = max(SILENT_MOMENT_SECONDS, _words(narration) / FACTUAL_WORDS_PER_SECOND)
        parts.append((seen, heard, seconds))
    return ViewerText(_one_line(title), _timed(parts, SCENE_BEAT_SECONDS))


def view_of(frozen: Mapping[str, Any]) -> ViewerText:
    """The view of a text kept as data: ``{"kind": "serial", "title", "beats"}`` or
    ``{"kind": "factual", "title", "scenes"}`` (`frozen_episode`, `frozen_script`)."""
    if frozen.get("kind") == "serial":
        return serial_view(frozen.get("title"), list(frozen.get("beats") or []))
    if frozen.get("kind") == "factual":
        return factual_view(frozen.get("title"), list(frozen.get("scenes") or []))
    raise ValueError(f"Un text de tipul {frozen.get('kind')!r} nu poate fi arătat")


def frozen_episode(title: Any, beats: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """An episode kept as only what its view needs: each beat's picture line and lines."""
    kept = []
    for beat in beats:
        lines = [
            {"speaker": line.get("speaker"), "text": _one_line(line.get("text"))}
            for line in beat_lines(dict(beat))
            if _one_line(line.get("text"))
        ]
        kept.append({"scene": _one_line(beat.get("scene")), "lines": lines})
    return {"kind": "serial", "title": _one_line(title), "beats": kept}


def frozen_script(title: Any, scenes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """A factual script kept as only what its view needs: narration, picture, kind, card."""
    kept = []
    for scene in scenes:
        card = scene.get("card") if isinstance(scene.get("card"), Mapping) else None
        kept.append(
            {
                "narration": _one_line(scene.get("narration") or scene.get("voiceover_segment")),
                "visual_description": _one_line(
                    scene.get("visual_description") or scene.get("visual")
                ),
                "scene_kind": _one_line(scene.get("scene_kind") or scene.get("kind")).upper(),
                "card": (
                    {
                        "title": card.get("title"),
                        "bars": [
                            {key: bar.get(key) for key in ("label", "value", "unit")}
                            for bar in card.get("bars") or []
                            if isinstance(bar, Mapping)
                        ],
                        "highlight": card.get("highlight"),
                    }
                    if card
                    else None
                ),
            }
        )
    return {"kind": "factual", "title": _one_line(title), "scenes": kept}


# ----------------------------------------------------------------------------- the questions


def question_prompt(view: ViewerText, order: Sequence[int]) -> str:
    """The five questions about one video, asked in ``order`` (indexes into `QUESTIONS`)."""
    if sorted(order) != list(range(len(QUESTIONS))):
        raise ValueError(f"Ordinea întrebărilor nu este o permutare: {order}")
    asked = [QUESTIONS[index] for index in order]
    rows = [
        "Below is one short video, written out in order as what is on screen and what is heard, "
        "with rough times. It is everything a viewer gets: there are no notes and no other "
        "context.",
        "",
        "<video>",
        view.render(),
        "</video>",
        "",
        "You just watched it. Answer each question below with yes or no, and justify each answer "
        "in one to three sentences that point at what in the video decided it. Judge each "
        "question on its own.",
    ]
    rows += [f"{n}. [{question.key}] {question.en}" for n, question in enumerate(asked, 1)]
    rows += [
        "",
        "Return only JSON, with the answers in the order asked and each id copied from the "
        'brackets: {"answers": [{"id": "...", "answer": "yes" | "no", "why": "one to three '
        'sentences"}]}',
    ]
    return "\n".join(rows)


_YES = frozenset({"yes", "y", "da", "true", "1"})
_NO = frozenset({"no", "n", "nu", "false", "0"})


def yes_or_no(value: Any) -> bool | None:
    """True, False, or None for anything that is neither (a label the Owner left empty)."""
    if isinstance(value, bool):
        return value
    word = str(value if value is not None else "").strip().lower().rstrip(".!")
    if word in _YES:
        return True
    if word in _NO:
        return False
    return None


def _clip(value: Any) -> str:
    return _one_line(value)[:WHY_CHARS]


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    answer: bool
    why: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _key(cls, value: Any) -> str:
        return _one_line(value).strip("[]").lower()

    @field_validator("answer", mode="before")
    @classmethod
    def _answer(cls, value: Any) -> bool:
        read = yes_or_no(value)
        if read is None:
            raise ValueError("answer is yes or no")
        return read

    @field_validator("why", mode="before")
    @classmethod
    def _why(cls, value: Any) -> str:
        return _clip(value)


class StrangerAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: list[QuestionAnswer] = Field(min_length=len(QUESTIONS), max_length=len(QUESTIONS))

    @model_validator(mode="after")
    def _every_question_once(self) -> StrangerAnswer:
        keys = [answer.id for answer in self.answers]
        if sorted(keys) != sorted(QUESTION_KEYS):
            raise ValueError("answers carry each id exactly once: " + ", ".join(QUESTION_KEYS))
        return self

    def by_key(self) -> dict[str, QuestionAnswer]:
        return {answer.id: answer for answer in self.answers}


def combine(per_order: Sequence[Mapping[str, bool] | None]) -> dict[str, Any]:
    """The answers of the orders that answered, averaged per question.

    Per question: how often it was yes (``yes_rate``), over how many answers, and the
    majority (None on an even split). The score is the sum of the yes rates, 0-5; None when no
    order answered at all.
    """
    answered = [answers for answers in per_order if answers is not None]
    questions: dict[str, dict[str, Any]] = {}
    for key in QUESTION_KEYS:
        votes = [bool(answers[key]) for answers in answered if key in answers]
        yes = sum(votes)
        questions[key] = {
            "yes_rate": round(yes / len(votes), 4) if votes else None,
            "votes": len(votes),
            "majority": (True if yes * 2 > len(votes) else False if yes * 2 < len(votes) else None)
            if votes
            else None,
        }
    rates = [entry["yes_rate"] for entry in questions.values() if entry["yes_rate"] is not None]
    return {
        "orders_asked": len(per_order),
        "orders_answered": len(answered),
        "questions": questions,
        "score": round(sum(rates), 4) if answered else None,
    }


# ----------------------------------------------------------------------------- the pair


def pairwise_prompt(first: ViewerText, second: ViewerText) -> str:
    """Which of two videos a stranger would watch to the end: A is ``first``, B ``second``."""
    return "\n".join(
        [
            "Below are two short videos, A and B, each written out in order as what is on screen "
            "and what is heard, with rough times. Each is everything a viewer gets.",
            "",
            '<video id="A">',
            first.render(),
            "</video>",
            "",
            '<video id="B">',
            second.render(),
            "</video>",
            "",
            "Which of these two would a stranger, who knows nothing about the people who made "
            "them, watch to the end? You must choose one. Justify the choice in one to three "
            "sentences that point at what in the videos decided it.",
            "",
            'Return only JSON: {"choice": "A" | "B", "why": "one to three sentences"}',
        ]
    )


class PairwiseAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choice: str
    why: str = ""

    @field_validator("choice", mode="before")
    @classmethod
    def _choice(cls, value: Any) -> str:
        word = _one_line(value).upper().removeprefix("VIDEO").strip(" .:\"'")
        if word not in ("A", "B"):
            raise ValueError("choice is A or B")
        return word

    @field_validator("why", mode="before")
    @classmethod
    def _why(cls, value: Any) -> str:
        return _clip(value)


TIE = "tie"
INCOMPLETE = "incomplete"


def pairwise_outcome(
    first_order: str | None, second_order: str | None, *, x: str = "new", y: str = "reference"
) -> str:
    """The comparison's result: ``x`` or ``y`` when both orders chose it, `TIE` when the choice
    flipped with the order, `INCOMPLETE` when an order gave no choice.

    ``first_order`` is the choice with ``x`` shown as A; ``second_order`` with ``y`` as A.
    """
    if first_order not in ("A", "B") or second_order not in ("A", "B"):
        return INCOMPLETE
    one = x if first_order == "A" else y
    two = y if second_order == "A" else x
    return one if one == two else TIE


# ----------------------------------------------------------------------------- calibration


def cohen_kappa(first: Sequence[bool], second: Sequence[bool]) -> float | None:
    """Cohen's kappa of two raters' yes/no answers on the same items; None when it is
    undefined: no items, or both raters gave one same answer to every item (chance agreement
    is then certain and the statistic is 0/0)."""
    if len(first) != len(second):
        raise ValueError("both raters must answer the same items")
    total = len(first)
    if not total:
        return None
    observed = sum(1 for a, b in zip(first, second, strict=True) if a == b) / total
    yes_first = sum(1 for a in first if a) / total
    yes_second = sum(1 for b in second if b) / total
    expected = yes_first * yes_second + (1 - yes_first) * (1 - yes_second)
    if expected >= 1.0:
        return None
    return round((observed - expected) / (1 - expected), 4)


def _agreement_of(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "agree": 0, "percent": None, "kappa": None}
    agree = sum(1 for judge, owner in pairs if judge == owner)
    return {
        "n": len(pairs),
        "agree": agree,
        "percent": round(100.0 * agree / len(pairs), 1),
        "kappa": cohen_kappa([judge for judge, _ in pairs], [owner for _, owner in pairs]),
    }


def agreement(
    judge: Mapping[str, Mapping[str, Any]], owner: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """How often the judge's majority answer matches the Owner's, per question and pooled, on
    the texts both answered (keyed alike). An answer either left empty is not counted."""
    per_question: dict[str, list[tuple[bool, bool]]] = {key: [] for key in QUESTION_KEYS}
    for text_key, owner_answers in owner.items():
        judged = judge.get(text_key)
        if not judged:
            continue
        for key in QUESTION_KEYS:
            mine, his = yes_or_no(judged.get(key)), yes_or_no(owner_answers.get(key))
            if mine is not None and his is not None:
                per_question[key].append((mine, his))
    pooled = [pair for pairs in per_question.values() for pair in pairs]
    return {
        "questions": {key: _agreement_of(pairs) for key, pairs in per_question.items()},
        "pooled": _agreement_of(pooled),
        "texts": sorted(key for key in owner if key in judge),
    }
