"""A scene bought again on the same words draws a different picture or clip (2026-10-12).

The film's one seed was used on every shot of the film, so a scene bought again on words that
had not changed — the serial's, whose words are the composer's and may already be today's —
would have made the same clip and failed the same check; the stills' re-rolls were numbered
from 1 in every step, so a second step drew the same candidates again. Now a scene's motion
round is seeded past the clips the scene already had (`assembler._scene_seed`, two seeds a
round: the shot and its clip-QC retry), and the stills' re-rolls are numbered past every still
the scene ever had (`stills_stage._Scene.rolls`). Every provider faked, 0 credits.
"""

from __future__ import annotations

from uuid import uuid4

from app.media import assembler
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, SEED_RANGE, film_seed
from app.media.models import SceneTake
from app.services import append_event, utc_now
from sqlalchemy.orm import Session
from test_film_costing import (
    SEEDANCE,
    Account,
    Models,
    SpyVideo,
    a_film,
    approved,
    by_scene,
    hero_approved,
    takes,
)


def test_a_scenes_round_is_seeded_past_the_clips_it_already_had():
    base = film_seed("a-film")
    assert assembler._scene_seed(base, 0) == base
    assert assembler._scene_seed(base, 1) == (base + 2) % SEED_RANGE
    assert assembler._scene_seed(base, 2) == (base + 4) % SEED_RANGE
    assert assembler._scene_seed(SEED_RANGE - 1, 1) == 1


def test_a_clip_bought_again_on_the_same_words_after_her_decision_gets_a_new_seed(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    account = Account(50_000)
    spy = SpyVideo("seedance2_5", account)
    models = Models(spy)
    hero_approved(engine, storyboard_id, tmp_path, models, account, capabilities=[SEEDANCE])
    first = approved(
        engine, storyboard_id, tmp_path, "motion", models, account, capabilities=[SEEDANCE]
    )
    base = first["seed"]
    assert base == film_seed(storyboard_id)
    assert by_scene(first)[2]["status"] == "PAID" and by_scene(first)[3]["status"] == "PAID"
    # The hero's test shot and the two shots of the rest: every first round on the film's seed.
    assert [ask["extra"]["seed"] for ask in spy.asked] == [base, base, base]

    # Clip QC refused scene 2's clip later; the Director decided about the scene (a rewrite
    # with the same words, as the serial's rung does): the scene is bought again.
    with Session(engine) as session, session.begin():
        (clip,) = [t for t in takes(engine, storyboard_id, "motion") if t.scene_number == 2]
        row = session.get(SceneTake, clip.id)
        row.status = "REJECTED"
        row.failure_code = "QC.CLIP"
        row.failure_detail = "apare text ars în cadru"
        append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {"scene_index": 2, "layer": "motion", "decided_by": "director"},
            str(uuid4()),
        )
    second = approved(
        engine, storyboard_id, tmp_path, "motion", models, account, capabilities=[SEEDANCE]
    )

    scenes = by_scene(second)
    assert scenes[2]["status"] == "PAID" and scenes[3]["status"] == "PAID"
    assert scenes[3].get("reused") is True, "scene 3's clip was bought again"
    assert second["seed"] == base, "the step's seed stays the film's"
    assert spy.asked[-1]["extra"]["seed"] == (base + 2) % SEED_RANGE
    clips = sorted(
        (t for t in takes(engine, storyboard_id, "motion") if t.scene_number == 2),
        key=lambda t: str(t.created_at),
    )
    assert [t.seed for t in clips] == [base, (base + 2) % SEED_RANGE]


def test_the_stills_rerolls_are_numbered_past_every_still_the_scene_had(engine, tmp_path):
    from app.media.stills_stage import _read_scenes

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    now = utc_now()
    with Session(engine) as session, session.begin():
        for row in session.query(SceneTake).filter_by(storyboard_id=storyboard_id, kind="still"):
            if int(row.scene_number) == 2:
                row.status = "REJECTED"
                row.failure_code = "LOCAL.STILL_GATE"
        for _ in range(2):
            session.add(
                SceneTake(
                    id=str(uuid4()),
                    storyboard_id=storyboard_id,
                    scene_number=2,
                    kind="still",
                    prompt_hash=uuid4().hex,
                    model_id="seedream5_pro",
                    resolution="1530:2720",
                    status="REJECTED",
                    failure_code="LOCAL.STILL_GATE",
                    failure_detail="două panouri",
                    path=None,
                    sha256=uuid4().hex,
                    created_at=now,
                    updated_at=now,
                )
            )

    _bible, scenes = _read_scenes(engine, storyboard_id)
    by_index = {scene.index: scene for scene in scenes}
    assert by_index[2].reuse is None and by_index[2].rolls == 3
    assert by_index[1].reuse is not None and by_index[1].rolls == 0
