"""Phase 4 FastAPI routes for Factual Intelligence & Verification Engine."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.factual.agent_pipeline import (
    NoIndependentVerifier,
    NoVerifiedClaims,
    ScriptRejected,
    VerificationRejected,
    agent_extract_claims,
    agent_verify_claim,
    agent_write_script,
)
from app.factual.schemas import (
    ApproveScriptCommand,
    ExtractClaimsCommand,
    FactualClaimView,
    GenerateHooksCommand,
    GenerateScriptCommand,
    IngestSourceCommand,
    ProposeTopicCommand,
    RetrievedSourceView,
    ScriptDraftView,
    SourceSnapshotView,
    TopicIdeaView,
    VerifyClaimCommand,
)
from app.factual.services import (
    FactualGateError,
    approve_script_draft,
    extract_claims,
    generate_hook_options,
    generate_script_draft,
    ingest_source_snapshot,
    list_claims,
    list_hooks,
    list_scripts,
    list_topic_ideas,
    propose_topic_idea,
    verify_claim,
)
from app.research.retrieval import RateLimited, RetrievalError
from app.research.service import (
    NOT_CONFIGURED_DETAIL,
    HostError,
    HostNotAllowed,
    RetrievalNotConfigured,
    add_allowed_host,
    allowed_host_rows,
    allowed_hosts,
    list_sources,
    remove_allowed_host,
    retrieve_and_ingest,
    test_allowed_host,
)
from app.security import require_owner


class AgentExtractCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    agent_id: UUID | None = None


class WriteScriptCommand(BaseModel):
    """Ask the script writer to draft from a topic's verified claims."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    topic_id: str = Field(min_length=36, max_length=36)
    target_duration_seconds: int = Field(default=50, ge=15, le=180)
    agent_id: UUID | None = None


class RetrieveSourceCommand(BaseModel):
    """Fetch a source the Owner named. The host must already be allow-listed in .env.

    Deliberately carries no host, policy or timeout field: everything that decides where the
    studio may connect comes from the Owner's configuration, never from the request.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    url: str = Field(min_length=8, max_length=1000)
    topic_id: UUID | None = None


def create_factual_router() -> APIRouter:
    router = APIRouter(prefix="/factual", dependencies=[Depends(require_owner)])

    @router.post("/topics", response_model=TopicIdeaView)
    def post_topic(request: Request, cmd: ProposeTopicCommand) -> dict:
        return propose_topic_idea(
            request.app.state.engine,
            cmd.title,
            cmd.topic,
            cmd.angle,
            cmd.target_audience,
            str(cmd.command_id),
        )

    @router.get("/topics")
    def get_topics(
        request: Request,
        status: Annotated[str | None, Query(max_length=30)] = None,
    ) -> dict:
        return {"topics": list_topic_ideas(request.app.state.engine, status=status)}

    @router.post("/sources/ingest", response_model=SourceSnapshotView)
    def post_source(request: Request, cmd: IngestSourceCommand) -> dict:
        return ingest_source_snapshot(
            request.app.state.engine,
            cmd.url,
            cmd.title,
            cmd.publisher,
            cmd.author,
            cmd.raw_content,
            cmd.credibility_score,
            str(cmd.command_id),
            topic_id=cmd.topic_id,
        )

    @router.get("/sources")
    def get_sources(request: Request) -> dict:
        """Stored sources, plus the hosts the Owner has authorised the studio to fetch."""
        return {
            "sources": list_sources(request.app.state.engine),
            "allowed_hosts": list(
                allowed_hosts(request.app.state.settings, request.app.state.engine)
            ),
            "allowed_host_rows": allowed_host_rows(
                request.app.state.settings, request.app.state.engine
            ),
        }

    @router.get("/sources/allowed-hosts")
    def get_allowed_hosts(request: Request) -> dict:
        return {"hosts": allowed_host_rows(request.app.state.settings, request.app.state.engine)}

    @router.put("/sources/allowed-hosts/{host}")
    def put_allowed_host(host: str, request: Request) -> dict:
        """The Owner authorises a site. Agents have no tool that reaches this endpoint."""
        try:
            return add_allowed_host(request.app.state.engine, host)
        except HostError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.delete("/sources/allowed-hosts/{host}")
    def delete_allowed_host(host: str, request: Request) -> dict:
        try:
            remove_allowed_host(request.app.state.engine, host)
        except HostError as exc:
            raise HTTPException(404, str(exc)) from None
        return {"removed": host.strip().lower()}

    @router.post("/sources/allowed-hosts/{host}/test")
    def post_test_allowed_host(host: str, request: Request) -> dict:
        """Fetch the site's front page for real and report whether the studio can read it."""
        try:
            return test_allowed_host(
                request.app.state.engine,
                request.app.state.settings,
                host,
                retriever=getattr(request.app.state, "source_retriever", None),
            )
        except HostError as exc:
            raise HTTPException(404, str(exc)) from None

    @router.post("/sources/retrieve", response_model=RetrievedSourceView)
    def post_retrieve_source(request: Request, cmd: RetrieveSourceCommand) -> dict:
        """Fetch a source the Owner named and store what actually came back.

        Each failure is reported as itself: no allowlist, a host outside it, a source that
        refused or did not answer. In every one of them nothing is stored, because a source
        snapshot the studio could not verify it downloaded is exactly the kind of record this
        system must never hold.
        """
        try:
            return retrieve_and_ingest(
                request.app.state.engine,
                request.app.state.settings,
                cmd.url,
                str(cmd.command_id),
                topic_id=str(cmd.topic_id) if cmd.topic_id else None,
                retriever=getattr(request.app.state, "source_retriever", None),
            )
        except RetrievalNotConfigured:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED_DETAIL) from None
        except HostNotAllowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Adresa nu este permisă. Sunt acceptate doar linkuri HTTPS către gazdele "
                    "din STUDIO_RESEARCH_ALLOWED_HOSTS, pe portul 443, fără date de "
                    "autentificare în URL."
                ),
            ) from None
        except RateLimited:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Sursa a limitat cererea și nu s-a preluat nimic. "
                    "Nu am reîncercat automat; încearcă mai târziu."
                ),
            ) from None
        except RetrievalError:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Sursa nu a răspuns cu un document utilizabil, deci nu s-a salvat nimic. "
                    "Verifică linkul sau încearcă mai târziu."
                ),
            ) from None

    @router.post("/claims/extract")
    def post_extract_claims(request: Request, cmd: ExtractClaimsCommand) -> dict:
        try:
            claims = extract_claims(
                request.app.state.engine,
                cmd.source_id,
                cmd.claims,
                str(cmd.command_id),
                topic_id=cmd.topic_id,
            )
            return {"claims": claims}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/sources/{source_id}/extract-with-agent")
    def post_extract_with_agent(
        request: Request,
        source_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: AgentExtractCommand,
    ) -> dict:
        """The research agent reads the ingested source and extracts claims via its LLM.

        Claims land UNVERIFIED regardless of the model's confidence — verification stays a
        separate, independent step the agent cannot perform for its own output.
        """
        try:
            return agent_extract_claims(
                request.app.state.engine,
                request.app.state.registry,
                source_id,
                str(cmd.command_id),
                agent_id=str(cmd.agent_id) if cmd.agent_id else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/claims/{claim_id}/verify", response_model=FactualClaimView)
    def post_verify_claim(
        request: Request,
        claim_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: VerifyClaimCommand,
    ) -> dict:
        try:
            return verify_claim(
                request.app.state.engine,
                claim_id,
                cmd.status,
                cmd.confidence,
                cmd.verifier_notes,
                cmd.evidence_text,
                str(cmd.command_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/claims/{claim_id}/verify-with-agent")
    def post_verify_with_agent(
        request: Request,
        claim_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: AgentExtractCommand,
    ) -> dict:
        """Have a second agent check this claim against the source it came from.

        A rejected verdict — one citing evidence that is not in the source — leaves the claim
        UNVERIFIED and says so. That is the correct outcome, not an error to be smoothed over.
        """
        try:
            return agent_verify_claim(
                request.app.state.engine,
                request.app.state.registry,
                claim_id,
                str(cmd.command_id),
                agent_id=str(cmd.agent_id) if cmd.agent_id else None,
            )
        except NoIndependentVerifier as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except VerificationRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/claims")
    def get_claims(
        request: Request,
        topic_id: Annotated[str | None, Query(max_length=36)] = None,
        source_id: Annotated[str | None, Query(max_length=36)] = None,
        status: Annotated[str | None, Query(max_length=30)] = None,
    ) -> dict:
        return {
            "claims": list_claims(
                request.app.state.engine,
                topic_id=topic_id,
                source_id=source_id,
                status=status,
            )
        }

    @router.post("/scripts/generate", response_model=ScriptDraftView)
    def post_generate_script(request: Request, cmd: GenerateScriptCommand) -> dict:
        try:
            return generate_script_draft(
                request.app.state.engine,
                cmd.topic_id,
                cmd.title,
                cmd.target_duration_seconds,
                cmd.voiceover_full_text,
                cmd.scenes,
                cmd.referenced_claim_ids,
                str(cmd.command_id),
            )
        except FactualGateError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FactualGateError",
                    "message": str(exc),
                    "unverified_claims": exc.unverified_claim_ids,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/scripts/{script_id}/approve", response_model=ScriptDraftView)
    def post_approve_script(
        request: Request,
        script_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: ApproveScriptCommand,
    ) -> dict:
        try:
            return approve_script_draft(request.app.state.engine, script_id, str(cmd.command_id))
        except FactualGateError as exc:
            # The gate runs again at approval on purpose: a claim that was SUPPORTED when the
            # draft was written may have been refuted since, and the Owner needs to be told
            # which one rather than reading a raw exception string.
            count = len(exc.unverified_claim_ids)
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FactualGateError",
                    "message": (
                        f"Aprobarea a fost refuzată: {count} afirmații citate nu mai sunt "
                        "susținute de o sursă. Verifică-le din nou sau rescrie scenariul."
                    ),
                    "unverified_claims": exc.unverified_claim_ids,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/scripts/write-with-agent")
    def post_write_with_agent(request: Request, cmd: WriteScriptCommand) -> dict:
        """Draft a voiceover from the topic's SUPPORTED claims, and only from those.

        A draft citing a claim that was not supplied is rejected whole; the factual gate then
        runs on the citations that survive, so a stored draft rests entirely on verified facts.
        """
        try:
            return agent_write_script(
                request.app.state.engine,
                request.app.state.registry,
                cmd.topic_id,
                str(cmd.command_id),
                target_duration_seconds=cmd.target_duration_seconds,
                agent_id=str(cmd.agent_id) if cmd.agent_id else None,
            )
        except NoVerifiedClaims as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ScriptRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except FactualGateError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FactualGateBlocked",
                    "message": (
                        "Poarta factuală a blocat scenariul: unele afirmații citate nu sunt "
                        "susținute de o sursă."
                    ),
                    "unverified_claim_ids": exc.unverified_claim_ids,
                },
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/scripts")
    def get_scripts(
        request: Request,
        topic_id: Annotated[str | None, Query(max_length=36)] = None,
    ) -> dict:
        return {"scripts": list_scripts(request.app.state.engine, topic_id=topic_id)}

    @router.post("/hooks/generate")
    def post_generate_hooks(request: Request, cmd: GenerateHooksCommand) -> dict:
        try:
            hooks = generate_hook_options(
                request.app.state.engine,
                cmd.script_id,
                [h.model_dump() for h in cmd.hooks],
                str(cmd.command_id),
            )
            return {"hooks": hooks}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/scripts/{script_id}/hooks")
    def get_hooks(
        request: Request,
        script_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return {"hooks": list_hooks(request.app.state.engine, script_id)}

    return router
