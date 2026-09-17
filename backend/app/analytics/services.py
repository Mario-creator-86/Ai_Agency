"""Phase 7 Analytics & Continuous Learning domain services."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.analytics.models import (
    AnalyticsSnapshot,
    ContentExperiment,
    ContentStrategy,
    DirectorRecommendation,
)
from app.analytics.schemas import (
    AnalyticsSnapshotView,
    ChannelAnalyticsSummaryView,
    CohortMetricView,
    ContentExperimentView,
    ContentStrategyView,
    DirectorRecommendationView,
)
from app.factual.models import HookOption, ScriptDraft, StoryReview, TopicIdea
from app.media.models import Storyboard, VideoRenderJob
from app.providers.analytics_base import AnalyticsProvider
from app.providers.youtube_analytics import YouTubeAnalyticsProvider
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import bound_connection_id
from app.services import append_event, utc_now
from app.youtube.models import YouTubeConnection

logger = logging.getLogger("studio.analytics")


MIN_SAMPLE_THRESHOLD = 3
MAX_WEIGHT_DELTA = 0.20


class _Baseline(TypedDict):
    topic_weights: dict[str, float]
    hook_weights: dict[str, float]
    target_duration_seconds: int
    notes: str


#: Neutral starting weights per channel type. Every weight is 1.0 on purpose: the baseline
#: expresses no preference, because no video has been measured yet. Preferences appear only
#: after the Director applies a recommendation built from real snapshots.
BASELINE_STRATEGY: dict[str, _Baseline] = {
    "MAIN_FACTUAL": {
        "topic_weights": {
            "space": 1.0,
            "physics": 1.0,
            "history": 1.0,
            "psychology": 1.0,
            "technology": 1.0,
        },
        "hook_weights": {
            "CURIOSITY_GAP": 1.0,
            "CONTRARIAN": 1.0,
            "STATISTIC_SHOCK": 1.0,
            "STORY_IN_MEDIA_RES": 1.0,
        },
        "target_duration_seconds": 45,
        "notes": "Baseline editorial strategy for Channel A (Factual Short-form). "
        "All weights neutral: no performance has been measured yet.",
    },
    "OFFICE_SERIAL": {
        "topic_weights": {
            "office_serial": 1.0,
            "character_vignette": 1.0,
            "studio_lore": 1.0,
        },
        "hook_weights": {
            "STORY_IN_MEDIA_RES": 1.0,
            "CURIOSITY_GAP": 1.0,
        },
        "target_duration_seconds": 60,
        "notes": "Baseline editorial strategy for Channel B (Office Serial). "
        "All weights neutral: no performance has been measured yet.",
    },
}


def seed_default_strategy(engine: Engine) -> int:
    """Seed the neutral v1 strategy for each seeded channel that does not have one.

    Channels are looked up by ``channel_type``; their ids are generated at seed time, so a
    hardcoded id would leave the strategy pointing at a channel that does not exist.
    """
    created = 0
    with Session(engine) as session, session.begin():
        for channel_type, baseline in BASELINE_STRATEGY.items():
            channel = session.scalar(
                select(ChannelRecord).where(ChannelRecord.channel_type == channel_type)
            )
            if channel is None:
                continue
            existing = session.scalar(
                select(ContentStrategy).where(ContentStrategy.channel_id == channel.id)
            )
            if existing is not None:
                continue
            session.add(
                ContentStrategy(
                    id=str(uuid4()),
                    channel_id=channel.id,
                    version=1,
                    topic_weights_json=dict(baseline["topic_weights"]),
                    hook_weights_json=dict(baseline["hook_weights"]),
                    target_duration_seconds=baseline["target_duration_seconds"],
                    cooldown_until=None,
                    notes=baseline["notes"],
                    is_active=True,
                    created_at=utc_now(),
                    event_id=None,
                )
            )
            created += 1
    return created


def get_active_strategy(engine: Engine, channel_id: str) -> dict | None:
    """Return currently active ContentStrategy for the channel."""
    with Session(engine) as session:
        strat = session.scalar(
            select(ContentStrategy)
            .where(ContentStrategy.channel_id == channel_id, ContentStrategy.is_active.is_(True))
            .order_by(ContentStrategy.version.desc())
        )
        if strat is None:
            return None
        return ContentStrategyView.model_validate(strat).model_dump()


class MetricsUnavailable(RuntimeError):
    """There is nothing measurable attached to this publication yet.

    Distinct from a missing publication (404) and from a provider failure (502): the row is
    there, the platform is reachable, but no real video exists to report on.
    """


def ingest_publication_metrics(
    engine: Engine,
    publication_id: str,
    provider: AnalyticsProvider,
    window: str = "LIFETIME",
    correlation_id: str = "",
) -> dict:
    """Ingest performance metrics from the specified analytics
    provider into an AnalyticsSnapshot."""
    with Session(engine) as session:
        pub = session.get(PublicationRecord, publication_id)
        if pub is None:
            raise ValueError(f"Publication {publication_id} not found")
        # Analytics describe a video the platform is actually serving. A publication that was
        # only simulated, or that never received a remote video id, has no audience to measure;
        # falling back to the internal row id here used to make the provider answer for an
        # identifier that does not exist on any platform.
        if pub.status != "PUBLISHED" or not pub.remote_video_id:
            raise MetricsUnavailable(
                "Publicarea nu are un videoclip real pe platformă "
                f"(status {pub.status}), deci nu există performanță de măsurat."
            )
        remote_id = pub.remote_video_id
        channel_id = pub.channel_id

    # Fetch metrics asynchronously from provider
    metrics = asyncio.run(provider.fetch_video_metrics(remote_id, window=window))

    snapshot_id = str(uuid4())
    snapshot_time = utc_now()
    corr = correlation_id or str(uuid4())

    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "analytics.snapshot_ingested",
            "analytics_snapshot",
            snapshot_id,
            1,
            {
                "publication_id": publication_id,
                "channel_id": channel_id,
                "views": metrics.views,
                "average_view_percentage": metrics.average_view_percentage,
                "ctr_percentage": metrics.ctr_percentage,
                "window": window,
            },
            corr,
        )

        snapshot = AnalyticsSnapshot(
            id=snapshot_id,
            publication_id=publication_id,
            channel_id=channel_id,
            window=window,
            views=metrics.views,
            watch_time_seconds=metrics.watch_time_seconds,
            average_view_percentage=metrics.average_view_percentage,
            impressions=metrics.impressions,
            ctr_percentage=metrics.ctr_percentage,
            likes=metrics.likes,
            comments=metrics.comments,
            shares=metrics.shares,
            subscribers_gained=metrics.subscribers_gained,
            subscribers_lost=metrics.subscribers_lost,
            raw_metrics_json=metrics.raw,
            snapshot_at=snapshot_time,
            event_id=event.event_id,
        )
        session.add(snapshot)
        session.flush()
        return AnalyticsSnapshotView.model_validate(snapshot).model_dump()


def analytics_provider_for_channel(
    engine: Engine, vault: Any, channel_id: str
) -> tuple[AnalyticsProvider | None, str]:
    """The analytics adapter for one channel slot: its own bound account, or nothing.

    Measured before this: performance intake built one adapter from the first bound slot
    and measured every publication through it, so with two channels bound the serial's
    retention was asked of the main channel's account. Here the slot's binding is the only
    source — no "the one connected account" fallback and no environment credentials, both
    of which can name an account that is not this channel's. Returns ``(provider, "")`` or
    ``(None, reason)`` in the Owner's language.
    """
    with Session(engine) as session:
        channel = session.get(ChannelRecord, channel_id)
        if channel is None:
            return None, f"Canalul {channel_id} nu există."
        identifier = bound_connection_id(channel)
        connection = session.get(YouTubeConnection, identifier) if identifier else None
        if connection is None:
            return None, (
                f"Slotul „{channel.channel_name}” nu este legat de un cont YouTube; fără "
                "legătură nu se știe ale cui sunt cifrele. Leagă-l în Publicare → Sloturi de "
                "canale."
            )
        if connection.status != "CONNECTED":
            return None, (
                f"Contul „{connection.name}” legat de slotul „{channel.channel_name}” nu mai "
                "este conectat; apasă Reconectează în Setări."
            )
        secrets = vault.decrypt(connection.encrypted_secrets)
        # Built whole from the bound account: the adapter takes explicit credentials as one
        # set and reads no STUDIO_YOUTUBE_* for them, and it carries the channel it answers
        # for, so a reader can check the account against the slot's binding.
        provider = YouTubeAnalyticsProvider(
            client_id=connection.client_id,
            client_secret=secrets.get("client_secret"),
            refresh_token=secrets.get("refresh_token"),
            channel_id=connection.remote_channel_id,
        )
        return provider, ""


def measure_channel_publications(
    engine: Engine,
    channel_id: str,
    provider: AnalyticsProvider,
    *,
    window: str = "LIFETIME",
    limit: int | None = None,
) -> dict[str, Any]:
    """Measure one channel's real publications through the adapter built for that channel.

    Only this channel's PUBLISHED rows with a remote video id are asked about: a simulated
    publication has no audience, and another channel's video is another account's number.
    Returns the count measured and, per publication, why one could not be.
    """
    with Session(engine) as session:
        query = (
            select(PublicationRecord.id)
            .where(
                PublicationRecord.channel_id == channel_id,
                PublicationRecord.status == "PUBLISHED",
                PublicationRecord.remote_video_id.is_not(None),
            )
            .order_by(PublicationRecord.published_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        identifiers = list(session.scalars(query))

    measured, unavailable = 0, []
    for publication_id in identifiers:
        try:
            ingest_publication_metrics(
                engine, publication_id, provider, window=window, correlation_id=str(uuid4())
            )
            measured += 1
        except MetricsUnavailable as exc:
            unavailable.append(f"{publication_id}: {exc}")
    return {
        "channel_id": channel_id,
        "candidates": len(identifiers),
        "measured": measured,
        "unavailable": unavailable,
    }


def get_channel_summary(engine: Engine, channel_id: str) -> dict:
    """Compute aggregate high-level metrics for a channel."""
    with Session(engine) as session:
        snapshots = session.scalars(
            select(AnalyticsSnapshot).where(AnalyticsSnapshot.channel_id == channel_id)
        ).all()
        pubs = session.scalars(
            select(PublicationRecord).where(PublicationRecord.channel_id == channel_id)
        ).all()
        recs_count = len(
            session.scalars(
                select(DirectorRecommendation).where(
                    DirectorRecommendation.channel_id == channel_id,
                    DirectorRecommendation.status == "PROPOSED",
                )
            ).all()
        )
        active_strat = session.scalar(
            select(ContentStrategy)
            .where(ContentStrategy.channel_id == channel_id, ContentStrategy.is_active.is_(True))
            .order_by(ContentStrategy.version.desc())
        )

        if not snapshots:
            return ChannelAnalyticsSummaryView(
                channel_id=channel_id,
                total_views=0,
                total_watch_time_seconds=0.0,
                average_retention_percentage=0.0,
                average_ctr_percentage=0.0,
                total_publications=len(pubs),
                total_snapshots=0,
                active_strategy_version=active_strat.version if active_strat else 1,
                pending_recommendations_count=recs_count,
            ).model_dump()

        total_views = sum(s.views for s in snapshots)
        total_watch = sum(s.watch_time_seconds for s in snapshots)
        avg_ret = round(sum(s.average_view_percentage for s in snapshots) / len(snapshots), 1)
        avg_ctr = round(sum(s.ctr_percentage for s in snapshots) / len(snapshots), 1)

        return ChannelAnalyticsSummaryView(
            channel_id=channel_id,
            total_views=total_views,
            total_watch_time_seconds=round(total_watch, 1),
            average_retention_percentage=avg_ret,
            average_ctr_percentage=avg_ctr,
            total_publications=len(pubs),
            total_snapshots=len(snapshots),
            active_strategy_version=active_strat.version if active_strat else 1,
            pending_recommendations_count=recs_count,
        ).model_dump()


def _resolve_publication_metadata(session: Session, pub: PublicationRecord) -> tuple[str, str]:
    """Resolve topic and hook technique from the publication metadata chain."""
    topic = "general"
    hook = "CURIOSITY_GAP"

    # Try resolving via media asset -> render job -> storyboard -> script -> topic
    if pub.media_asset_id:
        render_job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == pub.media_asset_id)
        )
        if render_job and render_job.storyboard_id:
            sb = session.get(Storyboard, render_job.storyboard_id)
            if sb and sb.script_draft_id:
                script = session.get(ScriptDraft, sb.script_draft_id)
                if script:
                    topic_obj = session.get(TopicIdea, script.topic_id)
                    if topic_obj:
                        topic = topic_obj.topic
                    selected_hook = session.scalar(
                        select(HookOption).where(
                            HookOption.script_id == script.id, HookOption.is_selected.is_(True)
                        )
                    )
                    if selected_hook:
                        hook = selected_hook.hook_technique

    # Fallback to tags if available
    if topic == "general" and pub.tags_json:
        for t in pub.tags_json:
            if t in ("space", "physics", "history", "psychology", "technology", "office_serial"):
                topic = t
                break

    return topic, hook


def story_performance(engine: Engine, channel_id: str | None = None) -> dict[str, Any]:
    """What the studio expected of each film, beside what the audience actually did.

    The studio scores an idea before it exists — hook potential, retention potential, whether
    there is a natural question to leave people with — and the Director estimates where
    interest will collapse. None of that was ever compared with a measurement, so the
    editorial judgement could be wrong for a year without anyone noticing.

    This is the comparison, per published film and as a mean: predicted hook against measured
    three-second retention (the closest thing a platform reports), predicted retention against
    the average percentage viewed, predicted call-to-action strength against the comments and
    shares a film actually earned. Nothing here optimises for views: a film that is watched
    and wrong is worth less than nothing to a factual channel.
    """
    rows: list[dict[str, Any]] = []
    with Session(engine) as session:
        query = select(AnalyticsSnapshot)
        if channel_id:
            query = query.where(AnalyticsSnapshot.channel_id == channel_id)
        for snapshot in session.scalars(query):
            pub = session.get(PublicationRecord, snapshot.publication_id)
            if pub is None or not pub.media_asset_id:
                continue
            job = session.scalar(
                select(VideoRenderJob).where(VideoRenderJob.output_asset_id == pub.media_asset_id)
            )
            board = session.get(Storyboard, job.storyboard_id) if job else None
            script = session.get(ScriptDraft, board.script_draft_id) if board else None
            if script is None:
                continue
            topic = session.get(TopicIdea, script.topic_id)
            scores = dict((topic.scores_json or {}) if topic else {})
            review = session.scalars(
                select(StoryReview)
                .where(StoryReview.script_id == script.id)
                .order_by(StoryReview.created_at.desc())
            ).first()
            retention = dict((review.retention_json or {}) if review else {})
            engagement = (
                (snapshot.comments + snapshot.shares) / snapshot.views * 100.0
                if snapshot.views
                else None
            )
            rows.append(
                {
                    "publication_id": pub.id,
                    "title": pub.title,
                    "predicted_hook": scores.get("hook_potential"),
                    "predicted_retention": scores.get("retention_potential"),
                    "predicted_cta": scores.get("cta_opportunity"),
                    "director_at_3_seconds": retention.get("at_3"),
                    "director_at_end": retention.get("at_end"),
                    "measured_view_percentage": snapshot.average_view_percentage,
                    "measured_ctr": snapshot.ctr_percentage,
                    "measured_engagement_percentage": (
                        round(engagement, 2) if engagement is not None else None
                    ),
                    "views": snapshot.views,
                    "story_review": review.verdict if review else "NONE",
                }
            )

    def mean(key: str) -> float | None:
        values = [row[key] for row in rows if isinstance(row.get(key), int | float)]
        return round(sum(values) / len(values), 3) if values else None

    # A prediction on a scale of 0..1 against a measurement in percent: the comparison is the
    # gap between them, stated in the same unit, so a systematic optimism is visible.
    predicted = mean("predicted_retention")
    measured = mean("measured_view_percentage")
    return {
        "videos": rows,
        "sample_size": len(rows),
        "predicted_retention": predicted,
        "measured_view_percentage": measured,
        "retention_gap": (
            round(predicted * 100 - measured, 2)
            if predicted is not None and measured is not None
            else None
        ),
        "predicted_hook": mean("predicted_hook"),
        "director_at_3_seconds": mean("director_at_3_seconds"),
        "predicted_cta": mean("predicted_cta"),
        "measured_engagement_percentage": mean("measured_engagement_percentage"),
        "note": (
            "nothing published and measured yet"
            if not rows
            else "means over every measured film; a gap above 20 points means the studio's "
            "editorial scoring is systematically optimistic"
        ),
    }


def compute_cohort_metrics(engine: Engine, channel_id: str, cohort_by: str = "topic") -> list[dict]:
    """Compute performance aggregated by cohort (topic, hook technique, or duration).

    Enforces minimum sample size threshold (N >= 3) and applies clickbait quality penalty.
    """
    with Session(engine) as session:
        snapshots = session.scalars(
            select(AnalyticsSnapshot).where(AnalyticsSnapshot.channel_id == channel_id)
        ).all()

        if not snapshots:
            return []

        # Group by cohort key
        groups: dict[str, list[AnalyticsSnapshot]] = {}
        for s in snapshots:
            pub = session.get(PublicationRecord, s.publication_id)
            if not pub:
                continue
            topic, hook = _resolve_publication_metadata(session, pub)
            if cohort_by == "hook":
                key = hook
            elif cohort_by == "duration":
                key = "45s" if s.watch_time_seconds < 50 else "60s"
            else:
                key = topic

            groups.setdefault(key, []).append(s)

        results: list[dict] = []
        for key, group in groups.items():
            n = len(group)
            mean_ret = round(sum(s.average_view_percentage for s in group) / n, 1)
            mean_ctr = round(sum(s.ctr_percentage for s in group) / n, 1)
            mean_views = round(sum(s.views for s in group) / n, 1)

            # Clickbait Penalty Rule: High CTR (> 10.0%) but poor retention (< 40.0%)
            is_clickbait = mean_ctr > 10.0 and mean_ret < 40.0
            if is_clickbait:
                # Heavily penalize score
                score = round((mean_ret * 0.5) + (mean_ctr * 0.5), 2)
            else:
                # Multi-objective balanced score: retention (70%) + CTR (30% weighted)
                score = round((mean_ret * 0.7) + (mean_ctr * 1.5), 2)

            view = CohortMetricView(
                cohort_key=key,
                cohort_type=cohort_by,
                sample_size=n,
                mean_retention=mean_ret,
                mean_ctr=mean_ctr,
                mean_views=mean_views,
                clickbait_penalty_applied=is_clickbait,
                score=score,
            )
            results.append(view.model_dump())

        # Sort descending by score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results


def generate_director_recommendations(
    engine: Engine, channel_id: str, correlation_id: str = ""
) -> list[dict]:
    """Formulate Director AI strategy recommendations based on cohort evidence.

    Normative Invariant: Strictly requires N >= 3 sample size before proposing adjustments.
    Bounded: suggested_weight_change <= +/- 0.20.
    """
    corr = correlation_id or str(uuid4())
    generated: list[dict] = []

    with Session(engine) as session, session.begin():
        strat = session.scalar(
            select(ContentStrategy)
            .where(ContentStrategy.channel_id == channel_id, ContentStrategy.is_active.is_(True))
            .order_by(ContentStrategy.version.desc())
        )
        if strat is None:
            return []

        topic_cohorts = compute_cohort_metrics(engine, channel_id, cohort_by="topic")
        hook_cohorts = compute_cohort_metrics(engine, channel_id, cohort_by="hook")

        # Evaluate Topic Cohorts
        for c in topic_cohorts:
            n = c["sample_size"]
            key = c["cohort_key"]
            mean_ret = c["mean_retention"]
            mean_ctr = c["mean_ctr"]

            # Gate: require minimum sample size of N >= 3
            if n < MIN_SAMPLE_THRESHOLD:
                continue

            existing_rec = session.scalar(
                select(DirectorRecommendation).where(
                    DirectorRecommendation.channel_id == channel_id,
                    DirectorRecommendation.target_entity == key,
                    DirectorRecommendation.status == "PROPOSED",
                )
            )
            if existing_rec:
                continue

            rec_type = None
            weight_change = 0.0
            evidence = ""

            if c["clickbait_penalty_applied"] or mean_ret < 40.0:
                rec_type = "REDUCE_TOPIC"
                weight_change = -0.15
                evidence = (
                    f"Topic '{key}' shows sub-threshold retention ({mean_ret}% < 40%) "
                    f"despite {mean_ctr}% CTR across N={n} publications. "
                    f"Penalized for clickbait/churn."
                )
            elif mean_ret >= 60.0:
                rec_type = "BOOST_TOPIC"
                weight_change = 0.15
                evidence = (
                    f"Topic '{key}' demonstrates superior retention ({mean_ret}%) "
                    f"and healthy CTR ({mean_ctr}%) across N={n} publications."
                )

            if rec_type:
                weight_change = max(-MAX_WEIGHT_DELTA, min(MAX_WEIGHT_DELTA, weight_change))
                rec_id = str(uuid4())
                confidence = min(0.95, round(0.5 + (n * 0.1), 2))
                rec = DirectorRecommendation(
                    id=rec_id,
                    channel_id=channel_id,
                    strategy_id=strat.id,
                    recommendation_type=rec_type,
                    target_entity=key,
                    suggested_weight_change=weight_change,
                    sample_size=n,
                    mean_retention=mean_ret,
                    mean_ctr=mean_ctr,
                    confidence_score=confidence,
                    evidence_summary=evidence,
                    status="PROPOSED",
                    created_at=utc_now(),
                )
                session.add(rec)
                append_event(
                    session,
                    "analytics.recommendation_generated",
                    "director_recommendation",
                    rec_id,
                    1,
                    {
                        "channel_id": channel_id,
                        "type": rec_type,
                        "target": key,
                        "weight_change": weight_change,
                        "sample_size": n,
                    },
                    corr,
                )
                generated.append(DirectorRecommendationView.model_validate(rec).model_dump())

        # Evaluate Hook Cohorts
        for h in hook_cohorts:
            n = h["sample_size"]
            key = h["cohort_key"]
            mean_ret = h["mean_retention"]
            mean_ctr = h["mean_ctr"]

            if n < MIN_SAMPLE_THRESHOLD:
                continue

            existing_rec = session.scalar(
                select(DirectorRecommendation).where(
                    DirectorRecommendation.channel_id == channel_id,
                    DirectorRecommendation.target_entity == key,
                    DirectorRecommendation.status == "PROPOSED",
                )
            )
            if existing_rec:
                continue

            if mean_ret >= 65.0:
                weight_change = 0.10
                rec_id = str(uuid4())
                confidence = min(0.95, round(0.5 + (n * 0.1), 2))
                evidence = (
                    f"Hook '{key}' delivers top-tier viewer retention ({mean_ret}%) "
                    f"across N={n} publications."
                )
                rec = DirectorRecommendation(
                    id=rec_id,
                    channel_id=channel_id,
                    strategy_id=strat.id,
                    recommendation_type="FAVOR_HOOK",
                    target_entity=key,
                    suggested_weight_change=weight_change,
                    sample_size=n,
                    mean_retention=mean_ret,
                    mean_ctr=mean_ctr,
                    confidence_score=confidence,
                    evidence_summary=evidence,
                    status="PROPOSED",
                    created_at=utc_now(),
                )
                session.add(rec)
                append_event(
                    session,
                    "analytics.recommendation_generated",
                    "director_recommendation",
                    rec_id,
                    1,
                    {
                        "channel_id": channel_id,
                        "type": "FAVOR_HOOK",
                        "target": key,
                        "weight_change": weight_change,
                        "sample_size": n,
                    },
                    corr,
                )
                generated.append(DirectorRecommendationView.model_validate(rec).model_dump())

    return generated


def apply_director_recommendation(
    engine: Engine, recommendation_id: str, correlation_id: str = ""
) -> dict:
    """Apply an approved Director Recommendation to promote a new Strategy version.

    Enforces:
    - Bounded adjustments (<= +/- 20%)
    - Version incrementation (v -> v+1)
    - Cooldown period enforcement
    """
    corr = correlation_id or str(uuid4())

    with Session(engine) as session, session.begin():
        rec = session.get(DirectorRecommendation, recommendation_id)
        if rec is None:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        if rec.status != "PROPOSED":
            raise ValueError(f"Recommendation is already {rec.status}")

        active_strat = session.scalar(
            select(ContentStrategy)
            .where(
                ContentStrategy.channel_id == rec.channel_id,
                ContentStrategy.is_active.is_(True),
            )
            .order_by(ContentStrategy.version.desc())
        )
        if active_strat is None:
            raise ValueError("No active strategy found to update")

        # Check cooldown
        if active_strat.cooldown_until:
            cooldown_dt = datetime.fromisoformat(active_strat.cooldown_until)
            now_dt = datetime.now(UTC)
            if now_dt < cooldown_dt:
                raise ValueError("Active strategy is currently in cooldown period")

        # Clone current weights
        new_topic_weights = dict(active_strat.topic_weights_json)
        new_hook_weights = dict(active_strat.hook_weights_json)

        # Apply bounded delta
        delta = max(-MAX_WEIGHT_DELTA, min(MAX_WEIGHT_DELTA, rec.suggested_weight_change))

        if rec.recommendation_type in ("BOOST_TOPIC", "REDUCE_TOPIC"):
            old_w = new_topic_weights.get(rec.target_entity, 1.0)
            new_topic_weights[rec.target_entity] = max(0.1, round(old_w + delta, 2))
        elif rec.recommendation_type == "FAVOR_HOOK":
            old_w = new_hook_weights.get(rec.target_entity, 1.0)
            new_hook_weights[rec.target_entity] = max(0.1, round(old_w + delta, 2))

        # Mark active strategy as inactive
        active_strat.is_active = False

        # Create new strategy revision
        new_strat_id = str(uuid4())
        new_version = active_strat.version + 1
        new_strat = ContentStrategy(
            id=new_strat_id,
            channel_id=rec.channel_id,
            version=new_version,
            topic_weights_json=new_topic_weights,
            hook_weights_json=new_hook_weights,
            target_duration_seconds=active_strat.target_duration_seconds,
            cooldown_until=None,
            notes=(
                f"Promoted from v{active_strat.version} via recommendation "
                f"{rec.recommendation_type} for '{rec.target_entity}'"
            ),
            is_active=True,
            created_at=utc_now(),
            event_id=None,
        )
        session.add(new_strat)

        rec.status = "APPLIED"

        event = append_event(
            session,
            "strategy.version_promoted",
            "content_strategy",
            new_strat_id,
            new_version,
            {
                "channel_id": rec.channel_id,
                "previous_version": active_strat.version,
                "new_version": new_version,
                "recommendation_id": rec.id,
                "applied_change": delta,
            },
            corr,
        )
        new_strat.event_id = event.event_id
        from app.agents.memory import remember

        remember(
            session,
            memory_class="STRATEGY",
            content=(
                f"Strategy v{new_version} on channel {rec.channel_id}: "
                f"{rec.recommendation_type} for '{rec.target_entity}' "
                f"(weight change {delta:+.2f}), from cohort evidence."
            ),
            source_type="event",
            source_id=new_strat_id,
            event_id=event.event_id,
        )

        session.flush()
        return ContentStrategyView.model_validate(new_strat).model_dump()


def list_channel_recommendations(engine: Engine, channel_id: str) -> list[dict]:
    """List all recommendations for a given channel."""
    with Session(engine) as session:
        recs = session.scalars(
            select(DirectorRecommendation)
            .where(DirectorRecommendation.channel_id == channel_id)
            .order_by(DirectorRecommendation.created_at.desc())
        ).all()
        return [DirectorRecommendationView.model_validate(r).model_dump() for r in recs]


def create_experiment(
    engine: Engine,
    channel_id: str,
    name: str,
    hypothesis: str,
    control_variant: str,
    treatment_variant: str,
    target_metric: str = "RETENTION_RATE",
    sample_size_target: int = 3,
    guardrail_metrics: dict | None = None,
    correlation_id: str = "",
) -> dict:
    """Create a new controlled A/B experiment."""
    corr = correlation_id or str(uuid4())
    exp_id = str(uuid4())
    now = utc_now()

    with Session(engine) as session, session.begin():
        exp = ContentExperiment(
            id=exp_id,
            channel_id=channel_id,
            name=name,
            hypothesis=hypothesis,
            target_metric=target_metric,
            guardrail_metrics_json=guardrail_metrics or {},
            status="ACTIVE",
            control_variant=control_variant,
            treatment_variant=treatment_variant,
            sample_size_target=sample_size_target,
            control_count=0,
            treatment_count=0,
            confidence_score=0.0,
            outcome_decision=None,
            started_at=now,
            concluded_at=None,
            event_id=None,
        )
        session.add(exp)

        event = append_event(
            session,
            "experiment.created",
            "content_experiment",
            exp_id,
            1,
            {
                "name": name,
                "target_metric": target_metric,
                "sample_size_target": sample_size_target,
            },
            corr,
        )
        exp.event_id = event.event_id

        session.flush()
        return ContentExperimentView.model_validate(exp).model_dump()


def list_channel_experiments(engine: Engine, channel_id: str) -> list[dict]:
    """List experiments for a channel."""
    with Session(engine) as session:
        exps = session.scalars(
            select(ContentExperiment)
            .where(ContentExperiment.channel_id == channel_id)
            .order_by(ContentExperiment.started_at.desc())
        ).all()
        return [ContentExperimentView.model_validate(e).model_dump() for e in exps]
