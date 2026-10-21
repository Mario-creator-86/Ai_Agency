"""A frame cut that fails keeps its scene's name with it (the audit of 2026-10-16, SAFE-001).

`editorial.frames_for` used to skip a frame ffmpeg could not cut and keep going. The names were
then cut from the end of the list: the Director was told «the middle of scenes 1, 2» about the
frames of scenes 1 and 3, and the film's picture look judged scene 3's frame as scene 2's and
named scene 3, the one that had been seen, as unlooked-at. Now each picked moment keeps its own
place, a failed one as None; the scene whose cut failed is left out with its frame and said to
have none.

No provider is called: every model is scripted, the encoder is faked.
"""

from __future__ import annotations

import base64
import json
import subprocess
from uuid import uuid4

from app.agents.editorial import editorial_review, frames_for
from app.media.models import MediaAsset, StoryboardScene
from app.media.picture_qc import evaluate_pictures
from app.services import utc_now
from sqlalchemy import delete
from sqlalchemy.orm import Session
from test_editorial import (
    ENGLISH,
    staffed,  # noqa: F401 - the fixture
)
from test_editorial import a_film as an_editorial_film
from test_editorial import registry_with as editorial_registry
from test_picture_qc import a_film as a_picture_film
from test_picture_qc import give_vision, registry_with, scene_answer, staff

REAL_RUN = subprocess.run


def _encoder(
    monkeypatch, *, fails: frozenset[int] | set[int], hangs: frozenset[int] = frozenset()
) -> list[float]:
    """ffmpeg, faked: the n-th cut (from 0) in ``fails`` exits 1 with nothing, one in ``hangs``
    times out; every other cut returns «frame at <seconds>». Any other command runs as it is."""
    cut: list[float] = []

    def run(args, **kwargs):
        if not isinstance(args, list) or "-ss" not in args or args[0] != "ffmpeg":
            return REAL_RUN(args, **kwargs)
        number = len(cut)
        moment = float(args[args.index("-ss") + 1])
        cut.append(moment)
        if number in hangs:
            raise subprocess.TimeoutExpired(args, 60)
        if number in fails:
            return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"broken")
        return subprocess.CompletedProcess(args, 0, stdout=f"frame at {moment:.2f}".encode())

    monkeypatch.setattr("app.agents.editorial.find_ffmpeg", lambda _path=None: "ffmpeg")
    monkeypatch.setattr("app.agents.editorial.subprocess.run", run)
    return cut


def _seen(frame: str | None) -> str | None:
    return None if frame is None else base64.b64decode(frame).decode()


def test_a_failed_cut_keeps_its_place_and_the_later_frames_keep_theirs(tmp_path, monkeypatch):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not decoded: the encoder is faked")
    _encoder(monkeypatch, fails={1})

    frames = frames_for(str(film), None, 18.0, [6.0, 6.0, 6.0], picks=[0, 1, 2])

    assert [_seen(frame) for frame in frames] == ["frame at 3.00", None, "frame at 15.00"]


def test_an_encoder_that_hangs_leaves_every_moment_after_it_unseen(tmp_path, monkeypatch):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not decoded: the encoder is faked")
    cut = _encoder(monkeypatch, fails=set(), hangs={1})

    frames = frames_for(str(film), None, 18.0, [6.0, 6.0, 6.0], picks=[0, 1, 2])

    assert [_seen(frame) for frame in frames] == ["frame at 3.00", None, None]
    assert len(cut) == 2, "a hung encoder is not asked again"


def test_the_directors_viewing_names_the_scenes_she_sees_and_the_one_she_does_not(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
    tmp_path,
    monkeypatch,
):
    ids = an_editorial_film(engine, voiceover=ENGLISH, with_source=True)
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not decoded: the encoder is faked")
    with Session(engine) as session, session.begin():
        session.execute(
            delete(StoryboardScene).where(StoryboardScene.storyboard_id == ids["board"])
        )
        for index in range(1, 4):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=f"Shot {index} of the telescope's story",
                    visual_type="GENERATED_IMAGE",
                    duration_seconds=6.0,
                    voiceover_segment=ENGLISH[:60],
                    created_at=utc_now(),
                )
            )
        asset = session.get(MediaAsset, ids["asset"])
        asset.uri_or_path = str(film)
        asset.duration_seconds = 18.0
    monkeypatch.setattr("app.agents.editorial.model_can_see", lambda _session, _agent: True)
    _encoder(monkeypatch, fails={1})
    approve = json.dumps(
        {"verdict": "APPROVE", "story": "A telescope finds water.", "reasons": [], "notes_for": {}}
    )
    registry, model = editorial_registry(staffed, lambda _prompt: approve)

    result = editorial_review(engine, registry, ids["asset"], language="en")

    assert result["frames_seen"] == 2
    prompt = model.calls[0]["prompt"]
    assert "(the middle of scenes 1, 3, in that order)" in prompt
    assert "no frame could be cut for scene 2, so you have not seen its picture" in prompt
    images = model.calls[0]["extra"]["images"]
    assert [_seen(image) for image in images] == ["frame at 3.00", "frame at 15.00"]


def test_the_film_look_judges_each_frame_as_its_own_scene_and_names_the_failed_cut(
    engine, tmp_path, monkeypatch
):
    workforce = staff(engine)
    ids = a_picture_film(engine)  # three scenes of 6 s, nobody in them
    film = tmp_path / "film.mp4"
    film.write_bytes(b"not decoded: the encoder is faked")
    with Session(engine) as session, session.begin():
        session.get(MediaAsset, ids["asset"]).uri_or_path = str(film)
    give_vision(engine, workforce["agents"]["VideoEditor"].id)
    _encoder(monkeypatch, fails={1})
    answer = json.dumps({"scenes": [scene_answer(1), scene_answer(3)], "characters": []})
    registry, model = registry_with(workforce, lambda _prompt: answer)

    result = evaluate_pictures(engine, registry, ids["asset"], str(uuid4()))

    picture = result["picture_qc"]
    by_scene = {entry["scene"]: entry for entry in picture["scenes"]}
    assert by_scene[1]["status"] == "MEASURED" and by_scene[3]["status"] == "MEASURED"
    assert by_scene[2]["status"] == "NOT_APPLICABLE"
    assert by_scene[2]["reason"] == "the frame of this scene could not be cut from the film"
    assert picture["frames"] == 2
    images = model.calls[0]["extra"]["images"]
    assert [_seen(image) for image in images] == ["frame at 3.00", "frame at 15.00"]
