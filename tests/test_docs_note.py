"""scripts/docs_note.py writes a dated note where the docs checks read it (WP29, 2026-10-09).

Every test works on a copy in its own folder: nothing under docs/project is read or written
here (tests/test_docs_truth.py runs the script on the real documents, in memory).
"""

import importlib.util

import pytest
from app.config import ROOT

spec = importlib.util.spec_from_file_location("docs_note", ROOT / "scripts/docs_note.py")
assert spec is not None and spec.loader is not None
docs_note = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docs_note)

STATUS = (
    "# CURRENT STATUS — State on 2026-10-09\n"
    "\n"
    "Current proof: the audit was proven on fakes only; AGENT_SCENARIO_ACCEPTANCE used real\n"
    "calls.\n"
    "\n"
    "## OLDER_WORK — complete on fakes (2026-10-08)\n"
    "\n"
    "Older words, with diacritice: «Închide filmul».\n"
)
CHANGELOG = "# Changelog\n\n## 2026-10-08 — older work\n\n- a line\n"


def _tree(tmp_path, status=STATUS, crlf=True, bom=False):
    folder = tmp_path / "docs" / "project"
    folder.mkdir(parents=True)
    for name, text in (("CURRENT_STATUS.md", status), ("CHANGELOG.md", CHANGELOG)):
        data = (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
        (folder / name).write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    (folder / "16_DECISION_LOG.md").write_bytes(b"# Decision Log\n\n## ADR-OLD (2026-10-08)\n\nx\n")
    return folder


def _run(tmp_path, capsys, *argv):
    code = docs_note.main(list(argv), root=tmp_path)
    return code, capsys.readouterr().out


def test_a_status_note_goes_under_the_state_block_and_keeps_crlf(tmp_path, capsys):
    folder = _tree(tmp_path)
    code, out = _run(
        tmp_path,
        capsys,
        "status",
        "NEW_WORK — complete",
        "--body",
        "Ce s-a făcut.",
        "--date",
        "2026-10-10",
    )
    assert code == 0, out
    raw = (folder / "CURRENT_STATUS.md").read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")  # every line ending is still CRLF
    text = raw.decode("utf-8").replace("\r\n", "\n")
    assert text == STATUS.replace("State on 2026-10-09", "State on 2026-10-10").replace(
        "\n## OLDER_WORK",
        "\n## NEW_WORK — complete (2026-10-10)\n\nCe s-a făcut.\n\n## OLDER_WORK",
    )
    assert "added «## NEW_WORK — complete (2026-10-10)»" in out


def test_the_same_note_twice_is_written_once(tmp_path, capsys):
    folder = _tree(tmp_path, crlf=False)
    argv = ("status", "NEW_WORK", "--body", "Once.", "--date", "2026-10-10")
    assert _run(tmp_path, capsys, *argv)[0] == 0
    once = (folder / "CURRENT_STATUS.md").read_bytes()
    code, out = _run(tmp_path, capsys, *argv)
    assert code == 0 and "already there" in out
    assert (folder / "CURRENT_STATUS.md").read_bytes() == once


def test_an_older_note_never_moves_the_header_date_back(tmp_path, capsys):
    folder = _tree(tmp_path, crlf=False)
    assert _run(tmp_path, capsys, "status", "LATE", "--body", "x", "--date", "2026-10-01")[0] == 0
    assert (
        (folder / "CURRENT_STATUS.md")
        .read_text(encoding="utf-8")
        .startswith("# CURRENT STATUS — State on 2026-10-09\n")
    )


def test_a_byte_order_mark_is_kept(tmp_path, capsys):
    folder = _tree(tmp_path, bom=True)
    assert (
        _run(tmp_path, capsys, "changelog", "new", "--body", "- x", "--date", "2026-10-10")[0] == 0
    )
    raw = (folder / "CHANGELOG.md").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf# Changelog\r\n\r\n## 2026-10-10 \xe2\x80\x94 new\r\n")


def test_a_changelog_and_a_decision_note_take_their_documents_heading_forms(tmp_path, capsys):
    folder = _tree(tmp_path, crlf=False)
    _run(tmp_path, capsys, "changelog", "a fix", "--body", "- one", "--date", "2026-10-10")
    _run(
        tmp_path, capsys, "decision", "ADR-NEW — why", "--body", "Because.", "--date", "2026-10-10"
    )
    assert (folder / "CHANGELOG.md").read_text(encoding="utf-8") == (
        "# Changelog\n\n## 2026-10-10 — a fix\n\n- one\n\n## 2026-10-08 — older work\n\n- a line\n"
    )
    log = (folder / "16_DECISION_LOG.md").read_text(encoding="utf-8")
    assert log == "# Decision Log\n\n## ADR-NEW — why (2026-10-10)\n\nBecause.\n\n" + (
        "## ADR-OLD (2026-10-08)\n\nx\n"
    )


def test_a_title_that_carries_its_date_is_not_dated_twice():
    assert docs_note.heading_for("status", "X — done (2026-10-09)", "2026-10-10") == (
        "X — done (2026-10-09)"
    )
    assert docs_note.heading_for("changelog", "2026-10-09 — x", "2026-10-10") == "2026-10-09 — x"
    assert docs_note.heading_for("decision", "ADR-X  —  why", "2026-10-10") == (
        "ADR-X — why (2026-10-10)"
    )


def test_live_claims_stay_above_the_state_block_and_the_note(tmp_path):
    text = STATUS.replace(
        "\n\nCurrent proof:",
        "\n\n## Active claim — WORK (Codex, 2026-10-09)\n\nMine.\n\nCurrent proof:",
    )
    updated, _ = docs_note.add_note(text, "status", "NEW", "Body.", "2026-10-09")
    assert updated.index("## Active claim") < updated.index("Current proof:")
    assert updated.index("Current proof:") < updated.index("## NEW (2026-10-09)")
    assert updated.index("## NEW (2026-10-09)") < updated.index("## OLDER_WORK")


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        (("status", "X", "--body", "  \n", "--date", "2026-10-10"), "no body"),
        (("status", "X", "--body", "a\n## B\nc", "--date", "2026-10-10"), "section of its own"),
        (("status", "X", "--body", "a", "--date", "10/10/2026"), "YYYY-MM-DD"),
        (("status", "X", "--body", "a", "--date", "2026-02-30"), "not a day of the calendar"),
    ],
)
def test_a_refused_note_writes_nothing_and_says_why(tmp_path, capsys, argv, why):
    folder = _tree(tmp_path)
    before = (folder / "CURRENT_STATUS.md").read_bytes()
    code, out = _run(tmp_path, capsys, *argv)
    assert code == 1 and "nothing written" in out and why in out, out
    assert (folder / "CURRENT_STATUS.md").read_bytes() == before


def test_a_body_file_written_with_a_byte_order_mark_is_read_without_it(tmp_path, capsys):
    """WP29 review (2026-10-09): Windows PowerShell's `>`, Out-File and `Set-Content -Encoding
    utf8` start a file with a BOM. Read as plain UTF-8 it became an invisible U+FEFF inside
    docs/project, and a body opening with «## » slipped past the section refusal behind it."""
    folder = _tree(tmp_path)
    sneaky = tmp_path / "sneaky.md"
    sneaky.write_bytes(b"\xef\xbb\xbf## Sneaky section\r\n\r\n- y\r\n")
    before = (folder / "CHANGELOG.md").read_bytes()
    code, out = _run(
        tmp_path, capsys, "changelog", "t", "--body-file", str(sneaky), "--date", "2026-10-10"
    )
    assert code == 1 and "section of its own" in out, out
    assert (folder / "CHANGELOG.md").read_bytes() == before

    plain = tmp_path / "plain.md"
    plain.write_bytes(b"\xef\xbb\xbf- Ce s-a f\xc4\x83cut.\r\n")
    code, out = _run(
        tmp_path, capsys, "changelog", "t", "--body-file", str(plain), "--date", "2026-10-10"
    )
    assert code == 0, out
    text = (folder / "CHANGELOG.md").read_bytes().decode("utf-8")
    assert "﻿" not in text
    assert "## 2026-10-10 — t\r\n\r\n- Ce s-a făcut.\r\n\r\n## 2026-10-08" in text


def test_a_body_handed_over_with_a_byte_order_mark_is_judged_without_it():
    with pytest.raises(docs_note.NoteRefused, match="section of its own"):
        docs_note.add_note(CHANGELOG, "changelog", "t", "﻿## Sneaky\n\n- y", "2026-10-10")
    updated, _ = docs_note.add_note(CHANGELOG, "changelog", "t", "﻿- y", "2026-10-10")
    assert "﻿" not in updated and "## 2026-10-10 — t\n\n- y\n" in updated


def test_a_status_head_without_its_state_block_is_refused_not_guessed(tmp_path, capsys):
    folder = _tree(tmp_path, status=STATUS.replace("Current proof: ", "Proof: "))
    before = (folder / "CURRENT_STATUS.md").read_bytes()
    code, out = _run(tmp_path, capsys, "status", "X", "--body", "a", "--date", "2026-10-10")
    assert code == 1 and "is missing" in out, out
    assert (folder / "CURRENT_STATUS.md").read_bytes() == before
    assert _run(tmp_path, capsys, "status", "--check")[0] == 1


def test_check_and_repair_find_and_move_a_pushed_down_state_block(tmp_path, capsys):
    title, _, rest = STATUS.partition("\n")
    broken = f"{title}\n\n## PUSHED (2026-10-09)\n\nWritten under the title.\n{rest}"
    folder = _tree(tmp_path, status=broken)
    code, out = _run(tmp_path, capsys, "status", "--check")
    assert code == 1 and "line 7, inside «## PUSHED (2026-10-09)»" in out, out
    assert (folder / "CURRENT_STATUS.md").read_bytes().decode("utf-8").replace("\r\n", "\n") == (
        broken
    )

    code, out = _run(tmp_path, capsys, "status", "--repair")
    assert code == 0 and "Moved the state block" in out, out
    text = (folder / "CURRENT_STATUS.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert text == STATUS.replace(
        "\n## OLDER_WORK", "\n## PUSHED (2026-10-09)\n\nWritten under the title.\n\n## OLDER_WORK"
    )
    assert _run(tmp_path, capsys, "status", "--check") == (
        0,
        "CURRENT_STATUS.md: the head is whole.\n",
    )
