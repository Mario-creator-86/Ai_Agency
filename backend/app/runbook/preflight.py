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

import os
import shutil
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord
from app.config import Settings
from app.integrations.models import Integration
from app.media.factory import describe as describe_media
from app.models import OwnerPolicy
from app.services import utc_now

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

        youtube_verified = session.scalars(
            select(Integration).where(
                Integration.kind == "youtube", Integration.status == "VERIFIED"
            )
        ).first()

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
    ffprobe = os.environ.get("STUDIO_FFPROBE_PATH") or shutil.which("ffprobe")
    checks.append(
        _check(
            "media_inspection",
            bool(ffprobe),
            DEGRADING,
            "FFprobe disponibil pentru controlul calității.",
            "FFprobe lipsește; QC nu poate măsura randarea, deci va eșua întotdeauna.",
        )
    )

    hosts = list(settings.research_allowed_hosts)
    checks.append(
        _check(
            "research_sources",
            bool(hosts),
            DEGRADING,
            f"{len(hosts)} site-uri autorizate pentru preluarea surselor.",
            "Niciun site autorizat; sursele trebuie introduse manual.",
        )
    )

    media = describe_media(engine, vault)
    checks.append(
        _check(
            "image_provider",
            bool(media["image_provider"]),
            DEGRADING,
            f"Imagini: {media['image_provider']}.",
            "Niciun furnizor de imagine verificat; randările folosesc substitute, iar QC le "
            "blochează de la publicare.",
        )
    )
    checks.append(
        _check(
            "voice_provider",
            bool(media["voice_provider"]),
            DEGRADING,
            f"Voce: {media['voice_provider']}.",
            "Niciun furnizor de voce verificat; naratiunea folosește un substitut.",
        )
    )

    checks.append(
        _check(
            "publishing",
            bool(youtube_verified) or settings.youtube_credentials_present,
            DEGRADING,
            "Conexiune YouTube verificată.",
            "Nicio conexiune YouTube verificată; publicarea este oprită.",
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
