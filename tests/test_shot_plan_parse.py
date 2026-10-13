"""A shot plan cannot be silently lost (SHOT_PLAN_PARSE, 2026-09-27).

The Nepal film (storyboard 0000003f): the video editor wrote a 9,302-character plan - aerial
24 mm shots, people without faces, an abstract chart, a pure black screen - and all of it was
thrown away because of one unescaped pair of quotes (`"Subtle metallic "ping" as bars stop"`).
Template prompts went to the vendor instead, twice, and nobody was told. These tests replay
that answer and the ways a plan can still be lost: a strict parse, a narrow repair, a salvage
shot by shot, ONE re-ask carrying the decoder's own error, and then NEEDS_SHOT_PLAN with a
WARNING event. In PRODUCTION a film whose shots were not written by the model is stopped
before any adapter is called.

Every model here is scripted and every adapter a spy: nothing leaves the machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim
from app.media.models import Storyboard, StoryboardScene
from app.media.prompt_agent import (
    ShotPlanUnusable,
    parse_shot_plan,
    trim_payload,
    write_shot_prompts,
)
from app.media.services import generate_storyboard_from_script
from app.models import DomainEvent, OwnerPolicy
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_editorial_quality import (
    BIBLE_ANSWER,
    GOOD_SCENES,
    GOOD_STORY,
    a_passed_review,
    a_script,
    a_topic,
    registry_with,
)


@pytest.fixture
def studio(engine):
    """The staffed studio of the editorial tests: workforce, bibles, channels, models on."""
    from app.agents.models import Agent, ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.publishing.services import seed_default_channels

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        return {"provider_id": session.scalar(select(Agent.provider_id))}


FIXTURE = Path(__file__).parent / "fixtures" / "factual_sample" / "shot_pack.txt"

#: Six scenes, like the Nepal film's. The words are the reserved-address story the story
#: gate already accepts (its grounding check reads the claims); the shot plan replayed over
#: them is Nepal's, because what is tested is the reading of the plan, not the story.
NEPAL_SCENES = [
    {**scene, "scene_number": index}
    for index, scene in enumerate(
        [
            *GOOD_SCENES[:4],
            {
                "purpose": "DEVELOPMENT",
                "narration": "No registrar can sell the reserved address: the registry holds it.",
                "visual_description": "Two bars side by side.",
                "claim_ids": ["c2"],
            },
            GOOD_SCENES[4],
        ],
        start=1,
    )
]


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _nepal_board(engine) -> str:
    topic_id = a_topic(engine)
    script_id = a_script(engine, topic_id, scenes=NEPAL_SCENES, story=GOOD_STORY)
    a_passed_review(engine, script_id)
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    return str(board["id"])


def _valid_pack() -> dict[str, Any]:
    """The Nepal plan as the model meant it: the fixture's six shots, correctly escaped."""
    parsed = parse_shot_plan(_fixture_text())
    return {"shots": [parsed.shots[index].model_dump() for index in sorted(parsed.shots)]}


def _four_of_six() -> str:
    """The same plan with shots 5 and 6 broken past any repair: an unquoted value each."""
    text = json.dumps(_valid_pack(), ensure_ascii=False, indent=2)
    for camera in ('"Extreme close-up, static', '"N/A (black screen)"'):
        start = text.index(f'"camera": {camera}')
        end = text.index("\n", start)
        text = text[:start] + '"camera": wide shot, locked,' + text[end:]
    return text


class ShotModel:
    """Answers the bible, and the shot plan from a queue; counts the shot calls."""

    def __init__(self, shot_answers: list[str]) -> None:
        self.shot_answers = list(shot_answers)
        self.shot_prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        if '"shots": [' in prompt:
            self.shot_prompts.append(prompt)
            return self.shot_answers.pop(0) if self.shot_answers else "no answer left"
        return json.dumps(BIBLE_ANSWER)


def _scenes(engine, board_id: str) -> list[StoryboardScene]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )


def _events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type))
        )


# ------------------------------------------------------------------ 1: the Nepal answer


def test_the_nepal_plan_is_recovered_whole_from_the_answer_that_was_thrown_away():
    text = _fixture_text()
    # The failure as it happened: the whole answer does not decode.
    with pytest.raises(json.JSONDecodeError):
        json.loads(text[text.index("{") : text.rindex("}") + 1])

    parsed = parse_shot_plan(text)

    assert sorted(parsed.shots) == [1, 2, 3, 4, 5, 6]
    assert parsed.method == "repaired"
    assert parsed.error and "offset" in parsed.error
    assert parsed.shots[6].avoid[0] == "Any visuals (keep pure black)"
    assert parsed.shots[5].audio_intent == 'Subtle metallic "ping" as bars stop, then silence'
    # The camera the editor chose for each shot is the camera that is kept, word for word.
    saved = re.findall(r'^\s*"camera": "(.*)",\s*$', text, re.MULTILINE)
    assert len(saved) == 6
    assert [parsed.shots[index].camera for index in range(1, 7)] == saved


def test_the_repair_is_narrow_a_valid_plan_is_read_strictly_and_trailing_commas_go():
    strict = parse_shot_plan(json.dumps(_valid_pack()))
    assert strict.method == "strict" and strict.error is None
    assert sorted(strict.shots) == [1, 2, 3, 4, 5, 6]

    trailing = '{"shots": [{"scene_index": 1, "subject": "a valley", "avoid": ["text",],},],}'
    repaired = parse_shot_plan(trailing)
    assert repaired.method == "repaired"
    assert repaired.shots[1].avoid == ["text"]

    assert parse_shot_plan("I would rather not.").shots == {}


# ------------------------------------------------------------------ 2: one re-ask


def test_a_plan_with_four_of_six_shots_is_asked_for_again_once_with_the_decoder_error(
    engine, studio
):
    board_id = _nepal_board(engine)
    broken = _four_of_six()
    with pytest.raises(json.JSONDecodeError) as decoded:
        json.loads(broken)
    salvage = parse_shot_plan(broken)
    assert sorted(salvage.shots) == [1, 2, 3, 4], "four shots survive on their own"

    model = ShotModel([broken, json.dumps(_valid_pack())])
    registry, _ = registry_with(studio, model)

    result = write_shot_prompts(engine, registry, board_id, str(uuid4()))

    assert len(model.shot_prompts) == 2, "asked once, then re-asked exactly once"
    reask = model.shot_prompts[1]
    assert decoded.value.msg in reask
    assert f"offset {decoded.value.pos}" in reask
    assert "5, 6" in reask, "the re-ask names the scenes that are missing"
    assert all(shot["from_model"] for shot in result["shots"])
    assert [scene.prompt_json["source"] for scene in _scenes(engine, board_id)] == ["model"] * 6
    written = _events(engine, "media.shot_prompts_written")
    assert written and written[-1].payload["from_model"] == 6
    assert written[-1].payload["reasked"] is True


def test_a_complete_plan_is_not_asked_for_twice(engine, studio):
    board_id = _nepal_board(engine)
    model = ShotModel([_fixture_text()])
    registry, _ = registry_with(studio, model)

    write_shot_prompts(engine, registry, board_id, str(uuid4()))

    assert len(model.shot_prompts) == 1
    packages = [scene.prompt_json for scene in _scenes(engine, board_id)]
    assert packages[0]["camera"].startswith("Aerial wide shot, static, 24mm")
    assert all(package["source"] == "model" for package in packages)


# ------------------------------------------------------------------ 3: NEEDS_SHOT_PLAN


def test_junk_twice_leaves_the_film_waiting_for_a_shot_plan_with_a_warning(engine, studio):
    board_id = _nepal_board(engine)
    model = ShotModel(["Sorry, here is a poem instead.", "{not json at all"])
    registry, _ = registry_with(studio, model)

    with pytest.raises(ShotPlanUnusable) as refused:
        write_shot_prompts(engine, registry, board_id, str(uuid4()))

    assert len(model.shot_prompts) == 2
    assert refused.value.missing == [1, 2, 3, 4, 5, 6]
    with Session(engine) as session:
        assert session.get(Storyboard, board_id).status == "NEEDS_SHOT_PLAN"
    incomplete = _events(engine, "media.shot_prompts_incomplete")
    assert len(incomplete) == 1
    payload = incomplete[0].payload
    assert payload["severity"] == "WARNING"
    assert payload["from_model"] == 0
    assert payload["missing_scenes"] == [1, 2, 3, 4, 5, 6]
    assert payload["decoder_error"]
    # Nothing composed from a template reaches the scenes as if a model had written it.
    assert all(
        (scene.prompt_json or {}).get("source") != "model" for scene in _scenes(engine, board_id)
    )


def test_a_plan_still_short_after_the_re_ask_names_what_it_kept_and_what_it_lost(engine, studio):
    board_id = _nepal_board(engine)
    model = ShotModel([_four_of_six(), _four_of_six()])
    registry, _ = registry_with(studio, model)

    with pytest.raises(ShotPlanUnusable):
        write_shot_prompts(engine, registry, board_id, str(uuid4()))

    payload = _events(engine, "media.shot_prompts_incomplete")[0].payload
    assert payload["from_model"] == 4
    assert payload["missing_scenes"] == [5, 6]
    sources = [(scene.prompt_json or {}).get("source") for scene in _scenes(engine, board_id)]
    assert sources == ["model"] * 4 + ["template"] * 2


# ------------------------------------------------------------------ 4: PRODUCTION stops it


class SpyAdapter:
    """Any method called on it is a paid call made out of order: it is recorded."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(f"paid adapter called: {name}")

        return record


def _to_production(engine) -> None:
    from app.schemas import EnvironmentCommand
    from app.services import change_environment

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


def _media_with_spies(engine, monkeypatch) -> tuple[list[str], SpyAdapter]:
    from app.runbook import stages

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    spy = SpyAdapter()
    rendered: list[str] = []

    def camera(engine_, storyboard_id, correlation_id, **kwargs):
        rendered.append(storyboard_id)
        return {"output_asset_id": f"asset-{storyboard_id[:8]}", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_video_job", camera)
    monkeypatch.setattr("app.media.factory.image_provider", lambda *a, **k: spy)
    monkeypatch.setattr("app.media.factory.tts_provider", lambda *a, **k: spy)
    monkeypatch.setattr(
        "app.media.factory.render_plan",
        lambda engine_, vault, board: {
            "image": spy,
            "tts_for_scene": lambda *a: spy,
            "video_for_scene": lambda *a: spy,
            "plan": {},
        },
    )
    monkeypatch.setattr(stages, "estimate_film_cost_micros", _free_plan)
    return rendered, spy


def _free_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"usd": "0.00", "usd_micros": 0, "caveat": ""}


def test_in_production_a_film_without_a_model_shot_plan_is_stopped_before_any_adapter(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    board_id = _nepal_board(engine)
    # No model reachable: the studio composes template prompts, which is a TEST convenience.
    write_shot_prompts(engine, None, board_id, str(uuid4()))
    assert {s.prompt_json["source"] for s in _scenes(engine, board_id)} == {"template"}
    _to_production(engine)
    rendered, spy = _media_with_spies(engine, monkeypatch)

    outcome = stages._media(engine, settings, None, None)

    assert rendered == [], "the film is stopped, not rendered from template prompts"
    assert spy.calls == []
    assert outcome["status"] == "SKIPPED", outcome
    assert "plan" in outcome["reason"].lower()
    assert board_id[:8] in " ".join(outcome["artefacts"]["held"])
    with Session(engine) as session:
        assert session.get(Storyboard, board_id).status == "NEEDS_SHOT_PLAN"
    held = _events(engine, "media.shot_prompts_incomplete")
    assert held and held[-1].payload["severity"] == "WARNING"
    assert held[-1].payload["missing_scenes"] == [1, 2, 3, 4, 5, 6]


def test_in_test_the_same_template_film_is_still_rendered(engine, settings, studio, monkeypatch):
    from app.runbook import stages

    board_id = _nepal_board(engine)
    write_shot_prompts(engine, None, board_id, str(uuid4()))
    rendered, _spy = _media_with_spies(engine, monkeypatch)

    stages._media(engine, settings, None, None)

    assert rendered == [board_id]


# ------------------------------------------------------------------ 5: whole-item trimming


def test_payload_trimming_drops_whole_claims_and_the_json_sent_always_parses(engine, studio):
    topic_id = a_topic(engine)
    long_claims = [f"claim-{n}" for n in range(40)]
    with Session(engine) as session, session.begin():
        for claim_id in long_claims:
            session.add(
                FactualClaim(
                    id=claim_id,
                    source_id=None,
                    topic_id=topic_id,
                    claim_text=f"{claim_id}: " + "a long verified sentence about the floods. " * 12,
                    claim_type="GENERAL",
                    importance="KEY",
                    status="SUPPORTED",
                    confidence=0.9,
                    evidence_text="x",
                    created_at=utc_now(),
                )
            )
    scenes = [{**scene, "claim_ids": ["c1", *long_claims]} for scene in NEPAL_SCENES]
    script_id = a_script(engine, topic_id, scenes=scenes, story=GOOD_STORY)
    a_passed_review(engine, script_id)
    board_id = str(
        generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")["id"]
    )
    with Session(engine) as session, session.begin():
        for scene in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == board_id)
        ):
            scene.claim_ids_json = ["c1", *long_claims]

    asked: list[str] = []

    def answer(prompt: str) -> str:
        asked.append(prompt)
        if '"shots": [' in prompt:
            return _fixture_text()
        return json.dumps(BIBLE_ANSWER)

    registry, _ = registry_with(studio, answer)
    write_shot_prompts(engine, registry, board_id, str(uuid4()))

    assert len(asked) == 2  # the bible, then the shots
    with Session(engine) as session:
        originals = {row.claim_text for row in session.scalars(select(FactualClaim))}
    for prompt in asked:
        body = re.search(
            r"<untrusted_source_evidence[^>]*>\n(.*)\n</untrusted_source_evidence>", prompt, re.S
        )
        assert body is not None
        data = json.loads(body.group(1))  # never cut mid-string
        film = data.get("film", data)
        assert [scene["scene_index"] for scene in film["scenes"]] == [1, 2, 3, 4, 5, 6]
        sent = [claim for scene in film["scenes"] for claim in scene["claims"]]
        assert sent, "the claims that fit are kept"
        assert all(claim in originals for claim in sent), "each claim is whole or absent"
        assert len(sent) < 6 * 41, "some whole claims were dropped to fit"


def test_trim_payload_drops_claims_then_scenes_and_never_slices():
    data = {
        "title": "t",
        "scenes": [
            {"scene_index": i, "narration": "n" * 50, "claims": ["c" * 300] * 5}
            for i in range(1, 7)
        ],
    }
    fitted, dropped = trim_payload(data, 2500)
    text = json.dumps(fitted)
    assert len(text) <= 2500
    assert json.loads(text) == fitted
    assert dropped["claims"] > 0
    assert all(claim == "c" * 300 for s in fitted["scenes"] for claim in s["claims"])

    tiny, dropped_more = trim_payload(data, 400)
    assert len(json.dumps(tiny)) <= 400
    assert dropped_more["scenes"] > 0
    assert [s["scene_index"] for s in tiny["scenes"]] == list(range(1, len(tiny["scenes"]) + 1)), (
        "scenes are dropped from the end, whole"
    )
