import logging
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.economy.prices import price_lookup
from app.integrations.catalog import CATALOG
from app.integrations.discovery import DISCOVERED_KINDS, reset_discovery
from app.integrations.llm import ConfiguredLLM
from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import (
    RECONNECT_RO,
    VAULT_MISSING,
    VAULT_REASONS_RO,
    CredentialVault,
    VaultUnreadable,
)
from app.models import DomainEvent
from app.providers.registry import ProviderRegistry
from app.providers.youtube import YouTubeProvider
from app.services import append_event, utc_now
from app.wording import SETTINGS_TABS


class SaveIntegration(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    kind: str = Field(max_length=40)
    name: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(default=0, ge=0)
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, SecretStr] = Field(default_factory=dict)


def public(row: Integration) -> dict:
    return dict(
        id=row.id,
        kind=row.kind,
        name=row.name,
        config=row.config,
        secret_fields=row.secret_fields,
        version=row.version,
        status=row.status,
        checked_at=row.checked_at,
        runtime=CATALOG.get(row.kind, {}).get("runtime", "unavailable"),
    )


def validate(kind: str, config: dict, secrets: dict) -> None:
    if kind == "runpod":
        from app.providers.runpod.config import RunPodConfig  # noqa: PLC0415

        # The form's values and the vault's keys (API key, bucket keys) together; an invalid
        # value the form typed is refused here, an old .env never is (`from_integration`).
        RunPodConfig.from_integration(config, secrets)
    if kind == "comfyui":
        from app.providers.comfyui import local_url  # noqa: PLC0415

        local_url(str(config.get("base_url", "")))
    spec = CATALOG.get(kind)
    if not spec:
        raise ValueError("Serviciu necunoscut")
    fields = {f["key"]: f for f in spec["fields"]}
    if any(k not in fields or fields[k]["secret"] for k in config):
        raise ValueError("Câmp de configurare nepermis")
    if any(k not in fields or not fields[k]["secret"] for k in secrets):
        raise ValueError("Câmp secret nepermis")
    for field in fields.values():
        value = (secrets if field["secret"] else config).get(field["key"], "")
        if field["required"] and not value.strip():
            raise ValueError("Lipsește câmpul: " + field["label"])
        if len(value) > (8192 if field["secret"] else 500):
            raise ValueError("Valoare prea lungă: " + field["label"])
        if value and ("\n" in value or "\r" in value or "\x00" in value):
            raise ValueError("Valoare invalidă: " + field["label"])
        if value and field["choices"] and value not in field["choices"]:
            raise ValueError("Opțiune invalidă: " + field["label"])
        if (
            value
            and field["kind"] == "number"
            and not (value.isdigit() and 1 <= int(value) <= 65535)
        ):
            raise ValueError("Port invalid")
        if (
            value
            and field["kind"] == "email"
            and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
        ):
            raise ValueError("Adresă e-mail invalidă")
        if value and field["kind"] == "url":
            parsed = urlsplit(value)
            local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.scheme not in ("http", "https")
                or (parsed.scheme == "http" and not local)
            ):
                raise ValueError("Folosește HTTPS sau o adresă HTTP locală, fără token în URL")
    if kind == "email" and bool(config.get("imap_host")) != bool(config.get("imap_port")):
        raise ValueError("Completează împreună serverul și portul IMAP")


def save(engine: Engine, vault: CredentialVault, identifier: str, command: SaveIntegration) -> dict:
    if not command.name.strip():
        raise ValueError("Numele conexiunii este obligatoriu")
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        if (row.version if row else 0) != command.expected_version:
            raise ValueError("Conflict de versiune; reîncarcă setările")
        if row and row.kind != command.kind:
            raise ValueError("Tipul unei conexiuni existente nu poate fi schimbat")
        try:
            secrets = vault.decrypt(row.encrypted_secrets) if row else {}
        except VaultUnreadable:
            # Keys that cannot be read are lost (REL-06): the Owner reconnects by typing them
            # again, and the required fields he leaves empty are asked for by `validate`.
            secrets = {}
        for key, value in command.secrets.items():
            if value.get_secret_value():
                secrets[key] = value.get_secret_value()
        validate(command.kind, command.config, secrets)
        version = command.expected_version + 1
        event = append_event(
            session,
            "settings.integration_saved",
            "integration",
            identifier,
            version,
            {"kind": command.kind},
            str(uuid4()),
        )
        if row is None:
            row = Integration(id=identifier)
            session.add(row)
        try:
            encrypted = vault.encrypt(secrets)
        except VaultUnreadable as exc:
            raise ValueError(
                f"{exc.reason_ro}. Conexiunea nu poate fi salvată până când fișierul cheii "
                f"({vault.path.name}) nu este mutat deoparte; apoi {RECONNECT_RO}."
            ) from None
        row.kind, row.name = command.kind, command.name.strip()
        stored = dict(command.config)
        if command.kind == "runpod" and isinstance(row.config, dict):
            # His answer on the card «Agenții pot porni singuri GPU-ul RunPod …» is not a form
            # field: a save of the form keeps it (`decisions.sources.apply_runpod_infra`).
            if "allow_infra_actions" in row.config:
                stored["allow_infra_actions"] = row.config["allow_infra_actions"]
            # Nor is his switch «RunPod pornit» (`providers.runpod.setup`): a save keeps it.
            if "enabled" in row.config:
                stored["enabled"] = row.config["enabled"]
        row.config, row.encrypted_secrets = stored, encrypted
        row.secret_fields, row.version = sorted(secrets), version
        row.status, row.checked_at, row.event_id = "SAVED", None, event.event_id
        if row.kind in DISCOVERED_KINDS:
            session.flush()
            reset_discovery(session, identifier)
        if CATALOG[row.kind]["runtime"] == "llm":
            provider = session.get(ProviderRecord, identifier)
            if provider is None:
                provider = ProviderRecord(id=identifier, created_at=utc_now())
                session.add(provider)
            provider.name = "settings:" + identifier
            provider.provider_type = row.kind
            provider.base_url = command.config.get("base_url", "")
            provider.status, provider.last_health_check = "UNKNOWN", None
            provider.adapter_version, provider.notes = "1.0.0", row.name
            provider.event_id = event.event_id
            for model in session.scalars(
                select(ModelRecord).where(ModelRecord.provider_id == identifier)
            ):
                model.is_available = False
        session.flush()
        return public(row)


def load_registry(engine: Engine, vault: CredentialVault, registry: ProviderRegistry) -> list[str]:
    """Registers every LLM connection whose keys can be read; returns the ids it could not.

    A connection whose keys cannot be read is left out and logged, never fatal: start-up used
    to decrypt all of them inside the lifespan, and one missing key file took the page down
    with it, so the Owner could not even reach the form to type the keys again (REL-06).
    """
    skipped: list[str] = []
    with Session(engine) as session:
        for row in session.scalars(select(Integration)):
            if CATALOG.get(row.kind, {}).get("runtime") != "llm":
                continue
            try:
                secrets = vault.decrypt(row.encrypted_secrets)
            except VaultUnreadable as exc:
                skipped.append(row.id)
                _log.warning(
                    "integration_not_loaded",
                    extra={"integration_id": row.id, "code": exc.code, "reason": exc.reason_ro},
                )
                continue
            # The price table of this connection's kind, read once per call inside the
            # adapter: a price the Owner types this afternoon costs this evening's runs
            # without a restart. Registered without one, every run of the connection
            # reported `cost_vr` NULL whatever he had typed.
            registry.register(
                row.id,
                ConfiguredLLM(
                    row.kind,
                    row.config,
                    secrets,
                    price_lookup=price_lookup(engine, row.kind),
                ),
            )
    return skipped


# ------------------------------------------------------------------ keys that cannot be read
#
# REL-06 / TS-03 / SELL-12. `vault_health` reads every stored connection's keys (the canary
# first, then each row) and says what cannot be read, in the Owner's words. At start-up
# `check_vault_at_startup` flags each unreadable connection NEEDS_RECONNECT on its own row (with
# an event saying why), gives a connection its status back once its keys read again, and writes
# the Owner one letter per distinct failure. The preflight line `credential_vault` reads the
# same health and BLOCKS the day when a connection the studio uses cannot be read, so no paid
# stage runs on keys it cannot open.

#: The status an unreadable connection is shown with until the Owner types its keys again.
NEEDS_RECONNECT = "NEEDS_RECONNECT"
NEEDS_RECONNECT_EVENT = "settings.integration_needs_reconnect"
READABLE_AGAIN_EVENT = "settings.integration_readable_again"
#: The letter's kind, one per distinct failure (`fingerprint`).
VAULT_LETTER_KIND = "credentials_unreadable"
VAULT_HEADLINE_RO = "Cheile salvate nu pot fi citite"

_log = logging.getLogger("studio.integrations")


def _settings_tab(kind: str) -> str:
    group = str(CATALOG.get(kind, {}).get("group") or "")
    return group if group in SETTINGS_TABS else "llm"


def vault_health(engine: Engine, vault: CredentialVault) -> dict[str, Any]:
    """Whether the studio can read the keys it stored. Reads, never writes, never creates a key.

    ``status`` HEALTHY | DEGRADED; ``code`` the key-level VAULT_* code or None; ``unreadable``
    each connection whose keys cannot be read (id, kind, name, table, in_use, code);
    ``blocking`` when the studio uses one of them (an LLM connection, or a connection selected
    for a purpose), or when the key itself cannot be opened and something was stored with it;
    ``reason_ro`` and ``place`` for the Owner.

    The connections are those saved in Settings (the `integration` table, which start-up and
    the media factory read). A YouTube channel's OAuth tokens (`youtube_connection`) are the
    YouTube service's: a token it cannot read surfaces where it is used, at the upload and the
    statistics read, and its own preflight lines name the channel.
    """
    key_code = vault.self_test()
    with Session(engine) as session:
        selected = {
            row.integration_id
            for row in session.scalars(select(ServiceSelection))
            if row.integration_id
        }
        stored: list[dict[str, Any]] = [
            {
                "id": row.id,
                "kind": row.kind,
                "name": row.name,
                "table": "integration",
                "encrypted": row.encrypted_secrets,
                "in_use": CATALOG.get(row.kind, {}).get("runtime") == "llm" or row.id in selected,
                "tab": _settings_tab(row.kind),
            }
            for row in session.scalars(select(Integration).order_by(Integration.id))
            if row.encrypted_secrets
        ]
    unreadable: list[dict[str, Any]] = []
    for item in stored:
        code = key_code
        if code is None:
            try:
                vault.decrypt(item["encrypted"])
            except VaultUnreadable as exc:
                code = exc.code
        if code is not None:
            unreadable.append(
                {k: v for k, v in item.items() if k not in ("encrypted", "tab")}
                | {"code": code, "tab": item["tab"]}
            )
    # A key file that cannot be opened is a fault even before anything is stored with it:
    # the first connection the Owner saves would fail. A key not there yet is a fresh studio.
    key_fault = key_code is not None and (bool(stored) or key_code != VAULT_MISSING)
    healthy = not unreadable and not key_fault
    code = key_code if key_fault else (unreadable[0]["code"] if unreadable else None)
    blocking = bool(stored) and any(item["in_use"] for item in unreadable)
    if key_fault and stored:
        blocking = True
    names = ", ".join(f"«{item['name']}»" for item in unreadable)
    reason = VAULT_REASONS_RO[code] if code else ""
    if healthy:
        reason_ro = ""
    elif unreadable:
        reason_ro = f"{VAULT_HEADLINE_RO}: {reason}. Conexiuni afectate: {names}; {RECONNECT_RO}."
    else:
        reason_ro = (
            f"{VAULT_HEADLINE_RO}: {reason}. Mutați fișierul cheii deoparte și {RECONNECT_RO}."
        )
    tab = next((item["tab"] for item in unreadable if item["tab"] == "llm"), None)
    tab = tab or (unreadable[0]["tab"] if unreadable else "llm")
    return {
        "status": "HEALTHY" if healthy else "DEGRADED",
        "code": code,
        "key_present": vault.key_present(),
        "stored": len(stored),
        "unreadable": unreadable,
        "blocking": blocking,
        "reason_ro": reason_ro,
        "place": f"settings:{tab}",
        "fingerprint": "" if healthy else f"{code}:{','.join(i['id'] for i in unreadable)}",
    }


def _flag_connections(engine: Engine, health: dict[str, Any]) -> dict[str, list[str]]:
    """NEEDS_RECONNECT on each unreadable Integration row (once), and its earlier status back
    on each flagged row that reads again. Each change bumps the row's version with an event."""
    unreadable = {
        item["id"]: item for item in health["unreadable"] if item["table"] == "integration"
    }
    flagged: list[str] = []
    restored: list[str] = []
    with Session(engine) as session, session.begin():
        for row in session.scalars(select(Integration)):
            if row.id in unreadable and row.status != NEEDS_RECONNECT:
                item = unreadable[row.id]
                previous = row.status
                row.status, row.checked_at = NEEDS_RECONNECT, utc_now()
                row.version += 1
                event = append_event(
                    session,
                    NEEDS_RECONNECT_EVENT,
                    "integration",
                    row.id,
                    row.version,
                    {
                        "previous_status": previous,
                        "code": item["code"],
                        "reason_ro": f"{VAULT_REASONS_RO[item['code']]}; {RECONNECT_RO}.",
                    },
                    str(uuid4()),
                )
                row.event_id = event.event_id
                flagged.append(row.id)
            elif row.id not in unreadable and row.status == NEEDS_RECONNECT:
                last = session.scalars(
                    select(DomainEvent)
                    .where(
                        DomainEvent.aggregate_type == "integration",
                        DomainEvent.aggregate_id == row.id,
                        DomainEvent.event_type == NEEDS_RECONNECT_EVENT,
                    )
                    .order_by(DomainEvent.aggregate_version.desc())
                ).first()
                said = (last.payload or {}) if last is not None else {}
                previous = str(said.get("previous_status") or "SAVED")
                row.status = previous
                row.version += 1
                event = append_event(
                    session,
                    READABLE_AGAIN_EVENT,
                    "integration",
                    row.id,
                    row.version,
                    {"status": previous},
                    str(uuid4()),
                )
                row.event_id = event.event_id
                restored.append(row.id)
    return {"flagged": flagged, "restored": restored}


def _vault_letter(engine: Engine, health: dict[str, Any]) -> str | None:
    """One letter to the Owner per distinct failure: the same broken key on every restart is
    one letter, a new connection that cannot be read is another."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415
    from app.db import lock_for_write  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for existing in session.scalars(
            select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
        ):
            body = existing.body_json if isinstance(existing.body_json, dict) else {}
            if (
                body.get("kind") == VAULT_LETTER_KIND
                and body.get("fingerprint") == health["fingerprint"]
            ):
                return None
        author = agent_for_role(session, "Director")
        consequence = (
            "Până atunci ziua nu pornește: nicio etapă plătită nu rulează pe chei pe care "
            "studioul nu le poate deschide."
            if health["blocking"]
            else "Ziua pornește, dar fără aceste conexiuni."
        )
        message = post_message(
            session,
            intent="ESCALATE",
            subject=VAULT_HEADLINE_RO,
            body={
                "kind": VAULT_LETTER_KIND,
                "fingerprint": health["fingerprint"],
                "code": health["code"],
                "connections": [item["id"] for item in health["unreadable"]],
            },
            body_text=(
                f"Către Owner. {health['reason_ro']} {consequence} Dacă studioul rulează ca "
                "sarcină Windows „fără utilizator conectat” (S4U), pornește-l din contul tău: "
                "cheia este legată de contul care a salvat conexiunile."
            ),
            from_agent_id=author.id if author is not None else None,
            to_owner=True,
        )
        return str(message.id)


def check_vault_at_startup(engine: Engine, vault: CredentialVault) -> dict[str, Any]:
    """The start-up self-test: health, the rows flagged or given back, one letter. Never raises:
    a studio that cannot say what is wrong with its keys must still start and serve the page."""
    try:
        health = vault_health(engine, vault)
        health["changes"] = _flag_connections(engine, health)
        if health["status"] != "HEALTHY":
            _log.warning(
                "credential_vault_degraded",
                extra={
                    "code": health["code"],
                    "unreadable": [item["id"] for item in health["unreadable"]],
                    "blocking": health["blocking"],
                },
            )
            health["letter_id"] = _vault_letter(engine, health)
        return health
    except Exception as exc:  # noqa: BLE001 - start-up goes on; the preflight reads it again
        _log.error("credential_vault_check_failed", exc_info=exc)
        return {"status": "UNKNOWN", "error_class": type(exc).__name__}


def selected_youtube(
    engine: Engine,
    vault: CredentialVault,
    identifier: str | None = None,
) -> YouTubeProvider | None:
    """The credentials to publish with, taken from an OAuth connection and nowhere else.

    ``identifier`` is a YouTube connection id — normally the one a channel record was bound to.
    Without one there is a single defensible answer only while exactly one channel is connected:
    AMN-AI runs more than one, and guessing which channel a publication belongs to is precisely
    the mistake this subsystem exists to prevent, so an ambiguous studio refuses instead.
    """
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415
    from app.youtube.services import (  # noqa: PLC0415
        STATUS_CONNECTED,
        YouTubeConnectionError,
        provider_for_connection,
    )

    if identifier is None:
        with Session(engine) as session:
            connected = session.scalars(
                select(YouTubeConnection)
                .where(YouTubeConnection.status == STATUS_CONNECTED)
                .order_by(YouTubeConnection.created_at)
            ).all()
        if not connected:
            return None
        if len(connected) > 1:
            raise ValueError(
                "Mai multe canale YouTube sunt conectate. Leagă canalul de publicare "
                "de o conexiune anume înainte de a publica."
            )
        identifier = connected[0].id
    try:
        return provider_for_connection(engine, vault, identifier)
    except YouTubeConnectionError as exc:
        raise ValueError(str(exc)) from None


def select_service(
    engine: Engine, purpose: str, identifier: str | None, expected_version: int
) -> dict:
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier) if identifier else None
        if identifier and (not row or purpose not in CATALOG[row.kind]["purposes"] + [row.kind]):
            raise ValueError("Conexiunea nu poate fi folosită pentru acest scop")
        if purpose not in (
            "image",
            "video",
            "voice",
            "music",
            "tiktok",
            "instagram",
            "facebook",
            "email",
        ):
            raise ValueError("Scop invalid")
        current = session.get(ServiceSelection, purpose)
        if (current.version if current else 0) != expected_version:
            raise ValueError("Conflict de versiune; reîncarcă setările")
        event = append_event(
            session,
            "settings.service_selected",
            "service_selection",
            purpose,
            expected_version + 1,
            {"integration_id": identifier},
            str(uuid4()),
        )
        if current is None:
            current = ServiceSelection(purpose=purpose)
            session.add(current)
        current.integration_id, current.version = identifier, expected_version + 1
        current.event_id = event.event_id
        return dict(purpose=purpose, integration_id=identifier, version=current.version)


def assign_agent(
    engine: Engine,
    agent_id: str,
    model_id: str,
    version: int,
    *,
    secondary_model_id: str | None = None,
    tertiary_model_id: str | None = None,
    multi_llm_strategy: str | None = None,
    additional_llm_policy: str | None = None,
    min_importance: str | None = None,
    min_confidence: float | None = None,
    assignment_origin: str = "OWNER",
) -> dict:
    """Save which models an employee thinks with, and what to do with more than one.

    One versioned command, as before: the primary model, and now the optional second and
    third slots with the strategy that uses them. Every slot is checked the same way the
    primary always was — the model must exist, be available, and satisfy what the role
    requires — because a fallback onto a model that cannot do the job is not a fallback.

    A model named in a slot is configuration. Nothing in the studio's logic reads its name,
    so the Owner can replace any of the three from here tomorrow without a code change.

    ``assignment_origin`` says whose choice it is: the Owner's (his Settings), the starting
    allocation file, or the Director's repair of an employee whose model stopped working
    (DIRECTOR_REPAIR, 2026-10-11: `app.agents.repairs.agent_health`, behind `may_act`'s
    ``agent.change_model``). The event keeps the slots it replaced, so a repair can be undone.
    """
    from app.agents.ensemble import IMPORTANCE, POLICIES, STRATEGIES
    from app.agents.services import DIRECTOR_REPAIR_ORIGIN

    strategy = (multi_llm_strategy or "SINGLE").upper()
    policy = (additional_llm_policy or "IMPORTANT_ONLY").upper()
    importance = (min_importance or "STRATEGIC").upper()
    if assignment_origin not in {"OWNER", "SEED_ALLOCATION", DIRECTOR_REPAIR_ORIGIN}:
        raise ValueError("Origine necunoscută pentru alocarea modelului")
    if strategy not in STRATEGIES:
        raise ValueError(f"Strategie necunoscută: {strategy}")
    if policy not in POLICIES:
        raise ValueError(f"Politică necunoscută: {policy}")
    if importance not in IMPORTANCE:
        raise ValueError(f"Prag de importanță necunoscut: {importance}")
    if min_confidence is not None and not 0.0 <= float(min_confidence) <= 1.0:
        raise ValueError("Pragul de încredere este între 0 și 1")

    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        model = session.get(ModelRecord, model_id)
        if not agent or not model or not model.is_available:
            raise ValueError("Agent sau model disponibil inexistent")
        if agent.version != version or agent.runtime_state not in ("IDLE", "BLOCKED", "ERROR"):
            raise ValueError("Agentul lucrează sau versiunea s-a schimbat; reîncarcă")
        if agent.lifecycle == "TERMINATED":
            raise ValueError("Agentul nu mai este activ în companie")
        previous = {
            "model_id": agent.model_id,
            "provider_id": agent.provider_id,
            "secondary_model_id": agent.secondary_model_id,
            "tertiary_model_id": agent.tertiary_model_id,
            "multi_llm_strategy": agent.multi_llm_strategy,
        }
        agent.provider_id, agent.model_id = model.provider_id, model.id
        from app.agents.services import PolicyKernelError, _check_required_capabilities

        try:
            _check_required_capabilities(session, agent)
        except PolicyKernelError as exc:
            raise ValueError("Modelul nu are capabilitățile necesare rolului") from exc

        extra: dict[str, str | None] = {}
        for slot, wanted in (
            ("secondary_model_id", secondary_model_id),
            ("tertiary_model_id", tertiary_model_id),
        ):
            if not wanted:
                extra[slot] = None
                continue
            row = session.get(ModelRecord, wanted)
            if row is None or not row.is_available:
                raise ValueError("Modelul secundar sau terțiar nu este disponibil")
            try:
                _check_required_capabilities(session, agent, model_id=row.id)
            except PolicyKernelError as exc:
                raise ValueError("Modelul din slot nu are capabilitățile necesare rolului") from exc
            extra[slot] = row.id
        if extra["tertiary_model_id"] and not extra["secondary_model_id"]:
            raise ValueError("Un al treilea model fără al doilea nu are cine să fie criticul")
        if strategy != "SINGLE" and not extra["secondary_model_id"]:
            raise ValueError(f"Strategia {strategy} are nevoie de un al doilea model")

        agent.secondary_model_id = extra["secondary_model_id"]
        agent.tertiary_model_id = extra["tertiary_model_id"]
        agent.multi_llm_strategy = strategy
        agent.additional_llm_policy = policy
        agent.min_importance = importance
        agent.min_confidence = float(min_confidence) if min_confidence is not None else None
        agent.version += 1
        event = append_event(
            session,
            "agent.model_assigned",
            "agent",
            agent.id,
            agent.version,
            {
                "model_id": model.id,
                "provider_id": model.provider_id,
                "secondary_model_id": agent.secondary_model_id,
                "tertiary_model_id": agent.tertiary_model_id,
                "multi_llm_strategy": strategy,
                "additional_llm_policy": policy,
                "assignment_origin": assignment_origin,
                "previous": previous,
            },
            str(uuid4()),
        )
        agent.event_id = event.event_id
        return dict(
            agent_id=agent.id,
            model_id=model.id,
            secondary_model_id=agent.secondary_model_id,
            tertiary_model_id=agent.tertiary_model_id,
            multi_llm_strategy=strategy,
            additional_llm_policy=policy,
            min_importance=importance,
            min_confidence=agent.min_confidence,
            version=agent.version,
        )
