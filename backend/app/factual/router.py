"""Phase 4 FastAPI routes for Factual Intelligence & Verification Engine."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

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
    SearchQueryCommand,
    SearchTemplateCommand,
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
from app.factual.story_review import StoryReviewError, latest_review, review_story
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
    research_health,
    retest_stale_hosts,
    retrieve_and_ingest,
    search_pages,
    set_search_template,
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
    revision_notes: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        default_factory=list, max_length=8
    )


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

    @router.put("/sources/allowed-hosts/{host}/search")
    def put_search_template(host: str, request: Request, cmd: SearchTemplateCommand) -> dict:
        """The Owner records the site's own search address (OpenSearch JSON, {query} inside)."""
        try:
            return set_search_template(request.app.state.engine, host, cmd.template)
        except HostError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/sources/allowed-hosts/{host}/search/test")
    def post_search_test(host: str, request: Request, cmd: SearchQueryCommand) -> dict:
        """Run the site's search for real and show what it finds; nothing is stored."""
        return {
            "host": host.strip().lower(),
            "query": cmd.query,
            "found": search_pages(
                request.app.state.settings,
                request.app.state.engine,
                host,
                cmd.query,
                retriever=getattr(request.app.state, "source_retriever", None),
            ),
        }

    @router.get("/research/health")
    def get_research_health(request: Request) -> dict:
        """How the studio stands for finding and reading pages, as the preflight sees it.

        Computed from the record and probing nothing, so the screen may ask for it as often
        as it likes: the counts, the failing hosts with their reason codes, whether a search
        engine is verified, how many verified claims are left, and the DEGRADED reasons.
        """
        return research_health(request.app.state.engine, request.app.state.settings)

    @router.post("/research/allowed-hosts/retest")
    def post_retest_allowed_hosts(request: Request) -> dict:
        """Re-test every authorised site now, instead of waiting for the weekly pass.

        ``max_age_days=0`` is what makes it "now": the runbook's pass leaves a site tested
        this week alone, and this is the Owner asking anyway after fixing something. One
        front page per site through the same DNS-pinned retriever, nothing stored as a source.
        """
        tested = retest_stale_hosts(
            request.app.state.engine,
            request.app.state.settings,
            max_age_days=0,
            retriever=getattr(request.app.state, "source_retriever", None),
        )
        return {"tested": tested}

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
                notes=cmd.revision_notes or None,
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

    @router.post("/scripts/{script_id}/story-review")
    def run_story_review(
        request: Request,
        script_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        """Read the story before anything is generated, and record the verdict.

        The runbook does this on its own for every script it writes. This is the same review
        for a script the Owner wrote or approved by hand — nothing reaches the prompt agent
        or the render until it has passed.
        """
        try:
            return review_story(
                request.app.state.engine,
                getattr(request.app.state, "registry", None),
                script_id,
            )
        except StoryReviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/scripts/{script_id}/story-review")
    def read_story_review(
        request: Request,
        script_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        """The latest story review of this script, or the reason there is none."""
        with Session(request.app.state.engine) as session:
            review = latest_review(session, script_id)
            if review is None:
                return {"script_id": script_id, "verdict": "NONE", "notes": [], "checks": {}}
            return {
                "script_id": script_id,
                "verdict": review.verdict,
                "checks": review.checks_json,
                "retention": review.retention_json,
                "scores": review.scores_json,
                "notes": (review.notes_json or {}).get("notes", []),
                "failed": (review.notes_json or {}).get("failed", []),
                "estimated_seconds": review.estimated_seconds,
                "created_at": review.created_at,
            }

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
