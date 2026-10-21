"""The last door before RunPod never sends a seed that already drew a picture for its scene.

The Owner, 2026-10-12 22:00: «Cum este permis să facă 9 încercări… și el să facă același
video?». The cyclotron film aa170155 bought its scene-4 and scene-5 stills again in four rounds
on the SAME two seeds (2509052738/2571181196, 596097424/719292034): the journal moved each
redo to the next attempt and kept the seed. The serial f06808c9 drew its scene-4 index-1 and
index-2 seeds a third time at 11:33 and 11:47 UTC. `batch.reserve_item` now replaces such a
seed with `batch.fresh_item_seed` and journals the asked one as ``seed_asked``; a resend of the
SAME row (a crash before /run, an unanswered /run, a /run proven never queued) keeps its key and
its fresh seed. Every RunPod, bucket and GPU call is faked; nothing is bought.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from app.providers.runpod import batch as batch_module
from app.providers.runpod.adapters import RunPodImageAdapter, RunPodVideoAdapter
from app.providers.runpod.batch import (
    SEED_EVENT,
    fresh_item_seed,
    item_seed,
    journal_payload,
    reserve_item,
)
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.errors import RunPodProtocolError
from app.providers.runpod.jobs import GenerationJob, JobStore, digest, now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import Cloud, Session_, adapter, request, serverless

#: The two films of the incident, with the seeds the live journal shows they reused.
CYCLOTRON = "aa170155-56c7-4e29-9616-e1e917fb243e"
SERIAL = "f06808c9-40d4-4f40-a980-84b6a5540348"


def still(project, scene, candidate, seed, *, prompt="the brass cyclotron", attempt=1):
    """A still request as the stills step built it before 1fbc4f9: attempt 1 in every step."""
    return request(
        scene,
        candidate,
        attempt,
        project_id=project,
        seed=seed,
        prompt=f"{prompt}, candidate {candidate}",
    )


def finish_round(cloud, run, count):
    """The worker makes every item of the round's job; the studio collects them."""
    job = list(cloud.jobs)[-1]
    for index in range(count):
        cloud.finish(job, index)
    outcomes = []
    while not run.done():
        outcomes += run.poll()
    assert {o.state for o in outcomes} == {"COMPLETED"}
    return cloud.jobs[job]["input"]["items"]


def journal(engine, **where):
    with Session(engine) as s:
        query = select(GenerationJob).order_by(GenerationJob.created_at, GenerationJob.attempt)
        for name, value in where.items():
            query = query.where(getattr(GenerationJob, name) == value)
        return list(s.scalars(query))


def seed_events(engine):
    with Session(engine) as s:
        return [
            e.payload
            for e in s.scalars(select(DomainEvent).where(DomainEvent.event_type == SEED_EVENT))
        ]


# ------------------------------------------------------------------------------ the helper


def test_fresh_item_seed_skips_used():
    used = {item_seed("f", 4, 1, 0), item_seed("f", 4, 2, 0)}
    assert fresh_item_seed("f", 4, 1, 0, used) == item_seed("f", 4, 3, 0)
    assert fresh_item_seed("f", 4, 1, 0, frozenset()) == item_seed("f", 4, 1, 0)
    # The index starts at 1 and the journal's scene id ("4") is the stills step's scene (4).
    assert fresh_item_seed("f", "4", 0, 0, frozenset()) == item_seed("f", 4, 1, 0)
    # A clip's fresh seed is its own draw, never the still's seed of the same index.
    clip = fresh_item_seed("f", 4, 1, 0, frozenset(), operation="video")
    assert clip != item_seed("f", 4, 1, 0)
    assert clip == fresh_item_seed("f", "4", 1, 0, frozenset(), operation="video")
    assert 0 <= clip <= 2**32 - 1


def test_fresh_item_seed_gives_up_instead_of_repeating(monkeypatch):
    monkeypatch.setattr(batch_module, "FRESH_SEED_TRIES", 3)
    used = {item_seed("f", 4, index, 0) for index in (1, 2, 3)}
    with pytest.raises(RunPodProtocolError):
        fresh_item_seed("f", 4, 1, 0, used)


def test_the_seed_formula_is_the_one_the_incident_reused():
    # Calibrated on the live journal (cloud_generation_job, read-only): these are the seeds
    # the cyclotron's still redos and the serial's scene-4 redos sent again and again.
    assert [item_seed(CYCLOTRON, 4, 1, c) for c in (0, 1)] == [2509052738, 2571181196]
    assert [item_seed(CYCLOTRON, 5, 1, c) for c in (0, 1)] == [596097424, 719292034]
    assert [item_seed(SERIAL, 4, i, c) for i in (1, 2) for c in (0, 1)] == [
        3380412453,
        1474500984,
        3724002785,
        3954483751,
    ]


# ------------------------------------------------------------------------ the door itself


def test_a_seed_that_already_made_a_picture_is_never_sent_again(engine, tmp_path, caplog):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = request()
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (first,) = finish_round(cloud, run, 1)
    assert first["seed"] == asked.seed

    caplog.set_level(logging.INFO, logger="studio.runpod")
    session = Session_()
    taken = []
    run = made.submit_batch([asked], session=session, on_submitted=taken.append)
    (again,) = cloud.jobs["job-2"]["input"]["items"]
    fresh = fresh_item_seed("film-1", "1", 2, 0, {asked.seed})
    assert again["seed"] == fresh != asked.seed
    # The take is written with the seed really sent; the row keeps both.
    (item,) = taken
    assert item.request.seed == fresh and item.request.seed_asked == asked.seed
    rows = journal(engine)
    assert [r.attempt for r in rows] == [1, 2]
    assert rows[1].request["seed"] == fresh and rows[1].request["seed_asked"] == asked.seed
    assert rows[1].request_digest == digest(journal_payload(item.request))
    assert "seed_asked" not in rows[0].request
    (logged,) = [r for r in caplog.records if r.getMessage() == "runpod_seed_refreshed"]
    assert logged.seed_asked == asked.seed and logged.seed_sent == fresh
    (event,) = seed_events(engine)
    assert event["seed_asked"] == asked.seed and event["seed_sent"] == fresh
    assert event["storyboard_id"] == "film-1" and event["scene_number"] == 1
    assert event["operation"] == "image" and event["job_row_id"] == rows[1].id
    assert "sămânța nouă" in event["reason_ro"] and str(fresh) in event["reason_ro"]
    finish_round(cloud, run, 1)


def test_the_cyclotron_rounds_get_new_seeds(engine, tmp_path):
    """Four rounds of scene 4, each asking index 1 again with changed words (the rounds of
    11 Oct 11:43, 13:50, 20:07 and 12 Oct 06:54): every round draws two pictures never drawn."""
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = [item_seed(CYCLOTRON, 4, 1, c) for c in (0, 1)]
    sent: list[int] = []
    for number, words in enumerate(("A", "B", "C", "D"), start=1):
        requests = [
            still(CYCLOTRON, "4", c, asked[c], prompt=f"brass cyclotron, words {words}")
            for c in (0, 1)
        ]
        run = made.submit_batch(requests, session=Session_(), on_submitted=lambda item: None)
        seeds = [it["seed"] for it in finish_round(cloud, run, 2)]
        if number == 1:
            assert seeds == asked
        else:
            assert not set(seeds) & set(sent), f"round {number} drew an old picture again"
        sent += seeds
    assert len(set(sent)) == 8
    rows = journal(engine, project_id=CYCLOTRON)
    assert sorted({r.attempt for r in rows}) == [1, 2, 3, 4]
    assert all(r.request.get("seed_asked") in asked for r in rows if r.attempt > 1)
    assert len(seed_events(engine)) == 6


def test_the_serials_scene_four_replayed_from_its_journal_gets_seeds_it_never_drew(engine):
    """The live journal of serial f06808c9 scene 4 before 11:33 UTC on 2026-10-12: attempts
    1-5, two COMPLETED stills each, on the index-1, -2, -3, -1 and -2 pairs (11 Oct 19:29,
    19:59, 20:03; 12 Oct 04:53, 05:04). The 11:33 redo asked the index-1 pair a third time and
    the journal sent it as attempt 6; at the door it now gets two seeds never drawn."""
    config = serverless()
    history = [(1, 1), (2, 2), (3, 3), (4, 1), (5, 2)]  # (attempt, seed index)
    drawn = {item_seed(SERIAL, 4, index, c) for _attempt, index in history for c in (0, 1)}
    with Session(engine) as s, s.begin():
        for attempt, index in history:
            for candidate in (0, 1):
                seed = item_seed(SERIAL, 4, index, candidate)
                s.add(journal_row(config, SERIAL, "4", attempt, candidate, seed, "COMPLETED"))
    store = JobStore(engine)
    sent = []
    for candidate in (0, 1):
        asked = still(SERIAL, "4", candidate, item_seed(SERIAL, 4, 1, candidate))
        row, action, effective = reserve_item(store, config, None, asked)
        assert action == "SEND" and row.attempt == 6
        assert effective.seed_asked == asked.seed and effective.attempt_number == 6
        sent.append(effective.seed)
    assert not set(sent) & drawn and len(set(sent)) == 2
    assert sent[0] == fresh_item_seed(SERIAL, "4", 6, 0, drawn)
    assert sent[1] == fresh_item_seed(SERIAL, "4", 6, 1, drawn | {sent[0]})


def journal_row(config, project, scene, attempt, candidate, seed, status):
    """A still's journal row as the live database holds it (a COMPLETED one with its asset)."""
    payload = journal_payload(still(project, scene, candidate, seed, attempt=attempt))
    hashed = digest(payload)
    target = batch_module.target_identity(config, None)
    key = digest([target, project, scene, attempt, "image", candidate])
    return GenerationJob(
        id=batch_module._uuid(),
        idempotency_key=key,
        payload_hash=hashed,
        request_digest=hashed,
        integration_id=None,
        provider="RUNPOD",
        target=target,
        project_id=project,
        scene_id=scene,
        attempt=attempt,
        operation="image",
        model=payload["model"],
        gpu="RTX PRO 6000",
        hourly_rate="4.00",
        status=status,
        request=payload,
        output={},
        created_at=now(),
        poll_count=0,
        remote_job_id=f"live-{attempt}:{candidate}",
        asset_path=f"/media/{project}/{attempt}_{candidate}.png" if status == "COMPLETED" else None,
    )


def test_a_seed_still_on_its_way_is_not_sent_twice_in_one_round(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    one = request("4", 0)
    two = request("4", 1, seed=one.seed)
    run = made.submit_batch([one, two], session=Session_(), on_submitted=lambda item: None)
    first, second = cloud.jobs["job-1"]["input"]["items"]
    assert first["seed"] == one.seed and second["seed"] != one.seed
    assert second["seed"] == fresh_item_seed("film-1", "4", 1, 1, {one.seed})
    finish_round(cloud, run, 2)


def test_a_fresh_seed_is_sent_exactly_as_asked(engine, tmp_path):
    """Byte for byte as before: no ``seed_asked``, the same digest the journal always wrote."""
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = request("3", 1)
    taken = []
    made.submit_batch([asked], session=Session_(), on_submitted=taken.append)
    (row,) = journal(engine)
    assert taken[0].request == asked and "seed_asked" not in row.request
    assert row.request_digest == digest(journal_payload(asked))
    assert cloud.jobs["job-1"]["input"]["items"][0]["seed"] == asked.seed
    assert seed_events(engine) == []


def test_another_scene_or_the_other_operation_may_use_the_seed(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = request("1", 0)
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    finish_round(cloud, run, 1)
    # Scene 2 on scene 1's seed: another scene, another picture.
    made.submit_batch(
        [request("2", 0, seed=asked.seed)], session=Session_(), on_submitted=lambda item: None
    )
    assert cloud.jobs["job-2"]["input"]["items"][0]["seed"] == asked.seed
    # Scene 1's clip on its still's seed: the still's journal is not the clip's.
    video = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    video.core.transport = video.core.client.transport = cloud
    video.submit_batch(
        [request("1", 0, operation="video", seed=asked.seed)],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    assert cloud.jobs["job-3"]["input"]["items"][0]["seed"] == asked.seed


def test_a_clip_whose_seed_already_made_a_clip_gets_a_fresh_one(engine, tmp_path):
    cloud = Cloud()
    video = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    video.core.transport = video.core.client.transport = cloud
    # The motion step's film seed (580970440 on the cyclotron) asked again for scene 1.
    asked = request("1", 0, operation="video", project_id=CYCLOTRON, seed=580970440)
    run = video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    finish_round(cloud, run, 1)
    run = video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (again,) = cloud.jobs["job-2"]["input"]["items"]
    assert again["seed"] == fresh_item_seed(CYCLOTRON, "1", 2, 0, {580970440}, operation="video")
    assert again["seed"] != 580970440
    (event,) = seed_events(engine)
    assert "un clip" in event["reason_ro"] and event["operation"] == "video"


def test_a_clip_that_expired_undelivered_may_go_again_on_its_seed(engine, tmp_path):
    """Nothing reached the studio, so nothing is repeated: the cyclotron's scene-1 clip that
    expired undelivered at 16:55 UTC (seed 580970446) went again on that seed at 18:07."""
    cloud = Cloud()
    video = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    video.core.transport = video.core.client.transport = cloud
    asked = request("1", 0, operation="video", project_id=CYCLOTRON, seed=580970446)
    run = video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    cloud.status_answers["job-1"] = [MediaProviderError("gone", http_status=404)]
    assert [o.error for o in run.poll()] == ["EXPIRED_UNDELIVERED"]
    video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    assert cloud.jobs["job-2"]["input"]["items"][0]["seed"] == 580970446
    assert [r.attempt for r in journal(engine)] == [1, 2]
    assert seed_events(engine) == []


# ----------------------------------------------------------- resends keep key and seed


def _completed_then(engine, tmp_path, cloud):
    """Round 1 drew a picture on the asked seed; the next purchase must get a fresh one."""
    made = adapter(engine, tmp_path, cloud)
    asked = request()
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    finish_round(cloud, run, 1)
    return made, asked


def test_a_crash_before_the_run_resends_the_same_key_with_its_fresh_seed(engine, tmp_path):
    cloud = Cloud()
    made, asked = _completed_then(engine, tmp_path, cloud)
    # Reserved, then the studio stopped before the /run (the row stays STARTING).
    row, action, effective = reserve_item(JobStore(engine), made.config, made.integration_id, asked)
    assert action == "SEND" and effective.seed != asked.seed
    # The step runs again and asks the same seed: the same row, the same fresh seed.
    taken = []
    made.submit_batch([asked], session=Session_(), on_submitted=taken.append)
    (sent,) = cloud.jobs["job-2"]["input"]["items"]
    assert sent["idempotency_key"] == row.idempotency_key and sent["seed"] == effective.seed
    assert taken[0].request == effective
    assert len(journal(engine)) == 2


def test_an_unanswered_run_resends_the_same_key_with_its_fresh_seed(engine, tmp_path):
    cloud = Cloud()
    made, asked = _completed_then(engine, tmp_path, cloud)
    cloud.run_answers = [MediaProviderError("lost", unanswered=True)]
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    assert [o.error for o in run.poll()] == ["SUBMISSION_UNCERTAIN"]
    rows = journal(engine)
    uncertain = rows[-1]
    assert uncertain.error_code == "SUBMISSION_UNCERTAIN"
    fresh = uncertain.request["seed"]
    assert fresh != asked.seed and uncertain.request["seed_asked"] == asked.seed
    # No event yet: RunPod never answered with a job id.
    assert seed_events(engine) == []
    made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (sent,) = cloud.jobs["job-2"]["input"]["items"]
    assert sent["idempotency_key"] == uncertain.idempotency_key and sent["seed"] == fresh
    assert len(journal(engine)) == 2
    (event,) = seed_events(engine)
    assert event["seed_sent"] == fresh


def test_a_run_proven_never_queued_goes_again_on_its_key_and_fresh_seed(engine, tmp_path):
    cloud = Cloud()
    made, asked = _completed_then(engine, tmp_path, cloud)
    cloud.run_answers = [MediaProviderError("connect", unsent=True)]
    with pytest.raises(MediaProviderError):
        made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    unsent = journal(engine)[-1]
    assert unsent.status == "FAILED" and unsent.error_code == "UNSENT"
    fresh = unsent.request["seed"]
    assert fresh != asked.seed
    made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (sent,) = cloud.jobs["job-2"]["input"]["items"]
    assert sent["idempotency_key"] == unsent.idempotency_key and sent["seed"] == fresh
    assert len(journal(engine)) == 2


def test_an_unsent_row_whose_seed_drew_a_picture_since_is_not_reused(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = request(prompt="the first words")
    cloud.run_answers = [MediaProviderError("connect", unsent=True)]
    with pytest.raises(MediaProviderError):
        made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    # Other words on the same seed drew a picture meanwhile (attempt 2).
    run = made.submit_batch(
        [replace(asked, prompt="other words")], session=Session_(), on_submitted=lambda i: None
    )
    (drawn,) = finish_round(cloud, run, 1)
    assert drawn["seed"] == asked.seed
    # The first words asked again: their unsent row stays unsent, a new attempt draws anew.
    made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (sent,) = cloud.jobs["job-2"]["input"]["items"]
    assert sent["seed"] != asked.seed
    rows = journal(engine)
    assert [(r.attempt, r.status) for r in rows[:2]] == [(1, "FAILED"), (2, "COMPLETED")]
    assert rows[2].attempt == 3 and rows[2].request["seed_asked"] == asked.seed


def test_the_watchdog_stand_in_keeps_both_seeds(engine, tmp_path):
    cloud = Cloud()
    made, asked = _completed_then(engine, tmp_path, cloud)
    made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    rebuilt = batch_module._request_of(journal(engine)[-1])
    assert rebuilt.seed_asked == asked.seed and rebuilt.seed != asked.seed


def test_the_mock_rounds_get_fresh_seeds_too(engine, tmp_path):
    made = RunPodImageAdapter(
        RunPodConfig(_env_file=None, enabled=True, mock=True), engine, storage_root=tmp_path
    )
    seeds = []
    for _round in range(3):
        run = made.submit_batch([request()], session=Session_(), on_submitted=lambda item: None)
        outcomes = []
        while not run.done():
            outcomes += run.poll()
        seeds += [o.item.request.seed for o in outcomes]
    assert len(set(seeds)) == 3


# ------------------------------------------------------------- review 2026-10-12: attacks


def test_a_resend_asking_the_seed_really_sent_is_the_same_purchase(engine, tmp_path):
    """After a crash the stage may ask the very seed the door sent (its own counter moved past
    the old one): that is the SAME purchase, byte for byte, never «another payload» on an open
    key (IDEMPOTENCY_CONFLICT would leave the scene stuck behind its own reserved row)."""
    cloud = Cloud()
    made, asked = _completed_then(engine, tmp_path, cloud)
    store = JobStore(engine)
    row, action, effective = reserve_item(store, made.config, made.integration_id, asked)
    assert action == "SEND" and effective.seed != asked.seed
    again, action, resent = reserve_item(
        store, made.config, made.integration_id, replace(asked, seed=effective.seed)
    )
    assert action == "RESEND" and again.id == row.id
    assert resent == effective
    assert digest(journal_payload(resent)) == again.request_digest


def test_a_request_handed_back_with_its_seed_asked_is_not_refreshed_twice(engine, tmp_path):
    """``seed_asked`` is the door's own record: a request that carries one (an item handed
    back) is read for its seed alone, so a seed still fresh is sent with no false «refreshed»
    line, event or journal key."""
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = replace(request("2", 0), seed_asked=123)
    made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (row,) = journal(engine)
    assert "seed_asked" not in row.request
    assert row.request_digest == digest(journal_payload(replace(asked, seed_asked=None)))
    assert seed_events(engine) == []


def test_a_seed_that_ended_twice_without_a_picture_is_not_sent_a_third_time(engine, tmp_path):
    """A technical ending after RunPod took the job (expired, cancelled, a worker error) drew
    nothing the studio saw, so the seed may go once more; twice is no longer luck (a seed the
    worker cannot finish, an output it cannot hand over): the third purchase gets a new seed."""
    cloud = Cloud()
    video = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    video.core.transport = video.core.client.transport = cloud
    asked = request("1", 0, operation="video", project_id=CYCLOTRON, seed=580970446)
    for job in ("job-1", "job-2"):
        run = video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
        cloud.status_answers[job] = [MediaProviderError("gone", http_status=404)]
        assert [o.error for o in run.poll()] == ["EXPIRED_UNDELIVERED"]
        assert cloud.jobs[job]["input"]["items"][0]["seed"] == 580970446
    video.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (third,) = cloud.jobs["job-3"]["input"]["items"]
    assert third["seed"] != 580970446
    assert third["seed"] == fresh_item_seed(CYCLOTRON, "1", 3, 0, {580970446}, operation="video")
    assert [r.attempt for r in journal(engine)] == [1, 2, 3]


def test_a_proven_unsent_seed_is_never_spent_by_its_refusals(engine, tmp_path):
    """RunPod never took a /run proven unsent: however often that happens, the key and its seed
    go again (cb14792), never a new attempt."""
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    asked = request("5", 1)
    for _ in range(3):
        cloud.run_answers = [MediaProviderError("connect", unsent=True)]
        with pytest.raises(MediaProviderError):
            made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    run = made.submit_batch([asked], session=Session_(), on_submitted=lambda item: None)
    (sent,) = cloud.jobs["job-1"]["input"]["items"]
    assert sent["seed"] == asked.seed
    assert [r.attempt for r in journal(engine)] == [1]
    finish_round(cloud, run, 1)


def test_a_fresh_seed_leaves_room_for_the_clip_retry(monkeypatch):
    """Clip QC's one retry is the sent seed + 1 (`qc.clip_retry_decision`) and the worker takes
    seeds up to 2**32 - 1 (`contract.MAX_SEED`): the door never hands out the last seed."""
    from runpod_worker import contract

    def drawn(storyboard_id, scene, attempt, candidate):
        return contract.MAX_SEED if attempt == 1 else 7

    monkeypatch.setattr(batch_module, "item_seed", drawn)
    assert fresh_item_seed("f", 1, 1, 0, frozenset(), operation="video") == 7
    assert fresh_item_seed("f", 1, 1, 0, frozenset()) == 7
