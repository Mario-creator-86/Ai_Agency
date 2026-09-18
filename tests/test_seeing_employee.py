"""The employee who can look arrives on the day the Owner admits a model that sees.

Measured on this tree before the work: `prefer_capable_models` was called from
`seed_initial_workforce` alone, and that from `scripts/bootstrap.py` alone — step 1 of the
Owner's morning, hours before step 9 where he admits the seeing model. Nothing ran between
the admission and the next day, so `app.agents.vision.vision_agent` returned None at 05:00,
the picture and character checks stood down, and a film of eight blank fields reached the
Director as a finished short.

What is asserted here is the whole chain, in the order the studio lives it: the workforce is
hired, the model sync applies the starting allocation, a seeing model is admitted later, the
next sync moves the Video Editor onto it, and `vision_agent` finds her. Then the converse: a
studio whose Owner never admits one still hires, still runs the day's quality stage, and has
its picture check stand down without failing a film.

Every provider is faked at its transport — the catalogue and the look alike. Nothing here
contacts a vendor and nothing costs money: the Owner's rule of 2026-09-17.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord, ProviderRecord, Role
from app.agents.seed_config import load_seed_config
from app.agents.services import (
    list_roles,
    prefer_capable_models,
    seed_initial_workforce,
    sync_provider_models,
)
from app.agents.vision import vision_agent
from app.integrations.services import assign_agent
from app.media.qc import evaluate_media_qc
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult, ModelInfo
from app.providers.registry import ProviderRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session

SEEING = "qwen3-vl:cloud"


class Catalogue:
    """A provider's catalogue and its answers, faked at the transport.

    `models` maps a model name to what the provider declares about it, in the provider's own
    words — the studio never guesses a capability, so a model sees here only because this
    fake says the vendor said so.
    """

    def __init__(self, models: dict[str, tuple[str, ...]], answer=None):
        self.models = dict(models)
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return [
            ModelInfo(
                model_name=name,
                context_length=131072,
                is_available=True,
                capabilities=capabilities,
                is_cloud=True,
            )
            for name, capabilities in self.models.items()
        ]

    async def generate(self, model, prompt, **kwargs):
        self.calls.append((model, prompt))
        return GenerateResult(self.answer(prompt) if self.answer else "", 10, 40, None)


def text_catalogue() -> dict[str, tuple[str, ...]]:
    """Every model the studio's own starting allocation names, and none of them sees.

    Read from `config/workforce_seed.json` rather than spelled here: the point of these tests
    is what happens to an employee the *file* placed, so the file has to be the one placing
    her.
    """
    catalogue: dict[str, tuple[str, ...]] = {}
    for entry in load_seed_config()["llm_allocation"]:
        for slot in ("primary", "secondary", "tertiary"):
            if entry.get(slot):
                catalogue[str(entry[slot])] = ("completion", "tools")
    return catalogue


def allocated(role_name: str) -> str:
    """The primary model the studio's own file gives this role."""
    for entry in load_seed_config()["llm_allocation"]:
        if entry["role"] == role_name:
            return str(entry["primary"])
    raise AssertionError(f"no allocation for {role_name}")


def provider_id_of(engine) -> str:
    with Session(engine) as session:
        return session.scalar(select(ProviderRecord.id))


def editor(engine) -> tuple[str, str]:
    """The Video Editor's id and the name of the model she thinks with."""
    with Session(engine) as session:
        agent = session.scalar(
            select(Agent)
            .join(Role, Agent.role_id == Role.id)
            .where(Role.name == "VideoEditor", Agent.lifecycle == "ACTIVE")
        )
        model = session.get(ModelRecord, agent.model_id)
        return agent.id, model.model_name


def events_of(engine, agent_id: str, event_type: str) -> int:
    with Session(engine) as session:
        return len(
            list(
                session.scalars(
                    select(DomainEvent.event_id).where(
                        DomainEvent.aggregate_id == agent_id,
                        DomainEvent.event_type == event_type,
                    )
                )
            )
        )


@pytest.fixture
def hired(engine):
    """A seeded studio whose provider catalogue has been synced once, as a first day goes."""
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    registry = ProviderRegistry()
    adapter = Catalogue(text_catalogue())
    provider_id = provider_id_of(engine)
    registry.register(provider_id, adapter)
    sync_provider_models(engine, registry, provider_id)
    return {
        "registry": registry,
        "adapter": adapter,
        "provider_id": provider_id,
        "engine": engine,
    }


# --------------------------------------------------------------- the chain, end to end


def test_a_model_admitted_after_the_workforce_exists_reaches_the_employee(hired, engine):
    """Step 9 of the Owner's morning is enough on its own: he admits it, the sync places it.

    Before this, the only call to `prefer_capable_models` was inside `seed_initial_workforce`,
    which runs at step 1; a model admitted at step 9 was never looked at again, so the studio
    woke at 05:00 with nobody who could see.
    """
    editor_id, on_model = editor(engine)
    assert on_model == allocated("VideoEditor"), "the starting allocation placed her"
    assert events_of(engine, editor_id, "agent.model_assigned") == 1
    with Session(engine) as session:
        assert vision_agent(session, "VideoEditor", "Director") is None

    hired["adapter"].models[SEEING] = ("completion", "tools", "vision")
    sync_provider_models(engine, hired["registry"], hired["provider_id"])

    with Session(engine) as session:
        found = vision_agent(session, "VideoEditor", "Director")
        assert found is not None, "the studio admitted a seeing model and still nobody looks"
        agent = session.get(Agent, found[0])
        assert session.get(Role, agent.role_id).name == "VideoEditor"
        assert session.get(ModelRecord, agent.model_id).model_name == SEEING
        # The move is the studio's own, never a claim that the Owner chose it.
        from app.agents.services import _check_required_capabilities

        _check_required_capabilities(session, agent)
    assert events_of(engine, editor_id, "agent.model_preferred") == 1
    assert events_of(engine, editor_id, "agent.model_assigned") == 1


def test_a_second_sync_moves_nobody_a_second_time(hired, engine):
    """Idempotent: the preference is applied on every sync and changes nothing once it holds."""
    hired["adapter"].models[SEEING] = ("completion", "tools", "vision")
    sync_provider_models(engine, hired["registry"], hired["provider_id"])
    editor_id, moved_to = editor(engine)
    with Session(engine) as session:
        version = session.get(Agent, editor_id).version

    sync_provider_models(engine, hired["registry"], hired["provider_id"])
    result = prefer_capable_models(engine)

    assert result["moved"] == []
    assert editor(engine)[1] == moved_to
    with Session(engine) as session:
        assert session.get(Agent, editor_id).version == version
    assert events_of(engine, editor_id, "agent.model_preferred") == 1


def test_the_owners_own_assignment_is_never_moved_by_a_preference(hired, engine):
    """A model he put her on by hand stays hers, seeing model admitted or not.

    The starting allocation is the studio's own file and may be refined; a model he named
    himself is a decision, and this function has no business arguing with it.
    """
    editor_id, _ = editor(engine)
    with Session(engine) as session:
        chosen = session.scalar(
            select(ModelRecord).where(
                ModelRecord.model_name == allocated("ScriptWriter"),
                ModelRecord.is_available.is_(True),
            )
        )
        chosen_id, chosen_name = chosen.id, chosen.model_name
        version = session.get(Agent, editor_id).version
    assign_agent(engine, editor_id, chosen_id, version)

    hired["adapter"].models[SEEING] = ("completion", "tools", "vision")
    sync_provider_models(engine, hired["registry"], hired["provider_id"])
    result = prefer_capable_models(engine)

    assert editor(engine)[1] == chosen_name
    assert result["moved"] == []
    assert any("Owner" in entry["why"] for entry in result["skipped"])
    with Session(engine) as session:
        assert vision_agent(session) is None, "nobody else was moved either"


def test_the_role_says_what_it_prefers_without_requiring_it(hired, engine):
    """The Owner's page can say why she is on the model she is on, without reading the base."""
    roles = {row["name"]: row for row in list_roles(engine)}
    assert roles["VideoEditor"]["preferred_capabilities"] == ["vision"]
    assert "vision" not in roles["VideoEditor"]["required_capabilities"]
    assert roles["Director"]["preferred_capabilities"] == []


# ------------------------------------------- and the studio that never admits one at all


def test_a_studio_with_no_seeing_model_hires_runs_its_day_and_stands_the_check_down(hired, engine):
    """The converse, which is the studio the Owner has today: honest, and not refused.

    Nothing is hired differently, the day's quality stage runs to a verdict, and the two
    checks that need eyes say they could not run rather than reporting a pass.
    """
    from test_picture_qc import a_film

    with Session(engine) as session:
        assert len(list(session.scalars(select(Agent).where(Agent.lifecycle == "ACTIVE")))) == len(
            load_seed_config()["agents_def"]
        )
        assert vision_agent(session) is None

    result = prefer_capable_models(engine)
    assert result["moved"] == []
    assert any("vision" in entry["why"] for entry in result["skipped"])

    ids = a_film(engine)
    report = evaluate_media_qc(engine, ids["asset"], str(uuid4()), registry=hired["registry"])

    picture = report["checks_json"]["picture_qc"]
    assert picture["status"] == "NOT_APPLICABLE" and picture["passed"] is None
    assert "vision" in picture["detail"]
    assert report["checks_json"]["character_drift_qc"]["passed"] is None
    assert not [r for r in report["failure_reasons_json"] if r.startswith("Scene ")]
    assert hired["adapter"].calls == [], "nobody was asked to look, so nothing was spent"
