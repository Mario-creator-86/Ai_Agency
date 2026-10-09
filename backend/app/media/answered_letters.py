"""Letters to the Owner that ask about something no longer waiting close themselves.

2026-10-09 (film babcf272): the Owner closed six «Foaia de filmare: … așteaptă răspunsul tău la
pasul …» letters by hand, each written for a question he had already answered on the sheet or
for a state the film had already left (13:42 «așteaptă să se încheie cumpărarea în curs»,
closed by him at 17:12). The studio now closes an OPEN letter to him when:

- it is the sheet's letter (``owner_shooting_sheet``) and the question it names
  (``approval_id``) no longer waits: answered, withdrawn or expired;
- it is the sheet's letter and a newer sheet letter about the same film says where the film
  stands now;
- it is the list of his standing questions (``owner_waiting``) and none of them waits any more.

Every other letter stays for him: a letter about the books or money (``paid_step_interrupted``,
a purchase abandoned, takes lost) reports a fact, not a question. Local reads and writes;
nothing sent, nothing bought.

Whether a question still waits is read through the Owner's command module
(`services.pending_approvals`), never from his approval rows directly: only that module may
reach them (tests/test_phase_dg_closure_adversary.py).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.services import pending_approvals

#: Who closed it, in the letter's record (the stage reports' archive uses the same word).
RESOLVED_BY = "system"
#: The sheet's letter and the list of his standing questions (`runbook.stages`,
#: `economy.accountant.waiting_approvals_letter`).
SHEET_LETTER = "owner_shooting_sheet"
WAITING_LETTER = "owner_waiting"

ANSWERED_RO = (
    "Închisă de studio: întrebarea din scrisoare nu mai așteaptă răspunsul tău (ai răspuns, "
    "a fost retrasă sau a expirat)."
)
SUPERSEDED_RO = (
    "Închisă de studio: o scrisoare mai nouă despre același film spune unde a ajuns acum."
)
LIST_ANSWERED_RO = "Închisă de studio: nicio întrebare din listă nu mai așteaptă răspunsul tău."


def retire_answered_letters(engine: Engine, correlation_id: str | None = None) -> dict[str, Any]:
    """Close the asking letters whose question no longer waits. Returns the closed ids by
    reason. Idempotent: a closed letter is never read again."""
    from app.agents.messages import is_for_owner, resolve_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.db import lock_for_write  # noqa: PLC0415

    correlation = correlation_id or str(uuid4())
    closed: dict[str, list[str]] = {"answered": [], "superseded": [], "lists": []}
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        # Read after the lock: a question asked (and its letter written) before it is in the
        # list, and nothing new can be asked until this pass commits.
        waiting = {view.id for view in pending_approvals(engine)}
        letters = [
            row
            for row in session.scalars(
                select(AgentMessage)
                .where(AgentMessage.to_agent_id.is_(None))
                .order_by(AgentMessage.created_at)
            )
            if is_for_owner(row)
        ]
        # The newest sheet letter of each film, whatever its status: the film's current word.
        newest: dict[str, str] = {}
        for row in letters:
            body = row.body_json if isinstance(row.body_json, dict) else {}
            if body.get("kind") == SHEET_LETTER and body.get("storyboard_id"):
                film = str(body["storyboard_id"])
                newest[film] = max(newest.get(film, ""), str(row.created_at))
        for row in letters:
            if row.status != "OPEN":
                continue
            body = row.body_json if isinstance(row.body_json, dict) else {}
            kind = body.get("kind")
            if kind == SHEET_LETTER:
                approval_id = str(body.get("approval_id") or "")
                if approval_id and approval_id not in waiting:
                    resolve_message(
                        session,
                        row.id,
                        resolution=ANSWERED_RO,
                        resolved_by=RESOLVED_BY,
                        correlation_id=correlation,
                    )
                    closed["answered"].append(str(row.id))
                    continue
                film = str(body.get("storyboard_id") or "")
                if film and newest.get(film, "") > str(row.created_at):
                    resolve_message(
                        session,
                        row.id,
                        resolution=SUPERSEDED_RO,
                        resolved_by=RESOLVED_BY,
                        correlation_id=correlation,
                    )
                    closed["superseded"].append(str(row.id))
            elif kind == WAITING_LETTER:
                questions = body.get("questions")
                if not isinstance(questions, list) or not questions:
                    continue
                ids = [str(q.get("id") or "") for q in questions if isinstance(q, dict)]
                if len(ids) != len(questions) or not all(ids):
                    continue  # a list the studio cannot read whole is left for him
                if any(i in waiting for i in ids):
                    continue
                resolve_message(
                    session,
                    row.id,
                    resolution=LIST_ANSWERED_RO,
                    resolved_by=RESOLVED_BY,
                    correlation_id=correlation,
                )
                closed["lists"].append(str(row.id))
    return closed
