"""Phase 4 FastAPI routes for Factual Intelligence & Verification Engine."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict

from app.factual.agent_pipeline import agent_extract_claims
from app.factual.schemas import (
    ApproveScriptCommand,
    ExtractClaimsCommand,
    FactualClaimView,
    GenerateHooksCommand,
    GenerateScriptCommand,
    IngestSourceCommand,
    ProposeTopicCommand,
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
from app.security import require_owner


class AgentExtractCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    agent_id: UUID | None = None


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
