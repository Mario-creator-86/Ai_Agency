"""Films uploaded private only for their licence, made public once it is confirmed (2026-10-10).

See `app.publishing.licence_release`. Film babcf272 went up private to «Main Channel A -
Factual Shorts» because its narrations' licence was not confirmed; the Owner upgrades his
ElevenLabs plan and `vendor_plan_licence` (order 120) records the licence within the hour. This
pass runs after it, so the watchdog pass that records the licence also makes the film public,
under the channel's policy as it is then, the Owner's stop, safe mode and mode read first. A
change YouTube did not answer is asked again on a later pass, with back-off. With no held upload
it only reads the publications and their records, and opens no account.
"""

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
