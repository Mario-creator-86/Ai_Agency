"""The Owner's decisions: proposed by anyone, decided only by him (2026-10-03).

His words: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un
card. Trebuie să am propria mea fereastră unde pot să accept sau refuz ce îmi este recomandat
sau trimis.»

Three verbs, three sets of callers:

- ``propose_owner_decision(session, ...)``: an agent, a stage or the audit puts a question in
  front of him. Idempotent by ``dedupe_key`` (one OPEN card per key, enforced by the database
  too), so a stage that notices the same thing every day adds nothing. A proposal is not an
  act: it writes the card and nothing in the ledger.
- ``withdraw_owner_decision(session, ...)``: the condition that made the card necessary has
  cleared (the connection works again). A PENDING card is WITHDRAWN; a card he accepted and
  that waited for his act is completed (ACCEPTED). ``refresh_owner_decisions`` does the same
  for every card whose ``clears_when`` now reads true, and expires what has aged out.
- ``decide_owner_decision(engine, decision_id, command, issued_by=...)``: only "owner". One
  answer per card version (a stale page is 409), idempotent by command id. His accept applies
  the chosen option through his OWN existing command (`APPLIERS`: the budget, the paid-media
  rule, the environment, the autonomy mode), so the same audited path runs as when he moves
  them himself (the command's ledger event and policy version, plus one
  ``owner.decision_decided`` event). An apply that fails leaves the card PENDING with the
  reason in Romanian and changes nothing. A guided option (reconnect a connection, Google's
  consent screen, commercial use, music, licences) records his choice and the place to go,
  and the card waits, WAITING_FOR_OWNER_ACTION, until its condition clears or he marks it
  done.

Atomicity. The Owner's commands each open their own transaction (they serialise on the policy
row), so the apply and the card's transition are two commits. The apply runs first under a
command id derived from the card's id, version and option (`_inner_command_id`): a decide that
is retried after the apply committed and before the card did finds the command already
recorded and does not apply twice; a failed apply commits nothing, so the card cannot be
half-applied.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import ROOT
from app.decisions.models import OPEN_STATUSES, OwnerDecision
from app.models import ApprovalRequest, CommandRecord, OwnerPolicy
from app.services import (
    AutonomyRefused,
    CommandConflict,
    append_event,
    approval_view,
    command_hash,
    film_titles,
    pending_approvals,
    recall_command,
    remember_command,
    utc_now,
)
from app.wording import COMMAND_REUSED, SETTINGS_TABS

logger = logging.getLogger("studio.decisions")

#: The only issuer whose answer decides a card.
OWNER = "owner"

#: The page's words for each state; WAITING_FOR_OWNER_ACTION is his own wording.
STATUS_RO: dict[str, str] = {
    "PENDING": "așteaptă decizia ta",
    "ACCEPTED": "acceptat",
    "REFUSED": "refuzat",
    "WAITING_FOR_OWNER_ACTION": "în așteptarea acțiunii tale",
    "WITHDRAWN": "retras",
    "EXPIRED": "expirat",
}

#: An option that records his answer and changes nothing (keep things as they are).
APPLY_NONE = "none"
#: An option whose answer is recorded for the studio to follow; nothing to apply today.
APPLY_RECORD = "record"
#: An option he carries out himself, at the place the card names.
APPLY_GUIDED = "guided"

#: The ledger events of a card's transitions.
DECIDED_EVENT = "owner.decision_decided"
APPLY_FAILED_EVENT = "owner.decision_apply_failed"
WITHDRAWN_EVENT = "owner.decision_withdrawn"
COMPLETED_EVENT = "owner.decision_completed"
EXPIRED_EVENT = "owner.decision_expired"

#: The command type a decide is remembered under.
DECIDE_COMMAND = "DecideOwnerDecision"

#: What the policy commands' "stale version" says, in his words.
POLICY_MOVED_RO = (
    "Politica studioului s-a schimbat chiar acum; nu s-a aplicat nimic. Reîncarcă fereastra "
    "și decide din nou."
)


class DecisionRefused(Exception):
    """Someone other than the Owner tried to decide a card; nothing changed."""


class DecisionMissing(Exception):
    """The card does not exist."""


class DecisionConflict(Exception):
    """The card moved (a stale version) or is already answered."""


class DecisionInvalid(ValueError):
    """A proposal or an answer that is malformed: an unknown option, two recommendations."""


class DecisionApplyFailed(Exception):
    """His accept could not be applied; the card stays PENDING with this reason."""


# ------------------------------------------------------------------------------- the commands


class DecideCommand(BaseModel):
    """The Owner answers one card: ACCEPT (an option, the recommended one by default), REFUSE,
    or DONE (a guided card he has carried out). Versioned and idempotent by command id; who
    issued it is the route's ``issued_by``, never a body field."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command_id: UUID
    expected_version: int = Field(ge=1)
    decision: Literal["ACCEPT", "REFUSE", "DONE"]
    option_key: str | None = Field(default=None, min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class DecisionOption(BaseModel):
    """One answer a card offers, and how it applies."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[A-Za-z0-9_.\-]{1,60}$")
    label_ro: str = Field(min_length=1, max_length=200)
    effect_ro: str = Field(default="", max_length=2000)
    recommended: bool = False
    apply: dict[str, Any] = Field(default_factory=lambda: {"type": APPLY_NONE})


# --------------------------------------------------------------------- the apply registry

#: An applier runs his existing Owner command for one option: (engine, spec, inner command id,
#: the card's words) -> {"command", "result", "event_id"}. It raises DecisionApplyFailed with a
#: Romanian reason when the command refuses; it commits nothing then.
Applier = Callable[[Engine, Mapping[str, Any], str, Mapping[str, Any]], dict[str, Any]]


def _recorded(engine: Engine, command_id: str) -> dict[str, Any] | None:
    """The response a command id already produced, if it ran."""
    with Session(engine) as session:
        record = session.get(CommandRecord, command_id)
        return dict(record.response) if record is not None else None


def _policy(engine: Engine) -> OwnerPolicy:
    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        if policy is None:
            raise DecisionApplyFailed("Studioul nu este inițializat (lipsește politica).")
        session.expunge(policy)
        return policy


def _expect(current: object, spec: Mapping[str, Any], what_ro: str) -> None:
    """Refuse an apply whose state moved since the card was written: his yes was about it."""
    expected = spec.get("expect")
    if expected is not None and current != expected:
        raise DecisionApplyFailed(
            f"{what_ro} s-a schimbat între timp: acum este {current}, iar cardul a fost scris "
            f"pentru {expected}. Nu s-a aplicat nimic; refuză cardul sau așteaptă unul nou."
        )


def _apply_budget(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    from app.economy.budget import BudgetCommand, set_budget  # noqa: PLC0415
    from app.economy.models import SpendingBudget  # noqa: PLC0415
    from app.economy.services import EconomyError  # noqa: PLC0415

    try:
        command = BudgetCommand(
            period=str(spec.get("period") or "DAILY"),
            limit_usd=str(spec.get("limit_usd") or ""),
            command_id=UUID(inner),
            expected_version=spec.get("expected_version"),
            notes=f"Decizia Proprietarului: {words.get('title_ro') or ''}"[:2000],
        )
    except ValidationError:
        raise DecisionApplyFailed(
            "Bugetul din card nu este o sumă validă; nu s-a aplicat nimic."
        ) from None
    try:
        answer = set_budget(engine, command, set_by=OWNER)
    except EconomyError as exc:
        raise DecisionApplyFailed(str(exc)) from None
    event_id = None
    if answer.get("id"):
        with Session(engine) as session:
            row = session.get(SpendingBudget, str(answer["id"]))
            event_id = row.event_id if row is not None else None
    return {"command": "SpendingBudget", "result": answer, "event_id": event_id}


def _apply_paid_media(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    from app.services import (  # noqa: PLC0415
        PaidMediaApprovalCommand,
        PaidMediaApprovalRefused,
        change_paid_media_approval,
    )

    done = _recorded(engine, inner)
    if done is not None:
        return {"command": "SetPaidMediaApproval", "result": done, "event_id": done.get("event_id")}
    policy = _policy(engine)
    _expect(policy.paid_media_approval, spec, "Regula pașilor plătiți")
    try:
        command = PaidMediaApprovalCommand(
            command_id=UUID(inner),
            expected_version=policy.version,
            paid_media_approval=spec.get("to"),  # type: ignore[arg-type]
            over_usd=spec.get("over_usd"),
        )
    except ValidationError:
        raise DecisionApplyFailed("Regula din card nu este validă; nu s-a aplicat nimic.") from None
    try:
        result = change_paid_media_approval(engine, command, issued_by=OWNER)
    except CommandConflict:
        raise DecisionApplyFailed(POLICY_MOVED_RO) from None
    except PaidMediaApprovalRefused as exc:
        raise DecisionApplyFailed(str(exc)) from None
    return {
        "command": "SetPaidMediaApproval",
        "result": result.model_dump(mode="json"),
        "event_id": result.event_id,
    }


def _apply_policy(kind: str) -> Applier:
    """The environment's and the autonomy mode's commands, which share one shape."""

    def apply(
        engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
    ) -> dict[str, Any]:
        from app.schemas import AutonomyModeCommand, EnvironmentCommand  # noqa: PLC0415
        from app.services import change_autonomy_mode, change_environment  # noqa: PLC0415

        name = "SetEnvironment" if kind == "environment" else "SetAutonomyMode"
        done = _recorded(engine, inner)
        if done is not None:
            return {"command": name, "result": done, "event_id": done.get("event_id")}
        policy = _policy(engine)
        try:
            if kind == "environment":
                _expect(policy.environment, spec, "Mediul studioului")
                result = change_environment(
                    engine,
                    EnvironmentCommand(
                        command_id=UUID(inner),
                        expected_version=policy.version,
                        environment=spec.get("to"),  # type: ignore[arg-type]
                    ),
                )
            else:
                _expect(policy.autonomy_mode, spec, "Modul de autonomie")
                result = change_autonomy_mode(
                    engine,
                    AutonomyModeCommand(
                        command_id=UUID(inner),
                        expected_version=policy.version,
                        autonomy_mode=spec.get("to"),  # type: ignore[arg-type]
                    ),
                )
        except ValidationError:
            raise DecisionApplyFailed(
                "Valoarea din card nu este validă; nu s-a aplicat nimic."
            ) from None
        except CommandConflict:
            raise DecisionApplyFailed(POLICY_MOVED_RO) from None
        except AutonomyRefused as exc:
            raise DecisionApplyFailed(str(exc)) from None
        return {
            "command": name,
            "result": result.model_dump(mode="json"),
            "event_id": result.event_id,
        }

    return apply


def _from_sources(name: str) -> Applier:
    """An applier the studio's producers define (`app.decisions.sources`), imported when it
    runs: the producers import this module, never the other way at import time."""

    def apply(
        engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
    ) -> dict[str, Any]:
        from app.decisions import sources  # noqa: PLC0415

        applier: Applier = getattr(sources, name)
        return applier(engine, spec, inner, words)

    return apply


#: Each option type his accept applies through his own command. Extended with
#: `register_applier`; an option of a type in neither this table nor the three plain types
#: (none, record, guided) is refused when proposed. The two sheet types are the paused sheet
#: repair's (DECISION_SOURCES): let it try again now, or the local move for its blocked scenes.
APPLIERS: dict[str, Applier] = {
    "budget": _apply_budget,
    "paid_media_approval": _apply_paid_media,
    "environment": _apply_policy("environment"),
    "autonomy_mode": _apply_policy("autonomy_mode"),
    "sheet_repair_retry": _from_sources("apply_sheet_repair_retry"),
    "sheet_local_move": _from_sources("apply_sheet_local_move"),
}


def register_applier(kind: str, applier: Applier) -> None:
    """Add an option type whose accept runs one more existing Owner command."""
    if kind in (APPLY_NONE, APPLY_RECORD, APPLY_GUIDED):
        raise ValueError(f"{kind} is a plain option type, not an applier")
    APPLIERS[kind] = applier


# ------------------------------------------------------------------------ the conditions

#: Reads whether a card's question has gone away: (session, card, params, settings) -> bool.
Condition = Callable[[Session, OwnerDecision, Mapping[str, Any], Any], bool]


def _integration_verified(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """The connection was checked and verified, or a model answered on it, after the card was
    written. A connection that no longer exists has nothing left to reconnect."""
    from app.agents.models import AgentRun, ProviderRecord  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415

    integration = session.get(Integration, str(params.get("integration_id") or ""))
    if integration is None:
        return True
    if (
        integration.status in ("VERIFIED", "ACCESS_VERIFIED")
        and integration.checked_at
        and integration.checked_at > row.created_at
    ):
        return True
    provider = session.get(ProviderRecord, integration.id)
    if provider is None:
        return False
    newest = session.scalars(
        select(AgentRun)
        .where(AgentRun.provider_name == provider.name)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    ).first()
    return bool(newest and newest.status == "SUCCEEDED" and newest.started_at > row.created_at)


def _youtube_connected(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    statuses = [c.status for c in session.scalars(select(YouTubeConnection))]
    return bool(statuses) and all(status == "CONNECTED" for status in statuses)


def _commercial_use(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.media.factory import vendor_licence  # noqa: PLC0415

    integration_id = str(params.get("integration_id") or "")
    if session.get(Integration, integration_id) is None:
        return True
    return vendor_licence(session, integration_id).get("commercial_use") is True


def _music_library_has_music(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    from app.media.music_library import load_library  # noqa: PLC0415

    return any(track.kind == "music" for track in load_library().tracks)


def _daily_budget_at_least(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    from app.economy.models import SpendingBudget  # noqa: PLC0415

    limit = session.scalar(
        select(SpendingBudget.limit_usd_micros).where(
            SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True)
        )
    )
    return limit is not None and int(limit) >= int(params.get("usd_micros") or 0)


def _paid_media_approval_is_not(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    policy = session.get(OwnerPolicy, 1)
    current = str(getattr(policy, "paid_media_approval", None) or "EVERY_PAID_STEP")
    return current != str(params.get("value") or "")


def _setting_is_set(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """A setting of his (.env) now has a value. Unknown without the settings: not cleared."""
    if settings is None:
        return False
    return getattr(settings, str(params.get("name") or ""), None) is not None


def media_folder_count(settings: Any = None) -> int:
    """How many film folders the media root holds (read only; nothing is moved or deleted)."""
    from app.media.disk import media_root  # noqa: PLC0415

    root = media_root(settings)
    try:
        return sum(1 for entry in root.iterdir() if entry.is_dir())
    except OSError:
        return 0


def _media_folders_below(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    return media_folder_count(settings) < int(params.get("count") or 0)


def _file_exists(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    names = params.get("any_of") or []
    return any((Path(ROOT) / str(name)).is_file() for name in names)


def _never(session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any) -> bool:
    """Nothing the studio can read clears it (Google's consent screen): only he marks it done."""
    return False


def _condition_from_sources(name: str) -> Condition:
    """A condition the producers define (`app.decisions.sources`), imported when it is read."""

    def check(
        session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
    ) -> bool:
        from app.decisions import sources  # noqa: PLC0415

        condition: Condition = getattr(sources, name)
        return condition(session, row, params, settings)

    return check


CONDITIONS: dict[str, Condition] = {
    "integration_verified": _integration_verified,
    "youtube_connected": _youtube_connected,
    "commercial_use": _commercial_use,
    "music_library_has_music": _music_library_has_music,
    "daily_budget_at_least": _daily_budget_at_least,
    "paid_media_approval_is_not": _paid_media_approval_is_not,
    "setting_is_set": _setting_is_set,
    "media_folders_below": _media_folders_below,
    "file_exists": _file_exists,
    "never": _never,
    "youtube_channel_connected": _condition_from_sources("youtube_channel_connected"),
    "sheet_repair_resumed": _condition_from_sources("sheet_repair_resumed_condition"),
}


def condition_cleared(session: Session, row: OwnerDecision, settings: Any = None) -> bool:
    """Whether the card's ``clears_when`` reads true now. A condition that cannot be read is
    not cleared: the card keeps waiting rather than vanishing on an error."""
    spec = row.clears_when if isinstance(row.clears_when, dict) else None
    if not spec:
        return False
    check = CONDITIONS.get(str(spec.get("type") or ""))
    if check is None:
        return False
    try:
        return bool(check(session, row, spec, settings))
    except Exception as exc:  # noqa: BLE001 - a reading that fails keeps the card, logged
        logger.warning("decision_condition_unreadable", extra={"kind": row.kind}, exc_info=exc)
        return False


# ---------------------------------------------------------------------------------- proposing


def _checked_options(options: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The options validated, the recommended one first; a guided option names its place."""
    if not options:
        raise DecisionInvalid("Un card are cel puțin o opțiune.")
    checked: list[dict[str, Any]] = []
    for raw in options:
        try:
            option = DecisionOption.model_validate(dict(raw)).model_dump()
        except ValidationError as exc:
            raise DecisionInvalid(f"Opțiune invalidă: {exc.errors()[0]['msg']}") from None
        apply = dict(option["apply"])
        kind = str(apply.get("type") or "")
        if kind not in APPLIERS and kind not in (APPLY_NONE, APPLY_RECORD, APPLY_GUIDED):
            raise DecisionInvalid(f"Opțiunea «{option['key']}» are un tip necunoscut: {kind}.")
        if kind == APPLY_GUIDED:
            place = apply.get("place")
            if place:
                if place not in SETTINGS_TABS:
                    raise DecisionInvalid(f"Locul «{place}» nu există în Setări.")
                apply["place_ro"] = SETTINGS_TABS[str(place)]
            if not apply.get("place_ro"):
                raise DecisionInvalid(
                    f"Opțiunea ghidată «{option['key']}» trebuie să spună unde se face."
                )
        option["apply"] = apply
        checked.append(option)
    keys = [option["key"] for option in checked]
    if len(set(keys)) != len(keys):
        raise DecisionInvalid("Două opțiuni au aceeași cheie.")
    if sum(1 for option in checked if option["recommended"]) > 1:
        raise DecisionInvalid("Un card recomandă cel mult o opțiune.")
    # The recommended option leads, the rest keep their order.
    return sorted(checked, key=lambda option: not option["recommended"])


def _open_card(session: Session, dedupe_key: str) -> OwnerDecision | None:
    return session.scalars(
        select(OwnerDecision).where(
            OwnerDecision.dedupe_key == dedupe_key, OwnerDecision.status.in_(OPEN_STATUSES)
        )
    ).first()


def propose_owner_decision(
    session: Session,
    *,
    kind: str,
    dedupe_key: str,
    title_ro: str,
    why_ro: str,
    effect_ro: str,
    options: list[Mapping[str, Any]],
    source: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    clears_when: Mapping[str, Any] | None = None,
    expires_at: str | None = None,
) -> OwnerDecision:
    """Put a question in front of the Owner, in the caller's transaction; return its card.

    Open to agents, stages and the audit: proposing decides nothing. Idempotent by
    ``dedupe_key``: while a card with that key is open (PENDING or waiting for his action) the
    same card is returned unchanged, so the studio never buries his one question under copies
    of it. Once he has answered, the key may be asked again.
    """
    if not dedupe_key or len(dedupe_key) > 200:
        raise DecisionInvalid("Cheia de unicitate a cardului lipsește sau e prea lungă.")
    if clears_when is not None and str(clears_when.get("type") or "") not in CONDITIONS:
        raise DecisionInvalid(f"Condiție necunoscută: {clears_when.get('type')}.")
    checked = _checked_options(options)
    standing = _open_card(session, dedupe_key)
    if standing is not None:
        return standing
    now = utc_now()
    row = OwnerDecision(
        id=str(uuid4()),
        kind=kind[:60],
        subject_type=(subject_type or None) and str(subject_type)[:40],
        subject_id=(subject_id or None) and str(subject_id)[:100],
        title_ro=title_ro[:300],
        why_ro=why_ro,
        effect_ro=effect_ro,
        options=checked,
        clears_when=dict(clears_when) if clears_when else None,
        source=(source or "necunoscut")[:100],
        dedupe_key=dedupe_key,
        status="PENDING",
        expires_at=expires_at,
        version=1,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # Another writer opened the same key between the read and the write: theirs stands.
        standing = _open_card(session, dedupe_key)
        if standing is None:
            raise
        return standing
    return row


# ------------------------------------------------------------------- closing by condition


def _transition(
    session: Session, row: OwnerDecision, status: str, event_type: str, payload: dict
) -> None:
    previous = row.status
    row.status = status
    row.version += 1
    row.updated_at = utc_now()
    event = append_event(
        session,
        event_type,
        "owner_decision",
        row.id,
        row.version,
        {"kind": row.kind, "previous_status": previous, "status": status, **payload},
        str(uuid4()),
    )
    row.event_id = event.event_id


def _close_by_condition(session: Session, row: OwnerDecision, reason_ro: str, by: str) -> None:
    """The question went away: a PENDING card is withdrawn, a waiting one is completed."""
    now = utc_now()
    if row.status == "WAITING_FOR_OWNER_ACTION":
        row.applied = {
            **dict(row.applied or {}),
            "completed_by": "condition",
            "completed_reason_ro": reason_ro,
            "completed_at": now,
        }
        _transition(session, row, "ACCEPTED", COMPLETED_EVENT, {"reason_ro": reason_ro, "by": by})
    else:
        row.applied = {
            **dict(row.applied or {}),
            "withdrawn_reason_ro": reason_ro,
            "withdrawn_by": by,
        }
        _transition(session, row, "WITHDRAWN", WITHDRAWN_EVENT, {"reason_ro": reason_ro, "by": by})


def withdraw_owner_decision(
    session: Session,
    *,
    reason_ro: str,
    dedupe_key: str | None = None,
    decision_id: str | None = None,
    source: str = "studio",
) -> OwnerDecision | None:
    """The condition behind an open card cleared (the connection works again): close it, in
    the caller's transaction. Open to agents and stages: withdrawing a question is not
    deciding it. Returns the card, or None when nothing open matched."""
    if decision_id is not None:
        row = session.get(OwnerDecision, decision_id)
        if row is None or row.status not in OPEN_STATUSES:
            return None
    elif dedupe_key is not None:
        row = _open_card(session, dedupe_key)
        if row is None:
            return None
    else:
        raise DecisionInvalid("Retragerea cere cheia sau identificatorul cardului.")
    _close_by_condition(session, row, reason_ro, source)
    return row


CONDITION_CLEARED_RO = "Situația s-a rezolvat: studioul a văzut că nu mai este nevoie de card."
EXPIRED_RO = "Cardul a expirat fără răspuns."


def refresh_owner_decisions(engine: Engine, settings: Any = None) -> dict[str, int]:
    """Close the open cards whose condition cleared and expire the PENDING ones that aged out.

    Read first, write only when something moved, so a page reading its cards takes no write
    lock on a quiet day. Returns how many cards were withdrawn, completed and expired."""
    now = utc_now()
    with Session(engine) as session:
        moved: list[tuple[str, int, str]] = []
        for row in session.scalars(
            select(OwnerDecision).where(OwnerDecision.status.in_(OPEN_STATUSES))
        ):
            if row.status == "PENDING" and row.expires_at and row.expires_at <= now:
                moved.append((row.id, row.version, "EXPIRED"))
            elif condition_cleared(session, row, settings):
                moved.append((row.id, row.version, "CLEARED"))
    counts = {"withdrawn": 0, "completed": 0, "expired": 0}
    if not moved:
        return counts
    with Session(engine) as session, session.begin():
        for decision_id, version, what in moved:
            card = session.get(OwnerDecision, decision_id)
            if card is None or card.version != version or card.status not in OPEN_STATUSES:
                continue  # it moved meanwhile; the next reading sees it again
            if what == "EXPIRED":
                card.applied = {**dict(card.applied or {}), "expired_reason_ro": EXPIRED_RO}
                _transition(session, card, "EXPIRED", EXPIRED_EVENT, {"reason_ro": EXPIRED_RO})
                counts["expired"] += 1
            else:
                counts["completed" if card.status != "PENDING" else "withdrawn"] += 1
                _close_by_condition(session, card, CONDITION_CLEARED_RO, "condition")
    return counts


# ----------------------------------------------------------------------------------- deciding


def _lock(session: Session) -> None:
    """The serialisation point every Owner command takes: one answer at a time."""
    session.execute(update(OwnerPolicy).where(OwnerPolicy.id == 1).values(id=1))


def _recall(session: Session, command_id: str, fingerprint: str) -> dict[str, Any] | None:
    try:
        return recall_command(session, command_id, fingerprint)
    except CommandConflict:
        raise DecisionConflict(COMMAND_REUSED) from None


def _inner_command_id(decision_id: str, version: int, option_key: str) -> str:
    """The id his own command runs under for this answer: the same card, version and option
    always name the same command, so an answer retried after the apply committed never
    applies twice."""
    return str(uuid5(NAMESPACE_URL, f"amn-ai:owner-decision:{decision_id}:v{version}:{option_key}"))


ALLOWED_FROM: dict[str, tuple[str, ...]] = {
    "ACCEPT": ("PENDING",),
    "REFUSE": ("PENDING", "WAITING_FOR_OWNER_ACTION"),
    "DONE": ("WAITING_FOR_OWNER_ACTION",),
}


def _check_answerable(
    row: OwnerDecision | None, decision_id: str, command: DecideCommand
) -> OwnerDecision:
    if row is None:
        raise DecisionMissing(f"Nu există niciun card cu identificatorul «{decision_id}».")
    if row.status not in ALLOWED_FROM[command.decision]:
        raise DecisionConflict(
            f"Cardul este «{STATUS_RO.get(row.status, row.status)}»; nu mai primește acest "
            "răspuns. Reîncarcă fereastra."
        )
    if row.version != command.expected_version:
        raise DecisionConflict(
            f"Cardul s-a schimbat (versiunea {row.version}, nu {command.expected_version}); "
            "reîncarcă fereastra și decide din nou."
        )
    return row


def _chosen_option(row: OwnerDecision, command: DecideCommand) -> dict[str, Any] | None:
    if command.decision != "ACCEPT":
        return None
    options = [dict(option) for option in (row.options or [])]
    if command.option_key is None:
        recommended = [option for option in options if option.get("recommended")]
        chosen = recommended[0] if recommended else (options[0] if len(options) == 1 else None)
        if chosen is None:
            raise DecisionInvalid("Cardul nu are o opțiune recomandată: alege una.")
        return chosen
    for option in options:
        if option.get("key") == command.option_key:
            return option
    raise DecisionInvalid(f"Cardul nu are opțiunea «{command.option_key}».")


def _record_apply_error(
    engine: Engine, decision_id: str, version: int, option_key: str, reason: str
) -> None:
    """Keep why his accept could not be applied on the card, which stays PENDING."""
    with Session(engine) as session, session.begin():
        row = session.get(OwnerDecision, decision_id)
        if row is None or row.version != version or row.status != "PENDING":
            return
        row.apply_error_ro = reason
        row.updated_at = utc_now()
        append_event(
            session,
            APPLY_FAILED_EVENT,
            "owner_decision",
            row.id,
            row.version,
            {"kind": row.kind, "option": option_key, "reason_ro": reason},
            str(uuid4()),
        )


def decide_owner_decision(
    engine: Engine,
    decision_id: str,
    command: DecideCommand,
    *,
    issued_by: str,
    settings: Any = None,
) -> dict[str, Any]:
    """The Owner answers one card. Only "owner"; see the module's note on atomicity.

    ACCEPT applies the chosen option (the recommended one when he names none): through his own
    command (APPLIERS), as a recorded answer (none, record), or as a guided card that waits
    for his act. REFUSE closes it with his note. DONE completes a guided card he carried out.
    """
    if issued_by != OWNER:
        raise DecisionRefused(
            "Doar Proprietarul decide un card; răspunsul venit de la "
            f"«{issued_by or 'necunoscut'}» nu a schimbat nimic. Un angajat poate doar propune."
        )
    command_id = str(command.command_id)
    fingerprint = command_hash({"decision_id": decision_id, **command.model_dump(mode="json")})

    with Session(engine) as session, session.begin():
        _lock(session)
        previous = _recall(session, command_id, fingerprint)
        if previous is not None:
            return previous
        row = _check_answerable(session.get(OwnerDecision, decision_id), decision_id, command)
        option = _chosen_option(row, command)
        version = row.version
        words = {"title_ro": row.title_ro, "kind": row.kind}

    spec: dict[str, Any] = dict(option.get("apply") or {}) if option else {}
    kind = str(spec.get("type") or APPLY_NONE)
    option_key = str(option["key"]) if option else ""
    applied_command: dict[str, Any] | None = None
    if option is not None and kind in APPLIERS:
        try:
            applied_command = APPLIERS[kind](
                engine, spec, _inner_command_id(decision_id, version, option_key), words
            )
        except DecisionApplyFailed as exc:
            _record_apply_error(engine, decision_id, version, option_key, str(exc))
            raise

    with Session(engine) as session, session.begin():
        _lock(session)
        previous = _recall(session, command_id, fingerprint)
        if previous is not None:
            return previous
        row = _check_answerable(session.get(OwnerDecision, decision_id), decision_id, command)
        previous_status = row.status
        now = utc_now()
        if command.decision == "REFUSE":
            status = "REFUSED"
            applied = dict(row.applied or {}) or None
        elif command.decision == "DONE":
            status = "ACCEPTED"
            applied = {**dict(row.applied or {}), "completed_by": OWNER, "completed_at": now}
        elif applied_command is not None:
            status = "ACCEPTED"
            applied = {"type": kind, **applied_command}
        elif kind == APPLY_GUIDED:
            applied = {
                "type": APPLY_GUIDED,
                "place": spec.get("place"),
                "place_ro": spec.get("place_ro"),
                "steps_ro": spec.get("steps_ro"),
            }
            if condition_cleared(session, row, settings):
                status = "ACCEPTED"
                applied.update(completed_by="condition", completed_at=now)
            else:
                status = "WAITING_FOR_OWNER_ACTION"
        elif kind == APPLY_RECORD:
            status = "ACCEPTED"
            applied = {"type": APPLY_RECORD, "follow_up_ro": spec.get("follow_up_ro")}
        else:
            status = "ACCEPTED"
            applied = {
                "type": APPLY_NONE,
                "result_ro": spec.get("result_ro") or "Nimic de schimbat: rămâne cum este.",
            }
        if command.decision != "DONE":
            row.chosen_option = option_key or None
            row.note = command.note
            row.decided_by = OWNER
            row.decided_at = now
        elif command.note:
            row.note = command.note
        row.applied = applied
        row.apply_error_ro = None
        row.status = status
        row.version += 1
        row.updated_at = now
        event = append_event(
            session,
            DECIDED_EVENT,
            "owner_decision",
            row.id,
            row.version,
            {
                "kind": row.kind,
                "decision": command.decision,
                "option": option_key or None,
                "previous_status": previous_status,
                "status": status,
                "note": command.note,
                "source": row.source,
                "applied_command": (applied_command or {}).get("command"),
                "applied_event_id": (applied_command or {}).get("event_id"),
            },
            command_id,
        )
        row.event_id = event.event_id
        result = {
            "command_id": command_id,
            "status": "COMMITTED",
            "decision": decision_view(row),
            "event_id": event.event_id,
        }
        remember_command(session, command_id, DECIDE_COMMAND, fingerprint, result)
        return result


# --------------------------------------------------------------------------------- the cards


def decision_view(row: OwnerDecision) -> dict[str, Any]:
    """One card as his window reads it. The options without their internals beyond the type
    and the place; the recommended one named."""
    options = []
    recommended = None
    for option in row.options or []:
        apply = dict(option.get("apply") or {})
        if option.get("recommended") and recommended is None:
            recommended = option.get("key")
        options.append(
            {
                "key": option.get("key"),
                "label_ro": option.get("label_ro"),
                "effect_ro": option.get("effect_ro") or "",
                "recommended": bool(option.get("recommended")),
                "apply_type": apply.get("type") or APPLY_NONE,
                "place_ro": apply.get("place_ro"),
                "steps_ro": apply.get("steps_ro"),
            }
        )
    return {
        "id": row.id,
        "kind": row.kind,
        "subject": (
            {"type": row.subject_type, "id": row.subject_id}
            if row.subject_type or row.subject_id
            else None
        ),
        "title_ro": row.title_ro,
        "why_ro": row.why_ro,
        "effect_ro": row.effect_ro,
        "options": options,
        "recommended_option": recommended,
        "source": row.source,
        "status": row.status,
        "status_ro": STATUS_RO.get(row.status, row.status),
        "chosen_option": row.chosen_option,
        "note": row.note,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at,
        "applied": row.applied,
        "apply_error_ro": row.apply_error_ro,
        "expires_at": row.expires_at,
        "version": row.version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _decision_card(row: OwnerDecision) -> dict[str, Any]:
    view = decision_view(row)
    return {
        **view,
        "card_id": f"decision:{row.id}",
        "source_type": "decision",
        "waiting": row.status in OPEN_STATUSES,
        "answer": {
            "method": "POST",
            "path": f"/api/v1/owner/decisions/{row.id}/decide",
            "accept": "ACCEPT",
            "refuse": "REFUSE",
            "done": "DONE" if row.status == "WAITING_FOR_OWNER_ACTION" else None,
        },
        "context": None,
        "cost_usd": None,
    }


APPROVAL_ACCEPT_RO = "Accept"
APPROVAL_REFUSE_RO = "Refuz"


def _approval_card(view: Any) -> dict[str, Any]:
    """A paid step (or any approval) as a card. It is answered through the existing
    POST /owner/approvals/decision; nothing of that logic is repeated here."""
    title = view.action_label + (f" — «{view.film_title}»" if view.film_title else "")
    waiting = view.result == "PENDING"
    return {
        "card_id": f"approval:{view.id}",
        "source_type": "approval",
        "id": view.id,
        "kind": view.action,
        "subject": {"type": "storyboard" if view.context else "subject", "id": view.subject}
        if view.subject
        else None,
        "title_ro": title,
        "why_ro": view.evidence or "",
        "effect_ro": view.cost_label,
        "options": [
            {
                "key": "APPROVED",
                "label_ro": APPROVAL_ACCEPT_RO,
                "effect_ro": f"Studioul face pasul cerut, cu {view.cost_label}; răspunsul "
                "acoperă un singur pas.",
                "recommended": True,
                "apply_type": "approval",
                "place_ro": None,
                "steps_ro": None,
            },
            {
                "key": "REFUSED",
                "label_ro": APPROVAL_REFUSE_RO,
                "effect_ro": "Pasul nu se face; studioul nu întreabă din nou până expiră "
                "răspunsul.",
                "recommended": False,
                "apply_type": "approval",
                "place_ro": None,
                "steps_ro": None,
            },
        ],
        # The request is the requester's recommendation: he asked to do it.
        "recommended_option": "APPROVED",
        "source": view.requester,
        "status": view.result,
        "status_ro": {
            "PENDING": STATUS_RO["PENDING"],
            "APPROVED": "aprobat",
            "REFUSED": "refuzat",
            "EXPIRED": "expirat",
        }.get(view.result, view.result),
        "chosen_option": None if waiting else view.result,
        "note": view.note,
        "decided_by": view.approver,
        "decided_at": view.decided_at,
        "applied": None,
        "apply_error_ro": None,
        "expires_at": view.expires_at,
        "version": None,
        "created_at": view.created_at,
        "updated_at": view.decided_at or view.created_at,
        "waiting": waiting,
        "answer": {
            "method": "POST",
            "path": "/api/v1/owner/approvals/decision",
            "body": {"approval_id": view.id},
            "accept": "APPROVED",
            "refuse": "REFUSED",
        },
        "context": view.context,
        "cost_usd": view.cost_usd,
    }


#: The letters that ask him something; a STATUS letter or a handoff only informs.
ASKING_INTENTS: tuple[str, ...] = ("REQUEST_INFO", "REQUEST_REVIEW", "CHALLENGE", "ESCALATE")


def _letter_card(letter: Mapping[str, Any]) -> dict[str, Any]:
    raw_body = letter.get("body_json")
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
    sender = letter.get("from_name") or "Directoarea"
    return {
        "card_id": f"letter:{letter['id']}",
        "source_type": "letter",
        "id": letter["id"],
        "kind": str(body.get("kind") or letter.get("intent") or "letter"),
        "subject": None,
        "title_ro": letter.get("subject") or "",
        "why_ro": letter.get("body_text") or "",
        "effect_ro": f"Răspunsul tău ajunge la {sender}; închiderea scrisorii o scoate din listă.",
        "options": [
            {
                "key": "reply",
                "label_ro": "Răspund",
                "effect_ro": f"Scrisoarea ta ajunge la {sender}.",
                "recommended": False,
                "apply_type": "letter",
                "place_ro": None,
                "steps_ro": None,
            },
            {
                "key": "resolve",
                "label_ro": "Închid scrisoarea",
                "effect_ro": "Scrisoarea se închide cu nota ta.",
                "recommended": False,
                "apply_type": "letter",
                "place_ro": None,
                "steps_ro": None,
            },
        ],
        "recommended_option": None,
        "source": sender,
        "status": "PENDING",
        "status_ro": STATUS_RO["PENDING"],
        "chosen_option": None,
        "note": None,
        "decided_by": None,
        "decided_at": None,
        "applied": None,
        "apply_error_ro": None,
        "expires_at": None,
        "version": None,
        "created_at": letter.get("created_at") or "",
        "updated_at": letter.get("created_at") or "",
        "waiting": True,
        "answer": {
            "method": "POST",
            "reply_path": f"/api/v1/agents/messages/{letter['id']}/reply",
            "resolve_path": f"/api/v1/agents/messages/{letter['id']}/resolve",
        },
        "context": None,
        "cost_usd": None,
    }


def _covered_by_card(letter: Mapping[str, Any], covered: set[tuple[str, str]]) -> bool:
    body = letter.get("body_json")
    if not isinstance(body, dict):
        return False
    return (str(body.get("kind") or ""), str(body.get("storyboard_id") or "")) in covered


def _answered_approvals(engine: Engine, limit: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        requests = list(
            session.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.result.in_(("APPROVED", "REFUSED")))
                .order_by(ApprovalRequest.decided_at.desc())
                .limit(limit)
            )
        )
        titles = film_titles(session, requests)
        return [
            _approval_card(approval_view(request, film_title=titles.get(request.subject or "")))
            for request in requests
        ]


def owner_decision_cards(
    engine: Engine,
    settings: Any = None,
    *,
    include_history: bool = True,
    history_limit: int = 50,
    refresh: bool = True,
) -> dict[str, Any]:
    """Everything that waits for the Owner, as one kind of card, newest first, with the count
    the «Decizii (N)» button shows; and, below, the history of what he answered.

    (a) the paid-step approvals (and any approval) still PENDING, answered through the existing
    approvals route; (b) the decision cards PENDING or waiting for his action; (c) the open
    letters to him that ask something, answered through the letters' own routes.
    """
    if refresh:
        try:
            refresh_owner_decisions(engine, settings)
        except Exception as exc:  # noqa: BLE001 - the window still opens; logged
            logger.warning("decision_refresh_failed", exc_info=exc)
    from app.agents.messages import letters_for_owner  # noqa: PLC0415

    approvals = [_approval_card(view) for view in pending_approvals(engine)]
    with Session(engine) as session:
        open_rows = list(
            session.scalars(
                select(OwnerDecision)
                .where(OwnerDecision.status.in_(OPEN_STATUSES))
                .order_by(OwnerDecision.created_at.desc())
            )
        )
        decisions = [_decision_card(row) for row in open_rows]
        closed = (
            [
                _decision_card(row)
                for row in session.scalars(
                    select(OwnerDecision)
                    .where(OwnerDecision.status.not_in(OPEN_STATUSES))
                    .order_by(OwnerDecision.updated_at.desc())
                    .limit(history_limit)
                )
            ]
            if include_history
            else []
        )
    # A letter that carries the same question as an open card (the paused sheet repair writes
    # both) is shown once, as the card: one question, one place to answer it.
    covered = {(row.kind, row.subject_id) for row in open_rows if row.subject_id}
    letters = [
        _letter_card(letter)
        for letter in letters_for_owner(engine, open_only=True, limit=100)
        if letter.get("intent") in ASKING_INTENTS and not _covered_by_card(letter, covered)
    ]
    cards = sorted(
        approvals + decisions + letters, key=lambda card: str(card["created_at"]), reverse=True
    )
    counts = {
        "approvals": len(approvals),
        "decisions": sum(1 for card in decisions if card["status"] == "PENDING"),
        "waiting_action": sum(
            1 for card in decisions if card["status"] == "WAITING_FOR_OWNER_ACTION"
        ),
        "letters": len(letters),
    }
    history: list[dict[str, Any]] = []
    if include_history:
        history = sorted(
            closed + _answered_approvals(engine, history_limit),
            key=lambda card: str(card["decided_at"] or card["updated_at"] or ""),
            reverse=True,
        )[:history_limit]
    return {
        "cards": cards,
        "count": sum(counts.values()),
        "counts": counts,
        "history": history,
        "measured_at": utc_now(),
    }


__all__ = [
    "APPLIERS",
    "CONDITIONS",
    "DecideCommand",
    "DecisionApplyFailed",
    "DecisionConflict",
    "DecisionInvalid",
    "DecisionMissing",
    "DecisionRefused",
    "decide_owner_decision",
    "decision_view",
    "owner_decision_cards",
    "propose_owner_decision",
    "refresh_owner_decisions",
    "register_applier",
    "withdraw_owner_decision",
]
