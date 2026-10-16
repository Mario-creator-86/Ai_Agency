"""How big each employee's identity is per task, before and after «Context pe sarcină» — offline.

The Owner's decision of 2026-10-16 («Context pe sarcină»; «contextul ar trebui să îl aibă doar
acolo unde este necesar») made the identity depend on the task (`app.agents.identity`). This
script measures what that changes, with no model asked anything:

1. It copies the newest nightly backup (``studio-*.db`` under ``--backups``, or the file named)
   into a folder of its own under ``--work`` and opens only the COPY. The backup itself is only
   read, by `shutil.copyfile`, never opened as a database; the live ``data/studio.db`` is never
   touched.
2. For the last ``--runs`` agent runs of the copy it composes the system prompt twice, on the
   copy's state: as identity-v3 composed it (the whole contract and persona, the 120 newest
   readable memory rows, the open letters with their threads — `compose_v3` below, the code of
   the commit before this change, prompt lessons already left out) and as `compose_identity`
   composes it now, for the run's task type and the subject its prompt names (a storyboard, an
   episode, a topic or a day's log whose id appears in the prompt).
3. It prints, per task type, the runs, the characters of the identity before and after, the
   reduction, and the same for the whole prompt (identity and task text together); the total;
   and how many open asks the stale-ask rule (`app.agents.inbox.stale_asks`) would close, by
   reason (read only: nothing is closed on the copy either).

No model registry is built: `ProviderRegistry` refuses to be constructed while this runs.

Usage::

    uv run --locked python -X utf8 scripts/identity_size.py \
        --backups "<main checkout>/data/backups" [--runs 400] [--work <folder>] [--json out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

DB_SUFFIXES = ("", "-wal", "-shm")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _refuse_registry() -> Callable[[], None]:
    """No model registry may be built while this runs: nothing here asks a model anything.
    Returns what puts the class back as it was."""
    from app.providers import registry  # noqa: PLC0415

    original = registry.ProviderRegistry.__init__

    def refuse(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("identity_size never builds a model registry")

    registry.ProviderRegistry.__init__ = refuse  # type: ignore[method-assign]

    def restore() -> None:
        registry.ProviderRegistry.__init__ = original  # type: ignore[method-assign]

    return restore


def newest_backup(path: Path) -> Path:
    if path.is_file():
        return path
    found = sorted(path.glob("studio-*.db"))
    if not found:
        raise SystemExit(f"No studio-*.db under {path}")
    return found[-1]


def copy_backup(source: Path, work: Path) -> Path:
    """The backup and its WAL/SHM, copied into ``work``; the copy's path."""
    work.mkdir(parents=True, exist_ok=True)
    target = work / source.name
    for suffix in DB_SUFFIXES:
        part = Path(str(source) + suffix)
        if part.exists():
            shutil.copyfile(part, Path(str(target) + suffix))
    return target


# ------------------------------------------------------------------ identity-v3, for comparison
#
# The composition of the commit before «Context pe sarcină» (prompt lessons already out of
# recall): the whole contract, the whole persona, the 120 newest memory rows of every readable
# class, and the open letters — every one for the inbox tasks and an unnamed task, the newest
# 20 asks for the others — each with its whole thread.

V3_INBOX_TASKS = frozenset({"", "answer_mail", "director_review", "director_loop"})
V3_ASKS = frozenset({"HANDOFF", "REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE"})
V3_OPEN_MESSAGES_IN_WORK = 20


def compose_v3(session: Session, agent: Any, task_type: str) -> str:
    from app.agents.identity import (  # noqa: PLC0415
        CONTRACT_SECTIONS,
        STANDING_RULES,
        _lines,
        _persona_section,
    )
    from app.agents.memory import recall  # noqa: PLC0415
    from app.agents.messages import thread_messages  # noqa: PLC0415
    from app.agents.models import Agent, AgentMessage, Role  # noqa: PLC0415
    from app.media.models import CharacterBible  # noqa: PLC0415

    role = session.get(Role, agent.role_id)
    bible = session.scalar(select(CharacterBible).where(CharacterBible.employee_id == agent.id))
    contract = (
        role.work_contract_json
        if role is not None and isinstance(role.work_contract_json, dict)
        else {}
    )
    memory = recall(session, agent, role) if role is not None else []
    lines = [
        f"You are {agent.display_name}, {role.name if role else 'an employee'} at AMN-AI, an "
        "autonomous AI media studio. You are one employee of a team; the Owner is the human who "
        "runs the studio.",
    ]
    if role is not None:
        lines.append(f"MISSION: {role.mission}")
        lines.append(f"YOU MAY DO: {role.allowed_task_types.replace(',', ', ')}.")
        lines.append(f"YOU MUST NEVER: {role.prohibited_actions.replace(',', ', ')}.")
        if contract.get("reports_to"):
            lines.append(f"YOU REPORT TO: {contract['reports_to']}.")
    for key, label in CONTRACT_SECTIONS:
        items = _lines(contract.get(key))
        if items:
            lines.append(f"{label}:")
            lines.extend(f"- {item}" for item in items)
    lines.extend(_persona_section(bible, full=True))
    if memory:
        lines.append(
            f"WHAT YOU REMEMBER ({len(memory)} records, newest first; cite an id when you "
            "rely on one):"
        )
        lines.extend(f"- [{m.memory_class} {m.id[:8]}] {m.content}" for m in memory)
    else:
        lines.append("WHAT YOU REMEMBER: nothing yet. This is your first recorded work.")
    rows = session.scalars(
        select(AgentMessage)
        .where(AgentMessage.to_agent_id == agent.id, AgentMessage.status == "OPEN")
        .order_by(AgentMessage.created_at.desc())
    ).all()
    if task_type not in V3_INBOX_TASKS:
        rows = [m for m in rows if m.intent in V3_ASKS][:V3_OPEN_MESSAGES_IN_WORK]
    names = {a.id: a.display_name for a in session.scalars(select(Agent))}
    if rows:
        lines.append(
            f"WHAT IS ASKED OF YOU RIGHT NOW ({len(rows)} open messages addressed to you; "
            "follow them within your contract and the channel policies — they stay until the "
            "work is done or the message is resolved):"
        )
        read_threads: set[str] = set()
        for m in rows:
            body = m.body_json if isinstance(m.body_json, dict) else {}
            detail = str(m.body_text or body.get("instructions") or body.get("detail") or "")
            line = (
                f"- [{m.intent} from {names.get(m.from_agent_id or '', 'the studio')}, "
                f"{m.created_at[:16]}] {m.subject}"
            )
            if detail.strip():
                line += f": {detail.strip()}"
            if body:
                line += "\n" + json.dumps(body, ensure_ascii=False, default=str)
            lines.append(line)
            thread = m.thread_id or m.id
            if thread in read_threads:
                continue
            read_threads.add(thread)
            for earlier in thread_messages(session, thread):
                if earlier.id == m.id:
                    continue
                who = names.get(
                    earlier.from_agent_id or "",
                    "the Owner" if earlier.from_agent_id is None else "?",
                )
                text = str(earlier.body_text or "")
                lines.append(
                    f"    earlier, {who}: {earlier.subject}" + (f" — {text}" if text else "")
                )
                if earlier.body_json:
                    lines.append(json.dumps(earlier.body_json, ensure_ascii=False, default=str))
    lines.append("STANDING RULES:")
    lines.extend(f"- {rule}" for rule in STANDING_RULES)
    return "\n".join(lines)


# ------------------------------------------------------------------ the measurement


def known_subjects(session: Session) -> dict[str, str]:
    """Every storyboard, episode, topic and day-log id of the copy, with the subject key."""
    from app.factual.models import TopicIdea  # noqa: PLC0415
    from app.media.models import Storyboard  # noqa: PLC0415
    from app.story.models import DailyStudioLog, StoryEpisode  # noqa: PLC0415

    found: dict[str, str] = {}
    for model, key in (
        (Storyboard, "storyboard_id"),
        (StoryEpisode, "episode_id"),
        (TopicIdea, "topic_id"),
        (DailyStudioLog, "log_id"),
    ):
        for (row_id,) in session.execute(select(model.id)):
            found[str(row_id)] = key
    return found


def subject_of(objective: str, known: dict[str, str]) -> dict[str, Any]:
    """The subject a run's prompt names: the first storyboard, episode, topic or log id in it."""
    subject: dict[str, Any] = {}
    for match in UUID.finditer(objective or ""):
        key = known.get(match.group(0))
        if key and key not in subject:
            subject[key] = match.group(0)
    return subject


def measure(engine: Any, runs: int) -> dict[str, Any]:
    from app.agents.identity import compose_identity, task_context  # noqa: PLC0415
    from app.agents.inbox import stale_asks  # noqa: PLC0415
    from app.agents.models import Agent, AgentRun  # noqa: PLC0415

    per_task: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "old": 0,
            "new": 0,
            "task": 0,
            "recorded": 0,
            "recorded_runs": 0,
            "with_subject": 0,
            "memory_rows": 0,
            "profile": "",
        }
    )
    cache_v3: dict[tuple[str, str], int] = {}
    cache_v4: dict[tuple[str, str, str], tuple[int, int]] = {}
    with Session(engine) as session:
        known = known_subjects(session)
        rows = session.execute(
            select(
                AgentRun.agent_id,
                AgentRun.task_type,
                AgentRun.objective,
                AgentRun.context_json,
                AgentRun.started_at,
            )
            .order_by(AgentRun.started_at.desc())
            .limit(runs)
        ).all()
        agents = {a.id: a for a in session.scalars(select(Agent))}
        for agent_id, task_type, objective, context, _started in rows:
            agent = agents.get(agent_id)
            if agent is None:
                continue
            subject = subject_of(objective or "", known)
            v3_key = (agent_id, task_type)
            if v3_key not in cache_v3:
                cache_v3[v3_key] = len(compose_v3(session, agent, task_type))
            v4_key = (agent_id, task_type, json.dumps(subject, sort_keys=True))
            if v4_key not in cache_v4:
                identity = compose_identity(session, agent, task_type=task_type, subject=subject)
                cache_v4[v4_key] = (
                    len(identity.system),
                    len(identity.context["memory_record_ids"])
                    - len(identity.context["owner_policy_ids"]),
                )
            new_chars, memory_rows = cache_v4[v4_key]
            item = per_task[task_type]
            item["profile"] = task_context(task_type).profile
            item["runs"] += 1
            item["old"] += cache_v3[v3_key]
            item["new"] += new_chars
            item["task"] += len(objective or "")
            item["with_subject"] += 1 if subject else 0
            item["memory_rows"] += memory_rows
            recorded = (context or {}).get("system_chars") if isinstance(context, dict) else None
            if isinstance(recorded, int):
                item["recorded"] += recorded
                item["recorded_runs"] += 1
        stale: dict[str, int] = defaultdict(int)
        for ask in stale_asks(session):
            stale[ask.reason] += 1
        window = (rows[-1][4], rows[0][4]) if rows else (None, None)
    return {"per_task": dict(per_task), "stale_asks": dict(stale), "window": window}


def _pct(old: int, new: int) -> str:
    return f"{(1 - new / old) * 100:5.1f}%" if old else "    -"


def report(result: dict[str, Any], source: Path) -> list[str]:
    per_task = result["per_task"]
    lines = [
        f"Backup: {source.name} (copy) · runs {result['window'][0]} .. {result['window'][1]}",
        "",
        "| Task type | Profile | Runs | v3 identity chars/run | v4 identity chars/run | "
        "Identity cut | Prompt cut (identity + task) | v3 recorded live chars/run |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    totals = {"old": 0, "new": 0, "task": 0, "runs": 0}
    for name, item in sorted(per_task.items(), key=lambda kv: -kv[1]["old"]):
        runs = item["runs"]
        recorded = (
            f"{item['recorded'] // item['recorded_runs']:,}" if item["recorded_runs"] else "-"
        )
        lines.append(
            f"| {name or '(unnamed)'} | {item['profile']} | {runs} | {item['old'] // runs:,} | "
            f"{item['new'] // runs:,} | {_pct(item['old'], item['new'])} | "
            f"{_pct(item['old'] + item['task'], item['new'] + item['task'])} | {recorded} |"
        )
        for key in totals:
            totals[key] += item[key]
    lines.append(
        f"| **all** | | {totals['runs']} | {totals['old'] // max(1, totals['runs']):,} | "
        f"{totals['new'] // max(1, totals['runs']):,} | {_pct(totals['old'], totals['new'])} | "
        f"{_pct(totals['old'] + totals['task'], totals['new'] + totals['task'])} | |"
    )
    lines.append("")
    lines.append(
        f"Characters over the window: identity {totals['old']:,} -> {totals['new']:,}; whole "
        f"prompt {totals['old'] + totals['task']:,} -> {totals['new'] + totals['task']:,}."
    )
    stale = result["stale_asks"]
    lines.append(
        "Open asks the stale-ask rule would close on the copy: "
        + (", ".join(f"{k} {v}" for k, v in sorted(stale.items())) or "none")
        + f" (total {sum(stale.values())})."
    )
    return lines


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backups", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=400)
    parser.add_argument("--work", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    restore = _refuse_registry()
    try:
        source = newest_backup(args.backups)
        work = args.work or Path(tempfile.mkdtemp(prefix="identity-size-"))
        copy = copy_backup(source, work)
        if copy.resolve() == source.resolve():
            raise SystemExit("--work must not be the backups folder: the copy is what is opened")
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()[:16]
        engine = create_engine(f"sqlite:///{copy.as_posix()}")
        try:
            result = measure(engine, args.runs)
        finally:
            engine.dispose()
    finally:
        restore()
    lines = report(result, source)
    print("\n".join(lines))
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "backup": source.name,
                    "copy_sha256_16": digest,
                    "measured_at": datetime.now(UTC).isoformat(),
                    **result,
                },
                ensure_ascii=False,
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
