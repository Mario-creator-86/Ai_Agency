"""An employee may think with more than one model, and never learns their names.

The Owner's twenty-two checks. The two that matter most are not about the strategies: that no
model is named anywhere in the studio's logic, so any of the three slots can be replaced from
Settings tomorrow without a line of code changing, and that a critic advises while the
employee decides.

Local throughout. The models here are scripted stand-ins with deliberately chosen names, and
nothing reaches a vendor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.ensemble import (
    AGREEMENT_FLOOR,
    IMPORTANCE,
    POLICIES,
    STRATEGIES,
    agreement,
    apply_llm_allocation,
    collaborations,
    resolve_model,
    run_with_strategy,
    should_collaborate,
    slots,
)
from app.agents.models import Agent, AgentRun, LlmCollaboration, ModelRecord, ProviderRecord, Role
from app.agents.seed_config import load_seed_config
from app.agents.services import seed_initial_workforce, sync_provider_models
from app.integrations.services import assign_agent
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult, ModelInfo
from app.providers.registry import ProviderRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers

#: Stand-in names with no meaning anywhere in the studio. If a test passes only because a
#: name looks familiar, the test is wrong.
PRIMARY = "alpha-one:cloud"
SECONDARY = "beta-two:cloud"
TERTIARY = "gamma-three:cloud"


class Scripted:
    """A provider whose answer depends on the model asked, and that remembers every call."""

    def __init__(self, answers: dict[str, str], fails: set[str] | None = None):
        self.answers = answers
        self.fails = fails or set()
        self.calls: list[tuple[str, str]] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return [
            ModelInfo(
                model_name=name,
                context_length=131072,
                is_available=True,
                capabilities=("completion",),
                is_cloud=True,
            )
            for name in self.answers
        ]

    async def generate(self, model, prompt, **kwargs):
        self.calls.append((model, prompt))
        if model in self.fails:
            raise RuntimeError("the model did not answer")
        return GenerateResult(self.answers.get(model, ""), 5, 9, None)

    def models_asked(self) -> list[str]:
        return [model for model, _ in self.calls]


@pytest.fixture
def staffed(engine):
    """A seeded studio whose provider offers three stand-in models, all verified."""
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    with Session(engine) as session:
        provider_id = session.scalar(select(ProviderRecord.id))
    return {"provider_id": provider_id}


def with_models(engine, staffed, answers, fails=None):
    """Register the provider, discover the models, and return the registry and the adapter."""
    registry = ProviderRegistry()
    adapter = Scripted(answers, fails)
    registry.register(staffed["provider_id"], adapter)
    sync_provider_models(engine, registry, staffed["provider_id"])
    return registry, adapter


def model_ids(engine) -> dict[str, str]:
    with Session(engine) as session:
        return {
            row.model_name: row.id
            for row in session.scalars(select(ModelRecord))
            if row.is_available
        }


def agent_of(engine, role: str) -> Agent:
    with Session(engine) as session:
        agent = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == role)
        )
        assert agent is not None, role
        session.expunge(agent)
        return agent


def configure(
    engine,
    role,
    *,
    primary,
    secondary=None,
    tertiary=None,
    strategy="SINGLE",
    policy="IMPORTANT_ONLY",
    min_importance="STRATEGIC",
    min_confidence=None,
):
    """Save an allocation the way the Owner's own command does."""
    ids = model_ids(engine)
    agent = agent_of(engine, role)
    return assign_agent(
        engine,
        agent.id,
        ids[primary],
        agent.version,
        secondary_model_id=ids[secondary] if secondary else None,
        tertiary_model_id=ids[tertiary] if tertiary else None,
        multi_llm_strategy=strategy,
        additional_llm_policy=policy,
        min_importance=min_importance,
        min_confidence=min_confidence,
    )


def three(answers: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        PRIMARY: "The primary answer about rain and wind.",
        SECONDARY: "A critique: the sample of three is too small to carry this.",
        TERTIARY: "The third opinion: neither position is established by the evidence.",
    }
    base.update(answers or {})
    return base


def _documentation_lines(source: str) -> set[int]:
    """Line numbers belonging to a docstring.

    A module, class or function docstring may name a model as an example of what a vendor
    offers — that is documentation. Code may not, and a model name inside any other string
    literal is code deciding by name, which is exactly what the check is for.
    """
    import ast

    lines: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - the repository does not hold broken files
        return lines
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            lines.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    return lines


# --------------------------------------------------------------- 1-5: the shape of it


def test_1_a_single_model_agent_works_exactly_as_before(engine, staffed):
    """The normal path is untouched: one model, one run, no collaboration row."""
    from app.agents.services import run_agent_task

    registry, adapter = with_models(engine, staffed, three())
    configure(engine, "ScriptWriter", primary=PRIMARY)
    agent = agent_of(engine, "ScriptWriter")
    result = run_agent_task(
        engine, registry, agent.id, "write_script", "Write something.", "v1", str(uuid4())
    )
    assert result["status"] == "SUCCEEDED"
    assert result["model_name"] == PRIMARY
    assert adapter.models_asked() == [PRIMARY]
    with Session(engine) as session:
        assert session.scalars(select(LlmCollaboration)).all() == []


def test_2_every_agent_can_be_given_a_second_and_third_model(engine, staffed):
    """Not only the Director: the slots belong to the agent table, so every employee has
    them, and a slot left empty is simply empty."""
    with_models(engine, staffed, three())
    with Session(engine) as session:
        roles = [row.name for row in session.scalars(select(Role))]
    for role in roles:
        if role not in (
            "Director",
            "LeadResearcher",
            "FactChecker",
            "ScriptWriter",
            "VoiceArtist",
            "VideoEditor",
            "Publisher",
            "Accountant",
        ):
            continue
        saved = configure(
            engine,
            role,
            primary=PRIMARY,
            secondary=SECONDARY,
            tertiary=TERTIARY,
            strategy="REVIEW",
        )
        assert saved["secondary_model_id"] and saved["tertiary_model_id"]
        with Session(engine) as session:
            agent = session.get(Agent, saved["agent_id"])
            configured = slots(session, agent)
        assert configured["primary"]["model_name"] == PRIMARY
        assert configured["secondary"]["model_name"] == SECONDARY
        assert configured["tertiary"]["model_name"] == TERTIARY
    # And a third model with no second one is refused: nobody would be the critic.
    ids = model_ids(engine)
    agent = agent_of(engine, "Accountant")
    with pytest.raises(ValueError, match="al doilea"):
        assign_agent(engine, agent.id, ids[PRIMARY], agent.version, tertiary_model_id=ids[TERTIARY])


def test_3_the_owners_allocation_is_configuration_and_it_applies(engine, staffed):
    """The list the Owner gave is a file, and the studio applies it once the models are known.

    The names in that file carry vendor suffixes that drift between refreshes, so they are
    resolved against the registry rather than trusted literally — and a name that matches
    nothing is reported, never invented.
    """
    seed = load_seed_config()
    allocation = {row["role"]: row for row in seed["llm_allocation"]}
    assert set(allocation) == {
        "Director",
        "LeadResearcher",
        "FactChecker",
        "ScriptWriter",
        "VoiceArtist",
        "VideoEditor",
        "Publisher",
        "Accountant",
    }
    assert allocation["Director"]["strategy"] == "REVIEW"
    assert allocation["Director"]["secondary"], "the Director has a strategic critic"
    assert all(
        row["strategy"] == "SINGLE" for role, row in allocation.items() if role != "Director"
    ), "only the Director starts with more than one model"

    # The vendor's own spelling drifts; the resolver follows it without inventing a row.
    names = {row["primary"] for row in seed["llm_allocation"]}
    names.update(row["secondary"] for row in seed["llm_allocation"] if row["secondary"])
    plain = {re.sub(r"[:-]cloud$", "", name) for name in names}
    registry, _ = with_models(engine, staffed, dict.fromkeys(plain, "an answer"))
    with Session(engine) as session:
        for name in names:
            assert resolve_model(session, name) is not None, name
        assert resolve_model(session, "a-model-nobody-has") is None

    # The sync itself applies it: that is the first moment the studio knows which models
    # exist, and a slot pointing at an unverified model would be worse than an empty slot.
    director = agent_of(engine, "Director")
    with Session(engine) as session:
        row = session.get(Agent, director.id)
        configured = slots(session, row)
        assert row.multi_llm_strategy == "REVIEW"
        assert row.additional_llm_policy == "IMPORTANT_ONLY"
        assert row.min_importance == "STRATEGIC"
        assert configured["secondary"] is not None, "the Director has a critic"
        writer = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == "ScriptWriter")
        )
        assert writer.multi_llm_strategy == "SINGLE" and writer.secondary_model_id is None

    # Applying it again changes nothing: a configured employee is the Owner's business.
    again = apply_llm_allocation(engine)
    assert again["applied"] == []
    assert {row["why"] for row in again["skipped"]} == {"deja configurat"}


def test_4_a_model_can_be_replaced_without_touching_code(engine, staffed):
    """The whole point. The same command that set one model sets another, the agent's version
    moves, and the next execution uses the new one."""
    registry, adapter = with_models(engine, staffed, three())
    configure(engine, "VideoEditor", primary=PRIMARY)
    from app.agents.services import run_agent_task

    agent = agent_of(engine, "VideoEditor")
    first = run_agent_task(
        engine, registry, agent.id, "shot_prompts", "Describe a shot.", "v1", str(uuid4())
    )
    assert first["model_name"] == PRIMARY

    configure(engine, "VideoEditor", primary=SECONDARY)
    agent = agent_of(engine, "VideoEditor")
    second = run_agent_task(
        engine, registry, agent.id, "shot_prompts", "Describe a shot.", "v1", str(uuid4())
    )
    assert second["model_name"] == SECONDARY
    # And the earlier run still says what answered it. History is not rewritten.
    with Session(engine) as session:
        assert session.get(AgentRun, first["id"]).model_name == PRIMARY


def test_owner_choice_matching_the_seed_is_protected_from_role_preferences(engine, staffed):
    from app.agents.services import _owner_chose_models

    seed = load_seed_config()
    names = {row["primary"] for row in seed["llm_allocation"]}
    names.update(row["secondary"] for row in seed["llm_allocation"] if row["secondary"])
    with_models(engine, staffed, dict.fromkeys(names, "an answer"))
    editor = agent_of(engine, "VideoEditor")
    with Session(engine) as session:
        assert not _owner_chose_models(session, session.get(Agent, editor.id), "VideoEditor")
    assign_agent(engine, editor.id, editor.model_id, editor.version)
    with Session(engine) as session:
        assert _owner_chose_models(session, session.get(Agent, editor.id), "VideoEditor")


def test_seed_assignment_stays_automatic_when_the_seed_file_changes(engine, staffed, monkeypatch):
    from app.agents import services

    seed = load_seed_config()
    names = {row["primary"] for row in seed["llm_allocation"]}
    names.update(row["secondary"] for row in seed["llm_allocation"] if row["secondary"])
    with_models(engine, staffed, dict.fromkeys(names, "an answer"))
    editor = agent_of(engine, "VideoEditor")
    monkeypatch.setattr(services, "_allocation_entry", lambda role: None)
    with Session(engine) as session:
        assert not services._owner_chose_models(
            session, session.get(Agent, editor.id), "VideoEditor"
        )


def test_5_no_model_name_appears_in_the_studios_logic():
    """The architectural rule, checked against the source. A model name lives in the Owner's
    configuration file and in the registry rows discovered from the vendor. If one appears in
    the studio's own code, some branch is deciding by name — which is what breaks the day a
    better model arrives."""
    root = Path(__file__).resolve().parents[1]
    seed = json.loads((root / "config/workforce_seed.json").read_text(encoding="utf-8"))
    names = {row[0] for row in seed["models_data"]}
    for row in seed["llm_allocation"]:
        names.update(
            value for value in (row["primary"], row["secondary"], row["tertiary"]) if value
        )
    bases = {re.sub(r"[:-]cloud$", "", name) for name in names}
    suspects = re.compile(
        "|".join(re.escape(name) for name in sorted(names | bases, key=len, reverse=True))
    )
    offenders: list[str] = []
    for path in (root / "backend/app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if not suspects.search(text):
            continue
        documentation = _documentation_lines(text)
        for number, line in enumerate(text.splitlines(), start=1):
            if number in documentation:
                continue
            found = suspects.search(line.split("#", 1)[0])
            if found:
                offenders.append(f"{path.relative_to(root)}:{number}: {found.group()}")
    assert not offenders, "model names in logic: " + "; ".join(offenders[:6])


# --------------------------------------------------------------- 6-10: the strategies


def test_6_single_asks_one_model(engine, staffed):
    registry, adapter = with_models(engine, staffed, three())
    configure(engine, "FactChecker", primary=PRIMARY, secondary=SECONDARY, strategy="SINGLE")
    agent = agent_of(engine, "FactChecker")
    result = run_with_strategy(
        engine,
        registry,
        agent.id,
        "verify_claim",
        "Check this.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
    )
    assert result["collaboration"]["strategy"] == "SINGLE"
    assert adapter.models_asked() == [PRIMARY]
    assert STRATEGIES[0] == "SINGLE"


def test_7_fallback_takes_over_only_when_the_first_model_fails(engine, staffed):
    """A fallback is not a second opinion: it runs because the first answer does not exist.
    And it never invents one — with every model failing, the failure is what comes back."""
    registry, adapter = with_models(engine, staffed, three(), fails={PRIMARY})
    configure(
        engine,
        "LeadResearcher",
        primary=PRIMARY,
        secondary=SECONDARY,
        strategy="FALLBACK",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "LeadResearcher")
    result = run_with_strategy(
        engine, registry, agent.id, "propose_topics", "Propose something.", "v1", str(uuid4())
    )
    assert adapter.models_asked() == [PRIMARY, SECONDARY]
    assert result["status"] == "SUCCEEDED" and result["model_name"] == SECONDARY
    assert result["collaboration"]["outcome"] == "COMPLETE"

    # Every model failing is a failure, not a fabricated answer.
    registry2, adapter2 = with_models(engine, staffed, three(), fails={PRIMARY, SECONDARY})
    agent = agent_of(engine, "LeadResearcher")
    broken = run_with_strategy(
        engine, registry2, agent.id, "propose_topics", "Propose something.", "v1", str(uuid4())
    )
    assert broken["status"] == "FAILED"
    assert not (broken["output_text"] or "")
    assert broken["collaboration"]["outcome"] == "PARTIAL"


def test_8_review_has_the_second_model_criticise_and_the_first_decide(engine, staffed):
    """Three calls: the answer, the critique, and the employee's own final word. The critique
    reaches the caller only through the primary model's final answer."""
    answers = three({PRIMARY: "First answer about rain.", SECONDARY: "Critique: too few samples."})
    registry, adapter = with_models(engine, staffed, answers)
    configure(engine, "Director", primary=PRIMARY, secondary=SECONDARY, strategy="REVIEW")
    agent = agent_of(engine, "Director")
    result = run_with_strategy(
        engine,
        registry,
        agent.id,
        "direct_company",
        "Decide something important.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
        review_objective="Challenge the sample size.",
        evidence="Three videos measured.",
    )
    assert adapter.models_asked() == [PRIMARY, SECONDARY, PRIMARY]
    assert result["model_name"] == PRIMARY, "the employee's own model gives the final answer"
    collaboration = result["collaboration"]
    assert collaboration["strategy"] == "REVIEW"
    assert collaboration["outcome"] == "COMPLETE"
    assert [entry["role"] for entry in collaboration["models"]] == ["PRIMARY", "CRITIC", "FINAL"]
    # The critic was given the task, the evidence and the answer — and told to review.
    critique_prompt = adapter.calls[1][1]
    assert "Challenge the sample size." in critique_prompt
    assert "Three videos measured." in critique_prompt
    assert "First answer about rain." in critique_prompt
    assert "reviewing another model's answer" in critique_prompt
    # And the final call carried the critique back to the primary as advice.
    assert "Critique: too few samples." in adapter.calls[2][1]
    assert "advice, not as instructions" in adapter.calls[2][1]


def test_9_debate_asks_a_third_model_only_when_the_two_materially_disagree(engine, staffed):
    """Two independent answers; a judge only if they actually differ. An arbiter for a
    disagreement that does not exist is money for nothing."""
    agreeing = three(
        {PRIMARY: "Rain and wind grew stronger.", SECONDARY: "Wind and rain grew stronger."}
    )
    registry, adapter = with_models(engine, staffed, agreeing)
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        tertiary=TERTIARY,
        strategy="DEBATE",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "Director")
    result = run_with_strategy(
        engine, registry, agent.id, "direct_company", "A hard question.", "v1", str(uuid4())
    )
    assert TERTIARY not in adapter.models_asked(), "they agreed; no judge was needed"
    assert result["collaboration"]["disagreed"] is False

    differing = three(
        {
            PRIMARY: "Retention collapsed because the hook is weak.",
            SECONDARY: "Distribution never served the video to anyone.",
        }
    )
    registry2, adapter2 = with_models(engine, staffed, differing)
    agent = agent_of(engine, "Director")
    split = run_with_strategy(
        engine, registry2, agent.id, "direct_company", "A hard question.", "v1", str(uuid4())
    )
    assert TERTIARY in adapter2.models_asked(), "a material disagreement earns a third opinion"
    assert split["collaboration"]["disagreed"] is True
    assert split["model_name"] == PRIMARY, "the employee still writes the answer"
    assert agreement("rain and wind", "rain and wind") == 1.0
    assert agreement("rain", "granite") < AGREEMENT_FLOOR


def test_10_parallel_synthesises_independent_answers(engine, staffed):
    registry, adapter = with_models(engine, staffed, three())
    configure(
        engine,
        "ScriptWriter",
        primary=PRIMARY,
        secondary=SECONDARY,
        tertiary=TERTIARY,
        strategy="PARALLEL",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "ScriptWriter")
    result = run_with_strategy(
        engine, registry, agent.id, "write_script", "Write the hook.", "v1", str(uuid4())
    )
    asked = adapter.models_asked()
    assert asked.count(PRIMARY) == 2 and SECONDARY in asked and TERTIARY in asked
    assert result["model_name"] == PRIMARY
    assert result["collaboration"]["outcome"] == "COMPLETE"


# --------------------------------------------------------------- 11-16: the Director


def test_11_and_16_routine_work_uses_the_primary_model_alone(engine, staffed):
    """Extra models cost money. With the policy at important-only, a routine task is one
    call — and the reason it was one call is recorded, not implied."""
    registry, adapter = with_models(engine, staffed, three())
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        strategy="REVIEW",
        policy="IMPORTANT_ONLY",
        min_importance="STRATEGIC",
    )
    agent = agent_of(engine, "Director")
    routine = run_with_strategy(
        engine,
        registry,
        agent.id,
        "choose_topic",
        "Pick today's topic.",
        "v1",
        str(uuid4()),
        importance="ROUTINE",
    )
    assert adapter.models_asked() == [PRIMARY]
    assert routine["collaboration"]["strategy"] == "SINGLE"
    assert "sub pragul" in routine["collaboration"]["reason"]
    assert POLICIES[0] == "IMPORTANT_ONLY" and IMPORTANCE == ("ROUTINE", "NOTABLE", "STRATEGIC")

    with Session(engine) as session:
        agent_row = session.get(Agent, agent.id)
        wanted, why = should_collaborate(agent_row, importance="ROUTINE")
        assert wanted is False and "sub pragul" in why
        wanted, why = should_collaborate(agent_row, importance="STRATEGIC")
        assert wanted is True and "STRATEGIC" in why


def test_12_an_important_decision_calls_the_strategic_critic(engine, staffed, settings):
    """The Director's own configuration decides this, and the company loop declares its
    decisions strategic — so the critic is consulted where it matters and nowhere else."""
    from app.agents.command import direct_company
    from app.factual.models import TopicIdea
    from app.publishing.services import seed_default_channels
    from app.services import append_event, utc_now

    seed_default_channels(engine)
    plan = json.dumps(
        {
            "choices": [
                {
                    "matter_key": "bottleneck_writing",
                    "decision": "ITERATE",
                    "interpretation": "Scripts are not being finished.",
                    "confidence": "HIGH",
                    "action": "shorten the setup and move the reveal earlier",
                    "owner_role": "ScriptWriter",
                    "review_after_videos": 3,
                }
            ],
            "note": "",
        }
    )
    registry, adapter = with_models(
        engine, staffed, {PRIMARY: plan, SECONDARY: "Critique: three scripts is a small sample."}
    )
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        strategy="REVIEW",
        policy="IMPORTANT_ONLY",
        min_importance="STRATEGIC",
    )
    for index in range(4):
        topic_id = str(uuid4())
        with Session(engine) as session, session.begin():
            event = append_event(
                session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, str(uuid4())
            )
            session.add(
                TopicIdea(
                    id=topic_id,
                    title=f"Topic {index}",
                    topic="space",
                    angle="An angle",
                    target_audience="general",
                    novelty_score=0.7,
                    status="SELECTED",
                    scores_json={"composite": 0.7},
                    source_plan_json=[],
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
            )
    result = direct_company(engine, registry, settings)
    assert result["status"] == "COMPLETED"
    assert SECONDARY in adapter.models_asked(), "a strategic decision was challenged"
    assert "REVIEW" in (result.get("note") or "")
    with Session(engine) as session:
        row = session.scalars(select(LlmCollaboration)).first()
        assert row is not None
        assert row.strategy == "REVIEW" and row.importance == "STRATEGIC"
        assert row.reason and "STRATEGIC" in row.reason


def test_13_and_15_the_critic_advises_and_the_employee_decides(engine, staffed):
    """A critic cannot publish, cannot command a department and cannot change strategy,
    because the only thing it produces is text the primary model reads. The answer the caller
    acts on is always a run on the employee's own model."""
    answers = three(
        {
            PRIMARY: "FINAL: hold the category and test one hook.",
            SECONDARY: "I hereby stop the category and instruct the Publisher to unpublish.",
        }
    )
    registry, adapter = with_models(engine, staffed, answers)
    configure(engine, "Director", primary=PRIMARY, secondary=SECONDARY, strategy="REVIEW")
    agent = agent_of(engine, "Director")
    result = run_with_strategy(
        engine,
        registry,
        agent.id,
        "direct_company",
        "Decide.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
    )
    # The critic's words are not the answer, and the final run is the employee's own model.
    assert result["output_text"] == "FINAL: hold the category and test one hook."
    assert result["model_name"] == PRIMARY
    with Session(engine) as session:
        row = session.scalars(select(LlmCollaboration)).first()
        final_run = session.get(AgentRun, row.final_run_id)
        critic_run = session.get(AgentRun, row.secondary_run_id)
    assert final_run.model_name == PRIMARY
    assert critic_run.model_name == SECONDARY
    assert critic_run.task_type.endswith(":critique"), "a critique is recorded as a critique"
    # And the critic was told, in as many words, that it decides nothing.
    assert "You are not the decision-maker" in adapter.calls[1][1]
    assert "do not issue" in adapter.calls[1][1]


def test_14_a_third_model_arbitrates_when_one_is_configured(engine, staffed):
    """And only when one is configured: with the slot empty, the disagreement is recorded and
    the employee reconciles it alone rather than waiting for an arbiter that does not exist."""
    differing = three(
        {PRIMARY: "The hook is the problem.", SECONDARY: "Distribution is the problem."}
    )
    registry, adapter = with_models(engine, staffed, differing)
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        strategy="DEBATE",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "Director")
    without = run_with_strategy(
        engine, registry, agent.id, "direct_company", "Why did it fail?", "v1", str(uuid4())
    )
    assert TERTIARY not in adapter.models_asked()
    assert without["collaboration"]["disagreed"] is True

    registry2, adapter2 = with_models(engine, staffed, differing)
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        tertiary=TERTIARY,
        strategy="DEBATE",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "Director")
    with_judge = run_with_strategy(
        engine, registry2, agent.id, "direct_company", "Why did it fail?", "v1", str(uuid4())
    )
    assert TERTIARY in adapter2.models_asked()
    judge_prompt = next(prompt for model, prompt in adapter2.calls if model == TERTIARY)
    assert "independent third opinion" in judge_prompt
    assert "You decide nothing" in judge_prompt
    with Session(engine) as session:
        row = session.scalars(
            select(LlmCollaboration).order_by(LlmCollaboration.created_at.desc())
        ).first()
        assert row.tertiary_run_id is not None
    assert with_judge["model_name"] == PRIMARY


# --------------------------------------------------------------- 17-22: the record


def test_17_the_record_names_every_model_that_took_part(engine, staffed):
    """A decision the studio cannot explain later is a decision nobody can review."""
    registry, adapter = with_models(engine, staffed, three())
    configure(
        engine,
        "Director",
        primary=PRIMARY,
        secondary=SECONDARY,
        tertiary=TERTIARY,
        strategy="REVIEW",
        policy="ALWAYS",
    )
    agent = agent_of(engine, "Director")
    run_with_strategy(
        engine,
        registry,
        agent.id,
        "direct_company",
        "Decide.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
    )
    traced = collaborations(engine, agent.id)
    assert len(traced) == 1
    entry = traced[0]
    assert entry["strategy"] == "REVIEW"
    assert entry["importance"] == "STRATEGIC"
    assert entry["reason"]
    assert entry["final_model"] == PRIMARY
    assert entry["latency_ms"] is not None
    assert entry["prompt_tokens"] and entry["completion_tokens"]
    parts = {role: data["model"] for role, data in entry["models"].items()}
    assert parts["PRIMARY"] == PRIMARY and parts["CRITIC"] == SECONDARY
    assert all(data["run_id"] for data in entry["models"].values())


def test_18_and_19_the_page_shows_the_configuration_and_a_change_takes_effect(
    engine, client, headers, staffed
):
    """The interface and the backend are one configuration. What the page saves is what the
    next execution uses, and the page reads back exactly what was saved."""
    registry, adapter = with_models(engine, staffed, three())
    client.app.app.state.registry = registry
    ids = model_ids(engine)
    agent = agent_of(engine, "Publisher")

    saved = client.put(
        f"/api/v1/settings/agents/{agent.id}/model",
        headers=headers,
        json={
            "model_id": ids[PRIMARY],
            "expected_version": agent.version,
            "secondary_model_id": ids[SECONDARY],
            "multi_llm_strategy": "FALLBACK",
            "additional_llm_policy": "ALWAYS",
            "min_importance": "ROUTINE",
        },
    )
    assert saved.status_code == 200
    listed = client.get("/api/v1/agents/", headers=headers).json()
    shown = next(row for row in listed["agents"] if row["id"] == agent.id)
    assert shown["model_id"] == ids[PRIMARY]
    assert shown["secondary_model_id"] == ids[SECONDARY]
    assert shown["multi_llm_strategy"] == "FALLBACK"
    assert shown["additional_llm_policy"] == "ALWAYS"
    assert shown["min_importance"] == "ROUTINE"

    # The saved strategy is what the next execution actually does.
    broken, adapter2 = with_models(engine, staffed, three(), fails={PRIMARY})
    agent = agent_of(engine, "Publisher")
    result = run_with_strategy(
        engine, broken, agent.id, "prepare_publication", "Prepare it.", "v1", str(uuid4())
    )
    assert adapter2.models_asked() == [PRIMARY, SECONDARY]
    assert result["model_name"] == SECONDARY


def test_20_history_keeps_the_model_that_actually_answered(engine, staffed):
    """Changing a slot today must not rewrite what yesterday was answered by."""
    registry, adapter = with_models(engine, staffed, three())
    configure(engine, "Accountant", primary=PRIMARY)
    from app.agents.services import run_agent_task

    agent = agent_of(engine, "Accountant")
    old = run_agent_task(
        engine, registry, agent.id, "reconcile_day", "Close the books.", "v1", str(uuid4())
    )
    configure(engine, "Accountant", primary=TERTIARY)
    with Session(engine) as session:
        assert session.get(AgentRun, old["id"]).model_name == PRIMARY
        assert session.get(Agent, agent.id).model_id == model_ids(engine)[TERTIARY]


def test_21_a_failed_review_is_recorded_as_incomplete_not_filled_in(engine, staffed):
    """Never a fabricated critique. If the reviewer cannot answer, the review did not happen,
    the answer still stands, and the caller is told so it can lower its own confidence."""
    registry, adapter = with_models(engine, staffed, three(), fails={SECONDARY})
    configure(engine, "Director", primary=PRIMARY, secondary=SECONDARY, strategy="REVIEW")
    agent = agent_of(engine, "Director")
    result = run_with_strategy(
        engine,
        registry,
        agent.id,
        "direct_company",
        "Decide.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
        require_review=True,
    )
    assert result["status"] == "SUCCEEDED", "the employee's own answer still stands"
    assert result["output_text"] == three()[PRIMARY]
    assert result["collaboration"]["outcome"] == "REVIEW_INCOMPLETE"
    assert result["collaboration"]["review_incomplete"] is True
    with Session(engine) as session:
        row = session.scalars(select(LlmCollaboration)).first()
        assert row.outcome == "REVIEW_INCOMPLETE"
        assert row.disagreement_note and "neverificată" in row.disagreement_note
        critic = session.get(AgentRun, row.secondary_run_id)
        assert critic.status == "FAILED" and not critic.output_text


def test_22_identities_permissions_and_the_existing_pipeline_still_hold(engine, staffed):
    """The slots changed nothing else: the identity is still composed the same way, the
    policy kernel still gates a run, and a model a role's capabilities do not allow cannot be
    put in any slot."""
    from app.agents.identity import compose_identity

    registry, adapter = with_models(engine, staffed, three())
    configure(engine, "Director", primary=PRIMARY, secondary=SECONDARY, strategy="REVIEW")
    agent = agent_of(engine, "Director")
    with Session(engine) as session:
        row = session.get(Agent, agent.id)
        identity = compose_identity(session, row, task_type="direct_company")
    assert identity.system and "Director" in identity.system
    assert identity.context

    # The Owner's stop still outranks everything, including a configured critic.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    blocked = run_with_strategy(
        engine,
        registry,
        agent.id,
        "direct_company",
        "Decide.",
        "v1",
        str(uuid4()),
        importance="STRATEGIC",
    )
    assert blocked["status"] == "BLOCKED_POLICY"
    assert adapter.models_asked() == [], "nothing was asked of any model"

    # And a slot cannot hold a model the role's required capabilities exclude.
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        from app.agents.models import Capability, ModelCapability

        capability = session.scalar(select(Capability).where(Capability.name == "vision"))
        if capability is None:
            capability = Capability(id=str(uuid4()), name="vision", description="sees frames")
            session.add(capability)
            session.flush()
        from app.agents.models import RoleCapability

        session.add(
            RoleCapability(
                role_id=session.get(Agent, agent.id).role_id,
                capability_id=capability.id,
                requirement_level="REQUIRED",
            )
        )
        session.flush()
        primary_id = model_ids(engine)[PRIMARY]
        session.add(
            ModelCapability(model_id=primary_id, capability_id=capability.id, confidence="DECLARED")
        )
    ids = model_ids(engine)
    fresh = agent_of(engine, "Director")
    with pytest.raises(ValueError, match="capabilit"):
        assign_agent(
            engine,
            fresh.id,
            ids[PRIMARY],
            fresh.version,
            secondary_model_id=ids[SECONDARY],
            multi_llm_strategy="REVIEW",
        )
