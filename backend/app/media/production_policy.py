"""Production policy: which technology a video is made with, and what may never change.

The rule the whole module enforces: **providers, models and voices are replaceable technology;
a recurring character is a persistent creative asset.** Both channels share the same discovered
resources (`ProviderResource`), the same verified connections (`Integration`) and the same
Organization defaults (`ServiceSelection` + `MediaProductionConfig`). They differ in how far
production may move away from those defaults.

Configuration hierarchy, later levels overriding earlier ones::

    Organization default   ServiceSelection(purpose) + MediaProductionConfig(model, voice)
    Channel default        ChannelRecord.production_defaults_json[purpose]
    Series rules           ChannelRecord.series_rules_json[series_key][purpose]
    Episode / video        Storyboard.production_overrides_json[purpose]
    Scene                  StoryboardScene.production_overrides_json[purpose]
    Character              CharacterBible.voice_binding_json, under identity_locks_json

A locked character field wins over every level above it. `allow_production_override = False`
on the Organization default or on the channel stops the merge there. Nothing in this module
names a channel, a model, a voice or a price: every value comes from a row.

A newer or cheaper model never replaces a locked identity on its own. It reaches a locked
character only through `approved_fallbacks_json`, which is written by an APPROVED
`CharacterIdentityChange`, or through a change to the binding itself, which is the same
workflow.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.integrations.discovery import (
    DISCOVERED_KINDS,
    production_resource,
    resource_available,
)
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.media.models import (
    CharacterBible,
    CharacterIdentityChange,
    Storyboard,
    StoryboardScene,
)
from app.publishing.models import ChannelRecord
from app.services import append_event, utc_now

logger = logging.getLogger("studio.production_policy")

POLICY_FLEXIBLE = "FLEXIBLE"
POLICY_LOCKED = "CONSISTENCY_LOCKED"
POLICIES = (POLICY_FLEXIBLE, POLICY_LOCKED)

#: Production purposes the hierarchy carries. `voice` and `image` have adapters today; the
#: others resolve the same way so a video/music/sfx provider slots in without a schema change.
PURPOSES = ("voice", "image", "video", "music", "sfx")

#: Identity fields a lock can protect, and the bible columns each one covers.
LOCKABLE_FIELDS = {
    "voice": ("voice_binding_json",),
    "visual": ("palette_json", "face_hair_desc", "outfit_desc", "props_desc"),
    "personality": ("personality_json",),
    "speech_style": ("speech_style_json", "expressions_json"),
}

CONSISTENCY_STATUSES = ("UNVERIFIED", "CONSISTENT", "CHANGE_PENDING", "DRIFT_SUSPECTED")
CHANGE_STATUSES = ("PROPOSED", "TESTING", "APPROVED", "REJECTED")
#: Allowed transitions of an identity change.
CHANGE_TRANSITIONS = {
    "PROPOSED": {"TESTING", "APPROVED", "REJECTED"},
    "TESTING": {"APPROVED", "REJECTED"},
}

#: Keys a level may set for a purpose.
SELECTION_KEYS = (
    "integration_id",
    "model_id",
    "voice_id",
    "strategy",
    "criteria",
    "voice_settings",
)


class PolicyError(ValueError):
    """The request contradicts a policy or a lock; nothing was changed."""


# ----------------------------------------------------------------------------- views


def channel_policy_view(row: ChannelRecord) -> dict[str, Any]:
    return {
        "production_policy": row.production_policy,
        "production_defaults_json": row.production_defaults_json or {},
        "series_rules_json": row.series_rules_json or {},
        "allow_production_override": bool(row.allow_production_override),
    }


def character_identity_view(row: CharacterBible) -> dict[str, Any]:
    return {
        "voice_binding_json": row.voice_binding_json or {},
        "identity_locks_json": row.identity_locks_json or {},
        "approved_fallbacks_json": row.approved_fallbacks_json or [],
        "consistency_status": row.consistency_status,
    }


def identity_change_view(row: CharacterIdentityChange) -> dict[str, Any]:
    return {
        "id": row.id,
        "character_id": row.character_id,
        "field": row.field,
        "proposed_json": row.proposed_json,
        "previous_json": row.previous_json,
        "rationale": row.rationale,
        "status": row.status,
        "proposed_by_agent_id": row.proposed_by_agent_id,
        "test_evidence_json": row.test_evidence_json,
        "decided_by": row.decided_by,
        "decision_notes": row.decision_notes,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }


# ----------------------------------------------------------------------------- defaults


def organization_default(session: Session, purpose: str) -> tuple[dict[str, Any], bool]:
    """The Organization-level selection for a purpose, and whether it may be overridden."""
    selection = session.get(ServiceSelection, purpose)
    if selection is None or not selection.integration_id:
        return {}, True
    integration = session.get(Integration, selection.integration_id)
    if integration is None:
        return {}, True
    value: dict[str, Any] = {"integration_id": integration.id}
    allow = True
    config = session.get(MediaProductionConfig, integration.id)
    if config is not None:
        # A connection serving two purposes keeps a default per purpose: its image default is
        # not its video default. Other purposes read the primary default.
        value["model_id"] = (
            config.image_model_id
            if purpose == "image" and config.image_model_id
            else config.model_id
        )
        value["voice_id"] = config.voice_id
        allow = bool(config.allow_production_override)
    elif isinstance(integration.config, dict) and integration.config.get("model"):
        value["model_id"] = integration.config.get("model")
    return value, allow


def _level_value(container: dict | None, purpose: str) -> dict[str, Any] | None:
    if not isinstance(container, dict):
        return None
    value = container.get(purpose)
    return value if isinstance(value, dict) and value else None


#: On a consistency-locked channel, episode and scene levels may tune settings but may not
#: swap technology: providers and models for a series are decided at channel/series level,
#: which is where an approved change lands.
TECHNOLOGY_KEYS = ("integration_id", "model_id", "strategy", "criteria")


def _apply(
    merged: dict[str, Any], value: dict[str, Any] | None, *, keys: tuple[str, ...] = SELECTION_KEYS
) -> bool:
    """Copy the keys a level sets onto the merge. Returns whether anything changed."""
    if not value:
        return False
    changed = False
    for key in keys:
        if key in value and value[key] is not None:
            merged[key] = value[key]
            changed = True
    return changed


# ----------------------------------------------------------------------------- ranking


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if 0.0 <= number <= 1.0 else default


#: The price a resource's research recorded, whatever the unit — voice is priced per
#: thousand characters, video per second, stills per image. Within one connection and kind
#: the units agree, so the cheapest of a kind is the cheapest whichever key holds it.
PRICE_KEYS = ("per_1k_characters_usd", "per_second_usd", "per_image_usd", "price_usd")


def _recorded_price(pricing: Any) -> float | None:
    if not isinstance(pricing, dict):
        return None
    for key in PRICE_KEYS:
        value = pricing.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


#: The task the studio actually calls for each purpose. A model may serve a purpose through
#: some other task — Runway's character performance is a video task, but it needs a driving
#: performance video, so it cannot be the default a storyboard scene renders through.
GENERATIVE_TASKS: dict[str, tuple[str, ...]] = {
    "video": ("text_to_video", "image_to_video"),
    "image": ("text_to_image",),
}


def rank_candidates(
    session: Session,
    integration_id: str,
    kind: str,
    criteria: dict[str, Any] | None,
    purpose: str | None = None,
) -> list[dict[str, Any]]:
    """Order discovered, available resources of one connection for an `auto` strategy.

    The score is built only from what is stored: research annotations in `capabilities`
    (`quality_score`, `reliability_score`, `latency_score`, 0..1) and `pricing`
    (`per_1k_characters_usd`), plus a language match against the API's own metadata. A
    resource with no annotations scores neutrally, so without research input the order is
    deterministic (by remote id) rather than invented. Weights come from the criteria
    (`weights`: quality, cost, speed, reliability), defaulting to an even split.
    """
    criteria = criteria or {}
    raw_weights = criteria.get("weights")
    weights: dict[str, Any] = raw_weights if isinstance(raw_weights, dict) else {}
    w_quality = _number(weights.get("quality"), 0.25)
    w_cost = _number(weights.get("cost"), 0.25)
    w_speed = _number(weights.get("speed"), 0.25)
    w_reliability = _number(weights.get("reliability"), 0.25)
    language = str(criteria.get("language") or "").lower() or None
    rows = session.scalars(
        select(ProviderResource).where(
            ProviderResource.integration_id == integration_id,
            ProviderResource.resource_type == kind,
        )
    ).all()
    ranked: list[dict[str, Any]] = []
    prices = [price for r in rows for price in [_recorded_price(r.pricing)] if price is not None]
    max_price = max(prices) if prices else None
    for row in rows:
        if not resource_available(row):
            continue
        if (
            kind == "MODEL"
            and production_resource(session, integration_id, kind, row.remote_id, purpose) is None
        ):
            continue
        caps = row.capabilities if isinstance(row.capabilities, dict) else {}
        pricing = row.pricing if isinstance(row.pricing, dict) else {}
        quality = _number(caps.get("quality_score"), 0.5)
        reliability = _number(caps.get("reliability_score"), 0.5)
        speed = _number(caps.get("latency_score"), 0.5)
        price = _recorded_price(pricing)
        if price is not None and max_price:
            cost = 1.0 - min(1.0, price / max_price)
        else:
            cost = 0.5
        score = quality * w_quality + cost * w_cost + speed * w_speed + reliability * w_reliability
        languages = (
            row.api_metadata.get("languages") if isinstance(row.api_metadata, dict) else None
        )
        language_match = None
        if language and isinstance(languages, list):
            codes = {
                str(item.get("language_id") or item.get("name") or "").lower()
                for item in languages
                if isinstance(item, dict)
            }
            language_match = language in codes
            if not language_match:
                score *= 0.5
        ranked.append(
            {
                "remote_id": row.remote_id,
                "name": row.name,
                "score": round(score, 4),
                "quality_score": quality,
                "reliability_score": reliability,
                "latency_score": speed,
                "per_1k_characters_usd": price,
                "language_match": language_match,
                "annotated": bool(caps or pricing),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["remote_id"]))
    return ranked


def estimate_cost_usd(
    session: Session, integration_id: str, model_id: str | None, characters: int
) -> float | None:
    """A cost estimate from research pricing, or None when no price is recorded."""
    if not model_id:
        return None
    row = session.scalar(
        select(ProviderResource).where(
            ProviderResource.integration_id == integration_id,
            ProviderResource.resource_type == "MODEL",
            ProviderResource.remote_id == model_id,
        )
    )
    if row is None or not isinstance(row.pricing, dict):
        return None
    price = row.pricing.get("per_1k_characters_usd")
    if not isinstance(price, int | float):
        return None
    return round(float(price) * characters / 1000.0, 6)


# ----------------------------------------------------------------------------- resolution


def resolve_purpose(
    session: Session,
    purpose: str,
    *,
    channel: ChannelRecord | None = None,
    series_key: str | None = None,
    episode_overrides: dict | None = None,
    scene_overrides: dict | None = None,
    characters: list[CharacterBible] | None = None,
) -> dict[str, Any]:
    """Walk the hierarchy for one purpose and return what production must use.

    The result says which level decided each thing and whether a character lock applied, so
    a render record can be audited later without re-running the resolution.
    """
    notes: list[str] = []
    merged: dict[str, Any] = {}
    source = None
    policy = channel.production_policy if channel else None
    #: Keys the level that asked for `auto` fixed by hand; ranking fills only the others.
    auto_fixed: set[str] = set()

    def apply_level(
        level_value: dict[str, Any] | None, keys: tuple[str, ...] = SELECTION_KEYS
    ) -> bool:
        if level_value and level_value.get("strategy") == "auto":
            auto_fixed.clear()
            auto_fixed.update(k for k in ("model_id", "voice_id") if level_value.get(k))
        elif level_value and level_value.get("strategy") == "fixed":
            auto_fixed.clear()
        return _apply(merged, level_value, keys=keys)

    org_value, org_allows = organization_default(session, purpose)
    if apply_level(org_value):
        source = "organization"

    if not org_allows:
        notes.append("Organization default does not allow production override")
    else:
        if channel is not None:
            if apply_level(_level_value(channel.production_defaults_json, purpose)):
                source = "channel"
            series = _level_value(channel.series_rules_json or {}, series_key or "")
            if apply_level(_level_value(series, purpose)):
                source = "series"
            if not channel.allow_production_override:
                notes.append("Channel does not allow episode or scene overrides")
            else:
                keys: tuple[str, ...] = SELECTION_KEYS
                if policy == POLICY_LOCKED:
                    keys = tuple(k for k in SELECTION_KEYS if k not in TECHNOLOGY_KEYS)
                    for level_name, level in (
                        ("episode", episode_overrides),
                        ("scene", scene_overrides),
                    ):
                        candidate = _level_value(level, purpose) or {}
                        if any(candidate.get(k) is not None for k in TECHNOLOGY_KEYS):
                            notes.append(
                                f"Consistency-locked channel: {level_name}-level technology "
                                "change ignored; approve it at channel or series level"
                            )
                if apply_level(_level_value(episode_overrides, purpose), keys):
                    source = "episode"
                if apply_level(_level_value(scene_overrides, purpose), keys):
                    source = "scene"
        else:
            if apply_level(_level_value(episode_overrides, purpose)):
                source = "episode"
            if apply_level(_level_value(scene_overrides, purpose)):
                source = "scene"

    lock_applied = False
    character_id = None
    if purpose == "voice":
        locked = [
            c
            for c in (characters or [])
            if (c.identity_locks_json or {}).get("voice")
            and (c.voice_binding_json or {}).get("voice_id")
        ]
        if locked:
            character = locked[0]
            if len(locked) > 1:
                notes.append(
                    "Several locked characters in one scene; the first one's voice is used: "
                    + ", ".join(c.canonical_name for c in locked)
                )
            binding = character.voice_binding_json
            fallbacks = character.approved_fallbacks_json or []
            wanted_model = merged.get("model_id")
            merged["integration_id"] = binding.get("integration_id")
            merged["voice_id"] = binding.get("voice_id")
            if binding.get("voice_settings"):
                merged["voice_settings"] = binding["voice_settings"]
            approved = {
                (f.get("integration_id"), f.get("model_id"))
                for f in fallbacks
                if isinstance(f, dict)
            }
            if binding.get("model_id"):
                if wanted_model and wanted_model != binding["model_id"]:
                    if (binding.get("integration_id"), wanted_model) in approved:
                        merged["model_id"] = wanted_model
                        notes.append("Model taken from the character's approved fallbacks")
                    else:
                        merged["model_id"] = binding["model_id"]
                        notes.append(
                            "Requested model is not approved for this character; "
                            "kept the bound model"
                        )
                else:
                    merged["model_id"] = binding["model_id"]
            merged.pop("strategy", None)
            merged.pop("criteria", None)
            lock_applied = True
            character_id = character.id
            source = "character"

    visual_blocked: list[str] = []
    if purpose == "video":
        # A character whose look is locked may only be rendered by video models approved for
        # it (`approved_fallbacks_json`, the same list a locked voice uses for TTS models):
        # approval is the evidence that the model preserves the character's appearance.
        for character in characters or []:
            if not (character.identity_locks_json or {}).get("visual"):
                continue
            lock_applied = True
            character_id = character_id or character.id
            approved = {
                (f.get("integration_id"), f.get("model_id"))
                for f in (character.approved_fallbacks_json or [])
                if isinstance(f, dict)
            }
            if (merged.get("integration_id"), merged.get("model_id")) not in approved:
                visual_blocked.append(character.canonical_name)

    ranking: list[dict[str, Any]] | None = None
    if merged.get("strategy") == "auto" and merged.get("integration_id"):
        if policy == POLICY_LOCKED and purpose == "voice":
            notes.append("Automatic voice selection is not allowed on a consistency-locked channel")
        else:
            # The level that asked for `auto` may still fix a model or a voice by hand; the
            # ranking decides only what it left open, and it replaces inherited choices.
            models = rank_candidates(
                session, merged["integration_id"], "MODEL", merged.get("criteria"), purpose
            )
            if models and "model_id" not in auto_fixed:
                merged["model_id"] = models[0]["remote_id"]
            if purpose == "voice" and "voice_id" not in auto_fixed:
                voices = rank_candidates(
                    session, merged["integration_id"], "VOICE", merged.get("criteria")
                )
                if voices:
                    merged["voice_id"] = voices[0]["remote_id"]
            ranking = models[:5]
            notes.append(f"Automatic selection ranked {len(models)} models by stored annotations")

    valid, why = _validate(session, purpose, merged)
    if why:
        notes.append(why)
    if visual_blocked and merged.get("strategy") == "auto" and merged.get("model_id"):
        # Ranking may have replaced the model after the lock check; re-check what it chose.
        visual_blocked = [
            c.canonical_name
            for c in characters or []
            if (c.identity_locks_json or {}).get("visual")
            and (merged.get("integration_id"), merged.get("model_id"))
            not in {
                (f.get("integration_id"), f.get("model_id"))
                for f in (c.approved_fallbacks_json or [])
                if isinstance(f, dict)
            }
        ]
    if visual_blocked:
        valid = False
        notes.append(
            "Visual identity locked for "
            + ", ".join(visual_blocked)
            + f": video model '{merged.get('model_id')}' is not approved for them; approve it "
            "through approved-models after a consistency test"
        )
    return {
        "purpose": purpose,
        "policy": policy,
        "integration_id": merged.get("integration_id"),
        "model_id": merged.get("model_id"),
        "voice_id": merged.get("voice_id"),
        "voice_settings": merged.get("voice_settings"),
        "strategy": merged.get("strategy", "fixed"),
        "criteria": merged.get("criteria"),
        "source_level": source,
        "lock_applied": lock_applied,
        "character_id": character_id,
        "valid": valid,
        "ranking": ranking,
        "notes": notes,
    }


def _validate(session: Session, purpose: str, merged: dict[str, Any]) -> tuple[bool, str | None]:
    """A selection is usable only if it names a verified connection and discovered resources."""
    integration_id = merged.get("integration_id")
    if not integration_id:
        return False, "No provider selected for this purpose"
    integration = session.get(Integration, integration_id)
    if integration is None:
        return False, "Selected connection no longer exists"
    if integration.status not in ("VERIFIED", "ACCESS_VERIFIED"):
        return False, "Selected connection is not verified"
    if integration.kind in DISCOVERED_KINDS:
        if (
            production_resource(session, integration_id, "MODEL", merged.get("model_id"), purpose)
            is None
        ):
            return (
                False,
                f"Model is not a discovered, available {purpose} model of this connection",
            )
        if (
            purpose == "voice"
            and DISCOVERED_KINDS[integration.kind]["has_voices"]
            and production_resource(session, integration_id, "VOICE", merged.get("voice_id"))
            is None
        ):
            return False, "Voice is not a discovered, available voice of this connection"
    return True, None


def resolve_storyboard_plan(session: Session, storyboard: Storyboard) -> dict[str, Any]:
    """Resolve every purpose for a storyboard, and the voice and video model for every scene."""
    channel = session.get(ChannelRecord, storyboard.channel_id) if storyboard.channel_id else None
    scenes = session.scalars(
        select(StoryboardScene)
        .where(StoryboardScene.storyboard_id == storyboard.id)
        .order_by(StoryboardScene.scene_index)
    ).all()
    purposes = {
        purpose: resolve_purpose(
            session,
            purpose,
            channel=channel,
            series_key=storyboard.series_key,
            episode_overrides=storyboard.production_overrides_json,
        )
        for purpose in PURPOSES
    }
    scene_plans = []
    for scene in scenes:
        ids = [c for c in (scene.character_ids_json or []) if isinstance(c, str)]
        characters = (
            session.scalars(select(CharacterBible).where(CharacterBible.id.in_(ids))).all()
            if ids
            else []
        )
        # Keep the scene's own order so "first locked character" is the one the writer put first.
        by_id = {c.id: c for c in characters}
        ordered = [by_id[i] for i in ids if i in by_id]
        scene_plans.append(
            {
                "scene_index": scene.scene_index,
                "character_ids": ids,
                "voice": resolve_purpose(
                    session,
                    "voice",
                    channel=channel,
                    series_key=storyboard.series_key,
                    episode_overrides=storyboard.production_overrides_json,
                    scene_overrides=scene.production_overrides_json,
                    characters=ordered,
                ),
                "video": resolve_purpose(
                    session,
                    "video",
                    channel=channel,
                    series_key=storyboard.series_key,
                    episode_overrides=storyboard.production_overrides_json,
                    scene_overrides=scene.production_overrides_json,
                    characters=ordered,
                ),
            }
        )
    return {
        "storyboard_id": storyboard.id,
        "channel_id": storyboard.channel_id,
        "channel_type": channel.channel_type if channel else None,
        "policy": channel.production_policy if channel else None,
        "series_key": storyboard.series_key,
        "purposes": purposes,
        "scenes": scene_plans,
    }


# ----------------------------------------------------------------------------- commands


class ChannelPolicyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    production_policy: str | None = None
    production_defaults_json: dict[str, Any] | None = None
    series_rules_json: dict[str, Any] | None = None
    allow_production_override: bool | None = None


def _check_selection_shape(value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise PolicyError(f"{where}: expected an object of purposes")
    for purpose, selection in value.items():
        if purpose not in PURPOSES:
            raise PolicyError(f"{where}: unknown purpose '{purpose}'")
        if not isinstance(selection, dict):
            raise PolicyError(f"{where}: '{purpose}' must be an object")
        unknown = set(selection) - set(SELECTION_KEYS)
        if unknown:
            raise PolicyError(f"{where}: '{purpose}' has unknown keys {sorted(unknown)}")
        if "strategy" in selection and selection["strategy"] not in ("fixed", "auto"):
            raise PolicyError(f"{where}: strategy must be 'fixed' or 'auto'")


def set_channel_policy(
    engine: Engine, channel_id: str, command: ChannelPolicyCommand
) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        row = session.get(ChannelRecord, channel_id)
        if row is None:
            raise PolicyError("Channel not found")
        if command.production_policy is not None:
            if command.production_policy not in POLICIES:
                raise PolicyError(f"production_policy must be one of {POLICIES}")
            row.production_policy = command.production_policy
        if command.production_defaults_json is not None:
            _check_selection_shape(command.production_defaults_json, "production_defaults_json")
            row.production_defaults_json = command.production_defaults_json
        if command.series_rules_json is not None:
            if not isinstance(command.series_rules_json, dict):
                raise PolicyError("series_rules_json must be an object of series keys")
            for key, rules in command.series_rules_json.items():
                _check_selection_shape(rules, f"series_rules_json[{key}]")
            row.series_rules_json = command.series_rules_json
        if command.allow_production_override is not None:
            row.allow_production_override = command.allow_production_override
        event = append_event(
            session,
            "channel.production_policy_set",
            "channel_record",
            row.id,
            1,
            channel_policy_view(row),
            str(uuid4()),
        )
        row.event_id = event.event_id
        return channel_policy_view(row)


class StoryboardProductionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str | None = Field(default=None, max_length=36)
    series_key: str | None = Field(default=None, max_length=100)
    production_overrides_json: dict[str, Any] | None = None
    scene_overrides: dict[str, dict[str, Any]] | None = None  # scene_index -> overrides


def set_storyboard_production(
    engine: Engine, storyboard_id: str, command: StoryboardProductionCommand
) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            raise PolicyError("Storyboard not found")
        if "channel_id" in command.model_fields_set:
            if command.channel_id and session.get(ChannelRecord, command.channel_id) is None:
                raise PolicyError("Channel not found")
            board.channel_id = command.channel_id
        if "series_key" in command.model_fields_set:
            board.series_key = command.series_key
        if command.production_overrides_json is not None:
            _check_selection_shape(command.production_overrides_json, "production_overrides_json")
            board.production_overrides_json = command.production_overrides_json
        if command.scene_overrides:
            scenes = {
                s.scene_index: s
                for s in session.scalars(
                    select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
                )
            }
            for index, overrides in command.scene_overrides.items():
                try:
                    scene = scenes[int(index)]
                except (KeyError, ValueError) as exc:
                    raise PolicyError(f"Scene {index} not found") from exc
                _check_selection_shape(overrides, f"scene_overrides[{index}]")
                scene.production_overrides_json = overrides
        append_event(
            session,
            "media.storyboard_production_set",
            "storyboard",
            board.id,
            1,
            {
                "channel_id": board.channel_id,
                "series_key": board.series_key,
                "production_overrides_json": board.production_overrides_json,
            },
            str(uuid4()),
        )
        return resolve_storyboard_plan(session, board)


class VoiceBindingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration_id: str = Field(min_length=1, max_length=36)
    voice_id: str = Field(min_length=1, max_length=200)
    model_id: str | None = Field(default=None, max_length=200)
    voice_settings: dict[str, Any] = Field(default_factory=dict)
    language: str | None = Field(default=None, max_length=20)
    pronunciation_rules: list[dict[str, Any]] = Field(default_factory=list)


def _binding_resources_exist(session: Session, binding: dict[str, Any]) -> None:
    integration = session.get(Integration, binding.get("integration_id"))
    if integration is None:
        raise PolicyError("Connection not found")
    if production_resource(session, integration.id, "VOICE", binding.get("voice_id")) is None:
        raise PolicyError("Voice is not a discovered, available voice of this connection")
    if (
        binding.get("model_id")
        and production_resource(session, integration.id, "MODEL", binding["model_id"]) is None
    ):
        raise PolicyError("Model is not a discovered, available TTS model of this connection")


def set_voice_binding(
    engine: Engine, character_id: str, command: VoiceBindingCommand
) -> dict[str, Any]:
    """Bind a character to a discovered voice. Refused when the voice is locked and differs."""
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        if row is None:
            raise PolicyError("Character not found")
        binding = command.model_dump()
        _binding_resources_exist(session, binding)
        current = row.voice_binding_json or {}
        locks = row.identity_locks_json or {}
        identity_changes = (current.get("integration_id"), current.get("voice_id")) != (
            binding["integration_id"],
            binding["voice_id"],
        )
        if locks.get("voice") and current.get("voice_id") and identity_changes:
            raise PolicyError(
                "Voice identity is locked; propose an identity change and have it approved"
            )
        row.voice_binding_json = binding
        row.version += 1
        if row.consistency_status == "UNVERIFIED":
            row.consistency_status = "CONSISTENT"
        event = append_event(
            session,
            "character.voice_bound",
            "character_bible",
            row.id,
            row.version,
            {
                "voice_id": binding["voice_id"],
                "integration_id": binding["integration_id"],
                "model_id": binding.get("model_id"),
            },
            str(uuid4()),
        )
        row.event_id = event.event_id
        return character_identity_view(row)


class IdentityLocksCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: bool | None = None
    visual: bool | None = None
    personality: bool | None = None
    speech_style: bool | None = None


def set_identity_locks(
    engine: Engine, character_id: str, command: IdentityLocksCommand
) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        if row is None:
            raise PolicyError("Character not found")
        locks = dict(row.identity_locks_json or {})
        for field in LOCKABLE_FIELDS:
            value = getattr(command, field)
            if value is not None:
                locks[field] = bool(value)
        if locks.get("voice") and not (row.voice_binding_json or {}).get("voice_id"):
            raise PolicyError("Bind a voice before locking it")
        row.identity_locks_json = locks
        row.version += 1
        event = append_event(
            session,
            "character.identity_locks_set",
            "character_bible",
            row.id,
            row.version,
            locks,
            str(uuid4()),
        )
        row.event_id = event.event_id
        return character_identity_view(row)


class IdentityChangeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    proposed_json: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=4000)
    proposed_by_agent_id: str | None = Field(default=None, max_length=36)


def _current_identity(row: CharacterBible, field: str) -> dict[str, Any]:
    columns = LOCKABLE_FIELDS[field]
    return {column: getattr(row, column) for column in columns}


def propose_identity_change(
    engine: Engine, character_id: str, command: IdentityChangeCommand
) -> dict[str, Any]:
    if command.field not in LOCKABLE_FIELDS:
        raise PolicyError(f"field must be one of {sorted(LOCKABLE_FIELDS)}")
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        if row is None:
            raise PolicyError("Character not found")
        if command.field == "voice":
            _binding_resources_exist(session, command.proposed_json)
        open_change = session.scalar(
            select(CharacterIdentityChange).where(
                CharacterIdentityChange.character_id == character_id,
                CharacterIdentityChange.field == command.field,
                CharacterIdentityChange.status.in_(("PROPOSED", "TESTING")),
            )
        )
        if open_change is not None:
            raise PolicyError("An identity change for this field is already open")
        change = CharacterIdentityChange(
            id=str(uuid4()),
            character_id=character_id,
            field=command.field,
            proposed_json=command.proposed_json,
            previous_json=_current_identity(row, command.field),
            rationale=command.rationale,
            status="PROPOSED",
            proposed_by_agent_id=command.proposed_by_agent_id,
            created_at=utc_now(),
        )
        session.add(change)
        row.consistency_status = "CHANGE_PENDING"
        event = append_event(
            session,
            "character.identity_change_proposed",
            "character_bible",
            row.id,
            row.version,
            {"change_id": change.id, "field": command.field},
            str(uuid4()),
        )
        change.event_id = event.event_id
        return identity_change_view(change)


class IdentityDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    decided_by: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)
    test_evidence_json: dict[str, Any] | None = None


def _apply_identity_change(row: CharacterBible, change: CharacterIdentityChange) -> None:
    proposed = change.proposed_json
    if change.field == "voice":
        previous = row.voice_binding_json or {}
        row.voice_binding_json = proposed
        # The model of the previous binding stays usable technology for this identity.
        fallbacks = list(row.approved_fallbacks_json or [])
        if previous.get("model_id") and previous.get("integration_id"):
            fallbacks.append(
                {
                    "integration_id": previous["integration_id"],
                    "model_id": previous["model_id"],
                    "approved_at": utc_now(),
                    "change_id": change.id,
                }
            )
        row.approved_fallbacks_json = fallbacks
    elif change.field == "visual":
        for column in LOCKABLE_FIELDS["visual"]:
            if column in proposed:
                setattr(row, column, proposed[column])
    elif change.field == "personality":
        row.personality_json = proposed.get("personality_json", proposed)
    elif change.field == "speech_style":
        if "speech_style_json" in proposed:
            row.speech_style_json = proposed["speech_style_json"]
        if "expressions_json" in proposed:
            row.expressions_json = proposed["expressions_json"]


def approve_model_fallback(
    engine: Engine, character_id: str, integration_id: str, model_id: str, decided_by: str
) -> dict[str, Any]:
    """Approve a model as technology for a locked character, without touching its identity.

    This is how a newer TTS model reaches a locked voice, and how a video model reaches a
    locked look: the identity stays, the model is added to the approved list, and production
    may then pick it through the hierarchy.
    """
    with Session(engine) as session, session.begin():
        row = session.get(CharacterBible, character_id)
        if row is None:
            raise PolicyError("Character not found")
        if production_resource(session, integration_id, "MODEL", model_id) is None:
            raise PolicyError("Model is not a discovered, available model of this connection")
        fallbacks = list(row.approved_fallbacks_json or [])
        if any(
            f.get("integration_id") == integration_id and f.get("model_id") == model_id
            for f in fallbacks
        ):
            return character_identity_view(row)
        fallbacks.append(
            {
                "integration_id": integration_id,
                "model_id": model_id,
                "approved_at": utc_now(),
                "approved_by": decided_by,
                "change_id": None,
            }
        )
        row.approved_fallbacks_json = fallbacks
        row.version += 1
        event = append_event(
            session,
            "character.model_fallback_approved",
            "character_bible",
            row.id,
            row.version,
            {"integration_id": integration_id, "model_id": model_id, "approved_by": decided_by},
            str(uuid4()),
        )
        row.event_id = event.event_id
        return character_identity_view(row)


def decide_identity_change(
    engine: Engine, change_id: str, command: IdentityDecisionCommand
) -> dict[str, Any]:
    if command.status not in CHANGE_STATUSES or command.status == "PROPOSED":
        raise PolicyError("status must be TESTING, APPROVED or REJECTED")
    with Session(engine) as session, session.begin():
        change = session.get(CharacterIdentityChange, change_id)
        if change is None:
            raise PolicyError("Identity change not found")
        allowed = CHANGE_TRANSITIONS.get(change.status, set())
        if command.status not in allowed:
            raise PolicyError(f"Cannot move from {change.status} to {command.status}")
        row = session.get(CharacterBible, change.character_id)
        if row is None:
            raise PolicyError("Character not found")
        if command.test_evidence_json is not None:
            change.test_evidence_json = command.test_evidence_json
        change.status = command.status
        change.decision_notes = command.notes
        if command.status in ("APPROVED", "REJECTED"):
            change.decided_by = command.decided_by
            change.decided_at = utc_now()
        if command.status == "APPROVED":
            _apply_identity_change(row, change)
            row.version += 1
            row.consistency_status = "CONSISTENT"
        elif command.status == "REJECTED":
            row.consistency_status = (
                "CONSISTENT" if (row.voice_binding_json or {}).get("voice_id") else "UNVERIFIED"
            )
        event = append_event(
            session,
            f"character.identity_change_{command.status.lower()}",
            "character_bible",
            row.id,
            row.version,
            {"change_id": change.id, "field": change.field, "decided_by": command.decided_by},
            str(uuid4()),
        )
        change.event_id = event.event_id
        row.event_id = event.event_id
        if command.status in ("APPROVED", "REJECTED"):
            from app.agents.memory import remember

            remember(
                session,
                memory_class="OWNER_POLICY",
                content=(
                    f"Identity change for {row.canonical_name} ({change.field}) was "
                    f"{command.status.lower()} by {command.decided_by}"
                    + (f": {command.notes}" if command.notes else ".")
                ),
                source_type="owner",
                source_id=change.id,
                event_id=event.event_id,
            )
        return identity_change_view(change)


def list_identity_changes(engine: Engine, character_id: str | None = None) -> list[dict[str, Any]]:
    with Session(engine) as session:
        query = select(CharacterIdentityChange).order_by(CharacterIdentityChange.created_at.desc())
        if character_id:
            query = query.where(CharacterIdentityChange.character_id == character_id)
        return [identity_change_view(row) for row in session.scalars(query)]
