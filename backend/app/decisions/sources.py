"""The studio's own places that meet a decision only the Owner can take (2026-10-03).

Each of them wrote him a letter or a log line and nothing in his window of decisions. Now each
PROPOSES a card, and keeps its letter:

- the daily run waiting OVER_DAILY_BUDGET (or with no daily budget) at a film's paid step:
  a budget card with what the film needs (`film_budget`, from `runbook.stages._sheet_letter`);
- a film's paid step that did not start, or stopped a scene, on the Runway balance (the Owner's
  rule of 2026-10-03: the balance holds the next round, or the next purchase, x the margin): a
  card to top up the account with what is missing, cleared by a later balance reading that
  covers it, read from the books (`film_low_balance` / `film_balance_covered`, from
  `media.shooting_sheet`; the condition `balance_covers`);
- a model connection its provider refused with HTTP 401, 402 or 403: a reconnect card naming
  the connection and its Settings place, withdrawn by the next run that succeeds on it
  (`model_run_finished`, from `agents.services.run_agent_task`);
- a YouTube connection whose grant Google refused (invalid_grant, or an upload or statistics
  read refused for the account): a reconnect card per connection, withdrawn when it is
  connected again (`youtube_refused` / `youtube_reconnected`);
- a film whose licence ledger is NEEDS_REVIEW because a connection does not state commercial
  use: one card per vendor connection (`film_needs_review`, from the licence ledger);
- a film assembled while the music library has no music: the music card (`film_without_music`);
- the automatic sheet repair paused (`media.blocker_repair`, LANGUAGE_MODEL_DOWN or DAILY_LIMIT):
  a card that says why and offers what unblocks it - reconnect the model; let the repair try
  again now; or turn the blocked scenes into a local move - the last two through his own Owner
  commands on his accept (`sheet_repair_paused` / `sheet_repair_resumed`).

The rules every producer keeps. It only proposes: the card is decided by the Owner alone
(`services.decide_owner_decision`). One open card per condition (the dedupe keys below, shared
with the audit's seed, so the same question is never asked twice). The card is withdrawn when
its condition clears (by the producer when it sees it, and by `refresh_owner_decisions` through
its ``clears_when``). A card he refused is not asked again for `REFUSAL_QUIET_DAYS`. And a
producer never breaks the work that called it: its writes run in a savepoint, and a failure is
logged and forgotten.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.decisions.models import OPEN_STATUSES, OwnerDecision
from app.decisions.services import (
    OWNER,
    DecisionApplyFailed,
    propose_owner_decision,
    withdraw_owner_decision,
)
from app.wording import count, decimal

logger = logging.getLogger("studio.decisions")

#: A card he refused is not proposed again by a producer for this many days: his no stands,
#: and the same failing connection does not put the same question in front of him every hour.
REFUSAL_QUIET_DAYS = 7

#: The provider statuses only he can fix: a key refused (401), a plan or credit ended (402), a
#: key without access (403). 404 (a retired model), 429 and 5xx are not reconnects.
OWNER_FIXES_HTTP = frozenset({401, 402, 403})

#: The vendors' names as he reads them; a connection's own name may repeat across vendors.
VENDOR_NAMES = {
    "runway": "Runway",
    "elevenlabs": "ElevenLabs",
    "ollama": "Ollama",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
}

#: The budget card recommends whole steps of this many dollars, rounded up.
BUDGET_STEP_USD = 5
#: The refusals of a film's paid step that wait on his daily budget.
BUDGET_REFUSALS = frozenset({"OVER_DAILY_BUDGET", "BLOCKED_NO_BUDGET"})

#: The pauses of the automatic sheet repair (`media.blocker_repair._repair_guard`).
SHEET_REPAIR_CAUSES = ("LANGUAGE_MODEL_DOWN", "DAILY_LIMIT")

#: The option types his accept applies through his own sheet commands (registered in
#: `services.APPLIERS`, implemented below).
SHEET_REPAIR_RETRY = "sheet_repair_retry"
SHEET_LOCAL_MOVE = "sheet_local_move"


# ---------------------------------------------------------------------------- the dedupe keys


def reconnect_key(integration_id: str) -> str:
    return f"reconnect:{integration_id}"


def youtube_key(connection_id: str) -> str:
    return f"reconnect_youtube:{connection_id}"


def commercial_use_key(integration_id: str) -> str:
    return f"commercial_use:{integration_id}"


MUSIC_KEY = "music_library"


def film_budget_key(storyboard_id: str) -> str:
    return f"daily_budget:film:{storyboard_id}"


def sheet_repair_key(storyboard_id: str, cause: str) -> str:
    return f"sheet_repair_paused:{storyboard_id}:{cause}"


def low_balance_key(storyboard_id: str) -> str:
    return f"low_balance:film:{storyboard_id}"


def runpod_infra_key(integration_id: str) -> str:
    return f"runpod_infra_actions:{integration_id}"


#: The LTX-2.5 licence gate on Hugging Face is his account's, once for the studio.
RUNPOD_LTX_KEY = "runpod_ltx_licence"
#: The option type his accept of the RunPod card applies (`apply_runpod_infra`).
RUNPOD_INFRA = "runpod_infra"
#: The option type his accept of the copy card applies: the one-time copy pod starts
#: (`apply_runpod_mirror_copy`, 2026-10-09).
RUNPOD_MIRROR_COPY = "runpod_mirror_copy"
#: The console step for an endpoint's cached model (no REST field sets it).
CONSOLE_MODEL_STEP_RO = "Manage → Edit Endpoint → Model"


def runpod_mirror_copy_key(integration_id: str) -> str:
    return f"runpod_mirror_copy:{integration_id}"


# ------------------------------------------------------------------------- the common rule


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _refused_lately(session: Session, dedupe_key: str) -> bool:
    latest = session.scalars(
        select(OwnerDecision)
        .where(OwnerDecision.dedupe_key == dedupe_key)
        .order_by(OwnerDecision.created_at.desc())
        .limit(1)
    ).first()
    if latest is None:
        return False
    # His no is a refusal, or an accept of the option that changes nothing («Las bugetul cum
    # este», «Filmele merg fără muzică»): both keep the question quiet. A guided accept or one
    # that applied something is not a no.
    kept_as_is = (
        latest.status == "ACCEPTED"
        and latest.decided_by == OWNER
        and isinstance(latest.applied, dict)
        and latest.applied.get("type") == "none"
    )
    if latest.status != "REFUSED" and not kept_as_is:
        return False
    decided = _when(latest.decided_at)
    return decided is not None and decided > datetime.now(UTC) - timedelta(days=REFUSAL_QUIET_DAYS)


def ask(session: Session, *, dedupe_key: str, source: str, **card: Any) -> OwnerDecision | None:
    """Propose a card in the caller's transaction, unless he refused the same question (or
    chose to keep things as they are) in the last `REFUSAL_QUIET_DAYS`. Idempotent: an open
    card with the key is returned unchanged."""
    if _refused_lately(session, dedupe_key):
        return None
    return propose_owner_decision(session, dedupe_key=dedupe_key, source=source, **card)


def _safely[T](session: Session, what: str, work: Callable[[], T]) -> T | None:
    """Run a producer inside a savepoint of the caller's transaction: a failure rolls back the
    card alone, is logged, and never fails the run, the upload or the film that called it."""
    try:
        with session.begin_nested():
            return work()
    except Exception as exc:  # noqa: BLE001 - a card is never worth the work that found it
        logger.warning("owner_decision_not_proposed", extra={"producer": what}, exc_info=exc)
        return None


def _own_transaction[T](engine: Engine, what: str, work: Callable[[Session], T]) -> T | None:
    """A producer called outside any transaction: its own, taking the write lock first."""
    from app.db import lock_for_write  # noqa: PLC0415

    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            return _safely(session, what, lambda: work(session))
    except Exception as exc:  # noqa: BLE001 - see _safely
        logger.warning("owner_decision_not_proposed", extra={"producer": what}, exc_info=exc)
        return None


def _usd(micros: int) -> str:
    """A sum as he reads it: «15», «7,40»."""
    text = decimal(micros / 1_000_000, 2)
    return text[:-3] if text.endswith(",00") else text


# ----------------------------------------------------------------------- the card builders
# Shared with the audit's seed (`app.decisions.seed`): one shape and one key per question.


def reconnect_card(
    integration: Any, *, why_ro: str, http_status: int | None = None
) -> dict[str, Any]:
    """A model connection to reconnect, in Settings → Furnizori AI."""
    steps = (
        "Reînnoiește abonamentul sau creditul la furnizor, apoi deschide conexiunea și apasă "
        "«Verifică»."
        if http_status == 402
        else "Deschide conexiunea, pune o cheie API validă (sau reînnoiește planul) și apasă "
        "«Verifică»."
    )
    return {
        "kind": "reconnect_connection",
        "dedupe_key": reconnect_key(integration.id),
        "title_ro": f"Reconectează «{integration.name}»",
        "why_ro": why_ro,
        "effect_ro": "Modelele de limbaj lucrează din nou; nu costă nimic să verifici.",
        "subject_type": "connection",
        "subject_id": integration.id,
        "options": [
            {
                "key": "reconnect",
                "label_ro": "O reconectez eu",
                "effect_ro": "Pune o cheie validă și apasă «Verifică».",
                "recommended": True,
                "apply": {"type": "guided", "place": "llm", "steps_ro": steps},
            }
        ],
        "clears_when": {"type": "integration_verified", "integration_id": integration.id},
    }


def youtube_card(connection: Any, *, why_ro: str) -> dict[str, Any]:
    """One YouTube connection to authorise again, in Settings → Conturi și e-mail."""
    name = connection.remote_channel_title or connection.name
    return {
        "kind": "reconnect_youtube",
        "dedupe_key": youtube_key(connection.id),
        "title_ro": f"Reconectează canalul YouTube «{name}»",
        "why_ro": why_ro,
        "effect_ro": "Încărcările și statisticile canalului pornesc din nou, private până la "
        "auditul YouTube API.",
        "subject_type": "channel",
        "subject_id": connection.id,
        "options": [
            {
                "key": "reconnect",
                "label_ro": "Îl reconectez eu",
                "effect_ro": "Autorizezi din nou contul canalului la Google.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place": "social",
                    "steps_ro": f"Apasă «Reconectează» la conexiunea «{connection.name}» și "
                    "autorizează contul canalului.",
                },
            }
        ],
        "clears_when": {"type": "youtube_channel_connected", "connection_id": connection.id},
    }


def vendor_label(integration: Any) -> str:
    return f"{VENDOR_NAMES.get(integration.kind, integration.kind)} («{integration.name}»)"


def commercial_use_card(integration: Any, *, why_ro: str | None = None) -> dict[str, Any]:
    """A vendor connection that does not state commercial use, in Settings → Video și sunet."""
    label = vendor_label(integration)
    return {
        "kind": "commercial_use",
        "dedupe_key": commercial_use_key(integration.id),
        "title_ro": f"Folosire comercială pe {label}",
        "why_ro": why_ro
        or (
            f"Conexiunea {label} nu spune dacă planul tău permite folosire comercială. Fără "
            "răspunsul tău, filmele rămân «NEEDS_REVIEW» și doar private."
        ),
        "effect_ro": "Cu «da», filmele pot ieși publice după QC și poarta drepturilor.",
        "subject_type": "connection",
        "subject_id": integration.id,
        "options": [
            {
                "key": "state",
                "label_ro": "Declar folosirea comercială",
                "effect_ro": "Scrii «da» și termenii pe conexiune, dacă planul o permite.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place": "media",
                    "steps_ro": f"Deschide conexiunea {label} și completează «folosire "
                    "comercială» cu «da» și termenii planului.",
                },
            }
        ],
        "clears_when": {"type": "commercial_use", "integration_id": integration.id},
    }


def runpod_infra_card(integration: Any) -> dict[str, Any]:
    """May agents switch the RunPod GPU on inside the paid steps he already approved?
    (2026-10-08, the Owner's cards: at most 1 GPU, budgeted at 4 USD/h, off right after.)"""
    return {
        "kind": "runpod_infra_actions",
        "dedupe_key": runpod_infra_key(integration.id),
        "title_ro": "Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?",
        "why_ro": (
            f"Conexiunea RunPod «{integration.name}» are GPU Serverless. Fără acordul tău, "
            "niciun pas plătit nu poate porni GPU-ul, așa că imaginile și mișcarea pe RunPod "
            "nu se pot face."
        ),
        "effect_ro": (
            "Pornesc GPU-ul (cel mult 1, buget 4 USD/oră) doar în pașii foii de filmare deja "
            "aprobați, sub plafonul lor, și îl opresc imediat după ultimul rezultat. Oprirea "
            "este mereu permisă, inclusiv la STOP AUTONOMIE."
        ),
        "subject_type": "connection",
        "subject_id": integration.id,
        "options": [
            {
                "key": "yes",
                "label_ro": "Da, doar în pașii aprobați",
                "effect_ro": "Agenții pot porni GPU-ul RunPod numai în interiorul unui pas "
                "plătit aprobat și îl opresc imediat după.",
                "recommended": True,
                "apply": {"type": RUNPOD_INFRA, "to": True, "integration_id": integration.id},
            },
            {
                "key": "not_yet",
                "label_ro": "Nu încă",
                "effect_ro": "GPU-ul RunPod rămâne oprit; pașii pe RunPod nu pornesc.",
                "apply": {"type": "none"},
            },
        ],
        "clears_when": {"type": "runpod_infra_enabled", "integration_id": integration.id},
    }


def runpod_ltx_licence_card() -> dict[str, Any]:
    """The LTX-2.5 weights are gated on Hugging Face: only he can accept their licence."""
    return {
        "kind": "runpod_ltx_licence",
        "dedupe_key": RUNPOD_LTX_KEY,
        "title_ro": (
            "Acceptă licența LTX-2.5 pe Hugging Face (contul tău) și pune tokenul HF pentru "
            "construirea imaginii"
        ),
        "why_ro": (
            "Modelul de mișcare LTX-2.5 este „închis” pe Hugging Face: condițiile le acceptă "
            "titularul contului (inclusiv acordul pentru e-mailuri de marketing). Licența e "
            "gratuită sub 10 milioane USD venit pe an, cere eticheta de conținut AI și interzice "
            "ștergerea marcajelor de proveniență."
        ),
        "effect_ro": (
            "Imaginea GPU pentru mișcare se poate construi cu LTX-2.5; fără ea rămâne doar "
            "Wan 2.2 (Apache-2.0)."
        ),
        "options": [
            {
                "key": "accept",
                "label_ro": "Accept eu licența",
                "effect_ro": "Accepți condițiile pe Hugging Face și creezi un token de citire.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": "huggingface.co → Lightricks LTX-2.5 (contul tău) și secretul "
                    "hf_token al construcției (backend/runpod_worker/README.md)",
                    "steps_ro": "Deschide pagina modelului LTX-2.5 pe Hugging Face, apasă "
                    "«Agree and access», apoi creează un token de citire și păstrează-l pentru "
                    "construirea imaginii (secretul hf_token, niciodată în cod).",
                },
            },
            {
                "key": "without",
                "label_ro": "Mișcarea merge doar pe Wan 2.2",
                "effect_ro": "Nimic nu se schimbă; LTX-2.5 nu se folosește.",
                "apply": {"type": "none"},
            },
        ],
        "clears_when": {"type": "never"},
    }


def runpod_weights_card(problem: Any, integration_id: str | None) -> dict[str, Any]:
    """An endpoint whose results proved other weights than his mirror (2026-10-09): which
    endpoint, what is expected, and the console step only he can take."""
    from app.providers.runpod.weights import (  # noqa: PLC0415
        ENV_STEP_RO,
        PURPOSE_RO,
        endpoint_pin_ro,
        weights_key,
    )

    purpose = str(problem.purpose)
    endpoint = problem.endpoint_id or "(nesetat)"
    expected = (
        f"{problem.expected_repo or '(depozit nesetat)'} la revizia "
        f"{(problem.expected_revision or 'nesetată')[:12]}"
    )
    return {
        "kind": "runpod_weights",
        "dedupe_key": weights_key(integration_id, purpose),
        "title_ro": f"Endpoint-ul RunPod pentru {PURPOSE_RO.get(purpose, purpose)} are alte modele",
        "why_ro": problem.words_ro(),
        "effect_ro": (
            f"Până faci pasul, GPU-ul endpoint-ului {endpoint} nu mai pornește și nu se cumpără "
            f"nimic pe el. Așteptat: copia ta {expected}."
        ),
        "subject_type": "connection" if integration_id else None,
        "subject_id": integration_id,
        "options": [
            {
                "key": "fix",
                "label_ro": "Pun modelul corect în consola RunPod",
                "effect_ro": "Alegi copia ta în câmpul Model al endpoint-ului și îi scrii "
                "revizia în variabilele lui, apoi apeși «Am făcut-o»; prima rundă următoare "
                "verifică din nou.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": f"console.runpod.io → Serverless → {endpoint} → "
                    f"{CONSOLE_MODEL_STEP_RO}",
                    "steps_ro": f"Deschide endpoint-ul {endpoint}, «{CONSOLE_MODEL_STEP_RO}», "
                    f"alege {problem.expected_repo or 'copia ta de pe Hugging Face'} (cu tokenul "
                    f"tău Hugging Face), apoi la «{ENV_STEP_RO}» pune "
                    f"{endpoint_pin_ro(problem.expected_repo, problem.expected_revision)} și "
                    "salvează. Nimic din acestea nu se poate seta prin API.",
                },
            },
            {
                "key": "keep_off",
                "label_ro": "Las GPU-ul acestui endpoint oprit",
                "effect_ro": "Nimic nu se cumpără pe acest endpoint până nu se schimbă copia.",
                "apply": {"type": "none"},
            },
        ],
        # Only he closes it (his DONE); the expected revision it was written for travels with
        # it, so a new copy (a new revision) is a new question (`weights.weights_hold`).
        "clears_when": {"type": "never", "expected_revision": problem.expected_revision},
    }


def runpod_mirror_copy_card(integration: Any, *, why_ro: str | None = None) -> dict[str, Any]:
    """The one-time copy of the weights into his private Hugging Face mirrors (2026-10-09).
    His accept IS the press: the cap is written on the card and nothing else starts it."""
    from app.providers.runpod.config import RunPodConfig  # noqa: PLC0415
    from app.providers.runpod.weights import expected_weights  # noqa: PLC0415

    config = RunPodConfig.from_integration(dict(integration.config or {}), {})
    images = [
        image
        for image, purpose in (("stills", "image"), ("motion", "video"))
        if config.endpoint_for(purpose) and not expected_weights(config, purpose)[1]  # type: ignore[arg-type]
    ] or ["stills", "motion"]
    usd = f"{config.mirror_copy_max_usd:.2f}"
    minutes = int(config.mirror_copy_max_minutes)
    repos = {
        image: expected_weights(config, purpose)[0] or "nesetat (Setări → RunPod)"  # type: ignore[arg-type]
        for image, purpose in (("stills", "image"), ("motion", "video"))
    }
    named = "; ".join(
        f"{'poze' if image == 'stills' else 'clipuri'}: {repos[image]}" for image in images
    )
    return {
        "kind": "runpod_mirror_copy",
        "dedupe_key": runpod_mirror_copy_key(integration.id),
        "title_ro": "Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?",
        "why_ro": why_ro
        or (
            "Endpoint-urile RunPod citesc modelele din cache-ul RunPod, iar cache-ul se umple "
            f"din copiile tale private de pe Hugging Face ({named}). Copiile nu există încă. "
            "Copierea o face un server RunPod temporar (CPU), nu PC-ul tău."
        ),
        "effect_ro": (
            "Un singur pas plătit, pornit chiar de acceptul tău: un server RunPod temporar "
            "copiază fișier cu fișier, verifică fiecare fișier, iar eu îl opresc definitiv "
            f"(terminate) la final. Plafon: {usd} USD și {minutes} minute; la plafon, la eșec "
            "sau la repornirea studioului îl opresc definitiv. Costul îl scriu în jurnal. Prețul "
            "exact al serverului nu e documentat. Ai nevoie de tokenul Hugging Face (scriere în "
            "cele două depozite private) salvat în conexiunea RunPod. Atenție: serverul primește "
            "tokenul în variabilele lui de mediu, iar acestea se văd în consola RunPod (Pods → "
            "amn-mirror-copy-…) cât timp serverul există; folosește un token fin (fine-grained) "
            "doar pentru cele două copii și pentru citirea LTX-2.5, și revocă-l pe Hugging Face "
            "după copiere."
        ),
        "subject_type": "connection",
        "subject_id": integration.id,
        "options": [
            {
                "key": "yes",
                "label_ro": f"Da, pornește copia acum (plafon {usd} USD, {minutes} minute)",
                "effect_ro": "Serverul temporar pornește acum și se oprește singur.",
                "recommended": True,
                "apply": {
                    "type": RUNPOD_MIRROR_COPY,
                    "integration_id": integration.id,
                    "images": images,
                    "max_usd": usd,
                    "max_minutes": minutes,
                },
            },
            {
                "key": "not_yet",
                "label_ro": "Nu încă",
                "effect_ro": "Totul rămâne pregătit și nu se cheltuie nimic, dar nu se poate "
                "genera pe RunPod.",
                "apply": {"type": "none"},
            },
        ],
        "clears_when": {"type": "runpod_mirrors_ready", "integration_id": integration.id},
    }


def music_card(*, why_ro: str | None = None) -> dict[str, Any]:
    """The empty music library: his choice of where the music comes from."""
    return {
        "kind": "music_library",
        "dedupe_key": MUSIC_KEY,
        "title_ro": "Biblioteca de muzică este goală",
        "why_ro": why_ro
        or (
            "config/music_library.json nu are nicio piesă cu licență comercială, așa că filmele "
            "ies fără muzică. Sursa muzicii este alegerea ta."
        ),
        "effect_ro": "Filmele primesc un fond muzical potrivit, cu licența verificată.",
        "options": [
            {
                "key": "add",
                "label_ro": "Adaug muzică licențiată",
                "effect_ro": "Pui piesele și licențele lor în bibliotecă.",
                "recommended": True,
                "apply": {
                    "type": "guided",
                    "place_ro": "config/music_library.json",
                    "steps_ro": "Adaugă fiecare piesă: fișierul, sha256, licența și "
                    "commercial_ok true doar dacă licența permite folosire comercială.",
                },
            },
            {
                "key": "without",
                "label_ro": "Filmele merg fără muzică",
                "effect_ro": "Nimic nu se schimbă.",
                "apply": {"type": "none"},
            },
        ],
        "clears_when": {"type": "music_library_has_music"},
    }


# ------------------------------------------------- (a) a film waiting on the daily budget


def _active_daily_limit(session: Session) -> int | None:
    from app.economy.models import SpendingBudget  # noqa: PLC0415

    limit = session.scalar(
        select(SpendingBudget.limit_usd_micros).where(
            SpendingBudget.period == "DAILY", SpendingBudget.active.is_(True)
        )
    )
    return int(limit) if limit is not None else None


def film_budget(
    engine: Engine,
    storyboard_id: str,
    film: Mapping[str, Any],
    plan_cost: Mapping[str, Any] | None,
    *,
    step_words: str = "",
) -> bool:
    """The daily run's film stopped at a paid step: a budget card when the step can never fit
    in a day under his daily budget (or there is none), with what the whole film needs; the
    film's card withdrawn once it no longer waits on the budget. A step that fits a fresh day
    and waits only for tomorrow is not his decision: no card. Returns whether a card stands."""

    def work(session: Session) -> bool:
        key = film_budget_key(storyboard_id)
        if film.get("refusal") not in BUDGET_REFUSALS:
            withdraw_owner_decision(
                session,
                dedupe_key=key,
                reason_ro="Filmul nu mai așteaptă bugetul zilei.",
                source="daily_run",
            )
            return False
        sheet = film.get("sheet") if isinstance(film.get("sheet"), Mapping) else None
        steps = (sheet or {}).get("steps")
        info = (steps if isinstance(steps, Mapping) else {}).get(film.get("step")) or {}
        step_micros = round(float(info.get("cap_usd") or 0.0) * 1_000_000)
        if step_micros <= 0:
            return False
        daily = _active_daily_limit(session)
        if daily is not None and daily >= step_micros:
            return False
        film_micros = int((plan_cost or {}).get("usd_micros") or 0)
        need = max(step_micros, film_micros)
        recommended = math.ceil(need / (BUDGET_STEP_USD * 1_000_000)) * BUDGET_STEP_USD
        title = str((sheet or {}).get("title") or storyboard_id[:8])
        words = f" «{step_words}»" if step_words else ""
        now_ro = (
            f"bugetul zilnic activ este de {_usd(daily)} USD, așa că pasul nu încape în nicio zi"
            if daily is not None
            else "nu există un buget zilnic activ, iar în producție fără buget nu se cumpără "
            "nimic neîntrebat"
        )
        whole = (
            f" Filmul întreg are, după foaia de filmare, plafonul de {_usd(film_micros)} USD."
            if film_micros
            else ""
        )
        from app.economy.budget import budget_version  # noqa: PLC0415

        card = ask(
            session,
            kind="daily_budget",
            dedupe_key=key,
            source="daily_run",
            subject_type="storyboard",
            subject_id=storyboard_id,
            title_ro=f"Bugetul zilnic nu ajunge pentru filmul «{title}»",
            why_ro=(
                f"Filmul «{title}» așteaptă la pasul{words}: plafonul pasului este de "
                f"{_usd(step_micros)} USD, iar {now_ro}.{whole}"
            ),
            effect_ro=(
                f"Bugetul zilnic devine {recommended} USD: filmul încape într-o zi, iar "
                "cheltuiala rămâne plafonată."
            ),
            options=[
                {
                    "key": "raise",
                    "label_ro": f"Ridic bugetul zilnic la {recommended} USD",
                    "effect_ro": "Pasul se cumpără la rularea următoare, sub regula ta.",
                    "recommended": True,
                    "apply": {
                        "type": "budget",
                        "period": "DAILY",
                        "limit_usd": str(recommended),
                        "expected_version": budget_version(session, "DAILY"),
                    },
                },
                {
                    "key": "keep",
                    "label_ro": "Las bugetul cum este",
                    "effect_ro": "Filmul așteaptă; pasul se poate cumpăra doar cu acordul tău "
                    "de depășire pe foaia de filmare.",
                    "apply": {"type": "none"},
                },
            ],
            clears_when={"type": "daily_budget_at_least", "usd_micros": step_micros},
        )
        return card is not None

    return bool(_own_transaction(engine, "film_budget", work))


# ------------------------------------------- (a2) a film's paid step the balance stopped


def film_low_balance(
    engine: Engine,
    storyboard_id: str,
    *,
    title: str,
    step_words: str,
    short: Mapping[str, Any],
) -> bool:
    """A paid step of the film did not start, or stopped a scene, on the Runway balance (the
    Owner's rule of 2026-10-03: the balance holds the next round, or the next purchase, x the
    margin). A card with what is missing for that purchase, cleared by a later balance reading
    that covers it (`balance_covers`); the step's letter, if the day writes one, stays.
    Returns whether a card stands."""
    needed = int(short.get("needed_credits") or 0)
    missing = int(short.get("missing_credits") or 0)
    if needed <= 0 or missing <= 0:
        return False

    def work(session: Session) -> bool:
        standing = _open_low_balance_card(session, storyboard_id)
        if standing is not None and _card_need(standing) != needed:
            # The film's newest need is what the card asks (a re-roll's 21 credits must not
            # clear on 50 when the next start needs 83). A card he has not answered is
            # replaced; one he accepted and is carrying out keeps its words, and its condition
            # follows the new need, so it never clears while the account is still short.
            if standing.status == "PENDING":
                withdraw_owner_decision(
                    session,
                    decision_id=standing.id,
                    reason_ro="Suma necesară s-a schimbat; cardul nou spune cât lipsește acum.",
                    source="paid_step",
                )
            else:
                standing.clears_when = {"type": "balance_covers", "credits": needed}
                return True
        lacking = count(missing, "credit", "credite")
        card = ask(
            session,
            kind="low_balance",
            dedupe_key=low_balance_key(storyboard_id),
            source="paid_step",
            subject_type="storyboard",
            subject_id=storyboard_id,
            title_ro=f"Contul Runway nu acoperă runda următoare a filmului «{title}»",
            why_ro=(
                f"Filmul «{title}» așteaptă la pasul «{step_words}». "
                f"{str(short.get('reason_ro') or '').strip()}"
            ).strip(),
            effect_ro=(
                "După alimentare, pasul pornește din nou: la rularea următoare a zilei sau "
                "când apeși pe foaia de filmare. Plafonul aprobat rămâne limita pasului."
            ),
            options=[
                {
                    "key": "top_up",
                    "label_ro": f"Alimentez contul Runway cu cel puțin {lacking}",
                    "effect_ro": "Soldul se citește din nou înaintea cumpărării următoare; "
                    "cardul se închide singur când ajunge.",
                    "recommended": True,
                    "apply": {
                        "type": "guided",
                        "place": "media",
                        "steps_ro": f"Alimentează contul Runway (pe site-ul Runway) cu cel "
                        f"puțin {lacking}, apoi lasă filmul să continue: nu se cumpără nimic "
                        "peste plafonul pe care l-ai aprobat.",
                    },
                },
                {
                    "key": "wait",
                    "label_ro": "Aștept",
                    "effect_ro": "Filmul așteaptă; nu se cumpără nimic până nu sunt bani în cont.",
                    "apply": {"type": "none"},
                },
            ],
            clears_when={"type": "balance_covers", "credits": needed},
        )
        return card is not None

    return bool(_own_transaction(engine, "film_low_balance", work))


def _open_low_balance_card(session: Session, storyboard_id: str) -> OwnerDecision | None:
    return session.scalars(
        select(OwnerDecision).where(
            OwnerDecision.dedupe_key == low_balance_key(storyboard_id),
            OwnerDecision.status.in_(OPEN_STATUSES),
        )
    ).first()


def _card_need(row: OwnerDecision) -> float:
    spec = row.clears_when if isinstance(row.clears_when, dict) else {}
    value = spec.get("credits")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def film_balance_covered(engine: Engine, storyboard_id: str, credits: float) -> None:
    """A paid step of the film started on a balance of ``credits``: its low-balance card is
    withdrawn when that balance covers what the card asks (a step that starts on a smaller
    need of its own leaves a larger one standing)."""

    def work(session: Session) -> None:
        standing = _open_low_balance_card(session, storyboard_id)
        if standing is None or float(credits) < _card_need(standing):
            return
        withdraw_owner_decision(
            session,
            dedupe_key=low_balance_key(storyboard_id),
            reason_ro="Soldul Runway acoperă acum runda următoare a filmului.",
            source="paid_step",
        )

    _own_transaction(engine, "film_balance_covered", work)


# ------------------------------------------------- (b) a model connection its provider refused


def _without_class(detail: str | None) -> str:
    text = str(detail or "").strip()
    return text.split(": ", 1)[1] if text.startswith("ProviderHTTPError: ") else text


def model_run_finished(
    session: Session,
    provider_id: str,
    status: str,
    http_status: int | None,
    error_detail: str | None,
) -> OwnerDecision | None:
    """After a model run, in its own record's transaction: a run its provider refused for a
    reason only he fixes proposes the reconnect card of the connection behind it; a run that
    succeeded withdraws it. A provider with no connection in Settings has nothing to reconnect."""
    if status not in ("SUCCEEDED", "FAILED"):
        return None

    def work() -> OwnerDecision | None:
        from app.integrations.models import Integration  # noqa: PLC0415

        integration = session.get(Integration, provider_id)
        if integration is None:
            return None
        if status == "SUCCEEDED":
            withdraw_owner_decision(
                session,
                dedupe_key=reconnect_key(integration.id),
                reason_ro=f"Conexiunea «{integration.name}» răspunde din nou: o rulare a reușit.",
                source="agents",
            )
            return None
        if http_status not in OWNER_FIXES_HTTP:
            return None
        why = (
            f"Furnizorul a refuzat conexiunea «{integration.name}»: "
            f"{_without_class(error_detail) or f'HTTP {http_status}'}. Fără ea, angajații care "
            "lucrează pe ea nu pot scrie, alege sau verifica nimic, iar studioul nu o poate "
            "repara singur."
        )
        return ask(
            session,
            source="agents",
            **reconnect_card(integration, why_ro=why, http_status=http_status),
        )

    return _safely(session, "model_run_finished", work)


# --------------------------------------------------------- (c) a YouTube grant refused


def youtube_refused(
    session: Session, connection: Any, reason_ro: str, *, source: str
) -> OwnerDecision | None:
    """Google refused a YouTube connection's account: its reconnect card."""
    if connection is None:
        return None

    def work() -> OwnerDecision | None:
        why = (
            f"{str(reason_ro).strip().rstrip('.')}. Până nu îl reconectezi, studioul nu poate "
            "încărca nimic pe acest canal și nu îi poate citi statisticile."
        )
        return ask(session, source=source, **youtube_card(connection, why_ro=why))

    return _safely(session, "youtube_refused", work)


def youtube_reconnected(session: Session, connection_id: str) -> None:
    """The connection answered again (authorised or verified): its card is withdrawn."""
    _safely(
        session,
        "youtube_reconnected",
        lambda: withdraw_owner_decision(
            session,
            dedupe_key=youtube_key(connection_id),
            reason_ro="Contul YouTube este conectat din nou.",
            source="youtube",
        ),
    )


# ------------------------------------------- (d) a film NEEDS_REVIEW for commercial use


def film_needs_review(engine: Engine, components: list[Mapping[str, Any]]) -> list[str]:
    """A film's licence ledger came out NEEDS_REVIEW: one commercial-use card per vendor
    connection whose component carries no commercial-use statement. Returns the cards' ids."""

    def work(session: Session) -> list[str]:
        from app.integrations.models import Integration  # noqa: PLC0415

        found: dict[str, int] = {}
        for component in components:
            if component.get("commercial_use") is True or component.get("source") != "connection":
                continue
            identifier = component.get("integration_id")
            if identifier:
                found[str(identifier)] = found.get(str(identifier), 0) + 1
        made: list[str] = []
        for identifier, parts in found.items():
            integration = session.get(Integration, identifier)
            if integration is None:
                continue
            label = vendor_label(integration)
            lacking = (
                f"o componentă de la {label} nu are"
                if parts == 1
                else f"{count(parts, 'componentă', 'componente')} de la {label} nu au"
            )
            why = (
                f"Un film asamblat a ieșit «NEEDS_REVIEW»: {lacking} confirmarea folosirii "
                "comerciale, fiindcă conexiunea nu spune dacă planul tău o permite. Fără "
                "răspunsul tău, filmele rămân doar private."
            )
            card = ask(session, source="licences", **commercial_use_card(integration, why_ro=why))
            if card is not None:
                made.append(card.id)
        return made

    return _own_transaction(engine, "film_needs_review", work) or []


# --------------------------------------------------------- (e) a film without music


def music_library_empty(session: Session, *, title: str) -> OwnerDecision | None:
    """A film was mixed while the library has no music at all: the music card."""
    why = (
        f"Filmul «{title}» a fost asamblat fără muzică: config/music_library.json nu are nicio "
        "piesă cu licență comercială confirmată. Sursa muzicii este alegerea ta."
    )
    return _safely(
        session,
        "music_library_empty",
        lambda: ask(session, source="assembly", **music_card(why_ro=why)),
    )


def film_without_music(engine: Engine, title: str) -> None:
    _own_transaction(engine, "film_without_music", lambda s: music_library_empty(s, title=title))


# ------------------------------------------------- (f) the automatic sheet repair paused


def _blocked_live_scenes(session: Session, sheet: Mapping[str, Any]) -> list[int]:
    """The filmed scenes the sheet's blockers name, the ones a local move can take."""
    from app.media.assembler import scene_kind_of  # noqa: PLC0415
    from app.media.blocker_repair import sheet_issues  # noqa: PLC0415
    from app.media.models import StoryboardScene  # noqa: PLC0415

    named = {
        int(issue["scene_index"])
        for issue in sheet_issues(dict(sheet))
        if isinstance(issue.get("scene_index"), int)
    }
    if not named:
        return []
    scenes = session.scalars(
        select(StoryboardScene).where(
            StoryboardScene.storyboard_id == str(sheet["storyboard_id"]),
            StoryboardScene.scene_index.in_(sorted(named)),
        )
    )
    return sorted(
        scene.scene_index
        for scene in scenes
        if scene_kind_of({"scene_kind": scene.scene_kind}) == "LIVE"
    )


def _scene_words(scenes: list[int]) -> str:
    return ("scena " if len(scenes) == 1 else "scenele ") + ", ".join(map(str, scenes))


def sheet_repair_paused(
    session: Session, sheet: Mapping[str, Any], fingerprint: str, guard: Mapping[str, Any]
) -> OwnerDecision | None:
    """The sheet's automatic repair paused: a card with the cause and what unblocks it. Its
    letter stays (`blocker_repair._pause_letter`)."""
    cause = str(guard.get("cause") or "")
    if cause not in SHEET_REPAIR_CAUSES:
        return None
    identifier = str(sheet["storyboard_id"])
    title = str(sheet.get("title") or identifier[:8])

    def work() -> OwnerDecision | None:
        from app.media.shooting_sheet import sheet_url  # noqa: PLC0415

        scenes = _blocked_live_scenes(session, sheet)
        options: list[dict[str, Any]] = []
        if cause == "LANGUAGE_MODEL_DOWN":
            options.append(
                {
                    "key": "reconnect",
                    "label_ro": "Reconectez modelul de limbaj",
                    "effect_ro": "După primul răspuns reușit al modelului, Directorul reia "
                    "singur remedierea.",
                    "recommended": True,
                    "apply": {
                        "type": "guided",
                        "place": "llm",
                        "steps_ro": "Deschide conexiunea modelului, pune o cheie validă (sau "
                        "reînnoiește planul) și apasă «Verifică».",
                    },
                }
            )
        else:
            options.append(
                {
                    "key": "retry",
                    "label_ro": "Să mai încerce o dată acum",
                    "effect_ro": "Directorul reia remedierea la următoarea verificare a "
                    "foilor; lucrează doar modelul de limbaj, nu se cumpără nimic.",
                    "recommended": True,
                    "apply": {
                        "type": SHEET_REPAIR_RETRY,
                        "storyboard_id": identifier,
                        "fingerprint": fingerprint,
                    },
                }
            )
        if scenes:
            options.append(
                {
                    "key": "local_move",
                    "label_ro": f"Animez local {_scene_words(scenes)}",
                    "effect_ro": f"Pentru {_scene_words(scenes)} nu se mai cumpără mișcare: "
                    "imaginea fixă se animă local (0 credite pentru mișcare). Foaia se "
                    "schimbă, iar remedierea o ia de la capăt pe foaia nouă.",
                    "apply": {
                        "type": SHEET_LOCAL_MOVE,
                        "storyboard_id": identifier,
                        "scenes": scenes,
                        "url": sheet_url(identifier),
                    },
                }
            )
        options.append(
            {
                "key": "wait",
                "label_ro": "Aștept",
                "effect_ro": (
                    "Remedierea se reia singură când modelul răspunde din nou."
                    if cause == "LANGUAGE_MODEL_DOWN"
                    else "Remedierea se reia mâine sau când foaia se schimbă."
                ),
                "apply": {"type": "none"},
            }
        )
        headline = (
            "modelul de limbaj nu răspunde"
            if cause == "LANGUAGE_MODEL_DOWN"
            else "s-a oprit pentru azi după prea multe încercări"
        )
        return ask(
            session,
            kind="sheet_repair_paused",
            dedupe_key=sheet_repair_key(identifier, cause),
            source="sheet_repair",
            subject_type="storyboard",
            subject_id=identifier,
            title_ro=f"Remedierea foii «{title}» stă: {headline}",
            why_ro=str(guard.get("reason_ro") or ""),
            effect_ro="Foaia de filmare se deblochează; nu se cumpără nimic fără regula ta.",
            options=options,
            clears_when={"type": "sheet_repair_resumed", "storyboard_id": identifier},
        )

    return _safely(session, "sheet_repair_paused", work)


def sheet_repair_resumed(session: Session, storyboard_id: str) -> None:
    """The repair was queued again: the pause cards of this sheet are withdrawn."""

    def work() -> None:
        for cause in SHEET_REPAIR_CAUSES:
            withdraw_owner_decision(
                session,
                dedupe_key=sheet_repair_key(storyboard_id, cause),
                reason_ro="Remedierea automată a foii a fost reluată.",
                source="sheet_repair",
            )

    _safely(session, "sheet_repair_resumed", work)


# ------------------------------------------------- his accept, through his own commands


def apply_sheet_repair_retry(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His accept lets the paused repair try again now (`blocker_repair.allow_repair_retry`)."""
    from app.media.blocker_repair import allow_repair_retry  # noqa: PLC0415

    identifier = str(spec.get("storyboard_id") or "")
    try:
        event_id = allow_repair_retry(
            engine,
            identifier,
            issued_by=OWNER,
            correlation_id=inner,
            fingerprint=spec.get("fingerprint"),
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise DecisionApplyFailed(str(exc)) from None
    return {
        "command": "AllowSheetRepairRetry",
        "result": {"storyboard_id": identifier},
        "event_id": event_id,
    }


def apply_sheet_local_move(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His accept chooses the local move for the blocked scenes (`set_scene_model`, his own
    sheet command). Every scene is checked before any is changed, so a refusal changes none;
    a scene already on the local move is not chosen again (a retried accept applies once)."""
    from app.media.assembler import scene_kind_of  # noqa: PLC0415
    from app.media.models import StoryboardScene  # noqa: PLC0415
    from app.media.production_policy import LOCAL_MOVE  # noqa: PLC0415
    from app.media.shooting_sheet import (  # noqa: PLC0415
        SCENE_MODEL_EVENT,
        SheetChoiceRefused,
        SheetNotFound,
        set_scene_model,
        sheet_overrides,
    )
    from app.models import DomainEvent  # noqa: PLC0415

    identifier = str(spec.get("storyboard_id") or "")
    scenes = [int(index) for index in spec.get("scenes") or []]
    if not identifier or not scenes:
        raise DecisionApplyFailed("Cardul nu numește nicio scenă; nu s-a aplicat nimic.")
    with Session(engine) as session:
        kinds = {
            row.scene_index: scene_kind_of({"scene_kind": row.scene_kind})
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == identifier)
            )
        }
    for index in scenes:
        if kinds.get(index) != "LIVE":
            raise DecisionApplyFailed(
                f"Scena {index} nu mai este o scenă filmată a acestui film; nu s-a aplicat "
                "nimic. Refuză cardul sau așteaptă unul nou."
            )
    chosen = sheet_overrides(engine, identifier)
    title = str(words.get("title_ro") or "")
    for index in scenes:
        if chosen.get(index) == LOCAL_MOVE:
            continue
        try:
            set_scene_model(
                engine,
                identifier,
                index,
                LOCAL_MOVE,
                issued_by=OWNER,
                note=f"Decizia Proprietarului: {title}"[:500],
                correlation_id=inner,
            )
        except (SheetChoiceRefused, SheetNotFound, PermissionError) as exc:
            raise DecisionApplyFailed(str(exc)) from None
    with Session(engine) as session:
        event_id = session.scalars(
            select(DomainEvent.event_id)
            .where(
                DomainEvent.event_type == SCENE_MODEL_EVENT,
                DomainEvent.aggregate_id == identifier,
                DomainEvent.correlation_id == inner,
            )
            .order_by(DomainEvent.sequence.desc())
            .limit(1)
        ).first()
    return {
        "command": "SetSceneModel",
        "result": {"storyboard_id": identifier, "scenes": scenes, "model_id": LOCAL_MOVE},
        "event_id": event_id,
    }


def apply_runpod_infra(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His accept of the RunPod card: the connection's ``allow_infra_actions`` becomes true
    (version bump, event ``runpod.infra_actions_enabled``). Idempotent by the inner command id.
    It lets agents switch the GPU on only inside paid steps the kernel already lets run
    (`services._gpu_on_verdict`); it buys nothing."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.models import CommandRecord  # noqa: PLC0415
    from app.services import append_event, command_hash, remember_command  # noqa: PLC0415

    name = "EnableRunPodInfra"
    if spec.get("to") is not True:
        raise DecisionApplyFailed("Cardul nu cere pornirea de către agenți; nu s-a aplicat nimic.")
    identifier = str(spec.get("integration_id") or "")
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        previous = session.get(CommandRecord, inner)
        if previous is not None:
            done = dict(previous.response)
            return {"command": name, "result": done, "event_id": done.get("event_id")}
        row = session.get(Integration, identifier)
        if row is None or row.kind != "runpod":
            raise DecisionApplyFailed(
                "Conexiunea RunPod din card nu mai există; nu s-a aplicat nimic."
            )
        config = dict(row.config or {})
        already = str(config.get("allow_infra_actions", "")).strip().lower() == "true"
        if not already:
            row.config = {**config, "allow_infra_actions": "true"}
            row.version += 1
        event = append_event(
            session,
            "runpod.infra_actions_enabled",
            "integration",
            row.id,
            row.version,
            {"integration_id": row.id, "already": already, "by": OWNER},
            inner,
        )
        if not already:
            row.event_id = event.event_id
        result = {
            "integration_id": row.id,
            "allow_infra_actions": True,
            "version": row.version,
            "event_id": event.event_id,
        }
        remember_command(session, inner, name, command_hash(dict(spec)), result)
    return {"command": name, "result": result, "event_id": result["event_id"]}


# --------------------------------------------------------------- the conditions they clear on


def apply_runpod_mirror_copy(
    engine: Engine, spec: Mapping[str, Any], inner: str, words: Mapping[str, Any]
) -> dict[str, Any]:
    """His accept of the copy card: the one-time copy pod starts now, under the card's cap
    (`providers.runpod.pods.start_copy`). A missing token, repo or bucket refuses with his
    reason and starts nothing; the card stays PENDING."""
    from pathlib import Path  # noqa: PLC0415

    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.providers.runpod import pods  # noqa: PLC0415

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    try:
        result = pods.start_copy(
            engine,
            vault,
            str(spec.get("integration_id") or ""),
            max_minutes=int(spec.get("max_minutes") or 0),
            max_usd=str(spec.get("max_usd") or ""),
            images=[str(image) for image in spec.get("images") or []] or None,
            decision_inner=inner,
        )
    except pods.CopyRefused as exc:
        raise DecisionApplyFailed(exc.reason_ro) from None
    return {"command": "StartRunPodMirrorCopy", "result": result, "event_id": result["event_id"]}


def runpod_mirrors_ready(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """Every configured endpoint of the connection knows its mirror's revision (or the
    connection no longer exists, or no longer reads a cache)."""
    from app.integrations.models import Integration  # noqa: PLC0415
    from app.providers.runpod.config import RunPodConfig  # noqa: PLC0415
    from app.providers.runpod.weights import expected_weights  # noqa: PLC0415

    integration = session.get(Integration, str(params.get("integration_id") or ""))
    if integration is None:
        return True
    config = RunPodConfig.from_integration(dict(integration.config or {}), {})
    if config.model_source != "cache":
        return True
    return all(
        expected_weights(config, purpose)[1]  # type: ignore[arg-type]
        for purpose in ("image", "video")
        if config.endpoint_for(purpose)  # type: ignore[arg-type]
    )


def runpod_infra_enabled(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """The RunPod connection lets agents switch its GPU on (or no longer exists)."""
    from app.integrations.models import Integration  # noqa: PLC0415

    integration = session.get(Integration, str(params.get("integration_id") or ""))
    if integration is None:
        return True
    config = integration.config if isinstance(integration.config, dict) else {}
    return str(config.get("allow_infra_actions", "")).strip().lower() == "true"


def youtube_channel_connected(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """The connection is CONNECTED and was authorised or verified after the card was written
    (a statistics refusal leaves it CONNECTED: only a new answer from Google clears it)."""
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    connection = session.get(YouTubeConnection, str(params.get("connection_id") or ""))
    if connection is None:
        return True
    if connection.status != "CONNECTED":
        return False
    created = _when(row.created_at)
    moments = [_when(value) for value in (connection.connected_at, connection.last_checked_at)]
    return created is not None and any(m is not None and m > created for m in moments)


def sheet_repair_resumed_condition(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """No open pause letter of this sheet's repair: the repair runs again."""
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.media.blocker_repair import PAUSED_KIND  # noqa: PLC0415

    identifier = str(params.get("storyboard_id") or "")
    for message in session.scalars(select(AgentMessage).where(AgentMessage.status == "OPEN")):
        body = message.body_json or {}
        if body.get("kind") == PAUSED_KIND and body.get("storyboard_id") == identifier:
            return False
    return True


def balance_covers(
    session: Session, row: OwnerDecision, params: Mapping[str, Any], settings: Any
) -> bool:
    """The newest balance reading a paid step recorded after the card was written covers the
    need the card names (`media.balance_rule.BALANCE_READ_EVENT`). Read from the books only:
    the feed that refreshes the cards never calls the vendor."""
    from app.media.balance_rule import BALANCE_READ_EVENT  # noqa: PLC0415 - media reads us
    from app.models import DomainEvent  # noqa: PLC0415

    newest = session.scalars(
        select(DomainEvent)
        .where(DomainEvent.event_type == BALANCE_READ_EVENT)
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    ).first()
    if newest is None:
        return False
    created, read = _when(row.created_at), _when(newest.timestamp)
    if created is None or read is None or read <= created:
        return False
    credits = (newest.payload or {}).get("credits")
    if isinstance(credits, bool) or not isinstance(credits, int | float):
        return False
    return float(credits) >= float(params.get("credits") or 0)
