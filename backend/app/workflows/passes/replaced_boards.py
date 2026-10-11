"""Boards a story repair replaced, closed by the studio itself (2026-10-11).

The Owner, looking at two «How NASA Keeps a Space Telescope Alive With Frozen Fuel» in his
media list: «De ce există 2 Storyboard? Trebuie doar 1!». A story repair writes a new board
for a film and, until that day, left the old one APPROVED. The repair now closes the board it
replaces (`sheet_story_repair.retire_replaced`); this pass closes the ones it left before, and
any whose closing waited for a purchase in flight. Nothing here buys or asks the Owner: a
board closed is REJECTED by the Director, with its takes and files kept.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.workflows.passes import WatchdogContext, watchdog_pass


@watchdog_pass("replaced_boards", order=145, on_error={"closed": []})
def close_replaced_boards(context: WatchdogContext) -> dict[str, Any]:
    from app.media.sheet_story_repair import retire_replaced_boards  # noqa: PLC0415

    return {"closed": retire_replaced_boards(context.engine, str(uuid4()))}
