"""Phase 6 Publishing services, Content Gate evaluation, and lifecycle state transitions."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.factual.models import FactualClaim, ScriptDraft
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.models import CommandRecord, OwnerPolicy
from app.providers.publishing_base import (
    PublishingProvider,
    RemoteStateUnavailable,
    UploadResult,
    ask_reconcile,
)
from app.providers.retry import is_transient
from app.providers.youtube import (
    DEFAULT_CATEGORY_ID,
    DESCRIPTION_LIMIT_BYTES,
    fit_bytes,
    footer_start,
    register_footer_marker,
    youtube_safe_metadata,
)
from app.publishing.models import ChannelBrandAsset, ChannelRecord, PublicationRecord
from app.publishing.schemas import (
    ChannelView,
    PublicationView,
    PublishPolicyCommand,
)
from app.publishing.serial_identity import hook_of
from app.services import CommandConflict, append_event, utc_now
from app.wording import (
    AUTONOMY_STOPPED,
    COMMAND_REUSED,
    count,
    decimal,
    error_fields,
    error_words,
    publication_status,
    qc_status,
    sentence,
    settings_place,
    written_for_the_owner,
)
from app.wording import environment as environment_word
from app.wording import privacy as privacy_word


class PublishingGateError(Exception):
    """Raised when a media asset fails one or more publishing gate criteria."""

    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.reasons = reasons


class PublishingAssetNotFound(PublishingGateError):
    """Raised when the referenced media asset or channel does not exist."""


class PublicationNotResolvable(ValueError):
    """The Owner asked to settle a publication the studio is not waiting on him for."""


class PublisherNotConfigured(Exception):
    """Raised when no real publishing provider is configured.

    The studio must refuse to publish rather than fall back to a simulator (AGENTS.md:
    never mark a provider integration working based on mocks).
    """


#: The publish policy's two refusals of «public», in the page's words. W34: they named the
#: command's field (``public_publish_enabled=true``) and sent the Owner to «pagina Owner», a
#: page the studio does not have; the environment is the dock's MEDIU switch, and the flag is
#: the channel's own «publicul permis» in the same change.
PUBLIC_NEEDS_PRODUCTION = (
    "Studioul este în {environment}: publicarea autonomă nu poate fi setată pe „public”. "
    "Treci studioul în PRODUCTION cu comutatorul MEDIU, apoi permite publicul pe canal."
)
PUBLIC_NEEDS_ITS_FLAG = (
    "„public” se acceptă doar dacă în aceeași schimbare permiți și publicul pe canal; fără "
    "această permisiune încărcările rămân private."
)


class PublishPolicyError(ValueError):
    """The Owner's publish-policy command asks for something the studio will not set.

    Raised with the reason in the Owner's language; the route answers 422 with it. Distinct
    from `CommandConflict` (a stale version or a reused command id), which is not a refusal
    of the policy but of the write.
    """


#: The three visibilities YouTube knows, from the least seen to the most. Order matters:
#: the sixth gate check compares a requested visibility against the one the policy allows.
PRIVACY_LEVELS = ("private", "unlisted", "public")
PRIVACY_RANK = {level: rank for rank, level in enumerate(PRIVACY_LEVELS)}

#: A storyboard names its channel by id; when it does not, its series key can. The office
#: serial is the one series with its own channel slot, so its key routes to that slot;
#: everything else is a factual film for the main channel.
SERIES_CHANNEL_TYPES = {"office_serial": "OFFICE_SERIAL"}
DEFAULT_CHANNEL_TYPE = "MAIN_FACTUAL"
#: The longest Short quality control accepts on a channel that names none (YouTube's own
#: limit is 180 s since 2024-10-15; a channel's policy sets its own, migration 0053).
DEFAULT_SHORTS_MAX_SECONDS = 60
SHORTS_MAX_SECONDS_LIMIT = 180

ROUTE_SELECTED = "SELECTED"
ROUTE_SKIPPED = "SKIPPED"


# Channel slots the studio plans to use. A slot is NOT a configured channel: it carries no
# remote channel ID and no credentials until the Owner supplies real ones. Inventing a
# remote_channel_id or a CONFIGURED status here would fabricate external state.
DEFAULT_CHANNELS: list[dict[str, Any]] = [
    {
        "channel_name": "Main Channel A - Factual Shorts",
        "channel_type": "MAIN_FACTUAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "Real World. Verified Facts. 60-Second Deep Dives.",
        # Seed default only: production may pick technology per video. Editable in the API.
        "production_policy": "FLEXIBLE",
        # The longest film quality control accepts: YouTube's Shorts limit (the Owner,
        # 2026-10-16; migration 0058 raised the rows still at the old 60).
        "shorts_max_seconds": 180,
    },
    {
        "channel_name": "Channel B - Office Serial",
        "channel_type": "OFFICE_SERIAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "AMN-AI (Autonomous Machine Nexus): Unscripted Silicon Life.",
        # Seed default only: recurring characters keep their locked identity. Editable in the API.
        "production_policy": "CONSISTENCY_LOCKED",
        # Episodes are written for 90-180 s (the Owner, 2026-10-16; migration 0058 raised
        # the rows still at the old 70).
        "shorts_max_seconds": 180,
    },
]

# Channel lifecycle, per 22_PROVIDER_INTEGRATION_CONTRACTS.md common provider state.
CHANNEL_NOT_CONFIGURED = "NOT_CONFIGURED"  # no remote channel identity yet
CHANNEL_AUTH_REQUIRED = "AUTH_REQUIRED"  # identity known, no verified credentials
CHANNEL_AUTHENTICATED = "AUTHENTICATED"  # remote identity verified through Settings
CHANNEL_CONFIGURED = "CONFIGURED"  # fields present; access not verified


#: Minimum QC score accepted for publication (documented in the Distribution Hub UI).
QC_MINIMUM_SCORE = 0.90

#: Statuses that mean a publication exists on the channel or is on its way there. A record in
#: one of these states is a video the audience can already reach, or will.
LIVE_PUBLICATION_STATES = [
    "PUBLISHED",
    "PUBLISHED_SIMULATED",
    "REMOTE_CONFIRMED",
    "REMOTE_UNKNOWN",
    "STARTED",
    "SCHEDULED",
]

#: Statuses of an upload the channel confirmed: with a remote video id, a film that is out, or
#: booked to go out (the reading `media.shooting_sheet.film_is_closed` gives an upload). Every
#: other row (a gate refusal, an upload that failed or YouTube refused, an intent not yet run,
#: a retry, a simulated run) left nothing certain on the channel; the film may still be owed.
CONFIRMED_UPLOAD_STATES = ("PUBLISHED", "SCHEDULED", "REMOTE_CONFIRMED")


def film_identity(session: Session, media_asset_id: str) -> tuple[str | None, str | None]:
    """Which film a rendered file belongs to: its script, and the storyboard it was shot from.

    A file is not a film. The same script can be rendered many times — a retake, a fix to one
    shot, a second pass at the edit — and each render is a new `MediaAsset` with a new id. The
    audience does not see files; it sees the film. So identity for anything that asks "have we
    already put this out?" is the script, with the storyboard as the fallback when a storyboard
    has no script behind it. Returns ``(None, None)`` when provenance cannot be walked at all,
    which callers must treat as "unknown", never as "new".
    """
    job = session.scalars(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    ).first()
    if job is None or not job.storyboard_id:
        return (None, None)
    storyboard = session.get(Storyboard, job.storyboard_id)
    if storyboard is None:
        return (None, job.storyboard_id)
    return (storyboard.script_draft_id, storyboard.id)


def published_films(
    session: Session, channel_id: str, *, exclude_publication_id: str | None = None
) -> dict[str, PublicationRecord]:
    """Every film this channel already carries, keyed by the identity above.

    Keyed by both the script and the storyboard, so a candidate matches whichever of the two
    it can establish. Only live publications count: a failed upload left nothing on the
    channel and must not block the retry. ``exclude_publication_id`` is a publication that
    must not count as its own duplicate (the gate run again at execution).
    """
    carried: dict[str, PublicationRecord] = {}
    query = select(PublicationRecord).where(
        PublicationRecord.channel_id == channel_id,
        PublicationRecord.status.in_(LIVE_PUBLICATION_STATES),
    )
    if exclude_publication_id is not None:
        query = query.where(PublicationRecord.id != exclude_publication_id)
    for record in session.scalars(query):
        script_id, storyboard_id = film_identity(session, record.media_asset_id)
        for key in (script_id, storyboard_id):
            if key is not None:
                carried.setdefault(key, record)
    return carried


def file_sha256(path: Path) -> str:
    """The SHA-256 of a file, read in blocks (a film is hundreds of megabytes)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derive_channel_status(remote_channel_id: str | None, credentials_ref: str | None) -> str:
    """Derive channel status from what is actually present. Never assume configuration."""
    if not remote_channel_id:
        return CHANNEL_NOT_CONFIGURED
    if not credentials_ref:
        return CHANNEL_AUTH_REQUIRED
    return CHANNEL_CONFIGURED


def seed_default_channels(engine: Engine) -> int:
    """Pre-seed Channel A (Main) and Channel B (Office Serial) if not present.

    A channel row created before production policies existed has a NULL policy; the seed
    fills it from the same list, once. A policy the Owner has set is never touched.
    """
    with Session(engine) as session, session.begin():
        count = 0
        for ch in DEFAULT_CHANNELS:
            existing = session.scalars(
                select(ChannelRecord).where(ChannelRecord.channel_type == ch["channel_type"])
            ).first()
            if existing is not None and existing.production_policy is None:
                existing.production_policy = ch["production_policy"]
                count += 1
            if not existing:
                now = utc_now()
                ch_id = str(uuid4())
                event = append_event(
                    session,
                    "channel.created",
                    "channel_record",
                    ch_id,
                    1,
                    {"channel_name": ch["channel_name"], "channel_type": ch["channel_type"]},
                    str(uuid4()),
                )
                rec = ChannelRecord(
                    id=ch_id,
                    channel_name=ch["channel_name"],
                    channel_type=ch["channel_type"],
                    platform=ch["platform"],
                    remote_channel_id=None,
                    credentials_ref=None,
                    upload_privacy_default=ch["upload_privacy_default"],
                    status=CHANNEL_NOT_CONFIGURED,
                    production_policy=ch["production_policy"],
                    shorts_max_seconds=ch["shorts_max_seconds"],
                    created_at=now,
                    last_sync_at=None,
                    event_id=event.event_id,
                )
                session.add(rec)
                # Add default brand tagline asset
                tagline_asset = ChannelBrandAsset(
                    id=str(uuid4()),
                    channel_id=ch_id,
                    asset_type="TAGLINE",
                    content_or_uri=ch["brand_tagline"],
                    created_at=now,
                )
                session.add(tagline_asset)
                count += 1
        return count


#: How a channel record names the OAuth connection it publishes through.
CREDENTIALS_PREFIX = "youtube_connection:"


def bound_connection_id(channel: ChannelRecord) -> str | None:
    """The YouTube connection a channel slot publishes through, or None when unbound."""
    reference = channel.credentials_ref or ""
    if not reference.startswith(CREDENTIALS_PREFIX):
        return None
    return reference[len(CREDENTIALS_PREFIX) :]


def channel_bindings(engine: Engine) -> dict[str, dict]:
    """Per channel id: which connected YouTube account it is bound to, if any.

    A slot is publishable only when its binding points at a connection that is still
    CONNECTED — a revoked grant leaves the reference in place, and reading it as "ready"
    is how a studio comes to believe it can publish to an account it can no longer reach.
    """
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    with Session(engine) as session:
        connections = {c.id: c for c in session.scalars(select(YouTubeConnection))}
        bindings: dict[str, dict] = {}
        for channel in session.scalars(select(ChannelRecord)):
            identifier = bound_connection_id(channel)
            connection = connections.get(identifier or "")
            bindings[channel.id] = {
                "youtube_connection_id": identifier,
                "youtube_connection_name": connection.name if connection else None,
                "youtube_channel_title": connection.remote_channel_title if connection else None,
                "youtube_connection_status": connection.status if connection else None,
                "publisher_ready": bool(connection and connection.status == "CONNECTED"),
            }
        return bindings


def policy_snapshot(channel: ChannelRecord) -> dict[str, Any]:
    """The publish policy as the ledger records it, before and after a command."""
    return {
        "autonomous_privacy": channel.autonomous_privacy,
        "public_publish_enabled": bool(channel.public_publish_enabled),
        "publish_delay_minutes": int(channel.publish_delay_minutes or 0),
        "director_may_approve_episodes": bool(channel.director_may_approve_episodes),
        "youtube_category_id": str(channel.youtube_category_id or DEFAULT_CATEGORY_ID),
        "made_for_kids": bool(channel.made_for_kids),
        "default_language": channel.default_language or None,
        "shorts_max_seconds": int(channel.shorts_max_seconds or DEFAULT_SHORTS_MAX_SECONDS),
        "policy_version": int(channel.policy_version or 1),
    }


def change_publish_policy(engine: Engine, channel_id: str, command: PublishPolicyCommand) -> dict:
    """Set a channel's publish policy, the way the environment and the stop are set.

    Idempotent by command id (the same command again is the same answer; the same id with
    other input is a conflict), refusing a stale `expected_version`, and recorded as
    `publishing.channel_policy_changed` with the old and the new values and the environment
    the decision was taken in. "public" is accepted only with `public_publish_enabled=True`
    in the same command, so nobody flips one switch without the other, and never while the
    studio is in TEST: the environment says what a film may cost, and a public release is
    the one cost that cannot be refunded. A command that changes nothing is NO_CHANGE — no
    version bump, no event — so a page that re-sends the current values leaves no trace of a
    decision that was not taken.
    """
    payload_hash = hashlib.sha256(
        json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    command_id = str(command.command_id)
    with Session(engine) as session, session.begin():
        # The write lock first, as every Owner command takes it: the idempotency record and
        # the version are read under it, so two screens cannot both see version 1 and both
        # write version 2.
        lock_for_write(session)
        previous = session.get(CommandRecord, command_id)
        if previous:
            if previous.payload_hash != payload_hash:
                raise CommandConflict(COMMAND_REUSED)
            return dict(previous.response)
        channel = session.get(ChannelRecord, channel_id)
        if channel is None:
            raise LookupError(f"Canalul {channel_id} nu există.")
        if command.expected_version != int(channel.policy_version or 1):
            raise CommandConflict(
                "Politica de publicare a canalului s-a schimbat între timp; reîncarcă și "
                "trimite comanda din nou."
            )
        policy = session.get(OwnerPolicy, 1)
        # A row written before the column existed reads as None; TEST is the safe reading.
        environment = str(policy.environment or "TEST") if policy else "TEST"

        old = policy_snapshot(channel)
        new = dict(old)
        if command.autonomous_privacy is not None:
            new["autonomous_privacy"] = command.autonomous_privacy
        if command.public_publish_enabled is not None:
            new["public_publish_enabled"] = bool(command.public_publish_enabled)
        if command.publish_delay_minutes is not None:
            new["publish_delay_minutes"] = int(command.publish_delay_minutes)
        if command.director_may_approve_episodes is not None:
            new["director_may_approve_episodes"] = bool(command.director_may_approve_episodes)
        if command.youtube_category_id is not None:
            new["youtube_category_id"] = str(int(command.youtube_category_id))
        if command.made_for_kids is not None:
            new["made_for_kids"] = bool(command.made_for_kids)
        if command.default_language is not None:
            # "" goes back to the studio's content language.
            new["default_language"] = command.default_language or None
        if command.shorts_max_seconds is not None:
            new["shorts_max_seconds"] = int(command.shorts_max_seconds)

        if command.autonomous_privacy == "public":
            if environment != "PRODUCTION":
                raise PublishPolicyError(PUBLIC_NEEDS_PRODUCTION.format(environment=environment))
            if command.public_publish_enabled is not True:
                raise PublishPolicyError(PUBLIC_NEEDS_ITS_FLAG)

        # The word "public" is not the only way to a public policy. With the privacy already
        # reading "public" from a PRODUCTION day and the flag switched off, the flag alone
        # would switch the policy back on: measured in TEST, `public_publish_enabled=true`
        # on such a channel was COMMITTED. The rule is on the state the command would
        # leave, not on the field it names; a policy already public is left as it is.
        def _public(snapshot: dict[str, Any]) -> bool:
            return snapshot["autonomous_privacy"] == "public" and bool(
                snapshot["public_publish_enabled"]
            )

        if _public(new) and not _public(old) and environment != "PRODUCTION":
            raise PublishPolicyError(PUBLIC_NEEDS_PRODUCTION.format(environment=environment))

        changed = sorted(key for key in old if key != "policy_version" and old[key] != new[key])
        event_id = None
        if changed:
            channel.autonomous_privacy = new["autonomous_privacy"]
            channel.public_publish_enabled = new["public_publish_enabled"]
            channel.publish_delay_minutes = new["publish_delay_minutes"]
            channel.director_may_approve_episodes = new["director_may_approve_episodes"]
            channel.youtube_category_id = new["youtube_category_id"]
            channel.made_for_kids = new["made_for_kids"]
            channel.default_language = new["default_language"]
            channel.shorts_max_seconds = new["shorts_max_seconds"]
            channel.policy_version = old["policy_version"] + 1
            new["policy_version"] = channel.policy_version
            event = append_event(
                session,
                "publishing.channel_policy_changed",
                "channel_record",
                channel_id,
                channel.policy_version,
                {"old": old, "new": new, "changed": changed, "environment": environment},
                command_id,
            )
            channel.policy_changed_event_id = event.event_id
            event_id = event.event_id
            session.flush()
        result = {
            "command_id": command_id,
            "status": "COMMITTED" if changed else "NO_CHANGE",
            "channel": ChannelView.model_validate(channel).model_dump(),
            "event_id": event_id,
        }
        session.add(
            CommandRecord(
                idempotency_key=command_id,
                command_type="SetPublishPolicy",
                payload_hash=payload_hash,
                response=result,
                created_at=utc_now(),
            )
        )
        return result


def _rfc3339(moment: datetime) -> str:
    """The form YouTube's publishAt takes: UTC, whole seconds, a trailing Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_publish_visibility(
    channel: Any, environment: str | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """What an autonomous upload to this channel is allowed to be, and why.

    Pure: reads the channel's policy fields and the studio's environment, writes nothing. The
    daily run calls this instead of the constant "private" it used to hardcode.

    - "private" unless the policy says "unlisted" or "public".
    - "unlisted" only while the environment is PRODUCTION: an unlisted film is watched by
      anyone with the link, a release and not a draft, so TEST keeps it private. Measured
      with the policy set in TEST: the run uploaded unlisted while the studio said nothing
      leaves it visibly.
    - "public" only while `public_publish_enabled` is True AND the environment is
      PRODUCTION; otherwise the upload is private and the reason says which condition failed.
    - A public policy with `publish_delay_minutes > 0` is a scheduled release. YouTube
      schedules one as a **private** upload carrying `status.publishAt`; a public upload with
      a delay attached does not exist on the platform. So the result is
      ``privacy_status="private"`` plus ``publish_at`` (RFC 3339, `now` + delay) and
      ``release_privacy="public"``, which is what the film becomes at that time. The delay
      applies to public releases only: an unlisted film has no premiere to wait for.

    A row from before the policy existed (None in every field) resolves private. The
    `policy_version` in the result is the stamp the publication must carry through the gate.
    """
    privacy = str(getattr(channel, "autonomous_privacy", None) or "private")
    enabled = bool(getattr(channel, "public_publish_enabled", None))
    delay = int(getattr(channel, "publish_delay_minutes", None) or 0)
    version = int(getattr(channel, "policy_version", None) or 1)
    environment = str(environment or "TEST")

    def _result(status: str, reason: str) -> dict[str, Any]:
        return {
            "privacy_status": status,
            "publish_at": None,
            "release_privacy": status,
            "policy_version": version,
            "reason": reason,
        }

    if privacy not in PRIVACY_LEVELS:
        return _result(
            "private",
            f"Politica canalului cere o vizibilitate necunoscută („{privacy}”); încărcare privată.",
        )
    if privacy == "private":
        return _result("private", "Politica canalului: încărcare privată.")
    if privacy == "unlisted":
        if environment != "PRODUCTION":
            return _result(
                "private",
                f"Studioul este în {environment_word(environment)}: nimic nu pleacă vizibil. "
                "Încărcare privată.",
            )
        return _result("unlisted", "Politica canalului: nelistat, studioul în producție.")
    if not enabled:
        return _result(
            "private",
            "Politica canalului cere „public”, dar filmele publice nu sunt permise pe "
            "canal; încărcarea rămâne privată.",
        )
    if environment != "PRODUCTION":
        return _result(
            "private",
            f"Studioul este în {environment_word(environment)}: nimic nu pleacă public. "
            "Încărcare privată.",
        )
    if delay > 0:
        moment = now if now is not None else datetime.now(UTC)
        publish_at = _rfc3339(moment + timedelta(minutes=delay))
        return {
            "privacy_status": "private",
            "publish_at": publish_at,
            "release_privacy": "public",
            "policy_version": version,
            "reason": (
                f"Lansare publică programată peste {count(delay, 'minut', 'minute')} "
                f"({publish_at}): YouTube o primește ca încărcare privată cu data lansării."
            ),
        }
    return _result("public", "Politica canalului: public, studioul în producție.")


def channel_type_for_storyboard(storyboard: Storyboard) -> str:
    """Which channel slot a storyboard was produced for, when it names none by id."""
    key = str(storyboard.series_key or "").strip().lower()
    return SERIES_CHANNEL_TYPES.get(key, DEFAULT_CHANNEL_TYPE)


def select_channel_for(
    engine: Engine, media_asset_id: str | None = None, *, storyboard_id: str | None = None
) -> dict[str, Any]:
    """The channel a film goes to, and the account it goes through — or why it goes nowhere.

    Measured before this: the daily run published to `ready[0]`, the first bound slot, so a
    studio with the serial's account bound and the main channel's not would have put a
    factual film on the serial's channel. The film's storyboard decides: its `channel_id`
    when set, else its series key (the office serial has its own slot), else the main
    factual channel. A slot whose binding is missing or no longer CONNECTED is a refusal,
    SKIPPED with the reason, and never a fallback to another channel: the wrong channel is
    the one mistake no later check can undo. A `channel_id` that contradicts the series
    key is the same refusal: the media stage knows a film by its key (`is_serial_storyboard`),
    so a serial-keyed storyboard pinned to Channel A would have been filmed as the serial and
    sent to the factual channel — measured, SELECTED for MAIN_FACTUAL before this check.
    """
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    def skipped(reason: str, channel: ChannelRecord | None, channel_type: str | None) -> dict:
        return {
            "status": ROUTE_SKIPPED,
            "channel_id": channel.id if channel else None,
            "channel_type": channel.channel_type if channel else channel_type,
            "channel_name": channel.channel_name if channel else None,
            "youtube_connection_id": None,
            "remote_channel_id": None,
            "reason": reason,
        }

    with Session(engine) as session:
        if storyboard_id is None and media_asset_id is not None:
            _, storyboard_id = film_identity(session, media_asset_id)
        board = session.get(Storyboard, storyboard_id) if storyboard_id else None
        if board is None:
            return skipped(
                "Filmul nu are un storyboard în spate, deci nu se știe pentru ce canal a fost "
                "produs; nu pleacă nicăieri.",
                None,
                None,
            )
        channel = session.get(ChannelRecord, board.channel_id) if board.channel_id else None
        keyed = channel_type_for_storyboard(board)
        if channel is not None and channel.channel_type != keyed:
            return skipped(
                f"Storyboard-ul numește slotul „{channel.channel_name}” "
                f"({channel.channel_type}), dar după cheia de serie este un film pentru "
                f"{keyed}; o contradicție nu pleacă pe niciun canal.",
                None,
                keyed,
            )
        channel_type = channel.channel_type if channel else keyed
        if channel is None:
            channel = session.scalars(
                select(ChannelRecord)
                .where(ChannelRecord.channel_type == channel_type)
                .order_by(ChannelRecord.created_at)
            ).first()
        if channel is None:
            return skipped(
                f"Nu există niciun slot de canal {channel_type} în studio; filmul nu pleacă "
                "pe alt canal.",
                None,
                channel_type,
            )
        identifier = bound_connection_id(channel)
        connection = session.get(YouTubeConnection, identifier) if identifier else None
        if connection is None or connection.status != "CONNECTED":
            return skipped(
                f"Slotul „{channel.channel_name}” ({channel.channel_type}) nu este legat de "
                "un cont YouTube conectat; filmul nu pleacă pe alt canal. Leagă-l în "
                "Distribuție → Sloturi de canal.",
                channel,
                channel_type,
            )
        return {
            "status": ROUTE_SELECTED,
            "channel_id": channel.id,
            "channel_type": channel.channel_type,
            "channel_name": channel.channel_name,
            "youtube_connection_id": connection.id,
            "remote_channel_id": connection.remote_channel_id,
            "reason": f"Filmul merge pe {channel.channel_name} prin contul „{connection.name}”.",
        }


#: What the audience reads under every film, per content language: the opening words, how the
#: studio's name follows them when one is configured (STUDIO_DISPLAY_NAME), and the stop.
#: Configuration, never a brand in code (audit PUB-07, 2026-10-02): the Owner's own sentence
#: for a language (STUDIO_AI_DISCLOSURE_TEXTS, a JSON object such as {"de": "… {studio}."})
#: wins over these, and a language with neither reads the English one.
BUILTIN_DISCLOSURES: dict[str, tuple[str, str, str]] = {
    "en": ("Disclosure: this video was produced with generative AI", " by {studio}", "."),
    "ro": (
        "Mențiune: acest video a fost realizat cu inteligență artificială generativă",
        " de {studio}",
        ".",
    ),
}
for _opening, _by, _stop in BUILTIN_DISCLOSURES.values():
    register_footer_marker(_opening)
#: The English sentence with no studio named: what a studio with no configuration writes.
AI_DISCLOSURE = BUILTIN_DISCLOSURES["en"][0] + BUILTIN_DISCLOSURES["en"][2]
YOUTUBE_DESCRIPTION_LIMIT = DESCRIPTION_LIMIT_BYTES
#: The heading of the computed sources block, per upload language (English otherwise).
SOURCES_HEADINGS = {"en": "Sources:", "ro": "Surse:"}
#: At most this many source addresses under a film: the ones its first claims rest on.
MAX_SOURCES = 5


@functools.lru_cache(maxsize=1)
def _configured_settings() -> Any:
    try:
        from app.config import Settings  # noqa: PLC0415

        return Settings()  # type: ignore[call-arg]  # read from the environment and .env
    except Exception:  # noqa: BLE001 - an unreadable configuration reads as the defaults
        return None


def studio_settings() -> Any:
    """The studio's configuration for the callers that are handed none (the day's publish
    stage passes only the disclosure site and the creator's channel): the content language,
    the studio's display name and the Owner's disclosure sentences. Read once, the way
    `app.providers.retry` reads its own settings."""
    return _configured_settings()


def _language(settings: Any) -> str:
    return str(getattr(settings, "content_language", None) or "en").strip().lower() or "en"


def disclosure_sentence(settings: Any | None = None) -> str:
    """The disclosure line in the studio's content language, naming the studio when a name is
    configured. The Owner's own sentence for the language wins, with ``{studio}`` replaced by
    the name (removed when there is none)."""
    configured = settings if settings is not None else studio_settings()
    language = _language(configured)
    base = language.split("-")[0]
    name = " ".join(str(getattr(configured, "studio_display_name", None) or "").split())
    texts = getattr(configured, "ai_disclosure_texts", None)
    own = (texts.get(language) or texts.get(base)) if isinstance(texts, dict) else None
    template = " ".join(str(own or "").split())
    if template:
        opening = template.split("{studio}")[0].strip()
        text = " ".join(template.replace("{studio}", name).split())
        text = re.sub(r"\s+([.,;:!?])", r"\1", text)
        register_footer_marker(opening if len(opening) >= 8 else text.rstrip(".!"))
        return text
    opening, by, stop = BUILTIN_DISCLOSURES.get(base, BUILTIN_DISCLOSURES["en"])
    return opening + (by.format(studio=name) if name else "") + stop


def channel_link(connection: Any) -> str | None:
    """The public address of a connected channel: its handle when it has one, else its id."""
    snapshot = getattr(connection, "channel_snapshot", None)
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except ValueError:
            snapshot = None
    handle = (
        str((snapshot or {}).get("custom_url") or "").strip() if isinstance(snapshot, dict) else ""
    )
    if handle:
        return f"https://www.youtube.com/{handle if handle.startswith('@') else '@' + handle}"
    remote = str(getattr(connection, "remote_channel_id", "") or "").strip()
    return f"https://www.youtube.com/channel/{remote}" if remote else None


def publication_footer(
    engine: Engine | None,
    disclosure_url: str | None,
    creator_channel_title: str | None,
    *,
    settings: Any | None = None,
) -> str:
    """The disclosure, the studio's site when one is configured, and the creator's channel.

    The disclosure is `disclosure_sentence` for ``settings`` (the studio's configuration when
    none is given). The creator is named by the title of a connected YouTube channel and
    linked from that connection, so the address is the one the studio actually holds — not
    one typed here. A title that matches no connection is still credited, without a link,
    rather than dropped.
    """
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    sentence = disclosure_sentence(settings)
    url = (disclosure_url or "").strip()
    lines = [f"{sentence} {url}" if url else sentence]
    title = (creator_channel_title or "").strip()
    if title and engine is None:
        lines.append(f"Created by {title}")
    elif title and engine is not None:
        with Session(engine) as session:
            match = next(
                (
                    row
                    for row in session.scalars(select(YouTubeConnection))
                    if (row.remote_channel_title or "").strip().casefold() == title.casefold()
                ),
                None,
            )
            link = channel_link(match) if match is not None else None
        lines.append(f"Created by {title}: {link}" if link else f"Created by {title}")
    return "\n".join(lines)


def with_footer(description: str, footer: str | None) -> str:
    """The description with the studio's block at the end, once, inside YouTube's 5000 bytes:
    a block already there (from any known disclosure on) is replaced, never doubled, and the
    text above it is what gets cut."""
    if not footer:
        return description
    if footer_start(footer) != 0:
        # A footer opening with words no disclosure is known by is still found again.
        register_footer_marker(footer.splitlines()[0])
    body = description or ""
    cut = footer_start(body)
    if cut >= 0:
        body = body[:cut]
    body = body.rstrip()
    _, fitted, _ = youtube_safe_metadata("", f"{body}\n\n{footer}" if body else footer, [])
    return fitted


def list_channels(engine: Engine) -> list[dict]:
    bindings = channel_bindings(engine)
    with Session(engine) as session:
        channels = session.scalars(select(ChannelRecord).order_by(ChannelRecord.created_at)).all()
        return [
            {**ChannelView.model_validate(c).model_dump(), **bindings.get(c.id, {})}
            for c in channels
        ]


def get_channel(engine: Engine, channel_id: str) -> dict | None:
    with Session(engine) as session:
        ch = session.get(ChannelRecord, channel_id)
        if not ch:
            return None
        return ChannelView.model_validate(ch).model_dump()


def configure_channel(
    engine: Engine,
    channel_id: str,
    channel_name: str | None,
    remote_channel_id: str | None,
    credentials_ref: str | None,
    upload_privacy_default: str,
    correlation_id: str,
) -> dict:
    with Session(engine) as session, session.begin():
        ch = session.get(ChannelRecord, channel_id)
        if not ch:
            raise ValueError(f"Channel {channel_id} not found")
        if channel_name:
            ch.channel_name = channel_name
        if remote_channel_id:
            ch.remote_channel_id = remote_channel_id
        if credentials_ref is not None:
            ch.credentials_ref = credentials_ref or None
        ch.status = derive_channel_status(ch.remote_channel_id, ch.credentials_ref)
        ch.upload_privacy_default = upload_privacy_default
        ch.last_sync_at = utc_now()

        event = append_event(
            session,
            "channel.configured",
            "channel_record",
            channel_id,
            1,
            {"upload_privacy_default": upload_privacy_default, "status": ch.status},
            correlation_id,
        )
        ch.event_id = event.event_id
        session.flush()
        return ChannelView.model_validate(ch).model_dump()


def film_attributions(session: Session, media_asset_id: str) -> list[str]:
    """The credits the film's music and ambience licences require, from its render's record
    (production['audio']['attributions'])."""
    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    )
    manifest = job.production_json if job is not None else None
    audio = manifest.get("audio") if isinstance(manifest, dict) else None
    lines = audio.get("attributions") if isinstance(audio, dict) else None
    return [str(line).strip() for line in lines or [] if str(line).strip()]


def with_attributions(description: str, attributions: list[str]) -> str:
    """The description with each required credit written once, just above the studio's block
    (`footer_start`) or at the end, inside YouTube's limit. A credit already there is not
    written again."""
    body = description or ""
    missing = [line for line in dict.fromkeys(attributions) if line and line not in body]
    if not missing:
        return body
    return _above_footer(body, "\n".join(missing))


def _above_footer(description: str, block: str) -> str:
    """``block`` written just above the studio's block, or at the end; the text above it is
    what YouTube's 5000 bytes cut, never the block or the footer."""
    cut = footer_start(description)
    head, tail = (
        (description[:cut].rstrip(), description[cut:]) if cut >= 0 else (description.rstrip(), "")
    )
    kept = "\n\n".join(part for part in (block, tail) if part)
    room = DESCRIPTION_LIMIT_BYTES - len(kept.encode("utf-8")) - 2
    if len(head.encode("utf-8")) > room:
        head = fit_bytes(head, room) if room > 0 else ""
    return "\n\n".join(part for part in (head, kept) if part)


def _http_address(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.lower().startswith(("https://", "http://")) or any(c.isspace() for c in text):
        return None
    return text


def film_sources(session: Session, media_asset_id: str, *, limit: int = MAX_SOURCES) -> list[str]:
    """The addresses a factual film's SUPPORTED claims rest on, in the order the script cites
    them, each page once, at most ``limit`` (audit PUB-10). A film of the office serial, or one
    with no script, has none: an episode is not a claim about the world."""
    from app.factual.models import SourceSnapshot  # noqa: PLC0415

    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
    )
    board = session.get(Storyboard, job.storyboard_id) if job and job.storyboard_id else None
    if board is None or not board.script_draft_id:
        return []
    channel = session.get(ChannelRecord, board.channel_id) if board.channel_id else None
    kind = channel.channel_type if channel is not None else channel_type_for_storyboard(board)
    if kind != DEFAULT_CHANNEL_TYPE:
        return []
    script = session.get(ScriptDraft, board.script_draft_id)
    cited = [str(item) for item in (script.claim_ids_json if script else None) or []]
    if not cited:
        return []
    claims = {
        claim.id: claim
        for claim in session.scalars(
            select(FactualClaim).where(
                FactualClaim.id.in_(cited),
                FactualClaim.status == "SUPPORTED",
                FactualClaim.source_id.is_not(None),
            )
        )
    }
    addresses: list[str] = []
    seen: set[str] = set()
    for claim_id in dict.fromkeys(cited):
        claim = claims.get(claim_id)
        source = session.get(SourceSnapshot, claim.source_id) if claim is not None else None
        address = _http_address(source.url if source is not None else None)
        if address is None:
            continue
        key = address.rstrip("/").casefold()
        if key in seen:
            continue
        seen.add(key)
        addresses.append(address)
        if len(addresses) >= limit:
            break
    return addresses


def sources_heading(language: str | None) -> str:
    base = str(language or "en").strip().lower().split("-")[0]
    return SOURCES_HEADINGS.get(base, SOURCES_HEADINGS["en"])


def with_sources(description: str, addresses: list[str], heading: str = "Sources:") -> str:
    """The description with the film's sources listed once, under ``heading``, above the
    studio's block (and above any licence credits added after it)."""
    body = description or ""
    missing = [address for address in dict.fromkeys(addresses) if address and address not in body]
    if not missing:
        return body
    return _above_footer(body, "\n".join([heading, *missing]))


def upload_language(channel: ChannelRecord | None) -> str:
    """What the channel's uploads are written in and say: its own language, else the studio's
    content language."""
    own = str(getattr(channel, "default_language", None) or "").strip()
    return own or _language(studio_settings())


def upload_settings(channel: ChannelRecord | None) -> dict[str, Any]:
    """The upload's own settings from the channel's policy (migration 0053), as the adapter
    takes them in ``extra``."""
    return {
        "category_id": str(getattr(channel, "youtube_category_id", None) or DEFAULT_CATEGORY_ID),
        "made_for_kids": bool(getattr(channel, "made_for_kids", False)),
        "default_language": upload_language(channel),
    }


def film_title(session: Session, media_asset_id: str) -> str:
    """The film's own title, from its script (else its storyboard), for an upload whose
    title came out empty."""
    script_id, storyboard_id = film_identity(session, media_asset_id)
    script = session.get(ScriptDraft, script_id) if script_id else None
    if script is not None and script.title:
        return hook_of(script.title)
    board = session.get(Storyboard, storyboard_id) if storyboard_id else None
    return hook_of(board.title) if board is not None and board.title else ""


def evaluate_publishing_gate(
    engine: Engine,
    media_asset_id: str,
    channel_id: str,
    *,
    privacy_status: str = "private",
    policy_version: int | None = None,
    scheduled_publish_time: str | None = None,
    exclude_publication_id: str | None = None,
) -> dict:
    """Evaluate the 5 mandatory publishing gates per 50_CONTENT_GATE_MATRIX.md.

    ``exclude_publication_id`` is the publication being executed when the gate is asked again
    at the last moment (PUB-04): it must not be its own duplicate. The file check compares the
    file's SHA-256 with the one quality control passed (PUB-14), so a file replaced on disk
    after QC is not uploaded under a PASSED verdict.

    A sixth check runs only for a publication that would be seen — unlisted, public, or a
    private upload with a scheduled public release — and asks whether the channel's policy
    authorised that: the publication must carry the channel's current `policy_version`, and
    the visibility it asks for must be no more open than what that policy resolves to in the
    studio's environment. A private upload needs no authorisation and gets the five checks
    it always had.
    """
    checks: list[dict] = []
    reasons: list[str] = []
    # One code per reason, in the same order: the sentence is the Owner's, the code is the
    # record's (a page, a test or a person diagnosing reads it without parsing the sentence).
    reason_codes: list[str] = []

    def check(name: str, passed: bool, detail: str, **data: Any) -> None:
        checks.append({"check_name": name, "passed": passed, "detail": detail, "data": data})

    def refuse(code: str, reason: str) -> None:
        reason_codes.append(code)
        reasons.append(reason)

    with Session(engine) as session:
        # Gate 1: Global Autonomy Stop check
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            check("AUTONOMY_GATE", False, AUTONOMY_STOPPED, autonomy_stopped=True)
            refuse("AUTONOMY_STOPPED", "Autonomia studioului este oprită")
        else:
            check(
                "AUTONOMY_GATE",
                True,
                "Autonomia studioului este pornită.",
                autonomy_stopped=False,
            )

        # Gate 2: Media Asset valid on disk
        asset = session.get(MediaAsset, media_asset_id)
        if not asset:
            check(
                "MEDIA_ASSET_EXISTS",
                False,
                "Materialul cerut nu există în evidența studioului.",
                media_asset_id=media_asset_id,
            )
            refuse("MEDIA_ASSET_MISSING", "Materialul nu există în evidența studioului")
        else:
            p = Path(asset.uri_or_path)
            if not p.is_file() or p.stat().st_size == 0:
                check(
                    "MEDIA_ASSET_ON_DISK",
                    False,
                    f"Fișierul materialului lipsește de pe disc sau este gol: {asset.uri_or_path}.",
                    path=asset.uri_or_path,
                )
                refuse(
                    "MEDIA_FILE_MISSING",
                    "Fișierul materialului lipsește de pe disc sau are 0 octeți",
                )
            else:
                size = p.stat().st_size
                actual = file_sha256(p)
                expected = str(asset.provenance_hash or "").strip().lower()
                if actual != expected:
                    check(
                        "MEDIA_ASSET_ON_DISK",
                        False,
                        "Fișierul de pe disc nu este cel trecut de controlul calității "
                        f"(amprenta SHA-256 {actual[:12]}… nu este {expected[:12] or '—'}…).",
                        path=asset.uri_or_path,
                        bytes=size,
                        sha256=actual,
                        provenance_hash=asset.provenance_hash,
                    )
                    refuse(
                        "MEDIA_HASH_MISMATCH",
                        "Fișierul de pe disc nu este cel trecut de controlul calității",
                    )
                else:
                    check(
                        "MEDIA_ASSET_ON_DISK",
                        True,
                        f"Fișierul este pe disc ({count(size, 'octet', 'octeți')}) și este "
                        "cel trecut de controlul calității.",
                        path=asset.uri_or_path,
                        bytes=size,
                    )

        # Gate 3: Technical & Quality Control (QC) Passed
        qc = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        qc_code = qc.status if qc else "MISSING"
        if not qc or qc.status != "PASSED":
            said = qc_status(qc_code)
            check(
                "QC_GATE",
                False,
                f"Controlul calității: {said}"
                + ("" if qc else " (niciun raport pentru acest material)")
                + "; publicarea cere un control trecut.",
                qc_status=qc_code,
                qc_score=qc.score if qc else None,
                qc_minimum=QC_MINIMUM_SCORE,
            )
            refuse("QC_NOT_PASSED", f"Controlul calității: {said}")
        elif (qc.score or 0.0) < QC_MINIMUM_SCORE:
            scored = (
                f"Scorul controlului calității, {decimal(qc.score or 0.0)}, este sub minimul "
                f"de {decimal(QC_MINIMUM_SCORE)}"
            )
            check(
                "QC_GATE",
                False,
                f"{scored}.",
                qc_status=qc_code,
                qc_score=qc.score,
                qc_minimum=QC_MINIMUM_SCORE,
            )
            refuse("QC_SCORE_BELOW_MINIMUM", scored)
        else:
            check(
                "QC_GATE",
                True,
                f"Controlul calității a trecut, cu scorul {decimal(qc.score or 0.0)}.",
                qc_status=qc_code,
                qc_score=qc.score,
                qc_minimum=QC_MINIMUM_SCORE,
            )

        # Gate 4: Factual Claim Integrity Check
        #
        # This gate answers one question: is every factual claim this video makes backed by a
        # claim record marked SUPPORTED? Answering it requires walking asset -> render job ->
        # storyboard -> script. If any link is missing the question has not been answered, and an
        # unanswered gate is a failed gate. An earlier version fell through to "Asset has
        # verified factual provenance" — passing the asset while asserting a verification that
        # never took place, which is the exact defect the 2026-09-09 audit found elsewhere.
        # 50_CONTENT_GATE_MATRIX.md gives NOT_APPLICABLE its own outcome ("record reason"); it is
        # not a synonym for PASS.
        script_id, storyboard_id = film_identity(session, media_asset_id)
        script = session.get(ScriptDraft, script_id) if script_id else None

        if script is None:
            missing_code, missing = (
                ("NO_RENDER_JOB", "nicio randare nu a produs acest material")
                if storyboard_id is None
                else ("NO_SCRIPT", "storyboardul nu are un scenariu în spate")
            )
            check(
                "FACTUAL_INTEGRITY_GATE",
                False,
                f"Proveniența nu poate fi stabilită: {missing}. Afirmațiile filmului nu pot "
                "fi verificate față de nimic.",
                missing=missing_code,
                storyboard_id=storyboard_id,
            )
            refuse(
                "FACTUAL_PROVENANCE_UNKNOWN",
                f"Proveniența factuală nu poate fi verificată: {missing}",
            )
        else:
            referenced = list(script.claim_ids_json or [])
            claims = session.scalars(
                select(FactualClaim).where(FactualClaim.id.in_(referenced))
            ).all()
            found = {claim.id for claim in claims}
            # A claim id with no row behind it is not a verified claim; it is a dangling
            # reference, and silently dropping it would let a script cite anything at all.
            dangling = [claim_id for claim_id in referenced if claim_id not in found]
            unverified_claims = [claim.id for claim in claims if claim.status != "SUPPORTED"]
            if dangling or unverified_claims:
                trouble = []
                if unverified_claims:
                    trouble.append(
                        count(
                            len(unverified_claims),
                            "afirmație neverificată sau infirmată",
                            "afirmații neverificate sau infirmate",
                        )
                    )
                if dangling:
                    trouble.append(
                        count(
                            len(dangling),
                            "afirmație citată care nu există în evidență",
                            "afirmații citate care nu există în evidență",
                        )
                    )
                check(
                    "FACTUAL_INTEGRITY_GATE",
                    False,
                    "Scenariul are " + " și ".join(trouble) + ".",
                    script_id=script.id,
                    claim_ids=referenced,
                    unverified_claim_ids=unverified_claims,
                    missing_claim_ids=dangling,
                )
                refuse(
                    "CLAIMS_NOT_SUPPORTED",
                    "Nu toate afirmațiile scenariului sunt verificate: " + " și ".join(trouble),
                )
            elif referenced:
                check(
                    "FACTUAL_INTEGRITY_GATE",
                    True,
                    "Afirmația citată de scenariu este verificată."
                    if len(claims) == 1
                    else f"Toate cele {count(len(claims), 'afirmație citată', 'afirmații citate')}"
                    " de scenariu sunt verificate.",
                    script_id=script.id,
                    claim_ids=referenced,
                )
            else:
                # A script that asserts nothing factual has nothing to verify. Said plainly,
                # rather than dressed up as a verification that happened.
                check(
                    "FACTUAL_INTEGRITY_GATE",
                    True,
                    "Scenariul nu citează nicio afirmație factuală; nu este nimic de verificat.",
                    script_id=script.id,
                    claim_ids=[],
                )

        # Gate 5: Idempotency & Duplicate Publishing Check
        #
        # The check used to compare `media_asset_id`, which protects against uploading the same
        # FILE twice and nothing more. A film rendered a second time — a retake, a re-edit, a
        # repeated render — is a different asset id carrying the same script, and every gate
        # passed it: the channel would receive the same video again, and again, once per render
        # sitting in the queue. Identity here is the film (see `film_identity`), so a script
        # already on this channel is not offered to it twice, whichever file it was rendered
        # into. Cross-posting to a DIFFERENT channel stays allowed: the gate is per channel.
        duplicates = select(PublicationRecord).where(
            PublicationRecord.channel_id == channel_id,
            PublicationRecord.media_asset_id == media_asset_id,
            PublicationRecord.status.in_(LIVE_PUBLICATION_STATES),
        )
        if exclude_publication_id is not None:
            duplicates = duplicates.where(PublicationRecord.id != exclude_publication_id)
        existing_pub = session.scalars(duplicates).first()
        same_film = None
        if existing_pub is None:
            script_id, storyboard_id = film_identity(session, media_asset_id)
            carried = published_films(
                session, channel_id, exclude_publication_id=exclude_publication_id
            )
            for key in (script_id, storyboard_id):
                if key is not None and key in carried:
                    same_film = carried[key]
                    break
        if existing_pub:
            check(
                "DUPLICATE_PROTECTION_GATE",
                False,
                "Materialul este deja publicat sau în curs de publicare pe acest canal "
                f"(ID YouTube: {existing_pub.remote_video_id or '—'}).",
                publication_id=existing_pub.id,
                publication_status=existing_pub.status,
                remote_video_id=existing_pub.remote_video_id,
            )
            refuse(
                "DUPLICATE_ASSET",
                "Publicare dublă oprită: materialul este deja pe acest canal",
            )
        elif same_film is not None:
            check(
                "DUPLICATE_PROTECTION_GATE",
                False,
                f"Filmul este deja pe canal ca „{same_film.title}” (ID YouTube: "
                f"{same_film.remote_video_id or '—'}); acest material este o altă randare a "
                "aceluiași scenariu.",
                publication_id=same_film.id,
                publication_status=same_film.status,
                remote_video_id=same_film.remote_video_id,
            )
            refuse(
                "DUPLICATE_FILM",
                "Publicare dublă oprită: același film este deja pe acest canal ca "
                f"{same_film.remote_video_id or same_film.id}",
            )
        else:
            check(
                "DUPLICATE_PROTECTION_GATE",
                True,
                "Filmul nu este deja pe acest canal.",
            )

        # Gate 6: Policy authorisation, only for a publication that would be seen.
        #
        # A scheduled release is a private upload today and a public film at publishAt, so
        # it is judged as public. The stamp is the channel's `policy_version` at the moment
        # the visibility was resolved; a stamp from a policy that has since changed is a
        # decision the Owner has revoked, and a request more open than the policy resolves to
        # (an unlisted intent on a private channel) was never authorised at all.
        requested = "public" if scheduled_publish_time else str(privacy_status or "private")
        if requested != "private":
            channel = session.get(ChannelRecord, channel_id)
            current = int(channel.policy_version or 1) if channel else None
            env = str(policy.environment or "TEST") if policy else "TEST"
            resolved = resolve_publish_visibility(channel, env) if channel else None
            if resolved is None:
                authorised = "private"
            elif resolved["publish_at"]:
                authorised = resolved["release_privacy"]
            else:
                authorised = resolved["privacy_status"]
            wanted, allowed = privacy_word(requested), privacy_word(authorised)
            where = environment_word(env)
            facts = {
                "requested": requested,
                "authorised": authorised,
                "policy_version": policy_version,
                "current_policy_version": current,
                "environment": env,
            }
            code: str | None
            if channel is None:
                code = "POLICY_NO_CHANNEL"
                detail = (
                    f"Canalul cerut nu există; nicio politică nu poate autoriza un film {wanted}."
                )
                reason = f"Nicio politică de canal nu autorizează un film {wanted}"
            elif policy_version is None:
                code = "POLICY_NO_VERSION"
                detail = (
                    f"Un film {wanted} nu poartă versiunea politicii canalului; doar o "
                    "politică de publicare stabilită de Proprietar poate face un film vizibil."
                )
                reason = f"Nicio versiune a politicii de publicare nu autorizează un film {wanted}"
            elif int(policy_version) != current:
                code = "POLICY_VERSION_STALE"
                detail = (
                    f"Publicarea poartă versiunea {policy_version} a politicii, dar canalul "
                    f"este la versiunea {current}; Proprietarul a schimbat politica după ce "
                    "vizibilitatea a fost stabilită."
                )
                reason = (
                    f"Politica de publicare s-a schimbat de la versiunea {policy_version}; "
                    f"canalul este la versiunea {current}"
                )
            elif PRIVACY_RANK.get(requested, 99) > PRIVACY_RANK.get(authorised, -1):
                code = "POLICY_VISIBILITY_EXCEEDED"
                detail = (
                    f"Politica canalului (versiunea {current}) permite un film {allowed} în "
                    f"{where}, nu {wanted}: {resolved['reason'] if resolved else ''}"
                ).rstrip(": ")
                reason = (
                    f"Versiunea {current} a politicii canalului autorizează un film {allowed}, "
                    f"nu {wanted}"
                )
            else:
                code = None
                detail = (
                    f"Versiunea {current} a politicii canalului autorizează un film {wanted} "
                    f"în {where}."
                )
                reason = None
            check("POLICY_AUTHORISATION_GATE", code is None, detail, **facts)
            if code is not None and reason is not None:
                refuse(code, reason)

        # Gate 7: Rights, only for a publication that would be seen (AR-15). A film whose
        # components do not all prove commercial use (NEEDS_REVIEW) may be uploaded private
        # and nothing more. A status nobody knows never gets here: quality control fails it.
        if requested != "private" and asset is not None:
            from app.media.qc import (  # noqa: PLC0415 - qc is heavy; read on demand
                PRIVATE_ONLY_LICENCE_STATUSES,
                rights_verdict,
            )

            job = session.scalar(
                select(VideoRenderJob).where(VideoRenderJob.output_asset_id == media_asset_id)
            )
            manifest = job.production_json if job is not None else None
            rights = rights_verdict(
                asset.license_status, manifest if isinstance(manifest, dict) else {}
            )
            wanted = privacy_word(requested)
            if rights["license_status"] not in PRIVATE_ONLY_LICENCE_STATUSES:
                check(
                    "RIGHTS_GATE",
                    True,
                    f"Licența filmului ({rights['license_status']}) permite un film {wanted}.",
                    license_status=rights["license_status"],
                )
            else:
                check(
                    "RIGHTS_GATE",
                    False,
                    f"Un film {wanted} cere dovada licenței comerciale pentru fiecare componentă: "
                    + rights["detail"],
                    license_status=rights["license_status"],
                    missing_ro=rights["missing_ro"],
                )
                refuse(
                    "RIGHTS_NEEDS_REVIEW",
                    f"Licența filmului trebuie verificată înainte de un film {wanted}",
                )

    eligible = len(reasons) == 0
    return {
        "media_asset_id": media_asset_id,
        "channel_id": channel_id,
        "eligible": eligible,
        "checks": checks,
        "reasons": reasons,
        "reason_codes": reason_codes,
    }


# ---------------------------------------------------------------- an episode's own metadata --

#: How far back "the same day" reaches for another film's metadata. A window, not a calendar
#: date: the daily run can straddle midnight, and a copy made at 23:50 is the same mistake at
#: 00:10.
METADATA_COPY_WINDOW = timedelta(hours=24)

#: Words that say nothing about what a film is: a title sharing only these with its episode
#: shares nothing. English and Romanian, because the Publisher writes in the audience's
#: language and the showrunner writes the episode in the studio's.
_FILLER_TERMS = frozenset(
    "the and for with what that this from how why who are was were its his her not but you "
    "out all one can has have had into about over when where which your their there they "
    "them then than just also more most very some any each our ours will would could should "
    "does did done being been is it in on of to at by an or as be do if so no up we he she "
    "pentru care este sunt cum dar din dupa sau mai lui cei cel cea ale unei unui prin spre "
    "fara intr intre catre despre acest aceasta acesta aceste acei ceea cand unde cine ce "
    "nu da si sa se la de pe cu un o in al ai ei ea el".split()
)
_TERM = re.compile(r"[^\W_]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    """The words of a text that can carry meaning: case and diacritics folded, fillers out."""
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return {w for w in _TERM.findall(plain) if len(w) >= 3 and w not in _FILLER_TERMS}


def _shares_a_term(title_terms: set[str], source_terms: set[str]) -> bool:
    """One word in common, or one inflection of it: Romanian and English both bend the ending
    ("biroul"/"birou", "lights"/"light"), so five shared leading letters count as one word."""
    if title_terms & source_terms:
        return True
    stems = {t[:5] for t in source_terms if len(t) >= 5}
    return any(len(t) >= 5 and t[:5] in stems for t in title_terms)


def _same_metadata_key(title: str, tags: list[str]) -> tuple[str, frozenset[str]]:
    """What "word for word" compares: the title and the set of tags, spacing and case aside.

    The title is read without the series marker the studio adds to every episode (S10,
    ``<hook> | Inside The Nexus Ep. N``), so another film's title copied as the hook is still
    the copy it is.
    """
    return (
        " ".join(hook_of(str(title or "")).split()).casefold(),
        frozenset(" ".join(str(t).split()).casefold() for t in tags or [] if str(t).strip()),
    )


def _episode_words(session: Session, script: ScriptDraft) -> str:
    """Everything the episode itself says: its title, its lines, its scenes, who is in it,
    and the summary the showrunner wrote — read from the script the film was shot from and
    from the episode row behind it."""
    from app.story.models import StoryEpisode  # noqa: PLC0415 - story imports publishing

    parts: list[str] = [script.title or "", script.voiceover_full_text or ""]
    for scene in script.scenes_json or []:
        if isinstance(scene, dict):
            parts += [str(scene.get("narration") or ""), str(scene.get("visual_description") or "")]
            parts += [str(name) for name in scene.get("characters") or []]
    story = script.story_json if isinstance(script.story_json, dict) else {}
    episode_id = story.get("episode_id")
    episode = session.get(StoryEpisode, episode_id) if episode_id else None
    if episode is not None:
        parts.append(episode.title or "")
        for beat in episode.beats_json or []:
            if isinstance(beat, dict):
                parts += [str(beat.get("scene") or ""), str(beat.get("dialogue") or "")]
                parts += [str(name) for name in beat.get("characters") or []]
        continuity = episode.continuity_json if isinstance(episode.continuity_json, dict) else {}
        parts.append(str(continuity.get("summary") or ""))
    return "\n".join(parts)


def publication_metadata_refusals(
    session: Session,
    media_asset_id: str,
    channel_id: str,
    title: str,
    tags: list[str],
) -> list[str]:
    """Why an office-serial episode may not go out under this title and these tags, in Romanian.

    Measured in the rehearsal of 2026-09-18: the factual film and the serial episode both went
    up as 'Infrared light and what it shows', tagged space/astronomy. The studio had asked for
    each film's metadata from its own storyboard; the stand-in model answered every Publisher
    prompt with the same JSON. A real model can make that mistake too, and a wrong title on
    YouTube is public, so two things are computed before an episode leaves:

    - its title and tags must not be, word for word, those of another film prepared or
      published in the last 24 hours for a different channel;
    - its title must share at least one meaning-bearing word with the episode itself (its
      title, lines, scenes, characters, summary). That is a necessary condition, not proof
      the title is good: it catches a title about something else entirely, nothing finer.

    An episode is a film whose script says it is one (`story_json.kind`, written by
    `storyboard_from_episode`). Every other film returns no reason: the factual film's
    metadata is the Publisher's and the claim gate's, and this check does not touch it. An
    episode whose words cannot be read is refused, never passed: the second test could not
    run.
    """
    script_id, storyboard_id = film_identity(session, media_asset_id)
    script = session.get(ScriptDraft, script_id) if script_id else None
    story = script.story_json if script is not None and isinstance(script.story_json, dict) else {}
    if script is None or story.get("kind") != "office_serial_episode":
        return []

    reasons: list[str] = []
    own_film = {key for key in (script_id, storyboard_id) if key}
    mine = _same_metadata_key(title, tags)
    since = (datetime.now(UTC) - METADATA_COPY_WINDOW).isoformat()

    def other_film(asset_id: str | None, other_channel: str | None) -> bool:
        if not asset_id or asset_id == media_asset_id or other_channel == channel_id:
            return False
        return not own_film & {k for k in film_identity(session, asset_id) if k}

    # Another film's metadata: what was already put on a channel (or tried), and what the
    # Publisher prepared and is waiting to go — whichever film the run reaches first.
    others: list[tuple[str, list[str], str | None]] = []
    for record in session.scalars(
        select(PublicationRecord).where(PublicationRecord.created_at >= since)
    ):
        if other_film(record.media_asset_id, record.channel_id):
            others.append((record.title, list(record.tags_json or []), record.channel_id))
    from app.agents.models import AgentMessage  # noqa: PLC0415 - agents import publishing

    for message in session.scalars(
        select(AgentMessage).where(
            AgentMessage.intent.in_(("STATUS", "ESCALATE")), AgentMessage.created_at >= since
        )
    ):
        body = message.body_json or {}
        if "title" not in body or body.get("verdict") != "READY":
            continue
        if other_film(body.get("media_asset_id"), body.get("channel_id")):
            others.append(
                (str(body["title"]), list(body.get("tags") or []), body.get("channel_id"))
            )
    for other_title, other_tags, other_channel in others:
        theirs = _same_metadata_key(other_title, other_tags)
        # The title alone is enough (adversary pass, 2026-09-24): the factual film's exact
        # title under the episode's own tags passed whenever one of its words was also in
        # the episode. Two films of one day on two channels never share a title.
        if theirs == mine or (mine[0] and theirs[0] == mine[0]):
            channel = session.get(ChannelRecord, other_channel) if other_channel else None
            where = channel.channel_name if channel is not None else "alt canal"
            what = (
                "Titlul și etichetele episodului sunt, cuvânt cu cuvânt, cele ale"
                if theirs == mine
                else "Titlul episodului este, cuvânt cu cuvânt, cel al"
            )
            reasons.append(
                f"{what} altui film pregătit sau publicat în ultimele 24 de ore pentru "
                f"{where}; un episod pleacă doar cu metadatele lui."
            )
            break

    source = _terms(_episode_words(session, script))
    if not source:
        reasons.append(
            "Episodul din spatele filmului nu poate fi citit (nu are niciun cuvânt), deci "
            "titlul nu poate fi verificat față de el; filmul nu pleacă până nu poate fi."
        )
    # The hook alone: "Inside The Nexus Ep. 3" is on every episode's title, so a word of it
    # proves nothing about this one, and a title about another film must not pass on it.
    elif not _shares_a_term(_terms(hook_of(title)), source):
        reasons.append(
            f"Titlul „{str(title)[:100]}” nu are niciun cuvânt comun cu episodul pe care îl "
            "descrie (titlul, replicile, scenele, personajele); un titlu greșit pe YouTube "
            "este public."
        )
    return reasons


def create_publication_intent(
    engine: Engine,
    channel_id: str,
    media_asset_id: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    idempotency_key: str | None,
    correlation_id: str,
    scheduled_publish_time: str | None = None,
    policy_version: int | None = None,
) -> dict:
    """Create publication record with DRAFT_INTENT, evaluate gate,
    transition to VALIDATED or BLOCKED_GATE.

    `policy_version` is the channel policy that authorised the visibility (from
    `resolve_publish_visibility`); the gate refuses an unlisted, public or scheduled
    publication without it, and the record keeps it for the audit.
    """
    if not idempotency_key:
        idempotency_key = str(uuid4())
    # What every upload carries, on the one road every upload takes: a factual film's sources
    # (audit PUB-10), then the credits its music licence requires, above the studio's block;
    # the disclosure when a caller brought none; and all of it within YouTube's limits
    # (PUB-06), so the record stored here is exactly what the adapter sends.
    with Session(engine) as session:
        channel_row = session.get(ChannelRecord, channel_id)
        description = with_sources(
            description,
            film_sources(session, media_asset_id),
            sources_heading(upload_language(channel_row)),
        )
        description = with_attributions(description, film_attributions(session, media_asset_id))
        fallback_title = film_title(session, media_asset_id)
    if footer_start(description) < 0:
        description = with_footer(description, disclosure_sentence())
    title, description, tags = youtube_safe_metadata(
        title, description, list(tags or []), fallback_title=fallback_title
    )

    # Check for existing publication with same (channel_id, idempotency_key)
    with Session(engine) as session:
        existing = session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.channel_id == channel_id,
                PublicationRecord.idempotency_key == idempotency_key,
            )
        ).first()
        if existing:
            return PublicationView.model_validate(existing).model_dump()

    # A publication row references media_asset by foreign key, so a missing asset cannot be
    # recorded at all. Reject it explicitly instead of surfacing a database integrity error.
    with Session(engine) as session:
        if session.get(MediaAsset, media_asset_id) is None:
            raise PublishingAssetNotFound(
                f"Materialul {media_asset_id} nu există în evidența studioului.",
                ["Materialul nu există în evidența studioului"],
            )
        if session.get(ChannelRecord, channel_id) is None:
            raise PublishingAssetNotFound(
                f"Canalul {channel_id} nu există.",
                ["Canalul nu există în studio"],
            )

    gate_result = evaluate_publishing_gate(
        engine,
        media_asset_id,
        channel_id,
        privacy_status=privacy_status,
        policy_version=policy_version,
        scheduled_publish_time=scheduled_publish_time,
    )
    # The metadata is checked here as well as by the Publisher: this is the one road every
    # upload takes, so a HOLD the Director lifted, or a caller that never asked her, still
    # cannot put an episode on its channel under another film's title.
    with Session(engine) as session:
        metadata_reasons = publication_metadata_refusals(
            session, media_asset_id, channel_id, title, tags
        )
    if metadata_reasons:
        gate_result = {
            **gate_result,
            "eligible": False,
            "reasons": [*gate_result["reasons"], *metadata_reasons],
            "reason_codes": [
                *gate_result["reason_codes"],
                *["EPISODE_METADATA"] * len(metadata_reasons),
            ],
        }
    pub_id = str(uuid4())
    now = utc_now()

    # The blocked intent and its event must survive the rejection: a gate refusal is an
    # auditable governance decision, not a discarded attempt. The record is therefore
    # committed first and the error raised afterwards, outside the transaction.
    with Session(engine) as session, session.begin():
        status = "VALIDATED" if gate_result["eligible"] else "BLOCKED_GATE"
        error_detail = "; ".join(gate_result["reasons"]) if not gate_result["eligible"] else None

        event_type = (
            "publishing.intent_created" if gate_result["eligible"] else "publishing.gate_failed"
        )
        event = append_event(
            session,
            event_type,
            "publication_record",
            pub_id,
            1,
            {
                "channel_id": channel_id,
                "media_asset_id": media_asset_id,
                "status": status,
                "title": title,
                "privacy_status": privacy_status,
                "publish_at": scheduled_publish_time,
                "policy_version": policy_version,
                "gate_reasons": gate_result["reasons"],
                "gate_reason_codes": gate_result["reason_codes"],
            },
            correlation_id,
        )

        pub = PublicationRecord(
            id=pub_id,
            channel_id=channel_id,
            media_asset_id=media_asset_id,
            title=title,
            description=description,
            tags_json=tags,
            privacy_status=privacy_status,
            status=status,
            idempotency_key=idempotency_key,
            remote_video_id=None,
            remote_url=None,
            scheduled_publish_time=scheduled_publish_time,
            policy_version=policy_version,
            published_at=None,
            error_detail=error_detail,
            created_at=now,
            event_id=event.event_id,
        )
        session.add(pub)
        session.flush()
        view = PublicationView.model_validate(pub).model_dump()

    if not gate_result["eligible"]:
        raise PublishingGateError(
            f"Poarta de publicare a refuzat filmul: {view['error_detail']}.",
            gate_result["reasons"],
        )

    return view


#: The states an upload may be started from: a fresh intent, and a retry the studio decided is
#: safe (the platform is asked first whether the earlier attempt landed).
RUNNABLE_STATES = ("VALIDATED", "FAILED_RETRYABLE")

#: YouTube's own word for a video it will not show (`status.uploadStatus`). Such a video is
#: not a publication; the same file would be refused again, and a deleted one was deleted by
#: a person, so none of them is offered to the channel again.
REMOTE_REJECTED_STATES = frozenset({"rejected", "failed", "deleted"})
#: YouTube's processing is finished for the studio's purposes in these states.
REMOTE_SETTLED_STATES = frozenset({"processed", *REMOTE_REJECTED_STATES})

#: YouTube's reasons, in the Owner's words (`status.rejectionReason` / `failureReason`).
REMOTE_REASON_WORDS = {
    "claim": "o revendicare de drepturi",
    "copyright": "drepturi de autor",
    "duplicate": "un duplicat al unui videoclip existent",
    "inappropriate": "conținut nepotrivit",
    "legal": "un motiv legal",
    "length": "durata",
    "termsofuse": "încălcarea termenilor de utilizare",
    "trademark": "o marcă înregistrată",
    "uploaderaccountclosed": "contul închis",
    "uploaderaccountsuspended": "contul suspendat",
    "codec": "un codec pe care YouTube nu îl citește",
    "conversion": "conversia a eșuat",
    "emptyfile": "fișier gol",
    "invalidfile": "fișier invalid",
    "toosmall": "fișier prea mic",
    "uploadaborted": "încărcare întreruptă",
}

#: PUB-05 / SELL-07, in the words the Owner reads: Google keeps every upload of an unaudited
#: API project (created after 28 July 2020) private until the project passes the audit.
LOCKED_PRIVATE_LETTER = (
    "YouTube a păstrat filmul privat: proiectul Google Cloud nu a trecut auditul YouTube API "
    "Services; până atunci orice încărcare rămâne privată."
)
LOCKED_PRIVATE_NEXT = (
    "Cere auditul pentru proiectul Google Cloud al aplicației (pașii sunt în "
    "docs/project/YOUTUBE_CONNECTIONS.md); filmul este pe canal, privat, și poate fi făcut "
    "vizibil din YouTube Studio."
)

#: The statuses a letter is written for when a publication moves into them (PUB-12).
LETTER_STATUSES = ("FAILED_FINAL", "REMOTE_UNKNOWN", "NEEDS_RECONCILIATION")


def _requested_visibility(pub: PublicationRecord) -> str:
    """What the publication asked the audience to see: a scheduled release is public."""
    return "public" if pub.scheduled_publish_time else str(pub.privacy_status or "private")


def _bound_connection(session: Session, channel_id: str) -> Any:
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    channel = session.get(ChannelRecord, channel_id)
    identifier = bound_connection_id(channel) if channel is not None else None
    return session.get(YouTubeConnection, identifier) if identifier else None


def _channel_name(session: Session, channel_id: str) -> str:
    channel = session.get(ChannelRecord, channel_id)
    return channel.channel_name if channel is not None else "canal necunoscut"


def _in_owner_words(detail: str | None, status: str) -> str:
    """The record's reason when it is a Romanian sentence the studio wrote; an adapter's
    English stays in the record and the letter says what the state means instead."""
    text = str(detail or "").strip()
    if text and written_for_the_owner(text):
        return text.rstrip(".")
    return {
        "FAILED_FINAL": "YouTube a refuzat încărcarea, iar studioul nu o mai încearcă singur",
        "REMOTE_UNKNOWN": "încărcarea s-a întrerupt și nu se știe dacă videoclipul a ajuns pe "
        "canal",
        "NEEDS_RECONCILIATION": "studioul nu a putut afla singur dacă videoclipul există pe canal",
    }.get(status, "publicarea nu s-a încheiat")


def _next_step(status: str, *, auth_refused: bool = False, rejected: bool = False) -> str:
    if status == "FAILED_FINAL" and auth_refused:
        return (
            f"Reconectează contul YouTube în {settings_place('social')}; după aceea filmul, "
            "care a trecut controlul calității, este oferit din nou la următoarea rulare."
        )
    if status == "FAILED_FINAL" and rejected:
        return (
            "YouTube nu îl va arăta, iar studioul nu îl mai încarcă singur; motivul se vede în "
            "YouTube Studio."
        )
    if status == "FAILED_FINAL":
        return (
            "Filmul a trecut controlul calității și este oferit din nou la următoarea rulare; "
            "dacă motivul se repetă, el trebuie rezolvat întâi."
        )
    if status == "REMOTE_UNKNOWN":
        return (
            "Studioul întreabă singur canalul dacă videoclipul există și nu îl încarcă din nou "
            "până nu știe; dacă nu primește răspuns, îți scrie din nou."
        )
    return (
        "Verifică pe canal dacă videoclipul există, apoi închide publicarea din Distribuție → "
        "Publicări: «Există», cu ID-ul videoclipului, sau «Nu există», ca filmul să poată fi "
        "încărcat din nou."
    )


def tell_owner_about_publication(
    session: Session,
    pub: PublicationRecord,
    status: str,
    correlation_id: str,
    *,
    auth_refused: bool = False,
    rejected: bool = False,
) -> None:
    """One ESCALATE letter from the Publisher to the Owner about a publication that failed, is
    unknown or is now his to settle (PUB-12). The subject names the film, the channel and the
    state, so the same state again is the same open letter, never a second one."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import publishing
    from app.agents.messages import post_message  # noqa: PLC0415

    channel_name = _channel_name(session, pub.channel_id)
    title = " ".join(str(pub.title or "").split())
    said = publication_status(status)
    publisher = agent_for_role(session, "Publisher")
    post_message(
        session,
        intent="ESCALATE",
        subject=f"Publicarea «{title[:90]}» pe {channel_name}: {said}",
        body={
            "kind": "publication_failed",
            "publication_id": pub.id,
            "media_asset_id": pub.media_asset_id,
            "channel_id": pub.channel_id,
            "status": status,
            "auth_refused": auth_refused,
        },
        from_agent_id=publisher.id if publisher is not None else None,
        correlation_id=correlation_id,
        body_text=(
            f"Filmul «{title}» pentru {channel_name} este {said}: "
            f"{_in_owner_words(pub.error_detail, status)}. "
            f"{_next_step(status, auth_refused=auth_refused, rejected=rejected)}"
        ),
        to_owner=True,
    )


def _note_remote_state(
    session: Session,
    pub: PublicationRecord,
    correlation_id: str,
    *,
    privacy: str | None,
    upload: str | None,
) -> None:
    """Keep what YouTube says the video is, and tell the Owner once when YouTube kept private
    a film that was meant to be seen (PUB-05)."""
    before = pub.remote_privacy_status
    if privacy:
        pub.remote_privacy_status = str(privacy)[:20]
    if upload:
        pub.remote_upload_status = str(upload)[:30]
    pub.remote_checked_at = utc_now()
    if (
        privacy == "private"
        and before != "private"
        and _requested_visibility(pub) in ("public", "unlisted")
        and not pub.scheduled_publish_time
    ):
        tell_owner_locked_private(session, pub, privacy, correlation_id)


def tell_owner_locked_private(
    session: Session, pub: PublicationRecord, privacy: str, correlation_id: str
) -> None:
    """YouTube kept private a film the studio asked it to show (PUB-05): the record says why,
    with its event, and the Owner gets the one letter about the channel."""
    pub.error_detail = f"{LOCKED_PRIVATE_LETTER} {LOCKED_PRIVATE_NEXT}"
    append_event(
        session,
        "publishing.visibility_locked_private",
        "publication_record",
        pub.id,
        1,
        {
            "requested": pub.privacy_status,
            "remote_privacy_status": privacy,
            "remote_video_id": pub.remote_video_id,
            "channel_id": pub.channel_id,
        },
        correlation_id,
    )
    from app.agents.memory import agent_for_role  # noqa: PLC0415
    from app.agents.messages import post_message  # noqa: PLC0415

    channel_name = _channel_name(session, pub.channel_id)
    publisher = agent_for_role(session, "Publisher")
    post_message(
        session,
        intent="ESCALATE",
        subject=f"YouTube păstrează private filmele de pe {channel_name}",
        body={
            "kind": "publication_locked_private",
            "publication_id": pub.id,
            "channel_id": pub.channel_id,
            "requested": pub.privacy_status,
        },
        from_agent_id=publisher.id if publisher is not None else None,
        correlation_id=correlation_id,
        body_text=(
            f"Filmul «{pub.title}» a fost cerut {privacy_word(pub.privacy_status)}. "
            f"{LOCKED_PRIVATE_LETTER} {LOCKED_PRIVATE_NEXT}"
        ),
        to_owner=True,
    )


def _remote_reason(status_res: Any) -> str:
    code = str(
        getattr(status_res, "rejection_reason", None)
        or getattr(status_res, "failure_reason", None)
        or ""
    ).strip()
    upload = str(getattr(status_res, "upload_status", "") or "").lower()
    what = {
        "rejected": "YouTube a respins videoclipul",
        "failed": "YouTube nu a putut prelucra videoclipul",
        "deleted": "Videoclipul a fost șters de pe YouTube",
    }.get(upload, "YouTube nu arată videoclipul")
    if code:
        words = REMOTE_REASON_WORDS.get(code.replace("_", "").lower())
        return f"{what} (motiv: {code}{' — ' + words if words else ''})"
    return what


def _record_remote_rejection(
    session: Session, pub: PublicationRecord, status_res: Any, correlation_id: str
) -> None:
    pub.status = "FAILED_FINAL"
    pub.error_detail = sentence(_remote_reason(status_res))
    _note_remote_state(
        session,
        pub,
        correlation_id,
        privacy=getattr(status_res, "privacy_status", None),
        upload=getattr(status_res, "upload_status", None),
    )
    event = append_event(
        session,
        "publishing.remote_rejected",
        "publication_record",
        pub.id,
        1,
        {
            "remote_video_id": pub.remote_video_id,
            "upload_status": getattr(status_res, "upload_status", None),
            "rejection_reason": getattr(status_res, "rejection_reason", None),
            "failure_reason": getattr(status_res, "failure_reason", None),
        },
        correlation_id,
    )
    pub.event_id = event.event_id
    tell_owner_about_publication(session, pub, "FAILED_FINAL", correlation_id, rejected=True)


def _blocked_at_execution(
    engine: Engine, publication_id: str, gate: dict, correlation_id: str
) -> dict:
    """The gate said no at the last moment: the row is BLOCKED_GATE with the reasons."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise ValueError(f"Publication {publication_id} not found")
        previous = pub.status
        pub.status = "BLOCKED_GATE"
        pub.error_detail = (
            "Poarta de publicare a refuzat filmul chiar înainte de încărcare: "
            + "; ".join(gate["reasons"])
        )
        event = append_event(
            session,
            "publishing.gate_failed_at_execution",
            "publication_record",
            publication_id,
            1,
            {
                "previous_status": previous,
                "gate_reasons": gate["reasons"],
                "gate_reason_codes": gate["reason_codes"],
            },
            correlation_id,
        )
        pub.event_id = event.event_id
        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def _settle_failed_execution(
    engine: Engine, publication_id: str, exc: BaseException, correlation_id: str
) -> dict:
    """An exception after STARTED: the row is never left STARTED (PUB-01). A fault that passes
    (the network, a 5xx) is FAILED_RETRYABLE, whose retry asks the channel first; anything
    else is FAILED_FINAL, with a letter."""
    status = "FAILED_RETRYABLE" if is_transient(exc) else "FAILED_FINAL"
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise ValueError(f"Publication {publication_id} not found") from exc
        if pub.status != "STARTED":
            # Whatever wrote the outcome before the fault stands.
            return PublicationView.model_validate(pub).model_dump()
        pub.status = status
        pub.error_detail = sentence(f"Publicarea s-a oprit: {error_words(exc)}")
        event = append_event(
            session,
            "publishing.failed",
            "publication_record",
            publication_id,
            1,
            {"error_detail": pub.error_detail, **error_fields(exc), "status": status},
            correlation_id,
        )
        pub.event_id = event.event_id
        if status == "FAILED_FINAL":
            tell_owner_about_publication(session, pub, status, correlation_id)
        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def _mark_reconnect_needed(
    engine: Engine, channel_id: str, reason: str, correlation_id: str
) -> None:
    """Google refused the account: the connection is ERROR until the Owner reconnects, so the
    preflight, the page and the next run say «Reconectează» instead of trying again."""
    from app.youtube.services import mark_reconnect_needed  # noqa: PLC0415

    with Session(engine) as session:
        connection = _bound_connection(session, channel_id)
        identifier = connection.id if connection is not None else None
    if identifier:
        mark_reconnect_needed(engine, identifier, reason, correlation_id=correlation_id)


def execute_publication(
    engine: Engine,
    publisher: PublishingProvider,
    publication_id: str,
    correlation_id: str,
) -> dict:
    """Execute upload for a VALIDATED publication following 47_STATE_MACHINE_SPECIFICATIONS.md.

    The gate runs again first (PUB-04): an intent validated yesterday, or a retry the watchdog
    makes, does not go up after the Owner's STOP, after a newer failed quality report, under a
    policy he has changed since, or with a file that is not the one QC passed. A refusal is
    BLOCKED_GATE with the reasons. Once the row is STARTED, every way the upload ends is
    recorded (PUB-01): nothing leaves it STARTED.
    """
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")
        if pub.status not in RUNNABLE_STATES:
            raise ValueError(
                f"Cannot execute publication in status {pub.status!r}; must be VALIDATED"
            )
        asset_id, channel_id = pub.media_asset_id, pub.channel_id
        gate_privacy, gate_policy = pub.privacy_status, pub.policy_version
        gate_schedule = pub.scheduled_publish_time

    gate = evaluate_publishing_gate(
        engine,
        asset_id,
        channel_id,
        privacy_status=gate_privacy,
        policy_version=gate_policy,
        scheduled_publish_time=gate_schedule,
        exclude_publication_id=publication_id,
    )
    if not gate["eligible"]:
        return _blocked_at_execution(engine, publication_id, gate, correlation_id)

    with Session(engine) as session, session.begin():
        # Under the write lock: two callers (the watchdog and a press) cannot both move one
        # row to STARTED and upload twice.
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None or pub.status not in RUNNABLE_STATES:
            raise ValueError(
                f"Cannot execute publication in status {getattr(pub, 'status', None)!r}; "
                "it changed while the gate ran"
            )
        asset = session.get(MediaAsset, pub.media_asset_id)
        if not asset:
            raise ValueError("Associated MediaAsset missing")
        connection = _bound_connection(session, pub.channel_id)
        facts = {
            "file_path": Path(asset.uri_or_path),
            "title": pub.title,
            "description": pub.description,
            "tags": pub.tags_json,
            "privacy": pub.privacy_status,
            "idempotency_key": pub.idempotency_key,
            "publish_at": pub.scheduled_publish_time,
            "policy_version": pub.policy_version,
            "created_at": pub.created_at,
            "remote_channel_id": connection.remote_channel_id if connection else None,
            "is_retry": pub.status == "FAILED_RETRYABLE",
            # The channel's own category, audience and language (migration 0053), read at
            # the moment of the upload, as its visibility policy is.
            "upload": upload_settings(session.get(ChannelRecord, pub.channel_id)),
        }
        pub.status = "STARTED"
        append_event(
            session,
            "publishing.started",
            "publication_record",
            publication_id,
            1,
            {"title": pub.title, "channel_id": pub.channel_id},
            correlation_id,
        )
        session.flush()

    try:
        return _upload_and_record(engine, publisher, publication_id, correlation_id, facts)
    except Exception as exc:  # noqa: BLE001 - the row must not stay STARTED, whatever failed
        return _settle_failed_execution(engine, publication_id, exc, correlation_id)


def _upload_and_record(
    engine: Engine,
    publisher: PublishingProvider,
    publication_id: str,
    correlation_id: str,
    facts: dict[str, Any],
) -> dict:
    title = facts["title"]
    privacy = facts["privacy"]
    publish_at = facts["publish_at"]
    # Never re-upload blindly after a failure: ask the platform whether the previous attempt
    # actually landed (47_STATE_MACHINE_SPECIFICATIONS.md, duplicate protection).
    if facts["is_retry"]:
        try:
            reconciled = asyncio.run(
                ask_reconcile(
                    publisher,
                    facts["idempotency_key"],
                    title,
                    created_after=facts["created_at"],
                    channel_id=facts["remote_channel_id"],
                )
            )
        except Exception as raised:  # noqa: BLE001 - any failure to ask is no answer
            exc = (
                raised
                if isinstance(raised, RemoteStateUnavailable)
                else RemoteStateUnavailable(str(raised))
            )
            # The one thing that must not happen here is a second upload. The platform could not
            # say whether the first attempt landed, so the publication stays retryable and the
            # record says why, rather than the studio guessing and posting a duplicate.
            with Session(engine) as session, session.begin():
                pub = session.get(PublicationRecord, publication_id)
                if pub is None:
                    raise ValueError("Publication record lost during reconciliation") from None
                pub.status = "FAILED_RETRYABLE"
                pub.error_detail = (
                    "Reîncercarea s-a oprit înainte de încărcare: "
                    f"{error_words(exc)}. Un duplicat nu poate fi exclus."
                )
                event = append_event(
                    session,
                    "publishing.reconcile_unavailable",
                    "publication_record",
                    publication_id,
                    1,
                    {"detail": str(exc), "uploaded": False},
                    correlation_id,
                )
                pub.event_id = event.event_id
                session.flush()
                return PublicationView.model_validate(pub).model_dump()
        if reconciled is not None:
            with Session(engine) as session, session.begin():
                pub = session.get(PublicationRecord, publication_id)
                if pub is None:
                    raise ValueError("Publication record lost during reconciliation")
                simulated = bool(reconciled.simulated or getattr(publisher, "IS_SIMULATED", False))
                pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
                pub.remote_video_id = reconciled.remote_video_id
                pub.remote_url = reconciled.remote_url or None
                pub.published_at = utc_now()
                pub.error_detail = SIMULATED_UPLOAD if simulated else None
                event = append_event(
                    session,
                    "publishing.retry_reconciled",
                    "publication_record",
                    publication_id,
                    1,
                    {
                        "remote_video_id": reconciled.remote_video_id,
                        "detail": "Încercarea anterioară există deja pe platformă; "
                        "reîncercarea nu a mai încărcat nimic.",
                        "simulated": simulated,
                    },
                    correlation_id,
                )
                pub.event_id = event.event_id
                if not simulated:
                    _note_remote_state(
                        session,
                        pub,
                        correlation_id,
                        privacy=getattr(reconciled, "privacy_status", None),
                        upload=getattr(reconciled, "upload_status", None),
                    )
                session.flush()
                return PublicationView.model_validate(pub).model_dump()

    # Upload video via provider. A scheduled release travels as `publish_at`: the intent was
    # stored with it since Phase 6 and, until now, never sent.
    extra: dict[str, Any] = {"idempotency_key": facts["idempotency_key"]}
    # The intent already holds the studio's disclosure (`create_publication_intent`), in
    # whatever language: the adapter must not write a second one beside it.
    extra.update(facts.get("upload") or {})
    extra["disclosed"] = True
    if publish_at:
        extra["publish_at"] = publish_at
    upload_res: UploadResult = asyncio.run(
        publisher.upload_video(
            facts["file_path"],
            title=title,
            description=facts["description"],
            tags=facts["tags"],
            privacy_status=privacy,
            extra=extra,
        )
    )

    auth_refused = bool(getattr(upload_res, "auth_refused", False))
    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError("Publication record lost during upload")

        if upload_res.status == "CONFIRMED":
            # A simulated upload created nothing on any platform. It is recorded under a
            # distinct terminal state and a distinct event so that no API consumer, log
            # reader or UI can mistake it for a real publication.
            simulated = bool(upload_res.simulated or getattr(publisher, "IS_SIMULATED", False))
            pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
            pub.remote_video_id = upload_res.remote_video_id
            pub.remote_url = upload_res.remote_url or None
            pub.published_at = utc_now()
            pub.error_detail = SIMULATED_UPLOAD if simulated else None
            remote_privacy = getattr(upload_res, "privacy_status", None)
            remote_upload = getattr(upload_res, "upload_status", None)

            event = append_event(
                session,
                "publishing.video_published_simulated"
                if simulated
                else "publishing.video_published",
                "publication_record",
                publication_id,
                1,
                {
                    "remote_video_id": upload_res.remote_video_id,
                    "remote_url": upload_res.remote_url,
                    "privacy_status": privacy,
                    "remote_privacy_status": remote_privacy,
                    "remote_upload_status": remote_upload,
                    "publish_at": publish_at,
                    "policy_version": facts["policy_version"],
                    "title": title,
                    "simulated": simulated,
                    "adapter": type(publisher).__name__,
                },
                correlation_id,
            )
            pub.event_id = event.event_id
            if not simulated:
                _note_remote_state(
                    session, pub, correlation_id, privacy=remote_privacy, upload=remote_upload
                )
        elif upload_res.status == "UNKNOWN":
            pub.status = "REMOTE_UNKNOWN"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.remote_unknown",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail},
                correlation_id,
            )
            tell_owner_about_publication(session, pub, "REMOTE_UNKNOWN", correlation_id)
        elif upload_res.status == "RETRYABLE":
            # Nothing was created; the watchdog retries the row, asking the channel first.
            pub.status = "FAILED_RETRYABLE"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.failed_retryable",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail},
                correlation_id,
            )
        else:
            pub.status = "FAILED_FINAL"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.failed",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail, "auth_refused": auth_refused},
                correlation_id,
            )
            tell_owner_about_publication(
                session, pub, "FAILED_FINAL", correlation_id, auth_refused=auth_refused
            )

        session.flush()
        view = PublicationView.model_validate(pub).model_dump()
        channel_id = pub.channel_id
    if auth_refused:
        _mark_reconnect_needed(
            engine, channel_id, str(upload_res.error_detail or ""), correlation_id
        )
    return view


#: What a simulated upload is, in the record the Owner reads: nothing is on any platform.
SIMULATED_UPLOAD = "Încărcare simulată: niciun video nu există pe vreo platformă."

_REMOTE_UNREAD = "starea de pe platformă nu a putut fi citită"


def _remote_state_unread(exc: BaseException) -> str:
    """Why the platform's state is unknown, said once: the class's own words already say it,
    so a cause is added only when there is one to add (an HTTP answer, a timeout)."""
    words = error_words(exc)
    if words == _REMOTE_UNREAD:
        return sentence(f"{_REMOTE_UNREAD}; publicarea rămâne necunoscută, nu absentă")
    return sentence(f"{_REMOTE_UNREAD}: {words}; publicarea rămâne necunoscută, nu absentă")


def list_publications(engine: Engine, channel_id: str | None = None) -> list[dict]:
    with Session(engine) as session:
        query = select(PublicationRecord).order_by(PublicationRecord.created_at.desc())
        if channel_id:
            query = query.where(PublicationRecord.channel_id == channel_id)
        pubs = session.scalars(query).all()
        return [PublicationView.model_validate(p).model_dump() for p in pubs]


def get_publication(engine: Engine, publication_id: str) -> dict | None:
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            return None
        return PublicationView.model_validate(pub).model_dump()


def reconcile_publication(
    engine: Engine,
    publication_id: str,
    provider: PublishingProvider,
    correlation_id: str,
) -> dict:
    """Reconcile an uncertain publication (REMOTE_UNKNOWN / FAILED_RETRYABLE) with remote state.

    Per 47_STATE_MACHINE_SPECIFICATIONS.md: Never re-upload from REMOTE_UNKNOWN
    without checking remote state. A video YouTube holds but rejected, failed to process or
    shows as deleted is not a publication (PUB-08): FAILED_FINAL with YouTube's reason, and a
    letter.
    """
    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")
        remote_id = pub.remote_video_id
        if not remote_id:
            return PublicationView.model_validate(pub).model_dump()

    # Query remote status via provider
    try:
        status_res = asyncio.run(provider.get_video_status(remote_id))
    except RemoteStateUnavailable as exc:
        # Staying REMOTE_UNKNOWN is the honest outcome. Calling it FAILED_RETRYABLE would tell
        # the operator the video is not on the channel, which nobody has established.
        with Session(engine) as session, session.begin():
            pub = session.get(PublicationRecord, publication_id)
            if not pub:
                raise ValueError(f"Publication {publication_id} not found") from None
            pub.status = "REMOTE_UNKNOWN"
            pub.error_detail = _remote_state_unread(exc)
            event = append_event(
                session,
                "publishing.reconcile_unavailable",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": remote_id, "detail": str(exc)},
                correlation_id,
            )
            pub.event_id = event.event_id
            session.flush()
            return PublicationView.model_validate(pub).model_dump()

    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")

        upload = str(status_res.upload_status or "").lower()
        if status_res.exists and upload in REMOTE_REJECTED_STATES:
            _record_remote_rejection(session, pub, status_res, correlation_id)
        elif status_res.exists:
            simulated = bool(getattr(provider, "IS_SIMULATED", False))
            pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
            pub.published_at = utc_now()
            # Keep whatever URL the provider actually returned; never synthesise one.
            pub.error_detail = SIMULATED_UPLOAD if simulated else None
            append_event(
                session,
                "publishing.reconciled_published",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": remote_id, "status": "PUBLISHED"},
                correlation_id,
            )
            if not simulated:
                _note_remote_state(
                    session,
                    pub,
                    correlation_id,
                    privacy=status_res.privacy_status,
                    upload=status_res.upload_status,
                )
        else:
            pub.status = "FAILED_RETRYABLE"
            pub.error_detail = (
                "Filmul nu a fost găsit pe canal după așteptare; poate fi reîncercat fără "
                "risc de dublură."
            )
            append_event(
                session,
                "publishing.reconciled_not_found",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": remote_id, "status": "FAILED_RETRYABLE"},
                correlation_id,
            )

        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def reconcile_by_title(
    engine: Engine,
    publication_id: str,
    provider: PublishingProvider,
    correlation_id: str,
) -> dict:
    """An uncertain publication with no video id, asked of the channel's own uploads.

    The upload was cut before YouTube named the video (or the process died while STARTED), so
    the only question left is the one `reconcile_upload` asks: is there, on this channel, a
    video of exactly this title uploaded since the publication was written. Found, it is the
    publication; the channel answering no makes the row safely retryable; no answer leaves it
    REMOTE_UNKNOWN, and the watchdog's bound on attempts hands it to the Owner.
    """
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise ValueError(f"Publication {publication_id} not found")
        connection = _bound_connection(session, pub.channel_id)
        facts: dict[str, Any] = {
            "key": pub.idempotency_key,
            "title": pub.title,
            "created_at": pub.created_at,
            "channel": connection.remote_channel_id if connection else None,
        }
    try:
        found = asyncio.run(
            ask_reconcile(
                provider,
                facts["key"],
                facts["title"],
                created_after=facts["created_at"],
                channel_id=facts["channel"],
            )
        )
    except Exception as raised:  # noqa: BLE001 - any failure to ask is no answer
        exc = (
            raised
            if isinstance(raised, RemoteStateUnavailable)
            else RemoteStateUnavailable(str(raised))
        )
        with Session(engine) as session, session.begin():
            pub = session.get(PublicationRecord, publication_id)
            if pub is None:
                raise ValueError(f"Publication {publication_id} not found") from None
            pub.error_detail = _remote_state_unread(exc)
            event = append_event(
                session,
                "publishing.reconcile_unavailable",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": None, "detail": str(exc), "by": "title"},
                correlation_id,
            )
            pub.event_id = event.event_id
            session.flush()
            return PublicationView.model_validate(pub).model_dump()

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise ValueError(f"Publication {publication_id} not found")
        if found is not None:
            simulated = bool(found.simulated or getattr(provider, "IS_SIMULATED", False))
            pub.status = "PUBLISHED_SIMULATED" if simulated else "PUBLISHED"
            pub.remote_video_id = found.remote_video_id
            pub.remote_url = found.remote_url or None
            pub.published_at = utc_now()
            pub.error_detail = SIMULATED_UPLOAD if simulated else None
            append_event(
                session,
                "publishing.reconciled_published",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": found.remote_video_id, "status": pub.status, "by": "title"},
                correlation_id,
            )
            if not simulated:
                _note_remote_state(
                    session,
                    pub,
                    correlation_id,
                    privacy=getattr(found, "privacy_status", None),
                    upload=getattr(found, "upload_status", None),
                )
        else:
            pub.status = "FAILED_RETRYABLE"
            pub.error_detail = (
                "Filmul nu a fost găsit pe canal după așteptare; poate fi reîncercat fără "
                "risc de dublură."
            )
            append_event(
                session,
                "publishing.reconciled_not_found",
                "publication_record",
                publication_id,
                1,
                {"remote_video_id": None, "status": "FAILED_RETRYABLE", "by": "title"},
                correlation_id,
            )
        session.flush()
        return PublicationView.model_validate(pub).model_dump()


def upload_started_at(session: Session, pub: PublicationRecord) -> datetime:
    """When the upload of a publication last began: its newest `publishing.started` event,
    else the moment the publication was written."""
    from app.models import DomainEvent  # noqa: PLC0415

    stamp = session.scalar(
        select(DomainEvent.timestamp)
        .where(
            DomainEvent.aggregate_id == pub.id,
            DomainEvent.event_type == "publishing.started",
        )
        .order_by(DomainEvent.sequence.desc())
        .limit(1)
    )
    moment = datetime.fromisoformat(str(stamp or pub.created_at))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def mark_stale_started(engine: Engine, older_than_seconds: int, correlation_id: str) -> list[str]:
    """STARTED rows whose upload began longer ago than any upload takes become REMOTE_UNKNOWN,
    to be reconciled (PUB-01): a process that died mid-upload leaves nothing else to move them,
    and STARTED counts as a film on its way, so the film was blocked for good."""
    now = datetime.now(UTC)
    moved: list[str] = []
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        for pub in session.scalars(
            select(PublicationRecord).where(PublicationRecord.status == "STARTED")
        ):
            elapsed = (now - upload_started_at(session, pub)).total_seconds()
            if elapsed < older_than_seconds:
                continue
            pub.status = "REMOTE_UNKNOWN"
            pub.error_detail = (
                "Încărcarea a început și nu s-a mai terminat (procesul s-a oprit); studioul "
                "verifică pe canal dacă videoclipul există înainte de orice reîncercare."
            )
            event = append_event(
                session,
                "publishing.started_stale",
                "publication_record",
                pub.id,
                1,
                {"stuck_seconds": int(elapsed)},
                correlation_id,
            )
            pub.event_id = event.event_id
            moved.append(pub.id)
    return moved


def check_processing(
    engine: Engine, publication_id: str, provider: PublishingProvider, correlation_id: str
) -> str:
    """YouTube's processing of a published video, read once (videos.list, 1 unit): its state
    is kept; rejected, failed or deleted makes the publication FAILED_FINAL with a letter.
    Returns YouTube's upload status, or UNREADABLE / GONE."""
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        remote_id = pub.remote_video_id if pub is not None else None
    if not remote_id:
        return "UNREADABLE"
    try:
        status_res = asyncio.run(provider.get_video_status(remote_id))
    except RemoteStateUnavailable:
        return "UNREADABLE"
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None or pub.status != "PUBLISHED":
            return "UNREADABLE"
        if not status_res.exists:
            # Not there by YouTube's own answer, a video it held an hour ago: deleted.
            status_res.upload_status = "deleted"
        upload = str(status_res.upload_status or "").lower()
        if upload in REMOTE_REJECTED_STATES:
            _record_remote_rejection(session, pub, status_res, correlation_id)
            return upload
        _note_remote_state(
            session,
            pub,
            correlation_id,
            privacy=status_res.privacy_status,
            upload=status_res.upload_status,
        )
        return upload or "UNREADABLE"


def hand_to_owner(engine: Engine, publication_id: str, detail: str, correlation_id: str) -> None:
    """The manual repair queue: a row a person must look at, named as such, not asked again,
    and told to the Owner in one letter (PUB-12)."""
    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            return
        previous = pub.status
        pub.status = "NEEDS_RECONCILIATION"
        pub.error_detail = detail
        event = append_event(
            session,
            "publishing.reconcile_exhausted",
            "publication_record",
            publication_id,
            1,
            {"previous_status": previous, "detail": detail},
            correlation_id,
        )
        pub.event_id = event.event_id
        tell_owner_about_publication(session, pub, "NEEDS_RECONCILIATION", correlation_id)


#: The states the Owner settles by hand: the studio could not tell whether the video exists.
RESOLVABLE_STATES = ("NEEDS_RECONCILIATION", "REMOTE_UNKNOWN")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def resolve_publication(
    engine: Engine,
    publication_id: str,
    *,
    found: bool,
    remote_video_id: str | None,
    command_id: str,
) -> dict:
    """The Owner says whether the video is on the channel (PUB-12).

    Found, with the video's id: PUBLISHED under that id. Not found: FAILED_RETRYABLE, which
    the watchdog retries after asking the channel itself once more. Idempotent by command id
    (the same command again is the same answer; the same id with other input is refused), and
    only for a row the studio could not settle.
    """
    payload = {"found": bool(found), "remote_video_id": remote_video_id}
    payload_hash = hashlib.sha256(
        json.dumps({"publication_id": publication_id, **payload}, sort_keys=True).encode()
    ).hexdigest()
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        previous = session.get(CommandRecord, command_id)
        if previous:
            if previous.payload_hash != payload_hash:
                raise CommandConflict(COMMAND_REUSED)
            return dict(previous.response)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise LookupError(f"Publicarea {publication_id} nu există.")
        if pub.status not in RESOLVABLE_STATES:
            raise PublicationNotResolvable(
                f"Publicarea este {publication_status(pub.status)}; doar una pe care studioul "
                "nu a putut-o verifica singur se închide de mână."
            )
        if found:
            video = str(remote_video_id or "").strip()
            if not _VIDEO_ID.match(video):
                raise ValueError("ID-ul videoclipului YouTube nu are forma unui ID de videoclip.")
            pub.status = "PUBLISHED"
            pub.remote_video_id = video
            pub.remote_url = f"https://youtube.com/shorts/{video}"
            pub.published_at = utc_now()
            pub.error_detail = None
        else:
            pub.status = "FAILED_RETRYABLE"
            pub.error_detail = (
                "Proprietarul a verificat: videoclipul nu este pe canal; filmul poate fi "
                "încărcat din nou."
            )
        event = append_event(
            session,
            "publishing.resolved_by_owner",
            "publication_record",
            publication_id,
            1,
            {**payload, "status": pub.status},
            command_id,
        )
        pub.event_id = event.event_id
        session.flush()
        view = PublicationView.model_validate(pub).model_dump()
        session.add(
            CommandRecord(
                idempotency_key=command_id,
                command_type="ResolvePublication",
                payload_hash=payload_hash,
                response=view,
                created_at=utc_now(),
            )
        )
        return view


def publish_media_asset(
    engine: Engine,
    media_asset_id: str,
    channel_id: str,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str = "private",
    correlation_id: str | None = None,
    provider: PublishingProvider | None = None,
    idempotency_key: str | None = None,
    footer: str | None = None,
    policy_version: int | None = None,
    scheduled_publish_time: str | None = None,
) -> dict:
    """End-to-end publishing pipeline: intent -> gate validation -> upload -> remote URL.

    `privacy_status`, `scheduled_publish_time` and `policy_version` are what
    `resolve_publish_visibility` handed over for the channel; the daily run passes them as
    given, never a visibility of its own.
    """
    corr_id = correlation_id or str(uuid4())
    # The disclosure and the creator's channel are not the Publisher's to remember: they are
    # added here, on the one road every upload takes, whatever she wrote above them.
    description = with_footer(description, footer)

    # Refuse before creating any record: without a provider nothing can be published, and a
    # DRAFT_INTENT row would only suggest an attempt that could never happen.
    if provider is None:
        raise PublisherNotConfigured(
            "Niciun furnizor de publicare nu este configurat. Setează "
            "STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET și "
            "STUDIO_YOUTUBE_REFRESH_TOKEN; studioul nu înlocuiește publicarea cu una simulată."
        )

    intent = create_publication_intent(
        engine=engine,
        channel_id=channel_id,
        media_asset_id=media_asset_id,
        title=title,
        description=description,
        tags=tags,
        privacy_status=privacy_status,
        idempotency_key=idempotency_key,
        correlation_id=corr_id,
        scheduled_publish_time=scheduled_publish_time,
        policy_version=policy_version,
    )

    return execute_publication(engine, provider, intent["id"], corr_id)


execute_publish = execute_publication
