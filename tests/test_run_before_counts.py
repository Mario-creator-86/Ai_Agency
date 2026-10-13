"""A run stored before the counts existed says so, instead of being counted from keys it never had.

Measured on a copy of the Owner's studio (2026-09-25): all 18 stored runs are of 2026-09-12 and
none of their stages carries ``produced``. The runs list recounted them from today's artefact
keys, which those runs never wrote — their media stage returned ``rendered``, not ``assets``;
their ideas ``pool``, not ``proposed`` — and so the headline said «Fără rezultat: «producție
media»» of a day that rendered, and «Ziua nu a produs nimic» of days the page's own stage rows
called «nenumărat». Two readings of one day, and the headline's was invented.

A stored run is now «counted» only when its stages carry the count they were run with. One
that does not is summarised by what the record does hold — which stages ran to their end, which
failed, which were blocked, and a film the legacy publish artefact names — opens with «Rulare
dinainte de numărătoare», has no ``stages_productive`` (None, never 0) and carries the code
``before_counts``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.runbook.models import DailyRun
from app.runbook.services import (
    SUMMARY_BEFORE_COUNTS,
    SUMMARY_COUNTED,
    list_runs,
    produced_by,
    run_summary,
    stored_summary,
)
from app.services import utc_now
from sqlalchemy.orm import Session

#: The shape of the Owner's 12.09 runs: every stage COMPLETED, artefacts under the keys the
#: runners returned then, and no ``produced`` anywhere.
OLD_DAY: list[dict[str, Any]] = [
    {"stage": "preflight", "status": "COMPLETED", "artefacts": {"status": "READY"}},
    {"stage": "performance_intake", "status": "COMPLETED", "artefacts": {"measured": 0}},
    {"stage": "idea_generation", "status": "COMPLETED", "artefacts": {"pool": 6}},
    {"stage": "research_and_verification", "status": "COMPLETED", "artefacts": {"claims": 4}},
    {"stage": "selection", "status": "COMPLETED", "artefacts": {"candidates": 3}},
    {"stage": "script_and_storyboard", "status": "COMPLETED", "artefacts": {"scripts": 1}},
    {"stage": "media", "status": "COMPLETED", "artefacts": {"rendered": 1}},
    {"stage": "edit_and_qc", "status": "COMPLETED", "artefacts": {"checked": 1}},
    {"stage": "publish", "status": "COMPLETED", "artefacts": {}},
    {"stage": "post_run", "status": "COMPLETED", "artefacts": {"reports": 10}},
    {"stage": "daily_log", "status": "COMPLETED", "artefacts": {"log_id": "x"}},
    {"stage": "serial_queue", "status": "COMPLETED", "artefacts": {"episodes": []}},
]


def _failed_old_day() -> list[dict[str, Any]]:
    stages = [dict(s) for s in OLD_DAY[:3]]
    stages.append({"stage": "research_and_verification", "status": "FAILED", "artefacts": {}})
    for name in ("selection", "script_and_storyboard", "media", "edit_and_qc", "publish"):
        stages.append({"stage": name, "status": "BLOCKED", "artefacts": {}})
    return stages


def test_an_old_run_says_it_was_not_counted_and_claims_no_count() -> None:
    told = stored_summary(OLD_DAY)
    assert told["summary_code"] == SUMMARY_BEFORE_COUNTS == "before_counts"
    assert told["stages_productive"] is None
    summary = told["summary"]
    assert summary.startswith("Rulare dinainte de numărătoare: ")
    assert "10 din 10 etape de lucru au rulat până la capăt" in summary
    # W35: «etape de lucru», because the page counts every stage beside it («12/12 etape
    # încheiate», the preflight and the day's log included): «10 din 10 etape» read as a
    # contradiction.
    assert " etape au rulat" not in summary
    assert "nu s-a numărat" in summary
    # Nothing the record never held: no stage called idle, no day called empty.
    for invented in ("Fără rezultat", "nu a produs nimic", "produs ceva", "Niciun film publicat"):
        assert invented not in summary, invented
    # It is not the day it is read on.
    assert "azi" not in summary.split()


def test_an_old_run_still_names_what_failed_and_what_was_blocked() -> None:
    summary = stored_summary(_failed_old_day())["summary"]
    assert summary.startswith("Rulare dinainte de numărătoare: ")
    assert "2 din 8 etape de lucru au rulat până la capăt" in summary
    assert "Eșuată: «documentare și verificare»." in summary
    assert "Blocate: «alegerea subiectului»" in summary


def test_one_stage_that_ran_is_said_in_the_singular() -> None:
    stages = [{"stage": "idea_generation", "status": "COMPLETED", "artefacts": {"pool": 6}}]
    assert "1 din 1 etape de lucru a rulat până la capăt" in stored_summary(stages)["summary"]


def test_an_old_run_keeps_the_film_its_legacy_publish_artefact_names() -> None:
    """The one count an old record can give truthfully: the publication it names by id."""
    published = {"publication_id": "0000010e", "publication_status": "PUBLISHED"}
    stages = [*OLD_DAY[:8], {"stage": "publish", "status": "COMPLETED", "artefacts": published}]
    assert produced_by(stages[-1]) == 1
    summary = stored_summary(stages)["summary"]
    assert summary.endswith("Filme publicate: 1.")
    assert stored_summary(stages)["stages_productive"] is None


def test_a_counted_run_reads_back_exactly_as_it_was_written() -> None:
    counted = [{**s, "produced": produced_by(s)} for s in OLD_DAY]
    told = stored_summary(counted)
    assert told["summary_code"] == SUMMARY_COUNTED == "counted"
    summary, productive = run_summary(counted)
    assert told["summary"] == summary and told["stages_productive"] == productive
    assert "Rulare dinainte de numărătoare" not in summary


def test_a_run_with_one_stage_missing_its_count_is_not_called_counted() -> None:
    """Half a count is no count: a headline over it would call the rest idle."""
    stages = [{**s, "produced": produced_by(s)} for s in OLD_DAY]
    del stages[6]["produced"]
    assert stored_summary(stages)["summary_code"] == SUMMARY_BEFORE_COUNTS


def test_the_runs_list_carries_the_code_and_no_count_for_an_old_run(engine) -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date="2026-09-12",
                preflight_status="READY",
                preflight_json={"status": "READY", "checks": []},
                status="COMPLETED",
                stages_json=OLD_DAY,
                stages_total=len(OLD_DAY),
                stages_completed=len(OLD_DAY),
                started_at=now,
                finished_at=now,
            )
        )
    (listed,) = list_runs(engine)
    assert listed["summary_code"] == "before_counts"
    assert listed["stages_productive"] is None
    assert listed["summary"].startswith("Rulare dinainte de numărătoare: ")
    # The stages are handed back as stored: the page's rows say «nenumărat» by themselves.
    assert all("produced" not in stage for stage in listed["stages"])
