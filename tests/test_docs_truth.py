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

note_spec = importlib.util.spec_from_file_location("docs_note", ROOT / "scripts/docs_note.py")
assert note_spec is not None and note_spec.loader is not None
docs_note = importlib.util.module_from_spec(note_spec)
note_spec.loader.exec_module(docs_note)

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
    _assert_the_audit_decisions_are_logged(_text(PROJECT / "16_DECISION_LOG.md"))


def _assert_the_audit_decisions_are_logged(log):
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


def _status_head(text):
    """The title and the state block: everything before the first dated journal section.

    Live «## Active claim — …» blocks (another agent's, dated) may stand between the title and
    the state block; the state block then reads under the last of them, so the head runs to
    the first heading that is not a claim (amended 2026-10-03)."""
    at = text.find("\n## ")
    while at != -1 and text.startswith("\n## Active claim", at):
        at = text.find("\n## ", at + 1)
    return text if at == -1 else text[:at]


def _status_header_problems(text):
    """What the status header must hold, as messages; [] when it holds all of it.

    2026-10-09 (WP29): a note written straight under the title pushed the state block into
    that note's section twice (SHOOTING_SHEET_UI on 2026-10-03, Codex's notes on 2026-10-09),
    and each time the failure only said a phrase was missing from the head. It now says where
    the paragraph stands and what moves it back (scripts/docs_note.py)."""
    head = _status_head(text)
    problems = []
    # The header's date moves with each dated update; it is never older than the audit's.
    date = re.match(r"^# CURRENT STATUS — State on (\d{4}-\d{2}-\d{2})\n", head)
    if not (date and date.group(1) >= "2026-10-02"):
        problems.append("the first line must read «# CURRENT STATUS — State on YYYY-MM-DD»")
    for stale in ("Last verified: 2026-09-09", "Active edit claim: Codex"):
        if stale in head:
            problems.append(f"the head still says «{stale}»")
    missing = [w for w in ("proven on fakes only", "AGENT_SCENARIO_ACCEPTANCE") if w not in head]
    if missing:
        placement = [p for p in docs_note.status_head_problems(text) if "state block" in p]
        problems.append(
            f"the head (the title and the state block, before the first dated section) does "
            f"not say {missing}: " + (" ".join(placement) or "restore the state block there.")
        )
    if "2,550 passed, 4 failed, 6 skipped" not in text:  # retain the historical audit evidence
        problems.append("the audit's evidence «2,550 passed, 4 failed, 6 skipped» is gone")
    problems.extend(f"{item} is not named" for item in ITEMS if item not in text)
    return problems


def test_the_status_header_is_dated_and_separates_proof_from_fakes():
    assert _status_header_problems(_text(PROJECT / "CURRENT_STATUS.md")) == []


def _assert_the_changelog_is_newest_first(changelog):
    # Newest first: later sections may stand above the audit's (amended 2026-10-03).
    assert changelog.startswith("# Changelog\n\n## ")
    assert "\n## The production-readiness audit — 2026-10-01 → 2026-10-02\n" in changelog


def test_the_roadmap_and_changelog_name_every_item():
    roadmap = _text(PROJECT / "13_ROADMAP_TODO.md")
    _assert_the_changelog_is_newest_first(_text(PROJECT / "CHANGELOG.md"))
    for item in ITEMS:
        assert item in roadmap, item


# ------------------------------------------- a note added by scripts/docs_note.py (WP29)
#
# Every agent adds its notes with scripts/docs_note.py, which puts them after the head. These
# run it on the documents as they stand, in memory: nothing under docs/project is written.

NOTE_BODY = "First paragraph of the note.\n\n- a line\n- another line\n"
NOTE_DAY = "2099-01-01"  # later than any header date, so the header's date must move to it


def _split_status(text):
    head = _status_head(text)
    return head.partition("\n")[2], text[len(head) :]


def test_a_status_note_from_docs_note_keeps_the_status_header_whole():
    text = _text(PROJECT / "CURRENT_STATUS.md")
    updated, notices = docs_note.add_note(
        text, "status", "WP29_SAMPLE — inserted by docs_note", NOTE_BODY, NOTE_DAY
    )
    assert _status_header_problems(updated) == []
    assert updated.startswith(f"# CURRENT STATUS — State on {NOTE_DAY}\n")
    # The head is the same but for its date; the note is the first section; the rest is kept.
    head_before, rest_before = _split_status(text)
    head_after, rest_after = _split_status(updated)
    assert head_after == head_before
    heading = f"\n## WP29_SAMPLE — inserted by docs_note ({NOTE_DAY})\n\n"
    assert rest_after == heading + NOTE_BODY + rest_before
    assert notices == [f"added «## WP29_SAMPLE — inserted by docs_note ({NOTE_DAY})»"]
    # Run again (a retried agent), the same note is not written twice.
    assert (
        docs_note.add_note(updated, "status", "WP29_SAMPLE — inserted by docs_note", "x", NOTE_DAY)[
            0
        ]
        == updated
    )


def test_a_changelog_and_a_decision_note_from_docs_note_keep_their_checks():
    changelog = _text(PROJECT / "CHANGELOG.md")
    updated, _ = docs_note.add_note(changelog, "changelog", "a WP29 sample", NOTE_BODY, NOTE_DAY)
    _assert_the_changelog_is_newest_first(updated)
    assert updated == f"# Changelog\n\n## {NOTE_DAY} — a WP29 sample\n\n{NOTE_BODY}\n" + (
        changelog.removeprefix("# Changelog\n\n")
    )

    log = _text(PROJECT / "16_DECISION_LOG.md")
    updated, _ = docs_note.add_note(log, "decision", "ADR-WP29-SAMPLE — why", NOTE_BODY, NOTE_DAY)
    _assert_the_audit_decisions_are_logged(updated)
    title, _, rest = log.partition("\n")
    assert updated == f"{title}\n\n## ADR-WP29-SAMPLE — why ({NOTE_DAY})\n\n{NOTE_BODY}" + rest


def _note_under_the_title(text):
    """The old mistake: a section written straight under the status title."""
    title, _, rest = text.partition("\n")
    return f"{title}\n\n## WP29_SAMPLE — written under the title (2026-10-09)\n\nA note.\n{rest}"


def test_a_state_block_pushed_under_a_note_is_named_and_moved_back():
    text = _text(PROJECT / "CURRENT_STATUS.md")
    broken = _note_under_the_title(text)
    problems = _status_header_problems(broken)
    assert any(
        "Move that paragraph up" in p and "WP29_SAMPLE — written under the title" in p
        for p in problems
    ), problems

    repaired, moved = docs_note.repair_status_head(broken)
    assert moved and _status_header_problems(repaired) == []
    assert repaired[len(_status_head(repaired)) :].startswith(
        "\n## WP29_SAMPLE — written under the title (2026-10-09)\n\nA note.\n\n## "
    )
    assert docs_note.repair_status_head(repaired) == (repaired, False)

    # The next note repairs it on the way, and says so.
    updated, notices = docs_note.add_note(broken, "status", "WP29_NEXT", NOTE_BODY, NOTE_DAY)
    assert _status_header_problems(updated) == []
    assert any("moved back under the title" in notice for notice in notices), notices


def test_the_project_state_follows_the_migration_chain():
    state = json.loads((PROJECT / "PROJECT_STATE.json").read_text(encoding="utf-8"))
    versions = sorted(
        p.name for p in (ROOT / "backend/migrations/versions").glob("0*.py") if p.is_file()
    )
    assert state["migration_version"] == expected_revision()
    assert state["migration_count"] == len(versions)
    assert re.match(r"^10 ", state["phase"])
    assert "2026-10-02" in state["active_task"]
