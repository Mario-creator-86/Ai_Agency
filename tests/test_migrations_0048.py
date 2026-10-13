"""Offline regression tests for test migrations 0048.

Providers are faked; all data is synthetic."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.db import ROOT, create_db_engine, migrate
from app.media.models import SceneTake, StoryboardScene
from app.models import OwnerPolicy
from app.services import bootstrap_studio
from sqlalchemy import inspect

PREVIOUS = "0047_replay_reads"
LIVE_DB = ROOT / "data" / "studio.db"


def _head() -> str:
    """The chain's head, read from the migrations (0049 and later build on this one)."""
    from app.main import expected_revision

    return expected_revision()


def _downgrade(engine, revision: str) -> None:
    """The same recipe as `app.db.migrate`, walked downwards, foreign keys suspended."""
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


def _raw(path: Path) -> sqlite3.Connection:
    # Plain sqlite3 with foreign keys off (its default): these tests are about the columns and
    # checks the migration writes, not about building a whole film's chain of parent rows.
    return sqlite3.connect(path)


def _db(tmp_path: Path, name: str = "studio.db") -> tuple[Path, object]:
    path = tmp_path / name
    return path, create_db_engine(f"sqlite:///{path.as_posix()}")


def _take(**overrides) -> dict:
    row = {
        "id": "take-1",
        "storyboard_id": "sb-1",
        "scene_number": 1,
        "kind": "still",
        "prompt_hash": "a" * 64,
        "model_id": "seedream5_pro",
        "resolution": "1530:2720",
        "seconds": None,
        "seed": None,
        "credits_quoted": 9.0,
        "credits_measured": None,
        "status": "QUOTED",
        "failure_code": None,
        "failure_detail": None,
        "path": None,
        "sha256": "b" * 64,
        "approved_by": None,
        "created_at": "2026-09-26T10:00:00Z",
        "updated_at": "2026-09-26T10:00:00Z",
    }
    row.update(overrides)
    return row


def _insert_take(connection: sqlite3.Connection, **overrides) -> None:
    row = _take(**overrides)
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO scene_take ({names}) VALUES ({marks})", list(row.values()))


def _insert_film_at_0047(connection: sqlite3.Connection) -> None:
    """The parent chain a scene stands on: topic -> script -> storyboard 'sb-1'.

    `app.db.migrate` checks every foreign key after it upgrades and refuses a database that
    has orphans, so the existing scenes must belong to a real film for the upgrade to run.
    """
    connection.execute(
        "INSERT INTO topic_idea (id, title, topic, angle, target_audience, novelty_score,"
        " status, created_at) VALUES ('topic-1', 'Nepal', 'climate', 'the bill', 'general',"
        " 0.5, 'SELECTED', '2026-09-26T10:00:00Z')"
    )
    connection.execute(
        "INSERT INTO script_draft (id, topic_id, version, title, target_duration_seconds,"
        " voiceover_full_text, scenes_json, status, claim_ids_json, unverified_claim_ids_json,"
        " created_at) VALUES ('script-1', 'topic-1', 1, 'Nepal', 30, 'Nepal.', '[]',"
        " 'APPROVED', '[]', '[]', '2026-09-26T10:00:00Z')"
    )
    connection.execute(
        "INSERT INTO storyboard (id, script_draft_id, title, visual_style, aspect_ratio,"
        " target_duration_seconds, status, total_scenes, created_at) VALUES ('sb-1',"
        " 'script-1', 'Nepal', 'MOTION_GRAPHIC', '9:16', 30, 'APPROVED', 3,"
        " '2026-09-26T10:00:00Z')"
    )


def _insert_scene_at_0047(connection: sqlite3.Connection, scene_id: str, index: int) -> None:
    connection.execute(
        "INSERT INTO storyboard_scene (id, storyboard_id, scene_index, visual_prompt,"
        " visual_type, duration_seconds, voiceover_segment, shot_type, transition_in,"
        " character_ids_json, claim_ids_json, created_at, production_overrides_json,"
        " prompt_json, story_purpose) VALUES (?, 'sb-1', ?, 'A valley under cloud',"
        " 'MOTION_GRAPHIC', 5.0, 'Nepal', 'MEDIUM', 'CUT', '[]', '[]',"
        " '2026-09-26T10:00:00Z', '{}', NULL, 'HOOK')",
        (scene_id, index),
    )


def _schema(path: Path, tables: tuple[str, ...]) -> dict[str, str | None]:
    connection = _raw(path)
    try:
        found = {
            name: sql
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index')"
            )
        }
    finally:
        connection.close()
    return {table: found.get(table) for table in tables}


# --- the scene_take table ------------------------------------------------------------------


def test_upgrade_on_an_empty_db_creates_scene_take_with_a_status_check(tmp_path):
    path, engine = _db(tmp_path)
    migrate(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("scene_take")}
    engine.dispose()
    assert {
        "storyboard_id",
        "scene_number",
        "kind",
        "prompt_hash",
        "model_id",
        "resolution",
        "seconds",
        "seed",
        "credits_quoted",
        "credits_measured",
        "status",
        "failure_code",
        "failure_detail",
        "path",
        "sha256",
        "approved_by",
    } <= columns

    connection = _raw(path)
    try:
        for status in ("QUOTED", "PAID", "APPROVED", "REJECTED", "REFUSED"):
            _insert_take(connection, id=f"take-{status}", status=status, sha256=status * 3)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_take(connection, id="take-bought", status="BOUGHT", sha256="c" * 64)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_take(connection, id="take-card", kind="card", sha256="d" * 64)
        for kind in ("motion", "test_shot"):
            _insert_take(connection, id=f"take-{kind}", kind=kind, sha256="e" * 64)
    finally:
        connection.close()


def test_one_file_of_one_prompt_for_one_scene_is_recorded_once(tmp_path):
    path, engine = _db(tmp_path)
    migrate(engine)
    engine.dispose()
    connection = _raw(path)
    try:
        _insert_take(connection, id="take-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_take(connection, id="take-2")
        # The second candidate of the same prompt is a different file: a different row.
        _insert_take(connection, id="take-3", sha256="f" * 64)
        # The same file adopted for a different scene or kind is a different take.
        _insert_take(connection, id="take-4", scene_number=2)
        _insert_take(connection, id="take-5", kind="motion")
    finally:
        connection.close()


def test_the_model_declares_what_the_migration_builds():
    table = SceneTake.__table__
    uniques = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("storyboard_id", "scene_number", "kind", "prompt_hash", "sha256") in uniques
    assert StoryboardScene.__table__.c.scene_kind.nullable is False
    assert StoryboardScene.__table__.c.card_json.nullable is True
    assert OwnerPolicy.__table__.c.paid_media_approval.nullable is False


def test_the_value_sets_the_code_uses_are_the_ones_the_database_checks():
    # A migration is frozen history and imports nothing from the app; the app's constants are
    # what later code reads. They must name the same values, or a valid-looking write fails.
    import importlib.util

    import app.media.models as media_models
    import app.models as core_models

    def load(name: str):
        spec = importlib.util.spec_from_file_location(
            name, ROOT / f"backend/migrations/versions/{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    migration = load("0048_production_sheet")
    assert migration.SCENE_KINDS == media_models.SCENE_KINDS
    # 0049 widened the take's kinds and statuses; it names 0048's sets as the ones it
    # rebuilds from, and its own as the model's.
    widened = load("0049_take_intent")
    assert migration.TAKE_KINDS == widened.OLD_TAKE_KINDS
    assert migration.TAKE_STATUSES == widened.OLD_TAKE_STATUSES
    assert widened.TAKE_KINDS == media_models.SCENE_TAKE_KINDS
    assert widened.TAKE_STATUSES == media_models.SCENE_TAKE_STATUSES
    assert migration.PAID_MEDIA_APPROVALS == core_models.PAID_MEDIA_APPROVALS
    assert core_models.PAID_MEDIA_APPROVALS[0] == "EVERY_PAID_STEP"
    assert StoryboardScene.__table__.c.scene_kind.server_default.arg == "LIVE"


# --- the Owner's rule for paid media ---------------------------------------------------------


def test_paid_media_approval_defaults_to_every_paid_step_with_a_check(tmp_path, settings):
    path, engine = _db(tmp_path, "policy.db")
    migrate(engine)
    bootstrap_studio(engine, settings)
    engine.dispose()
    connection = _raw(path)
    try:
        row = connection.execute(
            "SELECT paid_media_approval, paid_media_approval_over_usd FROM owner_policy"
        ).fetchone()
        assert row == ("EVERY_PAID_STEP", None)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE owner_policy SET paid_media_approval = 'NEVER_ASK'")
        # OVER_USD needs its threshold, and only OVER_USD may carry one.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE owner_policy SET paid_media_approval = 'OVER_USD'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE owner_policy SET paid_media_approval_over_usd = 5.0")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE owner_policy SET paid_media_approval = 'OVER_USD',"
                " paid_media_approval_over_usd = -1.0"
            )
        connection.execute(
            "UPDATE owner_policy SET paid_media_approval = 'OVER_USD',"
            " paid_media_approval_over_usd = 5.0"
        )
        connection.execute(
            "UPDATE owner_policy SET paid_media_approval = 'MODE',"
            " paid_media_approval_over_usd = NULL"
        )
        # The table's own older checks survived the new column.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE owner_policy SET id = 2")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE owner_policy SET version = 0")
    finally:
        connection.close()


# --- existing scenes, and the way back ------------------------------------------------------


def test_existing_scenes_become_live_and_the_downgrade_reverses_cleanly(tmp_path):
    tables = ("storyboard_scene", "owner_policy", "scene_take")
    fresh_path, fresh = _db(tmp_path, "fresh_0047.db")
    migrate(fresh, PREVIOUS)
    fresh.dispose()
    expected = _schema(fresh_path, tables)
    assert expected["scene_take"] is None

    path, engine = _db(tmp_path)
    migrate(engine, PREVIOUS)
    connection = _raw(path)
    _insert_film_at_0047(connection)
    for index in range(1, 4):
        _insert_scene_at_0047(connection, f"scene-{index}", index)
    connection.commit()
    connection.close()

    migrate(engine)
    connection = _raw(path)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            _head(),
        )
        rows = connection.execute(
            "SELECT id, scene_kind, card_json FROM storyboard_scene ORDER BY scene_index"
        ).fetchall()
        assert rows == [(f"scene-{i}", "LIVE", None) for i in range(1, 4)]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE storyboard_scene SET scene_kind = 'CHART'")
        for kind in ("DATA_CARD", "TITLE_CARD", "BLACK", "LIVE"):
            connection.execute(
                "UPDATE storyboard_scene SET scene_kind = ? WHERE id = 'scene-1'", (kind,)
            )
        connection.commit()
    finally:
        connection.close()

    _downgrade(engine, PREVIOUS)
    engine.dispose()
    assert _schema(path, tables) == expected
    connection = _raw(path)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            PREVIOUS,
        )
        assert connection.execute("SELECT COUNT(*) FROM storyboard_scene").fetchone() == (3,)
    finally:
        connection.close()

    # And forward again: the round trip leaves nothing behind that blocks the next upgrade.
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)
    engine.dispose()


def test_the_application_starts_on_the_new_head(tmp_path, settings):
    """The app refuses any revision but its own head; the chain through 0048 reaches it."""
    from app.main import create_app
    from fastapi.testclient import TestClient

    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    engine.dispose()
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200


# --- only temporary databases -----------------------------------------------------------------


def _stamp(path: Path) -> tuple[int, int] | None:
    # A stat reads the directory entry; it never opens the database.
    if not path.exists():
        return None
    status = path.stat()
    return status.st_size, status.st_mtime_ns


def test_the_migration_runs_on_a_temporary_copy_and_never_on_the_studio(tmp_path, settings):
    before = _stamp(LIVE_DB)
    assert (
        Path(settings.database_url.removeprefix("sqlite:///"))
        .resolve()
        .is_relative_to(tmp_path.resolve())
    )
    path, engine = _db(tmp_path, "throwaway.db")
    migrate(engine)
    _downgrade(engine, PREVIOUS)
    engine.dispose()
    assert path.resolve() != LIVE_DB.resolve()
    assert _stamp(LIVE_DB) == before


COPY = os.environ.get("STUDIO_MIGRATION_COPY_DB")


@pytest.mark.skipif(
    not COPY, reason="opt-in: set STUDIO_MIGRATION_COPY_DB to a COPY of data/studio.db"
)
def test_a_copy_of_the_owners_database_upgrades_and_comes_back(tmp_path):
    source = Path(str(COPY)).resolve()
    assert source != LIVE_DB.resolve(), "name a copy, never data/studio.db itself"
    path = tmp_path / "copy.db"
    # Copied again, so even the named copy is never changed.
    shutil.copyfile(source, path)
    before = _raw(path)
    scenes = before.execute("SELECT COUNT(*) FROM storyboard_scene").fetchone()[0]
    before.close()

    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)
    connection = _raw(path)
    try:
        kinds = connection.execute(
            "SELECT scene_kind, COUNT(*) FROM storyboard_scene GROUP BY scene_kind"
        ).fetchall()
        assert kinds == ([("LIVE", scenes)] if scenes else [])
        assert connection.execute("SELECT paid_media_approval FROM owner_policy").fetchall() == [
            ("EVERY_PAID_STEP",)
        ]
        assert connection.execute("SELECT COUNT(*) FROM scene_take").fetchone() == (0,)
    finally:
        connection.close()
    _downgrade(engine, PREVIOUS)
    engine.dispose()
