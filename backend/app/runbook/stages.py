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

from app.agents.director import (
    DirectorError,
    choose_topic,
    director_review,
    file_stage_reports,
    letter_to_owner,
)
from app.agents.editorial import EditorialError, editorial_review, latest_editorial
from app.agents.memory import agent_for_role, remember
from app.agents.models import AgentMessage
from app.agents.reviews import (
    NoReviewer,
    ReviewError,
    approved_metadata,
    prepare_publication,
    publication_hold,
    review_failed_render,
    review_narration,
)
from app.analytics.services import MetricsUnavailable, ingest_publication_metrics
from app.analytics.trends import is_fresh, refresh_trends
from app.config import Settings
from app.economy.accountant import AccountantError, reconcile_day, record_render_costs
from app.economy.budget import may_spend
from app.economy.services import EconomyError
from app.factual.agent_pipeline import (
    NoVerifiedClaims,
    ScriptRejected,
    agent_extract_claims,
    agent_verify_claim,
    agent_write_script,
)
from app.factual.models import FactualClaim, ScriptDraft, SourceSnapshot, TopicIdea
from app.factual.services import (
    FactualGateError,
    TopicNotProducible,
    approve_script_draft,
    select_topic,
)
from app.factual.story_review import (
    MAX_EXCHANGES,
    StoryReviewError,
    latest_review,
    review_story,
    story_gate,
)
from app.integrations.services import selected_youtube
from app.media.models import (
    EditorialReview,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    VideoRenderJob,
)
from app.media.prompt_agent import PromptError, write_shot_prompts
from app.media.qc import evaluate_media_qc
from app.media.services import generate_storyboard_from_script
from app.providers.registry import ProviderRegistry
from app.providers.youtube_analytics import YouTubeAnalyticsProvider
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    PublisherNotConfigured,
    PublishingGateError,
    channel_bindings,
    evaluate_publishing_gate,
    film_identity,
    publish_media_asset,
    published_films,
)
from app.research.agent import (
    NoAuthorisedHosts,
    NoResearcher,
    ResearchAgentError,
    gather_sources,
    propose_topics,
)
from app.services import studio_environment, utc_now
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.services import StoryError, write_episode

logger = logging.getLogger("studio.runbook.stages")

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"

#: How many items one stage will process in a single run. A day's run should finish; a backlog of
#: two hundred sources is not a reason to hold the whole day open, and what is left is picked up
#: by tomorrow's run.
#: How many drafts of one story a single run will work through — the same number the review
#: counts to, so the room and the reading agree about when the conversation is over.
MAX_SCRIPT_EXCHANGES = MAX_EXCHANGES

BATCH = 5
#: Claims verified in one day. Verification is one short call per claim; extraction from
#: three pages produces thirty, and a film needs the ones about its own subject checked.
VERIFY_BATCH = 24


def _outcome(status: str, reason: str, **artefacts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "artefacts": artefacts}


def _has_language_model(registry: ProviderRegistry) -> bool:
    """Whether any language model is registered to run an agent task.

    Asked before every agent stage so that "no model configured" is reported as a skip with a
    reason, rather than surfacing as a failure from somewhere deep inside an agent run.
    """
    return bool(registry.registered_ids())


# ---------------------------------------------------------------------- idea generation --

#: Enough candidates in the pool that proposing more would only add noise; the day picks one.
IDEA_POOL_TARGET = 6


def _idea_generation(
    engine: Engine, registry: ProviderRegistry, settings: Settings
) -> dict[str, Any]:
    """Ask the Lead Researcher for candidate topics when the pool is thin (runbook §3)."""
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")
    with Session(engine) as session:
        pool = (
            session.scalar(
                select(func.count())
                .select_from(TopicIdea)
                .where(TopicIdea.status.in_(("PROPOSED", "RESEARCHED")))
            )
            or 0
        )
    if pool >= IDEA_POOL_TARGET:
        return _outcome(
            COMPLETED,
            f"{pool} teme candidate sunt deja în așteptare; nu s-au propus altele.",
            pool=pool,
        )
    # Today's trends before today's ideas; a feed that does not answer is recorded, not fatal.
    if settings.trends_enabled and not is_fresh(engine, settings.trends_geo):
        refresh_trends(engine, settings, str(uuid4()))
    try:
        proposal = propose_topics(
            engine, registry, settings, str(uuid4()), wanted=IDEA_POOL_TARGET - pool
        )
    except NoAuthorisedHosts as exc:
        return _outcome(SKIPPED, str(exc))
    except (ResearchAgentError, NoResearcher, ValueError) as exc:
        # A refused proposal is the validation working; it must not take the day with it.
        return _outcome(COMPLETED, f"Propunerile au fost respinse: {exc}"[:300], proposed=0)
    if proposal.get("blocked"):
        return _outcome(
            COMPLETED, f"Cercetătorul a escaladat: {proposal['blocked']}"[:300], proposed=0
        )
    stored = proposal.get("proposed", [])
    rejected = proposal.get("rejected", [])
    reason = f"{len(stored)} teme propuse de cercetător."
    if rejected:
        reason += f" {len(rejected)} respinse (duplicat sau site neautorizat)."
    return _outcome(COMPLETED, reason, proposed=[t["title"] for t in stored], rejected=rejected)


# ------------------------------------------------------------------ performance intake --


def _performance_intake(engine: Engine, vault: Any) -> dict[str, Any]:
    """Measure the videos the platform is actually serving.

    Only a publication with a remote video id has an audience to measure. A simulated one has
    none, and asking an analytics API about an internal row id would produce numbers about
    nothing.
    """
    # The bound slot names the account whose numbers these are. Without a binding the adapter
    # can still answer when exactly one account is connected; with several it cannot, and
    # attributing one channel's retention to another is worse than measuring nothing.
    bound = [b for b in channel_bindings(engine).values() if b.get("publisher_ready")]
    connection_id = bound[0]["youtube_connection_id"] if bound else None
    provider = YouTubeAnalyticsProvider.from_verified_settings(engine, vault, connection_id)
    if provider is None:
        return _outcome(
            SKIPPED,
            "Niciun cont YouTube legat de un slot de canal pentru analytics. Leagă contul în "
            "Publicare → Sloturi de canale; fără legătură nu se știe ale cui sunt cifrele.",
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


def _gather_for_candidates(
    engine: Engine, registry: ProviderRegistry, settings: Settings
) -> list[dict[str, Any]]:
    """Fetch pages for the best candidates that have none yet (runbook §4, retrieval half).

    Bounded to a couple of candidates a day: the point is to give verification something real
    to read, not to crawl. Every page is downloaded by the studio itself.
    """
    with Session(engine) as session:
        with_sources = {
            row for row in session.scalars(select(SourceSnapshot.topic_id)) if row is not None
        }
        # A topic whose pages could not be found today is not tried again today: the
        # Researcher's escalation says so, and the same guesses would 404 the same way.
        today = utc_now()[:10]
        failed_today = set()
        for message in session.scalars(
            select(AgentMessage).where(
                AgentMessage.intent == "ESCALATE", AgentMessage.created_at >= today
            )
        ):
            body = message.body_json if isinstance(message.body_json, dict) else {}
            if body.get("failed") and body.get("topic_id"):
                failed_today.add(str(body["topic_id"]))
        seen_titles: set[str] = set()
        candidates = []
        for topic in session.scalars(
            select(TopicIdea)
            .where(TopicIdea.status.in_(("PROPOSED", "RESEARCHED")))
            .order_by(TopicIdea.created_at.desc(), TopicIdea.novelty_score.desc())
            .limit(30)
        ):
            if topic.id in with_sources or topic.id in failed_today:
                continue
            if topic.title in seen_titles:
                continue  # the same title proposed twice needs one set of sources
            seen_titles.add(topic.title)
            candidates.append(topic.id)
            if len(candidates) == 2:
                break
    gathered = []
    for topic_id in candidates:
        try:
            gathered.append(gather_sources(engine, registry, settings, topic_id, str(uuid4())))
        except (ResearchAgentError, NoResearcher, NoAuthorisedHosts, ValueError) as exc:
            logger.info("source_gathering_skipped", extra={"reason": type(exc).__name__})
    return gathered


def _research_and_verification(
    engine: Engine, registry: ProviderRegistry, settings: Settings | None = None
) -> dict[str, Any]:
    """Read the ingested sources, then have a second agent check what the first extracted.

    Extraction and verification are deliberately the same stage: a claim nobody checked is not
    research, and leaving verification for later would let an unverified claim sit in the record
    looking like a finding.
    """
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    # The studio reads for itself before it reads what it was given: a candidate topic with no
    # source can never be verified, and waiting for the Owner to paste a link is not research.
    gathered = _gather_for_candidates(engine, registry, settings) if settings else []
    pages = sum(len(item["fetched"]) for item in gathered)

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

    extracted, unreadable = 0, 0
    for source_id in pending_sources:
        try:
            agent_extract_claims(engine, registry, source_id, str(uuid4()))
            extracted += 1
        except ValueError as exc:
            # An answer the parser cannot read is that source's loss for today, not the
            # day's: a mistyped number once stopped the whole run and put the studio in
            # safe mode. The next source is read; the reason says how many were not.
            logger.info("extraction_unreadable", extra={"source_id": source_id, "reason": str(exc)})
            unreadable += 1

    with Session(engine) as session:
        # Three pages yield thirty claims; five verified a day left the writer a film whose
        # ending had no fact behind it. The Fact Checker reads a claim in seconds, so the
        # day verifies up to VERIFY_BATCH, the ones the film depends on first.
        rank = {"CRITICAL": 0, "SUPPORTING": 1, "FLAVOR": 2}
        pending = session.scalars(
            select(FactualClaim)
            .where(FactualClaim.status == "UNVERIFIED", FactualClaim.source_id.is_not(None))
            .order_by(FactualClaim.created_at.asc())
        ).all()
        unverified = [
            claim.id
            for claim in sorted(pending, key=lambda c: rank.get(c.importance, 1))[:VERIFY_BATCH]
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

    if not pending_sources and not unverified and not pages:
        return _outcome(COMPLETED, "Nicio sursă nouă și nicio afirmație neverificată.", claims=0)
    reason = (
        f"{pages} pagini preluate, {extracted} surse citite, {verified} afirmații verificate, "
        f"{refused} verdicte respinse."
        + (f" {unreadable} surse fără afirmații citibile." if unreadable else "")
    )
    return _outcome(
        COMPLETED,
        reason,
        pages_fetched=pages,
        sources_read=extracted,
        claims_verified=verified,
        verdicts_refused=refused,
    )


# ------------------------------------------------------------------------- selection --


def topics_in_production(session: Session) -> tuple[list[str], list[str]]:
    """SELECTED topics with work genuinely in flight, and the ones that have stalled.

    Seven topics sat SELECTED for days: each had a script, a storyboard and a render whose
    quality control failed (placeholder visuals, before an image provider existed). Nothing
    could move them and nothing new could be chosen past them. A topic is in production
    while something is still owed on it — a script, a storyboard, a render, a QC verdict,
    a publication; one whose newest render failed or lost its QC verdict is stalled, and a
    stalled topic does not stop the studio from choosing the next one.

    Two more ways a topic can be finished with, both found live on 2026-09-12. A story the
    review REJECTED will never be rewritten — that is the revision budget working — so a topic
    holding one is owed nothing and must not block the next choice; it was blocking it. And a
    topic whose film has been published is simply done: it used to fall through to the stalled
    bucket and be reported as "selected earlier, renders failed quality control", which was
    said of a film that had gone out an hour before.
    """
    selected = list(session.scalars(select(TopicIdea).where(TopicIdea.status == "SELECTED")))
    if not selected:
        return [], []
    # Newest per topic and per script: with two drafts of one topic, or two storyboards of one
    # script, which row won used to depend on the order the rows came back in.
    scripts = {
        s.topic_id: s
        for s in session.scalars(select(ScriptDraft).order_by(ScriptDraft.created_at))
        if s.topic_id
    }
    boards = {
        b.script_draft_id: b
        for b in session.scalars(select(Storyboard).order_by(Storyboard.created_at))
    }
    jobs: dict[str, VideoRenderJob] = {}
    for row in session.scalars(select(VideoRenderJob).order_by(VideoRenderJob.started_at)):
        if row.status == "COMPLETED":
            jobs[row.storyboard_id] = row  # the newest completed render per storyboard
    verdicts: dict[str, str] = {}
    for verdict_row in session.scalars(
        select(QualityControlReport).order_by(QualityControlReport.verified_at)
    ):
        verdicts[verdict_row.media_asset_id] = verdict_row.status  # the newest per asset
    published = set(session.scalars(select(PublicationRecord.media_asset_id)))
    rejected = {
        r.media_asset_id for r in session.scalars(select(EditorialReview)) if r.verdict == "REJECT"
    }
    live: list[str] = []
    stalled: list[str] = []
    for topic in selected:
        script = scripts.get(topic.id)
        board = boards.get(script.id) if script else None
        last = jobs.get(board.id) if board else None
        if script is not None and board is None:
            # Nothing has been shot yet, so what happens next depends on the reading of the
            # page. A refused story is nobody's to retry; anything else is still owed work.
            review = latest_review(session, script.id)
            if review is not None and review.verdict == "REJECT":
                stalled.append(topic.id)
            else:
                live.append(topic.id)
            continue
        if last is None or not last.output_asset_id:
            live.append(topic.id)  # writing, storyboarding or rendering still owed
            continue
        verdict = verdicts.get(last.output_asset_id)
        if last.output_asset_id in published:
            continue  # the film is out; this topic is finished, neither live nor stuck
        if last.output_asset_id in rejected:
            stalled.append(topic.id)  # the Director said no; the departments hold the notes
        elif verdict == "PASSED":
            live.append(topic.id)  # waiting to be published
        elif verdict is None:
            live.append(topic.id)  # waiting for quality control
        else:
            stalled.append(topic.id)  # FAILED or INVALIDATED: nothing moves it on its own
    return live, stalled


def _selection(engine: Engine, registry: ProviderRegistry | None = None) -> dict[str, Any]:
    """Choose what the day produces (runbook §5): the Director decides, under policy.

    Only a topic with at least one SUPPORTED claim can be produced, so the shortlist is
    computed first and the Director chooses among those. With one candidate there is nothing
    to decide and asking would only spend a run; with no model available the studio falls back
    to the deterministic order it used before — and says which of the two happened.
    """
    with Session(engine) as session:
        in_production, stalled = topics_in_production(session)
        if in_production:
            return _outcome(
                COMPLETED,
                "Un subiect este deja în producție."
                + (
                    f" ({len(stalled)} selectate mai demult stau cu randări picate la QC.)"
                    if stalled
                    else ""
                ),
                topic_id=in_production[0],
                stalled=stalled,
            )
        rows = list(
            session.scalars(
                select(TopicIdea)
                .where(TopicIdea.status.in_(("PROPOSED", "RESEARCHED")))
                .order_by(TopicIdea.novelty_score.desc())
                .limit(20)
            )
        )
        supported = {
            topic_id: count
            for topic_id, count in session.execute(
                select(FactualClaim.topic_id, func.count())
                .where(FactualClaim.status == "SUPPORTED", FactualClaim.topic_id.is_not(None))
                .group_by(FactualClaim.topic_id)
            ).all()
        }
        shortlist = [
            {
                "id": topic.id,
                "title": topic.title,
                "angle": topic.angle[:300],
                "scores": topic.scores_json or {},
                "supported_claims": supported.get(topic.id, 0),
            }
            for topic in rows
            if supported.get(topic.id, 0) > 0
        ]
        candidates = [topic.id for topic in rows]

    decided_by, notes = None, None
    if len(shortlist) > 1 and registry is not None and _has_language_model(registry):
        try:
            decision = choose_topic(engine, registry, shortlist, str(uuid4()))
            candidates = [decision["topic_id"]] + [
                c for c in candidates if c != decision["topic_id"]
            ]
            decided_by, notes = "Director", decision["reason"]
        except (DirectorError, ValueError) as exc:
            # An unusable choice falls back to the deterministic order rather than stopping
            # the day; the Owner is told the Director did not decide it.
            logger.info("director_choice_refused", extra={"reason": str(exc)[:200]})

    for topic_id in candidates:
        try:
            chosen = select_topic(engine, topic_id, str(uuid4()), decided_by, notes)
        except TopicNotProducible:
            continue
        reason = f"Subiect selectat: {chosen['title']}."
        if decided_by:
            reason += f" Ales de Director: {notes}"[:220]
        return _outcome(
            COMPLETED,
            reason,
            topic_id=topic_id,
            decided_by=decided_by,
            shortlist=len(shortlist),
        )

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


def script_work(session: Session, selected: list[str]) -> list[tuple[str, list[str]]]:
    """The topics that owe a script, and what the last reading of each one said.

    A topic used to be skipped the moment any draft existed for it. So a story the review sent
    back twice sat SELECTED with two refused drafts and no storyboard: nothing would write a
    third, because a script existed, and nothing else could be chosen, because the topic still
    counted as in production. The studio had written itself into a corner it could not leave.

    A topic owes work while its newest draft has no storyboard and the review sent it back. The
    notes come with it, so the rewrite is briefed rather than guessed. A draft the review
    REJECTED is not rewritten here — the revision budget is spent and the letters have gone to
    the departments; it is the Director's matter now, and the topic stops holding the studio up.
    """
    newest: dict[str, ScriptDraft] = {}
    for draft in session.scalars(select(ScriptDraft).order_by(ScriptDraft.created_at)):
        if draft.topic_id:
            newest[draft.topic_id] = draft  # ordered by age, so the last one wins
    storyboarded = set(session.scalars(select(Storyboard.script_draft_id)))
    owed: list[tuple[str, list[str]]] = []
    for topic_id in selected:
        latest = newest.get(topic_id)
        if latest is None:
            owed.append((topic_id, []))
            continue
        if latest.id in storyboarded:
            continue  # the film is past the page
        review = latest_review(session, latest.id)
        if review is None:
            # A draft nobody read is not progress. This is what a crashed run leaves behind —
            # the studio wrote a draft at the moment the day died and the reading never
            # happened — and it used to be invisible to both paths: not owed a rewrite,
            # because no reading asked for one, and not past the page either, so the topic
            # went on counting as in production and nothing else could be chosen.
            owed.append((topic_id, []))
            continue
        if review.verdict != "REVISE":
            continue  # approved and waiting to be shot, or refused and not ours to retry
        notes = list((review.notes_json or {}).get("notes") or [])
        owed.append((topic_id, notes))
    return owed


def _director_approves(engine: Engine, script_id: str, review: dict[str, Any]) -> str | None:
    """A story the Director passed is a story she approves, in the same breath.

    Approval is hers (the Owner said so): a script she has just read and passed does not wait
    in his inbox for a button. The factual gate is re-checked inside `approve_script_draft`, so
    her approval cannot carry a claim that stopped being supported while the script was written.
    """
    if review["verdict"] != "PASS":
        return None
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        director_id = director.id if director else None
    try:
        approve_script_draft(
            engine,
            script_id,
            str(uuid4()),
            approved_by=director_id,
            # A PASS means no check was broken, so there is nothing to enumerate here: what the
            # record needs is who decided and on what reading, and the review itself holds the
            # scores and the notes behind that reading.
            reason="Recenzia Directorului: PASS. Povestea a trecut toate verificările editoriale.",
        )
    except (FactualGateError, ValueError) as exc:
        # The gate refused at approval time — a claim was refuted after the script was written.
        # That is the gate working, and it must not take the rest of the day with it.
        logger.info("script_approval_refused", extra={"script_id": script_id, "reason": str(exc)})
        return None
    return script_id


def _script_and_storyboard(
    engine: Engine,
    registry: ProviderRegistry,
    language: str = "en",
    target_seconds: int = 30,
) -> dict[str, Any]:
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
        pending = script_work(session, selected)[:1]

    reviews: list[dict[str, Any]] = []
    approvals: list[str] = []
    for topic_id, carried_notes in pending:
        # The writer and the Director keep working the story until it passes, is refused, or
        # the room closes. It used to be exactly two drafts a day: a story one note away from
        # passing waited until tomorrow, and the day ended with nothing made. Text is the
        # cheapest thing the studio produces — a render is where the money is — so the
        # conversation happens now, in full, and the film reaches the camera in the same day.
        notes = list(carried_notes or [])
        for attempt in range(1, MAX_SCRIPT_EXCHANGES + 1):
            try:
                written = agent_write_script(
                    engine,
                    registry,
                    topic_id,
                    str(uuid4()),
                    target_duration_seconds=target_seconds,
                    language=language,
                    notes=notes or None,
                )
                drafted += 1
                # The story is read before anything is generated: a shot regenerated because
                # the story was weak costs dollars, and reading costs a few seconds.
                review = review_story(
                    engine, registry, written["script"]["id"], target_seconds=target_seconds
                )
                reviews.append(
                    {
                        "verdict": review["verdict"],
                        "failed": review["failed"][:4],
                        "exchange": attempt,
                    }
                )
                decided = _director_approves(engine, written["script"]["id"], review)
                if decided:
                    approvals.append(decided)
                    break  # she approved it; the camera is next
                if review["verdict"] == "REJECT":
                    break  # the budget is spent or the story is unsupportable; let it go
                notes = list(review["notes"])
            except (ScriptRejected, NoVerifiedClaims) as exc:
                # The draft was refused and nothing was stored — which is the pipeline working,
                # not the day breaking. A model that writes narration it cannot attribute to a
                # verified claim is a content problem; letting it stop the run would also stop
                # the day's log and every stage after it, over an outcome the studio handled
                # correctly. The room closes for this topic; the day goes on.
                logger.info("script_rejected", extra={"topic_id": topic_id, "reason": str(exc)})
                rejected.append(str(exc))
                break
        else:
            logger.info(
                "script_room_closed",
                extra={"topic_id": topic_id, "exchanges": MAX_SCRIPT_EXCHANGES},
            )

    with Session(engine) as session:
        storyboarded = set(session.scalars(select(Storyboard.script_draft_id)))
        approved = [
            script.id
            for script in session.scalars(
                select(ScriptDraft).where(ScriptDraft.status == "APPROVED")
            )
            if script.id not in storyboarded
        ][:BATCH]
        # A script the Owner approved before the story review existed, or approved by hand
        # in the interface, has no review — and the render stage would hold it forever
        # rather than buying shots for a story nobody judged. So it is read here, where
        # reading costs nothing, instead of stalling the day.
        unreviewed = [
            script_id for script_id in approved if latest_review(session, script_id) is None
        ]
    for script_id in unreviewed:
        try:
            reviews.append(
                {
                    "verdict": review_story(
                        engine, registry, script_id, target_seconds=target_seconds
                    )["verdict"],
                    "backlog": True,
                }
            )
        except StoryReviewError as exc:
            logger.info("story_review_failed", extra={"reason": str(exc)[:160]})

    boards = 0
    prompted = 0
    for script_id in approved:
        board = generate_storyboard_from_script(
            engine, script_id, "MOTION_GRAPHIC", "9:16", str(uuid4())
        )
        boards += 1
        # One look for the whole film, then a full prompt package per shot. This is where a
        # story becomes instructions a camera would understand — the step the studio did not
        # have when it sent "a spinning galaxy" to a model at 2.60 USD a shot.
        try:
            written = write_shot_prompts(engine, registry, board["id"], str(uuid4()))
            prompted += len(written["shots"])
        except PromptError as exc:
            logger.info("shot_prompts_skipped", extra={"reason": str(exc)[:160]})

    with Session(engine) as session:
        awaiting = session.scalar(
            select(ScriptDraft.id).where(ScriptDraft.status == "VERIFIED_PASS").limit(1)
        )

    reason = (
        f"{drafted} scenarii scrise în {len(reviews)} schimburi, "
        f"{len(approvals)} aprobate de Director, {boards} storyboard-uri generate."
    )
    if prompted:
        reason += f" {prompted} cadre descrise complet."
    if reviews:
        reason += " Recenzia poveștii: " + ", ".join(r["verdict"] for r in reviews) + "."
    if rejected:
        reason += f" {len(rejected)} respinse: {rejected[0][:120]}"
    if awaiting:
        reason += " Un scenariu așteaptă aprobarea ta înainte de storyboard."
    return _outcome(
        COMPLETED,
        reason,
        scripts=drafted,
        storyboards=boards,
        shots_described=prompted,
        story_reviews=reviews,
        rejected=rejected,
        awaiting_approval=bool(awaiting),
    )


# ----------------------------------------------------------------------------- media --


def stalled_storyboards(session: Session, engine: Engine, vault: Any) -> list[str]:
    """Rendered storyboards whose render failed quality control for want of real visuals,
    newest first, one per title — worth rendering again only once an image provider is
    READY, or the day would make the same placeholder film twice."""
    from app.media.factory import media_readiness  # noqa: PLC0415

    if media_readiness(engine, vault).get("image", {}).get("status") != "READY":
        return []
    newest_job: dict[str, VideoRenderJob] = {}
    for row in session.scalars(select(VideoRenderJob).order_by(VideoRenderJob.started_at)):
        if row.status == "COMPLETED":
            newest_job[row.storyboard_id] = row
    verdicts: dict[str, QualityControlReport] = {}
    for verdict_row in session.scalars(
        select(QualityControlReport).order_by(QualityControlReport.verified_at)
    ):
        verdicts[verdict_row.media_asset_id] = verdict_row
    seen_titles: set[str] = set()
    out: list[str] = []
    for board in session.scalars(select(Storyboard).order_by(Storyboard.created_at.desc())):
        if board.status == "REJECTED":
            continue  # the Director closed it; a re-render would be the same film
        last = newest_job.get(board.id)
        if last is None or not last.output_asset_id:
            continue
        verdict = verdicts.get(last.output_asset_id)
        if verdict is None or verdict.status not in ("FAILED", "INVALIDATED"):
            continue
        reasons = " ".join(str(r) for r in (verdict.failure_reasons_json or [])).lower()
        if "placeholder" not in reasons and verdict.status != "INVALIDATED":
            continue
        if board.title in seen_titles:
            continue  # a duplicate of a title already queued: not worth a second render
        seen_titles.add(board.title)
        out.append(board.id)
    return out


def _budget_left_usd(engine: Engine, settings: Settings) -> float:
    """What the tightest active budget still allows today, in dollars."""
    from app.economy.budget import budget_status  # noqa: PLC0415

    left = float(settings.motion_budget_usd)
    for period in budget_status(engine).get("budgets", []):
        micros = period.get("remaining_usd_micros")
        if isinstance(micros, int | float):
            left = min(left, max(0.0, float(micros) / 1_000_000))
    return left


def _media(
    engine: Engine, settings: Settings, vault: Any, registry: ProviderRegistry | None = None
) -> dict[str, Any]:
    """Render the storyboards that have no finished video yet.

    Before a storyboard is voiced, the Voice Artist reviews its narration (pronunciation,
    pacing). Her review is filed as a report; a FLAG escalates to the Director. It does not
    hold the render: the words rest on verified claims and the day's output is not blocked
    on an opinion about delivery.
    """
    from app.media.assembler import RenderEngineUnavailable, assemble_video_job
    from app.media.factory import image_provider, motion_for_scene, render_plan, tts_provider
    from app.media.production_policy import named_model
    from app.providers.media_http import MediaProviderError

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
        retry = [] if pending else stalled_storyboards(session, engine, vault)[:1]

    if not pending and not retry:
        return _outcome(COMPLETED, "Niciun storyboard de randat.", rendered=0)
    pending = pending or retry

    # Nothing is generated for a film whose story has not been read and passed. This is the
    # gate before the money: every other gate in the studio used to run after it was spent.
    held: list[str] = []
    with Session(engine) as session:
        allowed = []
        for storyboard_id in pending:
            board = session.get(Storyboard, storyboard_id)
            passed, why = (
                story_gate(session, board.script_draft_id) if board else (False, "fără storyboard")
            )
            if passed:
                allowed.append(storyboard_id)
            else:
                held.append(f"{storyboard_id[:8]}: {why}")
    if not allowed:
        return _outcome(
            SKIPPED,
            "Niciun film nu a trecut recenzia de poveste: " + (held[0] if held else "—"),
            held=held,
        )
    pending = allowed

    # The budget is asked before anything is generated (runbook §7, "reserve budget"). What
    # the render will cost is estimated from the plan at the stored price of each scene's
    # model; scenes without a price count as zero here and are reported as unpriced later.
    budget = may_spend(engine, 0)
    if not budget["allowed"]:
        return _outcome(SKIPPED, budget["reason"], budget=budget["period"])

    # Which environment the day renders in is the studio's own state, not a parameter.
    environment = studio_environment(engine)
    images = image_provider(engine, vault)
    voice = tts_provider(engine, vault)
    produced = []
    refused: list[dict[str, str]] = []
    narration_reviews = []
    costs_recorded = 0
    for storyboard_id in pending:
        if registry is not None and _has_language_model(registry):
            try:
                review = review_narration(engine, registry, storyboard_id, str(uuid4()))
                narration_reviews.append(
                    {"storyboard_id": storyboard_id, "verdict": review["verdict"]}
                )
            except (ReviewError, NoReviewer, ValueError) as exc:
                narration_reviews.append({"storyboard_id": storyboard_id, "error": str(exc)[:200]})
        try:
            # Channel policy, series rules, overrides and locked character voices decide per
            # scene; the Organization default is the fallback for scenes nothing else names.
            planned = render_plan(engine, vault, storyboard_id)
            result = assemble_video_job(
                engine,
                storyboard_id,
                str(uuid4()),
                ffmpeg_path=settings.ffmpeg_path,
                # The plan resolves the hierarchy's image choice (Runway included); the
                # Organization-level adapter is the fallback for a plan that names none.
                image_adapter=planned.get("image") or images,
                tts_adapter=voice,
                tts_adapter_for_scene=planned["tts_for_scene"],
                # The model of each scene is chosen against what the scene requires, in
                # the environment the studio is in: a test buys the cheapest that can do the
                # job, production the least expensive that reaches the quality. A model a
                # level of the hierarchy named by hand is honoured as an override.
                motion_chooser=(
                    lambda scene, tier, seconds, budget, exclude, plan=planned["plan"]: (
                        motion_for_scene(
                            engine,
                            vault,
                            scene,
                            environment=environment,
                            tier=tier,
                            seconds=seconds,
                            budget_usd=budget,
                            forced_model=named_model(plan, scene.get("scene_index")),
                            exclude=exclude,
                            max_usd_per_second=(
                                settings.test_max_cost_per_second_usd
                                if environment == "TEST"
                                else None
                            ),
                        )
                    )
                ),
                environment=environment,
                motion_from_prompt=environment == "TEST",
                # What this film may spend on motion, and how many scenes may be generated.
                # The ceiling is the smaller of the studio's per-film limit and what the
                # day's budget still allows, so one film cannot spend the week.
                motion_budget_usd=(
                    settings.test_max_cost_per_generation_usd
                    if environment == "TEST"
                    else min(settings.motion_budget_usd, _budget_left_usd(engine, settings))
                ),
                motion_max_usd_per_second=(
                    settings.test_max_cost_per_second_usd if environment == "TEST" else None
                ),
                price_tolerance_percent=settings.price_stale_tolerance_percent,
                motion_scene_limit=(
                    settings.test_motion_scenes
                    if environment == "TEST"
                    else settings.motion_scenes_max
                ),
                production_plan=planned["plan"],
            )
        except RenderEngineUnavailable as exc:
            return _outcome(SKIPPED, f"Randarea nu poate rula: {exc}")
        except MediaProviderError as exc:
            # A provider's refusal is that render's failure, not the day's: the storyboard
            # stays approved and unrendered, tomorrow's stage tries it again, and the Owner
            # reads why in the Director's report — not in a safe-mode banner.
            refused.append({"storyboard_id": storyboard_id, "error": str(exc)[:200]})
            logger.info("render_refused", extra={"storyboard_id": storyboard_id})
            continue
        produced.append(result["output_asset_id"])
        # Into the books at once, at the stored price, so the day's close and the next
        # budget check see what was just spent.
        try:
            costs_recorded += record_render_costs(
                engine,
                result["job_id"],
                str(uuid4()),
                alert_percent=settings.price_change_alert_percent,
            )["recorded"]
        except (EconomyError, KeyError):
            logger.info("render_cost_not_recorded", extra={"storyboard_id": storyboard_id})

    substitutes = images is None or voice is None
    reason = f"{len(produced)} videoclipuri randate."
    if refused:
        reason += f" {len(refused)} randări refuzate de furnizor: {refused[0]['error']}."
    if retry:
        reason += (
            " (o randare reluată: cea veche picase la QC cu substitute, acum sunt imagini reale.)"
        )
    if substitutes:
        # Said here as well as in QC, because a run summary is read on its own.
        reason += " Fără furnizor de imagine sau voce, deci cu substitute — QC le va bloca."
    return _outcome(
        COMPLETED,
        reason,
        assets=produced,
        used_substitutes=substitutes,
        narration_reviews=narration_reviews,
        costs_recorded=costs_recorded,
    )


# ---------------------------------------------------------------------- edit and QC --


def _edit_and_qc(engine: Engine, registry: ProviderRegistry | None = None) -> dict[str, Any]:
    """Measure every rendered file that has not been measured yet.

    Quality control is measured, never opined. What follows a failure is the Video Editor's
    work: a diagnosis and a proposed correction, filed as an escalation for the Director.
    """
    with Session(engine) as session:
        # A verdict a migration invalidated is no verdict: the file is measured again.
        checked = set(
            session.scalars(
                select(QualityControlReport.media_asset_id).where(
                    QualityControlReport.status != "INVALIDATED"
                )
            )
        )
        # Selected on what the file is, not on what it was labelled. The renderer writes
        # RENDERED_VIDEO and the test fixtures write VIDEO_COMPOSED; keying quality control to
        # either name would leave real renders unmeasured, which is how a video reaches the
        # publishing gate with no measurement behind it.
        pending = [
            asset.id
            for asset in session.scalars(
                select(MediaAsset)
                .where(MediaAsset.mime_type.startswith("video/"))
                .order_by(MediaAsset.created_at.desc())
            )
            if asset.id not in checked
        ][:BATCH]

    if not pending:
        return _outcome(COMPLETED, "Niciun material nou de verificat.", checked=0)

    passed, failed = 0, 0
    diagnoses = []
    for asset_id in pending:
        report = evaluate_media_qc(engine, asset_id, str(uuid4()))
        if report["status"] == "PASSED":
            passed += 1
            continue
        failed += 1
        if registry is not None and _has_language_model(registry):
            try:
                diagnosis = review_failed_render(engine, registry, report["id"], str(uuid4()))
                diagnoses.append(
                    {"report_id": report["id"], "correction": diagnosis.get("correction")}
                )
            except (ReviewError, NoReviewer, ValueError) as exc:
                diagnoses.append({"report_id": report["id"], "error": str(exc)[:200]})
    return _outcome(
        COMPLETED,
        f"{passed} au trecut QC, {failed} au picat.",
        passed=passed,
        failed=failed,
        diagnoses=diagnoses,
    )


# --------------------------------------------------------------------------- publish --


def _publish(
    engine: Engine,
    vault: Any,
    registry: ProviderRegistry | None = None,
    language: str = "en",
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Publish what the gate allows, to a channel that is actually connected.

    The Publisher prepares the title, description and tags from the script and says READY
    or HOLD. A HOLD keeps the candidate out until the Director lifts it; the five gates
    are checked by code either way. Without a language model the Publisher cannot do her
    work, and the studio does not publish with a bare title in her place.
    """
    # Which account a video is published to is the binding on the channel slot, never "the
    # only connection" or "the first row": a studio with two channels would otherwise upload
    # one channel's video to the other, which no later check could undo.
    bindings = channel_bindings(engine)
    with Session(engine) as session:
        slots = [
            (channel.id, channel.channel_name, bindings.get(channel.id, {}))
            for channel in session.scalars(
                select(ChannelRecord).where(ChannelRecord.platform == "YOUTUBE")
            )
        ]
    ready = [(cid, name, b) for cid, name, b in slots if b.get("publisher_ready")]
    if not ready:
        if not slots:
            return _outcome(SKIPPED, "Niciun canal configurat în studio.")
        return _outcome(
            SKIPPED,
            "Niciun slot de canal nu este legat de un cont YouTube conectat. Leagă-le în "
            "Publicare → Sloturi de canale; publicarea și analytics folosesc legătura.",
        )
    channel_id, channel_name, binding = ready[0]
    try:
        provider = selected_youtube(engine, vault, binding["youtube_connection_id"])
    except ValueError as exc:
        return _outcome(SKIPPED, str(exc))
    if provider is None:
        return _outcome(SKIPPED, "Contul YouTube legat de acest canal nu mai este conectat.")

    with Session(engine) as session:
        published_assets = set(session.scalars(select(PublicationRecord.media_asset_id)))
        # A film the Director rejected stays out of the queue; the next one comes forward.
        rejected_assets = {
            review.media_asset_id
            for review in session.scalars(select(EditorialReview))
            if review.verdict == "REJECT"
        }
        # The queue holds files, but the channel receives films. One film rendered four times
        # is four QC-passed assets: publishing them in turn would put the same video on the
        # channel four times, once per day. So the queue is collapsed to one entry per film —
        # the newest render of it — and a film this channel already carries is not a candidate
        # at all. The gate refuses a duplicate as well; this is what lets the stage walk past
        # it to the next real film instead of stopping on a refusal.
        carried = published_films(session, channel_id)
        offered: set[str] = set()
        candidates: list[tuple[str, str]] = []
        for report in session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.status == "PASSED")
            .order_by(QualityControlReport.verified_at.desc())
        ):
            if report.media_asset_id in published_assets:
                continue
            if report.media_asset_id in rejected_assets:
                continue
            script_id, storyboard_id = film_identity(session, report.media_asset_id)
            keys = [key for key in (script_id, storyboard_id) if key is not None]
            if any(key in carried for key in keys):
                continue  # already on this channel, under whatever file name
            if any(key in offered for key in keys):
                continue  # an older render of a film already queued above
            offered.update(keys)
            candidates.append((report.media_asset_id, report.id))

    if not candidates:
        return _outcome(COMPLETED, "Niciun material aprobat de QC în așteptarea publicării.")

    asset_id, _ = candidates[0]
    # The Director watches the film before anyone prepares its publication. Nothing goes
    # to a channel that she has not approved, and her refusal is a letter to whoever must
    # change something, not a silent skip.
    with Session(engine) as session:
        editorial = latest_editorial(session, asset_id)
    if editorial is None:
        if registry is None or not _has_language_model(registry):
            return _outcome(
                SKIPPED, "Directorul nu poate viziona materialul: niciun model de limbaj."
            )
        try:
            watched = editorial_review(
                engine,
                registry,
                asset_id,
                str(uuid4()),
                language=language,
                ffmpeg_path=ffmpeg_path,
            )
        except (EditorialError, ValueError) as exc:
            return _outcome(SKIPPED, f"Directorul nu a putut viziona materialul: {exc}"[:300])
        editorial_verdict, editorial_reasons = watched["verdict"], watched["reasons"]
    else:
        editorial_verdict = editorial.verdict
        editorial_reasons = list(editorial.reasons_json or [])
    if editorial_verdict != "APPROVE":
        return _outcome(
            COMPLETED,
            "Directorul a respins materialul înainte de publicare: "
            + "; ".join(str(r) for r in editorial_reasons)[:300],
            rejected_asset=asset_id,
            reasons=editorial_reasons,
        )
    verdict = evaluate_publishing_gate(engine, asset_id, channel_id)
    if not verdict["eligible"]:
        return _outcome(
            COMPLETED,
            "Poarta de publicare a refuzat: " + "; ".join(verdict["reasons"]),
            blocked_asset=asset_id,
            reasons=verdict["reasons"],
        )

    with Session(engine) as session:
        hold = publication_hold(session, asset_id)
        metadata = approved_metadata(session, asset_id)
    if hold:
        return _outcome(
            COMPLETED,
            "Publisher-ul ține materialul în așteptare: " + "; ".join(hold["hold_reasons"])[:300],
            held_asset=asset_id,
            hold_message_id=hold["message_id"],
        )
    if metadata is None:
        if registry is None or not _has_language_model(registry):
            return _outcome(
                SKIPPED,
                "Publisher-ul nu poate pregăti metadatele: niciun model de limbaj disponibil.",
            )
        try:
            prepared = prepare_publication(
                engine, registry, asset_id, channel_id, str(uuid4()), language=language
            )
        except (ReviewError, NoReviewer, ValueError) as exc:
            return _outcome(SKIPPED, f"Publisher-ul nu a pregătit publicarea: {exc}"[:300])
        if prepared["verdict"] != "READY":
            return _outcome(
                COMPLETED,
                "Publisher-ul ține materialul în așteptare: "
                + "; ".join(prepared.get("hold_reasons", []))[:300],
                held_asset=asset_id,
                hold_message_id=prepared.get("message_id"),
            )
        metadata = {
            "title": prepared["title"],
            "description": prepared["description"],
            "tags": prepared["tags"],
        }

    try:
        published = publish_media_asset(
            engine,
            media_asset_id=asset_id,
            channel_id=channel_id,
            title=metadata["title"][:100],
            description=metadata["description"],
            tags=metadata["tags"],
            privacy_status="private",
            correlation_id=str(uuid4()),
            provider=provider,
        )
    except (PublishingGateError, PublisherNotConfigured) as exc:
        return _outcome(SKIPPED, str(exc))

    with Session(engine) as session, session.begin():
        publisher = agent_for_role(session, "Publisher")
        if publisher is not None:
            remember(
                session,
                memory_class="HISTORICAL_EVENT",
                content=(
                    f"Published “{metadata['title'][:100]}” to {channel_name}: "
                    f"{published['status']}."
                ),
                source_type="event",
                source_id=published["id"],
                agent_id=publisher.id,
            )
    return _outcome(
        COMPLETED,
        f"Publicat pe {channel_name}: {published['status']}.",
        publication_id=published["id"],
        publication_status=published["status"],
        title=metadata["title"],
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
        episode = write_episode(
            engine, registry, pending[0], str(uuid4()), language=settings.content_language
        )
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


# ------------------------------------------------------------------------- post_run --


#: A stage report nobody read in this many days is archived: the day it reported on is
#: gone, and an inbox of seventy-five old reports buries the letters that need an answer.
REPORT_SHELF_DAYS = 3


def archive_stale_reports(engine: Engine) -> int:
    """Resolve STATUS reports in the Director's inbox that are older than the shelf life."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.agents.messages import open_messages, resolve_message  # noqa: PLC0415

    limit = (datetime.now(UTC) - timedelta(days=REPORT_SHELF_DAYS)).isoformat()
    archived = 0
    with Session(engine) as session, session.begin():
        for message in open_messages(session, inbox=True, limit=500):
            if message.intent == "STATUS" and message.created_at < limit:
                resolve_message(
                    session,
                    message.id,
                    resolution=f"Arhivat: raport neexaminat în {REPORT_SHELF_DAYS} zile.",
                    resolved_by="system",
                    status="RESOLVED",
                )
                archived += 1
    return archived


def _post_run(
    engine: Engine, registry: ProviderRegistry, outcomes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Close the books, file every department's report, then have the Director review the inbox.

    The Accountant closes first (runbook §10, "reconcile cost"): her figures are in the inbox
    when the Director reads it, and a budget exceeded reaches the Owner the same evening.
    """
    close: dict[str, Any] | None = None
    if _has_language_model(registry):
        try:
            close = reconcile_day(engine, registry, str(uuid4()))
        except (AccountantError, ValueError) as exc:
            logger.info("daily_close_refused", extra={"reason": str(exc)[:200]})
            close = {"error": str(exc)[:200]}
    if close and "headline" in close:
        books = {
            "status": close["intent"],
            "reason": close["headline"],
            "agent_id": close["agent_id"],
            "holds": (close.get("report") or {}).get("holds", []),
        }
    else:
        books = {"status": "SKIPPED", "reason": (close or {}).get("error") or "fără model"}
    outcomes = {**outcomes, "books": books}
    filed = file_stage_reports(engine, outcomes, str(uuid4()))
    if not _has_language_model(registry):
        return _outcome(
            SKIPPED,
            f"{len(filed)} rapoarte depuse; Directorul nu le poate revizui fără un model "
            "de limbaj.",
            reports=len(filed),
        )
    archived = archive_stale_reports(engine)
    try:
        # A dozen messages per review; the review comes round up to three times in one
        # evening while the inbox still holds more, so a busy day is decided, not deferred.
        review = director_review(engine, registry, str(uuid4()), outcomes)
        for _ in range(2):
            if not review.get("left_open") or not review.get("reviewed"):
                break
            # A second or third pass that fails does not undo the first: the messages it
            # would have read stay open for the next round, and the Owner is not told the
            # evening's review was refused when most of it was done.
            try:
                more = director_review(engine, registry, str(uuid4()), outcomes)
            except (DirectorError, ValueError) as exc:
                review = {**review, "later_pass_refused": str(exc)[:200]}
                break
            review = {
                **more,
                "reviewed": review.get("reviewed", 0) + more.get("reviewed", 0),
                "applied": list(review.get("applied", [])) + list(more.get("applied", [])),
            }
    except (DirectorError, ValueError) as exc:
        letter_to_owner(
            engine,
            "Nu am putut revizui ziua",
            f"Revizuirea de seară nu a putut rula: {str(exc)[:300]}. Rapoartele "
            f"({len(filed)}) sunt în inbox, nedecise. Verifică modelul meu în Settings sau "
            "spune-mi ce să fac cu ele. — Sarah",
            str(uuid4()),
        )
        return _outcome(
            COMPLETED,
            f"{len(filed)} rapoarte depuse; revizuirea Directorului a fost respinsă: {exc}"[:300],
            reports=len(filed),
            review_rejected=str(exc)[:200],
        )
    if review.get("blocked"):
        return _outcome(
            COMPLETED,
            f"{len(filed)} rapoarte depuse; Directorul a escaladat: {review['blocked']}"[:300],
            reports=len(filed),
            blocked=review["blocked"],
        )
    return _outcome(
        COMPLETED,
        f"{len(filed)} rapoarte depuse; Directorul a revizuit {review.get('reviewed', 0)} mesaje, "
        f"{len(review.get('applied', []))} decizii."
        + (f" {archived} rapoarte vechi arhivate." if archived else ""),
        reports=len(filed),
        reviewed=review.get("reviewed", 0),
        applied=review.get("applied", []),
        left_open=review.get("left_open", 0),
        priorities=review.get("priorities", []),
    )


# --------------------------------------------------------------------------- wiring --


def build_stage_runners(
    engine: Engine, settings: Settings, vault: Any, registry: ProviderRegistry
) -> dict[str, Callable[[], dict[str, Any]]]:
    """The runners for the stages that have real work behind them.

    Every stage of `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` now has work behind it:
    §3 idea generation (the Lead Researcher proposes a scored, deduplicated pool), §4 research
    (the studio fetches its own pages from the authorised sites, then extracts and verifies),
    §5 selection (the Director chooses among producible candidates) and §10 post-run (the
    Director's review of the day's reports).
    """
    # Each stage's outcome is kept for the day so post_run can report on it; the runbook
    # writes the run record only after every stage, so the record is not readable yet.
    outcomes: dict[str, dict[str, Any]] = {}

    def keep(name: str, runner: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
        def run() -> dict[str, Any]:
            outcome = runner()
            outcomes[name] = outcome
            return outcome

        return run

    return {
        "performance_intake": keep(
            "performance_intake", lambda: _performance_intake(engine, vault)
        ),
        "idea_generation": keep(
            "idea_generation", lambda: _idea_generation(engine, registry, settings)
        ),
        "research_and_verification": keep(
            "research_and_verification",
            lambda: _research_and_verification(engine, registry, settings),
        ),
        "selection": keep("selection", lambda: _selection(engine, registry)),
        "script_and_storyboard": keep(
            "script_and_storyboard",
            lambda: _script_and_storyboard(
                engine,
                registry,
                settings.content_language,
                settings.target_video_seconds,
            ),
        ),
        "media": keep("media", lambda: _media(engine, settings, vault, registry)),
        "edit_and_qc": keep("edit_and_qc", lambda: _edit_and_qc(engine, registry)),
        "publish": keep(
            "publish",
            lambda: _publish(
                engine, vault, registry, settings.content_language, settings.ffmpeg_path
            ),
        ),
        "post_run": lambda: _post_run(engine, registry, outcomes),
        "serial_queue": keep("serial_queue", lambda: _serial_queue(engine, registry, settings)),
    }
