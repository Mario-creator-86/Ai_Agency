"""Every paid picture is a take, and a take is never bought twice.

The Nepal film cost two full films: the second render bought every still and every clip again,
with the same prompts, because nothing recorded that they were paid. And two of its six scenes
(a bar chart and a black screen) went to a photographic model and came back as women.

What is asserted here, with every provider faked (spy adapters that count their calls):
  - a Nepal-shaped film (four LIVE scenes, a DATA_CARD, a BLACK) asks the image model four
    times and the video model four times; the two card scenes are composed locally, 0 credits,
    provenance 'composed', and no adapter ever sees them;
  - the stills step (`buy_stills`) buys each LIVE still once; once approved, `assemble_from_takes`
    asks no image model at all, and a second stills run with the same prompts buys nothing;
  - a second render of the same film buys no still and no clip again;
  - a vendor's 400 with its per-field complaint (issues[{path: 'ratio'}]) is kept on the take;
  - each scene carries scene_category = its kind and its story purpose to the model router,
    and the model's outcome is recorded under that kind.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.integrations.models import ModelOutcome
from app.media.assembler import (
    TakesMissing,
    assemble_from_takes,
    assemble_video_job,
    buy_stills,
)
from app.media.models import SceneTake, StoryboardScene, VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.providers.media_base import ImageResult, VideoGenerationResult
from app.providers.media_http import MediaProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_motion import a_clip
from test_phase5_media import _seeded_storyboard

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

FIXTURES = Path(__file__).parent / "fixtures" / "factual_sample"

#: The Nepal film's six scenes, as the new writer marks them.
NEPAL = [
    ("LIVE", "HOOK", "Aerial view of Himalayan ridges under grey storm clouds, a far village."),
    ("LIVE", "SETUP", "Brown floodwater running through a mountain valley, seen from high above."),
    ("LIVE", "EVIDENCE", "Terraced farmland covered by a mudslide, figures small and distant."),
    ("LIVE", "REVEAL", "A terraced field at dusk, a distant forest, a farmer seen from behind."),
    ("DATA_CARD", "ENDING", "Two vertical bars side by side: the first fills to the top."),
    ("BLACK", "CTA", "A black screen, silent and still."),
]

NEPAL_CARD = {
    "title": "Finanțare climatică pe an",
    "bars": [
        {"label": "Promis", "value": 100, "unit": "mld. USD", "claim_id": "00000196"},
        {"label": "Livrat", "value": 83, "unit": "mld. USD", "claim_id": "000001aa"},
    ],
    "highlight": "Livrat",
}


def nepal_like(engine, tmp_path: Path, kinds: list[tuple[str, str, str]] | None = None) -> str:
    """A storyboard shaped like the Nepal film: its kinds, purposes and pictures."""
    plan = kinds or NEPAL
    storyboard_id, _claim = _seeded_storyboard(engine, tmp_path, scenes=len(plan))
    with Session(engine) as session, session.begin():
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        for row, (kind, purpose, picture) in zip(rows, plan, strict=True):
            row.scene_kind = kind
            row.visual_type = kind
            row.story_purpose = purpose
            row.visual_prompt = picture
            row.duration_seconds = 2.0
            row.voiceover_segment = f"Scene {row.scene_index}."
            row.card_json = dict(NEPAL_CARD) if kind == "DATA_CARD" else None
    return storyboard_id


class SpyImages:
    """The image vendor, faked: hands back the Nepal stills in turn and counts every call."""

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "seedream5_pro"
    integration_id = "conn-test"

    def __init__(self, fail: MediaProviderError | None = None):
        self.asked: list[dict] = []
        self.fail = fail

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def generate_image(self, prompt, **kwargs):
        extra = kwargs.get("extra") or {}
        self.asked.append({"prompt": prompt, "scene_index": extra.get("scene_index")})
        if self.fail is not None:
            raise self.fail
        picture = FIXTURES / f"scene_{(len(self.asked) - 1) % 4 + 1:02d}.jpg"
        return ImageResult(
            image_bytes=picture.read_bytes(),
            format="jpeg",
            width=540,
            height=960,
            prompt=prompt,
        )


class SpyMotion:
    """The video vendor, faked: one tiny real clip per shot, or the failure it is told to give."""

    PROVIDER_NAME = "TEST_VIDEO_PROVIDER"
    model = "seedance2_5"

    def __init__(self, clip: bytes, integration_id: str = "conn-test", fail=None):
        self.clip = clip
        self.integration_id = integration_id
        self.fail = fail
        self.asked: list[dict] = []

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def create_generation(
        self, prompt, *, image_ref=None, duration_seconds=4.0, aspect_ratio="9:16", extra=None
    ):
        self.asked.append({"prompt": prompt, "seconds": duration_seconds})
        if self.fail is not None:
            raise self.fail
        return f"task-{len(self.asked)}"

    async def get_generation_status(self, job_id):
        return VideoGenerationResult(
            job_id=job_id, status="COMPLETED", video_bytes=self.clip, raw_response={"task": job_id}
        )


def takes(engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake)
            .where(SceneTake.storyboard_id == storyboard_id)
            .order_by(SceneTake.scene_number, SceneTake.kind, SceneTake.created_at)
        ).all()
        session.expunge_all()
        return list(rows)


def approve_stills(engine, storyboard_id: str) -> None:
    """The Owner's verdict on the contact sheet, as the sheet will write it."""
    with Session(engine) as session, session.begin():
        for take in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "still"
            )
        ):
            if take.status == "PAID":
                take.status = "APPROVED"
                take.approved_by = "owner"


# ------------------------------------------------------------ 1. cards never reach a model


@requires_ffmpeg
def test_a_nepal_shaped_film_asks_for_four_stills_and_composes_the_chart_and_the_black(
    engine, tmp_path
):
    storyboard_id = nepal_like(engine, tmp_path)
    images = SpyImages()
    motion = SpyMotion(a_clip(tmp_path))

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=images,
        video_adapter_for_scene=lambda scene: motion,
    )

    # Four LIVE scenes, four stills, four clips: never six.
    assert [call["scene_index"] for call in images.asked] == [1, 2, 3, 4]
    assert len(motion.asked) == 4
    assert not any(
        "bars" in call["prompt"] or "black screen" in call["prompt"].lower()
        for call in images.asked + motion.asked
    )

    production = render["production"]
    by_scene = {entry["scene_index"]: entry for entry in production["scenes"]}
    for index, kind in ((5, "DATA_CARD"), (6, "BLACK")):
        card = by_scene[index]["card"]
        assert card["provenance"] == "composed" and card["credits"] == 0
        assert card["kind"] == kind and len(card["sha256"]) == 64
        assert Path(card["path"]).is_file()
        assert by_scene[index]["image"] is None and "motion" not in by_scene[index]
    assert production["motion"]["composed_scenes"] == 2
    assert production["motion"]["fallback_scenes"] == 0
    assert production["motion"]["clips"] == 4

    # Every paid picture is a take; a composed card is not.
    rows = takes(engine, storyboard_id)
    assert sorted((t.scene_number, t.kind, t.status) for t in rows) == sorted(
        [(n, "still", "PAID") for n in (1, 2, 3, 4)] + [(n, "motion", "PAID") for n in (1, 2, 3, 4)]
    )
    for take in rows:
        assert take.path and Path(take.path).is_file() and len(take.sha256 or "") == 64
        assert len(take.prompt_hash) == 64
    assert {t.model_id for t in rows if t.kind == "still"} == {"seedream5_pro"}
    assert {t.model_id for t in rows if t.kind == "motion"} == {"seedance2_5"}


@requires_ffmpeg
def test_a_second_render_of_the_same_film_buys_no_still_and_no_clip_again(engine, tmp_path):
    """The Nepal waste, replayed: the second render re-bought every scene with the same prompts."""
    storyboard_id = nepal_like(engine, tmp_path)
    clip = a_clip(tmp_path)
    first_images, first_motion = SpyImages(), SpyMotion(clip)
    assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=first_images,
        video_adapter_for_scene=lambda scene: first_motion,
    )
    assert (len(first_images.asked), len(first_motion.asked)) == (4, 4)

    again_images, again_motion = SpyImages(), SpyMotion(clip)
    second = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media_again",
        image_adapter=again_images,
        video_adapter_for_scene=lambda scene: again_motion,
    )
    assert again_images.asked == [] and again_motion.asked == []
    assert second["production"]["motion"]["clips"] == 4
    scenes = {entry["scene_index"]: entry for entry in second["production"]["scenes"]}
    assert all(scenes[n]["still_take"]["reused"] for n in (1, 2, 3, 4))
    assert all(scenes[n]["motion"]["reused_take"] for n in (1, 2, 3, 4))
    # Nothing new was bought, so nothing new is a take.
    assert len(takes(engine, storyboard_id)) == 8


# ------------------------------------------------------- 2. stills first, then the takes


@requires_ffmpeg
def test_approved_stills_are_assembled_without_a_single_image_call(engine, tmp_path):
    storyboard_id = nepal_like(engine, tmp_path)
    images = SpyImages()

    bought = buy_stills(
        engine, storyboard_id, str(uuid4()), image_chain=[images], storage_root=tmp_path / "media"
    )
    assert [call["scene_index"] for call in images.asked] == [1, 2, 3, 4]
    assert (bought["bought"], bought["reused"], bought["composed"]) == (4, 0, 2)
    kinds = {entry["scene_index"]: entry["status"] for entry in bought["scenes"]}
    assert kinds == {n: "bought" for n in (1, 2, 3, 4)} | {5: "composed", 6: "composed"}

    # Nothing is assembled from stills nobody has looked at.
    with pytest.raises(TakesMissing, match="Scena 1"):
        assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            image_adapter=images,
        )
    assert len(images.asked) == 4
    with Session(engine) as session:
        assert session.scalars(select(VideoRenderJob)).all() == []

    approve_stills(engine, storyboard_id)
    # No shot was bought: every LIVE scene is a pushed still, which only a TEST film may be
    # without the Owner's LOCAL_MOVE (test_clip_qc_wiring.py holds PRODUCTION to it).
    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=images,
        environment="TEST",
    )
    assert len(images.asked) == 4, "assembling approved takes asked the image model again"
    assert Path(film["file_path"]).is_file()
    assert film["visual_source"] != "PLACEHOLDER_DETERMINISTIC_VISUALS"
    scenes = {entry["scene_index"]: entry for entry in film["production"]["scenes"]}
    assert all(scenes[n]["still_take"]["status"] == "APPROVED" for n in (1, 2, 3, 4))

    # The stills step run again with the same prompts buys nothing.
    again = buy_stills(
        engine, storyboard_id, str(uuid4()), image_chain=[images], storage_root=tmp_path / "media"
    )
    assert len(images.asked) == 4
    assert (again["bought"], again["reused"]) == (0, 4)

    # A changed prompt is a new picture, and only that scene is bought.
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        ).one()
        row.visual_prompt = "Brown floodwater in a valley, seen from a ridge, soft overcast light."
    changed = buy_stills(
        engine, storyboard_id, str(uuid4()), image_chain=[images], storage_root=tmp_path / "media"
    )
    assert [call["scene_index"] for call in images.asked[4:]] == [2]
    assert (changed["bought"], changed["reused"]) == (1, 3)


# ------------------------------------------------------------ 3. a vendor's 400 is kept


def _refusal() -> MediaProviderError:
    return MediaProviderError(
        "api.dev.runwayml.com refused the request (HTTP 400)",
        http_status=400,
        detail="Validation of body failed",
        issues=[{"path": "ratio", "message": "Invalid enum value. Expected '720:1280'"}],
    )


def test_a_refused_still_keeps_the_vendors_reason_on_its_take(engine, tmp_path):
    storyboard_id = nepal_like(engine, tmp_path, NEPAL[:1] + NEPAL[4:5])
    images = SpyImages(fail=_refusal())

    result = buy_stills(
        engine, storyboard_id, str(uuid4()), image_chain=[images], storage_root=tmp_path / "media"
    )

    assert len(images.asked) == 1
    assert result["refused"] == 1 and result["scenes"][0]["status"] == "refused"
    (take,) = takes(engine, storyboard_id)
    assert (take.scene_number, take.kind, take.status) == (1, "still", "REFUSED")
    assert take.failure_code == "HTTP_400"
    assert "ratio" in take.failure_detail and "Invalid enum value" in take.failure_detail
    assert "Validation of body failed" in take.failure_detail
    assert len(take.failure_detail) <= 500 and take.sha256 is None and take.path is None


@requires_ffmpeg
def test_a_refused_clip_keeps_the_vendors_reason_on_its_take(engine, tmp_path):
    storyboard_id = nepal_like(engine, tmp_path, NEPAL[:1] + NEPAL[5:6])
    motion = SpyMotion(a_clip(tmp_path), fail=_refusal())

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=SpyImages(),
        video_adapter_for_scene=lambda scene: motion,
        # The refused scene is a pushed still: a TEST film (PRODUCTION refuses it).
        environment="TEST",
    )

    refused = [t for t in takes(engine, storyboard_id) if t.kind == "motion"]
    assert [(t.scene_number, t.status, t.failure_code) for t in refused] == [
        (1, "REFUSED", "HTTP_400")
    ]
    assert "ratio: Invalid enum value" in refused[0].failure_detail
    record = render["production"]["scenes"][0]["motion"]
    assert record["failure_kind"] == "CONTRACT"
    assert "ratio" in record["failure_detail"]


# --------------------------------------- 4. the scene's kind and purpose reach the router


@requires_ffmpeg
def test_the_router_and_the_outcome_see_each_scenes_kind_and_purpose(engine, tmp_path):
    from app.integrations.services import SaveIntegration, save
    from app.integrations.vault import CredentialVault

    connection = str(uuid4())
    save(
        engine,
        CredentialVault(tmp_path / "takes.credentials.key"),
        connection,
        SaveIntegration(kind="runway", name="Runway", config={}, secrets={"api_key": "k-test"}),
    )
    storyboard_id = nepal_like(engine, tmp_path, NEPAL[:2] + NEPAL[5:6])
    motion = SpyMotion(a_clip(tmp_path), integration_id=connection)
    asked: list[dict] = []

    def chooser(scene, tier, seconds, budget, exclude):
        asked.append({**scene, "tier": tier})
        return motion, {"model_id": motion.model, "reason": "spy"}

    render = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=SpyImages(),
        motion_chooser=chooser,
        environment="TEST",
    )

    # The BLACK scene is never offered to the router.
    assert [(s["scene_index"], s["scene_category"], s["story_purpose"]) for s in asked] == [
        (1, "LIVE", "HOOK"),
        (2, "LIVE", "SETUP"),
    ]
    assert asked[0]["scene_kind"] == "LIVE" and asked[0]["tier"] == "HERO"
    records = [s["motion"] for s in render["production"]["scenes"] if "motion" in s]
    assert [(r["scene_category"], r["story_purpose"]) for r in records] == [
        ("LIVE", "HOOK"),
        ("LIVE", "SETUP"),
    ]
    with Session(engine) as session:
        outcomes = session.scalars(select(ModelOutcome)).all()
        assert sorted(o.scene_category for o in outcomes) == ["LIVE", "LIVE"]
        assert all(o.accepted and o.remote_id == "seedance2_5" for o in outcomes)


def test_the_factory_router_is_told_the_kind_and_purpose_and_never_asked_for_a_card(
    engine, monkeypatch
):
    from app.media import factory, production_policy

    seen: list = []

    def choose(session, integration_id, requirement, **kwargs):
        seen.append(requirement)
        return {"model_id": "seedance2_5", "reason": "spy"}

    monkeypatch.setattr(factory, "_selected", lambda session, purpose: SimpleNamespace(id="c"))
    monkeypatch.setattr(production_policy, "choose_model", choose)
    monkeypatch.setattr(factory, "video_provider_for", lambda *a, **k: "adapter")
    vault = SimpleNamespace()

    adapter, decision = factory.motion_for_scene(
        engine,
        vault,
        {"scene_index": 1, "scene_kind": "LIVE", "scene_category": "LIVE", "story_purpose": "HOOK"},
        environment="PRODUCTION",
        tier="HERO",
        seconds=5.0,
    )
    assert adapter == "adapter"
    assert seen[0].scene_category == "LIVE"
    assert decision["scene_category"] == "LIVE" and decision["story_purpose"] == "HOOK"

    for kind in ("DATA_CARD", "TITLE_CARD", "BLACK"):
        adapter, decision = factory.motion_for_scene(
            engine,
            vault,
            {"scene_index": 5, "scene_kind": kind, "scene_category": kind},
            environment="PRODUCTION",
        )
        assert adapter is None and decision["model_id"] is None
        assert "compus" in decision["reason"]
    assert len(seen) == 1, "a card scene reached the model router"


def test_a_scene_purpose_decides_its_tier_when_no_role_is_stated():
    from app.media.assembler import scene_tier

    assert scene_tier({"scene_index": 1, "story_purpose": "HOOK"}, 6) == "HERO"
    assert scene_tier({"scene_index": 3, "story_purpose": "EVIDENCE"}, 6) == "STANDARD"
    # The last position is not a payoff when the writer said it is evidence.
    assert scene_tier({"scene_index": 6, "story_purpose": "EVIDENCE"}, 6) == "STANDARD"
    assert scene_tier({"scene_index": 4, "quality_tier": "HERO", "story_purpose": "SETUP"}, 6) == (
        "HERO"
    )
    # No purpose: the position decides, as before.
    assert scene_tier({"scene_index": 1}, 6) == "HERO"


def test_the_spies_are_the_only_vendors_here():
    """A guard on the guard: the fakes above never open a socket and never call a provider."""
    images = SpyImages()
    result = asyncio.run(images.generate_image("p", extra={"scene_index": 1}))
    assert result.format == "jpeg" and images.asked[0]["scene_index"] == 1
