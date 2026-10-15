"""Free management while the one queue worker waits for already submitted GPU work."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OwnerPolicy
from app.runbook.services import shutdown_requested

logger = logging.getLogger("studio.director_upkeep")


def director_wait_work(
    engine: Engine,
    registry: Any,
    *,
    settings: Settings | None = None,
    clock: Callable[[], float] = time.monotonic,
    background: bool = True,
) -> Callable[[], None] | None:
    """A throttled callback for GPU polling. It runs no queue handler and buys no media.

    The existing management command assigns work through policy-checked durable tasks;
    correspondence answers one eligible letter and retains its model backoff. Both respect
    Owner autonomy STOP. No second worker or competing film lease is introduced.

    The free work runs beside the poll, on its own thread (``background``), never in it:
    2026-10-15 16:49Z, a4ecf40a — the Director's company call to the model ran past ten
    minutes inside the motion step's wait, the poll could not collect scene 8 nor renew the
    GPU session, and the guard found a worker idle without an open step and turned it off.
    A round still running when the interval comes again is left to finish; nothing is
    queued twice. ``background=False`` keeps the old synchronous order for tests.
    """
    config = settings or Settings()  # type: ignore[call-arg]  # BaseSettings reads Owner token from env.
    if registry is None or not config.worker_enabled:
        return None
    last = clock()
    round_thread: threading.Thread | None = None

    def perform_all() -> None:
        from app.agents.command import direct_company  # noqa: PLC0415
        from app.agents.mail import correspondence_round  # noqa: PLC0415

        for task, perform in (
            ("management", lambda: direct_company(engine, registry, config, str(uuid4()))),
            ("mail", lambda: correspondence_round(engine, registry, limit=1)),
        ):
            if shutdown_requested(engine):
                break
            try:
                perform()
            except Exception as exc:  # noqa: BLE001 - free work cannot fail the GPU purchase
                logger.warning(
                    "director_wait_work_failed",
                    extra={
                        "task": task,
                        "error_class": type(exc).__name__,
                    },
                )

    def check() -> None:
        nonlocal last, round_thread
        moment = clock()
        if moment - last < config.director_check_interval_seconds or shutdown_requested(engine):
            return
        with Session(engine) as session:
            policy = session.get(OwnerPolicy, 1)
            if policy is None or policy.autonomy_stopped:
                return
        last = moment
        if not background:
            perform_all()
            return
        if round_thread is not None and round_thread.is_alive():
            logger.info("director_wait_work_still_running")
            return
        round_thread = threading.Thread(target=perform_all, name="director-wait-work", daemon=True)
        round_thread.start()

    def running() -> bool:
        return round_thread is not None and round_thread.is_alive()

    setattr(check, "running", running)  # noqa: B010 - read by tests and the poll's log
    return check
