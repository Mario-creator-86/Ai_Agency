"""compile_prompts: two prompts per filmed scene, each written for the model that reads it.

The Nepal film (storyboard 1d530880, 2026-09-26) sent the image model and the video model the
same template text: enum codes, a hex palette, "Camera: medium shot, locked camera" on every
scene, an 8-item "Avoid:" list, and never the bible's "No human faces" rule. Three scenes came
back with faces and the clips came back almost static. These tests replay the Nepal bible and
the shot plan the model actually wrote (recovered from the scratchpad copy; see
tests/fixtures/nepal_1d530880) through the compiler, and hold what the vendors' guides ask:

- the still prompt is plain photographic prose that opens with the film's look block;
- the motion prompt describes only movement: one camera move, one environment motion, one
  speed word, and a fixed closing line;
- each video model gets its own dialect (veo: negativePrompt nouns and no negation in the
  promptText; seedance and wan: short constraint sentences; Runway gen4: positive only);
- caps come from the contract and cut at sentence boundaries, never by slicing;
- the compiled Nepal prompts pass prompt_lint with zero BLOCKs.

Nothing here calls a provider: the only adapters are spies that record what they are sent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media.prompt_agent import (
    VisualBible,
    _coerce,
    _validated_package,
    compile_film_prompts,
    compile_prompts,
    motion_prompt_for,
    parse_shot_plan,
    strip_on_screen_text,
)
from app.media.prompt_lint import (
    BLOCK,
    ENUM_CODE,
    MOTION_CLOSING,
    NEGATION,
    LintScene,
    camera_moves,
    classify_kind_phrase,
    lint_film,
    utf16_units,
)
from app.media.series_look import FACTUAL_LOOK_FILE, load_factual_look, look_block

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"


def test_airless_scene_does_not_gain_invented_weather():
    compiled = compile_prompts(
        {
            "subject": "The Moon",
            "environment": "Black space",
            "camera_move": "slow orbit",
            "camera": "Medium shot",
            "motion": "Cratered surface rotates slowly.",
        },
        {
            "world": "The airless Moon in space",
            "weather": "airless vacuum",
            "lighting": "direct cold sunlight",
            "palette": "grey and black",
        },
    )
    assert "haze" not in compiled["motion_prompt"].lower()
    assert "overcast" not in compiled["still_prompt"].lower()
    assert "rotates" in compiled["motion_prompt"].lower()


#: Colour words: the palette belongs to the still, never to the motion prompt.
PALETTE_WORDS = re.compile(
    r"\b(?:blue|blues|gold|golden|grey|gray|greys|brown|browns|green|greens|red|amber|ochre"
    r"|teal|orange|yellow|purple|violet|pink|crimson|beige|cyan|magenta|silver|palette)\b",
    re.IGNORECASE,
)
PERSON = re.compile(
    r"\b(?:person|people|man|men|woman|women|farmers?|child|children|figures?|villagers?)\b",
    re.IGNORECASE,
)


def nepal() -> dict[str, Any]:
    return json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))


def nepal_packages() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The six Nepal packages as write_shot_prompts builds them from the recovered plan.

    The kind of each scene comes from the deterministic phrase classifier the SCENE_KINDS
    item uses: scene 5 (bars) is a DATA_CARD and scene 6 (black screen) is BLACK.
    """
    data = nepal()
    bible = data["visual_bible"]
    parsed = parse_shot_plan((FIXTURES / "shot_pack.txt").read_text(encoding="utf-8"))
    assert sorted(parsed.shots) == [1, 2, 3, 4, 5, 6]
    allowed = " ".join(str(scene.get("narration") or "") for scene in data["scenes"])
    packages: list[dict[str, Any]] = []
    previous = ""
    for scene in data["scenes"]:
        index = int(scene["scene_index"])
        shot = parsed.shots[index]
        facts = {
            "scene_index": index,
            "seconds": scene["duration_seconds"],
            "story_purpose": scene["story_purpose"],
            "narration": scene["narration"],
            "writer_visual": scene["writer_visual"],
            "shot_type": scene["shot_type"],
            "characters": [],
        }
        package, _notes = _validated_package(shot, facts, bible, allowed, previous)
        forced = classify_kind_phrase(f"{shot.subject} {shot.environment}")
        package["scene_kind"] = forced[0] if forced else "LIVE"
        package["scene_index"] = index
        previous = str(package.get("ending_frame") or "")
        packages.append(package)
    return packages, bible


def live(compiled: list[dict[str, Any]], packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c, p in zip(compiled, packages, strict=True) if p["scene_kind"] == "LIVE"]


# --------------------------------------------------------------------- 1. the still prompt


def test_nepal_still_prompts_are_prose_that_opens_with_one_look_and_hides_every_face():
    packages, bible = nepal_packages()
    assert [p["scene_kind"] for p in packages] == [
        "LIVE",
        "LIVE",
        "LIVE",
        "LIVE",
        "DATA_CARD",
        "BLACK",
    ]
    compiled = compile_film_prompts(packages, bible, contract={"model_id": "seedance2_5"})
    block = look_block(bible)
    assert 40 <= len(block.split()) <= 60, block
    filmed = live(compiled, packages)
    assert len(filmed) == 4
    for item in filmed:
        still = item["still_prompt"]
        assert "#" not in still
        assert not ENUM_CODE.search(still), ENUM_CODE.search(still)
        for banned in ("Avoid:", "locked camera", "Motion:", "Camera:"):
            assert banned not in still, banned
        assert still.startswith(block)
        assert item["look_block"] == block
        assert 60 <= len(still.split()) <= 120, len(still.split())
        # Every person the prompt shows is kept from behind or in the distance, within the
        # words around it, in its own sentence.
        for sentence in re.split(r"(?<=[.!?;])\s+", still):
            words = sentence.split()
            for position, word in enumerate(words):
                if PERSON.fullmatch(word.strip(".,;:()").lower()):
                    window = " ".join(words[max(0, position - 3) : position + 7]).lower()
                    assert "from behind" in window or "distant" in window, (sentence, word)
    # Scene 3 and 4 have people in them; they are still there, only turned away.
    assert "farmer" in filmed[3]["still_prompt"].lower()
    assert "figures" in filmed[2]["still_prompt"].lower()


def test_card_scenes_carry_no_paid_prompt():
    packages, bible = nepal_packages()
    compiled = compile_film_prompts(packages, bible, contract={"model_id": "seedance2_5"})
    for item in compiled[4:]:
        assert item["still_prompt"] == ""
        assert item["motion_prompt"] == ""
        assert item["negative_prompt"] is None


def test_the_look_block_comes_from_the_factual_look_file_and_the_bible_only_refines_it():
    look = load_factual_look()
    assert FACTUAL_LOOK_FILE.name == "factual_look.json"
    assert look["in_use"] is True and look["version"]
    plain = look_block({})
    assert 40 <= len(plain.split()) <= 60
    # The spec's parts: place, weather, light, palette in colour words, lens feel, grain.
    for part in ("overcast sky", "daylight", "slate blue", "35mm lens", "film grain"):
        assert part in plain, part
    refined = look_block(
        {
            "world": "the terraced hills of central Nepal",
            "weather": "monsoon rain clouds",
            "palette": "slate blue, wet ochre earth, moss green",
            # A style that contradicts the documentary look is not taken.
            "style": "anime cartoon, cel shaded",
        }
    )
    assert "terraced hills of central Nepal" in refined
    assert "monsoon rain clouds" in refined
    assert "anime" not in refined.lower() and "cartoon" not in refined.lower()
    assert 40 <= len(refined.split()) <= 60
    # A bible full of codes and hex refines nothing and breaks nothing.
    coded = look_block(nepal()["visual_bible"])
    assert "#" not in coded and not ENUM_CODE.search(coded)
    # A very long bible still gives a block of at most sixty words.
    long_bible = {key: " ".join(["windswept high ridge"] * 20) for key in ("world", "weather")}
    assert len(look_block(long_bible).split()) <= 60


# --------------------------------------------------------------------- 2. the motion prompt


def test_every_nepal_motion_prompt_is_movement_only():
    packages, bible = nepal_packages()
    compiled = compile_film_prompts(packages, bible, contract={"model_id": "seedance2_5"})
    moves = []
    for item in live(compiled, packages):
        motion = item["motion_prompt"]
        assert 20 <= len(motion.split()) <= 70, (len(motion.split()), motion)
        found = camera_moves(motion)
        assert len(found) == 1, (found, motion)
        assert found[0][0] == item["camera_move"]
        moves.append(found[0][0])
        assert not PALETTE_WORDS.search(motion), PALETTE_WORDS.search(motion)
        assert motion.endswith(MOTION_CLOSING)
        assert not re.search(r"\bthen\b", motion, re.IGNORECASE)
        # It never re-describes the picture: the still prompt is not in it.
        assert item["still_prompt"][:80] not in motion
    # The plan said "static, no movement" on every scene; the film's camera still varies.
    assert len(set(moves)) >= 3, moves


def test_an_explicit_camera_move_from_the_plan_is_kept():
    packages, bible = nepal_packages()
    package = dict(packages[1], camera_move="slow orbit")
    compiled = compile_prompts(package, bible, {"model_id": "seedance2_5"})
    assert compiled["camera_move"] == "slow orbit"
    assert [m for m, _ in camera_moves(compiled["motion_prompt"])] == ["slow orbit"]


# --------------------------------------------------------------------- 3. the dialects


def test_each_video_model_gets_its_own_dialect():
    packages, bible = nepal_packages()
    scene = packages[2]  # the mudslide, with people in it

    veo = compile_prompts(scene, bible, {"model_id": "veo3.1"})
    assert veo["negative_prompt"] and "human faces" in veo["negative_prompt"]
    assert not re.search(r"\bno\b", veo["motion_prompt"], re.IGNORECASE)
    assert not NEGATION.search(veo["motion_prompt"])
    assert veo["motion_prompt"].endswith("Continuous, seamless shot.")

    seedance = compile_prompts(scene, bible, {"model_id": "seedance2_5"})
    assert seedance["negative_prompt"] is None
    assert "No subtitles" in seedance["motion_prompt"]

    wan = compile_prompts(scene, bible, {"model_id": "wan3_prime"})
    assert wan["negative_prompt"] is None
    assert wan["motion_prompt"].endswith(MOTION_CLOSING)

    gen4 = compile_prompts(scene, bible, {"model_id": "gen4_turbo"})
    assert gen4["negative_prompt"] is None
    assert not NEGATION.search(gen4["motion_prompt"]), NEGATION.search(gen4["motion_prompt"])

    # The still prompt is the same whichever video model moves it.
    assert veo["still_prompt"] == seedance["still_prompt"] == gen4["still_prompt"]


def test_the_motion_prompt_can_be_rewritten_for_another_model_from_the_stored_package():
    packages, bible = nepal_packages()
    package = dict(packages[2])
    package.update(compile_prompts(package, bible, {"model_id": "seedance2_5"}))
    prompt, negative = motion_prompt_for(package, "veo3.1_fast")
    assert negative and "human faces" in negative
    assert not NEGATION.search(prompt)
    again, none = motion_prompt_for(package, "seedance2")
    assert again == package["motion_prompt"] and none is None
    # A package from before the compiler has no intent: its stored text is used as it is.
    assert motion_prompt_for({"motion_prompt": "Slow push-in."}, "veo3.1") == (
        "Slow push-in.",
        None,
    )


# --------------------------------------------------------------------- 4. caps


def test_caps_come_from_the_contract_and_cut_whole_sentences():
    packages, bible = nepal_packages()
    full = compile_prompts(packages[0], bible, {"model_id": "seedance2_5"})
    for cap in (600, 420, 150):
        capped = compile_prompts(
            packages[0],
            bible,
            {
                "model_id": "seedance2_5",
                "prompt_max": {"text_to_image": cap, "image_to_video": cap},
            },
        )
        for key in ("still_prompt", "motion_prompt"):
            text = capped[key]
            assert text and utf16_units(text) <= cap, (key, cap, utf16_units(text))
            assert text.endswith("."), text
            # Only whole sentences of the uncapped prompt survive, never a slice of one.
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                assert sentence in full[key], sentence
    # veo's own promptText limit (1000 UTF-16 units) is the default.
    assert utf16_units(full["still_prompt"]) <= 1000
    for source in ("backend/app/media/prompt_agent.py", "backend/app/media/assembler.py"):
        code = (ROOT / source).read_text(encoding="utf-8")
        assert "[:900]" not in code, source
        assert "[:MAX_PROMPT_CHARS]" not in code, source


# --------------------------------------------------------------------- 5. lint


def test_the_compiled_nepal_prompts_pass_the_lint_without_a_block():
    packages, bible = nepal_packages()
    for model in ("seedance2_5", "veo3.1", "wan3_prime"):
        compiled = compile_film_prompts(packages, bible, contract={"model_id": model})
        scenes = [
            LintScene(
                scene=package["scene_index"],
                kind=package["scene_kind"],
                still_prompt=item["still_prompt"],
                motion_prompt=item["motion_prompt"],
                model_id=model,
            )
            for package, item in zip(packages, compiled, strict=True)
        ]
        findings = lint_film(scenes, bible=bible)
        blocks = [f.as_dict() for f in findings if f.severity == BLOCK]
        assert blocks == [], (model, blocks)


# --------------------------------------------------------------------- 6. strip_on_screen_text


def test_strip_on_screen_text_keeps_its_punctuation_and_reports_nothing_it_did_not_do():
    kept = "Clouds roll over the ridge; wind bends the grass. Rain begins."
    assert strip_on_screen_text(kept) == kept
    assert strip_on_screen_text("Clouds drift; a caption reads: 'x'. Rain falls.") == (
        "Clouds drift. Rain falls."
    )
    assert strip_on_screen_text("A text overlay appears. Rain falls; mist rises.") == (
        "Rain falls; mist rises."
    )
    # No repair is reported when nothing was taken out, semicolons and all.
    shot = parse_shot_plan(
        json.dumps(
            {
                "shots": [
                    {
                        "scene_index": 1,
                        "story_purpose": "HOOK",
                        "subject": "a river in flood; debris turning in the current",
                        "action": "water surging; a roof tilting",
                        "environment": "a valley; terraces under water",
                        "camera": "wide shot, 24mm lens",
                        "lighting": "overcast",
                        "composition": "vertical frame; the lower quarter calm",
                        "motion": "water flowing",
                    }
                ]
            }
        )
    ).shots[1]
    package, notes = _validated_package(
        shot, {"scene_index": 1, "story_purpose": "HOOK"}, {}, "", ""
    )
    assert "cerere de text în imagine scoasă" not in notes
    assert package["subject"] == "a river in flood; debris turning in the current"


# --------------------------------------------------------------------- 7. the bible's codes


def test_coerce_rejects_codes_and_hex_in_prompt_bound_bible_fields():
    fitted = _coerce(nepal()["visual_bible"], VisualBible)
    bible = VisualBible.model_validate(fitted)
    for name in (
        "style",
        "realism",
        "period",
        "world",
        "palette",
        "lighting",
        "camera_language",
        "weather",
    ):
        value = getattr(bible, name)
        assert "#" not in value and not ENUM_CODE.search(value), (name, value)
    for rule in [*bible.continuity_rules, *bible.avoid]:
        assert "#" not in rule and not ENUM_CODE.search(rule), rule
    # The face rule is words, and survives.
    assert any("No human faces" in rule for rule in bible.continuity_rules)
    # Hex survives only where the cards read it.
    assert "#2E4A66" in bible.card_palette and "#FF4500" in bible.card_palette
    assert all(re.fullmatch(r"#[0-9A-F]{6}", colour) for colour in bible.card_palette)

    mixed = VisualBible.model_validate(
        _coerce({"palette": "slate blue (#2E4A66), muted ochre", "world": "Nepal"}, VisualBible)
    )
    assert mixed.palette == "slate blue, muted ochre"
    assert mixed.card_palette == ["#2E4A66"]
    assert mixed.world == "Nepal"


# --------------------------------------------------------------------- 8. the assembler


class SpyImages:
    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "test-stills"
    integration_id = "conn-1"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def generate_image(self, prompt, **kwargs):
        from app.providers.media_base import ImageResult
        from test_media_providers import png_bytes

        self.prompts.append(prompt)
        return ImageResult(
            image_bytes=png_bytes(1024, 1536), format="png", width=1024, height=1536, prompt=prompt
        )


class SpyMotion:
    """An image-to-video model that records every prompt and extra it is sent."""

    PROVIDER_NAME = "TEST_VIDEO_PROVIDER"
    integration_id = "conn-1"

    def __init__(self, clip: bytes, model: str) -> None:
        self.clip = clip
        self.model = model
        self.asked: list[dict[str, Any]] = []

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def create_generation(
        self, prompt, *, image_ref=None, duration_seconds=4.0, aspect_ratio="9:16", extra=None
    ):
        self.asked.append(
            {"prompt": prompt, "first_frame": bool(image_ref), "extra": dict(extra or {})}
        )
        return f"task-{len(self.asked)}"

    async def get_generation_status(self, job_id):
        from app.providers.media_base import VideoGenerationResult

        return VideoGenerationResult(
            job_id=job_id, status="COMPLETED", video_bytes=self.clip, raw_response={}
        )


def _set_packages(engine, storyboard_id: str, packages: dict[int, dict[str, Any]]) -> None:
    from app.media.models import StoryboardScene
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            if scene.scene_index in packages:
                package = packages[scene.scene_index]
                scene.prompt_json = package
                scene.visual_prompt = package["still_prompt"]


def _render(engine, tmp_path: Path, motion: SpyMotion, images: SpyImages, storyboard_id: str):
    from app.media.assembler import assemble_video_job

    return assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=images,
        video_adapter_for_scene=lambda scene: motion,
    )


def _ffmpeg_or_skip() -> None:
    from app.media.toolchain import find_ffmpeg

    if find_ffmpeg() is None:
        pytest.skip("ffmpeg not installed")


def test_the_assembler_sends_the_motion_prompt_to_image_to_video(engine, tmp_path):
    _ffmpeg_or_skip()
    from test_motion import a_clip
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    packages, bible = nepal_packages()
    first = dict(packages[0])
    first.update(compile_prompts(first, bible, {"model_id": "seedance2_5"}))
    _set_packages(engine, storyboard_id, {1: first})

    images = SpyImages()
    motion = SpyMotion(a_clip(tmp_path), "seedance2_5")
    _render(engine, tmp_path, motion, images, storyboard_id)

    assert motion.asked, "the video model must have been asked"
    sent = motion.asked[0]
    assert sent["first_frame"] is True
    assert sent["prompt"] == first["motion_prompt"]
    assert sent["prompt"] != first["still_prompt"]
    assert "negative_prompt" not in sent["extra"]
    # The still prompt went to the image model, the motion prompt did not.
    assert images.prompts[0] == first["still_prompt"]
    # A scene with no compiled package still sends its visual prompt, as before.
    assert motion.asked[1]["prompt"] == "Fixture scene 2"


def test_the_assembler_speaks_the_dialect_of_the_model_that_films_the_scene(engine, tmp_path):
    _ffmpeg_or_skip()
    from test_motion import a_clip
    from test_phase5_media import _seeded_storyboard

    storyboard_id, _ = _seeded_storyboard(engine, tmp_path)
    packages, bible = nepal_packages()
    third = dict(packages[2])
    third.update(compile_prompts(third, bible, {"model_id": "seedance2_5"}))
    _set_packages(engine, storyboard_id, {1: third})

    motion = SpyMotion(a_clip(tmp_path), "veo3.1")
    _render(engine, tmp_path, motion, SpyImages(), storyboard_id)

    sent = motion.asked[0]
    assert not NEGATION.search(sent["prompt"]), sent["prompt"]
    assert "human faces" in sent["extra"]["negative_prompt"]
    assert sent["prompt"] == motion_prompt_for(third, "veo3.1")[0]
