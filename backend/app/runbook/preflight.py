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
from app.media.factory import PURPOSE_LABEL as MEDIA_PURPOSE_LABEL
from app.media.factory import describe as describe_media
from app.media.factory import media_readiness
from app.media.models import CharacterBible, MediaAsset
from app.media.toolchain import find_ffprobe
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import bound_connection_id, channel_bindings
from app.research.service import MIN_CLAIMS_AVAILABLE, research_health
from app.services import studio_environment, utc_now
from app.wording import (
    MEDIA_KEY_UNUSABLE,
    SETTINGS_TABS,
    budget_period,
    budget_state,
    count,
    host_test_reason,
    provider_name,
    search_engine,
    youtube_scope,
)
from app.wording import autonomy_mode as mode_words
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


# ----------------------------------------------------------------- the page's places, as data
#
# W31 (2026-09-25) judged the Rularea zilei door NO: the preflight told the Owner to «PUT
# /economy/budget», to «POST /media/characters/{id}/reference-set», and named STUDIO_*
# variables and OAuth scopes in the sentences he reads. Each line now says the fix in the
# page's own places and words, and carries beside it, as data the page reads without parsing:
#
# ``code``           ``<name>.<condition>``, stable: what exactly this line found.
# ``impact``         ``blocks`` | ``degrades`` | ``informs`` | ``ok`` — what the line does to
#                    the day. ``informs`` is a failing INFORMATIONAL line: the Owner's own
#                    choice (no serial slot, a budget that fits TEST and not PRODUCTION),
#                    never counted in the verdict. ``ok`` for every passing line.
# ``place``          where the Owner fixes it, from `PLACES`; None when the line passes.
# ``place_label``    the place in the page's words, as the sentence names it.
# ``place_section``  the element of `frontend/index.html` the fix sits in, or None.
# ``technical``      {routes, settings, scopes, fields, answers, paths}: the API routes, the
#                    ``STUDIO_*`` settings, the OAuth scopes, the record's field names, the
#                    vendor's raw answers and the files on the studio's computer that used to
#                    be in the sentence — for a tooltip. Always all six keys, each a list.

#: Where a fix is made. The doors are the masthead's rooms (`open-<id>-btn` in index.html,
#: their `room-label` as the name); the settings tabs are `settings.js`'s sections, named as
#: `app.wording.SETTINGS_TABS` names them; the switch is the dock's AUTONOMIE; ``machine`` is
#: the computer the studio runs on (nothing on the page installs FFmpeg); ``not_on_page`` is a
#: fix the studio's API accepts and the page has no control for yet — said so in the sentence,
#: never dressed as a place.
#:
#: A part of a door is not a place of its own: it is the door's id with a ``place_section``
#: (the element's id in index.html) and the words for it — the tuples below. So the treasury's
#: price form is ``treasury`` + ``tr-prices``, as its budget is ``treasury`` + ``tr-budget``,
#: and a page that knows the door already opens it at the section.
#:
#: W34 gave two lines their places. The Director's leave to approve episodes
#: (``serial_channel.director_may_not_approve``) is the switch in ``settings:channels``,
#: «Setări → Canale»; the token prices (``model_prices.unpriced``) are the form in
#: `PRICES_PLACE`, «Trezorerie → Prețurile modelelor». Only the serial's missing slot
#: (``serial_channel.missing``, `POST /publishing/channels/seed`) is still ``not_on_page``.
PLACES: dict[str, str] = {
    "research": "Cercetare",
    "media": "Producție media",
    "publishing": "Distribuție",
    "workforce": "Angajați",
    "story": "Jurnal",
    "runbook": "Rularea zilei",
    "treasury": "Trezorerie",
    **{f"settings:{tab}": label for tab, label in SETTINGS_TABS.items()},
    "autonomy_switch": "comutatorul AUTONOMIE",
    "machine": "calculatorul studioului",
    "not_on_page": "API-ul studioului",
}

IMPACTS = ("blocks", "degrades", "informs", "ok")
TECHNICAL_KEYS = ("routes", "settings", "scopes", "fields", "answers", "paths")

_IMPACT = {"BLOCKING": "blocks", "DEGRADING": "degrades", "INFORMATIONAL": "informs"}

#: The places with a section, and the words the sentences use for them.
BUDGET_PLACE = ("treasury", "tr-budget", "Trezorerie → Buget și cheltuieli")
SOURCES_PLACE = ("research", "rs-sources", "Cercetare → Surse și afirmații")
CHARACTERS_PLACE = ("media", "media-characters-section", "Producție media → Character Bible")
SLOTS_PLACE = ("publishing", "channels-list", "Distribuție → Sloturi de canal")
PRICES_PLACE = ("treasury", "tr-prices", "Trezorerie → Prețurile modelelor")

#: The routes and settings the sentences used to name, now said in ``technical`` only.
BUDGET_ROUTE = "PUT /economy/budget"
PRICES_ROUTE = "PUT /economy/prices"
SEED_CHANNELS_ROUTE = "POST /publishing/channels/seed"
FFMPEG_SETTING = "STUDIO_FFMPEG_PATH"
FFPROBE_SETTING = "STUDIO_FFPROBE_PATH"


def _usd(micros: int) -> str:
    """An amount in a sentence, as Romanian writes it: «1,2 USD», «7,5 USD». The line's
    ``value`` keeps the plain decimal (`format_micros`) for whoever reads it as a number."""
    return format_micros(micros).replace(".", ",")


def _technical(
    routes: list[str] | None = None,
    settings: list[str] | None = None,
    scopes: list[str] | None = None,
    fields: list[str] | None = None,
    answers: list[str] | None = None,
    paths: list[str] | None = None,
) -> dict[str, list[str]]:
    return {
        "routes": list(routes or []),
        "settings": list(settings or []),
        "scopes": list(scopes or []),
        "fields": list(fields or []),
        "answers": list(answers or []),
        "paths": list(paths or []),
    }


def _check(
    name: str,
    ok: bool,
    severity: str,
    present: str,
    absent: str,
    detail: str = "",
    value: Any = None,
    *,
    passed: str = "ok",
    failed: str = "missing",
    place: str | tuple[str, str | None, str] | None = None,
    technical: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """One line of the preflight. ``message`` and ``detail`` are what the Owner reads (the
    page prints them side by side), so both are Romanian with the codes said as words and
    the fix said as a place on the page; ``value`` is the same fact as data — the mode, the
    budget's period and state, the environment — for a page or a test that needs the code
    itself. ``passed``/``failed`` name the condition in ``code``; ``place`` is a `PLACES` id
    or (id, section, words); ``technical`` what the sentence no longer says."""
    where: str | None = None
    section: str | None = None
    if isinstance(place, tuple):
        place, section, where = place
    if place is not None:
        assert place in PLACES, place
        where = where or PLACES[place]
    return {
        "name": name,
        "ok": ok,
        "severity": severity,
        "message": present if ok else absent,
        "detail": detail,
        "value": value,
        "code": f"{name}.{passed if ok else failed}",
        "impact": "ok" if ok else _IMPACT[severity],
        "place": None if ok else place,
        "place_label": None if ok else where,
        "place_section": None if ok else section,
        "technical": technical or _technical(),
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
        f"{budget_period(b['period'])} {str(b['limit_usd']).replace('.', ',')} USD "
        f"({budget_state(b['state'])})"
        for b in budgets
    )
    return _check(
        "spending_budget",
        bool(budgets),
        DEGRADING,
        f"{count(len(budgets), 'buget activ', 'bugete active')}: {said}.",
        "Niciun buget activ: rezervarea ține banii filmului, dar nu are de ce să îl refuze. "
        f"Setează bugetul zilnic în {BUDGET_PLACE[2]}; nimeni altcineva nu îl poate pune.",
        value=[
            {"period": b["period"], "limit_usd": b["limit_usd"], "state": b["state"]}
            for b in budgets
        ],
        passed="set",
        failed="none",
        place=BUDGET_PLACE,
        technical=_technical(routes=[BUDGET_ROUTE]),
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
    # What the price form reads: each model still unpriced, and which of its two token prices
    # it lacks, in the order the form lists them. The kind is the table's key, lower case.
    value = {
        "models": len(wanted),
        "unpriced": [
            {
                "provider_kind": kind,
                "resource": model,
                "missing_units": [
                    unit for unit in TOKEN_UNITS if price_for(session, kind, model, unit) is None
                ],
            }
            for kind, model in sorted(unpriced)
        ],
    }
    if not wanted:
        # Nothing runs, so nothing is unpriced. The `agents` check above is where a studio
        # with no runnable employee is reported; saying it twice would read as two faults.
        return _check(
            "model_prices",
            True,
            DEGRADING,
            "Niciun angajat cu model alocat, deci nu este nimic de prețuit.",
            "",
            value=value,
            passed="nothing_runs",
        )
    return _check(
        "model_prices",
        not unpriced,
        DEGRADING,
        f"{count(len(wanted), 'model', 'modele')} pe care rulează angajații "
        f"{'are' if len(wanted) == 1 else 'au'} preț pe tokenuri.",
        f"Modele fără preț pe tokenuri la: {', '.join(kinds)}. Până când le pui un preț, "
        "fiecare rulare a unui angajat se înregistrează fără cost, iar cărțile văd o fracțiune "
        f"din zi. Studioul nu inventează un preț: pune-l tu în {PRICES_PLACE[2]}.",
        detail=models or f"{count(len(wanted), 'model prețuit', 'modele, toate prețuite')}",
        value=value,
        failed="unpriced",
        place=PRICES_PLACE,
        technical=_technical(
            routes=[PRICES_ROUTE],
            fields=["provider_kind", "resource (un model sau «*» pentru tot felul)", *TOKEN_UNITS],
        ),
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
        f"trece toate verificările automate. Alocă un model cu vedere unui angajat în "
        f"{PLACES['settings:agents']}.",
        value={"agent_id": seer[0], "agent_name": seer[1]} if seer else None,
        failed="nobody_sees",
        place="settings:agents",
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
    # The button on each character's card, and the route it calls, one per character named.
    button = f"cu «Produ setul de referință» din {CHARACTERS_PLACE[2]}"
    routes = [f"POST /media/characters/{c.id}/reference-set" for c in (locked or unlocked)]
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
            f"Produ setul {button} (consumă credite de imagine, deci este actul tău)."
            if locked
            else f"{count(len(unlocked), 'personaj', 'personaje')} fără imagine de referință: "
            f"{names}. Fiecare imagine "
            "a lor este o invenție nouă, iar verificarea personajelor nu are cu ce compara. "
            f"Setul se produce {button}."
        ),
        detail=names,
        passed="ok" if characters else "no_characters",
        failed="locked_missing" if locked else "unlocked_missing",
        place=CHARACTERS_PLACE,
        technical=_technical(routes=routes),
    )


def _serial_channel_check(session: Session, bindings: dict[str, dict]) -> dict[str, Any]:
    """Whether the serial has a channel to reach, and whether the Director may approve episodes.

    Both halves are his. A studio with no OFFICE_SERIAL row makes no serial, and a Director
    without the leave leaves every episode DRAFT waiting for his hand — which is his right,
    and is not autonomy. So the line says which of the two is missing and where he fixes it
    (the slot in Distribuție, the leave in Setări → Canale), and it never fails the day.
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
            "Niciun slot de canal pentru Office Serial: serialul nu are unde ajunge. Sloturile "
            "de canal se creează deocamdată doar prin API-ul studioului: pagina nu are încă un "
            "buton pentru ele.",
            value={"channel_type": "OFFICE_SERIAL", "exists": False},
            failed="missing",
            place="not_on_page",
            technical=_technical(routes=[SEED_CHANNELS_ROUTE]),
        )
    bound = bool(bindings.get(channel.id, {}).get("publisher_ready"))
    may_approve = bool(channel.director_may_approve_episodes)
    policy_route = f"POST /publishing/channels/{channel.id}/publish-policy"
    fix: tuple[str, str | None, str] | str
    if not bound:
        absent = (
            f"Canalul serialului ({channel.channel_name}) nu este legat de un cont YouTube "
            "conectat: episoadele se produc, dar nu au unde urca. Leagă-l în "
            f"{SLOTS_PLACE[2]}."
        )
        failed, fix = "unbound", SLOTS_PLACE
        technical = _technical()
    else:
        absent = (
            "Canalul serialului este legat, dar Directoarea nu are dreptul să aprobe episoade: "
            "fiecare episod rămâne ciornă și te așteaptă pe tine. Dreptul i-l dai în "
            f"{PLACES['settings:channels']}."
        )
        failed, fix = "director_may_not_approve", "settings:channels"
        technical = _technical(routes=[policy_route], fields=["director_may_approve_episodes"])
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
            # What the switch writes with: the channel, and the policy version it replaces.
            "channel_id": channel.id,
            "policy_version": int(channel.policy_version or 1),
        },
        failed=failed,
        place=fix,
        technical=technical,
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
                "granted_on": f"{granted_at:%d.%m.%Y}" if granted_at else None,
                # Said in words with the moment; Google's own answer («400 invalid_grant»)
                # is the line's technical record, not the Owner's sentence.
                "token_refusal": (
                    f"Google a refuzat tokenul pe {token_at:%d.%m.%Y, %H:%M} UTC"
                    if token is not None and token_at is not None
                    else ""
                ),
                "token_answer": _answer(token) if token is not None else "",
                "report_refusal": (
                    f"Google a refuzat citirea statisticilor pe {report_at:%d.%m.%Y, %H:%M} UTC"
                    if report is not None and report_at is not None
                    else ""
                ),
                "report_answer": _answer(report) if report is not None else "",
                "silence": (
                    f"{silent_at:%d.%m.%Y, %H:%M} UTC, fără răspuns de la Google (rețea); nu "
                    "spune nimic despre token"
                    if silence is not None and silent_at is not None
                    else ""
                ),
            }
        )
    return slots


def _answers(slots: list[dict[str, Any]], *keys: str) -> list[str]:
    """Google's raw answers, per slot, for the line's technical record."""
    return [f"{slot['label']}: {slot[key]}" for slot in slots for key in keys if slot.get(key)]


def _scopes_said(scopes: set[str] | frozenset[str] | list[str]) -> str:
    """The grants as what they let the studio do: «citirea canalului, încărcarea filmelor»."""
    return ", ".join(sorted(youtube_scope(scope_label(scope)) for scope in scopes))


def _slot_detail(slot: dict[str, Any]) -> str:
    scopes = slot["scopes"]
    granted = (
        _scopes_said(scopes) if scopes is not None else "necunoscute (neînregistrate la conectare)"
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
        f"{slot['channel']} → {slot['account']}: drepturi: {granted}; {age}; "
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


#: Where a grant is renewed: the reconnect button on the account's card.
ACCOUNTS_PLACE = "settings:social"


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
            passed="no_slots",
        )
    problems = []
    failed = ""
    for slot in slots:
        if slot["scopes"] is not None and UPLOAD_SCOPE not in slot["scopes"]:
            problems.append(f"{slot['label']}: Google nu a acordat dreptul de încărcare")
            failed = failed or "upload_not_granted"
        elif slot["token_refusal"]:
            problems.append(f"{slot['label']}: {slot['token_refusal']}")
            failed = failed or "token_refused"
    caveat = _grant_age_caveat(slots)
    return _check(
        "youtube_upload_access",
        not problems,
        BLOCKING,
        f"{count(len(slots), 'slot legat', 'sloturi legate')}: "
        f"{'nu arată' if len(slots) == 1 else 'niciunul nu arată'} dreptul de încărcare lipsă "
        f"sau un refuz al tokenului după acordare. {caveat}",
        f"Filmele nu pot urca pe YouTube: {'; '.join(problems)}. Reconectează canalul din "
        f"{PLACES[ACCOUNTS_PLACE]} și acordă dreptul de încărcare. " + caveat,
        detail=" | ".join(_slot_detail(slot) for slot in slots),
        failed=failed or "missing",
        place=ACCOUNTS_PLACE,
        technical=_technical(
            scopes=[scope_label(UPLOAD_SCOPE)],
            answers=_answers(slots, "token_answer"),
        ),
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
            passed="no_slots",
        )
    problems = []
    failed = ""
    for slot in slots:
        if slot["token_refusal"] or slot["report_refusal"]:
            refusal = slot["token_refusal"] or slot["report_refusal"]
            problems.append(f"{slot['label']}: {refusal}")
            failed = failed or ("token_refused" if slot["token_refusal"] else "report_refused")
        elif slot["scopes"] is not None and STATISTICS_SCOPE not in slot["scopes"]:
            granted = _scopes_said(slot["scopes"]) or "nimic"
            problems.append(f"{slot['label']}: Google a acordat doar {granted}, fără statistici")
            failed = failed or "statistics_not_granted"
    return _check(
        "youtube_statistics_access",
        not problems,
        DEGRADING,
        f"{count(len(slots), 'slot legat', 'sloturi legate')}: "
        f"{'nu arată' if len(slots) == 1 else 'niciunul nu arată'} lipsa accesului la "
        "statistici sau un refuz al tokenului după acordare.",
        f"Statisticile YouTube nu pot fi citite pentru {'; '.join(problems)}. Filmele nu depind "
        "de ele: ziua le face și le publică, dar cifrele de ieri nu ajung la studio. "
        f"Reconectează canalul din {PLACES[ACCOUNTS_PLACE]}, acordând accesul la statistici.",
        detail=" | ".join(_slot_detail(slot) for slot in slots),
        failed=failed or "missing",
        place=ACCOUNTS_PLACE,
        technical=_technical(
            scopes=[scope_label(STATISTICS_SCOPE)],
            answers=_answers(slots, "token_answer", "report_answer"),
        ),
    )


def _motion_knob(environment: str) -> tuple[str, list[str], list[str]]:
    """The per-film motion ceiling in words, and the settings and fields that hold it.

    Nothing on the page changes it: it is the studio's configuration on its computer, and
    the sentence says so; the names are the line's technical record.
    """
    if environment == "PRODUCTION":
        return (
            "plafonul de mișcare pe film (în configurația studioului, nu din pagină)",
            ["STUDIO_MOTION_BUDGET_USD"],
            ["motion_budget_usd"],
        )
    return (
        "plafonul de mișcare al unui film de test (în configurația studioului, nu din pagină)",
        ["STUDIO_TEST_MAX_COST_PER_GENERATION_USD", "STUDIO_TEST_MOTION_SCENES"],
        ["test_max_cost_per_generation_usd", "test_motion_scenes"],
    )


def _budget_films_technical(environment: str) -> dict[str, list[str]]:
    _, knob_settings, knob_fields = _motion_knob(environment)
    return _technical(routes=[BUDGET_ROUTE], settings=knob_settings, fields=knob_fields)


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
            passed="no_daily_budget",
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
                f"În {environment_words(env)} fiecare film ține {_usd(per_film)} USD "
                "pentru mișcare, peste "
                f"bugetul zilnic de {_usd(limit)} USD. Niciun film nu încape: scurtul "
                "factual este refuzat înainte de prima scenă"
                + (", iar episodul serialului la fel." if films == 2 else ".")
            )
        else:
            said = (
                f"În {environment_words(env)} fiecare film ține {_usd(per_film)} USD "
                f"pentru mișcare, iar bugetul zilnic este de {_usd(limit)} USD: "
                f"{count(films, 'film', 'filme')} ar cere "
                f"{_usd(films * per_film)} USD, deci episodul serialului, al doilea film "
                "al zilei, este refuzat de buget dacă scurtul factual a costat mai mult de "
                f"{_usd(spare)} USD (narațiunea se adaugă la fiecare film)."
            )
        return (
            f"{said} Cele două numere pe care le poți schimba: bugetul zilnic, în "
            f"{BUDGET_PLACE[2]}, la cel puțin {_usd(films * per_film)} USD, sau "
            f"{_motion_knob(env)[0]}, la cel mult {_usd(limit // films)} USD."
        )

    def refusal(per_film: int) -> str:
        return "no_film_fits" if limit < per_film else "second_film_refused"

    here = hold(environment)
    detail = (
        f"{environment_words(environment)}: {_usd(here)} USD pe film × "
        f"{count(films, 'film', 'filme')}; zilnic {_usd(limit)} USD"
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
            failed=refusal(here),
            place=BUDGET_PLACE,
            technical=_budget_films_technical(environment),
        )
    fits = (
        f"Bugetul zilnic de {_usd(limit)} USD ține {count(films, 'film', 'filme')} la "
        f"plafonul de mișcare din {environment_words(environment)} ({_usd(here)} USD "
        "pe film)."
    )
    if environment == "TEST":
        production = hold("PRODUCTION")
        detail += f"; producție: {_usd(production)} USD pe film"
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
                f"la {_usd(here)} USD pe film, în {_usd(limit)} USD. La "
                "trecerea în producție nu mai încape. " + refused("PRODUCTION", production),
                detail=detail,
                value=value,
                failed="production_would_refuse",
                place=BUDGET_PLACE,
                technical=_budget_films_technical("PRODUCTION"),
            )
        fits += (
            f" Și în producție ({_usd(production)} USD pe film) "
            f"{'încape' if films == 1 else 'încap'}."
        )
    return _check(
        "daily_budget_films", True, DEGRADING, fits, "", detail=detail, value=value, passed="fits"
    )


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
                "Autonomia studioului este oprită: nu pornește nicio rulare până nu o repornești "
                "de la comutatorul AUTONOMIE.",
                passed="on",
                failed="stopped",
                place="autonomy_switch",
                technical=_technical(fields=["autonomy_stopped"]),
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
                passed=autonomy_mode.lower(),
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
                "Niciun model verificat: fără el angajații nu pot rula. Verifică un furnizor în "
                f"{PLACES['settings:llm']}.",
                failed="no_verified_model",
                place="settings:llm",
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
                "făcută de altcineva decât cel care le-a extras. Alocă un model încă unui angajat "
                f"în {PLACES['settings:agents']}.",
                detail=f"{count(len(runnable_agents), 'activ', 'activi')}",
                failed="too_few",
                place="settings:agents",
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
            "FFmpeg nu a fost găsit pe calculatorul studioului: randarea nu poate rula deloc. "
            "Se instalează pe calculator, nu din pagină.",
            failed="ffmpeg_missing",
            place="machine",
            # Where it was found is a file on his computer: the tooltip's, not the sentence's.
            technical=_technical(settings=[FFMPEG_SETTING], paths=[str(ffmpeg)] if ffmpeg else []),
        )
    )
    ffprobe = find_ffprobe(settings.ffmpeg_path)
    checks.append(
        _check(
            "media_inspection",
            bool(ffprobe),
            DEGRADING,
            "FFprobe disponibil pentru controlul calității.",
            "FFprobe lipsește de pe calculatorul studioului: controlul calității nu poate măsura "
            "randarea, deci va eșua întotdeauna. Se instalează pe calculator, lângă FFmpeg.",
            failed="ffprobe_missing",
            place="machine",
            technical=_technical(
                settings=[FFPROBE_SETTING], paths=[str(ffprobe)] if ffprobe else []
            ),
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
                f"{SLOTS_PLACE[2]}: publicarea și statisticile folosesc legătura."
                if connected_accounts
                else "Niciun cont YouTube conectat: publicarea și statisticile nu au unde citi "
                f"sau scrie. Conectează un cont în {PLACES['settings:social']}."
            ),
            detail=", ".join(
                f"{b['youtube_connection_name']} → {b['youtube_channel_title'] or '—'}"
                for b in bound
            ),
            failed="unbound" if connected_accounts else "no_account",
            place=SLOTS_PLACE if connected_accounts else "settings:social",
        )
    )

    # Whether the studio can find pages at all, not merely whether a host is authorised.
    # The old check passed on the existence of a row: thirty-six hosts authorised, fourteen
    # of them behind bot walls, nothing with a search address and no engine connected was a
    # READY preflight followed by a day that fetched nothing. `research_health` reads the
    # record — it probes nothing, so it is safe on every run — and names what is missing.
    report = research_health(engine, settings)
    # Each failing site with why, in the sources list's words; the codes stay in `value`.
    failing = "; ".join(
        f"{h['host']} — {host_test_reason(h['reason'])}" for h in report["hosts_failing"]
    )
    # The counts go in the detail, not only in the message a passing check shows: the run
    # the Owner needs them for is the one where the check failed.
    counted = (
        f"{count(report['hosts_total'], 'site autorizat', 'site-uri autorizate')}, "
        f"{report['hosts_tested_ok']} testate cu succes, {report['hosts_with_template']} cu "
        f"adresă de căutare, {search_engine(report['search_provider'])}, "
        f"{count(report['claims_available'], 'afirmație verificată', 'afirmații verificate')} "
        f"{'disponibilă' if report['claims_available'] == 1 else 'disponibile'}."
    )
    # The same four conditions `research_health` words its reasons from, as codes: the
    # first that holds is the line's code, all that hold are in its value.
    research_codes = [
        code
        for code, holds in (
            ("no_hosts", report["hosts_total"] == 0),
            ("none_passed", report["hosts_total"] > 0 and report["hosts_tested_ok"] == 0),
            (
                "cannot_find_pages",
                report["hosts_with_template"] == 0 and report["search_provider"] == "NONE",
            ),
            ("few_claims", report["claims_available"] < MIN_CLAIMS_AVAILABLE),
        )
        if holds
    ]
    checks.append(
        _check(
            "research_sources",
            report["status"] == "OK",
            DEGRADING,
            counted,
            " ".join(report["degraded_reasons"])
            + f" Site-urile, testul lor și adresele de căutare sunt în {SOURCES_PLACE[2]}.",
            detail=counted + (f" Nu pot fi citite: {failing}." if failing else ""),
            value={
                "status": report["status"],
                "search_provider": report["search_provider"],
                "hosts_failing": [
                    {"host": h["host"], "reason": h["reason"]} for h in report["hosts_failing"]
                ],
                "reason_codes": research_codes,
            },
            failed=(research_codes or ["degraded"])[0],
            place=SOURCES_PLACE,
            technical=_technical(
                answers=[f"{h['host']}: {h['reason']}" for h in report["hosts_failing"]]
            ),
        )
    )

    media = describe_media(engine, vault)
    readiness = media_readiness(engine, vault)

    def _media_missing(purpose: str) -> str:
        """Why no generator, in words: readiness's own sentence, or, when readiness calls the
        choice ready and still no adapter came of it, the key that cannot be used."""
        state = readiness[purpose]
        if state["message"]:
            return state["message"]
        return MEDIA_KEY_UNUSABLE.format(
            name=state.get("connection") or "Conexiunea aleasă",
            purpose=MEDIA_PURPOSE_LABEL[purpose],
        )

    def _media_code(purpose: str) -> str:
        """Readiness's own status as the condition; READY with no generator is a bad key."""
        status = str(readiness[purpose]["status"] or "")
        return "key_unusable" if status == "READY" else status.lower() or "missing"

    checks.append(
        _check(
            "image_provider",
            bool(media["image_provider"]),
            DEGRADING,
            f"Imagini: {provider_name(media['image_provider'])}.",
            _media_missing("image")
            + " Până atunci randările folosesc substitute, iar QC le blochează de la publicare.",
            value=readiness["image"]["status"],
            passed="ready",
            failed=_media_code("image"),
            place="settings:media",
        )
    )
    checks.append(
        _check(
            "voice_provider",
            bool(media["voice_provider"]),
            DEGRADING,
            f"Voce: {provider_name(media['voice_provider'])}.",
            _media_missing("voice") + " Până atunci narațiunea folosește un substitut.",
            value=readiness["voice"]["status"],
            passed="ready",
            failed=_media_code("voice"),
            place="settings:media",
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
        publishing_how = "oauth"
    elif settings.youtube_credentials_present:
        publishing_detail = "Credențiale din mediul serverului, neverificate prin OAuth."
        publishing_ready = "Credențiale YouTube prezente în mediul serverului."
        publishing_how = "server_credentials"
    else:
        publishing_detail = ""
        publishing_ready = "Canal YouTube conectat prin OAuth."
        publishing_how = "oauth"
    checks.append(
        _check(
            "publishing",
            youtube_connected is not None or settings.youtube_credentials_present,
            DEGRADING,
            publishing_ready,
            "Niciun canal YouTube conectat: publicarea este oprită. Conectează un cont în "
            f"{PLACES['settings:social']}.",
            detail=publishing_detail,
            passed=publishing_how,
            failed="none",
            place="settings:social",
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
