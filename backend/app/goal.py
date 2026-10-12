"""The day's goal, counted from the record: per channel, what was published today, what is
in work and where, what is blocked and whose it is (2026-10-12).

The Owner, 14:00: «Putem urmări goal-ul de generare câte 2 pe fiecare canal, totul autonom?».
Until now the answer lived in the developer's peeks of a database copy. This module reads the
same record the page reads — the publications, the films' newest walk (`runbook.film_state`),
their newest quality control report, his open cards and questions about them, the serial's
episodes — and says, per channel: ``published`` today, ``in_work`` (with where the film
stands, in the film's own words), ``blocked`` (why, and whose the wait is: the Owner's for
money and his accounts, the Director's for quality), and one Romanian line for the register
(``words_ro``). `services.snapshot` carries it to the page as ``goal``. Reads only; never
raises into the snapshot (an unreadable goal is ``{}`` with a logged warning).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("studio.goal")

#: The Owner's goal of 2026-10-12: two films a day on each channel, published by the studio.
TARGET_PER_CHANNEL = 2
#: How far back a film counts as in work.
LOOKBACK_DAYS = 7
#: The channel types in the order the register shows them.
CHANNEL_ORDER = ("MAIN_FACTUAL", "OFFICE_SERIAL")
CHANNEL_WORDS = {"MAIN_FACTUAL": "shorturi", "OFFICE_SERIAL": "episoade"}
#: A film's newest walk, as `runbook.stages` records it.
FILM_STATE_EVENT = "runbook.film_state"
OWNER, DIRECTOR, STUDIO = "owner", "director", "studio"


def _day(session: Session) -> str:
    from app.runbook.models import DailyRun  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415

    newest = session.scalar(
        select(DailyRun.business_date).order_by(DailyRun.started_at.desc()).limit(1)
    )
    return str(newest or utc_now()[:10])


def _since(day: str) -> str:
    from datetime import date, timedelta  # noqa: PLC0415

    try:
        start = date.fromisoformat(day) - timedelta(days=LOOKBACK_DAYS)
    except ValueError:
        return ""
    return start.isoformat()


def _title(board: Any) -> str:
    title = str(getattr(board, "title", "") or "").strip()
    if title.lower().startswith("storyboard:"):
        title = title.split(":", 1)[1].strip()
    return title[:120] or str(getattr(board, "id", ""))[:8]


def _film_states(session: Session, since: str) -> dict[str, dict[str, Any]]:
    from app.models import DomainEvent  # noqa: PLC0415

    states: dict[str, dict[str, Any]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == FILM_STATE_EVENT, DomainEvent.timestamp >= since)
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        states[str(event.aggregate_id)] = {**payload, "at": str(event.timestamp)}
    return states


def _open_cards(session: Session) -> dict[str, str]:
    """His open cards by the film they are about: the card's title."""
    from app.decisions.models import OwnerDecision  # noqa: PLC0415

    cards: dict[str, str] = {}
    for row in session.scalars(
        select(OwnerDecision).where(
            OwnerDecision.subject_type == "storyboard",
            OwnerDecision.status.in_(("PENDING", "WAITING_FOR_OWNER_ACTION")),
        )
    ):
        cards.setdefault(str(row.subject_id), str(row.title_ro or "")[:160])
    return cards


def _published(session: Session, day: str) -> dict[str, list[dict[str, Any]]]:
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    out: dict[str, list[dict[str, Any]]] = {}
    for row in session.scalars(
        select(PublicationRecord)
        .where(PublicationRecord.status == "PUBLISHED")
        .order_by(PublicationRecord.published_at)
    ):
        at = str(row.published_at or row.created_at or "")
        if not at.startswith(day):
            continue
        out.setdefault(str(row.channel_id), []).append(
            {"title": str(row.title or "")[:120], "at": at, "url": row.remote_url}
        )
    return out


def _published_assets(session: Session) -> set[str]:
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    return {
        str(asset_id)
        for asset_id in session.scalars(
            select(PublicationRecord.media_asset_id).where(PublicationRecord.status == "PUBLISHED")
        )
    }


def _film_assets(session: Session, storyboard_id: str) -> list[str]:
    from app.media.models import VideoRenderJob  # noqa: PLC0415

    return [
        str(asset_id)
        for asset_id in session.scalars(
            select(VideoRenderJob.output_asset_id)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.output_asset_id.is_not(None),
            )
            .order_by(VideoRenderJob.finished_at)
        )
    ]


def _newest_report(session: Session, assets: list[str]) -> str | None:
    from app.media.models import QualityControlReport  # noqa: PLC0415

    if not assets:
        return None
    report = session.scalar(
        select(QualityControlReport)
        .where(
            QualityControlReport.media_asset_id.in_(assets),
            QualityControlReport.status != "INVALIDATED",
        )
        .order_by(QualityControlReport.verified_at.desc())
        .limit(1)
    )
    return str(report.status) if report is not None else None


def _where(
    board: Any, state: dict[str, Any], card: str | None, report: str | None
) -> tuple[str, str, str]:
    """(bucket, whose, words): ``blocked`` with whose wait it is, or ``in_work`` with where."""
    from app.runbook.stages import LADDER_REFUSALS, OWNER_DECIDES  # noqa: PLC0415

    reason = " ".join(str(state.get("reason") or "").split())[:220]
    refusal = str(state.get("refusal") or "")
    status = str(state.get("status") or "")
    if card:
        return "blocked", OWNER, f"cardul tău: {card}"
    if refusal in OWNER_DECIDES or refusal in ("NEEDS_REFERENCE",):
        return "blocked", OWNER, reason or f"așteaptă decizia ta ({refusal})"
    if status == "WAITING" and refusal in LADDER_REFUSALS:
        return "in_work", DIRECTOR, reason or "scara Directoarei: o scenă refuzată se rescrie"
    if status == "HELD":
        return "blocked", STUDIO, reason or "ținut de studio"
    if str(getattr(board, "status", "")) == "RENDERED" or report is not None:
        if report == "FAILED":
            return "in_work", DIRECTOR, reason or "controlul calității a picat; Directoarea decide"
        if report == "PASSED":
            return "in_work", STUDIO, reason or "a trecut controlul; merge la publicare"
    if status == "READY":
        return "in_work", STUDIO, reason or "gata de asamblare"
    if reason:
        return "in_work", DIRECTOR if "Directoar" in reason else STUDIO, reason
    return "in_work", STUDIO, "în lucru"


def _next_episode(session: Session) -> dict[str, Any] | None:
    """The serial's newest episode with no storyboard: approved and waiting to be readied,
    or refused and waiting for its rewrite."""
    from app.story.models import StoryEpisode  # noqa: PLC0415

    episode = session.scalar(
        select(StoryEpisode)
        .where(StoryEpisode.storyboard_id.is_(None))
        .order_by(StoryEpisode.created_at.desc())
        .limit(1)
    )
    if episode is None:
        return None
    status = str(episode.status or "")
    words = {
        "APPROVED": "aprobat, se pregătește de filmare",
        "REJECTED": "respins de Directoare; se rescrie la rularea următoare",
        "DRAFT": "în scriere",
    }.get(status, status.lower())
    return {"title": str(episode.title or "")[:120], "status": status, "words_ro": words}


def goal_snapshot(session: Session, *, day: str | None = None) -> dict[str, Any]:
    """The day's goal as the record reads it now; see the module's text."""
    try:
        return _goal(session, day or _day(session))
    except Exception as exc:  # noqa: BLE001 - the snapshot never fails on the goal
        logger.warning("goal_unreadable", extra={"error": type(exc).__name__})
        return {}


def _goal(session: Session, day: str) -> dict[str, Any]:
    from app.media.models import Storyboard  # noqa: PLC0415
    from app.publishing.models import ChannelRecord  # noqa: PLC0415
    from app.publishing.services import channel_type_for_storyboard  # noqa: PLC0415

    channels = {
        str(row.channel_type): row
        for row in session.scalars(select(ChannelRecord).order_by(ChannelRecord.created_at))
    }
    published = _published(session, day)
    published_assets = _published_assets(session)
    states = _film_states(session, _since(day))
    cards = _open_cards(session)
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {
        kind: {"in_work": [], "blocked": []} for kind in CHANNEL_ORDER
    }
    for board in session.scalars(
        select(Storyboard)
        .where(
            Storyboard.status.in_(("APPROVED", "RENDERED")), Storyboard.created_at >= _since(day)
        )
        .order_by(Storyboard.created_at)
    ):
        assets = _film_assets(session, str(board.id))
        if any(asset in published_assets for asset in assets):
            continue
        kind = channel_type_for_storyboard(board)
        bucket, whose, words = _where(
            board,
            states.get(str(board.id), {}),
            cards.get(str(board.id)),
            _newest_report(session, assets),
        )
        buckets.setdefault(kind, {"in_work": [], "blocked": []})[bucket].append(
            {
                "storyboard_id": str(board.id),
                "title": _title(board),
                "whose": whose,
                "words_ro": words,
                "since": str(board.created_at or "")[:16],
            }
        )
    out_channels: list[dict[str, Any]] = []
    parts: list[str] = []
    for kind in CHANNEL_ORDER:
        channel = channels.get(kind)
        done = published.get(str(channel.id), []) if channel is not None else []
        entry = {
            "channel_type": kind,
            "channel_id": channel.id if channel is not None else None,
            "channel_name": channel.channel_name if channel is not None else None,
            "target": TARGET_PER_CHANNEL,
            "published": done,
            "in_work": buckets.get(kind, {}).get("in_work", []),
            "blocked": buckets.get(kind, {}).get("blocked", []),
        }
        if kind == "OFFICE_SERIAL":
            entry["next_episode"] = _next_episode(session)
        out_channels.append(entry)
        parts.append(f"{CHANNEL_WORDS[kind]} {len(done)}/{TARGET_PER_CHANNEL}")
    blocked_his = sum(
        1 for channel in out_channels for item in channel["blocked"] if item["whose"] == OWNER
    )
    words = f"Azi ({day}): " + ", ".join(parts) + " publicate"
    in_work = sum(len(channel["in_work"]) for channel in out_channels)
    if in_work:
        words += f"; {in_work} în lucru"
    if blocked_his:
        words += f"; {blocked_his} așteaptă decizia ta"
    return {
        "day": day,
        "target_per_channel": TARGET_PER_CHANNEL,
        "channels": out_channels,
        "words_ro": words + ".",
    }


__all__ = ["TARGET_PER_CHANNEL", "goal_snapshot"]
