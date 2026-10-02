"""Migration 0049_take_intent: a paid task is on the books before the studio waits for it.

Until 0049 the id of a task Runway had accepted (and would bill) lived only in memory: a poll
that ran out of time, a download that failed or a process killed between the purchase and its
row left no trace of the task, and the next run bought the scene again. 0049 adds what the
take needs to say "bought, not yet collected":

- ``scene_take.remote_task_id``, the vendor's task id, written the moment the vendor accepts;
- the statuses SUBMITTED (accepted, its output not collected yet: never bought again) and
  LOST (accepted and never collected before its output expired);
- the kind ``narration``, for the narration purchases the books record as takes.

Checked on temporary databases only; ``data/studio.db`` is never opened.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db import ROOT, create_db_engine, migrate
from app.media.models import SCENE_TAKE_KINDS, SCENE_TAKE_STATUSES, SceneTake
from sqlalchemy import inspect
from test_migrations_0048 import _insert_film_at_0047

PREVIOUS = "0048_production_sheet"
REVISION = "0049_take_intent"
MIGRATION = ROOT / "backend/migrations/versions/0049_take_intent.py"


def _downgrade(engine, revision: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert raw is not None
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                config.attributes["connection"] = connection
                command.downgrade(config, revision)
        finally:
            raw.execute("PRAGMA foreign_keys=ON")


def _db(tmp_path: Path, name: str = "studio.db"):
    path = tmp_path / name
    return path, create_db_engine(f"sqlite:///{path.as_posix()}")


def _raw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _take(connection: sqlite3.Connection, **overrides) -> None:
    row = {
        "id": "take-1",
        "storyboard_id": "sb-1",
        "scene_number": 1,
        "kind": "motion",
        "prompt_hash": "a" * 64,
        "model_id": "seedance2_5",
        "resolution": "1080:1920",
        "credits_quoted": 340.0,
        "status": "PAID",
        "sha256": "b" * 64,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-01T10:00:00Z",
    }
    row.update(overrides)
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO scene_take ({names}) VALUES ({marks})", list(row.values()))


def _shape(path: Path) -> dict[str, object]:
    """The table as SQLite describes it: columns, indexes (with their columns) and foreign
    keys. The stored CREATE text is not compared: a rebuilt table is renamed into place, and
    SQLite quotes the name it rewrites."""
    connection = _raw(path)
    try:
        indexes = {
            row[1]: [col[2] for col in connection.execute(f"PRAGMA index_info('{row[1]}')")]
            for row in connection.execute("PRAGMA index_list('scene_take')")
            if not str(row[1]).startswith("sqlite_autoindex")
        }
        uniques = sorted(
            tuple(col[2] for col in connection.execute(f"PRAGMA index_info('{row[1]}')"))
            for row in connection.execute("PRAGMA index_list('scene_take')")
            if row[2]
        )
        return {
            "columns": connection.execute("PRAGMA table_info('scene_take')").fetchall(),
            "indexes": indexes,
            "uniques": uniques,
            "foreign_keys": sorted(
                row[2:5] for row in connection.execute("PRAGMA foreign_key_list('scene_take')")
            ),
        }
    finally:
        connection.close()


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0049", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_revision_follows_the_production_sheet():
    module = _migration()
    assert (module.revision, module.down_revision) == (REVISION, PREVIOUS)


def test_upgrade_adds_the_task_id_and_the_new_statuses_and_kind(tmp_path):
    path, engine = _db(tmp_path)
    migrate(engine, REVISION)
    columns = {c["name"]: c for c in inspect(engine).get_columns("scene_take")}
    engine.dispose()
    assert "remote_task_id" in columns and columns["remote_task_id"]["nullable"] is True

    connection = _raw(path)
    try:
        for n, status in enumerate(("SUBMITTED", "LOST", "QUOTED", "PAID", "REFUSED"), start=1):
            _take(connection, id=f"take-{status}", status=status, sha256=str(n) * 64)
        _take(
            connection,
            id="take-intent",
            status="SUBMITTED",
            remote_task_id="task-1234",
            sha256=None,
        )
        _take(connection, id="take-voice", kind="narration", sha256="9" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-bad-status", status="ORDERED", sha256="c" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-bad-kind", kind="music", sha256="d" * 64)
        # The checks 0048 wrote are still there after the rebuild.
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-zero", scene_number=0, sha256="e" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-twice", sha256="1" * 64, status="SUBMITTED")
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('scene_take')")}
        assert "ix_scene_take_scene" in indexes
        assert "ix_scene_take_remote_task" in indexes
    finally:
        connection.close()


def test_existing_takes_survive_the_upgrade_and_the_downgrade_comes_back(tmp_path):
    fresh_path, fresh = _db(tmp_path, "fresh_0048.db")
    migrate(fresh, PREVIOUS)
    fresh.dispose()
    expected = _shape(fresh_path)

    path, engine = _db(tmp_path)
    migrate(engine, PREVIOUS)
    connection = _raw(path)
    # The film the take belongs to: `migrate` refuses a database left with orphans.
    _insert_film_at_0047(connection)
    _take(connection, id="take-old", status="APPROVED", approved_by="owner")
    connection.commit()
    connection.close()

    migrate(engine, REVISION)
    connection = _raw(path)
    try:
        assert connection.execute(
            "SELECT id, status, approved_by, remote_task_id FROM scene_take"
        ).fetchall() == [("take-old", "APPROVED", "owner", None)]
        # A take still in flight at the vendor and one the vendor never handed over: on the
        # way down both become what 0048 can say, REFUSED, with the reason kept.
        _take(connection, id="take-flight", status="SUBMITTED", remote_task_id="t-1", sha256=None)
        _take(connection, id="take-lost", status="LOST", remote_task_id="t-2", sha256="7" * 64)
        connection.commit()
    finally:
        connection.close()

    _downgrade(engine, PREVIOUS)
    engine.dispose()
    assert _shape(path) == expected
    connection = _raw(path)
    try:
        # 0048's checks are back: the new words are refused again.
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-new", status="SUBMITTED", sha256="8" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _take(connection, id="take-voice", kind="narration", sha256="6" * 64)
        rows = connection.execute(
            "SELECT id, status, failure_code FROM scene_take ORDER BY id"
        ).fetchall()
        assert rows == [
            ("take-flight", "REFUSED", "DOWNGRADE.SUBMITTED"),
            ("take-lost", "REFUSED", "DOWNGRADE.LOST"),
            ("take-old", "APPROVED", None),
        ]
    finally:
        connection.close()

    # And forward again.
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)
    engine.dispose()


def test_a_narration_take_blocks_the_downgrade_rather_than_vanishing(tmp_path):
    path, engine = _db(tmp_path)
    migrate(engine, REVISION)
    connection = _raw(path)
    _take(connection, id="take-voice", kind="narration")
    connection.commit()
    connection.close()
    with pytest.raises(Exception, match="narration"):
        _downgrade(engine, PREVIOUS)
    engine.dispose()


def test_the_model_and_the_migration_name_the_same_values():
    module = _migration()
    assert module.TAKE_KINDS == SCENE_TAKE_KINDS
    assert module.TAKE_STATUSES == SCENE_TAKE_STATUSES
    assert "SUBMITTED" in SCENE_TAKE_STATUSES and "LOST" in SCENE_TAKE_STATUSES
    assert "narration" in SCENE_TAKE_KINDS
    assert SceneTake.__table__.c.remote_task_id.nullable is True
