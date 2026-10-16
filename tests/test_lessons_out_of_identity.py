"""Prompt lessons never ride an identity (audit of 2026-10-16, finding 22).

A prompt lesson is a studio-wide STRATEGY memory row («prompt lesson: [factual][?][new] …»).
`recall()` gave the 120 newest readable rows to every identity, so each role that reads
STRATEGY (the Director, the ScriptWriter, the LeadResearcher, the Publisher, the Accountant)
was told every lesson whole and raw, the unverified and the other kind of film's included. The
Director's prompt audit held 3 proven lessons in its data and 59 lesson rows in her memory, 56
of them unverified, around the 2026-10-15 rule that she reads proven lessons only; a factual
film's «people from behind» reached the serial's writers the same way.

A lesson now reaches a call only through `prompt_lessons(scope)` in its task data, which keeps
each kind of film's own and says which are unverified; the memory channel carries the rest.
Every model here is a fake: nothing is sent to a provider.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.identity import compose_identity, task_context
from app.agents.memory import RECALL_LIMIT, recall, remember
from app.agents.models import Agent, MemoryRecord, Role
from app.media.prompt_agent import (
    LESSON_MARKER,
    LESSON_READING_TASK,
    SCOPE_FACTUAL,
    SCOPE_SERIAL,
    UNVERIFIED_SUFFIX,
    prompt_lessons,
    record_prompt_lesson,
    write_shot_prompts,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_look import (  # noqa: F401 - `staffed` is a fixture
    models,
    scenes_of,
    serial_board,
    shot_pack,
    staffed,
)

#: Studio-wide, proven.
LEDGER = (
    "Pages and screens are blank: a ledger drawn for a number comes back with lettering the "
    "vision gate reads as writing."
)
#: Studio-wide, unverified.
CAMERA = "Asking for a slow push in produced a static shot; say 'dolly in' instead."
#: A factual film's, unverified: no rule for the serial, whose people face the viewer.
FROM_BEHIND = "Show people only from behind, small and distant, so no face is drawn."
#: The serial's own, proven.
FACING = "Both speakers face the viewer from the first moment to the last."
LESSONS = (LEDGER, CAMERA, FROM_BEHIND, FACING)
#: An ordinary studio-wide STRATEGY row, which still reaches the roles that read STRATEGY.
STRATEGY = "Strategy v2: boost topic space."
#: The roles whose contract reads STRATEGY (config/role_contracts.json).
STRATEGY_READERS = {"Director", "ScriptWriter", "LeadResearcher", "Publisher", "Accountant"}
#: The tasks the audit measured on, the inbox ones, an unnamed one, and the ones whose context
#: recalls STRATEGY by recency (`identity.TASK_CONTEXT`).
TASKS = (
    "",
    "director_review",
    "director_prompt_audit",
    "write_episode",
    "shot_prompts",
    "direct_company",
    "owner_chat",
)


def record_lessons(engine) -> None:
    with Session(engine) as session, session.begin():
        assert record_prompt_lesson(session, LEDGER, source_id=str(uuid4()))
        assert record_prompt_lesson(session, CAMERA, source_id=str(uuid4()), provisional=True)
        assert record_prompt_lesson(
            session, FROM_BEHIND, source_id=str(uuid4()), scope=SCOPE_FACTUAL, provisional=True
        )
        assert record_prompt_lesson(session, FACING, source_id=str(uuid4()), scope=SCOPE_SERIAL)


def told_no_lesson(system: str) -> bool:
    return LESSON_MARKER not in system and not any(lesson in system for lesson in LESSONS)


def unwrapped(prompt: str) -> dict:
    """The data a shot writer's prompt carries inside its inert boundary."""
    boundary = prompt.split('<untrusted_source_evidence hash="approved-film">\n', 1)[1]
    return json.loads(boundary.rsplit("\n</untrusted_source_evidence>", 1)[0])


@pytest.mark.usefixtures("staffed")
def test_no_identity_is_told_a_prompt_lesson_even_when_lessons_exist(engine):
    with Session(engine) as session, session.begin():
        remember(session, memory_class="STRATEGY", content=STRATEGY, source_type="event")
    record_lessons(engine)
    with Session(engine) as session:
        lesson_ids = {
            row.id
            for row in session.scalars(
                select(MemoryRecord).where(MemoryRecord.content.like(f"{LESSON_MARKER}%"))
            )
        }
        assert len(lesson_ids) == len(LESSONS)
        roles = {
            agent.id: role.name
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        assert STRATEGY_READERS <= set(roles.values())
        for agent_id, role_name in roles.items():
            agent = session.get(Agent, agent_id)
            for task in TASKS:
                identity = compose_identity(session, agent, task_type=task)
                assert told_no_lesson(identity.system), (role_name, task)
                assert not lesson_ids & set(identity.context["memory_record_ids"]), role_name
                # The memory channel still carries every other STRATEGY row, to the tasks
                # whose context recalls it (2026-10-16, «Context pe sarcină»), and only there.
                recalls = "STRATEGY" in task_context(task).recall
                told = STRATEGY in identity.system
                assert told == (role_name in STRATEGY_READERS and recalls), (role_name, task)
        # The lessons themselves are untouched: their own channel still gives them.
        assert set(prompt_lessons(session)) == {
            LEDGER,
            FACING,
            CAMERA + UNVERIFIED_SUFFIX,
            FROM_BEHIND + UNVERIFIED_SUFFIX,
        }


@pytest.mark.usefixtures("staffed")
def test_lesson_rows_no_longer_push_the_rest_out_of_the_recall_window(engine):
    """Live, 81 lesson rows took places among the Director's 120; with more of them than
    places, an older Owner decision or strategy was never told at all."""
    with Session(engine) as session, session.begin():
        kept = remember(session, memory_class="STRATEGY", content=STRATEGY, source_type="event")
        assert kept is not None
        kept_id = kept.id
        start = datetime.fromisoformat(kept.created_at) + timedelta(seconds=1)
        for number in range(RECALL_LIMIT + 10):
            session.add(
                MemoryRecord(
                    id=str(uuid4()),
                    agent_id=None,
                    memory_class="STRATEGY",
                    content=f"{LESSON_MARKER} [factual][?][new] Lesson {number}: quartz{number}.",
                    source_type="system",
                    created_at=(start + timedelta(seconds=number)).astimezone(UTC).isoformat(),
                )
            )
    with Session(engine) as session:
        director = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == "Director")
        )
        assert director is not None
        recalled = recall(session, director, session.get(Role, director.role_id))
        assert kept_id in {row.id for row in recalled}
        assert not any(row.content.startswith(LESSON_MARKER) for row in recalled)


@pytest.mark.usefixtures("staffed")
def test_the_shot_writer_still_gets_its_lessons_in_its_data_and_nobody_in_their_identity(
    engine, monkeypatch
):
    """The serial's shot writer is given its scope's lessons through `prompt_lessons`, in its
    data, as before; the Director, who reads the new lessons first, and the shot writer are
    told none in their identity (what `run_agent_task` sends as the system prompt)."""
    from app.agents import services, structured

    board_id = serial_board(engine, monkeypatch)
    record_lessons(engine)
    calls: list[dict] = []

    def system_of(agent_id: str, task_type: str) -> str:
        with Session(engine) as session:
            agent = session.get(Agent, agent_id)
            return compose_identity(session, agent, task_type=task_type).system

    def fake_run(_engine, _registry, agent_id, task_type, prompt, *args, **kwargs):
        calls.append(
            {"task": task_type, "prompt": prompt, "system": system_of(agent_id, task_type)}
        )
        answer = json.dumps(shot_pack(len(scenes_of(engine, board_id))))
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": answer}

    def fake_reading(
        _engine, _registry, agent_id, task_type, prompt, template, correlation, schema, hint, **_
    ):
        calls.append(
            {"task": task_type, "prompt": prompt, "system": system_of(agent_id, task_type)}
        )
        run = {"id": str(uuid4()), "status": "SUCCEEDED"}
        return schema.model_validate({"relations": []}), run, None

    monkeypatch.setattr(services, "run_agent_task", fake_run)
    monkeypatch.setattr(structured, "structured_run", fake_reading)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    tasks = [call["task"] for call in calls]
    assert LESSON_READING_TASK in tasks, "the Director read the new lessons first"
    shots = next(call for call in calls if call["task"] == "shot_prompts")
    given = unwrapped(shots["prompt"])["lessons"]
    with Session(engine) as session:
        assert given == prompt_lessons(session, scope=SCOPE_SERIAL)
    assert sorted(given) == sorted([LEDGER, FACING, CAMERA + UNVERIFIED_SUFFIX])
    assert FROM_BEHIND not in shots["prompt"], "a factual film's lesson is no serial rule"
    for call in calls:
        assert told_no_lesson(call["system"]), call["task"]
