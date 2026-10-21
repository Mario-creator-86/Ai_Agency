"""The stranger judge of the frozen evaluation answers again (the audit of 2026-10-16, STUB-002).

`scripts/writer_eval.judge_patches` replaces `compose_identity` for the length of the judge's
calls so the stranger is asked bare. Since `run_agent_task` passes ``subject=`` (the task
context of 2026-10-16), the stand-in, which took ``task_type`` alone, raised TypeError on
every stranger and pairwise call: every case reported an error after the writer's real calls
had used the subscription. The stand-in now takes every keyword `compose_identity` takes,
whatever is added next, and hands the other employees' calls to the real one untouched.

The real patched path is run: `ask_stranger` through `structured_run` and `run_agent_task`, on
a fake provider. No model is called.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

from app.agents import services as agent_services
from app.agents.identity import compose_identity
from app.agents.models import Agent, ModelRecord
from app.agents.services import seed_initial_workforce
from app.evals import stranger
from app.models import OwnerPolicy
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_writer_eval import FakeLLM, a_registry, frozen_serial, we


def _a_studio_with_its_stranger(engine) -> tuple[str, dict]:
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        name = session.scalars(
            select(ModelRecord.model_name).order_by(ModelRecord.model_name)
        ).first()
    judge = we.resolve_model(engine, name)
    return we.ensure_stranger(engine, judge), judge


def test_the_stranger_answers_through_the_patched_identity(engine):
    stranger_id, judge = _a_studio_with_its_stranger(engine)
    model = FakeLLM()
    registry = a_registry()
    registry.register(judge["provider_id"], model)

    with we.judge_patches(stranger_id):
        result = we.ask_stranger(
            engine, registry, stranger_id, stranger.view_of(frozen_serial()), str(uuid4()), "t"
        )

    assert result["orders_answered"] == 3, result
    assert all(call["answered"] for call in result["calls"])
    # Asked bare: the stranger's own system, never the studio's identity.
    assert set(model.systems("[orient]")) == {stranger.STRANGER_SYSTEM}


def test_the_stand_in_takes_every_keyword_the_identity_takes(engine):
    stranger_id, _judge = _a_studio_with_its_stranger(engine)
    keywords = {
        name: parameter.default
        for name, parameter in inspect.signature(compose_identity).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert "subject" in keywords
    subject = {"episode_id": "e1"}
    with Session(engine) as session:
        judge = session.get(Agent, stranger_id)
        writer = session.scalar(select(Agent).where(Agent.id != stranger_id))
        with we.judge_patches(stranger_id):
            bare = agent_services.compose_identity(session, judge, **keywords)
            patched = agent_services.compose_identity(
                session, writer, task_type="write_episode", subject=subject
            )
        real = compose_identity(session, writer, task_type="write_episode", subject=subject)

    assert bare.system == stranger.STRANGER_SYSTEM
    assert bare.context["profile"] == "BARE"
    # Every other employee is told what the studio tells it, its subject included.
    assert patched.system == real.system
