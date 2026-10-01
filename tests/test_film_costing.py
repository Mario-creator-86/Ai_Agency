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
    assert scenes[3]["status"] == "NOT_BOUGHT" and scenes[4]["status"] == "NOT_BOUGHT"
    assert "200" in result["stopped"] and "340" in result["stopped"]
    assert account.reads >= 4, "the balance was not read before every shot"


def test_a_balance_below_the_step_cap_with_margin_refuses_before_asking(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=2)
    account = Account(500)  # the test shot's cap is 680; 680 x 1.15 = 782
    models = Models(SpyVideo("seedance2_5", account))
    with pytest.raises(MotionStepRefused) as refused:
        run(engine, storyboard_id, tmp_path, "test_shot", models, account)
    assert refused.value.status == "LOW_BALANCE" and refused.value.http_status == 409
    assert "500" in refused.value.reason_ro
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
    account = Account(1_000)  # covers 680 x 1.15 = 782, not 680 x 2
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
