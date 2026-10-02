"""The archive a buyer receives holds the studio and nothing of this machine's (SELL-17)."""

from __future__ import annotations

import hashlib
import sys
import zipfile

import pytest
from app.config import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import make_release  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))


def test_the_allowlist_keeps_secrets_history_and_scratch_out():
    names = [
        "README.md",
        ".env",
        ".env.example",
        "backend/app/main.py",
        "backend/app/__pycache__/main.cpython-314.pyc",
        "backend/storage/media/film.mp4",
        "data/studio.db",
        "data/studio.credentials.key",
        "config/x.json",
        "scratch/verify_agent_model.mjs",
        "art-source/unreal/towers_day/day_pass.ps1",
        "Agents ID and Bible/Sarah.png",
        "AGENTS.md",
        "docs/project/CURRENT_STATUS.md",
        "docs/project/YOUTUBE_CONNECTIONS.md",
        "docs/OPERATOR_GUIDE.md",
        "scripts/start.py",
        "scripts/shot_page.mjs",
        "tests/test_foundation.py",
    ]
    chosen = make_release.select_files(names)
    assert chosen == [
        "README.md",
        ".env.example",
        "backend/app/main.py",
        "config/x.json",
        "docs/project/YOUTUBE_CONNECTIONS.md",
        "docs/OPERATOR_GUIDE.md",
        "scripts/start.py",
    ]
    assert "tests/test_foundation.py" in make_release.select_files(names, with_tests=True)


def test_a_file_that_names_this_machine_stops_the_build(tmp_path):
    root = tmp_path / "repo"
    for name in ("README.md", "THIRD_PARTY_NOTICES.md", "backend/app/main.py", ".env.example"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("ok\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "paths.json").write_text('{"x": "C:\\Users\\mario\\x"}', "utf-8")
    names = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    monkey = make_release.version
    try:
        make_release.version = lambda: "9.9.9"  # type: ignore[assignment]
        with pytest.raises(make_release.ReleaseRefused, match="config/paths.json:1"):
            make_release.build(tmp_path / "out", root=root, names=names)
        (root / "config" / "paths.json").write_text('{"x": "relative/x"}', "utf-8")
        archive = make_release.build(tmp_path / "out", root=root, names=names)
    finally:
        make_release.version = monkey  # type: ignore[assignment]
    assert archive.name == "amn-ai-9.9.9.zip"
    with zipfile.ZipFile(archive) as zipped:
        assert sorted(zipped.namelist()) == sorted(f"amn-ai-9.9.9/{n}" for n in names)
    digest = archive.with_suffix(".zip.sha256").read_text(encoding="utf-8").split()[0]
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_the_real_tree_builds_a_clean_archive(tmp_path):
    archive = make_release.build(tmp_path)
    with zipfile.ZipFile(archive) as zipped:
        names = [n.split("/", 1)[1] for n in zipped.namelist()]
    assert "README.md" in names and "THIRD_PARTY_NOTICES.md" in names
    assert "backend/app/media/models/LICENSE-YuNet" in names
    assert "frontend/public/THIRD_PARTY_NOTICES.txt" in names
    for name in names:
        assert not name.startswith(("scratch/", "art-source/", "data/", "docs/project/CURRENT"))
        assert not name.endswith((".credentials.key", ".db")), name
        assert name != ".env" and "__pycache__" not in name, name
