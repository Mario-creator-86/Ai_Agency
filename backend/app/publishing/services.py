"""Phase 6 Publishing services, Content Gate evaluation, and lifecycle state transitions."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from app.services import CommandConflict, append_event, utc_now


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
                raise CommandConflict("Command ID already used with different input")
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

        if command.autonomous_privacy == "public":
            if environment != "PRODUCTION":
                raise PublishPolicyError(
                    f"Studioul este în {environment}: publicarea autonomă nu poate fi setată "
                    "pe „public”. Treci studioul în PRODUCTION din pagina Owner, apoi "
                    "permite publicul pe canal."
                )
            if command.public_publish_enabled is not True:
                raise PublishPolicyError(
                    "„public” se acceptă doar împreună cu public_publish_enabled=true în "
                    "aceeași comandă; fără el încărcările rămân private."
                )

        changed = sorted(key for key in old if key != "policy_version" and old[key] != new[key])
        event_id = None
        if changed:
            channel.autonomous_privacy = new["autonomous_privacy"]
            channel.public_publish_enabled = new["public_publish_enabled"]
            channel.publish_delay_minutes = new["publish_delay_minutes"]
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
            "private", f"Politica canalului cere o vizibilitate necunoscută ({privacy!r}); privat."
        )
    if privacy == "private":
        return _result("private", "Politica canalului: încărcare privată.")
    if privacy == "unlisted":
        return _result("unlisted", "Politica canalului: nelistat.")
    if not enabled:
        return _result(
            "private",
            "Politica canalului cere „public”, dar public_publish_enabled este dezactivat; "
            "încărcarea rămâne privată.",
        )
    if environment != "PRODUCTION":
        return _result(
            "private",
            f"Studioul este în {environment}: nimic nu pleacă public. Încărcare privată.",
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
                f"Lansare publică programată peste {delay} de minute ({publish_at}): YouTube "
                "cere încărcare privată cu publishAt."
            ),
        }
    return _result("public", "Politica canalului: public, studioul în PRODUCTION.")


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
    the one mistake no later check can undo.
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
        channel_type = channel.channel_type if channel else channel_type_for_storyboard(board)
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
                "Publicare → Sloturi de canale.",
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

    with Session(engine) as session:
        # Gate 1: Global Autonomy Stop check
        policy = session.get(OwnerPolicy, 1)
        if policy and policy.autonomy_stopped:
            checks.append(
                {
                    "check_name": "AUTONOMY_GATE",
                    "passed": False,
                    "detail": "Global autonomy stop is active; Owner must clear it first.",
                }
            )
            reasons.append("Global autonomy stop is active")
        else:
            checks.append(
                {
                    "check_name": "AUTONOMY_GATE",
                    "passed": True,
                    "detail": "Autonomy stop is cleared.",
                }
            )

        # Gate 2: Media Asset valid on disk
        asset = session.get(MediaAsset, media_asset_id)
        if not asset:
            checks.append(
                {
                    "check_name": "MEDIA_ASSET_EXISTS",
                    "passed": False,
                    "detail": f"MediaAsset {media_asset_id} not found.",
                }
            )
            reasons.append("MediaAsset does not exist")
        else:
            p = Path(asset.uri_or_path)
            if not p.is_file() or p.stat().st_size == 0:
                checks.append(
                    {
                        "check_name": "MEDIA_ASSET_ON_DISK",
                        "passed": False,
                        "detail": f"File {asset.uri_or_path} missing or empty.",
                    }
                )
                reasons.append("Media file is missing or 0 bytes on disk")
            else:
                checks.append(
                    {
                        "check_name": "MEDIA_ASSET_ON_DISK",
                        "passed": True,
                        "detail": f"Valid file ({p.stat().st_size} bytes).",
                    }
                )

        # Gate 3: Technical & Quality Control (QC) Passed
        qc = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == media_asset_id)
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        if not qc or qc.status != "PASSED":
            checks.append(
                {
                    "check_name": "QC_GATE",
                    "passed": False,
                    "detail": f"QC Report is {qc.status if qc else 'MISSING'}; must be PASSED.",
                }
            )
            reasons.append(f"QC status is {qc.status if qc else 'MISSING'}")
        elif (qc.score or 0.0) < QC_MINIMUM_SCORE:
            checks.append(
                {
                    "check_name": "QC_GATE",
                    "passed": False,
                    "detail": f"QC score {qc.score} is below the {QC_MINIMUM_SCORE} minimum.",
                }
            )
            reasons.append(f"QC score {qc.score} below minimum {QC_MINIMUM_SCORE}")
        else:
            checks.append(
                {
                    "check_name": "QC_GATE",
                    "passed": True,
                    "detail": f"QC PASSED with score {qc.score}.",
                }
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
            missing = (
                "no render job records this asset"
                if storyboard_id is None
                else "the storyboard has no script"
            )
            checks.append(
                {
                    "check_name": "FACTUAL_INTEGRITY_GATE",
                    "passed": False,
                    "detail": (
                        f"Provenance could not be established: {missing}. The claims this video "
                        f"makes cannot be checked against anything."
                    ),
                }
            )
            reasons.append(f"Factual provenance unverifiable: {missing}")
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
                    trouble.append(f"unverified or refuted: {unverified_claims}")
                if dangling:
                    trouble.append(f"referenced but missing: {dangling}")
                checks.append(
                    {
                        "check_name": "FACTUAL_INTEGRITY_GATE",
                        "passed": False,
                        "detail": "Script contains claims " + "; ".join(trouble) + ".",
                    }
                )
                reasons.append("Claims in script are not all supported: " + "; ".join(trouble))
            elif referenced:
                checks.append(
                    {
                        "check_name": "FACTUAL_INTEGRITY_GATE",
                        "passed": True,
                        "detail": f"All {len(claims)} referenced claims are SUPPORTED.",
                    }
                )
            else:
                # A script that asserts nothing factual has nothing to verify. Said plainly,
                # rather than dressed up as a verification that happened.
                checks.append(
                    {
                        "check_name": "FACTUAL_INTEGRITY_GATE",
                        "passed": True,
                        "detail": "The script references no factual claims; none to verify.",
                    }
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
            checks.append(
                {
                    "check_name": "DUPLICATE_PROTECTION_GATE",
                    "passed": False,
                    "detail": (
                        f"Asset already published/in-flight on channel "
                        f"(remote_id: {existing_pub.remote_video_id})."
                    ),
                }
            )
            reasons.append(
                "Duplicate publishing prevented; asset already published to this channel"
            )
        elif same_film is not None:
            checks.append(
                {
                    "check_name": "DUPLICATE_PROTECTION_GATE",
                    "passed": False,
                    "detail": (
                        f"This film is already on the channel as “{same_film.title}” "
                        f"(remote_id: {same_film.remote_video_id}); this asset is another "
                        f"render of the same script."
                    ),
                }
            )
            reasons.append(
                "Duplicate publishing prevented; the same film is already on this channel "
                f"as {same_film.remote_video_id or same_film.id}"
            )
        else:
            checks.append(
                {
                    "check_name": "DUPLICATE_PROTECTION_GATE",
                    "passed": True,
                    "detail": "No duplicate publication found.",
                }
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
            environment = str(policy.environment or "TEST") if policy else "TEST"
            resolved = resolve_publish_visibility(channel, environment) if channel else None
            if resolved is None:
                authorised = "private"
            elif resolved["publish_at"]:
                authorised = resolved["release_privacy"]
            else:
                authorised = resolved["privacy_status"]
            if channel is None:
                detail = f"Channel {channel_id} not found; no policy can authorise {requested}."
                reason = f"No channel policy authorises a {requested} publication"
            elif policy_version is None:
                detail = (
                    f"A {requested} publication carries no channel policy version; only a "
                    "publish policy the Owner set may make a film visible."
                )
                reason = f"No publish policy version authorises a {requested} publication"
            elif int(policy_version) != current:
                detail = (
                    f"Policy version {policy_version} stamped on this publication is not the "
                    f"channel's current policy (version {current}); the Owner changed the "
                    "policy since the visibility was resolved."
                )
                reason = (
                    f"Publish policy changed since version {policy_version}; the channel is "
                    f"at version {current}"
                )
            elif PRIVACY_RANK.get(requested, 99) > PRIVACY_RANK.get(authorised, -1):
                detail = (
                    f"The channel policy (version {current}) resolves to {authorised} in "
                    f"{environment}, not {requested}: {resolved['reason'] if resolved else ''}"
                ).rstrip()
                reason = (
                    f"Channel policy version {current} authorises {authorised}, not {requested}"
                )
            else:
                detail = None
                reason = None
            if reason is None:
                checks.append(
                    {
                        "check_name": "POLICY_AUTHORISATION_GATE",
                        "passed": True,
                        "detail": (
                            f"Channel policy version {current} authorises a {requested} "
                            f"publication in {environment}."
                        ),
                    }
                )
            else:
                checks.append(
                    {"check_name": "POLICY_AUTHORISATION_GATE", "passed": False, "detail": detail}
                )
                reasons.append(reason)

    eligible = len(reasons) == 0
    return {
        "media_asset_id": media_asset_id,
        "channel_id": channel_id,
        "eligible": eligible,
        "checks": checks,
        "reasons": reasons,
    }


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
                f"MediaAsset {media_asset_id} does not exist",
                [f"MediaAsset {media_asset_id} not found"],
            )
        if session.get(ChannelRecord, channel_id) is None:
            raise PublishingAssetNotFound(
                f"Channel {channel_id} does not exist",
                [f"Channel {channel_id} not found"],
            )

    gate_result = evaluate_publishing_gate(
        engine,
        media_asset_id,
        channel_id,
        privacy_status=privacy_status,
        policy_version=policy_version,
        scheduled_publish_time=scheduled_publish_time,
    )
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
            f"Publishing gate rejected publication: {view['error_detail']}",
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
                    f"Retry stopped before uploading: {exc} A duplicate cannot be ruled out."
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
                pub.error_detail = (
                    "Simulated upload: no video exists on any platform." if simulated else None
                )
                event = append_event(
                    session,
                    "publishing.retry_reconciled",
                    "publication_record",
                    publication_id,
                    1,
                    {
                        "remote_video_id": reconciled.remote_video_id,
                        "detail": "Previous attempt already exists remotely; retry suppressed.",
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
            pub.error_detail = (
                "Simulated upload: no video exists on any platform." if simulated else None
            )

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
            pub.error_detail = f"Remote state could not be read: {exc}"
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
            pub.error_detail = (
                "Simulated upload: no video exists on any platform." if simulated else None
            )
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
            pub.error_detail = "Video not found on remote channel after timeout; safe to retry."
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
            "No publishing provider supplied. Configure STUDIO_YOUTUBE_CLIENT_ID, "
            "STUDIO_YOUTUBE_CLIENT_SECRET and STUDIO_YOUTUBE_REFRESH_TOKEN; the studio does "
            "not substitute a simulated publisher."
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
