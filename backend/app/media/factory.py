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

from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.economy.prices import price_lookup
from app.integrations.discovery import production_resource
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.integrations.vault import CredentialVault
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_base import ImageProvider, ImageResult, TTSProvider, VideoProvider
from app.providers.media_http import MediaProviderError, MediaProviderNotConfigured
from app.providers.openai_media import OpenAIImageAdapter
from app.providers.runway import RunwayImageAdapter, RunwayVideoAdapter

#: Statuses that mean the vendor itself answered. Anything else is an untested claim.
VERIFIED_STATUSES = ("VERIFIED", "ACCESS_VERIFIED")


# ------------------------------------------------- paid vendors stay off the whole-film path
#
# The legacy whole-film render (POST /media/render/{id} and the TEST day's media stage) shows
# no price and asks nothing per step. In TEST it could still buy a whole film from the real
# Runway connection. Real paid media is bought only through the shooting sheet's steps, under
# the Owner's yes bound to the sheet's plan_hash, in every environment, so the legacy path
# refuses whenever it would hand a real paid vendor adapter to the render.
#
# The marker is where the adapter's class comes from, not a flag each vendor must remember to
# set: every module under app/providers that is not one of the free ones below is a vendor,
# and an adapter whose class (or any base) is defined there is paid. A sixth vendor added
# tomorrow is paid until someone lists its module here, in review. The same list is what the
# static scan of the day's paid call sites reads (tests/test_no_paid_path_escapes.py).

#: The provider modules that cost nothing: interfaces, the deterministic stand-ins, the
#: registry and the transport helpers the vendor adapters share.
FREE_PROVIDER_MODULES = frozenset(
    {
        "app.providers",
        "app.providers.base",
        "app.providers.media_base",
        "app.providers.analytics_base",
        "app.providers.publishing_base",
        "app.providers.deterministic_analytics",
        "app.providers.deterministic_media",
        "app.providers.deterministic_pub",
        "app.providers.registry",
        "app.providers.retry",
        "app.providers.media_http",
    }
)
_PROVIDERS_PACKAGE = "app.providers"


class PaidVendorRefused(RuntimeError):
    """The legacy whole-film path would have handed a real paid vendor to the render.

    ``vendors`` names them (each adapter's PROVIDER_NAME); ``message_ro`` is the Owner's.
    """

    def __init__(self, vendors: list[str]) -> None:
        self.vendors = sorted(set(vendors))
        self.message_ro = (
            "Folosește foaia de filmare: calea veche de randare a filmului întreg ar fi "
            f"cumpărat de la un furnizor real ({', '.join(self.vendors)}). Imaginile, mișcarea "
            "și narațiunea plătite se cumpără doar prin pașii foii de filmare, fiecare cu "
            "aprobarea Proprietarului legată de planul văzut (plan_hash), în orice mediu. "
            "În mediul TEST rularea zilnică nu cumpără nimic de la furnizorii reali: filmul "
            "așteaptă pe foaia de filmare. În PRODUCTION rularea zilnică urcă singură foaia, "
            "pas cu pas, după regula Proprietarului pentru pașii plătiți. Mediul și regula le "
            "schimbă doar Proprietarul. Nimic nu a fost cumpărat."
        )
        super().__init__(self.message_ro)


def is_paid_vendor_class(cls: type) -> bool:
    """Whether this class, or any class it inherits from, is a paid vendor's adapter."""
    for klass in getattr(cls, "__mro__", ()):
        module = str(getattr(klass, "__module__", "") or "")
        inside = module == _PROVIDERS_PACKAGE or module.startswith(_PROVIDERS_PACKAGE + ".")
        if inside and module not in FREE_PROVIDER_MODULES:
            return True
    return False


def is_paid_vendor_adapter(adapter: object) -> bool:
    """Whether calling this adapter would reach a real paid vendor. A fake, a local stand-in
    and None are not; the class actually run decides, so a mock is never mistaken for one."""
    return adapter is not None and is_paid_vendor_class(type(adapter))


def _vendor_name(adapter: object) -> str:
    return str(getattr(adapter, "PROVIDER_NAME", None) or type(adapter).__name__)


def paid_vendors_of(adapters: Any) -> list[str]:
    """The names of the real paid vendors among ``adapters`` (any iterable, Nones allowed)."""
    return sorted({_vendor_name(a) for a in adapters if is_paid_vendor_adapter(a)})


def legacy_render_vendors(
    engine: Engine,
    storyboard_id: str,
    *,
    image: Any = None,
    image_chain: Any = None,
    tts: Any = None,
    tts_for_scene: Any = None,
    voice_segments_for_scene: Any = None,
) -> list[str]:
    """Every real paid vendor the whole-film render would be handed for this storyboard:
    its image adapter and chain, its voice, and each scene's voice and speakers' voices.

    Reads the adapters the caller already resolved (the plan builds them, 0 credits) and
    calls none of them. The motion model is chosen per scene inside the render, so it is
    guarded where it is chosen (`guard_motion_chooser`).
    """
    from app.media.models import StoryboardScene  # noqa: PLC0415

    found: list[Any] = [image, tts, *(image_chain or [])]
    with Session(engine) as session:
        indexes = [
            int(index)
            for index in session.scalars(
                select(StoryboardScene.scene_index).where(
                    StoryboardScene.storyboard_id == storyboard_id
                )
            )
        ]
    for index in indexes:
        scene = {"scene_index": index}
        if callable(tts_for_scene):
            found.append(tts_for_scene(scene))
        if callable(voice_segments_for_scene):
            for part in voice_segments_for_scene(scene) or []:
                found.append(part.get("adapter") if isinstance(part, dict) else None)
    return paid_vendors_of(found)


def guard_motion_chooser(chooser: Any) -> Any:
    """``chooser`` (the render's ``motion_chooser``), refusing a real paid video adapter.

    The refusal is raised where the model is chosen, before the adapter is used for anything:
    not a quote, not a balance read, not a shot. None stays None.
    """
    if chooser is None:
        return None

    def guarded(*args: Any, **kwargs: Any) -> Any:
        adapter, decision = chooser(*args, **kwargs)
        if is_paid_vendor_adapter(adapter):
            raise PaidVendorRefused([_vendor_name(adapter)])
        return adapter, decision

    return guarded


def abandon_unfinished_renders(
    engine: Engine, storyboard_id: str, since: str, reason: str
) -> list[str]:
    """Fail the storyboard's renders started at or after ``since`` and left unfinished by a
    refusal raised inside them (`PaidVendorRefused`), so no job stays RUNNING."""
    from app.media.models import VideoRenderJob  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415

    failed: list[str] = []
    with Session(engine) as session, session.begin():
        for job in session.scalars(
            select(VideoRenderJob).where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status.not_in(("COMPLETED", "FAILED")),
                VideoRenderJob.started_at >= since,
            )
        ):
            job.status = "FAILED"
            job.execution_log = reason[-8000:]
            job.finished_at = utc_now()
            failed.append(job.id)
    return failed


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


def reference_model_for_storyboard(
    engine: Engine, storyboard_id: str, model_id: str | None, integration_id: str | None = None
) -> str | None:
    """Choose a discovered reference sibling on the same configured RunPod connection."""
    from app.media.models import CharacterBible, MediaAsset, StoryboardScene  # noqa: PLC0415
    from app.providers.runpod.models import reference_spec, serverless_catalogue  # noqa: PLC0415

    if not model_id or reference_spec(model_id):
        return model_id
    with Session(engine) as session:
        selection = session.get(ServiceSelection, "image")
        connection_id = integration_id or (selection.integration_id if selection else None)
        connection = session.get(Integration, connection_id) if connection_id else None
        if (
            connection is None
            or connection.kind != "runpod"
            or connection.status not in VERIFIED_STATUSES
        ):
            return model_id
        ids = {
            cid
            for scene in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
            for cid in scene.character_ids_json or []
            if isinstance(cid, str)
        }
        has_picture = False
        for person in session.scalars(select(CharacterBible).where(CharacterBible.id.in_(ids))):
            for asset_id in (person.reference_assets_json or {}).values():
                asset = session.get(MediaAsset, str(asset_id)) if asset_id else None
                if asset is not None and Path(asset.uri_or_path).is_file():
                    has_picture = True
                    break
        if not has_picture:
            return model_id
        for entry in serverless_catalogue()["models"]:
            candidate = str(entry.get("id") or "")
            spec = reference_spec(candidate)
            if (
                spec
                and spec.get("text_model") == model_id
                and production_resource(session, connection.id, "MODEL", candidate, "image")
                is not None
            ):
                return candidate
    return model_id


def reference_image_adapter(engine: Engine, storyboard_id: str, adapter: Any) -> Any:
    """Resolve before pricing; preserve the source adapter and share a prepared route per batch."""
    from app.providers.runpod.adapters import RunPodImageAdapter  # noqa: PLC0415
    from app.providers.runpod.client import RunPodClient  # noqa: PLC0415

    if not isinstance(adapter, RunPodImageAdapter) or not adapter.integration_id:
        return adapter
    model = reference_model_for_storyboard(
        engine, storyboard_id, adapter.model, adapter.integration_id
    )
    if not model or model == adapter.model:
        return adapter
    cached = getattr(adapter, "_reference_route_cache", None)
    if not isinstance(cached, dict):
        cached = {}
        adapter._reference_route_cache = cached
    selected = cached.get(model)
    if selected is None:
        selected = RunPodImageAdapter(
            adapter.config,
            engine,
            model=model,
            integration_id=adapter.integration_id,
            storage_root=adapter.storage_root,
        )
        selected.core.transport = adapter.core.transport
        if isinstance(selected.core.client, RunPodClient) and isinstance(
            adapter.core.client, RunPodClient
        ):
            selected.core.client.transport = adapter.core.client.transport
        cached[model] = selected
    with Session(engine) as session:
        resource = production_resource(
            session, str(adapter.integration_id), "MODEL", model, "image"
        )
        if resource is not None:
            selected.model_metadata = dict(resource.api_metadata)
    return selected


def image_provider(engine: Engine, vault: CredentialVault) -> ImageProvider | None:
    """The image generator selected for the "image" purpose, if it has been verified."""
    with Session(engine) as session:
        row = _selected(session, "image")
        if row is None:
            return None
        kind, config = row.kind, dict(row.config)
        if kind == "runpod":
            from app.providers.runpod.wiring import connection  # noqa: PLC0415

            production = session.get(MediaProductionConfig, row.id)
            model = production.image_model_id if production else None
            if production_resource(session, row.id, "MODEL", model, "image") is None:
                return None
            return connection(engine, vault, row, model, "image")
        if kind == "comfyui":
            from app.providers.comfyui import ComfyImageAdapter  # noqa: PLC0415

            production = session.get(MediaProductionConfig, row.id)
            model = production.image_model_id if production else None
            if production_resource(session, row.id, "MODEL", model, "image") is None:
                return None
            return _from_connection(ComfyImageAdapter(config, model), row.id)
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
        if kind == "runpod":
            from app.providers.runpod.wiring import connection  # noqa: PLC0415

            if (
                production_resource(session, row.id, "MODEL", resolved.get("model_id"), "image")
                is None
            ):
                return None
            return connection(engine, vault, row, resolved.get("model_id"), "image")
        if kind == "comfyui":
            from app.providers.comfyui import ComfyImageAdapter  # noqa: PLC0415

            model = resolved.get("model_id")
            if production_resource(session, row.id, "MODEL", model, "image") is None:
                return None
            return _from_connection(ComfyImageAdapter(config, model), row.id)
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
                    secrets.get("api_key", ""),
                    config.get("voice_id"),
                    config.get("model"),
                    price_lookup=price_lookup(engine, "elevenlabs"),
                ),
                row_id,
            )
    except MediaProviderNotConfigured:
        return None
    return None


def pronunciation_locators(binding: Any) -> list[dict[str, str]]:
    """The vendor pronunciation dictionaries a character's voice binding names, as locators.

    ``pronunciation_rules`` holds two kinds of entry: hints for the voice artist ({"term",
    "hint"}), which never reach a vendor, and dictionaries the Owner created in his ElevenLabs
    account ({"pronunciation_dictionary_id", "version_id"}), which are sent by locator, at most
    three. Creating one is his act; the studio never writes to his account."""
    from app.providers.elevenlabs import checked_locators  # noqa: PLC0415

    rules = binding.get("pronunciation_rules") if isinstance(binding, dict) else None
    return checked_locators(rules)


def _binding_of(session: Session, character_id: Any) -> dict[str, Any]:
    from app.media.models import CharacterBible  # noqa: PLC0415 - read only for a voice

    if not character_id:
        return {}
    character = session.get(CharacterBible, str(character_id))
    binding = character.voice_binding_json if character is not None else None
    return dict(binding) if isinstance(binding, dict) else {}


# ------------------------------------------------------------- licences of what was bought
#
# A film may be published publicly only when every component of it carries commercial-use
# evidence (AR-15). For what a vendor made, the evidence is the Owner's own statement on the
# connection the component was bought through: his plan's terms and whether they allow
# commercial use, typed in Setări. The studio never infers a plan from a vendor's name.

#: The connection's answer that counts as evidence. Anything else, or nothing, is no evidence.
COMMERCIAL_USE_YES = "da"


def vendor_licence(session: Session, integration_id: Any) -> dict[str, Any]:
    """The licence the Owner recorded on a connection: {vendor, integration_id, terms,
    commercial_use (True | None), source}. ``commercial_use`` is True only on his explicit
    yes; a connection that is gone or says nothing is None, never False by assumption."""
    row = session.get(Integration, str(integration_id)) if integration_id else None
    if row is None:
        return {
            "vendor": None,
            "integration_id": integration_id or None,
            "terms": None,
            "commercial_use": None,
            "source": "missing_connection",
        }
    config = dict(row.config or {})
    terms = str(config.get("licence_terms") or "").strip() or None
    answer = str(config.get("commercial_use") or "").strip().lower()
    return {
        "vendor": row.kind,
        "integration_id": row.id,
        "terms": terms,
        "commercial_use": True if answer == COMMERCIAL_USE_YES else None,
        "source": "connection",
    }


def connection_of_model(session: Session, model_id: Any, purposes: tuple[str, ...]) -> str | None:
    """The connection a model belongs to: the one selected for one of ``purposes`` when it
    offers the model, else the first connection that discovered it. None when none did."""
    if not model_id:
        return None
    owners = [
        row.integration_id
        for row in session.scalars(
            select(ProviderResource).where(ProviderResource.remote_id == str(model_id))
        )
    ]
    if not owners:
        return None
    for purpose in purposes:
        selection = session.get(ServiceSelection, purpose)
        if selection is not None and selection.integration_id in owners:
            return selection.integration_id
    return owners[0]


def _voice_cache_key(voice: dict) -> tuple:
    """One adapter per connection, model, voice and character: a character's binding carries
    its own pronunciation dictionaries, which the first character on a shared voice must not
    decide for the others."""
    return (
        voice.get("integration_id"),
        voice.get("model_id"),
        voice.get("voice_id"),
        voice.get("character_id"),
    )


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
        # The character's own pronunciation dictionaries travel with its voice.
        locators = pronunciation_locators(_binding_of(session, resolved.get("character_id")))
    try:
        if kind == "elevenlabs":
            adapter = ElevenLabsTTSAdapter(
                secrets.get("api_key", ""),
                resolved.get("voice_id"),
                resolved.get("model_id"),
                price_lookup=price_lookup(engine, "elevenlabs"),
            )
            settings = resolved.get("voice_settings")
            if isinstance(settings, dict) and settings:
                adapter.voice_settings = settings
            adapter.pronunciation_locators = locators
            # The studio's own dictionary (names and acronyms), for every voice of the account;
            # the adapter sends it only with words that contain one of its terms.
            from app.providers.elevenlabs_lexicon import studio_dictionaries  # noqa: PLC0415

            adapter.studio_dictionaries = studio_dictionaries()
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
        if kind == "runpod":
            from app.providers.runpod.wiring import connection  # noqa: PLC0415

            if (
                production_resource(session, row.id, "MODEL", resolved.get("model_id"), "video")
                is None
            ):
                return None
            return connection(engine, vault, row, resolved.get("model_id"), "video")
        secrets = vault.decrypt(row.encrypted_secrets)
        resource = production_resource(session, row.id, "MODEL", resolved.get("model_id"), "video")
        if resource is None:
            # A discovered kind generates only with a model the account was seen to have.
            return None
        if kind == "comfyui":
            from app.providers.comfyui import ComfyVideoAdapter  # noqa: PLC0415

            return _from_connection(ComfyVideoAdapter(dict(row.config), resource.remote_id), row.id)
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

    The scene's kind (``scene_category``) and its story purpose travel with the requirement
    and come back on the decision. A card scene (DATA_CARD, TITLE_CARD, BLACK) is composed
    locally for 0 credits: the router is never asked for it and no adapter is built.
    """
    from app.media import production_policy  # noqa: PLC0415
    from app.media.cards import CARD_KINDS  # noqa: PLC0415

    kind = str(scene.get("scene_kind") or scene.get("scene_category") or "").upper()
    told: dict[str, Any] = {
        "scene_category": str(scene.get("scene_category") or kind or "GENERAL"),
        "story_purpose": scene.get("story_purpose"),
    }
    if kind in CARD_KINDS:
        return None, {
            "model_id": None,
            "reason": "Scenă compusă local (grafic, titlu sau ecran negru), 0 credite.",
            **told,
        }

    with Session(engine) as session:
        row = _selected(session, "video")
        if row is None:
            return None, {
                "model_id": None,
                "reason": "No connection is selected for video.",
                **told,
            }
        # A test films from the words (nothing is bought to make a first frame); production
        # moves the still the Director approved.
        tasks = (
            (production_policy.PROMPT_TO_VIDEO,) if environment == "TEST" else ("image_to_video",)
        )
        requirement = production_policy.SceneRequirement(
            purpose="video",
            tasks=tasks,
            tier=tier,
            scene_category=told["scene_category"],
            seconds=seconds,
            budget_usd=budget_usd,
            max_usd_per_second=max_usd_per_second,
        )
        decision = production_policy.choose_model(
            session,
            row.id,
            requirement,
            environment=environment,
            exclude=exclude,
            forced=forced_model,
        )
        integration_id = row.id
    decision = {**decision, **told}
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

    Returns the plan (recorded on the render job as production_json) plus `tts_for_scene`,
    `voice_segments_for_scene` (a scene's takes, one per speaker, for a scene whose lines
    name their speakers; None otherwise) and `video_for_scene` callables and the image
    adapter. A storyboard without a channel resolves at the Organization level, which is
    exactly what `tts_provider()` returned before policies existed, so nothing changes for
    videos that never named a channel.
    """
    from app.media.models import Storyboard
    from app.media.production_policy import resolve_storyboard_plan
    from app.media.speaker_voices import plan_speakers

    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise ValueError(f"Storyboard {storyboard_id} not found")
        plan = resolve_storyboard_plan(session, board)
        # One voice per speaker (S7): a scene whose lines say who speaks them gets one take
        # per speaker, each in that character's voice, recorded on the plan.
        plan_speakers(session, board, plan)
    adapters: dict[int, TTSProvider | None] = {}
    cache: dict[tuple, TTSProvider | None] = {}
    video_adapters: dict[int, VideoProvider | None] = {}
    video_cache: dict[tuple, VideoProvider | None] = {}
    for scene in plan["scenes"]:
        voice = scene["voice"]
        # The character too: its binding's dictionaries travel with its voice, so two characters
        # sharing one voice are two adapters (2026-10-12 audit).
        key = _voice_cache_key(voice)
        if key not in cache:
            cache[key] = tts_provider_for(engine, vault, voice)
        adapters[scene["scene_index"]] = cache[key]
        video = scene.get("video") or {}
        # A locked look can make the same model invalid for one scene and fine for another.
        video_key = (video.get("integration_id"), video.get("model_id"), bool(video.get("valid")))
        if video_key not in video_cache:
            video_cache[video_key] = video_provider_for(engine, vault, video)
        video_adapters[scene["scene_index"]] = video_cache[video_key]
    #: scene index -> its takes, each with the adapter of the voice it is spoken in (None
    #: when that voice has no usable adapter: the scene's own voice then speaks the take).
    takes: dict[int, list[dict]] = {}
    for scene in plan["scenes"]:
        speakers = scene.get("speakers") or []
        if not speakers:
            continue
        built = []
        for take in speakers:
            voice = take["voice"]
            key = _voice_cache_key(voice)
            if key not in cache:
                cache[key] = tts_provider_for(engine, vault, voice)
            built.append(
                {
                    "speaker": take["speaker"],
                    "character_id": take["character_id"],
                    "text": take["text"],
                    "adapter": cache[key],
                    "voice_source": voice.get("speaker_source"),
                }
            )
        # A locked voice that cannot be used is never replaced by another voice: the take
        # would fall back to the scene's, which may be another character's lock. The scene
        # is then unspeakable in real voices, exactly as a scene whose first locked
        # character's voice is unusable already is (the render records placeholders).
        broken = [
            str(take.get("speaker") or "")
            for take, made in zip(speakers, built, strict=True)
            if take["voice"].get("speaker_source") == "character_lock" and made["adapter"] is None
        ]
        if broken:
            adapters[scene["scene_index"]] = None
            scene["speakers_note"] = (
                "The locked voice of "
                + ", ".join(broken)
                + " cannot be used; no other voice may speak a locked character, so the "
                "scene has no real voice until the lock is fixed."
            )
        takes[scene["scene_index"]] = built

    def tts_for_scene(scene: dict) -> TTSProvider | None:
        index = scene.get("scene_index")
        return adapters.get(index) if isinstance(index, int) else None

    def voice_segments_for_scene(scene: dict) -> list[dict] | None:
        index = scene.get("scene_index")
        return takes.get(index) if isinstance(index, int) else None

    def video_for_scene(scene: dict) -> VideoProvider | None:
        index = scene.get("scene_index")
        return video_adapters.get(index) if isinstance(index, int) else None

    resolved_image = plan["purposes"].get("image") or {}
    # The vendors this film's stills may be drawn by, in order. One long in a studio whose
    # Owner approved no alternative, which is every studio until he does.
    from app.services import studio_environment  # noqa: PLC0415

    chain = image_adapter_chain(
        engine, vault, resolved_image, environment=studio_environment(engine)
    )
    #: asset id -> the bytes of that reference, read once per render.
    loaded: dict[str, bytes] = {}

    def reference_for_scene(scene: dict) -> dict | None:
        return reference_payload(engine, scene.get("character_ids"), cache=loaded)

    return {
        "plan": plan,
        "tts_for_scene": tts_for_scene,
        "voice_segments_for_scene": voice_segments_for_scene,
        "video_for_scene": video_for_scene,
        # The hierarchy's image choice, when it resolves to a usable adapter; else the
        # Organization's selection, exactly as before policies existed.
        "image": (chain[0] if chain else None) or image_provider(engine, vault),
        "image_chain": chain,
        "reference_for_scene": reference_for_scene,
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
        "Niciun serviciu ales pentru {purpose}. Alege conexiunea în Setări → Video și sunet → "
        "Servicii alese pentru producție."
    ),
    "NOT_VERIFIED": (
        "{name} este ales pentru {purpose}, dar cheia nu este verificată. Apasă «Verifică "
        "accesul» pe conexiune."
    ),
    "NO_DEFAULT": (
        "{name} este verificat și ales pentru {purpose}, dar nu are {needs}. Alege-le pe cardul "
        "conexiunii (Setări → Video și sunet), sau setează-le per canal în politica de producție."
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
                elif row.kind in ("runway", "comfyui"):
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
                elif row.kind == "runpod" and purpose == "image":
                    # RunPod Serverless: verified (endpoints read, never a /run), its model
                    # selected, and the Owner's bucket configured (RunPod keeps a result 30 min).
                    from app.providers.runpod.config import RunPodConfig  # noqa: PLC0415

                    config = RunPodConfig.from_integration(
                        dict(row.config or {}), vault.decrypt(row.encrypted_secrets)
                    )
                    selected = production is not None and (
                        production_resource(
                            session, row.id, "MODEL", production.image_model_id, "image"
                        )
                        is not None
                    )
                    if not selected:
                        status, needs = "NO_DEFAULT", "un model imagine implicit"
                    elif not config.ready_for_generation:
                        status, needs = "NO_DEFAULT", "bucketul de rezultate (S3 / R2) configurat"
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


# ------------------------------------------------- a second vendor, and a character's face


def accepts_reference_image(adapter: object) -> bool:
    """Whether this adapter can be handed a character's reference picture.

    Asked before one is passed, rather than passed in hope: an adapter that ignores it would
    let the studio report that a scene was drawn from the character's sheet when it was drawn
    from the words alone. Silence is not a capability, so an adapter that says nothing is no.
    """
    return bool(getattr(adapter, "ACCEPTS_REFERENCE_IMAGE", False))


def reference_payload(
    engine: Engine, character_ids: list[str] | None, *, cache: dict[str, bytes] | None = None
) -> dict | None:
    """This scene's reference picture with its bytes, ready for an adapter that takes one.

    Raises `ReferenceRequired` when a character whose look is locked has no reference the
    studio can read: the scene is not drawn at all rather than drawn from an invented face.
    A character with no lock and no reference simply has none, and the still is drawn from
    the prompt as it was before any of this existed.
    """
    from app.media.services import ReferenceRequired, image_reference_for_scene  # noqa: PLC0415

    reference = image_reference_for_scene(engine, character_ids)
    if reference is None:
        return None
    held = cache if cache is not None else {}
    asset_id = reference["asset_id"]
    if asset_id not in held:
        try:
            held[asset_id] = Path(reference["path"]).read_bytes()
        except OSError as exc:
            if reference["required"]:
                raise ReferenceRequired(
                    f"{reference['canonical_name']} are înfățișarea blocată, iar imaginea de "
                    "referință nu poate fi citită de pe disc; produ setul de referințe din nou."
                ) from exc
            return None
    return {**reference, "bytes": held[asset_id]}


def image_adapter_chain(
    engine: Engine,
    vault: CredentialVault,
    resolved: dict,
    *,
    environment: str | None = None,
) -> list[ImageProvider]:
    """The image vendors this purpose may be drawn by, in the order they are to be tried.

    The resolved selection first, then at most one alternative the Owner approved (see
    `production_policy.approved_alternatives`). In TEST the order is by the price the studio
    has recorded, cheapest first, because a test buys the cheapest model that can do the job
    and an approved alternative does not change that rule; an unpriced model cannot be proven
    cheapest, so it keeps its place behind the priced ones.
    """
    from app.media.production_policy import estimate_cost_usd  # noqa: PLC0415

    selections = [resolved, *(resolved.get("fallbacks") or [])]
    built: list[tuple[dict, ImageProvider]] = []
    for selection in selections:
        adapter = image_provider_for(engine, vault, selection)
        if adapter is not None:
            built.append((selection, adapter))
    if (environment or "TEST") != "TEST" or len(built) < 2:
        return [adapter for _selection, adapter in built]
    with Session(engine) as session:
        prices = [
            estimate_cost_usd(
                session, str(selection.get("integration_id")), selection.get("model_id"), images=1
            )
            for selection, _adapter in built
        ]
    order = sorted(
        range(len(built)),
        # (unpriced last, price, original order): a stable sort that never puts a model
        # nobody priced in front of one the studio can prove is cheap.
        key=lambda i: (prices[i] is None, prices[i] if prices[i] is not None else 0.0, i),
    )
    return [built[i][1] for i in order]


async def still_from_chain(
    engine: Engine,
    adapters: list[ImageProvider],
    prompt: str,
    *,
    width: int = 1080,
    height: int = 1920,
    style: str | None = None,
    extra: dict | None = None,
) -> tuple[ImageResult, list[dict]]:
    """Draw one still, trying the next approved vendor when the first refuses.

    Returns the picture and what each attempt was: which connection and model drew it, whether
    it answered, and what it is worth at the price the studio has recorded — None when no price
    covers it, never zero. When every approved vendor refuses, the last refusal is raised with
    the attempts attached, so the caller does exactly what it did before a chain existed: the
    placeholder still, which QC blocks from publication.

    A reference picture in `extra` is only passed to an adapter that says it can take one; for
    the others it is dropped and the attempt records that the still was drawn from words.
    """
    from app.media.production_policy import estimate_cost_usd  # noqa: PLC0415

    attempts: list[dict] = []
    last: MediaProviderError | None = None
    reference = (extra or {}).get("reference_image")
    for adapter in adapters:
        integration_id = getattr(adapter, "integration_id", None)
        model_id = getattr(adapter, "model", None)
        with Session(engine) as session:
            estimate = (
                estimate_cost_usd(session, integration_id, model_id, images=1)
                if integration_id and model_id
                else None
            )
        carries_reference = bool(reference) and accepts_reference_image(adapter)
        asked = dict(extra or {})
        if reference and not carries_reference:
            asked.pop("reference_image", None)
        record = {
            "provider": getattr(adapter, "PROVIDER_NAME", "UNKNOWN_IMAGE_PROVIDER"),
            "integration_id": integration_id,
            "model": model_id,
            "images": 1,
            "reference_image": carries_reference,
            "estimated_usd": estimate,
            "succeeded": False,
            "error": None,
        }
        try:
            result = await adapter.generate_image(
                prompt, width=width, height=height, style=style, extra=asked or None
            )
        except MediaProviderError as exc:
            record["error"] = str(exc)[:300]
            attempts.append(record)
            last = exc
            continue
        record["succeeded"] = True
        attempts.append(record)
        return result, attempts
    if last is None:  # pragma: no cover - a chain is never empty in the render path
        last = MediaProviderError("No image vendor is available for this scene")
    # The attempts travel with the refusal: a scene the books cannot see is a scene nobody
    # priced, and two lost stills used to leave the day's spending at zero.
    last.attempts = attempts  # type: ignore[attr-defined]
    raise last
