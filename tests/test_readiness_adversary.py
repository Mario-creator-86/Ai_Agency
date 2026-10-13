"""What an adversary found in the readiness phase, after the four parts had reported green.

Everything here was written against code that was already passing its own tests. The rule
each test attacks is named in its docstring, and the one that failed when it was first
written says what it measured before the fix.

Nothing here reaches a vendor, renders a frame, queues a day or opens `data/studio.db`: the
suite's own `no_network` fixture refuses a socket to anything but loopback, and every engine
comes from the `engine` fixture's temporary file.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from app.agents.services import seed_initial_workforce
from app.economy.budget import spend_since
from app.economy.models import ProviderCostRecord, ProviderReconciliation
from app.economy.services import (
    ReconciliationCommand,
    reconcile_provider_invoice,
    record_provider_cost,
    seed_chart_of_accounts,
    treasury_snapshot,
    trial_balance,
)
from app.integrations.vault import CredentialVault
from app.media.services import _character_keys, _characters_named_in
from app.models import DomainEvent, OwnerPolicy
from app.runbook.preflight import BLOCKING, run_preflight
from sqlalchemy import func, select
from sqlalchemy.orm import Session

DAY = "2026-09-18"
START = f"{DAY}T00:00:00+00:00"
END = "2026-09-19T00:00:00+00:00"


# ---------------------------------------------------------------------------
# A reconciliation counts each thing once, however many times it is corrected
# ---------------------------------------------------------------------------


def _estimate(engine, reference: str, amount: str, at: str) -> dict:
    view = record_provider_cost(
        engine,
        provider="runway",
        external_reference=reference,
        status="ESTIMATED",
        amount=amount,
        attribution={},
    )
    with Session(engine) as session, session.begin():
        session.get(ProviderCostRecord, view["id"]).recorded_at = at
    return view


def _invoice(engine, reference: str, amount: str, **kw) -> dict:
    return reconcile_provider_invoice(
        engine,
        ReconciliationCommand(
            command_id=uuid4(),
            provider="runway",
            external_reference=reference,
            amount=amount,
            scope="PERIOD",
            period_start=START,
            period_end=END,
            **kw,
        ),
    )


def test_a_second_correction_does_not_read_the_first_bill_as_an_estimate_it_replaced(engine):
    """A correction of a correction must still say what the studio had estimated.

    Measured before the fix: version 2's own BILLED row carried `reconciled_by_id` pointing
    at version 2, so version 3 re-adopted it as though it were one of the studio's estimates.
    One estimate of 5.00 and a first bill of 5.50 came back to the Owner as 10.50 of estimates
    covered, with `difference_vr` at -6.50 — a figure about nothing that ever happened. The
    money was right throughout; the sentence about it was not, and a book that reports what it
    did not measure is the one thing the reconciliation exists to stop.
    """
    seed_chart_of_accounts(engine)
    _estimate(engine, "render:v:scene:1:motion", "5.00", f"{DAY}T10:00:00+00:00")

    first = _invoice(engine, "RW-c1", "5.50")
    assert first["version"] == 1 and first["matched"] == 1 and first["matched_vr"] == "5"

    second = _invoice(engine, "RW-c2", "4.00", expected_version=1)
    assert second["version"] == 2 and second["matched"] == 1 and second["matched_vr"] == "5"

    third = _invoice(engine, "RW-c3", "4.25", expected_version=2)

    assert third["version"] == 3
    assert third["matched"] == 1, "one estimate was ever written; a bill is not an estimate"
    assert third["matched_vr"] == "5"
    assert third["difference_vr"] == "-0.75", "what the vendor charged under the studio's guess"
    assert third["unmatched"] == [], "a superseded bill is neither matched nor a finding"

    # And the money is the third figure, once, with the books closed and the chain reversed.
    with Session(engine) as session:
        assert spend_since(session, START)["spent_usd"] == "4.25"
        rows = {r.external_reference: r for r in session.scalars(select(ProviderCostRecord))}
        assert rows["RW-c1"].reconciled_at and rows["RW-c2"].reconciled_at
        assert rows["RW-c3"].reconciled_at is None
        active = session.scalars(
            select(ProviderReconciliation).where(ProviderReconciliation.active.is_(True))
        ).all()
        assert [row.external_reference for row in active] == ["RW-c3"]
    assert trial_balance(engine)["balanced"] is True
    assert treasury_snapshot(engine)["spendable"]["amount"] == "-4.25"


# ---------------------------------------------------------------------------
# A preflight measures the studio and changes nothing about it
# ---------------------------------------------------------------------------


def test_the_preflight_writes_nothing_however_many_times_it_is_read(engine, settings, tmp_path):
    """A check that changed the thing it measured would make the second reading a fiction.

    The five checks added this phase read a budget, a price table, the capability rows, the
    Character Bible and a channel — every one of them through a session that could write. The
    preflight is also the first stage of the day and the Owner's own page, so it runs many
    times an hour: it must leave the same ledger, the same rows and the same verdict behind.
    """
    vault = CredentialVault(tmp_path / "adversary.credentials.key")
    seed_initial_workforce(engine)
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"

    def state() -> tuple[int, int, str | None]:
        with Session(engine) as session:
            return (
                int(session.scalar(select(func.count()).select_from(DomainEvent)) or 0),
                int(session.scalar(select(func.count()).select_from(ProviderCostRecord)) or 0),
                session.scalar(select(DomainEvent.event_id).order_by(DomainEvent.sequence.desc())),
            )

    before = state()
    first = run_preflight(engine, settings, vault)
    after_one = state()
    second = run_preflight(engine, settings, vault)

    assert before == after_one == state(), "the preflight wrote something while reading"
    assert first["status"] == second["status"]
    assert first["blocking_failures"] == second["blocking_failures"]
    assert first["degrading_failures"] == second["degrading_failures"]


def test_no_check_the_readiness_phase_added_can_ever_stop_a_day(engine, settings, tmp_path):
    """The verdict is BLOCKED on BLOCKING alone, and none of the five carries that severity.

    Held structurally rather than by the five happening to pass: the Owner's own answers —
    no budget while the studio is in TEST, no serial channel — must be lines he reads, and a
    check that refused the day over one of them would be asking him to repair his own choice.
    """
    vault = CredentialVault(tmp_path / "adversary-two.credentials.key")
    seed_initial_workforce(engine)
    settings.ffmpeg_path = "ffmpeg-test-stub"
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    result = run_preflight(engine, settings, vault)

    added = {
        "spending_budget",
        "model_prices",
        "vision_capability",
        "character_references",
        "serial_channel",
    }
    by_name = {check["name"]: check for check in result["checks"]}
    assert added <= set(by_name)
    assert all(by_name[name]["severity"] != BLOCKING for name in added)
    assert not (added & set(result["blocking_failures"]))
    # Four of the five are failing here — nothing is configured — and the only thing that
    # stops this studio is the one that stopped it before the phase: no provider is verified.
    assert not by_name["spending_budget"]["ok"] and not by_name["model_prices"]["ok"]
    assert not by_name["vision_capability"]["ok"] and not by_name["serial_channel"]["ok"]
    assert result["blocking_failures"] == ["llm_provider"]


# ---------------------------------------------------------------------------
# A cast is read from the film, never invented
# ---------------------------------------------------------------------------


def test_a_name_spelled_in_lower_case_puts_nobody_on_screen(engine):
    """A proper noun is capitalised; a common word that happens to spell one is not a person.

    The rule is stated where the matcher is written; this holds it, because the day it stops
    holding, a factual script about a lyre or about a kayak would put an employee in the cast
    and the character gate would compare a still against a bible nobody asked for.
    """
    keys = {
        "lyra": _character_keys("Lyra Voice Artist"),
        "kael": _character_keys("Kael Video Editor"),
    }

    assert _characters_named_in("a lyra of seven strings, played slowly", keys) == []
    assert _characters_named_in("the kael of the old maps", keys) == []
    assert _characters_named_in("Lyra reads the line aloud", keys) == ["lyra"]


# ---------------------------------------------------------------------------
# No money moves on anything but the Owner's own hand
# ---------------------------------------------------------------------------


def test_nothing_the_studio_runs_for_itself_ever_writes_a_billed_cost_row():
    """Every cost the studio writes for itself is an estimate; only his invoice is money.

    Read from the source rather than from one run, because the rule is about every path at
    once: `record_provider_cost` is called inside the application in the Accountant's costing
    of a render and in the character reference set, and both must pass ESTIMATED. The two
    places a BILLED row is written — `bill_provider_cost` and `reconcile_provider_invoice` —
    are reachable only through the economy router, which the Owner's token guards. A day that
    billed itself would move real money on a figure no invoice had confirmed.
    """
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    sources = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    }
    callers = {
        name: text
        for name, text in sources.items()
        if "record_provider_cost(" in text and name not in ("economy/services.py",)
    }
    assert callers, "the costing call moved; this test has stopped measuring anything"
    for name in sorted(set(callers) - {"economy/router.py"}):
        lines = callers[name].splitlines()
        for index, line in enumerate(lines):
            if "record_provider_cost(" not in line:
                continue
            window = "\n".join(lines[index : index + 14])
            assert 'status="ESTIMATED"' in window, (
                f"{name} line {index + 1} records a cost without saying it is an estimate"
            )
