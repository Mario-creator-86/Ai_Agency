"""PAGE-01: the page says when it is older than the studio's own sources.

On 2026-10-01 the studio served a bundle built on 2026-09-27, before the shooting sheet and the
paid-media switch existed, and nothing on the page said so: the render button answered 409
«Folosește foaia de filmare» to a page that had no sheet to open. The launcher now records the
hash of the sources it built from (``dist/build.json``), and the snapshot compares it with the
sources on disk.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from app.page_build import BUILD_RECORD, page_build, source_hash, write_build_record


def a_page(root: Path) -> Path:
    frontend = root / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>x</title>\n", encoding="utf-8")
    (frontend / "src" / "main.js").write_text("console.log('one');\n", encoding="utf-8")
    (frontend / "dist").mkdir()
    (frontend / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return frontend


def test_the_hash_covers_the_sources_and_the_entry_page_and_ignores_line_endings(tmp_path):
    frontend = a_page(tmp_path)
    first = source_hash(frontend)
    assert len(first) == 64
    (frontend / "src" / "main.js").write_bytes(b"console.log('one');\r\n")
    assert source_hash(frontend) == first, "a CRLF checkout is the same source"
    (frontend / "src" / "main.js").write_text("console.log('two');\n", encoding="utf-8")
    assert source_hash(frontend) != first
    second = source_hash(frontend)
    (frontend / "index.html").write_text("<!doctype html><title>y</title>\n", encoding="utf-8")
    assert source_hash(frontend) != second
    # what is not a source does not count
    third = source_hash(frontend)
    (frontend / "dist" / "extra.js").write_text("x", encoding="utf-8")
    assert source_hash(frontend) == third


def test_a_dist_built_from_other_sources_is_stale(tmp_path):
    frontend = a_page(tmp_path)
    write_build_record(frontend, "0" * 64)
    record = json.loads((frontend / "dist" / BUILD_RECORD).read_text(encoding="utf-8"))
    assert record["source_sha256"] == "0" * 64
    state = page_build(frontend)
    assert state == {
        "built": "0" * 64,
        "source": source_hash(frontend),
        "stale": True,
        "basis": "hash",
    }


def test_a_dist_built_from_these_sources_is_current(tmp_path):
    frontend = a_page(tmp_path)
    write_build_record(frontend, source_hash(frontend))
    assert page_build(frontend)["stale"] is False


def test_a_dist_without_a_record_falls_back_to_the_file_times(tmp_path):
    frontend = a_page(tmp_path)
    built = frontend / "dist" / "index.html"
    old = time.time() - 3600
    os.utime(built, (old, old))
    state = page_build(frontend)
    assert state["built"] is None and state["basis"] == "mtime"
    assert state["stale"] is True, "a source newer than the bundle"
    os.utime(built, None)
    assert page_build(frontend)["stale"] is False


def test_no_dist_at_all_is_not_a_banner(tmp_path):
    frontend = a_page(tmp_path)
    (frontend / "dist" / "index.html").unlink()
    (frontend / "dist").rmdir()
    assert page_build(frontend) == {
        "built": None,
        "source": source_hash(frontend),
        "stale": False,
        "basis": "none",
    }


def test_the_snapshot_says_whether_the_page_is_stale(client, headers, tmp_path):
    frontend = a_page(tmp_path)
    write_build_record(frontend, "f" * 64)
    client.app.app.state.page_root = frontend
    snapshot = client.get("/api/v1/snapshot", headers=headers).json()
    assert snapshot["page_build"]["stale"] is True
    assert snapshot["page_build"]["built"] == "f" * 64
    write_build_record(frontend, source_hash(frontend))
    assert client.get("/api/v1/snapshot", headers=headers).json()["page_build"]["stale"] is False


def test_the_launcher_records_the_hash_it_built_from(tmp_path, monkeypatch):
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "start_for_page_build", root / "scripts" / "start.py"
    )
    assert spec and spec.loader
    start = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "start_for_page_build", start)
    spec.loader.exec_module(start)
    frontend = a_page(tmp_path)
    monkeypatch.setattr(start, "FRONTEND", frontend)

    built: list[list[str]] = []

    def fake_run(command, *, cwd, step):  # noqa: ARG001 - the launcher's own signature
        built.append(command)
        # the build itself rewrites dist; the record is written after it
        (frontend / "dist" / "index.html").write_text("<!doctype html> new", encoding="utf-8")

    monkeypatch.setattr(start, "run", fake_run)
    start.build_frontend("npm")
    assert built == [["npm", "run", "build"]]
    assert page_build(frontend) == {
        "built": source_hash(frontend),
        "source": source_hash(frontend),
        "stale": False,
        "basis": "hash",
    }


@pytest.mark.parametrize("missing", ["src", "index.html"])
def test_a_tree_missing_its_sources_still_answers(tmp_path, missing):
    frontend = a_page(tmp_path)
    target = frontend / missing
    if target.is_dir():
        for child in target.iterdir():
            child.unlink()
        target.rmdir()
    else:
        target.unlink()
    assert len(source_hash(frontend)) == 64
