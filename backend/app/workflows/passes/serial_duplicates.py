"""A serial day with two approved episodes is put back to one, after every start (2026-10-17).

Measured on his database at 2026-10-16 23:15:17Z: the held PASS 8caad7d9, rewritten as b8684fc5
and approved the evening before, was approved a second time by the serial stage; canon moved to
episode 5 on it and a second film of the same day, a7db1594, was built — nothing bought yet. The
approvals no longer do that (`app.story.duplicates`); this pass repairs what they did before,
and what a stopped process might leave, through the studio's own code: the day's first approved
episode keeps its number and its film, a later one is closed as superseded, its film retired
through the Director's own closing (`runbook.stages.close_film_books`: REJECTED, what was bought
counted, nothing more bought), and canon is told again without it. A draft left standing beside
a day's approved episode is closed too.

Ordered before `resume_interrupted_day` (20), so a day the restart cut off is resumed only after
the repair, and before `serial_unfilmed` (160), which walks every APPROVED serial film after a
start. Nothing here buys, approves or asks: local writes, and the register's words. A film with
a purchase in flight is left for the next tick. A quiet pass takes no write lock.
"""

from __future__ import annotations

from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass


@watchdog_pass("serial_duplicates", order=10, on_error={"retired": [], "drafts_closed": []})
def retire_duplicate_episodes(context: WatchdogContext) -> dict[str, Any]:
    from app.story.duplicates import repair_duplicate_days  # noqa: PLC0415 - story imports media

    done = repair_duplicate_days(context.engine, context.correlation_id)
    return {
        "retired": [
            {
                "episode_id": item["episode_id"],
                "kept_episode_id": item["kept_episode_id"],
                "storyboard_id": item["storyboard_id"],
                "canon_episode_number": item["canon_episode_number"],
            }
            for item in done["retired"]
        ],
        "waiting": [item.get("waiting") for item in done["waiting"]],
        "drafts_closed": list(done["drafts_closed"]),
    }
