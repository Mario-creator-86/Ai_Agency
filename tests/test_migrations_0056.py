"""Migration 0056_gpu_sessions: the GPU session table, the batch columns of the RunPod journal,
and the journal's base64 pictures replaced by their fingerprint.

Until 0056 a RunPod request kept every reference picture as a ``data:`` URI inside the journal's
``request`` JSON (rows of 6.7 MB). 0056 replaces each by {"sha256", "bytes", "mime"}; the
picture itself was never the journal's to keep. Checked on temporary databases only;
``data/studio.db`` is never opened.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.db import ROOT, create_db_engine, migrate
from sqlalchemy import inspect

PREVIOUS = "0055_cloud_generation_jobs"
REVISION = "0056_gpu_sessions"

PICTURE = b"\x89PNG\r\n\x1a\n" + b"x" * 300_000
SOURCE = b"\xff\xd8\xff" + b"y" * 1000


def _uri(content: bytes, mime: str) -> str:
    return "data:" + mime + ";base64," + base64.b64encode(content).decode()


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


def _job(connection: sqlite3.Connection, identifier: str, request: dict) -> None:
    row = {
        "id": identifier,
        "idempotency_key": identifier.ljust(64, "0"),
        "payload_hash": "c" * 64,
        "integration_id": None,
        "provider": "RUNPOD",
        "target": "t" * 64,
        "project_id": "film-1",
        "scene_id": "1",
        "attempt": 1,
        "operation": "image",
        "model": "Qwen-Image-2512",
        "gpu": "RTX_PRO_6000",
        "hourly_rate": "4.00",
        "status": "COMPLETED",
        "request": json.dumps(request),
        "output": "{}",
        "created_at": "2026-10-07T10:00:00+00:00",
        "poll_count": 0,
    }
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO cloud_generation_job ({names}) VALUES ({marks})", list(row.values())
    )


def _requests(path: Path) -> dict[str, dict]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]: json.loads(row[1])
            for row in connection.execute("SELECT id, request FROM cloud_generation_job")
        }


def test_0056_adds_the_session_table_the_batch_columns_and_drops_the_pictures(tmp_path):
    path = tmp_path / "studio.db"
    engine = create_db_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine, PREVIOUS)
    fat = {
        "project_id": "film-1",
        "prompt": "a hut",
        "reference_images": [_uri(PICTURE, "image/png"), "https://cdn.example/ref.png"],
        "source_image": _uri(SOURCE, "image/jpeg"),
    }
    with sqlite3.connect(path) as connection:
        _job(connection, "fat", fat)
        _job(connection, "thin", {"project_id": "film-1", "prompt": "plain"})
    migrate(engine)

    requests = _requests(path)
    assert requests["thin"] == {"project_id": "film-1", "prompt": "plain"}
    slim = requests["fat"]
    assert slim["reference_images"][0] == {
        "sha256": hashlib.sha256(PICTURE).hexdigest(),
        "bytes": len(PICTURE),
        "mime": "image/png",
    }
    assert slim["reference_images"][1] == "https://cdn.example/ref.png"
    assert slim["source_image"] == {
        "sha256": hashlib.sha256(SOURCE).hexdigest(),
        "bytes": len(SOURCE),
        "mime": "image/jpeg",
    }
    assert slim["prompt"] == "a hut"
    assert len(json.dumps(slim)) < 1000

    shape = inspect(engine)
    columns = {c["name"] for c in shape.get_columns("cloud_generation_job")}
    assert {
        "batch_remote_id",
        "batch_index",
        "request_digest",
        "gpu_session_id",
        "billed_seconds_value",
    } <= columns
    indexes = {i["name"] for i in shape.get_indexes("cloud_generation_job")}
    assert "ix_cloud_generation_job_batch_remote_id" in indexes
    session_columns = {c["name"] for c in shape.get_columns("gpu_session")}
    assert {
        "id",
        "integration_id",
        "endpoint_id",
        "purpose",
        "step",
        "storyboard_id",
        "correlation_id",
        "process_token",
        "status",
        "workers_max",
        "opened_at",
        "renewed_at",
        "expires_at",
        "closed_at",
        "close_reason",
        "verified_off",
        "off_reading",
        "remote_job_ids",
        "error_code",
    } == session_columns
    assert "ix_gpu_session_endpoint_status" in {i["name"] for i in shape.get_indexes("gpu_session")}

    # A status outside the list is refused by the database itself.
    with sqlite3.connect(path) as connection:
        try:
            connection.execute(
                "INSERT INTO gpu_session (id, integration_id, endpoint_id, purpose, step, "
                "correlation_id, process_token, status, workers_max, opened_at, renewed_at, "
                "expires_at, remote_job_ids) VALUES ('s', 'i', 'e', 'image', 'stills', 'c', "
                "'p', 'RUNNING', 1, 'a', 'a', 'a', '[]')"
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("an unknown session status was accepted")

    # Running the data step again changes nothing.
    migrate(engine)
    assert _requests(path)["fat"] == slim

    _downgrade(engine, PREVIOUS)
    shape = inspect(engine)
    assert "gpu_session" not in shape.get_table_names()
    columns = {c["name"] for c in shape.get_columns("cloud_generation_job")}
    assert "batch_remote_id" not in columns and "gpu_session_id" not in columns
    # The pictures are not restored: the downgrade says so; the fingerprints stay.
    assert _requests(path)["fat"] == slim
    engine.dispose()
