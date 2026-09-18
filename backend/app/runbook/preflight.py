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
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord
from app.config import Settings
from app.media.factory import describe as describe_media
from app.media.factory import media_readiness
from app.media.toolchain import find_ffprobe
from app.models import OwnerPolicy
from app.publishing.services import channel_bindings
from app.research.service import research_health
from app.services import utc_now
from app.youtube.models import YouTubeConnection

#: A check that stops the day entirely. Everything else degrades it.
BLOCKING = "BLOCKING"
DEGRADING = "DEGRADING"


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

    failed = [check for check in checks if not check["ok"]]
    blocking = [check for check in failed if check["severity"] == BLOCKING]
    status = "BLOCKED" if blocking else ("DEGRADED" if failed else "READY")

    return {
        "status": status,
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
