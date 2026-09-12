"""One command that finishes what a verified connection leaves unfinished.

Connecting a vendor and choosing what it does for the studio are two different things, and
the second one was invisible: a studio with a verified Runway key and a verified ElevenLabs
key still reported "no image provider" and "no default voice", because nothing was selected
for the `image` purpose and no default model or voice had been picked. The Owner's reasonable
reading — "I connected it, use it" — was right, and the missing step was a form deep in
Settings.

So this is one Owner action that does exactly what the stored catalogue already determines,
and nothing else:

- **A service is selected for a purpose only when there is one candidate.** Two verified
  connections that both make images is a choice, and a choice belongs to the Owner; this
  reports the ambiguity instead of resolving it.
- **A default model or voice is the top of `rank_candidates`** — the same deterministic order
  the production hierarchy uses for `strategy: auto`, built from stored research annotations
  and, absent those, from the resource id. It is a fallback, not a rule: every channel,
  series, episode and scene may still override it, and a locked character identity wins.
- **Nothing already chosen is touched.** The command only fills what is empty, and reports
  every choice it made with the reason, so the Owner can change any of them in the same card.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.integrations.catalog import CATALOG
from app.integrations.discovery import (
    DISCOVERED_KINDS,
    ProductionCommand,
    production_resource,
    save_production,
)
from app.integrations.models import Integration, MediaProductionConfig, ServiceSelection
from app.integrations.services import select_service
from app.integrations.vault import CredentialVault
from app.media.factory import VERIFIED_STATUSES

#: The purposes a media connection can be chosen for, in the order the report lists them.
PURPOSES = ("voice", "image", "video")

#: Which default each purpose needs on the connection, and which resource type it comes from.
DEFAULTS: dict[str, tuple[str, str]] = {
    "voice": ("model_id", "MODEL"),
    "image": ("image_model_id", "MODEL"),
    "video": ("model_id", "MODEL"),
}


def _candidates(session: Session, purpose: str) -> list[Integration]:
    """Verified connections that declare this purpose and can actually serve it.

    "Can actually serve it" means the account's own catalogue has at least one discovered,
    available resource for the purpose — a Runway key whose organisation exposes no video
    model is not a video provider, whatever the catalogue entry says it could be.
    """
    found = []
    for row in session.scalars(select(Integration)):
        spec = CATALOG.get(row.kind)
        if not spec or purpose not in spec["purposes"] or row.status not in VERIFIED_STATUSES:
            continue
        if row.kind in DISCOVERED_KINDS:
            from app.integrations.models import ProviderResource  # noqa: PLC0415

            usable = any(
                production_resource(session, row.id, "MODEL", resource.remote_id, purpose)
                for resource in session.scalars(
                    select(ProviderResource).where(
                        ProviderResource.integration_id == row.id,
                        ProviderResource.resource_type == "MODEL",
                    )
                )
            )
            if not usable:
                continue
        found.append(row)
    return found


from app.media.production_policy import GENERATIVE_TASKS  # noqa: E402


def _top_resource(engine: Engine, integration_id: str, kind: str, purpose: str) -> str | None:
    """The default this purpose should get: the highest-ranked model the pipeline can call.

    Ranking is the production hierarchy's own (`rank_candidates`), so the order is the one
    `strategy: auto` would use. Among equals, a model that generates from a prompt comes
    before one that needs an input the storyboard does not have.
    """
    from app.integrations.models import ProviderResource  # noqa: PLC0415
    from app.media.production_policy import rank_candidates  # noqa: PLC0415

    with Session(engine) as session:
        ranked = rank_candidates(session, integration_id, kind, None, purpose)
        if not ranked:
            return None
        wanted = GENERATIVE_TASKS.get(purpose)
        if not wanted:
            return str(ranked[0]["remote_id"])
        metadata = {
            row.remote_id: row.api_metadata
            for row in session.scalars(
                select(ProviderResource).where(
                    ProviderResource.integration_id == integration_id,
                    ProviderResource.resource_type == kind,
                )
            )
        }
    for candidate in ranked:
        tasks = (metadata.get(candidate["remote_id"]) or {}).get("tasks")
        if isinstance(tasks, list) and any(task in wanted for task in tasks):
            return str(candidate["remote_id"])
    return str(ranked[0]["remote_id"])


def auto_configure(engine: Engine, vault: CredentialVault) -> dict[str, Any]:
    """Select the forced services and fill the empty defaults. Returns what it did and why."""
    applied: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []
    already: list[dict[str, str]] = []

    for purpose in PURPOSES:
        with Session(engine) as session:
            selection = session.get(ServiceSelection, purpose)
            chosen_id = selection.integration_id if selection else None
            version = selection.version if selection else 0
            candidates = _candidates(session, purpose)
            names = {row.id: row.name for row in candidates}
        if chosen_id:
            with Session(engine) as session:
                row = session.get(Integration, chosen_id)
            already.append({"purpose": purpose, "connection": row.name if row else chosen_id})
            continue
        if not candidates:
            continue
        if len(candidates) > 1:
            ambiguous.append(
                {
                    "purpose": purpose,
                    "candidates": [names[row.id] for row in candidates],
                    "why": "mai multe conexiuni verificate pot face asta; alegerea este a ta",
                }
            )
            continue
        only = candidates[0]
        select_service(engine, purpose, only.id, version)
        applied.append(
            {
                "purpose": purpose,
                "action": "selected_service",
                "connection": only.name,
                "why": "singura conexiune verificată care poate face asta",
            }
        )

    # Defaults, for every connection now serving a purpose.
    with Session(engine) as session:
        serving: dict[str, set[str]] = {}
        for purpose in PURPOSES:
            selection = session.get(ServiceSelection, purpose)
            if selection and selection.integration_id:
                serving.setdefault(selection.integration_id, set()).add(purpose)
        rows = {row.id: row for row in session.scalars(select(Integration))}

    for integration_id, purposes in serving.items():
        row = rows.get(integration_id)
        if row is None or row.kind not in DISCOVERED_KINDS:
            continue
        with Session(engine) as session:
            config = session.get(MediaProductionConfig, integration_id)
            allow = bool(config.allow_production_override) if config else True
            version = config.version if config else 0
            wanted: dict[str, str | None] = {
                "model_id": config.model_id if config else None,
                "voice_id": config.voice_id if config else None,
                "image_model_id": config.image_model_id if config else None,
            }
        reasons: list[str] = []
        for purpose in sorted(purposes):
            field, _ = DEFAULTS.get(purpose, ("model_id", "MODEL"))
            if wanted.get(field):
                continue
            top = _top_resource(engine, integration_id, "MODEL", purpose)
            if top:
                wanted[field] = top
                reasons.append(f"{purpose}: {top}")
        if DISCOVERED_KINDS[row.kind]["has_voices"] and not wanted["voice_id"]:
            with Session(engine) as session:
                from app.media.production_policy import rank_candidates  # noqa: PLC0415

                voices = rank_candidates(session, integration_id, "VOICE", None)
            if voices:
                wanted["voice_id"] = voices[0]["remote_id"]
                reasons.append(f"voce: {voices[0]['remote_id']}")
        if not reasons:
            continue
        save_production(
            engine,
            integration_id,
            ProductionCommand(
                model_id=wanted["model_id"],
                voice_id=wanted["voice_id"],
                image_model_id=wanted["image_model_id"],
                allow_production_override=allow,
                expected_version=version,
            ),
        )
        applied.append(
            {
                "purpose": ", ".join(sorted(purposes)),
                "action": "set_defaults",
                "connection": row.name,
                "why": "primul din catalogul descoperit, după ordinea de clasare; "
                "poate fi schimbat oricând · " + "; ".join(reasons),
            }
        )

    return {
        "applied": applied,
        "ambiguous": ambiguous,
        "already_configured": already,
        "correlation_id": str(uuid4()),
    }
