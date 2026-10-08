"""The audit's open questions to the Owner, as cards (2026-10-03).

The production audit of 2026-10-02 (ac07033) left decisions only he can take: the daily
budget, reconnecting Ollama Cloud and both YouTube channels, Google's consent screen and the
YouTube API audit, commercial use on Runway and ElevenLabs, the music library, narration as a
paid step, when to leave EVERY_PAID_STEP, editorial QC advisory or blocking, the old test
films, the sale terms. `seed_owner_decisions` puts each in his window, once.

"Once" is literal: a key that has EVER had a card (in any state) is never seeded again, so a
card he refused does not come back at the next start. One exception (2026-10-04): a guided card
that his «Am făcut-o» closed while its condition was unmet (before that day DONE did not read
the condition) is re-opened once, on its own row, by `reopen_unconfirmed_done`; his refusals
and his «keep it as it is» answers are never re-opened. The reconnect, YouTube, commercial-use
and music cards use the keys and the shapes of the studio's own producers
(`app.decisions.sources`), so a question the audit and a failing run both see is one card.
Each card is proposed only when the studio's own state says the question stands (a connection
that works gets no reconnect card), with the recommended option first. The budget card's
figure is computed from the studio's numbers, never a constant: his active daily budget
against the cheapest capable film on his catalogue (`cheapest_capable_film`).

Read only outside the card table: nothing under the media folder is moved or deleted, no
provider is called, nothing is bought. A proposal writes no ledger event.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.decisions.models import OwnerDecision
from app.decisions.services import (
    media_folder_count,
    propose_owner_decision,
    reopen_unconfirmed_done,
)
from app.decisions.sources import (
    commercial_use_card,
    music_card,
    reconnect_card,
    runpod_infra_card,
    runpod_ltx_licence_card,
    youtube_card,
)
from app.wording import count, decimal

logger = logging.getLogger("studio.decisions")

SOURCE = "audit"

#: The film the budget is measured against: four filmed scenes of ten seconds with people in
#: every one, the hook at the HERO tier. The shape of the studio's short (the audit's
#: "four-scene film of 10 s scenes"); the models and the prices are his catalogue's.
REFERENCE_SCENES = 4
REFERENCE_SCENE_SECONDS = 10.0
#: The budget is recommended in whole steps of this many dollars, rounded up.
BUDGET_STEP_USD = 5

#: From this many folders in the media root the old test films are worth his decision.
OLD_FILMS_THRESHOLD = 100
#: Files read for the size of the media root at most; past it the size is "at least".
SIZE_SCAN_LIMIT = 200_000

#: The files that would hold the sale terms at the project's root.
LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "EULA.md", "EULA.txt")


def _usd(micros: int) -> str:
    """A sum as he reads it: «15», «27,92»."""
    text = decimal(micros / 1_000_000, 2)
    return text[:-3] if text.endswith(",00") else text


def _documented_capabilities() -> list[Any]:
    """The motion models of his documented catalogue (config/film_models.json), for a studio
    whose Runway connection lists none yet."""
    from app.media.production_policy import ModelCapability, load_film_models  # noqa: PLC0415

    catalogue = load_film_models()
    found = []
    for model_id, entry in catalogue.models.items():
        moves = entry.get("camera_moves")
        seconds = entry.get("seconds")
        found.append(
            ModelCapability(
                model_id=str(model_id),
                quality=float(entry.get("quality_score") or 0.5),
                seconds=dict(seconds) if isinstance(seconds, Mapping) else None,
                need_quality={
                    str(k): float(v) for k, v in dict(entry.get("need_quality") or {}).items()
                },
                camera_moves=tuple(str(m) for m in moves) if isinstance(moves, list) else None,
                quality_source="documentat",
                owner_allowed=catalogue.allows(str(model_id)),
            )
        )
    return found


def cheapest_capable_film(engine: Engine) -> dict[str, Any] | None:
    """What the cheapest film the planner would buy costs, on the Owner's own catalogue.

    The reference film (`REFERENCE_SCENES` × `REFERENCE_SCENE_SECONDS`, people in every scene,
    the hook HERO) is planned scene by scene by `production_policy.plan_scene_models` on the
    capabilities of his Runway connection (its documented catalogue when the connection lists
    none) and the published price table. A scene no allowed model reaches is priced at the
    best model available for it, as the sheet would offer him. Returns the expected cost, the
    cap the reservation holds (one redo of the dearest shot and one more round of stills on
    top), the models; None when the catalogue cannot price it (never a guess).
    """
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.media import cost_plan  # noqa: PLC0415
    from app.media.production_policy import (  # noqa: PLC0415
        SceneNeed,
        plan_scene_models,
        scene_model_capabilities,
    )

    try:
        with Session(engine) as session:
            runway = session.scalars(
                select(Integration).where(Integration.kind == "runway").order_by(Integration.id)
            ).first()
            capabilities = scene_model_capabilities(session, runway.id) if runway else []
        source_ro = "conexiunea ta Runway"
        if not capabilities:
            capabilities = _documented_capabilities()
            source_ro = "catalogul documentat (config/film_models.json)"
        table = cost_plan.load_price_table()
        needs = [
            SceneNeed(
                scene_index=index,
                tier="HERO" if index == 1 else "STANDARD",
                seconds=REFERENCE_SCENE_SECONDS,
                people=True,
            )
            for index in range(1, REFERENCE_SCENES + 1)
        ]
        plan = plan_scene_models(needs, capabilities, table=table)
    except Exception as exc:  # noqa: BLE001 - an unpriceable film gets no card, never a guess
        logger.warning("cheapest_film_unpriced", exc_info=exc)
        return None
    motion: list[int] = []
    models: list[str] = []
    for scene in plan["scenes"]:
        if scene.get("status") in ("PLANNED", "BOUGHT"):
            motion.append(int(scene["credits"]))
            models.append(str(scene["model_id"]))
        elif isinstance(scene.get("best_available"), dict):
            motion.append(int(scene["best_available"]["credits"]))
            models.append(str(scene["best_available"]["model_id"]))
        else:
            return None
    stills = int(plan["stills_credits"])
    total = stills + sum(motion)
    cap = total + max(motion, default=0) + stills

    def usd(credits: int) -> int:
        return cost_plan.credits_to_micros(credits, table.credit_usd)

    return {
        "scenes": REFERENCE_SCENES,
        "seconds": REFERENCE_SCENE_SECONDS,
        "models": sorted(set(models)),
        "total_credits": total,
        "cap_credits": cap,
        "stills_usd_micros": usd(stills),
        "total_usd_micros": usd(total),
        "cap_usd_micros": usd(cap),
        "source_ro": source_ro,
    }


# ------------------------------------------------------------------------------ the cards


def _budget_cards(session: Session, engine: Engine) -> list[dict[str, Any]]:
    from app.economy.budget import budget_version  # noqa: PLC0415
    from app.economy.models import SpendingBudget  # noqa: PLC0415

    film = cheapest_capable_film(engine)
    if film is None:
        return []
    daily = session.scalar(
        select(SpendingBudget.limit_usd_micros).where(
            SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True)
        )
    )
    need = int(film["cap_usd_micros"])
    if daily is not None and int(daily) >= need:
        return []
    recommended = math.ceil(need / (BUDGET_STEP_USD * 1_000_000)) * BUDGET_STEP_USD
    now_ro = (
        f"Bugetul zilnic activ este de {_usd(int(daily))} USD."
        if daily is not None
        else "Nu există un buget zilnic activ; în producție, fără buget nu se cumpără nimic."
    )
    models = ", ".join(film["models"])
    why = (
        f"{now_ro} Cel mai ieftin film capabil din {film['source_ro']} — "
        f"{count(film['scenes'], 'scenă', 'scene')} de câte {int(film['seconds'])} s, cu "
        f"oameni, cu {models} — costă aproximativ {_usd(film['total_usd_micros'])} USD, iar "
        f"rezervarea lui ține plafonul de {_usd(need)} USD (o refacere a celei mai scumpe "
        "scene și încă un rând de imagini). "
        + (
            "Cu bugetul de azi filmul nu încape într-o zi."
            if daily is not None
            else "Un buget zilnic de această mărime îl lasă să încapă într-o zi."
        )
    )
    return [
        {
            "kind": "daily_budget",
            "dedupe_key": "audit:daily_budget",
            "title_ro": (
                "Bugetul zilnic nu ajunge pentru un film"
                if daily is not None
                else "Studioul nu are un buget zilnic pentru filme"
            ),
            "why_ro": why,
            "effect_ro": f"Bugetul zilnic devine {recommended} USD; cheltuiala rămâne plafonată.",
            "options": [
                {
                    "key": "raise",
                    "label_ro": f"Ridic bugetul zilnic la {recommended} USD",
                    "effect_ro": "Un film întreg, cu plafonul lui, încape într-o zi.",
                    "recommended": True,
                    "apply": {
                        "type": "budget",
                        "period": "DAILY",
                        "limit_usd": str(recommended),
                        "expected_version": budget_version(session, "DAILY"),
                    },
                },
                {
                    "key": "cheaper",
                    "label_ro": "Aleg un model mai ieftin sau 720p",
                    "effect_ro": "Bugetul rămâne; filmul se face cu modele mai ieftine.",
                    "apply": {
                        "type": "guided",
                        "place_ro": "config/film_models.json (setul permis) și foaia de filmare",
                        "steps_ro": "Scoate din setul permis modelele scumpe sau alege 720p pe "
                        "foaia de filmare a filmului.",
                    },
                },
            ],
            "clears_when": {"type": "daily_budget_at_least", "usd_micros": need},
        }
    ]


def _llm_cards(session: Session) -> list[dict[str, Any]]:
    from app.agents.models import AgentRun, ProviderRecord  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415

    cards = []
    for integration in session.scalars(select(Integration).where(Integration.kind == "ollama")):
        provider = session.get(ProviderRecord, integration.id)
        runs = (
            list(
                session.scalars(
                    select(AgentRun)
                    .where(AgentRun.provider_name == provider.name)
                    .order_by(AgentRun.started_at.desc())
                    .limit(5)
                )
            )
            if provider is not None
            else []
        )
        all_failed = len(runs) >= 3 and all(run.status == "FAILED" for run in runs)
        failing = (
            integration.status == "FAILED"
            or (provider is not None and provider.status in ("AUTH_REQUIRED", "OFFLINE"))
            or all_failed
        )
        if not failing:
            continue
        detail = next((run.error_detail for run in runs if run.error_detail), None)
        why = (
            f"Conexiunea «{integration.name}» nu răspunde: "
            + (
                f"ultimele {count(len(runs), 'rulare', 'rulări')} ale modelelor au eșuat"
                if all_failed
                else "verificarea ei a eșuat"
            )
            + (f" (ultima: {str(detail)[:200]})" if detail else "")
            + ". Fără ea angajații nu scriu, nu aleg și nu verifică nimic."
        )
        cards.append(reconnect_card(integration, why_ro=why))
    return cards


def _youtube_cards(session: Session) -> list[dict[str, Any]]:
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    connections = list(session.scalars(select(YouTubeConnection)))
    if not connections:
        return []
    cards = []
    # One card per channel, under the key the upload, the statistics and the checks use too
    # (`sources.youtube_key`): the same question is never asked twice.
    for connection in connections:
        if connection.status == "CONNECTED":
            continue
        name = connection.remote_channel_title or connection.name
        cards.append(
            youtube_card(
                connection,
                why_ro=(
                    f"Canalul YouTube «{name}» nu mai este conectat"
                    + (
                        f": {str(connection.last_error).strip().rstrip('.')}."
                        if connection.last_error
                        else "."
                    )
                    + " Studioul nu poate încărca nimic pe el până nu îl reconectezi."
                ),
            )
        )
    cards.append(
        {
            "kind": "google_oauth_production",
            "dedupe_key": "audit:google_oauth_production",
            "title_ro": "Aplicația Google în producție și auditul YouTube API",
            "why_ro": (
                "Cât timp ecranul de consimțământ Google este «Testing», autorizarea expiră "
                "după 7 zile; fără auditul YouTube API, încărcările rămân private."
            ),
            "effect_ro": "Conectările nu mai expiră; după audit filmele pot fi publice.",
            "options": [
                {
                    "key": "apply",
                    "label_ro": "Trec aplicația în producție și cer auditul",
                    "effect_ro": "Le faci tu în Google Cloud Console; marchezi cardul gata.",
                    "recommended": True,
                    "apply": {
                        "type": "guided",
                        "place_ro": "Google Cloud Console → APIs & Services → OAuth consent screen",
                        "steps_ro": "Publică aplicația («In production») și trimite formularul "
                        "de audit YouTube API (docs/project/YOUTUBE_CONNECTIONS.md).",
                    },
                }
            ],
            "clears_when": {"type": "never"},
        }
    )
    return cards


def _commercial_cards(session: Session) -> list[dict[str, Any]]:
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.media.factory import vendor_licence  # noqa: PLC0415

    cards = []
    for integration in session.scalars(
        select(Integration).where(Integration.kind.in_(("runway", "elevenlabs")))
    ):
        if vendor_licence(session, integration.id).get("commercial_use") is True:
            continue
        # Both of his connections may carry the same name: the vendor tells them apart.
        cards.append(commercial_use_card(integration))
    return cards


def _runpod_cards(session: Session) -> list[dict[str, Any]]:
    """A real RunPod connection whose GPU agents may not switch on yet: his card (2026-10-08);
    and, once, the LTX-2.5 licence only his Hugging Face account can accept."""
    from app.integrations.models import Integration  # noqa: PLC0415

    cards: list[dict[str, Any]] = []
    real = [
        row
        for row in session.scalars(
            select(Integration).where(Integration.kind == "runpod").order_by(Integration.id)
        )
        if str((row.config or {}).get("mock", "")).strip().lower() != "true"
    ]
    for integration in real:
        allowed = str((integration.config or {}).get("allow_infra_actions", "")).strip().lower()
        if allowed != "true":
            cards.append(runpod_infra_card(integration))
    if real:
        cards.append(runpod_ltx_licence_card())
    return cards


def _music_cards() -> list[dict[str, Any]]:
    from app.media.music_library import load_library  # noqa: PLC0415

    if any(track.kind == "music" for track in load_library().tracks):
        return []
    return [music_card()]


def _paid_rule_cards(session: Session) -> list[dict[str, Any]]:
    from app.models import OwnerPolicy  # noqa: PLC0415

    policy = session.get(OwnerPolicy, 1)
    if str(getattr(policy, "paid_media_approval", None) or "EVERY_PAID_STEP") != "EVERY_PAID_STEP":
        return []
    still_every_step = {"type": "paid_media_approval_is_not", "value": "EVERY_PAID_STEP"}
    return [
        {
            "kind": "narration_paid_step",
            "dedupe_key": "audit:narration_paid_step",
            "title_ro": "Narațiunea ca pas plătit întrebat",
            "why_ro": (
                "Regula ta este «fiecare pas plătit»: imaginile, cadrul de probă și mișcarea "
                "te întreabă, dar narațiunea ElevenLabs (~0,10 USD pe film) se cumpără fără "
                "întrebare. Schimbarea cere o modificare a specificației 51."
            ),
            "effect_ro": "Narațiunea te întreabă și ea înainte de cumpărare.",
            "options": [
                {
                    "key": "ask",
                    "label_ro": "Să mă întrebe și pentru narațiune",
                    "effect_ro": "Se modifică specificația 51 și codul; până atunci rămâne "
                    "cumpărată fără întrebare.",
                    "recommended": True,
                    "apply": {
                        "type": "record",
                        "follow_up_ro": "Cere modificarea specificației 51 (narațiunea ca pas "
                        "plătit sub EVERY_PAID_STEP) și apoi a codului; până atunci narațiunea "
                        "se cumpără fără întrebare.",
                    },
                },
                {
                    "key": "unasked",
                    "label_ro": "Narațiunea rămâne cumpărată fără întrebare",
                    "effect_ro": "Nimic nu se schimbă (~0,10 USD pe film).",
                    "apply": {"type": "none"},
                },
            ],
            "clears_when": still_every_step,
        },
        {
            "kind": "paid_media_rule",
            "dedupe_key": "audit:paid_media_rule",
            "title_ro": "Când trece studioul de la «fiecare pas plătit» la MODE",
            "why_ro": (
                "Acum te întreabă fiecare pas plătit al fiecărui film. Recomandarea auditului: "
                "rămâi așa până vezi cu ochii tăi primul film plătit cu plafon, apoi treci la "
                "MODE, unde decide modul de autonomie."
            ),
            "effect_ro": "Cu MODE, pașii plătiți nu te mai întreabă; plafonul rămâne.",
            "options": [
                {
                    "key": "keep",
                    "label_ro": "Rămân la fiecare pas plătit până văd primul film",
                    "effect_ro": "Nimic nu se schimbă acum.",
                    "recommended": True,
                    "apply": {"type": "none"},
                },
                {
                    "key": "mode",
                    "label_ro": "Trec acum la MODE",
                    "effect_ro": "Pașii plătiți urmează modul de autonomie.",
                    "apply": {
                        "type": "paid_media_approval",
                        "to": "MODE",
                        "expect": "EVERY_PAID_STEP",
                    },
                },
            ],
            "clears_when": still_every_step,
        },
    ]


def _editorial_cards(settings: Any) -> list[dict[str, Any]]:
    if getattr(settings, "editorial_qc_blocking", None) is not None:
        return []
    return [
        {
            "kind": "editorial_qc",
            "dedupe_key": "audit:editorial_qc",
            "title_ro": "Controlul editorial: consultativ sau blocant",
            "why_ro": (
                "Controlul editorial al filmului (poveste, ritm, final) doar avertizează acum. "
                "Blocant, ar opri un film slab înainte de publicare, dar ar putea opri și unul "
                "bun până nu e calibrat pe filme reale."
            ),
            "effect_ro": "Consultativ: avertismente; blocant: filmul nu trece QC.",
            "options": [
                {
                    "key": "advisory",
                    "label_ro": "Rămâne consultativ până la primul film real",
                    "effect_ro": "Nimic nu se schimbă.",
                    "recommended": True,
                    "apply": {"type": "none"},
                },
                {
                    "key": "blocking",
                    "label_ro": "Devine blocant",
                    "effect_ro": "Un film care pică controlul editorial nu se publică.",
                    "apply": {
                        "type": "guided",
                        "place_ro": "fișierul .env al studioului",
                        "steps_ro": "Scrie STUDIO_EDITORIAL_QC_BLOCKING=true și repornește "
                        "studioul.",
                    },
                },
            ],
            "clears_when": {"type": "setting_is_set", "name": "editorial_qc_blocking"},
        }
    ]


def _folder_size_gb(root: Path) -> tuple[float, bool]:
    """The size of the media root in GB, reading at most `SIZE_SCAN_LIMIT` files; True when
    the scan stopped early (the size is then "at least")."""
    total = 0
    seen = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            seen += 1
            if seen > SIZE_SCAN_LIMIT:
                return total / 1e9, True
            try:
                total += (Path(folder) / name).stat().st_size
            except OSError:
                continue
    return total / 1e9, False


def _old_film_cards(settings: Any) -> list[dict[str, Any]]:
    from app.media.disk import media_root  # noqa: PLC0415

    folders = media_folder_count(settings)
    if folders < OLD_FILMS_THRESHOLD:
        return []
    root = media_root(settings)
    size, partial = _folder_size_gb(root)
    size_ro = ("cel puțin " if partial else "") + f"{decimal(size, 0)} GB"
    return [
        {
            "kind": "old_test_films",
            "dedupe_key": "audit:old_test_films",
            "title_ro": "Filmele vechi de test ocupă discul",
            "why_ro": (
                f"În {root} sunt {count(folders, 'dosar', 'dosare')} de filme ({size_ro}), "
                "aproape toate de test. Studioul nu mută și nu șterge nimic din ele singur."
            ),
            "effect_ro": "Spațiu eliberat pe disc; filmele reale rămân.",
            "options": [
                {
                    "key": "archive",
                    "label_ro": "Le arhivez sau le șterg eu",
                    "effect_ro": "Le muți pe un disc de arhivă sau le ștergi, după o copie.",
                    "recommended": True,
                    "apply": {
                        "type": "guided",
                        "place_ro": f"dosarul {root}",
                        "steps_ro": "Fă întâi o copie de siguranță, apoi mută sau șterge "
                        "dosarele filmelor de test; păstrează filmele publicate.",
                    },
                },
                {
                    "key": "keep",
                    "label_ro": "Le păstrez",
                    "effect_ro": "Nimic nu se schimbă.",
                    "apply": {"type": "none"},
                },
            ],
            "clears_when": {"type": "media_folders_below", "count": OLD_FILMS_THRESHOLD},
        }
    ]


def _sale_terms_cards() -> list[dict[str, Any]]:
    if any((Path(ROOT) / name).is_file() for name in LICENCE_FILES):
        return []
    return [
        {
            "kind": "sale_terms",
            "dedupe_key": "audit:sale_terms",
            "title_ro": "Termenii de vânzare ai studioului (LICENSE / EULA)",
            "why_ro": (
                "Proiectul nu are încă o licență sau un contract de utilizare pentru "
                "cumpărător. Termenii îi stabilești tu, de preferat cu un jurist; studioul nu "
                "îi scrie singur."
            ),
            "effect_ro": "Studioul poate fi vândut cu termeni clari.",
            "options": [
                {
                    "key": "write",
                    "label_ro": "Stabilesc termenii",
                    "effect_ro": "Pui LICENSE și EULA în rădăcina proiectului.",
                    "recommended": True,
                    "apply": {
                        "type": "guided",
                        "place_ro": "rădăcina proiectului: LICENSE și EULA.md",
                        "steps_ro": "Alege licența și termenii pentru cumpărător și pune-i în "
                        "rădăcina proiectului.",
                    },
                }
            ],
            "clears_when": {"type": "file_exists", "any_of": list(LICENCE_FILES)},
        }
    ]


def _ever_seen(session: Session, dedupe_key: str) -> bool:
    return (
        session.scalars(
            select(OwnerDecision.id).where(OwnerDecision.dedupe_key == dedupe_key).limit(1)
        ).first()
        is not None
    )


def seed_owner_decisions(engine: Engine, settings: Any = None) -> list[str]:
    """Put the audit's open questions in the Owner's window, each once. Returns the ids of the
    cards created by this call (none on a second call). First, the cards an earlier DONE
    closed while their condition was unmet are re-opened, once (`reopen_unconfirmed_done`)."""
    reopened = reopen_unconfirmed_done(engine, settings)
    if reopened:
        logger.info("owner_decisions_reopened", extra={"cards": reopened})
    with Session(engine) as session:
        proposals: list[dict[str, Any]] = []
        if not _ever_seen(session, "audit:daily_budget"):
            proposals += _budget_cards(session, engine)
        proposals += _llm_cards(session)
        proposals += _youtube_cards(session)
        proposals += _commercial_cards(session)
        proposals += _music_cards()
        proposals += _runpod_cards(session)
        proposals += _paid_rule_cards(session)
        proposals += _editorial_cards(settings)
        if not _ever_seen(session, "audit:old_test_films"):
            proposals += _old_film_cards(settings)
        proposals += _sale_terms_cards()
    created: list[str] = []
    with Session(engine) as session, session.begin():
        for proposal in proposals:
            if _ever_seen(session, proposal["dedupe_key"]):
                continue
            row = propose_owner_decision(session, source=SOURCE, **proposal)
            created.append(row.id)
    return created
