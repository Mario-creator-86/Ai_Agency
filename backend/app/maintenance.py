"""Start over: the studio's history is deleted, its configuration is kept.

What the agents produced — topics, sources, claims, scripts, storyboards, renders, quality
reports, publications, letters, runs, memories, the day's records, the live ledger — goes;
what the Owner configured — the workforce and its contracts, providers and their catalogues,
credentials, channels and their YouTube bindings, the character bibles, the strategy, the
authorised sites, the treasury and its funding — stays. The ledger then starts at the reset:
one line saying the history was deleted, and everything after it is new.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.models import DomainEvent
from app.services import append_event

logger = logging.getLogger("amn.maintenance")

RESET_EVENT = "studio.history_reset"

#: What the agents did, children before parents so every delete is a plain DELETE.
HISTORY_TABLES: tuple[str, ...] = (
    "editorial_review",
    "quality_control_report",
    "publication_record",
    "video_render_job",
    "storyboard_scene",
    "storyboard",
    "media_asset",
    "hook_option",
    "script_draft",
    "factual_claim",
    "source_snapshot",
    "topic_idea",
    "story_episode",
    "daily_studio_log",
    "content_experiment",
    "analytics_snapshot",
    "director_recommendation",
    "character_identity_change",
    "revenue_evidence",
    "provider_cost_record",
    "agent_message",
    "memory_record",
    "tool_receipt",
    "agent_run",
    "daily_run",
    "safe_mode_record",
    "task_queue",
    "workflow_step",
    "workforce_proposal",
    "trend_snapshot",
    "command_record",
    "youtube_oauth_state",
    "outbox_record",
)


def _tables_with_event_id(raw: Any) -> list[str]:
    names = [row[0] for row in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return [
        name
        for name in names
        if name != "domain_event"
        and any(col[1] == "event_id" for col in raw.execute(f"PRAGMA table_info({name})"))
    ]


def reset_history(engine: Engine, *, media_root: Path | None = None) -> dict[str, Any]:
    """Delete what the agents did and the ledger, keep what the Owner configured.

    Returns the rows deleted per table, the events removed and the media folders emptied.
    Foreign keys are suspended for the one connection doing the deletes and checked before
    they come back on — the same recipe the migrations use — so a half-deleted studio is
    an error, never a state.
    """
    deleted: dict[str, int] = {}
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        if raw is None:
            raise RuntimeError("The reset connection has no SQLite driver connection")
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                # History is immutable by trigger — nothing in the running studio may delete
                # an event, a command or a receipt. Starting over is the one deliberate
                # exception: the delete triggers are dropped for this transaction and put
                # back, verbatim from the catalogue, before it commits.
                guards = connection.execute(
                    text(
                        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
                        "AND name LIKE '%_no_delete'"
                    )
                ).all()
                for name, _ in guards:
                    connection.execute(text(f"DROP TRIGGER {name}"))
                for table in HISTORY_TABLES:
                    count = connection.scalar(text(f"SELECT COUNT(*) FROM {table}")) or 0
                    connection.execute(text(f"DELETE FROM {table}"))
                    deleted[table] = int(count)
                # The ledger goes too — except the few events that configuration rows still
                # cite as their origin (an employee hired, a site authorised, a channel bound).
                # Those stay for the foreign keys and disappear behind the reset line.
                cited: set[str] = set()
                for table in _tables_with_event_id(raw):
                    cited.update(
                        str(row[0])
                        for row in connection.execute(
                            text(
                                f"SELECT DISTINCT event_id FROM {table} WHERE event_id IS NOT NULL"
                            )
                        )
                    )
                total = connection.scalar(text("SELECT COUNT(*) FROM domain_event")) or 0
                if cited:
                    keep = ", ".join(f"'{event_id}'" for event_id in sorted(cited))
                    connection.execute(
                        text(f"DELETE FROM domain_event WHERE event_id NOT IN ({keep})")
                    )
                else:
                    connection.execute(text("DELETE FROM domain_event"))
                deleted["domain_event"] = int(total) - len(cited)
                # Nobody is mid-task on a studio that has no tasks.
                connection.execute(text("UPDATE agent SET runtime_state='IDLE'"))
                # Standing jobs run again on their next tick, not from a remembered last time.
                connection.execute(
                    text(
                        "UPDATE scheduled_job SET last_run_at=NULL, leader_token=NULL, "
                        "leader_expires_at=NULL"
                    )
                )
                for _, sql in guards:
                    connection.execute(text(sql))
            violations = raw.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                tables = sorted({str(row[0]) for row in violations})
                raise RuntimeError("Reset left foreign key violations in: " + ", ".join(tables))
        finally:
            raw.execute("PRAGMA foreign_keys=ON")

    folders = 0
    if media_root is not None and media_root.is_dir():
        for child in media_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                folders += 1
            else:
                child.unlink(missing_ok=True)

    with Session(engine) as session, session.begin():
        append_event(
            session,
            RESET_EVENT,
            "studio",
            "1",
            1,
            {
                "deleted_rows": sum(deleted.values()),
                "events": deleted["domain_event"],
                "messages": deleted["agent_message"],
                "runs": deleted["agent_run"],
                "media_folders": folders,
            },
            str(uuid4()),
        )
    logger.info("history_reset", extra={"deleted": deleted, "media_folders": folders})
    return {"deleted": deleted, "media_folders": folders}


def ledger_floor(session: Session) -> int:
    """The sequence of the latest reset: the ledger starts there, not before."""
    return int(
        session.scalar(
            select(func.max(DomainEvent.sequence)).where(DomainEvent.event_type == RESET_EVENT)
        )
        or 0
    )
