"""The Owner's decisions window is recorded where the project keeps its truth (2026-10-03).

His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
card.» The window, its cards and the rule behind them (an agent proposes, only the Owner
decides, his accept runs through his own command) must be stated in the normative governance
document (31) with its hash re-recorded, and in the decision log, the status, the changelog and
the roadmap. These checks read only the documents and the migration chain; they open no
database and call nothing.
"""

import importlib.util
import json

from app.config import ROOT
from app.main import expected_revision

spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

ARCH = ROOT / "docs/architecture"
PROJECT = ROOT / "docs/project"
SPEC = "31_GOVERNANCE_APPROVAL_POLICY.md"

SPEC_HEADING = "## Owner decision cards (amended 2026-10-03)"
LOG_HEADING = "## The Owner's decisions window (2026-10-03)"
STATUS_HEADING = "## The Owner's decisions window (2026-10-03)"
AUDIT_STATUS_HEADING = "## The production-readiness audit (2026-10-01 → 2026-10-02)"
CHANGELOG_HEADING = "## The Owner's decisions window — 2026-10-03"
ROADMAP_HEADING = "## Owner decisions window — 2026-10-03"

ITEMS = ("DECISIONS_CORE", "DECISION_SOURCES", "DECISIONS_WINDOW", "DOCS_AND_STATUS")


def _text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _section(text, heading):
    start = text.find(heading)
    assert start != -1, heading
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_spec_31_states_what_a_decision_card_is_and_is_not():
    section = _section(_text(ARCH / SPEC), SPEC_HEADING)
    for word in (
        "owner_decision",
        "propose_owner_decision",
        "only the Owner decides",
        "require_owner",
        "his own command",
        "plan_hash",
        "POST /api/v1/owner/approvals/decision",
        "may_act",
        "WAITING_FOR_OWNER_ACTION",
        "owner.decision_decided",
        "hard gate",
    ):
        assert word in section, word


def test_spec_31_hash_is_recorded_and_named_in_the_decision_log():
    index = json.loads((PROJECT / "DOCUMENTATION_INDEX.json").read_text(encoding="utf-8"))
    record = next(r for r in index["documents"] if r["path"].endswith(SPEC))
    assert record["sha256"] == checker.document_sha256(ARCH / SPEC)
    assert record["sha256"] != record["original_sha256"]
    assert checker.check_docs() == []
    section = _section(_text(PROJECT / "16_DECISION_LOG.md"), LOG_HEADING)
    assert SPEC in section and record["sha256"][:16] in section


def test_the_decision_log_records_the_window_and_its_rules():
    section = _section(_text(PROJECT / "16_DECISION_LOG.md"), LOG_HEADING)
    assert "trebuie să îmi apară un card" in section  # the Owner's words
    assert "Fereastră Decizii separată" in section  # the option he chose on a card
    for decision in (
        "ADR-OWNER-DECISION-CARDS",
        "ADR-ONLY-OWNER-DECIDES",
        "ADR-APPLY-THROUGH-OWNER-COMMANDS",
        "ADR-GUIDED-DECISIONS",
        "ADR-DECISION-SOURCES",
        "ADR-DECISIONS-WINDOW",
    ):
        assert decision in section, decision
    for word in ("0054_owner_decisions", "register_applier", "dedupe_key", "REFUSAL_QUIET_DAYS"):
        assert word in section, word


def test_the_status_has_a_dated_section_above_the_audit_naming_each_item():
    text = _text(PROJECT / "CURRENT_STATUS.md")
    import re

    date = re.match(r"^# CURRENT STATUS — State on (\d{4}-\d{2}-\d{2})\n", text)
    assert date and date.group(1) >= "2026-10-03"
    assert text.find(STATUS_HEADING) < text.find(AUDIT_STATUS_HEADING)
    section = _section(text, STATUS_HEADING)
    for item in ITEMS:
        assert item in section, item
    assert "proven on fakes only" in section
    assert "0054_owner_decisions" in section


def test_the_changelog_and_roadmap_lead_with_the_window():
    changelog = _text(PROJECT / "CHANGELOG.md")
    # Newest first: a later entry may stand above the window's (NEXT_ROUND_BALANCE, 2026-10-03).
    assert changelog.startswith("# Changelog\n\n## ")
    assert CHANGELOG_HEADING in changelog
    assert changelog.find(CHANGELOG_HEADING) < changelog.find(
        "## The production-readiness audit — 2026-10-01 → 2026-10-02"
    )
    roadmap = _text(PROJECT / "13_ROADMAP_TODO.md")
    assert roadmap.find(ROADMAP_HEADING) < roadmap.find("## Production-readiness audit")
    section = _section(roadmap, ROADMAP_HEADING)
    for item in ITEMS:
        assert f"- [x] {item}" in section, item


def test_the_project_state_names_the_window():
    state = json.loads((PROJECT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    assert state["migration_version"] == expected_revision()
    assert "0054_owner_decisions" in state["completed_milestone"]
    assert "2026-10-03" in state["active_task"]
    assert "Decizii" in state["active_task"]
