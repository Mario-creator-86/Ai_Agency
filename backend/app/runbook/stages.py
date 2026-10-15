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

**Where a person decides, the studio stops; where the Director decides, she does.** A script she
has read and passed is approved in the same breath (`_director_approves`, the Owner's word since
2026-09-12), with the factual gate re-checked at approval; a script that fails her review is sent
back with her notes for another exchange, not left in an inbox. The run happens at all only
because the Owner cleared the autonomy stop, which is what authorises the studio to act — but
clearing a stop is not the same as approving a film, and publication has its own five-point gate
that re-checks the stop, the file, quality control, factual provenance and duplication, plus a
sixth for a film that would be seen.

**Every stage now says what it is, in risk terms, before it runs.** `STAGE_ACTIONS` maps each
stage to one action and one tier of `../architecture/31_GOVERNANCE_APPROVAL_POLICY.md`, and
`mode_refusal` asks the Policy Kernel's `may_act` whether the autonomy mode the Owner set lets
the studio attempt it. A stage above the mode is SKIPPED with his reason — not BLOCKED, which
would end the day: a mode is his decision, not an incident, and the stages the mode does allow
still do their work. Under SUPERVISED an external write becomes the approval request he
answers instead of an upload. The stop is not read here and is not weakened by that: the
runbook reads it before every stage, the media stage before every film, the render between
scenes, the publishing gate and the Policy Kernel each in their own place.

Nothing here fabricates content or a verdict. Every stage either performs the real operation
against the real services or reports why it could not.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.director import (
    DirectorError,
    choose_topic,
    director_review,
    file_stage_reports,
    letter_to_owner,
)
from app.agents.editorial import (
    EditorialError,
    accepted_under_cap,
    editorial_review,
    latest_editorial,
)
from app.agents.memory import agent_for_role, remember
from app.agents.models import AgentMessage
from app.agents.reviews import (
    NoReviewer,
    ReviewError,
    approved_metadata,
    failed_render_reading,
    prepare_publication,
    publication_hold,
    review_bought_pictures,
    review_failed_render,
    review_film_qc,
    review_narration,
)
from app.analytics.services import (
    analytics_provider_for_channel,
    measure_channel_publications,
)
from app.analytics.trends import is_fresh, refresh_trends
from app.config import Settings
from app.db import lock_for_write
from app.economy.accountant import (
    AccountantError,
    budget_refusal_letter,
    reconcile_day,
    record_failed_render_cost,
    record_render_costs,
    waiting_approvals_letter,
)
from app.economy.budget import (
    estimate_film_cost_micros,
    release_reservation,
    reserve_spend,
    settle_reservation,
)
from app.economy.services import EconomyError
from app.factual.agent_pipeline import (
    NoVerifiedClaims,
    ScriptBlocked,
    ScriptRejected,
    agent_extract_claims,
    agent_verify_claim,
    agent_write_script,
)
from app.factual.grounding import script_grounding
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
    judged_story,
    latest_review,
    review_story,
    story_gate,
)
from app.integrations.services import selected_youtube
from app.integrations.vault import RECONNECT_RO, VaultUnreadable
from app.media.models import (
    EditorialReview,
    MediaAsset,
    QualityControlReport,
    Storyboard,
    VideoRenderJob,
)
from app.media.prompt_agent import (
    NEEDS_SHOT_PLAN,
    PromptError,
    ShotPlanUnusable,
    hold_for_shot_plan,
    write_shot_prompts,
)
from app.media.qc import evaluate_media_qc, rights_verdict
from app.media.serial_storyboard import describe_serial_shots
from app.media.services import generate_storyboard_from_script
from app.models import DomainEvent
from app.providers.registry import ProviderRegistry
from app.publishing.licence_release import mark_held_for_licence
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    LIVE_PUBLICATION_STATES,
    REMOTE_REJECTED_STATES,
    ROUTE_SELECTED,
    PublisherNotConfigured,
    PublishingGateError,
    channel_bindings,
    channel_type_for_storyboard,
    evaluate_publishing_gate,
    film_identity,
    publication_footer,
    publication_metadata_refusals,
    publish_media_asset,
    published_films,
    resolve_publish_visibility,
    select_channel_for,
)
from app.research.agent import (
    NoAuthorisedHosts,
    NoResearcher,
    ResearchAgentError,
    gather_sources,
    propose_topics,
)
from app.research.service import research_budget, retest_stale_hosts
from app.runbook.services import BLOCKED, safe_mode_state, stop_reason_words, stop_requested
from app.services import (
    append_event,
    may_act,
    pending_approvals,
    queue_film_continue,
    studio_environment,
    utc_now,
)
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.serial_stage import run_serial_next_stage, run_serial_stage
from app.story.services import business_date
from app.wording import (
    count,
    decimal,
    error_fields,
    error_words,
    privacy,
    publication_status,
    review_verdict,
    sentence,
)

logger = logging.getLogger("studio.runbook.stages")

#: Two counted phrases whose verb agrees with the number (`app.wording.count`).
STALLED_TOPICS = (
    "subiect selectat mai demult stă",
    "subiecte selectate mai demult stau",
)
REFUSED_RENDERS = ("randare refuzată de furnizor", "randări refuzate de furnizor")
ORPHAN_CLAIMS = (
    "afirmație verificată nu aparține",
    "afirmații verificate nu aparțin",
)

COMPLETED = "COMPLETED"
SKIPPED = "SKIPPED"

#: How many items one stage will process in a single run. A day's run should finish; a backlog of
#: two hundred sources is not a reason to hold the whole day open, and what is left is picked up
#: by tomorrow's run.
#: How many drafts of one story a single run will work through — the same number the review
#: counts to, so the room and the reading agree about when the conversation is over.
MAX_SCRIPT_EXCHANGES = MAX_EXCHANGES
#: How many times a draft its form refused (a chart without its figures, a citation that was
#: not supplied) is asked for again with the refusal in the writer's notes, per topic and day
#: (2026-10-15, 14:43Z: the first script with the right facts was dropped whole for one
#: DATA_CARD scene without its numbers). Text is free; the room is not endless.
SCRIPT_FORM_RETRIES = 2

BATCH = 5
#: Claims verified in one day. Verification is one short call per claim; extraction from
#: three pages produces thirty, and a film needs the ones about its own subject checked.
VERIFY_BATCH = 24


def _outcome(status: str, reason: str, **artefacts: Any) -> dict[str, Any]:
    return {"status": status, "reason": reason, "artefacts": artefacts}


# ------------------------------------------------------ what each stage is, in risk terms --

#: Every stage of the day as one action with one risk tier, so the Owner's autonomy mode can
#: reason about the day instead of about twelve unnamed functions. The tiers are
#: `31_GOVERNANCE_APPROVAL_POLICY`'s, and where the action is one the governance table already
#: names (`app.services.ACTION_RISK_TIERS`) the tier here is the same one — a test holds the
#: two tables to that, because two answers to "how risky is this" is worse than none.
#:
#: performance_intake — T0. 31's own T0 example is "read analytics": the stage reads the
#:   platform's numbers for films already published and writes nothing outside the studio.
#: idea_generation — T1, "create draft": a pool of topics nobody has acted on.
#: research_and_verification — T2. The studio fetches pages from the authorised sites, which
#:   is 32's EXTERNAL_READ: it leaves the studio, it is what a bot wall or a rate limit sees,
#:   and it is the first stage of the day that is not purely internal.
#: selection — T1, "change task priority": choosing which candidate goes into production
#:   re-orders the studio's own work and is undone by selecting another.
#: script_and_storyboard, serial_queue — T1, "create draft". Both write text and a shot list;
#:   nothing is bought and nothing leaves.
#: media — T2, paid generation inside the Owner's budget. Per film the stage asks again, and
#:   a film estimated above `settings.paid_generation_approval_threshold_usd` is asked as T3
#:   ("paid generation beyond threshold").
#: edit_and_qc — T1. Quality control measures a file the studio already has and writes its own
#:   report; the vision call it now makes is an agent run, which the Policy Kernel gates.
#: publish — T3. An upload is 32's EXTERNAL_WRITE whatever visibility it carries: private on
#:   the platform is still on the platform, under the studio's account, and only the channel's
#:   policy decides who may see it. Tiering it by visibility would have made the day's riskiest
#:   act depend on a setting the same day could change.
#: post_run — T1: the Director reads the day's reports and writes to the Owner, inside.
#: serial_next — T1, "create draft", as script_and_storyboard: tomorrow's episode is text, and
#:   it builds no storyboard, so nothing is bought and nothing leaves.
#:
#: preflight and daily_log have no runner and no entry: one reads the studio's own state and
#: refuses nothing by itself, the other is the run's own record of what already happened.
STAGE_ACTIONS: dict[str, tuple[str, str]] = {
    "performance_intake": ("analytics.read", "T0"),
    "idea_generation": ("idea.create", "T1"),
    "research_and_verification": ("research.fetch_page", "T2"),
    "selection": ("task.reprioritise", "T1"),
    "script_and_storyboard": ("script.draft", "T1"),
    "serial_queue": ("storyboard.draft", "T1"),
    "media": ("media.paid_generation", "T2"),
    "edit_and_qc": ("media.quality_control", "T1"),
    "publish": ("publishing.public_publish", "T3"),
    "post_run": ("runbook.day_report", "T1"),
    "serial_next": ("script.draft", "T1"),
}


def mode_refusal(
    engine: Engine,
    action: str,
    tier: str | None = None,
    *,
    requester: str = "director",
    subject: str = "",
    evidence: str | None = None,
    cost_usd: float | None = None,
    context: dict[str, Any] | None = None,
    ask_owner: bool = True,
) -> dict[str, Any] | None:
    """The Owner's autonomy mode, asked before an action — None when it does not refuse.

    `may_act` is the one door (`31`'s authority hierarchy, read top down), and under
    SUPERVISED a T3 action writes the Approval the Owner answers — or spends the answer he
    has already given about this exact `subject` — instead of being refused, so the call
    happens inside a transaction of its own.

    A STOP refusal is returned as no refusal *here* deliberately: the stop is read by the
    runbook before every stage, by the media stage before every film, by the render between
    scenes, by the publishing gate and by the Policy Kernel, and it must not come to be read
    only in this wrapper. What this asks is the question none of those ask — whether the mode
    the Owner set lets the studio attempt this at all.

    `ask_owner=False` asks the mode without putting anything in front of the Owner: a
    SUPERVISED T3 answers "he would have to be asked", nothing is written, and that is
    reported here as no refusal, because the caller that can name the film is the one that
    should do the asking. A mode that refuses outright still refuses.
    """
    with Session(engine) as session, session.begin():
        verdict = may_act(
            session,
            action,
            tier,
            requester=requester,
            subject=subject,
            evidence=evidence,
            cost_usd=cost_usd,
            context=context,
            ask_owner=ask_owner,
        )
    if verdict["allowed"] or verdict["status"] == "BLOCKED_STOP":
        return None
    if verdict["status"] == "NEEDS_APPROVAL" and not ask_owner:
        return None
    return verdict


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
            f"{count(pool, 'temă candidată este', 'teme candidate sunt')} deja în "
            "așteptare; nu s-au propus altele.",
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
        return _outcome(SKIPPED, sentence(error_words(exc)), **error_fields(exc))
    except (ResearchAgentError, NoResearcher, ValueError) as exc:
        # A refused proposal is the validation working; it must not take the day with it.
        return _outcome(
            COMPLETED,
            f"Propunerile au fost respinse: {error_words(exc)}."[:300],
            proposed=0,
            **error_fields(exc),
        )
    if proposal.get("blocked"):
        return _outcome(
            COMPLETED, f"Cercetătorul a escaladat: {proposal['blocked']}"[:300], proposed=0
        )
    stored = proposal.get("proposed", [])
    rejected = proposal.get("rejected", [])
    reason = f"{count(len(stored), 'temă propusă', 'teme propuse')} de cercetător."
    if rejected:
        reason += (
            f" {count(len(rejected), 'respinsă', 'respinse')} (duplicat sau site neautorizat)."
        )
    return _outcome(COMPLETED, reason, proposed=[t["title"] for t in stored], rejected=rejected)


# ------------------------------------------------------------------ performance intake --


def _performance_intake(engine: Engine, vault: Any) -> dict[str, Any]:
    """Measure the videos the platform is actually serving, channel by channel.

    Only a publication with a remote video id has an audience to measure. A simulated one has
    none, and asking an analytics API about an internal row id would produce numbers about
    nothing.

    Each slot is measured through its own bound account and its own publications. It used
    to be one adapter, built from the first bound slot, for every publication in the studio:
    with two channels bound, the serial's retention was asked of the main channel's account
    and answered with a straight face. A slot without a usable binding is named in the
    outcome and never measured through another slot's account — attributing one channel's
    numbers to another is worse than measuring nothing.
    """
    with Session(engine) as session:
        slots = [
            (channel.id, channel.channel_name)
            for channel in session.scalars(
                select(ChannelRecord)
                .where(ChannelRecord.platform == "YOUTUBE")
                .order_by(ChannelRecord.created_at)
            )
        ]

    measured, unavailable = 0, []
    channels: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for channel_id, channel_name in slots:
        try:
            provider, reason = analytics_provider_for_channel(engine, vault, channel_id)
        except VaultUnreadable as exc:
            # Statistics are optional: unavailable credentials produce no measurements.
            # The daily preflight still blocks work that requires the vault.
            skipped[channel_id] = f"{exc.reason_ro}; {RECONNECT_RO}."
            continue
        if provider is None:
            skipped[channel_id] = reason
            continue
        result = measure_channel_publications(engine, channel_id, provider, limit=BATCH)
        channels[channel_id] = {
            "channel_name": channel_name,
            "candidates": result["candidates"],
            "measured": result["measured"],
            "unavailable": len(result["unavailable"]),
        }
        measured += result["measured"]
        unavailable.extend(result["unavailable"])

    if not channels:
        detail = " ".join(skipped.values())[:300]
        return _outcome(
            SKIPPED,
            "Niciun cont YouTube utilizabil pentru analytics. Verifică legătura contului în "
            "Distribuție → Sloturi de canal și accesul la cheile conexiunilor în Setări."
            + (f" ({detail})" if detail else ""),
            skipped=skipped,
        )
    if not sum(entry["candidates"] for entry in channels.values()):
        return _outcome(
            COMPLETED,
            "Nicio publicare reală de măsurat.",
            measured=0,
            channels=channels,
            skipped=skipped,
        )
    reason = (
        f"{count(measured, 'publicare măsurată', 'publicări măsurate')} pe "
        f"{count(len(channels), 'canal', 'canale')}."
    )
    if unavailable:
        reason += f" {len(unavailable)} fără date."
    if skipped:
        reason += (
            f" {count(len(skipped), 'slot nemăsurat', 'sloturi nemăsurate')} (cont indisponibil)."
        )
    return _outcome(
        COMPLETED,
        reason,
        measured=measured,
        unavailable=unavailable,
        channels=channels,
        skipped=skipped,
    )


# ------------------------------------------------------- research and verification --


#: The body key of the Director's note that a topic's script was blocked on what research
#: gave it; sources fetched before the note are spent, the topic is read for again.
SCRIPT_BLOCKED_KEY = "script_blocked"


_CHART_WORDS = ("data_card", "chart", "grafic", "bar", "numeric", "value and unit", "cifr")


def _stop_is_about_a_chart(blocker: Any) -> bool:
    """Whether the writer stopped over a chart's missing figures rather than a missing fact:
    then the scene is LIVE and the claims stand (15:51Z, d7d80450)."""
    said = " ".join(str(getattr(blocker, key, "") or "") for key in ("reason", "needs")).lower()
    return any(word in said for word in _CHART_WORDS)


#: How many times in one day research is sent back for a topic whose writer stopped on its
#: facts before the topic is left for another (`_topic_back_to_research`). 2026-10-15,
#: d7d80450 «The Supernova Surprise»: three stops (14:17Z, 15:51Z, 17:41Z) — the pages read
#: never carried the thesis in words the verifier could hold — and every run of the day went
#: to the same topic while seven candidates waited.
TOPIC_RESEARCH_RETURNS = 1


def _stops_today(session: Session, topic_id: str) -> int:
    """How many times today the writer stopped on this topic's facts (the Director's notes)."""
    today = utc_now()[:10]
    count = 0
    for message in session.scalars(
        select(AgentMessage).where(
            AgentMessage.intent == "STATUS", AgentMessage.created_at >= today
        )
    ):
        body = message.body_json if isinstance(message.body_json, dict) else {}
        if body.get(SCRIPT_BLOCKED_KEY) and str(body.get("topic_id") or "") == topic_id:
            count += 1
    return count


def _topic_back_to_research(engine: Engine, topic_id: str, blocker: Any) -> None:
    """A SELECTED topic whose writer stopped is PROPOSED again, with his reason noted to the
    Director: `_gather_for_candidates` reads for it again (the note is newer than its
    sources), verification and selection follow, and the writer sees new claims. After
    `TOPIC_RESEARCH_RETURNS` such returns in a day the topic is left (REJECTED, with why):
    the day's next run selects another candidate instead of reading for this one again."""
    from app.agents.messages import post_message  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        topic = session.get(TopicIdea, topic_id)
        if topic is None:
            return
        stops_before = _stops_today(session, topic_id)
        left = stops_before >= TOPIC_RESEARCH_RETURNS
        if left:
            topic.status = "REJECTED"
            topic.decided_by = "scenaristul, după cercetare"
            topic.decision_notes = (
                f"Lăsat {utc_now()[:10]}: scenaristul s-a oprit de {stops_before + 1} ori pe "
                f"faptele lui ({' '.join(str(getattr(blocker, 'reason', '') or '').split())[:300]})"
            )[:2000]
            topic.rejection_reasons_json = [
                *list(topic.rejection_reasons_json or []),
                f"{stops_before + 1} opriri ale scenaristului pe fapte",
            ]
        elif topic.status == "SELECTED":
            topic.status = "PROPOSED"
        # The claims he could not write from are retired with him: a SUPPORTED claim stays
        # what the writer is handed (`script_agent.write_script`), and the Supernova topic's
        # 37 «SUPPORTED» claims were about Discovery Channel, a Daft Punk album and a ship
        # (2026-10-15 14:03Z: pages fetched for the word «Discovery»). The new pages bring
        # new claims; these are UNCERTAIN, with why.
        retired = 0
        for claim in session.scalars(
            select(FactualClaim).where(
                FactualClaim.topic_id == topic_id, FactualClaim.status == "SUPPORTED"
            )
        ):
            claim.status = "UNCERTAIN"
            claim.verifier_notes = (
                "retrasă: scenaristul nu a putut scrie din aceste afirmații ("
                + " ".join(str(getattr(blocker, "reason", "") or "").split())[:160]
                + ")"
            )[:500]
            retired += 1
        director = agent_for_role(session, "Director")
        post_message(
            session,
            intent="STATUS",
            subject=(
                f"Scenaristul s-a oprit la «{topic.title[:80]}»: "
                + (
                    "subiectul se lasă, se alege altul"
                    if left
                    else "subiectul merge înapoi la cercetare"
                )
            ),
            body={
                "topic_id": topic_id,
                SCRIPT_BLOCKED_KEY: str(getattr(blocker, "reason", "") or "")[:1000],
                "needs": str(getattr(blocker, "needs", "") or "")[:1000],
            },
            body_text=(
                f"Scenaristul nu a putut scrie «{topic.title}» cinstit: "
                f"{getattr(blocker, 'reason', '')}\n"
                + (f"Are nevoie de: {blocker.needs}\n" if getattr(blocker, "needs", "") else "")
                + (
                    f"Subiectul se lasă: de {stops_before + 1} ori azi cercetarea nu i-a adus "
                    f"faptele; {retired} afirmații sunt retrase, iar alegerea subiectului "
                    "trece la alt candidat la următoarea rulare."
                    if left
                    else f"Subiectul e din nou PROPUS, {retired} afirmații de dinainte sunt "
                    "retrase; cercetarea citește alte pagini pentru el la următoarea trecere, "
                    "apoi verificarea și alegerea subiectului."
                )
            ),
            to_agent_id=director.id if director else None,
        )


def _sent_back_after(session: Session) -> dict[str, str]:
    """topic_id → when its script was last blocked (the Director's note), if ever."""
    sent_back: dict[str, str] = {}
    for message in session.scalars(select(AgentMessage).where(AgentMessage.intent == "STATUS")):
        body = message.body_json if isinstance(message.body_json, dict) else {}
        if body.get(SCRIPT_BLOCKED_KEY) and body.get("topic_id"):
            topic_id = str(body["topic_id"])
            sent_back[topic_id] = max(sent_back.get(topic_id, ""), str(message.created_at))
    return sent_back


def _gather_for_candidates(
    engine: Engine, registry: ProviderRegistry, settings: Settings
) -> list[dict[str, Any]]:
    """Fetch pages for the best candidates that have none yet (runbook §4, retrieval half).

    Bounded to the Owner's `research_candidates_per_day` candidates, `research_pages_per_topic`
    pages each (`research_budget`, four and four, clamped 1..12): the point is to give
    verification something real to read, not to crawl. Two candidates of three pages was the
    old literal, and on a day when both plans guessed addresses that 404'd it left the studio
    with nothing. Every page is downloaded by the studio itself.
    """
    candidates_per_day, pages_per_topic = research_budget(settings)
    with Session(engine) as session:
        # A topic whose writer stopped on what its sources gave him is read for again:
        # the pages fetched before the Director's note are spent (`_topic_back_to_research`).
        sent_back = _sent_back_after(session)
        with_sources = {
            row.topic_id
            for row in session.scalars(select(SourceSnapshot))
            if row.topic_id is not None
            and str(row.fetched_at) >= sent_back.get(str(row.topic_id), "")
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
            if len(candidates) == candidates_per_day:
                break
    gathered = []
    for topic_id in candidates:
        try:
            gathered.append(
                gather_sources(
                    engine, registry, settings, topic_id, str(uuid4()), limit=pages_per_topic
                )
            )
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

    # Before the day reads anything, the sites it is allowed to read are re-tested — but only
    # the ones nobody has tested for a week. A site readable seven days ago may have grown a
    # bot wall since, and one that failed may have dropped it; on the other six days the pass
    # fetches nothing and costs the sites nothing, so it needs no scheduled job of its own.
    # Each test also looks again for the site's own search address, which is what keeps the
    # Researcher from guessing addresses that 404. A retest that fails is the retest's loss,
    # never the day's (Phase A's rule): the hosts it did reach are recorded before it stops.
    # Reading a page is what leaves the studio here (32's EXTERNAL_READ), so the mode is
    # asked before the first request and not after the pages are in the record. A studio the
    # Owner has put in MANUAL still extracts and verifies what it already holds — that is
    # internal work, and the stage below does it — but it fetches nothing new.
    may_fetch = mode_refusal(engine, "research.fetch_page", requester="lead_researcher")

    retested: list[dict[str, Any]] = []
    if settings is not None and may_fetch is None:
        try:
            retested = retest_stale_hosts(engine, settings, correlation_id=str(uuid4()))
        except Exception as exc:  # noqa: BLE001 - a site that cannot be reached is not a fault
            logger.info("host_retest_incomplete", extra={"reason": type(exc).__name__})

    # The studio reads for itself before it reads what it was given: a candidate topic with no
    # source can never be verified, and waiting for the Owner to paste a link is not research.
    gathered = (
        _gather_for_candidates(engine, registry, settings) if settings and may_fetch is None else []
    )
    pages = sum(len(item["fetched"]) for item in gathered)

    with Session(engine) as session:
        # A source nobody has extracted from yet, the newest first. It used to be looked for
        # among the first 50 rows of the table, in no order: past 50 sources, a page read for
        # a new topic was never extracted (found on the Owner's copy, 2026-10-02).
        has_claims = select(FactualClaim.id).where(FactualClaim.source_id == SourceSnapshot.id)
        pending_sources = list(
            session.scalars(
                select(SourceSnapshot.id)
                .where(~has_claims.exists())
                .order_by(SourceSnapshot.fetched_at.desc())
                .limit(BATCH)
            )
        )

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
        # day verifies up to VERIFY_BATCH, the ones the film depends on first, and of those
        # the newest first: a claim the Fact Checker refused stays UNVERIFIED, and taking the
        # oldest first re-read the same refused backlog every day while a new topic's claims
        # never reached her (61 such claims on the Owner's copy, 2026-10-02).
        rank = {"CRITICAL": 0, "SUPPORTING": 1, "FLAVOR": 2}
        pending = session.scalars(
            select(FactualClaim)
            .where(FactualClaim.status == "UNVERIFIED", FactualClaim.source_id.is_not(None))
            .order_by(FactualClaim.created_at.desc())
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

    retest_line = ""
    if retested:
        passed = len([r for r in retested if r["status"] == "PASSED"])
        retest_line = (
            f" {count(len(retested), 'site retestat', 'site-uri retestate')} "
            f"({passed} {'citibil' if passed == 1 else 'citibile'})."
        )
    if may_fetch is not None:
        # Said in the stage's own line, because a day that verified what it held and fetched
        # nothing new looks the same from the outside as a day that found nothing to read.
        retest_line += f" Nicio pagină nouă: {may_fetch['reason']}"
    if not pending_sources and not unverified and not pages:
        return _outcome(
            COMPLETED,
            "Nicio sursă nouă și nicio afirmație neverificată." + retest_line,
            claims=0,
            hosts_retested=len(retested),
        )
    reason = (
        f"{count(pages, 'pagină preluată', 'pagini preluate')}, "
        f"{count(extracted, 'sursă citită', 'surse citite')}, "
        f"{count(verified, 'afirmație verificată', 'afirmații verificate')}, "
        f"{count(refused, 'verdict respins', 'verdicte respinse')}."
        + (f" {count(unreadable, 'sursă', 'surse')} fără afirmații citibile." if unreadable else "")
        + retest_line
    )
    return _outcome(
        COMPLETED,
        reason,
        pages_fetched=pages,
        sources_read=extracted,
        claims_verified=verified,
        verdicts_refused=refused,
        hosts_retested=len(retested),
    )


# ------------------------------------------------------------------------- selection --


#: How long a film that passed quality control may wait to be published before its topic
#: stops holding the next choice (2026-10-15): a film the Publisher holds, the gate refuses
#: or the Owner never answers for kept its topic «live» for ever, and no new topic was chosen.
#: The film stays a candidate for publication; only the selection stops waiting for it.
PUBLISH_WAIT_DAYS = 3


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
    rejected = _viewing_rejected(session)
    live: list[str] = []
    stalled: list[str] = []
    for topic in selected:
        script = scripts.get(topic.id)
        board = boards.get(script.id) if script else None
        last = jobs.get(board.id) if board else None
        if (
            board is not None
            and board.status == "REJECTED"
            and (last is None or last.output_asset_id not in published)
        ):
            # Closed by the Director (a film she retired after it stood still, or a viewing
            # she refused): nothing more is owed on it, and the topic must not hold the
            # studio. It used to count as in production until a render COMPLETED (A4).
            stalled.append(topic.id)
            continue
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
            finished = str(last.finished_at or last.started_at or "")
            waited_days = (
                (datetime.now(UTC) - datetime.fromisoformat(finished)).days if finished else 0
            )
            if waited_days >= PUBLISH_WAIT_DAYS:
                stalled.append(topic.id)  # held or refused this long: it no longer holds the day
            else:
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
                    f" ({count(len(stalled), *STALLED_TOPICS)} cu randări picate la QC.)"
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
            reason += f" Ales de Director: {notes}"
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
            f" {count(orphan_supported, *ORPHAN_CLAIMS)} niciunui subiect: sursele au fost "
            "ingerate fără subiect."
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
        if ((latest.story_json or {}).get("editorial") or {}).get("superseded_by"):
            # The Director's editorial judgement shipped an earlier version of this topic
            # (2026-10-11): this later, lower-scored draft owes the room nothing.
            continue
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


def _script_awaiting_owner(session: Session) -> str | None:
    """A script only the Owner can move on: the newest draft of its topic, not yet
    storyboarded, VERIFIED_PASS, and passed by the story review (so the Director would have
    approved it, and did not - her approval re-checks the grounding). A draft the review sent
    back or refused, or one a newer draft superseded, waits for nobody: on the Owner's copy 28
    such drafts made every day say «Un scenariu așteaptă aprobarea ta» (2026-10-02)."""
    newest: dict[str, ScriptDraft] = {}
    for draft in session.scalars(select(ScriptDraft).order_by(ScriptDraft.created_at)):
        if draft.topic_id:
            newest[draft.topic_id] = draft
    storyboarded = set(session.scalars(select(Storyboard.script_draft_id)))
    for draft in newest.values():
        if draft.status != "VERIFIED_PASS" or draft.id in storyboarded:
            continue
        if ((draft.story_json or {}).get("editorial") or {}).get("superseded_by"):
            continue  # the judgement shipped an earlier version; this one waits for nobody
        review = latest_review(session, draft.id)
        if review is not None and review.verdict == "PASS":
            return draft.id
    return None


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
        # The factual gate asks whether the cited claims exist and are SUPPORTED; this asks
        # whether the narration says them. On the rehearsal of 2026-09-18 only the first was
        # asked, and a telescope film on the Nepal topic was approved. A PASS from a review
        # that measured it has already answered; the measurement is repeated because it costs
        # nothing and her approval must never rest on a review that did not take it.
        grounding = script_grounding(session, session.get(ScriptDraft, script_id))
    if grounding is not None and not grounding["passed"]:
        logger.info(
            "script_approval_refused",
            extra={"script_id": script_id, "reason": " ".join(grounding["reasons"])},
        )
        return None
    try:
        approve_script_draft(
            engine,
            script_id,
            str(uuid4()),
            approved_by=director_id,
            # A PASS means no check was broken, so there is nothing to enumerate here: what the
            # record needs is who decided and on what reading, and the review itself holds the
            # scores and the notes behind that reading.
            reason=(
                "Recenzia Directorului: trecută. Povestea a trecut toate verificările editoriale."
            ),
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
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Draft the voiceover for the selected topic, and storyboard what has been approved.

    A film still waiting for its shot plan (NEEDS_SHOT_PLAN), or one the prompt lint held, is
    asked of the model again here, once a business day until usable (`_reask_shot_plans`):
    text only, no media credit (A4).

    The draft stops at VERIFIED_PASS until the Director has read it: a PASS from her story
    review approves it (`_director_approves`), a rewrite follows her notes for up to
    `MAX_SCRIPT_EXCHANGES` exchanges, and a REJECT closes the room for that topic. Storyboarding
    requires an APPROVED script — so a run never approves its own writing, only what the
    Director has passed, and the Owner may still refuse what she allowed.
    """
    if not _has_language_model(registry):
        return _outcome(SKIPPED, "Niciun model de limbaj disponibil; agenții nu pot rula.")

    drafted, rejected = 0, []
    form_retries = 0
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
        form_refusals = 0  # refusals of the draft's form this topic had (`SCRIPT_FORM_RETRIES`)
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
                script_id = str(written["script"]["id"])
                review = review_story(engine, registry, script_id, target_seconds=target_seconds)
                reviews.append(
                    {
                        "verdict": review["verdict"],
                        "failed": review["failed"][:4],
                        "exchange": attempt,
                    }
                )
                if review["verdict"] == "PASS":
                    # Her editorial judgement (2026-10-11): would a stranger watch it to the
                    # end? Below her bar the writer rewrites on her brief, up to
                    # `editorial_rounds` versions, and the best-scored one is what she
                    # approves below — this draft or a later one.
                    judged = judged_story(
                        engine,
                        registry,
                        script_id,
                        target_seconds=target_seconds,
                        language=language,
                        rounds=getattr(settings, "editorial_rounds", None),
                        review=review,
                    )
                    script_id, review = judged["script_id"], judged["review"]
                    drafted += judged["rewrites"]
                    reviews[-1]["editorial"] = judged["editorial"]["shipped"]
                decided = _director_approves(engine, script_id, review)
                if decided:
                    approvals.append(decided)
                    break  # she approved it; the camera is next
                if review["verdict"] == "REJECT":
                    break  # the budget is spent or the story is unsupportable; let it go
                notes = list(review["notes"])
            except ScriptBlocked as exc:
                # The writer's honest stop: what he was given cannot be written. The topic
                # goes back to research with his reason, through the Director, and the day
                # goes on (2026-10-15, «The Supernova Surprise» on claims about «Discovery»).
                logger.info("script_blocked", extra={"topic_id": topic_id, "reason": str(exc)})
                if _stop_is_about_a_chart(exc.blocker):
                    # 15:51Z, d7d80450: four claims verified, the story passed, and he stopped
                    # because scene 3's chart had no figures — a form matter, not a fact the
                    # story lacks. The scene is written LIVE; his claims are not retired.
                    form_refusals += 1
                    if form_refusals <= SCRIPT_FORM_RETRIES and attempt < MAX_SCRIPT_EXCHANGES:
                        form_retries += 1
                        notes = [
                            *notes,
                            "Nu te opri pentru lipsa unei cifre: "
                            + " ".join(str(exc.blocker.reason or "").split())[:300]
                            + " Scena fără cifre verificate se scrie LIVE (ce se vede), fără "
                            "grafic; un grafic (DATA_CARD) există doar când fiecare bară are "
                            "valoarea, unitatea și afirmația ei. Blocker-ul este numai pentru "
                            "fapte pe care povestea nu le are deloc.",
                        ]
                        continue
                    # His retries spent on the same chart: the topic is refused today with
                    # his words, its claims untouched — the next run writes from them again.
                    rejected.append(
                        "scenaristul s-a oprit pentru un grafic fără cifre, deși scena se "
                        "scria LIVE: "
                        + " ".join(str(getattr(exc.blocker, "reason", "") or "").split())[:200]
                    )
                    break
                # His own words, not «o eroare neașteptată în codul studioului» (14:03Z).
                rejected.append(
                    "scenaristul s-a oprit cinstit, subiectul merge înapoi la cercetare: "
                    + " ".join(str(getattr(exc.blocker, "reason", "") or str(exc)).split())[:200]
                )
                _topic_back_to_research(engine, topic_id, exc.blocker)
                break
            except ScriptRejected as exc:
                # The draft was refused by its form and nothing was stored (a chart without
                # its figures, a citation that was not supplied). Until 2026-10-15 the room
                # closed on it; 14:43Z, d7d80450: the first script a writer with the right
                # facts wrote was dropped whole for one DATA_CARD scene without its numbers.
                # Text is free: the writer is asked again with the refusal, within the
                # exchanges the room allows (the Owner: «publicăm ce avem»).
                logger.info("script_rejected", extra={"topic_id": topic_id, "reason": str(exc)})
                form_refusals += 1
                if form_refusals <= SCRIPT_FORM_RETRIES and attempt < MAX_SCRIPT_EXCHANGES:
                    form_retries += 1
                    notes = [
                        *notes,
                        f"Forma a refuzat ciorna: {str(exc)[:400]} Dă fiecărei bare a unui "
                        "grafic valoarea, unitatea și afirmația verificată din care vine, sau "
                        "fă scena una filmată (LIVE) fără grafic.",
                    ]
                    continue
                rejected.append(str(exc)[:300])
                break
            except NoVerifiedClaims as exc:
                # No SUPPORTED claim at all: nothing truthful to write from; the room closes
                # for this topic and the day goes on.
                logger.info("script_rejected", extra={"topic_id": topic_id, "reason": str(exc)})
                rejected.append(error_words(exc))
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
    boards_written: set[str] = set()
    # Films whose shot plan could not be read even after the one re-ask. They wait as
    # NEEDS_SHOT_PLAN and are named in the day's outcome: the Nepal film's plan was lost to a
    # log line nobody read, and template prompts were bought in its place (2026-09-26).
    waiting_plan: list[str] = []
    # Scripts the storyboard's Content Gate refused: a card whose numbers no SUPPORTED claim
    # carries, or a claim refuted since. Named in the day's outcome; the day goes on.
    gated: list[str] = []
    for script_id in approved:
        try:
            # No style is named: each scene carries its own kind (SCENE_KINDS). The Nepal film
            # got one motion-graphic style for all six scenes, chart and black screen included.
            board = generate_storyboard_from_script(engine, script_id, None, "9:16", str(uuid4()))
        except FactualGateError as exc:
            logger.info("storyboard_gated", extra={"script_id": script_id, "reason": str(exc)})
            gated.append(f"{script_id[:8]}: {exc}")
            continue
        boards += 1
        boards_written.add(str(board["id"]))
        # One look for the whole film, then a full prompt package per shot. This is where a
        # story becomes instructions a camera would understand — the step the studio did not
        # have when it sent "a spinning galaxy" to a model at 2.60 USD a shot.
        try:
            written = write_shot_prompts(engine, registry, board["id"], str(uuid4()))
            prompted += len(written["shots"])
        except ShotPlanUnusable as exc:
            logger.warning("shot_plan_unusable", extra={"storyboard_id": board["id"]})
            waiting_plan.append(f"{str(board['id'])[:8]}: {exc}")
        except PromptError as exc:
            logger.info("shot_prompts_skipped", extra={"reason": str(exc)[:160]})

    # The films left without a plan on an earlier day, asked again (never one written now).
    reasked = _reask_shot_plans(engine, registry, settings, written_now=boards_written)

    with Session(engine) as session:
        awaiting = _script_awaiting_owner(session)

    reason = (
        f"{count(drafted, 'scenariu scris', 'scenarii scrise')} în "
        f"{count(len(reviews), 'schimb', 'schimburi')}, "
        f"{len(approvals)} {'aprobat' if len(approvals) == 1 else 'aprobate'} de Director, "
        f"{count(boards, 'storyboard generat', 'storyboarduri generate')}."
    )
    if prompted:
        reason += f" {count(prompted, 'cadru descris', 'cadre descrise')} complet."
    if waiting_plan:
        reason += (
            f" {count(len(waiting_plan), 'film așteaptă', 'filme așteaptă')} planul de cadre: "
            f"{waiting_plan[0][:160]}"
        )
    if reasked["asked"]:
        reason += (
            f" Planul de cadre cerut din nou modelului pentru "
            f"{count(len(reasked['asked']), 'film', 'filme')}: "
            f"{count(len(reasked['written']), 'scris', 'scrise')}."
        )
    if gated:
        reason += (
            f" {count(len(gated), 'storyboard oprit', 'storyboarduri oprite')} la poarta de "
            f"conținut: {gated[0][:200]}"
        )
    if reviews:
        reason += (
            " Recenzia poveștii: " + ", ".join(review_verdict(r["verdict"]) for r in reviews) + "."
        )
    if rejected:
        reason += f" {count(len(rejected), 'respins', 'respinse')}: {rejected[0][:120]}"
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
        form_retries=form_retries,
        awaiting_approval=bool(awaiting),
        waiting_shot_plan=waiting_plan,
        storyboards_gated=gated,
        shot_plans_reasked=reasked["asked"],
        shot_plans_rewritten=reasked["written"],
    )


def _reask_shot_plans(
    engine: Engine,
    registry: ProviderRegistry,
    settings: Settings | None,
    *,
    written_now: set[str],
) -> dict[str, list[str]]:
    """Ask the model again for the shot plan of each factual film that is waiting for one.

    A NEEDS_SHOT_PLAN storyboard, or an APPROVED one whose last recorded day was a lint BLOCK,
    is asked again once a business day until usable, counted by
    the day's own events: text only, no media credit. Only the POST /prompts route asked again
    before, so a plan the model lost stayed lost. A film holding a bought take is never asked:
    new prompts are new still identities, and a still bought for the old words would be bought
    again; that film waits for the Owner, and is retired if it stands still too long.
    """
    from app.media.models import SceneTake  # noqa: PLC0415

    timezone = str(getattr(settings, "timezone", None) or Settings.model_fields["timezone"].default)
    today = business_date(timezone)
    asked: list[str] = []
    written: list[str] = []
    with Session(engine) as session:
        rendered = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(VideoRenderJob.status == "COMPLETED")
            )
        )
        bought = set(
            session.scalars(
                select(SceneTake.storyboard_id).where(SceneTake.status.in_(BOUGHT_TAKE_STATUSES))
            )
        )
        candidates: list[str] = []
        for board in session.scalars(
            select(Storyboard)
            .where(Storyboard.status.in_((NEEDS_SHOT_PLAN, "APPROVED")))
            .order_by(Storyboard.created_at)
        ):
            if (
                board.id in rendered
                or board.id in written_now
                or board.id in bought
                or is_serial_storyboard(board)
            ):
                continue
            if board.status == "APPROVED":
                _since, last = _stood_since(session, board.id)
                if last.get("refusal") != "LINT_BLOCKED":
                    continue
            days = {
                str((event.payload or {}).get("business_date"))
                for event in session.scalars(
                    select(DomainEvent).where(
                        DomainEvent.event_type == SHOT_PLAN_REASKED_EVENT,
                        DomainEvent.aggregate_id == board.id,
                    )
                )
            }
            if today in days:
                continue
            candidates.append(board.id)
    for storyboard_id in candidates:
        correlation = str(uuid4())
        outcome = "WRITTEN"
        try:
            write_shot_prompts(engine, registry, storyboard_id, correlation)
            written.append(storyboard_id)
        except ShotPlanUnusable:
            outcome = "UNUSABLE"
        except PromptError as exc:
            outcome = "REFUSED"
            logger.info("shot_plan_reask_refused", extra={"reason": str(exc)[:160]})
        asked.append(storyboard_id)
        with Session(engine) as session, session.begin():
            append_event(
                session,
                SHOT_PLAN_REASKED_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {"business_date": today, "outcome": outcome},
                correlation,
            )
    return {"asked": asked, "written": written}


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


def is_serial_storyboard(board: Storyboard) -> bool:
    """Whether a storyboard was produced for the office serial (Channel B).

    Read from the same series-key mapping the publish routing uses, so the film the media
    stage calls the serial's is the film the publish stage sends to the serial's channel.
    """
    return channel_type_for_storyboard(board) == "OFFICE_SERIAL"


def serial_films_due(session: Session, boards: list[Storyboard], today: str) -> list[str]:
    """The serial storyboards the media stage may film ``today``, in the order given.

    A serial episode is filmed only once the day it tells is over. The serial stage takes
    only closed days before today and tomorrow's script builds no storyboard, but the
    Owner's approve button builds one at once (since 2026-09-24): an episode of today he
    approved in the afternoon would otherwise be filmed by a same-day re-run, before the day
    it tells has ended. A storyboard no episode points to is not held.
    """
    ids = [board.id for board in boards]
    told_on = {
        storyboard_id: date
        for storyboard_id, date in session.execute(
            select(StoryEpisode.storyboard_id, DailyStudioLog.business_date)
            .join(DailyStudioLog, DailyStudioLog.id == StoryEpisode.log_id)
            .where(StoryEpisode.storyboard_id.in_(ids))
        )
    }
    return [
        board.id
        for board in boards
        if is_serial_storyboard(board) and (told_on.get(board.id) or "") < today
    ]


def _release(engine: Engine, reservation_id: str | None, reason: str, correlation: str) -> None:
    """Let a film's hold go, for every path on which the film was not made.

    Releasing, never settling: a settlement says the real cost rows are in the books, and a
    film that was not made has none. A failure here is logged and swallowed — the watchdog
    releases what the day left behind (`release_stale_reservations`), so a second fault must
    not take the stage down on top of the first.
    """
    if not reservation_id:
        return
    try:
        release_reservation(engine, reservation_id, reason, correlation_id=correlation)
    except (EconomyError, ValueError):
        logger.info("reservation_not_released", extra={"reservation_id": reservation_id})


def _record_failed_attempt(engine: Engine, storyboard_id: str, correlation: str) -> int:
    """Charge the studio for what an interrupted render bought, and return the rows written.

    The error the assembler raises does not carry the job id, so the job is found by its
    storyboard and its FAILED status — the newest, because a storyboard may have been tried
    before. What was attempted is read from the job's own record: the assembler writes
    `production_json` on every path that ends a render, so the job carries the scenes whose
    narration was recorded and whose shots were generated, and never the plan. A job that
    failed before it made anything records nothing, and that is the honest answer — nothing
    is reconstructed here from a plan the vendor may never have executed. Nothing can charge
    twice either: the rows are referenced by job and scene.
    """
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status == "FAILED",
            )
            .order_by(VideoRenderJob.started_at.desc())
        )
        job_id = job.id if job is not None else None
    if job_id is None:
        return 0
    try:
        charged = record_failed_render_cost(engine, job_id, correlation_id=correlation)
        return int(charged["recorded"])
    except (AccountantError, EconomyError, ValueError):
        logger.info("failed_render_cost_not_recorded", extra={"storyboard_id": storyboard_id})
        return 0


# ------------------------------------------------- the staircase, in PRODUCTION --
#
# The Nepal film (2026-09-26) was bought twice, whole, from a path that showed no price, no
# prompt and no model and asked nothing. In PRODUCTION the daily run no longer buys a film in
# one piece: it builds the film's shooting sheet (0 credits; one free balance read) and hands
# the first stair that has something to buy (stills, then the hero test shot, then the rest of
# the motion) to `shooting_sheet.run_sheet_step`. That step asks the Owner, under his
# `paid_media_approval` (EVERY_PAID_STEP by default, read inside `may_act` in every mode,
# AUTONOMOUS_CEO included), and buys only once his yes for THIS sheet's hash is spent. The day
# then writes him the sheet and a letter and goes on; it never waits inside the stage, and it
# never buys a second stair on the first one's yes. A film with nothing left to buy is
# assembled from its takes, which buys nothing but its narration.

#: The Owner's words for each paid stair of the shooting sheet.
STEP_WORDS: dict[str, str] = {
    "stills": "imaginile",
    "test_shot": "cadrul de probă",
    "motion": "restul mișcării",
}
#: The kind of the letter that carries a film's sheet to the Owner.
SHEET_LETTER_KIND = "owner_shooting_sheet"
#: A step refused for a reason only the Owner can lift: his look at the hero take (needed only
#: when its clip QC did not pass or his paid-media rule asks him: under MODE, or OVER_USD with
#: the motion's cap within his amount, a passing hero is accepted by its clip QC and the motion
#: is bought in the same run, HERO_AUTO_ACCEPT), money on the account, a budget, a scene the
#: gate handed to him. The film WAITS for him; it is not held for a fault of its own (a stale
#: plan, a lint BLOCK, prompts no model wrote).
OWNER_DECIDES = frozenset(
    {
        "HERO_NOT_APPROVED",
        "HERO_FIRST",
        "LOW_BALANCE",
        "OVER_DAILY_BUDGET",
        "OVER_BUDGET",
        # A locked character with no reference picture: only he produces the reference set.
        "NEEDS_REFERENCE",
        # The film's own ceiling (PRODUCTION), and unasked buying with no daily budget
        # (2026-10-02, MONEY-07 / MONEY-06): his figure, or his consent on the sheet.
        "OVER_FILM_BUDGET",
        "BLOCKED_NO_BUDGET",
        # Another buyer (his own press on the sheet) holds the film's purchase lease: the
        # film waits for that purchase to end; nothing is bought twice.
        "FILM_BUSY",
        # The media disk has less free space than his minimum (REL-08): only room made on
        # the disk, or a media folder moved to a bigger one, lets the step start.
        "LOW_DISK",
        # His mode refuses the unasked step (2026-10-04: lowered while the day ran, the
        # stair is refused before the balance is read): his mode, his decision.
        "BLOCKED_MODE",
    }
)


def sheet_wiring(engine: Engine, vault: Any, settings: Settings) -> dict[str, Any]:
    """What the day's sheets and steps are built from: the Runway connection the Owner
    selected and verified, its catalogue, its balance and its adapters (the same wiring the
    shooting-sheet routes use). Building any of it opens no connection."""
    from app.media.factory import image_provider  # noqa: PLC0415 - media imports runbook
    from app.media.shooting_sheet import (  # noqa: PLC0415
        connection_account,
        connection_capabilities,
        connection_video_adapters,
        runway_connection_id,
    )

    integration_id = runway_connection_id(engine)
    return {
        "integration_id": integration_id,
        "capabilities": connection_capabilities(engine, integration_id),
        "image_adapter": image_provider(engine, vault),
        "account": connection_account(engine, vault, integration_id),
        "adapter_for_model": connection_video_adapters(engine, vault, integration_id),
        "resolution": getattr(settings, "motion_resolution", None),
        # The Owner's STUDIO_MEDIA_ROOT, or None for the studio's own folder (REL-08).
        "storage_root": getattr(settings, "media_root", None),
    }


def _credits_words(value: float | int | None) -> str:
    """«36 de credite», «10.000 de credite»: counted the Romanian way, grouped by dots."""
    number = round(float(value or 0))
    words = count(number, "credit", "credite")
    return f"{number:,}".replace(",", ".") + words[len(str(number)) :]


def _usd_words(micros: int | float | None) -> str:
    """«7,16 USD»: dollars with a decimal comma."""
    return f"{decimal(float(micros or 0) / 1_000_000)} USD"


def _film_staircase(
    engine: Engine,
    settings: Settings,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    wiring: dict[str, Any],
    environment: str,
    correlation: str,
) -> dict[str, Any]:
    """Walk one film up its staircase as far as the Owner's answers allow, and no further.

    Returns ``status``: ASKED (his question waits), WAITING (only he can move it on: his
    look at the hero take, money on the account, a budget, scenes a bought stair left for
    him, a locked character's reference picture), HELD (a step refused for the film's own
    fault before anything was asked or bought: a stale plan, a lint BLOCK, prompts no model
    wrote, his own no) or READY (nothing is left to buy: the film is assembled from its
    takes). ``bought`` lists every stair bought here, each already in the books
    (`run_sheet_step` books what a step spent) before the next stair's budget check reads
    them.

    Before any stair is priced, what was already paid for and not settled is settled
    (`recover_paid_takes`: collected by task id, judged, clip-checked; nothing bought). A
    stair whose scenes a bought stair left to the Owner is not run again until he decides
    (2026-10-02, A2): those scenes are held out of every purchase (`scene_memory`), and the
    film waits for him instead of buying the rest of that stair without his answer.

    The whole walk holds the film's purchase lease (holder: the day's correlation id), so the
    Owner's press on the sheet and the day never buy for one film at the same time (MONEY-04);
    a film whose lease someone else holds WAITs (FILM_BUSY) and nothing of it is bought.

    A walk that stops on scenes quality control refused does not leave them to the Owner
    (2026-10-11, his rule: redone until QC passes, only money stops it): the Director reads each
    one's prompt and has it rewritten (`app.media.scene_rewrite.director_ladder`), and the film
    is walked again, at most `DIRECTOR_LADDER_ROUNDS` times; past them a continuation walks it on.
    ``director_ladder`` lists her rounds.
    """
    from app.media.shooting_sheet import (  # noqa: PLC0415 - media imports runbook
        FILM_BUSY,
        FILM_CLOSED,
        FilmBusy,
        film_purchase_lease,
        lease_seconds,
    )

    try:
        with film_purchase_lease(
            engine,
            storyboard_id,
            holder=correlation,
            step="staircase",
            ttl_seconds=lease_seconds(settings),
        ):
            bought: list[dict[str, Any]] = []
            rounds: list[dict[str, Any]] = []
            while True:
                film = _walk_staircase(
                    engine, settings, registry, storyboard_id, wiring, environment, correlation
                )
                bought.extend(film.get("bought") or [])
                refused = _ladder_scenes(engine, storyboard_id, film)
                if not refused or stop_requested(engine):
                    break
                if len(rounds) >= DIRECTOR_LADDER_ROUNDS:
                    film["continues"] = _ladder_continues(engine, storyboard_id, correlation)
                    break
                rung = _director_rung(engine, registry, storyboard_id, refused, correlation)
                rounds.append(rung)
                if not rung["rewritten"] and not rung.get("recovered"):
                    # Nobody's decision: the Director's rewrite did not land (her brief
                    # refused, no Director, a fault), and the studio tries again by itself
                    # (`passes.ladder_retry`). The film's words say so, not «decide el».
                    why = "; ".join(
                        f"scena {item.get('scene_index')}: {item.get('reason')}"
                        for item in rung.get("not_rewritten") or []
                        if item.get("reason")
                    )
                    film["reason"] = (
                        "Directoarea nu a putut încă rescrie "
                        + ("scena " if len(refused) == 1 else "scenele ")
                        + ", ".join(map(str, refused))
                        + " refuzate de controlul calității"
                        + (f" ({why})" if why else "")
                        + "; studioul reia singur rescrierea."
                    )[:1500]
                    break
            film["bought"] = bought
            film["director_ladder"] = rounds
            return film
    except FilmBusy as exc:
        # A closed film (`FilmClosed`: the Owner closed it, or the Director retired it, after
        # the day read it) is HELD for good; a film another buyer holds WAITs.
        return {
            "status": "HELD" if exc.status == FILM_CLOSED else "WAITING",
            "step": None,
            "reason": exc.reason_ro,
            "sheet": {},
            "bought": [],
            "refusal": exc.status if exc.status == FILM_CLOSED else FILM_BUSY,
        }


#: The Director's rounds in one walk of a film: each is her rewrite of every scene quality
#: control refused, then the film walked again so what she rewrote is bought. The film's money
#: (the Policy Kernel, the budgets, its ceiling) ends them sooner; past them a continuation
#: walks the film on, so a film is never left idle while money allows it (2026-10-11).
DIRECTOR_LADDER_ROUNDS = 3
#: The stops of a walk whose scenes may be quality control's to answer.
LADDER_REFUSALS = frozenset({"NEEDS_OWNER", "TAKES_NOT_ACCEPTED"})
LADDER_CAUSE = "director_ladder"


def _ladder_scenes(engine: Engine, storyboard_id: str, film: dict[str, Any]) -> list[int]:
    """The scenes of a stopped walk that quality control refused (the Director's to answer)."""
    if film.get("status") != "WAITING" or film.get("refusal") not in LADDER_REFUSALS:
        return []
    scenes = [int(scene) for scene in film.get("scenes") or [] if isinstance(scene, int)]
    return _quality_scenes(engine, storyboard_id, scenes) if scenes else []


def _quality_scenes(engine: Engine, storyboard_id: str, scenes: list[int]) -> list[int]:
    """Of ``scenes``, those whose newest take quality control refused; [] when unreadable."""
    from app.media.scene_rewrite import quality_refused  # noqa: PLC0415 - media imports runbook

    try:
        return quality_refused(engine, storyboard_id, scenes)
    except Exception as exc:  # noqa: BLE001 - the walk's own stop stands
        logger.warning(
            "ladder_scenes_unread",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
        )
        return []


def _scenes_ro(scenes: list[int], *, refused: bool = False) -> str:
    """«scena 6», «scenele 3, 6» — with «refuzată/refuzate de controlul calității» when asked."""
    one = len(scenes) == 1
    words = ("scena " if one else "scenele ") + ", ".join(map(str, scenes))
    if refused:
        words += (" refuzată" if one else " refuzate") + " de controlul calității"
    return words


def _held_words(engine: Engine, storyboard_id: str, stair_ro: str, scenes: list[int]) -> str:
    """Why the walk stops before a stair, in the film's words: the scenes quality control
    refused wait for the Director's rewrite (her ladder, this same walk), the others for the
    Owner's decision on the shooting sheet. 2026-10-12: «scena 6 așteaptă decizia
    Proprietarului» reached him for a clip quality control had refused — hers, not his."""
    hers = set(_quality_scenes(engine, storyboard_id, scenes))
    from app.media.scene_rewrite import DELIVERY_CODES, last_failure_code  # noqa: PLC0415

    with Session(engine) as session:
        deliveries = {
            index
            for index in hers
            if last_failure_code(session, storyboard_id, index) in DELIVERY_CODES
        }
    quality = hers - deliveries
    his = [scene for scene in scenes if scene not in hers]
    parts: list[str] = []
    if quality:
        parts.append(_scenes_ro(sorted(quality), refused=True) + " așteaptă rescrierea Directoarei")
    if deliveries:
        parts.append(
            _scenes_ro(sorted(deliveries)) + " așteaptă remedierea livrării de către Directoare"
        )
    if his:
        parts.append(_scenes_ro(his) + " așteaptă decizia Proprietarului pe foaia de filmare")
    ending = (
        "nu se cumpără din nou până nu decide el."
        if not hers
        else (
            "nu se cumpără din nou până nu stabilește ea remedierea."
            if deliveries
            else "nu se cumpără din nou până nu o rescrie ea."
        )
        if not his
        else "nu se cumpără din nou până atunci."
    )
    return f"după pasul «{stair_ro}», " + "; ".join(parts) + "; " + ending


def _director_rung(
    engine: Engine,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    scenes: list[int],
    correlation: str,
) -> dict[str, Any]:
    """One round of the Director's rewrites: {"scenes", "rewritten", "not_rewritten"}."""
    from app.media.scene_rewrite import director_ladder  # noqa: PLC0415 - media imports runbook

    try:
        rung = director_ladder(engine, registry, storyboard_id, scenes, correlation)
    except Exception as exc:  # noqa: BLE001 - a fault leaves the walk's stop as it was
        logger.warning(
            "director_ladder_failed",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
        )
        rung = {"rewritten": [], "not_rewritten": [{"reason": error_words(exc)}]}
    return {"scenes": scenes, **rung}


def _ladder_continues(engine: Engine, storyboard_id: str, correlation: str) -> str | None:
    """A continuation for a film whose walk used its rounds of the Director's rewrites: the next
    walk rewrites and buys on (`queue_film_continue`; only in PRODUCTION)."""
    try:
        with Session(engine) as session, session.begin():
            # Read-then-write in the queue: the write lock first (the 2026-10-09 14:17 loss).
            lock_for_write(session)
            return queue_film_continue(
                session,
                storyboard_id,
                key=f"{LADDER_CAUSE}:{storyboard_id}:{correlation}",
                payload={"cause": LADDER_CAUSE},
            )
    except SQLAlchemyError:
        logger.warning("ladder_continue_not_queued", extra={"storyboard_id": storyboard_id})
        return None


def _walk_staircase(
    engine: Engine,
    settings: Settings,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    wiring: dict[str, Any],
    environment: str,
    correlation: str,
) -> dict[str, Any]:
    """`_film_staircase` inside the film's purchase lease."""
    from app.media.factory import reference_image_adapter  # noqa: PLC0415
    from app.media.prompt_audit import (  # noqa: PLC0415 - media imports runbook
        LAYER_OF_STEP,
        NEEDS_PROMPT_APPROVAL,
        audit_before_purchase,
    )
    from app.media.shooting_sheet import (  # noqa: PLC0415 - media imports runbook
        SHEET_STEPS,
        SheetNotFound,
        SheetStepRefused,
        build_sheet,
        recover_paid_takes,
        run_sheet_step,
    )

    image = reference_image_adapter(engine, storyboard_id, wiring.get("image_adapter"))
    context: dict[str, Any] = {
        "capabilities": list(wiring.get("capabilities") or []),
        "integration_id": wiring.get("integration_id"),
        "resolution": wiring.get("resolution") or getattr(settings, "motion_resolution", None),
    }
    bought: list[dict[str, Any]] = []
    sheet: dict[str, Any] = {}

    def stop(status: str, step: str | None, reason: str, **more: Any) -> dict[str, Any]:
        return {
            "status": status,
            "step": step,
            "reason": reason,
            "sheet": sheet,
            "bought": bought,
            **more,
        }

    # What was paid for and never settled (a task the vendor delivered late, candidates or a
    # shot nobody judged) is looked at first: 0 media credits, and it can only take scenes
    # out of buying. A failure here buys nothing and must not stop the film's day.
    try:
        recovered = recover_paid_takes(
            engine,
            storyboard_id,
            correlation_id=correlation,
            image_adapter=image,
            adapter_for_model=wiring.get("adapter_for_model"),
            registry=registry,
            environment=environment,
            storage_root=wiring.get("storage_root"),
            ffmpeg_path=settings.ffmpeg_path,
        )
    except Exception as exc:  # noqa: BLE001 - the staircase decides on what the books say
        logger.warning(
            "paid_takes_not_recovered",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
        )
        recovered = {}

    # Before the sheet prices a new still for a scene clip QC sent back to its still, she
    # looks at the refused clip herself (the Owner, 2026-10-15: «ea poate să hotărască că
    # imaginea este ok»); her yes restores the scene and nothing is bought for it. Free.
    try:
        from app.media.fix_check import restore_sent_back_scenes  # noqa: PLC0415

        restored = restore_sent_back_scenes(
            engine, registry, storyboard_id=storyboard_id, correlation_id=correlation
        )
        if restored:
            logger.info(
                "scenes_restored_by_look",
                extra={"storyboard_id": storyboard_id, "scenes": restored},
            )
    except Exception:  # noqa: BLE001 - her look never stops the walk
        logger.exception("restore_by_look_failed", extra={"storyboard_id": storyboard_id})
    for _stair in range(len(SHEET_STEPS) + 1):
        try:
            sheet = build_sheet(
                engine,
                storyboard_id,
                account=wiring.get("account"),
                stills_model=getattr(image, "model", None),
                settings=settings,
                **context,
            )
        except SheetNotFound as exc:
            return stop("HELD", None, str(exc), refusal="NOT_FOUND")
        steps = sheet["steps"]
        missing = (steps.get(SHEET_STEPS[0]) or {}).get("needs_reference") or []
        if missing:
            # A locked character with no reference picture: no still of the film is bought
            # and nobody is asked about one until the Owner produces the reference set.
            return stop(
                "WAITING",
                SHEET_STEPS[0],
                str(steps[SHEET_STEPS[0]].get("waiting_ro") or ""),
                refusal="NEEDS_REFERENCE",
                recovered=recovered,
            )
        step = next((name for name in SHEET_STEPS if steps[name]["to_buy"]), None)
        held_at = _held_stair(steps, step, SHEET_STEPS)
        if held_at is not None:
            scenes = sorted(steps[held_at].get("held") or [])
            return stop(
                "WAITING",
                held_at,
                _held_words(engine, storyboard_id, STEP_WORDS[held_at], scenes),
                refusal="NEEDS_OWNER",
                recovered=recovered,
                scenes=scenes,
            )
        if step is None:
            # Nothing left to buy; but a filmed scene with no accepted take and no LOCAL_MOVE
            # of his cannot be cut in (PRODUCTION): the film waits for his look on the sheet,
            # and nobody is asked about a narration for a film that cannot be assembled.
            assemble = (sheet.get("steps") or {}).get("assemble") or {}
            blocked = assemble.get("blocked") or []
            if blocked:
                return stop(
                    "WAITING",
                    None,
                    # the scenes grouped, said once (`sheet_words.blocked_words`)
                    str(assemble.get("blocked_ro") or "")
                    or " ".join(str(item.get("reason_ro") or "") for item in blocked),
                    refusal="TAKES_NOT_ACCEPTED",
                    scenes=sorted(
                        {
                            int(item["scene_index"])
                            for item in blocked
                            if isinstance(item, dict) and isinstance(item.get("scene_index"), int)
                        }
                    ),
                )
            return stop("READY", None, "")
        if bought and SHEET_STEPS.index(step) <= SHEET_STEPS.index(bought[-1]["step"]):
            # The stair just bought left scenes behind (a still the gate sent to him, a shot
            # the vendor refused). The same stair is not asked again in the same run: what
            # those scenes need is his decision on the sheet, not a second purchase.
            left = bought[-1]["result"]
            scenes = sorted(
                {*(left.get("needs_owner") or []), *(left.get("needs_still") or [])}
            ) or list(sheet["steps"][step]["to_buy"])
            return stop(
                "WAITING",
                step,
                _held_words(
                    engine,
                    storyboard_id,
                    STEP_WORDS[bought[-1]["step"]],
                    [int(scene) for scene in scenes],
                ),
                refusal="NEEDS_OWNER",
                scenes=[int(scene) for scene in scenes],
            )
        # The Owner, 2026-10-15: «Mereu verificăm prompturile, fără excepție!» Before a step
        # pays for a scene for the first time, the Director audits the words that would be
        # sent (`prompt_audit.audit_before_purchase`): her yes is kept on those words, her no
        # is a brief the Editor rewrites from, and the sheet is rebuilt on the new words; a
        # scene she cannot approve waits for her, never bought. Text only.
        if registry is not None and step in LAYER_OF_STEP:
            try:
                audit = audit_before_purchase(
                    engine,
                    registry,
                    storyboard_id=storyboard_id,
                    step=step,
                    scenes=[int(scene) for scene in sheet["steps"][step]["to_buy"]],
                    correlation_id=correlation,
                )
            except Exception:  # noqa: BLE001 - an audit that fell buys nothing
                logger.exception("prompt_audit_failed", extra={"storyboard_id": storyboard_id})
                audit = {"approved": [], "rewritten": [], "held": [], "skipped": [], "asked": False}
                return stop(
                    "WAITING",
                    step,
                    "Verificarea cuvintelor de către Directoare a căzut; nu se cumpără nimic "
                    "pe cuvinte neverificate.",
                    refusal=NEEDS_PROMPT_APPROVAL,
                    audit=audit,
                )
            if audit["rewritten"]:
                logger.info(
                    "prompt_audit_rewrote",
                    extra={"storyboard_id": storyboard_id, "scenes": audit["rewritten"]},
                )
                continue  # the sheet is rebuilt on her words; the new words are audited
            if audit["held"]:
                return stop(
                    "WAITING",
                    step,
                    " ".join(item["reason"] for item in audit["held"]),
                    refusal=NEEDS_PROMPT_APPROVAL,
                    scenes=[int(item["scene_index"]) for item in audit["held"]],
                    audit=audit,
                )
        try:
            result = run_sheet_step(
                engine,
                storyboard_id,
                step,
                sheet["sheet_hash"],
                correlation_id=correlation,
                account=wiring.get("account"),
                image_adapter=image,
                adapter_for_model=wiring.get("adapter_for_model"),
                registry=registry,
                settings=settings,
                environment=environment,
                storage_root=wiring.get("storage_root"),
                ffmpeg_path=settings.ffmpeg_path,
                # Nobody pressed it: the mode before the balance, and his policy read again
                # before every vendor request (spec 51, 2026-10-04).
                unasked=True,
                **context,
            )
        except SheetStepRefused as exc:
            if exc.status == "NEEDS_APPROVAL":
                status = "ASKED"
            elif exc.status in OWNER_DECIDES:
                status = "WAITING"
            else:
                status = "HELD"
            return stop(
                status,
                step,
                exc.reason_ro,
                refusal=exc.status,
                approval_id=exc.approval_id,
                cost_usd=exc.cost_usd,
                cap_credits=exc.cap_credits,
            )
        entry = {
            "step": step,
            "sheet_hash": sheet["sheet_hash"],
            "credit_usd": float(sheet.get("credit_usd") or 0.01),
            "result": result,
            # Booked by the step itself (`run_sheet_step`), once, before the next stair is
            # priced against the budget: the day books nothing of its own.
            "booked": result.get("booked"),
        }
        bought.append(entry)
        stopped_by = result.get("mode_stopped")
        if isinstance(stopped_by, dict) and stopped_by.get("status") == "BLOCKED_MODE":
            # His mode was lowered while the stair bought (spec 51): what it bought is in the
            # books, the rest waits on his mode, never on a fault of the film's.
            return stop("WAITING", step, str(result["stopped"]), refusal="BLOCKED_MODE")
        if result.get("stopped"):
            return stop("WAITING", step, str(result["stopped"]), refusal="STOPPED")
    return stop("WAITING", None, "Scara filmului nu s-a încheiat în această rulare.")


def _held_stair(
    steps: dict[str, Any], step: str | None, order: tuple[str, ...] | list[str]
) -> str | None:
    """The stair the film waits on because a bought stair left scenes to the Owner, or None.

    The stair about to be bought, when it holds scenes of its own (the rest of it is not
    bought without his answer); the test shot as well before the motion (the motion starts
    only after the hero); and, when nothing is left to buy, the first stair holding any."""

    def holds(name: str) -> bool:
        return bool((steps.get(name) or {}).get("held"))

    if step is None:
        return next((name for name in order if holds(name)), None)
    guarded = [step]
    if step == "motion":
        guarded.insert(0, "test_shot")
    return next((name for name in guarded if holds(name)), None)


# ------------------------------------------------------------- the day never stalls --
#
# 2026-10-02 (DAY_FLOW_NO_STALL; AR-02, REL-11, A4, A3, A15). The media stage took the oldest
# approved factual film alone, so one held by its story, without a shot plan or waiting for the
# Owner stopped every later film; its topic counted as in production until a render COMPLETED,
# so no new topic was chosen either; a film without a shot plan was never asked of the model
# again. Now: the films are walked oldest first (`_media_staircase`); a film's day is recorded
# (`FILM_STATE_EVENT`), so a NEEDS_SHOT_PLAN or lint-blocked film is asked again once per business
# day (`_reask_shot_plans`) and one that stood still longer than `film_wait_days` is retired
# by the Director with a letter (`retire_stale_films`). A film waiting only for his yes, his
# money or his budget is never retired. In TEST he is told once per film why the day does not
# buy and what would (`_test_environment_letter`), and every staircase letter says what the
# film waits for, his rule and his environment, and where both are changed.

#: One film's day, as the media stage left it: business date, status, refusal, step, reason,
#: and whether the day moved it on (or it waits on the Owner alone). Read to retire films.
FILM_STATE_EVENT = "runbook.film_state"
#: A film the Director retired after it stood still longer than `film_wait_days`.
FILM_RETIRED_EVENT = "runbook.film_retired"
#: The day asked the model for a film's shot plan again (text only, no media credit).
SHOT_PLAN_REASKED_EVENT = "runbook.shot_plan_reasked"
FILM_RETIRED_LETTER_KIND = "owner_film_retired"
TEST_ENVIRONMENT_LETTER_KIND = "owner_test_environment"
#: On how many business days a film's shot plan is asked of the model again.
#: Refusals that are the account's, not the film's: the next film would meet them as well, so
#: the walk stops there, and a film waiting on the Owner's money or budget is never retired.
ACCOUNT_WIDE = frozenset(
    {
        "LOW_BALANCE",
        "OVER_DAILY_BUDGET",
        "OVER_BUDGET",
        "BLOCKED_NO_BUDGET",
        "LOW_DISK",
        # The Owner's mode: every film meets it, and a film waiting on it is never retired.
        "BLOCKED_MODE",
    }
)
#: A take that cost (or may have cost) credits: what a retired film's letter lists.
BOUGHT_TAKE_STATUSES = ("SUBMITTED", "PAID", "APPROVED", "REJECTED", "LOST")
TAKE_WORDS: dict[str, tuple[str, str]] = {
    "still": ("imagine", "imagini"),
    "test_shot": ("cadru de probă", "cadre de probă"),
    "motion": ("cadru filmat", "cadre filmate"),
    "narration": ("bucată de narațiune", "bucăți de narațiune"),
}
#: Where the Owner changes the two settings the letters name. Both are his alone: the studio
#: never moves them (Owner commands only). PAGE_OWNER_DAY may move the rule's control into
#: Governance; this sentence moves with it.
OWNER_SETTINGS_PLACES = (
    "Mediul se schimbă din comutatorul «MEDIU» al studioului, iar regula din «Când te întreabă "
    "un pas plătit al unui film», pe foaia de filmare; pe amândouă le schimbi doar tu."
)
_PAID_STEPS_RO = "imaginile, cadrul de probă și restul mișcării"


def _no_stop(text: Any) -> str:
    """A reason without its closing full stop, for a sentence that adds its own."""
    return str(text or "").strip().rstrip(".").rstrip()


def _skip(storyboard_id: str, status: str, refusal: Any, reason: str) -> dict[str, Any]:
    return {
        "storyboard_id": storyboard_id,
        "status": status,
        "refusal": refusal,
        "reason": _no_stop(reason),
    }


def _film_moved(film: dict[str, Any]) -> bool:
    """Whether the day moved the film on (a stair bought, a question asked, nothing left to
    buy), or it waits on the Owner's money or budget alone: either way it does not count as
    standing still for a fault of its own."""
    return (
        bool(film.get("bought"))
        or film.get("status") in ("ASKED", "READY", "ASSEMBLED")
        or film.get("refusal") in ACCOUNT_WIDE
    )


def _passed_over(film: dict[str, Any]) -> bool:
    """A film the walk leaves for the next one: stopped for a reason of its own, nothing
    bought, nothing asked."""
    return not _film_moved(film) and film.get("status") in ("HELD", "WAITING")


def paid_rule_words(rule: str, over_usd: float | None) -> str:
    """The Owner's paid-media rule in his words, as the page says it (`paidMediaRuleWords`)."""
    if rule == "OVER_USD" and over_usd is not None:
        return (
            f"un pas plătit cu plafonul de peste {decimal(float(over_usd))} USD îți cere "
            "aprobarea; unul cu plafonul mai mic urmează modul studioului"
        )
    if rule == "MODE":
        return "pașii plătiți urmează modul studioului"
    return "fiecare pas plătit al unui film îți cere aprobarea, în orice mod al studioului"


def _owner_rule(session: Session) -> tuple[str, str, str, float | None]:
    """(environment, autonomy mode, paid-media rule, its threshold), read, never changed."""
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import paid_media_policy  # noqa: PLC0415

    policy = session.get(OwnerPolicy, 1)
    rule, over = paid_media_policy(policy)
    environment = str(policy.environment or "TEST") if policy is not None else "TEST"
    mode = str(policy.autonomy_mode or "MANUAL") if policy is not None else "MANUAL"
    return environment, mode, rule, over


def _rule_line(session: Session) -> str:
    """The line every staircase letter carries: his rule, his environment, where they change."""
    environment, _mode, rule, over = _owner_rule(session)
    return (
        f"Regula ta pentru pașii plătiți: {paid_rule_words(rule, over)}; mediul: {environment}. "
        + OWNER_SETTINGS_PLACES
    )


def _production_day_words(rule: str, over_usd: float | None, mode: str) -> str:
    """What the daily run would do with a film in PRODUCTION, under his rule and his mode."""
    asks = (
        f"ți-ar cere aprobarea pe foaia de filmare la fiecare pas plătit ({_PAID_STEPS_RO}), "
        "apoi ar asambla filmul din preluări"
    )
    if rule == "EVERY_PAID_STEP" or mode == "SUPERVISED":
        return asks + (" (modul supravegheat)" if rule != "EVERY_PAID_STEP" else "")
    if mode != "AUTONOMOUS_CEO":
        return (
            "nu ar cumpăra nimic singură (modul manual): fiecare pas se cumpără de pe foaia "
            "de filmare, la apăsarea ta"
        )
    budget = (
        "în bugetul zilnic pe care l-ai stabilit (fără un buget zilnic activ nu cumpără nimic), "
        "apoi ar asambla filmul și l-ar trece prin controlul calității"
    )
    if rule == "OVER_USD" and over_usd is not None:
        return (
            "ar cumpăra singură, fără să te întrebe, pașii cu plafonul de cel mult "
            f"{decimal(float(over_usd))} USD ({_PAID_STEPS_RO}), {budget}; pentru un pas mai "
            "scump ți-ar cere aprobarea"
        )
    return (
        "ar cumpăra singură, fără să te întrebe, imaginile și cadrul de probă, apoi, după ce "
        f"controlul clipului acceptă cadrul de probă, restul mișcării, {budget}"
    )


def _owner_letter_exists(session: Session, kind: str, **key: Any) -> bool:
    for existing in session.scalars(select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))):
        letter = existing.body_json if isinstance(existing.body_json, dict) else {}
        if letter.get("kind") == kind and all(letter.get(k) == v for k, v in key.items()):
            return True
    return False


def _test_environment_letter(
    engine: Engine, storyboard_id: str, vendors: list[str], correlation: str
) -> str | None:
    """Once per film: in TEST the day refused the paid vendors, so the film will not be made
    by itself. The letter says so, what the day would do in PRODUCTION under his rule as it is
    now, and where he changes either. It changes nothing (A3)."""
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.media.shooting_sheet import sheet_url  # noqa: PLC0415 - media imports runbook

    with Session(engine) as session, session.begin():
        if _owner_letter_exists(session, TEST_ENVIRONMENT_LETTER_KIND, storyboard_id=storyboard_id):
            return None
        environment, mode, rule, over = _owner_rule(session)
        board = session.get(Storyboard, storyboard_id)
        title = str(board.title if board is not None else storyboard_id[:8])
        url = sheet_url(storyboard_id)
        lines = [
            f"Către Owner. Filmul «{title}» este gata pentru foaia de filmare, dar studioul este "
            f"în mediul {environment}: acolo rularea zilnică nu cumpără nimic de la furnizorii "
            f"reali ({', '.join(vendors)}), deci filmul nu se face singur.",
            f"În PRODUCTION, cu regula ta pentru pașii plătiți de acum "
            f"({paid_rule_words(rule, over)}) și în modul {mode}, rularea zilnică "
            f"{_production_day_words(rule, over, mode)}.",
            OWNER_SETTINGS_PLACES,
            "Până atunci îl poți cumpăra chiar tu, pas cu pas, de pe foaia de filmare; nimic nu "
            "a fost cumpărat.",
            f"Foaia de filmare: {url}",
        ]
        director = agent_for_role(session, "Director")
        message = post_message(
            session,
            intent="ESCALATE",
            subject=f"Filmul «{title}» așteaptă: studioul este în mediul {environment}",
            body={
                "kind": TEST_ENVIRONMENT_LETTER_KIND,
                "storyboard_id": storyboard_id,
                "environment": environment,
                "paid_media_approval": rule,
                "over_usd": over,
                "autonomy_mode": mode,
                "paid_vendors": list(vendors),
                "sheet_url": url,
            },
            body_text="\n".join(lines),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation,
        )
        return str(message.id)


def _note_film_state(
    engine: Engine,
    storyboard_id: str,
    today: str,
    *,
    status: str,
    refusal: Any,
    reason: str,
    step: Any = None,
    moved: bool = False,
) -> None:
    """Record one factual film's day, once per business date and state. A failure here is
    logged: it is the day's bookkeeping, and must never stop the film or the day."""
    payload = {
        "business_date": today,
        "status": status,
        "refusal": refusal,
        "step": step,
        "reason": _no_stop(reason),
        "moved": bool(moved),
    }
    try:
        with Session(engine) as session, session.begin():
            last = session.scalar(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type == FILM_STATE_EVENT,
                    DomainEvent.aggregate_id == storyboard_id,
                )
                .order_by(DomainEvent.sequence.desc())
                .limit(1)
            )
            before = last.payload if last is not None and isinstance(last.payload, dict) else {}
            same = ("business_date", "status", "refusal", "step", "moved")
            if before and all(before.get(name) == payload[name] for name in same):
                return
            append_event(
                session, FILM_STATE_EVENT, "storyboard", storyboard_id, 1, payload, str(uuid4())
            )
    except SQLAlchemyError:
        logger.warning("film_state_not_recorded", extra={"storyboard_id": storyboard_id})


def _stood_since(session: Session, storyboard_id: str) -> tuple[str | None, dict[str, Any]]:
    """The business date the film began to stand still, and its last recorded state.

    The run of days starts at the first state the day did not move on after the last one it
    did, and after the last change to any of the film's takes (a purchase, his decision on
    the sheet): anything that happened to the film starts the count again."""
    from app.media.models import SceneTake  # noqa: PLC0415

    touched = session.scalar(
        select(func.max(SceneTake.updated_at)).where(SceneTake.storyboard_id == storyboard_id)
    )
    since: str | None = None
    last: dict[str, Any] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == FILM_STATE_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        last = payload
        if payload.get("moved") or (touched and str(event.timestamp) <= str(touched)):
            since = None
            continue
        if since is None:
            since = str(payload.get("business_date") or "") or None
    return since, last


def retire_stale_films(
    engine: Engine, settings: Settings, today: str | None = None
) -> list[dict[str, Any]]:
    """Retire every factual film that stood still longer than `film_wait_days` (A4).

    A film still unrendered (APPROVED or NEEDS_SHOT_PLAN) whose recorded days show it held or
    waiting for a reason of its own since then, with nothing bought and nothing decided, is
    set REJECTED by the Director, with one letter to the Owner listing what was bought for it
    and why it stood still; its topic then counts as stalled and selection moves on. A film
    with a question of his still PENDING, or waiting on his money or budget, is never retired.
    """
    today = today or business_date(settings.timezone)
    limit = int(getattr(settings, "film_wait_days", 3) or 3)
    due: list[tuple[str, str, str, int, dict[str, Any]]] = []
    # His standing questions, read through the Policy Kernel (only it reads approval rows).
    asked = {str(view.subject) for view in pending_approvals(engine)}
    with Session(engine) as session:
        rendered = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(VideoRenderJob.status == "COMPLETED")
            )
        )
        for board in session.scalars(
            select(Storyboard)
            .where(Storyboard.status.in_(("APPROVED", NEEDS_SHOT_PLAN)))
            .order_by(Storyboard.created_at)
        ):
            if board.id in rendered or board.id in asked or is_serial_storyboard(board):
                continue
            since, last = _stood_since(session, board.id)
            if since is None:
                continue
            try:
                days = (date.fromisoformat(today) - date.fromisoformat(since)).days
            except ValueError:
                continue
            if days >= limit:
                due.append((board.id, str(board.title), since, days, last))
    retired: list[dict[str, Any]] = []
    for storyboard_id, title, since, days, last in due:
        made = _retire_film(engine, storyboard_id, title, since, days, limit, last)
        if made is not None:
            retired.append(made)
    return retired


def film_spent_micros(engine: Engine, storyboard_id: str) -> int:
    """What the books hold for the film (`film_spend_micros`), or 0 when they cannot be read:
    the figure a closed film's event and letter carry, never a reason not to close it."""
    from app.media.shooting_sheet import film_spend_micros  # noqa: PLC0415 - media imports runbook

    try:
        return int(film_spend_micros(engine, storyboard_id))
    except (SQLAlchemyError, ValueError, TypeError):
        return 0


def bought_takes_of(session: Session, storyboard_id: str) -> dict[str, int]:
    """The film's takes that cost, or may have cost, credits, counted by kind."""
    from app.media.models import SceneTake  # noqa: PLC0415

    bought: dict[str, int] = {}
    for kind, number in session.execute(
        select(SceneTake.kind, func.count())
        .where(
            SceneTake.storyboard_id == storyboard_id,
            SceneTake.status.in_(BOUGHT_TAKE_STATUSES),
        )
        .group_by(SceneTake.kind)
    ).all():
        bought[str(kind)] = int(number)
    return bought


def close_film_books(
    session: Session,
    board: Storyboard,
    *,
    spent: int,
    retired_by: str,
    correlation: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Close one film, in the caller's transaction: what both the Director's retirement
    (`_retire_film`) and the Owner's «Închide filmul» (`app.media.film_close`) do.

    Counts what was bought for it (its takes that cost, or may have cost, credits, by kind),
    sets it REJECTED (its topic then counts as stalled and selection moves on; nothing more is
    bought for it, `shooting_sheet.film_is_closed`) and writes one `FILM_RETIRED_EVENT` with
    ``details``, those takes, ``spent`` (`film_spent_micros`, read by the caller before its
    transaction) and who closed it. The caller checks the film may be closed, and writes its
    own letter, or none. Returns ``bought_takes``, ``items`` (in the Owner's words),
    ``spent_usd_micros`` and the event's ``event_id`` and ``closed_at``."""
    bought = bought_takes_of(session, board.id)
    items = [count(bought[kind], *TAKE_WORDS[kind]) for kind in TAKE_WORDS if bought.get(kind)]
    board.status = "REJECTED"
    event = append_event(
        session,
        FILM_RETIRED_EVENT,
        "storyboard",
        board.id,
        1,
        {
            **details,
            "bought_takes": bought,
            "spent_usd_micros": int(spent),
            "retired_by": retired_by,
        },
        correlation,
    )
    return {
        "bought_takes": bought,
        "items": items,
        "spent_usd_micros": int(spent),
        "event_id": event.event_id,
        "closed_at": event.timestamp,
    }


def _retire_film(
    engine: Engine,
    storyboard_id: str,
    title: str,
    since: str,
    days: int,
    limit: int,
    last: dict[str, Any],
) -> dict[str, Any] | None:
    """The Director's retirement of one film: REJECTED, an event, and his letter."""
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.media.shooting_sheet import sheet_url  # noqa: PLC0415 - media imports runbook

    spent = film_spent_micros(engine, storyboard_id)
    correlation = str(uuid4())
    reason = _no_stop(last.get("reason")) or "fără un motiv înregistrat"
    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, storyboard_id)
        if board is None or board.status not in ("APPROVED", NEEDS_SHOT_PLAN):
            return None
        closed = close_film_books(
            session,
            board,
            spent=spent,
            retired_by="Director",
            correlation=correlation,
            details={
                "since": since,
                "days": days,
                "film_wait_days": limit,
                "last_status": last.get("status"),
                "last_refusal": last.get("refusal"),
                "reason": reason,
            },
        )
        bought, items = closed["bought_takes"], closed["items"]
        url = sheet_url(storyboard_id)
        lines = [
            f"Către Owner. Filmul «{title}» a fost retras de Director: stă pe loc de "
            f"{count(days, 'zi', 'zile')} (din {since}), iar limita este de "
            f"{count(limit, 'zi', 'zile')} (STUDIO_FILM_WAIT_DAYS).",
            f"Ultimul motiv: {sentence(reason)}",
            f"Cumpărat pentru el: {', '.join(items) if items else 'nimic'}; în registre: "
            f"{_usd_words(spent)}.",
            "Subiectul lui nu mai ține studioul pe loc: rularea următoare alege alt subiect. "
            "Preluările plătite rămân în studio, iar pentru acest film nu se mai cumpără nimic.",
            f"Foaia de filmare: {url}",
        ]
        director = agent_for_role(session, "Director")
        post_message(
            session,
            intent="ESCALATE",
            subject=f"Film retras: «{title}», pe loc de {count(days, 'zi', 'zile')}",
            body={
                "kind": FILM_RETIRED_LETTER_KIND,
                "storyboard_id": storyboard_id,
                "since": since,
                "days": days,
                "bought_takes": bought,
                "spent_usd_micros": spent,
                "sheet_url": url,
            },
            body_text="\n".join(lines),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation,
        )
    logger.info("film_retired", extra={"storyboard_id": storyboard_id, "days": days})
    return {"storyboard_id": storyboard_id, "title": title, "since": since, "days": days}


def _film_figures(sheet: dict[str, Any]) -> dict[str, Any]:
    """The sheet's own money, in the shape `estimate_film_cost_micros(sheet=...)` reads."""
    return {**dict(sheet.get("footer") or {}), "credit_usd": sheet.get("credit_usd")}


def _sheet_letter(
    engine: Engine,
    storyboard_id: str,
    film: dict[str, Any],
    plan_cost: dict[str, Any] | None,
    correlation: str,
) -> str | None:
    """The Owner's letter about one film stopped on its staircase: the sheet in words.

    Written once per film, sheet, stair and reason: the same day run again, or tomorrow's
    run finding the same question standing, writes nothing new. Deterministic: the sheet's
    own facts, never a model's account of them.
    """
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.decisions.sources import film_budget  # noqa: PLC0415
    from app.media.shooting_sheet import film_is_closed, sheet_url  # noqa: PLC0415

    with Session(engine) as session:
        closed = film_is_closed(session, storyboard_id)
    if closed:
        # «Închide filmul» pressed after the day gave the film's lease back: nothing more asks
        # him about it (no letter, no budget card, no repair of its sheet).
        return None
    sheet = film.get("sheet") or {}
    step = film.get("step")
    status = str(film.get("refusal") or film["status"])
    # A paid step that cannot fit any day under his daily budget is his decision: a card in
    # his window with what the film needs (withdrawn once the film no longer waits on it).
    budget_card = film_budget(
        engine, storyboard_id, film, plan_cost, step_words=STEP_WORDS.get(str(step), "")
    )
    if status in ("LINT_BLOCKED", "NEEDS_SHOT_PLAN") and sheet.get("sheet_hash"):
        from app.media.blocker_repair import submit_sheet_issues  # noqa: PLC0415

        # A prompt/shot-plan refusal is the studio's job, never an Owner questionnaire.
        report = submit_sheet_issues(engine, sheet)
        return report.get("message_id")
    if status == "NEEDS_PROMPT_APPROVAL":
        # Her audit of the words before a purchase (2026-10-15): the scene waits for her brief
        # and the Editor's rewrite, never for the Owner; no letter.
        return None
    if status == "OWNER_HOLD":
        # His own «Oprește GPU acum» stopped the step (2026-10-12): his card in «Decizii» says
        # it once for every film; a letter per film would repeat his own press back to him.
        return None
    if status in LADDER_REFUSALS and _ladder_scenes(engine, storyboard_id, film):
        # Quality control's refusal of a scene is the Director's to answer — her ladder in
        # the walk, the `ladder_retry` pass after it — never a letter to the Owner
        # (2026-10-12, 08:10, «The Zero Script Club» scene 3 after two re-rolls: «Foaia de
        # filmare … așteaptă decizia ta» reached him while the rung was composing again).
        return None
    key = {
        "storyboard_id": storyboard_id,
        "sheet_hash": sheet.get("sheet_hash"),
        "step": step,
        "status": status,
    }
    title = str(sheet.get("title") or storyboard_id[:8])
    words = STEP_WORDS.get(str(step), "") if step else "narațiunea și asamblarea"
    # What the film waits for decides what the letter asks of him (A15): a question is a
    # question, a hero is a look, a balance is a top-up, a budget is a wait or his consent.
    headline, follows = _letter_headline(str(film["status"]), status, words)
    with Session(engine) as session:
        rule_line = _rule_line(session)
    lines = [f"Către Owner. Filmul «{title}» {headline}. {follows}"]
    lines.append(sentence(str(film.get("reason") or "")))
    lines.append(rule_line)
    if budget_card:
        lines.append(
            "Bugetul de care are nevoie filmul te așteaptă și ca un card în fereastra «Decizii»."
        )
    info = (sheet.get("steps") or {}).get(step) if step else None
    if info:
        lines.append(
            f"Pasul «{words}» costă {_credits_words(info.get('cost_credits'))} "
            f"({decimal(float(info.get('cost_usd') or 0.0))} USD), cu plafonul de "
            f"{_credits_words(info.get('cap_credits'))}."
        )
    if plan_cost is not None:
        lines.append(
            f"Filmul întreg, după foaia de filmare: estimat "
            f"{_usd_words(plan_cost['expected_usd_micros'])}, plafon "
            f"{_usd_words(plan_cost['usd_micros'])}"
            + (f" ({plan_cost['caveat']})" if plan_cost.get("caveat") else "")
            + "."
        )
    balance = ((sheet.get("footer") or {}).get("balance") or {}).get("credits")
    if balance is not None:
        lines.append(f"Soldul Runway citit acum: {_credits_words(balance)}.")
    for scene in sheet.get("scenes") or []:
        line = scene.get("price_line_ro") or ""
        lines.append(f"Scena {scene.get('scene_index')} · {scene.get('kind')} · {line}".rstrip())
    url = sheet_url(storyboard_id)
    lines.append(f"Foaia de filmare: {url}")
    body = {
        "kind": SHEET_LETTER_KIND,
        **key,
        "sheet_url": url,
        "approval_id": film.get("approval_id"),
        "reason": film.get("reason"),
        "cost_credits": (info or {}).get("cost_credits"),
        "cap_credits": (info or {}).get("cap_credits"),
        "film_expected_usd_micros": (plan_cost or {}).get("expected_usd_micros"),
        "film_cap_usd_micros": (plan_cost or {}).get("usd_micros"),
    }
    with Session(engine) as session, session.begin():
        # Behind the write lock the Owner's close takes: a film closed meanwhile gets no letter.
        lock_for_write(session)
        if film_is_closed(session, storyboard_id):
            return None
        for existing in session.scalars(
            select(AgentMessage).where(AgentMessage.to_agent_id.is_(None))
        ):
            letter = existing.body_json if isinstance(existing.body_json, dict) else {}
            if letter.get("kind") == SHEET_LETTER_KIND and all(
                letter.get(name) == value for name, value in key.items()
            ):
                return None
        director = agent_for_role(session, "Director")
        message = post_message(
            session,
            intent="ESCALATE",
            subject=f"Foaia de filmare: «{title}» {headline}",
            body=body,
            body_text="\n".join(line for line in lines if line),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation,
        )
        message_id = str(message.id)
    # The film's older letters now say less than this one, and an answered question no longer
    # asks: closed by the studio (`answered_letters`), so he never closes them by hand.
    try:
        from app.media.answered_letters import retire_answered_letters  # noqa: PLC0415

        retire_answered_letters(engine, correlation)
    except Exception as exc:  # noqa: BLE001 - the new letter stands whatever happens here
        logger.error("answered_letters_failed", extra={"error": type(exc).__name__})
    return message_id


#: The refusals that are a budget's, and what the film then waits for.
_BUDGET_WAITS: dict[str, tuple[str, str]] = {
    "OVER_DAILY_BUDGET": (
        "așteaptă bugetul zilei",
        "Pasul se cumpără când bugetul îl permite: mâine, după ce îl schimbi tu în Trezorerie "
        "→ Buget și cheltuieli, sau cu acordul tău de depășire pe foaia de filmare.",
    ),
    "OVER_BUDGET": (
        "așteaptă bugetul",
        "Pasul se cumpără când bugetul îl permite: în perioada următoare, după ce îl schimbi tu "
        "în Trezorerie → Buget și cheltuieli, sau cu acordul tău de depășire pe foaia de filmare.",
    ),
    "OVER_FILM_BUDGET": (
        "așteaptă bugetul filmului",
        "Pasul trece de plafonul unui film (STUDIO_FILM_BUDGET_USD): se cumpără doar cu acordul "
        "tău de depășire pe foaia de filmare sau după ce schimbi plafonul.",
    ),
    "BLOCKED_NO_BUDGET": (
        "așteaptă un buget zilnic de la tine",
        "În PRODUCTION nimic nu se cumpără neîntrebat fără un buget zilnic activ: setează-l în "
        "Trezorerie → Buget și cheltuieli.",
    ),
}


def _letter_headline(film_status: str, refusal: str, words: str) -> tuple[str, str]:
    """The letter's headline and the sentence after it, for what the film waits on."""
    if film_status == "ASKED":
        return (
            f"așteaptă răspunsul tău la pasul «{words}»",
            "Pasul acesta nu se cumpără fără răspunsul tău pe foaia de filmare.",
        )
    if film_status == "WAITING":
        if refusal in ("HERO_NOT_APPROVED", "HERO_FIRST"):
            return (
                "așteaptă privirea ta pe cadrul de probă",
                "Restul mișcării nu se cumpără până nu privești cadrul de probă pe foaia de "
                "filmare.",
            )
        if refusal == "LOW_BALANCE":
            return (
                "așteaptă alimentarea contului Runway",
                "Nu se cumpără nimic până nu alimentezi contul; soldul se citește din nou la "
                "rularea următoare.",
            )
        if refusal in _BUDGET_WAITS:
            return _BUDGET_WAITS[refusal]
        if refusal == "LOW_DISK":
            return (
                "așteaptă spațiu liber pe discul filmelor",
                "Nu se cumpără nimic până nu faci loc pe disc (sau muți filmele pe un disc mai "
                "mare, STUDIO_MEDIA_ROOT); spațiul se măsoară din nou la rularea următoare.",
            )
        if refusal == "FILM_BUSY":
            return (
                "așteaptă să se încheie cumpărarea în curs",
                "Nimic nu se cumpără de două ori: rularea următoare îl reia.",
            )
        return (
            "așteaptă decizia ta pe foaia de filmare",
            "Nu se cumpără nimic pentru scenele lui până nu decizi.",
        )
    headline = f"este oprit înainte de pasul «{words}»" if words else "este oprit"
    return headline, "Nu se cumpără nimic până nu se rezolvă motivul de mai jos."


def _assemble_from_takes(
    engine: Engine,
    settings: Settings,
    vault: Any,
    storyboard_id: str,
    wiring: dict[str, Any],
    environment: str,
    plan_cost: dict[str, Any],
    correlation: str,
    *,
    sheet_hash: str | None = None,
    registry: ProviderRegistry | None = None,
) -> dict[str, Any]:
    """Assemble a film whose sheet has nothing left to buy: from its takes, buying no still
    and no shot. Only the narration is paid, so only the narration is asked and held.
    ``registry`` reaches the mix: the Voice Artist plans the sound through it.

    The question is the sheet's own (`shooting_sheet.narration_gate`'s action, subject and
    context): bound to ``sheet_hash`` and the assemble step, so the Owner's one yes for that
    plan is spent once, whether the day or his own click on the sheet assembles the film."""
    from app.economy.accountant import (  # noqa: PLC0415
        budget_refusal_letter,
        record_render_costs,
    )
    from app.economy.services import format_micros  # noqa: PLC0415
    from app.media.assembler import (  # noqa: PLC0415 - media imports runbook
        RenderEngineUnavailable,
        RenderStopped,
        TakesMissing,
        assemble_from_takes,
    )
    from app.media.factory import render_plan, tts_provider  # noqa: PLC0415
    from app.media.services import ReferenceRequired  # noqa: PLC0415
    from app.providers.media_http import MediaProviderError  # noqa: PLC0415

    narration = int(plan_cost.get("narration_usd_micros") or 0)
    caveat = str(plan_cost.get("caveat") or "")
    usd = narration / 1_000_000
    dear = usd > settings.paid_generation_approval_threshold_usd
    refusal = mode_refusal(
        engine,
        "media.paid_generation_over_threshold" if dear else "media.paid_generation",
        requester="video_editor",
        subject=storyboard_id,
        evidence=(
            f"storyboard {storyboard_id}: narațiunea filmului asamblat din preluările "
            f"aprobate, estimat {format_micros(narration)} USD" + (f" ({caveat})" if caveat else "")
        ),
        cost_usd=usd,
        context={"plan_hash": sheet_hash, "step": "assemble"} if sheet_hash else None,
    )
    if refusal is not None:
        return {
            "status": "ASKED" if refusal.get("approval_id") else "HELD",
            "reason": str(refusal.get("reason") or ""),
            "approval_id": refusal.get("approval_id"),
        }
    hold = reserve_spend(
        engine,
        narration,
        f"film {storyboard_id}",
        correlation,
        note=f"narațiunea filmului din preluări: {format_micros(narration)} USD"
        + (f"; {caveat}" if caveat else ""),
    )
    if not hold["allowed"]:
        budget_refusal_letter(engine, hold["reason"], correlation)
        return {"status": "HELD", "reason": str(hold["reason"])}
    reservation_id = hold.get("reservation_id")
    planned = render_plan(engine, vault, storyboard_id)
    try:
        result = assemble_from_takes(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=wiring.get("storage_root"),
            ffmpeg_path=settings.ffmpeg_path,
            reference_for_scene=planned.get("reference_for_scene"),
            tts_adapter=tts_provider(engine, vault),
            tts_adapter_for_scene=planned.get("tts_for_scene"),
            voice_segments_for_scene=planned.get("voice_segments_for_scene"),
            environment=environment,
            production_plan=planned.get("plan"),
            settings=settings,
            registry=registry,
        )
    except TakesMissing as exc:
        _release(engine, reservation_id, f"preluări lipsă: {exc}"[:120], correlation)
        return {"status": "HELD", "reason": str(exc)}
    except RenderStopped as exc:
        failed = _record_failed_attempt(engine, storyboard_id, correlation)
        _release(engine, reservation_id, f"asamblare oprită: {error_words(exc)}", correlation)
        return {"status": "STOPPED", "reason": error_words(exc), "costs_recorded": failed}
    except RenderEngineUnavailable as exc:
        _release(
            engine, reservation_id, f"asamblarea nu poate rula: {error_words(exc)}", correlation
        )
        return {"status": "NO_ENGINE", "reason": error_words(exc)}
    except (ReferenceRequired, MediaProviderError) as exc:
        failed = _record_failed_attempt(engine, storyboard_id, correlation)
        _release(
            engine, reservation_id, f"asamblare refuzată: {error_words(exc)}"[:120], correlation
        )
        return {
            "status": "REFUSED",
            "reason": error_words(exc),
            "error_class": type(exc).__name__,
            "costs_recorded": failed,
        }
    recorded = 0
    try:
        recorded = int(
            record_render_costs(
                engine,
                result["job_id"],
                correlation,
                alert_percent=settings.price_change_alert_percent,
            )["recorded"]
        )
    except (EconomyError, KeyError):
        logger.info("render_cost_not_recorded", extra={"storyboard_id": storyboard_id})
    if reservation_id:
        settle_reservation(
            engine,
            reservation_id,
            settled_reference=f"render:{result['job_id']}",
            correlation_id=correlation,
        )
    return {
        "status": "ASSEMBLED",
        "asset_id": result["output_asset_id"],
        "job_id": result["job_id"],
        "costs_recorded": recorded,
    }


def _media_staircase(
    engine: Engine,
    settings: Settings,
    vault: Any,
    registry: ProviderRegistry | None,
    pending: list[str],
    held: list[str],
    serial_ids: set[str],
    environment: str,
    *,
    skipped: list[dict[str, Any]] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """The PRODUCTION media stage: every film up its own staircase, one answered stair at a
    time, then the Owner is written to and the day goes on.

    The factual films are walked oldest first (AR-02, REL-11): a film stopped for a reason of
    its own, with nothing bought (HELD, or WAITING on its scenes, its hero, its ceiling, its
    lease), is passed over, named in ``skipped`` and written to the Owner once, and the next
    film is tried. The walk ends at the first film the day worked on (a stair bought, a
    question asked, a film assembled) or one stopped by the account itself (no money, no
    budget), which the next film would meet as well: one factual film a day, as before, and
    never one standing in front of all the others."""
    from app.media.shooting_sheet import (  # noqa: PLC0415 - media imports runbook
        ASSEMBLE_STEP,
        FILM_BUSY,
        FILM_CLOSED,
        FilmBusy,
        film_purchase_lease,
        lease_seconds,
    )

    wiring = sheet_wiring(engine, vault, settings)
    skipped = skipped if skipped is not None else []
    today = today or business_date(settings.timezone)
    # Whether the day has worked on a factual film; the films after it wait for tomorrow.
    factual_done = False
    produced: list[str] = []
    serial_assets: list[str] = []
    awaiting_owner: list[dict[str, Any]] = []
    waiting: list[str] = []
    director_waiting: list[str] = []
    bought_lines: list[str] = []
    bought_steps: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    sheets: dict[str, str] = {}
    films: list[dict[str, Any]] = []
    asked_correlation = ""
    costs_recorded = 0

    def stopped_outcome(storyboard_id: str, said: str) -> dict[str, Any]:
        if asked_correlation:
            waiting_approvals_letter(engine, asked_correlation)
        return _outcome(
            BLOCKED,
            f"{stop_reason_words(engine)} {said}",
            assets=produced,
            serial_assets=serial_assets,
            stopped_storyboard=storyboard_id,
            bought_steps=bought_steps,
            sheets=sheets,
        )

    for storyboard_id in pending:
        factual_film = storyboard_id not in serial_ids
        if factual_film and factual_done:
            continue  # one factual film a day; the next one is tomorrow's
        # His switch, before each film, as on the legacy path.
        if stop_requested(engine):
            return stopped_outcome(storyboard_id, "Filmul următor nu a fost început.")
        correlation = str(uuid4())
        film = _film_staircase(
            engine, settings, registry, storyboard_id, wiring, environment, correlation
        )
        if film.get("refusal") == FILM_CLOSED:
            # Closed after the day read it (the Owner's «Închide filmul», or the Director's
            # retirement): nothing was bought or asked, and nobody is written to about it.
            films.append(
                {"storyboard_id": storyboard_id, "status": "CLOSED", "refusal": film["refusal"]}
            )
            continue
        sheet = film.get("sheet") or {}
        if factual_film:
            if _passed_over(film):
                skipped.append(
                    _skip(
                        storyboard_id,
                        str(film["status"]),
                        film.get("refusal"),
                        str(film.get("reason") or ""),
                    )
                )
            else:
                factual_done = True
        if sheet.get("sheet_hash"):
            sheets[storyboard_id] = str(sheet["sheet_hash"])
        title = str(sheet.get("title") or storyboard_id[:8])
        for entry in film["bought"]:
            booked = entry.get("booked")
            result = entry["result"]
            spent = result.get("spent_credits_measured")
            if spent is None:
                spent = result.get("spent_credits_quoted")
            bought_steps.append(
                {
                    "storyboard_id": storyboard_id,
                    "step": entry["step"],
                    "sheet_hash": entry["sheet_hash"],
                    "credits": spent,
                    "booked": booked,
                }
            )
            accepted = result.get("hero_accepted")
            if isinstance(accepted, dict):
                # The hero test shot accepted by its clip QC under the Owner's own rule
                # (HERO_AUTO_ACCEPT): said in the day's account, before what it unlocked.
                bought_lines.append(
                    f"«{title}»: cadrul de probă (scena {accepted.get('scene_number')}) "
                    "acceptat de controlul clipului, cum permite regula ta pentru pașii plătiți"
                )
            bought_lines.append(f"«{title}»: {STEP_WORDS[entry['step']]} ({_credits_words(spent)})")
        # The film's own money, from its sheet: what the Owner reads in his letter, and the
        # narration the assembly holds. Never the flat motion ceiling.
        plan_cost = (
            estimate_film_cost_micros(
                engine,
                storyboard_id,
                environment=environment,
                settings=settings,
                sheet=_film_figures(sheet),
            )
            if sheet
            else None
        )
        if stop_requested(engine):
            return stopped_outcome(storyboard_id, "Scara filmului s-a oprit.")
        if film["status"] == "READY" and plan_cost is not None:
            try:
                # Under the film's purchase lease again, as the sheet's own assembly
                # (`run_assemble_step`): the staircase gave it back when it returned READY,
                # and the assembly asks and buys the narration. A film closed in between
                # («Închide filmul») meets `FilmClosed` here, and a close pressed during the
                # assembly is refused FILM_BUSY until it ends.
                with film_purchase_lease(
                    engine,
                    storyboard_id,
                    holder=correlation,
                    step=ASSEMBLE_STEP,
                    ttl_seconds=lease_seconds(settings),
                ):
                    made = _assemble_from_takes(
                        engine,
                        settings,
                        vault,
                        storyboard_id,
                        wiring,
                        environment,
                        plan_cost,
                        correlation,
                        sheet_hash=str(sheet.get("sheet_hash") or "") or None,
                        registry=registry,
                    )
            except FilmBusy as exc:
                if exc.status == FILM_CLOSED:
                    films.append(
                        {"storyboard_id": storyboard_id, "status": "CLOSED", "refusal": exc.status}
                    )
                    continue
                # Another buyer took the film between its staircase and its assembly (his
                # own press on the sheet): it WAITs, as a film whose staircase was busy.
                made = {"status": "WAITING", "reason": exc.reason_ro, "refusal": FILM_BUSY}
            costs_recorded += int(made.get("costs_recorded") or 0)
            if factual_film and made["status"] in ("ASSEMBLED", "REFUSED"):
                _note_film_state(
                    engine,
                    storyboard_id,
                    today,
                    status=str(made["status"]),
                    refusal=None,
                    reason=str(made.get("reason") or ""),
                    moved=made["status"] == "ASSEMBLED",
                )
            if made["status"] == "ASSEMBLED":
                from app.decisions.sources import film_budget  # noqa: PLC0415

                film_budget(engine, storyboard_id, {"status": "ASSEMBLED"}, None)
                produced.append(str(made["asset_id"]))
                if storyboard_id in serial_ids:
                    serial_assets.append(str(made["asset_id"]))
                films.append({"storyboard_id": storyboard_id, "status": "ASSEMBLED"})
                continue
            if made["status"] == "STOPPED":
                return stopped_outcome(storyboard_id, sentence(str(made["reason"])))
            if made["status"] == "NO_ENGINE":
                return _outcome(
                    SKIPPED,
                    f"Asamblarea nu poate rula: {made['reason']}.",
                    assets=produced,
                    bought_steps=bought_steps,
                    sheets=sheets,
                )
            if made["status"] == "REFUSED":
                refused.append({"storyboard_id": storyboard_id, "said": made["reason"]})
                films.append({"storyboard_id": storyboard_id, "status": "REFUSED"})
                continue
            film = {**film, **made, "status": made["status"], "step": None}
        films.append(
            {
                "storyboard_id": storyboard_id,
                "status": film["status"],
                "step": film.get("step"),
                "refusal": film.get("refusal"),
                "approval_id": film.get("approval_id"),
            }
        )
        # One full stop at the end of each film's reason: the day's sentence adds its own.
        reason = _no_stop(" ".join(str(film.get("reason") or "").split()))
        if factual_film:
            _note_film_state(
                engine,
                storyboard_id,
                today,
                status=str(film["status"]),
                refusal=film.get("refusal"),
                step=film.get("step"),
                reason=str(film.get("reason") or ""),
                moved=_film_moved(film),
            )
        if film["status"] == "ASKED":
            step = film.get("step")
            info = (sheet.get("steps") or {}).get(step) if step else None
            price = (
                f" ({_credits_words(info.get('cost_credits'))}, "
                f"{decimal(float(info.get('cost_usd') or 0.0))} USD; plafon "
                f"{_credits_words(info.get('cap_credits'))})"
                if info
                else ""
            )
            awaiting_owner.append(
                {
                    "storyboard_id": storyboard_id,
                    "status": "NEEDS_APPROVAL",
                    "step": step,
                    "approval_id": film.get("approval_id"),
                    "reason": reason,
                    "sheet_hash": sheet.get("sheet_hash"),
                }
            )
            waiting.append(f"«{title}» la pasul «{STEP_WORDS.get(str(step), 'narațiunea')}»{price}")
            if film.get("approval_id") and not asked_correlation:
                asked_correlation = correlation
        elif film["status"] == "WAITING":
            if _ladder_scenes(engine, storyboard_id, film):
                director_waiting.append(f"«{title}»: {reason}")
            else:
                waiting.append(f"«{title}»: {reason}")
        else:
            held.append(f"{storyboard_id[:8]}: {reason}")
        _sheet_letter(engine, storyboard_id, film, plan_cost, correlation)

    # The day's one letter about every standing question, as on the legacy path.
    if asked_correlation:
        waiting_approvals_letter(engine, asked_correlation)

    parts: list[str] = []
    if produced:
        parts.append(
            f"{count(len(produced), 'videoclip asamblat', 'videoclipuri asamblate')} din "
            "preluările aprobate."
        )
    if bought_lines:
        parts.append("Cumpărat pe foaia de filmare: " + "; ".join(bought_lines) + ".")
    if waiting:
        parts.append(
            f"{count(len(waiting), 'film așteaptă', 'filme așteaptă')} Proprietarul: "
            + "; ".join(waiting)
            + ". Foaia de filmare și scrisoarea i-au fost trimise."
        )
    if director_waiting:
        parts.append("Directoarea preia remedierea: " + "; ".join(director_waiting) + ".")
    if refused:
        parts.append(f"{count(len(refused), *REFUSED_RENDERS)}: {_no_stop(refused[0]['said'])}.")
    if held:
        parts.append("Oprit: " + _no_stop(held[0]) + ".")
    if skipped and factual_done:
        parts.append(
            count(len(skipped), "film oprit a fost lăsat", "filme oprite au fost lăsate")
            + " deoparte azi; s-a lucrat la următorul."
        )
    reason_text = " ".join(parts) or "Nimic de cumpărat."
    status = COMPLETED if produced or bought_steps else SKIPPED
    return _outcome(
        status,
        reason_text,
        assets=produced,
        serial_assets=serial_assets,
        awaiting_owner=awaiting_owner,
        approval_id=awaiting_owner[0]["approval_id"] if awaiting_owner else None,
        bought_steps=bought_steps,
        sheets=sheets,
        films=films,
        held=held,
        refused=refused,
        costs_recorded=costs_recorded,
        staircase=True,
        skipped=skipped,
    )


def _media(
    engine: Engine, settings: Settings, vault: Any, registry: ProviderRegistry | None = None
) -> dict[str, Any]:
    """The media stage: the day's films (`_media_films`), then the films that stood still
    too long retired by the Director (`retire_stale_films`), so a stuck film never holds its
    topic, and with it the studio, for ever (A4). His stop ends the stage before either."""
    outcome = _media_films(engine, settings, vault, registry)
    if outcome["status"] == BLOCKED:
        return outcome
    retired = retire_stale_films(engine, settings)
    artefacts = outcome.setdefault("artefacts", {})
    artefacts["retired"] = [item["storyboard_id"] for item in retired]
    if retired:
        said = (
            f"{count(len(retired), 'film retras', 'filme retrase')} de Director după "
            f"{count(int(settings.film_wait_days), 'zi', 'zile')} pe loc: "
            + "; ".join(f"«{item['title']}»" for item in retired)
            + "."
        )
        outcome["reason"] = (str(outcome.get("reason") or "").rstrip() + " " + said).strip()
    return outcome


def _media_films(
    engine: Engine, settings: Settings, vault: Any, registry: ProviderRegistry | None = None
) -> dict[str, Any]:
    """Render the storyboards that have no finished video yet: the factual film, then the serial's.

    Before a storyboard is voiced, the Voice Artist reviews its narration (pronunciation,
    pacing). Her review is filed as a report; a FLAG escalates to the Director. It does not
    hold the render: the words rest on verified claims and the day's output is not blocked
    on an opinion about delivery.

    One factual film and one serial episode a day, in that order, through the same story
    gate, the same budget check and the same camera. The serial stage runs before this one
    and leaves its storyboard APPROVED with a story review PASS behind it; nothing here knows
    the serial by anything but its storyboard's series key. The budget is asked before each
    film, not once for the day: what the factual film spent is in the books by the time the
    serial is asked about, and a refusal then skips the serial alone and says so. It used to
    be one storyboard per run, whichever came back first — a serial storyboard would have
    waited a day behind the factual one, or taken its place.
    """
    from app.economy.credits import credit_balances, record_credit_spend
    from app.media.assembler import RenderEngineUnavailable, RenderStopped, assemble_video_job
    from app.media.factory import (
        PaidVendorRefused,
        abandon_unfinished_renders,
        guard_motion_chooser,
        image_provider,
        legacy_render_vendors,
        motion_for_scene,
        render_plan,
        tts_provider,
    )
    from app.media.production_policy import named_model
    from app.media.services import ReferenceRequired
    from app.providers.media_http import MediaProviderError

    with Session(engine) as session:
        rendered = set(
            session.scalars(
                select(VideoRenderJob.storyboard_id).where(VideoRenderJob.status == "COMPLETED")
            )
        )
        approved = [
            board
            for board in session.scalars(
                select(Storyboard)
                .where(Storyboard.status == "APPROVED")
                .order_by(Storyboard.created_at)
            )
            if board.id not in rendered
        ]
        # Every approved factual film, oldest first, and not only the oldest: one held by its
        # story, without a shot plan or waiting for the Owner used to stop every later film
        # (AR-02, REL-11). The films are walked in order below until one can be worked on.
        factual = [board.id for board in approved if not is_serial_storyboard(board)]
        serial = serial_films_due(session, approved, business_date(settings.timezone))[:1]
        pending = factual + serial
        retry = [] if pending else stalled_storyboards(session, engine, vault)[:1]
        # A factual film still waiting for its shot plan stands still too; its day is recorded
        # so the Director can retire it once it has stood longer than `film_wait_days`.
        without_plan_boards = [
            board.id
            for board in session.scalars(
                select(Storyboard)
                .where(Storyboard.status == NEEDS_SHOT_PLAN)
                .order_by(Storyboard.created_at)
            )
            if board.id not in rendered and not is_serial_storyboard(board)
        ]
    today = business_date(settings.timezone)
    # Every film the walk passed over, with why: the day names them, and each one's day is kept.
    skipped: list[dict[str, Any]] = []
    for storyboard_id in without_plan_boards:
        _note_film_state(
            engine,
            storyboard_id,
            today,
            status="HELD",
            refusal=NEEDS_SHOT_PLAN,
            reason="Filmul așteaptă planul de cadre scris de model.",
        )

    if not pending and not retry:
        return _outcome(COMPLETED, "Niciun storyboard de randat.", rendered=0, skipped=skipped)
    pending = pending or retry
    serial_ids = set(serial)

    # Nothing is generated for a film whose story has not been read and passed. This is the
    # gate before the money: every other gate in the studio used to run after it was spent.
    held: list[str] = []
    with Session(engine) as session:
        allowed = []
        gated: list[tuple[str, str]] = []
        for storyboard_id in pending:
            board = session.get(Storyboard, storyboard_id)
            passed, why = (
                story_gate(session, board.script_draft_id) if board else (False, "fără storyboard")
            )
            if passed:
                allowed.append(storyboard_id)
            else:
                held.append(f"{storyboard_id[:8]}: {_no_stop(why)}")
                gated.append((storyboard_id, why))
    for storyboard_id, why in gated:
        if storyboard_id in serial_ids:
            continue
        skipped.append(_skip(storyboard_id, "HELD", "STORY_GATE", why))
        _note_film_state(
            engine, storyboard_id, today, status="HELD", refusal="STORY_GATE", reason=why
        )
    if not allowed:
        return _outcome(
            SKIPPED,
            "Niciun film nu a trecut recenzia de poveste: " + (held[0] if held else "—"),
            held=held,
            skipped=skipped,
        )
    pending = allowed

    # Which environment the day renders in is the studio's own state, not a parameter.
    environment = studio_environment(engine)
    # In PRODUCTION a factual film is bought only from the shot plan its video editor's model
    # wrote. A film whose scenes carry template prompts (no model was reachable, a TEST
    # convenience) or a plan that was lost is stopped here, before any adapter is asked for
    # anything: NEEDS_SHOT_PLAN and a WARNING event, and the day says so. The Nepal film was
    # rendered twice from template prompts after its plan was lost to one unescaped quote.
    if environment == "PRODUCTION":
        without_plan: list[str] = []
        for storyboard_id in pending:
            if storyboard_id in serial_ids:
                continue
            gaps = hold_for_shot_plan(engine, storyboard_id, str(uuid4()))
            if gaps:
                without_plan.append(storyboard_id)
                why = (
                    f"planul de cadre al modelului lipsește pentru "
                    f"{count(len(gaps), 'cadru', 'cadre')} ({', '.join(map(str, gaps))})"
                )
                held.append(f"{storyboard_id[:8]}: {why}")
                skipped.append(_skip(storyboard_id, "HELD", NEEDS_SHOT_PLAN, why))
                _note_film_state(
                    engine,
                    storyboard_id,
                    today,
                    status="HELD",
                    refusal=NEEDS_SHOT_PLAN,
                    reason=sentence(why),
                )
        pending = [storyboard_id for storyboard_id in pending if storyboard_id not in without_plan]
        if not pending:
            return _outcome(
                SKIPPED,
                "Niciun film nu are planul de cadre scris de model: " + held[0],
                held=held,
                skipped=skipped,
            )

    # A serial episode's shots are described from its beats before anything is bought (S8).
    # The serial stage already did it for a storyboard it built; this catches the one the
    # Owner's approval built, and one composed under an older series look. Once per look.
    for storyboard_id in pending:
        if storyboard_id in serial_ids:
            describe_serial_shots(engine, registry, storyboard_id, str(uuid4()))

    # In PRODUCTION nothing is bought in one piece: each film climbs its shooting sheet one
    # answered stair at a time (stills, the hero test shot, the rest of the motion), every
    # stair under the Owner's own yes for that sheet, and is assembled from its takes once
    # nothing is left to buy. The whole-film render below is the TEST environment's alone.
    if environment == "PRODUCTION":
        return _media_staircase(
            engine,
            settings,
            vault,
            registry,
            pending,
            held,
            serial_ids,
            environment,
            skipped=skipped,
            today=today,
        )

    # The whole-film path makes one factual film a day, as it always did: the first one the
    # story gate let through (a held older film no longer stands in its way).
    first_factual = [storyboard_id for storyboard_id in pending if storyboard_id not in serial_ids]
    pending = first_factual[:1] + [s for s in pending if s in serial_ids]

    images = image_provider(engine, vault)
    voice = tts_provider(engine, vault)
    produced: list[str] = []
    serial_assets: list[str] = []
    # A refusal carries the storyboard, the vendor's words and what the attempt cost.
    refused: list[dict[str, Any]] = []
    skipped_for_budget: list[str] = []
    # Films the Owner's mode will not let the studio buy on its own, with his reason.
    awaiting_owner: list[dict[str, Any]] = []
    # The correlation of the first film this stage had to ask him about, and the flag that
    # the Accountant owes him a letter about what is standing. Empty means nothing was asked.
    asked_correlation = ""
    budget_reason = ""
    narration_reviews = []
    costs_recorded = 0
    credit_lines: list[str] = []
    # Films this whole-film path refused because it would have bought from a real paid
    # vendor: their media is bought on the shooting sheet, step by step, under his yes.
    use_the_sheet: list[dict[str, Any]] = []
    for storyboard_id in pending:
        # The Owner's switch, read before each film and not once for the stage. The render
        # polls it between scenes and the runbook between stages, so a stop pressed during
        # the factual film's last scene used to start the serial's render regardless
        # (measured: two films, the stop set inside the first, both rendered).
        if stop_requested(engine):
            # His stop ends the stage, so the questions it already raised leave with it: the
            # runbook attempts no stage after a BLOCKED one, `_post_run` never runs, and a
            # question nobody told him about expires after `approval_expires_after_hours`.
            if asked_correlation:
                waiting_approvals_letter(engine, asked_correlation)
            return _outcome(
                BLOCKED,
                f"{stop_reason_words(engine)} Filmul următor nu a fost început.",
                assets=produced,
                serial_assets=serial_assets,
                stopped_storyboard=storyboard_id,
            )
        # The budget is asked before anything is generated for this film (runbook §7,
        # "reserve budget"), and now it is asked with a figure: `estimate_film_cost_micros`
        # prices the plan conservatively — the motion at the ceiling this render will be
        # given, the narration at the dearest active per-thousand price over the
        # storyboard's own voiceover. The check used to be `may_spend(engine, 0)` under a
        # comment that said the plan was costed, so a day at 14.99 of 15 USD started a full
        # film. The sum is *held*, not merely read: `reserve_spend` decides behind the write
        # lock and writes a row every budget counts until the film is in the books, so two
        # films asked in the same second cannot both be told the last ten dollars are free.
        # A refusal before the first film is the stage skipped, as it always was; after a
        # film has been made, the one refused is named — and either way the Accountant
        # writes to the Owner the same day, once, because a day without a film used to be
        # a SKIPPED line in a run summary nobody reads by itself.
        correlation = str(uuid4())
        # Read before this film's own hold is written, and not after: what the day still
        # allows is the ceiling this film may spend on motion, and the reservation about to
        # be made *is* that spend. Measured after the hold, a film asked for 12 USD would
        # have been given a ceiling of whatever was left after its own 12 were set aside —
        # nothing — and would have rendered stills. Other films' holds still count.
        left_usd = _budget_left_usd(engine, settings)
        plan_cost = estimate_film_cost_micros(
            engine, storyboard_id, environment=environment, settings=settings
        )
        # What the Owner's mode allows is asked before the money is held, not after: a hold
        # taken for a film the studio may not buy would sit against the day's budget until
        # the watchdog swept it. 31 puts a paid generation inside the budget at T2 and one
        # "beyond threshold" at T3, so the film's own estimate decides which question is
        # asked — and under SUPERVISED the T3 question writes the Approval the Owner answers.
        estimated_usd = float(plan_cost["usd"])
        dear = estimated_usd > settings.paid_generation_approval_threshold_usd
        # What the estimate could not price travels with it from here to all three places the
        # Owner can meet the figure — his question, the hold's note and the Accountant's
        # letter — in the one wording `unpriced_caveat` produces. It used to reach the note
        # alone, a row he never reads, so a SUPERVISED day asked him to approve 4.20 USD for a
        # film whose narration had been counted as nothing.
        caveat = plan_cost["caveat"]
        # The request is about *this* storyboard. Keyed by the action alone, the second and
        # dearer film of a SUPERVISED day reused the first film's row, so the Owner would
        # have been shown one question carrying the first film's price and his one answer
        # would have bought both.
        refusal = mode_refusal(
            engine,
            "media.paid_generation_over_threshold" if dear else "media.paid_generation",
            requester="video_editor",
            subject=storyboard_id,
            evidence=(
                f"storyboard {storyboard_id}, estimat {plan_cost['usd']} USD"
                + (f" ({caveat})" if caveat else "")
            ),
            cost_usd=estimated_usd,
        )
        if refusal is not None:
            awaiting_owner.append({"storyboard_id": storyboard_id, **refusal})
            # Remembered, not written: the letter is one a business date, so a letter sent
            # from inside this loop would be the day's only one and would name the first
            # film alone. It is written below, once the stage has finished asking. A refusal
            # that raised no question (MANUAL) is not remembered here either, because the
            # letter is about what is standing and nothing is.
            if refusal.get("approval_id") and not asked_correlation:
                asked_correlation = correlation
            continue
        hold = reserve_spend(
            engine,
            plan_cost["usd_micros"],
            f"film {storyboard_id}",
            correlation,
            note=f"estimat: {plan_cost['usd']} USD" + (f"; {caveat}" if caveat else ""),
        )
        if not hold["allowed"]:
            budget_refusal_letter(engine, hold["reason"], correlation)
            if not produced and not refused:
                return _outcome(SKIPPED, hold["reason"], budget=hold["period"])
            skipped_for_budget.append(storyboard_id)
            budget_reason = hold["reason"]
            continue
        # None when the plan priced at zero: there is nothing to hold, and nothing to settle.
        reservation_id = hold.get("reservation_id")
        if registry is not None and _has_language_model(registry):
            try:
                review = review_narration(engine, registry, storyboard_id, str(uuid4()))
                narration_reviews.append(
                    {"storyboard_id": storyboard_id, "verdict": review["verdict"]}
                )
            except (ReviewError, NoReviewer, ValueError) as exc:
                narration_reviews.append({"storyboard_id": storyboard_id, "error": str(exc)[:200]})
        # What the vendors say the account holds, read just before the money is spent, so the
        # render's cost can be proven from the credits and not only estimated from prices.
        balances_before = credit_balances(engine, vault)
        render_started = utc_now()
        try:
            # Channel policy, series rules, overrides and locked character voices decide per
            # scene; the Organization default is the fallback for scenes nothing else names.
            planned = render_plan(engine, vault, storyboard_id)
            # Real paid media is bought only through the shooting sheet's steps, under the
            # Owner's yes bound to its plan_hash, in every environment. In TEST this path
            # could still buy a whole film from the real Runway connection; it now refuses
            # whenever it would hand a real paid vendor to the render, and keeps working
            # with fakes and local stand-ins.
            vendors = legacy_render_vendors(
                engine,
                storyboard_id,
                image=planned.get("image") or images,
                image_chain=planned.get("image_chain"),
                tts=voice,
                tts_for_scene=planned.get("tts_for_scene"),
                voice_segments_for_scene=planned.get("voice_segments_for_scene"),
            )
            if vendors:
                raise PaidVendorRefused(vendors)
            result = assemble_video_job(
                engine,
                storyboard_id,
                str(uuid4()),
                storage_root=getattr(settings, "media_root", None),
                ffmpeg_path=settings.ffmpeg_path,
                # The day's registry reaches the mix: the Voice Artist plans the sound.
                registry=registry,
                # The plan resolves the hierarchy's image choice (Runway included); the
                # Organization-level adapter is the fallback for a plan that names none.
                image_adapter=planned.get("image") or images,
                # And the vendors it may fall back to: the Owner's approved alternative for
                # this purpose, at most one, already ordered for the environment. A studio
                # whose Owner approved none has a chain of one and behaves exactly as before.
                image_chain=planned.get("image_chain"),
                # The reference picture of the character the scene's cast names, so a face
                # the Owner locked is drawn from its own sheet rather than invented again per
                # scene. A character with a locked look and no readable reference refuses the
                # film below; a character with neither lock nor reference has none, and the
                # scene is drawn from the words as it always was.
                reference_for_scene=planned.get("reference_for_scene"),
                tts_adapter=voice,
                tts_adapter_for_scene=planned["tts_for_scene"],
                # One take per speaker in that character's voice, where the lines say who
                # speaks (the office serial); None for a scene read whole.
                voice_segments_for_scene=planned.get("voice_segments_for_scene"),
                # The model of each scene is chosen against what the scene requires, in
                # the environment the studio is in: a test buys the cheapest that can do the
                # job, production the least expensive that reaches the quality. A model a
                # level of the hierarchy named by hand is honoured as an override.
                # A real paid motion model is refused where it is chosen, before any use.
                motion_chooser=guard_motion_chooser(
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
                    else min(settings.motion_budget_usd, left_usd)
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
                # The Owner's delivery choices (captions burnt in) travel with the render.
                settings=settings,
            )
        except PaidVendorRefused as exc:
            # Nothing was bought: the refusal came before the render, or where a motion model
            # was chosen inside it, before that model was used. The film waits for its sheet.
            abandon_unfinished_renders(engine, storyboard_id, render_started, exc.message_ro)
            _release(
                engine, reservation_id, "folosește foaia de filmare (furnizor real)", correlation
            )
            use_the_sheet.append(
                {
                    "storyboard_id": storyboard_id,
                    "paid_vendors": exc.vendors,
                    "said": exc.message_ro,
                }
            )
            # The Owner is told once, in his words, why the day will not make this film by
            # itself and what would: his environment and his paid-media rule, both his to
            # change (A3). The film waits for him on the sheet, so it is never retired.
            _test_environment_letter(engine, storyboard_id, exc.vendors, correlation)
            if storyboard_id not in serial_ids:
                _note_film_state(
                    engine,
                    storyboard_id,
                    today,
                    status="USE_THE_SHEET",
                    refusal="PAID_VENDOR_IN_TEST",
                    reason=exc.message_ro,
                    moved=True,
                )
            continue
        except RenderStopped as exc:
            # The Owner's switch, read between two scenes: his decision, not a fault. The
            # runbook records the stage BLOCKED and the day PARTIAL, and opens no safe mode.
            #
            # His decision ends the film; it does not un-buy what the vendor had already
            # made. The assembler fails the job the same way here as for a refusal and keeps
            # the scenes it had built, so the attempt is costed from that record before the
            # hold is let go — same order, same reason as below: the estimate stops counting
            # exactly when the real cost of the attempt starts. A shot generated in the
            # minute before STOP read in the books as free until this line existed.
            failed_cost = _record_failed_attempt(engine, storyboard_id, correlation)
            costs_recorded += failed_cost
            # The hold goes with the film: money pledged to a film that was not made must
            # not sit against the day's budget until the watchdog's six hours are up.
            _release(engine, reservation_id, f"randare oprită: {error_words(exc)}", correlation)
            return _outcome(
                BLOCKED,
                f"{stop_reason_words(engine)} {sentence(error_words(exc))}",
                assets=produced,
                serial_assets=serial_assets,
                stopped_storyboard=storyboard_id,
                costs_recorded=costs_recorded,
            )
        except RenderEngineUnavailable as exc:
            _release(
                engine, reservation_id, f"randarea nu poate rula: {error_words(exc)}", correlation
            )
            return _outcome(
                SKIPPED,
                f"Randarea nu poate rula: {error_words(exc)}.",
                assets=produced,
                **error_fields(exc),
            )
        except ReferenceRequired as exc:
            # Not a vendor's refusal and not a fault: the studio refusing to invent the face
            # of a character whose look the Owner locked. The film is not made, so what was
            # bought before the refusal is costed and the hold goes back the same second —
            # the same order as a vendor refusal, for the same reason. Tomorrow's run tries
            # the film again; producing the character's reference set is the Owner's act.
            failed_cost = _record_failed_attempt(engine, storyboard_id, correlation)
            _release(
                engine, reservation_id, f"referință lipsă: {error_words(exc)}"[:120], correlation
            )
            refused.append(
                {
                    "storyboard_id": storyboard_id,
                    "error": str(exc)[:200],
                    "error_class": type(exc).__name__,
                    "said": error_words(exc),
                    "costs_recorded": failed_cost,
                }
            )
            costs_recorded += failed_cost
            logger.info("render_reference_missing", extra={"storyboard_id": storyboard_id})
            continue
        except MediaProviderError as exc:
            # A provider's refusal is that render's failure, not the day's: the storyboard
            # stays approved and unrendered, tomorrow's stage tries it again, and the Owner
            # reads why in the Director's report — not in a safe-mode banner.
            #
            # The vendor charges for the shot it generated and the narration it voiced
            # whether or not the film was finished — two lost shots cost six dollars on
            # 2026-09-16 and the books said nothing. So the attempt is costed first (from
            # what the failed job recorded of its production; nothing recorded is nothing
            # charged, and the count says so), and only then is the hold let go: the
            # estimate stops counting, the real cost of the attempt starts.
            failed_cost = _record_failed_attempt(engine, storyboard_id, correlation)
            _release(
                engine, reservation_id, f"randare refuzată: {error_words(exc)}"[:120], correlation
            )
            refused.append(
                {
                    "storyboard_id": storyboard_id,
                    "error": str(exc)[:200],
                    "error_class": type(exc).__name__,
                    "said": error_words(exc),
                    "costs_recorded": failed_cost,
                }
            )
            costs_recorded += failed_cost
            logger.info("render_refused", extra={"storyboard_id": storyboard_id})
            continue
        produced.append(result["output_asset_id"])
        if storyboard_id in serial_ids:
            serial_assets.append(result["output_asset_id"])
        measured = record_credit_spend(
            engine, result["job_id"], balances_before, credit_balances(engine, vault)
        )
        if measured:
            credit_lines.append(measured)
        # Into the books at once, at the stored price, so the day's close and the next
        # budget check see what was just spent. Only then is the hold settled: between the
        # two the film is counted twice rather than not at all, which is the error a budget
        # may make.
        try:
            costs_recorded += record_render_costs(
                engine,
                result["job_id"],
                correlation,
                alert_percent=settings.price_change_alert_percent,
            )["recorded"]
        except (EconomyError, KeyError):
            logger.info("render_cost_not_recorded", extra={"storyboard_id": storyboard_id})
        if reservation_id:
            settle_reservation(
                engine,
                reservation_id,
                settled_reference=f"render:{result['job_id']}",
                correlation_id=correlation,
            )

    # The Owner hears about every question this stage raised, and hears it here rather than at
    # the day's close. `waiting_approvals_letter` was called from `reconcile_day` alone, inside
    # `_post_run` — the day's last working stage — so a question raised at 05:30 reached him at
    # the run's end at best and not at all when the run stopped earlier; it then expired after
    # `approval_expires_after_hours` and that film was never made. Written once the stage has
    # finished asking rather than at the first refusal, because the letter is one a business
    # date: sent from inside the loop it named the first film and could never name the second,
    # and a SUPERVISED day makes two. `_letter_once_a_day` keeps the close from writing a
    # second one, and a stage that asked him nothing leaves his inbox silent.
    if asked_correlation:
        waiting_approvals_letter(engine, asked_correlation)

    if use_the_sheet and not produced and not refused and not awaiting_owner:
        return _outcome(
            SKIPPED,
            str(use_the_sheet[0]["said"])[:500],
            use_the_sheet=use_the_sheet,
            skipped=skipped,
        )

    if awaiting_owner and not produced and not refused:
        # Nothing was filmed and the mode is why: the stage could not run, which is SKIPPED
        # in the runbook's own vocabulary, with the Owner's reason and the request he answers.
        return _outcome(
            SKIPPED,
            awaiting_owner[0]["reason"],
            awaiting_owner=awaiting_owner,
            approval_id=awaiting_owner[0]["approval_id"],
            skipped=skipped,
        )

    substitutes = images is None or voice is None
    reason = f"{count(len(produced), 'videoclip randat', 'videoclipuri randate')}."
    if awaiting_owner:
        reason += (
            f" {count(len(awaiting_owner), 'nefilmat', 'nefilmate')}: {awaiting_owner[0]['reason']}"
        )
    if serial_assets:
        reason += " Episodul serialului a fost filmat."
    if skipped_for_budget:
        names = [
            "serialul" if board_id in serial_ids else "filmul factual"
            for board_id in skipped_for_budget
        ]
        reason += f" Nefilmate din lipsă de buget: {', '.join(names)} — {budget_reason}"
    if credit_lines:
        reason += " Credite măsurate la furnizor: " + " | ".join(credit_lines) + "."
    if refused:
        reason += f" {count(len(refused), *REFUSED_RENDERS)}: {refused[0]['said']}."
    if use_the_sheet:
        reason += f" {use_the_sheet[0]['said']}"
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
        serial_assets=serial_assets,
        skipped_for_budget=skipped_for_budget,
        awaiting_owner=awaiting_owner,
        used_substitutes=substitutes,
        narration_reviews=narration_reviews,
        costs_recorded=costs_recorded,
        # Each refused render with the vendor's own text and the exception's class: the
        # reason above says it in Romanian, and this is what a person diagnosing it reads.
        refused=refused,
        use_the_sheet=use_the_sheet,
        skipped=skipped,
    )


# ---------------------------------------------------------------------- edit and QC --


def _edit_and_qc(
    engine: Engine,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
    *,
    vault: Any = None,
    asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Measure every rendered file that has not been measured yet (or only ``asset_ids``).

    Quality control is measured, never opined. What follows a failure is first the Video
    Editor's diagnosis, then the Director's decision (`director_decides_failed_film`,
    2026-10-10): she judges every finding and accepts the film, has only the scenes she lists
    redone (bought under the Owner's rule and within his limits, then measured again and read
    by her again), or closes it, and the Owner gets her letter in Romanian. Nothing is redone
    before she has read the report; when she cannot decide, nothing is redone at all.
    """
    superseded = _repair_intermediates(engine)
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
            if asset.id not in checked and asset.id not in superseded
        ][:BATCH]
    if asset_ids is not None:
        # One film's own files (FILM_CONTINUE): measured whatever else is waiting.
        pending = [
            asset_id
            for asset_id in dict.fromkeys(asset_ids)
            if asset_id not in checked and asset_id not in superseded
        ]

    if not pending:
        return _outcome(COMPLETED, "Niciun material nou de verificat.", checked=0)

    passed, failed = 0, 0
    diagnoses = []
    passed_assets: list[str] = []
    failed_assets: list[str] = []
    repairs: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for asset_id in pending:
        # The Owner's ceiling on scenes that fell back to a slow push travels with the
        # measurement; without it quality control assumes half the scenes. So do the two
        # things it takes to look at the pictures rather than only at the container: the
        # registry, so an employee whose model declares vision can be asked whether each
        # scene is a picture at all and shows what it was asked for, and the encoder, which
        # cuts the frame it looks at. Without either the picture and character checks report
        # NOT_APPLICABLE with the reason and the film's verdict is exactly what the other
        # gates left it — the stage held both all along and passed neither.
        report = evaluate_media_qc(
            engine,
            asset_id,
            str(uuid4()),
            settings=settings,
            registry=registry,
            ffmpeg_path=settings.ffmpeg_path if settings is not None else None,
        )
        from app.media.assembler import release_after_qc  # noqa: PLC0415 - media imports runbook

        release_after_qc(engine, asset_id, str(uuid4()))
        # The Director's lessons whose scenes this film passes worked (2026-10-12 review).
        _confirm_lessons_quietly(engine, report.get("id"))
        if report["status"] == "PASSED":
            passed += 1
            passed_assets.append(asset_id)
            continue
        failed += 1
        failed_assets.append(asset_id)
        diagnosis: dict[str, Any] | None = None
        if registry is not None and _has_language_model(registry):
            try:
                diagnosis = review_failed_render(engine, registry, report["id"], str(uuid4()))
                diagnoses.append(
                    {"report_id": report["id"], "correction": diagnosis.get("correction")}
                )
            except (ReviewError, NoReviewer, ValueError) as exc:
                diagnoses.append(
                    {
                        "report_id": report["id"],
                        "error": str(exc)[:200],
                        "error_class": type(exc).__name__,
                    }
                )
        # The Director reads the report (and Kael's diagnosis) before anything is redone, and
        # decides: accept, repair only what she lists, or close (2026-10-10, babcf272).
        decided = director_decides_failed_film(
            engine, settings, vault, registry, str(report["id"]), asset_id, diagnosis=diagnosis
        )
        decisions.append(_decision_summary(decided))
        repairs.extend(decided.get("repairs") or [])
        if decided.get("passed_asset"):
            passed_assets.append(str(decided["passed_asset"]))
    reason = (
        f"{passed} {'a trecut' if passed == 1 else 'au trecut'} QC, "
        f"{failed} {'a picat' if failed == 1 else 'au picat'}."
    )
    if decisions:
        reason += " " + _decisions_words(decisions)
    return _outcome(
        COMPLETED,
        reason,
        passed=passed,
        failed=failed,
        diagnoses=diagnoses,
        passed_assets=passed_assets,
        failed_assets=failed_assets,
        decisions=decisions,
        repairs=[_repair_summary(item) for item in repairs],
    )


# ------------------------------- a film that failed QC is decided by the Director --
#
# 2026-10-02 (CONTINUE_REDOS_E2E, A8). A film that failed quality control used to be abandoned:
# the Video Editor's priced proposals were filed and never applied. From then on, for a film
# assembled from its takes, the free fixes (a re-encode from the same takes, a card recomposed,
# the sound remastered) and a scene's paid redo (a new picture, new motion) were applied by
# code, every scene the report named: the paid ones only through `redo_scene`, whose purchase
# passes `may_act` for media.scene_redo with the redo's own plan_hash (his paid-media rule, the
# mode, the budgets, the film's ceiling, the lease), within `film_max_paid_redos_per_scene` and
# `film_max_paid_redos`.
#
# 2026-10-10 (film babcf272, report d4ea68d2). That mechanical repair redid scenes 1 and 2
# unasked: the report had read the studio's own burned-in subtitles as «text or a logo» on
# every scene and the Owner's approved choice of a dark tunnel as a breach of the bible, and the
# repair retired the still, the motion and the test shot he had approved, rewrote both scenes'
# prompts and opened RunPod sessions, while the one real flaw (scene 5, three stacked panels)
# waited behind them. The Owner: the agents check one another and the Director decides alone.
# So the Director reads every failed report first (`director_decides_failed_film`): her
# verdict per finding, then ACCEPT, REPAIR (only her list, through the same paid path and
# limits; never a take he approved) or CLOSE, and her letter to him. With no model, nothing is
# redone: the report waits for her.

#: One repair of one failed film: what was applied, bought, asked, refused, and the verdict.
QC_REPAIR_EVENT = "runbook.qc_repair"
#: One scene's paid redo bought by a repair, counted against the Owner's limits.
QC_PAID_REDO_EVENT = "runbook.qc_paid_redo"
#: The mechanical repair's letter until 2026-10-10 (still in his inbox for older films); the
#: Director's letter is `app.media.director_qc.LETTER_KIND`.
QC_LETTER_KIND = "owner_qc_failed"
#: The free fixes, in the order they are applied: the picture first, the sound last, so the
#: remastered mix is the one that reaches the final film.
FREE_FIX_ORDER = ("encode", "card")
PAID_REDO_WORDS = {"still": "imaginea", "motion": "mișcarea"}


def _repair_intermediates(engine: Engine) -> set[str]:
    """The files a repair made on its way to its last film: never measured or repaired again
    by themselves (their last film is), so one repair never fans out into several."""
    made: set[str] = set()
    with Session(engine) as session:
        for event in session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == QC_REPAIR_EVENT)
        ):
            payload = event.payload if isinstance(event.payload, dict) else {}
            final = payload.get("new_asset")
            made.update(str(a) for a in payload.get("made") or [] if a and a != final)
    return made


#: How many times a film's free fixes (audio, encode, card — 0 credits) may be made in all.
#: The Owner, 2026-10-12 22:50: «Dacă "decide Proprietarul" înseamnă că nu este o agenție
#: autonomă!» — a free fix costs nothing, so the Director makes it again (no card to him);
#: the cap only keeps a fix that cannot work from running forever, and past it the defect is
#: the developer's (`_free_fix_defect_note`).
FREE_FIXES_PER_FILM = 3


def _free_fix_rounds(session: Session, storyboard_id: str) -> int:
    """How many of the film's repairs applied a free fix (their ``applied`` list)."""
    rounds = 0
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == QC_REPAIR_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("applied"):
            rounds += 1
    return rounds


def _made_by_free_fix(session: Session, storyboard_id: str, asset_id: str) -> bool:
    """Whether this very film came out of a repair that applied a free fix: the same fix on
    it gives the same film again (audio, encode and cards are deterministic), so a free fix is
    made again only after something else changed the film (a paid redo's new take)."""
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type == QC_REPAIR_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        made = {str(a) for a in [payload.get("new_asset"), *(payload.get("made") or [])] if a}
        if payload.get("applied") and asset_id in made:
            return True
    return False


def _free_fixes_spent(session: Session, storyboard_id: str, asset_id: str | None = None) -> bool:
    """Whether no free fix may be made for this film now: all `FREE_FIXES_PER_FILM` were made,
    or the film in hand is itself what a free fix made (`_made_by_free_fix`: repeating it would
    repeat the same result, the Owner's «nu să facă aceeași greșeală la nesfârșit»)."""
    if not storyboard_id:
        return False
    if _free_fix_rounds(session, storyboard_id) >= FREE_FIXES_PER_FILM:
        return True
    return bool(asset_id) and _made_by_free_fix(session, storyboard_id, str(asset_id))


def _repaired_assets(session: Session) -> set[str]:
    """Every film a repair started from or produced: none is repaired for free again."""
    seen: set[str] = set()
    for event in session.scalars(
        select(DomainEvent).where(DomainEvent.event_type == QC_REPAIR_EVENT)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        seen.update(str(a) for a in [payload.get("of_asset"), *(payload.get("made") or [])] if a)
    return seen


def _round_began(session: Session, event: DomainEvent) -> str:
    """When a paid redo round began: its own ``started_at`` (written since 2026-10-10), else
    the first thing its repair wrote (the round's event is written after its purchases, under
    the repair's correlation)."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    if payload.get("started_at"):
        return str(payload["started_at"])
    first = session.scalar(
        select(func.min(DomainEvent.timestamp)).where(
            DomainEvent.correlation_id == event.correlation_id
        )
    )
    return str(first or event.timestamp)


def _round_delivered(
    session: Session, storyboard_id: str, scene: int, since: str, until: str | None = None
) -> bool:
    """Whether a paid round of the scene that began at ``since`` delivered something: a still or
    shot of the scene made after it that came with its file or may still come (the history
    rule of `assembler._delivered_since`: APPROVED, PAID, SUBMITTED, or REJECTED with its
    file), or a candidate written since into an older row (`director_qc.bought_since`) that
    carries its file. ``until`` is when the scene's next round began: what that round made is
    its own, never this one's (`_round_windows`)."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook
    from app.media.assembler import _delivered_since  # noqa: PLC0415 - media imports runbook

    if _delivered_since(session, storyboard_id, scene, since, [], until=until):
        return True
    return any(
        row.sha256 and row.status in ("APPROVED", "PAID", "REJECTED")
        for row in director_qc.bought_since(
            session, storyboard_id, scene, director_qc.REJOIN, since, until
        )
    )


def _round_windows(
    session: Session, storyboard_id: str
) -> dict[int, list[tuple[DomainEvent, str, str | None]]]:
    """Per scene, its paid redo rounds in the order they began, each with when it began and
    when the scene's next round began (None for the newest): what a round delivered is read
    inside that window only. A motion that ``continues`` its still's round is that round, not
    one of its own, and opens no window.

    2026-10-12, 1c038a99 («The Particle That Shouldn't Exist»), scene 5: five rounds were
    counted and his cap of five fell, but two of them were stopped by a restart before anything
    was asked, one was cancelled after a second (14 credits of GPU, no picture), and only the
    fourth and fifth made anything — read without a window, the fourth round's still and clip
    «delivered» the three empty rounds before it, since they came after each one began. The
    Owner: «5 refaceri? Pentru o poză în mișcare? ... Nu ai cum să faci de 5 ori aceeași
    greșeală!» — those were five events, not five pictures."""
    began_by_scene: dict[int, list[tuple[DomainEvent, str]]] = {}
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == QC_PAID_REDO_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        scene = payload.get("scene_index")
        if not isinstance(scene, int) or payload.get("continues"):
            continue
        began_by_scene.setdefault(scene, []).append((event, _round_began(session, event)))
    windows: dict[int, list[tuple[DomainEvent, str, str | None]]] = {}
    for scene, rounds in began_by_scene.items():
        rounds.sort(key=lambda item: item[1])
        windows[scene] = [
            (event, began, rounds[index + 1][1] if index + 1 < len(rounds) else None)
            for index, (event, began) in enumerate(rounds)
        ]
    return windows


def _paid_redo_rounds(session: Session, storyboard_id: str) -> dict[int, int]:
    """The paid redo rounds of each scene, counted against his limits. The motion that follows
    its scene's new still (its event ``continues`` the still's round) is the same round, not
    another: a still bought in one walk and approved later by his look (or the vendor's late
    delivery) would otherwise spend the scene's one round and leave the new still with no motion,
    so never in a film (2026-10-10 review).

    A round that delivered nothing is not counted (`_round_delivered`; 2026-10-10, babcf272: the
    mechanical repair's two morning rounds, scenes 1 and 2, ended with every candidate REFUSED,
    the GPU forced off, and spent the film's two paid redos, so the Director's repair of the
    one real flaw, scene 5's three panels, was refused and she was steered to accept it), and
    each round is read inside its own window (`_round_windows`, 2026-10-12: rounds are counted
    by the pictures they made, not by their events). What a round may buy is still the Policy
    Kernel's, the budgets' and the film ceiling's."""
    rounds: dict[int, int] = {}
    for scene, windows in _round_windows(session, storyboard_id).items():
        delivered = sum(
            1
            for _event, began, until in windows
            if _round_delivered(session, storyboard_id, scene, began, until)
        )
        if delivered:
            rounds[scene] = delivered
    return rounds


def _open_still_rounds(session: Session, storyboard_id: str) -> dict[int, str]:
    """Per scene, the paid round whose new still was bought and whose motion was not yet
    (``open_motion``), by its event id: a motion of that scene continues it rather than
    starting a round of its own. A motion that continued it, or a newer round of the scene,
    closes it; a round that delivered nothing (`_round_delivered`) has no new still for a
    motion to start from, and opens nothing."""
    events = list(
        session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type == QC_PAID_REDO_EVENT,
                DomainEvent.aggregate_id == storyboard_id,
            )
            .order_by(DomainEvent.sequence)
        )
    )
    closed = {
        str(payload.get("continues"))
        for event in events
        if isinstance(payload := event.payload, dict) and payload.get("continues")
    }
    # Each round is read inside its own window (`_round_windows`): the next round's new still
    # does not make an empty round «delivered» and open.
    until_of = {
        str(event.event_id): (began, until)
        for windows in _round_windows(session, storyboard_id).values()
        for event, began, until in windows
    }
    open_rounds: dict[int, str] = {}
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        scene = payload.get("scene_index")
        if not isinstance(scene, int) or payload.get("continues"):
            continue
        began, until = until_of.get(str(event.event_id), (_round_began(session, event), None))
        if (
            payload.get("open_motion")
            and str(event.event_id) not in closed
            and _round_delivered(session, storyboard_id, scene, began, until)
        ):
            open_rounds[scene] = str(event.event_id)
        else:
            open_rounds.pop(scene, None)
    return open_rounds


def _repair_summary(repair: dict[str, Any]) -> dict[str, Any]:
    keys = ("storyboard_id", "of_asset", "new_asset", "requalified", "applied", "bought", "asked")
    return {key: repair.get(key) for key in keys}


#: The most rounds of the Director's review one film gets in one walk: a round is her reading
#: of one report and what she decided; a repair that made a new film is measured and read by
#: her again. The Owner's per-scene and per-film paid limits end the walk sooner; this ends a
#: loop they do not see (a decision of which nothing could be done, read once more).
DIRECTOR_QC_ROUNDS = 4
#: What a paid redo she decided says on the Owner's question, should his rule ask him.
DIRECTOR_REDO_NOTE = "Controlul calității a picat scena; refacere hotărâtă de Directoare."
#: A redo that would retire a take the Owner approved as final: refused before anything is
#: priced. Since 2026-10-11 (his card «Directoarea poate reface și ce am aprobat eu») her
#: confirmed repair replaces an approval he did not mark final, and tells him.
OWNER_APPROVED_REDO = "OWNER_APPROVED"


def director_decides_failed_film(
    engine: Engine,
    settings: Settings | None,
    vault: Any,
    registry: ProviderRegistry | None,
    report_id: str,
    asset_id: str,
    *,
    diagnosis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The Director decides one film that failed QC, and what she decided is carried out.

    2026-10-10, film babcf272: the mechanical repair redid every scene the report named, the
    Owner's approved takes with them, while the scenes' only real flaw was one still of panels
    and the rest was the studio's own subtitles read as text. Now each round is her reading of
    the report (`app.media.director_qc.film_qc_context`, `review_film_qc`): a verdict per
    finding and one decision. ACCEPT writes the PASSED report her decision stands on (the
    publishing gate then lets the film through; the rights and factual gates still run);
    REPAIR redoes only her list, never a take he approved (`_director_repairs`), and a new film
    is measured and read by her again; CLOSE closes the film. With no model, or an answer that
    did not validate twice, nothing is redone: the report waits in her inbox and the watchdog
    asks her again (`app.workflows.passes.director_qc_review`). Never raises.

    Returns ``outcome`` (the last round's: ACCEPTED, ACCEPT_REFUSED, REPAIRED, ASKED,
    BOUGHT_WAITING, CLOSED, NOTHING_DONE, WAITING), ``passed_asset`` (the film that may now be
    published, or None),
    ``rounds`` and ``repairs`` (what each repair applied, bought, asked and refused)."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    outcome: dict[str, Any] = {
        "report_id": report_id,
        "of_asset": asset_id,
        "outcome": None,
        "passed_asset": None,
        "rounds": [],
        "repairs": [],
    }
    report, asset = report_id, asset_id
    read_again = False
    for number in range(DIRECTOR_QC_ROUNDS):
        try:
            step = _director_round(
                engine,
                settings,
                vault,
                registry,
                report,
                asset,
                diagnosis=diagnosis if number == 0 else None,
            )
        except Exception as exc:  # noqa: BLE001 - a fault waits for her; it never redoes
            logger.warning(
                "director_qc_round_failed",
                extra={"report_id": report, "error": type(exc).__name__},
            )
            try:
                step = director_qc.wait_for_director(
                    engine,
                    {"report_id": report, "media_asset_id": asset, **_film_of(engine, asset)},
                    error_words(exc),
                    str(uuid4()),
                )
            except Exception as again:  # noqa: BLE001 - the stage's own record says it
                logger.warning(
                    "director_qc_wait_not_recorded",
                    extra={"report_id": report, "error": type(again).__name__},
                )
                step = {"outcome": "WAITING", "reason": error_words(exc)}
        outcome["outcome"] = step.get("outcome")
        outcome["rounds"].append(
            {
                "report_id": report,
                "asset_id": asset,
                "outcome": step.get("outcome"),
                "decision": (step.get("decision") or {}).get("decision"),
                "reason": step.get("reason"),
                "letter_id": step.get("letter_id"),
            }
        )
        repair = step.get("repair")
        if repair:
            outcome["repairs"].append(repair)
        kind = step.get("outcome")
        if kind == "ACCEPTED":
            outcome["passed_asset"] = asset
            break
        if kind == "REPAIRED" and repair:
            if repair.get("requalified") == "PASSED" and repair.get("new_asset"):
                outcome["passed_asset"] = str(repair["new_asset"])
                break
            if repair.get("requalified") == "FAILED" and repair.get("requalified_report_id"):
                # The film her repair made failed too: she reads its report next — in a walk
                # of its own when another film waits on the one worker (2026-10-12: the
                # cyclotron's rounds held the worker an hour while the serial's walk waited).
                new_report, new_asset = (
                    str(repair["requalified_report_id"]),
                    str(repair["new_asset"]),
                )
                yielded = _yield_next_round(engine, asset, new_report)
                if yielded:
                    outcome["yielded"] = yielded
                    break
                report, asset = new_report, new_asset
                continue
            break
        if (
            kind == "NOTHING_DONE"
            and not read_again
            and not (repair or {}).get("card_id")
            and not (repair or {}).get("developer_note")
        ):
            # Nothing of her list could be done (his approved takes, the limits, a free fix
            # already made, her second look overturning the refusal): she reads the report once
            # more, knowing why. Not when his cap stopped it and his card asks him what becomes
            # of the film (2026-10-12): she is not asked again until he answers, as the
            # review pass does (`workflows.passes.director_qc_review`).
            read_again = True
            continue
        break
    return outcome


def _yield_next_round(engine: Engine, asset_id: str, new_report: str) -> str | None:
    """Queue her next round (the repaired film's new report) as a continuation of its own,
    when another film's continuation waits in the queue; None when nobody waits (the round
    runs here, as before) or the continuation could not be queued (TEST). The key is the
    review pass's for that report (`passes.director_qc_review`), so the two never queue it
    twice; the worker then serves the films in turn."""
    from app.services import FILM_CONTINUE_TASK  # noqa: PLC0415
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415 - workflows import runbook

    storyboard_id = str(_film_of(engine, asset_id).get("storyboard_id") or "")
    if not storyboard_id:
        return None
    try:
        with Session(engine) as session, session.begin():
            others = [
                task
                for task in session.scalars(
                    select(TaskQueueItem).where(
                        TaskQueueItem.task_type == FILM_CONTINUE_TASK,
                        TaskQueueItem.status == "QUEUED",
                    )
                )
                if str((task.payload or {}).get("storyboard_id") or "") != storyboard_id
            ]
            if not others:
                return None
            lock_for_write(session)
            return queue_film_continue(
                session,
                storyboard_id,
                key=f"film-continue-{storyboard_id}-director-qc-{new_report}-0",
                payload={"cause": f"director_qc:{new_report}", "report_id": new_report},
            )
    except SQLAlchemyError:
        logger.warning("director_qc_round_not_yielded", extra={"storyboard_id": storyboard_id})
        return None


def _film_of(engine: Engine, asset_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id).limit(1)
        )
        return {"storyboard_id": job.storyboard_id if job is not None else None}


#: The Owner, 2026-10-15 12:20Z: «Randările odată făcute, de maxim 3x pentru fiecare imagine sau
#: mișcare». A scene's stills, and its shots, are made at most this many times (the first
#: purchase, the re-rolls and the paid redos all counted, `_renders_made`): past it nothing of
#: that layer is bought for the scene again, and the best take there is stands.
RENDERS_PER_LAYER = 3
#: ...and a failed report's repair is bought at most this many times (`_report_repair_rounds`:
#: her BOUGHT_WAITING decisions on it). Past either limit her list is not bought and the film
#: ships as it stands: «Nu putem să ne învârtim la nesfârșit la același subiect, cheltuim toți
#: banii și fără să publicăm!» — her ACCEPT under the cap (`director_qc.accepted_by_cap`),
#: no card to him (the card «ce se întâmplă cu filmul» of 2026-10-12 is answered for good).
REPAIR_ROUNDS_PER_REPORT = 2


def _renders_made(session: Session, storyboard_id: str) -> dict[tuple[int, str], int]:
    """How many times each scene's picture («still») and its shot («motion») were made, by
    (scene, layer): every paid request among the scene's takes, whatever became of it
    (`assembler._paid_attempts`: a stills request's candidates share its task id)."""
    from app.media.assembler import SHOT_TAKE_KINDS, _paid_attempts  # noqa: PLC0415
    from app.media.models import SceneTake  # noqa: PLC0415

    by_scene: dict[tuple[int, str], list[SceneTake]] = {}
    for row in session.scalars(select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)):
        if row.kind == "still":
            layer = "still"
        elif row.kind in SHOT_TAKE_KINDS:
            layer = "motion"
        else:
            continue
        by_scene.setdefault((int(row.scene_number), layer), []).append(row)
    return {key: _paid_attempts(rows, key[1]) for key, rows in by_scene.items()}


def _report_repair_rounds(session: Session, report_id: str) -> int:
    """How many times her repair of this report bought something (her BOUGHT_WAITING
    decisions on it)."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    return sum(
        1
        for event in session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == director_qc.DECISION_EVENT,
                DomainEvent.aggregate_id == report_id,
            )
        )
        if str((event.payload or {}).get("outcome") or "") == "BOUGHT_WAITING"
    )


def _redo_allowance(
    engine: Engine, settings: Settings | None, reading: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """The paid redos his limits allow the film ({per_scene, per_film, spent, open_motion}:
    the scenes whose new still was bought and whose motion may still follow in that round),
    and whether a free fix was already applied to its line (it is done once)."""
    storyboard_id = str(reading.get("storyboard_id") or "")
    with Session(engine) as session:
        spent = _paid_redo_rounds(session, storyboard_id) if storyboard_id else {}
        open_rounds = _open_still_rounds(session, storyboard_id) if storyboard_id else {}
        free_used = _free_fixes_spent(
            session, storyboard_id, str(reading.get("media_asset_id") or "")
        )
    limits = {
        "per_scene": int(getattr(settings, "film_max_paid_redos_per_scene", 1)),
        "per_film": int(getattr(settings, "film_max_paid_redos", 2)),
        "spent": spent,
        "open_motion": sorted(open_rounds),
    }
    return limits, free_used


def _director_round(
    engine: Engine,
    settings: Settings | None,
    vault: Any,
    registry: ProviderRegistry | None,
    report_id: str,
    asset_id: str,
    *,
    diagnosis: dict[str, Any] | None,
) -> dict[str, Any]:
    """One reading of one report by the Director, and what she decided, carried out.

    A report she already decided is not read again. Her REPAIR that waited on something
    outside her (`director_qc.PENDING_OUTCOMES`: his answer to the paid question, a take bought
    for her list waiting for his look or the vendor) is carried on once that came
    (`decision_state` ``ready``): only what is left of her list, never what was bought for it
    already (``bought_so_far``), and she is not asked a second time; while it still waits it
    stands. One whose wait lapsed (his no, an expired question, his look rejecting what was
    bought) is hers to read again, with what came of it (2026-10-10 review). Any other final
    decision stands.

    Candidates bought for her REPAIR that a gate refused are looked at by her first
    (`_director_looks`): her choice makes the decision ready and it is carried on in this
    round; her REJECT lapses it and she reads the report again, her reasons in front of her."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    correlation = str(uuid4())
    standing = director_qc.decision_state(engine, report_id)
    if not (standing["pending"] and standing["look"]):
        return _director_reads(
            engine, settings, vault, registry, report_id, asset_id, standing, diagnosis, correlation
        )
    looked = _director_looks(
        engine, settings, registry, report_id, dict(standing["decision"] or {}), correlation
    )
    if looked["outcome"] == "WAITING":
        return looked
    step = _director_reads(
        engine,
        settings,
        vault,
        registry,
        report_id,
        asset_id,
        director_qc.decision_state(engine, report_id),
        diagnosis,
        correlation,
    )
    return {**step, "look": looked}


def _director_reads(
    engine: Engine,
    settings: Settings | None,
    vault: Any,
    registry: ProviderRegistry | None,
    report_id: str,
    asset_id: str,
    standing: dict[str, Any],
    diagnosis: dict[str, Any] | None,
    correlation: str,
) -> dict[str, Any]:
    """`_director_round` once her looks are done: a decision that stands, one carried on, or
    her reading of the report (``standing``: `director_qc.decision_state`).

    A REPAIR carried on is first read again under today's rules (2026-10-12 review: one decided
    before that day's rules was carried out as it was): her reading of the report is rebuilt,
    the redos those rules refuse are dropped and said (`director_qc.resume_repairs`), and when
    nothing of her list is left she reads the report again. Before she reads a report, her
    earlier lessons whose scenes it passes are confirmed (`director_qc.confirm_lessons`)."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    if standing["final"]:
        decided = dict(standing["decision"] or {})
        if standing["pending"] and standing["ready"]:
            reading = failed_render_reading(engine, report_id)
            carried = {
                key: value
                for key, value in decided.items()
                if key not in ("outcome", "final", "done", "passed_report_id")
            }
            dropped: list[dict[str, Any]] = []
            if str(carried.get("decision") or "") == "REPAIR":
                limits, free_used = _redo_allowance(engine, settings, reading)
                context = director_qc.film_qc_context(
                    engine, reading, limits=limits, free_used=free_used
                )
                kept, dropped = director_qc.resume_repairs(carried, context)
                carried["repairs"] = kept
            if str(carried.get("decision") or "") != "REPAIR" or carried["repairs"]:
                return _carry_out(
                    engine,
                    settings,
                    vault,
                    registry,
                    reading,
                    {**carried, "resumed": True, "dropped_on_resume": dropped},
                    correlation,
                )
            # Nothing of her list is left under today's rules: the report is hers again.
            logger.info(
                "director_repair_dropped_on_resume",
                extra={"report_id": report_id, "dropped": len(dropped)},
            )
        else:
            return {
                "outcome": standing["outcome"],
                "decision": decided,
                "standing": True,
                "reason": (
                    "Refacerea hotărâtă de Directoare așteaptă răspunsul tău sau aprobarea "
                    "preluării cumpărate."
                    if standing["pending"]
                    else "Directoarea a decis deja acest raport."
                ),
            }
    _confirm_lessons_quietly(engine, report_id)
    reading = failed_render_reading(engine, report_id)
    limits, free_used = _redo_allowance(engine, settings, reading)
    context = director_qc.film_qc_context(
        engine, reading, diagnosis=diagnosis, limits=limits, free_used=free_used
    )
    if registry is None or not _has_language_model(registry):
        return director_qc.wait_for_director(
            engine, reading, "niciun model de limbaj nu este configurat", correlation
        )
    try:
        review = review_film_qc(engine, registry, context, correlation)
    except (NoReviewer, ReviewError, ValueError) as exc:
        return director_qc.wait_for_director(engine, reading, error_words(exc), correlation)
    decided = {
        "report_id": report_id,
        "media_asset_id": asset_id,
        "storyboard_id": reading.get("storyboard_id"),
        "decided_by": director_qc.DIRECTOR,
        "agent_id": review["agent_id"],
        "agent_name": review["agent_name"],
        "run_id": review["run_id"],
        "decision": review["decision"],
        "summary": review["summary"],
        "verdicts": director_qc.annotate_verdicts(review["verdicts"], context),
        "repairs": review["repairs"],
        "resumed": False,
        # The scope of the lessons she writes (serial or factual).
        "film_kind": (context.get("film") or {}).get("kind"),
    }
    # Her lessons are kept before anything is rewritten or bought (2026-10-12, the Owner: «să
    # înțeleagă de ce apar defectele»): the rewrite of her REPAIR's scenes already reads them.
    decided["lessons_recorded"] = director_qc.record_lessons(engine, decided)
    # Each under its own source (round 3 of the 2026-10-12 review): her second look can then
    # withdraw the lesson of a finding it overturned, and a later film confirm only its own.
    decided["lesson_sources"] = {
        lesson: source
        for lesson, source in director_qc.lesson_sources(decided).items()
        if lesson in decided["lessons_recorded"]
    }
    storyboard_id = str(reading.get("storyboard_id") or "")
    if review["decision"] == "REPAIR" and storyboard_id:
        # A take bought for her earlier REPAIR of this film, approved and in no film yet
        # (`director_qc.bought_not_in_film`): her REPAIR of that scene carries it on (the film
        # rejoined, or its motion) as bought for this decision, and never buys it again.
        listed = {
            item.get("scene_index")
            for item in review["repairs"]
            if item.get("redo") in ("still", "motion")
        }
        with Session(engine) as session:
            bought_before = [
                item
                for item in director_qc.bought_not_in_film(session, storyboard_id)
                if item["scene_index"] in listed
            ]
        if bought_before:
            decided["bought_so_far"] = [
                [item["kind"], item["scene_index"]] for item in bought_before
            ]
            decided["started_at"] = min(str(item["since"]) for item in bought_before)
    return _carry_out(engine, settings, vault, registry, reading, decided, correlation)


def _director_looks(
    engine: Engine,
    settings: Settings | None,
    registry: ProviderRegistry | None,
    report_id: str,
    decision: dict[str, Any],
    correlation: str,
) -> dict[str, Any]:
    """The Director looks at the candidates bought for her REPAIR that the stills gate or the
    clip QC refused, and decides (2026-10-10, the Owner: «El ar trebui să hotărască dacă poza
    este bună sau nu»): she is shown each one with the gate's own reasons
    (`director_qc.look_entries`, `review_bought_pictures`) and chooses one, which becomes the
    scene's take approved by her, or rejects them all, and the report is hers again at once
    (`director_qc.record_look`); the Owner gets a STATUS letter (`director_qc.look_letter`).
    Nothing is bought here.

    With no model, no seeing model or an answer that did not validate twice, nothing is
    chosen: the report waits (`wait_for_director`, the watchdog's back-off), and the decision
    lapses after `director_qc.BOUGHT_WAIT_DAYS` as before. Returns ``outcome`` LOOKED (with
    ``looks``) or WAITING."""
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    reading = {
        "report_id": report_id,
        "media_asset_id": decision.get("media_asset_id"),
        "storyboard_id": decision.get("storyboard_id"),
    }

    def wait(why: str) -> dict[str, Any]:
        return director_qc.wait_for_director(
            engine,
            reading,
            why,
            correlation,
            words=(
                "Directoarea nu a putut privi variantele cumpărate pentru refacerea ei, pe care "
                f"controlul studioului le refuzase ({why}); studioul o întreabă din nou la "
                "trecerea următoare."
            ),
        )

    with tempfile.TemporaryDirectory(prefix="director_look_") as work:
        entries = director_qc.look_entries(
            engine,
            decision,
            ffmpeg_path=getattr(settings, "ffmpeg_path", None),
            work_dir=Path(work),
        )
    looks: list[dict[str, Any]] = []
    for entry in entries:
        answer: dict[str, Any] | None = None
        if entry["offered"]:
            if registry is None or not _has_language_model(registry):
                return wait("niciun model de limbaj nu este configurat")
            try:
                answer = review_bought_pictures(
                    engine, registry, entry["shown"], entry["images"], correlation
                )
            except (NoReviewer, ReviewError, ValueError) as exc:
                return wait(error_words(exc))
        look = director_qc.record_look(engine, decision, entry, answer, correlation)
        try:
            look["letter_id"] = director_qc.look_letter(engine, decision, look, correlation)
        except Exception as exc:  # noqa: BLE001 - her look stands; the letter is logged
            logger.warning("director_look_letter_not_written", extra={"error": type(exc).__name__})
        looks.append(look)
    return {"outcome": "LOOKED", "looks": looks}


def _carry_out(
    engine: Engine,
    settings: Settings | None,
    vault: Any,
    registry: ProviderRegistry | None,
    reading: dict[str, Any],
    decided: dict[str, Any],
    correlation: str,
) -> dict[str, Any]:
    """Her decision, done as she decided it and recorded (`media.director_qc_decision`), with
    the Owner's letter once it is final; her inbox note about the report is then answered.

    A REPAIR that bought something and made no film yet is BOUGHT_WAITING (2026-10-10 review:
    a new still bought and waiting for his look was recorded «nothing could be done», with no
    letter to him about the money and a note in her inbox saying nothing was done): he gets the
    letter that lists the purchase, and the walk carries on her list once the take is approved.
    ``bought_so_far`` (the (redo, scene) bought for this decision, across its resumptions) is
    what a resumption never buys again."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    report_id = str(reading["report_id"])
    kind = str(decided.get("decision") or "")
    step: dict[str, Any] = {"decision": decided}
    done_lines: list[str] = []
    if kind == "ACCEPT":
        hard = [item for item in decided.get("verdicts") or [] if item.get("not_yours")]
        if hard:
            # Rights, claims, placeholder pictures, a file that is not its record: his or the
            # sources' to settle; her ACCEPT does not reach them.
            step["outcome"] = "ACCEPT_REFUSED"
            step["event_id"] = director_qc.record_decision(
                engine,
                {**decided, "outcome": "ACCEPT_REFUSED", "final": True},
                correlation,
            )
        else:
            accepted = director_qc.accept_film(engine, reading, decided, correlation)
            step.update(outcome="ACCEPTED", **accepted)
    elif kind == "CLOSE":
        closing = director_qc.close_film(engine, reading, decided, correlation)
        step.update(outcome="CLOSED", closing=closing, event_id=closing["event_id"])
    else:
        before = [
            [str(pair[0]), pair[1]]
            for pair in decided.get("bought_so_far") or []
            if isinstance(pair, list | tuple) and len(pair) == 2
        ]
        # When her REPAIR began to be carried out: a take approved after it is one bought for
        # her list (`director_qc.new_approved_take`).
        started_at = str(decided.get("started_at") or utc_now())
        repair = _director_repairs(
            engine,
            settings,
            vault,
            registry,
            reading,
            list(decided.get("repairs") or []),
            already=[(pair[0], pair[1]) for pair in before],
            since=started_at,
            verdicts=list(decided.get("verdicts") or []),
        )
        # What a resumption dropped under today's rules is said with what was not carried out
        # (2026-10-12 review, `director_qc.resume_repairs`).
        repair["skipped"] = list(repair.get("skipped") or []) + list(
            decided.get("dropped_on_resume") or []
        )
        overturned = [
            entry for entry in repair.get("overturned") or [] if isinstance(entry, Mapping)
        ]
        # Her second looks that found no defect at all: the lessons only those findings taught
        # are withdrawn (round 3 of the 2026-10-12 review: they were stored before her look, and
        # stayed). An overturn «minor» keeps its lesson: a small flaw has a cause too, and the
        # Owner wants it learned («să înțeleagă de ce apar defectele»).
        cleared = [
            int(entry["scene_index"])
            for entry in overturned
            if isinstance(entry.get("scene_index"), int) and entry.get("severity") == "none"
        ]
        if cleared:
            director_qc.withdraw_overturned_lessons(engine, decided, cleared)
        # The Owner, 2026-10-12 19:00: «și după ce se uită Directoarea, trebuie să aibă și
        # puterea de a trece de QC și merge mai departe cu publicarea». Her looks overturned
        # every REAL finding and nothing else was done: her decision is ACCEPT now, in this
        # walk, and the film goes on to publication (`director_decides_failed_film`), no film QC
        # round and no hourly wait in between.
        by_looks = (
            director_qc.accepted_by_looks(decided, overturned)
            if overturned
            and not any(
                repair.get(key)
                for key in (
                    "applied",
                    "bought",
                    "asked",
                    "limited",
                    "waiting",
                    "made",
                    "new_asset",
                    "card_id",
                )
            )
            else None
        )
        if by_looks is not None:
            accepted = director_qc.accept_film(engine, reading, by_looks, correlation)
            step.update(decision=by_looks, outcome="ACCEPTED", repair=repair, **accepted)
            done_lines = _repair_lines(repair)
        elif repair.get("ship"):
            # The Owner's cap (2026-10-15): nothing more is bought for this film; she
            # accepts the best film there is and it goes on to publication now.
            shipped = director_qc.accepted_by_cap(decided, repair["ship"])
            accepted = director_qc.accept_film(engine, reading, shipped, correlation)
            step.update(decision=shipped, outcome="ACCEPTED", repair=repair, **accepted)
            done_lines = _repair_lines(repair)
        else:
            bought_so_far = before + [
                [str(item["redo"]), item.get("scene_index")] for item in repair.get("bought") or []
            ]
            # What still waits: this walk's purchases in no film, and the earlier ones whose take
            # is not approved yet (one approved now was carried on above).
            waiting = list(repair.get("waiting") or [])
            seen = {(entry.get("scene_index"), entry.get("kind")) for entry in waiting}
            # A film still not rejoined keeps the moment it first waited: `BOUGHT_WAIT_DAYS` count
            # from there, not from each retry.
            first_waited = {
                (entry.get("scene_index"), entry.get("kind")): entry.get("waiting_since")
                for entry in decided.get("waiting_so_far") or []
                if isinstance(entry, dict) and entry.get("waiting_since")
            }
            for entry in waiting:
                first = first_waited.get((entry.get("scene_index"), entry.get("kind")))
                if first:
                    entry["waiting_since"] = first
            storyboard_id = str(reading.get("storyboard_id") or "")
            with Session(engine) as session:
                for entry in decided.get("waiting_so_far") or []:
                    if (
                        isinstance(entry, dict)
                        and isinstance(entry.get("scene_index"), int)
                        and (entry["scene_index"], entry.get("kind")) not in seen
                        and not director_qc.new_approved_take(
                            session,
                            storyboard_id,
                            int(entry["scene_index"]),
                            str(entry.get("kind") or "still"),
                            str(entry.get("since") or started_at),
                        )
                    ):
                        waiting.append(entry)
            if repair.get("new_asset"):
                result = "REPAIRED"
            elif repair.get("asked"):
                result = "ASKED"
            elif repair.get("bought") or waiting:
                result = "BOUGHT_WAITING"
            else:
                result = "NOTHING_DONE"
            step.update(outcome=result, repair=repair, bought_so_far=bought_so_far)
            done_lines = _repair_lines(repair)
            step["event_id"] = director_qc.record_decision(
                engine,
                {
                    **decided,
                    "outcome": result,
                    "final": result in director_qc.FINAL_OUTCOMES,
                    "started_at": started_at,
                    "bought_so_far": bought_so_far,
                    "waiting_so_far": waiting,
                    "done": {
                        key: repair.get(key)
                        for key in (
                            "applied",
                            "bought",
                            "asked",
                            "refused",
                            "limited",
                            "skipped",
                            "waiting",
                            "replaced_his",
                            # Her second look overturned the refusal: nothing bought for it, and
                            # the picture is settled for her next reading (2026-10-12).
                            "overturned",
                            "card_id",
                            "new_asset",
                            "requalified",
                            "requalified_report_id",
                        )
                    },
                },
                correlation,
            )
            # Her lessons whose scenes the film her repair made passes worked: confirmed, hers of
            # this very decision among them now that it is recorded (2026-10-12 review).
            _confirm_lessons_quietly(engine, repair.get("requalified_report_id"))
    if step["outcome"] in director_qc.FINAL_OUTCOMES:
        try:
            step["letter_id"] = director_qc.director_letter(
                engine, reading, step, correlation, done_lines=done_lines
            )
            director_qc.settle_inbox(engine, report_id, step["outcome"], correlation)
        except Exception as exc:  # noqa: BLE001 - her decision stands; the letter is logged
            logger.warning("director_qc_letter_not_written", extra={"error": type(exc).__name__})
    else:
        # Nothing of her list could be done: she reads it again, and until then it waits.
        director_qc.wait_for_director(
            engine,
            reading,
            "nimic din refacerea hotărâtă nu se putea face: "
            + "; ".join(line.lstrip("- ") for line in done_lines)[:300],
            correlation,
        )
    return step


def _director_repairs(
    engine: Engine,
    settings: Settings | None,
    vault: Any,
    registry: ProviderRegistry | None,
    reading: dict[str, Any],
    listed: list[dict[str, Any]],
    *,
    already: list[tuple[Any, Any]] | None = None,
    since: str | None = None,
    verdicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Her REPAIR: only what she listed, through the paid redo path (`_apply_repairs`, every
    purchase by `redo_scene` with ``unasked``: his paid-media rule, the caps, the lease and his
    per-scene and per-film limits), never a take he approved (`director_qc.repair_list` skips
    them, and `_apply_repairs` refuses a plan that would retire one), never against his choice
    on the sheet (a scene he chose to animate locally gets no paid motion), then measured once
    more. ``already``: what was bought for this decision before (it is not bought again);
    ``since``: when the decision began to be carried out; ``verdicts``: her annotated verdicts
    (what a scene's REAL findings said and why they appeared reach the rewrite and her second
    look before a purchase). Recorded as a `QC_REPAIR_EVENT` like every repair. Never raises."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    correlation = str(uuid4())
    storyboard_id = str(reading.get("storyboard_id") or "")
    asset_id = str(reading["media_asset_id"])
    result: dict[str, Any] = {
        "report_id": reading["report_id"],
        "storyboard_id": storyboard_id or None,
        "of_asset": asset_id,
        "new_asset": None,
        "decided_by": director_qc.DIRECTOR,
        "listed": listed,
        "applied": [],
        "bought": [],
        "asked": [],
        "refused": [],
        "limited": [],
        "skipped": [],
        "waiting": [],
        "replaced_his": [],
        "overturned": [],
        "made": [],
        "requalified": None,
    }
    image = (reading.get("production") or {}).get("image") or {}
    if image.get("provider") != "SCENE_TAKES" or not storyboard_id or settings is None:
        why = (
            "fără configurația studioului nu se reface nimic"
            if settings is None
            else "filmul nu este asamblat din preluări: nu se reface scenă cu scenă"
        )
        result["skipped"] = [{**item, "status": "NOT_TAKES", "reason": why} for item in listed]
        return result
    try:
        with Session(engine) as session:
            free_used = _free_fixes_spent(session, storyboard_id, asset_id)
            protected = director_qc.protected_redos(
                session, storyboard_id, reading.get("production") or {}
            )
            choices = director_qc.owner_scene_choices(session, storyboard_id)
        proposals, skipped = director_qc.repair_list(
            listed,
            kinds=director_qc.scene_kinds(reading.get("sheet")),
            protected=protected,
            proposals=reading.get("proposals") or [],
            free_used=free_used,
            choices=choices,
            already=already or (),
        )
        result["skipped"] = skipped
        if proposals:
            _apply_repairs(
                engine,
                settings,
                vault,
                registry,
                {**reading, "proposals": proposals, "verdicts": list(verdicts or [])},
                result,
                not free_used,
                correlation,
                note=DIRECTOR_REDO_NOTE,
                since=since,
            )
    except Exception as exc:  # noqa: BLE001 - her letter is the record of it
        logger.warning(
            "director_repair_failed", extra={"asset_id": asset_id, "error": type(exc).__name__}
        )
        result["refused"].append({"what": "refacerea", "reason": error_words(exc)[:300]})
    if _free_fix_spent_on_measured(result, verdicts or []):
        note_id = _free_fix_defect_note(engine, reading, result)
        if note_id:
            result["developer_note"] = note_id
    # Recorded once something was applied, bought or made: the film's line then had its free
    # fix (`_repaired_assets`); a redo only asked of him leaves the line as it was.
    if result["applied"] or result["bought"] or result["made"]:
        try:
            with Session(engine) as session, session.begin():
                lock_for_write(session)
                append_event(
                    session,
                    QC_REPAIR_EVENT,
                    "storyboard",
                    storyboard_id,
                    1,
                    {key: value for key, value in result.items() if key != "listed"},
                    correlation,
                )
        except SQLAlchemyError:
            logger.warning("qc_repair_not_recorded", extra={"asset_id": asset_id})
    return result


def _free_fix_spent_on_measured(result: Mapping[str, Any], verdicts: list[dict[str, Any]]) -> bool:
    """Whether her REPAIR could do nothing because the film's one free fix was already made,
    for a defect quality control measured as serious (no audio stream, a frozen clip): nothing
    applied, bought, asked or made, a free fix skipped FREE_FIX_USED, no card yet, and a REAL
    verdict of hers on a measured serious finding about the whole film, not a scene (the same
    rule as `reviews.owner_bound_repair`)."""
    from app.agents.reviews import measured_serious, scenes_named  # noqa: PLC0415

    if any(
        result.get(key)
        for key in ("applied", "bought", "asked", "new_asset", "card_id", "developer_note")
    ):
        return False
    if not any(
        isinstance(item, Mapping) and item.get("status") == "FREE_FIX_USED"
        for item in result.get("skipped") or []
    ):
        return False
    return any(
        isinstance(verdict, Mapping)
        and verdict.get("verdict") == "REAL"
        and not verdict.get("check_level")
        and (verdict.get("measured_serious") or measured_serious(verdict.get("text")))
        and not isinstance(verdict.get("scene_index"), int)
        and not scenes_named(verdict.get("text"))
        for verdict in verdicts
    )


#: The kind of the developer's note when a film's free fixes are spent on a measured defect,
#: and the start of its subject (the review pass finds it by it).
FREE_FIX_DEFECT = "free_fix_spent"
FREE_FIX_NOTE_SUBJECT = "Pentru dezvoltator: reparația gratuită nu ajută filmul"


def _free_fix_defect_note(
    engine: Engine, reading: Mapping[str, Any], result: Mapping[str, Any]
) -> str | None:
    """A note for the developer, never a card to the Owner, when the only fix of a defect
    quality control measured as serious is a free fix (audio, encode, card) already made
    `FREE_FIXES_PER_FILM` times for the film (the review of 2026-10-12, round 3: «The film has
    no audio stream» could be neither ACCEPTED nor repaired). The Owner, 22:50 that day: «Dacă
    "decide Proprietarul" înseamnă că nu este o agenție autonomă!» — a free fix that does not
    work three times is a tool's defect, the developer's (his letter rule: tool defects are
    developer_defect notes). Written in the Director's own thread, resolved at once, ONE per
    failed report, so the review pass does not ask her again about the same report
    (`workflows.passes.director_qc_review._developer_waits`). Never raises."""
    from app.agents.director import DEVELOPER_DEFECT_KIND  # noqa: PLC0415 - agents import runbook
    from app.agents.messages import post_message, resolve_message  # noqa: PLC0415
    from app.agents.models import AgentMessage  # noqa: PLC0415

    storyboard_id = str(reading.get("storyboard_id") or "")
    report_id = str(reading.get("report_id") or "")
    if not storyboard_id or not report_id:
        return None
    why_parts = [
        _no_stop(item.get("reason"))
        for item in result.get("skipped") or []
        if isinstance(item, Mapping) and item.get("status") == "FREE_FIX_USED"
    ]
    try:
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.subject.like(f"{FREE_FIX_NOTE_SUBJECT}%"))
            ):
                body = row.body_json if isinstance(row.body_json, dict) else {}
                if (
                    body.get("kind") == DEVELOPER_DEFECT_KIND
                    and body.get("defect") == FREE_FIX_DEFECT
                    and body.get("report_id") == report_id
                ):
                    return str(row.id)
            director = agent_for_role(session, "Director")
            if director is None:
                return None
            board = session.get(Storyboard, storyboard_id)
            title = str(getattr(board, "title", "") or storyboard_id[:8]).strip()[:120]
            note = (
                f"Filmul «{title}»: un defect serios măsurat de controlul calității se repară "
                f"doar gratuit, iar reparația gratuită s-a făcut deja de {FREE_FIXES_PER_FILM} ori "
                "fără să-l elimine"
                + (f" ({'; '.join(why_parts)[:400]})" if why_parts else "")
                + ". E un defect al uneltei: filmul așteaptă dezvoltatorul, nu Proprietarul."
            )
            row = post_message(
                session,
                intent="STATUS",
                subject=f"{FREE_FIX_NOTE_SUBJECT} «{title}»",
                body={
                    "kind": DEVELOPER_DEFECT_KIND,
                    "defect": FREE_FIX_DEFECT,
                    "storyboard_id": storyboard_id,
                    "report_id": report_id,
                    "note": note,
                },
                body_text=note,
                from_agent_id=director.id,
                to_agent_id=director.id,
                correlation_id=report_id,
            )
            resolve_message(
                session,
                row.id,
                resolution="Notat pentru dezvoltator.",
                resolved_by=director.display_name,
                status="RESOLVED",
                correlation_id=report_id,
            )
            return str(row.id)
    except Exception as exc:  # noqa: BLE001 - the repair's own words stand without the note
        logger.warning(
            "free_fix_note_not_written",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
            exc_info=exc,
        )
        return None


def _decision_summary(decided: dict[str, Any]) -> dict[str, Any]:
    return {key: decided.get(key) for key in ("report_id", "of_asset", "outcome", "passed_asset")}


def _decisions_words(decisions: list[dict[str, Any]]) -> str:
    """What the Director decided about the films that failed, in one sentence."""
    tally: dict[str, int] = {}
    for item in decisions:
        tally[str(item.get("outcome"))] = tally.get(str(item.get("outcome")), 0) + 1
    nouns = {
        "ACCEPTED": ("film acceptat", "filme acceptate"),
        "REPAIRED": ("film refăcut", "filme refăcute"),
        "ASKED": (
            "refacere în așteptarea răspunsului tău",
            "refaceri în așteptarea răspunsului tău",
        ),
        "BOUGHT_WAITING": (
            "refacere cumpărată în curs de verificare și continuare de către studio",
            "refaceri cumpărate care așteaptă aprobarea preluărilor noi",
        ),
        "CLOSED": ("film închis", "filme închise"),
        "ACCEPT_REFUSED": ("film oprit la ce nu este al ei", "filme oprite la ce nu este al ei"),
        "NOTHING_DONE": ("film fără refacere posibilă acum", "filme fără refacere posibilă acum"),
        "WAITING": ("film așteaptă decizia ei", "filme așteaptă decizia ei"),
    }
    parts = [count(tally[key], *words) for key, words in nouns.items() if tally.get(key)]
    passed = sum(1 for item in decisions if item.get("passed_asset"))
    said = "Directoarea a decis: " + (", ".join(parts) if parts else "nimic încă") + "."
    if passed:
        said += f" {count(passed, 'film merge', 'filme merg')} la publicare."
    return said


#: A paid redo whose prompt could not be corrected first: the same words are not bought again.
PROMPT_NOT_CORRECTED = "PROMPT_NOT_CORRECTED"
#: Told to the Director with the report's words when the movement's rewrite changed nothing
#: and the picture is rewritten instead.
SAME_PROMPT_NOTE = (
    "The movement of this scene was rewritten before and came back with the same words; the "
    "picture itself must change now."
)
#: Told to her when the movement's rewrite cannot treat what was found (``layer_exhausted``,
#: `scene_rewrite.rewrite_for_redo`): the findings are about the picture, so the picture is
#: rewritten (2026-10-12 review: a MOTION redo she picked for a picture finding stayed
#: PROMPT_NOT_CORRECTED every hour, no motion words being able to fix a picture).
LAYER_EXHAUSTED_NOTE = (
    "What was found in this scene cannot be fixed by the movement's words: it is in the "
    "picture, so the picture itself must change now."
)


def _still_newer_than_film(session: Session, storyboard_id: str, scene: int, asset_id: str) -> bool:
    """Whether the scene's approved still is newer than the picture the failed film
    (``asset_id``) shows: a new picture already bought and approved, in no film yet. A motion
    whose words came back unchanged is then right as it is — the clip is bought from the new
    still, and nothing turns to the picture (2026-10-12, the cyclotron's scenes 4 and 5: their
    stills approved the day before and never animated were retired by the «same prompt»
    escalation and bought again, 269 credits for two scenes that then passed; the Director had
    written «alătur imaginile aprobate, nu cumpăr nimic»).

    The film's picture of a scene is the still its clip was made from, read by time: a still
    approved AFTER the film's clip was made is new; one approved before it is the one the clip
    animated. Never read from the render record's ``still_take``: after a still redo and its
    motion, the record kept the still the scene had at its first assembly (1c038a99, scene 5,
    16:29: the record said the original still while the clip in the film was made from the
    «tower» the gate approved at 11:18, so the tower read as a new picture and its clip was
    bought a third time, the same words, 27 credits). A scene the film holds no clip for (a
    still animated locally) is read by the record's still."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook
    from app.media.models import SceneTake, VideoRenderJob  # noqa: PLC0415

    production = session.scalar(
        select(VideoRenderJob.production_json).where(
            VideoRenderJob.storyboard_id == storyboard_id,
            VideoRenderJob.output_asset_id == asset_id,
        )
    )
    in_film = (
        director_qc.film_takes(production).get(scene, {}) if isinstance(production, dict) else {}
    )
    approved = director_qc.current_approved_still(session, storyboard_id, scene)
    if approved is None:
        return False
    clip = session.get(SceneTake, in_film.get("motion")) if in_film.get("motion") else None
    if clip is not None:
        return str(approved.created_at) > str(clip.created_at)
    return str(approved.id) != in_film.get("still")


def _corrected_for_film(
    session: Session, storyboard_id: str, scene: int, asset_id: str
) -> dict[str, Any] | None:
    """The scene's words as the Director's ladder corrected them for the failed film
    ``asset_id`` and nobody bought on yet: her newest ``media.prompts_rewritten`` for the
    scene, written after the film was rendered and after every take of the scene — {"layer",
    "event_id"}; None when there is none (nothing corrected for this film, or a take bought on
    the correction since).

    2026-10-13: a paid redo under his ask-me rule is corrected first (`_correct_before_redo`)
    and then asked, his yes bound to the corrected plan; the walk that resumed after his yes
    corrected the scene AGAIN before spending it — the same words came back and the redo was
    refused PROMPT_NOT_CORRECTED, or new words made a new plan and he was asked again — so the
    redo he approved was never bought. On the resume, words corrected for this film and not
    bought yet are the words his yes was asked on: neither her look nor his rewrite is asked
    again before it is spent (`_apply_repairs`)."""
    from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT  # noqa: PLC0415
    from app.media.models import SceneTake, StoryboardScene  # noqa: PLC0415
    from app.media.prompt_agent import incomplete_plan_fields  # noqa: PLC0415
    from app.media.scene_rewrite import DECIDED_BY, REWRITE_REASON, _after  # noqa: PLC0415

    film = session.get(MediaAsset, asset_id) if asset_id else None
    if film is None:
        return None
    newest_take = session.scalar(
        select(SceneTake.created_at)
        .where(SceneTake.storyboard_id == storyboard_id, SceneTake.scene_number == scene)
        .order_by(SceneTake.created_at.desc())
        .limit(1)
    )
    floor = str(film.created_at or "")
    if newest_take and _after(newest_take, floor):
        floor = str(newest_take)
    for event in session.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT,
            DomainEvent.aggregate_id == storyboard_id,
        )
        .order_by(DomainEvent.sequence.desc())
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("scene_index") != scene:
            continue
        # Only her brief's rewrite (`scene_rewrite.REWRITE_REASON`): the serial's
        # recomposition and its technical re-roll write the same event as the Director's,
        # on words that may not have changed (the Codex review of c6dc05c).
        if (
            payload.get("decided_by") != DECIDED_BY
            or payload.get("reason") != REWRITE_REASON
            or not _after(event.timestamp, floor)
        ):
            return None
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene,
            )
        )
        if row is None:
            return None
        package = dict(row.prompt_json or {})
        layer = str(payload.get("layer") or "")
        review = payload.get("review")
        if (
            layer not in ("still", "motion")
            or not isinstance(review, dict)
            or review.get("verdict") != "TREATS"
            or incomplete_plan_fields(package, layers=(layer,))
        ):
            return None
        for field in ("still_prompt", "motion_prompt"):
            actual = str(
                package.get(field) or (row.visual_prompt if field == "still_prompt" else "")
            )
            if " ".join(actual.split()) != " ".join(str(payload.get(field) or "").split()):
                return None
        return {"layer": payload.get("layer"), "event_id": str(event.event_id)}
    return None


def _correct_before_redo(
    engine: Engine,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    scene: int,
    kinds: list[str],
    proposals: list[Any],
    reading: dict[str, Any],
    correlation: str,
    *,
    extra_reasons: Sequence[str] = (),
) -> dict[str, Any] | None:
    """The scene's prompt corrected before its paid redo (`scene_rewrite.rewrite_for_redo`):
    the Director reads it with her reasons, the report's words about the scene, why each REAL
    defect of hers appeared («cauza: …», her verdict's cause: 2026-10-12 review, it was read by
    nobody) and ``extra_reasons`` (her second look's words before the purchase), and the Video
    Editor rewrites the picture (a still redo) or the movement (a motion redo). None when it was
    rewritten, or is not a scene the studio rewrites (its redo goes on as before); the refusal
    when it could not be corrected: nothing is bought, and her decision waits to be read again.

    A movement whose rewrite came back with the same words (``same_prompt``), or that cannot
    treat what was found because it is in the picture (``layer_exhausted``), turns to the
    picture: the still is rewritten and bought with its motion — unless a newer approved still
    is already waiting (`_still_newer_than_film`), and then the motion is bought from it."""
    from app.agents.reviews import _names_scene  # noqa: PLC0415 - agents read the same words
    from app.media.models import StoryboardScene  # noqa: PLC0415
    from app.media.prompt_agent import incomplete_plan_fields  # noqa: PLC0415
    from app.media.scene_rewrite import rewrite_for_redo  # noqa: PLC0415 - media imports runbook

    layer = "still" if "still" in kinds else "motion"
    real = [
        verdict
        for verdict in reading.get("verdicts") or []
        if isinstance(verdict, Mapping)
        and verdict.get("verdict") == "REAL"
        and not verdict.get("check_level")
        and _names_scene(verdict, scene)
    ]
    reasons = [
        str(proposal.reason)
        for proposal in proposals
        if proposal.scene_index == scene and not proposal.free and proposal.reason
    ] + [
        str(finding.get("text") or "")
        for finding in reading.get("findings") or []
        if isinstance(finding, dict) and finding.get("scene_index") == scene
    ]
    for verdict in real:
        said = " ".join(str(verdict.get("text") or "").split())
        if said and said not in reasons:
            reasons.append(said)
    reasons += [
        f"cauza: {' '.join(str(verdict['cause']).split())}"
        for verdict in real
        if str(verdict.get("cause") or "").strip()
    ]
    reasons += [str(reason) for reason in extra_reasons if str(reason).strip()]
    with Session(engine) as session:
        row = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id,
                StoryboardScene.scene_index == scene,
            )
        )
        if row is not None:
            reasons += incomplete_plan_fields(dict(row.prompt_json or {}), layers=(layer,))
    try:
        done = rewrite_for_redo(engine, registry, storyboard_id, scene, layer, reasons, correlation)
        turn = done.get("same_prompt") or done.get("layer_exhausted")
        if layer == "motion" and turn and "still" not in kinds:
            with Session(engine) as session:
                new_picture = _still_newer_than_film(
                    session, storyboard_id, scene, str(reading.get("media_asset_id") or "")
                )
            if new_picture:
                # The picture already changed (a still bought for her earlier repair, or his
                # look's, approved and in no film yet): the movement's words need not, and the
                # clip is bought from the new still as they are.
                return None
            # The movement's words came back unchanged, or cannot treat what is in the picture,
            # on a picture that stays: the picture's turn (MOTION_REWRITES_BEFORE_STILL).
            # 2026-10-12, the cyclotron's scene 5: the same motion brief was asked every hour
            # and refused PROMPT_NOT_CORRECTED each time. The redo then buys the new still and
            # its motion (``kinds`` is the caller's).
            note = SAME_PROMPT_NOTE if done.get("same_prompt") else LAYER_EXHAUSTED_NOTE
            escalated = rewrite_for_redo(
                engine,
                registry,
                storyboard_id,
                scene,
                "still",
                [*reasons, note],
                correlation,
            )
            if escalated.get("rewritten"):
                kinds.insert(0, "still")
                return None
            if escalated.get("rewritable", True):
                done = escalated
    except Exception as exc:  # noqa: BLE001 - nothing is bought on words nobody corrected
        logger.warning(
            "redo_prompt_not_corrected",
            extra={"storyboard_id": storyboard_id, "error": type(exc).__name__},
        )
        done = {"rewritten": False, "rewritable": True, "reason": error_words(exc)}
    if done.get("rewritten") or not done.get("rewritable", True):
        return None
    return {
        "what": f"scena {scene}: {PAID_REDO_WORDS[layer]}",
        "redo": layer,
        "scene_index": scene,
        "status": PROMPT_NOT_CORRECTED,
        "reason": (
            f"promptul nu a fost corectat ({done.get('reason') or 'fără motiv'}); nu se cumpără "
            "din nou aceleași cuvinte"
        ),
    }


def _confirm_lessons_quietly(engine: Engine, report_id: Any) -> None:
    """`director_qc.confirm_lessons` for a report just measured or about to be read: her
    lessons whose scenes it passes stop being provisional. Never raises into the walk."""
    if not report_id:
        return
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    try:
        director_qc.confirm_lessons(engine, str(report_id))
    except Exception as exc:  # noqa: BLE001 - the lessons wait; the film does not
        logger.warning(
            "director_lessons_not_confirmed",
            extra={"report_id": str(report_id), "error": type(exc).__name__},
        )


#: Her second look before a paid redo (`_second_look_before_redo`): the refusal was wrong.
SECOND_LOOK_OVERTURNED = "OVERTURNED"


def _qc_frame_numbers(reading: Mapping[str, Any], scene: int) -> list[int]:
    """The film frames the span look judged ``scene`` at, as its report recorded them."""
    checks = (reading.get("report") or {}).get("checks_json") or {}
    record = checks.get("picture_spans_qc") if isinstance(checks, Mapping) else None
    entries = record.get("scenes") if isinstance(record, Mapping) else None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, Mapping) and entry.get("scene_index") == scene:
            return [
                int(item["frame"])
                for item in entry.get("frames") or []
                if isinstance(item, Mapping) and isinstance(item.get("frame"), int)
            ]
    return []


def _failed_film_frames(
    engine: Engine, reading: Mapping[str, Any], scene: int, ffmpeg_path: str | None, folder: Any
) -> list[Any]:
    """The frames of ``scene`` in the failed film as quality control judged them, without the
    studio's own subtitles over the picture: `media.second_look.film_scene_view` (the scene's
    shot at QC's own frame numbers, else the film's frames there with the caption rows cut out,
    else the bought clip at the span's times, else the still; she is told which, and which
    caption was on screen, by the view written beside them).

    The review of 2026-10-12, round 3: her second look was shown the film's frames with the
    studio's burnt-in subtitles on them, confirmed a refusal for «text» that was our own
    captions, and a still was bought. Should that view be unavailable (an older second look, an
    error preparing it), the frames are cut here the same way: the scene's own shot, the
    clip take still the one bought, a still animated locally, else the film's frames with the
    rows its captions draw in cut out (`picture_qc.cut_caption_rows`). Empty when nothing can
    be cut (no encoder, no file, a composed card)."""
    from pathlib import Path  # noqa: PLC0415

    try:
        from app.media.second_look import film_scene_view  # noqa: PLC0415 - optional module

        images, view = film_scene_view(
            engine,
            str(reading.get("media_asset_id") or ""),
            scene,
            work_dir=Path(folder) / "view",
            ffmpeg_path=ffmpeg_path,
            frame_numbers=_qc_frame_numbers(reading, scene),
        )
        if images and view:
            return list(images)
    except Exception as exc:  # noqa: BLE001 - the frames are cut here instead
        logger.info("film_scene_view_unavailable", extra={"error": type(exc).__name__})

    from app.agents.vision import frames_at  # noqa: PLC0415
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook
    from app.media.models import MediaAsset, SceneTake, StoryboardScene  # noqa: PLC0415
    from app.media.picture_qc import (  # noqa: PLC0415
        _file_sha256,
        caption_rows,
        clean_shots,
        cut_caption_rows,
    )
    from app.media.qc import (  # noqa: PLC0415 - the span look's own frame cutting
        DEFAULT_TIMELINE_FPS,
        _shot_span_frames,
        clip_frames,
        span_frame_numbers,
        timeline_spans,
    )
    from app.media.toolchain import find_ffmpeg  # noqa: PLC0415

    production = reading.get("production") or {}
    takes = director_qc.film_takes(production).get(scene) or {}
    with Session(engine) as session:
        asset = session.get(MediaAsset, str(reading.get("media_asset_id") or ""))
        film = str(asset.uri_or_path or "") if asset is not None else ""
        planned = {
            int(row.scene_index): float(row.duration_seconds or 0.0)
            for row in session.scalars(
                select(StoryboardScene).where(
                    StoryboardScene.storyboard_id == str(reading.get("storyboard_id") or "")
                )
            )
        }
        #: The takes the film was cut from, (path, sha256) — read while the session is open.
        files = {
            layer: (str(row.path), str(row.sha256 or ""))
            for layer, take_id in takes.items()
            if take_id
            and (row := session.get(SceneTake, take_id)) is not None
            and row.path
            and row.sha256
        }
    if not film or not Path(film).is_file():
        film = ""
    span = next(
        (
            item
            for item in timeline_spans(dict(production), planned)
            if item["scene_index"] == scene and not item["composed"]
        ),
        None,
    )
    if span is None:
        return []
    timeline = production.get("timeline")
    fps = float(
        (timeline.get("fps") if isinstance(timeline, dict) else None)
        or production.get("fps")
        or DEFAULT_TIMELINE_FPS
    )
    chosen = span_frame_numbers(span["start"], span["end"], fps, span["dissolve_seconds"])
    shot = clean_shots(production, Path(film).parent).get(scene) if film else None
    if shot is not None:
        taken = _shot_span_frames(
            shot, chosen, float(span["start"]), fps, ffmpeg_path, Path(folder) / "shot"
        )
        if taken:
            return [path for _at, _moment, path in taken]

    def verified(layer: str) -> str | None:
        path, sha = files.get(layer, ("", ""))
        return path if path and Path(path).is_file() and _file_sha256(Path(path)) == sha else None

    ffmpeg = find_ffmpeg(ffmpeg_path)
    clip = verified("motion")
    if clip is not None:
        # The clip the film was cut from: the same picture, before any subtitle was burnt in.
        frames = clip_frames(ffmpeg, clip, Path(folder) / "clip")
        if frames:
            return [path for _at, _moment, path in frames]
    still = verified("still") if not takes.get("motion") else None
    if still is not None:
        # A still animated locally (his LOCAL_MOVE): the still is the picture.
        return [Path(still)]
    if not film:
        return []
    cut = frames_at(film, ffmpeg_path, [number for _at, number in chosen], Path(folder) / "film")
    picture_paths = [cut.get(number) for _at, number in chosen]
    if not all(picture_paths):
        return []
    rows = caption_rows(production)
    if rows is None:
        return [frame for frame in picture_paths if frame is not None]
    # The film burns the narration's subtitles in: shown the picture above the rows they draw
    # in, never our own words (a frame with the rows painted over would read as a band).
    above: list[Any] = []
    for (at, _number), picture_path in zip(chosen, picture_paths, strict=True):
        if picture_path is None:
            return []
        pieces = cut_caption_rows(
            ffmpeg,
            Path(picture_path),
            rows,
            Path(folder) / f"film_{at}_deasupra.png",
            Path(folder) / f"film_{at}_dedesubt.png",
        )
        if pieces is None:
            return []
        above.append(pieces[0])
    return above


def _second_look_before_redo(
    engine: Engine,
    registry: ProviderRegistry | None,
    settings: Settings,
    reading: Mapping[str, Any],
    scene: int,
    proposals: list[Any],
    correlation: str,
) -> dict[str, Any]:
    """The Director looks again at the scene in the failed film before a paid still or motion
    is bought for it (the Owner, 2026-10-12: «trece imaginile picate de la QC pe la Directoare
    și să decidă dacă au picat corect sau nu și dacă trebuie refăcute»; «LLM-ul este pe
    abonament! NU COSTĂ BANI»). She is shown the scene's first, middle and last frames
    (`_failed_film_frames`) with quality control's words about it, her REAL findings' and her
    redo's reasons (`media.second_look.second_look`, kind «film_scene»). Returns its answer
    {verdict CONFIRMED | OVERTURNED | UNAVAILABLE, severity, redo, reason_ro, run_id};
    UNAVAILABLE (no model, no frames, no second look, an error) leaves the purchase as before.
    Never raises."""
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from app.agents.reviews import _names_scene  # noqa: PLC0415 - the same scene words
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook

    unavailable: dict[str, Any] = {
        "verdict": "UNAVAILABLE",
        "severity": "none",
        "redo": True,
        "reason_ro": "",
        "run_id": None,
    }
    if registry is None or not _has_language_model(registry):
        return {**unavailable, "reason_ro": "niciun model de limbaj nu este configurat"}
    try:
        from app.media.second_look import second_look  # noqa: PLC0415 - optional module
    except ImportError:
        return {**unavailable, "reason_ro": "a doua privire a Directoarei nu este disponibilă"}
    refusal = [
        " ".join(str(verdict.get("text") or "").split())
        for verdict in reading.get("verdicts") or []
        if isinstance(verdict, Mapping)
        and verdict.get("verdict") == "REAL"
        and not verdict.get("check_level")
        and _names_scene(verdict, scene)
        and str(verdict.get("text") or "").strip()
    ] + [
        str(proposal.reason)
        for proposal in proposals
        if proposal.scene_index == scene and not proposal.free and proposal.reason
    ]
    takes = director_qc.film_takes(reading.get("production") or {}).get(scene) or {}
    try:
        with tempfile.TemporaryDirectory(prefix="second_look_") as work:
            frames = _failed_film_frames(
                engine, reading, scene, getattr(settings, "ffmpeg_path", None), Path(work)
            )
            if not frames:
                return {**unavailable, "reason_ro": "cadrele scenei nu s-au putut tăia din film"}
            answer = second_look(
                engine,
                registry,
                storyboard_id=str(reading.get("storyboard_id") or ""),
                scene_index=scene,
                kind="film_scene",
                images=[str(frame) for frame in frames],
                refusal=refusal,
                correlation_id=correlation,
                take_ids=[take for take in (takes.get("still"), takes.get("motion")) if take],
            )
    except Exception as exc:  # noqa: BLE001 - without her look the purchase goes on as before
        logger.warning(
            "director_second_look_failed",
            extra={"scene_index": scene, "error": type(exc).__name__},
        )
        return {**unavailable, "reason_ro": error_words(exc)[:300]}
    return {**unavailable, **dict(answer)} if isinstance(answer, Mapping) else unavailable


def _scene_real(reading: Mapping[str, Any], scene: int) -> list[Mapping[str, Any]]:
    """Her REAL verdicts on one scene's findings (its own, or named with a scene word), a whole
    check's «a picat» left out."""
    from app.agents.reviews import _names_scene  # noqa: PLC0415 - the same scene words

    return [
        verdict
        for verdict in reading.get("verdicts") or []
        if isinstance(verdict, Mapping)
        and verdict.get("verdict") == "REAL"
        and not verdict.get("check_level")
        and _names_scene(verdict, scene)
    ]


def _measured_serious_scene(reading: Mapping[str, Any], scene: int) -> bool:
    """Whether a REAL finding of the scene is a defect quality control measured as serious (a
    face where the bible forbids faces, panels, writing, a frozen clip:
    `reviews.measured_serious`)."""
    from app.agents.reviews import measured_serious  # noqa: PLC0415

    return any(
        verdict.get("measured_serious") or measured_serious(verdict.get("text"))
        for verdict in _scene_real(reading, scene)
    )


def _overturned_entry(
    engine: Engine,
    reading: Mapping[str, Any],
    scene: int,
    kinds: list[str],
    look: Mapping[str, Any],
) -> dict[str, Any]:
    """What her second look dropped, as the repair records it: the scene, what would have been
    bought, her verdict and reason, the takes, and the families of the REAL findings it
    overturned (a finding no check claimed is «unattributed») each with the scene's carry key
    now (``carry_keys``): `picture_qc.earlier_acceptances` settles exactly that picture for those
    checks, whatever the check (the review of 2026-10-12, round 3: an overturned Motion QC or
    unattributed finding was not settled, and the film looped every hour)."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook
    from app.media.picture_qc import (  # noqa: PLC0415 - shared render evidence
        settle_family,
        storyboard_carry_keys,
    )

    production = reading.get("production") or {}
    takes = director_qc.film_takes(production).get(scene) or {}
    families = sorted(
        {settle_family(verdict.get("check")) for verdict in _scene_real(reading, scene)}
    )
    storyboard_id = str(reading.get("storyboard_id") or "")
    keys: dict[str, Any] = {}
    if storyboard_id:
        with Session(engine) as session:
            for family in families:
                key = storyboard_carry_keys(session, storyboard_id, production, family).get(scene)
                if key:
                    keys[family] = dict(key)
    return {
        "what": f"scena {scene}: " + ", ".join(PAID_REDO_WORDS.get(k, k) for k in kinds),
        "scene_index": scene,
        "redo": list(kinds),
        "status": SECOND_LOOK_OVERTURNED,
        "verdict": str(look.get("verdict") or ""),
        "severity": str(look.get("severity") or ""),
        "reason": str(look.get("reason_ro") or ""),
        "run_id": look.get("run_id"),
        "takes": {"still": takes.get("still"), "clip": takes.get("motion")},
        "checks": families,
        "carry_keys": keys,
    }


def _look_drops_redo(look: Mapping[str, Any], *, measured: bool = False) -> bool:
    """Whether her second look says nothing is to be bought for the scene: she OVERTURNED the
    refusal (the defect is not there, or it is minor). For a defect quality control measured as
    serious (``measured``: a face where faces are forbidden, panels, writing, a frozen clip)
    only an overturn that finds no defect at all (severity none) drops the purchase (the review
    of 2026-10-12, round 3: an overturn «minor», or a confirmation with no redo, dropped the
    redo of a face YuNet counted on a faceless bible, and the face was published). A
    confirmation always buys, under his caps."""
    if str(look.get("verdict") or "") != SECOND_LOOK_OVERTURNED:
        return False
    severity = str(look.get("severity") or "")
    return severity == "none" if measured else severity in ("none", "minor")


def _redo_ended_without_delivery(
    engine: Engine,
    storyboard_id: str,
    scene: int,
    kind: str,
    done: dict[str, Any],
    since: str,
) -> bool:
    from app.media.director_qc import bought_since  # noqa: PLC0415

    if kind == "still" and str((done.get("still") or {}).get("status") or "") in (
        "REFUSED",
        "FAILED",
        "CANCELLED",
        "NOT_BOUGHT",
        "UNSENT",
    ):
        return True
    if not done.get("given_back"):
        return False
    with Session(engine) as session:
        candidates = bought_since(session, storyboard_id, scene, kind, since)
        # Keep uncertain requests and delivered pictures rejected by QC available for
        # recovery/Sarah's look. A restored old take is excluded by bought_since.
        return not any(row.status == "SUBMITTED" or (row.path and row.sha256) for row in candidates)


def _apply_repairs(
    engine: Engine,
    settings: Settings,
    vault: Any,
    registry: ProviderRegistry | None,
    reading: dict[str, Any],
    result: dict[str, Any],
    free: bool,
    correlation: str,
    *,
    note: str = DIRECTOR_REDO_NOTE,
    since: str | None = None,
) -> None:
    """Carry out ``reading['proposals']`` (the Director's list, `_director_repairs`): the free
    fixes once per film, the paid redos prepared through `redo_scene` (unasked), within
    his limits, the film rejoined from its takes where her list says so (`director_qc.REJOIN`),
    and the film that came of them measured once more. Compatible ready RunPod repairs share
    a GPU batch after all corrections/reviews; images precede motion with accepted frames.
    Every purchase keeps its own approval and budget hold. A paid redo whose plan would retire a
    take the Owner approved is refused before anything is priced (2026-10-10: babcf272's
    approved still, motion and test shot were retired by an unasked repair).

    Priced and bought with his choices on the sheet (`sheet_overrides`: a model he chose for a
    scene, his LOCAL_MOVE), exactly as his own «Refă» prices them (2026-10-10 review: without
    them a motion redo of babcf272's scene 5, his LOCAL_MOVE, was planned buyable at 340
    credits on an auto-selected model). A motion that follows its scene's new still continues
    that still's paid round (`_open_still_rounds`), so a still approved later can still reach a
    film. Every take bought that is in no film yet is listed in ``result['waiting']``, with
    ``since`` (when her REPAIR began to be carried out: a take of its scene approved after it
    is the one it waits for, `director_qc.new_approved_take`).

    Before a scene's paid still or motion is bought, the Director looks at the scene in the
    failed film once more (`_second_look_before_redo`; the Owner, 2026-10-12: the look is free,
    the purchase is not). Her look overturning the refusal (no defect, or a minor one; for a
    defect quality control measured as serious only no defect at all, `_look_drops_redo`) buys
    nothing for the scene: it is listed in ``result['overturned']`` with her reason, the takes
    and the carry key of the picture it was about, and her next reading counts its findings as
    settled (`picture_qc.earlier_acceptances`). Her look confirming it adds her words to what
    the rewrite before the purchase reads; no look (no model, no frames) changes nothing.

    Money spent again on a layer the film already paid for once (a second still, a second
    clip of the scene) passes the Accountant after the correction and before the purchase
    (`economy.repurchase_gate.before_paid_redo`, the Owner's rule of 2026-10-13): her refusal
    is discussed with the Director, who insists (bought, both opinions recorded), accepts the
    defect as minor (listed ``overturned``, like her look) or closes the scene (held, in
    ``result['refused']``); no verdict holds the scene for the next try. The first purchase of
    a layer, a redo his ceiling or the day's budget refuses, and a resumed walk on a plan they
    already decided are not asked of her."""
    from app.media import director_qc  # noqa: PLC0415 - media imports runbook
    from app.media.assembler import (  # noqa: PLC0415 - media imports runbook
        REDO_STEP,
        SceneRedoRefused,
        SpentStageError,
        redo_plan,
        redo_scene,
    )
    from app.media.shooting_sheet import sheet_overrides  # noqa: PLC0415 - it imports runbook

    storyboard_id = str(reading["storyboard_id"])
    asset_id = str(reading["media_asset_id"])
    proposals = list(reading.get("proposals") or [])
    environment = studio_environment(engine)
    since = since or utc_now()
    result.setdefault("waiting", [])
    with Session(engine) as session:
        free_already = _free_fixes_spent(session, storyboard_id, asset_id)
        # What he approved as final is never retired here; what he approved without marking
        # it final is replaced by her confirmed repair, and he is told (2026-10-11, his card).
        his_final = director_qc.owner_approved_take_ids(session, storyboard_id, final_only=True)
        his_all = director_qc.owner_approved_take_ids(session, storyboard_id)

    def newest(film: Any) -> None:
        if isinstance(film, dict) and film.get("output_asset_id"):
            result["made"].append(str(film["output_asset_id"]))
            result["new_asset"] = str(film["output_asset_id"])

    def free_redo(kind: str, scene: int | None, words: str) -> None:
        try:
            done = redo_scene(
                engine,
                storyboard_id,
                correlation,
                kind=kind,
                scene_index=scene,
                ffmpeg_path=settings.ffmpeg_path,
                storage_root=getattr(settings, "media_root", None),
                settings=settings,
                environment=environment,
                # The sound redo re-plans a refused mix with the Voice Artist, told who asked
                # and why (her reason for the redo), through the day's registry.
                registry=registry,
                note=f"{note} {words}".strip(),
                requester="director",
            )
        except SceneRedoRefused as exc:
            result["refused"].append({"what": words, "reason": exc.reason_ro})
            return
        result["applied"].append({"redo": kind, "scene_index": scene, "reason": words})
        newest(done.get("film"))

    wanted = {proposal.redo for proposal in proposals if proposal.free}
    if free and not free_already:
        if "encode" in wanted:
            _reencode_from_takes(
                engine, settings, vault, storyboard_id, result, correlation, registry=registry
            )
        for proposal in proposals:
            if proposal.free and proposal.redo == "card":
                free_redo("card", proposal.scene_index, proposal.reason)

    # Every paid redo is prepared through `redo_scene` (may_act inside, his rule,
    # the budgets, the ceiling, the lease), and only within his limits — moved by what he
    # allowed this film on its card (`decisions.producers.redo_cap`, 2026-10-12).
    from app.decisions.producers.redo_cap import redo_allowance  # noqa: PLC0415
    from app.economy import repurchase_gate  # noqa: PLC0415 - economy imports media

    with Session(engine) as session:
        allowed_more = redo_allowance(session, storyboard_id)
    per_scene = int(getattr(settings, "film_max_paid_redos_per_scene", 1)) + allowed_more
    per_film = int(getattr(settings, "film_max_paid_redos", 2)) + allowed_more
    paid: dict[int, list[str]] = {}
    for proposal in proposals:
        if (
            not proposal.free
            and proposal.scene_index is not None
            and proposal.redo in PAID_REDO_WORDS
        ):
            paid.setdefault(int(proposal.scene_index), [])
            if proposal.redo not in paid[int(proposal.scene_index)]:
                paid[int(proposal.scene_index)].append(proposal.redo)
    wiring = sheet_wiring(engine, vault, settings) if paid else {}
    from app.media.factory import reference_image_adapter  # noqa: PLC0415

    image = reference_image_adapter(engine, storyboard_id, wiring.get("image_adapter"))
    capabilities = list(wiring.get("capabilities") or []) or None
    resolution = wiring.get("resolution") or getattr(settings, "motion_resolution", None)
    # His choices on the sheet, read once: the plan and the purchase price the same scene.
    overrides = sheet_overrides(engine, storyboard_id) if paid else None
    bought_kinds: dict[int, list[str]] = {}
    next_words: dict[int, str] = {}
    prepared: dict[int, dict[str, Any]] = {}
    with Session(engine) as session:
        report_rounds = _report_repair_rounds(session, str(reading.get("report_id") or ""))
    for scene in sorted(paid):
        with Session(engine) as session:
            rounds = _paid_redo_rounds(session, storyboard_id)
            open_round = _open_still_rounds(session, storyboard_id).get(scene)
            renders = _renders_made(session, storyboard_id)
        # Only her motion after the scene's new still continues the still's round.
        continues = open_round if paid[scene] == ["motion"] else None
        # The Owner's cap of 2026-10-15: three renders a layer a scene, two bought repairs
        # a report; past it the scene keeps the best take it has (`RENDERS_PER_LAYER`).
        over_renders = {
            redo: renders.get((scene, redo), 0)
            for redo in paid[scene]
            if renders.get((scene, redo), 0) >= RENDERS_PER_LAYER
        }
        if continues is None and (
            rounds.get(scene, 0) >= per_scene
            or sum(rounds.values()) >= per_film
            or over_renders
            or report_rounds >= REPAIR_ROUNDS_PER_REPORT
        ):
            result["limited"].append(
                {
                    "scene_index": scene,
                    "per_scene": per_scene,
                    "per_film": per_film,
                    "renders": over_renders,
                    "renders_cap": RENDERS_PER_LAYER,
                    "report_rounds": report_rounds,
                    "report_rounds_cap": REPAIR_ROUNDS_PER_REPORT,
                }
            )
            continue
        corrected = None
        if continues is None:
            with Session(engine) as session:
                corrected = _corrected_for_film(session, storyboard_id, scene, asset_id)
        if corrected is not None:
            # The words his yes was asked on (2026-10-13, `_corrected_for_film`): the walk
            # that resumes after it neither looks nor corrects again before spending it. A
            # correction that turned to the picture buys the still and its motion, as the
            # first walk did.
            if corrected.get("layer") == "still" and "still" not in paid[scene]:
                paid[scene].insert(0, "still")
        elif continues is None:
            # She looks at the scene once more before anything is bought for it (2026-10-12):
            # free, and the purchase is not. The motion that continues a new still was looked
            # at with that still.
            look = _second_look_before_redo(
                engine, registry, settings, reading, scene, proposals, correlation
            )
            if _look_drops_redo(look, measured=_measured_serious_scene(reading, scene)):
                result.setdefault("overturned", []).append(
                    _overturned_entry(engine, reading, scene, paid[scene], look)
                )
                continue
            extra = (
                [
                    f"Directoarea a privit din nou scena: {look['reason_ro']}"
                    + (
                        # An overturn that is not enough for a measured serious defect.
                        "; defectul măsurat de control ca serios se reface totuși"
                        if str(look.get("verdict") or "") == SECOND_LOOK_OVERTURNED
                        else ""
                    )
                ]
                if str(look.get("verdict") or "") != "UNAVAILABLE"
                and str(look.get("reason_ro") or "").strip()
                else []
            )
            # Not the same words bought again: she reads the prompt, he rewrites it (the Owner,
            # 2026-10-11). The motion that continues a new still was rewritten with it.
            uncorrected = _correct_before_redo(
                engine,
                registry,
                storyboard_id,
                scene,
                paid[scene],
                proposals,
                reading,
                correlation,
                extra_reasons=extra,
            )
            if uncorrected is not None:
                result["refused"].append(uncorrected)
                continue
        prepared[scene] = {
            "continues": continues,
            "rounds": rounds,
            "began": utc_now(),
        }

    from app.media.prepared_batch import RoundWork, flow_call, run_prepared  # noqa: PLC0415
    from app.media.shooting_sheet import (  # noqa: PLC0415
        FilmBusy,
        film_purchase_lease,
        lease_seconds,
    )

    blocked: set[int] = set()
    started: set[int] = set()
    reserved: set[int] = set()
    # All free reviews/corrections finish before a GPU purchase is prepared. Images go
    # together first; motion plans are read after their new starting still is accepted.
    for kind in ("still", "motion"):
        flows = []
        purchases = []
        for scene in sorted(prepared):
            if scene in blocked or kind not in paid[scene]:
                continue
            rounds = prepared[scene]["rounds"]
            try:
                plan = redo_plan(
                    engine,
                    storyboard_id,
                    kind,
                    scene,
                    capabilities=capabilities,
                    integration_id=wiring.get("integration_id"),
                    overrides=overrides,
                    resolution=resolution,
                    stills_model=getattr(image, "model", None),
                )
                if not plan.get("buyable"):
                    raise SceneRedoRefused("NOTHING_TO_BUY", str(plan.get("reason_ro") or ""))
                retiring = {*(plan.get("replaces") or []), *(plan.get("invalidates") or [])}
                if retiring & his_final:
                    # Nobody retires a still or a clip the Owner approved as final, but him.
                    raise SceneRedoRefused(
                        OWNER_APPROVED_REDO,
                        f"Scena {scene}: preluarea ei a fost aprobată de tine ca finală; o "
                        "refacere nepornită de tine nu o retrage.",
                    )
                replacing = sorted(retiring & his_all)
                # Money spent again on a layer this film already paid for passes the Accountant
                # first, and her refusal is discussed with the Director (the Owner, 2026-10-13:
                # «Nadia și Sarah discută … ei să hotărască»; `economy.repurchase_gate`). A
                # hold raises the redo's refusal; her ACCEPT_MINOR comes back as a look that
                # buys nothing; what they agreed, or decided for this plan before, buys below.
                accepted = repurchase_gate.before_paid_redo(
                    engine,
                    registry,
                    settings,
                    reading,
                    proposals,
                    scene,
                    kind,
                    plan,
                    rounds=rounds,
                    per_scene=per_scene,
                    per_film=per_film,
                    environment=environment,
                    measured=_measured_serious_scene(reading, scene),
                    correlation=correlation,
                )
                if accepted is not None:
                    result.setdefault("overturned", []).append(
                        _overturned_entry(engine, reading, scene, paid[scene], accepted)
                    )
                    blocked.add(scene)
                    continue
                flow = flow_call(
                    redo_scene,
                    engine,
                    storyboard_id,
                    correlation,
                    kind=kind,
                    scene_index=scene,
                    plan_hash=str(plan["plan_hash"]),
                    image_adapter=image,
                    adapter_for_model=wiring.get("adapter_for_model"),
                    capabilities=capabilities,
                    account=wiring.get("account"),
                    registry=registry,
                    overrides=overrides,
                    resolution=resolution,
                    settings=settings,
                    environment=environment,
                    integration_id=wiring.get("integration_id"),
                    ffmpeg_path=settings.ffmpeg_path,
                    storage_root=wiring.get("storage_root"),
                    note=note,
                    # The day's repair, nobody's press: his policy before every re-roll.
                    unasked=True,
                    # Her repair of a defect QC measured and she confirmed: it may replace a
                    # take he approved without marking it final (the deep guard agrees).
                    director_repair=True,
                )
                flows.append(flow)
                purchases.append((scene, plan, replacing))
            except SceneRedoRefused as exc:
                entry = {
                    "redo": kind,
                    "scene_index": scene,
                    "status": exc.status,
                    "reason": exc.reason_ro,
                    "approval_id": exc.approval_id,
                    "cap_usd": (exc.plan or {}).get("cap_usd"),
                }
                (result["asked"] if exc.status == "NEEDS_APPROVAL" else result["refused"]).append(
                    {**entry, "what": f"scena {scene}: {PAID_REDO_WORDS[kind]}"}
                )
                blocked.add(scene)
                continue
            except SpentStageError as exc:
                started.add(scene)
                result["refused"].append(
                    {"what": f"scena {scene}: {PAID_REDO_WORDS[kind]}", "reason": exc.reason_ro}
                )
                blocked.add(scene)
                continue
        if not flows:
            continue

        def before_prepare(index: int, purchases_: Any = purchases) -> None:
            candidate = purchases_[index][0]
            previous = prepared[candidate]
            if (
                previous["continues"] is None
                and candidate not in reserved
                and sum(previous["rounds"].values()) + len(reserved) >= per_film
            ):
                result["limited"].append(
                    {"scene_index": candidate, "per_scene": per_scene, "per_film": per_film}
                )
                raise SceneRedoRefused("REDO_LIMIT", "Plafonul refacerilor plătite este atins.")

        def on_prepared(index: int, value: Any, purchases_: Any = purchases) -> None:
            if isinstance(value, RoundWork) or (
                isinstance(value, dict)
                and (
                    value.get("credits")
                    or (value.get("still") or {}).get("status") == "APPROVED"
                    or (value.get("motion") or {}).get("bought_shots")
                )
            ):
                reserved.add(purchases_[index][0])

        try:
            # Keep the root lease until every nested purchase has settled its own hold.
            with film_purchase_lease(
                engine,
                storyboard_id,
                holder=correlation,
                step=REDO_STEP,
                ttl_seconds=lease_seconds(settings),
            ):
                outcomes = run_prepared(
                    flows, before_prepare=before_prepare, on_prepared=on_prepared
                )
        except FilmBusy as exc:
            outcomes = [
                SceneRedoRefused(exc.status, exc.reason_ro, plan=plan)
                for _scene, plan, _replacing in purchases
            ]
        for (scene, _plan, replacing), outcome in zip(purchases, outcomes, strict=True):
            if isinstance(outcome, SceneRedoRefused):
                entry = {
                    "redo": kind,
                    "scene_index": scene,
                    "status": outcome.status,
                    "reason": outcome.reason_ro,
                    "approval_id": outcome.approval_id,
                    "cap_usd": (outcome.plan or {}).get("cap_usd"),
                }
                (
                    result["asked"] if outcome.status == "NEEDS_APPROVAL" else result["refused"]
                ).append({**entry, "what": f"scena {scene}: {PAID_REDO_WORDS[kind]}"})
                blocked.add(scene)
                continue
            if isinstance(outcome, SpentStageError):
                started.add(scene)
                result["refused"].append(
                    {"what": f"scena {scene}: {PAID_REDO_WORDS[kind]}", "reason": outcome.reason_ro}
                )
                blocked.add(scene)
                continue
            if isinstance(outcome, Exception):
                raise outcome
            done = outcome
            still = done.get("still") or {}
            if _redo_ended_without_delivery(
                engine, storyboard_id, scene, kind, done, prepared[scene]["began"]
            ):
                result["refused"].append(
                    {
                        "what": f"scena {scene}: {PAID_REDO_WORDS[kind]}",
                        "redo": kind,
                        "scene_index": scene,
                        "status": str(still.get("status") or "NOT_DELIVERED"),
                        "reason": str(
                            done.get("next_ro")
                            or "Cererea s-a încheiat fără imagine sau clip nou; "
                            "refacerea nu este realizată."
                        ),
                        "credits": done.get("credits"),
                    }
                )
                blocked.add(scene)
                continue
            summary = done.get("motion") if kind == "motion" else None
            if isinstance(summary, dict) and not summary.get("bought_shots"):
                # The step bought nothing for the scene (held NEEDS_OWNER, stopped, not bought):
                # said as a refusal in the step's own words, never as a purchase. 2026-10-12,
                # the cyclotron (aa170155): a motion redo held «Profilul RunPod selectat nu
                # poate filma această scenă» was told to the Owner as «s-a cumpărat (1 refacere
                # cumpărată)» five times through the night.
                held: dict[str, Any] = next(
                    (
                        s
                        for s in summary.get("scenes") or []
                        if int(s.get("scene_index") or 0) == scene
                    ),
                    {},
                )
                result["refused"].append(
                    {
                        "what": f"scena {scene}: {PAID_REDO_WORDS[kind]}",
                        "redo": kind,
                        "scene_index": scene,
                        "status": str(held.get("status") or summary.get("stopped") or "NOT_BOUGHT"),
                        "reason": str(
                            held.get("reason")
                            or summary.get("stopped")
                            or "mișcarea nu a fost cumpărată"
                        ),
                    }
                )
                blocked.add(scene)
                continue
            started.add(scene)
            bought_kinds.setdefault(scene, []).append(kind)
            next_words[scene] = str(done.get("next_ro") or "")
            result["bought"].append(
                {"redo": kind, "scene_index": scene, "credits": done.get("credits")}
            )
            if replacing:
                # His approval, not marked final, replaced at her decision: told to him with
                # her reason (`_repair_lines`).
                result.setdefault("replaced_his", []).append(
                    {
                        "redo": kind,
                        "scene_index": scene,
                        "takes": replacing,
                        "reason": next(
                            (
                                str(proposal.reason or "")
                                for proposal in proposals
                                if proposal.redo == kind and proposal.scene_index == scene
                            ),
                            "",
                        ),
                    }
                )
            newest(done.get("film"))
            if kind == "still" and (done.get("still") or {}).get("status") != "APPROVED":
                # Bought, and waiting for the vendor's late delivery or his look on the sheet:
                # what follows it (its motion, or the film rejoined) waits with it.
                result["waiting"].append(
                    {
                        "scene_index": scene,
                        "kind": "still",
                        "status": (done.get("still") or {}).get("status"),
                        "since": since,
                        "next_ro": str(done.get("next_ro") or ""),
                    }
                )
                blocked.add(scene)
                continue
    for scene in sorted(started):
        kinds = bought_kinds.get(scene, [])
        with Session(engine) as session, session.begin():
            lock_for_write(session)
            append_event(
                session,
                QC_PAID_REDO_EVENT,
                "storyboard",
                storyboard_id,
                1,
                {
                    "scene_index": scene,
                    "of_asset": asset_id,
                    "kinds": kinds,
                    # A new still without its motion yet: the motion may still follow,
                    # in this round (a scene he chose to animate locally needs none).
                    "open_motion": "still" in kinds and "motion" not in kinds,
                    "continues": prepared[scene]["continues"],
                    "started_at": prepared[scene]["began"],
                },
                correlation,
            )

    # The cap stopped what she decided and nothing else of her list could be done. Until
    # 2026-10-15 the film became his question, as a card («ce se întâmplă cu filmul»); the
    # Owner answered it for good that day: «Publicăm ce avem! … orice iese, chiar dacă pică,
    # Directorul se uită peste ce avem, și publică!» The film ships as it stands, her ACCEPT
    # under the cap (`_carry_out`), and what stayed below standard is a lesson for the next.
    if result["limited"] and not (result["bought"] or result["asked"] or result["applied"]):
        result["ship"] = {
            "limited": list(result["limited"]),
            "reason_ro": (
                "plafonul Proprietarului (2026-10-15): cel mult "
                f"{RENDERS_PER_LAYER} randări pe imagine sau mișcare pe scenă și "
                f"{REPAIR_ROUNDS_PER_REPORT} refaceri cumpărate pe raport; se publică ce avem, "
                "Directoarea alege ce este cel mai apropiat de plan."
            ),
        }

    # The film rejoined from its takes where her list says so (a new still of a scene he chose
    # to animate locally, a shot bought earlier and approved since): 0 credits, once, and only
    # when a take bought for her list is approved (`director_qc.new_approved_take`: never the
    # old still a redo that delivered nothing gave back). It completes a paid redo, so it is
    # not the film's one free fix.
    rejoins = [
        proposal
        for proposal in proposals
        if proposal.redo == director_qc.REJOIN and proposal.scene_index is not None
    ]
    if rejoins:
        with Session(engine) as session:
            ready = [
                proposal
                for proposal in rejoins
                if director_qc.new_approved_take(
                    session,
                    storyboard_id,
                    int(proposal.scene_index or 0),
                    director_qc.REJOIN,
                    since,
                )
            ]
        if ready:
            refused_before = len(result["refused"])
            _reencode_from_takes(
                engine,
                settings,
                vault,
                storyboard_id,
                result,
                correlation,
                redo=director_qc.REJOIN,
                words=" ".join(proposal.reason for proposal in ready),
                registry=registry,
            )
            if not result["new_asset"]:
                # The approved take is in no film yet: her decision waits for the film to be
                # rejoined, tried again with the watchdog's back-off (2026-10-10 review: a
                # refused rejoin on a resumed walk fell to NOTHING_DONE, and she was then told
                # REPAIR was not possible and steered to accept the flaw it had replaced).
                why = "; ".join(
                    str(item.get("reason") or "") for item in result["refused"][refused_before:]
                )
                for proposal in ready:
                    result["waiting"].append(
                        {
                            "scene_index": int(proposal.scene_index or 0),
                            "kind": director_qc.REJOIN,
                            "status": None,
                            "since": since,
                            "waiting_since": utc_now(),
                            "next_ro": why[:300],
                        }
                    )

    if free and not free_already and "audio" in wanted:
        free_redo("audio", None, next(p.reason for p in proposals if p.redo == "audio"))

    if not result["new_asset"]:
        # Bought and in no film: a shot that waits for his look, a new still whose motion (or
        # rejoin) was refused for now. Each waits; the walk carries on once it is approved.
        listed = {(entry["scene_index"], entry["kind"]) for entry in result["waiting"]}
        for scene, kinds in sorted(bought_kinds.items()):
            kind = "motion" if "motion" in kinds else "still"
            if {(scene, kind), (scene, "still"), (scene, director_qc.REJOIN)} & listed:
                continue
            result["waiting"].append(
                {
                    "scene_index": scene,
                    "kind": kind,
                    "status": None,
                    "since": since,
                    "next_ro": next_words.get(scene, ""),
                }
            )

    final = result["new_asset"]
    if final:
        # Measured once more, and only once: what failed again is the Owner's decision.
        from app.media.assembler import release_after_qc  # noqa: PLC0415

        report = evaluate_media_qc(
            engine,
            final,
            str(uuid4()),
            settings=settings,
            registry=registry,
            ffmpeg_path=settings.ffmpeg_path,
        )
        release_after_qc(engine, final, str(uuid4()))
        result["requalified"] = report["status"]
        result["requalified_report_id"] = report.get("id")


def _reencode_from_takes(
    engine: Engine,
    settings: Settings,
    vault: Any,
    storyboard_id: str,
    result: dict[str, Any],
    correlation: str,
    *,
    redo: str = "encode",
    words: str | None = None,
    registry: ProviderRegistry | None = None,
) -> None:
    """The film encoded again from the same takes: no still and no shot is bought, and the
    narration already voiced is reused (BOOK_EVERY_PURCHASE); any narration left to buy goes
    through the same question and hold as the day's assembly. ``redo`` and ``words`` name it
    in the repair's record (the Director's `director_qc.REJOIN`: the film rejoined with a
    take bought for her list). ``registry`` reaches the mix, so the sound is planned by the
    Voice Artist again rather than falling to the deterministic plan."""
    from app.media.shooting_sheet import build_sheet  # noqa: PLC0415 - media imports runbook

    environment = studio_environment(engine)
    wiring = sheet_wiring(engine, vault, settings)
    from app.media.factory import reference_image_adapter  # noqa: PLC0415

    image = reference_image_adapter(engine, storyboard_id, wiring.get("image_adapter"))
    sheet = build_sheet(
        engine,
        storyboard_id,
        account=wiring.get("account"),
        stills_model=getattr(image, "model", None),
        settings=settings,
        capabilities=list(wiring.get("capabilities") or []),
        integration_id=wiring.get("integration_id"),
        resolution=wiring.get("resolution") or getattr(settings, "motion_resolution", None),
    )
    plan_cost = estimate_film_cost_micros(
        engine,
        storyboard_id,
        environment=environment,
        settings=settings,
        sheet=_film_figures(sheet),
    )
    made = _assemble_from_takes(
        engine,
        settings,
        vault,
        storyboard_id,
        wiring,
        environment,
        plan_cost,
        correlation,
        sheet_hash=str(sheet.get("sheet_hash") or "") or None,
        registry=registry,
    )
    words = words or (
        "Codare: filmul refăcut din aceleași preluări, fără credite pentru imagini sau cadre."
    )
    if made.get("status") == "ASSEMBLED":
        result["applied"].append({"redo": redo, "scene_index": None, "reason": words})
        result["made"].append(str(made["asset_id"]))
        result["new_asset"] = str(made["asset_id"])
    else:
        result["refused"].append(
            {
                "what": "recodarea" if redo == "encode" else "reasamblarea filmului",
                "reason": str(made.get("reason") or ""),
            }
        )


def _repair_lines(result: dict[str, Any]) -> list[str]:
    """What one repair did, line by line in the Owner's words, for the Director's letter:
    each free fix, each paid redo bought under his rule, each one waiting for his answer, the
    limits reached, what was refused and what of her list was not carried out, with why."""
    done: list[str] = []
    for item in result.get("applied") or []:
        done.append(f"- Refăcut fără credite: {_no_stop(item['reason'])}.")
    for item in result.get("bought") or []:
        done.append(
            f"- Refăcut și cumpărat sub regula ta pentru pașii plătiți: scena "
            f"{item['scene_index']}, {PAID_REDO_WORDS.get(item['redo'], item['redo'])} "
            f"({_credits_words(item.get('credits'))})."
        )
    for item in result.get("asked") or []:
        cap = item.get("cap_usd")
        done.append(
            f"- {str(item['what']).capitalize()}: refacerea așteaptă răspunsul tău pe foaia "
            "de filmare"
            + (f" (plafon {decimal(float(cap))} USD)" if isinstance(cap, int | float) else "")
            + "; nu se cumpără fără el."
        )
    for item in result.get("limited") or []:
        done.append(
            f"- Scena {item['scene_index']}: nu se mai cumpără automat, s-a atins limita de "
            f"{count(int(item['per_scene']), 'refacere plătită', 'refaceri plătite')} pe scenă"
            f" și {count(int(item['per_film']), 'refacere plătită', 'refaceri plătite')} pe "
            "film (STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE, STUDIO_FILM_MAX_PAID_REDOS)"
            + (
                "; ai un card: mai cumpăr, public așa cum e, sau închid."
                if result.get("card_id")
                else "."
            )
        )
    for item in result.get("replaced_his") or []:
        what = PAID_REDO_WORDS.get(item["redo"], item["redo"])
        why = _no_stop(item.get("reason"))
        done.append(
            f"- Scena {item['scene_index']}: {what} pe care o aprobaseși pe foaia de filmare a "
            "fost înlocuită la decizia Directoarei"
            + (f" ({why})" if why else "")
            + "; aprobarea ta nu era marcată «finală». O aprobare marcată «finală» pe foaie "
            "nu o reface nimeni în locul tău."
        )
    for item in result.get("refused") or []:
        done.append(f"- {str(item['what']).capitalize()}: {_no_stop(item['reason'])}.")
    for item in result.get("overturned") or []:
        # Her second look before the purchase (2026-10-12): nothing bought for the scene.
        why = _no_stop(item.get("reason"))
        done.append(
            f"- Scena {item['scene_index']}: Directoarea s-a uitat din nou la scenă înainte de "
            "cumpărare: refuzul controlului nu se confirmă"
            + (f" ({why})" if why else "")
            + "; nu se cumpără nimic pentru ea."
        )
    for item in result.get("waiting") or []:
        if item.get("kind") == "rejoin":
            done.append(
                f"- Scena {item['scene_index']}: preluarea nouă este aprobată, dar filmul nu s-a "
                "putut reasambla încă"
                + (f" ({_no_stop(item.get('next_ro'))})" if item.get("next_ro") else "")
                + "; studioul încearcă din nou, fără să cumpere nimic."
            )
            continue
        what = "imaginea nouă" if item.get("kind") == "still" else "cadrul nou"
        done.append(
            f"- Scena {item['scene_index']}: {what} este cumpărată, dar nu este încă în film"
            + (f": {_no_stop(item.get('next_ro'))}" if item.get("next_ro") else "")
            + "."
        )
    for item in result.get("skipped") or []:
        done.append(f"- Nu s-a refăcut: {_no_stop(item.get('reason'))}.")
    return done or ["- Nimic nu se putea reface."]


# ------------------------------------------- his yes continues the film the same day (A6) --
#
# 2026-10-02 (CONTINUE_REDOS_E2E; A6, AR-05). The daily run does one successful day per date,
# and nothing reacted to the Owner's answer: under EVERY_PAID_STEP a film climbed one stair a
# day, and the yes had often expired by the run that could spend it. His APPROVED answer on a
# paid step of a film (and his look approving one of its takes) now queues FILM_CONTINUE
# (`app.services.queue_film_continue`), and the worker walks that one film here: its staircase
# (his yes is spent by the step it names, under the film's lease), its assembly, its QC (and
# repair), and its publication under the channel's policy. Behind his stop, safe mode and his
# mode, PRODUCTION only; it is not a day, and it writes no DailyRun.

FILM_CONTINUED_EVENT = "runbook.film_continued"


def continue_film(
    engine: Engine,
    settings: Settings,
    vault: Any,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    *,
    cause: str = "",
    correlation_id: str = "",
) -> dict[str, Any]:
    """Walk one film on, now, as far as the Owner's answers and rule allow.

    Returns ``status`` in the stages' vocabulary (COMPLETED when something moved, SKIPPED
    when it could not, BLOCKED under his stop or safe mode), a Romanian ``reason``, and the
    film's ``refusal`` (FILM_BUSY when another buyer holds the film's lease: the worker looks
    again later)."""
    correlation = correlation_id or str(uuid4())

    def done(status: str, reason: str, **more: Any) -> dict[str, Any]:
        outcome = {
            "status": status,
            "reason": " ".join(str(reason).split()),
            "storyboard_id": storyboard_id,
            "cause": cause,
            "refusal": more.pop("refusal", None),
            **more,
        }
        try:
            with Session(engine) as session, session.begin():
                append_event(
                    session,
                    FILM_CONTINUED_EVENT,
                    "storyboard",
                    storyboard_id,
                    1,
                    {
                        key: outcome[key]
                        for key in ("status", "reason", "cause", "refusal")
                        if key in outcome
                    },
                    correlation,
                )
        except SQLAlchemyError:
            logger.warning("film_continue_not_recorded", extra={"storyboard_id": storyboard_id})
        return outcome

    if stop_requested(engine):
        return done(BLOCKED, stop_reason_words(engine))
    safe = safe_mode_state(engine)
    if safe.get("active"):
        return done(
            BLOCKED,
            f"Studioul este în mod sigur ({safe.get('reason') or 'fără motiv'}): filmul nu "
            "continuă până nu închizi modul sigur.",
        )
    environment = studio_environment(engine)
    if environment != "PRODUCTION":
        return done(
            SKIPPED,
            f"Studioul este în mediul {environment}: acolo rularea zilnică nu cumpără nimic de "
            "la furnizorii reali, deci filmul nu continuă singur. Pașii plătiți se apasă pe "
            "foaia de filmare.",
        )
    action, tier = STAGE_ACTIONS["media"]
    refusal = mode_refusal(engine, action, tier, ask_owner=False)
    if refusal is not None:
        return done(SKIPPED, str(refusal["reason"]))
    with Session(engine) as session:
        board = session.get(Storyboard, storyboard_id)
        if board is None:
            return done(SKIPPED, f"Filmul {storyboard_id[:8]} nu mai există.")
        title = str(board.title or storyboard_id[:8])
        rendered = session.scalar(
            select(VideoRenderJob)
            .where(
                VideoRenderJob.storyboard_id == storyboard_id,
                VideoRenderJob.status == "COMPLETED",
                VideoRenderJob.output_asset_id.is_not(None),
            )
            .order_by(VideoRenderJob.finished_at.desc(), VideoRenderJob.started_at.desc())
            .limit(1)
        )
        newest_asset = rendered.output_asset_id if rendered is not None else None
        status = str(board.status)
        serial = is_serial_storyboard(board)
        passed_story, why = story_gate(session, board.script_draft_id)
    if newest_asset is not None:
        return _continue_rendered(
            engine, settings, vault, registry, storyboard_id, str(newest_asset), title, done
        )
    if status != "APPROVED":
        return done(
            SKIPPED, f"Filmul «{title}» nu mai este de filmat (starea {status}); nu continuă."
        )
    if not passed_story:
        return done(SKIPPED, f"Filmul «{title}» nu a trecut recenzia de poveste: {why}")
    media = _media_staircase(
        engine,
        settings,
        vault,
        registry,
        [storyboard_id],
        [],
        {storyboard_id} if serial else set(),
        environment,
        skipped=[],
        today=business_date(settings.timezone),
    )
    artefacts = media.get("artefacts") or {}
    films = artefacts.get("films") or []
    film = films[0] if films else {}
    if media["status"] == BLOCKED:
        return done(BLOCKED, str(media["reason"]))
    assets = [str(asset) for asset in artefacts.get("assets") or []]
    if not assets:
        return done(
            COMPLETED if artefacts.get("bought_steps") else SKIPPED,
            str(media["reason"]),
            refusal=film.get("refusal"),
            film_status=film.get("status"),
            step=film.get("step"),
            bought_steps=artefacts.get("bought_steps") or [],
        )
    qc = _edit_and_qc(engine, registry, settings, vault=vault, asset_ids=assets)
    passed = list((qc.get("artefacts") or {}).get("passed_assets") or [])
    published = _publish_passed(engine, settings, vault, registry, passed)
    return done(
        COMPLETED,
        " ".join(
            part
            for part in (str(media["reason"]), str(qc["reason"]), str(published.get("reason")))
            if part and part != "None"
        ),
        film_status=film.get("status"),
        assets=assets,
        passed_assets=passed,
        published=published.get("artefacts", {}).get("published") or [],
        bought_steps=artefacts.get("bought_steps") or [],
    )


def _continue_rendered(
    engine: Engine,
    settings: Settings,
    vault: Any,
    registry: ProviderRegistry | None,
    storyboard_id: str,
    asset_id: str,
    title: str,
    done: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """A film already assembled: measured if it was not, decided by the Director if it failed
    (her REPAIR his yes continued is carried out again; a report she has not decided is read
    by her now, 2026-10-10), published if it passed."""
    with Session(engine) as session:
        report = session.scalar(
            select(QualityControlReport)
            .where(
                QualityControlReport.media_asset_id == asset_id,
                QualityControlReport.status != "INVALIDATED",
            )
            .order_by(QualityControlReport.verified_at.desc())
            .limit(1)
        )
        verdict = report.status if report is not None else None
        report_id = report.id if report is not None else None
    passed: list[str] = []
    said: list[str] = []
    if verdict is None:
        qc = _edit_and_qc(engine, registry, settings, vault=vault, asset_ids=[asset_id])
        passed = list((qc.get("artefacts") or {}).get("passed_assets") or [])
        said.append(str(qc["reason"]))
    elif verdict == "PASSED":
        passed = [asset_id]
    elif report_id is not None:
        # The film failed QC: the Director decides it (her REPAIR his yes continued is carried
        # out again; a report she never decided, babcf272's d4ea68d2 among them, is read now).
        from app.media.director_qc import outcome_words  # noqa: PLC0415 - media imports runbook

        decided = director_decides_failed_film(
            engine, settings, vault, registry, str(report_id), asset_id
        )
        if decided.get("passed_asset"):
            passed = [str(decided["passed_asset"])]
        said.append(outcome_words(title, decided))
    if not passed:
        return done(
            COMPLETED if said else SKIPPED,
            " ".join(said) or f"Filmul «{title}» nu are un material trecut de controlul calității.",
        )
    published = _publish_passed(engine, settings, vault, registry, passed)
    return done(
        COMPLETED,
        " ".join([*said, str(published.get("reason") or "")]),
        passed_assets=passed,
        published=published.get("artefacts", {}).get("published") or [],
    )


def _publish_passed(
    engine: Engine,
    settings: Settings,
    vault: Any,
    registry: ProviderRegistry | None,
    passed: list[str],
) -> dict[str, Any]:
    """The films that passed QC, through the publish stage's own path (the Director's look,
    the gate, the channel policy, the Owner's mode), and no other film."""
    if not passed:
        return _outcome(SKIPPED, "Niciun material trecut de QC de publicat.")
    action, tier = STAGE_ACTIONS["publish"]
    refusal = mode_refusal(engine, action, tier, ask_owner=False)
    if refusal is not None:
        return _outcome(SKIPPED, str(refusal["reason"]))
    return _publish(
        engine,
        vault,
        registry,
        settings.content_language,
        settings.ffmpeg_path,
        footer=publication_footer(
            engine, settings.ai_disclosure_url, settings.creator_channel_title
        ),
        only_assets=set(passed),
    )


# --------------------------------------------------------------------------- publish --


#: A publication that is a film on the channel, or on its way there under a release time:
#: only these are "published" in the stage's account (PUB-02). PUBLISHED_SIMULATED is the
#: TEST studio's simulator, counted as the film that studio made, as before.
OUT_ON_THE_CHANNEL = ("PUBLISHED", "PUBLISHED_SIMULATED", "SCHEDULED", "REMOTE_CONFIRMED")

#: Uncertain publications the watchdog or the Owner settles; the day does not offer their
#: films again beside them.
SETTLING_ELSEWHERE_STATES = ("FAILED_RETRYABLE", "NEEDS_RECONCILIATION")


def _viewing_rejected(session: Session) -> set[str]:
    """The films whose NEWEST viewing the Director refused. Until 2026-10-15 any refusal
    ever written kept a film out: a film viewed again under the Owner's cap (APPROVE with
    her notes) was still out of the queue on its older REJECT."""
    newest: dict[str, str] = {}
    for review in session.scalars(select(EditorialReview).order_by(EditorialReview.created_at)):
        newest[str(review.media_asset_id)] = str(review.verdict)
    # A film accepted under the Owner's cap is published as it stands: its refused viewing
    # is notes, and `_publish_one` has her view it again (13:31Z, 2d276038: the queue said
    # «niciun material aprobat de QC în așteptarea publicării» on that refusal).
    return {
        asset
        for asset, verdict in newest.items()
        if verdict == "REJECT" and accepted_under_cap(session, asset) is None
    }


def _publish_one(
    engine: Engine,
    vault: Any,
    registry: ProviderRegistry | None,
    language: str,
    ffmpeg_path: str | None,
    footer: str | None,
    asset_id: str,
    route: dict[str, Any],
    environment: str,
) -> dict[str, Any]:
    """One film to the channel its route names, at the visibility that channel's policy allows.

    Returns ``{"published": {...}}`` when the film went out, else ``{"status", "reason",
    ...artefacts}`` in the stage's own vocabulary: SKIPPED when the studio could not do the
    work (no account, no model, a gate error), COMPLETED when the work was done and the
    answer was no (the Director's refusal, the Publisher's HOLD, the gate's reasons).
    """
    channel_id, channel_name = route["channel_id"], route["channel_name"]
    try:
        provider = selected_youtube(engine, vault, route["youtube_connection_id"])
    except ValueError as exc:
        return {"status": SKIPPED, "reason": sentence(error_words(exc)), **error_fields(exc)}
    if provider is None:
        return {
            "status": SKIPPED,
            "reason": f"Contul YouTube legat de {channel_name} nu mai este conectat.",
        }

    # The Director watches the film before anyone prepares its publication. Nothing goes
    # to a channel that she has not approved, and her refusal is a letter to whoever must
    # change something, not a silent skip.
    with Session(engine) as session:
        editorial = latest_editorial(session, asset_id)
        if (
            editorial is not None
            and editorial.verdict != "APPROVE"
            and accepted_under_cap(session, asset_id) is not None
        ):
            # Refused by a viewing, accepted under the Owner's cap (2026-10-15): viewed
            # again, and her viewing is notes now, not a veto (`editorial_review`).
            editorial = None
    if editorial is None:
        if registry is None or not _has_language_model(registry):
            return {
                "status": SKIPPED,
                "reason": "Directorul nu poate viziona materialul: niciun model de limbaj.",
            }
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
            return {
                "status": SKIPPED,
                "reason": f"Directorul nu a putut viziona materialul: {error_words(exc)}."[:300],
                **error_fields(exc),
            }
        editorial_verdict, editorial_reasons = watched["verdict"], watched["reasons"]
    else:
        editorial_verdict = editorial.verdict
        editorial_reasons = list(editorial.reasons_json or [])
    if editorial_verdict != "APPROVE":
        return {
            "status": COMPLETED,
            "reason": "Directorul a respins materialul înainte de publicare: "
            + "; ".join(str(r) for r in editorial_reasons),
            "rejected_asset": asset_id,
            "reasons": editorial_reasons,
        }

    # What an autonomous upload to this channel may be is the Owner's policy on the slot,
    # resolved in one place for the gate, the upload and the record alike. It used to be
    # the constant "private" here, and a policy the Owner set was read by nobody.
    with Session(engine) as session:
        channel = session.get(ChannelRecord, channel_id)
        resolved = resolve_publish_visibility(channel, environment)
        rights = _film_rights(session, asset_id)
    if (
        rights["passed"]
        and not rights["public_allowed"]
        and (resolved["privacy_status"] != "private" or resolved["publish_at"])
    ):
        # A film whose components do not all prove commercial use (NEEDS_REVIEW) may go up
        # private and nothing more: the publishing gate's rights check (Gate 7) refuses it
        # public, unlisted or scheduled. Asked for the channel's visibility, it was refused on
        # every run and never uploaded at all (2026-10-10 review); it is uploaded private, and
        # the record says why.
        resolved = _private_until_licensed(resolved, rights)
    verdict = evaluate_publishing_gate(
        engine,
        asset_id,
        channel_id,
        privacy_status=resolved["privacy_status"],
        policy_version=resolved["policy_version"],
        scheduled_publish_time=resolved["publish_at"],
    )
    if not verdict["eligible"]:
        return {
            "status": COMPLETED,
            "reason": "Poarta de publicare a refuzat: " + "; ".join(verdict["reasons"]),
            "blocked_asset": asset_id,
            "reasons": verdict["reasons"],
            "reason_codes": verdict["reason_codes"],
        }

    with Session(engine) as session:
        hold = publication_hold(session, asset_id)
        metadata = approved_metadata(session, asset_id)
    if hold:
        return {
            "status": COMPLETED,
            "reason": "Publisher-ul ține materialul în așteptare: "
            + "; ".join(hold["hold_reasons"]),
            "held_asset": asset_id,
            "hold_message_id": hold["message_id"],
        }
    if metadata is not None:
        # A HOLD the Director lifted hands back the title she was shown, and for an episode
        # that title can be the very one the computed check refused (a copy of the other
        # channel's film, or no word of its own story). Measured on the code of 2026-09-19:
        # it went to the upload, the upload refused it and left a BLOCKED_GATE row, and every
        # later run did the same. The check is asked here first; a refused title is not
        # metadata, so the Publisher is asked again below and her new answer is judged anew.
        with Session(engine) as session:
            refused = publication_metadata_refusals(
                session, asset_id, channel_id, metadata["title"], metadata["tags"]
            )
        if refused:
            metadata = None
    if metadata is None:
        if registry is None or not _has_language_model(registry):
            return {
                "status": SKIPPED,
                "reason": (
                    "Publisher-ul nu poate pregăti metadatele: niciun model de limbaj disponibil."
                ),
            }
        try:
            prepared = prepare_publication(
                engine, registry, asset_id, channel_id, str(uuid4()), language=language
            )
        except (ReviewError, NoReviewer, ValueError) as exc:
            return {
                "status": SKIPPED,
                "reason": f"Publisher-ul nu a pregătit publicarea: {error_words(exc)}."[:300],
                **error_fields(exc),
            }
        if prepared["verdict"] != "READY":
            return {
                "status": COMPLETED,
                "reason": "Publisher-ul ține materialul în așteptare: "
                + "; ".join(prepared.get("hold_reasons", [])),
                "held_asset": asset_id,
                "hold_message_id": prepared.get("message_id"),
            }
        metadata = {
            "title": prepared["title"],
            "description": prepared["description"],
            "tags": prepared["tags"],
        }

    # The last question before the film leaves the studio, and the one no other gate asks:
    # whether the mode the Owner set lets the studio upload at all. An upload is an external
    # write whatever visibility it carries (T3), so MANUAL refuses it, SUPERVISED asks the
    # Owner — or spends the answer he already gave about *this film* — and AUTONOMOUS_CEO
    # performs it within the channel policy, which decides who may then see it. Asked here,
    # after the Director and the gate, so the Owner is asked about a film that is otherwise
    # ready to go.
    #
    # The request is about this media asset, and the state he is shown it in is the channel
    # and the policy version that will decide who sees the film. What each thing means for
    # an answer he has already given: a STOP or a SAFE_MODE is read by `may_act` before his
    # answer is even looked for, so the yes stays unspent and is still his when the stop is
    # lifted or the incident closes — neither of them retracts it, and neither of them lets
    # a film past on it. A channel policy that moved after he answered does retract it: he
    # said yes to this film going out at that visibility under that version, so the answer
    # is left where it is and a fresh request naming the new policy is raised instead.
    refusal = mode_refusal(
        engine,
        "publishing.public_publish",
        requester="publisher",
        subject=asset_id,
        evidence=f"{metadata['title']} → {channel_name} ({resolved['release_privacy']})",
        context={
            "channel_id": channel_id,
            "policy_version": resolved["policy_version"],
            "privacy_status": resolved["privacy_status"],
        },
    )
    if refusal is not None:
        if refusal["status"] == "REFUSED_BY_OWNER":
            # The stage's own vocabulary, kept exactly: the Owner's no is the work done and
            # the answer being no — the same shape as the Director's refusal and the
            # Publisher's HOLD — so it is COMPLETED, not SKIPPED. The film keeps its
            # QC-PASSED report and stays unpublished, and nothing asks him again until his
            # decision expires.
            return {
                "status": COMPLETED,
                "reason": refusal["reason"],
                "refused_by_owner": asset_id,
                "approval_id": refusal["approval_id"],
            }
        return {
            "status": SKIPPED,
            "reason": refusal["reason"],
            "awaiting_owner": asset_id,
            "approval_id": refusal["approval_id"],
        }

    try:
        published = publish_media_asset(
            engine,
            media_asset_id=asset_id,
            channel_id=channel_id,
            title=metadata["title"],
            description=metadata["description"],
            tags=metadata["tags"],
            privacy_status=resolved["privacy_status"],
            correlation_id=str(uuid4()),
            provider=provider,
            footer=footer,
            policy_version=resolved["policy_version"],
            scheduled_publish_time=resolved["publish_at"],
        )
    except (PublishingGateError, PublisherNotConfigured) as exc:
        return {"status": SKIPPED, "reason": sentence(error_words(exc)), **error_fields(exc)}
    except (ValueError, OSError) as exc:
        # A row that changed under the gate, an asset gone, a file the hash could not read:
        # this film's upload, not the studio's day. Raised, it made the stage HARD, opened
        # safe mode and stopped autonomy until the Owner cleared both; the film is offered
        # again tomorrow instead.
        return {
            "status": SKIPPED,
            "reason": sentence(
                f"Publicarea «{metadata['title']}» nu s-a putut face acum: "
                f"{type(exc).__name__}: {exc}"
            ),
            "publish_fault": asset_id,
        }

    went_out = published["status"] in OUT_ON_THE_CHANNEL
    with Session(engine) as session, session.begin():
        record = session.get(PublicationRecord, published["id"])
        remote_privacy = record.remote_privacy_status if record is not None else None
        if resolved.get("private_until_licensed"):
            # Private for its licence alone: the watchdog makes it public once the licence is
            # confirmed, under the channel's policy (`app.publishing.licence_release`).
            mark_held_for_licence(
                session, published["id"], resolved["reason"], rights["missing_ro"]
            )
        publisher = agent_for_role(session, "Publisher")
        if publisher is not None:
            remember(
                session,
                memory_class="HISTORICAL_EVENT",
                content=(
                    f"Published “{metadata['title']}” to {channel_name} "
                    f"({resolved['release_privacy']}): {published['status']}."
                    if went_out
                    else f"Upload of “{metadata['title']}” to {channel_name} did not "
                    f"go out: {published['status']}."
                ),
                source_type="event",
                source_id=published["id"],
                agent_id=publisher.id,
            )
    if not went_out:
        # PUB-02: a failed, unknown or refused upload is not a published film. The work was
        # done and the answer was no, so the stage's word is COMPLETED; the channel is not
        # served by it, and the film's next chance is the record's own (a FAILED_FINAL film
        # is offered again tomorrow, a retryable or unknown one is the watchdog's).
        detail = str(published.get("error_detail") or "").strip().rstrip(".")
        return {
            "status": COMPLETED,
            "reason": (
                f"Filmul «{metadata['title']}» nu a urcat pe {channel_name}: "
                f"{publication_status(published['status'])}"
                + (f" — {detail}" if detail else "")
                + "."
            ),
            "asset_id": asset_id,
            "publication_id": published["id"],
            "publication_status": published["status"],
        }
    return {
        "published": {
            "remote_privacy_status": remote_privacy,
            "publication_id": published["id"],
            "publication_status": published["status"],
            "title": metadata["title"],
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_type": route["channel_type"],
            "privacy_status": resolved["privacy_status"],
            "release_privacy": resolved["release_privacy"],
            "publish_at": resolved["publish_at"],
            "policy_version": resolved["policy_version"],
            "visibility_reason": resolved["reason"],
            "private_until_licensed": bool(resolved.get("private_until_licensed")),
        }
    }


def _film_rights(session: Session, asset_id: str) -> dict[str, Any]:
    """What the film's licence status allows (`media.qc.rights_verdict`), read as the
    publishing gate's rights check reads it: the asset's status and its render's manifest."""
    asset = session.get(MediaAsset, asset_id)
    job = session.scalar(
        select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id).limit(1)
    )
    manifest = job.production_json if job is not None else None
    return rights_verdict(
        asset.license_status if asset is not None else None,
        manifest if isinstance(manifest, dict) else {},
    )


def _private_until_licensed(resolved: dict[str, Any], rights: dict[str, Any]) -> dict[str, Any]:
    """The channel's resolved visibility turned into a private upload, with no scheduled
    release (a private upload with a publishAt is a public film later), and why, in the
    Owner's words. The policy version stays the one that was resolved."""
    missing = "; ".join(str(item) for item in rights.get("missing_ro") or [])
    return {
        **resolved,
        "privacy_status": "private",
        "publish_at": None,
        "release_privacy": "private",
        "reason": (
            "încărcat privat: licența filmului nu este confirmată"
            + (f" ({_no_stop(missing)[:300]})" if missing else "")
            + "; devine public doar după ce licența este confirmată"
        ),
        "private_until_licensed": True,
    }


def _publish(
    engine: Engine,
    vault: Any,
    registry: ProviderRegistry | None = None,
    language: str = "en",
    ffmpeg_path: str | None = None,
    footer: str | None = None,
    *,
    only_assets: set[str] | None = None,
) -> dict[str, Any]:
    """Publish what the gate allows, each film to the channel its storyboard names.

    ``only_assets`` limits the stage to those files (FILM_CONTINUE publishes its own film and
    no other).

    The Publisher prepares the title, description and tags from the script and says READY
    or HOLD. A HOLD keeps the candidate out until the Director lifts it; the five gates
    are checked by code either way. Without a language model the Publisher cannot do her
    work, and the studio does not publish with a bare title in her place.

    Which channel a film goes to is its storyboard's to say (`select_channel_for`): the
    serial's episode to Channel B, a factual short to Channel A. Measured before this: the
    stage took `ready[0]`, the first bound slot, for whatever film came first, so a studio
    with the serial's account bound and the main one not would have put a factual film on
    the serial's channel — the one mistake no later check can undo. A film whose slot is
    unbound goes nowhere and says which slot to bind; it is never sent to another channel.
    One film per channel per run; the next one waits for tomorrow.
    """
    with Session(engine) as session:
        slots = (
            session.scalar(
                select(func.count())
                .select_from(ChannelRecord)
                .where(ChannelRecord.platform == "YOUTUBE")
            )
            or 0
        )
        if not slots:
            return _outcome(SKIPPED, "Niciun canal configurat în studio.")
        # With no slot bound at all the stage cannot publish anything, and says so before it
        # looks for films: "nothing waiting" would be a false COMPLETED. Which slot a given
        # film needs is decided per film below; a connected account that no slot names is
        # never guessed to be a channel's.
        if not any(b.get("publisher_ready") for b in channel_bindings(engine).values()):
            return _outcome(
                SKIPPED,
                "Niciun slot de canal nu este legat de un cont YouTube conectat. Leagă-le în "
                "Distribuție → Sloturi de canal; publicarea și analytics folosesc legătura.",
            )
        # Which films are no longer the day's to offer (PUB-02). A film on its channel or on
        # its way there (the live states), one the watchdog is settling (FAILED_RETRYABLE:
        # its retry asks the channel first, and a second intent beside it could put the film
        # up twice), one handed to the Owner (NEEDS_RECONCILIATION: it may be on the
        # channel), and one YouTube rejected, failed or saw deleted (the same file would be
        # refused again). Everything else is offered again: a BLOCKED_GATE refusal (the gate
        # is asked again below, so a refusal that still holds still refuses), and a
        # FAILED_FINAL upload that left nothing on the channel. Measured before this: every
        # publication row but BLOCKED_GATE kept the film out for good.
        published_assets = set(
            session.scalars(
                select(PublicationRecord.media_asset_id).where(
                    PublicationRecord.status.in_(
                        [*LIVE_PUBLICATION_STATES, *SETTLING_ELSEWHERE_STATES]
                    )
                    | PublicationRecord.remote_upload_status.in_(sorted(REMOTE_REJECTED_STATES))
                )
            )
        )
        # A film the Director rejected stays out of the queue; the next one comes forward.
        rejected_assets = _viewing_rejected(session)
        # The queue holds files, but the channel receives films. One film rendered four times
        # is four QC-passed assets: publishing them in turn would put the same video on the
        # channel four times, once per day. So the queue is collapsed to one entry per film —
        # the newest render of it — and a film its channel already carries is not a candidate
        # at all (checked below, once the film's channel is known). The gate refuses a
        # duplicate as well; this is what lets the stage walk past it to the next real film
        # instead of stopping on a refusal.
        offered: set[str] = set()
        candidates: list[tuple[str, list[str]]] = []
        for report in session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.status == "PASSED")
            .order_by(QualityControlReport.verified_at.desc())
        ):
            if report.media_asset_id in published_assets:
                continue
            if report.media_asset_id in rejected_assets:
                continue
            if only_assets is not None and report.media_asset_id not in only_assets:
                continue
            script_id, storyboard_id = film_identity(session, report.media_asset_id)
            keys = [key for key in (script_id, storyboard_id) if key is not None]
            if any(key in offered for key in keys):
                continue  # an older render of a film already queued above
            offered.update(keys)
            candidates.append((report.media_asset_id, keys))

    if not candidates:
        return _outcome(COMPLETED, "Niciun material aprobat de QC în așteptarea publicării.")

    environment = studio_environment(engine)
    published: list[dict[str, Any]] = []
    not_published: list[dict[str, Any]] = []
    served: set[str] = set()
    for asset_id, keys in candidates:
        route = select_channel_for(engine, asset_id)
        if route["status"] != ROUTE_SELECTED:
            not_published.append(
                {
                    "asset_id": asset_id,
                    "status": SKIPPED,
                    "reason": route["reason"],
                    "channel_type": route["channel_type"],
                }
            )
            continue
        channel_id = route["channel_id"]
        if channel_id in served:
            continue  # one film per channel per run; this one waits for tomorrow
        with Session(engine) as session:
            carried = published_films(session, channel_id)
        if any(key in carried for key in keys):
            continue  # already on this channel, under whatever file name
        outcome = _publish_one(
            engine, vault, registry, language, ffmpeg_path, footer, asset_id, route, environment
        )
        if "published" in outcome:
            served.add(channel_id)
            published.append(outcome["published"])
        else:
            not_published.append({"asset_id": asset_id, **outcome})

    if published:
        reason = " ".join(
            f"Pe {p['channel_name']}: {publication_status(p['publication_status'])} "
            f"({privacy(p['release_privacy'])}"
            + (f", programat {p['publish_at']}" if p["publish_at"] else "")
            + (
                "; YouTube l-a păstrat privat: proiectul Google nu a trecut auditul"
                if p.get("remote_privacy_status") == "private"
                and p["release_privacy"] in ("public", "unlisted")
                and not p["publish_at"]
                else ""
            )
            + (f"; {p['visibility_reason']}" if p.get("private_until_licensed") else "")
            + ")."
            for p in published
        )
        if not_published:
            reason += (
                f" {count(len(not_published), 'nepublicat', 'nepublicate')}: "
                f"{not_published[0]['reason']}"
            )
        first = published[0]
        return _outcome(
            COMPLETED,
            reason,
            published=published,
            not_published=not_published,
            publication_id=first["publication_id"],
            publication_status=first["publication_status"],
            title=first["title"],
        )
    if not not_published:
        # Every candidate was a film its channel already carries, or a second film for a
        # channel served today.
        return _outcome(COMPLETED, "Niciun material aprobat de QC în așteptarea publicării.")
    # Nothing went out. A content outcome — the Director's refusal, a HOLD, the gate's
    # reasons — is the day's work done; a stage that could not work at all is SKIPPED, and
    # the first reason says why (an unbound slot, no model, no account).
    decided = [entry for entry in not_published if entry["status"] == COMPLETED]
    chosen = decided[0] if decided else not_published[0]
    artefacts = {
        key: value for key, value in chosen.items() if key not in ("status", "reason", "asset_id")
    }
    return _outcome(chosen["status"], chosen["reason"], not_published=not_published, **artefacts)


# ---------------------------------------------------------------------- serial queue --


def _serial_queue(
    engine: Engine, registry: ProviderRegistry, settings: Settings, vault: Any = None
) -> dict[str, Any]:
    """The Office Serial's day: project, write, review, approve under policy, storyboard.

    The stage used to write an episode and stop, so the serial ended as text. It now runs
    `app.story.serial_stage.run_serial_stage`, which carries the newest closed day without
    an episode through to an APPROVED storyboard for Channel B; the media stage, next in
    the runbook, films it in the same run. The stage reports SKIPPED without a language
    model, COMPLETED for every content outcome (a quiet day, a refused draft, an episode
    left for the Owner), and raises only for a provider or network fault.
    """
    return run_serial_stage(engine, registry, settings, vault)


def _serial_next(
    engine: Engine, registry: ProviderRegistry, settings: Settings, vault: Any = None
) -> dict[str, Any]:
    """Tomorrow's script, from today's log closed a moment before: written, read and
    approved under the Owner's policy, never storyboarded (`run_serial_next_stage`). The
    next run's serial stage readies it and that run's media stage films it."""
    return run_serial_next_stage(engine, registry, settings, vault)


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
            close = {"error": sentence(error_words(exc))[:200], **error_fields(exc)}
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
            f"{count(len(filed), 'raport depus', 'rapoarte depuse')}; Directorul nu "
            f"{'îl' if len(filed) == 1 else 'le'} poate revizui fără un model de limbaj.",
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
            f"Revizuirea de seară nu a putut rula: {error_words(exc)[:300]}. Rapoartele "
            f"({len(filed)}) sunt în inbox, nedecise. Verifică modelul meu în Setări sau "
            "spune-mi ce să fac cu ele. — Sarah",
            str(uuid4()),
        )
        return _outcome(
            COMPLETED,
            f"{count(len(filed), 'raport depus', 'rapoarte depuse')}; revizuirea "
            f"Directorului a fost respinsă: {error_words(exc)}."[:300],
            reports=len(filed),
            review_rejected=str(exc)[:200],
            **error_fields(exc),
        )
    if review.get("blocked"):
        return _outcome(
            COMPLETED,
            f"{count(len(filed), 'raport depus', 'rapoarte depuse')}; Directorul a "
            f"escaladat: {review['blocked']}"[:300],
            reports=len(filed),
            blocked=review["blocked"],
        )
    return _outcome(
        COMPLETED,
        f"{count(len(filed), 'raport depus', 'rapoarte depuse')}; Directorul a revizuit "
        f"{count(review.get('reviewed', 0), 'mesaj', 'mesaje')}, "
        f"{count(len(review.get('applied', [])), 'decizie', 'decizii')}."
        + (
            f" {count(archived, 'raport vechi arhivat', 'rapoarte vechi arhivate')}."
            if archived
            else ""
        ),
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
            # What the stage is, in the risk terms the Owner's mode understands (see
            # STAGE_ACTIONS). A stage above what the mode allows could not run, which is
            # SKIPPED and not BLOCKED: BLOCKED ends the day, and a mode is not an incident —
            # the stages below it that the mode does allow still do their work.
            #
            # The asking is left to the stages that know what they are asking about.
            # Measured before this: the wrapper raised the SUPERVISED approval itself, with
            # no film on it, and the stage never ran — so one answer would have covered
            # every film the day had, and a request was raised even on a day with nothing to
            # publish. `ask_owner=False` asks the mode the same question and writes nothing;
            # a stage the mode refuses outright is still refused here, and the stage that the
            # mode would merely ask about goes on to ask per film, with that film's name, its
            # price and its channel policy on the request.
            action, tier = STAGE_ACTIONS[name]
            refusal = mode_refusal(engine, action, tier, ask_owner=False)
            if refusal is not None:
                outcome = _outcome(
                    SKIPPED,
                    refusal["reason"],
                    autonomy_mode=refusal["mode"],
                    risk_tier=refusal["tier"],
                    governance_status=refusal["status"],
                    approval_id=refusal["approval_id"],
                )
                outcomes[name] = outcome
                return outcome
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
                settings=settings,
            ),
        ),
        "media": keep("media", lambda: _media(engine, settings, vault, registry)),
        "edit_and_qc": keep(
            "edit_and_qc", lambda: _edit_and_qc(engine, registry, settings, vault=vault)
        ),
        "publish": keep(
            "publish",
            lambda: _publish(
                engine,
                vault,
                registry,
                settings.content_language,
                settings.ffmpeg_path,
                footer=publication_footer(
                    engine, settings.ai_disclosure_url, settings.creator_channel_title
                ),
            ),
        ),
        # Kept like the others so the Owner's mode is asked about it too; its own outcome
        # lands in the day's record after it has read the others', which is harmless and
        # keeps every stage of the day under one rule.
        "post_run": keep("post_run", lambda: _post_run(engine, registry, outcomes)),
        "serial_queue": keep(
            "serial_queue", lambda: _serial_queue(engine, registry, settings, vault)
        ),
        "serial_next": keep("serial_next", lambda: _serial_next(engine, registry, settings, vault)),
    }
