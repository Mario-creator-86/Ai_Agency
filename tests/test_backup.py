"""Backups, the restore guard, the copy before a migration, and the tables that only grow.

Measured 2026-10-01 (REL-04, AR-08, SELL-20, REL-15): no backup code existed outside
scripts/reset_history.py, `bootstrap.py` migrated the studio's database in place on every
start, and the live copy held 601 completed watchdog tasks from two weeks and 2,850 published
outbox rows that nothing ever removed.

Every database here is a tmp one (the suite's own `engine`, or one made in tmp_path), every
backup folder is under tmp_path, and nothing touches data/ or backend/storage/. No provider
is asked anything: a backup is SQLite's own online copy and a few files.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import secrets
import socket
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app import backup
from app.config import ROOT, Settings
from app.db import create_db_engine, migrate
from app.main import expected_revision
from app.models import DomainEvent, OwnerPolicy
from app.services import append_event, bootstrap_studio
from app.workflows.models import OutboxRecord, ScheduledJob, TaskQueueItem
from app.workflows.services import append_event_with_outbox, ensure_scheduled_job
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 2, 3, 30, tzinfo=UTC)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"script_{name}", ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"script_{name}"] = module
    spec.loader.exec_module(module)
    return module


def database_of(engine) -> Path:
    return Path(str(engine.url.database))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    """A loopback port nobody answers on: bound once to learn it, then let go."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def count(engine, model) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


# ------------------------------------------------------------------ the online backup


def test_an_online_backup_of_a_live_wal_database_is_whole_and_matches_its_manifest(
    engine, tmp_path
):
    database = database_of(engine)
    key = database.with_suffix(".credentials.key")
    key.write_bytes(b"wrapped-for-this-windows-user")  # a stand-in: never a real key
    with Session(engine) as session, session.begin():
        for n in range(40):
            append_event(session, "test.written", "test", str(n), 1, {"n": n}, "live")
    # The writes sit in the WAL (nothing checkpointed them) and a reader holds a snapshot open
    # while the copy is taken: the studio is running.
    reader = engine.connect()
    snapshot = reader.begin()
    reader.execute(text("SELECT COUNT(*) FROM domain_event")).scalar()
    assert database.with_name(database.name + "-wal").is_file()
    try:
        made = backup.make_backup(database, tmp_path / "backups", now=NOW)
    finally:
        snapshot.rollback()
        reader.close()

    copy = Path(made["path"])
    assert copy.parent == tmp_path / "backups" and copy.name == "studio-20261002T033000Z.db"
    assert made["sha256"] == sha(copy)
    assert made["integrity"] == "ok"
    assert made["revision"] == expected_revision()
    on_disk = json.loads(Path(made["manifest_path"]).read_text(encoding="utf-8"))
    assert on_disk["sha256"] == sha(copy) and on_disk["bytes"] == copy.stat().st_size
    with closing(sqlite3.connect(copy)) as check:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        copied = check.execute(
            "SELECT COUNT(*) FROM domain_event WHERE event_type = 'test.written'"
        ).fetchone()[0]
    assert copied == 40, "the rows still in the WAL are not in the copy"
    # The wrapped credentials key is kept apart, and the manifest says it only opens for the
    # Windows account that made it.
    kept_key = Path(made["key"]["path"])
    assert kept_key.parent == tmp_path / "backups" / "key"
    assert kept_key.read_bytes() == key.read_bytes()
    assert made["key"]["user_bound"] is True and "Windows" in made["key"]["note_ro"]
    assert backup.verify_backup(copy)["ok"] is True


def test_a_copy_changed_after_it_was_made_fails_its_verification(engine, tmp_path):
    made = backup.make_backup(database_of(engine), tmp_path / "backups", now=NOW)
    copy = Path(made["path"])
    with closing(sqlite3.connect(copy)) as tamper:
        tamper.execute("UPDATE studio SET name = 'altul'")
        tamper.commit()
    verdict = backup.verify_backup(copy)
    assert verdict["ok"] is False and "sha256" in verdict["reason_ro"]


def test_retention_keeps_fourteen_days_and_four_older_weeks(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    days = [NOW - timedelta(days=n) for n in range(60)]
    for moment in days:
        stem = f"studio-{moment:%Y%m%dT%H%M%SZ}"
        (folder / f"{stem}.db").write_bytes(b"x")
        (folder / f"{stem}.json").write_text("{}", encoding="utf-8")
    # A second backup on the newest day (the Owner's own, by hand): only the newest of a day
    # is a daily one.
    earlier = f"studio-{NOW - timedelta(hours=2):%Y%m%dT%H%M%SZ}"
    (folder / f"{earlier}.db").write_bytes(b"x")
    (folder / f"{earlier}.json").write_text("{}", encoding="utf-8")
    # Before-migration copies are kept apart: the newest five.
    for n in range(7):
        stem = f"studio-{NOW - timedelta(days=n, hours=5):%Y%m%dT%H%M%SZ}-premigrare"
        (folder / f"{stem}.db").write_bytes(b"x")
        (folder / f"{stem}.json").write_text("{}", encoding="utf-8")
    # A copy this code did not make (no manifest: scripts/reset_history.py's) is never touched.
    legacy = folder / "studio-20250101T000000Z.db"
    legacy.write_bytes(b"x")

    deleted = backup.apply_retention(folder, keep_daily=14, keep_weekly=4, now=NOW)

    assert legacy.is_file() and legacy.name not in deleted
    legacy.unlink()
    kept = sorted(p.name for p in folder.glob("studio-*.db") if "premigrare" not in p.name)
    kept_days = [datetime.strptime(name[7:23], "%Y%m%dT%H%M%SZ") for name in kept]
    assert len(kept) == 18, kept
    newest = sorted(kept_days)[-14:]
    assert [d.date() for d in newest] == sorted(m.date() for m in days[:14])
    older = sorted(kept_days)[:-14]
    weeks = [d.isocalendar()[:2] for d in older]
    assert len(set(weeks)) == 4, "one per week, four weeks"
    for day in older:  # each the newest of its week among what was there
        same_week = [m for m in days[14:] if m.isocalendar()[:2] == day.isocalendar()[:2]]
        assert day.date() == max(same_week).date()
    assert len(list(folder.glob("studio-*-premigrare.db"))) == 5
    # The day's earlier copy (01:30) is not the newest of its day: it goes.
    assert f"studio-{NOW - timedelta(hours=2):%Y%m%dT%H%M%SZ}.db" in deleted
    # A deleted copy takes its manifest with it.
    assert all(not (folder / f"{Path(name).stem}.json").exists() for name in deleted)
    assert len(list(folder.glob("*.json"))) == len(kept) + 5


# ------------------------------------------------------------ before a migration


def test_bootstrap_backs_up_an_older_database_before_it_migrates_it(tmp_path):
    database = tmp_path / "older.db"
    settings = Settings(
        _env_file=None,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{database.as_posix()}",
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
    )
    engine = create_db_engine(settings.database_url)
    migrate(engine, "0050_film_purchase_lease")
    bootstrap_studio(engine, settings)
    engine.dispose()

    bootstrap = load_script("bootstrap")
    made = bootstrap.prepare_database(settings)

    assert made is not None and made["tag"] == "premigrare"
    assert made["revision"] == "0050_film_purchase_lease"
    copy = Path(made["path"])
    assert copy.parent == tmp_path / "backups"
    with closing(sqlite3.connect(copy)) as old:
        assert old.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            "0050_film_purchase_lease"
        )
    with closing(sqlite3.connect(database)) as now:
        assert now.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            expected_revision()
        )
    # At the head there is nothing to protect from a migration: no second copy.
    assert bootstrap.prepare_database(settings) is None
    assert len(list((tmp_path / "backups").glob("studio-*.db"))) == 1


def test_a_new_database_is_not_backed_up_before_its_first_migration(tmp_path):
    database = tmp_path / "fresh.db"
    assert backup.backup_before_migration(database, tmp_path / "backups", "0051") is None
    engine = create_db_engine(f"sqlite:///{database.as_posix()}")
    engine.dispose()  # an empty file: no schema, no studio
    assert backup.backup_before_migration(database, tmp_path / "backups", "0051") is None
    assert not (tmp_path / "backups").exists()


# ----------------------------------------------------------------------- the restore


def _studio_running_free(engine) -> None:
    """The studio as the Owner runs it: the stop lifted, PRODUCTION, the day's clock on."""
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE owner_policy SET autonomy_stopped = 0, environment = 'PRODUCTION'")
        )
    ensure_scheduled_job(
        engine, name="daily_main", workflow_type="DAILY_RUN", interval_seconds=86400, active=True
    )


def test_a_restore_is_refused_while_the_studio_answers_on_its_port(engine, tmp_path):
    database = database_of(engine)
    made = backup.make_backup(database, tmp_path / "backups", now=NOW)
    before = sha(database)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = int(listener.getsockname()[1])
    try:
        with pytest.raises(backup.RestoreRefused) as refused:
            backup.restore_backup(Path(made["path"]), database, host="127.0.0.1", port=port)
        restore = load_script("restore")
        code = restore.main(
            [
                made["path"],
                "--database",
                str(database),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--yes",
            ]
        )
    finally:
        listener.close()
    assert "rulează" in refused.value.reason_ro and str(port) in refused.value.reason_ro
    assert code != 0
    assert sha(database) == before, "the database was touched by a refused restore"


def test_after_a_restore_the_studio_is_stopped_in_test_with_its_day_off(engine, tmp_path):
    database = database_of(engine)
    _studio_running_free(engine)
    made = backup.make_backup(database, tmp_path / "backups", now=NOW)
    with Session(engine) as session, session.begin():
        append_event(session, "test.after_the_backup", "test", "1", 1, {}, "later")
    engine.dispose()

    result = backup.restore_backup(
        Path(made["path"]), database, host="127.0.0.1", port=free_port(), now=NOW
    )

    assert result["status"] == "RESTORED"
    restored = create_db_engine(f"sqlite:///{database.as_posix()}")
    try:
        with Session(restored) as session:
            policy = session.get(OwnerPolicy, 1)
            assert policy.autonomy_stopped is True
            assert policy.environment == "TEST"
            job = session.scalar(select(ScheduledJob).where(ScheduledJob.name == "daily_main"))
            assert job is not None and job.is_active is False
            types = set(session.scalars(select(DomainEvent.event_type)))
        assert "test.after_the_backup" not in types, "the restore kept a later write"
        assert "owner.restore_guard_applied" in types
    finally:
        restored.dispose()
    # What he must do next, in his words: nothing stored here, so no connection to re-enter.
    assert result["credentials"] == []
    assert "STOP" in result["guard"]["reason_ro"] and "TEST" in result["guard"]["reason_ro"]
    # The database as it was before the restore is kept, in case the restore was the mistake.
    assert result["previous"] and Path(result["previous"]["path"]).is_file()
    assert result["previous"]["tag"] == "prerestaurare"


def test_the_restore_script_restores_a_copy_and_says_what_to_re_enter(engine, tmp_path, capsys):
    database = database_of(engine)
    made = backup.make_backup(database, tmp_path / "backups", now=NOW)
    engine.dispose()
    restore = load_script("restore")
    code = restore.main(
        [
            made["path"],
            "--database",
            str(database),
            "--host",
            "127.0.0.1",
            "--port",
            str(free_port()),
            "--yes",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "restaurat" in out.lower() and "STOP" in out


# ------------------------------------------------------- the daily job and the pruning


def _task(engine, task_type: str, status: str, age_days: float) -> str:
    stamp = (NOW - timedelta(days=age_days)).isoformat()
    with Session(engine) as session, session.begin():
        row = TaskQueueItem(
            id=f"{task_type}-{status}-{age_days}",
            task_type=task_type,
            payload={},
            priority=0,
            status=status,
            attempts=1,
            max_attempts=1,
            backoff_seconds=5,
            next_attempt_at=stamp,
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(row)
        return row.id


def _outbox(engine, status: str, age_days: float) -> None:
    stamp = (NOW - timedelta(days=age_days)).isoformat()
    with Session(engine) as session, session.begin():
        append_event_with_outbox(session, "test.outbox", "test", "1", 1, {}, f"o-{age_days}")
    with Session(engine) as session, session.begin():
        row = session.scalars(select(OutboxRecord).order_by(OutboxRecord.sequence.desc())).first()
        row.status = status
        row.created_at = stamp
        row.published_at = stamp if status == "PUBLISHED" else None


def test_after_a_good_backup_old_housekeeping_tasks_and_sent_outbox_rows_are_pruned(
    engine, settings, tmp_path
):
    old_watchdog = _task(engine, "WATCHDOG", "COMPLETED", 40)
    recent_watchdog = _task(engine, "WATCHDOG", "COMPLETED", 10)
    old_day = _task(engine, "DAILY_RUN", "COMPLETED", 40)
    failed_watchdog = _task(engine, "WATCHDOG", "DEAD_LETTER", 40)
    with Session(engine) as session:
        outbox_before = int(session.scalar(select(func.count()).select_from(OutboxRecord)) or 0)
    _outbox(engine, "PUBLISHED", 10)
    _outbox(engine, "PUBLISHED", 2)
    _outbox(engine, "PENDING", 10)
    events_before = count(engine, DomainEvent)

    result = backup.run_backup_job(engine, settings, correlation_id="nightly", now=NOW)

    assert result["status"] == "COMPLETED", result
    assert Path(result["backup"]["path"]).parent == database_of(engine).parent / "backups"
    assert result["pruned"]["tasks"] == 1 and result["pruned"]["outbox"] >= 1
    with Session(engine) as session:
        ids = set(session.scalars(select(TaskQueueItem.id)))
        statuses = [row.status for row in session.scalars(select(OutboxRecord))]
    assert old_watchdog not in ids
    assert {recent_watchdog, old_day, failed_watchdog} <= ids
    assert "PENDING" in statuses
    assert len(statuses) == outbox_before + 3 - result["pruned"]["outbox"]
    # The record itself is immutable: events are never pruned (the job adds its own).
    assert count(engine, DomainEvent) >= events_before


def test_a_failed_backup_prunes_nothing_and_tells_the_owner_once(
    engine, settings, tmp_path, monkeypatch
):
    old_watchdog = _task(engine, "WATCHDOG", "COMPLETED", 40)

    def broken(*_args, **_kwargs):
        raise backup.BackupError("Discul copiilor de siguranță este plin.")

    monkeypatch.setattr(backup, "make_backup", broken)
    first = backup.run_backup_job(engine, settings, correlation_id="n1", now=NOW)
    second = backup.run_backup_job(engine, settings, correlation_id="n2", now=NOW)

    assert first["status"] == second["status"] == "FAILED"
    assert "plin" in first["reason_ro"]
    from app.agents.models import AgentMessage

    with Session(engine) as session:
        assert old_watchdog in set(session.scalars(select(TaskQueueItem.id)))
        failures = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == backup.BACKUP_FAILED_EVENT)
        ).all()
        letters = [
            row
            for row in session.scalars(select(AgentMessage))
            if (row.body_json or {}).get("kind") == backup.BACKUP_FAILED_LETTER
        ]
    assert len(failures) == 2
    assert len(letters) == 1, "the same failure on the same day is one letter"


def test_the_backup_job_is_a_worker_task_and_scheduled_at_start(settings, engine):
    from app.workflows.worker import BACKUP, BACKUP_JOB_NAME, build_task_handlers

    handlers = build_task_handlers(engine, settings, None, None)
    assert BACKUP in handlers
    assert BACKUP_JOB_NAME == "backup_daily"
