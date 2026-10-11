"""What each published film cost against what it returned, computed (2026-10-11).

The Director's reviews were hard-wired to «report what a film cost against what it returned»
for the Accountant. On 2026-10-11 that sent Nadia three HANDOFFs she answered nine times
without a figure: her prompt held the day's counts only, and she wrote that the cost «cannot
be attributed». It was one join away. Every paid step is booked on its board, the narration
on the board's render (`analytics.performance.film_cost`), and what the film returned is in
`analytics_snapshot`.

So the report is computed here, with no model and no letter:

- per published film, its cost in the books, ESTIMATED (the studio's figure) apart from
  BILLED (an invoice), holds excluded;
- the other boards of the same topic beside it, a rejected first attempt included (the
  «Universe's Missing Pieces» film cost 0 on its own board and 1.62 USD on the one before);
- its returns from the latest snapshot: views, watch time, average view, impressions, CTR,
  likes, comments, shares, subscribers;
- and the agents' cost stated as «neatribuit»: no run carries the film's id yet.

It closes the review it answers (a ``review_<matter>`` decision's subject, and that matter's
thread when the letter asked for this report, `asks_film_cost`), and a published film the
performance page shows with no cost raises it once.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.repairs import (
    APPLIED,
    RepairContext,
    finding,
    outcome,
    register_repair,
)
from app.agents.repairs.desk import (
    close_decision,
    director_of,
    fingerprint,
    usd_ro,
)
from app.db import lock_for_write
from app.wording import count, decimal

#: The agents' share of a film's cost, until film-stage runs carry the board's id.
AGENT_COST_RO = "neatribuit"
#: The action the reviews were given, which this report answers (`command.ACTION_REPAIRS`).
FILM_COST_ACTION = "report what a film cost against what it returned"
#: Besides every review (``review_<matter>``: its action was hard-wired to this report until
#: 2026-10-11), the matter whose decision asked a department for it whatever words it used.
FILM_COST_MATTERS = ("idle_costs_unread",)


def asks_film_cost(matter_key: str | None, action: str | None = "") -> bool:
    """Whether a decision asked what a film cost: known by its matter, or by how its action
    begins. Never by the action's whole text: her model writes it in its own words («Report
    what a film cost against what it returned for the 3 measured films to …»), and three such
    decisions of 2026-10-11 were missed by an equality."""
    key = str(matter_key or "")
    if key.startswith("review_") or key in FILM_COST_MATTERS:
        return True
    return " ".join(str(action or "").casefold().split()).startswith(FILM_COST_ACTION)


def _cost_view(cost: Mapping[str, Any] | None) -> dict[str, Any]:
    if not cost or not cost.get("rows"):
        return {
            "estimated_usd": None,
            "reconciled_usd": None,
            "billed_usd": None,
            "total_usd": None,
            "rows": 0,
        }
    return {
        "estimated_usd": usd_ro(int(cost["estimated_usd_micros"])),
        "reconciled_usd": usd_ro(int(cost.get("reconciled_usd_micros") or 0)),
        "reconciled_usd_micros": int(cost.get("reconciled_usd_micros") or 0),
        "billed_usd": usd_ro(int(cost["billed_usd_micros"])),
        "total_usd": usd_ro(int(cost["total_usd_micros"])),
        "total_usd_micros": int(cost["total_usd_micros"]),
        "rows": int(cost["rows"]),
        "providers": sorted(cost.get("by_provider") or {}),
    }


def _returns(session: Session, publication_id: str) -> dict[str, Any] | None:
    """The film's latest snapshot, LIFETIME first; None when it was never measured."""
    from app.analytics.models import AnalyticsSnapshot  # noqa: PLC0415

    rows = list(
        session.scalars(
            select(AnalyticsSnapshot)
            .where(AnalyticsSnapshot.publication_id == publication_id)
            .order_by(AnalyticsSnapshot.snapshot_at.desc())
        )
    )
    latest = next((row for row in rows if row.window == "LIFETIME"), rows[0] if rows else None)
    if latest is None:
        return None
    return {
        "window": latest.window,
        "snapshot_at": latest.snapshot_at,
        "views": int(latest.views),
        "watch_time_seconds": float(latest.watch_time_seconds),
        "average_view_percentage": float(latest.average_view_percentage),
        "impressions": int(latest.impressions),
        "ctr_percentage": float(latest.ctr_percentage),
        "likes": int(latest.likes),
        "comments": int(latest.comments),
        "shares": int(latest.shares),
        "subscribers_gained": int(latest.subscribers_gained),
        "subscribers_lost": int(latest.subscribers_lost),
    }


def film_report(engine: Any, publication_ids: list[str] | None = None) -> dict[str, Any]:
    """Every published film (or the ones named), oldest first, with its cost and returns."""
    from app.analytics.performance import film_cost  # noqa: PLC0415
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.media.models import Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.publishing.models import PublicationRecord  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415

    films: list[dict[str, Any]] = []
    with Session(engine) as session:
        query = select(PublicationRecord).where(PublicationRecord.status == "PUBLISHED")
        if publication_ids:
            query = query.where(PublicationRecord.id.in_(publication_ids))
        for pub in session.scalars(query.order_by(PublicationRecord.published_at)):
            job = session.scalars(
                select(VideoRenderJob)
                .where(VideoRenderJob.output_asset_id == pub.media_asset_id)
                .order_by(VideoRenderJob.started_at.desc())
            ).first()
            board = session.get(Storyboard, job.storyboard_id) if job is not None else None
            script = session.get(ScriptDraft, board.script_draft_id) if board is not None else None
            siblings: list[dict[str, Any]] = []
            if script is not None and board is not None:
                for other in session.scalars(
                    select(Storyboard)
                    .join(ScriptDraft, ScriptDraft.id == Storyboard.script_draft_id)
                    .where(ScriptDraft.topic_id == script.topic_id, Storyboard.id != board.id)
                    .order_by(Storyboard.created_at)
                ):
                    view = _cost_view(film_cost(session, other.id))
                    if view["rows"]:
                        siblings.append({"storyboard_id": other.id, "status": other.status, **view})
            films.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "published_at": pub.published_at,
                    "privacy": pub.privacy_status,
                    "storyboard_id": board.id if board is not None else None,
                    "topic_id": script.topic_id if script is not None else None,
                    "cost": _cost_view(film_cost(session, board.id) if board is not None else None),
                    "siblings": siblings,
                    "returns": _returns(session, pub.id),
                    "agent_cost": AGENT_COST_RO,
                }
            )
    return {"films": films, "agent_cost": AGENT_COST_RO, "measured_at": utc_now()}


def report_words(report: Mapping[str, Any]) -> str:
    """The report as the Owner reads it, one sentence per film."""
    films = list(report.get("films") or [])
    if not films:
        return "Niciun film publicat încă: nu este nimic de socotit."
    lines: list[str] = []
    for film in films:
        cost = film["cost"]
        spent = (
            f"{cost['total_usd']} USD în cărți ({cost['estimated_usd']} estimat, "
            + (
                f"{cost['reconciled_usd']} estimat și acoperit de factură, "
                if cost.get("reconciled_usd_micros")
                else ""
            )
            + f"{cost['billed_usd']} facturat)"
            if cost["rows"]
            else "niciun cost în cărți"
        )
        returns = film["returns"]
        got = (
            f"{count(returns['views'], 'vizualizare', 'vizualizări')}, "
            f"{decimal(returns['watch_time_seconds'] / 60, 1)} minute vizionate, "
            f"CTR {decimal(returns['ctr_percentage'], 1)} %, "
            f"{count(returns['subscribers_gained'], 'abonat câștigat', 'abonați câștigați')}"
            if returns
            else "încă nemăsurat"
        )
        sibling = ""
        if film["siblings"]:
            spent_before = sum(int(s.get("total_usd_micros") or 0) for s in film["siblings"])
            sibling = (
                f"; pe același subiect, {count(len(film['siblings']), 'altă placă', 'alte plăci')}"
                f" au costat {usd_ro(spent_before)} USD"
            )
        lines.append(
            f"«{film['title']}» ({str(film['published_at'] or '')[:10]}): {spent}{sibling}; "
            f"a adus {got}."
        )
    lines.append(f"Costul agenților pe film: {AGENT_COST_RO} (rulările nu poartă încă filmul).")
    return " ".join(lines)


# ----------------------------------------------------------------------------- detect


def films_without_cost(context: RepairContext) -> list[dict[str, Any]]:
    """Published films the performance page shows with no cost: once per set of films."""
    from app.analytics.performance import video_performance  # noqa: PLC0415

    missing = [film for film in video_performance(context.engine) if film["cost_usd"] is None]
    if not missing:
        return []
    ids = sorted(str(film["publication_id"]) for film in missing)
    return [
        finding(
            "film_cost_missing",
            "film_cost_report",
            observation=(
                f"{count(len(ids), 'film publicat nu are', 'filme publicate nu au')} niciun cost "
                "pe pagina de performanță: "
                + ", ".join(f"«{film['title']}»" for film in missing[:5])
                + "."
            ),
            evidence={"publication_ids": ids},
            params={"publication_ids": ids},
            fingerprint=fingerprint("film_cost_missing", ids),
            scope="PRODUCTION",
            decision="NEEDS_MORE_DATA",
            confidence="MEDIUM",
        )
    ]


# ----------------------------------------------------------------------------- apply


def films_published(context: RepairContext, params: Mapping[str, Any]) -> str | None:
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    with Session(context.engine) as session:
        any_film = session.scalars(
            select(PublicationRecord.id).where(PublicationRecord.status == "PUBLISHED")
        ).first()
    return None if any_film else "Niciun film publicat încă: nu este nimic de socotit."


def report_film_cost(context: RepairContext, params: Mapping[str, Any]) -> dict[str, Any]:
    from app.agents.repairs.threads import close_thread_letters  # noqa: PLC0415
    from app.analytics.models import DirectorDecision  # noqa: PLC0415

    ids = [str(i) for i in params.get("publication_ids") or []] or None
    report = film_report(context.engine, ids)
    words = report_words(report)
    reviewed = str(params.get("decision_id") or "") or None
    closed: list[str] = []
    letters: list[str] = []
    if reviewed:
        # The review of a decision is answered by this report: the decision it reviews is
        # closed with it. Its letter is closed too only when that letter asked for this very
        # report (Nadia's HANDOFFs of 2026-10-11); a department's work the decision handed out
        # (a thumbnail to redo) is still owed after its review, and stays in her runs.
        with Session(context.engine) as session, session.begin():
            lock_for_write(session)
            _director_id, director_name = director_of(session)
            row = session.get(DirectorDecision, reviewed)
            thread = None
            if row is not None and row.message_id and asks_film_cost(row.matter_key, row.action):
                from app.agents.models import AgentMessage  # noqa: PLC0415

                letter = session.get(AgentMessage, row.message_id)
                thread = (letter.thread_id or letter.id) if letter is not None else None
            if close_decision(session, reviewed, words):
                closed.append(reviewed)
            if thread:
                letters = close_thread_letters(
                    session,
                    thread,
                    resolution=words,
                    resolved_by=director_name,
                    correlation_id=context.correlation_id,
                )
    return outcome(
        APPLIED,
        words,
        changed={
            "films": [
                {
                    "publication_id": f["publication_id"],
                    "total_usd": f["cost"]["total_usd"],
                    "views": (f["returns"] or {}).get("views"),
                    "siblings": len(f["siblings"]),
                }
                for f in report["films"]
            ],
            "reviewed_decisions": closed,
            "letters_closed": letters,
            "agent_cost": AGENT_COST_RO,
        },
        letter_subject_ro="Costul filmelor față de ce au adus",
    )


register_repair(
    "film_cost_report",
    report_film_cost,
    # Not a read: it closes the decision it reviews and the letters that asked for it.
    tier="T1",
    action="director.close_review",
    precondition=films_published,
    detector=films_without_cost,
    summary=(
        "compute what each published film cost (estimated and billed, sibling boards of the "
        "same topic) against what it returned, and close the review it answers"
    ),
)
