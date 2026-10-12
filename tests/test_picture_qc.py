"""Quality control looks at the pictures before the Director does.

What is asserted: a film whose third scene is a blank field fails and names the scene; a
film whose pictures show what the scenes asked for passes; with no vision-capable model,
no registry or no frames the check certifies nothing and the film's verdict is unchanged;
a character wearing the wrong outfit fails with their name and their scene; a character
the bible neither describes nor pictures is not applicable; a bible with no characters at
all stays NOT_IMPLEMENTED as it was. Every model call is faked at the provider's transport,
as `tests/test_editorial.py` fakes it, and counted: one look per film.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, Capability, ModelCapability, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import (
    CharacterBible,
    MediaAsset,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.picture_qc import PICTURE_TASK, evaluate_pictures
from app.media.qc import evaluate_media_qc
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

FRAMES = ["ZnJhbWUx", "ZnJhbWUy", "ZnJhbWUz"]


class ScriptedModel:
    """The provider's transport, faked. No model is ever called: the Owner's rule."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "extra": kwargs.get("extra")})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    return staff(engine)


def staff(engine):
    """The workforce, available and unstopped. A plain function so other test files can
    build the same studio without copying it."""
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(staffed, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


def give_vision(engine, *agent_ids):
    """What a provider declares about a model, as the model sync records it."""
    with Session(engine) as session, session.begin():
        # The seed now writes this row itself, because a role can only prefer a capability
        # the studio has a name for; the declaration below is still per model, as a provider
        # makes it.
        capability = session.scalar(select(Capability).where(Capability.name == "vision"))
        if capability is None:
            capability = Capability(id=str(uuid4()), name="vision", description="sees pictures")
            session.add(capability)
            session.flush()
        for agent_id in agent_ids:
            agent = session.get(Agent, agent_id)
            session.add(
                ModelCapability(
                    model_id=agent.model_id,
                    capability_id=capability.id,
                    confidence="DECLARED_BY_PROVIDER",
                )
            )


def a_film(engine, *, scenes: list[dict] | None = None, title="Three shots"):
    """A rendered storyboard of three scenes and the film it produced.

    `scenes` is a list of `{"picture", "narration", "characters"}`; the default is three
    plain scenes with nobody in them.
    """
    plan = scenes or [
        {"picture": "The telescope's golden mirror against the dark", "narration": "A mirror."},
        {"picture": "A spectrum with a water line marked", "narration": "A line of water."},
        {"picture": "The planet turning against its star", "narration": "A world that keeps it."},
    ]
    ids = {k: str(uuid4()) for k in ("topic", "script", "board", "asset", "job")}
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title=title,
                topic="space",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title=title,
                voiceover_full_text=" ".join(s["narration"] for s in plan),
                claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title=title,
                status="RENDERED",
                total_scenes=len(plan),
                created_at=now,
            )
        )
        session.flush()
        for index, scene in enumerate(plan, start=1):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=scene["picture"],
                    visual_type="GENERATED_IMAGE",
                    duration_seconds=6.0,
                    voiceover_segment=scene["narration"],
                    character_ids_json=list(scene.get("characters") or []),
                    claim_ids_json=[],
                    created_at=now,
                )
            )
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=18.0,
                provider_name="RUNWAY_IMAGES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
            )
        )
    return ids


def a_character(engine, *, name, outfit="A charcoal suit with a white shirt", reference=None):
    character_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            CharacterBible(
                id=character_id,
                canonical_name=name,
                palette_json={"suit": "#334155"} if outfit else {},
                face_hair_desc="Short dark hair, square glasses" if outfit else "",
                outfit_desc=outfit,
                props_desc="An espresso cup" if outfit else "",
                role_symbols="a clipboard" if outfit else "",
                reference_assets_json={"portrait": reference} if reference else {"portrait": None},
                forbidden_deviations="Never in athletic wear.",
                created_at=utc_now(),
            )
        )
    return character_id


def a_reference_image(engine, tmp_path):
    """A stored reference portrait: a real file with a real asset row pointing at it."""
    asset_id = str(uuid4())
    path = tmp_path / f"{asset_id}.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"portrait-bytes")
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="IMAGE",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="image/png",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
    return asset_id


@pytest.fixture
def seen_frames(monkeypatch):
    """The encoder, faked: one frame per scene, without asking ffmpeg for a film we never made."""
    asked: dict = {}

    def frames_for(path, ffmpeg_path, duration, scene_seconds=None):
        asked["path"] = path
        asked["scene_seconds"] = list(scene_seconds or [])
        return list(FRAMES)

    monkeypatch.setattr("app.media.picture_qc.frames_for", frames_for)
    return asked


def scene_answer(scene, reason="", **changes):
    """One scene's answer as the model writes it: a picture, ONE picture, the scene asked for."""
    entry = {
        "scene": scene,
        "is_a_picture": True,
        "one_picture": True,
        "shows_the_scene": True,
        "reason": reason,
    }
    return {**entry, **changes}


def all_good(scenes=3, characters=()):
    return json.dumps(
        {
            "scenes": [scene_answer(i, "as asked") for i in range(1, scenes + 1)],
            "characters": [
                {"scene": scene, "character": name, "matches": True, "reason": "as the bible says"}
                for scene, name in characters
            ],
        }
    )


# ----------------------------------------------------------------- the pictures themselves


def test_a_blank_third_scene_fails_the_film_and_names_the_scene(engine, staffed, seen_frames):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    answer = json.dumps(
        {
            "scenes": [
                scene_answer(1),
                scene_answer(2),
                {
                    "scene": 3,
                    "is_a_picture": False,
                    "one_picture": True,
                    "shows_the_scene": False,
                    "reason": "an empty beige field, nothing in it",
                },
            ]
        }
    )
    registry, model = registry_with(staffed, lambda p: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    picture = result["picture_qc"]
    assert picture["status"] == "MEASURED" and picture["passed"] is False
    assert picture["frames"] == 3 and picture["model_used"] is True
    assert any("Scene 3" in reason for reason in result["failures"]), result["failures"]
    assert any("empty beige field" in reason for reason in result["failures"])
    assert not any("Scene 1" in reason for reason in result["failures"])
    # One look at the whole film, not one call per scene.
    assert len(model.calls) == 1
    assert model.calls[0]["extra"]["images"] == FRAMES


def test_pictures_that_show_the_scene_pass_and_the_film_is_looked_at_once(
    engine, staffed, seen_frames
):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda p: all_good())

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["picture_qc"]["passed"] is True
    assert result["failures"] == []
    assert len(model.calls) == 1
    prompt = model.calls[0]["prompt"]
    assert "golden mirror" in prompt and "A line of water." in prompt
    assert seen_frames["scene_seconds"] == [6.0, 6.0, 6.0]


def test_finished_picture_qc_reads_requested_motion_and_ending_not_only_the_still(
    engine, staffed, seen_frames
):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == ids["board"], StoryboardScene.scene_index == 1
            )
        )
        scene.prompt_json = {
            "still_prompt": "A pencil spiral on a cream napkin lies on a walnut table.",
            "motion_prompt": "A faint glowing trail of particles rises from the pencil spiral.",
            "ending_frame": "The napkin is still flat; the faint glow has risen above it.",
        }
    registry, model = registry_with(staffed, lambda p: all_good())

    evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    prompt = model.calls[0]["prompt"]
    assert "A pencil spiral on a cream napkin" in prompt
    assert "A faint glowing trail of particles rises" in prompt
    assert "the faint glow has risen above it" in prompt
    assert "requested motion" in prompt


@pytest.mark.parametrize("rewritten", [False, True])
def test_render_prompt_context_uses_submitted_take_before_a_later_storyboard_rewrite(
    engine, rewritten
):
    from app.media.models import SceneTake
    from app.media.picture_qc import film_scene_prompts
    from app.providers.runpod.jobs import GenerationJob

    ids = a_film(engine)
    take_id, remote, now = str(uuid4()), "offline-recorded-motion:0", utc_now()
    original_motion = "A faint glowing trail of particles rises from the pencil spiral."
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == ids["board"], StoryboardScene.scene_index == 1
            )
        )
        scene.prompt_json = {
            "still_prompt": "The same pencil spiral and napkin.",
            "motion_prompt": "The napkin stays dark and still." if rewritten else original_motion,
            "ending_frame": "No glow is visible." if rewritten else "The faint glow has risen.",
        }
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=ids["board"],
                scene_number=1,
                kind="motion",
                prompt_hash="b" * 64,
                model_id="offline-motion",
                resolution="1080:1920",
                remote_task_id=remote,
                status="APPROVED",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            GenerationJob(
                id=str(uuid4()),
                idempotency_key=str(uuid4()),
                payload_hash="c" * 64,
                provider="runpod",
                target="offline",
                project_id=ids["board"],
                scene_id="1",
                attempt=1,
                operation="video",
                model="offline-motion",
                gpu="offline",
                hourly_rate="0",
                remote_job_id=remote,
                status="COMPLETED",
                request={"prompt": original_motion},
                output={},
                created_at=now,
            )
        )
        session.flush()
        reading = film_scene_prompts(
            session, {"scenes": [{"scene_index": 1, "motion": {"take_id": take_id}}]}, scene
        )

    assert reading["motion_prompt"] == original_motion
    assert reading["prompt_sources"]["motion"] == "submitted_generation_job"
    assert reading["ending_frame"] == ("" if rewritten else "The faint glow has risen.")
    assert reading["prompt_sources"]["ending_frame"] == (
        "unavailable_for_submitted_take" if rewritten else "current_storyboard"
    )


def test_a_scene_made_of_panels_fails_the_film_and_names_the_scene(engine, staffed, seen_frames):
    """2026-10-09: scene 5 was three stacked panels and a model told the plan's three moments
    found it matched. The look now asks whether each frame is ONE picture."""
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    triptych = scene_answer(2, "a tunnel, a black band, another tunnel, stacked", one_picture=False)
    answer = json.dumps({"scenes": [scene_answer(1), triptych, scene_answer(3)]})
    registry, model = registry_with(staffed, lambda p: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    picture = result["picture_qc"]
    assert picture["status"] == "MEASURED" and picture["passed"] is False
    (failure,) = result["failures"]
    assert failure.startswith("Scene 2:") and "not one picture" in failure
    assert "black band" in failure
    records = {entry["scene"]: entry for entry in picture["scenes"]}
    assert records[2]["one_picture"] is False and records[1]["one_picture"] is True
    prompt = model.calls[0]["prompt"]
    assert "ONE picture" in prompt and '"one_picture": true' in prompt


def test_a_look_that_leaves_the_one_picture_question_out_certifies_nothing(
    engine, staffed, seen_frames
):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    silent = [
        {key: value for key, value in scene_answer(i).items() if key != "one_picture"}
        for i in (1, 2, 3)
    ]
    registry, _ = registry_with(staffed, lambda p: json.dumps({"scenes": silent}))

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["picture_qc"]["status"] == "NOT_APPLICABLE"
    assert result["picture_qc"]["passed"] is None and result["failures"] == []


def test_without_a_vision_model_the_check_certifies_nothing(engine, staffed, seen_frames):
    """No employee's model declares vision: the pictures were not looked at, and saying so
    is the whole point — a check that could not run never reports a pass."""
    ids = a_film(engine)
    registry, model = registry_with(staffed, lambda p: all_good())

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    picture = result["picture_qc"]
    assert picture["status"] == "NOT_APPLICABLE" and picture["passed"] is None
    assert "vision" in picture["detail"]
    assert result["failures"] == []
    assert model.calls == []
    assert result["character_drift_qc"]["passed"] is None


def test_no_registry_and_no_frames_are_both_not_applicable(engine, staffed, monkeypatch):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)

    without_registry = evaluate_pictures(engine, None, ids["asset"], str(uuid4()))
    assert without_registry["picture_qc"]["status"] == "NOT_APPLICABLE"
    assert without_registry["picture_qc"]["passed"] is None
    assert without_registry["failures"] == []

    monkeypatch.setattr(
        "app.media.picture_qc.frames_for", lambda path, ffmpeg, duration, scene_seconds=None: []
    )
    registry, model = registry_with(staffed, lambda p: all_good())
    without_frames = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))
    assert without_frames["picture_qc"]["status"] == "NOT_APPLICABLE"
    assert without_frames["picture_qc"]["passed"] is None
    assert "frame" in without_frames["picture_qc"]["detail"]
    assert model.calls == []


def test_the_look_is_an_agent_run_so_the_day_s_ceiling_covers_it(engine, staffed, seen_frames):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(staffed, lambda p: all_good())

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    with Session(engine) as session:
        runs = list(session.scalars(select(AgentRun).where(AgentRun.task_type == PICTURE_TASK)))
    assert len(runs) == 1 and runs[0].status == "SUCCEEDED"
    assert result["picture_qc"]["run_id"] == runs[0].id


# --------------------------------------------------------------------------- the characters


def test_a_character_in_the_wrong_outfit_fails_and_names_them(engine, staffed, seen_frames):
    sarah = a_character(engine, name="Sarah Director")
    ids = a_film(
        engine,
        scenes=[
            {"picture": "Sarah at the board", "narration": "Right.", "characters": [sarah]},
            {"picture": "The board alone", "narration": "The number."},
            {"picture": "Sarah leaving", "narration": "Tomorrow.", "characters": [sarah]},
        ],
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    answer = json.dumps(
        {
            "scenes": [scene_answer(i) for i in (1, 2, 3)],
            "characters": [
                {"scene": 1, "character": "Sarah Director", "matches": True, "reason": "the suit"},
                {
                    "scene": 3,
                    "character": "Sarah Director",
                    "matches": False,
                    "reason": "a red tracksuit, not the charcoal suit the bible describes",
                },
            ],
        }
    )
    registry, model = registry_with(staffed, lambda p: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    drift = result["character_drift_qc"]
    assert drift["status"] == "MEASURED" and drift["passed"] is False
    failure = [r for r in result["failures"] if "Sarah Director" in r]
    assert failure and "Scene 3" in failure[0] and "tracksuit" in failure[0]
    assert not any("Scene 1" in r for r in result["failures"])
    assert result["picture_qc"]["passed"] is True
    # Still one look: the frames carry both questions.
    assert len(model.calls) == 1
    assert "Sarah Director" in model.calls[0]["prompt"]
    assert "charcoal suit" in model.calls[0]["prompt"]


def test_a_character_with_neither_reference_nor_description_is_not_applicable(
    engine, staffed, seen_frames
):
    nobody = a_character(engine, name="Unwritten Extra", outfit="")
    ids = a_film(
        engine,
        scenes=[
            {"picture": "Someone at a desk", "narration": "Hello.", "characters": [nobody]},
            {"picture": "The desk alone", "narration": "Quiet."},
            {"picture": "The window", "narration": "Dusk."},
        ],
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda p: all_good())

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    drift = result["character_drift_qc"]
    assert drift["status"] == "NOT_APPLICABLE" and drift["passed"] is None
    entry = drift["characters"][0]
    assert entry["character"] == "Unwritten Extra" and entry["scene"] == 1
    assert entry["status"] == "NOT_APPLICABLE" and entry["matches"] is None
    assert "no description" in entry["reason"] and "no reference" in entry["reason"]
    assert result["failures"] == []
    # The character was never sent to the model; the pictures still were.
    assert len(model.calls) == 1
    assert "Unwritten Extra" not in model.calls[0]["prompt"]


def test_a_bible_without_characters_stays_not_implemented(engine, staffed, seen_frames):
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(staffed, lambda p: all_good())

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    drift = result["character_drift_qc"]
    assert drift["status"] == "NOT_IMPLEMENTED" and drift["passed"] is None
    assert drift["characters_configured"] == 0


def test_the_stored_reference_portrait_is_attached(engine, staffed, seen_frames, tmp_path):
    portrait = a_reference_image(engine, tmp_path)
    sarah = a_character(engine, name="Sarah Director", reference=portrait)
    ids = a_film(
        engine,
        scenes=[
            {"picture": "Sarah at the board", "narration": "Right.", "characters": [sarah]},
            {"picture": "The board", "narration": "The number."},
            {"picture": "The window", "narration": "Dusk."},
        ],
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda p: all_good(characters=[(1, "Sarah Director")]))

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["character_drift_qc"]["passed"] is True
    assert result["character_drift_qc"]["reference_images"] == 1
    images = model.calls[0]["extra"]["images"]
    assert images[:3] == FRAMES and len(images) == 4
    assert "reference" in model.calls[0]["prompt"].lower()


# ------------------------------------------------------------ and inside quality control


def test_quality_control_fails_a_film_whose_picture_is_not_a_picture(engine, staffed, seen_frames):
    """The gate is quality control's, not only the Director's: the report says FAILED and
    the reason names the scene, before the film is ever offered for review."""
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(
        staffed,
        lambda p: json.dumps(
            {
                "scenes": [
                    scene_answer(1),
                    scene_answer(2),
                    {
                        "scene": 3,
                        "is_a_picture": False,
                        "one_picture": True,
                        "shows_the_scene": False,
                        "reason": "vertical stripes",
                    },
                ]
            }
        ),
    )

    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()), registry=registry)

    assert report["status"] == "FAILED"
    picture = report["checks_json"]["picture_qc"]
    assert picture["status"] == "MEASURED" and picture["passed"] is False
    assert any("Scene 3" in r and "stripes" in r for r in report["failure_reasons_json"])


def test_quality_control_without_a_registry_reports_the_pictures_unlooked_at(engine, staffed):
    """The old callers pass no registry, and nothing about them may quietly start passing."""
    ids = a_film(engine)
    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()))
    picture = report["checks_json"]["picture_qc"]
    assert picture["status"] == "NOT_APPLICABLE" and picture["passed"] is None
    assert report["checks_json"]["character_drift_qc"]["passed"] is None


def test_a_refused_picture_fails_the_film_in_production_as_well_as_in_test(
    engine, staffed, seen_frames
):
    """The gate is unconditional, and that is a decision worth holding.

    `motion_qc` is conditional on PRODUCTION because in TEST most scenes push by design, so
    the count it measures is the studio's own policy there. Nothing in TEST policy produces
    a picture of nothing, so this gate follows `content_integrity_qc` instead and fails in
    both environments. Measured on the same film twice, once per environment.
    """
    from app.media.picture_qc import evaluate_pictures

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(
        staffed,
        lambda p: json.dumps(
            {
                "scenes": [
                    scene_answer(1),
                    scene_answer(2),
                    {
                        "scene": 3,
                        "is_a_picture": False,
                        "one_picture": True,
                        "shows_the_scene": False,
                        "reason": "an empty grey field",
                    },
                ]
            }
        ),
    )
    seen: dict[str, dict] = {}
    for environment in ("TEST", "PRODUCTION"):
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).environment = environment
        ids = a_film(engine)
        result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))
        seen[environment] = result

    for environment, result in seen.items():
        assert result["picture_qc"]["passed"] is False, environment
        assert any("Scene 3" in reason for reason in result["failures"]), environment


def test_a_provider_the_registry_cannot_reach_stands_the_check_down(engine, staffed, seen_frames):
    """A registry that holds some other provider is the live studio's own case: the employee
    who can see is there, the adapter for her provider is not. The run is recorded BLOCKED and
    the check reports NOT_APPLICABLE — it must not be an exception that takes the whole
    quality-control report down with it, because then a missing adapter would stop the day."""
    from app.media.picture_qc import evaluate_pictures

    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry = ProviderRegistry()
    registry.register(str(uuid4()), ScriptedModel(lambda p: all_good()))

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    assert result["picture_qc"]["status"] == "NOT_APPLICABLE"
    assert result["picture_qc"]["passed"] is None
    assert result["character_drift_qc"]["passed"] is None
    assert result["failures"] == []
    with Session(engine) as session:
        run = session.scalars(select(AgentRun).where(AgentRun.task_type == PICTURE_TASK)).one()
        assert run.status == "BLOCKED_PROVIDER"


# ------------------------------------------------- and when the Owner measures a film himself
# Measured before this work: `backend/app/media/router.py` called `evaluate_media_qc` with the
# settings alone at both of its call sites, so the same film reported the picture and character
# checks NOT_APPLICABLE when the Owner pressed the button and MEASURED when the day ran. The
# route now hands over the registry the app already holds and the configured encoder.


def test_the_owners_own_quality_control_looks_at_the_pictures(
    client, headers, engine, staffed, seen_frames
):
    """Through the route, on a film whose third scene is not a picture: the check is measured,
    the film fails and the reason names the scene — the day's reading of the same film."""
    ids = a_film(engine)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(
        staffed,
        lambda p: json.dumps(
            {
                "scenes": [
                    scene_answer(1),
                    scene_answer(2),
                    {
                        "scene": 3,
                        "is_a_picture": False,
                        "one_picture": True,
                        "shows_the_scene": False,
                        "reason": "an empty grey field",
                    },
                ]
            }
        ),
    )
    client.app.app.state.registry = registry

    response = client.post(f"/api/v1/media/qc/{ids['asset']}", headers=headers)

    assert response.status_code == 200, response.text
    report = response.json()
    picture = report["checks_json"]["picture_qc"]
    assert picture["status"] == "MEASURED" and picture["passed"] is False
    assert report["status"] == "FAILED"
    assert any("Scene 3" in reason for reason in report["failure_reasons_json"])
    # One look at the whole film, here as in the day's stage.
    assert len(model.calls) == 1


# ------------------------------------------ the film the studio actually makes, end to end


def a_factual_film(engine, plan: list[dict], title="Factual"):
    """A film built the way the studio builds one: the real storyboard path, then a render.

    `plan` is the script writer's own scenes. Nothing here writes `character_ids_json`: that
    is what `generate_storyboard_from_script` decides, and what this file exists to measure.
    """
    from app.media.services import generate_storyboard_from_script

    ids = {k: str(uuid4()) for k in ("topic", "script", "asset", "job")}
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.add(
            TopicIdea(
                id=ids["topic"],
                title=title,
                topic="space",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title=title,
                voiceover_full_text=" ".join(str(s.get("narration") or "") for s in plan),
                scenes_json=plan,
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
    board = generate_storyboard_from_script(
        engine, ids["script"], "GENERATED_IMAGE", "9:16", str(uuid4())
    )
    ids["board"] = board["id"]
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="RUNWAY_IMAGES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
            )
        )
    return ids


def test_the_character_check_measures_a_factual_film_that_named_its_cast(
    engine, staffed, seen_frames
):
    """The gate can now run on the studio's main product, not only on the serial.

    Measured before this: every factual scene was written with an empty cast, so this check
    answered "no scene in this film lists a character" on every film the studio has ever
    made. The storyboard path now records the character the film states is in the scene, and
    the check compares that scene against the bible.
    """
    a_character(engine, name="Sarah Executive")
    ids = a_factual_film(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window, reading the day's figures",
                "narration": "The day starts with the numbers.",
                "characters": ["Sarah"],
            },
            {
                "scene_index": 2,
                "visual_description": "A spectrum with a water line marked",
                "narration": "A line of water.",
            },
        ],
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(
        staffed, lambda _: all_good(scenes=2, characters=[(1, "Sarah Executive")])
    )

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    drift = result["character_drift_qc"]
    assert drift["status"] == "MEASURED" and drift["passed"] is True
    assert drift["characters_measured"] == 1
    assert [row["scene"] for row in drift["characters"]] == [1]
    assert len(model.calls) == 1, "one look per film"


def test_a_factual_film_of_landscapes_has_no_cast_and_the_storyboard_says_why(
    engine, staffed, seen_frames
):
    """An empty cast is a decision the storyboard recorded, not a gap nobody filled.

    The check itself still certifies nothing here — it measured no character, and it says so
    with `passed` None, which is the rule. What is new is that the reason is readable: the
    storyboard's own record says the film shows nobody by design.
    """
    from app.media.services import NO_CAST_BY_DESIGN, storyboard_cast_note

    a_character(engine, name="Sarah Executive")
    ids = a_factual_film(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "The telescope's golden mirror against the dark",
                "narration": "A mirror.",
            },
            {
                "scene_index": 2,
                "visual_description": "The planet turning against its star",
                "narration": "A world that keeps it.",
            },
        ],
        title="Landscapes",
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(staffed, lambda _: all_good(scenes=2))

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    drift = result["character_drift_qc"]
    assert drift["status"] == "NOT_APPLICABLE" and drift["passed"] is None
    assert drift["characters_measured"] == 0
    # The check says what the record says: "no characters by design", not "nobody listed
    # them". Both were the same sentence until the storyboard began recording its decision.
    assert drift["detail"] == NO_CAST_BY_DESIGN
    with Session(engine) as session:
        assert storyboard_cast_note(session, ids["board"]) == NO_CAST_BY_DESIGN


def test_a_guessed_name_is_looked_at_and_can_never_fail_the_film(engine, staffed, seen_frames):
    """A name the prose merely spells informs the comparison and refuses nothing.

    "Sarah at the studio window" is a guess: the storyboard does not cast her, so no
    reference is bought for her and no lock refuses the film on her account. The gate may
    still ask whether the frame shows her — that costs nothing but a line in the question —
    but a "no" is an observation, never a failure, because the studio was never told she was
    in the shot. The check therefore certifies nothing here: `passed` stays None.
    """
    a_character(engine, name="Sarah Executive")
    ids = a_factual_film(
        engine,
        [
            {
                "scene_index": 1,
                "visual_description": "Sarah at the studio window, reading the day's figures",
                "narration": "The day starts with the numbers.",
            },
            {
                "scene_index": 2,
                "visual_description": "A spectrum with a water line marked",
                "narration": "A line of water.",
            },
        ],
        title="A guess",
    )
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    answer = json.dumps(
        {
            "scenes": [scene_answer(i, "as asked") for i in (1, 2)],
            "characters": [
                {
                    "scene": 1,
                    "character": "Sarah Executive",
                    "matches": False,
                    "reason": "there is no person in this frame at all",
                }
            ],
        }
    )
    registry, model = registry_with(staffed, lambda _: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    with Session(engine) as session:
        assert [
            scene.character_ids_json
            for scene in session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == ids["board"])
                .order_by(StoryboardScene.scene_index)
            )
        ] == [[], []]
    drift = result["character_drift_qc"]
    assert drift["status"] == "NOT_APPLICABLE" and drift["passed"] is None
    assert drift["characters_measured"] == 0 and drift["characters_observed"] == 1
    observed = drift["characters"][0]
    assert observed["status"] == "OBSERVED" and observed["basis"] == "guessed"
    assert observed["scene"] == 1 and observed["matches"] is False
    assert result["failures"] == [], "a guess never fails a film"
    assert result["picture_qc"]["passed"] is True
    assert len(model.calls) == 1, "one look per film"


# ------------------------------------------------------------- one still, before motion
#
# judge_still is the vision half of the stills gate (app.media.still_gate): one call per
# candidate still, at 1080 px, through the same LOOKERS path, with a verdict schema that has
# no field a silent model could pass by.

NEPAL_STILL = (
    __import__("pathlib").Path(__file__).resolve().parent
    / "fixtures"
    / "nepal_1d530880"
    / "scene_01.jpg"
)


def still_plan(scene=1):
    from app.media.still_gate import StillPlan

    return StillPlan(
        scene=scene,
        still_prompt="A remote Himalayan village under gathering storm clouds, seen from above.",
        camera_move="aerial drift forward",
        faces_forbidden=True,
        bible_rules=("No human faces appear",),
        look_block="Late monsoon, overcast, soft diffuse light, muted greens and slate blue.",
    )


def a_still_answer(scene=1, **changes):
    entry = {
        "scene": scene,
        "faces_visible": False,
        "readable_text": False,
        "one_picture": True,
        "matches_plan": True,
        "shows_scene": True,
        "look_ok": True,
        "technical_ok": True,
        "bible_violations": "none",
        "verdict": "buy_motion",
        "reason": "the village under storm clouds",
    }
    entry.update(changes)
    return json.dumps({"stills": [entry]})


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Width and height from a baseline or progressive JPEG's SOF marker."""
    index = 2
    while index < len(data):
        assert data[index] == 0xFF
        marker = data[index + 1]
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        index += 2 + length
    raise AssertionError("no SOF marker")


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_judge_still_sends_the_still_at_1080_px_in_one_call(engine, staffed):
    import base64

    from app.media.picture_qc import STILL_TASK, STILL_WIDTH, judge_still

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, model = registry_with(staffed, lambda p: a_still_answer())

    judged = judge_still(engine, registry, NEPAL_STILL, still_plan(), str(uuid4()))

    assert STILL_WIDTH == 1080
    assert judged.status == "MEASURED" and judged.verdict is not None
    assert judged.verdict.verdict == "buy_motion" and judged.image_width == 1080
    assert len(model.calls) == 1
    images = model.calls[0]["extra"]["images"]
    assert len(images) == 1
    assert _jpeg_size(base64.b64decode(images[0])) == (1080, 1920)
    prompt = model.calls[0]["prompt"]
    assert "No human faces appear" in prompt and "bible_violations" in prompt
    assert "name the violation or write none" in prompt
    # 2026-10-09: a still is one moment, and one picture (scene 5 was three stacked panels).
    assert "one_picture" in prompt and "ONE moment" in prompt
    assert "judge the still against the first moment only" in prompt
    assert judged.verdict.one_picture is True
    with Session(engine) as session:
        runs = list(session.scalars(select(AgentRun).where(AgentRun.task_type == STILL_TASK)))
    assert len(runs) == 1 and judged.run_id == runs[0].id


def test_the_still_verdict_has_no_field_that_passes_by_default():
    from app.media.picture_qc import StillJudgeReport, StillVerdict
    from pydantic import ValidationError

    # one_picture and shows_scene are asked of the model like every other field (the report a
    # model's answer is read into refuses an entry without them, below); only a verdict built
    # in code, the stills step's fakes written before the questions, may leave them out.
    # `fixes` (2026-10-12) is asked only of a still whose scene was rewritten, and then the
    # report bound to its items requires every one (tests/test_fix_is_verified.py).
    assert all(
        field.is_required()
        for name, field in StillVerdict.model_fields.items()
        if name not in ("one_picture", "shows_scene", "fixes")
    )
    assert set(StillVerdict.model_fields) >= {
        "faces_visible",
        "readable_text",
        "one_picture",
        "shows_scene",
        "matches_plan",
        "look_ok",
        "technical_ok",
        "bible_violations",
        "verdict",
        "reason",
    }
    with pytest.raises(ValidationError):
        StillVerdict.model_validate({"scene": 1, "verdict": "buy_motion", "reason": "fine"})
    # A word is not an answer: "yes" and "true" in quotes are refused, not read as passes.
    good = json.loads(a_still_answer())["stills"][0]
    with pytest.raises(ValidationError):
        StillVerdict.model_validate({**good, "faces_visible": "no"})
    with pytest.raises(ValidationError):
        StillVerdict.model_validate({**good, "one_picture": "yes"})
    with pytest.raises(ValidationError):
        StillVerdict.model_validate({**good, "verdict": "looks fine"})
    # The model's answer must say whether the still is one picture.
    silent = {key: value for key, value in good.items() if key != "one_picture"}
    with pytest.raises(ValidationError):
        StillJudgeReport.model_validate({"stills": [silent]})
    assert StillJudgeReport.model_validate({"stills": [good]}).stills[0].one_picture is True
    # ... and whether it shows the scene, not only its prompt (2026-10-12, scene 5's rounds).
    mute = {key: value for key, value in good.items() if key != "shows_scene"}
    with pytest.raises(ValidationError):
        StillJudgeReport.model_validate({"stills": [mute]})
    assert StillJudgeReport.model_validate({"stills": [good]}).stills[0].shows_scene is True


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed")
@pytest.mark.parametrize(
    "answer",
    [
        json.dumps({"stills": []}),
        a_still_answer(scene=2),
        "I looked and it is lovely.",
        json.dumps(
            {
                "stills": [
                    {
                        key: value
                        for key, value in json.loads(a_still_answer())["stills"][0].items()
                        if key != "one_picture"
                    }
                ]
            }
        ),
    ],
    ids=["no-entry", "another-scene", "prose", "one-picture-unanswered"],
)
def test_judge_still_without_an_entry_for_this_still_is_not_run(engine, staffed, answer):
    from app.media.picture_qc import judge_still

    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    registry, _ = registry_with(staffed, lambda p: answer)

    judged = judge_still(engine, registry, NEPAL_STILL, still_plan(), str(uuid4()))

    assert judged.status == "NOT_RUN" and judged.verdict is None
    assert "nu a fost privită" in judged.detail_ro


def test_judge_still_with_nobody_who_can_see_is_not_run(engine, staffed):
    from app.media.picture_qc import judge_still

    registry, model = registry_with(staffed, lambda p: a_still_answer())

    judged = judge_still(engine, registry, NEPAL_STILL, still_plan(), str(uuid4()))
    unregistered = judge_still(engine, None, NEPAL_STILL, still_plan(), str(uuid4()))

    assert judged.status == "NOT_RUN" and "nu a fost privită" in judged.detail_ro
    assert unregistered.status == "NOT_RUN"
    assert model.calls == []


# ------------------------------------ the film's pictures, three frames a scene at 1080 px
#
# The film-level look used to be one 480 px frame from the middle of each scene. A scene is
# judged now as a bought clip is (picture_qc.judge_clip): its first, middle and last frame on
# the film's own timeline, at the delivered 1080 px, with YuNet counting faces on each frame
# when the bible forbids faces. Composed cards are drawn by the studio and are not judged as
# photographs. Every model and the detector are faked here; ffmpeg cuts a real film.

requires_ffmpeg = pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed"
)
NO_FACES_BIBLE = {"people_rule": "No human faces appear; people only from behind."}


def _png_width(path) -> int:
    data = open(path, "rb").read(32)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big")


def _span_film(tmp_path):
    """Five seconds at 24 fps, 1080x1920: four seconds of picture, one of black."""
    import shutil
    import subprocess

    out = tmp_path / "film.mp4"
    result = subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1080x1920:r=24:d=4",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:r=24:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    return out


#: The 2026-10-09 triptych (tests/fixtures/panels, test_still_gate's docstring): a tunnel with
#: a glowing atom, a flat black band, an empty tunnel.
TRIPTYCH = NEPAL_STILL.parents[1] / "panels" / "scene_05_c7c55abb_c1.jpg"


def _panel_film(tmp_path):
    """_span_film's shape, its first LIVE scene the triptych: 2 s of the panels, 2 s of a test
    card, 1 s of black, at 24 fps, 1080x1920."""
    import shutil
    import subprocess

    out = tmp_path / "panel_film.mp4"
    result = subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "24",
            "-t",
            "2",
            "-i",
            str(TRIPTYCH),
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1080x1920:r=24:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:r=24:d=1",
            "-filter_complex",
            "[0:v]scale=1080:1920:flags=lanczos,fps=24,format=yuv420p,setsar=1[a];"
            "[1:v]format=yuv420p,setsar=1[b];[2:v]format=yuv420p,setsar=1[c];"
            "[a][b][c]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    return out


def _spanned_film(engine, tmp_path, *, bible=None, film=None):
    """a_film's three scenes on a real file: two LIVE scenes of 2 s and a 1 s black card."""
    ids = a_film(engine)
    film = film or _span_film(tmp_path)
    spans = [
        {"scene_index": 1, "start": 0.0, "end": 2.0, "dissolve_seconds": 0.0, "composed": False},
        {"scene_index": 2, "start": 2.0, "end": 4.0, "dissolve_seconds": 0.0, "composed": False},
        {"scene_index": 3, "start": 4.0, "end": 5.0, "dissolve_seconds": 0.0, "composed": True},
    ]
    with Session(engine) as session, session.begin():
        session.get(MediaAsset, ids["asset"]).uri_or_path = str(film)
        session.get(VideoRenderJob, ids["job"]).production_json = {
            "scenes": [
                {"scene_index": 1, "scene_kind": "LIVE", "audio_seconds": 1.8},
                {"scene_index": 2, "scene_kind": "LIVE", "audio_seconds": 1.8},
                {"scene_index": 3, "scene_kind": "BLACK", "audio_seconds": 0.0},
            ],
            "timeline": {"fps": 24, "spans": spans},
        }
        session.get(Storyboard, ids["board"]).visual_bible_json = bible or {}
        card = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == ids["board"], StoryboardScene.scene_index == 3
            )
        ).one()
        card.scene_kind = "BLACK"
    return ids


def _keep(scene, **changes):
    from app.media.picture_qc import ClipJudgement, ClipVerdict

    fields = {
        "scene": scene,
        "faces_visible": False,
        "readable_text": False,
        "matches_plan": True,
        "shows_scene": True,
        "look_ok": True,
        "technical_ok": True,
        "same_shot": True,
        "one_picture": True,
        "bible_violations": "none",
        "verdict": "keep",
        "reason": "the mirror against the dark",
    }
    fields.update(changes)
    return ClipJudgement(
        status="MEASURED",
        verdict=ClipVerdict(**fields),
        detail_ro="privit",
        run_id="run",
        looked_by="Video Editor",
        image_width=1080,
        frames=3,
    )


class _Judge:
    def __init__(self, answer=None):
        self.calls: list[tuple[int, list]] = []
        self.answer = answer or (lambda scene: _keep(scene))

    def __call__(self, paths, plan):
        # The frames live only while the check runs: their widths are read as they arrive.
        self.calls.append((plan.scene, [_png_width(p) for p in paths]))
        return self.answer(plan.scene)


class _Faces:
    def __init__(self, faces=None, status="MEASURED"):
        self.seen: list[str] = []
        self.faces = faces or {}
        self.status = status

    def __call__(self, path, **_):
        from app.media.faces import FaceCount

        self.seen.append(str(path))
        if self.status != "MEASURED":
            return FaceCount(status="NOT_RUN", faces=None, boxes=(), detail_ro="YuNet lipsește")
        found = next((n for key, n in self.faces.items() if key in str(path)), 0)
        return FaceCount(status="MEASURED", faces=found, boxes=(), detail_ro="numărat")


@requires_ffmpeg
def test_frames_at_cuts_the_frames_asked_for_at_the_delivered_1080_px(tmp_path):
    from app.agents.vision import frames_at

    film = _span_film(tmp_path)
    frames = frames_at(str(film), None, [0, 47, 96], tmp_path / "cut")
    assert sorted(frames) == [0, 47, 96]
    assert all(_png_width(path) == 1080 for path in frames.values())
    # The black second is black and the test card is not: the frames are the ones asked for.
    assert frames[96].stat().st_size < frames[0].stat().st_size
    assert frames_at(str(tmp_path / "missing.mp4"), None, [0], tmp_path / "cut") == {}
    assert frames_at(str(film), None, [], tmp_path / "cut") == {}


@requires_ffmpeg
def test_each_live_scene_is_judged_on_its_first_middle_and_last_frame(engine, staffed, tmp_path):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)
    judge, faces = _Judge(), _Faces()

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=faces
    )

    assert record["status"] == "MEASURED" and record["passed"] is True, record
    assert record["failures"] == []
    # One look per LIVE scene, three frames each; the black card is never sent.
    assert [scene for scene, _ in judge.calls] == [1, 2]
    assert [widths for _, widths in judge.calls] == [[1080] * 3] * 2
    assert len(faces.seen) == 6
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    times = [frame["time"] for frame in scenes[2]["frames"]]
    assert [frame["at"] for frame in scenes[2]["frames"]] == ["first", "middle", "last"]
    assert times[0] == pytest.approx(2.0, abs=0.05)
    assert times[1] == pytest.approx(3.0, abs=0.05)
    assert 3.9 <= times[2] < 4.0
    assert scenes[3]["kind"] == "BLACK" and scenes[3]["status"] == "NOT_APPLICABLE"
    assert scenes[3]["passed"] is None
    assert record["frame_width"] == 1080


@pytest.mark.parametrize("fps", [12.0, 24.0, 30.0, 60.0, 24000 / 1001, 30000 / 1001])
@pytest.mark.parametrize("cut_frame", [1, 2, 17, 65, 736])
def test_rounded_timeline_cut_keeps_each_frame_in_its_own_scene(fps, cut_frame):
    from app.media.qc import span_frame_numbers

    # The assembler persists seconds at six decimal places, including the cyclotron's
    # 736 / 24 boundary (30.666667). The cut frame starts the next scene, never the last.
    cut = round(cut_frame / fps, 6)
    before = dict(span_frame_numbers(0, cut, fps))
    after = dict(span_frame_numbers(cut, round((cut_frame + 24) / fps, 6), fps))

    assert before["last"] == cut_frame - 1
    assert after["first"] == cut_frame


def test_rounded_dissolve_ends_on_its_own_frame_without_moving_a_real_partial_frame():
    from app.media.qc import span_frame_numbers

    # Both recorded times can round up; together they still name exactly frame 738.
    assert dict(span_frame_numbers(30.666667, 32, 24, 0.083333))["first"] == 738
    assert dict(span_frame_numbers(30.666667, 32, 24, 0.166667))["first"] == 740
    # An actual fractional frame is not snapped to the previous frame.
    assert dict(span_frame_numbers(1.001, 2.001, 24))["first"] == 25
    assert dict(span_frame_numbers(1.001, 2.001, 24))["last"] == 48


@requires_ffmpeg
def test_span_qc_never_shows_the_next_scenes_picture_at_a_rounded_cut(engine, staffed, tmp_path):
    import shutil
    import subprocess

    from app.media.qc import span_picture_qc
    from PIL import Image

    film = tmp_path / "rounded_cut.mp4"
    rendered = subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=1080x1920:r=24:d=0.666667",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1080x1920:r=24:d=1",
            "-filter_complex",
            "[0:v]trim=end_frame=16,setpts=PTS-STARTPTS[a];"
            "[1:v]trim=end_frame=23,setpts=PTS-STARTPTS[b];"
            "[a][b]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(film),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr[-1500:]
    ids = _spanned_film(engine, tmp_path, film=film)
    with Session(engine) as session, session.begin():
        job = session.get(VideoRenderJob, ids["job"])
        production = dict(job.production_json)
        production["timeline"] = {
            "fps": 24,
            "spans": [
                {"scene_index": 1, "start": 0.0, "end": 0.666667},
                {"scene_index": 2, "start": 0.666667, "end": 1.625},
            ],
        }
        job.production_json = production
    shown: dict[int, list[str]] = {}

    def judge(paths, plan):
        colours = []
        for path in paths:
            with Image.open(path) as image:
                red, _, blue = image.convert("RGB").getpixel((540, 960))
            colours.append("red" if red > blue else "blue")
        shown[plan.scene] = colours
        return _keep(plan.scene)

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()), judge=judge)

    assert shown == {1: ["red"] * 3, 2: ["blue"] * 3}
    scene_frames = {
        row["scene_index"]: {item["at"]: item["frame"] for item in row["frames"]}
        for row in record["scenes"]
    }
    assert scene_frames[1]["last"] == 15
    assert scene_frames[2]["first"] == 16


@requires_ffmpeg
def test_a_face_yunet_finds_on_any_of_the_three_frames_fails_the_film(engine, staffed, tmp_path):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)

    record = span_picture_qc(
        engine,
        None,
        ids["asset"],
        str(uuid4()),
        judge=_Judge(),
        face_counter=_Faces({"scene_02_middle": 1}),
    )

    assert record["passed"] is False
    assert len(record["failures"]) == 1
    assert "Scena 2" in record["failures"][0] and "YuNet" in record["failures"][0]
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["passed"] is True and scenes[2]["passed"] is False


@requires_ffmpeg
def test_what_the_look_refuses_fails_the_film_and_names_the_scene(engine, staffed, tmp_path):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)
    judge = _Judge(
        lambda scene: (
            _keep(scene, faces_visible=True, reason="a woman faces the camera")
            if scene == 1
            else _keep(scene)
        )
    )

    record = span_picture_qc(
        engine, None, ids["asset"], str(uuid4()), judge=judge, face_counter=_Faces()
    )

    assert record["passed"] is False
    assert any("Scena 1" in f and "față" in f for f in record["failures"]), record["failures"]
    assert not any("Scena 2" in f for f in record["failures"])


@requires_ffmpeg
def test_a_look_that_did_not_happen_certifies_nothing_and_fails_nothing(engine, staffed, tmp_path):
    from app.media.picture_qc import ClipJudgement
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path)
    unseen = _Judge(
        lambda scene: ClipJudgement(
            status="NOT_RUN",
            verdict=None,
            detail_ro="clipul nu a fost privit: niciun angajat nu are un model care vede",
            run_id=None,
            looked_by=None,
            image_width=None,
            frames=0,
        )
    )

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()), judge=unseen)

    assert record["passed"] is None and record["failures"] == []
    assert all(entry["passed"] is None for entry in record["scenes"])


def test_with_no_film_on_disk_no_frame_is_cut(engine, staffed, monkeypatch):
    from app.media.qc import span_picture_qc

    ids = a_film(engine)

    def refuse(*args, **kwargs):
        raise AssertionError("no frame should be cut from a film that is not on disk")

    monkeypatch.setattr("app.media.qc.frames_at", refuse)
    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()))
    assert record["status"] == "NOT_APPLICABLE" and record["passed"] is None
    assert "nu este pe disc" in record["detail"]


@requires_ffmpeg
def test_with_nobody_to_look_and_faces_allowed_the_band_still_fails_a_panel_scene(
    engine, staffed, tmp_path
):
    """Review of 2026-10-09: with no model that can see and a bible that allows faces, the
    span check stood down before cutting a frame, so the band, which is free, was never read
    on the film: the rehearsal's QC (registry None) and the Owner's re-QC could pass a film
    with the triptych in it. The band is read whoever looks."""
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, film=_panel_film(tmp_path))

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()))

    assert record["faces_forbidden"] is False
    assert record["status"] == "MEASURED" and record["passed"] is False, record
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["passed"] is False and scenes[1]["panels"]["status"] == "FAILED"
    assert "nu e o singură fotografie" in scenes[1]["reason"]
    # The scene with no band was read, not looked at: it certifies nothing.
    assert scenes[2]["passed"] is None and scenes[2]["status"] == "NOT_RUN"
    assert scenes[2]["panels"]["status"] == "PASSED"
    assert scenes[2]["picture"]["status"] == "NOT_RUN"
    (failure,) = record["failures"]
    assert failure.startswith("Scena 1:")
    assert "nimeni nu se uită" in record["detail"] and "banda plată" in record["detail"]


@requires_ffmpeg
def test_with_nobody_to_look_a_film_without_panels_is_read_and_certifies_nothing(
    engine, staffed, tmp_path
):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path)

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()))

    assert record["passed"] is None and record["failures"] == []
    filmed = [entry for entry in record["scenes"] if entry["kind"] == "LIVE"]
    assert len(filmed) == 2
    assert all(entry["panels"]["status"] == "PASSED" for entry in filmed)
    assert all(entry["passed"] is None for entry in filmed)


@requires_ffmpeg
def test_quality_control_without_a_seeing_model_fails_a_panel_scene_and_asks_for_still_and_motion(
    engine, staffed, tmp_path
):
    """The rehearsal's own QC: evaluate_media_qc with no registry and no judge of its own."""
    ids = _spanned_film(engine, tmp_path, film=_panel_film(tmp_path))

    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()))

    assert report["status"] == "FAILED"
    assert report["checks_json"]["picture_spans_qc"]["passed"] is False
    assert report["checks_json"]["picture_qc"]["passed"] is None
    assert _scene_redos(report) == {1: {"still", "motion"}}


@requires_ffmpeg
def test_a_face_count_that_could_not_run_blocks_in_production_and_warns_in_test(
    engine, staffed, tmp_path
):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)
    seen = {}
    for environment in ("TEST", "PRODUCTION"):
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1).environment = environment
        seen[environment] = span_picture_qc(
            engine,
            None,
            ids["asset"],
            str(uuid4()),
            judge=_Judge(),
            face_counter=_Faces(status="NOT_RUN"),
        )
    assert seen["PRODUCTION"]["passed"] is False
    assert any("Scena 1" in f for f in seen["PRODUCTION"]["failures"])
    assert seen["TEST"]["passed"] is None and seen["TEST"]["failures"] == []
    assert any("Scena 1" in w for w in seen["TEST"]["warnings"])


@requires_ffmpeg
def test_the_studios_own_judge_is_one_vision_call_per_live_scene(engine, staffed, tmp_path):
    import base64
    import re

    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)

    def answer(prompt):
        scene = int(re.search(r"for scene (\d+)", prompt).group(1))
        verdict = _keep(scene).verdict
        return json.dumps({"clips": [verdict.model_dump()]})

    registry, model = registry_with(staffed, answer)

    record = span_picture_qc(engine, registry, ids["asset"], str(uuid4()), face_counter=_Faces())

    assert record["passed"] is True, record
    assert len(model.calls) == 2
    for call in model.calls:
        images = call["extra"]["images"]
        assert len(images) == 3
        assert _jpeg_size(base64.b64decode(images[0])) == (1080, 1920)
        assert "No human faces appear" in call["prompt"]


@requires_ffmpeg
def test_finished_span_judge_receives_motion_ending_and_keeps_visual_rules(
    engine, staffed, tmp_path
):
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)
    give_vision(engine, staffed["agents"]["VideoEditor"].id)
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == ids["board"], StoryboardScene.scene_index == 1
            )
        )
        scene.prompt_json = {
            "still_prompt": "A pencil spiral on a cream napkin.",
            "motion_prompt": "A faint glowing trail rises from the pencil spiral.",
            "ending_frame": "The trail has risen; the napkin remains flat.",
        }

    def answer(prompt):
        import re

        scene = int(re.search(r"for scene (\d+)", prompt).group(1))
        return json.dumps({"clips": [_keep(scene).verdict.model_dump()]})

    registry, model = registry_with(staffed, answer)
    span_picture_qc(engine, registry, ids["asset"], str(uuid4()), face_counter=_Faces())

    prompt = model.calls[0]["prompt"]
    assert "A faint glowing trail rises from the pencil spiral." in prompt
    assert "The trail has risen; the napkin remains flat." in prompt
    assert "Explicitly requested motion or effects are not unrequested additions" in prompt
    assert "No human faces appear" in prompt
    assert '"faces_forbidden": true' in prompt


@requires_ffmpeg
def test_quality_control_fails_a_film_with_a_face_in_a_scene_and_keeps_the_one_frame_look(
    engine, staffed, tmp_path
):
    ids = _spanned_film(engine, tmp_path, bible=NO_FACES_BIBLE)

    report = evaluate_media_qc(
        engine,
        ids["asset"],
        str(uuid4()),
        span_judge=_Judge(),
        face_counter=_Faces({"scene_01_last": 2}),
    )

    spans = report["checks_json"]["picture_spans_qc"]
    assert spans["passed"] is False
    assert report["status"] == "FAILED"
    assert any("Scena 1" in r and "YuNet" in r for r in report["failure_reasons_json"])
    # The film-wide look and the character check are still the picture_qc they were.
    assert report["checks_json"]["picture_qc"]["status"] == "NOT_APPLICABLE"


# ------------------------------------------------------ one picture, not panels, in the film
#
# 2026-10-09: scene 5 of «The Particle That Shouldn't Exist (But Does)» was three stacked
# panels, its clip animated them, and every check passed it. The film's own QC reads each
# filmed scene's three frames for a flat band (qc.flat_band) and asks the look whether each is
# ONE picture; a scene made of panels fails, and the studio's own report asks for a new still
# and new motion for that scene, nothing else.


def _scene_redos(report) -> dict[int, set[str]]:
    from app.media.qc_report import redo_proposals

    redos: dict[int, set[str]] = {}
    for proposal in redo_proposals(report):
        if proposal.scene_index is not None:
            redos.setdefault(proposal.scene_index, set()).add(proposal.redo)
    return redos


@requires_ffmpeg
def test_a_scene_made_of_panels_fails_the_span_check_on_the_band_alone(engine, staffed, tmp_path):
    """The look is the lenient one of 2026-10-09: it keeps everything. The band does not."""
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path, film=_panel_film(tmp_path))

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()), judge=_Judge())

    assert record["status"] == "MEASURED" and record["passed"] is False
    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    panel, card = scenes[1], scenes[2]
    assert panel["passed"] is False and panel["panels"]["status"] == "FAILED"
    assert "nu e o singură fotografie" in panel["reason"] and "la mijloc" in panel["reason"]
    assert all(frame["splits_the_picture"] for frame in panel["panels"]["frames"])
    assert card["passed"] is True and card["panels"]["status"] == "PASSED"
    (failure,) = record["failures"]
    assert failure.startswith("Scena 1:")


@requires_ffmpeg
def test_quality_control_fails_a_panel_scene_and_the_studio_asks_for_a_new_still_and_motion(
    engine, staffed, tmp_path
):
    ids = _spanned_film(engine, tmp_path, film=_panel_film(tmp_path))

    report = evaluate_media_qc(
        engine, ids["asset"], str(uuid4()), span_judge=_Judge(), face_counter=_Faces()
    )

    assert report["status"] == "FAILED"
    assert report["checks_json"]["picture_spans_qc"]["passed"] is False
    assert any(
        "Scena 1" in reason and "singură fotografie" in reason
        for reason in report["failure_reasons_json"]
    ), report["failure_reasons_json"]
    # The studio's own redo: a new still and new motion for scene 1, and nothing for the
    # scene that passed. Never the whole film.
    assert _scene_redos(report) == {1: {"still", "motion"}}


@requires_ffmpeg
def test_panels_the_band_cannot_see_fail_the_scene_on_the_looks_one_picture(
    engine, staffed, tmp_path
):
    """scene_05_0d900cbd_c2 was three tunnels stacked with no band between them: the look's
    one_picture is its net, on the film as on the still."""
    from app.media.qc import span_picture_qc

    ids = _spanned_film(engine, tmp_path)
    judge = _Judge(
        lambda scene: (
            _keep(
                scene,
                one_picture=False,
                verdict="back_to_still",
                reason="three tunnels stacked one above another",
            )
            if scene == 2
            else _keep(scene)
        )
    )

    record = span_picture_qc(engine, None, ids["asset"], str(uuid4()), judge=judge)

    scenes = {entry["scene_index"]: entry for entry in record["scenes"]}
    assert scenes[1]["passed"] is True
    assert scenes[2]["passed"] is False and scenes[2]["panels"]["status"] == "PASSED"
    assert "nu sunt o singură fotografie" in scenes[2]["reason"]
    assert "three tunnels" in scenes[2]["reason"]
    assert _scene_redos({"checks_json": {"picture_spans_qc": record}}) == {2: {"still", "motion"}}
