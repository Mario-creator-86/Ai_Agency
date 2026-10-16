"""«Context pe sarcină» (the Owner, 2026-10-16): each call is told what its task needs.

Every employee is told who it is and the Owner's policies on every call. Beyond that a judge or a
narrow task (BARE) is told nothing; a writer or a decider (CRAFT) gets the contract sections, the
memory tied to its subject and the classes its need names, within a fixed budget and in whole
records; the mail tasks (INBOX) read one thread, or a page of the inbox, as their data. Asks of
closed films expire with an event that says why; repeated asks collapse into the newest.

Local tests with a scripted model; nothing is sent to a provider.
"""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.director import director_review
from app.agents.identity import (
    IDENTITY_VERSION,
    INBOX_TASKS,
    MEMORY_BUDGET_CHARS,
    PROFILE_BARE,
    PROFILE_CRAFT,
    PROFILE_INBOX,
    TASK_CONTEXT,
    compose_identity,
    task_context,
)
from app.agents.inbox import (
    DUPLICATE,
    EPISODE_CLOSED,
    EXPIRED,
    EXPIRED_EVENT,
    FILM_CLOSED,
    INBOX_PAGE_CHARS,
    STALE_ASK_DAYS,
    expire_stale_asks,
    inbox_page,
)
from app.agents.mail import answer_mail, correspondence_round
from app.agents.memory import remember
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord, ModelRecord, Role
from app.agents.services import run_agent_task, seed_initial_workforce
from app.media.models import Storyboard
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from app.story.models import DailyStudioLog, StoryEpisode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_production_policy import make_storyboard

BACKEND = Path(__file__).resolve().parents[1] / "backend"

#: The Owner's policy every identity must carry, however much newer memory there is.
POLICY = "The Owner approves on the shooting sheet every paid step above 50 USD."


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "system": kwargs.get("system")})
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def staffed(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(staffed, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


def identity_of(engine, agent_id, task_type, subject=None):
    with Session(engine) as session:
        agent = session.get(Agent, agent_id)
        return compose_identity(session, agent, task_type=task_type, subject=subject)


def ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


# --------------------------------------------------------------------------- the profiles


def _task_types_in_code() -> set[str]:
    """Every task type a call site names as a string or a module constant."""
    names = {"run_agent_task", "structured_run", "run_with_strategy"}
    found: set[str] = set()
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in names or len(node.args) < 4:
                continue
            arg = node.args[3]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in constants:
                found.add(constants[arg.id])
    return found


def test_every_task_type_the_studio_calls_is_classified():
    """The table is the one place a task's context is decided: every call site's task type is
    in it (a task nobody classified would get BARE, but silently)."""
    in_code = _task_types_in_code()
    # The ones passed through a variable at their call site (`reviews._run`, the repurchase
    # gate, `prompt_agent._run`, the Owner's chat).
    in_code |= {
        "review_narration",
        "review_failed_render",
        "repurchase_verdict",
        "repurchase_decision",
        "shot_prompts",
        "visual_bible",
        "owner_chat",
        "director_film_reasons_read",
    }
    assert in_code - set(TASK_CONTEXT) == set()
    assert len(in_code) >= 35


def test_each_task_gets_its_profile_and_every_craft_task_names_its_need():
    for task in (
        "director_prompt_audit",
        "director_rewrite_review",
        "director_second_look",
        "director_scene_brief",
        "prompt_lesson_reading",
        "still_qc",
        "clip_qc",
        "verify_claim",
        "episode_review",
        "editorial_judgement",
        "scene_prompt_rewrite",
        "direct_company:critique",
        "direct_company:judge",
        "something_nobody_classified",
        "",
    ):
        assert task_context(task).profile == PROFILE_BARE, task
    for task in (
        "write_script",
        "write_episode",
        "shot_prompts",
        "direct_company",
        "direct_company:final",
        "direct_company:peer",
        "choose_topic",
        "propose_topics",
        "owner_chat",
        "director_qc_review",
    ):
        assert task_context(task).profile == PROFILE_CRAFT, task
    assert INBOX_TASKS == {"answer_mail", "director_review"}
    for task in INBOX_TASKS:
        assert task_context(task).profile == PROFILE_INBOX
    for name, ctx in TASK_CONTEXT.items():
        assert len(ctx.why) > 30, name  # one line that says why
        if ctx.profile == PROFILE_BARE:
            assert not (ctx.recall or ctx.subject_memory or ctx.direction or ctx.contract), name


def test_a_judge_is_told_who_it_is_and_the_owners_policies_and_nothing_else(engine, staffed):
    sarah = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        remember(session, memory_class="OWNER_POLICY", content=POLICY, source_type="owner")
        remember(
            session,
            memory_class="AGENT_OPINION",
            content="Scene 2 of another film: the ledger read as writing.",
            source_type="system",
            agent_id=sarah.id,
        )
        remember(
            session, memory_class="STRATEGY", content="Strategy: boost space.", source_type="event"
        )
    identity = identity_of(engine, sarah.id, "director_prompt_audit", {"storyboard_id": "x" * 36})
    system = identity.system
    assert system.startswith("You are Sarah (Director), Director at AMN-AI")
    with Session(engine) as session:
        role = session.get(Role, sarah.role_id)
        assert f"MISSION: {role.mission}" in system
    assert "YOU MUST NEVER:" in system and "STANDING RULES:" in system
    assert POLICY in system
    assert "the ledger read as writing" not in system and "boost space" not in system
    assert "WHAT YOU REMEMBER" not in system
    assert "WATCH FOR:" not in system and "NEVER LET PASS:" not in system
    # Three lines of persona, not the habits and phrases.
    assert "YOUR CHARACTER:" in system and "Typical phrases" not in system
    context = identity.context
    assert context["profile"] == PROFILE_BARE
    assert context["identity_version"] == IDENTITY_VERSION == "identity-v4-task"
    assert context["subject"] == {"storyboard_id": "x" * 36}
    assert context["memory_tied_ids"] == [] and context["open_message_ids"] == []
    assert (
        context["owner_policy_ids"] and context["memory_record_ids"] == context["owner_policy_ids"]
    )


def test_a_contract_line_that_names_a_task_rides_with_that_task_only(engine, staffed):
    sarah = staffed["agents"]["Director"]
    review = identity_of(engine, sarah.id, "episode_review").system
    assert "(episode_review)" in review and "(editorial_judgement)" not in review
    judging = identity_of(engine, sarah.id, "editorial_judgement").system
    assert "(editorial_judgement)" in judging and "(episode_review)" not in judging
    audit = identity_of(engine, sarah.id, "director_prompt_audit").system
    assert "(episode_review)" not in audit
    marcus = staffed["agents"]["ScriptWriter"]
    script = identity_of(engine, marcus.id, "write_script").system
    assert "every LIVE scene is a paid shot" in script
    assert "(write_episode)" not in script, "the serial's line is the serial's"
    episode = identity_of(engine, marcus.id, "write_episode").system
    assert "(write_episode)" in episode
    chat = identity_of(engine, sarah.id, "owner_chat")
    assert chat.context["contract_sections"] == [
        "watch_for",
        "investigate",
        "correct",
        "let_pass",
        "never_let_pass",
        "escalate_when",
        "deliverables",
    ]
    assert "Show me the evidence" in chat.system, "the whole persona when she speaks as herself"


# --------------------------------------------------------------------------- the Owner's rules


def test_the_owners_policy_rides_every_call_even_under_200_newer_memories(engine, staffed):
    sarah = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        policy = remember(session, memory_class="OWNER_POLICY", content=POLICY, source_type="owner")
        policy.created_at = ago(days=30)
        policy_id = policy.id
        start = datetime.now(UTC) - timedelta(days=1)
        for number in range(200):
            session.add(
                MemoryRecord(
                    id=str(uuid4()),
                    agent_id=sarah.id if number % 2 else None,
                    memory_class="AGENT_OPINION" if number % 2 else "STRATEGY",
                    content=f"Newer record {number}: " + "words " * 40,
                    source_type="system",
                    created_at=(start + timedelta(minutes=number)).isoformat(),
                )
            )
    for task in ("director_prompt_audit", "direct_company", "owner_chat", "director_review"):
        identity = identity_of(engine, sarah.id, task)
        assert POLICY in identity.system, task
        assert policy_id in identity.context["owner_policy_ids"], task
        assert policy_id in identity.context["memory_record_ids"], task
        assert identity.context["memory_chars"] <= MEMORY_BUDGET_CHARS, task


# --------------------------------------------------------------------------- no inbox


def test_no_letter_rides_a_bare_or_craft_identity_and_the_inbox_tasks_add_none(engine, staffed):
    sarah, marcus = staffed["agents"]["Director"], staffed["agents"]["ScriptWriter"]
    with Session(engine) as session, session.begin():
        for i in range(5):
            post_message(
                session,
                intent="HANDOFF",
                subject=f"Rescris: episode {i}",
                body={"episode_id": str(uuid4())},
                body_text=f"ASK TEXT {i} whole.",
                from_agent_id=sarah.id,
                to_agent_id=marcus.id,
            )
        post_message(
            session,
            intent="STATUS",
            subject="Remediere foaie: RESOLVED",
            body={},
            body_text="A REPORT TEXT.",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        weekly = post_message(
            session,
            intent="HANDOFF",
            subject="Indicațiile Directorului pentru departamentul de scris — 2026-S42",
            body={"instructions": "Open on a stake.", "week": "2026-S42", "department": "scris"},
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        weekly_id = weekly.id
    for task in ("write_script", "write_episode", "verify_claim", "answer_mail", "", "owner_chat"):
        identity = identity_of(engine, marcus.id, task)
        assert "ASK TEXT" not in identity.system, task
        assert "A REPORT TEXT" not in identity.system, task
        assert "WHAT IS ASKED OF YOU" not in identity.system, task
        assert identity.context["open_message_ids"] == [], task
    # The Director's standing weekly direction is not the inbox: it rides where a task names
    # it as a need (a writer's), and nowhere else.
    script = identity_of(engine, marcus.id, "write_script")
    assert "Open on a stake." in script.system
    assert script.context["direction_message_ids"] == [weekly_id]
    for task in ("verify_claim", "answer_mail", "choose_topic"):
        assert "Open on a stake." not in identity_of(engine, marcus.id, task).system, task
    # A mail task records the letters its data carries.
    mail = identity_of(engine, marcus.id, "answer_mail", {"message_ids": [weekly_id]})
    assert mail.context["profile"] == PROFILE_INBOX
    assert mail.context["open_message_ids"] == [weekly_id]


# --------------------------------------------------------------------------- the budget


def test_craft_memory_stays_within_its_budget_in_whole_records(engine, staffed):
    sarah = staffed["agents"]["Director"]
    long_words = "LONG " + "x" * (MEMORY_BUDGET_CHARS + 100)
    with Session(engine) as session, session.begin():
        start = datetime.now(UTC) - timedelta(hours=5)
        session.add(
            MemoryRecord(
                id=str(uuid4()),
                agent_id=None,
                memory_class="STRATEGY",
                content=long_words,
                source_type="system",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        for number in range(40):
            session.add(
                MemoryRecord(
                    id=str(uuid4()),
                    agent_id=None,
                    memory_class="STRATEGY",
                    content=f"Decision {number:02d}: "
                    + "measured words " * 40
                    + f"END{number:02d}",
                    source_type="system",
                    created_at=(start + timedelta(minutes=number)).isoformat(),
                )
            )
    identity = identity_of(engine, sarah.id, "direct_company")
    context = identity.context
    assert context["profile"] == PROFILE_CRAFT
    assert 0 < context["memory_chars"] <= MEMORY_BUDGET_CHARS
    assert context["memory_left_out"] >= 1
    assert "LONG xxx" not in identity.system, "a record longer than the budget is left out whole"
    with Session(engine) as session:
        told = [
            row
            for row in session.scalars(
                select(MemoryRecord).where(MemoryRecord.id.in_(context["memory_record_ids"]))
            )
            if row.memory_class == "STRATEGY"
        ]
    assert told
    for row in told:
        assert row.content in identity.system, "every record told is told whole"
    # Newest first: the told decisions are the newest that fit.
    numbers = sorted(int(row.content[9:11]) for row in told)
    assert numbers == list(range(40 - len(numbers), 40))


# --------------------------------------------------------------------------- the subject


def test_memory_tied_to_the_subject_comes_first(engine, staffed):
    """A writer's rows about the episode he works on come before his newest rows about others,
    whichever way they are tied: by their source, by their words, by the run that wrote them
    (its recorded subject) or by the event they came from."""
    marcus = staffed["agents"]["ScriptWriter"]
    episode_id, other = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        run = AgentRun(
            id=str(uuid4()),
            agent_id=marcus.id,
            task_type="write_episode",
            objective="...",
            prompt_template_version="v",
            model_name="m",
            provider_name="p",
            status="SUCCEEDED",
            correlation_id=str(uuid4()),
            started_at=utc_now(),
            context_json={"subject_ids": [episode_id]},
        )
        session.add(run)
        event = append_event(
            session, "story.episode_reviewed", "story_episode", episode_id, 1, {}, str(uuid4())
        )
        old = datetime.now(UTC) - timedelta(days=2)
        tied = [
            ("by source", {"source_type": "system", "source_id": episode_id}),
            (f"about episode {episode_id[:8]}, by its words", {"source_type": "system"}),
            ("by the run that wrote it", {"source_type": "run", "source_id": run.id}),
            ("by its event", {"source_type": "event", "event_id": event.event_id}),
        ]
        tied_ids = []
        for number, (words, provenance) in enumerate(tied):
            row = MemoryRecord(
                id=str(uuid4()),
                agent_id=marcus.id,
                memory_class="AGENT_OPINION",
                content=f"TIED {words}.",
                created_at=(old + timedelta(minutes=number)).isoformat(),
                **provenance,
            )
            session.add(row)
            tied_ids.append(row.id)
        for number in range(30):
            session.add(
                MemoryRecord(
                    id=str(uuid4()),
                    agent_id=marcus.id,
                    memory_class="AGENT_OPINION",
                    content=f"UNTIED note {number} about episode {other[:8]}.",
                    source_type="system",
                    source_id=other,
                    created_at=ago(minutes=30 - number),
                )
            )
    identity = identity_of(engine, marcus.id, "write_episode", {"episode_id": episode_id})
    system = identity.system
    assert sorted(identity.context["memory_tied_ids"]) == sorted(tied_ids)
    first_untied = system.index("UNTIED")
    for words, _provenance in tied:
        assert system.index(f"TIED {words}.") < first_untied, words
    # Without a subject the same task falls back to its classes by recency: the newest first.
    plain = identity_of(engine, marcus.id, "write_episode")
    assert plain.context["memory_tied_ids"] == []
    assert plain.system.index("UNTIED note 29") < plain.system.index("UNTIED note 0")
    # A judge given the same subject is told none of it.
    sarah = staffed["agents"]["Director"]
    judge = identity_of(engine, sarah.id, "episode_review", {"episode_id": episode_id})
    assert "TIED" not in judge.system
    assert judge.context["memory_record_ids"] == judge.context["owner_policy_ids"]


# --------------------------------------------------------------------------- stale asks


def _day_log(session) -> str:
    log = DailyStudioLog(
        id=str(uuid4()),
        business_date="2026-10-15",
        timezone="Europe/Bucharest",
        event_counts_json={},
        total_events=0,
        roster_json=[],
        notable_events_json=[],
        status="CLOSED",
        closed_at=utc_now(),
    )
    session.add(log)
    session.flush()
    return log.id


def _episode(session, log_id: str, status: str, rewrite_of: str | None = None) -> str:
    row = StoryEpisode(
        id=str(uuid4()),
        log_id=log_id,
        title=f"Episode {status}",
        beats_json=[],
        grounded_event_ids_json=[],
        continuity_json={},
        status=status,
        created_at=utc_now(),
        rewrite_of_id=rewrite_of,
    )
    session.add(row)
    session.flush()
    return row.id


def test_stale_asks_expire_with_their_reason_and_repeats_collapse(engine, staffed, tmp_path):
    sarah, kael, marcus = (
        staffed["agents"]["Director"],
        staffed["agents"]["VideoEditor"],
        staffed["agents"]["ScriptWriter"],
    )
    closed_film = make_storyboard(engine, tmp_path)
    live_film = make_storyboard(engine, tmp_path)
    ids: dict[str, str] = {}
    with Session(engine) as session, session.begin():
        # A storyboard refused before anything was rendered is a closed film.
        session.get(Storyboard, closed_film).status = "REJECTED"
        log_id = _day_log(session)
        replaced = _episode(session, log_id, "REJECTED")
        _episode(session, log_id, "DRAFT", rewrite_of=replaced)

        def ask(key, *, to=kael, sender=sarah, intent="HANDOFF", when=None, **body):
            row = post_message(
                session,
                intent=intent,
                subject=body.pop("subject", f"Ask {key}"),
                body=body,
                body_text=body.pop("text", f"Do {key}."),
                from_agent_id=sender.id if sender else None,
                to_agent_id=to.id,
            )
            if when:
                row.created_at = when
            ids[key] = row.id

        ask("closed film", storyboard_id=closed_film, subject="Refăcut: closed")
        ask("closed film, worker's", storyboard_id=closed_film, executed_by_worker=True)
        ask("live film", storyboard_id=live_film, subject="Refăcut: live")
        ask("replaced episode", to=marcus, episode_id=replaced, subject="Rescris: old")
        ask("repeat old", to=marcus, subject="Same ask", text="Same words.", when=ago(hours=2))
        ask("repeat new", to=marcus, subject="Same ask", text="Same words.", when=ago(hours=1))
        ask("old", intent="REQUEST_INFO", when=ago(days=STALE_ASK_DAYS, hours=1))
        ask("fresh", intent="REQUEST_INFO", when=ago(days=STALE_ASK_DAYS - 1))
        ask("owner's old", sender=None, intent="REQUEST_INFO", when=ago(days=30))
        ask("decision's old", when=ago(days=30), matter_key="renders_failed", decision="ITERATE")
        ask("worker's old", when=ago(days=30), executed_by_worker=True)
        for week, when in (("2026-S40", ago(days=14)), ("2026-S41", ago(days=7))):
            ask(
                f"weekly {week}",
                subject=f"Indicațiile Directorului pentru departamentul de video — {week}",
                instructions=f"Direction {week}.",
                week=week,
                when=when,
            )

    result = expire_stale_asks(engine)

    expected = {
        "closed film": FILM_CLOSED,
        "closed film, worker's": FILM_CLOSED,
        "replaced episode": EPISODE_CLOSED,
        "repeat old": DUPLICATE,
        "old": EXPIRED,
        "weekly 2026-S40": DUPLICATE,
    }
    assert sorted(result["expired"]) == sorted(ids[key] for key in expected)
    with Session(engine) as session:
        for key, message_id in ids.items():
            row = session.get(AgentMessage, message_id)
            if key not in expected:
                assert row.status == "OPEN", key
                continue
            # Answered, not resolved: code that later resolves its own letter still may.
            assert row.status == "ANSWERED", key
            assert row.resolution.startswith("Închisă de studio:"), key
            event = session.scalar(
                select(DomainEvent).where(
                    DomainEvent.event_type == EXPIRED_EVENT,
                    DomainEvent.aggregate_id == message_id,
                )
            )
            assert event is not None and event.payload["reason"] == expected[key], key
        assert "publicat sau închis" in session.get(AgentMessage, ids["closed film"]).resolution
        dup = session.get(AgentMessage, ids["repeat old"])
        assert "rămâne deschisă numai cea mai nouă" in dup.resolution
    # Nothing left to close: a second sweep writes nothing.
    assert expire_stale_asks(engine) == {"expired": [], "by_reason": {}}


def test_the_mail_round_closes_stale_asks_before_answering(engine, staffed, tmp_path):
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    board = make_storyboard(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board).status = "REJECTED"
        stale = post_message(
            session,
            intent="HANDOFF",
            subject="Refăcut: a closed film",
            body={"storyboard_id": board},
            body_text="Redo scene 2.",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        )
        stale_id = stale.id
    registry, model = registry_with(staffed, lambda prompt: "{}")
    result = correspondence_round(engine, registry)
    assert result["expired"] == [stale_id]
    assert result["answered"] == [] and model.calls == [], "nobody answers a closed film's ask"


# --------------------------------------------------------------------------- the inbox, paged


def test_an_inbox_page_holds_whole_letters_within_its_budget():
    letters = [f"L{i}:" + "x" * 9_000 for i in range(5)]
    page, waiting = inbox_page(letters, len, budget=20_000)
    assert page == letters[:2] and waiting == letters[2:]
    alone, rest = inbox_page(["y" * 50_000, "z"], len, budget=20_000)
    assert alone == ["y" * 50_000] and rest == ["z"], "a letter longer than the page goes alone"


def test_the_directors_review_reads_a_page_and_no_run_fails_on_size(engine, staffed):
    sarah = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        for i in range(12):
            post_message(
                session,
                intent="STATUS",
                subject=f"Report {i}",
                body={"stage": f"stage {i}", "detail": "d" * 9_000},
                body_text=f"REPORT {i} whole.",
                from_agent_id=sarah.id,
                to_agent_id=None,
            )
        # Her own pile: 150 big letters addressed to her, which no identity carries now.
        for i in range(150):
            post_message(
                session,
                intent="REQUEST_REVIEW",
                subject=f"Blocaje foaie {i}",
                body={"issues": ["i" * 5_000]},
                body_text=f"PILE {i}.",
                from_agent_id=None,
                to_agent_id=sarah.id,
            )

    def answer(prompt):
        shown = json.loads(
            prompt.split('hash="director-inbox">\n', 1)[1].rsplit("\n</untrusted", 1)[0]
        )
        return json.dumps(
            {
                "summary": "Read.",
                "decisions": [
                    {"message_id": m["id"], "action": "ACKNOWLEDGE", "note": ""}
                    for m in shown["inbox"]
                ],
                "priorities": [],
            }
        )

    registry, model = registry_with(staffed, answer)
    review = director_review(engine, registry, str(uuid4()))
    call = model.calls[-1]
    page = json.loads(
        call["prompt"].split('hash="director-inbox">\n', 1)[1].rsplit("\n</untrusted", 1)[0]
    )["inbox"]
    assert 1 <= len(page) < 12 and review["reviewed"] == len(page)
    assert sum(len(json.dumps(m, ensure_ascii=False)) for m in page) <= INBOX_PAGE_CHARS
    for letter in page:
        assert letter["body_json"]["detail"] == "d" * 9_000, "a letter is never cut"
    assert "PILE" not in call["system"] and len(call["system"]) < 12_000
    with Session(engine) as session:
        run = session.get(AgentRun, review["run_id"])
        assert run.status == "SUCCEEDED"
        assert run.context_json["profile"] == PROFILE_INBOX
        assert run.context_json["open_message_ids"] == [m["id"] for m in page]


def test_a_letter_is_answered_with_its_thread_alone_whatever_the_pile(engine, staffed):
    """2026-10-15: Marcus's answer_mail failed 51 times in 103 on the model's window — every
    open letter rode his identity. Now the letter and its thread are the task, and only them."""
    sarah, marcus = staffed["agents"]["Director"], staffed["agents"]["ScriptWriter"]
    with Session(engine) as session, session.begin():
        for i in range(70):
            post_message(
                session,
                intent="HANDOFF",
                subject=f"Other matter {i}",
                body={"evidence": "e" * 8_000},
                body_text=f"OTHER {i}.",
                from_agent_id=sarah.id,
                to_agent_id=marcus.id,
            )
        first = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Which hook?",
            body={},
            body_text="EARLIER LETTER of the thread.",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Re: Which hook?",
            body={},
            body_text="THE LETTER: which hook did you keep?",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
            in_reply_to=first.id,
        )
        asked_id, first_id = asked.id, first.id
    registry, model = registry_with(
        staffed, lambda prompt: json.dumps({"reply": "The mirror hook, Sarah.", "done": True})
    )
    sent = answer_mail(engine, registry, asked_id)
    call = model.calls[-1]
    assert "THE LETTER" in call["prompt"] and "EARLIER LETTER" in call["prompt"]
    assert "OTHER" not in call["prompt"] and "OTHER" not in call["system"]
    assert len(call["system"]) < 12_000
    with Session(engine) as session:
        run = session.get(AgentRun, sent["run_id"])
        assert run.status == "SUCCEEDED" and run.task_type == "answer_mail"
        assert run.context_json["profile"] == PROFILE_INBOX
        assert sorted(run.context_json["open_message_ids"]) == sorted([asked_id, first_id])
        assert run.context_json["subject"]["thread_id"] == first_id


# --------------------------------------------------------------------------- the manifest


def test_the_run_records_its_profile_sizes_and_what_it_was_told(engine, staffed):
    marcus = staffed["agents"]["ScriptWriter"]
    with Session(engine) as session, session.begin():
        remember(session, memory_class="OWNER_POLICY", content=POLICY, source_type="owner")
    registry, _ = registry_with(staffed, lambda prompt: "ok")
    topic = str(uuid4())
    for task, profile in (
        ("write_script", PROFILE_CRAFT),
        ("verify_claim", PROFILE_BARE),
        ("TEST_CONNECTIVITY", PROFILE_BARE),
    ):
        result = run_agent_task(
            engine,
            registry,
            marcus.id,
            task,
            "Do the work.",
            "v1",
            str(uuid4()),
            subject={"topic_id": topic},
        )
        with Session(engine) as session:
            context = session.get(AgentRun, result["id"]).context_json
        assert context["identity_version"] == "identity-v4-task", task
        assert context["profile"] == profile, task
        assert context["identity_chars"] == context["system_chars"] > 0, task
        assert context["subject"] == {"topic_id": topic} and context["subject_ids"] == [topic]
        assert context["owner_policy_ids"] and set(context["owner_policy_ids"]) <= set(
            context["memory_record_ids"]
        )
        assert context["open_message_ids"] == []
        assert "memory_tied_ids" in context and "memory_chars" in context


# --------------------------------------------------------------------------- the measurement


def test_the_offline_measurement_reads_a_copy_and_never_builds_a_registry(
    engine, staffed, tmp_path, capsys
):
    """`scripts/identity_size.py` composes v3 and v4 on a COPY of a backup and asks no model."""
    import importlib.util
    import shutil

    registry, _ = registry_with(staffed, lambda prompt: "ok")
    sarah = staffed["agents"]["Director"]
    run_agent_task(
        engine, registry, sarah.id, "director_prompt_audit", "Audit.", "v1", str(uuid4())
    )
    database = Path(str(engine.url.database))
    backups = tmp_path / "backups"
    backups.mkdir()
    for suffix in ("", "-wal", "-shm"):
        part = Path(str(database) + suffix)
        if part.exists():
            shutil.copyfile(part, backups / f"studio-20261016T000000Z.db{suffix}")
    spec = importlib.util.spec_from_file_location(
        "identity_size", BACKEND.parent / "scripts" / "identity_size.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    measured = module.measure

    def measure_without_registry(*args, **kwargs):
        with pytest.raises(RuntimeError, match="never builds a model registry"):
            ProviderRegistry()
        return measured(*args, **kwargs)

    module.measure = measure_without_registry
    opened: list[str] = []
    real_engine = module.create_engine

    def recording_engine(url, *args, **kwargs):
        opened.append(str(url))
        return real_engine(url, *args, **kwargs)

    module.create_engine = recording_engine

    def folder_digest(folder: Path) -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.iterdir())
        }

    before = folder_digest(backups)
    out = tmp_path / "result.json"
    work = tmp_path / "work"
    assert module.main(["--backups", str(backups), "--work", str(work), "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "| director_prompt_audit | BARE | 1 |" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    row = data["per_task"]["director_prompt_audit"]
    assert row["old"] > row["new"] > 0
    # The copy is what was opened, read-only; the backups folder is byte for byte as it was;
    # the copy is gone afterwards; the asks are counted at the backup's own time.
    copy = (work / "studio-20261016T000000Z.db").as_posix()
    assert opened == [f"sqlite:///file:{copy}?mode=ro&uri=true"]
    assert folder_digest(backups) == before
    assert not list(work.iterdir()), "the work copy is cleaned"
    assert data["stale_asks_at"] == "2026-10-16T00:00:00+00:00"
    ProviderRegistry()  # put back as it was
