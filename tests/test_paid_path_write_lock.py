"""A purchase is booked, and its continuation queued, even when another write lands meanwhile.

2026-10-09 14:17 UTC: the Owner pressed a paid stills step; three GPU rounds made six images
(2100 s of RunPod time), and then the press answered HTTP 500. The frames: `book_step_cost` →
`book_purchase` → `economy.services.record_provider_cost`, which SELECTed the reference for a
duplicate and then INSERTed the cost row without the studio's write lock. Something committed in
between (the outbox dispatcher once a second, the lease keeper, the watchdog), SQLite refused to
upgrade the stale read snapshot at once («database is locked»; `app.db.lock_for_write`), and the
money that had been spent was not in the books. An unbooked purchase lets the next cap check pass
on too low a spend.

The same afternoon (16:47:25) a FILM_CONTINUE deferral died the same way in `enqueue_task`: it
looks its idempotency key up and then inserts, so the continuation of a paid yes became a dead
letter.

Each test commits another write between the read and the insert, with the helper the busy
snapshot suite uses (`test_busy_snapshot_writes._someone_else_writes`), and requires the write to
land; the races make every caller read before any of them writes
(`_every_caller_reads_before_anyone_writes`) and require one row and no error. The last
tests read the source: a transaction in the books or the queue that reads and then writes takes
the lock as its first statement, or stands on a short list that says why it may not, so the next
booking or queue write added to them cannot repeat the 14:17 loss unnoticed; and every such
transaction elsewhere on the paid path is either locked or named on the list of slots other
lanes owe. The paid path read is a list of modules plus every file in the directories where the
repairs, the cards, the books and the RunPod provider grow (`_PAID_PATH_DIRECTORIES`), so a new
unlocked transaction there fails this suite, and a slot another lane lands is named (a
`SlotLanded` warning) for the committing session to delete, without turning the suite red.
"""

from __future__ import annotations

import ast
import threading
import warnings
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from app.db import lock_for_write
from app.economy import services as economy_services
from app.economy.models import LedgerTransaction, ProviderCostRecord
from app.economy.services import (
    EconomyError,
    bill_provider_cost,
    record_provider_cost,
    seed_chart_of_accounts,
    trial_balance,
)
from app.models import OwnerPolicy
from app.workflows import services as workflow_services
from app.workflows.models import ScheduledJob, TaskQueueItem
from app.workflows.services import (
    enqueue_task,
    ensure_scheduled_job,
    retry_dead_letter_task,
    set_job_active,
)
from app.workflows.worker import DAILY_RUN, FILM_CONTINUE
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_busy_snapshot_writes import WRITERS, _someone_else_writes


@pytest.fixture(autouse=True)
def _writers_finish():
    yield
    while WRITERS:
        WRITERS.pop().join(60)


@pytest.fixture
def books(engine):
    seed_chart_of_accounts(engine)
    return engine


def _race(work, attempts: int = 6) -> list[str]:
    """Run ``work`` from several threads released at the same instant."""
    outcomes: list[str] = []
    guard = threading.Lock()
    barrier = threading.Barrier(attempts)

    def attempt() -> None:
        barrier.wait()
        try:
            work()
            result = "accepted"
        except EconomyError:
            result = "refused"
        except Exception as exc:  # noqa: BLE001 - the error class is the finding
            result = f"error:{type(exc).__name__}"
        with guard:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def _every_caller_reads_before_anyone_writes(original, attempts: int = 6, patience: float = 1.0):
    """Wrap the step between a race's read and its INSERT so the callers meet there first.

    Released together, six threads never overlapped between the duplicate (or idempotency)
    SELECT and the INSERT on their own: measured 2026-10-10, the three races stayed green with
    every WP2 lock switched off, so they proved nothing about the lock. Here every caller waits
    at that step until all of them have read. Unlocked, all of them read the same empty answer
    and then write: one row wins and the others are refused by SQLite («database is locked»,
    a stale snapshot) or by the unique index. Locked, the first caller reaches this step
    holding the write lock alone, the others wait in `lock_for_write`, the patience runs out
    and it goes on; each of the others then reads its row in turn and never comes here. Each
    thread waits once, so a step the winner calls twice cannot hold it a second time.
    """
    rendezvous = threading.Barrier(attempts, timeout=patience)
    arrived: set[int] = set()
    guard = threading.Lock()

    def meet_then(*args, **kwargs):
        with guard:
            first_time = threading.get_ident() not in arrived
            arrived.add(threading.get_ident())
        if first_time:
            try:
                rendezvous.wait()
            except threading.BrokenBarrierError:
                pass  # the lock kept the others out: the expected, locked outcome
        return original(*args, **kwargs)

    return meet_then


# ------------------------------------------------------------------- the books: a purchase


def test_record_provider_cost_survives_a_commit_between_read_and_insert(books, monkeypatch):
    original = economy_services._convert_to_usd

    def meanwhile(*args, **kwargs):
        # After the duplicate SELECT, before the INSERT: where the 14:17 booking died.
        _someone_else_writes(books)
        return original(*args, **kwargs)

    monkeypatch.setattr(economy_services, "_convert_to_usd", meanwhile)

    booked = record_provider_cost(
        books,
        provider="runpod",
        external_reference=f"foaie:film:stills:{uuid4().hex[:16]}",
        status="ESTIMATED",
        amount="1.250000",
        attribution={"step": "stills", "measured": True},
    )

    assert booked["status"] == "ESTIMATED"
    with Session(books) as session:
        row = session.get(ProviderCostRecord, booked["id"])
        assert row is not None and row.usd_micros == 1_250_000


def test_a_billed_cost_survives_a_commit_between_read_and_insert(books, monkeypatch):
    """BILLED posts a ledger transaction as well: the whole booking is behind the lock."""
    original = economy_services._convert_to_usd

    def meanwhile(*args, **kwargs):
        _someone_else_writes(books)
        return original(*args, **kwargs)

    monkeypatch.setattr(economy_services, "_convert_to_usd", meanwhile)

    booked = record_provider_cost(
        books,
        provider="runway",
        external_reference=f"invoice-{uuid4().hex[:10]}",
        status="BILLED",
        amount="3.00",
    )

    assert booked["transaction_id"]
    assert trial_balance(books)["balanced"] is True


def test_one_purchase_is_booked_once_however_many_callers_arrive_together(books, monkeypatch):
    """The losers are told it is already in the books, never «database is locked»."""
    reference = f"foaie:film:motion:{uuid4().hex[:16]}"
    # After the duplicate SELECT, before the INSERT (as in the 14:17 test above).
    monkeypatch.setattr(
        economy_services,
        "_convert_to_usd",
        _every_caller_reads_before_anyone_writes(economy_services._convert_to_usd),
    )

    outcomes = _race(
        lambda: record_provider_cost(
            books,
            provider="runway",
            external_reference=reference,
            status="ESTIMATED",
            amount="2.00",
        )
    )

    assert outcomes.count("accepted") == 1, outcomes
    assert outcomes.count("refused") == len(outcomes) - 1, outcomes
    with Session(books) as session:
        rows = session.scalar(
            select(func.count())
            .select_from(ProviderCostRecord)
            .where(ProviderCostRecord.external_reference == reference)
        )
    assert rows == 1


def test_an_estimate_is_billed_once_however_many_callers_arrive_together(books, monkeypatch):
    """One estimate becomes one posting; the losers are told it is posted, never locked out."""
    estimate = record_provider_cost(
        books,
        provider="runway",
        external_reference=f"task-{uuid4().hex[:10]}",
        status="ESTIMATED",
        amount="4.00",
    )
    # After the estimate is read and found unposted, before its posting is written.
    monkeypatch.setattr(
        economy_services,
        "post_transaction",
        _every_caller_reads_before_anyone_writes(economy_services.post_transaction),
    )

    outcomes = _race(lambda: bill_provider_cost(books, estimate["id"]))

    assert outcomes.count("accepted") == 1, outcomes
    assert outcomes.count("refused") == len(outcomes) - 1, outcomes
    assert trial_balance(books)["balanced"] is True
    with Session(books) as session:
        postings = session.scalar(
            select(func.count())
            .select_from(LedgerTransaction)
            .where(LedgerTransaction.memo == f"runway {estimate['external_reference']}")
        )
    assert postings == 1


# ------------------------------------------------------------ the queue: a paid yes goes on


def test_enqueue_task_survives_a_commit_between_read_and_insert(engine, monkeypatch):
    original = workflow_services.uuid4

    def meanwhile():
        # After the idempotency SELECT, before the INSERT: where the 16:47 deferral died.
        _someone_else_writes(engine)
        return original()

    monkeypatch.setattr(workflow_services, "uuid4", meanwhile)
    key = f"film-continue-{uuid4().hex[:8]}-later-1"

    queued = enqueue_task(
        engine,
        "FILM_CONTINUE",
        {"storyboard_id": "film", "deferred": 1},
        priority=4,
        max_attempts=1,
        idempotency_key=key,
    )

    assert queued["status"] == "QUEUED"
    with Session(engine) as session:
        assert session.scalars(
            select(TaskQueueItem).where(TaskQueueItem.idempotency_key == key)
        ).one()


def test_one_continuation_is_queued_once_however_many_callers_arrive_together(engine, monkeypatch):
    """Every caller gets the one queued task back, never «database is locked»."""
    key = f"film-continue-{uuid4().hex[:8]}-later-2"
    ids: list[str] = []
    guard = threading.Lock()
    # After the idempotency SELECT, before the INSERT (as in the 16:47 test above).
    monkeypatch.setattr(
        workflow_services,
        "uuid4",
        _every_caller_reads_before_anyone_writes(workflow_services.uuid4),
    )

    def queue() -> None:
        task = enqueue_task(
            engine,
            "FILM_CONTINUE",
            {"storyboard_id": "film", "deferred": 2},
            priority=4,
            max_attempts=1,
            idempotency_key=key,
        )
        with guard:
            ids.append(task["id"])

    outcomes = _race(queue)

    assert outcomes == ["accepted"] * len(outcomes), outcomes
    assert len(set(ids)) == 1, ids
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TaskQueueItem)
                .where(TaskQueueItem.idempotency_key == key)
            )
            == 1
        )


def test_a_dead_letter_is_requeued_even_when_a_write_lands_meanwhile(engine, monkeypatch):
    """The Owner's «retry» on a dead continuation reads the task and rewrites it."""
    queued = enqueue_task(engine, "FILM_CONTINUE", {"storyboard_id": "film"}, max_attempts=1)
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, queued["id"]).status = "DEAD_LETTER"
    original_get = Session.get

    def get_then_someone_writes(self, entity, ident, *args, **kwargs):
        found = original_get(self, entity, ident, *args, **kwargs)
        if entity is TaskQueueItem and ident == queued["id"]:
            _someone_else_writes(engine)
        return found

    monkeypatch.setattr(Session, "get", get_then_someone_writes)
    again = retry_dead_letter_task(engine, queued["id"])
    monkeypatch.setattr(Session, "get", original_get)

    assert again["status"] == "QUEUED"
    with Session(engine) as session:
        assert session.get(TaskQueueItem, queued["id"]).status == "QUEUED"


# ------------------------------------------------------- the daily clock: his on/off switch


def test_switching_the_daily_clock_off_survives_a_commit_between_read_and_write(
    engine, monkeypatch
):
    """Review 2026-10-09: `set_job_active` reads the job, then writes it and its event. A
    commit in between refused the write: his «stop» answered 500 and the job stayed active,
    so the day still started at its hour and bought under his paid-step rule and caps."""
    job = ensure_scheduled_job(
        engine, name=f"clock-{uuid4().hex[:8]}", workflow_type=DAILY_RUN, interval_seconds=86400
    )
    original = workflow_services.append_event

    def meanwhile(*args, **kwargs):
        # After the job is read and switched in memory, before its row and event are written.
        _someone_else_writes(engine)
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow_services, "append_event", meanwhile)

    stopped = set_job_active(engine, job["id"], False, str(uuid4()))

    assert stopped["is_active"] is False
    with Session(engine) as session:
        assert session.get(ScheduledJob, job["id"]).is_active is False


def test_the_daily_hour_reaches_its_job_even_when_a_write_lands_meanwhile(engine, monkeypatch):
    """At every start-up the job's hour follows the setting: the row is read, then rewritten.
    The outbox dispatcher, the catalogue refresher, the lease reclaim and the GPU guard are
    already running by then (`main.py` lifespan), and a refusal there is raised out of the
    start-up itself."""
    name = f"daily-{uuid4().hex[:8]}"
    original = workflow_services.next_local_occurrence

    def meanwhile(*args, **kwargs):
        # After the job is read, before its new hour is written: both transactions.
        _someone_else_writes(engine)
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow_services, "next_local_occurrence", meanwhile)

    def ensure(hour: str) -> dict:
        return ensure_scheduled_job(
            engine,
            name=name,
            workflow_type=DAILY_RUN,
            interval_seconds=86400,
            run_at_local=hour,
            timezone="Europe/Bucharest",
            active=False,
        )

    created = ensure("05:00")
    moved = ensure("06:00")

    assert (created["run_at_local"], moved["run_at_local"]) == ("05:00", "06:00")
    with Session(engine) as session:
        row = session.get(ScheduledJob, created["id"])
        assert (row.run_at_local, row.is_active) == ("06:00", False)


# --------------------------------------------- the paid-step gate and the Owner's letters


def test_a_paid_step_gate_that_takes_the_lock_first_survives_a_commit_inside_may_act(
    engine, monkeypatch
):
    """The recipe the gate slots need (`_DEFERRED_ELSEWHERE`), proved on the kernel itself.

    `may_act` reads his policy, then under EVERY_PAID_STEP writes his question or spends his
    yes (`app.services._ask_or_spend`). Inside a transaction that did not take the lock first,
    a commit between the two fails the gate on «database is locked»: after his yes that is a
    FILM_CONTINUE (max_attempts=1) dying a dead letter, and his own press a 500 (review
    2026-10-09). With `lock_for_write` first the verdict comes back.

    The unlocked failure is shown on a stand-in of the same shape, not on the live `may_act`
    (review 2026-10-09): the kernel may well learn to lock itself, and this suite must not
    turn red the day it does.
    """
    from app import services as kernel  # noqa: PLC0415 - the kernel's private reader

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    # The shape the gate slots have today: his policy read, a commit, then a write. The write
    # here is a lock taken too late, which is exactly how `_accept_hero` fails (its lock comes
    # after `hero_gate` has read).
    with pytest.raises(OperationalError, match="database is locked"):
        with Session(engine) as session, session.begin():
            session.get(OwnerPolicy, 1)
            _someone_else_writes(engine)
            lock_for_write(session)

    original = kernel._answered_approval
    commits_landed: list[int] = []

    def meanwhile(*args, **kwargs):
        # After his policy is read, before his answer is looked for and the question written.
        _someone_else_writes(engine)
        commits_landed.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(kernel, "_answered_approval", meanwhile)

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        verdict = kernel.may_act(
            session,
            "media.stills_purchase",
            requester="director",
            subject=f"film-{uuid4().hex[:8]}",
            evidence="6 imagini la 2K",
            cost_usd=1.0,
            context={"plan_hash": f"plan-{uuid4().hex[:12]}"},
        )

    assert commits_landed, "the commit was never put inside the gate: the test proves nothing"
    assert verdict["status"] == "NEEDS_APPROVAL", verdict
    assert verdict["approval_id"]


#: Not strict (review 2026-10-09): lane S lands this slot in worker.py, which it owns, and runs
#: only the tests that import what it changed. A strict marker would turn its correct fix into a
#: red XPASS here at the merge; an XPASS is reported instead, for the committing session to
#: delete the marker and the `_DEFERRED_ELSEWHERE` line.
@pytest.mark.xfail(
    strict=False,
    raises=AssertionError,
    reason=(
        "DEFERRED SLOT (lane S, WP11): workflows/worker.py `_tell_continue_interrupted` reads "
        "the Director, then writes the letter. Make `lock_for_write(session)` its first "
        "statement, then delete this marker and its `_DEFERRED_ELSEWHERE` line."
    ),
)
def test_the_interrupted_continuation_letter_survives_a_commit_before_it_is_written(
    engine, monkeypatch
):
    """Review 2026-10-09: the studio restarts during a paid continuation; the first worker pass
    dead-letters it and writes his «Continuarea … a fost întreruptă» letter while the start-up
    writers commit. Refused, the letter is lost for good: the task is already a dead letter and
    nothing tells him again."""
    from app.agents import messages  # noqa: PLC0415
    from app.workflows.worker import announce_interrupted  # noqa: PLC0415

    original = messages.post_message

    def meanwhile(*args, **kwargs):
        # After the Director is read, before the letter is written.
        _someone_else_writes(engine)
        return original(*args, **kwargs)

    monkeypatch.setattr(messages, "post_message", meanwhile)

    told = announce_interrupted(
        engine,
        [{"id": str(uuid4()), "task_type": FILM_CONTINUE, "payload": {"storyboard_id": "film"}}],
    )

    assert told[0].get("letter_id"), told


# ---------------------------------------------- the books: a render whose price has moved
#
# Review 2026-10-09: the first sweep missed this booking route. `record_render_costs` writes
# the price a render measured (`production_policy.record_measured_price`) and, past his alert
# threshold, the Accountant's price letter (`price_change_alert`) BEFORE it books the render's
# narration, still and motion rows. Both read and then write without the lock, and no caller
# catches OperationalError, so a refusal there loses every cost row of the render. Either fix
# makes these pass: the lock first in both, or the booking first and a failed price write that
# never stops it. Not strict, for the same reason as the letter above.

_RENDER_COSTS_SLOT = (
    "DEFERRED SLOT (lane M: media/production_policy.py `record_measured_price`; lane E, WP7: "
    "economy/accountant.py `price_change_alert` and `record_render_costs`): take "
    "`lock_for_write(session)` first in both, or book `_record_priced` before the prices are "
    "measured and the letter sent, so a refused price write never stops the booking. Then "
    "delete this marker, and the `_DEFERRED_ELSEWHERE` line of each function that now locks "
    "(a `SlotLanded` warning names it)."
)


def _a_render_that_moved_its_price(engine, tmp_path) -> str:
    """One bought shot: 20 credits at 0.01 USD, 10.2 s, so 0.0196 USD a second measured
    against the 0.02 on the model (-2 %), and one still at 0.02 USD."""
    from test_books_and_history import MOTION_SHAPES, _a_render_with_one_shot

    job_id, _ = _a_render_with_one_shot(
        engine, tmp_path, MOTION_SHAPES["bought_with_credits"][0], "COMPLETED"
    )
    return job_id


def _booked_in_full(engine, booked: dict) -> None:
    from test_books_and_history import _charged

    assert booked["recorded"] == 2, booked
    assert _charged(engine) == {"image": 20_000, "motion": 200_000}


@pytest.mark.xfail(strict=False, raises=OperationalError, reason=_RENDER_COSTS_SLOT)
def test_a_render_is_booked_even_when_a_write_lands_inside_its_measured_price(
    engine, tmp_path, monkeypatch
):
    from app.economy.accountant import record_render_costs
    from app.integrations import lifecycle

    job_id = _a_render_that_moved_its_price(engine, tmp_path)
    original = lifecycle.stamp_price
    landed: list[int] = []

    def meanwhile(*args, **kwargs):
        # After the model's row is read, before its measured price is written.
        _someone_else_writes(engine)
        landed.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "stamp_price", meanwhile)

    booked = record_render_costs(engine, job_id, str(uuid4()))

    assert landed, "the measured price never moved: the test proves nothing"
    _booked_in_full(engine, booked)


@pytest.mark.xfail(strict=False, raises=OperationalError, reason=_RENDER_COSTS_SLOT)
def test_a_render_is_booked_even_when_a_write_lands_inside_its_price_letter(
    engine, tmp_path, monkeypatch
):
    from app.agents.services import seed_initial_workforce
    from app.economy import accountant

    seed_initial_workforce(engine)  # the letter is the Accountant's; without her, no letter
    job_id = _a_render_that_moved_its_price(engine, tmp_path)
    original = accountant.post_message
    letters: list[int] = []

    def meanwhile(*args, **kwargs):
        # After the Accountant is read, before his letter is written.
        _someone_else_writes(engine)
        letters.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(accountant, "post_message", meanwhile)

    booked = accountant.record_render_costs(engine, job_id, str(uuid4()), alert_percent=1.0)

    assert letters, "no price letter was written: the test proves nothing"
    _booked_in_full(engine, booked)


# ------------------------------------------------- the rule, read from the modules' source
#
# A transaction is read by its structure, not by a list of read calls (review 2026-10-09: the
# list missed reads made through helpers, and counted a dict's `.get` as one). Every call handed
# the transaction's session is one of its actions, taken in the order Python evaluates them.
# Before the first read there must be the lock, or a write that reads nothing first, on a line
# that always runs (not under an `if`, a loop or a short-circuit): then the deferred BEGIN is a
# writer before it has read anything. A transaction that only reads from its first read on needs
# no lock. Anything else (a read and then a write, or a helper, which may read and then write:
# `may_act`, `post_message`, `agent_for_role`, `_convert_to_usd`) takes `lock_for_write` first
# or is named on a list that says why not.

#: The studio's write lock: `app.db.lock_for_write`, and the decisions kernel's `_lock` (the
#: same no-op UPDATE of the policy row).
_LOCKS = {"lock_for_write", "_lock"}
#: Session methods that write. An `add` is INSERTed at the next flush, and SQLAlchemy flushes
#: before any query, so a transaction that adds first is a writer before it reads.
_SESSION_WRITES = {"add", "add_all", "delete", "merge", "flush"}
#: Session methods that only read.
_SESSION_READS = {"get", "get_one", "scalar", "scalars", "query", "refresh"}
#: Helpers that write and read nothing first. Not `post_transaction`: it reads the accounts
#: before it inserts; nor `post_message`: a letter to the Owner first looks for the same one.
_WRITE_HELPERS = {"append_event", "append_event_with_outbox", "remember_command"}
_WRITE_SQL = ("update(", "insert(", "delete(", "UPDATE ", "INSERT ", "DELETE ")


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _session_names(block: ast.With) -> set[str]:
    """The names a `with … <session>.begin():` block opens its transaction on."""
    names: set[str] = set()
    for item in block.items:
        opened = item.context_expr
        if (
            isinstance(opened, ast.Call)
            and isinstance(opened.func, ast.Attribute)
            and opened.func.attr == "begin"
            and isinstance(opened.func.value, ast.Name)
        ):
            names.add(opened.func.value.id)
    return names


def _on_session(call: ast.Call, names: set[str]) -> bool:
    """A method of the session, or any call the session is handed to."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in names:
            return True
    handed = [*call.args, *(keyword.value for keyword in call.keywords)]
    return any(isinstance(arg, ast.Name) and arg.id in names for arg in handed)


def _action(call: ast.Call, names: set[str]) -> str:
    """lock, write, read, or helper (it may read, and it may write)."""
    name = _call_name(call)
    func = call.func
    own = (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in names
    )
    if name in _LOCKS:
        return "lock"
    if own and name in _SESSION_WRITES:
        return "write"
    if own and name == "execute":
        return "write" if any(word in ast.unparse(call) for word in _WRITE_SQL) else "read"
    if own and name in _SESSION_READS:
        return "read"
    if name in _WRITE_HELPERS:
        return "write"
    return "helper"


def _always_runs(node: ast.AST, block: ast.With) -> bool:
    """The node runs whenever the transaction does: no branch, loop or short-circuit stands
    between it and the block (an `if` test always runs, its body may not). 2026-10-09: the
    stills gate took the lock only `if rewriting:`, so the plain gate stayed unlocked while a
    reader that saw `lock_for_write` first called it locked."""
    parents = {
        id(child): parent for parent in ast.walk(block) for child in ast.iter_child_nodes(parent)
    }
    child: ast.AST = node
    while (parent := parents.get(id(child))) is not None and parent is not block:
        if isinstance(parent, ast.If | ast.While | ast.IfExp) and child is not parent.test:
            return False
        if isinstance(parent, ast.For | ast.AsyncFor) and child is not parent.iter:
            return False
        if isinstance(parent, ast.BoolOp) and child is not parent.values[0]:
            return False
        if isinstance(parent, ast.Try) and any(child is other for other in parent.orelse):
            return False
        if isinstance(
            parent,
            ast.ExceptHandler
            | ast.Match
            | ast.Lambda
            | ast.ListComp
            | ast.SetComp
            | ast.DictComp
            | ast.GeneratorExp,
        ):
            return False
        child = parent
    return True


def _actions(block: ast.With) -> list[tuple[str, ast.AST]]:
    """The transaction's actions in evaluation order: an inner call ends before the call it is
    an argument of, and a statement ends before the next one starts."""
    names = _session_names(block)
    found: list[tuple[int, int, str, ast.AST]] = []
    for statement in block.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and _on_session(node, names):
                kind = _action(node, names)
            elif isinstance(node, ast.Assign | ast.AugAssign) and any(
                isinstance(target, ast.Attribute)
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            ):
                kind = "write"  # a loaded row changed in memory: written at the flush
            else:
                continue
            found.append((node.end_lineno or 0, node.end_col_offset or 0, kind, node))
    return [(kind, node) for _, _, kind, node in sorted(found, key=lambda item: item[:2])]


def _transactions(tree: ast.AST) -> Iterator[tuple[str, ast.With]]:
    """(innermost function, block) for every `… .begin()` transaction in the module."""

    def visit(node: ast.AST, owner: str) -> Iterator[tuple[str, ast.With]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from visit(child, child.name)
                continue
            if isinstance(child, ast.With) and _session_names(child):
                yield owner, child
            yield from visit(child, owner)

    yield from visit(tree, "<module>")


def _unlocked_reads_then_writes(module: Path) -> dict[str, int]:
    """Function name -> line of its first transaction that may read before it writes and does
    not take the lock first, whatever branch it runs."""
    found: dict[str, int] = {}
    for owner, block in _transactions(ast.parse(module.read_text(encoding="utf-8"))):
        actions = _actions(block)
        for index, (kind, node) in enumerate(actions):
            if kind in ("lock", "write"):
                if _always_runs(node, block):
                    break  # a writer from here on, before anything was read
                continue  # a lock or write that may not run protects nothing
            # The first read. Unless everything from here on only reads, it is read-then-write
            # (a helper may itself read and then write; a lock taken now is a write refused).
            if any(later != "read" for later, _ in actions[index:]):
                found.setdefault(owner, block.lineno)
            break
    return found


#: backend/app, the package every module below is read from.
_APP = Path(economy_services.__file__).resolve().parents[1]


def _app_module(relative: str) -> Path:
    return _APP / relative


#: The books and the queue: WP2's own modules. Every read-then-write here takes the lock first.
_OWN_MODULES = ("economy/services.py", "workflows/services.py")

#: Read-then-write transactions in WP2's modules that do not take the lock, each with why.
#: Fixing one means taking it off this list.
_UNLOCKED_ON_PURPOSE = {
    ("workflows/services.py", "transition_workflow"): (
        "the Owner's pause/resume/cancel of a generic workflow: no purchase, no FILM_CONTINUE; "
        "refused, the press answers 500, nothing changed, and he presses again"
    ),
}


def test_the_paid_path_bookings_and_queue_writes_take_the_lock_first():
    for relative, names in (
        ("economy/services.py", {"record_provider_cost", "bill_provider_cost"}),
        (
            "workflows/services.py",
            {"enqueue_task", "retry_dead_letter_task", "set_job_active", "ensure_scheduled_job"},
        ),
    ):
        tree = ast.parse(_app_module(relative).read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if isinstance(function, ast.FunctionDef) and function.name in names:
                opened = [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.With)
                    and any("begin()" in ast.unparse(i.context_expr) for i in node.items)
                ]
                assert opened, function.name
                for node in opened:
                    first = ast.unparse(node.body[0])
                    assert first.startswith("lock_for_write("), (relative, function.name, first)
                names = names - {function.name}
        assert not names, f"{relative} no longer defines {sorted(names)}"


def test_every_read_then_write_in_the_books_and_the_queue_is_locked_or_says_why():
    found = {
        (relative, name): line
        for relative in _OWN_MODULES
        for name, line in _unlocked_reads_then_writes(_app_module(relative)).items()
    }

    unexplained = {key: line for key, line in found.items() if key not in _UNLOCKED_ON_PURPOSE}
    assert not unexplained, (
        "a transaction reads and then writes without `lock_for_write` as its first statement "
        f"(the 2026-10-09 14:17 loss): {unexplained}"
    )
    stale = set(_UNLOCKED_ON_PURPOSE) - set(found)
    assert not stale, f"locked now, take them off _UNLOCKED_ON_PURPOSE: {sorted(stale)}"


#: The rest of the paid path: the kernel's gate, the queue's worker and watchdog, the paid
#: steps, the daily run that starts them, the books' other writers.
_PAID_PATH_MODULES = (
    "services.py",
    "workflows/worker.py",
    "workflows/watchdog.py",
    "runbook/stages.py",
    "economy/budget.py",
    "economy/credits.py",
    "economy/accountant.py",
    "economy/prices.py",
    "media/stills_stage.py",
    "media/shooting_sheet.py",
    "media/assembler.py",
    "media/services.py",
    "media/balance_rule.py",
    "media/gpu_batch.py",
    "media/runpod_unsent.py",
    "media/film_close.py",
    "providers/runpod/batch.py",
    "providers/runpod/provider.py",
    "providers/runpod/gpu_guard.py",
    "providers/runpod/gpu_session.py",
    "providers/runpod/pods.py",
    # The Director's command module: WP11 routes a dead FILM_CONTINUE through its letters.
    "agents/command.py",
    # The cards: his paid questions and their answers are kept here.
    "decisions/services.py",
    # The prices a purchase teaches (review 2026-10-09: missed by the first sweep). The books
    # write the measured price BEFORE they book the render (`accountant.record_render_costs`),
    # the stills and motion stages after their purchase, and a shot's quote before it is bought.
    "media/production_policy.py",
    # The renders a vendor's refusal left RUNNING are failed here, after the purchase.
    "media/factory.py",
    # The day run's own records: SAFE MODE, and the letter that the day was interrupted.
    "runbook/services.py",
)

#: Where the paid path grows (review 2026-10-09: a hand-written list missed the directories P0
#: had just made for the repairs and the cards, so a new pass booking a render's credits without
#: the lock would have stayed green). Every file in them is read, today's and tomorrow's: the
#: watchdog's passes and the card producers (WP3, WP7, WP12, WP16, WP24), the books (WP7's
#: credits, WP23's close), the RunPod provider (WP3's `billing.py`).
_PAID_PATH_DIRECTORIES = (
    "workflows/passes",
    "decisions/producers",
    "economy",
    "providers/runpod",
)


def _paid_path_modules(app: Path) -> dict[str, Path]:
    """Relative name -> file, for every paid-path module that exists, WP2's own excepted (the
    books and the queue have their own, stricter test above). A listed module that is gone is
    left out: its slots then read as landed, and are named."""
    paths = {relative: app / relative for relative in _PAID_PATH_MODULES}
    for directory in _PAID_PATH_DIRECTORIES:
        for path in sorted((app / directory).glob("*.py")):
            paths.setdefault(path.relative_to(app).as_posix(), path)
    return {
        relative: path
        for relative, path in sorted(paths.items())
        if relative not in _OWN_MODULES and path.is_file()
    }


class SlotLanded(UserWarning):
    """A `_DEFERRED_ELSEWHERE` line whose transaction is locked (or gone) now."""


_GATE = "may_act reads his policy, then writes his question or spends his yes"
_LETTER = "the letter is lost (post_message first looks for the same open letter)"
#: `accountant.record_render_costs` measures the prices and sends the price letter first and
#: books the render's narration, still and motion rows (`_record_priced`) only after; none of
#: its callers (the sheet's assembly, the media router, the day's two render stages) catches
#: OperationalError. Proved by the xfail tests below.
_BEFORE_BOOKED = (
    "it runs inside accountant.record_render_costs BEFORE the render's costs are booked, so a "
    "refusal loses every cost row of the render and the next cap check reads too low a spend "
    "(the 14:17 loss by another route)"
)
_SETTING = (
    "not paid: his setting is read, then rewritten; refused, it answers 500 and he presses again"
)

#: The transactions on the paid path that WP2 (2026-10-09) could not lock because their files
#: belong to other lanes (audit plan, section 2), each with the lane that owes the slot and what
#: a refusal costs, and the ones read here as unproven that only read. The slot is always the
#: same: `lock_for_write(session)` as the first statement of the transaction. When a lane lands
#: one, its line here goes (a `SlotLanded` warning below names it; it never fails the suite).
_DEFERRED_ELSEWHERE = {
    # Read only: the reader cannot prove what a helper does, these were read by hand.
    ("services.py", "snapshot"): "read only: policy_view and last_task_per_agent only read",
    ("services.py", "read_events"): "read only: ledger_floor only reads",
    # Lane S (WP11 next).
    ("workflows/worker.py", "_tell_continue_interrupted"): (
        f"lane S: reads the Director, then writes «Continuarea … a fost întreruptă»; {_LETTER} "
        "and the task is already a dead letter"
    ),
    ("runbook/stages.py", "mode_refusal"): f"lane S: the daily run's gate; with ask_owner {_GATE}",
    ("runbook/stages.py", "_test_environment_letter"): f"lane S: {_LETTER}",
    ("runbook/stages.py", "_note_film_state"): "lane S: reads the film's state, then records it",
    ("runbook/stages.py", "_retire_film"): "lane S: reads the film, closes its books, writes",
    ("runbook/stages.py", "_qc_letter"): f"lane S: {_LETTER}",
    ("runbook/stages.py", "_publish_one"): "lane S: reads the publication, then remembers it",
    ("runbook/stages.py", "archive_stale_reports"): "lane S: reads the inbox, then resolves",
    ("agents/command.py", "prioritise_backlog"): "lane S: reads the topics, then reorders them",
    ("agents/command.py", "_assign"): (
        f"lane S: reads the role's agent, then writes its order; {_LETTER}"
    ),
    ("agents/command.py", "_escalate"): f"lane S: the escalation to the Owner; {_LETTER}",
    ("agents/command.py", "review_decision"): (
        "lane S: reads the Director's decision, then records its outcome"
    ),
    # Lane D.
    ("workflows/watchdog.py", "_fail_stuck_renders"): (
        "lane D: reads the RENDERING jobs, then fails them; refused, the next pass retries"
    ),
    ("decisions/services.py", "refresh_owner_decisions"): (
        "lane D: reads each card, then rewrites it; refused, the window shows a stale card"
    ),
    ("decisions/services.py", "reopen_unconfirmed_done"): (
        "lane D: reads the card, then reopens it"
    ),
    ("decisions/services.py", "_record_apply_error"): (
        "lane D: reads the card, then records why his answer did not apply"
    ),
    # Lane M (after the panels workflow).
    ("media/stills_stage.py", "run_stills_stage"): (
        f"lane M: the stills gate, {_GATE}; the lock is taken only `if rewriting:`, so the plain "
        "gate is still unlocked"
    ),
    ("media/shooting_sheet.py", "narration_gate"): f"lane M: the narration gate, {_GATE}",
    ("media/shooting_sheet.py", "set_scene_model"): "lane M: reads the scenes, then writes",
    ("media/shooting_sheet.py", "decide_sheet_take"): (
        "lane M: reads the takes, then supersedes the approved stills"
    ),
    ("media/shooting_sheet.py", "withdraw_stale_questions"): (
        "lane M: the kernel reads his open paid questions, then closes them"
    ),
    ("media/assembler.py", "run_motion_step"): f"lane M: the motion gate, {_GATE}",
    ("media/assembler.py", "_redo_still"): f"lane M: the one-scene redo gate, {_GATE}",
    ("media/assembler.py", "_accept_hero"): (
        "lane M: hero_gate reads before lock_for_write; move the lock above it"
    ),
    ("media/assembler.py", "book_film_spend"): (
        "lane M: reads the render job, then writes credits_measured"
    ),
    ("media/assembler.py", "assemble_video_job"): (
        "lane M: reads the board and scenes, then inserts the render job"
    ),
    ("media/assembler.py", "_fail_job"): (
        "lane M: reads the job, then writes the production_json its failed-render cost is "
        "booked from"
    ),
    ("media/assembler.py", "_lost_letter"): f"lane M: the lost-paid-work letter; {_LETTER}",
    # Found 2026-10-10 while WP10 was still writing it: lane M owes the lock before WP10 lands.
    ("media/assembler.py", "record_assembly_refused"): (
        "lane M (WP10): reads the film's scenes, then writes ASSEMBLY_REFUSED_EVENT inside the "
        "`except ClipsNotAccepted` of the pre-check, the render and the sheet; refused, the "
        "OperationalError replaces his refusal words (a 500) and nothing is recorded, so "
        "propose_clip_redos never proposes the longer motion redo"
    ),
    ("media/production_policy.py", "record_measured_price"): (
        f"lane M: reads the model's row, then writes the price a purchase measured; "
        f"{_BEFORE_BOOKED}; after a stills or motion purchase (credits.record_measured_prices) "
        "a refusal turns the step that bought into SpentStageError «s-a oprit după ce a cumpărat»"
    ),
    ("media/production_policy.py", "record_quoted_price"): (
        "lane M: reads the model's row, then writes the price the vendor quoted for a shot; "
        "a refusal fails the render in its motion loop, after the shots before it were bought"
    ),
    ("media/production_policy.py", "set_channel_policy"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "set_storyboard_production"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "set_voice_binding"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "set_identity_locks"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "propose_identity_change"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "approve_model_fallback"): f"lane M: {_SETTING}",
    ("media/production_policy.py", "decide_identity_change"): f"lane M: {_SETTING}",
    # No lane owns media/factory.py in the plan.
    ("media/factory.py", "abandon_unfinished_renders"): (
        "no lane: after a vendor's refusal, reads the film's unfinished renders, then fails "
        "them; refused, they stay RUNNING until the watchdog's _fail_stuck_renders"
    ),
    # Lane S.
    ("runbook/services.py", "clear_safe_mode"): (
        "lane S: his «ieși din modul sigur» reads the open record, then clears it; refused, "
        "it answers 500 and the studio stays in SAFE MODE, buying nothing"
    ),
    ("runbook/services.py", "tell_day_interrupted"): (
        f"lane S: the «ziua a fost întreruptă» letter; {_LETTER}"
    ),
    # No lane owns media/services.py in the plan.
    ("media/services.py", "generate_character_reference_set"): (
        "no lane: after the paid images, reads the bible, then writes the assets (its gate "
        "asks with ask_owner=False and writes nothing)"
    ),
    ("media/services.py", "seed_default_character_bibles"): "no lane: reads, then seeds",
    ("media/services.py", "generate_storyboard_from_script"): "no lane: reads, then writes",
    # Lane E (WP7 next).
    ("economy/budget.py", "set_budget"): (
        "lane E: locked only with a command id or an expected version; his budget sent with "
        "neither (the API allows it) reads and writes unlocked, and a refusal leaves his cap "
        "unset behind a 500"
    ),
    ("economy/credits.py", "record_credit_spend"): (
        "lane E: reads credit_usd and the job, then writes credits_measured and its event"
    ),
    ("economy/accountant.py", "_letter_each_time"): (
        f"lane E: the letter about money that went out; {_LETTER}"
    ),
    ("economy/accountant.py", "price_change_alert"): (
        f"lane E: the price letter reads the Accountant, then writes; {_BEFORE_BOOKED}"
    ),
    ("economy/accountant.py", "reconcile_day"): "lane E: the daily close (dormant)",
}


def _check_the_paid_path(app: Path = _APP) -> None:
    """A new unlocked read-then-write fails; a slot that landed is only named.

    The two are not symmetric on purpose (review 2026-10-09). A new unlocked transaction is the
    14:17 loss coming back, and must stop the merge. A slot landed is the owing lane doing what
    was asked, in a file it owns, without running this suite: failing here would punish the fix
    and turn the merge red although nothing regressed, so its line is named for deletion.
    """
    found = {
        (relative, name): line
        for relative, path in _paid_path_modules(app).items()
        for name, line in _unlocked_reads_then_writes(path).items()
    }

    unexplained = {key: line for key, line in found.items() if key not in _DEFERRED_ELSEWHERE}
    assert not unexplained, (
        "a paid-path transaction may read before it writes and does not take `lock_for_write` "
        f"first (the 2026-10-09 14:17 loss): {unexplained}. Lock it, or name it with its lane "
        "on _DEFERRED_ELSEWHERE."
    )
    for relative, name in sorted(set(_DEFERRED_ELSEWHERE) - set(found)):
        warnings.warn(
            SlotLanded(
                f"slot landed (locked or gone): {relative} {name}; "
                "delete its _DEFERRED_ELSEWHERE line"
            ),
            stacklevel=2,
        )


def test_every_read_then_write_on_the_paid_path_is_locked_or_owed_by_its_lane():
    _check_the_paid_path()


def test_a_repair_or_card_added_in_its_own_file_is_read_too(tmp_path):
    """Review 2026-10-09: P0 made `workflows/passes/` and `decisions/producers/` the place where
    repairs and cards register, and the lanes after it add files there. A pass that reads a
    render job and then books its credits without the lock is the 14:17 shape; it must fail
    this suite the day its file appears, not wait for someone to extend a list."""
    unlocked = (
        "def book(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        job = session.get(VideoRenderJob, 'film')\n"
        "        job.credits_measured = 1\n"
    )
    for directory, name in (
        ("workflows/passes", "credits_booked.py"),
        ("decisions/producers", "paid_question.py"),
        ("providers/runpod", "billing.py"),
        ("economy", "close.py"),
    ):
        app = tmp_path / directory.replace("/", "_")
        (app / directory).mkdir(parents=True)
        (app / directory / name).write_text(unlocked, encoding="utf-8")

        with pytest.raises(AssertionError, match=f"{directory}/{name}"):
            _check_the_paid_path(app)

    # And on the real tree, every file there is read today.
    scanned = set(_paid_path_modules(_APP))
    for directory in _PAID_PATH_DIRECTORIES:
        for path in (_APP / directory).glob("*.py"):
            relative = path.relative_to(_APP).as_posix()
            assert relative in scanned or relative in _OWN_MODULES, relative


def test_a_slot_another_lane_lands_is_reported_without_failing_this_suite(monkeypatch):
    """Review 2026-10-09: the lanes that owe these slots do not own this file, and run only the
    tests that import what they change. A slot landed exactly as asked must not turn this
    suite red at the merge; its line is named for the committing session to delete."""
    landed = ("media/assembler.py", "a_slot_another_lane_has_locked_meanwhile")
    monkeypatch.setitem(_DEFERRED_ELSEWHERE, landed, "lane M: landed")

    with pytest.warns(SlotLanded, match="a_slot_another_lane_has_locked_meanwhile"):
        _check_the_paid_path()


def test_the_source_reader_sees_every_shape_the_review_named(tmp_path):
    """The reader itself, on the shapes that broke or that the name-based reader misread."""
    module = tmp_path / "sample.py"
    module.write_text(
        "def unlocked(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        if session.scalar(select(Row)) is None:\n"
        "            session.add(Row())\n"
        "def locked(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        lock_for_write(session)\n"
        "        if session.scalar(select(Row)) is None:\n"
        "            session.add(Row())\n"
        "def decisions_lock(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        _lock(session)\n"
        "        session.add(Row(session.get(Row, 1)))\n"
        "def write_first(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        append_event(session, 'x', 'y', 'z', 1, {}, 'c')\n"
        "        session.get(Row, 1)\n"
        "def reads_only(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        session.get(Row, 1)\n"
        "        return session.scalars(select(Row)).all()\n"
        "def helper_then_insert(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        usd, fx = _convert_to_usd(session, 1)\n"
        "        session.add(Row(usd))\n"
        "def dict_get_then_insert(engine, payload):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        session.add(Row(payload.get('x')))\n"
        "def gate(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        verdict = may_act(session, 'media.stills_purchase')\n"
        "    return verdict\n"
        "def letter(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        director = agent_for_role(session, 'Director')\n"
        "        post_message(session, from_agent_id=director.id)\n"
        "def late_lock(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        hero_gate(session)\n"
        "        lock_for_write(session)\n"
        "        session.add(Row())\n"
        "def read_inside_a_write(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        append_event(session, 'x', 'y', 'z', 1, {'n': count(session)}, 'c')\n"
        "def post_first(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        post_transaction(session, [])\n"
        "def row_changed(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        job = session.get(Row, 1)\n"
        "        job.active = False\n"
        "def outer(engine):\n"
        "    def inner():\n"
        "        with Session(engine) as s, s.begin():\n"
        "            s.get(Row, 1).status = 'x'\n"
        "    return inner\n"
        "def lock_only_when_rewriting(engine, rewriting):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        if rewriting:\n"
        "            lock_for_write(session)\n"
        "        verdict = may_act(session, 'media.stills_purchase')\n"
        "def write_only_sometimes(engine, warn):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        if warn:\n"
        "            append_event(session, 'x', 'y', 'z', 1, {}, 'c')\n"
        "        session.get(Row, 1).status = 'x'\n"
        "def lock_in_a_try(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        try:\n"
        "            lock_for_write(session)\n"
        "            session.add(Row(session.get(Row, 1)))\n"
        "        finally:\n"
        "            pass\n"
        "def read_in_the_test_then_write(engine):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        if session.get(Row, 1) is None:\n"
        "            session.add(Row())\n"
        "def writes_in_a_loop(engine, rows):\n"
        "    with Session(engine) as session, session.begin():\n"
        "        for row in rows:\n"
        "            append_event(session, 'x', 'y', row, 1, {}, 'c')\n",
        encoding="utf-8",
    )

    assert set(_unlocked_reads_then_writes(module)) == {
        "unlocked",
        "helper_then_insert",
        "gate",
        "letter",
        "late_lock",
        "read_inside_a_write",
        "post_first",
        "row_changed",
        "inner",
        "lock_only_when_rewriting",
        "write_only_sometimes",
        "read_in_the_test_then_write",
    }
