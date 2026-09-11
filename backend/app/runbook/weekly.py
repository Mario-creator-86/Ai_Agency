"""The Director's weekly performance review.

The Owner's standing order: the Director verifies what became of the studio's published
work — what the audience measured, what the final product looked and sounded like — and
answers with written production indications for the sound and the video departments, every
week. This module is that review:

1. `weekly_digest` reads only what is recorded: publications with their measured metrics,
   per-channel totals, the week's production counts, and the strategy recommendations still
   waiting for a decision. Nothing is fetched from the platform here — the numbers come from
   `performance_intake`, which runs daily.
2. `execute_weekly_review` puts the digest in front of the Director through her identity and
   memory (an ordinary run through the policy kernel), then files her answer where it does
   work: a HANDOFF message to the sound department and one to the video department — those
   enter each employee's every run until resolved — and a STATUS report to the Director's
   inbox. A week with nothing published is reported as such and costs no tokens.

The job is scheduled for every seven days at start-up (`WEEKLY_JOB_NAME`); the Owner can
also fire it from the runbook panel. The autonomy stop gates both paths, like every other
scheduled work.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.messages import post_message
from app.agents.models import Agent, AgentRun, Role
from app.analytics.models import AnalyticsSnapshot, DirectorRecommendation
from app.publishing.models import ChannelRecord, PublicationRecord
from app.services import utc_now

WEEKLY_REVIEW_TASK = "WEEKLY_REVIEW"
WEEKLY_JOB_NAME = "weekly_review"
WEEKLY_SECONDS = 7 * 86400
WINDOW_DAYS = 7


class WeeklyReviewError(RuntimeError):
    """The weekly review cannot start; the reason is meant for the Owner."""


def _iso_week_label(now: str) -> str:
    from datetime import datetime

    moment = datetime.fromisoformat(now.replace("Z", "+00:00"))
    year, week, _ = moment.isocalendar()
    return f"{year}-S{week:02d}"


def _week_start(now: str) -> str:
    from datetime import datetime, timedelta

    moment = datetime.fromisoformat(now.replace("Z", "+00:00"))
    start = moment - timedelta(days=moment.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _latest_metrics(session: Session, publication_ids: list[str]) -> dict[str, AnalyticsSnapshot]:
    if not publication_ids:
        return {}
    rows = session.scalars(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.publication_id.in_(publication_ids))
        .order_by(AnalyticsSnapshot.snapshot_at.desc())
    ).all()
    latest: dict[str, AnalyticsSnapshot] = {}
    for row in rows:
        latest.setdefault(row.publication_id, row)
    return latest


def weekly_digest(engine: Engine) -> dict[str, Any]:
    """The week's recorded performance picture, from the studio's own tables."""
    now = utc_now()
    with Session(engine) as session:
        channels = {c.id: c for c in session.scalars(select(ChannelRecord))}
        publications = session.scalars(
            select(PublicationRecord)
            .where(
                PublicationRecord.status == "PUBLISHED",
                PublicationRecord.remote_video_id.is_not(None),
            )
            .order_by(PublicationRecord.created_at.desc())
            .limit(50)
        ).all()
        metrics = _latest_metrics(session, [p.id for p in publications])

        videos: list[dict[str, Any]] = []
        per_channel: dict[str, dict[str, int]] = {}
        for publication in publications:
            metric = metrics.get(publication.id)
            views = metric.views if metric else 0
            channel = channels.get(publication.channel_id or "")
            channel_name = channel.channel_name if channel else "necunoscut"
            likes = metric.likes if metric else 0
            entry = {
                "title": publication.title,
                "channel": channel_name,
                "channel_id": publication.channel_id,
                "published_at": publication.created_at,
                "views": views,
                "likes": likes,
                "comments": metric.comments if metric else 0,
                "average_view_percentage": (
                    round(metric.average_view_percentage, 1) if metric else None
                ),
                "ctr_percentage": round(metric.ctr_percentage, 1) if metric else None,
                "measured_at": metric.snapshot_at if metric else None,
            }
            videos.append(entry)
            bucket = per_channel.setdefault(channel_name, {"videos": 0, "views": 0, "likes": 0})
            bucket["videos"] += 1
            bucket["views"] += int(views)
            bucket["likes"] += int(likes)

        proposals = session.scalars(
            select(DirectorRecommendation)
            .where(DirectorRecommendation.status == "PROPOSED")
            .order_by(DirectorRecommendation.created_at.desc())
            .limit(10)
        ).all()
        recommendations = [
            {
                "type": rec.recommendation_type,
                "target": rec.target_entity,
                "weight_change": rec.suggested_weight_change,
                "evidence": rec.evidence_summary,
            }
            for rec in proposals
        ]

    week_start = _week_start(now)
    return {
        "week": _iso_week_label(now),
        "week_start": week_start,
        "videos": videos,
        "per_channel": per_channel,
        "open_recommendations": recommendations,
        "anything_published": bool(videos),
    }


def _digest_as_text(digest: dict[str, Any]) -> str:
    """The digest in sentences, because a prompt reads text, not JSON trees."""
    lines = [f"Săptămâna {digest['week']} — performanța măsurată:"]
    if not digest["anything_published"]:
        lines.append("Niciun video publicat. Nimic de măsurat.")
        return "\n".join(lines)
    for channel, totals in sorted(digest["per_channel"].items()):
        lines.append(
            f"- {channel}: {totals['videos']} videouri publicate, {totals['views']} vizualizări, "
            f"{totals['likes']} aprecieri (în total, până azi)."
        )
    for video in digest["videos"][:15]:
        average = video["average_view_percentage"]
        retention = f", reținere medie {average}%" if average is not None else ""
        ctr = f", CTR {video['ctr_percentage']}%" if video["ctr_percentage"] is not None else ""
        lines.append(
            f"- „{video['title']}” ({video['channel']}): {video['views']} vizualizări, "
            f"{video['likes']} aprecieri{retention}{ctr}."
        )
    for rec in digest["open_recommendations"]:
        lines.append(f"- Recomandare deschisă: {rec['type']} {rec['target']} — {rec['evidence']}")
    return "\n".join(lines)


_REVIEW_INSTRUCTIONS = (
    "You are doing your weekly performance review, as your contract requires. Below is what "
    "the audience measured for everything the studio has published, plus the strategy "
    "recommendations still waiting.\n"
    "Write, in Romanian, in this order:\n"
    "1. Verdict: what performed and what underperformed, judged from the measured numbers "
    "(views, retention, click-through), never from impressions.\n"
    "2. Production indications for the SOUND department (Lyra): what to keep, what to change "
    "or adjust in voice, pace or settings — only where the channel's production policy allows "
    "the change; say explicitly when something must go through an approved identity change "
    "because the channel or the character is locked.\n"
    "3. Production indications for the VIDEO department (Kael): which direction the video "
    "models and visual choices should take, weighed by quality, recorded cost and what kept "
    "viewers watching — same policy limits.\n"
    "4. What must reach the Owner: budget, personnel, a locked identity change.\n"
    "Base every statement on the numbers below or on what you remember; when the data is too "
    "thin to judge (fewer than three videos of a kind), say so instead of guessing.\n\n"
)

_WEEKLY_PROMPT_VERSION = "weekly-review-v1"


def _agent_for_role(session: Session, role_name: str) -> Agent | None:
    return session.scalar(
        select(Agent)
        .join(Role, Agent.role_id == Role.id)
        .where(Role.name == role_name, Agent.lifecycle.in_(("ACTIVE", "HIRED", "CANDIDATE")))
        .limit(1)
    )


def _already_reviewed_this_week(engine: Engine, week_start: str) -> bool:
    with Session(engine) as session:
        run = session.scalar(
            select(AgentRun)
            .where(
                AgentRun.task_type == WEEKLY_REVIEW_TASK,
                AgentRun.started_at >= week_start,
                AgentRun.status.in_(("SUCCEEDED", "EMPTY_OUTPUT")),
            )
            .limit(1)
        )
        return run is not None


def execute_weekly_review(
    engine: Engine,
    registry: Any,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """One weekly review: digest, the Director's run, her indications filed as messages."""
    correlation_id = correlation_id or str(uuid4())
    digest = weekly_digest(engine)

    if not digest["anything_published"]:
        with Session(engine) as session, session.begin():
            post_message(
                session,
                intent="STATUS",
                subject=f"Revizia săptămânală {digest['week']}: nimic publicat, nimic de măsurat",
                body={"digest": {"anything_published": False}},
                correlation_id=correlation_id,
            )
        return {
            "status": "SKIPPED",
            "reason": "Niciun video publicat de revizuit.",
            "week": digest["week"],
        }

    if _already_reviewed_this_week(engine, digest["week_start"]):
        return {
            "status": "SKIPPED",
            "reason": "Săptămâna a fost deja revizuită.",
            "week": digest["week"],
        }

    with Session(engine) as session:
        director = _agent_for_role(session, "Director")
        if director is None:
            raise WeeklyReviewError("Nu există un Director activ căruia să-i predau revizia.")
        sound = _agent_for_role(session, "VoiceArtist")
        video = _agent_for_role(session, "VideoEditor")
        director_id = director.id
        sound_id = sound.id if sound else None
        video_id = video.id if video else None

    from app.agents.services import run_agent_task

    prompt = _REVIEW_INSTRUCTIONS + _digest_as_text(digest)
    result = run_agent_task(
        engine,
        registry,
        director_id,
        WEEKLY_REVIEW_TASK,
        prompt,
        _WEEKLY_PROMPT_VERSION,
        correlation_id,
        max_tokens=1400,
        temperature=0.3,
        summary=f"Revizia săptămânală a performanței ({digest['week']})",
    )
    if result["status"] != "SUCCEEDED" or not (result.get("output_text") or "").strip():
        return {
            "status": result["status"],
            "reason": (
                "Directorul nu a produs o revizie: "
                f"{result.get('error_detail') or result.get('status')}"
            ),
            "run_id": result["id"],
            "week": digest["week"],
        }
    review_text = result["output_text"].strip()
    week_label = digest["week"]

    with Session(engine) as session, session.begin():
        for role_name, agent_id in (("VoiceArtist", sound_id), ("VideoEditor", video_id)):
            if agent_id is None:
                continue
            department = "sunet" if role_name == "VoiceArtist" else "video"
            post_message(
                session,
                intent="HANDOFF",
                subject=(
                    f"Indicațiile Directorului pentru departamentul de {department} — {week_label}"
                ),
                body={"instructions": review_text, "week": week_label},
                from_agent_id=director_id,
                to_agent_id=agent_id,
                run_id=result["id"],
                correlation_id=correlation_id,
            )
        headline = " ".join(review_text.split())[:140]
        post_message(
            session,
            intent="STATUS",
            subject=f"Revizia săptămânală {week_label}: {headline}",
            body={"review": review_text, "digest": digest["per_channel"]},
            from_agent_id=director_id,
            correlation_id=correlation_id,
        )
    return {
        "status": "COMPLETED",
        "run_id": result["id"],
        "week": week_label,
        "videos_reviewed": len(digest["videos"]),
        "instructions_filed": sum(1 for id_ in (sound_id, video_id) if id_),
    }
