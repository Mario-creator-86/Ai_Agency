"""Add a dated note to the project's journals where their checks read it, never above them.

AGENTS.md asks every change for a note in docs/project: CURRENT_STATUS.md, CHANGELOG.md and
16_DECISION_LOG.md, newest first. Notes kept landing directly under the title. In
CURRENT_STATUS that pushes the state block (the «Current proof: ... proven on fakes only»
paragraph that names AGENT_SCENARIO_ACCEPTANCE) down into someone's section, and
tests/test_docs_truth.py fails: the developer moved the paragraph back by hand on 2026-10-03
(SHOOTING_SHEET_UI) and again on 2026-10-09 (Codex's notes; row 60 of that day's audit, WP29).

So a note goes after the document's head: its title, any live «## Active claim — ...» blocks
and, in CURRENT_STATUS, the state block; before the first dated section. In CURRENT_STATUS the
header's «State on» date moves forward to the note's date, and a state block found pushed down
under a section (the old mistake) is moved back under the title first, and said so. A note
whose heading is already there is not written twice. Line endings are kept as the file has
them. Nothing else in the file changes.

    python scripts/docs_note.py status "RUNPOD_X — complete on fakes" --body-file note.md
    python scripts/docs_note.py changelog "RunPod stills: a fair sharpness check" --body "- ..."
    python scripts/docs_note.py decision "ADR-X — why it is so" --body-file adr.md
    python scripts/docs_note.py status --check    # is the status head whole? (exit 1 if not)
    python scripts/docs_note.py status --repair   # move a pushed-down state block back up
"""

from __future__ import annotations

import argparse
import codecs
import re
import sys
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "status": "docs/project/CURRENT_STATUS.md",
    "changelog": "docs/project/CHANGELOG.md",
    "decision": "docs/project/16_DECISION_LOG.md",
}
#: The first words of CURRENT_STATUS's state block, the paragraph that must stay in its head.
STATE_MARKER = "Current proof:"
_STATUS_TITLE = re.compile(r"# CURRENT STATUS — State on (\d{4}-\d{2}-\d{2})\n")
_DATED_TITLE = re.compile(r"\(\d{4}-\d{2}-\d{2}[^()]*\)$")
_DATED_CHANGELOG = re.compile(r"\d{4}-\d{2}-\d{2}\b")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class NoteRefused(ValueError):
    """Nothing was written; the message says why."""


def head_end(text: str) -> int:
    """Where the head ends: the first «## » heading that is not a live «## Active claim».

    The same rule as tests/test_docs_truth.py's `_status_head` (amended 2026-10-03)."""
    at = text.find("\n## ")
    while at != -1 and text.startswith("\n## Active claim", at):
        at = text.find("\n## ", at + 1)
    return len(text) if at == -1 else at


def heading_for(doc: str, title: str, day: str) -> str:
    """The section heading in the document's own form: a date unless the title has one."""
    title = " ".join(title.split())
    if doc == "changelog":
        return title if _DATED_CHANGELOG.match(title) else f"{day} — {title}"
    return title if _DATED_TITLE.search(title) else f"{title} ({day})"


def _state_paragraphs(text: str, start: int) -> list[int]:
    """Where a paragraph opening with the state marker starts, from `start` on."""
    found: list[int] = []
    at = text.find("\n" + STATE_MARKER, start)
    while at != -1:
        found.append(at + 1)
        at = text.find("\n" + STATE_MARKER, at + 1)
    return found


def _line_and_section(text: str, at: int) -> tuple[int, str]:
    line = text.count("\n", 0, at) + 1
    heading = text.rfind("\n## ", 0, at)
    if heading == -1:
        return line, "the title"
    return line, text[heading + 1 : text.find("\n", heading + 1)]


def status_head_problems(text: str) -> list[str]:
    """What is wrong with CURRENT_STATUS's head, each with what to do about it; [] if whole."""
    problems: list[str] = []
    if not _STATUS_TITLE.match(text):
        problems.append(
            "the first line must read «# CURRENT STATUS — State on YYYY-MM-DD» (the date of the "
            "newest note)"
        )
    end = head_end(text)
    if STATE_MARKER not in text[:end]:
        where = _state_paragraphs(text, end)
        if where:
            line, section = _line_and_section(text, where[0])
            problems.append(
                f"the state block («{STATE_MARKER} ... proven on fakes only», naming "
                "AGENT_SCENARIO_ACCEPTANCE) must stand under the title, before the first dated "
                f"section; it stands at line {line}, inside «{section}». Move that paragraph "
                "up under the title (python scripts/docs_note.py status --repair does it), and "
                "add new notes with python scripts/docs_note.py, which puts them below it."
            )
        else:
            problems.append(
                f"the state block («{STATE_MARKER} ... proven on fakes only», naming "
                "AGENT_SCENARIO_ACCEPTANCE) is missing: it must stand under the title, before "
                "the first dated section."
            )
    return problems


def repair_status_head(text: str) -> tuple[str, bool]:
    """Move a state block that a note pushed down back under the title (and any claims).

    Only when the head has none and exactly one paragraph below opens with the marker:
    anything else is left for a person, and `status_head_problems` names it."""
    end = head_end(text)
    if STATE_MARKER in text[:end]:
        return text, False
    where = _state_paragraphs(text, end)
    if len(where) != 1:
        return text, False
    start = where[0]
    stop = text.find("\n\n", start)
    stop = len(text) if stop == -1 else stop + 1
    paragraph = text[start:stop].rstrip("\n") + "\n"
    if text.startswith("\n", stop):
        stop += 1  # the blank line after it goes with it
    rest = text[:start] + text[stop:]
    if stop >= len(text):
        rest = rest.rstrip("\n") + "\n"
    end = head_end(rest)
    head = rest[:end].rstrip("\n") + "\n"
    return head + "\n" + paragraph + rest[end:], True


def move_status_date(text: str, day: str) -> str:
    """The header's «State on» date, moved forward to `day` (never back)."""
    match = _STATUS_TITLE.match(text)
    if match is None or match.group(1) >= day:
        return text
    return text[: match.start(1)] + day + text[match.end(1) :]


def add_note(text: str, doc: str, title: str, body: str, day: str) -> tuple[str, list[str]]:
    """`text` with the dated section added after its head, and what was done besides.

    Raises NoteRefused (nothing changed) when the body is empty or opens a section of its own,
    or when CURRENT_STATUS's head is broken in a way this cannot repair."""
    if doc not in DOCS:
        raise NoteRefused(f"unknown document {doc!r}; one of {', '.join(DOCS)}")
    if not _DAY.fullmatch(day):
        raise NoteRefused(f"the date must read YYYY-MM-DD, not {day!r}")
    try:
        Date.fromisoformat(day)
    except ValueError:
        raise NoteRefused(f"{day} is not a day of the calendar") from None
    # A byte order mark is not the note's: PowerShell's `>` and `Set-Content -Encoding utf8`
    # start a file with one, and before a «## » it hid the section from the refusal below.
    body = body.lstrip("﻿").replace("\r\n", "\n").strip("\n")
    if not body.strip():
        raise NoteRefused("the note has no body")
    if body.startswith("## ") or "\n## " in body:
        raise NoteRefused("the body may not open a «## » section of its own; use «### »")
    if not title.strip():
        raise NoteRefused("the note has no title")
    heading = heading_for(doc, title, day)
    notices: list[str] = []
    if f"\n## {heading}\n" in "\n" + text:
        return text, [f"already there: «## {heading}»; nothing written"]
    if doc == "status":
        text, repaired = repair_status_head(text)
        if repaired:
            notices.append("the state block stood under a section; moved back under the title")
        problems = status_head_problems(text)
        if problems:
            raise NoteRefused("CURRENT_STATUS's head is not whole: " + " ".join(problems))
        text = move_status_date(text, day)
    end = head_end(text)
    head = text[:end].rstrip("\n") + "\n"
    notices.append(f"added «## {heading}»")
    return head + f"\n## {heading}\n\n{body}\n" + text[end:], notices


def _read(path: Path) -> tuple[str, bool, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw[len(codecs.BOM_UTF8) :].decode("utf-8") if bom else raw.decode("utf-8")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), crlf, bom


def _write(path: Path, text: str, crlf: bool, bom: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes((codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8"))


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("doc", choices=sorted(DOCS))
    parser.add_argument("title", nargs="?", help="the section's title, without its date")
    text_source = parser.add_mutually_exclusive_group()
    text_source.add_argument("--body", help="the note's text")
    text_source.add_argument("--body-file", type=Path, help="a UTF-8 file holding the note")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="only check CURRENT_STATUS's head")
    mode.add_argument("--repair", action="store_true", help="only repair CURRENT_STATUS's head")
    args = parser.parse_args(argv)
    path = root / DOCS[args.doc]
    text, crlf, bom = _read(path)

    if args.check or args.repair:
        if args.doc != "status":
            parser.error("--check and --repair read CURRENT_STATUS only: use «status»")
        if args.repair:
            text, repaired = repair_status_head(text)
            if repaired:
                _write(path, text, crlf, bom)
                print("Moved the state block back under the title of CURRENT_STATUS.md.")
        problems = status_head_problems(text)
        for problem in problems:
            print(f"CURRENT_STATUS.md: {problem}")
        if not problems:
            print("CURRENT_STATUS.md: the head is whole.")
        return 1 if problems else 0

    if not args.title or (args.body is None and args.body_file is None):
        parser.error("a note needs a title and --body or --body-file")
    body = args.body
    if args.body_file is not None:
        body = args.body_file.read_text(encoding="utf-8-sig")
    day = args.date or Date.today().isoformat()
    try:
        updated, notices = add_note(text, args.doc, args.title, body or "", day)
    except NoteRefused as refused:
        print(f"{DOCS[args.doc]}: nothing written: {refused}")
        return 1
    if updated != text:
        _write(path, updated, crlf, bom)
    for notice in notices:
        print(f"{DOCS[args.doc]}: {notice}")
    return 0


if __name__ == "__main__":
    # Headings carry Romanian words; a Windows console's code page must not fail after a write.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    sys.exit(main())
