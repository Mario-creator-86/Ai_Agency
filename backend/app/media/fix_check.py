"""What a scene's words were rewritten to fix, so the next still is checked for exactly that.

The Owner, 2026-10-12, 16:50, after stopping the studio (19.50 USD of RunPod that day, 11.05
of it on redos, and all three films still failing QC): «Sistemul trebuie să refacă promptul!
... DAR SĂ REFACĂ CE A FOST GREȘIT. Și să se asigure că ce a fost greșit este acum corectat.
Nu să facă aceeași greșeală la nesfârșit!»

Until then the loop checked the WORDS and never the PICTURE against the mistake: the
Director's brief, the Video Editor's rewrite and her review (`scene_rewrite.review_rewrite`:
each finding, whether it is treated, by which new sentence) proved that the prompt answers
the finding; the new still was then judged only against its prompt and the scene (the stills
gate's matches_plan and shows_scene), and the film's picture QC — after the clip, the
assembly and the money — was the first to say the mistake was still there. On f06808c9 scene
4 the finding was «two women face to face instead of a single on Nadia»; nothing between the
rewrite and the finished film looked for the two women.

`open_findings` names, for one scene, the findings the scene's current words were rewritten
to fix: the review's findings on the newest rewrite of the picture by her brief (each with the
sentence that treats it, `expected`), and the film QC's own words about the scene on that
brief. The stills step gives them to the gate (`still_gate.StillPlan.must_fix`), the vision
check asks of each one whether the new still still shows it (`picture_qc.judge_still`), and a
still that repeats the mistake is refused before any clip is bought on it
(`still_gate.decide`, violation ``finding_persists``). A still approved after the rewrite was
already checked: nothing is open then.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.media.models import SceneTake
from app.models import DomainEvent

#: At most this many items are checked on a still, each at most this long: the gate's question
#: stays one look at one picture, and the refusal's words stay inside a take's failure detail.
MAX_ITEMS = 4
MAX_CHARS = 300
#: The layer of a rewrite that changed the picture's words (`scene_rewrite.STILL`). A motion
#: rewrite keeps the still's words as they were, so it leaves nothing for a still to show.
PICTURE_LAYER = "still"
#: The studio's own notes that travel with the film's findings in a brief's ``failures`` (the
#: reasons `runbook.stages._correct_before_redo` hands `rewrite_for_redo`: the Director's
#: proposals and `SAME_PROMPT_NOTE` beside the report's words). They say what the studio buys
#: or did, not what anybody saw in a picture, so they are never asked of a still. Read on the
#: 2026-10-12 database copy: «Scena 5: mișcarea filmată din imaginea nouă.» rode on every brief
#: of 1c038a99 scene 5 as a «film» finding.
PROCESS_NOTES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^scena \d+: mișcarea filmată din imaginea nouă\.?$", re.IGNORECASE),
    re.compile(r"^scena \d+: filmul se reasamblează", re.IGNORECASE),
    re.compile(r"^the movement of this scene was rewritten before", re.IGNORECASE),
)


def _said(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cut(text: str, limit: int = MAX_CHARS) -> str:
    """At most ``limit`` characters, cut at a word with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _is_process_note(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROCESS_NOTES)


def _scene_of(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload.get("scene_index"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _moment(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def _later(first: Any, second: Any) -> bool:
    """Whether ``first`` is later than ``second`` (ISO timestamps, as `utc_now` writes them)."""
    a, b = _moment(first), _moment(second)
    if a is not None and b is not None and (a.tzinfo is None) == (b.tzinfo is None):
        return a > b
    return str(first or "") > str(second or "")


def _rewrote_picture(payload: dict[str, Any]) -> bool:
    """Whether a rewrite by her brief changed the picture's words (its ``layer``; for a record
    without one, whether its still prompt changed)."""
    layer = payload.get("layer")
    if layer:
        return str(layer) == PICTURE_LAYER
    return _said(payload.get("still_prompt")) != _said(payload.get("old_still_prompt"))


def open_findings(session: Session, storyboard_id: str, scene_index: int) -> list[dict[str, str]]:
    """The findings the scene's current picture words were rewritten to fix, each as
    {"finding", "expected"} (``expected``: the new sentence her review said treats it; empty
    for the film QC's own words), at most `MAX_ITEMS`, each at most `MAX_CHARS`.

    Read from the newest `assembler.SCENE_PROMPTS_REWRITTEN_EVENT` of the scene by her brief
    (reason `scene_rewrite.REWRITE_REASON`) that changed the picture, and from her brief that
    goes with it (`scene_rewrite.BRIEF_EVENT`, its ``failures`` of kind ``film``). Empty when
    there is none, or when a still of the scene was made after it and approved: that still was
    checked for them (a still made before the rewrite, on the old words, never was)."""
    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415 - a large module
    from app.media.scene_rewrite import BRIEF_EVENT, REWRITE_REASON  # noqa: PLC0415

    rewrite: DomainEvent | None = None
    briefs_after: list[DomainEvent] = []  # newest first: the briefs recorded after the rewrite
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.aggregate_id == storyboard_id,
            DomainEvent.event_type.in_((SCENE_PROMPTS_REWRITTEN_EVENT, BRIEF_EVENT)),
        )
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if _scene_of(payload) != int(scene_index):
            continue
        if event.event_type == BRIEF_EVENT:
            briefs_after.append(event)
            continue
        if payload.get("reason") == REWRITE_REASON and _rewrote_picture(payload):
            rewrite = event
            break
    if rewrite is None:
        return []
    approved = session.scalars(
        select(SceneTake.created_at).where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.scene_number == int(scene_index),
            SceneTake.kind == "still",
            SceneTake.status == "APPROVED",
        )
    ).all()
    if any(_later(made, rewrite.timestamp) for made in approved):
        return []

    items: list[dict[str, str]] = []
    known: set[str] = set()

    def add(finding: Any, expected: Any) -> None:
        said = _said(finding)
        if not said or _is_process_note(said) or said.casefold() in known:
            return
        known.add(said.casefold())
        items.append({"finding": _cut(said), "expected": _cut(_said(expected))})

    payload = rewrite.payload if isinstance(rewrite.payload, dict) else {}
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    for entry in (review or {}).get("findings") or []:
        if isinstance(entry, dict):
            add(entry.get("finding"), entry.get("by"))
    # Her brief is recorded right after the rewrite it asked for (`scene_rewrite._rung`): the
    # one naming the rewrite's run, else the first one after it.
    run_id = payload.get("run_id")
    brief = next(
        (
            event
            for event in briefs_after
            if run_id and (event.payload or {}).get("rewrite_run_id") == run_id
        ),
        briefs_after[-1] if briefs_after else None,
    )
    brief_payload = brief.payload if brief is not None and isinstance(brief.payload, dict) else {}
    for failure in brief_payload.get("failures") or []:
        if isinstance(failure, dict) and failure.get("kind") == "film":
            for reason in failure.get("reasons") or []:
                add(reason, "")
    return items[:MAX_ITEMS]
