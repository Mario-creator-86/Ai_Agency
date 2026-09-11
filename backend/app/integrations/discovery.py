"""Account inventory refresh. Authentication, API facts, and research facts are independent.

One discovery path serves every connection whose inventory is read from the vendor
(`DISCOVERED_KINDS`): the key is verified, the account's models (and voices, where the vendor
has them) are written to `ProviderResource`, and production chooses among them. Only the
adapter and the Owner-facing wording differ per kind.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session

from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderDiscovery,
    ProviderResource,
)
from app.integrations.vault import CredentialVault
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import MediaProviderError
from app.providers.runway import VIDEO_TASKS, RunwayVideoAdapter
from app.services import append_event, utc_now

logger = logging.getLogger("studio.provider_discovery")

#: Connections whose account inventory is read from the vendor after the key is saved. The
#: values are what the Settings card shows; nothing here names a model or a voice.
DISCOVERED_KINDS: dict[str, dict[str, Any]] = {
    "elevenlabs": {
        "label": "ElevenLabs",
        "title": "Configurație de producție · ElevenLabs",
        "model_label": "Model implicit",
        "voice_label": "Voce implicită",
        "has_voices": True,
        "refresh_label": "Actualizează modelele și vocile",
        "syncing": "Se încarcă modelele și vocile…",
        "verify_hint": "Verifică cheia pentru a alege modelul și vocea de producție.",
        "select_hint": "Alege apoi această conexiune pentru Voce / TTS în serviciile de "
        "producție. Autentificarea rămâne verificată independent de selecții.",
        "unusable": "indisponibil pentru TTS",
    },
    "runway": {
        "label": "Runway",
        "title": "Configurație de producție · Runway",
        "model_label": "Model video implicit",
        "voice_label": None,
        "has_voices": False,
        "refresh_label": "Actualizează modelele video",
        "syncing": "Se încarcă modelele video…",
        "verify_hint": "Verifică cheia pentru a alege modelul video implicit.",
        "select_hint": "Alege apoi această conexiune pentru Video în serviciile de producție. "
        "Modelul implicit este doar o rezervă: producția poate alege alt model video "
        "descoperit, per video sau per scenă, după politica fiecărui canal.",
        "unusable": "nu generează video",
    },
}

#: What the Owner can do about each vendor error identifier. Keys are ElevenLabs'
#: `detail.status` values; the text never repeats the vendor's message or the key.
PERMISSIONS_HINT = (
    "În ElevenLabs → Developers → API Keys, editează cheia și acordă-i: User (Read), "
    "Models (Read), Voices (Read) și Text to Speech, apoi apasă „Verifică accesul”."
)
KEY_ERRORS = {
    "missing_permissions": "Cheia ElevenLabs este validă, dar a fost creată cu permisiuni "
    "restrânse. " + PERMISSIONS_HINT,
    "invalid_api_key": "Cheia ElevenLabs este invalidă sau a fost revocată. Generează o cheie "
    "nouă în ElevenLabs → Developers → API Keys și salveaz-o din nou.",
    "quota_exceeded": "Contul ElevenLabs nu mai are credit pentru cererea de verificare. "
    "Verifică abonamentul, apoi reîncearcă.",
    "too_many_concurrent_requests": "ElevenLabs limitează cererile acestui cont chiar acum. "
    "Reîncearcă peste câteva minute.",
}
#: Runway keys carry no permission scopes: a key either belongs to an organization or it does
#: not, so the only specific messages are about the key itself and the organization's access.
RUNWAY_KEY_ERRORS = {
    401: "Cheia Runway este invalidă sau a fost revocată. Generează o cheie nouă în "
    "Runway → Developer Portal → API Keys și salveaz-o din nou.",
    403: "Cheia Runway nu are acces la organizație. Verifică în Runway → Developer Portal "
    "că organizația cheii este activă și are credit, apoi apasă „Verifică accesul”.",
    429: "Runway limitează cererile acestui cont chiar acum. Reîncearcă peste câteva minute.",
}


def explain_key_error(exc: BaseException, authenticated: bool, kind: str = "elevenlabs") -> str:
    """An Owner-facing message for a failed refresh: specific when the vendor said why."""
    code = getattr(exc, "code", None)
    http_status = getattr(exc, "http_status", None)
    label = DISCOVERED_KINDS.get(kind, {}).get("label", kind)
    if kind == "runway":
        if authenticated:
            return (
                "Cheia a fost verificată, dar lista de modele nu a putut fi încărcată. "
                "Reîncearcă actualizarea catalogului."
            )
        if http_status in RUNWAY_KEY_ERRORS:
            return RUNWAY_KEY_ERRORS[http_status]
        if http_status is not None:
            return (
                f"Runway a refuzat verificarea (HTTP {http_status}). "
                "Verifică cheia și accesul organizației la API-ul Runway."
            )
        return "Cheia nu a putut fi verificată. Verifică cheia și accesul la Runway."
    if authenticated:
        if code == "missing_permissions":
            return (
                "Cheia a fost verificată, dar nu are permisiunile Models (Read) și Voices "
                "(Read), așa că listele nu au putut fi încărcate. " + PERMISSIONS_HINT
            )
        return (
            "Cheia a fost verificată, dar listele nu au putut fi încărcate. "
            "Verifică permisiunile Models/Voices și reîncearcă."
        )
    if code in KEY_ERRORS:
        return KEY_ERRORS[code]
    if http_status == 401:
        return KEY_ERRORS["invalid_api_key"]
    if http_status is not None:
        return (
            f"{label} a refuzat verificarea (HTTP {http_status}). "
            f"Verifică cheia, permisiunea User și accesul la {label}."
        )
    return (
        f"Cheia nu a putut fi verificată. Verifică cheia, permisiunea User și accesul la {label}."
    )


def discovery_adapter(kind: str, key: str) -> ElevenLabsTTSAdapter | RunwayVideoAdapter:
    if kind == "elevenlabs":
        return ElevenLabsTTSAdapter(key)
    if kind == "runway":
        return RunwayVideoAdapter(key)
    raise ValueError("Conexiunea nu are un catalog de resurse")


def model_usable(kind: str, resource: ProviderResource) -> bool:
    """Whether a discovered MODEL can serve the purpose this kind of connection is for.

    API evidence decides what a model can do; research (`capabilities`) may only restrict.
    """
    meta = resource.api_metadata if isinstance(resource.api_metadata, dict) else {}
    caps = resource.capabilities if isinstance(resource.capabilities, dict) else {}
    if kind == "elevenlabs":
        return (
            meta.get("can_do_text_to_speech") is True
            and caps.get("can_do_text_to_speech") is not False
        )
    if kind == "runway":
        tasks = meta.get("tasks")
        if not isinstance(tasks, list):
            # The contract could not be read at refresh time; research may fill the gap.
            tasks = caps.get("tasks")
        if not isinstance(tasks, list):
            return False
        return (
            any(task in VIDEO_TASKS for task in tasks)
            and caps.get("can_generate_video") is not False
        )
    return True


def reset_discovery(session: Session, identifier: str) -> None:
    state = session.get(ProviderDiscovery, identifier)
    if state is None:
        state = ProviderDiscovery(integration_id=identifier)
        session.add(state)
    state.status, state.next_refresh_at = "EMPTY", utc_now()
    state.lease_token = state.lease_until = state.last_error = None
    state.last_success_at = None
    for resource in session.scalars(
        select(ProviderResource).where(ProviderResource.integration_id == identifier)
    ):
        resource.api_available = False


def resource_available(resource: ProviderResource) -> bool:
    # Research may restrict use, but cannot make an API-absent resource exist.
    return resource.api_available and resource.availability_override is not False


def resource_view(row: ProviderResource, kind: str) -> dict:
    usable = resource_available(row) and (row.resource_type != "MODEL" or model_usable(kind, row))
    return dict(
        id=row.id,
        remote_id=row.remote_id,
        name=row.name,
        resource_type=row.resource_type,
        available=resource_available(row),
        production_usable=usable,
        api_available=row.api_available,
        api_metadata=row.api_metadata,
        last_seen_at=row.last_seen_at,
        pricing=row.pricing,
        capabilities=row.capabilities,
        availability_override=row.availability_override,
        metadata_source=row.metadata_source,
        metadata_updated_at=row.metadata_updated_at,
        metadata_version=row.metadata_version,
    )


def catalog_view(session: Session, identifier: str) -> dict:
    integration = session.get(Integration, identifier)
    kind = integration.kind if integration else ""
    state = session.get(ProviderDiscovery, identifier)
    production = session.get(MediaProductionConfig, identifier)
    resources = session.scalars(
        select(ProviderResource)
        .where(ProviderResource.integration_id == identifier)
        .order_by(ProviderResource.name, ProviderResource.remote_id)
    ).all()
    return dict(
        kind_info=dict(DISCOVERED_KINDS.get(kind, {})),
        models=[resource_view(r, kind) for r in resources if r.resource_type == "MODEL"],
        voices=[resource_view(r, kind) for r in resources if r.resource_type == "VOICE"],
        discovery=dict(
            status=state.status,
            last_success_at=state.last_success_at,
            next_refresh_at=state.next_refresh_at,
            last_error=state.last_error,
        )
        if state
        else None,
        # The connection's model/voice are the Organization default: a fallback for production,
        # not a rule, unless allow_production_override is switched off.
        production=dict(
            model_id=production.model_id,
            voice_id=production.voice_id,
            allow_production_override=bool(production.allow_production_override),
            version=production.version,
        )
        if production
        else dict(model_id=None, voice_id=None, allow_production_override=True, version=0),
    )


def _metadata(item: dict, resource_type: str, kind: str = "elevenlabs") -> dict:
    # Only public catalog fields; voice samples, verification recordings and account data stay out.
    if kind == "runway":
        fields: tuple[str, ...] = (
            "max_concurrent_generations",
            "max_daily_generations",
            "daily_generations",
            "tasks",
            "ratios",
            "durations",
        )
        return {field: item[field] for field in fields if field in item}
    fields = (
        (
            "description",
            "can_do_text_to_speech",
            "can_do_voice_conversion",
            "can_be_finetuned",
            "can_use_style",
            "can_use_speaker_boost",
            "serves_pro_voices",
            "requires_alpha_access",
            "maximum_text_length_per_request",
            "languages",
            "model_rates",
            "token_cost_factor",
        )
        if resource_type == "MODEL"
        else (
            "category",
            "description",
            "labels",
            "high_quality_base_model_ids",
            "is_owner",
            "is_legacy",
        )
    )
    return {field: item[field] for field in fields if field in item}


def refresh_catalog(
    engine: Engine,
    vault: CredentialVault,
    identifier: str,
    *,
    interval_seconds: int,
    retry_seconds: int,
    force: bool = False,
) -> dict:
    now = datetime.now(UTC)
    lease = str(uuid4())
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        if row is None or row.kind not in DISCOVERED_KINDS:
            raise ValueError("Conexiunea nu are un catalog de resurse")
        kind, version = row.kind, row.version
        state = session.get(ProviderDiscovery, identifier)
        if state is None:
            reset_discovery(session, identifier)
            session.flush()
        conditions = [
            ProviderDiscovery.integration_id == identifier,
            or_(
                ProviderDiscovery.lease_until.is_(None),
                ProviderDiscovery.lease_until <= now.isoformat(),
            ),
        ]
        if not force:
            conditions.append(ProviderDiscovery.next_refresh_at <= now.isoformat())
        # Short durable lease serializes manual/periodic refresh, including across server processes.
        claimed = session.execute(
            update(ProviderDiscovery)
            .where(*conditions)
            .values(
                status="SYNCING",
                lease_token=lease,
                lease_until=(now + timedelta(minutes=10)).isoformat(),
                last_attempt_at=now.isoformat(),
            )
        )
        if not claimed.rowcount:  # type: ignore[attr-defined]
            return {
                "status": row.status,
                "message": "Catalogul este actual sau se actualizează deja.",
            }
        key = vault.decrypt(row.encrypted_secrets).get("api_key", "")

    authenticated = False
    models: list[dict] = []
    voices: list[dict] = []
    error = None
    warning = None
    has_voices = bool(DISCOVERED_KINDS[kind]["has_voices"])
    try:
        adapter = discovery_adapter(kind, key)
        health = asyncio.run(adapter.health_check())
        if health["status"] != "HEALTHY":
            raise MediaProviderError(
                "Credential verification failed",
                code=health.get("code"),
                http_status=health.get("http_status"),
            )
        authenticated = True
        models = asyncio.run(adapter.list_models())
        voices = (
            asyncio.run(adapter.list_voices())
            if has_voices and isinstance(adapter, ElevenLabsTTSAdapter)
            else []
        )
        warning = getattr(adapter, "capabilities_warning", None)
    except Exception as exc:
        # Vendor message text and credential values never become UI/log strings; the vendor's
        # short error identifier does, because it is what tells the Owner what to fix.
        logger.warning(
            "provider_discovery_failed",
            extra={
                "error_class": type(exc).__name__,
                "vendor_code": getattr(exc, "code", None),
                "http_status": getattr(exc, "http_status", None),
            },
        )
        error = explain_key_error(exc, authenticated, kind)

    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        state = session.get(ProviderDiscovery, identifier)
        if row is None or row.version != version or state is None or state.lease_token != lease:
            raise ValueError("Conexiunea s-a schimbat în timpul verificării; reîncarcă setările")
        row.status, row.checked_at = ("VERIFIED" if authenticated else "FAILED"), utc_now()
        row.version += 1
        state.status, state.last_error = ("ERROR" if error else "READY"), error
        state.lease_token = state.lease_until = None
        state.next_refresh_at = (
            datetime.now(UTC) + timedelta(seconds=retry_seconds if error else interval_seconds)
        ).isoformat()
        if error is None:
            existing = {
                (r.resource_type, r.remote_id): r
                for r in session.scalars(
                    select(ProviderResource).where(ProviderResource.integration_id == identifier)
                )
            }
            for stale in existing.values():
                stale.api_available = False
            for resource_type, items, id_field in (
                ("MODEL", models, "model_id"),
                ("VOICE", voices, "voice_id"),
            ):
                for item in items:
                    remote_id = item[id_field]
                    resource = existing.get((resource_type, remote_id))
                    if resource is None:
                        resource = ProviderResource(
                            id=str(uuid4()),
                            integration_id=identifier,
                            resource_type=resource_type,
                            remote_id=remote_id,
                        )
                        session.add(resource)
                        existing[(resource_type, remote_id)] = resource
                    resource.name = str(item.get("name") or remote_id)[:300]
                    resource.api_metadata = _metadata(item, resource_type, kind)
                    resource.api_available, resource.last_seen_at = True, utc_now()
            state.last_success_at = utc_now()
        event = append_event(
            session,
            "provider.catalog_refreshed",
            "integration",
            identifier,
            row.version,
            {
                "status": row.status,
                "discovery_status": state.status,
                "models": len(models) if not error else None,
                "voices": len(voices) if not error else None,
            },
            str(uuid4()),
        )
        row.event_id = event.event_id
        loaded = (
            f"{len(models)} modele și {len(voices)} voci încărcate."
            if has_voices
            else f"{len(models)} modele încărcate."
        )
        return {
            "status": row.status,
            "discovery_status": state.status,
            "message": error or " ".join(filter(None, ["Conexiune verificată.", loaded, warning])),
        }


def refresh_due_catalogs(
    engine: Engine, vault: CredentialVault, *, interval_seconds: int, retry_seconds: int
) -> None:
    with Session(engine) as session:
        identifiers = session.scalars(
            select(Integration.id).where(Integration.kind.in_(tuple(DISCOVERED_KINDS)))
        ).all()
    for identifier in identifiers:
        try:
            refresh_catalog(
                engine,
                vault,
                identifier,
                interval_seconds=interval_seconds,
                retry_seconds=retry_seconds,
            )
        except Exception as exc:
            logger.warning(
                "provider_refresh_pass_failed", extra={"error_class": type(exc).__name__}
            )


class ProductionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    voice_id: str | None = Field(default=None, min_length=1, max_length=200)
    #: True: channels, series, episodes and scenes may choose differently (the default is a
    #: fallback). False: every video on this connection uses exactly this model and voice,
    #: except a character whose voice identity is locked.
    allow_production_override: bool = True
    expected_version: int = Field(ge=0)


def production_resource(
    session: Session, identifier: str, resource_type: str, remote_id: str | None
) -> ProviderResource | None:
    """A discovered, available resource production may use, or None.

    A MODEL must also serve the connection's purpose (a TTS model on ElevenLabs, a video
    model on Runway); the API's own evidence decides that, see `model_usable`.
    """
    resource = (
        session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == identifier,
                ProviderResource.resource_type == resource_type,
                ProviderResource.remote_id == remote_id,
            )
        )
        if remote_id
        else None
    )
    if resource is None or not resource_available(resource):
        return None
    if resource_type == "MODEL":
        integration = session.get(Integration, identifier)
        if integration is None or not model_usable(integration.kind, resource):
            return None
    return resource


def save_production(engine: Engine, identifier: str, command: ProductionCommand) -> dict:
    with Session(engine) as session, session.begin():
        integration = session.get(Integration, identifier)
        if integration is None or integration.kind not in DISCOVERED_KINDS:
            raise ValueError("Conexiunea nu are un catalog de resurse")
        if integration.status != "VERIFIED":
            raise ValueError("Verifică mai întâi conexiunea")
        has_voices = bool(DISCOVERED_KINDS[integration.kind]["has_voices"])
        if command.voice_id and not has_voices:
            raise ValueError("Această conexiune nu are voci; alege doar modelul implicit")
        for resource_type, value in (("MODEL", command.model_id), ("VOICE", command.voice_id)):
            if value and production_resource(session, identifier, resource_type, value) is None:
                raise ValueError(
                    "Alege un model TTS și o voce disponibile în catalogul acestui cont"
                    if has_voices
                    else "Alege un model video disponibil în catalogul acestui cont"
                )
        row = session.get(MediaProductionConfig, identifier)
        if (row.version if row else 0) != command.expected_version:
            raise ValueError("Configurația de producție s-a schimbat; reîncarcă")
        if row is None:
            row = MediaProductionConfig(integration_id=identifier)
            session.add(row)
        row.model_id, row.voice_id = command.model_id, command.voice_id
        row.allow_production_override = command.allow_production_override
        row.version, row.updated_at = command.expected_version + 1, utc_now()
        append_event(
            session,
            "media.production_configured",
            "integration",
            identifier,
            row.version,
            {
                "model_id": row.model_id,
                "voice_id": row.voice_id,
                "allow_production_override": row.allow_production_override,
            },
            str(uuid4()),
        )
        return {"saved": True, "version": row.version}


class ResourceMetadataCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    pricing: dict | None = None
    capabilities: dict | None = None
    availability_override: bool | None = None
    source: str = Field(min_length=1, max_length=2000)


def update_resource_metadata(
    engine: Engine, identifier: str, command: ResourceMetadataCommand
) -> dict:
    """Research/Accounting entry point. Does not edit authentication or API evidence."""
    with Session(engine) as session, session.begin():
        row = session.get(ProviderResource, identifier)
        if row is None:
            raise ValueError("Resursă inexistentă")
        if row.metadata_version != command.expected_version:
            raise ValueError("Metadatele s-au schimbat; reîncarcă")
        for field in ("pricing", "capabilities", "availability_override"):
            if field in command.model_fields_set:
                setattr(
                    row,
                    field,
                    getattr(command, field)
                    if field == "availability_override"
                    else getattr(command, field) or {},
                )
        row.metadata_version += 1
        row.metadata_source, row.metadata_updated_at = command.source, utc_now()
        append_event(
            session,
            "provider.resource_metadata_updated",
            "provider_resource",
            identifier,
            row.metadata_version,
            {"source": command.source},
            str(uuid4()),
        )
        integration = session.get(Integration, row.integration_id)
        return resource_view(row, integration.kind if integration else "")
