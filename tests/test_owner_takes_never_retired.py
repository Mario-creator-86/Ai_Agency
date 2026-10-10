"""A take the Owner approved himself is never retired unasked; a redo that delivered nothing
gives back what it retired (2026-10-10).

Film babcf272, «The Particle That Shouldn't Exist (But Does)»: the studio assembled the film
from takes the Owner had approved (scenes 1-4; scene 2 his approved test shot). The film-level
QC failed it, partly by reading the studio's own subtitles as text, and the day's QC repair
(`runbook.stages._apply_repairs`) redid scenes 1 and 2 by itself, under his OVER_USD 5 rule:
`_retire_takes` retired his still and clip of scene 1 and his still and test shot of scene 2,
the rewrite put new words on both scenes, RunPod GPU sessions opened, he forced the GPU off,
every new candidate ended REFUSED, and nothing was delivered. So:

- a redo nobody pressed that would retire a take he approved himself buys nothing, asks
  nothing, writes nothing (OWNER_APPROVED); the transaction that would retire it refuses too;
- his own press of «Refă imaginea» still redoes his approved scene;
- a redo that retired takes and then delivered nothing usable (the GPU forced off, every
  candidate refused) gives them back with the scene's words, and they are usable again in
  the motion plan and in the assembly;
- the watchdog gives back, once, what a redo that ended before this code left (an older
  event that kept only the old still and motion prompts: his clip, which those words no
  longer reproduce, is bound to the picture he approved), never a take he turned down, never
  beside a newer take, never while the film is being bought for.

The review of the same day (section 5): candidates a gate turned down were still delivered
(they wait for his look), so a redo that brought them gives nothing back, now or later; his
yes to the studio's question for a plan is his decision as his press is; and the money guards
of an unasked redo still run on a scene only the studio chose. His card of the same day: a clip
too short for its words is redone only as his question, raised about his own approved clip too
(also where his rule and mode would buy unasked); nothing is retired or bought before his yes.

Every provider is faked (spy adapters, a RunPod cloud stand-in); no socket is opened (conftest
refuses them) and nothing is spent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.media import gpu_batch
from app.media.assembler import (
    OWNER_APPROVED,
    REDO_ACTION,
    REDO_FAILURE_CODE,
    REDO_STILL_REPLACED,
    SCENE_PROMPTS_RESTORED_EVENT,
    SCENE_PROMPTS_REWRITTEN_EVENT,
    TAKE_RESTORED_EVENT,
    TAKE_RETIRED_EVENT,
    SceneRedoRefused,
    _retire_takes,
    _storyboard_scenes,
    assembly_readiness,
    decide_take,
    motion_plan,
    owner_approved_among,
    record_take,
    redo_plan,
    redo_scene,
    still_fields,
    take_hash,
)
from app.media.models import FilmPurchaseLease, SceneTake, StoryboardScene
from app.media.stills_stage import GATE_REVIEWER, STILL_RATIO
from app.media.toolchain import find_ffmpeg
from app.providers.media_http import MediaProviderError
from app.providers.runpod.gpu_session import FORCED_OFF_WORDS, GpuSessionRefused
from app.services import append_event, may_act, utc_now
from app.workflows.passes import WatchdogContext, registered_passes
from app.workflows.passes import restore_retired_takes as restore_pass
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film
from test_mode_lowered_mid_step import lower_mode, mode_studio, stopped_events, studio_chosen
from test_scene_redo import approvals, coloured_clip, filmed, redo_motion, takes
from test_scene_redo_prompt_rewrite import (
    STALE_MOTION,
    STALE_TAIL,
    compiled_film,
    packages,
    rewritten_events,
    statuses,
)
from test_stills_stage import FACE, NO_FACE, SpyJudge, SpyStills, faces_in, sha

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def events(engine, kind: str) -> list[Any]:
    from app.models import DomainEvent

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == kind)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


def take(engine, take_id: str) -> SceneTake:
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        assert row is not None
        session.expunge(row)
        return row


def scene_three_still(engine, storyboard_id: str) -> SceneTake:
    (still,) = [
        t
        for t in takes(engine, storyboard_id, "still")
        if t.scene_number == 3 and t.status == "APPROVED"
    ]
    return still


def still_press(
    engine, storyboard_id, tmp_path, images, plan_hash, *, unasked: bool, scene: int = 3, **extra
):
    """«Refă imaginea» of a scene (3): his press (unasked False) or the studio's own (True)."""
    return redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="still",
        scene_index=scene,
        plan_hash=plan_hash,
        image_adapter=images,
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
        unasked=unasked,
        **extra,
    )


def usable_in_assembly(engine, storyboard_id: str, scene: int) -> dict[str, Any]:
    """Scene ``scene``'s reading for the film assembled from its takes (PRODUCTION)."""
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    stills = {
        t.scene_number: t.sha256
        for t in takes(engine, storyboard_id, "still")
        if t.status == "APPROVED"
    }
    with Session(engine) as session:
        readings = assembly_readiness(
            session, storyboard_id, scenes, stills, environment="PRODUCTION", local_moves=set()
        )
    return next(item for item in readings if item["scene_index"] == scene)


def watchdog(engine) -> dict[str, Any]:
    return dict(restore_pass.give_back_what_redos_left(WatchdogContext(engine, None, "wd")))


# ------------------------------------------- 1. unasked, his approved scene is not touched


def test_an_unasked_still_redo_of_his_approved_scene_buys_nothing_and_retires_nothing(
    engine, tmp_path
):
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    before = packages(engine, storyboard_id)
    taken = {(t.id, t.status, t.failure_code) for t in takes(engine, storyboard_id)}
    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert plan["prompt_rewrite"], "the scene's words would be rewritten by this redo"
    images = SpyStills(balance=1_000)

    with pytest.raises(SceneRedoRefused) as refused:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=True)

    assert refused.value.status == OWNER_APPROVED and refused.value.http_status == 409
    reason = refused.value.reason_ro
    assert reason.startswith("Scena 3: Proprietarul a aprobat el însuși imaginea și clipul")
    assert "alegerea lui rămâne" in reason and "«Refă imaginea»" in reason
    # Nothing bought, nothing asked, nothing written.
    assert images.asked == []
    assert approvals(engine) == []
    assert {(t.id, t.status, t.failure_code) for t in takes(engine, storyboard_id)} == taken
    assert packages(engine, storyboard_id) == before
    assert rewritten_events(engine) == [] and events(engine, TAKE_RETIRED_EVENT) == []
    assert statuses(engine, storyboard_id)[3] == ("BOUGHT", shots[3])


def test_an_unasked_motion_redo_of_his_approved_clip_posts_nothing(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert plan["buyable"] and plan["replaces"] == [shots[3]]
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="motion",
            scene_index=3,
            plan_hash=plan["plan_hash"],
            capabilities=[SEEDANCE],
            adapter_for_model=models,
            account=account,
            storage_root=tmp_path / "media",
            note="Controlul calității a picat scena; refacere cerută de Video Editor.",
            unasked=True,
        )

    assert refused.value.status == OWNER_APPROVED
    assert "clipul" in refused.value.reason_ro and "«Refă mișcarea»" in refused.value.reason_ro
    assert models.posts() == 0 and account.reads == 0, "the balance was read for a refusal"
    assert approvals(engine) == []
    assert take(engine, shots[3]).status == "APPROVED"
    assert events(engine, TAKE_RETIRED_EVENT) == []


def test_the_retiring_transaction_itself_refuses_his_take_and_rolls_back(engine, tmp_path):
    """Any path that reaches `_retire_takes` unasked (the redo's own early check aside)."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))

    with pytest.raises(SceneRedoRefused) as refused:
        with Session(engine) as session, session.begin():
            _retire_takes(
                session, [shots[2]], REDO_FAILURE_CODE, "unasked", "c-1", redo_kind="motion"
            )
    assert refused.value.status == OWNER_APPROVED
    assert take(engine, shots[2]).status == "APPROVED"
    assert events(engine, TAKE_RETIRED_EVENT) == []

    # His own press retires it, and the event keeps what it was, to be given back exactly.
    with Session(engine) as session, session.begin():
        assert _retire_takes(
            session,
            [shots[2]],
            REDO_FAILURE_CODE,
            "his press",
            "c-2",
            redo_kind="motion",
            owner_press=True,
        ) == [shots[2]]
    (retired,) = events(engine, TAKE_RETIRED_EVENT)
    assert retired.payload["previous_status"] == "APPROVED"
    assert retired.payload["previous_approved_by"] == "owner"
    assert retired.payload["previous_failure_code"] is None
    assert retired.payload["owner_press"] is True


def test_only_his_own_approval_protects_a_take(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    stills = {t.scene_number: t.id for t in takes(engine, storyboard_id, "still")}
    with Session(engine) as session, session.begin():
        # Scene 4: approved by the stills gate and by nobody's hand (seeded as the gate does).
        session.get(SceneTake, stills[4]).approved_by = GATE_REVIEWER
        session.get(SceneTake, shots[4]).approved_by = "clip_qc"
    # Scene 2's clip: the Owner turned it down on the sheet.
    decide_take(engine, shots[2], "REJECTED", decided_by="owner", note="Nu.")
    # Scene 1's still: approved again by his own look (his decision's event).
    decide_take(engine, stills[1], "APPROVED", decided_by="owner")

    with Session(engine) as session:
        protected = owner_approved_among(
            session, [stills[1], stills[4], shots[2], shots[3], shots[4]]
        )
    assert protected == [stills[1], shots[3]]

    # The studio's own redo of scene 4 is not refused for his choice: only the gate chose.
    plan = redo_plan(engine, storyboard_id, "still", 4)
    with pytest.raises(SceneRedoRefused) as asked:
        still_press(
            engine,
            storyboard_id,
            tmp_path,
            SpyStills(balance=1_000),
            plan["plan_hash"],
            unasked=True,
            scene=4,
        )
    assert asked.value.status != OWNER_APPROVED


# --------------------------------------------------------- 2. his own press still works


def test_his_own_press_still_redoes_his_approved_scene(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    old = scene_three_still(engine, storyboard_id)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)

    with pytest.raises(SceneRedoRefused) as asked:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Refă imaginea scenei 3.")
    result = still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)

    assert len(images.asked) == 1 and result["still"]["status"] == "APPROVED"
    assert "given_back" not in result
    assert take(engine, old.id).failure_code == REDO_FAILURE_CODE
    assert take(engine, shots[3]).failure_code == REDO_STILL_REPLACED
    retired = events(engine, TAKE_RETIRED_EVENT)
    assert {e.aggregate_id for e in retired} == {old.id, shots[3]}
    assert all(e.payload["owner_press"] is True for e in retired)
    # A redo that delivered keeps its result: nothing is given back, now or by the watchdog.
    assert watchdog(engine)["restored"] == []
    assert events(engine, TAKE_RESTORED_EVENT) == []


# ------------------------------------- 3. a redo that delivered nothing gives them back


@pytest.fixture
def forced_off(monkeypatch):
    """RunPod's GPU, faked: his button switched it off, so no session opens (nothing sent)."""

    def gpu_session(*_args, **_kwargs):
        raise GpuSessionRefused("GPU_FORCED_OFF", FORCED_OFF_WORDS)

    monkeypatch.setattr(gpu_batch, "gpu_session", gpu_session)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)


def test_a_redo_the_gpu_was_forced_off_under_gives_back_his_takes_and_words(
    engine, tmp_path, forced_off
):
    from test_runpod_batch import PictureCloud, adapter, stills_table

    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    old = scene_three_still(engine, storyboard_id)
    before = packages(engine, storyboard_id)
    planned = statuses(engine, storyboard_id)
    assert planned[3] == ("BOUGHT", shots[3])
    cloud = PictureCloud(lambda prompt: NO_FACE[0].read_bytes())
    made = adapter(engine, tmp_path, cloud)
    table = stills_table()
    plan = redo_plan(engine, storyboard_id, "still", 3, table=table, stills_model=made.model)
    assert plan["prompt_rewrite"] and plan["replaces"] == [old.id]
    assert plan["invalidates"] == [shots[3]]

    def press():
        return still_press(
            engine, storyboard_id, tmp_path, made, plan["plan_hash"], unasked=False, table=table
        )

    with pytest.raises(SceneRedoRefused) as asked:
        press()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, refă imaginea.")
    with pytest.raises(SceneRedoRefused) as stopped:
        press()

    assert stopped.value.status == "GPU_FORCED_OFF"
    assert "înregistrările retrase au fost repuse cum erau" in stopped.value.reason_ro
    assert "cu promptul scenei de dinainte" in stopped.value.reason_ro
    assert not cloud.calls, "a round was sent with the GPU forced off"
    # It did retire and rewrite, then gave both back.
    assert len(events(engine, TAKE_RETIRED_EVENT)) == 2
    (rewrite,) = rewritten_events(engine)
    assert rewrite.payload["old_package"] and rewrite.payload["package"]
    for take_id in (old.id, shots[3]):
        row = take(engine, take_id)
        assert (row.status, row.failure_code, row.approved_by) == ("APPROVED", None, "owner")
    assert packages(engine, storyboard_id) == before, "the scene's words were not put back"
    restored = events(engine, TAKE_RESTORED_EVENT)
    assert {e.aggregate_id for e in restored} == {old.id, shots[3]}
    assert all(e.payload["cause"] == "redo_delivered_nothing" for e in restored)
    assert all(e.payload["prompt_matches"] and not e.payload["bound_to_picture"] for e in restored)
    (words,) = events(engine, SCENE_PROMPTS_RESTORED_EVENT)
    assert words.payload["exact"] is True and words.payload["kept_from_rewrite"] == []
    assert words.payload["rewritten_event_id"] == rewrite.event_id
    assert words.payload["still_prompt"].endswith(STALE_TAIL.strip())

    # Usable again: the motion plan stands on his clip, and the assembly cuts it in.
    assert statuses(engine, storyboard_id) == planned
    reading = usable_in_assembly(engine, storyboard_id, 3)
    assert reading["ok"] and reading["take_id"] == shots[3]
    # Given back once: the watchdog finds nothing more to do.
    assert watchdog(engine)["restored"] == []
    assert len(events(engine, TAKE_RESTORED_EVENT)) == 2


def test_a_motion_redo_whose_every_clip_failed_gives_back_his_clip(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    planned = statuses(engine, storyboard_id)
    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    account = Account(10_000)
    broken = ("INTERNAL.BAD_OUTPUT", "the model returned a broken clip")
    models = Models(SpyVideo("seedance2_5", account, fail={1: broken, 2: broken}))

    with pytest.raises(SceneRedoRefused) as asked:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED", note="Refă mișcarea scenei 3.")
    result = redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])

    assert models.posts() >= 1, "the redo never reached the vendor"
    assert result["film"] is None
    assert result["given_back"]["restored"] == [shots[3]]
    assert result["given_back"]["package"] is None  # a motion redo rewrites no words
    assert result["next_ro"].startswith("Refacerea scenei 3 nu a adus nimic folosibil")
    new_shots = [
        t
        for t in takes(engine, storyboard_id)
        if t.kind == "motion" and t.scene_number == 3 and t.id != shots[3]
    ]
    assert new_shots and all(t.status not in ("APPROVED", "PAID") for t in new_shots)
    row = take(engine, shots[3])
    assert (row.status, row.failure_code, row.approved_by) == ("APPROVED", None, "owner")
    assert statuses(engine, storyboard_id) == planned


class RefusingStills(SpyStills):
    """The image vendor, faked, refusing every request for safety (nothing delivered)."""

    async def generate_candidates(self, prompt, **_kwargs):
        self.asked.append({"prompt": prompt})
        raise MediaProviderError(
            "refused", code="SAFETY.INPUT.TEXT", http_status=400, detail="refused"
        )


def test_a_redo_whose_every_candidate_is_refused_gives_back_his_takes(engine, tmp_path):
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    old = scene_three_still(engine, storyboard_id)
    before = packages(engine, storyboard_id)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = RefusingStills(balance=1_000)

    with pytest.raises(SceneRedoRefused) as asked:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)
    answer(engine, asked.value.approval_id, "APPROVED")
    result = still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)

    assert images.asked, "the redo never reached the vendor"
    assert result["still"]["status"] != "APPROVED"
    assert sorted(result["given_back"]["restored"]) == sorted([old.id, shots[3]])
    assert result["next_ro"].startswith("Refacerea scenei 3 nu a adus nimic folosibil")
    refused = [
        t for t in takes(engine, storyboard_id, "still") if t.scene_number == 3 and t.id != old.id
    ]
    assert refused and all(t.status == "REFUSED" for t in refused)
    assert take(engine, old.id).status == "APPROVED"
    assert take(engine, shots[3]).status == "APPROVED"
    assert packages(engine, storyboard_id) == before
    assert statuses(engine, storyboard_id)[3] == ("BOUGHT", shots[3])
    (redone,) = events(engine, "media.scene_redone")
    assert sorted(redone.payload["given_back"]) == sorted([old.id, shots[3]])


# ------------------------------- 4. the watchdog gives back what an older redo left, once


def an_old_repair(engine, storyboard_id: str, clean: dict[int, dict], shot_id: str) -> str:
    """What the day's QC repair wrote on babcf272 before this code: scene 3's words rewritten
    (an event with the two old prompts only), his still and clip retired (events with their
    old status only), and the new candidate the vendor refused. Returns its correlation."""
    correlation = str(uuid4())
    still = scene_three_still(engine, storyboard_id)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        )
        assert row is not None
        stored = dict(row.prompt_json)
        row.prompt_json = dict(clean[3])
        row.visual_prompt = clean[3]["still_prompt"]
        append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "storyboard_id": storyboard_id,
                "scene_index": 3,
                "old_still_prompt": " ".join(stored["still_prompt"].split()),
                "still_prompt": " ".join(clean[3]["still_prompt"].split()),
                "old_motion_prompt": " ".join(stored["motion_prompt"].split()),
                "motion_prompt": " ".join(clean[3]["motion_prompt"].split()),
                "reason": "redo",
                "plan_hash": "plan-of-the-repair",
            },
            correlation,
        )
        for take_id, code in ((still.id, REDO_FAILURE_CODE), (shot_id, REDO_STILL_REPLACED)):
            retired = session.get(SceneTake, take_id)
            assert retired is not None
            retired.status, retired.failure_code = "REJECTED", code
            retired.failure_detail = "Controlul calității a picat scena."
            append_event(
                session,
                TAKE_RETIRED_EVENT,
                "scene_take",
                take_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "scene_number": 3,
                    "kind": retired.kind,
                    "previous_status": "APPROVED",
                    "failure_code": code,
                },
                correlation,
            )
    record_take(
        engine,
        storyboard_id=storyboard_id,
        scene_number=3,
        kind="still",
        prompt_hash=take_hash(still_fields(clean[3]["still_prompt"], None), "Qwen-Image-2512"),
        model_id="Qwen-Image-2512",
        resolution=STILL_RATIO,
        status="REFUSED",
        correlation_id=correlation,
        failure_code="GPU_FORCED_OFF",
    )
    return correlation


def test_the_watchdog_gives_back_once_what_an_older_repair_left(engine, tmp_path):
    assert "restore_retired_takes" in {entry.name for entry in registered_passes()}
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    still = scene_three_still(engine, storyboard_id)
    before = packages(engine, storyboard_id)
    planned = statuses(engine, storyboard_id)
    shot_hash = take(engine, shots[3]).prompt_hash
    an_old_repair(engine, storyboard_id, clean, shots[3])
    assert statuses(engine, storyboard_id)[3][0] != "BOUGHT"

    # While the film is being bought for, a redo may be giving back itself: left alone.
    with Session(engine) as session, session.begin():
        session.add(
            FilmPurchaseLease(
                storyboard_id=storyboard_id,
                holder="someone",
                step="scene_redo",
                acquired_at=utc_now(),
                expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            )
        )
    assert watchdog(engine)["restored"] == []
    with Session(engine) as session, session.begin():
        session.delete(session.get(FilmPurchaseLease, storyboard_id))

    done = watchdog(engine)

    assert done["restored"] == [still.id, shots[3]]
    # His clip was filmed on a motion intent the older event did not keep: the words put back
    # do not reproduce its hash, so his approval binds the picture he chose.
    assert done["bound_to_picture"] == [shots[3]]
    (put_back,) = done["packages"]
    assert (put_back["storyboard_id"], put_back["scene_index"]) == (storyboard_id, 3)
    assert "motion_intent" in put_back["kept_from_rewrite"]
    after = packages(engine, storyboard_id)
    for n in (1, 2, 4):
        assert after[n] == before[n]
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 3
            )
        )
        assert row is not None
        package, visual = dict(row.prompt_json), row.visual_prompt
    stale_words = " ".join((clean[3]["still_prompt"] + STALE_TAIL).split())
    assert package["still_prompt"] == stale_words and visual == stale_words
    assert package["motion_prompt"] == STALE_MOTION
    restored_still, restored_shot = take(engine, still.id), take(engine, shots[3])
    assert (restored_still.status, restored_still.failure_code) == ("APPROVED", None)
    assert restored_still.prompt_hash == still.prompt_hash
    assert (restored_shot.status, restored_shot.failure_code) == ("APPROVED", None)
    assert restored_shot.prompt_hash != shot_hash
    by_take = {e.aggregate_id: e.payload for e in events(engine, TAKE_RESTORED_EVENT)}
    assert by_take[still.id]["prompt_matches"] is True
    assert by_take[still.id]["bound_to_picture"] is False
    assert by_take[shots[3]]["bound_to_picture"] is True
    assert by_take[shots[3]]["previous_prompt_hash"] == shot_hash
    assert all(payload["cause"] == "watchdog" for payload in by_take.values())
    (words,) = events(engine, SCENE_PROMPTS_RESTORED_EVENT)
    assert words.payload["exact"] is False
    # What the older event could not give back stays the rewrite's, and the event says which
    # (review 2026-10-10): the package put back is not the old one.
    kept = words.payload["kept_from_rewrite"]
    assert {"motion_intent", "negative_prompt", "camera_move", "look_block"} <= set(kept)
    assert "still_prompt" not in kept and "motion_prompt" not in kept
    assert "subject" not in kept, "the scene's plan was never the rewrite's to change"
    # Usable again, in the motion plan and in the assembly.
    assert statuses(engine, storyboard_id) == planned
    reading = usable_in_assembly(engine, storyboard_id, 3)
    assert reading["ok"] and reading["take_id"] == shots[3]

    # Once: the next pass, minutes later, writes nothing.
    assert watchdog(engine) == {"restored": [], "bound_to_picture": []}
    assert len(events(engine, TAKE_RESTORED_EVENT)) == 2
    assert len(events(engine, SCENE_PROMPTS_RESTORED_EVENT)) == 1


@pytest.mark.parametrize("why", ["he_rejected_it", "newer_still"])
def test_the_watchdog_never_gives_back_what_he_turned_down_or_a_newer_take_replaced(
    engine, tmp_path, why
):
    storyboard_id, clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    still = scene_three_still(engine, storyboard_id)
    an_old_repair(engine, storyboard_id, clean, shots[3])
    rewritten = packages(engine, storyboard_id)
    if why == "he_rejected_it":
        # He looked at the retired picture on the sheet and turned it down himself.
        decide_take(engine, still.id, "REJECTED", decided_by="owner", note="Nu o mai vreau.")
    else:
        # A newer picture of the scene, bought on the new words and approved since.
        path = tmp_path / "newer_scene_03.jpg"
        path.write_bytes(NO_FACE[1].read_bytes() + b"newer")
        record_take(
            engine,
            storyboard_id=storyboard_id,
            scene_number=3,
            kind="still",
            prompt_hash=take_hash(still_fields(clean[3]["still_prompt"], None), "seedream5_pro"),
            model_id="seedream5_pro",
            resolution=STILL_RATIO,
            status="APPROVED",
            correlation_id=str(uuid4()),
            path=path,
            sha256=sha(path),
        )

    assert watchdog(engine)["restored"] == []
    assert take(engine, still.id).status == "REJECTED"
    assert take(engine, shots[3]).status == "REJECTED"
    assert packages(engine, storyboard_id) == rewritten
    assert events(engine, TAKE_RESTORED_EVENT) == []
    assert events(engine, SCENE_PROMPTS_RESTORED_EVENT) == []


# ------------------------------------------------------------- 5. the review of 2026-10-10


def faces_only(_prompt, _call):
    """The image vendor's pictures, faked: a face in both, so the stills gate turns down every
    candidate (the bible forbids faces) and asks for a re-roll."""
    return [FACE, FACE]


def scene_three_line(engine, storyboard_id: str) -> dict[str, Any]:
    plan = motion_plan(engine, storyboard_id, capabilities=[SEEDANCE])
    return next(item for item in plan["scenes"] if item["scene_index"] == 3)


def test_candidates_the_gate_turned_down_were_delivered_and_wait_for_his_look(engine, tmp_path):
    """His «Refă imaginea» whose every candidate the stills gate turned down (NEEDS_OWNER,
    «Decide Proprietarul»): the candidates are on disk for his look, so nothing is given back
    and the scene keeps the words they were bought on; the one he picks is the scene's still.
    Before the review the old still and clip came back with the old words, and his pick
    matched nothing: the plan stayed on the old clip."""
    storyboard_id, _clean = compiled_film(engine, tmp_path, stale=3)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    old = scene_three_still(engine, storyboard_id)
    before = packages(engine, storyboard_id)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(pictures=faces_only, balance=1_000)

    with pytest.raises(SceneRedoRefused) as asked:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)
    answer(engine, asked.value.approval_id, "APPROVED", note="Refă imaginea scenei 3.")
    result = still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)

    assert result["still"]["status"] in ("NEEDS_OWNER", "COMPOSE_LOCALLY")
    assert "given_back" not in result
    assert not result["next_ro"].startswith("Refacerea scenei 3 nu a adus nimic folosibil")
    delivered = [
        t
        for t in takes(engine, storyboard_id, "still")
        if t.scene_number == 3 and t.id != old.id and t.sha256
    ]
    assert delivered and all(t.status == "REJECTED" for t in delivered)
    retired = take(engine, old.id)
    assert (retired.status, retired.failure_code) == ("REJECTED", REDO_FAILURE_CODE)
    assert take(engine, shots[3]).status == "REJECTED"
    assert packages(engine, storyboard_id) != before, "the words the candidates were bought on"
    assert events(engine, TAKE_RESTORED_EVENT) == []
    assert events(engine, SCENE_PROMPTS_RESTORED_EVENT) == []
    # Nor later: the watchdog reads that the redo delivered.
    assert watchdog(engine)["restored"] == []

    # His look on the sheet: he picks one, and it is the scene's still.
    decide_take(engine, delivered[0].id, "APPROVED", decided_by="owner")
    assert scene_three_line(engine, storyboard_id)["still_take_id"] == delivered[0].id


def test_the_watchdog_never_brings_back_what_his_delivered_redo_replaced(engine, tmp_path):
    """His «Refă imaginea» delivered a new still; later he turns the new pictures down too.
    The still he pressed away and its clip stay retired: his redo did deliver, whatever became
    of what it delivered (read from the takes' history, not from their status now)."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    old = scene_three_still(engine, storyboard_id)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    images = SpyStills(balance=1_000)
    with pytest.raises(SceneRedoRefused) as asked:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)
    answer(engine, asked.value.approval_id, "APPROVED")
    result = still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=False)
    assert result["still"]["status"] == "APPROVED"
    assert watchdog(engine)["restored"] == []

    for candidate in takes(engine, storyboard_id, "still"):
        if candidate.scene_number == 3 and candidate.id != old.id and candidate.sha256:
            decide_take(engine, candidate.id, "REJECTED", decided_by="owner", note="Nici asta.")

    assert watchdog(engine)["restored"] == []
    assert take(engine, old.id).status == "REJECTED"
    assert take(engine, shots[3]).status == "REJECTED"
    assert events(engine, TAKE_RESTORED_EVENT) == []


def test_his_yes_to_the_studios_question_for_this_plan_is_his_decision(engine, tmp_path):
    """A question the studio raised for this redo's plan before 2026-10-10 (a clip too short
    for its words, the day's QC), which he answered yes: the studio's own re-run of it spends
    his yes and redoes his scene, as his press would. Without his yes it is refused (above)."""
    from test_clip_qc_wiring import passing

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    with Session(engine) as session, session.begin():
        raised = may_act(
            session,
            REDO_ACTION,
            requester="video_editor",
            subject=storyboard_id,
            evidence="Scena 3: clipul este prea scurt; studioul propune refacerea mișcării.",
            cost_usd=plan["cap_usd"],
            context={"plan_hash": plan["plan_hash"], "cap_credits": int(plan["cap_credits"])},
        )
    assert raised["status"] == "NEEDS_APPROVAL"
    answer(engine, raised["approval_id"], "APPROVED", note="Da, refă mișcarea scenei 3.")
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))

    result = redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="motion",
        scene_index=3,
        plan_hash=plan["plan_hash"],
        capabilities=[SEEDANCE],
        adapter_for_model=models,
        account=account,
        storage_root=tmp_path / "media",
        clip_check=passing(),
        note="Controlul calității a picat scena; refacere cerută de Video Editor.",
        unasked=True,
    )

    assert models.posts() == 1
    assert "given_back" not in result
    row = take(engine, shots[3])
    assert (row.status, row.failure_code) == ("REJECTED", REDO_FAILURE_CODE)
    (retired,) = events(engine, TAKE_RETIRED_EVENT)
    assert retired.payload["owner_press"] is True
    assert retired.payload["plan_hash"] == plan["plan_hash"]


@pytest.mark.parametrize("policy", ["his_rule_asks", "his_mode_would_buy"])
def test_his_too_short_clip_gets_his_question_and_is_retired_only_after_his_yes(
    engine, settings, tmp_path, monkeypatch, policy
):
    """His card of 2026-10-10: a clip too short for its words beyond the 25% a clip may be
    slowed is redone only as his question. Scene 3 of a babcf272-like film is his own approved
    clip and needs 29%: the studio raises his question (also where his rule and mode would let
    the redo buy unasked), nothing is retired or bought while it waits, and once he said yes
    the redo raised again spends his yes, buys the clip at its length and retires his."""
    from app.economy.budget import BudgetCommand, set_budget
    from app.media import qc
    from app.media.assembler import CLIP_SHORT, propose_clip_redos
    from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_assemble_step
    from app.models import ApprovalRequest
    from test_clip_fits_narration import babcf272_like, in_environment, wiring
    from test_clip_qc_wiring import passing

    storyboard_id = babcf272_like(engine, tmp_path)
    in_environment(engine, "PRODUCTION")
    if policy == "his_mode_would_buy":
        # AUTONOMOUS_CEO, his rule MODE and a daily budget: the kernel alone would buy it.
        mode_studio(engine)
        set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    (his,) = [t for t in takes(engine, storyboard_id, "motion") if t.scene_number == 3]
    with Session(engine) as session:
        assert owner_approved_among(session, [his.id]) == [his.id]
    account = Account(5000)
    video = SpyVideo("seedance2_5", account)
    models = Models(video)
    # The new clip's QC, faked: only a clip bought after his yes ever reaches it.
    monkeypatch.setattr(qc, "check_clip", passing())

    def propose(correlation_id: str) -> list[dict[str, Any]]:
        return propose_clip_redos(
            engine,
            storyboard_id,
            correlation_id,
            wiring=wiring(tmp_path, models, account),
            settings=settings,
            environment="PRODUCTION",
        )

    def redo_questions() -> list[ApprovalRequest]:
        return [row for row in approvals(engine) if row.action == REDO_ACTION]

    sheet = build_sheet(engine, storyboard_id, capabilities=[SEEDANCE], read_live=False)
    with pytest.raises(SheetStepRefused) as refused:
        run_assemble_step(
            engine,
            storyboard_id,
            sheet["sheet_hash"],
            correlation_id="press-1",
            capabilities=[SEEDANCE],
            settings=settings,
            environment="PRODUCTION",
            storage_root=tmp_path / "media",
            redo_wiring=wiring(tmp_path, models, account),
        )

    (scene,) = refused.value.scenes
    assert scene["code"] == CLIP_SHORT
    assert scene["redo"]["status"] == "NEEDS_APPROVAL", scene["redo"]
    if policy == "his_mode_would_buy":
        # Not his rule asking: his own clip made it his question.
        assert "Proprietarul a aprobat el însuși clipul" in scene["redo"]["reason_ro"]
    (question,) = redo_questions()
    assert question.id == scene["redo"]["approval_id"]
    assert "ar trebui încetinit cu 29%" in str(question.evidence)
    assert "Studioul propune refacerea mișcării la 7 s." in str(question.evidence)
    # Asking touched nothing of his: nothing bought, nothing retired.
    assert models.posts() == 0 and account.shots == 0
    assert take(engine, his.id).status == "APPROVED"
    assert events(engine, TAKE_RETIRED_EVENT) == []

    # Raised again while he has not answered: the same question, and still nothing.
    (waiting,) = propose("continue-2")
    assert waiting["status"] == "NEEDS_APPROVAL" and waiting["approval_id"] == question.id
    assert len(redo_questions()) == 1
    assert models.posts() == 0 and take(engine, his.id).status == "APPROVED"
    assert events(engine, TAKE_RETIRED_EVENT) == []

    # His yes: the redo raised again spends it, buys the longer clip and retires his.
    answer(engine, question.id, "APPROVED", note="Da, refă mișcarea scenei 3.")
    (bought,) = propose("continue-3")

    assert bought["status"] == "BOUGHT", bought
    assert models.posts() == 1 and account.shots == 1
    assert video.asked[0]["seconds"] == 7, "not the length its words need"
    row = take(engine, his.id)
    assert (row.status, row.failure_code) == ("REJECTED", REDO_FAILURE_CODE)
    (retired,) = events(engine, TAKE_RETIRED_EVENT)
    assert retired.aggregate_id == his.id and retired.payload["owner_press"] is True
    with Session(engine) as session:
        spent = session.get(ApprovalRequest, question.id)
        assert spent is not None and spent.consumed_at is not None, "his yes was not spent"
    assert len(redo_questions()) == 1


def test_unasked_under_manual_a_scene_only_the_studio_chose_is_refused_by_the_mode(
    engine, tmp_path
):
    """The money guard of an unasked redo (spec 51), reached on a scene whose still and clip
    only the gate and the clip QC chose: refused BLOCKED_MODE before anything is bought."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    filmed(engine, storyboard_id, tmp_path, b"clip")
    studio_chosen(engine, storyboard_id)
    mode_studio(engine)
    lower_mode(engine)
    images = SpyStills(balance=1_000)
    plan = redo_plan(engine, storyboard_id, "still", 3)

    with pytest.raises(SceneRedoRefused) as refused:
        still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=True)

    assert refused.value.status == "BLOCKED_MODE"
    assert images.asked == []
    assert events(engine, TAKE_RETIRED_EVENT) == []


def test_a_mode_lowered_during_the_studios_redo_buys_no_reroll_and_gives_nothing_back(
    engine, tmp_path
):
    """The Director's unasked repair of a still only the gate had chosen (as babcf272's
    three-panel scene 5): the mode lowered while the pair was at the vendor stops the re-roll
    (spec 51); the pair the gate turned down was delivered, so the still the repair retired
    does not come back to be assembled again."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, b"clip")
    studio_chosen(engine, storyboard_id)
    old = scene_three_still(engine, storyboard_id)
    mode_studio(engine)
    images = SpyStills(balance=1_000)

    def faces_then_lower(_prompt, call):
        if call == 1:
            lower_mode(engine)
        return [FACE, FACE]

    images.pictures = faces_then_lower
    plan = redo_plan(engine, storyboard_id, "still", 3)

    result = still_press(engine, storyboard_id, tmp_path, images, plan["plan_hash"], unasked=True)

    assert len(images.asked) == 1, "a re-roll was bought after the mode was lowered"
    assert "restul nu s-a cumpărat" in result["still"]["reason"]
    (event,) = stopped_events(engine)
    assert event["step"] == "scene_redo"
    assert "given_back" not in result
    assert take(engine, old.id).status == "REJECTED"
    assert take(engine, shots[3]).status == "REJECTED"
    assert all(e.payload["owner_press"] is False for e in events(engine, TAKE_RETIRED_EVENT))
    assert watchdog(engine)["restored"] == []
