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

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import CredentialVault
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_base import ImageProvider, TTSProvider
from app.providers.media_http import MediaProviderNotConfigured
from app.providers.openai_media import OpenAIImageAdapter

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


def image_provider(engine: Engine, vault: CredentialVault) -> ImageProvider | None:
    """The image generator selected for the "image" purpose, if it has been verified."""
    with Session(engine) as session:
        row = _selected(session, "image")
        if row is None:
            return None
        kind, config = row.kind, dict(row.config)
        secrets = vault.decrypt(row.encrypted_secrets)

    try:
        if kind == "openai_media":
            return OpenAIImageAdapter(secrets.get("api_key", ""), config.get("model"))
    except MediaProviderNotConfigured:
        return None
    # A vendor with no adapter yet is not an error and not a silent substitution: the studio
    # simply has no image generator, and says so through the placeholder path.
    return None


def tts_provider(engine: Engine, vault: CredentialVault) -> TTSProvider | None:
    """The voice generator selected for the "voice" purpose, if it has been verified."""
    with Session(engine) as session:
        row = _selected(session, "voice")
        if row is None:
            return None
        kind, config = row.kind, dict(row.config)
        secrets = vault.decrypt(row.encrypted_secrets)

    try:
        if kind == "elevenlabs":
            return ElevenLabsTTSAdapter(
                secrets.get("api_key", ""), config.get("voice_id"), config.get("model")
            )
    except MediaProviderNotConfigured:
        return None
    return None


def describe(engine: Engine, vault: CredentialVault) -> dict[str, str | None]:
    """What the interface should say about media generation, without probing anything."""
    image = image_provider(engine, vault)
    voice = tts_provider(engine, vault)
    return {
        "image_provider": getattr(image, "PROVIDER_NAME", None),
        "voice_provider": getattr(voice, "PROVIDER_NAME", None),
    }
