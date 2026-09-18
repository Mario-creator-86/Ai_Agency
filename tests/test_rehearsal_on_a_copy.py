"""The no-cost rehearsal of a whole day, on a COPY of the Owner's own studio database.

Opt-in: skipped unless ``STUDIO_REHEARSAL_DB`` names a database file. The file is a copy the
Owner (or a session) made of ``data/studio.db`` with a plain file copy; the test refuses any
path that resolves to ``data/studio.db`` itself. It copies that file again into its own
temporary folder (with ``-wal``/``-shm`` and the ``.credentials.key`` beside it, when they
exist), so even the named copy is never changed.

What it does, in the Owner's own order: migrate with the application's ``migrate()`` and run
the seeds ``scripts/bootstrap.py`` runs; start the application and read the preflight; then
drive one day through the real path — ``scheduler_tick`` -> the queue -> ``worker_pass`` ->
``execute_daily_run`` — with only the paid vendors faked, by the end-to-end test's own
installer (``install_vendor_fakes``, the list ``VENDOR_FAKES`` that
tests/test_no_paid_path_escapes.py checks against the source) and its language model under
every provider id of the copy. The motion chooser is the end-to-end fake: the studio's own
router picks the model from his catalogue and a local test pattern is the shot, so his
TEST terms and his books are exercised and nothing is bought. The trends feed is off.

Nothing leaves the machine, by the suite's own guard (``no_network`` in tests/conftest.py:
connect, connect_ex, DNS and asyncio's ``sock_connect``, refused for anything but loopback).
Here it is switched to raise a refusal as the OSError a real outage would be, so the day
meets it where it would meet the outage and goes on. A refused attempt is the rule working:
it is printed with the studio frames that made it, and it is never worked around.

It asserts only what must always hold: the migration applies, the application starts, the
preflight answers, the day reaches its log stage, and nothing left the machine. Everything
else a day does on real data — which stage stopped it and why — is printed, not asserted,
because that is the finding a rehearsal exists to produce.

    set STUDIO_REHEARSAL_DB=C:\\path\\to\\a\\copy\\studio.db
    uv run pytest -q -s tests/test_rehearsal_on_a_copy.py
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "studio.db"
NAMED = os.environ.get("STUDIO_REHEARSAL_DB", "").strip()

pytestmark = pytest.mark.skipif(
    not NAMED,
    reason="opt-in rehearsal: set STUDIO_REHEARSAL_DB to a COPY of data/studio.db",
)


def _is_live(path: Path) -> bool:
    if path.resolve() == LIVE_DB.resolve():
        return True
    try:
        return LIVE_DB.exists() and path.exists() and os.path.samefile(path, LIVE_DB)
    except OSError:
        return False


@pytest.fixture
def offline(no_network):
    """The suite's guard, raising what a real outage raises; returns its refusals.

    One guard for the suite and the rehearsal: this file used to carry its own, which was
    one DNS lookup ahead of the suite's and could drift from it again.
    """
    no_network.loud = False
    # The guard proves itself before the studio does anything.
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("example.com", 443)
    probe = socket.socket()
    try:
        with pytest.raises(ConnectionRefusedError):
            probe.connect(("192.0.2.1", 443))
    finally:
        probe.close()
    no_network.refused.clear()
    return no_network.refused


@pytest.fixture
def rehearsal_copy(tmp_path):
    named = Path(NAMED)
    if _is_live(named):
        pytest.fail(
            f"STUDIO_REHEARSAL_DB names the live studio database ({LIVE_DB}). The rehearsal "
            "runs only on a copy: copy data/studio.db (with -wal and -shm) somewhere else "
            "and name that file.",
            pytrace=False,
        )
    if not named.is_file():
        pytest.fail(f"STUDIO_REHEARSAL_DB does not name a file: {named}", pytrace=False)
    target = tmp_path / "studio.db"
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(named) + suffix)
        if source.is_file():
            shutil.copy2(source, Path(str(target) + suffix))
    key = named.with_suffix(".credentials.key")
    if key.is_file():
        shutil.copy2(key, target.with_suffix(".credentials.key"))
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        connection.close()
    return target


def _revision(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()


def test_a_whole_day_on_a_copy_of_the_owners_studio(
    offline, rehearsal_copy, tmp_path, monkeypatch, capsys
):
    from app.agents.services import seed_initial_workforce
    from app.analytics.services import seed_default_strategy
    from app.config import Settings
    from app.db import create_db_engine, migrate
    from app.economy.prices import seed_documented_prices
    from app.economy.services import seed_chart_of_accounts
    from app.integrations.vault import CredentialVault
    from app.main import create_app
    from app.media import assembler
    from app.media.services import seed_default_character_bibles
    from app.providers.registry import ProviderRegistry
    from app.publishing.services import seed_default_channels
    from app.runbook.models import DailyRun
    from app.runbook.services import STAGES, run_summary
    from app.runbook.stages import build_stage_runners
    from app.services import bootstrap_studio
    from app.story.services import business_date
    from app.workflows.models import ScheduledJob
    from app.workflows.services import scheduler_tick, set_job_active
    from app.workflows.worker import build_task_handlers, worker_pass
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_autonomous_day_end_to_end import (
        FakeMotionChooser,
        RecordingPublisher,
        StudioModel,
        _due_daily_job,
        install_vendor_fakes,
    )

    for key in [name for name in os.environ if name.upper().startswith("STUDIO_")]:
        monkeypatch.delenv(key)
    settings = Settings(
        _env_file=None,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{rehearsal_copy.as_posix()}",
        allowed_hosts=["testserver", "127.0.0.1"],
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
        trends_enabled=False,
        timezone="Europe/Bucharest",
        ffmpeg_path=shutil.which("ffmpeg"),
        # The waits between a stage's retries, not their number: a refused address fails
        # the same way on every attempt, and the rehearsal need not sleep through it.
        stage_retry_backoff_seconds=0,
    )
    report: dict = {"revision_before": _revision(rehearsal_copy)}

    # 1. The migration applies, and the seeds run in scripts/bootstrap.py's order.
    engine = create_db_engine(settings.database_url)
    try:
        migrate(engine)
        bootstrap_studio(engine, settings)
        seed_initial_workforce(engine)
        seed_default_character_bibles(engine)
        seed_default_channels(engine)
        seed_chart_of_accounts(engine)
        seed_documented_prices(engine)
        seed_default_strategy(engine)
    finally:
        engine.dispose()
    report["revision_after"] = _revision(rehearsal_copy)
    assert report["revision_after"] == "0045_reconciliation", report

    # 2. The application starts on it, and the preflight answers.
    headers = {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}
    with TestClient(create_app(settings)) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200, ready.text
        preflight = client.get("/api/v1/runbook/preflight", headers=headers)
        assert preflight.status_code == 200, preflight.text
        body = preflight.json()
        assert body["status"] in ("READY", "DEGRADED", "BLOCKED"), body
        assert body["checks"], body
    report["preflight"] = {
        "status": body["status"],
        "failing": [
            (check["name"], check["severity"], check["message"])
            for check in body["checks"]
            if not check["ok"]
        ],
    }
    report["preflight"]["youtube"] = [
        (check["name"], check["ok"], check["severity"], check["message"])
        for check in body["checks"]
        if check["name"].startswith(("youtube", "publishing", "daily_budget"))
    ]

    # 3. One day, through the real path, with the paid vendors faked.
    engine = create_db_engine(settings.database_url)
    try:
        vault = CredentialVault(rehearsal_copy.with_suffix(".credentials.key"))
        publisher = RecordingPublisher()
        monkeypatch.setattr(assembler, "DEFAULT_STORAGE_ROOT", tmp_path / "media")
        # Every paid boundary, by the end-to-end fixture's own list. The motion chooser is in
        # it since 2026-09-18: on this copy, whose Owner selected Runway for video, a TEST
        # day chose two models per film and tried four paid text_to_video calls that only
        # the network guard stopped. Now his router chooses and the fake films.
        motion = FakeMotionChooser()
        install_vendor_fakes(monkeypatch, publisher=publisher, motion=motion)
        # Except the statistics read, which is free and which the day met for real on this
        # copy on 2026-09-18: the token refresh to Google failed performance intake four times
        # and BLOCKED the nine stages after it, and a 4xx from Google would have opened safe
        # mode. Faking it hid exactly that path, so the real lookup and the real adapter stand
        # behind the guard here, and the refusal must end as «fără date», not as the day.
        from app.analytics import services as analytics_services
        from app.runbook import stages as stage_module

        monkeypatch.setattr(
            stage_module,
            "analytics_provider_for_channel",
            analytics_services.analytics_provider_for_channel,
        )
        model = StudioModel()
        registry = ProviderRegistry()
        with Session(engine) as session:
            from app.agents.models import ProviderRecord

            provider_ids = list(session.scalars(select(ProviderRecord.id)))
            job = session.scalar(select(ScheduledJob).where(ScheduledJob.name == "daily_main"))
            job_id = job.id if job is not None else None
        for provider_id in provider_ids:
            registry.register(provider_id, model)
        # The Owner's own step: the daily clock started from the panel's command, then due.
        if job_id is not None:
            set_job_active(engine, job_id, True, correlation_id=str(uuid4()))
        _due_daily_job(engine)

        runners = build_stage_runners(engine, settings, vault, registry)
        handlers = build_task_handlers(engine, settings, vault, runners, registry)
        scheduler_tick(engine)
        today = business_date(settings.timezone)
        for _ in range(8):
            result = worker_pass(engine, handlers, registry=registry)
            with Session(engine) as session:
                ran_today = session.scalars(
                    select(DailyRun).where(DailyRun.business_date == today)
                ).all()
            if ran_today or not (result["ran"] or result["triggered"]):
                break
        with Session(engine) as session:
            run = session.scalars(
                select(DailyRun)
                .where(DailyRun.business_date == today)
                .order_by(DailyRun.started_at.desc())
            ).first()
            assert run is not None, "the clock fired and no day was recorded"
            recorded = list(run.stages_json)
            report["day"] = {
                "status": run.status,
                "stopped_at_stage": run.stopped_at_stage,
                "stop_reason": run.stop_reason,
                "summary": run_summary(recorded)[0],
                "stages": [
                    (s["stage"], s["status"], s.get("produced"), s["reason"][:300])
                    for s in recorded
                ],
            }
            from app.models import OwnerPolicy

            policy = session.scalar(select(OwnerPolicy))
            report["autonomy_stopped"] = bool(policy.autonomy_stopped) if policy else None
            # The day's books, as the accountant wrote them: what was charged, and what each
            # film's hold was settled against.
            from app.economy.models import ProviderCostRecord, SpendReservation

            costs = session.scalars(
                select(ProviderCostRecord).where(ProviderCostRecord.recorded_at >= run.started_at)
            ).all()
            report["cost_rows"] = [
                (c.provider, c.status, c.usd_micros / 1_000_000, c.failed) for c in costs
            ]
            holds = session.scalars(
                select(SpendReservation).where(SpendReservation.reserved_at >= run.started_at)
            ).all()
            report["holds"] = [
                (h.purpose[:60], h.status, h.usd_micros / 1_000_000, h.settled_reference)
                for h in holds
            ]
    finally:
        engine.dispose()

    # 4. The day reached its log stage, with its own recorded outcome.
    names = [stage["stage"] for stage in recorded]
    assert names == list(STAGES), names
    closing = next(stage for stage in recorded if stage["stage"] == "daily_log")
    assert closing["status"], closing
    # A statistics read that cannot be made is «fără date», never the day: the refused token
    # refresh costs performance intake nothing, blocks no stage and stops no autonomy.
    intake = next(stage for stage in recorded if stage["stage"] == "performance_intake")
    assert intake["status"] != "FAILED", intake
    assert not any(
        "performance_intake" in stage["reason"]
        for stage in recorded[1:]
        if stage["status"] == "BLOCKED"
    ), recorded
    assert report["autonomy_stopped"] is False, report
    # The books charge what was bought and nothing else: one motion row per shot the fake
    # delivered, and no row for a shot that was refused or never reached the vendor.
    motion_rows = [row for row in report["cost_rows"] if row[0] == "runway"]
    assert len(motion_rows) == len(motion.delivered), (motion_rows, motion.delivered)

    # 5. Nothing left the machine: the guard is still the one installed, and every
    #    non-loopback attempt the day made is in the refused list, not on the wire.
    assert socket.getaddrinfo.__name__ == "guarded_getaddrinfo"
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("example.com", 443)
    offline.pop()  # the check above
    report["network_refused"] = offline
    report["uploads_to_simulator"] = len(publisher.uploads)
    report["motion_asked"] = motion.asked
    report["motion_shots"] = [
        (shot.model, shot.last_estimated_credits) for shot in motion.delivered
    ]
    with capsys.disabled():
        print("\nREHEARSAL " + json.dumps(report, ensure_ascii=False, indent=1, default=str))
