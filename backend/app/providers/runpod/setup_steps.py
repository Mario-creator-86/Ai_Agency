"""The Owner's «RunPod pornit» switch and the read-only «Pașii configurării» checklist.

His card (2026-10-09): he no longer edits ``RUNPOD_ENABLED`` in ``.env``. The switch lives with
the RunPod integration (``config["enabled"]``, "true" / "false", an event per change), and the
effective value of ``RunPodConfig.enabled`` is the switch when set, else the environment's
``RUNPOD_ENABLED``, else false. Nothing needs a restart: every reader builds its config from
the integration row per call (`RunPodConfig.from_integration`, where the stored value is an
init argument and so beats the environment).

* **ON** is the Owner's act (the router sits behind `require_owner`) and needs a VERIFIED
  connection; otherwise it is refused with his reason. It buys nothing: each paid step still
  asks his approval and his card «Agenții pot porni singuri GPU-ul RunPod …».
* **OFF** is always allowed and acts at once: the existing GPU off (`gpu_session.force_off`:
  purge, cancel, workers.max=0, verified) on the connection's endpoints, and a running copy pod
  is ended by the existing shutdown rule (`pods.watch_copies(reason="SHUTDOWN")`, a finished
  copy keeps its revisions).
* **The checklist** reads only. With ``fresh`` it GETs each endpoint's settings
  (``GET /v2/serverless/{id}``, no retry, a short timeout) and HEADs the bucket through a
  presigned URL; it never creates, PATCHes or POSTs, never starts a worker, never writes. The
  network rows of the last check are kept as an event (``runpod.setup_checked``) so a page that
  opens shows them without calling anything. Secrets are never returned: a key is «salvată» or
  «lipsește». Each row links to the exact console page (links only).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.integrations.models import Integration
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError, request
from app.providers.runpod import s3
from app.providers.runpod.client import Transport
from app.providers.runpod.config import RunPodConfig
from app.providers.runpod.endpoint import EndpointAccessDenied, EndpointControl, EndpointSettings

if TYPE_CHECKING:
    from app.integrations.vault import CredentialVault

#: Where the switch is stored in the integration's config (the RunPodConfig field it sets).
SWITCH_KEY = "enabled"
SWITCH_EVENT = "runpod.switch_changed"
CHECK_EVENT = "runpod.setup_checked"
#: The integration status a connection must have before the switch may go ON.
VERIFIED = "VERIFIED"
#: Each read of the checklist gets this long, and no retry: a press never hangs the page.
CHECK_TIMEOUT_SECONDS = 10.0

# The console pages each row links to (links only, never a secret).
RUNPOD_ACCOUNT_SETTINGS = "https://console.runpod.io/user/settings"
RUNPOD_SERVERLESS = "https://console.runpod.io/serverless"
RUNPOD_BILLING = "https://console.runpod.io/user/billing"
HF_TOKENS = "https://huggingface.co/settings/tokens"
HF_NEW_REPO = "https://huggingface.co/new"
LTX_GATE = "https://huggingface.co/Lightricks/LTX-2.5"
CLOUDFLARE_R2 = "https://dash.cloudflare.com/?to=/:account/r2/overview"
GITHUB_NEW = "https://github.com/new"
#: Every link a row may carry starts with one of these.
LINK_PREFIXES = (
    "https://console.runpod.io/",
    "https://huggingface.co/",
    "https://dash.cloudflare.com/",
    "https://github.com/",
)

Status = Literal["green", "red", "grey"]
#: The rows whose truth needs a read of RunPod or the bucket (kept from the last check).
NETWORK_ROWS = ("endpoint_stills", "endpoint_motion", "bucket")
PURPOSE_RO = {"image": "imagini", "video": "mișcare"}
NOT_CHECKED_RO = "Nu a fost verificat încă: apasă «Verifică pașii»."


class SwitchRefused(ValueError):
    """The switch could not be moved; ``reason_ro`` is his reason, ``status`` the HTTP code."""

    def __init__(self, reason_ro: str, status: int = 409) -> None:
        super().__init__(reason_ro)
        self.reason_ro = reason_ro
        self.status = status


def _row(
    key: str, title_ro: str, status: Status, words_ro: str, link: str | None, link_ro: str | None
) -> dict[str, Any]:
    return {
        "key": key,
        "title_ro": title_ro,
        "status": status,
        "words_ro": words_ro,
        "link": link,
        "link_ro": link_ro if link else None,
    }


def _integration(session: Session, integration_id: str) -> Integration:
    row = session.get(Integration, integration_id)
    if row is None or row.kind != "runpod":
        raise SwitchRefused("Conexiunea RunPod nu există.", status=404)
    return row


def _stored(config: Mapping[str, Any]) -> bool | None:
    value = str(config.get(SWITCH_KEY, "")).strip().lower()
    return {"true": True, "false": False}.get(value)


def _environment(config: Mapping[str, Any]) -> bool:
    """What RUNPOD_ENABLED (the environment or .env) says, the switch left out."""
    try:
        return RunPodConfig.from_integration(
            {k: v for k, v in config.items() if k != SWITCH_KEY}, {}
        ).enabled
    except ValueError:
        return False


def _state(row: Integration) -> dict[str, Any]:
    config = dict(row.config or {})
    stored = _stored(config)
    environment = _environment(config)
    on = environment if stored is None else stored
    verified = row.status == VERIFIED
    return {
        "integration_id": row.id,
        "on": on,
        "stored": stored,
        "environment": environment,
        "source": "environment" if stored is None else "switch",
        "verified": verified,
        "can_turn_on": verified,
        "why_not_ro": None if verified else _not_verified_ro(),
        "words_ro": _switch_words(on, stored is None),
    }


def _not_verified_ro() -> str:
    return (
        "Conexiunea RunPod nu este verificată. Apasă «Verifică API și modelele» pe cardul "
        "conexiunii și pornește din nou după ce scrie «Conexiune verificată»."
    )


def _switch_words(on: bool, from_environment: bool) -> str:
    where = " (din RUNPOD_ENABLED, până apeși comutatorul)" if from_environment else ""
    if on:
        return (
            "RunPod pornit" + where + ": pașii plătiți aprobați pot porni GPU-ul, "
            "fiecare cu aprobarea ta."
        )
    return "RunPod oprit" + where + ": niciun pas nu poate porni GPU-ul RunPod."


def switch_state(engine: Engine, integration_id: str) -> dict[str, Any]:
    """The switch as the page shows it: the effective value and where it comes from."""
    with Session(engine) as session:
        return _state(_integration(session, integration_id))


def set_switch(
    engine: Engine,
    vault: CredentialVault,
    integration_id: str,
    *,
    on: bool,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Move the switch (the Owner's act). ON needs a VERIFIED connection; OFF always works and
    switches the GPU off now. Raises `SwitchRefused` with his reason."""
    from app.services import append_event  # noqa: PLC0415 - services imports providers

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        row = _integration(session, integration_id)
        before = _state(row)
        if on and row.status != VERIFIED:
            raise SwitchRefused(_not_verified_ro())
        row.config = {**dict(row.config or {}), SWITCH_KEY: "true" if on else "false"}
        row.version += 1
        append_event(
            session,
            SWITCH_EVENT,
            "integration",
            row.id,
            row.version,
            {"integration_id": row.id, "on": on, "before": before["on"], "by": "owner"},
            str(uuid4()),
        )
    answer: dict[str, Any] = {**switch_state(engine, integration_id), "readings": []}
    if not on:
        answer["readings"] = _switch_off(engine, vault, integration_id, transport)
        verified = bool(answer["readings"]) and all(r["off"] for r in answer["readings"])
        answer["words_ro"] = (
            "RunPod oprit. GPU-ul este oprit și verificat."
            if verified
            else "RunPod oprit. Am trimis oprirea GPU-ului; paznicul o verifică din nou la fiecare "
            "minut."
            if answer["readings"]
            else "RunPod oprit. Nu era niciun GPU de oprit."
        )
    return answer


def _switch_off(
    engine: Engine, vault: CredentialVault, integration_id: str, transport: Transport | None
) -> list[dict[str, Any]]:
    from app.providers.runpod import pods  # noqa: PLC0415
    from app.providers.runpod.gpu_session import force_off  # noqa: PLC0415

    readings = [
        r.as_dict()
        for r in force_off(
            engine,
            vault,
            reason="OWNER_OFF",
            integration_ids=[integration_id],
            transport=transport,
        )
    ]
    try:
        # The existing shutdown rule: a running copy pod is terminated (results kept).
        pods.watch_copies(engine, vault, reason="SHUTDOWN", transport=transport)
    except Exception:  # noqa: BLE001 - the GPU's own off is never held back by the copy
        pass
    return readings


# ------------------------------------------------------------------------------ the checklist


def checklist(
    engine: Engine,
    vault: CredentialVault,
    integration_id: str,
    *,
    fresh: bool,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """«Pașii configurării»: one row per step of his path. ``fresh`` reads RunPod and the
    bucket (GET / HEAD only); otherwise the last check's network rows are shown."""
    from app.services import append_event, utc_now  # noqa: PLC0415 - services imports providers

    with Session(engine) as session:
        row = _integration(session, integration_id)
        state = _state(row)
        raw = dict(row.config or {})
        encrypted = row.encrypted_secrets
        cached = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == CHECK_EVENT, DomainEvent.aggregate_id == row.id)
            .order_by(DomainEvent.timestamp.desc())
            .limit(1)
        ).first()
        decisions = _decision_states(session, row.id)
        live_session = _live_gpu_session(session)
        version = row.version
    try:
        secrets = vault.decrypt(encrypted)
        unreadable = False
    except Exception:  # noqa: BLE001 - an unreadable vault is said, never raised
        secrets, unreadable = {}, True
    try:
        config: RunPodConfig | None = RunPodConfig.from_integration(raw, secrets)
    except ValueError:
        config = None
    checked_at = cached.timestamp if cached is not None else None
    network: dict[str, dict[str, Any]] = (
        dict(cached.payload.get("rows") or {}) if cached is not None else {}
    )
    if fresh and config is None:
        # Nothing can be read with an invalid connection; the rows say so instead of asking
        # for the check that was just pressed (not kept: the next valid check replaces it).
        invalid = {
            "status": "red",
            "words_ro": "Configurația conexiunii RunPod nu este validă, așa că nu am citit "
            "nimic; deschide «Modifică».",
        }
        network = {key: dict(invalid) for key in NETWORK_ROWS}
    elif fresh and config is not None:
        network = asyncio.run(_read(config, live_session, transport or request))
        checked_at = utc_now()
        with Session(engine) as session, session.begin():
            append_event(
                session,
                CHECK_EVENT,
                "integration",
                integration_id,
                version,
                {"rows": network},
                str(uuid4()),
            )
    rows = _rows(config, secrets, unreadable, network, decisions, state)
    return {
        "integration_id": integration_id,
        "checked_at": checked_at,
        "switch": state,
        "rows": rows,
    }


def _live_gpu_session(session: Session) -> bool:
    from app.providers.runpod.gpu_session import LIVE, GpuSessionRow  # noqa: PLC0415

    return (
        session.scalars(
            select(GpuSessionRow.id).where(GpuSessionRow.status.in_(LIVE)).limit(1)
        ).first()
        is not None
    )


def _decision_states(session: Session, integration_id: str) -> dict[str, str | None]:
    """The latest status of each of his RunPod cards (None: never proposed)."""
    from app.decisions.models import OwnerDecision  # noqa: PLC0415

    found: dict[str, str | None] = {"gpu": None, "copy": None, "bakeoff": None}
    cards = session.scalars(
        select(OwnerDecision)
        .where(OwnerDecision.kind.like("runpod_%"))
        .order_by(OwnerDecision.created_at)
    )
    for card in cards:
        if card.subject_id not in (None, integration_id):
            continue
        if card.kind == "runpod_infra_actions":
            found["gpu"] = card.status
        elif card.kind == "runpod_mirror_copy":
            found["copy"] = card.status
        elif card.kind.startswith("runpod_bake"):
            found["bakeoff"] = card.status
    return found


async def _read(
    config: RunPodConfig, live_session: bool, wire: Transport
) -> dict[str, dict[str, Any]]:
    readings = await asyncio.gather(
        _read_endpoint(config, "image", live_session, wire),
        _read_endpoint(config, "video", live_session, wire),
        _read_bucket(config, wire),
    )
    return dict(zip(NETWORK_ROWS, readings, strict=True))


def _api_key(config: RunPodConfig) -> bool:
    return bool(config.api_key.get_secret_value())


async def _read_endpoint(
    config: RunPodConfig, purpose: Literal["image", "video"], live_session: bool, wire: Transport
) -> dict[str, Any]:
    endpoint_id = config.endpoint_for(purpose)
    what = PURPOSE_RO[purpose]
    if not endpoint_id:
        return {"status": "red", "words_ro": f"Endpointul pentru {what} nu este salvat."}
    if not _api_key(config):
        return {
            "status": "red",
            "words_ro": f"Fără cheia API nu pot citi endpointul {endpoint_id}.",
        }
    control = EndpointControl(
        config, endpoint_id, wire, request_timeout=CHECK_TIMEOUT_SECONDS, retries=0
    )
    try:
        settings = await control.get()
    except EndpointAccessDenied as exc:
        return {
            "status": "red",
            "words_ro": f"Cheia RunPod nu are acces la endpointul {endpoint_id} "
            f"(HTTP {exc.http_status}); pune o cheie cu acces la Serverless.",
        }
    except MediaProviderError as exc:
        if exc.http_status == 404:
            words = f"Endpointul {endpoint_id} nu există în contul tău RunPod."
        else:
            words = f"Endpointul {endpoint_id} nu a putut fi citit acum; încearcă din nou."
        return {"status": "red", "words_ro": words}
    except Exception:  # noqa: BLE001 - a protocol surprise is a red row, never a crash
        return {
            "status": "red",
            "words_ro": f"Răspunsul pentru endpointul {endpoint_id} nu a putut fi înțeles.",
        }
    problems = _drift(settings, config, live_session)
    if problems:
        return {
            "status": "red",
            "words_ro": f"Endpointul {endpoint_id} are alte setări decât trebuie: "
            + "; ".join(problems)
            + ". Le corectezi în consola RunPod (Manage → Edit Endpoint).",
        }
    return {
        "status": "green",
        "words_ro": f"Endpointul {endpoint_id} se citește și are setările cerute "
        f"({_read_words(settings)}).",
    }


def _read_words(settings: EndpointSettings) -> str:
    """What RunPod actually answered (a field it left out is said, never assumed)."""
    missing = "nu apare în răspunsul RunPod"
    return ", ".join(
        (
            f"workers min {settings.workers_min}, max {settings.workers_max}",
            f"idleTimeout {settings.idle_timeout} s"
            if settings.idle_timeout is not None
            else f"idleTimeout {missing}",
            settings.flashboot if settings.flashboot is not None else f"flashboot {missing}",
            f"timeout {settings.timeout_ms} ms"
            if settings.timeout_ms is not None
            else f"timeout {missing}",
        )
    )


def _drift(settings: EndpointSettings, config: RunPodConfig, live_session: bool) -> list[str]:
    problems: list[str] = []
    if settings.workers_min != 0:
        problems.append(f"workers min este {settings.workers_min}, trebuie 0")
    allowed_max = config.max_workers if live_session else 0
    if settings.workers_max > allowed_max:
        problems.append(
            f"workers max este {settings.workers_max}, trebuie 0 când nu rulează un pas plătit"
        )
    if settings.idle_timeout is not None and settings.idle_timeout != config.idle_timeout_seconds:
        problems.append(
            f"idleTimeout este {settings.idle_timeout} s, trebuie {config.idle_timeout_seconds} s"
        )
    if settings.flashboot is not None and settings.flashboot != config.flashboot:
        problems.append(f"flashboot este {settings.flashboot}, trebuie {config.flashboot}")
    if settings.timeout_ms is not None and settings.timeout_ms != config.endpoint_timeout_ms:
        problems.append(
            f"timeout este {settings.timeout_ms} ms, trebuie {config.endpoint_timeout_ms} ms"
        )
    return problems


async def _read_bucket(config: RunPodConfig, wire: Transport) -> dict[str, Any]:
    bucket = config.bucket()
    if bucket is None:
        return {
            "status": "red",
            "words_ro": "Bucketul de rezultate nu este complet: adresa, numele și cele două "
            "chei ale lui trebuie salvate.",
        }
    host = urlsplit(bucket.endpoint_url).hostname or ""
    url = s3.presign_url(
        host=host,
        path="/" + bucket.bucket,
        method="HEAD",
        region=bucket.region,
        access_key_id=bucket.access_key_id,
        secret_access_key=bucket.secret_access_key.get_secret_value(),
        expires=300,
    )
    parts = urlsplit(url)
    try:
        await asyncio.to_thread(
            wire,
            host,
            "HEAD",
            parts.path + "?" + parts.query,
            {},
            None,
            timeout=CHECK_TIMEOUT_SECONDS,
            total_seconds=CHECK_TIMEOUT_SECONDS,
            expect_json=False,
            allowed_statuses=(200,),
        )
    except MediaProviderError as exc:
        if exc.http_status in (401, 403):
            words = (
                f"Bucketul «{bucket.bucket}» refuză cheile salvate (HTTP {exc.http_status}); "
                "verifică cheia de acces și cheia secretă."
            )
        elif exc.http_status == 404:
            words = f"Bucketul «{bucket.bucket}» nu există la adresa salvată (HTTP 404)."
        else:
            words = f"Bucketul «{bucket.bucket}» nu a răspuns acum; încearcă din nou."
        return {"status": "red", "words_ro": words}
    except Exception:  # noqa: BLE001 - an unreachable bucket is a red row
        return {"status": "red", "words_ro": f"Bucketul «{bucket.bucket}» nu a putut fi citit."}
    return {
        "status": "green",
        "words_ro": f"Bucketul «{bucket.bucket}» răspunde cu cheile salvate (doar citit, "
        "nimic scris).",
    }


def _endpoint_link(endpoint_id: str | None) -> str:
    if not endpoint_id:
        return RUNPOD_SERVERLESS
    return RUNPOD_SERVERLESS + "/user/endpoint/" + quote(endpoint_id, safe="")


def _rows(
    config: RunPodConfig | None,
    secrets: Mapping[str, str],
    unreadable: bool,
    network: Mapping[str, Mapping[str, Any]],
    decisions: Mapping[str, str | None],
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from app.decisions.models import OPEN_STATUSES  # noqa: PLC0415
    from app.providers.runpod.weights import expected_weights  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    if unreadable:
        key_words = "Cheile salvate nu pot fi citite din seif; scrie-le din nou în formular."
    elif secrets.get("api_key"):
        key_words = "Cheia API RunPod este salvată."
    else:
        key_words = "Cheia API RunPod lipsește: creeaz-o în consola RunPod și pune-o în formular."
    rows.append(
        _row(
            "api_key",
            "Cheia API RunPod",
            "green" if secrets.get("api_key") else "red",
            key_words,
            RUNPOD_ACCOUNT_SETTINGS,
            "Consola RunPod → API Keys",
        )
    )
    stills = config.endpoint_for("image") if config else None
    motion = config.endpoint_for("video") if config else None
    if config is None:
        ids_status: Status = "red"
        ids_words = "Configurația conexiunii RunPod nu este validă; deschide «Modifică»."
    elif stills and motion:
        ids_status, ids_words = "green", "Endpointurile pentru imagini și mișcare sunt salvate."
    else:
        missing = " și ".join(
            what for what, value in (("imagini", stills), ("mișcare", motion)) if not value
        )
        ids_status, ids_words = "red", f"Lipsește ID-ul endpointului pentru {missing}."
    rows.append(
        _row(
            "endpoint_ids",
            "ID-urile endpointurilor",
            ids_status,
            ids_words,
            RUNPOD_SERVERLESS,
            "Consola RunPod → Serverless",
        )
    )
    for key, purpose, endpoint_id in (
        ("endpoint_stills", "image", stills),
        ("endpoint_motion", "video", motion),
    ):
        reading = network.get(key)
        rows.append(
            _row(
                key,
                f"Endpointul pentru {PURPOSE_RO[purpose]}",
                reading["status"] if reading else "grey",
                str(reading["words_ro"]) if reading else NOT_CHECKED_RO,
                _endpoint_link(endpoint_id),
                # Without an id the link is the endpoint list, and its words say so.
                "Consola RunPod → endpointul" if endpoint_id else "Consola RunPod → Serverless",
            )
        )
    rows.append(
        _row(
            "cached_model",
            "Modelul din cache (câmpul Model)",
            "grey",
            "Nu se poate citi prin API: se verifică la primul rezultat (weights_revision).",
            _endpoint_link(stills or motion),
            "Consola RunPod → Edit Endpoint → Model",
        )
    )
    bucket = network.get("bucket")
    rows.append(
        _row(
            "bucket",
            "Bucketul de rezultate",
            bucket["status"] if bucket else "grey",
            str(bucket["words_ro"]) if bucket else NOT_CHECKED_RO,
            CLOUDFLARE_R2,
            "Cloudflare → R2",
        )
    )
    rows.append(
        _row(
            "hf_token",
            "Tokenul Hugging Face",
            "green" if secrets.get("hf_token") else "red",
            "Tokenul Hugging Face este salvat."
            if secrets.get("hf_token")
            else "Tokenul Hugging Face (scriere în cele două copii) lipsește.",
            HF_TOKENS,
            "Hugging Face → Access Tokens",
        )
    )
    rows.append(
        _row(
            "ltx_licence",
            "Licența LTX-2.5",
            "grey",
            "Licența se acceptă din contul tău Hugging Face; studioul nu o poate citi încă. "
            "Copia modelelor o confirmă.",
            LTX_GATE,
            "Hugging Face → LTX-2.5",
        )
    )
    repos = {
        purpose: expected_weights(config, purpose) if config else (None, None)  # type: ignore[arg-type]
        for purpose in ("image", "video")
    }
    named = [p for p in ("image", "video") if repos[p][0]]
    rows.append(
        _row(
            "mirror_repos",
            "Copiile tale private pe Hugging Face",
            "green" if len(named) == 2 else "red",
            "Ambele copii sunt numite: " + ", ".join(str(repos[p][0]) for p in named) + "."
            if len(named) == 2
            else "Lipsește numele copiei pentru "
            + " și ".join(PURPOSE_RO[p] for p in ("image", "video") if p not in named)
            + " (cont/nume).",
            f"https://huggingface.co/{repos['image'][0]}" if repos["image"][0] else HF_NEW_REPO,
            "Hugging Face → copia",
        )
    )
    pinned = [p for p in ("image", "video") if repos[p][1]]
    rows.append(
        _row(
            "mirror_revisions",
            "Reviziile copiilor (commit)",
            "green" if len(pinned) == 2 else "red",
            "Ambele revizii sunt fixate."
            if len(pinned) == 2
            else "Lipsește revizia pentru "
            + " și ".join(PURPOSE_RO[p] for p in ("image", "video") if p not in pinned)
            + "; o scrie copia modelelor când reușește.",
            f"https://huggingface.co/{repos['video'][0]}/commits/main"
            if repos["video"][0]
            else HF_NEW_REPO,
            "Hugging Face → istoricul copiei",
        )
    )
    allowed = bool(config and config.allow_infra_actions)
    gpu_card = decisions.get("gpu")
    rows.append(
        _decision_row(
            "decision_gpu",
            "Cardul «Agenții pot porni GPU-ul»",
            "green"
            if allowed or (gpu_card and gpu_card not in OPEN_STATUSES)
            else "red"
            if gpu_card in OPEN_STATUSES
            else "grey",
            "Ai răspuns la card." if allowed or gpu_card else None,
            gpu_card in OPEN_STATUSES,
        )
    )
    copy_card = decisions.get("copy")
    copy_done = len(pinned) == 2
    rows.append(
        _decision_row(
            "decision_copy",
            "Cardul «Copiez modelele»",
            "green"
            if copy_done or (copy_card and copy_card not in OPEN_STATUSES)
            else "red"
            if copy_card in OPEN_STATUSES
            else "grey",
            "Copia este făcută." if copy_done else "Ai răspuns la card." if copy_card else None,
            copy_card in OPEN_STATUSES,
        )
    )
    bake = decisions.get("bakeoff")
    rows.append(
        _decision_row(
            "decision_bakeoff",
            "Cardul pentru testul plătit (bake-off)",
            "green" if bake and bake not in OPEN_STATUSES else "red" if bake else "grey",
            "Ai răspuns la card." if bake else None,
            bake in OPEN_STATUSES,
            not_yet_ro="Cardul pentru testul plătit nu există încă; vine după pașii de mai sus.",
        )
    )
    rows.append(
        _row(
            "worker_repo",
            "Depozitul GitHub al workerului",
            "grey",
            "Studioul nu citește GitHub: creezi un depozit privat gol, apoi urmezi "
            "PUSH_ME.txt din E:\\amn-runpod-worker.",
            GITHUB_NEW,
            "GitHub → depozit nou",
        )
    )
    rows.append(
        _row(
            "billing",
            "Soldul RunPod",
            "grey",
            "Soldul nu se poate citi prin API încă; îl vezi în consola RunPod.",
            RUNPOD_BILLING,
            "Consola RunPod → Billing",
        )
    )
    rows.append(
        _row(
            "switch",
            "Comutatorul «RunPod pornit»",
            "green" if state["on"] else "red",
            str(state["words_ro"]),
            None,
            None,
        )
    )
    return rows


def _decision_row(
    key: str,
    title_ro: str,
    status: Status,
    done_ro: str | None,
    pending: bool,
    *,
    not_yet_ro: str = "Cardul nu a fost propus încă; apare în «Decizii» când e nevoie de el.",
) -> dict[str, Any]:
    if pending:
        words = "Cardul așteaptă răspunsul tău în fereastra «Decizii»."
    elif status == "green" and done_ro:
        words = done_ro
    else:
        words = not_yet_ro
    return _row(key, title_ro, status, words, None, None)
