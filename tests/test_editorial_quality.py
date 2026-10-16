"""Good idea, good story, good script, good prompt — checked before the money.

The Owner's principle, and the order it has to be enforced in: a powerful video model cannot
rescue a weak idea or weak storytelling, so the studio optimises the content first and the
generation second. These are the twenty-one checks he asked for.

They are all local: a scripted model, no vendor, no generation. That is the point — every one
of these would otherwise be discovered after a render had already been paid for.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.factual.editorial import composite, expected_seconds, idea_rejections, story_checks
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, StoryReview, TopicIdea
from app.media.models import CharacterBible, Storyboard, StoryboardScene
from app.media.prompt_agent import (
    PromptError,
    compose_prompt,
    new_numbers,
    production_package,
    prompt_lessons,
    record_prompt_lesson,
    write_shot_prompts,
)
from app.media.services import generate_storyboard_from_script, seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.services import seed_default_channels
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers


class ScriptedModel:
    """A model that answers whatever the test decided, and remembers what it was asked."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.prompts.append(prompt)
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        from app.agents.models import ModelRecord

        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        from app.agents.models import Agent

        provider_id = session.scalar(select(Agent.provider_id))
    return {"provider_id": provider_id}


def registry_with(studio, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(studio["provider_id"], model)
    return registry, model


#: A thesis that answers every editorial question. Used as the baseline the tests break.
GOOD_THESIS = {
    "core_fact": "A reserved web address exists so that nobody can own it.",
    "why_it_matters": "Everyone has typed it, and nobody knows why it cannot be bought.",
    "why_now": "The registry refreshed the page this week.",
    "payoff": "The registry reserves the address itself, so no company can ever hold it.",
    "hook": "There is one web address on earth nobody is allowed to buy.",
    "ending": "Reserved on purpose, by the registry that runs the list.",
    "cta": "Which reserved address surprised you most?",
    "cta_kind": "COMMENT",
    "channel_fit": "One verifiable idea, thirty seconds.",
    "visual_potential": "A browser bar, a registry page, a padlock closing.",
    "risk": "Nothing beyond the registry's own wording.",
    "expected_seconds": 30,
}

GOOD_SCORES = {
    "hook_potential": 0.8,
    "curiosity": 0.8,
    "story_potential": 0.75,
    "payoff_strength": 0.8,
    "visual_potential": 0.5,
    "fact_confidence": 0.9,
    "channel_fit": 0.8,
    "originality": 0.7,
    "shareability": 0.6,
    "retention_potential": 0.7,
    "cta_opportunity": 0.6,
    "production_feasibility": 0.9,
    "source_availability": 1.0,
}

#: A script that is a story: a hook, a causal middle, a payoff that answers the hook, an
#: ending, and a closing question about this film. Roughly thirty seconds of narration.
GOOD_SCENES = [
    {
        "scene_number": 1,
        "purpose": "HOOK",
        "narration": "There is one web address nobody on earth is allowed to buy.",
        "visual_description": "A browser bar with the address typed into it.",
        "claim_ids": ["c1"],
    },
    {
        "scene_number": 2,
        "purpose": "SETUP",
        "narration": "It looks ordinary, but every registrar refuses it.",
        "visual_description": "A registrar page returning a refusal.",
        "claim_ids": ["c1"],
    },
    {
        "scene_number": 3,
        "purpose": "DEVELOPMENT",
        "narration": "That is because the address was set aside before the web grew up.",
        "visual_description": "An old technical document on a desk.",
        "claim_ids": ["c2"],
    },
    {
        "scene_number": 4,
        "purpose": "REVEAL",
        "narration": "The registry reserved the address itself, so no company can hold it.",
        "visual_description": "A padlock closing over the registry's own page.",
        "claim_ids": ["c2"],
    },
    {
        "scene_number": 5,
        "purpose": "ENDING",
        "narration": "Which reserved address surprised you most?",
        "visual_description": "The address glowing in an empty browser bar.",
        "claim_ids": ["c1"],
    },
]

GOOD_STORY = {
    "core_message": "One web address is reserved so nobody can ever own it.",
    "takeaway": "Some addresses are reserved by the registry, on purpose.",
    "hook": "There is one web address nobody on earth is allowed to buy.",
    "ending": "Reserved on purpose, by the registry itself.",
    "cta": "Which reserved address surprised you most?",
    "cta_kind": "COMMENT",
    "estimated_seconds": 21.0,
    "target_seconds": 20,
    "structure": ["HOOK", "SETUP", "DEVELOPMENT", "REVEAL", "ENDING"],
}


def a_topic(engine, *, thesis=None, scores=None, with_claims=True, with_source=True) -> str:
    """A topic with its argument, its claims and the page they came from."""
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, str(uuid4())
        )
        session.add(
            TopicIdea(
                id=topic_id,
                title="The address nobody may buy",
                topic="internet",
                angle="Why one address is reserved",
                target_audience="general",
                novelty_score=0.7,
                status="SELECTED",
                scores_json={
                    **(scores or GOOD_SCORES),
                    "composite": composite(scores or GOOD_SCORES),
                },
                source_plan_json=["www.iana.org"],
                thesis_json=thesis if thesis is not None else GOOD_THESIS,
                rejection_reasons_json=[],
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        source_id = str(uuid4())
        if with_source:
            session.add(
                SourceSnapshot(
                    id=source_id,
                    topic_id=topic_id,
                    url="https://www.iana.org/domains/reserved",
                    title="Reserved domains",
                    publisher="IANA",
                    content_hash="0" * 64,
                    raw_content="The address is reserved.",
                    sanitized_content="The address is reserved.",
                    credibility_score=0.9,
                    fetched_at=utc_now(),
                )
            )
        if with_claims:
            for claim_id, text in (
                ("c1", "One web address is reserved and cannot be registered."),
                ("c2", "The registry reserved the address itself."),
            ):
                session.add(
                    FactualClaim(
                        id=claim_id,
                        source_id=source_id if with_source else None,
                        topic_id=topic_id,
                        claim_text=text,
                        claim_type="GENERAL",
                        importance="KEY",
                        status="SUPPORTED",
                        confidence=0.9,
                        evidence_text=text,
                        created_at=utc_now(),
                    )
                )
    return topic_id


def a_script(engine, topic_id, *, scenes=None, story=None, status="APPROVED") -> str:
    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="The address nobody may buy",
                target_duration_seconds=20,
                voiceover_full_text=" ".join(
                    s["narration"] for s in (scenes if scenes is not None else GOOD_SCENES)
                ),
                scenes_json=scenes if scenes is not None else GOOD_SCENES,
                status=status,
                claim_ids_json=["c1", "c2"],
                unverified_claim_ids_json=[],
                story_json=story if story is not None else GOOD_STORY,
                created_at=utc_now(),
            )
        )
    return script_id


def a_passed_review(engine, script_id) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="PASS",
                checks_json={},
                retention_json={"at_3": 80, "at_end": 55},
                scores_json={},
                notes_json={},
                estimated_seconds=21.0,
                created_at=utc_now(),
            )
        )


SHOT_ANSWER = {
    "shots": [
        {
            "scene_index": index,
            "story_purpose": purpose,
            "subject": "A woman in her thirties, short dark hair, grey raincoat, at a laptop",
            "action": "leaning in slowly, typing the address and stopping mid-keystroke",
            "environment": "a small flat at night, rain on the window, one desk lamp",
            "camera": "medium close-up, slight low angle, 35mm character, slow push in",
            "lighting": "single warm practical from the desk lamp, cold blue window spill",
            "composition": "subject left of centre in a vertical frame, laptop glow leading",
            "motion": "hands slow to a stop, steam from a mug drifting across the light",
            "emotion": "quiet curiosity turning to hesitation",
            "background": "rain streaks and a dark street below, no people",
            "continuity": "same grey raincoat, same flat, same night, same palette",
            "ending_frame": "her hand resting on the keyboard, screen still lit",
            "audio_intent": "rain, a keyboard, narration dominates",
            "transition": "dissolve on the screen glow",
            "avoid": ["on-screen text", "daylight"],
        }
        for index, purpose in enumerate(
            ["HOOK", "SETUP", "DEVELOPMENT", "REVEAL", "ENDING"], start=1
        )
    ]
}

BIBLE_ANSWER = {
    "style": "premium cinematic realism",
    "realism": "strict photographic realism",
    "period": "present day",
    "world": "a rainy European city at night",
    "palette": "cold blue-grey environment, warm skin and lamp light",
    "lighting": "naturalistic, one motivated source per shot, high dynamic range",
    "camera_language": "controlled, slow, motivated movement only",
    "weather": "light rain throughout",
    "continuity_rules": [
        "the same woman, coat and flat in every shot",
        "night and rain across the whole film",
    ],
    "avoid": ["daylight", "crowds"],
}


def film_registry(studio):
    """A model that answers the bible and the shot pack, and nothing else."""

    def answer(prompt: str) -> str:
        # The shot brief mentions the visual bible, so the shot test comes first: the two
        # calls are told apart by what they ask to be returned, not by what they mention.
        if '"shots": [' in prompt:
            return json.dumps(SHOT_ANSWER)
        if "one look the whole film" in prompt:
            return json.dumps(BIBLE_ANSWER)
        return "{}"

    return registry_with(studio, answer)


# --------------------------------------------------------------------- 1-3: the idea


def test_1_an_idea_with_no_payoff_is_refused_and_kept_with_its_reason():
    """A topic that sounds interesting is not an idea. Without a payoff the studio does not
    know what the viewer leaves with, and a film nobody leaves with anything is not made."""
    no_payoff = {**GOOD_THESIS, "payoff": ""}
    reasons = idea_rejections(no_payoff, GOOD_SCORES)
    assert any("final" in reason.lower() for reason in reasons)

    weak_payoff = {**GOOD_SCORES, "payoff_strength": 0.2}
    assert any("payoff_strength" in reason for reason in idea_rejections(GOOD_THESIS, weak_payoff))
    # And the same thesis with an answer to every question passes.
    assert idea_rejections(GOOD_THESIS, GOOD_SCORES) == []


def test_2_an_idea_with_no_trusted_evidence_never_reaches_a_script(engine, studio):
    """Research first, then ideation. A topic with no SUPPORTED claim has nothing truthful to
    write from, and the writer refuses rather than filling the gap from memory."""
    from app.factual.agent_pipeline import NoVerifiedClaims, agent_write_script

    topic_id = a_topic(engine, with_claims=False, with_source=False)
    registry, _ = registry_with(studio, lambda prompt: "{}")
    with pytest.raises(NoVerifiedClaims):
        agent_write_script(engine, registry, topic_id, str(uuid4()))


def test_3_beautiful_visuals_alone_cannot_approve_a_weak_story():
    """The failure the Owner named: "premium" read as "expensive". A topic with everything to
    show and nothing to say loses to one with a real story, because the weights say so."""
    beautiful_and_empty = {
        **GOOD_SCORES,
        "visual_potential": 1.0,
        "production_feasibility": 1.0,
        "shareability": 1.0,
        "hook_potential": 0.3,
        "payoff_strength": 0.2,
        "story_potential": 0.2,
    }
    strong_story = {**GOOD_SCORES, "visual_potential": 0.3}
    assert composite(strong_story) > composite(beautiful_and_empty)
    # And it is not merely ranked lower: it is refused.
    assert idea_rejections(GOOD_THESIS, beautiful_and_empty)


# --------------------------------------------------------------------- 4-7: the story


def test_4_a_script_must_have_a_hook_a_progression_a_payoff_and_an_ending():
    checks = story_checks(
        title="The address nobody may buy",
        scenes=GOOD_SCENES,
        story=GOOD_STORY,
        target_seconds=20,
    )
    for name in (
        "has_hook",
        "hook_is_not_generic",
        "has_progression",
        "has_payoff",
        "has_ending",
        "ending_answers_the_hook",
    ):
        assert checks[name]["passed"], f"{name}: {checks[name]['reason']}"

    # A list of facts joined by "and then" is not a story, and neither is a generic opening.
    flat = [
        {**GOOD_SCENES[0], "narration": "Did you know there is a reserved web address?"},
        {**GOOD_SCENES[1], "narration": "And then the registry made a list of them."},
        {**GOOD_SCENES[2], "purpose": "DEVELOPMENT"},
    ]
    weak = story_checks(title="Addresses", scenes=flat, story=GOOD_STORY, target_seconds=15)
    assert not weak["hook_is_not_generic"]["passed"]
    assert not weak["has_progression"]["passed"]
    assert not weak["has_payoff"]["passed"]


def test_5_the_closing_question_must_belong_to_this_story():
    """A call to action is part of the storytelling, not an advertisement pasted on the end."""
    generic = {**GOOD_STORY, "cta": "Like and subscribe for more videos!"}
    checks = story_checks(
        title="The address nobody may buy", scenes=GOOD_SCENES, story=generic, target_seconds=15
    )
    assert not checks["cta_belongs_to_the_story"]["passed"]

    unrelated = {**GOOD_STORY, "cta": "Which volcano would you visit?"}
    checks = story_checks(
        title="The address nobody may buy", scenes=GOOD_SCENES, story=unrelated, target_seconds=15
    )
    assert not checks["cta_belongs_to_the_story"]["passed"]

    kept = story_checks(
        title="The address nobody may buy", scenes=GOOD_SCENES, story=GOOD_STORY, target_seconds=15
    )
    assert kept["cta_belongs_to_the_story"]["passed"]
    assert kept["cta_kind_is_stated"]["passed"]


def test_6_the_narration_has_to_fit_the_length_it_claims():
    """Thirty seconds of film may not carry sixty seconds of words. The rate is the studio's
    own measured speaking rate, and the check is arithmetic, not opinion."""
    assert 18 <= expected_seconds(GOOD_SCENES) <= 24

    long_scenes = [{**scene, "narration": scene["narration"] * 6} for scene in GOOD_SCENES]
    checks = story_checks(
        title="The address nobody may buy",
        scenes=long_scenes,
        story=GOOD_STORY,
        target_seconds=20,
    )
    assert not checks["duration_is_realistic"]["passed"]
    assert "20s" in checks["duration_is_realistic"]["reason"]


def test_7_every_scene_declares_why_it_is_in_the_film(engine, studio):
    """A shot that exists because it looks good contributes nothing. The purpose travels from
    the script to the storyboard, so it can be read on the row that gets filmed."""
    nameless = [{**scene, "purpose": ""} for scene in GOOD_SCENES]
    checks = story_checks(
        title="The address nobody may buy", scenes=nameless, story=GOOD_STORY, target_seconds=15
    )
    assert not checks["every_scene_has_a_purpose"]["passed"]

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    with Session(engine) as session:
        purposes = [
            scene.story_purpose
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        ]
    assert purposes[0] == "HOOK" and purposes[-1] == "ENDING"
    assert all(purposes)


# --------------------------------------------------------------------- 8-15: the prompt


def test_8_the_prompt_agent_only_takes_a_story_that_passed(engine, studio):
    """The gate before the money. Describing shots is the last step before generation, so a
    film whose story nobody judged does not get described."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)

    with pytest.raises(PromptError) as refused:
        write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    assert "recenzia de poveste" in str(refused.value)

    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="REVISE",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={"notes": ["hook-ul nu ține"]},
                estimated_seconds=21.0,
                created_at=utc_now(),
            )
        )
    with pytest.raises(PromptError) as still:
        write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    assert "REVISE" in str(still.value)

    a_passed_review(engine, script_id)
    assert write_shot_prompts(engine, registry, board["id"], str(uuid4()))["shots"]


def test_9_the_prompt_agent_may_not_invent_a_fact(engine, studio):
    """A number in a picture looks documented. One the claims never stated is a fabrication
    the studio would publish as fact, so it is cut out of the prompt before it is sent."""
    assert new_numbers("340 soldiers arrive in 1912", "the year was 1912") == ["340"]
    assert new_numbers("a 35mm lens at 24fps in 9:16", "nothing numeric here") == []

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")

    def answer(prompt: str) -> str:
        if '"shots": [' not in prompt:
            return json.dumps(BIBLE_ANSWER)
        # Every scene is answered (a plan with missing shots is a lost plan, not a template
        # fill); the first one invents its numbers.
        invented = {
            "shots": [
                {
                    **SHOT_ANSWER["shots"][0],
                    "scene_index": 1,
                    "action": "typing while 4711 other users watch from 1863 terminals",
                },
                *SHOT_ANSWER["shots"][1:],
            ]
        }
        return json.dumps(invented)

    registry, _ = registry_with(studio, answer)
    result = write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    assert any("cifre inventate" in note for note in result["repaired"])
    with Session(engine) as session:
        first = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board["id"], StoryboardScene.scene_index == 1
            )
        )
    assert "4711" not in first.visual_prompt and "1863" not in first.visual_prompt


def test_10_a_shot_prompt_is_detailed_where_detail_changes_the_picture(engine, studio):
    """Not "a man walking through ancient Rome". Subject, action, environment, camera, light,
    composition and motion, in one prompt a model can act on — and not a word longer than it
    has to be, because a thousand meaningless words bury the fields that matter."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))

    with Session(engine) as session:
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board["id"], StoryboardScene.scene_index == 1
            )
        )
        package = dict(scene.prompt_json or {})
        prompt = scene.visual_prompt
    for field in (
        "subject",
        "action",
        "environment",
        "camera",
        "lighting",
        "composition",
        "motion",
    ):
        assert str(package.get(field) or "").strip(), f"{field} is empty"
    assert package["story_purpose"] == "HOOK"
    assert package["audio_intent"] and package["transition"] and package["avoid"]
    assert 200 < len(prompt) <= 1000, "specific, and not padded"
    # Since the Nepal film (PROMPT_COMPILER, 2026-09-27) the still prompt is prose: no
    # template labels and no "Avoid:" list, and the camera move is its own motion prompt.
    for label in ("Camera:", "Lighting:", "Avoid:", "Motion:"):
        assert label not in prompt
    assert package["still_prompt"] == prompt and package["motion_prompt"]
    assert package["camera_move"] in package["motion_prompt"].lower()


def test_11_a_character_looks_the_same_in_every_shot(engine, studio):
    """A film is one film. The bible states what must not change, the shot package repeats the
    character, and a locked character's own description travels into the prompt."""
    topic_id = a_topic(engine)
    character_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            CharacterBible(
                id=character_id,
                canonical_name="The typist",
                palette_json={},
                face_hair_desc="short dark hair, freckles, mid-thirties",
                outfit_desc="a grey raincoat over a black jumper",
                props_desc="a chipped enamel mug",
                role_symbols="none",
                voice_profile_json={},
                personality_json={},
                speech_style_json={},
                expressions_json={},
                behavior_json={},
                reference_assets_json={},
                voice_binding_json={},
                identity_locks_json={"visual": True},
                approved_fallbacks_json=[],
                consistency_status="CONSISTENT",
                forbidden_deviations="never change the coat",
                version=1,
                created_at=utc_now(),
            )
        )
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    with Session(engine) as session, session.begin():
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board["id"])
        ):
            scene.character_ids_json = [character_id]

    registry, _ = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    with Session(engine) as session:
        prompts = [
            scene.visual_prompt
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        ]
        bible = dict(session.get(Storyboard, board["id"]).visual_bible_json or {})
    # The character is described, not named: a name means nothing to an image model and can
    # be drawn as writing (PROMPT_COMPILER, 2026-09-27).
    assert all("short dark hair" in prompt for prompt in prompts)
    assert all("grey raincoat" in prompt for prompt in prompts)
    assert any("coat" in rule for rule in bible["continuity_rules"])


def test_12_the_world_holds_from_shot_to_shot(engine, studio):
    """Scene one in evening rain does not become a sunny afternoon in scene two. The bible
    carries the world, and each shot inherits the last shot's final frame as its continuity."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)
    result = write_shot_prompts(engine, registry, board["id"], str(uuid4()))

    assert "rain" in result["bible"]["weather"]
    with Session(engine) as session:
        scenes = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        )
    for scene in scenes:
        package = dict(scene.prompt_json or {})
        assert package["continuity"], f"scene {scene.scene_index} carries no continuity"
        assert "night" in scene.visual_prompt or "rain" in scene.visual_prompt


def test_13_and_14_light_and_camera_are_decided_not_left_to_the_model(engine, studio):
    """A shot with no lighting is a shot whose lighting the model invents — which is how a
    night scene arrives sunlit. Same for the camera: the frame is a decision."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")

    def answer(prompt: str) -> str:
        if '"shots": [' not in prompt:
            return json.dumps(BIBLE_ANSWER)
        # A model that leaves the light and the camera out: the studio fills them rather
        # than sending a prompt that decides nothing.
        bare = {
            "shots": [
                {"scene_index": index, "story_purpose": purpose, "subject": "a laptop screen"}
                for index, purpose in enumerate(
                    ["HOOK", "SETUP", "DEVELOPMENT", "REVEAL", "ENDING"], start=1
                )
            ]
        }
        return json.dumps(bare)

    registry, _ = registry_with(studio, answer)
    result = write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    # Nothing is left to the model: what the shot did not say, the film's own bible does.
    assert result["bible"]["lighting"]
    with Session(engine) as session:
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board["id"])
        ):
            package = dict(scene.prompt_json or {})
            assert package["lighting"].strip(), "a shot with no light has its light invented"
            assert package["camera"].strip(), "the frame is a decision, not a default"
            assert package["composition"].strip()
            assert "vertical" in package["composition"] or "9:16" in package["composition"]
            assert package["lighting"] == BIBLE_ANSWER["lighting"], "inherited from the bible"


def test_15_the_picture_serves_the_narration_it_is_under(engine, studio):
    """The prompt agent may not make the film more spectacular than the story. What it writes
    is stored beside the narration it belongs to, so the two can be read against each other."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))

    with Session(engine) as session:
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board["id"])
        ):
            package = dict(scene.prompt_json or {})
            assert package["narration"] == scene.voiceover_segment
            assert package["seconds"] == pytest.approx(scene.duration_seconds)
    # And the brief the agent was given says so in as many words: the approved story is
    # not the prompt agent's to change.
    registry_two, model = film_registry(studio)
    write_shot_prompts(engine, registry_two, board["id"], str(uuid4()))
    assert any("must not change" in prompt for prompt in model.prompts)
    assert any("more spectacular than the story" in prompt for prompt in model.prompts)


# --------------------------------------------------------------------- 16-19: the loop


def test_16_and_17_the_package_is_the_same_in_both_environments(engine, studio):
    """ "TEST environment, therefore a basic prompt" — no. A strong prompt can be tested
    cheaply: the environment decides which model is bought, not how well the shot is
    described. The prompt agent is never told which environment it is in."""
    import inspect

    from app.media import prompt_agent
    from app.schemas import EnvironmentCommand
    from app.services import change_environment, studio_environment

    for name in ("write_shot_prompts", "build_visual_bible", "compose_prompt"):
        signature = inspect.signature(getattr(prompt_agent, name))
        assert "environment" not in signature.parameters, f"{name} must not know the environment"

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)

    assert studio_environment(engine) == "TEST"
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    with Session(engine) as session:
        in_test = [
            scene.visual_prompt
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        ]

    with Session(engine) as session:
        version = session.get(OwnerPolicy, 1).version
    change_environment(
        engine,
        EnvironmentCommand(
            schema_version=1,
            command_id=str(uuid4()),
            expected_version=version,
            environment="PRODUCTION",
        ),
    )
    assert studio_environment(engine) == "PRODUCTION"
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    with Session(engine) as session:
        in_production = [
            scene.visual_prompt
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board["id"])
                .order_by(StoryboardScene.scene_index)
            )
        ]
    assert in_test == in_production, "the same story deserves the same description"

    # And the model routing is still the existing one: production ranks, test takes cheapest.
    from app.media.production_policy import PRODUCTION_READY, choose_model

    assert PRODUCTION_READY == ("CANDIDATE", "PRODUCTION", "PREFERRED")
    assert "environment" in inspect.signature(choose_model).parameters


def test_18_the_sources_stay_attached_to_the_finished_film(engine, studio):
    """A factual film that cannot show where its facts came from is not a factual film. The
    production package carries the pages and the claims, through the storyboard."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    registry, _ = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))

    package = production_package(engine, board["id"])
    assert package["trusted_sources"][0]["url"].startswith("https://www.iana.org")
    assert {claim["status"] for claim in package["fact_check"]} == {"SUPPORTED"}
    assert package["why_this_video_should_exist"]["payoff"]
    assert package["core_message"] and package["cta"]["kind"] == "COMMENT"
    assert len(package["shot_list"]) == len(GOOD_SCENES)
    assert package["approval"]["story_review"] == "PASS"
    assert package["master_visual_bible"]["continuity_rules"]
    assert package["negative_constraints"]
    with Session(engine) as session:
        scene_claims = [
            scene.claim_ids_json
            for scene in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == board["id"])
            )
        ]
    assert all(ids for ids in scene_claims), "every filmed scene keeps its citations"


def test_19_a_failed_prompt_teaches_the_next_one(engine, studio):
    """What the Director says about the pictures is a fact about how the vendor's model reads
    instructions. It is kept, and the next film's prompt agent is given it."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")

    with Session(engine) as session, session.begin():
        record_prompt_lesson(
            session, "asking for a slow push in produced a static shot; say 'dolly in' instead"
        )
    with Session(engine) as session:
        assert any("dolly in" in lesson for lesson in prompt_lessons(session))

    registry, model = film_registry(studio)
    write_shot_prompts(engine, registry, board["id"], str(uuid4()))
    assert any("dolly in" in prompt for prompt in model.prompts), (
        "the lesson has to reach the agent that writes the next prompt"
    )


# --------------------------------------------------------------------- 20-21: what existed


def test_20_the_directors_own_approval_still_decides(engine, studio, tmp_path):
    """The editorial review of the finished film is untouched: it still reads the script, the
    claims and the frames, and a REJECT still closes the storyboard."""
    from app.agents.editorial import editorial_review, gather_facts
    from app.media.models import MediaAsset, QualityControlReport, VideoRenderJob

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    asset_id = str(uuid4())
    film = tmp_path / "film.mp4"
    film.write_bytes(b"\x00" * 64)
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(film),
                file_size_bytes=64,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=15.0,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="a" * 64,
                created_at=utc_now(),
            )
        )
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board["id"],
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json={},
                started_at=utc_now(),
            )
        )
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=asset_id,
                status="PASSED",
                score=1.0,
                checks_json={"technical_qc": {"passed": True}},
                failure_reasons_json=[],
                verified_at=utc_now(),
            )
        )

    with Session(engine) as session:
        facts = gather_facts(session, asset_id, "en")
    assert facts["title"] and facts["scenes"]

    registry, _ = registry_with(
        studio,
        lambda prompt: json.dumps(
            {
                "verdict": "REJECT",
                "story": "Nothing a viewer learns.",
                "reasons": ["the payoff repeats the hook"],
                "notes_for": {"VideoEditor": "the flat is lit differently in every shot"},
                # Only her general rule is a lesson, never her note on this film (review of
                # 68fa0b4, 2026-10-12).
                "lesson": "A room lit differently in every shot reads as many rooms; name one "
                "light for it and keep it.",
            }
        ),
    )
    verdict = editorial_review(engine, registry, asset_id, str(uuid4()), "en")
    assert verdict["verdict"] == "REJECT"
    with Session(engine) as session:
        assert session.get(Storyboard, board["id"]).status == "REJECTED"
        # And her lesson about the pictures became a lesson for the next prompt.
        given = prompt_lessons(session)
        assert any("lit differently" in lesson for lesson in given)
        assert not any("the flat is lit" in lesson for lesson in given)


def test_21_the_page_and_the_backend_agree_on_what_a_film_is(engine, client, headers, studio):
    """What the interface reads is what the studio stored: the story review with its verdict,
    the production package with its shots, and the environment the render will use."""
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    registry, _ = film_registry(studio)
    client.app.app.state.registry = registry

    # No review yet: the page is told so, and the render refuses.
    read = client.get(f"/api/v1/factual/scripts/{script_id}/story-review", headers=headers).json()
    assert read["verdict"] == "NONE"

    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    refused = client.post(f"/api/v1/media/render/{board['id']}", headers=headers)
    assert refused.status_code == 422 and "recenzia de poveste" in refused.json()["detail"]

    reviewed = client.post(
        f"/api/v1/factual/scripts/{script_id}/story-review", headers=headers
    ).json()
    assert reviewed["verdict"] in ("PASS", "REVISE", "REJECT")
    assert reviewed["checks"]["has_hook"]["passed"] is True
    assert reviewed["estimated_seconds"] > 0

    read_again = client.get(
        f"/api/v1/factual/scripts/{script_id}/story-review", headers=headers
    ).json()
    assert read_again["verdict"] == reviewed["verdict"]

    a_passed_review(engine, script_id)
    written = client.post(f"/api/v1/media/storyboards/{board['id']}/prompts", headers=headers)
    assert written.status_code == 200 and written.json()["shots"]
    package = client.get(
        f"/api/v1/media/storyboards/{board['id']}/production-package", headers=headers
    ).json()
    assert package["approval"]["story_review"] == "PASS"
    assert package["expected_duration_seconds"] > 0
    state = client.get("/api/v1/snapshot", headers=headers).json()
    assert state["policy"]["environment"] in ("TEST", "PRODUCTION")


def test_a_prompt_with_nothing_to_inherit_still_says_something():
    """A film with no bible and a bare package still produces a usable instruction rather
    than an empty string sent to a model that charges by the second."""
    text = compose_prompt({"subject": "a padlock", "action": "closing", "avoid": ["text"]}, {})
    assert "padlock" in text and "Avoid: text." in text


# --------------------------------------------------------------------------------------------
# How long is a short?
#
# Found live on 2026-09-12: the writer was told "30 seconds ≈ 78 words" and, in the same brief,
# offered up to twelve scenes across eight story purposes with a five-line beat table. Seventy-
# eight words over seven scenes is eleven words a scene, which nobody writes — he wrote twenty-
# one, twice, and the duration check refused both drafts (57.5s, then 41.2s against a 39s
# ceiling). The brief asked for a film its own budget could not pay for. These tests hold the
# arithmetic in one place, so the instruction and the refusal cannot disagree.
# --------------------------------------------------------------------------------------------


def test_the_budget_states_the_window_the_check_enforces():
    """The brief's numbers and the check's numbers must be the same numbers.

    They were not, twice over. The brief priced the narration in words alone while the check
    measures the words plus the breath between scenes, so it named a ceiling five words looser
    than the one applied — and the writer, obeying the brief, was refused for it.
    """
    from app.factual.editorial import narration_budget

    budget = narration_budget(30)

    def measured(words: int, scenes: int):
        each = " ".join(["word"] * (words // scenes))
        return story_checks(
            title="t",
            scenes=[{"narration": each, "purpose": "HOOK"} for _ in range(scenes)],
            story={},
            target_seconds=30,
        )["duration_is_realistic"]["passed"]

    # Written to the stated target, with the stated number of scenes: accepted.
    assert measured(budget["total_words"], budget["scenes"])
    # Written to the stated ceiling: still accepted, because that is what the brief promised.
    assert measured(budget["max_words"] - budget["scenes"], budget["scenes"])
    # Far past it: refused. The ceiling is a real ceiling, only a generous one.
    assert not measured(budget["max_words"] * 2, budget["scenes"])


def test_the_budget_asks_for_scenes_it_can_pay_for():
    from app.factual.editorial import MAX_STORY_SCENES, narration_budget

    budget = narration_budget(30)
    # Five scenes at twelve to nineteen words each is a brief a writer can actually satisfy;
    # the old one offered twelve scenes for the same 78 words.
    assert budget["scenes"] == 5
    assert budget["words_per_scene_low"] >= 10
    assert budget["scenes"] * budget["words_per_scene_high"] <= budget["max_words"]
    assert budget["scenes"] * budget["words_per_scene_low"] >= budget["min_words"] - 1
    # And the cap is never exceeded, however long the film is asked to be.
    assert narration_budget(600)["scenes"] == MAX_STORY_SCENES
    assert narration_budget(0)["scenes"] == 0


def test_a_longer_film_scales_instead_of_promising_seconds_it_lacks():
    from app.factual.editorial import narration_budget

    thirty, forty_five = narration_budget(30), narration_budget(45)
    assert forty_five["total_words"] > thirty["total_words"]
    assert forty_five["scenes"] > thirty["scenes"]
    # The beat table always ends where the film ends. A 45-second brief that still said
    # "26-30s ENDING" would be telling the writer to finish fifteen seconds early.
    assert thirty["beats"][-1][2] == 30.0
    assert forty_five["beats"][-1][2] == 45.0
    assert thirty["beats"][0][1] == 0.0


def test_the_writers_brief_carries_the_budgets_own_numbers():
    from app.factual.agent_pipeline import _write_instructions
    from app.factual.editorial import narration_budget

    budget = narration_budget(30)
    brief = _write_instructions(30)
    # Every number the writer is given comes from the budget, not from prose written once and
    # left behind when a constant changed.
    assert f"{budget['total_words']} de cuvinte" in brief
    assert f"{budget['scenes']} scene" in brief
    assert f"{budget['words_per_scene_low']}-{budget['words_per_scene_high']} cuvinte" in brief
    assert str(budget["max_words"]) in brief
    # The brief says what is measured, because the writer had been filling duration_seconds
    # with numbers that summed to the target while writing twice the narration.
    assert "duration_seconds" in brief
    # It no longer offers more scenes than the budget affords.
    assert "maximum 12 scene" not in brief


def test_the_refusal_tells_the_writer_where_the_line_is():
    checks = story_checks(
        title="t",
        scenes=[{"narration": " ".join(["word"] * 300), "purpose": "HOOK"}],
        story={},
        target_seconds=30,
    )
    reason = checks["duration_is_realistic"]["reason"]
    # "Too long" is not a brief. The length measured, the target, and the band that would have
    # been accepted are all in the sentence the writer receives on the rewrite. The length is
    # the film the montage cuts from the words, breaths included (`film_length`).
    measured = checks["duration_is_realistic"]["estimated_seconds"]
    assert measured > 100.0 and f"{measured:.1f}s" in reason
    assert "ținta de 30s" in reason
    assert "15-45s" in reason


def test_a_few_words_over_is_not_a_refusal():
    """The Owner's rule: a film a little over its target is a film. The 41-second draft that
    was sent back twice against a 39-second ceiling is the case this exists for."""
    scenes = [
        {"narration": " ".join(["word"] * n), "purpose": "HOOK"} for n in (15, 25, 24, 23, 16)
    ]
    assert story_checks(title="t", scenes=scenes, story={}, target_seconds=30)[
        "duration_is_realistic"
    ]["passed"]

    # And the failure the check was written for is still a failure: sixty seconds of narration
    # inside a thirty-second film ends the film before its words.
    flood = [{"narration": " ".join(["word"] * 40), "purpose": "HOOK"} for _ in range(5)]
    assert not story_checks(title="t", scenes=flood, story={}, target_seconds=30)[
        "duration_is_realistic"
    ]["passed"]


def test_a_short_may_never_outgrow_the_format(engine):
    """However long the target, the outer wall is the format itself."""
    from app.factual.editorial import MAX_SHORT_SECONDS, length_ceiling_seconds, narration_budget
    from app.media.film_length import Timing

    assert narration_budget(45)["max_seconds"] == 67.5  # under the wall: its own tolerance
    # The wall itself: since «pauza vocii» the film's estimate carries its own margin on its
    # words (2026-10-16); with the pause rules off, the wall less the legacy margin.
    assert length_ceiling_seconds() == MAX_SHORT_SECONDS
    assert length_ceiling_seconds(Timing()) < MAX_SHORT_SECONDS
    assert narration_budget(200)["max_seconds"] == length_ceiling_seconds()
    assert narration_budget(300)["max_seconds"] == length_ceiling_seconds()


# --------------------------------------------------------------------------------------------
# Who approves a script, and what happens to one that was sent back.
#
# Found live on 2026-09-12, in one chain: the writer overshot the duration, the review sent the
# draft back twice, and then the studio wedged. The stage skipped the topic because a draft
# existed, the topic still counted as in production, and nothing else could be selected past
# it. The revision budget that should have escalated never fired either, because it counted
# reviews of one draft row while every rewrite wrote a new row. And a story the Director had
# passed still waited for the Owner to approve it by hand — his inbox doing her job.
# --------------------------------------------------------------------------------------------


def a_sent_back_review(engine, script_id, verdict="REVISE", notes=None) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict=verdict,
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={"notes": notes if notes is not None else ["Narațiunea durează 57.5s"]},
                estimated_seconds=57.5,
                created_at=utc_now(),
            )
        )


def test_a_topic_with_no_script_owes_one(engine, studio):
    from app.runbook.stages import script_work

    topic_id = a_topic(engine)
    with Session(engine) as session:
        assert script_work(session, [topic_id]) == [(topic_id, [])]


def test_a_sent_back_draft_owes_a_rewrite_and_carries_its_notes(engine, studio):
    from app.runbook.stages import script_work

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, status="VERIFIED_PASS")
    a_sent_back_review(engine, script_id, notes=["Narațiunea durează 57.5s", "hook slab"])

    with Session(engine) as session:
        owed = script_work(session, [topic_id])
    # Still owed work, and the rewrite is briefed with what the reading said. This is the case
    # that used to be skipped, leaving the studio with nothing it was able to do.
    assert owed == [(topic_id, ["Narațiunea durează 57.5s", "hook slab"])]


def test_a_refused_story_is_not_retried_and_stops_holding_the_studio_up(engine, studio):
    from app.runbook.stages import script_work

    topic_id = a_topic(engine)
    a_sent_back_review(engine, a_script(engine, topic_id, status="VERIFIED_PASS"), verdict="REJECT")
    with Session(engine) as session:
        # The revision budget is spent and the letters have gone to the departments. A fourth
        # draft against the same evidence is what the budget exists to prevent.
        assert script_work(session, [topic_id]) == []


def test_a_draft_she_passed_is_not_rewritten(engine, studio):
    from app.runbook.stages import script_work

    topic_id = a_topic(engine)
    a_passed_review(engine, a_script(engine, topic_id, status="VERIFIED_PASS"))
    with Session(engine) as session:
        assert script_work(session, [topic_id]) == []


def test_a_storyboarded_script_is_past_the_page(engine, studio):
    from app.runbook.stages import script_work

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id)
    a_passed_review(engine, script_id)
    generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4()))
    with Session(engine) as session:
        assert script_work(session, [topic_id]) == []


def test_the_revision_budget_counts_the_story_not_the_row(engine, studio):
    from app.factual.story_review import MAX_REVISIONS, review_story

    topic_id = a_topic(engine)
    # Two rewrites, each a new draft row, each sent back once. Counted per row this was always
    # "the first revision of this draft", so the budget never ran out and the topic never
    # escalated to anyone.
    for _ in range(MAX_REVISIONS):
        a_sent_back_review(engine, a_script(engine, topic_id, status="VERIFIED_PASS"))

    long_scenes = [{**scene, "narration": scene["narration"] * 6} for scene in GOOD_SCENES]
    third = a_script(engine, topic_id, scenes=long_scenes, status="VERIFIED_PASS")
    verdict = review_story(engine, None, third, str(uuid4()), target_seconds=20)
    assert verdict["verdict"] == "REJECT"
    assert any("nu au îmbunătățit nimic" in note for note in verdict["notes"])


def test_the_director_approves_what_she_passed(engine, studio):
    from app.agents.memory import agent_for_role
    from app.models import DomainEvent
    from app.runbook.stages import _director_approves

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, status="VERIFIED_PASS")
    approved = _director_approves(engine, script_id, {"verdict": "PASS", "failed": []})

    assert approved == script_id
    with Session(engine) as session:
        assert session.get(ScriptDraft, script_id).status == "APPROVED"
        director = agent_for_role(session, "Director")
        event = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "factual.script_approved")
        ).first()
        # The record says whose decision it was: "approved" with nobody behind it is not a
        # decision anyone can question later.
        assert event.payload["approved_by"] == (director.id if director else None)
        assert "Recenzia Directorului: trecută" in event.payload["reason"]


def test_a_story_she_sent_back_is_not_approved(engine, studio):
    from app.runbook.stages import _director_approves

    script_id = a_script(engine, a_topic(engine), status="VERIFIED_PASS")
    assert _director_approves(engine, script_id, {"verdict": "REVISE", "failed": ["x"]}) is None
    with Session(engine) as session:
        assert session.get(ScriptDraft, script_id).status != "APPROVED"


def test_a_refused_story_stops_holding_the_studio_up(engine, studio):
    """The last link: `script_work` will never rewrite a REJECTED story, so if the topic still
    counted as in production nothing could be rewritten and nothing new could be chosen — a
    corner one step further along than the one before it."""
    from app.runbook.stages import topics_in_production

    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, status="VERIFIED_PASS")
    a_sent_back_review(engine, script_id, verdict="REJECT")

    with Session(engine) as session:
        live, stalled = topics_in_production(session)
    assert live == []  # nothing is owed on it
    assert stalled == [topic_id]  # and the Owner is told it is stuck, not that it is working


def test_a_story_still_being_written_is_in_production(engine, studio):
    from app.runbook.stages import topics_in_production

    topic_id = a_topic(engine)
    a_sent_back_review(engine, a_script(engine, topic_id, status="VERIFIED_PASS"))
    with Session(engine) as session:
        live, stalled = topics_in_production(session)
    # A rewrite is owed, and the studio is the one who owes it.
    assert live == [topic_id] and stalled == []


def test_a_revision_shows_the_writer_the_draft_he_is_revising(engine, studio):
    """Found live on 2026-09-12: draft two passed every check at 39.5s and the Director asked
    for surgical changes — cut one line in scene 2, tighten scene 5 to end on the mirror.
    Draft three came back at 46.8s with no ending at all, because the rewrite was told to
    "write the story again from the beginning" and never saw the draft it was revising. Notes
    about scene 5 cannot be obeyed by a writer who has to reinvent scene 5 first."""
    import json as _json

    from app.factual.agent_pipeline import agent_write_script, previous_draft

    topic_id = a_topic(engine)
    a_script(engine, topic_id, status="VERIFIED_PASS")

    with Session(engine) as session:
        earlier = previous_draft(session, topic_id)
    assert earlier is not None
    assert earlier["scenes"][0]["narration"].startswith("There is one web address")

    seen: dict = {}

    def answer(prompt):
        seen["prompt"] = prompt
        return _json.dumps(
            {
                "title": "The address nobody may buy",
                "core_message": GOOD_STORY["core_message"],
                "takeaway": GOOD_STORY["takeaway"],
                "hook": GOOD_STORY["hook"],
                "ending": GOOD_STORY["ending"],
                "cta": GOOD_STORY["cta"],
                "cta_kind": "COMMENT",
                "scenes": [
                    {
                        "narration": scene["narration"],
                        "visual": scene["visual_description"],
                        "purpose": scene["purpose"],
                        "claim_ids": ["c1"],
                    }
                    for scene in GOOD_SCENES
                ],
            }
        )

    registry, _ = registry_with(studio, answer)
    agent_write_script(
        engine,
        registry,
        topic_id,
        str(uuid4()),
        target_duration_seconds=30,
        notes=["Taie replica a doua din scena 2.", "Strânge scena 5 ca să se încheie pe oglindă."],
    )

    prompt = seen["prompt"]
    # The draft is in front of him, the notes name what to change, and he is told to keep the
    # rest rather than start over.
    assert "VERSIUNEA ANTERIOARĂ A FOST TRIMISĂ ÎNAPOI" in prompt
    assert "There is one web address nobody on earth is allowed to buy." in prompt
    assert "Taie replica a doua din scena 2." in prompt
    assert "REVIZUIEȘTE scenariul de mai sus" in prompt
    assert "Nu reinventa povestea de la zero" in prompt


def test_a_first_draft_is_not_handed_a_previous_one(engine, studio):
    from app.factual.agent_pipeline import previous_draft

    with Session(engine) as session:
        assert previous_draft(session, a_topic(engine)) is None


def test_a_film_that_closes_passes_whatever_its_last_scene_is_called():
    """Found live on 2026-09-12: a draft was sent back twice for having no ending while ending
    on "after eleven years of defending the planet, it became a streak of fire in the sky",
    with a CTA of its own. The writer had spent all five scenes the brief allows on HOOK,
    SETUP, DEVELOPMENT, EVIDENCE and PAYOFF and delivered the close inside the last one. The
    check was reading the label, not the film."""
    scenes = [
        {"purpose": "HOOK", "narration": "A telescope watched for asteroids that could hit us."},
        {"purpose": "SETUP", "narration": "It flew for a decade, looking where nobody looked."},
        {
            "purpose": "DEVELOPMENT",
            "narration": "Because infrared sees rock that visible light misses.",
        },
        {"purpose": "EVIDENCE", "narration": "So it found the ones sunlight had been hiding."},
        {
            "purpose": "PAYOFF",
            "narration": (
                "Until, after ten years defending the planet, it became a streak of fire "
                "in the sky."
            ),
        },
    ]
    story = {
        "hook": "A telescope watched for asteroids that could hit us.",
        "ending": (
            "After eleven years of defending the planet, it became a streak of fire in the sky."
        ),
        "cta": "Follow to see what replaces this asteroid watch.",
        "cta_kind": "FOLLOW",
        "core_message": "The telescope that hunted asteroids burned up defending us.",
    }
    checks = story_checks(
        title="The asteroid hunter", scenes=scenes, story=story, target_seconds=30
    )
    assert checks["has_ending"]["passed"]

    # A film that simply stops still fails: no ENDING label, no declared ending, nothing in the
    # last scene that closes anything.
    open_ended = story_checks(
        title="The asteroid hunter",
        scenes=scenes,
        story={**story, "ending": ""},
        target_seconds=30,
    )
    assert not open_ended["has_ending"]["passed"]

    # And a declared ending nobody says out loud does not count either.
    unspoken = story_checks(
        title="The asteroid hunter",
        scenes=scenes,
        story={**story, "ending": "Yet the budget committee never met again."},
        target_seconds=30,
    )
    assert not unspoken["has_ending"]["passed"]


def test_the_brief_tells_the_writer_the_last_scene_closes_the_film():
    from app.factual.agent_pipeline import _write_instructions

    brief = _write_instructions(30)
    assert "ULTIMA scenă închide filmul" in brief
    assert "etichetează ENDING sau CTA" in brief


def test_the_writers_room_stays_open_until_the_story_passes(engine, studio):
    """The Owner's rule: the day does not close after two attempts.

    It used to write exactly two drafts and stop, so a story one note away from passing waited
    until tomorrow and the day ended with nothing made. Text is the cheapest thing the studio
    produces; the conversation happens now, and the film reaches the camera the same day.
    """
    from app.factual.story_review import MAX_REVISIONS
    from app.runbook.stages import MAX_SCRIPT_EXCHANGES, _script_and_storyboard

    # The instruction, as a guard: these must stay a real conversation, not a pair of tries.
    assert MAX_REVISIONS >= 10
    assert MAX_SCRIPT_EXCHANGES >= 10

    topic_id = a_topic(engine)
    written = {"count": 0}

    def script_json(*, long: bool):
        scenes = [
            {
                "narration": scene["narration"] * (4 if long else 1),
                "visual": scene["visual_description"],
                "purpose": scene["purpose"],
                "claim_ids": scene["claim_ids"],
            }
            for scene in GOOD_SCENES
        ]
        return json.dumps(
            {
                "title": "The address nobody may buy",
                "core_message": GOOD_STORY["core_message"],
                "takeaway": GOOD_STORY["takeaway"],
                "hook": GOOD_STORY["hook"],
                "ending": GOOD_STORY["ending"],
                "cta": GOOD_STORY["cta"],
                "cta_kind": "COMMENT",
                "scenes": scenes,
            }
        )

    def answer(prompt):
        if "You are the Director" in prompt:
            return json.dumps(
                {
                    "verdict": "PASS",
                    "hook_strength": 8,
                    "clarity": 8,
                    "payoff": 8,
                    "cta_fit": 8,
                    "retention": {"at_3": 80, "at_end": 55},
                    "notes": [],
                }
            )
        written["count"] += 1
        # Four drafts too long for the band, then one that fits — six exchanges would once
        # have been five more than the studio was willing to have.
        return script_json(long=written["count"] <= 4)

    registry, _ = registry_with(studio, answer)
    outcome = _script_and_storyboard(engine, registry, "en", 20)

    # Five drafts in five exchanges: it kept working instead of stopping at two. (The writer
    # may also re-ask its own model within one draft, so the model-call count is higher than
    # the number of drafts; what matters is how many drafts the stage was willing to work.)
    assert written["count"] >= 5
    assert "5 scenarii scrise în 5 schimburi" in outcome["reason"]
    assert "1 aprobat de Director" in outcome["reason"]
    with Session(engine) as session:
        approved = session.scalars(
            select(ScriptDraft).where(
                ScriptDraft.topic_id == topic_id, ScriptDraft.status == "APPROVED"
            )
        ).all()
        # One story, approved by her, and the storyboard made from it in the same run.
        assert len(approved) == 1
        assert session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == approved[0].id)
        ).first()


def test_the_director_sees_the_conversation_she_is_in(engine, studio):
    """Found live on 2026-09-12: nine drafts of one story, every computed check passing from
    the second on, and nine REVISEs — because she was asked "what is wrong with this" nine
    times in a vacuum, and there is always something. A reviewer who cannot see the
    conversation cannot finish it."""
    from app.factual.story_review import review_story

    topic_id = a_topic(engine)
    first = a_script(engine, topic_id, status="VERIFIED_PASS")
    seen: list[str] = []

    def answer(prompt):
        seen.append(prompt)
        return json.dumps(
            {
                "verdict": "REVISE",
                "hook_strength": 7,
                "clarity": 7,
                "payoff": 6,
                "cta_fit": 5,
                "retention": {"at_3": 70, "at_end": 40},
                "notes": ["Strânge scena 5.", "CTA-ul e generic."],
            }
        )

    registry, _ = registry_with(studio, answer)
    review_story(engine, registry, first, str(uuid4()), target_seconds=20)
    assert "This is exchange 1 of at most" in seen[0]
    assert "What you asked for last time" not in seen[0]

    # Second reading of the same story: she is told which exchange this is and what she
    # already asked for, so a note the writer has acted on is settled instead of reopened.
    second = a_script(engine, topic_id, status="VERIFIED_PASS")
    review_story(engine, registry, second, str(uuid4()), target_seconds=20)
    assert "This is exchange 2 of at most" in seen[1]
    assert "What you asked for last time" in seen[1]
    assert "Strânge scena 5." in seen[1]
    assert "good enough to publish, not whether it is perfect" in seen[1]


def _director_says(verdict: str, *notes: str):
    def answer(prompt):
        return json.dumps(
            {
                "verdict": verdict,
                "hook_strength": 7,
                "clarity": 7,
                "payoff": 7,
                "cta_fit": 6,
                "retention": {"at_3": 70, "at_end": 45},
                "notes": list(notes) or ["Strânge scena 3."],
            }
        )

    return answer


def test_taste_alone_sends_a_passing_story_back_once_then_the_studio_goes_on(engine, studio):
    """2026-10-10 (film «How NASA Keeps a Space Telescope Alive With Frozen Fuel»): the sheet
    repair sent the story round five times; the last two drafts passed every computed check and
    the Director still answered REVISE, until the repair paused and wrote to the Owner. Taste may
    send a passing draft back once; a second REVISE on taste alone in a row is a loop, and the
    studio goes on with her notes kept as suggestions (the Owner: «studioul trebuie să rezolve
    singur, fără intervenții»)."""
    from app.factual.story_review import TASTE_SETTLED_RO, review_story

    topic_id = a_topic(engine)
    registry, _ = registry_with(studio, _director_says("REVISE", "Strânge scena 3."))

    first = review_story(
        engine, registry, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert first["failed"] == [], first["failed"]
    assert first["verdict"] == "REVISE", "her first matter of taste is honoured"

    second = review_story(
        engine, registry, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert second["failed"] == []
    assert second["verdict"] == "PASS"
    assert TASTE_SETTLED_RO in second["notes"] and "Strânge scena 3." in second["notes"]
    with Session(engine) as session:
        stored = session.get(StoryReview, second["id"]).notes_json
    assert stored["taste_settled"] is True and stored["taste_only"] is False


def test_taste_is_spent_once_per_story_even_when_a_broken_check_comes_between(engine, studio):
    """Live the same day after the first fix: taste, then a rewrite that broke a check
    (duration), then taste again — "twice in a row" never came. Taste is once per story."""
    from app.factual.story_review import TASTE_SETTLED_RO, review_story

    topic_id = a_topic(engine)
    registry, _ = registry_with(studio, _director_says("REVISE", "Strânge scena 3."))
    first = review_story(
        engine, registry, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert first["verdict"] == "REVISE" and first["failed"] == []

    # The rewrite after her notes broke a check: sent back by the arithmetic, not by taste.
    broken = a_script(engine, topic_id, status="VERIFIED_PASS")
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=broken,
                verdict="REVISE",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={"notes": ["Prea lung."], "failed": ["duration_is_realistic"]},
                estimated_seconds=57.5,
                created_at=utc_now(),
            )
        )

    third = review_story(
        engine, registry, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert third["failed"] == [] and third["verdict"] == "PASS"
    assert TASTE_SETTLED_RO in third["notes"]


def test_her_reject_and_a_taste_round_after_a_failed_check_still_stand(engine, studio):
    """Only a REVISE on taste right after another one goes on: her REJECT is a decision and
    stays hers, and a taste REVISE after a draft the checks themselves sent back is her first."""
    from app.factual.story_review import review_story

    topic_id = a_topic(engine)
    # The last reading failed a check (no "taste_only", a refusing failure stored).
    failing = a_script(engine, topic_id, status="VERIFIED_PASS")
    with Session(engine) as session, session.begin():
        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=failing,
                verdict="REVISE",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={"notes": ["Prea lung."], "failed": ["duration_is_realistic"]},
                estimated_seconds=57.5,
                created_at=utc_now(),
            )
        )
    registry, _ = registry_with(studio, _director_says("REVISE"))
    after_a_check = review_story(
        engine, registry, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert after_a_check["verdict"] == "REVISE"

    rejecting, _ = registry_with(studio, _director_says("REJECT", "Ideea nu ține un short."))
    refused = review_story(
        engine, rejecting, a_script(engine, topic_id, status="VERIFIED_PASS"), target_seconds=30
    )
    assert refused["verdict"] == "REJECT", "a taste REVISE before does not turn her REJECT"


def test_director_respects_the_same_shot_limits_as_writer(engine, studio, monkeypatch):
    from app.factual.story_review import review_story

    observed = []

    def limits(_engine, seconds):
        assert seconds == 20
        return "LOCAL VIDEO CONSTRAINT: at most 4 seconds and 8 words per shot.\n"

    monkeypatch.setattr("app.media.local_media.writer_constraints", limits)

    def answer(prompt):
        observed.append(prompt)
        return json.dumps(
            {
                "verdict": "PASS",
                "hook_strength": 8,
                "clarity": 8,
                "payoff": 8,
                "cta_fit": 8,
                "retention": {"at_3": 70, "at_end": 40},
                "notes": [],
            }
        )

    registry, _ = registry_with(studio, answer)
    script_id = a_script(engine, a_topic(engine), status="VERIFIED_PASS")
    review_story(engine, registry, script_id, str(uuid4()), target_seconds=20)
    assert "at most 4 seconds and 8 words per shot" in observed[0]
    assert "do not require merging" in observed[0]
    assert "Never request unsupported facts" in observed[0]


def test_at_the_last_exchange_she_must_decide(engine, studio):
    """A REVISE at the wall is a refusal without the word: there will be no rewrite to answer
    it, and the day would end having quietly made nothing. Her authority is untouched — what
    she refuses stays refused. It is only named."""
    from app.factual.story_review import MAX_REVISIONS, review_story

    topic_id = a_topic(engine)
    # Spend the budget: enough rewrites sent back with nothing improving between them. The
    # first reading sets the mark; the ones after it are the rounds that went nowhere.
    for _ in range(MAX_REVISIONS + 1):
        a_sent_back_review(engine, a_script(engine, topic_id, status="VERIFIED_PASS"))

    asked: list[str] = []

    def answer(prompt):
        asked.append(prompt)
        return json.dumps(
            {
                "verdict": "REVISE",
                "hook_strength": 7,
                "clarity": 7,
                "payoff": 7,
                "cta_fit": 6,
                "retention": {"at_3": 70, "at_end": 45},
                "notes": ["Încă o tăietură în scena 3."],
            }
        )

    registry, _ = registry_with(studio, answer)
    last = a_script(engine, topic_id, status="VERIFIED_PASS")
    verdict = review_story(engine, registry, last, str(uuid4()), target_seconds=20)

    assert "This is the LAST exchange" in asked[-1]
    assert verdict["verdict"] == "REJECT"
    assert any("un refuz" in note for note in verdict["notes"])


def test_a_draft_nobody_read_still_owes_work(engine, studio):
    """What a crashed run leaves behind: a draft written at the moment the day died, with no
    reading after it. It used to be invisible to both paths — not owed a rewrite, because no
    reading asked for one, and not past the page either — so the topic went on counting as in
    production and nothing new could be chosen past it."""
    from app.runbook.stages import script_work, topics_in_production

    topic_id = a_topic(engine)
    a_script(engine, topic_id, status="VERIFIED_PASS")  # written, never reviewed

    with Session(engine) as session:
        assert script_work(session, [topic_id]) == [(topic_id, [])]
        live, stalled = topics_in_production(session)
    assert live == [topic_id] and stalled == []


def test_an_ending_that_answers_its_hook_in_other_words_is_not_refused():
    """Found live on 2026-09-12, four refusals running. The hook: "it was supposed to work 14
    months; it guarded Earth for over a decade." The ending: "it spent eleven years watching
    for things that burn in our sky — and ended as one of them." That ending answers that hook
    exactly, and shares no word with it. Counting words cannot decide a question about
    meaning, so the check reports and the reader decides."""
    from app.factual.editorial import failed
    from app.factual.story_review import ADVISORY_CHECKS

    scenes = [
        {
            "purpose": "HOOK",
            "narration": (
                "This telescope was supposed to work 14 months. It guarded Earth for over "
                "a decade instead."
            ),
            "claim_ids": ["c1"],
        },
        {
            "purpose": "SETUP",
            "narration": "NASA gave it a second life: hunt the asteroids that come near us.",
            "claim_ids": ["c1"],
        },
        {
            "purpose": "PAYOFF",
            "narration": "It gave us our best look at the rocks that could hit us.",
            "claim_ids": ["c2"],
        },
        {
            "purpose": "ENDING",
            "narration": (
                "It spent eleven years watching for things that burn in our sky — and ended "
                "as one of them."
            ),
            "claim_ids": ["c2"],
        },
    ]
    story = {
        "hook": scenes[0]["narration"],
        "core_message": "The telescope that hunted asteroids burned up in the end.",
        "ending": scenes[3]["narration"],
        "cta": "Which telescope should watch the sky for us next?",
        "cta_kind": "COMMENT",
    }
    checks = story_checks(
        title="The telescope that died twice", scenes=scenes, story=story, target_seconds=20
    )
    # The check still measures, and still says it found nothing shared — that is honest.
    assert not checks["ending_answers_the_hook"]["passed"]
    # But it is not one of the checks that refuse on their own.
    assert "ending_answers_the_hook" in ADVISORY_CHECKS
    assert [name for name in failed(checks) if name not in ADVISORY_CHECKS] == []


def test_a_story_that_keeps_improving_keeps_the_room(engine, studio):
    """The Owner's rule: it must be given the time to clarify and correct.

    The budget counted every rewrite of a topic, including rounds the studio's own faults had
    caused, so a story that was getting better every draft hit the wall anyway. It counts
    rounds that went nowhere: a draft better than any before it reopens the room.
    """
    from app.factual.story_review import stalled_rounds

    class Review:
        def __init__(self, failed, verdict="REVISE"):
            self.notes_json = {"failed": failed, "flagged": []}
            self.verdict = verdict

    improving = [Review(["a", "b", "c"]), Review(["a", "b"]), Review(["a"])]
    assert stalled_rounds(improving) == 0  # every draft better than the last

    going_nowhere = improving + [Review(["a"]), Review(["a"]), Review(["a"])]
    assert stalled_rounds(going_nowhere) == 3  # three rounds with nothing to show

    # And one real improvement after a stall reopens it.
    assert stalled_rounds(going_nowhere + [Review([])]) == 0


def test_a_shot_plan_is_not_thrown_away_for_one_long_field():
    """Found live on 2026-09-13: Kael's plan for the ATLAS film — 14,036 characters of lens,
    light and composition — was discarded whole because two audio lines ran past 200
    characters, and every shot was rebuilt from the writer's one-line description."""
    from app.media.prompt_agent import _parse_bible, _parse_shot_pack

    long_audio = "A rising electronic swoosh as the leptons converge, then a sharp ding. " * 6
    answer = (
        "```json\n"
        + json.dumps(
            {
                "shots": [
                    {
                        "scene_index": 1,
                        "story_purpose": "HOOK",
                        "subject": "A yellowed 1964 physics paper.",
                        "lighting": "Soft amber from the front, no harsh shadows.",
                        "audio_intent": "narration dominates",
                    },
                    {
                        "scene_index": 2,
                        "story_purpose": "PAYOFF",
                        "subject": "Four lepton tracks.",
                        "audio_intent": long_audio,
                    },
                    {"story_purpose": "ENDING", "subject": "no index: this shot cannot be placed"},
                ]
            }
        )
        + "\n```"
    )
    pack = _parse_shot_pack(answer)
    assert pack is not None
    assert [shot.scene_index for shot in pack.shots] == [1, 2]
    # 2026-10-14 (the Owner: complete messages, no silent shortening): the long field is
    # kept whole, not cut to the schema's old 200.
    assert len(pack.shots[1].audio_intent) == len(long_audio.strip())
    assert pack.shots[0].lighting == "Soft amber from the front, no harsh shadows."

    bible = _parse_bible(
        json.dumps(
            {
                "style": "MOTION_GRAPHICS_WITH_CGI_SIMULATION",
                "palette": {"primary": ["#0A1E2A", "#1A3E5A"]},
                "lighting": {"ambient": "dark, moody", "key": "high contrast"},
                "avoid": ["daylight"],
            }
        )
    )
    assert bible is not None
    assert bible.lighting == "ambient: dark, moody; key: high contrast"
    # Codes and hex colours never reach a prompt-bound field (PROMPT_COMPILER, 2026-09-27):
    # the style code is refused, and the hex palette is kept only for the local cards.
    assert bible.style == "" and "#" not in bible.palette
    assert bible.card_palette == ["#0A1E2A", "#1A3E5A"]


def test_a_picture_is_never_asked_to_draw_writing():
    """The ATLAS payoff asked for a caption and came back as eleven seconds of stripes."""
    from app.factual.agent_pipeline import _write_instructions
    from app.media.prompt_agent import strip_on_screen_text

    visual = (
        "Four glowing lepton tracks converging on a full-screen histogram, stacking into a "
        "sharp peak at 125 GeV; a text overlay appears: 'Top quark or W boson?'"
    )
    cleaned = strip_on_screen_text(visual)
    assert "overlay" not in cleaned and "Top quark" not in cleaned
    assert cleaned.startswith("Four glowing lepton tracks")
    unchanged = "A cavern opens beneath green hills."
    assert strip_on_screen_text(unchanged) == unchanged
    assert "Niciodată text în imagine" in _write_instructions(30)


def test_a_prompt_says_each_thing_once():
    """With no shot plan, one line filled four fields and the model read it four times."""
    line = "A cavern opening beneath the countryside, revealing the layered cylinder of ATLAS."
    package = {
        "subject": line,
        "action": line,
        "environment": line,
        "lighting": line,
        "camera": "medium shot, locked camera",
        "composition": "subject centred in a vertical frame",
        "avoid": ["on-screen text or captions"],
    }
    prompt = compose_prompt(package, {"style": "motion graphic, cinematic"})
    assert prompt.count("A cavern opening") == 1
    assert "Style: motion graphic, cinematic." in prompt
    assert ", ." not in prompt
