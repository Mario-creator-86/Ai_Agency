"""A paid redo never waits without bound, never buys blind, and never holds a film for hours.

The Owner's Nepal film, 2026-10-03 (storyboard 81438d13): he pressed «Refă» on the still of
scene 3 at 17:36 UTC. His yes was spent, the film's purchase lease was taken for three hours,
the step's budget hold was taken, Runway took 18 credits (334 -> 316) - and then nothing: no
take, no booking, no answer, until the studio was restarted. Every later press was refused
«Filmul este deja în lucru ... acum 144 de minute» by a lease whose holder was gone.

Three things made that possible, each fixed here:

- a vendor wait had no overall deadline: http.client's timeout bounds one socket operation,
  never a whole response, so a poll or a download that kept trickling never ended;
- the redo kept the vendor's task id only in memory (``heard``), so a redo cut short left
  no record of what Runway had accepted, and nothing could collect it;
- the lease lived three hours whatever happened to its holder, and nobody released the hold,
  or told the Owner what his spent yes had bought.

Every provider is faked; no socket is opened (conftest refuses them); 0 credits.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.models import AgentMessage
from app.economy.models import SpendReservation
from app.media.assembler import (
    SceneRedoRefused,
    collect_submitted_takes,
    redo_plan,
    redo_scene,
)
from app.media.models import FilmPurchaseLease, SceneTake
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from app.providers import media_http
from app.providers.media_http import MediaProviderError, TaskStillOpen
from app.services import append_event
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_approvals import answer
from test_film_costing import a_film
from test_stills_stage import (
    NO_FACE,
    SpyJudge,
    SpyStills,
    Transport,
    faces_in,
    runway_adapter,
)

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def scene_takes(engine, storyboard_id: str, scene: int) -> list[SceneTake]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake)
                .where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.scene_number == scene,
                    SceneTake.kind == "still",
                )
                .order_by(SceneTake.created_at)
            )
        )
        session.expunge_all()
        return rows


def reservations(engine) -> list[SpendReservation]:
    with Session(engine) as session:
        rows = list(
            session.scalars(select(SpendReservation).order_by(SpendReservation.reserved_at))
        )
        session.expunge_all()
        return rows


def events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == event_type)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


def owner_letters(engine, kind: str) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = [
            row
            for row in session.scalars(select(AgentMessage))
            if isinstance(row.body_json, dict) and row.body_json.get("kind") == kind
        ]
        session.expunge_all()
        return rows


def lease_row(engine, storyboard_id: str) -> FilmPurchaseLease | None:
    with Session(engine) as session:
        row = session.get(FilmPurchaseLease, storyboard_id)
        if row is not None:
            session.expunge(row)
        return row


def still_redo(engine, storyboard_id, tmp_path, adapter, plan_hash, judge=None):
    return redo_scene(
        engine,
        storyboard_id,
        str(uuid4()),
        kind="still",
        scene_index=3,
        plan_hash=plan_hash,
        image_adapter=adapter,
        judge=judge or SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
    )


def approved_still_redo(engine, storyboard_id, tmp_path, adapter, judge=None):
    """The Owner's press, his question, his yes, and the redo bought under it."""
    plan = redo_plan(engine, storyboard_id, "still", 3)
    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"], judge)
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED")
    return still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"], judge)


class WatchedStills(SpyStills):
    """The image vendor, faked; at the moment a task is accepted it looks at the books."""

    def __init__(self, engine, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = engine
        self.on_books: list[tuple[str, str | None]] = []

    async def generate_candidates(self, prompt, *, on_submitted=None, **kwargs):
        def heard(task_id: str) -> None:
            if on_submitted is not None:
                on_submitted(task_id)
            with Session(self.engine) as session:
                row = session.scalars(
                    select(SceneTake).where(SceneTake.remote_task_id == task_id)
                ).first()
                self.on_books.append((task_id, row.status if row is not None else None))

        return await super().generate_candidates(prompt, on_submitted=heard, **kwargs)


class OpenRedoStills(SpyStills):
    """Accepts the task (and charges it: 18 credits off the balance) and never delivers in
    time; a later GET answers from ``answers``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.answers: dict[str, dict] = {}
        self.collected: list[str] = []

    async def generate_candidates(self, prompt, *, on_submitted=None, **kwargs):
        self.asked.append({"prompt": prompt, **kwargs})
        task_id = f"img-task-{len(self.asked)}"
        if on_submitted is not None:
            on_submitted(task_id)
        if self.balance is not None:
            self.balance -= 18.0
        raise TaskStillOpen("Runway image task did not finish before the deadline", task_id=task_id)

    async def collect_task(self, task_id):
        self.collected.append(task_id)
        return self.answers.get(task_id, {"state": "RUNNING", "outputs": []})


class ProcessDied(BaseException):
    """The studio's process stopped under the redo (a restart, a closed terminal): nothing
    after this line of the redo runs, not even an ``except Exception``."""


class DyingStills(SpyStills):
    """Accepts the task, takes 18 credits, then the process dies while it polls."""

    async def generate_candidates(self, prompt, *, on_submitted=None, **kwargs):
        self.asked.append({"prompt": prompt, **kwargs})
        task_id = f"img-task-{len(self.asked)}"
        if on_submitted is not None:
            on_submitted(task_id)
        if self.balance is not None:
            self.balance -= 18.0
        raise ProcessDied()


def _done(*files: Path) -> dict:
    return {"state": "SUCCEEDED", "outputs": [(path.read_bytes(), "image/jpeg") for path in files]}


# ------------------------------------------------- 1. what the vendor accepted is on the books


@requires_ffmpeg
def test_a_still_redo_writes_the_vendors_task_on_the_books_before_any_poll(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = WatchedStills(engine, balance=1_000)

    result = approved_still_redo(engine, storyboard_id, tmp_path, adapter)

    assert result["still"]["status"] == "APPROVED"
    # Accepted -> SUBMITTED with its id, before anything was polled or downloaded.
    assert adapter.on_books == [("img-task-1", "SUBMITTED")]
    # The old picture, retired by the redo, is not one of the two bought now.
    bought = [
        t
        for t in scene_takes(engine, storyboard_id, 3)
        if t.sha256 and t.failure_code != "REDO.OWNER"
    ]
    assert len(bought) == 2
    assert {t.remote_task_id for t in bought} == {"img-task-1"}
    assert not [t for t in scene_takes(engine, storyboard_id, 3) if t.status == "SUBMITTED"]


@requires_ffmpeg
def test_a_redo_whose_stills_do_not_arrive_stops_in_flight_and_never_buys_twice(engine, tmp_path):
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = OpenRedoStills(balance=1_000)

    result = approved_still_redo(engine, storyboard_id, tmp_path, adapter)

    # One request only: an accepted task that did not arrive is never sent again.
    assert len(adapter.asked) == 1
    still = result["still"]
    assert still["status"] == "IN_FLIGHT"
    assert "se ridică" in still["reason"] and "fără plată" in still["reason"]
    assert "se ridică" in result["next_ro"]
    (open_take,) = [t for t in scene_takes(engine, storyboard_id, 3) if t.status == "SUBMITTED"]
    assert open_take.remote_task_id == "img-task-1"
    assert open_take.credits_quoted == pytest.approx(18)
    # Booked at once (the balance fell by 18) and the step's hold settled, not left open.
    assert still["spent_credits_measured"] == pytest.approx(18)
    (hold,) = [r for r in reservations(engine) if r.status != "RELEASED"]
    assert hold.status == "SETTLED"
    # A second press cannot buy the scene while the vendor still holds its pictures.
    plan = redo_plan(engine, storyboard_id, "still", 3)
    assert plan["buyable"] is False
    assert "furnizor" in plan["reason_ro"]
    with pytest.raises(SceneRedoRefused) as refused:
        still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"])
    assert refused.value.status == "NOTHING_TO_BUY"
    assert len(adapter.asked) == 1


@requires_ffmpeg
def test_an_in_flight_redo_is_collected_for_free_and_judged_without_a_purchase(engine, tmp_path):
    from app.media.stills_stage import settle_stills

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = OpenRedoStills(balance=1_000)
    approved_still_redo(engine, storyboard_id, tmp_path, adapter)
    adapter.answers["img-task-1"] = _done(*NO_FACE)

    collected = collect_submitted_takes(
        engine,
        collector_for=lambda _take: adapter,
        correlation_id=str(uuid4()),
        storyboard_id=storyboard_id,
        storage_root=tmp_path / "media",
    )
    assert [c["status"] for c in collected] == ["PAID"]
    settled = settle_stills(
        engine,
        storyboard_id,
        str(uuid4()),
        image_adapter=adapter,
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
        storage_root=tmp_path / "media",
    )

    assert {s["scene_index"]: s["status"] for s in settled["scenes"]}[3] == "APPROVED"
    assert len(adapter.asked) == 1, "collecting the redo's pictures bought something"
    statuses = sorted(t.status for t in scene_takes(engine, storyboard_id, 3) if t.sha256)
    assert "APPROVED" in statuses


# ----------------------------------------------- 2. no vendor wait is without an overall end


class SlowResponse:
    """An answer that never ends: one byte per read, each read ten seconds of the clock."""

    status = 200

    def __init__(self, clock):
        self.clock = clock
        self.reads = 0
        self.headers = self

    def get_content_type(self):
        return "image/png"

    def getheader(self, _name, default=None):
        return default

    def read(self, _amount=None):
        self.reads += 1
        self.clock[0] += 10.0
        return b"x"


class SlowConnection:
    def __init__(self, clock):
        self.response = SlowResponse(clock)
        self.sock = None

    def request(self, *_args, **_kwargs):
        return None

    def getresponse(self):
        return self.response

    def close(self):
        return None


def test_a_response_that_never_ends_is_cut_at_its_total_deadline(monkeypatch):
    clock = [1_000.0]
    connection = SlowConnection(clock)
    monkeypatch.setattr(media_http.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(media_http.http.client, "HTTPSConnection", lambda *_a, **_k: connection)

    with pytest.raises(MediaProviderError) as cut:
        media_http.request(
            "files.test", "GET", "/still.png", {}, timeout=120, expect_json=False, total_seconds=30
        )

    assert cut.value.unanswered is True
    assert connection.response.reads <= 4
    assert "30" in str(cut.value)


class RecordingTransport(Transport):
    """Runway's HTTPS boundary, faked, remembering the deadline each call was given."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.totals: list[tuple[str, float | None]] = []

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        self.totals.append((f"{method} {host}{path[:12]}", kwargs.get("total_seconds")))
        return super().__call__(host, method, path, headers, body, **kwargs)


def test_every_runway_call_of_a_still_purchase_carries_a_total_deadline(monkeypatch):
    from app.providers import runway

    adapter, _ = runway_adapter(monkeypatch)
    transport = RecordingTransport()
    monkeypatch.setattr(runway, "request", transport)

    results = asyncio.run(adapter.generate_candidates("ridges", ratio="1530:2720", count=2))

    assert len(results) == 2
    assert transport.totals, "nothing was asked"
    assert all(total is not None and total > 0 for _call, total in transport.totals), (
        transport.totals
    )


def test_a_still_purchase_past_its_overall_deadline_is_left_open_with_its_task_id(monkeypatch):
    from app.providers import runway

    adapter, transport = runway_adapter(monkeypatch)
    monkeypatch.setattr(runway, "IMAGE_PURCHASE_DEADLINE_SECONDS", 0)
    heard: list[str] = []

    with pytest.raises(TaskStillOpen) as still_open:
        asyncio.run(
            adapter.generate_candidates(
                "ridges", ratio="1530:2720", count=2, on_submitted=heard.append
            )
        )

    assert still_open.value.task_id == "task-1" and heard == ["task-1"]
    # Nothing was downloaded past the deadline: the pictures are collected later by the id.
    assert not [c for c in transport.calls if c["host"] == "files.test"]


# --------------------------------------- 3. a lease outlives no holder; his yes is accounted for


def test_a_held_lease_is_renewed_while_its_buyer_works(engine, tmp_path, monkeypatch):
    from app.media import shooting_sheet

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    monkeypatch.setattr(shooting_sheet, "LEASE_RENEW_SECONDS", 0.05)
    monkeypatch.setattr(shooting_sheet, "LEASE_STALE_SECONDS", 2)

    with shooting_sheet.film_purchase_lease(
        engine, storyboard_id, holder="press-1", step="scene_redo", ttl_seconds=3_600
    ):
        first = datetime.fromisoformat(lease_row(engine, storyboard_id).expires_at)
        # Never three hours ahead: a lease that stops being renewed lapses within minutes.
        assert first <= datetime.now(UTC) + timedelta(seconds=3)
        time.sleep(0.4)
        later = datetime.fromisoformat(lease_row(engine, storyboard_id).expires_at)
        assert later > first, "the holder did not renew its lease"
        # A live holder is never reclaimed, by the watchdog's pass or by a start-up.
        reclaimed = shooting_sheet.reclaim_abandoned_leases(
            engine, correlation_id="pass", started_at=datetime.now(UTC) + timedelta(hours=1)
        )
        assert reclaimed["reclaimed"] == []
        assert shooting_sheet.current_lease(engine, storyboard_id)["holder"] == "press-1"
    assert lease_row(engine, storyboard_id) is None


@requires_ffmpeg
def test_a_redo_whose_process_died_is_reclaimed_its_hold_released_and_the_owner_told(
    engine, settings, tmp_path, monkeypatch
):
    from app.media import shooting_sheet
    from app.workflows.watchdog import run_watchdog

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = DyingStills(balance=334)
    plan = redo_plan(engine, storyboard_id, "still", 3)
    with pytest.raises(SceneRedoRefused) as asked:
        still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"])
    answer(engine, asked.value.approval_id, "APPROVED")
    # A dead process gives nothing back: its lease row stays where it was.
    monkeypatch.setattr(shooting_sheet, "_give_back_lease", lambda *_a, **_k: None)
    with pytest.raises(ProcessDied):
        still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"])

    left = lease_row(engine, storyboard_id)
    assert left is not None and left.step == "scene_redo"
    (hold,) = [r for r in reservations(engine) if r.status == "RESERVED"]
    (task,) = [t for t in scene_takes(engine, storyboard_id, 3) if t.status == "SUBMITTED"]
    assert task.remote_task_id == "img-task-1"

    # Nobody renews it: ten minutes later the film is nobody's, and the page says so.
    later = datetime.now(UTC) + timedelta(minutes=10)
    monkeypatch.setattr(shooting_sheet, "_now", lambda: later)
    assert shooting_sheet.current_lease(engine, storyboard_id) is None

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda _take: None
    )

    assert result["film_leases"]["reclaimed"] == [storyboard_id]
    assert lease_row(engine, storyboard_id) is None
    released = next(r for r in reservations(engine) if r.id == hold.id)
    assert released.status == "RELEASED"
    (event,) = events(engine, "media.film_purchase_lease_reclaimed")
    assert event.payload["step"] == "scene_redo"
    assert event.payload["approvals_consumed"]
    assert event.payload["reservations_released"] == [hold.id]
    assert event.payload["submitted_takes"] == [task.id]
    (letter,) = owner_letters(engine, "film_purchase_abandoned")
    text = letter.body_text or ""
    assert "scenei 3" in text
    assert "aprobarea" in text.lower()
    assert "fără plată" in text  # the accepted request is collected, never bought again
    assert "Refă" in text and "automat" in text
    # A second pass finds nothing more to do and writes no second letter.
    again = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda _take: None
    )
    assert again["film_leases"]["reclaimed"] == []
    assert len(owner_letters(engine, "film_purchase_abandoned")) == 1


def _the_owners_lease_of_2026_10_03(engine, storyboard_id: str) -> str:
    """What his books held after the restarts: a three-hour lease, the redo's hold, his
    consumed yes, the balance read before (334) and after (316); no take. Returns the hold.
    (The books' history cannot be backdated: the lease is taken now, the start is later.)"""
    from app.economy.budget import reserve_spend

    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.scene_redone",
            "storyboard",
            storyboard_id,
            1,
            {"kind": "still", "scene_index": 2, "credits": 18.0, "balance_after": 334.0},
            str(uuid4()),
        )
    # Scene 3's redo was pressed after scene 2's had finished (17:35, then 17:36).
    acquired = datetime.now(UTC)
    hold = reserve_spend(engine, 540_000, "sheet:scene_redo", storyboard_id, note="plan")
    with Session(engine) as session, session.begin():
        session.add(
            FilmPurchaseLease(
                storyboard_id=storyboard_id,
                holder=str(uuid4()),
                step="scene_redo",
                acquired_at=acquired.isoformat(),
                expires_at=(acquired + timedelta(hours=3)).isoformat(),
            )
        )
        session.add(
            ApprovalRequest(
                id=str(uuid4()),
                action="media.scene_redo",
                risk_tier="T3",
                requester="video_editor",
                evidence="imaginea scenei 3: 2 variante la 2K, 18 credite, plafon 54",
                proposed_diff={"plan_hash": "p", "cap_credits": 54, "step": "scene_redo"},
                cost_usd=0.54,
                reversible=False,
                expires_at=(acquired + timedelta(days=2)).isoformat(),
                approver="owner",
                result="APPROVED",
                created_at=acquired.isoformat(),
                subject=storyboard_id,
                decided_at=acquired.isoformat(),
                consumed_at=(acquired + timedelta(seconds=1)).isoformat(),
            )
        )
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.paid_step_balance_read",
            "storyboard",
            str(uuid4()),
            1,
            {"credits": 316.0, "needed_credits": 21, "step": "stills"},
            str(uuid4()),
        )
    return str(hold["reservation_id"])


def test_at_start_a_lease_left_by_an_earlier_process_is_reclaimed_and_his_spend_told(
    engine, tmp_path
):
    from app.media.shooting_sheet import current_lease, reclaim_abandoned_leases

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    hold = _the_owners_lease_of_2026_10_03(engine, storyboard_id)
    # Its holder renewed nothing: written before leases were renewed, three hours ahead.
    assert current_lease(engine, storyboard_id) is not None

    # The watchdog's pass alone leaves a lease that has not lapsed to its holder...
    assert reclaim_abandoned_leases(engine, correlation_id="pass")["reclaimed"] == []
    # ...but a process that starts knows such a lease is from before it.
    started = datetime.now(UTC)
    result = reclaim_abandoned_leases(engine, correlation_id="start", started_at=started)

    assert result["reclaimed"] == [storyboard_id]
    assert current_lease(engine, storyboard_id) is None
    assert next(r for r in reservations(engine) if r.id == hold).status == "RELEASED"
    (letter,) = owner_letters(engine, "film_purchase_abandoned")
    text = letter.body_text or ""
    assert "334" in text and "316" in text
    assert "18 credite" in text
    assert "nicio imagine" in text
    assert "Refă" in text and "automat" in text


def test_a_lease_left_from_before_a_start_is_left_alone_when_it_was_renewed(engine, tmp_path):
    """Two studio processes on one database: one that starts must not take the other's live
    redo, which renews its lease (never further ahead than one window)."""
    from app.media.shooting_sheet import LEASE_STALE_SECONDS, reclaim_abandoned_leases

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        session.add(
            FilmPurchaseLease(
                storyboard_id=storyboard_id,
                holder="the-other-process",
                step="scene_redo",
                acquired_at=(now - timedelta(minutes=10)).isoformat(),
                expires_at=(now + timedelta(seconds=LEASE_STALE_SECONDS - 5)).isoformat(),
            )
        )

    result = reclaim_abandoned_leases(engine, correlation_id="start", started_at=now)

    assert result["reclaimed"] == []
    assert lease_row(engine, storyboard_id).holder == "the-other-process"


def test_a_press_after_a_lapsed_lease_takes_it_over_and_settles_what_was_left(
    engine, tmp_path, monkeypatch
):
    from app.media import shooting_sheet

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    hold = _the_owners_lease_of_2026_10_03(engine, storyboard_id)
    # His next press, after the old three-hour lease lapsed.
    later = datetime.now(UTC) + timedelta(hours=3, minutes=5)
    monkeypatch.setattr(shooting_sheet, "_now", lambda: later)

    with shooting_sheet.film_purchase_lease(
        engine, storyboard_id, holder="his-new-press", step="scene_redo"
    ):
        assert lease_row(engine, storyboard_id).holder == "his-new-press"

    assert next(r for r in reservations(engine) if r.id == hold).status == "RELEASED"
    assert len(owner_letters(engine, "film_purchase_abandoned")) == 1
    assert len(events(engine, "media.film_purchase_lease_reclaimed")) == 1


def test_a_live_holder_in_this_process_keeps_its_lapsed_lease(engine, tmp_path, monkeypatch):
    """The Owner's machine slept (or a write lock stood) longer than the lease's window while
    a redo was running: on waking, the watchdog of the same process may run before the
    holder's renewal. A holder alive in this very process is not gone: its film is neither
    reclaimed (no false letter, no hold released under a live purchase) nor taken over by a
    second press (no second purchase), and the sheet still says the film is being worked."""
    from app.media import shooting_sheet

    storyboard_id = a_film(engine, tmp_path, scenes=2)
    # No renewal happens during the test: the row lapses as it would during a sleep.
    monkeypatch.setattr(shooting_sheet, "LEASE_RENEW_SECONDS", 3_600.0)

    with shooting_sheet.film_purchase_lease(
        engine, storyboard_id, holder="live-redo", step="scene_redo", ttl_seconds=10_800
    ):
        woke = datetime.now(UTC) + timedelta(minutes=12)
        monkeypatch.setattr(shooting_sheet, "_now", lambda: woke)

        assert shooting_sheet.reclaim_abandoned_leases(engine, correlation_id="pass") == {
            "reclaimed": [],
            "letters": [],
        }
        assert lease_row(engine, storyboard_id).holder == "live-redo"
        with pytest.raises(shooting_sheet.FilmBusy):
            with shooting_sheet.film_purchase_lease(
                engine, storyboard_id, holder="second-press", step="scene_redo"
            ):
                pytest.fail("a second press bought while the first purchase was alive")
        assert shooting_sheet.current_lease(engine, storyboard_id)["holder"] == "live-redo"
        assert owner_letters(engine, "film_purchase_abandoned") == []

    # Once its block ends the holder is gone from this process, and the row with it.
    assert lease_row(engine, storyboard_id) is None
    assert shooting_sheet.reclaim_abandoned_leases(engine, correlation_id="pass")["reclaimed"] == []


# ------------------------------------- 4. adversarial checks (money lens, 2026-10-03 review)


def _trickling_server(head: bytes, drip: bytes, every: float = 0.05):
    """A loopback HTTP server that sends ``head`` and then ``drip`` every ``every`` seconds
    for ever: each socket read gets a byte well inside any per-read timeout, so only an
    overall deadline can end the request. Loopback only (conftest refuses anything else)."""
    import socket
    import threading

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def serve() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            conn.recv(65536)
            conn.sendall(head)
            while not stop.wait(every):
                conn.sendall(drip)
        except OSError:
            pass
        finally:
            conn.close()
            server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], stop


def _bounded_request(monkeypatch, head: bytes, drip: bytes, *, total: float, expect_json: bool):
    """`media_http.request` against a trickling loopback server, run in a thread that the
    test waits for at most 15 s; returns (finished, error, seconds)."""
    import http.client
    import threading

    port, stop = _trickling_server(head, drip)
    monkeypatch.setattr(
        media_http.http.client,
        "HTTPSConnection",
        lambda _host, timeout=None: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout),
    )
    outcome: dict = {}

    def call() -> None:
        started = time.monotonic()
        try:
            media_http.request(
                "api.test",
                "GET",
                "/v1/tasks/x",
                {},
                timeout=30,
                expect_json=expect_json,
                total_seconds=total,
            )
        except BaseException as exc:  # noqa: BLE001 - examined below
            outcome["error"] = exc
        outcome["seconds"] = time.monotonic() - started

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout=15)
    finished = not worker.is_alive()
    stop.set()
    worker.join(timeout=5)
    return finished, outcome.get("error"), outcome.get("seconds")


def test_a_body_trickled_a_byte_at_a_time_is_cut_at_the_total_deadline(monkeypatch):
    """A real socket: the vendor sends a byte every 50 ms of a 100 kB answer. Each read is
    well inside its own timeout, so only the request's overall end can stop it."""
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n"

    finished, error, seconds = _bounded_request(
        monkeypatch, head, b" ", total=1.0, expect_json=True
    )

    assert finished, "a trickling answer held the request past its total deadline"
    assert isinstance(error, MediaProviderError) and error.unanswered is True
    assert seconds < 5


def test_headers_trickled_a_byte_at_a_time_are_cut_at_the_total_deadline(monkeypatch):
    """The same vendor stalling inside its status line and headers, before any body."""
    finished, error, seconds = _bounded_request(
        monkeypatch, b"HTTP/1.1 200 OK\r\nX-Slow: ", b"a", total=1.0, expect_json=True
    )

    assert finished, "trickled headers held the request past its total deadline"
    assert isinstance(error, MediaProviderError) and error.unanswered is True
    assert seconds < 5


class SecondTaskTransport(Transport):
    """Runway without ``outputCount``: one task per candidate. The first is accepted and
    delivers; the second is ``second`` ("unanswered": its POST never answers; "failed": the
    vendor fails it)."""

    def __init__(self, second: str):
        super().__init__(outputs=1)
        self.second = second

    def __call__(self, host, method, path, headers, body=None, **kwargs):
        if path == "/v1/text_to_image" and self.tasks == 1 and self.second == "unanswered":
            self.calls.append({"host": host, "method": method, "path": path, "body": body})
            raise MediaProviderError("api.dev.runwayml.com did not answer", unanswered=True)
        if path == "/v1/tasks/task-2" and self.second == "failed":
            self.calls.append({"host": host, "method": method, "path": path, "body": body})
            return (
                {"status": "FAILED", "failureCode": "INTERNAL", "failure": "boom"},
                b"",
                "application/json",
            )
        return super().__call__(host, method, path, headers, body, **kwargs)


@pytest.mark.parametrize("second", ["unanswered", "failed"])
def test_a_first_task_already_accepted_is_never_turned_into_a_refusal(monkeypatch, second):
    """Two candidates as two tasks: the first is accepted (and charged) and delivers, the
    second's POST hangs or the vendor fails it. The purchase must stay open for the first
    task (TaskStillOpen with its id: collected free), never a plain refusal - a refusal
    marks the paid first task REFUSED (its picture thrown away) and, for a transient code,
    lets the redo buy the whole request again."""
    from app.providers import runway
    from test_stills_stage import SEEDREAM

    contract = {**SEEDREAM, "fields": {"text_to_image": ["model", "promptText", "ratio"]}}
    adapter = runway.RunwayImageAdapter("key", "seedream5_pro", dict(contract))
    transport = SecondTaskTransport(second)
    monkeypatch.setattr(runway, "request", transport)
    monkeypatch.setattr(runway, "IMAGE_POLL_SECONDS", 0.0)
    heard: list[str] = []

    with pytest.raises(TaskStillOpen) as still_open:
        asyncio.run(
            adapter.generate_candidates(
                "ridges", ratio="1530:2720", count=2, on_submitted=heard.append
            )
        )

    assert still_open.value.task_id == "task-1"
    assert heard[0] == "task-1"
    submits = [c for c in transport.calls if c["path"] == "/v1/text_to_image"]
    assert len(submits) == 2, "a POST was sent again"


@requires_ffmpeg
def test_collected_but_unjudged_redo_pictures_are_judged_before_a_second_purchase(engine, tmp_path):
    """The redo's task was collected free (the watchdog) and its pictures wait, PAID and not
    yet judged. A second press on the scene must not buy them again blind: they are judged
    first, free, and the one the gate approves ends the press with nothing bought."""
    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = OpenRedoStills(balance=1_000)
    approved_still_redo(engine, storyboard_id, tmp_path, adapter)
    adapter.answers["img-task-1"] = _done(*NO_FACE)
    collect_submitted_takes(
        engine,
        collector_for=lambda _take: adapter,
        correlation_id=str(uuid4()),
        storyboard_id=storyboard_id,
        storage_root=tmp_path / "media",
    )
    waiting = [t for t in scene_takes(engine, storyboard_id, 3) if t.status == "PAID"]
    assert waiting and all(t.failure_code == "COLLECTED.UNJUDGED" for t in waiting)
    plan = redo_plan(engine, storyboard_id, "still", 3)

    with pytest.raises(SceneRedoRefused) as judged:
        still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"])

    assert judged.value.status == "PAID_PICTURES_JUDGED"
    reason = judged.value.reason_ro
    assert "fără plată" in reason and "Nu s-a cumpărat nimic" in reason
    assert len(adapter.asked) == 1, "the paid pictures were bought a second time"
    statuses = [t.status for t in scene_takes(engine, storyboard_id, 3) if t.sha256]
    assert "APPROVED" in statuses
    # No yes was asked and no hold taken for the press that bought nothing.
    assert len([r for r in reservations(engine) if r.status == "RESERVED"]) == 0


@requires_ffmpeg
def test_a_press_never_collects_a_task_beside_a_buyer_at_work(engine, tmp_path):
    """The free judging a press does first runs under the film's lease: while another buyer
    holds it (and polls its own tasks) nothing is collected beside it."""
    from app.media import shooting_sheet

    storyboard_id = a_film(engine, tmp_path, scenes=4)
    adapter = OpenRedoStills(balance=1_000)
    approved_still_redo(engine, storyboard_id, tmp_path, adapter)
    adapter.answers["img-task-1"] = _done(*NO_FACE)
    plan = redo_plan(engine, storyboard_id, "still", 3)

    with shooting_sheet.film_purchase_lease(
        engine, storyboard_id, holder="buyer-at-work", step="stills"
    ):
        with pytest.raises(SceneRedoRefused):
            still_redo(engine, storyboard_id, tmp_path, adapter, plan["plan_hash"])

    assert adapter.collected == [], "a task was collected beside the buyer polling it"
    assert len(adapter.asked) == 1


def test_every_runway_call_of_a_shot_purchase_carries_a_total_deadline(monkeypatch):
    # The motion step, the test shot and a motion redo buy through the video adapter: its
    # submit, its polls and its download each carry an end of their own, as the stills do.
    from app.providers import runway
    from app.providers.runway import RunwayVideoAdapter

    answers = [
        ({"id": "task-9"}, b"", "application/json"),
        ({"id": "task-9", "status": "RUNNING"}, b"", "application/json"),
        (
            {"id": "task-9", "status": "SUCCEEDED", "output": ["https://cdn.vendor.example/o.mp4"]},
            b"",
            "application/json",
        ),
        (None, b"MP4BYTES", "video/mp4"),
    ]
    totals: list[tuple[str, object]] = []

    def transport(host, method, path, headers, body=None, **kwargs):
        totals.append((f"{method} {path[:16]}", kwargs.get("total_seconds")))
        return answers.pop(0)

    monkeypatch.setattr(runway, "request", transport)
    contract = {
        "tasks": ["text_to_video"],
        "ratios": {"text_to_video": ["720:1280"]},
        "durations": {"text_to_video": [5, 10]},
    }
    adapter = RunwayVideoAdapter("key", "gen4_turbo", contract)

    job = asyncio.run(
        adapter.create_generation("Slow push-in.", duration_seconds=5, aspect_ratio="9:16")
    )
    asyncio.run(adapter.get_generation_status(job))
    done = asyncio.run(adapter.get_generation_status(job))

    assert done.video_bytes == b"MP4BYTES"
    assert len(totals) == 4
    assert all(isinstance(total, int | float) and total > 0 for _call, total in totals), totals
