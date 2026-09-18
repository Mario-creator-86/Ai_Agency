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
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.agents.vision import vision_agent
from app.config import Settings
from app.economy.budget import budget_status
from app.economy.prices import price_for
from app.media.factory import describe as describe_media
from app.media.factory import media_readiness
from app.media.models import CharacterBible, MediaAsset
from app.media.toolchain import find_ffprobe
from app.models import OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import channel_bindings
from app.research.service import research_health
from app.services import utc_now
from app.youtube.models import YouTubeConnection

#: A check that stops the day entirely. Everything else degrades it.
BLOCKING = "BLOCKING"
DEGRADING = "DEGRADING"
#: A line that tells the Owner something about the run he is about to get and can never fail
#: it. The autonomy mode is the one such line: MANUAL is not a fault to be repaired, it is his
#: decision, and a preflight that called it DEGRADED would be asking him to fix his own answer.
#: The verdict below is computed over the other two severities only, so this holds structurally
#: and not by the check happening to pass.
INFORMATIONAL = "INFORMATIONAL"

#: What each mode means for the day about to run, in the Owner's language.
MODE_MEANS = {
    "MANUAL": (
        "Modul de autonomie este MANUAL: etapele care doar pregătesc merg singure, iar "
        "randarea plătită și publicarea rămân deciziile tale."
    ),
    "SUPERVISED": (
        "Modul de autonomie este SUPERVISED: etapele interne de rutină merg singure, iar "
        "publicarea îți cere mai întâi aprobarea."
    ),
    "AUTONOMOUS_CEO": (
        "Modul de autonomie este AUTONOMOUS_CEO: ziua merge singură în limitele politicii; "
        "porțile dure rămân la fel de închise."
    ),
}


#: The two units an agent run is costed in (`app.economy.prices.llm_cost_vr`). Both sides must
#: be priced or the cost is None, so half a price is no price here either: a run priced on one
#: side only would be read by the budget as cheaper than it was.
TOKEN_UNITS = ("per_1m_input_tokens", "per_1m_output_tokens")


def _check(
    name: str, ok: bool, severity: str, present: str, absent: str, detail: str = ""
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "severity": severity,
        "message": present if ok else absent,
        "detail": detail,
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
    named = ", ".join(f"{b['period']} {b['limit_usd']} USD ({b['state']})" for b in budgets)
    return _check(
        "spending_budget",
        bool(budgets),
        DEGRADING,
        f"{len(budgets)} bugete active: {named}.",
        "Niciun buget activ: rezervarea ține banii filmului, dar nu are de ce să îl refuze. "
        "Pune-l cu PUT /economy/budget (biroul Contabilitate); nimeni altcineva nu îl poate pune.",
        detail=named,
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
        f"{len(wanted)} modele pe care rulează angajații au preț pe jetoane.",
        f"Modele fără preț pe jetoane la: {', '.join(kinds)}. Până când îl tastezi "
        "(PUT /economy/prices, pe model sau «*» pentru tot felul), fiecare rulare a unui "
        "angajat se înregistrează fără cost, iar cărțile văd o fracțiune din zi. Studioul nu "
        "inventează un preț.",
        detail=models or f"{len(wanted)} modele, toate prețuite",
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
        f"{len(characters)} personaje cu imagine de referință citibilă."
        if characters
        else "Niciun personaj în Character Bible; nu se cere nicio referință.",
        (
            f"Personaje cu înfățișarea blocată și fără imagine de referință citibilă: {names}. "
            "Filmul lor se refuză înainte de prima scenă, în loc să li se inventeze o față. "
            "Produ setul cu POST /media/characters/{id}/reference-set (consumă credite de "
            "imagine, deci este actul tău)."
            if locked
            else f"{len(unlocked)} personaje fără imagine de referință: {names}. Fiecare imagine "
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
            "Niciun canal OFFICE_SERIAL: serialul nu are unde ajunge. Creează slotul în "
            "Publicare → Canale.",
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
            f"fiecare episod rămâne DRAFT și te așteaptă pe tine. Dreptul se dă cu "
            f"{policy_route} (director_may_approve_episodes)."
        )
    return _check(
        "serial_channel",
        bound and may_approve,
        INFORMATIONAL,
        "Serialul are canal legat, iar Directoarea poate aproba episoade.",
        absent,
        detail=f"{channel.channel_name}: legat={bound}, aprobă Directoarea={may_approve}",
    )


def run_preflight(engine: Engine, settings: Settings, vault: Any) -> dict[str, Any]:
    """Report the studio's readiness without changing anything or calling anything."""
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
                MODE_MEANS.get(autonomy_mode, f"Modul de autonomie este {autonomy_mode}."),
                "",
                detail=autonomy_mode,
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
                f"{len(assignable)} modele verificate și disponibile.",
                "Niciun model verificat. Verifică un furnizor în Settings; fără el agenții "
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
                f"{len(runnable_agents)} agenți activi cu model alocat.",
                "Sunt necesari cel puțin doi agenți activi: verificarea afirmațiilor trebuie "
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
            f"{len(bound)} sloturi de canal legate de conturi YouTube conectate.",
            (
                f"{len(connected_accounts)} conturi YouTube conectate, dar niciun slot de canal "
                "nu este legat de vreunul. Leagă-le în Publicare → Sloturi de canale: "
                "publicarea și analytics folosesc legătura."
                if connected_accounts
                else "Niciun cont YouTube conectat; publicarea și analytics nu au unde citi "
                "sau scrie. Conectează un cont în Settings → Conturi și e-mail."
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
        f"{report['hosts_total']} site-uri autorizate, {report['hosts_tested_ok']} testate cu "
        f"succes, {report['hosts_with_template']} cu adresă de căutare, motor de căutare: "
        f"{report['search_provider']}, {report['claims_available']} afirmații verificate "
        "disponibile."
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
            f"Imagini: {media['image_provider']}.",
            readiness["image"]["message"]
            + " Până atunci randările folosesc substitute, iar QC le blochează de la publicare.",
            detail=readiness["image"]["status"],
        )
    )
    checks.append(
        _check(
            "voice_provider",
            bool(media["voice_provider"]),
            DEGRADING,
            f"Voce: {media['voice_provider']}.",
            readiness["voice"]["message"] + " Până atunci narațiunea folosește un substitut.",
            detail=readiness["voice"]["status"],
        )
    )

    # Two different things can satisfy this check, and the Owner should be told which. Saying
    # "connected by OAuth" when the credentials actually came from the server environment would
    # describe a channel nobody authorised through the interface.
    if youtube_connected is not None:
        publishing_detail = f"Canal conectat: {youtube_connected.remote_channel_title or '—'}."
        publishing_ready = "Canal YouTube conectat prin OAuth."
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
    with Session(engine) as session:
        checks.append(_price_check(session))
        checks.append(_vision_check(session))
        checks.append(_character_reference_check(session))
        checks.append(_serial_channel_check(session, bindings))

    # An informational line can never change the verdict, whatever it reports: the mode is
    # the Owner's decision about the studio, not a capability the studio is missing.
    failed = [check for check in checks if not check["ok"] and check["severity"] != INFORMATIONAL]
    blocking = [check for check in failed if check["severity"] == BLOCKING]
    status = "BLOCKED" if blocking else ("DEGRADED" if failed else "READY")

    return {
        "status": status,
        "autonomy_mode": autonomy_mode,
        "checked_at": utc_now(),
        "checks": checks,
        "blocking_failures": [check["name"] for check in blocking],
        "degrading_failures": [check["name"] for check in failed if check["severity"] == DEGRADING],
        # Said plainly, because "DEGRADED" on its own invites being read as "fine for now".
        "summary": {
            "READY": "Toate capabilitățile necesare sunt prezente.",
            "DEGRADED": (
                "Studioul poate rula, dar unele etape vor fi sărite sau vor produce rezultate "
                "nepublicabile. Vezi lista de mai jos."
            ),
            "BLOCKED": "Studioul nu poate rula până nu se rezolvă punctele blocante.",
        }[status],
    }
