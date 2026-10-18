"""A refused rewrite is redone with the refusal's words, and the studio learns why (2026-10-12).

16:45-16:47, the serial f06808c9 («The Zero Script Club»), scenes 3, 4 and 7: the Video
Editor's motion rewrites were refused by the Director's review again and again — «Rescrierea nu
tratează constatarea: …promptul de mișcare păstrează…», «nu tratează niciuna dintre
constatări» — and the next round asked the SAME brief: the loop read nothing from the refusal.
Her review of scene 7 (runs e31aa5e7, 8035e541) listed two diagnoses of her own as findings and
refused a rewrite that treated quality control's one finding, the clip's ending; and the words
she said were untreated were the camera move's fixed sentence and the beat's action, which the
motion layer keeps. That day 11.05 of 19.50 USD went on redos and all three films still failed
QC. The Owner:

- «Sistemul trebuie să refacă promptul! Dacă ceva este greșit, trebuie să îl citească, să
  înțeleagă ce a fost greșit și să îl refacă. DAR SĂ REFACĂ CE A FOST GREȘIT.»
- «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA
  VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!»

What is held here, every model faked, 0 credits, nothing bought:

- her review answers quality control's findings by their ids, every one and no other; her own
  diagnoses are observations and decide nothing; a minor finding left untreated does not refuse
  the rewrite;
- an untreated finding names the field he must change, or the words the layer keeps; when every
  finding that refuses the rewrite is locked on the motion layer, he is not asked again there
  and the picture's turn comes at once (``layer_exhausted``);
- he gets one more rewrite in the same rung with her words; a second rewrite with the refused
  words on the motion layer is the layer exhausted too; a second review nobody could read keeps
  the first one's refusal;
- a rewrite she passes records her lesson for the film's kind, unverified, under her review's
  run; every writer reads the lessons whole, however long the scene's history;
- the record keeps each of quality control's findings with its own words and the sentence that
  treats it, for the check after the purchase.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

import pytest
from app.agents.director import DEVELOPER_DEFECT_KIND
from app.agents.models import AgentMessage, ModelRecord
from app.agents.services import seed_initial_workforce
from app.media import prompt_agent
from app.media import scene_rewrite as rewrite_module
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.models import SceneTake, StoryboardScene
from app.media.prompt_lint import MOTION_CLOSING
from app.media.scene_rewrite import (
    ACCEPTED_MINOR,
    BRIEF_EVENT,
    LOCK_COMPOSER,
    LOCK_PICTURE,
    MAX_PAYLOAD_CHARS,
    MINOR,
    MISSES,
    MOTION,
    STILL,
    STILL_KEPT_WHOLE,
    TREATS,
    director_brief,
    earlier_briefs,
    film_failure,
    layer_terms,
    lock_texts,
    open_layers,
    refusal_findings,
    review_findings,
    review_schema,
    rewrite_failed_scene,
    rewrite_for_redo,
    scene_context,
)
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.runbook.stages import LAYER_EXHAUSTED_NOTE, SAME_PROMPT_NOTE
from app.services import append_event, utc_now
from final_rewrite_actor import final_answer, final_review
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_clip_qc_wiring import events
from test_failed_brief_is_recorded import PLAN, a_refused_scene
from test_film_costing import a_film
from test_stills_stage import LOOK

#: Her brief for the motion (the Owner approved the scene's picture, so only motion is open).
BRIEF = {
    "diagnosis": "The motion keeps the figure on the ridge, whose head can turn to the camera.",
    "layer": "motion",
    "avoid": ["a figure whose face can turn to the camera"],
    "keep": ["the village on its terraced slope"],
    "change": ["the movement is the cloud's alone, rolling across the empty ridges"],
    "summary_ro": "Clipul arăta o față din profil; cer mișcarea norilor, fără nicio siluetă.",
}
STILL_BRIEF = {
    "diagnosis": "The picture holds the village the motion cannot move without a figure.",
    "layer": "still",
    "avoid": ["any figure on the ridge"],
    "keep": ["the Himalayan ridges under low cloud"],
    "change": ["the picture is the empty terraces under rolling cloud"],
    "summary_ro": "Refac imaginea: terasele goale sub nori.",
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
STILL_SHOT = {
    "scene_index": 1,
    "subject": "empty terraced fields on a mountain slope under rolling cloud",
    "action": "wind bends the young rice in long waves",
    "environment": "steep Himalayan ridges under low cloud",
    "camera": "wide establishing shot, 24mm lens",
    "lighting": "soft overcast daylight",
    "motion": "wind sweeps waves through the rice while cloud rolls over the ridges",
    "camera_move": "slow push-in",
}
#: Quality control's one finding on the fixture's refused clip: id 1.
QC_WORDS = "o față se vede din profil"
WHY_NOT = "the motion still names the herder on the ridge, who can turn his head to the camera"
CAUSE = "The motion named a herder on the ridge, a figure whose head can turn to the camera."
LESSON = "Move the landscape, the weather or an object; leave people out of the movement entirely."
MISSED = {
    "findings": [
        {
            "id": 1,
            "finding": "a face seen in profile",
            "treated": False,
            "severity": "serious",
            "by": "",
            "why_not": WHY_NOT,
            "field": "motion_prompt",
        }
    ],
    "reason_ro": "Rescrierea păstrează păstorul pe creastă; fața din profil rămâne posibilă.",
    "cause": CAUSE,
    "lesson": LESSON,
}
TREATED_BY = "Dense grey cloud sweeps quickly across the empty ridges from right to left."
TREATED = {
    "findings": [
        {
            "id": 1,
            "finding": "a face seen in profile",
            "treated": True,
            "severity": "serious",
            "by": TREATED_BY,
        }
    ],
    "reason_ro": "Mișcarea e acum a norilor peste crestele goale; nicio siluetă nu mai e în cadru.",
    "cause": CAUSE,
    "lesson": LESSON,
}
#: Her review when the words that invite the finding are the picture's, which a motion rewrite
#: keeps whole (f06808c9's «turning fully toward her», 2026-10-12): quoted as the kept still
#: says them.
PICTURE_WORDS = "a far village of stone houses on a terraced slope"
LOCKED = {
    "findings": [
        {
            "id": 1,
            "finding": "a face seen in profile",
            "treated": False,
            "severity": "serious",
            "why_not": "the picture keeps the village's people in the frame",
            "locked": True,
            "locked_words": PICTURE_WORDS,
        }
    ],
    "reason_ro": "Mișcarea nu poate scoate oamenii: imaginea îi păstrează.",
    "cause": "The picture holds a village whose people the clip moves.",
    "lesson": "",
}
#: Her review when the words that invite the finding are the composer's own closing sentence,
#: which no rewrite of the scene changes (`prompt_lint.MOTION_CLOSING`).
COMPOSER_WORDS = "Continuous, seamless shot"
COMPOSER_LOCKED = {
    **LOCKED,
    "findings": [
        {
            **LOCKED["findings"][0],
            "why_not": "the closing asks for one unbroken shot the model fills with a figure",
            "locked_words": COMPOSER_WORDS,
        }
    ],
}
#: Quality control's finding that is no hard limit of the bible: hers to rate minor.
CLOUDS = "norii stau aproape pe loc"
#: Her review when the one finding is a small defect she accepts as it is.
ALL_MINOR = {
    "findings": [
        {
            "id": 1,
            "finding": "the clouds barely move",
            "treated": False,
            "severity": "minor",
            "why_not": "the cloud moves, but slowly",
            "field": "motion",
        }
    ],
    "reason_ro": "Norii se mișcă încet, dar clipul e bun; accept defectul mic.",
    "cause": "The motion asked only for a slow drift.",
    "lesson": "Give the weather a clear verb and direction across the whole clip.",
}


class Agents:
    """The Director's and the Video Editor's models, scripted in turn: her briefs, his shots
    and her reviews, each list answered in order (the last answer repeats); a review that is a
    string is answered as it is, for a review nobody can read."""

    def __init__(
        self,
        shots: list[dict[str, Any]],
        reviews: list[Any],
        briefs: list[dict[str, Any]] | None = None,
    ):
        self.shots, self.reviews_said = list(shots), list(reviews)
        self.briefs_said = list(briefs or [BRIEF])
        self.briefs: list[str] = []
        self.rewrites: list[str] = []
        self.reviews: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    @staticmethod
    def _next(items: list[Any], asked: int) -> str:
        said = items[min(asked, len(items) - 1)]
        return said if isinstance(said, str) else json.dumps(said)

    async def generate(self, model, prompt, **kwargs):
        if '"scene-brief"' in prompt:
            self.briefs.append(prompt)
            return GenerateResult(self._next(self.briefs_said, len(self.briefs) - 1), 10, 40, None)
        if '"scene-rewrite"' in prompt:
            self.rewrites.append(prompt)
            answer = self.shots[min(len(self.rewrites) - 1, len(self.shots) - 1)]
            said = final_answer(prompt, answer)
            return GenerateResult(said if isinstance(said, str) else json.dumps(said), 10, 40, None)
        if '"rewrite-review"' in prompt:
            self.reviews.append(prompt)
            said = self._next(self.reviews_said, len(self.reviews) - 1)
            if isinstance(
                self.reviews_said[min(len(self.reviews) - 1, len(self.reviews_said) - 1)], dict
            ):
                said = json.dumps(final_review(json.loads(said)))
            return GenerateResult(said, 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


@pytest.fixture
def recorded(monkeypatch):
    """Every lesson her reviews hand the store, with how (scope, provisional, source)."""
    calls: list[dict[str, Any]] = []
    real = prompt_agent.record_prompt_lesson

    def spy(session, lesson, **kwargs):
        stored = real(session, lesson, **kwargs)
        calls.append({"lesson": lesson, **kwargs, "stored": stored})
        return stored

    monkeypatch.setattr(prompt_agent, "record_prompt_lesson", spy)
    return calls


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


def lessons_for(engine, scope: str | None) -> list[str]:
    with Session(engine) as session:
        return prompt_agent.prompt_lessons(session, 40, scope=scope)


def directors_rewrites(engine, storyboard_id: str) -> list[Any]:
    return [
        event
        for event in events(engine, SCENE_PROMPTS_REWRITTEN_EVENT, storyboard_id)
        if event.payload.get("decided_by") == "director"
    ]


def boundary_data(prompt: str, name: str) -> dict[str, Any]:
    """The data an agent was given inside its inert boundary."""
    found = re.search(
        rf'<untrusted_source_evidence hash="{name}">\n(.*?)\n</untrusted_source_evidence>',
        prompt,
        re.DOTALL,
    )
    assert found is not None, name
    return json.loads(found.group(1))


def test_a_refused_rewrite_is_redone_with_her_why_not_and_stored_when_it_treats(
    engine, tmp_path, studio, recorded
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["layer"] == "motion", outcome
    assert outcome["review_verdict"] == TREATS and outcome["not_treating"] is False
    assert outcome["layer_exhausted"] is False
    # One brief; two rewrites in the same rung, the second with her review's words.
    assert len(agents.briefs) == 1 and len(agents.rewrites) == 2 and len(agents.reviews) == 2
    first, second = agents.rewrites
    assert WHY_NOT not in first and "rewrite-feedback" not in first
    assert WHY_NOT in second and CAUSE in second and "refused it" in second
    assert "herder on the ridge looks down" in second  # his refused words, quoted to him
    feedback = boundary_data(second, "rewrite-feedback")
    assert feedback["untreated"] == [
        {
            "id": 1,
            "finding": "a face seen in profile",
            "quality_control": QC_WORDS,
            "why_not": WHY_NOT,
            "severity": "serious",
            "field": "motion_prompt",
        }
    ]
    # He is told, both times, what the motion layer lets him change and what it keeps — once,
    # in the rewrite's own data: her feedback does not say the layer's terms or the moves'
    # sentences again (2026-10-12 evening review: the second round ran 16-19 thousand).
    for asked in (first, second):
        data = boundary_data(asked, "scene-rewrite")
        terms = data["this_layer"]
        assert list(terms["fields_he_may_change"]) == ["motion_prompt", "camera_move"]
        assert terms["kept_word_for_word"]["still_prompt"]
        assert terms["still_kept_whole"] == STILL_KEPT_WHOLE
        assert data["camera_move_sentences"] == {}
        assert asked.count('"camera_move_sentences"') == 1
    assert "this_layer" not in feedback and "camera_move_sentences" not in feedback
    # Her reviews answered quality control's finding by its id, with its own words.
    review_data = boundary_data(agents.reviews[0], "rewrite-review")
    assert review_data["quality_control_findings"] == [
        {"id": 1, "qc_text": QC_WORDS, "source": "test_shot", "code": "QC.CLIP"}
    ]
    assert "fields_he_may_change" in review_data["this_layer"]
    assert review_data["this_layer"]["fixed_sentences"]["motion"] == []
    assert review_data["this_layer"]["said_by_his_fields"] == {}
    assert review_data["camera_move_sentences"] == {}
    # Her second review saw her first, and checked the untreated finding first — by id, with
    # quality control's words given once, in quality_control_findings.
    assert "your_earlier_review" in agents.reviews[1] and WHY_NOT in agents.reviews[1]
    assert "your_earlier_review" not in agents.reviews[0]
    earlier = boundary_data(agents.reviews[1], "rewrite-review")["your_earlier_review"]
    assert earlier["findings"] == [
        {
            "id": 1,
            "treated": False,
            "severity": "serious",
            "why_not": WHY_NOT,
            "field": "motion_prompt",
            "locked": False,
        }
    ]
    package = stored(engine, storyboard_id)
    assert "sweeps quickly across the empty ridges" in package["motion_prompt"].lower()
    assert "herder" not in package["motion_prompt"].lower()

    # Both rounds are on the brief's record, the refused one with why.
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    rounds = brief.payload["review_attempts"]
    assert [r["verdict"] for r in rounds] == [MISSES, TREATS]
    assert [r["round"] for r in rounds] == [1, 2]
    assert rounds[0]["findings"][0]["why_not"] == WHY_NOT
    assert "herder" in rounds[0]["motion_prompt"] and rounds[0]["review_run_id"]
    assert rounds[0]["rewrite_run_id"] != rounds[1]["rewrite_run_id"]
    assert brief.payload["review_verdict"] == TREATS and brief.payload["rewritten"] is True
    assert brief.payload["cause"] == CAUSE and brief.payload["lesson"] == LESSON
    assert brief.payload["qc_findings"][0]["qc_text"] == QC_WORDS
    # The next brief reads the refused round apart: nothing is left untreated on the scene.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["why_not"] == []
    assert shown["refused_rounds"] == [
        {
            "round": 1,
            "why_not": [{"finding": "a face seen in profile", "why_not": WHY_NOT}],
            "cause": CAUSE,
        }
    ]

    # The rewrite's record keeps each of quality control's findings with its own words and the
    # sentence that treats it (the check after the purchase reads exactly this).
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    review = rewritten.payload["review"]
    assert review["verdict"] == TREATS and review["rounds"] == 2
    assert review["findings"] == [
        {
            "id": 1,
            "qc_text": QC_WORDS,
            "finding": "a face seen in profile",
            "treated": True,
            "by": TREATED_BY,
            "why_not": "",
            "severity": "serious",
            "layer": "motion",
            "accepted": False,
            "field": "",
            "locked": False,
            "lock": "",
            "source": "test_shot",
        }
    ]
    assert review["cause"] == CAUSE and review["lesson"] == LESSON
    assert review["lesson_scope"] == "factual" and review["lesson_provisional"] is True
    (refused,) = review["refused"]
    assert refused["round"] == 1 and refused["findings"][0]["why_not"] == WHY_NOT

    # Her lesson is the studio's now, for factual films, unverified, under the review that drew
    # it — the run the stills gate confirms or withdraws it by.
    (call,) = recorded
    assert call["lesson"] == LESSON and call["stored"] is True
    assert call["scope"] == "factual" and call["provisional"] is True
    assert call["source_id"] == rounds[1]["review_run_id"] == review["run_id"]
    assert lessons_for(engine, "factual") == [f"{LESSON} (unverified)"]
    with Session(engine) as session, session.begin():
        assert prompt_agent.confirm_prompt_lessons(session, [review["run_id"]]) == 1
    assert lessons_for(engine, "factual") == [LESSON]


def test_a_rewrite_refused_twice_stores_nothing_and_teaches_nothing_studio_wide(
    engine, tmp_path, studio, recorded
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    before = stored(engine, storyboard_id)
    second_miss = {
        **MISSED,
        "findings": [
            {
                **MISSED["findings"][0],
                "why_not": "the ending frame still holds a silhouette on the ridge",
                "field": "ending_frame",
            }
        ],
    }
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, second_miss])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["not_treating"] is True, outcome
    assert outcome["same_prompt"] is False and outcome["review_unavailable"] is False
    # He missed twice on words he could change: that is no exhausted layer.
    assert outcome["layer_exhausted"] is False
    assert outcome["reason"].startswith("Rescrierea nu tratează constatarea")
    assert "a doua rescriere" in outcome["reason"]
    assert len(agents.rewrites) == 2 and len(agents.reviews) == 2
    assert stored(engine, storyboard_id) == before
    assert directors_rewrites(engine, storyboard_id) == []
    # Not a word of hers became the studio's lesson: nothing she passed.
    assert recorded == [] and lessons_for(engine, None) == []
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert [r["verdict"] for r in brief.payload["review_attempts"]] == [MISSES, MISSES]
    assert brief.payload["lesson_recorded"] is False
    # The next brief is shown why both rounds missed, each finding once with its first why.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["review_verdict"] == MISSES and shown["cause"] == CAUSE
    assert shown["why_not"] == [{"finding": "a face seen in profile", "why_not": WHY_NOT}]
    assert shown["lesson"] == LESSON and "refused_rounds" not in shown


def test_a_rewrite_she_passes_at_once_records_one_unverified_lesson_for_the_films_kind(
    engine, tmp_path, studio, recorded
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, json.dumps(outcome, ensure_ascii=False)
    assert len(agents.rewrites) == 1 and len(agents.reviews) == 1
    assert lessons_for(engine, "factual") == [f"{LESSON} (unverified)"]
    # A factual film's lesson is not the serial's to follow.
    assert lessons_for(engine, "serial") == []
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["lesson_recorded"] is True and brief.payload["lesson_skipped"] == ""
    assert len(brief.payload["review_attempts"]) == 1
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    assert rewritten.payload["review"]["rounds"] == 1
    assert rewritten.payload["review"]["refused"] == []
    assert rewritten.payload["review"]["lesson_recorded"] is True
    (call,) = recorded
    assert call["source_id"] == rewritten.payload["review"]["run_id"]


def test_a_lesson_the_store_refuses_or_none_at_all_is_said_so_and_the_rewrite_stands(
    engine, tmp_path, studio, recorded
):
    """The store decides what is a rule for every prompt (no film, scene or id named): its
    refusal is reported as it is, not as a lesson kept; a review that draws no general rule
    records nothing — and neither is a reason to buy nothing."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    noted = {**TREATED, "lesson": "Scene 1 needs the cloud to move, not the herder."}

    outcome = rewrite_failed_scene(
        engine, they_say(studio, Agents([SECOND_SHOT], [noted])), storyboard_id, 1, str(uuid4())
    )

    assert outcome["rewritten"] is True and outcome["lesson_recorded"] is False, outcome
    (call,) = recorded
    assert call["stored"] is False
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert "nu a fost păstrată" in brief.payload["lesson_skipped"]
    assert "sweeps quickly" in stored(engine, storyboard_id)["motion_prompt"]
    assert lessons_for(engine, None) == []

    other = a_refused_scene(engine, tmp_path)
    plain = {**TREATED, "lesson": ""}
    again = rewrite_failed_scene(
        engine, they_say(studio, Agents([SECOND_SHOT], [plain])), other, 1, str(uuid4())
    )
    assert again["rewritten"] is True and again["lesson_recorded"] is False
    assert len(recorded) == 1  # nothing handed to the store
    (brief,) = events(engine, BRIEF_EVENT, other)
    assert "nicio regulă generală" in brief.payload["lesson_skipped"]


def test_her_next_brief_reads_the_studios_lessons_and_the_earlier_causes(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)
    first = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, MISSED])
    assert not rewrite_failed_scene(
        engine, they_say(studio, first), storyboard_id, 1, str(uuid4())
    )["rewritten"]
    studio_lesson = "Name the moving thing first and give its direction across the whole clip."
    serial_lesson = "Keep both speakers turned to the viewer through the whole clip."
    with Session(engine) as session, session.begin():
        assert prompt_agent.record_prompt_lesson(session, studio_lesson, scope="factual")
        assert prompt_agent.record_prompt_lesson(session, serial_lesson, scope="serial")
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, outcome
    (asked,) = agents.briefs
    assert "Read the earlier briefs and the reviews of their rewrites" in asked
    assert "follow the studio's lessons" in asked
    # The lessons are named as rules in her instructions and given whole, first, in the data.
    assert prompt_agent.LESSONS_RULE in asked
    data = boundary_data(asked, "scene-brief")
    assert list(data)[0] == "lessons" and data["lessons"] == [studio_lesson]
    assert serial_lesson not in asked
    # The earlier round's cause, why the finding stayed, and the rule she drew.
    assert CAUSE in asked and WHY_NOT in asked and LESSON in asked
    assert '"review_verdict": "MISSES"' in asked
    # Quality control's findings by id, and what each open layer lets him change.
    assert data["quality_control_findings"][0]["qc_text"] == QC_WORDS
    assert list(data["layers_he_may_change"]) == ["motion"]
    # His rewrite and her review read the same lessons as rules.
    (rewrite,) = agents.rewrites
    (review,) = agents.reviews
    for prompt, name in ((rewrite, "scene-rewrite"), (review, "rewrite-review")):
        assert prompt_agent.LESSONS_RULE in prompt
        assert boundary_data(prompt, name)["lessons"] == [studio_lesson]
    assert "broken_lessons" in review and "a lesson only the composer's fixed words" in review


def test_older_briefs_beyond_the_ones_shown_whole_are_shown_in_short(engine, tmp_path, studio):
    """Every earlier diagnosis reaches her, however long the scene's history: the newest briefs
    whole, the newest twelve older ones by their diagnosis (cut short) and how they ended."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    long_tail = " because the ridge line kept a figure" * 12
    with Session(engine) as session, session.begin():
        for number in range(1, 21):
            append_event(
                session,
                BRIEF_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "scene_index": 1,
                    "layer": "still",
                    "rewritten": False,
                    "reason": "Rescrierea nu tratează constatarea: …",
                    "review_verdict": "MISSES",
                    "diagnosis": f"diagnosis number {number}{long_tail}",
                    "cause": f"cause number {number}",
                },
                str(uuid4()),
            )

    context = scene_context(engine, storyboard_id, 1)

    assert context is not None
    assert [b["diagnosis"].split(" because")[0] for b in context["briefs"]] == [
        f"diagnosis number {n}" for n in range(1, 21)
    ]
    assert context["older_briefs"] == []
    assert len(context["briefs"]) == 20
    assert len(context["briefs"][0]["diagnosis"]) > 200
    agents = Agents([SECOND_SHOT], [TREATED])
    rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))
    (asked,) = agents.briefs
    assert "diagnosis number 1" in asked and "diagnosis number 20" in asked


def test_a_long_history_keeps_every_lesson_whole_and_first(engine, tmp_path, studio):
    """2026-10-12 review: the brief, the rewrite and the review ran 14-21 thousand characters
    and `trim_payload` dropped every lesson first. The scene's history is fitted by whole items
    (the oldest refusals, then the oldest whole briefs said in short); the lessons ride on top,
    every one of them."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    #: Twelve rules about twelve different things (a store that folds a lesson into one that
    #: says the same keeps every one of them).
    lessons = [
        "Name the moving thing first and give its direction across the whole clip, from the "
        "opening frame to the closing one.",
        "Describe hands and tools in close detail whenever the bible forbids faces; never ask "
        "for a figure that could turn its head.",
        "Write one single moment for every still; a chain of actions belongs only to the "
        "motion prompt, never to the picture.",
        "Keep the blank pages and dark screens blank: describe paper as empty cream sheets and "
        "monitors as unlit glass.",
        "Give weather its own verb: clouds roll, rain slants, mist drifts, wind bends grass in "
        "visible waves.",
        "Place secondary people at the frame's edge, turned toward the viewer, never facing "
        "the main speaker across the frame.",
        "Choose lighting words that match the hour of the narration: lamplight at night, low "
        "amber sun in the evening.",
        "Name colours plainly in words such as forest green, rust red or slate blue instead of "
        "hexadecimal codes or brand names.",
        "Let the camera end on a steady hold over the subject so the next cut starts from a "
        "calm, readable frame.",
        "Say the room's furniture once, in order from foreground to background, so the "
        "composition stays legible.",
        "Prefer a tracking move beside walking characters; a push toward a seated speaker "
        "invites a frozen face.",
        "Mention the season through vegetation and clothing, for example bare branches and wool "
        "coats, rather than through captions.",
    ]
    with Session(engine) as session, session.begin():
        for lesson in lessons:
            assert prompt_agent.record_prompt_lesson(session, lesson, scope="factual")
    context = scene_context(engine, storyboard_id, 1)
    assert context is not None
    reason = "the clip showed a figure turning its head toward the camera on the ridge " * 5
    context["failures"] = [
        {"kind": "test_shot", "code": "QC.CLIP", "reasons": [reason[:400]] * 4} for _ in range(6)
    ]
    context["briefs"] = [
        {
            "layer": "motion",
            "rewritten": False,
            "diagnosis": f"diagnosis {n} " + "the cloud kept a figure on the ridge " * 30,
            "avoid": ["a figure on the ridge " * 10] * 4,
            "change": ["the cloud moves alone " * 10] * 4,
            "review_verdict": "MISSES",
            "cause": "the motion named a figure",
        }
        for n in range(4)
    ]
    whole = json.dumps(context["failures"] + context["briefs"], ensure_ascii=False)
    assert len(whole) > 20000
    agents = Agents([SECOND_SHOT], [TREATED])

    asked = director_brief(engine, they_say(studio, agents), context, str(uuid4()))

    assert asked["brief"] is not None, asked
    (prompt,) = agents.briefs
    data = boundary_data(prompt, "scene-brief")
    kept = data.pop("lessons")
    assert len(kept) == 12 and {k.removesuffix(" (unverified)") for k in kept} == set(lessons)
    assert len(json.dumps(data, ensure_ascii=False)) <= MAX_PAYLOAD_CHARS
    # The newest refusal and brief are still whole; the oldest were said in short.
    assert data["refusals"][0]["reasons"][0] == reason[:400]
    assert data["earlier_briefs"][-1]["diagnosis"].startswith("diagnosis 3")
    assert data["earlier_briefs"] == context["briefs"]
    assert data["refusals"] == context["failures"]


#: Where a lock's quote is read for the schema tests (`lock_texts`): the rewritten prompts, the
#: composer's constants, the picture a motion rewrite keeps, and the sentences his fields chose.
STILL_SAID = "The village rests below steep ridges under low grey cloud, soft diffuse light."
MOVE_SAID = (
    "Slow pan left, smooth and with a clear start and end, sweeping from the right side of "
    "the scene across to the subject."
)
LOCKS = {
    "said": (STILL_SAID, f"{MOVE_SAID} Dense cloud sweeps the ridges. {MOTION_CLOSING}"),
    "constants": (MOTION_CLOSING,),
    "picture": (STILL_SAID,),
    "fields": {"camera_move": (MOVE_SAID,)},
}


def test_her_review_answers_quality_controls_findings_by_id_and_says_how_serious():
    """The review's schema for one rewrite: quality control gave findings 1 and 2; the motion
    layer lets him change motion, camera_move and ending_frame and keeps the picture."""
    schema = review_schema((1, 2), ("motion", "camera_move", "ending_frame"), LOCKS)
    done = {"treated": True, "severity": "serious", "by": TREATED_BY}
    left = {"treated": False, "severity": "serious", "why_not": WHY_NOT, "field": "motion"}

    def review(*findings: dict[str, Any], **more: Any) -> dict[str, Any]:
        return {"findings": list(findings), "reason_ro": "…", "cause": CAUSE, **more}

    def locked_on(words: str) -> dict[str, Any]:
        return review({"id": 1, **done}, {**left, "id": 2, "locked": True, "locked_words": words})

    # Every finding answered, by its id: her own diagnoses are observations, not findings.
    for wrong, said in (
        (review({"id": 1, **done}), "missing"),
        (review({"id": 1, **done}, {"id": 2, **done}, {"id": 3, **done}), "did not give"),
        (review({"id": 1, **done}, {"id": 1, **done}, {"id": 2, **done}), "more than once"),
    ):
        with pytest.raises(ValidationError, match=said):
            schema.model_validate(wrong)
    # An untreated finding says why, and names a field he may change or the words kept.
    with pytest.raises(ValidationError, match="why_not"):
        schema.model_validate(review({"id": 1, **done}, {**left, "id": 2, "why_not": ""}))
    with pytest.raises(ValidationError, match="field must be one he may change"):
        schema.model_validate(review({"id": 1, **done}, {**left, "id": 2, "field": "subject"}))
    # A lock quotes three words of meaning the rewritten prompts say (2026-10-12 evening review:
    # «the», «a» and «toward the subject» were accepted as locks and bought a still).
    for words, said in (
        ("the", "words of meaning"),
        ("toward the subject", "words of meaning"),
        ("a herder looking down", "not in the rewritten prompts"),
        # The chosen move's own sentence is said by a field he may change: no lock.
        ("sweeping from the right side of the scene", "camera_move is his to change"),
        ("Dense cloud sweeps the ridges", "not in the words this layer keeps"),
    ):
        with pytest.raises(ValidationError, match=said):
            schema.model_validate(locked_on(words))
    picture = schema.model_validate(locked_on("«The village rests … ridges»"))
    assert picture.verdict == MISSES and [item.id for item in picture.blocking] == [2]
    assert picture.findings[1].lock_kind == LOCK_PICTURE
    composer = schema.model_validate(locked_on(COMPOSER_WORDS))
    assert composer.findings[1].lock_kind == LOCK_COMPOSER
    # The lock's kind is the studio's reading of the words, never hers.
    said_kind = {**left, "id": 2, "locked": True, "locked_words": COMPOSER_WORDS}
    claimed = schema.model_validate(
        review({"id": 1, **done}, {**said_kind, "lock_kind": LOCK_PICTURE})
    )
    assert claimed.findings[1].lock_kind == LOCK_COMPOSER
    # A treated finding quotes its sentence; the cause is said; the lesson may be empty.
    with pytest.raises(ValidationError, match="by"):
        schema.model_validate(review({"id": 1, **done, "by": ""}, {"id": 2, **done}))
    with pytest.raises(ValidationError, match="cause"):
        schema.model_validate(
            {"findings": [{"id": 1, **done}, {"id": 2, **done}], "reason_ro": "…"}
        )
    passed = schema.model_validate(
        review({"id": "#1", **done}, {"id": 2, **done}, observations=[{"observation": "flat"}])
    )
    assert passed.verdict == TREATS and passed.lesson == "" and passed.observations == ["flat"]
    # A minor finding left untreated does not refuse the rewrite; a serious one does.
    minor = schema.model_validate(review({"id": 1, **done}, {**left, "id": 2, "severity": MINOR}))
    assert minor.verdict == TREATS and minor.blocking == []
    serious = schema.model_validate(review({"id": 1, **done}, {**left, "id": 2}))
    assert serious.verdict == MISSES
    # Every finding minor: the take is accepted as it is and nothing is bought on a rewrite,
    # whatever the rewrite treated (2026-10-12 evening review of a50407e).
    small = {"severity": MINOR}
    for findings in (
        ({**left, "id": 1, **small}, {**left, "id": 2, **small}),
        ({"id": 1, **done, **small}, {**left, "id": 2, **small}),
    ):
        assert schema.model_validate(review(*findings)).verdict == ACCEPTED_MINOR
    # Serious whatever she says: a hard limit of the bible, or what an earlier round of the
    # rung found serious — her «minor» is not taken.
    anchored = review_schema(
        (1, 2), ("motion", "camera_move", "ending_frame"), LOCKS, serious={2}
    ).model_validate(review({"id": 1, **done}, {**left, "id": 2, **small}))
    assert anchored.findings[1].severity == "serious" and anchored.verdict == MISSES


def test_only_a_confirmed_lesson_refuses_a_rewrite():
    """2026-10-12 evening review of a50407e: a guess no picture had proven yet could refuse
    every rewrite after it. A lesson she names is read against the lessons she was given: one
    marked (unverified) broken is advisory; a confirmed one refuses, and names the field."""
    done = {"id": 1, "treated": True, "severity": "serious", "by": TREATED_BY}
    broken = {"lesson": LESSON, "why_not": "a herder moves", "field": "motion"}
    answer = {"findings": [done], "reason_ro": "…", "cause": CAUSE, "broken_lessons": [broken]}
    editable = ("motion", "camera_move", "ending_frame")

    unverified = review_schema(
        (1,), editable, LOCKS, lessons=[f"{LESSON} (unverified)"]
    ).model_validate(answer)
    assert unverified.verdict == TREATS and unverified.broken_lessons[0].confirmed is False
    # Her own say on «confirmed» is not taken.
    claimed = {**answer, "broken_lessons": [{**broken, "confirmed": True}]}
    assert (
        review_schema((1,), editable, LOCKS, lessons=[f"{LESSON} (unverified)"])
        .model_validate(claimed)
        .verdict
        == TREATS
    )
    # A lesson she names that she was never given refuses nothing either.
    assert review_schema((1,), editable, LOCKS, lessons=[]).model_validate(answer).verdict == TREATS

    proven = review_schema((1,), editable, LOCKS, lessons=[LESSON])
    refused = proven.model_validate(answer)
    assert refused.verdict == MISSES and refused.broken_lessons[0].confirmed is True
    with pytest.raises(ValidationError, match="broken lesson names the field"):
        proven.model_validate({**answer, "broken_lessons": [{**broken, "field": "subject"}]})


def test_an_audit_brief_is_reviewed_against_its_own_diagnosis_not_a_refused_candidates(
    engine, tmp_path
):
    """2026-10-15, 7c26a7ce scene 1: her audit refused the motion words before the clip was
    bought and briefed the Editor; her review of his rewrite was then handed the still gate's
    findings on the candidate it had refused beside the approved one («a bright window with
    daylight») and refused the clean rewrite as locked to the picture. A brief from the audit
    is answered by its diagnosis; a quality-control brief still by quality control's words."""
    from app.media.prompt_audit import AuditedScene, _brief_of
    from app.media.scene_rewrite import AUDIT_BRIEF, findings_to_treat

    storyboard_id = a_refused_scene(engine, tmp_path, detail=QC_WORDS)
    context = scene_context(engine, storyboard_id, 1)
    assert [item["qc_text"] for item in review_findings(context)] == [QC_WORDS]
    brief = _brief_of(
        AuditedScene(scene_index=1, approved=False, reason="the words contradict the plan"),
        "motion",
    )
    assert brief["source"] == AUDIT_BRIEF and brief["layer"] == "motion"
    (only,) = findings_to_treat(context, brief)
    assert only["source"] == "director_brief" and only["qc_text"] == brief["diagnosis"]
    # The same scene under a quality-control brief answers quality control.
    assert [item["qc_text"] for item in findings_to_treat(context, dict(brief, source=None))] == [
        QC_WORDS
    ]


def test_her_own_diagnoses_are_observations_and_a_minor_finding_does_not_refuse(
    engine, tmp_path, studio
):
    """Scene 7 of f06808c9 (2026-10-12): quality control's finding was treated and her review
    refused the rewrite for two diagnoses of her own. Now quality control's two findings here
    are answered by id — the face treated, the still clouds a minor defect she accepts — and
    what she adds is an observation recorded beside them."""
    storyboard_id = a_refused_scene(
        engine, tmp_path, detail=f"{QC_WORDS}; norii stau aproape pe loc"
    )
    context = scene_context(engine, storyboard_id, 1)
    assert [item["qc_text"] for item in review_findings(context)] == [
        QC_WORDS,
        "norii stau aproape pe loc",
    ]
    said = {
        **TREATED,
        "findings": [
            TREATED["findings"][0],
            {
                "id": 2,
                "treated": False,
                "severity": "minor",
                "why_not": "the cloud moves, but slowly",
                "field": "motion",
            },
        ],
        "observations": ["the camera path generalises to the subject"],
    }
    agents = Agents([SECOND_SHOT], [said])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["review_verdict"] == TREATS, outcome
    assert len(agents.rewrites) == 1
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    review = rewritten.payload["review"]
    assert [(f["id"], f["treated"], f["severity"]) for f in review["findings"]] == [
        (1, True, "serious"),
        (2, False, "minor"),
    ]
    assert review["findings"][1]["qc_text"] == "norii stau aproape pe loc"
    assert review["findings"][1]["finding"] == "norii stau aproape pe loc"
    assert review["observations"] == ["the camera path generalises to the subject"]
    # The minor one she left untreated is accepted: never open, never blocking, never a reason
    # to withdraw a lesson (the shared contract of 2026-10-12 evening); the treated one is not.
    assert [f["accepted"] for f in review["findings"]] == [False, True]
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
    assert shown["why_not"] == []


def test_a_review_naming_a_finding_quality_control_did_not_give_is_asked_again(
    engine, tmp_path, studio
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    her_own = {
        **TREATED,
        "findings": [
            TREATED["findings"][0],
            {
                "id": 2,
                "finding": "the camera sweeps toward the subject",
                "treated": False,
                "severity": "serious",
                "why_not": "the move's sentence names the subject",
                "field": "camera_move",
            },
        ],
    }
    agents = Agents([SECOND_SHOT], [her_own, TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["review_verdict"] == TREATS, outcome
    assert len(agents.reviews) == 2
    assert "did not give" in agents.reviews[1] and "observations" in agents.reviews[1]


def test_a_motion_rewrite_whose_findings_are_locked_turns_to_the_picture_at_once(
    engine, tmp_path, studio
):
    """2026-10-12, 16:46-16:48, f06808c9 scenes 3, 4, 7: what quality control refused was in
    words the motion layer keeps; the second motion rewrite could not treat it and nothing
    turned to the picture. Now he is not asked again on that layer, the attempt is recorded as
    the layer exhausted, and — the still being the gate's, not the Owner's — her brief for the
    picture follows in the same call."""
    storyboard_id = a_refused_scene(engine, tmp_path, still_by="still_gate")
    agents = Agents([SECOND_SHOT, STILL_SHOT], [LOCKED, TREATED], briefs=[BRIEF, STILL_BRIEF])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    assert outcome["escalated_from"] == MOTION
    assert "e rândul imaginii" in outcome["motion_reason"]
    # One motion rewrite (no second on a layer that cannot treat it), then the picture.
    assert len(agents.briefs) == 2 and len(agents.rewrites) == 2 and len(agents.reviews) == 2
    assert "only still is open" in agents.briefs[1]
    motion, picture = events(engine, BRIEF_EVENT, storyboard_id)
    assert motion.payload["layer"] == MOTION and motion.payload["layer_exhausted"] is True
    assert motion.payload["rewritten"] is False and motion.payload["locked_findings"] == [1]
    # The quote is the picture's (the still the motion keeps): the picture's turn, no note.
    assert motion.payload["review_attempts"][0]["lock"] == LOCK_PICTURE
    assert (
        motion.payload["composer_locked"] is False and motion.payload["developer_note_id"] is None
    )
    assert picture.payload["layer"] == STILL and picture.payload["rewritten"] is True
    assert "empty terraced fields" in stored(engine, storyboard_id)["still_prompt"].lower()
    # Her brief for the picture read the exhausted attempt.
    assert '"layer_exhausted": true' in agents.briefs[1]


def developer_notes(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(select(AgentMessage))
            if isinstance(row.body_json, dict)
            and row.body_json.get("kind") == DEVELOPER_DEFECT_KIND
        ]


def refused_again(engine, storyboard_id: str, detail: str = QC_WORDS) -> str:
    """A newer take of scene 1 refused by clip QC (no vendor, no credits)."""
    now = utc_now()
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="test_shot",
                prompt_hash=uuid4().hex,
                model_id="seedance2_5",
                resolution="1080:1920",
                status="REJECTED",
                failure_code="QC.CLIP",
                failure_detail=detail,
                path=None,
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )
    return take_id


def refused_take(engine, storyboard_id: str) -> str:
    with Session(engine) as session:
        return session.scalar(
            select(SceneTake.id).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.status == "REJECTED"
            )
        )


def test_a_locked_finding_on_a_picture_he_approved_waits_and_says_why(engine, tmp_path, studio):
    """His picture is never rewritten, and the motion cannot treat what is in it: nothing is
    bought, the developer is told once, the take goes to her second look — and the ladder's
    retries do not ask her the same brief again until something changes (2026-10-12 evening
    review of a50407e: it waited silently and was asked again every retry)."""
    storyboard_id = a_refused_scene(engine, tmp_path)  # the Owner approved the still
    before = stored(engine, storyboard_id)
    agents = Agents([SECOND_SHOT], [LOCKED])
    registry = they_say(studio, agents)

    outcome = rewrite_failed_scene(engine, registry, storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["layer_exhausted"] is True, outcome
    assert outcome["not_treating"] is True and "escalated_from" not in outcome
    assert outcome["second_look"] is True and outcome["refused_take_id"] == refused_take(
        engine, storyboard_id
    )
    assert (
        "aprobată de Proprietar" in outcome["reason"]
        and "e rândul imaginii" not in outcome["reason"]
    )
    assert len(agents.rewrites) == 1 and len(agents.reviews) == 1
    assert stored(engine, storyboard_id) == before
    (note,) = developer_notes(engine)
    assert note.id == outcome["developer_note_id"] and note.status == "RESOLVED"
    assert note.body_json["scene_index"] == 1 and QC_WORDS in note.body_text
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION,)

    # The retry pass's walk asks again: she is not asked the same brief, nothing is noted twice.
    again = rewrite_failed_scene(engine, registry, storyboard_id, 1, str(uuid4()))
    assert again["waiting"] is True and again["rewritten"] is False and again["second_look"] is True
    assert "nu o mai întreb" in again["reason"]
    assert len(agents.briefs) == 1 and len(agents.rewrites) == 1
    assert len(events(engine, BRIEF_EVENT, storyboard_id)) == 1
    assert len(developer_notes(engine)) == 1

    # Something changed — quality control refused a newer take: she is asked again.
    refused_again(engine, storyboard_id)
    rewrite_failed_scene(engine, registry, storyboard_id, 1, str(uuid4()))
    assert len(agents.briefs) == 2 and len(events(engine, BRIEF_EVENT, storyboard_id)) == 2
    assert len(developer_notes(engine)) == 1  # one note per scene


def test_the_refused_words_again_on_the_motion_layer_exhaust_it_for_the_redo(
    engine, tmp_path, studio
):
    """His second rewrite gives the words she refused: the motion layer has nothing else to
    say, and the paid redo's correction tells its caller so (`runbook.stages` turns to the
    still, as on ``same_prompt``)."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    agents = Agents([FIRST_SHOT, FIRST_SHOT], [MISSED])

    outcome = rewrite_for_redo(
        engine, they_say(studio, agents), storyboard_id, 1, "motion", [QC_WORDS], str(uuid4())
    )

    assert outcome["rewritten"] is False and outcome["rewritable"] is True, outcome
    assert outcome["layer_exhausted"] is True and outcome["not_treating"] is True
    assert "aceleași cuvinte pe care Directoarea le-a refuzat" in outcome["reason"]
    assert len(agents.rewrites) == 2 and len(agents.reviews) == 1


def test_an_unreadable_second_review_keeps_the_first_reviews_refusal(engine, tmp_path, studio):
    """2026-10-12 review: her review of his second rewrite could not be read, and the outcome
    said «review unavailable», erasing the first review's MISSES and its cause."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    before = stored(engine, storyboard_id)
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, "I would rather not say."])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["not_treating"] is True, outcome
    assert outcome["review_unavailable"] is False and outcome["layer_exhausted"] is False
    assert outcome["review_verdict"] == MISSES
    assert outcome["review_reason_ro"] == MISSED["reason_ro"]
    assert "verificarea ei nu a putut fi făcută" in outcome["reason"]
    assert stored(engine, storyboard_id) == before
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["review_verdict"] == MISSES and brief.payload["cause"] == CAUSE
    assert [r["verdict"] for r in brief.payload["review_attempts"]] == [MISSES, None]


def test_the_films_findings_reach_the_brief_with_the_cause_she_found(engine, tmp_path, studio):
    """The reasons a redo hands the rewrite carry the Director's verdict's cause (2026-10-12):
    her brief and her review read them as quality control's findings, each with its cause; the
    studio's own notes beside them are no finding."""
    second_look = "Directoarea a privit din nou scena: profilul e real, se reface mișcarea."
    proposal = (
        "After the new still is bought and approved, the motion must be redone on the new "
        "still with a prompt that names the final framing."
    )
    reasons: list[Any] = [
        {"text": "ending frame shows the two in profile", "cause": "the action turns him"},
        "Scena 1: mișcarea filmată din imaginea nouă.",
        "the clip barely moved (cauza: the motion asked only for a slow drift)",
        "Cauza: the plan never said where the clip ends",
        # Her repair proposal, her second look and the studio's notes ride in the same list
        # (`runbook.stages._correct_before_redo`): context for her brief, never a finding
        # with an id that decides the review (2026-10-12 evening review of a50407e).
        proposal,
        second_look,
        LAYER_EXHAUSTED_NOTE,
        SAME_PROMPT_NOTE,
    ]
    failure = film_failure(reasons)
    assert failure["reasons"] == [
        "ending frame shows the two in profile",
        "the clip barely moved",
    ]
    assert failure["causes"] == ["the action turns him", "the motion asked only for a slow drift"]
    assert failure["cause"] == "the plan never said where the clip ends"
    assert failure["context"] == [
        "Scena 1: mișcarea filmată din imaginea nouă.",
        proposal,
        second_look,
        LAYER_EXHAUSTED_NOTE,
        SAME_PROMPT_NOTE,
    ]
    # A reason that says what was seen and then what to buy keeps only what was seen.
    mixed = film_failure(
        ["Both women face each other in profile. Redo the motion on the new still."]
    )
    assert mixed["reasons"] == ["Both women face each other in profile."]
    storyboard_id = a_refused_scene(engine, tmp_path)
    treats_all = {
        **TREATED,
        "findings": [{**TREATED["findings"][0], "id": number} for number in (1, 2)],
    }
    agents = Agents([SECOND_SHOT], [treats_all])

    outcome = rewrite_for_redo(
        engine, they_say(studio, agents), storyboard_id, 1, "motion", reasons, str(uuid4())
    )

    assert outcome["rewritten"] is True, json.dumps(outcome, ensure_ascii=False)
    brief = boundary_data(agents.briefs[0], "scene-brief")
    review = boundary_data(agents.reviews[0], "rewrite-review")
    for data in (brief, review):
        found = data["quality_control_findings"]
        # The current film's findings; a historical candidate's QC is not a new finding.
        assert [(f["id"], f["qc_text"], f.get("cause")) for f in found] == [
            (1, "ending frame shows the two in profile", "the action turns him"),
            (2, "the clip barely moved", "the motion asked only for a slow drift"),
        ]
    assert brief["refusals"][0]["cause"] == "the plan never said where the clip ends"


def test_with_no_finding_a_picture_could_show_her_diagnosis_is_what_the_review_checks(
    engine, tmp_path, studio
):
    """f06808c9 scene 7, 2026-10-12: the only «finding» the redo carried was the studio's own
    note («Scena 7: mișcarea filmată din imaginea nouă.»). A note is no finding: with nothing
    of quality control's to answer, her review checks the rewrite against her brief's
    diagnosis, and the record says so."""
    storyboard_id = a_film(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        row.prompt_json = {**dict(row.prompt_json or {}), **PLAN}
    agents = Agents([SECOND_SHOT], [TREATED])

    outcome = rewrite_for_redo(
        engine,
        they_say(studio, agents),
        storyboard_id,
        1,
        "motion",
        ["Scena 1: mișcarea filmată din imaginea nouă."],
        str(uuid4()),
    )

    assert outcome["rewritten"] is True, outcome
    assert "quality_control_findings" not in boundary_data(agents.briefs[0], "scene-brief")
    review = boundary_data(agents.reviews[0], "rewrite-review")
    assert review["quality_control_findings"] == [
        {"id": 1, "qc_text": BRIEF["diagnosis"], "source": "director_brief", "code": None}
    ]
    (rewritten,) = directors_rewrites(engine, storyboard_id)
    (finding,) = rewritten.payload["review"]["findings"]
    assert finding["source"] == "director_brief" and finding["qc_text"] == BRIEF["diagnosis"]


def test_the_layer_terms_name_what_the_motion_keeps_and_the_composers_sentences(
    engine, tmp_path, studio
):
    storyboard_id = a_refused_scene(engine, tmp_path)
    context = scene_context(engine, storyboard_id, 1)
    assert context is not None

    motion = layer_terms(context, MOTION)
    still = layer_terms(context, STILL)

    assert list(motion["fields_he_may_change"]) == ["motion", "camera_move", "ending_frame"]
    assert motion["kept_word_for_word"]["action"] == PLAN["action"]
    # The still is in the prompts beside the terms: it is not said again under them
    # (2026-10-12 evening review: the payloads ran 16-19 thousand characters).
    assert motion["still_kept_whole"] == STILL_KEPT_WHOLE
    assert motion["fixed_sentences"]["still"] == [LOOK, prompt_agent.STILL_EXCLUSIONS]
    assert "subject" in still["fields_he_may_change"] and still["kept_word_for_word"] == {}
    assert "still_kept_whole" not in still
    # The people rule is said by the subject he chooses on the still layer — his to change —
    # and is the picture's on a motion rewrite, where the still is kept whole.
    assert still["said_by_his_fields"]["subject"] == [prompt_agent.PEOPLE_SENTENCE]
    assert "subject" not in motion["said_by_his_fields"]
    on_motion = lock_texts(context, MOTION)
    assert on_motion["picture"][0] == context["visual_prompt"]
    assert LOOK in on_motion["constants"]
    on_still = lock_texts(context, STILL)
    assert on_still["picture"] == () and LOOK in on_still["constants"]
    assert prompt_agent.PEOPLE_SENTENCE not in on_still["constants"]


# ------------------------------------------------------------------ 2026-10-12 evening review


def replies(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(select(AgentMessage))
            if str(row.subject or "").startswith("Re: Rescrie scena")
        ]


def test_every_finding_minor_buys_nothing_and_the_take_goes_to_her_second_look(
    engine, tmp_path, studio, recorded
):
    """2026-10-12 evening review of a50407e: a rewrite that treated nothing was stored and
    bought because she rated each finding minor. When no finding of quality control's is
    serious the take is acceptable as it is: nothing is stored or bought, no lesson is drawn
    from a review that treated nothing, and the caller hands the take to her second look. The
    Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!»"""
    storyboard_id = a_refused_scene(engine, tmp_path, detail=CLOUDS)
    before = stored(engine, storyboard_id)
    agents = Agents([SECOND_SHOT], [ALL_MINOR])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["accepted_minor"] is True, outcome
    assert outcome["accepted_minor_ids"] == [1] and outcome["second_look"] is True
    assert outcome["refused_take_id"] == refused_take(engine, storyboard_id)
    assert outcome["review_verdict"] == ACCEPTED_MINOR and outcome["not_treating"] is False
    assert outcome["layer_exhausted"] is False and outcome["composer_locked"] is False
    assert "defecte mici" in outcome["reason"]
    # Nothing stored, nothing bought, no lesson from a review that treated nothing.
    assert stored(engine, storyboard_id) == before
    assert directors_rewrites(engine, storyboard_id) == []
    assert recorded == [] and lessons_for(engine, None) == []
    assert len(agents.rewrites) == 1 and len(agents.reviews) == 1
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert brief.payload["accepted_minor"] is True and brief.payload["accepted_minor_ids"] == [1]
    assert brief.payload["review_verdict"] == ACCEPTED_MINOR
    assert brief.payload["review_findings"][0]["accepted"] is True
    assert brief.payload["second_look"] is True and brief.payload["developer_note_id"] is None
    (reply,) = replies(engine)
    assert "nu se cumpără nimic" in reply.body_text
    # Her next brief reads it as accepted, with nothing left open, and it is no motion attempt.
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
        assert shown["accepted_minor"] is True and shown["why_not"] == []
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION,)

    # The paid redo's correction says the same to its caller (`runbook.stages`).
    other = a_refused_scene(engine, tmp_path, detail=CLOUDS)
    redo = rewrite_for_redo(
        engine,
        they_say(studio, Agents([SECOND_SHOT], [ALL_MINOR])),
        other,
        1,
        "motion",
        [CLOUDS],
        str(uuid4()),
    )
    assert redo["rewritable"] is True and redo["rewritten"] is False, redo
    assert redo["accepted_minor"] is True and redo["second_look"] is True
    assert directors_rewrites(engine, other) == []


def test_a_hard_limit_or_a_finding_found_serious_in_the_rung_stays_serious(
    engine, tmp_path, studio
):
    """2026-10-12 evening review of a50407e: a face where the bible forbids faces could be rated
    minor and the take accepted; and her second review in the rung could downgrade what her
    first found serious."""
    # The bible forbids faces: quality control's «o față» is serious whatever she says.
    storyboard_id = a_refused_scene(engine, tmp_path)
    minor_face = {**ALL_MINOR, "findings": [{**ALL_MINOR["findings"][0], "finding": "a face"}]}
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [minor_face])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome.get("accepted_minor") is False, outcome
    assert outcome["not_treating"] is True and outcome["review_verdict"] == MISSES
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    assert [r["findings"][0]["severity"] for r in brief.payload["review_attempts"]] == [
        "serious",
        "serious",
    ]

    # No hard limit, but serious in her first review: her second may not call it minor.
    other = a_refused_scene(engine, tmp_path, detail=CLOUDS)
    serious_first = {**ALL_MINOR, "findings": [{**ALL_MINOR["findings"][0], "severity": "serious"}]}
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [serious_first, ALL_MINOR])

    again = rewrite_failed_scene(engine, they_say(studio, agents), other, 1, str(uuid4()))

    assert again["accepted_minor"] is False and again["not_treating"] is True, again
    assert len(agents.reviews) == 2
    (brief,) = events(engine, BRIEF_EVENT, other)
    assert [r["verdict"] for r in brief.payload["review_attempts"]] == [MISSES, MISSES]
    assert brief.payload["review_attempts"][1]["findings"][0]["severity"] == "serious"


def with_motion(engine, storyboard_id: str) -> None:
    """The scene's stored motion prompt as the composer says it (the fixture film stores none)."""
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        )
        row.prompt_json = {
            **dict(row.prompt_json or {}),
            "motion_prompt": f"Low grey cloud drifts slowly over the ridges. {MOTION_CLOSING}",
        }


def test_a_lock_in_the_composers_own_sentences_buys_nothing_and_waits_for_the_developer(
    engine, tmp_path, studio, monkeypatch
):
    """Editor-owned finals have no composer locks; a false lock fails closed."""
    storyboard_id = a_refused_scene(engine, tmp_path, still_by="still_gate")
    with_motion(engine, storyboard_id)
    before = stored(engine, storyboard_id)
    agents = Agents([SECOND_SHOT], [COMPOSER_LOCKED])
    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))
    assert outcome["rewritten"] is False
    assert outcome["composer_locked"] is False
    assert outcome["review_unavailable"] is True
    assert stored(engine, storyboard_id) == before
    assert directors_rewrites(engine, storyboard_id) == []
    assert developer_notes(engine) == []


def test_a_lock_on_the_still_layer_is_the_composers_and_notes_the_developer(
    engine, tmp_path, studio
):
    """Editor-owned finals have no composer locks; a false lock fails closed."""
    storyboard_id = a_refused_scene(engine, tmp_path, still_by="still_gate")
    before = stored(engine, storyboard_id)
    locked = {
        **COMPOSER_LOCKED,
        "findings": [
            {
                **COMPOSER_LOCKED["findings"][0],
                "layer": "still",
                "locked_words": "main subject in the upper two thirds",
            }
        ],
    }
    agents = Agents([STILL_SHOT], [locked], briefs=[STILL_BRIEF])
    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))
    assert outcome["rewritten"] is False
    assert outcome["composer_locked"] is False
    assert outcome["review_unavailable"] is True
    assert stored(engine, storyboard_id) == before
    assert directors_rewrites(engine, storyboard_id) == []
    assert developer_notes(engine) == []


def test_a_motion_rung_refused_twice_is_a_motion_attempt(engine, tmp_path, studio):
    """2026-10-12 evening review of a50407e: a motion brief whose second rewrite was refused
    too was not counted, so motion was chosen again without end. It is a motion attempt on
    this picture now: the picture's turn comes next."""
    storyboard_id = a_refused_scene(engine, tmp_path, still_by="still_gate")
    second_miss = {
        **MISSED,
        "findings": [
            {
                **MISSED["findings"][0],
                "why_not": "the ending still holds a silhouette",
                "field": "ending_frame",
            }
        ],
    }
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, second_miss])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["not_treating"] is True and outcome["layer_exhausted"] is False, outcome
    with Session(engine) as session:
        (shown,) = earlier_briefs(session, storyboard_id, 1)
        assert shown["refused_twice"] is True
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (STILL,)


def test_quality_controls_refusal_is_split_whole_before_any_cut(engine, tmp_path, studio):
    """2026-10-12 evening review of a50407e: the refusal was cut at 400 characters first and
    split after, so a finding ended «Verdictu», the cut verdict line read as a finding, and a
    «prag 15%)» split off its sentence. Now the whole refusal is split at the gate's «; »,
    never inside «…» or (…), the verdict line goes, a fragment joins the finding before it,
    and only then is each finding cut."""
    first = (
        "Modelul de vedere nu vede ce cere scena: «two women; facing each other» across the "
        "ledger (prag 15%; măsurat 40%) " + "and the room behind them is crowded " * 6
    )
    second = "Nadia stands in profile at the window, her face turned from the viewer " * 5
    detail = f"{first}; {second}; în profil; Verdictul modelului de vedere: regenerate_still"
    assert len(detail) > 2 * 300  # a cut at 400 before the split would have cut a finding

    found = refusal_findings(detail)

    assert len(found) == 2
    assert (
        found[0].startswith("Modelul de vedere nu vede") and "(prag 15%; măsurat 40%)" in found[0]
    )
    assert "«two women; facing each other»" in found[0]
    assert found[1].startswith("Nadia stands in profile") and found[1].endswith("în profil")
    assert all("Verdict" not in text for text in found)
    assert all(len(text) <= 400 for text in found)
    # The brief and the review answer exactly these, by id.
    storyboard_id = a_refused_scene(engine, tmp_path, detail=detail)
    context = scene_context(engine, storyboard_id, 1)
    assert [item["qc_text"] for item in review_findings(context)] == found


def test_a_still_brief_whose_picture_did_not_change_is_asked_again_not_reviewed_on_the_motion(
    engine, tmp_path, studio, monkeypatch
):
    """2026-10-12 evening review of a50407e: a still brief whose rewrite left the picture's
    words as they were was reviewed on the motion's terms, as if the brief had asked for the
    movement. Her review is bound to the brief's layer; a rewrite that did not change the
    picture is not reviewed at all, and he is asked once more, told the picture's words did not
    change."""
    storyboard_id = a_refused_scene(engine, tmp_path, still_by="still_gate")
    real = rewrite_module.rewritten_package
    calls: list[int] = []

    def compiler(context, shot, layer, brief):
        package = real(context, shot, layer, brief)
        calls.append(1)
        if len(calls) == 1:  # the first rewrite composes the same picture's words again
            package["still_prompt"] = context["visual_prompt"]
        return package

    monkeypatch.setattr(rewrite_module, "rewritten_package", compiler)
    agents = Agents([STILL_SHOT, STILL_SHOT], [TREATED], briefs=[STILL_BRIEF])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    assert len(agents.rewrites) == 2 and len(agents.reviews) == 1
    assert "the picture's words did not" in agents.rewrites[1]
    assert "on the still layer" in agents.reviews[0]
    assert boundary_data(agents.reviews[0], "rewrite-review")["this_layer"]["layer"] == STILL
    (brief,) = events(engine, BRIEF_EVENT, storyboard_id)
    first, second = brief.payload["review_attempts"]
    assert first["still_unchanged"] is True and first["review_run_id"] is None
    assert second["verdict"] == TREATS and second["layer"] == STILL


def test_the_second_rewrite_and_its_review_fit_the_budget_with_her_feedback(
    engine, tmp_path, studio
):
    """2026-10-12 evening review of a50407e, measured on that day's runs: the rewrites ran
    21-24 thousand characters and the second round added 10 thousand more — the moves'
    sentences and the layer's terms said again, the still repeated under the fixed sentences,
    her earlier review repeating quality control's words. Now each is said once, the scene's
    history gives way first, and the second rewrite's data is fitted together with her
    feedback."""
    storyboard_id = a_refused_scene(engine, tmp_path)
    long_tail = " because the ridge line kept a figure that could turn toward the lens" * 10
    with Session(engine) as session, session.begin():
        for number in range(1, 15):
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
                    "reason": "Rescrierea nu tratează constatarea: …" + long_tail,
                    "review_verdict": "MISSES",
                    "diagnosis": f"diagnosis number {number}{long_tail}",
                    "avoid": [f"a figure on the ridge {long_tail}"] * 3,
                    "change": [f"the cloud moves alone {long_tail}"] * 3,
                    "cause": f"cause number {number}{long_tail}",
                    "review_attempts": [
                        {
                            "verdict": "MISSES",
                            "findings": [{"finding": f"face {number}", "why_not": long_tail}],
                        }
                    ],
                },
                str(uuid4()),
            )
    for _ in range(4):
        refused_again(engine, storyboard_id, detail=f"{QC_WORDS}; {long_tail}; {long_tail}")
    refused_again(engine, storyboard_id)  # the newest: quality control's one finding
    context = scene_context(engine, storyboard_id, 1)
    whole = json.dumps(
        [context["failures"], context["briefs"], context["older_briefs"]], ensure_ascii=False
    )
    assert len(whole) > 28000  # exceeds both former 14,000-character payloads
    agents = Agents([FIRST_SHOT, SECOND_SHOT], [MISSED, TREATED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is True, outcome

    brief_data = boundary_data(agents.briefs[0], "scene-brief")
    assert brief_data["earlier_briefs"] == context["briefs"]
    assert brief_data["refusals"] == context["failures"]
    first, second = agents.rewrites
    feedback = boundary_data(second, "rewrite-feedback")
    for prompt in (first, second):
        payload = boundary_data(prompt, "scene-rewrite")
        assert payload["refusals"] == context["failures"]
    # Said once: the moves' sentences and the layer's terms are not in her feedback, and her
    # earlier review gives quality control's words by id, not again.
    assert "camera_move_sentences" not in feedback and "this_layer" not in feedback
    earlier = boundary_data(agents.reviews[1], "rewrite-review")["your_earlier_review"]
    assert all("qc_text" not in item for item in earlier["findings"])
    # The newest refusal and the findings stay, whatever history gave way.
    data = boundary_data(second, "scene-rewrite")
    assert data["quality_control_findings"][0]["qc_text"] == QC_WORDS
    assert data["director_brief"]["diagnosis"] == BRIEF["diagnosis"]
