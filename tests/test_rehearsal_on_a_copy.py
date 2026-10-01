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

The second test (`test_two_days_of_the_serial_on_a_copy`, S12) runs the day after his newest
events and the day after it, on the same copy, with the Director's leave granted there by his
own versioned policy command, the studio's calendar moved for every ``app.*`` module, and the
real production plan with its voice and picture adapters faked where they are built. With
``REHEARSAL_REPORT_PATH`` set it writes the whole report there, and each day's briefs beside it.
"""

from __future__ import annotations

import json
import os
import re
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
    assert report["revision_after"] == "0048_production_sheet", report

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
        # ASCII: a Windows console's code page cannot print the Romanian reasons, and the
        # rehearsal failed at its last line on that alone (2026-09-24).
        print("\nREHEARSAL " + json.dumps(report, ensure_ascii=True, indent=1, default=str))


# ------------------------------------------------ two days of the serial, on a copy (S12) --

#: The words each beat's two speakers say in the rehearsal, by the beat's part: English, 8-22
#: spoken words a beat and 115-170 in all, as the brief asks. The stand-in follows the brief's
#: schema and its computed rules; what it says is not a judgement of any real model.
REHEARSAL_LINES = {
    "hook": (
        "Before anyone asks, yes, I read the whole record twice.",
        "Twice is exactly once more than the record ever asked for.",
    ),
    "situation": (
        "I want the verdict in writing before the coffee goes cold.",
        "The verdict is in writing. The coffee was never warm.",
    ),
    "situation2": (
        "Then walk me through it, one step, and no adjectives.",
        "Step one, the letter arrived. Step two, I answered it.",
    ),
    "turn": (
        "That answer changes the plan for the rest of today.",
        "It changes my plan. Yours was already changing.",
    ),
    "payoff": (
        "So we keep what we can prove and drop the rest.",
        "Agreed. The rest was mostly your adjectives anyway.",
    ),
    "button": (
        "Note it down: the first time you agreed before lunch.",
        "Noted. Filed under things that will not happen again.",
    ),
}
REHEARSAL_DIRECTIONS = (
    "leaning back, arms crossed",
    "without looking up from the screen",
    "tapping the desk once",
    "turning the monitor towards her",
    "with a very small smile",
    "already walking away",
)
#: One title per told day (by the day's ordinal), so two episodes never share a title.
REHEARSAL_TITLES = (
    "The record, read twice",
    "A verdict before the coffee",
    "The letter that answered itself",
    "Evidence first, adjectives never",
    "One step, no adjectives",
    "The plan that changed at nine",
    "Filed under unlikely",
    "The second reading",
    "Agreed before lunch",
    "What the record kept",
    "The cold coffee clause",
    "Nobody asked twice",
)
_SERIAL_SHOTS_MARK = "office serial, Inside The Nexus. The beats are as they will be filmed"
_TOLD = re.compile(r"in the studio on (\d{4}-\d{2}-\d{2})")


def _rehearsal_model():
    """The end-to-end stand-in, writing each serial answer from its own prompt's data.

    Built lazily: the end-to-end module is imported only when the rehearsal runs.
    """
    from collections import Counter
    from datetime import date

    from test_autonomous_day_end_to_end import StudioModel

    uuid_row = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

    def quoted(prompt: str, key: str) -> str | None:
        found = re.search(rf'"{key}":\s*"((?:[^"\\]|\\.)*)"', prompt)
        return json.loads(f'"{found.group(1)}"') if found else None

    class RehearsalModel(StudioModel):
        def _answer(self, prompt: str) -> str:
            if _SERIAL_SHOTS_MARK in prompt:
                return self._serial_shots(prompt)
            if "hold_reasons" in prompt and '"script_title"' in prompt:
                return self._publisher(prompt)
            return super()._answer(prompt)

        def _publisher(self, prompt: str) -> str:
            title = quoted(prompt, "script_title") or "Untitled"
            serial = "Inside The Nexus" in prompt
            logline = quoted(prompt, "logline") if serial else None
            return json.dumps(
                {
                    "verdict": "READY",
                    "title": title,
                    "description": logline or f"{title}: what the studio found, from the record.",
                    "tags": ["office comedy", "workplace"] if serial else ["science", "explainer"],
                    "hold_reasons": [],
                }
            )

        def _serial_shots(self, prompt: str) -> str:
            indices = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)})
            cameras = (
                "wide establishing shot from the doorway, eye level",
                "medium two-shot across the desk",
                "medium two-shot, slightly lower, both faces visible",
                "medium close-up single on the first speaker",
                "medium two-shot, the second speaker leaning in",
                "close-up on the first speaker's reaction",
            )
            return json.dumps(
                {
                    "shots": [
                        {
                            "scene_index": index,
                            "subject": "the two colleagues of the beat, facing the viewer",
                            "action": REHEARSAL_DIRECTIONS[(index - 1) % 6]
                            + ", while the other listens with folded arms",
                            "emotion": "dry, patient amusement",
                            "camera": cameras[(index - 1) % len(cameras)],
                            "background": "colleagues working quietly at glowing monitors",
                            "continuity": "the same room, clothes and cups as the shot before",
                            "ending_frame": "both faces held for a beat",
                            "audio_intent": "room tone, a keyboard, the coffee machine",
                            "transition": "cut",
                        }
                        for index in (indices or [1])
                    ]
                }
            )

        def _episode(self, prompt: str) -> str:
            allowed = re.search(r"^ALLOWED_NAMES: (\[.*\])$", prompt, re.MULTILINE)
            names = json.loads(allowed.group(1)) if allowed else []
            rooms_block = prompt.split("LOCATIONS (", 1)[-1].split("EVENTS OF", 1)[0]
            rooms = re.findall(r"^- ([a-z0-9_-]+): ([^\n]*)$", rooms_block, re.MULTILINE)
            events_block = prompt.split("EVENTS OF", 1)[-1].split("PREVIOUSLY:", 1)[0]
            events = [
                json.loads(row)
                for row in events_block.splitlines()
                if row.startswith('{"id"') and uuid_row.search(row)
            ]
            told = _TOLD.search(prompt)
            if not events or len(names) < 2 or not rooms:
                return "Nu am din ce scrie episodul."
            acting = Counter(n for e in events for n in (e.get("who") or []) if n in names)
            speakers = [name for name, _ in acting.most_common(2)]
            speakers += [n for n in names if n not in speakers][: 2 - len(speakers)]
            ours = [e for e in events if set(e.get("who") or []) & set(speakers)]
            pool = ours + [e for e in events if e not in ours]
            # A writer cites what its speakers did, and no event in more than half the beats.
            cited = [pool[index % len(pool)] for index in range(6)]

            def room_of(name: str) -> str:
                for room_id, text in rooms:
                    if name in text.split("desks:", 1)[-1]:
                        return room_id
                return rooms[0][0]

            parts = ("hook", "situation", "situation2", "turn", "payoff", "button")
            beats = []
            for index, part in enumerate(parts):
                first, second = REHEARSAL_LINES[part]
                where = speakers[1] if part in ("turn", "payoff") else speakers[0]
                beats.append(
                    {
                        "part": "situation" if part == "situation2" else part,
                        "location": room_of(where),
                        "scene": (
                            f"{speakers[0].split(' (')[0]} and {speakers[1].split(' (')[0]} "
                            f"over the day's record, beat {index + 1}."
                        ),
                        "lines": [
                            {
                                "speaker": speakers[0],
                                "text": first,
                                "direction": REHEARSAL_DIRECTIONS[index],
                            },
                            {
                                "speaker": speakers[1],
                                "text": second,
                                "direction": REHEARSAL_DIRECTIONS[(index + 3) % 6],
                            },
                        ],
                        "background": (
                            [n for n in names if n not in speakers][:2] if index == 0 else []
                        ),
                        "event_ids": [cited[index]["id"]],
                    }
                )
            words = sum(len(line["text"].split()) for beat in beats for line in beat["lines"])
            assert 115 <= words <= 170, words
            day = date.fromisoformat(told.group(1)) if told else date.today()
            a, b = (name.split(" (")[0] for name in speakers)
            planned = "Written with Ep." in prompt
            return json.dumps(
                {
                    "title": REHEARSAL_TITLES[day.toordinal() % len(REHEARSAL_TITLES)],
                    "logline": (
                        f"{a} wants the verdict in writing; {b} already wrote it, and neither "
                        "will say so first."
                    ),
                    "beats": beats,
                    "summary": f"{a} asked for the verdict in writing; {b} had written it already.",
                    "threads_continued": [],
                    "threads_closed": [],
                    "threads_opened": [f"whether {a} will ever agree before lunch again"],
                    "recurring": ["the cold coffee"],
                    "next_episode": {
                        "premise": f"{b} brings the verdict before {a} can ask for it.",
                        "cold_open_line": "Before you ask, it is already in writing.",
                        "open_question": f"Will {a} trust a verdict nobody asked for?",
                        "threads_to_pay_off": [],
                    },
                    "plan_kept": False if planned else None,
                    "plan_note": "The day did not bring the verdict early." if planned else "",
                }
            )

    return RehearsalModel()


def _install_studio_clock(monkeypatch):
    """Move the studio's calendar, and only the studio's: every ``app.*`` module's `datetime`.

    The day must be the one after his newest events, and a run must write its own events on
    that day, as a real run at dawn does: the whole-day test moves only the story's calendar,
    which leaves the run's own events on the real date and tomorrow's script with nothing to
    tell. Returns the clock; set ``clock.offset`` to move it. Real time still flows.
    """
    import importlib
    import pkgutil
    import sys
    from datetime import datetime as real_datetime
    from datetime import timedelta

    import app

    class StudioClock(real_datetime):
        offset = timedelta(0)
        moved = 0

        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return real_datetime.now(tz) + cls.offset

    for info in pkgutil.walk_packages(app.__path__, "app."):
        try:
            importlib.import_module(info.name)
        except Exception:  # noqa: BLE001, S112 - a module that cannot import is not on the path
            continue
    for name, module in list(sys.modules.items()):
        if (name == "app" or name.startswith("app.")) and vars(module).get(
            "datetime"
        ) is real_datetime:
            monkeypatch.setattr(module, "datetime", StudioClock)
            StudioClock.moved += 1
    return StudioClock


def test_two_days_of_the_serial_on_a_copy(offline, rehearsal_copy, tmp_path, monkeypatch, capsys):
    """S12: the day after his newest events, then the day after it, through the real
    scheduler, worker and runbook, with every vendor faked. Day 1 films the newest told day
    and writes day 1's script; day 2 films that script without writing it again.

    Printed (and written to ``REHEARSAL_REPORT_PATH`` when set), not asserted, except what
    must hold: nothing leaves the machine, both days run to their log, and day 2 asks no
    model to write day 1's episode again.
    """
    from datetime import UTC, datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from app.agents.models import AgentMessage, ProviderRecord
    from app.agents.services import seed_initial_workforce
    from app.analytics import services as analytics_services
    from app.analytics.services import seed_default_strategy
    from app.config import Settings
    from app.db import create_db_engine, migrate
    from app.economy.prices import seed_documented_prices
    from app.economy.services import seed_chart_of_accounts
    from app.factual.models import StoryReview
    from app.integrations.vault import CredentialVault
    from app.media import assembler, factory
    from app.media.models import Storyboard, StoryboardScene, VideoRenderJob
    from app.media.series_look import load_series_look
    from app.media.services import seed_default_character_bibles
    from app.models import DomainEvent
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.providers.registry import ProviderRegistry
    from app.publishing.models import ChannelRecord, PublicationRecord
    from app.publishing.schemas import PublishPolicyCommand
    from app.publishing.services import change_publish_policy, seed_default_channels
    from app.runbook import stages as stage_module
    from app.runbook.models import DailyRun
    from app.runbook.services import STAGES
    from app.runbook.stages import build_stage_runners
    from app.services import bootstrap_studio
    from app.story.models import ContinuityState, DailyStudioLog, StoryEpisode
    from app.workflows.models import ScheduledJob
    from app.workflows.services import scheduler_tick, set_job_active
    from app.workflows.worker import build_task_handlers, worker_pass
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from test_autonomous_day_end_to_end import (
        FakeMotionChooser,
        RecordingPublisher,
        TestImages,
        install_vendor_fakes,
    )

    tz = "Europe/Bucharest"
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
        timezone=tz,
        ffmpeg_path=shutil.which("ffmpeg"),
        stage_retry_backoff_seconds=0,
    )
    report: dict = {"revision_before": _revision(rehearsal_copy)}

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

        # The day after his newest events, on his own calendar.
        with Session(engine) as session:
            newest = session.scalar(select(func.max(DomainEvent.timestamp)))
            serial_channel = session.scalar(
                select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
            )
            channel_id = serial_channel.id
            policy_version = int(serial_channel.policy_version or 1)
            before_leave = bool(serial_channel.director_may_approve_episodes)
            provider_ids = list(session.scalars(select(ProviderRecord.id)))
            job_id = session.scalar(
                select(ScheduledJob.id).where(ScheduledJob.name == "daily_main")
            )
        newest_local = datetime.fromisoformat(newest).astimezone(ZoneInfo(tz)).date()
        day_1 = newest_local + timedelta(days=1)
        day_2 = day_1 + timedelta(days=1)
        report["newest_event"] = newest
        report["days"] = [day_1.isoformat(), day_2.isoformat()]

        # The Director's leave, on the copy only, by the studio's own versioned command.
        leave = change_publish_policy(
            engine,
            channel_id,
            PublishPolicyCommand(
                command_id=uuid4(),
                expected_version=policy_version,
                director_may_approve_episodes=True,
            ),
        )
        report["director_leave"] = {
            "before": before_leave,
            "status": leave["status"],
            "policy_version": leave["channel"]["policy_version"],
            "event_id": leave["event_id"],
        }

        # The vendors: the whole-day list, then the real production plan with its adapters
        # faked where they are built, so the serial's one-voice-per-speaker plan runs on his
        # own catalogue and the voice cast proposal, and nothing is synthesised by anyone.
        real_render_plan = factory.render_plan
        publisher = RecordingPublisher()
        motion = FakeMotionChooser()
        monkeypatch.setattr(assembler, "DEFAULT_STORAGE_ROOT", tmp_path / "media")
        install_vendor_fakes(monkeypatch, publisher=publisher, motion=motion)
        monkeypatch.setattr(factory, "render_plan", real_render_plan)
        heard: list[tuple[str, str]] = []

        class RecordingVoice(DeterministicTTSAdapter):
            PROVIDER_NAME = "test_voice"
            model = "test-tts-model"

            def __init__(self, voice_id: str, integration_id: str | None = None) -> None:
                self.voice_id = voice_id
                self.integration_id = integration_id

            async def synthesize(self, text: str, **kwargs):  # type: ignore[override]
                heard.append((self.voice_id, text))
                return await super().synthesize(text, voice_id=self.voice_id, speed=1.6)

        def voice_for(_engine, _vault, resolved):
            if not resolved or not resolved.get("valid") or not resolved.get("voice_id"):
                return None
            return RecordingVoice(resolved["voice_id"], resolved.get("integration_id"))

        def image_for(_engine, _vault, resolved):
            return TestImages() if resolved and resolved.get("valid") else None

        monkeypatch.setattr(factory, "tts_provider_for", voice_for)
        monkeypatch.setattr(factory, "image_provider_for", image_for)
        monkeypatch.setattr(factory, "video_provider_for", lambda *a, **k: None)
        monkeypatch.setattr(
            stage_module,
            "analytics_provider_for_channel",
            analytics_services.analytics_provider_for_channel,
        )
        model = _rehearsal_model()
        registry = ProviderRegistry()
        for provider_id in provider_ids:
            registry.register(provider_id, model)
        vault = CredentialVault(rehearsal_copy.with_suffix(".credentials.key"))
        clock = _install_studio_clock(monkeypatch)
        report["clock_modules_moved"] = clock.moved

        def move_clock_to(day, hour: int, minute: int, second: int = 0) -> None:
            target = datetime.combine(day, time(hour, minute, second), ZoneInfo(tz))
            clock.offset = target.astimezone(UTC) - datetime.now(UTC)

        # The Owner's own step on the copy: the daily clock started from the panel's command,
        # a minute before its hour on day 1, so it fires at its hour and never on the spot.
        move_clock_to(day_1, 4, 59)
        activated = set_job_active(engine, job_id, True, correlation_id=str(uuid4()))
        report["daily_main_after_activation"] = activated["next_run_at"]

        look = load_series_look()
        runners = build_stage_runners(engine, settings, vault, registry)
        handlers = build_task_handlers(engine, settings, vault, runners, registry)

        def told_in_prompts(start: int) -> list[str]:
            return [
                (_TOLD.search(p).group(1) if _TOLD.search(p) else "?")
                for p in model.prompts[start:]
                if "ALLOWED_NAMES:" in p
            ]

        def continuity() -> dict:
            with Session(engine) as session:
                row = session.scalar(select(ContinuityState).order_by(ContinuityState.id.desc()))
                if row is None:
                    return {"rows": 0}
                return {
                    "rows": session.scalar(select(func.count(ContinuityState.id))),
                    "version": row.version,
                    "canon_episode_number": row.canon_episode_number,
                    "threads": row.threads_json,
                    "recurring": row.recurring_json,
                }

        def run_day(day) -> dict:
            move_clock_to(day, 5, 0, 30)
            prompts_before, heard_before = len(model.prompts), len(heard)
            uploads_before = len(publisher.uploads)
            triggered = scheduler_tick(engine)
            passes = []
            for _ in range(10):
                result = worker_pass(engine, handlers, registry=registry)
                passes.append([(item.get("status"), item.get("task_id")) for item in result["ran"]])
                with Session(engine) as session:
                    ran = session.scalars(
                        select(DailyRun).where(DailyRun.business_date == day.isoformat())
                    ).all()
                if ran or not (result["ran"] or result["triggered"]):
                    break
            day_report: dict = {
                "clock_at_start": (datetime.now(UTC) + clock.offset).astimezone(ZoneInfo(tz)),
                "triggered": [t.get("job_name") or t.get("job_id") for t in triggered],
                "worker_passes": passes,
            }
            with Session(engine) as session:
                run = session.scalars(
                    select(DailyRun)
                    .where(DailyRun.business_date == day.isoformat())
                    .order_by(DailyRun.started_at.desc())
                ).first()
                job = session.get(ScheduledJob, job_id)
                day_report["daily_main_next_run_at"] = job.next_run_at if job else None
                if run is None:
                    day_report["run"] = None
                    return day_report
                day_report["run"] = {
                    "business_date": run.business_date,
                    "status": run.status,
                    "stopped_at_stage": run.stopped_at_stage,
                    "stop_reason": run.stop_reason,
                }
                day_report["stages"] = [
                    {
                        "stage": s["stage"],
                        "status": s["status"],
                        "reason": s["reason"],
                        **(
                            {"artefacts": s.get("artefacts")}
                            if s["stage"] in ("serial_queue", "serial_next", "media", "publish")
                            else {}
                        ),
                    }
                    for s in run.stages_json
                ]
            day_report["model_calls"] = len(model.prompts) - prompts_before
            day_report["episode_prompts_told_dates"] = told_in_prompts(prompts_before)
            day_report["voice_takes"] = heard[heard_before:]
            day_report["uploads"] = publisher.uploads[uploads_before:]
            day_report["continuity_after"] = continuity()
            # The briefs as the models read them, for the Owner to read whole.
            target = os.environ.get("REHEARSAL_REPORT_PATH", "").strip()
            if target:
                folder = Path(target).parent / f"briefs_{day.isoformat()}"
                folder.mkdir(parents=True, exist_ok=True)
                for number, prompt in enumerate(model.prompts[prompts_before:], start=1):
                    kind = next(
                        (
                            name
                            for mark, name in (
                                ("ALLOWED_NAMES:", "episode"),
                                ('"verdict": "PASS" | "FAIL"', "episode_review"),
                                (_SERIAL_SHOTS_MARK, "serial_shots"),
                                ("hold_reasons", "publisher"),
                            )
                            if mark in prompt
                        ),
                        None,
                    )
                    if kind:
                        (folder / f"{number:03d}_{kind}.txt").write_text(prompt, encoding="utf-8")
            return day_report

        def episodes() -> list[dict]:
            out = []
            with Session(engine) as session:
                for episode in session.scalars(
                    select(StoryEpisode).order_by(StoryEpisode.created_at)
                ):
                    told = session.get(DailyStudioLog, episode.log_id).business_date
                    item: dict = {
                        "id": episode.id,
                        "told_date": told,
                        "title": episode.title,
                        "status": episode.status,
                    }
                    if episode.id in earlier:
                        out.append(item)
                        continue
                    review = episode.review_json or {}
                    item.update(
                        {
                            "reviewed_by": episode.reviewed_by,
                            "rewrite_of": episode.rewrite_of_id,
                            "storyboard_id": episode.storyboard_id,
                            "the_day_as_told": session.get(
                                DailyStudioLog, episode.log_id
                            ).narrative_projection_json,
                            "grounded_event_ids": episode.grounded_event_ids_json,
                            "review": review,
                            "continuity": episode.continuity_json,
                            "beats": [
                                {
                                    "part": beat.get("part"),
                                    "location": beat.get("location"),
                                    "scene": beat.get("scene"),
                                    "lines": [
                                        (
                                            line.get("speaker"),
                                            line.get("text"),
                                            line.get("direction"),
                                        )
                                        for line in beat.get("lines") or []
                                    ],
                                    "background": beat.get("background"),
                                    "event_ids": beat.get("event_ids"),
                                }
                                for beat in episode.beats_json or []
                            ],
                        }
                    )
                    out.append(item)
            return out

        def film_of(storyboard_id: str) -> dict:
            block = look.get("block") or ""
            with Session(engine) as session:
                board = session.get(Storyboard, storyboard_id)
                scenes = session.scalars(
                    select(StoryboardScene)
                    .where(StoryboardScene.storyboard_id == storyboard_id)
                    .order_by(StoryboardScene.scene_index)
                ).all()
                jobs = session.scalars(
                    select(VideoRenderJob)
                    .where(VideoRenderJob.storyboard_id == storyboard_id)
                    .order_by(VideoRenderJob.started_at)
                ).all()
                review = session.scalar(
                    select(StoryReview).where(StoryReview.script_id == board.script_draft_id)
                )
                return {
                    "storyboard": {
                        "title": board.title,
                        "series_key": board.series_key,
                        "visual_bible": {
                            k: (board.visual_bible_json or {}).get(k)
                            for k in ("source", "version", "status")
                        },
                        "story_gate_record": {
                            "verdict": review.verdict if review else None,
                            "notes": review.notes_json if review else None,
                        },
                    },
                    "scenes": [
                        {
                            "index": s.scene_index,
                            "shot_type": s.shot_type,
                            "story_purpose": s.story_purpose,
                            "chars": len(s.visual_prompt),
                            "opens_with_style_block": bool(block)
                            and s.visual_prompt.startswith(block),
                            "prompt_after_block": (
                                s.visual_prompt[len(block) :]
                                if block and s.visual_prompt.startswith(block)
                                else s.visual_prompt
                            ),
                            "location": (s.prompt_json or {}).get("location"),
                            "shot_size": (s.prompt_json or {}).get("shot_size"),
                            "from_model": (s.prompt_json or {}).get("from_model"),
                            "series_look_version": (s.prompt_json or {}).get("series_look_version"),
                            "voiceover": s.voiceover_segment,
                        }
                        for s in scenes
                    ],
                    "render_jobs": [
                        {
                            "status": j.status,
                            "voice_cast": (j.production_json or {}).get("voice_cast"),
                            "segments": [
                                [
                                    {
                                        k: seg.get(k)
                                        for k in (
                                            "speaker",
                                            "voice_id",
                                            "voice_source",
                                            "source",
                                            "provider",
                                            "audio_seconds",
                                        )
                                    }
                                    for seg in (scene.get("segments") or [])
                                ]
                                for scene in (j.production_json or {}).get("scenes") or []
                            ],
                        }
                        for j in jobs
                    ],
                }

        def serial_publications() -> dict:
            with Session(engine) as session:
                return {
                    "publications": [
                        {
                            "title": p.title,
                            "description": p.description,
                            "tags": p.tags_json,
                            "status": p.status,
                            "privacy": p.privacy_status,
                            "created_at": p.created_at,
                        }
                        for p in session.scalars(
                            select(PublicationRecord)
                            .where(PublicationRecord.channel_id == channel_id)
                            .order_by(PublicationRecord.created_at)
                        )
                    ],
                    "publisher_messages": [
                        {
                            k: (m.body_json or {}).get(k)
                            for k in (
                                "verdict",
                                "title",
                                "description",
                                "tags",
                                "metadata_source",
                                "episode_number",
                                "refusals",
                            )
                        }
                        for m in session.scalars(
                            select(AgentMessage)
                            .where(AgentMessage.subject.like("Publication %"))
                            .order_by(AgentMessage.created_at)
                        )
                        if (m.body_json or {}).get("series")
                    ],
                }

        with Session(engine) as session:
            earlier = set(session.scalars(select(StoryEpisode.id)))
        report["style_block"] = look.get("block")
        report["continuity_before"] = continuity()
        report["episodes_before"] = episodes()
        report["day_1"] = run_day(day_1)
        report["episodes_after_day_1"] = episodes()
        report["day_2"] = run_day(day_2)
        report["episodes_after_day_2"] = episodes()
        report["films"] = {
            e["told_date"]: film_of(e["storyboard_id"])
            for e in report["episodes_after_day_2"]
            if e.get("storyboard_id")
        }
        report["serial_channel"] = serial_publications()
        report["network_refused"] = list(offline)
    finally:
        engine.dispose()

    text = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    target = os.environ.get("REHEARSAL_REPORT_PATH", "").strip()
    if target:
        Path(target).write_text(text, encoding="utf-8")
    with capsys.disabled():
        # ASCII on the console: a Windows console's code page cannot print the Romanian
        # reasons, and the report file keeps them as they are.
        shown = json.dumps(report, ensure_ascii=True, indent=1, default=str)
        print("\nREHEARSAL2 " + (shown if not target else shown[:3000]))

    # What must hold. Nothing left the machine.
    assert socket.getaddrinfo.__name__ == "guarded_getaddrinfo"
    for key in ("day_1", "day_2"):
        assert report[key]["run"] is not None, report[key]
        assert [s["stage"] for s in report[key]["stages"]] == list(STAGES)
    # Day 2 asks no model to write day 1's episode again.
    assert report["days"][0] not in report["day_2"]["episode_prompts_told_dates"], report["day_2"]
