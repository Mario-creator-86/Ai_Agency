"""The balance a paid step asks for: its next round only (the Owner, 2026-10-03).

His question: «De ce avem nevoie de așa de multe credite dacă să creezi o imagine costă 10-20
de credite». His LHC film waited with 316 credits on the Runway account: its stills step was
going to buy 8 scenes x 2 candidates x 9 credits = 144 credits, but before it started it asked
the balance for its whole cap (432: the first round plus two re-roll rounds) x 1.15 = 497. On
a card he chose «Doar pentru runda următoare». The rule, for every paid media step:

- To START the step, the balance must hold the cost of its next round only, times the margin
  (``settings.paid_step_balance_margin``, 1.15): the stills step's first round (every scene it
  buys, two candidates each), the test shot's one shot, the motion step's shots, a redo's one
  purchase (`needed_credits`, `start_refusal_ro`).
- BEFORE EACH FURTHER purchase (a stills request, a re-roll round, a clip-QC retry, the next
  shot) the balance is read again and must hold that purchase's price times the margin. When it
  does not, that scene stops cleanly: NEEDS_OWNER with ``failure_kind`` LOW_BALANCE and a
  Romanian reason naming the balance and what is needed (`purchase_stop_ro`); what was bought
  is kept, nothing half-done is charged, nothing more is bought in the step, and the scene is
  not held against him (a top-up lets it go on).
- The cap he approved stays the absolute ceiling of the step, exactly as before.
- A balance that cannot be read, or that the vendor refuses to say, still stops the step
  (fail closed).

Every reading a paid step takes is recorded (`record_balance_reading`, BALANCE_READ_EVENT), so
the Owner's low-balance card clears on the books when a later reading covers the need, and
never on a vendor call made from his feed.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.wording import count

#: The margin over the next round when no setting names one (STUDIO_PAID_STEP_BALANCE_MARGIN).
DEFAULT_MARGIN = 1.15
#: The refusal status, and the failure kind a scene stopped on the balance carries.
LOW_BALANCE = "LOW_BALANCE"
#: A paid step read the vendor's balance: {credits, needed_credits, step, storyboard_id}.
BALANCE_READ_EVENT = "media.paid_step_balance_read"


def margin_of(settings: Any = None) -> float:
    """The Owner's margin (``paid_step_balance_margin``), or 1.15 when nothing names one."""
    value = getattr(settings, "paid_step_balance_margin", None) if settings is not None else None
    return float(value or DEFAULT_MARGIN)


def needed_credits(price: float, margin: float) -> int:
    """What the balance must hold before a purchase of ``price`` credits: rounded up, once.

    The product is rounded to six places first, so 20 x 1.15 (22.999999999999996 in floating
    point) asks 23 and not 24, and 144 x 1.15 asks 166.
    """
    return max(0, math.ceil(round(float(price) * float(margin), 6)))


def missing_credits(balance: float, needed: int) -> int:
    """How many credits the account lacks for ``needed`` (0 when it holds them)."""
    return max(0, math.ceil(round(float(needed) - float(balance), 6)))


def _credits(value: float) -> str:
    return count(math.floor(float(value)), "credit", "credite")


def _percent(margin: float) -> int:
    return round((float(margin) - 1) * 100)


def start_refusal_ro(
    balance: float, round_credits: float, cap_credits: float, margin: float, what: str
) -> str:
    """Why a paid step does not start: the balance, its next round, the need, the cap.

    ``what`` names the step in a sentence («pasului de imagini», «cadrului de probă»).
    """
    needed = needed_credits(round_credits, margin)
    return (
        f"Sold Runway insuficient: {_credits(balance)}. Runda următoare a {what} costă "
        f"{_credits(round_credits)}; cu marja de {_percent(margin)}% contul trebuie să aibă "
        f"{_credits(needed)}. Plafonul aprobat rămâne {_credits(cap_credits)}, limita "
        f"pasului întreg. Alimentați contul cu cel puțin "
        f"{_credits(missing_credits(balance, needed))}; nu se cumpără nimic până atunci."
    )


def round_line_ro(round_credits: float, cap_credits: float, margin: float) -> str:
    """The sheet's line under a step: what it starts on, its likely cost, its cap."""
    needed = needed_credits(round_credits, margin)
    return (
        f"Pornește cu {_credits(needed)} în cont: runda următoare costă "
        f"{_credits(round_credits)}, plus marja de {_percent(margin)}%. Plafonul aprobat "
        f"rămâne {_credits(cap_credits)}, limita pasului întreg; înaintea fiecărei cumpărări "
        "de după prima soldul se citește din nou."
    )


def purchase_stop_ro(scene: int, balance: float, price: float, margin: float, what: str) -> str:
    """Why one scene stops before its next purchase (``what``: «o nouă cerere de imagini»,
    «reluarea imaginilor», «cadrul», «reluarea cadrului după controlul clipului»)."""
    needed = needed_credits(price, margin)
    return (
        f"Scena {scene}: soldul Runway ({_credits(balance)}) nu acoperă {what} "
        f"({_credits(price)}; cu marja de {_percent(margin)}%, {_credits(needed)}). Ce s-a "
        "cumpărat rămâne, nimic nu se cumpără pe jumătate și în acest pas nu se mai cumpără "
        f"nimic. Scena se reia după ce alimentați contul cu cel puțin "
        f"{_credits(missing_credits(balance, needed))}."
    )


def low_balance_record(
    scene: int, balance: float, price: float, margin: float, reason: str
) -> dict:
    """The step summary's ``low_balance``: where it stopped, the balance and the need."""
    needed = needed_credits(price, margin)
    return {
        "scene_index": int(scene),
        "credits": float(balance),
        "price_credits": int(math.ceil(float(price))),
        "needed_credits": needed,
        "missing_credits": missing_credits(balance, needed),
        "reason_ro": reason,
    }


def record_balance_reading(
    engine: Engine,
    credits: float,
    *,
    storyboard_id: str,
    step: str,
    needed: int | None,
    correlation_id: str,
) -> None:
    """Keep one balance reading of a paid step on the books (an event; it buys nothing)."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415 - services imports media

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        append_event(
            session,
            BALANCE_READ_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {
                "credits": float(credits),
                "needed_credits": needed,
                "step": step,
                "storyboard_id": storyboard_id,
            },
            correlation_id,
        )
