"""Phase 6 Publishing services, Content Gate evaluation, and lifecycle state transitions."""

from __future__ import annotations

import asyncio
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
    error_words,
    qc_status,
    sentence,
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

ROUTE_SELECTED = "SELECTED"
ROUTE_SKIPPED = "SKIPPED"


# Channel slots the studio plans to use. A slot is NOT a configured channel: it carries no
# remote channel ID and no credentials until the Owner supplies real ones. Inventing a
# remote_channel_id or a CONFIGURED status here would fabricate external state.
DEFAULT_CHANNELS = [
    {
        "channel_name": "Main Channel A - Factual Shorts",
        "channel_type": "MAIN_FACTUAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "Real World. Verified Facts. 60-Second Deep Dives.",
        # Seed default only: production may pick technology per video. Editable in the API.
        "production_policy": "FLEXIBLE",
    },
    {
        "channel_name": "Channel B - Office Serial",
        "channel_type": "OFFICE_SERIAL",
        "platform": "YOUTUBE",
        "upload_privacy_default": "private",
        "brand_tagline": "AMN-AI (Autonomous Machine Nexus): Unscripted Silicon Life.",
        # Seed default only: recurring characters keep their locked identity. Editable in the API.
        "production_policy": "CONSISTENCY_LOCKED",
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


def published_films(session: Session, channel_id: str) -> dict[str, PublicationRecord]:
    """Every film this channel already carries, keyed by the identity above.

    Keyed by both the script and the storyboard, so a candidate matches whichever of the two
    it can establish. Only live publications count: a failed upload left nothing on the
    channel and must not block the retry.
    """
    carried: dict[str, PublicationRecord] = {}
    for record in session.scalars(
        select(PublicationRecord).where(
            PublicationRecord.channel_id == channel_id,
            PublicationRecord.status.in_(LIVE_PUBLICATION_STATES),
        )
    ):
        script_id, storyboard_id = film_identity(session, record.media_asset_id)
        for key in (script_id, storyboard_id):
            if key is not None:
                carried.setdefault(key, record)
    return carried


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


#: What the audience reads under every film, in the Owner's words. English, because what the
#: studio publishes is English.
AI_DISCLOSURE = (
    "Disclosure: this video was produced with generative AI by the AMN-AI studio pipeline."
)
#: The line that marks where the studio's own block begins, so it is written once however many
#: times a description passes through here.
FOOTER_MARKER = "Disclosure: this video was produced with generative AI"
YOUTUBE_DESCRIPTION_LIMIT = 5000


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
    engine: Engine, disclosure_url: str | None, creator_channel_title: str | None
) -> str:
    """The disclosure, the studio's site when one is configured, and the creator's channel.

    The creator is named by the title of a connected YouTube channel and linked from that
    connection, so the address is the one the studio actually holds — not one typed here.
    A title that matches no connection is still credited, without a link, rather than dropped.
    """
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    url = (disclosure_url or "").strip()
    lines = [f"{AI_DISCLOSURE} {url}" if url else AI_DISCLOSURE]
    title = (creator_channel_title or "").strip()
    if title:
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
    """The description with the studio's block at the end, once, inside YouTube's limit."""
    if not footer:
        return description
    body = description or ""
    cut = body.find(FOOTER_MARKER)
    if cut >= 0:
        body = body[:cut]
    body = body.rstrip()
    room = YOUTUBE_DESCRIPTION_LIMIT - len(footer) - 2
    body = body[: max(0, room)].rstrip()
    return f"{body}\n\n{footer}" if body else footer


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


def evaluate_publishing_gate(
    engine: Engine,
    media_asset_id: str,
    channel_id: str,
    *,
    privacy_status: str = "private",
    policy_version: int | None = None,
    scheduled_publish_time: str | None = None,
) -> dict:
    """Evaluate the 5 mandatory publishing gates per 50_CONTENT_GATE_MATRIX.md.

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
                check(
                    "MEDIA_ASSET_ON_DISK",
                    True,
                    f"Fișierul este pe disc ({count(size, 'octet', 'octeți')}).",
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
        existing_pub = session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.channel_id == channel_id,
                PublicationRecord.media_asset_id == media_asset_id,
                PublicationRecord.status.in_(LIVE_PUBLICATION_STATES),
            )
        ).first()
        same_film = None
        if existing_pub is None:
            script_id, storyboard_id = film_identity(session, media_asset_id)
            carried = published_films(session, channel_id)
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


def execute_publication(
    engine: Engine,
    publisher: PublishingProvider,
    publication_id: str,
    correlation_id: str,
) -> dict:
    """Execute upload for a VALIDATED publication following 47_STATE_MACHINE_SPECIFICATIONS.md."""
    with Session(engine) as session, session.begin():
        pub = session.get(PublicationRecord, publication_id)
        if not pub:
            raise ValueError(f"Publication {publication_id} not found")
        if pub.status not in ("VALIDATED", "FAILED_RETRYABLE"):
            raise ValueError(
                f"Cannot execute publication in status {pub.status!r}; must be VALIDATED"
            )

        asset = session.get(MediaAsset, pub.media_asset_id)
        if not asset:
            raise ValueError("Associated MediaAsset missing")

        file_path = Path(asset.uri_or_path)
        title = pub.title
        description = pub.description
        tags = pub.tags_json
        privacy = pub.privacy_status
        idempotency_key = pub.idempotency_key
        publish_at = pub.scheduled_publish_time
        policy_version = pub.policy_version

        is_retry = pub.status == "FAILED_RETRYABLE"

        # Transition to STARTED
        pub.status = "STARTED"
        append_event(
            session,
            "publishing.started",
            "publication_record",
            publication_id,
            1,
            {"title": title, "channel_id": pub.channel_id},
            correlation_id,
        )
        session.flush()

    # Never re-upload blindly after a failure: ask the platform whether the previous attempt
    # actually landed (47_STATE_MACHINE_SPECIFICATIONS.md, duplicate protection).
    if is_retry:
        try:
            reconciled = asyncio.run(publisher.reconcile_upload(idempotency_key, title))
        except RemoteStateUnavailable as exc:
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
                session.flush()
                return PublicationView.model_validate(pub).model_dump()

    # Upload video via provider. A scheduled release travels as `publish_at`: the intent was
    # stored with it since Phase 6 and, until now, never sent.
    extra: dict[str, Any] = {"idempotency_key": idempotency_key}
    if publish_at:
        extra["publish_at"] = publish_at
    upload_res: UploadResult = asyncio.run(
        publisher.upload_video(
            file_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy,
            extra=extra,
        )
    )

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
                    "publish_at": publish_at,
                    "policy_version": policy_version,
                    "title": title,
                    "simulated": simulated,
                    "adapter": type(publisher).__name__,
                },
                correlation_id,
            )
            pub.event_id = event.event_id
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
        else:
            pub.status = "FAILED_FINAL"
            pub.error_detail = upload_res.error_detail
            append_event(
                session,
                "publishing.failed",
                "publication_record",
                publication_id,
                1,
                {"error_detail": upload_res.error_detail},
                correlation_id,
            )

        session.flush()
        return PublicationView.model_validate(pub).model_dump()


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
    without checking remote state.
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

        if status_res.exists:
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
