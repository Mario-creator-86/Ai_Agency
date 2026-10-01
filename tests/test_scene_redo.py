"""A failed scene is redone alone: its still, its motion, its card or the film's sound.

The Nepal film (2026-09-26) failed quality control on two composed scenes and 0.07 dB of
sound, and the studio's only answer was to buy the whole film again: every still, every clip,
the same prompts. A redo here touches one scene and nothing else:

- a card redo recomposes that card locally and rejoins the film from the shots already built:
  0 credits, no adapter asked, and every other shot file left byte-for-byte as it was;
- an audio redo remasters the sound under the same picture (``-c:v copy``): 0 credits, the
  video packets identical;
- a motion redo buys ONE shot, only under the Owner's yes for ``media.scene_redo`` bound to
  the redo's own plan_hash, spent once; a yes for one scene buys no other;
- a still redo buys one pair of candidates for that scene, and the shot filmed from the old
  still can never be used again; no other scene's take, and no other scene's pending redo, is
  touched.

Every provider is faked: spy adapters count their calls. No socket is opened (conftest refuses
them).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from app.media.assembler import (
    REDO_ACTION,
    REDO_STEP,
    SceneRedoRefused,
    _storyboard_scenes,
    assemble_from_takes,
    assemble_video_job,
    motion_fields,
    redo_plan,
    redo_scene,
    take_hash,
    video_stream_sha256,
)
from app.media.models import MediaAsset, SceneTake, StoryboardScene, VideoRenderJob
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import SEEDANCE, Account, Models, SpyVideo, a_film
from test_motion import a_clip
from test_scene_takes import SpyImages, SpyMotion, nepal_like
from test_stills_stage import SpyJudge, SpyStills, faces_in

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stream_hash(path: Path, stream: str) -> str:
    """The sha256 over every packet of one stream ('v:0' or 'a:0'), as ffmpeg reads them."""
    result = subprocess.run(
        [
            find_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            f"0:{stream}",
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().split("=", 1)[1]


def coloured_clip(tmp_path: Path, colour: str) -> bytes:
    """Two seconds of real h264 in one colour: a vendor's clip, faked, with its own bytes."""
    target = tmp_path / f"clip_{colour}.mp4"
    subprocess.run(
        [
            find_ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:s=540x960:d=2",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target.read_bytes()


def takes(engine, storyboard_id: str, kind: str | None = None) -> list[SceneTake]:
    with Session(engine) as session:
        query = select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        if kind is not None:
            query = query.where(SceneTake.kind == kind)
        rows = session.scalars(query.order_by(SceneTake.scene_number, SceneTake.created_at)).all()
        session.expunge_all()
        return list(rows)


def approvals(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest)))
        session.expunge_all()
        return rows


def a_rendered_nepal_film(engine, tmp_path: Path):
    """The Nepal film's shape rendered once with fakes: 4 LIVE scenes, a chart, a black."""
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
    return storyboard_id, render, images, motion


def filmed(engine, storyboard_id: str, tmp_path: Path, clip: bytes) -> dict[int, str]:
    """An APPROVED shot (the Owner looked at it) for every LIVE scene, from its approved still."""
    _title, scenes = _storyboard_scenes(engine, storyboard_id)
    stills = {take.scene_number: take for take in takes(engine, storyboard_id, "still")}
    folder = tmp_path / "approved_shots"
    folder.mkdir(exist_ok=True)
    made: dict[int, str] = {}
    for scene in scenes:
        n = int(scene["scene_index"])
        if n not in stills:
            continue
        path = folder / f"{storyboard_id[:8]}_shot_{n:02d}.mp4"
        path.write_bytes(clip + bytes([n]))  # each shot its own sha256; mp4 ignores the tail
        fields = motion_fields(scene, stills[n].sha256, from_prompt=False)
        take_id = str(uuid4())
        with Session(engine) as session, session.begin():
            session.add(
                SceneTake(
                    id=take_id,
                    storyboard_id=storyboard_id,
                    scene_number=n,
                    kind="test_shot" if n == 1 else "motion",
                    prompt_hash=take_hash(fields, "seedance2_5"),
                    model_id="seedance2_5",
                    resolution="1080:1920",
                    seconds=5.0,
                    status="APPROVED",
                    approved_by="owner",
                    path=str(path),
                    sha256=sha(path),
                    created_at="2026-10-01T10:00:00+00:00",
                    updated_at="2026-10-01T10:00:00+00:00",
                )
            )
        made[n] = take_id
    return made


def shot_takes(engine, storyboard_id: str) -> list[SceneTake]:
    return [t for t in takes(engine, storyboard_id) if t.kind in ("motion", "test_shot")]


def redo_motion(engine, storyboard_id, tmp_path, models, account, scene, plan_hash):
    return redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="motion",
        scene_index=scene,
        plan_hash=plan_hash,
        capabilities=[SEEDANCE],
        adapter_for_model=models,
        account=account,
        storage_root=tmp_path / "media",
    )


# -------------------------------------- 1. a card redo: 0 credits, the other shots untouched


def test_a_card_redo_after_a_render_asks_no_adapter_and_leaves_shots_1_to_4_identical(
    engine, tmp_path
):
    storyboard_id, render, images, motion = a_rendered_nepal_film(engine, tmp_path)
    folder = Path(render["file_path"]).parent
    shots_before = {n: sha(folder / f"shot_{n:02d}.mp4") for n in range(1, 7)}
    film_before = sha(Path(render["file_path"]))
    asked_before = (len(images.asked), len(motion.asked))
    takes_before = len(takes(engine, storyboard_id))

    plan = redo_plan(engine, storyboard_id, "card", 5)
    assert plan["credits"] == 0 and plan["free"] is True
    assert plan["base_asset_id"] == render["output_asset_id"]

    result = redo_scene(engine, storyboard_id, str(uuid4()), kind="card", scene_index=5)

    assert (len(images.asked), len(motion.asked)) == asked_before, "a card redo asked a vendor"
    for n in (1, 2, 3, 4, 6):
        assert sha(folder / f"shot_{n:02d}.mp4") == shots_before[n], f"shot {n} was rebuilt"
    assert sha(Path(render["file_path"])) == film_before, "the film it came from was touched"
    assert result["credits"] == 0
    film = result["film"]
    assert film["reused_shots"] == [1, 2, 3, 4, 6]
    assert film["rebuilt_shots"] == [5]
    new_film = Path(film["file_path"])
    assert new_film.is_file() and new_film != Path(render["file_path"])
    # The sound is the film's own, copied in: a card redo does not touch it.
    assert stream_hash(new_film, "a:0") == stream_hash(Path(render["file_path"]), "a:0")
    assert len(takes(engine, storyboard_id)) == takes_before, "a card redo recorded a take"
    assert approvals(engine) == [], "a free redo asked the Owner to approve a purchase"

    with Session(engine) as session:
        asset = session.get(MediaAsset, film["output_asset_id"])
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset.id)
        )
        assert job.status == "COMPLETED"
        remaster = job.production_json["remaster"]
        scenes = {e["scene_index"]: e for e in job.production_json["scenes"]}
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.scene_redone")
        ).all()
    assert remaster["kind"] == "scene_redo" and remaster["redo"] == "card"
    assert remaster["scene_index"] == 5 and remaster["credits"] == 0
    assert remaster["of_asset"] == render["output_asset_id"]
    assert scenes[5]["card"]["provenance"] == "composed" and scenes[5]["card"]["credits"] == 0
    assert [e.payload["scene_index"] for e in events] == [5]


def test_a_card_redo_of_a_filmed_scene_is_refused_and_builds_nothing(engine, tmp_path):
    storyboard_id, render, images, motion = a_rendered_nepal_film(engine, tmp_path)
    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(engine, storyboard_id, str(uuid4()), kind="card", scene_index=3)
    assert refused.value.status == "KIND_MISMATCH" and refused.value.http_status == 409
    assert "Scena 3" in refused.value.reason_ro
    with Session(engine) as session:
        assert len(session.scalars(select(MediaAsset)).all()) == 1


# ------------------------------------------- 2. an audio remaster: only the sound changes


def test_an_audio_remaster_keeps_every_video_packet_and_costs_nothing(engine, tmp_path):
    storyboard_id, render, images, motion = a_rendered_nepal_film(engine, tmp_path)
    source = Path(render["file_path"])
    film_before = sha(source)
    asked_before = (len(images.asked), len(motion.asked))
    ffmpeg = find_ffmpeg()

    plan = redo_plan(engine, storyboard_id, "audio")
    assert plan["credits"] == 0 and plan["scene_index"] is None

    result = redo_scene(engine, storyboard_id, str(uuid4()), kind="audio")

    assert result["credits"] == 0
    repaired = Path(result["film"]["file_path"])
    assert repaired != source and repaired.is_file()
    assert video_stream_sha256(ffmpeg, repaired) == video_stream_sha256(ffmpeg, source)
    assert sha(source) == film_before
    assert (len(images.asked), len(motion.asked)) == asked_before
    assert approvals(engine) == []
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob).where(
                VideoRenderJob.output_asset_id == result["film"]["output_asset_id"]
            )
        )
    assert job.production_json["remaster"]["kind"] == "audio"
    assert "-c:v" in job.command_args_json and "copy" in job.command_args_json


# ------------------------------- 3. a motion redo: one yes for this redo, one POST, no other


def test_a_motion_redo_needs_a_scene_redo_yes_bound_to_its_plan_and_posts_once(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    old = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=coloured_clip(tmp_path, "olive")))

    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert plan["action"] == REDO_ACTION and plan["tier"] == "T3"
    assert plan["model_id"] == "seedance2_5"
    assert plan["credits"] == 340 and plan["cap_credits"] == 680
    assert plan["replaces"] == [old[3]]

    # No yes yet: the Owner is asked, nothing is bought.
    with pytest.raises(SceneRedoRefused) as asked:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    assert asked.value.status == "NEEDS_APPROVAL" and asked.value.http_status == 202
    assert models.posts() == 0
    (question,) = approvals(engine)
    assert question.action == REDO_ACTION
    assert question.proposed_diff["plan_hash"] == plan["plan_hash"]
    assert question.proposed_diff["step"] == REDO_STEP
    assert question.proposed_diff["cap_credits"] == 680

    # A hash that is not this redo's buys nothing and asks nothing.
    with pytest.raises(SceneRedoRefused) as stale:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, "0" * 64)
    assert stale.value.status == "STALE_PLAN" and stale.value.http_status == 409
    assert len(approvals(engine)) == 1 and models.posts() == 0

    answer(engine, asked.value.approval_id, "APPROVED", note="Refă scena 3.")

    # The yes for scene 3 does not buy scene 4's redo.
    plan_4 = redo_plan(engine, storyboard_id, "motion", 4, capabilities=[SEEDANCE])
    with pytest.raises(SceneRedoRefused) as other:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 4, plan_4["plan_hash"])
    assert other.value.status == "NEEDS_APPROVAL"
    assert models.posts() == 0

    result = redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])

    assert models.posts() == 1, "a one-scene redo POSTed more than one shot"
    assert models.asked_for == ["seedance2_5"]
    assert result["kind"] == "motion" and result["scene_index"] == 3
    assert result["motion"]["bought_shots"] == 1
    scene_3 = [t for t in shot_takes(engine, storyboard_id) if t.scene_number == 3]
    by_id = {t.id: t for t in scene_3}
    assert by_id[old[3]].status == "REJECTED" and by_id[old[3]].failure_code == "REDO.OWNER"
    new = [t for t in scene_3 if t.id != old[3]]
    assert [t.status for t in new] == ["PAID"] and new[0].kind == "motion"
    for n in (1, 2, 4):
        (kept,) = [t for t in shot_takes(engine, storyboard_id) if t.scene_number == n]
        assert kept.id == old[n] and kept.status == "APPROVED"
    with Session(engine) as session:
        spent = session.get(ApprovalRequest, asked.value.approval_id)
        assert spent.consumed_at is not None

    # The spent yes buys nothing more: the redo's plan has changed (it replaces the new take).
    with pytest.raises(SceneRedoRefused) as again:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    assert again.value.status == "STALE_PLAN"
    assert models.posts() == 1


def test_a_motion_redo_rebuilds_only_its_shot_and_reuses_every_other(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    first = assemble_from_takes(
        engine, storyboard_id, str(uuid4()), storage_root=tmp_path / "media"
    )
    folder = Path(first["file_path"]).parent
    shots_before = {n: sha(folder / f"shot_{n:02d}.mp4") for n in range(1, 5)}
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=coloured_clip(tmp_path, "olive")))

    plan = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    assert plan["base_asset_id"] == first["output_asset_id"]
    with pytest.raises(SceneRedoRefused) as asked:
        redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED")
    result = redo_motion(engine, storyboard_id, tmp_path, models, account, 3, plan["plan_hash"])

    assert models.posts() == 1
    film = result["film"]
    assert film["reused_shots"] == [1, 2, 4] and film["rebuilt_shots"] == [3]
    for n in (1, 2, 4):
        assert sha(folder / f"shot_{n:02d}.mp4") == shots_before[n]
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == film["output_asset_id"])
        )
    remaster = job.production_json["remaster"]
    assert remaster["redo"] == "motion" and remaster["scene_index"] == 3
    assert remaster["credits_quoted"] == 340
    scene_3 = {e["scene_index"]: e for e in job.production_json["scenes"]}[3]
    new_take = [
        t for t in shot_takes(engine, storyboard_id) if t.scene_number == 3 and t.status == "PAID"
    ]
    assert scene_3["motion"]["take_id"] == new_take[0].id


# --------------------------------- 4. a still redo: one pair, only scene 3's shot invalidated


def test_a_still_redo_buys_one_pair_and_invalidates_only_scene_3s_motion(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    shots = filmed(engine, storyboard_id, tmp_path, coloured_clip(tmp_path, "navy"))
    stills_before = {t.scene_number: t for t in takes(engine, storyboard_id, "still")}
    motion_3 = redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])
    motion_4 = redo_plan(engine, storyboard_id, "motion", 4, capabilities=[SEEDANCE])

    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert plan["action"] == REDO_ACTION and plan["model_id"] == "seedream5_pro"
    assert plan["credits"] == 18 and plan["cap_credits"] == 54
    assert plan["replaces"] == [stills_before[3].id]
    assert plan["invalidates"] == [shots[3]]

    images = SpyStills(balance=1_000)
    judge = SpyJudge()

    def run(plan_hash: str):
        return redo_scene(
            engine,
            storyboard_id,
            str(uuid4()),
            kind="still",
            scene_index=3,
            plan_hash=plan_hash,
            image_adapter=images,
            judge=judge,
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    with pytest.raises(SceneRedoRefused) as asked:
        run(plan["plan_hash"])
    assert asked.value.status == "NEEDS_APPROVAL"
    assert images.asked == []
    (question,) = approvals(engine)
    assert question.action == REDO_ACTION
    assert question.proposed_diff["plan_hash"] == plan["plan_hash"]
    answer(engine, asked.value.approval_id, "APPROVED")

    result = run(plan["plan_hash"])

    assert len(images.asked) == 1, "a one-scene still redo bought more than one request"
    assert images.asked[0]["count"] == 2 and images.asked[0]["ratio"] == "1530:2720"
    # Figure 1: scene 1's approved still, for its light, palette and grain.
    assert images.asked[0]["references"] == [Path(stills_before[1].path).read_bytes()]
    assert len(judge.looked_at) == 2
    assert result["still"]["status"] == "APPROVED"

    stills = [t for t in takes(engine, storyboard_id, "still") if t.scene_number == 3]
    old = next(t for t in stills if t.id == stills_before[3].id)
    assert old.status == "REJECTED" and old.failure_code == "REDO.OWNER"
    new = sorted(t.status for t in stills if t.id != old.id)
    assert new == ["APPROVED", "PAID"]
    for n in (1, 2, 4):
        kept = [t for t in takes(engine, storyboard_id, "still") if t.scene_number == n]
        assert [(t.id, t.status) for t in kept] == [(stills_before[n].id, "APPROVED")]

    # Only scene 3's shot was filmed from the old still: only it is invalidated.
    by_scene = {t.scene_number: t for t in shot_takes(engine, storyboard_id)}
    assert by_scene[3].status == "REJECTED" and by_scene[3].failure_code == "REDO.STILL_REPLACED"
    assert all(by_scene[n].status == "APPROVED" for n in (1, 2, 4))
    # A motion redo of scene 4 waits on the same plan as before; scene 3's plan is new.
    assert (
        redo_plan(engine, storyboard_id, "motion", 4, capabilities=[SEEDANCE])["plan_hash"]
        == (motion_4["plan_hash"])
    )
    assert (
        redo_plan(engine, storyboard_id, "motion", 3, capabilities=[SEEDANCE])["plan_hash"]
        != motion_3["plan_hash"]
    )


# ------------------------------------------------------------------- 5. the Owner's routes


def test_the_redo_routes_answer_200_for_a_free_redo_and_202_for_a_paid_one(
    client, engine, headers, tmp_path
):
    storyboard_id, render, images, motion = a_rendered_nepal_film(engine, tmp_path)
    filmed_id = a_film(engine, tmp_path, scenes=4)
    filmed(engine, filmed_id, tmp_path, coloured_clip(tmp_path, "navy"))
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account, clip=coloured_clip(tmp_path, "olive")))
    state = client.app.app.state
    state.media_storage_root = tmp_path / "media"
    state.scene_model_capabilities = [SEEDANCE]
    state.runway_account = account
    state.video_adapter_for_model = models
    base = f"/api/v1/media/storyboards/{storyboard_id}"
    filmed_base = f"/api/v1/media/storyboards/{filmed_id}"

    card = client.post(f"{base}/redo", headers=headers, json={"kind": "card", "scene_index": 5})
    assert card.status_code == 200, card.text
    assert card.json()["credits"] == 0
    assert card.json()["film"]["reused_shots"] == [1, 2, 3, 4, 6]

    # The rendered film's stills were bought but nobody approved them: no motion redo yet.
    unapproved = client.get(
        f"{base}/redo-plan", headers=headers, params={"kind": "motion", "scene": 3}
    )
    assert unapproved.status_code == 409
    assert unapproved.json()["detail"]["status"] == "NEEDS_STILL"

    planned = client.get(
        f"{filmed_base}/redo-plan", headers=headers, params={"kind": "motion", "scene": 3}
    )
    assert planned.status_code == 200, planned.text
    plan = planned.json()
    assert plan["action"] == REDO_ACTION and plan["credits"] == 340

    paid = client.post(
        f"{filmed_base}/redo",
        headers=headers,
        json={"kind": "motion", "scene_index": 3, "plan_hash": plan["plan_hash"]},
    )
    assert paid.status_code == 202, paid.text
    assert paid.json()["approval_id"] and paid.json()["cap_credits"] == 680
    assert models.posts() == 0

    no_hash = client.post(
        f"{filmed_base}/redo", headers=headers, json={"kind": "motion", "scene_index": 3}
    )
    assert no_hash.status_code == 409
    assert no_hash.json()["detail"]["status"] == "NO_PLAN"
    unknown = client.post(f"{base}/redo", headers=headers, json={"kind": "film", "scene_index": 3})
    assert unknown.status_code == 422
    missing = client.post(f"{base}/redo", headers=headers, json={"kind": "card", "scene_index": 9})
    assert missing.status_code == 404
    assert client.post(f"{base}/redo", json={"kind": "audio"}).status_code == 401
    assert models.posts() == 0
    with Session(engine) as session:
        scene_5 = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 5
            )
        )
        assert scene_5.scene_kind == "DATA_CARD"
