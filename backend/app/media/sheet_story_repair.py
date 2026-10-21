"""Repair prerequisites before asking the editor to describe a blocked film.

Revisions are new scripts/boards. Purchased media and the original narration keep their
provenance. The event cursor survives retries, including a failed review after a rewrite.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.memory import agent_for_role
from app.agents.messages import post_message
from app.db import lock_for_write
from app.factual.agent_pipeline import NoVerifiedClaims, ScriptRejected, agent_write_script
from app.factual.models import ScriptDraft
from app.factual.story_review import latest_review, review_story, rewrite_notes, story_gate
from app.media.models import Storyboard
from app.media.services import generate_storyboard_from_script
from app.models import DomainEvent
from app.services import append_event

STATE_EVENT = "media.sheet_story_repair_progress"


def progress(engine: Engine, board_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        event = session.scalar(
            select(DomainEvent)
            .where(DomainEvent.event_type == STATE_EVENT, DomainEvent.aggregate_id == board_id)
            .order_by(DomainEvent.sequence.desc())
            .limit(1)
        )
        return dict(event.payload) if event else {}


def save_progress(engine: Engine, board_id: str, state: dict[str, Any], correlation: str) -> None:
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        append_event(session, STATE_EVENT, "storyboard", board_id, 1, state, correlation)


def retire_replaced(
    engine: Engine, board_id: str, replacement_id: str, correlation: str
) -> dict[str, Any] | None:
    """The board a story repair replaced, closed by the Director, or None when it may not be.

    2026-10-11, the Owner, looking at two «How NASA Keeps a Space Telescope Alive With Frozen
    Fuel» in his media list: «De ce există 2 Storyboard? Trebuie doar 1!». The repair wrote
    6fe6a577 for 223fac3a and left the old board APPROVED «in history»: it stayed in his list
    as a second film of the topic, and a later shot-plan re-ask could have made it buyable
    beside its replacement. It is now set REJECTED through the Director's own closing
    (`runbook.stages.close_film_books`, one `runbook.film_retired` event with what was bought
    for it); its takes and files stay where they are, as the old script stays.

    Not closed (None, a later pass tries again) while a purchase of it may be in flight, when
    it has a finished render or is a serial episode (`film_close._unclosable`'s rules), when
    it is no longer open, or while the replacement is not a live board itself."""
    from app.media.film_close import _in_flight, _unclosable  # noqa: PLC0415
    from app.media.shooting_sheet import current_lease  # noqa: PLC0415
    from app.runbook.stages import close_film_books, film_spent_micros  # noqa: PLC0415

    if board_id == replacement_id or current_lease(engine, board_id) is not None:
        return None
    spent = film_spent_micros(engine, board_id)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        board = session.get(Storyboard, board_id)
        new = session.get(Storyboard, replacement_id)
        if board is None or new is None or new.status == "REJECTED":
            return None
        title = str(new.title or replacement_id[:8]).removeprefix("Storyboard: ")
        if _unclosable(session, board) is not None or _in_flight(session, board_id, title):
            return None
        return close_film_books(
            session,
            board,
            spent=spent,
            retired_by="Director",
            correlation=correlation,
            details={
                "reason": (
                    f"Înlocuit de storyboardul nou al aceluiași film («{title}», "
                    f"{replacement_id[:8]}) după reparația poveștii."
                ),
                "replaced_by": replacement_id,
            },
        )


def retire_replaced_boards(engine: Engine, correlation: str) -> list[str]:
    """Every board a story repair replaced and left open, closed (`retire_replaced`): the
    boards replaced before 2026-10-11, and any a closing missed (a purchase was in flight)."""
    with Session(engine) as session:
        pairs: dict[str, str] = {}
        for event in session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == STATE_EVENT)
            .order_by(DomainEvent.sequence)
        ):
            replacement = (event.payload or {}).get("replacement_storyboard_id")
            if replacement:
                pairs[str(event.aggregate_id)] = str(replacement)
        open_ids = set(
            session.scalars(
                select(Storyboard.id).where(
                    Storyboard.id.in_(list(pairs)), Storyboard.status != "REJECTED"
                )
            )
        )
    closed = []
    for board_id in sorted(open_ids):
        if retire_replaced(engine, board_id, pairs[board_id], correlation) is not None:
            closed.append(board_id)
    return closed


def _handoff(
    engine: Engine, board_id: str, parent: str, role: str, reason: str, correlation: str
) -> None:
    from app.agents.models import AgentMessage  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        director = agent_for_role(session, "Director")
        employee = agent_for_role(session, role)
        post_message(
            session,
            intent="HANDOFF",
            subject=f"Remediere înainte de cadre: {role}",
            body={
                "kind": "shooting_sheet_repair_work",
                "storyboard_id": board_id,
                "executed_by_worker": True,
                "responsible_role": role,
            },
            body_text=reason,
            from_agent_id=director.id if director else None,
            to_agent_id=employee.id if employee else None,
            in_reply_to=parent if session.get(AgentMessage, parent) else None,
            correlation_id=correlation,
        )


def repair_story(
    engine: Engine,
    registry: Any,
    board_id: str,
    correlation: str,
    parent: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """One durable revision per task; later scans continue without an attempt ceiling."""
    state = progress(engine, board_id)
    if state.get("replacement_storyboard_id"):
        retire_replaced(engine, board_id, str(state["replacement_storyboard_id"]), correlation)
        return {"status": "REVISED", **state}
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        if board is None:
            raise ValueError("Storyboard absent")
        script_id = str(state.get("candidate_script_id") or board.script_draft_id)
        original_script_id = board.script_draft_id
        aspect_ratio = board.aspect_ratio
        script = session.get(ScriptDraft, script_id)
        if script is None:
            raise ValueError("Script absent")
        topic_id, seconds = script.topic_id, script.target_duration_seconds
        passed, why = story_gate(session, script_id)
        review = latest_review(session, script_id)
        notes = list((review.notes_json or {}).get("notes") or []) if review else []
        retention = review.retention_json if review else None
    # SCENE_TOO_LONG (2026-10-10): a scene no clip of the motion model carries, even slowed
    # down locally. No prompt makes it shorter; the story is rewritten with the scene split.
    split = [i for i in issues if i["code"] == "SCENE_TOO_LONG"]
    visual_rewrite = split + [i for i in issues if i["code"] in ("KIND_MISMATCH", "CARD_INVALID")]
    if passed and not visual_rewrite and script_id == original_script_id:
        return None
    if not passed and review is None:
        _handoff(engine, board_id, parent, "Director", why, correlation)
        reading = review_story(engine, registry, script_id, correlation, continuous=True)
        notes = list(reading.get("notes") or [])
        retention = reading.get("retention")
        with Session(engine) as session:
            passed, why = story_gate(session, script_id)
        if passed and not visual_rewrite and script_id == original_script_id:
            return None
    # A candidate that passed is reused, even after a crash before its board was saved.
    if not passed or (visual_rewrite and script_id == original_script_id):
        notes = [
            "Repair this existing film, preserving its topic, supported facts and language. "
            "Describe chart scenes as DATA_CARD with a valid card specification and cited "
            "values; reserve LIVE for actual pictures. Do not invent new facts.",
            *(
                [
                    "A scene named below is longer than one clip of the video model can carry: "
                    "split it into two scenes, each with its own picture and part of its "
                    "narration, without adding facts."
                ]
                if split
                else []
            ),
            # Her notes and the retention row she judged the story against (`rewrite_notes`).
            *rewrite_notes(notes[:5], retention),
            *[i["detail"] for i in visual_rewrite[:2]],
        ]
        _handoff(engine, board_id, parent, "ScriptWriter", "\n".join(notes), correlation)
        try:
            written = agent_write_script(
                engine,
                registry,
                topic_id,
                correlation,
                target_duration_seconds=seconds,
                notes=notes,
            )
        except (ScriptRejected, NoVerifiedClaims) as error:
            role = "FactChecker" if isinstance(error, NoVerifiedClaims) else "ScriptWriter"
            return {
                "status": "UNRESOLVED",
                "responsible_role": role,
                "reason": str(error)[:1000],
                "code": "SCRIPT_REPAIR_REQUIRED",
            }
        script_id = str(written["script"]["id"])
        state = {"candidate_script_id": script_id}
        save_progress(engine, board_id, state, correlation)
        reading = review_story(engine, registry, script_id, correlation, continuous=True)
        with Session(engine) as session:
            passed, why = story_gate(session, script_id)
        if not passed:
            return {
                "status": "UNRESOLVED",
                "responsible_role": "ScriptWriter",
                "reason": why,
                "code": "STORY_REVIEW_REQUIRED",
                **state,
            }
    else:
        reading = {"verdict": "PASS"}
    from app.runbook.stages import _director_approves  # noqa: PLC0415

    if not _director_approves(engine, script_id, reading):
        return {
            "status": "UNRESOLVED",
            "responsible_role": "Director",
            "reason": "Scenariul revizuit nu a trecut aprobarea și verificarea dovezilor.",
            "code": "SCRIPT_APPROVAL_REQUIRED",
            **state,
        }
    # Reuse a board created immediately before an interrupted task's checkpoint.
    with Session(engine) as session:
        replacement = session.scalar(
            select(Storyboard.id)
            .where(Storyboard.script_draft_id == script_id, Storyboard.status != "REJECTED")
            .order_by(Storyboard.created_at.desc())
        )
    if replacement is None:
        replacement = generate_storyboard_from_script(
            engine, script_id, None, aspect_ratio, correlation
        )["id"]
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            old = session.get(Storyboard, board_id)
            new = session.get(Storyboard, replacement)
            if old and new:
                new.channel_id, new.series_key = old.channel_id, old.series_key
                new.production_overrides_json = dict(old.production_overrides_json or {})
    state = {
        "candidate_script_id": script_id,
        "replacement_storyboard_id": replacement,
        "reason": "Directorul a aprobat scenariul revizuit. Editorul continuă pe foaia nouă; "
        "storyboardul vechi se închide, iar fișierele lui rămân în istoric.",
        "responsible_role": "VideoEditor",
    }
    save_progress(engine, board_id, state, correlation)
    retire_replaced(engine, board_id, replacement, correlation)
    return {"status": "REVISED", **state}
