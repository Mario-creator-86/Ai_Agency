"""The GPU guard: a RunPod GPU found on with no paid step open is switched off.

Not part of the watchdog and not a scheduled job: both are behind STOP AUTONOMIE, and switching
a GPU off must work under it (ADR-GPU-OFF-ALWAYS, amendment of 51: «Oprirea GPU-ului nu este o
acțiune autonomă: nu cheltuie, doar oprește cheltuiala»). It runs in the one process that holds
the worker's lock: at start (BOOT), as a loop every `guard_interval_seconds` while a session is
open or closed less than 15 minutes ago (else every `guard_idle_interval_seconds`), and at
shutdown (`gpu_session.force_off`).

- BOOT: every live session row of another process is an orphan (that process crashed or was
  killed): FORCED_OFF (GUARD_ORPHAN), then every endpoint is checked as on a tick.
- TICK: a session of this process not renewed for `session_stale_seconds` (GUARD_STALE) or past
  its `expires_at` (GUARD_TTL, a letter) is forced off. Then, for each endpoint with no live
  session: read settings + health; anything that can bill (max > 0, running, in progress, in
  queue) is purged, cancelled, max=0 and verified, with an event and one letter per incident;
  a drift from the resting settings (min, idleTimeout, flashboot, timeout) is PATCHed back
  (cost-reducing, always allowed). Three unreadable ticks in a row are one event and a letter.
- Skipped silently: no RunPod integration, a simulation, no key or no endpoint.
- Every pass also looks at the one-time copy pod (`pods.watch_copies`, 2026-10-09): it is
  terminated on success, failure, its time or dollar cap, and at BOOT or SHUTDOWN; any pod named
  amn-mirror-copy that no running copy owns is terminated too. The short interval holds while a
  copy runs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.providers.media_http import MediaProviderError
from app.providers.runpod import pods
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.endpoint import EndpointControl, EndpointSettings, is_off, utc_now
from app.providers.runpod.gpu_session import (
    CLOSING,
    FORCED_OFF,
    LIVE,
    PROCESS_TOKEN,
    GpuSessionRow,
    _open_jobs,
    _switch_off,
    _tell_off,
    _write_event,
    controllable,
    endpoint_lock,
    force_off,
    listed,
    owner_letter,
    remember_reading,
    runpod_targets,
)

if TYPE_CHECKING:
    from app.integrations.vault import CredentialVault
    from app.providers.runpod.client import Transport

logger = logging.getLogger("studio.runpod")

#: Ticks in a row that could not read an endpoint before the Owner is told.
UNREADABLE_TICKS = 3
#: A session closed less than this long ago keeps the guard on its short interval.
RECENT_CLOSE = timedelta(minutes=15)

GUARD_OFF_SUBJECT = "GPU-ul RunPod a fost oprit de paznic"
GUARD_OFF_LETTER = (
    "GPU-ul RunPod a fost găsit pornit fără niciun pas plătit deschis și a fost oprit."
)
UNREADABLE_SUBJECT = "Nu pot verifica GPU-ul RunPod"
UNREADABLE_LETTER = (
    "Nu pot verifica GPU-ul RunPod (cheie sau rețea). Verifică în consola RunPod că 0 workeri "
    "rulează."
)
TTL_SUBJECT = "Un pas a ținut GPU-ul RunPod prea mult"
TTL_LETTER = (
    "Un pas plătit a ținut GPU-ul RunPod pornit peste limita de timp a unei sesiuni; l-am oprit. "
    "Ce s-a cumpărat rămâne; restul nu s-a cumpărat."
)

_COUNTERS_GUARD = threading.Lock()
_UNREADABLE: dict[str, int] = {}


def reset_counters() -> None:
    with _COUNTERS_GUARD:
        _UNREADABLE.clear()


def _count_unreadable(endpoint_id: str, failed: bool) -> int:
    with _COUNTERS_GUARD:
        value = _UNREADABLE.get(endpoint_id, 0) + 1 if failed else 0
        _UNREADABLE[endpoint_id] = value
        return value


def _expire_sessions(
    engine: Engine,
    reason: Literal["TICK", "BOOT", "SHUTDOWN"],
    config_by_id: dict[str, RunPodConfig],
) -> list[dict[str, Any]]:
    """Mark the sessions that no step will close any more FORCED_OFF; returns what was forced."""
    now = datetime.now(UTC)
    forced: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for row in session.scalars(
            select(GpuSessionRow).where(GpuSessionRow.status.in_((*LIVE, CLOSING)))
        ):
            if row.endpoint_id == "mock":
                if reason == "BOOT" and row.process_token != PROCESS_TOKEN:
                    row.status, row.close_reason, row.closed_at = (
                        FORCED_OFF,
                        "GUARD_ORPHAN",
                        utc_now(),
                    )
                continue
            why: str | None = None
            if reason == "BOOT" and row.process_token != PROCESS_TOKEN:
                why = "GUARD_ORPHAN"
            elif reason == "TICK":
                # Any process's session (a page-only second studio may run the Owner's own
                # press) is judged by its renewals, not by whose it is.
                config = config_by_id.get(row.integration_id)
                stale = config.session_stale_seconds if config else 300
                try:
                    renewed = datetime.fromisoformat(row.renewed_at)
                    expires = datetime.fromisoformat(row.expires_at)
                except ValueError:
                    why = "GUARD_STALE"
                else:
                    if expires <= now:
                        why = "GUARD_TTL"
                    elif renewed <= now - timedelta(seconds=stale):
                        why = "GUARD_STALE"
            if why is None:
                continue
            row.status, row.close_reason, row.closed_at = FORCED_OFF, why, utc_now()
            forced.append({"id": row.id, "endpoint_id": row.endpoint_id, "reason": why})
    return forced


def _drifted(settings: EndpointSettings, config: RunPodConfig) -> list[str]:
    drift = []
    if settings.workers_min != 0:
        drift.append("workers.min")
    if settings.idle_timeout is not None and settings.idle_timeout != config.idle_timeout_seconds:
        drift.append("workers.idleTimeout")
    if settings.flashboot is not None and settings.flashboot != config.flashboot:
        drift.append("flashboot")
    if settings.timeout_ms is not None and settings.timeout_ms != config.endpoint_timeout_ms:
        drift.append("timeout")
    return drift


def _check_endpoint(
    engine: Engine,
    config: RunPodConfig,
    endpoint_id: str,
    transport: Transport | None,
    summary: dict[str, Any],
    correlation: str,
) -> None:
    with endpoint_lock(endpoint_id):
        with Session(engine) as session:
            live = list(
                session.scalars(
                    select(GpuSessionRow).where(
                        GpuSessionRow.endpoint_id == endpoint_id,
                        GpuSessionRow.status.in_(LIVE),
                    )
                )
            )
        if live:
            # A step of this process is using it; its own close switches it off.
            summary["in_use"].append(endpoint_id)
            return
        control = EndpointControl(config, endpoint_id, transport)
        try:
            settings, health = asyncio.run(control.read())
        except MediaProviderError as exc:
            remember_reading(endpoint_id, None, None, "Nu am putut citi starea GPU-ului RunPod.")
            summary["unreadable"].append(endpoint_id)
            if _count_unreadable(endpoint_id, True) == UNREADABLE_TICKS:
                _write_event(
                    engine,
                    "runpod.gpu_guard_unreadable",
                    endpoint_id,
                    {"endpoint_id": endpoint_id, "http_status": exc.http_status, "code": exc.code},
                    correlation,
                )
                owner_letter(
                    engine,
                    UNREADABLE_SUBJECT,
                    UNREADABLE_LETTER,
                    "runpod_gpu_unreadable",
                    correlation,
                )
            return
        _count_unreadable(endpoint_id, False)
        remember_reading(endpoint_id, settings, health)
        if not is_off(settings, health):
            with Session(engine) as session:
                jobs = _open_jobs(session, endpoint_id, [])
            reading, errors = asyncio.run(_switch_off(control, jobs, verify=True))
            summary["turned_off"].append(endpoint_id)
            _write_event(
                engine,
                "runpod.gpu_guard_off",
                endpoint_id,
                {
                    "endpoint_id": endpoint_id,
                    "found_workers_max": settings.workers_max,
                    "found_running": health.running,
                    "found_in_progress": health.in_progress,
                    "found_in_queue": health.in_queue,
                    "found_idle": health.idle,
                    "errors": errors,
                    "reading": reading.as_dict(),
                },
                correlation,
            )
            owner_letter(
                engine, GUARD_OFF_SUBJECT, GUARD_OFF_LETTER, "runpod_gpu_guard_off", correlation
            )
            if not reading.off:
                _tell_off(engine, endpoint_id, reading, correlation)
            return
        drift = _drifted(settings, config)
        if drift:
            try:
                asyncio.run(control.apply_baseline())
            except MediaProviderError as exc:
                logger.warning(
                    "runpod_baseline_failed",
                    extra={"endpoint_id": endpoint_id, "error": exc.code or type(exc).__name__},
                )
            summary["drift"].append(endpoint_id)
            _write_event(
                engine,
                "runpod.endpoint_settings_drift",
                endpoint_id,
                {"endpoint_id": endpoint_id, "fields": drift},
                correlation,
            )


def run_gpu_guard(
    engine: Engine,
    vault: CredentialVault,
    *,
    reason: Literal["TICK", "BOOT", "SHUTDOWN"],
    transport: Transport | None = None,
) -> dict[str, Any]:
    """One pass of the guard; see the module's text. Never consults the kernel's stop."""
    summary: dict[str, Any] = {
        "reason": reason,
        "endpoints": [],
        "forced": [],
        "turned_off": [],
        "drift": [],
        "unreadable": [],
        "in_use": [],
    }
    correlation = str(uuid4())
    summary["copies"] = _watch_copies(engine, vault, reason, transport)
    targets = [t for t in runpod_targets(engine, vault) if listed(t)]
    if not targets and reason != "BOOT":
        return summary
    if reason == "SHUTDOWN":
        readings = force_off(
            engine,
            vault,
            reason="SHUTDOWN",
            transport=transport,
            integration_ids=[t.integration_id for t in targets],
        )
        summary["endpoints"] = [r.endpoint_id for r in readings]
        summary["turned_off"] = [r.endpoint_id for r in readings if r.off]
        return summary
    config_by_id = {t.integration_id: t.config for t in targets if t.config is not None}
    summary["forced"] = _expire_sessions(engine, reason, config_by_id)
    for forced in summary["forced"]:
        if forced["reason"] == "GUARD_TTL":
            owner_letter(engine, TTL_SUBJECT, TTL_LETTER, "runpod_gpu_session_ttl", correlation)
    for target in targets:
        config = target.config
        assert config is not None
        for _purpose, endpoint_id in config.endpoints():
            if endpoint_id in summary["endpoints"]:
                continue
            summary["endpoints"].append(endpoint_id)
            if target.problem_ro:
                summary["unreadable"].append(endpoint_id)
                continue
            try:
                _check_endpoint(engine, config, endpoint_id, transport, summary, correlation)
            except Exception as exc:  # noqa: BLE001 - one endpoint never stops the others
                logger.warning(
                    "runpod_guard_endpoint_failed",
                    extra={"endpoint_id": endpoint_id, "error": type(exc).__name__},
                )
    return summary


def _watch_copies(
    engine: Engine,
    vault: CredentialVault,
    reason: Literal["TICK", "BOOT", "SHUTDOWN"],
    transport: Transport | None,
) -> dict[str, Any] | None:
    try:
        return pods.watch_copies(engine, vault, reason=reason, transport=transport)
    except Exception as exc:  # noqa: BLE001 - the GPU's own off never waits on the copy
        logger.warning("runpod_mirror_watch_failed", extra={"error": type(exc).__name__})
        return None


def next_interval(engine: Engine, config_seconds: tuple[int, int]) -> int:
    """The short interval while a session is live or closed in the last 15 minutes, or a copy
    pod runs (it is ended one interval before its cap)."""
    active, idle = config_seconds
    if pods.live_copy(engine):
        return active
    since = (datetime.now(UTC) - RECENT_CLOSE).isoformat()
    with Session(engine) as session:
        live = session.scalars(
            select(GpuSessionRow.id).where(GpuSessionRow.status.in_((*LIVE, CLOSING))).limit(1)
        ).first()
        if live is not None:
            return active
        recent = session.scalars(
            select(GpuSessionRow.id).where(GpuSessionRow.closed_at >= since).limit(1)
        ).first()
    return active if recent is not None else idle


def guard_intervals(engine: Engine, vault: CredentialVault) -> tuple[int, int]:
    """(active, idle) seconds from the first real RunPod integration; the defaults otherwise."""
    for target in runpod_targets(engine, vault):
        if controllable(target.config):
            assert target.config is not None
            return target.config.guard_interval_seconds, target.config.guard_idle_interval_seconds
    defaults = RunPodConfig.model_fields
    return (
        int(defaults["guard_interval_seconds"].default),
        int(defaults["guard_idle_interval_seconds"].default),
    )
