"""The Director's command of the company: what is happening, why, and who acts next.

The studio had a Director who read her inbox, chose the day's topic and watched the finished
film. What it did not have was an executive: nobody asked where the company stood, what was
preventing growth, which department was the bottleneck, whether an agent had been idle for a
week, or whether last month's strategic bet had worked. Every part was measured and no part
was managed.

This is that desk, and it is built on three rules.

**The numbers say what is wrong; the Director decides what to do about it.** The findings here
are computed from stored rows — pipeline counts, idle agents, dead letters, the growth
constraint, anomalies, decisions whose review has come due. A model is then asked to choose
among them and justify the choice; with no model reachable, the computed findings are acted on
directly, in their own order. A studio with no language model still runs.

**An action or nothing.** The loop's output is assignments to real roles with a review
condition, a reprioritised backlog, or an escalation to the Owner. It is not a report. A
matter already decided today is not decided again, and a matter that has failed repeatedly is
escalated rather than retried forever.

**No busywork, and no idle without a reason.** When production work exists, agents do
production. When it is blocked, the blocker is the work. When there is genuinely nothing in
flight, the work is the improvement the evidence points at — topic research, a source check, a
prompt lesson, a benchmark — never activity invented to look busy.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agents.identity import parse_structured
from app.agents.memory import agent_for_role, remember
from app.agents.messages import post_message
from app.agents.models import Agent, Role
from app.analytics.models import DirectorDecision
from app.analytics.performance import (
    anomalies,
    channel_health,
    growth_diagnosis,
)
from app.config import Settings
from app.factual.models import ScriptDraft, TopicIdea
from app.factual.sanitizer import wrap_in_inert_boundary
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.publishing.models import ChannelRecord, PublicationRecord
from app.services import append_event, utc_now
from app.workflows.models import TaskQueueItem

logger = logging.getLogger("studio.command")

DIRECTOR_ROLE = "Director"
TEMPLATE_VERSION = "direction-v1"

#: How much internal evidence the studio has, and therefore how much it should lean on it.
#: With nothing published, strategy rests on editorial judgement and outside signals; that is
#: not an absence of strategy, and it is not licence to invent an audience.
COLD_START_MAX = 0
EARLY_DATA_MAX = 10

#: What each department can actually be given, so an assignment names real work for a real
#: role. Taken from the Owner's own table: the Director coordinates specialists, she does not
#: do their work, and she cannot hand a task to a department that has no way to perform it.
ASSIGNABLE: dict[str, tuple[str, ...]] = {
    "LeadResearcher": (
        "propose stronger topics for a named weakness",
        "find evidence for a topic that has none",
        "research an audience question that keeps coming back",
        "check the authorised sources for a category",
    ),
    "FactChecker": (
        "verify the claims behind a topic waiting for production",
        "re-check a claim a viewer disputed",
    ),
    "ScriptWriter": (
        "rewrite an opening that loses viewers",
        "shorten the setup and move the reveal earlier",
        "strengthen the closing question for subscriber conversion",
        "make the channel's promise explicit in the ending",
    ),
    "VideoEditor": (
        "improve the first frame and the thumbnail moment",
        "review the shot prompts against what the film actually looked like",
        "benchmark a cheaper model against the one in use",
    ),
    "VoiceArtist": ("review narration pacing on a named film",),
    "Publisher": (
        "check the publishing queue and the metadata of what is waiting",
        "report why a publication failed",
    ),
    "Accountant": (
        "report what a film cost against what it returned",
        "report the month's spend against the budget",
    ),
}

#: Work worth doing when nothing is in production — and only when nothing is. Each of these
#: changes something the studio will use; none of them is a report for its own sake.
IMPROVEMENT_WORK: tuple[tuple[str, str, str], ...] = (
    (
        "backlog_thin",
        "LeadResearcher",
        "propose stronger topics for a named weakness",
    ),
    (
        "sources_unchecked",
        "LeadResearcher",
        "check the authorised sources for a category",
    ),
    (
        "prompts_unreviewed",
        "VideoEditor",
        "review the shot prompts against what the film actually looked like",
    ),
    (
        "costs_unread",
        "Accountant",
        "report what a film cost against what it returned",
    ),
)

#: Decisions the Owner takes, not the Director. Stopping a whole category, repositioning a
#: channel or raising a budget are his; the Director states the case and waits.
HIGH_IMPACT = ("STOP", "SCALE")

#: How many assignments one loop may make. An executive who hands out twelve tasks in a
#: morning has not prioritised anything.
MAX_ASSIGNMENTS = 3

#: How many times the same matter may be assigned before it goes to the Owner instead. This
#: is the end of the retry loop the Owner asked for.
MAX_ATTEMPTS_PER_MATTER = 3


class CommandError(ValueError):
    """The loop could not run; nothing was decided and nothing was assigned."""


class Choice(BaseModel):
    """One decision the Director takes, in the shape that makes it reviewable."""

    model_config = ConfigDict(extra="ignore")
    matter_key: str = Field(min_length=1, max_length=120)
    decision: str = Field(
        pattern="^(SCALE|CONTINUE|ITERATE|EXPERIMENT|HOLD|COOLDOWN|REDUCE|STOP|NEEDS_MORE_DATA)$"
    )
    interpretation: str = Field(default="", max_length=1200)
    confidence: str = Field(default="LOW", pattern="^(LOW|MEDIUM|HIGH)$")
    action: str = Field(default="", max_length=1200)
    owner_role: str = Field(default="", max_length=50)
    review_after_videos: int | None = Field(default=None, ge=1, le=100)


class Direction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    choices: list[Choice] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=800)


_INSTRUCTIONS = (
    "You are the Director of this studio, and you are responsible for the whole company's "
    "performance, not for one video. Below is the company's state as data, and the matters "
    "the studio's own measurements have raised, each with its evidence.\n\n"
    "Choose at most {limit} of these matters to act on now — the ones that most limit growth — "
    "and for each one state what you decide and who does it. Do not invent a matter that is "
    "not in the list, do not assign work to a department that cannot do it, and do not ask "
    "for a report that changes nothing. Where the evidence is one film or fewer than three "
    "samples, the honest decision is NEEDS_MORE_DATA: one bad video does not condemn a "
    "category and one good video does not prove a format. Prefer finishing work in flight "
    "over starting new work.\n\n"
    "Decisions: SCALE, CONTINUE, ITERATE, EXPERIMENT, HOLD, COOLDOWN, REDUCE, STOP, "
    "NEEDS_MORE_DATA. Return only JSON: "
    '{{"choices": [{{"matter_key": "...", "decision": "ITERATE", "interpretation": "what '
    'you think is happening and why", "confidence": "LOW|MEDIUM|HIGH", "action": "the '
    'specific thing to do, naming what to change", "owner_role": "RoleName", '
    '"review_after_videos": 5}}], "note": "one line for the Owner"}}.\n'
)


# ----------------------------------------------------------------------------- the state


def data_maturity(measured: int) -> str:
    """How much the studio's own numbers may be leaned on. Not a preference — a fact."""
    if measured <= COLD_START_MAX:
        return "COLD_START"
    if measured < EARLY_DATA_MAX:
        return "EARLY_DATA"
    return "MATURE"


def pipeline(engine: Engine) -> dict[str, Any]:
    """What is in flight at each stage, and where it is stuck.

    The bottleneck is not the stage with the most work; it is the stage that is holding the
    stages after it. Twenty approved ideas with no finished script is a production problem, and
    assigning more research to it is how a studio ends with fifty ideas and nothing published.
    """
    with Session(engine) as session:
        proposed = session.scalar(
            select(func.count()).select_from(TopicIdea).where(TopicIdea.status == "PROPOSED")
        )
        selected = session.scalar(
            select(func.count()).select_from(TopicIdea).where(TopicIdea.status == "SELECTED")
        )
        drafts = {
            status: count
            for status, count in session.execute(
                select(ScriptDraft.status, func.count()).group_by(ScriptDraft.status)
            ).all()
        }
        boards = {
            status: count
            for status, count in session.execute(
                select(Storyboard.status, func.count()).group_by(Storyboard.status)
            ).all()
        }
        rendered = session.scalar(
            select(func.count())
            .select_from(VideoRenderJob)
            .where(VideoRenderJob.status == "COMPLETED")
        )
        failed_renders = session.scalar(
            select(func.count())
            .select_from(VideoRenderJob)
            .where(VideoRenderJob.status == "FAILED")
        )
        assets = session.scalar(
            select(func.count())
            .select_from(MediaAsset)
            .where(MediaAsset.asset_type == "RENDERED_VIDEO")
        )
        passed_qc = session.scalar(
            select(func.count())
            .select_from(QualityControlReport)
            .where(QualityControlReport.status == "PASSED")
        )
        published = session.scalar(
            select(func.count())
            .select_from(PublicationRecord)
            .where(PublicationRecord.status == "PUBLISHED")
        )
        stuck_publications = session.scalar(
            select(func.count())
            .select_from(PublicationRecord)
            .where(PublicationRecord.status.like("FAILED%"))
        )
    stages = {
        "topics_proposed": int(proposed or 0),
        "topics_selected": int(selected or 0),
        "scripts_awaiting_review": int(drafts.get("VERIFIED_PASS", 0)),
        "scripts_approved": int(drafts.get("APPROVED", 0)),
        "scripts_blocked": int(drafts.get("BLOCKED_UNVERIFIED_CLAIMS", 0)),
        "storyboards_approved": int(boards.get("APPROVED", 0)),
        "storyboards_rejected": int(boards.get("REJECTED", 0)),
        "renders_completed": int(rendered or 0),
        "renders_failed": int(failed_renders or 0),
        "films": int(assets or 0),
        "qc_passed": int(passed_qc or 0),
        "published": int(published or 0),
        "publications_failed": int(stuck_publications or 0),
    }
    # Work started and not finished. Starting is not producing: this is the number that says
    # whether the studio is finishing anything.
    in_flight = (
        stages["topics_selected"]
        + stages["scripts_awaiting_review"]
        + stages["scripts_approved"]
        + stages["storyboards_approved"]
    )
    order = (
        ("RESEARCH", stages["topics_proposed"], stages["topics_selected"]),
        ("WRITING", stages["topics_selected"], stages["scripts_awaiting_review"]),
        ("APPROVAL", stages["scripts_awaiting_review"], stages["scripts_approved"]),
        ("PRODUCTION", stages["storyboards_approved"], stages["renders_completed"]),
        ("PUBLISHING", stages["qc_passed"], stages["published"]),
    )
    bottleneck = None
    for name, waiting, passed_on in order:
        if waiting >= 3 and passed_on == 0:
            bottleneck = {"stage": name, "waiting": waiting, "passed_on": passed_on}
            break
    if bottleneck is None:
        worst = max(order, key=lambda row: row[1])
        if worst[1] >= 5 and worst[1] > worst[2] * 3:
            bottleneck = {"stage": worst[0], "waiting": worst[1], "passed_on": worst[2]}
    return {
        "stages": stages,
        "in_flight": in_flight,
        "bottleneck": bottleneck,
        "finished_ratio": (round(stages["published"] / in_flight, 2) if in_flight else None),
    }


def company_state(engine: Engine, settings: Settings) -> dict[str, Any]:
    """Where the company stands right now, in one readable shape.

    Reads only. Everything here comes from a stored row, and anything the studio has not
    measured is reported as unmeasured rather than filled with a zero.
    """
    from app.services import studio_environment  # noqa: PLC0415
    from app.workforce.services import measure_workforce  # noqa: PLC0415

    with Session(engine) as session:
        channel_ids = [row.id for row in session.scalars(select(ChannelRecord))]
        policy_stopped = _autonomy_stopped(session)
        open_decisions = list(
            session.scalars(select(DirectorDecision).where(DirectorDecision.state == "OPEN"))
        )
        dead_letters = int(
            session.scalar(
                select(func.count())
                .select_from(TaskQueueItem)
                .where(TaskQueueItem.status == "DEAD_LETTER")
            )
            or 0
        )
        queued = int(
            session.scalar(
                select(func.count())
                .select_from(TaskQueueItem)
                .where(TaskQueueItem.status.in_(["QUEUED", "RETRYING"]))
            )
            or 0
        )
    channels = [channel_health(engine, channel_id) for channel_id in channel_ids]
    measured = sum(int(c["measured"]) for c in channels)
    workforce = measure_workforce(engine)
    return {
        "at": utc_now(),
        "environment": studio_environment(engine),
        "autonomy_stopped": policy_stopped,
        "maturity": data_maturity(measured),
        "measured_films": measured,
        "channels": channels,
        "pipeline": pipeline(engine),
        "backlog": backlog(engine, limit=8),
        "agents": {
            "active": workforce["active_agents"],
            "idle": workforce["idle_agents"],
            "queue_backlog": queued,
            "dead_letter_tasks": dead_letters,
            "per_agent": [
                {
                    "agent_id": row["agent_id"],
                    "role": row["role_name"],
                    "runs": row["runs"],
                    "failure_rate": row["failure_rate"],
                }
                for row in workforce["agents"]
            ],
        },
        "open_decisions": [
            {
                "matter_key": row.matter_key,
                "decision": row.decision,
                "action": row.action[:200],
                "owner_role": row.owner_role,
                "review_after_videos": row.review_after_videos,
                "created_at": row.created_at,
            }
            for row in open_decisions
        ],
        "anomalies": anomalies(engine),
        "growth": [growth_diagnosis(engine, channel_id) for channel_id in channel_ids],
        "target_video_seconds": settings.target_video_seconds,
    }


def _autonomy_stopped(session: Session) -> bool:
    from app.models import OwnerPolicy  # noqa: PLC0415

    policy = session.get(OwnerPolicy, 1)
    return bool(policy.autonomy_stopped) if policy else True


# ----------------------------------------------------------------------------- the backlog


def backlog(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    """The company's candidate queue, in the order the Director put it, with the reason."""
    with Session(engine) as session:
        rows = session.scalars(
            select(TopicIdea)
            .where(TopicIdea.status.in_(["PROPOSED", "SELECTED"]))
            .order_by(TopicIdea.priority.desc(), TopicIdea.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "topic_id": row.id,
                "title": row.title,
                "status": row.status,
                "priority": round(float(row.priority or 0), 4),
                "priority_reason": row.priority_reason,
                "composite": (row.scores_json or {}).get("composite"),
                "payoff": (row.thesis_json or {}).get("payoff"),
                "claims": len(row.claims),
            }
            for row in rows
        ]


def prioritise_backlog(engine: Engine) -> list[dict[str, Any]]:
    """Order the backlog by what it is worth doing next, and write down why.

    Not first-in-first-out: a candidate with verified evidence and a strong payoff outranks an
    older one nobody has sourced, and a category the last films exhausted is pushed down so the
    channel does not publish the same thing four times. Every place in the queue carries the
    sentence that put it there.
    """
    from app.factual.editorial import composite  # noqa: PLC0415

    changed: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        candidates = list(
            session.scalars(select(TopicIdea).where(TopicIdea.status.in_(["PROPOSED", "SELECTED"])))
        )
        # What the channel has just published, so the queue does not repeat it.
        recent_topics = [
            (row.topic or "").lower()
            for row in session.scalars(
                select(TopicIdea)
                .where(TopicIdea.status == "PRODUCED")
                .order_by(TopicIdea.selected_at.desc())
                .limit(5)
            )
        ]
        for topic in candidates:
            scores = topic.scores_json if isinstance(topic.scores_json, dict) else {}
            editorial = scores.get("composite")
            if not isinstance(editorial, int | float):
                editorial = composite(scores)
            verified = sum(1 for claim in topic.claims if claim.status == "SUPPORTED")
            reasons: list[str] = [f"scor editorial {float(editorial):.2f}"]
            score = float(editorial)
            # Evidence already in hand is the difference between a film this week and a topic
            # that dies at verification.
            if verified:
                score += min(0.2, verified * 0.05)
                reasons.append(f"{verified} afirmații verificate")
            else:
                reasons.append("fără dovezi încă")
            if topic.status == "SELECTED":
                score += 0.15
                reasons.append("deja selectat, de terminat înainte să începem altul")
            repeat = (topic.topic or "").lower()
            if repeat and repeat in recent_topics:
                score -= 0.2
                reasons.append("categoria a fost publicată recent; pauză strategică")
            feasibility = scores.get("production_feasibility")
            if isinstance(feasibility, int | float) and float(feasibility) < 0.4:
                score -= 0.1
                reasons.append("greu de produs")
            topic.priority = round(score, 4)
            topic.priority_reason = "; ".join(reasons)[:2000]
            changed.append(
                {"topic_id": topic.id, "priority": topic.priority, "reason": topic.priority_reason}
            )
    changed.sort(key=lambda row: row["priority"], reverse=True)
    return changed


# ----------------------------------------------------------------------------- the findings


def findings(engine: Engine, settings: Settings, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Every matter the studio's own measurements raise, with its evidence and a suggestion.

    These are computed, not judged: a finding is a fact plus the department that could act on
    it. What to do about it is the Director's, and with no model reachable the suggestion
    stands as the decision — which is how a studio with no language model still acts.
    """
    matters: list[dict[str, Any]] = []

    def add(
        key: str,
        scope: str,
        observation: str,
        evidence: dict[str, Any],
        suggestion: str,
        action: str,
        role: str | None,
        confidence: str = "MEDIUM",
        channel_id: str | None = None,
        review_after_videos: int | None = 3,
    ) -> None:
        matters.append(
            {
                "matter_key": key,
                "scope": scope,
                "observation": observation,
                "evidence": evidence,
                "suggested_decision": suggestion,
                "action": action,
                "owner_role": role,
                "confidence": confidence,
                "channel_id": channel_id,
                "review_after_videos": review_after_videos,
            }
        )

    # 1. Blockers first: a studio that cannot finish what it started has no use for new work.
    pipe = state["pipeline"]
    if pipe["stages"]["publications_failed"]:
        add(
            "publications_failed",
            "PRODUCTION",
            f"{pipe['stages']['publications_failed']} publicări au eșuat și stau neterminate.",
            {"failed": pipe["stages"]["publications_failed"]},
            "ITERATE",
            "check the publishing queue and the metadata of what is waiting",
            "Publisher",
            confidence="HIGH",
        )
    if pipe["stages"]["renders_failed"]:
        add(
            "renders_failed",
            "PRODUCTION",
            f"{pipe['stages']['renders_failed']} randări au eșuat.",
            {"failed": pipe["stages"]["renders_failed"]},
            "ITERATE",
            "review the shot prompts against what the film actually looked like",
            "VideoEditor",
            confidence="HIGH",
        )
    if state["agents"]["dead_letter_tasks"]:
        add(
            "dead_letters",
            "AGENT",
            f"{state['agents']['dead_letter_tasks']} sarcini au murit în coadă.",
            {"dead_letters": state["agents"]["dead_letter_tasks"]},
            "HOLD",
            "report why a publication failed",
            "Publisher",
            confidence="HIGH",
            review_after_videos=None,
        )
    if pipe["stages"]["scripts_blocked"]:
        add(
            "scripts_blocked",
            "CONTENT",
            f"{pipe['stages']['scripts_blocked']} scenarii sunt blocate de afirmații neverificate.",
            {"blocked": pipe["stages"]["scripts_blocked"]},
            "ITERATE",
            "verify the claims behind a topic waiting for production",
            "FactChecker",
            confidence="HIGH",
        )

    # 2. The bottleneck: where work is piling up in front of an empty stage.
    if pipe["bottleneck"]:
        stage = pipe["bottleneck"]["stage"]
        role = {
            "RESEARCH": "FactChecker",
            "WRITING": "ScriptWriter",
            "APPROVAL": None,
            "PRODUCTION": "VideoEditor",
            "PUBLISHING": "Publisher",
        }.get(stage)
        action = {
            "RESEARCH": "verify the claims behind a topic waiting for production",
            "WRITING": "rewrite an opening that loses viewers",
            "APPROVAL": "",
            "PRODUCTION": "review the shot prompts against what the film actually looked like",
            "PUBLISHING": "check the publishing queue and the metadata of what is waiting",
        }.get(stage, "")
        add(
            f"bottleneck_{stage.lower()}",
            "PRODUCTION",
            f"Gâtuire la {stage}: {pipe['bottleneck']['waiting']} în așteptare, "
            f"{pipe['bottleneck']['passed_on']} trecute mai departe.",
            dict(pipe["bottleneck"]),
            "ITERATE" if role else "HOLD",
            action,
            role,
            confidence="HIGH",
        )

    # 3. Growth: what limits each channel, from its own measured films.
    for growth in state["growth"]:
        if growth["constraint"] in ("NONE_VISIBLE",):
            continue
        if growth["constraint"] == "NO_DATA":
            add(
                f"cold_start_{growth['channel_id'][:8]}",
                "CHANNEL",
                growth["reason"],
                growth["evidence"],
                "EXPERIMENT",
                "propose stronger topics for a named weakness",
                "LeadResearcher",
                confidence="LOW",
                channel_id=growth["channel_id"],
                review_after_videos=3,
            )
            continue
        add(
            f"growth_{growth['constraint'].lower()}_{growth['channel_id'][:8]}",
            "CHANNEL",
            growth["reason"],
            growth["evidence"],
            "ITERATE",
            {
                "REACH": "improve the first frame and the thumbnail moment",
                "RETENTION": "shorten the setup and move the reveal earlier",
                "CONVERSION": "strengthen the closing question for subscriber conversion",
                "TOPIC_SELECTION": "propose stronger topics for a named weakness",
            }.get(growth["constraint"], ""),
            growth["assign_to"],
            confidence=growth["confidence"],
            channel_id=growth["channel_id"],
            review_after_videos=5,
        )

    # 4. Anomalies: a reason to look, never a verdict on their own.
    for item in state["anomalies"]:
        add(
            f"anomaly_{item['kind'].lower()}_{item['channel_id'][:8]}",
            "CHANNEL",
            f"{item['kind'].replace('_', ' ').title()}: {item['detail']}.",
            dict(item),
            "NEEDS_MORE_DATA" if item["kind"] == "VIEW_SPIKE" else "ITERATE",
            {
                "VIEW_SPIKE": "research an audience question that keeps coming back",
                "RETENTION_DROP": "shorten the setup and move the reveal earlier",
                "COST_SPIKE": "benchmark a cheaper model against the one in use",
            }.get(item["kind"], ""),
            item["assign_to"],
            confidence="MEDIUM",
            channel_id=item["channel_id"],
            review_after_videos=3,
        )

    # 5. Idle agents — but only when there is genuinely nothing in flight. An agent is not
    # given invented work while the studio has films waiting to be finished.
    if state["agents"]["idle"] and pipe["in_flight"] == 0:
        with Session(engine) as session:
            idle_roles = _roles_of(session, state["agents"]["idle"])
        for key, role, work in IMPROVEMENT_WORK:
            if role in idle_roles:
                add(
                    f"idle_{key}",
                    "AGENT",
                    f"{role} nu a rulat nimic în perioada măsurată și nu există lucru în "
                    "producție.",
                    {"idle_roles": sorted(idle_roles), "in_flight": 0},
                    "ITERATE",
                    work,
                    role,
                    confidence="MEDIUM",
                    review_after_videos=None,
                )
                break

    # 6. Decisions whose review has come due.
    for due in due_reviews(engine):
        add(
            f"review_{due['matter_key']}",
            "COMPANY",
            f"Decizia «{due['matter_key']}» trebuia revăzută: "
            f"{due['published_since']} filme publicate de atunci.",
            due,
            "NEEDS_MORE_DATA" if due["published_since"] == 0 else "CONTINUE",
            "report what a film cost against what it returned",
            "Accountant",
            confidence="MEDIUM",
            review_after_videos=None,
        )
    return matters


def _roles_of(session: Session, agent_ids: list[str]) -> set[str]:
    rows = session.execute(
        select(Role.name).join(Agent, Agent.role_id == Role.id).where(Agent.id.in_(agent_ids))
    ).all()
    return {name for (name,) in rows}


def due_reviews(engine: Engine) -> list[dict[str, Any]]:
    """Open decisions whose review condition has been met."""
    out: list[dict[str, Any]] = []
    now = utc_now()
    with Session(engine) as session:
        published = int(
            session.scalar(
                select(func.count())
                .select_from(PublicationRecord)
                .where(PublicationRecord.status == "PUBLISHED")
            )
            or 0
        )
        for row in session.scalars(
            select(DirectorDecision).where(DirectorDecision.state == "OPEN")
        ):
            since = published - int(row.published_at_decision or 0)
            by_videos = row.review_after_videos is not None and since >= int(
                row.review_after_videos
            )
            by_date = row.review_after_at is not None and str(row.review_after_at) <= now
            if by_videos or by_date:
                out.append(
                    {
                        "decision_id": row.id,
                        "matter_key": row.matter_key,
                        "decision": row.decision,
                        "action": row.action[:200],
                        "published_since": since,
                        "review_after_videos": row.review_after_videos,
                    }
                )
    return out


# ----------------------------------------------------------------------------- the loop


def direct_company(
    engine: Engine,
    registry: Any,
    settings: Settings,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """One pass of the Director's management of the company. Its output is action.

    State, then the matters the measurements raise, then the Director's choice among them,
    then the work: a letter to the department that must act, with what to change and when it
    will be looked at again. A matter already open is not opened twice; a matter that has been
    assigned three times goes to the Owner instead of round again.
    """
    correlation = correlation_id or str(uuid4())
    state = company_state(engine, settings)
    if state["autonomy_stopped"]:
        return {
            "status": "SKIPPED",
            "reason": "Autonomia este oprită de Owner; Directoarea nu repartizează nimic.",
            "state": state,
        }
    prioritise_backlog(engine)
    state["backlog"] = backlog(engine, limit=8)
    matters = findings(engine, settings, state)
    if not matters:
        return {
            "status": "COMPLETED",
            "reason": "Nimic nu cere o decizie: producția merge, nu sunt blocaje, nimic anormal.",
            "assignments": [],
            "state": state,
        }

    with Session(engine) as session:
        director = agent_for_role(session, DIRECTOR_ROLE)
        director_id = director.id if director else None
        open_keys = {
            row.matter_key
            for row in session.scalars(
                select(DirectorDecision).where(DirectorDecision.state == "OPEN")
            )
        }
        attempts = {
            key: count
            for key, count in session.execute(
                select(DirectorDecision.matter_key, func.count()).group_by(
                    DirectorDecision.matter_key
                )
            ).all()
        }
    # A matter under an open decision is being worked on; raising it again is the endless
    # conversation the Owner asked to be prevented.
    fresh = [m for m in matters if m["matter_key"] not in open_keys]
    if not fresh:
        return {
            "status": "COMPLETED",
            "reason": f"{len(matters)} chestiuni, toate deja în lucru cu o decizie deschisă.",
            "assignments": [],
            "state": state,
        }

    chosen, run_id, note = _choose(engine, registry, director_id, state, fresh, correlation)
    assignments: list[dict[str, Any]] = []
    escalated: list[str] = []
    for choice in chosen[:MAX_ASSIGNMENTS]:
        matter = next((m for m in fresh if m["matter_key"] == choice.matter_key), None)
        if matter is None:
            continue
        role = choice.owner_role or matter["owner_role"] or ""
        action = (choice.action or matter["action"] or "").strip()
        # Three refusals to a matter is not a fourth attempt; it is the Owner's decision.
        too_many = int(attempts.get(matter["matter_key"], 0)) >= MAX_ATTEMPTS_PER_MATTER
        if choice.decision in HIGH_IMPACT or too_many or role not in ASSIGNABLE:
            escalated.append(matter["matter_key"])
            _escalate(engine, director_id, matter, choice, correlation, run_id, too_many)
            continue
        if not action:
            continue
        record = _assign(
            engine,
            director_id,
            matter,
            choice,
            action,
            role,
            correlation,
            run_id,
            state,
        )
        assignments.append(record)
    return {
        "status": "COMPLETED",
        "reason": (
            f"{len(assignments)} repartizări, {len(escalated)} escaladate la Owner, "
            f"din {len(fresh)} chestiuni."
        ),
        "assignments": assignments,
        "escalated": escalated,
        "note": note,
        "maturity": state["maturity"],
        "state": state,
    }


def _choose(
    engine: Engine,
    registry: Any,
    director_id: str | None,
    state: dict[str, Any],
    matters: list[dict[str, Any]],
    correlation: str,
) -> tuple[list[Choice], str | None, str]:
    """The Director's choice among the matters, or the measurements' own order.

    With no Director or no model, the computed suggestions are taken in the order the findings
    produced them — blockers, then the bottleneck, then growth. That is a worse executive than
    a model and a far better one than nothing.
    """
    fallback = [
        Choice(
            matter_key=m["matter_key"],
            decision=m["suggested_decision"],
            interpretation=m["observation"],
            confidence=m["confidence"],
            action=m["action"] or "",
            owner_role=m["owner_role"] or "",
            review_after_videos=m["review_after_videos"],
        )
        for m in matters
        if m["action"] and m["owner_role"]
    ]
    if director_id is None or registry is None:
        return fallback, None, "fără model: am urmat ordinea măsurătorilor"

    from app.agents.ensemble import run_with_strategy  # noqa: PLC0415

    payload = json.dumps(
        {
            "company": {
                "maturity": state["maturity"],
                "measured_films": state["measured_films"],
                "environment": state["environment"],
                "channels": [
                    {
                        "name": c["channel_name"],
                        "published": c["published"],
                        "measured": c["measured"],
                        "views_last_7_days": c["views_last_7_days"],
                        "views_change_percentage": c["views_change_percentage"],
                        "subscribers_last_7_days": c["subscribers_last_7_days"],
                        "baseline": c["baseline"]["note"],
                    }
                    for c in state["channels"]
                ],
                "pipeline": state["pipeline"],
                "agents": {
                    "idle": len(state["agents"]["idle"]),
                    "queue_backlog": state["agents"]["queue_backlog"],
                    "dead_letter_tasks": state["agents"]["dead_letter_tasks"],
                },
                "backlog": state["backlog"][:5],
                "open_decisions": state["open_decisions"],
            },
            "matters": [
                {
                    "matter_key": m["matter_key"],
                    "observation": m["observation"],
                    "evidence": m["evidence"],
                    "can_be_done_by": m["owner_role"],
                    "suggested_action": m["action"],
                    "suggested_decision": m["suggested_decision"],
                }
                for m in matters
            ],
            "departments": {role: list(work) for role, work in ASSIGNABLE.items()},
        },
        ensure_ascii=False,
        default=str,
    )[:14000]
    prompt = _INSTRUCTIONS.format(limit=MAX_ASSIGNMENTS) + wrap_in_inert_boundary(
        payload, "company-state"
    )
    try:
        # This is a strategic decision, and it is declared as one. What happens next is the
        # Director's own configuration: with a second model in her slot and a REVIEW strategy,
        # her proposal is challenged before she commits; with SINGLE, this is one call, exactly
        # as it was. Nothing here knows which model either of those is.
        result = run_with_strategy(
            engine,
            registry,
            director_id,
            "direct_company",
            prompt,
            TEMPLATE_VERSION,
            correlation,
            importance="STRATEGIC",
            review_objective=(
                "Challenge this plan before the company acts on it. Is there enough data for "
                "each conclusion, or is the sample too small? Could the change be noise? Does "
                "reach, retention or subscriber conversion actually point where the decision "
                "assumes? Is correlation being read as cause? Is there a cheaper experiment "
                "first, and what is the cost if the decision is wrong?"
            ),
            evidence=payload[:8000],
            summary=f"Conduc compania: {len(matters)} chestiuni pe masă.",
            max_tokens=3000,
            temperature=0.2,
            emit_message=False,
        )
    except (ValueError, RuntimeError) as exc:
        logger.info("direction_without_model", extra={"reason": str(exc)[:160]})
        return fallback, None, "modelul nu a răspuns: am urmat ordinea măsurătorilor"
    text = result.get("output_text") or ""
    if result["status"] != "SUCCEEDED" or not text.strip():
        return fallback, result["id"], "modelul nu a răspuns: am urmat ordinea măsurătorilor"
    direction = parse_structured(text, Direction)
    if not isinstance(direction, Direction) or not direction.choices:
        return fallback, result["id"], "răspunsul nu respecta schema: am urmat măsurătorile"
    allowed = {m["matter_key"] for m in matters}
    kept = [c for c in direction.choices if c.matter_key in allowed]
    note = direction.note
    collaboration = result.get("collaboration") or {}
    if collaboration.get("strategy") != "SINGLE":
        note = (
            f"{note} [{collaboration.get('strategy')}: "
            f"{collaboration.get('reason')}; {collaboration.get('outcome')}]"
        ).strip()
    if collaboration.get("review_incomplete"):
        # A decision nobody managed to challenge is not a challenged decision. It still
        # stands — the Director is the authority — but it is recorded at low confidence and
        # the Owner reads why.
        kept = [c.model_copy(update={"confidence": "LOW"}) for c in kept]
        note = (note + " Verificarea strategică nu s-a putut face; încredere redusă.").strip()
    return (kept or fallback), result["id"], note


def _assign(
    engine: Engine,
    director_id: str | None,
    matter: dict[str, Any],
    choice: Choice,
    action: str,
    role: str,
    correlation: str,
    run_id: str | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Hand one matter to the department that can act on it, and record the decision."""
    review_videos = choice.review_after_videos or matter["review_after_videos"]
    if choice.decision != "NEEDS_MORE_DATA" and not review_videos:
        review_videos = 3
    published = state["pipeline"]["stages"]["published"]
    decision_id = str(uuid4())
    with Session(engine) as session, session.begin():
        target = agent_for_role(session, role)
        letter = post_message(
            session,
            intent="HANDOFF",
            subject=f"{choice.decision}: {matter['observation'][:120]}",
            body={
                "kind": "direction",
                "matter_key": matter["matter_key"],
                "decision": choice.decision,
                "evidence": matter["evidence"],
            },
            body_text=(
                f"OBSERVAȚIE: {matter['observation']}\n"
                f"INTERPRETARE: {choice.interpretation or matter['observation']}\n"
                f"ÎNCREDERE: {choice.confidence}\n"
                f"DECIZIE: {choice.decision}\n"
                f"DE FĂCUT: {action}\n"
                + (
                    f"REVIZUIRE: după {review_videos} filme publicate."
                    if review_videos
                    else "REVIZUIRE: la următoarea trecere."
                )
            ),
            from_agent_id=director_id,
            to_agent_id=target.id if target else None,
            run_id=run_id,
            correlation_id=correlation,
        )
        session.flush()
        event = append_event(
            session,
            "director.decision_recorded",
            "director_decision",
            decision_id,
            1,
            {
                "matter_key": matter["matter_key"],
                "decision": choice.decision,
                "owner_role": role,
            },
            correlation,
        )
        session.add(
            DirectorDecision(
                id=decision_id,
                scope=matter["scope"],
                channel_id=matter.get("channel_id"),
                observation=matter["observation"],
                evidence_json=matter["evidence"],
                interpretation=choice.interpretation or matter["observation"],
                confidence=choice.confidence,
                decision=choice.decision,
                action=action,
                owner_role=role,
                review_after_videos=review_videos,
                review_after_at=None,
                state="OPEN",
                published_at_decision=published,
                matter_key=matter["matter_key"],
                message_id=letter.id,
                agent_id=director_id,
                run_id=run_id,
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        remember(
            session,
            memory_class="STRATEGY",
            content=(
                f"decision {choice.decision} on {matter['matter_key']}: {action[:200]} "
                f"(confidence {choice.confidence})"
            ),
            source_type="run" if run_id else "system",
            source_id=run_id,
            agent_id=None,
        )
    logger.info(
        "director_assigned",
        extra={"matter": matter["matter_key"], "role": role, "decision": choice.decision},
    )
    return {
        "decision_id": decision_id,
        "matter_key": matter["matter_key"],
        "decision": choice.decision,
        "owner_role": role,
        "action": action,
        "review_after_videos": review_videos,
    }


def _escalate(
    engine: Engine,
    director_id: str | None,
    matter: dict[str, Any],
    choice: Choice,
    correlation: str,
    run_id: str | None,
    too_many: bool,
) -> None:
    """State the case and wait: this one is the Owner's to decide."""
    with Session(engine) as session, session.begin():
        post_message(
            session,
            intent="ESCALATE",
            subject=f"Decizia ta: {matter['observation'][:120]}",
            body={
                "kind": "direction_escalation",
                "matter_key": matter["matter_key"],
                "decision": choice.decision,
                "evidence": matter["evidence"],
            },
            body_text=(
                f"OBSERVAȚIE: {matter['observation']}\n"
                f"INTERPRETARE: {choice.interpretation or matter['observation']}\n"
                f"ÎNCREDERE: {choice.confidence}\n"
                f"PROPUNERE: {choice.decision} — {choice.action or matter['action']}\n"
                + (
                    "Chestiunea a fost repartizată de trei ori fără rezultat, deci nu o mai "
                    "trimit a patra oară."
                    if too_many
                    else "Decizia asta schimbă direcția companiei, deci este a ta."
                )
            ),
            from_agent_id=director_id,
            to_agent_id=None,
            to_owner=True,
            run_id=run_id,
            correlation_id=correlation,
        )


def review_decision(engine: Engine, decision_id: str, outcome: str) -> dict[str, Any]:
    """Close an open decision with what actually happened."""
    with Session(engine) as session, session.begin():
        row = session.get(DirectorDecision, decision_id)
        if row is None:
            raise CommandError(f"Decision {decision_id} not found")
        row.state = "REVIEWED"
        row.outcome = outcome[:4000]
        row.reviewed_at = utc_now()
        return {"decision_id": decision_id, "state": row.state, "outcome": row.outcome}
