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
