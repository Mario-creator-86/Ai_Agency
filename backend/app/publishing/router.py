"""Phase 6 FastAPI router for Autonomous Publishing & Distribution endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from app.integrations.services import selected_youtube
from app.media.models import MediaAsset
from app.providers.publishing_base import PublishingProvider
from app.providers.youtube import YouTubeProvider, youtube_provider_from_settings
from app.publishing.schemas import (
    ChannelView,
    ConfigureChannelCommand,
    CreatePublicationIntentCommand,
    PublicationView,
    PublishingGateEvaluationView,
)
from app.publishing.services import (
    PublishingAssetNotFound,
    PublishingGateError,
    configure_channel,
    create_publication_intent,
    evaluate_publishing_gate,
    execute_publication,
    get_channel,
    get_publication,
    list_channels,
    list_publications,
    seed_default_channels,
)
from app.security import require_owner

PUBLISHER_NOT_CONFIGURED_DETAIL = {
    "error": "PublisherNotConfigured",
    "message": (
        "No YouTube credentials are configured, so nothing can be published. Set "
        "STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET and "
        "STUDIO_YOUTUBE_REFRESH_TOKEN in .env and restart the studio."
    ),
    "required_settings": [
        "STUDIO_YOUTUBE_CLIENT_ID",
        "STUDIO_YOUTUBE_CLIENT_SECRET",
        "STUDIO_YOUTUBE_REFRESH_TOKEN",
    ],
}


def get_active_publisher(request: Request) -> PublishingProvider:
    """Return the official YouTube provider, or refuse.

    There is deliberately no fallback to the simulated adapter: substituting a simulator at
    runtime would report a publication that does not exist (AGENTS.md).
    """
    override = getattr(request.app.state, "publishing_provider", None)
    if override is not None:
        return override
    # Bind a stored OAuth identity to the intended channel, never silently another account.
    channel = None
    publication_id = request.path_params.get("publication_id")
    if publication_id:
        publication = get_publication(request.app.state.engine, publication_id)
        if publication:
            channel = get_channel(request.app.state.engine, publication["channel_id"])
    elif "asset_id" in request.path_params:
        channel = next(
            (
                c
                for c in list_channels(request.app.state.engine)
                if c["channel_type"] == "MAIN_FACTUAL"
            ),
            None,
        )
    reference = (channel or {}).get("credentials_ref") or ""
    identifier = (
        reference.removeprefix("integration:") if reference.startswith("integration:") else None
    )
    try:
        configured = selected_youtube(
            request.app.state.engine, request.app.state.credential_vault, identifier
        )
    except ValueError:
        raise HTTPException(409, "Selected YouTube credentials are unavailable") from None
    yt: YouTubeProvider = configured or youtube_provider_from_settings(request.app.state.settings)
    if configured and channel and configured.channel_id != channel["remote_channel_id"]:
        raise HTTPException(
            409, "The selected YouTube account does not match the publication channel"
        )
    if not yt.is_configured:
        raise HTTPException(status_code=503, detail=PUBLISHER_NOT_CONFIGURED_DETAIL)
    return yt


def create_publishing_router() -> APIRouter:
    router = APIRouter(prefix="/publishing", dependencies=[Depends(require_owner)])

    @router.get("/channels")
    def get_all_channels(request: Request) -> dict:
        """Read-only listing. Seeding is an explicit command, never a side effect of a GET."""
        engine = request.app.state.engine
        settings = request.app.state.settings
        return {
            "channels": list_channels(engine),
            "publisher_configured": bool(
                selected_youtube(engine, request.app.state.credential_vault)
            )
            or bool(getattr(settings, "youtube_credentials_present", False)),
        }

    @router.post("/channels/seed")
    def seed_channels_endpoint(request: Request) -> dict:
        """Create the default channel slots if they are missing. Idempotent."""
        created = seed_default_channels(request.app.state.engine)
        return {"created": created, "channels": list_channels(request.app.state.engine)}

    @router.get("/channels/{channel_id}", response_model=ChannelView)
    def get_single_channel(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        ch = get_channel(request.app.state.engine, channel_id)
        if not ch:
            raise HTTPException(status_code=404, detail="Channel not found")
        return ch

    @router.post("/channels/{channel_id}/configure", response_model=ChannelView)
    def configure_channel_endpoint(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: ConfigureChannelCommand,
    ) -> dict:
        try:
            return configure_channel(
                request.app.state.engine,
                channel_id,
                cmd.channel_name,
                cmd.remote_channel_id,
                cmd.credentials_ref,
                cmd.upload_privacy_default,
                str(cmd.command_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/gate/evaluate/{media_asset_id}/{channel_id}", response_model=PublishingGateEvaluationView
    )
    def evaluate_gate(
        request: Request,
        media_asset_id: Annotated[str, Path(min_length=36, max_length=36)],
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        return evaluate_publishing_gate(request.app.state.engine, media_asset_id, channel_id)

    @router.get("/publications")
    def get_all_publications(request: Request) -> dict:
        return {"publications": list_publications(request.app.state.engine)}

    @router.get("/publications/{publication_id}", response_model=PublicationView)
    def get_single_publication(
        request: Request,
        publication_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        pub = get_publication(request.app.state.engine, publication_id)
        if not pub:
            raise HTTPException(status_code=404, detail="Publication not found")
        return pub

    @router.post("/publications/intent", response_model=PublicationView)
    def post_publication_intent(
        request: Request,
        cmd: CreatePublicationIntentCommand,
    ) -> dict:
        try:
            return create_publication_intent(
                request.app.state.engine,
                cmd.channel_id,
                cmd.media_asset_id,
                cmd.title,
                cmd.description,
                cmd.tags,
                cmd.privacy_status,
                cmd.idempotency_key,
                str(cmd.command_id),
                cmd.scheduled_publish_time,
            )
        except PublishingAssetNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": exc.message, "reasons": exc.reasons},
            ) from exc
        except PublishingGateError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "PublishingGateError",
                    "message": exc.message,
                    "reasons": exc.reasons,
                },
            ) from exc
        except SQLAlchemyError:
            raise HTTPException(
                status_code=500, detail="Database error creating publication intent"
            ) from None

    @router.post("/publications/{publication_id}/execute", response_model=PublicationView)
    def execute_publication_endpoint(
        request: Request,
        publication_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        publisher = get_active_publisher(request)
        correlation_id = str(uuid4())
        try:
            return execute_publication(
                request.app.state.engine,
                publisher,
                publication_id,
                correlation_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Publication execution failed: {exc}"
            ) from exc

    @router.post("/publish-asset/{asset_id}", response_model=PublicationView)
    def quick_publish_asset(
        request: Request,
        asset_id: Annotated[str, Path(min_length=36, max_length=36)],
    ) -> dict:
        """One-click pipeline: finds Channel A, checks gate, creates intent,
        and executes private upload."""
        engine = request.app.state.engine
        # Refuse before doing any work if there is no real publisher.
        publisher = get_active_publisher(request)
        seed_default_channels(engine)
        channels = [c for c in list_channels(engine) if c["channel_type"] == "MAIN_FACTUAL"]
        if not channels:
            raise HTTPException(status_code=404, detail="Channel A (MAIN_FACTUAL) is not present")
        channel = channels[0]
        if channel["status"] != "AUTHENTICATED":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "ChannelNotAuthenticated",
                    "message": (
                        f"Channel {channel['channel_name']!r} is {channel['status']}. Set its real "
                        "remote channel ID and credentials reference before publishing."
                    ),
                },
            )

        with engine.connect() as conn:
            asset = (
                conn.execute(MediaAsset.__table__.select().where(MediaAsset.id == asset_id))
                .mappings()
                .first()
            )
            if not asset:
                raise HTTPException(status_code=404, detail="Media asset not found")

        title = "Autonomous AI Studio: Shorts Release"
        description = (
            "Produced autonomously by Autonomous AI Studio with full provenance "
            "and QC verification. #shorts #ai"
        )
        tags = ["shorts", "autonomous", "ai", "technology"]
        cmd_id = uuid4()
        correlation_id = str(uuid4())

        try:
            intent = create_publication_intent(
                engine,
                channel["id"],
                asset_id,
                title,
                description,
                tags,
                "private",
                None,
                str(cmd_id),
            )
            return execute_publication(engine, publisher, intent["id"], correlation_id)
        except PublishingAssetNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": "NotFound", "message": exc.message, "reasons": exc.reasons},
            ) from exc
        except PublishingGateError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "PublishingGateError",
                    "message": exc.message,
                    "reasons": exc.reasons,
                },
            ) from exc

    return router
