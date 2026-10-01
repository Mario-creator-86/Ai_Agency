"""Phase 5 FastAPI router for Media Production endpoints."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as FPath
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.economy.accountant import record_render_costs
from app.economy.services import EconomyError
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.factual.story_review import story_gate
from app.media.assembler import (
    DEFAULT_STORAGE_ROOT,
    RenderEngineUnavailable,
    SceneRedoRefused,
    assemble_video_job,
    redo_plan,
    redo_scene,
    release_after_qc,
)
from app.media.factory import (
    PaidVendorRefused,
    abandon_unfinished_renders,
    describe,
    guard_motion_chooser,
    image_provider,
    legacy_render_vendors,
    motion_for_scene,
    render_plan,
    tts_provider,
)
from app.media.models import MediaAsset, SceneTake, Storyboard, StoryboardScene, VideoRenderJob
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
from app.media.prompt_agent import (
    PromptError,
    hold_for_shot_plan,
    production_package,
    shot_plan_gaps,
    write_shot_prompts,
)
from app.media.qc import evaluate_media_qc, get_media_qc
from app.media.rehearsal import (
    AdoptExistingFilesCommand,
    RehearsalError,
    RehearsalNotFound,
    RehearsalRefused,
    adopt_existing_files,
    rehearse,
)
from app.media.schemas import (
    GenerateStoryboardCommand,
    MediaAssetView,
    QCReportView,
    RenderJobView,
    SceneModelCommand,
    SheetStepCommand,
    StoryboardView,
    TakeDecisionCommand,
)
from app.media.services import (
    REFERENCE_STORAGE_ROOT,
    ReferenceRequired,
    ReferenceSetError,
    generate_character_reference_set,
    generate_storyboard_from_script,
    get_character_bible,
    get_storyboard,
    list_character_bibles,
    list_scripts_awaiting_storyboard,
    list_storyboards,
    seed_default_character_bibles,
)
from app.media.shooting_sheet import (
    ASSEMBLE_STEP,
    SHEET_STEPS,
    SheetChoiceRefused,
    SheetNotFound,
    SheetStepRefused,
    build_sheet,
    card_preview_png,
    connection_account,
    connection_capabilities,
    connection_video_adapters,
    decide_sheet_take,
    run_assemble_step,
    run_sheet_step,
    runway_connection_id,
    set_scene_model,
    sheet_hash,
    sheet_overrides,
    sheet_url,
)
from app.providers.media_http import MediaProviderError
from app.security import require_owner
from app.services import append_event, studio_environment, utc_now
from app.wording import settings_place


def _use_the_sheet(engine: Any, storyboard_id: str, correlation_id: str) -> dict[str, Any]:
    """The 409 of the legacy render button in PRODUCTION: the way to the shooting sheet.

    A film whose shots a model did not write is also held for its shot plan (NEEDS_SHOT_PLAN
    and a WARNING event), as the day's media stage holds it. Office-serial scenes composed
    from the fixed series look are not template prompts and are not held.
    """
    with Session(engine) as session:
        gaps = shot_plan_gaps(session, storyboard_id)
        serial = {
            row.scene_index
            for row in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
            if (row.prompt_json or {}).get("source") == "series_look"
        }
    gaps = [index for index in gaps if index not in serial]
    message = (
        "Folosește foaia de filmare: în PRODUCȚIE nimic nu se mai cumpără de la butonul vechi "
        "de randare. Foaia arată fiecare imagine, fiecare prompt, modelul fiecărei scene, "
        "secundele, creditele, soldul și plafonul, iar fiecare pas plătit (imaginile, cadrul "
        "de probă, mișcarea) cere aprobarea Proprietarului."
    )
    if gaps:
        hold_for_shot_plan(engine, storyboard_id, correlation_id)
        message += (
            " Scenele "
            + ", ".join(map(str, gaps))
            + " nu au planul de cadre scris de model; filmul așteaptă planul de cadre."
        )
    return {
        "error": "UseShootingSheet",
        "message": message,
        "sheet_url": sheet_url(storyboard_id),
        "shot_plan_gaps": gaps,
    }


def _paid_vendor_refusal(storyboard_id: str, refused: PaidVendorRefused) -> dict[str, Any]:
    """The 409 of the legacy render in any environment when it would reach a real paid
    vendor: the way to the shooting sheet, and the vendors it would have bought from."""
    return {
        "error": "UseShootingSheet",
        "message": refused.message_ro,
        "sheet_url": sheet_url(storyboard_id),
        "paid_vendors": refused.vendors,
        "shot_plan_gaps": [],
    }


class SceneRedoCommand(BaseModel):
    """The Owner's request to redo one scene (still | motion | card) or the film's sound.

    A still or motion redo names the plan he was shown (``plan_hash``, from the redo plan);
    card and audio cost nothing and need none. Nothing in the body says who asks: the route
    is the Owner's, and what the redo may buy is decided by his yes for that plan alone.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["still", "motion", "card", "audio"]
    scene_index: int | None = Field(default=None, ge=1, le=200)
    plan_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)
    allow_over_budget: bool = False


def _sheet_wiring(request: Request) -> dict[str, Any]:
    """What the sheet and its steps are built from: the fakes a test put on ``app.state``,
    otherwise the Runway connection the Owner selected and verified."""
    state = request.app.state
    engine = state.engine
    vault = state.credential_vault
    integration_id = getattr(state, "runway_integration_id", None) or runway_connection_id(engine)
    capabilities = getattr(state, "scene_model_capabilities", None)
    if capabilities is None:
        capabilities = connection_capabilities(engine, integration_id)
    image = getattr(state, "image_adapter", None) or image_provider(engine, vault)
    account = getattr(state, "runway_account", None) or connection_account(
        engine, vault, integration_id
    )
    adapters = getattr(state, "video_adapter_for_model", None) or connection_video_adapters(
        engine, vault, integration_id
    )
    return {
        "integration_id": integration_id,
        "capabilities": list(capabilities),
        "image_adapter": image,
        "account": account,
        "adapter_for_model": adapters,
        "resolution": getattr(state.settings, "motion_resolution", None),
    }


def _assemble_step(
    request: Request, storyboard_id: str, cmd: SheetStepCommand, wiring: dict[str, Any]
) -> Any:
    """The sheet's assemble step on the Owner's route: the voices the film would be spoken
    in (a test's injected voice alone, otherwise the production plan's), then
    `run_assemble_step`. 202 with his narration question, 409 with the reason, 200 with the
    film, its QC and his letter."""
    state = request.app.state
    engine = state.engine
    settings = state.settings
    storage = getattr(state, "media_storage_root", None)
    injected_tts = getattr(state, "tts_adapter", None)
    try:
        planned = render_plan(engine, state.credential_vault, storyboard_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return run_assemble_step(
            engine,
            storyboard_id,
            cmd.plan_hash,
            correlation_id=str(uuid4()),
            capabilities=wiring["capabilities"],
            integration_id=wiring["integration_id"],
            resolution=wiring["resolution"],
            stills_model=getattr(wiring["image_adapter"], "model", None),
            settings=settings,
            storage_root=Path(storage) if storage else None,
            ffmpeg_path=getattr(settings, "ffmpeg_path", None),
            registry=getattr(state, "registry", None),
            tts_adapter=injected_tts or tts_provider(engine, state.credential_vault),
            tts_adapter_for_scene=None if injected_tts else planned.get("tts_for_scene"),
            voice_segments_for_scene=(
                None if injected_tts else planned.get("voice_segments_for_scene")
            ),
            reference_for_scene=planned.get("reference_for_scene"),
            production_plan=planned.get("plan"),
            allow_over_budget=cmd.allow_over_budget,
        )
    except SheetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SheetStepRefused as exc:
        if exc.http_status == 202:
            return JSONResponse(status_code=202, content=exc.as_dict())
        raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc


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
        model: Annotated[str | None, Query(max_length=200)] = None,
    ) -> dict:
        correlation_id = str(uuid4())
        started = utc_now()
        engine = request.app.state.engine
        vault = request.app.state.credential_vault
        # Nothing is generated for a film whose story has not been read and passed. Every
        # other gate in this studio used to run after the money was spent.
        with Session(engine) as session:
            board = session.get(Storyboard, storyboard_id)
            if board is None:
                raise HTTPException(status_code=404, detail="Storyboard not found")
            script_id = board.script_draft_id
        # In PRODUCTION nothing is bought from this button any more. The second Nepal render
        # (2026-09-26) started here: no price, no prompt, no model shown, no question asked,
        # and every still and clip of the film bought again. The shooting sheet shows all of
        # it first and asks the Owner at every paid step. TEST keeps the button for the fakes.
        if studio_environment(engine) == "PRODUCTION":
            raise HTTPException(
                status_code=409, detail=_use_the_sheet(engine, storyboard_id, correlation_id)
            )
        with Session(engine) as session:
            passed, why = story_gate(session, script_id)
        if not passed:
            raise HTTPException(status_code=422, detail=why)
        # Only a provider the Owner selected *and* verified is used. With none, the render
        # falls back to placeholder generators and is labelled as such, which QC then blocks
        # from publication — a video to look at, never one presented as publishable.
        try:
            # The hierarchy decides per storyboard and per scene: channel policy, series rules,
            # episode/scene overrides and locked character voices. A test-injected adapter on
            # app.state still wins, as before.
            planned = render_plan(engine, vault, storyboard_id)
            # Which environment this render belongs to is the studio's own state: a page
            # cannot ask for production routing by adding a parameter, and an agent cannot
            # decide it. `model` is the Director's explicit override, recorded as such.
            environment = studio_environment(engine)
            injected_tts = getattr(request.app.state, "tts_adapter", None)
            injected_image = getattr(request.app.state, "image_adapter", None)
            voice = injected_tts or tts_provider(engine, vault)
            # Real paid media is bought only through the shooting sheet's steps, under the
            # Owner's yes bound to its plan_hash, in every environment. This button keeps
            # working with fakes and local stand-ins; it refuses, before a render job exists,
            # whenever it would hand a real paid vendor to the render (TEST included: it
            # could still buy a whole film from the real Runway connection).
            vendors = legacy_render_vendors(
                engine,
                storyboard_id,
                image=injected_image or planned["image"],
                image_chain=None if injected_image else planned.get("image_chain"),
                tts=voice,
                tts_for_scene=None if injected_tts else planned["tts_for_scene"],
                voice_segments_for_scene=(
                    None if injected_tts else planned.get("voice_segments_for_scene")
                ),
            )
            if vendors:
                raise PaidVendorRefused(vendors)
            result = assemble_video_job(
                engine,
                storyboard_id,
                correlation_id,
                ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
                image_adapter=injected_image or planned["image"],
                # The vendors this film's stills may be drawn by, in order — the same chain
                # the day's media stage passes: the resolved vendor and, where the Owner
                # approved one for this purpose, a single alternative that draws the scene
                # the first refused before the render falls back to a placeholder still. An
                # adapter injected on app.state is the render's only vendor, as it has always
                # been, so the chain is passed only when nothing was injected.
                image_chain=None if injected_image else planned.get("image_chain"),
                # And the reference picture of the character the scene's cast names, so the
                # Owner's own button keeps a locked face instead of inventing it per scene.
                # This one is passed whatever adapter draws: which face a scene must keep is
                # a fact about the film's characters and not about the vendor, and a locked
                # character with no readable sheet refuses the render below.
                reference_for_scene=planned.get("reference_for_scene"),
                tts_adapter=voice,
                tts_adapter_for_scene=None if injected_tts else planned["tts_for_scene"],
                voice_segments_for_scene=(
                    None if injected_tts else planned.get("voice_segments_for_scene")
                ),
                # The Owner's own render button makes the same film the day does: a shot per
                # scene from the scene's motion model, not a slideshow.
                video_adapter_for_scene=(
                    None if getattr(request.app.state, "image_adapter", None) else None
                ),
                # The motion model is chosen per scene inside the render; a real paid one is
                # refused where it is chosen, before it is used for anything.
                motion_chooser=(
                    None
                    if getattr(request.app.state, "image_adapter", None)
                    else guard_motion_chooser(
                        lambda scene, tier, seconds, budget, exclude: motion_for_scene(
                            engine,
                            vault,
                            scene,
                            environment=environment,
                            tier=tier,
                            seconds=seconds,
                            budget_usd=budget,
                            forced_model=model,
                            exclude=exclude,
                            max_usd_per_second=(
                                request.app.state.settings.test_max_cost_per_second_usd
                                if environment == "TEST"
                                else None
                            ),
                        )
                    )
                ),
                environment=environment,
                motion_from_prompt=environment == "TEST",
                # `motion_scenes=1` is how a test render costs one shot instead of eight.
                motion_budget_usd=(
                    request.app.state.settings.test_max_cost_per_generation_usd
                    if environment == "TEST"
                    else request.app.state.settings.motion_budget_usd
                ),
                # In TEST the ceiling is checked twice: once when the model is chosen, on the
                # price the studio has recorded, and once against what the vendor quotes for
                # this exact shot. The second is the one that can refuse a purchase.
                motion_max_usd_per_second=(
                    request.app.state.settings.test_max_cost_per_second_usd
                    if environment == "TEST"
                    else None
                ),
                price_tolerance_percent=(request.app.state.settings.price_stale_tolerance_percent),
                motion_scene_limit=(
                    motion_scenes
                    if motion_scenes is not None
                    else (
                        request.app.state.settings.test_motion_scenes
                        if environment == "TEST"
                        else request.app.state.settings.motion_scenes_max
                    )
                ),
                production_plan=planned["plan"],
                # The day's run hands the camera the Owner's settings (captions burnt in,
                # the fallback ceiling); this button used to hand nothing, so the same
                # storyboard made two different films depending on who pressed render.
                settings=request.app.state.settings,
            )
            # What the render bought goes into the books here too. The day's stage recorded
            # it and the Owner's own button did not, so four renders left the books empty.
            try:
                result["costs"] = record_render_costs(
                    engine,
                    result["job_id"],
                    correlation_id,
                    alert_percent=request.app.state.settings.price_change_alert_percent,
                )
            except (EconomyError, KeyError, ValueError) as exc:
                result["costs"] = {"error": str(exc)[:200]}

            # Automatically trigger QC
            qc_result = evaluate_media_qc(
                request.app.state.engine,
                result["output_asset_id"],
                correlation_id,
                settings=request.app.state.settings,
                # The two things it takes to look at the pictures and not only at the file:
                # a provider holding a model that declares it can see, and the encoder that
                # cuts the frame it looks at. The day's quality control passed both and this
                # one passed neither, so the same film measured here reported the picture and
                # character checks NOT_APPLICABLE and there measured them.
                registry=getattr(request.app.state, "registry", None),
                ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
            )
            release_after_qc(request.app.state.engine, result["output_asset_id"], correlation_id)
            result["qc"] = qc_result
            return result
        except PaidVendorRefused as exc:
            # Refused before any render job existed, or inside one, where the motion model
            # was chosen: that job is failed here, nothing having been bought.
            abandon_unfinished_renders(engine, storyboard_id, started, exc.message_ro)
            raise HTTPException(
                status_code=409, detail=_paid_vendor_refusal(storyboard_id, exc)
            ) from exc
        except RenderEngineUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "RenderEngineUnavailable", "message": str(exc)},
            ) from exc
        except ReferenceRequired as exc:
            # Not the vendor refusing but the studio: a character whose look the Owner locked
            # has no reference picture the render can read, and drawing the scene anyway would
            # invent the face the lock exists to fix. It is a `ValueError`, so without this it
            # was answered below as 404 — "storyboard not found" about a storyboard that
            # exists. The Owner produces the character's reference set, then renders.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "ReferenceRequired",
                    "message": (
                        "Un personaj cu înfățișarea blocată nu are imagine de referință, "
                        "deci scena nu poate fi desenată. Produ setul de referințe al "
                        "personajului și reia randarea."
                    ),
                    "detail": str(exc),
                },
            ) from exc
        except MediaProviderError as exc:
            # The vendor did not deliver. Nothing partial is presented as a render.
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "MediaProviderFailed",
                    "message": (
                        "Furnizorul media nu a livrat conținutul, deci randarea nu s-a produs. "
                        f"Verifică conexiunea în {settings_place('media')} și încearcă din nou."
                    ),
                    "detail": str(exc),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Render execution failed: {exc}") from exc

    @router.post("/storyboards/{storyboard_id}/adopt-existing-files")
    def post_adopt_existing_files(
        request: Request,
        # A uuid and nothing else: the id names a folder on disk.
        storyboard_id: Annotated[
            str, FPath(min_length=36, max_length=36, pattern=r"^[0-9a-fA-F-]{36}$")
        ],
        cmd: AdoptExistingFilesCommand,
    ) -> dict:
        """The zero-credit rehearsal: rebuild a film from the files already paid for.

        The Owner's own route (the router requires his key); it is issued as 'owner' and
        nothing a request carries can change who adopts. The film's media folder is only read:
        the files are copied into a new folder under ``rehearsals/`` beside it, adopted as
        takes there, and the film is assembled from them with no image, video or voice
        adapter, so no vendor is asked and nothing goes into the books. Whatever adapter a
        test or an old wiring left on ``app.state`` is never passed.
        """
        engine = request.app.state.engine
        settings = request.app.state.settings
        storage = Path(
            getattr(request.app.state, "media_storage_root", None) or DEFAULT_STORAGE_ROOT
        )
        stamp = utc_now().replace(":", "").replace("-", "").replace("+", "_").replace(".", "_")
        source = storage / storyboard_id
        root = storage / "rehearsals" / f"{storyboard_id}-{stamp}"
        ffmpeg_path = getattr(settings, "ffmpeg_path", None)
        try:
            if cmd.render:
                return rehearse(
                    engine,
                    storyboard_id,
                    source,
                    rehearsal_root=root,
                    issued_by="owner",
                    cards=cmd.cards,
                    keep_flagged_for_rehearsal=cmd.keep_flagged_for_rehearsal,
                    settings=settings,
                    ffmpeg_path=ffmpeg_path,
                )
            adoption = adopt_existing_files(
                engine,
                storyboard_id,
                source,
                rehearsal_root=root,
                issued_by="owner",
                cards=cmd.cards,
                keep_flagged_for_rehearsal=cmd.keep_flagged_for_rehearsal,
                ffmpeg_path=ffmpeg_path,
            )
            return {"adoption": adoption, "film": None, "qc": None, "credits": 0}
        except RehearsalNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RehearsalRefused as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RehearsalError as exc:
            raise HTTPException(
                status_code=422, detail={"error": "RehearsalRefused", "message": str(exc)}
            ) from exc
        except RenderEngineUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "RenderEngineUnavailable", "message": str(exc)},
            ) from exc

    @router.get("/storyboards/{storyboard_id}/shooting-sheet")
    def get_shooting_sheet(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        """Foaia de filmare: everything a film will buy, before a credit is spent.

        0 credits. Its only live call is the free Runway balance read; the face badge of an
        approved still is counted locally.
        """
        from app.media.faces import count_faces  # noqa: PLC0415 - opencv loads lazily

        wiring = _sheet_wiring(request)
        try:
            return build_sheet(
                request.app.state.engine,
                storyboard_id,
                capabilities=wiring["capabilities"],
                integration_id=wiring["integration_id"],
                account=wiring["account"],
                resolution=wiring["resolution"],
                stills_model=getattr(wiring["image_adapter"], "model", None),
                face_counter=count_faces,
            )
        except SheetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/storyboards/{storyboard_id}/steps/{step}")
    def post_sheet_step(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        step: Annotated[str, FPath(max_length=20)],
        cmd: SheetStepCommand,
    ) -> Any:
        """One paid step of the sheet: 202 with the Owner's question, 409 with the reason
        nothing was bought, 200 once his yes for THIS sheet was spent and the step bought.

        ``assemble`` is the last step: the film from its takes, its narration (asked under
        the same plan), its master, quality control and the Owner's QC letter; 409 names
        each filmed scene that has no accepted take and no LOCAL_MOVE of his."""
        if step not in SHEET_STEPS and step != ASSEMBLE_STEP:
            raise HTTPException(status_code=404, detail=f"Pas necunoscut: {step}")
        settings = request.app.state.settings
        wiring = _sheet_wiring(request)
        storage = getattr(request.app.state, "media_storage_root", None)
        if step == ASSEMBLE_STEP:
            return _assemble_step(request, storyboard_id, cmd, wiring)
        try:
            return run_sheet_step(
                request.app.state.engine,
                storyboard_id,
                step,
                cmd.plan_hash,
                correlation_id=str(uuid4()),
                capabilities=wiring["capabilities"],
                integration_id=wiring["integration_id"],
                account=wiring["account"],
                image_adapter=wiring["image_adapter"],
                adapter_for_model=wiring["adapter_for_model"],
                registry=getattr(request.app.state, "registry", None),
                allow_over_budget=cmd.allow_over_budget,
                settings=settings,
                storage_root=Path(storage) if storage else None,
                ffmpeg_path=getattr(settings, "ffmpeg_path", None),
            )
        except SheetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SheetStepRefused as exc:
            if exc.http_status == 202:
                return JSONResponse(status_code=202, content=exc.as_dict())
            raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc

    @router.put("/storyboards/{storyboard_id}/shooting-sheet/scenes/{scene_index}/model")
    def put_scene_model(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        scene_index: Annotated[int, FPath(ge=1, le=200)],
        cmd: SceneModelCommand,
    ) -> dict:
        """The Owner's choice of one filmed scene's motion model (or LOCAL_MOVE), on the sheet.
        It changes the sheet and its hash; a yes for the old sheet buys nothing."""
        engine = request.app.state.engine
        wiring = _sheet_wiring(request)
        context = {
            "capabilities": wiring["capabilities"],
            "integration_id": wiring["integration_id"],
            "resolution": wiring["resolution"],
            "stills_model": getattr(wiring["image_adapter"], "model", None),
        }
        try:
            before = sheet_hash(engine, storyboard_id, **context)
            chosen = set_scene_model(
                engine,
                storyboard_id,
                scene_index,
                cmd.model_id,
                issued_by="owner",
                note=cmd.note,
                resolution=wiring["resolution"] or "1080p",
            )
        except SheetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SheetChoiceRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            **chosen,
            "previous_sheet_hash": before,
            "sheet_hash": sheet_hash(engine, storyboard_id, **context),
        }

    @router.get("/storyboards/{storyboard_id}/redo-plan")
    def get_redo_plan(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        kind: Annotated[Literal["still", "motion", "card", "audio"], Query()],
        scene: Annotated[int | None, Query(ge=1, le=200)] = None,
    ) -> dict:
        """What redoing one scene (or the sound) would do, cost and replace, with the
        plan_hash the Owner's yes is bound to. 0 credits, no vendor asked."""
        engine = request.app.state.engine
        wiring = _sheet_wiring(request)
        try:
            return redo_plan(
                engine,
                storyboard_id,
                kind,
                scene,
                capabilities=wiring["capabilities"],
                integration_id=wiring["integration_id"],
                overrides=sheet_overrides(engine, storyboard_id),
                resolution=wiring["resolution"],
                stills_model=getattr(wiring["image_adapter"], "model", None),
            )
        except SceneRedoRefused as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc

    @router.post("/storyboards/{storyboard_id}/redo")
    def post_scene_redo(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        cmd: SceneRedoCommand,
    ) -> Any:
        """Redo one scene alone, or the film's sound; every other take and shot is reused.

        200 when it is done (a card or the sound at 0 credits; a paid redo once the Owner's
        yes for THIS redo plan was spent), 202 with his question, 409 with the reason nothing
        was bought, 404 for an unknown storyboard or scene.
        """
        engine = request.app.state.engine
        settings = request.app.state.settings
        storage = getattr(request.app.state, "media_storage_root", None)
        paid = cmd.kind in ("still", "motion")
        wiring = _sheet_wiring(request) if paid else {}
        try:
            return redo_scene(
                engine,
                storyboard_id,
                str(uuid4()),
                kind=cmd.kind,
                scene_index=cmd.scene_index,
                plan_hash=cmd.plan_hash,
                image_adapter=wiring.get("image_adapter"),
                adapter_for_model=wiring.get("adapter_for_model"),
                capabilities=wiring.get("capabilities"),
                account=wiring.get("account"),
                integration_id=wiring.get("integration_id"),
                registry=getattr(request.app.state, "registry", None),
                overrides=sheet_overrides(engine, storyboard_id) if paid else None,
                resolution=wiring.get("resolution"),
                settings=settings,
                ffmpeg_path=getattr(settings, "ffmpeg_path", None),
                storage_root=Path(storage) if storage else None,
                note=cmd.note,
                allow_over_budget=cmd.allow_over_budget,
            )
        except SceneRedoRefused as exc:
            if exc.http_status == 202:
                return JSONResponse(status_code=202, content=exc.as_dict())
            raise HTTPException(status_code=exc.http_status, detail=exc.as_dict()) from exc

    @router.post("/takes/{take_id}/decision")
    def post_take_decision(
        request: Request,
        take_id: Annotated[str, FPath(min_length=1, max_length=36)],
        cmd: TakeDecisionCommand,
    ) -> dict:
        """The Owner's look at a paid take on the contact sheet: APPROVED or REJECTED."""
        try:
            return decide_sheet_take(request.app.state.engine, take_id, cmd.decision, note=cmd.note)
        except SheetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/takes/{take_id}/file")
    def get_take_file(
        request: Request,
        take_id: Annotated[str, FPath(min_length=1, max_length=36)],
    ) -> FileResponse:
        """A paid take's picture or clip, for the contact sheet."""
        with Session(request.app.state.engine) as session:
            take = session.get(SceneTake, take_id)
            path = Path(take.path) if take is not None and take.path else None
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Fișierul înregistrării nu există.")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    @router.get("/storyboards/{storyboard_id}/scenes/{scene_index}/card-preview")
    def get_card_preview(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
        scene_index: Annotated[int, FPath(ge=1, le=200)],
    ) -> Response:
        """A card scene's last frame, composed locally from its verified numbers: 0 credits."""
        try:
            picture = card_preview_png(
                request.app.state.engine,
                storyboard_id,
                scene_index,
                ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
            )
        except SheetNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SheetChoiceRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=picture, media_type="image/png")

    @router.post("/storyboards/{storyboard_id}/prompts")
    def write_prompts(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        """Write the master visual bible and the full prompt package for every shot.

        The step between an approved story and the generator. It refuses a film whose story
        has not been read and passed: describing shots is the last thing before money.
        """
        try:
            return write_shot_prompts(
                request.app.state.engine,
                getattr(request.app.state, "registry", None),
                storyboard_id,
                str(uuid4()),
            )
        except PromptError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/storyboards/{storyboard_id}/production-package")
    def read_production_package(
        request: Request,
        storyboard_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        """Everything the generator is given, and everything a person needs to audit it."""
        try:
            return production_package(request.app.state.engine, storyboard_id)
        except PromptError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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

    @router.post("/characters/{character_id}/reference-set", status_code=201)
    def post_character_reference_set(
        request: Request,
        character_id: Annotated[str, FPath(min_length=36, max_length=36)],
    ) -> dict:
        """Produce this character's reference pictures. The Owner's act, never the day's.

        It spends image credits, so nothing in the runbook calls it: the Owner asks, the
        budget is asked before the first slot, and STOP AUTONOMY refuses it like any other
        autonomous work. A slot the vendor refused stays null and is named in the answer.
        """
        try:
            return generate_character_reference_set(
                request.app.state.engine,
                request.app.state.credential_vault,
                character_id,
                str(uuid4()),
                # A test injects its adapter here, exactly as the render route lets it.
                image_adapter=getattr(request.app.state, "image_adapter", None),
                storage_root=REFERENCE_STORAGE_ROOT,
            )
        except ReferenceSetError as exc:
            raise HTTPException(
                status_code=404 if exc.reason == "NO_CHARACTER" else 409,
                detail={"error": exc.reason, "message": str(exc)},
            ) from exc

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
        # Same ceiling as the day's quality control: without `settings=` the default of half
        # the scenes applies and the Owner's max_fallback_scenes is read by nobody here. And
        # the same eye on the pictures, for the same reason: a film the Owner measures himself
        # is measured by what the day would have measured, or the two readings of one film
        # disagree about which gates ever ran.
        return evaluate_media_qc(
            engine,
            asset_id,
            correlation_id,
            settings=request.app.state.settings,
            registry=getattr(request.app.state, "registry", None),
            ffmpeg_path=getattr(request.app.state.settings, "ffmpeg_path", None),
        )

    return router
