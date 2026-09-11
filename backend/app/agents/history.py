"""What an employee was asked, what it answered, what it decided and why — and a way to ask it.

Every run was already recorded (`AgentRun`), every typed message too (`AgentMessage`), and
every validated judgement became memory (`MemoryRecord`). What was missing was one place to
read them in order, and a way for the Owner to talk to an employee without inventing a "task
type". This module merges the three records into one timeline and adds `chat`, which is an
ordinary run through the same policy kernel and identity, with the Owner's question as the
prompt. Nothing here is a separate log: the timeline is the audit trail, read back.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.agents.memory import memory_view
from app.agents.messages import message_view
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord
from app.agents.services import run_agent_task
from app.factual.sanitizer import wrap_in_inert_boundary
from app.providers.registry import ProviderRegistry

CHAT_TASK = "owner_chat"
CHAT_TEMPLATE_VERSION = "chat-v1"

_CHAT_INSTRUCTIONS = (
    "The Owner is speaking to you directly. Answer in your own voice and in the language the "
    "Owner used. Draw on your work contract and on what you remember; when you do not know, "
    "say so rather than guess, and when a question is about a decision you made, give the "
    "reason you recorded. Keep it to a few sentences unless the Owner asks for detail.\n"
)


def _run_item(run: AgentRun) -> dict[str, Any]:
    """One run as a line of history.

    ``asked`` is the employee's own sentence about the task when the caller wrote one; the
    engineered prompt stays in ``prompt``, where the Owner can open it, because a timeline
    that shows nine hundred words of instructions per entry shows the same thing every time
    and hides the claim, the topic or the figures that made this run different from the last.
    """
    context = run.context_json if isinstance(run.context_json, dict) else {}
    summary = str(context.get("task_summary") or "").strip()
    return {
        "kind": "run",
        "id": run.id,
        "at": run.started_at,
        "finished_at": run.finished_at,
        "task_type": run.task_type,
        "asked": summary or run.objective,
        "prompt": run.objective,
        "answered": run.output_text,
        "status": run.status,
        "error": run.error_detail,
        "model": run.model_name,
        "cost_vr": run.cost_vr,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "memory_used": len(context.get("memory_record_ids") or []),
    }


def agent_timeline(engine: Engine, agent_id: str, limit: int = 80) -> list[dict[str, Any]]:
    """Runs, messages and memory of one employee, newest first."""
    with Session(engine) as session:
        names = {a.id: a.display_name for a in session.scalars(select(Agent))}
        runs = session.scalars(
            select(AgentRun)
            .where(AgentRun.agent_id == agent_id)
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        ).all()
        messages = session.scalars(
            select(AgentMessage)
            .where(
                or_(AgentMessage.from_agent_id == agent_id, AgentMessage.to_agent_id == agent_id)
            )
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        ).all()
        memory = session.scalars(
            select(MemoryRecord)
            .where(MemoryRecord.agent_id == agent_id)
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        ).all()
        items: list[dict[str, Any]] = [_run_item(r) for r in runs]
        items.extend(
            {"kind": "message", "at": m.created_at, **message_view(m, names)} for m in messages
        )
        # A message an employee files is also remembered, in the same words, with the
        # message's id as its source. Both records are right to exist — one is the message,
        # the other is what the employee carries into the next run — but shown one after the
        # other they read as the studio saying everything twice. The memory of a message
        # already on the timeline is dropped from the view, not from the record. A memory
        # whose source is a run is kept: that is what the employee concluded, not a copy of
        # what it said.
        filed = {m.id for m in messages}
        items.extend(
            {"kind": "memory", "at": m.created_at, **memory_view(m)}
            for m in memory
            if (m.source_id or "") not in filed
        )
    items.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return items[:limit]


def chat(
    engine: Engine,
    registry: ProviderRegistry,
    agent_id: str,
    message: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Put the Owner's question to the employee, through its identity, and record the run."""
    text = " ".join(str(message).split())
    if not text:
        raise ValueError("Scrie o întrebare")
    prompt = _CHAT_INSTRUCTIONS + wrap_in_inert_boundary(text, "owner-question")
    result = run_agent_task(
        engine,
        registry,
        agent_id,
        CHAT_TASK,
        prompt,
        CHAT_TEMPLATE_VERSION,
        correlation_id or str(uuid4()),
        summary=text,
        max_tokens=1200,
        temperature=0.4,
    )
    with Session(engine) as session:
        run = session.get(AgentRun, result["id"])
        item = _run_item(run) if run else {"kind": "run", "id": result["id"]}
    # The timeline shows the Owner's words, not the framing around them.
    item["asked"] = text
    return item
