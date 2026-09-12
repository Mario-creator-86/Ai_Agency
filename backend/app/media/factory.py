"""Resolve which media provider the studio may actually use for a render.

A provider is usable only when the Owner both selected it for a purpose and verified it — the
same rule publishing and analytics follow. `SAVED` means the credentials were typed in, not that
the vendor accepted them, and a render started against unaccepted credentials would fail
mid-pipeline after the Owner had been told generation was under way.

When nothing is usable this returns None. The caller then falls back to the deterministic
placeholder generators, and the asset it produces is labelled as a placeholder, so QC blocks it
from publication. That labelling is the whole point: a studio without media providers may still
assemble a video to look at, but it may never present one as publishable content.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.integrations.discovery import production_resource
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.integrations.vault import CredentialVault
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_base import ImageProvider, TTSProvider, VideoProvider
from app.providers.media_http import MediaProviderNotConfigured
from app.providers.openai_media import OpenAIImageAdapter
from app.providers.runway import RunwayImageAdapter, RunwayVideoAdapter

#: Statuses that mean the vendor itself answered. Anything else is an untested claim.
VERIFIED_STATUSES = ("VERIFIED", "ACCESS_VERIFIED")


def _selected(session: Session, purpose: str) -> Integration | None:
    selection = session.get(ServiceSelection, purpose)
    if selection is None or not selection.integration_id:
        return None
    row = session.get(Integration, selection.integration_id)
    if row is None or row.status not in VERIFIED_STATUSES:
        return None
    return row


def _runway_metadata(resource: ProviderResource | None) -> dict:
    """The model's contract from the catalog; research may add what the refresh could not."""
    if resource is None:
        return {}
    metadata = dict(resource.api_metadata)
    if isinstance(resource.capabilities, dict):
        for key in ("tasks", "ratios", "durations"):
            if key not in metadata and resource.capabilities.get(key) is not None:
                metadata[key] = resource.capabilities[key]
    return metadata


def _from_connection(adapter: _A, integration_id: str) -> _A:
    """Mark an adapter with the connection it was built from.

    The books price a scene by the model that made it, and a model belongs to a connection;
    without this the Accountant sees a still and a shot with no owner and reports them as
    unpriced. Set here, where the connection is known, rather than passed through every call.
    """
    if adapter is not None:
        # The adapters are vendor classes, not a studio protocol; the mark is an attribute
        # the Accountant reads and nothing else depends on.
        adapter.integration_id = integration_id  # type: ignore[attr-defined]
    return adapter


_A = TypeVar("_A")


def image_provider(engine: Engine, vault: CredentialVault) -> ImageProvider | None:
    """The image generator selected for the "image" purpose, if it has been verified."""
    with Session(engine) as session:
        row = _selected(session, "image")
        if row is None:
            return None
        kind, config = row.kind, dict(row.config)
        metadata: dict = {}
        if kind == "runway":
            production = session.get(MediaProductionConfig, row.id)
            resource = production_resource(
                session, row.id, "MODEL", production.image_model_id if production else None, "image"
            )
            if resource is None:
                return None
            config = {"model": resource.remote_id}
            metadata = _runway_metadata(resource)
        secrets = vault.decrypt(row.encrypted_secrets)
        row_id = row.id

    try:
        if kind == "openai_media":
            return _from_connection(
                OpenAIImageAdapter(secrets.get("api_key", ""), config.get("model")), row_id
            )
        if kind == "runway":
            return _from_connection(
                RunwayImageAdapter(secrets.get("api_key", ""), config.get("model"), metadata),
                row_id,
            )
    except MediaProviderNotConfigured:
        return None
    # A vendor with no adapter yet is not an error and not a silent substitution: the studio
    # simply has no image generator, and says so through the placeholder path.
    return None


def image_provider_for(
    engine: Engine, vault: CredentialVault, resolved: dict
) -> ImageProvider | None:
    """An image adapter for one resolved `image` selection (see production_policy)."""
    if not resolved or not resolved.get("valid") or not resolved.get("integration_id"):
        return None
    with Session(engine) as session:
        row = session.get(Integration, resolved["integration_id"])
        if row is None or row.status not in VERIFIED_STATUSES:
            return None
        kind, config = row.kind, dict(row.config)
        secrets = vault.decrypt(row.encrypted_secrets)
        metadata: dict = {}
        if kind == "runway":
            resource = production_resource(
                session, row.id, "MODEL", resolved.get("model_id"), "image"
            )
            if resource is None:
                return None
            config = {"model": resource.remote_id}
            metadata = _runway_metadata(resource)
        elif resolved.get("model_id"):
            config["model"] = resolved["model_id"]
    try:
        if kind == "openai_media":
            return _from_connection(
                OpenAIImageAdapter(secrets.get("api_key", ""), config.get("model")), row.id
            )
        if kind == "runway":
            return _from_connection(
                RunwayImageAdapter(secrets.get("api_key", ""), config.get("model"), metadata),
                row.id,
            )
    except MediaProviderNotConfigured:
        return None
    return None


def tts_provider(engine: Engine, vault: CredentialVault) -> TTSProvider | None:
    """The voice generator selected for the "voice" purpose, if it has been verified."""
    with Session(engine) as session:
        row = _selected(session, "voice")
        if row is None:
            return None
        kind, config = row.kind, dict(row.config)
        if kind == "elevenlabs":
            production = session.get(MediaProductionConfig, row.id)
            if production is None or not all(
                (
                    production_resource(session, row.id, "MODEL", production.model_id),
                    production_resource(session, row.id, "VOICE", production.voice_id),
                )
            ):
                return None
            config = {"model": production.model_id, "voice_id": production.voice_id}
        secrets = vault.decrypt(row.encrypted_secrets)
        row_id = row.id

    try:
        if kind == "elevenlabs":
            return _from_connection(
                ElevenLabsTTSAdapter(
                    secrets.get("api_key", ""), config.get("voice_id"), config.get("model")
                ),
                row_id,
            )
    except MediaProviderNotConfigured:
        return None
    return None


def tts_provider_for(engine: Engine, vault: CredentialVault, resolved: dict) -> TTSProvider | None:
    """A voice adapter for one resolved selection (see production_policy.resolve_purpose).

    Only a selection the resolver marked valid — a verified connection and discovered,
    available resources — becomes an adapter. Anything else returns None, and the render
    records a placeholder for that scene rather than guessing a voice.
    """
    if not resolved or not resolved.get("valid") or not resolved.get("integration_id"):
        return None
    with Session(engine) as session:
        row = session.get(Integration, resolved["integration_id"])
        if row is None or row.status not in VERIFIED_STATUSES:
            return None
        kind = row.kind
        secrets = vault.decrypt(row.encrypted_secrets)
    try:
        if kind == "elevenlabs":
            adapter = ElevenLabsTTSAdapter(
                secrets.get("api_key", ""), resolved.get("voice_id"), resolved.get("model_id")
            )
            settings = resolved.get("voice_settings")
            if isinstance(settings, dict) and settings:
                adapter.voice_settings = settings
            return _from_connection(adapter, row.id)
    except MediaProviderNotConfigured:
        return None
    return None


def video_provider_for(
    engine: Engine, vault: CredentialVault, resolved: dict
) -> VideoProvider | None:
    """A video adapter for one resolved `video` selection, carrying the model's contract.

    The model's tasks, ratios and durations come from the discovered resource, so the adapter
    generates with the terms the vendor published for that model rather than assumptions.
    """
    if not resolved or not resolved.get("valid") or not resolved.get("integration_id"):
        return None
    with Session(engine) as session:
        row = session.get(Integration, resolved["integration_id"])
        if row is None or row.status not in VERIFIED_STATUSES:
            return None
        kind = row.kind
        secrets = vault.decrypt(row.encrypted_secrets)
        resource = production_resource(session, row.id, "MODEL", resolved.get("model_id"), "video")
        if resource is None:
            # A discovered kind generates only with a model the account was seen to have.
            return None
        metadata = _runway_metadata(resource)
    try:
        if kind == "runway":
            return _from_connection(
                RunwayVideoAdapter(secrets.get("api_key", ""), resource.remote_id, metadata),
                row.id,
            )
    except MediaProviderNotConfigured:
        return None
    return None


def motion_for_scene(
    engine: Engine,
    vault: CredentialVault,
    scene: dict,
    *,
    environment: str,
    tier: str = "STANDARD",
    seconds: float = 0.0,
    budget_usd: float | None = None,
    forced_model: str | None = None,
    exclude: tuple[str, ...] = (),
    max_usd_per_second: float | None = None,
) -> tuple[VideoProvider | None, dict]:
    """The model that films this scene, chosen by requirement, with the reason it was chosen.

    The studio states what the scene needs — the task, the quality its tier demands, its
    length, what it may cost — and the router answers with a model. Which policy answers
    depends on the environment, and the environment is the studio's own state: a test takes
    the cheapest model that can do the job, production the least expensive that reaches the
    quality. The decision travels with the adapter so the page and the render job can both
    say why.
    """
    from app.media.production_policy import (  # noqa: PLC0415
        PROMPT_TO_VIDEO,
        SceneRequirement,
        choose_model,
    )

    with Session(engine) as session:
        row = _selected(session, "video")
        if row is None:
            return None, {"model_id": None, "reason": "No connection is selected for video."}
        # A test films from the words (nothing is bought to make a first frame); production
        # moves the still the Director approved.
        tasks = (PROMPT_TO_VIDEO,) if environment == "TEST" else ("image_to_video",)
        requirement = SceneRequirement(
            purpose="video",
            tasks=tasks,
            tier=tier,
            scene_category=str(scene.get("scene_category") or "GENERAL"),
            seconds=seconds,
            budget_usd=budget_usd,
            max_usd_per_second=max_usd_per_second,
        )
        decision = choose_model(
            session,
            row.id,
            requirement,
            environment=environment,
            exclude=exclude,
            forced=forced_model,
        )
        integration_id = row.id
    if not decision.get("model_id"):
        return None, decision
    adapter = video_provider_for(
        engine,
        vault,
        {"valid": True, "integration_id": integration_id, "model_id": decision["model_id"]},
    )
    return adapter, decision


def render_plan(engine: Engine, vault: CredentialVault, storyboard_id: str) -> dict:
    """Resolve the production hierarchy for a storyboard and build its adapters.

    Returns the plan (recorded on the render job as production_json) plus `tts_for_scene`
    and `video_for_scene` callables and the image adapter. A storyboard without a channel
    resolves at the Organization level, which is exactly what `tts_provider()` returned
    before policies existed, so nothing changes for videos that never named a channel.
    """
    from app.media.models import Storyboard
    from app.media.production_policy import resolve_storyboard_plan

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ValueError(f"Storyboard {storyboard_id} not found")
        plan = resolve_storyboard_plan(session, board)
    adapters: dict[int, TTSProvider | None] = {}
    cache: dict[tuple, TTSProvider | None] = {}
    video_adapters: dict[int, VideoProvider | None] = {}
    video_cache: dict[tuple, VideoProvider | None] = {}
    for scene in plan["scenes"]:
        voice = scene["voice"]
        key = (voice.get("integration_id"), voice.get("model_id"), voice.get("voice_id"))
        if key not in cache:
            cache[key] = tts_provider_for(engine, vault, voice)
        adapters[scene["scene_index"]] = cache[key]
        video = scene.get("video") or {}
        # A locked look can make the same model invalid for one scene and fine for another.
        video_key = (video.get("integration_id"), video.get("model_id"), bool(video.get("valid")))
        if video_key not in video_cache:
            video_cache[video_key] = video_provider_for(engine, vault, video)
        video_adapters[scene["scene_index"]] = video_cache[video_key]

    def tts_for_scene(scene: dict) -> TTSProvider | None:
        index = scene.get("scene_index")
        return adapters.get(index) if isinstance(index, int) else None

    def video_for_scene(scene: dict) -> VideoProvider | None:
        index = scene.get("scene_index")
        return video_adapters.get(index) if isinstance(index, int) else None

    return {
        "plan": plan,
        "tts_for_scene": tts_for_scene,
        "video_for_scene": video_for_scene,
        # The hierarchy's image choice, when it resolves to a usable adapter; else the
        # Organization's selection, exactly as before policies existed.
        "image": image_provider_for(engine, vault, plan["purposes"].get("image") or {})
        or image_provider(engine, vault),
    }


def describe(engine: Engine, vault: CredentialVault) -> dict[str, str | None]:
    """What the interface should say about media generation, without probing anything."""
    image = image_provider(engine, vault)
    voice = tts_provider(engine, vault)
    return {
        "image_provider": getattr(image, "PROVIDER_NAME", None),
        "voice_provider": getattr(voice, "PROVIDER_NAME", None),
    }


#: Why a purpose has no adapter, in the Owner's words. "NO_DEFAULT" is the case a verified,
#: selected connection lands in until a default model (and voice) is chosen — the one the
#: preflight used to report as "no verified provider", which sent the Owner to check a key
#: that was fine.
READINESS_MESSAGES = {
    "READY": "",
    "NO_SELECTION": (
        "Niciun serviciu ales pentru {purpose}. Alege conexiunea în Settings → Video și sunet → "
        "Serviciile alese pentru producție."
    ),
    "NOT_VERIFIED": (
        "{name} este ales pentru {purpose}, dar cheia nu este verificată. Apasă «Verifică "
        "accesul» pe conexiune."
    ),
    "NO_DEFAULT": (
        "{name} este verificat și ales pentru {purpose}, dar nu are {needs}. Alege-le pe cardul "
        "conexiunii (Settings → Video și sunet), sau setează-le per canal în politica de producție."
    ),
    "NO_ADAPTER": (
        "{name} este ales pentru {purpose}, dar studioul nu are încă un adaptor de generare "
        "pentru acest serviciu."
    ),
}
PURPOSE_LABEL = {"image": "Imagini", "voice": "Voce / TTS"}


def media_readiness(engine: Engine, vault: CredentialVault) -> dict[str, dict]:
    """Per purpose: whether an adapter exists and, if not, which step is missing.

    Reads the same rows the adapters read, probes nothing, and names the next action.
    """
    result: dict[str, dict] = {}
    with Session(engine) as session:
        for purpose in ("image", "voice"):
            selection = session.get(ServiceSelection, purpose)
            row = (
                session.get(Integration, selection.integration_id)
                if selection is not None and selection.integration_id
                else None
            )
            status, needs, name = "READY", "", ""
            if row is None:
                status = "NO_SELECTION"
            elif row.status not in VERIFIED_STATUSES:
                status, name = "NOT_VERIFIED", row.name
            else:
                name = row.name
                production = session.get(MediaProductionConfig, row.id)
                if row.kind == "elevenlabs":
                    ok = production is not None and all(
                        (
                            production_resource(
                                session, row.id, "MODEL", production.model_id, "voice"
                            ),
                            production_resource(session, row.id, "VOICE", production.voice_id),
                        )
                    )
                    if not ok:
                        status, needs = "NO_DEFAULT", "un model și o voce implicită"
                elif row.kind == "runway":
                    ok = production is not None and (
                        production_resource(
                            session, row.id, "MODEL", production.image_model_id, "image"
                        )
                        is not None
                    )
                    if not ok:
                        status, needs = "NO_DEFAULT", "un model imagine implicit"
                elif row.kind == "openai_media":
                    if not (row.config or {}).get("model"):
                        status, needs = "NO_DEFAULT", "un model configurat"
                else:
                    status = "NO_ADAPTER"
            result[purpose] = {
                "status": status,
                "connection": name or None,
                "message": READINESS_MESSAGES[status].format(
                    purpose=PURPOSE_LABEL[purpose], name=name, needs=needs
                ),
            }
    return result
