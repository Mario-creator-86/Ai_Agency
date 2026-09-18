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
from dataclasses import asdict, dataclass
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
from app.integrations.lifecycle import ADMITTED, LIFECYCLE
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
    # The Owner's approved second vendors for this purpose: [{"integration_id", "model_id"}].
    # A render that hits a refusal may try one of these and nothing else; the studio never
    # invents an alternative, because an alternative is a purchase from another account.
    "approved_fallbacks",
)

#: At most one alternative per purpose per scene. Trying vendors until one answers is how a
#: single shot spends a film's budget, and the second refusal is usually the same refusal:
#: a prompt the vendors both decline, not an account that is down.
MAX_FALLBACKS_PER_PURPOSE = 1


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
TECHNOLOGY_KEYS = ("integration_id", "model_id", "strategy", "criteria", "approved_fallbacks")


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


#: How close two quality scores must be to count as the same picture. Within a band, a
#: premium studio takes the cheaper model: paying three times for the same footage is not
#: premium, it is waste. Wider than the noise in a steward's judgement, narrower than the
#: difference between a good model and a mediocre one.
QUALITY_BAND = 0.1


#: What each standing priority means as weights over quality, cost, speed and reliability.
#: A premium studio buys the best picture its account can make; cost is a reported fact, not
#: the deciding one. Nothing here is a per-model preference — only what to optimise for.
PRIORITY_WEIGHTS: dict[str, dict[str, float]] = {
    "premium": {"quality": 0.6, "reliability": 0.25, "speed": 0.1, "cost": 0.05},
    "balanced": {"quality": 0.25, "reliability": 0.25, "speed": 0.25, "cost": 0.25},
    "thrifty": {"quality": 0.2, "reliability": 0.2, "speed": 0.1, "cost": 0.5},
}

#: The frame the studio's films are made in. A model whose published ratios do not include it
#: cannot deliver a full-height shot: `seedance2_fast` stops at 720×1280, so its picture would
#: be upscaled into a 1080×1920 film. Read from the contract, per model and task.
STUDIO_FRAME = "1080:1920"


def delivers_studio_frame(metadata: Any, purpose: str | None, frame: str = STUDIO_FRAME) -> bool:
    """Whether the contract says this model can produce the studio's frame for this purpose.

    A model whose ratios for the purpose's tasks are not known counts as able — that is
    research's business, not a guess made here. One that lists its ratios and not this one
    is ranked below every model that can: its picture would be upscaled into a 1080x1920
    film. `seedance2_fast`, recommended once for this studio, stops at 720x1280.
    """
    wanted = GENERATIVE_TASKS.get(purpose or "")
    meta = metadata if isinstance(metadata, dict) else {}
    ratios = meta.get("ratios")
    if not wanted or not isinstance(ratios, dict):
        return True
    listed = [r for task in wanted if isinstance(ratios.get(task), list) for r in ratios[task]]
    return frame in listed if listed else True


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
    # Absent explicit weights, the studio's standing priority decides. The Owner's is
    # premium — the best picture the account can make — and an even split had the ranking
    # recommending the cheapest model for a studio whose purpose is good films.
    default = PRIORITY_WEIGHTS.get(
        str(criteria.get("priority") or "premium"), PRIORITY_WEIGHTS["premium"]
    )
    w_quality = _number(weights.get("quality"), default["quality"])
    w_cost = _number(weights.get("cost"), default["cost"])
    w_speed = _number(weights.get("speed"), default["speed"])
    w_reliability = _number(weights.get("reliability"), default["reliability"])
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
                # Whether its own contract says it can fill the studio's frame. A model that
                # cannot is not excluded — an account may offer nothing better — but it never
                # outranks one that can: the alternative is upscaled footage in a 1080x1920
                # film, which is exactly the "rabat" a premium studio does not make.
                "delivers_studio_frame": delivers_studio_frame(row.api_metadata, purpose)
                if kind == "MODEL"
                else True,
            }
        )
    premium = str(criteria.get("priority") or "premium") == "premium" and not weights

    # Premium: the best picture, and among the models that match it the cheaper one. The
    # band is measured from the best score present, because that is the Owner's question —
    # "cum sa dam 9 USD cand avem WAN 3" — and the answer is that equal footage at a third
    # of the price wins. It is not "most expensive first".
    best_quality = max(
        (
            _number(item.get("quality_score"), 0.5)
            for item in ranked
            if item.get("delivers_studio_frame", True)
        ),
        default=0.0,
    )

    def order(item: dict[str, Any]) -> tuple[Any, ...]:
        frame_first = not item.get("delivers_studio_frame", True)
        if not premium:
            return (frame_first, -item["score"], item["remote_id"])
        near_best = best_quality - _number(item.get("quality_score"), 0.5) <= QUALITY_BAND
        price = item.get("per_1k_characters_usd")
        return (
            frame_first,
            not near_best,
            float(price) if isinstance(price, int | float) else float("inf"),
            -item["score"],
            item["remote_id"],
        )

    ranked.sort(key=order)
    return ranked


def record_measured_price(
    engine: Engine, integration_id: str, model_id: str, usd_per_unit: float, unit: str
) -> list[dict]:
    """Write what the vendor actually charged over whatever a steward had guessed.

    The studio learns a model's price by using it: Runway states the credits every task
    costs, and the Owner recorded what a credit costs. A measured price carries its source,
    so the next choice is made on what happened rather than on what a page seemed to say.
    """
    from app.integrations.lifecycle import stamp_price  # noqa: PLC0415

    if usd_per_unit <= 0:
        return []
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == integration_id,
                ProviderResource.resource_type == "MODEL",
                ProviderResource.remote_id == model_id,
            )
        )
        if row is None:
            return []
        pricing = dict(row.pricing) if isinstance(row.pricing, dict) else {}
        key = "per_second_usd" if unit.startswith("per second") else "per_image_usd"
        was = pricing.get(key)
        if isinstance(was, int | float) and abs(float(was) - usd_per_unit) < 1e-6:
            return []
        pricing.update({key: round(usd_per_unit, 6), "unit": unit, "source": "measured"})
        # What the account was charged is the dearest evidence there is about a price, and it
        # is written with its provenance: what the price was before, when this was measured,
        # and that it was measured rather than read on a page.
        moves = stamp_price(
            row,
            pricing,
            verification="BILLED",
            source="measured from the studio's own renders",
        )
        row.metadata_version = int(row.metadata_version or 1) + 1
        logger.info(
            "measured_price_recorded",
            extra={"model": model_id, key: round(usd_per_unit, 6), "was": was},
        )
        return moves


def record_quoted_price(
    engine: Engine,
    integration_id: str,
    model_id: str,
    usd_per_unit: float,
    unit_key: str,
    *,
    tolerance_percent: float,
) -> dict | None:
    """Compare a vendor's quote with the stored price, and correct the price if it drifted.

    A dry run is the vendor speaking about today's price. Within the tolerance the stored
    price stands — a quote is for one shot, at one length, and small differences are
    rounding. Past it the stored price is stale, and what the vendor just said replaces it,
    marked as estimated rather than billed.
    """
    from app.integrations.lifecycle import price_is_stale, stamp_price  # noqa: PLC0415

    if usd_per_unit <= 0:
        return None
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == integration_id,
                ProviderResource.resource_type == "MODEL",
                ProviderResource.remote_id == model_id,
            )
        )
        if row is None:
            return None
        stale = price_is_stale(
            row, usd_per_unit, unit_key=unit_key, tolerance_percent=tolerance_percent
        )
        if stale is None:
            return None
        pricing = dict(row.pricing) if isinstance(row.pricing, dict) else {}
        pricing.update(
            {unit_key: round(usd_per_unit, 6), "unit": unit_key, "source": "vendor dry run"}
        )
        stamp_price(
            row,
            pricing,
            verification="ESTIMATED",
            source="quoted by the vendor before generating",
        )
        row.metadata_version = int(row.metadata_version or 1) + 1
        logger.info("quoted_price_recorded", extra={"model": model_id, **stale})
        return stale


def credit_usd(session: Session, integration_id: str) -> float | None:
    """What one of this connection's credits costs, as the Owner recorded it.

    Vendors that bill in credits state the credits a task will cost and nothing about money;
    the exchange is the Owner's own purchase (for Runway: one dollar, a hundred credits).
    Kept on the connection because it is a fact about the account, not about a model.
    """
    row = session.get(Integration, integration_id)
    config = row.config if row is not None and isinstance(row.config, dict) else {}
    raw = config.get("credit_usd")
    try:
        price = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


#: The task a test render uses: a prompt straight into video, with no still bought first.
PROMPT_TO_VIDEO = "text_to_video"


def cheapest_prompt_to_video(session: Session, integration_id: str) -> str | None:
    """The cheapest model on this connection that turns a prompt into video.

    What a test render films with. Cheapest by the recorded price per second, among the
    models whose contract says they accept `text_to_video`; a model with no recorded price
    is not chosen over one with a price, because an unpriced test is how twenty-one dollars
    left the account in an afternoon.
    """
    priced: list[tuple[float, str]] = []
    unpriced: list[str] = []
    for row in session.scalars(
        select(ProviderResource).where(
            ProviderResource.integration_id == integration_id,
            ProviderResource.resource_type == "MODEL",
        )
    ):
        if not resource_available(row):
            continue
        meta = row.api_metadata if isinstance(row.api_metadata, dict) else {}
        tasks = meta.get("tasks")
        if not isinstance(tasks, list) or PROMPT_TO_VIDEO not in tasks:
            continue
        needs = meta.get("needs_references")
        if isinstance(needs, dict) and needs.get(PROMPT_TO_VIDEO):
            continue
        price = _recorded_price(row.pricing)
        if price is None:
            unpriced.append(str(row.remote_id))
        else:
            priced.append((price, str(row.remote_id)))
    if priced:
        return min(priced)[1]
    return sorted(unpriced)[0] if unpriced else None


def estimate_cost_usd(
    session: Session,
    integration_id: str,
    model_id: str | None,
    *,
    characters: int = 0,
    images: int = 0,
    seconds: float = 0.0,
    credits: float = 0.0,
) -> float | None:
    """A cost estimate from recorded pricing, or None when no price covers what was used.

    Three units, because a scene can cost in three ways: narration by the thousand
    characters, a still by the image, a shot by the second of film. Only the units with a
    recorded price are counted; a model priced in none returns None and is reported as
    unpriced rather than counted as free.
    """
    if not model_id:
        return None
    # Credits the vendor itself named outrank any price written down elsewhere: they are what
    # the account was actually charged, and the only conversion needed is the Owner's.
    if credits:
        per_credit = credit_usd(session, integration_id)
        if per_credit is not None:
            return round(credits * per_credit, 6)
    row = session.scalar(
        select(ProviderResource).where(
            ProviderResource.integration_id == integration_id,
            ProviderResource.resource_type == "MODEL",
            ProviderResource.remote_id == model_id,
        )
    )
    if row is None or not isinstance(row.pricing, dict):
        return None
    total = 0.0
    priced = False
    for key, quantity, per in (
        ("per_1k_characters_usd", characters, 1000.0),
        ("per_image_usd", images, 1.0),
        ("per_second_usd", seconds, 1.0),
    ):
        price = row.pricing.get(key)
        if isinstance(price, int | float) and quantity:
            total += float(price) * float(quantity) / per
            priced = True
    return round(total, 6) if priced else None


# ----------------------------------------------------------------- what a scene requires

#: What a scene needs, as a quality score in the same 0..1 scale the catalogue records. The
#: tier is a property of the scene, never of a model: STANDARD is not "the cheap model", it
#: is "the quality an ordinary published scene must reach". The router then finds the least
#: expensive model that reaches it.
QUALITY_TIERS: dict[str, float] = {
    "STANDARD": 0.80,
    "PREMIUM": 0.88,
    "HERO": 0.93,
}

#: Which scenes of a short carry the most weight. A hook that fails loses the viewer in the
#: first second and an ending that fails loses the comment, so those two are worth more than
#: the middle. Reused from the scene's own position when nothing else says otherwise.
SCENE_ROLE_TIERS: dict[str, str] = {
    "HOOK": "HERO",
    "ENDING": "PREMIUM",
    "KEY": "PREMIUM",
    "NORMAL": "STANDARD",
    "TRANSITION": "STANDARD",
    "BACKGROUND": "STANDARD",
}


def scene_role(scene_index: int, total_scenes: int) -> str:
    """The part this scene plays in the film, from its position when nothing else says.

    The first shot is the hook and the last is the payoff; a studio that treats them like
    the middle spends the same money on the scenes that decide whether anyone watches.
    """
    if scene_index <= 1:
        return "HOOK"
    if total_scenes and scene_index >= total_scenes:
        return "ENDING"
    return "NORMAL"


def required_quality(tier: str) -> float:
    return QUALITY_TIERS.get(str(tier).upper(), QUALITY_TIERS["STANDARD"])


# ----------------------------------------------------------------- what a model has done

#: Lifecycle states a model must be in before it may film something that will be published.
#: The stations themselves belong to `app.integrations.lifecycle`, which moves models between
#: them; the router only reads which ones are admitted.
PRODUCTION_READY = ADMITTED
#: And the ones that mean "not yet" or "no longer".
NOT_FOR_PRODUCTION = tuple(station for station in LIFECYCLE if station not in ADMITTED)


def model_record(
    session: Session, integration_id: str, purpose: str, remote_id: str
) -> dict[str, Any]:
    """What the studio knows about one model for one purpose, from its own generations.

    Only benchmarks and real production scenes teach quality; a cheap functional test only
    says whether the pipeline worked. That distinction is the whole reason the environment
    is recorded with every generation.
    """
    from app.integrations.models import ModelOutcome  # noqa: PLC0415

    rows = list(
        session.scalars(
            select(ModelOutcome).where(
                ModelOutcome.integration_id == integration_id,
                ModelOutcome.remote_id == remote_id,
                ModelOutcome.purpose == purpose,
            )
        )
    )
    judging = [r for r in rows if r.run_kind in ("PRODUCTION", "TEST_BENCHMARK")]
    accepted = [r for r in judging if r.accepted]
    usd = sum(float(r.usd or 0) for r in judging)
    seconds = sum(float(r.seconds_accepted or 0) for r in accepted)
    technical = [r for r in rows if r.failure_kind == "TECHNICAL"]
    return {
        "generations": len(rows),
        "judged": len(judging),
        "acceptance": (len(accepted) / len(judging)) if judging else None,
        "first_pass": (
            sum(1 for r in judging if r.first_pass and r.accepted) / len(judging)
            if judging
            else None
        ),
        "cost_per_accepted_second": (usd / seconds) if seconds > 0 else None,
        "technical_failures": len(technical),
    }


def _observed_quality(record: dict[str, Any], annotated: float) -> float:
    """What the studio believes about a model's picture: its own results, then research.

    Acceptance is the studio's own judgement of a finished shot, so where there is enough of
    it, it carries. Below three judged generations it cannot outweigh a steward's reading —
    one lucky shot is not evidence.
    """
    acceptance = record.get("acceptance")
    judged = int(record.get("judged") or 0)
    if acceptance is None or judged < 3:
        return annotated
    weight = min(1.0, judged / 10.0)
    return round(annotated * (1 - weight) + float(acceptance) * weight, 4)


# ----------------------------------------------------------------- the choice itself


@dataclass(frozen=True)
class SceneRequirement:
    """What the router is asked for: a capability, a quality, a length and a purse.

    Business logic states requirements, never a model name — the point of the whole
    arrangement. `generate_video(scene_requirements, minimum_quality, budget_limit)`, not
    `generate_with_seedance()`.
    """

    purpose: str = "video"
    tasks: tuple[str, ...] = ()
    tier: str = "STANDARD"
    scene_category: str = "GENERAL"
    seconds: float = 0.0
    budget_usd: float | None = None
    #: What one second may cost in this environment. A TEST render is checking that the
    #: pipeline works, so a shot above the ceiling is refused rather than quietly bought.
    max_usd_per_second: float | None = None
    frame: str = STUDIO_FRAME


def _unit_price(session: Session, integration_id: str, row: Any, seconds: float) -> float | None:
    """What this model would cost for the length asked, from whatever unit it is priced in."""
    price = estimate_cost_usd(
        session,
        integration_id,
        str(row.remote_id),
        seconds=seconds or 1.0,
    )
    if price is not None:
        return price
    return estimate_cost_usd(session, integration_id, str(row.remote_id), images=1)


def choose_model(
    session: Session,
    integration_id: str,
    requirement: SceneRequirement,
    *,
    environment: str,
    exclude: tuple[str, ...] = (),
    forced: str | None = None,
) -> dict[str, Any]:
    """Which model films this scene, in this environment, and why.

    TEST takes the cheapest model that can technically do the job and ignores the quality
    ranking entirely: a test answers "does this work", and a mediocre picture is a pass. Its
    fallback is the next cheapest, never the best. PRODUCTION takes the least expensive model
    whose expected quality reaches what the scene requires, and says what it did not buy and
    why — the marginal question the Owner asked: is the dearer model worth the multiple?

    `forced` is the Director's explicit override, which is honoured in both environments and
    recorded as such. `exclude` is what has already failed for this scene.
    """
    from app.integrations.discovery import resource_available, usable_purposes  # noqa: PLC0415
    from app.integrations.models import Integration  # noqa: PLC0415

    integration = session.get(Integration, integration_id)
    kind = integration.kind if integration else ""
    wanted_tasks = tuple(requirement.tasks) or GENERATIVE_TASKS.get(requirement.purpose, ())
    candidates: list[dict[str, Any]] = []
    for row in session.scalars(
        select(ProviderResource).where(
            ProviderResource.integration_id == integration_id,
            ProviderResource.resource_type == "MODEL",
        )
    ):
        remote_id = str(row.remote_id)
        if remote_id in exclude or not resource_available(row):
            continue
        # A retired model is retired everywhere: demoted for what it delivered, or named by
        # the Owner's deny list. Only the Director naming it by hand can bring it back.
        if str(row.production_status or "") == "DEPRECATED" and remote_id != forced:
            continue
        if requirement.purpose not in usable_purposes(kind, row):
            continue
        metadata = row.api_metadata if isinstance(row.api_metadata, dict) else {}
        listed = metadata.get("tasks")
        tasks: tuple[str, ...] = tuple(str(t) for t in listed) if isinstance(listed, list) else ()
        if wanted_tasks and tasks and not any(task in wanted_tasks for task in tasks):
            continue
        raw_needs = metadata.get("needs_references")
        needs: dict[str, Any] = raw_needs if isinstance(raw_needs, dict) else {}
        asked = wanted_tasks or tasks
        known = [task for task in asked if task in needs]
        if known and all(needs.get(task) for task in known):
            continue  # it only edits footage it is given; the studio has words and a still
        caps = row.capabilities if isinstance(row.capabilities, dict) else {}
        record = model_record(session, integration_id, requirement.purpose, remote_id)
        annotated = _number(caps.get("quality_score"), 0.5)
        price = _unit_price(session, integration_id, row, requirement.seconds)
        effective = record.get("cost_per_accepted_second")
        candidates.append(
            {
                "remote_id": remote_id,
                "status": str(row.production_status or "PRODUCTION"),
                "quality": _observed_quality(record, annotated),
                "annotated_quality": annotated,
                "price_usd": price,
                "price_per_second_usd": (
                    (price / requirement.seconds)
                    if price is not None and requirement.seconds
                    else None
                ),
                "effective_cost_per_second": effective,
                "delivers_studio_frame": delivers_studio_frame(
                    metadata, requirement.purpose, requirement.frame
                ),
                "record": record,
                "priced": price is not None,
            }
        )

    if forced:
        chosen = next((c for c in candidates if c["remote_id"] == forced), None)
        if chosen is not None:
            return _decision(
                chosen,
                candidates,
                environment,
                requirement,
                reason=f"Director's explicit choice: {forced}.",
                forced=True,
            )

    if not candidates:
        return {
            "model_id": None,
            "environment": environment,
            "requirement": asdict(requirement),
            "reason": "No model on this connection can do what the scene needs.",
            "candidates": [],
        }

    if environment == "TEST":
        # Compatibility, then availability, then cost — and nothing else. An unpriced model
        # goes last: an unpriced test is how an afternoon cost twenty-one dollars.
        order = sorted(
            candidates,
            key=lambda c: (
                not c["priced"],
                c["price_usd"] if c["price_usd"] is not None else float("inf"),
                c["remote_id"],
            ),
        )
        within = [c for c in order if _within_test_ceilings(c, requirement)]
        if not within:
            dearest = order[0]
            return {
                "model_id": None,
                "environment": environment,
                "scene_category": requirement.scene_category,
                "required_quality": 0.0,
                "reason": (
                    "Refused in TEST: the cheapest compatible model "
                    f"({dearest['remote_id']}) would cost {_money(dearest['price_usd'])} for "
                    f"{requirement.seconds:.1f}s, above the test ceiling. Raise the ceiling "
                    "or name the model explicitly."
                ),
                "considered": len(order),
                "blocked_by_ceiling": True,
            }
        return _decision(
            within[0],
            within,
            environment,
            requirement,
            reason=("Cheapest compatible model in TEST; the production ranking is not consulted."),
        )

    # PRODUCTION. Only models the studio has admitted to production may film a published
    # scene, and the frame comes first: upscaled footage in a 1080x1920 film is not premium.
    admitted = [c for c in candidates if c["status"] in PRODUCTION_READY]
    if not admitted:
        waiting = ", ".join(sorted(c["remote_id"] for c in candidates)[:4])
        return {
            "model_id": None,
            "environment": environment,
            "scene_category": requirement.scene_category,
            "required_quality": required_quality(requirement.tier),
            "reason": (
                "No model on this connection has been admitted to production for this "
                f"scene. Waiting outside production: {waiting}. A new model is benchmarked "
                "in TEST before it films anything that will be published."
            ),
            "considered": len(candidates),
            "blocked_by_lifecycle": True,
        }
    ready = [c for c in admitted if c["delivers_studio_frame"]] or admitted
    needed = required_quality(requirement.tier)
    affordable = [
        c
        for c in ready
        if requirement.budget_usd is None
        or c["price_usd"] is None
        or c["price_usd"] <= requirement.budget_usd
    ]
    pool = affordable or ready
    meeting = [c for c in pool if c["quality"] >= needed]

    def cost_key(c: dict[str, Any]) -> float:
        for value in (
            c.get("effective_cost_per_second"),
            c.get("price_per_second_usd"),
            c.get("price_usd"),
        ):
            if isinstance(value, int | float):
                return float(value)
        return float("inf")

    if meeting:
        chosen = min(meeting, key=lambda c: (cost_key(c), -c["quality"], c["remote_id"]))
        dearer = [
            c for c in pool if c["quality"] > chosen["quality"] and cost_key(c) > cost_key(chosen)
        ]
        reason = (
            f"{requirement.tier} needs {needed:.2f}; this model is expected at "
            f"{chosen['quality']:.2f} and is the least expensive that reaches it."
        )
        if dearer:
            best = max(dearer, key=lambda c: c["quality"])
            gain = best["quality"] - chosen["quality"]
            multiple = (cost_key(best) / cost_key(chosen)) if cost_key(chosen) else float("inf")
            reason += (
                f" {best['remote_id']} is expected at {best['quality']:.2f}"
                f" (+{gain:.2f}) for {multiple:.1f}x the cost, which the scene does not need."
            )
        return _decision(chosen, pool, environment, requirement, reason=reason)

    # Nothing reaches the requirement: take the best available and say so, rather than
    # pretending a tier was met.
    chosen = max(pool, key=lambda c: (c["quality"], -cost_key(c)))
    return _decision(
        chosen,
        pool,
        environment,
        requirement,
        reason=(
            f"No model reaches {needed:.2f} for {requirement.tier}; the best available is "
            f"{chosen['remote_id']} at an expected {chosen['quality']:.2f}."
        ),
        met=False,
    )


def _money(value: object) -> str:
    return f"{float(value):.2f} USD" if isinstance(value, int | float) else "an unknown amount"


def _within_test_ceilings(candidate: dict[str, Any], requirement: SceneRequirement) -> bool:
    """Whether a TEST generation may buy this model for this shot.

    Two ceilings, both from the settings: what one generation may cost and what one second
    may cost. An unpriced model passes — it is already ordered last — but a model whose
    price is known and above the ceiling is refused, which is the point of the ceiling.
    """
    price = candidate.get("price_usd")
    if requirement.budget_usd is not None and isinstance(price, int | float):
        if float(price) > float(requirement.budget_usd):
            return False
    if (
        requirement.max_usd_per_second is not None
        and isinstance(price, int | float)
        and requirement.seconds > 0
    ):
        if float(price) / requirement.seconds > float(requirement.max_usd_per_second):
            return False
    return True


def _decision(
    chosen: dict[str, Any],
    candidates: list[dict[str, Any]],
    environment: str,
    requirement: SceneRequirement,
    *,
    reason: str,
    forced: bool = False,
    met: bool = True,
) -> dict[str, Any]:
    """The choice, with what it was chosen over — what the page shows and the job records."""
    alternatives = [
        {
            "model_id": c["remote_id"],
            "quality": c["quality"],
            "price_usd": c["price_usd"],
            "status": c["status"],
        }
        for c in candidates
        if c["remote_id"] != chosen["remote_id"]
    ][:4]
    return {
        "model_id": chosen["remote_id"],
        "environment": environment,
        "requirement": asdict(requirement),
        "expected_quality": chosen["quality"],
        "required_quality": required_quality(requirement.tier),
        "requirement_met": met,
        "estimated_usd": chosen["price_usd"],
        "status": chosen["status"],
        "forced": forced,
        "reason": reason,
        "alternatives": alternatives,
        "candidates": len(candidates),
    }


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
    # The second vendor, resolved last so it is checked against the model the ranking and the
    # locks actually settled on. An empty chain is the studio as it was: one vendor, and the
    # still when it refuses.
    fallbacks, fallback_notes = approved_alternatives(session, purpose, merged, characters)
    notes.extend(fallback_notes)
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
        "approved_fallbacks": _fallback_entries(merged.get("approved_fallbacks")),
        "fallbacks": fallbacks,
        "notes": notes,
    }


def _fallback_entries(value: Any) -> list[dict[str, Any]]:
    """The approved-fallback list as pairs the resolver can check, ignoring anything else.

    Only a connection and a model make an alternative: a free-text name would resolve to
    nothing and a render would call it a second vendor.
    """
    entries: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        integration_id = item.get("integration_id")
        if not integration_id:
            continue
        model_id = item.get("model_id")
        entry = {
            "integration_id": str(integration_id),
            "model_id": str(model_id) if model_id else None,
        }
        if item.get("voice_id"):
            entry["voice_id"] = str(item["voice_id"])
        if entry not in entries:
            entries.append(entry)
    return entries


def approved_alternatives(
    session: Session,
    purpose: str,
    merged: dict[str, Any],
    characters: list[CharacterBible] | None = None,
    *,
    limit: int = MAX_FALLBACKS_PER_PURPOSE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The Owner's approved second vendors for this purpose, checked like the first one.

    Where they come from, in order: the approved-fallback list the hierarchy merged for this
    purpose, and — for a scene whose character has a locked look — that character's own
    `approved_fallbacks_json`, which is the list an APPROVED identity change writes. Nothing
    here proposes a vendor: a list nobody wrote is an empty chain, and the render falls back
    to the still exactly as it did before this existed.

    A locked character narrows the chain rather than widening it: an alternative must be
    approved for *every* locked character in the scene, because approval is the evidence
    that the technology keeps that character recognisable.
    """
    notes: list[str] = []
    locked = [c for c in (characters or []) if (c.identity_locks_json or {}).get("visual")]
    entries = _fallback_entries(merged.get("approved_fallbacks"))
    if not entries and locked:
        # A locked character's own approved list is an approved list for this purpose too.
        entries = _fallback_entries(locked[0].approved_fallbacks_json)
    for character in locked:
        approved = {
            (f.get("integration_id"), f.get("model_id"))
            for f in (character.approved_fallbacks_json or [])
            if isinstance(f, dict)
        }
        kept = [e for e in entries if (e["integration_id"], e["model_id"]) in approved]
        if len(kept) != len(entries):
            notes.append(
                f"Alternative technology not approved for {character.canonical_name} was "
                "left out of the fallback chain"
            )
        entries = kept

    chain: list[dict[str, Any]] = []
    for entry in entries:
        if len(chain) >= max(0, limit):
            break
        if (entry["integration_id"], entry["model_id"]) == (
            merged.get("integration_id"),
            merged.get("model_id"),
        ):
            continue  # the first vendor is not its own alternative
        valid, why = _validate(session, purpose, entry)
        if not valid:
            notes.append(f"Approved fallback is unusable: {why}")
            continue
        chain.append(
            {
                "purpose": purpose,
                "integration_id": entry["integration_id"],
                "model_id": entry["model_id"],
                "voice_id": entry.get("voice_id") or merged.get("voice_id"),
                "voice_settings": merged.get("voice_settings"),
                "strategy": "fixed",
                "criteria": None,
                "source_level": "fallback",
                "lock_applied": bool(locked),
                "character_id": locked[0].id if locked else None,
                "valid": True,
                "ranking": None,
                "notes": [],
            }
        )
    return chain, notes


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


#: Levels of the hierarchy where naming a model is a deliberate act: a channel, a series,
#: an episode, a scene, or a character's locked look. The Organization default is not one of
#: them — it is the connection's default model, and choosing between models is the studio's
#: job, which is exactly what the Owner asked the agent to start doing.
DELIBERATE_LEVELS = ("channel", "series", "episode", "scene", "character")


def named_model(plan: dict[str, Any], scene_index: object) -> str | None:
    """The video model a level of the hierarchy named for this scene, if any.

    A model a person chose for this channel, series, episode or scene is honoured over the
    policy's own ranking, and recorded as an override so the report says who decided.
    """
    if not isinstance(scene_index, int):
        return None
    for entry in plan.get("scenes", []):
        if entry.get("scene_index") != scene_index:
            continue
        video = entry.get("video") if isinstance(entry.get("video"), dict) else {}
        if str(video.get("source") or "") in DELIBERATE_LEVELS:
            model_id = video.get("model_id")
            return str(model_id) if model_id else None
        return None
    return None


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
        if "approved_fallbacks" in selection:
            # A second vendor is a connection and a model, not a name: anything else would be
            # stored as an approval and then resolve to nothing on the day a vendor refused.
            approved = selection["approved_fallbacks"]
            if not isinstance(approved, list) or not all(
                isinstance(entry, dict) and entry.get("integration_id") for entry in approved
            ):
                raise PolicyError(
                    f"{where}: '{purpose}' approved_fallbacks must be a list of "
                    "{integration_id, model_id} objects"
                )


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
