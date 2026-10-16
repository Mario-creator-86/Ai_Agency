"""«Context pe sarcină», amended (2026-10-16): the context a task needs reaches it.

The Owner's decision gives each call its role, his rules and only what its task needs, and the
inbox to the mail tasks only. Four reviews of the first version found the context some tasks
need had been lost with the inbox, and his rules told in a way that read as the wrong state.
Each test here guards one of those:

- the Director's company decisions (`agents.command._assign`) reach the work of the department
  they direct while their letter is open, beside her weekly letter;
- a standing direction is never left out, whatever its size: its size is logged and recorded;
- a weekly letter of the old format and the new one to the same department share one key;
- only the Owner's current rule on each matter is pinned, with the hour he set it; a rule he
  replaced is not told, his decisions on one thing go where that thing is the work, and none
  of his rows is changed;
- the Director's QC review reads her earlier reviews of the film; her direct_company and topic
  choice read the priorities her last daily review set;
- the sound plan names its film; an Owner's letter is answered with what the employee
  remembers of what it names; the episode writer is told the platform and the money;
- the stale-ask sweep keeps asks about films in work, writes nothing while autonomy is
  stopped, and never takes the mail round or her review down with it.

Local tests with scripted models; nothing is sent to a provider.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.agents import inbox as inbox_module
from app.agents.command import Choice, _assign
from app.agents.director import director_review
from app.agents.identity import (
    DIRECTION_BUDGET_CHARS,
    MEMORY_BUDGET_CHARS,
    PROFILE_CRAFT,
    TASK_CONTEXT,
    standing_direction,
)
from app.agents.inbox import (
    DUPLICATE,
    EXPIRED,
    FILM_CLOSED,
    STALE_ASK_DAYS,
    expire_stale_asks,
    stale_asks,
    weekly_department,
)
from app.agents.mail import answer_mail, correspondence_round
from app.agents.memory import (
    POLICY_DECISION,
    POLICY_IN_FORCE,
    POLICY_SUPERSEDED,
    owner_policy_rows,
    remember,
)
from app.agents.messages import post_message
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord, Role
from app.analytics.models import DirectorDecision
from app.media.models import Storyboard
from app.models import OwnerPolicy
from app.schemas import AutonomyModeCommand, EnvironmentCommand, PolicyCommand
from app.services import (
    MODE_MEMORY,
    PAID_MEDIA_MEMORY,
    PaidMediaApprovalCommand,
    change_autonomy_mode,
    change_environment,
    change_paid_media_approval,
    change_stop,
    utc_now,
)
from app.story.services import decide_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_context_profiles import (  # noqa: F401 - `staffed` is a fixture
    _day_log,
    _episode,
    ago,
    identity_of,
    registry_with,
    staffed,
)
from test_production_policy import make_storyboard

STATE = {"pipeline": {"stages": {"published": 3}}}


def _matter(key: str, observation: str) -> dict:
    return {
        "matter_key": key,
        "observation": observation,
        "evidence": {"films": 3},
        "scope": "STUDIO",
        "channel_id": None,
        "review_after_videos": 3,
    }


def _decide(engine, team, role: str, key: str, action: str) -> dict:
    sarah = team["agents"]["Director"]
    choice = Choice(matter_key=key, decision="ITERATE", confidence="MEDIUM", action=action)
    return _assign(
        engine,
        sarah.id,
        _matter(key, f"Observed for {role}: three films lost the viewer early."),
        choice,
        action,
        role,
        str(uuid4()),
        None,
        STATE,
    )


# --------------------------------------------------------------------------- C0/C6


def test_her_company_decision_reaches_the_work_of_the_department_it_directs(engine, staffed):  # noqa: F811
    """direct_company's `_assign` files a HANDOFF «kind: direction» with «DE FĂCUT: …». The
    decision's review after N films measures that action, so the department's work is told it
    while the letter is open — beside the weekly letter, not through the inbox."""
    work = {
        "ScriptWriter": ("write_script", "write_episode"),
        "VideoEditor": ("shot_prompts", "visual_bible"),
        "VoiceArtist": ("sound_design",),
    }
    decided = {}
    for role in work:
        action = f"ACTION FOR {role}: shorten the setup and move the reveal earlier."
        decided[role] = _decide(engine, staffed, role, f"retention_{role.lower()}", action)
    with Session(engine) as session:
        letters = {
            row.to_agent_id: row
            for row in session.scalars(select(AgentMessage).where(AgentMessage.intent == "HANDOFF"))
        }
    for role, tasks in work.items():
        agent = staffed["agents"][role]
        letter = letters[agent.id]
        assert letter.body_json["kind"] == "direction" and letter.status == "OPEN"
        for task in tasks:
            identity = identity_of(engine, agent.id, task)
            # The whole letter, on one line: observation, decision and what to do.
            assert f"DE FĂCUT: ACTION FOR {role}: shorten the setup" in identity.system, task
            assert "OBSERVAȚIE: Observed for" in identity.system, task
            assert identity.context["decision_message_ids"] == [letter.id], task
            assert identity.context["open_message_ids"] == [], task
        # A judge, the mail task (whose data is the letter) and the inspector's view are not
        # told it; nor is another department.
        for task in ("review_narration", "verify_claim", "answer_mail", ""):
            assert f"ACTION FOR {role}" not in identity_of(engine, agent.id, task).system, task
    kael = staffed["agents"]["VideoEditor"]
    assert "ACTION FOR ScriptWriter" not in identity_of(engine, kael.id, "shot_prompts").system

    # The decision reviewed, the letter no longer rides (it lingers only); a newer decision on
    # the same matter replaces the older; a closed letter rides nowhere.
    marcus = staffed["agents"]["ScriptWriter"]
    newer = _decide(engine, staffed, "ScriptWriter", "retention_scriptwriter", "NEWER ACTION.")
    script = identity_of(engine, marcus.id, "write_script")
    assert "NEWER ACTION." in script.system
    assert "ACTION FOR ScriptWriter" not in script.system
    with Session(engine) as session, session.begin():
        session.get(DirectorDecision, newer["decision_id"]).state = "REVIEWED"
    assert "NEWER ACTION." not in identity_of(engine, marcus.id, "write_script").system
    with Session(engine) as session, session.begin():
        lyra_letter = session.get(AgentMessage, letters[staffed["agents"]["VoiceArtist"].id].id)
        lyra_letter.status = "RESOLVED"
    lyra = staffed["agents"]["VoiceArtist"]
    assert "ACTION FOR VoiceArtist" not in identity_of(engine, lyra.id, "sound_design").system


# --------------------------------------------------------------------------- C2


def _weekly(session, sarah, agent, department, week, words, *, legacy=False, when=None):
    body = {"instructions": words, "week": week}
    if not legacy:
        body["department"] = department
    row = post_message(
        session,
        intent="HANDOFF",
        subject=f"Indicațiile Directorului pentru departamentul de {department} — {week}",
        body=body,
        from_agent_id=sarah.id,
        to_agent_id=agent.id,
    )
    if when:
        row.created_at = when
    return row.id


def test_a_standing_direction_over_its_budget_is_told_whole_and_its_size_recorded(
    engine,
    staffed,  # noqa: F811
    caplog,
):
    """Nothing bounds a weekly field (the weekly answer's text limits are lifted when it is
    read), so a long letter is possible; it is never left out: told whole, logged, recorded."""
    sarah, marcus, kael = (
        staffed["agents"]["Director"],
        staffed["agents"]["ScriptWriter"],
        staffed["agents"]["VideoEditor"],
    )
    topics = "TOPICS " + "what to write about " * 110  # about 2,200 characters
    writing = "WRITING " + "how to write it, measured " * 105  # about 2,800
    video = "VIDEO " + "frame the subject legibly " * 185  # about 4,800
    with Session(engine) as session, session.begin():
        topics_id = _weekly(session, sarah, marcus, "scenarii", "2026-S42", topics)
        writing_id = _weekly(session, sarah, marcus, "scris", "2026-S42", writing)
        video_id = _weekly(session, sarah, kael, "video", "2026-S42", video)
    caplog.set_level(logging.WARNING, logger="studio.identity")
    script = identity_of(engine, marcus.id, "write_script")
    assert " ".join(topics.split()) in script.system and " ".join(writing.split()) in script.system
    assert sorted(script.context["direction_message_ids"]) == sorted([topics_id, writing_id])
    assert script.context["direction_chars"] > DIRECTION_BUDGET_CHARS
    assert script.context["direction_over_budget"] is True
    shots = identity_of(engine, kael.id, "shot_prompts")
    assert " ".join(video.split()) in shots.system
    assert shots.context["direction_message_ids"] == [video_id]
    assert shots.context["direction_over_budget"] is True
    assert any(r.getMessage() == "direction_over_budget" for r in caplog.records)
    # Within the budget nothing is said about it.
    plain = identity_of(engine, staffed["agents"]["VoiceArtist"].id, "sound_design")
    assert plain.context["direction_chars"] == 0 and plain.context["direction_over_budget"] is False


# --------------------------------------------------------------------------- C4


def test_an_old_format_weekly_letter_and_a_new_one_share_one_department(engine, staffed):  # noqa: F811
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        old_id = _weekly(
            session, sarah, kael, "video", "2026-S41", "OLD WEEK.", legacy=True, when=ago(days=7)
        )
        new_id = _weekly(session, sarah, kael, "video", "2026-S42", "NEW WEEK.")
    with Session(engine) as session:
        old, new = session.get(AgentMessage, old_id), session.get(AgentMessage, new_id)
        assert "department" not in old.body_json
        assert weekly_department(old) == weekly_department(new) == "video"
        agent = session.get(Agent, kael.id)
        assert [row.id for row in standing_direction(session, agent)] == [new_id]
        (stale,) = stale_asks(session)
        assert stale.message_id == old_id and stale.reason == DUPLICATE
    shots = identity_of(engine, kael.id, "shot_prompts")
    assert "NEW WEEK." in shots.system and "OLD WEEK." not in shots.system


# --------------------------------------------------------------------------- C3/C11


def _version(engine) -> int:
    with Session(engine) as session:
        return session.get(OwnerPolicy, 1).version


def test_only_his_current_rule_on_each_matter_is_pinned_with_the_hour_he_set_it(engine, staffed):  # noqa: F811
    """`remember` keeps one live row per text: when the Owner switches back to an earlier rule
    no new row is written, and the old row keeps its old time. Told newest-first as «in force»,
    the stop he cleared, the TEST he left and the mode he left read as the studio's state."""

    def mode(value):
        change_autonomy_mode(
            engine,
            AutonomyModeCommand(
                command_id=uuid4(), expected_version=_version(engine), autonomy_mode=value
            ),
        )

    def environment(value):
        change_environment(
            engine,
            EnvironmentCommand(
                command_id=uuid4(), expected_version=_version(engine), environment=value
            ),
        )

    def stop(value):
        change_stop(
            engine,
            PolicyCommand(command_id=uuid4(), expected_version=_version(engine), stopped=value),
        )

    def paid(usd):
        change_paid_media_approval(
            engine,
            PaidMediaApprovalCommand(
                command_id=uuid4(),
                expected_version=_version(engine),
                paid_media_approval="OVER_USD",
                over_usd=usd,
            ),
            issued_by="owner",
        )

    for value in ("SUPERVISED", "AUTONOMOUS_CEO", "SUPERVISED", "AUTONOMOUS_CEO"):
        mode(value)
    for value in ("PRODUCTION", "TEST", "PRODUCTION", "TEST", "PRODUCTION"):
        environment(value)
    for usd in (10.0, 50.0, 10.0, 50.0):
        paid(usd)
    for value in (True, False, True, False):
        stop(value)
    with Session(engine) as session:
        rows_before = {
            row.id: (row.content, row.invalidated_at)
            for row in session.scalars(
                select(MemoryRecord).where(MemoryRecord.memory_class == "OWNER_POLICY")
            )
        }
        policy = session.get(OwnerPolicy, 1)
        assert (policy.autonomy_mode, policy.environment, policy.autonomy_stopped) == (
            "AUTONOMOUS_CEO",
            "PRODUCTION",
            False,
        )
    with Session(engine) as session, session.begin():
        # As on the studio's copy: the CEO row was written weeks before he last set CEO.
        ceo = session.scalar(
            select(MemoryRecord).where(MemoryRecord.content == MODE_MEMORY["AUTONOMOUS_CEO"])
        )
        ceo.created_at = ago(days=30)
    sarah = staffed["agents"]["Director"]
    for task in ("repurchase_decision", "director_qc_review", "write_script", "answer_mail"):
        agent_id = sarah.id if task != "write_script" else staffed["agents"]["ScriptWriter"].id
        identity = identity_of(engine, agent_id, task)
        policy_block = identity.system.split("THE OWNER'S POLICIES", 1)[1].split("\n- ", 1)[1]
        policy_block = policy_block.split("STANDING RULES:", 1)[0]
        assert MODE_MEMORY["AUTONOMOUS_CEO"] in policy_block, task
        assert MODE_MEMORY["SUPERVISED"] not in identity.system, task
        assert "The studio is in PRODUCTION" in policy_block, task
        assert "The studio is in TEST" not in identity.system, task
        assert "cleared the autonomy stop" in policy_block, task
        assert "The Owner stopped autonomy" not in identity.system, task
        assert PAID_MEDIA_MEMORY["OVER_USD"].format(threshold="50") in policy_block, task
        assert PAID_MEDIA_MEMORY["OVER_USD"].format(threshold="10") not in identity.system, task
        assert "(the 4 in force now" in identity.system, task
        assert len(identity.context["owner_policy_ids"]) == 4, task
        assert len(identity.context["owner_policy_superseded_ids"]) == 4, task
    # Each line says the minute he last set the rule — the CEO line today, from his command,
    # not the row's month-old time.
    lines = identity.system.split("newest first):\n", 1)[1].splitlines()[:4]
    for line in lines:
        assert re.match(r"^- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\] ", line), line
    (ceo_line,) = [line for line in lines if MODE_MEMORY["AUTONOMOUS_CEO"] in line]
    assert ceo_line.startswith(f"- [{datetime.now(UTC).date().isoformat()} "), ceo_line
    with Session(engine) as session:
        # Selection only: every one of his rows is still there, unchanged and live.
        after = {
            row.id: (row.content, row.invalidated_at)
            for row in session.scalars(
                select(MemoryRecord).where(MemoryRecord.memory_class == "OWNER_POLICY")
            )
        }
        assert after == rows_before and all(gone is None for _c, gone in after.values())
        uses = {
            p.row.content: p.use
            for p in owner_policy_rows(
                session, session.get(Agent, sarah.id), session.get(Role, sarah.role_id)
            )
        }
        assert uses[MODE_MEMORY["SUPERVISED"]] == POLICY_SUPERSEDED
        assert uses[MODE_MEMORY["AUTONOMOUS_CEO"]] == POLICY_IN_FORCE


def test_his_decision_on_one_episode_goes_where_that_episode_is_the_work(engine, staffed):  # noqa: F811
    marcus, sarah = staffed["agents"]["ScriptWriter"], staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        log_id = _day_log(session)
        episode_id = _episode(session, log_id, "DRAFT")
    decide_episode(engine, episode_id, False, "OWNER NOTE: the cold open repeats yesterday's.")
    with Session(engine) as session:
        (row,) = session.scalars(
            select(MemoryRecord).where(MemoryRecord.memory_class == "OWNER_POLICY")
        ).all()
        assert row.agent_id == marcus.id
        role = session.get(Role, marcus.role_id)
        (classified,) = owner_policy_rows(session, session.get(Agent, marcus.id), role)
        assert classified.use == POLICY_DECISION
    # Not pinned to every call: not a judge's, not another film's script, not the Director's.
    for agent_id, task in (
        (marcus.id, "write_script"),
        (marcus.id, "verify_claim"),
        (marcus.id, ""),
        (sarah.id, "director_prompt_audit"),
    ):
        identity = identity_of(engine, agent_id, task)
        assert "OWNER NOTE" not in identity.system, task
        assert row.id not in identity.context["owner_policy_ids"], task
    # The rewrite of that episode is told it; the Owner's own chat with him too.
    rewrite = identity_of(
        engine, marcus.id, "write_episode", {"log_id": log_id, "episode_id": episode_id}
    )
    assert "OWNER NOTE: the cold open" in rewrite.system
    assert row.id in rewrite.context["memory_tied_ids"]
    assert rewrite.context["owner_decision_ids"] == [row.id]
    assert "OWNER NOTE" in identity_of(engine, marcus.id, "owner_chat").system


# --------------------------------------------------------------------------- C8


def test_her_qc_review_reads_her_earlier_reviews_of_this_film(engine, staffed):  # noqa: F811
    """The payload omits earlier_reviews and your_looks past 24,000 characters (77% of her
    runs on the 2026-10-16 copy); her rows tied to the storyboard are told instead."""
    sarah = staffed["agents"]["Director"]
    board, other = str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        run = AgentRun(
            id=str(uuid4()),
            agent_id=sarah.id,
            task_type="director_qc_review",
            objective="...",
            prompt_template_version="v",
            model_name="m",
            provider_name="p",
            status="SUCCEEDED",
            correlation_id=str(uuid4()),
            started_at=utc_now(),
            context_json={"subject_ids": [board]},
        )
        session.add(run)
        session.flush()
        for words, source in (
            ("Film QC r1 of “This film”: REPAIR — scene 3 still, the ledger read as text.", run.id),
            ("Second look at scene 3: candidate 2 approved, the ledger is blank.", run.id),
        ):
            remember(
                session,
                memory_class="AGENT_OPINION",
                content=words,
                source_type="run",
                source_id=source,
                agent_id=sarah.id,
            )
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=f"Film QC of another film {other[:8]}: ACCEPT.",
            source_type="system",
            source_id=other,
            agent_id=sarah.id,
        )
    identity = identity_of(
        engine, sarah.id, "director_qc_review", {"storyboard_id": board, "report_id": str(uuid4())}
    )
    assert identity.context["profile"] == PROFILE_CRAFT
    assert "REPAIR — scene 3 still" in identity.system
    assert "candidate 2 approved" in identity.system
    assert "another film" not in identity.system, "only this film's rows: recall is empty"
    assert len(identity.context["memory_tied_ids"]) == 2
    assert identity.context["memory_chars"] <= MEMORY_BUDGET_CHARS
    assert "storyboard" in TASK_CONTEXT["director_qc_review"].why


# --------------------------------------------------------------------------- C9


def test_her_last_daily_review_and_its_priorities_reach_her_management_work(engine, staffed):  # noqa: F811
    sarah = staffed["agents"]["Director"]
    with Session(engine) as session, session.begin():
        for when, words in ((ago(days=1), "OLDER REVIEW."), (ago(hours=2), "NEWEST REVIEW.")):
            row = remember(
                session,
                memory_class="AGENT_OPINION",
                content=f"Daily review: {words} Priorities: finish the serial episode first",
                source_type="system",
                agent_id=sarah.id,
            )
            row.created_at = when
            review_id = row.id
        # A hundred newer TEMP_CONTEXT stage reports do not push it out.
        for number in range(100):
            remember(
                session,
                memory_class="TEMP_CONTEXT",
                content=f"Today, stage {number}: done.",
                source_type="system",
                agent_id=sarah.id,
            )
    for task in ("direct_company", "direct_company:final", "choose_topic"):
        identity = identity_of(engine, sarah.id, task)
        assert "NEWEST REVIEW. Priorities: finish the serial episode first" in identity.system
        assert "OLDER REVIEW" not in identity.system, task
        assert identity.context["own_review_id"] == review_id, task
        assert review_id in identity.context["memory_record_ids"], task
        assert "Today, stage" not in identity.system, task
        assert "priorities" in TASK_CONTEXT[task.partition(":")[0]].why, task
    for task in ("director_prompt_audit", "WEEKLY_REVIEW", "director_review"):
        assert "NEWEST REVIEW" not in identity_of(engine, sarah.id, task).system, task


# --------------------------------------------------------------------------- sound plan


def test_the_sound_plan_names_its_film_and_reads_her_earlier_plans_for_it(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    from app.agents import structured
    from app.media import sound_design
    from app.media.music_library import Library

    asked: list[dict] = []

    def capture(*args, **kwargs):
        asked.append(kwargs)
        raise RuntimeError("no model in this test")

    monkeypatch.setattr(structured, "structured_run", capture)
    board = str(uuid4())
    scenes = [
        sound_design.scene_brief(
            {"scene_index": 1, "voiceover_segment": "Words.", "duration_seconds": 4.0}
        )
    ]
    sound_design.sound_plan(
        engine,
        object(),
        film={"title": "A film", "core_message": "One idea."},
        scenes=scenes,
        library=Library(path=Path("music_library.json")),
        correlation_id=str(uuid4()),
        mood_text="calm",
        seed=board,
        storyboard_id=board,
    )
    assert asked and asked[0]["subject"] == {"storyboard_id": board}
    lyra = staffed["agents"]["VoiceArtist"]
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content="Sound plan of this film: the bed rises at the reveal.",
            source_type="system",
            source_id=board,
            agent_id=lyra.id,
        )
    identity = identity_of(engine, lyra.id, "sound_design", {"storyboard_id": board})
    assert "the bed rises at the reveal" in identity.system


# --------------------------------------------------------------------------- the Owner's letter


def test_a_letter_from_the_owner_is_answered_with_what_the_employee_remembers_of_it(
    engine,
    staffed,  # noqa: F811
):
    sarah, marcus = staffed["agents"]["Director"], staffed["agents"]["ScriptWriter"]
    film = str(uuid4())
    with Session(engine) as session, session.begin():
        remember(
            session,
            memory_class="AGENT_OPINION",
            content=f"REMEMBERED: the script of film {film[:8]} cut scene 4 for money.",
            source_type="system",
            source_id=film,
            agent_id=marcus.id,
        )
        remember(
            session,
            memory_class="AGENT_OPINION",
            content="UNRELATED newest note.",
            source_type="system",
            agent_id=marcus.id,
        )
        his = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Why was scene 4 cut?",
            body={"storyboard_id": film},
            body_text="What did you do on that film?",
            from_agent_id=None,
            to_agent_id=marcus.id,
        )
        hers = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Same film, her question",
            body={"storyboard_id": film},
            body_text="Which hook?",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        his_id, hers_id = his.id, hers.id
    registry, model = registry_with(
        staffed, lambda prompt: json.dumps({"reply": "Scene 4 was a paid shot.", "done": True})
    )
    sent = answer_mail(engine, registry, his_id)
    assert "REMEMBERED: the script of film" in model.calls[-1]["system"]
    assert "UNRELATED" not in model.calls[-1]["system"], "only what his letter names"
    with Session(engine) as session:
        context = session.get(AgentRun, sent["run_id"]).context_json
        assert context["owner_letter_memory"] is True and context["memory_tied_ids"]
    answer_mail(engine, registry, hers_id)
    assert "REMEMBERED" not in model.calls[-1]["system"], "a colleague's letter: its thread"


# --------------------------------------------------------------------------- write_episode


def test_the_episode_writer_is_told_the_platform_and_the_money(engine, staffed):  # noqa: F811
    marcus = staffed["agents"]["ScriptWriter"]
    episode = identity_of(engine, marcus.id, "write_episode").system
    assert "a vertical YouTube Short watched on a phone" in episode
    assert "every LIVE scene is a paid shot" in episode
    assert "(write_episode)" in episode


# --------------------------------------------------------------------------- the sweep


def test_an_old_ask_about_a_film_still_in_work_is_kept_and_the_words_are_true(
    engine,
    staffed,  # noqa: F811
    tmp_path,
):
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    live, closed = make_storyboard(engine, tmp_path), make_storyboard(engine, tmp_path)
    ids = {}
    with Session(engine) as session, session.begin():
        session.get(Storyboard, closed).status = "REJECTED"
        log_id = _day_log(session)
        live_episode = _episode(session, log_id, "DRAFT")
        for key, body in (
            ("live film", {"storyboard_id": live}),
            ("live episode", {"episode_id": live_episode}),
            ("closed film", {"storyboard_id": closed}),
            ("nothing", {}),
        ):
            row = post_message(
                session,
                intent="REQUEST_INFO",
                subject=f"Old ask: {key}",
                body=body,
                body_text=f"Answer about {key}.",
                from_agent_id=sarah.id,
                to_agent_id=kael.id,
            )
            row.created_at = ago(days=STALE_ASK_DAYS + 5)
            ids[key] = row.id
    result = expire_stale_asks(engine)
    assert result["by_reason"] == {FILM_CLOSED: 1, EXPIRED: 1}
    with Session(engine) as session:
        for key in ("live film", "live episode"):
            assert session.get(AgentMessage, ids[key]).status == "OPEN", key
        expired = session.get(AgentMessage, ids["nothing"])
        assert expired.status == "ANSWERED"
        assert "fără să țină de un film în lucru" in expired.resolution


def test_nothing_is_swept_while_the_owner_has_stopped_autonomy(engine, staffed):  # noqa: F811
    sarah, kael = staffed["agents"]["Director"], staffed["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        row = post_message(
            session,
            intent="REQUEST_INFO",
            subject="An old ask",
            body={},
            body_text="Old.",
            from_agent_id=sarah.id,
            to_agent_id=kael.id,
        )
        row.created_at = ago(days=30)
        row_id = row.id
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    assert expire_stale_asks(engine) == {"expired": [], "by_reason": {}, "stopped": True}
    # Her review, asked by the Owner while stopped (its route does not check the stop), sweeps
    # nothing either; the mail round stops before it.
    registry, model = registry_with(staffed, lambda prompt: "{}")
    director_review(engine, registry, str(uuid4()))
    assert correspondence_round(engine, registry)["expired"] == []
    assert model.calls == []
    with Session(engine) as session:
        assert session.get(AgentMessage, row_id).status == "OPEN"


def test_a_failed_sweep_never_ends_the_mail_round_or_her_review(engine, staffed, monkeypatch):  # noqa: F811
    sarah, marcus = staffed["agents"]["Director"], staffed["agents"]["ScriptWriter"]
    with Session(engine) as session, session.begin():
        asked = post_message(
            session,
            intent="REQUEST_INFO",
            subject="Which hook?",
            body={},
            body_text="Which hook did you keep?",
            from_agent_id=sarah.id,
            to_agent_id=marcus.id,
        )
        asked_id = asked.id

    def broken(*_args, **_kwargs):
        raise TimeoutError("database is locked")

    # The sweep's own reading fails, wherever it is called from.
    monkeypatch.setattr(inbox_module, "stale_asks", broken)

    def answer(prompt):
        if 'hash="director-inbox"' in prompt:
            return json.dumps({"summary": "Read.", "decisions": [], "priorities": []})
        return json.dumps({"reply": "The mirror hook.", "done": True})

    registry, _model = registry_with(staffed, answer)
    result = correspondence_round(engine, registry, datetime.now(UTC) + timedelta(seconds=1))
    assert [item["message_id"] for item in result["answered"]]
    assert result["expired"] == []
    with Session(engine) as session:
        assert session.get(AgentMessage, asked_id).status != "OPEN"
    review = director_review(engine, registry, str(uuid4()))
    assert "reviewed" in review
