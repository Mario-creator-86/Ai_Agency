"""Free management while the one queue worker waits for already submitted GPU work."""

from __future__ import annotations

import logging
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
) -> Callable[[], None] | None:
    """A throttled callback for GPU polling. It runs no queue handler and buys no media.

    The existing management command assigns work through policy-checked durable tasks;
    correspondence answers one eligible letter and retains its model backoff. Both respect
    Owner autonomy STOP. No second worker or competing film lease is introduced.
    """
    config = settings or Settings()  # type: ignore[call-arg]  # BaseSettings reads Owner token from env.
    if registry is None or not config.worker_enabled:
        return None
    last = clock()

    def check() -> None:
        nonlocal last
        moment = clock()
        if moment - last < config.director_check_interval_seconds or shutdown_requested(engine):
            return
        with Session(engine) as session:
            policy = session.get(OwnerPolicy, 1)
            if policy is None or policy.autonomy_stopped:
                return
        last = moment
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

    return check
