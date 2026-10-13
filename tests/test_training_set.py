"""The studio's approved cadres become a training set, by themselves (2026-10-11).

The Owner's card after the LTX-2 trainer was read: «Strângem setul de date de acum, antrenăm
după ~100 de clipuri». Every take the gates let through is written once to a manifest beside
the media, with the exact prompt it was bought on and what the trainer wants to know; a take
turned down, or one whose file is gone, is not; at the milestone of approved serial clips the
Owner gets one letter, and nothing is trained or bought here.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.agents.models import AgentMessage
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.assembler import still_fields, take_hash
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.models import DomainEvent
from app.services import utc_now
from app.workflows.passes import WatchdogContext, registered_passes
from app.workflows.passes import training_set as training
from sqlalchemy import select
from sqlalchemy.orm import Session

STILL = "Warm hand-drawn 2D animation like the studio's own office picture. Marcus at his desk."
MOTION = "Slow push-in toward the subject. Marcus types the first line. Continuous, seamless shot."


def a_film(engine, tmp_path, *, serial: bool, scenes: int = 2) -> dict[str, Any]:
    ids = {k: str(uuid4()) for k in ("topic", "script", "board")}
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title="A film",
                topic="office",
                angle="a",
                target_audience="g",
                novelty_score=0.5,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title="The Zero Script Club" if serial else "Why the Cyclotron Fit on a Desk",
                voiceover_full_text="text",
                claim_ids_json=[],
                status="APPROVED",
                story_json={"kind": "office_serial"} if serial else None,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title="The Zero Script Club" if serial else "Why the Cyclotron Fit on a Desk",
                status="APPROVED",
                total_scenes=scenes,
                visual_bible_json={},
                series_key="office_serial" if serial else None,
                created_at=now,
            )
        )
        session.flush()
        for index in range(1, scenes + 1):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=STILL,
                    duration_seconds=5.0,
                    voiceover_segment="words",
                    scene_kind="LIVE",
                    prompt_json={
                        "still_prompt": STILL,
                        "motion_prompt": MOTION,
                        "camera_move": "slow push-in",
                        "series_look_version": 2 if serial else None,
                        "source": "model",
                    },
                    created_at=now,
                )
            )
    return ids


def a_take(
    engine,
    tmp_path,
    board: str,
    scene: int,
    kind: str,
    status: str = "APPROVED",
    *,
    approved_by: str | None = "still_gate",
    on_disk: bool = True,
    prompt_hash: str | None = None,
) -> str:
    take_id = str(uuid4())
    path = tmp_path / "media" / board / f"{take_id}.{'png' if kind == 'still' else 'mp4'}"
    if on_disk:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bytes")
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=board,
                scene_number=scene,
                kind=kind,
                prompt_hash=prompt_hash or uuid4().hex,
                model_id="Qwen-Image-2512" if kind == "still" else "LTX-2.5",
                resolution="1530:2720" if kind == "still" else "1080:1920",
                seconds=None if kind == "still" else 7.0,
                status=status,
                approved_by=approved_by,
                path=str(path),
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )
    return take_id


def run_pass(engine, settings) -> dict[str, Any]:
    return dict(training.collect_training_samples(WatchdogContext(engine, settings, "wd")))


def manifest(settings) -> list[dict[str, Any]]:
    return training.read_manifest(training.manifest_path(settings))


def test_approved_takes_are_written_once_with_their_exact_prompt(engine, settings, tmp_path):
    seed_initial_workforce(engine)
    film = a_film(engine, tmp_path, serial=True)
    exact = take_hash(still_fields(STILL, None), "Qwen-Image-2512")
    still = a_take(engine, tmp_path, film["board"], 1, "still", prompt_hash=exact)
    clip = a_take(engine, tmp_path, film["board"], 1, "motion", approved_by="clip_qc")
    a_take(engine, tmp_path, film["board"], 2, "still", status="REJECTED", approved_by=None)
    a_take(engine, tmp_path, film["board"], 2, "still", on_disk=False)

    first = run_pass(engine, settings)
    again = run_pass(engine, settings)

    assert first["added"] == 2 and again["added"] == 0
    rows = {row["take_id"]: row for row in manifest(settings)}
    assert set(rows) == {still, clip}
    assert rows[still]["prompt"] == STILL and rows[still]["prompt_matches"] is True
    assert rows[still]["kind"] == "still" and rows[still]["serial"] is True
    assert rows[still]["film_title"] == "The Zero Script Club"
    assert rows[still]["series_look_version"] == 2 and rows[still]["approved_by"] == "still_gate"
    assert rows[clip]["prompt"] == MOTION and rows[clip]["camera_move"] == "slow push-in"
    assert rows[clip]["seconds"] == 7.0 and rows[clip]["model_id"] == "LTX-2.5"
    assert rows[clip]["prompt_matches"] is None
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == training.SAMPLE_EVENT)
        ).all()
        assert len(events) == 1 and events[0].payload["added"] == 2
        assert events[0].payload["serial_clips"] == 1


def test_a_still_drawn_from_other_words_is_kept_but_marked(engine, settings, tmp_path):
    seed_initial_workforce(engine)
    film = a_film(engine, tmp_path, serial=False)
    older = a_take(engine, tmp_path, film["board"], 1, "still", approved_by="owner")

    run_pass(engine, settings)

    (row,) = manifest(settings)
    assert row["take_id"] == older and row["prompt"] == STILL
    assert row["prompt_matches"] is False and row["serial"] is False
    assert row["approved_by"] == "owner" and row["series_look_version"] is None


def test_the_milestone_writes_the_owner_one_letter_and_trains_nothing(
    engine, settings, tmp_path, monkeypatch
):
    seed_initial_workforce(engine)
    monkeypatch.setattr(training, "MILESTONE_CLIPS", 2)
    film = a_film(engine, tmp_path, serial=True)
    a_take(engine, tmp_path, film["board"], 1, "motion", approved_by="clip_qc")
    first = run_pass(engine, settings)
    assert first["milestone"] is False
    a_take(engine, tmp_path, film["board"], 2, "test_shot", approved_by="owner")

    reached = run_pass(engine, settings)
    once_more = run_pass(engine, settings)

    assert reached["milestone"] is True and reached["clips"] == 2
    assert once_more["milestone"] is False
    with Session(engine) as session:
        letters = [
            m
            for m in session.scalars(select(AgentMessage))
            if (m.body_json or {}).get("kind") == training.LETTER_KIND
        ]
        assert len(letters) == 1
        assert letters[0].to_agent_id is None and "2 clipuri" in letters[0].body_text
        assert "nu se cheltuie nimic" in letters[0].body_text
        milestones = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == training.MILESTONE_EVENT)
        ).all()
        assert len(milestones) == 1


def test_the_pass_is_registered_after_the_serial_pass_and_the_manifest_survives_bad_lines(
    settings, tmp_path
):
    orders = {item.name: item.order for item in registered_passes()}
    assert orders["training_set"] == 170 and orders["serial_unfilmed"] < orders["training_set"]
    path = training.manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"take_id": "a"}\nnot json\n\n{"take_id": "b"}\n', encoding="utf-8")
    assert [row["take_id"] for row in training.read_manifest(path)] == ["a", "b"]
    assert json.dumps(training.read_manifest(path)[0]) == '{"take_id": "a"}'
