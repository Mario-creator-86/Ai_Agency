"""The project's own documents tell the truth the code tells (DOCS_AND_STATUS, 2026-10-02).

The audit of 2026-10-01 found the status header three weeks stale (AR-11), spec 51 saying the
paid staircase was "Not built" after it had shipped (A17), 08/11/39 silent about the only real
paid path (AR-13), 47 describing a Workflow machine nothing drives (AR-14) and 25 asking for a
backup that did not exist (AR-08). These checks read only the documents and the migration chain;
they open no database and call nothing.
"""

import importlib.util
import json
import re

from app.config import ROOT
from app.main import expected_revision

spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/check_docs.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

ARCH = ROOT / "docs/architecture"
PROJECT = ROOT / "docs/project"

AMENDED = {
    "51_AUTONOMY_MODE_SEMANTICS.md": [
        "hero_gate",
        "media.hero_accepted_by_clip_qc",
        "BLOCKED_NO_BUDGET",
        "FILM_CONTINUE",
        "plafon",
        "narration",
    ],
    "08_VIDEO_PIPELINE.md": [
        "## Paid staircase",
        "plan_hash",
        "scene_take",
        "clip QC",
        "SUBMITTED",
        "max_paid_attempts_per_scene",
        "music_library",
        "film_purchase_lease",
    ],
    "11_DATA_MODEL.md": [
        "scene_take",
        "remote_task_id",
        "spend_reservation",
        "spending_budget",
        "film_purchase_lease",
        "daily_run",
        "licence_vendor",
        "remote_privacy_status",
        "youtube_category_id",
    ],
    "39_DAILY_AUTONOMOUS_RUNBOOK.md": [
        "FILM_CONTINUE",
        "film_purchase_lease",
        "sheet:<step>",
        "film_wait_days",
    ],
    "47_STATE_MACHINE_SPECIFICATIONS.md": [
        "daily_run",
        "INTERRUPTED",
        "workflow.job_fired",
    ],
    "25_DEPLOYMENT_BACKUP_OPERATIONS.md": [
        "scripts/backup.py",
        "scripts/restore.py",
        "STUDIO_MIN_FREE_GB",
        "/health/ready",
        "premigrare",
    ],
}

ITEMS = (
    "GREEN_SUITE",
    "PAID_CALLS_AND_TAKE_INTENT",
    "BOOK_EVERY_PURCHASE",
    "NO_REBUY_RECOVERY_REFERENCES",
    "GATES_BEFORE_BUYING",
    "HERO_AUTO_ACCEPT",
    "DAY_FLOW_NO_STALL",
    "CONTINUE_REDOS_E2E",
    "QUEUE_LEASE_SHUTDOWN",
    "SECURITY_STARTUP_LOGGING",
    "GATES_AND_CI",
    "FILM_AUDIO_AND_RIGHTS",
    "FILM_STORY_PICTURE_QC",
    "BACKUP_DISK_HEALTH",
    "PUBLISHING_TRUTH",
    "PUBLISHING_METADATA",
    "SELLABLE",
    "PAGE_OWNER_DAY",
    "PAGE_SETTINGS_ERRORS",
    "DOCS_AND_STATUS",
)


def _text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _index():
    return json.loads((PROJECT / "DOCUMENTATION_INDEX.json").read_text(encoding="utf-8"))


def test_the_documentation_check_passes():
    assert checker.check_docs() == []


def test_each_amended_document_says_what_the_code_does():
    missing = {
        name: [word for word in words if word not in _text(ARCH / name)]
        for name, words in AMENDED.items()
    }
    assert {name: words for name, words in missing.items() if words} == {}


def test_spec_51_no_longer_leaves_the_staircase_unbuilt():
    text = _text(ARCH / "51_AUTONOMY_MODE_SEMANTICS.md")
    # The old sentence may stay as history, but a dated amendment after it must say it is built.
    old = text.find("Not built at this writing")
    built = text.find("Built since 2026-10-01")
    assert built != -1
    assert old == -1 or built > old


def test_each_amended_document_has_its_hash_named_in_the_decision_log():
    log = _text(PROJECT / "16_DECISION_LOG.md")
    records = {r["path"].split("/")[-1]: r for r in _index()["documents"]}
    for name in AMENDED:
        sha = records[name]["sha256"]
        assert sha == checker.document_sha256(ARCH / name), name
        assert sha != records[name]["original_sha256"], name
        assert f"{name}" in log and sha[:16] in log, f"{name}: hash {sha[:16]} not in the log"


def test_the_decision_log_records_each_decision_of_the_audit():
    log = _text(PROJECT / "16_DECISION_LOG.md")
    section = log[log.find("## The production-readiness audit (2026-10-01 → 2026-10-02)") :]
    assert section.startswith("## The production-readiness audit")
    for decision in (
        "ADR-HERO-CLIP-QC",
        "ADR-OVER-USD-CAP",
        "ADR-DAILY-BUDGET-REQUIRED",
        "ADR-FILM-CEILING",
        "ADR-SCENE-MEMORY",
        "ADR-FILM-RETIREMENT",
        "ADR-FILM-CONTINUE",
        "ADR-AUTOMATIC-REDOS",
        "ADR-MANUAL-DEFAULT",
        "ADR-NO-SCHEDULED-WORKFLOWS",
        "ADR-COMPONENT-LICENCES",
        "ADR-NO-SOCKET-TOKEN",
    ):
        assert decision in section, decision
    for pending in ("narration_purchase", "LOCAL_MOVE", "always-on"):
        assert pending in section, pending


def test_the_status_header_is_dated_and_separates_proof_from_fakes():
    text = _text(PROJECT / "CURRENT_STATUS.md")
    head = text[: text.find("\n## ", text.find("\n## ") + 1)]
    assert head.startswith("# CURRENT STATUS — State on 2026-10-02")
    assert "Last verified: 2026-09-09" not in head
    assert "Active edit claim: Codex" not in head
    assert "proven on fakes only" in head
    assert "2,550 passed, 4 failed, 6 skipped" in head
    for item in ITEMS:
        assert item in text, item


def test_the_roadmap_and_changelog_name_every_item():
    roadmap = _text(PROJECT / "13_ROADMAP_TODO.md")
    changelog = _text(PROJECT / "CHANGELOG.md")
    assert changelog.startswith("# Changelog\n\n## The production-readiness audit")
    for item in ITEMS:
        assert item in roadmap, item


def test_the_project_state_follows_the_migration_chain():
    state = json.loads((PROJECT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    versions = sorted(
        p.name for p in (ROOT / "backend/migrations/versions").glob("0*.py") if p.is_file()
    )
    assert state["migration_version"] == expected_revision()
    assert state["migration_count"] == len(versions)
    assert re.match(r"^10 ", state["phase"])
    assert "2026-10-02" in state["active_task"]
