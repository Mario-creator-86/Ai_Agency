"""A refused rewrite is redone with the refusal's words, and the studio learns why (2026-10-12).

16:45-16:47, the serial f06808c9 («The Zero Script Club»), scenes 3, 4 and 7: the Video
Editor's motion rewrites were refused by the Director's review again and again — «Rescrierea nu
tratează constatarea: …promptul de mișcare păstrează…», «nu tratează niciuna dintre
constatări» — and the next round asked the SAME brief: the loop read nothing from the refusal.
That day 11.05 of 19.50 USD went on redos and all three films still failed QC. The Owner:

- «Sistemul trebuie să refacă promptul! Dacă ceva este greșit, trebuie să îl citească, să
  înțeleagă ce a fost greșit și să îl refacă. DAR SĂ REFACĂ CE A FOST GREȘIT.»
- «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA
  VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!»

What is held here, every model faked, 0 credits, nothing bought:

- her review says, for each finding it leaves untreated, why (``why_not``), and the Video
  Editor gets one more rewrite in the same rung with exactly those words; only a second miss
  stores nothing;
- her review says what in the old words caused the defect and a general rule for future
  prompts; a rewrite she passes records that lesson studio-wide, once — a lesson the studio
  already has, or a note on one film, is not written again;
- her next brief reads the studio's lessons and, for the scene, the earlier reviews' causes,
  why_not and lessons;
- the record of the rewrite keeps each finding with the sentence that treats it, for the
  check after the purchase.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import MemoryRecord, ModelRecord
from app.agents.services import seed_initial_workforce
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.models import StoryboardScene
from app.media.prompt_agent import prompt_lessons, record_prompt_lesson
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    LESSON_OVERLAP,
    RewriteReview,
    earlier_briefs,
    lesson_not_general,
    lesson_overlap,
    rewrite_failed_scene,
    scene_context,
)
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import append_event
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import events
from test_failed_brief_is_recorded import a_refused_scene

#: Her brief for the motion (the Owner approved the scene's picture, so only motion is open).
BRIEF = {
    "diagnosis": "The motion keeps the figure on the ridge, whose head can turn to the camera.",
    "layer": "motion",
    "avoid": ["a figure whose face can turn to the camera"],
    "keep": ["the village on its terraced slope"],
    "change": ["the movement is the cloud's alone, rolling across the empty ridges"],
    "summary_ro": "Clipul arăta o față din profil; cer mișcarea norilor, fără nicio siluetă.",
}
FIRST_SHOT = {
    "scene_index": 1,
    "motion": "low grey cloud drifts over the ridges while the herder on the ridge looks down",
    "camera_move": "slow pan right",
    "ending_frame": "the herder on the ridge against the cloud",
}
SECOND_SHOT = {
    "scene_index": 1,
    "motion": "dense grey cloud sweeps quickly across the empty ridges from right to left",
    "camera_move": "slow pan left",
    "ending_frame": "the empty ridges half hidden by the passing cloud",
}
WHY_NOT = "the motion still names the herder on the ridge, who can turn his head to the camera"
CAUSE = "The motion named a herder on the ridge, a figure whose head can turn to the camera."
LESSON = "Move the landscape, the weather or an object; leave people out of the movement entirely."
MISSED = {
    "verdict": "MISSES",
    "findings": [
        {"finding": "a face seen in profile", "treated": False, "by": "", "why_not": WHY_NOT}
    ],
    "reason_ro": "Rescrierea păstrează păstorul pe creastă; fața din profil rămâne posibilă.",
    "cause": CAUSE,
    "lesson": LESSON,
}
TREATED_BY = "Dense grey cloud sweeps quickly across the empty ridges from right to left."
TREATED = {
    "verdict": "TREATS",
    "findings": [{"finding": "a face seen in profile", "treated": True, "by": TREATED_BY}],
    "reason_ro": "Mișcarea e acum a norilor peste crestele goale; nicio siluetă nu mai e în cadru.",
    "cause": CAUSE,
    "lesson": LESSON,
}


class Agents:
    """The Director's and the Video Editor's models, scripted in turn: her brief, his shots one
    after the other, her reviews one after the other (the last answer repeats)."""

    def __init__(self, shots: list[dict[str, Any]], reviews: list[dict[str, Any]]):
        self.shots, self.reviews_said = list(shots), list(reviews)
        self.briefs: list[str] = []
        self.rewrites: list[str] = []
        self.reviews: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    @staticmethod
    def _next(items: list[dict[str, Any]], asked: int) -> str:
        return json.dumps(items[min(asked, len(items) - 1)])

    async def generate(self, model, prompt, **kwargs):
        if '"scene-brief"' in prompt:
            self.briefs.append(prompt)
            return GenerateResult(json.dumps(BRIEF), 10, 40, None)
        if '"scene-rewrite"' in prompt:
            self.rewrites.append(prompt)
            return GenerateResult(self._next(self.shots, len(self.rewrites) - 1), 10, 40, None)
        if '"rewrite-review"' in prompt:
            self.reviews.append(prompt)
            said = self._next(self.reviews_said, len(self.reviews) - 1)
            return GenerateResult(said, 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        return {"provider_id": session.scalars(select(ModelRecord.provider_id)).first()}


def they_say(studio, agents: Agents) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], agents)
    return registry


def stored(engine, storyboard_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        return dict(row.prompt_json or {})


def lessons_with_sources(engine) -> list[tuple[str, str | None]]:
    with Session(engine) as session:
        return [
            (str(row.content), row.source_id)
            for row in session.scalars(
                select(MemoryRecord).where(
                    MemoryRecord.memory_class == "STRATEGY",
                    MemoryRecord.content.like("prompt lesson:%"),
                )
            )
        ]


def directors_rewrites(engine, storyboard_id: str) -> list[Any]:
    return [
        event
        for event in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if event.payload.get("decided_by") == "director"
    ]


def test_a_refused_rewrite_is_redone_with_her_why_not_and_stored_when_it_treats(
    engine, tmp_path, studio
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["layer"] == "motion", outcome
    assert outcome["review_verdict"] == "TREATS" and outcome["not_treating"] is False
    # One brief; two rewrites in the same rung, the second with her review's words.
    assert len(agents.briefs) == 1 and len(agents.rewrites) == 2 and len(agents.reviews) == 2
    first, second = agents.rewrites
    assert WHY_NOT not in first and "rewrite-feedback" not in first
    assert WHY_NOT in second and CAUSE in second and "refused it" in second
    assert "herder on the ridge looks down" in second  # his refused words, quoted to him
    # Her second review saw her first, and checked the untreated finding first.
    assert "your_earlier_review" in agents.reviews[1] and WHY_NOT in agents.reviews[1]
    assert "your_earlier_review" not in agents.reviews[0]
    package = stored(engine, storyboard_id)
    assert "sweeps quickly across the empty ridges" in package["motion_prompt"].lower()
    assert "herder" not in package["motion_prompt"].lower()

    # Both rounds are on the brief's record, the refused one with why.
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    rounds = brief.payload["review_attempts"]
    assert [r["verdict"] for r in rounds] == ["MISSES", "TREATS"]
    assert [r["round"] for r in rounds] == [1, 2]
    assert rounds[0]["findings"][0]["why_not"] == WHY_NOT
    assert "herder" in rounds[0]["motion_prompt"] and rounds[0]["review_run_id"]
    assert rounds[0]["rewrite_run_id"] != rounds[1]["rewrite_run_id"]
    assert brief.payload["review_verdict"] == "TREATS" and brief.payload["rewritten"] is True
    assert brief.payload["cause"] == CAUSE and brief.payload["lesson"] == LESSON

    # The rewrite's record keeps each finding with the sentence that treats it (the check after
    # the purchase reads exactly this), and the round she refused before it.
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    review = rewritten.payload["review"]
    assert review["verdict"] == "TREATS" and review["rounds"] == 2
    assert review["findings"] == [
        {"finding": "a face seen in profile", "treated": True, "by": TREATED_BY, "why_not": ""}
    ]
    assert review["cause"] == CAUSE and review["lesson"] == LESSON
    (refused,) = review["refused"]
    assert refused["round"] == 1 and refused["findings"][0]["why_not"] == WHY_NOT

    # Her lesson is the studio's now, with the review that drew it.
    ((content, source),) = lessons_with_sources(engine)
    assert content == f"prompt lesson: {LESSON}"
    assert source == rounds[1]["review_run_id"] == review["run_id"]


def test_a_rewrite_refused_twice_stores_nothing_and_teaches_nothing_studio_wide(
    engine, tmp_path, studio
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    before = stored(engine, storyboard_id)
    second_miss = {
        **MISSED,
        "findings": [
            {
                "finding": "a face seen in profile",
                "treated": False,
                "by": "",
                "why_not": "the ending frame still holds a silhouette on the ridge",
            }
        ],
    }
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, second_miss])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["not_treating"] is True, outcome
    assert outcome["same_prompt"] is False and outcome["review_unavailable"] is False
    assert outcome["reason"].startswith("Rescrierea nu tratează constatarea")
    assert "a doua rescriere" in outcome["reason"]
    assert len(agents.rewrites) == 2 and len(agents.reviews) == 2
    assert stored(engine, storyboard_id) == before
    assert directors_rewrites(engine, storyboard_id) == []
    # Not a word of hers became the studio's lesson: nothing she passed.
    assert lessons_with_sources(engine) == []
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert [r["verdict"] for r in brief.payload["review_attempts"]] == ["MISSES", "MISSES"]
    assert brief.payload["lesson_recorded"] is False
    # The next brief is shown why both rounds missed, each finding once with its first why.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["review_verdict"] == "MISSES" and shown["cause"] == CAUSE
    assert shown["why_not"] == [{"finding": "a face seen in profile", "why_not": WHY_NOT}]
    assert shown["lesson"] == LESSON


def test_a_rewrite_she_passes_at_once_records_one_lesson_and_no_second_round(
    engine, tmp_path, studio
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, outcome
    assert len(agents.rewrites) == 1 and len(agents.reviews) == 1
    with Session(engine) as session:
        assert prompt_lessons(session) == [LESSON]
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["lesson_recorded"] is True and brief.payload["lesson_skipped"] == ""
    assert len(brief.payload["review_attempts"]) == 1
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    assert rewritten.payload["review"]["rounds"] == 1
    assert rewritten.payload["review"]["refused"] == []
    assert rewritten.payload["review"]["lesson_recorded"] is True


def test_a_lesson_the_studio_already_has_is_not_written_twice(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)
    known = "Move the landscape, the weather or an object, and leave people out of the movement."
    with Session(engine) as session, session.begin():
        record_prompt_lesson(session, known, source_id=None)
    assert lesson_overlap(LESSON, known) >= LESSON_OVERLAP
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, outcome
    with Session(engine) as session:
        assert prompt_lessons(session, limit=40) == [known]
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["lesson_recorded"] is False
    assert "studioul are deja lecția" in brief.payload["lesson_skipped"]
    # The rewrite itself is stored all the same: a known lesson is no reason to buy nothing.
    assert "sweeps quickly" in stored(engine, storyboard_id)["motion_prompt"]


def test_a_note_on_one_film_is_not_a_lesson_for_every_prompt(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)
    context = scene_context(engine, storyboard_id, 1)
    assert context is not None
    title = context["title"]
    assert lesson_not_general(LESSON, context) == ""
    assert "filmul" in lesson_not_general(f"In {title}, move only the cloud.", context)
    assert "scenă" in lesson_not_general("In scene 4, move only the cloud.", context)
    assert "scenă" in lesson_not_general("Scena 3: mută doar norii.", context)
    assert lesson_not_general("", context)
    noted = {**TREATED, "lesson": "Scene 1 needs the cloud to move, not the herder."}
    agents = Agents([SECOND_SHOT], [noted])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["lesson_recorded"] is False, outcome
    assert lessons_with_sources(engine) == []


def test_her_next_brief_reads_the_studios_lessons_and_the_earlier_causes(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)
    first = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, MISSED])
    assert not rewrite_failed_scene(
        engine, they_say(studio, first), storyboard_id, 1, str(uuid4())
    )["rewritten"]
    studio_lesson = "Name the moving thing first and give its direction across the whole clip."
    with Session(engine) as session, session.begin():
        record_prompt_lesson(session, studio_lesson, source_id=None)
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, outcome
    (asked,) = agents.briefs
    assert "Read the earlier briefs and the reviews of their rewrites" in asked
    assert "follow the studio's lessons" in asked
    assert studio_lesson in asked and '"lessons"' in asked
    # The earlier round's cause, why the finding stayed, and the rule she drew.
    assert CAUSE in asked and WHY_NOT in asked and LESSON in asked
    assert '"review_verdict": "MISSES"' in asked


def test_older_briefs_beyond_the_ones_shown_whole_are_shown_in_short(engine, tmp_path, studio):
    """Every earlier diagnosis reaches her, however long the scene's history: the newest briefs
    whole, the older ones by their diagnosis and how they ended."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    with Session(engine) as session, session.begin():
        for number in range(1, 7):
            append_event(
                session,
                BRIEF_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "scene_index": 1,
                    "layer": "motion",
                    "rewritten": False,
                    "reason": "Rescrierea nu tratează constatarea: …",
                    "review_verdict": "MISSES",
                    "diagnosis": f"diagnosis number {number}",
                    "cause": f"cause number {number}",
                },
                str(uuid4()),
            )

    context = scene_context(engine, storyboard_id, 1)

    assert context is not None
    assert [b["diagnosis"] for b in context["briefs"]] == [
        f"diagnosis number {n}" for n in range(3, 7)
    ]
    assert [b["diagnosis"] for b in context["older_briefs"]] == [
        "diagnosis number 1",
        "diagnosis number 2",
    ]
    assert context["older_briefs"][0]["cause"] == "cause number 1"
    agents = Agents([SECOND_SHOT], [TREATED])
    rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))
    (asked,) = agents.briefs
    assert "older_briefs_in_short" in asked and "diagnosis number 1" in asked


def test_an_untreated_finding_must_say_why_and_a_review_must_say_cause_and_lesson():
    with pytest.raises(ValidationError, match="why_not"):
        RewriteReview.model_validate(
            {**MISSED, "findings": [{"finding": "a face", "treated": False, "by": ""}]}
        )
    for missing in ("cause", "lesson"):
        said = {key: value for key, value in TREATED.items() if key != missing}
        with pytest.raises(ValidationError, match=missing):
            RewriteReview.model_validate(said)
    review = RewriteReview.model_validate(MISSED)
    assert review.findings[0].why_not == WHY_NOT and review.cause == CAUSE


def test_lessons_are_compared_by_the_share_of_their_words_already_said():
    assert lesson_overlap(LESSON, LESSON) == 1.0
    same = "Leave people out of the movement entirely; move the landscape, weather or objects."
    assert lesson_overlap(same, LESSON) >= LESSON_OVERLAP
    other = "Name colours in words and keep the light the same from shot to shot."
    assert lesson_overlap(other, LESSON) < LESSON_OVERLAP
