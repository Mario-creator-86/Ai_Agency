"""The voice's commercial licence, read from the vendor's account by the watchdog (2026-10-10).

See `app.integrations.plan_licence`: the Owner's card «Da, citește singur» lets the studio read
his ElevenLabs plan and record the licence when it is paid, so a film can go public without
anybody typing «da» in Setări. A connection that already has the licence is never read again;
one without it at most once an hour (the Owner upgrades his plan, 2026-10-10). A GET that buys
nothing.
"""

from __future__ import annotations

from typing import Any

from app.workflows.passes import WatchdogContext, watchdog_pass


@watchdog_pass("vendor_plan_licence", order=120, on_error={"recorded": [], "checked": []})
def read_vendor_plans(context: WatchdogContext) -> dict[str, Any]:
    from pathlib import Path  # noqa: PLC0415

    from app.integrations.plan_licence import record_plan_licences  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415

    vault = CredentialVault(Path(str(context.engine.url.database)).with_suffix(".credentials.key"))
    return record_plan_licences(context.engine, vault)
