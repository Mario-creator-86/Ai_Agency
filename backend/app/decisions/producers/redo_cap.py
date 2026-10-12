"""The paid-redo cap reached: the Owner's card, not a loop of the Director's (2026-10-12).

«The Particle That Shouldn't Exist (And Briefly Didn't)» (1c038a99), 11:51: the film failed
quality control on one real flaw (scene 5's picture), the Director decided REPAIR three times
in eleven seconds, and each time the repair answered «Scena 5: nu se mai cumpără automat, s-a
atins limita de 5 refaceri plătite pe scenă» — his cap (`Settings.film_max_paid_redos_per_scene`,
`film_max_paid_redos`) — and the film waited in her inbox, where the review pass would have put
it before her again every hour, with the same answer, twenty-four times. The cap is money, and
money is his (his rule: only money stops a film; what is his reaches him as a card). So when a
repair she decided can buy nothing because of the cap, this card asks him, once per film:

- **allow**: `EXTRA_REDOS` more paid redos for this film (`ALLOWANCE_EVENT`, read by the cap in
  `runbook.stages._apply_repairs` through `redo_allowance`), and the film's continuation is
  queued so her repair runs again now;
- **publish**: the film is published as it is — his ACCEPT, carried out as hers is
  (`director_qc.accept_film`, ``decided_by`` owner), the continuation queued to publish it;
- **close**: his own «Închide filmul» (`media.film_close.close_film`);
- **wait**: nothing; the card stays.

The card closes by itself (`redo_cap_cleared`) once the film is closed, published, passed by
a decision, or given an allowance after the card was written. Nothing here buys: an allowance
only moves his cap; the purchase stays behind may_act, the budgets and the film's ceiling.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.decisions.services import (
    DecisionApplyFailed,
    propose_owner_decision,
    register_applier,
    register_condition,
)
from app.services import append_event, utc_now
from app.wording import count

logger = logging.getLogger("studio.decisions.redo_cap")

KIND = "redo_cap_reached"
SOURCE = "director_qc"
#: His allowance, on the film's record: {storyboard_id, extra, report_id, granted_by}.
ALLOWANCE_EVENT = "media.redo_allowance_granted"
#: How many more paid redos one accept of «allow» gives the film (per scene and per film).
EXTRA_REDOS = 5
#: The option types his accept applies.
REDO_ALLOW = "redo_allowance"
FILM_PUBLISH_AS_IS = "film_publish_as_is"
FILM_CLOSE_CAPPED = "film_close_capped"
#: The condition that closes the card by itself.
REDO_CAP_CLEARED = "redo_cap_cleared"
OWNER = "owner"


def dedupe_key(storyboard_id: str) -> str:
    return f"redo-cap:{storyboard_id}"


def redo_allowance(session: Session, storyboard_id: str) -> int:
    """How many paid redos beyond his settings the Owner allowed this film, in all."""
    from app.models import DomainEvent  # noqa: PLC0415 - imported inside, as the core does

    total = 0
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == ALLOWANCE_EVENT, DomainEvent.aggregate_id == storyboard_id
        )
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        try:
            total += max(0, int(payload.get("extra") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _title_of(session: Session, storyboard_id: str) -> str:
    from app.media.models import Storyboard  # noqa: PLC0415

    board = session.get(Storyboard, storyboard_id)
    title = str(getattr(board, "title", "") or "").strip()
    return title[:120] if title else storyboard_id[:8]


def _director_summary(session: Session, report_id: str) -> str:
    from app.media.director_qc import DECISION_EVENT  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    newest = session.scalar(
        select(DomainEvent)
        .where(DomainEvent.event_type == DECISION_EVENT, DomainEvent.aggregate_id == report_id)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    )
    payload = newest.payload if newest is not None and isinstance(newest.payload, dict) else {}
    return " ".join(str(payload.get("summary") or "").split())[:600]


def propose_redo_cap_card(
    engine: Engine,
    *,
    storyboard_id: str,
    report_id: str,
    media_asset_id: str,
    limited: list[Mapping[str, Any]],
    rounds: Mapping[int, int] | None = None,
) -> str | None:
    """Ask the Owner what becomes of a film whose repair his cap stopped; returns the card id
    (the standing card's when one is open). Never raises into the repair: a card that could
    not be written is logged, and the film's words still say where it stands."""
    scenes = sorted(
        {
            int(item["scene_index"])
            for item in limited
            if isinstance(item, Mapping) and isinstance(item.get("scene_index"), int)
        }
    )
    if not scenes:
        return None
    first = next(item for item in limited if isinstance(item, Mapping))
    per_scene = int(first.get("per_scene") or 0)
    per_film = int(first.get("per_film") or 0)
    spent = dict(rounds or {})
    try:
        with Session(engine) as session, session.begin():
            title = _title_of(session, storyboard_id)
            summary = _director_summary(session, report_id)
            scene_words = ("scena " if len(scenes) == 1 else "scenele ") + ", ".join(
                map(str, scenes)
            )
            used = ", ".join(
                f"scena {scene}: {spent.get(scene, per_scene)} din {per_scene}" for scene in scenes
            )
            why = (
                f"Directoarea a hotărât refacerea pentru {scene_words}, dar regula ta oprește "
                f"cumpărarea după {count(per_scene, 'refacere plătită', 'refaceri plătite')} pe "
                f"scenă și {count(per_film, 'refacere plătită', 'refaceri plătite')} pe film "
                f"({used}; pe film {sum(spent.values())} din {per_film})."
            )
            if summary:
                why += f" Ce a găsit ea: {summary}"
            options = [
                {
                    "key": "allow",
                    "label_ro": f"Mai permit {EXTRA_REDOS} refaceri plătite pentru acest film",
                    "effect_ro": (
                        f"Limita filmului crește cu {EXTRA_REDOS} pe scenă și pe film; "
                        "refacerea hotărâtă de Directoare se reia acum, sub regula ta pentru "
                        "pașii plătiți, bugete și plafonul filmului."
                    ),
                    "recommended": True,
                    "apply": {
                        "type": REDO_ALLOW,
                        "storyboard_id": storyboard_id,
                        "report_id": report_id,
                        "extra": EXTRA_REDOS,
                    },
                },
                {
                    "key": "publish",
                    "label_ro": "Publică filmul așa cum e",
                    "effect_ro": (
                        "Filmul trece controlul de calitate prin decizia ta, cu defectul rămas, "
                        "și merge la publicare; nu se mai cumpără nimic pentru el."
                    ),
                    "apply": {
                        "type": FILM_PUBLISH_AS_IS,
                        "storyboard_id": storyboard_id,
                        "report_id": report_id,
                        "media_asset_id": media_asset_id,
                    },
                },
                {
                    "key": "close",
                    "label_ro": "Închide filmul",
                    "effect_ro": (
                        "Filmul se închide cu registrele lui; ce s-a cumpărat rămâne în arhivă, "
                        "nimic nu se mai cumpără."
                    ),
                    "apply": {
                        "type": FILM_CLOSE_CAPPED,
                        "storyboard_id": storyboard_id,
                        "report_id": report_id,
                    },
                },
                {
                    "key": "wait",
                    "label_ro": "Aștept",
                    "effect_ro": "Filmul rămâne cum e; cardul stă până alegi.",
                    "apply": {"type": "none"},
                },
            ]
            card = propose_owner_decision(
                session,
                kind=KIND,
                dedupe_key=dedupe_key(storyboard_id),
                source=SOURCE,
                subject_type="storyboard",
                subject_id=storyboard_id,
                title_ro=(f"Filmul «{title}» a atins limita de refaceri plătite ({scene_words})"),
                why_ro=why,
                effect_ro="Nimic nu se cumpără pentru acest film până nu alegi.",
                options=options,
                clears_when={
                    "type": REDO_CAP_CLEARED,
                    "storyboard_id": storyboard_id,
                    "since": utc_now(),
                },
            )
            return str(card.id)
    except Exception as exc:  # noqa: BLE001 - the repair's own words stand without the card
        logger.warning(
            "redo_cap_card_not_proposed",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
        )
        return None


# ------------------------------------------------------------------- his accept, applied


def _continuation(session: Session, storyboard_id: str, report_id: str, inner: str) -> str | None:
    from app.services import queue_film_continue  # noqa: PLC0415

    return queue_film_continue(
        session,
        storyboard_id,
        key=f"film-continue-{storyboard_id}-redo-cap-{inner}",
        payload={"cause": f"director_qc:{report_id}", "report_id": report_id},
    )


def apply_redo_allowance(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His «allow»: the allowance on the film's record, and the film's continuation queued so
    the Director's repair runs again now. Idempotent by the inner command id."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415

    storyboard_id = str(spec.get("storyboard_id") or "")
    report_id = str(spec.get("report_id") or "")
    extra = int(spec.get("extra") or EXTRA_REDOS)
    if not storyboard_id or not report_id:
        raise DecisionApplyFailed("Cardul nu numește filmul sau raportul.")
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        done = session.scalar(
            select(DomainEvent).where(
                DomainEvent.event_type == ALLOWANCE_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.correlation_id == inner,
            )
        )
        if done is None:
            done = append_event(
                session,
                ALLOWANCE_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "storyboard_id": storyboard_id,
                    "report_id": report_id,
                    "extra": extra,
                    "granted_by": OWNER,
                    "command_id": inner,
                },
                inner,
            )
        queued = _continuation(session, storyboard_id, report_id, inner)
        event_id = str(done.event_id)
    return {
        "command": "GrantRedoAllowance",
        "result": {"storyboard_id": storyboard_id, "extra": extra, "continuation": queued},
        "event_id": event_id,
    }


def apply_film_publish_as_is(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His «publish as it is»: the film passes quality control by his decision, carried out
    as the Director's ACCEPT is (`director_qc.accept_film`), and its continuation is queued
    to publish it."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.media.director_qc import accept_film  # noqa: PLC0415
    from app.media.models import QualityControlReport  # noqa: PLC0415

    storyboard_id = str(spec.get("storyboard_id") or "")
    report_id = str(spec.get("report_id") or "")
    with Session(engine) as session:
        report = session.get(QualityControlReport, report_id)
        if report is None:
            raise DecisionApplyFailed("Raportul de calitate al filmului nu mai există.")
        reading = {
            "report_id": report_id,
            "media_asset_id": str(report.media_asset_id),
            "storyboard_id": storyboard_id,
            "report": {
                "status": report.status,
                "score": report.score,
                "checks_json": dict(report.checks_json or {}),
                "failure_reasons_json": list(report.failure_reasons_json or []),
            },
        }
    payload = {
        "report_id": report_id,
        "media_asset_id": reading["media_asset_id"],
        "storyboard_id": storyboard_id,
        "decision": "ACCEPT",
        "decided_by": OWNER,
        "agent_name": "Proprietarul",
        "verdicts": [],
        "summary": (
            "Proprietarul a hotărât publicarea filmului așa cum este: limita de refaceri "
            "plătite a fost atinsă și nu a mai permis altele."
        ),
        "command_id": inner,
    }
    done = accept_film(engine, reading, payload, inner, decided_by=OWNER)
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        queued = _continuation(session, storyboard_id, report_id, inner)
    return {
        "command": "AcceptFilmAsIs",
        "result": {**done, "continuation": queued},
        "event_id": done.get("event_id"),
    }


def apply_film_close_capped(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His «close»: the film closed with its books through the retirement path a rendered
    film has (`director_qc.close_film`; his own CloseFilm command refuses a rendered film),
    his decision on the report's record. A purchase in flight refuses the close."""
    from app.media.director_qc import close_film  # noqa: PLC0415
    from app.media.models import QualityControlReport  # noqa: PLC0415
    from app.media.shooting_sheet import FilmBusy  # noqa: PLC0415

    storyboard_id = str(spec.get("storyboard_id") or "")
    report_id = str(spec.get("report_id") or "")
    with Session(engine) as session:
        report = session.get(QualityControlReport, report_id) if report_id else None
        asset_id = str(report.media_asset_id) if report is not None else ""
    if not storyboard_id or not report_id or not asset_id:
        raise DecisionApplyFailed("Cardul nu numește filmul sau raportul.")
    reading = {"report_id": report_id, "media_asset_id": asset_id, "storyboard_id": storyboard_id}
    payload = {
        "report_id": report_id,
        "media_asset_id": asset_id,
        "storyboard_id": storyboard_id,
        "decision": "CLOSE",
        "decided_by": OWNER,
        "agent_name": "Proprietarul",
        "verdicts": [],
        "summary": "Proprietarul a închis filmul de pe cardul limitei de refaceri plătite.",
        "command_id": inner,
    }
    try:
        done = close_film(engine, reading, payload, inner)
    except FilmBusy as exc:
        raise DecisionApplyFailed(str(getattr(exc, "reason_ro", exc))) from None
    return {"command": "CloseFilm", "result": done, "event_id": done.get("event_id")}


# ------------------------------------------------------------------------- the condition


def redo_cap_cleared(session: Session, card: Any, params: Mapping[str, Any], settings: Any) -> bool:
    """The question went away: the film closed, an allowance granted since the card, a report
    of the film PASSED since the card (hers or his), or the film published."""
    from app.media.models import QualityControlReport, Storyboard, VideoRenderJob  # noqa: PLC0415
    from app.models import DomainEvent  # noqa: PLC0415
    from app.publishing.models import PublicationRecord  # noqa: PLC0415

    storyboard_id = str(params.get("storyboard_id") or "")
    since = str(params.get("since") or getattr(card, "created_at", "") or "")
    board = session.get(Storyboard, storyboard_id)
    if board is None or board.status == "REJECTED":
        return True
    granted = session.scalar(
        select(DomainEvent.event_id).where(
            DomainEvent.event_type == ALLOWANCE_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
            DomainEvent.timestamp >= since,
        )
    )
    if granted is not None:
        return True
    assets = [
        str(asset_id)
        for asset_id in session.scalars(
            select(VideoRenderJob.output_asset_id).where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.output_asset_id.is_not(None),
            )
        )
    ]
    if not assets:
        return False
    passed = session.scalar(
        select(QualityControlReport.id).where(
            QualityControlReport.media_asset_id.in_(assets),
            QualityControlReport.status == "PASSED",
            QualityControlReport.verified_at >= since,
        )
    )
    if passed is not None:
        return True
    published = session.scalar(
        select(PublicationRecord.id).where(PublicationRecord.media_asset_id.in_(assets))
    )
    return published is not None


register_applier(REDO_ALLOW, apply_redo_allowance)
register_applier(FILM_PUBLISH_AS_IS, apply_film_publish_as_is)
register_applier(FILM_CLOSE_CAPPED, apply_film_close_capped)
register_condition(
    REDO_CAP_CLEARED,
    redo_cap_cleared,
    missing_ro=(
        "Lipsește: filmul așteaptă încă alegerea ta — mai cumpăr, îl public așa cum e, sau "
        "îl închid."
    ),
)

__all__ = [
    "ALLOWANCE_EVENT",
    "EXTRA_REDOS",
    "KIND",
    "dedupe_key",
    "propose_redo_cap_card",
    "redo_allowance",
]
