"""Uploads held private for their licence alone, made public once it is confirmed (2026-10-10).

Film babcf272 passed quality control and the studio uploaded it to «Main Channel A - Factual
Shorts» private (YouTube IxQIzIulLBU), although the Owner's policy for the channel is public:
every narration came from ElevenLabs and the connection had no commercial-use evidence, so the
film's licence was NEEDS_REVIEW, which the publishing gate's rights check (Gate 7) lets go up
private and nothing more (`runbook.stages._publish_one`). The Owner upgrades his plan and the
studio records the licence itself (`integrations.plan_licence`); nothing made the film public
afterwards. The watchdog does it now (`workflows.passes.licence_release`):

- Which uploads. One `_publish_one` made private for its licence carries `HELD_EVENT`. One made
  before that marker existed is known by what its walk or its day said about it: the reason of
  the film's `runbook.film_continued` that uploaded it («încărcat privat: licența filmului nu
  este confirmată»), or the publish stage's ``private_until_licensed`` on that publication in
  `DailyRun.stages_json`. An upload private because the channel's policy or the Owner wanted it
  so carries none of the three and is never touched.
- The licence, read again. Quality control froze NEEDS_REVIEW on the asset and in its report
  (``rights_qc``), and Gate 7 reads the asset's status, so asking the gate again would refuse
  for ever. The render's ledger (``production_json["licences"]``) names each component and the
  connection its evidence was read from; each one without evidence is read again (its take, or
  the Owner's statement on the connection, `media.factory.vendor_licence`). When every one now
  carries it the film is LICENSED (`media.assembler.film_licences`), written on the asset and
  the ledger with `LICENCE_CONFIRMED_EVENT`. Gate 7 is unchanged: a film is seen only LICENSED.
- Under the channel's policy as it is now. The Owner's mode lets the studio publish
  (`may_act`: no stop, no safe mode, AUTONOMOUS_CEO), the channel's policy resolves to a public
  release (public permitted on the channel, the studio in PRODUCTION), and the publishing gate
  passes the film public under the channel's current policy version, its checks of the file on
  disk aside (a visibility change uploads nothing; the bytes were checked when they went up).
  A delay the policy sets is a premiere for a new upload; a held film has waited longer.
- The change: videos.update on the status part (`YouTubeProvider.update_visibility`). The record
  says public and which policy version authorised it, `RELEASED_EVENT` is written once, and the
  Owner gets a short note. A call YouTube did not answer is `RELEASE_FAILED_EVENT` and is asked
  again on a later pass, 15 minutes later, then twice as long each time up to a day. YouTube
  saying the video is not there settles it as deleted (as `check_processing` does); YouTube
  keeping it private (an unaudited Google Cloud project) is recorded as its answer, with the
  letter the upload path writes for that case.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import lock_for_write
from app.media.models import MediaAsset, SceneTake, VideoRenderJob
from app.models import DomainEvent, OwnerPolicy
from app.providers.publishing_base import RemoteStateUnavailable
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    _channel_name,
    _record_remote_rejection,
    evaluate_publishing_gate,
    film_identity,
    resolve_publish_visibility,
    tell_owner_locked_private,
)
from app.services import append_event, may_act, utc_now
from app.wording import count, error_fields, error_words

#: Written on a publication `_publish_one` uploaded private only because its licence was not
#: confirmed.
HELD_EVENT = "publishing.held_private_for_licence"
#: The upload made public once its licence was confirmed; written once per publication.
RELEASED_EVENT = "publishing.privacy_released"
#: A visibility change YouTube did not answer; counted for the back-off.
RELEASE_FAILED_EVENT = "publishing.privacy_release_failed"
#: A NEEDS_REVIEW film whose every component now carries commercial-use evidence.
LICENCE_CONFIRMED_EVENT = "media.licence_confirmed"
#: The words `runbook.stages._private_until_licensed` puts in the stage's reason, and the walk
#: that uploaded the film (`runbook.stages.continue_film`) records.
HELD_WORDS = "încărcat privat: licența filmului nu este confirmată"
FILM_CONTINUED_EVENT = "runbook.film_continued"
#: The day the hold first existed (commit 7f30429): no upload before it was held for its licence.
HELD_SINCE = "2026-10-10"
#: The wait after a failed call, doubled per failure up to `MAX_WAIT_MINUTES`.
RETRY_MINUTES = 15
MAX_WAIT_MINUTES = 24 * 60
#: Held uploads looked at per pass.
PER_PASS = 20
#: The gate's refusals about the file on disk, which a visibility change does not upload.
FILE_CHECKS = frozenset({"MEDIA_FILE_MISSING", "MEDIA_HASH_MISMATCH"})
PUBLIC_PUBLISH = "publishing.public_publish"

#: A channel id to the account that may change its videos (None: none).
PublisherResolver = Callable[[str], Any]


def _events(session: Session, publication_id: str, event_type: str) -> list[DomainEvent]:
    return list(
        session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_id == publication_id,
                DomainEvent.event_type == event_type,
            )
            .order_by(DomainEvent.sequence)
        )
    )


def mark_held_for_licence(
    session: Session, publication_id: str, reason: str, missing_ro: list[str]
) -> None:
    """Write on a publication that it went up private only because the film's licence was not
    confirmed (`_publish_one`, in the transaction that records the upload); once."""
    pub = session.get(PublicationRecord, publication_id)
    if pub is None or _events(session, publication_id, HELD_EVENT):
        return
    append_event(
        session,
        HELD_EVENT,
        "publication_record",
        publication_id,
        1,
        {
            "media_asset_id": pub.media_asset_id,
            "channel_id": pub.channel_id,
            "policy_version": pub.policy_version,
            "reason": reason,
            "missing_ro": [str(item) for item in missing_ro],
        },
        str(uuid4()),
    )


def held_for_licence(session: Session, pub: PublicationRecord) -> str | None:
    """How the studio knows this upload is private for its licence alone: "marked" (its
    event), "walk" (the film's continuation that uploaded it said so), "day" (the day's publish
    stage said so); None leaves the upload alone."""
    if _events(session, pub.id, HELD_EVENT):
        return "marked"
    if str(pub.created_at) < HELD_SINCE:
        return None
    _script_id, storyboard_id = film_identity(session, pub.media_asset_id)
    if storyboard_id is not None:
        # The walk writes its event right after the upload, so the first one since the
        # publication was written is the walk that made it.
        walk = session.scalar(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == FILM_CONTINUED_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
                DomainEvent.timestamp >= str(pub.created_at),
            )
            .order_by(DomainEvent.sequence)
            .limit(1)
        )
        if walk is not None and HELD_WORDS in str((walk.payload or {}).get("reason") or ""):
            return "walk"
    from app.runbook.models import DailyRun  # noqa: PLC0415 - the runbook imports publishing

    for run in session.scalars(select(DailyRun).where(DailyRun.started_at >= HELD_SINCE)):
        for stage in run.stages_json or []:
            if not isinstance(stage, dict) or stage.get("stage") != "publish":
                continue
            artefacts = stage.get("artefacts")
            published = artefacts.get("published") if isinstance(artefacts, dict) else None
            for item in published or []:
                if (
                    isinstance(item, dict)
                    and item.get("publication_id") == pub.id
                    and item.get("private_until_licensed")
                ):
                    return "day"
    return None


def licence_held_uploads(engine: Engine) -> list[tuple[str, str]]:
    """(publication id, how it is known) for each upload on its channel, private, that went up
    so only for its licence and has not been released; oldest first, `PER_PASS` at most."""
    held: list[tuple[str, str]] = []
    with Session(engine) as session:
        for pub in session.scalars(
            select(PublicationRecord)
            .where(
                PublicationRecord.status == "PUBLISHED",
                PublicationRecord.privacy_status == "private",
                PublicationRecord.scheduled_publish_time.is_(None),
                PublicationRecord.remote_video_id.is_not(None),
            )
            .order_by(PublicationRecord.created_at)
        ):
            known = held_for_licence(session, pub)
            if known is not None and not _events(session, pub.id, RELEASED_EVENT):
                held.append((pub.id, known))
            if len(held) >= PER_PASS:
                break
    return held


def confirm_licence(engine: Engine, asset_id: str, correlation_id: str) -> dict[str, Any]:
    """The film's rights verdict (`media.qc.rights_verdict`) with its licence read again.

    A NEEDS_REVIEW film whose every component now carries commercial-use evidence is written
    LICENSED, on the asset and on its render's ledger, with `LICENCE_CONFIRMED_EVENT`; any
    other status is read as it stands. ``missing_ro`` says what still lacks evidence."""
    from app.media.assembler import LICENSED, film_licences  # noqa: PLC0415 - heavy, on demand
    from app.media.factory import vendor_licence  # noqa: PLC0415
    from app.media.qc import PRIVATE_ONLY_LICENCE_STATUSES, rights_verdict  # noqa: PLC0415

    with Session(engine) as session:
        asset = session.get(MediaAsset, asset_id)
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id).limit(1)
        )
        production = job.production_json if job is not None else None
        production = dict(production) if isinstance(production, dict) else {}
        status = asset.license_status if asset is not None else None
        verdict = rights_verdict(status, production)
        if asset is None or job is None or str(status) not in PRIVATE_ONLY_LICENCE_STATUSES:
            return verdict
        job_id = job.id
        ledger = production.get("licences")
        ledger = dict(ledger) if isinstance(ledger, dict) else {}
        components = [
            dict(item) for item in ledger.get("components") or [] if isinstance(item, dict)
        ]
        for component in components:
            if component.get("commercial_use") is True:
                continue
            take_id = component.get("take_id")
            take = session.get(SceneTake, str(take_id)) if take_id else None
            if take is not None and take.commercial_use is True:
                component.update(
                    vendor=take.licence_vendor,
                    terms=take.licence_terms,
                    commercial_use=True,
                    source="take",
                )
            elif component.get("source") == "connection" and component.get("integration_id"):
                component.update(vendor_licence(session, component["integration_id"]))
        judged = film_licences(components)
    if judged["status"] != LICENSED:
        return {**verdict, "missing_ro": list(judged["missing_ro"])}

    with Session(engine) as session, session.begin():
        lock_for_write(session)
        asset = session.get(MediaAsset, asset_id)
        job = session.get(VideoRenderJob, job_id)
        if asset is None or job is None:
            return verdict
        if str(asset.license_status) in PRIVATE_ONLY_LICENCE_STATUSES:
            before = asset.license_status
            asset.license_status = LICENSED
            job.production_json = {
                **dict(job.production_json or {}),
                "licences": {**ledger, **judged, "confirmed_at": utc_now()},
            }
            append_event(
                session,
                LICENCE_CONFIRMED_EVENT,
                "media_asset",
                asset_id,
                1,
                {
                    "previous_status": before,
                    "license_status": LICENSED,
                    "render_job_id": job_id,
                    "was_missing_ro": list(ledger.get("missing_ro") or []),
                },
                correlation_id,
            )
        return rights_verdict(asset.license_status, job.production_json or {})


def _moment(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def release_licence_held_uploads(
    engine: Engine,
    publisher_for: PublisherResolver,
    correlation_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Make public each upload held private for its licence alone, once the licence is
    confirmed and the channel's policy releases it. Returns what was released, what YouTube
    kept private, what failed (asked again later) and what waits, with why."""
    result: dict[str, Any] = {"released": [], "kept_private": [], "failed": [], "waiting": []}
    held = licence_held_uploads(engine)
    if not held:
        return result
    # The Owner's stop, safe mode and mode, read once and without asking him: under
    # SUPERVISED or MANUAL a film is made public by him, never by this pass.
    with Session(engine) as session:
        verdict = may_act(session, PUBLIC_PUBLISH, "T3", requester="publisher", ask_owner=False)
    if not verdict["allowed"]:
        result["waiting"] = [
            {"publication_id": publication_id, "why": "mode", "reason": verdict["reason"]}
            for publication_id, _known in held
        ]
        return result
    moment = now or datetime.now(UTC)
    for publication_id, known in held:
        outcome, reason = _release_one(
            engine, publisher_for, publication_id, known, correlation_id, moment
        )
        if outcome in ("released", "kept_private", "failed"):
            result[outcome].append(publication_id)
        else:
            result["waiting"].append(
                {"publication_id": publication_id, "why": outcome, "reason": reason[:300]}
            )
    return result


def _release_one(
    engine: Engine,
    publisher_for: PublisherResolver,
    publication_id: str,
    known: str,
    correlation_id: str,
    moment: datetime,
) -> tuple[str, str]:
    """One held upload: (outcome, reason). The outcome is "released", "kept_private" or
    "failed", or why it waits: "policy", "backoff", "licence", "gate", "no_publisher",
    "changed" (or "gone": YouTube no longer has it)."""
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            return "changed", "publicarea nu mai există"
        channel = session.get(ChannelRecord, pub.channel_id)
        policy = session.get(OwnerPolicy, 1)
        environment = str(policy.environment or "TEST") if policy else "TEST"
        resolved = resolve_publish_visibility(channel, environment)
        failures = [
            str(event.timestamp) for event in _events(session, pub.id, RELEASE_FAILED_EVENT)
        ]
        asset_id, channel_id, video = pub.media_asset_id, pub.channel_id, str(pub.remote_video_id)
        made_for_kids = bool(channel.made_for_kids) if channel is not None else False
    if channel is None or resolved["release_privacy"] != "public":
        return "policy", str(resolved["reason"])
    version = int(resolved["policy_version"])
    if failures:
        wait = min(RETRY_MINUTES * 2 ** min(len(failures) - 1, 10), MAX_WAIT_MINUTES)
        if moment - _moment(failures[-1]) < timedelta(minutes=wait):
            return "backoff", f"YouTube este întrebat din nou după {count(wait, 'minut', 'minute')}"

    rights = confirm_licence(engine, asset_id, correlation_id)
    if not rights["public_allowed"]:
        return "licence", "; ".join(rights.get("missing_ro") or []) or str(rights["detail"])
    gate = evaluate_publishing_gate(
        engine,
        asset_id,
        channel_id,
        privacy_status="public",
        policy_version=version,
        exclude_publication_id=publication_id,
    )
    refused = [
        reason
        for code, reason in zip(gate["reason_codes"], gate["reasons"], strict=True)
        if code not in FILE_CHECKS
    ]
    if refused:
        return "gate", "; ".join(refused)

    try:
        provider = publisher_for(channel_id)
    except Exception as exc:  # noqa: BLE001 - an account that cannot be opened is no account
        return "no_publisher", error_words(exc)
    change = getattr(provider, "update_visibility", None) if provider is not None else None
    if change is None:
        return "no_publisher", "niciun cont YouTube legat de canal nu poate schimba vizibilitatea"
    try:
        answer = asyncio.run(change(video, "public", made_for_kids=made_for_kids))
        if answer.exists and not answer.privacy_status:
            raise RemoteStateUnavailable(
                "YouTube a răspuns fără să spună vizibilitatea videoclipului"
            )
    except AssertionError:
        raise  # the test suite's network guard: a test must fake YouTube, never reach it
    except Exception as exc:  # noqa: BLE001 - not answered: asked again on a later pass
        with Session(engine) as session, session.begin():
            append_event(
                session,
                RELEASE_FAILED_EVENT,
                "publication_record",
                publication_id,
                1,
                {
                    "attempt": len(failures) + 1,
                    "remote_video_id": video,
                    "detail": error_words(exc),
                    **error_fields(exc),
                },
                correlation_id,
            )
        return "failed", error_words(exc)
    return _record_release(engine, publication_id, answer, version, known, correlation_id)


def _record_release(
    engine: Engine,
    publication_id: str,
    answer: Any,
    version: int,
    known: str,
    correlation_id: str,
) -> tuple[str, str]:
    """YouTube's answer to the change, kept on the record, with the event and the Owner's note."""
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        pub = session.get(PublicationRecord, publication_id)
        if pub is None or pub.status != "PUBLISHED" or pub.privacy_status != "private":
            return "changed", "publicarea s-a schimbat între timp"
        if not answer.exists:
            # Not there by YouTube's own answer: deleted, as the processing check reads it.
            answer.upload_status = "deleted"
            _record_remote_rejection(session, pub, answer, correlation_id)
            return "gone", "YouTube nu mai are videoclipul"
        said = str(answer.privacy_status)
        pub.privacy_status = "public"
        pub.policy_version = version
        pub.remote_privacy_status = said[:20]
        if answer.upload_status:
            pub.remote_upload_status = str(answer.upload_status)[:30]
        pub.remote_checked_at = utc_now()
        event = append_event(
            session,
            RELEASED_EVENT,
            "publication_record",
            publication_id,
            1,
            {
                "remote_video_id": pub.remote_video_id,
                "previous_privacy": "private",
                "privacy_status": "public",
                "remote_privacy_status": said,
                "policy_version": version,
                "held_known_by": known,
            },
            correlation_id,
        )
        pub.event_id = event.event_id
        if said != "public":
            tell_owner_locked_private(session, pub, said, correlation_id)
            return "kept_private", f"YouTube a păstrat videoclipul {said}"
        _tell_owner_released(session, pub, version, correlation_id)
        return "released", ""


def _tell_owner_released(
    session: Session, pub: PublicationRecord, version: int, correlation_id: str
) -> None:
    """A short note to the Owner: the film is public now, and why it was not before."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import publishing
    from app.agents.messages import post_message  # noqa: PLC0415

    channel_name = _channel_name(session, pub.channel_id)
    title = " ".join(str(pub.title or "").split())
    address = pub.remote_url or f"https://youtube.com/shorts/{pub.remote_video_id}"
    publisher = agent_for_role(session, "Publisher")
    post_message(
        session,
        intent="STATUS",
        subject=f"Filmul «{title[:90]}» este acum public pe {channel_name}",
        body={
            "kind": "publication_released",
            "publication_id": pub.id,
            "media_asset_id": pub.media_asset_id,
            "channel_id": pub.channel_id,
            "remote_video_id": pub.remote_video_id,
            "policy_version": version,
        },
        from_agent_id=publisher.id if publisher is not None else None,
        correlation_id=correlation_id,
        body_text=(
            f"Licența filmului «{title}» este confirmată acum pentru fiecare componentă; filmul "
            f"fusese încărcat privat doar din cauza ei. Studioul l-a făcut public pe "
            f"{channel_name}, după politica canalului (versiunea {version}): {address}."
        ),
        to_owner=True,
    )
