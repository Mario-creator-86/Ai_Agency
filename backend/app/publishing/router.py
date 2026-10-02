"""Phase 6 FastAPI router for Autonomous Publishing & Distribution endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.factual.models import ScriptDraft
from app.integrations.services import selected_youtube
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.media.production_policy import ChannelPolicyCommand, PolicyError, set_channel_policy
from app.providers.publishing_base import PublishingProvider
from app.providers.youtube import YouTubeProvider, youtube_provider_from_settings
from app.publishing.schemas import (
    ChannelView,
    ConfigureChannelCommand,
    CreatePublicationIntentCommand,
    PublicationView,
    PublishingGateEvaluationView,
    PublishPolicyCommand,
    PublishPolicyResult,
)
from app.publishing.services import (
    PublicationNotResolvable,
    PublishingAssetNotFound,
    PublishingGateError,
    PublishPolicyError,
    change_publish_policy,
    configure_channel,
    create_publication_intent,
    evaluate_publishing_gate,
    execute_publication,
    get_channel,
    get_publication,
    list_channels,
    list_publications,
    resolve_publication,
    seed_default_channels,
)
from app.security import require_owner
from app.services import CommandConflict
from app.wording import settings_place
from app.youtube.models import YouTubeConnection

PUBLISHER_NOT_CONFIGURED_DETAIL = {
    "error": "PublisherNotConfigured",
    "message": (
        "Nu este configurată nicio conexiune YouTube, deci nu se poate publica nimic. "
        f"Adaugă și verifică o conexiune YouTube în {settings_place('social')}."
    ),
    "required_settings": [
        "STUDIO_YOUTUBE_CLIENT_ID",
        "STUDIO_YOUTUBE_CLIENT_SECRET",
        "STUDIO_YOUTUBE_REFRESH_TOKEN",
    ],
}


class ResolvePublicationCommand(BaseModel):
    """The Owner's answer about a publication the studio could not settle (PUB-12): the video
    is on the channel, with its id, or it is not."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    found: bool
    remote_video_id: str | None = Field(
        default=None, min_length=6, max_length=20, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @model_validator(mode="after")
    def _found_names_the_video(self) -> ResolvePublicationCommand:
        if self.found and not self.remote_video_id:
            raise ValueError(
                "„Există” cere ID-ul videoclipului de pe YouTube (partea de după /shorts/ "
                "sau watch?v=)."
            )
        return self


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
    prefix = "youtube_connection:"
    identifier = reference.removeprefix(prefix) if reference.startswith(prefix) else None
    try:
        configured = selected_youtube(
            request.app.state.engine,
            request.app.state.credential_vault,
            identifier,
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
    if channel and channel["status"] != "AUTHENTICATED":
        raise HTTPException(
            409,
            "Leagă canalul de un cont YouTube conectat în Distribuție → Sloturi de canal "
            "înainte de publicare.",
        )
    return yt


def create_publishing_router() -> APIRouter:
    router = APIRouter(prefix="/publishing", dependencies=[Depends(require_owner)])

    @router.get("/channels")
    def get_all_channels(request: Request) -> dict:
        """Read-only listing. Seeding is an explicit command, never a side effect of a GET.

        This used to ask `selected_youtube()` whether a publisher existed, which refuses to
        answer while several accounts are connected and no channel names one — so a studio
        with two connected accounts got a 500 here and the screen said "Internal error" for
        both channels and publications. Publishing is per slot, so the answer is per slot:
        which connection each channel is bound to, and which accounts are available to bind.
        """
        engine = request.app.state.engine
        settings = request.app.state.settings
        channels = list_channels(engine)
        with Session(engine) as session:
            accounts = [
                {
                    "id": row.id,
                    "name": row.name,
                    "status": row.status,
                    "channel_title": row.remote_channel_title,
                    "remote_channel_id": row.remote_channel_id,
                }
                for row in session.scalars(
                    select(YouTubeConnection).order_by(YouTubeConnection.created_at)
                )
            ]
        connected = [a for a in accounts if a["status"] == "CONNECTED"]
        bound = [c for c in channels if c.get("publisher_ready")]
        return {
            "channels": channels,
            "youtube_accounts": accounts,
            "publisher_configured": bool(bound)
            or bool(getattr(settings, "youtube_credentials_present", False)),
            "binding_hint": (
                f"{len(connected)} conturi YouTube conectate, niciun slot de canal legat de "
                "vreunul. Alege contul pentru fiecare slot mai jos: publicarea și analytics "
                "folosesc legătura, nu contul „primul găsit”."
                if connected and not bound
                else ""
            ),
        }

    @router.post("/channels/seed")
    def seed_channels_endpoint(request: Request) -> dict:
        """Create the default channel slots if they are missing. Idempotent."""
        created = seed_default_channels(request.app.state.engine)
        return {"created": created, "channels": list_channels(request.app.state.engine)}

    @router.put("/channels/{channel_id}/production-policy")
    def set_production_policy(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: ChannelPolicyCommand,
    ) -> dict:
        """Policy, channel defaults and series rules. Locked character identities are not
        touched here: they live on the character and change only through an approved
        identity change."""
        try:
            return set_channel_policy(request.app.state.engine, channel_id, cmd)
        except PolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/channels/{channel_id}/publish-policy", response_model=PublishPolicyResult)
    def set_publish_policy(
        request: Request,
        channel_id: Annotated[str, Path(min_length=36, max_length=36)],
        cmd: PublishPolicyCommand,
    ) -> dict:
        """How this channel's autonomous uploads are released: private, unlisted or public.

        Owner-only, versioned by the channel's `policy_version`, idempotent by command id and
        recorded as `publishing.channel_policy_changed`; the same answers as the environment
        and the autonomy stop give (409 for a stale version or a reused id, 422 for a policy
        the studio refuses to set, such as "public" while in TEST).
        """
        try:
            return change_publish_policy(request.app.state.engine, channel_id, cmd)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CommandConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PublishPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        # The Owner's own intent carries the disclosure and the creator's channel as well: no
        # road to YouTube leaves them out.
        from app.publishing.services import publication_footer, with_footer  # noqa: PLC0415

        settings = request.app.state.settings
        footer = publication_footer(
            request.app.state.engine,
            getattr(settings, "ai_disclosure_url", None),
            getattr(settings, "creator_channel_title", None),
        )
        # The Owner's own intent is stamped with the channel policy in force, so the audit
        # reads the same for a hand-made publication as for an autonomous one. The gate then
        # holds it to that policy: an unlisted intent on a channel whose policy says private
        # is refused until the Owner sets the policy, which is the one place visibility is
        # decided. A private upload needs no stamp.
        channel = get_channel(request.app.state.engine, cmd.channel_id)
        visible = cmd.privacy_status != "private" or bool(cmd.scheduled_publish_time)
        policy_version = channel["policy_version"] if channel and visible else None
        try:
            return create_publication_intent(
                request.app.state.engine,
                cmd.channel_id,
                cmd.media_asset_id,
                cmd.title,
                with_footer(cmd.description, footer),
                cmd.tags,
                cmd.privacy_status,
                cmd.idempotency_key,
                str(cmd.command_id),
                cmd.scheduled_publish_time,
                policy_version=policy_version,
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

    @router.post("/publications/{publication_id}/resolve", response_model=PublicationView)
    def resolve_publication_endpoint(
        request: Request,
        publication_id: Annotated[str, Path(min_length=36, max_length=36)],
        command: ResolvePublicationCommand,
    ) -> dict:
        """The Owner settles a publication the studio could not verify by itself: «Există»
        with the video's id, or «Nu există». Idempotent by command id; nothing is uploaded
        here (a «Nu există» row is retried by the watchdog, which asks the channel first)."""
        try:
            return resolve_publication(
                request.app.state.engine,
                publication_id,
                found=command.found,
                remote_video_id=command.remote_video_id,
                command_id=str(command.command_id),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (CommandConflict, PublicationNotResolvable) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

        with engine.connect() as connection:
            title = connection.scalar(
                select(ScriptDraft.title)
                .join(Storyboard, Storyboard.script_draft_id == ScriptDraft.id)
                .join(VideoRenderJob, VideoRenderJob.storyboard_id == Storyboard.id)
                .where(VideoRenderJob.output_asset_id == asset_id)
            )
        if not title:
            raise HTTPException(
                422, "Video has no source script title; create an explicit publication intent"
            )
        # Empty optional metadata is preferable to invented topic tags or quality claims — but
        # the disclosure and the creator's channel are not optional: every film carries them.
        from app.publishing.services import publication_footer, with_footer  # noqa: PLC0415

        settings = request.app.state.settings
        description = with_footer(
            "",
            publication_footer(
                engine,
                getattr(settings, "ai_disclosure_url", None),
                getattr(settings, "creator_channel_title", None),
            ),
        )
        tags: list[str] = []
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
