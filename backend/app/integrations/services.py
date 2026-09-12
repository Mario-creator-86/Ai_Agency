import re
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.integrations.catalog import CATALOG
from app.integrations.discovery import DISCOVERED_KINDS, reset_discovery
from app.integrations.llm import ConfiguredLLM
from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import CredentialVault
from app.providers.registry import ProviderRegistry
from app.providers.youtube import YouTubeProvider
from app.services import append_event, utc_now


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
        secrets = vault.decrypt(row.encrypted_secrets) if row else {}
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
        row.kind, row.name = command.kind, command.name.strip()
        row.config, row.encrypted_secrets = command.config, vault.encrypt(secrets)
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


def load_registry(engine: Engine, vault: CredentialVault, registry: ProviderRegistry) -> None:
    with Session(engine) as session:
        for row in session.scalars(select(Integration)):
            if CATALOG[row.kind]["runtime"] == "llm":
                registry.register(
                    row.id,
                    ConfiguredLLM(row.kind, row.config, vault.decrypt(row.encrypted_secrets)),
                )


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
) -> dict:
    """Save which models an employee thinks with, and what to do with more than one.

    One versioned command, as before: the primary model, and now the optional second and
    third slots with the strategy that uses them. Every slot is checked the same way the
    primary always was — the model must exist, be available, and satisfy what the role
    requires — because a fallback onto a model that cannot do the job is not a fallback.

    A model named in a slot is configuration. Nothing in the studio's logic reads its name,
    so the Owner can replace any of the three from here tomorrow without a code change.
    """
    from app.agents.ensemble import IMPORTANCE, POLICIES, STRATEGIES

    strategy = (multi_llm_strategy or "SINGLE").upper()
    policy = (additional_llm_policy or "IMPORTANT_ONLY").upper()
    importance = (min_importance or "STRATEGIC").upper()
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
