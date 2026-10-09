"""A redone still is bought on the prompt the studio writes today, never on stale stored words.

Film babcf272 (2026-10-09): scene 5's still came back as three stacked panels (an atom in the
tunnel, a flat black band, the empty tunnel) and its clip animated that triptych. Its stored
still prompt described a sequence of moments ("..., then the empty accelerator tunnel from
scene 1."). The package is compiled once, when the shots are written; «Refă imaginea» bought
the STORED words again, so a compiler fixed since could never reach a film already planned.

A still redo now compiles that one scene again from its stored plan with today's compiler
(deterministic, 0 credits, no language model):

- the Owner's redo plan carries the new still prompt and says so in Romanian, and its hash is
  bound to the new words: his yes buys what he was shown;
- the purchase rewrites that scene's package (prompt_json, visual_prompt) in the transaction
  that spends his yes, with one ``media.prompts_rewritten`` event (a «media.prompt*» event,
  so a letter saying the prompt was rewritten is proven); no other scene is touched, so every
  other bought take keeps matching its prompt (BOUGHT in the motion plan);
- the motion redo that follows reads the rewritten package;
- a scene whose words are already today's is left exactly as it was: no event, no write;
- his approval card says the prompt was rewritten, not only the sheet's drawer;
- pictures already paid for on the retired words are collected, never approved by the press;
- an episode of the serial keeps its own words; a package the compiler cannot read is refused.

Every provider is faked (spy adapters); no socket is opened (conftest refuses them). The stale
prompt is written by the test, so nothing here depends on how the compiler words a scene.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.reviews import check_work_claims
from app.media.assembler import (
    SCENE_PROMPTS_REWRITTEN_EVENT,
    UNJUDGED_FAILURE_CODE,
    SceneRedoRefused,
    motion_plan,
    record_take,
    redo_plan,
    redo_scene,
    still_fields,
    take_hash,
)
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.prompt_agent import compile_prompts, motion_prompt_for
from app.media.stills_stage import STILL_RATIO
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SCENES, SEEDANCE, Account, Models, SpyVideo, a_film
from test_scene_redo import approvals, coloured_clip, filmed, redo_motion, takes
from test_stills_stage import NO_FACE, SpyJudge, SpyStills, faces_in, sha

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

#: What a stale compiler left in scene 3's stored words: a second moment after the first.
STALE_TAIL = " Then the empty tunnel from scene 1, which sits still."
STALE_MOTION = "The cluster dissolves into the tunnel view, which sits empty and still."


def compiled_film(engine, tmp_path, *, stale: int | None = None) -> tuple[str, dict[int, dict]]:
    """A film of four filmed scenes whose packages carry a plan (subject, action, ...) compiled
    as `write_shot_prompts` compiles it, an APPROVED still per scene recorded under its words,
    and, for scene ``stale``, still and motion words a fixed compiler would not write.

    Returns the storyboard and each scene's clean compiled prompts."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    clean: dict[int, dict] = {}
    moves: list[str] = []
    with Session(engine) as session, session.begin():
        bible = dict(session.get(Storyboard, storyboard_id).visual_bible_json or {})
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        for row in rows:
            n = int(row.scene_index)
            subject, move, world = SCENES[n]
            plan = {
                **dict(row.prompt_json or {}),
                "story_purpose": row.story_purpose or "EVIDENCE",
                "subject": subject,
                "action": "The view holds steady while the weather moves through it.",
                "environment": "The Himalayan foothills in the late monsoon.",
                "camera": f"{move}, natural lens",
                "lighting": "soft overcast daylight",
                "composition": "subject in the upper two thirds of a vertical frame",
                "motion": world,
                "camera_move": move,
                "characters": [],
                "scene_kind": "LIVE",
                "shot_type": row.shot_type,
            }
            compiled = compile_prompts(plan, bible, previous_moves=moves)
            if compiled["camera_move"]:
                moves.append(compiled["camera_move"])
            package = {**plan, **compiled}
            clean[n] = package
            words = compiled["still_prompt"]
            if n == stale:
                words = compiled["still_prompt"] + STALE_TAIL
                package = {
                    **package,
                    "still_prompt": words,
                    "motion_prompt": STALE_MOTION,
                    "motion_intent": {**compiled["motion_intent"], "world": STALE_MOTION},
                }
            row.prompt_json = package
            row.visual_prompt = words
            # The approved still was bought on the words the scene carried then.
            still = session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == n,
                    SceneTake.kind == "still",
                )
            ).one()
            still.prompt_hash = take_hash(still_fields(words, None), "seedream5_pro")
    return storyboard_id, clean


def packages(engine, storyboard_id: str) -> dict[int, tuple[str, str]]:
    """Each scene's package and visual prompt, as canonical text (byte-for-byte comparable)."""
    with Session(engine) as session:
        rows = session.scalars(
            select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
        ).all()
        return {
            int(row.scene_index): (
                json.dumps(row.prompt_json, sort_keys=True, ensure_ascii=False),
                str(row.visual_prompt),
            )
            for row in rows
        }


def rewritten_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
            )
        )
        session.expunge_all()
        return rows


def statuses(engine, storyboard_id: str) -> dict[int, tuple[str, str | None]]:
    """Each scene's line in the motion plan: its status and the take it stands on."""
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    return {item["scene_index"]: (item["status"], item["take_id"]) for item in plan["scenes"]}


def still_redo(engine, storyboard_id, tmp_path, images, plan_hash):
    return redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="still",
        scene_index=3,
        plan_hash=plan_hash,
        image_adapter=images,
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
    )


def approved_still_redo(engine, storyboard_id, tmp_path, images, plan):
    """Asked once (nothing bought, nothing rewritten), answered yes as the Owner, then run."""
    before = packages(engine, storyboard_id)
    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])
    assert asked.value.status == "NEEDS_APPROVAL", asked.value.reason_ro
    assert images.asked == [], "a question bought a still"
    assert packages(engine, storyboard_id) == before, "a question rewrote a package"
    assert rewritten_events(engine) == []
    answer(engine, asked.value.approval_id, "APPROVED", note="Refă imaginea scenei 3.")
    return still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])


# --------------------------------------- 1. a stale prompt: shown, bound, bought, stored once


def test_a_stale_still_prompt_is_rewritten_for_its_scene_alone_and_bought_as_shown(
    engine, tmp_path
):
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    stale_words = clean[3]["still_prompt"] + STALE_TAIL
    new_words = " ".join(clean[3]["still_prompt"].split())
    before = packages(engine, storyboard_id)
    bought_before = statuses(engine, storyboard_id)
    assert {n: status for n, (status, _take) in bought_before.items()} == {
        1: "BOUGHT",
        2: "BOUGHT",
        3: "BOUGHT",
        4: "BOUGHT",
    }

    plan = redo_plan(engine, storyboard_id, "still", 3)

    # The plan the Owner approves carries the words that will be sent, and says so.
    assert plan["still_prompt"] == new_words
    rewrite = plan["prompt_rewrite"]
    assert rewrite["old_still_prompt"] == stale_words
    assert rewrite["still_prompt"] == new_words
    assert rewrite["old_motion_prompt"] == STALE_MOTION
    assert rewrite["motion_prompt"] == " ".join(clean[3]["motion_prompt"].split())
    assert plan["reason_ro"].startswith("Promptul imaginii a fost rescris de studio")
    assert "scos „Then the empty tunnel from scene 1, which sits still.”" in plan["reason_ro"]
    assert plan["buyable"] is True and plan["credits"] == 18

    images = SpyStills(balance=1_000)
    result = approved_still_redo(engine, storyboard_id, tmp_path, images, plan)

    # The vendor was sent the new words, once.
    assert len(images.asked) == 1
    sent = images.asked[0]["prompt"]
    assert sent.startswith(new_words) and "empty tunnel" not in sent
    assert result["still"]["status"] == "APPROVED"
    assert result["still"]["prompt_rewritten"] is True

    # Scene 3's package is today's: the compiled fields merged in, its visual prompt the new
    # still prompt; every other scene is byte-for-byte what it was.
    after = packages(engine, storyboard_id)
    for n in (1, 2, 4):
        assert after[n] == before[n], f"scene {n}'s package was touched"
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        )
        package, visual = dict(row.prompt_json), row.visual_prompt
    assert visual == clean[3]["still_prompt"] and package["still_prompt"] == visual
    for field in ("motion_prompt", "motion_intent", "camera_move", "look_block", "subject"):
        assert package[field] == clean[3][field], field

    (event,) = rewritten_events(engine)
    assert event.aggregate_id == storyboard_id
    assert event.payload["storyboard_id"] == storyboard_id
    assert event.payload["scene_index"] == 3
    assert event.payload["old_still_prompt"] == stale_words
    assert event.payload["still_prompt"] == new_words
    assert event.payload["old_motion_prompt"] == STALE_MOTION
    assert event.payload["motion_prompt"] == rewrite["motion_prompt"]
    assert event.payload["reason"] == "redo"
    assert event.payload["plan_hash"] == plan["plan_hash"]

    # The new still is recorded under the words it was bought on.
    new_stills = [
        t
        for t in takes(engine, storyboard_id, "still")
        if t.scene_number == 3 and t.status == "APPROVED"
    ]
    assert [t.prompt_hash for t in new_stills] == [
        take_hash(still_fields(visual, None), "seedream5_pro")
    ]

    # The other scenes' bought shots still match their prompts: BOUGHT, on the same takes.
    bought_after = statuses(engine, storyboard_id)
    for n in (1, 2, 4):
        assert bought_after[n] == bought_before[n], f"scene {n} is no longer bought"
    assert bought_after[3][0] == "PLANNED"

    # The words are today's now: the next plan rewrites nothing.
    again = redo_plan(engine, storyboard_id, "still", 3)
    assert "prompt_rewrite" not in again
    assert again["still_prompt"] == new_words
    assert "rescris" not in again["reason_ro"]


# -------------------------------------------- 2. the motion redo reads the rewritten package


def test_the_motion_redo_after_a_rewritten_still_sends_the_rewritten_motion(engine, tmp_path):
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    plan = redo_plan(engine, storyboard_id, "still", 3)
    approved_still_redo(engine, storyboard_id, tmp_path, SpyStills(balance=1_000), plan)

    expected, _negative = motion_prompt_for(clean[3], "seedance2_5", None)
    motion = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert motion["motion_prompt"] == expected
    assert STALE_MOTION not in motion["motion_prompt"]

    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=coloured_clip(tmp_path, "olive")))
    with pytest.raises(SceneRedoRefused) as asked:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, motion["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED")
    redo_motion(engine, storyboard_id, tmp_path, models, account, 3, motion["plan_hash"])

    (post,) = models.spies["seedance2_5"].asked
    assert post["prompt"] == expected


# ---------------------------------------------- 3. today's words already: nothing is written


def test_a_still_redo_whose_prompt_is_current_rewrites_nothing(engine, tmp_path):
    storyboard_id, clean = compiled_film(engine, tmp_path)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    before = packages(engine, storyboard_id)

    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert "prompt_rewrite" not in plan
    assert plan["still_prompt"] == " ".join(clean[3]["still_prompt"].split())
    assert "rescris" not in plan["reason_ro"]

    images = SpyStills(balance=1_000)
    result = approved_still_redo(engine, storyboard_id, tmp_path, images, plan)

    assert len(images.asked) == 1
    assert images.asked[0]["prompt"].startswith(plan["still_prompt"])
    assert result["still"]["prompt_rewritten"] is False
    assert packages(engine, storyboard_id) == before, "a current package was written"
    assert rewritten_events(engine) == []


# ------------------------------------- 4. his yes is bound to the words, at purchase as well


def test_a_yes_for_one_rewrite_buys_nothing_once_the_stored_words_change(engine, tmp_path):
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)
    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED")

    # The stored words change after his yes: the plan he approved is not the plan of now.
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        )
        row.prompt_json = {**row.prompt_json, "still_prompt": row.visual_prompt + " Again."}
    before = packages(engine, storyboard_id)

    with pytest.raises(SceneRedoRefused) as stale:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])

    assert stale.value.status == "STALE_PLAN"
    assert images.asked == []
    assert packages(engine, storyboard_id) == before
    assert rewritten_events(engine) == []
    with Session(engine) as session:
        assert session.get(ApprovalRequest, asked.value.approval_id).consumed_at is None


class ChangingStills(SpyStills):
    """The image vendor, faked, whose balance read lets another writer change scene 3's plan:
    after the plan was read inside the lease, before the transaction that spends the yes."""

    def __init__(self, change, **kwargs):
        super().__init__(**kwargs)
        self.change = change
        self.armed = False

    async def credit_balance(self):
        if self.armed:
            self.armed = False
            self.change()
        return await super().credit_balance()


def test_a_package_changed_before_the_yes_is_spent_rolls_back_and_spends_nothing(engine, tmp_path):
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    stills_before = {(t.id, t.status) for t in takes(engine, storyboard_id, "still")}

    def rewrite_the_plan() -> None:
        with Session(engine) as session, session.begin():
            row = session.scalar(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == storyboard_id,
                    StoryboardScene.scene_index == 3,
                )
            )
            row.prompt_json = {**row.prompt_json, "lighting": "hard noon sun"}

    images = ChangingStills(rewrite_the_plan, balance=1_000)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED")
    images.armed = True

    with pytest.raises(SceneRedoRefused) as stale:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])

    # Refused by the transaction that would have spent the yes, not before it.
    assert stale.value.status == "STALE_PLAN"
    assert stale.value.reason_ro.startswith("Pachetul scenei 3 s-a schimbat")
    assert images.asked == [], "a still was bought on a plan that had changed"
    assert rewritten_events(engine) == []
    with Session(engine) as session:
        # Rolled back together: his yes unspent, the old still and its shot still in use.
        assert session.get(ApprovalRequest, asked.value.approval_id).consumed_at is None
        assert session.get(SceneTake, shots[3]).status == "APPROVED"
        package = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        ).prompt_json
    assert package["lighting"] == "hard noon sun"
    assert package["still_prompt"].endswith(STALE_TAIL)
    assert {(t.id, t.status) for t in takes(engine, storyboard_id, "still")} == stills_before


# ------------------------------------------- 5. on RunPod Serverless: the round sends today's


def test_a_runpod_still_redo_sends_the_rewritten_prompt_in_its_round(engine, tmp_path, monkeypatch):
    """The redo bought in GPU rounds (`_redo_still_rounds`) sends and records the same new
    words as the per-request redo. The GPU session and every RunPod and bucket call are faked
    (test_runpod_batch's cloud)."""
    from contextlib import contextmanager

    from app.media import gpu_batch
    from test_runpod_batch import PictureCloud, Session_, adapter, stills_table
    from test_stills_stage import NO_FACE

    @contextmanager
    def gpu_session(engine, adapter, *, purpose, permit):
        session = Session_()
        try:
            yield session
        finally:
            session.off_evidence = {
                "before_purge": {"in_queue": 0, "in_progress": 0, "running": 0},
                "purge_removed": 0,
                "off": {"off": True},
                "other_sessions": [],
            }

    monkeypatch.setattr(gpu_batch, "gpu_session", gpu_session)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    before = packages(engine, storyboard_id)
    new_words = " ".join(clean[3]["still_prompt"].split())
    # Two different pictures (nobody in either), so the pair is two files, not one twice.
    drawn: list[int] = []

    def picture(_prompt: str) -> bytes:
        drawn.append(1)
        return NO_FACE[len(drawn) % 2].read_bytes()

    cloud = PictureCloud(picture)
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()

    plan = redo_plan(engine, storyboard_id, "still", 3, table=table, stills_model=made.model)
    assert plan["still_prompt"] == new_words and plan["prompt_rewrite"]

    def go():
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=3,
            plan_hash=plan["plan_hash"],
            image_adapter=made,
            table=table,
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    with pytest.raises(SceneRedoRefused) as asked:
        go()
    assert asked.value.status == "NEEDS_APPROVAL" and not cloud.jobs
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    result = go()

    (job,) = [cloud.jobs[name]["input"]["items"] for name in sorted(cloud.jobs)]
    assert [int(item["scene_id"]) for item in job] == [3, 3]
    assert all(item["prompt"].startswith(new_words) for item in job)
    assert not any("empty tunnel" in item["prompt"] for item in job)
    assert result["still"]["status"] == "APPROVED"
    assert result["still"]["prompt_rewritten"] is True
    after = packages(engine, storyboard_id)
    assert all(after[n] == before[n] for n in (1, 2, 4))
    assert after[3][1] == clean[3]["still_prompt"]
    (event,) = rewritten_events(engine)
    assert event.payload["still_prompt"] == new_words
    # The new still is recorded under the words it was bought on.
    approved = [
        t
        for t in takes(engine, storyboard_id, "still")
        if t.scene_number == 3 and t.status == "APPROVED"
    ]
    assert [t.prompt_hash for t in approved] == [
        take_hash(still_fields(clean[3]["still_prompt"], None), made.model)
    ]


# ------------------------------- 6. a letter saying the prompt was rewritten is proven by it


def test_a_letter_saying_the_prompt_was_rewritten_is_proven_by_the_redo(engine, tmp_path):
    """Review 2026-10-09: the rewrite's event did not start with «media.prompt», so the claim
    checker (`agents.reviews.check_work_claims`) labelled an agent's true report of the
    studio's own repair «NEEFĂCUT — afirmație fără dovadă»."""
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    since = utc_now()
    plan = redo_plan(engine, storyboard_id, "still", 3)
    approved_still_redo(engine, storyboard_id, tmp_path, SpyStills(balance=1_000), plan)

    with Session(engine) as session:
        (claim,) = check_work_claims(session, "Am rescris promptul scenei 3.", since=since)

    assert claim["kind"] == "prompt"
    assert claim["proven"] is True, claim["needs"]
    assert claim["event_type"] == SCENE_PROMPTS_REWRITTEN_EVENT


# ------------- 7. his approval card says the words were rewritten, not only the sheet's drawer


@pytest.mark.parametrize("stale", [3, None])
def test_the_owners_question_says_when_the_prompt_was_rewritten(engine, tmp_path, stale):
    """Review 2026-10-09: the card the Owner answers (the approval's evidence, which the
    governance window shows) looked exactly like an ordinary redo's; a repair nobody pressed
    (the day's QC, `_apply_repairs`) reaches him only through it."""
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=stale)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)

    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, images, plan["plan_hash"])

    assert asked.value.status == "NEEDS_APPROVAL"
    with Session(engine) as session:
        evidence = str(session.get(ApprovalRequest, asked.value.approval_id).evidence)
    assert evidence.startswith("imaginea scenei 3: 2 variante la 2K, 18 credite")
    if stale is None:
        assert "rescris" not in evidence
    else:
        assert "Promptul imaginii a fost rescris de studio" in evidence
        assert "scos „Then the empty tunnel from scene 1, which sits still.”" in evidence
    assert images.asked == []


# ------------------- 8. pictures paid for on the retired words are never approved by the press


def test_pictures_paid_for_on_the_retired_words_are_collected_never_approved(engine, tmp_path):
    """Review 2026-10-09: a press judged the scene's paid, unjudged candidates first against
    the STORED words (`_judge_paid_stills_first`), and one that passed ended the press with
    nothing rewritten: a picture bought on the words the plan he was shown retires (on
    babcf272, a triptych the vision check matched to a three-moment plan) became the scene's
    still. Under a plan that rewrites the words they are collected, free, and not judged."""
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    stale_identity = take_hash(
        still_fields(clean[3]["still_prompt"] + STALE_TAIL, None), "seedream5_pro"
    )
    with Session(engine) as session, session.begin():
        # The Owner turned the triptych down on the sheet: the scene has no still.
        for take in session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == 3,
                SceneTake.kind == "still",
            )
        ):
            take.status = "REJECTED"
    # A purchase on the stale words left its pair PAID and never judged (a process died).
    folder = tmp_path / "left_behind"
    folder.mkdir()
    left: list[str] = []
    for n, source in enumerate(NO_FACE, start=1):
        path = folder / f"scene_03_c{n}.jpg"
        path.write_bytes(source.read_bytes())
        left.append(
            record_take(
                engine,
                storyboard_id=storyboard_id,
                scene_number=3,
                kind="still",
                prompt_hash=stale_identity,
                model_id="seedream5_pro",
                resolution=STILL_RATIO,
                status="PAID",
                correlation_id="crash",
                credits_quoted=9.0,
                path=path,
                sha256=sha(path),
                failure_code=UNJUDGED_FAILURE_CODE,
                remote_task_id="img-task-stale",
            )
        )
    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert plan["prompt_rewrite"]
    images = SpyStills(balance=1_000)

    # The press is asked (not ended by a stale picture), then bought on the new words.
    result = approved_still_redo(engine, storyboard_id, tmp_path, images, plan)

    assert len(images.asked) == 1
    assert images.asked[0]["prompt"].startswith(" ".join(clean[3]["still_prompt"].split()))
    assert result["still"]["status"] == "APPROVED"
    assert result["still"]["prompt_rewritten"] is True
    by_id = {t.id: t for t in takes(engine, storyboard_id, "still")}
    for take_id in left:
        assert by_id[take_id].status == "PAID", "a picture of the retired words was approved"
    approved = [t for t in by_id.values() if t.scene_number == 3 and t.status == "APPROVED"]
    assert [t.prompt_hash for t in approved] == [
        take_hash(still_fields(clean[3]["still_prompt"], None), "seedream5_pro")
    ]
    assert len(rewritten_events(engine)) == 1


# ------------------------------------------ 9. a serial episode keeps the series' own words


def test_a_serial_episode_keeps_its_own_words_on_a_still_redo(engine, tmp_path):
    """An episode of the office serial is composed from the series' look
    (`compose_serial_prompt`); compiling it again as a documentary would buy its new still
    in the wrong look. Only the serial check keeps its words: its package has a plan
    (subject, action, environment) the compiler could read."""
    storyboard_id, clean = compiled_film(engine, tmp_path)
    serial_words = "Warm office sitcom look of the series, soft key light. " + " ".join(
        clean[3]["still_prompt"].split()
    )
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).series_key = "office_serial"
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        )
        row.prompt_json = {**row.prompt_json, "still_prompt": serial_words}
        row.visual_prompt = serial_words
        still = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == 3,
                SceneTake.kind == "still",
            )
        ).one()
        still.prompt_hash = take_hash(still_fields(serial_words, None), "seedream5_pro")
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    before = packages(engine, storyboard_id)

    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert "prompt_rewrite" not in plan
    assert plan["still_prompt"] == serial_words
    assert "rescris" not in plan["reason_ro"]

    images = SpyStills(balance=1_000)
    result = approved_still_redo(engine, storyboard_id, tmp_path, images, plan)

    assert len(images.asked) == 1
    assert images.asked[0]["prompt"].startswith(serial_words)
    assert result["still"]["prompt_rewritten"] is False
    assert packages(engine, storyboard_id) == before, "a serial episode's package was rewritten"
    assert rewritten_events(engine) == []


# ----------------------------- 10. a plan the compiler cannot read: refused, nothing bought


def test_a_package_the_compiler_cannot_read_is_refused_not_bought_on_old_words(
    engine, tmp_path, monkeypatch
):
    from app.media import prompt_agent

    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    before = packages(engine, storyboard_id)

    def unreadable(*_args, **_kwargs):
        raise ValueError("the plan has no subject the compiler can read")

    monkeypatch.setattr(prompt_agent, "compile_prompts", unreadable)

    with pytest.raises(SceneRedoRefused) as shown:
        redo_plan(engine, storyboard_id, "still", 3)
    assert shown.value.status == "PROMPT_NOT_COMPILED"
    assert "nu se cumpără o imagine pe cuvintele vechi" in shown.value.reason_ro

    images = SpyStills(balance=1_000)
    with pytest.raises(SceneRedoRefused) as pressed:
        still_redo(engine, storyboard_id, tmp_path, images, "a-hash-from-before")
    assert pressed.value.status == "PROMPT_NOT_COMPILED"
    assert images.asked == []
    assert approvals(engine) == [], "the Owner was asked about a still that cannot be written"
    assert packages(engine, storyboard_id) == before
    assert rewritten_events(engine) == []
