from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.models import Agent, ModelRecord, ProviderRecord
from app.agents.services import (
    list_agents,
    list_provider_models,
    list_roles,
    run_agent_task,
    sync_provider_models,
)
from app.integrations.catalog import CATALOG
from app.integrations.llm import ConfiguredLLM
from app.integrations.models import Integration, ServiceSelection
from app.integrations.probes import probe
from app.integrations.services import SaveIntegration, assign_agent, public, save, select_service
from app.publishing.models import ChannelRecord
from app.security import require_owner
from app.services import append_event, utc_now
from app.youtube.models import YouTubeConnection


class SelectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration_id: UUID | None
    expected_version: int = Field(ge=0)


class AssignmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: UUID
    expected_version: int = Field(ge=1)


class ChannelBindingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: A YouTube connection id. Credentials for a channel come from an OAuth grant, never from
    #: a catalog entry someone filled in by hand.
    connection_id: UUID | None
    expected_event_id: UUID | None


def create_settings_router() -> APIRouter:
    router = APIRouter(prefix="/settings", dependencies=[Depends(require_owner)])

    @router.get("")
    def read_settings(request: Request) -> dict:
        engine = request.app.state.engine
        with Session(engine) as session:
            integrations = [public(row) for row in session.scalars(select(Integration))]
            selections = {
                row.purpose: dict(integration_id=row.integration_id, version=row.version)
                for row in session.scalars(select(ServiceSelection))
            }
            provider_ids = set(session.scalars(select(ModelRecord.provider_id)).all())
            # Providers seeded before the Settings screen existed (the local Ollama
            # endpoint) have no Integration row, so without this the Owner can see their
            # models but has no control to verify them — and an unverifiable record can
            # only ever stay an unverified claim.
            integration_ids = {row.id for row in session.scalars(select(Integration))}
            legacy_providers = [
                dict(
                    id=p.id,
                    name=p.name,
                    provider_type=p.provider_type,
                    base_url=p.base_url,
                    status=p.status,
                    last_health_check=p.last_health_check,
                )
                for p in session.scalars(select(ProviderRecord))
                if p.id not in integration_ids
            ]
            channels = [
                dict(
                    id=c.id,
                    name=c.channel_name,
                    credentials_ref=c.credentials_ref,
                    # Which account this channel actually publishes to, as reported by Google
                    # when the connection behind it was authorised.
                    remote_channel_id=c.remote_channel_id,
                    event_id=c.event_id,
                    status=c.status,
                )
                for c in session.scalars(
                    select(ChannelRecord).where(ChannelRecord.platform == "YOUTUBE")
                )
            ]
        return dict(
            catalog=CATALOG,
            channels=channels,
            integrations=integrations,
            selections=selections,
            agents=list_agents(engine),
            roles=list_roles(engine),
            models=[m for p in provider_ids for m in list_provider_models(engine, p)],
            legacy_providers=legacy_providers,
            legacy_youtube_configured=request.app.state.settings.youtube_credentials_present,
        )

    @router.put("/integrations/{identifier}")
    def save_integration(identifier: UUID, command: SaveIntegration, request: Request) -> dict:
        try:
            result = save(
                request.app.state.engine,
                request.app.state.credential_vault,
                str(identifier),
                command,
            )
            if CATALOG[command.kind]["runtime"] == "llm":
                with Session(request.app.state.engine) as session:
                    row = session.get(Integration, str(identifier))
                    if row is None:
                        raise HTTPException(409, "Conexiunea a fost ștearsă")
                    adapter = ConfiguredLLM(
                        row.kind,
                        row.config,
                        request.app.state.credential_vault.decrypt(row.encrypted_secrets),
                    )
                    request.app.state.registry.register(str(identifier), adapter)
            return result
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/integrations/{identifier}/check")
    def check_integration(identifier: UUID, request: Request) -> dict:
        engine = request.app.state.engine
        vault = request.app.state.credential_vault
        with Session(engine) as session:
            row = session.get(Integration, str(identifier))
            if row is None:
                raise HTTPException(404, "Conexiune inexistentă")
            kind, config, version = row.kind, row.config, row.version
            secrets = vault.decrypt(row.encrypted_secrets)
        runtime = CATALOG[kind]["runtime"]
        try:
            if runtime == "llm":
                sync_provider_models(engine, request.app.state.registry, str(identifier))
                status = "VERIFIED"
            else:
                # "stored" and "media" both verify by calling the vendor and comparing the answer
                # to what was saved. Media kinds used to fall through to a YouTube health check
                # that could only ever raise, so verifying an ElevenLabs or OpenAI media key
                # always reported FAILED; that branch is gone with the YouTube catalog entry.
                status = "ACCESS_VERIFIED" if probe(kind, config, secrets) else "FAILED"
        except NotImplementedError:
            return {"status": "NOT_SUPPORTED", "message": "Verificarea nu este încă disponibilă."}
        except Exception:
            status = "FAILED"
        with Session(engine) as session, session.begin():
            row = session.get(Integration, str(identifier))
            if row is None or row.version != version:
                raise HTTPException(409, "Configurația s-a schimbat în timpul verificării")
            row.status, row.checked_at = status, utc_now()
            row.version += 1
            event = append_event(
                session,
                "settings.integration_checked",
                "integration",
                row.id,
                row.version,
                {"status": status},
                str(uuid4()),
            )
            row.event_id = event.event_id
        return {
            "status": status,
            "message": "Acces verificat. Nu s-a publicat sau generat conținut."
            if status in ("VERIFIED", "ACCESS_VERIFIED")
            else "Verificarea a eșuat. Verifică datele, permisiunile și accesul la serviciu.",
        }

    @router.put("/selections/{purpose}")
    def set_selection(purpose: str, command: SelectionCommand, request: Request) -> dict:
        try:
            return select_service(
                request.app.state.engine,
                purpose,
                str(command.integration_id) if command.integration_id else None,
                command.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.put("/agents/{agent_id}/model")
    def set_agent_model(agent_id: UUID, command: AssignmentCommand, request: Request) -> dict:
        try:
            return assign_agent(
                request.app.state.engine,
                str(agent_id),
                str(command.model_id),
                command.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/agents/{agent_id}/test")
    def test_agent_llm(agent_id: UUID, request: Request) -> dict:
        """Owner-initiated connectivity check: one real run through the policy kernel.

        Uses the agent's currently assigned provider/model; the answer, token counts and
        audit trail come from the same AgentRun envelope every other task uses.
        """
        started = perf_counter()
        try:
            result = run_agent_task(
                request.app.state.engine,
                request.app.state.registry,
                str(agent_id),
                "TEST_CONNECTIVITY",
                "Răspunde într-o singură propoziție scurtă: ești funcțional?",
                "v1",
                str(uuid4()),
                max_tokens=800,
                temperature=0.2,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SQLAlchemyError:
            raise HTTPException(500, "Internal error") from None
        result["duration_s"] = round(perf_counter() - started, 2)
        return result

    @router.put("/channels/{channel_id}")
    def bind_channel(channel_id: UUID, command: ChannelBindingCommand, request: Request) -> dict:
        with Session(request.app.state.engine) as session, session.begin():
            channel = session.get(ChannelRecord, str(channel_id))
            if channel is None or channel.platform != "YOUTUBE":
                raise HTTPException(404, "Canal YouTube inexistent")
            expected = str(command.expected_event_id) if command.expected_event_id else None
            if channel.event_id != expected:
                raise HTTPException(409, "Canalul s-a schimbat; reîncarcă")
            if command.connection_id:
                connection = session.get(YouTubeConnection, str(command.connection_id))
                if connection is None or connection.status != "CONNECTED":
                    raise HTTPException(422, "Conectează întâi canalul prin Google")
                # Read back from the API during authorisation, so binding cannot attach a
                # channel record to an account the grant does not actually open.
                channel.remote_channel_id = connection.remote_channel_id
                channel.credentials_ref = "youtube_connection:" + connection.id
                channel.status = "AUTHENTICATED"
            else:
                channel.credentials_ref = None
                channel.status = "NOT_CONFIGURED"
            event = append_event(
                session,
                "channel.credentials_bound",
                "channel_record",
                channel.id,
                1,
                {"connection_id": str(command.connection_id) if command.connection_id else None},
                str(uuid4()),
            )
            channel.event_id = event.event_id
            channel.last_sync_at = utc_now()
        return {"saved": True}

    @router.delete("/integrations/{identifier}")
    def delete_integration(identifier: UUID, expected_version: int, request: Request) -> dict:
        with Session(request.app.state.engine) as session, session.begin():
            row = session.get(Integration, str(identifier))
            if row is None:
                raise HTTPException(404, "Conexiune inexistentă")
            if row.version != expected_version:
                raise HTTPException(409, "Reîncarcă setările")
            assigned = session.scalar(select(Agent.id).where(Agent.provider_id == row.id).limit(1))
            selected = session.scalar(
                select(ServiceSelection.purpose)
                .where(ServiceSelection.integration_id == row.id)
                .limit(1)
            )
            bound = session.scalar(
                select(ChannelRecord.id)
                .where(ChannelRecord.credentials_ref == "integration:" + row.id)
                .limit(1)
            )
            if assigned or selected or bound:
                raise HTTPException(
                    409, "Conexiunea este alocată. Schimbă alocarea înainte de ștergere."
                )
            append_event(
                session,
                "settings.integration_deleted",
                "integration",
                row.id,
                row.version + 1,
                {"kind": row.kind},
                str(uuid4()),
            )
            session.delete(row)
        request.app.state.registry.unregister(str(identifier))
        return {"deleted": True}

    return router
