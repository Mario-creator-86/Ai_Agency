"""Phase 10 preflight — what the studio can actually do right now.

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` asks for a preflight that reports READY,
DEGRADED or BLOCKED. The whole value of that answer is that it is not optimistic. A preflight
that rounds a missing provider up to READY produces a run that fails halfway through having told
the Owner it was fine, which is worse than not running: the failure arrives after the Owner has
stopped paying attention.

So each check reports one of three things about one capability — present, absent, or unknown —
and the overall verdict is the worst of them. Nothing is probed over the network here: a
preflight that made outbound calls would be slow, would fail for reasons unrelated to the studio,
and would still only tell you about the moment it ran.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.agents.vision import vision_agent
from app.config import Settings
from app.economy.budget import budget_status, estimate_film_cost_micros
from app.economy.prices import price_for
from app.economy.services import format_micros
from app.media.factory import describe as describe_media
from app.media.factory import media_readiness
from app.media.models import CharacterBible, MediaAsset
from app.media.toolchain import find_ffprobe
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import bound_connection_id, channel_bindings
from app.research.service import research_health
from app.services import studio_environment, utc_now
from app.wording import autonomy_mode as mode_words
from app.wording import budget_period, budget_state, count, provider_name
from app.wording import environment as environment_words
from app.youtube.models import YouTubeConnection
from app.youtube.services import (
    ANALYTICS_REFUSED,
    STATISTICS_SCOPE,
    TOKEN_REFRESH_FAILED,
    UPLOAD_SCOPE,
    granted_scope_set,
    scope_label,
)

#: A check that stops the day entirely. Everything else degrades it.
BLOCKING = "BLOCKING"
DEGRADING = "DEGRADING"
#: A line that tells the Owner something about the run he is about to get and can never fail
#: it. The autonomy mode is the one such line: MANUAL is not a fault to be repaired, it is his
#: decision, and a preflight that called it DEGRADED would be asking him to fix his own answer.
#: The verdict below is computed over the other two severities only, so this holds structurally
#: and not by the check happening to pass.
INFORMATIONAL = "INFORMATIONAL"

#: What each mode means for the day about to run, in the Owner's language. The mode is said
#: as the governance panel names it; its code stays in the line's ``value``.
MODE_MEANS = {
    "MANUAL": (
        "Modul de autonomie este manual: etapele care doar pregătesc merg singure, iar "
        "randarea plătită și publicarea rămân deciziile tale."
    ),
    "SUPERVISED": (
        "Modul de autonomie este supravegheat: etapele interne de rutină merg singure, iar "
        "publicarea îți cere mai întâi aprobarea."
    ),
    "AUTONOMOUS_CEO": (
        "Modul de autonomie este CEO autonom: ziua merge singură în limitele politicii; "
        "porțile dure rămân la fel de închise."
    ),
}


#: A connected YouTube account, counted in the Owner's words.
CONNECTED_ACCOUNTS = ("cont YouTube conectat", "conturi YouTube conectate")

#: The two units an agent run is costed in (`app.economy.prices.llm_cost_vr`). Both sides must
#: be priced or the cost is None, so half a price is no price here either: a run priced on one
#: side only would be read by the budget as cheaper than it was.
TOKEN_UNITS = ("per_1m_input_tokens", "per_1m_output_tokens")


def _check(
    name: str,
    ok: bool,
    severity: str,
    present: str,
    absent: str,
    detail: str = "",
    value: Any = None,
) -> dict[str, Any]:
    """One line of the preflight. ``message`` and ``detail`` are what the Owner reads (the
    page prints them side by side), so both are Romanian with the codes said as words;
    ``value`` is the same fact as data — the mode, the budget's period and state, the
    environment — for a page or a test that needs the code itself."""
    return {
        "name": name,
        "ok": ok,
        "severity": severity,
        "message": present if ok else absent,
        "detail": detail,
        "value": value,
    }


# --------------------------------------------------------------- what the Owner alone supplies
#
# The five checks below are about the film the day produces rather than about whether it may
# start, and each one names something only the Owner can give the studio. None of them is
# BLOCKING, and two of the five are informational: a budget he has not set while the studio is
# in TEST, and a serial channel he has not created, are decisions of his. A preflight that
# refused the day over them would be asking him to repair his own answer.
#
# Each reads the database and nothing else — no vendor is asked, no key is used, no job is
# queued — so the preflight stays as cheap and as safe on the hundredth run as on the first.


def _budget_check(engine: Engine) -> dict[str, Any]:
    """Whether any budget is active at all.

    With none, `reserve_spend` still takes the write lock and still holds the film's money —
    it simply has no limit to refuse it against, so a day of retries can spend whatever the
    vendor will sell. The figure is his and nobody else's: the Accountant escalates, it does
    not approve.
    """
    budgets = budget_status(engine)["budgets"]
    said = ", ".join(
        f"{budget_period(b['period'])} {b['limit_usd']} USD ({budget_state(b['state'])})"
        for b in budgets
    )
    return _check(
        "spending_budget",
        bool(budgets),
        DEGRADING,
        f"{count(len(budgets), 'buget activ', 'bugete active')}: {said}.",
        "Niciun buget activ: rezervarea ține banii filmului, dar nu are de ce să îl refuze. "
        "Pune-l cu PUT /economy/budget (biroul Contabilitate); nimeni altcineva nu îl poate pune.",
        value=[
            {"period": b["period"], "limit_usd": b["limit_usd"], "state": b["state"]}
            for b in budgets
        ],
    )


def _price_check(session: Session) -> dict[str, Any]:
    """Whether the models the day's employees think with have a price on both token sides.

    Measured on the live copy: 391 `agent_run` rows carried `cost_vr` NULL, because no price
    existed for the models they ran on, so the books saw a fraction of the day. The check
    names the provider kinds that are unpriced and never invents a figure for them — a price
    is the Owner's, and a guessed one in the books is worse than the gap the Accountant reports.
    """
    running = session.execute(
        select(ProviderRecord.provider_type, ModelRecord.model_name)
        .select_from(Agent)
        .join(ModelRecord, ModelRecord.id == Agent.model_id)
        .join(ProviderRecord, ProviderRecord.id == ModelRecord.provider_id)
        .where(
            Agent.lifecycle == "ACTIVE",
            Agent.provider_id.is_not(None),
            Agent.model_id.is_not(None),
        )
    ).all()
    # The price table is keyed by the connection's kind, which is what the adapter passes to
    # `price_lookup`; `ProviderRecord.provider_type` holds it (upper case for the seeded
    # endpoint, lower case for one the Owner saved in Settings).
    wanted = {(str(kind or "").lower(), str(model)) for kind, model in running if kind and model}
    unpriced = {
        (kind, model)
        for kind, model in wanted
        if any(price_for(session, kind, model, unit) is None for unit in TOKEN_UNITS)
    }
    kinds = sorted({kind for kind, _ in unpriced})
    models = ", ".join(f"{kind}:{model}" for kind, model in sorted(unpriced))
    if not wanted:
        # Nothing runs, so nothing is unpriced. The `agents` check above is where a studio
        # with no runnable employee is reported; saying it twice would read as two faults.
        return _check(
            "model_prices",
            True,
            DEGRADING,
            "Niciun angajat cu model alocat, deci nu este nimic de prețuit.",
            "",
        )
    return _check(
        "model_prices",
        not unpriced,
        DEGRADING,
        f"{count(len(wanted), 'model', 'modele')} pe care rulează angajații "
        f"{'are' if len(wanted) == 1 else 'au'} preț pe jetoane.",
        f"Modele fără preț pe jetoane la: {', '.join(kinds)}. Până când îl tastezi "
        "(PUT /economy/prices, pe model sau «*» pentru tot felul), fiecare rulare a unui "
        "angajat se înregistrează fără cost, iar cărțile văd o fracțiune din zi. Studioul nu "
        "inventează un preț.",
        detail=models or f"{count(len(wanted), 'model prețuit', 'modele, toate prețuite')}",
    )


def _vision_check(session: Session) -> dict[str, Any]:
    """Whether any active employee's model the provider says can see.

    Without one, `picture_qc` and `character_drift_qc` are NOT_APPLICABLE on every film and
    certify nothing — which is honest, and which also means a film of eight blank fields
    passes every automatic check and reaches the Director as a finished short. The Owner has
    no other single place that tells him this, so the line says the consequence, not the fact.
    """
    seer = vision_agent(session)
    return _check(
        "vision_capability",
        seer is not None,
        DEGRADING,
        f"{seer[1]} poate privi imaginile." if seer else "",
        "Niciun angajat activ nu are un model care declară vedere: verificarea imaginilor și "
        "cea a personajelor stau deoparte la fiecare film, deci un film de câmpuri goale ar "
        "trece toate verificările automate. Alocă un model cu vedere unui angajat "
        "(Angajați → Model).",
        detail=f"{seer[0]} {seer[1]}" if seer else "",
    )


def _readable_reference(session: Session, character: CharacterBible) -> bool:
    """Whether one of the bible's slots holds a picture the studio could actually draw from.

    A slot holds a stored asset id or null, never a description standing in for an image. The
    row must exist — that is what `image_reference_for_scene` refuses a locked character's film
    over — and its file must still be on disk, because `picture_qc` reads the bytes: a row
    pointing at a file that was moved looks filled here and has nothing to compare against
    there. One `stat` on a local path is not a probe; nothing is opened over the network.
    """
    slots = (
        character.reference_assets_json if isinstance(character.reference_assets_json, dict) else {}
    )
    for value in slots.values():
        if not isinstance(value, str) or not value.strip():
            continue
        asset = session.get(MediaAsset, value.strip())
        if asset is None:
            continue
        try:
            if Path(asset.uri_or_path).is_file():
                return True
        except OSError:
            continue
    return False


def _character_reference_check(session: Session) -> dict[str, Any]:
    """Whether the characters that matter have a reference picture.

    A character whose look is locked and has no readable reference *refuses* its film rather
    than inventing a face — a blocked day, and one the Owner can prevent the evening before,
    so that case degrades the run and names him. A character with no lock simply has none: its
    still is drawn from the prompt as it always was, so that case is a line he reads.
    """
    characters = list(
        session.scalars(select(CharacterBible).order_by(CharacterBible.canonical_name))
    )
    missing = [c for c in characters if not _readable_reference(session, c)]
    locked = [c for c in missing if bool((c.identity_locks_json or {}).get("visual"))]
    unlocked = [c for c in missing if c not in locked]
    names = ", ".join(c.canonical_name for c in locked) or ", ".join(
        c.canonical_name for c in unlocked
    )
    return _check(
        "character_references",
        not missing,
        DEGRADING if locked else INFORMATIONAL,
        f"{count(len(characters), 'personaj', 'personaje')} cu imagine de referință citibilă."
        if characters
        else "Niciun personaj în Character Bible; nu se cere nicio referință.",
        (
            f"Personaje cu înfățișarea blocată și fără imagine de referință citibilă: {names}. "
            "Filmul lor se refuză înainte de prima scenă, în loc să li se inventeze o față. "
            "Produ setul cu POST /media/characters/{id}/reference-set (consumă credite de "
            "imagine, deci este actul tău)."
            if locked
            else f"{count(len(unlocked), 'personaj', 'personaje')} fără imagine de referință: "
            f"{names}. Fiecare imagine "
            "a lor este o invenție nouă, iar verificarea personajelor nu are cu ce compara. "
            "POST /media/characters/{id}/reference-set le produce."
        ),
        detail=names,
    )


def _serial_channel_check(session: Session, bindings: dict[str, dict]) -> dict[str, Any]:
    """Whether the serial has a channel to reach, and whether the Director may approve episodes.

    Both halves are his. A studio with no OFFICE_SERIAL row makes no serial, and a Director
    without the leave leaves every episode DRAFT waiting for his hand — which is his right,
    and is not autonomy. So the line says which of the two is missing and names the command,
    and it never fails the day.
    """
    channel = session.scalar(
        select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
    )
    if channel is None:
        return _check(
            "serial_channel",
            False,
            INFORMATIONAL,
            "",
            "Niciun canal pentru Office Serial: serialul nu are unde ajunge. Creează slotul "
            "în Publicare → Canale.",
            value={"channel_type": "OFFICE_SERIAL", "exists": False},
        )
    bound = bool(bindings.get(channel.id, {}).get("publisher_ready"))
    may_approve = bool(channel.director_may_approve_episodes)
    policy_route = f"POST /publishing/channels/{channel.id}/publish-policy"
    if not bound:
        absent = (
            f"Canalul serialului ({channel.channel_name}) nu este legat de un cont YouTube "
            "conectat: episoadele se produc, dar nu au unde urca. Leagă-l în Publicare → "
            "Sloturi de canale."
        )
    else:
        absent = (
            "Canalul serialului este legat, dar Directoarea nu are dreptul să aprobe episoade: "
            f"fiecare episod rămâne ciornă și te așteaptă pe tine. Dreptul se dă cu "
            f"{policy_route} (director_may_approve_episodes)."
        )
    return _check(
        "serial_channel",
        bound and may_approve,
        INFORMATIONAL,
        "Serialul are canal legat, iar Directoarea poate aproba episoade.",
        absent,
        detail=(
            f"{channel.channel_name}: {'legat' if bound else 'nelegat'}, "
            f"Directoarea {'poate' if may_approve else 'nu poate'} aproba episoade"
        ),
        value={
            "channel_type": "OFFICE_SERIAL",
            "exists": True,
            "bound": bound,
            "director_may_approve_episodes": may_approve,
        },
    )


# ------------------------------------------------------------------ what will stop tomorrow
#
# Three lines the 2026-09-18 rehearsal on a copy of the Owner's studio showed missing. The
# preflight said «Canal YouTube conectat» and «2 sloturi legate» off the stored status
# alone, while both of his connections held youtube.readonly and youtube.upload and not the
# statistics scope, had been granted seven days earlier, and the day stopped at performance
# intake on a token refresh. In PRODUCTION every film holds the whole motion budget (12 USD)
# against his 15 USD daily budget, so the second film of a day is refused. And the summary
# read «Studioul poate rula» above all of it. Each line below still reads the database only:
# the token is judged by what Google already answered, never by asking again.

#: How long Google keeps a refresh token alive while the OAuth app is in Testing. The studio
#: cannot see the app's publishing status, so this is a caveat beside the age, never a verdict.
TESTING_REFRESH_TOKEN_DAYS = 7

#: Google's answers that refuse the token itself, as opposed to Google not being reached:
#: 400 invalid_grant for a revoked or expired grant, 401 for a client it no longer knows,
#: 403 for a use the grant does not cover.
AUTH_REFUSAL_STATUSES = frozenset({400, 401, 403})
AUTH_REFUSAL_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_client",
        "unauthorized_client",
        "access_denied",
        "insufficient_scope",
    }
)

#: How many recorded refresh failures are read, newest first. Enough for every connection
#: many times over; the preflight runs many times an hour and must stay a cheap read.
REFRESH_FAILURES_READ = 500

#: Failed DEGRADING checks that foresee the day losing a film, not merely a worse film. The
#: summary names the first of them (or the first BLOCKING failure) instead of saying the
#: studio can run. A statistics refusal is not here: the films do not depend on statistics.
EMPTIES_THE_DAY = frozenset({"daily_budget_films"})


def _moment(value: str | None) -> datetime | None:
    """A stored ISO timestamp as an aware datetime; None when absent or unreadable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _http_status(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload.get("http_status"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _auth_refused(payload: dict[str, Any]) -> bool:
    """Whether Google refused the account, as opposed to not being reached.

    The analytics adapter decides it where it saw Google's answer and records `auth_refused`;
    that verdict is taken as written. A line without it is judged by the status and Google's
    own word, the only two things it can carry.
    """
    if "auth_refused" in payload:
        return bool(payload.get("auth_refused"))
    word = str(payload.get("oauth_error") or payload.get("error") or "")
    return _http_status(payload) in AUTH_REFUSAL_STATUSES or word in AUTH_REFUSAL_ERRORS


def _answer(payload: dict[str, Any]) -> str:
    """Google's answer as recorded: the status and its own word, never more."""
    word = payload.get("oauth_error") or payload.get("error")
    return " ".join(str(part) for part in (_http_status(payload), word) if part)


def _youtube_slots(session: Session, now: datetime) -> list[dict[str, Any]]:
    """Per bound slot: what Google granted, how old the grant is, and what it last refused.

    Only slots whose connection is CONNECTED — an unbound or disconnected slot is the binding
    check's line. Two refusals are told apart because they stop different things: a refused
    token refresh (`TOKEN_REFRESH_FAILED`) is the token every use of the account shares, the
    upload included; a refused statistics report (`ANALYTICS_REFUSED`, the token was fine) is
    the statistics scope alone. A refusal counts only while nothing has answered it: a
    reconnect (`connected_at`) or a successful verification (`last_checked_at`) after it is a
    new answer from Google. A failure with no answer from Google (the network) is kept apart,
    because it says nothing about the token.
    """
    token_refusals: dict[str, DomainEvent] = {}
    report_refusals: dict[str, DomainEvent] = {}
    silences: dict[str, DomainEvent] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type.in_((TOKEN_REFRESH_FAILED, ANALYTICS_REFUSED)))
        .order_by(DomainEvent.sequence.desc())
        .limit(REFRESH_FAILURES_READ)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        connection_id = str(payload.get("connection_id") or event.aggregate_id or "")
        if not connection_id:
            continue
        if not _auth_refused(payload):
            silences.setdefault(connection_id, event)
        elif event.event_type == ANALYTICS_REFUSED or payload.get("during") == "report":
            report_refusals.setdefault(connection_id, event)
        else:
            token_refusals.setdefault(connection_id, event)

    connections = {row.id: row for row in session.scalars(select(YouTubeConnection))}
    slots: list[dict[str, Any]] = []
    for channel in session.scalars(
        select(ChannelRecord).order_by(ChannelRecord.channel_type, ChannelRecord.channel_name)
    ):
        connection = connections.get(bound_connection_id(channel) or "")
        if connection is None or connection.status != "CONNECTED":
            continue
        granted_at = _moment(connection.connected_at)
        answered = max(
            (m for m in (granted_at, _moment(connection.last_checked_at)) if m), default=None
        )

        def standing(
            event: DomainEvent | None, answered: datetime | None = answered
        ) -> tuple[dict[str, Any] | None, datetime | None]:
            when = _moment(event.timestamp) if event is not None else None
            if event is None or (answered is not None and when is not None and when <= answered):
                return None, None
            return (event.payload if isinstance(event.payload, dict) else {}), when

        token, token_at = standing(token_refusals.get(connection.id))
        report, report_at = standing(report_refusals.get(connection.id))
        silence, silent_at = standing(silences.get(connection.id))
        slots.append(
            {
                "label": f"«{channel.channel_name}» ({connection.name})",
                "channel": channel.channel_name,
                "account": connection.name,
                "scopes": granted_scope_set(connection),
                "age_days": (now - granted_at).days if granted_at else None,
                "granted_on": granted_at.date().isoformat() if granted_at else None,
                "token_refusal": (
                    f"Google a refuzat tokenul pe {token_at:%Y-%m-%d %H:%M} UTC ({_answer(token)})"
                    if token is not None and token_at is not None
                    else ""
                ),
                "report_refusal": (
                    f"Google a refuzat citirea statisticilor pe {report_at:%Y-%m-%d %H:%M} UTC "
                    f"({_answer(report)})"
                    if report is not None and report_at is not None
                    else ""
                ),
                "silence": (
                    f"{silent_at:%Y-%m-%d %H:%M} UTC, fără răspuns de la Google (rețea); nu "
                    "spune nimic despre token"
                    if silence is not None and silent_at is not None
                    else ""
                ),
            }
        )
    return slots


def _slot_detail(slot: dict[str, Any]) -> str:
    scopes = slot["scopes"]
    granted = (
        ", ".join(sorted(scope_label(scope) for scope in scopes))
        if scopes is not None
        else "necunoscute (neînregistrate la conectare)"
    )
    age = (
        f"acordat pe {slot['granted_on']}, de {count(slot['age_days'], 'zi', 'zile')}"
        if slot["age_days"] is not None
        else "data acordării necunoscută"
    )
    last = (
        slot["token_refusal"]
        or slot["report_refusal"]
        or slot["silence"]
        or "niciuna înregistrată după acordare"
    )
    return (
        f"{slot['channel']} → {slot['account']}: drepturi {granted}; {age}; "
        f"ultima reîmprospătare eșuată: {last}"
    )


def _grant_age_caveat(slots: list[dict[str, Any]]) -> str:
    """The age of each grant, and what seven days mean if his Google app is in Testing."""
    ages = ", ".join(
        f"{slot['account']} {count(slot['age_days'], 'zi', 'zile')}"
        if slot["age_days"] is not None
        else f"{slot['account']} vârstă necunoscută"
        for slot in slots
    )
    oldest = max((slot["age_days"] for slot in slots if slot["age_days"] is not None), default=None)
    if oldest is not None and oldest >= TESTING_REFRESH_TOKEN_DAYS:
        tail = (
            f"Dacă aplicația Google OAuth este încă în modul Testing, Google face tokenul să "
            f"expire la {TESTING_REFRESH_TOKEN_DAYS} zile după acordare, deci tokenul poate fi "
            "deja expirat."
        )
    elif oldest is not None:
        tail = (
            f"Dacă aplicația Google OAuth este în modul Testing, tokenul expiră la "
            f"{TESTING_REFRESH_TOKEN_DAYS} zile după acordare, adică peste "
            f"{count(TESTING_REFRESH_TOKEN_DAYS - oldest, 'zi', 'zile')}."
        )
    else:
        tail = (
            f"Dacă aplicația Google OAuth este în modul Testing, tokenul expiră la "
            f"{TESTING_REFRESH_TOKEN_DAYS} zile după acordare."
        )
    return (
        f"Vârsta acordului: {ages}. {tail} Studioul nu vede starea aplicației; un refuz apare "
        "aici abia după ce Google l-a dat."
    )


def _youtube_upload_check(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the films can go out: the upload scope, and no standing refusal of the token.

    BLOCKING, because a film nobody can upload is money spent on nothing: in TEST the day
    uploads private, and a refused token refuses that upload as surely as a public one.
    """
    if not slots:
        return _check(
            "youtube_upload_access",
            True,
            BLOCKING,
            "Niciun slot legat de un cont YouTube conectat, deci niciun token de judecat aici; "
            "legarea sloturilor este linia ei.",
            "",
        )
    problems = []
    for slot in slots:
        if slot["scopes"] is not None and UPLOAD_SCOPE not in slot["scopes"]:
            problems.append(
                f"{slot['label']}: Google nu a acordat dreptul de încărcare (youtube.upload)"
            )
        elif slot["token_refusal"]:
            problems.append(f"{slot['label']}: {slot['token_refusal']}")
    caveat = _grant_age_caveat(slots)
    return _check(
        "youtube_upload_access",
        not problems,
        BLOCKING,
        f"{count(len(slots), 'slot legat', 'sloturi legate')}: "
        f"{'nu arată' if len(slots) == 1 else 'niciunul nu arată'} dreptul de încărcare lipsă "
        f"sau un refuz al tokenului după acordare. {caveat}",
        f"Filmele nu pot urca pe YouTube: {'; '.join(problems)}. Reconectează canalul din "
        "Setări (Conturi și e-mail → Reconectează) și acordă dreptul de încărcare. " + caveat,
        detail=" | ".join(_slot_detail(slot) for slot in slots),
    )


def _youtube_statistics_check(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether yesterday's numbers can be read: the statistics scope, and no standing refusal.

    DEGRADING, never blocking: the films do not depend on statistics, only what the studio
    learns from them does.
    """
    if not slots:
        return _check(
            "youtube_statistics_access",
            True,
            DEGRADING,
            "Niciun slot legat de un cont YouTube conectat, deci nicio statistică de citit.",
            "",
        )
    problems = []
    for slot in slots:
        if slot["token_refusal"] or slot["report_refusal"]:
            refusal = slot["token_refusal"] or slot["report_refusal"]
            problems.append(f"{slot['label']}: {refusal}")
        elif slot["scopes"] is not None and STATISTICS_SCOPE not in slot["scopes"]:
            granted = ", ".join(sorted(scope_label(scope) for scope in slot["scopes"]))
            problems.append(f"{slot['label']}: acordate doar {granted}, fără yt-analytics.readonly")
    return _check(
        "youtube_statistics_access",
        not problems,
        DEGRADING,
        f"{count(len(slots), 'slot legat', 'sloturi legate')}: "
        f"{'nu arată' if len(slots) == 1 else 'niciunul nu arată'} lipsa accesului la "
        "statistici (yt-analytics.readonly) sau un refuz al tokenului după acordare.",
        f"Statisticile YouTube nu pot fi citite pentru {'; '.join(problems)}. Filmele nu depind "
        "de ele: ziua le face și le publică, dar cifrele de ieri nu ajung la studio. "
        "Reconectează canalul din Setări, acordând accesul la statistici (yt-analytics.readonly).",
        detail=" | ".join(_slot_detail(slot) for slot in slots),
    )


def _motion_knob(environment: str) -> str:
    if environment == "PRODUCTION":
        return "plafonul de mișcare pe film (motion_budget_usd, STUDIO_MOTION_BUDGET_USD)"
    return (
        "plafonul de mișcare al unui film de test (test_max_cost_per_generation_usd × "
        "test_motion_scenes, STUDIO_TEST_MAX_COST_PER_GENERATION_USD și STUDIO_TEST_MOTION_SCENES)"
    )


def _daily_budget_films_check(
    engine: Engine, settings: Settings, environment: str, now: datetime
) -> dict[str, Any]:
    """Whether the active DAILY budget holds the day's films at the motion hold each one takes.

    The media stage reserves, before each film, `estimate_film_cost_micros` — whose motion
    part is the whole per-film ceiling of the environment (12 USD in PRODUCTION, two test
    shots at 0.60 USD in TEST) — and the hold is refused when it does not fit what the day has
    left. The same function is asked here, with no storyboard, so the figure is the stage's
    own and the narration it adds is said rather than guessed. The factual short is held
    first and the serial episode second (stages.py, `_media`), so the second film is the one
    the budget refuses. In TEST, the PRODUCTION answer is a line he reads before he switches.
    """
    daily = [b for b in budget_status(engine, now)["budgets"] if b["period"] == "DAILY"]
    with Session(engine) as session:
        serial = (
            session.scalar(
                select(ChannelRecord.id).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
            )
            is not None
        )
    films = 2 if serial else 1
    if not daily:
        return _check(
            "daily_budget_films",
            True,
            DEGRADING,
            "Niciun buget zilnic activ: nimic din buget nu refuză un film al zilei (linia "
            "bugetului spune ce înseamnă lipsa lui).",
            "",
        )
    limit = min(int(b["limit_usd_micros"]) for b in daily)

    def hold(env: str) -> int:
        return int(
            estimate_film_cost_micros(engine, "", environment=env, settings=settings)[
                "motion_usd_micros"
            ]
        )

    def refused(env: str, per_film: int) -> str:
        spare = limit - per_film
        if spare < 0:
            said = (
                f"În {environment_words(env)} fiecare film ține {format_micros(per_film)} USD "
                "pentru mișcare, peste "
                f"bugetul zilnic de {format_micros(limit)} USD. Niciun film nu încape: scurtul "
                "factual este refuzat înainte de prima scenă"
                + (", iar episodul serialului la fel." if films == 2 else ".")
            )
        else:
            said = (
                f"În {environment_words(env)} fiecare film ține {format_micros(per_film)} USD "
                f"pentru mișcare, iar bugetul zilnic este de {format_micros(limit)} USD: "
                f"{count(films, 'film', 'filme')} ar cere "
                f"{format_micros(films * per_film)} USD, deci episodul serialului, al doilea film "
                "al zilei, este refuzat de buget dacă scurtul factual a costat mai mult de "
                f"{format_micros(spare)} USD (narațiunea se adaugă la fiecare film)."
            )
        return (
            f"{said} Cele două numere pe care le poți schimba: bugetul zilnic (PUT "
            f"/economy/budget, biroul Contabilitate), la cel puțin "
            f"{format_micros(films * per_film)} USD, sau {_motion_knob(env)}, la cel mult "
            f"{format_micros(limit // films)} USD."
        )

    here = hold(environment)
    detail = (
        f"{environment_words(environment)}: {format_micros(here)} USD pe film × "
        f"{count(films, 'film', 'filme')}; zilnic {format_micros(limit)} USD"
    )
    value: dict[str, Any] = {
        "environment": environment,
        "films": films,
        "per_film_usd": format_micros(here),
        "daily_limit_usd": format_micros(limit),
    }
    if films * here > limit:
        return _check(
            "daily_budget_films",
            False,
            DEGRADING,
            "",
            refused(environment, here),
            detail=detail,
            value=value,
        )
    fits = (
        f"Bugetul zilnic de {format_micros(limit)} USD ține {count(films, 'film', 'filme')} la "
        f"plafonul de mișcare din {environment_words(environment)} ({format_micros(here)} USD "
        "pe film)."
    )
    if environment == "TEST":
        production = hold("PRODUCTION")
        detail += f"; producție: {format_micros(production)} USD pe film"
        value["production_per_film_usd"] = format_micros(production)
        if films * production > limit:
            # His answer about TEST is fine; the one about PRODUCTION is a line he reads now,
            # while switching is still a decision rather than a lost film.
            return _check(
                "daily_budget_films",
                False,
                INFORMATIONAL,
                "",
                f"Acum ești în mediul de test, iar ziua încape: {count(films, 'film', 'filme')} "
                f"la {format_micros(here)} USD pe film, în {format_micros(limit)} USD. La "
                "trecerea în producție nu mai încape. " + refused("PRODUCTION", production),
                detail=detail,
                value=value,
            )
        fits += (
            f" Și în producție ({format_micros(production)} USD pe film) "
            f"{'încape' if films == 1 else 'încap'}."
        )
    return _check("daily_budget_films", True, DEGRADING, fits, "", detail=detail, value=value)


def run_preflight(
    engine: Engine, settings: Settings, vault: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Report the studio's readiness without changing anything or calling anything.

    `now` is the moment the ages and the day's budget are read at; the clock when omitted.
    """
    moment = now or datetime.now(UTC)
    checks: list[dict[str, Any]] = []

    with Session(engine) as session:
        policy = session.get(OwnerPolicy, 1)
        stopped = bool(policy and policy.autonomy_stopped)
        checks.append(
            _check(
                "stop_autonomy",
                not stopped,
                BLOCKING,
                "Autonomia este pornită.",
                "STOP autonomie este activ; nu se pornește nicio rulare.",
            )
        )

        # Which stages the day may run at all is the Owner's mode, and the preflight is where
        # he reads the studio before it starts: a MANUAL day that films nothing should say so
        # here rather than be discovered in a run summary of skipped stages. It refuses
        # nothing by itself — the mode is his answer, not a missing capability.
        autonomy_mode = str((policy.autonomy_mode if policy else None) or "MANUAL")
        checks.append(
            _check(
                "autonomy_mode",
                True,
                INFORMATIONAL,
                MODE_MEANS.get(
                    autonomy_mode, f"Modul de autonomie este {mode_words(autonomy_mode)}."
                ),
                "",
                value=autonomy_mode,
            )
        )

        assignable = list(
            session.scalars(select(ModelRecord).where(ModelRecord.is_available.is_(True)))
        )
        checks.append(
            _check(
                "llm_provider",
                bool(assignable),
                BLOCKING,
                f"{count(len(assignable), 'model verificat', 'modele verificate')} și "
                f"{'disponibil' if len(assignable) == 1 else 'disponibile'}.",
                "Niciun model verificat. Verifică un furnizor în Setări; fără el angajații "
                "nu pot rula.",
            )
        )

        runnable_agents = list(
            session.scalars(
                select(Agent).where(
                    Agent.lifecycle == "ACTIVE",
                    Agent.provider_id.is_not(None),
                    Agent.model_id.is_not(None),
                )
            )
        )
        checks.append(
            _check(
                "agents",
                len(runnable_agents) >= 2,
                DEGRADING,
                f"{count(len(runnable_agents), 'angajat activ', 'angajați activi')} cu model "
                "alocat.",
                "Sunt necesari cel puțin doi angajați activi: verificarea afirmațiilor trebuie "
                "făcută de altcineva decât cel care le-a extras.",
                detail=f"{len(runnable_agents)} activi",
            )
        )

        youtube_connected = session.scalars(
            select(YouTubeConnection).where(YouTubeConnection.status == "CONNECTED")
        ).first()
        connected_accounts = list(
            session.scalars(
                select(YouTubeConnection).where(YouTubeConnection.status == "CONNECTED")
            )
        )

    ffmpeg = settings.ffmpeg_path or shutil.which("ffmpeg")
    checks.append(
        _check(
            "render_engine",
            bool(ffmpeg),
            BLOCKING,
            "FFmpeg disponibil.",
            "FFmpeg nu a fost găsit; randarea nu poate rula deloc.",
            detail=str(ffmpeg or ""),
        )
    )
    ffprobe = find_ffprobe(settings.ffmpeg_path)
    checks.append(
        _check(
            "media_inspection",
            bool(ffprobe),
            DEGRADING,
            "FFprobe disponibil pentru controlul calității.",
            "FFprobe lipsește; QC nu poate măsura randarea, deci va eșua întotdeauna.",
        )
    )

    # A connected account is not yet a place to publish: the channel slot has to name it, or
    # publishing and analytics cannot tell which channel a video and its numbers belong to.
    bindings = channel_bindings(engine)
    bound = [b for b in bindings.values() if b.get("publisher_ready")]
    checks.append(
        _check(
            "youtube_channel_binding",
            bool(bound),
            DEGRADING,
            # "Connected" is the stored status, not a tried token: what the grant may do and
            # whether Google refused it are the two lines that follow, and this one says so.
            f"{count(len(bound), 'slot de canal legat', 'sloturi de canal legate')} de conturi "
            "YouTube marcate conectate (starea stocată; ce poate face tokenul spun liniile "
            "despre încărcare și statistici).",
            (
                f"{count(len(connected_accounts), *CONNECTED_ACCOUNTS)}, dar niciun slot de "
                "canal nu este legat de "
                f"{'el' if len(connected_accounts) == 1 else 'vreunul'}. Leagă-le în "
                "Publicare → Sloturi de canale: publicarea și analytics folosesc legătura."
                if connected_accounts
                else "Niciun cont YouTube conectat; publicarea și analytics nu au unde citi "
                "sau scrie. Conectează un cont în Setări → Conturi și e-mail."
            ),
            detail=", ".join(
                f"{b['youtube_connection_name']} → {b['youtube_channel_title'] or '—'}"
                for b in bound
            ),
        )
    )

    # Whether the studio can find pages at all, not merely whether a host is authorised.
    # The old check passed on the existence of a row: thirty-six hosts authorised, fourteen
    # of them behind bot walls, nothing with a search address and no engine connected was a
    # READY preflight followed by a day that fetched nothing. `research_health` reads the
    # record — it probes nothing, so it is safe on every run — and names what is missing.
    report = research_health(engine, settings)
    failing = ", ".join(f"{h['host']} ({h['reason']})" for h in report["hosts_failing"])
    # The counts go in the detail, not only in the message a passing check shows: the run
    # the Owner needs them for is the one where the check failed.
    counted = (
        f"{count(report['hosts_total'], 'site autorizat', 'site-uri autorizate')}, "
        f"{report['hosts_tested_ok']} testate cu succes, {report['hosts_with_template']} cu "
        f"adresă de căutare, motor de căutare: {report['search_provider']}, "
        f"{count(report['claims_available'], 'afirmație verificată', 'afirmații verificate')} "
        f"{'disponibilă' if report['claims_available'] == 1 else 'disponibile'}."
    )
    checks.append(
        _check(
            "research_sources",
            report["status"] == "OK",
            DEGRADING,
            counted,
            " ".join(report["degraded_reasons"])
            or "Cercetarea nu poate găsi pagini; vezi Cercetare → Surse.",
            detail=counted + (f" Picate: {failing}" if failing else ""),
        )
    )

    media = describe_media(engine, vault)
    readiness = media_readiness(engine, vault)
    checks.append(
        _check(
            "image_provider",
            bool(media["image_provider"]),
            DEGRADING,
            f"Imagini: {provider_name(media['image_provider'])}.",
            readiness["image"]["message"]
            + " Până atunci randările folosesc substitute, iar QC le blochează de la publicare.",
            value=readiness["image"]["status"],
        )
    )
    checks.append(
        _check(
            "voice_provider",
            bool(media["voice_provider"]),
            DEGRADING,
            f"Voce: {provider_name(media['voice_provider'])}.",
            readiness["voice"]["message"] + " Până atunci narațiunea folosește un substitut.",
            value=readiness["voice"]["status"],
        )
    )

    # Two different things can satisfy this check, and the Owner should be told which. Saying
    # "connected by OAuth" when the credentials actually came from the server environment would
    # describe a channel nobody authorised through the interface.
    if youtube_connected is not None:
        publishing_detail = f"Canal conectat: {youtube_connected.remote_channel_title or '—'}."
        publishing_ready = (
            "Canal YouTube conectat prin OAuth (starea stocată, nu o încercare a tokenului)."
        )
    elif settings.youtube_credentials_present:
        publishing_detail = "Credențiale din mediul serverului, neverificate prin OAuth."
        publishing_ready = "Credențiale YouTube prezente în mediul serverului."
    else:
        publishing_detail = ""
        publishing_ready = "Canal YouTube conectat prin OAuth."
    checks.append(
        _check(
            "publishing",
            youtube_connected is not None or settings.youtube_credentials_present,
            DEGRADING,
            publishing_ready,
            "Niciun canal YouTube conectat; publicarea este oprită.",
            detail=publishing_detail,
        )
    )

    # What the Owner has not supplied yet. Read last, in one more session, because none of it
    # decides whether the day may start — it decides whether the day is worth having.
    checks.append(_budget_check(engine))
    checks.append(_daily_budget_films_check(engine, settings, studio_environment(engine), moment))
    with Session(engine) as session:
        # The token behind each bound slot, judged by what Google already answered.
        slots = _youtube_slots(session, moment)
        checks.append(_youtube_upload_check(slots))
        checks.append(_youtube_statistics_check(slots))
        checks.append(_price_check(session))
        checks.append(_vision_check(session))
        checks.append(_character_reference_check(session))
        checks.append(_serial_channel_check(session, bindings))

    # An informational line can never change the verdict, whatever it reports: the mode is
    # the Owner's decision about the studio, not a capability the studio is missing.
    failed = [check for check in checks if not check["ok"] and check["severity"] != INFORMATIONAL]
    blocking = [check for check in failed if check["severity"] == BLOCKING]
    status = "BLOCKED" if blocking else ("DEGRADED" if failed else "READY")
    # The first line that foresees the day stopping or losing a film. «Studioul poate rula»
    # stood above a check that foresaw exactly that on the rehearsal's copy, and the summary
    # is the sentence the run records as its stop reason, so it names the line itself.
    first_stop = next(iter(blocking), None) or next(
        (check for check in failed if check["name"] in EMPTIES_THE_DAY), None
    )
    if status == "BLOCKED":
        assert first_stop is not None  # a BLOCKED status has a blocking line
        summary = (
            "Studioul nu poate rula până nu se rezolvă punctele blocante. Primul: "
            + first_stop["message"]
        )
    elif first_stop is not None:
        summary = (
            "Ziua pornește, dar nu ajunge întreagă: " + first_stop["message"] + " Vezi lista "
            "de mai jos."
        )
    else:
        # Said plainly, because "DEGRADED" on its own invites being read as "fine for now".
        summary = {
            "READY": "Toate capabilitățile necesare sunt prezente.",
            "DEGRADED": (
                "Studioul poate rula, dar unele etape vor fi sărite sau vor produce rezultate "
                "nepublicabile. Vezi lista de mai jos."
            ),
        }[status]

    return {
        "status": status,
        "autonomy_mode": autonomy_mode,
        "checked_at": utc_now(),
        "checks": checks,
        "blocking_failures": [check["name"] for check in blocking],
        "degrading_failures": [check["name"] for check in failed if check["severity"] == DEGRADING],
        "first_stop": first_stop["name"] if first_stop else None,
        "summary": summary,
    }
