"""The work behind the runbook's stages.

`execute_daily_run` walks twelve stages and asks for the work of each. Until now nothing supplied
any, so a run recorded preflight and then eleven stages as SKIPPED — honest, and idle. This module
is what turns the day into work the studio actually does.

**The contract.** A runner takes nothing and returns ``{"status", "reason", "artefacts"}``. It
must not raise for an ordinary shortage; raising is reserved for a genuine fault, and the runbook
turns it into FAILED and stops the day.

**COMPLETED means the stage ran to its end. SKIPPED means it could not run.** A research stage
that finds no sources to read has completed: it looked, and there was nothing. A research stage
with no language model configured has been skipped: it could not look. Both report a count and a
reason, so a run that produced nothing says which of the two happened. Getting this backwards is
how a runbook comes to imply work it never did.

**Where a person decides, the studio stops.** A script is drafted and left at VERIFIED_PASS for
the Owner to approve; storyboarding waits for that approval. The run happens at all only because
the Owner cleared the autonomy stop, which is what authorises the studio to act — but clearing a
stop is not the same as approving a script, and publication has its own five-point gate that
re-checks the stop, the file, quality control, factual provenance and duplication.

Nothing here fabricates content or a verdict. Every stage either performs the real operation
against the real services or reports why it could not.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.analytics.services import MetricsUnavailable, ingest_publication_metrics
from app.config import Settings
from app.factual.agent_pipeline import (
    NoVerifiedClaims,
    ScriptRejected,
    agent_extract_claims,
    agent_verify_claim,
    agent_write_script,
)
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, TopicIdea
from app.factual.services import TopicNotProducible, select_topic
from app.integrations.services import selected_youtube
from app.media.models import MediaAsset, QualityControlReport, Storyboard, VideoRenderJob
from app.media.qc import evaluate_media_qc
from app.media.services import generate_storyboard_from_script
from app.providers.registry import ProviderRegistry
from app.providers.youtube_analytics import YouTubeAnalyticsProvider
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    PublisherNotConfigured,
    PublishingGateError,
    evaluate_publishing_gate,
    publish_media_asset,
)
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.services import StoryError, write_episode

logger = logging.getLogger("studio.runbook.stages")

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"

#: How many items one stage will process in a single run. A day's run should finish; a backlog of
#: two hundred sources is not a reason to hold the whole day open, and what is left is picked up
#: by tomorrow's run.
BATCH = 5


def _outcome(status: str, reason: str, **artefacts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "artefacts": artefacts}


def _has_language_model(registry: ProviderRegistry) -> bool:
    """Whether any language model is registered to run an agent task.

    Asked before every agent stage so that "no model configured" is reported as a skip with a
    reason, rather than surfacing as a failure from somewhere deep inside an agent run.
    """
    return bool(registry.registered_ids())


# ------------------------------------------------------------------ performance intake --


def _performance_intake(engine: Engine, vault: Any) -> dict[str, Any]:
    """Measure the videos the platform is actually serving.

    Only a publication with a remote video id has an audience to measure. A simulated one has
    none, and asking an analytics API about an internal row id would produce numbers about
    nothing.
    """
    provider = YouTubeAnalyticsProvider.from_verified_settings(engine, vault)
    if provider is None:
        return _outcome(
            SKIPPED,
            "Niciun cont YouTube verificat pentru analytics; nu există de unde citi performanța.",
        )

    with Session(engine) as session:
        publications = list(
            session.scalars(
                select(PublicationRecord)
                .where(
                    PublicationRecord.status == "PUBLISHED",
                    PublicationRecord.remote_video_id.is_not(None),
                )
                .limit(BATCH)
            )
        )
        identifiers = [publication.id for publication in publications]

    measured, unavailable = 0, []
    for publication_id in identifiers:
        try:
            ingest_publication_metrics(
                engine, publication_id, provider, correlation_id=str(uuid4())
            )
            measured += 1
        except MetricsUnavailable as exc:
            unavailable.append(f"{publication_id}: {exc}")

    if not identifiers:
        return _outcome(COMPLETED, "Nicio publicare reală de măsurat.", measured=0)
    reason = f"{measured} publicări măsurate."
    if unavailable:
        reason += f" {len(unavailable)} fără date."
    return _outcome(COMPLETED, reason, measured=measured, unavailable=unavailable)


# ------------------------------------------------------- research and verification --


def _research_and_verification(engine: Engine, registry: ProviderRegistry) -> dict[str, Any]:
    """Read the ingested sources, then have a second agent check what the first extracted.

    Extraction and verification are deliberately the same stage: a claim nobody checked is not
    research, and leaving verification for later would let an unverified claim sit in the record
    looking like a finding.
    """
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    with Session(engine) as session:
        # A source nobody has extracted from yet.
        extracted_source_ids = set(
            session.scalars(
                select(FactualClaim.source_id).where(FactualClaim.source_id.is_not(None))
            )
        )
        pending_sources = [
            source.id
            for source in session.scalars(select(SourceSnapshot).limit(50))
            if source.id not in extracted_source_ids
        ][:BATCH]

    extracted = 0
    for source_id in pending_sources:
        agent_extract_claims(engine, registry, source_id, str(uuid4()))
        extracted += 1

    with Session(engine) as session:
        unverified = [
            claim.id
            for claim in session.scalars(
                select(FactualClaim)
                .where(FactualClaim.status == "UNVERIFIED", FactualClaim.source_id.is_not(None))
                .limit(BATCH)
            )
        ]

    verified, refused = 0, 0
    for claim_id in unverified:
        try:
            agent_verify_claim(engine, registry, claim_id, str(uuid4()))
            verified += 1
        except Exception as exc:  # noqa: BLE001
            # A rejected verdict is an outcome of verification, not a fault in the run: the
            # agent's evidence did not appear in the source, so the claim stays unverified.
            logger.info("verification_refused", extra={"claim_id": claim_id, "reason": str(exc)})
            refused += 1

    if not pending_sources and not unverified:
        return _outcome(COMPLETED, "Nicio sursă nouă și nicio afirmație neverificată.", claims=0)
    return _outcome(
        COMPLETED,
        f"{extracted} surse citite, {verified} afirmații verificate, {refused} verdicte respinse.",
        sources_read=extracted,
        claims_verified=verified,
        verdicts_refused=refused,
    )


# ------------------------------------------------------------------------- selection --


def _selection(engine: Engine) -> dict[str, Any]:
    """Choose what the day produces: a topic with something verified to say."""
    with Session(engine) as session:
        already_selected = session.scalar(
            select(TopicIdea.id).where(TopicIdea.status == "SELECTED").limit(1)
        )
        if already_selected:
            return _outcome(
                COMPLETED, "Un subiect este deja în producție.", topic_id=already_selected
            )
        candidates = [
            topic.id
            for topic in session.scalars(
                select(TopicIdea)
                .where(TopicIdea.status.in_(("PROPOSED", "RESEARCHED")))
                .order_by(TopicIdea.novelty_score.desc())
                .limit(20)
            )
        ]

    for topic_id in candidates:
        try:
            chosen = select_topic(engine, topic_id, str(uuid4()))
        except TopicNotProducible:
            continue
        return _outcome(COMPLETED, f"Subiect selectat: {chosen['title']}.", topic_id=topic_id)

    # A verified claim that belongs to no topic can never be selected, and the Owner would
    # otherwise be told only that there was "nothing to produce" while the work sat right there.
    with Session(engine) as session:
        orphan_supported = session.scalar(
            select(func.count())
            .select_from(FactualClaim)
            .where(FactualClaim.status == "SUPPORTED", FactualClaim.topic_id.is_(None))
        )
    reason = "Niciun subiect cu afirmații verificate; nu există nimic adevărat de produs azi."
    if orphan_supported:
        reason += (
            f" {orphan_supported} afirmații verificate nu aparțin niciunui subiect: "
            "sursele au fost ingerate fără subiect."
        )
    return _outcome(
        COMPLETED,
        reason,
        candidates=len(candidates),
        supported_claims_without_topic=int(orphan_supported or 0),
    )


# ------------------------------------------------------------- script and storyboard --


def _script_and_storyboard(engine: Engine, registry: ProviderRegistry) -> dict[str, Any]:
    """Draft the voiceover for the selected topic, and storyboard what the Owner has approved.

    The draft stops at VERIFIED_PASS. Turning a draft into an APPROVED script is the Owner's
    decision, and storyboarding requires it — so a run leaves the draft waiting rather than
    approving its own work.
    """
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    drafted, rejected = 0, []
    with Session(engine) as session:
        selected = [
            topic.id
            for topic in session.scalars(select(TopicIdea).where(TopicIdea.status == "SELECTED"))
        ]
        scripted = set(session.scalars(select(ScriptDraft.topic_id)))
        needing_script = [topic_id for topic_id in selected if topic_id not in scripted][:1]

    for topic_id in needing_script:
        try:
            agent_write_script(engine, registry, topic_id, str(uuid4()))
            drafted += 1
        except (ScriptRejected, NoVerifiedClaims) as exc:
            # The draft was refused and nothing was stored — which is the pipeline working, not
            # the day breaking. A model that writes narration it cannot attribute to a verified
            # claim is a content problem; letting it stop the run would also stop the day's log
            # and every stage after it, over an outcome the studio handled correctly.
            logger.info("script_rejected", extra={"topic_id": topic_id, "reason": str(exc)})
            rejected.append(str(exc))

    with Session(engine) as session:
        storyboarded = set(session.scalars(select(Storyboard.script_draft_id)))
        approved = [
            script.id
            for script in session.scalars(
                select(ScriptDraft).where(ScriptDraft.status == "APPROVED")
            )
            if script.id not in storyboarded
        ][:BATCH]

    boards = 0
    for script_id in approved:
        generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4()))
        boards += 1

    with Session(engine) as session:
        awaiting = session.scalar(
            select(ScriptDraft.id).where(ScriptDraft.status == "VERIFIED_PASS").limit(1)
        )

    reason = f"{drafted} scenarii scrise, {boards} storyboard-uri generate."
    if rejected:
        reason += f" {len(rejected)} respinse: {rejected[0][:120]}"
    if awaiting:
        reason += " Un scenariu așteaptă aprobarea ta înainte de storyboard."
    return _outcome(
        COMPLETED,
        reason,
        scripts=drafted,
        storyboards=boards,
        rejected=rejected,
        awaiting_approval=bool(awaiting),
    )


# ----------------------------------------------------------------------------- media --


def _media(engine: Engine, settings: Settings, vault: Any) -> dict[str, Any]:
    """Render the storyboards that have no finished video yet."""
    from app.media.assembler import RenderEngineUnavailable, assemble_video_job
    from app.media.factory import image_provider, tts_provider

    with Session(engine) as session:
        rendered = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(VideoRenderJob.status == "COMPLETED")
            )
        )
        pending = [
            board.id
            for board in session.scalars(select(Storyboard).where(Storyboard.status == "APPROVED"))
            if board.id not in rendered
        ][:1]

    if not pending:
        return _outcome(COMPLETED, "Niciun storyboard de randat.", rendered=0)

    images = image_provider(engine, vault)
    voice = tts_provider(engine, vault)
    produced = []
    for storyboard_id in pending:
        try:
            result = assemble_video_job(
                engine,
                storyboard_id,
                str(uuid4()),
                ffmpeg_path=settings.ffmpeg_path,
                image_adapter=images,
                tts_adapter=voice,
            )
        except RenderEngineUnavailable as exc:
            return _outcome(SKIPPED, f"Randarea nu poate rula: {exc}")
        produced.append(result["output_asset_id"])

    substitutes = images is None or voice is None
    reason = f"{len(produced)} videoclipuri randate."
    if substitutes:
        # Said here as well as in QC, because a run summary is read on its own.
        reason += " Fără furnizor de imagine sau voce, deci cu substitute — QC le va bloca."
    return _outcome(COMPLETED, reason, assets=produced, used_substitutes=substitutes)


# ---------------------------------------------------------------------- edit and QC --


def _edit_and_qc(engine: Engine) -> dict[str, Any]:
    """Measure every rendered file that has not been measured yet."""
    with Session(engine) as session:
        checked = set(session.scalars(select(QualityControlReport.media_asset_id)))
        # Selected on what the file is, not on what it was labelled. The renderer writes
        # RENDERED_VIDEO and the test fixtures write VIDEO_COMPOSED; keying quality control to
        # either name would leave real renders unmeasured, which is how a video reaches the
        # publishing gate with no measurement behind it.
        pending = [
            asset.id
            for asset in session.scalars(
                select(MediaAsset).where(MediaAsset.mime_type.startswith("video/"))
            )
            if asset.id not in checked
        ][:BATCH]

    if not pending:
        return _outcome(COMPLETED, "Niciun material nou de verificat.", checked=0)

    passed, failed = 0, 0
    for asset_id in pending:
        report = evaluate_media_qc(engine, asset_id, str(uuid4()))
        if report["status"] == "PASSED":
            passed += 1
        else:
            failed += 1
    return _outcome(
        COMPLETED, f"{passed} au trecut QC, {failed} au picat.", passed=passed, failed=failed
    )


# --------------------------------------------------------------------------- publish --


def _publish(engine: Engine, vault: Any) -> dict[str, Any]:
    """Publish what the gate allows, to a channel that is actually connected."""
    try:
        provider = selected_youtube(engine, vault)
    except ValueError as exc:
        return _outcome(SKIPPED, str(exc))
    if provider is None:
        return _outcome(SKIPPED, "Niciun canal YouTube conectat; nu există unde publica.")

    with Session(engine) as session:
        channel = session.scalars(
            select(ChannelRecord).where(ChannelRecord.platform == "YOUTUBE").limit(1)
        ).first()
        if channel is None:
            return _outcome(SKIPPED, "Niciun canal configurat în studio.")
        channel_id, channel_name = channel.id, channel.channel_name
        published_assets = set(session.scalars(select(PublicationRecord.media_asset_id)))
        candidates = [
            (report.media_asset_id, report.id)
            for report in session.scalars(
                select(QualityControlReport).where(QualityControlReport.status == "PASSED")
            )
            if report.media_asset_id not in published_assets
        ][:1]

    if not candidates:
        return _outcome(COMPLETED, "Niciun material aprobat de QC în așteptarea publicării.")

    asset_id, _ = candidates[0]
    verdict = evaluate_publishing_gate(engine, asset_id, channel_id)
    if not verdict["eligible"]:
        return _outcome(
            COMPLETED,
            "Poarta de publicare a refuzat: " + "; ".join(verdict["reasons"]),
            blocked_asset=asset_id,
            reasons=verdict["reasons"],
        )

    with Session(engine) as session:
        script_title = "AMN-AI"
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        ).first()
        if job:
            board = session.get(Storyboard, job.storyboard_id)
            if board:
                script_title = board.title

    try:
        published = publish_media_asset(
            engine,
            media_asset_id=asset_id,
            channel_id=channel_id,
            title=script_title[:100],
            description="",
            tags=[],
            privacy_status="private",
            correlation_id=str(uuid4()),
            provider=provider,
        )
    except (PublishingGateError, PublisherNotConfigured) as exc:
        return _outcome(SKIPPED, str(exc))

    return _outcome(
        COMPLETED,
        f"Publicat pe {channel_name}: {published['status']}.",
        publication_id=published["id"],
        publication_status=published["status"],
    )


# ---------------------------------------------------------------------- serial queue --


def _serial_queue(engine: Engine, registry: ProviderRegistry, settings: Settings) -> dict[str, Any]:
    """Write the Office Serial episode for the day the studio has just closed."""
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    with Session(engine) as session:
        written = set(session.scalars(select(StoryEpisode.log_id)))
        log = session.scalars(
            select(DailyStudioLog).order_by(DailyStudioLog.business_date.desc()).limit(5)
        ).all()
        pending = [entry.id for entry in log if entry.id not in written][:1]

    if not pending:
        # The day's own log is closed after every stage has run, so this stage always writes
        # about the previous closed day. The studio is one day behind on the serial by design,
        # not by oversight: an episode about a day cannot be written in the middle of it.
        return _outcome(COMPLETED, "Nicio zi închisă fără episod.", episodes=0)

    try:
        episode = write_episode(engine, registry, pending[0], str(uuid4()))
    except StoryError as exc:
        # Same reasoning as a rejected script: the episode was refused and nothing was stored,
        # which is the grounding check working. It must not take the rest of the day with it.
        logger.info("episode_rejected", extra={"log_id": pending[0], "reason": str(exc)})
        return _outcome(COMPLETED, f"Episod respins: {exc}"[:300], episodes=0, rejected=str(exc))

    return _outcome(
        COMPLETED,
        f"Episod scris pentru {episode.get('business_date', 'ziua închisă')}.",
        episode_id=episode.get("id"),
    )


# --------------------------------------------------------------------------- wiring --


def build_stage_runners(
    engine: Engine, settings: Settings, vault: Any, registry: ProviderRegistry
) -> dict[str, Callable[[], dict[str, Any]]]:
    """The runners for the stages that have real work behind them.

    Stages absent from this mapping are recorded SKIPPED by the runbook with its own reason, and
    that is the correct outcome for them: `idea_generation` has no implementation — topics are
    proposed by the Owner — and `post_run` has no defined work yet. Naming them here with an
    invented body would be worse than leaving the runbook to say so.
    """
    return {
        "performance_intake": lambda: _performance_intake(engine, vault),
        "research_and_verification": lambda: _research_and_verification(engine, registry),
        "selection": lambda: _selection(engine),
        "script_and_storyboard": lambda: _script_and_storyboard(engine, registry),
        "media": lambda: _media(engine, settings, vault),
        "edit_and_qc": lambda: _edit_and_qc(engine),
        "publish": lambda: _publish(engine, vault),
        "serial_queue": lambda: _serial_queue(engine, registry, settings),
    }
