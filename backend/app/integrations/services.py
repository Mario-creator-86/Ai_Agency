import re
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.integrations.catalog import CATALOG
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
        runtime=CATALOG[row.kind]["runtime"],
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
    engine: Engine, vault: CredentialVault, identifier: str | None = None
) -> YouTubeProvider | None:
    with Session(engine) as session:
        selection = session.get(ServiceSelection, "youtube")
        identifier = identifier or (selection.integration_id if selection else None)
        if not identifier:
            return None
        row = session.get(Integration, identifier)
        if row is None or row.kind != "youtube":
            raise ValueError("YouTube selection invalid")
        secrets = vault.decrypt(row.encrypted_secrets)
        return YouTubeProvider(
            client_id=row.config["client_id"],
            client_secret=secrets["client_secret"],
            refresh_token=secrets["refresh_token"],
            channel_id=row.config["channel_id"],
        )


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
            "youtube",
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


def assign_agent(engine: Engine, agent_id: str, model_id: str, version: int) -> dict:
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
        agent.version += 1
        event = append_event(
            session,
            "agent.model_assigned",
            "agent",
            agent.id,
            agent.version,
            {"model_id": model.id, "provider_id": model.provider_id},
            str(uuid4()),
        )
        agent.event_id = event.event_id
        return dict(agent_id=agent.id, model_id=model.id, version=agent.version)
