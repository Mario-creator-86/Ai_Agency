"""The Owner's «Oprește GPU acum» holds until he allows the GPU again (2026-10-12).

16:52:08 that day he pressed «Oprește GPU acum» while the Director's repair of «The Particle That
Shouldn't Exist (And Briefly Didn't)» was buying a clip of scene 5; the clip was cancelled, and
25 s later the same walk opened a new GPU session and bought the same clip again. His button
switched the GPU off for the job it caught and held nothing after it. Now his press is a hold
(`providers.runpod.gpu_session.OWNER_HOLD_EVENT`): every paid step's precheck and every
`open_session` refuse to switch the GPU on while it stands (OWNER_HOLD, nothing sent, nothing
spent), and this card is his one way back:

- **allow**: «Permite din nou pașii plătiți» — the hold is lifted on the record; the studio's paid
  steps may switch the GPU on again, under his paid-media rule, the budgets and the film ceiling.

The card has no «keep» option: while he does not answer, the hold stands and the card waits.
It closes by itself (`gpu_hold_lifted`) once the hold is lifted.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.decisions.services import (
    propose_owner_decision,
    register_applier,
    register_condition,
)
from app.db import lock_for_write
from app.services import utc_now

logger = logging.getLogger("studio.decisions.gpu_hold")

KIND = "gpu_owner_hold"
SOURCE = "runpod"
DEDUPE_KEY = "gpu-owner-hold"
#: The option type his accept applies.
GPU_HOLD_LIFT = "gpu_hold_lift"
#: The condition that closes the card by itself.
GPU_HOLD_LIFTED = "gpu_hold_lifted"
OWNER = "owner"


def propose_gpu_hold_card(engine: Engine) -> str | None:
    """His card after «Oprește GPU acum»: the GPU stays off until he allows it again. Returns
    the card id (the standing card's when one is open). Never raises into his button."""
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            card = propose_owner_decision(
                session,
                kind=KIND,
                dedupe_key=DEDUPE_KEY,
                source=SOURCE,
                subject_type="runpod",
                subject_id="gpu",
                title_ro="Ai oprit GPU-ul: pașii plătiți stau până permiți din nou",
                why_ro=(
                    "Ai apăsat «Oprește GPU acum». Studioul nu mai pornește GPU-ul pentru nicio "
                    "imagine sau clip, la niciun film, până nu alegi aici. Directoarea poate "
                    "citi și rescrie prompturi între timp; nimic nu se cumpără."
                ),
                effect_ro="Nimic nu se cumpără pe RunPod până nu permiți din nou.",
                options=[
                    {
                        "key": "allow",
                        "label_ro": "Permite din nou pașii plătiți",
                        "effect_ro": (
                            "Studioul poate porni din nou GPU-ul pentru pașii plătiți, sub regula "
                            "ta pentru pașii plătiți, bugete și plafonul fiecărui film."
                        ),
                        "recommended": False,
                        "apply": {"type": GPU_HOLD_LIFT},
                    }
                ],
                clears_when={"type": GPU_HOLD_LIFTED, "since": utc_now()},
            )
            return str(card.id)
    except Exception as exc:  # noqa: BLE001 - the hold itself stands without the card
        logger.warning("gpu_hold_card_not_proposed", extra={"error": type(exc).__name__})
        return None


def apply_gpu_hold_lift(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His «Permite din nou»: the hold lifted on the record."""
    from app.providers.runpod.gpu_session import set_owner_hold  # noqa: PLC0415

    set_owner_hold(engine, False, by=OWNER, command_id=inner)
    return {"command": "LiftGpuOwnerHold", "result": {"on": False}, "event_id": None}


def gpu_hold_lifted(session: Session, card: Any, params: Mapping[str, Any], settings: Any) -> bool:
    """The question went away: the newest hold record says off."""
    from app.models import DomainEvent  # noqa: PLC0415
    from app.providers.runpod.gpu_session import OWNER_HOLD_EVENT  # noqa: PLC0415

    newest = session.scalar(
        select(DomainEvent)
        .where(DomainEvent.event_type == OWNER_HOLD_EVENT)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    )
    payload = newest.payload if newest is not None and isinstance(newest.payload, dict) else {}
    return newest is not None and not payload.get("on")


register_applier(GPU_HOLD_LIFT, apply_gpu_hold_lift)
register_condition(
    GPU_HOLD_LIFTED,
    gpu_hold_lifted,
    missing_ro="Lipsește: GPU-ul e încă oprit de tine; alege «Permite din nou» când vrei.",
)

__all__ = ["DEDUPE_KEY", "KIND", "propose_gpu_hold_card"]
