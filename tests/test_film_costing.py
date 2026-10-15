"""The motion step: one hero test shot kept in the film, then the rest, under a hard cap.

The Nepal film (2026-09-26) bought every clip twice, on five different models, with no price
shown and no question asked, and the studio's books recorded 0.74 USD of the 966 credits the
account lost. The motion step is the last, dearest stair of the money staircase:

- it buys only under the Owner's yes for its own step (``media.test_shot`` for the hero,
  ``media.motion_purchase`` for the rest), bound to the plan he was shown (the plan_hash);
- the hero test shot comes first and is kept in the film; the rest is bought only after the
  Owner has looked at it and approved its take;
- the cap binds inside the loop: before every POST, the credits committed plus that shot's
  price must stay within the approved cap (STOPPED_AT_CAP otherwise), and the account's
  balance is read before every shot (a free read) and the step halts below the shot's price;
- each scene keeps the model the sheet gave it (chosen per scene, cheapest capable, the
  Owner's decision of 2026-09-27): a failure moves no other scene and tries no other model in
  this step; SAFETY sends the scene's picture back to the stills gate; an account failure or
  two refused requests in a row stop the step; a technical failure is tried once more on the
  same model;
- the balance before and after the step is the measured price, written on the takes and as
  a MEASURED price on the model.

Every provider is faked: spy adapters count their calls and charge a fake account, which is
what the balance read sees. No socket is opened (conftest refuses them).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from app.media.assembler import (
    MotionStepRefused,
    decide_take,
    motion_plan,
    run_motion_step,
    still_fields,
    take_hash,
)
from app.media.cost_plan import price_shot
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.production_policy import ModelCapability
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from app.providers.media_base import VideoGenerationResult
from app.providers.media_http import MediaProviderError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_scene_takes import nepal_like
from test_stills_stage import BIBLE, LOOK, TAIL

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"

#: Six filmed scenes: (still subject, camera move, the world's motion). Sizes and moves vary,
#: so the lint finds no BLOCK and every refusal below is about the step, not the words.
SCENES = {
    1: (
        "A wide establishing view of steep Himalayan ridges and a far village of stone "
        "houses on a terraced slope, 24 mm lens, seen from high above.",
        "aerial drift forward",
        "Low grey cloud drifts slowly over the ridges.",
    ),
    2: (
        "A medium view of brown floodwater running through a narrow mountain valley, stones "
        "and broken trees in the current, 50 mm lens.",
        "slow pan right",
        "Brown water flows steadily through the valley.",
    ),
    3: (
        "A detail of wet terraced soil and young rice seedlings after rain, 85 mm lens, "
        "shallow depth of field.",
        "slow push-in",
        "Rain drips gently from the seedling leaves.",
    ),
    4: (
        "A wide view of an empty terraced field at dusk below a dark forest, 24 mm lens.",
        "tilt up",
        "Mist drifts slowly along the forest edge.",
    ),
    5: (
        "A medium view of a stone footbridge over a glacial river, 50 mm lens.",
        "slow pull-back",
        "The river flows steadily under the bridge.",
    ),
    6: (
        "A detail of cracked dry earth at the edge of a dried pond, 85 mm lens.",
        "slow pan left",
        "Dust drifts slowly in a light wind.",
    ),
}
#: A scene's planned narration; with the assembler's 0.4 s transition the shot is 5.0 s,
#: which seedance2_5 bills as 5 s at 68 credits: 340 credits a shot.
SECONDS = 4.6
SEEDANCE = ModelCapability(
    model_id="seedance2_5",
    quality=0.95,
    seconds={"min": 4, "max": 30},
    ratios=("1080:1920", "720:1280"),
    tasks=("image_to_video",),
)
VEO_FAST = ModelCapability(
    model_id="veo3.1_fast",
    quality=0.85,
    seconds={"values": [4, 6, 8]},
    ratios=("1080:1920", "720:1280"),
    tasks=("image_to_video",),
)


def still_prompt(scene: int) -> str:
    return f"{LOOK} {SCENES[scene][0]} {TAIL}"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def a_film(engine, tmp_path: Path, scenes: int = 6, kinds: list[str] | None = None) -> str:
    """A film of ``scenes`` scenes with compiled prompts and an APPROVED still per LIVE scene."""
    kinds = kinds or ["LIVE"] * scenes
    purposes = ["HOOK"] + ["EVIDENCE"] * (len(kinds) - 1)
    storyboard_id = nepal_like(
        engine,
        tmp_path,
        kinds=[
            (kind, purpose, still_prompt(n) if kind == "LIVE" else "A black screen.")
            for n, (kind, purpose) in enumerate(zip(kinds, purposes, strict=True), start=1)
        ],
    )
    stills = tmp_path / "approved_stills"
    stills.mkdir(exist_ok=True)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).visual_bible_json = dict(BIBLE)
        rows = session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ).all()
        for row in rows:
            n = int(row.scene_index)
            if row.scene_kind != "LIVE":
                row.prompt_json = {"scene_kind": row.scene_kind, "source": "model"}
                row.card_json = None if row.scene_kind != "BLACK" else {"cta": ""}
                continue
            _subject, move, world = SCENES[n]
            row.duration_seconds = SECONDS
            row.prompt_json = {
                "scene_kind": "LIVE",
                "source": "model",
                "still_prompt": still_prompt(n),
                "look_block": LOOK,
                "camera_move": move,
                "motion_intent": {
                    "camera_move": move,
                    "world": world,
                    "subject": "",
                    "faces_banned": True,
                    "people": False,
                },
            }
    for n in range(1, len(kinds) + 1):
        if kinds[n - 1] != "LIVE":
            continue
        copy = stills / f"{storyboard_id[:8]}_scene_{n:02d}.jpg"
        shutil.copyfile(FIXTURES / f"scene_{(n - 1) % 2 + 1:02d}.jpg", copy)
        # A different byte at the end, so every scene's still has its own sha256.
        copy.write_bytes(copy.read_bytes() + bytes([n]))
        with Session(engine) as session, session.begin():
            session.add(
                SceneTake(
                    id=str(uuid4()),
                    storyboard_id=storyboard_id,
                    scene_number=n,
                    kind="still",
                    prompt_hash=take_hash(still_fields(still_prompt(n), None), "seedream5_pro"),
                    model_id="seedream5_pro",
                    resolution="1530:2720",
                    status="APPROVED",
                    approved_by="owner",
                    path=str(copy),
                    sha256=sha(copy),
                    created_at="2026-10-01T10:00:00+00:00",
                    updated_at="2026-10-01T10:00:00+00:00",
                )
            )
    return storyboard_id


class Account:
    """The Runway account, faked: what a shot costs comes off it; the balance read sees it."""

    def __init__(self, balance: float, *, after_shot: dict[int, float] | None = None):
        self.balance = float(balance)
        self.after_shot = after_shot or {}
        self.shots = 0
        self.reads = 0

    async def credit_balance(self):
        self.reads += 1
        return self.balance

    def charge(self, credits: float) -> None:
        self.shots += 1
        self.balance -= credits
        if self.shots in self.after_shot:
            self.balance = self.after_shot[self.shots]


class SpyVideo:
    """One video model, faked. Counts every POST; ``refuse`` fails a POST (by call number),
    ``fail`` fails the task after it was created (and charged), as Runway does."""

    PROVIDER_NAME = "TEST_VIDEO_PROVIDER"
    integration_id = "conn-test"
    model_metadata = None

    def __init__(self, model: str, account: Account, clip: bytes | None = None, **script):
        self.model = model
        self.account = account
        self.clip = clip
        self.refuse: dict[int, MediaProviderError] = script.get("refuse", {})
        self.fail: dict[int, tuple[str | None, str]] = script.get("fail", {})
        self.asked: list[dict] = []
        self.last_estimated_credits: float | None = None

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def credit_balance(self):
        return await self.account.credit_balance()

    async def create_generation(
        self, prompt, *, image_ref=None, duration_seconds=4.0, aspect_ratio="9:16", extra=None
    ):
        self.last_estimated_credits = None
        self.asked.append(
            {
                "prompt": prompt,
                "seconds": duration_seconds,
                "first_frame": bytes(image_ref or b"")[:3],
                "extra": dict(extra or {}),
            }
        )
        number = len(self.asked)
        if number in self.refuse:
            raise self.refuse[number]
        price = price_shot(self.model, "1080p", duration_seconds)
        self.account.charge(price)
        self.last_estimated_credits = float(price)
        return f"{self.model}-task-{number}"

    async def get_generation_status(self, job_id):
        number = int(job_id.rsplit("-", 1)[1])
        if number in self.fail:
            code, detail = self.fail[number]
            return VideoGenerationResult(
                job_id=job_id,
                status="FAILED",
                raw_response={"failure_code": code, "failure": detail},
            )
        body = self.clip or f"clip {self.model} {number}".encode()
        return VideoGenerationResult(
            job_id=job_id, status="COMPLETED", video_bytes=body, raw_response={"task": job_id}
        )

    async def generate_image(self, *_args, **_kwargs):  # pragma: no cover - must not be used
        raise AssertionError("the motion step asked for a still")

    async def generate_candidates(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("the motion step asked for stills")


class Models:
    """``adapter_for_model``: the spies by model id, and every model the step asked for."""

    def __init__(self, *spies: SpyVideo):
        self.spies = {spy.model: spy for spy in spies}
        self.asked_for: list[str] = []

    def __call__(self, model_id: str):
        self.asked_for.append(model_id)
        return self.spies.get(model_id)

    def posts(self) -> int:
        return sum(len(spy.asked) for spy in self.spies.values())


def run(engine, storyboard_id, tmp_path, step, models, account, *, plan_hash=None, **kwargs):
    kwargs.setdefault("capabilities", [SEEDANCE])
    plan = motion_plan(
        engine,
        storyboard_id,
        capabilities=kwargs["capabilities"],
        overrides=kwargs.get("overrides"),
    )
    return run_motion_step(
        engine,
        storyboard_id,
        str(uuid4()),
        step=step,
        plan_hash=plan_hash or plan["plan_hash"],
        adapter_for_model=models,
        account=account,
        storage_root=tmp_path / "media",
        **kwargs,
    )


def approved(engine, storyboard_id, tmp_path, step, models, account, **kwargs):
    """Ask once (the Owner is asked, nothing is bought), answer yes as him, run the step."""
    posts = models.posts()
    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, step, models, account, **kwargs)
    assert asked.value.status == "NEEDS_APPROVAL", asked.value.reason_ro
    assert asked.value.http_status == 202
    assert models.posts() == posts, "a question bought a shot"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    return run(engine, storyboard_id, tmp_path, step, models, account, **kwargs)


def takes(engine, storyboard_id: str, kind: str | None = None) -> list[SceneTake]:
    with Session(engine) as session:
        query = select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        if kind is not None:
            query = query.where(SceneTake.kind == kind)
        rows = session.scalars(query.order_by(SceneTake.scene_number, SceneTake.created_at)).all()
        session.expunge_all()
        return list(rows)


def hero_approved(engine, storyboard_id, tmp_path, models, account, **kwargs) -> SceneTake:
    """The test shot bought and looked at: the Owner approves its take."""
    result = approved(engine, storyboard_id, tmp_path, "test_shot", models, account, **kwargs)
    assert by_scene(result)[1]["status"] == "PAID"
    hero = takes(engine, storyboard_id, "test_shot")
    assert len(hero) == 1
    decide_take(engine, hero[0].id, "APPROVED", decided_by="owner", note="Cadrul e bun.")
    return hero[0]


def by_scene(result: dict) -> dict[int, dict]:
    return {entry["scene_index"]: entry for entry in result["scenes"]}


# --------------------------------------------------------------- 1. the cap binds in the loop


def test_a_cap_of_400_buys_one_340_shot_and_stops_before_the_second_post(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, models, account)
    assert models.posts() == 1
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert [plan_scene["credits"] for plan_scene in plan["scenes"]] == [340, 340, 340]
    assert plan["steps"]["motion"]["to_buy"] == [2, 3]

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account, cap_credits=400)

    assert models.posts() == 2, "the second shot was POSTed past the cap"
    scenes = by_scene(result)
    assert scenes[2]["status"] == "PAID" and scenes[2]["credits_quoted"] == 340
    assert scenes[3]["status"] == "NOT_BOUGHT"
    assert result["stopped"].startswith("STOPPED_AT_CAP")
    assert "400" in result["stopped"] and "340" in result["stopped"]
    assert result["cap_credits"] == 400
    assert result["spent_credits_quoted"] == 340
    assert [t.scene_number for t in takes(engine, storyboard_id, "motion")] == [2]


def test_the_yes_is_bound_to_the_cap_it_was_given(engine, tmp_path):
    """A yes under a cap of 400 does not buy under a cap of 4000."""
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, models, account)
    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, "motion", models, account, cap_credits=400)
    answer(engine, asked.value.approval_id, "APPROVED")
    with pytest.raises(MotionStepRefused) as again:
        run(engine, storyboard_id, tmp_path, "motion", models, account, cap_credits=4000)
    assert again.value.status == "NEEDS_APPROVAL"
    assert models.posts() == 1


# ----------------------------------------- 2. the balance before each shot, and what it cost


def test_a_balance_below_the_next_shots_price_stops_before_the_post(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    # After the second shot of the account's life (the hero, then scene 2) something else
    # spent the money: 200 credits are left, under the next shot's 340.
    account = Account(10_000, after_shot={2: 200.0})
    models = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, models, account)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)

    assert models.posts() == 2, "a shot was POSTed with 200 credits left for a 340 shot"
    scenes = by_scene(result)
    assert scenes[2]["status"] == "PAID"
    # The Owner's rule of 2026-10-03: the scene the balance cannot pay stops cleanly (his to
    # top up, NEEDS_OWNER with LOW_BALANCE), and nothing after it is bought in this step.
    assert scenes[3]["status"] == "NEEDS_OWNER" and scenes[3]["failure_kind"] == "LOW_BALANCE"
    assert scenes[4]["status"] == "NOT_BOUGHT"
    assert "200" in result["stopped"] and "340" in result["stopped"]
    assert account.reads >= 4, "the balance was not read before every shot"


def test_a_balance_below_the_next_round_with_margin_refuses_before_asking(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    # The test shot's one shot is 340 credits; 340 x 1.15 = 391 (its cap of 680 is not asked).
    account = Account(390)
    models = Models(SpyVideo("seedance2_5", account))
    with pytest.raises(MotionStepRefused) as refused:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert refused.value.status == "LOW_BALANCE" and refused.value.http_status == 409
    assert "390" in refused.value.reason_ro
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == []
    assert models.posts() == 0


def test_a_balance_drop_of_340_after_a_clip_writes_a_measured_price(engine, tmp_path):
    from app.integrations.models import ProviderResource
    from test_phase11_economy import _runway_with_models

    connection = _runway_with_models(engine)
    with Session(engine) as session, session.begin():
        # A steward's old guess, so the measured figure visibly replaces it.
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == connection,
                ProviderResource.remote_id == "seedance2_5",
            )
        )
        row.pricing = {"per_second_usd": 0.5, "unit": "per second of video"}
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(5_000)
    models = Models(SpyVideo("seedance2_5", account))

    result = approved(
        engine,
        storyboard_id,
        tmp_path,
        "test_shot",
        models,
        account,
        integration_id=connection,
    )

    assert result["balance_before"] == 5_000 and result["balance_after"] == 4_660
    assert result["spent_credits_measured"] == 340
    (hero,) = takes(engine, storyboard_id, "test_shot")
    assert hero.credits_measured == pytest.approx(340)
    assert hero.credits_quoted == pytest.approx(340)
    assert hero.seconds == 5 and hero.model_id == "seedance2_5"
    with Session(engine) as session:
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == connection,
                ProviderResource.remote_id == "seedance2_5",
            )
        )
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "economy.prices_measured")
        ).all()
    # 340 credits over 5 billed seconds at 0.01 USD a credit.
    assert row.pricing["per_second_usd"] == pytest.approx(0.68)
    assert row.pricing["source"] == "measured"
    assert len(events) == 1 and events[0].payload["spent_credits"] == 340


# ------------------------------------------------- 3. SAFETY moves no other scene, buys again


def test_a_safety_refusal_on_scene_3_goes_back_to_stills_and_moves_no_other_scene(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=6)
    account = Account(50_000)
    caps = [SEEDANCE, VEO_FAST]
    hero_models = Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account))
    hero_approved(engine, storyboard_id, tmp_path, hero_models, account, capabilities=caps)
    plan = motion_plan(engine, storyboard_id, capabilities=caps)
    planned = {s["scene_index"]: s["model_id"] for s in plan["scenes"]}
    # Chosen per scene: the HERO hook on the premium model, the rest on the cheapest capable.
    assert planned == {1: "seedance2_5", **{n: "veo3.1_fast" for n in range(2, 7)}}

    seedance = SpyVideo("seedance2_5", account)
    # Scenes 2..6 are veo's calls 1..5: scene 3 is its second call, refused after creation.
    veo = SpyVideo(
        "veo3.1_fast",
        account,
        fail={2: ("INPUT_PREPROCESSING.SAFETY.THIRD_PARTY", "The input was flagged.")},
    )
    models = Models(seedance, veo)
    result = approved(engine, storyboard_id, tmp_path, "motion", models, account, capabilities=caps)

    assert len(veo.asked) == 5, "scene 3 was submitted again after a safety refusal"
    assert seedance.asked == [], "another model was tried in the same step"
    scenes = by_scene(result)
    assert scenes[3]["status"] == "NEEDS_STILL"
    assert scenes[3]["failure_kind"] == "SAFETY"
    # The scene's own move is shown for the Owner to decide; nothing is bought on it.
    assert scenes[3]["suggested"]["model_id"] == "seedance2_5"
    assert all(scenes[n]["status"] == "PAID" for n in (2, 4, 5, 6))
    motion = takes(engine, storyboard_id, "motion")
    refused = [t for t in motion if t.scene_number == 3]
    assert [t.status for t in refused] == ["REFUSED"]
    assert refused[0].failure_code == "INPUT_PREPROCESSING.SAFETY.THIRD_PARTY"
    assert {t.model_id for t in motion if t.scene_number in (4, 5, 6)} == {"veo3.1_fast"}
    # The picture goes back to the stills gate: its approved still is no longer approved.
    still = [t for t in takes(engine, storyboard_id, "still") if t.scene_number == 3]
    assert [t.status for t in still] == ["REJECTED"]
    assert "SAFETY" in (still[0].failure_code or "")
    with Session(engine) as session:
        warned = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.motion_needs_owner")
        ).all()
    assert [e.payload["scene_number"] for e in warned] == [3]


# ----------------------------------------- 4. account failures and repeated 400s stop the step


def test_insufficient_credits_stops_the_step_with_the_vendor_message_kept(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    account = Account(50_000)
    caps = [SEEDANCE, VEO_FAST]
    hero_approved(
        engine,
        storyboard_id,
        tmp_path,
        Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account)),
        account,
        capabilities=caps,
    )
    broke = MediaProviderError(
        "api.dev.runwayml.com refused the request (HTTP 400)",
        http_status=400,
        detail="Insufficient credits: you do not have enough credits to run this task.",
    )
    seedance = SpyVideo("seedance2_5", account)
    veo = SpyVideo("veo3.1_fast", account, refuse={1: broke})
    models = Models(seedance, veo)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account, capabilities=caps)

    assert len(veo.asked) == 1 and seedance.asked == []
    scenes = by_scene(result)
    assert scenes[2]["status"] == "NEEDS_OWNER" and scenes[2]["failure_kind"] == "ACCOUNT"
    assert scenes[3]["status"] == "NOT_BOUGHT" and scenes[4]["status"] == "NOT_BOUGHT"
    assert result["stopped"]
    (take,) = takes(engine, storyboard_id, "motion")
    assert take.status == "REFUSED" and take.failure_code == "HTTP_400"
    assert "Insufficient credits" in take.failure_detail


def test_two_400s_in_a_row_stop_the_step_and_no_other_model_is_tried(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=5)
    account = Account(50_000)
    caps = [SEEDANCE, VEO_FAST]
    hero_approved(
        engine,
        storyboard_id,
        tmp_path,
        Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account)),
        account,
        capabilities=caps,
    )

    def bad(field: str) -> MediaProviderError:
        return MediaProviderError(
            "api.dev.runwayml.com refused the request (HTTP 400)",
            http_status=400,
            detail="Validation of body failed",
            issues=[{"path": field, "message": "Invalid enum value"}],
        )

    seedance = SpyVideo("seedance2_5", account)
    veo = SpyVideo("veo3.1_fast", account, refuse={1: bad("ratio"), 2: bad("duration")})
    models = Models(seedance, veo)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account, capabilities=caps)

    assert len(veo.asked) == 2 and seedance.asked == []
    assert set(models.asked_for) == {"veo3.1_fast"}
    scenes = by_scene(result)
    assert scenes[2]["status"] == "NEEDS_OWNER" and scenes[2]["failure_kind"] == "CONTRACT"
    assert scenes[3]["status"] == "NEEDS_OWNER"
    assert scenes[4]["status"] == "NOT_BOUGHT" and scenes[5]["status"] == "NOT_BOUGHT"
    assert "400" in result["stopped"]
    details = [t.failure_detail for t in takes(engine, storyboard_id, "motion")]
    assert details[0].endswith("ratio: Invalid enum value")
    assert details[1].endswith("duration: Invalid enum value")
    # A refused POST costs nothing: the cap and the books count only what was charged.
    assert result["spent_credits_quoted"] == 0


# ------------------------------------------------- 5. a technical failure: once more, same model


def test_a_technical_failure_retries_the_same_model_once_and_every_clip_keeps_its_model(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    account = Account(50_000)
    caps = [SEEDANCE, VEO_FAST]
    hero_approved(
        engine,
        storyboard_id,
        tmp_path,
        Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account)),
        account,
        capabilities=caps,
    )
    seedance = SpyVideo("seedance2_5", account)
    # Scene 2 (veo's first call) fails with no reason given; the retry (call 2) lands. Scene 3
    # (calls 3 and 4) fails twice: after one retry it goes to the Owner.
    veo = SpyVideo(
        "veo3.1_fast",
        account,
        fail={1: (None, "task failed"), 3: (None, "task failed"), 4: (None, "task failed")},
    )
    models = Models(seedance, veo)

    result = approved(
        engine,
        storyboard_id,
        tmp_path,
        "motion",
        models,
        account,
        capabilities=caps,
        cap_credits=1000,
    )

    assert len(veo.asked) == 5 and seedance.asked == []
    scenes = by_scene(result)
    assert scenes[2]["status"] == "PAID" and scenes[2]["attempts"] == 2
    assert scenes[3]["status"] == "NEEDS_OWNER" and scenes[3]["failure_kind"] == "TECHNICAL"
    assert scenes[4]["status"] == "PAID"
    # The retry is the same request: the same model, the same seconds and the film's seed.
    assert veo.asked[0]["extra"]["seed"] == veo.asked[1]["extra"]["seed"] == result["seed"]
    assert veo.asked[0]["seconds"] == veo.asked[1]["seconds"] == 6
    clips = takes(engine, storyboard_id, "motion")
    assert {t.model_id for t in clips} == {"veo3.1_fast"}
    assert all(t.seed == result["seed"] for t in clips)
    assert [t.status for t in clips if t.scene_number == 2] == ["REFUSED", "PAID"]


# ---------------------------------------------- 6. the hero is kept; motion needs its own yes


def test_the_approved_hero_is_not_bought_again_and_motion_needs_a_yes_for_its_plan(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    first = approved(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert by_scene(first)[1]["status"] == "PAID" and models.posts() == 1
    (hero,) = takes(engine, storyboard_id, "test_shot")

    # Nothing is animated until someone has looked at the test shot.
    with pytest.raises(MotionStepRefused) as waiting:
        run(engine, storyboard_id, tmp_path, "motion", models, account)
    assert waiting.value.status == "HERO_NOT_APPROVED" and waiting.value.http_status == 409
    with Session(engine) as session:
        asked = session.scalars(select(ApprovalRequest)).all()
    assert [a.action for a in asked] == ["media.test_shot"]
    # The test shot step again buys nothing: the hero is bought and waits for his look.
    again = run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert again["bought_shots"] == 0 and models.posts() == 1

    # Only the Owner approves a take.
    with pytest.raises(PermissionError):
        decide_take(engine, hero.id, "APPROVED", decided_by="director")
    old_hash = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])["plan_hash"]
    decide_take(engine, hero.id, "APPROVED", decided_by="owner")
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert plan["plan_hash"] != old_hash, "his look at the hero is part of the plan"
    assert plan["steps"]["motion"]["to_buy"] == [2, 3]

    # A yes for another plan buys nothing.
    with pytest.raises(MotionStepRefused) as stale:
        run(engine, storyboard_id, tmp_path, "motion", models, account, plan_hash=old_hash)
    assert stale.value.status == "STALE_PLAN"
    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)
    assert models.posts() == 3, "the approved hero was bought again"
    scenes = by_scene(result)
    assert scenes[1]["status"] == "APPROVED" and scenes[1]["reused"] is True
    assert scenes[1]["take_id"] == hero.id
    # The yes is spent: running the step again with the same hash buys nothing new.
    with pytest.raises(MotionStepRefused):
        run(engine, storyboard_id, tmp_path, "motion", models, account, plan_hash=plan["plan_hash"])
    assert models.posts() == 3
    with Session(engine) as session:
        actions = [a.action for a in session.scalars(select(ApprovalRequest))]
        consumed = session.scalars(
            select(ApprovalRequest).where(ApprovalRequest.consumed_at.is_not(None))
        ).all()
    assert actions.count("media.motion_purchase") == 1
    assert len(consumed) == 2


def test_the_owners_settings_name_the_margin_and_the_resolution(engine, tmp_path, settings):
    """STUDIO_PAID_STEP_BALANCE_MARGIN and STUDIO_MOTION_RESOLUTION are read by the step."""
    assert settings.paid_step_balance_margin == pytest.approx(1.15)
    assert settings.motion_resolution == "1080p"
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(500)  # covers the shot of 340 x 1.15 = 391, not 340 x 2
    models = Models(SpyVideo("seedance2_5", account))
    stricter = settings.model_copy(update={"paid_step_balance_margin": 2.0})
    with pytest.raises(MotionStepRefused) as refused:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account, settings=stricter)
    assert refused.value.status == "LOW_BALANCE" and "100%" in refused.value.reason_ro
    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account, settings=settings)
    assert asked.value.status == "NEEDS_APPROVAL"


def test_a_still_kept_only_for_the_rehearsal_never_starts_a_paid_shot(engine, tmp_path):
    """The Nepal rehearsal may keep a still with faces 'doar pentru repetiție' (APPROVED, with
    a LOCAL.* failure code) so the Owner can watch the zero-credit film. No paid shot may start
    from it: the motion plan holds that scene and no step buys a shot of it."""
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    with Session(engine) as session, session.begin():
        still = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == 1,
                SceneTake.kind == "still",
            )
        ).one()
        still.failure_code = "LOCAL.FACES"
        still.approved_by = "owner (doar repetiția)"

    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])

    assert 1 not in plan["steps"]["test_shot"]["to_buy"]
    assert 1 not in plan["steps"]["motion"]["to_buy"]
    scene = next(s for s in plan["scenes"] if s["scene_index"] == 1)
    assert "repetiț" in scene["reason_ro"]


# ------------------------------------- 7. a task the vendor accepted is on the books at once
#
# Until 2026-10-01 the id of a task Runway had accepted lived only in a list in memory: a poll
# that ran out of time was recorded REFUSED and the id thrown away, a process killed while it
# waited left no row at all, and the next run bought the scene again. Now the take is written
# SUBMITTED, with the vendor's task id, the moment the vendor accepts it; it is collected with
# a free GET, and no step buys a scene whose task is still open.


class Killed(BaseException):
    """The process dying under the step: not an Exception, so nothing in the step catches it."""


class DyingVideo(SpyVideo):
    """A SpyVideo whose status poll fails for the calls in ``dies`` (the task was created and
    charged); ``kill`` raises Killed instead, as a process killed mid-poll would stop."""

    def __init__(self, *args, dies=(), kill=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.dies = set(dies)
        self.kill = set(kill)
        self.polls: list[str] = []

    async def get_generation_status(self, job_id):
        self.polls.append(job_id)
        number = int(job_id.rsplit("-", 1)[1])
        if number in self.kill:
            raise Killed()
        if number in self.dies:
            raise MediaProviderError("api.dev.runwayml.com did not answer", unanswered=True)
        return await super().get_generation_status(job_id)


@pytest.fixture
def instant_polls(monkeypatch):
    from app.media import assembler

    monkeypatch.setattr(assembler, "MOTION_POLL_SECONDS", 0)


def test_a_shot_whose_poll_fails_stays_submitted_and_is_never_bought_again(
    engine, tmp_path, instant_polls
):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    video = DyingVideo("seedance2_5", account, dies={1})
    models = Models(video)

    result = approved(engine, storyboard_id, tmp_path, "test_shot", models, account)

    assert models.posts() == 1
    hero = by_scene(result)[1]
    assert hero["status"] == "IN_FLIGHT"
    assert "seedance2_5-task-1" not in (hero.get("reason") or "")  # no vendor id in his words
    (take,) = takes(engine, storyboard_id, "test_shot")
    assert take.status == "SUBMITTED"
    assert take.remote_task_id == "seedance2_5-task-1"
    assert take.credits_quoted == pytest.approx(340)
    assert take.path is None and take.sha256 is None
    # The money went out: it is counted against the cap and named in the result.
    assert result["spent_credits_quoted"] == 340
    assert result["stopped"]

    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert next(s for s in plan["scenes"] if s["scene_index"] == 1)["status"] == "IN_FLIGHT"
    assert plan["steps"]["test_shot"]["to_buy"] == []

    # The next step, the vendor still silent: the task is asked about, never bought again.
    again = run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert models.posts() == 1
    assert again["bought_shots"] == 0
    assert video.polls.count("seedance2_5-task-1") >= 2


def test_a_submitted_shot_is_collected_on_the_next_step_with_no_new_post(
    engine, tmp_path, instant_polls
):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    video = DyingVideo("seedance2_5", account, dies={1})
    models = Models(video)
    approved(engine, storyboard_id, tmp_path, "test_shot", models, account)
    (take,) = takes(engine, storyboard_id, "test_shot")
    assert take.status == "SUBMITTED"

    video.dies.clear()  # the vendor answers again
    result = run(engine, storyboard_id, tmp_path, "test_shot", models, account)

    assert models.posts() == 1, "a shot the vendor had already made was bought again"
    (collected,) = takes(engine, storyboard_id, "test_shot")
    assert collected.id == take.id
    assert collected.status == "PAID"
    assert collected.remote_task_id == "seedance2_5-task-1"
    assert collected.path and Path(collected.path).read_bytes() == b"clip seedance2_5 1"
    assert collected.sha256 == sha(Path(collected.path))
    assert result["collected"][0]["take_id"] == take.id
    with Session(engine) as session:
        # Collected and then checked like any bought shot: its clip-QC report is on the take.
        reports = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "media.clip_qc_checked",
                DomainEvent.aggregate_id == take.id,
            )
        ).all()
        collected_events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.scene_take_collected")
        ).all()
    assert len(reports) == 1
    assert [e.aggregate_id for e in collected_events] == [take.id]
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert next(s for s in plan["scenes"] if s["scene_index"] == 1)["status"] == "BOUGHT"


def test_a_process_killed_while_it_waits_leaves_the_task_on_the_books(
    engine, tmp_path, instant_polls
):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(10_000)
    models = Models(DyingVideo("seedance2_5", account, kill={1}))
    with pytest.raises(MotionStepRefused) as asked:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    answer(engine, asked.value.approval_id, "APPROVED")

    with pytest.raises(Killed):
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)

    (take,) = takes(engine, storyboard_id, "test_shot")
    assert (take.status, take.remote_task_id) == ("SUBMITTED", "seedance2_5-task-1")
    # Restarted, with a vendor that answers: collected, not bought.
    healthy = Models(SpyVideo("seedance2_5", account))
    run(engine, storyboard_id, tmp_path, "test_shot", healthy, account)
    assert healthy.posts() == 0 and models.posts() == 1
    (take,) = takes(engine, storyboard_id, "test_shot")
    assert take.status == "PAID"


def test_an_open_motion_task_stops_the_step_and_only_that_scene_waits(
    engine, tmp_path, instant_polls
):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    # Scenes 2, 3, 4 are this spy's calls 1, 2, 3: scene 2's poll fails.
    video = DyingVideo("seedance2_5", account, dies={1})
    models = Models(video)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)

    assert len(video.asked) == 1, "the step went on buying while a paid task was open"
    scenes = by_scene(result)
    assert scenes[2]["status"] == "IN_FLIGHT"
    assert scenes[3]["status"] == "NOT_BOUGHT" and scenes[4]["status"] == "NOT_BOUGHT"
    assert result["stopped"]

    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    assert plan["steps"]["motion"]["to_buy"] == [3, 4]
    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)
    # Scene 2 is never POSTed again; scenes 3 and 4 are bought once each.
    assert len(video.asked) == 3
    assert by_scene(result)[2]["status"] == "IN_FLIGHT"


def test_a_task_the_vendor_failed_turns_its_own_row_refused_with_the_task_id(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(
        SpyVideo("seedance2_5", account, fail={1: ("INTERNAL.BAD_OUTPUT.CODE01", "bad output")})
    )

    approved(engine, storyboard_id, tmp_path, "test_shot", models, account)

    shots = takes(engine, storyboard_id, "test_shot")
    first = [t for t in shots if t.remote_task_id == "seedance2_5-task-1"]
    assert len(first) == 1 and first[0].status == "REFUSED"
    assert first[0].failure_code == "INTERNAL.BAD_OUTPUT.CODE01"
    assert not [t for t in shots if t.status == "SUBMITTED"]


# ----------------------------- 8. a submit charged without an answer is counted, never re-sent
#
# MONEY-01 (2026-10-02): ``posted`` was filled only once create_generation returned. A POST
# that left and whose answer was lost raised MediaProviderError(unanswered=True), counted as
# free and sorted TECHNICAL, so the same POST was sent again. Measured on fakes before the
# fix: 3 POSTs, 1,020 credits off the account under an approved cap of 700.


class UnansweredVideo(SpyVideo):
    """A SpyVideo whose POSTs in ``lost`` are charged by the vendor and never answered."""

    def __init__(self, *args, lost=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.lost = set(lost)

    async def create_generation(self, prompt, **kwargs):
        number = len(self.asked) + 1
        if number in self.lost:
            self.asked.append({"prompt": prompt, "lost": True, "extra": {}})
            self.account.charge(price_shot(self.model, "1080p", kwargs.get("duration_seconds")))
            raise MediaProviderError("api.dev.runwayml.com did not answer", unanswered=True)
        return await super().create_generation(prompt, **kwargs)


def test_a_charged_but_unanswered_submit_is_counted_and_never_sent_again(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    start = account.balance
    video = UnansweredVideo("seedance2_5", account, lost={1})
    models = Models(video)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account, cap_credits=700)

    scenes = by_scene(result)
    assert len(video.asked) == 1, "a POST whose answer was lost was sent again"
    assert scenes[2]["status"] == "NEEDS_OWNER"
    assert "poate fi taxat" in scenes[2]["reason"]
    # It is counted against the cap and named as possibly charged; nothing more is bought
    # in this step from a vendor whose answers are being lost.
    assert result["spent_credits_quoted"] == pytest.approx(340)
    assert scenes[3]["status"] == "NOT_BOUGHT" and result["stopped"]
    assert start - account.balance <= 700
    (refused,) = [t for t in takes(engine, storyboard_id, "motion") if t.scene_number == 2]
    assert refused.status == "REFUSED" and refused.credits_quoted == pytest.approx(340)


def test_a_request_that_never_left_is_not_counted_as_charged(engine, tmp_path):
    """A request that never left this machine cost nothing and may be sent again."""
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    unsent = MediaProviderError("api.dev.runwayml.com could not be reached", unsent=True)
    video = SpyVideo("seedance2_5", account, refuse={1: unsent})
    models = Models(video)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)

    # The unsent request is tried once more (it cannot have been charged); both scenes land.
    assert len(video.asked) == 3
    assert result["spent_credits_quoted"] == pytest.approx(680)
    first = [t for t in takes(engine, storyboard_id, "motion") if t.status == "REFUSED"]
    assert len(first) == 1 and first[0].credits_quoted is None


def test_an_account_that_drops_more_than_was_counted_stops_before_the_next_post(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    # After the first motion shot (the account's 2nd charge) 500 credits more are gone than
    # the step counted: a charge it does not know about.
    account.after_shot = {2: account.balance - 340 - 500}
    video = SpyVideo("seedance2_5", account)
    models = Models(video)

    result = approved(engine, storyboard_id, tmp_path, "motion", models, account)

    assert len(video.asked) == 1, "the step bought on after the account lost uncounted credits"
    assert result["stopped"] and "neexplicat" in result["stopped"]
    scenes = by_scene(result)
    assert scenes[3]["status"] == "NOT_BOUGHT" and scenes[4]["status"] == "NOT_BOUGHT"


# ---------------------------------- 9. every purchase is booked once, under its own reference


def test_two_runs_under_one_plan_book_two_rows_and_a_refused_booking_is_loud(engine):
    from app.agents.models import AgentMessage
    from app.economy.models import ProviderCostRecord
    from app.media.shooting_sheet import book_step_cost

    storyboard_id = "film-" + uuid4().hex[:8]
    spend = {"spent_credits_quoted": 340.0, "spent_credits_measured": None}

    first = book_step_cost(engine, storyboard_id, "motion", "f" * 64, 0.01, spend, "day-1")
    second = book_step_cost(engine, storyboard_id, "motion", "f" * 64, 0.01, spend, "day-2")

    assert first and second
    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
    assert len(rows) == 2, "a second purchase under the same sheet was not booked"
    assert {r.external_reference for r in rows} == {
        f"foaie:{storyboard_id}:motion:{'f' * 16}:day-1",
        f"foaie:{storyboard_id}:motion:{'f' * 16}:day-2",
    }

    # The same purchase booked again is refused by the books, and that is never silent.
    again = book_step_cost(engine, storyboard_id, "motion", "f" * 64, 0.01, spend, "day-2")

    assert again is None
    with Session(engine) as session:
        assert len(list(session.scalars(select(ProviderCostRecord)))) == 2
        warned = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.step_cost_not_booked")
        ).all()
        sent = [
            m
            for m in session.scalars(select(AgentMessage))
            if isinstance(m.body_json, dict) and m.body_json.get("kind") == "booking_refused"
        ]
        text = sent[0].body_text if sent else ""
    assert len(warned) == 1 and warned[0].payload["severity"] == "WARNING"
    assert len(sent) == 1 and "3,40 USD" in text and "nu a putut fi trecut" in text, text


def test_a_clip_that_cannot_be_written_still_books_what_was_bought(engine, tmp_path, monkeypatch):
    from app.economy.models import ProviderCostRecord
    from app.media.assembler import SpentStageError
    from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    hero_approved(
        engine, storyboard_id, tmp_path, Models(SpyVideo("seedance2_5", account)), account
    )
    start = account.balance
    models = Models(SpyVideo("seedance2_5", account))
    context = {
        "capabilities": [SEEDANCE],
        "account": account,
        "adapter_for_model": models,
        "storage_root": tmp_path / "media",
        "environment": "TEST",
    }
    plan_hash = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)[
        "sheet_hash"
    ]
    with pytest.raises(SheetStepRefused) as asked:
        run_sheet_step(engine, storyboard_id, "motion", plan_hash, correlation_id="a", **context)
    answer(engine, asked.value.approval_id, "APPROVED")

    # The second shot's clip meets a full disk after Runway has charged for it.
    real_write = Path.write_bytes
    clips: list[str] = []

    def full_disk(self: Path, data: bytes) -> int:
        if self.name.startswith("motion_"):
            clips.append(self.name)
            if len(clips) == 2:
                raise OSError(28, "No space left on device")
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", full_disk)

    with pytest.raises(SpentStageError):
        run_sheet_step(engine, storyboard_id, "motion", plan_hash, correlation_id="b", **context)

    assert models.posts() == 2
    with Session(engine) as session:
        (cost,) = session.scalars(select(ProviderCostRecord)).all()
    # Both shots were charged: the first one landed, the second is on the vendor's side.
    assert cost.attribution_json["credits"] == pytest.approx(start - account.balance)
    assert cost.attribution_json["credits"] >= 340


def test_a_stills_request_charged_without_an_answer_is_counted_and_not_sent_again(engine, tmp_path):
    """The same rule on the stills step: no task heard, no answer, the request is counted
    as possibly charged, is never re-sent, and the step stops."""
    import test_stills_stage as stills_tests

    class UnansweredStills(stills_tests.SpyStills):
        async def generate_candidates(self, prompt, *, ratio, count=2, references=(), **kwargs):
            self.asked.append({"prompt": prompt, "ratio": ratio, "count": count})
            if self.balance is not None:
                self.balance -= 9.0 * count
            raise MediaProviderError("api.dev.runwayml.com did not answer", unanswered=True)

    storyboard_id = stills_tests.a_film(engine, tmp_path)
    images = UnansweredStills(balance=1_000)

    result = stills_tests.approved_run(
        engine, storyboard_id, tmp_path, images, stills_tests.SpyJudge()
    )

    assert len(images.asked) == 1, "a stills request whose answer was lost was sent again"
    assert result["spent_credits_quoted"] == pytest.approx(18)
    first = next(e for e in result["scenes"] if e["scene_index"] == 1)
    assert first["status"] == "NEEDS_OWNER" and "poate fi taxat" in first["reason"]
    assert result["stopped"]
    (refused,) = stills_tests.takes(engine, storyboard_id)
    assert refused.status == "REFUSED" and refused.credits_quoted == pytest.approx(18)
    assert refused.failure_code == "VENDOR.UNANSWERED"


# ------------------------------------- 9. a scene that failed is not bought again across runs
#
# 2026-10-02 (NO_REBUY_RECOVERY_REFERENCES, MONEY-03): under AUTONOMOUS_CEO with the Owner's
# MODE rule, a scene whose shots failed went back to PLANNED on the next run and was bought
# again, unasked ("day1 posts 3 day2 posts 2"). The scene now remembers what happened to it
# since the Owner last decided about it: it waits for him, and only his decision on the sheet
# lifts the hold.


def autonomous_mode(engine) -> None:
    """AUTONOMOUS_CEO with the paid-media rule MODE: the step buys without asking."""
    from app.models import OwnerPolicy

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.paid_media_approval = "MODE"


def test_under_mode_a_scene_that_failed_is_not_bought_again_on_the_next_run(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    first = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, first, account)
    autonomous_mode(engine)
    # Run 1: scene 3's task fails twice (charged both times, as Runway does) -> NEEDS_OWNER.
    day1 = Models(SpyVideo("seedance2_5", account, fail={2: (None, "x"), 3: (None, "x")}))
    first = run(engine, storyboard_id, tmp_path, "motion", day1, account)
    assert day1.posts() == 3
    assert by_scene(first)[3]["status"] == "NEEDS_OWNER"

    # Run 2: nobody decided anything. Scene 3 waits for the Owner and nothing is bought.
    day2 = Models(SpyVideo("seedance2_5", account))
    second = run(engine, storyboard_id, tmp_path, "motion", day2, account)

    assert day2.posts() == 0, "a scene that failed was bought again without the Owner"
    assert by_scene(second)[3]["status"] == "NEEDS_OWNER"
    assert by_scene(second)[3]["reason"]
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    scene_three = next(s for s in plan["scenes"] if s["scene_index"] == 3)
    assert scene_three["status"] == "NEEDS_OWNER"
    assert "Proprietar" in scene_three["reason_ro"]
    assert plan["steps"]["motion"]["to_buy"] == []


def test_the_owners_choice_on_the_sheet_lifts_the_hold_and_the_scene_is_bought_once(
    engine, tmp_path
):
    from app.media.shooting_sheet import set_scene_model

    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    first = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, first, account)
    autonomous_mode(engine)
    day1 = Models(SpyVideo("seedance2_5", account, fail={2: (None, "x"), 3: (None, "x")}))
    run(engine, storyboard_id, tmp_path, "motion", day1, account)

    # His decision on the sheet: scene 3 on the same model, once more.
    set_scene_model(engine, storyboard_id, 3, "seedance2_5", issued_by="owner")
    day2 = Models(SpyVideo("seedance2_5", account))
    second = run(
        engine, storyboard_id, tmp_path, "motion", day2, account, overrides={3: "seedance2_5"}
    )

    assert day2.posts() == 1
    assert by_scene(second)[3]["status"] == "PAID"


def test_a_vendor_refusal_that_cost_nothing_does_not_hold_the_scene(engine, tmp_path):
    """An account problem refused before anything was charged says nothing about the scene:
    once the account is topped up the scene is bought; it is not held for the Owner."""
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(50_000)
    first = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, first, account)
    autonomous_mode(engine)
    broke = MediaProviderError(
        "api.dev.runwayml.com refused the request (HTTP 402)",
        http_status=402,
        detail="Insufficient credits.",
    )
    day1 = Models(SpyVideo("seedance2_5", account, refuse={1: broke}))
    first = run(engine, storyboard_id, tmp_path, "motion", day1, account)
    assert by_scene(first)[2]["status"] == "NEEDS_OWNER"

    day2 = Models(SpyVideo("seedance2_5", account))
    second = run(engine, storyboard_id, tmp_path, "motion", day2, account)

    assert day2.posts() == 1
    assert by_scene(second)[2]["status"] == "PAID"


def test_no_scene_is_bought_past_the_paid_attempt_limit_without_the_owner(
    engine, tmp_path, monkeypatch
):
    """A new prompt is a new shot, but not a new allowance: past the limit of paid attempts
    since the Owner last decided about the scene, it waits for him."""
    from app.media import assembler

    monkeypatch.setattr(assembler, "max_paid_attempts_per_scene", lambda: 2)
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    first = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, first, account)
    autonomous_mode(engine)
    day1 = Models(SpyVideo("seedance2_5", account, fail={2: (None, "x"), 3: (None, "x")}))
    run(engine, storyboard_id, tmp_path, "motion", day1, account)
    # The shot plan of scene 3 is written again (a new motion prompt: a new shot identity).
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        ).one()
        package = dict(row.prompt_json)
        package["motion_intent"] = {**package["motion_intent"], "world": "Rain falls softly."}
        row.prompt_json = package

    day2 = Models(SpyVideo("seedance2_5", account))
    second = run(engine, storyboard_id, tmp_path, "motion", day2, account)

    assert day2.posts() == 0
    assert by_scene(second)[3]["status"] == "NEEDS_OWNER"
    assert "2" in by_scene(second)[3]["reason"]


def test_the_paid_attempt_limit_is_the_owners_setting(settings, monkeypatch):
    """STUDIO_MAX_PAID_ATTEMPTS_PER_SCENE, 3 by default; read from one place for every plan,
    so the sheet on the page and the one the day buys from hash the same."""
    from app.media import assembler

    assert settings.max_paid_attempts_per_scene == 3
    stricter = settings.model_copy(update={"max_paid_attempts_per_scene": 5})
    monkeypatch.setattr(assembler, "_studio_settings", lambda: stricter)
    assert assembler.max_paid_attempts_per_scene() == 5
    monkeypatch.setattr(assembler, "_studio_settings", lambda: None)
    assert assembler.max_paid_attempts_per_scene() == assembler.DEFAULT_MAX_PAID_ATTEMPTS == 3


# ------------------------------- 10. a paid shot nobody checked is checked before the day waits


def test_a_paid_shot_without_a_clip_report_is_judged_before_the_staircase_waits(
    engine, settings, tmp_path, monkeypatch
):
    """A shot that landed PAID and was never checked (the process died before clip QC) used
    to keep the film TAKES_NOT_ACCEPTED for ever. The day checks it first (vision tokens only,
    no media bought) and the film goes on."""
    from app.media import assembler
    from app.media import qc as clip_qc
    from app.models import OwnerPolicy
    from app.runbook import stages

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    hero_approved(engine, storyboard_id, tmp_path, models, account)

    def dies(*_args, **_kwargs):
        raise Killed()

    with monkeypatch.context() as patched:
        patched.setattr(assembler, "_check_shot", dies)
        with pytest.raises(Killed):
            approved(engine, storyboard_id, tmp_path, "motion", models, account)
    (left,) = takes(engine, storyboard_id, "motion")
    assert left.status == "PAID" and left.remote_task_id
    posts = models.posts()

    checked: list[int] = []

    def passing(path, *, scene, **_kwargs):
        checked.append(scene)
        return clip_qc.ClipReport(
            scene=scene,
            path=str(path),
            checks=(),
            passed=True,
            blocks_ro=(),
            warnings_ro=(),
            unmeasured=(),
        )

    monkeypatch.setattr(clip_qc, "check_clip", passing)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    wiring = {
        "integration_id": None,
        "capabilities": [SEEDANCE],
        "image_adapter": None,
        "account": account,
        "adapter_for_model": models,
        "resolution": "1080p",
        "storage_root": tmp_path / "media",
    }

    film = stages._film_staircase(
        engine, settings, None, storyboard_id, wiring, "PRODUCTION", str(uuid4())
    )

    assert checked == [2]
    assert models.posts() == posts, "a shot was bought to replace one nobody had checked"
    assert film["status"] == "READY", film
    with Session(engine) as session:
        reports = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == "media.clip_qc_checked",
                DomainEvent.aggregate_id == left.id,
            )
        ).all()
    assert len(reports) == 1


def test_production_buys_one_still_per_scene():
    """2026-10-15 21:10Z, the Owner watching the Speed of Light film buy ten images for five
    scenes: «ne costă bani pentru că facem câte două imagini, vreau să facem doar 1». The
    suite keeps two (conftest), production one: read from the source, not the patched module."""
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "backend" / "app" / "media" / "cost_plan.py"
    match = re.search(r"^STILL_CANDIDATES = (\d+)$", source.read_text(encoding="utf-8"), re.M)
    assert match and int(match.group(1)) == 1
