"""Phase 5 FastAPI router for Media Production endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as FPath
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.media.assembler import RenderEngineUnavailable, assemble_video_job
from app.media.models import MediaAsset, VideoRenderJob
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
    list_storyboards,
    seed_default_character_bibles,
)
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
    ) -> dict:
        correlation_id = str(uuid4())
        try:
            result = assemble_video_job(
                request.app.state.engine,
                storyboard_id,
                correlation_id,
                ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
            )
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
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Render execution failed: {exc}") from exc

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
