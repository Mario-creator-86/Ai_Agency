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


def all_good(scenes=3, characters=()):
    return json.dumps(
        {
            "scenes": [
                {"scene": i, "is_a_picture": True, "shows_the_scene": True, "reason": "as asked"}
                for i in range(1, scenes + 1)
            ],
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
                {"scene": 1, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                {"scene": 2, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                {
                    "scene": 3,
                    "is_a_picture": False,
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
            "scenes": [
                {"scene": i, "is_a_picture": True, "shows_the_scene": True, "reason": ""}
                for i in (1, 2, 3)
            ],
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
                    {"scene": 1, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {"scene": 2, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {
                        "scene": 3,
                        "is_a_picture": False,
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
                    {"scene": 1, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {"scene": 2, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {
                        "scene": 3,
                        "is_a_picture": False,
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
                    {"scene": 1, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {"scene": 2, "is_a_picture": True, "shows_the_scene": True, "reason": ""},
                    {
                        "scene": 3,
                        "is_a_picture": False,
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
            "scenes": [
                {"scene": i, "is_a_picture": True, "shows_the_scene": True, "reason": "as asked"}
                for i in (1, 2)
            ],
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
        "matches_plan": True,
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
    with Session(engine) as session:
        runs = list(session.scalars(select(AgentRun).where(AgentRun.task_type == STILL_TASK)))
    assert len(runs) == 1 and judged.run_id == runs[0].id


def test_the_still_verdict_has_no_field_that_passes_by_default():
    from app.media.picture_qc import StillVerdict
    from pydantic import ValidationError

    assert all(field.is_required() for field in StillVerdict.model_fields.values())
    assert set(StillVerdict.model_fields) >= {
        "faces_visible",
        "readable_text",
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
        StillVerdict.model_validate({**good, "verdict": "looks fine"})


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg is not installed")
@pytest.mark.parametrize(
    "answer",
    [
        json.dumps({"stills": []}),
        a_still_answer(scene=2),
        "I looked and it is lovely.",
    ],
    ids=["no-entry", "another-scene", "prose"],
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
