"""Licence release: existing local-first media checks.

Private production traces omitted; implementation unchanged."""

from __future__ import annotations

from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass


@watchdog_pass(
    "licence_release",
    order=130,
    on_error={"released": [], "kept_private": [], "failed": [], "waiting": []},
)
def make_licensed_uploads_public(context: WatchdogContext) -> dict[str, Any]:
    from app.publishing.licence_release import (  # noqa: PLC0415
        licence_held_uploads,
        release_licence_held_uploads,
    )
    from app.workflows.watchdog import _default_publisher_for  # noqa: PLC0415

    if not licence_held_uploads(context.engine):
        return {"released": [], "kept_private": [], "failed": [], "waiting": []}
    return release_licence_held_uploads(
        context.engine,
        _default_publisher_for(context.engine, context.settings),
        context.correlation_id,
    )
