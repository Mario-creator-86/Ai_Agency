"""Phase 5 FastAPI router for Media Production endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as FPath
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.economy.accountant import record_render_costs
from app.economy.services import EconomyError
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.media.assembler import RenderEngineUnavailable, assemble_video_job
from app.media.factory import describe, render_plan, test_motion_provider, tts_provider
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.media.production_policy import (
    IdentityChangeCommand,
    IdentityDecisionCommand,
    IdentityLocksCommand,
    PolicyError,
    StoryboardProductionCommand,
    VoiceBindingCommand,
    approve_model_fallback,
    decide_identity_change,
    list_identity_changes,
    propose_identity_change,
    resolve_storyboard_plan,
    set_identity_locks,
    set_storyboard_production,
    set_voice_binding,
)
from app.media.qc import evaluate_media_qc, get_media_qc
from app.media.schemas import (
    GenerateStoryboardCommand,
    MediaAssetView,
    QCReportView,
    RenderJobView,
    StoryboardView,
)
from app.media.services import (
    generate_storyboard_from_script,
    get_character_bible,
    get_storyboard,
    list_character_bibles,
    list_scripts_awaiting_storyboard,
    list_storyboards,
    seed_default_character_bibles,
)
from app.providers.media_http import MediaProviderError
from app.security import require_owner
from app.services import append_event, utc_now


def create_media_router() -> APIRouter:
    router = APIRouter(prefix="/media", dependencies=[Depends(require_owner)])

    @router.get("/character-bible")
    def get_character_bibles(request: Request) -> dict:
        # Auto-seed defaults if table is empty
        seed_default_character_bibles(request.app.state.engine)
        return {"characters": list_character_bibles(request.app.state.engine)}

    @router.get("/character-bible/{character_id}")
    def get_single_character(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        char = get_character_bible(request.app.state.engine, character_id)
        if not char:
            raise HTTPException(status_code=404, detail="Character Bible entry not found")
        return char

    @router.get("/storyboards")
    def get_all_storyboards(request: Request) -> dict:
        return {"storyboards": list_storyboards(request.app.state.engine)}

    @router.get("/scripts/awaiting-storyboard")
    def get_scripts_awaiting_storyboard(request: Request) -> dict:
        """Approved scripts that production has not picked up yet."""
        return {"scripts": list_scripts_awaiting_storyboard(request.app.state.engine)}

    @router.get("/storyboards/{storyboard_id}")
    def get_single_storyboard(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        sb = get_storyboard(request.app.state.engine, storyboard_id)
        if not sb:
            raise HTTPException(status_code=404, detail="Storyboard not found")
        return sb

    @router.post("/storyboards/from-script/{script_id}", response_model=StoryboardView)
    def create_storyboard_from_script(
        request: Request,
        script_id: Annotated[str, FPath(min_length=36, max_length=36)],
        cmd: GenerateStoryboardCommand,
    ) -> dict:
        correlation_id = str(uuid4())
        try:
            return generate_storyboard_from_script(
                request.app.state.engine,
                script_id,
                cmd.visual_style,
                cmd.aspect_ratio,
                correlation_id,
            )
        except FactualGateError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SQLAlchemyError:
            raise HTTPException(
                status_code=500, detail="Database error during storyboarding"
            ) from None

    @router.post("/storyboards/demo-fixture", status_code=201)
    def create_demo_fixture(request: Request) -> dict:
        """Seed an UNVERIFIED demo topic, source and script for exercising the factual pipeline.

        This deliberately does NOT mark anything as SUPPORTED. A claim becomes SUPPORTED only
        through the verification endpoint, with real evidence recorded by the Owner or a
        fact-checking agent. Auto-approving a claim here would make the publishing gate certify
        evidence the studio invented for itself.
        """
        correlation_id = str(uuid4())
        engine = request.app.state.engine
        now = utc_now()
        script_id = str(uuid4())
        claim_id = str(uuid4())
        topic_id = str(uuid4())

        with Session(engine) as session, session.begin():
            session.add(
                TopicIdea(
                    id=topic_id,
                    title="Demo fixture: Descoperire Robotică Autonomă",
                    topic="robotics_breakthrough",
                    angle="Fixture local pentru testarea pipeline-ului factual",
                    target_audience="general",
                    novelty_score=0.95,
                    status="PROPOSED",
                    created_at=now,
                )
            )
            session.add(
                FactualClaim(
                    id=claim_id,
                    topic_id=topic_id,
                    claim_text=(
                        "Sistemul produce video 9:16 cu hash de proveniență SHA-256 și QC automat."
                    ),
                    claim_type="SCIENTIFIC_FACT",
                    importance="CRITICAL",
                    status="UNVERIFIED",
                    confidence=0.0,
                    verifier_notes=None,
                    evidence_text=None,
                    verified_at=None,
                    created_at=now,
                )
            )
            session.add(
                ScriptDraft(
                    id=script_id,
                    topic_id=topic_id,
                    version=1,
                    title="Demo fixture: Shorts #1",
                    target_duration_seconds=18,
                    voiceover_full_text=(
                        "Studioul AI produce conținut cu integritate garantată. Fiecare afirmație "
                        "este validată factual înainte de producție. Fiecare cadru este inspectat "
                        "și certificat automat."
                    ),
                    scenes_json=[
                        {
                            "scene_index": 1,
                            "visual_prompt": (
                                "Laborator high-tech cu servere modulare și ecrane holografice 9:16"
                            ),
                            "visual_type": "GENERATED_IMAGE",
                            "shot_type": "WIDE_ESTABLISHING",
                            "duration_seconds": 6.0,
                            "voiceover_segment": (
                                "Studioul AI produce conținut cu integritate garantată."
                            ),
                            "transition_in": "FADE",
                        },
                        {
                            "scene_index": 2,
                            "visual_prompt": (
                                "Inginer analizând date de telemetrie pe ecrane verticale"
                            ),
                            "visual_type": "GENERATED_IMAGE",
                            "shot_type": "MEDIUM_CLOSEUP",
                            "duration_seconds": 6.0,
                            "voiceover_segment": (
                                "Fiecare afirmație este validată factual înainte de producție."
                            ),
                            "transition_in": "DISSOLVE",
                        },
                        {
                            "scene_index": 3,
                            "visual_prompt": (
                                "Linie de asamblare media digitală generând fluxul video 9:16 final"
                            ),
                            "visual_type": "GENERATED_IMAGE",
                            "shot_type": "CLOSEUP_PRODUCT",
                            "duration_seconds": 6.0,
                            "voiceover_segment": (
                                "Fiecare cadru este inspectat și certificat automat."
                            ),
                            "transition_in": "FADE",
                        },
                    ],
                    status="DRAFT",
                    claim_ids_json=[claim_id],
                    unverified_claim_ids_json=[claim_id],
                    created_at=now,
                )
            )
            append_event(
                session,
                "factual.demo_fixture_created",
                "script_draft",
                script_id,
                1,
                {"topic_id": topic_id, "claim_ids": [claim_id], "verified": False},
                correlation_id,
            )

        return {
            "topic_id": topic_id,
            "script_id": script_id,
            "claim_ids": [claim_id],
            "script_status": "DRAFT",
            "claims_status": "UNVERIFIED",
            "next_step": (
                "Verifică afirmația în panoul Cercetare (cu sursă reală), apoi aprobă scenariul. "
                "Storyboard-ul nu poate fi generat cât timp există afirmații neverificate."
            ),
        }

    @router.post("/render/{storyboard_id}")
    def start_render(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        motion_scenes: Annotated[int | None, Query(ge=0, le=24)] = None,
        mode: Annotated[str, Query(pattern="^(production|test)$")] = "production",
    ) -> dict:
        correlation_id = str(uuid4())
        engine = request.app.state.engine
        vault = request.app.state.credential_vault
        # Only a provider the Owner selected *and* verified is used. With none, the render
        # falls back to placeholder generators and is labelled as such, which QC then blocks
        # from publication — a video to look at, never one presented as publishable.
        try:
            # The hierarchy decides per storyboard and per scene: channel policy, series rules,
            # episode/scene overrides and locked character voices. A test-injected adapter on
            # app.state still wins, as before.
            planned = render_plan(engine, vault, storyboard_id)
            # A test films on the cheapest prompt-to-video model, for as few scenes as it
            # takes to see how the film reads: one experiment must never cost a film again.
            test_motion = test_motion_provider(engine, vault) if mode == "test" else None
            injected_tts = getattr(request.app.state, "tts_adapter", None)
            result = assemble_video_job(
                engine,
                storyboard_id,
                correlation_id,
                ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
                image_adapter=getattr(request.app.state, "image_adapter", None) or planned["image"],
                tts_adapter=injected_tts or tts_provider(engine, vault),
                tts_adapter_for_scene=None if injected_tts else planned["tts_for_scene"],
                # The Owner's own render button makes the same film the day does: a shot per
                # scene from the scene's motion model, not a slideshow.
                video_adapter_for_scene=(
                    None
                    if getattr(request.app.state, "image_adapter", None)
                    else (
                        (lambda scene: test_motion)
                        if mode == "test" and test_motion is not None
                        else planned["video_for_scene"]
                    )
                ),
                motion_from_prompt=mode == "test",
                # `motion_scenes=1` is how a test render costs one shot instead of eight.
                motion_budget_usd=request.app.state.settings.motion_budget_usd,
                motion_scene_limit=(
                    motion_scenes
                    if motion_scenes is not None
                    else (2 if mode == "test" else request.app.state.settings.motion_scenes_max)
                ),
                production_plan=planned["plan"],
            )
            # What the render bought goes into the books here too. The day's stage recorded
            # it and the Owner's own button did not, so four renders left the books empty.
            try:
                result["costs"] = record_render_costs(engine, result["job_id"], correlation_id)
            except (EconomyError, KeyError, ValueError) as exc:
                result["costs"] = {"error": str(exc)[:200]}

            # Automatically trigger QC
            qc_result = evaluate_media_qc(
                request.app.state.engine,
                result["output_asset_id"],
                correlation_id,
            )
            result["qc"] = qc_result
            return result
        except RenderEngineUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "RenderEngineUnavailable", "message": str(exc)},
            ) from exc
        except MediaProviderError as exc:
            # The vendor did not deliver. Nothing partial is presented as a render.
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "MediaProviderFailed",
                    "message": (
                        "Furnizorul media nu a livrat conținutul, deci randarea nu s-a produs. "
                        "Verifică conexiunea în Settings și încearcă din nou."
                    ),
                    "detail": str(exc),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Render execution failed: {exc}") from exc

    @router.get("/storyboards/{storyboard_id}/production-plan")
    def get_production_plan(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        """What a render of this storyboard would use, resolved through the hierarchy now."""
        with Session(request.app.state.engine) as session:
            board = session.get(Storyboard, storyboard_id)
            if board is None:
                raise HTTPException(status_code=404, detail="Storyboard not found")
            return resolve_storyboard_plan(session, board)

    @router.put("/storyboards/{storyboard_id}/production")
    def put_storyboard_production(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: StoryboardProductionCommand,
    ) -> dict:
        """Channel, series and episode/scene overrides for one video."""
        try:
            return set_storyboard_production(request.app.state.engine, storyboard_id, command)
        except PolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/character-bible/{character_id}/voice-binding")
    def put_voice_binding(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: VoiceBindingCommand,
    ) -> dict:
        try:
            return set_voice_binding(request.app.state.engine, character_id, command)
        except PolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put("/character-bible/{character_id}/identity-locks")
    def put_identity_locks(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: IdentityLocksCommand,
    ) -> dict:
        try:
            return set_identity_locks(request.app.state.engine, character_id, command)
        except PolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/character-bible/{character_id}/approved-models")
    def post_approved_model(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: dict,
    ) -> dict:
        """Approve a model as technology for a locked character; the voice identity stays."""
        try:
            return approve_model_fallback(
                request.app.state.engine,
                character_id,
                str(command.get("integration_id") or ""),
                str(command.get("model_id") or ""),
                str(command.get("decided_by") or "Owner"),
            )
        except PolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/character-bible/{character_id}/identity-changes", status_code=201)
    def post_identity_change(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: IdentityChangeCommand,
    ) -> dict:
        try:
            return propose_identity_change(request.app.state.engine, character_id, command)
        except PolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/identity-changes")
    def get_identity_changes(request: Request, character_id: str | None = None) -> dict:
        return {"changes": list_identity_changes(request.app.state.engine, character_id)}

    @router.post("/identity-changes/{change_id}/decision")
    def post_identity_decision(
        request: Request,
        change_id: Annotated[str, FPath(min_length=36, max_length=36)],
        command: IdentityDecisionCommand,
    ) -> dict:
        try:
            return decide_identity_change(request.app.state.engine, change_id, command)
        except PolicyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/providers")
    def get_media_providers(request: Request) -> dict:
        """Which media generators a render would actually use right now.

        Reports the selection as it stands; it probes nothing, so this never asserts that a
        provider is reachable — only that the Owner selected and verified it.
        """
        described = describe(request.app.state.engine, request.app.state.credential_vault)
        return {
            **described,
            "renders_are_publishable": bool(described["image_provider"]),
            "note": (
                "Fără un furnizor de imagine verificat, randările folosesc cadre-substitut, "
                "iar QC le blochează de la publicare."
            ),
        }

    @router.get("/renders/{job_id}", response_model=RenderJobView)
    def get_render_status(
        request: Request,
        job_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        with request.app.state.engine.connect() as conn:
            job = (
                conn.execute(VideoRenderJob.__table__.select().where(VideoRenderJob.id == job_id))
                .mappings()
                .first()
            )
            if not job:
                raise HTTPException(status_code=404, detail="Render job not found")
            return dict(job)

    @router.get("/assets/{asset_id}", response_model=MediaAssetView)
    def get_asset_info(
        request: Request,
        asset_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        with request.app.state.engine.connect() as conn:
            asset = (
                conn.execute(MediaAsset.__table__.select().where(MediaAsset.id == asset_id))
                .mappings()
                .first()
            )
            if not asset:
                raise HTTPException(status_code=404, detail="Media asset not found")
            return dict(asset)

    @router.get("/assets/{asset_id}/stream")
    def stream_asset_file(
        request: Request,
        asset_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> FileResponse:
        with request.app.state.engine.connect() as conn:
            asset = (
                conn.execute(MediaAsset.__table__.select().where(MediaAsset.id == asset_id))
                .mappings()
                .first()
            )
            if not asset:
                raise HTTPException(status_code=404, detail="Media asset not found")
            file_path = Path(asset["uri_or_path"])
            if not file_path.is_file():
                raise HTTPException(status_code=404, detail="Asset file missing on disk")
            return FileResponse(file_path, media_type=asset["mime_type"])

    @router.get("/qc/{identifier}", response_model=QCReportView)
    def get_asset_qc_report(
        request: Request,
        identifier: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        engine = request.app.state.engine
        qc = get_media_qc(engine, identifier)
        if not qc:
            with Session(engine) as session:
                job = session.scalars(
                    select(VideoRenderJob)
                    .where(
                        VideoRenderJob.storyboard_id == identifier,
                        VideoRenderJob.status == "COMPLETED",
                    )
                    .order_by(VideoRenderJob.finished_at.desc())
                ).first()
                if job and job.output_asset_id:
                    qc = get_media_qc(engine, job.output_asset_id)
        if not qc:
            raise HTTPException(status_code=404, detail="QC report not found")
        return qc

    @router.post("/qc/{identifier}", response_model=QCReportView)
    def evaluate_qc_for_storyboard(
        request: Request,
        identifier: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        correlation_id = str(uuid4())
        engine = request.app.state.engine
        asset_id = identifier
        with Session(engine) as session:
            asset = session.get(MediaAsset, identifier)
            if not asset:
                job = session.scalars(
                    select(VideoRenderJob)
                    .where(
                        VideoRenderJob.storyboard_id == identifier,
                        VideoRenderJob.status == "COMPLETED",
                    )
                    .order_by(VideoRenderJob.finished_at.desc())
                ).first()
                if job and job.output_asset_id:
                    asset_id = job.output_asset_id
                else:
                    raise HTTPException(
                        status_code=404,
                        detail="No rendered asset found for storyboard to run QC on",
                    )
        return evaluate_media_qc(engine, asset_id, correlation_id)

    return router
