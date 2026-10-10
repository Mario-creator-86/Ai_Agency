"""Cards register from their own files (2026-10-09, P0).

The Owner's rule of 2026-10-09: every correction leaves the studio unable to repeat the
mistake, or able to notice and repair it itself, asking him only for money, his accounts or
his choices, through a card. About fifteen packages of that plan add a card, and each card
needs an applier (what his accept runs) and a condition (what the studio reads to close it)
in the decisions core. The core had `register_applier` and nothing called it; there was no
`register_condition`. Now a module of `app.decisions.producers` registers its own, and the
core imports the package the first time one of its tables is read.

What is proven here, with every provider faked and no network: a producer module dropped in
the package registers an applier and a condition, a card that uses them is proposed, his
accept applies it through the registered applier, his «Am făcut-o» gets the registered
words while the condition is unmet and the condition closes the card when it reads true; an
unknown condition still reads UNREADABLE; a producer that fails to import is named and does
not stop the others; a second owner of a name is refused; and an accept whose applier is gone
keeps the card PENDING with the reason, never ACCEPTED with nothing applied.
"""

from __future__ import annotations

import ast
import importlib
import sys
import textwrap
from pathlib import Path
from uuid import uuid4

import app.decisions.producers as producers_package
import pytest
from app.decisions import services as decisions
from app.decisions.models import OwnerDecision
from app.decisions.producers import PRODUCERS
from app.decisions.services import (
    APPLIERS,
    CONDITIONS,
    MISSING_RO,
    DecideCommand,
    DecisionApplyFailed,
    DecisionInvalid,
    condition_reading,
    decide_owner_decision,
    propose_owner_decision,
    refresh_owner_decisions,
    register_applier,
    register_condition,
    still_missing_ro,
)
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session

PACKAGE = "app.decisions.producers"
PROBE_MODULE = f"{PACKAGE}.p0_probe"
#: The names the probe modules register; removed again after each test.
PROBE_KINDS = (
    "probe_apply",
    "probe_cleared",
    "probe_half_apply",
    "probe_half_cleared",
    "probe_sibling_apply",
    "probe_cross_apply",
    "probe_cross_cleared",
    "probe_caught_apply",
    "probe_caught_cleared",
    "probe_late_apply",
    "probe_late_cleared",
)

PROBE_SOURCE = textwrap.dedent(
    '''
    """A producer, as a package of the self-repair plan writes one."""

    from pathlib import Path

    from app.decisions.services import register_applier, register_condition

    CALLS = []


    def apply_probe(engine, spec, inner, words):
        CALLS.append({"value": spec.get("value"), "inner": inner, "title": words["title_ro"]})
        return {"command": "ProbeCommand", "result": {"value": spec.get("value")}, "event_id": None}


    def probe_cleared(session, row, params, settings):
        return Path(str(params["flag"])).is_file()


    register_applier("probe_apply", apply_probe)
    register_condition(
        "probe_cleared", probe_cleared, missing_ro="Lipsește: proba nu este încă gata."
    )
    '''
)

MISSING_PROBE_RO = "Lipsește: proba nu este încă gata."


@pytest.fixture
def producer_folder(tmp_path):
    """One more folder of `app.decisions.producers`, read on the next first read; the
    package, its tables and the loader are put back afterwards."""
    folder = tmp_path / "producers_extra"
    folder.mkdir()
    original_path = list(producers_package.__path__)
    producers_package.__path__[:] = [*original_path, str(folder)]
    PRODUCERS.reset()
    importlib.invalidate_caches()
    try:
        yield folder
    finally:
        producers_package.__path__[:] = original_path
        for name in [n for n in sys.modules if n.startswith(f"{PACKAGE}.p0_")]:
            del sys.modules[name]
        for table in (APPLIERS, CONDITIONS, MISSING_RO):
            for kind in PROBE_KINDS:
                dict.pop(table, kind, None)
        PRODUCERS.reset()
        importlib.invalidate_caches()


def _write(folder: Path, name: str, source: str) -> None:
    (folder / f"{name}.py").write_text(source, encoding="utf-8")


def _probe_calls() -> list[dict]:
    return sys.modules[PROBE_MODULE].CALLS


def _propose(engine, *, options, clears_when=None, key: str | None = None) -> tuple[str, int]:
    with Session(engine) as session, session.begin():
        row = propose_owner_decision(
            session,
            kind="probe",
            dedupe_key=key or f"probe:{uuid4()}",
            title_ro="O întrebare de probă",
            why_ro="Proba registrului.",
            effect_ro="Nimic plătit.",
            options=options,
            clears_when=clears_when,
            source="test",
        )
        return row.id, row.version


def _row(engine, decision_id: str) -> OwnerDecision:
    with Session(engine) as session:
        row = session.get(OwnerDecision, decision_id)
        assert row is not None
        session.expunge(row)
        return row


def _answer(engine, decision_id: str, version: int, decision: str, option_key=None):
    command = DecideCommand(
        command_id=uuid4(), expected_version=version, decision=decision, option_key=option_key
    )
    return decide_owner_decision(engine, decision_id, command, issued_by="owner")


GUIDED = {
    "key": "do",
    "label_ro": "O fac eu",
    "effect_ro": "O faci tu.",
    "recommended": True,
    "apply": {"type": "guided", "place_ro": "Setări", "steps_ro": "Fă proba."},
}


# ------------------------------------------------------------------ a producer module


def test_a_producer_module_registers_an_applier_and_his_accept_runs_it(engine, producer_folder):
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    # Nothing names the module anywhere: the first read of the table imports it.
    assert "probe_apply" in APPLIERS
    assert PROBE_MODULE in PRODUCERS.loaded and PRODUCERS.errors == {}

    decision_id, version = _propose(
        engine,
        options=[
            {
                "key": "go",
                "label_ro": "Da",
                "effect_ro": "Rulează proba.",
                "recommended": True,
                "apply": {"type": "probe_apply", "value": 7},
            },
            {"key": "keep", "label_ro": "Nu", "apply": {"type": "none"}},
        ],
    )
    result = _answer(engine, decision_id, version, "ACCEPT")

    assert result["decision"]["status"] == "ACCEPTED"
    (call,) = _probe_calls()
    assert call["value"] == 7 and call["title"] == "O întrebare de probă"
    # His own command ran under the id derived from the card, so a retried answer is one apply.
    assert call["inner"] == decisions._inner_command_id(decision_id, version, "go")
    row = _row(engine, decision_id)
    assert row.applied["type"] == "probe_apply"
    assert row.applied["command"] == "ProbeCommand"
    assert row.chosen_option == "go" and row.decided_by == "owner"


def test_a_registered_condition_words_his_done_and_closes_the_card(
    engine, producer_folder, tmp_path
):
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    flag = tmp_path / "flag.txt"
    decision_id, version = _propose(
        engine, options=[GUIDED], clears_when={"type": "probe_cleared", "flag": str(flag)}
    )
    _answer(engine, decision_id, version, "ACCEPT")
    waiting = _row(engine, decision_id)
    assert waiting.status == "WAITING_FOR_OWNER_ACTION"

    # His DONE while the condition reads false: the card stays and says what is missing, in
    # the words the producer registered.
    _answer(engine, decision_id, waiting.version, "DONE")
    still = _row(engine, decision_id)
    assert still.status == "WAITING_FOR_OWNER_ACTION"
    assert MISSING_PROBE_RO in (still.apply_error_ro or "")

    # The condition reads true: the studio closes it itself.
    flag.write_text("gata", encoding="utf-8")
    assert refresh_owner_decisions(engine)["completed"] >= 1
    done = _row(engine, decision_id)
    assert done.status == "ACCEPTED" and done.applied["completed_by"] == "condition"


def test_every_registered_condition_says_what_is_missing(producer_folder):
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    readable = set(CONDITIONS) - {"never"}
    assert "probe_cleared" in readable
    assert readable <= set(MISSING_RO), readable - set(MISSING_RO)
    with pytest.raises(ValueError, match="missing"):
        register_condition("probe_cleared", lambda *a: True, missing_ro="")


# ------------------------------------------------------------- what still fails closed


def test_an_unknown_condition_still_reads_unreadable(engine):
    row = OwnerDecision(
        id=str(uuid4()),
        kind="probe",
        clears_when={"type": "no_such_condition"},
        created_at="2026-10-09T00:00:00+00:00",
    )
    with Session(engine) as session:
        assert condition_reading(session, row) == "UNREADABLE"
        assert still_missing_ro(session, row, "UNREADABLE") == decisions.UNREADABLE_RO
    # And a card cannot be proposed with one.
    with pytest.raises(DecisionInvalid, match="no_such_condition"):
        _propose(engine, options=[GUIDED], clears_when={"type": "no_such_condition"})


def test_a_card_whose_condition_producer_is_gone_stays_open(engine, producer_folder, tmp_path):
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    flag = tmp_path / "flag.txt"
    flag.write_text("gata", encoding="utf-8")
    decision_id, _version = _propose(
        engine, options=[GUIDED], clears_when={"type": "probe_cleared", "flag": str(flag)}
    )
    # After a restart the producer did not import: its condition is not registered.
    dict.pop(CONDITIONS, "probe_cleared")
    with Session(engine) as session:
        assert condition_reading(session, _row(engine, decision_id)) == "UNREADABLE"
    refresh_owner_decisions(engine)
    assert _row(engine, decision_id).status == "PENDING"


def test_an_accept_whose_applier_is_gone_keeps_the_card_pending(engine, producer_folder):
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    decision_id, version = _propose(
        engine,
        options=[
            {
                "key": "go",
                "label_ro": "Da",
                "recommended": True,
                "apply": {"type": "probe_apply", "value": 1},
            }
        ],
    )
    # Before 2026-10-09 an option whose type nothing could apply was recorded as «none»:
    # ACCEPTED, with nothing run. Now the card stays and says why.
    dict.pop(APPLIERS, "probe_apply")
    with pytest.raises(DecisionApplyFailed, match="probe_apply"):
        _answer(engine, decision_id, version, "ACCEPT")
    row = _row(engine, decision_id)
    assert row.status == "PENDING" and row.version == version
    assert "nu s-a aplicat nimic" in (row.apply_error_ro or "")
    assert _probe_calls() == []
    with Session(engine) as session:
        failed = session.scalars(
            select(DomainEvent).where(
                DomainEvent.aggregate_id == decision_id,
                DomainEvent.event_type == "owner.decision_apply_failed",
            )
        ).all()
    assert len(failed) == 1 and failed[0].payload["option"] == "go"


def test_a_producer_that_fails_to_import_is_named_and_the_others_still_load(producer_folder):
    # Sorted by name, the broken module is imported before the probe.
    _write(producer_folder, "p0_broken", 'raise RuntimeError("stricat intenționat")\n')
    _write(producer_folder, "p0_probe", PROBE_SOURCE)
    assert "probe_apply" in APPLIERS
    assert set(PRODUCERS.errors) == {f"{PACKAGE}.p0_broken"}
    assert "stricat intenționat" in PRODUCERS.errors[f"{PACKAGE}.p0_broken"]
    assert PROBE_MODULE in PRODUCERS.loaded


HALF_SOURCE = textwrap.dedent(
    """
    from app.decisions.services import register_applier, register_condition


    def apply_half(engine, spec, inner, words):
        raise AssertionError("a producer that failed to import must not apply")


    register_applier("probe_half_apply", apply_half)
    register_condition("probe_half_cleared", lambda *a: True, missing_ro="Lipsește: proba.")
    # A name another producer (here the core) already owns: the import fails here.
    register_condition("commercial_use", lambda *a: True, missing_ro="Lipsește: altceva.")
    """
)


def test_a_producer_that_fails_after_registering_leaves_nothing_behind(producer_folder):
    """Its applier would run his accept and its condition close cards while the module is
    named as not loaded; and a card naming a condition that collided must read the owner's
    condition, never the failed module's."""
    original_condition = dict.__getitem__(CONDITIONS, "commercial_use")
    original_words = dict.__getitem__(MISSING_RO, "commercial_use")
    _write(producer_folder, "p0_half", HALF_SOURCE)

    assert "probe_half_apply" not in APPLIERS
    assert f"{PACKAGE}.p0_half" in PRODUCERS.errors
    assert "already registered" in PRODUCERS.errors[f"{PACKAGE}.p0_half"]
    assert "probe_half_cleared" not in CONDITIONS and "probe_half_cleared" not in MISSING_RO
    assert CONDITIONS["commercial_use"] is original_condition
    assert MISSING_RO["commercial_use"] is original_words


def test_a_sibling_a_failed_producer_imported_still_registers_on_its_own_turn(producer_folder):
    """`p0_a` imports its sibling `p0_z` and then fails: what `p0_z` registered during that
    import is undone with `p0_a`, and `p0_z` is imported again in its own turn, so it is
    registered and named as loaded (not left as a cached module whose entries are gone)."""
    _write(
        producer_folder,
        "p0_z_sibling",
        "from app.decisions.services import register_applier\n"
        "def apply_sibling(engine, spec, inner, words):\n"
        "    return {'command': 'Sibling'}\n"
        "register_applier('probe_sibling_apply', apply_sibling)\n",
    )
    _write(
        producer_folder,
        "p0_a_importer",
        f"import {PACKAGE}.p0_z_sibling\nraise RuntimeError('stricat după import')\n",
    )

    assert "probe_sibling_apply" in APPLIERS
    assert set(PRODUCERS.errors) == {f"{PACKAGE}.p0_a_importer"}
    assert f"{PACKAGE}.p0_z_sibling" in PRODUCERS.loaded
    assert APPLIERS["probe_sibling_apply"].__module__ == f"{PACKAGE}.p0_z_sibling"


BROKEN_AFTER_REGISTERING = textwrap.dedent(
    """
    from app.decisions.services import register_applier, register_condition


    def apply_{kind}(engine, spec, inner, words):
        raise AssertionError("a producer that failed to import must not apply")


    def {kind}_cleared(session, row, params, settings):
        return True


    register_applier("probe_{kind}_apply", apply_{kind})
    register_condition(
        "probe_{kind}_cleared", {kind}_cleared, missing_ro="Lipsește: proba."
    )
    raise RuntimeError("stricat după înregistrare")
    """
)


def _broken_producer(kind: str) -> str:
    return BROKEN_AFTER_REGISTERING.replace("{kind}", kind)


def test_a_broken_producer_a_pass_imported_first_leaves_nothing_behind(producer_folder, tmp_path):
    """Review of 2026-10-09: what a module registered was undone only when its own loader was
    importing it. A pass module importing a producer at its top imports it first, during the
    passes' load: the producer's applier was recorded nowhere, its own turn later found «the
    same function» already there, and after both failed imports his accept could still run it
    while the studio named the module as not loaded."""
    import app.workflows.passes as passes_package
    from app.workflows.passes import PASSES, registered_passes

    _write(producer_folder, "p0_cross", _broken_producer("cross"))
    pass_folder = tmp_path / "passes_cross"
    pass_folder.mkdir()
    (pass_folder / "p0_cross_pass.py").write_text(
        f"from {PACKAGE}.p0_cross import apply_cross  # noqa: F401\n"
        "from app.workflows.passes import watchdog_pass\n\n\n"
        '@watchdog_pass("p0_cross_pass", order=1)\n'
        "def cross(context):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    original_path = list(passes_package.__path__)
    passes_package.__path__[:] = [*original_path, str(pass_folder)]
    PASSES.reset()
    importlib.invalidate_caches()
    try:
        # The watchdog's own order: its passes first, then the producers' report.
        assert "p0_cross_pass" not in {entry.name for entry in registered_passes()}
        assert "app.workflows.passes.p0_cross_pass" in PASSES.errors
        PRODUCERS.load()
        assert f"{PACKAGE}.p0_cross" in PRODUCERS.errors
        assert "probe_cross_apply" not in APPLIERS
        assert "probe_cross_cleared" not in CONDITIONS
        assert "probe_cross_cleared" not in MISSING_RO
    finally:
        passes_package.__path__[:] = original_path
        for name in [n for n in sys.modules if n.startswith("app.workflows.passes.p0_")]:
            del sys.modules[name]
        PASSES.reset()


def test_a_broken_producer_whose_error_a_sibling_caught_leaves_nothing_behind(producer_folder):
    """A sibling that catches a producer's import error loads fine: what the broken one
    registered meanwhile was counted as the sibling's, and kept when the sibling loaded."""
    _write(
        producer_folder,
        "p0_a_catcher",
        f"try:\n    import {PACKAGE}.p0_z_caught  # noqa: F401\nexcept Exception:\n    pass\n",
    )
    _write(producer_folder, "p0_z_caught", _broken_producer("caught"))

    assert "probe_caught_apply" not in APPLIERS
    assert f"{PACKAGE}.p0_a_catcher" in PRODUCERS.loaded
    assert set(PRODUCERS.errors) == {f"{PACKAGE}.p0_z_caught"}


def test_a_broken_producer_imported_after_the_load_is_not_applied(producer_folder):
    """The package already loaded; a module (a router, a media step) then imports a producer
    that fails after registering. No loader is running: the next read of the table still
    must not offer what it registered."""
    PRODUCERS.load()
    _write(producer_folder, "p0_late", _broken_producer("late"))
    importlib.invalidate_caches()
    with pytest.raises(RuntimeError, match="stricat"):
        importlib.import_module(f"{PACKAGE}.p0_late")
    assert dict.__contains__(APPLIERS, "probe_late_apply")  # what the failed import left
    assert "probe_late_apply" not in APPLIERS  # and what a read of the table sees
    assert not dict.__contains__(APPLIERS, "probe_late_apply")


def test_a_second_owner_of_a_name_is_refused(producer_folder):
    _write(
        producer_folder,
        "p0_dupe",
        "from app.decisions.services import register_applier\n"
        "def apply_other(engine, spec, inner, words):\n"
        "    raise AssertionError('never')\n"
        "register_applier('budget', apply_other)\n",
    )
    assert "budget" in APPLIERS
    assert "already registered" in PRODUCERS.errors[f"{PACKAGE}.p0_dupe"]
    assert APPLIERS["budget"] is decisions._apply_budget
    with pytest.raises(ValueError, match="plain option type"):
        register_applier("guided", decisions._apply_budget)
    with pytest.raises(ValueError, match="lower case"):
        register_applier("Close-Film", decisions._apply_budget)
    # The same function registered again (a module imported twice) is not a second owner.
    register_applier("budget", decisions._apply_budget)


# ---------------------------------------------------------------- the package as shipped


def test_the_shipped_producers_load_without_errors():
    PRODUCERS.load()
    assert PRODUCERS.done and PRODUCERS.errors == {}


def _producer_files() -> list[Path]:
    folder = Path(producers_package.__file__).parent
    return sorted(path for path in folder.glob("*.py") if path.name != "__init__.py")


def test_producers_import_media_and_providers_inside_their_functions():
    """A producer is imported from inside the decisions core, which media and providers
    import: at the module's top it may import the core, never media or providers."""
    for path in _producer_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                assert not name.startswith(("app.media", "app.providers")), (
                    f"{path.name}:{node.lineno} imports {name} at the top"
                )
