"""The media file routes serve only files inside the studio's media folders (SEC-06).

``GET /media/takes/{id}/file`` and ``GET /media/assets/{id}/stream`` used to serve whatever path
the database row held, following symlinks. The paths are written only by the pipeline today, so
this was not reachable; but one bad row (an import, a rehearsal that adopted a folder holding a
link, a migration) would have served any file the process can read, ``.env`` included, to
whoever holds the key. A path is now served only when it resolves inside the media storage root
(the page's ``media_storage_root`` or the default, rehearsals included) or the character
references folder, and is not itself a link; anything else answers 404.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from app.media.models import MediaAsset, SceneTake
from app.media.storage import media_file_inside, media_roots
from app.services import utc_now
from sqlalchemy.orm import Session
from test_production_policy import make_storyboard

PICTURE = b"\x89PNG\r\n\x1a\n" + b"picture" * 10


def _take(engine, storyboard_id: str, path: Path) -> str:
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=1,
                kind="still",
                prompt_hash=hashlib.sha256(take_id.encode()).hexdigest(),
                model_id="seedream5_pro",
                resolution="1530:2720",
                status="PAID",
                path=str(path),
                sha256=hashlib.sha256(PICTURE).hexdigest(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    return take_id


def _asset(engine, path: Path) -> str:
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(path),
                file_size_bytes=len(PICTURE),
                mime_type="video/mp4",
                provenance_hash=hashlib.sha256(PICTURE).hexdigest(),
                created_at=utc_now(),
            )
        )
    return asset_id


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PICTURE)
    return path


def _link(link: Path, target: Path) -> None:
    """A symbolic link, or on Windows without the privilege a directory junction."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except OSError:
        if sys.platform != "win32" or not target.is_dir():
            pytest.skip("this account may not create symbolic links")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def storage(client, private_media_storage):
    """The page's media root, as the studio's routes read it."""
    root = private_media_storage["DEFAULT_STORAGE_ROOT"]
    root.mkdir(parents=True, exist_ok=True)
    client.app.app.state.media_storage_root = root
    return root


def test_files_inside_the_media_folders_are_served(client, headers, engine, tmp_path, storage):
    storyboard_id = make_storyboard(engine, tmp_path)
    take_id = _take(engine, storyboard_id, _write(storage / storyboard_id / "stills" / "s1.png"))
    rehearsal = _write(storage / "rehearsals" / f"{storyboard_id}-x" / "legacy" / "film.mp4")
    asset_id = _asset(engine, rehearsal)
    taken = client.get(f"/api/v1/media/takes/{take_id}/file", headers=headers)
    assert taken.status_code == 200 and taken.content == PICTURE
    streamed = client.get(f"/api/v1/media/assets/{asset_id}/stream", headers=headers)
    assert streamed.status_code == 200 and streamed.content == PICTURE


def test_a_reference_portrait_in_its_own_folder_is_served(
    client, headers, engine, private_media_storage
):
    portrait = _write(private_media_storage["REFERENCE_STORAGE_ROOT"] / "c1" / "front.png")
    asset_id = _asset(engine, portrait)
    streamed = client.get(f"/api/v1/media/assets/{asset_id}/stream", headers=headers)
    assert streamed.status_code == 200 and streamed.content == PICTURE


def test_a_path_outside_the_media_folders_is_not_served(client, headers, engine, tmp_path, storage):
    storyboard_id = make_storyboard(engine, tmp_path)
    outside = _write(tmp_path / "outside" / "secret.env")
    take_id = _take(engine, storyboard_id, outside)
    asset_id = _asset(engine, outside)
    climbing = _take(engine, storyboard_id, storage / ".." / "outside-too.txt")
    _write(storage.parent / "outside-too.txt")
    for url in (
        f"/api/v1/media/takes/{take_id}/file",
        f"/api/v1/media/assets/{asset_id}/stream",
        f"/api/v1/media/takes/{climbing}/file",
    ):
        answer = client.get(url, headers=headers)
        assert answer.status_code == 404, (url, answer.status_code)
        assert PICTURE not in answer.content


def test_a_link_inside_storage_pointing_outside_is_not_served(
    client, headers, engine, tmp_path, storage
):
    storyboard_id = make_storyboard(engine, tmp_path)
    outside = _write(tmp_path / "elsewhere" / "secret.png")
    _link(storage / storyboard_id / "linked", outside.parent)
    through_folder = storage / storyboard_id / "linked" / "secret.png"
    assert through_folder.is_file()
    take_id = _take(engine, storyboard_id, through_folder)
    asset_id = _asset(engine, through_folder)
    assert client.get(f"/api/v1/media/takes/{take_id}/file", headers=headers).status_code == 404
    assert client.get(f"/api/v1/media/assets/{asset_id}/stream", headers=headers).status_code == 404


def test_a_file_link_is_refused_even_when_it_points_inside(tmp_path):
    root = tmp_path / "media"
    real = _write(root / "a.png")
    link = root / "b.png"
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("this account may not create file symbolic links")
    assert media_file_inside(real, [root]) == real.resolve()
    assert media_file_inside(link, [root]) is None


def test_the_helper_on_its_own(tmp_path):
    root = tmp_path / "media"
    inside = _write(root / "x" / "a.png")
    assert media_file_inside(inside, [root]) == inside.resolve()
    assert media_file_inside(root / "x" / "missing.png", [root]) is None
    assert media_file_inside(root / "x", [root]) is None, "a folder is not a file"
    assert media_file_inside(_write(tmp_path / "b.png"), [root]) is None
    assert media_file_inside(None, [root]) is None
    assert media_file_inside("", [root]) is None
    assert media_file_inside(inside, []) is None


def test_the_roots_are_the_page_root_the_default_and_the_references(private_media_storage):
    from types import SimpleNamespace

    roots = media_roots(SimpleNamespace(media_storage_root=Path("E:/x/media")))
    assert Path("E:/x/media") in roots
    assert private_media_storage["DEFAULT_STORAGE_ROOT"] in roots
    assert private_media_storage["REFERENCE_STORAGE_ROOT"] in roots
    assert media_roots(SimpleNamespace()) == [
        private_media_storage["DEFAULT_STORAGE_ROOT"],
        private_media_storage["REFERENCE_STORAGE_ROOT"],
    ]
