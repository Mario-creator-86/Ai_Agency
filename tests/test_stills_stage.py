"""The stills step: two candidates at 2K per filmed scene, looked at before any motion.

The Nepal film bought every still and every clip before anybody looked at a picture, then
bought them all again. This step is the first, cheapest stair of the money staircase:

- it runs only with the Owner's yes for ``media.stills_purchase`` bound to the plan he was
  shown (the plan_hash); a stale plan, a plan he did not answer, a lint BLOCK or a yes that
  was already spent buys nothing;
- it buys seedream5_pro at 2K (1530:2720), two candidates per request, for LIVE scenes only;
  a chart, a title or a black screen never reaches the image model;
- scene 1 is bought first, and once a candidate passes it is Figure 1 (referenceImages) for
  every later scene, for its light, palette and grain only;
- every candidate goes through the local checks first; a face from YuNet rejects it there,
  and it never reaches the vision model (``judge_still``);
- a scene whose candidates fail is bought again at most twice, with what was wrong rewritten
  as positive words, and then waits for the Owner (NEEDS_OWNER); it is never pushed on;
- nothing in the step ever asks a video model.

Every provider is faked: spy adapters count their calls, the vision model is a spy, and the
Runway transport is a fake that records the body it would have sent.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.media import stills_stage
from app.media.faces import FaceCount, count_faces, detector_available
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.picture_qc import StillJudgement, StillVerdict
from app.media.prompt_lint import LintScene, has_block, lint_film
from app.media.still_gate import MAX_REROLLS
from app.media.stills_stage import (
    FIGURE_ONE,
    STILL_RATIO,
    StillsStageRefused,
    run_stills_stage,
    stills_plan,
)
from app.models import ApprovalRequest, DomainEvent
from app.providers.media_base import ImageResult
from app.providers.media_http import MediaProviderError, TaskStillOpen
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_scene_takes import nepal_like

FIXTURES = Path(__file__).parent / "fixtures" / "factual_sample"
FACE = FIXTURES / "scene_06.jpg"  # a woman's face filling the right half (eye-checked)
NO_FACE = (FIXTURES / "scene_01.jpg", FIXTURES / "scene_02.jpg")  # ridges, a river: nobody

LOOK = (
    "Late monsoon in the Himalayan foothills, overcast sky with low grey cloud, soft diffuse "
    "light from the left, muted greens, slate blue and ochre, 35 mm lens feel, fine film "
    "grain, a real location as it is today, calm and documentary."
)
SUBJECTS = {
    1: "A wide establishing view of steep Himalayan ridges and a far village of stone houses "
    "on a terraced slope, 24 mm lens, seen from high above.",
    2: "A medium view of brown floodwater running fast through a narrow mountain valley, "
    "stones and broken trees in the current, 50 mm lens.",
    3: "A detail of muddy hands only, pressing seedlings into wet terraced soil, 85 mm lens, "
    "shallow depth of field.",
    4: "A wide view of a terraced field at dusk with a farmer small and distant, seen from "
    "behind, walking along the edge, 24 mm lens.",
}
TAIL = (
    "Vertical 9:16 frame, the subject in the upper two thirds, the lower quarter calm and "
    "empty for captions. Any people appear only as small distant figures seen from behind, "
    "faces turned away. No text, no logo."
)
BIBLE = {"continuity_rules": ["No human faces appear"]}


def still_prompt(scene: int) -> str:
    return f"{LOOK} {SUBJECTS[scene]} {TAIL}"


def a_film(engine, tmp_path: Path) -> str:
    """The Nepal film's shape (4 LIVE, a DATA_CARD, a BLACK) with compiled, clean prompts."""
    storyboard_id = nepal_like(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).visual_bible_json = dict(BIBLE)
        for row in session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ):
            if row.scene_kind != "LIVE":
                row.prompt_json = {"scene_kind": row.scene_kind, "source": "model"}
                continue
            words = still_prompt(row.scene_index)
            row.visual_prompt = words
            row.prompt_json = {
                "scene_kind": "LIVE",
                "source": "model",
                "still_prompt": words,
                "look_block": LOOK,
                "camera_move": "slow push-in",
            }
    return storyboard_id


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SpyStills:
    """The image vendor, faked: two candidates per request, every request recorded.

    ``pictures(prompt, call)`` chooses the files handed back; by default two pictures with
    nobody in them. It also carries every video method, each of which fails the test.
    """

    PROVIDER_NAME = "TEST_IMAGE_PROVIDER"
    model = "seedream5_pro"
    REFERENCE_IMAGE_VERIFIED = False

    def __init__(self, pictures=None, balance: float | None = None):
        self.asked: list[dict] = []
        self.pictures = pictures or (lambda prompt, call: list(NO_FACE))
        self.balance = balance
        self.last_estimated_credits: float | None = None

    async def health_check(self):
        return {"status": "HEALTHY"}

    async def credit_balance(self):
        return self.balance

    async def generate_candidates(
        self, prompt, *, ratio, count=2, references=(), seed=None, on_submitted=None
    ):
        self.asked.append(
            {"prompt": prompt, "ratio": ratio, "count": count, "references": list(references)}
        )
        if on_submitted is not None:
            # As Runway's adapter does: the task is heard the moment it is accepted.
            on_submitted(f"img-task-{len(self.asked)}")
        files = self.pictures(prompt, len(self.asked))[:count]
        self.last_estimated_credits = 9.0 * count
        if self.balance is not None:
            self.balance -= 9.0 * count
        return [
            ImageResult(
                image_bytes=path.read_bytes(),
                format="jpeg",
                width=540,
                height=960,
                prompt=prompt,
                raw_response={"output_index": n},
            )
            for n, path in enumerate(files)
        ]

    async def generate_image(self, *_args, **_kwargs):  # pragma: no cover - must not be used
        raise AssertionError("the stills step asks for candidates, never one image at a time")

    async def create_generation(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("the stills step called image_to_video")

    async def estimate_generation(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("the stills step priced a video")

    async def image_to_video(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("the stills step called image_to_video")


class SpyJudge:
    """The vision model, faked: says the still is right, and remembers what it looked at."""

    def __init__(self):
        self.looked_at: list[str] = []

    def __call__(self, engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        self.looked_at.append(str(path))
        return StillJudgement(
            status="MEASURED",
            verdict=StillVerdict(
                scene=plan.scene,
                faces_visible=False,
                readable_text=False,
                matches_plan=True,
                look_ok=True,
                technical_ok=True,
                bible_violations="none",
                verdict="buy_motion",
                reason="the scene as planned",
            ),
            detail_ro="",
            run_id="run-1",
            looked_by="Video Editor",
            image_width=1080,
        )


def faces_in(face_files: tuple[Path, ...] = (FACE,)):
    """A face counter that finds a face exactly in the given pictures (by their bytes)."""
    marked = {sha(path) for path in face_files}

    def counter(path, **_):
        found = 1 if sha(Path(path)) in marked else 0
        return FaceCount(
            status="MEASURED",
            faces=found,
            boxes=((600, 400, 300, 360, 0.95),) if found else (),
            detail_ro=f"{found} fețe",
        )

    return counter


def run(engine, storyboard_id, tmp_path, adapter, judge, *, plan_hash=None, **kwargs):
    kwargs.setdefault("face_counter", faces_in())
    kwargs.setdefault("measure", ("faces",))
    return run_stills_stage(
        engine,
        storyboard_id,
        str(uuid4()),
        plan_hash=plan_hash or stills_plan(engine, storyboard_id)["plan_hash"],
        image_adapter=adapter,
        registry=None,
        judge=judge,
        storage_root=tmp_path / "media",
        **kwargs,
    )


def approved_run(engine, storyboard_id, tmp_path, adapter, judge, **kwargs):
    """Ask once (the Owner is asked), answer yes as the Owner, then run the step."""
    with pytest.raises(StillsStageRefused) as asked:
        run(engine, storyboard_id, tmp_path, adapter, judge, **kwargs)
    assert asked.value.status == "NEEDS_APPROVAL"
    assert adapter.asked == []
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    return run(engine, storyboard_id, tmp_path, adapter, judge, **kwargs)


def takes(engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = session.scalars(
            select(SceneTake)
            .where(SceneTake.storyboard_id == storyboard_id)
            .order_by(SceneTake.scene_number, SceneTake.created_at)
        ).all()
        session.expunge_all()
        return list(rows)


def test_the_fixture_prompts_pass_the_lint():
    """The test film is clean, so every refusal below is about the step, not the words."""
    scenes = [LintScene(scene=n, kind="LIVE", still_prompt=still_prompt(n)) for n in SUBJECTS]
    scenes += [LintScene(scene=5, kind="DATA_CARD"), LintScene(scene=6, kind="BLACK")]
    assert not has_block(lint_film(scenes, bible=BIBLE))


# ------------------------------------- 1. two candidates at 2K, LIVE only, scene 1 is Figure 1


def test_two_candidates_at_2k_for_live_scenes_only_and_scene_one_is_figure_one(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    adapter, judge = SpyStills(), SpyJudge()

    result = approved_run(engine, storyboard_id, tmp_path, adapter, judge)

    # Four LIVE scenes, four requests; the chart and the black screen never reach the model.
    assert len(adapter.asked) == 4
    assert all(call["count"] == 2 for call in adapter.asked)
    assert all(call["ratio"] == STILL_RATIO == "1530:2720" for call in adapter.asked)
    for call, scene in zip(adapter.asked, (1, 2, 3, 4), strict=True):
        assert SUBJECTS[scene] in call["prompt"]
    assert not any("bars" in c["prompt"] or "black screen" in c["prompt"] for c in adapter.asked)

    # Scene 1 is drawn from words alone; every later scene carries scene 1's approved still.
    rows = takes(engine, storyboard_id)
    first = [t for t in rows if t.scene_number == 1 and t.status == "APPROVED"]
    assert len(first) == 1
    figure_one = Path(first[0].path).read_bytes()
    assert adapter.asked[0]["references"] == []
    assert FIGURE_ONE not in adapter.asked[0]["prompt"]
    for call in adapter.asked[1:]:
        assert call["references"] == [figure_one]
        assert FIGURE_ONE in call["prompt"]
    assert "light, palette and grain" in FIGURE_ONE

    # Every candidate is a take at 2K; one approved per scene, the other kept as PAID.
    assert len(rows) == 8
    assert {t.scene_number for t in rows} == {1, 2, 3, 4}
    assert all(t.kind == "still" and t.resolution == "1530:2720" for t in rows)
    assert all(t.model_id == "seedream5_pro" for t in rows)
    for scene in (1, 2, 3, 4):
        statuses = sorted(t.status for t in rows if t.scene_number == scene)
        assert statuses == ["APPROVED", "PAID"]
    assert all(t.approved_by == "still_gate" for t in rows if t.status == "APPROVED")

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[5]["status"] == "composed" and by_scene[5]["credits"] == 0
    assert by_scene[6]["status"] == "composed" and by_scene[6]["credits"] == 0
    assert all(by_scene[n]["status"] == "APPROVED" for n in (1, 2, 3, 4))
    # The first real use of referenceImages is said to be unverified.
    assert result["reference_unverified"] is True
    assert result["spent_credits_quoted"] == 4 * 18


def test_an_approved_take_is_never_bought_again(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    approved_run(engine, storyboard_id, tmp_path, SpyStills(), SpyJudge())

    # The same film again: every LIVE scene already has an approved still for its prompt.
    plan = stills_plan(engine, storyboard_id)
    assert plan["to_buy"] == []
    assert plan["cost_credits"] == 0
    again = SpyStills()
    result = run(engine, storyboard_id, tmp_path, again, SpyJudge(), plan_hash=plan["plan_hash"])
    assert again.asked == []
    assert result["bought_images"] == 0


# ------------------------------------------- 2. the face gate rejects before the vision model


@pytest.mark.skipif(not detector_available(), reason="YuNet is not installed")
def test_a_candidate_with_a_face_is_rejected_by_the_face_gate_and_never_judged(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    # The real detector: the Nepal scene-6 still (a woman's face) and a ridge with nobody.
    assert count_faces(FACE).faces >= 1
    assert count_faces(NO_FACE[0]).faces == 0
    adapter = SpyStills(pictures=lambda prompt, call: [FACE, NO_FACE[0]])
    judge = SpyJudge()

    approved_run(engine, storyboard_id, tmp_path, adapter, judge, face_counter=count_faces)

    face_sha = sha(FACE)
    rows = takes(engine, storyboard_id)
    with_face = [t for t in rows if t.sha256 == face_sha]
    assert len(with_face) == 4
    assert all(t.status == "REJECTED" for t in with_face)
    assert all("YuNet" in (t.failure_detail or "") for t in with_face)
    # The vision model looked only at the candidates that passed the local checks.
    assert len(judge.looked_at) == 4
    assert not any(sha(Path(p)) == face_sha for p in judge.looked_at)
    assert all(t.status == "APPROVED" for t in rows if t.sha256 == sha(NO_FACE[0]))


# ------------------------------------------- 3. two re-rolls, positive words, then the Owner


def test_a_failing_scene_is_rerolled_twice_with_positive_words_then_needs_the_owner(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        # Scene 2's words always come back with a face in both candidates.
        return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)

    adapter, judge = SpyStills(pictures=pictures), SpyJudge()

    result = approved_run(engine, storyboard_id, tmp_path, adapter, judge)

    scene_two = [c for c in adapter.asked if SUBJECTS[2] in c["prompt"]]
    assert MAX_REROLLS == 2
    assert len(scene_two) == 1 + MAX_REROLLS
    assert "faces not visible" not in scene_two[0]["prompt"]
    for call in scene_two[1:]:
        assert "figures small and distant, seen from behind, faces not visible" in call["prompt"]
        assert "avoid" not in call["prompt"].lower()

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[2]["status"] == "NEEDS_OWNER"
    assert "Proprietar" in by_scene[2]["reason"]
    assert by_scene[2]["rerolls"] == MAX_REROLLS
    # The other scenes go on; scene 2 is never pushed on with a failing still.
    assert all(by_scene[n]["status"] == "APPROVED" for n in (1, 3, 4))
    rows = [t for t in takes(engine, storyboard_id) if t.scene_number == 2]
    assert len(rows) >= 1 and all(t.status == "REJECTED" for t in rows)
    assert result["needs_owner"] == [2]
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.still_needs_owner")
        ).all()
        assert [e.payload["scene_number"] for e in events] == [2]


def test_without_a_passing_scene_one_no_later_scene_is_bought(engine, tmp_path):
    """Scene 1 is Figure 1 for the film: until it passes, buying the rest is buying blind."""
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        return [FACE, FACE] if SUBJECTS[1] in prompt else list(NO_FACE)

    adapter = SpyStills(pictures=pictures)

    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert len(adapter.asked) == 1 + MAX_REROLLS
    assert all(SUBJECTS[1] in c["prompt"] for c in adapter.asked)
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "NEEDS_OWNER"
    assert all(by_scene[n]["status"] == "NOT_BOUGHT" for n in (2, 3, 4))
    assert "Scena 1" in by_scene[2]["reason"]


# --------------------------------------------------------- 4. never a video model, anywhere


def test_no_image_to_video_method_is_called_anywhere_in_the_stage(engine, tmp_path, monkeypatch):
    from app.media import assembler, factory
    from app.providers import runway

    called: list[str] = []

    def forbidden(name):
        def spy(*_args, **_kwargs):
            called.append(name)
            raise AssertionError(f"{name} was called by the stills step")

        return spy

    for owner, name in (
        (runway.RunwayVideoAdapter, "create_generation"),
        (runway.RunwayVideoAdapter, "estimate_generation"),
        (assembler, "_generate_motion"),
        (assembler, "_quote_motion"),
        (assembler, "motion_request"),
        (factory, "motion_for_scene"),
    ):
        monkeypatch.setattr(owner, name, forbidden(f"{getattr(owner, '__name__', owner)}.{name}"))
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills()

    approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert called == []
    assert len(adapter.asked) == 4
    assert not hasattr(stills_stage, "image_to_video")


# ------------------------------------------------- 5. the Owner's yes, bound to this plan


def test_the_stage_refuses_without_an_approval_bound_to_the_current_plan_hash(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    adapter, judge = SpyStills(), SpyJudge()
    plan = stills_plan(engine, storyboard_id)
    assert plan["cost_credits"] == 4 * 18
    assert plan["cap_credits"] == 4 * 18 * (1 + MAX_REROLLS)

    # No answer yet: the Owner is asked about exactly this plan, and nothing is bought.
    with pytest.raises(StillsStageRefused) as first:
        run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash=plan["plan_hash"])
    assert first.value.status == "NEEDS_APPROVAL"
    assert first.value.http_status == 202
    with Session(engine) as session:
        request = session.get(ApprovalRequest, first.value.approval_id)
        assert request.action == "media.stills_purchase"
        assert request.subject == storyboard_id
        assert request.proposed_diff == {
            "plan_hash": plan["plan_hash"],
            "step": "stills",
            "cap_credits": plan["cap_credits"],
        }
        # The question carries the step's cap, the most his yes lets it spend (MONEY-08).
        assert request.cost_usd == pytest.approx(2.16)
    assert adapter.asked == []

    # A hash that is not the current plan's is refused before the Owner's yes is looked at.
    with pytest.raises(StillsStageRefused) as other:
        run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash="b" * 64)
    assert other.value.status == "STALE_PLAN"
    assert other.value.http_status == 409
    assert "foaia de filmare" in other.value.reason_ro.lower()

    # He says yes; then a scene's words change. The yes was about the old plan.
    answer(engine, first.value.approval_id, "APPROVED")
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        ).one()
        changed = row.visual_prompt.replace("seedlings", "rice seedlings")
        row.visual_prompt = changed
        row.prompt_json = {**row.prompt_json, "still_prompt": changed}
    with pytest.raises(StillsStageRefused) as stale:
        run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash=plan["plan_hash"])
    assert stale.value.status == "STALE_PLAN"
    assert adapter.asked == []
    with Session(engine) as session:
        assert session.get(ApprovalRequest, first.value.approval_id).consumed_at is None

    # The new plan needs its own yes; the old one buys nothing.
    fresh = stills_plan(engine, storyboard_id)
    assert fresh["plan_hash"] != plan["plan_hash"]
    with pytest.raises(StillsStageRefused) as again:
        run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash=fresh["plan_hash"])
    assert again.value.status == "NEEDS_APPROVAL"
    assert again.value.approval_id != first.value.approval_id
    answer(engine, again.value.approval_id, "APPROVED")
    run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash=fresh["plan_hash"])
    assert len(adapter.asked) == 4
    with Session(engine) as session:
        assert session.get(ApprovalRequest, again.value.approval_id).consumed_at is not None

    # A spent yes buys nothing a second time.
    bought = len(adapter.asked)
    with pytest.raises(StillsStageRefused):
        run(engine, storyboard_id, tmp_path, adapter, judge, plan_hash=fresh["plan_hash"])
    assert len(adapter.asked) == bought


def test_a_lint_block_stops_the_step_before_the_owner_is_asked(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 2
            )
        ).one()
        bad = row.visual_prompt + " Environment: NEPAL_CLIMATE_CRISIS. Palette: #2E4A66."
        row.visual_prompt = bad
        row.prompt_json = {**row.prompt_json, "still_prompt": bad}
    adapter = SpyStills()

    with pytest.raises(StillsStageRefused) as refused:
        run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert refused.value.status == "LINT_BLOCKED"
    assert refused.value.http_status == 409
    assert any(f.code == "ENUM_CODE" for f in refused.value.findings)
    assert "NEPAL_CLIMATE_CRISIS" in refused.value.reason_ro
    assert adapter.asked == []
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == []


def test_a_balance_below_the_first_round_stops_the_step_before_the_yes_is_spent(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    plan = stills_plan(engine, storyboard_id)
    # The Owner's rule of 2026-10-03: the step starts on its first round x 1.15, not its cap.
    adapter = SpyStills(balance=plan["cost_credits"] * 1.15 - 1)

    with pytest.raises(StillsStageRefused) as asked:
        run(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    # The balance is read before the Owner is asked, so he is not asked to buy what the
    # account cannot pay for.
    assert asked.value.status == "LOW_BALANCE"
    assert adapter.asked == []
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == []


def test_the_measured_balance_drop_is_written_on_each_take(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    adapter = SpyStills(balance=5000.0)

    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert result["balance_before"] == 5000.0
    assert result["balance_after"] == 5000.0 - 72
    assert result["spent_credits_measured"] == 72
    rows = takes(engine, storyboard_id)
    assert all(t.credits_measured == pytest.approx(9.0) for t in rows)
    assert all(t.credits_quoted == pytest.approx(9.0) for t in rows)


def test_a_vendor_refusal_is_a_refused_take_and_the_scene_waits_for_the_owner(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    class Refusing(SpyStills):
        async def generate_candidates(self, prompt, **kwargs):
            if SUBJECTS[3] in prompt:
                self.asked.append({"prompt": prompt, **kwargs})
                raise MediaProviderError(
                    "Runway image task failed",
                    code="SAFETY.INPUT.TEXT",
                    detail="The prompt was flagged",
                )
            return await super().generate_candidates(prompt, **kwargs)

    adapter = Refusing()
    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[3]["status"] == "NEEDS_OWNER"
    assert by_scene[3]["failure_kind"] == "SAFETY"
    # A safety refusal is never resubmitted with the same words.
    assert len([c for c in adapter.asked if SUBJECTS[3] in c["prompt"]]) == 1
    refused = [t for t in takes(engine, storyboard_id) if t.status == "REFUSED"]
    assert len(refused) == 1 and refused[0].failure_code == "SAFETY.INPUT.TEXT"
    assert by_scene[4]["status"] == "APPROVED"


# ------------------------------------------------- the Runway body: outputCount, 2K, Figure 1


def png(width: int, height: int) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00" * width * 3 for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SEEDREAM = {
    "tasks": ["text_to_image"],
    "ratios": {"text_to_image": ["1080:1920", "1530:2720", "2720:1530"]},
    "fields": {"text_to_image": ["model", "promptText", "ratio", "referenceImages", "outputCount"]},
    "needs_references": {"text_to_image": False},
}


class Transport:
    """Runway's HTTPS boundary, faked: no request leaves the machine, no credit is spent."""

    def __init__(self, outputs: int = 2):
        self.calls: list[dict] = []
        self.outputs = outputs
        self.tasks = 0

    def __call__(self, host, method, path, headers, body=None, **_kwargs):
        self.calls.append({"host": host, "method": method, "path": path, "body": body})
        if path == "/v1/text_to_image":
            self.tasks += 1
            return (
                {"id": f"task-{self.tasks}", "estimatedCost": {"credits": 18}},
                b"",
                "application/json",
            )
        if path.startswith("/v1/tasks/"):
            urls = [f"https://files.test/{path[-6:]}-{n}.png" for n in range(self.outputs)]
            return {"status": "SUCCEEDED", "output": urls}, b"", "application/json"
        if host == "files.test":
            return None, png(1530, 2720), "image/png"
        raise AssertionError(f"unexpected request {host}{path}")


def runway_adapter(monkeypatch, contract=None, outputs=2):
    from app.providers import runway

    transport = Transport(outputs)
    monkeypatch.setattr(runway, "request", transport)
    adapter = runway.RunwayImageAdapter("key", "seedream5_pro", dict(contract or SEEDREAM))
    return adapter, transport


def test_runway_gets_output_count_two_at_1530x2720_with_figure_one(monkeypatch):
    adapter, transport = runway_adapter(monkeypatch)
    reference = png(16, 28)

    results = asyncio.run(
        adapter.generate_candidates(
            "A wide view of ridges.", ratio="1530:2720", count=2, references=[reference]
        )
    )

    submits = [c for c in transport.calls if c["path"] == "/v1/text_to_image"]
    assert len(submits) == 1
    body = json.loads(submits[0]["body"])
    assert body["model"] == "seedream5_pro"
    assert body["ratio"] == "1530:2720"
    assert body["outputCount"] == 2
    assert body["referenceImages"] == [
        {"uri": "data:image/png;base64," + base64.b64encode(reference).decode("ascii")}
    ]
    assert "seed" not in body
    assert len(results) == 2
    assert {(r.width, r.height) for r in results} == {(1530, 2720)}
    assert [r.raw_response["output_index"] for r in results] == [0, 1]
    assert all(r.raw_response["reference_images"] == 1 for r in results)
    assert all(r.raw_response["reference_verified"] is False for r in results)
    assert adapter.last_estimated_credits == 18


def test_runway_without_output_count_in_its_contract_buys_one_task_per_candidate(monkeypatch):
    contract = {**SEEDREAM, "fields": {"text_to_image": ["model", "promptText", "ratio"]}}
    adapter, transport = runway_adapter(monkeypatch, contract, outputs=1)

    results = asyncio.run(adapter.generate_candidates("ridges", ratio="1530:2720", count=2))

    submits = [json.loads(c["body"]) for c in transport.calls if c["path"] == "/v1/text_to_image"]
    assert len(submits) == 2
    assert all("outputCount" not in body for body in submits)
    assert len(results) == 2
    # The two tasks' prices are added, not the last one kept.
    assert adapter.last_estimated_credits == 36


def test_runway_refuses_a_ratio_its_contract_does_not_list_before_any_call(monkeypatch):
    contract = {**SEEDREAM, "ratios": {"text_to_image": ["1080:1920"]}}
    adapter, transport = runway_adapter(monkeypatch, contract)

    with pytest.raises(MediaProviderError):
        asyncio.run(adapter.generate_candidates("ridges", ratio="1530:2720", count=2))

    assert transport.calls == []


# --------------------------------------- a still task the vendor accepted is on the books at once
#
# The stills step used to keep a task's id nowhere: a poll past IMAGE_DEADLINE_SECONDS raised,
# the request was recorded REFUSED with no id, and the next run bought the scene again. Now
# each task is a SUBMITTED take with the vendor's id the moment it is accepted; a task whose
# stills do not arrive keeps the scene IN_FLIGHT, it is collected with a GET, and the
# collected candidates are judged before anything is bought for that scene.


class OpenTaskStills(SpyStills):
    """The image vendor whose task for the prompts in ``stuck`` is accepted (and charged) but
    whose stills do not arrive; ``answers`` scripts what a later GET says about a task."""

    def __init__(self, *args, stuck=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.stuck = set(stuck)
        self.answers: dict[str, dict] = {}
        self.collected: list[str] = []

    async def generate_candidates(self, prompt, *, on_submitted=None, **kwargs):
        if any(SUBJECTS[n] in prompt for n in self.stuck):
            self.asked.append({"prompt": prompt, **kwargs})
            task_id = f"img-task-{len(self.asked)}"
            if on_submitted is not None:
                on_submitted(task_id)
            raise TaskStillOpen("Runway image task did not finish", task_id=task_id)
        return await super().generate_candidates(prompt, on_submitted=on_submitted, **kwargs)

    async def collect_task(self, task_id):
        self.collected.append(task_id)
        return self.answers.get(task_id, {"state": "RUNNING", "outputs": []})


def approved_again(engine, storyboard_id, tmp_path, adapter, judge):
    """approved_run for an adapter that already bought something: asked, nothing bought."""
    before = len(adapter.asked)
    with pytest.raises(StillsStageRefused) as asked:
        run(engine, storyboard_id, tmp_path, adapter, judge)
    assert asked.value.status == "NEEDS_APPROVAL"
    assert len(adapter.asked) == before, "a question bought a still"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da.")
    return run(engine, storyboard_id, tmp_path, adapter, judge)


def _done(*files: Path) -> dict:
    return {"state": "SUCCEEDED", "outputs": [(path.read_bytes(), "image/jpeg") for path in files]}


def test_every_candidate_is_written_with_its_task_id_before_it_is_judged(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    approved_run(engine, storyboard_id, tmp_path, SpyStills(), SpyJudge())

    rows = takes(engine, storyboard_id)
    assert len(rows) == 8
    assert {t.remote_task_id for t in rows} == {f"img-task-{n}" for n in (1, 2, 3, 4)}
    # Judged: no candidate keeps the "not judged yet" mark.
    assert all(t.failure_code is None for t in rows if t.status in ("APPROVED", "PAID"))
    assert not [t for t in rows if t.status == "SUBMITTED"]


def test_a_still_task_that_does_not_arrive_stays_submitted_and_is_not_bought_again(
    engine, tmp_path
):
    storyboard_id = a_film(engine, tmp_path)
    adapter = OpenTaskStills(stuck={1})

    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "IN_FLIGHT"
    assert all(by_scene[n]["status"] == "NOT_BOUGHT" for n in (2, 3, 4))
    assert result["stopped"]
    (take,) = takes(engine, storyboard_id)
    assert (take.status, take.remote_task_id) == ("SUBMITTED", "img-task-1")
    assert take.credits_quoted == pytest.approx(18)
    assert result["spent_credits_quoted"] == 18

    plan = stills_plan(engine, storyboard_id)
    assert plan["pending"] == [1] and 1 not in plan["to_buy"]

    # The next run: the vendor still working. Asked about it, nothing bought for scene 1.
    again = approved_again(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert adapter.collected == ["img-task-1"] * 2
    assert len([c for c in adapter.asked if SUBJECTS[1] in c["prompt"]]) == 1
    assert {e["scene_index"]: e["status"] for e in again["scenes"]}[1] == "IN_FLIGHT"


def test_collected_candidates_are_judged_before_the_scene_is_bought(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)
    adapter = OpenTaskStills(stuck={1})
    approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    adapter.stuck.clear()
    adapter.answers["img-task-1"] = _done(*NO_FACE)
    judge = SpyJudge()
    result = approved_again(engine, storyboard_id, tmp_path, adapter, judge)

    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "APPROVED"
    assert by_scene[1]["judged_collected"] == 2
    # Scene 1 was bought once, ever; the others now have their Figure 1.
    assert len([c for c in adapter.asked if SUBJECTS[1] in c["prompt"]]) == 1
    assert all(by_scene[n]["status"] == "APPROVED" for n in (2, 3, 4))
    scene_one = [t for t in takes(engine, storyboard_id) if t.scene_number == 1]
    assert sorted(t.status for t in scene_one) == ["APPROVED", "PAID"]
    assert {t.remote_task_id for t in scene_one} == {"img-task-1"}
    assert all(t.failure_code is None for t in scene_one)
    assert len(judge.looked_at) == 8


def test_a_paid_candidate_never_judged_is_judged_not_bought_again(engine, tmp_path):
    """A process killed between a candidate's row and its judgement left it PAID and unjudged;
    the plan used to buy the scene again. It is judged first (0 credits)."""
    from app.media.assembler import UNJUDGED_FAILURE_CODE, record_take, still_fields, take_hash

    storyboard_id = a_film(engine, tmp_path)
    with Session(engine) as session:
        visual = (
            session.scalars(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
                )
            )
            .one()
            .visual_prompt
        )
    folder = tmp_path / "left_behind"
    folder.mkdir()
    for n, source in enumerate(NO_FACE, start=1):
        path = folder / f"scene_01_c{n}.jpg"
        path.write_bytes(source.read_bytes())
        record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=1,
            kind="still",
            prompt_hash=take_hash(still_fields(visual, None), "seedream5_pro"),
            model_id="seedream5_pro",
            resolution=STILL_RATIO,
            status="PAID",
            correlation_id="crash",
            credits_quoted=9.0,
            path=path,
            sha256=sha(path),
            failure_code=UNJUDGED_FAILURE_CODE,
            remote_task_id="img-task-old",
        )
    plan = stills_plan(engine, storyboard_id)
    assert plan["pending"] == [1] and plan["to_buy"] == [2, 3, 4]

    adapter = SpyStills()
    result = approved_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())

    assert not [c for c in adapter.asked if SUBJECTS[1] in c["prompt"]]
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "APPROVED" and by_scene[1]["judged_collected"] == 2
    assert len(adapter.asked) == 3


def test_runway_hears_each_task_before_it_is_polled_and_an_open_task_keeps_its_id(monkeypatch):
    from app.providers import runway

    adapter, transport = runway_adapter(monkeypatch)
    heard: list[tuple[str, int]] = []
    monkeypatch.setattr(runway, "IMAGE_DEADLINE_SECONDS", 0)

    def running(host, method, path, headers, body=None, **kwargs):
        if path.startswith("/v1/tasks/"):
            transport.calls.append({"host": host, "method": method, "path": path, "body": body})
            return {"status": "RUNNING"}, b"", "application/json"
        return Transport.__call__(transport, host, method, path, headers, body, **kwargs)

    monkeypatch.setattr(runway, "request", running)

    with pytest.raises(TaskStillOpen) as excinfo:
        asyncio.run(
            adapter.generate_candidates(
                "ridges",
                ratio="1530:2720",
                count=2,
                on_submitted=lambda task: heard.append((task, len(transport.calls))),
            )
        )

    assert excinfo.value.task_id == "task-1"
    # Heard right after the submit, before the first poll.
    assert heard == [("task-1", 1)]
    assert [c["path"] for c in transport.calls] == ["/v1/text_to_image", "/v1/tasks/task-1"]


def test_runway_collects_a_task_by_its_id_with_a_get_only(monkeypatch):
    adapter, transport = runway_adapter(monkeypatch)

    answer = asyncio.run(adapter.collect_task("task-7"))

    assert answer["state"] == "SUCCEEDED" and len(answer["outputs"]) == 2
    assert all(kind == "image/png" for _bytes, kind in answer["outputs"])
    assert {c["method"] for c in transport.calls} == {"GET"}
    assert transport.calls[0]["path"] == "/v1/tasks/task-7"


# ----------------------------- the memory of a scene: never bought again without the Owner
#
# 2026-10-02 (NO_REBUY_RECOVERY_REFERENCES): a scene the gate handed to the Owner, or one the
# vendor refused for its words, was in the next plan's purchase again: under the MODE rule the
# next day bought it again, unasked. It now stays out of the purchase until he decides.


def _scene_two_shows_a_face(prompt, call):
    return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)


def test_a_scene_the_gate_sent_to_the_owner_is_held_out_of_the_next_plan(engine, tmp_path):
    from app.media.shooting_sheet import decide_sheet_take

    storyboard_id = a_film(engine, tmp_path)
    approved_run(
        engine, storyboard_id, tmp_path, SpyStills(pictures=_scene_two_shows_a_face), SpyJudge()
    )

    plan = stills_plan(engine, storyboard_id)

    assert plan["to_buy"] == [] and plan["held"] == [2]
    (scene_two,) = [s for s in plan["scenes"] if s["scene_index"] == 2]
    assert scene_two["status"] == "NEEDS_OWNER"
    assert "Proprietar" in scene_two["reason_ro"]
    # The next run buys nothing and asks nothing.
    again = SpyStills()
    result = run(engine, storyboard_id, tmp_path, again, SpyJudge(), plan_hash=plan["plan_hash"])
    assert again.asked == []
    assert {e["scene_index"]: e["status"] for e in result["scenes"]}[2] == "NEEDS_OWNER"

    # His look at the contact sheet (he rejects what he saw) lifts the hold: one more round.
    rejected = next(t for t in takes(engine, storyboard_id) if t.scene_number == 2)
    decide_sheet_take(engine, rejected.id, "REJECTED", note="Fețe; încă o dată.")
    assert stills_plan(engine, storyboard_id)["to_buy"] == [2]


def test_a_safety_refusal_holds_the_scene_out_of_the_next_plan(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path)

    class Refusing(SpyStills):
        async def generate_candidates(self, prompt, **kwargs):
            if SUBJECTS[3] in prompt:
                self.asked.append({"prompt": prompt, **kwargs})
                raise MediaProviderError(
                    "Runway image task failed",
                    code="SAFETY.INPUT.TEXT",
                    detail="The prompt was flagged",
                )
            return await super().generate_candidates(prompt, **kwargs)

    approved_run(engine, storyboard_id, tmp_path, Refusing(), SpyJudge())

    plan = stills_plan(engine, storyboard_id)
    assert plan["to_buy"] == [] and plan["held"] == [3]


def test_a_first_scene_held_for_the_owner_leaves_nothing_to_buy(engine, tmp_path):
    """Scene 1 is Figure 1: while it waits for the Owner the later scenes cannot be bought,
    so the plan does not offer them (a step that would buy nothing is not a purchase)."""
    storyboard_id = a_film(engine, tmp_path)

    def pictures(prompt, call):
        return [FACE, FACE] if SUBJECTS[1] in prompt else list(NO_FACE)

    approved_run(engine, storyboard_id, tmp_path, SpyStills(pictures=pictures), SpyJudge())

    plan = stills_plan(engine, storyboard_id)
    assert plan["held"] == [1]
    assert plan["to_buy"] == []
    assert plan["cost_credits"] == 0


def test_a_paid_unjudged_candidate_is_judged_with_nothing_else_to_buy(engine, tmp_path):
    """The only open scene holds candidates collected after their step (the watchdog took
    them in) and never judged: the plan has nothing to buy, so no step would ever run for it.
    The day settles it: judged (vision tokens only), no image bought, no yes asked."""
    from app.media.assembler import UNJUDGED_FAILURE_CODE, record_take, still_fields, take_hash

    storyboard_id = a_film(engine, tmp_path)
    approved_run(engine, storyboard_id, tmp_path, SpyStills(), SpyJudge())
    # Scene 1's approved still is retired by the Owner; collected candidates wait for scene 1.
    with Session(engine) as session, session.begin():
        for row in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.scene_number == 1
            )
        ):
            row.status = "REJECTED"
            row.failure_code = "REDO.OWNER"
        visual = (
            session.scalars(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
                )
            )
            .one()
            .visual_prompt
        )
    folder = tmp_path / "collected"
    folder.mkdir()
    for n, source in enumerate(NO_FACE, start=1):
        path = folder / f"scene_01_collected_c{n}.jpg"
        path.write_bytes(source.read_bytes() + b"collected")
        record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=1,
            kind="still",
            prompt_hash=take_hash(still_fields(visual, None), "seedream5_pro"),
            model_id="seedream5_pro",
            resolution=STILL_RATIO,
            status="PAID",
            correlation_id="watchdog",
            credits_quoted=9.0,
            path=path,
            sha256=sha(path),
            failure_code=UNJUDGED_FAILURE_CODE,
            remote_task_id="img-task-late",
        )
    plan = stills_plan(engine, storyboard_id)
    assert plan["to_buy"] == [] and plan["pending"] == [1]

    with Session(engine) as session:
        questions = len(session.scalars(select(ApprovalRequest)).all())
    adapter, judge = SpyStills(), SpyJudge()
    settled = stills_stage.settle_stills(
        engine,
        storyboard_id,
        str(uuid4()),
        image_adapter=adapter,
        registry=None,
        judge=judge,
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
    )

    assert adapter.asked == []
    assert len(judge.looked_at) == 2
    assert {e["scene_index"]: e["status"] for e in settled["scenes"]} == {1: "APPROVED"}
    with Session(engine) as session:
        assert len(session.scalars(select(ApprovalRequest)).all()) == questions
    approved_now = [
        t for t in takes(engine, storyboard_id) if t.scene_number == 1 and t.status == "APPROVED"
    ]
    assert len(approved_now) == 1 and approved_now[0].remote_task_id == "img-task-late"
