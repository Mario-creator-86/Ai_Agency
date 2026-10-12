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
from app.agents.models import ModelRecord
from app.agents.services import seed_initial_workforce
from app.media import prompt_agent
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT
from app.media.models import StoryboardScene
from app.media.prompt_lint import MOTION_CLOSING
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    MAX_OLDER_BRIEFS,
    MAX_PAYLOAD_CHARS,
    MINOR,
    MISSES,
    MOTION,
    OLDER_DIAGNOSIS_CHARS,
    STILL,
    TREATS,
    director_brief,
    earlier_briefs,
    film_failure,
    layer_terms,
    open_layers,
    review_findings,
    review_schema,
    rewrite_failed_scene,
    rewrite_for_redo,
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
from test_failed_brief_is_recorded import PLAN, a_refused_scene, contract_lessons
from test_film_costing import a_film

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
            "field": "motion",
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
#: Her review when the words that invite the finding are the plan's action, which a motion
#: rewrite keeps word for word (f06808c9's «turning fully toward her», 2026-10-12).
LOCKED = {
    "findings": [
        {
            "id": 1,
            "finding": "a face seen in profile",
            "treated": False,
            "severity": "serious",
            "why_not": "the picture's action keeps the village's people in the frame",
            "locked": True,
            "locked_words": PLAN["action"],
        }
    ],
    "reason_ro": "Mișcarea nu poate scoate oamenii: acțiunea imaginii îi păstrează.",
    "cause": "The plan's action keeps people in the picture the clip moves.",
    "lesson": "",
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
            return GenerateResult(self._next(self.shots, len(self.rewrites) - 1), 10, 40, None)
        if '"rewrite-review"' in prompt:
            self.reviews.append(prompt)
            said = self._next(self.reviews_said, len(self.reviews) - 1)
            return GenerateResult(said, 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


@pytest.fixture(autouse=True)
def lesson_store(monkeypatch):
    return contract_lessons(monkeypatch)


@pytest.fixture
def recorded(monkeypatch, lesson_store):
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
            "field": "motion",
        }
    ]
    # He is told, both times, what the motion layer lets him change and what it keeps.
    for asked in (first, second):
        terms = boundary_data(asked, "scene-rewrite")["this_layer"]
        assert list(terms["fields_he_may_change"]) == ["motion", "camera_move", "ending_frame"]
        assert terms["kept_word_for_word"]["action"] == PLAN["action"]
    assert MOTION_CLOSING in feedback["this_layer"]["fixed_sentences"]["motion"]
    # Her reviews answered quality control's finding by its id, with its own words.
    review_data = boundary_data(agents.reviews[0], "rewrite-review")
    assert review_data["quality_control_findings"] == [
        {"id": 1, "qc_text": QC_WORDS, "source": "test_shot", "code": "QC.CLIP"}
    ]
    assert "fields_he_may_change" in review_data["this_layer"]
    assert "slow pan left" in review_data["camera_move_sentences"]
    # Her second review saw her first, and checked the untreated finding first.
    assert "your_earlier_review" in agents.reviews[1] and WHY_NOT in agents.reviews[1]
    assert "your_earlier_review" not in agents.reviews[0]
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
            "field": "",
            "locked": False,
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

    assert outcome["rewritten"] is True, outcome
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
        f"diagnosis number {n}" for n in range(17, 21)
    ]
    older = context["older_briefs"]
    assert len(older) == MAX_OLDER_BRIEFS
    assert [b["diagnosis"].split(" because")[0] for b in older] == [
        f"diagnosis number {n}" for n in range(5, 17)
    ]
    assert all(len(b["diagnosis"]) <= OLDER_DIAGNOSIS_CHARS for b in older)
    assert older[0]["cause"] == "cause number 5"
    agents = Agents([SECOND_SHOT], [TREATED])
    rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))
    (asked,) = agents.briefs
    assert "older_briefs_in_short" in asked and "diagnosis number 5" in asked


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
    assert data["older_briefs_in_short"][0]["diagnosis"].startswith("diagnosis 0")


def test_her_review_answers_quality_controls_findings_by_id_and_says_how_serious():
    """The review's schema for one rewrite: quality control gave findings 1 and 2; the motion
    layer lets him change motion, camera_move and ending_frame and keeps the plan's action."""
    schema = review_schema((1, 2), ("motion", "camera_move", "ending_frame"), (PLAN["action"],))
    done = {"treated": True, "severity": "serious", "by": TREATED_BY}
    left = {"treated": False, "severity": "serious", "why_not": WHY_NOT, "field": "motion"}

    def review(*findings: dict[str, Any], **more: Any) -> dict[str, Any]:
        return {"findings": list(findings), "reason_ro": "…", "cause": CAUSE, **more}

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
    with pytest.raises(ValidationError, match="not in the words this layer keeps"):
        schema.model_validate(
            review(
                {"id": 1, **done},
                {**left, "id": 2, "locked": True, "locked_words": "a herder looking down"},
            )
        )
    locked = schema.model_validate(
        review(
            {"id": 1, **done},
            {**left, "id": 2, "locked": True, "locked_words": "«The village rests … ridges»"},
        )
    )
    assert locked.verdict == MISSES and [item.id for item in locked.blocking] == [2]
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
    # Words that break a lesson of the studio's refuse it too.
    broken = schema.model_validate(
        review(
            {"id": 1, **done},
            {"id": 2, **done},
            broken_lessons=[{"lesson": LESSON, "why_not": "a herder moves", "field": "motion"}],
        )
    )
    assert broken.verdict == MISSES


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
    assert picture.payload["layer"] == STILL and picture.payload["rewritten"] is True
    assert "empty terraced fields" in stored(engine, storyboard_id)["still_prompt"].lower()
    # Her brief for the picture read the exhausted attempt.
    assert '"layer_exhausted": true' in agents.briefs[1]


def test_a_locked_finding_on_a_picture_he_approved_waits_and_says_why(engine, tmp_path, studio):
    storyboard_id = a_refused_scene(engine, tmp_path)  # the Owner approved the still
    before = stored(engine, storyboard_id)
    agents = Agents([SECOND_SHOT], [LOCKED])

    outcome = rewrite_failed_scene(engine, they_say(studio, agents), storyboard_id, 1, str(uuid4()))

    assert outcome["rewritten"] is False and outcome["layer_exhausted"] is True, outcome
    assert outcome["not_treating"] is True and "escalated_from" not in outcome
    assert len(agents.rewrites) == 1 and len(agents.reviews) == 1
    assert stored(engine, storyboard_id) == before
    with Session(engine) as session:
        assert open_layers(session, storyboard_id, 1, last_code="QC.CLIP") == (MOTION,)


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
    reasons: list[Any] = [
        {"text": "ending frame shows the two in profile", "cause": "the action turns him"},
        "Scena 1: mișcarea filmată din imaginea nouă.",
        "the clip barely moved (cauza: the motion asked only for a slow drift)",
        "Cauza: the plan never said where the clip ends",
    ]
    failure = film_failure(reasons)
    assert failure["reasons"] == [
        "ending frame shows the two in profile",
        "Scena 1: mișcarea filmată din imaginea nouă.",
        "the clip barely moved",
    ]
    assert failure["causes"] == [
        "the action turns him",
        "",
        "the motion asked only for a slow drift",
    ]
    assert failure["cause"] == "the plan never said where the clip ends"
    storyboard_id = a_refused_scene(engine, tmp_path)
    treats_all = {
        **TREATED,
        "findings": [{**TREATED["findings"][0], "id": number} for number in (1, 2, 3)],
    }
    agents = Agents([SECOND_SHOT], [treats_all])

    outcome = rewrite_for_redo(
        engine, they_say(studio, agents), storyboard_id, 1, "motion", reasons, str(uuid4())
    )

    assert outcome["rewritten"] is True, outcome
    brief = boundary_data(agents.briefs[0], "scene-brief")
    review = boundary_data(agents.reviews[0], "rewrite-review")
    for data in (brief, review):
        found = data["quality_control_findings"]
        # The film's two findings with their causes, then the clip's refusal (the newest take).
        assert [(f["id"], f["qc_text"], f.get("cause")) for f in found] == [
            (1, "ending frame shows the two in profile", "the action turns him"),
            (2, "the clip barely moved", "the motion asked only for a slow drift"),
            (3, QC_WORDS, None),
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
    assert motion["fixed_sentences"]["still"] == [" ".join(context["visual_prompt"].split())]
    assert "subject" in still["fields_he_may_change"] and still["kept_word_for_word"] == {}
